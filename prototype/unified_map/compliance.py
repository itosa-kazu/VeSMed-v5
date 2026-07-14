"""Executable minimum compliance battery and deliberately malicious controls.

This module tests *operational state closure*: after ``initialize`` returns an
inert payload, fresh workers must be able to run every head and ``update`` from
that payload alone.  Passing this battery never upgrades an opaque candidate to
``semantic_unity=PASS``; source/dependency/behavioral audits remain necessary.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from .canonical import ProtocolViolation, digest_json
from .candidate_protocol import (
    CandidateCallViolation,
    CandidateEntrypoint,
    DiagnoseRequest,
    DiagnoseResponse,
    DiagnosisResult,
    FreshProcessExecutor,
    HeadExecution,
    InProcessExecutor,
    InitializeRequest,
    InvocationOutcome,
    Operation,
    ResultStatus,
    RolloutRequest,
    RolloutResponse,
    RolloutResult,
    StateResponse,
    UpdateRequest,
    WorkerInvocationError,
    _load_candidate,
    assert_shared_state_fanout,
    invoke_diagnose,
    invoke_rollout,
)
from .schema import DiagnosisQuery, RolloutQuery, VisibleDelta, VisibleHistory
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


def _response_wire(outcome: InvocationOutcome) -> dict[str, Any]:
    return outcome.response.to_wire()


def _failure_from_worker(error: WorkerInvocationError, gate: str) -> ComplianceFinding:
    return ComplianceFinding(
        gate=gate,
        verdict=ComplianceVerdict.FAIL,
        failure_code=error.failure_code,
        detail=str(error),
        evidence={
            "audit_events": list(error.audit_events),
            "returncode": error.returncode,
            "captured_stderr": error.captured_stderr[-2000:],
        },
    )


def _failure_from_exception(error: Exception, gate: str) -> ComplianceFinding:
    code = (
        error.failure_code
        if isinstance(error, CandidateCallViolation)
        else "UCM-F008-STATE_NOT_CLOSED"
    )
    return ComplianceFinding(
        gate=gate,
        verdict=ComplianceVerdict.FAIL,
        failure_code=code,
        detail=f"{type(error).__name__}: {error}",
    )


def _report(
    entrypoint: CandidateEntrypoint,
    findings: list[ComplianceFinding],
    records: list[HeadExecution],
) -> ComplianceReport:
    normalized = list(findings)
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
                    "method-phase Python audit does not exclude import-time, "
                    "native-extension, or Windows kernel escape"
                ),
            )
        )
    failed = any(
        finding.verdict is ComplianceVerdict.FAIL for finding in normalized
    )
    return ComplianceReport(
        candidate=f"{entrypoint.module}:{entrypoint.qualname}",
        operational_state_closure=(
            ComplianceVerdict.FAIL if failed else ComplianceVerdict.PASS
        ),
        # A black-box closure battery cannot rule out three concatenated task
        # latents inside one opaque payload.
        semantic_unity=ComplianceVerdict.INCOMPLETE,
        isolation_completeness=ComplianceVerdict.INCOMPLETE,
        isolation_assurance=(
            "fresh-python-process-method-audit-v1; import-time and Windows "
            "kernel/native escape not excluded"
        ),
        findings=tuple(normalized),
        head_records=tuple(record.record.to_wire() for record in records),
    )


def evaluate_candidate_compliance(
    entrypoint: CandidateEntrypoint,
    *,
    history: VisibleHistory,
    diagnosis_query: DiagnosisQuery,
    rollout_query: RolloutQuery,
    delta: VisibleDelta | None = None,
    seed: int = 17,
) -> ComplianceReport:
    """Run the portable benchmark-v1 minimum operational closure battery.

    The method intentionally uses the exact same sealed state for diagnosis and
    rollout, repeats calls in independent workers, and compares a warm process
    with the fresh-process result.  It emits ``semantic_unity=INCOMPLETE`` even
    when all automated checks pass.
    """

    findings: list[ComplianceFinding] = []
    records: list[HeadExecution] = []
    fresh = FreshProcessExecutor(entrypoint)

    try:
        init_a = fresh.invoke(InitializeRequest(history, seed))
        init_b = fresh.invoke(InitializeRequest(history, seed))
    except WorkerInvocationError as error:
        findings.append(_failure_from_worker(error, "C04-clean-process-initialize"))
        return _report(entrypoint, findings, records)
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
        return _report(entrypoint, findings, records)
    if init_a.response.to_wire() != init_b.response.to_wire():
        findings.append(
            ComplianceFinding(
                "C28/C30-explicit-replay",
                ComplianceVerdict.FAIL,
                "UCM-F020-NONREPRODUCIBLE",
                "same initialize input and seed produced different state bytes",
            )
        )
        return _report(entrypoint, findings, records)

    payload = init_a.response.state
    sealed = seal_state(
        payload,
        candidate_bundle_digest=digest_json(
            {"module": entrypoint.module, "qualname": entrypoint.qualname}
        ),
        model_digest=digest_json({"model": "compliance-control"}),
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

    try:
        diagnosis_a = invoke_diagnose(fresh, sealed, diagnosis_query, seed=seed + 1)
        diagnosis_b = invoke_diagnose(fresh, sealed, diagnosis_query, seed=seed + 1)
        rollout_a = invoke_rollout(fresh, sealed, rollout_query, seed=seed + 2)
        rollout_b = invoke_rollout(fresh, sealed, rollout_query, seed=seed + 2)
        records.extend((diagnosis_a, diagnosis_b, rollout_a, rollout_b))
        assert_shared_state_fanout(tuple(records))
    except WorkerInvocationError as error:
        findings.append(_failure_from_worker(error, "C02/C04-fresh-head-closure"))
        return _report(entrypoint, findings, records)
    except Exception as error:
        findings.append(_failure_from_exception(error, "C01/C16-head-purity"))
        return _report(entrypoint, findings, records)

    if _response_wire(diagnosis_a.outcome) != _response_wire(diagnosis_b.outcome):
        findings.append(
            ComplianceFinding(
                "C28/C30-explicit-head-replay",
                ComplianceVerdict.FAIL,
                "UCM-F020-NONREPRODUCIBLE",
                "fresh diagnosis workers disagreed for the same state/query/seed",
            )
        )
    if _response_wire(rollout_a.outcome) != _response_wire(rollout_b.outcome):
        findings.append(
            ComplianceFinding(
                "C16/C28-counterfactual-replay",
                ComplianceVerdict.FAIL,
                "UCM-F020-NONREPRODUCIBLE",
                "fresh rollout workers disagreed for the same state/query/seed",
            )
        )

    if delta is not None:
        update_request = UpdateRequest(sealed.candidate_input, delta, seed + 3)
        try:
            update_a = fresh.invoke(update_request)
            update_b = fresh.invoke(update_request)
        except WorkerInvocationError as error:
            findings.append(_failure_from_worker(error, "C21/C22-fresh-update"))
            return _report(entrypoint, findings, records)
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
        elif update_a.response.to_wire() != update_b.response.to_wire():
            findings.append(
                ComplianceFinding(
                    "C22/C30-update-replay",
                    ComplianceVerdict.FAIL,
                    "UCM-F020-NONREPRODUCIBLE",
                    "fresh update workers disagreed for the same state/delta/seed",
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
        try:
            warm = InProcessExecutor(_load_candidate(entrypoint))
            warm_init = warm.invoke(InitializeRequest(history, seed))
            if type(warm_init.response) is not StateResponse:
                raise CandidateCallViolation(
                    "UCM-F008-STATE_NOT_CLOSED", "warm initialize returned no state"
                )
            warm_state = CandidateStateInput(warm_init.response.state)
            warm_diagnosis = warm.invoke(
                DiagnoseRequest(warm_state, diagnosis_query, seed + 1)
            )
            warm_rollout = warm.invoke(
                RolloutRequest(warm_state, rollout_query, seed + 2)
            )
            if (
                warm_init.response.to_wire() != init_a.response.to_wire()
                or warm_diagnosis.response.to_wire()
                != diagnosis_a.outcome.response.to_wire()
                or warm_rollout.response.to_wire()
                != rollout_a.outcome.response.to_wire()
            ):
                findings.append(
                    ComplianceFinding(
                        "C04/C05/C15-warm-cold-equivalence",
                        ComplianceVerdict.FAIL,
                        "UCM-F006-HIDDEN_PATIENT_CACHE",
                        "warm and fresh workers disagree; state payload is not the full closure",
                    )
                )
        except WorkerInvocationError as error:
            findings.append(_failure_from_worker(error, "C04-warm-cold-equivalence"))
        except Exception as error:
            findings.append(_failure_from_exception(error, "C16-query-purity"))

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
    return _report(entrypoint, findings, records)


def control_entrypoint(
    control_name: str, *, bundle_root: Path | None = None
) -> CandidateEntrypoint:
    """Return an importable entrypoint for one built-in mutation control."""

    allowed = {
        "HonestSeededControl",
        "GlobalSecondStateControl",
        "RawHistoryHeadControl",
        "QueryMutatorControl",
        "ImplicitRNGControl",
    }
    if control_name not in allowed:
        raise ProtocolViolation(f"unknown compliance control {control_name!r}")
    root = bundle_root or Path(__file__).resolve().parents[2]
    return CandidateEntrypoint(
        bundle_root=root,
        module="prototype.unified_map.compliance",
        qualname=control_name,
    )
