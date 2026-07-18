"""Isolated PRE-FREEZE runtime for UCM metrics M03 and M04.

This module is deliberately not imported by the official evaluator and does not
issue or imply benchmark/freeze authority.  It closes executable formulas for a
continuous-Gaussian slice of M03 and for point/partially identified M04 cells so
that the formulas can be exercised before the semantic metric configuration is
frozen.  Utility is always maximized.  There is intentionally no aggregate or
weighted total score.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .canonical import ProtocolViolation


METRIC_RUNTIME_SCHEMA = "ucm-pre-freeze-m03-m04-runtime/1"
BENCHMARK_STATUS = "PRE-FREEZE"
ARTIFACT_ROLE = "runtime_only"
FREEZE_AUTHORITY = "not_claimed"
OFFICIAL_EVALUATOR_BINDING = "not_bound"
UTILITY_DIRECTION = "larger_is_better"


class UndefinedReason(str, Enum):
    NOT_PROVIDED = "not_provided"
    NO_UNIT_IDENTIFIED_EXPOSURE = "no_unit_identified_exposure"
    NO_SET_CLAIM_EXPOSURE = "no_set_claim_exposure"
    NO_CERTAINTY_CLAIM_EXPOSURE = "no_certainty_claim_exposure"
    ZERO_ORACLE_UTILITY_RANGE = "zero_oracle_utility_range"
    NO_W19_TAIL_EXPOSURE = "no_w19_tail_exposure"


class EffectIdentification(str, Enum):
    DISTRIBUTION = "distribution_identified"
    UNIT = "unit_identified"


class CoverageDisposition(str, Enum):
    POINT_SCORED = "point_scored"
    SET_SCORED = "set_scored"
    TYPED_ABSTENTION = "typed_abstention"
    UNSUPPORTED = "unsupported"
    INVALID = "invalid"
    MISSING = "missing"


class SetClaimKind(str, Enum):
    IDENTIFIED_SET = "identified_set"
    POINT = "point"
    HIGH_CONFIDENCE_INTERVAL = "high_confidence_interval"
    TYPED_ABSTENTION = "typed_abstention"


class RegretDisposition(str, Enum):
    POINT_IDENTIFIED_PRIMARY = "point_identified_primary"
    PARTIAL_IDENTIFICATION_ROBUST_PRIMARY = "partial_identification_robust_primary"


@dataclass(frozen=True, slots=True)
class NullableMetric:
    value: float | None
    exposure: int
    undefined_reason: UndefinedReason | None


@dataclass(frozen=True, slots=True)
class Interval:
    lower: float
    upper: float


@dataclass(frozen=True, slots=True)
class GaussianTrajectoryCase:
    case_id: str
    policy_id: str
    horizon_id: str
    predicted_mean: tuple[float, ...]
    predicted_std: tuple[float, ...]
    oracle_realization: tuple[float, ...]
    oracle_scale: tuple[float, ...]


@dataclass(frozen=True, slots=True)
class InterventionTrajectoryMetrics:
    case_count: int
    scalar_exposure: int
    gaussian_nll: float
    mean_absolute_error: float
    root_mean_squared_error: float
    oracle_scale_normalized_mae: float
    oracle_scale_normalized_rmse: float
    formula_scope: str = "continuous_gaussian_trajectory_slice"


@dataclass(frozen=True, slots=True)
class TreatmentEffectCase:
    case_id: str
    predicted_effect: float
    oracle_effect: float
    identification: EffectIdentification


@dataclass(frozen=True, slots=True)
class TreatmentEffectMetrics:
    count: int
    mean_absolute_effect_error: float
    root_mean_squared_effect_error: float
    effect_sign_error_count: int
    effect_sign_error_rate: float
    effect_sign_tolerance: float
    pehe: NullableMetric


@dataclass(frozen=True, slots=True)
class PolicyHorizonExposure:
    record_id: str
    world_slot: str
    case_id: str
    cut_id: str
    policy_id: str
    horizon_id: str
    disposition: CoverageDisposition


@dataclass(frozen=True, slots=True)
class PolicyHorizonCoverageMetrics:
    required_exposure: int
    responded_exposure: int
    scored_exposure: int
    point_scored_exposure: int
    set_scored_exposure: int
    typed_abstention_exposure: int
    unsupported_exposure: int
    invalid_exposure: int
    missing_exposure: int
    response_coverage: float
    scored_coverage: float
    rows: tuple[PolicyHorizonExposure, ...]


@dataclass(frozen=True, slots=True)
class IdentifiedSetCase:
    case_id: str
    oracle_effect_set: Interval
    claim_kind: SetClaimKind
    candidate_effect_set: Interval | None
    oracle_optimal_action_ids: tuple[str, ...] = ()
    candidate_optimal_action_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IdentifiedSetRow:
    case_id: str
    claim_kind: SetClaimKind
    candidate_width: float | None
    oracle_covered: bool | None
    hausdorff_error: float | None
    set_bound_error: float | None
    false_certainty: bool


@dataclass(frozen=True, slots=True)
class IdentifiedSetMetrics:
    required_exposure: int
    set_claim_exposure: int
    abstention_exposure: int
    set_claim_rate: float
    oracle_set_coverage: NullableMetric
    mean_candidate_set_width: NullableMetric
    mean_hausdorff_error: NullableMetric
    mean_set_bound_error: NullableMetric
    certainty_claim_exposure: int
    false_certainty_count: int
    false_certainty_rate: NullableMetric
    tolerance: float
    rows: tuple[IdentifiedSetRow, ...]


@dataclass(frozen=True, slots=True)
class RegretCase:
    case_id: str
    world_slot: str
    action_ids: tuple[str, ...]
    predicted_utilities: tuple[float, ...]
    oracle_utilities: tuple[float, ...]
    tie_break_action_ids: tuple[str, ...]
    optimal_action_tolerance: float
    catastrophic_margin: float
    catastrophic_action_ids: tuple[str, ...] = ()
    w19_tail_member: bool = False


@dataclass(frozen=True, slots=True)
class RegretRow:
    case_id: str
    world_slot: str
    selected_action_id: str
    candidate_optimal_action_ids: tuple[str, ...]
    oracle_optimal_action_ids: tuple[str, ...]
    raw_regret: float
    normalized_regret: float | None
    normalized_regret_undefined_reason: UndefinedReason | None
    catastrophic_action: bool
    w19_tail_member: bool


@dataclass(frozen=True, slots=True)
class DistributionSummary:
    exposure: int
    mean: float
    median: float
    p95: float
    maximum: float
    cvar95: float


@dataclass(frozen=True, slots=True)
class RegretCohortSummary:
    exposure: int
    raw: DistributionSummary
    normalized: DistributionSummary | None
    normalized_exposure: int
    normalized_undefined_exposure: int
    catastrophic_action_count: int
    catastrophic_action_rate: float


@dataclass(frozen=True, slots=True)
class PointRegretMetrics:
    disposition: RegretDisposition
    utility_direction: str
    full_population: RegretCohortSummary
    w19_tail: RegretCohortSummary | None
    w19_tail_undefined_reason: UndefinedReason | None
    rows: tuple[RegretRow, ...]


@dataclass(frozen=True, slots=True)
class PartialIdentificationCase:
    case_id: str
    world_slot: str
    action_ids: tuple[str, ...]
    candidate_utility_sets: tuple[Interval, ...]
    compatible_oracle_utilities: tuple[tuple[float, ...], ...]
    tie_break_action_ids: tuple[str, ...]
    optimal_action_tolerance: float
    catastrophic_margin: float
    catastrophic_action_ids: tuple[str, ...] = ()
    claim_kind: SetClaimKind = SetClaimKind.IDENTIFIED_SET
    descriptive_realized_oracle_utilities: tuple[float, ...] | None = None
    w19_tail_member: bool = False


@dataclass(frozen=True, slots=True)
class PartialIdentificationRow:
    case_id: str
    world_slot: str
    selected_action_id: str
    oracle_set_valued_optimal_action_ids: tuple[str, ...]
    uniformly_dominated_action_ids: tuple[str, ...]
    robust_regret_by_action: tuple[tuple[str, float], ...]
    selected_oracle_robust_regret_interval: Interval
    selected_oracle_robust_regret_bound: float
    all_compatible_catastrophic: bool
    false_certainty: bool
    descriptive_realization_regret: float | None
    point_regret_primary: None = None
    w19_tail_member: bool = False


@dataclass(frozen=True, slots=True)
class PartialIdentificationMetrics:
    disposition: RegretDisposition
    utility_direction: str
    exposure: int
    robust_regret_bound_summary: DistributionSummary
    all_compatible_catastrophic_count: int
    all_compatible_catastrophic_rate: float
    false_certainty_exposure: int
    false_certainty_count: int
    false_certainty_rate: NullableMetric
    w19_tail_robust_regret_bound_summary: DistributionSummary | None
    w19_tail_undefined_reason: UndefinedReason | None
    rows: tuple[PartialIdentificationRow, ...]


def runtime_status() -> dict[str, object]:
    """Return the non-authoritative status without a digest/authority claim."""

    return {
        "schema": METRIC_RUNTIME_SCHEMA,
        "benchmark_status": BENCHMARK_STATUS,
        "artifact_role": ARTIFACT_ROLE,
        "freeze_authority": FREEZE_AUTHORITY,
        "official_evaluator_binding": OFFICIAL_EVALUATOR_BINDING,
        "utility_direction": UTILITY_DIRECTION,
        "single_aggregate_score": "forbidden",
    }


def _identifier(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise ProtocolViolation(f"{label} must be a non-empty exact string")
    return value


def _number(value: object, label: str) -> float:
    if type(value) not in {int, float}:
        raise ProtocolViolation(f"{label} must be an exact finite number")
    try:
        result = float(value)
    except (OverflowError, ValueError) as exc:
        raise ProtocolViolation(f"{label} must be an exact finite number") from exc
    if not math.isfinite(result):
        raise ProtocolViolation(f"{label} must be an exact finite number")
    return result


def _derived(value: float, label: str) -> float:
    if not math.isfinite(value):
        raise ProtocolViolation(f"{label} became non-finite")
    return value


def _difference(left: float, right: float, label: str) -> float:
    return _derived(left - right, label)


def _product(left: float, right: float, label: str) -> float:
    return _derived(left * right, label)


def _quotient(numerator: float, denominator: float, label: str) -> float:
    try:
        result = numerator / denominator
    except (OverflowError, ZeroDivisionError) as exc:
        raise ProtocolViolation(f"{label} became non-finite") from exc
    return _derived(result, label)


def _finite_sum(values: Iterable[float], label: str) -> float:
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError) as exc:
        raise ProtocolViolation(f"{label} became non-finite") from exc
    return _derived(result, label)


def _mean(values: list[float] | tuple[float, ...], label: str) -> float:
    if not values:
        raise ProtocolViolation(f"{label} requires non-empty values")
    return _quotient(_finite_sum(values, label), len(values), label)


def _nonnegative(value: object, label: str) -> float:
    result = _number(value, label)
    if result < 0.0:
        raise ProtocolViolation(f"{label} must be non-negative")
    return result


def _positive(value: object, label: str) -> float:
    result = _number(value, label)
    if result <= 0.0:
        raise ProtocolViolation(f"{label} must be positive")
    return result


def _tuple_numbers(value: object, label: str) -> tuple[float, ...]:
    if type(value) is not tuple or not value:
        raise ProtocolViolation(f"{label} must be a non-empty exact tuple")
    return tuple(_number(item, f"{label}[{index}]") for index, item in enumerate(value))


def _tuple_identifiers(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple or not value:
        raise ProtocolViolation(f"{label} must be a non-empty exact tuple")
    result = tuple(
        _identifier(item, f"{label}[{index}]") for index, item in enumerate(value)
    )
    if len(set(result)) != len(result):
        raise ProtocolViolation(f"{label} contains duplicate identifiers")
    return result


def _interval(value: object, label: str) -> Interval:
    if type(value) is not Interval:
        raise ProtocolViolation(f"{label} must be an exact Interval")
    lower = _number(value.lower, f"{label}.lower")
    upper = _number(value.upper, f"{label}.upper")
    if lower > upper:
        raise ProtocolViolation(f"{label} bounds are reversed")
    return Interval(lower, upper)


def _exact_enum(value: object, expected: type[Enum], label: str) -> Enum:
    if type(value) is not expected:
        raise ProtocolViolation(f"{label} must be an exact {expected.__name__}")
    return value


def _nullable(
    value: float | None, exposure: int, reason: UndefinedReason
) -> NullableMetric:
    if value is None:
        return NullableMetric(None, exposure, reason)
    return NullableMetric(value, exposure, None)


def intervention_trajectory_metrics(
    cases: tuple[GaussianTrajectoryCase, ...],
) -> InterventionTrajectoryMetrics:
    """Score continuous Gaussian intervention trajectories at scalar-cell grain.

    Gaussian NLL is the proper score.  Raw and oracle-scale-normalized point
    errors are descriptive companion metrics.  Every policy/horizon exposure is
    retained by the typed input; coverage itself is computed separately.
    """

    if type(cases) is not tuple or not cases:
        raise ProtocolViolation("trajectory cases must be a non-empty exact tuple")
    absolute: list[float] = []
    squared: list[float] = []
    normalized_absolute: list[float] = []
    normalized_squared: list[float] = []
    nll: list[float] = []
    case_ids: set[str] = set()
    for case_index, case in enumerate(cases):
        if type(case) is not GaussianTrajectoryCase:
            raise ProtocolViolation("trajectory cases contain a non-exact case")
        case_id = _identifier(case.case_id, f"cases[{case_index}].case_id")
        if case_id in case_ids:
            raise ProtocolViolation("trajectory case_id values must be unique")
        case_ids.add(case_id)
        _identifier(case.policy_id, f"cases[{case_index}].policy_id")
        _identifier(case.horizon_id, f"cases[{case_index}].horizon_id")
        mean = _tuple_numbers(case.predicted_mean, "predicted_mean")
        std = _tuple_numbers(case.predicted_std, "predicted_std")
        truth = _tuple_numbers(case.oracle_realization, "oracle_realization")
        scale = _tuple_numbers(case.oracle_scale, "oracle_scale")
        if not (len(mean) == len(std) == len(truth) == len(scale)):
            raise ProtocolViolation("trajectory vectors must have identical lengths")
        for index, (prediction, sigma, observed, normalization) in enumerate(
            zip(mean, std, truth, scale, strict=True)
        ):
            _positive(sigma, f"predicted_std[{index}]")
            _positive(normalization, f"oracle_scale[{index}]")
            error = _difference(prediction, observed, "trajectory error")
            absolute.append(abs(error))
            squared.append(_product(error, error, "squared trajectory error"))
            normalized = _quotient(error, normalization, "normalized trajectory error")
            normalized_absolute.append(abs(normalized))
            normalized_squared.append(
                _product(normalized, normalized, "squared normalized trajectory error")
            )
            variance = _positive(
                _product(sigma, sigma, "predicted variance"), "predicted variance"
            )
            log_argument = _product(
                2.0 * math.pi, variance, "Gaussian NLL log argument"
            )
            _positive(log_argument, "Gaussian NLL log argument")
            quadratic = _quotient(squared[-1], variance, "Gaussian NLL quadratic term")
            nll.append(
                _derived(
                    0.5 * math.log(log_argument) + 0.5 * quadratic,
                    "Gaussian NLL",
                )
            )
    return InterventionTrajectoryMetrics(
        case_count=len(cases),
        scalar_exposure=len(absolute),
        gaussian_nll=_mean(nll, "mean Gaussian NLL"),
        mean_absolute_error=_mean(absolute, "mean absolute trajectory error"),
        root_mean_squared_error=_derived(
            math.sqrt(_mean(squared, "mean squared trajectory error")),
            "root mean squared trajectory error",
        ),
        oracle_scale_normalized_mae=_mean(
            normalized_absolute, "mean normalized absolute trajectory error"
        ),
        oracle_scale_normalized_rmse=_derived(
            math.sqrt(
                _mean(normalized_squared, "mean squared normalized trajectory error")
            ),
            "normalized root mean squared trajectory error",
        ),
    )


def _effect_sign(value: float, tolerance: float) -> int:
    if value > tolerance:
        return 1
    if value < -tolerance:
        return -1
    return 0


def treatment_effect_metrics(
    cases: tuple[TreatmentEffectCase, ...],
    *,
    effect_sign_tolerance: float,
) -> TreatmentEffectMetrics:
    if type(cases) is not tuple or not cases:
        raise ProtocolViolation("effect cases must be a non-empty exact tuple")
    tolerance = _nonnegative(effect_sign_tolerance, "effect_sign_tolerance")
    errors: list[float] = []
    unit_errors: list[float] = []
    sign_errors = 0
    case_ids: set[str] = set()
    for index, case in enumerate(cases):
        if type(case) is not TreatmentEffectCase:
            raise ProtocolViolation("effect cases contain a non-exact case")
        case_id = _identifier(case.case_id, f"cases[{index}].case_id")
        if case_id in case_ids:
            raise ProtocolViolation("effect case_id values must be unique")
        case_ids.add(case_id)
        predicted = _number(case.predicted_effect, "predicted_effect")
        oracle = _number(case.oracle_effect, "oracle_effect")
        identification = _exact_enum(
            case.identification, EffectIdentification, "identification"
        )
        error = _difference(predicted, oracle, "treatment effect error")
        errors.append(error)
        if _effect_sign(predicted, tolerance) != _effect_sign(oracle, tolerance):
            sign_errors += 1
        if identification is EffectIdentification.UNIT:
            unit_errors.append(error)
    pehe_value = (
        _derived(
            math.sqrt(
                _mean(
                    [
                        _product(value, value, "squared unit treatment effect error")
                        for value in unit_errors
                    ],
                    "mean squared unit treatment effect error",
                )
            ),
            "PEHE",
        )
        if unit_errors
        else None
    )
    return TreatmentEffectMetrics(
        count=len(errors),
        mean_absolute_effect_error=_mean(
            [abs(value) for value in errors], "mean absolute treatment effect error"
        ),
        root_mean_squared_effect_error=_derived(
            math.sqrt(
                _mean(
                    [
                        _product(value, value, "squared treatment effect error")
                        for value in errors
                    ],
                    "mean squared treatment effect error",
                )
            ),
            "root mean squared treatment effect error",
        ),
        effect_sign_error_count=sign_errors,
        effect_sign_error_rate=sign_errors / len(errors),
        effect_sign_tolerance=tolerance,
        pehe=_nullable(
            pehe_value,
            len(unit_errors),
            UndefinedReason.NO_UNIT_IDENTIFIED_EXPOSURE,
        ),
    )


def policy_horizon_coverage(
    rows: tuple[PolicyHorizonExposure, ...],
) -> PolicyHorizonCoverageMetrics:
    if type(rows) is not tuple or not rows:
        raise ProtocolViolation("coverage rows must be a non-empty exact tuple")
    seen_records: set[str] = set()
    seen_cells: set[tuple[str, str, str, str, str]] = set()
    counts = {item: 0 for item in CoverageDisposition}
    validated: list[PolicyHorizonExposure] = []
    for index, row in enumerate(rows):
        if type(row) is not PolicyHorizonExposure:
            raise ProtocolViolation("coverage rows contain a non-exact row")
        record = _identifier(row.record_id, f"rows[{index}].record_id")
        world = _identifier(row.world_slot, f"rows[{index}].world_slot")
        case_id = _identifier(row.case_id, f"rows[{index}].case_id")
        cut = _identifier(row.cut_id, f"rows[{index}].cut_id")
        policy = _identifier(row.policy_id, f"rows[{index}].policy_id")
        horizon = _identifier(row.horizon_id, f"rows[{index}].horizon_id")
        disposition = _exact_enum(
            row.disposition, CoverageDisposition, "coverage disposition"
        )
        key = (world, case_id, cut, policy, horizon)
        if record in seen_records:
            raise ProtocolViolation("coverage record_id values must be unique")
        if key in seen_cells:
            raise ProtocolViolation("required coverage cells must be unique")
        seen_records.add(record)
        seen_cells.add(key)
        counts[disposition] += 1
        validated.append(row)
    required = len(validated)
    responded = required - counts[CoverageDisposition.MISSING]
    scored = (
        counts[CoverageDisposition.POINT_SCORED]
        + counts[CoverageDisposition.SET_SCORED]
    )
    return PolicyHorizonCoverageMetrics(
        required_exposure=required,
        responded_exposure=responded,
        scored_exposure=scored,
        point_scored_exposure=counts[CoverageDisposition.POINT_SCORED],
        set_scored_exposure=counts[CoverageDisposition.SET_SCORED],
        typed_abstention_exposure=counts[CoverageDisposition.TYPED_ABSTENTION],
        unsupported_exposure=counts[CoverageDisposition.UNSUPPORTED],
        invalid_exposure=counts[CoverageDisposition.INVALID],
        missing_exposure=counts[CoverageDisposition.MISSING],
        response_coverage=responded / required,
        scored_coverage=scored / required,
        rows=tuple(validated),
    )


def identified_set_metrics(
    cases: tuple[IdentifiedSetCase, ...],
    *,
    tolerance: float,
) -> IdentifiedSetMetrics:
    if type(cases) is not tuple or not cases:
        raise ProtocolViolation("identified-set cases must be a non-empty exact tuple")
    tol = _nonnegative(tolerance, "tolerance")
    widths: list[float] = []
    coverage: list[bool] = []
    hausdorff: list[float] = []
    bound_errors: list[float] = []
    rows: list[IdentifiedSetRow] = []
    certainty_claims = 0
    false_certainty_count = 0
    abstentions = 0
    case_ids: set[str] = set()
    for index, case in enumerate(cases):
        if type(case) is not IdentifiedSetCase:
            raise ProtocolViolation("identified-set cases contain a non-exact case")
        case_id = _identifier(case.case_id, f"cases[{index}].case_id")
        if case_id in case_ids:
            raise ProtocolViolation("identified-set case_id values must be unique")
        case_ids.add(case_id)
        oracle = _interval(case.oracle_effect_set, "oracle_effect_set")
        kind = _exact_enum(case.claim_kind, SetClaimKind, "claim_kind")
        oracle_actions = _optional_action_set(
            case.oracle_optimal_action_ids, "oracle_optimal_action_ids"
        )
        candidate_actions = _optional_action_set(
            case.candidate_optimal_action_ids, "candidate_optimal_action_ids"
        )
        if kind is SetClaimKind.TYPED_ABSTENTION:
            if case.candidate_effect_set is not None or candidate_actions:
                raise ProtocolViolation(
                    "typed abstention cannot carry an effect set or action claim"
                )
            abstentions += 1
            rows.append(IdentifiedSetRow(case_id, kind, None, None, None, None, False))
            continue
        candidate = _interval(case.candidate_effect_set, "candidate_effect_set")
        if kind is SetClaimKind.POINT and candidate.lower != candidate.upper:
            raise ProtocolViolation("point claim must have zero-width effect set")
        width = _difference(candidate.upper, candidate.lower, "candidate set width")
        excess_lower_bound = _difference(
            candidate.lower, oracle.lower, "candidate lower-bound excess"
        )
        missing_upper_bound = _difference(
            oracle.upper, candidate.upper, "candidate upper-bound shortfall"
        )
        covered = excess_lower_bound <= tol and missing_upper_bound <= tol
        lower_bound_error = abs(
            _difference(candidate.lower, oracle.lower, "lower set-bound error")
        )
        upper_bound_error = abs(
            _difference(candidate.upper, oracle.upper, "upper set-bound error")
        )
        distance = max(
            lower_bound_error,
            upper_bound_error,
        )
        bound_error = _product(
            0.5,
            _finite_sum(
                (lower_bound_error, upper_bound_error), "total set-bound error"
            ),
            "mean set-bound error",
        )
        widths.append(width)
        coverage.append(covered)
        hausdorff.append(distance)
        bound_errors.append(bound_error)
        certainty = kind in {
            SetClaimKind.POINT,
            SetClaimKind.HIGH_CONFIDENCE_INTERVAL,
        }
        false_certainty = False
        if certainty:
            certainty_claims += 1
            # Crossing zero is not itself false certainty.  A high-confidence
            # interval may honestly cross zero and cover every compatible
            # value.  It is false certainty only when the claim excludes an
            # oracle-compatible effect/sign or an explicitly claimed action
            # set is too narrow.
            oracle_wider = excess_lower_bound > tol or missing_upper_bound > tol
            action_overclaim = bool(candidate_actions) and not set(
                oracle_actions
            ).issubset(candidate_actions)
            false_certainty = oracle_wider or action_overclaim
            false_certainty_count += int(false_certainty)
        rows.append(
            IdentifiedSetRow(
                case_id,
                kind,
                width,
                covered,
                distance,
                bound_error,
                false_certainty,
            )
        )
    set_exposure = len(widths)
    required = len(cases)
    return IdentifiedSetMetrics(
        required_exposure=required,
        set_claim_exposure=set_exposure,
        abstention_exposure=abstentions,
        set_claim_rate=set_exposure / required,
        oracle_set_coverage=_nullable(
            _quotient(sum(coverage), set_exposure, "oracle set coverage")
            if set_exposure
            else None,
            set_exposure,
            UndefinedReason.NO_SET_CLAIM_EXPOSURE,
        ),
        mean_candidate_set_width=_nullable(
            _mean(widths, "mean candidate set width") if set_exposure else None,
            set_exposure,
            UndefinedReason.NO_SET_CLAIM_EXPOSURE,
        ),
        mean_hausdorff_error=_nullable(
            _mean(hausdorff, "mean set Hausdorff error") if set_exposure else None,
            set_exposure,
            UndefinedReason.NO_SET_CLAIM_EXPOSURE,
        ),
        mean_set_bound_error=_nullable(
            _mean(bound_errors, "mean set-bound error") if set_exposure else None,
            set_exposure,
            UndefinedReason.NO_SET_CLAIM_EXPOSURE,
        ),
        certainty_claim_exposure=certainty_claims,
        false_certainty_count=false_certainty_count,
        false_certainty_rate=_nullable(
            false_certainty_count / certainty_claims if certainty_claims else None,
            certainty_claims,
            UndefinedReason.NO_CERTAINTY_CLAIM_EXPOSURE,
        ),
        tolerance=tol,
        rows=tuple(rows),
    )


def _optional_action_set(value: object, label: str) -> tuple[str, ...]:
    if type(value) is not tuple:
        raise ProtocolViolation(f"{label} must be an exact tuple")
    if not value:
        return ()
    return _tuple_identifiers(value, label)


def _action_inputs(
    action_ids: object,
    tie_break_action_ids: object,
    vectors: Iterable[tuple[object, str]],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[tuple[float, ...], ...]]:
    actions = _tuple_identifiers(action_ids, "action_ids")
    tie_break = _tuple_identifiers(tie_break_action_ids, "tie_break_action_ids")
    if len(actions) < 2:
        raise ProtocolViolation("at least two actions are required")
    if set(actions) != set(tie_break) or len(actions) != len(tie_break):
        raise ProtocolViolation("tie-break actions must be an exact action permutation")
    converted = tuple(_tuple_numbers(value, label) for value, label in vectors)
    if any(len(vector) != len(actions) for vector in converted):
        raise ProtocolViolation("utility vectors must align with action_ids")
    return actions, tie_break, converted


def _optimal_actions(
    action_ids: tuple[str, ...], values: tuple[float, ...], tolerance: float
) -> tuple[str, ...]:
    best = max(values)
    return tuple(
        action
        for action, value in zip(action_ids, values, strict=True)
        if _difference(best, value, "optimal-action utility gap") <= tolerance
    )


def _tie_select(options: tuple[str, ...], tie_break: tuple[str, ...]) -> str:
    allowed = set(options)
    for action in tie_break:
        if action in allowed:
            return action
    raise ProtocolViolation("tie-break rule contains no eligible action")


def _percentile_type7(values: tuple[float, ...], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    fraction = position - lower
    gap = _difference(ordered[upper], ordered[lower], "percentile interpolation gap")
    interpolation = _product(fraction, gap, "percentile interpolation")
    return _derived(ordered[lower] + interpolation, "percentile")


def _upper_cvar(values: tuple[float, ...], tail_probability: float = 0.05) -> float:
    ordered = sorted(values, reverse=True)
    mass_per_row = 1.0 / len(ordered)
    remaining = tail_probability
    weighted = 0.0
    for value in ordered:
        mass = min(mass_per_row, remaining)
        contribution = _product(mass, value, "CVaR contribution")
        weighted = _derived(weighted + contribution, "CVaR weighted sum")
        remaining -= mass
        if remaining <= 1e-15:
            break
    return _quotient(weighted, tail_probability, "CVaR95")


def _summary(values: tuple[float, ...]) -> DistributionSummary:
    if not values:
        raise ProtocolViolation("distribution summary requires non-empty values")
    return DistributionSummary(
        exposure=len(values),
        mean=_mean(values, "distribution mean"),
        median=_percentile_type7(values, 0.5),
        p95=_percentile_type7(values, 0.95),
        maximum=max(values),
        cvar95=_upper_cvar(values),
    )


def _cohort_summary(rows: tuple[RegretRow, ...]) -> RegretCohortSummary:
    raw = tuple(row.raw_regret for row in rows)
    normalized = tuple(
        row.normalized_regret for row in rows if row.normalized_regret is not None
    )
    catastrophic = sum(row.catastrophic_action for row in rows)
    return RegretCohortSummary(
        exposure=len(rows),
        raw=_summary(raw),
        normalized=_summary(normalized) if normalized else None,
        normalized_exposure=len(normalized),
        normalized_undefined_exposure=len(rows) - len(normalized),
        catastrophic_action_count=catastrophic,
        catastrophic_action_rate=catastrophic / len(rows),
    )


def point_identified_regret(
    cases: tuple[RegretCase, ...],
) -> PointRegretMetrics:
    """Compute point-identified regret with frozen tolerance and tie ordering."""

    if type(cases) is not tuple or not cases:
        raise ProtocolViolation("regret cases must be a non-empty exact tuple")
    rows: list[RegretRow] = []
    case_ids: set[str] = set()
    for index, case in enumerate(cases):
        if type(case) is not RegretCase:
            raise ProtocolViolation("regret cases contain a non-exact case")
        case_id = _identifier(case.case_id, f"cases[{index}].case_id")
        if case_id in case_ids:
            raise ProtocolViolation("regret case_id values must be unique")
        case_ids.add(case_id)
        world_slot = _identifier(case.world_slot, f"cases[{index}].world_slot")
        actions, tie_break, vectors = _action_inputs(
            case.action_ids,
            case.tie_break_action_ids,
            (
                (case.predicted_utilities, "predicted_utilities"),
                (case.oracle_utilities, "oracle_utilities"),
            ),
        )
        predicted, oracle = vectors
        tolerance = _nonnegative(
            case.optimal_action_tolerance, "optimal_action_tolerance"
        )
        catastrophic_margin = _positive(case.catastrophic_margin, "catastrophic_margin")
        catastrophic_actions = _optional_action_set(
            case.catastrophic_action_ids, "catastrophic_action_ids"
        )
        if not set(catastrophic_actions).issubset(actions):
            raise ProtocolViolation("catastrophic actions must be declared actions")
        if type(case.w19_tail_member) is not bool:
            raise ProtocolViolation("w19_tail_member must be an exact bool")
        if case.w19_tail_member and world_slot != "W19":
            raise ProtocolViolation("only W19 rows may be tail-cohort members")
        candidate_optimal = _optimal_actions(actions, predicted, tolerance)
        selected = _tie_select(candidate_optimal, tie_break)
        oracle_optimal = _optimal_actions(actions, oracle, tolerance)
        selected_index = actions.index(selected)
        raw = max(
            _difference(max(oracle), oracle[selected_index], "raw treatment regret"),
            0.0,
        )
        utility_range = _difference(max(oracle), min(oracle), "oracle utility range")
        normalized = (
            _quotient(raw, utility_range, "normalized treatment regret")
            if utility_range != 0.0
            else None
        )
        catastrophic = selected in catastrophic_actions and raw >= catastrophic_margin
        rows.append(
            RegretRow(
                case_id=case_id,
                world_slot=world_slot,
                selected_action_id=selected,
                candidate_optimal_action_ids=candidate_optimal,
                oracle_optimal_action_ids=oracle_optimal,
                raw_regret=raw,
                normalized_regret=normalized,
                normalized_regret_undefined_reason=(
                    None
                    if normalized is not None
                    else UndefinedReason.ZERO_ORACLE_UTILITY_RANGE
                ),
                catastrophic_action=catastrophic,
                w19_tail_member=case.w19_tail_member,
            )
        )
    exact_rows = tuple(rows)
    tail = tuple(row for row in exact_rows if row.w19_tail_member)
    return PointRegretMetrics(
        disposition=RegretDisposition.POINT_IDENTIFIED_PRIMARY,
        utility_direction=UTILITY_DIRECTION,
        full_population=_cohort_summary(exact_rows),
        w19_tail=_cohort_summary(tail) if tail else None,
        w19_tail_undefined_reason=(
            None if tail else UndefinedReason.NO_W19_TAIL_EXPOSURE
        ),
        rows=exact_rows,
    )


def _matrix(
    value: object, label: str, expected_columns: int
) -> tuple[tuple[float, ...], ...]:
    if type(value) is not tuple or not value:
        raise ProtocolViolation(f"{label} must be a non-empty exact tuple")
    result = tuple(
        _tuple_numbers(row, f"{label}[{index}]") for index, row in enumerate(value)
    )
    if any(len(row) != expected_columns for row in result):
        raise ProtocolViolation(f"{label} rows must align with action_ids")
    return result


def _uniformly_dominated(
    actions: tuple[str, ...],
    models: tuple[tuple[float, ...], ...],
    tolerance: float,
) -> tuple[str, ...]:
    dominated: list[str] = []
    for action_index, action in enumerate(actions):
        for competitor_index in range(len(actions)):
            if competitor_index == action_index:
                continue
            differences = tuple(
                _difference(
                    row[competitor_index],
                    row[action_index],
                    "uniform-dominance utility gap",
                )
                for row in models
            )
            if all(value >= -tolerance for value in differences) and any(
                value > tolerance for value in differences
            ):
                dominated.append(action)
                break
    return tuple(dominated)


def partial_identification_regret(
    cases: tuple[PartialIdentificationCase, ...],
) -> PartialIdentificationMetrics:
    """Compute robust M04 metrics without converting partial ID to a point.

    Candidate interval utilities are used only for the frozen interval-minimax
    choice.  Primary regret is evaluated over every compatible oracle model.
    An optional realized private model contributes a descriptive value only.
    """

    if type(cases) is not tuple or not cases:
        raise ProtocolViolation("partial-ID cases must be a non-empty exact tuple")
    rows: list[PartialIdentificationRow] = []
    case_ids: set[str] = set()
    for index, case in enumerate(cases):
        if type(case) is not PartialIdentificationCase:
            raise ProtocolViolation("partial-ID cases contain a non-exact case")
        case_id = _identifier(case.case_id, f"cases[{index}].case_id")
        if case_id in case_ids:
            raise ProtocolViolation("partial-ID case_id values must be unique")
        case_ids.add(case_id)
        world_slot = _identifier(case.world_slot, f"cases[{index}].world_slot")
        actions = _tuple_identifiers(case.action_ids, "action_ids")
        tie_break = _tuple_identifiers(
            case.tie_break_action_ids, "tie_break_action_ids"
        )
        if len(actions) < 2:
            raise ProtocolViolation("at least two actions are required")
        if set(actions) != set(tie_break) or len(actions) != len(tie_break):
            raise ProtocolViolation(
                "tie-break actions must be an exact action permutation"
            )
        if type(case.candidate_utility_sets) is not tuple or len(
            case.candidate_utility_sets
        ) != len(actions):
            raise ProtocolViolation("candidate utility sets must align with actions")
        candidate_sets = tuple(
            _interval(value, f"candidate_utility_sets[{set_index}]")
            for set_index, value in enumerate(case.candidate_utility_sets)
        )
        models = _matrix(
            case.compatible_oracle_utilities,
            "compatible_oracle_utilities",
            len(actions),
        )
        if len(models) < 2:
            raise ProtocolViolation(
                "partial identification requires at least two models"
            )
        tolerance = _nonnegative(
            case.optimal_action_tolerance, "optimal_action_tolerance"
        )
        catastrophic_margin = _positive(case.catastrophic_margin, "catastrophic_margin")
        catastrophic_actions = _optional_action_set(
            case.catastrophic_action_ids, "catastrophic_action_ids"
        )
        if not set(catastrophic_actions).issubset(actions):
            raise ProtocolViolation("catastrophic actions must be declared actions")
        claim_kind = _exact_enum(case.claim_kind, SetClaimKind, "claim_kind")
        if claim_kind is SetClaimKind.TYPED_ABSTENTION:
            raise ProtocolViolation(
                "partial regret selection requires utility sets; abstention belongs in coverage"
            )
        if claim_kind is SetClaimKind.POINT and any(
            item.lower != item.upper for item in candidate_sets
        ):
            raise ProtocolViolation("point utility claim must use zero-width sets")
        if type(case.w19_tail_member) is not bool:
            raise ProtocolViolation("w19_tail_member must be an exact bool")
        if case.w19_tail_member and world_slot != "W19":
            raise ProtocolViolation("only W19 rows may be tail-cohort members")

        # The interval-only minimax envelope treats different action intervals
        # as a Cartesian utility set.  The selected action itself contributes
        # zero regret, not its own interval width.
        candidate_regret_upper = tuple(
            max(
                0.0,
                max(
                    _difference(
                        competitor.upper,
                        candidate_sets[action_index].lower,
                        "candidate robust-regret upper bound",
                    )
                    for competitor_index, competitor in enumerate(candidate_sets)
                    if competitor_index != action_index
                ),
            )
            for action_index in range(len(candidate_sets))
        )
        minimum_candidate_bound = min(candidate_regret_upper)
        candidate_options = tuple(
            action
            for action, bound in zip(actions, candidate_regret_upper, strict=True)
            if _difference(
                bound, minimum_candidate_bound, "candidate minimax-regret tie gap"
            )
            <= tolerance
        )
        selected = _tie_select(candidate_options, tie_break)
        selected_index = actions.index(selected)

        model_regrets = tuple(
            tuple(
                _difference(
                    max(row), row[action_index], "compatible-model treatment regret"
                )
                for action_index in range(len(actions))
            )
            for row in models
        )
        robust_by_action = tuple(
            max(row[action_index] for row in model_regrets)
            for action_index in range(len(actions))
        )
        selected_regrets = tuple(row[selected_index] for row in model_regrets)
        oracle_optimal_union = tuple(
            action
            for action_index, action in enumerate(actions)
            if any(
                _difference(
                    max(model),
                    model[action_index],
                    "compatible-model optimal-action gap",
                )
                <= tolerance
                for model in models
            )
        )
        dominated = _uniformly_dominated(actions, models, tolerance)
        all_catastrophic = selected in catastrophic_actions and all(
            value >= catastrophic_margin for value in selected_regrets
        )
        oracle_sets = tuple(
            Interval(
                min(model[action_index] for model in models),
                max(model[action_index] for model in models),
            )
            for action_index in range(len(actions))
        )
        false_certainty = claim_kind in {
            SetClaimKind.POINT,
            SetClaimKind.HIGH_CONFIDENCE_INTERVAL,
        } and (
            not set(oracle_optimal_union).issubset(
                action
                for action_index, action in enumerate(actions)
                if all(
                    _difference(
                        competitor.lower,
                        candidate_sets[action_index].upper,
                        "candidate possible-optimum gap",
                    )
                    <= tolerance
                    for competitor_index, competitor in enumerate(candidate_sets)
                    if competitor_index != action_index
                )
            )
            or any(
                _difference(
                    candidate.lower,
                    oracle.lower,
                    "candidate utility-set lower exclusion",
                )
                > tolerance
                or _difference(
                    oracle.upper,
                    candidate.upper,
                    "candidate utility-set upper exclusion",
                )
                > tolerance
                for candidate, oracle in zip(candidate_sets, oracle_sets, strict=True)
            )
        )
        descriptive: float | None = None
        if case.descriptive_realized_oracle_utilities is not None:
            realized = _tuple_numbers(
                case.descriptive_realized_oracle_utilities,
                "descriptive_realized_oracle_utilities",
            )
            if len(realized) != len(actions):
                raise ProtocolViolation(
                    "descriptive realized utilities must align with actions"
                )
            descriptive = _difference(
                max(realized),
                realized[selected_index],
                "descriptive realization regret",
            )
        rows.append(
            PartialIdentificationRow(
                case_id=case_id,
                world_slot=world_slot,
                selected_action_id=selected,
                oracle_set_valued_optimal_action_ids=oracle_optimal_union,
                uniformly_dominated_action_ids=dominated,
                robust_regret_by_action=tuple(
                    zip(actions, robust_by_action, strict=True)
                ),
                selected_oracle_robust_regret_interval=Interval(
                    min(selected_regrets), max(selected_regrets)
                ),
                selected_oracle_robust_regret_bound=max(selected_regrets),
                all_compatible_catastrophic=all_catastrophic,
                false_certainty=false_certainty,
                descriptive_realization_regret=descriptive,
                w19_tail_member=case.w19_tail_member,
            )
        )
    exact_rows = tuple(rows)
    robust_bounds = tuple(row.selected_oracle_robust_regret_bound for row in exact_rows)
    tail_bounds = tuple(
        row.selected_oracle_robust_regret_bound
        for row in exact_rows
        if row.w19_tail_member
    )
    catastrophic_count = sum(row.all_compatible_catastrophic for row in exact_rows)
    false_certainty_count = sum(row.false_certainty for row in exact_rows)
    certainty_claim_exposure = sum(
        case.claim_kind in {SetClaimKind.POINT, SetClaimKind.HIGH_CONFIDENCE_INTERVAL}
        for case in cases
    )
    return PartialIdentificationMetrics(
        disposition=RegretDisposition.PARTIAL_IDENTIFICATION_ROBUST_PRIMARY,
        utility_direction=UTILITY_DIRECTION,
        exposure=len(exact_rows),
        robust_regret_bound_summary=_summary(robust_bounds),
        all_compatible_catastrophic_count=catastrophic_count,
        all_compatible_catastrophic_rate=catastrophic_count / len(exact_rows),
        false_certainty_exposure=certainty_claim_exposure,
        false_certainty_count=false_certainty_count,
        false_certainty_rate=_nullable(
            _quotient(
                false_certainty_count,
                certainty_claim_exposure,
                "partial-ID false-certainty rate",
            )
            if certainty_claim_exposure
            else None,
            certainty_claim_exposure,
            UndefinedReason.NO_CERTAINTY_CLAIM_EXPOSURE,
        ),
        w19_tail_robust_regret_bound_summary=(
            _summary(tail_bounds) if tail_bounds else None
        ),
        w19_tail_undefined_reason=(
            None if tail_bounds else UndefinedReason.NO_W19_TAIL_EXPOSURE
        ),
        rows=exact_rows,
    )


__all__ = [
    "ARTIFACT_ROLE",
    "BENCHMARK_STATUS",
    "CoverageDisposition",
    "DistributionSummary",
    "EffectIdentification",
    "FREEZE_AUTHORITY",
    "GaussianTrajectoryCase",
    "IdentifiedSetCase",
    "IdentifiedSetMetrics",
    "IdentifiedSetRow",
    "InterventionTrajectoryMetrics",
    "Interval",
    "METRIC_RUNTIME_SCHEMA",
    "NullableMetric",
    "OFFICIAL_EVALUATOR_BINDING",
    "PartialIdentificationCase",
    "PartialIdentificationMetrics",
    "PartialIdentificationRow",
    "PointRegretMetrics",
    "PolicyHorizonCoverageMetrics",
    "PolicyHorizonExposure",
    "RegretCase",
    "RegretCohortSummary",
    "RegretDisposition",
    "RegretRow",
    "SetClaimKind",
    "TreatmentEffectCase",
    "TreatmentEffectMetrics",
    "UTILITY_DIRECTION",
    "UndefinedReason",
    "identified_set_metrics",
    "intervention_trajectory_metrics",
    "partial_identification_regret",
    "point_identified_regret",
    "policy_horizon_coverage",
    "runtime_status",
    "treatment_effect_metrics",
]
