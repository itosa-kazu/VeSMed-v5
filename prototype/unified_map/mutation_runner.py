"""Execute the currently portable UCM mutation controls into matrix evidence.

Only observed detector outcomes are converted to kill records.  The static
mapping below selects which already-executed gate is decisive; it never turns
a crash, timeout, missing failure code, or unrelated rejection into a kill.
The resulting partial matrix is intentionally HARNESS_INCOMPLETE until all
public benchmark mutants and specificity controls have real executions.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from .canonical import ProtocolViolation, digest_bytes, digest_json
from .compliance import (
    ComplianceFinding,
    ComplianceVerdict,
    HonestSeededControl,
    control_entrypoint,
    evaluate_candidate_compliance,
)
from .mutation_matrix import (
    MutationObservation,
    ObservationOutcome,
    SubjectKind,
    evaluate_mutation_matrix,
)
from .schema import DiagnosisQuery, RolloutQuery, VisibleDelta, VisibleHistory


RUNNER_PROTOCOL = "ucm-portable-mutation-runner/1"


@dataclass(frozen=True, slots=True)
class PortableMutationCase:
    matrix_subject_id: str
    control_class_name: str
    decisive_gate: str
    expected_failure_code: str


PORTABLE_MUTATION_CASES: tuple[PortableMutationCase, ...] = (
    PortableMutationCase(
        "GlobalSecondState",
        "GlobalSecondStateControl",
        "C04",
        "UCM-F006-HIDDEN_PATIENT_CACHE",
    ),
    PortableMutationCase(
        "FileHandleState",
        "FileHandleStateControl",
        "C07",
        "UCM-F008-STATE_NOT_CLOSED",
    ),
    PortableMutationCase(
        "RawHistoryHead",
        "RawHistoryHeadControl",
        "C02",
        "UCM-F004-HEAD_HISTORY_ACCESS",
    ),
    PortableMutationCase(
        "TrainerTargetSmuggler",
        "TrainerTargetSmugglerControl",
        "C08",
        "UCM-F002-ORACLE_TRUE_STATE_ACCESS",
    ),
    PortableMutationCase(
        "QueryReencoder",
        "QueryReencoderControl",
        "C02",
        "UCM-F004-HEAD_HISTORY_ACCESS",
    ),
    PortableMutationCase(
        "MutableCheckpoint",
        "MutableCheckpointControl",
        "C06",
        "UCM-F009-MODEL_MUTATION",
    ),
    PortableMutationCase(
        "TrueStateReader",
        "TrueStateReaderControl",
        "C08",
        "UCM-F002-ORACLE_TRUE_STATE_ACCESS",
    ),
    PortableMutationCase(
        "FutureReader",
        "FutureReaderControl",
        "C08",
        "UCM-F001-FUTURE_LEAK",
    ),
    PortableMutationCase(
        "CounterfactualMutator",
        "QueryMutatorControl",
        "C16",
        "UCM-F012-QUERY_MUTATES_FACT",
    ),
    PortableMutationCase(
        "ImplicitRNGState",
        "ImplicitRNGControl",
        "C30",
        "UCM-F020-NONREPRODUCIBLE",
    ),
)


def _finding_wire(finding: ComplianceFinding) -> dict[str, Any]:
    return {
        "gate": finding.gate,
        "verdict": finding.verdict.value,
        "failure_code": finding.failure_code,
        "detail": finding.detail,
        "evidence": finding.evidence,
    }


def _source_digest(control_class_name: str) -> str:
    # All built-ins are imported through the same sealed Python bundle, but
    # source identity is per class rather than a shared module-name assertion.
    from . import compliance

    value = getattr(compliance, control_class_name, None)
    if type(value) is not type:
        raise ProtocolViolation(f"unknown portable control {control_class_name!r}")
    return digest_bytes(inspect.getsource(value).encode("utf-8"))


def _decisive_finding(
    findings: tuple[ComplianceFinding, ...], expected_failure_code: str
) -> ComplianceFinding | None:
    matches = [
        finding
        for finding in findings
        if finding.verdict is ComplianceVerdict.FAIL
        and finding.failure_code == expected_failure_code
    ]
    if len(matches) > 1:
        # Ambiguous duplicates are not silently selected because the matrix is
        # supposed to point to one decisive detector record.
        raise ProtocolViolation(
            f"multiple decisive findings for {expected_failure_code}"
        )
    return matches[0] if matches else None


def _finding_gate_tokens(finding: ComplianceFinding) -> frozenset[str]:
    return frozenset(
        token
        for token in finding.gate.replace("/", " ").replace("-", " ").split()
        if len(token) == 3 and token.startswith("C") and token[1:].isdigit()
    )


def run_portable_mutation_evidence(
    *,
    history: VisibleHistory,
    diagnosis_query: DiagnosisQuery,
    rollout_query: RolloutQuery,
    delta: VisibleDelta | None = None,
    seed: int,
) -> tuple[MutationObservation, ...]:
    if type(seed) is not int or not 0 <= seed < 2**128:
        raise ProtocolViolation("seed must be unsigned 128-bit integer")
    rows: list[MutationObservation] = []
    for index, case in enumerate(PORTABLE_MUTATION_CASES):
        execution_seed = seed + index
        if execution_seed >= 2**128:
            raise ProtocolViolation("derived mutation seed overflows uint128")
        report = evaluate_candidate_compliance(
            control_entrypoint(case.control_class_name),
            history=history,
            diagnosis_query=diagnosis_query,
            rollout_query=rollout_query,
            delta=delta,
            seed=execution_seed,
        )
        decisive = _decisive_finding(report.findings, case.expected_failure_code)
        if decisive is not None and case.decisive_gate not in _finding_gate_tokens(
            decisive
        ):
            decisive = None
        rows.append(
            MutationObservation(
                subject_id=case.matrix_subject_id,
                subject_kind=SubjectKind.MUTANT,
                source_digest=_source_digest(case.control_class_name),
                execution_seed=execution_seed,
                outcome=(
                    ObservationOutcome.KILLED
                    if decisive is not None
                    else ObservationOutcome.SURVIVED
                ),
                actual_gate=case.decisive_gate if decisive is not None else None,
                actual_failure_code=(
                    decisive.failure_code if decisive is not None else None
                ),
                decisive_record_digest=(
                    digest_json(
                        {
                            "protocol": RUNNER_PROTOCOL,
                            "candidate": report.candidate,
                            "finding": _finding_wire(decisive),
                        }
                    )
                    if decisive is not None
                    else None
                ),
            )
        )

    control_report = evaluate_candidate_compliance(
        control_entrypoint("HonestSeededControl"),
        history=history,
        diagnosis_query=diagnosis_query,
        rollout_query=rollout_query,
        delta=delta,
        seed=seed + len(PORTABLE_MUTATION_CASES),
    )
    passed = (
        control_report.operational_state_closure is ComplianceVerdict.PASS
        and not control_report.failure_codes
    )
    rows.append(
        MutationObservation(
            subject_id="ExplicitSeedStochasticState",
            subject_kind=SubjectKind.SPECIFICITY_CONTROL,
            source_digest=digest_bytes(
                inspect.getsource(HonestSeededControl).encode("utf-8")
            ),
            execution_seed=seed + len(PORTABLE_MUTATION_CASES),
            outcome=(
                ObservationOutcome.PASSED
                if passed
                else ObservationOutcome.REJECTED
            ),
            actual_gate=None,
            actual_failure_code=None,
            decisive_record_digest=digest_json(
                {
                    "protocol": RUNNER_PROTOCOL,
                    "candidate": control_report.candidate,
                    "operational_state_closure": (
                        control_report.operational_state_closure.value
                    ),
                    "failure_codes": list(control_report.failure_codes),
                    "head_records": list(control_report.head_records),
                }
            ),
            classification="ordinary_candidate",
        )
    )
    # Evaluate immediately so an accidental registry mismatch fails at the
    # producer boundary rather than much later during freeze assembly.
    evaluate_mutation_matrix(rows)
    return tuple(rows)


__all__ = [
    "PORTABLE_MUTATION_CASES",
    "RUNNER_PROTOCOL",
    "PortableMutationCase",
    "run_portable_mutation_evidence",
]
