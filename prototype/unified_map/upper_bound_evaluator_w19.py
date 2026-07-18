"""Typed PRE-FREEZE W19 rare-contraindication evaluator.

The W19 probe is an upper-bound harness check, not a candidate experiment.
This evaluator replays the committed vertical slice byte-for-byte, binds every
query and head to one shared public-belief state, and independently derives the
rare-tail posterior and safety-panel decision from canonical raw evidence
bytes.  It does not certify a source-distinct oracle, full-policy optimality,
full outcome-distribution CVaR, or recursive-filter sufficiency.
"""

from __future__ import annotations

from copy import deepcopy
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
from .oracle_certification import oracle_output_wire
from .schema import DiagnosisQuery, RolloutQuery
from .true_state_probe_w19 import (
    W19PublicTailProbe,
    _marker_response_delta,
    _policy,
    run_w19_tail_slice,
)
from .upper_bound_evaluator import (
    PROTOCOL,
    STATUS_CHAIN,
    _cell_root,
    _closed,
    _digest,
    _head_wire,
    _state_binding,
    _verify_head,
    _verify_state_binding,
    compute_upper_bound_bundle_root,
)
from .worlds.w19 import W19World, _truncated_uniform_gaussian_moments


DEFAULT_W19_ARTIFACT = Path(
    "results/unified_map/pre_freeze/"
    "20260717-w19-rare-contraindication-probe/vertical-slice.json"
)
_ALIASES = ("no_new_action", "do_A1", "do_A2")
_TAIL_RATE = 1.0 / 64.0
_MARKER_SENSITIVITY = 0.98
_MARKER_FALSE_POSITIVE = 0.02
_CATASTROPHIC_REGRET_MARGIN = 10.0


def _raw_row(wire: dict[str, Any]) -> dict[str, Any]:
    raw = canonical_json_bytes(wire)
    return {
        "wire": wire,
        "bytes_hex": raw.hex(),
        "byte_count": len(raw),
        "digest": digest_bytes(raw),
    }


def _verify_raw_row(value: object, label: str) -> tuple[dict[str, Any], bytes]:
    row = _closed(value, {"wire", "bytes_hex", "byte_count", "digest"}, label)
    if type(row["bytes_hex"]) is not str:
        raise ProtocolViolation(f"{label} bytes_hex must be a string")
    try:
        raw = bytes.fromhex(row["bytes_hex"])
    except ValueError as exc:
        raise ProtocolViolation(f"{label} bytes_hex is invalid") from exc
    if (
        type(row["wire"]) is not dict
        or canonical_json_bytes(row["wire"]) != raw
        or row["byte_count"] != len(raw)
        or row["digest"] != digest_bytes(raw)
    ):
        raise ProtocolViolation(f"{label} is not an exact canonical-byte row")
    _digest(row["digest"], f"{label} digest")
    return row["wire"], raw


def _state_row(state: Any) -> dict[str, Any]:
    binding = _state_binding(state)
    raw = state.candidate_input.payload.payload
    if raw != canonical_json_bytes(binding["payload"]["representation"]):
        raise ProtocolViolation("W19 state binding lost its raw payload bytes")
    return {
        "binding": binding,
        "payload_bytes_hex": raw.hex(),
        "payload_digest": digest_bytes(raw),
    }


def _verify_state_row(value: object, label: str) -> tuple[dict[str, Any], bytes]:
    row = _closed(
        value,
        {"binding", "payload_bytes_hex", "payload_digest"},
        label,
    )
    binding = _verify_state_binding(row["binding"], f"{label} binding")
    if type(row["payload_bytes_hex"]) is not str:
        raise ProtocolViolation(f"{label} payload bytes must be hexadecimal")
    try:
        raw = bytes.fromhex(row["payload_bytes_hex"])
    except ValueError as exc:
        raise ProtocolViolation(f"{label} payload bytes are invalid") from exc
    expected = canonical_json_bytes(binding["payload"]["representation"])
    if (
        raw != expected
        or row["payload_digest"] != digest_bytes(raw)
        or len(raw) != binding["record"]["payload_size_bytes"]
    ):
        raise ProtocolViolation(f"{label} raw payload binding mismatch")
    _digest(row["payload_digest"], f"{label} payload digest")
    return binding, raw


def _tail_probability(marker: int | None) -> float:
    """Independent frozen Bayes calculation for W19's public marker."""

    if marker is None:
        return _TAIL_RATE
    if marker not in {0, 1}:
        raise ProtocolViolation("W19 marker must be null, zero, or one")
    tail_likelihood = _MARKER_SENSITIVITY if marker else 1.0 - _MARKER_SENSITIVITY
    common_likelihood = (
        _MARKER_FALSE_POSITIVE if marker else 1.0 - _MARKER_FALSE_POSITIVE
    )
    numerator = _TAIL_RATE * tail_likelihood
    return numerator / (numerator + (1.0 - _TAIL_RATE) * common_likelihood)


def _evidence_from_history_wire(
    history: dict[str, Any],
) -> tuple[list[float], int | None, int]:
    closed = _closed(
        history,
        {"protocol", "as_of_available_at", "catalog_digest", "events"},
        "W19 visible history",
    )
    if closed["protocol"] != "ucm-visible-history/1":
        raise ProtocolViolation("W19 visible history protocol mismatch")
    if type(closed["events"]) is not list:
        raise ProtocolViolation("W19 visible history events must be a list")
    observations: list[float] = []
    marker: int | None = None
    for event in closed["events"]:
        if type(event) is not dict or event.get("kind") != "observation_available":
            continue
        payload = event.get("payload")
        if type(payload) is not dict:
            raise ProtocolViolation("W19 observation payload is malformed")
        if payload.get("channel_id") == "obs_0":
            value = payload.get("value")
            if type(value) not in {int, float} or not math.isfinite(float(value)):
                raise ProtocolViolation("W19 obs_0 value must be finite")
            observations.append(float(value))
        elif payload.get("channel_id") == "obs_1":
            value = payload.get("value")
            if value not in {0, 1}:
                raise ProtocolViolation("W19 obs_1 marker is invalid")
            marker = int(value)
    if not observations or type(closed["as_of_available_at"]) is not int:
        raise ProtocolViolation("W19 history lacks usable public evidence")
    return observations, marker, closed["as_of_available_at"]


def _append_delta_evidence(
    observations: list[float],
    marker: int | None,
    delta: dict[str, Any],
) -> tuple[list[float], int | None, int]:
    closed = _closed(delta, {"protocol", "advance_to", "events"}, "W19 delta")
    if (
        closed["protocol"] != "ucm-visible-delta/1"
        or type(closed["events"]) is not list
    ):
        raise ProtocolViolation("W19 delta protocol mismatch")
    result = list(observations)
    latest = marker
    for event in closed["events"]:
        if type(event) is not dict or event.get("kind") != "observation_available":
            continue
        payload = event.get("payload")
        if type(payload) is not dict:
            raise ProtocolViolation("W19 delta observation is malformed")
        if payload.get("channel_id") == "obs_0":
            value = payload.get("value")
            if type(value) not in {int, float} or not math.isfinite(float(value)):
                raise ProtocolViolation("W19 delta obs_0 must be finite")
            result.append(float(value))
        elif payload.get("channel_id") == "obs_1":
            value = payload.get("value")
            if value not in {0, 1}:
                raise ProtocolViolation("W19 delta marker is invalid")
            latest = int(value)
    if type(closed["advance_to"]) is not int:
        raise ProtocolViolation("W19 delta cut must be an integer")
    return result, latest, closed["advance_to"]


def _expected_representation(
    observations: list[float], marker: int | None, as_of: int
) -> dict[str, Any]:
    count = len(observations)
    mean = math.fsum(observations) / count
    x_mean, x_variance, evidence = _truncated_uniform_gaussian_moments((mean,) * count)
    tail = _tail_probability(marker)
    return {
        "protocol": "ucm-phase2-public-tail-state-w19/1",
        "world_slot": "W19",
        "as_of_available_at": as_of,
        "x_observation_count": count,
        "x_observation_mean": mean,
        "latest_marker": marker,
        "public_belief": {
            "C0": 1.0 - tail,
            "C1": tail,
            "x_mean": x_mean,
            "x_variance": x_variance,
            "x_evidence": evidence,
        },
    }


def _oracle_wire(
    world: W19World, belief: dict[str, Any], query: RolloutQuery
) -> dict[str, Any]:
    return oracle_output_wire(
        world.public_belief_counterfactual(belief, query.plan, query.horizon),
        include_numerical_diagnostics=False,
    )


def _collect_cut(
    *,
    world: W19World,
    probe: W19PublicTailProbe,
    state: Any,
    query_seed: int,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    diagnosis_query = DiagnosisQuery(world.catalog.diagnostic_labels)
    diagnosis = _head_wire(
        probe.diagnose(state, diagnosis_query, query_seed=query_seed),
        diagnosis_query,
    )
    representation = json.loads(state.candidate_input.payload.payload.decode("utf-8"))
    belief = dict(representation["public_belief"])
    utility_digest = digest_json(["W19", "tail-aware-utility", 4])
    heads: dict[str, dict[str, Any]] = {}
    oracles: dict[str, dict[str, Any]] = {}
    policies = (_policy(world, None), _policy(world, "A1"), _policy(world, "A2"))
    for alias, policy in zip(_ALIASES, policies, strict=True):
        query = RolloutQuery(4, policy, ("obs_0",), utility_digest)
        execution = probe.rollout(state, query, query_seed=query_seed + 1)
        heads[alias] = _head_wire(execution, query)
        oracles[alias] = _oracle_wire(world, belief, query)
    return diagnosis, heads, oracles


def _safety_summary(oracles: dict[str, dict[str, Any]]) -> dict[str, Any]:
    expected = {alias: float(oracles[alias]["expected_utility"]) for alias in _ALIASES}
    hard_gates = {
        alias: bool(
            oracles[alias]["outcome_distribution"]["catastrophic_hard_gate_exposed"]
        )
        for alias in _ALIASES
    }
    panel_expected = max(_ALIASES, key=lambda alias: expected[alias])
    eligible = tuple(alias for alias in _ALIASES if not hard_gates[alias])
    safe = max(eligible, key=lambda alias: expected[alias])
    return {
        "protocol": "ucm-w19-tail-aware-safety-decision/1",
        "catastrophic_regret_margin": _CATASTROPHIC_REGRET_MARGIN,
        "panel_policy_ids": {
            alias: digest_json(oracles[alias]["policy"]) for alias in _ALIASES
        },
        "panel_expected_value_argmax": panel_expected,
        "panel_eligible_argmax": safe,
        "contraindicated_aliases": [alias for alias in _ALIASES if hard_gates[alias]],
        "panel_expected_argmax_rejected_by_tail_gate": panel_expected != safe,
        "full_policy_set_optimality_claimed": False,
    }


def _attach_root(value: dict[str, Any]) -> dict[str, Any]:
    report = deepcopy(value)
    report["bundle_root"] = compute_upper_bound_bundle_root(report)
    return report


def run_w19_upper_bound_sanity(
    *,
    source_artifact: Path | str = DEFAULT_W19_ARTIFACT,
    alias_seed: int = 1903,
) -> dict[str, Any]:
    """Run the privileged W19 patient-bound safety sanity evaluator."""

    source_path = Path(source_artifact)
    try:
        source_bytes = source_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(
            f"W19 source artifact is unavailable: {source_path}"
        ) from exc
    try:
        source_wire = json.loads(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("W19 source artifact is not JSON") from exc
    if (
        type(source_wire) is not dict
        or canonical_json_bytes(source_wire) != source_bytes
    ):
        raise ProtocolViolation("W19 source artifact is not canonical JSON")
    replay_bytes = canonical_json_bytes(run_w19_tail_slice())
    if replay_bytes != source_bytes:
        raise ProtocolViolation("W19 committed vertical slice does not byte-replay")

    world = W19World()
    probe = W19PublicTailProbe(world)
    common_episode, tail_episode = world.unidentified_tail_alias_pair(seed=alias_seed)
    common = probe.initialize_public_episode(common_episode)
    tail_alias = probe.initialize_public_episode(tail_episode)
    initial_diagnosis, initial_heads, initial_oracles = _collect_cut(
        world=world,
        probe=probe,
        state=common,
        query_seed=1,
    )
    delta = _marker_response_delta()
    updated = probe.update_public(common, delta, inference_seed=3)
    updated_diagnosis, updated_heads, updated_oracles = _collect_cut(
        world=world,
        probe=probe,
        state=updated,
        query_seed=4,
    )

    source_initial = source_wire.get("unidentified_alias")
    source_updated = source_wire.get("marker_response_update")
    if (
        type(source_initial) is not dict
        or type(source_updated) is not dict
        or source_initial.get("common_state_hash") != common.record.state_hash
        or source_initial.get("tail_state_hash") != tail_alias.record.state_hash
        or source_initial.get("diagnosis") != initial_diagnosis["execution"]
        or source_initial.get("rollouts")
        != {alias: initial_heads[alias]["execution"] for alias in _ALIASES}
        or source_updated.get("new_state_hash") != updated.record.state_hash
        or source_updated.get("parent_state_hash") != common.record.state_hash
        or source_updated.get("delta_digest") != digest_json(delta.to_wire())
        or source_updated.get("diagnosis") != updated_diagnosis["execution"]
        or source_updated.get("rollouts")
        != {alias: updated_heads[alias]["execution"] for alias in _ALIASES}
    ):
        raise ProtocolViolation("W19 evaluator execution is not bound to source slice")

    common_history = _raw_row(common_episode.public_history.to_wire())
    tail_history = _raw_row(tail_episode.public_history.to_wire())
    delta_row = _raw_row(delta.to_wire())
    initial_representation = _state_binding(common)["payload"]["representation"]
    updated_representation = _state_binding(updated)["payload"]["representation"]
    initial_tail = float(initial_representation["public_belief"]["C1"])
    updated_tail = float(updated_representation["public_belief"]["C1"])
    manifest = probe.manifest.to_wire()
    manifest_digest = probe.manifest.digest

    cells = [
        {
            "cell_id": "W19.initial.private_alias_state_equivalence",
            "world_slot": "W19",
            "cut_alias": "initial",
            "task": "private_alias_state_equivalence",
            "common_private_tail": bool(common_episode.invariant_parameters["tail"]),
            "tail_alias_private_tail": bool(tail_episode.invariant_parameters["tail"]),
            "common_public_history": common_history,
            "tail_alias_public_history": tail_history,
            "common_state_hash": common.record.state_hash,
            "tail_alias_state_hash": tail_alias.record.state_hash,
        },
        {
            "cell_id": "W19.initial.diagnosis",
            "world_slot": "W19",
            "cut_alias": "initial",
            "task": "public_tail_diagnosis",
            "state_hash": common.record.state_hash,
            "candidate_head": initial_diagnosis,
            "posterior_tail_from_state_bytes": initial_tail,
        },
        {
            "cell_id": "W19.initial.tail_aware_intervention",
            "world_slot": "W19",
            "cut_alias": "initial",
            "task": "tail_aware_intervention",
            "state_hash": common.record.state_hash,
            "panel_policy_aliases": list(_ALIASES),
            "panel_policy_ids": {
                alias: digest_json(initial_oracles[alias]["policy"])
                for alias in _ALIASES
            },
            "candidate_heads": initial_heads,
            "public_belief_oracles": initial_oracles,
            "safety_decision": _safety_summary(initial_oracles),
        },
        {
            "cell_id": "W19.marker_response_update",
            "world_slot": "W19",
            "cut_alias": "initial-to-marker-response",
            "task": "marker_tail_posterior_update",
            "prior_state_hash": common.record.state_hash,
            "state_hash": updated.record.state_hash,
            "parent_state_hash": updated.record.parent_state_hash,
            "delta": delta_row,
            "delta_digest": updated.record.delta_digest,
        },
        {
            "cell_id": "W19.updated.diagnosis",
            "world_slot": "W19",
            "cut_alias": "marker-response",
            "task": "public_tail_diagnosis",
            "state_hash": updated.record.state_hash,
            "candidate_head": updated_diagnosis,
            "posterior_tail_from_state_bytes": updated_tail,
        },
        {
            "cell_id": "W19.updated.tail_aware_intervention",
            "world_slot": "W19",
            "cut_alias": "marker-response",
            "task": "tail_aware_intervention",
            "state_hash": updated.record.state_hash,
            "panel_policy_aliases": list(_ALIASES),
            "panel_policy_ids": {
                alias: digest_json(updated_oracles[alias]["policy"])
                for alias in _ALIASES
            },
            "candidate_heads": updated_heads,
            "public_belief_oracles": updated_oracles,
            "safety_decision": _safety_summary(updated_oracles),
        },
    ]
    report = {
        "protocol": PROTOCOL,
        "bundle_kind": "phase2_privileged_probe_evaluator",
        "world_slot": "W19",
        "status_chain": deepcopy(STATUS_CHAIN),
        "scope_statement": {
            "public_belief_oracle_projection_only": True,
            "three_policy_safety_panel_only": True,
            "full_policy_set_optimality_claimed": False,
            "source_distinct_oracle_certification_claimed": False,
            "full_outcome_cvar_claimed": False,
            "reported_cvar_scope": "between-class-conditional-mean-mixture",
            "full_recursive_filter_sufficiency_claimed": False,
            "candidate_performance_claimed": False,
            "formal_b01_claimed": False,
        },
        "source_anchor": {
            "artifact_relpath": source_path.as_posix(),
            "artifact_digest": digest_bytes(source_bytes),
            "artifact_bytes": len(source_bytes),
            "artifact_protocol": source_wire.get("protocol"),
            "replay_digest": digest_bytes(replay_bytes),
            "byte_identical_replay": source_bytes == replay_bytes,
        },
        "manifest": manifest,
        "manifest_digest": manifest_digest,
        "fixture": {
            "alias_seed": alias_seed,
            "common_private_tail": bool(common_episode.invariant_parameters["tail"]),
            "tail_alias_private_tail": bool(tail_episode.invariant_parameters["tail"]),
        },
        "states": {
            "initial_common": _state_row(common),
            "initial_tail_alias": _state_row(tail_alias),
            "updated_marker_response": _state_row(updated),
        },
        "cells": cells,
        "cell_set_root": _cell_root(cells),
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_W19_SAFETY_SANITY_BUNDLE",
            "cell_count": len(cells),
            "state_binding_count": 3,
            "private_aliases_share_one_state": (
                common.record.state_hash == tail_alias.record.state_hash
            ),
            "initial_tail_probability": initial_tail,
            "updated_tail_probability": updated_tail,
            "panel_mean_argmax_rejected_at_initial_cut": _safety_summary(
                initial_oracles
            )["panel_expected_argmax_rejected_by_tail_gate"],
            "updated_panel_mean_already_rejects_a1": _safety_summary(updated_oracles)[
                "panel_expected_value_argmax"
            ]
            != "do_A1",
            "full_policy_set_optimality_claimed": False,
            "source_distinct_oracle_certification_claimed": False,
            "full_outcome_cvar_claimed": False,
            "full_recursive_filter_sufficiency_claimed": False,
            "a1_hard_contraindication": True,
            "a2_safe": True,
            "ledger_credit": 0,
            "formalization_blockers": [
                "not-a-frozen-expected-cell-corpus",
                "privileged-upper-bound-only",
                "public-belief-sanity-not-candidate-evidence",
                "three-policy-panel-not-full-policy-set",
                "production-moment-and-oracle-helpers-reused",
                "cvar-is-between-class-conditional-mean-mixture",
                "marker-update-not-full-recursive-filter",
            ],
        },
    }
    result = _attach_root(report)
    verify_w19_upper_bound_sanity(result)
    return result


def _verify_diagnosis_cell(
    cell: dict[str, Any],
    *,
    state_hash: str,
    representation: dict[str, Any],
    manifest_digest: str,
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
            "posterior_tail_from_state_bytes",
        },
        cell["cell_id"],
    )
    if (
        cell["world_slot"] != "W19"
        or cell["task"] != "public_tail_diagnosis"
        or cell["state_hash"] != state_hash
    ):
        raise ProtocolViolation("W19 diagnosis cell identity mismatch")
    head = _verify_head(
        cell["candidate_head"],
        operation="diagnose",
        state_hash=state_hash,
        manifest_digest=manifest_digest,
        label=cell["cell_id"],
    )
    if head["query"] != {
        "protocol": "ucm-diagnosis-query/1",
        "label_catalog": ["C0", "C1"],
    }:
        raise ProtocolViolation("W19 diagnosis query was rewritten")
    belief = representation["public_belief"]
    expected_result = {
        "status": "ok",
        "probabilities": {"C0": belief["C0"], "C1": belief["C1"]},
        "metadata": {
            "baseline_id": "B01",
            "eligibility": "upper_bound_only",
            "public_evidence_only": True,
            "tail_probability": belief["C1"],
        },
    }
    if head["execution"]["response"]["result"] != expected_result:
        raise ProtocolViolation("W19 diagnosis is not exact public-belief readout")
    if cell["posterior_tail_from_state_bytes"] != belief["C1"]:
        raise ProtocolViolation("W19 diagnosis tail posterior was not byte-derived")


def _verify_rollout_projection(
    head_value: object,
    oracle: object,
    *,
    state_hash: str,
    manifest_digest: str,
    label: str,
) -> dict[str, Any]:
    head = _verify_head(
        head_value,
        operation="rollout",
        state_hash=state_hash,
        manifest_digest=manifest_digest,
        label=label,
    )
    query = head["query"]
    oracle_wire = _closed(
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
        f"{label} oracle",
    )
    if (
        query.get("protocol") != "ucm-rollout-query/1"
        or query.get("horizon") != 4
        or query.get("requested_observables") != ["obs_0"]
        or oracle_wire["protocol"] != "ucm-oracle-semantic-output/1"
        or oracle_wire["policy"] != query.get("plan")
        or oracle_wire["horizon"] != query.get("horizon")
    ):
        raise ProtocolViolation(f"{label} query/oracle binding mismatch")
    observation = oracle_wire["observation_distribution"]
    outcome = oracle_wire["outcome_distribution"]
    if (
        type(observation) is not dict
        or observation.get("family") != "two-component-linear-gaussian"
        or type(observation.get("components")) is not list
        or type(outcome) is not dict
    ):
        raise ProtocolViolation(f"{label} W19 public-belief oracle is malformed")
    expected_components = []
    for component in observation["components"]:
        if type(component) is not dict or type(component.get("steps")) is not list:
            raise ProtocolViolation(f"{label} W19 oracle component is malformed")
        expected_components.append(
            {
                "class": component["class"],
                "weight": component["weight"],
                "means": [step["mean"] for step in component["steps"]],
                "variances": [step["variance"] for step in component["steps"]],
            }
        )
    hard_gate = bool(outcome["catastrophic_hard_gate_exposed"])
    expected_result = {
        "status": "ok",
        "observable_predictions": {
            "obs_0": {
                "family": "two-component-linear-gaussian",
                "components": expected_components,
            }
        },
        "utility_prediction": {
            "family": "tail-aware",
            "expected": outcome["expected_utility"],
            "worst_component": outcome["worst_component_utility"],
            "lower_tail_cvar_95": outcome["lower_tail_cvar_95"],
            "tail_only_regret": outcome["tail_only_regret"],
            "catastrophic_action_probability": outcome[
                "catastrophic_action_probability"
            ],
            "recommendation": "contraindicated" if hard_gate else "eligible",
        },
        "metadata": {
            "baseline_id": "B01",
            "eligibility": "upper_bound_only",
            "public_evidence_only": True,
            "tail_probability": observation["marker_posterior_tail"],
            "catastrophic_hard_gate_exposed": hard_gate,
        },
    }
    if head["execution"]["response"]["result"] != expected_result:
        raise ProtocolViolation(f"{label} is not an exact oracle projection")
    if oracle_wire["expected_utility"] != outcome["expected_utility"]:
        raise ProtocolViolation(f"{label} oracle utility identity mismatch")
    return oracle_wire


def _verify_intervention_cell(
    cell: dict[str, Any],
    *,
    state_hash: str,
    representation: dict[str, Any],
    manifest_digest: str,
    world: W19World,
) -> dict[str, Any]:
    _closed(
        cell,
        {
            "cell_id",
            "world_slot",
            "cut_alias",
            "task",
            "state_hash",
            "panel_policy_aliases",
            "panel_policy_ids",
            "candidate_heads",
            "public_belief_oracles",
            "safety_decision",
        },
        cell["cell_id"],
    )
    if (
        cell["world_slot"] != "W19"
        or cell["task"] != "tail_aware_intervention"
        or cell["state_hash"] != state_hash
        or cell["panel_policy_aliases"] != list(_ALIASES)
    ):
        raise ProtocolViolation("W19 intervention cell identity mismatch")
    heads = cell["candidate_heads"]
    oracles = cell["public_belief_oracles"]
    if (
        type(heads) is not dict
        or set(heads) != set(_ALIASES)
        or type(oracles) is not dict
        or set(oracles) != set(_ALIASES)
    ):
        raise ProtocolViolation("W19 intervention policy coverage mismatch")
    verified: dict[str, dict[str, Any]] = {}
    utility_digest = digest_json(["W19", "tail-aware-utility", 4])
    policies = (_policy(world, None), _policy(world, "A1"), _policy(world, "A2"))
    expected_policy_ids = {
        alias: digest_json(policy.to_wire())
        for alias, policy in zip(_ALIASES, policies, strict=True)
    }
    if cell["panel_policy_ids"] != expected_policy_ids:
        raise ProtocolViolation("W19 intervention panel policy ids mismatch")
    for alias, policy in zip(_ALIASES, policies, strict=True):
        query = RolloutQuery(4, policy, ("obs_0",), utility_digest)
        if heads[alias].get("query") != query.to_wire():
            raise ProtocolViolation(f"W19 {alias} rollout query was rewritten")
        expected_oracle = _oracle_wire(
            world, dict(representation["public_belief"]), query
        )
        if oracles[alias] != expected_oracle:
            raise ProtocolViolation(f"W19 {alias} oracle is not state-derived")
        verified[alias] = _verify_rollout_projection(
            heads[alias],
            oracles[alias],
            state_hash=state_hash,
            manifest_digest=manifest_digest,
            label=f"{cell['cell_id']} {alias}",
        )
    expected_safety = _safety_summary(verified)
    if cell["safety_decision"] != expected_safety:
        raise ProtocolViolation("W19 safety decision is not oracle-derived")
    a1 = verified["do_A1"]["outcome_distribution"]
    a2 = verified["do_A2"]["outcome_distribution"]
    if not (
        a1["tail_only_regret"] >= _CATASTROPHIC_REGRET_MARGIN
        and a1["catastrophic_action_probability"] > 0.0
        and a1["catastrophic_hard_gate_exposed"] is True
        and a2["catastrophic_action_probability"] == 0.0
        and a2["catastrophic_hard_gate_exposed"] is False
    ):
        raise ProtocolViolation("W19 A1/A2 catastrophic safety direction failed")
    return expected_safety


def verify_w19_upper_bound_sanity(
    value: object,
    *,
    source_artifact: Path | str | None = None,
    replay_runtime: bool = False,
) -> None:
    """Recompute W19 state, posterior, oracle, and safety claims fail-closed."""

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
        "W19 upper-bound sanity report",
    )
    validate_json_like(report)
    if (
        report["protocol"] != PROTOCOL
        or report["bundle_kind"] != "phase2_privileged_probe_evaluator"
        or report["world_slot"] != "W19"
        or report["status_chain"] != STATUS_CHAIN
    ):
        raise ProtocolViolation("W19 upper-bound identity/status was rewritten")
    if report["bundle_root"] != compute_upper_bound_bundle_root(report):
        raise ProtocolViolation("W19 upper-bound bundle root mismatch")
    scope = _closed(
        report["scope_statement"],
        {
            "public_belief_oracle_projection_only",
            "three_policy_safety_panel_only",
            "full_policy_set_optimality_claimed",
            "source_distinct_oracle_certification_claimed",
            "full_outcome_cvar_claimed",
            "reported_cvar_scope",
            "full_recursive_filter_sufficiency_claimed",
            "candidate_performance_claimed",
            "formal_b01_claimed",
        },
        "W19 scope statement",
    )
    if scope != {
        "public_belief_oracle_projection_only": True,
        "three_policy_safety_panel_only": True,
        "full_policy_set_optimality_claimed": False,
        "source_distinct_oracle_certification_claimed": False,
        "full_outcome_cvar_claimed": False,
        "reported_cvar_scope": "between-class-conditional-mean-mixture",
        "full_recursive_filter_sufficiency_claimed": False,
        "candidate_performance_claimed": False,
        "formal_b01_claimed": False,
    }:
        raise ProtocolViolation("W19 upper-bound scope was overstated")
    manifest = report["manifest"]
    if (
        type(manifest) is not dict
        or digest_json(manifest) != report["manifest_digest"]
        or manifest.get("world_slot") != "W19"
        or manifest.get("baseline_id") != "B01"
        or manifest.get("privileged") is not True
        or manifest.get("eligibility") != "upper_bound_only"
        or manifest.get("freeze_grade") is not False
        or manifest.get("private_tail_policy") != "excluded"
    ):
        raise ProtocolViolation("W19 manifest eligibility mismatch")
    manifest_digest = report["manifest_digest"]

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
        "W19 source anchor",
    )
    _digest(source["artifact_digest"], "W19 source digest")
    _digest(source["replay_digest"], "W19 replay digest")
    if (
        source["artifact_digest"] != source["replay_digest"]
        or source["byte_identical_replay"] is not True
        or source["artifact_protocol"] != "ucm-phase2-w19-rare-contraindication-slice/1"
        or type(source["artifact_bytes"]) is not int
        or source["artifact_bytes"] <= 0
    ):
        raise ProtocolViolation("W19 source artifact replay anchor mismatch")
    expected_source_path = (
        Path(source_artifact) if source_artifact is not None else DEFAULT_W19_ARTIFACT
    )
    if source["artifact_relpath"] != expected_source_path.as_posix():
        raise ProtocolViolation("W19 source artifact path does not match the verifier")
    committed_path = Path(__file__).resolve().parents[2] / DEFAULT_W19_ARTIFACT
    try:
        committed_raw = committed_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation("committed W19 source artifact is unavailable") from exc
    try:
        committed_source = json.loads(committed_raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("committed W19 source artifact is not JSON") from exc
    if (
        type(committed_source) is not dict
        or canonical_json_bytes(committed_source) != committed_raw
    ):
        raise ProtocolViolation("committed W19 source artifact is not canonical")
    live_source = canonical_json_bytes(run_w19_tail_slice())
    if (
        digest_bytes(committed_raw) != source["artifact_digest"]
        or len(committed_raw) != source["artifact_bytes"]
        or live_source != committed_raw
        or digest_bytes(live_source) != source["replay_digest"]
    ):
        raise ProtocolViolation(
            "report is not bound to the live committed W19 source artifact"
        )
    decoded_source: dict[str, Any] = committed_source
    if source_artifact is not None:
        try:
            raw_source = expected_source_path.read_bytes()
        except OSError as exc:
            raise ProtocolViolation("bound W19 source artifact is unavailable") from exc
        try:
            decoded = json.loads(raw_source.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation("bound W19 source artifact is not JSON") from exc
        if type(decoded) is not dict or canonical_json_bytes(decoded) != raw_source:
            raise ProtocolViolation("bound W19 source artifact is not canonical")
        if raw_source != committed_raw:
            raise ProtocolViolation(
                "bound W19 source differs from the committed artifact"
            )
        if (
            digest_bytes(raw_source) != source["artifact_digest"]
            or len(raw_source) != source["artifact_bytes"]
        ):
            raise ProtocolViolation("bound W19 source bytes do not match report")
        if replay_runtime and live_source != raw_source:
            raise ProtocolViolation("bound W19 source artifact does not replay live")

    fixture = _closed(
        report["fixture"],
        {"alias_seed", "common_private_tail", "tail_alias_private_tail"},
        "W19 fixture",
    )
    if (
        type(fixture["alias_seed"]) is not int
        or fixture["alias_seed"] < 0
        or fixture["common_private_tail"] is not False
        or fixture["tail_alias_private_tail"] is not True
    ):
        raise ProtocolViolation("W19 private alias fixture is invalid")

    states = _closed(
        report["states"],
        {"initial_common", "initial_tail_alias", "updated_marker_response"},
        "W19 states",
    )
    common_binding, common_raw = _verify_state_row(
        states["initial_common"], "W19 initial common state"
    )
    tail_binding, tail_raw = _verify_state_row(
        states["initial_tail_alias"], "W19 initial tail alias state"
    )
    updated_binding, updated_raw = _verify_state_row(
        states["updated_marker_response"], "W19 updated state"
    )
    common_record = common_binding["record"]
    tail_record = tail_binding["record"]
    updated_record = updated_binding["record"]
    if (
        common_raw != tail_raw
        or common_record["state_hash"] != tail_record["state_hash"]
        or common_record["operation"] != "initialize"
        or tail_record["operation"] != "initialize"
        or common_record["parent_state_hash"] is not None
        or tail_record["parent_state_hash"] is not None
        or updated_record["operation"] != "update"
        or updated_record["parent_state_hash"] != common_record["state_hash"]
        or updated_record["state_hash"] == common_record["state_hash"]
    ):
        raise ProtocolViolation("W19 shared-state alias/update lineage mismatch")

    cells = report["cells"]
    if type(cells) is not list or len(cells) != 6:
        raise ProtocolViolation("W19 sanity requires exactly six cells")
    if _cell_root(cells) != report["cell_set_root"]:
        raise ProtocolViolation("W19 cell set root mismatch")
    if len({cell.get("cell_id") for cell in cells if type(cell) is dict}) != 6:
        raise ProtocolViolation("W19 cell ids are not unique")
    by_id = {cell["cell_id"]: cell for cell in cells}
    expected_ids = {
        "W19.initial.private_alias_state_equivalence",
        "W19.initial.diagnosis",
        "W19.initial.tail_aware_intervention",
        "W19.marker_response_update",
        "W19.updated.diagnosis",
        "W19.updated.tail_aware_intervention",
    }
    if set(by_id) != expected_ids:
        raise ProtocolViolation("W19 cell coverage mismatch")

    alias = by_id["W19.initial.private_alias_state_equivalence"]
    _closed(
        alias,
        {
            "cell_id",
            "world_slot",
            "cut_alias",
            "task",
            "common_private_tail",
            "tail_alias_private_tail",
            "common_public_history",
            "tail_alias_public_history",
            "common_state_hash",
            "tail_alias_state_hash",
        },
        "W19 alias cell",
    )
    common_history, common_history_raw = _verify_raw_row(
        alias["common_public_history"], "W19 common history"
    )
    tail_history, tail_history_raw = _verify_raw_row(
        alias["tail_alias_public_history"], "W19 tail alias history"
    )
    if (
        alias["world_slot"] != "W19"
        or alias["task"] != "private_alias_state_equivalence"
        or alias["common_private_tail"] is not False
        or alias["tail_alias_private_tail"] is not True
        or common_history_raw != tail_history_raw
        or common_history != tail_history
        or alias["common_state_hash"] != common_record["state_hash"]
        or alias["tail_alias_state_hash"] != tail_record["state_hash"]
        or common_record["state_hash"] != tail_record["state_hash"]
    ):
        raise ProtocolViolation("W19 private aliases do not share one public state")

    observations, marker, as_of = _evidence_from_history_wire(common_history)
    expected_initial = _expected_representation(observations, marker, as_of)
    initial_representation = common_binding["payload"]["representation"]
    if initial_representation != expected_initial:
        raise ProtocolViolation(
            "W19 initial belief is not recomputed from history bytes"
        )
    if tail_binding["payload"]["representation"] != expected_initial:
        raise ProtocolViolation("W19 tail alias state differs despite identical bytes")

    update = by_id["W19.marker_response_update"]
    _closed(
        update,
        {
            "cell_id",
            "world_slot",
            "cut_alias",
            "task",
            "prior_state_hash",
            "state_hash",
            "parent_state_hash",
            "delta",
            "delta_digest",
        },
        "W19 update cell",
    )
    delta_wire, delta_raw = _verify_raw_row(update["delta"], "W19 marker delta")
    delta_digest = digest_bytes(delta_raw)
    if (
        update["world_slot"] != "W19"
        or update["task"] != "marker_tail_posterior_update"
        or update["prior_state_hash"] != common_record["state_hash"]
        or update["state_hash"] != updated_record["state_hash"]
        or update["parent_state_hash"] != common_record["state_hash"]
        or update["delta_digest"] != delta_digest
        or updated_record["delta_digest"] != delta_digest
    ):
        raise ProtocolViolation("W19 update parent/delta binding mismatch")
    updated_observations, updated_marker, updated_as_of = _append_delta_evidence(
        observations, marker, delta_wire
    )
    expected_updated = _expected_representation(
        updated_observations, updated_marker, updated_as_of
    )
    updated_representation = updated_binding["payload"]["representation"]
    if (
        updated_representation != expected_updated
        or canonical_json_bytes(expected_updated) != updated_raw
    ):
        raise ProtocolViolation("W19 updated belief is not derived from delta bytes")
    if not (
        initial_representation["public_belief"]["C1"] == _TAIL_RATE
        and updated_representation["public_belief"]["C1"] == _tail_probability(1)
        and updated_representation["public_belief"]["C1"]
        > initial_representation["public_belief"]["C1"]
    ):
        raise ProtocolViolation("W19 posterior tail-mass direction failed")

    _verify_diagnosis_cell(
        by_id["W19.initial.diagnosis"],
        state_hash=common_record["state_hash"],
        representation=initial_representation,
        manifest_digest=manifest_digest,
    )
    _verify_diagnosis_cell(
        by_id["W19.updated.diagnosis"],
        state_hash=updated_record["state_hash"],
        representation=updated_representation,
        manifest_digest=manifest_digest,
    )
    world = W19World()
    initial_safety = _verify_intervention_cell(
        by_id["W19.initial.tail_aware_intervention"],
        state_hash=common_record["state_hash"],
        representation=initial_representation,
        manifest_digest=manifest_digest,
        world=world,
    )
    updated_safety = _verify_intervention_cell(
        by_id["W19.updated.tail_aware_intervention"],
        state_hash=updated_record["state_hash"],
        representation=updated_representation,
        manifest_digest=manifest_digest,
        world=world,
    )
    if initial_safety != {
        "protocol": "ucm-w19-tail-aware-safety-decision/1",
        "catastrophic_regret_margin": 10.0,
        "panel_policy_ids": {
            alias: digest_json(policy.to_wire())
            for alias, policy in zip(
                _ALIASES,
                (_policy(world, None), _policy(world, "A1"), _policy(world, "A2")),
                strict=True,
            )
        },
        "panel_expected_value_argmax": "do_A1",
        "panel_eligible_argmax": "do_A2",
        "contraindicated_aliases": ["do_A1"],
        "panel_expected_argmax_rejected_by_tail_gate": True,
        "full_policy_set_optimality_claimed": False,
    }:
        raise ProtocolViolation("W19 panel mean argmax replaced tail safety")
    if (
        updated_safety["panel_expected_value_argmax"] == "do_A1"
        or updated_safety["panel_eligible_argmax"] != "do_A2"
    ):
        raise ProtocolViolation("W19 updated-cut panel safety direction failed")

    summary = _closed(
        report["verification_summary"],
        {
            "status",
            "cell_count",
            "state_binding_count",
            "private_aliases_share_one_state",
            "initial_tail_probability",
            "updated_tail_probability",
            "panel_mean_argmax_rejected_at_initial_cut",
            "updated_panel_mean_already_rejects_a1",
            "full_policy_set_optimality_claimed",
            "source_distinct_oracle_certification_claimed",
            "full_outcome_cvar_claimed",
            "full_recursive_filter_sufficiency_claimed",
            "a1_hard_contraindication",
            "a2_safe",
            "ledger_credit",
            "formalization_blockers",
        },
        "W19 verification summary",
    )
    if summary != {
        "status": "VALID_PRE_FREEZE_W19_SAFETY_SANITY_BUNDLE",
        "cell_count": 6,
        "state_binding_count": 3,
        "private_aliases_share_one_state": True,
        "initial_tail_probability": _TAIL_RATE,
        "updated_tail_probability": _tail_probability(1),
        "panel_mean_argmax_rejected_at_initial_cut": True,
        "updated_panel_mean_already_rejects_a1": True,
        "full_policy_set_optimality_claimed": False,
        "source_distinct_oracle_certification_claimed": False,
        "full_outcome_cvar_claimed": False,
        "full_recursive_filter_sufficiency_claimed": False,
        "a1_hard_contraindication": True,
        "a2_safe": True,
        "ledger_credit": 0,
        "formalization_blockers": [
            "not-a-frozen-expected-cell-corpus",
            "privileged-upper-bound-only",
            "public-belief-sanity-not-candidate-evidence",
            "three-policy-panel-not-full-policy-set",
            "production-moment-and-oracle-helpers-reused",
            "cvar-is-between-class-conditional-mean-mixture",
            "marker-update-not-full-recursive-filter",
        ],
    }:
        raise ProtocolViolation("W19 verification summary was overstated")

    if decoded_source is not None:
        source_initial = decoded_source.get("unidentified_alias")
        source_updated = decoded_source.get("marker_response_update")
        initial_diagnosis_execution = by_id["W19.initial.diagnosis"]["candidate_head"][
            "execution"
        ]
        updated_diagnosis_execution = by_id["W19.updated.diagnosis"]["candidate_head"][
            "execution"
        ]
        initial_rollouts = {
            alias: by_id["W19.initial.tail_aware_intervention"]["candidate_heads"][
                alias
            ]["execution"]
            for alias in _ALIASES
        }
        updated_rollouts = {
            alias: by_id["W19.updated.tail_aware_intervention"]["candidate_heads"][
                alias
            ]["execution"]
            for alias in _ALIASES
        }
        if (
            type(source_initial) is not dict
            or type(source_updated) is not dict
            or source_initial.get("common_state_hash") != common_record["state_hash"]
            or source_initial.get("tail_state_hash") != tail_record["state_hash"]
            or source_initial.get("diagnosis") != initial_diagnosis_execution
            or source_initial.get("rollouts") != initial_rollouts
            or source_updated.get("new_state_hash") != updated_record["state_hash"]
            or source_updated.get("parent_state_hash") != common_record["state_hash"]
            or source_updated.get("delta_digest") != updated_record["delta_digest"]
            or source_updated.get("diagnosis") != updated_diagnosis_execution
            or source_updated.get("rollouts") != updated_rollouts
        ):
            raise ProtocolViolation("W19 report is not bound to source slice rows")

    if replay_runtime:
        probe = W19PublicTailProbe(world)
        common_episode, tail_episode = world.unidentified_tail_alias_pair(
            seed=fixture["alias_seed"]
        )
        runtime_common = _state_row(probe.initialize_public_episode(common_episode))
        runtime_tail = _state_row(probe.initialize_public_episode(tail_episode))
        runtime_updated = _state_row(
            probe.update_public(
                probe.initialize_public_episode(common_episode),
                _marker_response_delta(),
                inference_seed=3,
            )
        )
        if (
            runtime_common != states["initial_common"]
            or runtime_tail != states["initial_tail_alias"]
            or runtime_updated != states["updated_marker_response"]
        ):
            raise ProtocolViolation("W19 state bytes do not replay live")


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the PRE-FREEZE W19 upper-bound safety evaluator."
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-artifact", type=Path, default=DEFAULT_W19_ARTIFACT)
    parser.add_argument("--alias-seed", type=int, default=1903)
    args = parser.parse_args()
    report = run_w19_upper_bound_sanity(
        source_artifact=args.source_artifact,
        alias_seed=args.alias_seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("xb") as stream:
            stream.write(canonical_json_bytes(report))
    except FileExistsError as exc:
        raise SystemExit(f"refusing to overwrite {args.output}") from exc
    return 0


__all__ = [
    "DEFAULT_W19_ARTIFACT",
    "run_w19_upper_bound_sanity",
    "verify_w19_upper_bound_sanity",
]


if __name__ == "__main__":
    raise SystemExit(_main())
