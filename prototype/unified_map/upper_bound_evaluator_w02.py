"""Patient-bound PRE-FREEZE upper-bound sanity evaluator for W02.

W02 is partially observed.  Its formal diagnosis target is therefore a public
posterior, not the parent-only realized class stored by the privileged B01
probe.  This adapter keeps those objects separate:

* the privileged diagnosis head is scored only as a true-class identity sanity
  check and is never presented as a calibrated candidate diagnosis;
* source-distinct production/reference *public* oracles are retained as an
  oracle audit, but are not used as a reference for the privileged head; and
* the privileged conditional-mean rollout is compared only with the judge
  true-state oracle.  W02 has no source-distinct explicit-state reference
  implementation, so the corresponding reference fields are always ``None``.

The committed W02 vertical slice must replay byte-for-byte before collection.
The resulting report stores stable state-hash preimages, exact query/response
wires, collector-derived metrics, and recursive-update lineage.  It remains
``PRE-FREEZE`` / ``NOT_COUNT_ELIGIBLE`` with zero ledger credit.
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
from .schema import DiagnosisQuery, RolloutQuery
from .true_state_probe_w02 import (
    W02TrueStateUpperBoundProbe,
    _factual_delta,
    run_w02_vertical_slice,
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
from .worlds.base import WorldSplit
from .worlds.w02 import W02World


DEFAULT_W02_ARTIFACT = Path(
    "results/unified_map/pre_freeze/20260717-w02-true-state-probe/vertical-slice.json"
)

_SCOPE_STATEMENT = {
    "privileged_true_class_identity_only": True,
    "mean_trajectory_only": True,
    "expected_utility_only": True,
    "public_posterior_primary_claimed": False,
    "diagnostic_calibration_claimed": False,
    "proper_distribution_score_claimed": False,
    "candidate_performance_claimed": False,
    "formal_b01_claimed": False,
}

_FORMALIZATION_BLOCKERS = [
    "not-a-frozen-expected-cell-corpus",
    "privileged-upper-bound-only",
    "privileged-true-class-is-not-public-posterior-diagnosis",
    "public-oracle-audit-is-not-a-candidate-head-score",
    "explicit-state-reference-absent",
    "mean-and-expected-utility-projections-only",
]


def _verify_w02_state_representation(
    binding: dict[str, Any], label: str
) -> dict[str, Any]:
    payload = binding["payload"]
    record = binding["record"]
    if (
        payload["schema_version"] != "ucm-phase2-true-state-w02-state/1"
        or payload["state_class"] != "dynamic_shared_state"
    ):
        raise ProtocolViolation(f"{label} has the wrong W02 payload identity")
    representation = _closed(
        payload["representation"],
        {"protocol", "world_slot", "as_of_available_at", "class_index", "x"},
        f"{label} representation",
    )
    if (
        representation["protocol"] != "ucm-phase2-true-state-w02/1"
        or representation["world_slot"] != "W02"
        or type(representation["as_of_available_at"]) is not int
        or representation["as_of_available_at"] != record["as_of_available_at"]
        or type(representation["class_index"]) is not int
        or representation["class_index"] not in {0, 1}
        or type(representation["x"]) is not list
        or len(representation["x"]) != 2
    ):
        raise ProtocolViolation(f"{label} representation is malformed")
    for index, item in enumerate(representation["x"]):
        _finite(item, f"{label} x[{index}]")
    return representation


def _w02_oracle_mean_matrix(
    oracle: dict[str, Any], requested: tuple[str, ...]
) -> list[list[float]]:
    """Collect W02 observable means from its latent moment projection."""

    distribution = oracle.get("observation_distribution")
    if type(distribution) is not dict or set(distribution) != {
        "family",
        "channels",
        "latent_moment_projection",
    }:
        raise ProtocolViolation("W02 oracle observation distribution is not closed")
    if distribution["family"] != "gaussian-mixture":
        raise ProtocolViolation("W02 oracle observation family mismatch")
    channels = distribution["channels"]
    if channels != ["obs_0", "obs_1", "obs_2"]:
        raise ProtocolViolation("W02 oracle channel catalog mismatch")
    steps = distribution["latent_moment_projection"]
    if type(steps) is not list or not steps:
        raise ProtocolViolation("W02 oracle moment projection is absent")
    rows: list[list[float]] = []
    for expected_offset, step in enumerate(steps, start=1):
        if type(step) is not dict or set(step) != {
            "offset",
            "mean",
            "covariance",
        }:
            raise ProtocolViolation("W02 oracle moment step is not closed")
        if step["offset"] != expected_offset:
            raise ProtocolViolation("W02 oracle moment offsets are not contiguous")
        mean = step["mean"]
        if type(mean) is not list or len(mean) != 2:
            raise ProtocolViolation("W02 oracle latent mean is malformed")
        latent_0 = _finite(mean[0], "W02 latent mean 0")
        latent_1 = _finite(mean[1], "W02 latent mean 1")
        row: list[float] = []
        for observable in requested:
            if observable == "obs_0":
                row.append(latent_0 + latent_1)
            elif observable == "obs_1":
                row.append(latent_0)
            elif observable == "obs_2":
                row.append(latent_1)
            else:
                raise ProtocolViolation("W02 oracle requested unknown observable")
        rows.append(row)
    return rows


def _w02_public_posterior(
    oracle: dict[str, Any], label_order: tuple[str, ...]
) -> list[float]:
    latent = oracle.get("latent_distribution")
    if type(latent) is not dict or set(latent) != {
        "family",
        "diagnostic_posterior",
        "steps",
    }:
        raise ProtocolViolation("W02 public latent distribution is not closed")
    if latent["family"] != "class-conditioned-gaussian-mixture":
        raise ProtocolViolation("W02 public latent distribution family mismatch")
    posterior = latent["diagnostic_posterior"]
    if type(posterior) is not dict or set(posterior) != set(label_order):
        raise ProtocolViolation("W02 public posterior label catalog mismatch")
    values = [
        _finite(posterior[label], f"W02 public posterior {label}")
        for label in label_order
    ]
    if any(value <= 0.0 or value >= 1.0 for value in values):
        raise ProtocolViolation("W02 public posterior must remain non-degenerate")
    if not np.isclose(sum(values), 1.0, atol=1e-12, rtol=0.0):
        raise ProtocolViolation("W02 public posterior is not normalized")
    return values


def _public_oracle_audit(
    production: dict[str, Any],
    reference: dict[str, Any],
    query_wire: dict[str, Any],
    label_order: tuple[str, ...],
) -> dict[str, Any]:
    production = _verify_oracle_query_binding(
        production, query_wire, "W02 public production oracle"
    )
    reference = _verify_oracle_query_binding(
        reference, query_wire, "W02 public reference oracle"
    )
    production_posterior = _w02_public_posterior(production, label_order)
    reference_posterior = _w02_public_posterior(reference, label_order)
    comparison = _oracle_comparison(production, reference)
    if comparison["passed"] is not True:
        raise ProtocolViolation("W02 source-distinct public oracles disagree")
    if not np.allclose(
        production_posterior,
        reference_posterior,
        atol=1e-12,
        rtol=1e-12,
    ):
        raise ProtocolViolation("W02 public posterior reference disagreement")
    return {
        "role": "public_oracle_audit_not_candidate_head_score",
        "candidate_output": False,
        "candidate_capability_claimed": False,
        "production_entrypoint": "W02World.counterfactual",
        "reference_entrypoint": "W02World.reference_counterfactual",
        "source_distinct": True,
        "production_oracle": production,
        "reference_oracle": reference,
        "oracle_comparison": comparison,
        "label_order": list(label_order),
        "public_posterior": production_posterior,
        "non_degenerate": True,
    }


def _verify_public_oracle_audit(
    value: object,
    *,
    query_wire: dict[str, Any],
    label_order: tuple[str, ...],
    label: str,
) -> dict[str, Any]:
    audit = _closed(
        value,
        {
            "role",
            "candidate_output",
            "candidate_capability_claimed",
            "production_entrypoint",
            "reference_entrypoint",
            "source_distinct",
            "production_oracle",
            "reference_oracle",
            "oracle_comparison",
            "label_order",
            "public_posterior",
            "non_degenerate",
        },
        label,
    )
    if (
        audit["role"] != "public_oracle_audit_not_candidate_head_score"
        or audit["candidate_output"] is not False
        or audit["candidate_capability_claimed"] is not False
        or audit["production_entrypoint"] != "W02World.counterfactual"
        or audit["reference_entrypoint"] != "W02World.reference_counterfactual"
        or audit["source_distinct"] is not True
        or audit["non_degenerate"] is not True
        or audit["label_order"] != list(label_order)
    ):
        raise ProtocolViolation(f"{label} information boundary was rewritten")
    expected = _public_oracle_audit(
        audit["production_oracle"],
        audit["reference_oracle"],
        query_wire,
        label_order,
    )
    _metric_equal(audit, expected, label)
    return audit


def _live_expected_runtime(
    *, generator_seed: int, episode_index: int
) -> dict[str, Any]:
    """Rebuild every patient-bound W02 object from the fixture identity.

    This is intentionally stronger than merely re-hashing caller-supplied
    state bytes.  In particular, the updated state is derived again from the
    generated episode's first factual response and parent-only next truth.
    A caller therefore cannot replace ``x`` and repair the state/cell roots.
    """

    world = W02World()
    probe = W02TrueStateUpperBoundProbe(world)
    episode = world.generate_episode(
        WorldSplit.TRAIN,
        generator_seed,
        episode_index,
    )
    labels = world.catalog.diagnostic_labels
    requested = ("obs_0", "obs_1", "obs_2")
    aliases = ("no_new_action", "single_A1", "single_A2")
    policies = world.policy_set(4)[:3]
    utility_digest = digest_json(
        {
            "protocol": "ucm-w02-upper-bound-utility/1",
            "catalog_digest": world.catalog.digest,
            "horizon": 4,
            "utility": "discounted-quadratic-cost",
        }
    )

    initial = probe.initialize_private(episode)
    diagnosis_query = DiagnosisQuery(labels)
    initial_diagnosis = _head_wire(
        probe.diagnose(initial, diagnosis_query, query_seed=1),
        diagnosis_query,
    )
    rollout_heads: dict[str, dict[str, Any]] = {}
    judge_oracles: dict[str, dict[str, Any]] = {}
    public_audits: dict[str, dict[str, Any]] = {}
    for alias, policy in zip(aliases, policies, strict=True):
        query = RolloutQuery(4, policy, requested, utility_digest)
        rollout_heads[alias] = _head_wire(
            probe.rollout(initial, query, query_seed=2),
            query,
        )
        judge_oracles[alias] = _oracle_wire(
            world.judge_true_state_counterfactual(
                episode.hidden_state_at_cut,
                episode.invariant_parameters,
                policy,
                4,
            )
        )
        public_audits[alias] = _public_oracle_audit(
            _oracle_wire(world.counterfactual(episode, policy, 4, 2)),
            _oracle_wire(
                world.reference_counterfactual(
                    episode,
                    policy,
                    4,
                    oracle_seed=2,
                )
            ),
            query.to_wire(),
            labels,
        )

    delta = _factual_delta(episode)
    next_row = episode.factual_future[0]
    updated = probe.update_private(
        initial,
        delta,
        hidden_state_at_cut={"x": next_row["latent_outcome"]},
        invariant_parameters=episode.invariant_parameters,
        inference_seed=3,
    )
    updated_diagnosis = _head_wire(
        probe.diagnose(updated, diagnosis_query, query_seed=4),
        diagnosis_query,
    )
    updated_query = RolloutQuery(4, policies[0], requested, utility_digest)
    updated_rollout = _head_wire(
        probe.rollout(updated, updated_query, query_seed=5),
        updated_query,
    )
    updated_representation = _state_binding(updated)["payload"]["representation"]
    updated_judge = _oracle_wire(
        world.judge_true_state_counterfactual(
            {"x": updated_representation["x"]},
            {"class_index": updated_representation["class_index"]},
            policies[0],
            4,
        )
    )
    return {
        "manifest": probe.manifest.to_wire(),
        "manifest_digest": probe.manifest.digest,
        "fixture": {
            "split": WorldSplit.TRAIN.value,
            "generator_seed": generator_seed,
            "episode_index": episode_index,
            "public_history_digest": episode.public_history.digest,
        },
        "states": {
            "initial": _state_binding(initial),
            "updated": _state_binding(updated),
        },
        "delta": delta.to_wire(),
        "heads": {
            "initial_diagnosis": initial_diagnosis,
            "initial_rollouts": rollout_heads,
            "updated_diagnosis": updated_diagnosis,
            "updated_rollout": updated_rollout,
        },
        "judge_oracles": {
            "initial": judge_oracles,
            "updated": updated_judge,
        },
        "public_audits": public_audits,
        "vertical_slice": run_w02_vertical_slice(
            generator_seed=generator_seed,
            episode_index=episode_index,
        ),
    }


def run_w02_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W02_ARTIFACT,
    generator_seed: int = 92024,
    episode_index: int = 36,
) -> dict[str, Any]:
    """Collect a replay-bound W02 upper-bound sanity report."""

    source_path = Path(source_artifact)
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(
            f"W02 source artifact is unavailable: {source_path}"
        ) from exc
    try:
        source_wire = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("W02 source artifact is not JSON") from exc
    if canonical_json_bytes(source_wire) != source_bytes:
        raise ProtocolViolation("W02 source artifact is not canonical JSON")
    replay = run_w02_vertical_slice(
        generator_seed=generator_seed,
        episode_index=episode_index,
    )
    replay_bytes = canonical_json_bytes(replay)
    if replay_bytes != source_bytes:
        raise ProtocolViolation("W02 committed vertical slice does not byte-replay")

    world = W02World()
    probe = W02TrueStateUpperBoundProbe(world)
    episode = world.generate_episode(WorldSplit.TRAIN, generator_seed, episode_index)
    labels = world.catalog.diagnostic_labels
    requested = ("obs_0", "obs_1", "obs_2")
    policy_aliases = ("no_new_action", "single_A1", "single_A2")
    policies = world.policy_set(4)[:3]
    utility_digest = digest_json(
        {
            "protocol": "ucm-w02-upper-bound-utility/1",
            "catalog_digest": world.catalog.digest,
            "horizon": 4,
            "utility": "discounted-quadratic-cost",
        }
    )

    initial = probe.initialize_private(episode)
    initial_binding = _state_binding(initial)
    diagnosis_query = DiagnosisQuery(labels)
    diagnosis = probe.diagnose(initial, diagnosis_query, query_seed=1)
    diagnosis_head = _head_wire(diagnosis, diagnosis_query)
    true_target = [float(episode.diagnostic_target[label]) for label in labels]
    privileged_probabilities = _diagnosis_probabilities(diagnosis_head, labels)

    rollout_heads: dict[str, dict[str, Any]] = {}
    judge_oracles: dict[str, dict[str, Any]] = {}
    public_audits: dict[str, dict[str, Any]] = {}
    trajectory_metrics: dict[str, dict[str, Any]] = {}
    predicted_utilities: list[float] = []
    oracle_utilities: list[float] = []
    for alias, policy in zip(policy_aliases, policies, strict=True):
        query = RolloutQuery(4, policy, requested, utility_digest)
        execution = probe.rollout(initial, query, query_seed=2)
        head = _head_wire(execution, query)
        judge = _oracle_wire(
            world.judge_true_state_counterfactual(
                episode.hidden_state_at_cut,
                episode.invariant_parameters,
                policy,
                4,
            )
        )
        public_production = _oracle_wire(world.counterfactual(episode, policy, 4, 2))
        public_reference = _oracle_wire(
            world.reference_counterfactual(episode, policy, 4, oracle_seed=2)
        )
        predicted, predicted_utility = _point_rollout(head, requested)
        judge_mean = _w02_oracle_mean_matrix(judge, requested)
        rollout_heads[alias] = head
        judge_oracles[alias] = judge
        public_audits[alias] = _public_oracle_audit(
            public_production,
            public_reference,
            query.to_wire(),
            labels,
        )
        trajectory_metrics[alias] = _trajectory_metric_wire(predicted, judge_mean)
        predicted_utilities.append(predicted_utility)
        oracle_utilities.append(_finite(judge["expected_utility"], "W02 judge utility"))

    no_action_public = public_audits["no_new_action"]
    public_posterior = no_action_public["public_posterior"]
    information_boundary = {
        "protocol": "ucm-w02-upper-bound-information-boundary/1",
        "formal_diagnosis_target": "public_posterior",
        "privileged_true_class": {
            "role": "parent_only_identity_sanity_not_candidate_capability",
            "probabilities": privileged_probabilities,
            "one_hot": True,
            "candidate_eligible": False,
            "candidate_capability_claimed": False,
        },
        "public_belief": {
            "role": "public_oracle_audit_not_candidate_output",
            "probabilities": public_posterior,
            "non_degenerate": True,
            "candidate_output": False,
            "candidate_capability_claimed": False,
        },
        "vectors_are_distinct": privileged_probabilities != public_posterior,
        "substitution_forbidden": True,
    }

    delta = _factual_delta(episode)
    next_row = episode.factual_future[0]
    updated = probe.update_private(
        initial,
        delta,
        hidden_state_at_cut={"x": next_row["latent_outcome"]},
        invariant_parameters=episode.invariant_parameters,
        inference_seed=3,
    )
    updated_binding = _state_binding(updated)
    updated_representation = updated_binding["payload"]["representation"]
    updated_target = [
        float(updated_representation["class_index"] == index) for index in range(2)
    ]
    updated_diagnosis = probe.diagnose(updated, diagnosis_query, query_seed=4)
    updated_diagnosis_head = _head_wire(updated_diagnosis, diagnosis_query)
    updated_probabilities = _diagnosis_probabilities(updated_diagnosis_head, labels)
    updated_query = RolloutQuery(4, policies[0], requested, utility_digest)
    updated_rollout = probe.rollout(updated, updated_query, query_seed=5)
    updated_rollout_head = _head_wire(updated_rollout, updated_query)
    updated_judge = _oracle_wire(
        world.judge_true_state_counterfactual(
            {"x": updated_representation["x"]},
            {"class_index": updated_representation["class_index"]},
            policies[0],
            4,
        )
    )
    updated_predicted, updated_utility = _point_rollout(updated_rollout_head, requested)
    updated_judge_mean = _w02_oracle_mean_matrix(updated_judge, requested)

    cells = [
        {
            "cell_id": "W02.initial.privileged_true_class_identity",
            "world_slot": "W02",
            "cut_alias": "initial",
            "task": "privileged_true_class_identity_sanity",
            "state_hash": initial.record.state_hash,
            "candidate_head": diagnosis_head,
            "oracle_target": {
                "label_order": list(labels),
                "probabilities": true_target,
                "target_role": "parent_only_realized_class_not_formal_public_posterior",
            },
            "metric": _diagnostic_metric_wire(privileged_probabilities, true_target),
            "degraded_control_metric": _degraded_diagnosis(
                privileged_probabilities, true_target
            ),
            "public_oracle_audit": no_action_public,
        },
        {
            "cell_id": "W02.initial.natural_forecast",
            "world_slot": "W02",
            "cut_alias": "initial",
            "task": "privileged_natural_forecast_mean_sanity",
            "state_hash": initial.record.state_hash,
            "candidate_head": rollout_heads["no_new_action"],
            "judge_oracle": judge_oracles["no_new_action"],
            "explicit_state_reference_oracle": None,
            "metric": trajectory_metrics["no_new_action"],
            "degraded_control_metric": _degraded_trajectory(
                _point_rollout(rollout_heads["no_new_action"], requested)[0],
                _w02_oracle_mean_matrix(judge_oracles["no_new_action"], requested),
            ),
            "expected_utility": predicted_utilities[0],
            "public_oracle_audit": no_action_public,
        },
        {
            "cell_id": "W02.initial.intervention",
            "world_slot": "W02",
            "cut_alias": "initial",
            "task": "privileged_intervention_mean_utility_sanity",
            "state_hash": initial.record.state_hash,
            "policy_aliases": list(policy_aliases),
            "candidate_heads": rollout_heads,
            "judge_oracles": judge_oracles,
            "explicit_state_reference_oracles": {
                alias: None for alias in policy_aliases
            },
            "public_oracle_audits": public_audits,
            "trajectory_metrics": trajectory_metrics,
            "predicted_utilities": predicted_utilities,
            "oracle_utilities": oracle_utilities,
            "metric": _regret_metric_wire(predicted_utilities, oracle_utilities),
            "degraded_control_metric": _degraded_regret(oracle_utilities),
        },
        {
            "cell_id": "W02.update",
            "world_slot": "W02",
            "cut_alias": "initial-to-updated",
            "task": "recursive_update",
            "state_hash": updated.record.state_hash,
            "prior_state_hash": initial.record.state_hash,
            "parent_state_hash": updated.record.parent_state_hash,
            "delta": delta.to_wire(),
            "delta_digest": digest_json(delta.to_wire()),
        },
        {
            "cell_id": "W02.updated.privileged_true_class_identity",
            "world_slot": "W02",
            "cut_alias": "updated",
            "task": "privileged_true_class_identity_sanity",
            "state_hash": updated.record.state_hash,
            "candidate_head": updated_diagnosis_head,
            "oracle_target": {
                "label_order": list(labels),
                "probabilities": updated_target,
                "target_role": "parent_only_realized_class_not_formal_public_posterior",
            },
            "metric": _diagnostic_metric_wire(updated_probabilities, updated_target),
            "degraded_control_metric": _degraded_diagnosis(
                updated_probabilities, updated_target
            ),
            "public_oracle_audit": None,
        },
        {
            "cell_id": "W02.updated.natural_forecast",
            "world_slot": "W02",
            "cut_alias": "updated",
            "task": "privileged_natural_forecast_mean_sanity",
            "state_hash": updated.record.state_hash,
            "candidate_head": updated_rollout_head,
            "judge_oracle": updated_judge,
            "explicit_state_reference_oracle": None,
            "metric": _trajectory_metric_wire(updated_predicted, updated_judge_mean),
            "degraded_control_metric": _degraded_trajectory(
                updated_predicted, updated_judge_mean
            ),
            "expected_utility": updated_utility,
            "public_oracle_audit": None,
        },
    ]
    body = {
        "protocol": PROTOCOL,
        "bundle_kind": "phase2_privileged_probe_evaluator",
        "world_slot": "W02",
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
            "split": WorldSplit.TRAIN.value,
            "generator_seed": generator_seed,
            "episode_index": episode_index,
            "public_history_digest": episode.public_history.digest,
        },
        "information_boundary": information_boundary,
        "states": {"initial": initial_binding, "updated": updated_binding},
        "cells": cells,
        "cell_set_root": _cell_root(cells),
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_SANITY_BUNDLE",
            "cell_count": len(cells),
            "state_binding_count": 2,
            "source_distinct_explicit_state_oracle_pairs": 0,
            "source_distinct_public_oracle_audit_pairs": len(policy_aliases),
            "ledger_credit": 0,
            "formalization_blockers": list(_FORMALIZATION_BLOCKERS),
        },
    }
    result = _attach_bundle_root(body)
    verify_w02_upper_bound_sanity(result)
    return result


def verify_w02_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    """Recompute W02 state, query, oracle, metric, and status claims."""

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
            "information_boundary",
            "states",
            "cells",
            "cell_set_root",
            "verification_summary",
            "bundle_root",
        },
        "W02 upper-bound sanity report",
    )
    validate_json_like(report)
    if (
        report["protocol"] != PROTOCOL
        or report["bundle_kind"] != "phase2_privileged_probe_evaluator"
        or report["world_slot"] != "W02"
        or report["status_chain"] != STATUS_CHAIN
    ):
        raise ProtocolViolation("W02 upper-bound status or identity was rewritten")
    if report["bundle_root"] != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation("W02 upper-bound bundle root mismatch")
    if report["scope_statement"] != _SCOPE_STATEMENT:
        raise ProtocolViolation("W02 upper-bound scope was overstated")

    manifest = report["manifest"]
    if digest_json(manifest) != report["manifest_digest"]:
        raise ProtocolViolation("W02 upper-bound manifest digest mismatch")
    if (
        type(manifest) is not dict
        or manifest.get("world_slot") != "W02"
        or manifest.get("baseline_id") != "B01"
        or manifest.get("privileged") is not True
        or manifest.get("eligibility") != "upper_bound_only"
        or manifest.get("freeze_grade") is not False
    ):
        raise ProtocolViolation("W02 upper-bound manifest eligibility mismatch")
    manifest_digest = report["manifest_digest"]

    fixture = _closed(
        report["fixture"],
        {"split", "generator_seed", "episode_index", "public_history_digest"},
        "W02 fixture",
    )
    if (
        fixture["split"] != WorldSplit.TRAIN.value
        or type(fixture["generator_seed"]) is not int
        or fixture["generator_seed"] < 0
        or type(fixture["episode_index"]) is not int
        or fixture["episode_index"] < 0
    ):
        raise ProtocolViolation("W02 fixture identity is invalid")
    _digest(fixture["public_history_digest"], "W02 public history digest")

    live_expected = _live_expected_runtime(
        generator_seed=fixture["generator_seed"],
        episode_index=fixture["episode_index"],
    )
    if report["manifest"] != live_expected["manifest"] or (
        manifest_digest != live_expected["manifest_digest"]
    ):
        raise ProtocolViolation("W02 manifest does not match the live probe")
    if fixture != live_expected["fixture"]:
        raise ProtocolViolation("W02 fixture does not match the live episode")

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
        "W02 source anchor",
    )
    _digest(source["artifact_digest"], "W02 source artifact digest")
    _digest(source["replay_digest"], "W02 source replay digest")
    if (
        source["artifact_digest"] != source["replay_digest"]
        or source["byte_identical_replay"] is not True
        or source["artifact_protocol"] != "ucm-phase2-true-state-vertical-slice/1"
        or type(source["artifact_bytes"]) is not int
        or source["artifact_bytes"] <= 0
    ):
        raise ProtocolViolation("W02 source artifact replay anchor mismatch")
    if type(source["artifact_relpath"]) is not str or not source["artifact_relpath"]:
        raise ProtocolViolation("W02 source artifact path is invalid")
    expected_source_path = (
        Path(source_artifact) if source_artifact is not None else DEFAULT_W02_ARTIFACT
    )
    if source["artifact_relpath"] != expected_source_path.as_posix():
        raise ProtocolViolation("W02 source artifact path does not match the verifier")

    # The repository artifact is the authority even when the report was
    # collected from a byte-identical copy.  This prevents a caller from
    # changing fixture identity and pointing the verifier at a newly forged
    # source file.
    committed_path = Path(__file__).resolve().parents[2] / DEFAULT_W02_ARTIFACT
    try:
        committed_raw = committed_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation("committed W02 source artifact is unavailable") from exc
    try:
        committed_wire = json.loads(committed_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("committed W02 source artifact is not JSON") from exc
    if canonical_json_bytes(committed_wire) != committed_raw:
        raise ProtocolViolation("committed W02 source artifact is not canonical")
    if (
        digest_bytes(committed_raw) != source["artifact_digest"]
        or len(committed_raw) != source["artifact_bytes"]
    ):
        raise ProtocolViolation("report is not bound to the committed W02 artifact")
    live_vertical_slice = canonical_json_bytes(live_expected["vertical_slice"])
    if (
        live_vertical_slice != committed_raw
        or digest_bytes(live_vertical_slice) != source["replay_digest"]
    ):
        raise ProtocolViolation("committed W02 source artifact does not replay live")
    if source_artifact is not None:
        source_path = expected_source_path
        try:
            raw = source_path.read_bytes()
        except OSError as exc:
            raise ProtocolViolation("bound W02 source artifact is unavailable") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("bound W02 source artifact is not JSON") from exc
        if canonical_json_bytes(decoded) != raw:
            raise ProtocolViolation("bound W02 source artifact is not canonical")
        if raw != committed_raw:
            raise ProtocolViolation(
                "bound W02 source differs from the committed artifact"
            )
        if (
            digest_bytes(raw) != source["artifact_digest"]
            or len(raw) != source["artifact_bytes"]
        ):
            raise ProtocolViolation("bound W02 source bytes do not match the report")
        if replay_runtime and live_vertical_slice != raw:
            raise ProtocolViolation("bound W02 source artifact does not replay live")

    states = _closed(report["states"], {"initial", "updated"}, "W02 states")
    initial = _verify_state_binding(states["initial"], "W02 initial state")
    updated = _verify_state_binding(states["updated"], "W02 updated state")
    _verify_w02_state_representation(initial, "W02 initial state")
    _verify_w02_state_representation(updated, "W02 updated state")
    if states["initial"] != live_expected["states"]["initial"]:
        raise ProtocolViolation("W02 initial state differs from the live episode")
    if states["updated"] != live_expected["states"]["updated"]:
        raise ProtocolViolation(
            "W02 updated state differs from the factual next-truth update"
        )
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
        raise ProtocolViolation("W02 recursive state lineage is not closed")

    cells = report["cells"]
    if type(cells) is not list or len(cells) != 6:
        raise ProtocolViolation("W02 sanity requires exactly six cells")
    if len({cell.get("cell_id") for cell in cells if type(cell) is dict}) != 6:
        raise ProtocolViolation("W02 sanity cell ids are not unique")
    if _cell_root(cells) != report["cell_set_root"]:
        raise ProtocolViolation("W02 sanity cell set root mismatch")
    by_id = {cell["cell_id"]: cell for cell in cells}
    expected_ids = {
        "W02.initial.privileged_true_class_identity",
        "W02.initial.natural_forecast",
        "W02.initial.intervention",
        "W02.update",
        "W02.updated.privileged_true_class_identity",
        "W02.updated.natural_forecast",
    }
    if set(by_id) != expected_ids:
        raise ProtocolViolation("W02 sanity cell coverage mismatch")
    labels = ("C0", "C1")

    def verify_identity_cell(
        cell: dict[str, Any],
        *,
        state_hash: str,
        state_representation: dict[str, Any],
        expected_head: dict[str, Any],
        public_audit_query: dict[str, Any] | None,
        expected_public_audit: dict[str, Any] | None,
    ) -> list[float]:
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
                "public_oracle_audit",
            },
            cell["cell_id"],
        )
        if (
            cell["world_slot"] != "W02"
            or cell["task"] != "privileged_true_class_identity_sanity"
            or cell["state_hash"] != state_hash
        ):
            raise ProtocolViolation("W02 identity cell binding mismatch")
        head = _verify_head(
            cell["candidate_head"],
            operation="diagnose",
            state_hash=state_hash,
            manifest_digest=manifest_digest,
            label=cell["cell_id"],
        )
        if cell["candidate_head"] != expected_head:
            raise ProtocolViolation(
                f"{cell['cell_id']} differs from the live diagnosis head"
            )
        target = _closed(
            cell["oracle_target"],
            {"label_order", "probabilities", "target_role"},
            "W02 identity target",
        )
        expected_target = [
            float(state_representation.get("class_index") == index)
            for index in range(2)
        ]
        if (
            target["label_order"] != list(labels)
            or target["probabilities"] != expected_target
            or target["target_role"]
            != "parent_only_realized_class_not_formal_public_posterior"
        ):
            raise ProtocolViolation("W02 identity target contradicts its role or state")
        probabilities = _diagnosis_probabilities(head, labels)
        expected_metric = _diagnostic_metric_wire(probabilities, expected_target)
        degraded = _degraded_diagnosis(probabilities, expected_target)
        _metric_equal(cell["metric"], expected_metric, f"{cell['cell_id']} metric")
        _metric_equal(
            cell["degraded_control_metric"],
            degraded,
            f"{cell['cell_id']} degraded metric",
        )
        if (
            sorted(probabilities) != [0.0, 1.0]
            or expected_metric["accuracy"] != 1.0
            or expected_metric["log_loss"] != 0.0
            or expected_metric["multiclass_brier"] != 0.0
            or degraded["log_loss"] <= expected_metric["log_loss"]
        ):
            raise ProtocolViolation("W02 privileged identity metric direction failed")
        if public_audit_query is None:
            if (
                cell["public_oracle_audit"] is not None
                or expected_public_audit is not None
            ):
                raise ProtocolViolation("W02 updated identity invents a public audit")
        else:
            _verify_public_oracle_audit(
                cell["public_oracle_audit"],
                query_wire=public_audit_query,
                label_order=labels,
                label="W02 initial identity public audit",
            )
            if cell["public_oracle_audit"] != expected_public_audit:
                raise ProtocolViolation(
                    "W02 initial identity public audit differs from live oracles"
                )
        return probabilities

    def verify_forecast_cell(
        cell: dict[str, Any],
        *,
        state_hash: str,
        require_public_audit: bool,
        expected_head: dict[str, Any],
        expected_judge: dict[str, Any],
        expected_public_audit: dict[str, Any] | None,
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
                "explicit_state_reference_oracle",
                "metric",
                "degraded_control_metric",
                "expected_utility",
                "public_oracle_audit",
            },
            cell["cell_id"],
        )
        if (
            cell["world_slot"] != "W02"
            or cell["task"] != "privileged_natural_forecast_mean_sanity"
            or cell["state_hash"] != state_hash
            or cell["explicit_state_reference_oracle"] is not None
        ):
            raise ProtocolViolation("W02 privileged forecast identity mismatch")
        head = _verify_head(
            cell["candidate_head"],
            operation="rollout",
            state_hash=state_hash,
            manifest_digest=manifest_digest,
            label=cell["cell_id"],
        )
        if cell["candidate_head"] != expected_head:
            raise ProtocolViolation(
                f"{cell['cell_id']} differs from the live rollout head"
            )
        query = cell["candidate_head"]["query"]
        requested = tuple(query["requested_observables"])
        predicted, utility = _point_rollout(head, requested)
        judge = _verify_oracle_query_binding(
            cell["judge_oracle"], query, f"{cell['cell_id']} judge oracle"
        )
        if cell["judge_oracle"] != expected_judge:
            raise ProtocolViolation(
                f"{cell['cell_id']} judge oracle differs from live runtime"
            )
        truth = _w02_oracle_mean_matrix(judge, requested)
        expected_metric = _trajectory_metric_wire(predicted, truth)
        degraded = _degraded_trajectory(predicted, truth)
        _metric_equal(cell["metric"], expected_metric, f"{cell['cell_id']} metric")
        _metric_equal(
            cell["degraded_control_metric"],
            degraded,
            f"{cell['cell_id']} degraded metric",
        )
        if utility != cell["expected_utility"] or utility != judge["expected_utility"]:
            raise ProtocolViolation("W02 privileged forecast utility mismatch")
        if (
            expected_metric["normalized_rmse"] != 0.0
            or degraded["normalized_rmse"] <= 0.0
        ):
            raise ProtocolViolation("W02 privileged forecast metric direction failed")
        if require_public_audit:
            _verify_public_oracle_audit(
                cell["public_oracle_audit"],
                query_wire=query,
                label_order=labels,
                label=f"{cell['cell_id']} public audit",
            )
            if cell["public_oracle_audit"] != expected_public_audit:
                raise ProtocolViolation(
                    f"{cell['cell_id']} public audit differs from live oracles"
                )
        elif (
            cell["public_oracle_audit"] is not None or expected_public_audit is not None
        ):
            raise ProtocolViolation("W02 updated forecast invents a public audit")

    initial_forecast = by_id["W02.initial.natural_forecast"]
    initial_query = initial_forecast["candidate_head"]["query"]
    initial_probabilities = verify_identity_cell(
        by_id["W02.initial.privileged_true_class_identity"],
        state_hash=initial_record["state_hash"],
        state_representation=initial["payload"]["representation"],
        expected_head=live_expected["heads"]["initial_diagnosis"],
        public_audit_query=initial_query,
        expected_public_audit=live_expected["public_audits"]["no_new_action"],
    )
    verify_identity_cell(
        by_id["W02.updated.privileged_true_class_identity"],
        state_hash=updated_record["state_hash"],
        state_representation=updated["payload"]["representation"],
        expected_head=live_expected["heads"]["updated_diagnosis"],
        public_audit_query=None,
        expected_public_audit=None,
    )
    verify_forecast_cell(
        initial_forecast,
        state_hash=initial_record["state_hash"],
        require_public_audit=True,
        expected_head=live_expected["heads"]["initial_rollouts"]["no_new_action"],
        expected_judge=live_expected["judge_oracles"]["initial"]["no_new_action"],
        expected_public_audit=live_expected["public_audits"]["no_new_action"],
    )
    verify_forecast_cell(
        by_id["W02.updated.natural_forecast"],
        state_hash=updated_record["state_hash"],
        require_public_audit=False,
        expected_head=live_expected["heads"]["updated_rollout"],
        expected_judge=live_expected["judge_oracles"]["updated"],
        expected_public_audit=None,
    )

    intervention = _closed(
        by_id["W02.initial.intervention"],
        {
            "cell_id",
            "world_slot",
            "cut_alias",
            "task",
            "state_hash",
            "policy_aliases",
            "candidate_heads",
            "judge_oracles",
            "explicit_state_reference_oracles",
            "public_oracle_audits",
            "trajectory_metrics",
            "predicted_utilities",
            "oracle_utilities",
            "metric",
            "degraded_control_metric",
        },
        "W02 intervention cell",
    )
    aliases = intervention["policy_aliases"]
    if (
        intervention["world_slot"] != "W02"
        or intervention["cut_alias"] != "initial"
        or intervention["task"] != "privileged_intervention_mean_utility_sanity"
        or intervention["state_hash"] != initial_record["state_hash"]
        or aliases != ["no_new_action", "single_A1", "single_A2"]
    ):
        raise ProtocolViolation("W02 intervention identity mismatch")
    alias_set = set(aliases)
    for field in (
        "candidate_heads",
        "judge_oracles",
        "explicit_state_reference_oracles",
        "public_oracle_audits",
        "trajectory_metrics",
    ):
        if (
            type(intervention[field]) is not dict
            or set(intervention[field]) != alias_set
        ):
            raise ProtocolViolation(f"W02 intervention {field} coverage mismatch")
    if any(
        intervention["explicit_state_reference_oracles"][alias] is not None
        for alias in aliases
    ):
        raise ProtocolViolation("W02 falsely claims an explicit-state reference oracle")
    predicted_utilities: list[float] = []
    oracle_utilities: list[float] = []
    for alias in aliases:
        if (
            intervention["candidate_heads"][alias]
            != live_expected["heads"]["initial_rollouts"][alias]
        ):
            raise ProtocolViolation(
                f"W02 intervention {alias} differs from the live rollout head"
            )
        head = _verify_head(
            intervention["candidate_heads"][alias],
            operation="rollout",
            state_hash=initial_record["state_hash"],
            manifest_digest=manifest_digest,
            label=f"W02 intervention {alias}",
        )
        query = intervention["candidate_heads"][alias]["query"]
        requested = tuple(query["requested_observables"])
        predicted, utility = _point_rollout(head, requested)
        judge = _verify_oracle_query_binding(
            intervention["judge_oracles"][alias],
            query,
            f"W02 intervention {alias} judge oracle",
        )
        if (
            intervention["judge_oracles"][alias]
            != live_expected["judge_oracles"]["initial"][alias]
        ):
            raise ProtocolViolation(
                f"W02 intervention {alias} judge oracle differs from live runtime"
            )
        truth = _w02_oracle_mean_matrix(judge, requested)
        expected_trajectory = _trajectory_metric_wire(predicted, truth)
        _metric_equal(
            intervention["trajectory_metrics"][alias],
            expected_trajectory,
            f"W02 intervention {alias} trajectory",
        )
        if expected_trajectory["normalized_rmse"] != 0.0:
            raise ProtocolViolation("W02 privileged intervention mean is not exact")
        _verify_public_oracle_audit(
            intervention["public_oracle_audits"][alias],
            query_wire=query,
            label_order=labels,
            label=f"W02 intervention {alias} public audit",
        )
        if (
            intervention["public_oracle_audits"][alias]
            != live_expected["public_audits"][alias]
        ):
            raise ProtocolViolation(
                f"W02 intervention {alias} public audit differs from live oracles"
            )
        predicted_utilities.append(utility)
        oracle_utilities.append(_finite(judge["expected_utility"], "W02 judge utility"))
    if (
        predicted_utilities != intervention["predicted_utilities"]
        or oracle_utilities != intervention["oracle_utilities"]
    ):
        raise ProtocolViolation("W02 intervention utility extraction mismatch")
    expected_regret = _regret_metric_wire(predicted_utilities, oracle_utilities)
    degraded_regret = _degraded_regret(oracle_utilities)
    _metric_equal(intervention["metric"], expected_regret, "W02 intervention regret")
    _metric_equal(
        intervention["degraded_control_metric"],
        degraded_regret,
        "W02 intervention degraded regret",
    )
    if expected_regret["worst_regret"] != 0.0 or degraded_regret["worst_regret"] <= 0.0:
        raise ProtocolViolation("W02 intervention regret direction failed")

    update = _closed(
        by_id["W02.update"],
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
        "W02 update cell",
    )
    if (
        update["world_slot"] != "W02"
        or update["task"] != "recursive_update"
        or update["state_hash"] != updated_record["state_hash"]
        or update["prior_state_hash"] != initial_record["state_hash"]
        or update["parent_state_hash"] != initial_record["state_hash"]
        or update["delta"] != live_expected["delta"]
        or digest_json(update["delta"]) != update["delta_digest"]
        or update["delta_digest"] != updated_record["delta_digest"]
    ):
        raise ProtocolViolation("W02 update cell does not close the lineage")

    boundary = _closed(
        report["information_boundary"],
        {
            "protocol",
            "formal_diagnosis_target",
            "privileged_true_class",
            "public_belief",
            "vectors_are_distinct",
            "substitution_forbidden",
        },
        "W02 information boundary",
    )
    privileged = _closed(
        boundary["privileged_true_class"],
        {
            "role",
            "probabilities",
            "one_hot",
            "candidate_eligible",
            "candidate_capability_claimed",
        },
        "W02 privileged identity evidence",
    )
    public = _closed(
        boundary["public_belief"],
        {
            "role",
            "probabilities",
            "non_degenerate",
            "candidate_output",
            "candidate_capability_claimed",
        },
        "W02 public belief evidence",
    )
    initial_public_audit = by_id["W02.initial.privileged_true_class_identity"][
        "public_oracle_audit"
    ]
    expected_public = initial_public_audit["public_posterior"]
    if (
        boundary["protocol"] != "ucm-w02-upper-bound-information-boundary/1"
        or boundary["formal_diagnosis_target"] != "public_posterior"
        or boundary["vectors_are_distinct"] is not True
        or boundary["substitution_forbidden"] is not True
        or privileged
        != {
            "role": "parent_only_identity_sanity_not_candidate_capability",
            "probabilities": initial_probabilities,
            "one_hot": True,
            "candidate_eligible": False,
            "candidate_capability_claimed": False,
        }
        or public
        != {
            "role": "public_oracle_audit_not_candidate_output",
            "probabilities": expected_public,
            "non_degenerate": True,
            "candidate_output": False,
            "candidate_capability_claimed": False,
        }
        or initial_probabilities == expected_public
    ):
        raise ProtocolViolation("W02 public/privileged evidence was substituted")

    summary = _closed(
        report["verification_summary"],
        {
            "status",
            "cell_count",
            "state_binding_count",
            "source_distinct_explicit_state_oracle_pairs",
            "source_distinct_public_oracle_audit_pairs",
            "ledger_credit",
            "formalization_blockers",
        },
        "W02 verification summary",
    )
    if summary != {
        "status": "VALID_PRE_FREEZE_SANITY_BUNDLE",
        "cell_count": 6,
        "state_binding_count": 2,
        "source_distinct_explicit_state_oracle_pairs": 0,
        "source_distinct_public_oracle_audit_pairs": 3,
        "ledger_credit": 0,
        "formalization_blockers": _FORMALIZATION_BLOCKERS,
    }:
        raise ProtocolViolation("W02 verification summary was overstated")


def _load_canonical_report(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"{path} is not JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise SystemExit(f"{path} is not canonical JSON")
    return value


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run or verify the PRE-FREEZE W02 upper-bound sanity bundle."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="collect into a new file")
    mode.add_argument("--verify-bundle", type=Path, help="verify an existing bundle")
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_W02_ARTIFACT)
    parser.add_argument("--generator-seed", type=int, default=92024)
    parser.add_argument("--episode-index", type=int, default=36)
    parser.add_argument(
        "--replay-runtime",
        action="store_true",
        help="compatibility flag; verification always performs live replay",
    )
    args = parser.parse_args()
    if args.output is not None:
        report = run_w02_upper_bound_sanity(
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
    report = _load_canonical_report(args.verify_bundle)
    verify_w02_upper_bound_sanity(
        report,
        source_artifact=args.source_artifact,
        replay_runtime=args.replay_runtime,
    )
    return 0


__all__ = [
    "DEFAULT_W02_ARTIFACT",
    "run_w02_upper_bound_sanity",
    "verify_w02_upper_bound_sanity",
]


if __name__ == "__main__":
    raise SystemExit(_main())
