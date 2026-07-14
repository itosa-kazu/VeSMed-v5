from __future__ import annotations

import json

import pytest

from prototype.unified_map.canonical import ProtocolViolation, digest_json
from prototype.unified_map.mutation_matrix import (
    GATE_SPECS,
    MUTANT_SPECS,
    SPECIFICITY_CONTROLS,
    MutationObservation,
    ObservationOutcome,
    SubjectKind,
    evaluate_mutation_matrix,
)


SOURCE = "sha256:" + "a" * 64
RECORD = "sha256:" + "b" * 64


def kill(mutant_id: str, gate: str | None = None) -> MutationObservation:
    spec = next(row for row in MUTANT_SPECS if row.mutant_id == mutant_id)
    selected = gate or spec.expected_gates[0]
    return MutationObservation(
        mutant_id,
        SubjectKind.MUTANT,
        SOURCE,
        17,
        ObservationOutcome.KILLED,
        selected,
        spec.expected_failure_codes[0],
        RECORD,
    )


def pass_control(control_id: str) -> MutationObservation:
    spec = next(row for row in SPECIFICITY_CONTROLS if row.control_id == control_id)
    return MutationObservation(
        control_id,
        SubjectKind.SPECIFICITY_CONTROL,
        SOURCE,
        19,
        ObservationOutcome.PASSED,
        None,
        None,
        RECORD,
        spec.allowed_classification,
    )


def test_empty_matrix_is_fail_closed_and_lists_all_missing_evidence() -> None:
    report = evaluate_mutation_matrix(())
    assert not report.freeze_ready
    assert report.benchmark_status == "HARNESS_INCOMPLETE"
    assert set(report.missing_or_invalid_mutants) == {
        row.mutant_id for row in MUTANT_SPECS
    }
    assert report.uncovered_gates == tuple(f"C{index:02d}" for index in range(1, 34))
    assert set(report.failed_specificity_controls) == {
        row.control_id for row in SPECIFICITY_CONTROLS
    }


def test_crash_or_unrelated_failure_is_not_a_valid_kill() -> None:
    bad = MutationObservation(
        "RawHistoryHead",
        SubjectKind.MUTANT,
        SOURCE,
        23,
        ObservationOutcome.CRASHED,
        "C02",
        "UCM-F004-HEAD_HISTORY_ACCESS",
        RECORD,
    )
    wrong = MutationObservation(
        "RawHistoryHead",
        SubjectKind.MUTANT,
        SOURCE,
        29,
        ObservationOutcome.KILLED,
        "C16",
        "UCM-F012-QUERY_MUTATES_FACT",
        RECORD,
    )
    report = evaluate_mutation_matrix((bad, wrong))
    assert "RawHistoryHead" in report.missing_or_invalid_mutants
    assert "C02" in report.uncovered_gates


def test_specificity_rejection_prevents_freeze_even_when_classified_baseline() -> None:
    row = MutationObservation(
        "DeclaredFullHistoryBaseline",
        SubjectKind.SPECIFICITY_CONTROL,
        SOURCE,
        31,
        ObservationOutcome.REJECTED,
        "C27",
        "UCM-F018-FULL_HISTORY_MISCLAIM",
        RECORD,
        "baseline_only",
    )
    report = evaluate_mutation_matrix((row,))
    assert "DeclaredFullHistoryBaseline" in report.failed_specificity_controls
    assert not report.freeze_ready


def test_every_gate_requires_an_actual_decisive_record() -> None:
    # Produce at least one valid kill per mutant, then add targeted executions
    # until every gate has a decisive record.  This is registry mechanics only;
    # real freeze evidence must come from actual detector transcripts.
    rows = [kill(spec.mutant_id) for spec in MUTANT_SPECS]
    covered = {row.actual_gate for row in rows}
    for gate_spec in GATE_SPECS:
        if gate_spec.gate_id in covered:
            continue
        mutant = next(
            spec for spec in MUTANT_SPECS if gate_spec.gate_id in spec.expected_gates
        )
        rows.append(
            MutationObservation(
                mutant.mutant_id,
                SubjectKind.MUTANT,
                digest_json({"source": mutant.mutant_id, "gate": gate_spec.gate_id}),
                100 + int(gate_spec.gate_id[1:]),
                ObservationOutcome.KILLED,
                gate_spec.gate_id,
                next(
                    code
                    for code in mutant.expected_failure_codes
                    if code in gate_spec.allowed_failure_codes
                ),
                digest_json({"record": gate_spec.gate_id}),
            )
        )
    rows.extend(pass_control(spec.control_id) for spec in SPECIFICITY_CONTROLS)
    report = evaluate_mutation_matrix(rows)
    assert report.freeze_ready
    assert report.uncovered_gates == ()
    wire = report.to_wire()
    assert wire["benchmark_status"] == "MUTATION-GATES-PASS"
    assert json.loads(report.canonical_bytes()) == wire


def test_duplicate_observation_identity_is_rejected() -> None:
    row = kill("RawHistoryHead")
    with pytest.raises(ProtocolViolation, match="duplicate"):
        evaluate_mutation_matrix((row, row))


def test_registry_has_exact_c01_c33_and_declared_contract_subjects() -> None:
    assert tuple(row.gate_id for row in GATE_SPECS) == tuple(
        f"C{index:02d}" for index in range(1, 34)
    )
    assert len(MUTANT_SPECS) == 26
    assert {row.control_id for row in SPECIFICITY_CONTROLS} == {
        "ExplicitSeedStochasticState",
        "BehaviorEquivalentSerialization",
        "DeclaredFullHistoryBaseline",
        "CorrectNonidentifiedSet",
    }
