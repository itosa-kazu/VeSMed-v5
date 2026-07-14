from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from prototype.unified_map.canonical import ProtocolViolation
from prototype.unified_map.world_registry import WORLD_REGISTRY
from prototype.unified_map.worlds.base import MicroWorld, PrivateEpisode, WorldSplit
from prototype.unified_map.worlds.w11 import World11
from prototype.unified_map.worlds.w12 import World12
from prototype.unified_map.worlds.w13 import World13
from prototype.unified_map.worlds.w14 import World14
from prototype.unified_map.worlds.w15 import World15A, World15B


WORLD_PANELS = (
    ("W11", "primary", World11),
    ("W12", "primary", World12),
    ("W13", "primary", World13),
    ("W14", "primary", World14),
    ("W15", "W15A-randomized-identifiable", World15A),
    ("W15", "W15B-observational-nonidentified", World15B),
)


def _declared(slot: str, panel_id: str) -> tuple[str, ...]:
    return next(
        panel.strata
        for panel in WORLD_REGISTRY[slot].panels
        if panel.panel_id == panel_id
    )


def _population_counts(
    world: MicroWorld, *, seed: int, count: int
) -> Counter[str]:
    result: Counter[str] = Counter()
    classifier = getattr(world, "strata_for_episode")
    for index in range(count):
        result.update(
            classifier(
                world.generate_episode(WorldSplit.SEALED_TEST, seed, index)
            )
        )
    return result


@pytest.mark.parametrize("slot,panel_id,world_type", WORLD_PANELS)
@pytest.mark.parametrize("split", tuple(WorldSplit))
def test_population_strata_are_exact_registry_ordered_and_never_pair_probes(
    slot: str,
    panel_id: str,
    world_type: type[MicroWorld],
    split: WorldSplit,
) -> None:
    world = world_type()
    declared = _declared(slot, panel_id)
    for index in range(24):
        episode = world.generate_episode(split, 8100 + index, index)
        first = world.strata_for_episode(episode)  # type: ignore[attr-defined]
        second = world.strata_for_episode(episode)  # type: ignore[attr-defined]
        assert first == second
        assert first[0] == "iid_support"
        assert len(first) == len(set(first))
        assert first == tuple(item for item in declared if item in first)
        assert set(first) <= set(declared)
        # Pair fixtures are materialized in the probe denominator.  A broad
        # population cell whose historical name happens to contain "probe"
        # must not silently enter that cohort.
        assert "behavior_pair" not in first


def test_sealed_population_allocation_is_deterministic_and_nonempty() -> None:
    # Modular generator cells have exact counts over one complete allocation
    # cycle.  Public-value boundary cells use a fixed larger deterministic
    # cohort so their support, rather than a private label, is snapshotted.
    cases = (
        (World11(), 811, 20, {"iid_support": 20, "boundary_tail": 6}),
        (
            World12(),
            812,
            10,
            {
                "iid_support": 10,
                "boundary_tail": 2,
                "compositional_holdout": 5,
            },
        ),
        (
            World13(),
            813,
            10,
            {
                "iid_support": 10,
                "boundary_tail": 2,
                "compositional_holdout": 2,
            },
        ),
        (
            World14(),
            814,
            10,
            {
                "iid_support": 10,
                "boundary_tail": 5,
                "schedule_time_holdout": 2,
            },
        ),
        (
            World15A(),
            815,
            10,
            {
                "iid_support": 10,
                "boundary_tail": 4,
                "policy_coverage_holdout": 5,
            },
        ),
        (
            World15B(),
            816,
            200,
            {
                "iid_support": 200,
                "boundary_tail": 22,
                "policy_coverage_holdout": 200,
            },
        ),
    )
    for world, seed, count, expected in cases:
        assert dict(_population_counts(world, seed=seed, count=count)) == expected
        assert dict(_population_counts(world, seed=seed, count=count)) == expected


def test_declared_pair_probe_support_is_explicit_and_outside_population() -> None:
    probe_sets = (
        (World11(), ("distinguishable_fixture", "equivalent_fixture")),
        (
            World14(),
            (
                "distinguishable_fixture",
                "equivalent_fixture",
                "alpha_equivalent_fixture",
            ),
        ),
        (World15A(), ("distinguishable_fixture", "equivalent_fixture")),
        (World15B(), ("nonidentified_twin_fixture", "equivalent_fixture")),
    )
    for world, method_names in probe_sets:
        for method_name in method_names:
            pair = getattr(world, method_name)()
            assert len(pair) == 2
            for episode in pair:
                assert "behavior_pair" in world.strata_for_episode(episode)  # type: ignore[attr-defined]

        for index in range(40):
            population = world.generate_episode(WorldSplit.SEALED_TEST, 8201, index)
            assert "behavior_pair" not in world.strata_for_episode(population)  # type: ignore[attr-defined]

    # W15B makes the denominator separation especially explicit: adjacent
    # population rows are observational twins but are not probe-cohort rows;
    # the producer returns public-identical judge-tagged clones for that role.
    w15b = World15B()
    population = (
        w15b.generate_episode(WorldSplit.SEALED_TEST, 8203, 0),
        w15b.generate_episode(WorldSplit.SEALED_TEST, 8203, 1),
    )
    probe = w15b.nonidentified_twin_fixture(seed=8203, confounder=0)
    assert population[0].public_history == population[1].public_history
    assert probe[0].public_history == probe[1].public_history
    assert all("behavior_pair" not in w15b.strata_for_episode(row) for row in population)
    assert all("behavior_pair" in w15b.strata_for_episode(row) for row in probe)


@pytest.mark.parametrize("slot,panel_id,world_type", WORLD_PANELS)
def test_stratum_membership_does_not_read_private_realized_labels(
    slot: str,
    panel_id: str,
    world_type: type[MicroWorld],
) -> None:
    del slot, panel_id
    world = world_type()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 8301, 5)
    before = world.strata_for_episode(episode)  # type: ignore[attr-defined]
    private_swap = replace(
        episode,
        hidden_state_at_cut={"poison_private_state": 9.9e99},
        invariant_parameters={"poison_private_label": "opposite"},
        diagnostic_target={"C0": 0.0, "C1": 1.0},
    )
    assert world.strata_for_episode(private_swap) == before  # type: ignore[attr-defined]


def test_boundary_and_policy_witnesses_are_checked_against_real_material() -> None:
    w11 = World11()
    missing = w11.generate_episode(WorldSplit.SEALED_TEST, 8401, 14)
    assert "boundary_tail" in w11.strata_for_episode(missing)
    assert all(
        row["check_probabilities"]["Q1"] == 0.0
        for row in missing.action_propensities
    )
    with pytest.raises(ProtocolViolation):
        w11.strata_for_episode(
            replace(
                missing,
                action_propensities=[
                    {
                        **missing.action_propensities[0],
                        "check_probabilities": {"Q1": 0.5, "NoCheck": 0.5},
                    },
                    *missing.action_propensities[1:],
                ],
            )
        )

    w12 = World12()
    marker_missing = w12.generate_episode(WorldSplit.SEALED_TEST, 8403, 5)
    assert "boundary_tail" in w12.strata_for_episode(marker_missing)
    assert all(
        row["check_probabilities"]["Q1"] == 0.0
        for row in marker_missing.action_propensities
    )

    w15b = World15B()
    no_overlap = w15b.generate_episode(WorldSplit.SEALED_TEST, 8405, 0)
    assert "policy_coverage_holdout" in w15b.strata_for_episode(no_overlap)
    with pytest.raises(ProtocolViolation):
        w15b.strata_for_episode(
            replace(
                no_overlap,
                action_propensities=[
                    {
                        **no_overlap.action_propensities[0],
                        "probabilities": {"A1": 0.5, "NoNewAction": 0.5},
                    }
                ],
            )
        )
