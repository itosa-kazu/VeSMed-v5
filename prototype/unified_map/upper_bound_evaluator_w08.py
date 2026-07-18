"""Typed PRE-FREEZE evaluator for the privileged W08 true-state probe.

W08 is the asynchronous-availability vertical slice.  The evaluator binds the
committed runnable artifact to a live byte replay, records stable state-hash
preimages, and turns the exact diagnosis/rollout heads into typed sanity cells.
It is deliberately privileged, upper-bound-only evidence: it has no candidate
or benchmark-freeze authority and contributes zero experiment-ledger credit.

The W08 public-history reference oracle and the privileged true-state judge do
not answer the same conditional query.  Consequently this module records the
full judge oracle but explicitly declines a source-distinct reference-oracle
claim.  Conditional-mean trajectory and expected-utility metrics are derived
only from the recorded head and judge bytes and are recomputed by the verifier.
"""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

import numpy as np

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .oracle_certification import oracle_output_wire
from .schema import DiagnosisQuery, EventKind, RolloutQuery
from .true_state_probe_w08 import (
    W08TrueStateUpperBoundProbe,
    _late_response_delta,
    _vertical_policies,
    run_w08_availability_slice,
)
from .upper_bound_evaluator import (
    PROTOCOL,
    STATUS_CHAIN,
    _attach_bundle_root,
    _cell_root,
    _closed,
    _degraded_diagnosis,
    _degraded_regret,
    _degraded_trajectory,
    _diagnostic_metric_wire,
    _digest,
    _finite,
    _head_wire,
    _metric_equal,
    _point_rollout,
    _regret_metric_wire,
    _state_binding,
    _trajectory_metric_wire,
    _verify_head,
    _verify_oracle_query_binding,
    _verify_state_binding,
    compute_upper_bound_bundle_root,
)
from .worlds.w08 import World08


DEFAULT_W08_ARTIFACT = Path(
    "results/unified_map/pre_freeze/"
    "20260717-w08-asynchronous-availability-probe/vertical-slice.json"
)
_REFERENCE_STATUS = "UNAVAILABLE_FOR_MATCHED_PRIVILEGED_TRUE_STATE_QUERY"
_UTILITY_PROTOCOL = "ucm-w08-upper-bound-utility/1"
_FIXTURE = {
    "class_index": 0,
    "x": [0.4, -0.2],
    "exposure": 0,
    "remaining": 0,
    "as_of_available_at": -1,
    "pending_swap_generator_seed": 806,
}


def _utility_digest(world: World08) -> str:
    return digest_json(["W08", world.catalog.digest, 4, "discounted-quadratic-cost"])


def _judge_wire(value: Any) -> dict[str, Any]:
    return oracle_output_wire(value, include_numerical_diagnostics=False)


def _verify_exact_judge_oracle(
    recorded: dict[str, Any],
    *,
    representation: dict[str, Any],
    policy: Any,
    world: World08,
    label: str,
) -> None:
    expected = _judge_wire(
        world.judge_true_state_counterfactual(
            {
                "x": representation["x"],
                "exposure": representation["exposure"],
                "remaining": representation["remaining"],
            },
            {"c": representation["class_index"]},
            policy,
            4,
        )
    )
    if canonical_json_bytes(recorded) != canonical_json_bytes(expected):
        raise ProtocolViolation(f"{label} is not the exact live judge oracle wire")


def _w08_oracle_mean_matrix(
    oracle: dict[str, Any], requested: tuple[str, ...]
) -> list[list[float]]:
    distribution = oracle.get("observation_distribution")
    if type(distribution) is not dict or set(distribution) != {
        "obs_0",
        "obs_1",
    }:
        raise ProtocolViolation("W08 judge observation distribution is malformed")
    columns: list[list[float]] = []
    horizon: int | None = None
    for channel in requested:
        if channel not in {"obs_0", "obs_1"}:
            raise ProtocolViolation("W08 requested an unknown observation channel")
        rows = distribution[channel]
        if type(rows) is not list or not rows:
            raise ProtocolViolation("W08 judge observation rows are absent")
        if horizon is None:
            horizon = len(rows)
        elif horizon != len(rows):
            raise ProtocolViolation("W08 judge observation horizons disagree")
        values: list[float] = []
        for offset, row in enumerate(rows, start=1):
            if type(row) is not dict or set(row) != {
                "offset",
                "mean",
                "variance",
            }:
                raise ProtocolViolation("W08 judge observation row is not closed")
            if row["offset"] != offset:
                raise ProtocolViolation("W08 judge observation offsets are not dense")
            if _finite(row["variance"], "W08 judge variance") < 0.0:
                raise ProtocolViolation("W08 judge observation variance is negative")
            values.append(_finite(row["mean"], "W08 judge mean"))
        columns.append(values)
    if horizon is None:
        raise ProtocolViolation("W08 judge horizon is absent")
    return np.asarray(columns, dtype=float).T.tolist()


def _utility_metric_wire(predicted: float, oracle: float) -> dict[str, float | str]:
    predicted_value = _finite(predicted, "W08 predicted utility")
    oracle_value = _finite(oracle, "W08 judge utility")
    return {
        "protocol": "ucm-upper-bound-expected-utility-error/1",
        "predicted": predicted_value,
        "oracle": oracle_value,
        "absolute_error": abs(predicted_value - oracle_value),
    }


def _degraded_utility_metric(oracle: float) -> dict[str, float | str]:
    return _utility_metric_wire(_finite(oracle, "W08 judge utility") + 0.25, oracle)


def _c0_transition(state: list[float], *, active: int) -> list[float]:
    """Independent C0 transition used only by the evaluator verifier."""

    if (
        type(state) is not list
        or len(state) != 2
        or type(active) is not int
        or active not in {-1, 0, 1}
    ):
        raise ProtocolViolation("W08 C0 transition input is malformed")
    x0 = _finite(state[0], "W08 C0 x0")
    x1 = _finite(state[1], "W08 C0 x1")
    return [
        0.98 * x0 + 0.01 * x1 - 0.07 * active,
        -0.005 * x0 + 0.97 * x1 + 0.025 * active,
    ]


def _exact_diagnosis_query(world: World08) -> DiagnosisQuery:
    return DiagnosisQuery(world.catalog.diagnostic_labels)


def _exact_rollout_query(world: World08, policy: Any) -> RolloutQuery:
    return RolloutQuery(
        4,
        policy,
        ("obs_0", "obs_1"),
        _utility_digest(world),
    )


def _check_head_metadata(head: dict[str, Any], operation: str) -> None:
    result = head["execution"]["response"]["result"]
    metadata = result.get("metadata")
    expected: dict[str, Any] = {
        "baseline_id": "B01",
        "privileged": True,
        "eligibility": "upper_bound_only",
    }
    if operation == "rollout":
        expected["projection"] = "conditional-mean-observation"
    if metadata != expected:
        raise ProtocolViolation("W08 candidate head metadata mismatch")


def _assert_exact_query(
    head: dict[str, Any], expected: DiagnosisQuery | RolloutQuery, label: str
) -> None:
    if head["query"] != expected.to_wire():
        raise ProtocolViolation(f"{label} did not retain the exact query wire")


def _load_canonical_artifact(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(f"{label} is unavailable: {path}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} is not JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"{label} is not canonical JSON")
    return raw, value


def run_w08_upper_bound_sanity(
    *, source_artifact: Path | str = DEFAULT_W08_ARTIFACT
) -> dict[str, Any]:
    """Execute, collect, and verify the privileged W08 evaluator slice."""

    source_path = Path(source_artifact)
    source_bytes, source_wire = _load_canonical_artifact(
        source_path, "W08 source artifact"
    )
    replay = run_w08_availability_slice()
    replay_bytes = canonical_json_bytes(replay)
    if replay_bytes != source_bytes:
        raise ProtocolViolation("W08 committed vertical slice does not byte-replay")

    world = World08()
    probe = W08TrueStateUpperBoundProbe(world)
    diagnosis_query = _exact_diagnosis_query(world)
    policies = _vertical_policies(world)
    aliases = ("no_new_action", "single_A1", "single_A2")
    state = probe.initialize_true_state(
        class_index=_FIXTURE["class_index"],
        x=deepcopy(_FIXTURE["x"]),
        exposure=_FIXTURE["exposure"],
        remaining=_FIXTURE["remaining"],
        as_of_available_at=_FIXTURE["as_of_available_at"],
    )
    diagnosis = probe.diagnose(state, diagnosis_query, query_seed=1)
    diagnosis_head = _head_wire(diagnosis, diagnosis_query)

    rollout_heads: dict[str, dict[str, Any]] = {}
    judge_oracles: dict[str, dict[str, Any]] = {}
    trajectory_metrics: dict[str, dict[str, Any]] = {}
    degraded_trajectory_metrics: dict[str, dict[str, Any]] = {}
    utility_metrics: dict[str, dict[str, Any]] = {}
    predicted_utilities: list[float] = []
    oracle_utilities: list[float] = []
    for alias, policy in zip(aliases, policies, strict=True):
        query = _exact_rollout_query(world, policy)
        execution = probe.rollout(state, query, query_seed=2)
        head = _head_wire(execution, query)
        oracle = _judge_wire(
            world.judge_true_state_counterfactual(
                {
                    "x": deepcopy(_FIXTURE["x"]),
                    "exposure": _FIXTURE["exposure"],
                    "remaining": _FIXTURE["remaining"],
                },
                {"c": _FIXTURE["class_index"]},
                policy,
                4,
            )
        )
        requested = tuple(query.requested_observables)
        predicted, predicted_utility = _point_rollout(head, requested)
        expected = _w08_oracle_mean_matrix(oracle, requested)
        oracle_utility = _finite(
            oracle["expected_utility"], "W08 judge expected utility"
        )
        rollout_heads[alias] = head
        judge_oracles[alias] = oracle
        trajectory_metrics[alias] = _trajectory_metric_wire(predicted, expected)
        degraded_trajectory_metrics[alias] = _degraded_trajectory(predicted, expected)
        utility_metrics[alias] = _utility_metric_wire(predicted_utility, oracle_utility)
        predicted_utilities.append(predicted_utility)
        oracle_utilities.append(oracle_utility)

    initial_binding = _state_binding(state)
    initial_hash = state.record.state_hash
    diagnosis_probabilities = [
        float(diagnosis_head["execution"]["response"]["result"]["probabilities"][label])
        for label in world.catalog.diagnostic_labels
    ]
    diagnosis_target = [1.0, 0.0]

    delta, next_x = _late_response_delta()
    updated = probe.update_private(
        state,
        delta,
        hidden_state_at_cut={"x": next_x, "exposure": 1, "remaining": 3},
        invariant_parameters={"c": 0},
        inference_seed=3,
    )
    updated_binding = _state_binding(updated)
    updated_diagnosis = probe.diagnose(updated, diagnosis_query, query_seed=4)
    updated_diagnosis_head = _head_wire(updated_diagnosis, diagnosis_query)
    updated_query = _exact_rollout_query(world, policies[0])
    updated_rollout = probe.rollout(
        updated,
        updated_query,
        query_seed=5,
    )
    updated_rollout_head = _head_wire(updated_rollout, updated_query)
    updated_representation = updated_binding["payload"]["representation"]
    updated_judge = _judge_wire(
        world.judge_true_state_counterfactual(
            {
                "x": updated_representation["x"],
                "exposure": updated_representation["exposure"],
                "remaining": updated_representation["remaining"],
            },
            {"c": updated_representation["class_index"]},
            policies[0],
            4,
        )
    )
    updated_predicted, updated_predicted_utility = _point_rollout(
        updated_rollout_head, ("obs_0", "obs_1")
    )
    updated_expected = _w08_oracle_mean_matrix(updated_judge, ("obs_0", "obs_1"))
    updated_oracle_utility = _finite(
        updated_judge["expected_utility"], "W08 updated judge utility"
    )
    updated_probabilities = [
        float(
            updated_diagnosis_head["execution"]["response"]["result"]["probabilities"][
                label
            ]
        )
        for label in world.catalog.diagnostic_labels
    ]

    pending_left, pending_right = world.probe_fixtures(
        _FIXTURE["pending_swap_generator_seed"]
    )["identical_prefix_future_swap"]
    pending_left_state = probe.initialize_private(pending_left)
    pending_right_state = probe.initialize_private(pending_right)
    pending_left_raw = pending_left.hidden_state_at_cut["pending_results"]
    pending_right_raw = pending_right.hidden_state_at_cut["pending_results"]
    pending_left_binding = _state_binding(pending_left_state)
    pending_right_binding = _state_binding(pending_right_state)

    cells = [
        {
            "cell_id": "W08.initial.diagnosis",
            "world_slot": "W08",
            "cut_alias": "preavailability",
            "task": "diagnosis",
            "state_hash": initial_hash,
            "candidate_head": diagnosis_head,
            "oracle_target": {
                "label_order": list(world.catalog.diagnostic_labels),
                "probabilities": diagnosis_target,
            },
            "metric": _diagnostic_metric_wire(
                diagnosis_probabilities, diagnosis_target
            ),
            "degraded_control_metric": _degraded_diagnosis(
                diagnosis_probabilities, diagnosis_target
            ),
        },
        {
            "cell_id": "W08.initial.natural_forecast",
            "world_slot": "W08",
            "cut_alias": "preavailability",
            "task": "conditional_mean_natural_forecast",
            "state_hash": initial_hash,
            "candidate_head": rollout_heads["no_new_action"],
            "judge_oracle": judge_oracles["no_new_action"],
            "reference_oracle": None,
            "reference_status": _REFERENCE_STATUS,
            "trajectory_metric": trajectory_metrics["no_new_action"],
            "degraded_control_metric": degraded_trajectory_metrics["no_new_action"],
            "utility_metric": utility_metrics["no_new_action"],
            "degraded_utility_metric": _degraded_utility_metric(oracle_utilities[0]),
        },
        {
            "cell_id": "W08.initial.intervention",
            "world_slot": "W08",
            "cut_alias": "preavailability",
            "task": "conditional_mean_intervention_utility",
            "state_hash": initial_hash,
            "policy_aliases": list(aliases),
            "candidate_heads": rollout_heads,
            "judge_oracles": judge_oracles,
            "reference_oracles": {alias: None for alias in aliases},
            "reference_status": _REFERENCE_STATUS,
            "trajectory_metrics": trajectory_metrics,
            "degraded_trajectory_metrics": degraded_trajectory_metrics,
            "utility_metrics": utility_metrics,
            "predicted_utilities": predicted_utilities,
            "oracle_utilities": oracle_utilities,
            "metric": _regret_metric_wire(predicted_utilities, oracle_utilities),
            "degraded_control_metric": _degraded_regret(oracle_utilities),
        },
        {
            "cell_id": "W08.preavailability.pending_firewall",
            "world_slot": "W08",
            "cut_alias": "private-pending-swap",
            "task": "availability_firewall",
            "state_hash": pending_left_state.record.state_hash,
            "left_pending_results": pending_left_raw,
            "right_pending_results": pending_right_raw,
            "left_pending_digest": digest_json(pending_left_raw),
            "right_pending_digest": digest_json(pending_right_raw),
            "left_state_hash": pending_left_state.record.state_hash,
            "right_state_hash": pending_right_state.record.state_hash,
        },
        {
            "cell_id": "W08.late_result.update",
            "world_slot": "W08",
            "cut_alias": "preavailability-to-available",
            "task": "recursive_update",
            "state_hash": updated.record.state_hash,
            "prior_state_hash": initial_hash,
            "parent_state_hash": updated.record.parent_state_hash,
            "delta": delta.to_wire(),
            "delta_digest": digest_json(delta.to_wire()),
            "hidden_state_at_cut": {
                "x": next_x,
                "exposure": 1,
                "remaining": 3,
            },
            "invariant_parameters": {"c": 0},
        },
        {
            "cell_id": "W08.updated.diagnosis",
            "world_slot": "W08",
            "cut_alias": "available",
            "task": "diagnosis",
            "state_hash": updated.record.state_hash,
            "candidate_head": updated_diagnosis_head,
            "oracle_target": {
                "label_order": list(world.catalog.diagnostic_labels),
                "probabilities": [1.0, 0.0],
            },
            "metric": _diagnostic_metric_wire(updated_probabilities, [1.0, 0.0]),
            "degraded_control_metric": _degraded_diagnosis(
                updated_probabilities, [1.0, 0.0]
            ),
        },
        {
            "cell_id": "W08.updated.natural_forecast",
            "world_slot": "W08",
            "cut_alias": "available",
            "task": "conditional_mean_natural_forecast",
            "state_hash": updated.record.state_hash,
            "candidate_head": updated_rollout_head,
            "judge_oracle": updated_judge,
            "reference_oracle": None,
            "reference_status": _REFERENCE_STATUS,
            "trajectory_metric": _trajectory_metric_wire(
                updated_predicted, updated_expected
            ),
            "degraded_control_metric": _degraded_trajectory(
                updated_predicted, updated_expected
            ),
            "utility_metric": _utility_metric_wire(
                updated_predicted_utility, updated_oracle_utility
            ),
            "degraded_utility_metric": _degraded_utility_metric(updated_oracle_utility),
        },
    ]
    body = {
        "protocol": PROTOCOL,
        "bundle_kind": "phase2_privileged_probe_evaluator",
        "world_slot": "W08",
        "status_chain": deepcopy(STATUS_CHAIN),
        "scope_statement": {
            "conditional_mean_trajectory_only": True,
            "expected_utility_only": True,
            "proper_distribution_score_claimed": False,
            "candidate_performance_claimed": False,
            "formal_b01_claimed": False,
            "source_distinct_reference_oracle_claimed": False,
            "evidence_assimilation_claimed": False,
        },
        "source_anchor": {
            "artifact_relpath": source_path.as_posix(),
            "artifact_digest": digest_bytes(source_bytes),
            "artifact_bytes": len(source_bytes),
            "artifact_protocol": source_wire["protocol"],
            "replay_digest": digest_bytes(replay_bytes),
            "byte_identical_replay": True,
        },
        "manifest": probe.manifest.to_wire(),
        "manifest_digest": probe.manifest.digest,
        "fixture": deepcopy(_FIXTURE),
        "states": {
            "initial": initial_binding,
            "updated": updated_binding,
            "pending_left": pending_left_binding,
            "pending_right": pending_right_binding,
        },
        "cells": cells,
        "cell_set_root": _cell_root(cells),
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_SANITY_BUNDLE",
            "cell_count": len(cells),
            "state_binding_count": 4,
            "judge_oracle_policy_bindings": 4,
            "source_distinct_oracle_cells": 0,
            "ledger_credit": 0,
            "formalization_blockers": [
                "not-a-frozen-expected-cell-corpus",
                "privileged-upper-bound-only",
                "no-matched-source-distinct-true-state-reference-oracle",
                "conditional-means-and-expected-utilities-only",
            ],
        },
    }
    report = _attach_bundle_root(body)
    verify_w08_upper_bound_sanity(report)
    return report


def _verify_diagnosis_cell(
    cell: dict[str, Any],
    *,
    state_hash: str,
    class_index: int,
    cut_alias: str,
    manifest_digest: str,
    world: World08,
) -> None:
    _closed(
        cell,
        {
            "cell_id",
            "world_slot",
            "cut_alias",
            "task",
            "state_hash",
            "candidate_head",
            "oracle_target",
            "metric",
            "degraded_control_metric",
        },
        cell["cell_id"],
    )
    if (
        cell["world_slot"] != "W08"
        or cell["task"] != "diagnosis"
        or cell["state_hash"] != state_hash
        or cell["cut_alias"] != cut_alias
    ):
        raise ProtocolViolation("W08 diagnosis cell identity mismatch")
    head = _verify_head(
        cell["candidate_head"],
        operation="diagnose",
        state_hash=state_hash,
        manifest_digest=manifest_digest,
        label=cell["cell_id"],
    )
    _assert_exact_query(head, _exact_diagnosis_query(world), cell["cell_id"])
    _check_head_metadata(head, "diagnose")
    target = _closed(
        cell["oracle_target"],
        {"label_order", "probabilities"},
        f"{cell['cell_id']} target",
    )
    labels = list(world.catalog.diagnostic_labels)
    expected_target = [float(class_index == index) for index in range(2)]
    if target != {"label_order": labels, "probabilities": expected_target}:
        raise ProtocolViolation("W08 diagnosis target contradicts sealed state")
    probabilities = head["execution"]["response"]["result"].get("probabilities")
    if type(probabilities) is not dict or set(probabilities) != set(labels):
        raise ProtocolViolation("W08 diagnosis probability labels mismatch")
    predicted = [
        _finite(probabilities[label], f"W08 diagnosis {label}") for label in labels
    ]
    if predicted != expected_target:
        raise ProtocolViolation("W08 privileged diagnosis is not exact")
    expected = _diagnostic_metric_wire(predicted, expected_target)
    degraded = _degraded_diagnosis(predicted, expected_target)
    _metric_equal(cell["metric"], expected, f"{cell['cell_id']} metric")
    _metric_equal(
        cell["degraded_control_metric"],
        degraded,
        f"{cell['cell_id']} degraded metric",
    )
    if (
        expected["accuracy"] != 1.0
        or expected["log_loss"] != 0.0
        or expected["multiclass_brier"] != 0.0
        or degraded["log_loss"] <= expected["log_loss"]
    ):
        raise ProtocolViolation("W08 diagnosis metric direction failed")


def _verify_forecast_cell(
    cell: dict[str, Any],
    *,
    state_hash: str,
    state_representation: dict[str, Any],
    cut_alias: str,
    policy: Any,
    manifest_digest: str,
    world: World08,
) -> None:
    _closed(
        cell,
        {
            "cell_id",
            "world_slot",
            "cut_alias",
            "task",
            "state_hash",
            "candidate_head",
            "judge_oracle",
            "reference_oracle",
            "reference_status",
            "trajectory_metric",
            "degraded_control_metric",
            "utility_metric",
            "degraded_utility_metric",
        },
        cell["cell_id"],
    )
    if (
        cell["world_slot"] != "W08"
        or cell["task"] != "conditional_mean_natural_forecast"
        or cell["state_hash"] != state_hash
        or cell["cut_alias"] != cut_alias
        or cell["reference_oracle"] is not None
        or cell["reference_status"] != _REFERENCE_STATUS
    ):
        raise ProtocolViolation(
            "W08 forecast cell identity or reference status mismatch"
        )
    head = _verify_head(
        cell["candidate_head"],
        operation="rollout",
        state_hash=state_hash,
        manifest_digest=manifest_digest,
        label=cell["cell_id"],
    )
    expected_query = _exact_rollout_query(world, policy)
    _assert_exact_query(head, expected_query, cell["cell_id"])
    _check_head_metadata(head, "rollout")
    oracle = _verify_oracle_query_binding(
        cell["judge_oracle"],
        head["query"],
        f"{cell['cell_id']} judge oracle",
    )
    _verify_exact_judge_oracle(
        oracle,
        representation=state_representation,
        policy=policy,
        world=world,
        label=f"{cell['cell_id']} judge oracle",
    )
    requested = tuple(expected_query.requested_observables)
    predicted, predicted_utility = _point_rollout(head, requested)
    expected_trajectory = _w08_oracle_mean_matrix(oracle, requested)
    oracle_utility = _finite(
        oracle["expected_utility"], f"{cell['cell_id']} judge utility"
    )
    trajectory_metric = _trajectory_metric_wire(predicted, expected_trajectory)
    degraded = _degraded_trajectory(predicted, expected_trajectory)
    utility_metric = _utility_metric_wire(predicted_utility, oracle_utility)
    degraded_utility = _degraded_utility_metric(oracle_utility)
    _metric_equal(cell["trajectory_metric"], trajectory_metric, "W08 trajectory metric")
    _metric_equal(cell["degraded_control_metric"], degraded, "W08 degraded trajectory")
    _metric_equal(cell["utility_metric"], utility_metric, "W08 utility metric")
    _metric_equal(
        cell["degraded_utility_metric"],
        degraded_utility,
        "W08 degraded utility metric",
    )
    if (
        trajectory_metric["normalized_rmse"] != 0.0
        or degraded["normalized_rmse"] <= 0.0
        or utility_metric["absolute_error"] != 0.0
        or degraded_utility["absolute_error"] <= 0.0
    ):
        raise ProtocolViolation("W08 forecast metric direction failed")


def verify_w08_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    """Recompute every W08 state, query, oracle, and metric binding."""

    report = _closed(
        value,
        {
            "protocol",
            "bundle_kind",
            "world_slot",
            "status_chain",
            "scope_statement",
            "source_anchor",
            "manifest",
            "manifest_digest",
            "fixture",
            "states",
            "cells",
            "cell_set_root",
            "verification_summary",
            "bundle_root",
        },
        "W08 upper-bound sanity report",
    )
    validate_json_like(report)
    if (
        report["protocol"] != PROTOCOL
        or report["bundle_kind"] != "phase2_privileged_probe_evaluator"
        or report["world_slot"] != "W08"
        or report["status_chain"] != STATUS_CHAIN
    ):
        raise ProtocolViolation("W08 upper-bound status or identity was rewritten")
    if report["bundle_root"] != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation("W08 upper-bound bundle root mismatch")
    expected_scope = {
        "conditional_mean_trajectory_only": True,
        "expected_utility_only": True,
        "proper_distribution_score_claimed": False,
        "candidate_performance_claimed": False,
        "formal_b01_claimed": False,
        "source_distinct_reference_oracle_claimed": False,
        "evidence_assimilation_claimed": False,
    }
    if report["scope_statement"] != expected_scope:
        raise ProtocolViolation("W08 upper-bound scope was overstated")
    if report["fixture"] != _FIXTURE:
        raise ProtocolViolation("W08 upper-bound fixture was rewritten")

    world = World08()
    expected_probe = W08TrueStateUpperBoundProbe(world)
    expected_manifest = expected_probe.manifest.to_wire()
    manifest_digest = digest_json(report["manifest"])
    if manifest_digest != report["manifest_digest"]:
        raise ProtocolViolation("W08 upper-bound manifest digest mismatch")
    manifest = report["manifest"]
    if (
        type(manifest) is not dict
        or manifest != expected_manifest
        or manifest.get("world_slot") != "W08"
        or manifest.get("baseline_id") != "B01"
        or manifest.get("privileged") is not True
        or manifest.get("eligibility") != "upper_bound_only"
        or manifest.get("freeze_grade") is not False
    ):
        raise ProtocolViolation("W08 upper-bound manifest eligibility mismatch")

    source = _closed(
        report["source_anchor"],
        {
            "artifact_relpath",
            "artifact_digest",
            "artifact_bytes",
            "artifact_protocol",
            "replay_digest",
            "byte_identical_replay",
        },
        "W08 source anchor",
    )
    _digest(source["artifact_digest"], "W08 artifact digest")
    _digest(source["replay_digest"], "W08 replay digest")
    if (
        source["artifact_digest"] != source["replay_digest"]
        or source["byte_identical_replay"] is not True
        or source["artifact_protocol"]
        != "ucm-phase2-w08-asynchronous-availability-slice/1"
        or type(source["artifact_bytes"]) is not int
        or source["artifact_bytes"] <= 0
    ):
        raise ProtocolViolation("W08 source artifact replay anchor mismatch")
    expected_source_path = (
        Path(source_artifact) if source_artifact is not None else DEFAULT_W08_ARTIFACT
    )
    if source["artifact_relpath"] != expected_source_path.as_posix():
        raise ProtocolViolation("W08 source artifact path does not match the verifier")
    committed_path = Path(__file__).resolve().parents[2] / DEFAULT_W08_ARTIFACT
    committed_raw, bound_source = _load_canonical_artifact(
        committed_path, "committed W08 source artifact"
    )
    live_replay = canonical_json_bytes(run_w08_availability_slice())
    if (
        digest_bytes(committed_raw) != source["artifact_digest"]
        or len(committed_raw) != source["artifact_bytes"]
        or live_replay != committed_raw
        or digest_bytes(live_replay) != source["replay_digest"]
    ):
        raise ProtocolViolation(
            "report is not bound to the live committed W08 source artifact"
        )
    if source_artifact is not None:
        raw, _ = _load_canonical_artifact(
            expected_source_path, "bound W08 source artifact"
        )
        if raw != committed_raw:
            raise ProtocolViolation(
                "bound W08 source differs from the committed artifact"
            )
        if (
            digest_bytes(raw) != source["artifact_digest"]
            or len(raw) != source["artifact_bytes"]
        ):
            raise ProtocolViolation("bound W08 artifact bytes do not match report")
        if replay_runtime:
            if live_replay != raw:
                raise ProtocolViolation("bound W08 artifact does not replay live")

    states = _closed(
        report["states"],
        {"initial", "updated", "pending_left", "pending_right"},
        "W08 state bindings",
    )
    initial = _verify_state_binding(states["initial"], "W08 initial state")
    updated = _verify_state_binding(states["updated"], "W08 updated state")
    pending_left = _verify_state_binding(
        states["pending_left"], "W08 pending-left state"
    )
    pending_right = _verify_state_binding(
        states["pending_right"], "W08 pending-right state"
    )
    initial_record = initial["record"]
    updated_record = updated["record"]
    initial_representation = initial["payload"]["representation"]
    updated_representation = updated["payload"]["representation"]
    expected_initial = {
        "protocol": "ucm-phase2-true-state-w08/1",
        "world_slot": "W08",
        "as_of_available_at": -1,
        "class_index": 0,
        "x": [0.4, -0.2],
        "exposure": 0,
        "remaining": 0,
    }
    if initial_representation != expected_initial:
        raise ProtocolViolation("W08 initial state preimage was rewritten")
    if (
        initial_record["operation"] != "initialize"
        or initial_record["parent_state_hash"] is not None
        or initial_record["delta_digest"] is not None
        or updated_record["operation"] != "update"
        or updated_record["parent_state_hash"] != initial_record["state_hash"]
        or updated_record["state_hash"] == initial_record["state_hash"]
    ):
        raise ProtocolViolation("W08 recursive state lineage is not closed")
    if (
        pending_left != pending_right
        or pending_left["record"]["state_hash"] != pending_right["record"]["state_hash"]
    ):
        raise ProtocolViolation("W08 pending private data split preavailable state")
    expected_initial_record = _state_binding(
        expected_probe.initialize_true_state(
            class_index=0,
            x=[0.4, -0.2],
            exposure=0,
            remaining=0,
            as_of_available_at=-1,
        )
    )["record"]
    binding_fields = (
        "candidate_bundle_digest",
        "model_digest",
        "scope_digest",
        "catalog_digest",
    )
    for label, record in (
        ("initial", initial_record),
        ("updated", updated_record),
        ("pending-left", pending_left["record"]),
        ("pending-right", pending_right["record"]),
    ):
        if any(
            record[field] != expected_initial_record[field] for field in binding_fields
        ):
            raise ProtocolViolation(f"W08 {label} state model binding mismatch")

    cells = report["cells"]
    if type(cells) is not list or len(cells) != 7:
        raise ProtocolViolation("W08 sanity requires exactly seven cells")
    if len({cell.get("cell_id") for cell in cells if type(cell) is dict}) != 7:
        raise ProtocolViolation("W08 sanity cell ids are not unique")
    if _cell_root(cells) != report["cell_set_root"]:
        raise ProtocolViolation("W08 cell set root mismatch")
    by_id = {cell["cell_id"]: cell for cell in cells}
    expected_ids = {
        "W08.initial.diagnosis",
        "W08.initial.natural_forecast",
        "W08.initial.intervention",
        "W08.preavailability.pending_firewall",
        "W08.late_result.update",
        "W08.updated.diagnosis",
        "W08.updated.natural_forecast",
    }
    if set(by_id) != expected_ids:
        raise ProtocolViolation("W08 sanity cell coverage mismatch")
    if bound_source is not None:
        source_assertions = bound_source.get("assertions")
        if (
            type(source_assertions) is not dict
            or set(source_assertions)
            != {
                "initial_heads_consumed_one_hash",
                "pending_private_result_excluded_before_availability",
                "late_result_preserved_collection_and_availability_times",
                "update_changed_hash",
                "update_parent_link_closed",
                "updated_heads_consumed_new_hash",
                "active_course_typestate_retained",
            }
            or any(item is not True for item in source_assertions.values())
        ):
            raise ProtocolViolation("bound W08 source assertions are incomplete")
        intervention_source = by_id["W08.initial.intervention"]
        pending_source = by_id["W08.preavailability.pending_firewall"]
        update_source = by_id["W08.late_result.update"]
        if (
            bound_source.get("initial_state_hash") != initial_record["state_hash"]
            or bound_source.get("diagnosis")
            != by_id["W08.initial.diagnosis"]["candidate_head"]["execution"]
            or bound_source.get("rollouts")
            != {
                alias: intervention_source["candidate_heads"][alias]["execution"]
                for alias in ("no_new_action", "single_A1", "single_A2")
            }
            or bound_source.get("private_pending_swap")
            != {
                "left_pending_digest": pending_source["left_pending_digest"],
                "right_pending_digest": pending_source["right_pending_digest"],
                "left_state_hash": pending_source["left_state_hash"],
                "right_state_hash": pending_source["right_state_hash"],
            }
            or bound_source.get("late_update")
            != {
                "delta": update_source["delta"],
                "delta_digest": update_source["delta_digest"],
                "new_state_id": updated_record["state_id"],
                "new_state_hash": updated_record["state_hash"],
                "parent_state_hash": update_source["parent_state_hash"],
                "diagnosis": by_id["W08.updated.diagnosis"]["candidate_head"][
                    "execution"
                ],
                "no_new_action_rollout": by_id["W08.updated.natural_forecast"][
                    "candidate_head"
                ]["execution"],
            }
        ):
            raise ProtocolViolation("W08 report cells drifted from bound source bytes")

    policies = _vertical_policies(world)
    aliases = ["no_new_action", "single_A1", "single_A2"]
    _verify_diagnosis_cell(
        by_id["W08.initial.diagnosis"],
        state_hash=initial_record["state_hash"],
        class_index=initial_representation["class_index"],
        cut_alias="preavailability",
        manifest_digest=manifest_digest,
        world=world,
    )
    _verify_diagnosis_cell(
        by_id["W08.updated.diagnosis"],
        state_hash=updated_record["state_hash"],
        class_index=updated_representation["class_index"],
        cut_alias="available",
        manifest_digest=manifest_digest,
        world=world,
    )
    _verify_forecast_cell(
        by_id["W08.initial.natural_forecast"],
        state_hash=initial_record["state_hash"],
        state_representation=initial_representation,
        cut_alias="preavailability",
        policy=policies[0],
        manifest_digest=manifest_digest,
        world=world,
    )
    _verify_forecast_cell(
        by_id["W08.updated.natural_forecast"],
        state_hash=updated_record["state_hash"],
        state_representation=updated_representation,
        cut_alias="available",
        policy=policies[0],
        manifest_digest=manifest_digest,
        world=world,
    )

    intervention = by_id["W08.initial.intervention"]
    _closed(
        intervention,
        {
            "cell_id",
            "world_slot",
            "cut_alias",
            "task",
            "state_hash",
            "policy_aliases",
            "candidate_heads",
            "judge_oracles",
            "reference_oracles",
            "reference_status",
            "trajectory_metrics",
            "degraded_trajectory_metrics",
            "utility_metrics",
            "predicted_utilities",
            "oracle_utilities",
            "metric",
            "degraded_control_metric",
        },
        "W08 intervention cell",
    )
    if (
        intervention["world_slot"] != "W08"
        or intervention["cut_alias"] != "preavailability"
        or intervention["task"] != "conditional_mean_intervention_utility"
        or intervention["state_hash"] != initial_record["state_hash"]
        or intervention["policy_aliases"] != aliases
        or intervention["reference_status"] != _REFERENCE_STATUS
        or intervention["reference_oracles"] != {alias: None for alias in aliases}
    ):
        raise ProtocolViolation("W08 intervention identity mismatch")
    expected_aliases = set(aliases)
    for field in (
        "candidate_heads",
        "judge_oracles",
        "trajectory_metrics",
        "degraded_trajectory_metrics",
        "utility_metrics",
    ):
        if (
            type(intervention[field]) is not dict
            or set(intervention[field]) != expected_aliases
        ):
            raise ProtocolViolation(f"W08 intervention {field} coverage mismatch")
    predicted_utilities: list[float] = []
    oracle_utilities: list[float] = []
    for alias, policy in zip(aliases, policies, strict=True):
        head = _verify_head(
            intervention["candidate_heads"][alias],
            operation="rollout",
            state_hash=initial_record["state_hash"],
            manifest_digest=manifest_digest,
            label=f"W08 intervention {alias}",
        )
        expected_query = _exact_rollout_query(world, policy)
        _assert_exact_query(head, expected_query, f"W08 intervention {alias}")
        _check_head_metadata(head, "rollout")
        oracle = _verify_oracle_query_binding(
            intervention["judge_oracles"][alias],
            head["query"],
            f"W08 intervention {alias} judge oracle",
        )
        _verify_exact_judge_oracle(
            oracle,
            representation=initial_representation,
            policy=policy,
            world=world,
            label=f"W08 intervention {alias} judge oracle",
        )
        requested = tuple(expected_query.requested_observables)
        predicted, predicted_utility = _point_rollout(head, requested)
        expected_trajectory = _w08_oracle_mean_matrix(oracle, requested)
        oracle_utility = _finite(
            oracle["expected_utility"], f"W08 intervention {alias} utility"
        )
        _metric_equal(
            intervention["trajectory_metrics"][alias],
            _trajectory_metric_wire(predicted, expected_trajectory),
            f"W08 intervention {alias} trajectory",
        )
        _metric_equal(
            intervention["degraded_trajectory_metrics"][alias],
            _degraded_trajectory(predicted, expected_trajectory),
            f"W08 intervention {alias} degraded trajectory",
        )
        _metric_equal(
            intervention["utility_metrics"][alias],
            _utility_metric_wire(predicted_utility, oracle_utility),
            f"W08 intervention {alias} utility",
        )
        if (
            intervention["trajectory_metrics"][alias]["normalized_rmse"] != 0.0
            or intervention["degraded_trajectory_metrics"][alias]["normalized_rmse"]
            <= 0.0
            or intervention["utility_metrics"][alias]["absolute_error"] != 0.0
        ):
            raise ProtocolViolation("W08 intervention metric direction failed")
        predicted_utilities.append(predicted_utility)
        oracle_utilities.append(oracle_utility)
    if (
        predicted_utilities != intervention["predicted_utilities"]
        or oracle_utilities != intervention["oracle_utilities"]
    ):
        raise ProtocolViolation("W08 intervention utility extraction mismatch")
    regret = _regret_metric_wire(predicted_utilities, oracle_utilities)
    degraded_regret = _degraded_regret(oracle_utilities)
    _metric_equal(intervention["metric"], regret, "W08 intervention regret")
    _metric_equal(
        intervention["degraded_control_metric"],
        degraded_regret,
        "W08 degraded intervention regret",
    )
    if regret["worst_regret"] != 0.0 or degraded_regret["worst_regret"] <= 0.0:
        raise ProtocolViolation("W08 intervention regret direction failed")

    firewall = by_id["W08.preavailability.pending_firewall"]
    _closed(
        firewall,
        {
            "cell_id",
            "world_slot",
            "cut_alias",
            "task",
            "state_hash",
            "left_pending_results",
            "right_pending_results",
            "left_pending_digest",
            "right_pending_digest",
            "left_state_hash",
            "right_state_hash",
        },
        "W08 pending firewall cell",
    )
    if (
        firewall["world_slot"] != "W08"
        or firewall["cut_alias"] != "private-pending-swap"
        or firewall["task"] != "availability_firewall"
        or digest_json(firewall["left_pending_results"])
        != firewall["left_pending_digest"]
        or digest_json(firewall["right_pending_results"])
        != firewall["right_pending_digest"]
        or firewall["left_pending_digest"] == firewall["right_pending_digest"]
        or firewall["left_state_hash"] != firewall["right_state_hash"]
        or firewall["state_hash"] != pending_left["record"]["state_hash"]
        or firewall["left_state_hash"] != pending_left["record"]["state_hash"]
        or firewall["right_state_hash"] != pending_right["record"]["state_hash"]
    ):
        raise ProtocolViolation("W08 private pending result crossed availability")
    if (
        pending_left["payload"]["representation"]["as_of_available_at"] != 0
        or pending_right["payload"]["representation"]["as_of_available_at"] != 0
    ):
        raise ProtocolViolation("W08 pending firewall states are not at cut zero")
    for side in ("left_pending_results", "right_pending_results"):
        rows = firewall[side]
        if type(rows) is not list or not rows:
            raise ProtocolViolation("W08 pending firewall has no private rows")
        for row in rows:
            if (
                type(row) is not dict
                or set(row) != {"collected_at", "available_at", "channel_id", "value"}
                or type(row["available_at"]) is not int
                or row["available_at"] <= 0
                or type(row["collected_at"]) is not int
            ):
                raise ProtocolViolation(
                    "W08 pending firewall row was already available at cut zero"
                )

    update = by_id["W08.late_result.update"]
    _closed(
        update,
        {
            "cell_id",
            "world_slot",
            "cut_alias",
            "task",
            "state_hash",
            "prior_state_hash",
            "parent_state_hash",
            "delta",
            "delta_digest",
            "hidden_state_at_cut",
            "invariant_parameters",
        },
        "W08 late-result update cell",
    )
    if (
        update["world_slot"] != "W08"
        or update["cut_alias"] != "preavailability-to-available"
        or update["task"] != "recursive_update"
        or update["state_hash"] != updated_record["state_hash"]
        or update["prior_state_hash"] != initial_record["state_hash"]
        or update["parent_state_hash"] != initial_record["state_hash"]
        or digest_json(update["delta"]) != update["delta_digest"]
        or update["delta_digest"] != updated_record["delta_digest"]
    ):
        raise ProtocolViolation("W08 late-result update did not close state lineage")
    delta = _closed(update["delta"], {"protocol", "advance_to", "events"}, "W08 delta")
    if (
        delta["protocol"] != "ucm-visible-delta/1"
        or delta["advance_to"] != 1
        or type(delta["events"]) is not list
        or len(delta["events"]) != 2
    ):
        raise ProtocolViolation("W08 late-result delta identity mismatch")
    treatment, late_result = delta["events"]
    if treatment != {
        "kind": EventKind.PERFORMED_TREATMENT.value,
        "occurred_at": 0,
        "available_at": 0,
        "event_uid": "w08-factual-a1-at-zero",
        "payload": {"action_id": "A1", "course_microticks": 4},
        "collected_at": None,
    } or late_result != {
        "kind": EventKind.OBSERVATION_AVAILABLE.value,
        "occurred_at": -1,
        "available_at": 1,
        "event_uid": "w08-late-result-at-one",
        "payload": {"channel_id": "obs_0", "check_id": "Q0", "value": 0.55},
        "collected_at": -1,
    }:
        raise ProtocolViolation(
            "W08 event, collection, or availability time was rewritten"
        )
    hidden = _closed(
        update["hidden_state_at_cut"],
        {"x", "exposure", "remaining"},
        "W08 updated truth",
    )
    invariant = _closed(update["invariant_parameters"], {"c"}, "W08 invariant truth")
    if updated_representation != {
        "protocol": "ucm-phase2-true-state-w08/1",
        "world_slot": "W08",
        "as_of_available_at": 1,
        "class_index": invariant["c"],
        "x": hidden["x"],
        "exposure": hidden["exposure"],
        "remaining": hidden["remaining"],
    }:
        raise ProtocolViolation("W08 updated state contradicts update truth")
    if hidden["exposure"] != 1 or hidden["remaining"] != 3:
        raise ProtocolViolation("W08 active-course typestate was discarded")
    at_zero = _c0_transition(initial_representation["x"], active=0)
    expected_next = _c0_transition(at_zero, active=1)
    if not np.allclose(
        np.asarray(hidden["x"], dtype=float),
        np.asarray(expected_next, dtype=float),
        atol=1e-12,
        rtol=0.0,
    ):
        raise ProtocolViolation("W08 two-step privileged update truth is inconsistent")
    updated_head = by_id["W08.updated.natural_forecast"]["candidate_head"]
    updated_predictions = updated_head["execution"]["response"]["result"][
        "observable_predictions"
    ]
    expected_first = _c0_transition(hidden["x"], active=1)
    first_values = [
        updated_predictions["obs_0"]["values"][0],
        updated_predictions["obs_1"]["values"][0],
    ]
    if not np.allclose(
        np.asarray(first_values, dtype=float),
        np.asarray(expected_first, dtype=float),
        atol=1e-12,
        rtol=0.0,
    ):
        raise ProtocolViolation(
            "W08 updated NoNewAction failed to continue the active course"
        )

    summary = _closed(
        report["verification_summary"],
        {
            "status",
            "cell_count",
            "state_binding_count",
            "judge_oracle_policy_bindings",
            "source_distinct_oracle_cells",
            "ledger_credit",
            "formalization_blockers",
        },
        "W08 verification summary",
    )
    if summary != {
        "status": "VALID_PRE_FREEZE_SANITY_BUNDLE",
        "cell_count": 7,
        "state_binding_count": 4,
        "judge_oracle_policy_bindings": 4,
        "source_distinct_oracle_cells": 0,
        "ledger_credit": 0,
        "formalization_blockers": [
            "not-a-frozen-expected-cell-corpus",
            "privileged-upper-bound-only",
            "no-matched-source-distinct-true-state-reference-oracle",
            "conditional-means-and-expected-utilities-only",
        ],
    }:
        raise ProtocolViolation("W08 verification summary was overstated")


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run or verify the PRE-FREEZE W08 upper-bound sanity bundle."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify", type=Path, metavar="REPORT")
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_W08_ARTIFACT)
    parser.add_argument("--replay-runtime", action="store_true")
    args = parser.parse_args()
    if args.verify is not None:
        _raw, report = _load_canonical_artifact(args.verify, "W08 sanity report")
        verify_w08_upper_bound_sanity(
            report,
            source_artifact=args.source_artifact,
            replay_runtime=args.replay_runtime,
        )
        return 0
    report = run_w08_upper_bound_sanity(source_artifact=args.source_artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(report))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "DEFAULT_W08_ARTIFACT",
    "run_w08_upper_bound_sanity",
    "verify_w08_upper_bound_sanity",
]


if __name__ == "__main__":
    raise SystemExit(_main())
