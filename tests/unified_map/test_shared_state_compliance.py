from __future__ import annotations

import ast
import inspect

import prototype.unified_map.compliance as compliance
from prototype.unified_map.compliance import (
    ComplianceVerdict,
    control_entrypoint,
    evaluate_candidate_compliance,
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


CATALOG = "sha256:" + "a" * 64
UTILITY = "sha256:" + "b" * 64


def test_portable_sequence_probes_share_one_source_bound_timeout_budget() -> None:
    assert compliance.PORTABLE_COMPLIANCE_PROBE_TIMEOUT_SECONDS == 20.0

    evaluate_tree = ast.parse(
        inspect.getsource(compliance.evaluate_candidate_compliance)
    )
    probe_calls: dict[str, ast.Call] = {}
    for node in ast.walk(evaluate_tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "_invoke_observed_sequence"
        ):
            probe_calls[node.targets[0].id] = node.value

    # The two late/future warm sequences and C04 warm/cold sequence must not
    # silently acquire different machine-sensitive budgets.
    assert set(probe_calls) == {
        "initialize_sequence",
        "update_sequence",
        "warm_sequence",
    }
    for call in probe_calls.values():
        timeout = next(
            keyword.value
            for keyword in call.keywords
            if keyword.arg == "timeout_seconds"
        )
        assert isinstance(timeout, ast.Name)
        assert timeout.id == "PORTABLE_COMPLIANCE_PROBE_TIMEOUT_SECONDS"

    # The helper still forwards an explicit caller deadline.  This keeps the
    # short-deadline candidate-protocol tests independent of the probe budget.
    helper_tree = ast.parse(inspect.getsource(compliance._invoke_observed_sequence))
    executor_calls = [
        node
        for node in ast.walk(helper_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "SequentialProcessExecutor"
    ]
    assert len(executor_calls) == 1
    forwarded = next(
        keyword.value
        for keyword in executor_calls[0].keywords
        if keyword.arg == "timeout_seconds"
    )
    assert isinstance(forwarded, ast.Name)
    assert forwarded.id == "timeout_seconds"


def fixture_inputs() -> tuple[
    VisibleHistory, DiagnosisQuery, RolloutQuery, VisibleDelta
]:
    initial = CandidateVisibleEvent(
        EventKind.OBSERVATION_AVAILABLE,
        occurred_at=0,
        available_at=0,
        event_uid="initial",
        payload={"signal": 0.82},
    )
    history = VisibleHistory((initial,), 0, CATALOG)
    diagnosis = DiagnosisQuery(("positive", "negative"))
    rollout = RolloutQuery(
        3,
        ActionPlan(PlanKind.NO_NEW_ACTION),
        ("measurement",),
        UTILITY,
    )
    delta_event = CandidateVisibleEvent(
        EventKind.OBSERVATION_AVAILABLE,
        occurred_at=1,
        available_at=1,
        event_uid="follow-up",
        payload={"signal": 0.21},
    )
    return history, diagnosis, rollout, VisibleDelta(1, (delta_event,))


def test_honest_control_passes_operational_closure_but_not_semantic_proof() -> None:
    history, diagnosis, rollout, delta = fixture_inputs()
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=31,
    )
    assert report.operational_state_closure is ComplianceVerdict.PASS
    assert report.semantic_unity is ComplianceVerdict.INCOMPLETE
    assert report.isolation_completeness is ComplianceVerdict.INCOMPLETE
    assert report.failure_codes == ()
    assert "kernel/native escape not excluded" in report.isolation_assurance
    incomplete_codes = {
        finding.failure_code
        for finding in report.findings
        if finding.verdict is ComplianceVerdict.INCOMPLETE
    }
    assert incomplete_codes == {
        "UCM-E001-SEMANTIC_UNITY_UNVERIFIED",
        "UCM-E002-ISOLATION_INCOMPLETE",
    }
    assert len({row["consumed_state_hash"] for row in report.head_records}) == 1


def test_global_patient_cache_is_killed_by_warm_cold_closure_check() -> None:
    history, diagnosis, rollout, _ = fixture_inputs()
    report = evaluate_candidate_compliance(
        control_entrypoint("GlobalSecondStateControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=37,
    )
    assert report.operational_state_closure is ComplianceVerdict.FAIL
    assert "UCM-F006-HIDDEN_PATIENT_CACHE" in report.failure_codes


def test_no_query_preannouncement_is_an_envelope_invariant() -> None:
    history, diagnosis, rollout, _ = fixture_inputs()
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=41,
    )
    finding = next(
        row for row in report.findings if row.gate == "C03/C29-task-blind-state-producer"
    )
    assert finding.verdict is ComplianceVerdict.PASS
