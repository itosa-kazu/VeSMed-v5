"""One-pass judge materialization for the supplemental CONFIRM5 pack.

The frozen judge data for each C01--C05 replicate is materialized exactly once
in this process, then five fresh models are fit and evaluated sequentially:
F10, F14, F18, B02V2 and B03V2.  Only public training projections and public
histories cross the candidate boundary.  Candidate-facing objects are deep
copied per model so a malicious or buggy model cannot contaminate the next
model; models and ``SharedPatientState`` objects are never shared.

The CLI defaults to the complete frozen W01--W20 allocation (train32,
validation8 authority binding, sealed-test16, pair limit2).  Importing this
module or running its tests does not issue seeds and does not execute the
formal pack.
"""

from __future__ import annotations

import argparse
import copy
import gzip
import json
import os
import shutil
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

from . import benchmark_v1_runner as _runner
from .benchmark_v1_freeze import (
    FREEZE_FILENAME,
    MODEL_SEEDS,
    REPLICATE_IDS,
    SPLIT_EPISODES_PER_PANEL,
)
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .postseal_confirm5 import (
    CONFIRM_ALIASES,
    DURABLE_SEAL_COMMIT,
    PURPOSE,
    commitment_digest,
    verify_commitment_bytes,
)
from .world_registry import WORLD_REGISTRY


BATCH_PROTOCOL = "ucm-postseal-confirm5-batch/1"
BATCH_MANIFEST_PROTOCOL = "ucm-postseal-confirm5-batch-manifest/1"
DEFAULT_RESULTS_ROOT = Path("results/unified_map/postseal_confirm5")
DEFAULT_ORACLE_WORKERS = 2


@dataclass(frozen=True, slots=True)
class CandidateSpec:
    family_code: str
    experiment_id: str
    parameters: dict[str, Any]

    def __post_init__(self) -> None:
        if (
            type(self.family_code) is not str
            or not self.family_code
            or type(self.experiment_id) is not str
            or not self.experiment_id
        ):
            raise ProtocolViolation("CONFIRM5 candidate spec identity is invalid")
        validate_json_like(self.parameters, path="CONFIRM5 candidate parameters")


CANDIDATE_SPECS = (
    CandidateSpec("F10", "POSTSEAL-CONFIRM5-F10", {}),
    CandidateSpec("F14", "POSTSEAL-CONFIRM5-F14", {}),
    CandidateSpec("F18", "POSTSEAL-CONFIRM5-F18", {}),
    CandidateSpec("B02V2", "POSTSEAL-CONFIRM5-B02V2", {}),
    CandidateSpec("B03V2", "POSTSEAL-CONFIRM5-B03V2", {}),
)


@dataclass(frozen=True, slots=True)
class BatchConfig:
    world_slots: tuple[str, ...] = tuple(WORLD_REGISTRY)
    train_episodes_per_panel: int = SPLIT_EPISODES_PER_PANEL["train"]
    validation_episodes_per_panel: int = SPLIT_EPISODES_PER_PANEL["validation"]
    test_episodes_per_panel: int = SPLIT_EPISODES_PER_PANEL["sealed_test"]
    pair_probe_limit_per_declaration: int = 2

    def __post_init__(self) -> None:
        # Reuse the exact frozen allocation validator.  The public API always
        # evaluates all five C aliases; reduced world/count configurations are
        # only useful for tests and explicit dry validation.
        _runner.RunConfig(
            "POSTSEAL-CONFIRM5-CONFIG-CHECK",
            "F10",
            {},
            self.world_slots,
            REPLICATE_IDS,
            self.train_episodes_per_panel,
            self.validation_episodes_per_panel,
            self.test_episodes_per_panel,
            self.pair_probe_limit_per_declaration,
        )

    @property
    def complete_benchmark(self) -> bool:
        return (
            self.world_slots == tuple(WORLD_REGISTRY)
            and self.train_episodes_per_panel
            == SPLIT_EPISODES_PER_PANEL["train"]
            and self.validation_episodes_per_panel
            == SPLIT_EPISODES_PER_PANEL["validation"]
            and self.test_episodes_per_panel
            == SPLIT_EPISODES_PER_PANEL["sealed_test"]
        )

    def child_config(self, spec: CandidateSpec) -> _runner.RunConfig:
        return _runner.RunConfig(
            spec.experiment_id,
            spec.family_code,
            spec.parameters,
            self.world_slots,
            REPLICATE_IDS,
            self.train_episodes_per_panel,
            self.validation_episodes_per_panel,
            self.test_episodes_per_panel,
            self.pair_probe_limit_per_declaration,
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "world_slots": list(self.world_slots),
            "confirm_aliases": list(CONFIRM_ALIASES),
            "train_episodes_per_panel": self.train_episodes_per_panel,
            "validation_episodes_per_panel": self.validation_episodes_per_panel,
            "test_episodes_per_panel": self.test_episodes_per_panel,
            "pair_probe_limit_per_declaration": self.pair_probe_limit_per_declaration,
            "complete_benchmark": self.complete_benchmark,
            "candidate_order": [spec.family_code for spec in CANDIDATE_SPECS],
        }


@dataclass(slots=True)
class _ChildRun:
    spec: CandidateSpec
    config: _runner.RunConfig
    run_id: str
    directory: Path
    raw_path: Path
    pair_path: Path
    raw_writer: BinaryIO | None
    pair_writer: BinaryIO | None
    replicates: list[dict[str, Any]]
    active_seconds: float


@dataclass(frozen=True, slots=True)
class _JudgeReplicate:
    panel_rows: list[tuple[str, Any, Any]]
    catalogs: tuple[Any, ...]
    training: tuple[Any, ...]
    sealed_rows: dict[tuple[str, str, int], tuple[Any, dict[int, tuple[Any, ...]]]]
    pair_rows: dict[tuple[str, str], list[dict[str, Any]]]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_binding() -> dict[str, Any]:
    root = _repo_root()
    paths = (
        "prototype/unified_map/postseal_confirm5_runner.py",
        "prototype/unified_map/benchmark_v1_runner.py",
        "prototype/unified_map/benchmark_v1_authority.py",
        "prototype/unified_map/postseal_confirm5.py",
        "prototype/unified_map/baselines_v2.py",
        "prototype/unified_map/candidate_families.py",
    )
    rows = []
    for relative in paths:
        raw = (root / relative).read_bytes()
        rows.append(
            {
                "relative_path": relative,
                "byte_length": len(raw),
                "sha256": digest_bytes(raw),
            }
        )
    return {"files": rows, "source_digest": digest_json(rows)}


def _candidate_source_digest() -> str:
    relative = "prototype/unified_map/candidate_families.py"
    raw = (_repo_root() / relative).read_bytes()
    return digest_json(
        [
            {
                "relative_path": relative,
                "byte_length": len(raw),
                "sha256": digest_bytes(raw),
            }
        ]
    )


def _batch_id() -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-POSTSEAL-CONFIRM5-{uuid.uuid4().hex[:10]}"


def _run_id(spec: CandidateSpec) -> str:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{spec.experiment_id}-{uuid.uuid4().hex[:10]}"


def _materialize_replicate(
    config: BatchConfig, seed_row: dict[str, Any]
) -> _JudgeReplicate:
    """Materialize all expensive judge data exactly once for one C alias."""

    panel_rows = _runner._panels(config.world_slots)
    catalogs, training = _runner._training_records(
        panel_rows, seed_row, config.train_episodes_per_panel
    )
    sealed_rows = _runner._sealed_evaluation_rows(
        panel_rows, seed_row, config.test_episodes_per_panel
    )
    pair_rows = _runner._precompute_pair_oracles(
        panel_rows,
        seed_row["sealed_test_root_seed"],
        config.pair_probe_limit_per_declaration,
    )
    return _JudgeReplicate(panel_rows, catalogs, training, sealed_rows, pair_rows)


def _isolated_training(
    materialized: _JudgeReplicate,
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    # Public records are materialized once, but each model gets a disjoint
    # object graph.  This prevents object.__setattr__ or nested-dict mutation by
    # one baseline/candidate from changing a later model's inputs.
    return copy.deepcopy(materialized.catalogs), copy.deepcopy(materialized.training)


def _isolated_episode(
    materialized: _JudgeReplicate, key: tuple[str, str, int]
) -> tuple[Any, dict[int, tuple[Any, ...]]]:
    episode, oracles = materialized.sealed_rows[key]
    # The candidate receives only episode.public_history, but cloning the
    # episode provides a strong object-identity boundary.  Judge-only oracles
    # are never passed into candidate code and remain shared read-only inputs.
    return copy.deepcopy(episode), oracles


def _isolated_pairs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    isolated = []
    for row in rows:
        isolated.append(
            {
                **row,
                "left": copy.deepcopy(row["left"]),
                "right": copy.deepcopy(row["right"]),
            }
        )
    return isolated


def _commitment_for_alias(
    commitment: dict[str, Any], alias: str
) -> str:
    return next(
        row["commitment"]
        for row in commitment["row_commitments"]
        if row["confirm_alias"] == alias
    )


def _evaluate_candidate_replicate(
    *,
    child: _ChildRun,
    materialized: _JudgeReplicate,
    seed_row: dict[str, Any],
    replicate_id: str,
    confirm_alias: str,
    commitment: dict[str, Any],
) -> None:
    candidate_started = time.perf_counter()
    if child.raw_writer is None or child.pair_writer is None:
        raise ProtocolViolation("CONFIRM5 child writers are closed")
    candidate = _runner._make_benchmark_candidate(
        child.spec.family_code, child.spec.parameters
    )
    catalogs, training = _isolated_training(materialized)
    model_seed = MODEL_SEEDS[REPLICATE_IDS.index(replicate_id)]
    fit_started = time.perf_counter()
    candidate.fit(catalogs, training, model_seed=model_seed)
    fit_seconds = time.perf_counter() - fit_started

    episode_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    for slot, panel, _judge_world in materialized.panel_rows:
        # Policies/catalog query objects are cheap and public.  Give each model
        # a fresh world instance so even aggressive mutation cannot affect the
        # next model; no episode or oracle is regenerated here.
        world = _runner._instantiate_panel(slot, panel.panel_id)
        oracle_root = _runner._derived_seed(
            seed_row["sealed_test_root_seed"], slot, panel.panel_id, "oracle"
        )
        for episode_index in range(child.config.test_episodes_per_panel):
            episode, precomputed_oracles = _isolated_episode(
                materialized, (slot, panel.panel_id, episode_index)
            )
            episode_rows.append(
                _runner._evaluate_episode(
                    candidate=candidate,
                    slot=slot,
                    panel=panel,
                    world=world,
                    episode=episode,
                    replicate_id=replicate_id,
                    episode_index=episode_index,
                    oracle_root=_runner._derived_seed(oracle_root, episode_index),
                    raw_writer=child.raw_writer,
                    precomputed_oracles=precomputed_oracles,
                )
            )
        panel_pairs = _runner._pair_probes(
            candidate=candidate,
            slot=slot,
            panel=panel,
            world=world,
            seed_root=seed_row["sealed_test_root_seed"],
            limit=child.config.pair_probe_limit_per_declaration,
            precomputed=_isolated_pairs(
                materialized.pair_rows[(slot, panel.panel_id)]
            ),
        )
        pair_rows.extend(panel_pairs)
        for row in panel_pairs:
            child.pair_writer.write(canonical_json_bytes(row))

    child.replicates.append(
        {
            "replicate_id": replicate_id,
            "confirm_alias": confirm_alias,
            "model_seed": model_seed,
            "seed_commitment": _commitment_for_alias(commitment, confirm_alias),
            "fit_seconds": fit_seconds,
            "training_record_count": len(training),
            "model_summary": candidate.model_summary(),
            "summary": _runner._replicate_summary(episode_rows, pair_rows),
        }
    )
    child.active_seconds += time.perf_counter() - candidate_started


def _hard_failures(replicates: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "dangerous_collision": sum(
            row["summary"]["dangerous_collision_count"] for row in replicates
        ),
        "update_inconsistency": sum(
            row["summary"]["update_replay_failure_count"] for row in replicates
        ),
        "query_order_impurity": sum(
            row["summary"]["query_order_failure_count"] for row in replicates
        ),
        "unsafe_forced_known_ood": sum(
            row["summary"]["unsafe_non_abstain_count"] for row in replicates
        ),
    }


def _finalize_child(
    child: _ChildRun,
    *,
    freeze: dict[str, Any],
    commitment: dict[str, Any],
    authority_provenance: dict[str, Any],
    source_binding: dict[str, Any],
) -> dict[str, Any]:
    hard_failures = _hard_failures(child.replicates)
    baseline_only = child.spec.family_code in _runner.BASELINE_ONLY_FAMILIES
    separate_task = child.spec.family_code in _runner.SEPARATE_TASK_FAMILIES
    seed_authority = {
        **authority_provenance,
        "row_commitments": commitment["row_commitments"],
    }
    report = {
        "protocol": _runner.RUN_PROTOCOL,
        "run_id": child.run_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "freeze_root": freeze["freeze_root"],
        "benchmark_status": freeze["status"],
        "config": child.config.to_wire(),
        "candidate_eligibility": "baseline_only" if baseline_only else "ucm_candidate",
        "shared_state_compliant_by_design": not separate_task,
        "source_binding": source_binding,
        "replicates": child.replicates,
        "cross_seed_summary": _runner._cross_seed_summary(child.replicates),
        "hard_failures": hard_failures,
        "hard_gate_pass": not any(hard_failures.values()) and not separate_task,
        "wall_seconds": child.active_seconds,
        "raw_episode_file": child.raw_path.name,
        "raw_pair_file": child.pair_path.name,
        "seed_preimages_published": authority_provenance["seed_preimages_published"],
        "seed_authority": seed_authority,
        "supplemental_confirmation": {
            "purpose": PURPOSE,
            "commitment_digest": commitment_digest(commitment),
            "pack_root": commitment["pack_root"],
            "candidate_source_digest": commitment["candidate_source_digest"],
            "durable_seal_commit": DURABLE_SEAL_COMMIT,
            "confirm_aliases": list(CONFIRM_ALIASES),
            "alias_mapping": authority_provenance["alias_mapping"],
            "judge_materialization": "once_per_confirm_alias_shared_judge_only",
            "candidate_input_isolation": "deep_copy_per_model_no_model_or_state_sharing",
        },
        "claim_boundary": {
            "synthetic_only": True,
            "clinical_validity_claimed": False,
            "complete_benchmark": child.config.complete_benchmark,
            "screening_run": not child.config.complete_benchmark,
            "supplemental_postseal_confirm": True,
            "original_freeze_seeds": False,
        },
    }
    summary_path = child.directory / "summary.json"
    summary_path.write_bytes(canonical_json_bytes(report))
    manifest = {
        "protocol": _runner.RUN_MANIFEST_PROTOCOL,
        "run_id": child.run_id,
        "freeze_root": freeze["freeze_root"],
        "files": [
            {
                "name": path.name,
                "byte_length": path.stat().st_size,
                "sha256": digest_bytes(path.read_bytes()),
            }
            for path in (child.raw_path, child.pair_path, summary_path)
        ],
    }
    manifest["bundle_root"] = digest_json(manifest)
    manifest_path = child.directory / "manifest.json"
    manifest_path.write_bytes(canonical_json_bytes(manifest))
    return {
        "family_code": child.spec.family_code,
        "experiment_id": child.spec.experiment_id,
        "run_id": child.run_id,
        "relative_path": PurePosixPath("runs", child.run_id).as_posix(),
        "bundle_root": manifest["bundle_root"],
        "manifest_sha256": digest_bytes(manifest_path.read_bytes()),
    }


def _write_deterministic_gzip(path: Path) -> Path:
    """Write a reproducible sidecar while manifest custody stays uncompressed."""

    output = path.with_name(path.name + ".gz")
    if output.exists():
        raise ProtocolViolation("CONFIRM5 gzip sidecar already exists")
    with path.open("rb") as source, output.open("xb") as target:
        # Empty filename omits the host path from the gzip header; mtime=0
        # makes independently generated sidecars byte-identical.
        with gzip.GzipFile(filename="", mode="wb", fileobj=target, mtime=0) as archive:
            shutil.copyfileobj(source, archive)
    return output


def run_postseal_confirm5_batch(
    *,
    secret_path: Path,
    commitment_path: Path,
    freeze_path: Path | None = None,
    results_root: Path | None = None,
    config: BatchConfig | None = None,
) -> Path:
    """Run the fixed five-model CONFIRM5 comparison with one judge pass/alias."""

    root = _repo_root()
    freeze_path = freeze_path or root / FREEZE_FILENAME
    results_root = results_root or root / DEFAULT_RESULTS_ROOT
    config = config or BatchConfig()
    commitment = verify_commitment_bytes(commitment_path.read_bytes())
    if commitment["candidate_source_digest"] != _candidate_source_digest():
        raise ProtocolViolation("supplemental commitment candidate source drifted")
    freeze, execution_secret, authority_provenance = _runner._load_authority(
        freeze_path, secret_path, commitment_path
    )
    if not authority_provenance.get("supplemental_postseal_confirm", False):
        raise ProtocolViolation("CONFIRM5 runner requires supplemental seed authority")

    batch_id = _batch_id()
    final = results_root / batch_id
    temporary = results_root / f".{batch_id}.tmp"
    if final.exists() or temporary.exists():
        raise ProtocolViolation("CONFIRM5 batch id collision; append-only publication refused")
    temporary.mkdir(parents=True, exist_ok=False)
    (temporary / "runs").mkdir()
    source_binding = _source_binding()
    children: list[_ChildRun] = []
    stack = ExitStack()
    batch_started = time.perf_counter()
    try:
        for spec in CANDIDATE_SPECS:
            run_id = _run_id(spec)
            directory = temporary / "runs" / run_id
            directory.mkdir()
            raw_path = directory / "raw-episodes.jsonl"
            pair_path = directory / "raw-pairs.jsonl"
            child = _ChildRun(
                spec=spec,
                config=config.child_config(spec),
                run_id=run_id,
                directory=directory,
                raw_path=raw_path,
                pair_path=pair_path,
                raw_writer=stack.enter_context(raw_path.open("wb")),
                pair_writer=stack.enter_context(pair_path.open("wb")),
                replicates=[],
                active_seconds=0.0,
            )
            children.append(child)

        for replicate_id, confirm_alias in zip(
            REPLICATE_IDS, CONFIRM_ALIASES, strict=True
        ):
            seed_row = _runner._replicate_secret(execution_secret, replicate_id)
            materialized = _materialize_replicate(config, seed_row)
            for child in children:
                _evaluate_candidate_replicate(
                    child=child,
                    materialized=materialized,
                    seed_row=seed_row,
                    replicate_id=replicate_id,
                    confirm_alias=confirm_alias,
                    commitment=commitment,
                )

        stack.close()
        for child in children:
            child.raw_writer = None
            child.pair_writer = None
            _write_deterministic_gzip(child.raw_path)
            _write_deterministic_gzip(child.pair_path)
        child_rows = [
            _finalize_child(
                child,
                freeze=freeze,
                commitment=commitment,
                authority_provenance=authority_provenance,
                source_binding=source_binding,
            )
            for child in children
        ]
        batch_manifest = {
            "protocol": BATCH_MANIFEST_PROTOCOL,
            "batch_id": batch_id,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "freeze_root": freeze["freeze_root"],
            "purpose": PURPOSE,
            "commitment_digest": commitment_digest(commitment),
            "pack_root": commitment["pack_root"],
            "candidate_source_digest": commitment["candidate_source_digest"],
            "durable_seal_commit": DURABLE_SEAL_COMMIT,
            "confirm_aliases": list(CONFIRM_ALIASES),
            "config": config.to_wire(),
            "oracle_workers": _runner._oracle_worker_count(2**31 - 1),
            "judge_materialization_count": len(CONFIRM_ALIASES),
            "judge_materialization": {
                "orchestration": "single_parent_process",
                "unit": "once_per_confirm_alias",
                "public_training_materializations": len(CONFIRM_ALIASES),
                "sealed_test_materializations": len(CONFIRM_ALIASES),
                "pair_oracle_materializations": len(CONFIRM_ALIASES),
                "reused_across_candidate_count": len(CANDIDATE_SPECS),
            },
            "source_binding": source_binding,
            "children": child_rows,
            "wall_seconds": time.perf_counter() - batch_started,
        }
        batch_manifest["batch_root"] = digest_json(batch_manifest)
        (temporary / "batch-manifest.json").write_bytes(
            canonical_json_bytes(batch_manifest)
        )
        results_root.mkdir(parents=True, exist_ok=True)
        os.replace(temporary, final)
    except BaseException:
        stack.close()
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    verify_postseal_confirm5_batch(final)
    return final


def _decode_canonical(path: Path, label: str) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} is unavailable or invalid") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"{label} is not canonical JSON")
    return value


def verify_postseal_confirm5_batch(path: Path) -> dict[str, Any]:
    """Verify the batch root and every standard child run bundle."""

    manifest = _decode_canonical(path / "batch-manifest.json", "CONFIRM5 batch manifest")
    if manifest.get("protocol") != BATCH_MANIFEST_PROTOCOL:
        raise ProtocolViolation("CONFIRM5 batch manifest protocol mismatch")
    expected_root = digest_json(
        {key: value for key, value in manifest.items() if key != "batch_root"}
    )
    if manifest.get("batch_root") != expected_root:
        raise ProtocolViolation("CONFIRM5 batch root mismatch")
    if (
        manifest.get("purpose") != PURPOSE
        or manifest.get("confirm_aliases") != list(CONFIRM_ALIASES)
        or manifest.get("durable_seal_commit") != DURABLE_SEAL_COMMIT
        or type(manifest.get("children")) is not list
        or len(manifest["children"]) != len(CANDIDATE_SPECS)
    ):
        raise ProtocolViolation("CONFIRM5 batch authority/cardinality mismatch")
    for expected, row in zip(CANDIDATE_SPECS, manifest["children"], strict=True):
        if (
            type(row) is not dict
            or row.get("family_code") != expected.family_code
            or row.get("experiment_id") != expected.experiment_id
        ):
            raise ProtocolViolation("CONFIRM5 child order/identity mismatch")
        run_id = row.get("run_id")
        if (
            type(run_id) is not str
            or not run_id
            or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._-" for character in run_id)
        ):
            raise ProtocolViolation("CONFIRM5 child run id is not a safe identity")
        relative = row.get("relative_path")
        if type(relative) is not str or relative != PurePosixPath(
            "runs", run_id
        ).as_posix():
            raise ProtocolViolation("CONFIRM5 child path mismatch")
        child_path = path / Path(*PurePosixPath(relative).parts)
        try:
            child_path.resolve().relative_to(path.resolve())
        except ValueError as exc:
            raise ProtocolViolation("CONFIRM5 child path escapes batch") from exc
        summary = _runner.verify_run_bundle(child_path)
        child_manifest = _decode_canonical(
            child_path / "manifest.json", "CONFIRM5 child manifest"
        )
        if (
            summary.get("run_id") != row.get("run_id")
            or child_manifest.get("bundle_root") != row.get("bundle_root")
            or digest_bytes((child_path / "manifest.json").read_bytes())
            != row.get("manifest_sha256")
        ):
            raise ProtocolViolation("CONFIRM5 child custody mismatch")
    return manifest


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Run supplemental post-seal CONFIRM5 as one judge-materialized batch"
    )
    parser.add_argument("--secret", type=Path, required=True)
    parser.add_argument("--commitment", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, default=_repo_root() / FREEZE_FILENAME)
    parser.add_argument("--results-root", type=Path, default=_repo_root() / DEFAULT_RESULTS_ROOT)
    args = parser.parse_args()
    result = run_postseal_confirm5_batch(
        secret_path=args.secret,
        commitment_path=args.commitment,
        freeze_path=args.freeze,
        results_root=args.results_root,
    )
    manifest = verify_postseal_confirm5_batch(result)
    print(
        json.dumps(
            {
                "protocol": BATCH_PROTOCOL,
                "batch_id": manifest["batch_id"],
                "batch_root": manifest["batch_root"],
                "relative_path": result.as_posix(),
                "child_run_ids": [row["run_id"] for row in manifest["children"]],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "BATCH_MANIFEST_PROTOCOL",
    "BATCH_PROTOCOL",
    "BatchConfig",
    "CANDIDATE_SPECS",
    "DEFAULT_ORACLE_WORKERS",
    "run_postseal_confirm5_batch",
    "verify_postseal_confirm5_batch",
]
