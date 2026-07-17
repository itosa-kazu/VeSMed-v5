from __future__ import annotations

import pytest

from prototype.unified_map.schema import PlanKind
from prototype.unified_map.true_state_probe_w20 import (
    W20PublicFeedbackProbe,
    run_w20_feedback_slice,
)
from prototype.unified_map.worlds.w20 import W20World


def _policy(world: W20World, action: str | None):
    if action is None:
        return next(
            policy
            for policy in world.policy_set(4)
            if policy.kind is PlanKind.NO_NEW_ACTION
        )
    return next(
        policy
        for policy in world.policy_set(4)
        if len(policy.actions) == 1 and policy.actions[0].action_id == action
    )


def test_w20_public_belief_rollout_matches_episode_oracle() -> None:
    world = W20World()
    low, _ = world.exposure_collision_pair(seed=2001)
    policy = _policy(world, "A1")
    episode_result = world.counterfactual(low, policy, 4, 1)
    belief = world._production_posterior(low)
    state_result = world.public_belief_counterfactual(*belief, policy, 4)
    assert episode_result == state_result


def test_w20_exposure_memory_separates_same_x_opposite_responses() -> None:
    world = W20World()
    low, high = world.exposure_collision_pair(seed=2001)
    low_belief = world._production_posterior(low)
    high_belief = world._production_posterior(high)
    assert low_belief[0] == pytest.approx(high_belief[0], abs=1e-12)
    assert low_belief[2] < 0.75 < high_belief[2]

    policy = _policy(world, "A1")
    low_result = world.public_belief_counterfactual(*low_belief, policy, 4)
    high_result = world.public_belief_counterfactual(*high_belief, policy, 4)
    low_first = low_result.observation_distribution["components"][0]["steps"][0]
    high_first = high_result.observation_distribution["components"][0]["steps"][0]
    assert low_first["mean"] == pytest.approx(0.33, abs=1e-12)
    assert high_first["mean"] == pytest.approx(1.08, abs=1e-12)


def test_w20_complete_sufficient_statistics_quotient_different_histories() -> None:
    world = W20World()
    probe = W20PublicFeedbackProbe(world)
    left, right = world.sufficient_statistic_false_split_pair(seed=2003)
    assert left.public_history.digest != right.public_history.digest

    left_state = probe.initialize_public_episode(left)
    right_state = probe.initialize_public_episode(right)
    assert left_state.record.state_hash == right_state.record.state_hash


def test_w20_feedback_slice_is_deterministic_and_closes_all_claims() -> None:
    first = run_w20_feedback_slice()
    second = run_w20_feedback_slice()
    assert first == second
    assert all(first["assertions"].values())
    assert first["experiment_status"] == "NOT_COUNT_ELIGIBLE"
    updated = first["response_update"]["a1_rollout"]
    assert updated["response"]["result"]["metadata"]["response_regime"] == "reversed"
