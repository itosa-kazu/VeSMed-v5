"""Candidate process protocol for the isolated UCM benchmark.

The protocol deliberately separates the two state-producing operations
(``initialize`` and ``update``) from the pure readout heads (``diagnose`` and
``rollout``).  A candidate never supplies a trusted state hash: the harness
seals returned inert bytes with :mod:`prototype.unified_map.state`.

``FreshProcessExecutor`` is a portable minimum closure test.  It starts a new
Python interpreter in an empty temporary working directory, passes the request
through stdin, uses a small environment allow-list, and records/denies ordinary
Python-audited file/network/process attempts from candidate import and
construction through each candidate call.  Import-time reads are limited to an
exact code-file manifest.  This is useful observability for cooperative Python
candidates, but same-process hook self-tampering, native code, and Windows
kernel escape remain unexcluded; this is not an OS sandbox or proof of semantic
unity.
"""

from __future__ import annotations

import base64
import contextlib
import importlib
import importlib.machinery
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import queue
import re
import stat
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol, TypeAlias

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .schema import (
    ActionPlan,
    CandidateVisibleEvent,
    DiagnosisQuery,
    EventKind,
    PlanKind,
    PlannedAction,
    RolloutQuery,
    VisibleDelta,
    VisibleHistory,
)
from .state import CandidateStateInput, SealedState, StateClass, StatePayload


REQUEST_PROTOCOL = "ucm-candidate-request/1"
RESPONSE_PROTOCOL = "ucm-candidate-response/1"
WORKER_PROTOCOL = "ucm-python-worker-result/4"
SESSION_WORKER_PROTOCOL = "ucm-python-sequential-worker-stream/4"
SESSION_REQUEST_PROTOCOL = "ucm-candidate-request-frame/2"
MAX_STATE_PAYLOAD_BYTES = 256 * 1024 * 1024
MAX_SESSION_REQUESTS = 64
MAX_SESSION_FRAME_BYTES = (MAX_STATE_PAYLOAD_BYTES * 4 // 3) + 4 * 1024 * 1024
MAX_CAPTURED_STREAM_BYTES = 1024 * 1024
MAX_AUDIT_EVENTS = 256
MAX_AUDIT_EVENT_ARGS = 16
MAX_IMPORT_FILES = 20_000
MAX_IMPORT_ALLOWED_PATHS = 40_000
MAX_IMPORT_FILE_BYTES = 256 * 1024 * 1024
MAX_IMPORT_TOTAL_BYTES = 512 * 1024 * 1024
MAX_IMPORT_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_SEQUENTIAL_AGGREGATE_BYTES = 512 * 1024 * 1024
MAX_RESPONSE_FRAME_BYTES = MAX_SESSION_FRAME_BYTES
PARENT_POSTVERIFY_TIMEOUT_SECONDS = 5.0
WORKER_CLEANUP_GRACE_SECONDS = 1.0


def _bounded_evidence_text(value: str | bytes) -> str:
    """Return UTF-8 evidence whose re-encoded size cannot exceed the cap."""

    if type(value) is bytes:
        raw = value[:MAX_CAPTURED_STREAM_BYTES]
    elif type(value) is str:
        # Every Unicode code point consumes at least one UTF-8 byte, so this
        # character slice bounds the temporary encoding as well as the result.
        raw = value[:MAX_CAPTURED_STREAM_BYTES].encode("utf-8", "replace")[
            :MAX_CAPTURED_STREAM_BYTES
        ]
    else:
        raw = str(value)[:MAX_CAPTURED_STREAM_BYTES].encode(
            "utf-8", "replace"
        )[:MAX_CAPTURED_STREAM_BYTES]
    # Ignore a terminal partial code point.  Evidence is diagnostic only; the
    # byte ceiling is an integrity boundary and takes precedence over fidelity.
    return raw.decode("utf-8", "ignore")


def _merge_bounded_evidence(*values: str | bytes) -> str:
    retained = bytearray()
    for value in values:
        if len(retained) >= MAX_CAPTURED_STREAM_BYTES:
            break
        normalized = _bounded_evidence_text(value).encode("utf-8")
        retained.extend(
            normalized[: MAX_CAPTURED_STREAM_BYTES - len(retained)]
        )
    return bytes(retained).decode("utf-8", "ignore")


def _validated_capture_field(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise ProtocolViolation(f"{label} must be an exact string")
    if len(value[: MAX_CAPTURED_STREAM_BYTES + 1].encode("utf-8")) > (
        MAX_CAPTURED_STREAM_BYTES
    ) or len(value) > MAX_CAPTURED_STREAM_BYTES:
        raise ProtocolViolation(f"{label} exceeded the captured stream limit")
    return value


def _exact_keys(
    value: object,
    *,
    required: frozenset[str],
    label: str,
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    keys = frozenset(value)
    if keys != required:
        missing = sorted(required - keys)
        extra = sorted(keys - required)
        raise ProtocolViolation(
            f"{label} fields mismatch; missing={missing!r}, extra={extra!r}"
        )
    return value


def _seed(value: object) -> None:
    if type(value) is not int or value < 0 or value >= 2**64:
        raise ProtocolViolation("seed must be an unsigned 64-bit exact integer")


def _positive_worker_pid(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ProtocolViolation(f"{label} must be a positive exact integer")
    return value


def _positive_finite_seconds(value: object, label: str) -> float:
    if type(value) not in {int, float}:
        raise ProtocolViolation(f"{label} must be a finite positive number")
    try:
        normalized = float(value)
    except (OverflowError, ValueError) as exc:
        raise ProtocolViolation(
            f"{label} must be a finite positive number"
        ) from exc
    if not math.isfinite(normalized) or normalized <= 0.0:
        raise ProtocolViolation(f"{label} must be a finite positive number")
    return normalized


def _worker_subdeadline(total_deadline: float, timeout_seconds: float) -> float:
    """Reserve bounded wall time for mandatory parent-side post-rehashing."""

    # Parent verification is part of, rather than an extension to, the caller's
    # total wall-clock budget.  A quarter of a normal invocation (capped at
    # five seconds) leaves enough time to rehash the bounded runtime closure
    # while still giving the candidate the majority of its declared budget.
    reserve = min(
        PARENT_POSTVERIFY_TIMEOUT_SECONDS,
        max(0.5, timeout_seconds * 0.25),
    )
    if reserve >= timeout_seconds:
        reserve = timeout_seconds / 2.0
    return total_deadline - reserve


def _cleanup_remaining(cleanup_deadline: float) -> float:
    return max(0.0, cleanup_deadline - time.monotonic())


def _begin_cleanup_deadline(current: float | None) -> float:
    if current is not None:
        return current
    return time.monotonic() + WORKER_CLEANUP_GRACE_SECONDS


def _nonempty(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ProtocolViolation(f"{label} must be a non-empty exact string")
    return value


def _forbid_head_state_fields(value: Any, path: str = "$.result") -> None:
    """Reject attempts to return a new persistent patient state from a head."""

    validate_json_like(value, path=path)
    forbidden = {
        "state",
        "state_payload",
        "new_state",
        "next_state",
        "patient_state",
        "state_handle",
    }

    def walk(node: Any, where: str) -> None:
        if type(node) is dict:
            for key, item in node.items():
                normalized = key.strip().lower().replace("-", "_")
                if normalized in forbidden:
                    raise ProtocolViolation(
                        f"{where}.{key}: readout heads cannot return patient state"
                    )
                walk(item, f"{where}.{key}")
        elif type(node) is list:
            for index, item in enumerate(node):
                walk(item, f"{where}[{index}]")

    walk(value, path)


class Operation(str, Enum):
    INITIALIZE = "initialize"
    UPDATE = "update"
    DIAGNOSE = "diagnose"
    ROLLOUT = "rollout"


class ResultStatus(str, Enum):
    OK = "ok"
    ABSTAIN = "abstain"
    SCOPE_INSUFFICIENT = "scope_insufficient"
    UNSUPPORTED = "unsupported"
    INVALID_INPUT = "invalid_input"
    NUMERICAL_FAILURE = "numerical_failure"


@dataclass(frozen=True, slots=True)
class InitializeRequest:
    history: VisibleHistory
    seed: int

    def __post_init__(self) -> None:
        if type(self.history) is not VisibleHistory:
            raise ProtocolViolation("initialize history must be VisibleHistory")
        _seed(self.seed)

    @property
    def operation(self) -> Operation:
        return Operation.INITIALIZE

    def to_wire(self) -> dict[str, Any]:
        # There is intentionally no query/task/action field here.
        return {
            "protocol": REQUEST_PROTOCOL,
            "operation": self.operation.value,
            "seed": self.seed,
            "history": self.history.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class UpdateRequest:
    state: CandidateStateInput
    delta: VisibleDelta
    seed: int

    def __post_init__(self) -> None:
        if type(self.state) is not CandidateStateInput:
            raise ProtocolViolation("update state must be CandidateStateInput")
        if type(self.delta) is not VisibleDelta:
            raise ProtocolViolation("update delta must be VisibleDelta")
        _seed(self.seed)

    @property
    def operation(self) -> Operation:
        return Operation.UPDATE

    def to_wire(self) -> dict[str, Any]:
        # There is intentionally no old history or future query here.
        return {
            "protocol": REQUEST_PROTOCOL,
            "operation": self.operation.value,
            "seed": self.seed,
            "state": state_input_to_wire(self.state),
            "delta": self.delta.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class DiagnoseRequest:
    state: CandidateStateInput
    query: DiagnosisQuery
    seed: int

    def __post_init__(self) -> None:
        if type(self.state) is not CandidateStateInput:
            raise ProtocolViolation("diagnose state must be CandidateStateInput")
        if type(self.query) is not DiagnosisQuery:
            raise ProtocolViolation("diagnose query must be DiagnosisQuery")
        _seed(self.seed)

    @property
    def operation(self) -> Operation:
        return Operation.DIAGNOSE

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": REQUEST_PROTOCOL,
            "operation": self.operation.value,
            "seed": self.seed,
            "state": state_input_to_wire(self.state),
            "query": self.query.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class RolloutRequest:
    state: CandidateStateInput
    query: RolloutQuery
    seed: int

    def __post_init__(self) -> None:
        if type(self.state) is not CandidateStateInput:
            raise ProtocolViolation("rollout state must be CandidateStateInput")
        if type(self.query) is not RolloutQuery:
            raise ProtocolViolation("rollout query must be RolloutQuery")
        _seed(self.seed)

    @property
    def operation(self) -> Operation:
        return Operation.ROLLOUT

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": REQUEST_PROTOCOL,
            "operation": self.operation.value,
            "seed": self.seed,
            "state": state_input_to_wire(self.state),
            "query": self.query.to_wire(),
        }


CandidateRequest: TypeAlias = (
    InitializeRequest | UpdateRequest | DiagnoseRequest | RolloutRequest
)


@dataclass(frozen=True, slots=True)
class StateResponse:
    operation: Operation
    state: StatePayload

    def __post_init__(self) -> None:
        if self.operation not in {Operation.INITIALIZE, Operation.UPDATE}:
            raise ProtocolViolation("StateResponse is only valid for initialize/update")
        if type(self.state) is not StatePayload:
            raise ProtocolViolation("state response must contain StatePayload")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": RESPONSE_PROTOCOL,
            "operation": self.operation.value,
            "state": state_payload_to_wire(self.state),
        }


@dataclass(frozen=True, slots=True)
class DiagnosisResult:
    status: ResultStatus
    probabilities: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.status) is not ResultStatus:
            raise ProtocolViolation("diagnosis status must be ResultStatus")
        if type(self.probabilities) is not dict:
            raise ProtocolViolation("diagnosis probabilities must be an exact dict")
        for label, probability in self.probabilities.items():
            _nonempty(label, "diagnosis probability label")
            if type(probability) not in {int, float}:
                raise ProtocolViolation("diagnosis probabilities must be numeric")
            validate_json_like(probability)
            if probability < 0.0 or probability > 1.0:
                raise ProtocolViolation("diagnosis probability is outside [0,1]")
        if self.status is ResultStatus.OK:
            if not self.probabilities:
                raise ProtocolViolation("ok diagnosis requires probabilities")
            if abs(sum(self.probabilities.values()) - 1.0) > 1e-9:
                raise ProtocolViolation("diagnosis probabilities must sum to one")
        elif self.probabilities:
            raise ProtocolViolation("non-ok diagnosis cannot claim probabilities")
        if type(self.metadata) is not dict:
            raise ProtocolViolation("diagnosis metadata must be an exact dict")
        _forbid_head_state_fields(self.metadata, "$.diagnosis.metadata")

    def to_wire(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "probabilities": self.probabilities,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class DiagnoseResponse:
    result: DiagnosisResult

    def __post_init__(self) -> None:
        if type(self.result) is not DiagnosisResult:
            raise ProtocolViolation("diagnose response must contain DiagnosisResult")

    @property
    def operation(self) -> Operation:
        return Operation.DIAGNOSE

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": RESPONSE_PROTOCOL,
            "operation": self.operation.value,
            "result": self.result.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class RolloutResult:
    """A world-scored predictive distribution returned by the shared head.

    ``observable_predictions`` is keyed by the requested observable IDs.  Each
    value is closed JSON-like distribution data interpreted and scored by the
    frozen world contract.  This envelope intentionally does not dictate one
    universal distribution family, but it does forbid a returned factual state.
    """

    status: ResultStatus
    observable_predictions: dict[str, Any] = field(default_factory=dict)
    utility_prediction: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.status) is not ResultStatus:
            raise ProtocolViolation("rollout status must be ResultStatus")
        for value, label in (
            (self.observable_predictions, "observable_predictions"),
            (self.utility_prediction, "utility_prediction"),
            (self.metadata, "rollout metadata"),
        ):
            if type(value) is not dict:
                raise ProtocolViolation(f"{label} must be an exact dict")
            _forbid_head_state_fields(value, f"$.rollout.{label}")
        if self.status is ResultStatus.OK:
            if not self.observable_predictions:
                raise ProtocolViolation("ok rollout requires observable predictions")
        elif self.observable_predictions or self.utility_prediction:
            raise ProtocolViolation("non-ok rollout cannot claim predictions")

    def to_wire(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "observable_predictions": self.observable_predictions,
            "utility_prediction": self.utility_prediction,
            "metadata": self.metadata,
        }


@dataclass(frozen=True, slots=True)
class RolloutResponse:
    result: RolloutResult

    def __post_init__(self) -> None:
        if type(self.result) is not RolloutResult:
            raise ProtocolViolation("rollout response must contain RolloutResult")

    @property
    def operation(self) -> Operation:
        return Operation.ROLLOUT

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": RESPONSE_PROTOCOL,
            "operation": self.operation.value,
            "result": self.result.to_wire(),
        }


CandidateResponse: TypeAlias = StateResponse | DiagnoseResponse | RolloutResponse


class UCMCandidateV1(Protocol):
    """The candidate-side API.  All four seeds are mandatory keyword inputs."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload: ...

    def update(
        self,
        state: CandidateStateInput,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> StatePayload: ...

    def diagnose(
        self,
        state: CandidateStateInput,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> DiagnosisResult: ...

    def rollout(
        self,
        state: CandidateStateInput,
        query: RolloutQuery,
        *,
        query_seed: int,
    ) -> RolloutResult: ...


class CandidateCallViolation(ProtocolViolation):
    """A typed candidate/harness boundary failure."""

    def __init__(self, failure_code: str, message: str) -> None:
        super().__init__(message)
        self.failure_code = failure_code


def state_payload_to_wire(payload: StatePayload) -> dict[str, Any]:
    if type(payload) is not StatePayload:
        raise ProtocolViolation("state payload must be StatePayload")
    raw = payload.payload
    codec = payload.codec
    schema_version = payload.schema_version
    state_class = payload.state_class
    if type(raw) is not bytes:
        raise ProtocolViolation("state payload bytes must be exact bytes")
    if len(raw) > MAX_STATE_PAYLOAD_BYTES:
        raise ProtocolViolation("state payload exceeds protocol size limit")
    if type(codec) is not str or type(schema_version) is not str:
        raise ProtocolViolation("state payload metadata must be exact strings")
    if type(state_class) is not StateClass:
        raise ProtocolViolation("state payload class must be StateClass")
    return {
        "codec": codec,
        "schema_version": schema_version,
        "state_class": state_class.value,
        "payload_b64": base64.b64encode(raw).decode("ascii"),
    }


def state_input_to_wire(state: CandidateStateInput) -> dict[str, Any]:
    if type(state) is not CandidateStateInput:
        raise ProtocolViolation("state input must be CandidateStateInput")
    return state_payload_to_wire(state.payload)


def state_payload_from_wire(value: object) -> StatePayload:
    obj = _exact_keys(
        value,
        required=frozenset(
            {"codec", "schema_version", "state_class", "payload_b64"}
        ),
        label="state payload",
    )
    codec = _nonempty(obj["codec"], "state codec")
    schema_version = _nonempty(obj["schema_version"], "state schema_version")
    encoded = _nonempty(obj["payload_b64"], "state payload_b64")
    try:
        raw = base64.b64decode(encoded.encode("ascii"), validate=True)
    except (ValueError, UnicodeEncodeError) as exc:
        raise ProtocolViolation("state payload_b64 is not canonical base64") from exc
    if len(raw) > MAX_STATE_PAYLOAD_BYTES:
        raise ProtocolViolation("state payload exceeds protocol size limit")
    try:
        state_class = StateClass(obj["state_class"])
    except (ValueError, TypeError) as exc:
        raise ProtocolViolation("unknown state_class") from exc
    return StatePayload(
        payload=raw,
        codec=codec,
        schema_version=schema_version,
        state_class=state_class,
    )


def _event_from_wire(value: object) -> CandidateVisibleEvent:
    obj = _exact_keys(
        value,
        required=frozenset(
            {
                "kind",
                "occurred_at",
                "collected_at",
                "available_at",
                "event_uid",
                "payload",
            }
        ),
        label="visible event",
    )
    try:
        kind = EventKind(obj["kind"])
    except (ValueError, TypeError) as exc:
        raise ProtocolViolation("unknown visible event kind") from exc
    return CandidateVisibleEvent(
        kind=kind,
        occurred_at=obj["occurred_at"],
        collected_at=obj["collected_at"],
        available_at=obj["available_at"],
        event_uid=obj["event_uid"],
        payload=obj["payload"],
    )


def _history_from_wire(value: object) -> VisibleHistory:
    obj = _exact_keys(
        value,
        required=frozenset(
            {"protocol", "as_of_available_at", "catalog_digest", "events"}
        ),
        label="visible history",
    )
    if obj["protocol"] != "ucm-visible-history/1":
        raise ProtocolViolation("unknown visible history protocol")
    if type(obj["events"]) is not list:
        raise ProtocolViolation("visible history events must be a list")
    return VisibleHistory(
        events=tuple(_event_from_wire(item) for item in obj["events"]),
        as_of_available_at=obj["as_of_available_at"],
        catalog_digest=obj["catalog_digest"],
    )


def _delta_from_wire(value: object) -> VisibleDelta:
    obj = _exact_keys(
        value,
        required=frozenset({"protocol", "advance_to", "events"}),
        label="visible delta",
    )
    if obj["protocol"] != "ucm-visible-delta/1":
        raise ProtocolViolation("unknown visible delta protocol")
    if type(obj["events"]) is not list:
        raise ProtocolViolation("delta events must be a list")
    return VisibleDelta(
        advance_to=obj["advance_to"],
        events=tuple(_event_from_wire(item) for item in obj["events"]),
    )


def _plan_from_wire(value: object) -> ActionPlan:
    obj = _exact_keys(
        value,
        required=frozenset({"kind", "actions", "policy_digest"}),
        label="action plan",
    )
    try:
        kind = PlanKind(obj["kind"])
    except (ValueError, TypeError) as exc:
        raise ProtocolViolation("unknown action plan kind") from exc
    if type(obj["actions"]) is not list:
        raise ProtocolViolation("action plan actions must be a list")
    actions: list[PlannedAction] = []
    for value in obj["actions"]:
        action = _exact_keys(
            value,
            required=frozenset({"offset", "action_id", "parameters"}),
            label="planned action",
        )
        actions.append(
            PlannedAction(
                offset=action["offset"],
                action_id=action["action_id"],
                parameters=action["parameters"],
            )
        )
    return ActionPlan(
        kind=kind,
        actions=tuple(actions),
        policy_digest=obj["policy_digest"],
    )


def _diagnosis_query_from_wire(value: object) -> DiagnosisQuery:
    obj = _exact_keys(
        value,
        required=frozenset({"protocol", "label_catalog"}),
        label="diagnosis query",
    )
    if obj["protocol"] != "ucm-diagnosis-query/1":
        raise ProtocolViolation("unknown diagnosis query protocol")
    if type(obj["label_catalog"]) is not list:
        raise ProtocolViolation("label_catalog must be a list")
    return DiagnosisQuery(tuple(obj["label_catalog"]))


def _rollout_query_from_wire(value: object) -> RolloutQuery:
    obj = _exact_keys(
        value,
        required=frozenset(
            {
                "protocol",
                "horizon",
                "plan",
                "requested_observables",
                "utility_digest",
            }
        ),
        label="rollout query",
    )
    if obj["protocol"] != "ucm-rollout-query/1":
        raise ProtocolViolation("unknown rollout query protocol")
    if type(obj["requested_observables"]) is not list:
        raise ProtocolViolation("requested_observables must be a list")
    return RolloutQuery(
        horizon=obj["horizon"],
        plan=_plan_from_wire(obj["plan"]),
        requested_observables=tuple(obj["requested_observables"]),
        utility_digest=obj["utility_digest"],
    )


def request_from_wire(value: object) -> CandidateRequest:
    if type(value) is not dict:
        raise ProtocolViolation("candidate request must be an exact object")
    if value.get("protocol") != REQUEST_PROTOCOL:
        raise ProtocolViolation("unknown candidate request protocol")
    try:
        operation = Operation(value.get("operation"))
    except (ValueError, TypeError) as exc:
        raise ProtocolViolation("unknown candidate operation") from exc

    if operation is Operation.INITIALIZE:
        obj = _exact_keys(
            value,
            required=frozenset({"protocol", "operation", "seed", "history"}),
            label="initialize request",
        )
        return InitializeRequest(_history_from_wire(obj["history"]), obj["seed"])
    if operation is Operation.UPDATE:
        obj = _exact_keys(
            value,
            required=frozenset(
                {"protocol", "operation", "seed", "state", "delta"}
            ),
            label="update request",
        )
        return UpdateRequest(
            CandidateStateInput(state_payload_from_wire(obj["state"])),
            _delta_from_wire(obj["delta"]),
            obj["seed"],
        )
    if operation is Operation.DIAGNOSE:
        obj = _exact_keys(
            value,
            required=frozenset(
                {"protocol", "operation", "seed", "state", "query"}
            ),
            label="diagnose request",
        )
        return DiagnoseRequest(
            CandidateStateInput(state_payload_from_wire(obj["state"])),
            _diagnosis_query_from_wire(obj["query"]),
            obj["seed"],
        )
    obj = _exact_keys(
        value,
        required=frozenset({"protocol", "operation", "seed", "state", "query"}),
        label="rollout request",
    )
    return RolloutRequest(
        CandidateStateInput(state_payload_from_wire(obj["state"])),
        _rollout_query_from_wire(obj["query"]),
        obj["seed"],
    )


def response_from_wire(value: object) -> CandidateResponse:
    if type(value) is not dict:
        raise ProtocolViolation("candidate response must be an exact object")
    if value.get("protocol") != RESPONSE_PROTOCOL:
        raise ProtocolViolation("unknown candidate response protocol")
    try:
        operation = Operation(value.get("operation"))
    except (ValueError, TypeError) as exc:
        raise ProtocolViolation("unknown response operation") from exc
    if operation in {Operation.INITIALIZE, Operation.UPDATE}:
        obj = _exact_keys(
            value,
            required=frozenset({"protocol", "operation", "state"}),
            label="state response",
        )
        return StateResponse(operation, state_payload_from_wire(obj["state"]))

    obj = _exact_keys(
        value,
        required=frozenset({"protocol", "operation", "result"}),
        label="head response",
    )
    if operation is Operation.DIAGNOSE:
        result = _exact_keys(
            obj["result"],
            required=frozenset({"status", "probabilities", "metadata"}),
            label="diagnosis result",
        )
        try:
            status = ResultStatus(result["status"])
        except (ValueError, TypeError) as exc:
            raise ProtocolViolation("unknown diagnosis status") from exc
        return DiagnoseResponse(
            DiagnosisResult(
                status=status,
                probabilities=result["probabilities"],
                metadata=result["metadata"],
            )
        )
    result = _exact_keys(
        obj["result"],
        required=frozenset(
            {
                "status",
                "observable_predictions",
                "utility_prediction",
                "metadata",
            }
        ),
        label="rollout result",
    )
    try:
        status = ResultStatus(result["status"])
    except (ValueError, TypeError) as exc:
        raise ProtocolViolation("unknown rollout status") from exc
    return RolloutResponse(
        RolloutResult(
            status=status,
            observable_predictions=result["observable_predictions"],
            utility_prediction=result["utility_prediction"],
            metadata=result["metadata"],
        )
    )


def _validate_response_for_request(
    request: CandidateRequest, response: CandidateResponse
) -> None:
    if isinstance(request, InitializeRequest):
        expected = Operation.INITIALIZE
    elif isinstance(request, UpdateRequest):
        expected = Operation.UPDATE
    elif isinstance(request, DiagnoseRequest):
        expected = Operation.DIAGNOSE
    else:
        expected = Operation.ROLLOUT
    actual = response.operation
    if actual is not expected:
        raise CandidateCallViolation(
            "UCM-F022-INVALID_DISTRIBUTION",
            f"candidate returned {actual.value} response for {expected.value}",
        )
    if isinstance(request, DiagnoseRequest) and isinstance(
        response, DiagnoseResponse
    ):
        if response.result.status is ResultStatus.OK and set(
            response.result.probabilities
        ) != set(request.query.label_catalog):
            raise CandidateCallViolation(
                "UCM-F022-INVALID_DISTRIBUTION",
                "diagnosis response labels do not equal the query catalog",
            )
    if isinstance(request, RolloutRequest) and isinstance(response, RolloutResponse):
        if response.result.status is ResultStatus.OK:
            requested = set(request.query.requested_observables)
            returned = set(response.result.observable_predictions)
            if returned != requested:
                missing = sorted(requested - returned)
                extra = sorted(returned - requested)
                raise CandidateCallViolation(
                    "UCM-F022-INVALID_DISTRIBUTION",
                    "rollout response observable keys do not equal the query; "
                    f"missing={missing!r}, extra={extra!r}",
                )


def _bounded_json_wire_size(value: Any, *, limit: int) -> tuple[int, Any]:
    """Compute the canonical JSON UTF-8 size without building a giant frame.

    Candidate metadata is untrusted.  Calling ``json.dumps`` first would let a
    single enormous string allocate an equally enormous temporary buffer before
    the protocol limit is checked.  This walker mirrors the compact canonical
    encoder's separators/string escaping and fails as soon as the limit is
    exceeded.
    """

    total = 1  # canonical_json_bytes appends one terminal LF
    nodes = 0

    def add(amount: int) -> None:
        nonlocal total
        total += amount
        if total > limit:
            raise CandidateCallViolation(
                "UCM-F008-STATE_NOT_CLOSED",
                "candidate response frame exceeds protocol size limit",
            )

    def string_size(text: str) -> int:
        # Every code point contributes at least one UTF-8/escape byte.  This
        # makes the hostile common case O(1) once it cannot possibly fit.
        if len(text) + 2 > limit:
            return limit + 1
        size = 2
        for character in text:
            ordinal = ord(character)
            if character in {'"', "\\"}:
                size += 2
            elif character in {"\b", "\f", "\n", "\r", "\t"}:
                size += 2
            elif ordinal < 0x20:
                size += 6
            elif ordinal < 0x80:
                size += 1
            elif ordinal < 0x800:
                size += 2
            elif ordinal < 0x10000:
                size += 3
            else:
                size += 4
            if size > limit:
                return size
        return size

    def walk(node: Any, depth: int) -> Any:
        nonlocal nodes
        nodes += 1
        if nodes > 1_000_000 or depth > 64:
            raise CandidateCallViolation(
                "UCM-F008-STATE_NOT_CLOSED",
                "candidate response JSON structure exceeds protocol limits",
            )
        kind = type(node)
        if node is None:
            add(4)
            return None
        elif kind is bool:
            add(4 if node else 5)
            return node
        elif kind is int:
            add(len(str(node)))
            return node
        elif kind is float:
            if not math.isfinite(node):
                raise CandidateCallViolation(
                    "UCM-F008-STATE_NOT_CLOSED",
                    "candidate response contains a non-finite number",
                )
            # The canonical encoder uses Python's JSON number rendering.
            add(len(json.dumps(node, allow_nan=False)))
            return node
        elif kind is str:
            add(string_size(node))
            return node
        elif kind is list:
            add(2)
            frozen_list: list[Any] = []
            for index, child in enumerate(node):
                if index:
                    add(1)
                frozen_list.append(walk(child, depth + 1))
            return frozen_list
        elif kind is dict:
            add(2)
            if any(type(key) is not str for key in node):
                raise CandidateCallViolation(
                    "UCM-F008-STATE_NOT_CLOSED",
                    "candidate response JSON keys must be strings",
                )
            try:
                items = sorted(tuple(node.items()))
            except RuntimeError as exc:
                raise CandidateCallViolation(
                    "UCM-F008-STATE_NOT_CLOSED",
                    "candidate mutated its response during serialization",
                ) from exc
            frozen_dict: dict[str, Any] = {}
            for index, (key, child) in enumerate(items):
                if index:
                    add(1)
                add(string_size(key))
                add(1)
                frozen_dict[key] = walk(child, depth + 1)
            return frozen_dict
        else:
            raise CandidateCallViolation(
                "UCM-F008-STATE_NOT_CLOSED",
                "candidate response is not JSON-like",
            )

    frozen = walk(value, 0)
    return total, frozen


def _canonical_bounded_response_frame(value: dict[str, Any]) -> bytes:
    _, frozen = _bounded_json_wire_size(value, limit=MAX_RESPONSE_FRAME_BYTES)
    encoded = canonical_json_bytes(frozen)
    if len(encoded) > MAX_RESPONSE_FRAME_BYTES:
        raise CandidateCallViolation(
            "UCM-F008-STATE_NOT_CLOSED",
            "candidate response frame exceeds protocol size limit",
        )
    return encoded


def _dispatch_candidate(
    candidate: UCMCandidateV1,
    request: CandidateRequest,
    *,
    phase_hook: Callable[[str], None] | None = None,
) -> CandidateResponse:
    before = canonical_json_bytes(request.to_wire())
    if phase_hook is not None:
        phase_hook("candidate-call")
    try:
        if isinstance(request, InitializeRequest):
            candidate_value = candidate.initialize(
                request.history, inference_seed=request.seed
            )
        elif isinstance(request, UpdateRequest):
            candidate_value = candidate.update(
                request.state,
                request.delta,
                inference_seed=request.seed,
            )
        elif isinstance(request, DiagnoseRequest):
            candidate_value = candidate.diagnose(
                request.state,
                request.query,
                query_seed=request.seed,
            )
        else:
            candidate_value = candidate.rollout(
                request.state,
                request.query,
                query_seed=request.seed,
            )
    except BaseException as exc:
        raise CandidateCallViolation(
            "UCM-F008-STATE_NOT_CLOSED",
            f"candidate operation {request.operation.value} failed: "
            f"{type(exc).__name__}: {exc}",
        ) from exc
    expected_type: type[Any]
    if isinstance(request, (InitializeRequest, UpdateRequest)):
        expected_type = StatePayload
    elif isinstance(request, DiagnoseRequest):
        expected_type = DiagnosisResult
    else:
        expected_type = RolloutResult
    if type(candidate_value) is not expected_type:
        if phase_hook is not None:
            phase_hook("candidate-validation")
        raise CandidateCallViolation(
            "UCM-F008-STATE_NOT_CLOSED",
            f"candidate operation {request.operation.value} returned "
            f"{type(candidate_value).__name__}; expected {expected_type.__name__}",
        )
    if phase_hook is not None:
        phase_hook("harness-response-finalization")
    try:
        if isinstance(request, InitializeRequest):
            response: CandidateResponse = StateResponse(
                Operation.INITIALIZE, candidate_value
            )
        elif isinstance(request, UpdateRequest):
            response = StateResponse(Operation.UPDATE, candidate_value)
        elif isinstance(request, DiagnoseRequest):
            response = DiagnoseResponse(candidate_value)
        else:
            response = RolloutResponse(candidate_value)
        after = canonical_json_bytes(request.to_wire())
        if after != before:
            code = (
                "UCM-F012-QUERY_MUTATES_FACT"
                if request.operation in {Operation.DIAGNOSE, Operation.ROLLOUT}
                else "UCM-F019-UPDATE_INCONSISTENT"
            )
            raise CandidateCallViolation(
                code, "candidate mutated its request/state/query"
            )
        _validate_response_for_request(request, response)
        response_wire = response.to_wire()
        response_frame = _canonical_bounded_response_frame(response_wire)
        frozen_response = response_from_wire(
            json.loads(response_frame.decode("utf-8"))
        )
        _validate_response_for_request(request, frozen_response)
        return frozen_response
    except CandidateCallViolation:
        if phase_hook is not None:
            phase_hook("candidate-validation")
        raise


@dataclass(frozen=True, slots=True)
class CandidateEntrypoint:
    bundle_root: Path
    module: str
    qualname: str
    model_relative_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        root = Path(self.bundle_root).resolve()
        if not root.is_dir():
            raise ProtocolViolation("candidate bundle_root must be an existing directory")
        object.__setattr__(self, "bundle_root", root)
        module = _nonempty(self.module, "candidate module")
        qualname = _nonempty(self.qualname, "candidate qualname")
        dotted = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
        if dotted.fullmatch(module) is None or dotted.fullmatch(qualname) is None:
            raise ProtocolViolation("candidate module/qualname must be dotted identifiers")
        if type(self.model_relative_paths) is not tuple:
            raise ProtocolViolation("model_relative_paths must be an exact tuple")
        normalized_models: list[str] = []
        for raw in self.model_relative_paths:
            if type(raw) is not str or not raw:
                raise ProtocolViolation("model_relative_paths must contain strings")
            normalized = raw.replace("\\", "/")
            relative = Path(normalized)
            if (
                relative.is_absolute()
                or normalized.startswith("/")
                or any(part in {"", ".", ".."} for part in relative.parts)
                or relative.as_posix() != normalized
            ):
                raise ProtocolViolation("model paths must be canonical relative paths")
            normalized_models.append(normalized)
        if normalized_models != sorted(set(normalized_models)):
            raise ProtocolViolation("model_relative_paths must be sorted and unique")
        object.__setattr__(self, "model_relative_paths", tuple(normalized_models))


def _loaded_module_origin(module: Any, bundle_root: Path) -> str:
    spec = getattr(module, "__spec__", None)
    origin = getattr(spec, "origin", None) or getattr(module, "__file__", None)
    if type(origin) is not str or origin in {"built-in", "frozen"}:
        raise ProtocolViolation("candidate module has no regular-file origin")
    resolved = Path(origin).resolve()
    try:
        return resolved.relative_to(bundle_root.resolve()).as_posix()
    except ValueError as exc:
        raise ProtocolViolation("candidate module origin escaped the bound bundle") from exc


def _load_candidate(
    entrypoint: CandidateEntrypoint, inventory: _WorkerImportInventory
) -> UCMCandidateV1:
    bundle_root = entrypoint.bundle_root.resolve()
    root_text = str(entrypoint.bundle_root)
    added = root_text not in sys.path
    if added:
        sys.path.insert(0, root_text)
    try:
        if inventory.mode == "snapshot":
            top_level = entrypoint.module.split(".", 1)[0]
            existing = sys.modules.get(top_level)
            if existing is not None:
                try:
                    existing_origin = _loaded_module_origin(existing, bundle_root)
                except ProtocolViolation as exc:
                    raise ProtocolViolation(
                        "candidate module namespace collides with the harness"
                    ) from exc
                if not existing_origin:
                    raise ProtocolViolation(
                        "candidate module namespace collides with the harness"
                    )
        module = importlib.import_module(entrypoint.module)
        actual_origin = _loaded_module_origin(module, bundle_root)
        if actual_origin != inventory.module_origin:
            raise ProtocolViolation(
                "candidate module origin does not match the byte inventory"
            )
        target: Any = module
        for component in entrypoint.qualname.split("."):
            target = getattr(target, component)
        candidate = target()
    finally:
        if added:
            try:
                sys.path.remove(root_text)
            except ValueError:
                pass
    return candidate


@dataclass(frozen=True, slots=True)
class InvocationOutcome:
    response: CandidateResponse
    request_digest: str
    response_digest: str
    isolation: str
    audit_events: tuple[dict[str, Any], ...] = ()
    audit_overflow: bool = False
    captured_stdout: str = ""
    captured_stderr: str = ""
    worker_pid: int | None = None
    import_inventory_digest: str | None = None
    harness_bundle_digest: str | None = None
    candidate_bundle_digest: str | None = None
    candidate_model_digest: str | None = None
    module_origin: str | None = None


class CandidateExecutor(Protocol):
    def invoke(self, request: CandidateRequest) -> InvocationOutcome: ...


class InProcessExecutor:
    """Fast protocol executor; not isolation evidence."""

    def __init__(self, candidate: UCMCandidateV1) -> None:
        self.candidate = candidate

    def invoke(self, request: CandidateRequest) -> InvocationOutcome:
        if not isinstance(
            request,
            (InitializeRequest, UpdateRequest, DiagnoseRequest, RolloutRequest),
        ):
            raise ProtocolViolation("unknown candidate request type")
        stdout_accumulator = _BoundedByteAccumulator(MAX_CAPTURED_STREAM_BYTES)
        stderr_accumulator = _BoundedByteAccumulator(MAX_CAPTURED_STREAM_BYTES)
        stdout = _BoundedTextCapture(stdout_accumulator)
        stderr = _BoundedTextCapture(stderr_accumulator)
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            response = _dispatch_candidate(self.candidate, request)
        captured_stdout, stdout_overflow = stdout_accumulator.snapshot_text()
        captured_stderr, stderr_overflow = stderr_accumulator.snapshot_text()
        if stdout_overflow or stderr_overflow:
            raise CandidateCallViolation(
                "UCM-F008-STATE_NOT_CLOSED",
                "in-process candidate output exceeded the captured stream limit",
            )
        return InvocationOutcome(
            response=response,
            request_digest=digest_json(request.to_wire()),
            response_digest=digest_json(response.to_wire()),
            isolation="in-process-none",
            captured_stdout=captured_stdout,
            captured_stderr=captured_stderr,
        )


def _canonical_candidate_failure_code(value: object) -> str | None:
    suffix = value[9:] if type(value) is str and len(value) > 9 else ""
    if (
        type(value) is str
        and value.startswith("UCM-F")
        and 9 < len(value) <= 128
        and value[5:8].isdigit()
        and value[8] == "-"
        and suffix[0] in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        and suffix[-1] in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        and all(
            character in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
            for character in suffix
        )
        and "__" not in suffix
    ):
        return value
    return None


def _validate_failure_origin_code(failure_origin: object, failure_code: object) -> None:
    if failure_origin not in {"candidate", "harness"}:
        raise ProtocolViolation("failure_origin must be candidate or harness")
    if failure_origin == "harness":
        if failure_code != "UCM-E003-HARNESS_INCOMPLETE":
            raise ProtocolViolation(
                "harness failures must use UCM-E003-HARNESS_INCOMPLETE"
            )
    elif _canonical_candidate_failure_code(failure_code) is None:
        raise ProtocolViolation("candidate failures must use a canonical UCM-F code")


class WorkerInvocationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_code: str,
        audit_events: tuple[dict[str, Any], ...] = (),
        audit_overflow: bool = False,
        captured_stdout: str = "",
        captured_stderr: str = "",
        returncode: int | None = None,
        failure_origin: str = "harness",
        import_inventory_digest: str | None = None,
        harness_bundle_digest: str | None = None,
        candidate_bundle_digest: str | None = None,
        candidate_model_digest: str | None = None,
        module_origin: str | None = None,
    ) -> None:
        super().__init__(_bounded_evidence_text(message))
        _validate_failure_origin_code(failure_origin, failure_code)
        self.failure_code = failure_code
        self.audit_events = audit_events
        self.audit_overflow = audit_overflow
        # This is the final parent-side guard.  Even a malformed or hostile
        # worker envelope cannot make retained error evidence exceed the
        # benchmark's per-stream ceiling.
        self.captured_stdout = _bounded_evidence_text(captured_stdout)
        self.captured_stderr = _bounded_evidence_text(captured_stderr)
        self.returncode = returncode
        self.failure_origin = failure_origin
        self.import_inventory_digest = import_inventory_digest
        self.harness_bundle_digest = harness_bundle_digest
        self.candidate_bundle_digest = candidate_bundle_digest
        self.candidate_model_digest = candidate_model_digest
        self.module_origin = module_origin


IMPORT_INVENTORY_PROTOCOL = "ucm-python-import-byte-inventory/3"
RUNTIME_IMPORT_CLOSURE_PROTOCOL = "ucm-runtime-import-closure/1"
RUNTIME_BINDING_KIND = (
    "stdlib-exact-source-binary-bytes+isolated-prefix-absent-cache-probes"
)
HARNESS_BUNDLE_PROTOCOL = "ucm-python-harness-source-snapshot/1"
BOOTSTRAP_PROTOCOL = "ucm-python-worker-bootstrap/1"
# Compatibility name retained for source-binding registries.  The wire value
# intentionally changed because v2 binds candidate bytes, not only file names.
IMPORT_ALLOWLIST_PROTOCOL = IMPORT_INVENTORY_PROTOCOL
_IMPORT_FILE_SUFFIXES = frozenset(
    suffix.lower() for suffix in importlib.machinery.all_suffixes()
) | frozenset({".zip"})
_IMPORT_TREE_PRUNE = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "site-packages",
        "dist-packages",
    }
)
_HARNESS_SOURCE_RELATIVE_PATHS = (
    "prototype/__init__.py",
    "prototype/unified_map/__init__.py",
    "prototype/unified_map/candidate_protocol.py",
    "prototype/unified_map/canonical.py",
    "prototype/unified_map/schema.py",
    "prototype/unified_map/state.py",
)


def _source_cache_filename(source: Path) -> str:
    """Return CPython's exact cache filename without consulting parent globals."""

    cache_tag = sys.implementation.cache_tag
    if not cache_tag:
        raise ProtocolViolation("approved Python runtime has no bytecode cache tag")
    base, separator, rest = source.name.rpartition(".")
    stem = base if base else rest
    almost = f"{stem}{separator}{cache_tag}"
    if sys.flags.optimize:
        almost = f"{almost}.opt-{sys.flags.optimize}"
    return f"{almost}.pyc"


def _source_cache_relative_path(root: Path, relative: str, label: str) -> str:
    """Return a stable logical source-adjacent cache identity.

    The logical identity remains part of stable harness/candidate bundle
    digests.  Workers map it to their private ``-X pycache_prefix`` authority;
    this function must therefore ignore a non-``-B`` parent's mutable
    ``sys.pycache_prefix``.
    """

    source = (root / Path(relative)).resolve(strict=False)
    cache_path = source.parent / "__pycache__" / _source_cache_filename(source)
    try:
        return cache_path.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise ProtocolViolation(f"{label} cache probe escaped its authority root") from exc


def _source_cache_path_under_prefix(
    pycache_prefix: Path, source: Path, label: str
) -> Path:
    """Mirror one absolute source path under a worker-private cache prefix."""

    prefix = pycache_prefix.resolve(strict=False)
    resolved_source = source.resolve(strict=False)
    drive, source_parent = os.path.splitdrive(str(resolved_source.parent))
    del drive
    separators = os.sep + (os.altsep or "")
    mirrored_parent = source_parent.lstrip(separators)
    cache_path = (
        prefix / Path(mirrored_parent) / _source_cache_filename(resolved_source)
    ).resolve(strict=False)
    try:
        cache_path.relative_to(prefix)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} cache probe escaped its private prefix") from exc
    return cache_path


def _source_cache_logical_identity(source: Path, label: str) -> str:
    """Return the stable cross-execution identity of one private cache probe."""

    normalized_source = _normalized_file_path(source)
    source_key = digest_bytes(normalized_source.encode("utf-8"))[7:]
    identity = (
        f"__ucm_private_pycache__/{source_key}/"
        f"{_source_cache_filename(Path(normalized_source))}"
    )
    if Path(identity).as_posix() != identity or ".." in Path(identity).parts:
        raise ProtocolViolation(f"{label} cache identity is not canonical")
    return identity


def _normalized_file_path(value: os.PathLike[str] | str | bytes) -> str:
    raw = os.fsdecode(os.fspath(value))
    return os.path.normcase(str(Path(raw).resolve(strict=False)))


class _PreparationTimeout(TimeoutError):
    pass


def _check_preparation_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise _PreparationTimeout("candidate preparation timed out")


def _check_fresh_completion_deadline(deadline: float) -> None:
    """Keep parent-side response parsing inside the invocation's total budget."""

    _check_preparation_deadline(deadline)


def _runtime_import_roots() -> tuple[Path, ...]:
    roots: set[Path] = set()
    for key in ("stdlib", "platstdlib"):
        raw = sysconfig.get_paths().get(key)
        if raw:
            roots.add(Path(raw).resolve())
    shared = sysconfig.get_config_var("DESTSHARED")
    if shared:
        roots.add(Path(shared).resolve())
    dll_root = Path(sys.base_prefix, "DLLs").resolve()
    if dll_root.is_dir():
        roots.add(dll_root)
    return tuple(sorted(roots, key=lambda value: os.path.normcase(str(value))))


def _approved_runtime_zip_paths() -> tuple[Path, ...]:
    filename = f"python{sys.version_info.major}{sys.version_info.minor}.zip"
    candidates = {Path(sys.base_prefix, filename).resolve(strict=False)}
    for root in _runtime_import_roots():
        candidates.add((root.parent / filename).resolve(strict=False))
    return tuple(sorted(candidates, key=lambda value: os.path.normcase(str(value))))


def _runtime_path_is_approved(path: Path) -> bool:
    resolved = path.resolve(strict=False)
    roots = _runtime_import_roots()
    for root in roots:
        try:
            relative = resolved.relative_to(root)
        except ValueError:
            continue
        lowered_parts = {part.casefold() for part in relative.parts}
        forbidden_parts = {
            part.casefold() for part in (_IMPORT_TREE_PRUNE - {"__pycache__"})
        }
        if lowered_parts & forbidden_parts:
            return False
        return True
    return resolved in _approved_runtime_zip_paths()


def _iter_import_files(
    root: Path, *, deadline: float, include_bytecode_caches: bool = False
) -> Any:
    if root.is_file():
        if root.suffix.lower() in _IMPORT_FILE_SUFFIXES:
            yield root
        return
    if not root.is_dir():
        return
    for current, directories, filenames in os.walk(root):
        _check_preparation_deadline(deadline)
        pruned = _IMPORT_TREE_PRUNE - (
            {"__pycache__"} if include_bytecode_caches else set()
        )
        directories[:] = sorted(name for name in directories if name not in pruned)
        for filename in sorted(filenames):
            _check_preparation_deadline(deadline)
            path = Path(current, filename)
            if path.suffix.lower() in _IMPORT_FILE_SUFFIXES:
                yield path


_RUNTIME_IMPORT_CACHE_LOCK = threading.Lock()
_RUNTIME_IMPORT_CACHE: tuple[
    tuple[tuple[str, int, str], ...], tuple[str, ...], tuple[str, ...], int, int
] | None = None


def _runtime_identity_wire() -> dict[str, str]:
    executable = Path(sys.executable).resolve()
    size = executable.stat().st_size
    if size > MAX_IMPORT_FILE_BYTES:
        raise ProtocolViolation("Python executable exceeds runtime identity limit")
    raw = executable.read_bytes()
    if len(raw) != size:
        raise ProtocolViolation("Python executable changed while binding runtime")
    return {
        "implementation": sys.implementation.name,
        "cache_tag": sys.implementation.cache_tag or "",
        "version": sys.version,
        "executable_sha256": digest_bytes(raw),
    }


def _approved_python_executable(value: str | None) -> str:
    """Return the one interpreter whose exact bytes the runtime seal binds."""

    if value is not None and type(value) is not str:
        raise ProtocolViolation("python_executable must be an exact string or null")
    approved = Path(sys.executable).resolve()
    requested = Path(value or sys.executable).resolve()
    if requested != approved:
        raise ProtocolViolation(
            "candidate workers must use the parent-approved Python executable"
        )
    # ``_runtime_identity_wire`` reads and hashes the same resolved executable;
    # perform it now as a fail-closed constructor gate rather than allowing an
    # alternate wrapper executable to fake bootstrap/snapshot verification.
    _runtime_identity_wire()
    return str(approved)


def _approved_interpreter_wire() -> dict[str, str | int]:
    executable = Path(sys.executable).resolve()
    if executable.is_symlink() or not executable.is_file():
        raise ProtocolViolation("approved Python executable is not a regular file")
    size = executable.stat().st_size
    if size > MAX_IMPORT_FILE_BYTES:
        raise ProtocolViolation("approved Python executable exceeds byte limit")
    raw = executable.read_bytes()
    if len(raw) != size:
        raise ProtocolViolation("approved Python executable changed while reading")
    return {
        "protocol": BOOTSTRAP_PROTOCOL,
        "resolved_path": _normalized_file_path(executable),
        "size_bytes": size,
        "sha256": digest_bytes(raw),
        "implementation": sys.implementation.name,
        "cache_tag": sys.implementation.cache_tag or "",
        "version": sys.version,
    }


def _runtime_import_read_allowlist(
    *, deadline: float
) -> tuple[
    tuple[tuple[str, int, str], ...], tuple[str, ...], tuple[str, ...], int, int
]:
    global _RUNTIME_IMPORT_CACHE
    _check_preparation_deadline(deadline)
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not _RUNTIME_IMPORT_CACHE_LOCK.acquire(timeout=remaining):
        raise _PreparationTimeout("runtime import inventory lock timed out")
    try:
        _check_preparation_deadline(deadline)
        if _RUNTIME_IMPORT_CACHE is not None:
            return _RUNTIME_IMPORT_CACHE

        allowed: set[str] = set()
        inventory: dict[str, tuple[int, str]] = {}
        total_bytes = 0
        actual_files = 0

        def bind_existing(path: Path) -> None:
            nonlocal total_bytes, actual_files
            _check_preparation_deadline(deadline)
            normalized = _normalized_file_path(path)
            if normalized in inventory:
                allowed.add(normalized)
                return
            if path.is_symlink() or not path.is_file():
                return
            size = path.stat().st_size
            if size > MAX_IMPORT_FILE_BYTES:
                raise ProtocolViolation("runtime import file exceeds byte limit")
            if actual_files + 1 > MAX_IMPORT_FILES:
                raise ProtocolViolation("runtime import inventory exceeds file limit")
            if total_bytes + size > MAX_IMPORT_TOTAL_BYTES:
                raise ProtocolViolation("runtime import inventory exceeds byte limit")
            raw = path.read_bytes()
            _check_preparation_deadline(deadline)
            if len(raw) != size:
                raise ProtocolViolation("runtime import file changed while reading")
            allowed.add(normalized)
            inventory[normalized] = (size, digest_bytes(raw))
            total_bytes += size
            actual_files += 1

        # Runtime authority is deliberately restricted to the approved Python
        # installation.  Live workspace/site modules are snapshotted under a
        # separate harness/candidate authority and must never leak into this
        # allowlist merely because the parent happened to import them already.
        runtime_roots = _runtime_import_roots()
        for path in _approved_runtime_zip_paths():
            _check_preparation_deadline(deadline)
            if path.is_file():
                bind_existing(path)
        # Bind the complete bounded stdlib source/binary closure.  Source-
        # adjacent ``.pyc`` files are deliberately excluded: workers use a
        # fresh per-process ``-X pycache_prefix`` and cannot select those shared
        # caches.  Third-party site/dist-packages remain pruned.
        for root in runtime_roots:
            for path in _iter_import_files(root, deadline=deadline):
                if path.suffix.lower() == ".pyc":
                    continue
                bind_existing(path)
                if len(allowed) > MAX_IMPORT_ALLOWED_PATHS:
                    raise ProtocolViolation(
                        "runtime import allowlist exceeds path limit"
                    )
        if len(allowed) > MAX_IMPORT_ALLOWED_PATHS:
            raise ProtocolViolation("runtime import allowlist exceeds path limit")
        runtime_entries = tuple(
            (path, size, sha256)
            for path, (size, sha256) in sorted(inventory.items())
        )
        _RUNTIME_IMPORT_CACHE = (
            runtime_entries,
            (),
            tuple(sorted(allowed)),
            actual_files,
            total_bytes,
        )
        return _RUNTIME_IMPORT_CACHE
    finally:
        _RUNTIME_IMPORT_CACHE_LOCK.release()


@dataclass(frozen=True, slots=True)
class _ByteInventoryEntry:
    relative_path: str
    size_bytes: int
    sha256: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }


def _byte_inventory_digest(
    kind: str,
    entries: tuple[_ByteInventoryEntry, ...],
    absent_paths: tuple[str, ...] = (),
) -> str:
    return digest_json(
        {
            "protocol": "ucm-exact-byte-inventory/1",
            "kind": kind,
            "entries": [entry.to_wire() for entry in entries],
            "absent_paths": list(absent_paths),
        }
    )


def _candidate_inventory_scan_root(entrypoint: CandidateEntrypoint) -> Path:
    module_path = entrypoint.bundle_root.joinpath(*entrypoint.module.split("."))
    module_files = [
        module_path.with_suffix(suffix)
        for suffix in _IMPORT_FILE_SUFFIXES
        if suffix != ".zip"
    ]
    if any(path.is_file() for path in module_files):
        # Bind the containing package/flat-module directory so relative helper
        # imports are included without sealing unrelated top-level packages.
        return module_path.parent
    if module_path.is_dir():
        return module_path
    top_level = entrypoint.module.split(".", 1)[0]
    package_root = entrypoint.bundle_root / top_level
    # A declared top-level package is the candidate namespace.  For a plain
    # module, sibling helper modules remain part of the bundle root.
    return package_root if package_root.is_dir() else entrypoint.bundle_root


def _read_inventory_file(
    path: Path,
    *,
    deadline: float,
    total_bytes: list[int],
    file_count: list[int],
) -> bytes:
    _check_preparation_deadline(deadline)
    if path.is_symlink() or not path.is_file():
        raise ProtocolViolation("candidate inventory paths must be regular files")
    size = path.stat().st_size
    if size > MAX_IMPORT_FILE_BYTES:
        raise ProtocolViolation("candidate inventory file exceeds byte limit")
    file_count[0] += 1
    total_bytes[0] += size
    if file_count[0] > MAX_IMPORT_FILES:
        raise ProtocolViolation("candidate import inventory exceeds file limit")
    if total_bytes[0] > MAX_IMPORT_TOTAL_BYTES:
        raise ProtocolViolation("candidate import inventory exceeds byte limit")
    raw = path.read_bytes()
    _check_preparation_deadline(deadline)
    if len(raw) != size:
        raise ProtocolViolation("candidate inventory file changed while reading")
    return raw


def _module_origin_relative_path(
    bundle_root: Path, module_name: str, code_paths: frozenset[str]
) -> str:
    stem = module_name.replace(".", "/")
    candidates: list[str] = []
    for suffix in sorted(_IMPORT_FILE_SUFFIXES):
        candidates.append(f"{stem}{suffix}")
        candidates.append(f"{stem}/__init__{suffix}")
    matches = [value for value in candidates if value in code_paths]
    if len(matches) != 1:
        raise ProtocolViolation(
            "candidate module must resolve to exactly one inventoried code file"
        )
    return matches[0]


@dataclass(frozen=True, slots=True)
class _PreparedImportInventory:
    manifest_path: Path
    worker_harness_root: Path
    worker_bundle_root: Path
    import_inventory_digest: str
    harness_bundle_digest: str
    bootstrap_sha256: str
    manifest_sha256: str
    candidate_bundle_digest: str
    candidate_model_digest: str
    module_origin: str


def _write_import_allowlist_manifest(
    temp_root: Path,
    entrypoint: CandidateEntrypoint,
    *,
    deadline: float,
    bootstrap_source: str | None = None,
) -> _PreparedImportInventory:
    if bootstrap_source is None:
        bootstrap_source = _UNIFIED_WORKER_BOOTSTRAP
    if type(bootstrap_source) is not str or not bootstrap_source:
        raise ProtocolViolation("worker bootstrap source must be a non-empty string")
    bootstrap_bytes = bootstrap_source.encode("utf-8")
    if len(bootstrap_bytes) > MAX_IMPORT_FILE_BYTES:
        raise ProtocolViolation("worker bootstrap source exceeds byte limit")
    (
        runtime_entries,
        shared_runtime_absent_paths,
        runtime_present_files,
        runtime_count,
        runtime_bytes,
    ) = _runtime_import_read_allowlist(deadline=deadline)
    if shared_runtime_absent_paths:
        raise ProtocolViolation("shared runtime cache authority must be empty")
    worker_pycache_prefix = (temp_root / "pycache-prefix").resolve(strict=False)
    worker_pycache_prefix.mkdir(parents=False, exist_ok=False)
    runtime_absent_paths = tuple(
        sorted(
            _source_cache_logical_identity(Path(path), "runtime")
            for path, _, _ in runtime_entries
            if Path(path).suffix.lower() == ".py"
        )
    )
    runtime_files = tuple(
        sorted(set(runtime_present_files) | set(runtime_absent_paths))
    )
    if len(runtime_files) > MAX_IMPORT_ALLOWED_PATHS:
        raise ProtocolViolation("runtime import allowlist exceeds path limit")
    total_bytes = [runtime_bytes]
    file_count = [runtime_count]
    bundle_root = entrypoint.bundle_root.resolve()
    live_harness_root = Path(__file__).resolve().parents[2]
    for runtime_path in runtime_present_files:
        try:
            Path(runtime_path).resolve(strict=False).relative_to(live_harness_root)
        except ValueError:
            continue
        raise ProtocolViolation("runtime inventory leaked a live harness path")

    live_harness = (
        bundle_root == live_harness_root
        and entrypoint.module == "prototype.unified_map.compliance"
    )
    if bundle_root == live_harness_root and not live_harness:
        raise ProtocolViolation("only the registered built-in compliance module is allowed")
    if not live_harness and (
        entrypoint.module == "prototype" or entrypoint.module.startswith("prototype.")
    ):
        raise ProtocolViolation(
            "external candidate cannot occupy the reserved prototype namespace"
        )

    # Least-authority bootstrap closure.  The two generated inert package
    # initializers prevent the live package initializers from pulling unrelated
    # benchmark/judge modules into the candidate's readable namespace.
    harness_bytes: dict[str, bytes] = {
        "prototype/__init__.py": (
            b'"""Generated isolated UCM harness package."""\n'
        ),
        "prototype/unified_map/__init__.py": (
            b'"""Generated isolated UCM protocol package."""\n'
        ),
    }
    required_harness_sources = set(_HARNESS_SOURCE_RELATIVE_PATHS) - set(
        harness_bytes
    )
    for relative in sorted(required_harness_sources):
        path = live_harness_root / Path(relative)
        harness_bytes[relative] = _read_inventory_file(
            path,
            deadline=deadline,
            total_bytes=total_bytes,
            file_count=file_count,
        )
    file_count[0] += 2
    total_bytes[0] += sum(
        len(harness_bytes[key])
        for key in ("prototype/__init__.py", "prototype/unified_map/__init__.py")
    )
    if file_count[0] > MAX_IMPORT_FILES or total_bytes[0] > MAX_IMPORT_TOTAL_BYTES:
        raise ProtocolViolation("harness source snapshot exceeds combined limits")

    worker_harness_root = temp_root / "harness-snapshot"
    worker_harness_root.mkdir(parents=True, exist_ok=False)
    for relative, raw in sorted(harness_bytes.items()):
        _check_preparation_deadline(deadline)
        target = worker_harness_root / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        try:
            target.chmod(0o444)
        except OSError:
            pass

    harness_entries = tuple(
        _ByteInventoryEntry(relative, len(raw), digest_bytes(raw))
        for relative, raw in sorted(harness_bytes.items())
    )
    if tuple(entry.relative_path for entry in harness_entries) != (
        _HARNESS_SOURCE_RELATIVE_PATHS
    ):
        raise ProtocolViolation("harness source snapshot authority drifted")
    harness_absent = tuple(
        sorted(
            _source_cache_relative_path(
                worker_harness_root, relative, "harness"
            )
            for relative in _HARNESS_SOURCE_RELATIVE_PATHS
        )
    )
    approved_interpreter = _approved_interpreter_wire()
    file_count[0] += 1
    total_bytes[0] += int(approved_interpreter["size_bytes"])
    if file_count[0] > MAX_IMPORT_FILES or total_bytes[0] > MAX_IMPORT_TOTAL_BYTES:
        raise ProtocolViolation("approved interpreter exceeds combined limits")
    bootstrap_sha256 = digest_bytes(bootstrap_bytes)
    harness_digest_wire = {
        "protocol": HARNESS_BUNDLE_PROTOCOL,
        "bootstrap_protocol": BOOTSTRAP_PROTOCOL,
        "bootstrap_sha256": bootstrap_sha256,
        "approved_interpreter": approved_interpreter,
        "entries": [entry.to_wire() for entry in harness_entries],
        "absent_paths": list(harness_absent),
    }
    harness_bundle_digest = digest_json(harness_digest_wire)

    scan_root = _candidate_inventory_scan_root(entrypoint).resolve()
    try:
        scan_root.relative_to(bundle_root)
    except ValueError as exc:
        raise ProtocolViolation("candidate inventory root escaped bundle_root") from exc

    code_bytes: dict[str, bytes] = {}
    if live_harness:
        relative = "prototype/unified_map/compliance.py"
        raw = _read_inventory_file(
            live_harness_root / Path(relative),
            deadline=deadline,
            total_bytes=total_bytes,
            file_count=file_count,
        )
        code_bytes[relative] = raw
        target = worker_harness_root / Path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        try:
            target.chmod(0o444)
        except OSError:
            pass
    else:
        for path in _iter_import_files(scan_root, deadline=deadline):
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(bundle_root).as_posix()
            except ValueError as exc:
                raise ProtocolViolation("candidate code path escaped bundle_root") from exc
            code_bytes[relative] = _read_inventory_file(
                path,
                deadline=deadline,
                total_bytes=total_bytes,
                file_count=file_count,
            )
    # Shared source-adjacent caches are not worker authority.  ``-X
    # pycache_prefix`` redirects every source cache probe to this invocation's
    # private prefix; source bytes (and genuine sourceless modules, if any)
    # remain independently inventoried above.

    model_bytes: dict[str, bytes] = {}
    code_physical_paths = {
        _normalized_file_path(bundle_root / Path(relative)) for relative in code_bytes
    }
    harness_live_physical_paths = {
        _normalized_file_path(live_harness_root / Path(relative))
        for relative in harness_bytes
    }
    model_physical_paths: set[str] = set()
    for relative in entrypoint.model_relative_paths:
        path = bundle_root / Path(relative)
        try:
            path.resolve().relative_to(bundle_root)
        except ValueError as exc:
            raise ProtocolViolation("declared model path escaped bundle_root") from exc
        normalized_model = _normalized_file_path(path)
        if (
            normalized_model in code_physical_paths
            or normalized_model in model_physical_paths
            or (live_harness and normalized_model in harness_live_physical_paths)
        ):
            raise ProtocolViolation("model path overlaps candidate code inventory")
        model_physical_paths.add(normalized_model)
        model_bytes[relative] = _read_inventory_file(
            path,
            deadline=deadline,
            total_bytes=total_bytes,
            file_count=file_count,
        )
        if live_harness:
            target = worker_harness_root / Path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(model_bytes[relative])
            try:
                target.chmod(0o444)
            except OSError:
                pass

    code_entries = tuple(
        _ByteInventoryEntry(path, len(raw), digest_bytes(raw))
        for path, raw in sorted(code_bytes.items())
    )
    model_entries = tuple(
        _ByteInventoryEntry(path, len(raw), digest_bytes(raw))
        for path, raw in sorted(model_bytes.items())
    )
    module_origin = _module_origin_relative_path(
        bundle_root, entrypoint.module, frozenset(code_bytes)
    )
    candidate_absent_cache_paths: list[str] = []
    for relative in sorted(path for path in code_bytes if path.endswith(".py")):
        cache_relative = _source_cache_relative_path(
            bundle_root, relative, "candidate"
        )
        if cache_relative not in code_bytes:
            candidate_absent_cache_paths.append(cache_relative)
    candidate_absent = tuple(sorted(set(candidate_absent_cache_paths)))
    candidate_bundle_digest = _byte_inventory_digest(
        "candidate-code", code_entries, candidate_absent
    )
    candidate_model_digest = _byte_inventory_digest("candidate-model", model_entries)
    runtime_entries_wire = [
        {"path": path, "size_bytes": size, "sha256": sha256}
        for path, size, sha256 in runtime_entries
    ]
    runtime_identity = _runtime_identity_wire()
    runtime_digest = digest_json(
        {
            "protocol": RUNTIME_IMPORT_CLOSURE_PROTOCOL,
            "binding_kind": RUNTIME_BINDING_KIND,
            "entries": runtime_entries_wire,
            "absent_paths": list(runtime_absent_paths),
            "allowed_paths": list(runtime_files),
            "runtime_identity": runtime_identity,
        }
    )
    if live_harness:
        worker_bundle_root = worker_harness_root
        mode = "harness-snapshot"
    else:
        worker_bundle_root = temp_root / "candidate-snapshot"
        worker_bundle_root.mkdir(parents=True, exist_ok=False)
        for relative, raw in sorted({**code_bytes, **model_bytes}.items()):
            target = worker_bundle_root / Path(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            try:
                target.chmod(0o444)
            except OSError:
                pass
        mode = "snapshot"

    import_inventory_digest = digest_json(
        {
            "protocol": IMPORT_INVENTORY_PROTOCOL,
            "mode": mode,
            "candidate_bundle_digest": candidate_bundle_digest,
            "candidate_model_digest": candidate_model_digest,
            "harness_bundle_digest": harness_bundle_digest,
            "runtime_allowlist_digest": runtime_digest,
            "module_origin": module_origin,
        }
    )

    value = {
        "protocol": IMPORT_INVENTORY_PROTOCOL,
        "mode": mode,
        "runtime_allowed_files": list(runtime_files),
        "runtime_entries": runtime_entries_wire,
        "runtime_absent_paths": list(runtime_absent_paths),
        "runtime_binding_kind": RUNTIME_BINDING_KIND,
        "runtime_identity": runtime_identity,
        "runtime_allowlist_digest": runtime_digest,
        "harness_entries": [entry.to_wire() for entry in harness_entries],
        "harness_absent_paths": list(harness_absent),
        "bootstrap_protocol": BOOTSTRAP_PROTOCOL,
        "bootstrap_sha256": bootstrap_sha256,
        "approved_interpreter": approved_interpreter,
        "harness_bundle_digest": harness_bundle_digest,
        "candidate_entries": [entry.to_wire() for entry in code_entries],
        "candidate_absent_paths": list(candidate_absent),
        "model_entries": [entry.to_wire() for entry in model_entries],
        "import_inventory_digest": import_inventory_digest,
        "candidate_bundle_digest": candidate_bundle_digest,
        "candidate_model_digest": candidate_model_digest,
        "module_origin": module_origin,
    }
    payload = canonical_json_bytes(value)
    if len(payload) > MAX_IMPORT_MANIFEST_BYTES:
        raise ProtocolViolation("import inventory manifest exceeds byte limit")
    path = temp_root / "import-byte-inventory.json"
    path.write_bytes(payload)
    _check_preparation_deadline(deadline)
    return _PreparedImportInventory(
        manifest_path=path,
        worker_harness_root=worker_harness_root,
        worker_bundle_root=worker_bundle_root,
        import_inventory_digest=import_inventory_digest,
        harness_bundle_digest=harness_bundle_digest,
        bootstrap_sha256=bootstrap_sha256,
        manifest_sha256=digest_bytes(payload),
        candidate_bundle_digest=candidate_bundle_digest,
        candidate_model_digest=candidate_model_digest,
        module_origin=module_origin,
    )


@dataclass(frozen=True, slots=True)
class _WorkerImportInventory:
    allowed_files: frozenset[str]
    runtime_entries: tuple[tuple[str, int, str], ...]
    runtime_absent_paths: tuple[str, ...]
    pycache_prefix: Path
    harness_root: Path
    harness_entries: tuple[_ByteInventoryEntry, ...]
    harness_absent_paths: tuple[str, ...]
    bootstrap_kind: str
    bootstrap_sha256: str
    approved_interpreter: dict[str, str | int]
    mode: str
    entries: tuple[_ByteInventoryEntry, ...]
    candidate_absent_paths: tuple[str, ...]
    model_entries: tuple[_ByteInventoryEntry, ...]
    import_inventory_digest: str
    harness_bundle_digest: str
    candidate_bundle_digest: str
    candidate_model_digest: str
    module_origin: str


def _parse_inventory_entries(value: object, label: str) -> tuple[_ByteInventoryEntry, ...]:
    if type(value) is not list or len(value) > MAX_IMPORT_FILES:
        raise ProtocolViolation(f"{label} must be a bounded exact list")
    rows: list[_ByteInventoryEntry] = []
    for item in value:
        row = _exact_keys(
            item,
            required=frozenset({"relative_path", "size_bytes", "sha256"}),
            label=label,
        )
        relative = row["relative_path"]
        size = row["size_bytes"]
        sha256 = row["sha256"]
        if type(relative) is not str or Path(relative).as_posix() != relative:
            raise ProtocolViolation(f"{label} contains a malformed relative path")
        if type(size) is not int or size < 0 or size > MAX_IMPORT_FILE_BYTES:
            raise ProtocolViolation(f"{label} contains a malformed byte size")
        if type(sha256) is not str or not re.fullmatch(r"sha256:[0-9a-f]{64}", sha256):
            raise ProtocolViolation(f"{label} contains a malformed digest")
        rows.append(_ByteInventoryEntry(relative, size, sha256))
    if [row.relative_path for row in rows] != sorted(
        {row.relative_path for row in rows}
    ):
        raise ProtocolViolation(f"{label} is not canonical")
    return tuple(rows)


def _read_import_allowlist_manifest(
    path_text: str,
    bundle_root_text: str,
    harness_root_text: str | None = None,
) -> _WorkerImportInventory:
    path = Path(path_text).resolve()
    pycache_prefix = (path.parent / "pycache-prefix").resolve(strict=False)
    try:
        pycache_info = pycache_prefix.lstat()
    except OSError as exc:
        raise ProtocolViolation("worker pycache prefix is missing") from exc
    if stat.S_ISLNK(pycache_info.st_mode) or not stat.S_ISDIR(pycache_info.st_mode):
        raise ProtocolViolation("worker pycache prefix is not a regular directory")
    harness_root = Path(
        harness_root_text or (path.parent / "harness-snapshot")
    ).resolve()
    path_info = path.lstat()
    if (
        stat.S_ISLNK(path_info.st_mode)
        or not stat.S_ISREG(path_info.st_mode)
        or path_info.st_size > MAX_IMPORT_MANIFEST_BYTES
    ):
        raise ProtocolViolation("import inventory manifest exceeds byte limit")
    with path.open("rb") as stream:
        manifest_raw = stream.read(path_info.st_size + 1)
    if len(manifest_raw) != path_info.st_size:
        raise ProtocolViolation("import inventory manifest changed while reading")
    value = json.loads(manifest_raw.decode("utf-8"))
    obj = _exact_keys(
        value,
        required=frozenset(
            {
                "protocol",
                "mode",
                "runtime_allowed_files",
                "runtime_entries",
                "runtime_absent_paths",
                "runtime_binding_kind",
                "runtime_identity",
                "runtime_allowlist_digest",
                "harness_entries",
                "harness_absent_paths",
                "bootstrap_protocol",
                "bootstrap_sha256",
                "approved_interpreter",
                "harness_bundle_digest",
                "candidate_entries",
                "candidate_absent_paths",
                "model_entries",
                "import_inventory_digest",
                "candidate_bundle_digest",
                "candidate_model_digest",
                "module_origin",
            }
        ),
        label="import byte inventory",
    )
    if obj["protocol"] != IMPORT_INVENTORY_PROTOCOL:
        raise ProtocolViolation("unknown import byte inventory protocol")
    if obj["mode"] not in {"snapshot", "harness-snapshot"}:
        raise ProtocolViolation("unknown import inventory mode")
    if obj["runtime_binding_kind"] != RUNTIME_BINDING_KIND:
        raise ProtocolViolation("unknown runtime binding kind")
    runtime_files = obj["runtime_allowed_files"]
    if (
        type(runtime_files) is not list
        or len(runtime_files) > MAX_IMPORT_ALLOWED_PATHS
        or any(type(item) is not str for item in runtime_files)
        or runtime_files != sorted(set(runtime_files))
    ):
        raise ProtocolViolation("runtime import allowlist is malformed")
    runtime_rows = obj["runtime_entries"]
    if type(runtime_rows) is not list or len(runtime_rows) > MAX_IMPORT_FILES:
        raise ProtocolViolation("runtime byte inventory is malformed")
    parsed_runtime: list[tuple[str, int, str]] = []
    for raw_row in runtime_rows:
        row = _exact_keys(
            raw_row,
            required=frozenset({"path", "size_bytes", "sha256"}),
            label="runtime byte inventory entry",
        )
        path_value = row["path"]
        size_value = row["size_bytes"]
        digest_value = row["sha256"]
        if (
            type(path_value) is not str
            or _normalized_file_path(path_value) != path_value
            or type(size_value) is not int
            or size_value < 0
            or size_value > MAX_IMPORT_FILE_BYTES
            or type(digest_value) is not str
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest_value) is None
        ):
            raise ProtocolViolation("runtime byte inventory entry is malformed")
        parsed_runtime.append((path_value, size_value, digest_value))
    if parsed_runtime != sorted(set(parsed_runtime)):
        raise ProtocolViolation("runtime byte inventory is not canonical")
    if any(not _runtime_path_is_approved(Path(row[0])) for row in parsed_runtime):
        raise ProtocolViolation("runtime byte inventory escaped approved roots")
    if any(Path(row[0]).suffix.lower() == ".pyc" for row in parsed_runtime):
        raise ProtocolViolation("shared runtime bytecode cache entered worker authority")
    runtime_absent = obj["runtime_absent_paths"]
    if (
        type(runtime_absent) is not list
        or len(runtime_absent) > MAX_IMPORT_ALLOWED_PATHS
        or any(type(path) is not str for path in runtime_absent)
        or runtime_absent != sorted(set(runtime_absent))
        or any(
            Path(path).is_absolute()
            or Path(path).as_posix() != path
            or ".." in Path(path).parts
            for path in runtime_absent
        )
    ):
        raise ProtocolViolation("runtime absent-path inventory is malformed")
    if set(runtime_absent) & {path for path, _, _ in parsed_runtime}:
        raise ProtocolViolation("runtime path is both present and absent")
    expected_runtime_absent = tuple(
        sorted(
            _source_cache_logical_identity(Path(path_value), "runtime")
            for path_value, _, _ in parsed_runtime
            if Path(path_value).suffix.lower() == ".py"
        )
    )
    if tuple(runtime_absent) != expected_runtime_absent:
        raise ProtocolViolation("runtime isolated-cache authority is not exact")
    runtime_absent_actual = {
        _source_cache_logical_identity(Path(path_value), "runtime"): (
            _normalized_file_path(
                _source_cache_path_under_prefix(
                    pycache_prefix, Path(path_value), "runtime"
                )
            )
        )
        for path_value, _, _ in parsed_runtime
        if Path(path_value).suffix.lower() == ".py"
    }
    if set(runtime_absent_actual) != set(runtime_absent):
        raise ProtocolViolation("runtime physical-cache mapping is not exact")
    if any(path not in runtime_files for path in runtime_absent):
        raise ProtocolViolation("runtime absent path is outside its allowlist")
    expected_runtime_allowed = {
        path for path, _, _ in parsed_runtime
    } | set(runtime_absent)
    if set(runtime_files) != expected_runtime_allowed:
        raise ProtocolViolation(
            "runtime allowlist is not exactly covered by present/absent inventory"
        )
    runtime_identity = _exact_keys(
        obj["runtime_identity"],
        required=frozenset(
            {"implementation", "cache_tag", "version", "executable_sha256"}
        ),
        label="runtime identity",
    )
    if (
        any(
            type(runtime_identity[key]) is not str
            for key in ("implementation", "cache_tag", "version")
        )
        or type(runtime_identity["executable_sha256"]) is not str
        or re.fullmatch(
            r"sha256:[0-9a-f]{64}", runtime_identity["executable_sha256"]
        )
        is None
    ):
        raise ProtocolViolation("runtime identity is malformed")
    runtime_digest = digest_json(
        {
            "protocol": RUNTIME_IMPORT_CLOSURE_PROTOCOL,
            "binding_kind": RUNTIME_BINDING_KIND,
            "entries": runtime_rows,
            "absent_paths": runtime_absent,
            "allowed_paths": runtime_files,
            "runtime_identity": runtime_identity,
        }
    )
    if runtime_identity != _runtime_identity_wire():
        raise ProtocolViolation("runtime identity mismatch")
    if runtime_digest != obj["runtime_allowlist_digest"]:
        raise ProtocolViolation("runtime import allowlist digest mismatch")

    harness_entries = _parse_inventory_entries(
        obj["harness_entries"], "harness entries"
    )
    if tuple(entry.relative_path for entry in harness_entries) != (
        _HARNESS_SOURCE_RELATIVE_PATHS
    ):
        raise ProtocolViolation("harness source authority is not exact")
    harness_absent = obj["harness_absent_paths"]
    if (
        type(harness_absent) is not list
        or len(harness_absent) > MAX_IMPORT_ALLOWED_PATHS
        or any(type(item) is not str for item in harness_absent)
        or harness_absent != sorted(set(harness_absent))
        or any(
            Path(item).is_absolute()
            or Path(item).as_posix() != item
            or ".." in Path(item).parts
            for item in harness_absent
        )
    ):
        raise ProtocolViolation("harness absent-path inventory is malformed")
    if set(harness_absent) & {
        entry.relative_path for entry in harness_entries
    }:
        raise ProtocolViolation("harness path is both present and absent")
    expected_harness_absent = tuple(
        sorted(
            _source_cache_relative_path(harness_root, relative, "harness")
            for relative in _HARNESS_SOURCE_RELATIVE_PATHS
        )
    )
    if tuple(harness_absent) != expected_harness_absent:
        raise ProtocolViolation("harness absent-cache authority is not exact")
    if obj["bootstrap_protocol"] != BOOTSTRAP_PROTOCOL:
        raise ProtocolViolation("unknown worker bootstrap protocol")
    bootstrap_sha256 = obj["bootstrap_sha256"]
    if (
        type(bootstrap_sha256) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", bootstrap_sha256) is None
    ):
        raise ProtocolViolation("worker bootstrap digest is malformed")
    approved_interpreter = _exact_keys(
        obj["approved_interpreter"],
        required=frozenset(
            {
                "protocol",
                "resolved_path",
                "size_bytes",
                "sha256",
                "implementation",
                "cache_tag",
                "version",
            }
        ),
        label="approved interpreter",
    )
    if approved_interpreter != _approved_interpreter_wire():
        raise ProtocolViolation("approved interpreter identity mismatch")
    harness_bundle_digest = digest_json(
        {
            "protocol": HARNESS_BUNDLE_PROTOCOL,
            "bootstrap_protocol": obj["bootstrap_protocol"],
            "bootstrap_sha256": bootstrap_sha256,
            "approved_interpreter": approved_interpreter,
            "entries": obj["harness_entries"],
            "absent_paths": harness_absent,
        }
    )
    if harness_bundle_digest != obj["harness_bundle_digest"]:
        raise ProtocolViolation("harness bundle digest mismatch")

    entries = _parse_inventory_entries(obj["candidate_entries"], "candidate entries")
    if any(
        Path(entry.relative_path).suffix.lower() not in _IMPORT_FILE_SUFFIXES
        for entry in entries
    ):
        raise ProtocolViolation("candidate entries contain a non-import artifact")
    candidate_absent = obj["candidate_absent_paths"]
    if (
        type(candidate_absent) is not list
        or len(candidate_absent) > MAX_IMPORT_ALLOWED_PATHS
        or any(type(path) is not str for path in candidate_absent)
        or candidate_absent != sorted(set(candidate_absent))
        or any(
            Path(path).is_absolute()
            or Path(path).as_posix() != path
            or ".." in Path(path).parts
            for path in candidate_absent
        )
    ):
        raise ProtocolViolation("candidate absent-path inventory is malformed")
    if set(candidate_absent) & {row.relative_path for row in entries}:
        raise ProtocolViolation("candidate path is both present and absent")
    model_entries = _parse_inventory_entries(obj["model_entries"], "model entries")
    bundle_root = Path(bundle_root_text).resolve()
    candidate_entry_paths = {entry.relative_path for entry in entries}
    expected_candidate_absent = tuple(
        sorted(
            cache_relative
            for cache_relative in (
                _source_cache_relative_path(
                    bundle_root, entry.relative_path, "candidate"
                )
                for entry in entries
                if entry.relative_path.endswith(".py")
            )
            if cache_relative not in candidate_entry_paths
        )
    )
    if tuple(candidate_absent) != expected_candidate_absent:
        raise ProtocolViolation("candidate absent-cache authority is not exact")
    harness_absent_actual = {
        _source_cache_relative_path(
            harness_root, entry.relative_path, "harness"
        ): _normalized_file_path(
            _source_cache_path_under_prefix(
                pycache_prefix,
                harness_root / Path(entry.relative_path),
                "harness",
            )
        )
        for entry in harness_entries
        if entry.relative_path.endswith(".py")
    }
    candidate_absent_actual = {
        _source_cache_relative_path(
            bundle_root, entry.relative_path, "candidate"
        ): _normalized_file_path(
            _source_cache_path_under_prefix(
                pycache_prefix,
                bundle_root / Path(entry.relative_path),
                "candidate",
            )
        )
        for entry in entries
        if entry.relative_path.endswith(".py")
    }
    if set(harness_absent_actual) != set(harness_absent):
        raise ProtocolViolation("harness isolated-cache authority is not exact")
    if set(candidate_absent_actual) != set(candidate_absent):
        raise ProtocolViolation("candidate isolated-cache authority is not exact")
    declared_paths: dict[str, tuple[int, str]] = {
        path: (size, sha256) for path, size, sha256 in parsed_runtime
    }
    interpreter_path = str(approved_interpreter["resolved_path"])
    if interpreter_path in declared_paths:
        raise ProtocolViolation("runtime/interpreter byte authorities overlap")
    declared_paths[interpreter_path] = (
        int(approved_interpreter["size_bytes"]),
        str(approved_interpreter["sha256"]),
    )
    for entry in harness_entries:
        normalized = _normalized_file_path(harness_root / entry.relative_path)
        if normalized in declared_paths:
            raise ProtocolViolation("runtime/harness byte authorities overlap")
        declared_paths[normalized] = (entry.size_bytes, entry.sha256)
    for entry in (*entries, *model_entries):
        normalized = _normalized_file_path(bundle_root / entry.relative_path)
        identity = (entry.size_bytes, entry.sha256)
        if normalized in declared_paths:
            raise ProtocolViolation("candidate byte authorities overlap")
        declared_paths[normalized] = identity
    absent_authority_paths: set[str] = set()
    for normalized in (
        *(runtime_absent_actual[identity] for identity in runtime_absent),
        *(harness_absent_actual[relative] for relative in harness_absent),
        *(candidate_absent_actual[relative] for relative in candidate_absent),
    ):
        if normalized in declared_paths or normalized in absent_authority_paths:
            raise ProtocolViolation("present/absent byte authorities overlap")
        absent_authority_paths.add(normalized)
    declared_rows = len(declared_paths)
    declared_bytes = sum(size for size, _ in declared_paths.values())
    if declared_rows > MAX_IMPORT_FILES:
        raise ProtocolViolation("combined import inventory exceeds file limit")
    if declared_bytes > MAX_IMPORT_TOTAL_BYTES:
        raise ProtocolViolation("combined import inventory exceeds byte limit")
    if any(path not in runtime_files for path, _, _ in parsed_runtime):
        raise ProtocolViolation("runtime byte inventory is outside its allowlist")
    if (
        _byte_inventory_digest(
            "candidate-code", entries, tuple(candidate_absent)
        )
        != obj["candidate_bundle_digest"]
    ):
        raise ProtocolViolation("candidate bundle digest mismatch")
    if _byte_inventory_digest("candidate-model", model_entries) != obj["candidate_model_digest"]:
        raise ProtocolViolation("candidate model digest mismatch")
    module_origin = obj["module_origin"]
    if type(module_origin) is not str or module_origin not in {
        row.relative_path for row in entries
    }:
        raise ProtocolViolation("module origin is not inventoried")
    expected_import_digest = digest_json(
        {
            "protocol": IMPORT_INVENTORY_PROTOCOL,
            "mode": obj["mode"],
            "candidate_bundle_digest": obj["candidate_bundle_digest"],
            "candidate_model_digest": obj["candidate_model_digest"],
            "harness_bundle_digest": obj["harness_bundle_digest"],
            "runtime_allowlist_digest": obj["runtime_allowlist_digest"],
            "module_origin": module_origin,
        }
    )
    if expected_import_digest != obj["import_inventory_digest"]:
        raise ProtocolViolation("import inventory digest mismatch")

    if (obj["mode"] == "harness-snapshot") != (bundle_root == harness_root):
        raise ProtocolViolation("candidate/harness snapshot mode-root mismatch")
    allowed = {path for path, _, _ in parsed_runtime}
    allowed.update(runtime_absent_actual.values())
    allowed.add(interpreter_path)
    for entry in harness_entries:
        target = harness_root / Path(entry.relative_path)
        try:
            target.resolve().relative_to(harness_root)
        except ValueError as exc:
            raise ProtocolViolation("harness path escaped worker snapshot") from exc
        allowed.add(_normalized_file_path(target))
    for relative in harness_absent:
        allowed.add(harness_absent_actual[relative])
    for entry in (*entries, *model_entries):
        target = bundle_root / Path(entry.relative_path)
        try:
            target.resolve().relative_to(bundle_root)
        except ValueError as exc:
            raise ProtocolViolation("inventoried path escaped worker bundle") from exc
        allowed.add(_normalized_file_path(target))
    for relative in candidate_absent:
        allowed.add(candidate_absent_actual[relative])
    expected_allowed = set(declared_paths) | absent_authority_paths
    if allowed != expected_allowed:
        raise ProtocolViolation(
            "combined allowlist is not exactly covered by byte authorities"
        )
    if len(allowed) > MAX_IMPORT_ALLOWED_PATHS:
        raise ProtocolViolation("combined import allowlist exceeds path limit")
    return _WorkerImportInventory(
        allowed_files=frozenset(allowed),
        runtime_entries=tuple(parsed_runtime),
        runtime_absent_paths=tuple(
            runtime_absent_actual[identity] for identity in runtime_absent
        ),
        pycache_prefix=pycache_prefix,
        harness_root=harness_root,
        harness_entries=harness_entries,
        harness_absent_paths=tuple(harness_absent),
        bootstrap_kind="unified",
        bootstrap_sha256=bootstrap_sha256,
        approved_interpreter=approved_interpreter,
        mode=obj["mode"],
        entries=entries,
        candidate_absent_paths=tuple(candidate_absent),
        model_entries=model_entries,
        import_inventory_digest=obj["import_inventory_digest"],
        harness_bundle_digest=obj["harness_bundle_digest"],
        candidate_bundle_digest=obj["candidate_bundle_digest"],
        candidate_model_digest=obj["candidate_model_digest"],
        module_origin=module_origin,
    )


def _verify_worker_inventory_bytes(
    inventory: _WorkerImportInventory,
    bundle_root: Path,
    *,
    deadline: float | None = None,
) -> None:
    for entry in (*inventory.entries, *inventory.model_entries):
        if deadline is not None:
            _check_preparation_deadline(deadline)
        path = bundle_root / Path(entry.relative_path)
        if path.is_symlink() or not path.is_file():
            raise ProtocolViolation("inventoried candidate file is missing or non-regular")
        raw = path.read_bytes()
        if deadline is not None:
            _check_preparation_deadline(deadline)
        if len(raw) != entry.size_bytes or digest_bytes(raw) != entry.sha256:
            raise ProtocolViolation("inventoried candidate bytes changed before execution")
    for relative in inventory.candidate_absent_paths:
        if deadline is not None:
            _check_preparation_deadline(deadline)
        source_relative = next(
            (
                entry.relative_path
                for entry in inventory.entries
                if entry.relative_path.endswith(".py")
                and _source_cache_relative_path(
                    bundle_root, entry.relative_path, "candidate"
                )
                == relative
            ),
            None,
        )
        if source_relative is None:
            raise ProtocolViolation("candidate cache authority lost its source")
        cache_path = _source_cache_path_under_prefix(
            inventory.pycache_prefix,
            bundle_root / Path(source_relative),
            "candidate",
        )
        if os.path.lexists(os.fspath(cache_path)):
            raise ProtocolViolation("bound-absent candidate cache appeared before execution")


def _verify_worker_harness_inventory_bytes(
    inventory: _WorkerImportInventory,
    *,
    deadline: float | None = None,
) -> None:
    for entry in inventory.harness_entries:
        if deadline is not None:
            _check_preparation_deadline(deadline)
        path = inventory.harness_root / Path(entry.relative_path)
        if path.is_symlink() or not path.is_file():
            raise ProtocolViolation("inventoried harness source is missing or non-regular")
        raw = path.read_bytes()
        if deadline is not None:
            _check_preparation_deadline(deadline)
        if len(raw) != entry.size_bytes or digest_bytes(raw) != entry.sha256:
            raise ProtocolViolation("inventoried harness bytes changed before execution")
    for relative in inventory.harness_absent_paths:
        if deadline is not None:
            _check_preparation_deadline(deadline)
        source_relative = next(
            (
                entry.relative_path
                for entry in inventory.harness_entries
                if _source_cache_relative_path(
                    inventory.harness_root, entry.relative_path, "harness"
                )
                == relative
            ),
            None,
        )
        if source_relative is None:
            raise ProtocolViolation("harness cache authority lost its source")
        cache_path = _source_cache_path_under_prefix(
            inventory.pycache_prefix,
            inventory.harness_root / Path(source_relative),
            "harness",
        )
        if os.path.lexists(os.fspath(cache_path)):
            raise ProtocolViolation("bound-absent harness cache appeared before execution")
    if deadline is not None:
        _check_preparation_deadline(deadline)
    if inventory.approved_interpreter != _approved_interpreter_wire():
        raise ProtocolViolation("approved interpreter bytes changed before execution")
    if deadline is not None:
        _check_preparation_deadline(deadline)


def _verify_worker_runtime_inventory_bytes(
    inventory: _WorkerImportInventory,
    *,
    deadline: float | None = None,
) -> None:
    total_bytes = 0
    for path_text, size_bytes, sha256 in inventory.runtime_entries:
        if deadline is not None:
            _check_preparation_deadline(deadline)
        path = Path(path_text)
        if path.is_symlink() or not path.is_file():
            raise ProtocolViolation("inventoried runtime file is missing or non-regular")
        if _normalized_file_path(path) != path_text:
            raise ProtocolViolation("inventoried runtime path is not canonical")
        total_bytes += size_bytes
        if total_bytes > MAX_IMPORT_TOTAL_BYTES:
            raise ProtocolViolation("runtime byte verification exceeds total limit")
        raw = path.read_bytes()
        if deadline is not None:
            _check_preparation_deadline(deadline)
        if len(raw) != size_bytes or digest_bytes(raw) != sha256:
            raise ProtocolViolation("inventoried runtime bytes changed before execution")
    for path_text in inventory.runtime_absent_paths:
        if deadline is not None:
            _check_preparation_deadline(deadline)
        if os.path.lexists(path_text):
            raise ProtocolViolation("bound-absent runtime cache appeared before execution")


def _parent_verify_prepared_inventory(
    prepared: _PreparedImportInventory,
    *,
    deadline: float,
) -> None:
    """Independently rehash every child authority before temp cleanup."""

    _check_preparation_deadline(deadline)
    manifest_info = prepared.manifest_path.lstat()
    if (
        stat.S_ISLNK(manifest_info.st_mode)
        or not stat.S_ISREG(manifest_info.st_mode)
        or manifest_info.st_size > MAX_IMPORT_MANIFEST_BYTES
    ):
        raise ProtocolViolation("prepared child manifest is non-regular or oversized")
    with prepared.manifest_path.open("rb") as stream:
        raw_manifest = stream.read(manifest_info.st_size + 1)
    if len(raw_manifest) != manifest_info.st_size:
        raise ProtocolViolation("prepared child manifest changed while reading")
    _check_preparation_deadline(deadline)
    if digest_bytes(raw_manifest) != prepared.manifest_sha256:
        raise ProtocolViolation("prepared child manifest bytes changed")
    inventory = _read_import_allowlist_manifest(
        str(prepared.manifest_path),
        str(prepared.worker_bundle_root),
        str(prepared.worker_harness_root),
    )
    _check_preparation_deadline(deadline)
    if (
        inventory.import_inventory_digest != prepared.import_inventory_digest
        or inventory.harness_bundle_digest != prepared.harness_bundle_digest
        or inventory.candidate_bundle_digest != prepared.candidate_bundle_digest
        or inventory.candidate_model_digest != prepared.candidate_model_digest
        or inventory.module_origin != prepared.module_origin
        or inventory.bootstrap_sha256 != prepared.bootstrap_sha256
    ):
        raise ProtocolViolation("prepared child authority binding changed")
    _verify_worker_harness_inventory_bytes(inventory, deadline=deadline)
    _verify_worker_runtime_inventory_bytes(inventory, deadline=deadline)
    _verify_worker_inventory_bytes(
        inventory, prepared.worker_bundle_root, deadline=deadline
    )


def _combined_postverify_failure(
    primary: BaseException | None,
    postverify: Exception,
    *,
    label: str,
    binding_fields: dict[str, str],
) -> WorkerInvocationError:
    """Retain a primary failure when mandatory post-verification also fails."""

    primary_text = (
        f"{type(primary).__name__}: {primary}"
        if primary is not None
        else "no earlier execution failure"
    )
    message = (
        f"{primary_text}; {label}: "
        f"{type(postverify).__name__}: {postverify}"
    )
    if isinstance(primary, WorkerInvocationError):
        return WorkerInvocationError(
            message,
            failure_code="UCM-E003-HARNESS_INCOMPLETE",
            audit_events=primary.audit_events,
            audit_overflow=primary.audit_overflow,
            captured_stdout=primary.captured_stdout,
            captured_stderr=primary.captured_stderr,
            returncode=primary.returncode,
            failure_origin="harness",
            **binding_fields,
        )
    return WorkerInvocationError(
        message,
        failure_code="UCM-E003-HARNESS_INCOMPLETE",
        failure_origin="harness",
        **binding_fields,
    )


def _candidate_import_read_allowlist(bundle_root_text: str) -> tuple[str, ...]:
    """Compatibility helper returning a bounded current path allowlist."""

    deadline = time.monotonic() + 60.0
    _, _, runtime, _, _ = _runtime_import_read_allowlist(deadline=deadline)
    allowed = set(runtime)
    root = Path(bundle_root_text).resolve()
    for path in _iter_import_files(root, deadline=deadline):
        allowed.add(_normalized_file_path(path))
    return tuple(sorted(allowed))


_UNIFIED_WORKER_BOOTSTRAP = r"""
import hashlib, json, os, stat, sys
try:
    if len(sys.argv) != 11 or sys.argv[6] not in {"fresh", "sequential"}:
        raise ValueError("bad bootstrap argv")
    harness_root = os.path.realpath(sys.argv[1])
    manifest_path = os.path.realpath(sys.argv[5])
    pycache_prefix = os.path.realpath(
        os.path.join(os.path.dirname(manifest_path), "pycache-prefix")
    )
    if (sys.pycache_prefix is None or
            os.path.realpath(sys.pycache_prefix) != pycache_prefix):
        raise ValueError("worker pycache prefix mismatch")
    with open(manifest_path, "rb") as stream:
        manifest_raw = stream.read(16 * 1024 * 1024 + 1)
    if len(manifest_raw) > 16 * 1024 * 1024:
        raise ValueError("oversized manifest")
    if "sha256:" + hashlib.sha256(manifest_raw).hexdigest() != sys.argv[8]:
        raise ValueError("manifest byte binding mismatch")
    manifest = json.loads(manifest_raw.decode("utf-8"))
    entries = manifest["harness_entries"]
    absent_paths = manifest["harness_absent_paths"]
    if not isinstance(entries, list) or not isinstance(absent_paths, list):
        raise ValueError("bad harness inventory")
    if len(entries) > 20000 or len(absent_paths) > 40000:
        raise ValueError("oversized harness inventory")
    if entries != sorted(entries, key=lambda row: row["relative_path"]):
        raise ValueError("noncanonical harness inventory")
    expected_sources = [
        "prototype/__init__.py",
        "prototype/unified_map/__init__.py",
        "prototype/unified_map/candidate_protocol.py",
        "prototype/unified_map/canonical.py",
        "prototype/unified_map/schema.py",
        "prototype/unified_map/state.py",
    ]
    if [row.get("relative_path") for row in entries] != expected_sources:
        raise ValueError("harness source authority is not exact")
    seen = set()
    total_bytes = 0
    for row in entries:
        if (type(row) is not dict or
                set(row) != {"relative_path", "size_bytes", "sha256"}):
            raise ValueError("bad harness row")
        relative = row["relative_path"]
        size_bytes = row["size_bytes"]
        sha256 = row["sha256"]
        if (not isinstance(relative, str) or not relative.endswith(".py") or
                relative.startswith(("/", "\\")) or "\\" in relative or
                any(part in {"", ".", ".."} for part in relative.split("/")) or
                relative in seen):
            raise ValueError("bad harness path")
        if (type(size_bytes) is not int or size_bytes < 0 or
                size_bytes > 256 * 1024 * 1024 or type(sha256) is not str or
                len(sha256) != 71 or not sha256.startswith("sha256:") or
                any(ch not in "0123456789abcdef" for ch in sha256[7:])):
            raise ValueError("bad harness byte identity")
        total_bytes += size_bytes
        if total_bytes > 512 * 1024 * 1024:
            raise ValueError("oversized harness bytes")
        seen.add(relative)
        target = os.path.realpath(os.path.join(harness_root, *relative.split("/")))
        if os.path.commonpath((harness_root, target)) != harness_root:
            raise ValueError("escaped harness path")
        info = os.lstat(target)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise ValueError("nonregular harness source")
        with open(target, "rb") as stream:
            raw = stream.read(size_bytes + 1)
        if (len(raw) != size_bytes or
                "sha256:" + hashlib.sha256(raw).hexdigest() != sha256):
            raise ValueError("harness source mismatch")
    source_by_expected_absent = {}
    for relative in expected_sources:
        parent, filename = relative.rsplit("/", 1)
        cache_relative = (
            parent + "/__pycache__/" + filename[:-3] + "." +
            (sys.implementation.cache_tag or "") + ".pyc"
        )
        source_by_expected_absent[cache_relative] = relative
    expected_absent = sorted(source_by_expected_absent)
    if absent_paths != expected_absent:
        raise ValueError("noncanonical absent paths")
    for relative in absent_paths:
        source_relative = source_by_expected_absent[relative]
        if (not isinstance(relative, str) or relative.startswith(("/", "\\")) or
                "\\" in relative or
                any(part in {"", ".", ".."} for part in relative.split("/"))):
            raise ValueError("bad absent path")
        source = os.path.realpath(
            os.path.join(harness_root, *source_relative.split("/"))
        )
        source_head, source_tail = os.path.split(source)
        base, separator, rest = source_tail.rpartition(".")
        cache_name = (base if base else rest) + separator + (
            sys.implementation.cache_tag or ""
        )
        if sys.flags.optimize:
            cache_name += ".opt-" + str(sys.flags.optimize)
        cache_name += ".pyc"
        _, source_head = os.path.splitdrive(source_head)
        target = os.path.realpath(os.path.join(
            pycache_prefix,
            source_head.lstrip(os.sep + (os.altsep or "")),
            cache_name,
        ))
        if (os.path.commonpath((pycache_prefix, target)) != pycache_prefix or
                os.path.lexists(target)):
            raise ValueError("harness absent-path mismatch")
    executable = os.path.realpath(sys.executable)
    executable_info = os.stat(executable)
    if executable_info.st_size > 256 * 1024 * 1024:
        raise ValueError("oversized interpreter")
    with open(executable, "rb") as stream:
        executable_raw = stream.read(executable_info.st_size + 1)
    if len(executable_raw) != executable_info.st_size:
        raise ValueError("interpreter changed while reading")
    interpreter = {
        "protocol": "ucm-python-worker-bootstrap/1",
        "resolved_path": os.path.normcase(executable),
        "size_bytes": executable_info.st_size,
        "sha256": "sha256:" + hashlib.sha256(executable_raw).hexdigest(),
        "implementation": sys.implementation.name,
        "cache_tag": sys.implementation.cache_tag or "",
        "version": sys.version,
    }
    if manifest["approved_interpreter"] != interpreter:
        raise ValueError("interpreter mismatch")
    harness_wire = {
        "protocol": "ucm-python-harness-source-snapshot/1",
        "bootstrap_protocol": manifest["bootstrap_protocol"],
        "bootstrap_sha256": manifest["bootstrap_sha256"],
        "approved_interpreter": interpreter,
        "entries": entries,
        "absent_paths": absent_paths,
    }
    canonical = (json.dumps(harness_wire, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    actual_digest = "sha256:" + hashlib.sha256(canonical).hexdigest()
    if (manifest["bootstrap_protocol"] != "ucm-python-worker-bootstrap/1" or
            manifest["harness_bundle_digest"] != actual_digest or
            sys.argv[7] != actual_digest):
        raise ValueError("harness bundle mismatch")
except BaseException:
    raise SystemExit(90)
if harness_root not in sys.path:
    sys.path.insert(0, harness_root)
import prototype.unified_map.candidate_protocol as _ucm_candidate_protocol
if (_ucm_candidate_protocol.__cached__ is None or
        os.path.commonpath((
            pycache_prefix,
            os.path.realpath(_ucm_candidate_protocol.__cached__),
        )) != pycache_prefix):
    raise SystemExit(90)
_session_worker_main = _ucm_candidate_protocol._session_worker_main
_worker_main = _ucm_candidate_protocol._worker_main
if sys.argv[6] == "fresh":
    raise SystemExit(_worker_main(
        sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5],
        sys.argv[9], sys.argv[10]
    ))
raise SystemExit(_session_worker_main(
    sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5],
    sys.argv[9], sys.argv[10]
))
"""

_WORKER_BOOTSTRAP = _UNIFIED_WORKER_BOOTSTRAP


class FreshProcessExecutor:
    """Invoke every operation in a newly spawned, minimally isolated worker."""

    def __init__(
        self,
        entrypoint: CandidateEntrypoint,
        *,
        timeout_seconds: float = 20.0,
        python_executable: str | None = None,
    ) -> None:
        if type(entrypoint) is not CandidateEntrypoint:
            raise ProtocolViolation("entrypoint must be CandidateEntrypoint")
        self.entrypoint = entrypoint
        self.timeout_seconds = _positive_finite_seconds(
            timeout_seconds, "timeout_seconds"
        )
        self.python_executable = _approved_python_executable(python_executable)

    @staticmethod
    def _worker_env(temp_root: Path) -> dict[str, str]:
        env = {
            "PYTHONHASHSEED": "0",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "UCM_WORKER": "1",
            "TEMP": str(temp_root),
            "TMP": str(temp_root),
        }
        # CPython and DLL loading on Windows may require these OS variables.
        for key in ("SystemRoot", "WINDIR"):
            if key in os.environ:
                env[key] = os.environ[key]
        return env

    def invoke(self, request: CandidateRequest) -> InvocationOutcome:
        if not isinstance(
            request,
            (InitializeRequest, UpdateRequest, DiagnoseRequest, RolloutRequest),
        ):
            raise ProtocolViolation("unknown candidate request type")
        timeout_seconds = _positive_finite_seconds(
            self.timeout_seconds, "timeout_seconds"
        )
        python_executable = _approved_python_executable(self.python_executable)
        deadline = time.monotonic() + timeout_seconds
        worker_deadline = _worker_subdeadline(deadline, timeout_seconds)
        request_bytes = canonical_json_bytes(request.to_wire())
        if len(request_bytes) > MAX_SESSION_FRAME_BYTES:
            raise ProtocolViolation("fresh candidate request frame is too large")
        prepared_bindings: dict[str, str] = {}
        prepared: _PreparedImportInventory | None = None
        try:
            with tempfile.TemporaryDirectory(prefix="ucm-fresh-worker-") as raw_temp:
                temp_root = Path(raw_temp).resolve()
                bootstrap_source = _UNIFIED_WORKER_BOOTSTRAP
                prepared = _write_import_allowlist_manifest(
                    temp_root,
                    self.entrypoint,
                    deadline=worker_deadline,
                    bootstrap_source=bootstrap_source,
                )
                prepared_bindings = {
                    "import_inventory_digest": prepared.import_inventory_digest,
                    "harness_bundle_digest": prepared.harness_bundle_digest,
                    "candidate_bundle_digest": prepared.candidate_bundle_digest,
                    "candidate_model_digest": prepared.candidate_model_digest,
                    "module_origin": prepared.module_origin,
                }
                command = [
                    python_executable,
                    "-I",
                    "-S",
                    "-B",
                    "-X",
                    f"pycache_prefix={temp_root / 'pycache-prefix'}",
                    "-c",
                    bootstrap_source,
                    str(prepared.worker_harness_root),
                    str(prepared.worker_bundle_root),
                    self.entrypoint.module,
                    self.entrypoint.qualname,
                    str(prepared.manifest_path),
                    "fresh",
                    prepared.harness_bundle_digest,
                    prepared.manifest_sha256,
                    str(temp_root / "harness-prepared.marker"),
                    os.urandom(16).hex(),
                ]
                if digest_bytes(command[7].encode("utf-8")) != prepared.bootstrap_sha256:
                    raise ProtocolViolation("fresh bootstrap source binding drifted")
                prepared_marker_path = Path(command[-2])
                prepared_nonce = command[-1]
                try:
                    completed = _run_fresh_process_bounded(
                        command,
                        request_bytes=request_bytes,
                        cwd=temp_root,
                        env=self._worker_env(temp_root),
                        timeout_seconds=_session_remaining(worker_deadline),
                        binding_fields=prepared_bindings,
                        prepared_marker_path=prepared_marker_path,
                        prepared_nonce=prepared_nonce,
                    )
                finally:
                    primary_error = sys.exc_info()[1]
                    try:
                        _parent_verify_prepared_inventory(
                            prepared,
                            deadline=deadline,
                        )
                    except Exception as postverify_error:
                        raise _combined_postverify_failure(
                            primary_error,
                            postverify_error,
                            label="fresh parent post-verification failed",
                            binding_fields=prepared_bindings,
                        ) from postverify_error
        except WorkerInvocationError:
            raise
        except (_PreparationTimeout, TimeoutError) as exc:
            raise WorkerInvocationError(
                "fresh candidate preparation timed out",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                failure_origin="harness",
                **prepared_bindings,
            ) from exc
        except Exception as exc:
            raise WorkerInvocationError(
                "fresh candidate preparation failed",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                failure_origin="harness",
                **prepared_bindings,
            ) from exc
        stderr_text = _bounded_evidence_text(completed.stderr)

        if completed.stdout_overflow:
            raise WorkerInvocationError(
                "fresh candidate worker emitted an oversized protocol frame",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=_bounded_evidence_text(completed.stdout),
                captured_stderr=stderr_text,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            )
        if completed.stderr_overflow:
            raise WorkerInvocationError(
                "fresh candidate worker emitted oversized external stderr",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=_bounded_evidence_text(completed.stdout),
                captured_stderr=stderr_text,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            )
        try:
            worker = _parse_canonical_fresh_frame(completed.stdout)
        except ProtocolViolation as exc:
            raise WorkerInvocationError(
                "fresh candidate worker returned a malformed envelope",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=_bounded_evidence_text(completed.stdout),
                captured_stderr=stderr_text,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            ) from exc
        success_fields = frozenset(
            {
                "protocol",
                "ok",
                "failure_origin",
                "response",
                "audit_events",
                "audit_overflow",
                "captured_stdout",
                "captured_stderr",
                "worker_pid",
                "worker_cwd_isolated",
                "import_inventory_digest",
                "harness_bundle_digest",
                "candidate_bundle_digest",
                "candidate_model_digest",
                "module_origin",
            }
        )
        error_fields = frozenset(
            {
                "protocol",
                "ok",
                "failure_origin",
                "error",
                "audit_events",
                "audit_overflow",
                "captured_stdout",
                "captured_stderr",
                "worker_pid",
                "import_inventory_digest",
                "harness_bundle_digest",
                "candidate_bundle_digest",
                "candidate_model_digest",
                "module_origin",
            }
        )
        try:
            worker = _exact_keys(
                worker,
                required=success_fields if worker.get("ok") is True else error_fields,
                label="fresh worker envelope",
            )
        except ProtocolViolation as exc:
            raise WorkerInvocationError(
                "fresh candidate worker returned extra or missing envelope fields",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=_bounded_evidence_text(completed.stdout),
                captured_stderr=stderr_text,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            ) from exc
        try:
            worker_stdout = _validated_capture_field(
                worker.get("captured_stdout"), label="fresh captured_stdout"
            )
            worker_stderr = _validated_capture_field(
                worker.get("captured_stderr"), label="fresh captured_stderr"
            )
        except ProtocolViolation as exc:
            raise WorkerInvocationError(
                "fresh candidate worker returned malformed capture evidence",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=_bounded_evidence_text(completed.stdout),
                captured_stderr=stderr_text,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            ) from exc
        combined_stderr = _merge_bounded_evidence(worker_stderr, stderr_text)
        audit_events_raw = worker.get("audit_events", [])
        audit_overflow = worker.get("audit_overflow", False)
        if (
            type(audit_events_raw) is not list
            or len(audit_events_raw) > MAX_AUDIT_EVENTS
            or any(type(row) is not dict for row in audit_events_raw)
            or type(audit_overflow) is not bool
        ):
            raise WorkerInvocationError(
                "fresh candidate worker returned malformed audit evidence",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=worker_stdout,
                captured_stderr=combined_stderr,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            )
        audit_events = tuple(audit_events_raw)
        binding_names = (
            "import_inventory_digest",
            "harness_bundle_digest",
            "candidate_bundle_digest",
            "candidate_model_digest",
            "module_origin",
        )
        worker_bindings = {name: worker.get(name) for name in binding_names}
        expected_bindings = prepared_bindings
        is_error = worker["ok"] is False or completed.returncode != 0
        bindings_are_strings = all(
            type(value) is str for value in worker_bindings.values()
        )
        bindings_are_empty = all(value is None for value in worker_bindings.values())
        if not bindings_are_strings and not (
            is_error
            and worker.get("failure_origin") == "harness"
            and bindings_are_empty
        ):
            raise WorkerInvocationError(
                "fresh worker returned malformed byte-inventory binding",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=worker_stdout,
                captured_stderr=combined_stderr,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            )
        if bindings_are_strings and worker_bindings != expected_bindings:
            raise WorkerInvocationError(
                "fresh worker byte-inventory binding mismatch",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=worker_stdout,
                captured_stderr=combined_stderr,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            )
        if is_error or worker.get("ok") is not True:
            candidate_boundary = (
                completed.prepared_attested and completed.request_fully_sent
            )
            declared_origin = worker.get("failure_origin")
            if declared_origin not in {"candidate", "harness"} or (
                declared_origin == "candidate" and not candidate_boundary
            ):
                raise WorkerInvocationError(
                    "fresh worker failure origin/boundary mismatch",
                    failure_code="UCM-E003-HARNESS_INCOMPLETE",
                    captured_stdout=worker_stdout,
                    captured_stderr=combined_stderr,
                    returncode=completed.returncode,
                    failure_origin="harness",
                    **prepared_bindings,
                )
            try:
                error = _exact_keys(
                    worker.get("error"),
                    required=frozenset({"failure_code", "type", "message"}),
                    label="fresh worker error",
                )
            except ProtocolViolation as exc:
                raise WorkerInvocationError(
                    "fresh candidate worker returned a malformed error object",
                    failure_code="UCM-E003-HARNESS_INCOMPLETE",
                    captured_stdout=worker_stdout,
                    captured_stderr=combined_stderr,
                    returncode=completed.returncode,
                    failure_origin="harness",
                    **prepared_bindings,
                ) from exc
            try:
                _validate_failure_origin_code(
                    declared_origin, error.get("failure_code")
                )
            except ProtocolViolation as exc:
                raise WorkerInvocationError(
                    "fresh worker returned an invalid failure origin/code pair",
                    failure_code="UCM-E003-HARNESS_INCOMPLETE",
                    captured_stdout=worker_stdout,
                    captured_stderr=combined_stderr,
                    returncode=completed.returncode,
                    failure_origin="harness",
                    **prepared_bindings,
                ) from exc
            raise WorkerInvocationError(
                str(error.get("message", "fresh candidate worker failed")),
                failure_code=str(
                    error.get("failure_code", "UCM-F008-STATE_NOT_CLOSED")
                ),
                audit_events=audit_events,
                audit_overflow=audit_overflow,
                captured_stdout=worker_stdout,
                captured_stderr=combined_stderr,
                returncode=completed.returncode,
                failure_origin=(
                    worker.get("failure_origin")
                    if worker.get("failure_origin") in {"candidate", "harness"}
                    else "harness"
                ),
                **(
                    worker_bindings if bindings_are_strings else prepared_bindings
                ),
            )
        if worker["failure_origin"] is not None:
            raise WorkerInvocationError(
                "successful fresh worker declared a failure origin",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=worker_stdout,
                captured_stderr=combined_stderr,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            )
        if not completed.prepared_attested or not completed.request_fully_sent:
            raise WorkerInvocationError(
                "successful fresh worker lacked the prepared/request handshake",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=worker_stdout,
                captured_stderr=combined_stderr,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            )
        if worker["worker_cwd_isolated"] is not True:
            raise WorkerInvocationError(
                "fresh worker did not retain its isolated working directory",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=worker_stdout,
                captured_stderr=combined_stderr,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            )
        try:
            worker_pid = _positive_worker_pid(
                worker.get("worker_pid"), "fresh worker_pid"
            )
        except ProtocolViolation as exc:
            raise WorkerInvocationError(
                "fresh worker returned a malformed worker_pid",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=worker_stdout,
                captured_stderr=combined_stderr,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            ) from exc
        if audit_events or audit_overflow:
            raise WorkerInvocationError(
                "fresh candidate worker caught a denied audited capability",
                failure_code=_classify_denied_audit(list(audit_events), request),
                audit_events=audit_events,
                audit_overflow=audit_overflow,
                captured_stdout=worker_stdout,
                captured_stderr=combined_stderr,
                returncode=completed.returncode,
                failure_origin="candidate",
                **worker_bindings,
            )
        response = response_from_wire(worker.get("response"))
        _validate_response_for_request(request, response)
        outcome = InvocationOutcome(
            response=response,
            request_digest=digest_json(request.to_wire()),
            response_digest=digest_json(response.to_wire()),
            isolation="fresh-python-process-audit-v2",
            audit_events=audit_events,
            audit_overflow=audit_overflow,
            captured_stdout=worker_stdout,
            captured_stderr=combined_stderr,
            worker_pid=worker_pid,
            **worker_bindings,
        )
        try:
            _check_fresh_completion_deadline(deadline)
        except _PreparationTimeout as exc:
            raise WorkerInvocationError(
                "fresh response validation exceeded the overall deadline",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=worker_stdout,
                captured_stderr=combined_stderr,
                returncode=completed.returncode,
                failure_origin="harness",
                **prepared_bindings,
            ) from exc
        return outcome


_SESSION_WORKER_BOOTSTRAP = _UNIFIED_WORKER_BOOTSTRAP


class _PipeSignal(str, Enum):
    EOF = "eof"
    OVERFLOW = "overflow"


_PIPE_EOF = _PipeSignal.EOF
_PIPE_OVERFLOW = _PipeSignal.OVERFLOW


class _BoundedByteAccumulator:
    """Thread-safe byte evidence accumulator with bounded retained memory."""

    def __init__(self, limit: int) -> None:
        if type(limit) is not int or limit <= 0:
            raise ValueError("capture limit must be a positive exact integer")
        self._limit = limit
        self._value = bytearray()
        self._overflow = False
        self._lock = threading.Lock()

    @property
    def limit(self) -> int:
        return self._limit

    def append(self, chunk: bytes) -> None:
        if type(chunk) is not bytes:
            raise TypeError("captured bytes must be exact bytes")
        with self._lock:
            remaining = self._limit - len(self._value)
            if remaining > 0:
                self._value.extend(chunk[:remaining])
            if len(chunk) > remaining:
                self._overflow = True

    def mark_overflow(self) -> None:
        with self._lock:
            self._overflow = True

    def snapshot_bytes(self) -> tuple[bytes, bool]:
        with self._lock:
            return bytes(self._value), self._overflow

    def snapshot_text(self) -> tuple[str, bool]:
        raw, overflow = self.snapshot_bytes()
        if self._limit == MAX_CAPTURED_STREAM_BYTES:
            return _bounded_evidence_text(raw), overflow
        return raw.decode("utf-8", "replace"), overflow


class _BoundedTextCapture(io.TextIOBase):
    """Python text sink sharing one aggregate budget with raw fd writes."""

    def __init__(self, accumulator: _BoundedByteAccumulator) -> None:
        super().__init__()
        self._accumulator = accumulator

    @property
    def encoding(self) -> str:
        return "utf-8"

    def writable(self) -> bool:
        return True

    def write(self, value: str) -> int:
        if type(value) is not str:
            raise TypeError("captured text must be an exact string")
        # At most limit+1 code points are needed to retain the prefix and prove
        # overflow (every code point is at least one UTF-8 byte).  This avoids a
        # second candidate-sized temporary allocation for a huge Python write.
        prefix = value[: self._accumulator.limit + 1]
        self._accumulator.append(prefix.encode("utf-8"))
        if len(prefix) < len(value):
            self._accumulator.mark_overflow()
        return len(value)

    def flush(self) -> None:
        return None


def _raw_fd_capture_pump(
    read_fd: int, accumulator: _BoundedByteAccumulator
) -> None:
    try:
        while True:
            chunk = os.read(read_fd, 8192)
            if not chunk:
                return
            accumulator.append(chunk)
    except OSError:
        return
    finally:
        try:
            os.close(read_fd)
        except OSError:
            pass


class _CandidateOutputCapture:
    """Capture Python text and OS fd 1/2 writes under one budget per stream.

    The worker protocol is moved to a separate descriptor before this context
    is used.  During candidate import, construction, and calls, fd 1 and fd 2
    point to private pipes.  ``contextlib`` captures ordinary Python writes
    into the same accumulators, while reader threads capture ``os.write`` and
    writes through ``sys.__stdout__`` / ``sys.__stderr__``.  Restoring the
    baseline descriptors closes the pipe writers and gives a deterministic EOF.
    """

    def __init__(self) -> None:
        self._stdout = _BoundedByteAccumulator(MAX_CAPTURED_STREAM_BYTES)
        self._stderr = _BoundedByteAccumulator(MAX_CAPTURED_STREAM_BYTES)
        self._text_stdout = _BoundedTextCapture(self._stdout)
        self._text_stderr = _BoundedTextCapture(self._stderr)
        self._saved_fd1: int | None = None
        self._saved_fd2: int | None = None
        self._stdout_redirect: Any = None
        self._stderr_redirect: Any = None
        self._threads: tuple[threading.Thread, threading.Thread] = ()
        self._broken = False
        self._non_quiescent = False

    def __enter__(self) -> _CandidateOutputCapture:
        for stream in (sys.__stdout__, sys.__stderr__):
            try:
                stream.flush()
            except Exception:
                pass
        self._saved_fd1 = os.dup(1)
        self._saved_fd2 = os.dup(2)
        stdout_read, stdout_write = os.pipe()
        stderr_read, stderr_write = os.pipe()
        stdout_thread = threading.Thread(
            target=_raw_fd_capture_pump,
            args=(stdout_read, self._stdout),
            name="ucm-candidate-fd1-capture",
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_raw_fd_capture_pump,
            args=(stderr_read, self._stderr),
            name="ucm-candidate-fd2-capture",
            daemon=True,
        )
        self._threads = (stdout_thread, stderr_thread)
        stdout_thread.start()
        stderr_thread.start()
        try:
            os.dup2(stdout_write, 1)
            os.dup2(stderr_write, 2)
        finally:
            os.close(stdout_write)
            os.close(stderr_write)
        self._stdout_redirect = contextlib.redirect_stdout(self._text_stdout)
        self._stderr_redirect = contextlib.redirect_stderr(self._text_stderr)
        self._stdout_redirect.__enter__()
        self._stderr_redirect.__enter__()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            if self._stderr_redirect is not None:
                self._stderr_redirect.__exit__(exc_type, exc, traceback)
            if self._stdout_redirect is not None:
                self._stdout_redirect.__exit__(exc_type, exc, traceback)
            # Flush bypasses through sys.__stdout__/sys.__stderr__ before fd
            # restoration.  A candidate that closes these streams is rejected.
            for stream in (sys.__stdout__, sys.__stderr__):
                try:
                    stream.flush()
                except Exception:
                    self._broken = True
        finally:
            try:
                if self._saved_fd1 is not None:
                    os.dup2(self._saved_fd1, 1)
                else:
                    self._broken = True
            except OSError:
                self._broken = True
            try:
                if self._saved_fd2 is not None:
                    os.dup2(self._saved_fd2, 2)
                else:
                    self._broken = True
            except OSError:
                self._broken = True
            for saved in (self._saved_fd1, self._saved_fd2):
                if saved is not None:
                    try:
                        os.close(saved)
                    except OSError:
                        self._broken = True
        for thread in self._threads:
            thread.join(timeout=1.0)
            if thread.is_alive():
                self._non_quiescent = True
        return False

    @property
    def captured_stdout(self) -> str:
        return self._stdout.snapshot_text()[0]

    @property
    def captured_stderr(self) -> str:
        return self._stderr.snapshot_text()[0]

    def require_valid(self) -> None:
        stdout_overflow = self._stdout.snapshot_bytes()[1]
        stderr_overflow = self._stderr.snapshot_bytes()[1]
        if stdout_overflow or stderr_overflow:
            raise CandidateCallViolation(
                "UCM-F008-STATE_NOT_CLOSED",
                "candidate captured stream exceeded byte limit",
            )
        if self._broken or self._non_quiescent:
            raise ProtocolViolation("candidate output descriptors did not close cleanly")


class _WorkerProtocolChannel:
    """Private protocol descriptor isolated from candidate-visible fd 1/2."""

    def __init__(self) -> None:
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except Exception:
                pass
        self._protocol_fd = os.dup(1)
        devnull_fd = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull_fd, 1)
            os.dup2(devnull_fd, 2)
        finally:
            os.close(devnull_fd)

    def emit(self, value: dict[str, Any]) -> None:
        _, frozen = _bounded_json_wire_size(value, limit=MAX_SESSION_FRAME_BYTES)
        encoded = canonical_json_bytes(frozen)
        if len(encoded) > MAX_SESSION_FRAME_BYTES:
            raise ProtocolViolation("worker protocol frame exceeded byte limit")
        view = memoryview(encoded)
        while view:
            written = os.write(self._protocol_fd, view)
            if written <= 0:
                raise OSError("worker protocol channel closed")
            view = view[written:]


class _BoundedPipeCapture:
    def __init__(self, limit: int = MAX_CAPTURED_STREAM_BYTES) -> None:
        self._accumulator = _BoundedByteAccumulator(limit)

    def append(self, chunk: bytes) -> None:
        self._accumulator.append(chunk)

    def snapshot(self) -> tuple[str, bool]:
        return self._accumulator.snapshot_text()

    def snapshot_bytes(self) -> tuple[bytes, bool]:
        return self._accumulator.snapshot_bytes()


def _session_stdout_pump(
    stream: Any,
    frames: queue.Queue[bytes | object],
    stop_event: threading.Event,
) -> None:
    total_bytes = 0

    def put_bounded(value: bytes | object) -> bool:
        while not stop_event.is_set():
            try:
                frames.put(value, timeout=0.05)
                return True
            except queue.Full:
                continue
        return False

    try:
        while not stop_event.is_set():
            line = stream.readline(MAX_SESSION_FRAME_BYTES + 2)
            if not line:
                put_bounded(_PIPE_EOF)
                return
            total_bytes += len(line)
            if total_bytes > MAX_SEQUENTIAL_AGGREGATE_BYTES:
                put_bounded(_PIPE_OVERFLOW)
                return
            if not put_bounded(line):
                return
    except Exception:
        put_bounded(_PIPE_EOF)


def _session_stderr_pump(stream: Any, capture: _BoundedPipeCapture) -> None:
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            capture.append(chunk)
    except Exception:
        return


def _bounded_binary_pipe_pump(stream: Any, capture: _BoundedPipeCapture) -> None:
    try:
        while True:
            chunk = stream.read(8192)
            if not chunk:
                return
            capture.append(chunk)
    except Exception:
        return


@dataclass(frozen=True, slots=True)
class _BoundedCompletedProcess:
    returncode: int
    stdout: bytes
    stdout_overflow: bool
    stderr: bytes
    stderr_overflow: bool
    prepared_attested: bool
    request_fully_sent: bool


def _run_fresh_process_bounded(
    command: list[str],
    *,
    request_bytes: bytes,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: float,
    binding_fields: dict[str, str],
    prepared_marker_path: Path,
    prepared_nonce: str,
) -> _BoundedCompletedProcess:
    """Run one worker with a trusted PREPARED-before-request handshake."""

    deadline = time.monotonic() + _positive_finite_seconds(
        timeout_seconds, "timeout_seconds"
    )
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
        )
    except Exception as exc:
        raise WorkerInvocationError(
            "could not start fresh candidate worker",
            failure_code="UCM-E003-HARNESS_INCOMPLETE",
            failure_origin="harness",
            **binding_fields,
        ) from exc
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_capture = _BoundedPipeCapture(MAX_SESSION_FRAME_BYTES)
    stderr_capture = _BoundedPipeCapture(MAX_CAPTURED_STREAM_BYTES)

    def marker_matches() -> bool:
        try:
            info = prepared_marker_path.lstat()
            if (
                prepared_marker_path.is_symlink()
                or not prepared_marker_path.is_file()
                or info.st_size != len(prepared_nonce)
            ):
                return False
            with prepared_marker_path.open("rb") as stream:
                raw = stream.read(len(prepared_nonce) + 1)
            return raw == prepared_nonce.encode("ascii")
        except OSError:
            return False

    def remaining() -> float:
        value = deadline - time.monotonic()
        if value <= 0.0:
            raise TimeoutError("fresh candidate worker timed out")
        return value

    def terminate(cleanup_deadline: float) -> None:
        if process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=_cleanup_remaining(cleanup_deadline))
            except subprocess.TimeoutExpired:
                pass

    def join_for_cleanup(
        cleanup_deadline: float, *threads: threading.Thread
    ) -> None:
        for thread in threads:
            if thread.ident is not None:
                thread.join(timeout=_cleanup_remaining(cleanup_deadline))

    stdout_thread = threading.Thread(
        target=_bounded_binary_pipe_pump,
        args=(process.stdout, stdout_capture),
        name="ucm-fresh-protocol-capture",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_bounded_binary_pipe_pump,
        args=(process.stderr, stderr_capture),
        name="ucm-fresh-stderr-capture",
        daemon=True,
    )
    try:
        stdout_thread.start()
        stderr_thread.start()
    except Exception as exc:
        cleanup_deadline = time.monotonic() + WORKER_CLEANUP_GRACE_SECONDS
        terminate(cleanup_deadline)
        join_for_cleanup(cleanup_deadline, stdout_thread, stderr_thread)
        raise WorkerInvocationError(
            "could not start fresh candidate worker pipe pumps",
            failure_code="UCM-E003-HARNESS_INCOMPLETE",
            returncode=process.poll(),
            failure_origin="harness",
            **binding_fields,
        ) from exc

    prepared_attested = False
    try:
        while True:
            if marker_matches():
                prepared_attested = True
                break
            if process.poll() is not None:
                break
            sleep_seconds = min(0.01, remaining())
            time.sleep(sleep_seconds)
    except TimeoutError as exc:
        cleanup_deadline = time.monotonic() + WORKER_CLEANUP_GRACE_SECONDS
        terminate(cleanup_deadline)
        join_for_cleanup(cleanup_deadline, stdout_thread, stderr_thread)
        raise WorkerInvocationError(
            "fresh candidate worker timed out before PREPARED",
            failure_code="UCM-E003-HARNESS_INCOMPLETE",
            captured_stdout=_bounded_evidence_text(
                stdout_capture.snapshot_bytes()[0]
            ),
            captured_stderr=_bounded_evidence_text(
                stderr_capture.snapshot_bytes()[0]
            ),
            returncode=process.poll(),
            failure_origin="harness",
            **binding_fields,
        ) from exc

    request_fully_sent = False
    if prepared_attested:
        try:
            prepared_marker_path.unlink()
            if os.path.lexists(os.fspath(prepared_marker_path)):
                raise OSError("PREPARED marker remained after unlink")
        except OSError as exc:
            cleanup_deadline = time.monotonic() + WORKER_CLEANUP_GRACE_SECONDS
            terminate(cleanup_deadline)
            join_for_cleanup(cleanup_deadline, stdout_thread, stderr_thread)
            raise WorkerInvocationError(
                "fresh parent could not retire the PREPARED marker",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=_bounded_evidence_text(
                    stdout_capture.snapshot_bytes()[0]
                ),
                captured_stderr=_bounded_evidence_text(
                    stderr_capture.snapshot_bytes()[0]
                ),
                returncode=process.poll(),
                failure_origin="harness",
                **binding_fields,
            ) from exc
        writer_result: queue.Queue[BaseException | None] = queue.Queue(maxsize=1)

        def write_request() -> None:
            try:
                remaining_view = memoryview(request_bytes)
                while remaining_view:
                    written = process.stdin.write(remaining_view)
                    if (
                        type(written) is not int
                        or written <= 0
                        or written > len(remaining_view)
                    ):
                        raise OSError("fresh request pipe returned an invalid write count")
                    remaining_view = remaining_view[written:]
                process.stdin.flush()
                process.stdin.close()
            except BaseException as exc:  # delivered to the controller
                writer_result.put(exc)
            else:
                writer_result.put(None)

        writer_thread = threading.Thread(
            target=write_request,
            name="ucm-fresh-request-writer",
            daemon=True,
        )
        writer_thread.start()
        try:
            write_error = writer_result.get(timeout=remaining())
        except (queue.Empty, TimeoutError) as exc:
            cleanup_deadline = time.monotonic() + WORKER_CLEANUP_GRACE_SECONDS
            terminate(cleanup_deadline)
            join_for_cleanup(
                cleanup_deadline, writer_thread, stdout_thread, stderr_thread
            )
            raise WorkerInvocationError(
                "fresh parent could not completely send the request",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=_bounded_evidence_text(
                    stdout_capture.snapshot_bytes()[0]
                ),
                captured_stderr=_bounded_evidence_text(
                    stderr_capture.snapshot_bytes()[0]
                ),
                returncode=process.poll(),
                failure_origin="harness",
                **binding_fields,
            ) from exc
        if write_error is not None:
            cleanup_deadline = time.monotonic() + WORKER_CLEANUP_GRACE_SECONDS
            terminate(cleanup_deadline)
            join_for_cleanup(
                cleanup_deadline, writer_thread, stdout_thread, stderr_thread
            )
            raise WorkerInvocationError(
                "fresh parent request pipe failed before complete delivery",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                captured_stdout=_bounded_evidence_text(
                    stdout_capture.snapshot_bytes()[0]
                ),
                captured_stderr=_bounded_evidence_text(
                    stderr_capture.snapshot_bytes()[0]
                ),
                returncode=process.poll(),
                failure_origin="harness",
                **binding_fields,
            ) from write_error
        request_fully_sent = True

    try:
        process.wait(timeout=remaining())
    except (subprocess.TimeoutExpired, TimeoutError) as exc:
        cleanup_deadline = time.monotonic() + WORKER_CLEANUP_GRACE_SECONDS
        terminate(cleanup_deadline)
        join_for_cleanup(cleanup_deadline, stdout_thread, stderr_thread)
        raise WorkerInvocationError(
            "fresh worker timed out at an unprovable in-process phase",
            failure_code="UCM-E003-HARNESS_INCOMPLETE",
            captured_stdout=_bounded_evidence_text(
                stdout_capture.snapshot_bytes()[0]
            ),
            captured_stderr=_bounded_evidence_text(
                stderr_capture.snapshot_bytes()[0]
            ),
            returncode=process.poll(),
            failure_origin="harness",
            **binding_fields,
        ) from exc

    cleanup_deadline = time.monotonic() + WORKER_CLEANUP_GRACE_SECONDS
    join_for_cleanup(cleanup_deadline, stdout_thread, stderr_thread)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        raise WorkerInvocationError(
            "fresh candidate worker pipes did not close cleanly",
            failure_code="UCM-E003-HARNESS_INCOMPLETE",
            captured_stdout=_bounded_evidence_text(
                stdout_capture.snapshot_bytes()[0]
            ),
            captured_stderr=_bounded_evidence_text(
                stderr_capture.snapshot_bytes()[0]
            ),
            returncode=process.poll(),
            failure_origin="harness",
            **binding_fields,
        )
    stdout_raw, stdout_overflow = stdout_capture.snapshot_bytes()
    stderr_raw, stderr_overflow = stderr_capture.snapshot_bytes()
    return _BoundedCompletedProcess(
        returncode=process.returncode,
        stdout=stdout_raw,
        stdout_overflow=stdout_overflow,
        stderr=stderr_raw,
        stderr_overflow=stderr_overflow,
        prepared_attested=prepared_attested,
        request_fully_sent=request_fully_sent,
    )

def _session_remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("sequential candidate worker timed out")
    return remaining


def _parse_canonical_session_frame(line: bytes) -> dict[str, Any]:
    if len(line) > MAX_SESSION_FRAME_BYTES or not line.endswith(b"\n"):
        raise ProtocolViolation("sequential worker emitted an oversized frame")
    body = line[:-1]
    if b"\n" in body or b"\r" in body:
        raise ProtocolViolation("sequential worker emitted invalid frame delimiters")
    try:
        value = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("sequential worker emitted malformed JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation("sequential worker frame must be an exact object")
    if canonical_json_bytes(value) != line:
        raise ProtocolViolation("sequential worker frame is not canonical JSON")
    if value.get("protocol") != SESSION_WORKER_PROTOCOL:
        raise ProtocolViolation("sequential worker emitted the wrong protocol")
    return value


def _parse_canonical_fresh_frame(frame: bytes) -> dict[str, Any]:
    """Parse exactly one canonical LF-terminated fresh-worker envelope."""

    if len(frame) > MAX_SESSION_FRAME_BYTES or not frame.endswith(b"\n"):
        raise ProtocolViolation("fresh worker emitted an oversized or partial frame")
    body = frame[:-1]
    if b"\n" in body or b"\r" in body:
        raise ProtocolViolation("fresh worker emitted invalid frame delimiters")
    try:
        value = json.loads(frame.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("fresh worker emitted malformed JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation("fresh worker frame must be an exact object")
    if canonical_json_bytes(value) != frame:
        raise ProtocolViolation("fresh worker frame is not canonical JSON")
    if value.get("protocol") != WORKER_PROTOCOL:
        raise ProtocolViolation("fresh worker emitted the wrong protocol")
    return value


class SequentialProcessExecutor:
    """Interact with one candidate instance without preloading future requests."""

    def __init__(
        self,
        entrypoint: CandidateEntrypoint,
        *,
        timeout_seconds: float = 20.0,
        python_executable: str | None = None,
    ) -> None:
        if type(entrypoint) is not CandidateEntrypoint:
            raise ProtocolViolation("entrypoint must be CandidateEntrypoint")
        self.entrypoint = entrypoint
        self.timeout_seconds = _positive_finite_seconds(
            timeout_seconds, "timeout_seconds"
        )
        self.python_executable = _approved_python_executable(python_executable)

    def invoke_sequence(
        self, requests: tuple[CandidateRequest, ...]
    ) -> tuple[InvocationOutcome, ...]:
        timeout_seconds = _positive_finite_seconds(
            self.timeout_seconds, "timeout_seconds"
        )
        python_executable = _approved_python_executable(self.python_executable)
        deadline = time.monotonic() + timeout_seconds
        worker_deadline = _worker_subdeadline(deadline, timeout_seconds)
        if type(requests) is not tuple or not requests:
            raise ProtocolViolation("sequential requests must be a non-empty tuple")
        if len(requests) > MAX_SESSION_REQUESTS:
            raise ProtocolViolation("sequential request count exceeds limit")
        if any(
            not isinstance(
                request,
                (InitializeRequest, UpdateRequest, DiagnoseRequest, RolloutRequest),
            )
            for request in requests
        ):
            raise ProtocolViolation("sequential requests contain an unknown request")

        # Freeze independently.  No request N+1 is sent before N completes.
        frozen_bytes_list: list[bytes] = []
        frozen_requests_list: list[CandidateRequest] = []
        request_preflight_bytes = 0
        for request in requests:
            encoded = canonical_json_bytes(request.to_wire())
            if len(encoded) > MAX_SESSION_FRAME_BYTES:
                raise ProtocolViolation("sequential request frame is too large")
            request_preflight_bytes += len(encoded)
            if request_preflight_bytes > MAX_SEQUENTIAL_AGGREGATE_BYTES:
                raise ProtocolViolation(
                    "sequential request aggregate exceeds byte limit"
                )
            frozen_bytes_list.append(encoded)
            frozen_requests_list.append(
                request_from_wire(json.loads(encoded.decode("utf-8")))
            )
        frozen_bytes = tuple(frozen_bytes_list)
        frozen_requests = tuple(frozen_requests_list)

        prepared_bindings: dict[str, str] = {}
        prepared: _PreparedImportInventory | None = None
        try:
            temp_context = tempfile.TemporaryDirectory(
                prefix="ucm-sequential-worker-"
            )
            raw_temp = temp_context.__enter__()
        except Exception as exc:
            raise WorkerInvocationError(
                "could not create sequential candidate worker directory",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                failure_origin="harness",
            ) from exc

        try:
            temp_root = Path(raw_temp).resolve()
            bootstrap_source = _UNIFIED_WORKER_BOOTSTRAP
            prepared = _write_import_allowlist_manifest(
                temp_root,
                self.entrypoint,
                deadline=worker_deadline,
                bootstrap_source=bootstrap_source,
            )
            prepared_bindings = {
                "import_inventory_digest": prepared.import_inventory_digest,
                "harness_bundle_digest": prepared.harness_bundle_digest,
                "candidate_bundle_digest": prepared.candidate_bundle_digest,
                "candidate_model_digest": prepared.candidate_model_digest,
                "module_origin": prepared.module_origin,
            }
            command = [
                python_executable,
                "-I",
                "-S",
                "-B",
                "-X",
                f"pycache_prefix={temp_root / 'pycache-prefix'}",
                "-c",
                bootstrap_source,
                str(prepared.worker_harness_root),
                str(prepared.worker_bundle_root),
                self.entrypoint.module,
                self.entrypoint.qualname,
                str(prepared.manifest_path),
                "sequential",
                prepared.harness_bundle_digest,
                prepared.manifest_sha256,
                str(temp_root / "harness-prepared.marker"),
                os.urandom(16).hex(),
            ]
            if digest_bytes(command[7].encode("utf-8")) != prepared.bootstrap_sha256:
                raise ProtocolViolation("sequential bootstrap source binding drifted")
            prepared_marker_path = Path(command[-2])
            prepared_nonce = command[-1]
            # The protocol is lock-step; retaining more than one unconsumed
            # maximum-size frame only creates a parent-memory amplification.
            frames: queue.Queue[bytes | object] = queue.Queue(maxsize=1)
            stderr_capture = _BoundedPipeCapture()
            pump_stop = threading.Event()
            try:
                process = subprocess.Popen(
                    command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=temp_root,
                    env=FreshProcessExecutor._worker_env(temp_root),
                )
            except Exception as exc:
                raise WorkerInvocationError(
                    "could not start sequential candidate worker",
                    failure_code="UCM-E003-HARNESS_INCOMPLETE",
                    failure_origin="harness",
                    **prepared_bindings,
                ) from exc
            assert process.stdin is not None
            assert process.stdout is not None
            assert process.stderr is not None
            stdout_thread = threading.Thread(
                target=_session_stdout_pump,
                args=(process.stdout, frames, pump_stop),
                name="ucm-session-stdout",
                daemon=True,
            )
            stderr_thread = threading.Thread(
                target=_session_stderr_pump,
                args=(process.stderr, stderr_capture),
                name="ucm-session-stderr",
                daemon=True,
            )
            try:
                stdout_thread.start()
                stderr_thread.start()
            except Exception as exc:
                cleanup_deadline = (
                    time.monotonic() + WORKER_CLEANUP_GRACE_SECONDS
                )
                pump_stop.set()
                if process.poll() is None:
                    process.kill()
                    try:
                        process.wait(
                            timeout=_cleanup_remaining(cleanup_deadline)
                        )
                    except subprocess.TimeoutExpired:
                        pass
                try:
                    process.stdin.close()
                except Exception:
                    pass
                if stdout_thread.ident is not None:
                    stdout_thread.join(
                        timeout=_cleanup_remaining(cleanup_deadline)
                    )
                if stderr_thread.ident is not None:
                    stderr_thread.join(
                        timeout=_cleanup_remaining(cleanup_deadline)
                    )
                raise WorkerInvocationError(
                    "could not start sequential candidate worker pipe pumps",
                    failure_code="UCM-E003-HARNESS_INCOMPLETE",
                    returncode=process.poll(),
                    failure_origin="harness",
                    **prepared_bindings,
                ) from exc

            outcomes: list[InvocationOutcome] = []
            import_stdout = ""
            import_stderr = ""
            worker_pid: int | None = None
            worker_ready = False
            prepared_confirmed = False
            candidate_delivery_active = False
            session_aggregate_bytes = 0
            session_cleanup_deadline: float | None = None

            def marker_matches() -> bool:
                try:
                    info = prepared_marker_path.lstat()
                    if (
                        prepared_marker_path.is_symlink()
                        or not prepared_marker_path.is_file()
                        or info.st_size != len(prepared_nonce)
                    ):
                        return False
                    with prepared_marker_path.open("rb") as stream:
                        raw = stream.read(len(prepared_nonce) + 1)
                    return raw == prepared_nonce.encode("ascii")
                except OSError:
                    return False

            def raw_stderr() -> str:
                return stderr_capture.snapshot()[0]

            def begin_cleanup() -> float:
                nonlocal session_cleanup_deadline
                session_cleanup_deadline = _begin_cleanup_deadline(
                    session_cleanup_deadline
                )
                return session_cleanup_deadline

            def terminate_worker() -> None:
                cleanup_deadline = begin_cleanup()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(
                            timeout=min(
                                0.5, _cleanup_remaining(cleanup_deadline)
                            )
                        )
                    except subprocess.TimeoutExpired:
                        process.kill()
                        try:
                            process.wait(
                                timeout=_cleanup_remaining(cleanup_deadline)
                            )
                        except subprocess.TimeoutExpired:
                            pass
                pump_stop.set()
                stdout_thread.join(
                    timeout=_cleanup_remaining(cleanup_deadline)
                )
                stderr_thread.join(
                    timeout=_cleanup_remaining(cleanup_deadline)
                )
            def charge_frame_bytes(amount: int) -> None:
                nonlocal session_aggregate_bytes
                session_aggregate_bytes += amount
                if session_aggregate_bytes > MAX_SEQUENTIAL_AGGREGATE_BYTES:
                    raise ProtocolViolation(
                        "sequential request/response aggregate exceeds byte limit"
                    )

            def next_frame() -> dict[str, Any]:
                try:
                    item = frames.get(timeout=_session_remaining(worker_deadline))
                except queue.Empty as exc:
                    raise TimeoutError(
                        "sequential candidate worker timed out"
                    ) from exc
                if item is _PIPE_EOF:
                    returncode = process.poll()
                    if returncode is None:
                        try:
                            returncode = process.wait(
                                timeout=min(
                                    0.05, _session_remaining(worker_deadline)
                                )
                            )
                        except subprocess.TimeoutExpired:
                            returncode = None
                    if returncode not in {0, None}:
                        raise WorkerInvocationError(
                            "sequential candidate worker returned a malformed envelope after candidate exit",
                            failure_code="UCM-E003-HARNESS_INCOMPLETE",
                            captured_stderr=raw_stderr(),
                            returncode=returncode,
                            # EOF/nonzero is not a canonical worker response;
                            # only a full-send timeout has the development
                            # candidate-origin exception.
                            failure_origin="harness",
                            **prepared_bindings,
                        )
                    raise ProtocolViolation(
                        "sequential candidate worker returned a malformed envelope"
                    )
                if item is _PIPE_OVERFLOW:
                    raise ProtocolViolation(
                        "sequential worker exceeded the aggregate output limit"
                    )
                assert type(item) is bytes
                charge_frame_bytes(len(item))
                return _parse_canonical_session_frame(item)

            def send_frame(value: dict[str, Any], *, close_after: bool = False) -> None:
                encoded = canonical_json_bytes(value)
                if len(encoded) > MAX_SESSION_FRAME_BYTES:
                    raise ProtocolViolation("sequential request frame is too large")
                charge_frame_bytes(len(encoded))
                result: queue.Queue[BaseException | None] = queue.Queue(maxsize=1)

                def write_one() -> None:
                    try:
                        remaining_view = memoryview(encoded)
                        while remaining_view:
                            written = process.stdin.write(remaining_view)
                            if (
                                type(written) is not int
                                or written <= 0
                                or written > len(remaining_view)
                            ):
                                raise OSError(
                                    "sequential request pipe returned an invalid write count"
                                )
                            remaining_view = remaining_view[written:]
                        process.stdin.flush()
                        if close_after:
                            process.stdin.close()
                    except BaseException as exc:  # delivered to controller
                        result.put(exc)
                    else:
                        result.put(None)

                writer = threading.Thread(
                    target=write_one,
                    name="ucm-session-request-writer",
                    daemon=True,
                )
                writer.start()
                try:
                    write_result = result.get(timeout=_session_remaining(worker_deadline))
                except (queue.Empty, TimeoutError) as exc:
                    raise WorkerInvocationError(
                        "sequential parent could not completely send a frame",
                        failure_code="UCM-E003-HARNESS_INCOMPLETE",
                        captured_stderr=raw_stderr(),
                        returncode=process.poll(),
                        failure_origin="harness",
                        **prepared_bindings,
                    ) from exc
                if write_result is not None:
                    raise WorkerInvocationError(
                        "sequential parent frame pipe failed before complete delivery",
                        failure_code="UCM-E003-HARNESS_INCOMPLETE",
                        captured_stderr=raw_stderr(),
                        returncode=process.poll(),
                        failure_origin="harness",
                        **prepared_bindings,
                    ) from write_result

            binding_names = (
                "import_inventory_digest",
                "harness_bundle_digest",
                "candidate_bundle_digest",
                "candidate_model_digest",
                "module_origin",
            )

            def checked_bindings(
                frame: dict[str, Any], *, allow_empty_harness: bool = False
            ) -> dict[str, str]:
                values = {name: frame[name] for name in binding_names}
                if all(type(value) is str for value in values.values()):
                    if values != prepared_bindings:
                        raise ProtocolViolation(
                            "sequential worker byte-inventory binding mismatch"
                        )
                    return values  # type: ignore[return-value]
                if (
                    allow_empty_harness
                    and frame.get("failure_origin") == "harness"
                    and all(value is None for value in values.values())
                ):
                    return prepared_bindings
                raise ProtocolViolation(
                    "sequential worker byte-inventory binding is malformed"
                )

            def raise_worker_error(frame: dict[str, Any]) -> None:
                frame = _exact_keys(
                    frame,
                    required=frozenset(
                        {
                            "protocol",
                            "type",
                            "ok",
                            "failure_origin",
                            "error",
                            "audit_events",
                            "audit_overflow",
                            "captured_stdout",
                            "captured_stderr",
                            "worker_pid",
                            *binding_names,
                        }
                    ),
                    label="sequential error frame",
                )
                declared_origin = frame["failure_origin"]
                if (
                    frame["type"] != "error"
                    or frame["ok"] is not False
                    or declared_origin not in {"candidate", "harness"}
                    or (declared_origin == "candidate" and not candidate_delivery_active)
                ):
                    raise ProtocolViolation("sequential error frame is malformed")
                bindings = checked_bindings(
                    frame, allow_empty_harness=not prepared_confirmed
                )
                error = _exact_keys(
                    frame["error"],
                    required=frozenset(
                        {"failure_code", "type", "message", "request_index"}
                    ),
                    label="sequential worker error",
                )
                _validate_failure_origin_code(
                    declared_origin, error.get("failure_code")
                )
                expected_request_index = len(outcomes) if worker_ready else None
                if error["request_index"] != expected_request_index:
                    raise ProtocolViolation(
                        "sequential error request index is out of phase"
                    )
                events = frame["audit_events"]
                overflow = frame["audit_overflow"]
                if (
                    type(events) is not list
                    or len(events) > MAX_AUDIT_EVENTS
                    or any(type(row) is not dict for row in events)
                    or type(overflow) is not bool
                ):
                    raise ProtocolViolation("sequential error audit is malformed")
                error_stdout = _validated_capture_field(
                    frame["captured_stdout"],
                    label="sequential error captured_stdout",
                )
                error_stderr = _validated_capture_field(
                    frame["captured_stderr"],
                    label="sequential error captured_stderr",
                )
                raise WorkerInvocationError(
                    str(error["message"]),
                    failure_code=str(error["failure_code"]),
                    audit_events=tuple(events),
                    audit_overflow=overflow,
                    captured_stdout=error_stdout,
                    captured_stderr=_merge_bounded_evidence(
                        error_stderr, raw_stderr()
                    ),
                    returncode=process.poll(),
                    failure_origin=declared_origin,
                    **bindings,
                )

            try:
                prepared_frame = next_frame()
                if prepared_frame.get("type") == "error":
                    raise_worker_error(prepared_frame)
                prepared_frame = _exact_keys(
                    prepared_frame,
                    required=frozenset(
                        {
                            "protocol",
                            "type",
                            "ok",
                            "failure_origin",
                            "worker_pid",
                            "audit_events",
                            "audit_overflow",
                            *binding_names,
                        }
                    ),
                    label="sequential prepared frame",
                )
                if (
                    prepared_frame["type"] != "prepared"
                    or prepared_frame["ok"] is not True
                    or prepared_frame["failure_origin"] is not None
                    or prepared_frame["audit_events"] != []
                    or prepared_frame["audit_overflow"] is not False
                ):
                    raise ProtocolViolation("sequential PREPARED frame is malformed")
                checked_bindings(prepared_frame)
                worker_pid = _positive_worker_pid(
                    prepared_frame["worker_pid"], "prepared worker_pid"
                )
                if not marker_matches():
                    raise ProtocolViolation(
                        "sequential PREPARED frame lacked exact marker authority"
                    )
                try:
                    prepared_marker_path.unlink()
                    if os.path.lexists(os.fspath(prepared_marker_path)):
                        raise OSError("PREPARED marker remained after unlink")
                except OSError as exc:
                    raise ProtocolViolation(
                        "sequential parent could not retire the PREPARED marker"
                    ) from exc
                prepared_confirmed = True

                send_frame(
                    {
                        "protocol": SESSION_REQUEST_PROTOCOL,
                        "type": "go",
                        "index": 0,
                    }
                )
                candidate_delivery_active = True
                ready = next_frame()
                if ready.get("type") == "error":
                    raise_worker_error(ready)
                ready = _exact_keys(
                    ready,
                    required=frozenset(
                        {
                            "protocol",
                            "type",
                            "ok",
                            "failure_origin",
                            "worker_pid",
                            "audit_events",
                            "audit_overflow",
                            "captured_stdout",
                            "captured_stderr",
                            *binding_names,
                        }
                    ),
                    label="sequential ready frame",
                )
                if (
                    ready["type"] != "ready"
                    or ready["ok"] is not True
                    or ready["failure_origin"] is not None
                    or ready["worker_pid"] != worker_pid
                ):
                    raise ProtocolViolation("sequential worker did not become ready")
                checked_bindings(ready)
                if ready["audit_events"] != [] or ready["audit_overflow"] is not False:
                    raise ProtocolViolation("ready frame contains denied audit events")
                import_stdout = _validated_capture_field(
                    ready["captured_stdout"],
                    label="sequential ready captured_stdout",
                )
                import_stderr = _validated_capture_field(
                    ready["captured_stderr"],
                    label="sequential ready captured_stderr",
                )
                candidate_delivery_active = False
                worker_ready = True

                for index, (request, encoded_request) in enumerate(
                    zip(frozen_requests, frozen_bytes)
                ):
                    wire = json.loads(encoded_request.decode("utf-8"))
                    send_frame(
                        {
                            "protocol": SESSION_REQUEST_PROTOCOL,
                            "type": "request",
                            "index": index,
                            "request": wire,
                        }
                    )
                    candidate_delivery_active = True
                    row = next_frame()
                    if row.get("type") == "error":
                        raise_worker_error(row)
                    row = _exact_keys(
                        row,
                        required=frozenset(
                            {
                                "protocol",
                                "type",
                                "ok",
                                "failure_origin",
                                "index",
                                "response",
                                "audit_events",
                                "audit_overflow",
                                "captured_stdout",
                                "captured_stderr",
                                *binding_names,
                            }
                        ),
                        label="sequential result frame",
                    )
                    if (
                        row["type"] != "result"
                        or row["ok"] is not True
                        or row["failure_origin"] is not None
                        or row["index"] != index
                    ):
                        raise ProtocolViolation(
                            "sequential worker result frame is out of order"
                        )
                    row_bindings = checked_bindings(row)
                    try:
                        response = response_from_wire(row["response"])
                        _validate_response_for_request(request, response)
                    except (ProtocolViolation, CandidateCallViolation) as exc:
                        raise WorkerInvocationError(
                            "sequential worker response could not be parsed",
                            failure_code="UCM-E003-HARNESS_INCOMPLETE",
                            captured_stderr=raw_stderr(),
                            returncode=process.poll(),
                            failure_origin="harness",
                            **prepared_bindings,
                        ) from exc
                    row_stdout = _validated_capture_field(
                        row["captured_stdout"],
                        label="sequential result captured_stdout",
                    )
                    row_stderr = _validated_capture_field(
                        row["captured_stderr"],
                        label="sequential result captured_stderr",
                    )
                    row_audit = row["audit_events"]
                    row_overflow = row["audit_overflow"]
                    if (
                        type(row_audit) is not list
                        or len(row_audit) > MAX_AUDIT_EVENTS
                        or any(type(item) is not dict for item in row_audit)
                        or type(row_overflow) is not bool
                    ):
                        raise ProtocolViolation(
                            "sequential result audit evidence is malformed"
                        )
                    candidate_delivery_active = False
                    if row_audit or row_overflow:
                        raise WorkerInvocationError(
                            "sequential candidate worker caught a denied audited capability",
                            failure_code=_classify_denied_audit(row_audit, request),
                            audit_events=tuple(row_audit),
                            audit_overflow=row_overflow,
                            captured_stdout=row_stdout,
                            captured_stderr=_merge_bounded_evidence(
                                row_stderr, raw_stderr()
                            ),
                            returncode=process.poll(),
                            failure_origin="candidate",
                            **row_bindings,
                        )
                    outcomes.append(
                        InvocationOutcome(
                            response=response,
                            request_digest=digest_json(wire),
                            response_digest=digest_json(response.to_wire()),
                            isolation="sequential-python-process-audit-v3",
                            audit_events=tuple(row_audit),
                            audit_overflow=row_overflow,
                            captured_stdout=_merge_bounded_evidence(
                                import_stdout if index == 0 else "", row_stdout
                            ),
                            captured_stderr=_merge_bounded_evidence(
                                import_stderr if index == 0 else "", row_stderr
                            ),
                            worker_pid=worker_pid,
                            **row_bindings,
                        )
                    )

                send_frame(
                    {
                        "protocol": SESSION_REQUEST_PROTOCOL,
                        "type": "close",
                        "index": len(frozen_requests),
                    },
                    close_after=True,
                )
                candidate_delivery_active = False
                closed = next_frame()
                if closed.get("type") == "error":
                    raise_worker_error(closed)
                closed = _exact_keys(
                    closed,
                    required=frozenset(
                        {
                            "protocol",
                            "type",
                            "ok",
                            "worker_pid",
                            "requests_completed",
                        }
                    ),
                    label="sequential close frame",
                )
                if (
                    closed["type"] != "closed"
                    or closed["ok"] is not True
                    or closed["worker_pid"] != worker_pid
                    or closed["requests_completed"] != len(frozen_requests)
                ):
                    raise ProtocolViolation("sequential close acknowledgement is invalid")
                process.wait(timeout=_session_remaining(worker_deadline))
                if process.returncode != 0:
                    raise WorkerInvocationError(
                        "sequential candidate worker exited unsuccessfully during close",
                        failure_code="UCM-E003-HARNESS_INCOMPLETE",
                        captured_stderr=raw_stderr(),
                        returncode=process.returncode,
                        failure_origin="harness",
                        **prepared_bindings,
                    )
                cleanup_deadline = begin_cleanup()
                stdout_thread.join(
                    timeout=_cleanup_remaining(cleanup_deadline)
                )
                stderr_thread.join(
                    timeout=_cleanup_remaining(cleanup_deadline)
                )
                if stdout_thread.is_alive() or stderr_thread.is_alive():
                    raise ProtocolViolation(
                        "sequential worker pipe pumps did not quiesce"
                    )
                try:
                    trailing = frames.get_nowait()
                except queue.Empty as exc:
                    raise ProtocolViolation(
                        "sequential worker stdout did not close cleanly"
                    ) from exc
                if trailing is not _PIPE_EOF:
                    raise ProtocolViolation("sequential worker emitted extra output")
                pump_stop.set()
                stderr_text, stderr_overflow = stderr_capture.snapshot()
                if stderr_text or stderr_overflow:
                    raise ProtocolViolation(
                        "sequential worker emitted uncaptured stderr output"
                    )
                if len({outcome.worker_pid for outcome in outcomes}) != 1:
                    raise ProtocolViolation(
                        "sequential worker did not bind one candidate process"
                    )
                return tuple(outcomes)
            except (TimeoutError, subprocess.TimeoutExpired) as exc:
                terminate_worker()
                raise WorkerInvocationError(
                    "sequential worker timed out at an unprovable in-process phase",
                    failure_code="UCM-E003-HARNESS_INCOMPLETE",
                    captured_stderr=raw_stderr(),
                    returncode=process.poll(),
                    failure_origin="harness",
                    **prepared_bindings,
                ) from exc
            except WorkerInvocationError:
                terminate_worker()
                raise
            except Exception as exc:
                terminate_worker()
                raise WorkerInvocationError(
                    "sequential candidate worker returned a malformed envelope",
                    failure_code="UCM-E003-HARNESS_INCOMPLETE",
                    captured_stderr=raw_stderr(),
                    returncode=process.poll(),
                    failure_origin="harness",
                    **prepared_bindings,
                ) from exc
        except _PreparationTimeout as exc:
            raise WorkerInvocationError(
                "sequential candidate preparation timed out",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                failure_origin="harness",
                **prepared_bindings,
            ) from exc
        except WorkerInvocationError:
            raise
        except Exception as exc:
            raise WorkerInvocationError(
                "sequential candidate preparation failed",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                failure_origin="harness",
                **prepared_bindings,
            ) from exc
        finally:
            primary_error = sys.exc_info()[1]
            try:
                if prepared is not None:
                    _parent_verify_prepared_inventory(
                        prepared,
                        deadline=deadline,
                    )
            except Exception as exc:
                raise _combined_postverify_failure(
                    primary_error,
                    exc,
                    label="sequential parent post-verification failed",
                    binding_fields=prepared_bindings,
                ) from exc
            finally:
                temp_context.__exit__(None, None, None)


_DENIED_AUDIT_EVENTS = frozenset(
    {
        "open",
        "os.chdir",
        "os.chmod",
        "os.chown",
        "os.fork",
        "os.forkpty",
        "os.exec",
        "os.system",
        "os.spawn",
        "os.kill",
        "os.link",
        "os.mkdir",
        "os.posix_spawn",
        "os.remove",
        "os.rename",
        "os.rmdir",
        "os.symlink",
        "os.truncate",
        "os.utime",
        "subprocess.Popen",
        "socket.__new__",
        "socket.bind",
        "socket.connect",
        "socket.getaddrinfo",
        "ctypes.dlopen",
        "mmap.__new__",
    }
)


def _audit_arg(value: Any) -> str:
    kind = type(value)
    try:
        if kind is str:
            text = repr(value[:512])
        elif kind is bytes:
            text = repr(value[:512])
        elif value is None or kind in {bool, int, float}:
            text = repr(value)
        else:
            text = f"<{kind.__module__}.{kind.__qualname__}>"
    except Exception:
        text = "<unprintable-audit-arg>"
    return text[:512]


def _audit_open_is_read_only(args: tuple[Any, ...]) -> bool:
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else None
    if mode is not None:
        if type(mode) is not str or any(token in mode for token in "wax+"):
            return False
    if type(flags) is int:
        write_flags = (
            os.O_WRONLY
            | os.O_RDWR
            | os.O_CREAT
            | os.O_TRUNC
            | os.O_APPEND
            | getattr(os, "O_EXCL", 0)
        )
        if flags & write_flags:
            return False
    return True


class _CandidateAuditBoundary:
    """Always-on import/call audit with a temporary exact import manifest."""

    def __init__(self, import_read_allowlist: frozenset[str]) -> None:
        self._import_read_allowlist = import_read_allowlist
        self._import_phase = True
        self._inventory_verification_phase = False
        self._attestation_write_path: str | None = None
        self._attestation_publish_pair: tuple[str, str] | None = None
        self._denied_events = _DENIED_AUDIT_EVENTS
        self._normalize_file_path = _normalized_file_path
        self._open_is_read_only = _audit_open_is_read_only
        self._render_arg = _audit_arg
        self._max_events = MAX_AUDIT_EVENTS
        self._max_args = MAX_AUDIT_EVENT_ARGS
        self._os_open = os.open
        self._os_write = os.write
        self._os_fsync = os.fsync
        self._os_close = os.close
        self._os_replace = os.replace
        self.audit_events: list[dict[str, Any]] = []
        self.audit_overflow = False

    def finish_import(self) -> None:
        self._import_phase = False

    def verify_inventory_bytes(
        self, inventory: _WorkerImportInventory, bundle_root: Path
    ) -> None:
        self._inventory_verification_phase = True
        try:
            _verify_worker_harness_inventory_bytes(inventory)
            _verify_worker_runtime_inventory_bytes(inventory)
            _verify_worker_inventory_bytes(inventory, bundle_root)
        finally:
            self._inventory_verification_phase = False

    def commit_attestation(self, path: Path, nonce: str, label: str) -> None:
        normalized = self._normalize_file_path(path)
        pending = path.with_name(f".{path.name}.{nonce}.pending")
        pending_normalized = self._normalize_file_path(pending)
        self._attestation_write_path = pending_normalized
        self._attestation_publish_pair = (pending_normalized, normalized)
        descriptor: int | None = None
        try:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = self._os_open(pending, flags, 0o600)
            remaining = memoryview(nonce.encode("ascii"))
            while remaining:
                written = self._os_write(descriptor, remaining)
                if (
                    type(written) is not int
                    or written <= 0
                    or written > len(remaining)
                ):
                    raise OSError(f"{label} attestation write was incomplete")
                remaining = remaining[written:]
            self._os_fsync(descriptor)
            self._os_close(descriptor)
            descriptor = None
            self._os_replace(pending, path)
        finally:
            if descriptor is not None:
                self._os_close(descriptor)
            self._attestation_write_path = None
            self._attestation_publish_pair = None

    def __call__(self, event: str, args: tuple[Any, ...]) -> None:
        write_requested = False
        if event == "open":
            write_requested = not self._open_is_read_only(args)
            allowed = False
            if self._attestation_write_path is not None and args:
                try:
                    allowed = (
                        self._normalize_file_path(args[0])
                        == self._attestation_write_path
                    )
                except (TypeError, ValueError, OSError):
                    allowed = False
            if (
                not allowed
                and (self._import_phase or self._inventory_verification_phase)
                and args
                and self._open_is_read_only(args)
            ):
                try:
                    allowed = (
                        self._normalize_file_path(args[0])
                        in self._import_read_allowlist
                    )
                except (TypeError, ValueError, OSError):
                    allowed = False
            if allowed:
                return
        elif event == "os.rename" and self._attestation_publish_pair is not None:
            try:
                pair = (
                    self._normalize_file_path(args[0]),
                    self._normalize_file_path(args[1]),
                )
            except (IndexError, TypeError, ValueError, OSError):
                pair = ("", "")
            if pair == self._attestation_publish_pair:
                return
        elif event not in self._denied_events and not event.startswith("winreg."):
            return
        if len(self.audit_events) < self._max_events:
            row = {
                "event": event,
                "args": [self._render_arg(arg) for arg in args[: self._max_args]],
            }
            if event == "open":
                row["write_requested"] = write_requested
            self.audit_events.append(row)
        else:
            self.audit_overflow = True
        raise PermissionError(
            f"UCM candidate boundary denied audited capability: {event}"
        )


def _classify_denied_audit(
    audit_events: list[dict[str, Any]], request: CandidateRequest | None
) -> str:
    """Map a denied capability to the most specific registered failure code.

    The decision uses only the audited capability/path and request operation;
    it does not trust a candidate-provided label.  Generic head file access is
    history access, while explicit future/oracle/model paths retain their more
    decisive information-flow semantics.
    """

    open_rows = [row for row in audit_events if row.get("event") == "open"]
    open_text = " ".join(
        str(part).lower() for row in open_rows for part in row.get("args", [])
    )
    if any(
        token in open_text for token in ("model", "checkpoint", "weights")
    ) and any(row.get("write_requested") is True for row in open_rows):
        return "UCM-F009-MODEL_MUTATION"
    if any(
        token in open_text
        for token in (
            "simulator",
            "hidden-state",
            "hidden_state",
            "true-state",
            "true_state",
            "oracle",
        )
    ):
        return "UCM-F002-ORACLE_TRUE_STATE_ACCESS"
    if any(
        token in open_text
        for token in ("actual-future", "actual_future", "future", "results")
    ):
        return "UCM-F001-FUTURE_LEAK"
    if open_rows and request is not None and request.operation in {
        Operation.DIAGNOSE,
        Operation.ROLLOUT,
    }:
        return "UCM-F004-HEAD_HISTORY_ACCESS"
    return "UCM-F008-STATE_NOT_CLOSED"


def _inventory_binding_wire(
    inventory: _WorkerImportInventory | None,
) -> dict[str, str | None]:
    if inventory is None:
        return {
            "import_inventory_digest": None,
            "harness_bundle_digest": None,
            "candidate_bundle_digest": None,
            "candidate_model_digest": None,
            "module_origin": None,
        }
    return {
        "import_inventory_digest": inventory.import_inventory_digest,
        "harness_bundle_digest": inventory.harness_bundle_digest,
        "candidate_bundle_digest": inventory.candidate_bundle_digest,
        "candidate_model_digest": inventory.candidate_model_digest,
        "module_origin": inventory.module_origin,
    }


def _worker_failure_origin(
    exc: Exception,
    *,
    phase: str,
    audit_events: list[dict[str, Any]],
    audit_overflow: bool,
) -> str:
    if phase in _HARNESS_FAILURE_PHASES:
        return "harness"
    if phase in {"candidate-import", "candidate-call"}:
        return "candidate"
    if phase == "candidate-validation" and isinstance(
        exc, CandidateCallViolation
    ):
        return "candidate"
    # Unknown phases are not evidence of candidate ownership.  The closed set
    # below is also source-bound and tested; any drift fails conservatively.
    return "harness"


_CANDIDATE_FAILURE_PHASES = frozenset(
    {"candidate-import", "candidate-call", "candidate-validation"}
)
_HARNESS_FAILURE_PHASES = frozenset(
    {
        "manifest",
        "harness-prepared-attestation",
        "request-parser",
        "go-parser",
        "harness-post-import",
        "harness-response-finalization",
        "harness-postcheck",
    }
)
_WORKER_FAILURE_PHASES = _CANDIDATE_FAILURE_PHASES | _HARNESS_FAILURE_PHASES


def _worker_main(
    harness_root_text: str,
    bundle_root_text: str,
    module_name: str,
    qualname: str,
    import_allowlist_path: str,
    prepared_marker_path: str,
    prepared_nonce: str,
) -> int:
    """Private subprocess entry point.  The parent parses only this envelope."""

    protocol = _WorkerProtocolChannel()
    audit_events: list[dict[str, Any]] = []
    capture = _CandidateOutputCapture()
    request: CandidateRequest | None = None
    boundary: _CandidateAuditBoundary | None = None
    inventory: _WorkerImportInventory | None = None
    boundary_call: Any = None
    boundary_call_code: Any = None
    boundary_finish_import: Any = None
    boundary_finish_import_func: Any = None
    boundary_finish_import_code: Any = None
    boundary_commit_attestation: Any = None
    boundary_commit_func: Any = None
    boundary_commit_code: Any = None
    boundary_verify_func: Any = None
    boundary_verify_code: Any = None
    harness_verifier: Any = None
    harness_verifier_code: Any = None
    runtime_verifier: Any = None
    runtime_verifier_code: Any = None
    candidate_verifier: Any = None
    candidate_verifier_code: Any = None
    phase = "manifest"

    def set_phase(value: str) -> None:
        nonlocal phase
        if value not in _WORKER_FAILURE_PHASES:
            raise ProtocolViolation("worker phase escaped its closed taxonomy")
        phase = value

    try:
        worker_cwd = Path.cwd().resolve()
        prepared_marker = Path(prepared_marker_path).resolve()
        if (
            prepared_marker.parent != worker_cwd
            or re.fullmatch(r"[0-9a-f]{32}", prepared_nonce) is None
        ):
            raise ProtocolViolation(
                "fresh PREPARED-attestation parameters are malformed"
            )
        inventory = _read_import_allowlist_manifest(
            import_allowlist_path, bundle_root_text, harness_root_text
        )
        root = Path.cwd()  # the empty isolated worker directory
        entrypoint = CandidateEntrypoint(
            bundle_root=Path(bundle_root_text),
            module=module_name,
            qualname=qualname,
        )
        _verify_worker_harness_inventory_bytes(inventory)
        _verify_worker_runtime_inventory_bytes(inventory)
        _verify_worker_inventory_bytes(inventory, entrypoint.bundle_root)
        boundary = _CandidateAuditBoundary(inventory.allowed_files)
        audit_events = boundary.audit_events
        boundary_call = type(boundary).__call__
        boundary_call_code = boundary_call.__code__
        boundary_finish_import = boundary.finish_import
        boundary_finish_import_func = type(boundary).finish_import
        boundary_finish_import_code = boundary_finish_import_func.__code__
        boundary_commit_attestation = boundary.commit_attestation
        boundary_commit_func = type(boundary).commit_attestation
        boundary_commit_code = boundary_commit_func.__code__
        boundary_verify_func = type(boundary).verify_inventory_bytes
        boundary_verify_code = boundary_verify_func.__code__
        harness_verifier = _verify_worker_harness_inventory_bytes
        harness_verifier_code = harness_verifier.__code__
        runtime_verifier = _verify_worker_runtime_inventory_bytes
        runtime_verifier_code = runtime_verifier.__code__
        candidate_verifier = _verify_worker_inventory_bytes
        candidate_verifier_code = candidate_verifier.__code__

        def verify_bound_inventory(*, rehash: bool) -> None:
            if (
                type(boundary).verify_inventory_bytes is not boundary_verify_func
                or boundary_verify_func.__code__ is not boundary_verify_code
                or type(boundary).commit_attestation is not boundary_commit_func
                or boundary_commit_func.__code__ is not boundary_commit_code
                or _verify_worker_harness_inventory_bytes is not harness_verifier
                or harness_verifier.__code__ is not harness_verifier_code
                or _verify_worker_runtime_inventory_bytes is not runtime_verifier
                or runtime_verifier.__code__ is not runtime_verifier_code
                or _verify_worker_inventory_bytes is not candidate_verifier
                or candidate_verifier.__code__ is not candidate_verifier_code
            ):
                raise ProtocolViolation(
                    "candidate tampered with an inventory verifier"
                )
            if rehash:
                boundary._inventory_verification_phase = True
                try:
                    harness_verifier(inventory)
                    runtime_verifier(inventory)
                    candidate_verifier(inventory, entrypoint.bundle_root)
                finally:
                    boundary._inventory_verification_phase = False

        # Register the already-bound method.  Replacing the exported class
        # attribute no longer swaps the live hook, although pure-Python code
        # mutation remains outside this portable isolation grade.
        sys.addaudithook(boundary.__call__)
        phase = "harness-prepared-attestation"
        boundary_commit_attestation(
            prepared_marker, prepared_nonce, "fresh harness-prepared"
        )
        sys.argv[9] = "<retired-prepared-marker>"
        sys.argv[10] = "<retired-prepared-nonce>"
        prepared_marker_path = ""
        prepared_nonce = ""
        prepared_marker = None
        phase = "request-parser"
        request_frame = sys.stdin.buffer.read(MAX_SESSION_FRAME_BYTES + 1)
        if len(request_frame) > MAX_SESSION_FRAME_BYTES:
            raise ProtocolViolation("fresh parent sent an oversized request frame")
        try:
            wire = json.loads(request_frame.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("fresh parent sent malformed JSON") from exc
        if canonical_json_bytes(wire) != request_frame:
            raise ProtocolViolation("fresh parent request is not canonical JSON")
        request = request_from_wire(wire)
        with capture:
            set_phase("candidate-import")
            try:
                candidate = _load_candidate(entrypoint, inventory)
            except BaseException:
                set_phase("harness-post-import")
                if (
                    type(boundary).finish_import is not boundary_finish_import_func
                    or boundary_finish_import_func.__code__
                    is not boundary_finish_import_code
                ):
                    raise ProtocolViolation(
                        "candidate tampered with the import-phase boundary"
                    )
                boundary_finish_import()
                set_phase("candidate-import")
                raise
            else:
                set_phase("harness-post-import")
                if (
                    type(boundary).finish_import is not boundary_finish_import_func
                    or boundary_finish_import_func.__code__
                    is not boundary_finish_import_code
                ):
                    raise ProtocolViolation(
                        "candidate tampered with the import-phase boundary"
                    )
                boundary_finish_import()
            if (
                type(boundary).__call__ is not boundary_call
                or boundary_call.__code__ is not boundary_call_code
            ):
                raise ProtocolViolation("candidate tampered with the Python audit hook")
            if audit_events or boundary.audit_overflow:
                set_phase("candidate-import")
                raise PermissionError("candidate caught a denied import capability")
            set_phase("harness-post-import")
            verify_bound_inventory(rehash=True)
            set_phase("harness-response-finalization")
            response = _dispatch_candidate(
                candidate, request, phase_hook=set_phase
            )
        set_phase("candidate-validation")
        capture.require_valid()
        if (
            type(boundary).__call__ is not boundary_call
            or boundary_call.__code__ is not boundary_call_code
        ):
            raise ProtocolViolation("candidate tampered with the Python audit hook")
        if audit_events or boundary.audit_overflow:
            set_phase("candidate-call")
            raise PermissionError("candidate caught a denied audited capability")
        set_phase("harness-postcheck")
        verify_bound_inventory(rehash=True)
        envelope = {
            "protocol": WORKER_PROTOCOL,
            "ok": True,
            "failure_origin": None,
            "response": response.to_wire(),
            "audit_events": audit_events,
            "audit_overflow": boundary.audit_overflow,
            "captured_stdout": capture.captured_stdout,
            "captured_stderr": capture.captured_stderr,
            "worker_pid": os.getpid(),
            "worker_cwd_isolated": root == Path.cwd(),
            **_inventory_binding_wire(inventory),
        }
        protocol.emit(envelope)
        return 0
    except Exception as exc:
        # A denied capability attempt is more decisive than the generic call
        # wrapper that may have caught the resulting PermissionError.
        audit_overflow = boundary.audit_overflow if boundary is not None else False
        failure_origin = _worker_failure_origin(
            exc,
            phase=phase,
            audit_events=audit_events,
            audit_overflow=audit_overflow,
        )
        if failure_origin == "harness":
            failure_code = "UCM-E003-HARNESS_INCOMPLETE"
        elif audit_events or audit_overflow:
            failure_code = _classify_denied_audit(audit_events, request)
        elif isinstance(exc, CandidateCallViolation):
            failure_code = exc.failure_code
        else:
            failure_code = "UCM-F008-STATE_NOT_CLOSED"
        envelope = {
            "protocol": WORKER_PROTOCOL,
            "ok": False,
            "failure_origin": failure_origin,
            "error": {
                "failure_code": failure_code,
                "type": type(exc).__name__,
                "message": _bounded_evidence_text(str(exc)),
            },
            "audit_events": audit_events,
            "audit_overflow": audit_overflow,
            "captured_stdout": capture.captured_stdout,
            "captured_stderr": capture.captured_stderr,
            "worker_pid": os.getpid(),
            **_inventory_binding_wire(inventory),
        }
        try:
            protocol.emit(envelope)
        except Exception:
            return 3
        return 2


def _session_worker_main(
    harness_root_text: str,
    bundle_root_text: str,
    module_name: str,
    qualname: str,
    import_allowlist_path: str,
    prepared_marker_path: str,
    prepared_nonce: str,
) -> int:
    """Serve one request at a time after a PREPARED/GO handshake."""

    protocol_stdin = sys.stdin.buffer
    protocol = _WorkerProtocolChannel()
    audit_events: list[dict[str, Any]] = []
    current_capture = _CandidateOutputCapture()
    current_request: CandidateRequest | None = None
    current_index: int | None = None
    completed = 0
    boundary: _CandidateAuditBoundary | None = None
    inventory: _WorkerImportInventory | None = None
    boundary_call: Any = None
    boundary_call_code: Any = None
    boundary_finish_import: Any = None
    boundary_finish_import_func: Any = None
    boundary_finish_import_code: Any = None
    boundary_commit_attestation: Any = None
    boundary_commit_func: Any = None
    boundary_commit_code: Any = None
    boundary_verify_func: Any = None
    boundary_verify_code: Any = None
    harness_verifier: Any = None
    harness_verifier_code: Any = None
    runtime_verifier: Any = None
    runtime_verifier_code: Any = None
    candidate_verifier: Any = None
    candidate_verifier_code: Any = None
    phase = "manifest"

    def set_phase(value: str) -> None:
        nonlocal phase
        if value not in _WORKER_FAILURE_PHASES:
            raise ProtocolViolation("worker phase escaped its closed taxonomy")
        phase = value

    def emit(value: dict[str, Any]) -> None:
        protocol.emit(value)

    def emit_error(exc: Exception) -> int:
        audit_overflow = boundary.audit_overflow if boundary is not None else False
        failure_origin = _worker_failure_origin(
            exc,
            phase=phase,
            audit_events=audit_events,
            audit_overflow=audit_overflow,
        )
        if failure_origin == "harness":
            failure_code = "UCM-E003-HARNESS_INCOMPLETE"
        elif audit_events or audit_overflow:
            failure_code = _classify_denied_audit(audit_events, current_request)
        elif isinstance(exc, CandidateCallViolation):
            failure_code = exc.failure_code
        else:
            failure_code = "UCM-F008-STATE_NOT_CLOSED"
        output = {
            "protocol": SESSION_WORKER_PROTOCOL,
            "type": "error",
            "ok": False,
            "failure_origin": failure_origin,
            "error": {
                "failure_code": failure_code,
                "type": type(exc).__name__,
                "message": _bounded_evidence_text(str(exc)),
                "request_index": current_index,
            },
            "audit_events": audit_events,
            "audit_overflow": audit_overflow,
            "captured_stdout": current_capture.captured_stdout,
            "captured_stderr": current_capture.captured_stderr,
            "worker_pid": os.getpid(),
            **_inventory_binding_wire(inventory),
        }
        try:
            emit(output)
        except Exception:
            return 3
        return 2

    def read_parent_frame(label: str) -> dict[str, Any]:
        line = protocol_stdin.readline(MAX_SESSION_FRAME_BYTES + 2)
        if not line:
            raise ProtocolViolation(f"sequential parent closed before {label}")
        if len(line) > MAX_SESSION_FRAME_BYTES or not line.endswith(b"\n"):
            raise ProtocolViolation(f"sequential parent sent an oversized {label}")
        body = line[:-1]
        if b"\n" in body or b"\r" in body:
            raise ProtocolViolation(f"sequential {label} has invalid delimiters")
        try:
            frame = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation(f"sequential {label} is malformed JSON") from exc
        if type(frame) is not dict or canonical_json_bytes(frame) != line:
            raise ProtocolViolation(f"sequential {label} is not canonical JSON")
        if frame.get("protocol") != SESSION_REQUEST_PROTOCOL:
            raise ProtocolViolation(f"unknown sequential {label} protocol")
        return frame

    try:
        worker_cwd = Path.cwd().resolve()
        prepared_marker = Path(prepared_marker_path).resolve()
        if (
            prepared_marker.parent != worker_cwd
            or re.fullmatch(r"[0-9a-f]{32}", prepared_nonce) is None
        ):
            raise ProtocolViolation(
                "sequential PREPARED-attestation parameters are malformed"
            )
        inventory = _read_import_allowlist_manifest(
            import_allowlist_path, bundle_root_text, harness_root_text
        )
        entrypoint = CandidateEntrypoint(
            bundle_root=Path(bundle_root_text),
            module=module_name,
            qualname=qualname,
        )
        _verify_worker_harness_inventory_bytes(inventory)
        _verify_worker_runtime_inventory_bytes(inventory)
        _verify_worker_inventory_bytes(inventory, entrypoint.bundle_root)
        boundary = _CandidateAuditBoundary(inventory.allowed_files)
        audit_events = boundary.audit_events
        boundary_call = type(boundary).__call__
        boundary_call_code = boundary_call.__code__
        boundary_finish_import = boundary.finish_import
        boundary_finish_import_func = type(boundary).finish_import
        boundary_finish_import_code = boundary_finish_import_func.__code__
        boundary_commit_attestation = boundary.commit_attestation
        boundary_commit_func = type(boundary).commit_attestation
        boundary_commit_code = boundary_commit_func.__code__
        boundary_verify_func = type(boundary).verify_inventory_bytes
        boundary_verify_code = boundary_verify_func.__code__
        harness_verifier = _verify_worker_harness_inventory_bytes
        harness_verifier_code = harness_verifier.__code__
        runtime_verifier = _verify_worker_runtime_inventory_bytes
        runtime_verifier_code = runtime_verifier.__code__
        candidate_verifier = _verify_worker_inventory_bytes
        candidate_verifier_code = candidate_verifier.__code__

        def verify_bound_inventory(*, rehash: bool) -> None:
            if (
                type(boundary).verify_inventory_bytes is not boundary_verify_func
                or boundary_verify_func.__code__ is not boundary_verify_code
                or type(boundary).commit_attestation is not boundary_commit_func
                or boundary_commit_func.__code__ is not boundary_commit_code
                or _verify_worker_harness_inventory_bytes is not harness_verifier
                or harness_verifier.__code__ is not harness_verifier_code
                or _verify_worker_runtime_inventory_bytes is not runtime_verifier
                or runtime_verifier.__code__ is not runtime_verifier_code
                or _verify_worker_inventory_bytes is not candidate_verifier
                or candidate_verifier.__code__ is not candidate_verifier_code
            ):
                raise ProtocolViolation(
                    "candidate tampered with an inventory verifier"
                )
            if rehash:
                boundary._inventory_verification_phase = True
                try:
                    harness_verifier(inventory)
                    runtime_verifier(inventory)
                    candidate_verifier(inventory, entrypoint.bundle_root)
                finally:
                    boundary._inventory_verification_phase = False

        sys.addaudithook(boundary.__call__)
        phase = "harness-prepared-attestation"
        boundary_commit_attestation(
            prepared_marker, prepared_nonce, "sequential harness-prepared"
        )
        emit(
            {
                "protocol": SESSION_WORKER_PROTOCOL,
                "type": "prepared",
                "ok": True,
                "failure_origin": None,
                "worker_pid": os.getpid(),
                "audit_events": audit_events,
                "audit_overflow": boundary.audit_overflow,
                **_inventory_binding_wire(inventory),
            }
        )
        sys.argv[9] = "<retired-prepared-marker>"
        sys.argv[10] = "<retired-prepared-nonce>"
        prepared_marker_path = ""
        prepared_nonce = ""
        prepared_marker = None
        phase = "go-parser"
        go_frame = _exact_keys(
            read_parent_frame("GO frame"),
            required=frozenset({"protocol", "type", "index"}),
            label="sequential GO frame",
        )
        if go_frame["type"] != "go" or go_frame["index"] != 0:
            raise ProtocolViolation("sequential GO frame is invalid")
        del go_frame

        with current_capture:
            set_phase("candidate-import")
            try:
                candidate = _load_candidate(entrypoint, inventory)
            except BaseException:
                set_phase("harness-post-import")
                if (
                    type(boundary).finish_import is not boundary_finish_import_func
                    or boundary_finish_import_func.__code__
                    is not boundary_finish_import_code
                ):
                    raise ProtocolViolation(
                        "candidate tampered with the import-phase boundary"
                    )
                boundary_finish_import()
                set_phase("candidate-import")
                raise
            else:
                set_phase("harness-post-import")
                if (
                    type(boundary).finish_import is not boundary_finish_import_func
                    or boundary_finish_import_func.__code__
                    is not boundary_finish_import_code
                ):
                    raise ProtocolViolation(
                        "candidate tampered with the import-phase boundary"
                    )
                boundary_finish_import()
        set_phase("candidate-validation")
        current_capture.require_valid()
        if (
            type(boundary).__call__ is not boundary_call
            or boundary_call.__code__ is not boundary_call_code
        ):
            raise ProtocolViolation("candidate tampered with the Python audit hook")
        if audit_events or boundary.audit_overflow:
            set_phase("candidate-import")
            raise PermissionError("candidate caught a denied import capability")
        set_phase("harness-post-import")
        verify_bound_inventory(rehash=True)
        emit(
            {
                "protocol": SESSION_WORKER_PROTOCOL,
                "type": "ready",
                "ok": True,
                "failure_origin": None,
                "worker_pid": os.getpid(),
                "audit_events": audit_events,
                "audit_overflow": boundary.audit_overflow,
                "captured_stdout": current_capture.captured_stdout,
                "captured_stderr": current_capture.captured_stderr,
                **_inventory_binding_wire(inventory),
            }
        )
    except Exception as exc:
        return emit_error(exc)

    while completed < MAX_SESSION_REQUESTS:
        current_capture = _CandidateOutputCapture()
        current_request = None
        current_index = completed
        try:
            phase = "request-parser"
            frame = read_parent_frame("request frame")
            frame_type = frame.get("type")
            if frame_type == "close":
                frame = _exact_keys(
                    frame,
                    required=frozenset({"protocol", "type", "index"}),
                    label="sequential close request",
                )
                if frame["index"] != completed:
                    raise ProtocolViolation("sequential close index is out of order")
                phase = "harness-postcheck"
                verify_bound_inventory(rehash=True)
                emit(
                    {
                        "protocol": SESSION_WORKER_PROTOCOL,
                        "type": "closed",
                        "ok": True,
                        "worker_pid": os.getpid(),
                        "requests_completed": completed,
                    }
                )
                return 0
            frame = _exact_keys(
                frame,
                required=frozenset({"protocol", "type", "index", "request"}),
                label="sequential request frame",
            )
            if frame_type != "request" or frame["index"] != completed:
                raise ProtocolViolation("sequential request index is out of order")
            request_wire = frame["request"]
            current_request = request_from_wire(request_wire)
            audit_start = len(audit_events)
            audit_overflow_start = boundary.audit_overflow
            with current_capture:
                set_phase("harness-response-finalization")
                response = _dispatch_candidate(
                    candidate, current_request, phase_hook=set_phase
                )
            set_phase("candidate-validation")
            current_capture.require_valid()
            if (
                type(boundary).__call__ is not boundary_call
                or boundary_call.__code__ is not boundary_call_code
            ):
                raise ProtocolViolation("candidate tampered with the Python audit hook")
            if (
                len(audit_events) != audit_start
                or boundary.audit_overflow != audit_overflow_start
            ):
                set_phase("candidate-call")
                raise PermissionError("candidate caught a denied audited capability")
            set_phase("harness-postcheck")
            verify_bound_inventory(rehash=False)
            response_wire = response.to_wire()
            emit(
                {
                    "protocol": SESSION_WORKER_PROTOCOL,
                    "type": "result",
                    "ok": True,
                    "failure_origin": None,
                    "index": completed,
                    "response": response_wire,
                    "audit_events": audit_events[audit_start:],
                    "audit_overflow": (
                        boundary.audit_overflow != audit_overflow_start
                    ),
                    "captured_stdout": current_capture.captured_stdout,
                    "captured_stderr": current_capture.captured_stderr,
                    **_inventory_binding_wire(inventory),
                }
            )
            completed += 1
            del response_wire, response, request_wire, frame, frame_type
            current_request = None
            current_index = None
        except Exception as exc:
            return emit_error(exc)
    return emit_error(ProtocolViolation("sequential request count exceeds limit"))


@dataclass(frozen=True, slots=True)
class HeadExecutionRecord:
    operation: Operation
    consumed_state_hash: str
    request_digest: str
    response_digest: str
    seed: int
    isolation: str
    import_inventory_digest: str | None = None
    harness_bundle_digest: str | None = None
    candidate_bundle_digest: str | None = None
    candidate_model_digest: str | None = None
    module_origin: str | None = None

    def __post_init__(self) -> None:
        if self.operation not in {Operation.DIAGNOSE, Operation.ROLLOUT}:
            raise ProtocolViolation("head record operation must be a readout")
        _seed(self.seed)
        for label, value in (
            ("import_inventory_digest", self.import_inventory_digest),
            ("harness_bundle_digest", self.harness_bundle_digest),
            ("candidate_bundle_digest", self.candidate_bundle_digest),
            ("candidate_model_digest", self.candidate_model_digest),
        ):
            if value is not None and (
                type(value) is not str
                or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
            ):
                raise ProtocolViolation(f"{label} must be a SHA-256 digest or null")
        if self.module_origin is not None and (
            type(self.module_origin) is not str
            or not self.module_origin
            or Path(self.module_origin).is_absolute()
            or Path(self.module_origin).as_posix() != self.module_origin
            or ".." in Path(self.module_origin).parts
        ):
            raise ProtocolViolation("module_origin must be a canonical relative path")

    def to_wire(self) -> dict[str, Any]:
        return {
            "operation": self.operation.value,
            "consumed_state_hash": self.consumed_state_hash,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "seed": self.seed,
            "isolation": self.isolation,
            "import_inventory_digest": self.import_inventory_digest,
            "harness_bundle_digest": self.harness_bundle_digest,
            "candidate_bundle_digest": self.candidate_bundle_digest,
            "candidate_model_digest": self.candidate_model_digest,
            "module_origin": self.module_origin,
        }


@dataclass(frozen=True, slots=True)
class HeadExecution:
    outcome: InvocationOutcome
    record: HeadExecutionRecord


def _verify_head_candidate_binding(
    outcome: InvocationOutcome, sealed_state: SealedState
) -> None:
    """Close a readout over the candidate/model that produced its state."""

    candidate_digest = outcome.candidate_bundle_digest
    model_digest = outcome.candidate_model_digest
    if candidate_digest is None and model_digest is None:
        # Explicit development-only compatibility for InProcessExecutor.  Any
        # executor that claims one execution binding must claim and close both.
        if (
            outcome.isolation == "in-process-none"
            and outcome.worker_pid is None
            and outcome.import_inventory_digest is None
            and outcome.harness_bundle_digest is None
            and outcome.module_origin is None
        ):
            return
        raise ProtocolViolation(
            "only an explicitly unbound in-process head may omit candidate/model bindings"
        )
    if candidate_digest is None or model_digest is None:
        raise ProtocolViolation(
            "head executor returned a partial candidate/model binding"
        )
    if (
        candidate_digest != sealed_state.record.candidate_bundle_digest
        or model_digest != sealed_state.record.model_digest
    ):
        raise ProtocolViolation(
            "head executor candidate/model binding does not match the sealed state"
        )


def invoke_diagnose(
    executor: CandidateExecutor,
    sealed_state: SealedState,
    query: DiagnosisQuery,
    *,
    seed: int,
) -> HeadExecution:
    if type(sealed_state) is not SealedState:
        raise ProtocolViolation("diagnose requires a SealedState")
    outcome = executor.invoke(DiagnoseRequest(sealed_state.candidate_input, query, seed))
    if type(outcome.response) is not DiagnoseResponse:
        raise ProtocolViolation("executor returned a non-diagnosis response")
    _verify_head_candidate_binding(outcome, sealed_state)
    return HeadExecution(
        outcome=outcome,
        record=HeadExecutionRecord(
            operation=Operation.DIAGNOSE,
            consumed_state_hash=sealed_state.record.state_hash,
            request_digest=outcome.request_digest,
            response_digest=outcome.response_digest,
            seed=seed,
            isolation=outcome.isolation,
            import_inventory_digest=outcome.import_inventory_digest,
            harness_bundle_digest=outcome.harness_bundle_digest,
            candidate_bundle_digest=outcome.candidate_bundle_digest,
            candidate_model_digest=outcome.candidate_model_digest,
            module_origin=outcome.module_origin,
        ),
    )


def invoke_rollout(
    executor: CandidateExecutor,
    sealed_state: SealedState,
    query: RolloutQuery,
    *,
    seed: int,
) -> HeadExecution:
    if type(sealed_state) is not SealedState:
        raise ProtocolViolation("rollout requires a SealedState")
    outcome = executor.invoke(RolloutRequest(sealed_state.candidate_input, query, seed))
    if type(outcome.response) is not RolloutResponse:
        raise ProtocolViolation("executor returned a non-rollout response")
    _verify_head_candidate_binding(outcome, sealed_state)
    return HeadExecution(
        outcome=outcome,
        record=HeadExecutionRecord(
            operation=Operation.ROLLOUT,
            consumed_state_hash=sealed_state.record.state_hash,
            request_digest=outcome.request_digest,
            response_digest=outcome.response_digest,
            seed=seed,
            isolation=outcome.isolation,
            import_inventory_digest=outcome.import_inventory_digest,
            harness_bundle_digest=outcome.harness_bundle_digest,
            candidate_bundle_digest=outcome.candidate_bundle_digest,
            candidate_model_digest=outcome.candidate_model_digest,
            module_origin=outcome.module_origin,
        ),
    )


def assert_shared_state_fanout(executions: tuple[HeadExecution, ...]) -> str:
    if type(executions) is not tuple or not executions:
        raise ProtocolViolation("fan-out executions must be a non-empty tuple")
    hashes = {execution.record.consumed_state_hash for execution in executions}
    if len(hashes) != 1:
        raise ProtocolViolation(
            "harness-owned head records consumed different sealed states: "
            f"{sorted(hashes)!r}"
        )
    return next(iter(hashes))
