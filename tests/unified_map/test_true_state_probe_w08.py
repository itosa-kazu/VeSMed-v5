from __future__ import annotations

import pytest

from prototype.unified_map.canonical import digest_json
from prototype.unified_map.schema import PlanKind, RolloutQuery
from prototype.unified_map.true_state_probe_w08 import (
    W08TrueStateUpperBoundProbe,
    run_w08_availability_slice,
)
from prototype.unified_map.worlds.w08 import World08


def _policy(world: World08, action_id: str | None):
    if action_id is None:
        return next(
            policy
            for policy in world.policy_set(4)
            if policy.kind is PlanKind.NO_NEW_ACTION
        )
    return next(
        policy
        for policy in world.policy_set(4)
        if len(policy.actions) == 1 and policy.actions[0].action_id == action_id
    )


def _query(world: World08, action_id: str | None) -> RolloutQuery:
    return RolloutQuery(
        4,
        _policy(world, action_id),
        ("obs_0", "obs_1"),
        digest_json(["W08", world.catalog.digest, 4, "quadratic"]),
    )


def test_w08_private_one_step_transition_has_independent_numeric_check() -> None:
    world = World08()
    result = world.judge_true_state_counterfactual(
        {"x": [0.4, -0.2], "exposure": 0, "remaining": 0},
        {"c": 0},
        _policy(world, "A1"),
        4,
    )

    latent_0 = result.latent_distribution["x0"][0]
    latent_1 = result.latent_distribution["x1"][0]
    assert latent_0["mean"] == pytest.approx(0.32, abs=1e-12)
    assert latent_1["mean"] == pytest.approx(-0.171, abs=1e-12)
    assert latent_0["variance"] == pytest.approx(0.25 * 0.05**2, abs=1e-12)
    assert latent_1["variance"] == pytest.approx(0.25 * 0.05**2, abs=1e-12)


def test_w08_no_new_action_keeps_already_performed_course_active() -> None:
    world = World08()
    probe = W08TrueStateUpperBoundProbe(world)
    state = probe.initialize_true_state(
        class_index=0,
        x=[0.4, -0.2],
        exposure=1,
        remaining=2,
    )
    execution = probe.rollout(state, _query(world, None), query_seed=1)

    first = execution.response.result.observable_predictions["obs_0"]["values"][0]
    assert first == pytest.approx(0.32, abs=1e-12)


def test_w08_pending_private_report_is_not_serialized_before_availability() -> None:
    world = World08()
    probe = W08TrueStateUpperBoundProbe(world)
    left, right = world.probe_fixtures(806)["identical_prefix_future_swap"]
    assert left.hidden_state_at_cut["pending_results"] != right.hidden_state_at_cut[
        "pending_results"
    ]

    left_state = probe.initialize_private(left)
    right_state = probe.initialize_private(right)
    assert left_state.record.state_hash == right_state.record.state_hash


def test_w08_availability_slice_is_deterministic_and_closes_all_claims() -> None:
    first = run_w08_availability_slice()
    second = run_w08_availability_slice()
    assert first == second
    assert all(first["assertions"].values())
    assert first["experiment_status"] == "NOT_COUNT_ELIGIBLE"
