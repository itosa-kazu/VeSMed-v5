"""Patient-bound PRE-FREEZE upper-bound sanity evaluator for W18.

W18 is the public-evidence OOD/rejection world.  This evaluator turns its
committed vertical-slice probe into replayable evaluator cells while preserving
the information boundary that makes the world useful:

* candidate state and every head contain public evidence only;
* a known but low-density extreme must not be rejected;
* publicly attributable OOD must emit ``unknown`` and abstain;
* a private unseen/known alias with the same public history must have the same
  state and is excluded from the primary forced-OOD denominator; and
* action utilities and recursive updates are bound to the same exact state
  preimages used by the diagnosis head.

The bundle is deliberately privileged, upper-bound-only and worth zero ledger
credit.  It is a harness sanity artifact, not a candidate result and not
benchmark-freeze evidence.
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
from .evaluator import _average_precision
from .metrics import binary_roc_auc, treatment_regret
from .oracle_certification import (
    NumericTolerance,
    compare_canonical_outputs,
    oracle_output_wire,
)
from .schema import (
    CandidateVisibleEvent,
    DiagnosisQuery,
    EventKind,
    RolloutQuery,
    VisibleDelta,
)
from .state import StateClass, StatePayload, seal_state
from .true_state_probe_w18 import (
    W18PublicOODProbe,
    _attributable_delta,
    _policy,
    run_w18_ood_slice,
)
from .upper_bound_evaluator import (
    STATUS_CHAIN,
    _attach_bundle_root,
    _cell_root,
    _closed,
    _digest,
    _finite,
    _head_wire,
    _state_binding,
    _verify_state_binding,
    compute_upper_bound_bundle_root,
)
from .worlds.w18 import W18World


PROTOCOL = "ucm-pre-freeze-upper-bound-sanity-w18/1"
PUBLIC_ORACLE_PREIMAGE_PROTOCOL = "ucm-w18-public-state-oracle-preimage/1"
DIAGNOSIS_ORACLE_PROTOCOL = "ucm-w18-public-diagnosis-oracle/1"
OOD_COLLECTOR_PROTOCOL = "ucm-w18-ood-collector-metrics/1"
ACTION_COLLECTOR_PROTOCOL = "ucm-w18-action-utility-collector/1"
DEFAULT_W18_ARTIFACT = Path(
    "results/unified_map/pre_freeze/20260717-w18-public-ood-probe/vertical-slice.json"
)

_LABELS = ("C0", "C1", "unknown")
_POLICY_ALIASES = ("no_new_action", "do_A1")
_SOURCE_PROTOCOL = "ucm-phase2-w18-public-ood-slice/1"
_ORACLE_TOLERANCE = NumericTolerance(absolute=3e-4, relative=3e-4)


def _diagnosis_probabilities(head: dict[str, Any]) -> dict[str, float]:
    result = head["execution"]["response"]["result"]
    probabilities = result.get("probabilities")
    if type(probabilities) is not dict or set(probabilities) != set(_LABELS):
        raise ProtocolViolation("W18 diagnosis probability labels mismatch")
    normalized = {
        label: _finite(probabilities[label], f"W18 diagnosis probability {label}")
        for label in _LABELS
    }
    if any(
        value < 0.0 or value > 1.0 for value in normalized.values()
    ) or not np.isclose(sum(normalized.values()), 1.0, atol=1e-12, rtol=0.0):
        raise ProtocolViolation("W18 diagnosis probabilities are not normalized")
    return normalized


def _diagnosis_abstain(head: dict[str, Any]) -> bool:
    metadata = head["execution"]["response"]["result"].get("metadata")
    if type(metadata) is not dict or type(metadata.get("abstain")) is not bool:
        raise ProtocolViolation("W18 diagnosis abstention metadata is malformed")
    if (
        metadata.get("baseline_id") != "B01"
        or metadata.get("eligibility") != "upper_bound_only"
        or metadata.get("public_evidence_only") is not True
        or metadata.get("public_ood_attribution")
        not in {"KNOWN_SUPPORT_PRESENT", "OOD_ATTRIBUTABLE"}
    ):
        raise ProtocolViolation("W18 diagnosis metadata crosses the public boundary")
    return bool(metadata["abstain"])


def _diagnosis_oracle_record(
    *,
    state_binding: dict[str, Any],
    query: DiagnosisQuery,
    reference_probabilities: dict[str, float],
) -> dict[str, Any]:
    representation = deepcopy(state_binding["payload"]["representation"])
    preimage = {
        "protocol": PUBLIC_ORACLE_PREIMAGE_PROTOCOL,
        "operation": "diagnose",
        "state_hash": state_binding["record"]["state_hash"],
        "public_state": representation,
        "query": query.to_wire(),
    }
    posterior = representation["mechanism_posterior"]
    probabilities = {
        "C0": float(posterior["C0"]),
        "C1": float(posterior["C1"]),
        "unknown": float(posterior["C2"] + posterior["Cdev"]),
    }
    attribution = representation["public_ood_attribution"]
    differences = [
        abs(probabilities[label] - float(reference_probabilities[label]))
        for label in _LABELS
    ]
    return {
        "preimage": preimage,
        "preimage_digest": digest_json(preimage),
        "output": {
            "protocol": DIAGNOSIS_ORACLE_PROTOCOL,
            "probabilities": probabilities,
            "public_ood_attribution": attribution,
            "abstain": attribution == "OOD_ATTRIBUTABLE",
        },
        "reference_probabilities": {
            label: float(reference_probabilities[label]) for label in _LABELS
        },
        "reference_comparison": {
            "passed": max(differences) <= _ORACLE_TOLERANCE.absolute,
            "max_absolute_error": max(differences),
            "absolute_tolerance": _ORACLE_TOLERANCE.absolute,
        },
    }


def _rollout_oracle_record(
    *,
    world: W18World,
    state_binding: dict[str, Any],
    query: RolloutQuery,
    reference_episode: Any,
) -> dict[str, Any]:
    representation = deepcopy(state_binding["payload"]["representation"])
    preimage = {
        "protocol": PUBLIC_ORACLE_PREIMAGE_PROTOCOL,
        "operation": "rollout",
        "state_hash": state_binding["record"]["state_hash"],
        "public_state": representation,
        "query": query.to_wire(),
    }
    observations = representation["latest_observations"]
    production = oracle_output_wire(
        world.public_state_counterfactual(
            observations["obs_0"],
            observations["obs_1"],
            query.plan,
            query.horizon,
        ),
        include_numerical_diagnostics=False,
    )
    reference = oracle_output_wire(
        world.reference_counterfactual(
            reference_episode, query.plan, query.horizon, oracle_seed=17
        ),
        include_numerical_diagnostics=False,
    )
    comparison = compare_canonical_outputs(
        production, reference, _ORACLE_TOLERANCE
    ).to_wire()
    return {
        "preimage": preimage,
        "preimage_digest": digest_json(preimage),
        "production_output": production,
        "reference_output": reference,
        "reference_comparison": comparison,
    }


def _utility_from_head(head: dict[str, Any]) -> float:
    result = head["execution"]["response"]["result"]
    utility = result.get("utility_prediction")
    if type(utility) is not dict or set(utility) != {
        "family",
        "recommendation",
        "value",
    }:
        raise ProtocolViolation("W18 utility prediction is not closed")
    if utility["family"] != "public-reference-mixture" or utility[
        "recommendation"
    ] not in {"evaluate-actions", "abstain"}:
        raise ProtocolViolation("W18 utility prediction identity mismatch")
    return _finite(utility["value"], "W18 expected utility")


def _rollout_abstain(head: dict[str, Any]) -> bool:
    result = head["execution"]["response"]["result"]
    metadata = result.get("metadata")
    utility = result.get("utility_prediction")
    if type(metadata) is not dict or type(utility) is not dict:
        raise ProtocolViolation("W18 rollout metadata is malformed")
    abstain = metadata.get("abstain")
    if type(abstain) is not bool:
        raise ProtocolViolation("W18 rollout abstain must be boolean")
    if (utility.get("recommendation") == "abstain") is not abstain:
        raise ProtocolViolation("W18 rollout abstention contradicts recommendation")
    return abstain


def _assert_rollout_matches_oracle(
    head: dict[str, Any], oracle_record: dict[str, Any]
) -> None:
    result = head["execution"]["response"]["result"]
    query = head["query"]
    oracle = oracle_record["production_output"]
    if oracle.get("policy") != query.get("plan") or oracle.get("horizon") != query.get(
        "horizon"
    ):
        raise ProtocolViolation("W18 public oracle does not bind the rollout query")
    if _utility_from_head(head) != _finite(
        oracle.get("expected_utility"), "W18 oracle expected utility"
    ):
        raise ProtocolViolation("W18 candidate and public-oracle utilities disagree")
    requested = query.get("requested_observables")
    predictions = result.get("observable_predictions")
    components = oracle.get("observation_distribution", {}).get("components")
    if (
        type(requested) is not list
        or type(predictions) is not dict
        or set(predictions) != set(requested)
        or type(components) is not list
    ):
        raise ProtocolViolation("W18 rollout/oracle observable coverage mismatch")
    for channel in requested:
        expected = {
            "family": "bounded-affine-mixture",
            "components": [
                {
                    "label": component["public_component"],
                    "weight": float(component["weight"]),
                    "values": [
                        float(step[f"{channel}_mean"]) for step in component["steps"]
                    ],
                }
                for component in components
            ],
        }
        if digest_json(predictions[channel]) != digest_json(expected):
            raise ProtocolViolation(
                "W18 rollout projection is not collector-derived from public oracle"
            )


def _regret_wire(
    predicted_utilities: list[float], oracle_utilities: list[float]
) -> dict[str, Any]:
    metric = treatment_regret(
        [predicted_utilities], [oracle_utilities], catastrophic_margin=0.75
    )
    wire = asdict(metric)
    wire["chosen_actions"] = list(metric.chosen_actions)
    return wire


def _degraded_regret_wire(oracle_utilities: list[float]) -> dict[str, Any]:
    worst = int(np.argmin(np.asarray(oracle_utilities, dtype=float)))
    adversarial = [0.0] * len(oracle_utilities)
    adversarial[worst] = 1.0
    return _regret_wire(adversarial, oracle_utilities)


def _sealed_state_from_binding(value: object) -> Any:
    binding = _verify_state_binding(value, "W18 replay initial state")
    payload_wire = binding["payload"]
    record = binding["record"]
    payload = StatePayload.from_json(
        payload_wire["representation"],
        schema_version=payload_wire["schema_version"],
        state_class=StateClass(payload_wire["state_class"]),
    )
    reconstructed = seal_state(
        payload,
        candidate_bundle_digest=record["candidate_bundle_digest"],
        model_digest=record["model_digest"],
        scope_digest=record["scope_digest"],
        catalog_digest=record["catalog_digest"],
        as_of_available_at=record["as_of_available_at"],
        operation=record["operation"],
        parent_state_hash=record["parent_state_hash"],
        delta_digest=record["delta_digest"],
        state_instance_id="w18-standalone-update-verifier",
    )
    if _state_binding(reconstructed) != binding:
        raise ProtocolViolation(
            "W18 state binding cannot reconstruct its sealed preimage"
        )
    return reconstructed


def _visible_delta_from_wire(value: object) -> VisibleDelta:
    wire = _closed(value, {"protocol", "advance_to", "events"}, "W18 reported delta")
    if wire["protocol"] != "ucm-visible-delta/1":
        raise ProtocolViolation("W18 reported delta protocol mismatch")
    if type(wire["events"]) is not list:
        raise ProtocolViolation("W18 reported delta events must be a list")
    events = []
    for index, raw in enumerate(wire["events"]):
        event = _closed(
            raw,
            {
                "kind",
                "occurred_at",
                "collected_at",
                "available_at",
                "event_uid",
                "payload",
            },
            f"W18 reported delta event {index}",
        )
        try:
            kind = EventKind(event["kind"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("W18 reported delta event kind is invalid") from exc
        parsed = CandidateVisibleEvent(
            kind=kind,
            occurred_at=event["occurred_at"],
            collected_at=event["collected_at"],
            available_at=event["available_at"],
            event_uid=event["event_uid"],
            payload=deepcopy(event["payload"]),
        )
        if parsed.to_wire() != event:
            raise ProtocolViolation("W18 reported delta event is not canonical")
        events.append(parsed)
    parsed_delta = VisibleDelta(wire["advance_to"], tuple(events))
    if parsed_delta.to_wire() != wire:
        raise ProtocolViolation("W18 reported delta is not canonical")
    return parsed_delta


def _diagnosis_cell(
    *,
    cell_id: str,
    cut_alias: str,
    state: Any,
    execution: Any,
    query: DiagnosisQuery,
    world: W18World,
    oracle_episode: Any,
) -> dict[str, Any]:
    truth = _ood_scoring_truth(world, oracle_episode)
    binding = _state_binding(state)
    head = _head_wire(execution, query)
    oracle = _diagnosis_oracle_record(
        state_binding=binding,
        query=query,
        reference_probabilities=world.reference_public_posterior(oracle_episode),
    )
    probabilities = _diagnosis_probabilities(head)
    abstain = _diagnosis_abstain(head)
    if (
        probabilities != oracle["output"]["probabilities"]
        or abstain is not oracle["output"]["abstain"]
    ):
        raise ProtocolViolation("W18 diagnosis head disagrees with public-state oracle")
    return {
        "cell_id": cell_id,
        "world_slot": "W18",
        "cut_alias": cut_alias,
        "task": "ood_detection",
        "state_hash": state.record.state_hash,
        "candidate_head": head,
        "public_state_oracle": oracle,
        "oracle_scoring": {
            **truth,
            "truth_derivation": "W18World.attribution_tag+scored_for_forced_ood",
            "private_attribution_used_as_candidate_input": False,
        },
        "collector_row": {
            "unknown_score": probabilities["unknown"],
            "abstain": abstain,
        },
    }


def _ood_scoring_truth(world: W18World, episode: Any) -> dict[str, Any]:
    """Derive judge labels from live W18 truth instead of caller constants."""

    attribution = world.attribution_tag(episode)
    forced_ood_positive = world.scored_for_forced_ood(attribution)
    anchor = episode.oracle_anchor
    if (
        type(anchor) is not dict
        or anchor.get("ood_attribution") != attribution
        or anchor.get("forced_ood_scored") is not forced_ood_positive
    ):
        raise ProtocolViolation(
            "W18 episode oracle anchor contradicts live attribution"
        )
    known_negative = attribution in {"KNOWN", "KNOWN_EXTREME"}
    return {
        "attribution": attribution,
        "primary_ood_scored": forced_ood_positive or known_negative,
        "positive_label": (
            1 if forced_ood_positive else (0 if known_negative else None)
        ),
        "forced_ood_positive": forced_ood_positive,
    }


def _action_cell(
    *,
    cell_id: str,
    cut_alias: str,
    state: Any,
    probe: W18PublicOODProbe,
    world: W18World,
    policies: tuple[Any, ...],
    utility_digest: str,
    reference_episode: Any,
    query_seed: int,
) -> dict[str, Any]:
    binding = _state_binding(state)
    heads: dict[str, Any] = {}
    oracles: dict[str, Any] = {}
    predicted: list[float] = []
    oracle_utilities: list[float] = []
    abstentions: list[bool] = []
    for alias, policy in zip(_POLICY_ALIASES, policies, strict=True):
        query = RolloutQuery(4, policy, ("obs_0", "obs_1"), utility_digest)
        execution = probe.rollout(state, query, query_seed=query_seed)
        head = _head_wire(execution, query)
        oracle = _rollout_oracle_record(
            world=world,
            state_binding=binding,
            query=query,
            reference_episode=reference_episode,
        )
        _assert_rollout_matches_oracle(head, oracle)
        if oracle["reference_comparison"]["passed"] is not True:
            raise ProtocolViolation("W18 production/reference public oracles disagree")
        heads[alias] = head
        oracles[alias] = oracle
        predicted.append(_utility_from_head(head))
        oracle_utilities.append(
            _finite(
                oracle["production_output"]["expected_utility"],
                "W18 oracle expected utility",
            )
        )
        abstentions.append(_rollout_abstain(head))
    abstain = all(abstentions)
    selection_scored = not any(abstentions)
    metric = _regret_wire(predicted, oracle_utilities) if selection_scored else None
    degraded = _degraded_regret_wire(oracle_utilities) if selection_scored else None
    return {
        "cell_id": cell_id,
        "world_slot": "W18",
        "cut_alias": cut_alias,
        "task": "intervention_expected_utility",
        "state_hash": state.record.state_hash,
        "policy_aliases": list(_POLICY_ALIASES),
        "candidate_heads": heads,
        "public_state_oracles": oracles,
        "predicted_utilities": predicted,
        "oracle_utilities": oracle_utilities,
        "metric": metric,
        "degraded_control_metric": degraded,
        "abstain": abstain,
        "selection_scored": selection_scored,
        "selected_action_alias": (
            None
            if any(abstentions)
            else _POLICY_ALIASES[int(np.argmax(np.asarray(predicted, dtype=float)))]
        ),
    }


def _collect_ood_metrics(cells: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [cell for cell in cells if cell["task"] == "ood_detection"]
    primary = [row for row in rows if row["oracle_scoring"]["primary_ood_scored"]]
    excluded = [row for row in rows if not row["oracle_scoring"]["primary_ood_scored"]]
    scores = [float(row["collector_row"]["unknown_score"]) for row in primary]
    labels = [int(row["oracle_scoring"]["positive_label"]) for row in primary]
    auroc: float | None = None
    average_precision: float | None = None
    if scores and set(labels) == {0, 1}:
        score_array = np.asarray(scores, dtype=float)
        label_array = np.asarray(labels, dtype=int)
        auroc = binary_roc_auc(score_array, label_array)
        average_precision = _average_precision(score_array, label_array)
    raw_rows = [
        {
            "cell_id": row["cell_id"],
            "unknown_score": row["collector_row"]["unknown_score"],
            "abstain": row["collector_row"]["abstain"],
            "positive_label": row["oracle_scoring"]["positive_label"],
        }
        for row in primary
    ]
    return {
        "protocol": OOD_COLLECTOR_PROTOCOL,
        "metric_scope": "two-point-sanity-only",
        "statistical_significance_claimed": False,
        "abstain_signal": "ok-result-metadata.abstain-pre-freeze-only",
        "positive_class": "OOD_ATTRIBUTABLE",
        "score_field": "diagnosis.probabilities.unknown",
        "primary_denominator": len(primary),
        "known_count": sum(
            row["oracle_scoring"]["positive_label"] == 0 for row in primary
        ),
        "attributable_ood_count": sum(
            row["oracle_scoring"]["positive_label"] == 1 for row in primary
        ),
        "irreducible_excluded_count": len(excluded),
        "sample_counts": {
            "primary_total": len(primary),
            "positive_attributable": sum(
                row["oracle_scoring"]["positive_label"] == 1 for row in primary
            ),
            "negative_known_extreme": sum(
                row["oracle_scoring"]["attribution"] == "KNOWN_EXTREME"
                for row in primary
            ),
            "irreducible_excluded": len(excluded),
        },
        "primary_rows": raw_rows,
        "excluded_cell_ids": [row["cell_id"] for row in excluded],
        "auroc": auroc,
        "average_precision": average_precision,
        "known_extreme_false_rejection_count": sum(
            row["oracle_scoring"]["attribution"] == "KNOWN_EXTREME"
            and row["collector_row"]["abstain"]
            for row in primary
        ),
        "attributable_ood_miss_count": sum(
            row["oracle_scoring"]["positive_label"] == 1
            and (
                not row["collector_row"]["abstain"]
                or row["collector_row"]["unknown_score"] < 0.90
            )
            for row in primary
        ),
        "irreducible_forced_ood_count": sum(
            row["collector_row"]["abstain"] for row in excluded
        ),
    }


def _collect_action_metrics(cells: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [cell for cell in cells if cell["task"] == "intervention_expected_utility"]
    return {
        "protocol": ACTION_COLLECTOR_PROTOCOL,
        "panels": [
            {
                "cell_id": row["cell_id"],
                "predicted_utilities": row["predicted_utilities"],
                "oracle_utilities": row["oracle_utilities"],
                "metric": row["metric"],
                "abstain": row["abstain"],
                "selection_scored": row["selection_scored"],
                "selected_action_alias": row["selected_action_alias"],
            }
            for row in rows
        ],
        "exact_public_utility_panel_count": sum(
            row["predicted_utilities"] == row["oracle_utilities"] for row in rows
        ),
        "scored_panel_count": sum(row["selection_scored"] for row in rows),
        "abstained_panel_count": sum(row["abstain"] for row in rows),
        "scored_mean_regret": (
            float(
                np.mean(
                    [
                        row["metric"]["mean_regret"]
                        for row in rows
                        if row["selection_scored"]
                    ]
                )
            )
            if any(row["selection_scored"] for row in rows)
            else None
        ),
        "unsafe_non_abstain_count": sum(
            row["cut_alias"] == "attributable-updated" and not row["abstain"]
            for row in rows
        ),
    }


def _runtime_material() -> dict[str, Any]:
    world = W18World()
    probe = W18PublicOODProbe(world)
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    utility_digest = digest_json(["W18", "public-reference-utility", 4])
    policies = (_policy(world, None), _policy(world, "A1"))

    unseen, known_alias = world.irreducible_alias_pair(seed=1803)
    initial = probe.initialize_public_episode(unseen)
    initial_known_alias = probe.initialize_public_episode(known_alias)
    delta = _attributable_delta()
    updated = probe.update_public(initial, delta, inference_seed=3)
    attributable_reference = world.attributable_ood_fixture(seed=1801)
    extreme_episode = world.known_extreme_fixture(seed=1805)
    extreme = probe.initialize_public_episode(extreme_episode)

    states = {
        "initial": _state_binding(initial),
        "initial_known_alias": _state_binding(initial_known_alias),
        "updated": _state_binding(updated),
        "known_extreme": _state_binding(extreme),
    }
    diagnosis_cells = [
        _diagnosis_cell(
            cell_id="W18.irreducible_alias.ood",
            cut_alias="irreducible-alias",
            state=initial,
            execution=probe.diagnose(initial, diagnosis_query, query_seed=1),
            query=diagnosis_query,
            world=world,
            oracle_episode=unseen,
        ),
        _diagnosis_cell(
            cell_id="W18.attributable_updated.ood",
            cut_alias="attributable-updated",
            state=updated,
            execution=probe.diagnose(updated, diagnosis_query, query_seed=4),
            query=diagnosis_query,
            world=world,
            oracle_episode=attributable_reference,
        ),
        _diagnosis_cell(
            cell_id="W18.known_extreme.ood",
            cut_alias="known-extreme",
            state=extreme,
            execution=probe.diagnose(extreme, diagnosis_query, query_seed=6),
            query=diagnosis_query,
            world=world,
            oracle_episode=extreme_episode,
        ),
    ]
    action_cells = [
        _action_cell(
            cell_id="W18.irreducible_alias.intervention",
            cut_alias="irreducible-alias",
            state=initial,
            probe=probe,
            world=world,
            policies=policies,
            utility_digest=utility_digest,
            reference_episode=unseen,
            query_seed=2,
        ),
        _action_cell(
            cell_id="W18.attributable_updated.intervention",
            cut_alias="attributable-updated",
            state=updated,
            probe=probe,
            world=world,
            policies=policies,
            utility_digest=utility_digest,
            reference_episode=attributable_reference,
            query_seed=5,
        ),
        _action_cell(
            cell_id="W18.known_extreme.intervention",
            cut_alias="known-extreme",
            state=extreme,
            probe=probe,
            world=world,
            policies=policies,
            utility_digest=utility_digest,
            reference_episode=extreme_episode,
            query_seed=7,
        ),
    ]
    update_cell = {
        "cell_id": "W18.update",
        "world_slot": "W18",
        "cut_alias": "irreducible-to-attributable",
        "task": "recursive_update",
        "state_hash": updated.record.state_hash,
        "prior_state_hash": initial.record.state_hash,
        "parent_state_hash": updated.record.parent_state_hash,
        "delta": delta.to_wire(),
        "delta_digest": digest_json(delta.to_wire()),
    }
    cells = [*diagnosis_cells, *action_cells, update_cell]
    collector_metrics = {
        "ood": _collect_ood_metrics(cells),
        "action_utility": _collect_action_metrics(cells),
    }
    return {
        "world": world,
        "probe": probe,
        "states": states,
        "cells": cells,
        "collector_metrics": collector_metrics,
        "delta": delta,
        "fixtures": {
            "irreducible_alias_seed": 1803,
            "known_extreme_seed": 1805,
            "attributable_reference_seed": 1801,
            "irreducible_public_history_digest": unseen.public_history.digest,
            "known_alias_public_history_digest": known_alias.public_history.digest,
            "known_extreme_public_history_digest": extreme_episode.public_history.digest,
        },
    }


def run_w18_upper_bound_sanity(
    *, source_artifact: Path | str = DEFAULT_W18_ARTIFACT
) -> dict[str, Any]:
    """Replay W18 bytes and collect the patient-bound sanity cells."""

    source_path = Path(source_artifact)
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(
            f"W18 source artifact is unavailable: {source_path}"
        ) from exc
    try:
        source_wire = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("W18 source artifact is not JSON") from exc
    if canonical_json_bytes(source_wire) != source_bytes:
        raise ProtocolViolation("W18 source artifact is not canonical JSON")
    replay_bytes = canonical_json_bytes(run_w18_ood_slice())
    if source_bytes != replay_bytes:
        raise ProtocolViolation("W18 committed vertical slice does not byte-replay")

    runtime = _runtime_material()
    probe = runtime["probe"]
    cells = runtime["cells"]
    body = {
        "protocol": PROTOCOL,
        "bundle_kind": "phase2_privileged_probe_evaluator",
        "world_slot": "W18",
        "status_chain": deepcopy(STATUS_CHAIN),
        "scope_statement": {
            "public_evidence_candidate_state_only": True,
            "private_attribution_is_judge_only": True,
            "irreducible_alias_excluded_from_primary_ood": True,
            "public_reference_utility_only": True,
            "statistical_significance_claimed": False,
            "formal_result_status_abstain_claimed": False,
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
        "manifest_digest": probe.manifest.digest,
        "fixture": runtime["fixtures"],
        "states": runtime["states"],
        "cells": cells,
        "cell_set_root": _cell_root(cells),
        "collector_metrics": runtime["collector_metrics"],
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_SANITY_BUNDLE",
            "cell_count": len(cells),
            "state_binding_count": len(runtime["states"]),
            "primary_ood_denominator": 2,
            "irreducible_excluded_count": 1,
            "ood_sample_counts": {
                "primary_total": 2,
                "positive_attributable": 1,
                "negative_known_extreme": 1,
                "irreducible_excluded": 1,
            },
            "statistical_significance_claimed": False,
            "source_distinct_oracle_cells": 9,
            "ledger_credit": 0,
            "formalization_blockers": [
                "not-a-frozen-expected-cell-corpus",
                "privileged-upper-bound-only",
                "public-reference-utility-not-private-patient-utility",
                "three-fixture-sanity-panel-only",
                "probe-ok-plus-metadata-abstain-not-formal-result-status",
            ],
        },
    }
    result = _attach_bundle_root(body)
    verify_w18_upper_bound_sanity(result)
    return result


def verify_w18_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    """Recompute W18 state/query/head/oracle/metric claims fail-closed."""

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
            "collector_metrics",
            "verification_summary",
            "bundle_root",
        },
        "W18 upper-bound sanity report",
    )
    validate_json_like(report)
    if (
        report["protocol"] != PROTOCOL
        or report["bundle_kind"] != "phase2_privileged_probe_evaluator"
        or report["world_slot"] != "W18"
        or report["status_chain"] != STATUS_CHAIN
    ):
        raise ProtocolViolation("W18 upper-bound status or identity was rewritten")
    if report["bundle_root"] != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation("W18 upper-bound bundle root mismatch")
    expected_scope = {
        "public_evidence_candidate_state_only": True,
        "private_attribution_is_judge_only": True,
        "irreducible_alias_excluded_from_primary_ood": True,
        "public_reference_utility_only": True,
        "statistical_significance_claimed": False,
        "formal_result_status_abstain_claimed": False,
        "candidate_performance_claimed": False,
        "formal_b01_claimed": False,
    }
    if report["scope_statement"] != expected_scope:
        raise ProtocolViolation("W18 upper-bound scope was overstated")

    manifest = report["manifest"]
    if digest_json(manifest) != report["manifest_digest"]:
        raise ProtocolViolation("W18 manifest digest mismatch")
    if (
        type(manifest) is not dict
        or manifest.get("world_slot") != "W18"
        or manifest.get("baseline_id") != "B01"
        or manifest.get("privileged") is not True
        or manifest.get("eligibility") != "upper_bound_only"
        or manifest.get("freeze_grade") is not False
        or manifest.get("state_evidence") != "public-observations-only"
        or manifest.get("private_mechanism_policy") != "excluded"
    ):
        raise ProtocolViolation("W18 manifest violates the public-state boundary")

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
        "W18 source anchor",
    )
    _digest(source["artifact_digest"], "W18 source artifact digest")
    _digest(source["replay_digest"], "W18 source replay digest")
    if (
        source["artifact_digest"] != source["replay_digest"]
        or source["artifact_protocol"] != _SOURCE_PROTOCOL
        or source["byte_identical_replay"] is not True
        or type(source["artifact_bytes"]) is not int
        or source["artifact_bytes"] <= 0
    ):
        raise ProtocolViolation("W18 source artifact replay anchor mismatch")
    expected_source_path = (
        Path(source_artifact) if source_artifact is not None else DEFAULT_W18_ARTIFACT
    )
    if source["artifact_relpath"] != expected_source_path.as_posix():
        raise ProtocolViolation("W18 source artifact path does not match the verifier")
    committed_path = Path(__file__).resolve().parents[2] / DEFAULT_W18_ARTIFACT
    try:
        committed_raw = committed_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation("committed W18 source artifact is unavailable") from exc
    try:
        committed_wire = json.loads(committed_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("committed W18 source artifact is not JSON") from exc
    if canonical_json_bytes(committed_wire) != committed_raw:
        raise ProtocolViolation("committed W18 source artifact is not canonical")
    live_replay = canonical_json_bytes(run_w18_ood_slice())
    if (
        digest_bytes(committed_raw) != source["artifact_digest"]
        or len(committed_raw) != source["artifact_bytes"]
        or live_replay != committed_raw
        or digest_bytes(live_replay) != source["replay_digest"]
    ):
        raise ProtocolViolation(
            "report is not bound to the live committed W18 source artifact"
        )
    if source_artifact is not None:
        source_path = expected_source_path
        try:
            raw = source_path.read_bytes()
        except OSError as exc:
            raise ProtocolViolation("bound W18 source artifact is unavailable") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("bound W18 source artifact is not JSON") from exc
        if canonical_json_bytes(decoded) != raw:
            raise ProtocolViolation("bound W18 source artifact is not canonical")
        if raw != committed_raw:
            raise ProtocolViolation(
                "bound W18 source differs from the committed artifact"
            )
        if (
            digest_bytes(raw) != source["artifact_digest"]
            or len(raw) != source["artifact_bytes"]
        ):
            raise ProtocolViolation("bound W18 source bytes do not match report")
        if replay_runtime and live_replay != raw:
            raise ProtocolViolation("bound W18 source artifact does not replay live")

    runtime = _runtime_material()
    if report["manifest"] != runtime["probe"].manifest.to_wire():
        raise ProtocolViolation("W18 manifest is not the live probe manifest")
    if report["fixture"] != runtime["fixtures"]:
        raise ProtocolViolation("W18 fixture identity was rewritten")
    if report["states"] != runtime["states"]:
        raise ProtocolViolation("W18 state/hash preimages are not live-derived")
    states = report["states"]
    initial_hash = states["initial"]["record"]["state_hash"]
    alias_hash = states["initial_known_alias"]["record"]["state_hash"]
    updated_record = states["updated"]["record"]
    if initial_hash != alias_hash:
        raise ProtocolViolation("W18 irreducible private aliases split public state")
    if (
        updated_record["parent_state_hash"] != initial_hash
        or updated_record["state_hash"] == initial_hash
        or updated_record["delta_digest"] != digest_json(runtime["delta"].to_wire())
    ):
        raise ProtocolViolation("W18 recursive update lineage is not closed")
    # Defence in depth: candidate-input representations are the exact closed
    # public-state schema.  Judge-only attribution strings occur only in the
    # scoring cells and never in a state/query/head preimage.
    for name, binding in states.items():
        representation = binding["payload"]["representation"]
        if set(representation) != {
            "protocol",
            "world_slot",
            "as_of_available_at",
            "latest_observations",
            "mechanism_posterior",
            "known_support",
            "public_ood_attribution",
        }:
            raise ProtocolViolation(f"W18 {name} state contains non-public fields")

    cells = report["cells"]
    if type(cells) is not list or len(cells) != 7:
        raise ProtocolViolation("W18 sanity requires exactly seven cells")
    if _cell_root(cells) != report["cell_set_root"]:
        raise ProtocolViolation("W18 sanity cell set root mismatch")
    if cells != runtime["cells"]:
        raise ProtocolViolation(
            "W18 cells are not live-derived from exact state/query/head/oracle preimages"
        )
    expected_ids = {
        "W18.irreducible_alias.ood",
        "W18.attributable_updated.ood",
        "W18.known_extreme.ood",
        "W18.irreducible_alias.intervention",
        "W18.attributable_updated.intervention",
        "W18.known_extreme.intervention",
        "W18.update",
    }
    if {cell["cell_id"] for cell in cells} != expected_ids:
        raise ProtocolViolation("W18 sanity cell coverage mismatch")

    # Independently replay the reported canonical delta from the reported
    # initial-state preimage.  This is deliberately separate from the live
    # fixture equality check above: changing and re-signing delta bytes cannot
    # preserve the updated state merely because both claims are self-consistent.
    by_id = {cell["cell_id"]: cell for cell in cells}
    update = by_id["W18.update"]
    parsed_delta = _visible_delta_from_wire(update["delta"])
    reconstructed_initial = _sealed_state_from_binding(states["initial"])
    replayed_updated = runtime["probe"].update_public(
        reconstructed_initial, parsed_delta, inference_seed=3
    )
    if _state_binding(replayed_updated) != states["updated"]:
        raise ProtocolViolation(
            "W18 reported delta does not independently replay update"
        )

    collector = runtime["collector_metrics"]
    if report["collector_metrics"] != collector:
        raise ProtocolViolation("W18 metrics are not collector-derived")
    ood = collector["ood"]
    if (
        ood["primary_denominator"] != 2
        or ood["known_count"] != 1
        or ood["attributable_ood_count"] != 1
        or ood["irreducible_excluded_count"] != 1
        or ood["metric_scope"] != "two-point-sanity-only"
        or ood["statistical_significance_claimed"] is not False
        or ood["abstain_signal"] != "ok-result-metadata.abstain-pre-freeze-only"
        or ood["sample_counts"]
        != {
            "primary_total": 2,
            "positive_attributable": 1,
            "negative_known_extreme": 1,
            "irreducible_excluded": 1,
        }
        or ood["auroc"] != 1.0
        or ood["average_precision"] != 1.0
        or ood["known_extreme_false_rejection_count"] != 0
        or ood["attributable_ood_miss_count"] != 0
        or ood["irreducible_forced_ood_count"] != 0
    ):
        raise ProtocolViolation("W18 OOD direction or denominator contract failed")
    action = collector["action_utility"]
    if (
        action["exact_public_utility_panel_count"] != 3
        or action["scored_panel_count"] != 2
        or action["abstained_panel_count"] != 1
        or action["scored_mean_regret"] != 0.0
        or action["unsafe_non_abstain_count"] != 0
        or any(
            panel["metric"]["worst_regret"] != 0.0
            for panel in action["panels"]
            if panel["selection_scored"]
        )
        or any(
            panel["metric"] is not None
            for panel in action["panels"]
            if panel["abstain"]
        )
    ):
        raise ProtocolViolation("W18 action utility direction failed")

    expected_summary = {
        "status": "VALID_PRE_FREEZE_SANITY_BUNDLE",
        "cell_count": 7,
        "state_binding_count": 4,
        "primary_ood_denominator": 2,
        "irreducible_excluded_count": 1,
        "ood_sample_counts": {
            "primary_total": 2,
            "positive_attributable": 1,
            "negative_known_extreme": 1,
            "irreducible_excluded": 1,
        },
        "statistical_significance_claimed": False,
        "source_distinct_oracle_cells": 9,
        "ledger_credit": 0,
        "formalization_blockers": [
            "not-a-frozen-expected-cell-corpus",
            "privileged-upper-bound-only",
            "public-reference-utility-not-private-patient-utility",
            "three-fixture-sanity-panel-only",
            "probe-ok-plus-metadata-abstain-not-formal-result-status",
        ],
    }
    if report["verification_summary"] != expected_summary:
        raise ProtocolViolation("W18 verification summary was overstated")


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run or verify the PRE-FREEZE W18 upper-bound sanity bundle."
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path)
    mode.add_argument("--verify-input", type=Path)
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_W18_ARTIFACT)
    args = parser.parse_args()
    if args.verify_input is not None:
        try:
            raw = args.verify_input.read_bytes()
            report = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SystemExit(f"cannot read W18 sanity bundle: {exc}") from exc
        if canonical_json_bytes(report) != raw:
            raise SystemExit("W18 sanity bundle is not canonical JSON")
        verify_w18_upper_bound_sanity(
            report, source_artifact=args.source_artifact, replay_runtime=True
        )
        return 0

    report = run_w18_upper_bound_sanity(source_artifact=args.source_artifact)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(report))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "DEFAULT_W18_ARTIFACT",
    "PROTOCOL",
    "STATUS_CHAIN",
    "compute_upper_bound_bundle_root",
    "run_w18_upper_bound_sanity",
    "verify_w18_upper_bound_sanity",
]


if __name__ == "__main__":
    raise SystemExit(_main())
