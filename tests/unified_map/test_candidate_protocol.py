from __future__ import annotations

from pathlib import Path

import pytest

from prototype.unified_map.canonical import ProtocolViolation
from prototype.unified_map.candidate_protocol import (
    CandidateEntrypoint,
    DiagnoseRequest,
    DiagnoseResponse,
    FreshProcessExecutor,
    InProcessExecutor,
    InitializeRequest,
    Operation,
    ResultStatus,
    RolloutRequest,
    StateResponse,
    UpdateRequest,
    assert_shared_state_fanout,
    invoke_diagnose,
    invoke_rollout,
    request_from_wire,
    response_from_wire,
)
from prototype.unified_map.compliance import (
    HonestSeededControl,
    QueryMutatorControl,
    control_entrypoint,
)
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
from prototype.unified_map.state import CandidateStateInput, seal_state


CATALOG = "sha256:" + "1" * 64
UTILITY = "sha256:" + "2" * 64
CANDIDATE = "sha256:" + "3" * 64
MODEL = "sha256:" + "4" * 64
SCOPE = "sha256:" + "5" * 64


def test_result_statuses_match_the_frozen_wire_vocabulary() -> None:
    assert {status.value for status in ResultStatus} == {
        "ok",
        "abstain",
        "scope_insufficient",
        "unsupported",
        "invalid_input",
        "numerical_failure",
    }


def history() -> VisibleHistory:
    return VisibleHistory(
        (
            CandidateVisibleEvent(
                EventKind.OBSERVATION_AVAILABLE,
                occurred_at=0,
                available_at=0,
                event_uid="event-0",
                payload={"signal": 0.8},
            ),
        ),
        as_of_available_at=0,
        catalog_digest=CATALOG,
    )


def diagnosis_query() -> DiagnosisQuery:
    return DiagnosisQuery(("class.a", "class.b"))


def rollout_query() -> RolloutQuery:
    return RolloutQuery(
        horizon=2,
        plan=ActionPlan(PlanKind.NO_NEW_ACTION),
        requested_observables=("observable.x",),
        utility_digest=UTILITY,
    )


def test_operation_envelopes_are_exact_and_state_producers_are_task_blind() -> None:
    init = InitializeRequest(history(), 7)
    init_wire = init.to_wire()
    assert set(init_wire) == {"protocol", "operation", "seed", "history"}
    assert "query" not in init_wire and "task" not in init_wire
    assert request_from_wire(init_wire) == init

    state = HonestSeededControl().initialize(history(), inference_seed=7)
    update = UpdateRequest(
        CandidateStateInput(state), VisibleDelta(advance_to=1), seed=8
    )
    update_wire = update.to_wire()
    assert set(update_wire) == {"protocol", "operation", "seed", "state", "delta"}
    assert "history" not in update_wire and "query" not in update_wire
    assert request_from_wire(update_wire) == update

    smuggled = dict(init_wire)
    smuggled["query"] = diagnosis_query().to_wire()
    with pytest.raises(ProtocolViolation, match="extra=.*query"):
        request_from_wire(smuggled)


@pytest.mark.parametrize("seed", [None, True, -1, 2**64])
def test_all_operations_require_an_explicit_uint64_seed(seed: object) -> None:
    with pytest.raises(ProtocolViolation, match="seed"):
        InitializeRequest(history(), seed)  # type: ignore[arg-type]


def test_head_response_schema_cannot_return_new_patient_state() -> None:
    bad = {
        "protocol": "ucm-candidate-response/1",
        "operation": "diagnose",
        "result": {
            "status": "ok",
            "probabilities": {"class.a": 0.5, "class.b": 0.5},
            "metadata": {"state_payload": "second-state"},
        },
    }
    with pytest.raises(ProtocolViolation, match="cannot return patient state"):
        response_from_wire(bad)


def test_inprocess_heads_are_pure_and_record_one_harness_state_hash() -> None:
    payload = HonestSeededControl().initialize(history(), inference_seed=9)
    sealed = seal_state(
        payload,
        candidate_bundle_digest=CANDIDATE,
        model_digest=MODEL,
        scope_digest=SCOPE,
        catalog_digest=CATALOG,
        as_of_available_at=0,
        operation="initialize",
        state_instance_id="protocol-test",
    )
    before = sealed.candidate_input.payload.payload
    executor = InProcessExecutor(HonestSeededControl())
    diagnose = invoke_diagnose(executor, sealed, diagnosis_query(), seed=11)
    rollout = invoke_rollout(executor, sealed, rollout_query(), seed=12)

    assert type(diagnose.outcome.response) is DiagnoseResponse
    assert assert_shared_state_fanout((diagnose, rollout)) == sealed.record.state_hash
    assert diagnose.record.consumed_state_hash == rollout.record.consumed_state_hash
    assert sealed.candidate_input.payload.payload == before


def test_dispatch_detects_candidate_mutation_of_query() -> None:
    state = HonestSeededControl().initialize(history(), inference_seed=3)
    executor = InProcessExecutor(QueryMutatorControl())
    request = RolloutRequest(CandidateStateInput(state), rollout_query(), seed=4)
    with pytest.raises(ProtocolViolation, match="mutated"):
        executor.invoke(request)


def test_fresh_executor_rehydrates_state_without_initializer_process() -> None:
    executor = FreshProcessExecutor(control_entrypoint("HonestSeededControl"))
    initialized = executor.invoke(InitializeRequest(history(), seed=21))
    assert type(initialized.response) is StateResponse
    diagnosed = executor.invoke(
        DiagnoseRequest(
            CandidateStateInput(initialized.response.state),
            diagnosis_query(),
            seed=22,
        )
    )
    rolled = executor.invoke(
        RolloutRequest(
            CandidateStateInput(initialized.response.state),
            rollout_query(),
            seed=23,
        )
    )
    assert type(diagnosed.response) is DiagnoseResponse
    assert diagnosed.worker_pid != rolled.worker_pid
    assert diagnosed.isolation == "fresh-python-process-audit-v1"
    assert diagnosed.audit_events == ()


def test_entrypoint_rejects_non_identifier_target(tmp_path: Path) -> None:
    with pytest.raises(ProtocolViolation, match="dotted identifiers"):
        CandidateEntrypoint(tmp_path, "candidate;import os", "Factory")
