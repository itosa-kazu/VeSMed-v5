from __future__ import annotations

import math

import pytest

from prototype.unified_map.canonical import canonical_json_bytes
from prototype.unified_map.schema import EventKind, PlanKind
from prototype.unified_map.worlds.base import WorldSplit
from prototype.unified_map.worlds.w06 import World06
from prototype.unified_map.worlds.w07 import World07
from prototype.unified_map.worlds.w08 import World08
from prototype.unified_map.worlds.w09 import World09
from prototype.unified_map.worlds.w10 import World10


WORLD_HORIZONS = (
    (World06, 4),
    (World07, 4),
    (World08, 4),
    (World09, 4),
    (World10, 4),
)


def action_plan(world: object, horizon: int, action_id: str):
    return next(
        plan
        for plan in world.policy_set(horizon)
        if plan.kind is PlanKind.ACTION_SEQUENCE
        and len(plan.actions) == 1
        and plan.actions[0].offset == 0
        and plan.actions[0].action_id == action_id
        and not plan.actions[0].parameters
    )


@pytest.mark.parametrize(("world_type", "horizon"), WORLD_HORIZONS)
def test_generators_are_replayable_branch_independent_and_candidate_neutral(
    world_type, horizon: int
) -> None:
    world = world_type()
    first = world.generate_episode(WorldSplit.TRAIN, 123456, 7)
    _ = world.generate_episode(WorldSplit.VALIDATION, 999, 19)
    second = world.generate_episode(WorldSplit.TRAIN, 123456, 7)
    assert first == second
    assert first.public_history.catalog_digest == world.catalog.digest
    wire = canonical_json_bytes(first.public_history.to_wire())
    for forbidden in (
        b"world_id",
        b"case_id",
        b"test_id",
        b"episode_index",
        b"generator_seed",
        b"hidden_state",
        b"oracle",
        b"actual_future",
    ):
        assert forbidden not in wire
    policy_wires = [canonical_json_bytes(plan.to_wire()) for plan in world.policy_set(horizon)]
    assert len(policy_wires) == len(set(policy_wires))


def test_w06_channel_action_changes_surface_but_not_latent_distribution() -> None:
    world = World06()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 61, 2)
    no_action = world.policy_set(4)[0]
    action = action_plan(world, 4, "A1")
    natural = world.counterfactual(episode, no_action, 4, 41)
    treated = world.counterfactual(episode, action, 4, 41)
    assert natural.latent_distribution == treated.latent_distribution
    surface_shift = (
        treated.observation_distribution["obs_0"][0]["mean"]
        - natural.observation_distribution["obs_0"][0]["mean"]
    )
    assert surface_shift == pytest.approx(-0.75, abs=1e-12)
    assert treated.outcome_distribution["latent_action_path"] == "none"


def test_w06_masked_state_and_future_leak_fixtures_have_intended_semantics() -> None:
    world = World06()
    fixtures = world.probe_fixtures()
    low, high = fixtures["masked_state_collision"]
    low_q0 = [
        event.payload["value"]
        for event in low.public_history.events
        if event.payload.get("channel_id") == "obs_0" and event.collected_at == 0
    ]
    high_q0 = [
        event.payload["value"]
        for event in high.public_history.events
        if event.payload.get("channel_id") == "obs_0" and event.collected_at == 0
    ]
    assert low_q0 == high_q0 == [0.55]
    low_posterior = world._posterior(low)
    high_posterior = world._posterior(high)
    low_mean = sum(item["weight"] * item["mean_x"] for item in low_posterior)
    high_mean = sum(item["weight"] * item["mean_x"] for item in high_posterior)
    assert high_mean - low_mean > 0.35
    low_utilities = [
        world.counterfactual(low, plan, 4, 1).expected_utility
        for plan in world.policy_set(4)
    ]
    high_utilities = [
        world.counterfactual(high, plan, 4, 1).expected_utility
        for plan in world.policy_set(4)
    ]
    assert low_utilities.index(max(low_utilities)) == 0
    assert high_utilities.index(max(high_utilities)) == 2

    factual, swapped = fixtures["identical_prefix_future_swap"]
    assert factual.public_history == swapped.public_history
    plan = world.policy_set(4)[0]
    assert world.counterfactual(factual, plan, 4, 1) == world.counterfactual(swapped, plan, 4, 1)

    original, renamed = fixtures["false_split_alpha_rename"]
    assert original.public_history.digest != renamed.public_history.digest
    assert world.counterfactual(original, plan, 4, 1) == world.counterfactual(renamed, plan, 4, 1)


def test_w07_oracle_separates_state_mediated_and_direct_channel_effects() -> None:
    world = World07()
    episode = world.generate_episode(WorldSplit.VALIDATION, 72, 3)
    natural = world.counterfactual(episode, world.policy_set(4)[0], 4, 5)
    treated = world.counterfactual(episode, action_plan(world, 4, "A1"), 4, 5)
    latent_contrast = (
        treated.latent_distribution["x"][0]["mean"]
        - natural.latent_distribution["x"][0]["mean"]
    )
    observed_contrast = (
        treated.observation_distribution["obs_0"][0]["mean"]
        - natural.observation_distribution["obs_0"][0]["mean"]
    )
    assert -0.31 < latent_contrast < -0.17
    assert observed_contrast == pytest.approx(latent_contrast - 0.55, abs=1e-12)
    decomposition = treated.outcome_distribution["path_decomposition"]
    assert decomposition["channel_per_unit_dose"] == -0.55
    assert decomposition["state_per_unit_dose"] == pytest.approx(latent_contrast)


def test_w07_hypothetical_query_order_cannot_mutate_factual_state() -> None:
    world = World07()
    episode = world.generate_episode(WorldSplit.TRAIN, 73, 1)
    no_action = world.policy_set(4)[0]
    before = world.counterfactual(episode, no_action, 4, 99)
    _ = world.counterfactual(episode, action_plan(world, 4, "A2"), 4, 99)
    after = world.counterfactual(episode, no_action, 4, 99)
    assert before == after


def test_w08_enforces_availability_cut_and_collection_time_semantics() -> None:
    world = World08()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 83, 4)
    assert all(event.available_at <= 0 for event in episode.public_history.events)
    assert episode.hidden_state_at_cut["pending_results"] == [
        item for item in episode.hidden_state_at_cut["pending_results"] if item["available_at"] > 0
    ]
    visible, hidden = world.probe_fixtures()["availability_boundary"]
    assert len(visible.public_history.events) == 1
    assert visible.public_history.events[0].available_at == 0
    assert hidden.public_history.events == ()

    fresh, stale = world.probe_fixtures()["collection_time_collision"]
    fresh_mean = sum(
        item["weight"] * float(item["mean"][0]) for item in world._posterior(fresh)
    )
    stale_mean = sum(
        item["weight"] * float(item["mean"][0]) for item in world._posterior(stale)
    )
    assert abs(fresh_mean - stale_mean) > 0.05


def test_w08_course_is_exactly_four_microticks_and_policy_calls_are_pure() -> None:
    world = World08()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 84, 2)
    treatment_events = [
        event
        for event in episode.public_history.events
        if event.kind is EventKind.PERFORMED_TREATMENT
    ]
    assert all(event.payload["course_microticks"] == 4 for event in treatment_events)
    constant = next(
        plan
        for plan in world.policy_set(16)
        if [action.offset for action in plan.actions if action.action_id == "A1"]
        == [0, 4, 8, 12]
    )
    assert [action.offset for action in constant.actions] == [0, 4, 8, 12]

    no_action = world.policy_set(16)[0]
    first = world.counterfactual(episode, no_action, 16, 22)
    _ = world.counterfactual(episode, constant, 16, 22)
    second = world.counterfactual(episode, no_action, 16, 22)
    assert first == second


def test_w08_identical_prefix_private_future_never_changes_cut_oracle() -> None:
    world = World08()
    left, right = world.probe_fixtures()["identical_prefix_future_swap"]
    assert left.public_history == right.public_history
    plan = world.policy_set(4)[0]
    assert world.counterfactual(left, plan, 4, 1) == world.counterfactual(right, plan, 4, 1)


def test_w09_same_absolute_level_keeps_baseline_and_deviation_separate() -> None:
    world = World09()
    high, low = world.probe_fixtures()["same_absolute_collision"]
    assert high.public_history.events[-1].payload["value"] in {0.20, 0.80, 1.00}
    high_components = world._posterior(high)
    low_components = world._posterior(low)
    high_deviation = sum(
        item["weight"] * float(item["mean"][1]) for item in high_components
    )
    low_deviation = sum(
        item["weight"] * float(item["mean"][1]) for item in low_components
    )
    assert high_deviation - low_deviation > 0.35
    plan = world.policy_set(4)[0]
    diagnosis = world.counterfactual(high, plan, 4, 2).outcome_distribution[
        "diagnostic_posterior"
    ]
    assert math.fsum(diagnosis.values()) == pytest.approx(1.0)


def test_w09_translation_is_oracle_screened_and_private_decomposition_does_not_leak() -> None:
    world = World09()
    original, translated = world.probe_fixtures()["interior_translation"]
    policies = world.policy_set(4)[:3]
    utilities_original = [
        world.counterfactual(original, policy, 4, 7).expected_utility
        for policy in policies
    ]
    utilities_translated = [
        world.counterfactual(translated, policy, 4, 7).expected_utility
        for policy in policies
    ]
    for index in (1, 2):
        assert (
            utilities_original[index]
            - utilities_original[0]
            - utilities_translated[index]
            + utilities_translated[0]
        ) == pytest.approx(0.0, abs=0.01)

    visible, private_swap = world.probe_fixtures()["identical_prefix_private_decomposition"]
    assert visible.public_history == private_swap.public_history
    plan = world.policy_set(4)[0]
    assert world.counterfactual(visible, plan, 4, 4) == world.counterfactual(private_swap, plan, 4, 4)


def test_w10_grouping_changes_precision_but_nullspace_does_not_change_posterior() -> None:
    world = World10()
    fixtures = world.probe_fixtures()
    grouped, independent = fixtures["same_values_different_grouping"]
    grouped_posterior = world._posterior(grouped)
    independent_posterior = world._posterior(independent)
    assert all(
        right["variance"] < left["variance"]
        for left, right in zip(grouped_posterior, independent_posterior)
    )

    left, right = fixtures["posterior_equivalent_nullspace"]
    for left_component, right_component in zip(
        world._posterior(left), world._posterior(right)
    ):
        assert left_component["mean"] == pytest.approx(right_component["mean"], abs=1e-12)
        assert left_component["variance"] == pytest.approx(right_component["variance"], abs=1e-12)
        assert left_component["weight"] == pytest.approx(right_component["weight"], abs=1e-12)


def test_w10_uses_independent_owen_scrambled_sobol_replicates_for_tail_error() -> None:
    world = World10()
    episode = world.probe_fixtures()["same_values_different_grouping"][0]
    plan = world.policy_set(4)[0]
    oracle = world.counterfactual(episode, plan, 4, 222)
    diagnostics = oracle.numerical_diagnostics
    assert diagnostics["method"] == "nested_owen_scrambled_sobol_base2"
    assert diagnostics["replicates"] == 16
    assert diagnostics["points_per_replicate"] == 2**14
    assert len(diagnostics["replicate_estimates"]) == 16
    assert diagnostics["ci99_half_width"] < 0.005
    assert diagnostics["ci99_requirement_met"] is True
    probability = oracle.outcome_distribution["first_crossing_probability"]
    assert 0.05 < probability < 0.95


def test_w10_hypothetical_policy_order_reuses_common_scramble_without_mutation() -> None:
    world = World10()
    episode = world.generate_episode(WorldSplit.VALIDATION, 105, 1)
    no_action = world.policy_set(1)[0]
    first = world.counterfactual(episode, no_action, 1, 303)
    _ = world.counterfactual(episode, action_plan(world, 1, "A1"), 1, 303)
    second = world.counterfactual(episode, no_action, 1, 303)
    assert first == second
