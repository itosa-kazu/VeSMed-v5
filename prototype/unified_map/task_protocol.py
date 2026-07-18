"""Code-owned semantic mapping from benchmark tasks to candidate execution.

This module closes one deliberately narrow authority boundary: it records how
the five benchmark tasks are expressed through the four operations that the
current candidate protocol actually exposes.  It does *not* claim that any
runtime, corpus, expected-cell set, or freeze evidence is complete.

In particular, OOD is scored from a bundle of the existing ``diagnose`` and
``rollout`` readouts; it is not a fifth candidate method.  A frozen-model novel
readout is a post-seal extension probe and is likewise not part of the base
candidate API.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

from .candidate_protocol import Operation, REQUEST_PROTOCOL
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    validate_json_like,
)
from .evaluator import EvaluationTask


TASK_EXECUTION_MANIFEST_SCHEMA = "ucm-task-execution-manifest/1"
TASK_EXECUTION_AUTHORITY_CLAIM = "semantic_execution_mapping_only"
TASK_EXECUTION_RUNTIME_READINESS = "not_claimed"
CANDIDATE_REQUEST_PROTOCOL_TRUTH = "ucm-candidate-request/1"

_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "candidate_request_protocol",
        "base_operation_truth",
        "task_bindings",
        "authority_claim",
        "runtime_readiness",
    }
)
_BINDING_KEYS = frozenset({"task", "execution_kind", "operations"})


class TaskExecutionKind(str, Enum):
    """How a benchmark task reaches candidate-visible execution."""

    BASE_OPERATION = "base_operation"
    OPERATION_BUNDLE = "operation_bundle"
    POST_SEAL_EXTENSION = "post_seal_extension"


BASE_OPERATION_TRUTH = (
    Operation.INITIALIZE,
    Operation.UPDATE,
    Operation.DIAGNOSE,
    Operation.ROLLOUT,
)
TASK_EXECUTION_TRUTH = (
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


def _exact_object(
    value: object,
    expected_keys: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    validate_json_like(value, path=label)
    actual = frozenset(value)
    if actual != expected_keys:
        raise ProtocolViolation(
            f"{label} has missing/extra fields; "
            f"missing={sorted(expected_keys - actual)!r}, "
            f"extra={sorted(actual - expected_keys)!r}"
        )
    return value


_EnumT = TypeVar("_EnumT", bound=Enum)


def _enum_value(enum_type: type[_EnumT], value: object, label: str) -> _EnumT:
    if type(value) is not str:
        raise ProtocolViolation(f"{label} must be an exact string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} is not code-owned protocol truth") from exc


def _decode_exact_canonical_object(payload: object) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation("task execution manifest must be exact bytes")

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolViolation(
                    f"task execution manifest contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProtocolViolation(
            "task execution manifest is not strict UTF-8 JSON"
        ) from exc
    try:
        value = json.loads(text, object_pairs_hook=reject_duplicate_pairs)
    except ProtocolViolation:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProtocolViolation("task execution manifest is not valid JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation(
            "task execution manifest must encode an exact JSON object"
        )
    validate_json_like(value, path="task execution manifest")
    try:
        rebuilt = canonical_json_bytes(value)
    except (UnicodeEncodeError, ValueError) as exc:
        raise ProtocolViolation(
            "task execution manifest is not canonical strict UTF-8 JSON"
        ) from exc
    if rebuilt != payload:
        raise ProtocolViolation(
            "task execution manifest bytes are not canonical sorted compact JSON "
            "plus one LF"
        )
    return value


@dataclass(frozen=True, slots=True)
class TaskExecutionBinding:
    """Typed execution semantics for exactly one benchmark task."""

    task: EvaluationTask
    execution_kind: TaskExecutionKind
    operations: tuple[Operation, ...]

    def __post_init__(self) -> None:
        if type(self.task) is not EvaluationTask:
            raise ProtocolViolation("task binding task must be EvaluationTask")
        if type(self.execution_kind) is not TaskExecutionKind:
            raise ProtocolViolation(
                "task binding execution_kind must be TaskExecutionKind"
            )
        if type(self.operations) is not tuple or any(
            type(operation) is not Operation for operation in self.operations
        ):
            raise ProtocolViolation(
                "task binding operations must be an exact tuple of base Operations"
            )
        expected = {
            task: (execution_kind, operations)
            for task, execution_kind, operations in TASK_EXECUTION_TRUTH
        }.get(self.task)
        if expected is None:
            raise ProtocolViolation(
                f"task {self.task.value} is absent from code-owned execution truth"
            )
        if (self.execution_kind, self.operations) != expected:
            raise ProtocolViolation(
                f"task {self.task.value} execution does not match code-owned truth"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "task": self.task.value,
            "execution_kind": self.execution_kind.value,
            "operations": [operation.value for operation in self.operations],
        }

    @classmethod
    def from_wire(cls, value: object) -> "TaskExecutionBinding":
        body = _exact_object(value, _BINDING_KEYS, "task execution binding")
        operations = body["operations"]
        if type(operations) is not list:
            raise ProtocolViolation("task binding operations must be an exact list")
        parsed_operations: list[Operation] = []
        for index, operation in enumerate(operations):
            parsed_operations.append(
                _enum_value(
                    Operation,
                    operation,
                    f"task binding operation {index}",
                )
            )
        return cls(
            task=_enum_value(EvaluationTask, body["task"], "task binding task"),
            execution_kind=_enum_value(
                TaskExecutionKind,
                body["execution_kind"],
                "task binding execution_kind",
            ),
            operations=tuple(parsed_operations),
        )


@dataclass(frozen=True, slots=True)
class TaskExecutionManifest:
    """Closed authority DTO for the code-owned semantic execution map."""

    task_bindings: tuple[TaskExecutionBinding, ...]
    base_operation_truth: tuple[Operation, ...] = BASE_OPERATION_TRUTH
    schema_version: str = TASK_EXECUTION_MANIFEST_SCHEMA
    candidate_request_protocol: str = CANDIDATE_REQUEST_PROTOCOL_TRUTH
    authority_claim: str = TASK_EXECUTION_AUTHORITY_CLAIM
    runtime_readiness: str = TASK_EXECUTION_RUNTIME_READINESS

    def __post_init__(self) -> None:
        if REQUEST_PROTOCOL != CANDIDATE_REQUEST_PROTOCOL_TRUTH:
            raise ProtocolViolation(
                "live candidate request protocol drifted from task authority truth"
            )
        if tuple(Operation) != BASE_OPERATION_TRUTH:
            raise ProtocolViolation(
                "live candidate Operation enum drifted from the four-operation truth"
            )
        if tuple(task for task, _, _ in TASK_EXECUTION_TRUTH) != tuple(EvaluationTask):
            raise ProtocolViolation(
                "live EvaluationTask enum drifted from the five-task truth"
            )
        if (
            type(self.schema_version) is not str
            or self.schema_version != TASK_EXECUTION_MANIFEST_SCHEMA
        ):
            raise ProtocolViolation(
                "task execution manifest schema_version is not code-owned v1"
            )
        if (
            type(self.candidate_request_protocol) is not str
            or self.candidate_request_protocol != CANDIDATE_REQUEST_PROTOCOL_TRUTH
        ):
            raise ProtocolViolation(
                "task execution manifest candidate protocol binding is stale"
            )
        if (
            type(self.base_operation_truth) is not tuple
            or any(
                type(operation) is not Operation
                for operation in self.base_operation_truth
            )
            or self.base_operation_truth != BASE_OPERATION_TRUTH
        ):
            raise ProtocolViolation(
                "task execution manifest base operation truth is missing, duplicated, "
                "reordered, or stale"
            )
        if type(self.task_bindings) is not tuple or any(
            type(binding) is not TaskExecutionBinding for binding in self.task_bindings
        ):
            raise ProtocolViolation(
                "task execution manifest bindings must be an exact typed tuple"
            )
        expected = tuple(
            (task, execution_kind, operations)
            for task, execution_kind, operations in TASK_EXECUTION_TRUTH
        )
        actual = tuple(
            (binding.task, binding.execution_kind, binding.operations)
            for binding in self.task_bindings
        )
        if actual != expected:
            raise ProtocolViolation(
                "task bindings are missing, duplicated, reordered, or not code-owned"
            )
        if (
            type(self.authority_claim) is not str
            or self.authority_claim != TASK_EXECUTION_AUTHORITY_CLAIM
        ):
            raise ProtocolViolation(
                "task execution manifest may claim semantic mapping only"
            )
        if (
            type(self.runtime_readiness) is not str
            or self.runtime_readiness != TASK_EXECUTION_RUNTIME_READINESS
        ):
            raise ProtocolViolation(
                "task execution manifest must not claim runtime readiness"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_request_protocol": self.candidate_request_protocol,
            "base_operation_truth": [
                operation.value for operation in self.base_operation_truth
            ],
            "task_bindings": [binding.to_wire() for binding in self.task_bindings],
            "authority_claim": self.authority_claim,
            "runtime_readiness": self.runtime_readiness,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    def binding_for(self, task: EvaluationTask) -> TaskExecutionBinding:
        if type(task) is not EvaluationTask:
            raise ProtocolViolation("binding lookup task must be EvaluationTask")
        return self.task_bindings[tuple(EvaluationTask).index(task)]

    @classmethod
    def from_wire(cls, value: object) -> "TaskExecutionManifest":
        body = _exact_object(value, _TOP_LEVEL_KEYS, "task execution manifest")
        base_operations = body["base_operation_truth"]
        if type(base_operations) is not list:
            raise ProtocolViolation("base_operation_truth must be an exact list")
        bindings = body["task_bindings"]
        if type(bindings) is not list:
            raise ProtocolViolation("task_bindings must be an exact list")
        return cls(
            schema_version=body["schema_version"],
            candidate_request_protocol=body["candidate_request_protocol"],
            base_operation_truth=tuple(
                _enum_value(Operation, operation, f"base operation {index}")
                for index, operation in enumerate(base_operations)
            ),
            task_bindings=tuple(
                TaskExecutionBinding.from_wire(binding) for binding in bindings
            ),
            authority_claim=body["authority_claim"],
            runtime_readiness=body["runtime_readiness"],
        )


def _code_owned_manifest() -> TaskExecutionManifest:
    return TaskExecutionManifest(
        task_bindings=tuple(
            TaskExecutionBinding(task, execution_kind, operations)
            for task, execution_kind, operations in TASK_EXECUTION_TRUTH
        )
    )


CODE_OWNED_TASK_EXECUTION_MANIFEST = _code_owned_manifest()
CODE_OWNED_TASK_EXECUTION_MANIFEST_BYTES = (
    CODE_OWNED_TASK_EXECUTION_MANIFEST.canonical_bytes
)
CODE_OWNED_TASK_EXECUTION_MANIFEST_DIGEST = CODE_OWNED_TASK_EXECUTION_MANIFEST.digest


def parse_task_execution_manifest_bytes(payload: bytes) -> TaskExecutionManifest:
    """Parse exact canonical task authority bytes and enforce live code truth."""

    value = _decode_exact_canonical_object(payload)
    manifest = TaskExecutionManifest.from_wire(value)
    if manifest.canonical_bytes != payload:
        raise ProtocolViolation("task execution manifest DTO round-trip changed bytes")
    return manifest


def task_execution_manifest_digest_from_bytes(payload: bytes) -> str:
    """Return an artifact digest only after closed code-truth validation."""

    return parse_task_execution_manifest_bytes(payload).digest


__all__ = [
    "BASE_OPERATION_TRUTH",
    "CANDIDATE_REQUEST_PROTOCOL_TRUTH",
    "CODE_OWNED_TASK_EXECUTION_MANIFEST",
    "CODE_OWNED_TASK_EXECUTION_MANIFEST_BYTES",
    "CODE_OWNED_TASK_EXECUTION_MANIFEST_DIGEST",
    "TASK_EXECUTION_AUTHORITY_CLAIM",
    "TASK_EXECUTION_MANIFEST_SCHEMA",
    "TASK_EXECUTION_RUNTIME_READINESS",
    "TASK_EXECUTION_TRUTH",
    "TaskExecutionBinding",
    "TaskExecutionKind",
    "TaskExecutionManifest",
    "parse_task_execution_manifest_bytes",
    "task_execution_manifest_digest_from_bytes",
]
