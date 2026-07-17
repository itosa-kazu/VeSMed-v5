from __future__ import annotations

import pytest

from prototype.unified_map.canonical import digest_json
from prototype.unified_map.schema import DiagnosisQuery, PlanKind, RolloutQuery
from prototype.unified_map.true_state_probe_w15 import (
    W15SharedCausalProbe,
    run_w15_causal_slice,
)
from prototype.unified_map.worlds.w15 import World15A, World15B


def _policy(world, horizon: int, action: str | None):
    if action is None:
        return next(
            policy
            for policy in world.policy_set(horizon)
            if policy.kind is PlanKind.NO_NEW_ACTION
        )
    return next(
        policy
        for policy in world.policy_set(horizon)
        if len(policy.actions) == 1 and policy.actions[0].action_id == action
    )


def test_w15a_private_do_effect_has_independent_one_step_check() -> None:
    world = World15A()
    no_action = world.judge_true_state_counterfactual(
        {"severity": 0.9}, {"confounder": 0}, _policy(world, 4, None), 4
    )
    do_a1 = world.judge_true_state_counterfactual(
        {"severity": 0.9}, {"confounder": 0}, _policy(world, 4, "A1"), 4
    )

    no_action_mean = no_action.observation_distribution["steps"][0]["obs_0_mean"]
    do_a1_mean = do_a1.observation_distribution["steps"][0]["obs_0_mean"]
    assert no_action_mean == pytest.approx(0.828, abs=1e-12)
    assert do_a1_mean == pytest.approx(0.478, abs=1e-12)
    assert do_a1_mean - no_action_mean == pytest.approx(-0.35, abs=1e-12)


def test_w15b_private_scm_twins_cannot_split_shared_state() -> None:
    world = World15B()
    probe = W15SharedCausalProbe(nonidentified=world)
    plus, minus = world.nonidentified_twin_fixture(seed=757, confounder=0)
    assert world.judge_structural_effect(plus) == 1.0
    assert world.judge_structural_effect(minus) == -1.0

    plus_state = probe.initialize_nonidentified_private(plus)
    minus_state = probe.initialize_nonidentified_private(minus)
    assert plus_state.record.state_hash == minus_state.record.state_hash


def test_w15b_shared_state_returns_set_and_abstains() -> None:
    world = World15B()
    probe = W15SharedCausalProbe(nonidentified=world)
    plus, _ = world.nonidentified_twin_fixture(seed=757, confounder=1)
    state = probe.initialize_nonidentified_private(plus)
    diagnosis = probe.diagnose(
        state, DiagnosisQuery(("C0", "C1")), query_seed=1
    )
    rollout = probe.rollout(
        state,
        RolloutQuery(
            1,
            _policy(world, 1, "A1"),
            ("obs_1",),
            digest_json(["W15B", "identified-set", 1]),
        ),
        query_seed=2,
    )

    assert diagnosis.response.result.probabilities == {"C0": 0.5, "C1": 0.5}
    prediction = rollout.response.result.utility_prediction
    assert prediction["ate_identified_set"] == [-1.0, 1.0]
    assert prediction["recommendation"] == "abstain"


def test_w15_causal_slice_is_deterministic_and_closes_all_claims() -> None:
    first = run_w15_causal_slice()
    second = run_w15_causal_slice()
    assert first == second
    assert all(first["assertions"].values())
    assert first["experiment_status"] == "NOT_COUNT_ELIGIBLE"
