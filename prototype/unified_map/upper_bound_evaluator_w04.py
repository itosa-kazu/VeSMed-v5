"""Patient-bound PRE-FREEZE evaluator for the privileged W04 pair.

W04 is the smallest world in which an untreated trajectory is insufficient to
identify treatment response.  The two patients evaluated here start from the
same observed scalar and have the same no-action mean trajectory, while their
optimal one-shot treatments are opposite.  This evaluator therefore binds all
heads to patient-specific true-state hashes and checks the resulting *full*
controlled-future behaviour with the ordinary pair metric.

This is deliberately an upper-bound sanity adapter, not a public candidate
evaluation.  The response modifier is judge-private, the committed source is
PRE-FREEZE, and every row has zero ledger credit.  The analytic reference below
is a second scalar recurrence local to this module; it is useful for byte-level
recomputation but is not represented as a formally certified source-distinct
oracle.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
import math
from pathlib import Path
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .metrics import InformationRelation, PairProbe, classify_pair
from .schema import ActionPlan, DiagnosisQuery, PlanKind, RolloutQuery
from .true_state_probe_w04 import (
    W04TrueStateUpperBoundProbe,
    _response_delta,
    run_w04_collision_slice,
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
    _diagnosis_probabilities,
    _diagnostic_metric_wire,
    _digest,
    _finite,
    _head_wire,
    _metric_equal,
    _oracle_comparison,
    _oracle_wire,
    _point_rollout,
    _regret_metric_wire,
    _state_binding,
    _trajectory_metric_wire,
    _verify_head,
    _verify_oracle_query_binding,
    _verify_state_binding,
    compute_upper_bound_bundle_root,
)
from .worlds.base import CounterfactualOracle
from .worlds.w04 import W04World


DEFAULT_W04_ARTIFACT = Path(
    "results/unified_map/pre_freeze/20260717-w04-dangerous-collision-probe/"
    "vertical-slice.json"
)

_BUNDLE_KIND = "phase2_privileged_patient_pair_evaluator"
_PATIENTS = ("C0", "C1")
_POLICY_ALIASES = ("no_new_action", "single_A1", "single_A2")
_HORIZON = 4
_PAIR_THRESHOLDS = {
    "candidate_same_epsilon": 0.005,
    "candidate_split_delta": 0.35,
    "oracle_distinguishable_delta": 0.35,
    "oracle_equivalent_epsilon": 0.005,
    "catastrophic_margin": 0.75,
}
_SCOPE_STATEMENT = {
    "patient_bound_true_state": True,
    "mean_trajectory_only": True,
    "expected_utility_only": True,
    "proper_distribution_score_claimed": False,
    "candidate_performance_claimed": False,
    "formal_b01_claimed": False,
    "public_collision_attribution_claimed": False,
    "public_belief_oracle_used_as_point_truth": False,
    "source_distinct_oracle_certified": False,
}
_FORMALIZATION_BLOCKERS = [
    "not-a-frozen-expected-cell-corpus",
    "privileged-upper-bound-only",
    "public-belief-oracle-is-not-point-true-state-reference",
    "analytic-reference-not-source-distinct-certified",
    "mean-and-expected-utility-projections-only",
]


def _clean_float(value: float) -> float:
    result = float(value)
    return 0.0 if result == 0.0 else result


def _analytic_true_state_reference(
    *, class_index: int, x: float, policy: ActionPlan, horizon: int
) -> CounterfactualOracle:
    """Independent scalar closed recurrence for the W04 point state.

    This code intentionally does not call ``W04World`` rollout internals.  It
    implements the published recurrence directly:

    ``m'=.92m+.15-.45*g*u``; ``v'=.92^2v+.04^2``; and discounted
    quadratic utility with a .06 non-zero-action cost.
    """

    if type(class_index) is not int or class_index not in {0, 1}:
        raise ProtocolViolation("W04 analytic reference class must be zero or one")
    if type(x) not in {int, float} or not math.isfinite(float(x)):
        raise ProtocolViolation("W04 analytic reference x must be finite")
    if type(policy) is not ActionPlan or type(horizon) is not int or horizon <= 0:
        raise ProtocolViolation("W04 analytic reference query is invalid")

    schedule = [0.0] * horizon
    if policy.kind is PlanKind.ACTION_SEQUENCE:
        for action in policy.actions:
            if action.offset >= horizon:
                continue
            if action.action_id == "A1":
                schedule[action.offset] = 1.0
            elif action.action_id == "A2":
                schedule[action.offset] = -1.0
            else:
                raise ProtocolViolation(
                    "W04 point reference only supports treatment sequences"
                )
    elif policy.kind is not PlanKind.NO_NEW_ACTION:
        raise ProtocolViolation("W04 point reference does not support this plan kind")

    mean = float(x)
    variance = 0.0
    utility = 0.0
    response_sign = 1.0 if class_index == 0 else -1.0
    steps: list[dict[str, Any]] = []
    for offset, action in enumerate(schedule):
        mean = 0.92 * mean + 0.15 - 0.45 * response_sign * action
        variance = 0.92**2 * variance + 0.04**2
        expected_cost = variance + mean**2 + 0.06 * float(action != 0.0)
        utility -= 0.97**offset * expected_cost
        steps.append(
            {
                "offset": offset + 1,
                "mean": _clean_float(mean),
                "variance": _clean_float(variance),
            }
        )

    expected_utility = _clean_float(utility)
    posterior = {
        "C0": float(class_index == 0),
        "C1": float(class_index == 1),
    }
    return CounterfactualOracle(
        policy=policy,
        horizon=horizon,
        observation_distribution={
            "family": "class-conditioned-gaussian-mixture",
            "channels": ["obs_0", "obs_1"],
            "steps": deepcopy(steps),
        },
        latent_distribution={
            "family": "class-conditioned-gaussian-mixture",
            "diagnostic_posterior": posterior,
            "steps": deepcopy(steps),
        },
        outcome_distribution={
            "utility_family": "mixture-quadratic-form",
            "expected_utility": expected_utility,
        },
        expected_utility=expected_utility,
        numerical_diagnostics={
            "method": "independent-scalar-closed-recurrence",
            "initial_variance": 0.0,
        },
    )


def _w04_oracle_mean(oracle: dict[str, Any]) -> list[list[float]]:
    distribution = oracle.get("observation_distribution")
    if (
        type(distribution) is not dict
        or distribution.get("family") != "class-conditioned-gaussian-mixture"
        or distribution.get("channels") != ["obs_0", "obs_1"]
    ):
        raise ProtocolViolation("W04 oracle observation distribution is malformed")
    steps = distribution.get("steps")
    if type(steps) is not list or not steps:
        raise ProtocolViolation("W04 oracle steps are absent")
    result: list[list[float]] = []
    for step in steps:
        row = _closed(step, {"offset", "mean", "variance"}, "W04 oracle step")
        if type(row["offset"]) is not int or row["offset"] != len(result) + 1:
            raise ProtocolViolation("W04 oracle offsets are not contiguous")
        if _finite(row["variance"], "W04 oracle variance") < 0.0:
            raise ProtocolViolation("W04 oracle variance is negative")
        result.append([_finite(row["mean"], "W04 oracle mean")])
    return result


def _behaviour_signature(
    heads: dict[str, dict[str, Any]], aliases: tuple[str, ...]
) -> tuple[float, ...]:
    values: list[float] = []
    for alias in aliases:
        predicted, utility = _point_rollout(heads[alias], ("obs_0",))
        values.extend(row[0] for row in predicted)
        values.append(utility)
    return tuple(values)


def _oracle_signature(
    oracles: dict[str, dict[str, Any]], aliases: tuple[str, ...]
) -> tuple[float, ...]:
    values: list[float] = []
    for alias in aliases:
        values.extend(row[0] for row in _w04_oracle_mean(oracles[alias]))
        values.append(_finite(oracles[alias]["expected_utility"], "oracle utility"))
    return tuple(values)


def _pair_probe_wire(probe: PairProbe) -> dict[str, Any]:
    return {
        "pair_id": probe.pair_id,
        "state_hash_a": probe.state_hash_a,
        "state_hash_b": probe.state_hash_b,
        "candidate_signature_a": list(probe.candidate_signature_a),
        "candidate_signature_b": list(probe.candidate_signature_b),
        "oracle_signature_a": list(probe.oracle_signature_a),
        "oracle_signature_b": list(probe.oracle_signature_b),
        "oracle_action_values_a": list(probe.oracle_action_values_a),
        "oracle_action_values_b": list(probe.oracle_action_values_b),
        "information_relation": probe.information_relation,
        "intervention_identifiable": probe.intervention_identifiable,
    }


def _pair_probe_from_wire(value: object) -> PairProbe:
    row = _closed(
        value,
        {
            "pair_id",
            "state_hash_a",
            "state_hash_b",
            "candidate_signature_a",
            "candidate_signature_b",
            "oracle_signature_a",
            "oracle_signature_b",
            "oracle_action_values_a",
            "oracle_action_values_b",
            "information_relation",
            "intervention_identifiable",
        },
        "W04 pair probe",
    )
    for name in ("state_hash_a", "state_hash_b"):
        _digest(row[name], f"W04 pair {name}")
    tuple_fields: dict[str, tuple[float, ...]] = {}
    for name in (
        "candidate_signature_a",
        "candidate_signature_b",
        "oracle_signature_a",
        "oracle_signature_b",
        "oracle_action_values_a",
        "oracle_action_values_b",
    ):
        raw = row[name]
        if type(raw) is not list or not raw:
            raise ProtocolViolation(f"W04 pair {name} must be a non-empty list")
        tuple_fields[name] = tuple(_finite(item, f"W04 pair {name}") for item in raw)
    if type(row["intervention_identifiable"]) is not bool:
        raise ProtocolViolation("W04 pair intervention_identifiable must be boolean")
    return PairProbe(
        pair_id=row["pair_id"],
        state_hash_a=row["state_hash_a"],
        state_hash_b=row["state_hash_b"],
        information_relation=row["information_relation"],
        intervention_identifiable=row["intervention_identifiable"],
        **tuple_fields,
    )


def _classification_wire(probe: PairProbe) -> dict[str, Any]:
    wire = asdict(classify_pair(probe, **_PAIR_THRESHOLDS))
    validate_json_like(wire)
    return wire


def _load_and_replay_source(
    source_artifact: Path | str, *, x: float
) -> tuple[Path, bytes, dict[str, Any], bytes]:
    source_path = Path(source_artifact)
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(
            f"W04 source artifact is unavailable: {source_path}"
        ) from exc
    try:
        source_wire = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("W04 source artifact is not JSON") from exc
    if canonical_json_bytes(source_wire) != source_bytes:
        raise ProtocolViolation("W04 source artifact is not canonical JSON")
    replay_bytes = canonical_json_bytes(run_w04_collision_slice(x=x))
    if replay_bytes != source_bytes:
        raise ProtocolViolation("W04 committed vertical slice does not byte-replay")
    return source_path, source_bytes, source_wire, replay_bytes


def run_w04_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W04_ARTIFACT,
    x: float = 0.4,
) -> dict[str, Any]:
    """Replay W04 and collect patient-bound diagnosis/control/update cells."""

    source_path, source_bytes, source_wire, replay_bytes = _load_and_replay_source(
        source_artifact, x=x
    )
    world = W04World()
    probe = W04TrueStateUpperBoundProbe(world)
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    utility_digest = digest_json(
        ["W04", world.catalog.digest, _HORIZON, "discounted-quadratic-cost"]
    )
    policies = world.policy_set(_HORIZON)[:3]

    states: dict[str, dict[str, Any]] = {}
    cells: list[dict[str, Any]] = []
    initial_heads_by_patient: dict[str, dict[str, dict[str, Any]]] = {}
    initial_oracles_by_patient: dict[str, dict[str, dict[str, Any]]] = {}
    initial_utilities_by_patient: dict[str, list[float]] = {}

    for class_index, patient in enumerate(_PATIENTS):
        initial = probe.initialize_true_state(class_index=class_index, x=x)
        diagnosis = probe.diagnose(initial, diagnosis_query, query_seed=1)
        diagnosis_head = _head_wire(diagnosis, diagnosis_query)
        diagnosis_probabilities = _diagnosis_probabilities(
            diagnosis_head, world.catalog.diagnostic_labels
        )
        diagnosis_target = [float(index == class_index) for index in range(2)]

        heads: dict[str, dict[str, Any]] = {}
        production_oracles: dict[str, dict[str, Any]] = {}
        analytic_references: dict[str, dict[str, Any]] = {}
        oracle_comparisons: dict[str, dict[str, Any]] = {}
        trajectory_metrics: dict[str, dict[str, Any]] = {}
        predicted_utilities: list[float] = []
        oracle_utilities: list[float] = []
        predicted_paths: dict[str, list[list[float]]] = {}
        oracle_paths: dict[str, list[list[float]]] = {}

        for alias, policy in zip(_POLICY_ALIASES, policies, strict=True):
            query = RolloutQuery(_HORIZON, policy, ("obs_0",), utility_digest)
            execution = probe.rollout(initial, query, query_seed=2)
            head = _head_wire(execution, query)
            production = _oracle_wire(
                world.judge_true_state_counterfactual(
                    {"x": float(x)}, {"class_index": class_index}, policy, _HORIZON
                )
            )
            reference = _oracle_wire(
                _analytic_true_state_reference(
                    class_index=class_index,
                    x=float(x),
                    policy=policy,
                    horizon=_HORIZON,
                )
            )
            predicted, predicted_utility = _point_rollout(head, ("obs_0",))
            oracle_mean = _w04_oracle_mean(production)
            heads[alias] = head
            production_oracles[alias] = production
            analytic_references[alias] = reference
            oracle_comparisons[alias] = _oracle_comparison(production, reference)
            trajectory_metrics[alias] = _trajectory_metric_wire(predicted, oracle_mean)
            predicted_utilities.append(predicted_utility)
            oracle_utilities.append(
                _finite(production["expected_utility"], "W04 oracle utility")
            )
            predicted_paths[alias] = predicted
            oracle_paths[alias] = oracle_mean

        initial_heads_by_patient[patient] = heads
        initial_oracles_by_patient[patient] = production_oracles
        initial_utilities_by_patient[patient] = oracle_utilities
        initial_hash = initial.record.state_hash
        cells.extend(
            (
                {
                    "cell_id": f"W04.{patient}.initial.diagnosis",
                    "world_slot": "W04",
                    "patient_alias": patient,
                    "cut_alias": "initial",
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
                    "cell_id": f"W04.{patient}.initial.natural_forecast",
                    "world_slot": "W04",
                    "patient_alias": patient,
                    "cut_alias": "initial",
                    "task": "natural_forecast_mean",
                    "state_hash": initial_hash,
                    "candidate_head": heads["no_new_action"],
                    "production_oracle": production_oracles["no_new_action"],
                    "analytic_reference_oracle": analytic_references["no_new_action"],
                    "oracle_comparison": oracle_comparisons["no_new_action"],
                    "metric": trajectory_metrics["no_new_action"],
                    "degraded_control_metric": _degraded_trajectory(
                        predicted_paths["no_new_action"],
                        oracle_paths["no_new_action"],
                    ),
                    "expected_utility": predicted_utilities[0],
                },
                {
                    "cell_id": f"W04.{patient}.initial.intervention",
                    "world_slot": "W04",
                    "patient_alias": patient,
                    "cut_alias": "initial",
                    "task": "intervention_mean_utility",
                    "state_hash": initial_hash,
                    "policy_aliases": list(_POLICY_ALIASES),
                    "candidate_heads": heads,
                    "production_oracles": production_oracles,
                    "analytic_reference_oracles": analytic_references,
                    "oracle_comparisons": oracle_comparisons,
                    "trajectory_metrics": trajectory_metrics,
                    "predicted_utilities": predicted_utilities,
                    "oracle_utilities": oracle_utilities,
                    "metric": _regret_metric_wire(
                        predicted_utilities, oracle_utilities
                    ),
                    "degraded_control_metric": _degraded_regret(oracle_utilities),
                },
            )
        )

        delta, next_x = _response_delta(class_index=class_index, prior_x=float(x))
        updated = probe.update_private(
            initial,
            delta,
            hidden_state_at_cut={"x": next_x},
            invariant_parameters={"class_index": class_index},
            inference_seed=3,
        )
        updated_diagnosis = probe.diagnose(updated, diagnosis_query, query_seed=4)
        updated_diagnosis_head = _head_wire(updated_diagnosis, diagnosis_query)
        updated_query = RolloutQuery(_HORIZON, policies[0], ("obs_0",), utility_digest)
        updated_execution = probe.rollout(updated, updated_query, query_seed=5)
        updated_head = _head_wire(updated_execution, updated_query)
        updated_production = _oracle_wire(
            world.judge_true_state_counterfactual(
                {"x": next_x},
                {"class_index": class_index},
                policies[0],
                _HORIZON,
            )
        )
        updated_reference = _oracle_wire(
            _analytic_true_state_reference(
                class_index=class_index,
                x=next_x,
                policy=policies[0],
                horizon=_HORIZON,
            )
        )
        updated_predicted, updated_utility = _point_rollout(updated_head, ("obs_0",))
        updated_truth = _w04_oracle_mean(updated_production)
        updated_probabilities = _diagnosis_probabilities(
            updated_diagnosis_head, world.catalog.diagnostic_labels
        )
        states[patient] = {
            "initial": _state_binding(initial),
            "updated": _state_binding(updated),
        }
        cells.extend(
            (
                {
                    "cell_id": f"W04.{patient}.update",
                    "world_slot": "W04",
                    "patient_alias": patient,
                    "cut_alias": "initial-to-updated",
                    "task": "recursive_update",
                    "state_hash": updated.record.state_hash,
                    "prior_state_hash": initial.record.state_hash,
                    "parent_state_hash": updated.record.parent_state_hash,
                    "delta": delta.to_wire(),
                    "delta_digest": digest_json(delta.to_wire()),
                },
                {
                    "cell_id": f"W04.{patient}.updated.diagnosis",
                    "world_slot": "W04",
                    "patient_alias": patient,
                    "cut_alias": "updated",
                    "task": "diagnosis",
                    "state_hash": updated.record.state_hash,
                    "candidate_head": updated_diagnosis_head,
                    "oracle_target": {
                        "label_order": list(world.catalog.diagnostic_labels),
                        "probabilities": diagnosis_target,
                    },
                    "metric": _diagnostic_metric_wire(
                        updated_probabilities, diagnosis_target
                    ),
                    "degraded_control_metric": _degraded_diagnosis(
                        updated_probabilities, diagnosis_target
                    ),
                },
                {
                    "cell_id": f"W04.{patient}.updated.natural_forecast",
                    "world_slot": "W04",
                    "patient_alias": patient,
                    "cut_alias": "updated",
                    "task": "natural_forecast_mean",
                    "state_hash": updated.record.state_hash,
                    "candidate_head": updated_head,
                    "production_oracle": updated_production,
                    "analytic_reference_oracle": updated_reference,
                    "oracle_comparison": _oracle_comparison(
                        updated_production, updated_reference
                    ),
                    "metric": _trajectory_metric_wire(updated_predicted, updated_truth),
                    "degraded_control_metric": _degraded_trajectory(
                        updated_predicted, updated_truth
                    ),
                    "expected_utility": updated_utility,
                },
            )
        )

    left_heads = initial_heads_by_patient["C0"]
    right_heads = initial_heads_by_patient["C1"]
    left_oracles = initial_oracles_by_patient["C0"]
    right_oracles = initial_oracles_by_patient["C1"]
    pair_probe = PairProbe(
        pair_id="W04.patient-bound.opposite-treatment-response",
        state_hash_a=states["C0"]["initial"]["record"]["state_hash"],
        state_hash_b=states["C1"]["initial"]["record"]["state_hash"],
        candidate_signature_a=_behaviour_signature(left_heads, _POLICY_ALIASES),
        candidate_signature_b=_behaviour_signature(right_heads, _POLICY_ALIASES),
        oracle_signature_a=_oracle_signature(left_oracles, _POLICY_ALIASES),
        oracle_signature_b=_oracle_signature(right_oracles, _POLICY_ALIASES),
        oracle_action_values_a=tuple(initial_utilities_by_patient["C0"]),
        oracle_action_values_b=tuple(initial_utilities_by_patient["C1"]),
        information_relation=InformationRelation.NONIDENTIFIED.value,
        intervention_identifiable=False,
    )
    classification = _classification_wire(pair_probe)
    left_noop, _ = _point_rollout(left_heads["no_new_action"], ("obs_0",))
    right_noop, _ = _point_rollout(right_heads["no_new_action"], ("obs_0",))
    cells.append(
        {
            "cell_id": "W04.patient_pair.collision",
            "world_slot": "W04",
            "patient_alias": "C0-vs-C1",
            "cut_alias": "initial-pair",
            "task": "dangerous_collision",
            "shared_observed_scalar": float(x),
            "natural_mean_paths": {"C0": left_noop, "C1": right_noop},
            "optimal_action_aliases": {
                "C0": _POLICY_ALIASES[
                    max(
                        range(3),
                        key=initial_utilities_by_patient["C0"].__getitem__,
                    )
                ],
                "C1": _POLICY_ALIASES[
                    max(
                        range(3),
                        key=initial_utilities_by_patient["C1"].__getitem__,
                    )
                ],
            },
            "pair_probe": _pair_probe_wire(pair_probe),
            "thresholds": deepcopy(_PAIR_THRESHOLDS),
            "classification": classification,
            "public_attribution": {
                "candidate_failure_claimed": False,
                "attribution_eligible": False,
                "privileged_truth_required": True,
                "basis": "direct-true-state-pair-without-candidate-visible-history",
            },
        }
    )

    body = {
        "protocol": PROTOCOL,
        "bundle_kind": _BUNDLE_KIND,
        "world_slot": "W04",
        "status_chain": deepcopy(STATUS_CHAIN),
        "scope_statement": deepcopy(_SCOPE_STATEMENT),
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
        "fixture": {
            "shared_observed_scalar": float(x),
            "horizon": _HORIZON,
            "patient_aliases": list(_PATIENTS),
            "policy_aliases": list(_POLICY_ALIASES),
        },
        "states": states,
        "cells": cells,
        "cell_set_root": _cell_root(cells),
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_W04_PATIENT_PAIR_SANITY_BUNDLE",
            "cell_count": len(cells),
            "state_binding_count": 4,
            "analytic_reference_comparison_count": 10,
            "source_distinct_oracle_certification_count": 0,
            "ledger_credit": 0,
            "formalization_blockers": list(_FORMALIZATION_BLOCKERS),
        },
    }
    result = _attach_bundle_root(body)
    verify_w04_upper_bound_sanity(result)
    return result


def _expected_policy_map(world: W04World) -> dict[str, ActionPlan]:
    return dict(zip(_POLICY_ALIASES, world.policy_set(_HORIZON)[:3], strict=True))


def verify_w04_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    """Recompute state, head, oracle, metric, pair, and lineage claims."""

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
        "W04 upper-bound sanity report",
    )
    validate_json_like(report)
    if (
        report["protocol"] != PROTOCOL
        or report["bundle_kind"] != _BUNDLE_KIND
        or report["world_slot"] != "W04"
        or report["status_chain"] != STATUS_CHAIN
        or report["scope_statement"] != _SCOPE_STATEMENT
    ):
        raise ProtocolViolation(
            "W04 upper-bound identity, status, or scope was rewritten"
        )
    if report["bundle_root"] != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation("W04 upper-bound bundle root mismatch")

    manifest = report["manifest"]
    if digest_json(manifest) != report["manifest_digest"]:
        raise ProtocolViolation("W04 upper-bound manifest digest mismatch")
    if (
        type(manifest) is not dict
        or manifest.get("world_slot") != "W04"
        or manifest.get("baseline_id") != "B01"
        or manifest.get("privileged") is not True
        or manifest.get("eligibility") != "upper_bound_only"
        or manifest.get("freeze_grade") is not False
    ):
        raise ProtocolViolation("W04 upper-bound manifest eligibility mismatch")

    fixture = _closed(
        report["fixture"],
        {"shared_observed_scalar", "horizon", "patient_aliases", "policy_aliases"},
        "W04 fixture",
    )
    x = _finite(fixture["shared_observed_scalar"], "W04 shared scalar")
    if (
        fixture["horizon"] != _HORIZON
        or fixture["patient_aliases"] != list(_PATIENTS)
        or fixture["policy_aliases"] != list(_POLICY_ALIASES)
    ):
        raise ProtocolViolation("W04 fixture identity mismatch")

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
        "W04 source anchor",
    )
    _digest(source["artifact_digest"], "W04 source artifact digest")
    _digest(source["replay_digest"], "W04 source replay digest")
    if (
        source["artifact_digest"] != source["replay_digest"]
        or source["byte_identical_replay"] is not True
        or source["artifact_protocol"] != "ucm-phase2-w04-dangerous-collision-slice/1"
        or type(source["artifact_bytes"]) is not int
        or source["artifact_bytes"] <= 0
    ):
        raise ProtocolViolation("W04 source artifact replay anchor mismatch")
    expected_source_path = (
        Path(source_artifact) if source_artifact is not None else DEFAULT_W04_ARTIFACT
    )
    if source["artifact_relpath"] != expected_source_path.as_posix():
        raise ProtocolViolation("W04 source artifact path does not match the verifier")

    # Always bind verification to the repository-owned source artifact.  A
    # caller may provide a byte-identical copy, but may not replace the source
    # and then re-sign the self-consistent report around it.
    committed_path = Path(__file__).resolve().parents[2] / DEFAULT_W04_ARTIFACT
    try:
        committed_raw = committed_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation("committed W04 source artifact is unavailable") from exc
    try:
        committed_wire = json.loads(committed_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("committed W04 source artifact is not JSON") from exc
    if canonical_json_bytes(committed_wire) != committed_raw:
        raise ProtocolViolation("committed W04 source artifact is not canonical")
    live_replay = canonical_json_bytes(run_w04_collision_slice(x=x))
    if (
        digest_bytes(committed_raw) != source["artifact_digest"]
        or len(committed_raw) != source["artifact_bytes"]
        or live_replay != committed_raw
        or digest_bytes(live_replay) != source["replay_digest"]
    ):
        raise ProtocolViolation(
            "report is not bound to the live committed W04 source artifact"
        )
    if source_artifact is not None:
        source_path = expected_source_path
        try:
            raw = source_path.read_bytes()
        except OSError as exc:
            raise ProtocolViolation("bound W04 source artifact is unavailable") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("bound W04 source artifact is not JSON") from exc
        if canonical_json_bytes(decoded) != raw:
            raise ProtocolViolation("bound W04 source artifact is not canonical")
        if raw != committed_raw:
            raise ProtocolViolation(
                "bound W04 source differs from the committed artifact"
            )
        if (
            digest_bytes(raw) != source["artifact_digest"]
            or len(raw) != source["artifact_bytes"]
        ):
            raise ProtocolViolation("bound W04 source bytes do not match the report")
        if replay_runtime and live_replay != raw:
            raise ProtocolViolation("bound W04 source artifact does not replay live")

    world = W04World()
    probe = W04TrueStateUpperBoundProbe(world)
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    utility_digest = digest_json(
        ["W04", world.catalog.digest, _HORIZON, "discounted-quadratic-cost"]
    )
    policy_map = _expected_policy_map(world)

    states = _closed(report["states"], set(_PATIENTS), "W04 patient states")
    verified_states: dict[str, dict[str, dict[str, Any]]] = {}
    live_states: dict[str, dict[str, Any]] = {}
    live_deltas: dict[str, Any] = {}
    for class_index, patient in enumerate(_PATIENTS):
        pair = _closed(states[patient], {"initial", "updated"}, f"{patient} states")
        initial = _verify_state_binding(pair["initial"], f"{patient} initial state")
        updated = _verify_state_binding(pair["updated"], f"{patient} updated state")
        initial_record = initial["record"]
        updated_record = updated["record"]
        initial_representation = _closed(
            initial["payload"]["representation"],
            {
                "protocol",
                "world_slot",
                "as_of_available_at",
                "class_index",
                "x",
            },
            f"{patient} initial representation",
        )
        updated_representation = _closed(
            updated["payload"]["representation"],
            {
                "protocol",
                "world_slot",
                "as_of_available_at",
                "class_index",
                "x",
            },
            f"{patient} updated representation",
        )
        if (
            initial_representation["protocol"] != "ucm-phase2-true-state-w04/1"
            or initial_representation["world_slot"] != "W04"
            or initial_representation["class_index"] != class_index
            or initial_representation["x"] != x
            or initial_representation["as_of_available_at"] != 0
            or updated_representation["protocol"] != "ucm-phase2-true-state-w04/1"
            or updated_representation["world_slot"] != "W04"
            or updated_representation["class_index"] != class_index
            or updated_representation["as_of_available_at"] != 1
        ):
            raise ProtocolViolation(f"{patient} sealed state contradicts the fixture")
        expected_next_x = 0.92 * x + 0.15 - 0.45 * (1.0 if class_index == 0 else -1.0)
        if updated_representation["x"] != expected_next_x:
            raise ProtocolViolation(f"{patient} updated x contradicts the response")
        if (
            initial_record["operation"] != "initialize"
            or initial_record["parent_state_hash"] is not None
            or initial_record["delta_digest"] is not None
            or updated_record["operation"] != "update"
            or updated_record["parent_state_hash"] != initial_record["state_hash"]
            or updated_record["state_hash"] == initial_record["state_hash"]
        ):
            raise ProtocolViolation(f"{patient} recursive state lineage is not closed")

        live_initial = probe.initialize_true_state(class_index=class_index, x=x)
        live_delta, live_next_x = _response_delta(class_index=class_index, prior_x=x)
        if live_next_x != expected_next_x:
            raise ProtocolViolation(f"{patient} live response recurrence drifted")
        live_updated = probe.update_private(
            live_initial,
            live_delta,
            hidden_state_at_cut={"x": live_next_x},
            invariant_parameters={"class_index": class_index},
            inference_seed=3,
        )
        _metric_equal(
            initial,
            _state_binding(live_initial),
            f"{patient} live initial state binding",
        )
        _metric_equal(
            updated,
            _state_binding(live_updated),
            f"{patient} live updated state binding",
        )
        verified_states[patient] = {"initial": initial, "updated": updated}
        live_states[patient] = {"initial": live_initial, "updated": live_updated}
        live_deltas[patient] = live_delta
    if (
        verified_states["C0"]["initial"]["record"]["state_hash"]
        == verified_states["C1"]["initial"]["record"]["state_hash"]
    ):
        raise ProtocolViolation("W04 response modifier was lost from state identity")

    cells = report["cells"]
    if type(cells) is not list or len(cells) != 13:
        raise ProtocolViolation("W04 patient-pair sanity requires exactly 13 cells")
    if len({cell.get("cell_id") for cell in cells if type(cell) is dict}) != 13:
        raise ProtocolViolation("W04 patient-pair cell ids are not unique")
    if _cell_root(cells) != report["cell_set_root"]:
        raise ProtocolViolation("W04 cell set root mismatch")
    by_id = {cell["cell_id"]: cell for cell in cells}
    expected_ids = {"W04.patient_pair.collision"}
    for patient in _PATIENTS:
        expected_ids.update(
            {
                f"W04.{patient}.initial.diagnosis",
                f"W04.{patient}.initial.natural_forecast",
                f"W04.{patient}.initial.intervention",
                f"W04.{patient}.update",
                f"W04.{patient}.updated.diagnosis",
                f"W04.{patient}.updated.natural_forecast",
            }
        )
    if set(by_id) != expected_ids:
        raise ProtocolViolation("W04 patient-pair cell coverage mismatch")

    manifest_digest = report["manifest_digest"]

    def verify_diagnosis(cell: dict[str, Any], *, patient: str, cut_alias: str) -> None:
        _closed(
            cell,
            {
                "cell_id",
                "world_slot",
                "patient_alias",
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
        state = verified_states[patient][cut_alias]
        state_hash = state["record"]["state_hash"]
        class_index = int(state["payload"]["representation"]["class_index"])
        if (
            cell["world_slot"] != "W04"
            or cell["patient_alias"] != patient
            or cell["cut_alias"] != cut_alias
            or cell["task"] != "diagnosis"
            or cell["state_hash"] != state_hash
        ):
            raise ProtocolViolation(f"{cell['cell_id']} identity mismatch")
        head = _verify_head(
            cell["candidate_head"],
            operation="diagnose",
            state_hash=state_hash,
            manifest_digest=manifest_digest,
            label=cell["cell_id"],
        )
        live_head = _head_wire(
            probe.diagnose(
                live_states[patient][cut_alias],
                diagnosis_query,
                query_seed=1 if cut_alias == "initial" else 4,
            ),
            diagnosis_query,
        )
        _metric_equal(head, live_head, f"{cell['cell_id']} live diagnosis head")
        target = _closed(
            cell["oracle_target"],
            {"label_order", "probabilities"},
            f"{cell['cell_id']} target",
        )
        expected_target = [float(index == class_index) for index in range(2)]
        if target != {"label_order": ["C0", "C1"], "probabilities": expected_target}:
            raise ProtocolViolation(f"{cell['cell_id']} diagnosis target mismatch")
        probabilities = _diagnosis_probabilities(head, ("C0", "C1"))
        expected_metric = _diagnostic_metric_wire(probabilities, expected_target)
        degraded = _degraded_diagnosis(probabilities, expected_target)
        _metric_equal(cell["metric"], expected_metric, f"{cell['cell_id']} metric")
        _metric_equal(
            cell["degraded_control_metric"],
            degraded,
            f"{cell['cell_id']} degraded metric",
        )
        if (
            expected_metric["accuracy"] != 1.0
            or expected_metric["log_loss"] != 0.0
            or degraded["log_loss"] <= expected_metric["log_loss"]
        ):
            raise ProtocolViolation(f"{cell['cell_id']} metric direction failed")

    def verify_forecast(
        cell: dict[str, Any], *, patient: str, cut_alias: str
    ) -> dict[str, Any]:
        _closed(
            cell,
            {
                "cell_id",
                "world_slot",
                "patient_alias",
                "cut_alias",
                "task",
                "state_hash",
                "candidate_head",
                "production_oracle",
                "analytic_reference_oracle",
                "oracle_comparison",
                "metric",
                "degraded_control_metric",
                "expected_utility",
            },
            cell["cell_id"],
        )
        state = verified_states[patient][cut_alias]
        state_hash = state["record"]["state_hash"]
        representation = state["payload"]["representation"]
        if (
            cell["world_slot"] != "W04"
            or cell["patient_alias"] != patient
            or cell["cut_alias"] != cut_alias
            or cell["task"] != "natural_forecast_mean"
            or cell["state_hash"] != state_hash
        ):
            raise ProtocolViolation(f"{cell['cell_id']} identity mismatch")
        head = _verify_head(
            cell["candidate_head"],
            operation="rollout",
            state_hash=state_hash,
            manifest_digest=manifest_digest,
            label=cell["cell_id"],
        )
        query = cell["candidate_head"]["query"]
        if query.get("plan") != policy_map["no_new_action"].to_wire():
            raise ProtocolViolation(f"{cell['cell_id']} is not a no-action query")
        live_query = RolloutQuery(
            _HORIZON,
            policy_map["no_new_action"],
            ("obs_0",),
            utility_digest,
        )
        live_head = _head_wire(
            probe.rollout(
                live_states[patient][cut_alias],
                live_query,
                query_seed=2 if cut_alias == "initial" else 5,
            ),
            live_query,
        )
        _metric_equal(head, live_head, f"{cell['cell_id']} live rollout head")
        production = _verify_oracle_query_binding(
            cell["production_oracle"], query, f"{cell['cell_id']} judge oracle"
        )
        live_production = _oracle_wire(
            world.judge_true_state_counterfactual(
                {"x": representation["x"]},
                {"class_index": representation["class_index"]},
                policy_map["no_new_action"],
                _HORIZON,
            )
        )
        _metric_equal(
            production, live_production, f"{cell['cell_id']} live judge oracle"
        )
        reference = _verify_oracle_query_binding(
            cell["analytic_reference_oracle"],
            query,
            f"{cell['cell_id']} analytic reference",
        )
        recomputed_reference = _oracle_wire(
            _analytic_true_state_reference(
                class_index=representation["class_index"],
                x=representation["x"],
                policy=policy_map["no_new_action"],
                horizon=_HORIZON,
            )
        )
        _metric_equal(reference, recomputed_reference, f"{cell['cell_id']} reference")
        comparison = _oracle_comparison(production, reference)
        _metric_equal(
            cell["oracle_comparison"], comparison, f"{cell['cell_id']} comparison"
        )
        if comparison["passed"] is not True:
            raise ProtocolViolation(f"{cell['cell_id']} judge/reference disagreement")
        predicted, utility = _point_rollout(head, ("obs_0",))
        truth = _w04_oracle_mean(production)
        expected_metric = _trajectory_metric_wire(predicted, truth)
        degraded = _degraded_trajectory(predicted, truth)
        _metric_equal(cell["metric"], expected_metric, f"{cell['cell_id']} metric")
        _metric_equal(
            cell["degraded_control_metric"],
            degraded,
            f"{cell['cell_id']} degraded metric",
        )
        if (
            utility != cell["expected_utility"]
            or utility != production["expected_utility"]
            or expected_metric["normalized_rmse"] != 0.0
            or degraded["normalized_rmse"] <= 0.0
        ):
            raise ProtocolViolation(f"{cell['cell_id']} metric direction failed")
        return head

    intervention_heads: dict[str, dict[str, dict[str, Any]]] = {}
    intervention_oracles: dict[str, dict[str, dict[str, Any]]] = {}
    intervention_utilities: dict[str, list[float]] = {}
    for patient in _PATIENTS:
        verify_diagnosis(
            by_id[f"W04.{patient}.initial.diagnosis"],
            patient=patient,
            cut_alias="initial",
        )
        verify_diagnosis(
            by_id[f"W04.{patient}.updated.diagnosis"],
            patient=patient,
            cut_alias="updated",
        )
        initial_natural = verify_forecast(
            by_id[f"W04.{patient}.initial.natural_forecast"],
            patient=patient,
            cut_alias="initial",
        )
        verify_forecast(
            by_id[f"W04.{patient}.updated.natural_forecast"],
            patient=patient,
            cut_alias="updated",
        )

        intervention = by_id[f"W04.{patient}.initial.intervention"]
        _closed(
            intervention,
            {
                "cell_id",
                "world_slot",
                "patient_alias",
                "cut_alias",
                "task",
                "state_hash",
                "policy_aliases",
                "candidate_heads",
                "production_oracles",
                "analytic_reference_oracles",
                "oracle_comparisons",
                "trajectory_metrics",
                "predicted_utilities",
                "oracle_utilities",
                "metric",
                "degraded_control_metric",
            },
            intervention["cell_id"],
        )
        initial_state = verified_states[patient]["initial"]
        state_hash = initial_state["record"]["state_hash"]
        representation = initial_state["payload"]["representation"]
        if (
            intervention["world_slot"] != "W04"
            or intervention["patient_alias"] != patient
            or intervention["cut_alias"] != "initial"
            or intervention["task"] != "intervention_mean_utility"
            or intervention["state_hash"] != state_hash
            or intervention["policy_aliases"] != list(_POLICY_ALIASES)
        ):
            raise ProtocolViolation(f"{intervention['cell_id']} identity mismatch")
        for field in (
            "candidate_heads",
            "production_oracles",
            "analytic_reference_oracles",
            "oracle_comparisons",
            "trajectory_metrics",
        ):
            if type(intervention[field]) is not dict or set(intervention[field]) != set(
                _POLICY_ALIASES
            ):
                raise ProtocolViolation(
                    f"{intervention['cell_id']} {field} coverage mismatch"
                )
        predicted_utilities: list[float] = []
        oracle_utilities: list[float] = []
        verified_heads: dict[str, dict[str, Any]] = {}
        verified_oracles: dict[str, dict[str, Any]] = {}
        for alias in _POLICY_ALIASES:
            head = _verify_head(
                intervention["candidate_heads"][alias],
                operation="rollout",
                state_hash=state_hash,
                manifest_digest=manifest_digest,
                label=f"{intervention['cell_id']} {alias}",
            )
            query = intervention["candidate_heads"][alias]["query"]
            if query.get("plan") != policy_map[alias].to_wire():
                raise ProtocolViolation(
                    f"{intervention['cell_id']} {alias} policy mismatch"
                )
            live_query = RolloutQuery(
                _HORIZON,
                policy_map[alias],
                ("obs_0",),
                utility_digest,
            )
            live_head = _head_wire(
                probe.rollout(
                    live_states[patient]["initial"],
                    live_query,
                    query_seed=2,
                ),
                live_query,
            )
            _metric_equal(
                head,
                live_head,
                f"{intervention['cell_id']} {alias} live rollout head",
            )
            production = _verify_oracle_query_binding(
                intervention["production_oracles"][alias],
                query,
                f"{intervention['cell_id']} {alias} judge oracle",
            )
            live_production = _oracle_wire(
                world.judge_true_state_counterfactual(
                    {"x": representation["x"]},
                    {"class_index": representation["class_index"]},
                    policy_map[alias],
                    _HORIZON,
                )
            )
            _metric_equal(
                production,
                live_production,
                f"{intervention['cell_id']} {alias} live judge oracle",
            )
            reference = _verify_oracle_query_binding(
                intervention["analytic_reference_oracles"][alias],
                query,
                f"{intervention['cell_id']} {alias} analytic reference",
            )
            recomputed_reference = _oracle_wire(
                _analytic_true_state_reference(
                    class_index=representation["class_index"],
                    x=representation["x"],
                    policy=policy_map[alias],
                    horizon=_HORIZON,
                )
            )
            _metric_equal(
                reference,
                recomputed_reference,
                f"{intervention['cell_id']} {alias} reference",
            )
            comparison = _oracle_comparison(production, reference)
            _metric_equal(
                intervention["oracle_comparisons"][alias],
                comparison,
                f"{intervention['cell_id']} {alias} comparison",
            )
            if comparison["passed"] is not True:
                raise ProtocolViolation(
                    f"{intervention['cell_id']} {alias} oracle disagreement"
                )
            predicted, predicted_utility = _point_rollout(head, ("obs_0",))
            truth = _w04_oracle_mean(production)
            metric = _trajectory_metric_wire(predicted, truth)
            _metric_equal(
                intervention["trajectory_metrics"][alias],
                metric,
                f"{intervention['cell_id']} {alias} trajectory",
            )
            if metric["normalized_rmse"] != 0.0:
                raise ProtocolViolation(
                    f"{intervention['cell_id']} {alias} trajectory is not exact"
                )
            predicted_utilities.append(predicted_utility)
            oracle_utilities.append(
                _finite(production["expected_utility"], "W04 oracle utility")
            )
            verified_heads[alias] = head
            verified_oracles[alias] = production
        if verified_heads["no_new_action"] != initial_natural:
            raise ProtocolViolation(
                f"{intervention['cell_id']} duplicates inconsistent natural bytes"
            )
        if (
            intervention["predicted_utilities"] != predicted_utilities
            or intervention["oracle_utilities"] != oracle_utilities
        ):
            raise ProtocolViolation(
                f"{intervention['cell_id']} utility extraction mismatch"
            )
        regret = _regret_metric_wire(predicted_utilities, oracle_utilities)
        degraded_regret = _degraded_regret(oracle_utilities)
        _metric_equal(
            intervention["metric"], regret, f"{intervention['cell_id']} regret"
        )
        _metric_equal(
            intervention["degraded_control_metric"],
            degraded_regret,
            f"{intervention['cell_id']} degraded regret",
        )
        if regret["worst_regret"] != 0.0 or degraded_regret["worst_regret"] <= 0.0:
            raise ProtocolViolation(
                f"{intervention['cell_id']} regret direction failed"
            )
        intervention_heads[patient] = verified_heads
        intervention_oracles[patient] = verified_oracles
        intervention_utilities[patient] = oracle_utilities

        update = by_id[f"W04.{patient}.update"]
        _closed(
            update,
            {
                "cell_id",
                "world_slot",
                "patient_alias",
                "cut_alias",
                "task",
                "state_hash",
                "prior_state_hash",
                "parent_state_hash",
                "delta",
                "delta_digest",
            },
            update["cell_id"],
        )
        initial_record = verified_states[patient]["initial"]["record"]
        updated_record = verified_states[patient]["updated"]["record"]
        if (
            update["world_slot"] != "W04"
            or update["patient_alias"] != patient
            or update["cut_alias"] != "initial-to-updated"
            or update["task"] != "recursive_update"
            or update["state_hash"] != updated_record["state_hash"]
            or update["prior_state_hash"] != initial_record["state_hash"]
            or update["parent_state_hash"] != initial_record["state_hash"]
            or digest_json(update["delta"]) != update["delta_digest"]
            or update["delta_digest"] != updated_record["delta_digest"]
        ):
            raise ProtocolViolation(f"{update['cell_id']} does not close lineage")
        _metric_equal(
            update["delta"],
            live_deltas[patient].to_wire(),
            f"{update['cell_id']} live visible delta",
        )
        events = (
            update["delta"].get("events") if type(update["delta"]) is dict else None
        )
        if type(events) is not list or len(events) != 2:
            raise ProtocolViolation(f"{update['cell_id']} response delta is malformed")
        observations = [
            event
            for event in events
            if type(event) is dict
            and event.get("kind") == "observation_available"
            and event.get("payload", {}).get("channel_id") == "obs_0"
        ]
        if (
            len(observations) != 1
            or observations[0]["payload"].get("value")
            != verified_states[patient]["updated"]["payload"]["representation"]["x"]
        ):
            raise ProtocolViolation(
                f"{update['cell_id']} does not bind visible response"
            )

    pair_cell = by_id["W04.patient_pair.collision"]
    _closed(
        pair_cell,
        {
            "cell_id",
            "world_slot",
            "patient_alias",
            "cut_alias",
            "task",
            "shared_observed_scalar",
            "natural_mean_paths",
            "optimal_action_aliases",
            "pair_probe",
            "thresholds",
            "classification",
            "public_attribution",
        },
        "W04 pair cell",
    )
    if (
        pair_cell["world_slot"] != "W04"
        or pair_cell["patient_alias"] != "C0-vs-C1"
        or pair_cell["cut_alias"] != "initial-pair"
        or pair_cell["task"] != "dangerous_collision"
        or pair_cell["shared_observed_scalar"] != x
        or pair_cell["thresholds"] != _PAIR_THRESHOLDS
    ):
        raise ProtocolViolation("W04 pair cell identity mismatch")
    expected_paths = {}
    for patient in _PATIENTS:
        path, _utility = _point_rollout(
            intervention_heads[patient]["no_new_action"], ("obs_0",)
        )
        expected_paths[patient] = path
    if (
        pair_cell["natural_mean_paths"] != expected_paths
        or expected_paths["C0"] != expected_paths["C1"]
    ):
        raise ProtocolViolation("W04 pair does not preserve identical natural course")
    expected_best = {
        patient: _POLICY_ALIASES[
            max(range(3), key=intervention_utilities[patient].__getitem__)
        ]
        for patient in _PATIENTS
    }
    if pair_cell["optimal_action_aliases"] != expected_best or expected_best != {
        "C0": "single_A1",
        "C1": "single_A2",
    }:
        raise ProtocolViolation("W04 pair does not have opposite optimal treatment")
    expected_probe = PairProbe(
        pair_id="W04.patient-bound.opposite-treatment-response",
        state_hash_a=verified_states["C0"]["initial"]["record"]["state_hash"],
        state_hash_b=verified_states["C1"]["initial"]["record"]["state_hash"],
        candidate_signature_a=_behaviour_signature(
            intervention_heads["C0"], _POLICY_ALIASES
        ),
        candidate_signature_b=_behaviour_signature(
            intervention_heads["C1"], _POLICY_ALIASES
        ),
        oracle_signature_a=_oracle_signature(
            intervention_oracles["C0"], _POLICY_ALIASES
        ),
        oracle_signature_b=_oracle_signature(
            intervention_oracles["C1"], _POLICY_ALIASES
        ),
        oracle_action_values_a=tuple(intervention_utilities["C0"]),
        oracle_action_values_b=tuple(intervention_utilities["C1"]),
        information_relation=InformationRelation.NONIDENTIFIED.value,
        intervention_identifiable=False,
    )
    stored_probe = _pair_probe_from_wire(pair_cell["pair_probe"])
    if _pair_probe_wire(stored_probe) != _pair_probe_wire(expected_probe):
        raise ProtocolViolation("W04 pair probe is not collector-derived")
    expected_classification = _classification_wire(expected_probe)
    _metric_equal(
        pair_cell["classification"],
        expected_classification,
        "W04 pair classification",
    )
    if (
        expected_classification["exact_collision"] is not False
        or expected_classification["functional_near_collision"] is not False
        or expected_classification["dangerous_collision"] is not False
        or expected_classification["attributable_collision"] is not False
        or expected_classification["candidate_distance"]
        < _PAIR_THRESHOLDS["candidate_split_delta"]
        or expected_classification["oracle_distance"]
        < _PAIR_THRESHOLDS["oracle_distinguishable_delta"]
        or expected_classification["cross_applied_regret"]
        < _PAIR_THRESHOLDS["catastrophic_margin"]
    ):
        raise ProtocolViolation("W04 patient-bound state failed collision sanity")
    attribution = _closed(
        pair_cell["public_attribution"],
        {
            "candidate_failure_claimed",
            "attribution_eligible",
            "privileged_truth_required",
            "basis",
        },
        "W04 public attribution",
    )
    if attribution != {
        "candidate_failure_claimed": False,
        "attribution_eligible": False,
        "privileged_truth_required": True,
        "basis": "direct-true-state-pair-without-candidate-visible-history",
    }:
        raise ProtocolViolation("W04 privileged pair was misattributed publicly")

    summary = _closed(
        report["verification_summary"],
        {
            "status",
            "cell_count",
            "state_binding_count",
            "analytic_reference_comparison_count",
            "source_distinct_oracle_certification_count",
            "ledger_credit",
            "formalization_blockers",
        },
        "W04 verification summary",
    )
    if summary != {
        "status": "VALID_PRE_FREEZE_W04_PATIENT_PAIR_SANITY_BUNDLE",
        "cell_count": 13,
        "state_binding_count": 4,
        "analytic_reference_comparison_count": 10,
        "source_distinct_oracle_certification_count": 0,
        "ledger_credit": 0,
        "formalization_blockers": _FORMALIZATION_BLOCKERS,
    }:
        raise ProtocolViolation("W04 verification summary was overstated")


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run or verify the PRE-FREEZE W04 patient-pair evaluator."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="collect a new immutable bundle")
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument(
        "--source-artifact", type=Path, default=DEFAULT_W04_ARTIFACT
    )
    run_parser.add_argument("--x", type=float, default=0.4)

    verify_parser = subparsers.add_parser("verify", help="verify an existing bundle")
    verify_parser.add_argument("--input", type=Path, required=True)
    verify_parser.add_argument("--source-artifact", type=Path)
    verify_parser.add_argument("--replay-runtime", action="store_true")
    args = parser.parse_args()

    if args.command == "run":
        report = run_w04_upper_bound_sanity(
            source_artifact=args.source_artifact,
            x=args.x,
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        try:
            with args.output.open("xb") as stream:
                stream.write(canonical_json_bytes(report))
        except FileExistsError as exc:
            raise SystemExit(f"refusing to overwrite {args.output}") from exc
        return 0

    try:
        raw = args.input.read_bytes()
        report = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read W04 bundle: {args.input}") from exc
    if canonical_json_bytes(report) != raw:
        raise SystemExit("W04 bundle is not canonical JSON")
    verify_w04_upper_bound_sanity(
        report,
        source_artifact=args.source_artifact,
        replay_runtime=args.replay_runtime,
    )
    return 0


__all__ = [
    "DEFAULT_W04_ARTIFACT",
    "run_w04_upper_bound_sanity",
    "verify_w04_upper_bound_sanity",
]


if __name__ == "__main__":
    raise SystemExit(_main())
