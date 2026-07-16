from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import prototype.unified_map.compliance as compliance
from prototype.unified_map.canonical import canonical_json_bytes, digest_bytes
from prototype.unified_map.candidate_protocol import (
    CandidateEntrypoint,
    DiagnoseRequest,
    InProcessExecutor,
    InitializeRequest,
    InvocationOutcome,
    RolloutRequest,
    StateResponse,
    UpdateRequest,
    WorkerInvocationError,
)
from prototype.unified_map.compliance import HonestSeededControl
from prototype.unified_map.schema import (
    ActionPlan,
    CandidateVisibleEvent,
    DiagnosisQuery,
    EventKind,
    PlanKind,
    RolloutQuery,
    VisibleDelta,
    VisibleHistory,
)
from prototype.unified_map.state import CandidateStateInput


CATALOG = "sha256:" + "1" * 64
UTILITY = "sha256:" + "2" * 64


def _history() -> VisibleHistory:
    return VisibleHistory(
        (
            CandidateVisibleEvent(
                EventKind.OBSERVATION_AVAILABLE,
                occurred_at=0,
                available_at=0,
                event_uid="event-0",
                payload={"signal": 0.75},
            ),
        ),
        as_of_available_at=0,
        catalog_digest=CATALOG,
    )


def _diagnosis_query() -> DiagnosisQuery:
    return DiagnosisQuery(("class.a", "class.b"))


def _rollout_query() -> RolloutQuery:
    return RolloutQuery(
        horizon=2,
        plan=ActionPlan(PlanKind.NO_NEW_ACTION),
        requested_observables=("observable.x",),
        utility_digest=UTILITY,
    )


def _success_requests() -> tuple[object, ...]:
    candidate = HonestSeededControl()
    payload = candidate.initialize(_history(), inference_seed=7)
    state = CandidateStateInput(payload)
    return (
        InitializeRequest(_history(), 7),
        DiagnoseRequest(state, _diagnosis_query(), 8),
        RolloutRequest(state, _rollout_query(), 9),
        UpdateRequest(state, VisibleDelta(advance_to=1), 10),
    )


def test_observed_executor_records_closed_full_wire_lineage_for_all_operations() -> None:
    collector = compliance._ExecutionBindingCollector()
    executor = compliance._BindingObservedExecutor(
        InProcessExecutor(HonestSeededControl()), collector
    )

    outcomes = tuple(executor.invoke(request) for request in _success_requests())

    assert len(outcomes) == 4
    assert [row["operation"] for row in collector.request_records] == [
        "initialize",
        "diagnose",
        "rollout",
        "update",
    ]
    exact_keys = {
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
    for row in collector.request_records:
        assert set(row) == exact_keys
        assert row["status"] == "success"
        assert row["request_fully_sent"] is True
        assert row["received_request_digest"] == row["request_digest"]
        assert row["request_digest"] == digest_bytes(
            canonical_json_bytes(row["request_wire"])
        )
        assert row["response_digest"] == digest_bytes(
            canonical_json_bytes(row["response_wire"])
        )
        assert row["failure_origin"] is None
        assert row["failure_code"] is None
    assert collector.request_records[0]["response_wire"]["state"]
    assert collector.request_records[1]["request_wire"]["state"]
    assert collector.request_records[2]["request_wire"]["state"]
    assert collector.request_records[3]["request_wire"]["state"]
    assert collector.request_records[3]["request_wire"]["delta"]
    assert collector.request_records[3]["response_wire"]["state"]


def test_candidate_failure_retains_attempted_request_and_survives_early_report() -> None:
    class CandidateFailure:
        def invoke(self, request: object) -> InvocationOutcome:
            encoded = canonical_json_bytes(request.to_wire())  # type: ignore[attr-defined]
            request_digest = digest_bytes(encoded)
            raise WorkerInvocationError(
                "candidate rejected request",
                failure_code="UCM-F008-STATE_NOT_CLOSED",
                failure_origin="candidate",
                request_digest=request_digest,
                request_fully_sent=True,
                received_request_digest=request_digest,
            )

    collector = compliance._ExecutionBindingCollector()
    executor = compliance._BindingObservedExecutor(CandidateFailure(), collector)
    request = InitializeRequest(_history(), 17)
    with pytest.raises(WorkerInvocationError) as captured:
        executor.invoke(request)

    assert captured.value.failure_origin == "candidate"
    assert collector.request_records[0]["status"] == "worker_error"
    assert collector.request_records[0]["request_wire"] == request.to_wire()
    report = compliance._report(
        CandidateEntrypoint(Path.cwd(), "prototype.unified_map.compliance", "HonestSeededControl"),
        [],
        [],
        collector,
    )
    assert report.request_records == tuple(collector.request_records)


def test_observed_request_wire_is_disjoint_from_mutable_delegate_use() -> None:
    class MutatingFailure:
        def invoke(self, request: InitializeRequest) -> InvocationOutcome:
            encoded = canonical_json_bytes(request.to_wire())
            request_digest = digest_bytes(encoded)
            request.history.events[0].payload["signal"] = 0.01
            raise WorkerInvocationError(
                "mutated after capture",
                failure_code="UCM-F012-QUERY_MUTATES_FACT",
                failure_origin="candidate",
                request_digest=request_digest,
                request_fully_sent=True,
                received_request_digest=request_digest,
            )

    collector = compliance._ExecutionBindingCollector()
    executor = compliance._BindingObservedExecutor(MutatingFailure(), collector)
    request = InitializeRequest(_history(), 18)
    with pytest.raises(WorkerInvocationError):
        executor.invoke(request)

    assert request.history.events[0].payload["signal"] == 0.75
    assert collector.request_records[0]["request_wire"]["history"]["events"][0][
        "payload"
    ]["signal"] == 0.75


@pytest.mark.parametrize("field", ["request_digest", "response_digest"])
def test_success_digest_mismatch_is_e003_with_non_success_record(field: str) -> None:
    class Mismatch:
        def __init__(self) -> None:
            self.delegate = InProcessExecutor(HonestSeededControl())

        def invoke(self, request: object) -> InvocationOutcome:
            outcome = self.delegate.invoke(request)  # type: ignore[arg-type]
            return replace(outcome, **{field: "sha256:" + "0" * 64})

    collector = compliance._ExecutionBindingCollector()
    executor = compliance._BindingObservedExecutor(Mismatch(), collector)
    with pytest.raises(WorkerInvocationError) as captured:
        executor.invoke(InitializeRequest(_history(), 19))

    assert captured.value.failure_origin == "harness"
    assert captured.value.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert len(collector.request_records) == 1
    record = collector.request_records[0]
    assert record["status"] == "harness_error"
    assert record["failure_origin"] == "harness"
    assert record["failure_code"] == "UCM-E003-HARNESS_INCOMPLETE"
    assert record["response_wire"] is not None
    assert record["response_digest"] is not None


def test_observed_sequential_records_each_exact_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _success_requests()[:3]

    class LocalSequential:
        def __init__(self, _entrypoint: object, *, timeout_seconds: float) -> None:
            assert timeout_seconds == 3.0
            self.delegate = InProcessExecutor(HonestSeededControl())

        def invoke_sequence(self, frozen: tuple[object, ...]) -> tuple[InvocationOutcome, ...]:
            return tuple(self.delegate.invoke(request) for request in frozen)  # type: ignore[arg-type]

    monkeypatch.setattr(compliance, "SequentialProcessExecutor", LocalSequential)
    collector = compliance._ExecutionBindingCollector()
    outcomes = compliance._invoke_observed_sequence(
        CandidateEntrypoint(Path.cwd(), "prototype.unified_map.compliance", "HonestSeededControl"),
        requests,
        collector,
        timeout_seconds=3.0,
    )

    assert len(outcomes) == len(requests)
    assert [row["status"] for row in collector.request_records] == [
        "success",
        "success",
        "success",
    ]
    assert all(
        row["execution_mode"] == "sequential"
        for row in collector.request_records
    )


def test_inconsistent_sequential_prefix_cannot_duplicate_a_success_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _success_requests()[:2]

    class InconsistentSequential:
        def __init__(self, _entrypoint: object, *, timeout_seconds: float) -> None:
            del timeout_seconds

        def invoke_sequence(self, frozen: tuple[object, ...]) -> tuple[InvocationOutcome, ...]:
            first = InProcessExecutor(HonestSeededControl()).invoke(frozen[0])  # type: ignore[arg-type]
            first_digest = digest_bytes(canonical_json_bytes(frozen[0].to_wire()))  # type: ignore[attr-defined]
            raise WorkerInvocationError(
                "inconsistent prefix index",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                failure_origin="harness",
                request_digest=first_digest,
                request_fully_sent=True,
                received_request_digest=first_digest,
                request_index=0,
                completed_outcomes=(first,),
            )

    monkeypatch.setattr(
        compliance, "SequentialProcessExecutor", InconsistentSequential
    )
    collector = compliance._ExecutionBindingCollector()
    with pytest.raises(WorkerInvocationError) as captured:
        compliance._invoke_observed_sequence(
            CandidateEntrypoint(Path.cwd(), "prototype.unified_map.compliance", "HonestSeededControl"),
            requests,
            collector,
            timeout_seconds=3.0,
        )

    assert captured.value.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert [(row["seed"], row["status"]) for row in collector.request_records] == [
        (requests[0].seed, "success"),  # type: ignore[attr-defined]
        (requests[1].seed, "harness_error"),  # type: ignore[attr-defined]
    ]


def test_sequential_close_error_does_not_fabricate_duplicate_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _success_requests()[:2]

    class CloseFailureSequential:
        def __init__(self, _entrypoint: object, *, timeout_seconds: float) -> None:
            del timeout_seconds

        def invoke_sequence(self, frozen: tuple[object, ...]) -> tuple[InvocationOutcome, ...]:
            delegate = InProcessExecutor(HonestSeededControl())
            completed = tuple(delegate.invoke(request) for request in frozen)  # type: ignore[arg-type]
            raise WorkerInvocationError(
                "close failed",
                failure_code="UCM-E003-HARNESS_INCOMPLETE",
                failure_origin="harness",
                completed_outcomes=completed,
            )

    monkeypatch.setattr(
        compliance, "SequentialProcessExecutor", CloseFailureSequential
    )
    collector = compliance._ExecutionBindingCollector()
    with pytest.raises(WorkerInvocationError):
        compliance._invoke_observed_sequence(
            CandidateEntrypoint(Path.cwd(), "prototype.unified_map.compliance", "HonestSeededControl"),
            requests,
            collector,
            timeout_seconds=3.0,
        )

    assert [(row["seed"], row["status"]) for row in collector.request_records] == [
        (requests[0].seed, "success"),  # type: ignore[attr-defined]
        (requests[1].seed, "success"),  # type: ignore[attr-defined]
    ]


def test_report_rejects_nonclosed_request_record_as_e003() -> None:
    collector = compliance._ExecutionBindingCollector()
    collector.request_records.append({"extra": "accepted"})

    report = compliance._report(
        CandidateEntrypoint(Path.cwd(), "prototype.unified_map.compliance", "HonestSeededControl"),
        [],
        [],
        collector,
    )

    assert report.request_records == ()
    finding = next(
        item
        for item in report.findings
        if item.gate == "harness-request-record-serialization"
    )
    assert finding.failure_code == "UCM-E003-HARNESS_INCOMPLETE"
    assert report.operational_state_closure is compliance.ComplianceVerdict.INCOMPLETE


def test_report_request_record_view_cannot_mutate_authoritative_snapshot() -> None:
    collector = compliance._ExecutionBindingCollector()
    executor = compliance._BindingObservedExecutor(
        InProcessExecutor(HonestSeededControl()), collector
    )
    executor.invoke(InitializeRequest(_history(), 22))
    report = compliance._report(
        CandidateEntrypoint(Path.cwd(), "prototype.unified_map.compliance", "HonestSeededControl"),
        [],
        [],
        collector,
    )
    digest_before = report.request_records_digest
    view = report.request_records
    view[0]["status"] = "harness_error"

    assert report.request_records[0]["status"] == "success"
    assert report.request_records_digest == digest_before


@pytest.mark.parametrize(
    ("received", "expected_gate"),
    [
        (None, "request-transcript-error-consistency"),
        ("sha256:" + "0" * 64, "harness-request-record-serialization"),
    ],
)
def test_harness_error_record_can_never_yield_operational_pass(
    received: str | None,
    expected_gate: str,
) -> None:
    collector = compliance._ExecutionBindingCollector()
    executor = compliance._BindingObservedExecutor(
        InProcessExecutor(HonestSeededControl()), collector
    )
    executor.invoke(InitializeRequest(_history(), 24))
    row = dict(collector.request_records[0])
    row.update(
        {
            "status": "harness_error",
            "received_request_digest": received,
            "response_wire": None,
            "response_digest": None,
            "failure_origin": "harness",
            "failure_code": "UCM-E003-HARNESS_INCOMPLETE",
        }
    )
    collector.request_records[:] = [row]
    collector.observed = 1
    collector.candidate_bundle_digest = "sha256:" + "a" * 64
    collector.candidate_model_digest = "sha256:" + "b" * 64
    collector.harness_bundle_digest = "sha256:" + "c" * 64
    collector.import_inventory_digest = "sha256:" + "d" * 64
    collector.module_origin = "candidate.py"
    collector.violations.clear()

    report = compliance._report(
        CandidateEntrypoint(Path.cwd(), "prototype.unified_map.compliance", "HonestSeededControl"),
        [],
        [],
        collector,
    )

    assert report.operational_state_closure is compliance.ComplianceVerdict.INCOMPLETE
    assert any(finding.gate == expected_gate for finding in report.findings)


def test_live_compliance_report_retains_actual_fresh_and_sequential_transcript() -> None:
    report = compliance.evaluate_candidate_compliance(
        compliance.control_entrypoint("HonestSeededControl"),
        history=_history(),
        diagnosis_query=_diagnosis_query(),
        rollout_query=_rollout_query(),
        delta=VisibleDelta(advance_to=1),
        seed=23,
    )

    assert report.request_records
    assert {row["operation"] for row in report.request_records} == {
        "initialize",
        "diagnose",
        "rollout",
        "update",
    }
    assert {row["execution_mode"] for row in report.request_records} == {
        "fresh",
        "sequential",
    }
    assert all(row["status"] == "success" for row in report.request_records)
    assert all(
        row["request_digest"]
        == digest_bytes(canonical_json_bytes(row["request_wire"]))
        == row["received_request_digest"]
        for row in report.request_records
    )
    assert all(
        row["response_digest"]
        == digest_bytes(canonical_json_bytes(row["response_wire"]))
        for row in report.request_records
    )
