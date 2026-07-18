from __future__ import annotations

import math

import pytest

from prototype.unified_map.canonical import ProtocolViolation
from prototype.unified_map.pre_freeze_metrics_m05_m08 import (
    BENCHMARK_STATUS,
    COMPOSITE_SCORE_SUPPORTED,
    FREEZE_AUTHORITY_CLAIMED,
    OOD_PROJECTION_OWNER,
    PairMetricProbe,
    PairThresholds,
    OODExample,
    TemporalLeakProbe,
    collision_metrics,
    false_split_metrics,
    ood_metrics,
    temporal_leakage_metrics,
)


def thresholds() -> PairThresholds:
    return PairThresholds(
        epsilon_candidate_same=0.1,
        delta_candidate_split=0.5,
        epsilon_oracle_equivalent=0.1,
        delta_oracle_distinguishable=0.5,
        catastrophic_margin=1.0,
    )


def pair(
    pair_id: str,
    *,
    cohort: str = "main",
    weight: float = 1.0,
    exact: bool = False,
    candidate: float = 0.2,
    oracle: float = 0.2,
    attributable: bool = False,
    danger: float = 0.0,
) -> PairMetricProbe:
    return PairMetricProbe(
        pair_id=pair_id,
        cohort=cohort,
        weight=weight,
        exact_state_hash_equal=exact,
        candidate_distance=candidate,
        oracle_distance=oracle,
        attributable=attributable,
        dangerous_decision_margin=danger,
    )


def test_runtime_is_explicitly_pre_freeze_non_authoritative_and_has_no_score() -> None:
    assert BENCHMARK_STATUS == "PRE-FREEZE"
    assert FREEZE_AUTHORITY_CLAIMED is False
    assert COMPOSITE_SCORE_SUPPORTED is False
    assert OOD_PROJECTION_OWNER == "parent_runner_from_diagnose_and_rollout"


def test_collision_rates_bind_exact_pair_denominators_weights_and_danger() -> None:
    rows = (
        pair(
            "a",
            cohort="c1",
            exact=True,
            candidate=0.05,
            oracle=0.8,
            attributable=True,
            danger=1.2,
        ),
        pair("b", cohort="c1", weight=3, candidate=0.05, oracle=0.6, danger=2),
        pair("c", cohort="c2", weight=2, candidate=0.8, oracle=0.05),
        pair("d", cohort="c2", weight=4, exact=True, candidate=0.2, oracle=0.05),
        # Attributable eligibility is its own exact denominator.  This grey-zone
        # pair is not silently deleted merely because it is not a collision.
        pair("e", cohort="c2", weight=4, candidate=0.2, oracle=0.3, attributable=True),
    )
    result = collision_metrics(rows, thresholds())
    overall = result.overall
    assert overall.oracle_distinguishable_denominator.denominator_count == 2
    assert overall.oracle_distinguishable_denominator.denominator_weight == 4
    assert overall.raw_exact_collision_rate.numerator_count == 1
    assert overall.raw_exact_collision_rate.rate.value == 0.25
    assert overall.functional_near_collision_rate.numerator_count == 2
    assert overall.functional_near_collision_rate.rate.value == 1.0
    assert overall.attributable_pair_denominator.denominator_count == 2
    assert overall.attributable_pair_denominator.denominator_weight == 5
    assert overall.attributable_collision_rate.numerator_count == 1
    assert overall.attributable_collision_rate.rate.value == 0.2
    assert overall.max_missed_oracle_distance.value == 0.8
    assert tuple(event.pair_id for event in overall.dangerous_events) == ("a",)
    assert overall.dangerous_events[0].weight == 1
    assert overall.dangerous_events[0].dangerous_decision_margin == 1.2
    assert [item.cohort for item in result.cohorts] == ["c1", "c2"]
    assert result.cohorts[0].raw_exact_collision_rate.rate.value == 0.25

    # Pair-level evidence and dangerous events are canonical by pair_id, not
    # by caller iteration order.
    assert collision_metrics(tuple(reversed(rows)), thresholds()) == result


def test_false_split_uses_only_oracle_equivalent_pairs_and_reports_max() -> None:
    rows = (
        pair("equiv-split", weight=2, candidate=0.8, oracle=0.05),
        pair("equiv-same-hash", weight=4, exact=True, candidate=0.2, oracle=0.05),
        pair("middle", weight=9, candidate=0.9, oracle=0.3),
        pair("different", weight=20, candidate=0.9, oracle=0.8),
    )
    report = false_split_metrics(rows, thresholds())
    result = report.overall
    assert result.oracle_equivalent_denominator.denominator_count == 2
    assert result.oracle_equivalent_denominator.denominator_weight == 6
    assert result.functional_false_split_rate.numerator_count == 1
    assert result.functional_false_split_rate.rate.value == pytest.approx(1 / 3)
    assert result.structural_redundancy_count == 1
    assert result.structural_redundancy_weight == 2
    assert result.max_spurious_candidate_distance.value == 0.8
    assert false_split_metrics(tuple(reversed(rows)), thresholds()) == report


def test_pair_threshold_equalities_are_inclusive_and_grey_zone_is_neither() -> None:
    rows = (
        pair("collision", candidate=0.1, oracle=0.5, attributable=True, danger=1.0),
        pair("split", candidate=0.5, oracle=0.1),
        pair("grey", candidate=0.3, oracle=0.3),
    )
    collision = collision_metrics(rows, thresholds()).pair_decisions
    false_split = false_split_metrics(rows, thresholds()).pair_decisions
    by_id = {item.pair_id: item for item in collision}
    split_by_id = {item.pair_id: item for item in false_split}
    assert by_id["collision"].attributable_dangerous_collision
    assert split_by_id["split"].functional_false_split
    assert not by_id["grey"].functional_near_collision
    assert not split_by_id["grey"].functional_false_split


def ood_rows() -> tuple[OODExample, ...]:
    return (
        OODExample("k1", "mixed", 1, False, 0.1, False, 0.0, 0.0),
        OODExample("k2", "mixed", 1, False, 0.8, True, 1.0, 0.0),
        OODExample("o1", "mixed", 1, True, 0.9, True, 0.0, 2.0),
        OODExample("o2", "mixed", 1, True, 0.8, False, 1.0, 1.2),
    )


def test_ood_metrics_have_tie_invariant_hand_calculated_values() -> None:
    result = ood_metrics(ood_rows(), frozen_low_fpr=0.1, catastrophic_margin=1.0)
    overall = result.overall
    assert result.label_owner == "runner_or_judge_runtime_truth"
    assert result.projection_owner == "parent_runner_from_diagnose_and_rollout"
    assert overall.auroc.value == 0.875
    assert overall.auprc.value == pytest.approx(5 / 6)
    assert overall.fpr_at_95_tpr.value == 0.5
    assert overall.tpr_at_frozen_low_fpr.value == 0.5
    # Only actual non-abstentions enter the accepted set.  All four examples
    # remain in the coverage denominator, so achieved coverage is 1/2 and the
    # right-continuous raw area is (0.50-0.25) * 0.50 = 1/8.
    assert overall.risk_coverage_aurc.value == pytest.approx(1 / 8)
    assert overall.risk_coverage_final_coverage == 0.5
    assert "actual_nonabstain_coverage" in overall.risk_coverage_aurc_convention
    assert overall.known_case_coverage.denominator_count == 2
    assert overall.known_case_coverage.rate.value == 0.5
    assert overall.ood_abstention_rate.rate.value == 0.5
    assert overall.unknown_probability_brier.value == pytest.approx(0.175)
    expected_nll = -(math.log(0.9) + math.log(0.2) + math.log(0.9) + math.log(0.8)) / 4
    assert overall.unknown_probability_nll.value == pytest.approx(expected_nll)
    assert overall.unknown_probability_nll_clip == 1e-12
    assert (
        overall.unknown_probability_nll_convention
        == "binary_log_score_after_clipping_probability_to_[1e-12,1-1e-12]"
    )
    assert overall.unsafe_nonabstain_rate.denominator_count == 2
    assert overall.unsafe_nonabstain_rate.rate.value == 0.5
    assert overall.nonabstain_ood_mean_regret.value == 1.2
    assert overall.nonabstain_ood_max_regret.value == 1.2

    permuted = ood_metrics(
        tuple(reversed(ood_rows())), frozen_low_fpr=0.1, catastrophic_margin=1.0
    )
    assert permuted.overall.auroc == overall.auroc
    assert permuted.overall.auprc == overall.auprc
    assert permuted.overall.fpr_at_95_tpr == overall.fpr_at_95_tpr
    assert permuted.overall.risk_coverage_aurc == overall.risk_coverage_aurc


def test_ood_weighting_changes_exposures_without_splitting_ties() -> None:
    rows = (
        OODExample("p", "x", 2, True, 0.5, False, 1.0, 2.0),
        OODExample("n", "x", 1, False, 0.5, False, 0.0, 0.0),
    )
    result = ood_metrics(rows, frozen_low_fpr=0.0, catastrophic_margin=1.0).overall
    assert result.auroc.value == 0.5
    assert result.auprc.value == pytest.approx(2 / 3)
    assert result.fpr_at_95_tpr.value == 1.0
    assert result.tpr_at_frozen_low_fpr.value == 0.0
    assert result.threshold_curve[0].true_positive_rate == 1.0
    assert result.threshold_curve[0].false_positive_rate == 1.0
    assert result.risk_coverage_aurc.value == pytest.approx(2 / 3)
    assert result.risk_coverage_final_coverage == 1.0


def test_ood_all_abstain_has_zero_coverage_but_undefined_aurc() -> None:
    rows = (
        OODExample("known", "all-abstain", 1, False, 0.2, True, 0.5, 0),
        OODExample("ood", "all-abstain", 2, True, 0.8, True, 1.0, 3),
    )
    result = ood_metrics(rows, frozen_low_fpr=0.05, catastrophic_margin=1).overall
    assert result.risk_coverage_final_coverage == 0.0
    assert result.risk_coverage_aurc.value is None
    assert result.risk_coverage_aurc.reason == "no_nonabstain_coverage"
    assert result.risk_coverage_curve == ()
    assert result.known_case_coverage.rate.value == 0.0
    assert result.ood_abstention_rate.rate.value == 1.0


def test_ood_single_class_and_empty_are_typed_undefined_not_nan() -> None:
    known_only = ood_metrics(
        (OODExample("k", "known", 1, False, 0.2, False, 0, 0),),
        frozen_low_fpr=0.05,
        catastrophic_margin=1,
    ).overall
    assert known_only.auroc.value is None
    assert known_only.auroc.reason == "single_class_discrimination"
    assert known_only.auprc.value is None
    assert known_only.fpr_at_95_tpr.value is None
    assert known_only.known_case_coverage.rate.value == 1.0
    assert known_only.ood_abstention_rate.rate.value is None
    assert known_only.ood_abstention_rate.rate.reason == "empty_denominator"

    empty = ood_metrics((), frozen_low_fpr=0.05, catastrophic_margin=1).overall
    assert empty.total_count == 0
    assert empty.unknown_probability_brier.value is None
    assert empty.unknown_probability_nll.value is None
    assert empty.risk_coverage_aurc.reason == "empty_denominator"


def temporal_probe(
    probe_id: str,
    *,
    weight: float = 1.0,
    same_prefix: bool = True,
    state_equal: bool = True,
    prediction_equal: bool = True,
    divergence: float = 0.0,
    boundary: tuple[bool, bool] | None = None,
    old_cut_stable: bool | None = None,
) -> TemporalLeakProbe:
    old = {}
    if old_cut_stable is not None:
        old = {
            "old_cut_state_hash_before": "old-a",
            "old_cut_state_hash_after": "old-a" if old_cut_stable else "old-b",
            "old_cut_prediction_before": b"old-pred-a",
            "old_cut_prediction_after": (
                b"old-pred-a" if old_cut_stable else b"old-pred-b"
            ),
        }
    return TemporalLeakProbe(
        probe_id=probe_id,
        cohort="time",
        weight=weight,
        prefix_bytes_a=b"prefix-a",
        prefix_bytes_b=b"prefix-a" if same_prefix else b"prefix-b",
        state_hash_a="state-a",
        state_hash_b="state-a" if state_equal else "state-b",
        prediction_bytes_a=b"prediction-a",
        prediction_bytes_b=(b"prediction-a" if prediction_equal else b"prediction-b"),
        preavailability_output_divergence=divergence,
        boundary_expected_visible=None if boundary is None else boundary[0],
        boundary_observed_visible=None if boundary is None else boundary[1],
        **old,
    )


def test_temporal_leakage_uses_exact_prefix_and_output_bytes() -> None:
    rows = (
        temporal_probe(
            "state-leak",
            state_equal=False,
            boundary=(True, False),
            old_cut_stable=True,
        ),
        temporal_probe(
            "prediction-leak",
            weight=3,
            prediction_equal=False,
            divergence=0.7,
            boundary=(False, False),
            old_cut_stable=False,
        ),
        temporal_probe(
            "excluded-nonidentical-prefix",
            weight=5,
            same_prefix=False,
            state_equal=False,
            prediction_equal=False,
            divergence=99,
        ),
    )
    result = temporal_leakage_metrics(rows).overall
    assert result.identical_prefix_denominator.denominator_count == 2
    assert result.identical_prefix_denominator.denominator_weight == 4
    assert result.state_leak_rate.rate.value == 0.25
    assert result.prediction_leak_rate.rate.value == 0.75
    assert result.max_preavailability_output_divergence.value == 0.7
    assert result.boundary_exposure_count == 2
    assert result.boundary_exposure_weight == 4
    assert result.boundary_error_count == 1
    assert result.boundary_error_weight == 1
    assert result.old_cut_exposure_count == 2
    assert result.old_cut_exposure_weight == 4
    assert result.old_cut_instability_count == 1
    assert result.old_cut_instability_weight == 3


def test_temporal_empty_identical_prefix_denominator_is_typed_undefined() -> None:
    result = temporal_leakage_metrics(
        (temporal_probe("different", same_prefix=False),)
    ).overall
    assert result.state_leak_rate.rate.value is None
    assert result.prediction_leak_rate.rate.value is None
    assert result.max_preavailability_output_divergence.value is None
    assert (
        result.max_preavailability_output_divergence.reason
        == "empty_identical_prefix_denominator"
    )


@pytest.mark.parametrize(
    "constructor, message",
    [
        (
            lambda: PairThresholds(True, 0.5, 0.1, 0.5, 1.0),
            "excluding bool",
        ),
        (
            lambda: pair("bad", candidate=float("nan")),
            "must be finite",
        ),
        (
            lambda: pair("bad", exact=1),
            "must be bool",
        ),
        (
            lambda: OODExample("bad", "x", 1, 1, 0.5, False, 0, 0),
            "must be bool",
        ),
        (
            lambda: OODExample("bad", "x", 1, False, float("inf"), False, 0, 0),
            "must be finite",
        ),
        (
            lambda: TemporalLeakProbe(
                "bad",
                "x",
                1,
                b"a",
                b"a",
                "a",
                "a",
                b"a",
                b"a",
                0,
                boundary_expected_visible=True,
            ),
            "must be paired",
        ),
    ],
)
def test_invalid_nan_bool_and_incomplete_evidence_fail_closed(
    constructor, message: str
) -> None:
    with pytest.raises(ProtocolViolation, match=message):
        constructor()


def test_duplicate_runtime_identifiers_fail_closed() -> None:
    with pytest.raises(ProtocolViolation, match="identifiers must be unique"):
        collision_metrics((pair("p"), pair("p")), thresholds())
    with pytest.raises(ProtocolViolation, match="identifiers must be unique"):
        ood_metrics(
            (
                OODExample("x", "c", 1, False, 0.1, False, 0, 0),
                OODExample("x", "c", 1, True, 0.9, True, 0, 0),
            ),
            frozen_low_fpr=0.05,
            catastrophic_margin=1,
        )


def test_threshold_order_and_call_parameters_fail_closed() -> None:
    with pytest.raises(ProtocolViolation, match="below delta_candidate_split"):
        PairThresholds(0.5, 0.5, 0.1, 0.5, 1)
    with pytest.raises(ProtocolViolation, match="below delta_oracle"):
        PairThresholds(0.1, 0.5, 0.5, 0.5, 1)
    with pytest.raises(ProtocolViolation, match="excluding bool"):
        ood_metrics(ood_rows(), frozen_low_fpr=True, catastrophic_margin=1)
    with pytest.raises(ProtocolViolation, match="non-negative"):
        ood_metrics(ood_rows(), frozen_low_fpr=0.05, catastrophic_margin=-1)
