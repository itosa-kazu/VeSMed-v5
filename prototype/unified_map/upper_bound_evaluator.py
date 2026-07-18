"""Typed PRE-FREEZE evaluator for privileged true-state sanity probes.

This module deliberately does *not* reuse the candidate headline evaluator.
The B01 true-state probe is privileged, has zero experiment credit, and must
never enter candidate denominators or a benchmark-freeze decision.  Its job is
smaller: prove that a real patient-world execution can be replayed, that every
task head consumes the same sealed state, that the judge oracle and metric
directions agree, and that a recursive update closes over the prior state.

The first implemented adapter is W01.  Its wire format is intentionally rich:
it carries stable state-hash preimages, exact query and response wires, exact
judge/reference oracle outputs, and collector-derived metrics.  The verifier
recomputes every metric and state hash; a caller cannot preserve a reported
zero loss by merely re-signing altered raw bytes.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
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
from .metrics import diagnostic_metrics, trajectory_metrics, treatment_regret
from .oracle_certification import (
    NumericTolerance,
    compare_canonical_outputs,
    oracle_output_wire,
)
from .schema import DiagnosisQuery, RolloutQuery
from .state import StateClass, StatePayload, compute_state_hash
from .true_state_probe import (
    W01TrueStateUpperBoundProbe,
    _w01_factual_delta,
    run_w01_vertical_slice,
)
from .worlds.base import CounterfactualOracle, WorldSplit
from .worlds.w01 import W01World


PROTOCOL = "ucm-pre-freeze-upper-bound-sanity/1"
STATE_BINDING_PROTOCOL = "ucm-upper-bound-stable-state-binding/1"
STATUS_CHAIN = {
    "benchmark_status": "PRE-FREEZE",
    "experiment_status": "NOT_COUNT_ELIGIBLE",
    "eligibility": "upper_bound_only",
    "privileged": True,
    "freeze_grade": False,
    "formal_run": False,
    "candidate_eligible": False,
    "ledger_credit": 0,
    "analysis_weight": 0.0,
    "benchmark_freeze_evidence": False,
    "candidate_gate": "NOT_APPLICABLE",
}
DEFAULT_W01_ARTIFACT = Path(
    "results/unified_map/pre_freeze/20260717-w01-true-state-probe/vertical-slice.json"
)


def _closed(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ProtocolViolation(f"{label} must be a closed object")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 71 or not value.startswith("sha256:"):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} must be hexadecimal") from exc
    return value


def _finite(value: object, label: str) -> float:
    if type(value) not in {int, float} or not np.isfinite(float(value)):
        raise ProtocolViolation(f"{label} must be finite numeric")
    return float(value)


def _state_binding(state: Any) -> dict[str, Any]:
    """Return the deterministic part of a sealed state and its hash preimage.

    ``state_instance_id`` is intentionally excluded: it is an execution nonce
    and is not an input to ``compute_state_hash``.  Every omitted field is
    therefore irrelevant to stable state identity, not silently discarded.
    """

    payload = state.candidate_input.payload
    if payload.codec != "canonical-json-v1":
        raise ProtocolViolation("W01 sanity requires a canonical JSON state")
    try:
        representation = json.loads(payload.payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("W01 state payload is not valid JSON") from exc
    if canonical_json_bytes(representation) != payload.payload:
        raise ProtocolViolation("W01 state payload is not canonical")
    record = state.record
    return {
        "protocol": STATE_BINDING_PROTOCOL,
        "payload": {
            "codec": payload.codec,
            "schema_version": payload.schema_version,
            "state_class": payload.state_class.value,
            "representation": representation,
        },
        "record": {
            "state_id": record.state_id,
            "state_hash": record.state_hash,
            "parent_state_hash": record.parent_state_hash,
            "operation": record.operation,
            "delta_digest": record.delta_digest,
            "candidate_bundle_digest": record.candidate_bundle_digest,
            "model_digest": record.model_digest,
            "scope_digest": record.scope_digest,
            "catalog_digest": record.catalog_digest,
            "as_of_available_at": record.as_of_available_at,
            "payload_size_bytes": record.payload_size_bytes,
        },
    }


def _verify_state_binding(value: object, label: str) -> dict[str, Any]:
    binding = _closed(value, {"protocol", "payload", "record"}, label)
    if binding["protocol"] != STATE_BINDING_PROTOCOL:
        raise ProtocolViolation(f"{label} protocol mismatch")
    payload_wire = _closed(
        binding["payload"],
        {"codec", "schema_version", "state_class", "representation"},
        f"{label} payload",
    )
    if payload_wire["codec"] != "canonical-json-v1":
        raise ProtocolViolation(f"{label} payload codec mismatch")
    try:
        state_class = StateClass(payload_wire["state_class"])
    except (TypeError, ValueError) as exc:
        raise ProtocolViolation(f"{label} state_class is invalid") from exc
    payload = StatePayload.from_json(
        payload_wire["representation"],
        schema_version=payload_wire["schema_version"],
        state_class=state_class,
    )
    record = _closed(
        binding["record"],
        {
            "state_id",
            "state_hash",
            "parent_state_hash",
            "operation",
            "delta_digest",
            "candidate_bundle_digest",
            "model_digest",
            "scope_digest",
            "catalog_digest",
            "as_of_available_at",
            "payload_size_bytes",
        },
        f"{label} record",
    )
    for name in (
        "state_hash",
        "candidate_bundle_digest",
        "model_digest",
        "scope_digest",
        "catalog_digest",
    ):
        _digest(record[name], f"{label} {name}")
    for name in ("parent_state_hash", "delta_digest"):
        if record[name] is not None:
            _digest(record[name], f"{label} {name}")
    if type(record["as_of_available_at"]) is not int:
        raise ProtocolViolation(f"{label} as_of must be integer")
    if record["payload_size_bytes"] != len(payload.payload):
        raise ProtocolViolation(f"{label} payload byte count mismatch")
    expected = compute_state_hash(
        payload,
        candidate_bundle_digest=record["candidate_bundle_digest"],
        model_digest=record["model_digest"],
        scope_digest=record["scope_digest"],
        catalog_digest=record["catalog_digest"],
        as_of_available_at=record["as_of_available_at"],
    )
    if record["state_hash"] != expected:
        raise ProtocolViolation(f"{label} state hash does not match its preimage")
    if record["state_id"] != "ucm-state:" + expected[7:23]:
        raise ProtocolViolation(f"{label} state_id does not match state hash")
    return binding


def _head_wire(execution: Any, query: Any) -> dict[str, Any]:
    query_wire = query.to_wire()
    head = execution.to_wire()
    if digest_json(query_wire) != head["query_digest"]:
        raise ProtocolViolation("head query digest mismatch during collection")
    return {"query": query_wire, "execution": head}


def _verify_head(
    value: object,
    *,
    operation: str,
    state_hash: str,
    manifest_digest: str,
    label: str,
) -> dict[str, Any]:
    row = _closed(value, {"query", "execution"}, label)
    head = _closed(
        row["execution"],
        {
            "protocol",
            "operation",
            "consumed_state_hash",
            "query_digest",
            "manifest_digest",
            "privileged",
            "eligibility",
            "response",
        },
        f"{label} execution",
    )
    if (
        head["protocol"] != "ucm-true-state-head-execution/1"
        or head["operation"] != operation
        or head["consumed_state_hash"] != state_hash
        or head["manifest_digest"] != manifest_digest
        or head["privileged"] is not True
        or head["eligibility"] != "upper_bound_only"
    ):
        raise ProtocolViolation(f"{label} head binding mismatch")
    if digest_json(row["query"]) != head["query_digest"]:
        raise ProtocolViolation(f"{label} query digest mismatch")
    response = _closed(head["response"], {"protocol", "operation", "result"}, f"{label} response")
    if (
        response["protocol"] != "ucm-candidate-response/1"
        or response["operation"] != operation
        or type(response["result"]) is not dict
        or response["result"].get("status") != "ok"
    ):
        raise ProtocolViolation(f"{label} response is not an ok {operation} result")
    return row


def _diagnosis_probabilities(head: dict[str, Any], label_order: tuple[str, ...]) -> list[float]:
    result = head["execution"]["response"]["result"]
    probabilities = result.get("probabilities")
    if type(probabilities) is not dict or set(probabilities) != set(label_order):
        raise ProtocolViolation("diagnosis probability labels mismatch")
    values = [_finite(probabilities[label], f"diagnosis probability {label}") for label in label_order]
    if any(value < 0.0 or value > 1.0 for value in values) or not np.isclose(
        sum(values), 1.0, atol=1e-12, rtol=0.0
    ):
        raise ProtocolViolation("diagnosis probabilities are not normalized")
    return values


def _point_rollout(
    head: dict[str, Any], requested: tuple[str, ...]
) -> tuple[list[list[float]], float]:
    result = head["execution"]["response"]["result"]
    predictions = result.get("observable_predictions")
    if type(predictions) is not dict or set(predictions) != set(requested):
        raise ProtocolViolation("rollout observable set mismatch")
    columns: list[list[float]] = []
    horizon: int | None = None
    for observable in requested:
        distribution = predictions[observable]
        if type(distribution) is not dict or set(distribution) != {
            "family",
            "horizon",
            "values",
        }:
            raise ProtocolViolation("W01 rollout distribution is not closed")
        if distribution["family"] != "point_mass":
            raise ProtocolViolation("W01 rollout must be a point mean projection")
        if type(distribution["horizon"]) is not int or distribution["horizon"] <= 0:
            raise ProtocolViolation("W01 rollout horizon is invalid")
        if horizon is None:
            horizon = distribution["horizon"]
        elif horizon != distribution["horizon"]:
            raise ProtocolViolation("W01 rollout horizons disagree")
        values = distribution["values"]
        if type(values) is not list or len(values) != horizon:
            raise ProtocolViolation("W01 rollout values do not match horizon")
        columns.append([_finite(item, "W01 rollout value") for item in values])
    utility = result.get("utility_prediction")
    if type(utility) is not dict or set(utility) != {"family", "value"}:
        raise ProtocolViolation("W01 utility prediction is not closed")
    if utility["family"] != "point_mass":
        raise ProtocolViolation("W01 utility must be a point expectation")
    matrix = np.asarray(columns, dtype=float).T.tolist()
    return matrix, _finite(utility["value"], "W01 expected utility")


def _oracle_mean_matrix(
    oracle: dict[str, Any], requested: tuple[str, ...]
) -> list[list[float]]:
    distribution = oracle.get("observation_distribution")
    if type(distribution) is not dict or distribution.get("family") != "joint-gaussian":
        raise ProtocolViolation("W01 oracle observation family mismatch")
    steps = distribution.get("steps")
    if type(steps) is not list or not steps:
        raise ProtocolViolation("W01 oracle steps are absent")
    point = distribution.get("obs_2_point_mass")
    rows: list[list[float]] = []
    for step in steps:
        if type(step) is not dict or type(step.get("mean")) is not list or len(step["mean"]) != 2:
            raise ProtocolViolation("W01 oracle step mean is malformed")
        row: list[float] = []
        for observable in requested:
            if observable == "obs_0":
                raw = step["mean"][0]
            elif observable == "obs_1":
                raw = step["mean"][1]
            elif observable == "obs_2":
                raw = point
            else:
                raise ProtocolViolation("W01 oracle requested unknown observable")
            row.append(_finite(raw, "W01 oracle mean"))
        rows.append(row)
    return rows


def _verify_oracle_query_binding(
    oracle: object, query: dict[str, Any], label: str
) -> dict[str, Any]:
    wire = _closed(
        oracle,
        {
            "protocol",
            "policy",
            "horizon",
            "observation_distribution",
            "latent_distribution",
            "outcome_distribution",
            "expected_utility",
        },
        label,
    )
    if (
        wire["protocol"] != "ucm-oracle-semantic-output/1"
        or query.get("protocol") != "ucm-rollout-query/1"
        or wire["policy"] != query.get("plan")
        or wire["horizon"] != query.get("horizon")
    ):
        raise ProtocolViolation(f"{label} does not bind the exact rollout query")
    _finite(wire["expected_utility"], f"{label} expected utility")
    return wire


def _diagnostic_metric_wire(probabilities: list[float], target: list[float]) -> dict[str, Any]:
    if len(probabilities) != len(target) or target.count(1.0) != 1 or any(
        value not in {0.0, 1.0} for value in target
    ):
        raise ProtocolViolation("W01 diagnostic target must be one-hot")
    metric = diagnostic_metrics([probabilities], [target.index(1.0)])
    return asdict(metric)


def _trajectory_metric_wire(predicted: list[list[float]], oracle: list[list[float]]) -> dict[str, Any]:
    metric = trajectory_metrics(predicted, oracle, [1.0] * len(oracle[0]))
    return asdict(metric)


def _regret_metric_wire(predicted: list[float], oracle: list[float]) -> dict[str, Any]:
    metric = treatment_regret(
        [predicted], [oracle], catastrophic_margin=0.25
    )
    wire = asdict(metric)
    wire["chosen_actions"] = list(metric.chosen_actions)
    return wire


def _degraded_diagnosis(probabilities: list[float], target: list[float]) -> dict[str, Any]:
    if len(probabilities) != 2:
        raise ProtocolViolation("W01 degraded diagnosis expects two labels")
    return _diagnostic_metric_wire(list(reversed(probabilities)), target)


def _degraded_trajectory(predicted: list[list[float]], oracle: list[list[float]]) -> dict[str, Any]:
    shifted = deepcopy(predicted)
    for row in shifted:
        row[0] += 0.25
    return _trajectory_metric_wire(shifted, oracle)


def _degraded_regret(oracle: list[float]) -> dict[str, Any]:
    worst = int(np.argmin(np.asarray(oracle, dtype=float)))
    adversarial = [0.0] * len(oracle)
    adversarial[worst] = 1.0
    return _regret_metric_wire(adversarial, oracle)


def _oracle_wire(value: CounterfactualOracle) -> dict[str, Any]:
    return oracle_output_wire(value, include_numerical_diagnostics=False)


def _oracle_comparison(
    production: dict[str, Any], reference: dict[str, Any]
) -> dict[str, Any]:
    return compare_canonical_outputs(
        production,
        reference,
        NumericTolerance(absolute=1e-12, relative=1e-12),
    ).to_wire()


def _cell_root(cells: list[dict[str, Any]]) -> str:
    identities = [
        {
            "cell_id": cell["cell_id"],
            "cut_alias": cell["cut_alias"],
            "task": cell["task"],
            "cell_digest": digest_json(cell),
        }
        for cell in cells
    ]
    identities.sort(key=lambda item: item["cell_id"].encode("utf-8"))
    return digest_json(
        {
            "protocol": "ucm-upper-bound-cell-set-root/1",
            "identities": identities,
        }
    )


def compute_upper_bound_bundle_root(value: dict[str, Any]) -> str:
    """Compute the non-authorizing integrity root for a sanity bundle."""

    if type(value) is not dict:
        raise ProtocolViolation("upper-bound bundle must be an object")
    body = {key: deepcopy(item) for key, item in value.items() if key != "bundle_root"}
    return digest_json(
        {
            "protocol": "ucm-upper-bound-sanity-bundle-root/1",
            "body": body,
        }
    )


def _attach_bundle_root(value: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(value)
    result["bundle_root"] = compute_upper_bound_bundle_root(result)
    return result


def run_w01_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W01_ARTIFACT,
    generator_seed: int = 92011,
    episode_index: int = 13,
) -> dict[str, Any]:
    """Execute and verify the first real upper-bound evaluator slice."""

    source_path = Path(source_artifact)
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(f"W01 source artifact is unavailable: {source_path}") from exc
    try:
        source_wire = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("W01 source artifact is not JSON") from exc
    if canonical_json_bytes(source_wire) != source_bytes:
        raise ProtocolViolation("W01 source artifact is not canonical JSON")
    replay = run_w01_vertical_slice(
        generator_seed=generator_seed, episode_index=episode_index
    )
    replay_bytes = canonical_json_bytes(replay)
    if source_bytes != replay_bytes:
        raise ProtocolViolation("W01 committed vertical slice does not byte-replay")

    world = W01World()
    probe = W01TrueStateUpperBoundProbe(world)
    episode = world.generate_episode(WorldSplit.TRAIN, generator_seed, episode_index)
    initial = probe.initialize_private(episode)
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    diagnosis = probe.diagnose(initial, diagnosis_query, query_seed=1)
    utility_digest = digest_json(
        {
            "protocol": "ucm-w01-upper-bound-utility/1",
            "catalog_digest": world.catalog.digest,
            "horizon": 4,
            "utility": "discounted-quadratic-cost",
        }
    )
    requested = ("obs_0", "obs_1", "obs_2")
    policy_aliases = ("no_new_action", "single_A1", "single_A2")
    policies = world.policy_set(4)[:3]
    rollout_heads: dict[str, dict[str, Any]] = {}
    production_oracles: dict[str, dict[str, Any]] = {}
    reference_oracles: dict[str, dict[str, Any]] = {}
    oracle_comparisons: dict[str, dict[str, Any]] = {}
    for alias, policy in zip(policy_aliases, policies, strict=True):
        query = RolloutQuery(4, policy, requested, utility_digest)
        execution = probe.rollout(initial, query, query_seed=2)
        rollout_heads[alias] = _head_wire(execution, query)
        production = _oracle_wire(
            world.judge_true_state_counterfactual(
                episode.hidden_state_at_cut,
                episode.invariant_parameters,
                policy,
                4,
            )
        )
        reference = _oracle_wire(
            world.reference_counterfactual(episode, policy, 4, oracle_seed=2)
        )
        production_oracles[alias] = production
        reference_oracles[alias] = reference
        oracle_comparisons[alias] = _oracle_comparison(production, reference)

    initial_binding = _state_binding(initial)
    initial_hash = initial.record.state_hash
    manifest_digest = probe.manifest.digest
    diagnosis_head = _head_wire(diagnosis, diagnosis_query)
    diagnosis_probabilities = _diagnosis_probabilities(
        diagnosis_head, world.catalog.diagnostic_labels
    )
    diagnosis_target = [
        float(episode.diagnostic_target[label])
        for label in world.catalog.diagnostic_labels
    ]
    diagnosis_metric = _diagnostic_metric_wire(
        diagnosis_probabilities, diagnosis_target
    )

    natural_predicted, natural_utility = _point_rollout(
        rollout_heads["no_new_action"], requested
    )
    natural_oracle = _oracle_mean_matrix(
        production_oracles["no_new_action"], requested
    )
    natural_metric = _trajectory_metric_wire(natural_predicted, natural_oracle)

    predicted_utilities: list[float] = []
    oracle_utilities: list[float] = []
    intervention_trajectory: dict[str, Any] = {}
    for alias in policy_aliases:
        predicted, utility = _point_rollout(rollout_heads[alias], requested)
        oracle_mean = _oracle_mean_matrix(production_oracles[alias], requested)
        predicted_utilities.append(utility)
        oracle_utilities.append(
            _finite(production_oracles[alias]["expected_utility"], "oracle utility")
        )
        intervention_trajectory[alias] = _trajectory_metric_wire(
            predicted, oracle_mean
        )

    delta = _w01_factual_delta(episode)
    updated = probe.update(initial, delta, inference_seed=3)
    updated_binding = _state_binding(updated)
    updated_diagnosis = probe.diagnose(updated, diagnosis_query, query_seed=4)
    updated_query = RolloutQuery(4, policies[0], requested, utility_digest)
    updated_rollout = probe.rollout(updated, updated_query, query_seed=5)
    updated_diagnosis_head = _head_wire(updated_diagnosis, diagnosis_query)
    updated_rollout_head = _head_wire(updated_rollout, updated_query)
    updated_representation = updated_binding["payload"]["representation"]
    updated_target = [
        float(updated_representation["class_index"] == index) for index in range(2)
    ]
    updated_probabilities = _diagnosis_probabilities(
        updated_diagnosis_head, world.catalog.diagnostic_labels
    )
    updated_judge = _oracle_wire(
        world.judge_true_state_counterfactual(
            {"x": updated_representation["x"]},
            {"class_index": updated_representation["class_index"]},
            policies[0],
            4,
        )
    )
    updated_predicted, _updated_utility = _point_rollout(
        updated_rollout_head, requested
    )
    updated_oracle_mean = _oracle_mean_matrix(updated_judge, requested)

    cells = [
        {
            "cell_id": "W01.initial.diagnosis",
            "world_slot": "W01",
            "cut_alias": "initial",
            "task": "diagnosis",
            "state_hash": initial_hash,
            "candidate_head": diagnosis_head,
            "oracle_target": {
                "label_order": list(world.catalog.diagnostic_labels),
                "probabilities": diagnosis_target,
            },
            "metric": diagnosis_metric,
            "degraded_control_metric": _degraded_diagnosis(
                diagnosis_probabilities, diagnosis_target
            ),
        },
        {
            "cell_id": "W01.initial.natural_forecast",
            "world_slot": "W01",
            "cut_alias": "initial",
            "task": "natural_forecast_mean",
            "state_hash": initial_hash,
            "candidate_head": rollout_heads["no_new_action"],
            "production_oracle": production_oracles["no_new_action"],
            "reference_oracle": reference_oracles["no_new_action"],
            "oracle_comparison": oracle_comparisons["no_new_action"],
            "metric": natural_metric,
            "degraded_control_metric": _degraded_trajectory(
                natural_predicted, natural_oracle
            ),
            "expected_utility": natural_utility,
        },
        {
            "cell_id": "W01.initial.intervention",
            "world_slot": "W01",
            "cut_alias": "initial",
            "task": "intervention_mean_utility",
            "state_hash": initial_hash,
            "policy_aliases": list(policy_aliases),
            "candidate_heads": rollout_heads,
            "production_oracles": production_oracles,
            "reference_oracles": reference_oracles,
            "oracle_comparisons": oracle_comparisons,
            "trajectory_metrics": intervention_trajectory,
            "predicted_utilities": predicted_utilities,
            "oracle_utilities": oracle_utilities,
            "metric": _regret_metric_wire(predicted_utilities, oracle_utilities),
            "degraded_control_metric": _degraded_regret(oracle_utilities),
        },
        {
            "cell_id": "W01.update",
            "world_slot": "W01",
            "cut_alias": "initial-to-updated",
            "task": "recursive_update",
            "state_hash": updated.record.state_hash,
            "prior_state_hash": initial.record.state_hash,
            "parent_state_hash": updated.record.parent_state_hash,
            "delta": delta.to_wire(),
            "delta_digest": digest_json(delta.to_wire()),
        },
        {
            "cell_id": "W01.updated.diagnosis",
            "world_slot": "W01",
            "cut_alias": "updated",
            "task": "diagnosis",
            "state_hash": updated.record.state_hash,
            "candidate_head": updated_diagnosis_head,
            "oracle_target": {
                "label_order": list(world.catalog.diagnostic_labels),
                "probabilities": updated_target,
            },
            "metric": _diagnostic_metric_wire(
                updated_probabilities, updated_target
            ),
            "degraded_control_metric": _degraded_diagnosis(
                updated_probabilities, updated_target
            ),
        },
        {
            "cell_id": "W01.updated.natural_forecast",
            "world_slot": "W01",
            "cut_alias": "updated",
            "task": "natural_forecast_mean",
            "state_hash": updated.record.state_hash,
            "candidate_head": updated_rollout_head,
            "production_oracle": updated_judge,
            "reference_oracle": None,
            "oracle_comparison": None,
            "metric": _trajectory_metric_wire(
                updated_predicted, updated_oracle_mean
            ),
            "degraded_control_metric": _degraded_trajectory(
                updated_predicted, updated_oracle_mean
            ),
            "expected_utility": _updated_utility,
        },
    ]
    body = {
        "protocol": PROTOCOL,
        "bundle_kind": "phase2_privileged_probe_evaluator",
        "world_slot": "W01",
        "status_chain": deepcopy(STATUS_CHAIN),
        "scope_statement": {
            "mean_trajectory_only": True,
            "expected_utility_only": True,
            "proper_distribution_score_claimed": False,
            "candidate_performance_claimed": False,
            "formal_b01_claimed": False,
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
        "manifest_digest": manifest_digest,
        "fixture": {
            "split": WorldSplit.TRAIN.value,
            "generator_seed": generator_seed,
            "episode_index": episode_index,
            "public_history_digest": episode.public_history.digest,
        },
        "states": {
            "initial": initial_binding,
            "updated": updated_binding,
        },
        "cells": cells,
        "cell_set_root": _cell_root(cells),
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_SANITY_BUNDLE",
            "cell_count": len(cells),
            "state_binding_count": 2,
            "source_distinct_oracle_cells": 2,
            "ledger_credit": 0,
            "formalization_blockers": [
                "not-a-frozen-expected-cell-corpus",
                "privileged-upper-bound-only",
                "updated-cut-reference-oracle-not-source-distinct",
                "mean-and-expected-utility-projections-only",
            ],
        },
    }
    result = _attach_bundle_root(body)
    verify_w01_upper_bound_sanity(result)
    return result


def _metric_equal(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    if digest_json(actual) != digest_json(expected):
        raise ProtocolViolation(f"{label} is not collector-derived from raw bytes")


def verify_w01_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    """Recompute every W01 state/query/oracle/metric claim fail-closed."""

    keys = {
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
    }
    report = _closed(value, keys, "upper-bound sanity report")
    validate_json_like(report)
    if (
        report["protocol"] != PROTOCOL
        or report["bundle_kind"] != "phase2_privileged_probe_evaluator"
        or report["world_slot"] != "W01"
        or report["status_chain"] != STATUS_CHAIN
    ):
        raise ProtocolViolation("upper-bound status or identity was rewritten")
    if report["bundle_root"] != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation("upper-bound bundle root mismatch")
    scope = _closed(
        report["scope_statement"],
        {
            "mean_trajectory_only",
            "expected_utility_only",
            "proper_distribution_score_claimed",
            "candidate_performance_claimed",
            "formal_b01_claimed",
        },
        "scope statement",
    )
    if scope != {
        "mean_trajectory_only": True,
        "expected_utility_only": True,
        "proper_distribution_score_claimed": False,
        "candidate_performance_claimed": False,
        "formal_b01_claimed": False,
    }:
        raise ProtocolViolation("upper-bound scope was overstated")
    manifest_digest = digest_json(report["manifest"])
    if manifest_digest != report["manifest_digest"]:
        raise ProtocolViolation("upper-bound manifest digest mismatch")
    manifest = report["manifest"]
    if (
        type(manifest) is not dict
        or manifest.get("world_slot") != "W01"
        or manifest.get("baseline_id") != "B01"
        or manifest.get("privileged") is not True
        or manifest.get("eligibility") != "upper_bound_only"
        or manifest.get("freeze_grade") is not False
    ):
        raise ProtocolViolation("upper-bound manifest eligibility mismatch")
    fixture = _closed(
        report["fixture"],
        {"split", "generator_seed", "episode_index", "public_history_digest"},
        "W01 fixture",
    )
    if (
        fixture["split"] != WorldSplit.TRAIN.value
        or type(fixture["generator_seed"]) is not int
        or fixture["generator_seed"] < 0
        or type(fixture["episode_index"]) is not int
        or fixture["episode_index"] < 0
    ):
        raise ProtocolViolation("W01 fixture identity is invalid")
    _digest(fixture["public_history_digest"], "W01 public history digest")
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
        "source anchor",
    )
    _digest(source["artifact_digest"], "source artifact digest")
    _digest(source["replay_digest"], "source replay digest")
    if (
        source["artifact_digest"] != source["replay_digest"]
        or source["byte_identical_replay"] is not True
        or source["artifact_protocol"]
        != "ucm-phase2-true-state-vertical-slice/1"
        or type(source["artifact_bytes"]) is not int
        or source["artifact_bytes"] <= 0
    ):
        raise ProtocolViolation("source artifact replay anchor mismatch")
    if source_artifact is not None:
        source_path = Path(source_artifact)
        try:
            raw = source_path.read_bytes()
        except OSError as exc:
            raise ProtocolViolation("bound source artifact is unavailable") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("bound source artifact is not JSON") from exc
        if canonical_json_bytes(decoded) != raw:
            raise ProtocolViolation("bound source artifact is not canonical")
        if digest_bytes(raw) != source["artifact_digest"] or len(raw) != source["artifact_bytes"]:
            raise ProtocolViolation("bound source artifact bytes do not match the report")
        if replay_runtime:
            replay_bytes = canonical_json_bytes(
                run_w01_vertical_slice(
                    generator_seed=fixture["generator_seed"],
                    episode_index=fixture["episode_index"],
                )
            )
            if replay_bytes != raw or digest_bytes(replay_bytes) != source["replay_digest"]:
                raise ProtocolViolation("bound source artifact does not replay live")

    states = _closed(report["states"], {"initial", "updated"}, "states")
    initial = _verify_state_binding(states["initial"], "initial state")
    updated = _verify_state_binding(states["updated"], "updated state")
    initial_record = initial["record"]
    updated_record = updated["record"]
    if (
        initial_record["operation"] != "initialize"
        or initial_record["parent_state_hash"] is not None
        or initial_record["delta_digest"] is not None
        or updated_record["operation"] != "update"
        or updated_record["parent_state_hash"] != initial_record["state_hash"]
        or updated_record["state_hash"] == initial_record["state_hash"]
    ):
        raise ProtocolViolation("W01 recursive state lineage is not closed")

    cells = report["cells"]
    if type(cells) is not list or len(cells) != 6:
        raise ProtocolViolation("W01 sanity requires exactly six cells")
    if len({cell.get("cell_id") for cell in cells if type(cell) is dict}) != 6:
        raise ProtocolViolation("W01 sanity cell ids are not unique")
    if _cell_root(cells) != report["cell_set_root"]:
        raise ProtocolViolation("W01 cell set root mismatch")
    by_id = {cell["cell_id"]: cell for cell in cells}
    expected_ids = {
        "W01.initial.diagnosis",
        "W01.initial.natural_forecast",
        "W01.initial.intervention",
        "W01.update",
        "W01.updated.diagnosis",
        "W01.updated.natural_forecast",
    }
    if set(by_id) != expected_ids:
        raise ProtocolViolation("W01 sanity cell coverage mismatch")

    def verify_diagnosis(
        cell: dict[str, Any], state_hash: str, state_representation: dict[str, Any]
    ) -> None:
        required = {
            "cell_id",
            "world_slot",
            "cut_alias",
            "task",
            "state_hash",
            "candidate_head",
            "oracle_target",
            "metric",
            "degraded_control_metric",
        }
        _closed(cell, required, cell["cell_id"])
        if cell["world_slot"] != "W01" or cell["task"] != "diagnosis" or cell["state_hash"] != state_hash:
            raise ProtocolViolation("W01 diagnosis cell identity mismatch")
        head = _verify_head(
            cell["candidate_head"],
            operation="diagnose",
            state_hash=state_hash,
            manifest_digest=manifest_digest,
            label=cell["cell_id"],
        )
        target = _closed(
            cell["oracle_target"], {"label_order", "probabilities"}, "diagnosis target"
        )
        labels = target["label_order"]
        probabilities = target["probabilities"]
        if type(labels) is not list or labels != ["C0", "C1"] or type(probabilities) is not list:
            raise ProtocolViolation("W01 diagnosis oracle target is malformed")
        expected_target = [
            float(state_representation.get("class_index") == index)
            for index in range(2)
        ]
        if probabilities != expected_target:
            raise ProtocolViolation("W01 diagnosis target contradicts sealed state")
        candidate = _diagnosis_probabilities(head, tuple(labels))
        expected = _diagnostic_metric_wire(candidate, probabilities)
        degraded = _degraded_diagnosis(candidate, probabilities)
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
            raise ProtocolViolation("W01 diagnosis metric direction failed")

    def verify_forecast(cell: dict[str, Any], state_hash: str, *, require_reference: bool) -> None:
        required = {
            "cell_id",
            "world_slot",
            "cut_alias",
            "task",
            "state_hash",
            "candidate_head",
            "production_oracle",
            "reference_oracle",
            "oracle_comparison",
            "metric",
            "degraded_control_metric",
            "expected_utility",
        }
        _closed(cell, required, cell["cell_id"])
        if cell["world_slot"] != "W01" or cell["task"] != "natural_forecast_mean" or cell["state_hash"] != state_hash:
            raise ProtocolViolation("W01 forecast cell identity mismatch")
        head = _verify_head(
            cell["candidate_head"],
            operation="rollout",
            state_hash=state_hash,
            manifest_digest=manifest_digest,
            label=cell["cell_id"],
        )
        requested = tuple(cell["candidate_head"]["query"]["requested_observables"])
        predicted, utility = _point_rollout(head, requested)
        oracle = _verify_oracle_query_binding(
            cell["production_oracle"],
            cell["candidate_head"]["query"],
            f"{cell['cell_id']} production oracle",
        )
        truth = _oracle_mean_matrix(oracle, requested)
        expected = _trajectory_metric_wire(predicted, truth)
        degraded = _degraded_trajectory(predicted, truth)
        _metric_equal(cell["metric"], expected, f"{cell['cell_id']} metric")
        _metric_equal(cell["degraded_control_metric"], degraded, f"{cell['cell_id']} degraded metric")
        if utility != cell["expected_utility"] or utility != oracle["expected_utility"]:
            raise ProtocolViolation("W01 forecast expected utility mismatch")
        if expected["normalized_rmse"] != 0.0 or degraded["normalized_rmse"] <= 0.0:
            raise ProtocolViolation("W01 forecast metric direction failed")
        if require_reference:
            reference = _verify_oracle_query_binding(
                cell["reference_oracle"],
                cell["candidate_head"]["query"],
                f"{cell['cell_id']} reference oracle",
            )
            expected_comparison = _oracle_comparison(oracle, reference)
            _metric_equal(cell["oracle_comparison"], expected_comparison, "oracle comparison")
            if expected_comparison["passed"] is not True:
                raise ProtocolViolation("W01 production/reference oracle disagreement")
        elif cell["reference_oracle"] is not None or cell["oracle_comparison"] is not None:
            raise ProtocolViolation("updated W01 cell falsely claims a distinct reference")

    verify_diagnosis(
        by_id["W01.initial.diagnosis"],
        initial_record["state_hash"],
        initial["payload"]["representation"],
    )
    verify_diagnosis(
        by_id["W01.updated.diagnosis"],
        updated_record["state_hash"],
        updated["payload"]["representation"],
    )
    verify_forecast(
        by_id["W01.initial.natural_forecast"],
        initial_record["state_hash"],
        require_reference=True,
    )
    verify_forecast(
        by_id["W01.updated.natural_forecast"],
        updated_record["state_hash"],
        require_reference=False,
    )

    intervention = by_id["W01.initial.intervention"]
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
            "production_oracles",
            "reference_oracles",
            "oracle_comparisons",
            "trajectory_metrics",
            "predicted_utilities",
            "oracle_utilities",
            "metric",
            "degraded_control_metric",
        },
        "W01 intervention cell",
    )
    aliases = intervention["policy_aliases"]
    if (
        intervention["world_slot"] != "W01"
        or intervention["cut_alias"] != "initial"
        or intervention["task"] != "intervention_mean_utility"
        or intervention["state_hash"] != initial_record["state_hash"]
        or aliases != ["no_new_action", "single_A1", "single_A2"]
    ):
        raise ProtocolViolation("W01 intervention policy aliases mismatch")
    expected_aliases = set(aliases)
    for field in (
        "candidate_heads",
        "production_oracles",
        "reference_oracles",
        "oracle_comparisons",
        "trajectory_metrics",
    ):
        if type(intervention[field]) is not dict or set(intervention[field]) != expected_aliases:
            raise ProtocolViolation(f"W01 intervention {field} coverage mismatch")
    predicted_utilities = []
    oracle_utilities = []
    for alias in aliases:
        head = _verify_head(
            intervention["candidate_heads"][alias],
            operation="rollout",
            state_hash=initial_record["state_hash"],
            manifest_digest=manifest_digest,
            label=f"W01 intervention {alias}",
        )
        requested = tuple(
            intervention["candidate_heads"][alias]["query"]["requested_observables"]
        )
        predicted, utility = _point_rollout(head, requested)
        oracle = _verify_oracle_query_binding(
            intervention["production_oracles"][alias],
            intervention["candidate_heads"][alias]["query"],
            f"W01 intervention {alias} production oracle",
        )
        truth = _oracle_mean_matrix(oracle, requested)
        _metric_equal(
            intervention["trajectory_metrics"][alias],
            _trajectory_metric_wire(predicted, truth),
            f"W01 intervention {alias} trajectory",
        )
        reference = _verify_oracle_query_binding(
            intervention["reference_oracles"][alias],
            intervention["candidate_heads"][alias]["query"],
            f"W01 intervention {alias} reference oracle",
        )
        comparison = _oracle_comparison(oracle, reference)
        _metric_equal(
            intervention["oracle_comparisons"][alias],
            comparison,
            f"W01 intervention {alias} oracle comparison",
        )
        if comparison["passed"] is not True:
            raise ProtocolViolation("W01 intervention oracle disagreement")
        if intervention["trajectory_metrics"][alias]["normalized_rmse"] != 0.0:
            raise ProtocolViolation("W01 intervention mean trajectory is not exact")
        predicted_utilities.append(utility)
        oracle_utilities.append(_finite(oracle["expected_utility"], "oracle utility"))
    if predicted_utilities != intervention["predicted_utilities"] or oracle_utilities != intervention["oracle_utilities"]:
        raise ProtocolViolation("W01 intervention utility extraction mismatch")
    expected_regret = _regret_metric_wire(predicted_utilities, oracle_utilities)
    degraded_regret = _degraded_regret(oracle_utilities)
    _metric_equal(intervention["metric"], expected_regret, "W01 intervention regret")
    _metric_equal(
        intervention["degraded_control_metric"],
        degraded_regret,
        "W01 intervention degraded regret",
    )
    if expected_regret["worst_regret"] != 0.0 or degraded_regret["worst_regret"] <= 0.0:
        raise ProtocolViolation("W01 intervention regret direction failed")

    update = by_id["W01.update"]
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
        },
        "W01 update cell",
    )
    if (
        update["world_slot"] != "W01"
        or update["task"] != "recursive_update"
        or update["state_hash"] != updated_record["state_hash"]
        or update["prior_state_hash"] != initial_record["state_hash"]
        or update["parent_state_hash"] != initial_record["state_hash"]
        or digest_json(update["delta"]) != update["delta_digest"]
        or update["delta_digest"] != updated_record["delta_digest"]
    ):
        raise ProtocolViolation("W01 update cell does not close the lineage")

    summary = _closed(
        report["verification_summary"],
        {
            "status",
            "cell_count",
            "state_binding_count",
            "source_distinct_oracle_cells",
            "ledger_credit",
            "formalization_blockers",
        },
        "verification summary",
    )
    if (
        summary["status"] != "VALID_PRE_FREEZE_SANITY_BUNDLE"
        or summary["cell_count"] != 6
        or summary["state_binding_count"] != 2
        or summary["source_distinct_oracle_cells"] != 2
        or summary["ledger_credit"] != 0
        or summary["formalization_blockers"]
        != [
            "not-a-frozen-expected-cell-corpus",
            "privileged-upper-bound-only",
            "updated-cut-reference-oracle-not-source-distinct",
            "mean-and-expected-utility-projections-only",
        ]
    ):
        raise ProtocolViolation("W01 verification summary was overstated")


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the PRE-FREEZE W01 upper-bound evaluator sanity bundle."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_W01_ARTIFACT)
    parser.add_argument("--generator-seed", type=int, default=92011)
    parser.add_argument("--episode-index", type=int, default=13)
    args = parser.parse_args()
    report = run_w01_upper_bound_sanity(
        source_artifact=args.source_artifact,
        generator_seed=args.generator_seed,
        episode_index=args.episode_index,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(report))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "DEFAULT_W01_ARTIFACT",
    "PROTOCOL",
    "STATUS_CHAIN",
    "compute_upper_bound_bundle_root",
    "run_w01_upper_bound_sanity",
    "verify_w01_upper_bound_sanity",
]


if __name__ == "__main__":
    raise SystemExit(_main())
