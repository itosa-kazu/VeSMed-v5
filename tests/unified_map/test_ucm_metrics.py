from __future__ import annotations

import math

import pytest

from prototype.unified_map.canonical import ProtocolViolation
from prototype.unified_map.metrics import (
    InformationRelation,
    PairProbe,
    binary_roc_auc,
    classify_pair,
    diagnostic_metrics,
    trajectory_metrics,
    treatment_regret,
)


def test_diagnostic_proper_scores_reward_correct_calibrated_predictions() -> None:
    good = diagnostic_metrics([[0.9, 0.1], [0.2, 0.8]], [0, 1], calibration_bins=5)
    bad = diagnostic_metrics([[0.1, 0.9], [0.8, 0.2]], [0, 1], calibration_bins=5)
    assert good.accuracy == 1.0
    assert good.log_loss < bad.log_loss
    assert good.multiclass_brier < bad.multiclass_brier


def test_diagnostic_probabilities_must_be_normalized() -> None:
    with pytest.raises(ProtocolViolation, match="sum to one"):
        diagnostic_metrics([[0.9, 0.9]], [0])


def test_trajectory_metrics_have_zero_error_for_exact_mean() -> None:
    result = trajectory_metrics(
        [[1.0, 2.0], [2.0, 3.0]],
        [[1.0, 2.0], [2.0, 3.0]],
        [1.0, 2.0],
        predicted_std=[[0.5, 0.5], [0.5, 0.5]],
    )
    assert result.normalized_rmse == 0.0
    assert result.normalized_mae == 0.0
    assert result.gaussian_nll is not None and math.isfinite(result.gaussian_nll)


def test_regret_uses_oracle_value_of_candidate_chosen_action() -> None:
    result = treatment_regret(
        predicted_utilities=[[0.0, 1.0], [2.0, 1.0]],
        oracle_utilities=[[3.0, 1.0], [2.0, -5.0]],
        catastrophic_margin=1.5,
    )
    assert result.chosen_actions == (1, 0)
    assert result.mean_regret == 1.0
    assert result.worst_regret == 2.0
    assert result.catastrophic_count == 1


def test_roc_auc_handles_ties_and_direction() -> None:
    assert binary_roc_auc([0.1, 0.2, 0.8, 0.9], [0, 0, 1, 1]) == 1.0
    assert binary_roc_auc([0.5, 0.5], [0, 1]) == 0.5


def probe(**changes) -> PairProbe:
    values = {
        "pair_id": "p",
        "state_hash_a": "sha256:" + "a" * 64,
        "state_hash_b": "sha256:" + "a" * 64,
        "candidate_signature_a": (0.0, 0.0),
        "candidate_signature_b": (0.01, 0.0),
        "oracle_signature_a": (0.0, 0.0),
        "oracle_signature_b": (1.0, 0.0),
        "oracle_action_values_a": (2.0, 0.0),
        "oracle_action_values_b": (0.0, 2.0),
        "information_relation": InformationRelation.DISTINGUISHABLE,
        "intervention_identifiable": True,
    }
    values.update(changes)
    return PairProbe(**values)


def classify(value: PairProbe):
    return classify_pair(
        value,
        candidate_same_epsilon=0.05,
        candidate_split_delta=0.5,
        oracle_distinguishable_delta=0.5,
        oracle_equivalent_epsilon=0.05,
        catastrophic_margin=1.0,
    )


def test_dangerous_collision_is_hard_only_when_attributable_to_visible_information() -> None:
    visible = classify(probe())
    identical = classify(
        probe(information_relation=InformationRelation.IDENTICAL_PREFIX)
    )
    nonidentified = classify(
        probe(
            information_relation=InformationRelation.NONIDENTIFIED,
            intervention_identifiable=False,
        )
    )
    assert visible.exact_collision and visible.dangerous_collision
    assert visible.attributable_collision
    assert identical.dangerous_collision and not identical.attributable_collision
    assert nonidentified.dangerous_collision and not nonidentified.attributable_collision


def test_false_split_uses_oracle_equivalence_not_state_labels() -> None:
    result = classify(
        probe(
            state_hash_b="sha256:" + "b" * 64,
            candidate_signature_b=(1.0, 1.0),
            oracle_signature_b=(0.01, 0.0),
            oracle_action_values_b=(2.0, 0.0),
        )
    )
    assert result.false_split
    assert not result.dangerous_collision


def test_pair_classifier_rejects_unknown_relation_and_bad_threshold() -> None:
    with pytest.raises(ProtocolViolation, match="unknown pair information"):
        classify(probe(information_relation="secret-test-id-match"))
    with pytest.raises(ProtocolViolation, match="finite and non-negative"):
        classify_pair(
            probe(),
            candidate_same_epsilon=-1.0,
            candidate_split_delta=0.5,
            oracle_distinguishable_delta=0.5,
            oracle_equivalent_epsilon=0.05,
            catastrophic_margin=1.0,
        )
