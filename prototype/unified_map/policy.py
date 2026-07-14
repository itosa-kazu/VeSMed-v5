"""Typed finite-policy and event execution semantics for UCM benchmark v1.

The module is deliberately world-neutral.  A world supplies only two pure
judge-side callbacks (transition and collection) plus finite action/check
catalogues.  The engine owns the temporal contract:

``decision -> order -> perform -> transition -> collect -> available``.

In particular, an ordered or even collected check is not a result.  A result
can influence an adaptive policy only after its ``available_at`` time and only
through the public event ledger.  Policy queries are functional: the caller
must explicitly adopt the returned snapshot to make an execution factual.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, TypeAlias

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
    reject_privileged_keys,
    validate_json_like,
)
from .schema import (
    PRIVILEGED_FIELD_NAMES,
    CandidateVisibleEvent,
    EventKind,
    VisibleHistory,
    event_sort_key,
)


def _name(value: object, label: str) -> None:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a non-empty canonical string")


def _tick(value: object, label: str) -> None:
    if type(value) is not int or value < -(2**63) or value >= 2**63:
        raise ProtocolViolation(f"{label} must be a signed 64-bit integer tick")


def _offset(value: object, label: str) -> None:
    if type(value) is not int or value < 0 or value >= 2**63:
        raise ProtocolViolation(f"{label} must be a non-negative integer tick")


def _json_clone(value: Any) -> Any:
    validate_json_like(value)
    return copy.deepcopy(value)


def _closed_object(
    value: object, expected_keys: frozenset[str], label: str
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    keys = frozenset(value)
    if keys != expected_keys:
        missing = sorted(expected_keys - keys)
        extra = sorted(keys - expected_keys)
        raise ProtocolViolation(
            f"{label} has non-canonical fields; missing={missing!r}, extra={extra!r}"
        )
    return value


def _reject_reference_cycles(value: object) -> None:
    """Reject object/list reference cycles before ordinary JSON validation.

    JSON itself cannot express reference cycles, but callers can hand a Python
    object graph to ``finite_policy_from_wire``.  Reporting a typed protocol
    error is preferable to RecursionError or a non-terminating graph walk.
    """

    active: set[int] = set()

    def walk(node: object, path: str, depth: int) -> None:
        if depth > 64:
            raise ProtocolViolation(f"{path}: policy exceeds maximum depth")
        if type(node) not in {dict, list}:
            return
        identity = id(node)
        if identity in active:
            raise ProtocolViolation(f"{path}: cyclic policy graph is forbidden")
        active.add(identity)
        try:
            if type(node) is dict:
                for key, child in node.items():
                    walk(child, f"{path}.{key}", depth + 1)
            else:
                for index, child in enumerate(node):
                    walk(child, f"{path}[{index}]", depth + 1)
        finally:
            active.remove(identity)

    walk(value, "$", 0)


class ControlKind(str, Enum):
    """Four non-conflatable treatment-control meanings."""

    NO_NEW_ACTION = "no_new_action"
    CONTINUE_CURRENT = "continue_current"
    STOP_CONTROLLABLE = "stop_controllable"
    DO = "do"


@dataclass(frozen=True, slots=True)
class ControlDirective:
    kind: ControlKind
    action_id: str | None = None
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.kind) is not ControlKind:
            raise ProtocolViolation("control kind must be ControlKind")
        if type(self.parameters) is not dict:
            raise ProtocolViolation("control parameters must be an exact object")
        reject_privileged_keys(
            self.parameters,
            forbidden=PRIVILEGED_FIELD_NAMES,
            path="$.control.parameters",
        )
        object.__setattr__(self, "parameters", _json_clone(self.parameters))
        if self.kind is ControlKind.DO:
            _name(self.action_id, "control action_id")
        else:
            if self.action_id is not None:
                raise ProtocolViolation(
                    f"{self.kind.value} cannot carry an action_id"
                )
            if self.parameters:
                raise ProtocolViolation(
                    f"{self.kind.value} cannot carry action parameters"
                )

    def to_wire(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "action_id": self.action_id,
            "parameters": _json_clone(self.parameters),
        }


NO_NEW_ACTION = ControlDirective(ControlKind.NO_NEW_ACTION)
CONTINUE_CURRENT = ControlDirective(ControlKind.CONTINUE_CURRENT)
STOP_CONTROLLABLE = ControlDirective(ControlKind.STOP_CONTROLLABLE)


@dataclass(frozen=True, slots=True)
class CheckOrder:
    check_id: str
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _name(self.check_id, "check_id")
        if type(self.parameters) is not dict:
            raise ProtocolViolation("check parameters must be an exact object")
        reject_privileged_keys(
            self.parameters,
            forbidden=PRIVILEGED_FIELD_NAMES,
            path="$.check.parameters",
        )
        object.__setattr__(self, "parameters", _json_clone(self.parameters))

    def to_wire(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "parameters": _json_clone(self.parameters),
        }


def _check_sort_key(check: CheckOrder) -> tuple[str, bytes]:
    return check.check_id, canonical_json_bytes(check.parameters)


@dataclass(frozen=True, slots=True)
class ScheduledDecision:
    offset: int
    control: ControlDirective = NO_NEW_ACTION
    checks: tuple[CheckOrder, ...] = ()

    def __post_init__(self) -> None:
        _offset(self.offset, "decision offset")
        if type(self.control) is not ControlDirective:
            raise ProtocolViolation("decision control must be ControlDirective")
        if type(self.checks) is not tuple or any(
            type(check) is not CheckOrder for check in self.checks
        ):
            raise ProtocolViolation("decision checks must be a tuple of CheckOrder")
        if tuple(sorted(self.checks, key=_check_sort_key)) != self.checks:
            raise ProtocolViolation("decision checks are not in canonical order")
        keys = [canonical_json_bytes(check.to_wire()) for check in self.checks]
        if len(keys) != len(set(keys)):
            raise ProtocolViolation("a decision cannot duplicate an identical check")

    def to_wire(self) -> dict[str, Any]:
        return {
            "offset": self.offset,
            "control": self.control.to_wire(),
            "checks": [check.to_wire() for check in self.checks],
        }


class ComparisonOperator(str, Enum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"


@dataclass(frozen=True, slots=True)
class ResultPredicate:
    """A typed predicate over one channel in one available check result."""

    channel_id: str
    operator: ComparisonOperator
    value: str | int | float | bool | None

    def __post_init__(self) -> None:
        _name(self.channel_id, "predicate channel_id")
        if type(self.operator) is not ComparisonOperator:
            raise ProtocolViolation("predicate operator must be ComparisonOperator")
        if self.value is not None and type(self.value) not in {str, int, float, bool}:
            raise ProtocolViolation("predicate value must be a JSON scalar")
        validate_json_like(self.value)
        if self.operator in {
            ComparisonOperator.LT,
            ComparisonOperator.LE,
            ComparisonOperator.GT,
            ComparisonOperator.GE,
        } and type(self.value) not in {int, float}:
            raise ProtocolViolation("ordered predicate requires a numeric value")

    def to_wire(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "operator": self.operator.value,
            "value": self.value,
        }

    def evaluate(self, observed: Any) -> bool:
        validate_json_like(observed)
        if self.operator is ComparisonOperator.EQ:
            return type(observed) is type(self.value) and observed == self.value
        if self.operator is ComparisonOperator.NE:
            return not (type(observed) is type(self.value) and observed == self.value)
        if type(observed) not in {int, float}:
            raise ProtocolViolation(
                f"channel {self.channel_id!r} is non-numeric for ordered predicate"
            )
        target = self.value
        assert type(target) in {int, float}
        if self.operator is ComparisonOperator.LT:
            return observed < target
        if self.operator is ComparisonOperator.LE:
            return observed <= target
        if self.operator is ComparisonOperator.GT:
            return observed > target
        if self.operator is ComparisonOperator.GE:
            return observed >= target
        raise AssertionError("unreachable comparison operator")


@dataclass(frozen=True, slots=True)
class AdaptiveBranch:
    not_before_offset: int
    predicate: ResultPredicate
    when_true: ControlDirective
    when_false: ControlDirective

    def __post_init__(self) -> None:
        _offset(self.not_before_offset, "branch not_before_offset")
        if type(self.predicate) is not ResultPredicate:
            raise ProtocolViolation("branch predicate must be ResultPredicate")
        if type(self.when_true) is not ControlDirective:
            raise ProtocolViolation("when_true must be ControlDirective")
        if type(self.when_false) is not ControlDirective:
            raise ProtocolViolation("when_false must be ControlDirective")

    def to_wire(self) -> dict[str, Any]:
        return {
            "not_before_offset": self.not_before_offset,
            "predicate": self.predicate.to_wire(),
            "when_true": self.when_true.to_wire(),
            "when_false": self.when_false.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class ScheduledCheck:
    offset: int
    check: CheckOrder

    def __post_init__(self) -> None:
        _offset(self.offset, "check offset")
        if type(self.check) is not CheckOrder:
            raise ProtocolViolation("scheduled check must contain CheckOrder")

    def to_wire(self) -> dict[str, Any]:
        return {"offset": self.offset, "check": self.check.to_wire()}


class FinitePolicyKind(str, Enum):
    OPEN_LOOP = "open_loop"
    CHECK_THEN_TREAT = "check_then_treat"


@dataclass(frozen=True, slots=True)
class OpenLoopPolicy:
    horizon: int
    decisions: tuple[ScheduledDecision, ...]

    def __post_init__(self) -> None:
        if type(self.horizon) is not int or self.horizon <= 0:
            raise ProtocolViolation("policy horizon must be a positive integer")
        if type(self.decisions) is not tuple or any(
            type(decision) is not ScheduledDecision for decision in self.decisions
        ):
            raise ProtocolViolation("open-loop decisions must be a tuple")
        offsets = [decision.offset for decision in self.decisions]
        if offsets != sorted(offsets) or len(offsets) != len(set(offsets)):
            raise ProtocolViolation(
                "open-loop decision offsets must be sorted and unique"
            )
        if any(offset >= self.horizon for offset in offsets):
            raise ProtocolViolation("decision offset lies outside policy horizon")

    @property
    def kind(self) -> FinitePolicyKind:
        return FinitePolicyKind.OPEN_LOOP

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": "ucm-finite-policy/1",
            "kind": self.kind.value,
            "horizon": self.horizon,
            "decisions": [decision.to_wire() for decision in self.decisions],
        }

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


@dataclass(frozen=True, slots=True)
class CheckThenTreatPolicy:
    """One check followed by one terminal typed treatment branch.

    There are intentionally no node identifiers or ``goto`` fields.  This
    closed shape admits exactly one adaptive layer, so a nested branch or a
    policy cycle cannot be smuggled into the v1 wire format.
    """

    horizon: int
    order: ScheduledCheck
    branch: AdaptiveBranch

    def __post_init__(self) -> None:
        if type(self.horizon) is not int or self.horizon <= 0:
            raise ProtocolViolation("policy horizon must be a positive integer")
        if type(self.order) is not ScheduledCheck:
            raise ProtocolViolation("adaptive order must be ScheduledCheck")
        if type(self.branch) is not AdaptiveBranch:
            raise ProtocolViolation("adaptive branch must be AdaptiveBranch")
        if self.order.offset >= self.horizon:
            raise ProtocolViolation("check offset lies outside policy horizon")
        if not (
            self.order.offset < self.branch.not_before_offset < self.horizon
        ):
            raise ProtocolViolation(
                "adaptive branch must occur after its order and within horizon"
            )

    @property
    def kind(self) -> FinitePolicyKind:
        return FinitePolicyKind.CHECK_THEN_TREAT

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": "ucm-finite-policy/1",
            "kind": self.kind.value,
            "horizon": self.horizon,
            "order": self.order.to_wire(),
            "branch": self.branch.to_wire(),
        }

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


FinitePolicy: TypeAlias = OpenLoopPolicy | CheckThenTreatPolicy


def _control_from_wire(value: object, path: str) -> ControlDirective:
    obj = _closed_object(
        value, frozenset({"kind", "action_id", "parameters"}), path
    )
    try:
        kind = ControlKind(obj["kind"])
    except (TypeError, ValueError) as exc:
        raise ProtocolViolation(f"{path}.kind is not a control enum") from exc
    return ControlDirective(kind, obj["action_id"], obj["parameters"])


def _check_from_wire(value: object, path: str) -> CheckOrder:
    obj = _closed_object(value, frozenset({"check_id", "parameters"}), path)
    return CheckOrder(obj["check_id"], obj["parameters"])


def finite_policy_from_wire(value: object) -> FinitePolicy:
    """Parse the closed v1 finite-policy wire format.

    Free-text predicates, arbitrary graph nodes, callbacks and extra fields are
    rejected.  The result re-serializes to one canonical representation.
    """

    _reject_reference_cycles(value)
    validate_json_like(value, path="$.policy")
    if type(value) is not dict:
        raise ProtocolViolation("policy must be an exact object")
    if value.get("protocol") != "ucm-finite-policy/1":
        raise ProtocolViolation("unsupported finite policy protocol")
    try:
        kind = FinitePolicyKind(value.get("kind"))
    except (TypeError, ValueError) as exc:
        raise ProtocolViolation("policy kind is not a finite policy enum") from exc

    if kind is FinitePolicyKind.OPEN_LOOP:
        obj = _closed_object(
            value,
            frozenset({"protocol", "kind", "horizon", "decisions"}),
            "$.policy",
        )
        if type(obj["decisions"]) is not list:
            raise ProtocolViolation("$.policy.decisions must be an exact array")
        decisions: list[ScheduledDecision] = []
        for index, item in enumerate(obj["decisions"]):
            path = f"$.policy.decisions[{index}]"
            decision = _closed_object(
                item, frozenset({"offset", "control", "checks"}), path
            )
            if type(decision["checks"]) is not list:
                raise ProtocolViolation(f"{path}.checks must be an exact array")
            checks = tuple(
                _check_from_wire(check, f"{path}.checks[{check_index}]")
                for check_index, check in enumerate(decision["checks"])
            )
            decisions.append(
                ScheduledDecision(
                    decision["offset"],
                    _control_from_wire(decision["control"], f"{path}.control"),
                    checks,
                )
            )
        answer: FinitePolicy = OpenLoopPolicy(obj["horizon"], tuple(decisions))
    else:
        obj = _closed_object(
            value,
            frozenset({"protocol", "kind", "horizon", "order", "branch"}),
            "$.policy",
        )
        order = _closed_object(
            obj["order"], frozenset({"offset", "check"}), "$.policy.order"
        )
        branch = _closed_object(
            obj["branch"],
            frozenset(
                {"not_before_offset", "predicate", "when_true", "when_false"}
            ),
            "$.policy.branch",
        )
        predicate = _closed_object(
            branch["predicate"],
            frozenset({"channel_id", "operator", "value"}),
            "$.policy.branch.predicate",
        )
        try:
            operator = ComparisonOperator(predicate["operator"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation(
                "$.policy.branch.predicate.operator is not an enum"
            ) from exc
        answer = CheckThenTreatPolicy(
            horizon=obj["horizon"],
            order=ScheduledCheck(
                order["offset"],
                _check_from_wire(order["check"], "$.policy.order.check"),
            ),
            branch=AdaptiveBranch(
                branch["not_before_offset"],
                ResultPredicate(
                    predicate["channel_id"], operator, predicate["value"]
                ),
                _control_from_wire(
                    branch["when_true"], "$.policy.branch.when_true"
                ),
                _control_from_wire(
                    branch["when_false"], "$.policy.branch.when_false"
                ),
            ),
        )

    # This equality makes non-canonical aliases/omissions impossible even if a
    # future parser change accidentally becomes more permissive.
    if answer.to_wire() != value:
        raise ProtocolViolation("policy wire is not in canonical v1 form")
    return answer


@dataclass(frozen=True, slots=True)
class ActionRuntimeSpec:
    action_id: str
    duration_ticks: int = 1

    def __post_init__(self) -> None:
        _name(self.action_id, "action runtime action_id")
        if type(self.duration_ticks) is not int or self.duration_ticks <= 0:
            raise ProtocolViolation("action duration_ticks must be positive")


@dataclass(frozen=True, slots=True)
class CheckRuntimeSpec:
    check_id: str
    result_channels: tuple[str, ...]
    collection_delay: int = 1
    result_delay: int = 0

    def __post_init__(self) -> None:
        _name(self.check_id, "check runtime check_id")
        if type(self.result_channels) is not tuple or not self.result_channels:
            raise ProtocolViolation("result_channels must be a non-empty tuple")
        for channel_id in self.result_channels:
            _name(channel_id, "result channel_id")
        if tuple(sorted(set(self.result_channels))) != self.result_channels:
            raise ProtocolViolation("result_channels must be sorted and unique")
        if type(self.collection_delay) is not int or self.collection_delay <= 0:
            raise ProtocolViolation(
                "post-transition collection_delay must be a positive integer"
            )
        if type(self.result_delay) is not int or self.result_delay < 0:
            raise ProtocolViolation("result_delay must be non-negative")


@dataclass(frozen=True, slots=True)
class CollectedResult:
    values: dict[str, Any]
    availability_delay: int | None = None

    def __post_init__(self) -> None:
        if type(self.values) is not dict or not self.values:
            raise ProtocolViolation("collected values must be a non-empty object")
        for channel_id, value in self.values.items():
            _name(channel_id, "collected channel_id")
            reject_privileged_keys(
                value,
                forbidden=PRIVILEGED_FIELD_NAMES,
                path=f"$.collected.{channel_id}",
            )
        object.__setattr__(self, "values", _json_clone(self.values))
        if self.availability_delay is not None and (
            type(self.availability_delay) is not int
            or self.availability_delay < 0
        ):
            raise ProtocolViolation("availability_delay must be non-negative")


@dataclass(frozen=True, slots=True)
class ActiveControl:
    action_id: str
    parameters: dict[str, Any]
    remaining_ticks: int

    def __post_init__(self) -> None:
        _name(self.action_id, "active action_id")
        if type(self.parameters) is not dict:
            raise ProtocolViolation("active parameters must be an exact object")
        reject_privileged_keys(
            self.parameters,
            forbidden=PRIVILEGED_FIELD_NAMES,
            path="$.active.parameters",
        )
        object.__setattr__(self, "parameters", _json_clone(self.parameters))
        if type(self.remaining_ticks) is not int or self.remaining_ticks <= 0:
            raise ProtocolViolation("active remaining_ticks must be positive")


@dataclass(frozen=True, slots=True)
class TransitionRequest:
    from_tick: int
    to_tick: int
    effective_control: ActiveControl | None
    decision_control_kind: ControlKind


@dataclass(frozen=True, slots=True)
class CollectionRequest:
    check_id: str
    parameters: dict[str, Any]
    order_uid: str
    ordered_at: int
    collected_at: int


TransitionFunction: TypeAlias = Callable[
    [dict[str, Any], TransitionRequest], dict[str, Any]
]
CollectionFunction: TypeAlias = Callable[
    [dict[str, Any], CollectionRequest], CollectedResult
]


@dataclass(frozen=True, slots=True)
class _PendingCheck:
    order_uid: str
    check: CheckOrder
    ordered_at: int
    collect_at: int


@dataclass(frozen=True, slots=True)
class _PendingObservation:
    event: CandidateVisibleEvent


def _event_wire_bytes(event: CandidateVisibleEvent) -> bytes:
    return canonical_json_bytes(event.to_wire())


def merge_visible_events(
    existing: tuple[CandidateVisibleEvent, ...],
    incoming: tuple[CandidateVisibleEvent, ...],
    *,
    as_of: int,
) -> tuple[CandidateVisibleEvent, ...]:
    """Idempotently merge available events by UID.

    Replaying a byte-identical event is a no-op.  Reusing a UID for different
    content is a protocol violation rather than last-write-wins behavior.
    """

    _tick(as_of, "as_of")
    if type(existing) is not tuple or type(incoming) is not tuple:
        raise ProtocolViolation("event batches must be exact tuples")
    by_uid: dict[str, CandidateVisibleEvent] = {}
    for label, batch in (("existing", existing), ("incoming", incoming)):
        for event in batch:
            if type(event) is not CandidateVisibleEvent:
                raise ProtocolViolation(f"{label} batch contains a non-event")
            if event.available_at > as_of:
                raise ProtocolViolation(
                    f"event {event.event_uid!r} is unavailable at cut {as_of}"
                )
            prior = by_uid.get(event.event_uid)
            if prior is not None:
                if _event_wire_bytes(prior) != _event_wire_bytes(event):
                    raise ProtocolViolation(
                        f"event_uid collision for {event.event_uid!r}"
                    )
                continue
            by_uid[event.event_uid] = event
    return tuple(sorted(by_uid.values(), key=event_sort_key))


@dataclass(frozen=True, slots=True)
class EngineSnapshot:
    """Judge-side execution state; only ``visible_history`` is projectable."""

    tick: int
    plant_state: dict[str, Any]
    public_events: tuple[CandidateVisibleEvent, ...] = ()
    active_control: ActiveControl | None = None
    pending_checks: tuple[_PendingCheck, ...] = ()
    pending_observations: tuple[_PendingObservation, ...] = ()
    next_event_index: int = 0

    def __post_init__(self) -> None:
        _tick(self.tick, "snapshot tick")
        if type(self.plant_state) is not dict:
            raise ProtocolViolation("plant_state must be an exact object")
        validate_json_like(self.plant_state)
        object.__setattr__(self, "plant_state", _json_clone(self.plant_state))
        if type(self.public_events) is not tuple:
            raise ProtocolViolation("public_events must be an exact tuple")
        merged = merge_visible_events((), self.public_events, as_of=self.tick)
        if merged != self.public_events:
            raise ProtocolViolation(
                "public_events must be unique and in canonical event order"
            )
        if self.active_control is not None and type(self.active_control) is not ActiveControl:
            raise ProtocolViolation("active_control must be ActiveControl or None")
        if type(self.pending_checks) is not tuple or any(
            type(item) is not _PendingCheck for item in self.pending_checks
        ):
            raise ProtocolViolation("pending_checks must be an internal tuple")
        if tuple(
            sorted(self.pending_checks, key=lambda item: (item.collect_at, item.order_uid))
        ) != self.pending_checks:
            raise ProtocolViolation("pending_checks are not canonically ordered")
        if any(item.collect_at <= self.tick for item in self.pending_checks):
            raise ProtocolViolation("snapshot contains an overdue uncollected check")
        if type(self.pending_observations) is not tuple or any(
            type(item) is not _PendingObservation
            for item in self.pending_observations
        ):
            raise ProtocolViolation("pending_observations must be an internal tuple")
        if tuple(
            sorted(
                self.pending_observations,
                key=lambda item: event_sort_key(item.event),
            )
        ) != self.pending_observations:
            raise ProtocolViolation("pending observations are not canonically ordered")
        if any(
            item.event.available_at <= self.tick
            for item in self.pending_observations
        ):
            raise ProtocolViolation("snapshot contains an overdue available result")
        pending_uids = [item.event.event_uid for item in self.pending_observations]
        if len(pending_uids) != len(set(pending_uids)):
            raise ProtocolViolation("pending result event_uids must be unique")
        public_uids = {event.event_uid for event in self.public_events}
        if public_uids.intersection(pending_uids):
            raise ProtocolViolation("an event cannot be both public and pending")
        if type(self.next_event_index) is not int or self.next_event_index < 0:
            raise ProtocolViolation("next_event_index must be non-negative")

    def visible_history(self, catalog_digest: str) -> VisibleHistory:
        """Return the sole candidate-visible projection of an engine snapshot."""

        return VisibleHistory(self.public_events, self.tick, catalog_digest)

    @property
    def public_digest(self) -> str:
        return digest_json(
            {
                "as_of_available_at": self.tick,
                "events": [event.to_wire() for event in self.public_events],
            }
        )


class ExecutionPhase(str, Enum):
    DECISION = "decision"
    ORDER = "order"
    PERFORM = "perform"
    TRANSITION = "transition"
    COLLECT = "collect"
    AVAILABLE = "available"


PHASE_ORDER = (
    ExecutionPhase.DECISION,
    ExecutionPhase.ORDER,
    ExecutionPhase.PERFORM,
    ExecutionPhase.TRANSITION,
    ExecutionPhase.COLLECT,
    ExecutionPhase.AVAILABLE,
)


@dataclass(frozen=True, slots=True)
class PhaseRecord:
    phase: ExecutionPhase
    tick: int
    public_details: dict[str, Any]

    def __post_init__(self) -> None:
        if type(self.phase) is not ExecutionPhase:
            raise ProtocolViolation("phase must be ExecutionPhase")
        _tick(self.tick, "phase tick")
        if type(self.public_details) is not dict:
            raise ProtocolViolation("phase details must be an exact object")
        reject_privileged_keys(
            self.public_details,
            forbidden=PRIVILEGED_FIELD_NAMES,
            path="$.phase.public_details",
        )
        object.__setattr__(self, "public_details", _json_clone(self.public_details))

    def to_wire(self) -> dict[str, Any]:
        return {
            "phase": self.phase.value,
            "tick": self.tick,
            "public_details": _json_clone(self.public_details),
        }


@dataclass(frozen=True, slots=True)
class PolicyExecution:
    policy_digest: str
    initial_public_digest: str
    final_snapshot: EngineSnapshot
    trace: tuple[PhaseRecord, ...]

    def __post_init__(self) -> None:
        _name(self.policy_digest, "policy_digest")
        _name(self.initial_public_digest, "initial_public_digest")
        if type(self.final_snapshot) is not EngineSnapshot:
            raise ProtocolViolation("final_snapshot must be EngineSnapshot")
        if type(self.trace) is not tuple or any(
            type(record) is not PhaseRecord for record in self.trace
        ):
            raise ProtocolViolation("execution trace must be a tuple")


class PolicyEngine:
    """Pure event/policy interpreter shared by benchmark generators/oracles."""

    def __init__(
        self,
        *,
        actions: tuple[ActionRuntimeSpec, ...],
        checks: tuple[CheckRuntimeSpec, ...],
        transition: TransitionFunction,
        collect: CollectionFunction,
    ) -> None:
        if type(actions) is not tuple or any(
            type(spec) is not ActionRuntimeSpec for spec in actions
        ):
            raise ProtocolViolation("actions must be a tuple of ActionRuntimeSpec")
        if type(checks) is not tuple or any(
            type(spec) is not CheckRuntimeSpec for spec in checks
        ):
            raise ProtocolViolation("checks must be a tuple of CheckRuntimeSpec")
        if len({spec.action_id for spec in actions}) != len(actions):
            raise ProtocolViolation("runtime action ids must be unique")
        if len({spec.check_id for spec in checks}) != len(checks):
            raise ProtocolViolation("runtime check ids must be unique")
        if not callable(transition) or not callable(collect):
            raise ProtocolViolation("transition and collect must be callable")
        self._actions = {spec.action_id: spec for spec in actions}
        self._checks = {spec.check_id: spec for spec in checks}
        self._transition = transition
        self._collect = collect

    @staticmethod
    def initial_snapshot(
        *,
        tick: int,
        plant_state: dict[str, Any],
        public_events: tuple[CandidateVisibleEvent, ...] = (),
        active_control: ActiveControl | None = None,
    ) -> EngineSnapshot:
        return EngineSnapshot(
            tick=tick,
            plant_state=plant_state,
            public_events=public_events,
            active_control=active_control,
        )

    @staticmethod
    def _clone_snapshot(snapshot: EngineSnapshot) -> EngineSnapshot:
        if type(snapshot) is not EngineSnapshot:
            raise ProtocolViolation("snapshot must be EngineSnapshot")
        return EngineSnapshot(
            tick=snapshot.tick,
            plant_state=_json_clone(snapshot.plant_state),
            public_events=snapshot.public_events,
            active_control=snapshot.active_control,
            pending_checks=snapshot.pending_checks,
            pending_observations=snapshot.pending_observations,
            next_event_index=snapshot.next_event_index,
        )

    @staticmethod
    def _allocate_event_uid(
        snapshot: EngineSnapshot, reserved: set[str]
    ) -> tuple[str, int]:
        used = {event.event_uid for event in snapshot.public_events}
        used.update(
            item.event.event_uid for item in snapshot.pending_observations
        )
        used.update(reserved)
        index = snapshot.next_event_index
        while True:
            candidate = f"evt-{index:016x}"
            index += 1
            if candidate not in used:
                return candidate, index

    def _validate_check(self, check: CheckOrder) -> CheckRuntimeSpec:
        try:
            return self._checks[check.check_id]
        except KeyError as exc:
            raise ProtocolViolation(f"unknown check_id {check.check_id!r}") from exc

    def _apply_control(
        self,
        snapshot: EngineSnapshot,
        control: ControlDirective,
        *,
        event_uid: str | None,
    ) -> tuple[ActiveControl | None, CandidateVisibleEvent | None]:
        tick = snapshot.tick
        if control.kind is ControlKind.NO_NEW_ACTION:
            return snapshot.active_control, None

        if control.kind is ControlKind.DO:
            assert control.action_id is not None
            try:
                spec = self._actions[control.action_id]
            except KeyError as exc:
                raise ProtocolViolation(
                    f"unknown action_id {control.action_id!r}"
                ) from exc
            active = ActiveControl(
                control.action_id, control.parameters, spec.duration_ticks
            )
            payload = {
                "control_kind": ControlKind.DO.value,
                "action_id": active.action_id,
                "parameters": _json_clone(active.parameters),
            }
        elif control.kind is ControlKind.CONTINUE_CURRENT:
            if snapshot.active_control is None:
                raise ProtocolViolation(
                    "continue_current requires an active controllable action"
                )
            spec = self._actions.get(snapshot.active_control.action_id)
            if spec is None:
                raise ProtocolViolation("active action is absent from runtime catalog")
            active = ActiveControl(
                snapshot.active_control.action_id,
                snapshot.active_control.parameters,
                spec.duration_ticks,
            )
            payload = {
                "control_kind": ControlKind.CONTINUE_CURRENT.value,
                "action_id": active.action_id,
                "parameters": _json_clone(active.parameters),
            }
        else:
            active = None
            payload = {
                "control_kind": ControlKind.STOP_CONTROLLABLE.value,
                "stopped_action_id": (
                    snapshot.active_control.action_id
                    if snapshot.active_control is not None
                    else None
                ),
            }

        assert event_uid is not None
        event = CandidateVisibleEvent(
            kind=EventKind.PERFORMED_TREATMENT,
            occurred_at=tick,
            collected_at=None,
            available_at=tick,
            event_uid=event_uid,
            payload=payload,
        )
        return active, event

    @staticmethod
    def _decrement_active(active: ActiveControl | None) -> ActiveControl | None:
        if active is None or active.remaining_ticks == 1:
            return None
        return ActiveControl(
            active.action_id, active.parameters, active.remaining_ticks - 1
        )

    @staticmethod
    def _result_for_order(
        public_events: tuple[CandidateVisibleEvent, ...], order_uid: str
    ) -> CandidateVisibleEvent | None:
        matches = [
            event
            for event in public_events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("order_uid") == order_uid
        ]
        if len(matches) > 1:
            raise ProtocolViolation("one check order produced multiple result events")
        return matches[0] if matches else None

    @staticmethod
    def _predicate_value(
        result_event: CandidateVisibleEvent, channel_id: str
    ) -> Any:
        results = result_event.payload.get("results")
        if type(results) is not list:
            raise ProtocolViolation("observation result has no typed results array")
        matches = [
            item
            for item in results
            if type(item) is dict and item.get("channel_id") == channel_id
        ]
        if len(matches) != 1 or frozenset(matches[0]) != frozenset(
            {"channel_id", "value"}
        ):
            raise ProtocolViolation(
                f"available result does not contain exactly one {channel_id!r} value"
            )
        return matches[0]["value"]

    def execute(
        self, snapshot: EngineSnapshot, policy: FinitePolicy
    ) -> PolicyExecution:
        """Execute a policy functionally and return the uncommitted future.

        The input snapshot and engine carry no mutable episode cursor.  Thus
        invoking this method for hypothetical policies in any order cannot
        alter the factual lineage.  To perform a factual rollout, the runner
        explicitly adopts ``result.final_snapshot``.
        """

        if type(policy) not in {OpenLoopPolicy, CheckThenTreatPolicy}:
            raise ProtocolViolation("policy must be a finite v1 policy")
        working = self._clone_snapshot(snapshot)
        initial_public_digest = working.public_digest
        trace: list[PhaseRecord] = []
        open_decisions = (
            {decision.offset: decision for decision in policy.decisions}
            if type(policy) is OpenLoopPolicy
            else {}
        )
        adaptive_order_uid: str | None = None
        adaptive_branch_fired = False

        for offset in range(policy.horizon):
            tick = working.tick
            control = NO_NEW_ACTION
            checks_to_order: tuple[CheckOrder, ...] = ()
            decision_detail: dict[str, Any] = {
                "offset": offset,
                "policy_kind": policy.kind.value,
                "adaptive_status": "not_applicable",
            }

            if type(policy) is OpenLoopPolicy:
                decision = open_decisions.get(offset)
                if decision is not None:
                    control = decision.control
                    checks_to_order = decision.checks
            else:
                if offset == policy.order.offset:
                    checks_to_order = (policy.order.check,)
                decision_detail["adaptive_status"] = "waiting"
                if (
                    not adaptive_branch_fired
                    and adaptive_order_uid is not None
                    and offset >= policy.branch.not_before_offset
                ):
                    available_result = self._result_for_order(
                        working.public_events, adaptive_order_uid
                    )
                    if available_result is not None:
                        observed = self._predicate_value(
                            available_result, policy.branch.predicate.channel_id
                        )
                        predicate_result = policy.branch.predicate.evaluate(observed)
                        control = (
                            policy.branch.when_true
                            if predicate_result
                            else policy.branch.when_false
                        )
                        adaptive_branch_fired = True
                        decision_detail["adaptive_status"] = (
                            "true_branch" if predicate_result else "false_branch"
                        )
                if adaptive_branch_fired and decision_detail["adaptive_status"] == "waiting":
                    decision_detail["adaptive_status"] = "completed"

            trace.append(
                PhaseRecord(ExecutionPhase.DECISION, tick, decision_detail)
            )

            reserved: set[str] = set()
            next_index = working.next_event_index
            order_events: list[CandidateVisibleEvent] = []
            new_pending_checks = list(working.pending_checks)
            for check in checks_to_order:
                spec = self._validate_check(check)
                allocation_view = EngineSnapshot(
                    tick=working.tick,
                    plant_state=working.plant_state,
                    public_events=working.public_events,
                    active_control=working.active_control,
                    pending_checks=working.pending_checks,
                    pending_observations=working.pending_observations,
                    next_event_index=next_index,
                )
                event_uid, next_index = self._allocate_event_uid(
                    allocation_view, reserved
                )
                reserved.add(event_uid)
                order_uid = f"order-{event_uid[4:]}"
                event = CandidateVisibleEvent(
                    kind=EventKind.TEST_ORDERED,
                    occurred_at=tick,
                    collected_at=None,
                    available_at=tick,
                    event_uid=event_uid,
                    payload={
                        "check_id": check.check_id,
                        "order_uid": order_uid,
                        "parameters": _json_clone(check.parameters),
                    },
                )
                order_events.append(event)
                new_pending_checks.append(
                    _PendingCheck(
                        order_uid=order_uid,
                        check=check,
                        ordered_at=tick,
                        collect_at=tick + spec.collection_delay,
                    )
                )
                if type(policy) is CheckThenTreatPolicy:
                    if adaptive_order_uid is not None:
                        raise ProtocolViolation(
                            "check-then-treat policy ordered more than one check"
                        )
                    adaptive_order_uid = order_uid

            public_after_order = merge_visible_events(
                working.public_events, tuple(order_events), as_of=tick
            )
            trace.append(
                PhaseRecord(
                    ExecutionPhase.ORDER,
                    tick,
                    {"ordered_event_uids": [event.event_uid for event in order_events]},
                )
            )

            perform_uid: str | None = None
            if control.kind is not ControlKind.NO_NEW_ACTION:
                allocation_view = EngineSnapshot(
                    tick=tick,
                    plant_state=working.plant_state,
                    public_events=public_after_order,
                    active_control=working.active_control,
                    pending_checks=tuple(
                        sorted(
                            new_pending_checks,
                            key=lambda item: (item.collect_at, item.order_uid),
                        )
                    ),
                    pending_observations=working.pending_observations,
                    next_event_index=next_index,
                )
                perform_uid, next_index = self._allocate_event_uid(
                    allocation_view, reserved
                )
                reserved.add(perform_uid)
            active_during_transition, perform_event = self._apply_control(
                working, control, event_uid=perform_uid
            )
            public_after_perform = merge_visible_events(
                public_after_order,
                (perform_event,) if perform_event is not None else (),
                as_of=tick,
            )
            trace.append(
                PhaseRecord(
                    ExecutionPhase.PERFORM,
                    tick,
                    {
                        "performed_event_uids": (
                            [perform_event.event_uid]
                            if perform_event is not None
                            else []
                        ),
                        "control_kind": control.kind.value,
                    },
                )
            )

            transition_request = TransitionRequest(
                from_tick=tick,
                to_tick=tick + 1,
                effective_control=active_during_transition,
                decision_control_kind=control.kind,
            )
            transition_input = _json_clone(working.plant_state)
            transitioned = self._transition(transition_input, transition_request)
            if type(transitioned) is not dict:
                raise ProtocolViolation("transition callback must return an exact object")
            validate_json_like(transitioned)
            transitioned = _json_clone(transitioned)
            trace.append(
                PhaseRecord(
                    ExecutionPhase.TRANSITION,
                    tick + 1,
                    {
                        "from_tick": tick,
                        "to_tick": tick + 1,
                        "effective_action_id": (
                            active_during_transition.action_id
                            if active_during_transition is not None
                            else None
                        ),
                    },
                )
            )

            due_checks = sorted(
                (
                    pending
                    for pending in new_pending_checks
                    if pending.collect_at == tick + 1
                ),
                key=lambda item: (item.collect_at, item.order_uid),
            )
            future_checks = tuple(
                pending
                for pending in new_pending_checks
                if pending.collect_at > tick + 1
            )
            collect_events: list[CandidateVisibleEvent] = []
            new_pending_observations = list(working.pending_observations)
            for pending in due_checks:
                spec = self._checks[pending.check.check_id]
                allocation_view = EngineSnapshot(
                    tick=tick,
                    plant_state=transitioned,
                    public_events=public_after_perform,
                    active_control=active_during_transition,
                    pending_checks=(),
                    pending_observations=tuple(
                        sorted(
                            new_pending_observations,
                            key=lambda item: event_sort_key(item.event),
                        )
                    ),
                    next_event_index=next_index,
                )
                performed_uid, next_index = self._allocate_event_uid(
                    allocation_view, reserved
                )
                reserved.add(performed_uid)
                performed = CandidateVisibleEvent(
                    kind=EventKind.TEST_PERFORMED,
                    occurred_at=tick + 1,
                    collected_at=tick + 1,
                    available_at=tick + 1,
                    event_uid=performed_uid,
                    payload={
                        "check_id": pending.check.check_id,
                        "order_uid": pending.order_uid,
                        "parameters": _json_clone(pending.check.parameters),
                    },
                )
                collect_events.append(performed)

                request = CollectionRequest(
                    check_id=pending.check.check_id,
                    parameters=_json_clone(pending.check.parameters),
                    order_uid=pending.order_uid,
                    ordered_at=pending.ordered_at,
                    collected_at=tick + 1,
                )
                collected = self._collect(_json_clone(transitioned), request)
                if type(collected) is not CollectedResult:
                    raise ProtocolViolation(
                        "collection callback must return CollectedResult"
                    )
                if tuple(sorted(collected.values)) != spec.result_channels:
                    raise ProtocolViolation(
                        f"check {spec.check_id!r} returned channels outside its schema"
                    )
                delay = (
                    spec.result_delay
                    if collected.availability_delay is None
                    else collected.availability_delay
                )
                allocation_view = EngineSnapshot(
                    tick=tick,
                    plant_state=transitioned,
                    public_events=public_after_perform,
                    active_control=active_during_transition,
                    pending_checks=(),
                    pending_observations=tuple(
                        sorted(
                            new_pending_observations,
                            key=lambda item: event_sort_key(item.event),
                        )
                    ),
                    next_event_index=next_index,
                )
                result_uid, next_index = self._allocate_event_uid(
                    allocation_view, reserved
                )
                reserved.add(result_uid)
                result_event = CandidateVisibleEvent(
                    kind=EventKind.OBSERVATION_AVAILABLE,
                    occurred_at=tick + 1,
                    collected_at=tick + 1,
                    available_at=tick + 1 + delay,
                    event_uid=result_uid,
                    payload={
                        "check_id": pending.check.check_id,
                        "order_uid": pending.order_uid,
                        "results": [
                            {"channel_id": channel_id, "value": value}
                            for channel_id, value in sorted(collected.values.items())
                        ],
                    },
                )
                new_pending_observations.append(
                    _PendingObservation(result_event)
                )

            public_after_collect = merge_visible_events(
                public_after_perform, tuple(collect_events), as_of=tick + 1
            )
            trace.append(
                PhaseRecord(
                    ExecutionPhase.COLLECT,
                    tick + 1,
                    {
                        "performed_check_event_uids": [
                            event.event_uid for event in collect_events
                        ]
                    },
                )
            )

            due_observations = tuple(
                sorted(
                    (
                        item.event
                        for item in new_pending_observations
                        if item.event.available_at <= tick + 1
                    ),
                    key=event_sort_key,
                )
            )
            future_observations = tuple(
                sorted(
                    (
                        item
                        for item in new_pending_observations
                        if item.event.available_at > tick + 1
                    ),
                    key=lambda item: event_sort_key(item.event),
                )
            )
            public_after_available = merge_visible_events(
                public_after_collect, due_observations, as_of=tick + 1
            )
            trace.append(
                PhaseRecord(
                    ExecutionPhase.AVAILABLE,
                    tick + 1,
                    {
                        "available_result_event_uids": [
                            event.event_uid for event in due_observations
                        ]
                    },
                )
            )

            working = EngineSnapshot(
                tick=tick + 1,
                plant_state=transitioned,
                public_events=public_after_available,
                active_control=self._decrement_active(active_during_transition),
                pending_checks=tuple(
                    sorted(
                        future_checks,
                        key=lambda item: (item.collect_at, item.order_uid),
                    )
                ),
                pending_observations=future_observations,
                next_event_index=next_index,
            )

        expected_phases = PHASE_ORDER * policy.horizon
        actual_phases = tuple(record.phase for record in trace)
        if actual_phases != expected_phases:
            raise AssertionError("internal phase-order invariant violated")
        return PolicyExecution(
            policy_digest=policy.digest,
            initial_public_digest=initial_public_digest,
            final_snapshot=working,
            trace=tuple(trace),
        )

    def hypothetical(
        self, snapshot: EngineSnapshot, policy: FinitePolicy
    ) -> PolicyExecution:
        """Explicit pure-query spelling used by counterfactual callers."""

        before = snapshot.public_digest
        result = self.execute(snapshot, policy)
        if snapshot.public_digest != before:
            raise ProtocolViolation("hypothetical query mutated factual public state")
        return result


__all__ = [
    "ActionRuntimeSpec",
    "ActiveControl",
    "AdaptiveBranch",
    "CheckOrder",
    "CheckRuntimeSpec",
    "CheckThenTreatPolicy",
    "CollectedResult",
    "CollectionRequest",
    "ComparisonOperator",
    "CONTINUE_CURRENT",
    "ControlDirective",
    "ControlKind",
    "EngineSnapshot",
    "ExecutionPhase",
    "FinitePolicy",
    "FinitePolicyKind",
    "NO_NEW_ACTION",
    "OpenLoopPolicy",
    "PHASE_ORDER",
    "PhaseRecord",
    "PolicyEngine",
    "PolicyExecution",
    "ResultPredicate",
    "STOP_CONTROLLABLE",
    "ScheduledCheck",
    "ScheduledDecision",
    "TransitionRequest",
    "finite_policy_from_wire",
    "merge_visible_events",
]
