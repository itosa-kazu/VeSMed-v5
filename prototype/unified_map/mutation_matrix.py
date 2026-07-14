"""Fail-closed mutation-kill evidence for the UCM benchmark.

The registry in this module is executable freeze input, not a claim that the
detectors already exist.  A matrix is freeze-ready only when every declared
mutant has a semantically matching decisive kill, every C01--C33 gate is
covered, and every specificity control has a decisive non-rejection record.
Crashes, timeouts, unrelated failure codes, and string-only assertions never
count as kills.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from .canonical import ProtocolViolation, canonical_json_bytes, digest_json


MATRIX_PROTOCOL = "ucm-mutation-kill-matrix/1"


class SubjectKind(str, Enum):
    MUTANT = "mutant"
    SPECIFICITY_CONTROL = "specificity_control"


class ObservationOutcome(str, Enum):
    KILLED = "killed"
    SURVIVED = "survived"
    PASSED = "passed"
    REJECTED = "rejected"
    CRASHED = "crashed"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class GateSpec:
    gate_id: str
    allowed_failure_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not _is_gate(self.gate_id):
            raise ProtocolViolation("gate_id must be C01 through C33")
        _nonempty_unique_strings(self.allowed_failure_codes, "allowed_failure_codes")

    def to_wire(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "allowed_failure_codes": list(self.allowed_failure_codes),
        }


@dataclass(frozen=True, slots=True)
class MutantSpec:
    mutant_id: str
    expected_gates: tuple[str, ...]
    expected_failure_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        _name(self.mutant_id, "mutant_id")
        _nonempty_unique_strings(self.expected_gates, "expected_gates")
        if any(not _is_gate(gate) for gate in self.expected_gates):
            raise ProtocolViolation("mutant expected_gates must be C01 through C33")
        _nonempty_unique_strings(
            self.expected_failure_codes, "expected_failure_codes"
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "mutant_id": self.mutant_id,
            "expected_gates": list(self.expected_gates),
            "expected_failure_codes": list(self.expected_failure_codes),
        }


@dataclass(frozen=True, slots=True)
class SpecificityControlSpec:
    control_id: str
    allowed_classification: str

    def __post_init__(self) -> None:
        _name(self.control_id, "control_id")
        _name(self.allowed_classification, "allowed_classification")

    def to_wire(self) -> dict[str, Any]:
        return {
            "control_id": self.control_id,
            "allowed_classification": self.allowed_classification,
        }


@dataclass(frozen=True, slots=True)
class MutationObservation:
    subject_id: str
    subject_kind: SubjectKind
    source_digest: str
    execution_seed: int
    outcome: ObservationOutcome
    actual_gate: str | None
    actual_failure_code: str | None
    decisive_record_digest: str | None
    classification: str | None = None

    def __post_init__(self) -> None:
        _name(self.subject_id, "subject_id")
        if type(self.subject_kind) is not SubjectKind:
            raise ProtocolViolation("subject_kind must be SubjectKind")
        _digest(self.source_digest, "source_digest")
        if type(self.execution_seed) is not int or not 0 <= self.execution_seed < 2**128:
            raise ProtocolViolation("execution_seed must be unsigned 128-bit integer")
        if type(self.outcome) is not ObservationOutcome:
            raise ProtocolViolation("outcome must be ObservationOutcome")
        if self.actual_gate is not None and not _is_gate(self.actual_gate):
            raise ProtocolViolation("actual_gate must be null or C01 through C33")
        if self.actual_failure_code is not None:
            _name(self.actual_failure_code, "actual_failure_code")
        if self.decisive_record_digest is not None:
            _digest(self.decisive_record_digest, "decisive_record_digest")
        if self.classification is not None:
            _name(self.classification, "classification")

    def to_wire(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "subject_kind": self.subject_kind.value,
            "source_digest": self.source_digest,
            "execution_seed": self.execution_seed,
            "outcome": self.outcome.value,
            "actual_gate": self.actual_gate,
            "actual_failure_code": self.actual_failure_code,
            "decisive_record_digest": self.decisive_record_digest,
            "classification": self.classification,
        }


@dataclass(frozen=True, slots=True)
class MutationMatrixReport:
    observations: tuple[MutationObservation, ...]
    valid_kills: tuple[str, ...]
    missing_or_invalid_mutants: tuple[str, ...]
    covered_gates: tuple[str, ...]
    uncovered_gates: tuple[str, ...]
    passed_specificity_controls: tuple[str, ...]
    failed_specificity_controls: tuple[str, ...]

    @property
    def freeze_ready(self) -> bool:
        return not (
            self.missing_or_invalid_mutants
            or self.uncovered_gates
            or self.failed_specificity_controls
        )

    @property
    def benchmark_status(self) -> str:
        return "MUTATION-GATES-PASS" if self.freeze_ready else "HARNESS_INCOMPLETE"

    def to_wire(self) -> dict[str, Any]:
        body = {
            "protocol": MATRIX_PROTOCOL,
            "benchmark_status": self.benchmark_status,
            "freeze_ready": self.freeze_ready,
            "registry_digest": REGISTRY_DIGEST,
            "observations": [row.to_wire() for row in self.observations],
            "valid_kills": list(self.valid_kills),
            "missing_or_invalid_mutants": list(self.missing_or_invalid_mutants),
            "covered_gates": list(self.covered_gates),
            "uncovered_gates": list(self.uncovered_gates),
            "passed_specificity_controls": list(self.passed_specificity_controls),
            "failed_specificity_controls": list(self.failed_specificity_controls),
        }
        body["matrix_digest"] = digest_json(body)
        return body

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 71 or not value.startswith("sha256:"):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} is not hexadecimal") from exc
    return value


def _is_gate(value: object) -> bool:
    return type(value) is str and len(value) == 3 and value[0] == "C" and value[1:].isdigit() and 1 <= int(value[1:]) <= 33


def _nonempty_unique_strings(values: object, label: str) -> tuple[str, ...]:
    if type(values) is not tuple or not values:
        raise ProtocolViolation(f"{label} must be a non-empty tuple")
    if any(type(value) is not str or not value for value in values):
        raise ProtocolViolation(f"{label} entries must be non-empty strings")
    if len(values) != len(set(values)):
        raise ProtocolViolation(f"{label} entries must be unique")
    return values


def _gates(ids: str) -> tuple[str, ...]:
    return tuple(ids.split())


GATE_SPECS: tuple[GateSpec, ...] = (
    GateSpec("C01", ("UCM-F007-STATE_FANOUT_MISMATCH",)),
    GateSpec("C02", ("UCM-F004-HEAD_HISTORY_ACCESS",)),
    GateSpec("C03", ("UCM-F005-TASK_SPECIFIC_STATE",)),
    GateSpec("C04", ("UCM-F006-HIDDEN_PATIENT_CACHE", "UCM-F008-STATE_NOT_CLOSED", "UCM-F020-NONREPRODUCIBLE")),
    GateSpec("C05", ("UCM-F006-HIDDEN_PATIENT_CACHE", "UCM-F001-FUTURE_LEAK", "UCM-F020-NONREPRODUCIBLE")),
    GateSpec("C06", ("UCM-F009-MODEL_MUTATION",)),
    GateSpec("C07", ("UCM-F008-STATE_NOT_CLOSED", "UCM-F001-FUTURE_LEAK", "UCM-F002-ORACLE_TRUE_STATE_ACCESS")),
    GateSpec("C08", ("UCM-F001-FUTURE_LEAK", "UCM-F002-ORACLE_TRUE_STATE_ACCESS")),
    GateSpec("C09", ("UCM-F002-ORACLE_TRUE_STATE_ACCESS", "UCM-F004-HEAD_HISTORY_ACCESS", "UCM-F008-STATE_NOT_CLOSED")),
    GateSpec("C10", ("UCM-F001-FUTURE_LEAK",)),
    GateSpec("C11", ("UCM-F011-TIME_VISIBILITY_VIOLATION",)),
    GateSpec("C12", ("UCM-F001-FUTURE_LEAK",)),
    GateSpec("C13", ("UCM-F003-TEST_ID_BRANCH",)),
    GateSpec("C14", ("UCM-F003-TEST_ID_BRANCH",)),
    GateSpec("C15", ("UCM-F006-HIDDEN_PATIENT_CACHE",)),
    GateSpec("C16", ("UCM-F012-QUERY_MUTATES_FACT",)),
    GateSpec("C17", ("UCM-F014-ACTION_SEMANTICS_CONFLATED",)),
    GateSpec("C18", ("UCM-F014-ACTION_SEMANTICS_CONFLATED",)),
    GateSpec("C19", ("UCM-F015-CONDITIONING_AS_INTERVENTION",)),
    GateSpec("C20", ("UCM-F014-ACTION_SEMANTICS_CONFLATED",)),
    GateSpec("C21", ("UCM-F007-STATE_FANOUT_MISMATCH", "UCM-F010-UPDATE_NOT_RECURSIVE", "UCM-F005-TASK_SPECIFIC_STATE")),
    GateSpec("C22", ("UCM-F019-UPDATE_INCONSISTENT",)),
    GateSpec("C23", ("UCM-F011-TIME_VISIBILITY_VIOLATION", "UCM-F001-FUTURE_LEAK")),
    GateSpec("C24", ("UCM-F016-DANGEROUS_COLLISION",)),
    GateSpec("C25", ("UCM-F017-OOD_FORCED_MATCH",)),
    GateSpec("C26", ("UCM-F004-HEAD_HISTORY_ACCESS", "UCM-F005-TASK_SPECIFIC_STATE")),
    GateSpec("C27", ("UCM-F018-FULL_HISTORY_MISCLAIM",)),
    GateSpec("C28", ("UCM-F020-NONREPRODUCIBLE",)),
    GateSpec("C29", ("UCM-F005-TASK_SPECIFIC_STATE",)),
    GateSpec("C30", ("UCM-F020-NONREPRODUCIBLE",)),
    GateSpec("C31", ("UCM-F018-FULL_HISTORY_MISCLAIM",)),
    GateSpec("C32", ("UCM-F013-SPLIT_TRANSITION_CORE", "UCM-F005-TASK_SPECIFIC_STATE")),
    GateSpec("C33", ("UCM-F005-TASK_SPECIFIC_STATE",)),
)


MUTANT_SPECS: tuple[MutantSpec, ...] = (
    MutantSpec("GlobalSecondState", _gates("C04 C05 C15"), ("UCM-F006-HIDDEN_PATIENT_CACHE",)),
    MutantSpec("FileHandleState", _gates("C04 C07 C09"), ("UCM-F008-STATE_NOT_CLOSED",)),
    MutantSpec("RawHistoryHead", _gates("C02 C09"), ("UCM-F004-HEAD_HISTORY_ACCESS",)),
    MutantSpec("TrainerTargetSmuggler", _gates("C07 C08 C10 C11 C12"), ("UCM-F001-FUTURE_LEAK", "UCM-F002-ORACLE_TRUE_STATE_ACCESS")),
    MutantSpec("HistoryInBlob", _gates("C27 C31"), ("UCM-F018-FULL_HISTORY_MISCLAIM",)),
    MutantSpec("MutableCheckpoint", _gates("C06"), ("UCM-F009-MODEL_MUTATION",)),
    MutantSpec("WarmFutureCache", _gates("C05 C10 C12 C23"), ("UCM-F001-FUTURE_LEAK", "UCM-F011-TIME_VISIBILITY_VIOLATION")),
    MutantSpec("AvailabilityOffByOne", _gates("C11"), ("UCM-F011-TIME_VISIBILITY_VIOLATION",)),
    MutantSpec("TrueStateReader", _gates("C08 C09"), ("UCM-F002-ORACLE_TRUE_STATE_ACCESS",)),
    MutantSpec("FutureReader", _gates("C08 C09 C10 C11 C12"), ("UCM-F001-FUTURE_LEAK", "UCM-F002-ORACLE_TRUE_STATE_ACCESS")),
    MutantSpec("TestIdSwitch", _gates("C13 C14"), ("UCM-F003-TEST_ID_BRANCH",)),
    MutantSpec("WorldNameSwitch", _gates("C13 C14"), ("UCM-F003-TEST_ID_BRANCH",)),
    MutantSpec("ImplicitRNGState", _gates("C04 C05 C28 C30"), ("UCM-F020-NONREPRODUCIBLE",)),
    MutantSpec("QuerySmuggler", _gates("C03 C29"), ("UCM-F005-TASK_SPECIFIC_STATE",)),
    MutantSpec("QueryReencoder", _gates("C01 C02 C03 C26 C29 C32"), ("UCM-F004-HEAD_HISTORY_ACCESS", "UCM-F005-TASK_SPECIFIC_STATE", "UCM-F013-SPLIT_TRANSITION_CORE")),
    MutantSpec("CounterfactualMutator", _gates("C16"), ("UCM-F012-QUERY_MUTATES_FACT",)),
    MutantSpec("NoOpMeansStop", _gates("C17"), ("UCM-F014-ACTION_SEMANTICS_CONFLATED",)),
    MutantSpec("PlanMeansPerformed", _gates("C18"), ("UCM-F014-ACTION_SEMANTICS_CONFLATED",)),
    MutantSpec("ActionAsConditioning", _gates("C19"), ("UCM-F015-CONDITIONING_AS_INTERVENTION",)),
    MutantSpec("NonIdPointEstimate", _gates("C19"), ("UCM-F015-CONDITIONING_AS_INTERVENTION",)),
    MutantSpec("ObservationEqualsMechanism", _gates("C20"), ("UCM-F014-ACTION_SEMANTICS_CONFLATED",)),
    MutantSpec("ReplayBatchDivergence", _gates("C21 C22"), ("UCM-F019-UPDATE_INCONSISTENT", "UCM-F010-UPDATE_NOT_RECURSIVE")),
    MutantSpec("DoubleCountEvent", _gates("C22"), ("UCM-F019-UPDATE_INCONSISTENT",)),
    MutantSpec("TripleLatentBlob", _gates("C21 C26 C32 C33"), ("UCM-F005-TASK_SPECIFIC_STATE",)),
    MutantSpec("UnsafeClosedWorld", _gates("C25"), ("UCM-F017-OOD_FORCED_MATCH",)),
    MutantSpec("DangerousMeanCompressor", _gates("C24"), ("UCM-F016-DANGEROUS_COLLISION",)),
)


SPECIFICITY_CONTROLS: tuple[SpecificityControlSpec, ...] = (
    SpecificityControlSpec("ExplicitSeedStochasticState", "ordinary_candidate"),
    SpecificityControlSpec("BehaviorEquivalentSerialization", "ordinary_candidate"),
    SpecificityControlSpec("DeclaredFullHistoryBaseline", "baseline_only"),
    SpecificityControlSpec("CorrectNonidentifiedSet", "ordinary_candidate"),
)


def _registry_wire() -> dict[str, Any]:
    return {
        "protocol": MATRIX_PROTOCOL,
        "gates": [gate.to_wire() for gate in GATE_SPECS],
        "mutants": [mutant.to_wire() for mutant in MUTANT_SPECS],
        "specificity_controls": [control.to_wire() for control in SPECIFICITY_CONTROLS],
    }


REGISTRY_DIGEST = digest_json(_registry_wire())


def evaluate_mutation_matrix(
    observations: Iterable[MutationObservation],
) -> MutationMatrixReport:
    rows = tuple(observations)
    identities = [
        (row.subject_kind.value, row.subject_id, row.execution_seed, row.source_digest)
        for row in rows
    ]
    if len(identities) != len(set(identities)):
        raise ProtocolViolation("duplicate mutation observation identity")

    mutant_by_id = {row.mutant_id: row for row in MUTANT_SPECS}
    control_by_id = {row.control_id: row for row in SPECIFICITY_CONTROLS}
    valid_kills: set[str] = set()
    covered_gates: set[str] = set()
    passed_controls: set[str] = set()
    failed_controls: set[str] = set()

    for row in rows:
        if row.subject_kind is SubjectKind.MUTANT:
            spec = mutant_by_id.get(row.subject_id)
            if spec is None:
                raise ProtocolViolation(f"unknown mutant observation {row.subject_id!r}")
            valid = (
                row.outcome is ObservationOutcome.KILLED
                and row.actual_gate in spec.expected_gates
                and row.actual_failure_code in spec.expected_failure_codes
                and row.decisive_record_digest is not None
            )
            if valid:
                valid_kills.add(spec.mutant_id)
                covered_gates.add(str(row.actual_gate))
        else:
            spec = control_by_id.get(row.subject_id)
            if spec is None:
                raise ProtocolViolation(
                    f"unknown specificity control observation {row.subject_id!r}"
                )
            valid = (
                row.outcome is ObservationOutcome.PASSED
                and row.actual_gate is None
                and row.actual_failure_code is None
                and row.decisive_record_digest is not None
                and row.classification == spec.allowed_classification
            )
            if valid:
                passed_controls.add(spec.control_id)
            else:
                failed_controls.add(spec.control_id)

    missing_mutants = sorted(set(mutant_by_id) - valid_kills)
    all_gates = {row.gate_id for row in GATE_SPECS}
    # A gate is covered only by an actual decisive kill assigned to that exact
    # gate.  Merely listing the gate in a mutant spec is not execution evidence.
    uncovered = sorted(all_gates - covered_gates)
    missing_controls = set(control_by_id) - passed_controls
    failed_controls.update(missing_controls)

    return MutationMatrixReport(
        observations=tuple(
            sorted(
                rows,
                key=lambda row: (
                    row.subject_kind.value,
                    row.subject_id,
                    row.execution_seed,
                    row.source_digest,
                ),
            )
        ),
        valid_kills=tuple(sorted(valid_kills)),
        missing_or_invalid_mutants=tuple(missing_mutants),
        covered_gates=tuple(sorted(covered_gates)),
        uncovered_gates=tuple(uncovered),
        passed_specificity_controls=tuple(sorted(passed_controls)),
        failed_specificity_controls=tuple(sorted(failed_controls)),
    )


__all__ = [
    "GATE_SPECS",
    "MATRIX_PROTOCOL",
    "MUTANT_SPECS",
    "MutationMatrixReport",
    "MutationObservation",
    "ObservationOutcome",
    "REGISTRY_DIGEST",
    "SPECIFICITY_CONTROLS",
    "SubjectKind",
    "evaluate_mutation_matrix",
]
