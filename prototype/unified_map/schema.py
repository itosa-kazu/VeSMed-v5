"""Candidate-visible and judge-private UCM benchmark schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
    reject_privileged_keys,
    validate_json_like,
)


PRIVILEGED_FIELD_NAMES = frozenset(
    {
        "world_id",
        "case_id",
        "test_id",
        "episode_id",
        "episode_index",
        "split",
        "generator_seed",
        "environment_seed",
        "hidden_state",
        "true_state",
        "oracle",
        "oracle_target",
        "future",
        "actual_future",
        "counterfactual_truth",
        "reward_to_come",
        "expected_answer",
        "expected_label",
        "expected_action",
        "private",
    }
)


def _exact_nonempty_string(value: object, label: str) -> None:
    if type(value) is not str or not value.strip():
        raise ProtocolViolation(f"{label} must be a non-empty exact string")


def _tick(value: object, label: str) -> None:
    if type(value) is not int or value < -(2**63) or value >= 2**63:
        raise ProtocolViolation(f"{label} must be a signed 64-bit integer tick")


def _sha256(value: object, label: str) -> None:
    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or len(value) != 71
    ):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} is not hexadecimal") from exc


class EventKind(str, Enum):
    OBSERVATION_AVAILABLE = "observation_available"
    PERFORMED_TREATMENT = "performed_treatment"
    TEST_ORDERED = "test_ordered"
    TEST_PERFORMED = "test_performed"
    CONTEXT_AVAILABLE = "context_available"


@dataclass(frozen=True, slots=True)
class CandidateVisibleEvent:
    kind: EventKind
    occurred_at: int
    available_at: int
    event_uid: str
    payload: dict[str, Any]
    collected_at: int | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not EventKind:
            raise ProtocolViolation("event kind must be EventKind")
        _tick(self.occurred_at, "occurred_at")
        _tick(self.available_at, "available_at")
        if self.collected_at is not None:
            _tick(self.collected_at, "collected_at")
        _exact_nonempty_string(self.event_uid, "event_uid")
        if type(self.payload) is not dict:
            raise ProtocolViolation("event payload must be an exact dict")
        reject_privileged_keys(
            self.payload,
            forbidden=PRIVILEGED_FIELD_NAMES,
            path="$.payload",
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "occurred_at": self.occurred_at,
            "collected_at": self.collected_at,
            "available_at": self.available_at,
            "event_uid": self.event_uid,
            "payload": self.payload,
        }


def event_sort_key(event: CandidateVisibleEvent) -> tuple[int, int, str, str]:
    return (
        event.available_at,
        event.occurred_at,
        event.kind.value,
        event.event_uid,
    )


@dataclass(frozen=True, slots=True)
class VisibleHistory:
    events: tuple[CandidateVisibleEvent, ...]
    as_of_available_at: int
    catalog_digest: str

    def __post_init__(self) -> None:
        if type(self.events) is not tuple or any(
            type(event) is not CandidateVisibleEvent for event in self.events
        ):
            raise ProtocolViolation("events must be a tuple of visible events")
        _tick(self.as_of_available_at, "as_of_available_at")
        _sha256(self.catalog_digest, "catalog_digest")
        if tuple(sorted(self.events, key=event_sort_key)) != self.events:
            raise ProtocolViolation("visible events are not in canonical order")
        invisible = [
            event.event_uid
            for event in self.events
            if event.available_at > self.as_of_available_at
        ]
        if invisible:
            raise ProtocolViolation(
                f"history contains events unavailable at cut: {invisible!r}"
            )
        uids = [event.event_uid for event in self.events]
        if len(set(uids)) != len(uids):
            raise ProtocolViolation("event_uid must be unique within a history")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": "ucm-visible-history/1",
            "as_of_available_at": self.as_of_available_at,
            "catalog_digest": self.catalog_digest,
            "events": [event.to_wire() for event in self.events],
        }

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


@dataclass(frozen=True, slots=True)
class VisibleDelta:
    advance_to: int
    events: tuple[CandidateVisibleEvent, ...] = ()

    def __post_init__(self) -> None:
        _tick(self.advance_to, "advance_to")
        if type(self.events) is not tuple or any(
            type(event) is not CandidateVisibleEvent for event in self.events
        ):
            raise ProtocolViolation("delta events must be a tuple")
        if tuple(sorted(self.events, key=event_sort_key)) != self.events:
            raise ProtocolViolation("delta events are not in canonical order")
        if any(event.available_at > self.advance_to for event in self.events):
            raise ProtocolViolation("delta contains an event not yet available")
        uids = [event.event_uid for event in self.events]
        if len(uids) != len(set(uids)):
            raise ProtocolViolation("delta event_uid values must be unique")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": "ucm-visible-delta/1",
            "advance_to": self.advance_to,
            "events": [event.to_wire() for event in self.events],
        }


class PlanKind(str, Enum):
    NO_NEW_ACTION = "no_new_action"
    CONTINUE_CURRENT = "continue_current"
    STOP_CONTROLLABLE = "stop_controllable"
    ACTION_SEQUENCE = "action_sequence"


@dataclass(frozen=True, slots=True)
class PlannedAction:
    offset: int
    action_id: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.offset) is not int or self.offset < 0:
            raise ProtocolViolation("action offset must be a non-negative integer")
        _exact_nonempty_string(self.action_id, "action_id")
        if type(self.parameters) is not dict:
            raise ProtocolViolation("action parameters must be an exact dict")
        reject_privileged_keys(
            self.parameters,
            forbidden=PRIVILEGED_FIELD_NAMES,
            path="$.action.parameters",
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "offset": self.offset,
            "action_id": self.action_id,
            "parameters": self.parameters,
        }


@dataclass(frozen=True, slots=True)
class ActionPlan:
    kind: PlanKind
    actions: tuple[PlannedAction, ...] = ()
    policy_digest: str | None = None

    def __post_init__(self) -> None:
        if type(self.kind) is not PlanKind:
            raise ProtocolViolation("plan kind must be PlanKind")
        if type(self.actions) is not tuple or any(
            type(action) is not PlannedAction for action in self.actions
        ):
            raise ProtocolViolation("plan actions must be a tuple")
        if self.kind is PlanKind.ACTION_SEQUENCE:
            if not self.actions:
                raise ProtocolViolation("action_sequence requires actions")
            if tuple(
                sorted(self.actions, key=lambda action: (action.offset, action.action_id))
            ) != self.actions:
                raise ProtocolViolation("actions are not in canonical order")
        elif self.actions:
            raise ProtocolViolation(f"{self.kind.value} cannot contain actions")
        if self.kind is PlanKind.CONTINUE_CURRENT:
            _sha256(self.policy_digest, "policy_digest")
        elif self.policy_digest is not None:
            raise ProtocolViolation(
                "policy_digest is only valid for continue_current"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "actions": [action.to_wire() for action in self.actions],
            "policy_digest": self.policy_digest,
        }


@dataclass(frozen=True, slots=True)
class DiagnosisQuery:
    label_catalog: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.label_catalog) is not tuple or not self.label_catalog:
            raise ProtocolViolation("diagnosis label_catalog must be non-empty")
        for label in self.label_catalog:
            _exact_nonempty_string(label, "diagnosis label")
        if len(set(self.label_catalog)) != len(self.label_catalog):
            raise ProtocolViolation("diagnosis labels must be unique")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": "ucm-diagnosis-query/1",
            "label_catalog": list(self.label_catalog),
        }


@dataclass(frozen=True, slots=True)
class RolloutQuery:
    horizon: int
    plan: ActionPlan
    requested_observables: tuple[str, ...]
    utility_digest: str

    def __post_init__(self) -> None:
        if type(self.horizon) is not int or self.horizon <= 0:
            raise ProtocolViolation("rollout horizon must be a positive integer")
        if type(self.plan) is not ActionPlan:
            raise ProtocolViolation("rollout plan must be ActionPlan")
        if type(self.requested_observables) is not tuple:
            raise ProtocolViolation("requested_observables must be a tuple")
        for observable in self.requested_observables:
            _exact_nonempty_string(observable, "observable")
        if len(set(self.requested_observables)) != len(self.requested_observables):
            raise ProtocolViolation("requested_observables must be unique")
        _sha256(self.utility_digest, "utility_digest")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": "ucm-rollout-query/1",
            "horizon": self.horizon,
            "plan": self.plan.to_wire(),
            "requested_observables": list(self.requested_observables),
            "utility_digest": self.utility_digest,
        }


@dataclass(frozen=True, slots=True)
class TrainerOnlyTargets:
    diagnostic_target: dict[str, float]
    factual_future: list[dict[str, Any]]
    action_propensities: list[dict[str, Any]]
    factual_utility: float

    def __post_init__(self) -> None:
        validate_json_like(self.diagnostic_target)
        validate_json_like(self.factual_future)
        validate_json_like(self.action_propensities)
        if type(self.factual_utility) not in {int, float}:
            raise ProtocolViolation("factual_utility must be numeric")
        validate_json_like(self.factual_utility)


@dataclass(frozen=True, slots=True)
class TrainingExample:
    history: VisibleHistory
    targets: TrainerOnlyTargets

    def __post_init__(self) -> None:
        if type(self.history) is not VisibleHistory:
            raise ProtocolViolation("training history must be VisibleHistory")
        if type(self.targets) is not TrainerOnlyTargets:
            raise ProtocolViolation("training targets must be trainer-only targets")


@dataclass(frozen=True, slots=True)
class JudgePrivateCase:
    """Judge-only container.  Never serialize this object for a candidate."""

    case_key: str
    environment_key: str
    split: str
    generator_seed: int
    public_history: VisibleHistory
    hidden_state: dict[str, Any]
    oracle_targets: dict[str, Any]

    def __post_init__(self) -> None:
        for value, label in (
            (self.case_key, "case_key"),
            (self.environment_key, "environment_key"),
            (self.split, "split"),
        ):
            _exact_nonempty_string(value, label)
        if type(self.generator_seed) is not int:
            raise ProtocolViolation("generator_seed must be an exact integer")
        if type(self.public_history) is not VisibleHistory:
            raise ProtocolViolation("public_history must be VisibleHistory")
        validate_json_like(self.hidden_state)
        validate_json_like(self.oracle_targets)

    def candidate_projection(self) -> VisibleHistory:
        return self.public_history
