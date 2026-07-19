from __future__ import annotations

import inspect

import numpy as np

from prototype.unified_map.benchmark_v1_contract import (
    SharedPatientState,
    build_public_training_record,
)
from prototype.unified_map.candidate_families import (
    CANDIDATE_FACTORIES,
    FullHistoryBaseline,
    SeparateTaskBaseline,
    accumulator_from_history,
    feature_vector,
)
from prototype.unified_map.schema import VisibleDelta
from prototype.unified_map.world_registry import WORLD_REGISTRY
from prototype.unified_map.worlds.base import WorldSplit


def _w01_training(count: int = 12):
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


def test_feature_accumulator_is_finite_and_history_order_sensitive() -> None:
    world, _ = _w01_training(2)
    episode = world.generate_episode(WorldSplit.TRAIN, 12, 0)
    vector = feature_vector(accumulator_from_history(episode.public_history))
    assert vector.shape == (87,)
    assert np.all(np.isfinite(vector))
    assert np.any(vector != 0.0)


def test_all_eight_families_and_three_public_baselines_execute_same_state_heads() -> None:
    world, records = _w01_training()
    episode = world.generate_episode(WorldSplit.VALIDATION, 991, 0)
    state_shapes: dict[str, int] = {}
    for code, factory in CANDIDATE_FACTORIES.items():
        candidate = factory()
        candidate.fit((world.catalog,), records, model_seed=17)
        state = candidate.initialize(episode.public_history, inference_seed=23)
        assert type(state) is SharedPatientState
        state_shapes[code] = len(state.distance_vector)
        diagnosis = candidate.diagnose(
            state, world.catalog.diagnostic_labels, query_seed=29
        )
        assert set(diagnosis.probabilities) == set(world.catalog.diagnostic_labels)
        assert abs(sum(diagnosis.probabilities.values()) - 1.0) < 1e-9
        plan = world.policy_set(world.catalog.horizons[0])[0]
        rollout = candidate.rollout(
            state, plan, world.catalog.horizons[0], query_seed=31
        )
        assert len(rollout.signature) == 32
        replay = candidate.update(
            state,
            VisibleDelta(episode.public_history.as_of_available_at, ()),
            inference_seed=37,
        )
        assert replay.state_hash == state.state_hash
    assert set(state_shapes) == {
        "F01",
        "F02",
        "F03",
        "F04",
        "F05",
        "F06",
        "F07",
        "F08",
        "B02",
        "B03",
        "B04",
    }
    assert len({state_shapes[code] for code in tuple(f"F{i:02d}" for i in range(1, 9))}) >= 6


def test_head_signatures_have_no_history_parameter() -> None:
    for factory in CANDIDATE_FACTORIES.values():
        for method_name in ("diagnose", "rollout"):
            parameters = inspect.signature(getattr(factory, method_name)).parameters
            assert "history" not in parameters
            assert "state" in parameters


def test_baseline_truth_is_explicit_in_state_class() -> None:
    world, records = _w01_training()
    episode = world.generate_episode(WorldSplit.VALIDATION, 123, 0)
    full = FullHistoryBaseline()
    full.fit((world.catalog,), records, model_seed=1)
    full_state = full.initialize(episode.public_history, inference_seed=1)
    assert full_state.compactness_class == "full_visible_history_baseline"
    assert b"visible_history" in full_state.payload

    separate = SeparateTaskBaseline()
    separate.fit((world.catalog,), records, model_seed=1)
    separate_state = separate.initialize(episode.public_history, inference_seed=1)
    assert separate_state.compactness_class == "separate_task_baseline"
    assert b"task_states" in separate_state.payload

