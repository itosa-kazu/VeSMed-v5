from __future__ import annotations

import json

import pytest

from prototype.unified_map.canonical import digest_json
from prototype.unified_map.candidate_protocol import DiagnoseResponse, RolloutResponse
from prototype.unified_map.schema import (
    CandidateVisibleEvent,
    DiagnosisQuery,
    EventKind,
    RolloutQuery,
    VisibleDelta,
    event_sort_key,
)
from prototype.unified_map.true_state_probe import (
    W01TrueStateUpperBoundProbe,
    run_w01_vertical_slice,
)
from prototype.unified_map.worlds.base import WorldSplit
from prototype.unified_map.worlds.w01 import W01World


def _utility_digest(world: W01World, horizon: int) -> str:
    return digest_json(
        {
            "protocol": "ucm-test-utility/1",
            "world_slot": "W01",
            "catalog_digest": world.catalog.digest,
            "horizon": horizon,
            "utility": "discounted-quadratic-cost",
        }
    )


def _next_visible_delta(episode: object) -> VisibleDelta:
    row = episode.factual_future[0]
    observations = row["observations"]
    events: list[CandidateVisibleEvent] = []
    if row["performed_action"] != "NoNewAction":
        events.append(
            CandidateVisibleEvent(
                kind=EventKind.PERFORMED_TREATMENT,
                occurred_at=1,
                collected_at=None,
                available_at=1,
                event_uid="w01-upper-bound-action-0001",
                payload={"action_id": row["performed_action"], "parameters": {}},
            )
        )
    for slot, channel in enumerate(("obs_0", "obs_1", "obs_2")):
        events.append(
            CandidateVisibleEvent(
                kind=EventKind.OBSERVATION_AVAILABLE,
                occurred_at=1,
                collected_at=1,
                available_at=1,
                event_uid=f"w01-upper-bound-observation-{slot:04d}",
                payload={"channel_id": channel, "value": observations[channel]},
            )
        )
    return VisibleDelta(1, tuple(sorted(events, key=event_sort_key)))


def _decoded_state(state: object) -> dict:
    return json.loads(state.candidate_input.payload.payload.decode("utf-8"))


def test_w01_true_state_probe_uses_one_hash_for_diagnosis_and_all_rollouts() -> None:
    world = W01World()
    probe = W01TrueStateUpperBoundProbe(world)
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 92001, 7)
    state = probe.initialize_private(episode)

    diagnosis = probe.diagnose(
        state,
        DiagnosisQuery(world.catalog.diagnostic_labels),
        query_seed=1,
    )
    assert isinstance(diagnosis.response, DiagnoseResponse)
    assert diagnosis.response.result.probabilities == episode.diagnostic_target
    assert diagnosis.consumed_state_hash == state.record.state_hash
    assert diagnosis.to_wire()["eligibility"] == "upper_bound_only"

    consumed = {diagnosis.consumed_state_hash}
    for horizon in world.catalog.horizons:
        for policy in world.policy_set(horizon):
            query = RolloutQuery(
                horizon,
                policy,
                ("obs_0", "obs_1", "obs_2"),
                _utility_digest(world, horizon),
            )
            execution = probe.rollout(state, query, query_seed=2)
            assert isinstance(execution.response, RolloutResponse)
            consumed.add(execution.consumed_state_hash)

            oracle = world.counterfactual(episode, policy, horizon, 2)
            steps = oracle.observation_distribution["steps"]
            predictions = execution.response.result.observable_predictions
            assert predictions["obs_0"]["values"] == pytest.approx(
                [step["mean"][0] for step in steps], abs=1e-12
            )
            assert predictions["obs_1"]["values"] == pytest.approx(
                [step["mean"][1] for step in steps], abs=1e-12
            )
            class_index = episode.invariant_parameters["class_index"]
            assert predictions["obs_2"]["values"] == [float(class_index)] * horizon
            assert execution.response.result.utility_prediction["value"] == pytest.approx(
                oracle.expected_utility, abs=1e-12
            )

    assert consumed == {state.record.state_hash}


def test_w01_true_state_probe_recursively_updates_to_a_new_shared_state() -> None:
    world = W01World()
    probe = W01TrueStateUpperBoundProbe(world)
    episode = world.generate_episode(WorldSplit.TRAIN, 92003, 11)
    initial = probe.initialize_private(episode)
    delta = _next_visible_delta(episode)
    updated = probe.update(initial, delta, inference_seed=3)

    assert updated.record.parent_state_hash == initial.record.state_hash
    assert updated.record.delta_digest == digest_json(delta.to_wire())
    assert updated.record.state_hash != initial.record.state_hash
    assert updated.record.as_of_available_at == 1
    assert _decoded_state(initial)["as_of_available_at"] == 0
    assert _decoded_state(updated)["x"] == pytest.approx(
        [
            episode.factual_future[0]["observations"]["obs_0"],
            episode.factual_future[0]["observations"]["obs_1"],
        ]
    )

    diagnosis = probe.diagnose(
        updated,
        DiagnosisQuery(world.catalog.diagnostic_labels),
        query_seed=4,
    )
    rollout = probe.rollout(
        updated,
        RolloutQuery(
            4,
            world.policy_set(4)[0],
            ("obs_0", "obs_1"),
            _utility_digest(world, 4),
        ),
        query_seed=5,
    )
    assert diagnosis.consumed_state_hash == updated.record.state_hash
    assert rollout.consumed_state_hash == updated.record.state_hash


def test_w01_true_state_probe_separates_behavior_and_quotients_alpha_renames() -> None:
    world = W01World()
    probe = W01TrueStateUpperBoundProbe(world)

    distinguishable = tuple(probe.initialize_private(item) for item in world.collision_fixture())
    equivalent = tuple(probe.initialize_private(item) for item in world.false_split_fixture())

    assert distinguishable[0].record.state_hash != distinguishable[1].record.state_hash
    assert equivalent[0].record.state_hash == equivalent[1].record.state_hash

    policies = world.policy_set(4)
    best: list[int] = []
    for state in distinguishable:
        utilities = []
        for policy in policies:
            result = probe.rollout(
                state,
                RolloutQuery(
                    4,
                    policy,
                    ("obs_0", "obs_1"),
                    _utility_digest(world, 4),
                ),
                query_seed=6,
            )
            utilities.append(result.response.result.utility_prediction["value"])
        best.append(max(range(len(utilities)), key=utilities.__getitem__))
    assert best[0] != best[1]


def test_w01_true_state_probe_is_explicitly_privileged_and_not_freeze_grade() -> None:
    probe = W01TrueStateUpperBoundProbe()
    wire = probe.manifest.to_wire()
    assert wire["baseline_id"] == "B01"
    assert wire["privileged"] is True
    assert wire["eligibility"] == "upper_bound_only"
    assert wire["freeze_grade"] is False


def test_w01_vertical_slice_is_deterministic_and_closes_the_hash_chain() -> None:
    first = run_w01_vertical_slice(generator_seed=92011, episode_index=13)
    second = run_w01_vertical_slice(generator_seed=92011, episode_index=13)
    assert first == second
    assert first["benchmark_status"] == "PRE-FREEZE"
    assert first["experiment_status"] == "NOT_COUNT_ELIGIBLE"
    assert first["assertions"] == {
        "initial_heads_consumed_one_hash": True,
        "update_changed_hash": True,
        "update_parent_link_closed": True,
        "updated_heads_consumed_new_hash": True,
    }
    initial_hash = first["initial_state"]["state_hash"]
    assert first["diagnosis"]["consumed_state_hash"] == initial_hash
    assert {
        row["consumed_state_hash"] for row in first["rollouts"].values()
    } == {initial_hash}
    update = first["update"]
    assert update["parent_state_hash"] == initial_hash
    assert update["new_state_hash"] != initial_hash
