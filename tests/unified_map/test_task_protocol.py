from __future__ import annotations

import copy
import json
from enum import Enum

import pytest

import prototype.unified_map.task_protocol as task_protocol
from prototype.unified_map.candidate_protocol import Operation, REQUEST_PROTOCOL
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
)
from prototype.unified_map.evaluator import EvaluationTask
from prototype.unified_map.task_protocol import (
    BASE_OPERATION_TRUTH,
    CANDIDATE_REQUEST_PROTOCOL_TRUTH,
    CODE_OWNED_TASK_EXECUTION_MANIFEST,
    CODE_OWNED_TASK_EXECUTION_MANIFEST_BYTES,
    CODE_OWNED_TASK_EXECUTION_MANIFEST_DIGEST,
    TASK_EXECUTION_AUTHORITY_CLAIM,
    TASK_EXECUTION_MANIFEST_SCHEMA,
    TASK_EXECUTION_RUNTIME_READINESS,
    TASK_EXECUTION_TRUTH,
    TaskExecutionBinding,
    TaskExecutionKind,
    TaskExecutionManifest,
    parse_task_execution_manifest_bytes,
    task_execution_manifest_digest_from_bytes,
)


def _wire() -> dict[str, object]:
    return copy.deepcopy(CODE_OWNED_TASK_EXECUTION_MANIFEST.to_wire())


def _payload(wire: dict[str, object] | None = None) -> bytes:
    return canonical_json_bytes(_wire() if wire is None else wire)


def test_code_owned_manifest_binds_live_four_operation_truth() -> None:
    manifest = CODE_OWNED_TASK_EXECUTION_MANIFEST

    assert manifest.schema_version == TASK_EXECUTION_MANIFEST_SCHEMA
    assert manifest.candidate_request_protocol == REQUEST_PROTOCOL
    assert CANDIDATE_REQUEST_PROTOCOL_TRUTH == REQUEST_PROTOCOL
    assert BASE_OPERATION_TRUTH == tuple(Operation)
    assert tuple(task for task, _, _ in TASK_EXECUTION_TRUTH) == tuple(EvaluationTask)
    assert manifest.base_operation_truth == (
        Operation.INITIALIZE,
        Operation.UPDATE,
        Operation.DIAGNOSE,
        Operation.ROLLOUT,
    )
    assert manifest.authority_claim == TASK_EXECUTION_AUTHORITY_CLAIM
    assert manifest.runtime_readiness == TASK_EXECUTION_RUNTIME_READINESS
    assert manifest.runtime_readiness == "not_claimed"


def test_exact_five_task_execution_mapping_is_typed() -> None:
    manifest = CODE_OWNED_TASK_EXECUTION_MANIFEST
    actual = tuple(
        (binding.task, binding.execution_kind, binding.operations)
        for binding in manifest.task_bindings
    )

    assert actual == TASK_EXECUTION_TRUTH
    assert actual == (
        (
            EvaluationTask.DIAGNOSIS,
            TaskExecutionKind.BASE_OPERATION,
            (Operation.DIAGNOSE,),
        ),
        (
            EvaluationTask.NATURAL_FORECAST,
            TaskExecutionKind.BASE_OPERATION,
            (Operation.ROLLOUT,),
        ),
        (
            EvaluationTask.INTERVENTION,
            TaskExecutionKind.BASE_OPERATION,
            (Operation.ROLLOUT,),
        ),
        (
            EvaluationTask.OOD,
            TaskExecutionKind.OPERATION_BUNDLE,
            (Operation.DIAGNOSE, Operation.ROLLOUT),
        ),
        (
            EvaluationTask.NEW_READOUT,
            TaskExecutionKind.POST_SEAL_EXTENSION,
            (),
        ),
    )
    assert manifest.binding_for(EvaluationTask.OOD).operations == (
        Operation.DIAGNOSE,
        Operation.ROLLOUT,
    )
    assert (
        manifest.binding_for(EvaluationTask.NEW_READOUT).execution_kind
        is TaskExecutionKind.POST_SEAL_EXTENSION
    )
    assert manifest.binding_for(EvaluationTask.NEW_READOUT).operations == ()


def test_code_owned_bytes_round_trip_and_digest() -> None:
    parsed = parse_task_execution_manifest_bytes(
        CODE_OWNED_TASK_EXECUTION_MANIFEST_BYTES
    )

    assert parsed == CODE_OWNED_TASK_EXECUTION_MANIFEST
    assert parsed.canonical_bytes == CODE_OWNED_TASK_EXECUTION_MANIFEST_BYTES
    assert parsed.digest == CODE_OWNED_TASK_EXECUTION_MANIFEST_DIGEST
    assert CODE_OWNED_TASK_EXECUTION_MANIFEST_DIGEST == digest_bytes(
        CODE_OWNED_TASK_EXECUTION_MANIFEST_BYTES
    )
    assert CODE_OWNED_TASK_EXECUTION_MANIFEST_DIGEST == (
        "sha256:59a3b4023c78175c98212314b907c3361045b9dba1eaf95d8521304b6469852c"
    )
    assert (
        task_execution_manifest_digest_from_bytes(
            CODE_OWNED_TASK_EXECUTION_MANIFEST_BYTES
        )
        == CODE_OWNED_TASK_EXECUTION_MANIFEST_DIGEST
    )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda row: row.update({"extra": False}),
        lambda row: row.pop("authority_claim"),
        lambda row: row["task_bindings"][0].update({"extra": False}),
        lambda row: row["task_bindings"][0].pop("operations"),
    ],
)
def test_closed_schema_rejects_extra_or_missing_fields(mutation: object) -> None:
    wire = _wire()
    mutation(wire)  # type: ignore[operator]

    with pytest.raises(ProtocolViolation, match="missing/extra"):
        parse_task_execution_manifest_bytes(_payload(wire))


@pytest.mark.parametrize(
    "attack",
    [
        lambda payload: payload.rstrip(b"\n"),
        lambda payload: json.dumps(
            json.loads(payload), ensure_ascii=False, indent=2
        ).encode("utf-8"),
        lambda payload: payload.replace(b'"task_bindings":', b'"task_bindings" :', 1),
    ],
)
def test_parser_rejects_noncanonical_exact_bytes(attack: object) -> None:
    with pytest.raises(ProtocolViolation, match="canonical"):
        parse_task_execution_manifest_bytes(
            attack(CODE_OWNED_TASK_EXECUTION_MANIFEST_BYTES)  # type: ignore[operator]
        )


def test_parser_rejects_duplicate_json_keys() -> None:
    payload = CODE_OWNED_TASK_EXECUTION_MANIFEST_BYTES
    duplicate = payload.replace(
        b"{",
        b'{"schema_version":"ucm-task-execution-manifest/1",',
        1,
    )

    with pytest.raises(ProtocolViolation, match="duplicate key"):
        parse_task_execution_manifest_bytes(duplicate)


@pytest.mark.parametrize("attack", ["missing", "duplicate", "reorder"])
def test_task_registry_rejects_missing_duplicate_or_reordered_rows(
    attack: str,
) -> None:
    wire = _wire()
    bindings = wire["task_bindings"]
    if attack == "missing":
        bindings.pop()
    elif attack == "duplicate":
        bindings[-1] = copy.deepcopy(bindings[0])
    else:
        bindings[0], bindings[1] = bindings[1], bindings[0]

    with pytest.raises(ProtocolViolation, match="missing, duplicated, reordered"):
        parse_task_execution_manifest_bytes(_payload(wire))


@pytest.mark.parametrize("attack", ["missing", "duplicate", "reorder"])
def test_base_operation_truth_rejects_missing_duplicate_or_reorder(
    attack: str,
) -> None:
    wire = _wire()
    operations = wire["base_operation_truth"]
    if attack == "missing":
        operations.pop()
    elif attack == "duplicate":
        operations[-1] = operations[0]
    else:
        operations[0], operations[1] = operations[1], operations[0]

    with pytest.raises(ProtocolViolation, match="missing, duplicated, reordered"):
        parse_task_execution_manifest_bytes(_payload(wire))


@pytest.mark.parametrize("forged_method", ["ood", "new_readout"])
def test_ood_and_new_readout_cannot_enter_base_operation_truth(
    forged_method: str,
) -> None:
    wire = _wire()
    wire["base_operation_truth"].append(forged_method)

    with pytest.raises(ProtocolViolation, match="not code-owned protocol truth"):
        parse_task_execution_manifest_bytes(_payload(wire))


@pytest.mark.parametrize(
    ("task", "execution_kind", "operations"),
    [
        ("diagnosis", "base_operation", ["rollout"]),
        ("natural_forecast", "base_operation", ["diagnose"]),
        ("intervention", "base_operation", ["diagnose"]),
        ("ood", "base_operation", ["diagnose"]),
        ("ood", "operation_bundle", ["rollout", "diagnose"]),
        ("new_readout", "base_operation", ["rollout"]),
        ("new_readout", "operation_bundle", ["diagnose", "rollout"]),
    ],
)
def test_every_task_mapping_is_code_owned_and_cannot_be_reinterpreted(
    task: str,
    execution_kind: str,
    operations: list[str],
) -> None:
    wire = _wire()
    binding = next(row for row in wire["task_bindings"] if row["task"] == task)
    binding["execution_kind"] = execution_kind
    binding["operations"] = operations

    with pytest.raises(ProtocolViolation, match="does not match code-owned truth"):
        parse_task_execution_manifest_bytes(_payload(wire))


@pytest.mark.parametrize("task", ["ood", "new_readout"])
def test_ood_or_readout_spelling_is_never_a_candidate_operation(task: str) -> None:
    wire = _wire()
    binding = next(row for row in wire["task_bindings"] if row["task"] == task)
    binding["operations"] = [task]

    with pytest.raises(ProtocolViolation, match="not code-owned protocol truth"):
        parse_task_execution_manifest_bytes(_payload(wire))


def test_manifest_cannot_claim_runtime_ready() -> None:
    wire = _wire()
    wire["runtime_readiness"] = "ready"
    with pytest.raises(ProtocolViolation, match="must not claim runtime readiness"):
        parse_task_execution_manifest_bytes(_payload(wire))

    wire = _wire()
    wire["authority_claim"] = "runtime_complete"
    with pytest.raises(ProtocolViolation, match="semantic mapping only"):
        parse_task_execution_manifest_bytes(_payload(wire))


def test_typed_dto_cannot_construct_readout_as_base_method() -> None:
    with pytest.raises(ProtocolViolation, match="does not match code-owned truth"):
        TaskExecutionBinding(
            EvaluationTask.NEW_READOUT,
            TaskExecutionKind.BASE_OPERATION,
            (Operation.ROLLOUT,),
        )


@pytest.mark.parametrize(
    "dropped_task", [EvaluationTask.OOD, EvaluationTask.NEW_READOUT]
)
def test_typed_manifest_cannot_drop_required_task(
    dropped_task: EvaluationTask,
) -> None:
    retained = tuple(
        binding
        for binding in CODE_OWNED_TASK_EXECUTION_MANIFEST.task_bindings
        if binding.task is not dropped_task
    )
    with pytest.raises(ProtocolViolation, match="missing, duplicated, reordered"):
        TaskExecutionManifest(task_bindings=retained)


def test_manifest_construction_fails_closed_on_live_operation_enum_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DriftOperation(str, Enum):
        INITIALIZE = "initialize"
        UPDATE = "update"
        DIAGNOSE = "diagnose"
        ROLLOUT = "rollout"
        OOD = "ood"

    monkeypatch.setattr(task_protocol, "Operation", DriftOperation)
    with pytest.raises(ProtocolViolation, match="Operation enum drifted"):
        TaskExecutionManifest(
            task_bindings=CODE_OWNED_TASK_EXECUTION_MANIFEST.task_bindings
        )


def test_manifest_construction_fails_closed_on_live_task_enum_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DriftEvaluationTask(str, Enum):
        DIAGNOSIS = "diagnosis"
        NATURAL_FORECAST = "natural_forecast"
        INTERVENTION = "intervention"
        OOD = "ood"
        NEW_READOUT = "new_readout"
        FUTURE_TASK = "future_task"

    monkeypatch.setattr(task_protocol, "EvaluationTask", DriftEvaluationTask)
    with pytest.raises(ProtocolViolation, match="EvaluationTask enum drifted"):
        TaskExecutionManifest(
            task_bindings=CODE_OWNED_TASK_EXECUTION_MANIFEST.task_bindings
        )


@pytest.mark.parametrize("payload", [bytearray(b"{}\n"), "{}\n", memoryview(b"{}\n")])
def test_parser_and_digest_require_exact_bytes(payload: object) -> None:
    for function in (
        parse_task_execution_manifest_bytes,
        task_execution_manifest_digest_from_bytes,
    ):
        with pytest.raises(ProtocolViolation, match="exact bytes"):
            function(payload)  # type: ignore[arg-type]
