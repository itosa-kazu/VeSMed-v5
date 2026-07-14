from __future__ import annotations

from dataclasses import replace

import pytest

from prototype.unified_map.schema import EventKind
from prototype.unified_map.worlds.base import MicroWorld, PrivateEpisode, WorldSplit
from prototype.unified_map.worlds.w11 import World11
from prototype.unified_map.worlds.w12 import World12
from prototype.unified_map.worlds.w13 import World13
from prototype.unified_map.worlds.w14 import World14
from prototype.unified_map.worlds.w15 import World15A, World15B


def _malicious_private_swap(
    world: MicroWorld, episode: PrivateEpisode
) -> PrivateEpisode:
    """Change every judge truth while preserving the exact candidate prefix."""

    if isinstance(world, World11):
        return replace(
            episode,
            hidden_state_at_cut={"components": [8.0, 0.0]},
            invariant_parameters={"mechanism_index": 1},
            diagnostic_target={"C0": 0.0, "C1": 1.0},
        )
    if isinstance(world, World12):
        return replace(
            episode,
            hidden_state_at_cut={"mechanism_activity": 8.0},
            invariant_parameters={"host_modifier": 1.40, "host_class": 1},
            diagnostic_target={"C0": 0.0, "C1": 1.0},
        )
    if isinstance(world, World13):
        return replace(
            episode,
            hidden_state_at_cut={"components": [1.5, 1.5]},
            invariant_parameters={"interaction_class": 2},
            diagnostic_target={"C0": 0.0, "C1": 0.0, "C2": 1.0},
        )
    if isinstance(world, World14):
        return replace(
            episode,
            hidden_state_at_cut={"current_activity": 4.0, "path_memory": 8.0},
            invariant_parameters={"memory_class": 1},
            diagnostic_target={"C0": 0.0, "C1": 1.0},
        )
    if isinstance(world, World15A):
        return replace(
            episode,
            hidden_state_at_cut={"severity": 6.0},
            invariant_parameters={"confounder": 1},
            diagnostic_target={"C0": 0.0, "C1": 1.0},
        )
    assert isinstance(world, World15B)
    old_model = str(episode.invariant_parameters["private_scm"])
    old_u = int(episode.hidden_state_at_cut["latent_confounder"])
    return replace(
        episode,
        hidden_state_at_cut={"latent_confounder": 1 - old_u},
        invariant_parameters={
            "private_scm": "Mminus" if old_model == "Mplus" else "Mplus"
        },
    )


@pytest.mark.parametrize(
    "world_type,horizon",
    (
        (World11, 4),
        (World12, 4),
        (World13, 4),
        (World14, 4),
        (World15A, 4),
        (World15B, 1),
    ),
)
def test_each_scoring_oracle_is_exactly_invariant_to_malicious_private_swap(
    world_type: type[MicroWorld], horizon: int
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 1701, 8)
    swapped = _malicious_private_swap(world, episode)
    assert episode.public_history.to_wire() == swapped.public_history.to_wire()
    for policy in world.policy_set(horizon):
        assert world.counterfactual(episode, policy, horizon, 7) == world.counterfactual(
            swapped, policy, horizon, 999
        )
    # The negative control is substantive: the explicitly judge-only realized
    # comparator can see the swap even though the scoring oracle cannot.
    policy = world.policy_set(horizon)[0]
    assert world.private_state_upper_bound(episode, policy, horizon) != (
        world.private_state_upper_bound(swapped, policy, horizon)
    )


@pytest.mark.parametrize(
    "world_type,horizon,tolerance",
    (
        (World11, 4, 0.06),
        (World12, 4, 0.01),
        (World13, 4, 0.05),
        (World14, 4, 0.04),
        (World15A, 4, 1e-5),
        (World15B, 1, 0.0),
    ),
)
def test_source_distinct_reference_solver_agrees_with_production(
    world_type: type[MicroWorld], horizon: int, tolerance: float
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 1771, 7)
    for policy in world.policy_set(horizon):
        production = world.counterfactual(episode, policy, horizon, 31)
        reference = world.reference_counterfactual(episode, policy, horizon)
        assert production.expected_utility == pytest.approx(
            reference, abs=tolerance
        )


@pytest.mark.parametrize(
    "world_type",
    (World11, World12, World13, World14, World15A),
)
def test_reference_path_does_not_call_production_posterior_or_transition(
    world_type: type[MicroWorld], monkeypatch: pytest.MonkeyPatch
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.VALIDATION, 1781, 4)
    policy = world.policy_set(1)[0]

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("reference reused a production core")

    monkeypatch.setattr(world_type, "_public_posterior", forbidden)
    monkeypatch.setattr(world_type, "_step", forbidden)
    value = world.reference_counterfactual(episode, policy, 1)
    assert isinstance(value, float)


def test_w14_future_propensities_replay_from_recorded_public_inputs() -> None:
    world = World14()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 1801, 9)
    future_rows = [
        row for row in episode.action_propensities if row["phase"] == "factual-future"
    ]
    assert len(future_rows) == 4
    for row in future_rows:
        public = row["public_inputs"]
        expected = world._behavior(
            float(public["latest_obs_0"]), float(public["public_ewma"])
        )
        assert row["probabilities"] == {
            "NoNewAction": expected[0],
            "A1": expected[1],
            "A2": expected[2],
        }
        assert sum(row["probabilities"].values()) == pytest.approx(1.0)
        assert sum(row["check_probabilities"].values()) == pytest.approx(1.0)
        assert row["selected_check"] in {"Q1", "NoCheck"}


def test_w15a_public_randomized_anchor_identifies_beneficial_effect_sign() -> None:
    world = World15A()
    episodes = tuple(
        world.generate_episode(WorldSplit.TRAIN, 1881, index)
        for index in range(400)
    )
    estimate = world.estimate_randomized_anchor_effect(episodes)
    # Reflection makes the marginal effect smaller than the interior -0.35,
    # but the public randomized contrast still identifies its beneficial sign.
    assert estimate < -0.15


def test_w15b_cut_is_before_action_and_outcome_and_no_action_is_prospective() -> None:
    world = World15B()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 1901, 0)
    assert all(
        event.kind is not EventKind.PERFORMED_TREATMENT
        for event in episode.public_history.events
    )
    assert all(
        not (
            event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_1"
        )
        for event in episode.public_history.events
    )
    assert episode.factual_future[0]["offset"] == 1
    assert episode.oracle_anchor["cut_semantics"] == "pre-action-pre-outcome"
    no_action, do_a1 = world.policy_set(1)
    no_action_result = world.counterfactual(episode, no_action, 1, 1)
    do_a1_result = world.counterfactual(episode, do_a1, 1, 1)
    assert no_action_result.observation_distribution["obs_1_support"] == [
        0.0,
        0.0,
        0.0,
        2.0,
    ]
    assert do_a1_result.observation_distribution["obs_1_support"] == [
        1.0,
        1.0,
        -1.0,
        1.0,
    ]
    assert no_action_result.latent_distribution["diagnostic_posterior"] == {
        "C0": 0.5,
        "C1": 0.5,
    }


def test_frozen_split_strata_and_probe_attribution_are_materialized() -> None:
    w11 = World11()
    counts11: dict[str, int] = {}
    for index in range(20):
        stratum = w11.generate_episode(
            WorldSplit.SEALED_TEST, 1951, index
        ).oracle_anchor["split_stratum"]
        counts11[stratum] = counts11.get(stratum, 0) + 1
    assert counts11 == {
        "iid": 8,
        "same-q0-opposite-source-probe": 6,
        "q1-missing": 3,
        "q1-contradictory-noise": 3,
    }

    w12 = World12()
    counts12: dict[str, int] = {}
    for index in range(10):
        stratum = w12.generate_episode(
            WorldSplit.SEALED_TEST, 1953, index
        ).oracle_anchor["stratum"]
        counts12[stratum] = counts12.get(stratum, 0) + 1
    assert counts12 == {
        "same-expression": 3,
        "same-mechanism-different-expression": 2,
        "marker-missing": 2,
        "iid": 3,
    }

    w14 = World14()
    counts14: dict[str, int] = {}
    for index in range(10):
        stratum = w14.generate_episode(
            WorldSplit.SEALED_TEST, 1955, index
        ).oracle_anchor["stratum"]
        counts14[stratum] = counts14.get(stratum, 0) + 1
    assert counts14 == {
        "same-current-different-memory": 3,
        "same-sufficient-state-different-history": 2,
        "long-gap": 2,
        "routine": 3,
    }

    for world in (w11, w12, World13(), w14, World15A()):
        first, second = world.collision_fixture()
        assert first.oracle_anchor["probe_attribution"] == "candidate-attributable"
        assert second.oracle_anchor["probe_attribution"] == "candidate-attributable"

    nonidentified = World15B().generate_episode(WorldSplit.SEALED_TEST, 1957, 0)
    assert (
        nonidentified.oracle_anchor["probe_attribution"]
        == "nonidentified-not-candidate-error"
    )
