"""Closed, isolated PRE-FREEZE metric primitives for UCM M01 and M02.

This module is runtime evidence only.  It neither changes the active evaluator
nor claims benchmark-freeze authority.  It intentionally exposes a Pareto
vector of named results; there is no cross-metric aggregate.

The implementation is deliberately strict:

* numeric inputs must be real, finite and non-empty; booleans are not numbers;
* probability rows are closed on the simplex to an absolute tolerance of
  ``1e-12``;
* log scores use the benchmark's calculation-only clip to
  ``[1e-12, 1-1e-12]`` while raw probabilities remain unchanged;
* calibration uses the existing code-owned 15-bin target: Hyndman-Fan type-7
  (NumPy ``method="linear"``) quantiles and ``searchsorted(..., side="right")``.
  Exact probability ties therefore remain together.  Empty nominal bins remain
  present in the result;
* all summaries retain their denominator and a per-row, per-class, per-axis or
  per-horizon grain;
* empirical ensemble CRPS and energy scores give every ensemble member equal
  weight and use the biased ``S**2`` pair denominator, including self-pairs;
* interval endpoints are closed and coverage therefore uses ``lower <= truth
  <= upper``.

The formulas are identified in every result.  Their optimization direction,
tie policy, undefined disposition, denominator and weighting are therefore
part of the typed runtime output rather than ambient documentation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

import numpy as np

from .canonical import ProtocolViolation


BENCHMARK_STATUS = "PRE-FREEZE"
RUNTIME_ROLE = "runtime_only"
FREEZE_AUTHORITY = "not_claimed"
CALIBRATION_BIN_COUNT = 15
INTERVAL_LEVELS = (0.50, 0.80, 0.95)
SIMPLEX_ABSOLUTE_TOLERANCE = 1e-12
LOG_SCORE_CLIP_LOWER = 1e-12
LOG_SCORE_CLIP_UPPER = 1.0 - LOG_SCORE_CLIP_LOWER
SEMANTIC_COMPLETENESS = "partial_M01_M02_runtime_primitives_only"
BLOCKER_CODES = (
    "UCM-METRIC-B002",
    "UCM-METRIC-B003",
    "UCM-METRIC-B004",
    "UCM-METRIC-B007",
)
UNIMPLEMENTED_M02_OUTPUTS = (
    "no_new_action_policy_slice",
    "continue_current_policy_slice",
    "freeze_authorized_time_integrated_survival_weighting",
    "fixed_time_utility_distribution_error",
    "calibration_slope_intercept_by_horizon",
)


class OptimizationDirection(str, Enum):
    """Direction of improvement for one metric, never across metrics."""

    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class MetricStatus(str, Enum):
    """Closed disposition for defined, support-free, and unavailable results."""

    DEFINED = "defined"
    UNDEFINED_NO_SUPPORT = "undefined_no_support"
    UNAVAILABLE_UNRESOLVED_SEMANTICS = "unavailable_unresolved_semantics"


class DiagnosisTruthBranch(str, Enum):
    REALIZED_LABEL = "realized_label"
    ORACLE_POSTERIOR = "oracle_posterior"


class WeightPolicy(str, Enum):
    EQUAL_ROWS = "equal_rows"
    EQUAL_ROW_CLASS_CELLS = "equal_row_class_cells"
    EQUAL_OBSERVED_CLASSES = "equal_observed_classes"
    EQUAL_ENSEMBLE_MEMBERS = "equal_ensemble_members"
    EQUAL_ROWS_AND_ENSEMBLE_MEMBERS = "equal_rows_and_equal_ensemble_members"
    EQUAL_ROWS_ENSEMBLE_MEMBERS_AND_BIASED_PAIRS = (
        "equal_rows_equal_members_and_S_squared_pairs_including_self_pairs"
    )
    EQUAL_ROW_AXIS_CELLS = "equal_row_axis_cells"
    EQUAL_ROW_HORIZON_CELLS = "equal_row_horizon_cells"


class TiePolicy(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    ASCENDING_CLASS_INDEX = "descending_probability_then_ascending_class_index"
    HF_TYPE7_SEARCHSORTED_RIGHT = (
        "HF_type7_quantiles_then_searchsorted_right_exact_ties_together"
    )


class UndefinedPolicy(str, Enum):
    REJECT_INVALID_INPUT = "reject_invalid_or_empty_input"
    LOG_SCORE_CLIPPED = "calculation_only_clip_to_[1e-12,1-1e-12]"
    NO_CLASS_SUPPORT_IS_UNDEFINED = "no_true_class_support_is_undefined"
    EMPTY_NOMINAL_BIN_IS_UNDEFINED = "empty_nominal_bin_is_undefined"


@dataclass(frozen=True, slots=True)
class FormulaContract:
    """Closed semantic preimage for one runtime formula family."""

    formula_id: str
    formula: str
    direction: OptimizationDirection
    primitive_grain: str
    denominator: str
    weights: WeightPolicy
    tie_policy: TiePolicy
    undefined_policy: UndefinedPolicy
    finite_shape_policy: str


@dataclass(frozen=True, slots=True)
class MetricRuntimeContract:
    benchmark_status: str
    runtime_role: str
    freeze_authority: str
    aggregate_score: str
    calibration_bins: int
    interval_levels: tuple[float, float, float]
    interval_endpoints: str
    log_base: str
    log_score_clip_lower: float
    log_score_clip_upper: float
    probability_simplex_absolute_tolerance: float
    numeric_input_policy: str
    semantic_completeness: str
    blocker_codes: tuple[str, ...]
    unimplemented_m02_outputs: tuple[str, ...]
    formulas: tuple[FormulaContract, ...]


@dataclass(frozen=True, slots=True)
class MetricGrain:
    """One auditable metric grain.

    Exactly the applicable coordinates are populated.  ``denominator`` is
    always the number of equally weighted primitive observations represented by
    this grain.  ``numerator`` is the additive numerator before division; for
    RMSE it is the sum of squared normalized errors.
    """

    row_index: int | None
    class_index: int | None
    axis_index: int | None
    event_index: int | None
    horizon_index: int | None
    count: int
    denominator: int
    numerator: float | None
    value: float | None
    status: MetricStatus


@dataclass(frozen=True, slots=True)
class MetricResult:
    metric_id: str
    formula_id: str
    direction: OptimizationDirection
    count: int
    denominator: int
    numerator: float | None
    value: float | None
    status: MetricStatus
    grains: tuple[MetricGrain, ...]


@dataclass(frozen=True, slots=True)
class ReliabilityBin:
    """One nominal equal-mass bin; empty bins have undefined means."""

    bin_index: int
    count: int
    denominator: int
    minimum_probability: float | None
    maximum_probability: float | None
    mean_probability: float | None
    empirical_frequency: float | None
    absolute_gap: float | None
    weighted_absolute_gap: float
    status: MetricStatus


@dataclass(frozen=True, slots=True)
class CalibrationResult:
    metric_id: str
    formula_id: str
    direction: OptimizationDirection
    count: int
    denominator: int
    ece: float
    bins: tuple[ReliabilityBin, ...]


@dataclass(frozen=True, slots=True)
class IntervalInput:
    """Closed interval predictions at one nominal coverage level."""

    level: float
    lower: Any
    upper: Any


@dataclass(frozen=True, slots=True)
class IntervalCoverageResult:
    level: float
    result: MetricResult


@dataclass(frozen=True, slots=True)
class ClassRecallResult:
    class_index: int
    result: MetricResult


@dataclass(frozen=True, slots=True)
class ClassCalibrationResult:
    class_index: int
    calibration: CalibrationResult


@dataclass(frozen=True, slots=True)
class TopKResult:
    k: int
    result: MetricResult


@dataclass(frozen=True, slots=True)
class DiagnosisMetricReport:
    benchmark_status: str
    runtime_role: str
    freeze_authority: str
    count: int
    class_count: int
    truth_branch: DiagnosisTruthBranch
    multiclass_nll: MetricResult
    multiclass_brier: MetricResult
    top1_accuracy: MetricResult
    topk_accuracy: tuple[TopKResult, ...]
    macro_recall: MetricResult
    recall_by_class: tuple[ClassRecallResult, ...]
    top_label_calibration: CalibrationResult
    classwise_calibration: tuple[ClassCalibrationResult, ...]
    probability_interval_coverage: tuple[IntervalCoverageResult, ...]


@dataclass(frozen=True, slots=True)
class OraclePosteriorDiagnosisMetricReport:
    """Primary proper scores when the world exposes P(label | public history)."""

    benchmark_status: str
    runtime_role: str
    freeze_authority: str
    count: int
    class_count: int
    truth_branch: DiagnosisTruthBranch
    posterior_cross_entropy_nll: MetricResult
    posterior_multiclass_brier: MetricResult


@dataclass(frozen=True, slots=True)
class ContinuousAxisResult:
    axis_index: int
    result: MetricResult


@dataclass(frozen=True, slots=True)
class EventResult:
    event_index: int
    result: MetricResult


@dataclass(frozen=True, slots=True)
class HorizonResult:
    horizon_index: int
    horizon: float
    result: MetricResult


@dataclass(frozen=True, slots=True)
class UnavailableMetricResult:
    metric_id: str
    status: MetricStatus
    blocker_code: str
    detail: str


@dataclass(frozen=True, slots=True)
class ContinuousForecastReport:
    benchmark_status: str
    runtime_role: str
    freeze_authority: str
    count: int
    axis_count: int
    ensemble_size: int
    crps_by_axis: tuple[ContinuousAxisResult, ...]
    oracle_scale_normalized_mae_by_axis: tuple[ContinuousAxisResult, ...]
    oracle_scale_normalized_rmse_by_axis: tuple[ContinuousAxisResult, ...]
    interval_coverage: tuple[IntervalCoverageResult, ...]


@dataclass(frozen=True, slots=True)
class EventMetricReport:
    benchmark_status: str
    runtime_role: str
    freeze_authority: str
    count: int
    event_count: int
    nll_by_event: tuple[EventResult, ...]
    brier_by_event: tuple[EventResult, ...]
    reliability_by_event: tuple[ClassCalibrationResult, ...]


@dataclass(frozen=True, slots=True)
class EnergyScoreReport:
    benchmark_status: str
    runtime_role: str
    freeze_authority: str
    count: int
    axis_count: int
    ensemble_size: int
    normalized_joint_energy_score: MetricResult


@dataclass(frozen=True, slots=True)
class SurvivalMetricReport:
    """Scores for complete event status at every declared horizon.

    ``alive_by_horizon`` is the closed truth input.  No censoring estimator or
    implicit IPCW is performed.  Per-horizon scores are primary runtime
    primitives.  Equal-horizon summaries are explicitly descriptive; the
    required time-integrated primary scores remain typed unavailable until
    freeze-authorized time weights and endpoint semantics are closed.
    """

    benchmark_status: str
    runtime_role: str
    freeze_authority: str
    count: int
    horizon_count: int
    brier_by_horizon: tuple[HorizonResult, ...]
    nll_by_horizon: tuple[HorizonResult, ...]
    descriptive_equal_horizon_mean_brier: MetricResult
    descriptive_equal_horizon_mean_nll: MetricResult
    time_integrated_brier: UnavailableMetricResult
    time_integrated_nll: UnavailableMetricResult


def _contains_boolean(value: Any) -> bool:
    """Inspect the caller value before NumPy can coerce mixed booleans to ints."""

    if isinstance(value, (bool, np.bool_)):
        return True
    if isinstance(value, np.ndarray):
        if value.dtype == np.bool_:
            return True
        if value.dtype == object:
            return any(_contains_boolean(item) for item in value.flat)
        return False
    if isinstance(value, (list, tuple)):
        return any(_contains_boolean(item) for item in value)
    return False


def _finite_derived_scalar(value: Any, *, label: str) -> float:
    try:
        result = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ProtocolViolation(f"{label} must be finite") from exc
    if not math.isfinite(result):
        raise ProtocolViolation(f"{label} became non-finite")
    return result


def _finite_derived_array(value: np.ndarray, *, label: str) -> np.ndarray:
    if not np.all(np.isfinite(value)):
        raise ProtocolViolation(f"{label} became non-finite")
    return value


def _finite_square(value: float, *, label: str) -> float:
    try:
        with np.errstate(over="ignore", invalid="ignore"):
            squared = np.float64(value) * np.float64(value)
    except (FloatingPointError, OverflowError, TypeError, ValueError) as exc:
        raise ProtocolViolation(f"{label} became non-finite") from exc
    return _finite_derived_scalar(squared, label=label)


def _finite_fsum(values: Iterable[float], *, label: str) -> float:
    try:
        result = math.fsum(values)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ProtocolViolation(f"{label} became non-finite") from exc
    return _finite_derived_scalar(result, label=label)


def _numeric_array(value: Any, *, ndim: int, label: str) -> np.ndarray:
    if _contains_boolean(value):
        raise ProtocolViolation(f"{label} must contain real numbers, not booleans")
    try:
        raw = np.asarray(value)
        is_numeric = np.issubdtype(raw.dtype, np.number)
        is_complex = np.issubdtype(raw.dtype, np.complexfloating)
        if raw.dtype == np.bool_ or not is_numeric:
            raise ProtocolViolation(f"{label} must contain real numbers, not booleans")
        if is_complex:
            raise ProtocolViolation(f"{label} must contain real numbers")
        array = raw.astype(np.float64, copy=False)
    except ProtocolViolation:
        raise
    except (OverflowError, TypeError, ValueError) as exc:
        raise ProtocolViolation(
            f"{label} must be convertible to a rectangular real array"
        ) from exc
    if array.ndim != ndim or array.size == 0:
        raise ProtocolViolation(f"{label} must be a non-empty {ndim}D array")
    if not np.all(np.isfinite(array)):
        raise ProtocolViolation(f"{label} must contain only finite values")
    return array


def _integer_array(value: Any, *, ndim: int, label: str) -> np.ndarray:
    if _contains_boolean(value):
        raise ProtocolViolation(f"{label} must contain integers, not booleans")
    try:
        raw = np.asarray(value)
        is_integer = np.issubdtype(raw.dtype, np.integer)
        if raw.dtype == np.bool_ or not is_integer:
            raise ProtocolViolation(f"{label} must contain integers, not booleans")
        if raw.ndim != ndim or raw.size == 0:
            raise ProtocolViolation(f"{label} must be a non-empty {ndim}D array")
        return raw.astype(np.int64, copy=False)
    except ProtocolViolation:
        raise
    except (OverflowError, TypeError, ValueError) as exc:
        raise ProtocolViolation(
            f"{label} must be convertible to a rectangular integer array"
        ) from exc


def _probability_array(value: Any, *, ndim: int, label: str) -> np.ndarray:
    probabilities = _numeric_array(value, ndim=ndim, label=label)
    if np.any(probabilities < 0.0) or np.any(probabilities > 1.0):
        raise ProtocolViolation(f"{label} must be within [0,1]")
    return probabilities


def _probability_matrix(value: Any, *, label: str) -> np.ndarray:
    probabilities = _probability_array(value, ndim=2, label=label)
    if probabilities.shape[1] < 2:
        raise ProtocolViolation(f"{label} must contain at least two classes")
    if not np.allclose(
        probabilities.sum(axis=1),
        1.0,
        rtol=0.0,
        atol=SIMPLEX_ABSOLUTE_TOLERANCE,
    ):
        raise ProtocolViolation(f"{label} rows must sum to one")
    return probabilities


def _defined_grain(
    value: float,
    *,
    numerator: float | None = None,
    denominator: int = 1,
    row_index: int | None = None,
    class_index: int | None = None,
    axis_index: int | None = None,
    event_index: int | None = None,
    horizon_index: int | None = None,
) -> MetricGrain:
    finite_value = _finite_derived_scalar(value, label="metric grain value")
    finite_numerator = (
        finite_value
        if numerator is None
        else _finite_derived_scalar(numerator, label="metric grain numerator")
    )
    return MetricGrain(
        row_index=row_index,
        class_index=class_index,
        axis_index=axis_index,
        event_index=event_index,
        horizon_index=horizon_index,
        count=denominator,
        denominator=denominator,
        numerator=finite_numerator,
        value=finite_value,
        status=MetricStatus.DEFINED,
    )


def _mean_result(
    metric_id: str,
    formula_id: str,
    direction: OptimizationDirection,
    grains: Iterable[MetricGrain],
) -> MetricResult:
    materialized = tuple(grains)
    denominator = sum(grain.denominator for grain in materialized)
    if denominator <= 0:
        return MetricResult(
            metric_id=metric_id,
            formula_id=formula_id,
            direction=direction,
            count=0,
            denominator=0,
            numerator=None,
            value=None,
            status=MetricStatus.UNDEFINED_NO_SUPPORT,
            grains=materialized,
        )
    try:
        numerator = math.fsum(float(grain.numerator) for grain in materialized)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ProtocolViolation(f"{metric_id} aggregate became non-finite") from exc
    numerator = _finite_derived_scalar(numerator, label=f"{metric_id} numerator")
    value = _finite_derived_scalar(numerator / denominator, label=f"{metric_id} value")
    return MetricResult(
        metric_id=metric_id,
        formula_id=formula_id,
        direction=direction,
        count=denominator,
        denominator=denominator,
        numerator=numerator,
        value=value,
        status=MetricStatus.DEFINED,
        grains=materialized,
    )


def _rmse_result(
    metric_id: str,
    formula_id: str,
    grains: Iterable[MetricGrain],
) -> MetricResult:
    mean_square = _mean_result(
        metric_id,
        formula_id,
        OptimizationDirection.MINIMIZE,
        grains,
    )
    if mean_square.status is not MetricStatus.DEFINED:
        return mean_square
    return MetricResult(
        metric_id=mean_square.metric_id,
        formula_id=mean_square.formula_id,
        direction=mean_square.direction,
        count=mean_square.count,
        denominator=mean_square.denominator,
        numerator=mean_square.numerator,
        value=math.sqrt(float(mean_square.value)),
        status=mean_square.status,
        grains=mean_square.grains,
    )


def _log_score(probability: float) -> float:
    clipped = min(max(probability, LOG_SCORE_CLIP_LOWER), LOG_SCORE_CLIP_UPPER)
    return _finite_derived_scalar(-math.log(clipped), label="clipped log score")


def _hf_type7_calibration_bin_assignments(values: np.ndarray) -> np.ndarray:
    """Apply the existing HF type-7 quantile/right-search target exactly."""

    edges = np.quantile(
        values,
        np.arange(1, CALIBRATION_BIN_COUNT, dtype=np.float64) / CALIBRATION_BIN_COUNT,
        method="linear",
    )
    _finite_derived_array(edges, label="calibration quantile edges")
    return np.searchsorted(edges, values, side="right")


def _calibration(
    metric_id: str,
    formula_id: str,
    probabilities: np.ndarray,
    outcomes: np.ndarray,
) -> CalibrationResult:
    assignments = _hf_type7_calibration_bin_assignments(probabilities)
    denominator = probabilities.shape[0]
    bins: list[ReliabilityBin] = []
    weighted_sum = 0.0
    for bin_index in range(CALIBRATION_BIN_COUNT):
        mask = assignments == bin_index
        count = int(np.sum(mask))
        if count == 0:
            bins.append(
                ReliabilityBin(
                    bin_index=bin_index,
                    count=0,
                    denominator=denominator,
                    minimum_probability=None,
                    maximum_probability=None,
                    mean_probability=None,
                    empirical_frequency=None,
                    absolute_gap=None,
                    weighted_absolute_gap=0.0,
                    status=MetricStatus.UNDEFINED_NO_SUPPORT,
                )
            )
            continue
        selected_probabilities = probabilities[mask]
        mean_probability = _finite_derived_scalar(
            np.mean(selected_probabilities), label="calibration mean probability"
        )
        empirical_frequency = _finite_derived_scalar(
            np.mean(outcomes[mask]), label="calibration empirical frequency"
        )
        gap = _finite_derived_scalar(
            abs(mean_probability - empirical_frequency), label="calibration gap"
        )
        contribution = _finite_derived_scalar(
            (count / denominator) * gap, label="calibration weighted gap"
        )
        weighted_sum = _finite_derived_scalar(
            weighted_sum + contribution, label="calibration ECE"
        )
        bins.append(
            ReliabilityBin(
                bin_index=bin_index,
                count=count,
                denominator=denominator,
                minimum_probability=float(np.min(selected_probabilities)),
                maximum_probability=float(np.max(selected_probabilities)),
                mean_probability=mean_probability,
                empirical_frequency=empirical_frequency,
                absolute_gap=gap,
                weighted_absolute_gap=contribution,
                status=MetricStatus.DEFINED,
            )
        )
    return CalibrationResult(
        metric_id=metric_id,
        formula_id=formula_id,
        direction=OptimizationDirection.MINIMIZE,
        count=denominator,
        denominator=denominator,
        ece=weighted_sum,
        bins=tuple(bins),
    )


def _validate_interval_inputs(
    intervals: Iterable[IntervalInput],
    *,
    shape: tuple[int, ...],
    label: str,
    probability_bounds: bool,
) -> tuple[tuple[float, np.ndarray, np.ndarray], ...]:
    materialized = tuple(intervals)
    if tuple(item.level for item in materialized) != INTERVAL_LEVELS:
        raise ProtocolViolation(
            f"{label} must contain ordered levels {INTERVAL_LEVELS} exactly"
        )
    result: list[tuple[float, np.ndarray, np.ndarray]] = []
    for item in materialized:
        if type(item.level) is not float:
            raise ProtocolViolation(f"{label} levels must be floats")
        lower = _numeric_array(item.lower, ndim=len(shape), label=f"{label} lower")
        upper = _numeric_array(item.upper, ndim=len(shape), label=f"{label} upper")
        if lower.shape != shape or upper.shape != shape:
            raise ProtocolViolation(f"{label} endpoints must have shape {shape}")
        if np.any(lower > upper):
            raise ProtocolViolation(f"{label} requires lower <= upper")
        if probability_bounds and (np.any(lower < 0.0) or np.any(upper > 1.0)):
            raise ProtocolViolation(f"{label} probability endpoints must be in [0,1]")
        result.append((item.level, lower, upper))
    return tuple(result)


def diagnosis_metrics_m01(
    probabilities: Any,
    true_class: Any,
    *,
    top_k: tuple[int, ...],
    probability_intervals: tuple[IntervalInput, ...],
) -> DiagnosisMetricReport:
    """Compute the closed M01 diagnosis Pareto vector.

    Multiclass Brier is ``sum_k (p_k-y_k)^2`` per row (no class-count
    division).  Macro recall averages only classes with positive true support;
    unsupported class recalls remain explicit ``undefined_no_support`` grains.
    Prediction ties are ordered by ascending class index for top-1/top-k.
    Probability interval coverage treats each row/class one-hot target as one
    equally weighted primitive observation.
    """

    probs = _probability_matrix(probabilities, label="probabilities")
    labels = _integer_array(true_class, ndim=1, label="true_class")
    row_count, class_count = probs.shape
    if labels.shape != (row_count,):
        raise ProtocolViolation("true_class must align with probability rows")
    if np.any(labels < 0) or np.any(labels >= class_count):
        raise ProtocolViolation("true_class contains an out-of-range class")
    if (
        type(top_k) is not tuple
        or not top_k
        or any(type(k) is not int for k in top_k)
        or tuple(sorted(set(top_k))) != top_k
        or any(k < 2 or k > class_count for k in top_k)
    ):
        raise ProtocolViolation(
            "top_k must be a non-empty strictly increasing tuple in [2,class_count]"
        )

    one_hot = np.zeros_like(probs)
    one_hot[np.arange(row_count), labels] = 1.0
    nll_grains: list[MetricGrain] = []
    brier_grains: list[MetricGrain] = []
    top1_grains: list[MetricGrain] = []
    topk_grains: dict[int, list[MetricGrain]] = {k: [] for k in top_k}
    chosen = np.empty(row_count, dtype=np.int64)
    for row_index in range(row_count):
        score = _log_score(float(probs[row_index, labels[row_index]]))
        nll_grains.append(_defined_grain(score, row_index=row_index))
        row_brier = float(np.sum((probs[row_index] - one_hot[row_index]) ** 2))
        brier_grains.append(_defined_grain(row_brier, row_index=row_index))
        ranking = np.lexsort((np.arange(class_count), -probs[row_index]))
        chosen[row_index] = ranking[0]
        correct = float(ranking[0] == labels[row_index])
        top1_grains.append(_defined_grain(correct, row_index=row_index))
        for k in top_k:
            hit = float(labels[row_index] in ranking[:k])
            topk_grains[k].append(_defined_grain(hit, row_index=row_index))

    nll = _mean_result(
        "M01.multiclass_nll",
        "m01.realized_label_multiclass_nll.clip_1e-12/v1",
        OptimizationDirection.MINIMIZE,
        nll_grains,
    )
    brier = _mean_result(
        "M01.multiclass_brier",
        "m01.multiclass_brier.sum_over_classes_then_mean_rows/v1",
        OptimizationDirection.MINIMIZE,
        brier_grains,
    )
    top1 = _mean_result(
        "M01.top1_accuracy",
        "m01.top1.descending_probability_then_class_index/v1",
        OptimizationDirection.MAXIMIZE,
        top1_grains,
    )
    topk_results = tuple(
        TopKResult(
            k=k,
            result=_mean_result(
                f"M01.top{k}_accuracy",
                "m01.topk.descending_probability_then_class_index/v1",
                OptimizationDirection.MAXIMIZE,
                topk_grains[k],
            ),
        )
        for k in top_k
    )

    recall_by_class: list[ClassRecallResult] = []
    defined_recalls: list[MetricGrain] = []
    for class_index in range(class_count):
        support = int(np.sum(labels == class_index))
        true_positive = int(np.sum((labels == class_index) & (chosen == class_index)))
        if support == 0:
            result = MetricResult(
                metric_id=f"M01.recall.class_{class_index}",
                formula_id="m01.recall.true_positive_over_true_support/v1",
                direction=OptimizationDirection.MAXIMIZE,
                count=0,
                denominator=0,
                numerator=None,
                value=None,
                status=MetricStatus.UNDEFINED_NO_SUPPORT,
                grains=(),
            )
        else:
            value = true_positive / support
            grain = _defined_grain(
                value,
                numerator=float(true_positive),
                denominator=support,
                class_index=class_index,
            )
            result = MetricResult(
                metric_id=f"M01.recall.class_{class_index}",
                formula_id="m01.recall.true_positive_over_true_support/v1",
                direction=OptimizationDirection.MAXIMIZE,
                count=support,
                denominator=support,
                numerator=float(true_positive),
                value=value,
                status=MetricStatus.DEFINED,
                grains=(grain,),
            )
            defined_recalls.append(_defined_grain(value, class_index=class_index))
        recall_by_class.append(ClassRecallResult(class_index, result))
    macro_recall = _mean_result(
        "M01.macro_recall",
        "m01.macro_recall.unweighted_observed_classes_only/v1",
        OptimizationDirection.MAXIMIZE,
        defined_recalls,
    )

    confidence = probs[np.arange(row_count), chosen]
    correctness = (chosen == labels).astype(np.float64)
    top_label_calibration = _calibration(
        "M01.equal_mass_ece_15",
        "m01.top_label_ece.15_HF_type7_searchsorted_right/v1",
        confidence,
        correctness,
    )
    classwise_calibration = tuple(
        ClassCalibrationResult(
            class_index=class_index,
            calibration=_calibration(
                f"M01.classwise_ece_15.class_{class_index}",
                "m01.one_vs_rest_ece.15_HF_type7_searchsorted_right/v1",
                probs[:, class_index],
                one_hot[:, class_index],
            ),
        )
        for class_index in range(class_count)
    )

    interval_values = _validate_interval_inputs(
        probability_intervals,
        shape=probs.shape,
        label="probability_intervals",
        probability_bounds=True,
    )
    interval_results: list[IntervalCoverageResult] = []
    for level, lower, upper in interval_values:
        grains = []
        for row_index in range(row_count):
            for class_index in range(class_count):
                covered = float(
                    lower[row_index, class_index]
                    <= one_hot[row_index, class_index]
                    <= upper[row_index, class_index]
                )
                grains.append(
                    _defined_grain(
                        covered,
                        row_index=row_index,
                        class_index=class_index,
                    )
                )
        interval_results.append(
            IntervalCoverageResult(
                level=level,
                result=_mean_result(
                    f"M01.probability_interval_coverage.{level:.2f}",
                    "m01.one_hot_probability_interval.closed_endpoints.equal_cells/v1",
                    OptimizationDirection.MAXIMIZE,
                    grains,
                ),
            )
        )

    return DiagnosisMetricReport(
        benchmark_status=BENCHMARK_STATUS,
        runtime_role=RUNTIME_ROLE,
        freeze_authority=FREEZE_AUTHORITY,
        count=row_count,
        class_count=class_count,
        truth_branch=DiagnosisTruthBranch.REALIZED_LABEL,
        multiclass_nll=nll,
        multiclass_brier=brier,
        top1_accuracy=top1,
        topk_accuracy=topk_results,
        macro_recall=macro_recall,
        recall_by_class=tuple(recall_by_class),
        top_label_calibration=top_label_calibration,
        classwise_calibration=classwise_calibration,
        probability_interval_coverage=tuple(interval_results),
    )


def oracle_posterior_diagnosis_metrics_m01(
    predicted_probabilities: Any,
    oracle_posterior: Any,
) -> OraclePosteriorDiagnosisMetricReport:
    """Primary M01 proper scores against P(label | public history).

    This branch is intentionally distinct from :func:`diagnosis_metrics_m01`,
    whose truth is one realized label per row.  The oracle posterior is used as
    a soft target only; it is never sampled or collapsed to top-1.  Per-row
    cross-entropy is ``-sum_k q_k log(clip(p_k))`` and posterior Brier is
    ``sum_k (p_k-q_k)^2``.
    """

    predicted = _probability_matrix(
        predicted_probabilities, label="predicted_probabilities"
    )
    oracle = _probability_matrix(oracle_posterior, label="oracle_posterior")
    if oracle.shape != predicted.shape:
        raise ProtocolViolation(
            "oracle_posterior must align with predicted probability rows/classes"
        )
    nll_grains: list[MetricGrain] = []
    brier_grains: list[MetricGrain] = []
    for row_index in range(predicted.shape[0]):
        row_cross_entropy = _finite_fsum(
            (
                float(oracle[row_index, class_index])
                * _log_score(float(predicted[row_index, class_index]))
                for class_index in range(predicted.shape[1])
            ),
            label="oracle posterior cross entropy",
        )
        nll_grains.append(
            _defined_grain(
                _finite_derived_scalar(
                    row_cross_entropy, label="oracle posterior cross entropy"
                ),
                row_index=row_index,
            )
        )
        with np.errstate(over="ignore", invalid="ignore"):
            row_brier = np.sum((predicted[row_index] - oracle[row_index]) ** 2)
        brier_grains.append(
            _defined_grain(
                _finite_derived_scalar(row_brier, label="oracle posterior Brier"),
                row_index=row_index,
            )
        )
    return OraclePosteriorDiagnosisMetricReport(
        benchmark_status=BENCHMARK_STATUS,
        runtime_role=RUNTIME_ROLE,
        freeze_authority=FREEZE_AUTHORITY,
        count=predicted.shape[0],
        class_count=predicted.shape[1],
        truth_branch=DiagnosisTruthBranch.ORACLE_POSTERIOR,
        posterior_cross_entropy_nll=_mean_result(
            "M01.oracle_posterior_cross_entropy_nll",
            "m01.oracle_posterior_cross_entropy.clip_1e-12/v1",
            OptimizationDirection.MINIMIZE,
            nll_grains,
        ),
        posterior_multiclass_brier=_mean_result(
            "M01.oracle_posterior_multiclass_brier",
            "m01.oracle_posterior_brier.sum_over_classes_then_mean_rows/v1",
            OptimizationDirection.MINIMIZE,
            brier_grains,
        ),
    )


def _continuous_forecast_core(
    samples: np.ndarray,
    truth: np.ndarray,
    oracle_scale: np.ndarray,
    intervals: tuple[IntervalInput, ...],
) -> ContinuousForecastReport:
    row_count, ensemble_size, axis_count = samples.shape
    if truth.shape != (row_count, axis_count):
        raise ProtocolViolation("truth must align with sample rows and axes")
    if oracle_scale.shape != (axis_count,) or np.any(oracle_scale <= 0.0):
        raise ProtocolViolation(
            "oracle_scale must be one finite positive value per axis"
        )
    interval_values = _validate_interval_inputs(
        intervals,
        shape=truth.shape,
        label="continuous_intervals",
        probability_bounds=False,
    )
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        means = np.mean(samples, axis=1)
    _finite_derived_array(means, label="ensemble means")
    crps_results: list[ContinuousAxisResult] = []
    mae_results: list[ContinuousAxisResult] = []
    rmse_results: list[ContinuousAxisResult] = []
    for axis_index in range(axis_count):
        crps_grains: list[MetricGrain] = []
        mae_grains: list[MetricGrain] = []
        rmse_grains: list[MetricGrain] = []
        for row_index in range(row_count):
            members = samples[row_index, :, axis_index]
            observed = truth[row_index, axis_index]
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                first_term_raw = np.mean(np.abs(members - observed))
                second_term_raw = 0.5 * np.mean(
                    np.abs(members[:, None] - members[None, :])
                )
            first_term = _finite_derived_scalar(
                first_term_raw, label="CRPS observation term"
            )
            second_term = _finite_derived_scalar(
                second_term_raw, label="CRPS ensemble pair term"
            )
            crps = _finite_derived_scalar(
                first_term - second_term, label="CRPS row score"
            )
            crps_grains.append(
                _defined_grain(crps, row_index=row_index, axis_index=axis_index)
            )
            with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
                normalized_error_raw = (
                    means[row_index, axis_index] - observed
                ) / oracle_scale[axis_index]
            normalized_error = _finite_derived_scalar(
                normalized_error_raw, label="oracle-scale normalized error"
            )
            mae_grains.append(
                _defined_grain(
                    abs(normalized_error),
                    row_index=row_index,
                    axis_index=axis_index,
                )
            )
            rmse_grains.append(
                _defined_grain(
                    _finite_square(normalized_error, label="squared normalized error"),
                    row_index=row_index,
                    axis_index=axis_index,
                )
            )
        crps_results.append(
            ContinuousAxisResult(
                axis_index,
                _mean_result(
                    f"M02.continuous_crps.axis_{axis_index}",
                    "m02.empirical_crps.equal_members.biased_pair_denominator/v1",
                    OptimizationDirection.MINIMIZE,
                    crps_grains,
                ),
            )
        )
        mae_results.append(
            ContinuousAxisResult(
                axis_index,
                _mean_result(
                    f"M02.oracle_scale_normalized_mae.axis_{axis_index}",
                    "m02.absolute_ensemble_mean_error_over_positive_oracle_scale/v1",
                    OptimizationDirection.MINIMIZE,
                    mae_grains,
                ),
            )
        )
        rmse_results.append(
            ContinuousAxisResult(
                axis_index,
                _rmse_result(
                    f"M02.oracle_scale_normalized_rmse.axis_{axis_index}",
                    "m02.sqrt_mean_squared_ensemble_mean_error_over_oracle_scale/v1",
                    rmse_grains,
                ),
            )
        )

    coverage_results = []
    for level, lower, upper in interval_values:
        grains = tuple(
            _defined_grain(
                float(lower[row, axis] <= truth[row, axis] <= upper[row, axis]),
                row_index=row,
                axis_index=axis,
            )
            for row in range(row_count)
            for axis in range(axis_count)
        )
        coverage_results.append(
            IntervalCoverageResult(
                level,
                _mean_result(
                    f"M02.continuous_interval_coverage.{level:.2f}",
                    "m02.continuous_interval.closed_endpoints.equal_cells/v1",
                    OptimizationDirection.MAXIMIZE,
                    grains,
                ),
            )
        )
    return ContinuousForecastReport(
        benchmark_status=BENCHMARK_STATUS,
        runtime_role=RUNTIME_ROLE,
        freeze_authority=FREEZE_AUTHORITY,
        count=row_count,
        axis_count=axis_count,
        ensemble_size=ensemble_size,
        crps_by_axis=tuple(crps_results),
        oracle_scale_normalized_mae_by_axis=tuple(mae_results),
        oracle_scale_normalized_rmse_by_axis=tuple(rmse_results),
        interval_coverage=tuple(coverage_results),
    )


def deterministic_continuous_metrics_m02(
    prediction: Any,
    truth: Any,
    oracle_scale: Any,
    *,
    intervals: tuple[IntervalInput, ...],
) -> ContinuousForecastReport:
    """M02 continuous scores with a one-member (deterministic) ensemble."""

    predicted = _numeric_array(prediction, ndim=2, label="prediction")
    observed = _numeric_array(truth, ndim=2, label="truth")
    scale = _numeric_array(oracle_scale, ndim=1, label="oracle_scale")
    return _continuous_forecast_core(predicted[:, None, :], observed, scale, intervals)


def ensemble_continuous_metrics_m02(
    samples: Any,
    truth: Any,
    oracle_scale: Any,
    *,
    intervals: tuple[IntervalInput, ...],
) -> ContinuousForecastReport:
    """M02 continuous scores for equally weighted empirical ensemble members."""

    ensemble = _numeric_array(samples, ndim=3, label="samples")
    observed = _numeric_array(truth, ndim=2, label="truth")
    scale = _numeric_array(oracle_scale, ndim=1, label="oracle_scale")
    return _continuous_forecast_core(ensemble, observed, scale, intervals)


def discrete_event_metrics_m02(
    event_probabilities: Any,
    event_truth: Any,
) -> EventMetricReport:
    """M02 Bernoulli event NLL/Brier/reliability, separately by event."""

    probabilities = _probability_array(
        event_probabilities, ndim=2, label="event_probabilities"
    )
    truth = _integer_array(event_truth, ndim=2, label="event_truth")
    if truth.shape != probabilities.shape or not np.all(np.isin(truth, (0, 1))):
        raise ProtocolViolation("event_truth must be aligned integer 0/1 values")
    row_count, event_count = probabilities.shape
    nll_results: list[EventResult] = []
    brier_results: list[EventResult] = []
    reliability_results: list[ClassCalibrationResult] = []
    for event_index in range(event_count):
        nll_grains = []
        brier_grains = []
        for row_index in range(row_count):
            realized_probability = (
                probabilities[row_index, event_index]
                if truth[row_index, event_index] == 1
                else 1.0 - probabilities[row_index, event_index]
            )
            score = _log_score(float(realized_probability))
            nll_grains.append(
                _defined_grain(score, row_index=row_index, event_index=event_index)
            )
            error = (
                probabilities[row_index, event_index] - truth[row_index, event_index]
            )
            brier_grains.append(
                _defined_grain(
                    float(error**2), row_index=row_index, event_index=event_index
                )
            )
        nll_results.append(
            EventResult(
                event_index,
                _mean_result(
                    f"M02.event_nll.event_{event_index}",
                    "m02.bernoulli_nll.clip_1e-12/v1",
                    OptimizationDirection.MINIMIZE,
                    nll_grains,
                ),
            )
        )
        brier_results.append(
            EventResult(
                event_index,
                _mean_result(
                    f"M02.event_brier.event_{event_index}",
                    "m02.bernoulli_brier.equal_rows/v1",
                    OptimizationDirection.MINIMIZE,
                    brier_grains,
                ),
            )
        )
        reliability_results.append(
            ClassCalibrationResult(
                event_index,
                _calibration(
                    f"M02.event_reliability.event_{event_index}",
                    "m02.event_reliability.15_HF_type7_searchsorted_right/v1",
                    probabilities[:, event_index],
                    truth[:, event_index].astype(np.float64),
                ),
            )
        )
    return EventMetricReport(
        benchmark_status=BENCHMARK_STATUS,
        runtime_role=RUNTIME_ROLE,
        freeze_authority=FREEZE_AUTHORITY,
        count=row_count,
        event_count=event_count,
        nll_by_event=tuple(nll_results),
        brier_by_event=tuple(brier_results),
        reliability_by_event=tuple(reliability_results),
    )


def joint_energy_score_m02(
    samples: Any,
    truth: Any,
    oracle_scale: Any,
) -> EnergyScoreReport:
    """M02 normalized multivariate empirical energy score.

    Each axis is divided by its positive oracle scale before Euclidean norms are
    taken.  Rows and ensemble members are equally weighted.
    """

    ensemble = _numeric_array(samples, ndim=3, label="samples")
    observed = _numeric_array(truth, ndim=2, label="truth")
    scale = _numeric_array(oracle_scale, ndim=1, label="oracle_scale")
    row_count, ensemble_size, axis_count = ensemble.shape
    if observed.shape != (row_count, axis_count):
        raise ProtocolViolation("truth must align with sample rows and axes")
    if scale.shape != (axis_count,) or np.any(scale <= 0.0):
        raise ProtocolViolation(
            "oracle_scale must be one finite positive value per axis"
        )
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        normalized_samples = ensemble / scale[None, None, :]
        normalized_truth = observed / scale[None, :]
    _finite_derived_array(normalized_samples, label="normalized energy samples")
    _finite_derived_array(normalized_truth, label="normalized energy truth")
    grains = []
    for row_index in range(row_count):
        members = normalized_samples[row_index]
        target = normalized_truth[row_index]
        with np.errstate(over="ignore", invalid="ignore"):
            member_errors = members - target
            pairwise = members[:, None, :] - members[None, :, :]
        _finite_derived_array(member_errors, label="energy member-truth differences")
        _finite_derived_array(pairwise, label="energy pairwise differences")
        member_norms = tuple(
            _finite_derived_scalar(
                math.hypot(*(float(value) for value in row)),
                label="energy member norm",
            )
            for row in member_errors
        )
        pair_norms = tuple(
            _finite_derived_scalar(
                math.hypot(*(float(value) for value in row)),
                label="energy pair norm",
            )
            for matrix in pairwise
            for row in matrix
        )
        first_term = _finite_derived_scalar(
            _finite_fsum(member_norms, label="energy observation sum") / ensemble_size,
            label="energy observation term",
        )
        second_term = _finite_derived_scalar(
            0.5
            * _finite_fsum(pair_norms, label="energy pair sum")
            / (ensemble_size**2),
            label="energy pair term",
        )
        grains.append(
            _defined_grain(
                _finite_derived_scalar(
                    first_term - second_term, label="energy row score"
                ),
                row_index=row_index,
            )
        )
    result = _mean_result(
        "M02.normalized_joint_energy_score",
        "m02.energy.euclidean_after_oracle_scale.equal_members.biased_pairs/v1",
        OptimizationDirection.MINIMIZE,
        grains,
    )
    return EnergyScoreReport(
        benchmark_status=BENCHMARK_STATUS,
        runtime_role=RUNTIME_ROLE,
        freeze_authority=FREEZE_AUTHORITY,
        count=row_count,
        axis_count=axis_count,
        ensemble_size=ensemble_size,
        normalized_joint_energy_score=result,
    )


def closed_survival_metrics_m02(
    survival_probabilities: Any,
    alive_by_horizon: Any,
    horizons: Any,
) -> SurvivalMetricReport:
    """M02 complete-data per-horizon survival Brier/NLL.

    The benchmark requires *time-integrated* Brier/NLL, but its weighting and
    endpoint rule remain a typed target gap.  Consequently this function does
    not label an equal-horizon mean as integrated.  It returns the equal-horizon
    value as explicitly descriptive and returns typed unavailable primary
    results until a freeze-authorized time-weight preimage exists.
    """

    probabilities = _probability_array(
        survival_probabilities, ndim=2, label="survival_probabilities"
    )
    alive = _integer_array(alive_by_horizon, ndim=2, label="alive_by_horizon")
    horizon_values = _numeric_array(horizons, ndim=1, label="horizons")
    if alive.shape != probabilities.shape or not np.all(np.isin(alive, (0, 1))):
        raise ProtocolViolation("alive_by_horizon must be aligned integer 0/1 values")
    if horizon_values.shape != (probabilities.shape[1],):
        raise ProtocolViolation("horizons must align with survival columns")
    if np.any(horizon_values <= 0.0) or np.any(np.diff(horizon_values) <= 0.0):
        raise ProtocolViolation("horizons must be strictly increasing and positive")
    if np.any(np.diff(probabilities, axis=1) > SIMPLEX_ABSOLUTE_TOLERANCE):
        raise ProtocolViolation("survival probabilities must be non-increasing")
    if np.any(np.diff(alive, axis=1) > 0):
        raise ProtocolViolation("alive_by_horizon cannot return to alive after death")

    row_count, horizon_count = probabilities.shape
    brier_by_horizon = []
    nll_by_horizon = []
    equal_horizon_brier_grains: list[MetricGrain] = []
    equal_horizon_nll_grains: list[MetricGrain] = []
    for horizon_index in range(horizon_count):
        brier_grains = []
        nll_grains = []
        for row_index in range(row_count):
            error = (
                probabilities[row_index, horizon_index]
                - alive[row_index, horizon_index]
            )
            brier_grain = _defined_grain(
                float(error**2),
                row_index=row_index,
                horizon_index=horizon_index,
            )
            brier_grains.append(brier_grain)
            equal_horizon_brier_grains.append(brier_grain)
            realized_probability = (
                probabilities[row_index, horizon_index]
                if alive[row_index, horizon_index] == 1
                else 1.0 - probabilities[row_index, horizon_index]
            )
            score = _log_score(float(realized_probability))
            nll_grain = _defined_grain(
                score,
                row_index=row_index,
                horizon_index=horizon_index,
            )
            nll_grains.append(nll_grain)
            equal_horizon_nll_grains.append(nll_grain)
        brier_by_horizon.append(
            HorizonResult(
                horizon_index,
                float(horizon_values[horizon_index]),
                _mean_result(
                    f"M02.survival_brier.horizon_{horizon_index}",
                    "m02.complete_alive_indicator_brier.equal_rows/v1",
                    OptimizationDirection.MINIMIZE,
                    brier_grains,
                ),
            )
        )
        nll_by_horizon.append(
            HorizonResult(
                horizon_index,
                float(horizon_values[horizon_index]),
                _mean_result(
                    f"M02.survival_nll.horizon_{horizon_index}",
                    "m02.complete_alive_indicator_nll.clip_1e-12/v1",
                    OptimizationDirection.MINIMIZE,
                    nll_grains,
                ),
            )
        )
    return SurvivalMetricReport(
        benchmark_status=BENCHMARK_STATUS,
        runtime_role=RUNTIME_ROLE,
        freeze_authority=FREEZE_AUTHORITY,
        count=row_count,
        horizon_count=horizon_count,
        brier_by_horizon=tuple(brier_by_horizon),
        nll_by_horizon=tuple(nll_by_horizon),
        descriptive_equal_horizon_mean_brier=_mean_result(
            "M02.descriptive_equal_horizon_mean_survival_brier",
            "m02.descriptive_survival_brier.equal_row_horizon_cells/v1",
            OptimizationDirection.MINIMIZE,
            equal_horizon_brier_grains,
        ),
        descriptive_equal_horizon_mean_nll=_mean_result(
            "M02.descriptive_equal_horizon_mean_survival_nll",
            "m02.descriptive_survival_nll.equal_row_horizon_cells.clip_1e-12/v1",
            OptimizationDirection.MINIMIZE,
            equal_horizon_nll_grains,
        ),
        time_integrated_brier=UnavailableMetricResult(
            metric_id="M02.time_integrated_survival_brier",
            status=MetricStatus.UNAVAILABLE_UNRESOLVED_SEMANTICS,
            blocker_code="UCM-METRIC-B007",
            detail=(
                "freeze-authorized time weights and endpoint integration rule are "
                "not closed"
            ),
        ),
        time_integrated_nll=UnavailableMetricResult(
            metric_id="M02.time_integrated_survival_nll",
            status=MetricStatus.UNAVAILABLE_UNRESOLVED_SEMANTICS,
            blocker_code="UCM-METRIC-B007",
            detail=(
                "freeze-authorized time weights and endpoint integration rule are "
                "not closed"
            ),
        ),
    )


def runtime_contract() -> MetricRuntimeContract:
    """Return the closed code-owned semantic constants without freeze claims."""

    finite = (
        "real finite non-boolean non-empty arrays; exact declared rank and aligned "
        "shape; probability values in [0,1]"
    )
    formulas = (
        FormulaContract(
            "m01.realized_label_multiclass_nll.clip_1e-12/v1",
            "row=-ln(clip(p[true_class],1e-12,1-1e-12)); summary=sum(row)/N",
            OptimizationDirection.MINIMIZE,
            "row",
            "N rows",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.LOG_SCORE_CLIPPED,
            finite + "; probabilities shape N x K, K>=2, rows sum to one",
        ),
        FormulaContract(
            "m01.multiclass_brier.sum_over_classes_then_mean_rows/v1",
            "row=sum_k((p_k-one_hot_k)^2); summary=sum(row)/N",
            OptimizationDirection.MINIMIZE,
            "row",
            "N rows; no division by K",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; probabilities shape N x K and labels shape N",
        ),
        FormulaContract(
            "m01.oracle_posterior_cross_entropy.clip_1e-12/v1",
            "row=-sum_k(q_k*ln(clip(p_k,1e-12,1-1e-12))); summary=sum(row)/N",
            OptimizationDirection.MINIMIZE,
            "row with soft oracle posterior q",
            "N rows; class sum is inside each row",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.LOG_SCORE_CLIPPED,
            finite + "; predicted p and oracle q both shape N x K and simplex rows",
        ),
        FormulaContract(
            "m01.oracle_posterior_brier.sum_over_classes_then_mean_rows/v1",
            "row=sum_k((p_k-q_k)^2); summary=sum(row)/N",
            OptimizationDirection.MINIMIZE,
            "row with soft oracle posterior q",
            "N rows; no division by K",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; predicted p and oracle q both shape N x K and simplex rows",
        ),
        FormulaContract(
            "m01.top1.descending_probability_then_class_index/v1",
            "row=1[argmax(p)==true_class]; summary=sum(row)/N",
            OptimizationDirection.MAXIMIZE,
            "row",
            "N rows",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.ASCENDING_CLASS_INDEX,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; probabilities shape N x K and labels shape N",
        ),
        FormulaContract(
            "m01.topk.descending_probability_then_class_index/v1",
            "row=1[true_class in first k ranked classes]; summary=sum(row)/N",
            OptimizationDirection.MAXIMIZE,
            "row",
            "N rows separately for each declared k",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.ASCENDING_CLASS_INDEX,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; 2<=k<=K; k values strictly increasing and unique",
        ),
        FormulaContract(
            "m01.recall.true_positive_over_true_support/v1",
            "class=TP_c/(TP_c+FN_c)",
            OptimizationDirection.MAXIMIZE,
            "class",
            "true support of class c",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.ASCENDING_CLASS_INDEX,
            UndefinedPolicy.NO_CLASS_SUPPORT_IS_UNDEFINED,
            finite + "; labels shape N",
        ),
        FormulaContract(
            "m01.macro_recall.unweighted_observed_classes_only/v1",
            "sum(recall_c over supported classes)/number_supported_classes",
            OptimizationDirection.MAXIMIZE,
            "supported class",
            "number of classes with positive true support",
            WeightPolicy.EQUAL_OBSERVED_CLASSES,
            TiePolicy.ASCENDING_CLASS_INDEX,
            UndefinedPolicy.NO_CLASS_SUPPORT_IS_UNDEFINED,
            finite + "; at least one row guarantees at least one supported class",
        ),
        FormulaContract(
            "m01.top_label_ece.15_HF_type7_searchsorted_right/v1",
            "sum_b(n_b/N*abs(mean_confidence_b-accuracy_b))",
            OptimizationDirection.MINIMIZE,
            "top-label confidence row grouped into 15 nominal bins",
            "N rows",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.HF_TYPE7_SEARCHSORTED_RIGHT,
            UndefinedPolicy.EMPTY_NOMINAL_BIN_IS_UNDEFINED,
            finite + "; confidence and correctness shape N",
        ),
        FormulaContract(
            "m01.one_vs_rest_ece.15_HF_type7_searchsorted_right/v1",
            "for each class c: sum_b(n_b/N*abs(mean_p_c_b-frequency_c_b))",
            OptimizationDirection.MINIMIZE,
            "row separately within each class",
            "N rows per class",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.HF_TYPE7_SEARCHSORTED_RIGHT,
            UndefinedPolicy.EMPTY_NOMINAL_BIN_IS_UNDEFINED,
            finite + "; probabilities shape N x K",
        ),
        FormulaContract(
            "m01.one_hot_probability_interval.closed_endpoints.equal_cells/v1",
            "sum_(row,class)(1[lower<=one_hot<=upper])/(N*K)",
            OptimizationDirection.MAXIMIZE,
            "row-class cell",
            "N*K cells separately at levels .50, .80, .95",
            WeightPolicy.EQUAL_ROW_CLASS_CELLS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; lower/upper shape N x K, 0<=lower<=upper<=1",
        ),
        FormulaContract(
            "m02.empirical_crps.equal_members.biased_pair_denominator/v1",
            "row_axis=mean_s|x_s-y|-0.5*mean_(s,t)|x_s-x_t|",
            OptimizationDirection.MINIMIZE,
            "row separately within each axis",
            "N rows per axis; pair mean denominator S^2 including self-pairs",
            WeightPolicy.EQUAL_ROWS_ENSEMBLE_MEMBERS_AND_BIASED_PAIRS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; samples shape N x S x D, S>=1; truth shape N x D",
        ),
        FormulaContract(
            "m02.absolute_ensemble_mean_error_over_positive_oracle_scale/v1",
            "row_axis=abs(mean_s(x_s)-y)/oracle_scale_axis",
            OptimizationDirection.MINIMIZE,
            "row separately within each axis",
            "N rows per axis",
            WeightPolicy.EQUAL_ROWS_AND_ENSEMBLE_MEMBERS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; oracle_scale shape D and strictly positive",
        ),
        FormulaContract(
            "m02.sqrt_mean_squared_ensemble_mean_error_over_oracle_scale/v1",
            "axis=sqrt(sum_row(((mean_s(x_s)-y)/scale)^2)/N)",
            OptimizationDirection.MINIMIZE,
            "row squared error separately within each axis",
            "N rows per axis",
            WeightPolicy.EQUAL_ROWS_AND_ENSEMBLE_MEMBERS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; oracle_scale shape D and strictly positive",
        ),
        FormulaContract(
            "m02.continuous_interval.closed_endpoints.equal_cells/v1",
            "sum_(row,axis)(1[lower<=truth<=upper])/(N*D)",
            OptimizationDirection.MAXIMIZE,
            "row-axis cell",
            "N*D cells separately at levels .50, .80, .95",
            WeightPolicy.EQUAL_ROW_AXIS_CELLS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; lower/upper/truth shape N x D and lower<=upper",
        ),
        FormulaContract(
            "m02.bernoulli_nll.clip_1e-12/v1",
            "row_event=-ln(clip(p,1e-12,1-1e-12)) if event=1 else -ln(clip(1-p,1e-12,1-1e-12))",
            OptimizationDirection.MINIMIZE,
            "row separately within each event",
            "N rows per event",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.LOG_SCORE_CLIPPED,
            finite + "; probabilities/truth shape N x E; truth integer 0/1",
        ),
        FormulaContract(
            "m02.bernoulli_brier.equal_rows/v1",
            "row_event=(p-event_truth)^2",
            OptimizationDirection.MINIMIZE,
            "row separately within each event",
            "N rows per event",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; probabilities/truth shape N x E; truth integer 0/1",
        ),
        FormulaContract(
            "m02.event_reliability.15_HF_type7_searchsorted_right/v1",
            "for each event: sum_b(n_b/N*abs(mean_p_b-event_frequency_b))",
            OptimizationDirection.MINIMIZE,
            "row separately within each event",
            "N rows per event",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.HF_TYPE7_SEARCHSORTED_RIGHT,
            UndefinedPolicy.EMPTY_NOMINAL_BIN_IS_UNDEFINED,
            finite + "; probabilities/truth shape N x E",
        ),
        FormulaContract(
            "m02.energy.euclidean_after_oracle_scale.equal_members.biased_pairs/v1",
            "row=mean_s||x_s/scale-y/scale||_2-0.5*mean_(s,t)||x_s/scale-x_t/scale||_2",
            OptimizationDirection.MINIMIZE,
            "row joint across all axes",
            "N rows; pair mean denominator S^2 including self-pairs",
            WeightPolicy.EQUAL_ROWS_ENSEMBLE_MEMBERS_AND_BIASED_PAIRS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; samples N x S x D, truth N x D, positive scale D",
        ),
        FormulaContract(
            "m02.complete_alive_indicator_brier.equal_rows/v1",
            "row_horizon=(survival_probability-alive_indicator)^2",
            OptimizationDirection.MINIMIZE,
            "row separately within each horizon",
            "N rows per horizon",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite + "; complete alive truth N x H; no censoring",
        ),
        FormulaContract(
            "m02.complete_alive_indicator_nll.clip_1e-12/v1",
            "row_horizon=-ln(clip(S)) if alive else -ln(clip(1-S)); clip=[1e-12,1-1e-12]",
            OptimizationDirection.MINIMIZE,
            "row separately within each horizon",
            "N rows per horizon",
            WeightPolicy.EQUAL_ROWS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.LOG_SCORE_CLIPPED,
            finite + "; complete alive truth N x H; no censoring",
        ),
        FormulaContract(
            "m02.descriptive_survival_brier.equal_row_horizon_cells/v1",
            "sum_(row,horizon)((S-alive)^2)/(N*H)",
            OptimizationDirection.MINIMIZE,
            "row-horizon cell",
            "N*H cells",
            WeightPolicy.EQUAL_ROW_HORIZON_CELLS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.REJECT_INVALID_INPUT,
            finite
            + "; complete alive truth N x H; no censoring; descriptive, not time-integrated",
        ),
        FormulaContract(
            "m02.descriptive_survival_nll.equal_row_horizon_cells.clip_1e-12/v1",
            "sum_(row,horizon)(clipped Bernoulli alive NLL)/(N*H)",
            OptimizationDirection.MINIMIZE,
            "row-horizon cell",
            "N*H cells",
            WeightPolicy.EQUAL_ROW_HORIZON_CELLS,
            TiePolicy.NOT_APPLICABLE,
            UndefinedPolicy.LOG_SCORE_CLIPPED,
            finite
            + "; complete alive truth N x H; no censoring; descriptive, not time-integrated",
        ),
    )
    if len({item.formula_id for item in formulas}) != len(formulas):
        raise AssertionError("formula contract ids must be unique")
    return MetricRuntimeContract(
        benchmark_status=BENCHMARK_STATUS,
        runtime_role=RUNTIME_ROLE,
        freeze_authority=FREEZE_AUTHORITY,
        aggregate_score="forbidden",
        calibration_bins=CALIBRATION_BIN_COUNT,
        interval_levels=INTERVAL_LEVELS,
        interval_endpoints="closed",
        log_base="natural",
        log_score_clip_lower=LOG_SCORE_CLIP_LOWER,
        log_score_clip_upper=LOG_SCORE_CLIP_UPPER,
        probability_simplex_absolute_tolerance=SIMPLEX_ABSOLUTE_TOLERANCE,
        numeric_input_policy=(
            "real finite non-boolean non-empty exact-rank arrays; invalid input "
            "raises ProtocolViolation"
        ),
        semantic_completeness=SEMANTIC_COMPLETENESS,
        blocker_codes=BLOCKER_CODES,
        unimplemented_m02_outputs=UNIMPLEMENTED_M02_OUTPUTS,
        formulas=formulas,
    )
