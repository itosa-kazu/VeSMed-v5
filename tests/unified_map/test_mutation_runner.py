from __future__ import annotations

from prototype.unified_map.mutation_matrix import evaluate_mutation_matrix
from prototype.unified_map.mutation_runner import run_portable_mutation_evidence
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


CATALOG = "sha256:" + "c" * 64
UTILITY = "sha256:" + "d" * 64


def inputs() -> tuple[VisibleHistory, DiagnosisQuery, RolloutQuery, VisibleDelta]:
    event = CandidateVisibleEvent(
        EventKind.OBSERVATION_AVAILABLE,
        occurred_at=0,
        available_at=0,
        event_uid="portable-mutation-initial",
        payload={"signal": 0.88},
    )
    follow_up = CandidateVisibleEvent(
        EventKind.OBSERVATION_AVAILABLE,
        occurred_at=1,
        available_at=1,
        event_uid="portable-mutation-update",
        payload={"signal": 0.24},
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
        VisibleDelta(1, (follow_up,)),
    )


def test_portable_mutants_emit_real_decisive_records_and_control_passes() -> None:
    history, diagnosis, rollout, delta = inputs()
    rows = run_portable_mutation_evidence(
        history=history,
        diagnosis_query=diagnosis,
        rollout_query=rollout,
        delta=delta,
        seed=701,
    )
    by_id = {row.subject_id: row for row in rows}
    assert by_id["GlobalSecondState"].actual_failure_code == (
        "UCM-F006-HIDDEN_PATIENT_CACHE"
    )
    assert by_id["RawHistoryHead"].actual_failure_code == (
        "UCM-F004-HEAD_HISTORY_ACCESS"
    )
    assert by_id["CounterfactualMutator"].actual_failure_code == (
        "UCM-F012-QUERY_MUTATES_FACT"
    )
    assert by_id["ImplicitRNGState"].actual_failure_code == (
        "UCM-F020-NONREPRODUCIBLE"
    )
    assert all(row.decisive_record_digest is not None for row in rows)
    assert by_id["ExplicitSeedStochasticState"].outcome.value == "passed"


def test_partial_real_evidence_remains_harness_incomplete() -> None:
    history, diagnosis, rollout, delta = inputs()
    report = evaluate_mutation_matrix(
        run_portable_mutation_evidence(
            history=history,
            diagnosis_query=diagnosis,
            rollout_query=rollout,
            delta=delta,
            seed=733,
        )
    )
    assert not report.freeze_ready
    assert report.benchmark_status == "HARNESS_INCOMPLETE"
    assert set(report.valid_kills) == {
        "GlobalSecondState",
        "RawHistoryHead",
        "CounterfactualMutator",
        "ImplicitRNGState",
    }
    assert set(report.covered_gates) == {"C02", "C04", "C16", "C30"}
    assert set(report.passed_specificity_controls) == {
        "ExplicitSeedStochasticState"
    }
