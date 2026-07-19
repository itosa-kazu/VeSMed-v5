from __future__ import annotations

import inspect
import json

import numpy as np
import pytest

from prototype.unified_map.baselines_v2 import (
    ExactFullHistoryBaselineV2,
    SeparateTaskBaselineV2,
    exact_history_feature_vector,
)
from prototype.unified_map.benchmark_v1_contract import (
    SharedPatientState,
    build_public_training_record,
)
from prototype.unified_map.benchmark_v1_runner import (
    BASELINE_ONLY_FAMILIES,
    SEPARATE_TASK_FAMILIES,
    _make_benchmark_candidate,
    _source_binding,
)
from prototype.unified_map.candidate_families import make_candidate
from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes, digest_bytes
from prototype.unified_map.schema import VisibleDelta, VisibleHistory
from prototype.unified_map.world_registry import WORLD_REGISTRY
from prototype.unified_map.worlds.base import WorldSplit


def _training(count: int = 12):
    world = WORLD_REGISTRY["W01"].panels[0].instantiate()
    records = tuple(
        build_public_training_record(
            world,
            world.generate_episode(WorldSplit.TRAIN, 177, index),
            oracle_seed=701 + index,
        )
        for index in range(count)
    )
    return world, records


def _prefix_and_delta(history: VisibleHistory) -> tuple[VisibleHistory, VisibleDelta]:
    split = max(1, len(history.events) // 2)
    prefix_events = history.events[:split]
    prefix = VisibleHistory(
        prefix_events,
        max(event.available_at for event in prefix_events),
        history.catalog_digest,
    )
    return prefix, VisibleDelta(history.as_of_available_at, history.events[split:])


def test_b02v2_exact_history_affects_readout_and_is_not_legacy_payload_decoration() -> None:
    world, records = _training()
    baseline = ExactFullHistoryBaselineV2()
    baseline.fit((world.catalog,), records, model_seed=17)
    episode = world.generate_episode(WorldSplit.VALIDATION, 991, 0)
    state = baseline.initialize(episode.public_history, inference_seed=23)

    assert state.compactness_class == "full_visible_history_baseline"
    wire = json.loads(state.payload)
    assert wire["storage_semantics"] == "exact_uncompressed_visible_history"
    assert wire["visible_history"] == episode.public_history.to_wire()
    assert "representation" not in wire

    changed = json.loads(canonical_json_bytes(wire["visible_history"]))
    changed["events"][0]["event_uid"] += "-different"
    assert not np.array_equal(
        exact_history_feature_vector(wire["visible_history"]),
        exact_history_feature_vector(changed),
    )

    # A head recomputes from exact history and rejects a payload-only change
    # instead of trusting the old distance/readout representation.
    wire["visible_history"] = changed
    tampered = SharedPatientState(
        state.schema_version,
        canonical_json_bytes(wire),
        state.distance_vector,
        state.compactness_class,
    )
    with pytest.raises(ProtocolViolation, match="representation mismatch"):
        baseline.diagnose(tampered, world.catalog.diagnostic_labels, query_seed=1)


def test_b02v2_update_equals_full_reinitialize_and_heads_are_pure() -> None:
    world, records = _training()
    baseline = ExactFullHistoryBaselineV2()
    baseline.fit((world.catalog,), records, model_seed=17)
    episode = world.generate_episode(WorldSplit.VALIDATION, 991, 1)
    prefix, delta = _prefix_and_delta(episode.public_history)
    before = baseline.initialize(prefix, inference_seed=1)
    updated = baseline.update(before, delta, inference_seed=2)
    replay = baseline.initialize(episode.public_history, inference_seed=3)
    assert updated.payload == replay.payload
    assert updated.distance_vector == replay.distance_vector
    assert updated.state_hash == replay.state_hash

    empty = baseline.update(
        updated,
        VisibleDelta(episode.public_history.as_of_available_at, ()),
        inference_seed=4,
    )
    assert empty is updated
    diagnosis_first = baseline.diagnose(updated, world.catalog.diagnostic_labels, query_seed=5)
    for plan in world.policy_set(world.catalog.horizons[0]):
        baseline.rollout(updated, plan, world.catalog.horizons[0], query_seed=6)
    diagnosis_last = baseline.diagnose(updated, world.catalog.diagnostic_labels, query_seed=7)
    assert diagnosis_first == diagnosis_last
    assert "history" not in inspect.signature(baseline.diagnose).parameters
    assert "history" not in inspect.signature(baseline.rollout).parameters


def test_b03v2_routes_to_three_standalone_models_and_updates_every_child() -> None:
    world, records = _training()
    baseline = SeparateTaskBaselineV2()
    baseline.fit((world.catalog,), records, model_seed=19)
    standalones = {
        "diagnosis": make_candidate("F10"),
        "natural": make_candidate("F14"),
        "intervention": make_candidate("F18"),
    }
    for candidate in standalones.values():
        candidate.fit((world.catalog,), records, model_seed=19)

    episode = world.generate_episode(WorldSplit.VALIDATION, 812, 0)
    state = baseline.initialize(episode.public_history, inference_seed=2)
    assert state.compactness_class == "separate_task_baseline"
    wire = json.loads(state.payload)
    assert set(wire["task_states"]) == {"diagnosis", "natural", "intervention"}
    child_ids = {
        task: row["payload"]["candidate_id"] for task, row in wire["task_states"].items()
    }
    assert child_ids == {
        "diagnosis": "F10-nonparametric-support-belief-v1",
        "natural": "F14-multiscale-path-koopman-v1",
        "intervention": "F18-causal-operator-ensemble-state-v1",
    }
    standalone_states = {
        task: candidate.initialize(episode.public_history, inference_seed=2)
        for task, candidate in standalones.items()
    }
    assert baseline.diagnose(state, world.catalog.diagnostic_labels, query_seed=3) == standalones[
        "diagnosis"
    ].diagnose(standalone_states["diagnosis"], world.catalog.diagnostic_labels, query_seed=3)
    horizon = world.catalog.horizons[0]
    for plan in world.policy_set(horizon):
        task = "natural" if plan.kind.value in {"no_new_action", "continue_current"} else "intervention"
        assert baseline.rollout(state, plan, horizon, query_seed=4) == standalones[task].rollout(
            standalone_states[task], plan, horizon, query_seed=4
        )

    prefix, delta = _prefix_and_delta(episode.public_history)
    prefix_state = baseline.initialize(prefix, inference_seed=5)
    assert baseline.update(prefix_state, delta, inference_seed=6).state_hash == state.state_hash
    summary = baseline.model_summary()
    assert summary["eligibility"] == "baseline_only_non_ucm"
    assert set(summary["components"]) == {"diagnosis", "natural", "intervention"}


def test_b03v2_fails_closed_on_child_tamper() -> None:
    world, records = _training()
    baseline = SeparateTaskBaselineV2()
    baseline.fit((world.catalog,), records, model_seed=1)
    episode = world.generate_episode(WorldSplit.VALIDATION, 123, 0)
    state = baseline.initialize(episode.public_history, inference_seed=1)
    wire = json.loads(state.payload)
    wire["task_states"]["natural"]["distance_vector"][0] += 1.0
    tampered = SharedPatientState(
        state.schema_version,
        canonical_json_bytes(wire),
        state.distance_vector,
        state.compactness_class,
    )
    with pytest.raises(ProtocolViolation, match="outer/child distance mismatch"):
        baseline.rollout(
            tampered,
            world.policy_set(world.catalog.horizons[0])[0],
            world.catalog.horizons[0],
            query_seed=1,
        )


def test_runner_dispatch_and_source_custody_make_v2_baselines_ineligible() -> None:
    assert type(_make_benchmark_candidate("B02V2", {})) is ExactFullHistoryBaselineV2
    assert type(_make_benchmark_candidate("B03V2", {})) is SeparateTaskBaselineV2
    assert {"B02V2", "B03V2"} <= BASELINE_ONLY_FAMILIES
    assert "B03V2" in SEPARATE_TASK_FAMILIES
    row = next(
        item
        for item in _source_binding()["files"]
        if item["relative_path"] == "prototype/unified_map/baselines_v2.py"
    )
    raw = open("prototype/unified_map/baselines_v2.py", "rb").read()
    assert row["byte_length"] == len(raw)
    assert row["sha256"] == digest_bytes(raw)
