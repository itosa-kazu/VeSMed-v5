"""Candidate process protocol for the isolated UCM benchmark.

The protocol deliberately separates the two state-producing operations
(``initialize`` and ``update``) from the pure readout heads (``diagnose`` and
``rollout``).  A candidate never supplies a trusted state hash: the harness
seals returned inert bytes with :mod:`prototype.unified_map.state`.

``FreshProcessExecutor`` is a portable minimum closure test.  It starts a new
Python interpreter in an empty temporary working directory, passes the request
through stdin, uses a small environment allow-list, and denies Python-audited
file/network/process access while the candidate method runs.  This is useful
evidence for Python candidates, but it is not a Windows kernel sandbox and it
does not prove semantic unity inside an opaque payload.
"""

from __future__ import annotations

import base64
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, TypeAlias

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
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
WORKER_PROTOCOL = "ucm-python-worker-result/1"
MAX_STATE_PAYLOAD_BYTES = 256 * 1024 * 1024


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
    return {
        "codec": payload.codec,
        "schema_version": payload.schema_version,
        "state_class": payload.state_class.value,
        "payload_b64": base64.b64encode(payload.payload).decode("ascii"),
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
            missing = set(request.query.requested_observables) - set(
                response.result.observable_predictions
            )
            if missing:
                raise CandidateCallViolation(
                    "UCM-F022-INVALID_DISTRIBUTION",
                    f"rollout response omitted observables: {sorted(missing)!r}",
                )


def _dispatch_candidate(
    candidate: UCMCandidateV1, request: CandidateRequest
) -> CandidateResponse:
    before = canonical_json_bytes(request.to_wire())
    try:
        if isinstance(request, InitializeRequest):
            state = candidate.initialize(
                request.history, inference_seed=request.seed
            )
            response: CandidateResponse = StateResponse(Operation.INITIALIZE, state)
        elif isinstance(request, UpdateRequest):
            state = candidate.update(
                request.state,
                request.delta,
                inference_seed=request.seed,
            )
            response = StateResponse(Operation.UPDATE, state)
        elif isinstance(request, DiagnoseRequest):
            result = candidate.diagnose(
                request.state,
                request.query,
                query_seed=request.seed,
            )
            response = DiagnoseResponse(result)
        else:
            result = candidate.rollout(
                request.state,
                request.query,
                query_seed=request.seed,
            )
            response = RolloutResponse(result)
    except CandidateCallViolation:
        raise
    except ProtocolViolation:
        raise
    except Exception as exc:
        raise CandidateCallViolation(
            "UCM-F008-STATE_NOT_CLOSED",
            f"candidate operation {request.operation.value} failed: "
            f"{type(exc).__name__}: {exc}",
        ) from exc
    after = canonical_json_bytes(request.to_wire())
    if after != before:
        code = (
            "UCM-F012-QUERY_MUTATES_FACT"
            if request.operation in {Operation.DIAGNOSE, Operation.ROLLOUT}
            else "UCM-F019-UPDATE_INCONSISTENT"
        )
        raise CandidateCallViolation(code, "candidate mutated its request/state/query")
    _validate_response_for_request(request, response)
    return response


@dataclass(frozen=True, slots=True)
class CandidateEntrypoint:
    bundle_root: Path
    module: str
    qualname: str

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


def _load_candidate(entrypoint: CandidateEntrypoint) -> UCMCandidateV1:
    root_text = str(entrypoint.bundle_root)
    added = root_text not in sys.path
    if added:
        sys.path.insert(0, root_text)
    try:
        module = importlib.import_module(entrypoint.module)
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
    captured_stdout: str = ""
    captured_stderr: str = ""
    worker_pid: int | None = None


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
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            response = _dispatch_candidate(self.candidate, request)
        return InvocationOutcome(
            response=response,
            request_digest=digest_json(request.to_wire()),
            response_digest=digest_json(response.to_wire()),
            isolation="in-process-none",
            captured_stdout=stdout.getvalue(),
            captured_stderr=stderr.getvalue(),
        )


class WorkerInvocationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_code: str,
        audit_events: tuple[dict[str, Any], ...] = (),
        captured_stdout: str = "",
        captured_stderr: str = "",
        returncode: int | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_code = failure_code
        self.audit_events = audit_events
        self.captured_stdout = captured_stdout
        self.captured_stderr = captured_stderr
        self.returncode = returncode


_WORKER_BOOTSTRAP = r"""
import sys
root = sys.argv[1]
if root not in sys.path:
    sys.path.insert(0, root)
from prototype.unified_map.candidate_protocol import _worker_main
raise SystemExit(_worker_main(sys.argv[2], sys.argv[3]))
"""


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
        if type(timeout_seconds) not in {int, float} or timeout_seconds <= 0:
            raise ProtocolViolation("timeout_seconds must be positive")
        self.entrypoint = entrypoint
        self.timeout_seconds = float(timeout_seconds)
        self.python_executable = python_executable or sys.executable

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
        request_bytes = canonical_json_bytes(request.to_wire())
        with tempfile.TemporaryDirectory(prefix="ucm-fresh-worker-") as raw_temp:
            temp_root = Path(raw_temp).resolve()
            command = [
                self.python_executable,
                "-I",
                "-S",
                "-c",
                _WORKER_BOOTSTRAP,
                str(self.entrypoint.bundle_root),
                self.entrypoint.module,
                self.entrypoint.qualname,
            ]
            try:
                completed = subprocess.run(
                    command,
                    input=request_bytes,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=temp_root,
                    env=self._worker_env(temp_root),
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                raise WorkerInvocationError(
                    "fresh candidate worker timed out",
                    failure_code="UCM-F008-STATE_NOT_CLOSED",
                    captured_stdout=(exc.stdout or b"").decode("utf-8", "replace"),
                    captured_stderr=(exc.stderr or b"").decode("utf-8", "replace"),
                ) from exc
        stderr_text = completed.stderr.decode("utf-8", "replace")
        try:
            worker = json.loads(completed.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkerInvocationError(
                "fresh candidate worker returned a malformed envelope",
                failure_code="UCM-F008-STATE_NOT_CLOSED",
                captured_stdout=completed.stdout.decode("utf-8", "replace"),
                captured_stderr=stderr_text,
                returncode=completed.returncode,
            ) from exc
        if type(worker) is not dict or worker.get("protocol") != WORKER_PROTOCOL:
            raise WorkerInvocationError(
                "fresh candidate worker returned the wrong protocol",
                failure_code="UCM-F008-STATE_NOT_CLOSED",
                captured_stdout=completed.stdout.decode("utf-8", "replace"),
                captured_stderr=stderr_text,
                returncode=completed.returncode,
            )
        audit_events_raw = worker.get("audit_events", [])
        audit_events = (
            tuple(audit_events_raw) if type(audit_events_raw) is list else tuple()
        )
        if completed.returncode != 0 or worker.get("ok") is not True:
            error = worker.get("error")
            if type(error) is not dict:
                error = {}
            raise WorkerInvocationError(
                str(error.get("message", "fresh candidate worker failed")),
                failure_code=str(
                    error.get("failure_code", "UCM-F008-STATE_NOT_CLOSED")
                ),
                audit_events=audit_events,
                captured_stdout=str(worker.get("captured_stdout", "")),
                captured_stderr=str(worker.get("captured_stderr", ""))
                + stderr_text,
                returncode=completed.returncode,
            )
        response = response_from_wire(worker.get("response"))
        _validate_response_for_request(request, response)
        return InvocationOutcome(
            response=response,
            request_digest=digest_json(request.to_wire()),
            response_digest=digest_json(response.to_wire()),
            isolation="fresh-python-process-audit-v1",
            audit_events=audit_events,
            captured_stdout=str(worker.get("captured_stdout", "")),
            captured_stderr=str(worker.get("captured_stderr", "")) + stderr_text,
            worker_pid=worker.get("worker_pid"),
        )


_DENIED_AUDIT_EVENTS = frozenset(
    {
        "open",
        "os.system",
        "os.spawn",
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
    try:
        text = repr(value)
    except Exception:
        text = f"<{type(value).__name__}>"
    return text[:512]


def _classify_denied_audit(
    audit_events: list[dict[str, Any]], request: CandidateRequest | None
) -> str:
    """Map a denied capability to the most specific registered failure code.

    The decision uses only the audited capability/path and request operation;
    it does not trust a candidate-provided label.  Generic head file access is
    history access, while explicit future/oracle/model paths retain their more
    decisive information-flow semantics.
    """

    joined = " ".join(
        str(part).lower()
        for row in audit_events
        for part in (row.get("event"), *row.get("args", []))
    )
    if any(token in joined for token in ("model", "checkpoint", "weights")) and any(
        token in joined for token in ("'w'", "'a'", "'x'", "'+'")
    ):
        return "UCM-F009-MODEL_MUTATION"
    if any(
        token in joined
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
        token in joined
        for token in ("actual-future", "actual_future", "future", "results")
    ):
        return "UCM-F001-FUTURE_LEAK"
    if request is not None and request.operation in {
        Operation.DIAGNOSE,
        Operation.ROLLOUT,
    }:
        return "UCM-F004-HEAD_HISTORY_ACCESS"
    return "UCM-F008-STATE_NOT_CLOSED"


def _worker_main(module_name: str, qualname: str) -> int:
    """Private subprocess entry point.  The parent parses only this envelope."""

    audit_events: list[dict[str, Any]] = []
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    request: CandidateRequest | None = None
    try:
        wire = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        request = request_from_wire(wire)
        root = Path.cwd()  # the empty isolated worker directory
        entrypoint = CandidateEntrypoint(
            bundle_root=Path(sys.path[0]),
            module=module_name,
            qualname=qualname,
        )
        candidate = _load_candidate(entrypoint)

        def audit_hook(event: str, args: tuple[Any, ...]) -> None:
            if event in _DENIED_AUDIT_EVENTS or event.startswith("winreg."):
                row = {"event": event, "args": [_audit_arg(arg) for arg in args]}
                audit_events.append(row)
                raise PermissionError(
                    f"UCM fresh worker denied audited capability: {event}"
                )

        sys.addaudithook(audit_hook)
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(
            captured_stderr
        ):
            response = _dispatch_candidate(candidate, request)
        envelope = {
            "protocol": WORKER_PROTOCOL,
            "ok": True,
            "response": response.to_wire(),
            "audit_events": audit_events,
            "captured_stdout": captured_stdout.getvalue(),
            "captured_stderr": captured_stderr.getvalue(),
            "worker_pid": os.getpid(),
            "worker_cwd_isolated": root == Path.cwd(),
        }
        sys.stdout.buffer.write(canonical_json_bytes(envelope))
        return 0
    except Exception as exc:
        # A denied capability attempt is more decisive than the generic call
        # wrapper that may have caught the resulting PermissionError.
        if audit_events:
            failure_code = _classify_denied_audit(audit_events, request)
        elif isinstance(exc, CandidateCallViolation):
            failure_code = exc.failure_code
        else:
            failure_code = "UCM-F008-STATE_NOT_CLOSED"
        envelope = {
            "protocol": WORKER_PROTOCOL,
            "ok": False,
            "error": {
                "failure_code": failure_code,
                "type": type(exc).__name__,
                "message": str(exc),
            },
            "audit_events": audit_events,
            "captured_stdout": captured_stdout.getvalue(),
            "captured_stderr": captured_stderr.getvalue(),
            "worker_pid": os.getpid(),
        }
        try:
            sys.stdout.buffer.write(canonical_json_bytes(envelope))
        except Exception:
            return 3
        return 2


@dataclass(frozen=True, slots=True)
class HeadExecutionRecord:
    operation: Operation
    consumed_state_hash: str
    request_digest: str
    response_digest: str
    seed: int
    isolation: str

    def __post_init__(self) -> None:
        if self.operation not in {Operation.DIAGNOSE, Operation.ROLLOUT}:
            raise ProtocolViolation("head record operation must be a readout")
        _seed(self.seed)

    def to_wire(self) -> dict[str, Any]:
        return {
            "operation": self.operation.value,
            "consumed_state_hash": self.consumed_state_hash,
            "request_digest": self.request_digest,
            "response_digest": self.response_digest,
            "seed": self.seed,
            "isolation": self.isolation,
        }


@dataclass(frozen=True, slots=True)
class HeadExecution:
    outcome: InvocationOutcome
    record: HeadExecutionRecord


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
    return HeadExecution(
        outcome=outcome,
        record=HeadExecutionRecord(
            operation=Operation.DIAGNOSE,
            consumed_state_hash=sealed_state.record.state_hash,
            request_digest=outcome.request_digest,
            response_digest=outcome.response_digest,
            seed=seed,
            isolation=outcome.isolation,
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
    return HeadExecution(
        outcome=outcome,
        record=HeadExecutionRecord(
            operation=Operation.ROLLOUT,
            consumed_state_hash=sealed_state.record.state_hash,
            request_digest=outcome.request_digest,
            response_digest=outcome.response_digest,
            seed=seed,
            isolation=outcome.isolation,
        ),
    )


def assert_shared_state_fanout(executions: tuple[HeadExecution, ...]) -> str:
    if type(executions) is not tuple or not executions:
        raise ProtocolViolation("fan-out executions must be a non-empty tuple")
    hashes = {execution.record.consumed_state_hash for execution in executions}
    if len(hashes) != 1:
        raise CandidateCallViolation(
            "UCM-F007-STATE_FANOUT_MISMATCH",
            f"heads consumed different sealed states: {sorted(hashes)!r}",
        )
    return next(iter(hashes))
