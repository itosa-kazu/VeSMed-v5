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

from .candidate_protocol import ResultStatus
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

    def to_wire(self) -> dict[str, Any]:
        return {
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

    def to_wire(self) -> dict[str, Any]:
        return {
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
    raw_population_count: int
    raw_probe_pair_count: int

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
        if row.task is EvaluationTask.INTERVENTION and row.result_status is ResultStatus.OK:
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
