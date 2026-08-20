"""Independent semantic red-team probes for Runtime v2.

This is deliberately outside the runtime test package.  It records decisive
architecture-contract counterexamples without modifying runtime/model source.
Run only after concurrent runtime repairs have settled::

    cd research/new_clinical_framework_case_study
    python runtime_v2/evidence/semantic_redteam_probe.py \
      --output runtime_v2/evidence/semantic_redteam_results.json

The neutral model is a structural fixture, not a medical model.  A PASS here
means only that the software honors the frozen NCF-ARCH-1.0.0 semantics tested
by that probe.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "examples" / "neutral_factorial_model.json"
PACKAGE_PARENT = ROOT.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from runtime_v2 import PublicEvent, RuntimeV2, SharedPatientState, architecture_state_hash


def model_dict() -> dict[str, Any]:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def observation(
    event_id: str,
    concept_id: str,
    value: Any,
    *,
    available_at: float,
    sample_lower: float | None = None,
    sample_upper: float | None = None,
    occurred_lower: float | None = None,
    occurred_upper: float | None = None,
    result_at: float | None = None,
    recorded_at: float | None = None,
    source_id: str | None = None,
    unit: str | None = None,
    reliability: float | None = None,
    measurement_condition: dict[str, Any] | None = None,
) -> PublicEvent:
    sample_lower = available_at if sample_lower is None else sample_lower
    sample_upper = sample_lower if sample_upper is None else sample_upper
    occurred_lower = sample_lower if occurred_lower is None else occurred_lower
    occurred_upper = sample_upper if occurred_upper is None else occurred_upper
    result_at = available_at if result_at is None else result_at
    recorded_at = available_at if recorded_at is None else recorded_at
    row: dict[str, Any] = {
        "event_id": event_id,
        "event_type": "ObservationAvailable",
        "available_at": available_at,
        "recorded_at": recorded_at,
        "occurred_time": {"lower": occurred_lower, "upper": occurred_upper},
        "sample_time": {"lower": sample_lower, "upper": sample_upper},
        "result_at": result_at,
        "concept_id": concept_id,
        "value": value,
        "provenance": {"source_result_id": source_id or event_id},
    }
    if unit is not None:
        row["unit"] = unit
    if reliability is not None:
        row["reliability"] = reliability
    if measurement_condition is not None:
        row["measurement_condition"] = copy.deepcopy(measurement_condition)
    return PublicEvent.from_dict(row)


def action_started(
    event_id: str,
    *,
    exposure_id: str,
    occurred_lower: float,
    occurred_upper: float,
    recorded_at: float,
    available_at: float,
    dose: float = 1.0,
    dose_unit: str | None = None,
    source_id: str | None = None,
) -> PublicEvent:
    row: dict[str, Any] = {
        "event_id": event_id,
        "event_type": "ActionStarted",
        "available_at": available_at,
        "recorded_at": recorded_at,
        "occurred_time": {"lower": occurred_lower, "upper": occurred_upper},
        "provenance": {"source_result_id": source_id or event_id},
        "action_id": "ACTION_REDUCE_A",
        "exposure_id": exposure_id,
        "dose": dose,
    }
    if dose_unit is not None:
        row["dose_unit"] = dose_unit
    return PublicEvent.from_dict(row)


def state_signature(state: Any) -> dict[str, Any]:
    wire = state.to_dict()
    return {
        "marginals": {
            row["process_id"]: row["p_active"]
            for row in wire["active_process_posterior"]["process_marginals"]
        },
        "locals": {
            row["process_id"]: {
                "coordinates": row["coordinates"],
                "modes": row["mode_posterior"],
            }
            for row in wire["local_states"]
        },
        "epistemic": wire["epistemic_residual"],
    }


def process_probability(runtime: RuntimeV2, state: Any, process_id: str) -> float:
    return float(runtime.diagnose(state)["process_activation_marginals"][process_id])


def coordinate_mean(state: Any, process_id: str, coordinate_id: str) -> float:
    local = next(
        row for row in state.to_dict()["local_states"] if row["process_id"] == process_id
    )
    coordinate = next(
        row for row in local["coordinates"] if row["coordinate_id"] == coordinate_id
    )
    return float(coordinate["distribution"]["mean"])


def action_instance(state: Any, exposure_id: str) -> dict[str, Any]:
    return next(
        row
        for row in state.to_dict()["action_memory"]["instances"]
        if row["action_instance_id"] == exposure_id
    )


def probe_stale_event_recursive_equivalence() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    event = observation(
        "stale-observation",
        "OBS_A_LOAD",
        0.4,
        available_at=1.0,
    )
    replay = runtime.initialize([event], cut=5.0)
    already_advanced = runtime.initialize([], cut=5.0)
    try:
        recursive = runtime.update(already_advanced, [event], advance_to=5.0)
    except ValueError as exc:
        # Explicitly requiring replay/smoothing is preferable to silently
        # applying a stale event at the current clock.
        return True, {"disposition": "FAIL_CLOSED", "message": str(exc)}
    left = state_signature(replay)
    right = state_signature(recursive)
    return left == right, {
        "disposition": "ACCEPTED_STALE_EVENT",
        "cold_replay_coordinate": coordinate_mean(replay, "PROCESS_A", "a_burden"),
        "recursive_coordinate": coordinate_mean(recursive, "PROCESS_A", "a_burden"),
        "semantic_equal": left == right,
    }


def probe_delayed_sample_is_not_current_measurement() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    old_sample = observation(
        "old-sample",
        "OBS_A_LOAD",
        0.4,
        sample_lower=0.0,
        sample_upper=0.0,
        occurred_lower=0.0,
        occurred_upper=0.0,
        result_at=5.0,
        recorded_at=5.0,
        available_at=5.0,
    )
    current_sample = observation(
        "current-sample",
        "OBS_A_LOAD",
        0.4,
        available_at=5.0,
    )
    old_state = runtime.initialize([old_sample], cut=5.0)
    current_state = runtime.initialize([current_sample], cut=5.0)
    old_value = coordinate_mean(old_state, "PROCESS_A", "a_burden")
    current_value = coordinate_mean(current_state, "PROCESS_A", "a_burden")
    # In the declared model PROCESS_A has non-zero expected natural drift.
    # Treating a t=0 sample as a t=5 measurement makes these exactly equal.
    distinct = not math.isclose(old_value, current_value, rel_tol=0.0, abs_tol=1e-12)
    return distinct, {
        "sample_at_0_available_at_5": old_value,
        "sample_at_5_available_at_5": current_value,
        "distinct": distinct,
    }


def probe_common_source_event_id_invariance() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    first = [
        observation("a", "OBS_A_MARKER", True, available_at=0.0, source_id="joint-source"),
        observation("z", "OBS_B_MARKER", True, available_at=0.0, source_id="joint-source"),
    ]
    second = [
        observation("z", "OBS_A_MARKER", True, available_at=0.0, source_id="joint-source"),
        observation("a", "OBS_B_MARKER", True, available_at=0.0, source_id="joint-source"),
    ]
    try:
        state_a = runtime.initialize(first, cut=0.0)
        state_b = runtime.initialize(second, cut=0.0)
    except ValueError as exc:
        # Explicitly rejecting a source bundle that lacks a registered joint
        # factor is safe; arbitrary first-event-wins is not.
        return True, {"disposition": "FAIL_CLOSED", "message": str(exc)}
    marginal_a = runtime.diagnose(state_a)["process_activation_marginals"]
    marginal_b = runtime.diagnose(state_b)["process_activation_marginals"]
    tolerance = float(runtime.spec["scope"]["tolerance"])
    max_abs_difference = max(
        abs(float(marginal_a[key]) - float(marginal_b[key])) for key in marginal_a
    )
    return max_abs_difference <= tolerance, {
        "event_ids_A_then_B": marginal_a,
        "event_ids_B_then_A": marginal_b,
        "exactly_equal": marginal_a == marginal_b,
        "max_abs_difference": max_abs_difference,
        "declared_scope_tolerance": tolerance,
        "behaviorally_equivalent_within_scope": max_abs_difference <= tolerance,
    }


def probe_same_event_set_input_order_is_canonical() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    rows = [
        observation("event-a", "OBS_A_MARKER", True, available_at=0.0),
        observation("event-b", "OBS_B_MARKER", True, available_at=0.0),
        observation("event-c", "OBS_A_LOAD", 0.7, available_at=0.0),
    ]
    forward = runtime.initialize(rows, cut=0.0)
    reverse = runtime.initialize(list(reversed(rows)), cut=0.0)
    same_bytes = forward.to_bytes() == reverse.to_bytes()
    return same_bytes, {
        "forward_state_hash": forward.state_hash,
        "reverse_state_hash": reverse.state_hash,
        "same_canonical_bytes": same_bytes,
    }


def probe_reliability_changes_inference() -> tuple[bool, dict[str, Any]]:
    high_spec = model_dict()
    low_spec = model_dict()
    for spec, reliability in ((high_spec, 1.0), (low_spec, 0.01)):
        target = next(
            row for row in spec["observations"] if row["concept_id"] == "OBS_A_MARKER"
        )
        target["reliability"] = reliability
    high = RuntimeV2(high_spec)
    low = RuntimeV2(low_spec)
    event = observation("reliability", "OBS_A_MARKER", True, available_at=0.0)
    high_prior = process_probability(high, high.initialize([], cut=0.0), "PROCESS_A")
    low_prior = process_probability(low, low.initialize([], cut=0.0), "PROCESS_A")
    high_post = process_probability(high, high.initialize([event], cut=0.0), "PROCESS_A")
    low_post = process_probability(low, low.initialize([event], cut=0.0), "PROCESS_A")
    high_shift = abs(high_post - high_prior)
    low_shift = abs(low_post - low_prior)
    return low_shift < high_shift - 1e-12, {
        "high_reliability_shift": high_shift,
        "low_reliability_shift": low_shift,
        "high_posterior": high_post,
        "low_posterior": low_post,
    }


def probe_active_support_masks_observation_likelihood() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    start = action_started(
        "support-start",
        exposure_id="support-exposure",
        occurred_lower=0.0,
        occurred_upper=0.0,
        recorded_at=0.0,
        available_at=0.0,
    )
    unmasked = observation(
        "unmasked-marker",
        "OBS_A_MARKER",
        True,
        available_at=1.0,
    )
    masked = observation(
        "masked-marker",
        "OBS_A_MARKER",
        True,
        available_at=1.0,
        measurement_condition={
            "active_support_exposure_ids": ["support-exposure"],
            "support_masking": 0.0,
        },
    )
    baseline = runtime.initialize([start], cut=1.0)
    unmasked_state = runtime.initialize([start, unmasked], cut=1.0)
    masked_state = runtime.initialize([start, masked], cut=1.0)
    prior = process_probability(runtime, baseline, "PROCESS_A")
    unmasked_post = process_probability(runtime, unmasked_state, "PROCESS_A")
    masked_post = process_probability(runtime, masked_state, "PROCESS_A")
    unmasked_shift = abs(unmasked_post - prior)
    masked_shift = abs(masked_post - prior)
    return masked_shift < unmasked_shift - 1e-12, {
        "baseline_p_active": prior,
        "unmasked_p_active": unmasked_post,
        "masked_p_active": masked_post,
        "unmasked_shift": unmasked_shift,
        "masked_shift": masked_shift,
    }


def probe_mapped_misfit_has_provenance() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    event = observation(
        "impossible-mapped",
        "OBS_A_LOAD",
        100.0,
        available_at=0.0,
        source_id="impossible-mapped-source",
    )
    state = runtime.initialize([event], cut=0.0)
    residual = state.to_dict()["epistemic_residual"]
    ids = {
        row["result_id"] for row in residual.get("unexplained_observations", [])
    }
    listed = "impossible-mapped-source" in ids
    return bool(residual["model_misfit"] > 0.0 and listed), {
        "model_misfit": residual["model_misfit"],
        "unexplained_result_ids": sorted(ids),
        "listed": listed,
    }


def probe_observation_fingerprint_includes_unit() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    first = observation(
        "unit-first",
        "OBS_A_LOAD",
        0.4,
        available_at=0.0,
        source_id="corrected-result",
        unit="unit-one",
    )
    correction = observation(
        "unit-correction",
        "OBS_A_LOAD",
        0.4,
        available_at=0.0,
        source_id="corrected-result",
        unit="unit-two",
    )
    state = runtime.initialize([first], cut=0.0)
    try:
        changed = runtime.update(state, [correction], advance_to=0.0)
    except ValueError as exc:
        return True, {"disposition": "SEMANTIC_COLLISION_REJECTED", "message": str(exc)}
    silently_identical = changed.to_bytes() == state.to_bytes()
    return not silently_identical, {
        "disposition": "ACCEPTED",
        "silently_deduplicated": silently_identical,
    }


def probe_delayed_action_exposure_uses_occurrence() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    event = action_started(
        "delayed-start",
        exposure_id="delayed-exposure",
        occurred_lower=1.0,
        occurred_upper=1.0,
        recorded_at=5.0,
        available_at=5.0,
        dose=1.0,
    )
    try:
        state = runtime.initialize([event], cut=10.0)
    except ValueError as exc:
        # A runtime without retrospective smoothing may reject the event; it
        # must not silently backfill exposure while omitting factual dynamics.
        return True, {"disposition": "FAIL_CLOSED", "message": str(exc)}
    exposure = float(action_instance(state, "delayed-exposure")["cumulative_exposure"]["value"])
    return math.isclose(exposure, 9.0, abs_tol=1e-12), {
        "occurred_at": 1.0,
        "available_at": 5.0,
        "cut": 10.0,
        "cumulative_exposure": exposure,
        "expected": 9.0,
    }


def probe_delayed_action_backfills_factual_dynamics() -> tuple[bool, dict[str, Any]]:
    """Late public knowledge of an earlier action must not update exposure alone."""

    spec = model_dict()
    process = next(row for row in spec["processes"] if row["process_id"] == "PROCESS_A")
    process["activation_transition"] = {
        "enter_hazard_per_step": 0.8,
        "withdraw_hazard_per_step": 0.0,
        "entry_initialization": {"policy": "RESET_TO_PRIOR"},
        "exit_policy": {"policy": "SURVIVOR_CARRY_REENTRY_RESET"},
        "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
        "source_id": "semantic-redteam-delayed-action-transition",
        "version": "1",
    }
    action = next(row for row in spec["actions"] if row["action_id"] == "ACTION_REDUCE_A")
    action["activation_effects"] = [
        {
            "process_id": "PROCESS_A",
            "enter_log_hazard_shift_per_unit": -4.0,
            "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
            "source_id": "semantic-redteam-delayed-action-effect",
            "version": "1",
        }
    ]
    runtime = RuntimeV2(spec)
    delayed = action_started(
        "delayed-action-transport",
        exposure_id="factual-backfill-exposure",
        occurred_lower=0.0,
        occurred_upper=0.0,
        recorded_at=2.0,
        available_at=2.0,
        source_id="same-action-source",
    )
    timely = action_started(
        "timely-action-transport",
        exposure_id="factual-backfill-exposure",
        occurred_lower=0.0,
        occurred_upper=0.0,
        recorded_at=0.0,
        available_at=0.0,
        source_id="same-action-source",
    )
    try:
        delayed_state = runtime.initialize([delayed], cut=2.0)
    except ValueError as exc:
        return True, {"disposition": "FAIL_CLOSED", "message": str(exc)}
    timely_state = runtime.update(runtime.initialize([timely], cut=0.0), [], advance_to=2.0)
    delayed_coordinate = coordinate_mean(delayed_state, "PROCESS_A", "a_burden")
    timely_coordinate = coordinate_mean(timely_state, "PROCESS_A", "a_burden")
    delayed_p_active = process_probability(runtime, delayed_state, "PROCESS_A")
    timely_p_active = process_probability(runtime, timely_state, "PROCESS_A")
    delayed_modes = next(
        row["mode_posterior"]
        for row in delayed_state.to_dict()["local_states"]
        if row["process_id"] == "PROCESS_A"
    )
    timely_modes = next(
        row["mode_posterior"]
        for row in timely_state.to_dict()["local_states"]
        if row["process_id"] == "PROCESS_A"
    )
    delayed_exposure = action_instance(delayed_state, "factual-backfill-exposure")[
        "cumulative_exposure"
    ]["value"]
    timely_exposure = action_instance(timely_state, "factual-backfill-exposure")[
        "cumulative_exposure"
    ]["value"]
    tolerance = float(spec["scope"]["tolerance"])
    equivalent = (
        math.isclose(delayed_coordinate, timely_coordinate, rel_tol=0.0, abs_tol=tolerance)
        and math.isclose(delayed_p_active, timely_p_active, rel_tol=0.0, abs_tol=tolerance)
        and delayed_modes == timely_modes
        and math.isclose(delayed_exposure, timely_exposure, rel_tol=0.0, abs_tol=tolerance)
    )
    return equivalent, {
        "disposition": "FACTUAL_BACKFILL_EQUIVALENT" if equivalent else "SILENT_PARTIAL_BACKFILL",
        "delayed": {
            "a_burden": delayed_coordinate,
            "p_active": delayed_p_active,
            "mode_posterior": delayed_modes,
            "cumulative_exposure": delayed_exposure,
        },
        "timely_then_advanced": {
            "a_burden": timely_coordinate,
            "p_active": timely_p_active,
            "mode_posterior": timely_modes,
            "cumulative_exposure": timely_exposure,
        },
    }


def probe_action_source_event_id_provenance() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    event = action_started(
        "transport-event-id",
        exposure_id="source-provenance-exposure",
        occurred_lower=0.0,
        occurred_upper=0.0,
        recorded_at=0.0,
        available_at=0.0,
        source_id="upstream-source-result-id",
    )
    state = runtime.initialize([event], cut=0.0)
    wire = state.to_dict()
    instance = action_instance(state, "source-provenance-exposure")
    source_event_ids = instance["source_event_ids"]
    processed_event_ids = wire["event_lineage"]["processed_event_ids"]
    event_referenced = "transport-event-id" in source_event_ids
    return event_referenced, {
        "processed_event_ids": processed_event_ids,
        "action_source_event_ids": source_event_ids,
        "upstream_source_result_id": "upstream-source-result-id",
        "transport_event_referenced": event_referenced,
    }


def probe_ambiguous_partial_order_no_false_response() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    start = action_started(
        "ambiguous-action",
        exposure_id="ambiguous-exposure",
        occurred_lower=0.0,
        occurred_upper=2.0,
        recorded_at=3.0,
        available_at=3.0,
    )
    measured = observation(
        "ambiguous-observation",
        "OBS_A_LOAD",
        0.7,
        sample_lower=1.0,
        sample_upper=1.0,
        occurred_lower=1.0,
        occurred_upper=1.0,
        result_at=2.0,
        recorded_at=3.0,
        available_at=3.0,
    )
    try:
        state = runtime.initialize([start, measured], cut=3.0)
    except ValueError as exc:
        return True, {"disposition": "FAIL_CLOSED", "message": str(exc)}
    windows = state.to_dict()["history_summary"].get("action_response_windows", [])
    # With overlapping occurrence intervals there is no established
    # before/after relation.  A response window must be omitted or explicitly
    # marked ambiguous; a definitive attribution fabricates ordering.
    definitive = [row for row in windows if not row.get("temporal_order_ambiguous", False)]
    return not definitive, {
        "response_windows": windows,
        "definitive_response_count": len(definitive),
    }


def probe_active_unidentifiable_action_marks_forecast() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    start = action_started(
        "unidentified-active",
        exposure_id="unidentified-exposure",
        occurred_lower=0.0,
        occurred_upper=0.0,
        recorded_at=0.0,
        available_at=0.0,
    )
    state = runtime.initialize([start], cut=0.0)
    forecast = runtime.forecast(state, horizon=1.0)
    status = forecast["identifiability"]["status"]
    return status == "UNIDENTIFIABLE", {
        "status": status,
        "reasons": forecast["identifiability"].get("reasons"),
    }


def _final_activation_probability(rollout: dict[str, Any], process_id: str) -> float:
    return sum(
        float(row["probability"])
        for row in rollout["final_joint_hypotheses"]
        if process_id in row["active_processes"]
    )


def probe_process_activation_is_dynamic_and_action_controllable() -> tuple[bool, dict[str, Any]]:
    spec = model_dict()
    process = next(row for row in spec["processes"] if row["process_id"] == "PROCESS_A")
    process["activation_transition"] = {
        "enter_hazard_per_step": 0.8,
        "withdraw_hazard_per_step": 0.0,
        "entry_initialization": {"policy": "RESET_TO_PRIOR"},
        "exit_policy": {"policy": "SURVIVOR_CARRY_REENTRY_RESET"},
        "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
        "source_id": "semantic-redteam-activation-transition",
        "version": "1",
    }
    action = next(row for row in spec["actions"] if row["action_id"] == "ACTION_REDUCE_A")
    action["activation_effects"] = [
        {
            "process_id": "PROCESS_A",
            "enter_log_hazard_shift_per_unit": -4.0,
            "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
            "source_id": "semantic-redteam-activation-effect",
            "version": "1",
        }
    ]
    runtime = RuntimeV2(spec)
    state = runtime.initialize([], cut=0.0)
    initial = process_probability(runtime, state, "PROCESS_A")
    natural = runtime.rollout(
        state,
        {"policy_id": "NATURAL", "start_actions": []},
        horizon=1.0,
    )
    controlled = runtime.rollout(
        state,
        {
            "policy_id": "CONTROLLED",
            "start_actions": [{"action_id": "ACTION_REDUCE_A", "dose": 1.0}],
        },
        horizon=1.0,
    )
    natural_p = _final_activation_probability(natural, "PROCESS_A")
    controlled_p = _final_activation_probability(controlled, "PROCESS_A")
    passed = natural_p > initial + 1e-6 and controlled_p < natural_p - 1e-6
    return passed, {
        "initial_p_active": initial,
        "natural_p_active_h1": natural_p,
        "controlled_p_active_h1": controlled_p,
        "activation_transition_trace": natural.get("process_activation_trace"),
        "controlled_transition_trace": controlled.get("process_activation_trace"),
    }


def probe_ood_is_operative_for_planning() -> tuple[bool, dict[str, Any]]:
    spec = model_dict()
    action = next(row for row in spec["actions"] if row["action_id"] == "ACTION_REDUCE_A")
    action["causal_status"] = "IDENTIFIED_WITHIN_SCOPE"
    action["identified_set"] = {
        "lower": 0.0,
        "upper": 3.0,
        "unit": "declared_coordinate_burden",
    }
    runtime = RuntimeV2(spec)
    events = [observation("load", "OBS_A_LOAD", 0.9, available_at=0.0)]
    events.extend(
        observation(
            f"unknown-{index}",
            f"UNKNOWN_CONCEPT_{index}",
            "novel",
            available_at=0.0,
        )
        for index in range(12)
    )
    state = runtime.initialize(events, cut=0.0)
    policies = [
        {"policy_id": "NO_NEW_ACTION", "start_actions": []},
        {"policy_id": "ACT", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]},
    ]
    plan = runtime.plan(state, policies, horizon=1.0)
    residual = state.to_dict()["epistemic_residual"]
    # A unique action may be returned only if compatible unknown worlds are
    # bounded sufficiently for robust dominance.  This fixture supplies no
    # such unknown-world action model.
    abstained = plan.get("selected_policy_id") is None or plan.get("status") in {
        "PARTIAL_ANSWER_ONLY",
        "UNIDENTIFIABLE",
        "OUT_OF_SCOPE",
    }
    return abstained, {
        "selected_policy_id": plan.get("selected_policy_id"),
        "plan_status": plan.get("status"),
        "unmodeled_process": residual["unmodeled_process"],
        "mapping_gap": residual["mapping_gap"],
        "abstention_status": residual["abstention_status"],
    }


def probe_partial_identification_not_point_optimized() -> tuple[bool, dict[str, Any]]:
    spec = model_dict()
    action = next(row for row in spec["actions"] if row["action_id"] == "ACTION_REDUCE_A")
    action["causal_status"] = "PARTIALLY_IDENTIFIED"
    action["identified_set"] = {
        "lower": 0.0,
        "upper": 3.0,
        "unit": "declared_coordinate_burden",
    }
    runtime = RuntimeV2(spec)
    state = runtime.initialize(
        [observation("partial-load", "OBS_A_LOAD", 0.9, available_at=0.0)],
        cut=0.0,
    )
    policies = [
        {"policy_id": "NO_NEW_ACTION", "start_actions": []},
        {"policy_id": "PARTIAL_ACT", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]},
    ]
    plan = runtime.plan(state, policies, horizon=1.0)
    selected = plan.get("selected_policy_id")
    # The two complete-outcome identified sets overlap, so the point-model
    # rollout must not silently authorize the partially identified action.
    pass_condition = selected != "PARTIAL_ACT" or bool(plan.get("robust_dominance_proven"))
    return pass_condition, {
        "selected_policy_id": selected,
        "robust_dominance_proven": plan.get("robust_dominance_proven"),
        "policy_results": plan.get("policy_results"),
    }


def probe_partial_effect_bounds_are_not_mislabeled_as_outcome_bounds() -> tuple[bool, dict[str, Any]]:
    spec = model_dict()
    action = next(row for row in spec["actions"] if row["action_id"] == "ACTION_REDUCE_A")
    action["causal_status"] = "PARTIALLY_IDENTIFIED"
    action["identified_set"] = {
        "lower": -0.3,
        "upper": -0.2,
        "unit": "declared_coordinate_effect",
    }
    try:
        RuntimeV2(spec)
    except ValueError as exc:
        message = str(exc)
        rejected_as_effect = "complete post-policy" in message or "unit must equal" in message
        return rejected_as_effect, {
            "disposition": "REJECTED_EFFECT_BOUNDS_AT_MODEL_LOAD",
            "message": message,
        }
    return False, {
        "disposition": "ACCEPTED_RAW_EFFECT_BOUNDS_AS_OUTCOME_SET",
        "identified_set": action["identified_set"],
    }


def probe_natural_forecast_identified_set_contains_declared_model_point() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    events = [
        observation("set-a-marker", "OBS_A_MARKER", True, available_at=0.0),
        observation("set-b-marker", "OBS_B_MARKER", True, available_at=0.0),
        observation("set-a-load", "OBS_A_LOAD", 1.0, available_at=0.0),
        observation("set-b-load", "OBS_B_LOAD", 1.0, available_at=0.0),
    ]
    state = runtime.initialize(events, cut=0.0)
    forecast = runtime.forecast(state, horizon=1.0)
    interval = forecast.get("decision_value_interval")
    contained = interval is None or (
        float(interval["lower"])
        <= float(forecast["total_objective"])
        <= float(interval["upper"])
    )
    return contained, {
        "declared_model_total_objective": forecast["total_objective"],
        "decision_value_interval": interval,
        "declared_model_point_contained": contained,
    }


def probe_invalid_mode_prior_rejected_early() -> tuple[bool, dict[str, Any]]:
    spec = model_dict()
    modes = spec["processes"][0]["modes"]
    modes[0]["prior"] = -0.1
    modes[1]["prior"] = 1.0
    modes[2]["prior"] = 0.1
    try:
        RuntimeV2(spec)
    except ValueError as exc:
        return True, {"disposition": "REJECTED_AT_MODEL_LOAD", "message": str(exc)}
    return False, {"disposition": "ACCEPTED_INVALID_NEGATIVE_MODE_PRIOR"}


def probe_nan_scope_horizon_rejected_early() -> tuple[bool, dict[str, Any]]:
    spec = model_dict()
    spec["scope"]["horizon"]["value"] = math.nan
    try:
        RuntimeV2(spec)
    except ValueError as exc:
        return True, {"disposition": "REJECTED_AT_MODEL_LOAD", "message": str(exc)}
    return False, {"disposition": "ACCEPTED_NAN_SCOPE_HORIZON"}


def probe_frozen_nested_state_schema_is_enforced() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    state = runtime.initialize([], cut=0.0)
    wire = state.to_dict()
    wire["as_of"]["undeclared_nested_field"] = "must-be-rejected"
    wire["integrity"]["state_hash"] = architecture_state_hash(wire)
    try:
        tampered = SharedPatientState.from_dict(wire)
        runtime.diagnose(tampered)
    except ValueError as exc:
        return True, {"disposition": "REJECTED_BY_RUNTIME", "message": str(exc)}
    return False, {
        "disposition": "ACCEPTED_SCHEMA_INVALID_REHASHED_WIRE",
        "invalid_path": "as_of.undeclared_nested_field",
    }


def probe_clock_time_matches_frozen_datetime_format() -> tuple[bool, dict[str, Any]]:
    """The frozen schema permits null or an RFC3339 date-time, not model-step text."""

    runtime = RuntimeV2(model_dict())
    value = runtime.initialize([], cut=0.0).to_dict()["as_of"]["clock_time"]
    if value is None:
        return True, {"clock_time": None, "disposition": "NULL_ALLOWED_BY_FROZEN_SCHEMA"}
    if not isinstance(value, str):
        return False, {"clock_time": value, "disposition": "NON_STRING_NON_NULL"}
    rfc3339 = re.fullmatch(
        r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})",
        value,
    )
    if rfc3339 is None:
        return False, {"clock_time": value, "disposition": "NOT_RFC3339_DATE_TIME"}
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError as exc:
        return False, {
            "clock_time": value,
            "disposition": "INVALID_RFC3339_DATE_TIME",
            "message": str(exc),
        }
    return True, {"clock_time": value, "disposition": "VALID_RFC3339_DATE_TIME"}


def probe_record_only_event_is_losslessly_nonrankable() -> tuple[bool, dict[str, Any]]:
    runtime = RuntimeV2(model_dict())
    event = PublicEvent.from_dict(
        {
            "event_id": "record-only-event",
            "event_type": "RecordOnly",
            "available_at": 0.0,
            "recorded_at": 0.0,
            "occurred_time": {"lower": 0.0, "upper": 0.0},
            "provenance": {"source_result_id": "record-only-source"},
            "concept_id": "UNRANKABLE_FREE_TEXT",
        }
    )
    try:
        state = runtime.initialize([event], cut=0.0)
        diagnosis = runtime.diagnose(state)
    except Exception as exc:
        return False, {
            "disposition": "PUBLIC_RECORD_ONLY_PATH_CRASHED",
            "exception_type": type(exc).__name__,
            "message": str(exc),
        }
    wire = state.to_dict()
    retained = "record-only-event" in wire["event_lineage"]["processed_event_ids"]
    rankable_messages = [
        row
        for row in wire["factor_graph_state"]["factor_messages"]
        if not str(row["factor_id"]).startswith("DISPOSITION:")
    ]
    return retained and not rankable_messages, {
        "retained_in_event_lineage": retained,
        "factor_messages": wire["factor_graph_state"]["factor_messages"],
        "diagnostic_marginals": diagnosis["process_activation_marginals"],
    }


PROBES: list[tuple[str, str, Callable[[], tuple[bool, dict[str, Any]]]]] = [
    ("stale_event_recursive_equivalence", "G03/G05", probe_stale_event_recursive_equivalence),
    ("delayed_sample_is_not_current_measurement", "G01/G03/G13", probe_delayed_sample_is_not_current_measurement),
    ("common_source_event_id_invariance", "G03/G05/G06", probe_common_source_event_id_invariance),
    ("same_event_set_input_order_is_canonical", "G03/G05/G16", probe_same_event_set_input_order_is_canonical),
    ("reliability_changes_inference", "G06", probe_reliability_changes_inference),
    ("active_support_masks_observation_likelihood", "G06/G09", probe_active_support_masks_observation_likelihood),
    ("mapped_misfit_has_provenance", "G12", probe_mapped_misfit_has_provenance),
    ("observation_fingerprint_includes_unit", "G03/G06/G16", probe_observation_fingerprint_includes_unit),
    ("delayed_action_exposure_uses_occurrence", "G01/G02/G09/G11", probe_delayed_action_exposure_uses_occurrence),
    ("delayed_action_backfills_factual_dynamics", "G01/G02/G07/G09/G11/G13", probe_delayed_action_backfills_factual_dynamics),
    ("action_source_event_id_provenance", "G02/G03/G16", probe_action_source_event_id_provenance),
    ("ambiguous_partial_order_no_false_response", "G01/G02/G13", probe_ambiguous_partial_order_no_false_response),
    ("active_unidentifiable_action_marks_forecast", "G09/G11/G17", probe_active_unidentifiable_action_marks_forecast),
    ("process_activation_is_dynamic_and_action_controllable", "G07/G11/G13", probe_process_activation_is_dynamic_and_action_controllable),
    ("ood_is_operative_for_planning", "G12/G17", probe_ood_is_operative_for_planning),
    ("partial_identification_not_point_optimized", "G17", probe_partial_identification_not_point_optimized),
    ("partial_effect_bounds_are_not_mislabeled_as_outcome_bounds", "G17", probe_partial_effect_bounds_are_not_mislabeled_as_outcome_bounds),
    ("natural_forecast_identified_set_contains_declared_model_point", "G17", probe_natural_forecast_identified_set_contains_declared_model_point),
    ("invalid_mode_prior_rejected_early", "G08/G16", probe_invalid_mode_prior_rejected_early),
    ("nan_scope_horizon_rejected_early", "G16/G17", probe_nan_scope_horizon_rejected_early),
    ("frozen_nested_state_schema_is_enforced", "G16", probe_frozen_nested_state_schema_is_enforced),
    ("clock_time_matches_frozen_datetime_format", "G16", probe_clock_time_matches_frozen_datetime_format),
    ("record_only_event_is_losslessly_nonrankable", "G01/G03/G06", probe_record_only_event_is_losslessly_nonrankable),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    rows: list[dict[str, Any]] = []
    for probe_id, gates, probe in PROBES:
        try:
            passed, details = probe()
            rows.append(
                {
                    "probe_id": probe_id,
                    "gates": gates,
                    "status": "PASS" if passed else "FAIL",
                    "details": details,
                }
            )
        except Exception as exc:  # red-team harness errors must be explicit
            rows.append(
                {
                    "probe_id": probe_id,
                    "gates": gates,
                    "status": "ERROR",
                    "details": {
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                }
            )
    result = {
        "schema_version": "ncf.runtime.semantic-redteam.v1",
        "architecture_version": "NCF-ARCH-1.0.0",
        "model_fixture": str(MODEL_PATH),
        "summary": {
            status: sum(row["status"] == status for row in rows)
            for status in ("PASS", "FAIL", "ERROR")
        },
        "overall_status": "PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
        "probes": rows,
    }
    raw = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(raw, encoding="utf-8")
    print(raw, end="")
    return 0 if result["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

