"""Public-wire adapter for the source-distinct red-team v2 pack.

The adapter is the only v2 module that loads the two pre-sealed candidate
implementations.  It converts independent pack wires into the existing public
catalog/history/training DTOs.  It does not import a frozen world, registry,
fixture, oracle, evaluator, or benchmark runner.
"""

from __future__ import annotations

import base64
import contextlib
import json
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Iterator

from . import candidate_families as _sealed_module
from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes, digest_json
from .independent_f18 import IndependentStructuralEnsemble
from .schema import (
    ActionPlan,
    CandidateVisibleEvent,
    EventKind,
    PlanKind,
    PlannedAction,
    VisibleDelta,
    VisibleHistory,
)


ADAPTER_PROTOCOL = "ucm-source-distinct-redteam-adapter/2"

# These public DTO constructors are intentionally obtained from the sealed
# candidate protocol namespace.  This avoids importing any simulator module in
# red-team code while still satisfying the exact public DTO type checks used by
# the already-sealed implementation.
PublicCatalog = _sealed_module.PublicCatalog
PublicTrainingRecord = _sealed_module.PublicTrainingRecord
_PUBLIC_DTO_GLOBALS = PublicCatalog.__post_init__.__globals__
ChannelSpec = _PUBLIC_DTO_GLOBALS["ChannelSpec"]
ActionSpec = _PUBLIC_DTO_GLOBALS["ActionSpec"]
CheckSpec = _PUBLIC_DTO_GLOBALS["CheckSpec"]
_CONTRACT_GLOBALS = PublicTrainingRecord.__post_init__.__globals__
RolloutTarget = _CONTRACT_GLOBALS["RolloutTarget"]
SharedPatientState = _CONTRACT_GLOBALS["SharedPatientState"]


def candidate_source_bindings() -> dict[str, str]:
    return {
        "sealed_f18": digest_bytes(Path(_sealed_module.__file__).read_bytes()),
        "independent_f18": digest_bytes(
            Path(sys.modules[IndependentStructuralEnsemble.__module__].__file__).read_bytes()
        ),
    }


def _exact_keys(value: dict[str, Any], required: set[str], label: str) -> None:
    if type(value) is not dict or set(value) != required:
        raise ProtocolViolation(f"{label} wire fields mismatch")


def catalog_from_wire(wire: dict[str, Any]) -> Any:
    _exact_keys(
        wire,
        {"protocol", "observations", "actions", "checks", "diagnostic_labels", "horizons", "time_unit"},
        "catalog",
    )
    if wire["protocol"] != "ucm-public-catalog/1":
        raise ProtocolViolation("catalog protocol mismatch")
    observations = tuple(
        ChannelSpec(
            row["channel_id"],
            row["value_type"],
            row["unit"],
            None if row["valid_range"] is None else tuple(row["valid_range"]),
        )
        for row in wire["observations"]
    )
    actions = tuple(
        ActionSpec(row["action_id"], row["parameter_schema"], row["cost"])
        for row in wire["actions"]
    )
    checks = tuple(
        CheckSpec(
            row["check_id"],
            tuple(row["result_channels"]),
            tuple(row["delay_support"]),
            row["cost"],
        )
        for row in wire["checks"]
    )
    catalog = PublicCatalog(
        observations,
        actions,
        checks,
        tuple(wire["diagnostic_labels"]),
        tuple(wire["horizons"]),
        wire["time_unit"],
    )
    if catalog.to_wire() != wire:
        raise ProtocolViolation("catalog wire did not round-trip")
    return catalog


def event_from_wire(wire: dict[str, Any]) -> CandidateVisibleEvent:
    _exact_keys(
        wire,
        {"kind", "occurred_at", "collected_at", "available_at", "event_uid", "payload"},
        "event",
    )
    return CandidateVisibleEvent(
        EventKind(wire["kind"]),
        wire["occurred_at"],
        wire["available_at"],
        wire["event_uid"],
        wire["payload"],
        wire["collected_at"],
    )


def history_from_wire(wire: dict[str, Any]) -> VisibleHistory:
    _exact_keys(wire, {"protocol", "as_of_available_at", "catalog_digest", "events"}, "history")
    if wire["protocol"] != "ucm-visible-history/1":
        raise ProtocolViolation("history protocol mismatch")
    history = VisibleHistory(
        tuple(event_from_wire(row) for row in wire["events"]),
        wire["as_of_available_at"],
        wire["catalog_digest"],
    )
    if history.to_wire() != wire:
        raise ProtocolViolation("history wire did not round-trip")
    return history


def plan_from_wire(wire: dict[str, Any]) -> ActionPlan:
    _exact_keys(wire, {"plan_id", "kind", "actions", "policy_digest"}, "plan")
    return ActionPlan(
        PlanKind(wire["kind"]),
        tuple(
            PlannedAction(row["offset"], row["action_id"], row["parameters"])
            for row in wire["actions"]
        ),
        wire["policy_digest"],
    )


def _plan_index(pack: dict[str, Any]) -> dict[str, ActionPlan]:
    return {row["plan_id"]: plan_from_wire(row) for row in pack["plans"]}


def training_records(pack: dict[str, Any]) -> tuple[Any, tuple[Any, ...]]:
    catalog = catalog_from_wire(pack["catalog"])
    if catalog.digest != pack["catalog_digest"]:
        raise ProtocolViolation("pack catalog digest mismatch")
    plans = _plan_index(pack)
    rows: list[Any] = []
    for episode in pack["training_episodes"]:
        private = episode["judge_private"]
        rollouts = tuple(
            RolloutTarget(
                row["horizon"],
                plans[row["plan_id"]],
                tuple(row["signature"]),
                row["expected_utility"],
            )
            for row in private["oracle_rows"]
            # The opposite-response operator is declared in the public scope
            # but its target is deliberately withheld from public training.
            # Red-team evaluation therefore measures honest novel-treatment
            # handling (including abstention), not memorization of its oracle.
            if row["plan_id"] not in {"biphasic", "new_check"}
        )
        rows.append(
            PublicTrainingRecord(
                history_from_wire(episode["public_history"]),
                dict(private["diagnostic_target"]),
                rollouts,
            )
        )
    return catalog, tuple(rows)


_AUDIT_LOCAL = threading.local()
_AUDIT_INSTALLED = False
_AUDIT_LOCK = threading.Lock()
_SENSITIVE_PREFIXES = (
    "open",
    "os.listdir",
    "os.scandir",
    "os.remove",
    "os.rename",
    "os.system",
    "subprocess.",
    "socket.",
    "urllib.",
    "http.",
    "ctypes.dlopen",
    "winreg.",
)


def _safe_audit_arg(value: Any) -> Any:
    if value is None or type(value) in {bool, int, float, str}:
        text = value if type(value) is not str else value[:512]
        return text
    if type(value) is bytes:
        return {"bytes": len(value), "digest": digest_bytes(value)}
    return {"type": type(value).__name__, "repr": repr(value)[:512]}


def _audit_hook(event: str, args: tuple[Any, ...]) -> None:
    scope = getattr(_AUDIT_LOCAL, "scope", None)
    if scope is None or not event.startswith(_SENSITIVE_PREFIXES):
        return
    row = {
        "hook": "sys.addaudithook",
        "event": event,
        "args": [_safe_audit_arg(value) for value in args[:8]],
        "denied": bool(scope["deny"]),
    }
    scope["events"].append(row)
    if scope["deny"]:
        raise ProtocolViolation(f"patient-time candidate access denied by audit hook: {event}")


def _ensure_audit_hook() -> None:
    global _AUDIT_INSTALLED
    with _AUDIT_LOCK:
        if not _AUDIT_INSTALLED:
            sys.addaudithook(_audit_hook)
            _AUDIT_INSTALLED = True


@contextlib.contextmanager
def audit_scope(*, deny_sensitive_access: bool) -> Iterator[list[dict[str, Any]]]:
    _ensure_audit_hook()
    if getattr(_AUDIT_LOCAL, "scope", None) is not None:
        raise ProtocolViolation("nested red-team audit scopes are forbidden")
    scope = {"deny": deny_sensitive_access, "events": []}
    _AUDIT_LOCAL.scope = scope
    try:
        yield scope["events"]
    finally:
        _AUDIT_LOCAL.scope = None


def call_with_access_trace(
    operation: str,
    implementation_id: str,
    function: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> tuple[Any, dict[str, Any]]:
    deny = operation != "fit"
    with audit_scope(deny_sensitive_access=deny) as events:
        result = function(*args, **kwargs)
    return result, {
        "protocol": "ucm-redteam-v2-access-trace/1",
        "implementation_id": implementation_id,
        "operation": operation,
        "enforcement": "python_audit_hook_deny_patient_time_io_process_network",
        "deny_sensitive_access": deny,
        "sensitive_event_count": len(events),
        "events": events,
        "passed": not any(row["denied"] for row in events),
    }


def fit_implementations(
    pack: dict[str, Any],
    *,
    model_seed: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    catalog, records = training_records(pack)
    candidates = {
        "sealed_f18": _sealed_module.make_candidate("F18"),
        "independent_f18": IndependentStructuralEnsemble(),
    }
    traces: list[dict[str, Any]] = []
    for implementation_id, candidate in candidates.items():
        _, trace = call_with_access_trace(
            "fit",
            implementation_id,
            candidate.fit,
            (catalog,),
            records,
            model_seed=model_seed,
        )
        traces.append(trace)
    return candidates, traces


def rehydrate_state(closure: dict[str, Any]) -> Any:
    payload = base64.b64decode(closure["payload_base64"], validate=True)
    state = SharedPatientState(
        closure["schema_version"],
        payload,
        tuple(closure["distance_vector"]),
        closure["compactness_class"],
    )
    if state.state_hash != closure["state_hash"]:
        raise ProtocolViolation("cold-rehydrated state hash mismatch")
    return state


def state_closure(state: Any) -> dict[str, Any]:
    if type(state) is not SharedPatientState:
        raise ProtocolViolation("state closure requires exact SharedPatientState")
    closure = {
        "protocol": "ucm-redteam-v2-state-closure/1",
        "schema_version": state.schema_version,
        "payload_base64": base64.b64encode(state.payload).decode("ascii"),
        "payload_digest": digest_bytes(state.payload),
        "payload_size_bytes": len(state.payload),
        "distance_vector": list(state.distance_vector),
        "distance_dimension": len(state.distance_vector),
        "compactness_class": state.compactness_class,
        "state_hash": state.state_hash,
        "reachable_patient_specific_bytes": "payload_plus_distance_vector_bound_by_state_hash",
        "external_patient_cache": False,
        "patient_rng_state": False,
    }
    closure["closure_digest"] = digest_json(closure)
    return closure


def prediction_wire(prediction: Any) -> dict[str, Any]:
    if hasattr(prediction, "probabilities"):
        return {"kind": "diagnosis", "probabilities": dict(prediction.probabilities)}
    return {
        "kind": "rollout",
        "signature": list(prediction.signature),
        "expected_utility": prediction.expected_utility,
        "abstained": prediction.abstained,
    }


def make_check_delta(episode: dict[str, Any], *, informative: bool) -> VisibleDelta:
    private = episode["judge_private"]
    value = private["new_check_result"] if informative else 0.0
    prefix = episode["instance_id"]
    events = (
        CandidateVisibleEvent(
            EventKind.TEST_ORDERED,
            1,
            1,
            prefix + "-new-check-ordered",
            {"check_id": "rt_new_check"},
            None,
        ),
        CandidateVisibleEvent(
            EventKind.TEST_PERFORMED,
            1,
            2,
            prefix + "-new-check-performed",
            {"check_id": "rt_new_check"},
            None,
        ),
        CandidateVisibleEvent(
            EventKind.OBSERVATION_AVAILABLE,
            2,
            2,
            prefix + "-new-check-result",
            {"channel_id": "rt_new_check_signal", "value": float(value)},
            2,
        ),
    )
    return VisibleDelta(2, tuple(sorted(events, key=lambda row: (row.available_at, row.occurred_at, row.kind.value, row.event_uid))))


def append_delta_history(history: VisibleHistory, delta: VisibleDelta) -> VisibleHistory:
    known = {event.event_uid for event in history.events}
    if any(event.event_uid in known for event in delta.events):
        raise ProtocolViolation("delta duplicates a visible-history event")
    events = tuple(sorted((*history.events, *delta.events), key=lambda row: (row.available_at, row.occurred_at, row.kind.value, row.event_uid)))
    return VisibleHistory(events, delta.advance_to, history.catalog_digest)


__all__ = [
    "ADAPTER_PROTOCOL",
    "append_delta_history",
    "call_with_access_trace",
    "candidate_source_bindings",
    "catalog_from_wire",
    "fit_implementations",
    "history_from_wire",
    "make_check_delta",
    "plan_from_wire",
    "prediction_wire",
    "rehydrate_state",
    "state_closure",
    "training_records",
]
