"""Auditable closed-loop demo for the sealed F18 shared-state candidate.

The demo is deliberately synthetic.  It proves the API/data-flow property that
diagnosis, natural-course rollout and three treatment rollouts consume the
same immutable ``SharedPatientState``.  It does not repair F18's benchmark
failures and it does not claim clinical validity.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from .benchmark_v1_contract import build_public_training_record
from .candidate_families import make_candidate
from .candidate_seal import verify_candidate_seal
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from .schema import (
    CandidateVisibleEvent,
    EventKind,
    VisibleDelta,
    event_sort_key,
)
from .world_registry import WORLD_REGISTRY
from .worlds.base import WorldSplit


TRAIN_EPISODES = 32
TRAIN_SEED = 881_300
ORACLE_SEED = 991_300
MODEL_SEED = 104_729
DEMO_SEED = 881_300
RESPONSE_SEED = 777
OOD_SEED = 881_800
HORIZON = 4
DEMO_PROTOCOL = "ucm-shared-state-demo/1"
MANIFEST_PROTOCOL = "ucm-shared-state-demo-manifest/1"
REPO_ROOT = Path(__file__).resolve().parents[2]


def _manifest(
    directory: Path,
    run_id: str,
    sources: tuple[Path, ...],
    *,
    repo_root: Path,
) -> dict[str, Any]:
    rows = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.name == "manifest.json" or not path.is_file():
            continue
        raw = path.read_bytes()
        rows.append(
            {
                "name": path.name,
                "byte_length": len(raw),
                "sha256": digest_bytes(raw),
            }
        )
    source_rows = []
    for source in sources:
        resolved = source.resolve()
        try:
            relative = resolved.relative_to(repo_root.resolve())
        except ValueError as exc:
            raise ProtocolViolation(f"demo source is outside repository: {source}") from exc
        raw = resolved.read_bytes()
        source_rows.append(
            {
                "relative_path": relative.as_posix(),
                "byte_length": len(raw),
                "sha256": digest_bytes(raw),
            }
        )
    payload = {
        "protocol": MANIFEST_PROTOCOL,
        "run_id": run_id,
        "files": rows,
        "sources": source_rows,
    }
    # The root binds the manifest identity as well as its byte inventories.
    # Omitting protocol/run_id here would allow cross-protocol or cross-run
    # relabeling without changing the root.
    payload["bundle_root"] = digest_json(payload)
    return payload


def _canonical_json_file(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"invalid JSON artifact: {path}") from exc
    if type(value) is not dict:
        raise ProtocolViolation(f"artifact must be a JSON object: {path}")
    if canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"artifact is not canonical JSON: {path}")
    return value


def verify_demo_bundle(
    directory: Path,
    *,
    repo_root: Path = REPO_ROOT,
) -> dict[str, Any]:
    """Verify a demo bundle, including canonical bytes and live sources."""

    directory = directory.resolve()
    manifest = _canonical_json_file(directory / "manifest.json")
    required = {"protocol", "run_id", "files", "sources", "bundle_root"}
    if set(manifest) != required:
        raise ProtocolViolation("demo manifest fields do not match protocol")
    if manifest["protocol"] != MANIFEST_PROTOCOL:
        raise ProtocolViolation("unexpected demo manifest protocol")
    if manifest["run_id"] != directory.name:
        raise ProtocolViolation("demo manifest run_id does not match directory")
    expected_root = digest_json(
        {key: value for key, value in manifest.items() if key != "bundle_root"}
    )
    if manifest["bundle_root"] != expected_root:
        raise ProtocolViolation("demo manifest bundle_root mismatch")

    files = manifest["files"]
    sources = manifest["sources"]
    if type(files) is not list or type(sources) is not list:
        raise ProtocolViolation("demo manifest inventories must be lists")

    seen_files: set[str] = set()
    for row in files:
        if type(row) is not dict or set(row) != {"name", "byte_length", "sha256"}:
            raise ProtocolViolation("invalid demo file inventory row")
        name = row["name"]
        if type(name) is not str or Path(name).name != name or name == "manifest.json":
            raise ProtocolViolation("unsafe demo artifact name")
        if name in seen_files:
            raise ProtocolViolation("duplicate demo artifact name")
        seen_files.add(name)
        raw = (directory / name).read_bytes()
        if len(raw) != row["byte_length"] or digest_bytes(raw) != row["sha256"]:
            raise ProtocolViolation(f"demo artifact binding mismatch: {name}")
        _canonical_json_file(directory / name)
    actual_files = {
        path.name
        for path in directory.iterdir()
        if path.is_file() and path.name != "manifest.json"
    }
    if actual_files != seen_files:
        raise ProtocolViolation("demo file inventory is not closed")

    seen_sources: set[str] = set()
    root = repo_root.resolve()
    for row in sources:
        if type(row) is not dict or set(row) != {
            "relative_path",
            "byte_length",
            "sha256",
        }:
            raise ProtocolViolation("invalid demo source inventory row")
        relative = row["relative_path"]
        if type(relative) is not str or relative in seen_sources:
            raise ProtocolViolation("invalid or duplicate demo source path")
        seen_sources.add(relative)
        source = (root / Path(relative)).resolve()
        try:
            source.relative_to(root)
        except ValueError as exc:
            raise ProtocolViolation("demo source escapes repository") from exc
        raw = source.read_bytes()
        if len(raw) != row["byte_length"] or digest_bytes(raw) != row["sha256"]:
            raise ProtocolViolation(f"demo source binding mismatch: {relative}")

    report = _canonical_json_file(directory / "demo.json")
    if report.get("protocol") != DEMO_PROTOCOL:
        raise ProtocolViolation("unexpected demo report protocol")
    if report.get("run_id") != manifest["run_id"]:
        raise ProtocolViolation("demo report run_id mismatch")
    return report


def _candidate_visible_delta(action_id: str, step: dict[str, Any]) -> VisibleDelta:
    """Turn a post-selection synthetic response into the candidate-visible wire."""

    events = [
        CandidateVisibleEvent(
            EventKind.PERFORMED_TREATMENT,
            1,
            1,
            digest_json({"demo": "performed-treatment", "action_id": action_id}),
            {"action_id": action_id, "parameters": {}},
            None,
        )
    ]
    for key, value in sorted(step.items()):
        if not (key.startswith("obs_") and key.endswith("_mean")):
            continue
        channel_id = key[: -len("_mean")]
        events.append(
            CandidateVisibleEvent(
                EventKind.OBSERVATION_AVAILABLE,
                1,
                1,
                digest_json({"demo": "observation", "channel_id": channel_id}),
                {"channel_id": channel_id, "value": float(value)},
                1,
            )
        )
    return VisibleDelta(1, tuple(sorted(events, key=event_sort_key)))


def _rollout_row(candidate: Any, state: Any, policy: Any, label: str, index: int) -> dict[str, Any]:
    prediction = candidate.rollout(
        state,
        policy,
        HORIZON,
        query_seed=20_000 + index,
    )
    return {
        "label": label,
        "input_state_hash": state.state_hash,
        "policy": policy.to_wire(),
        "horizon": HORIZON,
        "signature": list(prediction.signature),
        "expected_utility": prediction.expected_utility,
        "abstained": prediction.abstained,
    }


def run_demo(*, seal_path: Path, output_root: Path) -> Path:
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-DEMO-{uuid.uuid4().hex[:10]}"
    seal = verify_candidate_seal(seal_path)
    started = time.perf_counter()
    worlds = {
        slot: WORLD_REGISTRY[slot].panels[0].instantiate()
        for slot in ("W13", "W18")
    }
    catalogs = tuple(world.catalog for world in worlds.values())
    training = []
    for slot, world in worlds.items():
        base = TRAIN_SEED + int(slot[1:]) * 100
        for index in range(TRAIN_EPISODES):
            episode = world.generate_episode(WorldSplit.TRAIN, base, index)
            training.append(
                build_public_training_record(
                    world,
                    episode,
                    oracle_seed=ORACLE_SEED + int(slot[1:]) * 100 + index,
                )
            )

    candidate = make_candidate("F18")
    candidate.fit(catalogs, tuple(training), model_seed=MODEL_SEED)

    world = worlds["W13"]
    episode = world.generate_episode(WorldSplit.VALIDATION, DEMO_SEED, 0)
    before = candidate.initialize(episode.public_history, inference_seed=10_001)
    diagnosis_before = candidate.diagnose(
        before,
        world.catalog.diagnostic_labels,
        query_seed=10_002,
    )
    policies = world.policy_set(HORIZON)[:4]
    labels = ("no_new_treatment", "treatment_A", "treatment_B", "treatment_C")
    before_rollouts = [
        _rollout_row(candidate, before, policy, label, index)
        for index, (policy, label) in enumerate(zip(policies, labels, strict=True))
    ]
    treatment_indices = range(1, 4)
    selected_index = max(
        treatment_indices,
        key=lambda index: before_rollouts[index]["expected_utility"],
    )
    selected_policy = policies[selected_index]
    selected_action = selected_policy.actions[0].action_id

    # Judge/world access occurs only after the treatment has been selected.
    # Its first-step mean is exposed as the deterministic synthetic realization;
    # only the resulting public delta is passed to the candidate update.
    realized = world.counterfactual(
        episode,
        selected_policy,
        HORIZON,
        RESPONSE_SEED,
    )
    first_step = realized.observation_distribution["steps"][0]
    delta = _candidate_visible_delta(selected_action, first_step)
    after = candidate.update(before, delta, inference_seed=10_003)
    diagnosis_after = candidate.diagnose(
        after,
        world.catalog.diagnostic_labels,
        query_seed=10_004,
    )
    after_rollouts = [
        _rollout_row(candidate, after, policy, label, index + 10)
        for index, (policy, label) in enumerate(zip(policies, labels, strict=True))
    ]

    before_inputs = [before.state_hash] + [row["input_state_hash"] for row in before_rollouts]
    after_inputs = [after.state_hash] + [row["input_state_hash"] for row in after_rollouts]
    before_head_hashes = {
        "diagnosis": before.state_hash,
        **{
            row["label"]: row["input_state_hash"]
            for row in before_rollouts
        },
    }
    after_head_hashes = {
        "diagnosis": after.state_hash,
        **{
            row["label"]: row["input_state_hash"]
            for row in after_rollouts
        },
    }

    # A fixed, genuinely unknown W18 episode demonstrates a successful local
    # abstention.  The report also preserves the aggregate red-team failure
    # boundary so this example cannot be read as an OOD success claim.
    ood_world = worlds["W18"]
    ood_episode = None
    ood_state = None
    ood_diagnosis = None
    ood_index = None
    for index in range(64):
        inspected = ood_world.generate_episode(WorldSplit.VALIDATION, OOD_SEED, index)
        if inspected.diagnostic_target.get("unknown", 0.0) < 0.5:
            continue
        inspected_state = candidate.initialize(
            inspected.public_history,
            inference_seed=30_001 + index,
        )
        inspected_diagnosis = candidate.diagnose(
            inspected_state,
            ood_world.catalog.diagnostic_labels,
            query_seed=31_001 + index,
        )
        if inspected_diagnosis.probabilities["unknown"] >= 0.5:
            ood_episode = inspected
            ood_state = inspected_state
            ood_diagnosis = inspected_diagnosis
            ood_index = index
            break
    if ood_episode is None or ood_state is None or ood_diagnosis is None:
        raise RuntimeError("no admitted W18 unknown example found in fixed 64-episode scan")
    unknown_probability = ood_diagnosis.probabilities["unknown"]

    report = {
        "protocol": DEMO_PROTOCOL,
        "run_id": run_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "candidate_seal_digest": digest_bytes(seal_path.read_bytes()),
        "sealed_candidate_source_digest": seal["candidate_source_binding"]["source_digest"],
        "candidate": candidate.model_summary(),
        "training": {
            "world_slots": ["W13", "W18"],
            "public_record_count": len(training),
            "episodes_per_panel": TRAIN_EPISODES,
            "train_seed": TRAIN_SEED,
            "oracle_seed": ORACLE_SEED,
            "model_seed": MODEL_SEED,
        },
        "closed_loop": {
            "world_slot": "W13",
            "synthetic_only": True,
            "public_history_digest": episode.public_history.digest,
            "before": {
                "state_hash": before.state_hash,
                "state_dimension": len(before.distance_vector),
                "state_bytes": before.canonical_size_bytes,
                "diagnosis": {
                    "input_state_hash": before.state_hash,
                    "probabilities": diagnosis_before.probabilities,
                },
                "rollouts": before_rollouts,
                "head_input_state_hashes": before_head_hashes,
                "all_heads_same_state": len(set(before_inputs)) == 1,
            },
            "selection": {
                "rule": "argmax predicted expected utility over treatment_A/B/C",
                "selected_label": labels[selected_index],
                "selected_action_id": selected_action,
                "selected_input_state_hash": before.state_hash,
                "oracle_or_future_not_used_for_selection": True,
            },
            "realized_public_delta": {
                "wire": delta.to_wire(),
                "generation": "post-selection W13 oracle first-step mean used as deterministic synthetic realization",
                "candidate_received_private_state": False,
                "performed_action_event_count": sum(
                    event.kind is EventKind.PERFORMED_TREATMENT
                    for event in delta.events
                ),
                "observation_event_count": sum(
                    event.kind is EventKind.OBSERVATION_AVAILABLE
                    for event in delta.events
                ),
            },
            "update": {
                "input_state_hash": before.state_hash,
                "output_state_hash": after.state_hash,
                "actual_candidate_update_call": True,
                "nonempty_action_and_observation_delta": bool(delta.events),
                "state_changed": after.state_hash != before.state_hash,
                "state_distance": float(
                    np.linalg.norm(
                        np.asarray(after.distance_vector)
                        - np.asarray(before.distance_vector)
                    )
                ),
            },
            "after": {
                "state_hash": after.state_hash,
                "state_dimension": len(after.distance_vector),
                "state_bytes": after.canonical_size_bytes,
                "diagnosis": {
                    "input_state_hash": after.state_hash,
                    "probabilities": diagnosis_after.probabilities,
                },
                "rollouts": after_rollouts,
                "head_input_state_hashes": after_head_hashes,
                "all_heads_same_state": len(set(after_inputs)) == 1,
            },
            "shared_state_invariants": {
                "before_head_input_hash_count": len(set(before_inputs)),
                "after_head_input_hash_count": len(set(after_inputs)),
                "before_head_labels": list(before_head_hashes),
                "after_head_labels": list(after_head_hashes),
                "heads_received_raw_history": False,
                "heads_received_private_state": False,
                "task_specific_patient_state": False,
                "passed": len(set(before_inputs)) == len(set(after_inputs)) == 1,
            },
        },
        "ood_or_insufficient_information": {
            "world_slot": "W18",
            "example_index": ood_index,
            "example_selection": "first true-unknown episode admitted as unknown in fixed indices 0..63",
            "public_history_digest": ood_episode.public_history.digest,
            "input_state_hash": ood_state.state_hash,
            "judge_target": ood_episode.diagnostic_target,
            "candidate_probabilities": ood_diagnosis.probabilities,
            "map_admitted_unknown": unknown_probability >= 0.5,
            "unknown_probability": unknown_probability,
            "boundary": {
                "example_is_not_aggregate_validation": True,
                "sealed_full_benchmark_unsafe_forced_known_ood": 5,
                "exploratory_redteam_unsafe_forced_known_ood": 9,
                "conclusion": "F18 OOD handling fails the hard gate despite this admitted example",
            },
        },
        "wall_seconds": time.perf_counter() - started,
        "claim_boundary": {
            "synthetic_only": True,
            "clinical_validity_claimed": False,
            "production_safety_claimed": False,
            "repairs_sealed_failures": False,
            "demonstrates_shared_state_data_flow_only": True,
        },
    }
    invariants = report["closed_loop"]["shared_state_invariants"]
    if not invariants["passed"]:
        raise RuntimeError("demo heads did not all consume the same state")
    if not report["closed_loop"]["update"]["state_changed"]:
        raise RuntimeError("demo public response failed to update the state")
    if report["closed_loop"]["realized_public_delta"]["performed_action_event_count"] != 1:
        raise RuntimeError("demo response lacks the selected treatment event")
    if report["closed_loop"]["realized_public_delta"]["observation_event_count"] < 1:
        raise RuntimeError("demo response lacks a visible observation event")
    if not report["ood_or_insufficient_information"]["map_admitted_unknown"]:
        raise RuntimeError("fixed W18 demo episode no longer admits map insufficiency")

    output_root.mkdir(parents=True, exist_ok=True)
    directory = output_root / run_id
    directory.mkdir()
    (directory / "demo.json").write_bytes(canonical_json_bytes(report))
    sources = (
        REPO_ROOT / "prototype/unified_map/demo_v1.py",
        REPO_ROOT / "prototype/unified_map/candidate_families.py",
        seal_path.resolve(),
    )
    manifest = _manifest(directory, run_id, sources, repo_root=REPO_ROOT)
    (directory / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    verify_demo_bundle(directory)
    return directory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seal",
        type=Path,
        default=Path("research/unified_map/CANDIDATE_SEAL.json"),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("results/unified_map/demo"),
    )
    args = parser.parse_args()
    print(run_demo(seal_path=args.seal, output_root=args.output_root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
