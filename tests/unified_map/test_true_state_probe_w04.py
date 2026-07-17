from __future__ import annotations

import pytest

from prototype.unified_map.canonical import digest_json
from prototype.unified_map.schema import RolloutQuery
from prototype.unified_map.true_state_probe_w04 import (
    W04TrueStateUpperBoundProbe,
    run_w04_collision_slice,
)
from prototype.unified_map.worlds.w04 import W04World


def _query(world: W04World, policy: object) -> RolloutQuery:
    return RolloutQuery(
        4,
        policy,
        ("obs_0",),
        digest_json(["W04", world.catalog.digest, 4, "quadratic"]),
    )


def test_w04_same_natural_state_requires_distinct_treatment_modifier() -> None:
    world = W04World()
    probe = W04TrueStateUpperBoundProbe(world)
    left = probe.initialize_true_state(class_index=0, x=0.4)
    right = probe.initialize_true_state(class_index=1, x=0.4)
    policies = world.policy_set(4)[:3]

    assert left.record.state_hash != right.record.state_hash
    left_rows = [probe.rollout(left, _query(world, policy), query_seed=1) for policy in policies]
    right_rows = [probe.rollout(right, _query(world, policy), query_seed=1) for policy in policies]
    left_noop = left_rows[0].response.result.observable_predictions["obs_0"]["values"]
    right_noop = right_rows[0].response.result.observable_predictions["obs_0"]["values"]
    assert left_noop == right_noop

    left_utilities = [row.response.result.utility_prediction["value"] for row in left_rows]
    right_utilities = [row.response.result.utility_prediction["value"] for row in right_rows]
    assert max(range(3), key=left_utilities.__getitem__) == 1
    assert max(range(3), key=right_utilities.__getitem__) == 2


def test_w04_private_one_step_response_sign_has_independent_check() -> None:
    world = W04World()
    policy = world.policy_set(1)[1]
    for class_index, expected in ((0, 0.068), (1, 0.968)):
        result = world.judge_true_state_counterfactual(
            {"x": 0.4}, {"class_index": class_index}, policy, 1
        )
        step = result.latent_distribution["steps"][0]
        assert step["mean"] == pytest.approx(expected, abs=1e-12)
        assert step["variance"] == pytest.approx(0.04**2, abs=1e-12)


def test_w04_collision_slice_is_deterministic_and_closes_all_claims() -> None:
    first = run_w04_collision_slice(x=0.4)
    second = run_w04_collision_slice(x=0.4)
    assert first == second
    assert all(first["assertions"].values())
    assert first["patients"]["C0"]["best_action"] == "single_A1"
    assert first["patients"]["C1"]["best_action"] == "single_A2"
    assert first["experiment_status"] == "NOT_COUNT_ELIGIBLE"
