from __future__ import annotations

from dataclasses import replace

import pytest

from prototype.unified_map.canonical import canonical_json_bytes
from prototype.unified_map.oracle_certification import (
    NumericTolerance,
    OracleProbe,
    PrivateSwapProbe,
    certify_oracle_pair,
)
from prototype.unified_map.schema import PlanKind
from prototype.unified_map.worlds.base import WorldSplit
from prototype.unified_map.worlds.w18 import W18World
from prototype.unified_map.worlds.w19 import W19World, W19TailTruth


def _oracle_bytes(value: object) -> bytes:
    return canonical_json_bytes(
        {
            "observation": value.observation_distribution,
            "latent": value.latent_distribution,
            "outcome": value.outcome_distribution,
            "utility": value.expected_utility,
            "numerics": value.numerical_diagnostics,
        }
    )


def _single_action(world: object, horizon: int, action_id: str):
    return next(
        policy
        for policy in world.policy_set(horizon)
        if policy.kind is PlanKind.ACTION_SEQUENCE
        and len(policy.actions) == 1
        and policy.actions[0].action_id == action_id
    )


def test_w18_overlap_posterior_keeps_unknown_mass_and_is_private_swap_invariant() -> None:
    world = W18World()
    unseen, known = world.irreducible_alias_pair()
    unseen_posterior = world.public_posterior(unseen)
    known_posterior = world.public_posterior(known)
    assert unseen.public_history.digest == known.public_history.digest
    assert unseen_posterior == pytest.approx(known_posterior, abs=1e-12)
    assert 0.0 < unseen_posterior["unknown"] < 1.0
    assert sum(unseen_posterior.values()) == pytest.approx(1.0)
    assert world.attribution_tag(unseen) == "OOD_IRREDUCIBLE"
    assert world.attribution_tag(known) == "KNOWN"


def test_w18_dual_known_support_uses_likelihood_weights_not_hard_half() -> None:
    world = W18World()
    episode = world._fixture(
        seed=1811,
        side=0,
        mechanism="C2",
        obs_0=0.020,
        obs_1=0.010,
    )
    assert world.known_support(episode) == (True, True)
    posterior = world.public_posterior(episode)
    assert posterior["C0"] != pytest.approx(posterior["C1"])
    assert posterior["unknown"] > 0.0


def test_w18_production_and_source_distinct_reference_posterior_agree() -> None:
    world = W18World()
    for episode in (
        world.attributable_ood_fixture(),
        world.irreducible_alias_pair()[0],
        world.known_extreme_fixture(),
    ):
        production = world.public_posterior(episode)
        reference = world.reference_public_posterior(episode)
        assert production == pytest.approx(reference, abs=2e-4)
    assert world.posterior_solver_provenance() == {
        "production": "analytic-interval-mixture-v1",
        "reference": "independent-midpoint-quadrature-v1",
    }


def test_w18_scoring_oracle_never_uses_private_attribution_or_future() -> None:
    world = W18World()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 987, 1)
    swapped = replace(
        episode,
        hidden_state_at_cut={"x": -999.0},
        invariant_parameters={"mechanism": "C0", "subtype": "poison"},
        diagnostic_target={"C0": 1.0, "C1": 0.0, "unknown": 0.0},
        factual_future=[{"poison": 1}],
        oracle_anchor={"ood_attribution": "POISON"},
    )
    assert world.public_posterior(episode) == world.public_posterior(swapped)
    for policy in world.policy_set(4):
        assert _oracle_bytes(world.counterfactual(episode, policy, 4, 7)) == _oracle_bytes(
            world.counterfactual(swapped, policy, 4, 999)
        )


def test_w18_sealed_strata_have_exact_publicly_auditable_population_quota() -> None:
    world = W18World()
    rows = [world.generate_episode(WorldSplit.SEALED_TEST, 44, i) for i in range(100)]
    tags = [world.attribution_tag(row) for row in rows]
    assert tags.count("OOD_ATTRIBUTABLE") == 10
    assert tags.count("OOD_IRREDUCIBLE") == 10
    assert tags.count("KNOWN_EXTREME") == 20
    covered = set().union(*(world.strata_for_episode(row) for row in rows))
    covered.update(world.strata_for_episode(world.irreducible_alias_pair()[0]))
    assert covered == {
        "iid_support",
        "boundary_tail",
        "mechanism_ood",
        "behavior_pair",
    }


def test_w19_public_posterior_includes_uniform_x_prior_and_reference_agrees() -> None:
    world = W19World()
    episode = world._probe_episode(
        seed=1911,
        probe_index=0,
        tail=False,
        marker=None,
        observed_x=0.205,
    )
    production = world.public_posterior(episode)
    reference = world.reference_public_posterior(episode)
    assert production["x_mean"] > 0.205
    assert production["x_variance"] < (1.1**2) / 12.0
    assert production == pytest.approx(reference, abs=3e-5)
    assert world.posterior_solver_provenance() == {
        "production": "analytic-truncated-normal-v1",
        "reference": "independent-uniform-grid-v1",
    }


@pytest.mark.parametrize("split", list(WorldSplit))
def test_w19_tail_marker_and_action_quota_are_exact(split: WorldSplit) -> None:
    world = W19World()
    audit = world.audit_population_quota(split, 331)
    assert audit == world.population_quota_manifest(split)
    assert audit["tail"] == world.population_size(split) // 64
    assert all(count > 0 for count in audit["actions"].values())
    assert audit["tail_marker"]["positive"] > 0
    assert audit["tail_marker"]["negative"] > 0


def test_w19_population_has_one_denominator_and_probe_has_none() -> None:
    world = W19World()
    population = world.generate_episode(WorldSplit.SEALED_TEST, 19, 0)
    common, tail = world.tail_probe_pair(seed=19, probe_index=17)
    assert world.population_membership(population)
    assert not world.population_membership(common)
    assert not world.population_membership(tail)
    for episode in (population, common, tail):
        assert "population_weight" not in episode.invariant_parameters
    tail_population = next(
        world.generate_episode(WorldSplit.SEALED_TEST, 19, index)
        for index in range(64)
        if world.is_population_tail(WorldSplit.SEALED_TEST, 19, index)
    )
    covered = set(world.strata_for_episode(tail_population))
    covered.update(world.strata_for_episode(tail))
    assert covered == {
        "iid_support",
        "boundary_tail",
        "policy_coverage_holdout",
        "behavior_pair",
    }


def test_w19_tail_truth_is_typed_and_exposes_catastrophic_hard_gate() -> None:
    world = W19World()
    _, tail = world.tail_probe_pair()
    a1 = _single_action(world, 4, "A1")
    truth = world.tail_truth(tail, a1, 4)
    assert isinstance(truth, W19TailTruth)
    assert truth.tail_only_regret > 10.0
    assert truth.tail_catastrophic_action_probability == pytest.approx(1.0)
    assert truth.posterior_catastrophic_action_probability > 0.40
    outcome = world.counterfactual(tail, a1, 4, 0).outcome_distribution
    assert outcome["tail_only_regret"] == pytest.approx(truth.tail_only_regret)
    assert outcome["catastrophic_hard_gate_exposed"]
    assert "reporting_contract" not in outcome


def test_w19_scoring_posterior_and_oracle_ignore_private_tail_swap() -> None:
    world = W19World()
    common, tail = world.unidentified_tail_alias_pair()
    assert common.public_history.digest == tail.public_history.digest
    assert world.public_posterior(common) == world.public_posterior(tail)
    for policy in world.policy_set(4):
        assert _oracle_bytes(world.counterfactual(common, policy, 4, 0)) == _oracle_bytes(
            world.counterfactual(tail, policy, 4, 918)
        )


@pytest.mark.parametrize("world_type", (W18World, W19World))
def test_w18_w19_counterfactual_reference_is_source_distinct_and_certified(
    world_type: type,
) -> None:
    world = world_type()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 99119, 7)
    swapped = replace(
        episode,
        case_key="private-swap",
        hidden_state_at_cut={"poison": 1},
        invariant_parameters={"poison": 2},
        diagnostic_target={"poison": 1.0},
        factual_future=[{"poison": 3}],
        action_propensities=[{"poison": 4}],
        factual_utility=-999.0,
        oracle_anchor={"poison": 5},
    )
    policy = world.policy_set(4)[1]
    report = certify_oracle_pair(
        benchmark_id=f"ucm-v1-{world_type.__name__}",
        production=world.counterfactual,
        reference=world.reference_counterfactual,
        probes=(OracleProbe("ordinary", episode, policy, 4, 17),),
        private_swap_probes=(
            PrivateSwapProbe("swap", episode, swapped, policy, 4, 17),
        ),
        tolerance=NumericTolerance(absolute=3e-8, relative=3e-8),
    )
    assert report.source_separation.passed, report.source_separation.to_wire()
    assert report.passed, report.to_wire()
