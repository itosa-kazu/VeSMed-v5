from __future__ import annotations

from dataclasses import replace

import pytest

from prototype.unified_map.canonical import canonical_json_bytes
from prototype.unified_map.oracle_certification import (
    NumericTolerance,
    OracleProbe,
    PrivateSwapProbe,
    certify_oracle_pair,
    compare_canonical_outputs,
    oracle_output_wire,
)
from prototype.unified_map.worlds.base import MicroWorld, PrivateEpisode, WorldSplit
from prototype.unified_map.worlds.w01 import W01World
from prototype.unified_map.worlds.w02 import W02World
from prototype.unified_map.worlds.w03 import W03World
from prototype.unified_map.worlds.w04 import W04World
from prototype.unified_map.worlds.w05 import W05World


WORLD_TYPES = (W01World, W02World, W03World, W04World, W05World)


def _private_swap(episode: PrivateEpisode) -> PrivateEpisode:
    """Change every realized/ledger field while preserving the public query."""

    return replace(
        episode,
        case_key="judge-private-swap",
        environment_key="judge-private-swap-environment",
        generator_seed=episode.generator_seed + 1234567,
        hidden_state_at_cut={"malicious": [1_000_000.0, -1_000_000.0]},
        invariant_parameters={"malicious": "opposite-realization"},
        diagnostic_target={"C0": 0.123, "C1": 0.877},
        factual_future=[{"malicious_future": 1_000_000.0}],
        action_propensities=[{"malicious_propensity": 1.0}],
        factual_utility=-1_000_000.0,
        oracle_anchor={"malicious_anchor": True},
    )


def _semantic(value: object) -> dict[str, object]:
    return oracle_output_wire(value, include_numerical_diagnostics=False)


@pytest.mark.parametrize("world_type", WORLD_TYPES)
def test_reference_oracle_is_source_distinct_and_private_swap_invariant(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 91001, 7)
    swapped = _private_swap(episode)
    policy = world.policy_set(1)[1]
    report = certify_oracle_pair(
        benchmark_id=f"ucm-benchmark-v1-{world_type.__name__}",
        production=world.counterfactual,
        reference=world.reference_counterfactual,
        probes=(OracleProbe("ordinary", episode, policy, 1, 17),),
        private_swap_probes=(
            PrivateSwapProbe("private-swap", episode, swapped, policy, 1, 17),
        ),
        tolerance=NumericTolerance(absolute=2e-9, relative=2e-9),
    )
    assert report.source_separation.passed, report.source_separation.to_wire()
    assert report.passed, report.to_wire()
    assert report.private_swap_probes[0].production_exact_invariant
    assert report.private_swap_probes[0].reference_exact_invariant


@pytest.mark.parametrize("world_type", WORLD_TYPES)
def test_reference_oracle_matches_every_finite_horizon_one_policy(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 91003, 8)
    for policy in world.policy_set(1):
        production = world.counterfactual(episode, policy, 1, 19)
        reference = world.reference_counterfactual(episode, policy, 1, 19)
        comparison = compare_canonical_outputs(
            _semantic(production),
            _semantic(reference),
            NumericTolerance(absolute=2e-9, relative=2e-9),
        )
        assert comparison.passed, comparison.to_wire()


@pytest.mark.parametrize("world_type", (W02World, W03World, W04World))
def test_reference_oracle_matches_adaptive_check_then_treat_policy(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 91005, 9)
    policy = world.policy_set(4)[-1]
    production = world.counterfactual(episode, policy, 4, 23)
    reference = world.reference_counterfactual(episode, policy, 4, 23)
    comparison = compare_canonical_outputs(
        _semantic(production),
        _semantic(reference),
        NumericTolerance(absolute=5e-8, relative=5e-8),
    )
    assert comparison.passed, comparison.to_wire()


@pytest.mark.parametrize("world_type", WORLD_TYPES)
def test_same_public_private_swap_is_exact_for_all_horizon_four_queries(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 91007, 6)
    swapped = _private_swap(episode)
    assert episode.public_history.digest == swapped.public_history.digest
    for policy in world.policy_set(4):
        for oracle in (world.counterfactual, world.reference_counterfactual):
            first = oracle(episode, policy, 4, 29)
            second = oracle(swapped, policy, 4, 29)
            assert canonical_json_bytes(
                oracle_output_wire(first, include_numerical_diagnostics=True)
            ) == canonical_json_bytes(
                oracle_output_wire(second, include_numerical_diagnostics=True)
            )


@pytest.mark.parametrize(
    ("world_type", "split", "episode_index", "expected"),
    (
        (W01World, WorldSplit.TRAIN, 0, ("iid_support",)),
        (W01World, WorldSplit.SEALED_TEST, 5, ("iid_support", "boundary_tail")),
        (W02World, WorldSplit.SEALED_TEST, 1, ("iid_support", "boundary_tail")),
        (W02World, WorldSplit.SEALED_TEST, 2, ("iid_support", "boundary_tail")),
        (W02World, WorldSplit.SEALED_TEST, 3, ("iid_support",)),
        (W03World, WorldSplit.SEALED_TEST, 0, ("iid_support", "behavior_pair")),
        (W03World, WorldSplit.SEALED_TEST, 4, ("iid_support", "boundary_tail")),
        (W03World, WorldSplit.SEALED_TEST, 6, ("iid_support",)),
        (W04World, WorldSplit.SEALED_TEST, 1, ("iid_support", "policy_coverage_holdout")),
        (W04World, WorldSplit.SEALED_TEST, 2, ("iid_support", "boundary_tail")),
        (W04World, WorldSplit.SEALED_TEST, 3, ("iid_support",)),
        (W05World, WorldSplit.SEALED_TEST, 0, ("iid_support", "boundary_tail")),
        (W05World, WorldSplit.SEALED_TEST, 2, ("iid_support", "policy_coverage_holdout")),
        (W05World, WorldSplit.SEALED_TEST, 4, ("iid_support",)),
    ),
)
def test_generated_episode_has_exact_machine_readable_strata(
    world_type: type[MicroWorld],
    split: WorldSplit,
    episode_index: int,
    expected: tuple[str, ...],
) -> None:
    world = world_type()
    episode = world.generate_episode(split, 91009, episode_index)
    assert world.strata_for_episode(episode) == expected


@pytest.mark.parametrize("world_type", WORLD_TYPES)
def test_equivalent_and_distinguishable_probes_have_oracle_attribution(
    world_type: type[MicroWorld],
) -> None:
    world = world_type()
    distinguishable = world.collision_fixture()
    equivalent = world.false_split_fixture()
    policy_set = world.policy_set(4)

    distinct_gap = max(
        abs(
            world.reference_counterfactual(distinguishable[0], policy, 4, 31).expected_utility
            - world.reference_counterfactual(distinguishable[1], policy, 4, 31).expected_utility
        )
        for policy in policy_set
    )
    assert distinct_gap > 0.20

    for policy in policy_set:
        left = world.reference_counterfactual(equivalent[0], policy, 4, 31)
        right = world.reference_counterfactual(equivalent[1], policy, 4, 31)
        comparison = compare_canonical_outputs(
            _semantic(left),
            _semantic(right),
            NumericTolerance(absolute=2e-10, relative=2e-10),
        )
        assert comparison.passed, comparison.to_wire()
