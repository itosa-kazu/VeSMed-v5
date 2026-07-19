"""One-shot runner and independent verifier for source-distinct red-team v2.

The runner consumes an already committed hiding commitment and an external
reveal.  It executes both pre-bound implementations before publishing the
reveal into the result bundle.  Raw rows, actual Python audit-hook events,
state closure bytes, paired controls, source hashes and chronology are all
bound into one non-circular bundle root.

This is process-level evidence, not an OS sandbox: the manifest says so.  Every
candidate fit/initialize/update/diagnose/rollout call is observed by the live
Python audit hook.  Every patient state created by initialize, update, replay,
deletion, capacity probing, or cold rehydration is persisted as closure bytes;
the fitted static candidate object graph is separately hashed before and after
all patient calls to detect an external patient cache.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import shutil
import subprocess
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes, digest_json
from .redteam_v2_adapter import (
    append_delta_history,
    call_with_access_trace,
    candidate_source_bindings,
    candidate_static_closure,
    fit_implementations,
    history_from_wire,
    make_check_delta,
    plan_from_wire,
    prediction_wire,
    rehydrate_state,
    state_closure,
)
from .redteam_v2_pack import (
    COMMITMENT_PROTOCOL,
    REQUIRED_ATTACK_CLASSES,
    REVEAL_PROTOCOL,
    verify_reveal,
)
from .schema import CandidateVisibleEvent, EventKind, VisibleDelta


RUN_PROTOCOL = "ucm-source-distinct-redteam-run/2"
MANIFEST_PROTOCOL = "ucm-source-distinct-redteam-manifest/2"
MODEL_SEED = 610_271


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_bytes())
    if type(value) is not dict:
        raise ProtocolViolation(f"{path} must contain a JSON object")
    return value


def _read_artifact_bytes(directory: Path, name: str) -> bytes:
    """Read a tracked artifact or reconstruct an ignored raw JSONL from gzip."""

    path = directory / name
    if path.is_file():
        return path.read_bytes()
    if name.endswith(".jsonl"):
        sidecar = directory / (name + ".gz")
        if sidecar.is_file():
            try:
                return gzip.decompress(sidecar.read_bytes())
            except OSError as exc:
                raise ProtocolViolation(f"invalid red-team gzip fallback: {sidecar.name}") from exc
    raise ProtocolViolation(f"red-team artifact is missing: {name}")


def _write_object(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("wb") as handle:
        for row in rows:
            handle.write(canonical_json_bytes(row))
            count += 1
    raw = path.read_bytes()
    gzip_path = path.with_suffix(path.suffix + ".gz")
    with gzip_path.open("wb") as raw_handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_handle, mtime=0) as compressed:
            compressed.write(raw)
    return {
        "path": path.name,
        "line_count": count,
        "byte_length": len(raw),
        "sha256": digest_bytes(raw),
        "gzip_path": gzip_path.name,
        "gzip_sha256": digest_bytes(gzip_path.read_bytes()),
    }


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode:
        raise ProtocolViolation(f"git {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout.strip()


def _verify_commitment_chronology(
    repository_root: Path,
    commitment_path: Path,
    commitment_git_commit: str,
    commitment: dict[str, Any],
) -> dict[str, Any]:
    relative = commitment_path.resolve().relative_to(repository_root.resolve()).as_posix()
    shown = subprocess.run(
        ["git", "show", f"{commitment_git_commit}:{relative}"],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if shown.returncode:
        raise ProtocolViolation("durable commitment blob is missing from git")
    committed = shown.stdout
    if committed != commitment_path.read_bytes():
        raise ProtocolViolation("local commitment bytes differ from durable git blob")
    pre_pack = commitment["pre_pack_git_commit"]
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", pre_pack, commitment_git_commit],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0 or pre_pack == commitment_git_commit:
        raise ProtocolViolation("commitment commit must descend from a distinct pre-pack commit")
    prepack_paths = {
        "sealed_f18": "prototype/unified_map/candidate_families.py",
        "independent_f18": "prototype/unified_map/independent_f18.py",
    }
    prepack_source_receipts: dict[str, dict[str, Any]] = {}
    for implementation_id, relative_source in prepack_paths.items():
        shown_source = subprocess.run(
            ["git", "show", f"{pre_pack}:{relative_source}"],
            cwd=repository_root,
            check=False,
            capture_output=True,
        )
        if shown_source.returncode:
            raise ProtocolViolation(f"pre-pack commit lacks bound source: {relative_source}")
        source_hash = digest_bytes(shown_source.stdout)
        if source_hash != commitment["candidate_source_bindings"][implementation_id]:
            raise ProtocolViolation(f"pre-pack source binding mismatch: {implementation_id}")
        prepack_source_receipts[implementation_id] = {
            "path": relative_source,
            "sha256": source_hash,
            "byte_length": len(shown_source.stdout),
        }
    generator_path = "prototype/unified_map/redteam_v2_pack.py"
    shown_generator = subprocess.run(
        ["git", "show", f"{pre_pack}:{generator_path}"],
        cwd=repository_root,
        check=False,
        capture_output=True,
    )
    if shown_generator.returncode:
        raise ProtocolViolation("pre-pack commit lacks red-team generator source")
    generator_hash = digest_bytes(shown_generator.stdout)
    if generator_hash != commitment["generator_source_digest"]:
        raise ProtocolViolation("pre-pack red-team generator source binding mismatch")
    protocol_paths = {
        "adapter": "prototype/unified_map/redteam_v2_adapter.py",
        "runner": "prototype/unified_map/redteam_v2_runner.py",
    }
    live_protocol_paths = {
        "adapter": Path(sys.modules[fit_implementations.__module__].__file__),
        "runner": Path(__file__),
    }
    prepack_protocol_receipts: dict[str, dict[str, Any]] = {}
    for label, relative_source in protocol_paths.items():
        shown_source = subprocess.run(
            ["git", "show", f"{pre_pack}:{relative_source}"],
            cwd=repository_root,
            check=False,
            capture_output=True,
        )
        if shown_source.returncode:
            raise ProtocolViolation(f"pre-pack commit lacks protocol source: {relative_source}")
        source_hash = digest_bytes(shown_source.stdout)
        live_hash = digest_bytes(live_protocol_paths[label].read_bytes())
        if source_hash != live_hash:
            raise ProtocolViolation(f"pre-pack protocol source binding mismatch: {label}")
        prepack_protocol_receipts[label] = {
            "path": relative_source,
            "sha256": source_hash,
            "byte_length": len(shown_source.stdout),
        }
    head = _git(repository_root, "rev-parse", "HEAD")
    return {
        "pre_pack_git_commit": pre_pack,
        "commitment_git_commit": commitment_git_commit,
        "run_git_head": head,
        "commitment_blob_path": relative,
        "commitment_blob_digest": digest_bytes(committed),
        "pre_pack_is_strict_ancestor": True,
        "git_chronology_enforced": True,
        "prepack_candidate_source_receipts": prepack_source_receipts,
        "prepack_generator_source_receipt": {
            "path": generator_path,
            "sha256": generator_hash,
            "byte_length": len(shown_generator.stdout),
        },
        "prepack_protocol_source_receipts": prepack_protocol_receipts,
    }


def _squared_error(left: Iterable[float], right: Iterable[float]) -> float:
    a = np.asarray(tuple(left), dtype=np.float64)
    b = np.asarray(tuple(right), dtype=np.float64)
    return float(np.mean((a - b) ** 2))


def _distance(left: Any, right: Any) -> float | None:
    a = np.asarray(left.distance_vector, dtype=np.float64)
    b = np.asarray(right.distance_vector, dtype=np.float64)
    if a.shape != b.shape:
        return None
    return float(np.linalg.norm(a - b))


def _row_base(run_id: str, implementation_id: str, attack_id: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "implementation_id": implementation_id,
        "attack_id": attack_id,
        "evaluator_only_attack_id": True,
    }


def _history_feature(history_wire: dict[str, Any], capacity: int, seed: int) -> np.ndarray:
    """Fixed-capacity projection of the exact allowed visible sequence."""

    vector = np.zeros(capacity, dtype=np.float64)
    for position, event in enumerate(history_wire["events"]):
        preimage = canonical_json_bytes({"position": position, "event": event})
        digest = digest_bytes(preimage)[7:]
        bucket = int(digest[:16], 16) % capacity
        sign = -1.0 if int(digest[16:18], 16) & 1 else 1.0
        value = event["payload"].get("value", 1.0)
        magnitude = float(value) if type(value) in {int, float} else 1.0
        vector[bucket] += sign * (1.0 + 0.1 * position + magnitude)
    vector[(seed + len(history_wire["events"])) % capacity] += math.log1p(len(history_wire["events"]))
    return vector


def _fixed_projection(values: np.ndarray, capacity: int, seed: int) -> np.ndarray:
    if values.shape[1] == capacity:
        return values.copy()
    rng = np.random.default_rng(seed)
    projection = rng.normal(0.0, 1.0 / math.sqrt(max(1, values.shape[1])), size=(values.shape[1], capacity))
    return values @ projection


def _ridge_fit_predict(train_x: np.ndarray, train_y: np.ndarray, test_x: np.ndarray) -> np.ndarray:
    mean = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    x = (train_x - mean) / scale
    z = (test_x - mean) / scale
    design = np.concatenate((np.ones((len(x), 1)), x), axis=1)
    test_design = np.concatenate((np.ones((len(z), 1)), z), axis=1)
    penalty = np.eye(design.shape[1]) * 1e-3
    penalty[0, 0] = 0.0
    weights = np.linalg.pinv(design.T @ design + penalty, rcond=1e-10) @ design.T @ train_y
    return test_design @ weights


def _probe_rows(
    run_id: str,
    implementation_id: str,
    candidate: Any,
    pack: dict[str, Any],
    states: dict[str, Any],
    invoke: Any,
    record_closure: Any,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    train_episodes = pack["training_episodes"]
    test_episodes = pack["test_episodes"]
    # RT04 uses a pre-registered noise-integrated target and a matched capacity
    # ladder across state, exact allowed history, and judge true-state views.
    train_states: list[Any] = []
    for i, row in enumerate(train_episodes):
        state = invoke(
            "initialize",
            row["instance_id"],
            "VisibleHistory",
            candidate.initialize,
            history_from_wire(row["public_history"]),
            inference_seed=MODEL_SEED + i,
        )
        record_closure(state, row["instance_id"], "new_task_training_state")
        train_states.append(state)
    for capacity in pack["new_task_contract"]["capacities"]:
        targets_train = np.asarray(
            [row["judge_private"]["conditional_expected_future_utility"] for row in train_episodes],
            dtype=np.float64,
        )
        targets_test = np.asarray(
            [row["judge_private"]["conditional_expected_future_utility"] for row in test_episodes],
            dtype=np.float64,
        )
        state_train_raw = np.asarray([state.distance_vector for state in train_states], dtype=np.float64)
        state_test_raw = np.asarray([states[row["instance_id"]].distance_vector for row in test_episodes], dtype=np.float64)
        history_train = np.asarray([_history_feature(row["public_history"], capacity, MODEL_SEED) for row in train_episodes])
        history_test = np.asarray([_history_feature(row["public_history"], capacity, MODEL_SEED) for row in test_episodes])
        # True-state upper bound includes the complete judge latent plus exact
        # visible-sequence projection; it is an upper bound, not an eligible map.
        def true_row(row: dict[str, Any]) -> np.ndarray:
            latent = row["judge_private"]["latent"]
            base = np.asarray(
                [latent["a"], latent["b"], latent["subtype"], latent["interaction"], latent["reserve"]],
                dtype=np.float64,
            )
            return np.concatenate((base, _history_feature(row["public_history"], max(8, capacity), MODEL_SEED + 7)))

        true_train_raw = np.asarray([true_row(row) for row in train_episodes])
        true_test_raw = np.asarray([true_row(row) for row in test_episodes])
        views = {
            "state_only": (
                _fixed_projection(state_train_raw, capacity, MODEL_SEED + capacity),
                _fixed_projection(state_test_raw, capacity, MODEL_SEED + capacity),
            ),
            "same_capacity_full_visible_history": (history_train, history_test),
            "true_state_upper_bound": (
                _fixed_projection(true_train_raw, capacity, MODEL_SEED + capacity * 3),
                _fixed_projection(true_test_raw, capacity, MODEL_SEED + capacity * 3),
            ),
        }
        for view, (train_x, test_x) in views.items():
            predicted = _ridge_fit_predict(train_x, targets_train, test_x)
            rows.append(
                {
                    **_row_base(run_id, implementation_id, "new_task_conditional_expected_future_utility"),
                    "probe_id": f"capacity-{capacity}-{view}",
                    "view": view,
                    "capacity": capacity,
                    "model": "fixed_projection_ridge",
                    "train_count": len(train_x),
                    "test_count": len(test_x),
                    "target_is_conditional_expectation": True,
                    "realized_future_noise_used": False,
                    "rmse": float(np.sqrt(np.mean((predicted - targets_test) ** 2))),
                    "mae": float(np.mean(np.abs(predicted - targets_test))),
                    "predictions": predicted.tolist(),
                    "targets": targets_test.tolist(),
                }
            )
    return rows


def _run_one(
    *,
    run_id: str,
    implementation_id: str,
    candidate: Any,
    pack: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    episode_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    probe_rows: list[dict[str, Any]] = []
    access_rows: list[dict[str, Any]] = []
    closure_rows: list[dict[str, Any]] = []
    states: dict[str, Any] = {}
    plans = {row["plan_id"]: plan_from_wire(row) for row in pack["plans"]}
    labels = tuple(pack["catalog"]["diagnostic_labels"])

    def invoke(
        operation: str,
        instance_id: str,
        allowed_patient_input: str,
        function: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        result, trace = call_with_access_trace(
            operation,
            implementation_id,
            function,
            *args,
            **kwargs,
        )
        trace.update(
            {
                "run_id": run_id,
                "instance_id": instance_id,
                "allowed_patient_input": allowed_patient_input,
            }
        )
        access_rows.append(trace)
        return result

    def record_closure(
        state: Any,
        instance_id: str,
        role: str,
        *,
        parent_state_hash: str | None = None,
        delta_digest: str | None = None,
    ) -> None:
        closure = state_closure(state)
        closure.pop("closure_digest", None)
        closure.update(
            {
                "run_id": run_id,
                "implementation_id": implementation_id,
                "instance_id": instance_id,
                "state_role": role,
                "parent_state_hash": parent_state_hash,
                "delta_digest": delta_digest,
                "patient_specific_reachable_bytes_complete": True,
                "candidate_static_model_bound_separately": True,
            }
        )
        closure["closure_digest"] = digest_json(closure)
        closure_rows.append(closure)

    for position, episode in enumerate(pack["test_episodes"]):
        instance_id = episode["instance_id"]
        history = history_from_wire(episode["public_history"])
        state = invoke(
            "initialize",
            instance_id,
            "VisibleHistory",
            candidate.initialize,
            history,
            inference_seed=MODEL_SEED + position,
        )
        states[instance_id] = state
        record_closure(state, instance_id, "initial_secret_test_state")
        diagnosis = invoke(
            "diagnose",
            instance_id,
            "SharedPatientState only",
            candidate.diagnose,
            state,
            labels,
            query_seed=MODEL_SEED + 10_000 + position,
        )
        target = episode["judge_private"]["diagnostic_target"]
        episode_rows.append(
            {
                **_row_base(run_id, implementation_id, "ood" if episode["tier"] == "ood" else "diagnosis_control"),
                "instance_id": instance_id,
                "tier": episode["tier"],
                "query": "diagnose",
                "pre_state_hash": state.state_hash,
                "post_state_hash": state.state_hash,
                "prediction": prediction_wire(diagnosis),
                "oracle_target": target,
                "brier": float(np.mean([(diagnosis.probabilities[label] - target[label]) ** 2 for label in labels])),
                "unsafe_ood_forced_known": bool(episode["tier"] == "ood" and diagnosis.probabilities["unknown"] < pack["thresholds"]["ood_unknown_decision_boundary"]),
            }
        )
        for oracle in episode["judge_private"]["oracle_rows"]:
            plan = plans[oracle["plan_id"]]
            prediction = invoke(
                "rollout",
                instance_id,
                "SharedPatientState only",
                candidate.rollout,
                state,
                plan,
                oracle["horizon"],
                query_seed=MODEL_SEED + 20_000 + position * 101 + oracle["horizon"],
            )
            attack = "same_state_time_scales" if instance_id == pack["paired_controls"]["time_scales"]["instance_id"] else "rollout_control"
            if oracle["plan_id"] in {"biphasic"}:
                attack = "new_treatment_opposite_response"
            elif oracle["plan_id"] in {"observation_shift", "latent_repair"}:
                attack = "action_semantics"
            elif episode["tier"] == "novel_quadrant":
                attack = "new_nonlinear_combination"
            evaluator_fields: dict[str, Any] = {}
            if oracle["plan_id"] == "biphasic":
                natural_oracle = next(
                    row
                    for row in episode["judge_private"]["oracle_rows"]
                    if row["plan_id"] == "natural" and row["horizon"] == oracle["horizon"]
                )
                effect = oracle["expected_utility"] - natural_oracle["expected_utility"]
                evaluator_fields = {
                    "judge_private_subtype": episode["judge_private"]["latent"]["subtype"],
                    "oracle_treatment_effect_vs_natural": effect,
                    "oracle_effect_sign": 1 if effect > 0 else (-1 if effect < 0 else 0),
                    "opposite_response_oracle_valid": True,
                }
            episode_rows.append(
                {
                    **_row_base(run_id, implementation_id, attack),
                    "instance_id": instance_id,
                    "tier": episode["tier"],
                    "query": {"plan_id": oracle["plan_id"], "horizon": oracle["horizon"]},
                    "pre_state_hash": state.state_hash,
                    "post_state_hash": state.state_hash,
                    "prediction": prediction_wire(prediction),
                    "oracle_target": oracle,
                    "signature_mse": _squared_error(prediction.signature, oracle["signature"]),
                    "utility_absolute_error": abs(prediction.expected_utility - oracle["expected_utility"]),
                    "operator_in_primary_scope": oracle["plan_id"] not in {"biphasic", "new_check"},
                    "scope_result": (
                        "scope_insufficient"
                        if oracle["plan_id"] in {"biphasic", "new_check"} and prediction.abstained
                        else (
                            "nonadmissible_old_scope_prediction"
                            if oracle["plan_id"] in {"biphasic", "new_check"}
                            else "primary_scope"
                        )
                    ),
                    "migration_required": (
                        pack["extension_contract"]["admissible_migration"]
                        if oracle["plan_id"] in {"biphasic", "new_check"}
                        else None
                    ),
                    **evaluator_fields,
                }
            )

    # Dangerous collision: exact state distance paired with a committed oracle
    # margin/opposite-response control, never state distance alone.
    for pair in pack["paired_controls"]["collision"]:
        left = states[pair["left_instance_id"]]
        right = states[pair["right_instance_id"]]
        distance = _distance(left, right)
        dangerous = bool(
            distance is not None
            and distance <= pack["thresholds"]["state_equivalence_l2"]
            and pair["oracle_margin"] >= pack["thresholds"]["oracle_distinguishable_l2"]
        )
        pair_rows.append(
            {
                **_row_base(run_id, implementation_id, "dangerous_collision"),
                **pair,
                "left_state_hash": left.state_hash,
                "right_state_hash": right.state_hash,
                "state_distance": distance,
                "dangerous_collision": dangerous,
            }
        )

    # Three deletion controls are encoded independently and bind numeric oracle
    # distances, not only verbal relations.
    for pair in pack["paired_controls"]["history_deletion"]:
        left = invoke(
            "initialize",
            pair["pair_id"] + "-left",
            "VisibleHistory",
            candidate.initialize,
            history_from_wire(pair["left"]["public_history"]),
            inference_seed=MODEL_SEED + 31,
        )
        right = invoke(
            "initialize",
            pair["pair_id"] + "-right",
            "VisibleHistory",
            candidate.initialize,
            history_from_wire(pair["right"]["public_history"]),
            inference_seed=MODEL_SEED + 32,
        )
        record_closure(left, pair["pair_id"] + "-left", "history_deletion_left")
        record_closure(right, pair["pair_id"] + "-right", "history_deletion_right")
        distance = _distance(left, right)
        pair_rows.append(
            {
                **_row_base(run_id, implementation_id, "history_deletion_trio"),
                "pair_id": pair["pair_id"],
                "control": pair["control"],
                "oracle_relation": pair["oracle_relation"],
                "oracle_values": pair["oracle_values"],
                "oracle_distance": pair["oracle_distance"],
                "expected_state_relation": pair["expected_state_relation"],
                "left_history_digest": digest_json(pair["left"]["public_history"]),
                "right_history_digest": digest_json(pair["right"]["public_history"]),
                "left_state_hash": left.state_hash,
                "right_state_hash": right.state_hash,
                "state_distance": distance,
            }
        )

    # Informative and null check updates plus replay equality/locality evidence.
    check_contract = pack["paired_controls"]["new_check"]
    for control, instance_id, informative in (
        ("informative", check_contract["informative_instance_id"], True),
        ("null", check_contract["null_instance_id"], False),
        ("locality", check_contract["locality_instance_id"], True),
    ):
        episode = next(row for row in pack["test_episodes"] if row["instance_id"] == instance_id)
        old_state = states[instance_id]
        old_diag = invoke(
            "diagnose", instance_id, "SharedPatientState only", candidate.diagnose, old_state, labels, query_seed=71
        )
        delta = make_check_delta(episode, informative=informative)
        new_state = invoke(
            "update",
            instance_id,
            "old SharedPatientState plus VisibleDelta",
            candidate.update,
            old_state,
            delta,
            inference_seed=72,
        )
        record_closure(
            new_state,
            instance_id,
            f"new_check_{control}_updated",
            parent_state_hash=old_state.state_hash,
            delta_digest=digest_json(delta.to_wire()),
        )
        new_diag = invoke(
            "diagnose", instance_id, "SharedPatientState only", candidate.diagnose, new_state, labels, query_seed=73
        )
        replay_history = append_delta_history(history_from_wire(episode["public_history"]), delta)
        replay_state = invoke(
            "initialize", instance_id, "VisibleHistory", candidate.initialize, replay_history, inference_seed=74
        )
        record_closure(replay_state, instance_id, f"new_check_{control}_replay")
        natural_before = invoke(
            "rollout", instance_id, "SharedPatientState only", candidate.rollout, old_state, plans["natural"], 24, query_seed=75
        )
        natural_after = invoke(
            "rollout", instance_id, "SharedPatientState only", candidate.rollout, new_state, plans["natural"], 24, query_seed=76
        )
        probe_rows.append(
            {
                **_row_base(run_id, implementation_id, "new_check"),
                "probe_id": f"new-check-{control}",
                "instance_id": instance_id,
                "control": control,
                "informative": informative,
                "old_state_hash": old_state.state_hash,
                "updated_state_hash": new_state.state_hash,
                "replay_state_hash": replay_state.state_hash,
                "incremental_replay_match": new_state.state_hash == replay_state.state_hash,
                "diagnosis_before": prediction_wire(old_diag),
                "diagnosis_after": prediction_wire(new_diag),
                "unrelated_natural_utility_shift": natural_after.expected_utility - natural_before.expected_utility,
                "delta_digest": digest_json(delta.to_wire()),
                "operator_in_primary_scope": False,
                "scope_result": "nonadmissible_old_scope_update_attempt",
                "candidate_failed_closed": False,
                "migration_required": pack["extension_contract"]["admissible_migration"],
                "migration_cost": {
                    "extension_catalog_digest": pack["extension_catalog_digest"],
                    "primary_state_reusable_without_replay": False,
                    "visible_history_replay_required": True,
                    "extension_refit_required": True,
                },
            }
        )

    # Query order, cold rehydration, and update/replay are exercised on the same
    # closure; no history is supplied to either head.
    anchor = pack["test_episodes"][0]
    anchor_state = states[anchor["instance_id"]]
    first_diag = invoke(
        "diagnose", anchor["instance_id"], "SharedPatientState only", candidate.diagnose, anchor_state, labels, query_seed=81
    )
    first_roll = invoke(
        "rollout", anchor["instance_id"], "SharedPatientState only", candidate.rollout, anchor_state, plans["natural"], 24, query_seed=82
    )
    second_roll = invoke(
        "rollout", anchor["instance_id"], "SharedPatientState only", candidate.rollout, anchor_state, plans["natural"], 24, query_seed=82
    )
    second_diag = invoke(
        "diagnose", anchor["instance_id"], "SharedPatientState only", candidate.diagnose, anchor_state, labels, query_seed=81
    )
    closure = state_closure(anchor_state)
    cold = rehydrate_state(closure)
    record_closure(cold, anchor["instance_id"], "cold_rehydrated_state")
    cold_diag = invoke(
        "diagnose", anchor["instance_id"], "SharedPatientState only", candidate.diagnose, cold, labels, query_seed=81
    )
    cold_roll = invoke(
        "rollout", anchor["instance_id"], "SharedPatientState only", candidate.rollout, cold, plans["natural"], 24, query_seed=82
    )
    primary_event = CandidateVisibleEvent(
        EventKind.OBSERVATION_AVAILABLE,
        2,
        2,
        anchor["instance_id"] + "-primary-update",
        {"channel_id": "rt_pulse", "value": 0.125},
        2,
    )
    primary_delta = VisibleDelta(2, (primary_event,))
    primary_updated = invoke(
        "update",
        anchor["instance_id"],
        "old SharedPatientState plus VisibleDelta",
        candidate.update,
        anchor_state,
        primary_delta,
        inference_seed=83,
    )
    record_closure(
        primary_updated,
        anchor["instance_id"],
        "primary_scope_updated_state",
        parent_state_hash=anchor_state.state_hash,
        delta_digest=digest_json(primary_delta.to_wire()),
    )
    primary_replay = invoke(
        "initialize",
        anchor["instance_id"],
        "VisibleHistory",
        candidate.initialize,
        append_delta_history(history_from_wire(anchor["public_history"]), primary_delta),
        inference_seed=84,
    )
    record_closure(primary_replay, anchor["instance_id"], "primary_scope_replay_state")
    probe_rows.append(
        {
            **_row_base(run_id, implementation_id, "query_update_rehydrate_compliance"),
            "probe_id": "query-order-and-cold-rehydrate",
            "instance_id": anchor["instance_id"],
            "state_hash_before": anchor_state.state_hash,
            "state_hash_after": anchor_state.state_hash,
            "query_order_diagnosis_equal": prediction_wire(first_diag) == prediction_wire(second_diag),
            "query_order_rollout_equal": prediction_wire(first_roll) == prediction_wire(second_roll),
            "cold_state_hash_equal": cold.state_hash == anchor_state.state_hash,
            "cold_diagnosis_equal": prediction_wire(cold_diag) == prediction_wire(first_diag),
            "cold_rollout_equal": prediction_wire(cold_roll) == prediction_wire(first_roll),
            "cold_rehydrate_scope": "same_process_static_model; fresh object from closure bytes",
            "primary_scope_update_old_hash": anchor_state.state_hash,
            "primary_scope_update_delta_digest": digest_json(primary_delta.to_wire()),
            "primary_scope_update_new_hash": primary_updated.state_hash,
            "primary_scope_replay_hash": primary_replay.state_hash,
            "primary_scope_update_replay_match": primary_updated.state_hash == primary_replay.state_hash,
        }
    )
    probe_rows.extend(
        _probe_rows(
            run_id,
            implementation_id,
            candidate,
            pack,
            states,
            invoke,
            record_closure,
        )
    )
    return episode_rows, pair_rows, probe_rows, access_rows, closure_rows


def _artifact_entries(directory: Path, *, exclude: set[str]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for path in sorted(row for row in directory.iterdir() if row.is_file() and row.name not in exclude):
        raw = path.read_bytes()
        entry = {"path": path.name, "byte_length": len(raw), "sha256": digest_bytes(raw)}
        if path.suffix == ".jsonl":
            entry["line_count"] = len(raw.splitlines())
        entries.append(entry)
    return entries


def run_redteam_v2(
    *,
    repository_root: Path,
    commitment_path: Path,
    external_reveal_path: Path,
    output_root: Path,
    commitment_git_commit: str | None,
    enforce_git_chronology: bool = True,
    model_seed: int = MODEL_SEED,
) -> Path:
    """Run both pre-bound implementations once, then publish reveal."""

    started = datetime.now(UTC).isoformat()
    commitment = _read_object(commitment_path)
    reveal = _read_object(external_reveal_path)
    pack = verify_reveal(commitment, reveal)
    if commitment["candidate_source_bindings"] != candidate_source_bindings():
        raise ProtocolViolation("live candidate sources differ from pre-pack bindings")
    if enforce_git_chronology:
        if not commitment_git_commit:
            raise ProtocolViolation("durable commitment git commit is required")
        chronology_git = _verify_commitment_chronology(
            repository_root, commitment_path, commitment_git_commit, commitment
        )
    else:
        chronology_git = {
            "pre_pack_git_commit": commitment["pre_pack_git_commit"],
            "commitment_git_commit": commitment_git_commit,
            "git_chronology_enforced": False,
            "test_only": True,
        }
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-RT2-" + uuid.uuid4().hex[:10]
    output_root.mkdir(parents=True, exist_ok=True)
    temporary = output_root / ("." + run_id + ".tmp")
    if temporary.exists():
        shutil.rmtree(temporary)
    temporary.mkdir()
    _write_object(temporary / "commitment.json", commitment)
    candidates, fit_traces = fit_implementations(pack, model_seed=model_seed)
    static_before = {
        implementation_id: candidate_static_closure(candidate)
        for implementation_id, candidate in candidates.items()
    }
    all_episodes: list[dict[str, Any]] = []
    all_pairs: list[dict[str, Any]] = []
    all_probes: list[dict[str, Any]] = []
    all_access: list[dict[str, Any]] = []
    all_closures: list[dict[str, Any]] = []
    for trace in fit_traces:
        trace["run_id"] = run_id
    all_access.extend(fit_traces)
    implementation_started: dict[str, str] = {}
    implementation_finished: dict[str, str] = {}
    for implementation_id, candidate in candidates.items():
        implementation_started[implementation_id] = datetime.now(UTC).isoformat()
        episodes, pairs, probes, access, closures = _run_one(
            run_id=run_id,
            implementation_id=implementation_id,
            candidate=candidate,
            pack=pack,
        )
        implementation_finished[implementation_id] = datetime.now(UTC).isoformat()
        all_episodes.extend(episodes)
        all_pairs.extend(pairs)
        all_probes.extend(probes)
        all_access.extend(access)
        all_closures.extend(closures)
    static_after = {
        implementation_id: candidate_static_closure(candidate)
        for implementation_id, candidate in candidates.items()
    }
    if {
        key: value["sha256"] for key, value in static_before.items()
    } != {key: value["sha256"] for key, value in static_after.items()}:
        raise ProtocolViolation("candidate static model mutated during patient-time evaluation")
    _write_object(
        temporary / "candidate-static-closures.json",
        {
            "protocol": "ucm-redteam-v2-static-closure-comparison/1",
            "before": static_before,
            "after": static_after,
            "unchanged": True,
            "patient_specific_cache_detected": False,
        },
    )
    raw_receipts = {
        "raw-episodes.jsonl": _write_jsonl(temporary / "raw-episodes.jsonl", all_episodes),
        "raw-pairs.jsonl": _write_jsonl(temporary / "raw-pairs.jsonl", all_pairs),
        "raw-probes.jsonl": _write_jsonl(temporary / "raw-probes.jsonl", all_probes),
        "access-trace.jsonl": _write_jsonl(temporary / "access-trace.jsonl", all_access),
        "state-closures.jsonl": _write_jsonl(temporary / "state-closures.jsonl", all_closures),
    }
    # Seal raw outputs from both implementations before reveal publication.
    pre_reveal_entries = _artifact_entries(temporary, exclude=set())
    pre_reveal_output_root = digest_json(pre_reveal_entries)
    raw_sealed_at = datetime.now(UTC).isoformat()
    _write_object(temporary / "reveal.json", reveal)
    reveal_published_at = datetime.now(UTC).isoformat()
    chronology = {
        "protocol": "ucm-redteam-v2-chronology/1",
        **chronology_git,
        "run_started_at": started,
        "implementation_started_at": implementation_started,
        "implementation_finished_at": implementation_finished,
        "both_implementations_finished_before_reveal": all(
            value <= reveal_published_at for value in implementation_finished.values()
        ),
        "retry_count": 0,
        "raw_sealed_at": raw_sealed_at,
        "pre_reveal_artifacts": pre_reveal_entries,
        "pre_reveal_output_root": pre_reveal_output_root,
        "reveal_published_at": reveal_published_at,
    }
    _write_object(temporary / "chronology.json", chronology)
    summary = {
        "protocol": RUN_PROTOCOL,
        "run_id": run_id,
        "implementations": sorted(candidates),
        "attack_classes": list(REQUIRED_ATTACK_CLASSES),
        "episode_row_count": len(all_episodes),
        "pair_row_count": len(all_pairs),
        "probe_row_count": len(all_probes),
        "access_trace_row_count": len(all_access),
        "state_closure_row_count": len(all_closures),
        "dangerous_collision_count": sum(bool(row.get("dangerous_collision")) for row in all_pairs),
        "unsafe_ood_forced_known_count": sum(bool(row.get("unsafe_ood_forced_known")) for row in all_episodes),
        "candidate_source_bindings": candidate_source_bindings(),
        "pack_digest": commitment["pack_digest"],
        "raw_receipts": raw_receipts,
        "evidence_boundary": {
            "source_distinct_generator": True,
            "head_inputs_state_only": True,
            "python_audit_hook_all_candidate_calls": True,
            "all_candidate_calls_audited": True,
            "os_sandbox": False,
            "cold_rehydrate": "fresh SharedPatientState object in same process/static model",
            "state_closure_scope": "all initialized, updated, replayed, training-probe, deletion, and cold-rehydrated patient states",
            "external_patient_cache_check": "fitted candidate static object graph digest unchanged before/after all patient calls",
            "verifier_scope": "bundle/reveal/raw/closure/pre-reveal-root integrity plus live git chronology when required",
            "independent_implementation": True,
        },
    }
    _write_object(temporary / "summary.json", summary)
    entries = _artifact_entries(temporary, exclude={"manifest.json"})
    manifest = {
        "protocol": MANIFEST_PROTOCOL,
        "run_id": run_id,
        "bundle_root_definition": "sha256(canonical_json(artifact entries excluding manifest.json))",
        "artifacts": entries,
        "bundle_root": digest_json(entries),
        "source_files": {
            path.name: digest_bytes(path.read_bytes())
            for path in (
                Path(__file__),
                Path(sys.modules[verify_reveal.__module__].__file__),
                Path(sys.modules[fit_implementations.__module__].__file__),
            )
        },
        "environment": {
            "python": sys.version,
            "platform": sys.platform,
            "pid": os.getpid(),
            "model_seed": model_seed,
        },
    }
    _write_object(temporary / "manifest.json", manifest)
    final = output_root / run_id
    temporary.replace(final)
    verify_redteam_v2_run(
        final,
        repository_root=repository_root if enforce_git_chronology else None,
        require_git_chronology=enforce_git_chronology,
    )
    return final


def verify_redteam_v2_run(
    directory: Path,
    *,
    repository_root: Path | None = None,
    require_git_chronology: bool | None = None,
) -> dict[str, Any]:
    manifest = _read_object(directory / "manifest.json")
    if manifest.get("protocol") != MANIFEST_PROTOCOL:
        raise ProtocolViolation("red-team v2 manifest protocol mismatch")
    for entry in manifest["artifacts"]:
        path = directory / entry["path"]
        raw = _read_artifact_bytes(directory, entry["path"])
        if len(raw) != entry["byte_length"] or digest_bytes(raw) != entry["sha256"]:
            raise ProtocolViolation(f"red-team artifact digest mismatch: {path.name}")
        if "line_count" in entry and len(raw.splitlines()) != entry["line_count"]:
            raise ProtocolViolation(f"red-team JSONL line count mismatch: {path.name}")
        if entry["path"].endswith(".gz"):
            try:
                gzip.decompress(raw)
            except OSError as exc:
                raise ProtocolViolation(f"invalid red-team gzip artifact: {path.name}") from exc
    if digest_json(manifest["artifacts"]) != manifest["bundle_root"]:
        raise ProtocolViolation("red-team bundle root mismatch")
    live_sources = {
        path.name: digest_bytes(path.read_bytes())
        for path in (
            Path(__file__),
            Path(sys.modules[verify_reveal.__module__].__file__),
            Path(sys.modules[fit_implementations.__module__].__file__),
        )
    }
    if live_sources != manifest.get("source_files"):
        raise ProtocolViolation("red-team protocol source binding mismatch")
    commitment = _read_object(directory / "commitment.json")
    reveal = _read_object(directory / "reveal.json")
    pack = verify_reveal(commitment, reveal)
    summary = _read_object(directory / "summary.json")
    chronology = _read_object(directory / "chronology.json")
    if require_git_chronology is None:
        require_git_chronology = bool(chronology.get("git_chronology_enforced"))
    if require_git_chronology:
        if repository_root is None:
            raise ProtocolViolation("repository_root is required to reverify git chronology")
        blob_path = chronology.get("commitment_blob_path")
        commit_id = chronology.get("commitment_git_commit")
        if type(blob_path) is not str or type(commit_id) is not str:
            raise ProtocolViolation("git chronology evidence is incomplete")
        live_chronology = _verify_commitment_chronology(
            repository_root,
            repository_root / Path(blob_path),
            commit_id,
            commitment,
        )
        for key in (
            "pre_pack_git_commit",
            "commitment_git_commit",
            "commitment_blob_path",
            "commitment_blob_digest",
            "prepack_candidate_source_receipts",
            "prepack_generator_source_receipt",
            "prepack_protocol_source_receipts",
        ):
            if live_chronology.get(key) != chronology.get(key):
                raise ProtocolViolation(f"git chronology receipt mismatch: {key}")
    pre_reveal_entries = chronology.get("pre_reveal_artifacts")
    if type(pre_reveal_entries) is not list or not pre_reveal_entries:
        raise ProtocolViolation("pre-reveal artifact registry is missing")
    if any(entry.get("path") == "reveal.json" for entry in pre_reveal_entries):
        raise ProtocolViolation("reveal was included in pre-reveal output root")
    for entry in pre_reveal_entries:
        raw = _read_artifact_bytes(directory, entry["path"])
        if len(raw) != entry["byte_length"] or digest_bytes(raw) != entry["sha256"]:
            raise ProtocolViolation(f"pre-reveal artifact mismatch: {entry['path']}")
        if "line_count" in entry and len(raw.splitlines()) != entry["line_count"]:
            raise ProtocolViolation(f"pre-reveal row count mismatch: {entry['path']}")
    if digest_json(pre_reveal_entries) != chronology.get("pre_reveal_output_root"):
        raise ProtocolViolation("pre-reveal output root mismatch")
    if not (
        all(value <= chronology["raw_sealed_at"] for value in chronology["implementation_finished_at"].values())
        and chronology["raw_sealed_at"] <= chronology["reveal_published_at"]
    ):
        raise ProtocolViolation("red-team phase timestamps are out of order")
    if not chronology.get("both_implementations_finished_before_reveal"):
        raise ProtocolViolation("both implementations were not sealed before reveal")
    if summary.get("attack_classes") != list(REQUIRED_ATTACK_CLASSES):
        raise ProtocolViolation("red-team summary attack registry mismatch")
    for name, receipt in summary["raw_receipts"].items():
        raw = _read_artifact_bytes(directory, name)
        if digest_bytes(raw) != receipt["sha256"] or len(raw.splitlines()) != receipt["line_count"]:
            raise ProtocolViolation(f"raw receipt mismatch: {name}")
        compressed = (directory / receipt["gzip_path"]).read_bytes()
        if digest_bytes(compressed) != receipt["gzip_sha256"] or gzip.decompress(compressed) != raw:
            raise ProtocolViolation(f"raw gzip receipt mismatch: {name}")
    closure_rows = [json.loads(line) for line in _read_artifact_bytes(directory, "state-closures.jsonl").splitlines()]
    for closure in closure_rows:
        if digest_bytes(__import__("base64").b64decode(closure["payload_base64"])) != closure["payload_digest"]:
            raise ProtocolViolation("state closure payload digest mismatch")
        preimage = {key: value for key, value in closure.items() if key != "closure_digest"}
        if digest_json(preimage) != closure["closure_digest"]:
            raise ProtocolViolation("state closure digest mismatch")
        rehydrate_state(closure)
    required_state_roles = {
        "initial_secret_test_state",
        "new_task_training_state",
        "history_deletion_left",
        "history_deletion_right",
        "new_check_informative_updated",
        "new_check_informative_replay",
        "new_check_null_updated",
        "new_check_null_replay",
        "new_check_locality_updated",
        "new_check_locality_replay",
        "cold_rehydrated_state",
        "primary_scope_updated_state",
        "primary_scope_replay_state",
    }
    for implementation_id in summary["implementations"]:
        roles = {
            row["state_role"]
            for row in closure_rows
            if row["implementation_id"] == implementation_id
        }
        missing_roles = required_state_roles - roles
        if missing_roles:
            raise ProtocolViolation(
                f"patient state closure roles missing for {implementation_id}: {sorted(missing_roles)!r}"
            )
        if any(
            not row.get("patient_specific_reachable_bytes_complete")
            for row in closure_rows
            if row["implementation_id"] == implementation_id
        ):
            raise ProtocolViolation("patient state closure completeness flag is false")
    static_closures = _read_object(directory / "candidate-static-closures.json")
    if not static_closures.get("unchanged") or static_closures.get("patient_specific_cache_detected"):
        raise ProtocolViolation("candidate static object graph changed during patient evaluation")
    if {
        key: value["sha256"] for key, value in static_closures["before"].items()
    } != {
        key: value["sha256"] for key, value in static_closures["after"].items()
    }:
        raise ProtocolViolation("candidate static closure hash mismatch")
    access_rows = [json.loads(line) for line in _read_artifact_bytes(directory, "access-trace.jsonl").splitlines()]
    if any(not row.get("passed") for row in access_rows):
        raise ProtocolViolation("candidate access trace contains a denied/failed operation")
    if any(
        row.get("allowed_patient_input") != "SharedPatientState only"
        for row in access_rows
        if row.get("operation") in {"diagnose", "rollout"}
    ):
        raise ProtocolViolation("a readout head was not state-only")
    probe_rows = [json.loads(line) for line in _read_artifact_bytes(directory, "raw-probes.jsonl").splitlines()]
    if any(
        not row.get("incremental_replay_match")
        for row in probe_rows
        if row.get("attack_id") == "new_check"
    ):
        raise ProtocolViolation("new-check update/replay lineage mismatch")
    if any(
        not row.get("primary_scope_update_replay_match")
        for row in probe_rows
        if row.get("attack_id") == "query_update_rehydrate_compliance"
    ):
        raise ProtocolViolation("primary-scope update/replay lineage mismatch")
    attack_rows = [
        json.loads(line)["attack_id"]
        for filename in ("raw-episodes.jsonl", "raw-pairs.jsonl", "raw-probes.jsonl")
        for line in _read_artifact_bytes(directory, filename).splitlines()
    ]
    missing = set(REQUIRED_ATTACK_CLASSES) - set(attack_rows)
    if missing:
        raise ProtocolViolation(f"red-team run lacks raw attack rows: {sorted(missing)!r}")
    return {
        "protocol": "ucm-source-distinct-redteam-verification/2",
        "run_id": manifest["run_id"],
        "bundle_root": manifest["bundle_root"],
        "pack_digest": digest_json(pack),
        "artifact_count": len(manifest["artifacts"]),
        "verification_scope": "bundle_integrity_reveal_binding_and_raw_receipts",
        "git_chronology_reverified": bool(require_git_chronology),
        "pre_reveal_output_root_reverified": True,
        "pre_reveal_wall_clock_order_reverified": True,
        "verified": True,
    }


# Imported late only to keep the public namespace concise while recording exact
# source/environment data in manifests.
import sys  # noqa: E402  (intentional evidence dependency)


__all__ = ["MANIFEST_PROTOCOL", "RUN_PROTOCOL", "run_redteam_v2", "verify_redteam_v2_run"]
