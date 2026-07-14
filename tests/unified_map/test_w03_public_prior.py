from __future__ import annotations

from dataclasses import replace

import pytest

from prototype.unified_map.canonical import canonical_json_bytes
from prototype.unified_map.oracle_certification import (
    NumericTolerance,
    compare_canonical_outputs,
    oracle_output_wire,
)
from prototype.unified_map.worlds.base import PrivateEpisode, WorldSplit
from prototype.unified_map.worlds.w03 import W03World


def _semantic(value: object) -> dict[str, object]:
    return oracle_output_wire(value, include_numerical_diagnostics=False)


def _cross_split_private_clone(
    episode: PrivateEpisode, split: WorldSplit, salt: int
) -> PrivateEpisode:
    """Replace judge-only identity/realization fields, not the public query."""

    return replace(
        episode,
        case_key=f"w03-private-cross-split-{split.value}-{salt}",
        environment_key=f"w03-private-environment-{salt}",
        split=split,
        generator_seed=episode.generator_seed + 100_000 + salt,
        hidden_state_at_cut={"private_x": -1000.0 - salt},
        invariant_parameters={"private_drift": 1000.0 + salt},
        diagnostic_target={"C0": 0.321, "C1": 0.679},
        factual_future=[{"private_future": salt}],
        action_propensities=[{"private_propensity": salt}],
        factual_utility=-1000.0 - salt,
        oracle_anchor={"private_anchor": salt},
    )


@pytest.mark.parametrize("policy_index", (0, -1))
def test_same_public_query_is_exact_across_private_split_identity(
    policy_index: int,
) -> None:
    world = W03World()
    source = world.generate_episode(WorldSplit.SEALED_TEST, 93201, 6)
    episodes = tuple(
        _cross_split_private_clone(source, split, index)
        for index, split in enumerate(WorldSplit, start=1)
    )
    assert len({episode.public_history.digest for episode in episodes}) == 1
    policy = world.policy_set(4)[policy_index]

    for oracle in (world.counterfactual, world.reference_counterfactual):
        outputs = tuple(
            canonical_json_bytes(
                oracle_output_wire(
                    oracle(episode, policy, 4, 37),
                    include_numerical_diagnostics=True,
                )
            )
            for episode in episodes
        )
        assert len(set(outputs)) == 1


@pytest.mark.parametrize("split", tuple(WorldSplit))
@pytest.mark.parametrize("policy_index", (0, -1))
def test_production_and_reference_share_the_frozen_public_prior(
    split: WorldSplit, policy_index: int
) -> None:
    world = W03World()
    source = world.generate_episode(WorldSplit.SEALED_TEST, 93203, 7)
    episode = _cross_split_private_clone(source, split, 11)
    policy = world.policy_set(4)[policy_index]
    comparison = compare_canonical_outputs(
        _semantic(world.counterfactual(episode, policy, 4, 41)),
        _semantic(world.reference_counterfactual(episode, policy, 4, 41)),
        NumericTolerance(absolute=5e-8, relative=5e-8),
    )
    assert comparison.passed, comparison.to_wire()


def test_public_posterior_remains_non_degenerate_after_prior_unification() -> None:
    world = W03World()
    falling, rising = world.collision_fixture(seed=93205)
    policy = world.policy_set(1)[0]

    falling_result = world.counterfactual(falling, policy, 1, 43)
    rising_result = world.counterfactual(rising, policy, 1, 43)
    falling_posterior = falling_result.latent_distribution["diagnostic_posterior"]
    rising_posterior = rising_result.latent_distribution["diagnostic_posterior"]

    assert float(falling_posterior["C0"]) > 0.999
    assert float(rising_posterior["C1"]) > 0.999
    assert canonical_json_bytes(falling_posterior) != canonical_json_bytes(
        rising_posterior
    )

