from __future__ import annotations

from prototype.unified_map.canonical import digest_json
from prototype.unified_map.schema import DiagnosisQuery, PlanKind, RolloutQuery
from prototype.unified_map.true_state_probe_w18 import (
    W18PublicOODProbe,
    run_w18_ood_slice,
)
from prototype.unified_map.worlds.w18 import W18World


def _policy(world: W18World, action: str | None):
    if action is None:
        return next(
            policy
            for policy in world.policy_set(4)
            if policy.kind is PlanKind.NO_NEW_ACTION
        )
    return next(
        policy
        for policy in world.policy_set(4)
        if len(policy.actions) == 1 and policy.actions[0].action_id == action
    )


def test_w18_public_state_rollout_matches_episode_oracle() -> None:
    world = W18World()
    episode = world.attributable_ood_fixture(seed=1801)
    policy = _policy(world, "A1")

    episode_result = world.counterfactual(episode, policy, 4, 1)
    state_result = world.public_state_counterfactual(0.8, 0.0, policy, 4)
    assert episode_result == state_result


def test_w18_irreducible_private_aliases_cannot_split_public_state() -> None:
    world = W18World()
    probe = W18PublicOODProbe(world)
    unseen, known = world.irreducible_alias_pair(seed=1803)
    assert world.attribution_tag(unseen) == "OOD_IRREDUCIBLE"
    assert world.attribution_tag(known) == "KNOWN"

    unseen_state = probe.initialize_public_episode(unseen)
    known_state = probe.initialize_public_episode(known)
    assert unseen_state.record.state_hash == known_state.record.state_hash


def test_w18_known_extreme_remains_known_instead_of_blanket_rejection() -> None:
    world = W18World()
    probe = W18PublicOODProbe(world)
    state = probe.initialize_public_episode(world.known_extreme_fixture(seed=1805))
    diagnosis = probe.diagnose(
        state, DiagnosisQuery(world.catalog.diagnostic_labels), query_seed=1
    )
    rollout = probe.rollout(
        state,
        RolloutQuery(
            4,
            _policy(world, None),
            ("obs_0", "obs_1"),
            digest_json(["W18", "known-extreme", 4]),
        ),
        query_seed=2,
    )

    assert diagnosis.response.result.probabilities == {
        "C0": 1.0,
        "C1": 0.0,
        "unknown": 0.0,
    }
    assert diagnosis.response.result.metadata["abstain"] is False
    assert rollout.response.result.metadata["abstain"] is False


def test_w18_ood_slice_is_deterministic_and_closes_all_claims() -> None:
    first = run_w18_ood_slice()
    second = run_w18_ood_slice()
    assert first == second
    assert all(first["assertions"].values())
    assert first["experiment_status"] == "NOT_COUNT_ELIGIBLE"
