from __future__ import annotations

from prototype.unified_map.canonical import digest_json
from prototype.unified_map.schema import DiagnosisQuery, PlanKind, RolloutQuery
from prototype.unified_map.true_state_probe_w19 import (
    W19PublicTailProbe,
    run_w19_tail_slice,
)
from prototype.unified_map.worlds.w19 import W19World


def _policy(world: W19World, action: str | None):
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


def test_w19_public_belief_rollout_matches_episode_oracle() -> None:
    world = W19World()
    _, tail = world.tail_probe_pair(seed=1901, probe_index=0)
    policy = _policy(world, "A1")
    episode_result = world.counterfactual(tail, policy, 4, 1)
    state_result = world.public_belief_counterfactual(
        world.public_posterior(tail), policy, 4
    )
    assert episode_result == state_result


def test_w19_unidentified_private_tail_alias_cannot_split_public_state() -> None:
    world = W19World()
    probe = W19PublicTailProbe(world)
    common, tail = world.unidentified_tail_alias_pair(seed=1903)
    assert common.invariant_parameters["tail"] is False
    assert tail.invariant_parameters["tail"] is True

    common_state = probe.initialize_public_episode(common)
    tail_state = probe.initialize_public_episode(tail)
    assert common_state.record.state_hash == tail_state.record.state_hash


def test_w19_positive_marker_state_exposes_a1_but_not_a2_hard_gate() -> None:
    world = W19World()
    probe = W19PublicTailProbe(world)
    _, tail = world.tail_probe_pair(seed=1901, probe_index=0)
    state = probe.initialize_public_episode(tail)
    diagnosis = probe.diagnose(
        state, DiagnosisQuery(world.catalog.diagnostic_labels), query_seed=1
    )
    assert diagnosis.response.result.probabilities["C1"] > 0.40

    rows = {}
    for action in ("A1", "A2"):
        rows[action] = probe.rollout(
            state,
            RolloutQuery(
                4,
                _policy(world, action),
                ("obs_0",),
                digest_json(["W19", "tail-aware", action]),
            ),
            query_seed=2,
        ).response.result.utility_prediction
    assert rows["A1"]["recommendation"] == "contraindicated"
    assert rows["A1"]["tail_only_regret"] > 10.0
    assert rows["A2"]["recommendation"] == "eligible"


def test_w19_tail_slice_is_deterministic_and_closes_all_claims() -> None:
    first = run_w19_tail_slice()
    second = run_w19_tail_slice()
    assert first == second
    assert all(first["assertions"].values())
    assert first["experiment_status"] == "NOT_COUNT_ELIGIBLE"
