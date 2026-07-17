from __future__ import annotations

import json
from dataclasses import replace

import pytest

from prototype.unified_map.canonical import ProtocolViolation, digest_json
from prototype.unified_map.mutation_matrix import (
    EXECUTION_CASE_MAIN_OFFSETS,
    EXECUTION_CASE_SEED_STRIDE,
    GATE_SPECS,
    MUTANT_SPECS,
    PORTABLE_EXECUTION_CASES,
    REGISTRY_DIGEST,
    SPECIFICITY_CONTROLS,
    MutationObservation,
    ObservationOutcome,
    SubjectKind,
    UPDATE_CONSISTENCY_LINEAGE_OFFSETS,
    evaluate_mutation_matrix,
    execution_seed_for_case,
    portable_execution_case,
)


SOURCE = "sha256:" + "a" * 64
RECORD = "sha256:" + "b" * 64
BASE_SEED = 17


def case_for(subject_id: str):
    matches = [case for case in PORTABLE_EXECUTION_CASES if case.subject_id == subject_id]
    assert len(matches) == 1
    return matches[0]


def kill(mutant_id: str) -> MutationObservation:
    case = case_for(mutant_id)
    return MutationObservation(
        subject_id=mutant_id,
        subject_kind=SubjectKind.MUTANT,
        execution_case_id=case.execution_case_id,
        probe_id=case.probe_id,
        source_digest=digest_json({"source": case.execution_case_id}),
        execution_seed=execution_seed_for_case(BASE_SEED, case),
        outcome=ObservationOutcome.KILLED,
        actual_gate=case.expected_gate,
        actual_failure_code=case.expected_failure_code,
        decisive_record_digest=digest_json({"record": case.execution_case_id}),
    )


def pass_control(control_id: str) -> MutationObservation:
    case = case_for(control_id)
    return MutationObservation(
        subject_id=control_id,
        subject_kind=SubjectKind.SPECIFICITY_CONTROL,
        execution_case_id=case.execution_case_id,
        probe_id=case.probe_id,
        source_digest=digest_json({"source": case.execution_case_id}),
        execution_seed=execution_seed_for_case(BASE_SEED, case),
        outcome=ObservationOutcome.PASSED,
        actual_gate=None,
        actual_failure_code=None,
        decisive_record_digest=digest_json({"record": case.execution_case_id}),
        classification=case.classification,
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


def test_crash_is_not_a_valid_kill() -> None:
    case = case_for("RawHistoryHead")
    bad = MutationObservation(
        subject_id=case.subject_id,
        subject_kind=case.subject_kind,
        execution_case_id=case.execution_case_id,
        probe_id=case.probe_id,
        source_digest=SOURCE,
        execution_seed=execution_seed_for_case(BASE_SEED, case),
        outcome=ObservationOutcome.CRASHED,
        actual_gate=case.expected_gate,
        actual_failure_code=case.expected_failure_code,
        decisive_record_digest=None,
    )
    report = evaluate_mutation_matrix((bad,))
    assert "RawHistoryHead" in report.missing_or_invalid_mutants
    assert "C02" in report.uncovered_gates


def test_swapped_case_or_probe_identity_is_rejected() -> None:
    raw = case_for("RawHistoryHead")
    query = case_for("WarmFutureCache")
    row = MutationObservation(
        subject_id=raw.subject_id,
        subject_kind=raw.subject_kind,
        execution_case_id=raw.execution_case_id,
        probe_id=query.probe_id,
        source_digest=SOURCE,
        execution_seed=execution_seed_for_case(BASE_SEED, raw),
        outcome=ObservationOutcome.KILLED,
        actual_gate=raw.expected_gate,
        actual_failure_code=raw.expected_failure_code,
        decisive_record_digest=RECORD,
    )
    with pytest.raises(ProtocolViolation, match="execution case"):
        evaluate_mutation_matrix((row,))


def test_case_gate_and_failure_code_are_exact_not_cross_products() -> None:
    case = case_for("ReplayBatchDivergence")
    crossed = MutationObservation(
        subject_id=case.subject_id,
        subject_kind=case.subject_kind,
        execution_case_id=case.execution_case_id,
        probe_id=case.probe_id,
        source_digest=SOURCE,
        execution_seed=execution_seed_for_case(BASE_SEED, case),
        outcome=ObservationOutcome.KILLED,
        actual_gate="C21",
        actual_failure_code="UCM-F010-UPDATE_NOT_RECURSIVE",
        decisive_record_digest=RECORD,
    )
    report = evaluate_mutation_matrix((crossed,))
    assert "ReplayBatchDivergence" in report.missing_or_invalid_mutants
    assert "C21" in report.uncovered_gates


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("execution_seed", True, "execution_seed"),
        ("actual_gate", True, "actual_gate"),
        ("actual_failure_code", 1, "actual_failure_code"),
    ],
)
def test_observation_is_type_strict(field: str, value: object, message: str) -> None:
    case = case_for("RawHistoryHead")
    kwargs = {
        "subject_id": case.subject_id,
        "subject_kind": case.subject_kind,
        "execution_case_id": case.execution_case_id,
        "probe_id": case.probe_id,
        "source_digest": SOURCE,
        "execution_seed": execution_seed_for_case(BASE_SEED, case),
        "outcome": ObservationOutcome.KILLED,
        "actual_gate": case.expected_gate,
        "actual_failure_code": case.expected_failure_code,
        "decisive_record_digest": RECORD,
    }
    kwargs[field] = value
    with pytest.raises(ProtocolViolation, match=message):
        MutationObservation(**kwargs)


def test_registry_ordinal_seed_schedule_is_not_caller_order() -> None:
    raw = kill("RawHistoryHead")
    query = kill("QueryReencoder")
    shifted = MutationObservation(
        subject_id=query.subject_id,
        subject_kind=query.subject_kind,
        execution_case_id=query.execution_case_id,
        probe_id=query.probe_id,
        source_digest=query.source_digest,
        execution_seed=query.execution_seed + 1,
        outcome=query.outcome,
        actual_gate=query.actual_gate,
        actual_failure_code=query.actual_failure_code,
        decisive_record_digest=query.decisive_record_digest,
    )
    with pytest.raises(ProtocolViolation, match="ordinal seed schedule"):
        evaluate_mutation_matrix((raw, shifted))


def test_specificity_rejection_prevents_freeze() -> None:
    case = case_for("DeclaredFullHistoryBaseline")
    row = MutationObservation(
        subject_id=case.subject_id,
        subject_kind=case.subject_kind,
        execution_case_id=case.execution_case_id,
        probe_id=case.probe_id,
        source_digest=SOURCE,
        execution_seed=execution_seed_for_case(BASE_SEED, case),
        outcome=ObservationOutcome.REJECTED,
        actual_gate=None,
        actual_failure_code=None,
        decisive_record_digest=None,
        classification=case.classification,
    )
    report = evaluate_mutation_matrix((row,))
    assert "DeclaredFullHistoryBaseline" in report.failed_specificity_controls
    assert not report.freeze_ready


def test_registry_cases_drive_kill_aggregation_and_gate_union() -> None:
    rows = [kill(spec.mutant_id) for spec in MUTANT_SPECS]
    rows.extend(pass_control(spec.control_id) for spec in SPECIFICITY_CONTROLS)
    report = evaluate_mutation_matrix(rows)
    expected_covered = tuple(
        sorted(
            {
                case.expected_gate
                for case in PORTABLE_EXECUTION_CASES
                if case.subject_kind is SubjectKind.MUTANT
            }
        )
    )
    assert report.valid_kills == tuple(sorted(spec.mutant_id for spec in MUTANT_SPECS))
    assert report.covered_gates == expected_covered
    assert report.uncovered_gates == tuple(
        sorted({gate.gate_id for gate in GATE_SPECS} - set(expected_covered))
    )
    assert not report.freeze_ready
    wire = report.to_wire()
    assert wire["registry_digest"] == REGISTRY_DIGEST
    assert json.loads(report.canonical_bytes()) == wire


def test_duplicate_execution_case_is_rejected() -> None:
    row = kill("RawHistoryHead")
    with pytest.raises(ProtocolViolation, match="duplicate"):
        evaluate_mutation_matrix((row, row))


def test_matrix_rejects_duck_typed_rows_and_noncanonical_case_schedule() -> None:
    row = kill("RawHistoryHead")

    class DuckRow:
        pass

    duck = DuckRow()
    for field_name in row.__dataclass_fields__:
        setattr(duck, field_name, getattr(row, field_name))
    with pytest.raises(ProtocolViolation, match="exact MutationObservation"):
        evaluate_mutation_matrix((duck,))

    case = case_for("RawHistoryHead")
    forged = replace(case, execution_ordinal=case.execution_ordinal + 1)
    with pytest.raises(ProtocolViolation, match="code-owned registry"):
        execution_seed_for_case(BASE_SEED, forged)


def test_registry_has_exact_inventory_and_contiguous_ordinals() -> None:
    assert tuple(row.gate_id for row in GATE_SPECS) == tuple(
        f"C{index:02d}" for index in range(1, 34)
    )
    assert len(MUTANT_SPECS) == 26
    assert len(SPECIFICITY_CONTROLS) == 4
    assert len(PORTABLE_EXECUTION_CASES) == 30
    assert tuple(case.execution_ordinal for case in PORTABLE_EXECUTION_CASES) == tuple(
        range(30)
    )
    assert len({case.execution_case_id for case in PORTABLE_EXECUTION_CASES}) == 30
    assert all(
        portable_execution_case(case.execution_case_id) is case
        for case in PORTABLE_EXECUTION_CASES
    )
    assert EXECUTION_CASE_SEED_STRIDE == 16
    assert EXECUTION_CASE_MAIN_OFFSETS == (0, 1, 2, 3)
    assert UPDATE_CONSISTENCY_LINEAGE_OFFSETS == (0, 1, 2)
    assert all("C01" not in row.expected_gates for row in MUTANT_SPECS)
    c20 = case_for("ObservationEqualsMechanism")
    assert c20.execution_case_id == (
        "case.mutant.ObservationEqualsMechanism.C20.v1"
    )
    assert c20.probe_id == "C20-observation-state-channel-separation"
    assert c20.semantic_probes == ("observation_channel_separation",)
    assert c20.head_record_shape == "replay_ddrr"
    assert c20.expected_gate == "C20"
    assert c20.expected_failure_code == "UCM-F014-ACTION_SEMANTICS_CONFLATED"
