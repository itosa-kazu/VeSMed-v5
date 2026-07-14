from __future__ import annotations

from dataclasses import replace
import math

import pytest

from prototype.unified_map.schema import EventKind
from prototype.unified_map.worlds.base import MicroWorld, PrivateEpisode, WorldSplit
from prototype.unified_map.worlds.w06 import World06
from prototype.unified_map.worlds.w07 import World07
from prototype.unified_map.worlds.w08 import World08
from prototype.unified_map.worlds.w09 import World09
from prototype.unified_map.worlds.w10 import World10


WORLD_CASES = (
    (World06, 4, 1e-10),
    (World07, 4, 1e-10),
    (World08, 4, 1e-9),
    (World09, 4, 1e-10),
    (World10, 4, 0.012),
)


def _malicious_private_swap(episode: PrivateEpisode) -> PrivateEpisode:
    """Replace every realised judge target while preserving candidate bytes."""

    flipped = {
        label: float(index == 0)
        for index, label in enumerate(reversed(tuple(episode.diagnostic_target)))
    }
    return replace(
        episode,
        case_key=episode.case_key + "-private-swap",
        environment_key="malicious-private-environment-key",
        split=(
            WorldSplit.TRAIN
            if episode.split is not WorldSplit.TRAIN
            else WorldSplit.SEALED_TEST
        ),
        generator_seed=episode.generator_seed + 999,
        hidden_state_at_cut={"malicious_private_truth": 9.0},
        invariant_parameters={"malicious_private_parameter": -7.0},
        diagnostic_target=flipped,
        factual_future=[{"private_future": -123.0}],
        action_propensities=[{"private_propensity": 0.999}],
        factual_utility=episode.factual_utility - 1000.0,
        oracle_anchor={"private_anchor": "changed"},
    )


@pytest.mark.parametrize(("world_type", "horizon", "_tolerance"), WORLD_CASES)
def test_scoring_oracle_is_exactly_invariant_to_realised_private_swap(
    world_type: type[MicroWorld], horizon: int, _tolerance: float
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 2601, 17)
    swapped = _malicious_private_swap(episode)
    assert episode.public_history.to_wire() == swapped.public_history.to_wire()
    for policy in world.policy_set(horizon):
        first = world.counterfactual(episode, policy, horizon, 701)
        second = world.counterfactual(swapped, policy, horizon, 701)
        assert first == second


@pytest.mark.parametrize(("world_type", "horizon", "tolerance"), WORLD_CASES)
def test_source_distinct_reference_agrees_with_public_history_oracle(
    world_type: type[MicroWorld], horizon: int, tolerance: float
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 2701, 11)
    for policy in world.policy_set(horizon):
        production = world.counterfactual(episode, policy, horizon, 31337)
        reference = world.reference_counterfactual(
            episode, policy, horizon, oracle_seed=31337
        )
        assert production.expected_utility == pytest.approx(reference, abs=tolerance)


@pytest.mark.parametrize(("world_type", "horizon", "_tolerance"), WORLD_CASES)
def test_reference_does_not_call_production_posterior_or_tail_solver(
    world_type: type[MicroWorld],
    horizon: int,
    _tolerance: float,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.VALIDATION, 2801, 5)
    policy = world.policy_set(horizon)[0]

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("reference reused a production core")

    monkeypatch.setattr(world_type, "_posterior", forbidden)
    if world_type is World10:
        monkeypatch.setattr(world_type, "_tail_probability", forbidden)
    value = world.reference_counterfactual(
        episode, policy, horizon, oracle_seed=19
    )
    assert isinstance(value, float) and math.isfinite(value)


DECLARED_STRATA = {
    World06: {"iid_support", "boundary_tail", "policy_coverage_holdout"},
    World07: {"iid_support", "boundary_tail", "policy_coverage_holdout"},
    World08: {"iid_support", "boundary_tail", "schedule_time_holdout"},
    World09: {"iid_support", "boundary_tail"},
    World10: {"iid_support", "boundary_tail", "compositional_holdout"},
}


@pytest.mark.parametrize("world_type", tuple(DECLARED_STRATA))
def test_exact_strata_classifier_matches_materialised_anchor_and_registry(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    seen: set[str] = set()
    for index in range(512):
        episode = world.generate_episode(WorldSplit.SEALED_TEST, 2901, index)
        strata = world.strata_for_episode(episode)
        assert type(strata) is tuple
        assert strata[0] == "iid_support"
        assert set(strata) <= DECLARED_STRATA[world_type]
        assert tuple(episode.oracle_anchor["split_strata"]) == strata
        seen.update(strata)
    assert seen == DECLARED_STRATA[world_type]


@pytest.mark.parametrize("world_type", (World06, World07, World08, World09, World10))
def test_behavior_propensity_ledger_names_public_inputs_and_selected_events(
    world_type: type[MicroWorld],
) -> None:
    episode = world_type().generate_episode(WorldSplit.SEALED_TEST, 3001, 3)
    assert episode.action_propensities
    for row in episode.action_propensities:
        assert row["conditioning"] == "available_public_prefix"
        assert isinstance(row["public_inputs"], dict)
        for probability_group in ("action", "check"):
            if probability_group in row:
                probabilities = row[probability_group]
                assert sum(probabilities.values()) == pytest.approx(1.0)
                assert all(value > 0.0 for value in probabilities.values())
        if "selected_action" in row:
            assert row["selected_action"] in row["action"]
        if "selected_check" in row:
            assert row["selected_check"] in row["check"]


def test_w08_every_visible_result_respects_available_cut_and_public_replay() -> None:
    world = World08()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 3101, 6)
    assert all(event.available_at <= 0 for event in episode.public_history.events)
    for row in episode.action_propensities:
        tick = row["tick"]
        visible_values = [
            float(event.payload["value"])
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.available_at <= tick
        ]
        expected = visible_values[-1] if visible_values else 0.0
        assert row["public_inputs"]["latest_available_value"] == pytest.approx(
            expected
        )

    fixtures = world.probe_fixtures()
    early, late = fixtures["availability_equivalent"]
    assert early.public_history != late.public_history
    for policy in world.policy_set(4):
        assert world.counterfactual(early, policy, 4, 1) == world.counterfactual(
            late, policy, 4, 1
        )


def test_w10_compositional_holdout_is_real_unseen_q1_sensor_subset() -> None:
    world = World10()
    train_subsets: set[tuple[int, ...]] = set()
    test_holdout = 0
    for split, count in ((WorldSplit.TRAIN, 256), (WorldSplit.SEALED_TEST, 512)):
        for index in range(count):
            episode = world.generate_episode(split, 3201, index)
            grouped: dict[tuple[int, int], set[int]] = {}
            for event in episode.public_history.events:
                if (
                    event.kind is EventKind.OBSERVATION_AVAILABLE
                    and event.payload.get("check_id") == "Q1"
                ):
                    key = (int(event.collected_at), int(event.available_at))
                    grouped.setdefault(key, set()).add(int(event.payload["assay_slot"]))
            subsets = {tuple(sorted(value)) for value in grouped.values()}
            if split is WorldSplit.TRAIN:
                train_subsets.update(subsets)
            elif "compositional_holdout" in world.strata_for_episode(episode):
                test_holdout += 1
                assert (1, 2) in subsets
    assert (1, 2) not in train_subsets
    assert test_holdout > 0
