from __future__ import annotations

import pytest

from prototype.unified_map.canonical import digest_json
from prototype.unified_map.schema import DiagnosisQuery, RolloutQuery
from prototype.unified_map.true_state_probe_w02 import (
    W02TrueStateUpperBoundProbe,
    run_w02_vertical_slice,
)
from prototype.unified_map.worlds.base import WorldSplit
from prototype.unified_map.worlds.w02 import W02World


def _utility_digest(world: W02World, horizon: int) -> str:
    return digest_json(["W02", world.catalog.digest, horizon, "quadratic"])


def test_w02_true_state_is_one_hot_while_public_belief_remains_uncertain() -> None:
    world = W02World()
    probe = W02TrueStateUpperBoundProbe(world)
    episode = world.generate_episode(WorldSplit.TRAIN, 93021, 9)
    state = probe.initialize_private(episode)
    diagnosis = probe.diagnose(
        state,
        DiagnosisQuery(world.catalog.diagnostic_labels),
        query_seed=1,
    )
    public = world.counterfactual(episode, world.policy_set(4)[0], 4, 1)
    posterior = public.latent_distribution["diagnostic_posterior"]

    assert all(0.0 < value < 1.0 for value in posterior.values())
    assert diagnosis.response.result.probabilities == episode.diagnostic_target
    assert sorted(diagnosis.response.result.probabilities.values()) == [0.0, 1.0]


def test_w02_true_state_rollouts_share_one_hash_and_match_private_oracle() -> None:
    world = W02World()
    probe = W02TrueStateUpperBoundProbe(world)
    episode = world.generate_episode(WorldSplit.VALIDATION, 93023, 6)
    state = probe.initialize_private(episode)
    consumed = set()
    for policy in world.policy_set(4):
        execution = probe.rollout(
            state,
            RolloutQuery(
                4,
                policy,
                ("obs_0", "obs_1", "obs_2"),
                _utility_digest(world, 4),
            ),
            query_seed=2,
        )
        consumed.add(execution.consumed_state_hash)
        oracle = world.judge_true_state_counterfactual(
            episode.hidden_state_at_cut,
            episode.invariant_parameters,
            policy,
            4,
        )
        steps = oracle.observation_distribution["latent_moment_projection"]
        predictions = execution.response.result.observable_predictions
        assert predictions["obs_0"]["values"] == pytest.approx(
            [sum(step["mean"]) for step in steps], abs=1e-12
        )
        assert predictions["obs_1"]["values"] == pytest.approx(
            [step["mean"][0] for step in steps], abs=1e-12
        )
        assert predictions["obs_2"]["values"] == pytest.approx(
            [step["mean"][1] for step in steps], abs=1e-12
        )
        assert execution.response.result.utility_prediction["value"] == pytest.approx(
            oracle.expected_utility, abs=1e-12
        )
    assert consumed == {state.record.state_hash}


def test_w02_private_one_step_dynamics_have_an_independent_numeric_check() -> None:
    world = W02World()
    episode = world.generate_episode(WorldSplit.TRAIN, 93025, 4)
    policy = world.policy_set(1)[1]
    result = world.judge_true_state_counterfactual(
        episode.hidden_state_at_cut,
        episode.invariant_parameters,
        policy,
        1,
    )
    x0, x1 = episode.hidden_state_at_cut["x"]
    if episode.invariant_parameters["class_index"] == 0:
        expected = [0.85 * x0 + 0.25 * x1 - 0.30, -0.10 * x0 + 0.80 * x1 + 0.12]
    else:
        expected = [0.85 * x0 - 0.25 * x1 - 0.30, 0.10 * x0 + 0.80 * x1 + 0.12]
    step = result.latent_distribution["steps"][0]
    assert step["mean"] == pytest.approx(expected, abs=1e-12)
    assert step["covariance"][0] == pytest.approx([0.06**2, 0.0], abs=1e-12)
    assert step["covariance"][1] == pytest.approx([0.0, 0.06**2], abs=1e-12)


def test_w02_vertical_slice_is_deterministic_and_closes_hash_lineage() -> None:
    first = run_w02_vertical_slice(generator_seed=92024, episode_index=36)
    second = run_w02_vertical_slice(generator_seed=92024, episode_index=36)
    assert first == second
    assert all(first["assertions"].values())
    assert first["manifest"]["world_slot"] == "W02"
    assert first["manifest"]["privileged"] is True
    assert first["experiment_status"] == "NOT_COUNT_ELIGIBLE"
