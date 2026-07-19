from __future__ import annotations

import json

import pytest

from prototype.unified_map import compliance
from prototype.unified_map.compliance import (
    ActionAsConditioningControl,
    AvailabilityOffByOneControl,
    NoOpMeansStopControl,
    PlanMeansPerformedControl,
    QuerySmugglerControl,
    TestIdSwitchControl,
    TripleLatentBlobControl,
    WorldNameSwitchControl,
)
from prototype.unified_map.state import CandidateStateInput


def state_input(payload):
    return CandidateStateInput(payload)


def diagnosis_vector(result, labels):
    return [float(result.probabilities[label]) for label in labels]


def rollout_point(result, observable):
    return float(result.observable_predictions[observable]["values"][0])


def test_c11_equal_cut_event_is_actually_ignored_by_mutant() -> None:
    fixture = compliance._directed_fixture("availability_boundary", 101)
    control = AvailabilityOffByOneControl()
    states = [
        control.initialize(history, inference_seed=101)
        for history in fixture["histories"]
    ]
    assert states[0] == states[1]
    assert fixture["expected"]["equal_cut_visible"] is True


def test_c13_and_c14_name_and_canary_switches_change_actual_answers() -> None:
    c13 = compliance._directed_fixture("opaque_alpha_renaming", 103)
    world_control = WorldNameSwitchControl()
    state = state_input(world_control.initialize(c13["history"], inference_seed=103))
    vectors = [
        diagnosis_vector(
            world_control.diagnose(state, query, query_seed=104),
            query.label_catalog,
        )
        for query in c13["queries"]
    ]
    assert vectors == [[0.9, 0.1], [0.1, 0.9]]

    c14 = compliance._directed_fixture("hidden_test_id_canary", 107)
    test_control = TestIdSwitchControl()
    vectors = []
    for history in c14["histories"]:
        state = state_input(test_control.initialize(history, inference_seed=107))
        vectors.append(
            diagnosis_vector(
                test_control.diagnose(state, c14["query"], query_seed=108),
                c14["query"].label_catalog,
            )
        )
    assert vectors[0] != vectors[1]


def test_c03_covert_future_task_route_changes_state_and_readout() -> None:
    fixture = compliance._directed_fixture("task_blind_state", 109)
    control = QuerySmugglerControl()
    states = []
    vectors = []
    for history in fixture["histories"]:
        payload = control.initialize(history, inference_seed=109)
        states.append(payload)
        vectors.append(
            diagnosis_vector(
                control.diagnose(
                    state_input(payload), fixture["query"], query_seed=110
                ),
                fixture["query"].label_catalog,
            )
        )
    assert states[0] != states[1]
    assert vectors == [[0.9, pytest.approx(0.1)], [0.1, 0.9]]


def test_c17_and_c18_action_semantics_are_observably_conflated() -> None:
    c17 = compliance._directed_fixture("no_op_semantics", 113)
    no_op = NoOpMeansStopControl()
    state = state_input(no_op.initialize(c17["history"], inference_seed=113))
    points = [
        rollout_point(no_op.rollout(state, query, query_seed=115), "future_burden")
        for query in c17["queries"]
    ]
    assert points == [1.0, 0.4, 1.0, 0.8]
    assert points != c17["expected"]["burdens_by_plan"]

    c18 = compliance._directed_fixture("plan_performed_separation", 127)
    plan = PlanMeansPerformedControl()
    points = []
    for history in c18["histories"]:
        state = state_input(plan.initialize(history, inference_seed=127))
        points.append(
            rollout_point(
                plan.rollout(state, c18["query"], query_seed=129),
                "future_burden",
            )
        )
    assert points == [0.5, 0.5]
    assert c18["expected"] == {"ordered_burden": 1.0, "performed_burden": 0.5}


def test_c19_w15a_do_effect_sign_is_reversed_by_conditioning_mutant() -> None:
    fixture = compliance._directed_fixture("condition_do_separation", 131)
    control = ActionAsConditioningControl()
    state = state_input(control.initialize(fixture["history"], inference_seed=131))
    points = [
        rollout_point(control.rollout(state, query, query_seed=133), "obs_0")
        for query in fixture["queries"]
    ]
    assert points[1] - points[0] > 0.0
    assert fixture["expected"]["oracle_effect"] < 0.0


def test_c33_update_leaves_two_task_exclusive_roots_stale() -> None:
    fixture = compliance._directed_fixture("patient_state_root", 137)
    control = TripleLatentBlobControl()
    initial = control.initialize(fixture["history"], inference_seed=137)
    updated = control.update(state_input(initial), fixture["delta"], inference_seed=140)
    roots = json.loads(updated.payload.decode("utf-8"))
    assert roots["diagnosis_root"] == 0.2
    assert roots["natural_root"] == roots["treatment_root"] == 0.8
    state = state_input(updated)
    points = [
        rollout_point(control.rollout(state, query, query_seed=139), "root_readout")
        for query in fixture["rollout_queries"]
    ]
    assert points == [0.8, 0.8]
