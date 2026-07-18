from __future__ import annotations

import math

import numpy as np
import pytest

from prototype.unified_map.canonical import ProtocolViolation
from prototype.unified_map.metrics import benchmark_v1_diagnostic_metrics
from prototype.unified_map.metrics_diagnosis_forecast import (
    CALIBRATION_BIN_COUNT,
    FREEZE_AUTHORITY,
    LOG_SCORE_CLIP_LOWER,
    LOG_SCORE_CLIP_UPPER,
    RUNTIME_ROLE,
    DiagnosisTruthBranch,
    IntervalInput,
    MetricStatus,
    closed_survival_metrics_m02,
    deterministic_continuous_metrics_m02,
    diagnosis_metrics_m01,
    discrete_event_metrics_m02,
    ensemble_continuous_metrics_m02,
    joint_energy_score_m02,
    oracle_posterior_diagnosis_metrics_m01,
    runtime_contract,
)


def _intervals(lower: np.ndarray, upper: np.ndarray) -> tuple[IntervalInput, ...]:
    return tuple(
        IntervalInput(level, lower.copy(), upper.copy()) for level in (0.50, 0.80, 0.95)
    )


def _diagnosis_fixture() -> tuple[np.ndarray, np.ndarray, tuple[IntervalInput, ...]]:
    probabilities = np.array(
        [
            [0.7, 0.2, 0.1],
            [0.2, 0.5, 0.3],
            [0.4, 0.4, 0.2],
            [0.1, 0.2, 0.7],
        ]
    )
    labels = np.array([0, 2, 1, 2])
    return (
        probabilities,
        labels,
        _intervals(np.zeros_like(probabilities), np.ones_like(probabilities)),
    )


def test_m01_hand_calculated_scores_grains_and_tie_policy() -> None:
    probabilities, labels, intervals = _diagnosis_fixture()
    report = diagnosis_metrics_m01(
        probabilities,
        labels,
        top_k=(2, 3),
        probability_intervals=intervals,
    )

    assert report.runtime_role == "runtime_only"
    assert report.freeze_authority == "not_claimed"
    assert report.multiclass_nll.value == pytest.approx(
        -math.log(0.7 * 0.3 * 0.4 * 0.7) / 4
    )
    assert report.multiclass_nll.denominator == 4
    assert len(report.multiclass_nll.grains) == 4
    assert report.multiclass_brier.value == pytest.approx(0.405)
    assert report.top1_accuracy.value == pytest.approx(0.5)
    assert [item.result.value for item in report.topk_accuracy] == [1.0, 1.0]

    # Probability tie in row 2 is resolved by ascending class index, so class 0
    # wins over the true class 1.
    assert report.top1_accuracy.grains[2].value == 0.0
    assert [item.result.value for item in report.recall_by_class] == [1.0, 0.0, 0.5]
    assert report.macro_recall.value == pytest.approx(0.5)
    assert report.macro_recall.denominator == 3

    # Confidence values are .7, .5, .4, .7.  The .7 tie is one atomic bin.
    assert report.top_label_calibration.ece == pytest.approx(0.375)
    nonempty = [
        bin_value for bin_value in report.top_label_calibration.bins if bin_value.count
    ]
    assert len(report.top_label_calibration.bins) == CALIBRATION_BIN_COUNT
    assert sorted(bin_value.count for bin_value in nonempty) == [1, 1, 2]
    tied_bin = next(bin_value for bin_value in nonempty if bin_value.count == 2)
    assert tied_bin.minimum_probability == pytest.approx(0.7)
    assert tied_bin.maximum_probability == pytest.approx(0.7)
    assert sum(bin_value.count for bin_value in nonempty) == 4
    assert all(
        item.result.value == 1.0 for item in report.probability_interval_coverage
    )
    assert all(
        item.result.denominator == 12 for item in report.probability_interval_coverage
    )


def test_m01_absent_class_is_undefined_and_log_score_uses_benchmark_clip() -> None:
    probabilities = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    labels = np.array([1, 1])
    report = diagnosis_metrics_m01(
        probabilities,
        labels,
        top_k=(2,),
        probability_intervals=_intervals(
            np.zeros_like(probabilities), np.ones_like(probabilities)
        ),
    )

    expected = (-math.log(LOG_SCORE_CLIP_LOWER) - math.log(LOG_SCORE_CLIP_UPPER)) / 2
    existing_target = benchmark_v1_diagnostic_metrics(probabilities, labels)
    assert report.truth_branch is DiagnosisTruthBranch.REALIZED_LABEL
    assert report.multiclass_nll.status is MetricStatus.DEFINED
    assert report.multiclass_nll.value == pytest.approx(expected)
    assert report.multiclass_nll.value == pytest.approx(existing_target.log_loss)
    assert report.multiclass_nll.denominator == 2
    assert report.multiclass_nll.grains[0].value == pytest.approx(
        -math.log(LOG_SCORE_CLIP_LOWER)
    )
    assert report.recall_by_class[0].result.status is MetricStatus.UNDEFINED_NO_SUPPORT
    assert report.recall_by_class[0].result.denominator == 0
    assert report.recall_by_class[2].result.status is MetricStatus.UNDEFINED_NO_SUPPORT
    assert report.macro_recall.denominator == 1


def test_m01_row_permutation_and_equal_confidence_ties_are_deterministic() -> None:
    probabilities = np.full((8, 2), 0.5)
    labels = np.array([0, 1, 1, 0, 1, 0, 0, 1])
    intervals = _intervals(np.zeros_like(probabilities), np.ones_like(probabilities))
    baseline = diagnosis_metrics_m01(
        probabilities, labels, top_k=(2,), probability_intervals=intervals
    )
    order = np.array([6, 2, 0, 7, 4, 1, 5, 3])
    permuted = diagnosis_metrics_m01(
        probabilities[order],
        labels[order],
        top_k=(2,),
        probability_intervals=_intervals(
            np.zeros_like(probabilities), np.ones_like(probabilities)
        ),
    )

    assert baseline.multiclass_nll.value == permuted.multiclass_nll.value
    assert baseline.multiclass_brier.value == permuted.multiclass_brier.value
    assert baseline.top1_accuracy.value == permuted.top1_accuracy.value
    assert baseline.top_label_calibration.ece == permuted.top_label_calibration.ece
    assert [item.count for item in baseline.top_label_calibration.bins] == [
        item.count for item in permuted.top_label_calibration.bins
    ]
    assert sum(item.count > 0 for item in baseline.top_label_calibration.bins) == 1


def test_m01_ece_matches_existing_hf_type7_right_search_target() -> None:
    probabilities, labels, intervals = _diagnosis_fixture()
    report = diagnosis_metrics_m01(
        probabilities, labels, top_k=(2,), probability_intervals=intervals
    )
    legacy_target = benchmark_v1_diagnostic_metrics(probabilities, labels)
    confidence = np.max(probabilities, axis=1)
    edges = np.quantile(
        confidence, np.arange(1, 15, dtype=np.float64) / 15, method="linear"
    )
    assignments = np.searchsorted(edges, confidence, side="right")

    assert report.top_label_calibration.ece == pytest.approx(
        legacy_target.expected_calibration_error
    )
    assert assignments.tolist() == [14, 5, 0, 14]
    assert [item.count for item in report.top_label_calibration.bins] == [
        int(np.sum(assignments == index)) for index in range(15)
    ]


def test_m01_soft_oracle_posterior_primary_scores_are_not_realized_labels() -> None:
    predicted = np.array([[0.6, 0.4], [0.0, 1.0]])
    oracle = np.array([[0.25, 0.75], [0.2, 0.8]])
    report = oracle_posterior_diagnosis_metrics_m01(predicted, oracle)

    expected_nll = (
        -0.25 * math.log(0.6)
        - 0.75 * math.log(0.4)
        - 0.2 * math.log(LOG_SCORE_CLIP_LOWER)
        - 0.8 * math.log(LOG_SCORE_CLIP_UPPER)
    ) / 2
    assert report.truth_branch is DiagnosisTruthBranch.ORACLE_POSTERIOR
    assert report.posterior_cross_entropy_nll.value == pytest.approx(expected_nll)
    assert report.posterior_cross_entropy_nll.denominator == 2
    assert report.posterior_multiclass_brier.value == pytest.approx(0.1625)
    assert len(report.posterior_multiclass_brier.grains) == 2


@pytest.mark.parametrize(
    ("predicted", "oracle"),
    [
        ([[0.5, 0.5]], [[0.2, 0.3]]),
        ([[0.5, 0.5]], [[0.2, 0.3, 0.5]]),
        ([[0.5, True]], [[0.5, 0.5]]),
        ([[0.5, 0.5]], [[False, 1.0]]),
    ],
)
def test_m01_soft_oracle_posterior_rejects_open_or_mixed_bool_input(
    predicted: object, oracle: object
) -> None:
    with pytest.raises(ProtocolViolation):
        oracle_posterior_diagnosis_metrics_m01(predicted, oracle)


@pytest.mark.parametrize(
    ("probabilities", "labels", "top_k"),
    [
        ([], [], (2,)),
        ([[0.5, 0.5]], [True], (2,)),
        ([[True, False]], [0], (2,)),
        ([[False, 1.0]], [1], (2,)),
        ([[0.5, 0.5]], [0, True], (2,)),
        ([[0.5, float("nan")]], [0], (2,)),
        ([[0.5, 0.6]], [0], (2,)),
        ([[0.5, 0.5]], [2], (2,)),
        ([[0.5, 0.5]], [0], (1,)),
        ([[0.5, 0.5]], [0], (2, 2)),
    ],
)
def test_m01_rejects_empty_bool_nan_shape_simplex_label_and_topk_drift(
    probabilities: object, labels: object, top_k: tuple[int, ...]
) -> None:
    array = np.asarray(probabilities)
    shape = array.shape if array.ndim == 2 else (1, 2)
    intervals = _intervals(np.zeros(shape), np.ones(shape))
    with pytest.raises(ProtocolViolation):
        diagnosis_metrics_m01(
            probabilities,
            labels,
            top_k=top_k,
            probability_intervals=intervals,
        )


def test_m01_rejects_interval_shape_order_bounds_and_nonfinite_values() -> None:
    probabilities = np.array([[0.5, 0.5]])
    labels = np.array([0])
    invalid = (
        IntervalInput(0.80, np.zeros((1, 2)), np.ones((1, 2))),
        IntervalInput(0.50, np.zeros((1, 2)), np.ones((1, 2))),
        IntervalInput(0.95, np.zeros((1, 2)), np.ones((1, 2))),
    )
    with pytest.raises(ProtocolViolation):
        diagnosis_metrics_m01(
            probabilities, labels, top_k=(2,), probability_intervals=invalid
        )
    mixed_boolean = (
        IntervalInput(0.50, [[False, 0.0]], [[1.0, 1.0]]),
        IntervalInput(0.80, [[0.0, 0.0]], [[1.0, 1.0]]),
        IntervalInput(0.95, [[0.0, 0.0]], [[1.0, 1.0]]),
    )
    with pytest.raises(ProtocolViolation):
        diagnosis_metrics_m01(
            probabilities,
            labels,
            top_k=(2,),
            probability_intervals=mixed_boolean,
        )
    invalid = _intervals(np.zeros((1, 3)), np.ones((1, 3)))
    with pytest.raises(ProtocolViolation):
        diagnosis_metrics_m01(
            probabilities, labels, top_k=(2,), probability_intervals=invalid
        )
    invalid = _intervals(np.array([[0.0, 0.8]]), np.array([[1.0, 0.2]]))
    with pytest.raises(ProtocolViolation):
        diagnosis_metrics_m01(
            probabilities, labels, top_k=(2,), probability_intervals=invalid
        )


def test_ragged_numeric_and_integer_inputs_fail_closed_as_protocol_violations() -> None:
    with pytest.raises(ProtocolViolation):
        diagnosis_metrics_m01(
            [[0.5, 0.5], [1.0]],
            [0, 0],
            top_k=(2,),
            probability_intervals=_intervals(np.zeros((2, 2)), np.ones((2, 2))),
        )

    with pytest.raises(ProtocolViolation):
        deterministic_continuous_metrics_m02(
            [[0.0, 1.0], [2.0, 3.0]],
            [[0.0, 1.0], [2.0]],
            [1.0, 1.0],
            intervals=_intervals(np.zeros((2, 2)), np.ones((2, 2))),
        )

    with pytest.raises(ProtocolViolation):
        discrete_event_metrics_m02(
            [[0.5, 0.5], [0.4, 0.6]],
            [[0, 1], [1]],
        )


def test_m02_deterministic_crps_normalized_errors_and_interval_coverage() -> None:
    prediction = np.array([[2.0, 4.0], [0.0, 8.0]])
    truth = np.array([[1.0, 2.0], [2.0, 4.0]])
    report = deterministic_continuous_metrics_m02(
        prediction,
        truth,
        np.array([2.0, 2.0]),
        intervals=_intervals(truth.copy(), truth.copy()),
    )

    assert report.ensemble_size == 1
    assert [item.result.value for item in report.crps_by_axis] == [1.5, 3.0]
    assert [
        item.result.value for item in report.oracle_scale_normalized_mae_by_axis
    ] == [0.75, 1.5]
    assert report.oracle_scale_normalized_rmse_by_axis[0].result.value == pytest.approx(
        math.sqrt(0.625)
    )
    assert report.oracle_scale_normalized_rmse_by_axis[1].result.value == pytest.approx(
        math.sqrt(2.5)
    )
    assert all(item.result.denominator == 2 for item in report.crps_by_axis)
    assert all(item.result.value == 1.0 for item in report.interval_coverage)
    assert all(item.result.denominator == 4 for item in report.interval_coverage)


def test_m02_ensemble_crps_and_joint_energy_are_hand_calculated() -> None:
    samples = np.array([[[0.0], [2.0]]])
    truth = np.array([[1.0]])
    intervals = _intervals(np.array([[0.0]]), np.array([[2.0]]))
    continuous = ensemble_continuous_metrics_m02(
        samples, truth, np.array([1.0]), intervals=intervals
    )
    energy = joint_energy_score_m02(samples, truth, np.array([1.0]))

    assert continuous.crps_by_axis[0].result.value == pytest.approx(0.5)
    assert continuous.oracle_scale_normalized_mae_by_axis[0].result.value == 0.0
    assert energy.normalized_joint_energy_score.value == pytest.approx(0.5)
    assert energy.normalized_joint_energy_score.denominator == 1
    assert len(energy.normalized_joint_energy_score.grains) == 1


def test_m02_discrete_event_scores_reliability_and_clipped_log_score() -> None:
    report = discrete_event_metrics_m02(
        np.array([[0.8, 0.2], [0.5, 0.0]]),
        np.array([[1, 0], [0, 1]]),
    )

    assert report.nll_by_event[0].result.value == pytest.approx(
        (-math.log(0.8) - math.log(0.5)) / 2
    )
    assert report.brier_by_event[0].result.value == pytest.approx(0.145)
    assert report.nll_by_event[1].result.status is MetricStatus.DEFINED
    assert report.nll_by_event[1].result.value == pytest.approx(
        (-math.log(0.8) - math.log(LOG_SCORE_CLIP_LOWER)) / 2
    )
    assert report.brier_by_event[1].result.value == pytest.approx(0.52)
    assert all(
        item.calibration.denominator == 2 for item in report.reliability_by_event
    )
    assert all(len(item.calibration.bins) == 15 for item in report.reliability_by_event)


def test_m02_closed_survival_scores_are_hand_calculated_and_horizon_grained() -> None:
    probabilities = np.array([[0.9, 0.6], [0.8, 0.2]])
    alive = np.array([[1, 0], [1, 0]])
    report = closed_survival_metrics_m02(probabilities, alive, np.array([1.0, 2.0]))

    assert report.descriptive_equal_horizon_mean_brier.value == pytest.approx(0.1125)
    assert report.descriptive_equal_horizon_mean_brier.denominator == 4
    assert report.descriptive_equal_horizon_mean_nll.value == pytest.approx(
        (-math.log(0.9) - math.log(0.4) - math.log(0.8) - math.log(0.8)) / 4
    )
    assert [item.horizon for item in report.brier_by_horizon] == [1.0, 2.0]
    assert all(item.result.denominator == 2 for item in report.brier_by_horizon)
    assert (
        report.time_integrated_brier.status
        is MetricStatus.UNAVAILABLE_UNRESOLVED_SEMANTICS
    )
    assert report.time_integrated_brier.blocker_code == "UCM-METRIC-B007"


def test_m02_unequal_horizons_do_not_masquerade_as_time_integrated_scores() -> None:
    probabilities = np.array([[0.9, 0.6, 0.2]])
    alive = np.array([[1, 1, 0]])
    report = closed_survival_metrics_m02(
        probabilities, alive, np.array([1.0, 3.0, 10.0])
    )

    expected_equal_horizon_brier = (0.01 + 0.16 + 0.04) / 3
    assert report.descriptive_equal_horizon_mean_brier.value == pytest.approx(
        expected_equal_horizon_brier
    )
    assert report.time_integrated_brier.status is (
        MetricStatus.UNAVAILABLE_UNRESOLVED_SEMANTICS
    )
    assert report.time_integrated_nll.status is (
        MetricStatus.UNAVAILABLE_UNRESOLVED_SEMANTICS
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda: deterministic_continuous_metrics_m02(
            [[True]],
            [[0.0]],
            [1.0],
            intervals=_intervals(np.zeros((1, 1)), np.ones((1, 1))),
        ),
        lambda: deterministic_continuous_metrics_m02(
            [[0.0, True]],
            [[0.0, 0.0]],
            [1.0, 1.0],
            intervals=_intervals(np.zeros((1, 2)), np.ones((1, 2))),
        ),
        lambda: ensemble_continuous_metrics_m02(
            np.empty((1, 0, 1)),
            [[0.0]],
            [1.0],
            intervals=_intervals(np.zeros((1, 1)), np.ones((1, 1))),
        ),
        lambda: ensemble_continuous_metrics_m02(
            [[[float("nan")]]],
            [[0.0]],
            [1.0],
            intervals=_intervals(np.zeros((1, 1)), np.ones((1, 1))),
        ),
        lambda: deterministic_continuous_metrics_m02(
            [[0.0]],
            [[0.0]],
            [0.0],
            intervals=_intervals(np.zeros((1, 1)), np.ones((1, 1))),
        ),
        lambda: joint_energy_score_m02([[[0.0, 1.0]]], [[0.0]], [1.0, 1.0]),
        lambda: discrete_event_metrics_m02([[0.5]], [[True]]),
        lambda: discrete_event_metrics_m02([[0.5, True]], [[0, 1]]),
        lambda: discrete_event_metrics_m02([[1.2]], [[1]]),
        lambda: discrete_event_metrics_m02([[0.5]], [[2]]),
        lambda: closed_survival_metrics_m02([[0.8, 0.9]], [[1, 1]], [1.0, 2.0]),
        lambda: closed_survival_metrics_m02([[0.8, 0.2]], [[0, 1]], [1.0, 2.0]),
        lambda: closed_survival_metrics_m02([[0.8, 0.2]], [[1, 0]], [2.0, 1.0]),
    ],
)
def test_m02_rejects_bool_empty_nan_nonpositive_scale_shape_and_semantic_drift(
    call: object,
) -> None:
    with pytest.raises(ProtocolViolation):
        call()  # type: ignore[operator]


def test_m02_row_and_ensemble_permutations_are_deterministic() -> None:
    samples = np.array(
        [
            [[0.0, 1.0], [2.0, 3.0], [1.0, 2.0]],
            [[4.0, 2.0], [2.0, 0.0], [3.0, 1.0]],
        ]
    )
    truth = np.array([[1.0, 2.0], [3.0, 1.0]])
    intervals = _intervals(np.zeros((2, 2)), np.full((2, 2), 4.0))
    baseline = ensemble_continuous_metrics_m02(
        samples, truth, np.array([1.0, 2.0]), intervals=intervals
    )
    permuted = ensemble_continuous_metrics_m02(
        samples[::-1, ::-1],
        truth[::-1],
        np.array([1.0, 2.0]),
        intervals=intervals,
    )
    baseline_energy = joint_energy_score_m02(samples, truth, np.array([1.0, 2.0]))
    permuted_energy = joint_energy_score_m02(
        samples[::-1, ::-1], truth[::-1], np.array([1.0, 2.0])
    )

    assert [item.result.value for item in baseline.crps_by_axis] == pytest.approx(
        [item.result.value for item in permuted.crps_by_axis]
    )
    assert baseline_energy.normalized_joint_energy_score.value == pytest.approx(
        permuted_energy.normalized_joint_energy_score.value
    )


@pytest.mark.parametrize(
    "call",
    [
        lambda: deterministic_continuous_metrics_m02(
            [[1e308]],
            [[-1e308]],
            [1.0],
            intervals=_intervals(np.array([[-1e308]]), np.array([[1e308]])),
        ),
        lambda: deterministic_continuous_metrics_m02(
            [[1e200]],
            [[0.0]],
            [1.0],
            intervals=_intervals(np.array([[0.0]]), np.array([[1e200]])),
        ),
        lambda: deterministic_continuous_metrics_m02(
            [[1e308], [1e308]],
            [[0.0], [0.0]],
            [1.0],
            intervals=_intervals(
                np.array([[0.0], [0.0]]), np.array([[1e308], [1e308]])
            ),
        ),
        lambda: deterministic_continuous_metrics_m02(
            [[1.0]],
            [[0.0]],
            [np.nextafter(0.0, 1.0)],
            intervals=_intervals(np.array([[0.0]]), np.array([[1.0]])),
        ),
        lambda: joint_energy_score_m02([[[1e308]]], [[-1e308]], [1.0]),
        lambda: joint_energy_score_m02([[[1.0]]], [[0.0]], [np.nextafter(0.0, 1.0)]),
    ],
)
def test_m02_derived_overflow_and_tiny_scale_fail_closed(call: object) -> None:
    with pytest.raises(ProtocolViolation):
        call()  # type: ignore[operator]


def test_runtime_contract_forbids_aggregate_and_claims_no_freeze_authority() -> None:
    contract = runtime_contract()
    assert contract.benchmark_status == "PRE-FREEZE"
    assert contract.runtime_role == RUNTIME_ROLE
    assert contract.freeze_authority == FREEZE_AUTHORITY
    assert contract.aggregate_score == "forbidden"
    assert contract.calibration_bins == 15
    assert contract.interval_levels == (0.50, 0.80, 0.95)
    assert contract.log_score_clip_lower == 1e-12
    assert contract.log_score_clip_upper == 1.0 - 1e-12
    assert len(contract.formulas) == 23
    assert len({item.formula_id for item in contract.formulas}) == 23
    assert all(item.denominator for item in contract.formulas)
    assert all(item.finite_shape_policy for item in contract.formulas)
    assert contract.semantic_completeness == "partial_M01_M02_runtime_primitives_only"
    assert set(contract.blocker_codes) == {
        "UCM-METRIC-B002",
        "UCM-METRIC-B003",
        "UCM-METRIC-B004",
        "UCM-METRIC-B007",
    }
    assert "no_new_action_policy_slice" in contract.unimplemented_m02_outputs
    assert "continue_current_policy_slice" in contract.unimplemented_m02_outputs
    assert "fixed_time_utility_distribution_error" in contract.unimplemented_m02_outputs
    assert (
        "calibration_slope_intercept_by_horizon" in contract.unimplemented_m02_outputs
    )

    continuous_formula_ids = {
        "m02.empirical_crps.equal_members.biased_pair_denominator/v1",
        "m02.absolute_ensemble_mean_error_over_positive_oracle_scale/v1",
        "m02.sqrt_mean_squared_ensemble_mean_error_over_oracle_scale/v1",
        "m02.continuous_interval.closed_endpoints.equal_cells/v1",
        "m02.energy.euclidean_after_oracle_scale.equal_members.biased_pairs/v1",
    }
    by_id = {item.formula_id: item for item in contract.formulas}
    assert continuous_formula_ids < set(by_id)
    for formula_id in continuous_formula_ids:
        policy = by_id[formula_id].finite_shape_policy
        assert "arbitrary real finite" in policy
        assert "probability values in [0,1]" not in policy
    for formula_id, formula in by_id.items():
        if formula_id not in continuous_formula_ids:
            assert "probability values in [0,1]" in formula.finite_shape_policy
