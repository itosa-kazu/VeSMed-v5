"""Executable PRE-FREEZE M05--M08 metric semantics.

This module is an isolated measurement runtime.  It neither changes the
candidate RPC nor supplies benchmark/freeze authority.  In particular, OOD
labels are runner/judge truth and ``unknown_probability`` is the parent
runner's projection from the ordinary diagnosis/rollout response.  It is not
an additional candidate-owned OOD endpoint.

Rates are pair/example-weighted.  Every result retains both the exact integer
exposure count and the corresponding weight denominator.  Ties are never
split: AUROC gives a tied positive/negative pair one half credit; AUPRC and
operating points advance by complete equal-score blocks; selective-risk AURC
advances by complete equal-confidence blocks.  Empty denominators and
single-class discrimination are returned as typed undefined scalars rather
than NaN.  No aggregate score is implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Callable, Iterable, TypeVar

from .canonical import ProtocolViolation


BENCHMARK_STATUS = "PRE-FREEZE"
RUNTIME_AUTHORITY = "none"
FREEZE_AUTHORITY_CLAIMED = False
COMPOSITE_SCORE_SUPPORTED = False
OOD_PROJECTION_OWNER = "parent_runner_from_diagnose_and_rollout"
UNKNOWN_PROBABILITY_NLL_CLIP = 1e-12
UNKNOWN_PROBABILITY_NLL_CONVENTION = (
    "binary_log_score_after_clipping_probability_to_[1e-12,1-1e-12]"
)
RISK_COVERAGE_AURC_CONVENTION = (
    "right_continuous_area_over_actual_nonabstain_coverage;"
    "all_eligible_weight_is_denominator;uncovered_tail_not_imputed;"
    "no_nonabstain_coverage_is_typed_undefined"
)


def _real(value: object, label: str, *, nonnegative: bool = False) -> float:
    if type(value) not in {int, float}:
        raise ProtocolViolation(f"{label} must be a finite real, excluding bool")
    result = float(value)
    if not math.isfinite(result):
        raise ProtocolViolation(f"{label} must be finite")
    if nonnegative and result < 0.0:
        raise ProtocolViolation(f"{label} must be non-negative")
    return result


def _probability(value: object, label: str) -> float:
    result = _real(value, label)
    if result < 0.0 or result > 1.0:
        raise ProtocolViolation(f"{label} must be in [0,1]")
    return result


def _strict_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ProtocolViolation(f"{label} must be bool")
    return value


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise ProtocolViolation(f"{label} must be a non-empty string")
    return value


def _bytes(value: object, label: str) -> bytes:
    if type(value) is not bytes:
        raise ProtocolViolation(f"{label} must be exact bytes")
    return value


def _weight(value: object, label: str) -> float:
    result = _real(value, label)
    if result <= 0.0:
        raise ProtocolViolation(f"{label} must be positive")
    return result


@dataclass(frozen=True, slots=True)
class ScalarMetric:
    value: float | None
    reason: str | None

    @classmethod
    def defined(cls, value: float) -> ScalarMetric:
        if not math.isfinite(value):
            raise ProtocolViolation("defined metric value must be finite")
        return cls(float(value), None)

    @classmethod
    def undefined(cls, reason: str) -> ScalarMetric:
        return cls(None, _identifier(reason, "undefined reason"))


@dataclass(frozen=True, slots=True)
class RateMetric:
    numerator_count: int
    denominator_count: int
    numerator_weight: float
    denominator_weight: float
    rate: ScalarMetric


def _rate(rows: Iterable[object], predicate: Callable[[object], bool]) -> RateMetric:
    materialized = tuple(rows)
    numerator = tuple(row for row in materialized if predicate(row))
    denominator_weight = math.fsum(
        float(getattr(row, "weight")) for row in materialized
    )
    numerator_weight = math.fsum(float(getattr(row, "weight")) for row in numerator)
    scalar = (
        ScalarMetric.undefined("empty_denominator")
        if not materialized
        else ScalarMetric.defined(numerator_weight / denominator_weight)
    )
    return RateMetric(
        numerator_count=len(numerator),
        denominator_count=len(materialized),
        numerator_weight=numerator_weight,
        denominator_weight=denominator_weight,
        rate=scalar,
    )


@dataclass(frozen=True, slots=True)
class PairThresholds:
    epsilon_candidate_same: float
    delta_candidate_split: float
    epsilon_oracle_equivalent: float
    delta_oracle_distinguishable: float
    catastrophic_margin: float

    def __post_init__(self) -> None:
        candidate_same = _real(
            self.epsilon_candidate_same,
            "epsilon_candidate_same",
            nonnegative=True,
        )
        candidate_split = _real(
            self.delta_candidate_split,
            "delta_candidate_split",
            nonnegative=True,
        )
        oracle_equivalent = _real(
            self.epsilon_oracle_equivalent,
            "epsilon_oracle_equivalent",
            nonnegative=True,
        )
        oracle_distinguishable = _real(
            self.delta_oracle_distinguishable,
            "delta_oracle_distinguishable",
            nonnegative=True,
        )
        catastrophic = _real(
            self.catastrophic_margin, "catastrophic_margin", nonnegative=True
        )
        if candidate_same >= candidate_split:
            raise ProtocolViolation(
                "epsilon_candidate_same must be below delta_candidate_split"
            )
        if oracle_equivalent >= oracle_distinguishable:
            raise ProtocolViolation(
                "epsilon_oracle_equivalent must be below delta_oracle_distinguishable"
            )
        object.__setattr__(self, "epsilon_candidate_same", candidate_same)
        object.__setattr__(self, "delta_candidate_split", candidate_split)
        object.__setattr__(self, "epsilon_oracle_equivalent", oracle_equivalent)
        object.__setattr__(self, "delta_oracle_distinguishable", oracle_distinguishable)
        object.__setattr__(self, "catastrophic_margin", catastrophic)


@dataclass(frozen=True, slots=True)
class PairMetricProbe:
    pair_id: str
    cohort: str
    weight: float
    exact_state_hash_equal: bool
    candidate_distance: float
    oracle_distance: float
    attributable: bool
    dangerous_decision_margin: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "pair_id", _identifier(self.pair_id, "pair_id"))
        object.__setattr__(self, "cohort", _identifier(self.cohort, "cohort"))
        object.__setattr__(self, "weight", _weight(self.weight, "pair weight"))
        object.__setattr__(
            self,
            "exact_state_hash_equal",
            _strict_bool(self.exact_state_hash_equal, "exact_state_hash_equal"),
        )
        object.__setattr__(
            self,
            "candidate_distance",
            _real(self.candidate_distance, "candidate_distance", nonnegative=True),
        )
        object.__setattr__(
            self,
            "oracle_distance",
            _real(self.oracle_distance, "oracle_distance", nonnegative=True),
        )
        object.__setattr__(
            self, "attributable", _strict_bool(self.attributable, "attributable")
        )
        object.__setattr__(
            self,
            "dangerous_decision_margin",
            _real(
                self.dangerous_decision_margin,
                "dangerous_decision_margin",
                nonnegative=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class PairDecision:
    pair_id: str
    cohort: str
    weight: float
    candidate_distance: float
    oracle_distance: float
    attributable_eligibility: bool
    dangerous_decision_margin: float
    raw_exact_collision: bool
    functional_near_collision: bool
    attributable_collision: bool
    attributable_dangerous_collision: bool
    oracle_equivalent: bool
    functional_false_split: bool
    structural_redundancy: bool


def classify_metric_pair(
    row: PairMetricProbe, thresholds: PairThresholds
) -> PairDecision:
    oracle_distinguishable = (
        row.oracle_distance >= thresholds.delta_oracle_distinguishable
    )
    raw = row.exact_state_hash_equal and oracle_distinguishable
    near = (
        row.candidate_distance <= thresholds.epsilon_candidate_same
        and oracle_distinguishable
    )
    collision = raw or near
    attributable = row.attributable and collision
    dangerous = (
        attributable and row.dangerous_decision_margin >= thresholds.catastrophic_margin
    )
    oracle_equivalent = row.oracle_distance <= thresholds.epsilon_oracle_equivalent
    false_split = (
        oracle_equivalent and row.candidate_distance >= thresholds.delta_candidate_split
    )
    structural_redundancy = oracle_equivalent and not row.exact_state_hash_equal
    return PairDecision(
        pair_id=row.pair_id,
        cohort=row.cohort,
        weight=row.weight,
        candidate_distance=row.candidate_distance,
        oracle_distance=row.oracle_distance,
        attributable_eligibility=row.attributable,
        dangerous_decision_margin=row.dangerous_decision_margin,
        raw_exact_collision=raw,
        functional_near_collision=near,
        attributable_collision=attributable,
        attributable_dangerous_collision=dangerous,
        oracle_equivalent=oracle_equivalent,
        functional_false_split=false_split,
        structural_redundancy=structural_redundancy,
    )


@dataclass(frozen=True, slots=True)
class DangerousCollisionEvent:
    pair_id: str
    cohort: str
    weight: float
    candidate_distance: float
    oracle_distance: float
    dangerous_decision_margin: float
    raw_exact_collision: bool
    functional_near_collision: bool


@dataclass(frozen=True, slots=True)
class CollisionMetricSlice:
    cohort: str
    total_pair_count: int
    total_pair_weight: float
    oracle_distinguishable_denominator: RateMetric
    raw_exact_collision_rate: RateMetric
    functional_near_collision_rate: RateMetric
    attributable_pair_denominator: RateMetric
    attributable_collision_rate: RateMetric
    dangerous_events: tuple[DangerousCollisionEvent, ...]
    max_missed_oracle_distance: ScalarMetric


def _collision_slice(
    cohort: str, rows: tuple[PairMetricProbe, ...], thresholds: PairThresholds
) -> CollisionMetricSlice:
    decisions = {row.pair_id: classify_metric_pair(row, thresholds) for row in rows}
    distinguishable = tuple(
        row
        for row in rows
        if row.oracle_distance >= thresholds.delta_oracle_distinguishable
    )
    attributable = tuple(row for row in rows if row.attributable)
    collided = tuple(
        row
        for row in distinguishable
        if decisions[row.pair_id].raw_exact_collision
        or decisions[row.pair_id].functional_near_collision
    )
    events = tuple(
        DangerousCollisionEvent(
            pair_id=row.pair_id,
            cohort=row.cohort,
            weight=row.weight,
            candidate_distance=row.candidate_distance,
            oracle_distance=row.oracle_distance,
            dangerous_decision_margin=row.dangerous_decision_margin,
            raw_exact_collision=decisions[row.pair_id].raw_exact_collision,
            functional_near_collision=decisions[row.pair_id].functional_near_collision,
        )
        for row in rows
        if decisions[row.pair_id].attributable_dangerous_collision
    )
    max_missed = (
        ScalarMetric.undefined("no_collision_event")
        if not collided
        else ScalarMetric.defined(max(row.oracle_distance for row in collided))
    )
    # Denominator objects use a tautological numerator to expose exact counts
    # and weights without inventing another unbound aggregation convention.
    distinguishable_denominator = _rate(distinguishable, lambda _row: True)
    attributable_denominator = _rate(attributable, lambda _row: True)
    return CollisionMetricSlice(
        cohort=cohort,
        total_pair_count=len(rows),
        total_pair_weight=math.fsum(row.weight for row in rows),
        oracle_distinguishable_denominator=distinguishable_denominator,
        raw_exact_collision_rate=_rate(
            distinguishable, lambda row: decisions[row.pair_id].raw_exact_collision
        ),
        functional_near_collision_rate=_rate(
            distinguishable,
            lambda row: decisions[row.pair_id].functional_near_collision,
        ),
        attributable_pair_denominator=attributable_denominator,
        attributable_collision_rate=_rate(
            attributable, lambda row: decisions[row.pair_id].attributable_collision
        ),
        dangerous_events=events,
        max_missed_oracle_distance=max_missed,
    )


@dataclass(frozen=True, slots=True)
class CollisionMetricReport:
    overall: CollisionMetricSlice
    cohorts: tuple[CollisionMetricSlice, ...]
    pair_decisions: tuple[PairDecision, ...]


def collision_metrics(
    probes: Iterable[PairMetricProbe], thresholds: PairThresholds
) -> CollisionMetricReport:
    rows = tuple(
        sorted(
            _validated_unique_rows(probes, PairMetricProbe, "pair"),
            key=lambda row: row.pair_id,
        )
    )
    cohort_names = sorted({row.cohort for row in rows})
    return CollisionMetricReport(
        overall=_collision_slice("__all__", rows, thresholds),
        cohorts=tuple(
            _collision_slice(
                cohort, tuple(row for row in rows if row.cohort == cohort), thresholds
            )
            for cohort in cohort_names
        ),
        pair_decisions=tuple(classify_metric_pair(row, thresholds) for row in rows),
    )


@dataclass(frozen=True, slots=True)
class FalseSplitMetricSlice:
    cohort: str
    oracle_equivalent_denominator: RateMetric
    functional_false_split_rate: RateMetric
    structural_redundancy_count: int
    structural_redundancy_weight: float
    max_spurious_candidate_distance: ScalarMetric


def _false_split_slice(
    cohort: str, rows: tuple[PairMetricProbe, ...], thresholds: PairThresholds
) -> FalseSplitMetricSlice:
    decisions = {row.pair_id: classify_metric_pair(row, thresholds) for row in rows}
    equivalent = tuple(row for row in rows if decisions[row.pair_id].oracle_equivalent)
    false_splits = tuple(
        row for row in equivalent if decisions[row.pair_id].functional_false_split
    )
    return FalseSplitMetricSlice(
        cohort=cohort,
        oracle_equivalent_denominator=_rate(equivalent, lambda _row: True),
        functional_false_split_rate=_rate(
            equivalent, lambda row: decisions[row.pair_id].functional_false_split
        ),
        structural_redundancy_count=sum(
            decisions[row.pair_id].structural_redundancy for row in equivalent
        ),
        structural_redundancy_weight=math.fsum(
            row.weight
            for row in equivalent
            if decisions[row.pair_id].structural_redundancy
        ),
        max_spurious_candidate_distance=(
            ScalarMetric.undefined("no_false_split_event")
            if not false_splits
            else ScalarMetric.defined(
                max(row.candidate_distance for row in false_splits)
            )
        ),
    )


@dataclass(frozen=True, slots=True)
class FalseSplitMetricReport:
    overall: FalseSplitMetricSlice
    cohorts: tuple[FalseSplitMetricSlice, ...]
    pair_decisions: tuple[PairDecision, ...]


def false_split_metrics(
    probes: Iterable[PairMetricProbe], thresholds: PairThresholds
) -> FalseSplitMetricReport:
    rows = tuple(
        sorted(
            _validated_unique_rows(probes, PairMetricProbe, "pair"),
            key=lambda row: row.pair_id,
        )
    )
    cohort_names = sorted({row.cohort for row in rows})
    return FalseSplitMetricReport(
        overall=_false_split_slice("__all__", rows, thresholds),
        cohorts=tuple(
            _false_split_slice(
                cohort, tuple(row for row in rows if row.cohort == cohort), thresholds
            )
            for cohort in cohort_names
        ),
        pair_decisions=tuple(classify_metric_pair(row, thresholds) for row in rows),
    )


@dataclass(frozen=True, slots=True)
class OODExample:
    example_id: str
    cohort: str
    weight: float
    is_ood_runtime_truth: bool
    unknown_probability: float
    abstained: bool
    selective_loss: float
    unsafe_treatment_regret: float

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "example_id", _identifier(self.example_id, "example_id")
        )
        object.__setattr__(self, "cohort", _identifier(self.cohort, "cohort"))
        object.__setattr__(self, "weight", _weight(self.weight, "example weight"))
        object.__setattr__(
            self,
            "is_ood_runtime_truth",
            _strict_bool(self.is_ood_runtime_truth, "is_ood_runtime_truth"),
        )
        object.__setattr__(
            self,
            "unknown_probability",
            _probability(self.unknown_probability, "unknown_probability"),
        )
        object.__setattr__(self, "abstained", _strict_bool(self.abstained, "abstained"))
        loss = _probability(self.selective_loss, "selective_loss")
        object.__setattr__(self, "selective_loss", loss)
        object.__setattr__(
            self,
            "unsafe_treatment_regret",
            _real(
                self.unsafe_treatment_regret,
                "unsafe_treatment_regret",
                nonnegative=True,
            ),
        )


@dataclass(frozen=True, slots=True)
class OODThresholdPoint:
    threshold_inclusive: float
    true_positive_rate: float
    false_positive_rate: float


@dataclass(frozen=True, slots=True)
class RiskCoveragePoint:
    minimum_acceptance_confidence_inclusive: float
    coverage: float
    selective_risk: float


def _ood_class_weights(rows: tuple[OODExample, ...]) -> tuple[float, float]:
    positive = math.fsum(row.weight for row in rows if row.is_ood_runtime_truth)
    negative = math.fsum(row.weight for row in rows if not row.is_ood_runtime_truth)
    return positive, negative


def _ood_threshold_curve(rows: tuple[OODExample, ...]) -> tuple[OODThresholdPoint, ...]:
    positive, negative = _ood_class_weights(rows)
    if positive == 0.0 or negative == 0.0:
        return ()
    result: list[OODThresholdPoint] = []
    true_positive = 0.0
    false_positive = 0.0
    index = 0
    ordered = sorted(rows, key=lambda row: (-row.unknown_probability, row.example_id))
    while index < len(ordered):
        score = ordered[index].unknown_probability
        end = index + 1
        while end < len(ordered) and ordered[end].unknown_probability == score:
            end += 1
        for row in ordered[index:end]:
            if row.is_ood_runtime_truth:
                true_positive += row.weight
            else:
                false_positive += row.weight
        result.append(
            OODThresholdPoint(
                threshold_inclusive=score,
                true_positive_rate=true_positive / positive,
                false_positive_rate=false_positive / negative,
            )
        )
        index = end
    return tuple(result)


def _weighted_auroc(rows: tuple[OODExample, ...]) -> ScalarMetric:
    positive = tuple(row for row in rows if row.is_ood_runtime_truth)
    negative = tuple(row for row in rows if not row.is_ood_runtime_truth)
    positive_weight = math.fsum(row.weight for row in positive)
    negative_weight = math.fsum(row.weight for row in negative)
    if not positive or not negative:
        return ScalarMetric.undefined("single_class_discrimination")
    concordance = 0.0
    for pos in positive:
        for neg in negative:
            credit = (
                1.0
                if pos.unknown_probability > neg.unknown_probability
                else 0.5
                if pos.unknown_probability == neg.unknown_probability
                else 0.0
            )
            concordance += pos.weight * neg.weight * credit
    return ScalarMetric.defined(concordance / (positive_weight * negative_weight))


def _weighted_auprc(rows: tuple[OODExample, ...]) -> ScalarMetric:
    positive, negative = _ood_class_weights(rows)
    if positive == 0.0 or negative == 0.0:
        return ScalarMetric.undefined("single_class_discrimination")
    true_positive = 0.0
    false_positive = 0.0
    prior_recall = 0.0
    area = 0.0
    ordered = sorted(rows, key=lambda row: (-row.unknown_probability, row.example_id))
    index = 0
    while index < len(ordered):
        score = ordered[index].unknown_probability
        end = index + 1
        while end < len(ordered) and ordered[end].unknown_probability == score:
            end += 1
        for row in ordered[index:end]:
            if row.is_ood_runtime_truth:
                true_positive += row.weight
            else:
                false_positive += row.weight
        recall = true_positive / positive
        precision = true_positive / (true_positive + false_positive)
        area += (recall - prior_recall) * precision
        prior_recall = recall
        index = end
    return ScalarMetric.defined(area)


def _risk_coverage(
    rows: tuple[OODExample, ...],
) -> tuple[ScalarMetric, float, tuple[RiskCoveragePoint, ...]]:
    if not rows:
        return ScalarMetric.undefined("empty_denominator"), 0.0, ()
    total_weight = math.fsum(row.weight for row in rows)
    accepted_weight = 0.0
    accepted_loss = 0.0
    previous_coverage = 0.0
    area = 0.0
    points: list[RiskCoveragePoint] = []
    # Actual typed abstentions are never silently reclassified as accepted by
    # the curve.  They remain in ``total_weight``, so the final coverage may be
    # below one.  The raw AURC integrates only [0, achieved coverage]; no loss
    # is imputed over the uncovered tail.  An all-abstain non-empty cohort has
    # zero final coverage but an undefined AURC: returning numeric zero would
    # falsely make complete refusal look like a best-possible risk curve.
    ordered = sorted(
        (row for row in rows if not row.abstained),
        key=lambda row: (-(1.0 - row.unknown_probability), row.example_id),
    )
    if not ordered:
        return ScalarMetric.undefined("no_nonabstain_coverage"), 0.0, ()
    index = 0
    while index < len(ordered):
        confidence = 1.0 - ordered[index].unknown_probability
        end = index + 1
        while (
            end < len(ordered) and 1.0 - ordered[end].unknown_probability == confidence
        ):
            end += 1
        for row in ordered[index:end]:
            accepted_weight += row.weight
            accepted_loss += row.weight * row.selective_loss
        coverage = accepted_weight / total_weight
        risk = accepted_loss / accepted_weight
        # Right-continuous blockwise integral.  Equal-confidence examples are
        # indivisible, so permutation within a tie cannot alter the result.
        area += (coverage - previous_coverage) * risk
        points.append(
            RiskCoveragePoint(
                minimum_acceptance_confidence_inclusive=confidence,
                coverage=coverage,
                selective_risk=risk,
            )
        )
        previous_coverage = coverage
        index = end
    return ScalarMetric.defined(area), previous_coverage, tuple(points)


@dataclass(frozen=True, slots=True)
class OODMetricSlice:
    cohort: str
    total_count: int
    total_weight: float
    known_count: int
    ood_count: int
    auroc: ScalarMetric
    auprc: ScalarMetric
    fpr_at_95_tpr: ScalarMetric
    tpr_at_frozen_low_fpr: ScalarMetric
    frozen_low_fpr: float
    risk_coverage_aurc: ScalarMetric
    risk_coverage_final_coverage: float
    risk_coverage_aurc_convention: str
    known_case_coverage: RateMetric
    ood_abstention_rate: RateMetric
    unknown_probability_brier: ScalarMetric
    unknown_probability_nll: ScalarMetric
    unknown_probability_nll_clip: float
    unknown_probability_nll_convention: str
    unsafe_nonabstain_rate: RateMetric
    nonabstain_ood_mean_regret: ScalarMetric
    nonabstain_ood_max_regret: ScalarMetric
    threshold_curve: tuple[OODThresholdPoint, ...]
    risk_coverage_curve: tuple[RiskCoveragePoint, ...]


def _ood_slice(
    cohort: str,
    rows: tuple[OODExample, ...],
    *,
    frozen_low_fpr: float,
    catastrophic_margin: float,
) -> OODMetricSlice:
    known = tuple(row for row in rows if not row.is_ood_runtime_truth)
    ood = tuple(row for row in rows if row.is_ood_runtime_truth)
    curve = _ood_threshold_curve(rows)
    fpr95 = next(
        (
            point.false_positive_rate
            for point in curve
            if point.true_positive_rate >= 0.95
        ),
        None,
    )
    eligible_low_fpr = tuple(
        point for point in curve if point.false_positive_rate <= frozen_low_fpr
    )
    tpr_low = max((point.true_positive_rate for point in eligible_low_fpr), default=0.0)
    aurc, final_coverage, risk_curve = _risk_coverage(rows)
    total_weight = math.fsum(row.weight for row in rows)
    brier = (
        ScalarMetric.undefined("empty_denominator")
        if not rows
        else ScalarMetric.defined(
            math.fsum(
                row.weight
                * (row.unknown_probability - (1.0 if row.is_ood_runtime_truth else 0.0))
                ** 2
                for row in rows
            )
            / total_weight
        )
    )
    clip = UNKNOWN_PROBABILITY_NLL_CLIP
    nll = (
        ScalarMetric.undefined("empty_denominator")
        if not rows
        else ScalarMetric.defined(
            math.fsum(
                row.weight
                * -math.log(
                    max(clip, min(1.0 - clip, row.unknown_probability))
                    if row.is_ood_runtime_truth
                    else max(clip, min(1.0 - clip, 1.0 - row.unknown_probability))
                )
                for row in rows
            )
            / total_weight
        )
    )
    nonabstain_ood = tuple(row for row in ood if not row.abstained)
    nonabstain_weight = math.fsum(row.weight for row in nonabstain_ood)
    mean_regret = (
        ScalarMetric.undefined("no_nonabstain_ood_exposure")
        if not nonabstain_ood
        else ScalarMetric.defined(
            math.fsum(
                row.weight * row.unsafe_treatment_regret for row in nonabstain_ood
            )
            / nonabstain_weight
        )
    )
    max_regret = (
        ScalarMetric.undefined("no_nonabstain_ood_exposure")
        if not nonabstain_ood
        else ScalarMetric.defined(
            max(row.unsafe_treatment_regret for row in nonabstain_ood)
        )
    )
    class_defined = bool(known and ood)
    return OODMetricSlice(
        cohort=cohort,
        total_count=len(rows),
        total_weight=total_weight,
        known_count=len(known),
        ood_count=len(ood),
        auroc=_weighted_auroc(rows),
        auprc=_weighted_auprc(rows),
        fpr_at_95_tpr=(
            ScalarMetric.defined(fpr95)
            if class_defined and fpr95 is not None
            else ScalarMetric.undefined("single_class_discrimination")
        ),
        tpr_at_frozen_low_fpr=(
            ScalarMetric.defined(tpr_low)
            if class_defined
            else ScalarMetric.undefined("single_class_discrimination")
        ),
        frozen_low_fpr=frozen_low_fpr,
        risk_coverage_aurc=aurc,
        risk_coverage_final_coverage=final_coverage,
        risk_coverage_aurc_convention=RISK_COVERAGE_AURC_CONVENTION,
        known_case_coverage=_rate(known, lambda row: not row.abstained),
        ood_abstention_rate=_rate(ood, lambda row: row.abstained),
        unknown_probability_brier=brier,
        unknown_probability_nll=nll,
        unknown_probability_nll_clip=UNKNOWN_PROBABILITY_NLL_CLIP,
        unknown_probability_nll_convention=UNKNOWN_PROBABILITY_NLL_CONVENTION,
        unsafe_nonabstain_rate=_rate(
            ood,
            lambda row: (
                not row.abstained and row.unsafe_treatment_regret >= catastrophic_margin
            ),
        ),
        nonabstain_ood_mean_regret=mean_regret,
        nonabstain_ood_max_regret=max_regret,
        threshold_curve=curve,
        risk_coverage_curve=risk_curve,
    )


@dataclass(frozen=True, slots=True)
class OODMetricReport:
    overall: OODMetricSlice
    cohorts: tuple[OODMetricSlice, ...]
    label_owner: str
    projection_owner: str


def ood_metrics(
    examples: Iterable[OODExample],
    *,
    frozen_low_fpr: float,
    catastrophic_margin: float,
) -> OODMetricReport:
    rows = _validated_unique_rows(examples, OODExample, "OOD example")
    low_fpr = _probability(frozen_low_fpr, "frozen_low_fpr")
    catastrophic = _real(catastrophic_margin, "catastrophic_margin", nonnegative=True)
    cohort_names = sorted({row.cohort for row in rows})
    return OODMetricReport(
        overall=_ood_slice(
            "__all__",
            rows,
            frozen_low_fpr=low_fpr,
            catastrophic_margin=catastrophic,
        ),
        cohorts=tuple(
            _ood_slice(
                cohort,
                tuple(row for row in rows if row.cohort == cohort),
                frozen_low_fpr=low_fpr,
                catastrophic_margin=catastrophic,
            )
            for cohort in cohort_names
        ),
        label_owner="runner_or_judge_runtime_truth",
        projection_owner=OOD_PROJECTION_OWNER,
    )


@dataclass(frozen=True, slots=True)
class TemporalLeakProbe:
    probe_id: str
    cohort: str
    weight: float
    prefix_bytes_a: bytes
    prefix_bytes_b: bytes
    state_hash_a: str
    state_hash_b: str
    prediction_bytes_a: bytes
    prediction_bytes_b: bytes
    preavailability_output_divergence: float
    boundary_expected_visible: bool | None = None
    boundary_observed_visible: bool | None = None
    old_cut_state_hash_before: str | None = None
    old_cut_state_hash_after: str | None = None
    old_cut_prediction_before: bytes | None = None
    old_cut_prediction_after: bytes | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "probe_id", _identifier(self.probe_id, "probe_id"))
        object.__setattr__(self, "cohort", _identifier(self.cohort, "cohort"))
        object.__setattr__(self, "weight", _weight(self.weight, "probe weight"))
        object.__setattr__(
            self, "prefix_bytes_a", _bytes(self.prefix_bytes_a, "prefix_bytes_a")
        )
        object.__setattr__(
            self, "prefix_bytes_b", _bytes(self.prefix_bytes_b, "prefix_bytes_b")
        )
        object.__setattr__(
            self, "state_hash_a", _identifier(self.state_hash_a, "state_hash_a")
        )
        object.__setattr__(
            self, "state_hash_b", _identifier(self.state_hash_b, "state_hash_b")
        )
        object.__setattr__(
            self,
            "prediction_bytes_a",
            _bytes(self.prediction_bytes_a, "prediction_bytes_a"),
        )
        object.__setattr__(
            self,
            "prediction_bytes_b",
            _bytes(self.prediction_bytes_b, "prediction_bytes_b"),
        )
        object.__setattr__(
            self,
            "preavailability_output_divergence",
            _real(
                self.preavailability_output_divergence,
                "preavailability_output_divergence",
                nonnegative=True,
            ),
        )
        boundary_values = (
            self.boundary_expected_visible,
            self.boundary_observed_visible,
        )
        if (boundary_values[0] is None) != (boundary_values[1] is None):
            raise ProtocolViolation("boundary expected/observed values must be paired")
        if boundary_values[0] is not None:
            _strict_bool(boundary_values[0], "boundary_expected_visible")
            _strict_bool(boundary_values[1], "boundary_observed_visible")
        old_values = (
            self.old_cut_state_hash_before,
            self.old_cut_state_hash_after,
            self.old_cut_prediction_before,
            self.old_cut_prediction_after,
        )
        provided = tuple(value is not None for value in old_values)
        if any(provided) and not all(provided):
            raise ProtocolViolation("old-cut before/after evidence must be complete")
        if all(provided):
            _identifier(old_values[0], "old_cut_state_hash_before")
            _identifier(old_values[1], "old_cut_state_hash_after")
            _bytes(old_values[2], "old_cut_prediction_before")
            _bytes(old_values[3], "old_cut_prediction_after")


@dataclass(frozen=True, slots=True)
class TemporalLeakMetricSlice:
    cohort: str
    identical_prefix_denominator: RateMetric
    state_leak_rate: RateMetric
    prediction_leak_rate: RateMetric
    max_preavailability_output_divergence: ScalarMetric
    boundary_exposure_count: int
    boundary_exposure_weight: float
    boundary_error_count: int
    boundary_error_weight: float
    old_cut_exposure_count: int
    old_cut_exposure_weight: float
    old_cut_instability_count: int
    old_cut_instability_weight: float


def _is_old_cut_exposure(row: TemporalLeakProbe) -> bool:
    return row.old_cut_state_hash_before is not None


def _old_cut_unstable(row: TemporalLeakProbe) -> bool:
    return _is_old_cut_exposure(row) and (
        row.old_cut_state_hash_before != row.old_cut_state_hash_after
        or row.old_cut_prediction_before != row.old_cut_prediction_after
    )


def _temporal_slice(
    cohort: str, rows: tuple[TemporalLeakProbe, ...]
) -> TemporalLeakMetricSlice:
    identical = tuple(row for row in rows if row.prefix_bytes_a == row.prefix_bytes_b)
    boundary = tuple(row for row in rows if row.boundary_expected_visible is not None)
    old_cut = tuple(row for row in rows if _is_old_cut_exposure(row))
    return TemporalLeakMetricSlice(
        cohort=cohort,
        identical_prefix_denominator=_rate(identical, lambda _row: True),
        state_leak_rate=_rate(
            identical, lambda row: row.state_hash_a != row.state_hash_b
        ),
        prediction_leak_rate=_rate(
            identical, lambda row: row.prediction_bytes_a != row.prediction_bytes_b
        ),
        max_preavailability_output_divergence=(
            ScalarMetric.undefined("empty_identical_prefix_denominator")
            if not identical
            else ScalarMetric.defined(
                max(row.preavailability_output_divergence for row in identical)
            )
        ),
        boundary_exposure_count=len(boundary),
        boundary_exposure_weight=math.fsum(row.weight for row in boundary),
        boundary_error_count=sum(
            row.boundary_expected_visible != row.boundary_observed_visible
            for row in boundary
        ),
        boundary_error_weight=math.fsum(
            row.weight
            for row in boundary
            if row.boundary_expected_visible != row.boundary_observed_visible
        ),
        old_cut_exposure_count=len(old_cut),
        old_cut_exposure_weight=math.fsum(row.weight for row in old_cut),
        old_cut_instability_count=sum(_old_cut_unstable(row) for row in old_cut),
        old_cut_instability_weight=math.fsum(
            row.weight for row in old_cut if _old_cut_unstable(row)
        ),
    )


@dataclass(frozen=True, slots=True)
class TemporalLeakMetricReport:
    overall: TemporalLeakMetricSlice
    cohorts: tuple[TemporalLeakMetricSlice, ...]


def temporal_leakage_metrics(
    probes: Iterable[TemporalLeakProbe],
) -> TemporalLeakMetricReport:
    rows = _validated_unique_rows(probes, TemporalLeakProbe, "temporal probe")
    cohort_names = sorted({row.cohort for row in rows})
    return TemporalLeakMetricReport(
        overall=_temporal_slice("__all__", rows),
        cohorts=tuple(
            _temporal_slice(cohort, tuple(row for row in rows if row.cohort == cohort))
            for cohort in cohort_names
        ),
    )


T = TypeVar("T")


def _validated_unique_rows(
    values: Iterable[T], expected_type: type[T], label: str
) -> tuple[T, ...]:
    try:
        rows = tuple(values)
    except TypeError as exc:
        raise ProtocolViolation(f"{label} collection must be iterable") from exc
    if any(type(row) is not expected_type for row in rows):
        raise ProtocolViolation(f"{label} collection contains wrong row type")
    id_attribute = (
        "pair_id"
        if expected_type is PairMetricProbe
        else ("example_id" if expected_type is OODExample else "probe_id")
    )
    identifiers = tuple(getattr(row, id_attribute) for row in rows)
    if len(set(identifiers)) != len(identifiers):
        raise ProtocolViolation(f"{label} identifiers must be unique")
    return rows
