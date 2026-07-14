from __future__ import annotations

import copy

import pytest

from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes
from prototype.unified_map.policy import (
    PHASE_ORDER,
    ActionRuntimeSpec,
    AdaptiveBranch,
    CheckOrder,
    CheckRuntimeSpec,
    CheckThenTreatPolicy,
    CollectedResult,
    ComparisonOperator,
    CONTINUE_CURRENT,
    ControlDirective,
    ControlKind,
    NO_NEW_ACTION,
    OpenLoopPolicy,
    PolicyEngine,
    ResultPredicate,
    STOP_CONTROLLABLE,
    ScheduledCheck,
    ScheduledDecision,
    finite_policy_from_wire,
    merge_visible_events,
)
from prototype.unified_map.schema import CandidateVisibleEvent, EventKind


def _transition(state: dict, request: object) -> dict:
    active = request.effective_control
    state["x"] += 1 if active is not None and active.action_id == "A1" else 0
    return state


def _collect(state: dict, request: object) -> CollectedResult:
    return CollectedResult({"obs_0": state["x"]})


def _engine(*, result_delay: int = 1, duration: int = 3) -> PolicyEngine:
    return PolicyEngine(
        actions=(ActionRuntimeSpec("A1", duration),),
        checks=(CheckRuntimeSpec("Q0", ("obs_0",), 1, result_delay),),
        transition=_transition,
        collect=_collect,
    )


def _do(action_id: str = "A1") -> ControlDirective:
    return ControlDirective(ControlKind.DO, action_id)


def _p0(horizon: int = 1) -> OpenLoopPolicy:
    return OpenLoopPolicy(horizon, ())


def test_open_loop_wire_is_closed_canonical_and_has_no_free_text_rule() -> None:
    policy = OpenLoopPolicy(
        2,
        (
            ScheduledDecision(0, _do(), (CheckOrder("Q0"),)),
            ScheduledDecision(1, NO_NEW_ACTION),
        ),
    )
    wire = policy.to_wire()
    assert finite_policy_from_wire(copy.deepcopy(wire)) == policy
    assert canonical_json_bytes(finite_policy_from_wire(wire).to_wire()) == canonical_json_bytes(wire)

    malformed = copy.deepcopy(wire)
    malformed["decisions"][0]["rule"] = "if result > 0 then A1"
    with pytest.raises(ProtocolViolation, match="non-canonical fields"):
        finite_policy_from_wire(malformed)


def test_adaptive_wire_rejects_reference_cycle_and_nested_graph_shape() -> None:
    cyclic: dict = {
        "protocol": "ucm-finite-policy/1",
        "kind": "open_loop",
        "horizon": 1,
        "decisions": [],
    }
    cyclic["decisions"].append(cyclic)
    with pytest.raises(ProtocolViolation, match="cyclic policy graph"):
        finite_policy_from_wire(cyclic)

    policy = CheckThenTreatPolicy(
        3,
        ScheduledCheck(0, CheckOrder("Q0")),
        AdaptiveBranch(
            1,
            ResultPredicate("obs_0", ComparisonOperator.GT, 0),
            _do(),
            STOP_CONTROLLABLE,
        ),
    )
    malformed = policy.to_wire()
    malformed["branch"]["when_true"]["next_branch"] = {}
    with pytest.raises(ProtocolViolation, match="non-canonical fields"):
        finite_policy_from_wire(malformed)


def test_phase_order_and_delayed_result_visibility_are_exact() -> None:
    engine = _engine(result_delay=1)
    initial = engine.initial_snapshot(tick=0, plant_state={"x": 0})
    policy = OpenLoopPolicy(
        1, (ScheduledDecision(0, _do(), (CheckOrder("Q0"),)),)
    )
    first = engine.execute(initial, policy)
    assert tuple(record.phase for record in first.trace) == PHASE_ORDER
    assert first.final_snapshot.plant_state == {"x": 1}
    assert [
        event.kind for event in first.final_snapshot.public_events
    ].count(EventKind.OBSERVATION_AVAILABLE) == 0
    performed = next(
        event
        for event in first.final_snapshot.public_events
        if event.kind is EventKind.TEST_PERFORMED
    )
    assert performed.collected_at == 1
    assert len(first.final_snapshot.pending_observations) == 1
    assert first.final_snapshot.pending_observations[0].event.available_at == 2

    second = engine.execute(first.final_snapshot, _p0())
    result = next(
        event
        for event in second.final_snapshot.public_events
        if event.kind is EventKind.OBSERVATION_AVAILABLE
    )
    assert result.collected_at == 1
    assert result.available_at == 2
    assert result.payload["results"] == [{"channel_id": "obs_0", "value": 1}]


def test_adaptive_action_waits_until_result_is_available_at_a_later_decision() -> None:
    engine = _engine(result_delay=1)
    initial = engine.initial_snapshot(tick=0, plant_state={"x": 2})
    policy = CheckThenTreatPolicy(
        3,
        ScheduledCheck(0, CheckOrder("Q0")),
        AdaptiveBranch(
            1,
            ResultPredicate("obs_0", ComparisonOperator.GT, 1),
            _do(),
            STOP_CONTROLLABLE,
        ),
    )
    result = engine.execute(initial, policy)
    actions = [
        event
        for event in result.final_snapshot.public_events
        if event.kind is EventKind.PERFORMED_TREATMENT
    ]
    assert len(actions) == 1
    assert actions[0].occurred_at == 2
    decisions = [record for record in result.trace if record.phase.value == "decision"]
    assert [record.public_details["adaptive_status"] for record in decisions] == [
        "waiting",
        "waiting",
        "true_branch",
    ]


def test_duplicate_event_is_idempotent_but_uid_collision_is_rejected() -> None:
    original = CandidateVisibleEvent(
        EventKind.CONTEXT_AVAILABLE, 0, 0, "opaque-1", {"value": 1}
    )
    assert merge_visible_events((original,), (original,), as_of=0) == (original,)
    conflict = CandidateVisibleEvent(
        EventKind.CONTEXT_AVAILABLE, 0, 0, "opaque-1", {"value": 2}
    )
    with pytest.raises(ProtocolViolation, match="event_uid collision"):
        merge_visible_events((original,), (conflict,), as_of=0)


def test_no_new_continue_and_stop_have_distinct_runtime_meanings() -> None:
    engine = _engine(result_delay=0, duration=3)
    initial = engine.initial_snapshot(tick=0, plant_state={"x": 0})
    started = engine.execute(
        initial, OpenLoopPolicy(1, (ScheduledDecision(0, _do()),))
    ).final_snapshot
    assert started.active_control is not None
    assert started.active_control.remaining_ticks == 2

    no_new = engine.hypothetical(started, _p0()).final_snapshot
    continued = engine.hypothetical(
        started,
        OpenLoopPolicy(1, (ScheduledDecision(0, CONTINUE_CURRENT),)),
    ).final_snapshot
    stopped = engine.hypothetical(
        started,
        OpenLoopPolicy(1, (ScheduledDecision(0, STOP_CONTROLLABLE),)),
    ).final_snapshot

    assert no_new.plant_state == {"x": 2}
    assert no_new.active_control is not None
    assert no_new.active_control.remaining_ticks == 1
    assert continued.plant_state == {"x": 2}
    assert continued.active_control is not None
    assert continued.active_control.remaining_ticks == 2
    assert stopped.plant_state == {"x": 1}
    assert stopped.active_control is None
    assert len(no_new.public_events) + 1 == len(continued.public_events)
    assert len(no_new.public_events) + 1 == len(stopped.public_events)


def test_hypothetical_queries_are_pure_and_order_invariant() -> None:
    engine = _engine()
    factual = engine.initial_snapshot(tick=0, plant_state={"x": 0})
    before = copy.deepcopy(factual)
    action = OpenLoopPolicy(1, (ScheduledDecision(0, _do()),))
    noop = _p0()

    action_first = engine.hypothetical(factual, action)
    noop_second = engine.hypothetical(factual, noop)
    noop_first = engine.hypothetical(factual, noop)
    action_second = engine.hypothetical(factual, action)

    assert factual == before
    assert action_first.final_snapshot == action_second.final_snapshot
    assert noop_first.final_snapshot == noop_second.final_snapshot


def test_candidate_visible_parameters_and_collected_values_reject_private_keys() -> None:
    with pytest.raises(ProtocolViolation, match="judge-private"):
        CheckOrder("Q0", {"testId": "leak"})
    with pytest.raises(ProtocolViolation, match="judge-private"):
        ControlDirective(ControlKind.DO, "A1", {"generator_seed": 7})
    with pytest.raises(ProtocolViolation, match="judge-private"):
        CollectedResult({"obs_0": {"private": 1}})

