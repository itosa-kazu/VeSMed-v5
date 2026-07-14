from __future__ import annotations

from dataclasses import replace
import math

import pytest

from prototype.unified_map.canonical import canonical_json_bytes
from prototype.unified_map.schema import EventKind, PlanKind
from prototype.unified_map.worlds import MicroWorld, WorldSplit
from prototype.unified_map.worlds.w01 import W01World
from prototype.unified_map.worlds.w02 import W02World
from prototype.unified_map.worlds.w03 import W03World
from prototype.unified_map.worlds.w04 import W04World
from prototype.unified_map.worlds.w05 import W05World


WORLD_TYPES = (W01World, W02World, W03World, W04World, W05World)
FORBIDDEN_WIRE_TOKENS = (
    b"world_id",
    b"case_id",
    b"test_id",
    b"episode_index",
    b"generator_seed",
    b"environment_seed",
    b"hidden_state",
    b"true_state",
    b"oracle",
    b"actual_future",
    b"expected_action",
    b"expected_label",
    b"reward_to_come",
)


def _oracle_signature(oracle: object) -> bytes:
    # CounterfactualOracle deliberately has no candidate-facing serializer.
    # This is a test-only canonical projection of public numeric behavior.
    return canonical_json_bytes(
        {
            "observation_distribution": oracle.observation_distribution,
            "latent_distribution": oracle.latent_distribution,
            "outcome_distribution": oracle.outcome_distribution,
            "expected_utility": oracle.expected_utility,
            "numerical_diagnostics": oracle.numerical_diagnostics,
        }
    )


def _semantic_event_projection(episode: object) -> list[dict[str, object]]:
    projected = [
        {
            "kind": event.kind.value,
            "occurred_at": event.occurred_at,
            "collected_at": event.collected_at,
            "available_at": event.available_at,
            "payload": event.payload,
        }
        for event in episode.public_history.events
    ]
    return sorted(projected, key=canonical_json_bytes)


@pytest.mark.parametrize("world_type", WORLD_TYPES)
def test_worlds_are_deterministic_and_candidate_projection_is_clean(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    first = world.generate_episode(WorldSplit.TRAIN, 987654321, 17)
    second = world.generate_episode(WorldSplit.TRAIN, 987654321, 17)
    other_split = world.generate_episode(WorldSplit.VALIDATION, 987654321, 17)

    assert first.public_history.to_wire() == second.public_history.to_wire()
    assert first.hidden_state_at_cut == second.hidden_state_at_cut
    assert first.invariant_parameters == second.invariant_parameters
    assert first.factual_future == second.factual_future
    assert first.action_propensities == second.action_propensities
    assert first.factual_utility == second.factual_utility
    assert first.generator_seed == other_split.generator_seed == 987654321
    assert first.public_history.digest != other_split.public_history.digest

    history_wire = canonical_json_bytes(first.public_history.to_wire())
    catalog_wire = canonical_json_bytes(world.catalog.to_wire())
    for forbidden in FORBIDDEN_WIRE_TOKENS:
        assert forbidden not in history_wire
        assert forbidden not in catalog_wire
    assert first.public_history.as_of_available_at == 0
    assert all(event.available_at <= 0 for event in first.public_history.events)


@pytest.mark.parametrize("world_type", WORLD_TYPES)
def test_no_new_action_is_typed_absence_not_a_zero_dose_event(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.TRAIN, 111, 5)
    performed = [
        event
        for event in episode.public_history.events
        if event.kind is EventKind.PERFORMED_TREATMENT
    ]
    assert all(event.payload["action_id"] in {"A1", "A2"} for event in performed)
    assert all(event.payload["action_id"] != "NoNewAction" for event in performed)

    policies = world.policy_set(4)
    assert policies[0].kind is PlanKind.NO_NEW_ACTION
    assert policies[0].actions == ()
    assert len({canonical_json_bytes(policy.to_wire()) for policy in policies}) == len(
        policies
    )


@pytest.mark.parametrize("world_type", WORLD_TYPES)
def test_policy_enumeration_and_oracle_seed_order_do_not_change_results(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.VALIDATION, 321, 3)
    policies = world.policy_set(4)
    forward = {
        canonical_json_bytes(policy.to_wire()): _oracle_signature(
            world.counterfactual(episode, policy, 4, 1)
        )
        for policy in policies
    }
    reverse = {
        canonical_json_bytes(policy.to_wire()): _oracle_signature(
            world.counterfactual(episode, policy, 4, 999999)
        )
        for policy in reversed(policies)
    }
    assert forward == reverse


@pytest.mark.parametrize("world_type", WORLD_TYPES)
def test_alpha_renamed_false_split_fixture_has_identical_semantics_and_oracle(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    left, right = world.false_split_fixture()
    assert left.public_history.digest != right.public_history.digest
    assert _semantic_event_projection(left) == _semantic_event_projection(right)
    for policy in world.policy_set(4):
        left_oracle = world.counterfactual(left, policy, 4, 7)
        right_oracle = world.counterfactual(right, policy, 4, 7)
        assert left_oracle.expected_utility == pytest.approx(
            right_oracle.expected_utility, abs=1e-11
        )
        assert left_oracle.latent_distribution["diagnostic_posterior"] == pytest.approx(
            right_oracle.latent_distribution["diagnostic_posterior"], abs=1e-11
        )


@pytest.mark.parametrize("world_type", WORLD_TYPES)
def test_collision_fixture_is_oracle_distinguishable(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    left, right = world.collision_fixture()
    policies = world.policy_set(4)
    left_utilities = [
        world.counterfactual(left, policy, 4, 13).expected_utility
        for policy in policies
    ]
    right_utilities = [
        world.counterfactual(right, policy, 4, 13).expected_utility
        for policy in policies
    ]
    assert max(abs(a - b) for a, b in zip(left_utilities, right_utilities, strict=True)) > 0.20
    assert left_utilities.index(max(left_utilities)) != right_utilities.index(
        max(right_utilities)
    )


def test_w01_exact_panel_and_analytic_linear_oracle() -> None:
    world = W01World()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 9, 40)
    oracle = world.counterfactual(episode, world.policy_set(8)[0], 8, 0)
    assert oracle.latent_distribution["diagnostic_posterior"] in (
        {"C0": 1.0, "C1": 0.0},
        {"C0": 0.0, "C1": 1.0},
    )
    assert oracle.numerical_diagnostics["method"] == "analytic-linear-gaussian"
    assert oracle.numerical_diagnostics["absolute_error_bound"] == 0.0
    assert oracle.numerical_diagnostics["spectral_radius"] < 1.0


def test_w02_private_realization_and_future_cannot_change_cut_posterior() -> None:
    world = W02World()
    left, right = world.future_leak_fixture()
    assert left.public_history.digest == right.public_history.digest
    for policy in world.policy_set(4):
        assert _oracle_signature(world.counterfactual(left, policy, 4, 1)) == _oracle_signature(
            world.counterfactual(right, policy, 4, 1)
        )
    posterior = world.counterfactual(left, world.policy_set(4)[0], 4, 1).latent_distribution[
        "diagnostic_posterior"
    ]
    assert 0.0 < posterior["C0"] < 1.0
    assert 0.0 < posterior["C1"] < 1.0
    assert math.isclose(posterior["C0"] + posterior["C1"], 1.0)


def test_w03_same_current_value_opposite_ordered_trends_fork_natural_future() -> None:
    world = W03World()
    falling, rising = world.collision_fixture()
    falling_last = [
        event.payload["value"]
        for event in falling.public_history.events
        if event.payload.get("channel_id") == "obs_0"
    ][-1]
    rising_last = [
        event.payload["value"]
        for event in rising.public_history.events
        if event.payload.get("channel_id") == "obs_0"
    ][-1]
    assert falling_last == rising_last == 0.0
    noop = world.policy_set(4)[0]
    left = world.counterfactual(falling, noop, 4, 0)
    right = world.counterfactual(rising, noop, 4, 0)
    assert left.latent_distribution["steps"][-1]["mean"] < -0.7
    assert right.latent_distribution["steps"][-1]["mean"] > 0.7


def test_w04_natural_course_is_class_invariant_but_treatment_response_is_not() -> None:
    world = W04World()
    class_zero_belief, class_one_belief = world.collision_fixture()
    policies = world.policy_set(4)
    natural_left = world.counterfactual(class_zero_belief, policies[0], 4, 0)
    natural_right = world.counterfactual(class_one_belief, policies[0], 4, 0)
    assert natural_left.expected_utility == pytest.approx(
        natural_right.expected_utility, abs=1e-12
    )
    a1_left = world.counterfactual(class_zero_belief, policies[1], 4, 0)
    a1_right = world.counterfactual(class_one_belief, policies[1], 4, 0)
    assert abs(a1_left.expected_utility - a1_right.expected_utility) > 1.0

    private_left, private_right = world.irreducible_fixture()
    assert private_left.public_history.digest == private_right.public_history.digest
    assert _oracle_signature(
        world.counterfactual(private_left, policies[1], 4, 0)
    ) == _oracle_signature(world.counterfactual(private_right, policies[1], 4, 0))


def test_w05_noop_preserves_residual_and_future_response_is_not_visible_early() -> None:
    world = W05World()
    exposed, unexposed = world.collision_fixture()
    exposed_actions = [
        event
        for event in exposed.public_history.events
        if event.kind is EventKind.PERFORMED_TREATMENT
    ]
    assert exposed_actions
    assert not [
        event
        for event in unexposed.public_history.events
        if event.kind is EventKind.PERFORMED_TREATMENT
    ]
    assert [
        event.payload["value"]
        for event in exposed.public_history.events
        if event.payload.get("channel_id") == "obs_0"
    ] == [
        event.payload["value"]
        for event in unexposed.public_history.events
        if event.payload.get("channel_id") == "obs_0"
    ]
    noop = world.policy_set(4)[0]
    exposed_oracle = world.counterfactual(exposed, noop, 4, 0)
    unexposed_oracle = world.counterfactual(unexposed, noop, 4, 0)
    assert exposed_oracle.expected_utility != pytest.approx(
        unexposed_oracle.expected_utility, abs=0.5
    )

    future_left, future_right = world.future_leak_fixture()
    assert future_left.public_history.digest == future_right.public_history.digest
    assert _oracle_signature(
        world.counterfactual(future_left, noop, 4, 0)
    ) == _oracle_signature(world.counterfactual(future_right, noop, 4, 0))


def test_private_fields_do_not_affect_any_world_oracle() -> None:
    for world_type in WORLD_TYPES:
        world = world_type()
        episode = world.generate_episode(WorldSplit.TRAIN, 765, 4)
        altered = replace(
            episode,
            case_key="judge-private-altered",
            hidden_state_at_cut={"adversarial_private_value": 1_000_000.0},
            invariant_parameters={"adversarial_private_value": -1_000_000.0},
            factual_future=[{"unavailable": 1_000_000.0}],
            oracle_anchor={"unavailable": -1_000_000.0},
        )
        policy = world.policy_set(4)[0]
        assert _oracle_signature(
            world.counterfactual(episode, policy, 4, 42)
        ) == _oracle_signature(world.counterfactual(altered, policy, 4, 42))
