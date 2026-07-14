from __future__ import annotations

import math
from dataclasses import replace

import pytest

from prototype.unified_map.canonical import canonical_json_bytes
from prototype.unified_map.oracle_certification import (
    NumericTolerance,
    OracleProbe,
    PrivateSwapProbe,
    certify_oracle_pair,
)
from prototype.unified_map.schema import EventKind, PlanKind
from prototype.unified_map.worlds.base import WorldSplit
from prototype.unified_map.worlds.w20 import W20World


def _semantic_wire(value: object) -> bytes:
    return canonical_json_bytes(
        {
            "policy": value.policy.to_wire(),
            "horizon": value.horizon,
            "observation_distribution": value.observation_distribution,
            "latent_distribution": value.latent_distribution,
            "outcome_distribution": value.outcome_distribution,
            "expected_utility": value.expected_utility,
        }
    )


def _full_wire(value: object) -> bytes:
    return canonical_json_bytes(
        {
            "semantic": _semantic_wire(value).decode("utf-8"),
            "numerical_diagnostics": value.numerical_diagnostics,
        }
    )


def _adaptive_policy(world: W20World, horizon: int = 4):
    return next(
        plan
        for plan in world.policy_set(horizon)
        if plan.kind is PlanKind.ACTION_SEQUENCE
        and len(plan.actions) == 1
        and plan.actions[0].action_id == "Q1"
        and plan.actions[0].parameters.get("adaptive_rule")
    )


def test_w20_scoring_oracle_conditions_on_the_entire_public_history() -> None:
    world = W20World()
    episode = world.generate_episode(WorldSplit.TRAIN, 92001, 7)
    events = list(episode.public_history.events)
    position = next(
        index
        for index, event in enumerate(events)
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == "obs_0"
        and event.collected_at == -4
    )
    events[position] = replace(
        events[position],
        payload={**events[position].payload, "value": events[position].payload["value"] + 1.0},
    )
    changed = replace(
        episode,
        public_history=replace(episode.public_history, events=tuple(events)),
    )
    policy = world.policy_set(4)[0]
    original = world.counterfactual(episode, policy, 4, 0)
    perturbed = world.counterfactual(changed, policy, 4, 0)
    first = original.latent_distribution["cut_posterior"]
    second = perturbed.latent_distribution["cut_posterior"]
    assert first["family"] == "gaussian-x-point-mass-r"
    assert first["state_channels"] == ["x", "r"]
    assert first["covariance"][1] == [0.0, 0.0]
    assert first["mean"][0] != pytest.approx(second["mean"][0], abs=1e-8)


def test_w20_production_and_reference_oracles_are_certifiably_source_distinct() -> None:
    world = W20World()
    episode = world.generate_episode(WorldSplit.VALIDATION, 92003, 9)
    swapped = replace(
        episode,
        case_key="w20-private-swap",
        hidden_state_at_cut={"x": -999.0, "r": 999.0},
        invariant_parameters={"malicious": True},
        diagnostic_target={"C0": 0.123, "C1": 0.877},
        factual_future=[{"private": "changed"}],
        action_propensities=[{"private": "changed"}],
        factual_utility=12345.0,
        oracle_anchor={"private": "changed"},
    )
    policy = _adaptive_policy(world)
    report = certify_oracle_pair(
        benchmark_id="ucm-w20-oracle-source-separation",
        production=world.counterfactual,
        reference=world.reference_counterfactual,
        probes=(OracleProbe("w20-adaptive", episode, policy, 4, 17),),
        private_swap_probes=(
            PrivateSwapProbe("w20-public-only", episode, swapped, policy, 4, 17),
        ),
        tolerance=NumericTolerance(absolute=2e-10, relative=2e-10),
    )
    assert report.passed, report.to_wire()
    assert report.source_separation.passed
    assert report.production_implementation.implementation_digest != (
        report.reference_implementation.implementation_digest
    )


def test_w20_source_distinct_oracles_agree_on_every_frozen_policy_shape() -> None:
    world = W20World()
    episodes = (
        world.generate_episode(WorldSplit.TRAIN, 92013, 3),
        world.generate_episode(WorldSplit.VALIDATION, 92013, 4),
        world.exposure_collision_pair(92013)[1],
    )
    for episode in episodes:
        for horizon in world.catalog.horizons:
            for policy in world.policy_set(horizon):
                production = world.counterfactual(episode, policy, horizon, 1)
                reference = world.reference_counterfactual(
                    episode, policy, horizon, 2**127
                )
                assert _semantic_wire(production) == _semantic_wire(reference)


def test_w20_noop_stop_and_continue_are_exactly_public_only_for_both_oracles() -> None:
    world = W20World()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 92015, 17)
    changed = replace(
        episode,
        case_key="w20-private-only-change",
        hidden_state_at_cut={"x": 1e6, "r": -1e6},
        invariant_parameters={"private": "changed"},
        diagnostic_target={"C0": 0.25, "C1": 0.75},
        factual_future=[{"private": 1}],
        action_propensities=[{"private": 2}],
        factual_utility=-1e9,
        oracle_anchor={"private": 3},
    )
    policies = tuple(
        policy
        for policy in world.policy_set(4)
        if policy.kind
        in {
            PlanKind.NO_NEW_ACTION,
            PlanKind.STOP_CONTROLLABLE,
            PlanKind.CONTINUE_CURRENT,
        }
    )
    for solver in (world.counterfactual, world.reference_counterfactual):
        for policy in policies:
            assert _full_wire(solver(episode, policy, 4, 1)) == _full_wire(
                solver(changed, policy, 4, 2)
            )


def test_w20_false_split_pair_matches_full_posterior_and_all_behavior_oracles() -> None:
    world = W20World()
    first, second = world.sufficient_statistic_false_split_pair()
    assert first.public_history.digest != second.public_history.digest
    noop = next(
        plan for plan in world.policy_set(4) if plan.kind is PlanKind.NO_NEW_ACTION
    )
    first_cut = world.counterfactual(first, noop, 4, 0).latent_distribution[
        "cut_posterior"
    ]
    second_cut = world.counterfactual(second, noop, 4, 0).latent_distribution[
        "cut_posterior"
    ]
    assert first_cut["mean"] == pytest.approx(second_cut["mean"], abs=1e-12)
    assert first_cut["covariance"] == second_cut["covariance"]
    for policy in world.policy_set(4):
        assert _semantic_wire(world.counterfactual(first, policy, 4, 1)) == (
            _semantic_wire(world.counterfactual(second, policy, 4, 999))
        )


def test_w20_collision_pair_is_distinguished_by_the_behavior_oracle() -> None:
    world = W20World()
    low, high = world.exposure_collision_pair()
    policies = world.policy_set(4)
    low_values = tuple(world.counterfactual(low, p, 4, 0).expected_utility for p in policies)
    high_values = tuple(world.counterfactual(high, p, 4, 0).expected_utility for p in policies)
    low_cut = world.counterfactual(low, policies[0], 4, 0).latent_distribution[
        "cut_posterior"
    ]
    high_cut = world.counterfactual(high, policies[0], 4, 0).latent_distribution[
        "cut_posterior"
    ]
    assert low_cut["mean"][0] == pytest.approx(high_cut["mean"][0], abs=1e-12)
    assert low_cut["mean"][1] < 0.75 <= high_cut["mean"][1]
    assert max(abs(a - b) for a, b in zip(low_values, high_values, strict=True)) > 0.38


def test_w20_sealed_population_has_exact_frozen_25_25_20_15_15_strata() -> None:
    world = W20World()
    split = WorldSplit.SEALED_TEST
    expected = world.expected_frozen_stratum_counts(split)
    assert expected == {
        "response_reversal": 512,
        "sufficient_false_split": 512,
        "stop_continue": 410,
        "threshold_band": 307,
        "iid": 307,
    }
    counts = {name: 0 for name in expected}
    registry_tags: set[str] = set()
    pairs: dict[tuple[str, int], list[object]] = {}
    threshold_exposures = []
    stop_histories = []
    for index in range(world.population_size(split)):
        episode = world.generate_episode(split, 92005, index)
        name = world.frozen_stratum(episode)
        counts[name] += 1
        registry_tags.update(world.strata_for_episode(episode))
        pair_id = episode.oracle_anchor.get("frozen_pair_id")
        if pair_id is not None:
            pairs.setdefault((name, pair_id), []).append(episode)
        if name == "threshold_band":
            threshold_exposures.append(world.exposure_from_history(episode))
        if name == "stop_continue":
            stop_histories.append(episode)
    assert counts == expected
    assert registry_tags == {
        "iid_support",
        "boundary_tail",
        "compositional_holdout",
        "schedule_time_holdout",
        "policy_coverage_holdout",
        "behavior_pair",
    }
    assert all(value == pytest.approx(0.75) for value in threshold_exposures)
    assert all(
        any(
            event.kind is EventKind.PERFORMED_TREATMENT
            and event.occurred_at == -1
            and event.payload.get("action_id") == "A1"
            for event in episode.public_history.events
        )
        for episode in stop_histories
    )
    assert all(len(rows) == 2 for rows in pairs.values())
    for (name, _), rows in pairs.items():
        left, right = rows
        left_state = world.sufficient_state(left)
        right_state = world.sufficient_state(right)
        assert left_state[0] == right_state[0]
        if name == "response_reversal":
            assert min(left_state[1], right_state[1]) < 0.75
            assert max(left_state[1], right_state[1]) >= 0.75
        else:
            assert left_state == right_state

    noop = next(
        plan for plan in world.policy_set(4) if plan.kind is PlanKind.NO_NEW_ACTION
    )
    false_split_pairs = [
        rows
        for (name, _), rows in sorted(pairs.items())
        if name == "sufficient_false_split"
    ][:8]
    for left, right in false_split_pairs:
        assert _semantic_wire(world.counterfactual(left, noop, 4, 1)) == (
            _semantic_wire(world.counterfactual(right, noop, 4, 999))
        )


def test_w20_q1_behavior_propensity_delay_and_adaptive_branch_are_executable() -> None:
    world = W20World()
    selected = []
    for index in range(32):
        episode = world.generate_episode(WorldSplit.TRAIN, 92007, index)
        selected.extend(
            row
            for row in episode.action_propensities
            if row.get("kind") == "check" and row["selected"] == "Q1"
        )
        for row in (
            item for item in episode.action_propensities if item.get("kind") == "check"
        ):
            rhat = row["public_inputs"]["rhat"]
            expected = 0.10 + 0.30 / (1.0 + math.exp(-(rhat - 0.60)))
            assert row["probabilities"]["Q1"] == pytest.approx(expected, abs=1e-15)
            assert row["probabilities"]["NoCheck"] == pytest.approx(1.0 - expected)
        q1_results = [
            event
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_1"
        ]
        assert all(event.available_at == event.collected_at + 1 for event in q1_results)
        for result in q1_results:
            assert any(
                event.kind is EventKind.TEST_ORDERED
                and event.occurred_at == result.collected_at
                and event.payload.get("check_id") == "Q1"
                for event in episode.public_history.events
            )
            assert any(
                event.kind is EventKind.TEST_PERFORMED
                and event.occurred_at == result.collected_at
                and event.payload.get("check_id") == "Q1"
                for event in episode.public_history.events
            )
    assert selected

    adaptive = _adaptive_policy(world)
    episode = world.generate_episode(WorldSplit.VALIDATION, 92009, 11)
    oracle = world.counterfactual(episode, adaptive, 4, 0)
    components = oracle.observation_distribution["components"]
    assert {component["branch_action"] for component in components} == {"A1", "A2"}
    assert sum(component["weight"] for component in components) == pytest.approx(1.0)
    assert all(component["result_available_offset"] == 1 for component in components)
    cut_r = oracle.latent_distribution["cut_posterior"]["mean"][1]
    expected_below = 0.5 * (
        1.0 + math.erf((0.75 - cut_r) / (0.08 * math.sqrt(2.0)))
    )
    by_action = {component["branch_action"]: component for component in components}
    assert by_action["A1"]["weight"] == pytest.approx(expected_below, abs=1e-12)
    assert by_action["A1"]["steps"][0]["dose"] == 0.0
    assert by_action["A1"]["steps"][1]["dose"] == 1.0
    assert by_action["A2"]["steps"][1]["dose"] == 0.5
    assert oracle.outcome_distribution["check_cost"] == 0.08


def test_w20_factual_future_policy_ledger_declares_only_public_inputs() -> None:
    world = W20World()
    episode = world.generate_episode(WorldSplit.TRAIN, 92011, 3)
    assert episode.factual_future
    for row in episode.factual_future:
        public_inputs = row["decision_public_inputs"]
        probabilities = world.behavior_probabilities(
            public_inputs["latest_q0"], public_inputs["rhat"]
        )
        assert row["action_probabilities"] == pytest.approx(
            {
                "NoNewAction": probabilities[0],
                "A1": probabilities[1],
                "A2": probabilities[2],
            }
        )
        assert "x" not in public_inputs
        if row["q1_ordered"]:
            assert "obs_1" in row["observations"]
            assert row["q1_result_available_offset"] == row["offset"]
        else:
            assert "obs_1" not in row["observations"]
            assert row["q1_result_available_offset"] is None


def test_w20_forced_holdout_rows_record_actual_not_proposal_propensities() -> None:
    world = W20World()
    episodes = [
        world.generate_episode(WorldSplit.SEALED_TEST, 92017, index)
        for index in range(64)
    ]
    action_rows = [
        row
        for episode in episodes
        for row in episode.action_propensities
        if row.get("kind") == "action"
    ]
    assert action_rows
    for row in action_rows:
        assert sum(row["probabilities"].values()) == pytest.approx(1.0)
        assert row["probabilities"][row["selected"]] > 0.0
        public = row["public_inputs"]
        proposal = world.behavior_probabilities(
            public["latest_q0"], public["rhat"]
        )
        assert row["behavior_proposal_probabilities"] == pytest.approx(
            {
                "NoNewAction": proposal[0],
                "A1": proposal[1],
                "A2": proposal[2],
            }
        )
        if row["selection_mode"] == "frozen_stratum":
            assert row["probabilities"][row["selected"]] == 1.0
