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


MATRIX_PROTOCOL = "ucm-mutation-kill-matrix/2"


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
    execution_case_id: str
    probe_id: str
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
        _name(self.execution_case_id, "execution_case_id")
        _name(self.probe_id, "probe_id")
        _digest(self.source_digest, "source_digest")
        if type(self.execution_seed) is not int or not 0 <= self.execution_seed < 2**64:
            raise ProtocolViolation("execution_seed must be unsigned 64-bit integer")
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
            "execution_case_id": self.execution_case_id,
            "probe_id": self.probe_id,
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


def _finding_gate_tokens(value: str) -> frozenset[str]:
    return frozenset(
        token
        for token in value.replace("/", " ").replace("-", " ").split()
        if _is_gate(token)
    )


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
    MutantSpec("TrainerTargetSmuggler", _gates("C07 C08 C10 C12"), ("UCM-F001-FUTURE_LEAK", "UCM-F002-ORACLE_TRUE_STATE_ACCESS")),
    MutantSpec("HistoryInBlob", _gates("C27 C31"), ("UCM-F018-FULL_HISTORY_MISCLAIM",)),
    MutantSpec("MutableCheckpoint", _gates("C06"), ("UCM-F009-MODEL_MUTATION",)),
    MutantSpec("WarmFutureCache", _gates("C05 C10 C12 C23"), ("UCM-F001-FUTURE_LEAK", "UCM-F011-TIME_VISIBILITY_VIOLATION")),
    MutantSpec("AvailabilityOffByOne", _gates("C11"), ("UCM-F011-TIME_VISIBILITY_VIOLATION",)),
    MutantSpec("TrueStateReader", _gates("C08 C09"), ("UCM-F002-ORACLE_TRUE_STATE_ACCESS",)),
    MutantSpec("FutureReader", _gates("C08 C09 C10 C12"), ("UCM-F001-FUTURE_LEAK", "UCM-F002-ORACLE_TRUE_STATE_ACCESS")),
    MutantSpec("TestIdSwitch", _gates("C13 C14"), ("UCM-F003-TEST_ID_BRANCH",)),
    MutantSpec("WorldNameSwitch", _gates("C13 C14"), ("UCM-F003-TEST_ID_BRANCH",)),
    MutantSpec("ImplicitRNGState", _gates("C04 C05 C28 C30"), ("UCM-F020-NONREPRODUCIBLE",)),
    MutantSpec("QuerySmuggler", _gates("C03 C29"), ("UCM-F005-TASK_SPECIFIC_STATE",)),
    MutantSpec("QueryReencoder", _gates("C02 C03 C26 C29 C32"), ("UCM-F004-HEAD_HISTORY_ACCESS", "UCM-F005-TASK_SPECIFIC_STATE", "UCM-F013-SPLIT_TRANSITION_CORE")),
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


PORTABLE_EXECUTION_CASE_REGISTRY_PROTOCOL = "ucm-portable-execution-cases/1"
PORTABLE_SEMANTIC_PROBE_PROTOCOL_ALIAS = "ucm-portable-semantic-probes/6"
EXECUTION_CASE_SEED_STRIDE = 16
EXECUTION_CASE_MAIN_OFFSETS = (0, 1, 2, 3)
UPDATE_CONSISTENCY_LINEAGE_OFFSETS = (0, 1, 2)
UPDATE_CONSISTENCY_LINEAGE_XOR_MASK = 0x6A09E667F3BCC909


def _execution_seed(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value < 2**64:
        raise ProtocolViolation(f"{label} must be an unsigned 64-bit integer")
    return value


@dataclass(frozen=True, slots=True)
class PortableExecutionCaseSpec:
    """One code-owned parent-harness execution row.

    ``execution_case_id`` is the globally unique execution identity. ``probe_id``
    names the exact directed detector profile used by that case; it never enters
    a candidate request.  The explicit ordinal is seed authority and therefore
    cannot be inferred from a caller-selected active-row order.
    """

    execution_case_id: str
    probe_id: str
    execution_ordinal: int
    subject_kind: SubjectKind
    subject_id: str
    control_class_name: str
    expected_gate: str | None
    expected_failure_code: str | None
    classification: str | None
    semantic_probes: tuple[str, ...]
    head_record_shape: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.execution_case_id, "execution_case_id"),
            (self.probe_id, "probe_id"),
            (self.subject_id, "subject_id"),
            (self.control_class_name, "control_class_name"),
        ):
            _name(value, f"portable execution case {label}")
        if type(self.execution_ordinal) is not int or self.execution_ordinal < 0:
            raise ProtocolViolation(
                "portable execution case ordinal must be a nonnegative exact integer"
            )
        if type(self.subject_kind) is not SubjectKind:
            raise ProtocolViolation("portable execution case subject_kind is invalid")
        if (
            type(self.semantic_probes) is not tuple
            or any(type(item) is not str or not item for item in self.semantic_probes)
            or tuple(sorted(self.semantic_probes)) != self.semantic_probes
            or len(set(self.semantic_probes)) != len(self.semantic_probes)
        ):
            raise ProtocolViolation(
                "portable execution case semantic_probes must be a sorted unique tuple"
            )
        if self.head_record_shape not in {"empty", "replay_ddrr"}:
            raise ProtocolViolation("portable execution case head_record_shape is invalid")

        mutant_by_id = {item.mutant_id: item for item in MUTANT_SPECS}
        control_by_id = {item.control_id: item for item in SPECIFICITY_CONTROLS}
        gate_by_id = {item.gate_id: item for item in GATE_SPECS}
        if self.subject_kind is SubjectKind.MUTANT:
            spec = mutant_by_id.get(self.subject_id)
            gate = gate_by_id.get(self.expected_gate)
            if (
                spec is None
                or self.classification is not None
                or gate is None
                or self.expected_gate not in spec.expected_gates
                or self.expected_gate not in _finding_gate_tokens(self.probe_id)
                or self.expected_failure_code not in spec.expected_failure_codes
                or self.expected_failure_code not in gate.allowed_failure_codes
            ):
                raise ProtocolViolation(
                    "portable mutant case is outside the direct gate/failure registry"
                )
        else:
            spec = control_by_id.get(self.subject_id)
            if (
                spec is None
                or self.expected_gate is not None
                or self.expected_failure_code is not None
                or self.classification != spec.allowed_classification
            ):
                raise ProtocolViolation(
                    "portable specificity case is outside the control registry"
                )

    def to_wire(self) -> dict[str, Any]:
        return {
            "execution_case_id": self.execution_case_id,
            "probe_id": self.probe_id,
            "execution_ordinal": self.execution_ordinal,
            "subject_kind": self.subject_kind.value,
            "subject_id": self.subject_id,
            "control_class_name": self.control_class_name,
            "expected_gate": self.expected_gate,
            "expected_failure_code": self.expected_failure_code,
            "classification": self.classification,
            "semantic_probes": list(self.semantic_probes),
            "head_record_shape": self.head_record_shape,
        }

    @property
    def matrix_subject_id(self) -> str:
        """Compatibility view; the execution registry remains sole authority."""

        return self.subject_id

    @property
    def decisive_gate(self) -> str:
        if self.expected_gate is None:
            raise ProtocolViolation("specificity case has no decisive gate")
        return self.expected_gate


def _mutant_case(
    execution_case_id: str,
    probe_id: str,
    execution_ordinal: int,
    subject_id: str,
    control_class_name: str,
    expected_gate: str,
    expected_failure_code: str,
    semantic_probes: tuple[str, ...] = (),
    head_record_shape: str = "empty",
) -> PortableExecutionCaseSpec:
    return PortableExecutionCaseSpec(
        execution_case_id=execution_case_id,
        probe_id=probe_id,
        execution_ordinal=execution_ordinal,
        subject_kind=SubjectKind.MUTANT,
        subject_id=subject_id,
        control_class_name=control_class_name,
        expected_gate=expected_gate,
        expected_failure_code=expected_failure_code,
        classification=None,
        semantic_probes=semantic_probes,
        head_record_shape=head_record_shape,
    )


def _specificity_case(
    execution_case_id: str,
    probe_id: str,
    execution_ordinal: int,
    subject_id: str,
    control_class_name: str,
    classification: str,
    semantic_probes: tuple[str, ...],
) -> PortableExecutionCaseSpec:
    return PortableExecutionCaseSpec(
        execution_case_id=execution_case_id,
        probe_id=probe_id,
        execution_ordinal=execution_ordinal,
        subject_kind=SubjectKind.SPECIFICITY_CONTROL,
        subject_id=subject_id,
        control_class_name=control_class_name,
        expected_gate=None,
        expected_failure_code=None,
        classification=classification,
        semantic_probes=semantic_probes,
        head_record_shape="replay_ddrr",
    )


# Exactly one initial case per matrix mutant/control.  Some controls are not yet
# implemented in compliance.py; their executions honestly become non-decisive
# CRASHED rows and keep PRE-FREEZE/HARNESS_INCOMPLETE status.
PORTABLE_EXECUTION_CASES: tuple[PortableExecutionCaseSpec, ...] = (
    _mutant_case("case.mutant.GlobalSecondState.C04.v1", "C04/C05/C15-warm-cold-equivalence", 0, "GlobalSecondState", "GlobalSecondStateControl", "C04", "UCM-F006-HIDDEN_PATIENT_CACHE", head_record_shape="replay_ddrr"),
    _mutant_case("case.mutant.FileHandleState.C07.v1", "C07-state-closed-schema", 1, "FileHandleState", "FileHandleStateControl", "C07", "UCM-F008-STATE_NOT_CLOSED"),
    _mutant_case("case.mutant.RawHistoryHead.C02.v1", "C02-head-history-denial", 2, "RawHistoryHead", "RawHistoryHeadControl", "C02", "UCM-F004-HEAD_HISTORY_ACCESS"),
    _mutant_case("case.mutant.TrainerTargetSmuggler.C08.v1", "C08-candidate-view-physical-isolation", 3, "TrainerTargetSmuggler", "TrainerTargetSmugglerControl", "C08", "UCM-F002-ORACLE_TRUE_STATE_ACCESS"),
    _mutant_case("case.mutant.HistoryInBlob.C27.v1", "C27-fixed-codec-full-history-disclosure", 4, "HistoryInBlob", "HistoryInBlobControl", "C27", "UCM-F018-FULL_HISTORY_MISCLAIM", ("full_history_disclosure",), "replay_ddrr"),
    _mutant_case("case.mutant.MutableCheckpoint.C06.v1", "C06-model-immutability", 5, "MutableCheckpoint", "MutableCheckpointControl", "C06", "UCM-F009-MODEL_MUTATION"),
    _mutant_case("case.mutant.WarmFutureCache.C23.v1", "C23-late-event-old-cut-stability", 6, "WarmFutureCache", "WarmFutureCacheControl", "C23", "UCM-F001-FUTURE_LEAK", ("warm_future_old_cut",), "replay_ddrr"),
    _mutant_case("case.mutant.AvailabilityOffByOne.C11.v1", "C11-availability-boundary", 7, "AvailabilityOffByOne", "AvailabilityOffByOneControl", "C11", "UCM-F011-TIME_VISIBILITY_VIOLATION"),
    _mutant_case("case.mutant.TrueStateReader.C08.v1", "C08-candidate-view-physical-isolation", 8, "TrueStateReader", "TrueStateReaderControl", "C08", "UCM-F002-ORACLE_TRUE_STATE_ACCESS"),
    _mutant_case("case.mutant.FutureReader.C08.v1", "C08-candidate-view-physical-isolation", 9, "FutureReader", "FutureReaderControl", "C08", "UCM-F001-FUTURE_LEAK"),
    _mutant_case("case.mutant.TestIdSwitch.C13.v1", "C13-opaque-alpha-renaming", 10, "TestIdSwitch", "TestIdSwitchControl", "C13", "UCM-F003-TEST_ID_BRANCH"),
    _mutant_case("case.mutant.WorldNameSwitch.C14.v1", "C14-hidden-test-id-canary", 11, "WorldNameSwitch", "WorldNameSwitchControl", "C14", "UCM-F003-TEST_ID_BRANCH"),
    _mutant_case("case.mutant.ImplicitRNGState.C30.v1", "C28/C30-explicit-head-replay", 12, "ImplicitRNGState", "ImplicitRNGControl", "C30", "UCM-F020-NONREPRODUCIBLE", head_record_shape="replay_ddrr"),
    _mutant_case("case.mutant.QuerySmuggler.C03.v1", "C03/C29-task-blind-state-producer", 13, "QuerySmuggler", "QuerySmugglerControl", "C03", "UCM-F005-TASK_SPECIFIC_STATE"),
    _mutant_case("case.mutant.QueryReencoder.C02.v1", "C02-head-history-denial", 14, "QueryReencoder", "QueryReencoderControl", "C02", "UCM-F004-HEAD_HISTORY_ACCESS"),
    _mutant_case("case.mutant.CounterfactualMutator.C16.v1", "C16-counterfactual-purity-order", 15, "CounterfactualMutator", "QueryMutatorControl", "C16", "UCM-F012-QUERY_MUTATES_FACT"),
    _mutant_case("case.mutant.NoOpMeansStop.C17.v1", "C17-no-op-semantics", 16, "NoOpMeansStop", "NoOpMeansStopControl", "C17", "UCM-F014-ACTION_SEMANTICS_CONFLATED"),
    _mutant_case("case.mutant.PlanMeansPerformed.C18.v1", "C18-plan-performed-separation", 17, "PlanMeansPerformed", "PlanMeansPerformedControl", "C18", "UCM-F014-ACTION_SEMANTICS_CONFLATED"),
    _mutant_case("case.mutant.ActionAsConditioning.C19.v1", "C19-condition-do-separation", 18, "ActionAsConditioning", "ActionAsConditioningControl", "C19", "UCM-F015-CONDITIONING_AS_INTERVENTION"),
    _mutant_case("case.mutant.NonIdPointEstimate.C19.v1", "C19-nonidentified-effect-set", 19, "NonIdPointEstimate", "NonIdPointEstimateControl", "C19", "UCM-F015-CONDITIONING_AS_INTERVENTION", ("nonidentified_set",), "replay_ddrr"),
    _mutant_case("case.mutant.ObservationEqualsMechanism.C20.v1", "C20-observation-state-channel-separation", 20, "ObservationEqualsMechanism", "ObservationEqualsMechanismControl", "C20", "UCM-F014-ACTION_SEMANTICS_CONFLATED", ("observation_channel_separation",), "replay_ddrr"),
    _mutant_case("case.mutant.ReplayBatchDivergence.C22.v1", "C22-incremental-replay-duplicate-equivalence", 21, "ReplayBatchDivergence", "ReplayBatchDivergenceControl", "C22", "UCM-F019-UPDATE_INCONSISTENT", ("update_consistency",), "replay_ddrr"),
    _mutant_case("case.mutant.DoubleCountEvent.C22.v1", "C22-incremental-replay-duplicate-equivalence", 22, "DoubleCountEvent", "DoubleCountEventControl", "C22", "UCM-F019-UPDATE_INCONSISTENT", ("update_consistency",), "replay_ddrr"),
    _mutant_case("case.mutant.TripleLatentBlob.C33.v1", "C33-patient-state-root-audit", 23, "TripleLatentBlob", "TripleLatentBlobControl", "C33", "UCM-F005-TASK_SPECIFIC_STATE"),
    _mutant_case("case.mutant.UnsafeClosedWorld.C25.v1", "C25-attributable-ood-forced-match", 24, "UnsafeClosedWorld", "UnsafeClosedWorldControl", "C25", "UCM-F017-OOD_FORCED_MATCH", ("unsafe_closed_world",), "replay_ddrr"),
    _mutant_case("case.mutant.DangerousMeanCompressor.C24.v1", "C24-full-pair-dangerous-collision", 25, "DangerousMeanCompressor", "DangerousMeanCompressorControl", "C24", "UCM-F016-DANGEROUS_COLLISION", ("dangerous_collision",), "replay_ddrr"),
    _specificity_case("case.specificity.ExplicitSeedStochasticState.v1", "probe.specificity.ExplicitSeedStochasticState.v1", 26, "ExplicitSeedStochasticState", "HonestSeededControl", "ordinary_candidate", ("full_history_disclosure", "update_consistency", "warm_future_old_cut")),
    _specificity_case("case.specificity.BehaviorEquivalentSerialization.v1", "probe.specificity.BehaviorEquivalentSerialization.v1", 27, "BehaviorEquivalentSerialization", "BehaviorEquivalentSerializationControl", "ordinary_candidate", ("update_consistency",)),
    _specificity_case("case.specificity.DeclaredFullHistoryBaseline.v1", "probe.specificity.DeclaredFullHistoryBaseline.v1", 28, "DeclaredFullHistoryBaseline", "DeclaredFullHistoryBaselineControl", "baseline_only", ("full_history_disclosure",)),
    _specificity_case("case.specificity.CorrectNonidentifiedSet.v1", "probe.specificity.CorrectNonidentifiedSet.v1", 29, "CorrectNonidentifiedSet", "CorrectNonidentifiedSetControl", "ordinary_candidate", ("nonidentified_set",)),
)


def _validate_execution_case_registry() -> None:
    ordinals = tuple(item.execution_ordinal for item in PORTABLE_EXECUTION_CASES)
    if ordinals != tuple(range(len(PORTABLE_EXECUTION_CASES))):
        raise ProtocolViolation("portable execution-case ordinals must be contiguous")
    execution_case_ids = tuple(
        item.execution_case_id for item in PORTABLE_EXECUTION_CASES
    )
    if len(execution_case_ids) != len(set(execution_case_ids)):
        raise ProtocolViolation("portable execution cases reuse execution_case_id")
    expected_subjects = {
        (SubjectKind.MUTANT, item.mutant_id) for item in MUTANT_SPECS
    } | {
        (SubjectKind.SPECIFICITY_CONTROL, item.control_id)
        for item in SPECIFICITY_CONTROLS
    }
    actual_subjects = {
        (item.subject_kind, item.subject_id) for item in PORTABLE_EXECUTION_CASES
    }
    if actual_subjects != expected_subjects:
        raise ProtocolViolation(
            "portable execution cases must cover every matrix subject"
        )


_validate_execution_case_registry()
_EXECUTION_CASE_BY_ID = {
    item.execution_case_id: item for item in PORTABLE_EXECUTION_CASES
}


def portable_execution_case(execution_case_id: str) -> PortableExecutionCaseSpec:
    _name(execution_case_id, "execution_case_id")
    case = _EXECUTION_CASE_BY_ID.get(execution_case_id)
    if case is None:
        raise ProtocolViolation("unknown code-owned portable execution_case_id")
    return case


def execution_seed_for_case(base_seed: int, case: PortableExecutionCaseSpec) -> int:
    checked_base_seed = _execution_seed(base_seed, "execution base_seed")
    if type(case) is not PortableExecutionCaseSpec:
        raise ProtocolViolation("execution case must be PortableExecutionCaseSpec")
    canonical_case = portable_execution_case(case.execution_case_id)
    if case.to_wire() != canonical_case.to_wire():
        raise ProtocolViolation("execution case differs from the code-owned registry")
    value = (
        checked_base_seed
        + canonical_case.execution_ordinal * EXECUTION_CASE_SEED_STRIDE
    )
    return _execution_seed(value, "code-owned execution_seed")


def portable_runner_contract(runner_protocol: str) -> dict[str, Any]:
    """Return the sole code-owned execution-case registry and seed schedule."""

    _name(runner_protocol, "portable runner contract runner_protocol")
    return {
        "runner_protocol": runner_protocol,
        "execution_case_registry_protocol": (
            PORTABLE_EXECUTION_CASE_REGISTRY_PROTOCOL
        ),
        "runner_semantic_probe_protocol_alias": PORTABLE_SEMANTIC_PROBE_PROTOCOL_ALIAS,
        "execution_case_seed_stride": EXECUTION_CASE_SEED_STRIDE,
        "execution_case_main_offsets": list(EXECUTION_CASE_MAIN_OFFSETS),
        "update_consistency_lineage_offsets": list(
            UPDATE_CONSISTENCY_LINEAGE_OFFSETS
        ),
        "update_consistency_lineage_xor_mask": (
            UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
        ),
        "execution_cases": [item.to_wire() for item in PORTABLE_EXECUTION_CASES],
    }


def _case_seed_domain(
    base_seed: int, case: PortableExecutionCaseSpec
) -> frozenset[int]:
    execution_seed = execution_seed_for_case(base_seed, case)
    seeds = {
        execution_seed + offset for offset in EXECUTION_CASE_MAIN_OFFSETS
    }
    if max(seeds) >= 2**64:
        raise ProtocolViolation(
            "base_seed and code-owned operation seeds must fit unsigned 64-bit integer"
        )
    if "update_consistency" in case.semantic_probes:
        lineage_seed = execution_seed ^ UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
        lineage = {
            lineage_seed + offset
            for offset in UPDATE_CONSISTENCY_LINEAGE_OFFSETS
        }
        if max(lineage) >= 2**64:
            raise ProtocolViolation(
                "code-owned update-consistency lineage seeds must fit unsigned 64-bit integer"
            )
        if seeds.intersection(lineage):
            raise ProtocolViolation("one execution case reuses main and lineage seeds")
        seeds.update(lineage)
    return frozenset(seeds)


def _validate_base_seed_execution_domain(base_seed: object, label: str) -> int:
    """Prove disjoint uint64 seed domains for every code-owned case."""

    checked_base_seed = _execution_seed(base_seed, label)
    owners: dict[int, str] = {}
    for case in PORTABLE_EXECUTION_CASES:
        for derived_seed in _case_seed_domain(checked_base_seed, case):
            previous = owners.setdefault(derived_seed, case.execution_case_id)
            if previous != case.execution_case_id:
                raise ProtocolViolation(
                    f"{label} causes cross-case derived seed reuse"
                )
    return checked_base_seed


def _registry_wire() -> dict[str, Any]:
    return {
        "protocol": MATRIX_PROTOCOL,
        "execution_case_registry_protocol": (
            PORTABLE_EXECUTION_CASE_REGISTRY_PROTOCOL
        ),
        "portable_semantic_probe_protocol_alias": (
            PORTABLE_SEMANTIC_PROBE_PROTOCOL_ALIAS
        ),
        "execution_case_seed_stride": EXECUTION_CASE_SEED_STRIDE,
        "execution_case_main_offsets": list(EXECUTION_CASE_MAIN_OFFSETS),
        "update_consistency_lineage_offsets": list(
            UPDATE_CONSISTENCY_LINEAGE_OFFSETS
        ),
        "update_consistency_lineage_xor_mask": (
            UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
        ),
        "gates": [gate.to_wire() for gate in GATE_SPECS],
        "mutants": [mutant.to_wire() for mutant in MUTANT_SPECS],
        "specificity_controls": [control.to_wire() for control in SPECIFICITY_CONTROLS],
        "execution_cases": [case.to_wire() for case in PORTABLE_EXECUTION_CASES],
    }


REGISTRY_DIGEST = digest_json(_registry_wire())


def evaluate_mutation_matrix(
    observations: Iterable[MutationObservation],
) -> MutationMatrixReport:
    rows = tuple(observations)
    if any(type(row) is not MutationObservation for row in rows):
        raise ProtocolViolation(
            "mutation matrix rows must be exact MutationObservation values"
        )
    identities = [row.execution_case_id for row in rows]
    if len(identities) != len(set(identities)):
        raise ProtocolViolation("duplicate mutation execution_case_id")

    # The explicit registry ordinal, rather than caller iteration order, owns
    # the seed schedule.  Even a standalone matrix therefore proves that all
    # supplied rows share one base seed and the frozen stride.
    derived_base_seeds: set[int] = set()
    cases_by_execution_id: dict[str, PortableExecutionCaseSpec] = {}
    for row in rows:
        case = portable_execution_case(row.execution_case_id)
        cases_by_execution_id[row.execution_case_id] = case
        if (
            row.probe_id != case.probe_id
            or row.subject_kind is not case.subject_kind
            or row.subject_id != case.subject_id
        ):
            raise ProtocolViolation(
                "mutation observation differs from its code-owned execution case"
            )
        ordinal_offset = case.execution_ordinal * EXECUTION_CASE_SEED_STRIDE
        if row.execution_seed < ordinal_offset:
            raise ProtocolViolation(
                "mutation observation execution_seed precedes its registry ordinal"
            )
        derived_base_seeds.add(row.execution_seed - ordinal_offset)
    if len(derived_base_seeds) > 1:
        raise ProtocolViolation(
            "mutation observations do not share the code-owned ordinal seed schedule"
        )
    if derived_base_seeds:
        _validate_base_seed_execution_domain(
            next(iter(derived_base_seeds)), "matrix-derived base_seed"
        )

    mutant_by_id = {row.mutant_id: row for row in MUTANT_SPECS}
    gate_by_id = {row.gate_id: row for row in GATE_SPECS}
    control_by_id = {row.control_id: row for row in SPECIFICITY_CONTROLS}
    valid_kills: set[str] = set()
    covered_gates: set[str] = set()
    passed_controls: set[str] = set()
    failed_controls: set[str] = set()

    for row in rows:
        case = cases_by_execution_id[row.execution_case_id]
        if row.subject_kind is SubjectKind.MUTANT:
            spec = mutant_by_id.get(row.subject_id)
            if spec is None:
                raise ProtocolViolation(f"unknown mutant observation {row.subject_id!r}")
            if row.classification is not None:
                raise ProtocolViolation("mutant observation cannot carry classification")
            gate_spec = gate_by_id.get(row.actual_gate)
            valid = (
                row.outcome is ObservationOutcome.KILLED
                and row.actual_gate == case.expected_gate
                and row.actual_failure_code == case.expected_failure_code
                and gate_spec is not None
                and row.actual_failure_code in gate_spec.allowed_failure_codes
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
            if row.classification != case.classification:
                raise ProtocolViolation(
                    "specificity observation classification differs from execution case"
                )
            valid = (
                row.outcome is ObservationOutcome.PASSED
                and row.actual_gate is None
                and row.actual_failure_code is None
                and row.decisive_record_digest is not None
                and row.classification == case.classification
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
                    row.execution_case_id,
                    row.probe_id,
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
    "EXECUTION_CASE_SEED_STRIDE",
    "EXECUTION_CASE_MAIN_OFFSETS",
    "GATE_SPECS",
    "MATRIX_PROTOCOL",
    "MUTANT_SPECS",
    "MutationMatrixReport",
    "MutationObservation",
    "ObservationOutcome",
    "PORTABLE_EXECUTION_CASES",
    "PORTABLE_EXECUTION_CASE_REGISTRY_PROTOCOL",
    "PORTABLE_SEMANTIC_PROBE_PROTOCOL_ALIAS",
    "PortableExecutionCaseSpec",
    "REGISTRY_DIGEST",
    "SPECIFICITY_CONTROLS",
    "SubjectKind",
    "UPDATE_CONSISTENCY_LINEAGE_XOR_MASK",
    "UPDATE_CONSISTENCY_LINEAGE_OFFSETS",
    "_validate_base_seed_execution_domain",
    "evaluate_mutation_matrix",
    "execution_seed_for_case",
    "portable_execution_case",
    "portable_runner_contract",
]
