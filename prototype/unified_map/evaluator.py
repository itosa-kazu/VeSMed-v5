"""Rebuildable, denominator-safe evaluator primitives for UCM benchmark v1.

The evaluator consumes parent/judge-side raw rows plus a separately frozen
expected-cell manifest.  It intentionally emits two orthogonal axes:

* evidence completeness (complete vs ``UCM-E003`` incomplete), and
* observed candidate hard failures.

Consequently, missing tail rows or missing probe records can never turn into a
candidate PASS, while an externally proven dangerous collision is retained
even if some other part of the harness remains incomplete.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

import numpy as np

from .candidate_protocol import (
    DiagnoseResponse,
    ResultStatus,
    RolloutResponse,
    StateResponse,
    response_from_wire,
)
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
    validate_json_like,
)
from .metrics import PairClassification, PairProbe, binary_roc_auc, classify_pair


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
        raise ProtocolViolation(f"{label} must be hexadecimal") from exc
    return value


def _finite(value: object, label: str, *, nonnegative: bool = False) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise ProtocolViolation(f"{label} must be finite numeric")
    result = float(value)
    if nonnegative and result < 0.0:
        raise ProtocolViolation(f"{label} must be non-negative")
    return result


class EvidenceStatus(str, Enum):
    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class CandidateGateStatus(str, Enum):
    NO_HARD_FAILURE_OBSERVED = "no_hard_failure_observed"
    HARD_FAILURE = "hard_failure"


class EvaluationCohort(str, Enum):
    POPULATION = "population"
    PROBE = "probe"


class EvaluationTask(str, Enum):
    DIAGNOSIS = "diagnosis"
    NATURAL_FORECAST = "natural_forecast"
    INTERVENTION = "intervention"
    OOD = "ood"
    NEW_READOUT = "new_readout"


class EvaluationSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"
    REDTEAM = "redteam"


class OODAttribution(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    KNOWN = "known"
    KNOWN_EXTREME = "known_extreme"
    ATTRIBUTABLE = "ood_attributable"
    IRREDUCIBLE = "ood_irreducible"


class IdentificationKind(str, Enum):
    POINT = "point"
    PARTIAL = "partial"
    NONE = "none"


class FixtureSemantic(str, Enum):
    """Code-owned meaning of a raw evaluator fixture declared by the manifest.

    The raw oracle still carries its protocol and ``fixture_kind`` for exact
    replay, but it cannot opt itself out of semantic validation.  Generic rows
    may leave the declaration unset during the PRE-FREEZE migration.
    """

    W15B_NONIDENTIFIED_SET = "w15b_nonidentified_set"
    W18_OOD = "w18_ood"
    W04_DANGEROUS_COLLISION = "w04_dangerous_collision"
    W06_OBSERVATION_CHANNEL_SEPARATION = "w06_observation_channel_separation"


_CELL_FIXTURE_SEMANTICS = frozenset(
    {
        FixtureSemantic.W15B_NONIDENTIFIED_SET,
        FixtureSemantic.W18_OOD,
        FixtureSemantic.W06_OBSERVATION_CHANNEL_SEPARATION,
    }
)
_LEGACY_RAW_SELF_IDENTIFYING_CELL_FIXTURES = frozenset(
    {FixtureSemantic.W15B_NONIDENTIFIED_SET, FixtureSemantic.W18_OOD}
)


@dataclass(frozen=True, slots=True)
class EvaluationIssue:
    code: str
    record_id: str | None
    detail: str

    def __post_init__(self) -> None:
        _name(self.code, "issue code")
        if self.record_id is not None:
            _name(self.record_id, "issue record_id")
        _name(self.detail, "issue detail")

    def to_wire(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "record_id": self.record_id,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class ExpectedEvaluationCell:
    """Frozen judge metadata for one required population/query raw row."""

    record_id: str
    world_slot: str
    panel_id: str
    episode_alias: str
    cohort: EvaluationCohort
    task: EvaluationTask
    scope_digest: str
    split: EvaluationSplit
    family_id: str
    cut_alias: str
    training_replicate_id: str
    evaluation_replicate_id: str
    horizon: int
    policy_alias: str
    tail_member: bool = False
    ood_attribution: OODAttribution = OODAttribution.NOT_APPLICABLE
    identification: IdentificationKind = IdentificationKind.POINT
    unsafe_action_ids: tuple[str, ...] = ()
    required_fixture_semantic: FixtureSemantic | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.record_id, "expected record_id"),
            (self.world_slot, "world_slot"),
            (self.panel_id, "panel_id"),
            (self.episode_alias, "episode_alias"),
        ):
            _name(value, label)
        if type(self.cohort) is not EvaluationCohort:
            raise ProtocolViolation("cohort must be EvaluationCohort")
        if type(self.task) is not EvaluationTask:
            raise ProtocolViolation("task must be EvaluationTask")
        _digest(self.scope_digest, "expected scope_digest")
        if type(self.split) is not EvaluationSplit:
            raise ProtocolViolation("split must be EvaluationSplit")
        for value, label in (
            (self.family_id, "family_id"),
            (self.cut_alias, "cut_alias"),
            (self.training_replicate_id, "training_replicate_id"),
            (self.evaluation_replicate_id, "evaluation_replicate_id"),
            (self.policy_alias, "policy_alias"),
        ):
            _name(value, label)
        if type(self.horizon) is not int or self.horizon < 0:
            raise ProtocolViolation("horizon must be a non-negative integer")
        if type(self.tail_member) is not bool:
            raise ProtocolViolation("tail_member must be boolean")
        if type(self.ood_attribution) is not OODAttribution:
            raise ProtocolViolation("ood_attribution must be OODAttribution")
        if type(self.identification) is not IdentificationKind:
            raise ProtocolViolation("identification must be IdentificationKind")
        if type(self.unsafe_action_ids) is not tuple or any(
            type(item) is not str or not item for item in self.unsafe_action_ids
        ):
            raise ProtocolViolation("unsafe_action_ids must be tuple[str, ...]")
        if len(set(self.unsafe_action_ids)) != len(self.unsafe_action_ids):
            raise ProtocolViolation("unsafe_action_ids must be unique")
        if self.required_fixture_semantic is not None:
            if (
                type(self.required_fixture_semantic) is not FixtureSemantic
                or self.required_fixture_semantic not in _CELL_FIXTURE_SEMANTICS
            ):
                raise ProtocolViolation(
                    "evaluation cell required_fixture_semantic is not a cell fixture"
                )
            if (
                self.required_fixture_semantic
                is FixtureSemantic.W15B_NONIDENTIFIED_SET
                and (
                    self.world_slot != "W15B"
                    or self.task is not EvaluationTask.INTERVENTION
                    or self.cohort is not EvaluationCohort.PROBE
                    or self.identification
                    not in {IdentificationKind.PARTIAL, IdentificationKind.NONE}
                )
            ):
                raise ProtocolViolation(
                    "W15B fixture semantic requires a nonidentified intervention probe"
                )
            if (
                self.required_fixture_semantic is FixtureSemantic.W18_OOD
                and (
                    self.world_slot != "W18"
                    or self.task is not EvaluationTask.OOD
                    or self.cohort is not EvaluationCohort.PROBE
                )
            ):
                raise ProtocolViolation("W18 fixture semantic requires an OOD probe")
            if (
                self.required_fixture_semantic
                is FixtureSemantic.W06_OBSERVATION_CHANNEL_SEPARATION
                and (
                    self.world_slot != "W06"
                    or self.panel_id != "observation-channel-only"
                    or self.task is not EvaluationTask.INTERVENTION
                    or self.cohort is not EvaluationCohort.PROBE
                    or self.identification is not IdentificationKind.POINT
                    or self.horizon != 4
                )
            ):
                raise ProtocolViolation(
                    "W06 fixture semantic requires the point-identified "
                    "observation-channel intervention probe"
                )

    def to_wire(self) -> dict[str, Any]:
        body = {
            "record_id": self.record_id,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "episode_alias": self.episode_alias,
            "cohort": self.cohort.value,
            "task": self.task.value,
            "scope_digest": self.scope_digest,
            "split": self.split.value,
            "family_id": self.family_id,
            "cut_alias": self.cut_alias,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "horizon": self.horizon,
            "policy_alias": self.policy_alias,
            "tail_member": self.tail_member,
            "ood_attribution": self.ood_attribution.value,
            "identification": self.identification.value,
            "unsafe_action_ids": list(self.unsafe_action_ids),
        }
        if self.required_fixture_semantic is not None:
            body["required_fixture_semantic"] = self.required_fixture_semantic.value
        return body


@dataclass(frozen=True, slots=True)
class RawEvaluationRecord:
    """One lossless judge-linked candidate prediction row.

    Optional metric fields are task-dependent, but the raw candidate and
    oracle objects and their digests are always required.  The evaluator
    validates those digests before using any extracted scalar.
    """

    record_id: str
    world_slot: str
    panel_id: str
    episode_alias: str
    cohort: EvaluationCohort
    task: EvaluationTask
    result_status: ResultStatus
    scope_digest: str
    split: EvaluationSplit
    family_id: str
    cut_alias: str
    training_replicate_id: str
    evaluation_replicate_id: str
    horizon: int
    policy_alias: str
    state_hash: str
    public_input_digest: str
    query_digest: str
    candidate_output: dict[str, Any]
    candidate_output_digest: str
    oracle_record: dict[str, Any]
    oracle_record_digest: str
    analysis_weight: float
    loss: float | None = None
    selection_confidence: float | None = None
    unknown_probability: float | None = None
    max_known_probability: float | None = None
    chosen_action_id: str | None = None
    action_ids: tuple[str, ...] = ()
    predicted_utilities: tuple[float, ...] = ()
    oracle_utilities: tuple[float, ...] = ()
    all_compatible_catastrophic: bool = False

    def __post_init__(self) -> None:
        for value, label in (
            (self.record_id, "record_id"),
            (self.world_slot, "world_slot"),
            (self.panel_id, "panel_id"),
            (self.episode_alias, "episode_alias"),
        ):
            _name(value, label)
        if type(self.cohort) is not EvaluationCohort:
            raise ProtocolViolation("cohort must be EvaluationCohort")
        if type(self.task) is not EvaluationTask:
            raise ProtocolViolation("task must be EvaluationTask")
        if type(self.result_status) is not ResultStatus:
            raise ProtocolViolation("result_status must be ResultStatus")
        if type(self.split) is not EvaluationSplit:
            raise ProtocolViolation("raw split must be EvaluationSplit")
        for value, label in (
            (self.family_id, "raw family_id"),
            (self.cut_alias, "raw cut_alias"),
            (self.training_replicate_id, "raw training_replicate_id"),
            (self.evaluation_replicate_id, "raw evaluation_replicate_id"),
            (self.policy_alias, "raw policy_alias"),
        ):
            _name(value, label)
        if type(self.horizon) is not int or self.horizon < 0:
            raise ProtocolViolation("raw horizon must be a non-negative integer")
        for value, label in (
            (self.scope_digest, "scope_digest"),
            (self.state_hash, "state_hash"),
            (self.public_input_digest, "public_input_digest"),
            (self.query_digest, "query_digest"),
            (self.candidate_output_digest, "candidate_output_digest"),
            (self.oracle_record_digest, "oracle_record_digest"),
        ):
            _digest(value, label)
        if type(self.candidate_output) is not dict or type(self.oracle_record) is not dict:
            raise ProtocolViolation("raw candidate/oracle records must be exact objects")
        validate_json_like(self.candidate_output)
        validate_json_like(self.oracle_record)
        _finite(self.analysis_weight, "analysis_weight", nonnegative=True)
        for value, label in (
            (self.loss, "loss"),
            (self.selection_confidence, "selection_confidence"),
            (self.unknown_probability, "unknown_probability"),
            (self.max_known_probability, "max_known_probability"),
        ):
            if value is not None:
                numeric = _finite(value, label, nonnegative=(label == "loss"))
                if "probability" in label or label == "selection_confidence":
                    if not 0.0 <= numeric <= 1.0:
                        raise ProtocolViolation(f"{label} must lie in [0,1]")
        if self.chosen_action_id is not None:
            _name(self.chosen_action_id, "chosen_action_id")
        for sequence, label in (
            (self.action_ids, "action_ids"),
            (self.predicted_utilities, "predicted_utilities"),
            (self.oracle_utilities, "oracle_utilities"),
        ):
            if type(sequence) is not tuple:
                raise ProtocolViolation(f"{label} must be a tuple")
        if any(type(item) is not str or not item for item in self.action_ids):
            raise ProtocolViolation("action_ids must contain names")
        if len(self.action_ids) != len(set(self.action_ids)):
            raise ProtocolViolation("action_ids must be unique")
        for values, label in (
            (self.predicted_utilities, "predicted_utilities"),
            (self.oracle_utilities, "oracle_utilities"),
        ):
            for value in values:
                _finite(value, label)
        if type(self.all_compatible_catastrophic) is not bool:
            raise ProtocolViolation("all_compatible_catastrophic must be boolean")

    def to_wire(self) -> dict[str, Any]:
        """Losslessly serialize the judge-linked raw row.

        The evaluator historically consumed typed rows only.  Mutation
        evidence also needs a canonical preimage for the *entire* row so that
        extracted OOD/action/set fields cannot be replaced and re-signed
        independently of the candidate response that produced them.
        """

        body = {
            "schema_version": "ucm-raw-evaluation-record/1",
            "record_id": self.record_id,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "episode_alias": self.episode_alias,
            "cohort": self.cohort.value,
            "task": self.task.value,
            "result_status": self.result_status.value,
            "scope_digest": self.scope_digest,
            "split": self.split.value,
            "family_id": self.family_id,
            "cut_alias": self.cut_alias,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "horizon": self.horizon,
            "policy_alias": self.policy_alias,
            "state_hash": self.state_hash,
            "public_input_digest": self.public_input_digest,
            "query_digest": self.query_digest,
            "candidate_output": self.candidate_output,
            "candidate_output_digest": self.candidate_output_digest,
            "oracle_record": self.oracle_record,
            "oracle_record_digest": self.oracle_record_digest,
            "analysis_weight": self.analysis_weight,
            "loss": self.loss,
            "selection_confidence": self.selection_confidence,
            "unknown_probability": self.unknown_probability,
            "max_known_probability": self.max_known_probability,
            "chosen_action_id": self.chosen_action_id,
            "action_ids": list(self.action_ids),
            "predicted_utilities": list(self.predicted_utilities),
            "oracle_utilities": list(self.oracle_utilities),
            "all_compatible_catastrophic": self.all_compatible_catastrophic,
        }
        validate_json_like(body)
        return body


@dataclass(frozen=True, slots=True)
class PairThresholds:
    candidate_same_epsilon: float
    candidate_split_delta: float
    oracle_distinguishable_delta: float
    oracle_equivalent_epsilon: float
    catastrophic_margin: float

    def __post_init__(self) -> None:
        for name in (
            "candidate_same_epsilon",
            "candidate_split_delta",
            "oracle_distinguishable_delta",
            "oracle_equivalent_epsilon",
            "catastrophic_margin",
        ):
            _finite(getattr(self, name), name, nonnegative=True)

    def to_wire(self) -> dict[str, float]:
        return {
            "candidate_same_epsilon": self.candidate_same_epsilon,
            "candidate_split_delta": self.candidate_split_delta,
            "oracle_distinguishable_delta": self.oracle_distinguishable_delta,
            "oracle_equivalent_epsilon": self.oracle_equivalent_epsilon,
            "catastrophic_margin": self.catastrophic_margin,
        }


@dataclass(frozen=True, slots=True)
class ExpectedPairCell:
    pair_id: str
    world_slot: str
    panel_id: str
    thresholds: PairThresholds
    scope_digest: str
    split: EvaluationSplit
    family_id: str
    training_replicate_id: str
    evaluation_replicate_id: str
    required_fixture_semantic: FixtureSemantic | None = None

    def __post_init__(self) -> None:
        _name(self.pair_id, "pair_id")
        _name(self.world_slot, "pair world_slot")
        _name(self.panel_id, "pair panel_id")
        if type(self.thresholds) is not PairThresholds:
            raise ProtocolViolation("pair thresholds must be PairThresholds")
        _digest(self.scope_digest, "pair scope_digest")
        if type(self.split) is not EvaluationSplit:
            raise ProtocolViolation("pair split must be EvaluationSplit")
        for value, label in (
            (self.family_id, "pair family_id"),
            (self.training_replicate_id, "pair training_replicate_id"),
            (self.evaluation_replicate_id, "pair evaluation_replicate_id"),
        ):
            _name(value, label)
        if self.required_fixture_semantic is not None:
            if (
                type(self.required_fixture_semantic) is not FixtureSemantic
                or self.required_fixture_semantic
                is not FixtureSemantic.W04_DANGEROUS_COLLISION
                or self.world_slot != "W04"
            ):
                raise ProtocolViolation(
                    "pair required_fixture_semantic must be the W04 collision contract"
                )

    def to_wire(self) -> dict[str, Any]:
        body = {
            "pair_id": self.pair_id,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "thresholds": self.thresholds.to_wire(),
            "scope_digest": self.scope_digest,
            "split": self.split.value,
            "family_id": self.family_id,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
        }
        if self.required_fixture_semantic is not None:
            body["required_fixture_semantic"] = self.required_fixture_semantic.value
        return body


@dataclass(frozen=True, slots=True)
class RawPairRecord:
    pair_id: str
    world_slot: str
    panel_id: str
    probe: PairProbe
    scope_digest: str
    split: EvaluationSplit
    family_id: str
    training_replicate_id: str
    evaluation_replicate_id: str
    analysis_weight: float
    candidate_record: dict[str, Any]
    candidate_record_digest: str
    oracle_record: dict[str, Any]
    oracle_record_digest: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.pair_id, "pair_id"),
            (self.world_slot, "pair world_slot"),
            (self.panel_id, "pair panel_id"),
        ):
            _name(value, label)
        if type(self.probe) is not PairProbe or self.probe.pair_id != self.pair_id:
            raise ProtocolViolation("pair probe must match pair_id")
        _digest(self.scope_digest, "raw pair scope_digest")
        if type(self.split) is not EvaluationSplit:
            raise ProtocolViolation("raw pair split must be EvaluationSplit")
        for value, label in (
            (self.family_id, "raw pair family_id"),
            (self.training_replicate_id, "raw pair training_replicate_id"),
            (self.evaluation_replicate_id, "raw pair evaluation_replicate_id"),
        ):
            _name(value, label)
        _finite(self.analysis_weight, "pair analysis_weight", nonnegative=True)
        if type(self.candidate_record) is not dict or type(self.oracle_record) is not dict:
            raise ProtocolViolation("pair raw records must be exact objects")
        validate_json_like(self.candidate_record)
        validate_json_like(self.oracle_record)
        _digest(self.candidate_record_digest, "candidate_record_digest")
        _digest(self.oracle_record_digest, "oracle_record_digest")

    def to_wire(self) -> dict[str, Any]:
        body = {
            "schema_version": "ucm-raw-pair-record/1",
            "pair_id": self.pair_id,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "probe": {
                "pair_id": self.probe.pair_id,
                "state_hash_a": self.probe.state_hash_a,
                "state_hash_b": self.probe.state_hash_b,
                "candidate_signature_a": list(self.probe.candidate_signature_a),
                "candidate_signature_b": list(self.probe.candidate_signature_b),
                "oracle_signature_a": list(self.probe.oracle_signature_a),
                "oracle_signature_b": list(self.probe.oracle_signature_b),
                "oracle_action_values_a": list(self.probe.oracle_action_values_a),
                "oracle_action_values_b": list(self.probe.oracle_action_values_b),
                "information_relation": self.probe.information_relation,
                "intervention_identifiable": self.probe.intervention_identifiable,
            },
            "scope_digest": self.scope_digest,
            "split": self.split.value,
            "family_id": self.family_id,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "analysis_weight": self.analysis_weight,
            "candidate_record": self.candidate_record,
            "candidate_record_digest": self.candidate_record_digest,
            "oracle_record": self.oracle_record,
            "oracle_record_digest": self.oracle_record_digest,
        }
        validate_json_like(body)
        return body


@dataclass(frozen=True, slots=True)
class W19SafetyDeclaration:
    tail_episode_aliases: tuple[str, ...]
    tail_cohort_digest: str
    contraindicated_action_id: str = "A1"
    catastrophic_margin: float = 10.0

    def __post_init__(self) -> None:
        if type(self.tail_episode_aliases) is not tuple or not self.tail_episode_aliases:
            raise ProtocolViolation("W19 tail cohort must be a non-empty tuple")
        if any(type(item) is not str or not item for item in self.tail_episode_aliases):
            raise ProtocolViolation("W19 tail aliases must be names")
        if len(set(self.tail_episode_aliases)) != len(self.tail_episode_aliases):
            raise ProtocolViolation("W19 tail aliases must be unique")
        _digest(self.tail_cohort_digest, "tail_cohort_digest")
        _name(self.contraindicated_action_id, "contraindicated_action_id")
        _finite(self.catastrophic_margin, "catastrophic_margin", nonnegative=True)

    @staticmethod
    def compute_digest(aliases: Iterable[str]) -> str:
        values = tuple(sorted(aliases))
        return digest_json(
            {
                "schema_version": "ucm-w19-tail-cohort/1",
                "episode_aliases": list(values),
            }
        )


@dataclass(frozen=True, slots=True)
class EvaluationManifest:
    scope_digest: str
    expected_cells: tuple[ExpectedEvaluationCell, ...]
    expected_pairs: tuple[ExpectedPairCell, ...] = ()
    w19_safety: W19SafetyDeclaration | None = None
    forced_known_max_known: float = 0.90
    forced_known_max_unknown: float = 0.10
    # When the manifest is produced from a frozen corpus/query contract, this
    # digest binds the otherwise path-free expected-cell rows back to the
    # exact corpus digests and query declarations used to create them.  Hand-
    # assembled unit fixtures may leave it unset.  This is only a local
    # contract binding; it is not an authoritative freeze receipt and cannot
    # make ``benchmark_freeze_eligible`` true.
    cell_contract_digest: str | None = None

    def __post_init__(self) -> None:
        _digest(self.scope_digest, "evaluation manifest scope_digest")
        if type(self.expected_cells) is not tuple or not self.expected_cells:
            raise ProtocolViolation("expected_cells must be non-empty")
        if any(type(item) is not ExpectedEvaluationCell for item in self.expected_cells):
            raise ProtocolViolation("expected_cells contains wrong type")
        ids = [cell.record_id for cell in self.expected_cells]
        if len(ids) != len(set(ids)):
            raise ProtocolViolation("expected record ids must be unique")
        if any(cell.scope_digest != self.scope_digest for cell in self.expected_cells):
            raise ProtocolViolation("expected cells do not share manifest scope_digest")
        if type(self.expected_pairs) is not tuple or any(
            type(item) is not ExpectedPairCell for item in self.expected_pairs
        ):
            raise ProtocolViolation("expected_pairs contains wrong type")
        pair_ids = [cell.pair_id for cell in self.expected_pairs]
        if len(pair_ids) != len(set(pair_ids)):
            raise ProtocolViolation("expected pair ids must be unique")
        if any(cell.scope_digest != self.scope_digest for cell in self.expected_pairs):
            raise ProtocolViolation("expected pairs do not share manifest scope_digest")
        if self.w19_safety is not None and type(self.w19_safety) is not W19SafetyDeclaration:
            raise ProtocolViolation("w19_safety must be W19SafetyDeclaration")
        if self.cell_contract_digest is not None:
            _digest(self.cell_contract_digest, "cell_contract_digest")
        for value, label in (
            (self.forced_known_max_known, "forced_known_max_known"),
            (self.forced_known_max_unknown, "forced_known_max_unknown"),
        ):
            number = _finite(value, label)
            if not 0.0 <= number <= 1.0:
                raise ProtocolViolation(f"{label} must lie in [0,1]")

    def to_wire(self) -> dict[str, Any]:
        body = {
            "schema_version": "ucm-expected-cells/1",
            "scope_digest": self.scope_digest,
            "expected_cells": [cell.to_wire() for cell in self.expected_cells],
            "expected_pairs": [cell.to_wire() for cell in self.expected_pairs],
            "w19_safety": None
            if self.w19_safety is None
            else {
                "tail_episode_aliases": list(self.w19_safety.tail_episode_aliases),
                "tail_cohort_digest": self.w19_safety.tail_cohort_digest,
                "contraindicated_action_id": self.w19_safety.contraindicated_action_id,
                "catastrophic_margin": self.w19_safety.catastrophic_margin,
            },
            "forced_known_max_known": self.forced_known_max_known,
            "forced_known_max_unknown": self.forced_known_max_unknown,
            "cell_contract_digest": self.cell_contract_digest,
        }
        validate_json_like(body)
        return body

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


@dataclass(frozen=True, slots=True)
class HeadlineSlice:
    world_slot: str
    panel_id: str
    task: str
    denominator: int
    scored_count: int
    abstain_count: int
    unsupported_count: int
    mean_loss: float | None

    def to_wire(self) -> dict[str, Any]:
        return {
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "task": self.task,
            "denominator": self.denominator,
            "scored_count": self.scored_count,
            "abstain_count": self.abstain_count,
            "unsupported_count": self.unsupported_count,
            "mean_loss": self.mean_loss,
        }


@dataclass(frozen=True, slots=True)
class RiskCoveragePoint:
    coverage: float
    selective_risk: float

    def to_wire(self) -> dict[str, float]:
        return {"coverage": self.coverage, "selective_risk": self.selective_risk}


@dataclass(frozen=True, slots=True)
class OODSummary:
    primary_denominator: int
    attributable_ood_count: int
    known_count: int
    irreducible_excluded_count: int
    auroc: float | None
    average_precision: float | None
    known_coverage: float | None
    attributable_ood_abstention: float | None
    risk_coverage: tuple[RiskCoveragePoint, ...]
    aurc: float | None
    unsafe_non_abstain_count: int

    def to_wire(self) -> dict[str, Any]:
        return {
            "primary_denominator": self.primary_denominator,
            "attributable_ood_count": self.attributable_ood_count,
            "known_count": self.known_count,
            "irreducible_excluded_count": self.irreducible_excluded_count,
            "auroc": self.auroc,
            "average_precision": self.average_precision,
            "known_coverage": self.known_coverage,
            "attributable_ood_abstention": self.attributable_ood_abstention,
            "risk_coverage": [point.to_wire() for point in self.risk_coverage],
            "aurc": self.aurc,
            "unsafe_non_abstain_count": self.unsafe_non_abstain_count,
        }


@dataclass(frozen=True, slots=True)
class PairSummary:
    denominator: int
    dangerous_collision_count: int
    attributable_collision_count: int
    false_split_count: int
    classifications: tuple[PairClassification, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "denominator": self.denominator,
            "dangerous_collision_count": self.dangerous_collision_count,
            "attributable_collision_count": self.attributable_collision_count,
            "false_split_count": self.false_split_count,
            "classifications": [
                {
                    "pair_id": item.pair_id,
                    "candidate_distance": item.candidate_distance,
                    "oracle_distance": item.oracle_distance,
                    "exact_collision": item.exact_collision,
                    "functional_near_collision": item.functional_near_collision,
                    "dangerous_collision": item.dangerous_collision,
                    "attributable_collision": item.attributable_collision,
                    "false_split": item.false_split,
                    "cross_applied_regret": item.cross_applied_regret,
                }
                for item in self.classifications
            ],
        }


@dataclass(frozen=True, slots=True)
class W19Summary:
    expected_tail_episodes: int
    observed_tail_episodes: int
    intervention_denominator: int
    selected_count: int
    abstain_count: int
    mean_regret: float | None
    p95_regret: float | None
    max_regret: float | None
    cvar95_regret: float | None
    catastrophic_action_count: int
    catastrophic_action_rate: float

    def to_wire(self) -> dict[str, Any]:
        return {
            "expected_tail_episodes": self.expected_tail_episodes,
            "observed_tail_episodes": self.observed_tail_episodes,
            "intervention_denominator": self.intervention_denominator,
            "selected_count": self.selected_count,
            "abstain_count": self.abstain_count,
            "mean_regret": self.mean_regret,
            "p95_regret": self.p95_regret,
            "max_regret": self.max_regret,
            "cvar95_regret": self.cvar95_regret,
            "catastrophic_action_count": self.catastrophic_action_count,
            "catastrophic_action_rate": self.catastrophic_action_rate,
        }


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    evidence_status: EvidenceStatus
    candidate_gate_status: CandidateGateStatus
    headline: tuple[HeadlineSlice, ...]
    pairs: PairSummary
    ood: OODSummary | None
    w19: W19Summary | None
    blockers: tuple[EvaluationIssue, ...]
    failures: tuple[EvaluationIssue, ...]
    # The current evaluator checks local row/denominator integrity but its
    # cells do not yet bind authoritative public-input/query/oracle/state
    # ledger roots.  A structurally complete report is therefore never, by
    # itself, benchmark-freeze evidence.
    benchmark_freeze_eligible: bool
    benchmark_evidence_status: EvidenceStatus
    raw_population_count: int
    raw_probe_pair_count: int

    def __post_init__(self) -> None:
        if type(self.benchmark_freeze_eligible) is not bool:
            raise ProtocolViolation("benchmark_freeze_eligible must be boolean")
        if self.benchmark_freeze_eligible:
            raise ProtocolViolation(
                "this evaluator revision cannot produce benchmark-freeze-eligible evidence"
            )
        if type(self.benchmark_evidence_status) is not EvidenceStatus:
            raise ProtocolViolation(
                "benchmark_evidence_status must be EvidenceStatus"
            )
        if self.benchmark_evidence_status is not EvidenceStatus.INCOMPLETE:
            raise ProtocolViolation(
                "this evaluator revision requires incomplete benchmark evidence"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-evaluation-report/1",
            "evidence_status": self.evidence_status.value,
            "candidate_gate_status": self.candidate_gate_status.value,
            "headline": [item.to_wire() for item in self.headline],
            "pairs": self.pairs.to_wire(),
            "ood": None if self.ood is None else self.ood.to_wire(),
            "w19": None if self.w19 is None else self.w19.to_wire(),
            "blockers": [item.to_wire() for item in self.blockers],
            "failures": [item.to_wire() for item in self.failures],
            # Defence in depth: even low-level mutation that bypasses the
            # frozen dataclass constructor cannot serialize false freeze
            # evidence from this evaluator revision.
            "benchmark_freeze_eligible": False,
            "benchmark_evidence_status": EvidenceStatus.INCOMPLETE.value,
            "raw_population_count": self.raw_population_count,
            "raw_probe_pair_count": self.raw_probe_pair_count,
        }


def _average_precision(scores: np.ndarray, labels: np.ndarray) -> float:
    order = np.argsort(-scores, kind="mergesort")
    ordered_labels = labels[order]
    positives = int(np.sum(ordered_labels == 1))
    if positives == 0:
        raise ProtocolViolation("average precision requires a positive row")
    precision = np.cumsum(ordered_labels == 1) / np.arange(1, len(labels) + 1)
    return float(np.sum(precision[ordered_labels == 1]) / positives)


def _upper_cvar95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values, reverse=True)
    mass_per = 1.0 / len(ordered)
    remaining = 0.05
    total = 0.0
    for value in ordered:
        mass = min(mass_per, remaining)
        total += mass * value
        remaining -= mass
        if remaining <= 1e-15:
            break
    return total / 0.05


def _action_regret(record: RawEvaluationRecord) -> tuple[str, float] | None:
    if record.result_status is not ResultStatus.OK:
        return None
    if not record.action_ids:
        return None
    if not (
        len(record.action_ids)
        == len(record.predicted_utilities)
        == len(record.oracle_utilities)
    ):
        raise ProtocolViolation("action utility vectors are not aligned")
    chosen_index = int(np.argmax(np.asarray(record.predicted_utilities, dtype=float)))
    chosen = record.action_ids[chosen_index]
    if record.chosen_action_id is not None and record.chosen_action_id != chosen:
        raise ProtocolViolation("chosen_action_id contradicts predicted utilities")
    oracle = np.asarray(record.oracle_utilities, dtype=float)
    regret = max(float(np.max(oracle) - oracle[chosen_index]), 0.0)
    return chosen, regret


def _headline(
    cells: tuple[ExpectedEvaluationCell, ...],
    trusted_records: dict[str, RawEvaluationRecord],
) -> tuple[HeadlineSlice, ...]:
    groups: dict[
        tuple[str, str, EvaluationTask], list[ExpectedEvaluationCell]
    ] = {}
    for cell in cells:
        if cell.cohort is EvaluationCohort.POPULATION:
            groups.setdefault((cell.world_slot, cell.panel_id, cell.task), []).append(
                cell
            )
    result = []
    for (world, panel, task), expected_rows in sorted(
        groups.items(), key=lambda item: (item[0][0], item[0][1], item[0][2].value)
    ):
        rows = [
            trusted_records[cell.record_id]
            for cell in expected_rows
            if cell.record_id in trusted_records
        ]
        losses = [
            float(row.loss)
            for row in rows
            if row.result_status is ResultStatus.OK and row.loss is not None
        ]
        result.append(
            HeadlineSlice(
                world,
                panel,
                task.value,
                len(expected_rows),
                len(losses),
                sum(row.result_status is ResultStatus.ABSTAIN for row in rows),
                sum(
                    row.result_status
                    in {ResultStatus.UNSUPPORTED, ResultStatus.SCOPE_INSUFFICIENT}
                    for row in rows
                ),
                float(np.mean(losses)) if losses else None,
            )
        )
    return tuple(result)


def _risk_coverage(
    rows: list[RawEvaluationRecord], expected_denominator: int
) -> tuple[tuple[RiskCoveragePoint, ...], float | None]:
    accepted = [
        row
        for row in rows
        if row.result_status is ResultStatus.OK
        and row.loss is not None
        and row.selection_confidence is not None
    ]
    accepted.sort(key=lambda row: (-float(row.selection_confidence), row.record_id))
    if not accepted or expected_denominator <= 0:
        return (), None
    points = []
    running = 0.0
    for index, row in enumerate(accepted, 1):
        running += float(row.loss)
        points.append(RiskCoveragePoint(index / expected_denominator, running / index))
    # Rectangle rule with a fixed 1/N increment.  Abstained suffix remains in
    # the denominator rather than disappearing from the curve.
    aurc = float(
        sum(point.selective_risk for point in points) / expected_denominator
    )
    return tuple(points), aurc


def _ood_summary(
    trusted_records: dict[str, RawEvaluationRecord],
    expected: dict[str, ExpectedEvaluationCell],
) -> OODSummary | None:
    ood_cells = [cell for cell in expected.values() if cell.task is EvaluationTask.OOD]
    if not ood_cells:
        return None
    primary_cells = [
        cell
        for cell in ood_cells
        if cell.ood_attribution
        in {
            OODAttribution.KNOWN,
            OODAttribution.KNOWN_EXTREME,
            OODAttribution.ATTRIBUTABLE,
        }
    ]
    irreducible = sum(
        cell.ood_attribution is OODAttribution.IRREDUCIBLE for cell in ood_cells
    )
    primary = [
        trusted_records[cell.record_id]
        for cell in primary_cells
        if cell.record_id in trusted_records
    ]
    attributable = [
        row
        for row in primary
        if expected[row.record_id].ood_attribution is OODAttribution.ATTRIBUTABLE
    ]
    known = [
        row
        for row in primary
        if expected[row.record_id].ood_attribution
        in {OODAttribution.KNOWN, OODAttribution.KNOWN_EXTREME}
    ]
    scores = []
    labels = []
    for row in primary:
        if row.unknown_probability is not None:
            scores.append(float(row.unknown_probability))
            labels.append(
                int(expected[row.record_id].ood_attribution is OODAttribution.ATTRIBUTABLE)
            )
    auroc = None
    average_precision = None
    if scores and set(labels) == {0, 1}:
        score_array = np.asarray(scores, dtype=float)
        label_array = np.asarray(labels, dtype=int)
        auroc = binary_roc_auc(score_array, label_array)
        average_precision = _average_precision(score_array, label_array)
    curve, aurc = _risk_coverage(primary, len(primary_cells))
    expected_known_count = sum(
        cell.ood_attribution in {OODAttribution.KNOWN, OODAttribution.KNOWN_EXTREME}
        for cell in primary_cells
    )
    expected_attributable_count = sum(
        cell.ood_attribution is OODAttribution.ATTRIBUTABLE
        for cell in primary_cells
    )
    known_coverage = (
        sum(row.result_status is ResultStatus.OK for row in known)
        / expected_known_count
        if expected_known_count
        else None
    )
    ood_abstention = (
        sum(row.result_status is ResultStatus.ABSTAIN for row in attributable)
        / expected_attributable_count
        if expected_attributable_count
        else None
    )
    unsafe = sum(
        row.result_status is ResultStatus.OK
        and row.chosen_action_id in expected[row.record_id].unsafe_action_ids
        for row in attributable
    )
    return OODSummary(
        len(primary_cells),
        expected_attributable_count,
        expected_known_count,
        irreducible,
        auroc,
        average_precision,
        known_coverage,
        ood_abstention,
        curve,
        aurc,
        unsafe,
    )


_FIXTURE_CANDIDATE_CELL_PROTOCOL = "ucm-evaluator-fixture-candidate-cell/1"
_FIXTURE_ORACLE_PROTOCOL = "ucm-evaluator-fixture-oracle/1"
_FIXTURE_PAIR_CANDIDATE_PROTOCOL = "ucm-evaluator-fixture-pair-candidate/1"
_FIXTURE_PAIR_ORACLE_PROTOCOL = "ucm-evaluator-fixture-pair-oracle/1"
_IDENTIFIED_INTERVAL_PROTOCOL = "ucm-identified-mean-interval/1"
_W06_MECHANISM_EFFECT_THRESHOLD = 0.03
_W06_ORACLE_CHANNEL_EFFECT = (-0.75, -0.1875, -0.046875, -0.01171875)
_W06_ORACLE_MECHANISM_EFFECT = (0.0, 0.0, 0.0, 0.0)


def _closed_fixture_object(
    value: object, keys: frozenset[str], label: str
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ProtocolViolation(
            f"{label} must be a closed object with keys {sorted(keys)!r}"
        )
    return value


def _fixture_candidate_cell(value: object) -> dict[str, Any]:
    cell = _closed_fixture_object(
        value,
        frozenset(
            {
                "protocol",
                "state_response",
                "diagnosis_response",
                "rollout_responses",
            }
        ),
        "fixture candidate cell",
    )
    if cell["protocol"] != _FIXTURE_CANDIDATE_CELL_PROTOCOL:
        raise ProtocolViolation("fixture candidate cell protocol mismatch")
    state = response_from_wire(cell["state_response"])
    if type(state) is not StateResponse:
        raise ProtocolViolation("fixture candidate cell lacks initialize state")
    diagnosis_wire = cell["diagnosis_response"]
    if diagnosis_wire is not None:
        diagnosis = response_from_wire(diagnosis_wire)
        if type(diagnosis) is not DiagnoseResponse:
            raise ProtocolViolation("fixture candidate diagnosis response has wrong type")
    rollouts = cell["rollout_responses"]
    if type(rollouts) is not list or not rollouts:
        raise ProtocolViolation("fixture candidate rollouts must be non-empty")
    if any(type(response_from_wire(item)) is not RolloutResponse for item in rollouts):
        raise ProtocolViolation("fixture candidate rollout response has wrong type")
    return cell


def _point_utility(response: RolloutResponse, label: str) -> float:
    if response.result.status is not ResultStatus.OK:
        raise ProtocolViolation(f"{label} is not an ok rollout")
    value = _closed_fixture_object(
        response.result.utility_prediction,
        frozenset({"family", "value"}),
        f"{label} utility prediction",
    )
    if value["family"] != "point_mass" or type(value["value"]) is not float:
        raise ProtocolViolation(f"{label} utility must be an exact float point_mass")
    if not math.isfinite(value["value"]):
        raise ProtocolViolation(f"{label} utility must be finite")
    return value["value"]


def _point_trajectories(
    response: RolloutResponse,
    *,
    label: str,
    observables: tuple[str, ...],
    horizon: int,
) -> dict[str, tuple[float, ...]]:
    """Parse exact point trajectories used by one manifest-declared fixture."""

    if response.result.status is not ResultStatus.OK:
        raise ProtocolViolation(f"{label} is not an ok rollout")
    predictions = response.result.observable_predictions
    if type(predictions) is not dict or set(predictions) != set(observables):
        raise ProtocolViolation(f"{label} observable set mismatch")
    parsed: dict[str, tuple[float, ...]] = {}
    for observable in observables:
        value = _closed_fixture_object(
            predictions[observable],
            frozenset({"family", "horizon", "values"}),
            f"{label} {observable} point trajectory",
        )
        values = value["values"]
        if (
            value["family"] != "point_mass"
            or type(value["horizon"]) is not int
            or value["horizon"] != horizon
            or type(values) is not list
            or len(values) != horizon
            or any(type(item) is not float or not math.isfinite(item) for item in values)
        ):
            raise ProtocolViolation(
                f"{label} {observable} must be an exact finite horizon-{horizon} point path"
            )
        parsed[observable] = tuple(values)
    return parsed


def _w06_observation_channel_projection(
    row: RawEvaluationRecord,
) -> tuple[
    tuple[str, ...],
    tuple[float, ...],
    str,
    tuple[float, ...],
    tuple[float, ...],
]:
    """Rebuild W06 candidate effects from raw responses, not extracted fields."""

    oracle = _closed_fixture_object(
        row.oracle_record,
        frozenset(
            {
                "protocol",
                "fixture_kind",
                "public_history_digest",
                "action_ids",
                "channel_observable_id",
                "mechanism_observable_id",
                "horizon",
                "oracle_channel_effect",
                "oracle_mechanism_effect",
                "latent_distribution_digest",
                "latent_distributions_exact",
                "oracle_utilities",
                "mechanism_effect_threshold",
            }
        ),
        "W06 fixture oracle",
    )
    if (
        oracle["protocol"] != _FIXTURE_ORACLE_PROTOCOL
        or oracle["fixture_kind"]
        != FixtureSemantic.W06_OBSERVATION_CHANNEL_SEPARATION.value
        or oracle["action_ids"] != ["NoNewAction", "A1"]
        or oracle["channel_observable_id"] != "obs_0"
        or oracle["mechanism_observable_id"] != "obs_1"
        or type(oracle["horizon"]) is not int
        or oracle["horizon"] != 4
        or oracle["latent_distributions_exact"] is not True
        or type(oracle["mechanism_effect_threshold"]) is not float
        or oracle["mechanism_effect_threshold"] != _W06_MECHANISM_EFFECT_THRESHOLD
    ):
        raise ProtocolViolation("W06 fixture oracle contract mismatch")
    _digest(oracle["public_history_digest"], "W06 public history digest")
    _digest(oracle["latent_distribution_digest"], "W06 latent distribution digest")
    for field_name, expected in (
        ("oracle_channel_effect", _W06_ORACLE_CHANNEL_EFFECT),
        ("oracle_mechanism_effect", _W06_ORACLE_MECHANISM_EFFECT),
    ):
        values = oracle[field_name]
        if (
            type(values) is not list
            or len(values) != 4
            or any(type(item) is not float or not math.isfinite(item) for item in values)
            or any(
                not math.isclose(item, target, rel_tol=0.0, abs_tol=1e-12)
                for item, target in zip(values, expected, strict=True)
            )
        ):
            raise ProtocolViolation(f"W06 {field_name} contradicts live fixture geometry")
    oracle_utilities = oracle["oracle_utilities"]
    if (
        type(oracle_utilities) is not list
        or len(oracle_utilities) != 2
        or any(
            type(item) is not float or not math.isfinite(item)
            for item in oracle_utilities
        )
    ):
        raise ProtocolViolation("W06 oracle utilities are malformed")

    candidate = _fixture_candidate_cell(row.candidate_output)
    if candidate["diagnosis_response"] is not None:
        raise ProtocolViolation("W06 candidate cell unexpectedly contains diagnosis")
    rollouts = tuple(response_from_wire(item) for item in candidate["rollout_responses"])
    if len(rollouts) != 2 or any(type(item) is not RolloutResponse for item in rollouts):
        raise ProtocolViolation("W06 candidate cell must contain no-op and A1 rollouts")
    paths = tuple(
        _point_trajectories(
            response,
            label=f"W06 action {action}",
            observables=("obs_0", "obs_1"),
            horizon=4,
        )
        for action, response in zip(("NoNewAction", "A1"), rollouts, strict=True)
    )
    predicted_utilities = tuple(
        _point_utility(response, f"W06 action {action}")
        for action, response in zip(("NoNewAction", "A1"), rollouts, strict=True)
    )
    chosen = ("NoNewAction", "A1")[
        int(np.argmax(np.asarray(predicted_utilities, dtype=float)))
    ]
    channel_effect = tuple(
        treated - control
        for control, treated in zip(paths[0]["obs_0"], paths[1]["obs_0"], strict=True)
    )
    mechanism_effect = tuple(
        treated - control
        for control, treated in zip(paths[0]["obs_1"], paths[1]["obs_1"], strict=True)
    )
    return (
        ("NoNewAction", "A1"),
        predicted_utilities,
        chosen,
        channel_effect,
        mechanism_effect,
    )


def _identified_mean_interval(response: RolloutResponse) -> tuple[float, float]:
    """Parse one exact W15B marginal interval (or a point mutant claim)."""

    if response.result.status is not ResultStatus.OK:
        raise ProtocolViolation("identified-set rollout is not ok")
    predictions = response.result.observable_predictions
    if type(predictions) is not dict or set(predictions) != {"obs_1"}:
        raise ProtocolViolation("identified-set rollout must predict exactly obs_1")
    value = predictions["obs_1"]
    if type(value) is not dict:
        raise ProtocolViolation("identified-set prediction must be an exact object")
    if value.get("protocol") == _IDENTIFIED_INTERVAL_PROTOCOL:
        value = _closed_fixture_object(
            value,
            frozenset({"protocol", "lower", "upper"}),
            "identified mean interval",
        )
        lower = value["lower"]
        upper = value["upper"]
        if type(lower) is not float or type(upper) is not float:
            raise ProtocolViolation("identified interval bounds must be exact floats")
    elif value.get("family") == "point_mass":
        # A point estimate is a legitimate parseable mutant output, not a
        # harness gap.  Convert it to its degenerate claimed set so C19 can
        # compare the actual claim to the public equivalence-class oracle.
        value = _closed_fixture_object(
            value,
            frozenset({"family", "horizon", "values"}),
            "point identified-mean claim",
        )
        if type(value["horizon"]) is not int or value["horizon"] != 1:
            raise ProtocolViolation("point identified-mean claim horizon mismatch")
        values = value["values"]
        if (
            type(values) is not list
            or len(values) != 1
            or type(values[0]) is not float
        ):
            raise ProtocolViolation("point identified-mean claim must contain one float")
        lower = upper = values[0]
    else:
        raise ProtocolViolation("unknown identified-mean prediction family")
    if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
        raise ProtocolViolation("identified interval is non-finite or reversed")
    return lower, upper


def _nonidentified_effect_claim(
    row: RawEvaluationRecord,
) -> tuple[tuple[float, float], tuple[float, float]]:
    oracle = _closed_fixture_object(
        row.oracle_record,
        frozenset(
            {
                "protocol",
                "fixture_kind",
                "public_history_digest",
                "action_ids",
                "identified_effect_set",
            }
        ),
        "W15B fixture oracle",
    )
    if (
        oracle["protocol"] != _FIXTURE_ORACLE_PROTOCOL
        or oracle["fixture_kind"] != "w15b_nonidentified_set"
        or oracle["action_ids"] != ["NoNewAction", "A1"]
    ):
        raise ProtocolViolation("W15B fixture oracle contract mismatch")
    _digest(oracle["public_history_digest"], "W15B public history digest")
    expected = oracle["identified_effect_set"]
    if (
        type(expected) is not list
        or len(expected) != 2
        or any(type(item) is not float or not math.isfinite(item) for item in expected)
        or expected[0] > expected[1]
    ):
        raise ProtocolViolation("W15B oracle identified set is malformed")
    candidate = _fixture_candidate_cell(row.candidate_output)
    if candidate["diagnosis_response"] is not None:
        raise ProtocolViolation("W15B candidate cell unexpectedly contains diagnosis")
    rollouts = tuple(response_from_wire(item) for item in candidate["rollout_responses"])
    if len(rollouts) != 2 or any(type(item) is not RolloutResponse for item in rollouts):
        raise ProtocolViolation("W15B candidate cell must contain both intervention rows")
    control = _identified_mean_interval(rollouts[0])
    treated = _identified_mean_interval(rollouts[1])
    claimed = (treated[0] - control[1], treated[1] - control[0])
    return claimed, (expected[0], expected[1])


def _fixture_ood_projection(
    row: RawEvaluationRecord,
) -> tuple[float, float, tuple[str, ...], tuple[float, ...], str]:
    oracle = _closed_fixture_object(
        row.oracle_record,
        frozenset(
            {
                "protocol",
                "fixture_kind",
                "public_history_digest",
                "label_order",
                "action_ids",
                "oracle_utilities",
                "unsafe_action_ids",
                "ood_attribution",
            }
        ),
        "W18 fixture oracle",
    )
    if (
        oracle["protocol"] != _FIXTURE_ORACLE_PROTOCOL
        or oracle["fixture_kind"] != "w18_ood"
    ):
        raise ProtocolViolation("W18 fixture oracle contract mismatch")
    _digest(oracle["public_history_digest"], "W18 public history digest")
    labels = oracle["label_order"]
    actions = oracle["action_ids"]
    utilities = oracle["oracle_utilities"]
    if (
        labels != ["C0", "C1", "unknown"]
        or actions != ["NoNewAction", "A1"]
        or type(utilities) is not list
        or len(utilities) != 2
        or any(type(item) is not float or not math.isfinite(item) for item in utilities)
        or type(oracle["unsafe_action_ids"]) is not list
        or any(type(item) is not str for item in oracle["unsafe_action_ids"])
        or type(oracle["ood_attribution"]) is not str
    ):
        raise ProtocolViolation("W18 fixture oracle fields are malformed")
    candidate = _fixture_candidate_cell(row.candidate_output)
    diagnosis_wire = candidate["diagnosis_response"]
    if diagnosis_wire is None:
        raise ProtocolViolation("W18 candidate cell lacks diagnosis")
    diagnosis = response_from_wire(diagnosis_wire)
    if type(diagnosis) is not DiagnoseResponse or diagnosis.result.status is not ResultStatus.OK:
        raise ProtocolViolation("W18 candidate diagnosis is not ok")
    if list(diagnosis.result.probabilities) != labels:
        raise ProtocolViolation("W18 candidate diagnosis labels/order mismatch")
    rollouts = tuple(response_from_wire(item) for item in candidate["rollout_responses"])
    if len(rollouts) != len(actions) or any(type(item) is not RolloutResponse for item in rollouts):
        raise ProtocolViolation("W18 candidate action rollouts are incomplete")
    predicted = tuple(
        _point_utility(item, f"W18 action {action}")
        for action, item in zip(actions, rollouts, strict=True)
    )
    chosen = actions[int(np.argmax(np.asarray(predicted, dtype=float)))]
    probabilities = diagnosis.result.probabilities
    return (
        probabilities["unknown"],
        max(probabilities["C0"], probabilities["C1"]),
        tuple(actions),
        predicted,
        chosen,
    )


def _candidate_pair_signature(
    endpoint: object,
    *,
    label_order: list[str],
    requested_observables: list[str],
) -> tuple[str, tuple[float, ...]]:
    cell = _fixture_candidate_cell(endpoint)
    diagnosis_wire = cell["diagnosis_response"]
    if diagnosis_wire is None:
        raise ProtocolViolation("pair endpoint lacks diagnosis response")
    diagnosis = response_from_wire(diagnosis_wire)
    if type(diagnosis) is not DiagnoseResponse or diagnosis.result.status is not ResultStatus.OK:
        raise ProtocolViolation("pair diagnosis response is not ok")
    if (
        len(diagnosis.result.probabilities) != 2
        or list(diagnosis.result.probabilities) != label_order
    ):
        raise ProtocolViolation("pair diagnosis labels/order mismatch")
    signature = [diagnosis.result.probabilities[label] for label in label_order]
    for index, wire in enumerate(cell["rollout_responses"]):
        response = response_from_wire(wire)
        if type(response) is not RolloutResponse:
            raise ProtocolViolation("pair rollout response has wrong type")
        signature.append(_point_utility(response, f"pair rollout {index}"))
        if list(response.result.observable_predictions) != requested_observables:
            raise ProtocolViolation("pair rollout observable order mismatch")
        for observable in requested_observables:
            prediction = _closed_fixture_object(
                response.result.observable_predictions[observable],
                frozenset({"family", "horizon", "values"}),
                "pair point trajectory",
            )
            values = prediction["values"]
            if (
                prediction["family"] != "point_mass"
                or type(prediction["horizon"]) is not int
                or prediction["horizon"] != 4
                or type(values) is not list
                or len(values) != 4
                or any(type(item) is not float or not math.isfinite(item) for item in values)
            ):
                raise ProtocolViolation("pair point trajectory must have exact horizon four")
            signature.extend(values)
    state_hash = digest_json(cell["state_response"]["state"])
    return state_hash, tuple(signature)


def _oracle_pair_signature(endpoint: object) -> tuple[tuple[float, ...], tuple[float, ...]]:
    value = _closed_fixture_object(
        endpoint,
        frozenset({"diagnosis", "rollouts"}),
        "pair oracle endpoint",
    )
    diagnosis = value["diagnosis"]
    rollouts = value["rollouts"]
    if (
        type(diagnosis) is not list
        or len(diagnosis) != 2
        or any(type(item) is not float or not math.isfinite(item) for item in diagnosis)
        or type(rollouts) is not list
        or len(rollouts) != 8
    ):
        raise ProtocolViolation("pair oracle endpoint is malformed")
    signature = list(diagnosis)
    utilities = []
    for rollout in rollouts:
        rollout = _closed_fixture_object(
            rollout,
            frozenset({"expected_utility", "observation_means"}),
            "pair oracle rollout",
        )
        utility = rollout["expected_utility"]
        means = rollout["observation_means"]
        if (
            type(utility) is not float
            or not math.isfinite(utility)
            or type(means) is not list
            or len(means) != 4
            or any(type(item) is not float or not math.isfinite(item) for item in means)
        ):
            raise ProtocolViolation("pair oracle rollout is malformed")
        utilities.append(utility)
        signature.append(utility)
        signature.extend(means)
    return tuple(signature), tuple(utilities)


def _derive_fixture_pair_probe(
    pair_id: str,
    candidate_record: dict[str, Any],
    oracle_record: dict[str, Any],
) -> PairProbe | None:
    if oracle_record.get("protocol") != _FIXTURE_PAIR_ORACLE_PROTOCOL:
        return None
    candidate = _closed_fixture_object(
        candidate_record,
        frozenset({"protocol", "endpoints"}),
        "fixture pair candidate record",
    )
    oracle = _closed_fixture_object(
        oracle_record,
        frozenset(
            {
                "protocol",
                "fixture_kind",
                "public_history_digests",
                "label_order",
                "action_ids",
                "requested_observables",
                "endpoints",
                "information_relation",
                "intervention_identifiable",
            }
        ),
        "fixture pair oracle record",
    )
    if (
        candidate["protocol"] != _FIXTURE_PAIR_CANDIDATE_PROTOCOL
        or oracle["fixture_kind"] != "w04_dangerous_collision"
        or candidate["endpoints"] is None
    ):
        raise ProtocolViolation("fixture pair protocol/kind mismatch")
    endpoints = candidate["endpoints"]
    oracle_endpoints = oracle["endpoints"]
    public_digests = oracle["public_history_digests"]
    label_order = oracle["label_order"]
    action_ids = oracle["action_ids"]
    observables = oracle["requested_observables"]
    if (
        type(endpoints) is not list
        or len(endpoints) != 2
        or type(oracle_endpoints) is not list
        or len(oracle_endpoints) != 2
        or type(public_digests) is not list
        or len(public_digests) != 2
        or any(_digest(item, "pair public history digest") != item for item in public_digests)
        or len(set(public_digests)) != 2
        or label_order != ["C0", "C1"]
        or type(action_ids) is not list
        or len(action_ids) != 8
        or any(type(item) is not str or not item or item.strip() != item for item in action_ids)
        or len(set(action_ids)) != 8
        or observables != ["obs_0", "obs_1"]
        or oracle["information_relation"] != "distinguishable_from_public_history"
        or oracle["intervention_identifiable"] is not True
    ):
        raise ProtocolViolation("fixture pair authority fields are malformed")
    left_state, left_candidate = _candidate_pair_signature(
        endpoints[0], label_order=label_order, requested_observables=observables
    )
    right_state, right_candidate = _candidate_pair_signature(
        endpoints[1], label_order=label_order, requested_observables=observables
    )
    if any(
        len(_fixture_candidate_cell(endpoint)["rollout_responses"]) != len(action_ids)
        for endpoint in endpoints
    ):
        raise ProtocolViolation("fixture pair did not execute the full policy set")
    left_oracle, left_actions = _oracle_pair_signature(oracle_endpoints[0])
    right_oracle, right_actions = _oracle_pair_signature(oracle_endpoints[1])
    return PairProbe(
        pair_id,
        left_state,
        right_state,
        left_candidate,
        right_candidate,
        left_oracle,
        right_oracle,
        left_actions,
        right_actions,
        oracle["information_relation"],
        oracle["intervention_identifiable"],
    )


def _fixture_pair_probe(row: RawPairRecord) -> PairProbe | None:
    return _derive_fixture_pair_probe(
        row.pair_id, row.candidate_record, row.oracle_record
    )


def evaluate_records(
    records: Iterable[RawEvaluationRecord],
    pair_records: Iterable[RawPairRecord],
    manifest: EvaluationManifest,
) -> EvaluationReport:
    """Evaluate raw rows against an exact frozen expected-cell manifest."""

    if type(manifest) is not EvaluationManifest:
        raise ProtocolViolation("manifest must be EvaluationManifest")
    rows = tuple(records)
    pairs = tuple(pair_records)
    if any(type(row) is not RawEvaluationRecord for row in rows):
        raise ProtocolViolation("records contains a non-RawEvaluationRecord")
    if any(type(row) is not RawPairRecord for row in pairs):
        raise ProtocolViolation("pair_records contains a non-RawPairRecord")

    blockers: list[EvaluationIssue] = []
    failures: list[EvaluationIssue] = []
    if manifest.cell_contract_digest is not None:
        blockers.append(
            EvaluationIssue(
                "UCM-E003-HARNESS_INCOMPLETE",
                None,
                "cell-contract-bound manifest is PRE_FREEZE_SCAFFOLD only; "
                "authoritative per-cell public/query/oracle/state roots are absent",
            )
        )
    expected = {cell.record_id: cell for cell in manifest.expected_cells}
    actual: dict[str, RawEvaluationRecord] = {}
    duplicate_record_ids: set[str] = set()
    for row in rows:
        if row.record_id in actual:
            duplicate_record_ids.add(row.record_id)
            blockers.append(
                EvaluationIssue(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    row.record_id,
                    "duplicate raw prediction record",
                )
            )
        else:
            actual[row.record_id] = row
    for record_id in sorted(set(expected) - set(actual)):
        blockers.append(
            EvaluationIssue(
                "UCM-E003-HARNESS_INCOMPLETE",
                record_id,
                "required raw prediction record is missing",
            )
        )
    for record_id in sorted(set(actual) - set(expected)):
        blockers.append(
            EvaluationIssue(
                "UCM-E003-HARNESS_INCOMPLETE",
                record_id,
                "unexpected raw prediction is outside expected-cells",
            )
        )

    common_ids = sorted(set(expected) & set(actual))
    trusted_actual: dict[str, RawEvaluationRecord] = {}
    for record_id in common_ids:
        row = actual[record_id]
        cell = expected[record_id]
        trusted = record_id not in duplicate_record_ids
        if (
            row.world_slot != cell.world_slot
            or row.panel_id != cell.panel_id
            or row.episode_alias != cell.episode_alias
            or row.cohort is not cell.cohort
            or row.task is not cell.task
            or row.scope_digest != cell.scope_digest
            or row.scope_digest != manifest.scope_digest
            or row.split is not cell.split
            or row.family_id != cell.family_id
            or row.cut_alias != cell.cut_alias
            or row.training_replicate_id != cell.training_replicate_id
            or row.evaluation_replicate_id != cell.evaluation_replicate_id
            or row.horizon != cell.horizon
            or row.policy_alias != cell.policy_alias
        ):
            trusted = False
            blockers.append(
                EvaluationIssue(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    record_id,
                    "raw row judge labels contradict expected-cells",
                )
            )
        expected_weight = 1.0 if cell.cohort is EvaluationCohort.POPULATION else 0.0
        if not math.isclose(float(row.analysis_weight), expected_weight, abs_tol=0.0):
            trusted = False
            blockers.append(
                EvaluationIssue(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    record_id,
                    "probe/population denominator weight is invalid",
                )
            )
        if digest_json(row.candidate_output) != row.candidate_output_digest:
            trusted = False
            blockers.append(
                EvaluationIssue(
                    "UCM-F023-RESULT_EVIDENCE_LOSS",
                    record_id,
                    "candidate raw output digest mismatch",
                )
            )
        if digest_json(row.oracle_record) != row.oracle_record_digest:
            trusted = False
            blockers.append(
                EvaluationIssue(
                    "UCM-F023-RESULT_EVIDENCE_LOSS",
                    record_id,
                    "oracle raw record digest mismatch",
                )
            )
        declared_fixture = cell.required_fixture_semantic
        observed_fixture_protocol = row.oracle_record.get("protocol")
        observed_fixture_kind = row.oracle_record.get("fixture_kind")
        if declared_fixture is not None and (
            observed_fixture_protocol != _FIXTURE_ORACLE_PROTOCOL
            or observed_fixture_kind != declared_fixture.value
        ):
            trusted = False
            blockers.append(
                EvaluationIssue(
                    "UCM-F023-RESULT_EVIDENCE_LOSS",
                    record_id,
                    "raw oracle protocol/kind contradicts the required fixture semantic",
                )
            )
        fixture_semantic: FixtureSemantic | None = None
        if declared_fixture is not None:
            fixture_semantic = declared_fixture
        elif observed_fixture_protocol == _FIXTURE_ORACLE_PROTOCOL:
            try:
                observed_semantic = FixtureSemantic(observed_fixture_kind)
            except (TypeError, ValueError):
                observed_semantic = None
            if observed_semantic in _LEGACY_RAW_SELF_IDENTIFYING_CELL_FIXTURES:
                fixture_semantic = observed_semantic
        if trusted and fixture_semantic in _CELL_FIXTURE_SEMANTICS:
            try:
                candidate_cell = _fixture_candidate_cell(row.candidate_output)
                derived_state_hash = digest_json(
                    candidate_cell["state_response"]["state"]
                )
                public_digest = row.oracle_record["public_history_digest"]
                _digest(public_digest, "fixture public history digest")
                if fixture_semantic is FixtureSemantic.W18_OOD:
                    (
                        derived_unknown,
                        derived_max_known,
                        derived_actions,
                        derived_utilities,
                        derived_chosen,
                    ) = _fixture_ood_projection(row)
                    derived_oracle = tuple(row.oracle_record["oracle_utilities"])
                    derived_status = ResultStatus.OK
                    exact_projection = (
                        row.result_status is derived_status
                        and row.state_hash == derived_state_hash
                        and row.public_input_digest == public_digest
                        and row.unknown_probability == derived_unknown
                        and row.max_known_probability == derived_max_known
                        and row.action_ids == derived_actions
                        and row.predicted_utilities == derived_utilities
                        and row.oracle_utilities == derived_oracle
                        and row.chosen_action_id == derived_chosen
                        and list(cell.unsafe_action_ids)
                        == row.oracle_record["unsafe_action_ids"]
                        and cell.ood_attribution.value
                        == row.oracle_record["ood_attribution"]
                    )
                elif (
                    fixture_semantic
                    is FixtureSemantic.W06_OBSERVATION_CHANNEL_SEPARATION
                ):
                    (
                        derived_actions,
                        derived_utilities,
                        derived_chosen,
                        _derived_channel_effect,
                        _derived_mechanism_effect,
                    ) = _w06_observation_channel_projection(row)
                    derived_oracle = tuple(row.oracle_record["oracle_utilities"])
                    exact_projection = (
                        row.result_status is ResultStatus.OK
                        and row.state_hash == derived_state_hash
                        and row.public_input_digest == public_digest
                        and cell.identification is IdentificationKind.POINT
                        and row.action_ids == derived_actions
                        and all(
                            type(value) is float
                            for value in row.predicted_utilities
                        )
                        and row.predicted_utilities == derived_utilities
                        and all(
                            type(value) is float for value in row.oracle_utilities
                        )
                        and row.oracle_utilities == derived_oracle
                        and row.chosen_action_id == derived_chosen
                    )
                else:
                    rollout_statuses = tuple(
                        response_from_wire(item).result.status
                        for item in candidate_cell["rollout_responses"]
                    )
                    exact_projection = (
                        row.result_status is ResultStatus.OK
                        and rollout_statuses == (ResultStatus.OK, ResultStatus.OK)
                        and row.state_hash == derived_state_hash
                        and row.public_input_digest == public_digest
                        and cell.identification
                        in {IdentificationKind.PARTIAL, IdentificationKind.NONE}
                        and not row.action_ids
                        and not row.predicted_utilities
                        and not row.oracle_utilities
                        and row.chosen_action_id is None
                    )
                if not exact_projection:
                    raise ProtocolViolation(
                        "fixture extracted fields differ from actual candidate/oracle bytes"
                    )
            except (KeyError, ProtocolViolation, TypeError, ValueError) as exc:
                trusted = False
                blockers.append(
                    EvaluationIssue(
                        "UCM-F023-RESULT_EVIDENCE_LOSS",
                        record_id,
                        f"fixture response projection is not exact: {exc}",
                    )
                )
        if not trusted:
            continue
        trusted_actual[record_id] = row
        if row.result_status is ResultStatus.OK and row.loss is None:
            blockers.append(
                EvaluationIssue(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    record_id,
                    "ok population/query row lacks a headline loss",
                )
            )
        if row.result_status in {ResultStatus.UNSUPPORTED, ResultStatus.SCOPE_INSUFFICIENT}:
            failures.append(
                EvaluationIssue(
                    "UCM-F021-REQUIRED_QUERY_UNSUPPORTED",
                    record_id,
                    f"required query returned {row.result_status.value}",
                )
            )
        if row.result_status in {ResultStatus.INVALID_INPUT, ResultStatus.NUMERICAL_FAILURE}:
            failures.append(
                EvaluationIssue(
                    "UCM-F022-INVALID_DISTRIBUTION",
                    record_id,
                    f"required query returned {row.result_status.value}",
                )
            )
        if (
            row.task is EvaluationTask.INTERVENTION
            and row.result_status is ResultStatus.OK
            and declared_fixture is not FixtureSemantic.W15B_NONIDENTIFIED_SET
        ):
            try:
                action = _action_regret(row)
            except ProtocolViolation as exc:
                failures.append(
                    EvaluationIssue(
                        "UCM-F022-INVALID_DISTRIBUTION", record_id, str(exc)
                    )
                )
            else:
                if action is None:
                    failures.append(
                        EvaluationIssue(
                            "UCM-F022-INVALID_DISTRIBUTION",
                            record_id,
                            "ok intervention row lacks aligned action utilities",
                        )
                    )

        if (
            row.task is EvaluationTask.INTERVENTION
            and cell.identification in {IdentificationKind.PARTIAL, IdentificationKind.NONE}
            and fixture_semantic is FixtureSemantic.W15B_NONIDENTIFIED_SET
        ):
            try:
                claimed_set, oracle_set = _nonidentified_effect_claim(row)
            except ProtocolViolation as exc:
                failures.append(
                    EvaluationIssue(
                        "UCM-F015-CONDITIONING_AS_INTERVENTION",
                        record_id,
                        f"nonidentified effect was not returned as an exact set: {exc}",
                    )
                )
            else:
                if claimed_set != oracle_set:
                    failures.append(
                        EvaluationIssue(
                            "UCM-F015-CONDITIONING_AS_INTERVENTION",
                            record_id,
                            (
                                "candidate pointified/narrowed a public-equivalence "
                                f"effect set: claimed={claimed_set!r}, oracle={oracle_set!r}"
                            ),
                        )
                    )

        if (
            row.task is EvaluationTask.INTERVENTION
            and fixture_semantic
            is FixtureSemantic.W06_OBSERVATION_CHANNEL_SEPARATION
        ):
            try:
                (
                    _actions,
                    _utilities,
                    _chosen,
                    channel_effect,
                    mechanism_effect,
                ) = _w06_observation_channel_projection(row)
            except ProtocolViolation as exc:
                blockers.append(
                    EvaluationIssue(
                        "UCM-F023-RESULT_EVIDENCE_LOSS",
                        record_id,
                        f"W06 fixture projection became unavailable: {exc}",
                    )
                )
            else:
                if max(abs(value) for value in mechanism_effect) > (
                    _W06_MECHANISM_EFFECT_THRESHOLD
                ):
                    failures.append(
                        EvaluationIssue(
                            "UCM-F014-ACTION_SEMANTICS_CONFLATED",
                            record_id,
                            (
                                "observation-only A1 was predicted to change the "
                                "latent-mechanism proxy: "
                                f"channel_effect={channel_effect!r}, "
                                f"mechanism_effect={mechanism_effect!r}"
                            ),
                        )
                    )

        attribution = cell.ood_attribution
        if row.task is EvaluationTask.OOD:
            if row.unknown_probability is None or row.max_known_probability is None:
                blockers.append(
                    EvaluationIssue(
                        "UCM-E003-HARNESS_INCOMPLETE",
                        record_id,
                        "OOD row lacks extracted known/unknown probabilities",
                    )
                )
            # Only publicly attributable OOD can trigger the forced-known gate.
            # An identical-prefix/private C2 row is deliberately excluded.
            if (
                attribution is OODAttribution.ATTRIBUTABLE
                and row.result_status is ResultStatus.OK
                and row.max_known_probability is not None
                and row.unknown_probability is not None
                and row.max_known_probability >= manifest.forced_known_max_known
                and row.unknown_probability <= manifest.forced_known_max_unknown
                and row.chosen_action_id in cell.unsafe_action_ids
            ):
                failures.append(
                    EvaluationIssue(
                        "UCM-F017-OOD_FORCED_MATCH",
                        record_id,
                        "publicly attributable OOD was forced known and given an unsafe action",
                    )
                )

    expected_pair = {cell.pair_id: cell for cell in manifest.expected_pairs}
    actual_pair: dict[str, RawPairRecord] = {}
    duplicate_pair_ids: set[str] = set()
    for row in pairs:
        if row.pair_id in actual_pair:
            duplicate_pair_ids.add(row.pair_id)
            blockers.append(
                EvaluationIssue(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    row.pair_id,
                    "duplicate raw pair record",
                )
            )
        else:
            actual_pair[row.pair_id] = row
    for pair_id in sorted(set(expected_pair) - set(actual_pair)):
        blockers.append(
            EvaluationIssue(
                "UCM-E003-HARNESS_INCOMPLETE",
                pair_id,
                "required behavior-pair raw record is missing",
            )
        )
    for pair_id in sorted(set(actual_pair) - set(expected_pair)):
        blockers.append(
            EvaluationIssue(
                "UCM-E003-HARNESS_INCOMPLETE",
                pair_id,
                "unexpected behavior pair is outside expected-cells",
            )
        )

    classifications = []
    trusted_pairs: dict[str, RawPairRecord] = {}
    for pair_id in sorted(set(expected_pair) & set(actual_pair)):
        row = actual_pair[pair_id]
        cell = expected_pair[pair_id]
        trusted = pair_id not in duplicate_pair_ids
        if (
            row.world_slot != cell.world_slot
            or row.panel_id != cell.panel_id
            or row.scope_digest != cell.scope_digest
            or row.scope_digest != manifest.scope_digest
            or row.split is not cell.split
            or row.family_id != cell.family_id
            or row.training_replicate_id != cell.training_replicate_id
            or row.evaluation_replicate_id != cell.evaluation_replicate_id
        ):
            trusted = False
            blockers.append(
                EvaluationIssue(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    pair_id,
                    "pair judge labels contradict expected-cells",
                )
            )
        if float(row.analysis_weight) != 0.0:
            trusted = False
            blockers.append(
                EvaluationIssue(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    pair_id,
                    "probe pair was assigned population/headline weight",
                )
            )
        if digest_json(row.candidate_record) != row.candidate_record_digest:
            trusted = False
            blockers.append(
                EvaluationIssue(
                    "UCM-F023-RESULT_EVIDENCE_LOSS",
                    pair_id,
                    "pair candidate record digest mismatch",
                )
            )
        if digest_json(row.oracle_record) != row.oracle_record_digest:
            trusted = False
            blockers.append(
                EvaluationIssue(
                    "UCM-F023-RESULT_EVIDENCE_LOSS",
                    pair_id,
                    "pair oracle record digest mismatch",
                )
            )
        declared_fixture = cell.required_fixture_semantic
        if declared_fixture is not None and (
            row.oracle_record.get("protocol") != _FIXTURE_PAIR_ORACLE_PROTOCOL
            or row.oracle_record.get("fixture_kind") != declared_fixture.value
        ):
            trusted = False
            blockers.append(
                EvaluationIssue(
                    "UCM-F023-RESULT_EVIDENCE_LOSS",
                    pair_id,
                    "raw pair oracle protocol/kind contradicts the required fixture semantic",
                )
            )
        if trusted:
            try:
                fixture_probe = _fixture_pair_probe(row)
                if declared_fixture is not None and fixture_probe is None:
                    raise ProtocolViolation("required fixture pair was not derived")
            except (KeyError, ProtocolViolation, TypeError, ValueError) as exc:
                trusted = False
                blockers.append(
                    EvaluationIssue(
                        "UCM-F023-RESULT_EVIDENCE_LOSS",
                        pair_id,
                        f"fixture pair projection is not exact: {exc}",
                    )
                )
            else:
                if fixture_probe is not None and fixture_probe != row.probe:
                    trusted = False
                    blockers.append(
                        EvaluationIssue(
                            "UCM-F023-RESULT_EVIDENCE_LOSS",
                            pair_id,
                            "pair probe differs from actual endpoint/oracle bytes",
                        )
                    )
        if not trusted:
            continue
        trusted_pairs[pair_id] = row
        thresholds = cell.thresholds
        classification = classify_pair(
            row.probe,
            candidate_same_epsilon=thresholds.candidate_same_epsilon,
            candidate_split_delta=thresholds.candidate_split_delta,
            oracle_distinguishable_delta=thresholds.oracle_distinguishable_delta,
            oracle_equivalent_epsilon=thresholds.oracle_equivalent_epsilon,
            catastrophic_margin=thresholds.catastrophic_margin,
        )
        classifications.append(classification)
        if classification.attributable_collision:
            failures.append(
                EvaluationIssue(
                    "UCM-F016-DANGEROUS_COLLISION",
                    pair_id,
                    "publicly distinguishable histories were functionally merged",
                )
            )

    pair_summary = PairSummary(
        len(manifest.expected_pairs),
        sum(item.dangerous_collision for item in classifications),
        sum(item.attributable_collision for item in classifications),
        sum(item.false_split for item in classifications),
        tuple(classifications),
    )

    w19_summary = None
    w19_cells = [cell for cell in manifest.expected_cells if cell.world_slot == "W19"]
    if w19_cells:
        declaration = manifest.w19_safety
        if declaration is None:
            blockers.append(
                EvaluationIssue(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    None,
                    "W19 rows exist without frozen tail safety declaration",
                )
            )
        else:
            expected_aliases = set(declaration.tail_episode_aliases)
            if W19SafetyDeclaration.compute_digest(expected_aliases) != declaration.tail_cohort_digest:
                blockers.append(
                    EvaluationIssue(
                        "UCM-E003-HARNESS_INCOMPLETE",
                        None,
                        "W19 frozen tail cohort digest is inconsistent",
                    )
                )
            manifest_tail = {
                cell.episode_alias for cell in w19_cells if cell.tail_member
            }
            if manifest_tail != expected_aliases:
                blockers.append(
                    EvaluationIssue(
                        "UCM-E003-HARNESS_INCOMPLETE",
                        None,
                        "W19 expected-cells do not exactly cover frozen tail cohort",
                    )
                )
            observed_tail = {
                trusted_actual[cell.record_id].episode_alias
                for cell in w19_cells
                if cell.tail_member and cell.record_id in trusted_actual
            }
            if observed_tail != expected_aliases:
                blockers.append(
                    EvaluationIssue(
                        "UCM-E003-HARNESS_INCOMPLETE",
                        None,
                        "W19 raw records are missing or adding frozen tail episodes",
                    )
                )
            tail_interventions = [
                trusted_actual[cell.record_id]
                for cell in w19_cells
                if cell.tail_member
                and cell.task is EvaluationTask.INTERVENTION
                and cell.record_id in trusted_actual
            ]
            expected_tail_intervention_count = sum(
                cell.tail_member and cell.task is EvaluationTask.INTERVENTION
                for cell in w19_cells
            )
            regrets: list[float] = []
            catastrophic = 0
            selected = 0
            abstained = 0
            for row in tail_interventions:
                if row.result_status is ResultStatus.ABSTAIN:
                    abstained += 1
                    continue
                if row.result_status is not ResultStatus.OK:
                    continue
                try:
                    chosen_and_regret = _action_regret(row)
                except ProtocolViolation:
                    continue
                if chosen_and_regret is None:
                    continue
                selected += 1
                chosen, regret = chosen_and_regret
                regrets.append(regret)
                cell = expected[row.record_id]
                catastrophic_identified = (
                    cell.identification is IdentificationKind.POINT
                    or row.all_compatible_catastrophic
                )
                if (
                    chosen == declaration.contraindicated_action_id
                    and catastrophic_identified
                    and regret >= declaration.catastrophic_margin
                ):
                    catastrophic += 1
                    failures.append(
                        EvaluationIssue(
                            "UCM-F016-DANGEROUS_COLLISION",
                            row.record_id,
                            "W19 point-identified contraindicated tail received catastrophic action",
                        )
                    )
            w19_summary = W19Summary(
                len(expected_aliases),
                len(observed_tail),
                expected_tail_intervention_count,
                selected,
                abstained,
                float(np.mean(regrets)) if regrets else None,
                float(np.quantile(regrets, 0.95)) if regrets else None,
                max(regrets) if regrets else None,
                _upper_cvar95(regrets),
                catastrophic,
                catastrophic / expected_tail_intervention_count
                if expected_tail_intervention_count
                else 0.0,
            )

    ood = _ood_summary(trusted_actual, expected) if common_ids else None
    # If the frozen manifest declares a primary OOD panel, both attributable
    # and known rows are needed for primary discrimination metrics.
    expected_ood = [cell for cell in manifest.expected_cells if cell.task is EvaluationTask.OOD]
    if expected_ood:
        labels = {
            cell.ood_attribution
            for cell in expected_ood
            if cell.ood_attribution is not OODAttribution.IRREDUCIBLE
        }
        if OODAttribution.ATTRIBUTABLE not in labels or not labels.intersection(
            {OODAttribution.KNOWN, OODAttribution.KNOWN_EXTREME}
        ):
            blockers.append(
                EvaluationIssue(
                    "UCM-E003-HARNESS_INCOMPLETE",
                    None,
                    "primary OOD panel lacks attributable-positive or known-negative cells",
                )
            )

    return EvaluationReport(
        EvidenceStatus.INCOMPLETE if blockers else EvidenceStatus.COMPLETE,
        CandidateGateStatus.HARD_FAILURE
        if any(issue.code.startswith("UCM-F0") and issue.code not in {"UCM-F021-REQUIRED_QUERY_UNSUPPORTED"} for issue in failures)
        else CandidateGateStatus.NO_HARD_FAILURE_OBSERVED,
        _headline(manifest.expected_cells, trusted_actual),
        pair_summary,
        ood,
        w19_summary,
        tuple(blockers),
        tuple(failures),
        False,
        EvidenceStatus.INCOMPLETE,
        sum(row.cohort is EvaluationCohort.POPULATION for row in rows),
        len(pairs),
    )


__all__ = [
    "CandidateGateStatus",
    "EvaluationCohort",
    "EvaluationIssue",
    "EvaluationManifest",
    "EvaluationReport",
    "EvaluationSplit",
    "EvaluationTask",
    "EvidenceStatus",
    "ExpectedEvaluationCell",
    "ExpectedPairCell",
    "HeadlineSlice",
    "IdentificationKind",
    "OODAttribution",
    "OODSummary",
    "PairSummary",
    "PairThresholds",
    "RawEvaluationRecord",
    "RawPairRecord",
    "RiskCoveragePoint",
    "W19SafetyDeclaration",
    "W19Summary",
    "evaluate_records",
]
