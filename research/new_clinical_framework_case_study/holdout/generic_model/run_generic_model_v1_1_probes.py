"""Case-blind executable probes for generic-model/1.1.0.

These probes use only synthetic contract events over the frozen generic
observation/action catalog.  They do not read a real or holdout case.  Rerun
this script only against the exact runtime tree that will be sealed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


HERE = Path(__file__).resolve().parent
CASE_STUDY = HERE.parents[1]
PACK = HERE / "model_pack.json"
EVIDENCE = HERE.parent / "evidence" / "GENERIC_MODEL_V1_1_RUNTIME_PROBES.json"
UNMODELED = "NCF_UNMODELED_PROCESS"
TOL = 1e-12

import sys

sys.path.insert(0, str(CASE_STUDY))
from runtime_v2 import PublicEvent, RuntimeV2, log_likelihood


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def observation(
    concept_id: str,
    value: Any,
    *,
    event_id: str,
    reliability: float = 1.0,
    rankable: bool = True,
    disposition: str | None = None,
) -> PublicEvent:
    row: dict[str, Any] = {
        "event_id": event_id,
        "event_type": "ObservationAvailable",
        "available_at": 0.0,
        "recorded_at": 0.0,
        "occurred_time": {"lower": 0.0, "upper": 0.0},
        "sample_time": {"lower": 0.0, "upper": 0.0},
        "result_at": 0.0,
        "provenance": {"source_result_id": f"source:{event_id}"},
        "concept_id": concept_id,
        "value": value,
        "reliability": reliability,
        "rankable": rankable,
    }
    if disposition is not None:
        row["mapper_disposition_reason"] = disposition
    return PublicEvent.from_dict(row)


def planned(action_id: str, *, event_id: str) -> PublicEvent:
    return PublicEvent.from_dict(
        {
            "event_id": event_id,
            "event_type": "PlannedAction",
            "available_at": 0.0,
            "recorded_at": 0.0,
            "occurred_time": {"lower": 0.0, "upper": 0.0},
            "provenance": {"source_result_id": f"source:{event_id}"},
            "action_id": action_id,
        }
    )


def internal_marginals(rows: Sequence[Mapping[str, Any]], process_ids: Sequence[str]) -> dict[str, float]:
    return {
        pid: math.fsum(
            float(row["probability"])
            for row in rows
            if pid in row["active_processes"]
        )
        for pid in process_ids
    }


def architecture_marginals(state: Any) -> dict[str, float]:
    return {
        row["process_id"]: float(row["p_active"])
        for row in state.to_dict()["active_process_posterior"]["process_marginals"]
        if row["process_id"] != UNMODELED
    }


def architecture_joint(state: Any) -> list[dict[str, Any]]:
    return state.to_dict()["active_process_posterior"]["joint_hypotheses"]


def architecture_local(state: Any) -> dict[str, Any]:
    return {
        row["process_id"]: {
            "coordinates": {
                coordinate["coordinate_id"]: {
                    "mean": float(coordinate["distribution"]["mean"]),
                    "uncertainty": float(coordinate["distribution"]["sd"]),
                }
                for coordinate in row["coordinates"]
            },
            "modes": {
                mode["mode_id"]: float(mode["probability"])
                for mode in row["mode_posterior"]
            },
        }
        for row in state.to_dict()["local_states"]
    }


def pair_mass(rows: Sequence[Mapping[str, Any]], first: str, second: str) -> float:
    return math.fsum(
        float(row["probability"])
        for row in rows
        if first in row["active_processes"] and second in row["active_processes"]
    )


def maximum_abs_difference(left: Mapping[str, float], right: Mapping[str, float]) -> float:
    return max(abs(float(left[key]) - float(right[key])) for key in left)


def deep_rename(value: Any, rename: Mapping[str, str]) -> Any:
    if isinstance(value, dict):
        return {
            deep_rename(key, rename): deep_rename(child, rename)
            for key, child in value.items()
        }
    if isinstance(value, list):
        return [deep_rename(child, rename) for child in value]
    if isinstance(value, str):
        result = value
        for old in sorted(rename, key=len, reverse=True):
            result = result.replace(old, rename[old])
        return result
    return value


def run() -> dict[str, Any]:
    spec = json.loads(PACK.read_text(encoding="utf-8"))
    runtime = RuntimeV2(spec)
    process_ids = runtime.process_ids
    probes: list[dict[str, Any]] = []

    def record(probe_id: str, passed: bool, evidence: Any) -> None:
        probes.append(
            {
                "probe_id": probe_id,
                "status": "PASS" if passed else "FAIL",
                "evidence": evidence,
            }
        )

    # D01: the process activation table really moves without new evidence.
    empty = runtime.initialize([], cut=0)
    natural = runtime.forecast(empty, horizon=1)
    before = architecture_marginals(empty)
    after = internal_marginals(natural["final_joint_hypotheses"], process_ids)
    max_delta = max(abs(after[pid] - before[pid]) for pid in process_ids)
    record(
        "GM11-DYNAMIC-ACTIVATION-NATURAL",
        max_delta > 1e-8 and bool(natural["process_activation_trace"]),
        {
            "max_process_marginal_delta": max_delta,
            "trace_rows": len(natural["process_activation_trace"]),
        },
    )

    # A declared source process must change target entry relative to an exact
    # ablation of only that activation coupling.
    tox_event = observation(
        "confirmed_toxic_exposure_presence", True, event_id="tox-confirmed"
    )
    coupled_state = runtime.initialize([tox_event], cut=0)
    coupled_forecast = runtime.forecast(coupled_state, horizon=2)
    ablated_spec = copy.deepcopy(spec)
    ablated_spec["process_activation_couplings"] = [
        row
        for row in ablated_spec["process_activation_couplings"]
        if not (
            row["source_process_id"] == "P_TOXICOLOGIC_DRIVER"
            and row["target_process_id"] == "P_ARRHYTHMIA"
        )
    ]
    ablated_runtime = RuntimeV2(ablated_spec)
    ablated_state = ablated_runtime.initialize([tox_event], cut=0)
    ablated_forecast = ablated_runtime.forecast(ablated_state, horizon=2)
    coupled_marginal = internal_marginals(
        coupled_forecast["final_joint_hypotheses"], process_ids
    )["P_ARRHYTHMIA"]
    ablated_marginal = internal_marginals(
        ablated_forecast["final_joint_hypotheses"], process_ids
    )["P_ARRHYTHMIA"]
    coupled_pair = pair_mass(
        coupled_forecast["final_joint_hypotheses"],
        "P_TOXICOLOGIC_DRIVER",
        "P_ARRHYTHMIA",
    )
    ablated_pair = pair_mass(
        ablated_forecast["final_joint_hypotheses"],
        "P_TOXICOLOGIC_DRIVER",
        "P_ARRHYTHMIA",
    )
    record(
        "GM11-ACTIVATION-COUPLING-ABLATION",
        coupled_marginal > ablated_marginal + 1e-8
        and coupled_pair > ablated_pair + 1e-8,
        {
            "target_marginal_with_coupling": coupled_marginal,
            "target_marginal_without_coupling": ablated_marginal,
            "joint_pair_mass_with_coupling": coupled_pair,
            "joint_pair_mass_without_coupling": ablated_pair,
        },
    )

    # A cause/process-removing action may alter persistence, but the rollout
    # remains causally UNIDENTIFIABLE.
    no_new = runtime.forecast(coupled_state, horizon=2)
    source_control = runtime.rollout(
        coupled_state,
        {
            "policy_id": "START_TOX_SOURCE_CONTROL",
            "start_actions": [
                {"action_id": "ACTION_TOXICOLOGIC_SOURCE_CONTROL", "dose": 1.0}
            ],
        },
        horizon=2,
    )
    no_new_tox = internal_marginals(no_new["final_joint_hypotheses"], process_ids)[
        "P_TOXICOLOGIC_DRIVER"
    ]
    treated_tox = internal_marginals(
        source_control["final_joint_hypotheses"], process_ids
    )["P_TOXICOLOGIC_DRIVER"]
    record(
        "GM11-RESOLVING-ACTION-ACTIVATION-EFFECT",
        treated_tox < no_new_tox - 1e-8
        and source_control["status"] == "UNIDENTIFIABLE",
        {
            "no_new_action_toxicologic_marginal": no_new_tox,
            "source_control_toxicologic_marginal": treated_tox,
            "rollout_status": source_control["status"],
        },
    )

    # A record-only plan must not create exposure or alter dynamics.
    planned_state = runtime.update(
        coupled_state,
        [planned("ACTION_TOXICOLOGIC_SOURCE_CONTROL", event_id="tox-plan")],
        advance_to=0,
    )
    planned_forecast = runtime.forecast(planned_state, horizon=1)
    baseline_forecast = runtime.forecast(coupled_state, horizon=1)
    planned_instances = planned_state.to_dict()["action_memory"]["instances"]
    record(
        "GM11-PLANNED-ACTION-RECORD-ONLY",
        planned_forecast["final_joint_hypotheses"]
        == baseline_forecast["final_joint_hypotheses"]
        and planned_forecast["final_coordinates"]
        == baseline_forecast["final_coordinates"]
        and all(row["status"] == "planned" for row in planned_instances),
        {
            "planned_instances": planned_instances,
            "joint_equal": planned_forecast["final_joint_hypotheses"]
            == baseline_forecast["final_joint_hypotheses"],
            "coordinates_equal": planned_forecast["final_coordinates"]
            == baseline_forecast["final_coordinates"],
        },
    )

    # Factual no-event advancement and no-new-action forecast are the same
    # declared dynamics from the same canonical state.
    factual = runtime.update(coupled_state, [], advance_to=1)
    factual_marginals = architecture_marginals(factual)
    forecast_marginals = internal_marginals(
        baseline_forecast["final_joint_hypotheses"], process_ids
    )
    local_factual = architecture_local(factual)
    local_forecast = {
        pid: {
            "coordinates": baseline_forecast["final_coordinates"][pid],
            "modes": baseline_forecast["final_mode_posteriors"][pid],
        }
        for pid in process_ids
    }
    record(
        "GM11-FACTUAL-ADVANCE-EQUALS-NO-NEW-FORECAST",
        maximum_abs_difference(factual_marginals, forecast_marginals) <= TOL
        and local_factual == local_forecast,
        {
            "max_activation_marginal_abs_diff": maximum_abs_difference(
                factual_marginals, forecast_marginals
            ),
            "local_state_exact_equal": local_factual == local_forecast,
        },
    )

    # The single common-source factor must match a manual one-factor Bayes
    # update, not a product of per-process LLRs.
    common_event = observation(
        "persistent_hypotension_presence", True, event_id="common-hypotension"
    )
    common_observation = runtime.observations["persistent_hypotension_presence"]
    target_ids = {
        row["process_id"] for row in common_observation["emissions"]
    }
    base_joint = architecture_joint(empty)
    table = common_observation["joint_likelihoods"]
    reference_logp = log_likelihood(common_observation["reference_likelihood"], True)
    unknown_llr = (
        log_likelihood(common_observation["unknown_likelihood"], True)
        - reference_logp
    )
    manual_logs: dict[str, float] = {}
    for row in base_joint:
        active = set(row["active_process_ids"])
        unknown = UNMODELED in active
        known = active - {UNMODELED}
        key = ",".join(sorted(known.intersection(target_ids))) or "-"
        manual_logs[row["hypothesis_id"]] = (
            math.log(float(row["probability"]))
            + log_likelihood(table[key], True)
            + (unknown_llr if unknown else 0.0)
        )
    maximum_log = max(manual_logs.values())
    normalizer = math.fsum(
        math.exp(value - maximum_log) for value in manual_logs.values()
    )
    manual = {
        key: math.exp(value - maximum_log) / normalizer
        for key, value in manual_logs.items()
    }
    common_state = runtime.update(empty, [common_event], advance_to=0)
    actual = {
        row["hypothesis_id"]: float(row["probability"])
        for row in architecture_joint(common_state)
    }
    common_diff = max(abs(actual[key] - manual[key]) for key in actual)
    record(
        "GM11-COMMON-SOURCE-SINGLE-FACTOR-RUNTIME",
        common_diff <= TOL,
        {
            "target_process_count": len(target_ids),
            "max_joint_probability_abs_diff_from_manual_one_factor_update": common_diff,
        },
    )

    # Reliability must scale evidence, while non-rankable support-masked input
    # must leave the posterior unchanged and create a canonical residual.
    prior_tox = architecture_marginals(empty)["P_TOXICOLOGIC_DRIVER"]
    reliable = runtime.initialize(
        [
            observation(
                "confirmed_toxic_exposure_presence",
                True,
                event_id="tox-reliable",
                reliability=1.0,
            )
        ],
        cut=0,
    )
    low_reliability = runtime.initialize(
        [
            observation(
                "confirmed_toxic_exposure_presence",
                True,
                event_id="tox-low-reliability",
                reliability=0.01,
            )
        ],
        cut=0,
    )
    reliable_tox = architecture_marginals(reliable)["P_TOXICOLOGIC_DRIVER"]
    low_tox = architecture_marginals(low_reliability)["P_TOXICOLOGIC_DRIVER"]
    record(
        "GM11-RELIABILITY-OPERATIVE",
        abs(reliable_tox - prior_tox) > abs(low_tox - prior_tox) + 1e-8,
        {
            "prior": prior_tox,
            "reliability_1": reliable_tox,
            "reliability_0_01": low_tox,
        },
    )

    withheld = runtime.initialize(
        [
            observation(
                "confirmed_toxic_exposure_presence",
                True,
                event_id="tox-support-masked",
                rankable=False,
                disposition="SUPPORT_MASKED",
            )
        ],
        cut=0,
    )
    withheld_marginals = architecture_marginals(withheld)
    withheld_payload = withheld.to_dict()
    withheld_trace = withheld_payload["factor_graph_state"]["factor_messages"]
    unexplained = withheld_payload["epistemic_residual"]["unexplained_observations"]
    disposition_only = (
        len(withheld_trace) == 1
        and withheld_trace[0]["variable_ids"]
        == ["DISPOSITION:record_only_nonrankable"]
        and float(withheld_trace[0]["reliability"]) == 0.0
        and all(
            not str(key).startswith("process:")
            and not str(key).startswith("joint:known=")
            for key in withheld_trace[0]["log_likelihood_by_hypothesis"]
        )
    )
    record(
        "GM11-SUPPORT-MASKED-FAIL-CLOSED",
        maximum_abs_difference(before, withheld_marginals) <= TOL
        and disposition_only
        and any(
            row["reason"] == "unknown_measurement_condition" for row in unexplained
        ),
        {
            "max_activation_marginal_abs_diff": maximum_abs_difference(
                before, withheld_marginals
            ),
            "factor_message_count": len(withheld_trace),
            "factor_messages": withheld_trace,
            "unexplained_observations": unexplained,
        },
    )

    # Directly attack the declared conditional-active entry/exit semantics with
    # a real process definition from this pack.
    pid = "P_TOXICOLOGIC_DRIVER"
    process = runtime.processes[pid]
    extreme_coordinates = {
        row["coordinate_id"]: {"mean": 0.95, "uncertainty": 0.05}
        for row in process["coordinates"]
    }
    extreme_modes = {
        row["mode_id"]: (1.0 if row["mode_id"] == "failed" else 0.0)
        for row in process["modes"]
    }
    partial_coordinates = copy.deepcopy(extreme_coordinates)
    partial_modes = copy.deepcopy(extreme_modes)
    partial_trace = runtime._apply_activation_local_semantics(
        pid,
        partial_coordinates,
        partial_modes,
        {
            "p_active_before": 0.8,
            "p_active_after": 0.6,
            "entered_probability_flux": 0.0,
            "withdrawn_probability_flux": 0.2,
        },
        step_width=1.0,
    )
    exit_coordinates = copy.deepcopy(extreme_coordinates)
    exit_modes = copy.deepcopy(extreme_modes)
    exit_trace = runtime._apply_activation_local_semantics(
        pid,
        exit_coordinates,
        exit_modes,
        {
            "p_active_before": 0.8,
            "p_active_after": 0.0,
            "entered_probability_flux": 0.0,
            "withdrawn_probability_flux": 0.8,
        },
        step_width=1.0,
    )
    entry_coordinates = copy.deepcopy(extreme_coordinates)
    entry_modes = copy.deepcopy(extreme_modes)
    entry_trace = runtime._apply_activation_local_semantics(
        pid,
        entry_coordinates,
        entry_modes,
        {
            "p_active_before": 0.0,
            "p_active_after": 0.2,
            "entered_probability_flux": 0.2,
            "withdrawn_probability_flux": 0.0,
        },
        step_width=1.0,
    )
    prior_coordinates = {
        row["coordinate_id"]: {
            "mean": float(row["prior_mean"]),
            "uncertainty": float(row["prior_uncertainty"]),
        }
        for row in process["coordinates"]
    }
    prior_modes = {
        row["mode_id"]: float(row["prior"])
        for row in process["modes"]
    }
    record(
        "GM11-CONDITIONAL-ACTIVE-ENTRY-EXIT",
        partial_coordinates == extreme_coordinates
        and partial_modes == extreme_modes
        and partial_trace["prior_blend_fraction"] == 0.0
        and exit_coordinates == prior_coordinates
        and exit_modes == prior_modes
        and exit_trace["prior_blend_fraction"] == 1.0
        and entry_coordinates == prior_coordinates
        and entry_modes == prior_modes
        and entry_trace["prior_blend_fraction"] == 1.0,
        {
            "partial_exit": partial_trace,
            "full_exit": exit_trace,
            "reentry": entry_trace,
        },
    )

    # Alpha-renaming every process ID must not change behavior after mapping
    # outputs back to original IDs.
    rename = {pid: f"R_{index:02d}" for index, pid in enumerate(process_ids)}
    renamed_spec = deep_rename(spec, rename)
    renamed_runtime = RuntimeV2(renamed_spec)
    renamed_empty = renamed_runtime.initialize([], cut=0)
    renamed_forecast = renamed_runtime.forecast(renamed_empty, horizon=1)
    reverse = {new: old for old, new in rename.items()}
    renamed_before = {
        reverse[pid]: value
        for pid, value in architecture_marginals(renamed_empty).items()
    }
    renamed_after = {
        reverse[pid]: value
        for pid, value in internal_marginals(
            renamed_forecast["final_joint_hypotheses"], renamed_runtime.process_ids
        ).items()
    }
    before_diff = maximum_abs_difference(before, renamed_before)
    after_diff = maximum_abs_difference(after, renamed_after)
    record(
        "GM11-PROCESS-ID-ALPHA-RENAME-INVARIANCE",
        before_diff <= TOL and after_diff <= TOL,
        {
            "initial_marginal_max_abs_diff": before_diff,
            "forecast_marginal_max_abs_diff": after_diff,
            "tolerance": TOL,
        },
    )

    # Every query must advertise the approximation instead of calling the
    # result a full-state joint.
    diagnosis = runtime.diagnose(empty)
    record(
        "GM11-FACTORIZATION-LIMITATION-EXPOSED",
        diagnosis["posterior_factorization"] == spec["posterior_factorization"]
        and diagnosis["inference_kind"]
        == "exact_factorial_activation_plus_conditional_active_mean_field_local_state"
        and "out_of_scope" in diagnosis["factorization_limitation"].lower()
        and "q(x,m|process active)" in diagnosis["factorization_limitation"],
        {
            "posterior_factorization": diagnosis["posterior_factorization"],
            "inference_kind": diagnosis["inference_kind"],
            "factorization_limitation": diagnosis["factorization_limitation"],
        },
    )

    passed = all(row["status"] == "PASS" for row in probes)
    return {
        "schema_version": "ncf.generic-model-runtime-probes.v1",
        "model_id": spec["model_id"],
        "model_version": spec["model_version"],
        "model_pack_sha256": sha256(PACK),
        "case_blind": True,
        "primary_holdout_inspected": False,
        "status": "PASS" if passed else "FAIL",
        "passed": sum(row["status"] == "PASS" for row in probes),
        "total": len(probes),
        "probes": probes,
    }


def main() -> int:
    report = run()
    EVIDENCE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
