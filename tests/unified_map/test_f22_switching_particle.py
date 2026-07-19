from __future__ import annotations

import inspect
import json

import numpy as np
import pytest

from prototype.unified_map.benchmark_v1_contract import (
    SharedPatientState,
    build_public_training_record,
)
from prototype.unified_map.candidate_families import LinearSharedCandidate
from prototype.unified_map.f22_switching_particle import (
    F22_FACTORIES,
    SwitchingParticleBeliefCandidate,
    make_f22_candidate,
)
from prototype.unified_map.canonical import ProtocolViolation
from prototype.unified_map.schema import (
    ActionPlan,
    PlanKind,
    PlannedAction,
    VisibleDelta,
    VisibleHistory,
)
from prototype.unified_map.world_registry import WORLD_REGISTRY
from prototype.unified_map.worlds.base import WorldSplit


def _fitted_candidate(count: int = 18):
    world = WORLD_REGISTRY["W01"].panels[0].instantiate()
    records = tuple(
        build_public_training_record(
            world,
            world.generate_episode(WorldSplit.TRAIN, 177, index),
            oracle_seed=701 + index,
        )
        for index in range(count)
    )
    candidate = make_f22_candidate(prototypes=7)
    candidate.fit((world.catalog,), records, model_seed=17)
    episode = world.generate_episode(WorldSplit.VALIDATION, 991, 0)
    return world, records, episode, candidate


def _first_plans(world):
    horizon = world.catalog.horizons[0]
    policies = world.policy_set(horizon)
    natural = next(plan for plan in policies if plan.kind is PlanKind.NO_NEW_ACTION)
    action = next(plan for plan in policies if plan.kind is PlanKind.ACTION_SEQUENCE)
    return horizon, natural, action


def test_f22_factory_and_heads_use_one_shared_state_without_history_parameter() -> None:
    world, _, episode, candidate = _fitted_candidate()
    assert F22_FACTORIES == {"F22": SwitchingParticleBeliefCandidate}
    assert not isinstance(candidate, LinearSharedCandidate)
    for method_name in ("diagnose", "rollout"):
        parameters = inspect.signature(getattr(candidate, method_name)).parameters
        assert "state" in parameters
        assert "history" not in parameters

    state = candidate.initialize(episode.public_history, inference_seed=23)
    wire = json.loads(state.payload)
    assert type(state) is SharedPatientState
    assert state.compactness_class == "candidate_shared_state"
    assert set(wire) == {
        "protocol",
        "candidate_id",
        "family_id",
        "catalog_digest",
        "posterior",
        "posterior_entropy",
        "novelty_ratio",
        "accumulator",
    }
    assert abs(sum(wire["posterior"]) - 1.0) < 1e-12
    assert len(wire["posterior"]) == 7
    payload_text = state.payload.decode("utf-8")
    for forbidden in (
        "visible_history",
        "task_states",
        "representation",
        "exemplars",
        "case_id",
        "test_id",
        "true_state",
        "future_observations",
    ):
        assert forbidden not in payload_text
    assert all(event.event_uid not in payload_text for event in episode.public_history.events)

    diagnosis = candidate.diagnose(
        state, world.catalog.diagnostic_labels, query_seed=29
    )
    horizon, natural, action = _first_plans(world)
    natural_result = candidate.rollout(state, natural, horizon, query_seed=31)
    action_result = candidate.rollout(state, action, horizon, query_seed=37)
    assert set(diagnosis.probabilities) == set(world.catalog.diagnostic_labels)
    assert len(natural_result.signature) == len(action_result.signature) == 32
    assert natural_result != action_result


def test_f22_queries_are_pure_and_query_order_independent() -> None:
    world, _, episode, candidate = _fitted_candidate()
    state = candidate.initialize(episode.public_history, inference_seed=23)
    original = (state.payload, state.distance_vector, state.state_hash)
    horizon, natural, action = _first_plans(world)

    diagnosis_a = candidate.diagnose(
        state, world.catalog.diagnostic_labels, query_seed=1
    )
    action_a = candidate.rollout(state, action, horizon, query_seed=2)
    natural_a = candidate.rollout(state, natural, horizon, query_seed=3)
    natural_b = candidate.rollout(state, natural, horizon, query_seed=3003)
    action_b = candidate.rollout(state, action, horizon, query_seed=2002)
    diagnosis_b = candidate.diagnose(
        state, world.catalog.diagnostic_labels, query_seed=1001
    )

    assert diagnosis_a == diagnosis_b
    assert action_a == action_b
    assert natural_a == natural_b
    assert (state.payload, state.distance_vector, state.state_hash) == original


def test_f22_update_is_recursive_and_noop_is_hash_stable() -> None:
    world, _, episode, candidate = _fitted_candidate()
    full = episode.public_history
    assert len(full.events) >= 2
    cut = max(1, len(full.events) // 2)
    early_events = full.events[:cut]
    late_events = full.events[cut:]
    early = VisibleHistory(
        early_events,
        max(event.available_at for event in early_events),
        full.catalog_digest,
    )
    state = candidate.initialize(early, inference_seed=11)
    replay = candidate.update(
        state,
        VisibleDelta(early.as_of_available_at, ()),
        inference_seed=12,
    )
    assert replay is state
    assert replay.state_hash == state.state_hash

    updated = candidate.update(
        state,
        VisibleDelta(full.as_of_available_at, late_events),
        inference_seed=13,
    )
    updated_wire = json.loads(updated.payload)
    assert updated.state_hash != state.state_hash
    assert updated_wire["accumulator"]["as_of"] == full.as_of_available_at
    assert updated_wire["accumulator"]["total_events"] == len(full.events)
    assert abs(sum(updated_wire["posterior"]) - 1.0) < 1e-12
    assert "events" not in updated_wire["accumulator"]


def test_f22_cold_model_and_state_rehydration_are_exact() -> None:
    world, _, episode, candidate = _fitted_candidate()
    state = candidate.initialize(episode.public_history, inference_seed=23)
    reconstructed = SharedPatientState(
        state.schema_version,
        bytes(state.payload),
        tuple(state.distance_vector),
        state.compactness_class,
    )
    cold = make_f22_candidate()
    cold.load_model_artifact((world.catalog,), candidate.model_artifact())
    horizon, natural, action = _first_plans(world)

    assert cold.diagnose(
        reconstructed, world.catalog.diagnostic_labels, query_seed=400
    ) == candidate.diagnose(state, world.catalog.diagnostic_labels, query_seed=4)
    assert cold.rollout(
        reconstructed, natural, horizon, query_seed=500
    ) == candidate.rollout(state, natural, horizon, query_seed=5)
    assert cold.rollout(
        reconstructed, action, horizon, query_seed=600
    ) == candidate.rollout(state, action, horizon, query_seed=6)


def test_f22_is_structurally_a_switching_prototype_posterior_not_existing_family_tuning() -> None:
    world, _, episode, candidate = _fitted_candidate()
    state = candidate.initialize(episode.public_history, inference_seed=23)
    _, model, posterior, _ = candidate._decoded(state)
    horizon, natural, action = _first_plans(world)
    natural_posterior, natural_fallback = candidate._counterfactual_posterior(
        posterior, natural, horizon, model
    )
    action_posterior, action_fallback = candidate._counterfactual_posterior(
        posterior, action, horizon, model
    )

    summary = candidate.model_summary()
    assert summary["architecture"] == "action_conditioned_switching_particle_filter"
    assert summary["transition_operator_count"] >= 2
    assert model.prototypes.shape[0] == len(posterior)
    assert model.prototypes.shape[1] > len(posterior)
    assert set(model.transitions) >= {"natural"}
    assert any(key.startswith("action:") for key in model.transitions)
    assert all(
        matrix.shape == (len(posterior), len(posterior))
        and np.allclose(matrix.sum(axis=1), 1.0)
        for matrix in model.transitions.values()
    )
    assert not natural_fallback
    assert not action_fallback
    assert not np.allclose(natural_posterior, action_posterior)
    # The single patient object is a posterior plus uncertainty/lag coordinates,
    # rather than Gaussian moments, exemplar kernels, or an ensemble concatenation.
    assert len(state.distance_vector) == len(posterior) + 4


def test_f22_catalog_legal_zero_evidence_control_uses_natural_abstaining_fallback() -> None:
    world, _, episode, candidate = _fitted_candidate()
    state = candidate.initialize(episode.public_history, inference_seed=23)
    _, model, posterior, _ = candidate._decoded(state)
    horizon, natural, _ = _first_plans(world)
    zero_evidence = {
        key for key, count in model.operator_evidence_counts.items() if count == 0
    }
    assert zero_evidence
    fallback_policy = next(
        plan
        for plan in world.policy_set(horizon)
        if plan.kind is PlanKind.ACTION_SEQUENCE
        and any(
            f"action:{action.action_id}" in zero_evidence
            or f"check:{action.action_id}" in zero_evidence
            for action in plan.actions
        )
    )

    switched, used_fallback = candidate._counterfactual_posterior(
        posterior, fallback_policy, horizon, model
    )
    natural_result = candidate.rollout(state, natural, horizon, query_seed=40)
    fallback_result = candidate.rollout(
        state, fallback_policy, horizon, query_seed=41
    )
    assert used_fallback
    assert np.all(np.isfinite(switched))
    assert abs(float(switched.sum()) - 1.0) < 1e-12
    assert fallback_result.abstained
    assert fallback_result.signature == natural_result.signature
    assert fallback_result.expected_utility == natural_result.expected_utility

    # Every frozen catalog-legal public policy is total; genuinely undeclared
    # identifiers remain fail-closed instead of receiving the fallback.
    for plan in world.policy_set(horizon):
        candidate.rollout(state, plan, horizon, query_seed=42)
    undeclared = ActionPlan(
        PlanKind.ACTION_SEQUENCE,
        (PlannedAction(0, "GENERIC_UNDECLARED_CONTROL"),),
    )
    with pytest.raises(ProtocolViolation, match="absent from its public catalog"):
        candidate.rollout(state, undeclared, horizon, query_seed=43)

    summary = candidate.model_summary()
    assert summary["zero_evidence_operator_count"] >= 1
