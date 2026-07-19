"""Portable, live hard-compliance audit for the sealed F18 candidate.

The audit fits and instantiates the real F18 implementation.  It then treats
``SharedPatientState`` as the only patient-specific head input and records each
runtime access and state-closure assertion in separately bound JSONL files.
Source inspection is deliberately supplementary to the live guards.
"""

from __future__ import annotations

import argparse
import ast
import inspect
import json
import textwrap
import time
import uuid
from contextlib import contextmanager
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

import numpy as np

from .benchmark_v1_contract import (
    DiagnosisPrediction,
    RolloutPrediction,
    SharedPatientState,
    build_public_training_record,
)
from .candidate_families import make_candidate
from .candidate_seal import verify_candidate_seal
from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes, digest_json
from .schema import (
    CandidateVisibleEvent,
    PRIVILEGED_FIELD_NAMES,
    VisibleDelta,
    VisibleHistory,
)
from .world_registry import WORLD_REGISTRY
from .worlds.base import WorldSplit


REPO_ROOT = Path(__file__).resolve().parents[2]
PROTOCOL = "ucm-f18-hard-compliance/1"
MANIFEST_PROTOCOL = "ucm-f18-hard-compliance-manifest/1"
TRAIN_SEED = 941_003
EVAL_SEED = 942_007
MODEL_SEED = 104_729
TRAIN_RECORDS = 16


class RawHistoryAccessBlocked(RuntimeError):
    """Positive signal from the live head-phase raw-history trap."""


def _json_file(path: Path) -> dict[str, Any]:
    raw = path.read_bytes()
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"invalid JSON artifact: {path.name}") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"artifact is not canonical JSON: {path.name}")
    return value


def _jsonl_file(path: Path) -> list[dict[str, Any]]:
    raw = path.read_bytes()
    if not raw or not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise ProtocolViolation(f"artifact is not canonical JSONL: {path.name}")
    rows: list[dict[str, Any]] = []
    rebuilt = bytearray()
    for line in raw.splitlines(keepends=True):
        try:
            row = json.loads(line)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation(f"invalid JSONL row: {path.name}") from exc
        if type(row) is not dict or canonical_json_bytes(row) != line:
            raise ProtocolViolation(f"noncanonical JSONL row: {path.name}")
        rows.append(row)
        rebuilt.extend(canonical_json_bytes(row))
    if bytes(rebuilt) != raw:
        raise ProtocolViolation(f"JSONL reconstruction mismatch: {path.name}")
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_bytes(b"".join(canonical_json_bytes(row) for row in rows))


def _array_digest(value: np.ndarray) -> dict[str, Any]:
    contiguous = np.ascontiguousarray(value)
    return {
        "dtype": contiguous.dtype.str,
        "shape": list(contiguous.shape),
        "sha256": digest_bytes(contiguous.tobytes()),
    }


def _model_fingerprint(candidate: Any) -> str:
    """Digest fitted parameters before/after heads to expose task caches."""

    models = []
    for catalog_digest, model in sorted(candidate._models.items()):
        models.append(
            {
                "catalog_digest": catalog_digest,
                "catalog_object_digest": model.catalog.digest,
                "labels": list(model.labels),
                "query_keys": list(model.query_keys),
                "representation_data": model.representation_data,
                "diagnosis_weights": _array_digest(model.diagnosis_weights),
                "rollout_weights": {
                    key: _array_digest(weights)
                    for key, weights in sorted(model.rollout_weights.items())
                },
            }
        )
    return digest_json(
        {
            "candidate_id": candidate.candidate_id,
            "family_id": candidate.family_id,
            "model_seed": candidate._model_seed,
            "regularization": candidate.regularization,
            "models": models,
        }
    )


def _prediction_wire(value: DiagnosisPrediction | RolloutPrediction) -> dict[str, Any]:
    if type(value) is DiagnosisPrediction:
        return {"kind": "diagnosis", "probabilities": value.probabilities}
    if type(value) is RolloutPrediction:
        return {
            "kind": "rollout",
            "signature": list(value.signature),
            "expected_utility": value.expected_utility,
            "abstained": value.abstained,
        }
    raise ProtocolViolation("unknown head output")


def _state_snapshot(state: SharedPatientState) -> dict[str, Any]:
    return {
        "state_hash": state.state_hash,
        "payload_sha256": digest_bytes(state.payload),
        "payload_bytes": len(state.payload),
        "distance_vector_sha256": digest_json(list(state.distance_vector)),
        "distance_dimension": len(state.distance_vector),
        "schema_version": state.schema_version,
        "compactness_class": state.compactness_class,
    }


def _object_patient_specific_types(root: Any) -> list[str]:
    """Find retained patient wires without serializing or invoking callbacks."""

    forbidden_types = (VisibleHistory, VisibleDelta, CandidateVisibleEvent, SharedPatientState)
    seen: set[int] = set()
    hits: list[str] = []

    def walk(value: Any, path: str, depth: int) -> None:
        if depth > 12 or id(value) in seen:
            return
        seen.add(id(value))
        if isinstance(value, forbidden_types):
            hits.append(f"{path}:{type(value).__name__}")
            return
        if value is None or type(value) in {bool, int, float, str, bytes}:
            return
        if isinstance(value, np.ndarray):
            return
        if type(value) is dict:
            for key, item in value.items():
                walk(item, f"{path}.{key}", depth + 1)
            return
        if type(value) in {tuple, list}:
            for index, item in enumerate(value):
                walk(item, f"{path}[{index}]", depth + 1)
            return
        if is_dataclass(value) and not isinstance(value, type):
            for field in fields(value):
                walk(getattr(value, field.name), f"{path}.{field.name}", depth + 1)
            return
        namespace = getattr(value, "__dict__", None)
        if type(namespace) is dict:
            for key, item in namespace.items():
                walk(item, f"{path}.{key}", depth + 1)

    walk(root, "$candidate", 0)
    return sorted(hits)


def _payload_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if type(value) is dict:
        for key, item in value.items():
            keys.append(key)
            keys.extend(_payload_keys(item))
    elif type(value) is list:
        for item in value:
            keys.extend(_payload_keys(item))
    return keys


@contextmanager
def _raw_history_guard(accesses: list[dict[str, Any]]) -> Iterator[dict[str, str]]:
    """Make any raw ``VisibleHistory`` attribute read fail during head calls."""

    original = VisibleHistory.__getattribute__
    phase = {"value": "positive_control"}

    def guarded(instance: VisibleHistory, name: str) -> Any:
        if not name.startswith("__"):
            accesses.append({"phase": phase["value"], "attribute": name})
            raise RawHistoryAccessBlocked(f"raw VisibleHistory.{name} access blocked")
        return original(instance, name)

    VisibleHistory.__getattribute__ = guarded  # type: ignore[method-assign]
    try:
        yield phase
    finally:
        VisibleHistory.__getattribute__ = original  # type: ignore[method-assign]


def _split_history(history: VisibleHistory) -> tuple[VisibleHistory, VisibleDelta]:
    cuts = sorted({event.available_at for event in history.events})
    if len(cuts) < 2:
        raise ProtocolViolation("audit episode lacks a nonempty incremental suffix")
    cut = cuts[len(cuts) // 2 - 1]
    prefix_events = tuple(event for event in history.events if event.available_at <= cut)
    suffix_events = tuple(event for event in history.events if event.available_at > cut)
    if not prefix_events or not suffix_events:
        raise ProtocolViolation("audit history split is empty")
    return (
        VisibleHistory(prefix_events, cut, history.catalog_digest),
        VisibleDelta(history.as_of_available_at, suffix_events),
    )


def _source_audit(candidate: Any) -> dict[str, Any]:
    callables = {
        "diagnose": candidate.diagnose.__func__,
        "rollout": candidate.rollout.__func__,
        "update": candidate.update.__func__,
        "decoded": candidate._decoded.__func__,
    }
    forbidden = set(PRIVILEGED_FIELD_NAMES) | {
        "visible_history",
        "task_state",
        "task_states",
        "patient_cache",
        "history_cache",
    }
    hits: list[dict[str, str]] = []
    source_digests: dict[str, str] = {}
    ast_names: dict[str, list[str]] = {}
    signatures: dict[str, list[str]] = {}
    for label, function in callables.items():
        source = textwrap.dedent(inspect.getsource(function))
        source_digests[label] = digest_bytes(source.encode("utf-8"))
        tree = ast.parse(source)
        names = sorted(
            {
                node.id.lower()
                for node in ast.walk(tree)
                if isinstance(node, ast.Name)
            }
            | {
                node.attr.lower()
                for node in ast.walk(tree)
                if isinstance(node, ast.Attribute)
            }
        )
        ast_names[label] = names
        signatures[label] = list(inspect.signature(function).parameters)
        lowered = source.encode("utf-8").lower()
        for token in sorted(forbidden):
            if token.encode("ascii") in lowered or token in names:
                hits.append({"callable": label, "token": token})
    expected = {
        "diagnose": ["self", "state", "label_catalog", "query_seed"],
        "rollout": ["self", "state", "policy", "horizon", "query_seed"],
        "update": ["self", "state", "delta", "inference_seed"],
    }
    signature_pass = all(signatures[name] == parameters for name, parameters in expected.items())
    return {
        "callable_source_digests": source_digests,
        "callable_ast_names": ast_names,
        "signatures": signatures,
        "expected_signatures": expected,
        "signature_pass": signature_pass,
        "forbidden_identifier_hits": hits,
        "passed": signature_pass and not hits,
    }


def _head_call(
    *,
    candidate: Any,
    state: SharedPatientState,
    operation: str,
    patient: str,
    access_rows: list[dict[str, Any]],
    invoke: Any,
) -> dict[str, Any]:
    before_state = _state_snapshot(state)
    before_model = _model_fingerprint(candidate)
    output = invoke()
    after_state = _state_snapshot(state)
    after_model = _model_fingerprint(candidate)
    output_wire = _prediction_wire(output)
    row = {
        "sequence": len(access_rows) + 1,
        "phase": "head",
        "operation": operation,
        "patient": patient,
        "input_type": type(state).__name__,
        "input_state_hash": state.state_hash,
        "state_before": before_state,
        "state_after": after_state,
        "model_fingerprint_before": before_model,
        "model_fingerprint_after": after_model,
        "output_digest": digest_json(output_wire),
        "state_immutable": before_state == after_state,
        "model_immutable": before_model == after_model,
        "passed": type(state) is SharedPatientState
        and before_state == after_state
        and before_model == after_model,
    }
    access_rows.append(row)
    return output_wire


def run_audit(*, seal_path: Path, output_root: Path, training_records: int = TRAIN_RECORDS) -> Path:
    started = time.perf_counter()
    seal_path = seal_path.resolve()
    seal = verify_candidate_seal(seal_path)
    if seal["candidate"]["family_code"] != "F18":
        raise ProtocolViolation("candidate seal is not F18")
    world = WORLD_REGISTRY["W01"].panels[0].instantiate()
    training = tuple(
        build_public_training_record(
            world,
            world.generate_episode(WorldSplit.TRAIN, TRAIN_SEED, index),
            oracle_seed=TRAIN_SEED + 10_000 + index,
        )
        for index in range(training_records)
    )
    candidate = make_candidate("F18")
    candidate.fit((world.catalog,), training, model_seed=MODEL_SEED)
    fresh_candidate = make_candidate("F18")
    fresh_candidate.fit((world.catalog,), training, model_seed=MODEL_SEED)
    if candidate.family_id != seal["candidate"]["family_id"]:
        raise ProtocolViolation("live F18 identity differs from candidate seal")

    episode_a = world.generate_episode(WorldSplit.VALIDATION, EVAL_SEED, 0)
    episode_b = world.generate_episode(WorldSplit.VALIDATION, EVAL_SEED, 1)
    prefix_a, delta_a = _split_history(episode_a.public_history)
    state_a0 = candidate.initialize(prefix_a, inference_seed=1)
    state_b = candidate.initialize(episode_b.public_history, inference_seed=2)
    state_a_direct = candidate.initialize(episode_a.public_history, inference_seed=3)
    state_a0_before = _state_snapshot(state_a0)
    state_b_before = _state_snapshot(state_b)
    model_before_update = _model_fingerprint(candidate)

    access_rows: list[dict[str, Any]] = []
    closure_rows: list[dict[str, Any]] = []
    raw_accesses: list[dict[str, Any]] = []
    labels = world.catalog.diagnostic_labels
    horizon = world.catalog.horizons[0]
    policies = world.policy_set(horizon)[:2]

    # Exact-type negative controls exercise the real head boundary.
    rejected_history_diagnose = False
    rejected_history_rollout = False
    try:
        candidate.diagnose(episode_a.public_history, labels, query_seed=5)  # type: ignore[arg-type]
    except ProtocolViolation:
        rejected_history_diagnose = True
    try:
        candidate.rollout(episode_a.public_history, policies[0], horizon, query_seed=6)  # type: ignore[arg-type]
    except ProtocolViolation:
        rejected_history_rollout = True

    with _raw_history_guard(raw_accesses) as guard_phase:
        positive_control = False
        try:
            _ = episode_a.public_history.events
        except RawHistoryAccessBlocked:
            positive_control = True
        guard_phase["value"] = "head"

        # Observe B, update only A under the raw-history trap, then observe B
        # again.  The call chronology, rather than only a before/after state
        # snapshot, makes cross-patient isolation executable evidence.
        b_before = _head_call(
            candidate=candidate,
            state=state_b,
            operation="diagnose_before_A_update",
            patient="B",
            access_rows=access_rows,
            invoke=lambda: candidate.diagnose(state_b, labels, query_seed=201),
        )
        guard_phase["value"] = "update"
        state_a1 = candidate.update(state_a0, delta_a, inference_seed=4)
        model_after_update = _model_fingerprint(candidate)
        state_a0_after = _state_snapshot(state_a0)
        guard_phase["value"] = "head"
        b_after = _head_call(
            candidate=candidate,
            state=state_b,
            operation="diagnose_after_A_update",
            patient="B",
            access_rows=access_rows,
            invoke=lambda: candidate.diagnose(state_b, labels, query_seed=201),
        )
        order_one = {
            "diagnosis": _head_call(
                candidate=candidate,
                state=state_a1,
                operation="diagnose",
                patient="A",
                access_rows=access_rows,
                invoke=lambda: candidate.diagnose(state_a1, labels, query_seed=101),
            ),
            "rollout_0": _head_call(
                candidate=candidate,
                state=state_a1,
                operation="rollout_0",
                patient="A",
                access_rows=access_rows,
                invoke=lambda: candidate.rollout(state_a1, policies[0], horizon, query_seed=102),
            ),
            "rollout_1": _head_call(
                candidate=candidate,
                state=state_a1,
                operation="rollout_1",
                patient="A",
                access_rows=access_rows,
                invoke=lambda: candidate.rollout(state_a1, policies[1], horizon, query_seed=103),
            ),
        }
        order_two = {
            "rollout_1": _head_call(
                candidate=candidate,
                state=state_a1,
                operation="rollout_1_reverse",
                patient="A",
                access_rows=access_rows,
                invoke=lambda: candidate.rollout(state_a1, policies[1], horizon, query_seed=103),
            ),
            "diagnosis": _head_call(
                candidate=candidate,
                state=state_a1,
                operation="diagnose_reverse",
                patient="A",
                access_rows=access_rows,
                invoke=lambda: candidate.diagnose(state_a1, labels, query_seed=101),
            ),
            "rollout_0": _head_call(
                candidate=candidate,
                state=state_a1,
                operation="rollout_0_reverse",
                patient="A",
                access_rows=access_rows,
                invoke=lambda: candidate.rollout(state_a1, policies[0], horizon, query_seed=102),
            ),
        }
        cold_state = SharedPatientState(
            state_a1.schema_version,
            bytes(state_a1.payload),
            tuple(state_a1.distance_vector),
            state_a1.compactness_class,
        )
        cold_outputs = {
            "diagnosis": _head_call(
                candidate=fresh_candidate,
                state=cold_state,
                operation="cold_diagnose",
                patient="A-cold",
                access_rows=access_rows,
                invoke=lambda: fresh_candidate.diagnose(cold_state, labels, query_seed=101),
            ),
            "rollout_0": _head_call(
                candidate=fresh_candidate,
                state=cold_state,
                operation="cold_rollout_0",
                patient="A-cold",
                access_rows=access_rows,
                invoke=lambda: fresh_candidate.rollout(cold_state, policies[0], horizon, query_seed=102),
            ),
            "rollout_1": _head_call(
                candidate=fresh_candidate,
                state=cold_state,
                operation="cold_rollout_1",
                patient="A-cold",
                access_rows=access_rows,
                invoke=lambda: fresh_candidate.rollout(cold_state, policies[1], horizon, query_seed=103),
            ),
        }

    protected_raw_accesses = [
        row for row in raw_accesses if row["phase"] in {"head", "update"}
    ]
    head_raw_accesses = [row for row in raw_accesses if row["phase"] == "head"]
    wire = json.loads(state_a1.payload)
    payload_key_set = set(_payload_keys(wire))
    forbidden_payload_keys = set(PRIVILEGED_FIELD_NAMES) | {
        "visible_history",
        "events",
        "event_uid",
        "task_state",
        "task_states",
        "diagnosis_state",
        "natural_state",
        "intervention_state",
    }
    payload_forbidden_hits = sorted(payload_key_set & forbidden_payload_keys)
    raw_identifiers = {
        event.event_uid
        for event in episode_a.public_history.events
    }
    for event in episode_a.public_history.events:
        for key in ("channel_id", "action_id", "check_id"):
            value = event.payload.get(key)
            if type(value) is str:
                raw_identifiers.add(value)
    payload_text = state_a1.payload.decode("utf-8")
    retained_raw_identifiers = sorted(value for value in raw_identifiers if value in payload_text)
    retained_patient_objects = _object_patient_specific_types(candidate)
    source_audit = _source_audit(candidate)

    closure_rows.extend(
        [
            {
                "check": "heads_accept_exact_shared_patient_state_only",
                "evidence": {
                    "all_live_head_input_types": sorted({row["input_type"] for row in access_rows}),
                    "raw_history_diagnose_rejected": rejected_history_diagnose,
                    "raw_history_rollout_rejected": rejected_history_rollout,
                },
                "passed": all(row["input_type"] == "SharedPatientState" for row in access_rows)
                and rejected_history_diagnose
                and rejected_history_rollout,
            },
            {
                "check": "live_raw_visible_history_guard",
                "evidence": {
                    "positive_control_triggered": positive_control,
                    "all_guard_accesses": raw_accesses,
                    "head_phase_accesses": head_raw_accesses,
                    "update_phase_accesses": [
                        row for row in raw_accesses if row["phase"] == "update"
                    ],
                },
                "passed": positive_control and not protected_raw_accesses,
            },
            {
                "check": "same_state_query_order_and_repeat_purity",
                "evidence": {
                    "order_one_digest": digest_json(order_one),
                    "order_two_normalized_digest": digest_json(
                        {key: order_two[key] for key in ("diagnosis", "rollout_0", "rollout_1")}
                    ),
                    "all_call_state_and_model_immutable": all(row["passed"] for row in access_rows),
                },
                "passed": order_one
                == {key: order_two[key] for key in ("diagnosis", "rollout_0", "rollout_1")}
                and all(row["passed"] for row in access_rows),
            },
            {
                "check": "cold_rehydrate_fresh_fit_equivalence",
                "evidence": {
                    "hot_state_hash": state_a1.state_hash,
                    "cold_state_hash": cold_state.state_hash,
                    "hot_output_digest": digest_json(order_one),
                    "cold_output_digest": digest_json(cold_outputs),
                    "fresh_model_fingerprint": _model_fingerprint(fresh_candidate),
                },
                "passed": state_a1.state_hash == cold_state.state_hash and order_one == cold_outputs,
            },
            {
                "check": "visible_delta_only_update_and_old_state_immutability",
                "evidence": {
                    "update_signature": list(inspect.signature(candidate.update).parameters),
                    "delta_type": type(delta_a).__name__,
                    "delta_event_count": len(delta_a.events),
                    "old_state_before": state_a0_before,
                    "old_state_after": state_a0_after,
                    "new_state": _state_snapshot(state_a1),
                    "direct_full_history_state_hash": state_a_direct.state_hash,
                    "model_fingerprint_before": model_before_update,
                    "model_fingerprint_after": model_after_update,
                },
                "passed": type(delta_a) is VisibleDelta
                and bool(delta_a.events)
                and state_a0_before == state_a0_after
                and state_a1.state_hash != state_a0.state_hash
                and state_a1.state_hash == state_a_direct.state_hash
                and model_before_update == model_after_update,
            },
            {
                "check": "second_patient_state_isolation",
                "evidence": {
                    "patient_A_hash": state_a1.state_hash,
                    "patient_B_before": state_b_before,
                    "patient_B_after": _state_snapshot(state_b),
                    "B_output_before_digest": digest_json(b_before),
                    "B_output_after_digest": digest_json(b_after),
                    "access_trace_operations": [
                        row["operation"] for row in access_rows[:2]
                    ],
                },
                "passed": state_b_before == _state_snapshot(state_b)
                and b_before == b_after
                and [row["operation"] for row in access_rows[:2]]
                == ["diagnose_before_A_update", "diagnose_after_A_update"],
            },
            {
                "check": "no_private_future_test_id_task_cache_or_full_history_reencode",
                "evidence": {
                    "payload_keys": sorted(payload_key_set),
                    "forbidden_payload_key_hits": payload_forbidden_hits,
                    "retained_exact_raw_identifiers": retained_raw_identifiers,
                    "candidate_retained_patient_objects": retained_patient_objects,
                    "candidate_model_unchanged_across_all_heads": all(row["model_immutable"] for row in access_rows),
                    "source_audit": source_audit,
                },
                "passed": not payload_forbidden_hits
                and not retained_raw_identifiers
                and not retained_patient_objects
                and all(row["model_immutable"] for row in access_rows)
                and source_audit["passed"],
            },
        ]
    )
    for index, row in enumerate(closure_rows, 1):
        row["sequence"] = index

    all_passed = all(row["passed"] for row in closure_rows) and all(
        row["passed"] for row in access_rows
    )
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-F18-compliance-{uuid.uuid4().hex[:10]}"
    report = {
        "protocol": PROTOCOL,
        "run_id": run_id,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "candidate_seal_digest": digest_bytes(seal_path.read_bytes()),
        "sealed_candidate_source_digest": seal["candidate_source_binding"]["source_digest"],
        "candidate": candidate.model_summary(),
        "execution": {
            "actually_instantiated_and_fit": True,
            "family_code": "F18",
            "world_slot": "W01",
            "training_records": training_records,
            "train_seed": TRAIN_SEED,
            "eval_seed": EVAL_SEED,
            "model_seed": MODEL_SEED,
            "head_call_count": len(access_rows),
            "state_closure_check_count": len(closure_rows),
        },
        "summary": {
            "all_passed": all_passed,
            "access_trace_passed": sum(row["passed"] for row in access_rows),
            "access_trace_total": len(access_rows),
            "state_closure_passed": sum(row["passed"] for row in closure_rows),
            "state_closure_total": len(closure_rows),
            "raw_history_head_access_count": len(head_raw_accesses),
            "raw_history_update_access_count": sum(
                row["phase"] == "update" for row in raw_accesses
            ),
            "retained_patient_object_count": len(retained_patient_objects),
            "payload_forbidden_key_count": len(payload_forbidden_hits),
            "retained_raw_identifier_count": len(retained_raw_identifiers),
        },
        "artifact_rows": {
            "access_trace": "access-trace.jsonl",
            "state_closure": "state-closure.jsonl",
        },
        "wall_seconds": time.perf_counter() - started,
        "claim_boundary": {
            "portable_runtime_contract_audit": True,
            "source_scan_is_supplementary": True,
            "synthetic_W01_execution_only": True,
            "clinical_validity_claimed": False,
            "repairs_sealed_ood_failure": False,
        },
    }
    if not all_passed:
        failed = [row["check"] for row in closure_rows if not row["passed"]]
        raise RuntimeError(f"F18 compliance audit failed: {failed}")

    output_root.mkdir(parents=True, exist_ok=True)
    directory = output_root / run_id
    directory.mkdir()
    report_path = directory / "compliance.json"
    access_path = directory / "access-trace.jsonl"
    closure_path = directory / "state-closure.jsonl"
    report_path.write_bytes(canonical_json_bytes(report))
    _write_jsonl(access_path, access_rows)
    _write_jsonl(closure_path, closure_rows)
    source_paths = (
        Path(__file__).resolve(),
        REPO_ROOT / "prototype/unified_map/candidate_families.py",
        REPO_ROOT / "prototype/unified_map/benchmark_v1_contract.py",
        REPO_ROOT / "prototype/unified_map/schema.py",
        REPO_ROOT / "prototype/unified_map/canonical.py",
        seal_path,
    )
    files = []
    for path in (report_path, access_path, closure_path):
        raw = path.read_bytes()
        files.append(
            {"name": path.name, "byte_length": len(raw), "sha256": digest_bytes(raw)}
        )
    sources = []
    for path in source_paths:
        raw = path.read_bytes()
        sources.append(
            {
                "relative_path": path.relative_to(REPO_ROOT).as_posix(),
                "byte_length": len(raw),
                "sha256": digest_bytes(raw),
            }
        )
    bound_manifest = {
        "protocol": MANIFEST_PROTOCOL,
        "run_id": run_id,
        "candidate_seal_digest": report["candidate_seal_digest"],
        "files": files,
        "sources": sources,
    }
    manifest = {**bound_manifest, "bundle_root": digest_json(bound_manifest)}
    (directory / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    verify_f18_compliance_bundle(directory, repo_root=REPO_ROOT)
    return directory


def verify_f18_compliance_bundle(
    directory: Path, *, repo_root: Path = REPO_ROOT
) -> dict[str, Any]:
    directory = directory.resolve()
    root = repo_root.resolve()
    manifest = _json_file(directory / "manifest.json")
    if manifest.get("protocol") != MANIFEST_PROTOCOL:
        raise ProtocolViolation("unexpected F18 compliance manifest protocol")
    expected_keys = {
        "protocol",
        "run_id",
        "candidate_seal_digest",
        "files",
        "sources",
        "bundle_root",
    }
    if set(manifest) != expected_keys:
        raise ProtocolViolation("F18 compliance manifest has unbound fields")
    bound = {key: manifest[key] for key in expected_keys - {"bundle_root"}}
    if manifest["bundle_root"] != digest_json(bound):
        raise ProtocolViolation("F18 compliance bundle root mismatch")
    seen: set[str] = set()
    for row in manifest["files"]:
        if set(row) != {"name", "byte_length", "sha256"} or row["name"] in seen:
            raise ProtocolViolation("invalid or duplicate compliance file row")
        seen.add(row["name"])
        path = directory / row["name"]
        raw = path.read_bytes()
        if len(raw) != row["byte_length"] or digest_bytes(raw) != row["sha256"]:
            raise ProtocolViolation(f"compliance file binding mismatch: {row['name']}")
    if seen != {"compliance.json", "access-trace.jsonl", "state-closure.jsonl"}:
        raise ProtocolViolation("compliance file inventory is incomplete")
    seen_sources: set[str] = set()
    for row in manifest["sources"]:
        if set(row) != {"relative_path", "byte_length", "sha256"}:
            raise ProtocolViolation("invalid compliance source row")
        relative = row["relative_path"]
        if type(relative) is not str or relative in seen_sources:
            raise ProtocolViolation("duplicate compliance source path")
        seen_sources.add(relative)
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ProtocolViolation("compliance source escapes repository") from exc
        raw = path.read_bytes()
        if len(raw) != row["byte_length"] or digest_bytes(raw) != row["sha256"]:
            raise ProtocolViolation(f"compliance source binding mismatch: {relative}")
    report = _json_file(directory / "compliance.json")
    access_rows = _jsonl_file(directory / "access-trace.jsonl")
    closure_rows = _jsonl_file(directory / "state-closure.jsonl")
    if report.get("protocol") != PROTOCOL or report.get("run_id") != manifest["run_id"]:
        raise ProtocolViolation("compliance report identity mismatch")
    if report.get("candidate_seal_digest") != manifest["candidate_seal_digest"]:
        raise ProtocolViolation("compliance seal binding mismatch")
    summary = report.get("summary")
    if type(summary) is not dict or summary.get("all_passed") is not True:
        raise ProtocolViolation("compliance report is not passing")
    if len(access_rows) != summary.get("access_trace_total") or not all(
        row.get("passed") is True for row in access_rows
    ):
        raise ProtocolViolation("compliance access trace is incomplete or failing")
    if len(closure_rows) != summary.get("state_closure_total") or not all(
        row.get("passed") is True for row in closure_rows
    ):
        raise ProtocolViolation("compliance state closure is incomplete or failing")
    if [row.get("sequence") for row in access_rows] != list(range(1, len(access_rows) + 1)):
        raise ProtocolViolation("compliance access trace sequence is invalid")
    if [row.get("sequence") for row in closure_rows] != list(range(1, len(closure_rows) + 1)):
        raise ProtocolViolation("compliance closure sequence is invalid")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seal", type=Path, default=Path("research/unified_map/CANDIDATE_SEAL.json")
    )
    parser.add_argument(
        "--output-root", type=Path, default=Path("results/unified_map/compliance")
    )
    parser.add_argument("--training-records", type=int, default=TRAIN_RECORDS)
    args = parser.parse_args()
    print(
        run_audit(
            seal_path=args.seal,
            output_root=args.output_root,
            training_records=args.training_records,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
