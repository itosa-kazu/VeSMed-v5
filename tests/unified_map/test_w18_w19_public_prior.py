from __future__ import annotations

from dataclasses import replace
import inspect

import pytest

from prototype.unified_map.canonical import canonical_json_bytes
from prototype.unified_map.oracle_certification import (
    NumericTolerance,
    compare_canonical_outputs,
    oracle_output_wire,
)
from prototype.unified_map.worlds.base import MicroWorld, PrivateEpisode, WorldSplit
from prototype.unified_map.worlds.w18 import W18World
from prototype.unified_map.worlds.w19 import W19World


def _semantic(value: object) -> dict[str, object]:
    return oracle_output_wire(value, include_numerical_diagnostics=False)


def _full_wire(value: object) -> bytes:
    return canonical_json_bytes(
        oracle_output_wire(value, include_numerical_diagnostics=True)
    )


def _full_private_cross_split_clone(
    episode: PrivateEpisode, split: WorldSplit, salt: int
) -> PrivateEpisode:
    """Replace every judge-only field while retaining the exact public query."""

    return replace(
        episode,
        case_key=f"private-cross-split-{split.value}-{salt}",
        environment_key=f"private-environment-{salt}",
        split=split,
        generator_seed=episode.generator_seed + 100_000 + salt,
        hidden_state_at_cut={"poison_hidden_state": 10_000.0 + salt},
        invariant_parameters={"poison_invariant": -10_000.0 - salt},
        diagnostic_target={"poison_target": 1.0},
        factual_future=[{"poison_future": salt}],
        action_propensities=[{"poison_propensity": salt}],
        factual_utility=-10_000.0 - salt,
        oracle_anchor={"poison_anchor": salt},
    )


def _stress_episode(world: MicroWorld) -> PrivateEpisode:
    if isinstance(world, W18World):
        # This overlap prefix exercises known and unknown posterior mass.
        return world.irreducible_alias_pair()[0]
    assert isinstance(world, W19World)
    # A positive rare-tail marker makes the safety mixture non-degenerate.
    return world.tail_probe_pair(seed=98119, probe_index=7)[1]


@pytest.mark.parametrize(
    ("world_type", "tolerance"),
    ((W18World, 3e-4), (W19World, 3e-8)),
)
def test_all_declared_policy_semantics_use_one_public_prior_across_splits(
    world_type: type[MicroWorld], tolerance: float
) -> None:
    world = world_type()
    source = _stress_episode(world)
    episodes = tuple(
        _full_private_cross_split_clone(source, split, index)
        for index, split in enumerate(WorldSplit, start=1)
    )
    assert len({episode.public_history.digest for episode in episodes}) == 1

    for horizon in world.catalog.horizons:
        policies = world.policy_set(horizon)
        assert policies
        for policy in policies:
            production = tuple(
                world.counterfactual(episode, policy, horizon, 53)
                for episode in episodes
            )
            reference = tuple(
                world.reference_counterfactual(episode, policy, horizon, 53)
                for episode in episodes
            )

            # The private split/id/seed/realization swap is byte-exact within
            # each independently implemented oracle.
            assert len({_full_wire(value) for value in production}) == 1
            assert len({_full_wire(value) for value in reference}) == 1

            # Production/reference remain independently implemented, so their
            # deterministic numerical solvers are compared by frozen tolerance.
            for actual, expected in zip(production, reference, strict=True):
                comparison = compare_canonical_outputs(
                    _semantic(actual),
                    _semantic(expected),
                    NumericTolerance(absolute=tolerance, relative=tolerance),
                )
                assert comparison.passed, comparison.to_wire()


def test_w18_known_extreme_is_scoreable_under_every_private_split_identity() -> None:
    world = W18World()
    source = world.known_extreme_fixture()
    episodes = tuple(
        _full_private_cross_split_clone(source, split, index)
        for index, split in enumerate(WorldSplit, start=11)
    )

    production = tuple(world.public_posterior(episode) for episode in episodes)
    reference = tuple(
        world.reference_public_posterior(episode) for episode in episodes
    )
    assert all(any(world.known_support(episode)) for episode in episodes)
    assert len({canonical_json_bytes(value) for value in production}) == 1
    assert len({canonical_json_bytes(value) for value in reference}) == 1
    for actual, expected in zip(production, reference, strict=True):
        assert actual == pytest.approx(expected, abs=2e-4)
        assert sum(actual.values()) == pytest.approx(1.0, abs=1e-12)


def test_w19_generator_quota_remains_exactly_one_tail_per_64() -> None:
    world = W19World()
    for split in WorldSplit:
        manifest = world.population_quota_manifest(split)
        assert manifest["tail"] * 64 == manifest["population"]
        audit = world.audit_population_quota(split, 98123)
        assert audit == manifest


@pytest.mark.parametrize(
    ("world_type", "method_names"),
    (
        (
            W18World,
            (
                "known_support",
                "public_posterior",
                "reference_public_posterior",
                "counterfactual",
                "reference_counterfactual",
            ),
        ),
        (
            W19World,
            (
                "public_posterior",
                "reference_public_posterior",
                "counterfactual",
                "reference_counterfactual",
            ),
        ),
    ),
)
def test_scoring_entrypoints_do_not_read_private_episode_split_directly(
    world_type: type[MicroWorld], method_names: tuple[str, ...]
) -> None:
    for method_name in method_names:
        source = inspect.getsource(getattr(world_type, method_name))
        assert "episode.split" not in source
