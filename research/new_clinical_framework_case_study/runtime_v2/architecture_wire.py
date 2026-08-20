"""Adapter between Runtime v2.1 internals and SharedPatientStateV1 wire.

The wire is authoritative at query boundaries.  Private runtime caches are
reconstructible conveniences and are never included in canonical bytes.
"""

from __future__ import annotations

import base64
import copy
import json
import math
from typing import Any, Mapping

from .schema import (
    ARCHITECTURE_VERSION,
    RUNTIME_VERSION,
    STATE_SCHEMA_VERSION,
    SharedPatientState,
    architecture_state_hash,
    digest,
    validate_state_payload,
)
from .ledger import build_event_ledger_proof
from .history_codec import decode_history_features, encode_history_summary


def _encode_common_binding(binding: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(binding), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_common_binding(token: str) -> dict[str, Any]:
    try:
        padded = token + "=" * (-len(token) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("invalid common-cause provenance binding") from exc
    required = {
        "event_id",
        "event_digest",
        "source_result_id",
        "concept_id",
        "fingerprint",
        "inference_fingerprint",
        "reliability",
        "common_cause_instance_id",
    }
    if not isinstance(value, dict) or not required.issubset(value):
        raise ValueError("incomplete common-cause provenance binding")
    if any(not str(value[key]) for key in required.difference({"reliability"})):
        raise ValueError("blank common-cause provenance binding field")
    reliability = float(value["reliability"])
    if not math.isfinite(reliability) or not 0.0 <= reliability <= 1.0:
        raise ValueError("common-cause member reliability must be in [0,1]")
    value["reliability"] = reliability
    return value


def _factor_graph_preimage(runtime: Any) -> dict[str, Any]:
    return {
        "observations": runtime.spec["observations"],
        "common_cause_factors": runtime.spec.get("common_cause_factors", []),
    }


UNKNOWN_PROCESS_ID = "NCF_UNMODELED_PROCESS"


def model_time_from_as_of(as_of: Mapping[str, Any]) -> float:
    """Return the runtime's numeric model-step cut from a frozen ``as_of``.

    ``SharedPatientStateV1.as_of.clock_time`` is an RFC3339 wall-clock field,
    not a free-form numeric slot.  This runtime declares a ``model_step``
    horizon, so its numeric causal cut is carried by the typed ``cut_id`` and
    ``clock_time`` remains null.  Keeping the parser in one place prevents a
    cold query, update, migration, and refinement from silently assigning
    different meanings to the same canonical state.
    """

    cut_id = str(as_of.get("cut_id") or "")
    prefix = "cut:"
    if not cut_id.startswith(prefix):
        raise ValueError("model-step state requires as_of.cut_id prefixed by 'cut:'")
    try:
        value = float(cut_id[len(prefix) :])
    except (TypeError, ValueError) as exc:
        raise ValueError("model-step state has a non-numeric as_of.cut_id") from exc
    if not math.isfinite(value):
        raise ValueError("model-step state has a non-finite as_of.cut_id")
    return value


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _primary_stratum_id(internal: Mapping[str, Any], process_id: str) -> str:
    posterior = internal["per_process"][process_id].get("stratum_posterior", {})
    if not posterior:
        return f"stratum:{process_id}"
    return max(sorted(posterior), key=lambda key: float(posterior[key]))


def _scope(runtime: Any) -> dict[str, Any]:
    declared = runtime.spec["scope"]
    horizon = declared["horizon"]
    return {
        "scope_id": declared["scope_id"],
        "scope_version": declared["scope_version"],
        "scope_digest": digest(declared),
        "population_id": declared["population_id"],
        "observation_catalog_digest": digest(runtime.spec["observations"]),
        "action_catalog_digest": digest(runtime.spec["actions"]),
        "policy_catalog_digest": digest(
            {"no_new_action": True, "registered_action_ids": sorted(runtime.actions)}
        ),
        "horizon": {"value": float(horizon["value"]), "unit": str(horizon["unit"])},
        "outcome_ids": sorted(set(declared["outcome_ids"])),
        "utility_digest": digest(
            {
                "coordinates": [
                    {
                        "process_id": process["process_id"],
                        "weights": {
                            row["coordinate_id"]: row.get("objective_weight", 0.0)
                            for row in process["coordinates"]
                        },
                    }
                    for process in runtime.spec["processes"]
                ],
                "action_costs": {
                    row["action_id"]: row.get("action_cost", 0.0)
                    for row in runtime.spec["actions"]
                },
            }
        ),
        "distance_metric_id": declared["distance_metric_id"],
        "tolerance": float(declared["tolerance"]),
    }


def _model_lineage(runtime: Any, internal: Mapping[str, Any]) -> dict[str, Any]:
    migrations = internal.get("lineage", {}).get("migration_history", [])
    last = migrations[-1] if migrations else {}
    return {
        "model_id": runtime.spec["model_id"],
        "model_version": str(runtime.spec.get("model_version", "2.1")),
        "model_digest": runtime.model_digest,
        "process_registry_digest": digest(runtime.spec["processes"]),
        "mode_registry_digest": digest(
            {row["process_id"]: row["modes"] for row in runtime.spec["processes"]}
        ),
        "factor_graph_digest": digest(_factor_graph_preimage(runtime)),
        "dynamics_digest": digest(
            {
                "actions": runtime.spec["actions"],
                "process_couplings": runtime.spec["process_couplings"],
                "process_activation_couplings": runtime.spec.get(
                    "process_activation_couplings", []
                ),
                "mode_couplings": runtime.spec["mode_couplings"],
                "process_activation_transitions": {
                    row["process_id"]: row.get("activation_transition", {})
                    for row in runtime.spec["processes"]
                },
                "mode_guards": {
                    row["process_id"]: row.get("mode_guards", [])
                    for row in runtime.spec["processes"]
                },
            }
        ),
        "geometry_digest": digest(
            {
                "topology": runtime.spec["topology"],
                "strata": {
                    row["process_id"]: row.get("strata", [])
                    for row in runtime.spec["processes"]
                },
            }
        ),
        "parent_model_digest": last.get("from_model_digest"),
        "migration_id": last.get("migration_id"),
    }


def _factor_messages(runtime: Any, internal: dict[str, Any]) -> list[dict[str, Any]]:
    messages = copy.deepcopy(internal.get("architecture_factor_messages", []))
    for trace in internal.get("evidence_trace", []):
        sample = trace.get("sample_time") or {"lower": "unknown", "upper": "unknown"}
        temporal_key = (
            "provenance:temporal:"
            f"sample={sample.get('lower')},{sample.get('upper')};"
            f"result={trace.get('result_at')};recorded={trace.get('recorded_at')};"
            f"available={trace.get('available_at')}"
        )
        provenance_digest_key = (
            f"provenance:source_payload:{trace.get('provenance_digest')}"
        )
        if trace.get("status") == "UNMAPPED":
            unknown_llr = float(trace.get("unknown_llr", 0.0))
            likelihoods = {
                "disposition:unmapped": 0.0,
                f"provenance:event:{trace['event_id']}:{trace['event_digest']}": 0.0,
                (
                    f"provenance:member:{trace['concept_id']}:"
                    f"{trace['semantic_fingerprint']}"
                ): 0.0,
                (
                    "provenance:inference_member:"
                    f"{trace['inference_fingerprint']}"
                ): 0.0,
                temporal_key: 0.0,
                provenance_digest_key: 0.0,
            }
            variables = [f"DISPOSITION:unmapped:{trace['concept_id']}"]
            if unknown_llr:
                # Unmapped evidence is not merely a display disposition: it
                # moves probability toward the explicit unmodeled-process
                # hypothesis and must remain replayable from canonical bytes.
                variables.append(UNKNOWN_PROCESS_ID)
                likelihoods["unmodeled:active_vs_reference"] = unknown_llr
            messages.append(
                {
                    "factor_id": f"DISPOSITION:UNMAPPED:{trace['event_id']}",
                    "factor_type": "measurement",
                    "variable_ids": sorted(variables),
                    "source_result_ids": [str(trace["source_result_id"])],
                    "log_likelihood_by_hypothesis": dict(sorted(likelihoods.items())),
                    "reliability": float(trace.get("reliability", 1.0)),
                }
            )
            continue
        if trace.get("status") in {"RECORD_ONLY_NONRANKABLE", "RECORD_ONLY_EVENT"}:
            generic_record_only = trace.get("status") == "RECORD_ONLY_EVENT"
            provenance_terms = {
                f"provenance:event:{trace['event_id']}:{trace['event_digest']}": 0.0,
                (
                    f"provenance:member:{trace['concept_id']}:"
                    f"{trace['semantic_fingerprint']}"
                ): 0.0,
                (
                    "provenance:inference_member:"
                    f"{trace['inference_fingerprint']}"
                ): 0.0,
                temporal_key: 0.0,
                provenance_digest_key: 0.0,
            }
            messages.append(
                {
                    "factor_id": str(trace["factor_id"]),
                    "factor_type": "constraint" if generic_record_only else "measurement",
                    "variable_ids": [
                        "DISPOSITION:record_only_event"
                        if generic_record_only
                        else "DISPOSITION:record_only_nonrankable"
                    ],
                    "source_result_ids": [str(trace["source_result_id"])],
                    "log_likelihood_by_hypothesis": {
                        (
                            "disposition:record_only_event"
                            if generic_record_only
                            else "disposition:record_only_nonrankable"
                        ): 0.0,
                        **provenance_terms,
                    },
                    "reliability": 0.0,
                }
            )
            continue
        if trace.get("status") == "CONSUMED_COMMON_CAUSE":
            likelihoods = {
                f"joint:known={active_set}": float(log_likelihood_value)
                for active_set, log_likelihood_value in trace.get(
                    "joint_log_likelihoods", {}
                ).items()
            }
            if trace.get("unknown_llr"):
                likelihoods["unmodeled:active_vs_reference"] = float(
                    trace["unknown_llr"]
                )
            likelihoods[
                f"common_cause:instance={trace['common_cause_instance_id']}"
            ] = 0.0
            for binding in trace["common_cause_bindings"]:
                likelihoods[
                    f"provenance:binding64:{_encode_common_binding(binding)}"
                ] = 0.0
            messages.append(
                {
                    "factor_id": str(trace["factor_id"]),
                    "factor_type": "common_cause",
                    "variable_ids": sorted(
                        {str(row["process_id"]) for row in trace.get("emissions", [])}
                    ),
                    "source_result_ids": list(trace["source_result_ids"]),
                    "log_likelihood_by_hypothesis": dict(sorted(likelihoods.items())),
                    "reliability": float(trace.get("reliability", 1.0)),
                }
            )
            continue
        if trace.get("status") != "CONSUMED":
            continue
        likelihoods: dict[str, float] = {}
        variables: set[str] = set()
        has_joint_likelihood = bool(trace.get("joint_log_likelihoods"))
        for emission in trace.get("emissions", []):
            pid = emission["process_id"]
            variables.add(pid)
            # A multi-process observation is one common-cause factor.  Its
            # per-process emission fields remain useful for local-coordinate
            # updates, but must not be serialized as independent evidence.
            if not has_joint_likelihood:
                likelihoods[f"process:{pid}:active"] = float(emission["active_log_likelihood"])
                likelihoods[f"process:{pid}:inactive"] = float(emission["inactive_log_likelihood"])
        for active_set, log_likelihood_value in trace.get(
            "joint_log_likelihoods", {}
        ).items():
            likelihoods[f"joint:known={active_set}"] = float(log_likelihood_value)
        for contribution in trace.get("topology_contributions", []):
            variables.add(contribution["target_process_id"])
            key = f"topology:{contribution['source_process_id']}->{contribution['target_process_id']}"
            likelihoods[key] = float(contribution["signed_llr"])
        if trace.get("unknown_llr"):
            variables.add(UNKNOWN_PROCESS_ID)
            likelihoods["unmodeled:active_vs_reference"] = float(trace["unknown_llr"])
        likelihoods[
            f"provenance:event:{trace['event_id']}:{trace['event_digest']}"
        ] = 0.0
        likelihoods[
            f"provenance:inference_member:{trace['inference_fingerprint']}"
        ] = 0.0
        likelihoods[temporal_key] = 0.0
        likelihoods[provenance_digest_key] = 0.0
        likelihoods[
            (
                f"provenance:member:{trace['concept_id']}:"
                f"{trace['semantic_fingerprint']}"
            )
        ] = 0.0
        messages.append(
            {
                "factor_id": str(trace["factor_id"]),
                "factor_type": "emission",
                "variable_ids": sorted(variables or {UNKNOWN_PROCESS_ID}),
                "source_result_ids": [str(trace["source_result_id"])],
                "log_likelihood_by_hypothesis": dict(sorted(likelihoods.items())),
                "reliability": float(trace.get("reliability", 1.0)),
            }
        )
    internal["architecture_factor_messages"] = copy.deepcopy(messages)
    return messages


def _factor_message_provenance(message: Mapping[str, Any]) -> dict[str, Any]:
    """Recover the event/member content bindings carried by a factor message."""

    event_rows: list[tuple[str, str]] = []
    member_rows: list[tuple[str, str]] = []
    inference_rows: list[str] = []
    common_bindings: list[dict[str, Any]] = []
    for key in message.get("log_likelihood_by_hypothesis", {}):
        if str(key).startswith("provenance:event:"):
            body = str(key)[len("provenance:event:") :]
            event_id, separator, event_digest = body.rpartition(":")
            if separator and event_id and event_digest:
                event_rows.append((event_id, event_digest))
        elif str(key).startswith("provenance:member:"):
            body = str(key)[len("provenance:member:") :]
            concept_id, separator, fingerprint = body.rpartition(":")
            if separator and concept_id and fingerprint:
                member_rows.append((concept_id, fingerprint))
        elif str(key).startswith("provenance:inference_member:"):
            fingerprint = str(key)[len("provenance:inference_member:") :]
            if fingerprint:
                inference_rows.append(fingerprint)
        elif str(key).startswith("provenance:binding64:"):
            common_bindings.append(
                _decode_common_binding(
                    str(key)[len("provenance:binding64:") :]
                )
            )
    if common_bindings:
        if event_rows or member_rows or inference_rows:
            raise ValueError(
                "common-cause factor cannot mix legacy and multi-member provenance"
            )
        member_keys = {
            (binding["source_result_id"], binding["concept_id"])
            for binding in common_bindings
        }
        event_ids = {binding["event_id"] for binding in common_bindings}
        if len(member_keys) != len(common_bindings) or len(event_ids) != len(common_bindings):
            raise ValueError("common-cause factor bindings must be exact-once")
        first = sorted(
            common_bindings,
            key=lambda binding: (
                binding["concept_id"], binding["source_result_id"], binding["event_id"]
            ),
        )[0]
        return {
            "event_id": str(first["event_id"]),
            "event_digest": str(first["event_digest"]),
            "concept_id": str(first["concept_id"]),
            "fingerprint": str(first["fingerprint"]),
            "inference_fingerprint": str(first["inference_fingerprint"]),
            "bindings": common_bindings,
        }
    if len(event_rows) != 1 or len(member_rows) != 1 or len(inference_rows) != 1:
        raise ValueError(
            "architecture factor message provenance is inconsistent: exactly one event/member binding required"
        )
    row = {
        "event_id": event_rows[0][0],
        "event_digest": event_rows[0][1],
        "concept_id": member_rows[0][0],
        "fingerprint": member_rows[0][1],
        "inference_fingerprint": inference_rows[0],
    }
    row["bindings"] = [
        {
            **row,
            "source_result_id": str(message["source_result_ids"][0]),
            "reliability": float(message["reliability"]),
        }
    ]
    return row


def _replay_factorial_joint(runtime: Any, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replay canonical factor messages from the model prior.

    This is the strongest authority check available from the frozen wire: a
    caller cannot inject an operative factor without also producing the exact
    posterior implied by the declared prior and all public factor messages.
    It does not claim cryptographic proof of the original source payload.
    """

    rows = copy.deepcopy(runtime._enumerate_prior())
    for message in messages:
        likelihoods = message["log_likelihood_by_hypothesis"]
        process_llrs: dict[str, float] = {}
        for pid in runtime.process_ids:
            active = likelihoods.get(f"process:{pid}:active")
            inactive = likelihoods.get(f"process:{pid}:inactive")
            if active is not None and inactive is not None:
                process_llrs[pid] = float(active) - float(inactive)
        for key, contribution in likelihoods.items():
            if not str(key).startswith("topology:"):
                continue
            edge = str(key).split(":", 1)[1]
            _, separator, target = edge.partition("->")
            if separator and target in runtime.process_ids:
                process_llrs[target] = process_llrs.get(target, 0.0) + float(contribution)
        joint_terms = {
            str(key)[len("joint:known=") :]: float(value)
            for key, value in likelihoods.items()
            if str(key).startswith("joint:known=")
        }
        unknown_llr = float(likelihoods.get("unmodeled:active_vs_reference", 0.0))
        log_weights: list[float] = []
        for hypothesis in rows:
            active_set = set(hypothesis["active_processes"])
            value = math.log(max(1e-300, float(hypothesis["probability"])))
            if joint_terms:
                local = sorted(active_set.intersection(message["variable_ids"]))
                joint_key = ",".join(local) or "-"
                if joint_key not in joint_terms:
                    raise ValueError(
                        "architecture joint common-cause factor omits an active-set likelihood"
                    )
                value += joint_terms[joint_key]
            else:
                value += sum(
                    llr for pid, llr in process_llrs.items() if pid in active_set
                )
            if hypothesis["unknown_active"]:
                value += unknown_llr
            log_weights.append(value)
        normalizer = max(log_weights) + math.log(
            sum(math.exp(value - max(log_weights)) for value in log_weights)
        )
        for hypothesis, value in zip(rows, log_weights):
            hypothesis["probability"] = math.exp(value - normalizer)
    return rows


def _active_process_posterior(runtime: Any, internal: Mapping[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
    support: dict[str, set[str]] = {pid: set() for pid in runtime.process_ids}
    oppose: dict[str, set[str]] = {pid: set() for pid in runtime.process_ids}
    for message in messages:
        for pid in runtime.process_ids:
            active = message["log_likelihood_by_hypothesis"].get(f"process:{pid}:active")
            inactive = message["log_likelihood_by_hypothesis"].get(f"process:{pid}:inactive")
            if active is None or inactive is None:
                continue
            (support if active > inactive else oppose if active < inactive else support)[pid].add(message["factor_id"])
    thresholds = runtime.spec["inference"]["activation_status_thresholds"]
    marginals = []
    for pid in runtime.process_ids:
        probability = float(internal["process_activation_marginals"][pid])
        modes = internal["per_process"][pid]["mode_posterior"]
        leading_mode = max(modes, key=modes.get)
        if probability <= float(thresholds["inactive_upper"]):
            status = "inactive"
        elif leading_mode == "recovering" and probability >= float(thresholds["possible_lower"]):
            status = "resolving"
        elif probability >= float(thresholds["active_lower"]):
            status = "active"
        else:
            status = "possible"
        organ = str(runtime.processes[pid].get("organ_or_domain") or "UNSPECIFIED_DOMAIN")
        marginals.append(
            {
                "process_id": pid,
                "branch_id": str(runtime.processes[pid].get("branch_id") or pid),
                "organ_ids": [organ],
                "p_active": probability,
                "activation_status": status,
                "supporting_factor_ids": sorted(support[pid]),
                "opposing_factor_ids": sorted(oppose[pid]),
            }
        )
    unknown = float(internal["epistemic"]["unknown_process_probability"])
    marginals.append(
        {
            "process_id": UNKNOWN_PROCESS_ID,
            "branch_id": "OPEN_WORLD",
            "organ_ids": ["UNMODELED_DOMAIN"],
            "p_active": unknown,
            "activation_status": "unknown",
            "supporting_factor_ids": [
                message["factor_id"]
                for message in messages
                if message["log_likelihood_by_hypothesis"].get("unmodeled:active_vs_reference", 0.0) > 0.0
            ],
            "opposing_factor_ids": [
                message["factor_id"]
                for message in messages
                if message["log_likelihood_by_hypothesis"].get("unmodeled:active_vs_reference", 0.0) < 0.0
            ],
        }
    )
    hypotheses = []
    for row in internal["joint_hypotheses"]:
        active = list(row["active_processes"])
        if row["unknown_active"]:
            active.append(UNKNOWN_PROCESS_ID)
        hypotheses.append(
            {
                "hypothesis_id": row["configuration_id"],
                "active_process_ids": sorted(active),
                "probability": float(row["probability"]),
            }
        )
    dependencies = [
        {
            "factor_id": f"coactivation:{index}:{row['process_a']}:{row['process_b']}",
            "process_ids": sorted([row["process_a"], row["process_b"]]),
            "relation_type": "coactivation" if float(row.get("log_potential_when_coactive", 0.0)) >= 0.0 else "inhibition",
            "log_potential": float(row.get("log_potential_when_coactive", 0.0)),
            "conditionality": str(row.get("conditionality", "declared model coactivation potential")),
        }
        for index, row in enumerate(runtime.spec["coactivation_interactions"])
    ]
    world_models = [
        {"hypothesis_id": "DECLARED_MODEL", "model_digest": runtime.model_digest, "probability": 1.0 - unknown},
        {"hypothesis_id": "UNMODELED_WORLD", "model_digest": digest({"kind": "unmodeled", "scope": _scope(runtime)["scope_digest"]}), "probability": unknown},
    ]
    return {
        # The activation table is exact, but the whole posterior is not a
        # joint distribution over activation plus every local coordinate/mode.
        # Local rows are q(x,m | own process active) mean-field factors.
        "representation": "hybrid_approximation",
        "process_marginals": marginals,
        "dependence_factors": dependencies,
        "joint_hypotheses": hypotheses,
        "world_model_hypotheses": world_models,
    }


def _local_states(runtime: Any, internal: Mapping[str, Any], messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    source_factors: dict[tuple[str, str], set[str]] = {}
    for message in messages:
        for pid in runtime.process_ids:
            if pid not in message["variable_ids"]:
                continue
            concept_sources = message["source_result_ids"]
            for obs in runtime.spec["observations"]:
                if obs["factor_id"] != message["factor_id"]:
                    continue
                for emission in obs["emissions"]:
                    update = emission.get("coordinate_update")
                    if emission["process_id"] == pid and update:
                        source_factors.setdefault((pid, update["coordinate_id"]), set()).add(message["factor_id"])
    rows = []
    for pid in runtime.process_ids:
        local = internal["per_process"][pid]
        coordinates = []
        for coord in runtime.processes[pid]["coordinates"]:
            cid = coord["coordinate_id"]
            estimate = local["coordinates"][cid]
            low, high = map(float, coord["bounds"])
            sd = max(0.0, float(estimate["uncertainty"]) * (high - low))
            mean = float(estimate["mean"])
            coordinates.append(
                {
                    "coordinate_id": cid,
                    "unit": str(coord.get("unit", "normalized")),
                    "support": {"lower": low, "upper": high},
                    "distribution": {
                        "family": "truncated_normal" if sd > 0 else "point",
                        "mean": mean,
                        "sd": sd,
                        "quantiles": {
                            "0.05": max(low, mean - 1.645 * sd),
                            "0.5": mean,
                            "0.95": min(high, mean + 1.645 * sd),
                        },
                        "particle_digest": None,
                    },
                    "knownness": _clamp01(1.0 - float(estimate["uncertainty"])),
                    "source_factor_ids": sorted(source_factors.get((pid, cid), set())),
                }
            )
        support_dependence = []
        for exposure_id, instance in internal["action_instances"].items():
            action = runtime.actions.get(instance["action_id"])
            if action is None:
                continue
            for effect in action.get("effects", []):
                if effect["process_id"] != pid:
                    continue
                washout = float(action.get("washout_steps", 0.0))
                remaining = float(instance.get("washout_remaining", 0.0))
                residual = 1.0 if instance["status"] == "active" else remaining / washout if washout else 0.0
                fraction = _clamp01(
                    abs(float(effect["delta_per_unit_step"]))
                    * float(instance["current_dose"])
                    / float(action["dose_reference"])
                    * residual
                )
                support_dependence.append(
                    {
                        "action_instance_id": exposure_id,
                        "coordinate_id": effect["coordinate_id"],
                        "estimated_fraction_supported": fraction,
                        "trend": "stable" if instance["status"] == "active" else "decreasing",
                    }
                )
        for stratum_id in sorted(local.get("stratum_posterior", {f"stratum:{pid}": 1.0})):
            rows.append(
                {
                "stratum_id": stratum_id,
                "process_id": pid,
                "organ_id": str(runtime.processes[pid].get("organ_or_domain") or "UNSPECIFIED_DOMAIN"),
                "coordinates": coordinates,
                "mode_posterior": [
                    {"mode_id": mid, "probability": float(probability)}
                    for mid, probability in sorted(local["mode_posterior"].items())
                ],
                "support_dependence": support_dependence,
                "last_transition_cursor": local.get("last_transition_cursor"),
                }
            )
    return rows


def _cross_couplings(runtime: Any, internal: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for index, coupling in enumerate(runtime.spec["process_couplings"]):
        source = coupling["source_process_id"]
        strength = float(coupling["strength_per_step"])
        rows.append(
            {
                "coupling_id": f"dynamic:{index}:{source}->{coupling['target_process_id']}",
                "source_stratum_id": _primary_stratum_id(internal, source),
                "target_stratum_id": _primary_stratum_id(internal, coupling['target_process_id']),
                "coupling_type": "dynamic",
                "effect_direction": "increase" if strength > 0 else "decrease" if strength < 0 else "constraint_only",
                "lag": {"lower": 0.0, "upper": 1.0, "unit": runtime.spec["scope"]["horizon"]["unit"]},
                "activity_probability": float(internal["process_activation_marginals"][source]),
                "conditionality": str(coupling.get("conditionality", "source process active")),
                "source_factor_ids": [f"declared-process-coupling:{index}"],
            }
        )
    for index, coupling in enumerate(runtime.spec["mode_couplings"]):
        source = coupling["source_process_id"]
        probability = (
            float(internal["process_activation_marginals"][source])
            * float(internal["per_process"][source]["mode_posterior"][coupling["source_mode_id"]])
        )
        rows.append(
            {
                "coupling_id": f"mode:{index}:{source}->{coupling['target_process_id']}",
                "source_stratum_id": _primary_stratum_id(internal, source),
                "target_stratum_id": _primary_stratum_id(internal, coupling['target_process_id']),
                "coupling_type": "mode_guard",
                "effect_direction": "increase" if float(coupling["log_potential_per_step"]) >= 0 else "decrease",
                "lag": {"lower": 0.0, "upper": 1.0, "unit": runtime.spec["scope"]["horizon"]["unit"]},
                "activity_probability": _clamp01(probability),
                "conditionality": f"source mode {coupling['source_mode_id']}",
                "source_factor_ids": [f"declared-mode-coupling:{index}"],
            }
        )
    for pid in runtime.process_ids:
        for index, guard in enumerate(runtime.processes[pid].get("mode_guards", [])):
            value = float(internal["per_process"][pid]["coordinates"][guard["coordinate_id"]]["mean"])
            if guard["direction"] == "above":
                active = value >= float(guard["enter_threshold"]) or value <= float(guard["exit_threshold"])
            else:
                active = value <= float(guard["enter_threshold"]) or value >= float(guard["exit_threshold"])
            rows.append(
                {
                    "coupling_id": f"guard:{pid}:{guard['guard_id']}",
                    "source_stratum_id": _primary_stratum_id(internal, pid),
                    "target_stratum_id": _primary_stratum_id(internal, pid),
                    "coupling_type": "mode_guard",
                    "effect_direction": "mixed",
                    "lag": {"lower": 0.0, "upper": 0.0, "unit": runtime.spec["scope"]["horizon"]["unit"]},
                    "activity_probability": float(guard["transition_probability"]) if active else 0.0,
                    "conditionality": (
                        f"{guard['coordinate_id']} {guard['direction']} enter={guard['enter_threshold']} "
                        f"exit={guard['exit_threshold']}"
                    ),
                    "source_factor_ids": [f"declared-mode-guard:{pid}:{index}"],
                }
            )
    return rows


def _action_memory(runtime: Any, internal: Mapping[str, Any]) -> dict[str, Any]:
    processed = sorted(internal["event_ledger"])
    cursor = {event_id: index + 1 for index, event_id in enumerate(processed)}
    instances = []
    for exposure_id, row in sorted(internal["action_instances"].items()):
        action = runtime.actions[row["action_id"]]
        washout_steps = float(action.get("washout_steps", 0.0))
        remaining = float(row.get("washout_remaining", 0.0))
        if row["status"] == "active":
            status = "active"
        elif row["status"] == "held":
            status = "held"
        elif row["status"] == "completed":
            status = "completed"
        else:
            status = "residual" if remaining > 0 else "stopped"
        lifecycle = list(row.get("lifecycle_event_ids", []))
        dose_history = copy.deepcopy(row.get("dose_history", []))
        if not dose_history:
            first = lifecycle[0] if lifecycle else f"migration:{exposure_id}"
            dose_history = [
                {
                    "event_cursor": cursor.get(first, int(row.get("started_cursor", 0) or 0)),
                    "operation": "start",
                    "value": float(row["current_dose"]),
                    "unit": str(row.get("dose_unit") or "normalized"),
                    "route": None,
                }
            ]
        instances.append(
            {
                "action_instance_id": exposure_id,
                "action_id": row["action_id"],
                "status": status,
                "planned_cursor": row.get("planned_cursor"),
                "started_cursor": int(row.get("started_cursor") or dose_history[0]["event_cursor"]),
                "held_cursor": row.get("held_cursor"),
                "stopped_cursor": row.get("stopped_cursor"),
                "completed_cursor": row.get("completed_cursor"),
                "dose_history": dose_history,
                "cumulative_exposure": {
                    "value": float(row["cumulative_exposure"]),
                    "unit": f"{row.get('dose_unit') or 'normalized'}*{runtime.spec['scope']['horizon']['unit']}",
                },
                "washout": {
                    "residual_effect_probability": _clamp01(remaining / washout_steps if washout_steps else 0.0),
                    "estimated_remaining_fraction": _clamp01(remaining / washout_steps if washout_steps else 0.0),
                },
                "response_summaries": copy.deepcopy(row.get("response_summaries", [])),
                "source_event_ids": sorted(
                    set(lifecycle or [f"migration:{exposure_id}"])
                ),
            }
        )
    for plan in internal.get("planned_action_records", []):
        instances.append(
            {
                "action_instance_id": f"planned:{plan['event_id']}",
                "action_id": str(plan.get("action_id") or "UNSPECIFIED_PLANNED_ACTION"),
                "status": "planned",
                "planned_cursor": int(plan.get("event_cursor") or cursor.get(plan["event_id"], 0)),
                "started_cursor": None,
                "held_cursor": None,
                "stopped_cursor": None,
                "completed_cursor": None,
                "dose_history": [],
                "cumulative_exposure": {"value": 0.0, "unit": "none"},
                "washout": {"residual_effect_probability": 0.0, "estimated_remaining_fraction": 0.0},
                "response_summaries": [],
                "source_event_ids": [str(plan["event_id"])],
            }
        )
    return {
        "instances": instances,
        "current_policy_id": internal.get("current_policy_id"),
        "history_digest": digest(instances),
    }


def _geometry(runtime: Any, internal: Mapping[str, Any], scope: Mapping[str, Any]) -> dict[str, Any]:
    neighbors = []
    stratum_rows = {
        row["stratum_id"]: (pid, row)
        for pid in runtime.process_ids
        for row in (
            runtime.processes[pid].get("strata")
            or [{"stratum_id": f"stratum:{pid}", "action_effect_modifiers": {}}]
        )
    }
    for source in sorted(stratum_rows):
        candidates = []
        for target in stratum_rows:
            if target == source:
                continue
            distance = runtime._stratum_distance_unchecked(source, target)
            if math.isfinite(distance):
                candidates.append((distance, target))
        if not candidates:
            continue
        distance, target = min(candidates)
        source_pid, source_row = stratum_rows[source]
        target_pid, target_row = stratum_rows[target]
        witnesses = sorted(
            action_id
            for action_id, action in runtime.actions.items()
            if (
                any(
                    effect["process_id"] in {source_pid, target_pid}
                    for effect in action.get("effects", [])
                )
                or float(
                    source_row.get("action_effect_modifiers", {}).get(action_id, 1.0)
                )
                != float(
                    target_row.get("action_effect_modifiers", {}).get(action_id, 1.0)
                )
            )
        )
        neighbors.append(
            {
                "reference_state_id": f"reference-state:{source}->{target}",
                "distance": float(distance),
                "shared_scope_digest": scope["scope_digest"],
                "policy_witness_ids": witnesses,
            }
        )
    return {
        "geometry_digest": digest(
            {
                "topology": runtime.spec["topology"],
                "strata": {
                    row["process_id"]: row.get("strata", [])
                    for row in runtime.spec["processes"]
                },
            }
        ),
        "distance_metric_id": scope["distance_metric_id"],
        "stratum_memberships": [
            {
                "stratum_id": stratum_id,
                "probability": _clamp01(
                    float(internal["process_activation_marginals"][pid])
                    * float(stratum_probability)
                ),
            }
            for pid in runtime.process_ids
            for stratum_id, stratum_probability in sorted(
                internal["per_process"][pid].get(
                    "stratum_posterior", {f"stratum:{pid}": 1.0}
                ).items()
            )
        ],
        "nearest_behavioral_neighbors": neighbors,
    }


def _history(internal: Mapping[str, Any]) -> dict[str, Any]:
    return encode_history_summary(
        internal["history_summary"],
        mode_transitions=internal.get("mode_transitions", []),
        action_response_windows=internal.get("action_response_windows", []),
        retained_event_ids=internal["event_ledger"],
    )


def _epistemic(runtime: Any, internal: dict[str, Any]) -> dict[str, Any]:
    epistemic = internal["epistemic"]
    mapped = int(epistemic["mapped_observation_count"])
    unmapped = int(epistemic["unmapped_observation_count"])
    total = mapped + unmapped
    mapping_gap = float(epistemic["mapping_residual"])
    unexplained = copy.deepcopy(internal.get("architecture_unexplained_observations", []))
    for trace in internal.get("evidence_trace", []):
        if trace.get("status") == "UNMAPPED":
            unexplained.append(
                {
                    "result_id": str(trace.get("source_result_id") or trace["event_id"]),
                    "reason": "unmapped",
                    "surprisal": float(max(0.0, trace.get("unknown_llr", 0.0))),
                    "candidate_process_ids": list(runtime.process_ids),
                }
            )
    internal["architecture_unexplained_observations"] = copy.deepcopy(unexplained)
    uncertainties = [
        float(estimate["uncertainty"])
        for local in internal["per_process"].values()
        for estimate in local["coordinates"].values()
    ]
    measurement_count = int(epistemic.get("measurement_count", 0))
    reliability_sum = float(epistemic.get("measurement_reliability_sum", 0.0))
    measurement_quality_uncertainty = (
        _clamp01(1.0 - reliability_sum / measurement_count)
        if measurement_count > 0
        else 0.0
    )
    coordinate_uncertainty = _clamp01(
        sum(uncertainties) / len(uncertainties) if uncertainties else 1.0
    )
    causal_statuses = [str(action.get("causal_status", "UNIDENTIFIABLE")) for action in runtime.actions.values()]
    causal_nonidentifiability = (
        sum(status != "IDENTIFIED_WITHIN_SCOPE" for status in causal_statuses) / len(causal_statuses)
        if causal_statuses else 1.0
    )
    unmodeled = float(epistemic["unknown_process_probability"])
    missing_information = copy.deepcopy(
        internal.get("missing_distinguishing_information", [])
    )
    factorization_gap_id = "factorization:unsupported-correlations"
    if not any(
        str(row.get("information_id")) == factorization_gap_id
        for row in missing_information
    ):
        missing_information.append(
            {
                "information_id": factorization_gap_id,
                "target_query_id": "diagnose.active_process_posterior",
                "expected_discrimination": 1.0,
                "availability": "not_available",
                "risk_class": "material",
            }
        )
    return {
        "mapping_coverage": _clamp01(1.0 - mapping_gap),
        "mapping_gap": _clamp01(mapping_gap),
        "model_misfit": _clamp01(epistemic["model_misfit_residual"]),
        "unmodeled_process": _clamp01(unmodeled),
        "measurement_uncertainty": max(
            coordinate_uncertainty, measurement_quality_uncertainty
        ),
        "causal_nonidentifiability": _clamp01(causal_nonidentifiability),
        "scope_gap": _clamp01(
            max(
                float(epistemic["unknown_process_probability"]),
                mapping_gap,
                float(runtime.spec.get("scope", {}).get("declared_scope_gap", 0.0)),
            )
        ),
        "unexplained_observations": unexplained,
        "missing_distinguishing_information": missing_information,
        # The public state is a hybrid approximation, not a full joint over
        # activation and local state.  Queries may answer within the declared
        # factorization scope but must never present the result as unrestricted.
        "abstention_status": "partial_answer_only",
    }


def _identifiability(runtime: Any, internal: Mapping[str, Any]) -> list[dict[str, Any]]:
    unknown = float(internal["epistemic"]["unknown_process_probability"])
    worlds = ["DECLARED_MODEL"] + (["UNMODELED_WORLD"] if unknown > 0.0 else [])
    outcome_ids = list(runtime.spec["scope"]["outcome_ids"])
    objective_id = str(outcome_ids[0])
    objective_upper = sum(
        float(coordinate.get("objective_weight", 0.0))
        for process in runtime.processes.values()
        for coordinate in process["coordinates"]
    )
    factorization_assumptions = sorted(
        set(runtime.spec["posterior_factorization"]["assumption_ids"])
    )
    claims = [
        {
            "query_id": "diagnose.active_process_posterior",
            "target_id": "active_process_posterior",
            "status": "PARTIALLY_IDENTIFIED",
            "assumption_ids": sorted(set([
                "declared-emission-families",
                "declared-factorial-priors",
                "public-events-only",
                *factorization_assumptions,
            ])),
            "compatible_world_ids": worlds,
            "identified_set": {"lower": 0.0, "upper": 1.0, "unit": "process_activation_probability"},
            "reason": (
                "Activation-configuration mass is exact for the declared finite factor model; "
                "process-local coordinates/modes are conditional-active mean-field factors. "
                "Unsupported activation-local and cross-process local-state correlations are "
                "OUT_OF_SCOPE, and parameters are not clinically calibrated."
            ),
        },
        {
            "query_id": "forecast.no_new_action",
            "target_id": objective_id,
            "status": "PARTIALLY_IDENTIFIED",
            "assumption_ids": sorted(set([
                "declared-mode-drift",
                "declared-couplings",
                "existing-action-lifecycle",
                *factorization_assumptions,
            ])),
            "compatible_world_ids": worlds,
            "identified_set": {
                "lower": 0.0,
                "upper": objective_upper,
                "unit": objective_id,
            },
            "reason": (
                "Forecast is model-assumed, uncalibrated, and uses conditional-active "
                "mean-field local propagation; unsupported correlations and unmodeled "
                "processes remain outside the point forecast."
            ),
        },
    ]
    for action_id, action in sorted(runtime.actions.items()):
        status = str(action.get("causal_status", "UNIDENTIFIABLE"))
        if status not in {"IDENTIFIED_WITHIN_SCOPE", "PARTIALLY_IDENTIFIED", "UNIDENTIFIABLE", "OUT_OF_SCOPE"}:
            status = "UNIDENTIFIABLE"
        action_worlds = sorted(
            str(world_id)
            for world_id in (
                action.get("compatible_world_values", {}).keys()
                or action.get("compatible_world_ids", [])
                or worlds
            )
        )
        claims.append(
            {
                "query_id": f"action:{action_id}",
                "target_id": objective_id,
                "status": status,
                "assumption_ids": sorted(set([
                    *action.get("assumption_ids", ["declared-toy-action-effect"]),
                    *factorization_assumptions,
                ])),
                "compatible_world_ids": action_worlds,
                "identified_set": copy.deepcopy(
                    action.get(
                        "identified_set",
                        {"lower": None, "upper": None, "unit": objective_id},
                    )
                ),
                "reason": (
                    str(action.get(
                        "identifiability_reason",
                        "No patient-level causal identification evidence is encoded.",
                    ))
                    + " Local response propagation additionally assumes the declared "
                    "conditional-active mean-field factorization; unsupported correlations "
                    "are OUT_OF_SCOPE."
                ),
            }
        )
    return claims


def internal_to_architecture_state(runtime: Any, internal: dict[str, Any]) -> SharedPatientState:
    """Create the only public canonical state bytes consumed by all queries."""

    messages = _factor_messages(runtime, internal)
    scope = _scope(runtime)
    event_ids = sorted(internal["event_ledger"])
    event_digest = str(internal.get("event_ledger_digest") or digest([]))
    new_ids = list(internal.get("lineage", {}).get("consumed_event_ids", []))
    update_id = "update:" + digest(
        {
            "parent": internal.get("lineage", {}).get("parent_state_hash"),
            "cut": internal["state_time"],
            "new_event_ids": new_ids,
            "event_ledger_digest": event_digest,
        }
    )
    wire: dict[str, Any] = {
        "schema_version": STATE_SCHEMA_VERSION,
        "architecture_version": ARCHITECTURE_VERSION,
        "state_id": "state:" + update_id.split(":", 1)[1],
        "as_of": {
            "cut_id": f"cut:{internal['state_time']}",
            "event_cursor": len(event_ids),
            "availability_watermark": f"available-through:{internal['state_time']}",
            "occurred_time_lower": None,
            "occurred_time_upper": None,
            # The frozen schema reserves this field for RFC3339 date-time.
            # Numeric model time is encoded by cut_id and must not masquerade
            # as a wall-clock string such as "0.0".
            "clock_time": None,
        },
        "scope": scope,
        "model_lineage": _model_lineage(runtime, internal),
        "event_lineage": {
            "event_ledger_digest": event_digest,
            "processed_event_ids": event_ids,
            "parent_state_hash": internal.get("lineage", {}).get("parent_state_hash"),
            "update_id": update_id,
            "new_event_ids": new_ids,
        },
        "active_process_posterior": _active_process_posterior(runtime, internal, messages),
        "local_states": _local_states(runtime, internal, messages),
        "cross_couplings": _cross_couplings(runtime, internal),
        "action_memory": _action_memory(runtime, internal),
        "factor_graph_state": {
            "graph_digest": digest(_factor_graph_preimage(runtime)),
            "messages_digest": digest(messages),
            "factor_messages": messages,
            "recognized_result_ids": sorted(
                {
                    source
                    for message in messages
                    if not str(message["factor_id"]).startswith("DISPOSITION:UNMAPPED:")
                    for source in message["source_result_ids"]
                }
            ),
            "unrecognized_result_ids": sorted(
                {
                    str(trace.get("source_result_id") or trace["event_id"])
                    for trace in internal.get("evidence_trace", [])
                    if trace.get("status") == "UNMAPPED"
                }
                | {
                    row["result_id"]
                    for row in internal.get("architecture_unexplained_observations", [])
                    if row["reason"] == "unmapped"
                }
            ),
        },
        "geometry_state": _geometry(runtime, internal, scope),
        "history_summary": _history(internal),
        "epistemic_residual": _epistemic(runtime, internal),
        "identifiability_claims": _identifiability(runtime, internal),
        "integrity": {"canonicalization": "RFC8785-JCS", "hash_algorithm": "SHA-256", "state_hash": "0" * 64},
    }
    wire["integrity"]["state_hash"] = architecture_state_hash(wire)
    internal["evidence_trace"] = []
    warm = SharedPatientState(wire, copy.deepcopy(internal))
    return SharedPatientState(
        wire,
        None,
        build_event_ledger_proof(warm),
    )


def architecture_state_to_internal(runtime: Any, state: SharedPatientState) -> dict[str, Any]:
    """Reconstruct the operational cache from an authoritative architecture wire."""

    wire = state.payload
    state_time = model_time_from_as_of(wire["as_of"])
    internal = runtime._empty_payload(state_time)
    internal["state_time"] = state_time
    joint = []
    for row in wire["active_process_posterior"]["joint_hypotheses"]:
        active = [pid for pid in row["active_process_ids"] if pid != UNKNOWN_PROCESS_ID]
        unknown = UNKNOWN_PROCESS_ID in row["active_process_ids"]
        joint.append(
            {
                "configuration_id": runtime._configuration_id(active, unknown),
                "active_processes": sorted(active),
                "unknown_active": unknown,
                "probability": float(row["probability"]),
            }
        )
    internal["joint_hypotheses"] = joint
    for local in wire["local_states"]:
        pid = local["process_id"]
        if pid not in internal["per_process"]:
            continue
        internal["per_process"][pid]["coordinates"] = {
            row["coordinate_id"]: {
                "mean": float(row["distribution"]["mean"]),
                "uncertainty": _clamp01(1.0 - float(row["knownness"])),
            }
            for row in local["coordinates"]
        }
        internal["per_process"][pid]["mode_posterior"] = {
            row["mode_id"]: float(row["probability"]) for row in local["mode_posterior"]
        }
        internal["per_process"][pid]["last_transition_cursor"] = local["last_transition_cursor"]
    membership = {
        row["stratum_id"]: float(row["probability"])
        for row in wire["geometry_state"]["stratum_memberships"]
    }
    marginals = {
        row["process_id"]: float(row["p_active"])
        for row in wire["active_process_posterior"]["process_marginals"]
    }
    for pid in runtime.process_ids:
        declared = runtime.processes[pid].get("strata") or [
            {"stratum_id": f"stratum:{pid}", "prior": 1.0}
        ]
        weights = {
            row["stratum_id"]: membership.get(row["stratum_id"], 0.0)
            / max(1e-12, marginals.get(pid, 0.0))
            for row in declared
        }
        total = sum(weights.values())
        if total <= 0.0:
            weights = {row["stratum_id"]: float(row.get("prior", 0.0)) for row in declared}
            total = sum(weights.values())
        internal["per_process"][pid]["stratum_posterior"] = {
            key: value / total for key, value in sorted(weights.items())
        }
    proof_entries = {}
    if state._event_ledger_proof is not None:
        proof_entries = {
            str(row["event_id"]): str(row["event_digest"])
            for row in state._event_ledger_proof["entries"]
        }
    internal["event_ledger"] = {
        event_id: proof_entries.get(event_id)
        for event_id in wire["event_lineage"]["processed_event_ids"]
    }
    internal["event_ledger_digest"] = wire["event_lineage"]["event_ledger_digest"]
    internal["architecture_factor_messages"] = copy.deepcopy(wire["factor_graph_state"]["factor_messages"])
    internal["evidence_trace"] = []
    internal["evidence_ledger"] = {}
    for message in wire["factor_graph_state"]["factor_messages"]:
        provenance = _factor_message_provenance(message)
        for binding in provenance["bindings"]:
            source = str(binding["source_result_id"])
            evidence_key = f"source:{source}"
            entry = internal["evidence_ledger"].setdefault(evidence_key, {"members": {}})
            known = entry["members"].get(binding["concept_id"])
            if known is not None and known.get("fingerprint") != binding["fingerprint"]:
                raise ValueError(
                    f"architecture factor/source member provenance is inconsistent: "
                    f"{source}:{binding['concept_id']}"
                )
            entry["members"][binding["concept_id"]] = copy.deepcopy(binding)
    internal["history_summary"] = decode_history_features(
        wire["history_summary"]["trajectory_features"],
        default_state_time=state_time,
    )
    internal["mode_transitions"] = copy.deepcopy(wire["history_summary"]["mode_transitions"])
    internal["action_response_windows"] = copy.deepcopy(wire["history_summary"]["action_response_windows"])
    internal["architecture_unexplained_observations"] = copy.deepcopy(
        wire["epistemic_residual"]["unexplained_observations"]
    )
    internal["missing_distinguishing_information"] = copy.deepcopy(
        wire["epistemic_residual"]["missing_distinguishing_information"]
    )
    mapped_messages = [
        message
        for message in wire["factor_graph_state"]["factor_messages"]
        if not str(message["factor_id"]).startswith("DISPOSITION:")
    ]
    mapped = len(mapped_messages)
    unmapped = len(wire["factor_graph_state"]["unrecognized_result_ids"])
    # Generic RecordOnly factors bind source semantics to lineage but are not
    # failed/withheld measurements and therefore must not inflate measurement
    # uncertainty on cold reconstruction.
    all_measurement_messages = [
        message
        for message in wire["factor_graph_state"]["factor_messages"]
        if message["factor_type"] != "constraint"
    ]
    represented_unmapped_sources = {
        source
        for message in all_measurement_messages
        if str(message["factor_id"]).startswith("DISPOSITION:UNMAPPED:")
        for source in message["source_result_ids"]
    }
    missing_unmapped_count = len(
        set(wire["factor_graph_state"]["unrecognized_result_ids"])
        - represented_unmapped_sources
    )
    measurement_count = missing_unmapped_count
    reliability_sum = float(missing_unmapped_count)
    for message in all_measurement_messages:
        provenance = _factor_message_provenance(message)
        if message["factor_type"] == "common_cause":
            measurement_count += len(provenance["bindings"])
            reliability_sum += sum(
                float(binding["reliability"])
                for binding in provenance["bindings"]
            )
        else:
            measurement_count += 1
            reliability_sum += float(message["reliability"])
    internal["epistemic"] = {
        "mapped_observation_count": mapped,
        "unmapped_observation_count": unmapped,
        "deduplicated_evidence_count": 0,
        "measurement_count": measurement_count,
        "measurement_reliability_sum": reliability_sum,
        "misfit_sum": float(wire["epistemic_residual"]["model_misfit"]) * max(1, mapped),
        "mapping_residual": float(wire["epistemic_residual"]["mapping_gap"]),
        "model_misfit_residual": float(wire["epistemic_residual"]["model_misfit"]),
        "unknown_process_probability": float(wire["epistemic_residual"]["unmodeled_process"]),
    }
    internal["planned_action_records"] = []
    internal["action_instances"] = {}
    internal["action_source_ledger"] = {}
    internal["action_source_identity_complete"] = not bool(
        wire["action_memory"]["instances"]
    )
    for row in wire["action_memory"]["instances"]:
        if row["status"] == "planned":
            source_id = str(row["source_event_ids"][0])
            internal["planned_action_records"].append(
                {
                    "event_id": source_id,
                    "source_result_id": source_id,
                    "source_fingerprint": None,
                    "action_id": row["action_id"],
                    "exposure_id": None,
                    "event_cursor": row["planned_cursor"],
                    "available_at": state_time,
                }
            )
            internal["action_source_ledger"][source_id] = {
                "fingerprint": None,
                "event_type": "PlannedAction",
                "action_id": row["action_id"],
                "exposure_id": None,
            }
            continue
        action = runtime.actions.get(row["action_id"])
        washout_steps = float(action.get("washout_steps", 0.0)) if action else 0.0
        last_dose = next(
            (
                item["value"]
                for item in reversed(row["dose_history"])
                if item.get("value") is not None
            ),
            0.0,
        )
        internal["action_instances"][row["action_instance_id"]] = {
            "action_id": row["action_id"],
            "status": (
                "active" if row["status"] in {"started", "active"}
                else "held" if row["status"] == "held"
                else "completed" if row["status"] == "completed"
                else "stopped"
            ),
            "planned_cursor": row["planned_cursor"],
            "started_at": state_time,
            # The action was already public in the canonical state at this
            # cut, so a future observation strictly after the cut may be
            # ordered after it.  Earlier/delayed observations remain
            # ambiguous and are not attributed as responses.
            "definitely_active_by": state_time,
            "started_cursor": row["started_cursor"],
            "last_accounted_at": state_time,
            "last_lifecycle_occurred_at": state_time,
            "current_dose": float(last_dose or 0.0),
            "dose_unit": row["dose_history"][-1]["unit"] if row["dose_history"] else None,
            "cumulative_exposure": float(row["cumulative_exposure"]["value"] or 0.0),
            "stopped_at": state_time if row["stopped_cursor"] is not None else None,
            "held_cursor": row["held_cursor"],
            "stopped_cursor": row["stopped_cursor"],
            "completed_cursor": row["completed_cursor"],
            "washout_remaining": float(row["washout"]["estimated_remaining_fraction"]) * washout_steps,
            "lifecycle_event_ids": list(row["source_event_ids"]),
            "source_result_ids": list(row["source_event_ids"]),
            "dose_history": copy.deepcopy(row["dose_history"]),
            "response_summaries": copy.deepcopy(row["response_summaries"]),
        }
        for source_id in row["source_event_ids"]:
            internal["action_source_ledger"][str(source_id)] = {
                "fingerprint": None,
                "event_type": "ActionLifecycle",
                "action_id": row["action_id"],
                "exposure_id": row["action_instance_id"],
            }
    migrations = []
    if wire["model_lineage"]["migration_id"]:
        migrations.append(
            {
                "migration_id": wire["model_lineage"]["migration_id"],
                "from_model_digest": wire["model_lineage"]["parent_model_digest"],
                "to_model_digest": wire["model_lineage"]["model_digest"],
            }
        )
    internal["lineage"] = {
        "parent_state_hash": state.state_hash,
        "consumed_event_ids": [],
        "skipped_duplicate_event_ids": [],
        "migration_history": migrations,
    }
    runtime._derive_marginals(internal)
    # Every public query/update reconstructs from the same canonical bytes and
    # crosses this one model-bound validation boundary.  Do not let diagnose,
    # forecast, planning, or recursive update each acquire a different notion
    # of a valid state.
    validate_state_payload(
        internal,
        runtime.spec,
        state_context={
            "event_cursor": wire["as_of"]["event_cursor"],
            "processed_event_ids": wire["event_lineage"]["processed_event_ids"],
            "new_event_ids": wire["event_lineage"]["new_event_ids"],
            "parent_state_hash": wire["event_lineage"]["parent_state_hash"],
            "model_digest": wire["model_lineage"]["model_digest"],
            "migration_id": wire["model_lineage"]["migration_id"],
        },
    )
    return internal


def validate_runtime_state_semantics(runtime: Any, state: SharedPatientState) -> None:
    """Reject rehashed wires whose redundant control-plane state is inconsistent.

    Cross-coupling activity and geometry membership are authoritative state
    fields, but their identities/topology are model-bound.  A caller may not
    edit them independently, recompute the integrity hash, and expect queries
    to silently ignore the edit.
    """

    internal = architecture_state_to_internal(runtime, state)
    def equivalent(left: Any, right: Any) -> bool:
        if isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
            return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            return set(left) == set(right) and all(equivalent(left[key], right[key]) for key in left)
        if isinstance(left, list) and isinstance(right, list):
            return len(left) == len(right) and all(equivalent(a, b) for a, b in zip(left, right))
        return left == right

    # Scope and model registries are model-bound control-plane data, not
    # caller-editable annotations.  A recomputed content hash alone is not
    # authority to silently change Omega or claim a different dynamics/factor
    # registry while retaining the same runtime model digest.
    expected_scope = _scope(runtime)
    if not equivalent(state.payload["scope"], expected_scope):
        raise ValueError("architecture scope is inconsistent with model-bound state")
    expected_lineage = _model_lineage(runtime, internal)
    if not equivalent(state.payload["model_lineage"], expected_lineage):
        raise ValueError("architecture model_lineage is inconsistent with model-bound state")

    factor_state = state.payload["factor_graph_state"]
    if factor_state["graph_digest"] != digest(_factor_graph_preimage(runtime)):
        raise ValueError("architecture factor_graph_state graph_digest is inconsistent")
    if factor_state["messages_digest"] != digest(factor_state["factor_messages"]):
        raise ValueError("architecture factor_graph_state messages_digest is inconsistent")
    recognized = sorted(
        {
            source
            for message in factor_state["factor_messages"]
            if not str(message["factor_id"]).startswith("DISPOSITION:UNMAPPED:")
            for source in message["source_result_ids"]
        }
    )
    if factor_state["recognized_result_ids"] != recognized:
        raise ValueError("architecture factor_graph_state recognized_result_ids are inconsistent")

    action_memory = state.payload["action_memory"]
    if action_memory["history_digest"] != digest(action_memory["instances"]):
        raise ValueError("architecture action_memory history_digest is inconsistent")
    expected_action_memory = _action_memory(runtime, internal)
    if not equivalent(action_memory, expected_action_memory):
        raise ValueError("architecture action_memory is internally inconsistent")
    history = state.payload["history_summary"]
    history_body = {
        "trajectory_features": history["trajectory_features"],
        "mode_transitions": history["mode_transitions"],
        "action_response_windows": history["action_response_windows"],
        "retained_event_ids": history["retained_event_ids"],
    }
    if history["summary_digest"] != digest(history_body):
        raise ValueError("architecture history_summary summary_digest is inconsistent")
    if history["retained_event_ids"] != state.payload["event_lineage"]["processed_event_ids"]:
        raise ValueError("architecture retained_event_ids are inconsistent with event lineage")

    # Redundant posterior/local summaries must describe one probability state.
    # Queries are forbidden from reading mutually inconsistent views (for
    # example diagnosis reading a caller-edited marginal while forecast
    # silently re-derives another marginal from the joint posterior).
    messages = copy.deepcopy(factor_state["factor_messages"])
    internal_joint = internal["joint_hypotheses"]
    expected_configuration_ids = {
        row["configuration_id"] for row in runtime._enumerate_prior()
    }
    actual_configuration_ids = [
        row["configuration_id"] for row in internal_joint
    ]
    if (
        len(actual_configuration_ids) != len(set(actual_configuration_ids))
        or set(actual_configuration_ids) != expected_configuration_ids
    ):
        raise ValueError(
            "architecture joint posterior does not cover the declared factorial configurations"
        )
    joint_probabilities = [float(row["probability"]) for row in internal_joint]
    if (
        any(
            not math.isfinite(value) or value < 0.0 or value > 1.0
            for value in joint_probabilities
        )
        or not math.isclose(
            sum(joint_probabilities), 1.0, rel_tol=0.0, abs_tol=1e-12
        )
    ):
        raise ValueError("architecture joint posterior is not normalized")
    # Static factorial models admit the stronger prior-plus-factor replay.
    # Models with entry/withdrawal dynamics do not: after a clock transition
    # the frozen wire is the authoritative current belief and intentionally
    # does not contain the full path of coordinate/mode/action contexts needed
    # to reconstruct a path-dependent transition from time zero.  For those
    # models the validator still closes every redundant *current-state* view
    # below (joint -> marginals, local summaries, epistemic and geometry), but
    # must not misclassify legitimate time evolution as forged evidence.
    if (
        state.payload["model_lineage"].get("migration_id") is None
        and not runtime._activation_dynamics_enabled()
    ):
        replayed_joint = _replay_factorial_joint(runtime, messages)
        replayed_by_id = {
            row["configuration_id"]: row for row in replayed_joint
        }
        internal_by_id = {
            row["configuration_id"]: row for row in internal["joint_hypotheses"]
        }
        if not equivalent(internal_by_id, replayed_by_id):
            raise ValueError(
                "architecture joint posterior is inconsistent with model prior and factor messages"
            )
    expected_active = _active_process_posterior(runtime, internal, messages)
    if not equivalent(state.payload["active_process_posterior"], expected_active):
        raise ValueError("architecture active_process_posterior is internally inconsistent")
    for local in state.payload["local_states"]:
        mode_probabilities = [float(row["probability"]) for row in local["mode_posterior"]]
        if any(value < 0.0 or value > 1.0 for value in mode_probabilities) or not math.isclose(
            sum(mode_probabilities), 1.0, rel_tol=0.0, abs_tol=1e-12
        ):
            raise ValueError("architecture local mode posterior is not normalized")
    expected_local = _local_states(runtime, internal, messages)
    if not equivalent(state.payload["local_states"], expected_local):
        raise ValueError("architecture local_states are internally inconsistent")

    # Epistemic and identifiability outputs are derived from the public state
    # plus the frozen model.  In particular, a wire edit must never upgrade an
    # UNIDENTIFIABLE action into an authorized identified intervention.
    runtime._derive_epistemic(internal)
    expected_epistemic = _epistemic(runtime, internal)
    if not equivalent(state.payload["epistemic_residual"], expected_epistemic):
        raise ValueError("architecture epistemic_residual is internally inconsistent")
    expected_identifiability = _identifiability(runtime, internal)
    if not equivalent(state.payload["identifiability_claims"], expected_identifiability):
        raise ValueError("architecture identifiability_claims are inconsistent with model-bound state")

    expected_cross = _cross_couplings(runtime, internal)
    if not equivalent(state.payload["cross_couplings"], expected_cross):
        raise ValueError("architecture cross_couplings are inconsistent with model-bound state")
    expected_geometry = _geometry(runtime, internal, _scope(runtime))
    if not equivalent(state.payload["geometry_state"], expected_geometry):
        raise ValueError("architecture geometry_state is inconsistent with model-bound state")

    # Bind each factor to a public processed event using only canonical bytes.
    # Event-content authentication is deliberately left to the update ledger
    # proof; pure queries must remain executable from SharedPatientState bytes
    # alone because the frozen wire has no source-result -> event payload map.
    seen_members: set[tuple[str, str]] = set()
    for message in factor_state["factor_messages"]:
        source_ids = [str(source) for source in message["source_result_ids"]]
        if not source_ids or any(not source for source in source_ids):
            raise ValueError("architecture factor source_result_ids must be nonempty")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("architecture factor source_result_ids must be unique")
        provenance = _factor_message_provenance(message)
        bindings = provenance["bindings"]
        binding_sources = sorted({str(row["source_result_id"]) for row in bindings})
        if sorted(source_ids) != binding_sources:
            raise ValueError(
                "architecture factor source_result_ids do not match content-bound members"
            )
        for binding in bindings:
            if binding["event_id"] not in state.payload["event_lineage"]["processed_event_ids"]:
                raise ValueError(
                    "architecture factor source provenance is inconsistent with processed event lineage"
                )
            member_key = (
                str(binding["source_result_id"]),
                str(binding["concept_id"]),
            )
            if member_key in seen_members:
                raise ValueError(
                    "architecture factor source/member is duplicated instead of exact-once"
                )
            seen_members.add(member_key)
        if message["factor_type"] == "common_cause":
            declared = runtime.common_cause_factors.get(str(message["factor_id"]))
            if declared is None:
                raise ValueError("architecture common_cause factor is not model-declared")
            if {str(row["concept_id"]) for row in bindings} != set(
                declared["member_concept_ids"]
            ):
                raise ValueError("architecture common_cause factor member set is incomplete")
            instance_ids = {
                str(row.get("common_cause_instance_id") or "") for row in bindings
            }
            if len(instance_ids) != 1 or not next(iter(instance_ids)):
                raise ValueError("architecture common_cause instance binding is inconsistent")
            if declared["binding_mode"] == "SAME_SOURCE_RESULT" and len(source_ids) != 1:
                raise ValueError("architecture SAME_SOURCE_RESULT factor has multiple sources")
            if declared["binding_mode"] == "SHARED_LATENT_INSTANCE" and len(source_ids) < 2:
                raise ValueError("architecture SHARED_LATENT_INSTANCE factor lacks distinct sources")
            instance_terms = [
                str(key)[len("common_cause:instance=") :]
                for key in message["log_likelihood_by_hypothesis"]
                if str(key).startswith("common_cause:instance=")
            ]
            if instance_terms != [next(iter(instance_ids))]:
                raise ValueError("architecture common_cause instance term is inconsistent")
        elif len(bindings) != 1:
            raise ValueError("non-common factor cannot carry multiple member bindings")


__all__ = [
    "UNKNOWN_PROCESS_ID",
    "architecture_state_to_internal",
    "internal_to_architecture_state",
    "model_time_from_as_of",
    "validate_runtime_state_semantics",
]
