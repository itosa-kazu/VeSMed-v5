"""Fail-closed verifier for the post-selection UCM candidate seal."""

from __future__ import annotations

import json
import math
import statistics
from pathlib import Path, PurePosixPath
from typing import Any

from .benchmark_v1_freeze import (
    FREEZE_FILENAME,
    MODEL_SEEDS,
    REPLICATE_IDS,
    SPLIT_EPISODES_PER_PANEL,
    verify_freeze_manifest_bytes,
)
from .benchmark_v1_runner import verify_run_bundle
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .world_registry import WORLD_REGISTRY


_TOP_LEVEL_KEYS = {
    "candidate",
    "candidate_source_binding",
    "complete_run",
    "freeze_root",
    "mutation_rule",
    "protocol",
    "sealed_at_utc",
    "seed_reveal_status",
    "selection_disposition",
    "status",
}
_CANDIDATE_KEYS = {
    "candidate_id",
    "family_code",
    "family_id",
    "parameters",
    "shared_state_contract",
}
_SOURCE_BINDING_KEYS = {"files", "source_digest"}
_SOURCE_ROW_KEYS = {"relative_path", "byte_length", "sha256"}
_COMPLETE_RUN_KEYS = {
    "bundle_root",
    "cross_seed_summary",
    "hard_failures",
    "relative_path",
    "replicate_ids",
    "run_id",
    "source_digest",
}
_SELECTION_KEYS = {
    "blocking_hard_failure",
    "no_winner_claimed",
    "role",
    "ucm_eligible",
}


def _decode_canonical(payload: bytes, label: str) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolViolation(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
        )
    except ProtocolViolation:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProtocolViolation(f"{label} is not valid JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != payload:
        raise ProtocolViolation(f"{label} is not canonical JSON")
    validate_json_like(value, path=label)
    return value


def _is_digest(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 71
        and value.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in value[7:])
    )


def _contained_path(repo_root: Path, relative: object, label: str) -> Path:
    if type(relative) is not str or not relative or "\\" in relative:
        raise ProtocolViolation(f"{label} is not a canonical repository-relative path")
    wire_path = PurePosixPath(relative)
    if wire_path.is_absolute() or any(part in {"", ".", ".."} for part in wire_path.parts):
        raise ProtocolViolation(f"{label} escapes the repository")
    root = repo_root.resolve()
    target = (root / Path(*wire_path.parts)).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} escapes the repository") from exc
    return target


def _verify_source_binding(
    binding: object,
    *,
    repo_root: Path,
    require_live_bytes: bool,
) -> tuple[list[dict[str, Any]], str]:
    if type(binding) is not dict or set(binding) != _SOURCE_BINDING_KEYS:
        raise ProtocolViolation("candidate source binding shape mismatch")
    files = binding["files"]
    if type(files) is not list or not files:
        raise ProtocolViolation("candidate source binding has no files")
    seen: set[str] = set()
    for row in files:
        if type(row) is not dict or set(row) != _SOURCE_ROW_KEYS:
            raise ProtocolViolation("candidate source row shape mismatch")
        relative = row["relative_path"]
        if type(relative) is not str or relative in seen:
            raise ProtocolViolation("candidate source paths are invalid or duplicated")
        seen.add(relative)
        if type(row["byte_length"]) is not int or row["byte_length"] < 0:
            raise ProtocolViolation("candidate source byte length is invalid")
        if not _is_digest(row["sha256"]):
            raise ProtocolViolation("candidate source digest is invalid")
        source = _contained_path(repo_root, relative, "candidate source path")
        if require_live_bytes:
            try:
                source_raw = source.read_bytes()
            except OSError as exc:
                raise ProtocolViolation("sealed candidate source is unavailable") from exc
            if (
                len(source_raw) != row["byte_length"]
                or digest_bytes(source_raw) != row["sha256"]
            ):
                raise ProtocolViolation("sealed candidate source drifted")
    expected = digest_json(files)
    if binding["source_digest"] != expected:
        raise ProtocolViolation("candidate source aggregate mismatch")
    return files, expected


def _cross_seed_summary(replicates: list[dict[str, Any]]) -> dict[str, Any]:
    keys = sorted(
        {
            key
            for row in replicates
            for key, value in row["summary"]["headline"].items()
            if value is not None
        }
    )
    metrics: dict[str, Any] = {}
    for key in keys:
        values = [
            float(row["summary"]["headline"][key])
            for row in replicates
            if row["summary"]["headline"][key] is not None
        ]
        if not values or any(not math.isfinite(value) for value in values):
            raise ProtocolViolation("run replicate headline is not finite")
        mean = statistics.fmean(values)
        sd = statistics.stdev(values) if len(values) > 1 else 0.0
        half_width = 2.7764451051977987 * sd / math.sqrt(5) if len(values) == 5 else None
        metrics[key] = {
            "mean": mean,
            "sd": sd,
            "min": min(values),
            "max": max(values),
            "t95_low": None if half_width is None else mean - half_width,
            "t95_high": None if half_width is None else mean + half_width,
            "seed_count": len(values),
        }
    return metrics


def _hard_failures(replicates: list[dict[str, Any]]) -> dict[str, int]:
    try:
        result = {
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
    except (KeyError, TypeError) as exc:
        raise ProtocolViolation("run replicate failure counters are malformed") from exc
    if any(type(value) is not int or value < 0 for value in result.values()):
        raise ProtocolViolation("run replicate failure counters are invalid")
    return result


def verify_candidate_seal(path: Path, *, repo_root: Path | None = None) -> dict[str, Any]:
    """Rebuild every live and derivable binding carried by a candidate seal."""

    repo_root = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation("candidate seal is unavailable") from exc
    seal = _decode_canonical(raw, "candidate seal")
    if (
        set(seal) != _TOP_LEVEL_KEYS
        or seal.get("protocol") != "ucm-candidate-seal/1"
        or seal.get("status") != "SEALED_FOR_POST_SELECTION_REDTEAM"
        or seal.get("seed_reveal_status") != "SEALED_NOT_PUBLISHED"
        or type(seal.get("sealed_at_utc")) is not str
        or not seal["sealed_at_utc"]
        or seal.get("mutation_rule")
        != "Any candidate source byte change invalidates this seal and requires a new family/version; red-team may not modify it."
    ):
        raise ProtocolViolation("candidate seal protocol/shape mismatch")
    candidate = seal["candidate"]
    complete = seal["complete_run"]
    if type(candidate) is not dict or set(candidate) != _CANDIDATE_KEYS:
        raise ProtocolViolation("candidate seal identity shape mismatch")
    if type(complete) is not dict or set(complete) != _COMPLETE_RUN_KEYS:
        raise ProtocolViolation("candidate seal complete-run shape mismatch")
    for key in ("candidate_id", "family_code", "family_id", "shared_state_contract"):
        if type(candidate[key]) is not str or not candidate[key]:
            raise ProtocolViolation("candidate seal identity value mismatch")
    if type(candidate["parameters"]) is not dict:
        raise ProtocolViolation("candidate seal parameters must be an object")
    for key in ("bundle_root", "source_digest"):
        if not _is_digest(complete[key]):
            raise ProtocolViolation("candidate seal complete-run digest is invalid")

    source_files, candidate_source_digest = _verify_source_binding(
        seal["candidate_source_binding"],
        repo_root=repo_root,
        require_live_bytes=True,
    )
    if candidate_source_digest != seal["candidate_source_binding"]["source_digest"]:
        raise ProtocolViolation("candidate source aggregate mismatch")

    freeze_path = repo_root / FREEZE_FILENAME
    try:
        live_freeze = verify_freeze_manifest_bytes(freeze_path.read_bytes())
    except OSError as exc:
        raise ProtocolViolation("live benchmark freeze is unavailable") from exc
    if seal["freeze_root"] != live_freeze["freeze_root"]:
        raise ProtocolViolation("candidate seal/live freeze root mismatch")

    run_path = _contained_path(repo_root, complete["relative_path"], "sealed run path")
    summary = verify_run_bundle(run_path)
    manifest = _decode_canonical((run_path / "manifest.json").read_bytes(), "run manifest")
    if (
        summary.get("run_id") != complete["run_id"]
        or manifest.get("run_id") != complete["run_id"]
        or manifest.get("bundle_root") != complete["bundle_root"]
        or manifest.get("freeze_root") != seal["freeze_root"]
        or summary.get("freeze_root") != seal["freeze_root"]
    ):
        raise ProtocolViolation("candidate seal/run/freeze binding mismatch")

    run_binding = summary.get("source_binding")
    if type(run_binding) is not dict or set(run_binding) != _SOURCE_BINDING_KEYS:
        raise ProtocolViolation("sealed run source binding shape mismatch")
    run_files = run_binding["files"]
    if type(run_files) is not list or not run_files or any(
        type(row) is not dict or set(row) != _SOURCE_ROW_KEYS for row in run_files
    ):
        raise ProtocolViolation("sealed run source rows are malformed")
    run_paths: set[str] = set()
    for row in run_files:
        relative = row["relative_path"]
        if type(relative) is not str or relative in run_paths:
            raise ProtocolViolation("sealed run source paths are invalid or duplicated")
        run_paths.add(relative)
        _contained_path(repo_root, relative, "sealed run source path")
        if type(row["byte_length"]) is not int or row["byte_length"] < 0:
            raise ProtocolViolation("sealed run source byte length is invalid")
        if not _is_digest(row["sha256"]):
            raise ProtocolViolation("sealed run source digest is invalid")
    if (
        run_binding["source_digest"] != digest_json(run_files)
        or run_binding["source_digest"] != complete["source_digest"]
    ):
        raise ProtocolViolation("candidate seal/run source aggregate mismatch")
    if any(row not in run_files for row in source_files):
        raise ProtocolViolation("sealed candidate source is absent from run source binding")

    config = summary.get("config")
    replicate_ids = complete["replicate_ids"]
    expected_ids = list(REPLICATE_IDS)
    if (
        type(config) is not dict
        or config.get("family_code") != candidate["family_code"]
        or config.get("parameters") != candidate["parameters"]
        or config.get("complete_benchmark") is not True
        or config.get("world_slots") != list(WORLD_REGISTRY)
        or config.get("replicate_ids") != expected_ids
        or config.get("train_episodes_per_panel") != SPLIT_EPISODES_PER_PANEL["train"]
        or config.get("validation_episodes_per_panel")
        != SPLIT_EPISODES_PER_PANEL["validation"]
        or config.get("test_episodes_per_panel") != SPLIT_EPISODES_PER_PANEL["sealed_test"]
        or replicate_ids != expected_ids
    ):
        raise ProtocolViolation("candidate seal does not bind a complete benchmark run")

    replicates = summary.get("replicates")
    if type(replicates) is not list or len(replicates) != len(REPLICATE_IDS):
        raise ProtocolViolation("sealed run replicate cardinality mismatch")
    if [row.get("replicate_id") for row in replicates] != expected_ids:
        raise ProtocolViolation("sealed run replicate identities/order mismatch")
    if [row.get("model_seed") for row in replicates] != list(MODEL_SEEDS):
        raise ProtocolViolation("sealed run model seeds mismatch")
    for row in replicates:
        model = row.get("model_summary")
        counters = row.get("summary")
        if (
            type(model) is not dict
            or model.get("candidate_id") != candidate["candidate_id"]
            or model.get("family_id") != candidate["family_id"]
        ):
            raise ProtocolViolation("sealed run candidate identity mismatch")
        if type(counters) is not dict or any(
            type(counters.get(key)) is not int or counters[key] < 0
            for key in (
                "dangerous_collision_count",
                "update_replay_failure_count",
                "query_order_failure_count",
                "unsafe_non_abstain_count",
            )
        ):
            raise ProtocolViolation("sealed run replicate failure counter mismatch")

    rebuilt_cross_seed = _cross_seed_summary(replicates)
    rebuilt_hard_failures = _hard_failures(replicates)
    if (
        summary.get("cross_seed_summary") != rebuilt_cross_seed
        or complete["cross_seed_summary"] != rebuilt_cross_seed
    ):
        raise ProtocolViolation("candidate seal cross-seed summary mismatch")
    if (
        summary.get("hard_failures") != rebuilt_hard_failures
        or complete["hard_failures"] != rebuilt_hard_failures
    ):
        raise ProtocolViolation("candidate seal hard-failure summary mismatch")
    expected_hard_gate = (
        not any(rebuilt_hard_failures.values())
        and candidate["family_code"] != "B03"
    )
    if summary.get("hard_gate_pass") is not expected_hard_gate:
        raise ProtocolViolation("sealed run hard-gate result mismatch")
    disposition = seal["selection_disposition"]
    if (
        type(disposition) is not dict
        or set(disposition) != _SELECTION_KEYS
        or type(disposition["blocking_hard_failure"]) is not str
        or disposition["role"] != "pareto-leading redteam subject"
        or disposition["ucm_eligible"] is not expected_hard_gate
        or disposition["no_winner_claimed"] is not True
    ):
        raise ProtocolViolation("candidate seal selection disposition mismatch")
    return seal


__all__ = ["verify_candidate_seal"]
