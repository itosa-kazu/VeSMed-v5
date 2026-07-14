from __future__ import annotations

import pytest

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
    VisibleHistory,
)


CATALOG = "sha256:" + "c" * 64
UTILITY = "sha256:" + "d" * 64


def inputs() -> tuple[VisibleHistory, DiagnosisQuery, RolloutQuery]:
    event = CandidateVisibleEvent(
        EventKind.OBSERVATION_AVAILABLE,
        occurred_at=0,
        available_at=0,
        event_uid="probe",
        payload={"signal": 0.91},
    )
    return (
        VisibleHistory((event,), 0, CATALOG),
        DiagnosisQuery(("a", "b")),
        RolloutQuery(
            2,
            ActionPlan(PlanKind.NO_NEW_ACTION),
            ("x",),
            UTILITY,
        ),
    )


@pytest.mark.parametrize(
    ("control", "expected_code"),
    [
        ("GlobalSecondStateControl", "UCM-F006-HIDDEN_PATIENT_CACHE"),
        ("RawHistoryHeadControl", "UCM-F004-HEAD_HISTORY_ACCESS"),
        ("QueryMutatorControl", "UCM-F012-QUERY_MUTATES_FACT"),
        ("ImplicitRNGControl", "UCM-F020-NONREPRODUCIBLE"),
    ],
)
def test_each_malicious_control_is_killed_by_its_semantic_gate(
    control: str, expected_code: str
) -> None:
    history, diagnosis, rollout = inputs()
    report = evaluate_candidate_compliance(
        control_entrypoint(control),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=53,
    )
    assert report.operational_state_closure is ComplianceVerdict.FAIL
    assert expected_code in report.failure_codes


def test_raw_history_attack_has_decisive_audit_evidence() -> None:
    history, diagnosis, rollout = inputs()
    report = evaluate_candidate_compliance(
        control_entrypoint("RawHistoryHeadControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=59,
    )
    finding = next(
        row
        for row in report.findings
        if row.failure_code == "UCM-F004-HEAD_HISTORY_ACCESS"
    )
    assert finding.evidence["audit_events"]
    assert finding.evidence["audit_events"][0]["event"] == "open"


def test_explicit_seed_specificity_control_is_not_false_positive() -> None:
    history, diagnosis, rollout = inputs()
    report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        seed=61,
    )
    assert report.operational_state_closure is ComplianceVerdict.PASS
    assert report.failure_codes == ()
