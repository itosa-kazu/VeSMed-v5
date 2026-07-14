from __future__ import annotations

import math
from dataclasses import replace

import pytest

from prototype.unified_map.canonical import canonical_json_bytes
from prototype.unified_map.schema import EventKind
from prototype.unified_map.worlds.base import MicroWorld, PrivateEpisode, WorldSplit
from prototype.unified_map.worlds.w11 import World11, _semantic_events
from prototype.unified_map.worlds.w12 import World12
from prototype.unified_map.worlds.w13 import World13
from prototype.unified_map.worlds.w14 import World14
from prototype.unified_map.worlds.w15 import World15A, World15B


PRIMARY_WORLDS = (World11, World12, World13, World14, World15A)


def _last_value(episode: PrivateEpisode, channel: str) -> float:
    values = [
        float(event.payload["value"])
        for event in episode.public_history.events
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == channel
    ]
    assert values
    return values[-1]


def _best_action(world: MicroWorld, episode: PrivateEpisode) -> str:
    scored = [
        (world.counterfactual(episode, policy, 1, 9001).expected_utility, policy)
        for policy in world.policy_set(1)
    ]
    policy = max(scored, key=lambda row: row[0])[1]
    return policy.kind.value if not policy.actions else policy.actions[0].action_id


@pytest.mark.parametrize("world_type", (*PRIMARY_WORLDS, World15B))
@pytest.mark.parametrize("split", tuple(WorldSplit))
def test_generators_are_deterministic_and_cut_filters_future(
    world_type: type[MicroWorld], split: WorldSplit
) -> None:
    world = world_type()
    first = world.generate_episode(split, 741, 7)
    second = world.generate_episode(split, 741, 7)
    assert first == second
    assert first.split is split
    assert first.public_history == first.judge_case().candidate_projection()
    assert first.training_example().history == first.public_history
    assert all(
        event.available_at <= first.public_history.as_of_available_at
        for event in first.public_history.events
    )


@pytest.mark.parametrize("world_type", (*PRIMARY_WORLDS, World15B))
def test_catalog_and_candidate_projection_do_not_expose_private_fields(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 743, 6)
    candidate_bytes = canonical_json_bytes(episode.public_history.to_wire())
    catalog_bytes = canonical_json_bytes(world.catalog.to_wire())
    for forbidden in (
        b"w11",
        b"w12",
        b"w13",
        b"w14",
        b"w15",
        b"split",
        b"generator_seed",
        b"mechanism_index",
        b"host_modifier",
        b"interaction_class",
        b"path_memory",
        b"confounder",
        b"private_scm",
        b"oracle",
    ):
        assert forbidden not in candidate_bytes.lower()
        assert forbidden not in catalog_bytes.lower()
    # Judge-private truth remains available to the evaluator only.
    assert episode.judge_case().hidden_state


@pytest.mark.parametrize("world_type", (*PRIMARY_WORLDS, World15B))
def test_policy_sets_are_finite_unique_and_counterfactual_queries_are_pure(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    horizon = 1 if world_type is World15B else 4
    policies = world.policy_set(horizon)
    policy_bytes = [canonical_json_bytes(policy.to_wire()) for policy in policies]
    assert 2 <= len(policies) <= 16
    assert len(set(policy_bytes)) == len(policy_bytes)
    episode = world.generate_episode(WorldSplit.VALIDATION, 745, 8)
    forward = [
        world.counterfactual(episode, policy, horizon, 11) for policy in policies
    ]
    backward = [
        world.counterfactual(episode, policy, horizon, 99)
        for policy in reversed(policies)
    ]
    assert forward == list(reversed(backward))
    assert episode == world.generate_episode(WorldSplit.VALIDATION, 745, 8)


def test_w11_same_routine_total_needs_source_contrast_and_opposite_treatment() -> None:
    world = World11()
    first, second = world.distinguishable_fixture()
    assert _last_value(first, "obs_0") == _last_value(second, "obs_0")
    assert _last_value(first, "obs_1") == -_last_value(second, "obs_1")
    assert _best_action(world, first) == "A1"
    assert _best_action(world, second) == "A2"


def test_w11_uid_alpha_renaming_is_behaviorally_equivalent() -> None:
    world = World11()
    first, second = world.equivalent_fixture()
    assert first.public_history.digest != second.public_history.digest
    assert _semantic_events(first) == _semantic_events(second)
    assert first.hidden_state_at_cut == second.hidden_state_at_cut
    for policy in world.policy_set(4):
        assert world.counterfactual(first, policy, 4, 1) == world.counterfactual(
            second, policy, 4, 999
        )


def test_w12_expression_is_not_the_shared_mechanism_state() -> None:
    world = World12()
    low_host, high_host = world.distinguishable_fixture()
    assert _last_value(low_host, "obs_0") == pytest.approx(0.60)
    assert _last_value(high_host, "obs_0") == pytest.approx(0.60)
    no_action = world.policy_set(1)[0]
    low = world.counterfactual(low_host, no_action, 1, 1)
    high = world.counterfactual(high_host, no_action, 1, 1)
    assert (
        low.latent_distribution["steps"][0]["mean"]
        != high.latent_distribution["steps"][0]["mean"]
    )
    same_x_low, same_x_high = world.same_mechanism_fixture()
    low_future = world.counterfactual(same_x_low, no_action, 1, 1)
    high_future = world.counterfactual(same_x_high, no_action, 1, 1)
    # Both public posteriors recover the same mechanism mean.  Their variance
    # may differ because h changes Q0 measurement precision; that uncertainty
    # is part of the posterior and must not be silently discarded.
    assert low_future.latent_distribution["steps"][0]["mean"] == pytest.approx(
        high_future.latent_distribution["steps"][0]["mean"], abs=1e-10
    )
    assert (
        low_future.observation_distribution["steps"][0]["obs_0_mean"]
        != high_future.observation_distribution["steps"][0]["obs_0_mean"]
    )


def test_w12_equivalent_uid_histories_have_equal_all_policy_futures() -> None:
    world = World12()
    first, second = world.equivalent_fixture()
    for policy in world.policy_set(4):
        assert world.counterfactual(first, policy, 4, 1) == world.counterfactual(
            second, policy, 4, 2
        )


def test_w13_threshold_is_nonlinear_and_not_an_additive_bonus() -> None:
    world = World13()
    below, above = world.threshold_fixture()
    assert _last_value(below, "obs_0") == pytest.approx(
        _last_value(above, "obs_0")
    )
    assert _last_value(below, "obs_2") == 0.0
    assert _last_value(above, "obs_2") == pytest.approx(0.04)
    no_action = world.policy_set(1)[0]
    below_future = world.counterfactual(below, no_action, 1, 1)
    above_future = world.counterfactual(above, no_action, 1, 1)
    assert below_future.expected_utility != above_future.expected_utility
    # Direct independent effects would omit z; the executable transition must
    # include the threshold term in both component equations exactly once.
    x0, x1 = 0.8, 0.5
    z = World13._phi(2, x0, x1)
    next0, next1 = World13._step(2, x0, x1, None)
    assert next0 == pytest.approx(0.88 * x0 + 0.06 + 0.12 * z)
    assert next1 == pytest.approx(0.84 * x1 + 0.08 + 0.12 * z)


def test_w13_equivalent_sufficient_state_ignores_uid_history() -> None:
    world = World13()
    first, second = world.equivalent_fixture()
    for policy in world.policy_set(4):
        assert world.counterfactual(first, policy, 4, 3) == world.counterfactual(
            second, policy, 4, 4
        )


def test_w14_same_snapshot_different_memory_has_opposite_optimal_action() -> None:
    world = World14()
    low_memory, high_memory = world.distinguishable_fixture()
    assert _last_value(low_memory, "obs_0") == _last_value(high_memory, "obs_0")
    assert low_memory.public_history.digest != high_memory.public_history.digest
    assert _best_action(world, low_memory) == "A1"
    assert _best_action(world, high_memory) == "A2"


def test_w14_different_raw_paths_same_finite_state_are_future_equivalent() -> None:
    world = World14()
    first, second = world.equivalent_fixture()
    assert first.public_history.digest != second.public_history.digest
    assert first.hidden_state_at_cut == second.hidden_state_at_cut
    for policy in world.policy_set(8):
        assert world.counterfactual(first, policy, 8, 17) == world.counterfactual(
            second, policy, 8, 18
        )


def test_w15a_randomized_anchor_is_exactly_30_percent_and_public() -> None:
    world = World15A()
    randomized = 0
    decisions = 0
    for episode_index in range(10):
        episode = world.generate_episode(WorldSplit.TRAIN, 751, episode_index)
        flags = [
            int(event.payload["value"])
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_2"
        ]
        assert len(flags) == 3
        randomized += sum(flags)
        decisions += len(flags)
        for row in episode.action_propensities:
            if row["assignment"] == "randomized":
                assert row["probabilities"] == {"A1": 0.5, "NoNewAction": 0.5}
    assert (randomized, decisions) == (9, 30)


def test_w15a_anchor_oracle_reports_identified_do_effect_not_association() -> None:
    world = World15A()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 753, 4)
    for policy in world.policy_set(4):
        result = world.counterfactual(episode, policy, 4, 1)
        assert (
            result.outcome_distribution["identification_status"]
            == "identified-by-randomized-anchor"
        )


def test_w15b_observational_twins_are_exact_bytes_but_private_effects_reverse() -> None:
    world = World15B()
    plus, minus = world.nonidentified_twin_fixture(seed=755, confounder=0)
    assert plus.public_history.to_wire() == minus.public_history.to_wire()
    assert plus.training_example().history == minus.training_example().history
    assert plus.diagnostic_target == minus.diagnostic_target
    assert plus.invariant_parameters != minus.invariant_parameters
    assert world.judge_structural_effect(plus) == 1.0
    assert world.judge_structural_effect(minus) == -1.0


def test_w15b_oracle_conditions_only_on_public_equivalence_class() -> None:
    world = World15B()
    plus, minus = world.nonidentified_twin_fixture(seed=757, confounder=1)
    for policy in world.policy_set(1):
        first = world.counterfactual(plus, policy, 1, 1)
        second = world.counterfactual(minus, policy, 1, 999)
        assert first == second
        assert first.outcome_distribution["ate_identified_set"] == [-1.0, 1.0]
        assert (
            first.outcome_distribution["identification_status"]
            == "unsupported-point-effect"
        )
        assert first.outcome_distribution["recommendation"] == "abstain"
        assert first.outcome_distribution["candidate_collision_attributable"] is False
        assert first.numerical_diagnostics["private_scm_used_for_scoring"] is False


def test_w15b_private_swap_cannot_change_candidate_or_scoring_oracle() -> None:
    """Negative control: private point-effect scoring would fail this test."""

    world = World15B()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 759, 0)
    swapped = replace(
        episode,
        invariant_parameters={"private_scm": "Mminus"},
    )
    assert episode.public_history == swapped.public_history
    assert world.judge_structural_effect(episode) == -world.judge_structural_effect(
        swapped
    )
    for policy in world.policy_set(1):
        assert world.counterfactual(episode, policy, 1, 1) == world.counterfactual(
            swapped, policy, 1, 1
        )


def test_w15_panels_have_separate_reporting_anchors() -> None:
    identifiable = World15A().generate_episode(WorldSplit.TRAIN, 761, 0)
    nonidentified = World15B().generate_episode(WorldSplit.TRAIN, 761, 0)
    assert identifiable.oracle_anchor["panel"] == "randomized-identifiable"
    assert identifiable.oracle_anchor["causal_effect_identified"] is True
    assert nonidentified.oracle_anchor["panel"] == "observational-nonidentified"
    assert nonidentified.oracle_anchor["point_effect_scoring"] is False
    assert math.isclose(
        sum(nonidentified.oracle_anchor["public_scm_posterior"].values()), 1.0
    )
