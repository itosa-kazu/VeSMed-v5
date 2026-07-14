from __future__ import annotations

from dataclasses import replace

import pytest

from prototype.unified_map.canonical import canonical_json_bytes
from prototype.unified_map.metrics import (
    InformationRelation,
    PairProbe,
    classify_pair,
)
from prototype.unified_map.schema import ActionPlan, EventKind, PlanKind
from prototype.unified_map.worlds.base import WorldSplit
from prototype.unified_map.worlds.w16 import W16World
from prototype.unified_map.worlds.w17 import W17World
from prototype.unified_map.worlds.w18 import W18World
from prototype.unified_map.worlds.w19 import W19World
from prototype.unified_map.worlds.w20 import W20World


WORLD_TYPES = (W16World, W17World, W18World, W19World, W20World)


def _oracle_signature(oracle: object) -> bytes:
    return canonical_json_bytes(
        {
            "observation_distribution": oracle.observation_distribution,
            "latent_distribution": oracle.latent_distribution,
            "outcome_distribution": oracle.outcome_distribution,
            "expected_utility": oracle.expected_utility,
            "numerical_diagnostics": oracle.numerical_diagnostics,
        }
    )


def _single_policy(world: object, horizon: int, action_id: str) -> ActionPlan:
    for policy in world.policy_set(horizon):
        if (
            policy.kind is PlanKind.ACTION_SEQUENCE
            and len(policy.actions) == 1
            and policy.actions[0].offset == 0
            and policy.actions[0].action_id == action_id
        ):
            return policy
    raise AssertionError(f"missing single {action_id} policy")


@pytest.mark.parametrize("world_type", WORLD_TYPES)
def test_w16_w20_generators_are_deterministic_and_public_projection_is_clean(
    world_type: type,
) -> None:
    world = world_type()
    first = world.generate_episode(WorldSplit.SEALED_TEST, 812381, 1)
    second = world.generate_episode(WorldSplit.SEALED_TEST, 812381, 1)
    assert first.public_history.to_wire() == second.public_history.to_wire()
    assert first.hidden_state_at_cut == second.hidden_state_at_cut
    assert first.invariant_parameters == second.invariant_parameters
    assert first.factual_future == second.factual_future
    assert first.action_propensities == second.action_propensities

    candidate_wire = canonical_json_bytes(
        {"catalog": world.catalog.to_wire(), "history": first.public_history.to_wire()}
    )
    for forbidden in (
        b"environment_key",
        b"generator_seed",
        b"episode_index",
        b"hidden_state",
        b"class_index",
        b"mechanism",
        b"ood_attribution",
        b"tail_allocation",
        b"oracle_anchor",
    ):
        assert forbidden not in candidate_wire


@pytest.mark.parametrize("world_type", WORLD_TYPES)
def test_w16_w20_policy_branch_order_and_oracle_seed_are_inert(
    world_type: type,
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.VALIDATION, 777, 7)
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
def test_w16_w20_public_oracle_does_not_read_private_realization(
    world_type: type,
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.TRAIN, 199, 4)
    altered = replace(
        episode,
        case_key="judge-private-swap",
        hidden_state_at_cut={"adversarial": 99999.0},
        invariant_parameters={"adversarial": -99999.0},
        diagnostic_target={"adversarial": 1.0},
        factual_future=[{"future": 99999.0}],
        oracle_anchor={"oracle": -99999.0},
    )
    for policy in world.policy_set(4):
        assert _oracle_signature(
            world.counterfactual(episode, policy, 4, 13)
        ) == _oracle_signature(world.counterfactual(altered, policy, 4, 13))


def test_w16_primary_scope_is_exactly_equivalent_before_extension_reveal() -> None:
    world = W16World()
    left, right = world.pre_result_alias_pair()
    assert left.public_history.digest == right.public_history.digest
    assert left.invariant_parameters != right.invariant_parameters
    noop = world.extension_policy_set(4)[0]
    left_oracle = world.counterfactual(left, noop, 4, 0)
    right_oracle = world.counterfactual(right, noop, 4, 0)
    assert _oracle_signature(left_oracle) == _oracle_signature(right_oracle)
    assert left_oracle.latent_distribution["diagnostic_posterior"] == {
        "C0": 0.5,
        "C1": 0.5,
    }
    assert world.catalog.digest != world.extension_catalog.digest
    assert world.extension_commitment == world.extension_commitment


def test_w16_local_q2_update_splits_one_sealed_old_prefix_only_after_result() -> None:
    world = W16World()
    negative, positive = world.extension_result_pair()
    negative_prefix = [
        event.to_wire()
        for event in negative.public_history.events
        if event.payload.get("channel_id") != "obs_2"
    ]
    positive_prefix = [
        event.to_wire()
        for event in positive.public_history.events
        if event.payload.get("channel_id") != "obs_2"
    ]
    assert negative_prefix == positive_prefix
    delta = world.extension_delta(1, seed=9, episode_index=2)
    assert {event.payload.get("channel_id") for event in delta.events} <= {None, "obs_2"}
    assert "obs_0" not in {event.payload.get("channel_id") for event in delta.events}

    noop = world.extension_policy_set(4)[0]
    posterior_negative = world.counterfactual(
        negative, noop, 4, 1
    ).latent_distribution["diagnostic_posterior"]
    posterior_positive = world.counterfactual(
        positive, noop, 4, 1
    ).latent_distribution["diagnostic_posterior"]
    assert posterior_negative == pytest.approx({"C0": 0.95, "C1": 0.05})
    assert posterior_positive == pytest.approx({"C0": 0.05, "C1": 0.95})


def test_w16_legacy_scope_insufficient_is_honest_limit_not_prediction_failure() -> None:
    assert W16World.legacy_extension_verdict("scope_insufficient") == "HONEST_LIMIT"
    assert (
        W16World.legacy_extension_verdict(
            "supported", supported_and_correct=True
        )
        == "PASS"
    )
    assert W16World.legacy_extension_verdict("supported") == "HARD_FAILURE"


def test_w17_s0_oracle_ignores_context_that_only_future_a2_makes_relevant() -> None:
    world = W17World()
    marker_c0, marker_c1 = world.extension_split_pair()
    assert marker_c0.public_history.digest != marker_c1.public_history.digest
    for policy in world.policy_set(4):
        assert _oracle_signature(
            world.counterfactual(marker_c0, policy, 4, 3)
        ) == _oracle_signature(world.counterfactual(marker_c1, policy, 4, 3))


def test_w17_revealed_a2_splits_old_histories_without_rewriting_s0() -> None:
    world = W17World()
    base_left, base_right = world.extension_split_pair()
    base_left_wire = base_left.public_history.to_wire()
    left = world.as_extension_episode(base_left)
    right = world.as_extension_episode(base_right)
    assert base_left.public_history.to_wire() == base_left_wire
    assert left.public_history.events == base_left.public_history.events
    assert left.public_history.catalog_digest == world.extension_catalog.digest

    a2 = next(
        policy
        for policy in world.extension_policy_set(4)
        if policy.kind is PlanKind.ACTION_SEQUENCE
        and len(policy.actions) == 1
        and policy.actions[0].action_id == "A2"
    )
    left_oracle = world.counterfactual(left, a2, 4, 0)
    right_oracle = world.counterfactual(right, a2, 4, 0)
    assert abs(left_oracle.expected_utility - right_oracle.expected_utility) > 0.30
    left_first = left_oracle.observation_distribution["components"]
    right_first = right_oracle.observation_distribution["components"]
    assert left_first != right_first


def test_w17_scope_insufficient_and_explicit_migration_semantics() -> None:
    assert W17World.legacy_extension_verdict("scope_insufficient") == "HONEST_LIMIT"
    assert (
        W17World.legacy_extension_verdict(
            "scope_insufficient", replayed_history=True
        )
        == "HARD_FAILURE"
    )
    assert (
        W17World.legacy_extension_verdict(
            "supported", supported_and_correct=True
        )
        == "PASS"
    )


def test_w18_sealed_split_contains_half_attributable_half_irreducible_c2() -> None:
    world = W18World()
    c2_rows = [
        world.generate_episode(WorldSplit.SEALED_TEST, 888, index)
        for index in range(20)
        if index % 5 == 0
    ]
    tags = [world.attribution_tag(episode) for episode in c2_rows]
    assert tags.count("OOD_ATTRIBUTABLE") == 2
    assert tags.count("OOD_IRREDUCIBLE") == 2
    assert all(
        episode.invariant_parameters["mechanism"] == "C2" for episode in c2_rows
    )


def test_w18_only_publicly_attributable_ood_is_forced_and_known_extreme_is_kept() -> None:
    world = W18World()
    attributable = world.attributable_ood_fixture()
    extreme = world.known_extreme_fixture()
    assert world.public_ood_attributable(attributable)
    assert world.attribution_tag(attributable) == "OOD_ATTRIBUTABLE"
    assert world.scored_for_forced_ood(world.attribution_tag(attributable))
    assert not world.public_ood_attributable(extreme)
    assert world.attribution_tag(extreme) == "KNOWN_EXTREME"
    assert extreme.diagnostic_target == {"C0": 1.0, "C1": 0.0, "unknown": 0.0}


def test_w18_irreducible_private_alias_is_exact_and_excluded_from_ood_error() -> None:
    world = W18World()
    unseen, known = world.irreducible_alias_pair()
    assert unseen.public_history.digest == known.public_history.digest
    assert world.attribution_tag(unseen) == "OOD_IRREDUCIBLE"
    assert world.attribution_tag(known) == "KNOWN"
    assert not world.scored_for_forced_ood(world.attribution_tag(unseen))
    for policy in world.policy_set(4):
        assert _oracle_signature(
            world.counterfactual(unseen, policy, 4, 1)
        ) == _oracle_signature(world.counterfactual(known, policy, 4, 1))


@pytest.mark.parametrize("split", list(WorldSplit))
@pytest.mark.parametrize("seed", (1, 991827))
def test_w19_population_has_exactly_one_tail_per_64_and_frozen_counts(
    split: WorldSplit, seed: int
) -> None:
    world = W19World()
    size = world.population_size(split)
    flags = [world.is_population_tail(split, seed, index) for index in range(size)]
    assert sum(flags) == world.expected_tail_count(split) == size // 64
    assert all(sum(flags[start : start + 64]) == 1 for start in range(0, size, 64))


def test_w19_dedicated_tail_probe_is_not_in_population_denominator() -> None:
    world = W19World()
    common, tail = world.tail_probe_pair(seed=17, probe_index=255)
    assert common.invariant_parameters["cohort"] == "dedicated-probe"
    assert tail.invariant_parameters["cohort"] == "dedicated-probe"
    assert common.invariant_parameters["population_weight"] == 0.0
    assert tail.invariant_parameters["population_weight"] == 0.0
    assert not common.oracle_anchor["probe_cohort_in_population_denominator"]
    with pytest.raises(ValueError):
        world.tail_probe_pair(seed=17, probe_index=256)


def test_w19_unmeasured_private_tail_alias_keeps_population_mixture() -> None:
    world = W19World()
    common, tail = world.unidentified_tail_alias_pair()
    assert common.public_history.digest == tail.public_history.digest
    for policy in world.policy_set(4):
        assert _oracle_signature(
            world.counterfactual(common, policy, 4, 0)
        ) == _oracle_signature(world.counterfactual(tail, policy, 4, 0))
    posterior = world.counterfactual(
        common, world.policy_set(4)[0], 4, 0
    ).latent_distribution["diagnostic_posterior"]
    assert posterior["C1"] == pytest.approx(1.0 / 64.0)


def test_w19_marker_evidence_changes_safe_action_and_tail_metrics_remain_visible() -> None:
    world = W19World()
    common, tail = world.tail_probe_pair()
    a1 = _single_policy(world, 4, "A1")
    a2 = _single_policy(world, 4, "A2")
    common_values = [
        world.counterfactual(common, policy, 4, 0).expected_utility
        for policy in (a1, a2)
    ]
    tail_values = [
        world.counterfactual(tail, policy, 4, 0).expected_utility
        for policy in (a1, a2)
    ]
    assert common_values[0] > common_values[1]
    assert tail_values[1] > tail_values[0]
    assert tail_values[1] - tail_values[0] > 10.0
    outcome = world.counterfactual(tail, a1, 4, 0).outcome_distribution
    assert outcome["catastrophic_action_probability"] > 0.40
    assert "tail_only_regret" in outcome["reporting_contract"]
    assert "cvar95" in outcome["reporting_contract"]


def test_w20_public_performed_actions_close_exact_exposure_memory() -> None:
    world = W20World()
    for index in range(16):
        episode = world.generate_episode(WorldSplit.TRAIN, 20, index)
        assert world.exposure_from_history(episode) == pytest.approx(
            episode.hidden_state_at_cut["r"], abs=1e-12
        )
        assert all(
            event.payload["action_id"] in {"A1", "A2"}
            for event in episode.public_history.events
            if event.kind is EventKind.PERFORMED_TREATMENT
        )


def test_w20_same_current_x_different_exposure_reverses_a1_response() -> None:
    world = W20World()
    low, high = world.exposure_collision_pair()
    assert world.sufficient_state(low)[0] == world.sufficient_state(high)[0]
    assert world.sufficient_state(low)[1] < 0.75
    assert world.sufficient_state(high)[1] >= 0.75
    a1 = _single_policy(world, 1, "A1")
    low_next = world.counterfactual(
        low, a1, 1, 0
    ).latent_distribution["steps"][0]["mean"]
    high_next = world.counterfactual(
        high, a1, 1, 0
    ).latent_distribution["steps"][0]["mean"]
    current = world.sufficient_state(low)[0]
    natural_next = 0.90 * current + 0.10
    assert low_next < natural_next
    assert high_next > natural_next


def test_w20_noop_decays_memory_but_does_not_clear_it() -> None:
    world = W20World()
    _, high = world.exposure_collision_pair()
    before = world.sufficient_state(high)[1]
    noop = next(policy for policy in world.policy_set(1) if policy.kind is PlanKind.NO_NEW_ACTION)
    after = world.counterfactual(
        high, noop, 1, 0
    ).latent_distribution["steps"][0]["exposure_memory"]
    assert after == pytest.approx(0.5 * before)
    assert after > 0.0


def test_w20_different_history_same_sufficient_state_is_oracle_equivalent() -> None:
    world = W20World()
    first, second = world.sufficient_statistic_false_split_pair()
    assert first.public_history.digest != second.public_history.digest
    assert world.sufficient_state(first) == world.sufficient_state(second) == (0.65, 0.5)
    for policy in world.policy_set(4):
        assert _oracle_signature(
            world.counterfactual(first, policy, 4, 1)
        ) == _oracle_signature(world.counterfactual(second, policy, 4, 999))


def test_information_attribution_marks_w20_collision_but_not_w18_alias() -> None:
    w20 = W20World()
    low, high = w20.exposure_collision_pair()
    policies = (w20.policy_set(1)[0], _single_policy(w20, 1, "A1"))
    low_values = tuple(
        w20.counterfactual(low, policy, 1, 0).expected_utility for policy in policies
    )
    high_values = tuple(
        w20.counterfactual(high, policy, 1, 0).expected_utility for policy in policies
    )
    collision = classify_pair(
        PairProbe(
            pair_id="w20-exposure",
            state_hash_a="same",
            state_hash_b="same",
            candidate_signature_a=(0.0,),
            candidate_signature_b=(0.0,),
            oracle_signature_a=(w20.sufficient_state(low)[1],),
            oracle_signature_b=(w20.sufficient_state(high)[1],),
            oracle_action_values_a=low_values,
            oracle_action_values_b=high_values,
            information_relation=InformationRelation.DISTINGUISHABLE,
            intervention_identifiable=True,
        ),
        candidate_same_epsilon=0.008,
        candidate_split_delta=0.38,
        oracle_distinguishable_delta=0.38,
        oracle_equivalent_epsilon=0.008,
        catastrophic_margin=0.10,
    )
    assert collision.dangerous_collision
    assert collision.attributable_collision

    w18 = W18World()
    unseen, known = w18.irreducible_alias_pair()
    noop = w18.policy_set(1)[0]
    unseen_value = w18.counterfactual(unseen, noop, 1, 0).expected_utility
    known_value = w18.counterfactual(known, noop, 1, 0).expected_utility
    alias = classify_pair(
        PairProbe(
            pair_id="w18-alias",
            state_hash_a="same",
            state_hash_b="same",
            candidate_signature_a=(0.0,),
            candidate_signature_b=(0.0,),
            oracle_signature_a=(unseen_value,),
            oracle_signature_b=(known_value,),
            oracle_action_values_a=(unseen_value,),
            oracle_action_values_b=(known_value,),
            information_relation=InformationRelation.IDENTICAL_PREFIX,
            intervention_identifiable=False,
        ),
        candidate_same_epsilon=0.005,
        candidate_split_delta=0.35,
        oracle_distinguishable_delta=0.35,
        oracle_equivalent_epsilon=0.005,
        catastrophic_margin=0.75,
    )
    assert not alias.dangerous_collision
    assert not alias.attributable_collision


def test_information_attribution_marks_w20_full_history_false_split() -> None:
    world = W20World()
    first, second = world.sufficient_statistic_false_split_pair()
    noop = world.policy_set(1)[0]
    value_a = world.counterfactual(first, noop, 1, 0).expected_utility
    value_b = world.counterfactual(second, noop, 1, 0).expected_utility
    result = classify_pair(
        PairProbe(
            pair_id="w20-false-split",
            state_hash_a="history-a",
            state_hash_b="history-b",
            candidate_signature_a=(0.0,),
            candidate_signature_b=(1.0,),
            oracle_signature_a=(value_a,),
            oracle_signature_b=(value_b,),
            oracle_action_values_a=(value_a,),
            oracle_action_values_b=(value_b,),
            information_relation=InformationRelation.DISTINGUISHABLE,
            intervention_identifiable=True,
        ),
        candidate_same_epsilon=0.008,
        candidate_split_delta=0.38,
        oracle_distinguishable_delta=0.38,
        oracle_equivalent_epsilon=0.008,
        catastrophic_margin=0.80,
    )
    assert result.false_split
    assert not result.dangerous_collision
