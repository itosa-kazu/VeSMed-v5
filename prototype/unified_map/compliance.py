"""Executable minimum compliance battery and deliberately malicious controls.

This module tests *operational state closure*: after ``initialize`` returns an
inert payload, fresh workers must be able to run every head and ``update`` from
that payload alone.  Passing this battery never upgrades an opaque candidate to
``semantic_unity=PASS``; source/dependency/behavioral audits remain necessary.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import os
import random
import signal
import zlib
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from .candidate_protocol import (
    CandidateCallViolation,
    CandidateEntrypoint,
    DiagnoseRequest,
    DiagnoseResponse,
    DiagnosisResult,
    FreshProcessExecutor,
    HeadExecution,
    InitializeRequest,
    InvocationOutcome,
    Operation,
    ResultStatus,
    RolloutRequest,
    RolloutResponse,
    RolloutResult,
    SequentialProcessExecutor,
    StateResponse,
    UpdateRequest,
    WorkerInvocationError,
    assert_shared_state_fanout,
    invoke_diagnose,
    invoke_rollout,
    request_from_wire,
    response_from_wire,
    _canonical_candidate_failure_code,
    _validate_response_for_request,
)
from .schema import (
    DiagnosisQuery,
    RolloutQuery,
    VisibleDelta,
    VisibleHistory,
    event_sort_key,
)
from .state import (
    CandidateStateInput,
    StateClass,
    StatePayload,
    seal_state,
)


class ComplianceVerdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    INCOMPLETE = "incomplete"


PORTABLE_SEMANTIC_PROBES = frozenset(
    {
        "full_history_disclosure",
        "update_consistency",
        "warm_future_old_cut",
    }
)
PORTABLE_SEMANTIC_PROBE_PROTOCOL = "ucm-portable-semantic-probes/4"
# Portable compliance probes launch a cold isolated interpreter and re-hash the
# code-owned authority surface.  Keep that budget source-bound here rather than
# embedding a machine-sensitive literal at individual probe call sites.
PORTABLE_COMPLIANCE_PROBE_TIMEOUT_SECONDS = 20.0
SEMANTIC_ABS_TOLERANCE = 1e-9
SEMANTIC_REL_TOLERANCE = 0.0
UPDATE_CONSISTENCY_LINEAGE_XOR_MASK = 0x6A09E667F3BCC909
_HISTORY_MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
_HISTORY_MAX_DEPTH = 16
_HISTORY_MAX_NODES = 4096
_HISTORY_MAX_STRINGS = 256
_HISTORY_MAX_STRING_CHARS = 2 * 1024 * 1024
_HISTORY_MAX_DECODE_ATTEMPTS = 64
_HISTORY_MAX_TOTAL_COMPRESSED_BYTES = 2 * 1024 * 1024
_HISTORY_MAX_SINGLE_EXPANDED_BYTES = 4 * 1024 * 1024
_HISTORY_MAX_TOTAL_EXPANDED_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ComplianceFinding:
    gate: str
    verdict: ComplianceVerdict
    failure_code: str | None
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.gate) is not str or not self.gate:
            raise ProtocolViolation("finding gate must be non-empty")
        if type(self.verdict) is not ComplianceVerdict:
            raise ProtocolViolation("finding verdict must be ComplianceVerdict")
        if self.verdict is ComplianceVerdict.FAIL and not self.failure_code:
            raise ProtocolViolation("failed finding requires a failure code")
        if type(self.evidence) is not dict:
            raise ProtocolViolation("finding evidence must be an exact dict")


@dataclass(frozen=True, slots=True)
class ComplianceReport:
    candidate: str
    operational_state_closure: ComplianceVerdict
    semantic_unity: ComplianceVerdict
    isolation_completeness: ComplianceVerdict
    isolation_assurance: str
    findings: tuple[ComplianceFinding, ...]
    head_records: tuple[dict[str, Any], ...] = ()
    _request_record_bytes: tuple[bytes, ...] = field(
        default=(), repr=False
    )
    candidate_bundle_digest: str | None = None
    candidate_model_digest: str | None = None
    harness_bundle_digest: str | None = None
    import_inventory_digest: str | None = None
    module_origin: str | None = None

    @property
    def request_records(self) -> tuple[dict[str, Any], ...]:
        # Return a fresh decoded view.  The authoritative snapshot is the
        # immutable canonical byte tuple, so mutating a consumer's nested dict
        # cannot rewrite an already materialized compliance report.
        return tuple(
            json.loads(encoded.decode("utf-8"))
            for encoded in self._request_record_bytes
        )

    @property
    def request_records_digest(self) -> str:
        return digest_json(
            {
                "protocol": "ucm-compliance-request-records/1",
                "records": list(self.request_records),
            }
        )

    @property
    def failure_codes(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                finding.failure_code
                for finding in self.findings
                if finding.verdict is ComplianceVerdict.FAIL
                and finding.failure_code is not None
            )
        )

    @property
    def operationally_eligible(self) -> bool:
        return self.operational_state_closure is ComplianceVerdict.PASS


def _binding_digest(value: Any, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
    ):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    if any(character not in "0123456789abcdef" for character in value[7:]):
        raise ProtocolViolation(f"{label} must be lowercase hexadecimal")
    return value


def _binding_module_origin(value: Any, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a non-empty exact string")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or path.as_posix() != value
        or "\\" in value
        or any(part in {"", ".", ".."} or ":" in part for part in path.parts)
    ):
        raise ProtocolViolation(f"{label} must be a canonical bundle-relative POSIX path")
    return value


@dataclass(slots=True)
class _ExecutionBindingCollector:
    """Require every worker call to use one exact candidate snapshot."""

    candidate_bundle_digest: str | None = None
    candidate_model_digest: str | None = None
    harness_bundle_digest: str | None = None
    import_inventory_digest: str | None = None
    module_origin: str | None = None
    observed: int = 0
    violations: list[str] = field(default_factory=list)
    request_records: list[dict[str, Any]] = field(default_factory=list)

    def observe(self, value: Any, *, allow_missing: bool = False) -> None:
        raw = {
            "candidate_bundle_digest": getattr(
                value, "candidate_bundle_digest", None
            ),
            "candidate_model_digest": getattr(value, "candidate_model_digest", None),
            "harness_bundle_digest": getattr(value, "harness_bundle_digest", None),
            "import_inventory_digest": getattr(
                value, "import_inventory_digest", None
            ),
            "module_origin": getattr(value, "module_origin", None),
        }
        if all(item is None for item in raw.values()) and allow_missing:
            return
        try:
            bundle = _binding_digest(
                raw["candidate_bundle_digest"], "worker candidate_bundle_digest"
            )
            model = _binding_digest(
                raw["candidate_model_digest"], "worker candidate_model_digest"
            )
            harness = _binding_digest(
                raw["harness_bundle_digest"], "worker harness_bundle_digest"
            )
            inventory = _binding_digest(
                raw["import_inventory_digest"], "worker import_inventory_digest"
            )
            origin = _binding_module_origin(
                raw["module_origin"], "worker module_origin"
            )
        except ProtocolViolation as error:
            self.violations.append(str(error))
            return

        self.observed += 1
        if self.candidate_bundle_digest is None:
            self.candidate_bundle_digest = bundle
            self.candidate_model_digest = model
            self.harness_bundle_digest = harness
            self.import_inventory_digest = inventory
            self.module_origin = origin
            return
        if bundle != self.candidate_bundle_digest:
            self.violations.append("candidate bundle digest drifted across worker calls")
        if model != self.candidate_model_digest:
            self.violations.append("candidate model digest drifted across worker calls")
        if harness != self.harness_bundle_digest:
            self.violations.append("harness bundle digest drifted across worker calls")
        if inventory != self.import_inventory_digest:
            self.violations.append("import inventory digest drifted across worker calls")
        if origin != self.module_origin:
            self.violations.append("module origin drifted across worker calls")

    @property
    def complete(self) -> bool:
        return (
            self.observed > 0
            and not self.violations
            and self.candidate_bundle_digest is not None
            and self.candidate_model_digest is not None
            and self.harness_bundle_digest is not None
            and self.import_inventory_digest is not None
            and self.module_origin is not None
        )


class _BindingObservedExecutor:
    def __init__(
        self,
        delegate: Any,
        collector: _ExecutionBindingCollector,
        *,
        execution_mode: str = "fresh",
    ) -> None:
        if execution_mode not in {"fresh", "sequential"}:
            raise ProtocolViolation("unknown observed execution mode")
        self._delegate = delegate
        self._collector = collector
        self._execution_mode = execution_mode

    def invoke(self, request: Any) -> InvocationOutcome:
        frozen = _freeze_observed_request(request)
        try:
            outcome = self._delegate.invoke(frozen.request)
        except WorkerInvocationError as error:
            self._collector.observe(
                error,
                allow_missing=(
                    getattr(error, "failure_origin", "harness") != "candidate"
                ),
            )
            normalized = _record_observed_error(
                self._collector,
                frozen,
                error,
                execution_mode=self._execution_mode,
            )
            raise normalized
        except Exception as error:
            normalized = _observed_harness_error(
                error,
                frozen=frozen,
                message="observed candidate invocation escaped its worker envelope",
            )
            _record_observed_error(
                self._collector,
                frozen,
                normalized,
                execution_mode=self._execution_mode,
            )
            raise normalized from error
        self._collector.observe(outcome)
        try:
            return _record_observed_success(
                self._collector,
                frozen,
                outcome,
                execution_mode=self._execution_mode,
            )
        except WorkerInvocationError as error:
            raise error
        except Exception as error:
            normalized = _observed_harness_error(
                error,
                frozen=frozen,
                outcome=outcome,
                message="observed invocation transcript validation incomplete",
            )
            _record_observed_error(
                self._collector,
                frozen,
                normalized,
                execution_mode=self._execution_mode,
                response=_best_effort_response_evidence(outcome),
            )
            raise normalized from error


@dataclass(frozen=True, slots=True)
class _FrozenObservedRequest:
    request: Any
    wire: dict[str, Any]
    encoded: bytes
    digest: str
    operation: str
    seed: int


def _freeze_observed_request(request: Any) -> _FrozenObservedRequest:
    encoded = canonical_json_bytes(request.to_wire())
    wire = json.loads(encoded.decode("utf-8"))
    # Keep the retained wire and the delegate's typed object disjoint.  Some
    # typed schema leaves contain mutable JSON dicts; a hostile delegate must
    # not be able to rewrite the already captured transcript through aliases.
    frozen = request_from_wire(json.loads(encoded.decode("utf-8")))
    return _FrozenObservedRequest(
        request=frozen,
        wire=wire,
        encoded=encoded,
        digest=digest_bytes(encoded),
        operation=frozen.operation.value,
        seed=frozen.seed,
    )


def _binding_error_kwargs(value: Any) -> dict[str, Any]:
    return {
        "import_inventory_digest": getattr(
            value, "import_inventory_digest", None
        ),
        "harness_bundle_digest": getattr(value, "harness_bundle_digest", None),
        "candidate_bundle_digest": getattr(
            value, "candidate_bundle_digest", None
        ),
        "candidate_model_digest": getattr(
            value, "candidate_model_digest", None
        ),
        "module_origin": getattr(value, "module_origin", None),
    }


def _observed_harness_error(
    error: BaseException,
    *,
    frozen: _FrozenObservedRequest,
    message: str,
    outcome: Any | None = None,
) -> WorkerInvocationError:
    source = outcome if outcome is not None else error
    return WorkerInvocationError(
        f"{message}: {type(error).__name__}: {error}",
        failure_code="UCM-E003-HARNESS_INCOMPLETE",
        failure_origin="harness",
        request_digest=frozen.digest,
        request_fully_sent=bool(
            getattr(error, "request_fully_sent", outcome is not None)
        ),
        received_request_digest=getattr(
            source, "received_request_digest", None
        ),
        **_binding_error_kwargs(source),
    )


def _request_record(
    frozen: _FrozenObservedRequest,
    *,
    execution_mode: str,
    status: str,
    request_fully_sent: bool,
    received_request_digest: str | None,
    response_wire: dict[str, Any] | None,
    response_digest: str | None,
    failure_origin: str | None,
    failure_code: str | None,
) -> dict[str, Any]:
    # This exact closed schema is consumed by typed mutation evidence.  Do not
    # add candidate-visible harness state hashes here: full request/response
    # wires carry the candidate-visible state lineage, while harness seals are
    # bound separately by the runner.
    return {
        "operation": frozen.operation,
        "seed": frozen.seed,
        "execution_mode": execution_mode,
        "status": status,
        "request_wire": frozen.wire,
        "request_digest": frozen.digest,
        "request_fully_sent": request_fully_sent,
        "received_request_digest": received_request_digest,
        "response_wire": response_wire,
        "response_digest": response_digest,
        "failure_origin": failure_origin,
        "failure_code": failure_code,
    }


_REQUEST_RECORD_KEYS = frozenset(
    {
        "operation",
        "seed",
        "execution_mode",
        "status",
        "request_wire",
        "request_digest",
        "request_fully_sent",
        "received_request_digest",
        "response_wire",
        "response_digest",
        "failure_origin",
        "failure_code",
    }
)


def _validated_request_record_bytes(value: object) -> bytes:
    if type(value) is not dict or frozenset(value) != _REQUEST_RECORD_KEYS:
        raise ProtocolViolation(
            "request record must use the exact closed field set"
        )
    operation = value["operation"]
    seed = value["seed"]
    if operation not in {item.value for item in Operation}:
        raise ProtocolViolation("request record operation is invalid")
    if type(seed) is not int or not 0 <= seed < 2**64:
        raise ProtocolViolation("request record seed is invalid")
    if value["execution_mode"] not in {"fresh", "sequential"}:
        raise ProtocolViolation("request record execution_mode is invalid")
    if value["status"] not in {
        "success",
        "worker_error",
        "harness_error",
    }:
        raise ProtocolViolation("request record status is invalid")
    if type(value["request_wire"]) is not dict:
        raise ProtocolViolation("request record request_wire must be an object")
    request_bytes = canonical_json_bytes(value["request_wire"])
    request_digest = _binding_digest(
        value["request_digest"], "request record request_digest"
    )
    if request_digest != digest_bytes(request_bytes):
        raise ProtocolViolation("request record request digest mismatch")
    request = request_from_wire(
        json.loads(request_bytes.decode("utf-8"))
    )
    if request.operation.value != operation or request.seed != seed:
        raise ProtocolViolation("request record operation/seed binding mismatch")
    sent = value["request_fully_sent"]
    if type(sent) is not bool:
        raise ProtocolViolation("request_fully_sent must be an exact boolean")
    received = value["received_request_digest"]
    if received is not None:
        _binding_digest(received, "request record received_request_digest")
    if not sent and received is not None:
        raise ProtocolViolation(
            "an incompletely sent request cannot have a worker received digest"
        )
    response_wire = value["response_wire"]
    response_digest = value["response_digest"]
    if (response_wire is None) != (response_digest is None):
        raise ProtocolViolation("response wire/digest nullability mismatch")
    response = None
    if response_wire is not None:
        if type(response_wire) is not dict:
            raise ProtocolViolation("response_wire must be an object or null")
        response_bytes = canonical_json_bytes(response_wire)
        if _binding_digest(
            response_digest, "request record response_digest"
        ) != digest_bytes(response_bytes):
            raise ProtocolViolation("request record response digest mismatch")
        response = response_from_wire(
            json.loads(response_bytes.decode("utf-8"))
        )

    status = value["status"]
    origin = value["failure_origin"]
    code = value["failure_code"]
    if status == "success":
        if (
            sent is not True
            or received != request_digest
            or response is None
            or origin is not None
            or code is not None
        ):
            raise ProtocolViolation("successful request record is inconsistent")
        _validate_response_for_request(request, response)
    elif status == "worker_error":
        if (
            sent is not True
            or received != request_digest
            or response_wire is not None
            or origin != "candidate"
            or _canonical_candidate_failure_code(code) is None
        ):
            raise ProtocolViolation("candidate worker error record is inconsistent")
    else:
        if origin != "harness" or code != "UCM-E003-HARNESS_INCOMPLETE":
            raise ProtocolViolation("harness error record is inconsistent")
        if not sent and (received is not None or response_wire is not None):
            raise ProtocolViolation(
                "unsent harness error cannot claim worker receipt/response"
            )
        if sent and received not in {None, request_digest}:
            raise ProtocolViolation(
                "harness error received digest must be null or exact"
            )
        if response is not None:
            if received != request_digest:
                raise ProtocolViolation(
                    "retained harness response requires exact worker receipt"
                )
            _validate_response_for_request(request, response)
    return canonical_json_bytes(value)


def _best_effort_response_evidence(
    outcome: Any,
) -> tuple[dict[str, Any] | None, str | None]:
    try:
        encoded = canonical_json_bytes(outcome.response.to_wire())
        wire = json.loads(encoded.decode("utf-8"))
    except Exception:
        return None, None
    return wire, digest_bytes(encoded)


def _record_observed_error(
    collector: _ExecutionBindingCollector,
    frozen: _FrozenObservedRequest,
    error: WorkerInvocationError,
    *,
    execution_mode: str,
    response: tuple[dict[str, Any] | None, str | None] = (None, None),
) -> WorkerInvocationError:
    origin = getattr(error, "failure_origin", "harness")
    sent = getattr(error, "request_fully_sent", False)
    received = getattr(error, "received_request_digest", None)
    claimed = getattr(error, "request_digest", None)
    candidate_proven = (
        origin == "candidate"
        and sent is True
        and claimed == frozen.digest
        and received == frozen.digest
    )
    if origin == "candidate" and not candidate_proven:
        error = _observed_harness_error(
            ProtocolViolation(
                "candidate worker error lacked exact sent/received request binding"
            ),
            frozen=frozen,
            outcome=error,
            message="candidate failure request binding incomplete",
        )
        origin = "harness"
        sent = bool(getattr(error, "request_fully_sent", False))
        received = getattr(error, "received_request_digest", None)
    status = "worker_error" if origin == "candidate" else "harness_error"
    if status == "harness_error" and received not in {None, frozen.digest}:
        # A mismatching worker claim is why this row is harness-incomplete; it
        # is not a verified received-request binding and therefore cannot
        # occupy the verified digest field.
        received = None
    response_wire, response_digest = response
    if status == "harness_error" and (
        sent is not True or received != frozen.digest
    ):
        response_wire = None
        response_digest = None
    collector.request_records.append(
        _request_record(
            frozen,
            execution_mode=execution_mode,
            status=status,
            request_fully_sent=sent is True,
            received_request_digest=(
                received if type(received) is str else None
            ),
            response_wire=response_wire,
            response_digest=response_digest,
            failure_origin=origin if origin in {"candidate", "harness"} else "harness",
            failure_code=(
                error.failure_code
                if type(getattr(error, "failure_code", None)) is str
                else "UCM-E003-HARNESS_INCOMPLETE"
            ),
        )
    )
    return error


def _record_observed_success(
    collector: _ExecutionBindingCollector,
    frozen: _FrozenObservedRequest,
    outcome: InvocationOutcome,
    *,
    execution_mode: str,
) -> InvocationOutcome:
    if type(outcome) is not InvocationOutcome:
        raise ProtocolViolation("executor outcome must be InvocationOutcome")
    response_bytes = canonical_json_bytes(outcome.response.to_wire())
    response_wire = json.loads(response_bytes.decode("utf-8"))
    response = response_from_wire(json.loads(response_bytes.decode("utf-8")))
    _validate_response_for_request(frozen.request, response)
    response_digest = digest_bytes(response_bytes)
    if (
        outcome.request_digest != frozen.digest
        or outcome.received_request_digest != frozen.digest
        or outcome.response_digest != response_digest
    ):
        error = _observed_harness_error(
            ProtocolViolation("executor request/response digest binding mismatch"),
            frozen=frozen,
            outcome=outcome,
            message="successful invocation digest validation incomplete",
        )
        _record_observed_error(
            collector,
            frozen,
            error,
            execution_mode=execution_mode,
            response=(response_wire, response_digest),
        )
        raise error
    collector.request_records.append(
        _request_record(
            frozen,
            execution_mode=execution_mode,
            status="success",
            request_fully_sent=True,
            received_request_digest=frozen.digest,
            response_wire=response_wire,
            response_digest=response_digest,
            failure_origin=None,
            failure_code=None,
        )
    )
    return replace(
        outcome,
        response=response,
        request_digest=frozen.digest,
        response_digest=response_digest,
        received_request_digest=frozen.digest,
    )


def _invoke_observed_sequence(
    entrypoint: CandidateEntrypoint,
    requests: tuple[Any, ...],
    collector: _ExecutionBindingCollector,
    *,
    timeout_seconds: float,
) -> tuple[InvocationOutcome, ...]:
    frozen_requests = tuple(_freeze_observed_request(item) for item in requests)
    try:
        outcomes = SequentialProcessExecutor(
            entrypoint, timeout_seconds=timeout_seconds
        ).invoke_sequence(tuple(item.request for item in frozen_requests))
    except WorkerInvocationError as error:
        collector.observe(
            error,
            allow_missing=(
                getattr(error, "failure_origin", "harness") != "candidate"
            ),
        )
        completed_raw = getattr(error, "completed_outcomes", ())
        if (
            type(completed_raw) is not tuple
            or len(completed_raw) > len(frozen_requests)
        ):
            completed: tuple[InvocationOutcome, ...] = ()
            prefix_contract_valid = False
        else:
            completed = completed_raw
            prefix_contract_valid = True
        completed_count = len(completed)
        error_index = getattr(error, "request_index", None)
        error_digest = getattr(error, "request_digest", None)
        error_sent = getattr(error, "request_fully_sent", False)
        error_received = getattr(error, "received_request_digest", None)
        error_origin = getattr(error, "failure_origin", "harness")
        if completed_count < len(frozen_requests):
            expected = frozen_requests[completed_count]
            prefix_contract_valid = prefix_contract_valid and (
                error_index == completed_count
                and error_digest == expected.digest
                and type(error_sent) is bool
                and (error_sent or error_received is None)
            )
        else:
            # No candidate request exists after a complete prefix.  Only a
            # harness-owned close/postcheck error may follow it.
            prefix_contract_valid = prefix_contract_valid and (
                error_origin == "harness"
                and error_index is None
                and error_digest is None
                and error_sent is False
                and error_received is None
            )
        if not prefix_contract_valid:
            if completed_count < len(frozen_requests):
                expected = frozen_requests[completed_count]
            else:
                expected = frozen_requests[-1]
            error = WorkerInvocationError(
                "sequential error/prefix binding was inconsistent",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                failure_origin="harness",
                request_digest=(
                    expected.digest
                    if completed_count < len(frozen_requests)
                    else None
                ),
                request_fully_sent=False,
                request_index=(
                    completed_count
                    if completed_count < len(frozen_requests)
                    else None
                ),
                completed_outcomes=completed,
                **_binding_error_kwargs(error),
            )
        for frozen, outcome in zip(frozen_requests, completed):
            collector.observe(outcome)
            _record_observed_success(
                collector,
                frozen,
                outcome,
                execution_mode="sequential",
            )
        if completed_count < len(frozen_requests):
            normalized = _record_observed_error(
                collector,
                frozen_requests[completed_count],
                error,
                execution_mode="sequential",
            )
            raise normalized
        # A close/postcheck failure is not another candidate request.  The
        # exact completed call prefix is retained, while the caller's E003
        # finding preserves the failed harness phase without fabricating a
        # duplicate request record.
        raise error
    if len(outcomes) != len(frozen_requests):
        error = _observed_harness_error(
            ProtocolViolation("sequential outcome count mismatch"),
            frozen=frozen_requests[0],
            message="sequential transcript incomplete",
        )
        _record_observed_error(
            collector,
            frozen_requests[0],
            error,
            execution_mode="sequential",
        )
        raise error
    normalized_outcomes: list[InvocationOutcome] = []
    for frozen, outcome in zip(frozen_requests, outcomes):
        collector.observe(outcome)
        normalized_outcomes.append(
            _record_observed_success(
                collector,
                frozen,
                outcome,
                execution_mode="sequential",
            )
        )
    return tuple(normalized_outcomes)


def _state_dict(state: CandidateStateInput) -> dict[str, Any]:
    payload = state.payload
    if payload.codec != "canonical-json-v1":
        raise ProtocolViolation("control candidate expects canonical-json-v1")
    value = json.loads(payload.payload.decode("utf-8"))
    if type(value) is not dict:
        raise ProtocolViolation("control candidate state is not an object")
    return value


def _signal_from_history(history: VisibleHistory) -> float:
    signal = 0.5
    for event in history.events:
        value = event.payload.get("signal")
        if type(value) in {int, float}:
            signal = min(1.0, max(0.0, float(value)))
    return signal


def _probabilities(
    labels: tuple[str, ...], signal: float, seed: int
) -> dict[str, float]:
    if len(labels) == 1:
        return {labels[0]: 1.0}
    # Local RNG, recreated solely from the explicit request seed.
    jitter = (random.Random(seed).random() - 0.5) * 0.01
    first = min(0.95, max(0.05, 0.05 + 0.90 * signal + jitter))
    rest = (1.0 - first) / (len(labels) - 1)
    return {labels[0]: first, **{label: rest for label in labels[1:]}}


class HonestSeededControl:
    """Specificity control: closed state and explicit seeded stochastic heads."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        # inference_seed is explicit even though this deterministic encoder does
        # not need to sample.
        del inference_seed
        return StatePayload.from_json(
            {
                "signal": _signal_from_history(history),
                "seen": [event.event_uid for event in history.events],
                "as_of": history.as_of_available_at,
            },
            schema_version="ucm-control-state/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )

    def update(
        self,
        state: CandidateStateInput,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> StatePayload:
        del inference_seed
        value = _state_dict(state)
        seen = list(value.get("seen", []))
        signal = float(value.get("signal", 0.5))
        for event in delta.events:
            if event.event_uid in seen:
                continue
            seen.append(event.event_uid)
            candidate_signal = event.payload.get("signal")
            if type(candidate_signal) in {int, float}:
                signal = min(1.0, max(0.0, float(candidate_signal)))
        return StatePayload.from_json(
            {"signal": signal, "seen": seen, "as_of": delta.advance_to},
            schema_version="ucm-control-state/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )

    def diagnose(
        self,
        state: CandidateStateInput,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> DiagnosisResult:
        signal = float(_state_dict(state).get("signal", 0.5))
        return DiagnosisResult(
            ResultStatus.OK,
            _probabilities(query.label_catalog, signal, query_seed),
            {"rng": "explicit-local"},
        )

    def rollout(
        self,
        state: CandidateStateInput,
        query: RolloutQuery,
        *,
        query_seed: int,
    ) -> RolloutResult:
        signal = float(_state_dict(state).get("signal", 0.5))
        jitter = (random.Random(query_seed).random() - 0.5) * 0.01
        value = signal + jitter
        predictions = {
            observable: {
                "family": "point_mass",
                "horizon": query.horizon,
                "values": [value for _ in range(query.horizon)],
            }
            for observable in query.requested_observables
        }
        return RolloutResult(
            ResultStatus.OK,
            observable_predictions=predictions,
            utility_prediction={"family": "point_mass", "value": -abs(value)},
            metadata={"rng": "explicit-local"},
        )


_GLOBAL_SECOND_STATE: float | None = None


class GlobalSecondStateControl(HonestSeededControl):
    """Malicious: payload is a token; patient signal lives in module global."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del inference_seed
        global _GLOBAL_SECOND_STATE
        _GLOBAL_SECOND_STATE = _signal_from_history(history)
        return StatePayload.from_json(
            {"opaque_token": "lookup-global"},
            schema_version="malicious-global/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )

    def diagnose(
        self,
        state: CandidateStateInput,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> DiagnosisResult:
        del state
        signal = 0.5 if _GLOBAL_SECOND_STATE is None else _GLOBAL_SECOND_STATE
        return DiagnosisResult(
            ResultStatus.OK,
            _probabilities(query.label_catalog, signal, query_seed),
            {"malicious": "module-global"},
        )

    def rollout(
        self,
        state: CandidateStateInput,
        query: RolloutQuery,
        *,
        query_seed: int,
    ) -> RolloutResult:
        del state
        signal = 0.5 if _GLOBAL_SECOND_STATE is None else _GLOBAL_SECOND_STATE
        jitter = (random.Random(query_seed).random() - 0.5) * 0.01
        predictions = {
            observable: {
                "family": "point_mass",
                "values": [signal + jitter for _ in range(query.horizon)],
            }
            for observable in query.requested_observables
        }
        return RolloutResult(
            ResultStatus.OK,
            observable_predictions=predictions,
            utility_prediction={"family": "point_mass", "value": -signal},
            metadata={"malicious": "module-global"},
        )


class RawHistoryHeadControl(HonestSeededControl):
    """Malicious: a readout attempts to reopen an undeclared patient history."""

    def diagnose(
        self,
        state: CandidateStateInput,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> DiagnosisResult:
        del state, query, query_seed
        with open("patient-history.json", "rb") as stream:  # noqa: PTH123
            stream.read()
        raise AssertionError("unreachable")


class TrainerTargetSmugglerControl(HonestSeededControl):
    """Malicious: initialization attempts to read trainer/judge-only targets."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del history, inference_seed
        with open("trainer-target-oracle.json", "rb") as stream:  # noqa: PTH123
            stream.read()
        raise AssertionError("unreachable")


class QueryReencoderControl(HonestSeededControl):
    """Malicious: a task head attempts to reopen and re-encode raw history."""

    def diagnose(
        self,
        state: CandidateStateInput,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> DiagnosisResult:
        del state, query, query_seed
        with open("patient-history-for-query-reencoder.json", "rb") as stream:  # noqa: PTH123
            stream.read()
        raise AssertionError("unreachable")


class FileHandleStateControl(HonestSeededControl):
    """Malicious: tries to persist patient state behind a filesystem handle."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del inference_seed
        with open("patient-state.bin", "wb") as stream:  # noqa: PTH123
            stream.write(str(_signal_from_history(history)).encode("ascii"))
        return StatePayload.from_json(
            {"path": "patient-state.bin"},
            schema_version="malicious-file-handle/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )


class FutureReaderControl(HonestSeededControl):
    """Malicious: a rollout attempts to read a private future artifact."""

    def rollout(
        self,
        state: CandidateStateInput,
        query: RolloutQuery,
        *,
        query_seed: int,
    ) -> RolloutResult:
        del state, query, query_seed
        with open("actual-future-results.json", "rb") as stream:  # noqa: PTH123
            stream.read()
        raise AssertionError("unreachable")


class TrueStateReaderControl(HonestSeededControl):
    """Malicious: a head attempts to open simulator hidden truth."""

    def diagnose(
        self,
        state: CandidateStateInput,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> DiagnosisResult:
        del state, query, query_seed
        with open("simulator-hidden-state.json", "rb") as stream:  # noqa: PTH123
            stream.read()
        raise AssertionError("unreachable")


class MutableCheckpointControl(HonestSeededControl):
    """Malicious: writes patient material into a model checkpoint."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del inference_seed
        with open("model-checkpoint.weights", "wb") as stream:  # noqa: PTH123
            stream.write(str(_signal_from_history(history)).encode("ascii"))
        raise AssertionError("unreachable")


class QueryMutatorControl(HonestSeededControl):
    """Malicious: a counterfactual query mutates its caller-owned input."""

    def rollout(
        self,
        state: CandidateStateInput,
        query: RolloutQuery,
        *,
        query_seed: int,
    ) -> RolloutResult:
        object.__setattr__(query, "horizon", query.horizon + 1)
        return super().rollout(state, query, query_seed=query_seed)


class ImplicitRNGControl(HonestSeededControl):
    """Malicious: ignores ``query_seed`` and reads operating-system entropy."""

    def diagnose(
        self,
        state: CandidateStateInput,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> DiagnosisResult:
        del state, query_seed
        if len(query.label_catalog) == 1:
            probabilities = {query.label_catalog[0]: 1.0}
        else:
            first = 0.05 + 0.90 * random.SystemRandom().random()
            rest = (1.0 - first) / (len(query.label_catalog) - 1)
            probabilities = {
                query.label_catalog[0]: first,
                **{label: rest for label in query.label_catalog[1:]},
            }
        return DiagnosisResult(
            ResultStatus.OK,
            probabilities,
            {"malicious": "implicit-system-rng"},
        )


def _history_from_state(state: CandidateStateInput) -> VisibleHistory:
    """Decode the deliberately transparent full-history control state."""

    value = _state_dict(state)
    history = value.get("history")
    if type(history) is not dict:
        raise ProtocolViolation("full-history control state omitted history")
    events = history.get("events")
    if type(events) is not list:
        raise ProtocolViolation("full-history control state omitted events")
    # Reuse the protocol's strict wire parser rather than trusting a hand-built
    # object.  Importing this private parser is confined to mutation controls.
    from .candidate_protocol import _history_from_wire

    return _history_from_wire(history)


class DeclaredFullHistoryBaselineControl(HonestSeededControl):
    """Specificity control: full public history is stored and honestly declared."""

    state_class = StateClass.FULL_HISTORY_BASELINE

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del inference_seed
        return StatePayload.from_json(
            {"history": history.to_wire()},
            schema_version="ucm-declared-full-history/1",
            state_class=self.state_class,
        )

    def update(
        self,
        state: CandidateStateInput,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> StatePayload:
        del inference_seed
        history = _history_from_state(state)
        known = {event.event_uid for event in history.events}
        combined = history.events + tuple(
            event for event in delta.events if event.event_uid not in known
        )
        updated = VisibleHistory(
            tuple(sorted(combined, key=event_sort_key)),
            delta.advance_to,
            history.catalog_digest,
        )
        return StatePayload.from_json(
            {"history": updated.to_wire()},
            schema_version="ucm-declared-full-history/1",
            state_class=self.state_class,
        )

    def diagnose(
        self,
        state: CandidateStateInput,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> DiagnosisResult:
        signal = _signal_from_history(_history_from_state(state))
        return DiagnosisResult(
            ResultStatus.OK,
            _probabilities(query.label_catalog, signal, query_seed),
            {"baseline": "declared-full-history"},
        )

    def rollout(
        self,
        state: CandidateStateInput,
        query: RolloutQuery,
        *,
        query_seed: int,
    ) -> RolloutResult:
        signal = _signal_from_history(_history_from_state(state))
        jitter = (random.Random(query_seed).random() - 0.5) * 0.01
        value = signal + jitter
        return RolloutResult(
            ResultStatus.OK,
            observable_predictions={
                observable: {
                    "family": "point_mass",
                    "horizon": query.horizon,
                    "values": [value for _ in range(query.horizon)],
                }
                for observable in query.requested_observables
            },
            utility_prediction={"family": "point_mass", "value": -abs(value)},
            metadata={"baseline": "declared-full-history"},
        )


class HistoryInBlobControl(DeclaredFullHistoryBaselineControl):
    """Malicious: deterministic compressed history masquerades as compact state."""

    state_class = StateClass.COMPRESSED_SHARED

    @staticmethod
    def _compressed_payload(history: VisibleHistory) -> StatePayload:
        compressed = zlib.compress(canonical_json_bytes(history.to_wire()), level=9)
        return StatePayload.from_json(
            {
                "opaque_blob": base64.b64encode(compressed).decode("ascii"),
                "advertised": "compact-patient-latent",
            },
            schema_version="malicious-compressed-history/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del inference_seed
        return self._compressed_payload(history)

    def update(
        self,
        state: CandidateStateInput,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> StatePayload:
        del inference_seed
        history = self._decode_compressed_history(state)
        known = {event.event_uid for event in history.events}
        combined = history.events + tuple(
            event for event in delta.events if event.event_uid not in known
        )
        return self._compressed_payload(
            VisibleHistory(
                tuple(sorted(combined, key=event_sort_key)),
                delta.advance_to,
                history.catalog_digest,
            )
        )

    @staticmethod
    def _decode_compressed_history(state: CandidateStateInput) -> VisibleHistory:
        value = _state_dict(state)
        encoded = value.get("opaque_blob")
        if type(encoded) is not str:
            raise ProtocolViolation("compressed-history control omitted blob")
        try:
            decoded = json.loads(
                zlib.decompress(base64.b64decode(encoded, validate=True)).decode(
                    "utf-8"
                )
            )
        except (
            ValueError,
            binascii.Error,
            UnicodeDecodeError,
            json.JSONDecodeError,
            zlib.error,
        ) as exc:
            raise ProtocolViolation("compressed-history control blob is invalid") from exc
        from .candidate_protocol import _history_from_wire

        return _history_from_wire(decoded)

    def diagnose(
        self,
        state: CandidateStateInput,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> DiagnosisResult:
        signal = _signal_from_history(self._decode_compressed_history(state))
        return DiagnosisResult(
            ResultStatus.OK,
            _probabilities(query.label_catalog, signal, query_seed),
            {"malicious": "compressed-history-masquerade"},
        )

    def rollout(
        self,
        state: CandidateStateInput,
        query: RolloutQuery,
        *,
        query_seed: int,
    ) -> RolloutResult:
        signal = _signal_from_history(self._decode_compressed_history(state))
        jitter = (random.Random(query_seed).random() - 0.5) * 0.01
        value = signal + jitter
        return RolloutResult(
            ResultStatus.OK,
            observable_predictions={
                observable: {
                    "family": "point_mass",
                    "horizon": query.horizon,
                    "values": [value for _ in range(query.horizon)],
                }
                for observable in query.requested_observables
            },
            utility_prediction={"family": "point_mass", "value": -abs(value)},
            metadata={"malicious": "compressed-history-masquerade"},
        )


_WARM_FUTURE_CACHE: tuple[int, float] | None = None


class WarmFutureCacheControl(HonestSeededControl):
    """Malicious: a later-cut warm initialization contaminates an old state."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        global _WARM_FUTURE_CACHE
        _WARM_FUTURE_CACHE = (
            history.as_of_available_at,
            _signal_from_history(history),
        )
        return super().initialize(history, inference_seed=inference_seed)

    def update(
        self,
        state: CandidateStateInput,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> StatePayload:
        global _WARM_FUTURE_CACHE
        updated = super().update(state, delta, inference_seed=inference_seed)
        updated_value = json.loads(updated.payload.decode("utf-8"))
        _WARM_FUTURE_CACHE = (
            delta.advance_to,
            float(updated_value.get("signal", 0.5)),
        )
        return updated

    @staticmethod
    def _contaminated_signal(state: CandidateStateInput) -> float:
        value = _state_dict(state)
        state_cut = int(value.get("as_of", -1))
        state_signal = float(value.get("signal", 0.5))
        if _WARM_FUTURE_CACHE is None:
            return state_signal
        cached_cut, cached_signal = _WARM_FUTURE_CACHE
        return cached_signal if cached_cut > state_cut else state_signal

    def diagnose(
        self,
        state: CandidateStateInput,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> DiagnosisResult:
        return DiagnosisResult(
            ResultStatus.OK,
            _probabilities(
                query.label_catalog,
                self._contaminated_signal(state),
                query_seed,
            ),
            {"malicious": "warm-future-cache"},
        )

    def rollout(
        self,
        state: CandidateStateInput,
        query: RolloutQuery,
        *,
        query_seed: int,
    ) -> RolloutResult:
        signal = self._contaminated_signal(state)
        jitter = (random.Random(query_seed).random() - 0.5) * 0.01
        value = signal + jitter
        return RolloutResult(
            ResultStatus.OK,
            observable_predictions={
                observable: {
                    "family": "point_mass",
                    "horizon": query.horizon,
                    "values": [value for _ in range(query.horizon)],
                }
                for observable in query.requested_observables
            },
            utility_prediction={"family": "point_mass", "value": -abs(value)},
            metadata={"malicious": "warm-future-cache"},
        )


class ReplayBatchDivergenceControl(HonestSeededControl):
    """Malicious: incremental update uses a different transition than replay."""

    def update(
        self,
        state: CandidateStateInput,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> StatePayload:
        del inference_seed
        value = _state_dict(state)
        signal = float(value.get("signal", 0.5))
        seen = list(value.get("seen", []))
        for event in delta.events:
            if event.event_uid in seen:
                continue
            seen.append(event.event_uid)
            candidate_signal = event.payload.get("signal")
            if type(candidate_signal) in {int, float}:
                # Initialization uses the latest signal; this deliberately uses
                # a path-dependent averaging transition instead.
                signal = 0.5 * (signal + float(candidate_signal))
        return StatePayload.from_json(
            {"signal": signal, "seen": seen, "as_of": delta.advance_to},
            schema_version="malicious-replay-batch-divergence/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )


class DoubleCountEventControl(HonestSeededControl):
    """Malicious: replaying an already-seen event changes the patient state."""

    def update(
        self,
        state: CandidateStateInput,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> StatePayload:
        del inference_seed
        value = _state_dict(state)
        signal = float(value.get("signal", 0.5))
        seen = list(value.get("seen", []))
        for event in delta.events:
            candidate_signal = event.payload.get("signal")
            if event.event_uid in seen:
                if type(candidate_signal) in {int, float}:
                    signal = min(1.0, signal + 0.1 * float(candidate_signal))
                continue
            seen.append(event.event_uid)
            if type(candidate_signal) in {int, float}:
                signal = min(1.0, max(0.0, float(candidate_signal)))
        return StatePayload.from_json(
            {"signal": signal, "seen": seen, "as_of": delta.advance_to},
            schema_version="malicious-double-count-event/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )


class BehaviorEquivalentSerializationControl(HonestSeededControl):
    """Specificity control: an affine coordinate encodes identical behavior."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del inference_seed
        signal = _signal_from_history(history)
        return StatePayload.from_json(
            {
                "centered_coordinate": 2.0 * signal - 1.0,
                "seen": [event.event_uid for event in history.events],
                "as_of": history.as_of_available_at,
            },
            schema_version="ucm-affine-coordinate-state/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )

    def update(
        self,
        state: CandidateStateInput,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> StatePayload:
        del inference_seed
        value = _state_dict(state)
        signal = (float(value.get("centered_coordinate", 0.0)) + 1.0) / 2.0
        seen = list(value.get("seen", []))
        for event in delta.events:
            if event.event_uid in seen:
                continue
            seen.append(event.event_uid)
            candidate_signal = event.payload.get("signal")
            if type(candidate_signal) in {int, float}:
                signal = min(1.0, max(0.0, float(candidate_signal)))
        return StatePayload.from_json(
            {
                "centered_coordinate": 2.0 * signal - 1.0,
                "seen": seen,
                "as_of": delta.advance_to,
            },
            schema_version="ucm-affine-coordinate-state/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )

    @staticmethod
    def _signal(state: CandidateStateInput) -> float:
        value = _state_dict(state)
        return (float(value.get("centered_coordinate", 0.0)) + 1.0) / 2.0

    def diagnose(
        self,
        state: CandidateStateInput,
        query: DiagnosisQuery,
        *,
        query_seed: int,
    ) -> DiagnosisResult:
        return DiagnosisResult(
            ResultStatus.OK,
            _probabilities(query.label_catalog, self._signal(state), query_seed),
            {"rng": "explicit-local", "coordinates": "affine"},
        )

    def rollout(
        self,
        state: CandidateStateInput,
        query: RolloutQuery,
        *,
        query_seed: int,
    ) -> RolloutResult:
        signal = self._signal(state)
        jitter = (random.Random(query_seed).random() - 0.5) * 0.01
        value = signal + jitter
        return RolloutResult(
            ResultStatus.OK,
            observable_predictions={
                observable: {
                    "family": "point_mass",
                    "horizon": query.horizon,
                    "values": [value for _ in range(query.horizon)],
                }
                for observable in query.requested_observables
            },
            utility_prediction={"family": "point_mass", "value": -abs(value)},
            metadata={"rng": "explicit-local", "coordinates": "affine"},
        )


class MatchedStochasticApproxControl(HonestSeededControl):
    """Specificity probe: matched seeded paths differ below scoring tolerance."""

    @staticmethod
    def _matched_noise(seed: int) -> float:
        return (random.Random(seed).random() - 0.5) * 0.004

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        signal = _signal_from_history(history) + self._matched_noise(inference_seed)
        return StatePayload.from_json(
            {
                "signal": signal,
                "seen": [event.event_uid for event in history.events],
                "as_of": history.as_of_available_at,
            },
            schema_version="ucm-matched-stochastic-approx/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )

    def update(
        self,
        state: CandidateStateInput,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> StatePayload:
        value = _state_dict(state)
        signal = float(value.get("signal", 0.5))
        seen = list(value.get("seen", []))
        changed = False
        for event in delta.events:
            if event.event_uid in seen:
                continue
            seen.append(event.event_uid)
            candidate_signal = event.payload.get("signal")
            if type(candidate_signal) in {int, float}:
                signal = (
                    float(candidate_signal)
                    + self._matched_noise(inference_seed)
                    + 4e-10
                )
                changed = True
        if not changed:
            # Duplicate update is exactly idempotent.
            signal = float(value.get("signal", signal))
        return StatePayload.from_json(
            {"signal": signal, "seen": seen, "as_of": delta.advance_to},
            schema_version="ucm-matched-stochastic-approx/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )


class HistoryBudgetJunkControl(HonestSeededControl):
    """Specificity negative: exhaust fixed-codec traversal without a history."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del inference_seed
        return StatePayload.from_json(
            {
                "signal": _signal_from_history(history),
                "seen": [event.event_uid for event in history.events],
                "as_of": history.as_of_available_at,
                "junk": ["AAAA" for _ in range(_HISTORY_MAX_STRINGS + 1)],
            },
            schema_version="ucm-history-budget-junk/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )


class InfiniteLoopControl(HonestSeededControl):
    """Negative control: candidate method never returns."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del history, inference_seed
        while True:
            pass


class ExitProcessControl(HonestSeededControl):
    """Negative control: candidate terminates only its isolated child."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del history, inference_seed
        os._exit(91)


class ParentTamperControl(HonestSeededControl):
    """Negative control: audited parent-signal attempt must be denied in child."""

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del history, inference_seed
        os.kill(os.getppid(), signal.SIGTERM)
        raise AssertionError("parent signal unexpectedly escaped audit")


def _audit_hook_noop(_self: Any, _event: str, _args: tuple[Any, ...]) -> None:
    """Code donor for the explicit same-process audit-tamper counterexample."""


class HarnessTamperControl(HonestSeededControl):
    """Counterexample: transient Python hook code mutation evades attestation.

    This control is intentionally retained as evidence that CPython audit
    observability is not an adversarial OS sandbox.  It must never be counted
    as a killed mutant merely because parent-side source binding is intact.
    """

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> StatePayload:
        del inference_seed
        from . import candidate_protocol

        hook_function = candidate_protocol._CandidateAuditBoundary.__call__
        original_code = hook_function.__code__
        hook_function.__code__ = _audit_hook_noop.__code__
        try:
            with Path(__file__).open("rb") as stream:
                escaped_read = bool(stream.read(1))
        finally:
            hook_function.__code__ = original_code
        return StatePayload.from_json(
            {
                "signal": _signal_from_history(history),
                "seen": [event.event_uid for event in history.events],
                "as_of": history.as_of_available_at,
                "harness_audit_bypass_observed": escaped_read,
            },
            schema_version="ucm-harness-tamper-counterexample/1",
            state_class=StateClass.COMPRESSED_SHARED,
        )


def _response_wire(outcome: InvocationOutcome) -> dict[str, Any]:
    return outcome.response.to_wire()


def _canonical_candidate_failure_code(value: Any) -> str | None:
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


def _harness_incomplete_from_exception(
    error: Exception, gate: str, *, detail: str = "harness/helper execution incomplete"
) -> ComplianceFinding:
    """Classify an exception from code-owned infrastructure without guessing.

    ``CandidateCallViolation`` is meaningful only at a call site that has
    already attributed the violation to candidate behavior.  A harness helper
    can itself raise that type, so helper-only sites must never infer origin
    from the exception class alone.
    """

    return ComplianceFinding(
        gate=gate,
        verdict=ComplianceVerdict.INCOMPLETE,
        failure_code="UCM-E003-HARNESS_INCOMPLETE",
        detail=f"{detail}: {type(error).__name__}: {error}",
        evidence={"exception_type": type(error).__name__},
    )


def _failure_from_worker(error: WorkerInvocationError, gate: str) -> ComplianceFinding:
    failure_origin = getattr(error, "failure_origin", "harness")
    reported_failure_code = getattr(error, "failure_code", None)
    canonical_failure_code = _canonical_candidate_failure_code(
        reported_failure_code
    )
    if failure_origin == "candidate" and canonical_failure_code is None:
        return ComplianceFinding(
            gate=gate,
            verdict=ComplianceVerdict.INCOMPLETE,
            failure_code="UCM-E003-HARNESS_INCOMPLETE",
            detail="worker returned a malformed candidate failure envelope",
            evidence={
                "failure_origin": failure_origin,
                "reported_failure_code": reported_failure_code,
                "audit_events": list(error.audit_events),
                "audit_overflow": error.audit_overflow,
                "returncode": error.returncode,
                "captured_stderr": error.captured_stderr[-2000:],
                "candidate_bundle_digest": getattr(
                    error, "candidate_bundle_digest", None
                ),
                "candidate_model_digest": getattr(
                    error, "candidate_model_digest", None
                ),
                "harness_bundle_digest": getattr(
                    error, "harness_bundle_digest", None
                ),
                "import_inventory_digest": getattr(
                    error, "import_inventory_digest", None
                ),
                "module_origin": getattr(error, "module_origin", None),
            },
        )
    if failure_origin != "candidate":
        return ComplianceFinding(
            gate=gate,
            verdict=ComplianceVerdict.INCOMPLETE,
            failure_code="UCM-E003-HARNESS_INCOMPLETE",
            detail=f"worker/harness execution incomplete: {error}",
            evidence={
                "failure_origin": failure_origin,
                "reported_failure_code": reported_failure_code,
                "audit_events": list(error.audit_events),
                "audit_overflow": error.audit_overflow,
                "returncode": error.returncode,
                "captured_stderr": error.captured_stderr[-2000:],
                "candidate_bundle_digest": getattr(
                    error, "candidate_bundle_digest", None
                ),
                "candidate_model_digest": getattr(
                    error, "candidate_model_digest", None
                ),
                "harness_bundle_digest": getattr(
                    error, "harness_bundle_digest", None
                ),
                "import_inventory_digest": getattr(
                    error, "import_inventory_digest", None
                ),
                "module_origin": getattr(error, "module_origin", None),
            },
        )
    return ComplianceFinding(
        gate=gate,
        verdict=ComplianceVerdict.FAIL,
        failure_code=canonical_failure_code,
        detail=str(error),
        evidence={
            "failure_origin": failure_origin,
            "audit_events": list(error.audit_events),
            "audit_overflow": error.audit_overflow,
            "returncode": error.returncode,
            "captured_stderr": error.captured_stderr[-2000:],
            "candidate_bundle_digest": getattr(
                error, "candidate_bundle_digest", None
            ),
            "candidate_model_digest": getattr(
                error, "candidate_model_digest", None
            ),
            "harness_bundle_digest": getattr(
                error, "harness_bundle_digest", None
            ),
            "import_inventory_digest": getattr(
                error, "import_inventory_digest", None
            ),
            "module_origin": getattr(error, "module_origin", None),
        },
    )


def _failure_from_exception(error: Exception, gate: str) -> ComplianceFinding:
    if not isinstance(error, CandidateCallViolation):
        return ComplianceFinding(
            gate=gate,
            verdict=ComplianceVerdict.INCOMPLETE,
            failure_code="UCM-E003-HARNESS_INCOMPLETE",
            detail=f"harness/helper execution incomplete: {type(error).__name__}: {error}",
            evidence={"exception_type": type(error).__name__},
        )
    reported_failure_code = getattr(error, "failure_code", None)
    canonical_failure_code = _canonical_candidate_failure_code(
        reported_failure_code
    )
    if canonical_failure_code is None:
        return ComplianceFinding(
            gate=gate,
            verdict=ComplianceVerdict.INCOMPLETE,
            failure_code="UCM-E003-HARNESS_INCOMPLETE",
            detail="candidate call violation carried a malformed failure code",
            evidence={"reported_failure_code": reported_failure_code},
        )
    return ComplianceFinding(
        gate=gate,
        verdict=ComplianceVerdict.FAIL,
        failure_code=canonical_failure_code,
        detail=f"{type(error).__name__}: {error}",
    )


def _decisive_gate_for_failure(failure_code: str, fallback: str) -> str:
    """Select the actual detector gate represented by a worker failure."""

    return {
        "UCM-F001-FUTURE_LEAK": "C08-candidate-view-physical-isolation",
        "UCM-F002-ORACLE_TRUE_STATE_ACCESS": "C08-candidate-view-physical-isolation",
        "UCM-F004-HEAD_HISTORY_ACCESS": "C02-head-history-denial",
        "UCM-F006-HIDDEN_PATIENT_CACHE": "C04-clean-process-replay",
        "UCM-F008-STATE_NOT_CLOSED": "C07-state-closed-schema",
        "UCM-F009-MODEL_MUTATION": "C06-model-immutability",
        "UCM-F012-QUERY_MUTATES_FACT": "C16-counterfactual-purity-order",
    }.get(failure_code, fallback)


def _recovers_full_history(
    payload: StatePayload, history: VisibleHistory
) -> tuple[str | None, dict[str, Any], str | None]:
    """Identify an exact recoverable history, including compressed JSON blobs.

    Every traversal and decode dimension is bounded.  This is deliberately a
    fixed recoverable-codec C27 probe, not evidence against encryption or a
    complete C31 undeclared-memory audit.
    """

    budgets = {
        "max_payload_bytes": _HISTORY_MAX_PAYLOAD_BYTES,
        "max_depth": _HISTORY_MAX_DEPTH,
        "max_nodes": _HISTORY_MAX_NODES,
        "max_strings": _HISTORY_MAX_STRINGS,
        "max_string_chars": _HISTORY_MAX_STRING_CHARS,
        "max_decode_attempts": _HISTORY_MAX_DECODE_ATTEMPTS,
        "max_total_compressed_bytes": _HISTORY_MAX_TOTAL_COMPRESSED_BYTES,
        "max_single_expanded_bytes": _HISTORY_MAX_SINGLE_EXPANDED_BYTES,
        "max_total_expanded_bytes": _HISTORY_MAX_TOTAL_EXPANDED_BYTES,
    }
    stats: dict[str, Any] = {
        "protocol": PORTABLE_SEMANTIC_PROBE_PROTOCOL,
        "scope": "fixed-recoverable-codec-c27-only",
        "encryption_or_c31_coverage": False,
        "budgets": budgets,
        "payload_bytes": len(payload.payload),
        "nodes_visited": 0,
        "max_depth_seen": 0,
        "strings_seen": 0,
        "string_chars_seen": 0,
        "decode_attempts": 0,
        "compressed_bytes_decoded": 0,
        "expanded_bytes_examined": 0,
    }
    if len(payload.payload) > _HISTORY_MAX_PAYLOAD_BYTES:
        return None, stats, "payload budget exceeded"
    if payload.codec != "canonical-json-v1":
        return None, stats, f"unsupported fixed-probe codec: {payload.codec}"
    try:
        decoded = json.loads(payload.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, stats, None
    target = history.to_wire()
    strings: list[str] = []
    stack: list[tuple[Any, int]] = [(decoded, 0)]
    while stack:
        value, depth = stack.pop()
        stats["nodes_visited"] += 1
        stats["max_depth_seen"] = max(stats["max_depth_seen"], depth)
        if stats["nodes_visited"] > _HISTORY_MAX_NODES:
            return None, stats, "node budget exceeded"
        if depth > _HISTORY_MAX_DEPTH:
            return None, stats, "depth budget exceeded"
        if value == target:
            return "canonical-json-subtree", stats, None
        if type(value) is dict:
            stack.extend((item, depth + 1) for item in value.values())
        elif type(value) is list:
            stack.extend((item, depth + 1) for item in value)
        elif type(value) is str:
            stats["strings_seen"] += 1
            stats["string_chars_seen"] += len(value)
            if stats["strings_seen"] > _HISTORY_MAX_STRINGS:
                return None, stats, "string-count budget exceeded"
            if len(value) > _HISTORY_MAX_STRING_CHARS:
                return None, stats, "single-string budget exceeded"
            if stats["string_chars_seen"] > _HISTORY_MAX_STRING_CHARS:
                return None, stats, "total-string-work budget exceeded"
            strings.append(value)

    for text in strings:
        # Strict prechecks avoid spending decoder work on arbitrary metadata.
        if not text or len(text) % 4 or not text.isascii():
            continue
        if len(text) > ((_HISTORY_MAX_TOTAL_COMPRESSED_BYTES + 2) // 3) * 4:
            return None, stats, "base64-length budget exceeded"
        if any(
            character
            not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/="
            for character in text
        ):
            continue
        stats["decode_attempts"] += 1
        if stats["decode_attempts"] > _HISTORY_MAX_DECODE_ATTEMPTS:
            return None, stats, "decode-attempt budget exceeded"
        try:
            compressed = base64.b64decode(text.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError, binascii.Error):
            continue
        stats["compressed_bytes_decoded"] += len(compressed)
        if (
            stats["compressed_bytes_decoded"]
            > _HISTORY_MAX_TOTAL_COMPRESSED_BYTES
        ):
            return None, stats, "compressed-work budget exceeded"
        remaining_total = (
            _HISTORY_MAX_TOTAL_EXPANDED_BYTES
            - stats["expanded_bytes_examined"]
        )
        if remaining_total <= 0:
            return None, stats, "expanded-work budget exceeded"
        expansion_limit = min(
            _HISTORY_MAX_SINGLE_EXPANDED_BYTES, remaining_total
        )
        try:
            inflater = zlib.decompressobj()
            recovered = inflater.decompress(compressed, expansion_limit + 1)
            if len(recovered) > expansion_limit:
                return None, stats, "single-expansion budget exceeded"
            if (
                not inflater.eof
                or inflater.unconsumed_tail
                or inflater.unused_data
            ):
                continue
            flushed = inflater.flush()
            if flushed:
                if len(recovered) + len(flushed) > expansion_limit:
                    return None, stats, "single-expansion budget exceeded"
                recovered += flushed
            stats["expanded_bytes_examined"] += len(recovered)
            candidate = json.loads(recovered.decode("utf-8"))
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            zlib.error,
        ):
            continue
        if candidate == target:
            return "base64-zlib-json", stats, None
    return None, stats, None


def _merged_visible_history(
    history: VisibleHistory, delta: VisibleDelta | None
) -> VisibleHistory | None:
    if delta is None or delta.advance_to < history.as_of_available_at:
        return None
    existing = {event.event_uid for event in history.events}
    if any(event.event_uid in existing for event in delta.events):
        return None
    return VisibleHistory(
        tuple(sorted(history.events + delta.events, key=event_sort_key)),
        delta.advance_to,
        history.catalog_digest,
    )


def _head_behavior(
    executor: FreshProcessExecutor,
    payload: StatePayload,
    diagnosis_query: DiagnosisQuery,
    rollout_query: RolloutQuery,
    *,
    seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    state = CandidateStateInput(payload)
    diagnosis = executor.invoke(
        DiagnoseRequest(state, diagnosis_query, seed + 1)
    )
    rollout = executor.invoke(
        RolloutRequest(state, rollout_query, seed + 2)
    )
    behavior = {
        "diagnosis": _semantic_behavior_projection(diagnosis.response),
        "rollout": _semantic_behavior_projection(rollout.response),
    }
    transcript = [
        {
            "operation": "diagnose",
            "request_digest": diagnosis.request_digest,
            "response_digest": diagnosis.response_digest,
            "worker_pid": diagnosis.worker_pid,
            "isolation": diagnosis.isolation,
        },
        {
            "operation": "rollout",
            "request_digest": rollout.request_digest,
            "response_digest": rollout.response_digest,
            "worker_pid": rollout.worker_pid,
            "isolation": rollout.isolation,
        },
    ]
    return behavior, transcript


def _semantic_behavior_projection(response: Any) -> dict[str, Any]:
    """Frozen scoring semantics only; metadata/diagnostics are excluded."""

    if isinstance(response, DiagnoseResponse):
        return {
            "operation": "diagnose",
            "status": response.result.status.value,
            "probabilities": response.result.probabilities,
        }
    if isinstance(response, RolloutResponse):
        return {
            "operation": "rollout",
            "status": response.result.status.value,
            "observable_predictions": response.result.observable_predictions,
            "utility_prediction": response.result.utility_prediction,
        }
    raise ProtocolViolation("semantic projection requires a head response")


def _semantic_behavior_equal(left: Any, right: Any) -> bool:
    """Recursive numeric comparator for frozen semantic projections."""

    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if type(left) in {int, float} and type(right) in {int, float}:
        return math.isclose(
            float(left),
            float(right),
            rel_tol=SEMANTIC_REL_TOLERANCE,
            abs_tol=SEMANTIC_ABS_TOLERANCE,
        )
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(
            _semantic_behavior_equal(left[key], right[key]) for key in left
        )
    if type(left) is list:
        return len(left) == len(right) and all(
            _semantic_behavior_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def _report(
    entrypoint: CandidateEntrypoint,
    findings: list[ComplianceFinding],
    records: list[HeadExecution],
    bindings: _ExecutionBindingCollector,
) -> ComplianceReport:
    normalized = list(findings)
    if not bindings.complete:
        normalized.append(
            ComplianceFinding(
                "execution-source-binding",
                ComplianceVerdict.INCOMPLETE,
                "UCM-E003-HARNESS_INCOMPLETE",
                (
                    "worker executions did not preserve one complete exact "
                    "candidate/model/harness/import inventory binding"
                ),
                {
                    "observed_bindings": bindings.observed,
                    "binding_violations": list(bindings.violations),
                    "candidate_bundle_digest": bindings.candidate_bundle_digest,
                    "candidate_model_digest": bindings.candidate_model_digest,
                    "harness_bundle_digest": bindings.harness_bundle_digest,
                    "import_inventory_digest": bindings.import_inventory_digest,
                    "module_origin": bindings.module_origin,
                },
            )
        )
    if not any(
        finding.failure_code == "UCM-E001-SEMANTIC_UNITY_UNVERIFIED"
        for finding in normalized
    ):
        normalized.append(
            ComplianceFinding(
                "semantic-unity-boundary",
                ComplianceVerdict.INCOMPLETE,
                "UCM-E001-SEMANTIC_UNITY_UNVERIFIED",
                "fresh-process closure does not prove an opaque payload is not multiplexed",
            )
        )
    if not any(
        finding.failure_code == "UCM-E002-ISOLATION_INCOMPLETE"
        for finding in normalized
    ):
        normalized.append(
            ComplianceFinding(
                "portable-isolation-boundary",
                ComplianceVerdict.INCOMPLETE,
                "UCM-E002-ISOLATION_INCOMPLETE",
                (
                    "same-process Python audit hook self-tampering, native "
                    "extension behavior, and Windows kernel escape are not "
                    "excluded; this result is not freeze-grade isolation"
                ),
            )
        )
    try:
        head_records = tuple(record.record.to_wire() for record in records)
    except Exception as error:
        # Report materialization is harness-owned.  A broken serializer must
        # not escape the evaluator or be mistaken for a candidate rejection.
        normalized.append(
            _harness_incomplete_from_exception(
                error,
                "harness-head-record-serialization",
                detail="head execution record serialization incomplete",
            )
        )
        head_records = ()
    try:
        request_record_bytes = tuple(
            _validated_request_record_bytes(record)
            for record in bindings.request_records
        )
    except Exception as error:
        normalized.append(
            _harness_incomplete_from_exception(
                error,
                "harness-request-record-serialization",
                detail="request/response transcript serialization incomplete",
            )
        )
        request_record_bytes = ()
    unmatched_request_errors: list[dict[str, Any]] = []
    for encoded in request_record_bytes:
        record = json.loads(encoded.decode("utf-8"))
        if record["status"] == "success":
            continue
        if not any(
            finding.failure_code == record["failure_code"]
            for finding in normalized
        ):
            unmatched_request_errors.append(
                {
                    "operation": record["operation"],
                    "seed": record["seed"],
                    "status": record["status"],
                    "failure_code": record["failure_code"],
                }
            )
    if unmatched_request_errors:
        normalized.append(
            ComplianceFinding(
                "request-transcript-error-consistency",
                ComplianceVerdict.INCOMPLETE,
                "UCM-E003-HARNESS_INCOMPLETE",
                "request transcript errors lacked a matching compliance finding",
                {"unmatched_records": unmatched_request_errors},
            )
        )
    failed = any(
        finding.verdict is ComplianceVerdict.FAIL for finding in normalized
    )
    fixed_scope_boundaries = {
        "UCM-E001-SEMANTIC_UNITY_UNVERIFIED",
        "UCM-E002-ISOLATION_INCOMPLETE",
    }
    detector_incomplete = any(
        finding.verdict is ComplianceVerdict.INCOMPLETE
        and finding.failure_code not in fixed_scope_boundaries
        for finding in normalized
    )
    return ComplianceReport(
        candidate=f"{entrypoint.module}:{entrypoint.qualname}",
        operational_state_closure=(
            ComplianceVerdict.INCOMPLETE
            if detector_incomplete
            else (ComplianceVerdict.FAIL if failed else ComplianceVerdict.PASS)
        ),
        # A black-box closure battery cannot rule out three concatenated task
        # latents inside one opaque payload.
        semantic_unity=ComplianceVerdict.INCOMPLETE,
        isolation_completeness=ComplianceVerdict.INCOMPLETE,
        isolation_assurance=(
            "fresh/sequential Python audit observability with bounded evidence; "
            "same-process hook tamper and Windows kernel/native escape not excluded"
        ),
        findings=tuple(normalized),
        head_records=head_records,
        _request_record_bytes=request_record_bytes,
        candidate_bundle_digest=bindings.candidate_bundle_digest,
        candidate_model_digest=bindings.candidate_model_digest,
        harness_bundle_digest=bindings.harness_bundle_digest,
        import_inventory_digest=bindings.import_inventory_digest,
        module_origin=bindings.module_origin,
    )


def evaluate_candidate_compliance(
    entrypoint: CandidateEntrypoint,
    *,
    history: VisibleHistory,
    diagnosis_query: DiagnosisQuery,
    rollout_query: RolloutQuery,
    delta: VisibleDelta | None = None,
    seed: int = 17,
    semantic_probes: frozenset[str] = frozenset(),
) -> ComplianceReport:
    """Run the portable benchmark-v1 minimum operational closure battery.

    The method intentionally uses the exact same sealed state for diagnosis and
    rollout, repeats calls in independent workers, and compares a warm process
    with the fresh-process result.  It emits ``semantic_unity=INCOMPLETE`` even
    when all automated checks pass.
    """

    if type(semantic_probes) is not frozenset or not semantic_probes.issubset(
        PORTABLE_SEMANTIC_PROBES
    ):
        raise ProtocolViolation("semantic_probes contains an unknown probe")
    if type(seed) is not int or not 0 <= seed < 2**64 or seed + 3 >= 2**64:
        raise ProtocolViolation(
            "seed and all derived operation seeds must fit unsigned 64-bit integer"
        )
    if (
        "update_consistency" in semantic_probes
        and (seed ^ UPDATE_CONSISTENCY_LINEAGE_XOR_MASK) + 2 >= 2**64
    ):
        raise ProtocolViolation(
            "update-consistency lineage seeds must fit unsigned 64-bit integer"
        )

    findings: list[ComplianceFinding] = []
    records: list[HeadExecution] = []
    bindings = _ExecutionBindingCollector()
    try:
        fresh = _BindingObservedExecutor(FreshProcessExecutor(entrypoint), bindings)
    except Exception as error:
        findings.append(
            _harness_incomplete_from_exception(
                error,
                "candidate-worker-construction",
                detail="fresh worker executor construction incomplete",
            )
        )
        return _report(entrypoint, findings, records, bindings)

    try:
        initialize_request = InitializeRequest(history, seed)
    except Exception as error:
        findings.append(
            _harness_incomplete_from_exception(
                error,
                "candidate-worker-initialize-request",
                detail="initialize request construction incomplete",
            )
        )
        return _report(entrypoint, findings, records, bindings)
    try:
        init_a = fresh.invoke(initialize_request)
        init_b = fresh.invoke(initialize_request)
    except WorkerInvocationError as error:
        findings.append(
            _failure_from_worker(
                error,
                _decisive_gate_for_failure(
                    error.failure_code, "C04-clean-process-initialize"
                ),
            )
        )
        return _report(entrypoint, findings, records, bindings)
    except Exception as error:
        findings.append(
            _harness_incomplete_from_exception(
                error,
                "candidate-worker-initialize",
                detail="initialize worker invocation incomplete",
            )
        )
        return _report(entrypoint, findings, records, bindings)
    if type(init_a.response) is not StateResponse or type(
        init_b.response
    ) is not StateResponse:
        findings.append(
            ComplianceFinding(
                "C07-state-response-schema",
                ComplianceVerdict.FAIL,
                "UCM-F008-STATE_NOT_CLOSED",
                "initialize did not return a state response",
            )
        )
        return _report(entrypoint, findings, records, bindings)
    try:
        initialize_reproducible = (
            init_a.response.to_wire() == init_b.response.to_wire()
        )
    except Exception as error:
        findings.append(
            _harness_incomplete_from_exception(
                error,
                "C28-initialize-replay-compare",
                detail="initialize replay comparison incomplete",
            )
        )
        return _report(entrypoint, findings, records, bindings)
    if not initialize_reproducible:
        findings.append(
            ComplianceFinding(
                "C28/C30-explicit-replay",
                ComplianceVerdict.FAIL,
                "UCM-F020-NONREPRODUCIBLE",
                "same initialize input and seed produced different state bytes",
            )
        )
        return _report(entrypoint, findings, records, bindings)

    # State seals must commit to the exact bytes that the workers imported,
    # not a synthetic module/qualname label.  Any missing or drifting binding
    # makes the harness incomplete before a state can be honestly sealed.
    if not bindings.complete:
        return _report(entrypoint, findings, records, bindings)

    payload = init_a.response.state
    try:
        history_recovery_method, history_recovery_evidence, history_probe_incomplete = (
            _recovers_full_history(payload, history)
            if "full_history_disclosure" in semantic_probes
            else (None, {}, None)
        )
    except Exception as error:
        findings.append(
            _harness_incomplete_from_exception(
                error,
                "C27-fixed-codec-full-history-disclosure",
                detail="fixed-codec history recovery probe incomplete",
            )
        )
        return _report(entrypoint, findings, records, bindings)
    if history_probe_incomplete is not None:
        findings.append(
            ComplianceFinding(
                "C27-fixed-codec-full-history-disclosure",
                ComplianceVerdict.INCOMPLETE,
                "UCM-E003-HARNESS_INCOMPLETE",
                f"bounded history recovery probe incomplete: {history_probe_incomplete}",
                history_recovery_evidence,
            )
        )
    elif history_recovery_method is not None:
        if payload.state_class is StateClass.FULL_HISTORY_BASELINE:
            findings.append(
                ComplianceFinding(
                    "C27-fixed-codec-full-history-disclosure",
                    ComplianceVerdict.PASS,
                    None,
                    "recoverable public history is honestly declared as baseline_only",
                    {
                        "history_digest": history.digest,
                        "recovery_method": history_recovery_method,
                        **history_recovery_evidence,
                    },
                )
            )
        else:
            findings.append(
                ComplianceFinding(
                    "C27-fixed-codec-full-history-disclosure",
                    ComplianceVerdict.FAIL,
                    "UCM-F018-FULL_HISTORY_MISCLAIM",
                    (
                        "exact public history is recoverable through the fixed "
                        "bounded codec probe from a state claiming compression"
                    ),
                    {
                        "history_digest": history.digest,
                        "claimed_state_class": payload.state_class.value,
                        "recovery_method": history_recovery_method,
                        **history_recovery_evidence,
                    },
                )
            )
    try:
        sealed = seal_state(
            payload,
            candidate_bundle_digest=bindings.candidate_bundle_digest,
            model_digest=bindings.candidate_model_digest,
            scope_digest=digest_json(
                {
                    "diagnosis_query": diagnosis_query.to_wire(),
                    "rollout_query": rollout_query.to_wire(),
                }
            ),
            catalog_digest=history.catalog_digest,
            as_of_available_at=history.as_of_available_at,
            operation="initialize",
            state_instance_id="compliance-initialize",
        )
    except Exception as error:
        findings.append(
            _harness_incomplete_from_exception(
                error, "harness-state-seal", detail="state sealing incomplete"
            )
        )
        return _report(entrypoint, findings, records, bindings)

    try:
        diagnosis_a = invoke_diagnose(fresh, sealed, diagnosis_query, seed=seed + 1)
        diagnosis_b = invoke_diagnose(fresh, sealed, diagnosis_query, seed=seed + 1)
        rollout_a = invoke_rollout(fresh, sealed, rollout_query, seed=seed + 2)
        rollout_b = invoke_rollout(fresh, sealed, rollout_query, seed=seed + 2)
        records.extend((diagnosis_a, diagnosis_b, rollout_a, rollout_b))
        assert_shared_state_fanout(tuple(records))
    except WorkerInvocationError as error:
        findings.append(
            _failure_from_worker(
                error,
                _decisive_gate_for_failure(
                    error.failure_code, "C02/C04-fresh-head-closure"
                ),
            )
        )
        return _report(entrypoint, findings, records, bindings)
    except Exception as error:
        findings.append(_failure_from_exception(error, "C01/C16-head-purity"))
        return _report(entrypoint, findings, records, bindings)

    try:
        diagnosis_reproducible = _response_wire(
            diagnosis_a.outcome
        ) == _response_wire(diagnosis_b.outcome)
        rollout_reproducible = _response_wire(
            rollout_a.outcome
        ) == _response_wire(rollout_b.outcome)
    except Exception as error:
        findings.append(
            _harness_incomplete_from_exception(
                error,
                "C28-head-replay-compare",
                detail="head replay comparison incomplete",
            )
        )
        return _report(entrypoint, findings, records, bindings)
    if not diagnosis_reproducible:
        findings.append(
            ComplianceFinding(
                "C28/C30-explicit-head-replay",
                ComplianceVerdict.FAIL,
                "UCM-F020-NONREPRODUCIBLE",
                "fresh diagnosis workers disagreed for the same state/query/seed",
            )
        )
    if not rollout_reproducible:
        findings.append(
            ComplianceFinding(
                "C16/C28-counterfactual-replay",
                ComplianceVerdict.FAIL,
                "UCM-F020-NONREPRODUCIBLE",
                "fresh rollout workers disagreed for the same state/query/seed",
            )
        )

    update_a: InvocationOutcome | None = None
    if delta is not None:
        try:
            update_request = UpdateRequest(sealed.candidate_input, delta, seed + 3)
            update_a = fresh.invoke(update_request)
            update_b = fresh.invoke(update_request)
        except WorkerInvocationError as error:
            findings.append(
                _failure_from_worker(
                    error,
                    _decisive_gate_for_failure(
                        error.failure_code, "C21/C22-fresh-update"
                    ),
                )
            )
            return _report(entrypoint, findings, records, bindings)
        except Exception as error:
            findings.append(
                _harness_incomplete_from_exception(
                    error,
                    "C21/C22-fresh-update",
                    detail="update request/executor helper incomplete",
                )
            )
            return _report(entrypoint, findings, records, bindings)
        if type(update_a.response) is not StateResponse or type(
            update_b.response
        ) is not StateResponse:
            findings.append(
                ComplianceFinding(
                    "C21-update-schema",
                    ComplianceVerdict.FAIL,
                    "UCM-F010-UPDATE_NOT_RECURSIVE",
                    "update did not return state bytes",
                )
            )
            update_a = None
        else:
            try:
                update_reproducible = (
                    update_a.response.to_wire() == update_b.response.to_wire()
                )
            except Exception as error:
                findings.append(
                    _harness_incomplete_from_exception(
                        error,
                        "C22-update-replay-compare",
                        detail="update replay comparison incomplete",
                    )
                )
                return _report(entrypoint, findings, records, bindings)
            if not update_reproducible:
                findings.append(
                    ComplianceFinding(
                        "C22/C30-update-replay",
                        ComplianceVerdict.FAIL,
                        "UCM-F020-NONREPRODUCIBLE",
                        "fresh update workers disagreed for the same state/delta/seed",
                    )
                )

    try:
        merged_history = (
            _merged_visible_history(history, delta)
            if semantic_probes
            & frozenset({"update_consistency", "warm_future_old_cut"})
            else None
        )
    except Exception as error:
        findings.append(
            _harness_incomplete_from_exception(
                error,
                "semantic-probe-preparation",
                detail="semantic probe preparation incomplete",
            )
        )
        return _report(entrypoint, findings, records, bindings)
    if "update_consistency" in semantic_probes and merged_history is None:
        findings.append(
            ComplianceFinding(
                "C22-incremental-replay-duplicate-equivalence",
                ComplianceVerdict.INCOMPLETE,
                "UCM-E003-HARNESS_INCOMPLETE",
                "consistency probe requires a valid non-overlapping visible delta",
                {
                    "protocol": PORTABLE_SEMANTIC_PROBE_PROTOCOL,
                    "delta_provided": delta is not None,
                },
            )
        )
    if "warm_future_old_cut" in semantic_probes and merged_history is None:
        findings.append(
            ComplianceFinding(
                "C23-late-event-old-cut-stability",
                ComplianceVerdict.INCOMPLETE,
                "UCM-E003-HARNESS_INCOMPLETE",
                "old-cut stability probe requires a valid later visible delta",
                {
                    "protocol": PORTABLE_SEMANTIC_PROBE_PROTOCOL,
                    "delta_provided": delta is not None,
                },
            )
        )
    if (
        "update_consistency" in semantic_probes
        and merged_history is not None
    ):
        lineage_seed = seed ^ UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
        consistency_evidence: dict[str, Any] = {
            "protocol": PORTABLE_SEMANTIC_PROBE_PROTOCOL,
            "projection": "scored-fields-only; metadata-and-diagnostics-excluded",
            "absolute_tolerance": SEMANTIC_ABS_TOLERANCE,
            "relative_tolerance": SEMANTIC_REL_TOLERANCE,
            "lineage_seed": lineage_seed,
            "scope": "portable-current-diagnosis-rollout-surface-only",
            "all_query_lineage_coverage": False,
        }
        try:
            probe_initial = fresh.invoke(InitializeRequest(history, lineage_seed))
            if not isinstance(probe_initial.response, StateResponse):
                raise ProtocolViolation("lineage initialize did not return state")
            incremental = fresh.invoke(
                UpdateRequest(
                    CandidateStateInput(probe_initial.response.state),
                    delta,
                    lineage_seed,
                )
            )
            replay = fresh.invoke(InitializeRequest(merged_history, lineage_seed))
            if not isinstance(incremental.response, StateResponse):
                raise ProtocolViolation("incremental probe did not return state")
            duplicate = fresh.invoke(
                UpdateRequest(
                    CandidateStateInput(incremental.response.state),
                    delta,
                    lineage_seed,
                )
            )
            if not isinstance(replay.response, StateResponse) or not isinstance(
                duplicate.response, StateResponse
            ):
                raise ProtocolViolation("consistency probe did not receive state")
            incremental_behavior, incremental_heads = _head_behavior(
                fresh,
                incremental.response.state,
                diagnosis_query,
                rollout_query,
                seed=lineage_seed,
            )
            replay_behavior, replay_heads = _head_behavior(
                fresh,
                replay.response.state,
                diagnosis_query,
                rollout_query,
                seed=lineage_seed,
            )
            duplicate_behavior, duplicate_heads = _head_behavior(
                fresh,
                duplicate.response.state,
                diagnosis_query,
                rollout_query,
                seed=lineage_seed,
            )
            replay_match = _semantic_behavior_equal(
                incremental_behavior, replay_behavior
            )
            duplicate_match = _semantic_behavior_equal(
                incremental_behavior, duplicate_behavior
            )
            consistency_evidence.update(
                {
                    "state_transition_transcript": [
                        {
                            "operation": "lineage_initialize",
                            "request_digest": probe_initial.request_digest,
                            "response_digest": probe_initial.response_digest,
                            "worker_pid": probe_initial.worker_pid,
                            "isolation": probe_initial.isolation,
                        },
                        {
                            "operation": "incremental_update",
                            "request_digest": incremental.request_digest,
                            "response_digest": incremental.response_digest,
                            "worker_pid": incremental.worker_pid,
                            "isolation": incremental.isolation,
                        },
                        {
                            "operation": "clean_replay_initialize",
                            "request_digest": replay.request_digest,
                            "response_digest": replay.response_digest,
                            "worker_pid": replay.worker_pid,
                            "isolation": replay.isolation,
                        },
                        {
                            "operation": "duplicate_update",
                            "request_digest": duplicate.request_digest,
                            "response_digest": duplicate.response_digest,
                            "worker_pid": duplicate.worker_pid,
                            "isolation": duplicate.isolation,
                        },
                    ],
                    "incremental_head_transcript": incremental_heads,
                    "replay_head_transcript": replay_heads,
                    "duplicate_head_transcript": duplicate_heads,
                    "incremental_behavior_digest": digest_json(
                        incremental_behavior
                    ),
                    "replay_behavior_digest": digest_json(replay_behavior),
                    "duplicate_behavior_digest": digest_json(duplicate_behavior),
                    "incremental_equals_replay": replay_match,
                    "duplicate_event_is_idempotent": duplicate_match,
                }
            )
            if not replay_match or not duplicate_match:
                findings.append(
                    ComplianceFinding(
                        "C22-incremental-replay-duplicate-equivalence",
                        ComplianceVerdict.FAIL,
                        "UCM-F019-UPDATE_INCONSISTENT",
                        "incremental, clean replay, or duplicate-event behavior diverged",
                        consistency_evidence,
                    )
                )
            else:
                findings.append(
                    ComplianceFinding(
                        "C22-incremental-replay-duplicate-equivalence",
                        ComplianceVerdict.PASS,
                        None,
                        (
                            "incremental, clean replay, and duplicate-event "
                            "scored behavior agree within frozen tolerance"
                        ),
                        consistency_evidence,
                    )
                )
        except WorkerInvocationError as error:
            findings.append(
                _failure_from_worker(
                    error, "C22-incremental-replay-duplicate-equivalence"
                )
            )
        except Exception as error:
            # A probe execution failure is preserved as evidence, but is not
            # converted into F019: only an observed semantic divergence counts.
            findings.append(
                ComplianceFinding(
                    "C22-incremental-replay-duplicate-equivalence",
                    ComplianceVerdict.INCOMPLETE,
                    "UCM-E003-HARNESS_INCOMPLETE",
                    f"consistency probe incomplete: {type(error).__name__}: {error}",
                    consistency_evidence,
                )
            )

    if (
        "warm_future_old_cut" in semantic_probes
        and merged_history is not None
    ):
        # Prime a later public cut in the same candidate instance, then query
        # the already sealed old state.  A compliant head is a function of the
        # old state/query/seed and therefore cannot change.
        try:
            before_raw_wire = {
                "diagnosis": diagnosis_a.outcome.response.to_wire(),
                "rollout": rollout_a.outcome.response.to_wire(),
            }
            before_behavior = {
                "diagnosis": _semantic_behavior_projection(
                    diagnosis_a.outcome.response
                ),
                "rollout": _semantic_behavior_projection(rollout_a.outcome.response),
            }

            initialize_sequence = _invoke_observed_sequence(
                entrypoint,
                (
                    InitializeRequest(merged_history, seed),
                    DiagnoseRequest(
                        sealed.candidate_input, diagnosis_query, seed + 1
                    ),
                    RolloutRequest(
                        sealed.candidate_input, rollout_query, seed + 2
                    ),
                ),
                bindings,
                timeout_seconds=PORTABLE_COMPLIANCE_PROBE_TIMEOUT_SECONDS,
            )
            initialize_old_diagnosis = initialize_sequence[1]
            initialize_old_rollout = initialize_sequence[2]
            after_initialize_behavior = {
                "diagnosis": _semantic_behavior_projection(
                    initialize_old_diagnosis.response
                ),
                "rollout": _semantic_behavior_projection(
                    initialize_old_rollout.response
                ),
            }
            after_initialize_raw_wire = {
                "diagnosis": initialize_old_diagnosis.response.to_wire(),
                "rollout": initialize_old_rollout.response.to_wire(),
            }

            update_sequence = _invoke_observed_sequence(
                entrypoint,
                (
                    InitializeRequest(history, seed),
                    UpdateRequest(sealed.candidate_input, delta, seed + 3),
                    DiagnoseRequest(
                        sealed.candidate_input, diagnosis_query, seed + 1
                    ),
                    RolloutRequest(
                        sealed.candidate_input, rollout_query, seed + 2
                    ),
                ),
                bindings,
                timeout_seconds=PORTABLE_COMPLIANCE_PROBE_TIMEOUT_SECONDS,
            )
            update_old_diagnosis = update_sequence[2]
            update_old_rollout = update_sequence[3]
            after_update_behavior = {
                "diagnosis": _semantic_behavior_projection(
                    update_old_diagnosis.response
                ),
                "rollout": _semantic_behavior_projection(update_old_rollout.response),
            }
            after_update_raw_wire = {
                "diagnosis": update_old_diagnosis.response.to_wire(),
                "rollout": update_old_rollout.response.to_wire(),
            }
            initialize_stable = _semantic_behavior_equal(
                before_behavior, after_initialize_behavior
            )
            update_stable = _semantic_behavior_equal(
                before_behavior, after_update_behavior
            )
            initialize_raw_stable = before_raw_wire == after_initialize_raw_wire
            update_raw_stable = before_raw_wire == after_update_raw_wire

            def transcript(
                outcomes: tuple[InvocationOutcome, ...]
            ) -> list[dict[str, Any]]:
                return [
                    {
                        "request_digest": outcome.request_digest,
                        "response_digest": outcome.response_digest,
                        "worker_pid": outcome.worker_pid,
                        "isolation": outcome.isolation,
                    }
                    for outcome in outcomes
                ]

            warm_evidence = {
                "protocol": PORTABLE_SEMANTIC_PROBE_PROTOCOL,
                "projection": "scored-fields-only; metadata-and-diagnostics-excluded",
                "before_behavior_digest": digest_json(before_behavior),
                "before_raw_wire_digest": digest_json(before_raw_wire),
                "after_initialize_later_digest": digest_json(
                    after_initialize_behavior
                ),
                "after_initialize_later_raw_wire_digest": digest_json(
                    after_initialize_raw_wire
                ),
                "after_update_old_delta_digest": digest_json(
                    after_update_behavior
                ),
                "after_update_old_delta_raw_wire_digest": digest_json(
                    after_update_raw_wire
                ),
                "initialize_later_stable": initialize_stable,
                "update_old_delta_stable": update_stable,
                "initialize_later_raw_exact": initialize_raw_stable,
                "update_old_delta_raw_exact": update_raw_stable,
                "before_head_transcript": [
                    {
                        "request_digest": diagnosis_a.outcome.request_digest,
                        "response_digest": diagnosis_a.outcome.response_digest,
                        "worker_pid": diagnosis_a.outcome.worker_pid,
                        "isolation": diagnosis_a.outcome.isolation,
                    },
                    {
                        "request_digest": rollout_a.outcome.request_digest,
                        "response_digest": rollout_a.outcome.response_digest,
                        "worker_pid": rollout_a.outcome.worker_pid,
                        "isolation": rollout_a.outcome.isolation,
                    },
                ],
                "initialize_later_transcript": transcript(initialize_sequence),
                "update_old_delta_transcript": transcript(update_sequence),
                "old_cut": history.as_of_available_at,
                "later_cut": merged_history.as_of_available_at,
            }
            if not (
                initialize_stable
                and update_stable
                and initialize_raw_stable
                and update_raw_stable
            ):
                findings.append(
                    ComplianceFinding(
                        "C23-late-event-old-cut-stability",
                        ComplianceVerdict.FAIL,
                        "UCM-F001-FUTURE_LEAK",
                        "warming a later public cut changed a sealed old-cut answer",
                        warm_evidence,
                    )
                )
            else:
                findings.append(
                    ComplianceFinding(
                        "C23-late-event-old-cut-stability",
                        ComplianceVerdict.PASS,
                        None,
                        (
                            "sealed old-cut scored and exact raw responses survived "
                            "both initialize-later and update(old, delta) warming"
                        ),
                        warm_evidence,
                    )
                )
        except WorkerInvocationError as error:
            findings.append(
                _failure_from_worker(error, "C23-late-event-old-cut-stability")
            )
        except Exception as error:
            findings.append(
                ComplianceFinding(
                    "C23-late-event-old-cut-stability",
                    ComplianceVerdict.INCOMPLETE,
                    "UCM-E003-HARNESS_INCOMPLETE",
                    f"old-cut stability probe incomplete: {type(error).__name__}: {error}",
                )
            )

    # Warm-vs-fresh equivalence kills module/global patient state that happens
    # to make a warm demo work but disappears at process teardown.  Do not add
    # a cache diagnosis after explicit replay has already proven hidden RNG;
    # that would confuse two distinct root causes.
    if not any(
        finding.failure_code == "UCM-F020-NONREPRODUCIBLE"
        for finding in findings
    ):
        warm_sequence: tuple[InvocationOutcome, ...] | None = None
        try:
            warm_sequence = _invoke_observed_sequence(
                entrypoint,
                (
                    InitializeRequest(history, seed),
                    DiagnoseRequest(
                        sealed.candidate_input, diagnosis_query, seed + 1
                    ),
                    RolloutRequest(
                        sealed.candidate_input, rollout_query, seed + 2
                    ),
                ),
                bindings,
                timeout_seconds=PORTABLE_COMPLIANCE_PROBE_TIMEOUT_SECONDS,
            )
        except WorkerInvocationError as error:
            findings.append(_failure_from_worker(error, "C04-warm-cold-equivalence"))
        except Exception as error:
            findings.append(
                _harness_incomplete_from_exception(
                    error,
                    "C04-warm-cold-sequence",
                    detail="warm worker sequence helper incomplete",
                )
            )
        if warm_sequence is not None:
            try:
                warm_init, warm_diagnosis, warm_rollout = warm_sequence
            except Exception as error:
                findings.append(
                    _harness_incomplete_from_exception(
                        error,
                        "C04-warm-cold-sequence-shape",
                        detail="warm worker sequence shape incomplete",
                    )
                )
            else:
                if type(warm_init.response) is not StateResponse:
                    findings.append(
                        ComplianceFinding(
                            "C04-warm-cold-initialize-schema",
                            ComplianceVerdict.FAIL,
                            "UCM-F008-STATE_NOT_CLOSED",
                            "warm initialize returned no state",
                        )
                    )
                else:
                    try:
                        warm_matches_fresh = (
                            warm_init.response.to_wire()
                            == init_a.response.to_wire()
                            and warm_diagnosis.response.to_wire()
                            == diagnosis_a.outcome.response.to_wire()
                            and warm_rollout.response.to_wire()
                            == rollout_a.outcome.response.to_wire()
                        )
                    except Exception as error:
                        findings.append(
                            _harness_incomplete_from_exception(
                                error,
                                "C04-warm-cold-serialization",
                                detail="warm/cold response comparison incomplete",
                            )
                        )
                    else:
                        if not warm_matches_fresh:
                            findings.append(
                                ComplianceFinding(
                                    "C04/C05/C15-warm-cold-equivalence",
                                    ComplianceVerdict.FAIL,
                                    "UCM-F006-HIDDEN_PATIENT_CACHE",
                                    (
                                        "warm and fresh workers disagree; state "
                                        "payload is not the full closure"
                                    ),
                                )
                            )

    if not any(
        finding.failure_code == "UCM-F007-STATE_FANOUT_MISMATCH"
        for finding in findings
    ):
        findings.append(
            ComplianceFinding(
                "C01-exact-shared-state-fanout",
                ComplianceVerdict.PASS,
                None,
                "all executed heads consumed the same harness-owned state hash",
                {"state_hash": sealed.record.state_hash},
            )
        )
    findings.append(
        ComplianceFinding(
            "C03/C29-task-blind-state-producer",
            ComplianceVerdict.PASS,
            None,
            "initialize/update envelopes have no query or future-task field",
        )
    )
    return _report(entrypoint, findings, records, bindings)


def control_entrypoint(
    control_name: str, *, bundle_root: Path | None = None
) -> CandidateEntrypoint:
    """Return an importable entrypoint for one built-in mutation control."""

    allowed = {
        "HonestSeededControl",
        "GlobalSecondStateControl",
        "RawHistoryHeadControl",
        "FileHandleStateControl",
        "FutureReaderControl",
        "TrueStateReaderControl",
        "MutableCheckpointControl",
        "QueryMutatorControl",
        "ImplicitRNGControl",
        "TrainerTargetSmugglerControl",
        "QueryReencoderControl",
        "HistoryInBlobControl",
        "WarmFutureCacheControl",
        "ReplayBatchDivergenceControl",
        "DoubleCountEventControl",
        "BehaviorEquivalentSerializationControl",
        "DeclaredFullHistoryBaselineControl",
        "MatchedStochasticApproxControl",
        "HistoryBudgetJunkControl",
        "InfiniteLoopControl",
        "ExitProcessControl",
        "ParentTamperControl",
        "HarnessTamperControl",
    }
    if control_name not in allowed:
        raise ProtocolViolation(f"unknown compliance control {control_name!r}")
    root = bundle_root or Path(__file__).resolve().parents[2]
    return CandidateEntrypoint(
        bundle_root=root,
        module="prototype.unified_map.compliance",
        qualname=control_name,
    )
