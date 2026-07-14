from __future__ import annotations

import math

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
)
from prototype.unified_map.schema import (
    ActionPlan,
    CandidateVisibleEvent,
    EventKind,
    JudgePrivateCase,
    PlanKind,
    PlannedAction,
    TrainerOnlyTargets,
    TrainingExample,
    VisibleDelta,
    VisibleHistory,
)


DIGEST = "sha256:" + "a" * 64


def event(
    uid: str,
    *,
    available: int,
    occurred: int | None = None,
    payload: dict | None = None,
) -> CandidateVisibleEvent:
    return CandidateVisibleEvent(
        kind=EventKind.OBSERVATION_AVAILABLE,
        occurred_at=available if occurred is None else occurred,
        available_at=available,
        collected_at=occurred,
        event_uid=uid,
        payload=payload or {"channel": "obs_0", "value": 1.25},
    )


def test_canonical_json_is_order_stable_utf8_and_lf_terminated() -> None:
    left = canonical_json_bytes({"z": "患者", "a": [1, 2.5, None]})
    right = canonical_json_bytes({"a": [1, 2.5, None], "z": "患者"})
    assert left == right
    assert left == '{"a":[1,2.5,null],"z":"患者"}\n'.encode()


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf, (1, 2)])
def test_canonical_json_rejects_non_json_or_nonfinite_values(bad: object) -> None:
    with pytest.raises(ProtocolViolation):
        canonical_json_bytes({"bad": bad})


def test_visible_event_rejects_privileged_fields_at_any_depth() -> None:
    with pytest.raises(ProtocolViolation, match="judge-private"):
        event("e", available=0, payload={"nested": {"oracle": 7}})


@pytest.mark.parametrize("alias", ["testId", "case-id", "Generator Seed"])
def test_visible_event_rejects_privileged_key_aliases(alias: str) -> None:
    with pytest.raises(ProtocolViolation, match="judge-private"):
        event("e", available=0, payload={alias: "secret"})


def test_history_is_available_time_cut_and_canonical_ordered() -> None:
    early = event("early", available=0, occurred=-2)
    late = event("late", available=2, occurred=-3)
    history = VisibleHistory(
        events=(early, late), as_of_available_at=2, catalog_digest=DIGEST
    )
    assert history.to_wire()["events"][1]["event_uid"] == "late"
    with pytest.raises(ProtocolViolation, match="unavailable"):
        VisibleHistory(
            events=(early, late), as_of_available_at=1, catalog_digest=DIGEST
        )
    with pytest.raises(ProtocolViolation, match="canonical order"):
        VisibleHistory(
            events=(late, early), as_of_available_at=2, catalog_digest=DIGEST
        )


def test_empty_delta_can_advance_time_without_fabricating_an_event() -> None:
    delta = VisibleDelta(advance_to=4, events=())
    assert delta.to_wire() == {
        "protocol": "ucm-visible-delta/1",
        "advance_to": 4,
        "events": [],
    }


def test_noop_continue_stop_and_action_sequence_are_distinct() -> None:
    noop = ActionPlan(PlanKind.NO_NEW_ACTION)
    stop = ActionPlan(PlanKind.STOP_CONTROLLABLE)
    cont = ActionPlan(PlanKind.CONTINUE_CURRENT, policy_digest=DIGEST)
    action = ActionPlan(
        PlanKind.ACTION_SEQUENCE,
        actions=(PlannedAction(0, "A1", {"dose": 1.0}),),
    )
    assert len({str(x.to_wire()) for x in (noop, stop, cont, action)}) == 4
    with pytest.raises(ProtocolViolation):
        ActionPlan(PlanKind.ACTION_SEQUENCE)


def test_judge_truth_changes_cannot_change_candidate_projection() -> None:
    history = VisibleHistory(
        events=(event("e", available=0),),
        as_of_available_at=0,
        catalog_digest=DIGEST,
    )
    first = JudgePrivateCase(
        case_key="private-a",
        environment_key="private-env",
        split="sealed-test",
        generator_seed=1,
        public_history=history,
        hidden_state={"mode": 0},
        oracle_targets={"future": [0.0]},
    )
    second = JudgePrivateCase(
        case_key="private-b",
        environment_key="another-env",
        split="sealed-test",
        generator_seed=999,
        public_history=history,
        hidden_state={"mode": 1},
        oracle_targets={"future": [100.0]},
    )
    assert first.candidate_projection().digest == second.candidate_projection().digest


def test_training_targets_are_not_serialized_into_history() -> None:
    history = VisibleHistory(events=(), as_of_available_at=0, catalog_digest=DIGEST)
    targets = TrainerOnlyTargets(
        diagnostic_target={"C0": 1.0},
        factual_future=[{"value": 3.0}],
        action_propensities=[{"A1": 0.5}],
        factual_utility=-1.0,
    )
    training = TrainingExample(history, targets)
    encoded = canonical_json_bytes(training.history.to_wire())
    assert b"diagnostic_target" not in encoded
    assert b"factual_future" not in encoded
