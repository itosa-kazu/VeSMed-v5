"""Independent pre-freeze red-team gate for the bridge holdout.

This module deliberately imports neither bridge implementation nor the existing
reference/model executors.  It defines the *external runner report* that a later
holdout driver must measure and checks twelve essential mutants.  ``--self-test``
constructs one good externally-observed report, injects every known-bad mutant,
and proves that the corresponding HARD gate rejects it.

The report is not a candidate self-attestation.  In the real experiment its
static, runtime, and mutation observations must be populated by an external
isolated runner (see ``bridge_mutation_gate_v1.json``).
"""

from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import argparse
import json
from pathlib import Path
from typing import Any, Callable, Mapping


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "research_notes" / "bridge_mutation_gate_v1.json"
PUBLIC_PROTOCOL_PATH = ROOT / "research_notes" / "bridge_panel_protocol_v1.json"

MUTANT_IDS = (
    "M01_CANONICAL_ECHO",
    "M02_SHARED_EXECUTABLE_HELPER",
    "M03_FUTURE_IN_FILTER",
    "M04_NO_FUTURE_IN_SMOOTH",
    "M05_DO_AS_CONDITION",
    "M06_AAP_AS_POPULATION_DO",
    "M07_UNCERTAINTY_FLATTEN",
    "M08_RAW_ROOT_REWRITTEN",
    "M09_PATH_COUNT_AS_ROOT_COUNT",
    "M10_LATEST_VERSION_REWRITE",
    "M11_CACHE_AS_CLEAN_REBUILD",
    "M12_UNSUPPORTED_RELABEL",
)

TOLERANCE = 1e-12


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _close(left: float, right: float, tolerance: float = TOLERANCE) -> bool:
    return abs(float(left) - float(right)) <= tolerance


def _e02_oracle(protocol: Mapping[str, Any]) -> tuple[float, float]:
    model = protocol["models"]["E02"]
    p_s = Fraction(str(model["P_severe"]))
    p_tm_s = Fraction(str(model["P_treated_given_severe"]))
    p_tm_m = Fraction(str(model["P_treated_given_mild"]))
    bad = model["P_bad"]
    p_bad_s_t1 = Fraction(str(bad["severe_T1"]))
    p_bad_m_t1 = Fraction(str(bad["mild_T1"]))
    condition = (p_s * p_tm_s * p_bad_s_t1 + (1 - p_s) * p_tm_m * p_bad_m_t1) / (
        p_s * p_tm_s + (1 - p_s) * p_tm_m
    )
    intervene = p_s * p_bad_s_t1 + (1 - p_s) * p_bad_m_t1
    return float(condition), float(intervene)


def _hmm_oracle(y1: int | None) -> float:
    """P(X0=1 | Y0=0 [, Y1]) for the public red-team HMM probe."""

    prior = Fraction(1, 2)
    emission_accuracy = Fraction(4, 5)
    persistence = Fraction(9, 10)
    if y1 is None:
        numerator = prior * (1 - emission_accuracy)
        denominator = numerator + (1 - prior) * emission_accuracy
        return float(numerator / denominator)

    def future_likelihood(x0: int) -> Fraction:
        total = Fraction(0)
        for x1 in (0, 1):
            transition = persistence if x1 == x0 else 1 - persistence
            emission = emission_accuracy if y1 == x1 else 1 - emission_accuracy
            total += transition * emission
        return total

    w1 = prior * (1 - emission_accuracy) * future_likelihood(1)
    w0 = (1 - prior) * emission_accuracy * future_likelihood(0)
    return float(w1 / (w1 + w0))


def _baseline_report() -> dict[str, Any]:
    protocol = _load_json(PUBLIC_PROTOCOL_PATH)
    condition, intervene = _e02_oracle(protocol)
    return {
        "report_producer": "external_holdout_runner",
        "independence": {
            "impl_a": {
                "repo_imports": [],
                "repo_executable_dependency_hashes": ["sha256:impl-a-only"],
                "process_root": "isolated-a",
            },
            "impl_b": {
                "repo_imports": [],
                "repo_executable_dependency_hashes": ["sha256:impl-b-only"],
                "process_root": "isolated-b",
            },
            "shared_data_hashes": ["sha256:frozen-protocol-only"],
        },
        "native_ir": {
            "portable_source_removed_before_execution": True,
            "opaque_portable_payload_paths": [],
            "native_semantic_mutation_changed_result": True,
            "decode_used_native_addresses": True,
        },
        "dynamic": {
            "filter_before_future_visible": _hmm_oracle(None),
            "filter_after_future_visible": _hmm_oracle(None),
            "smooth_before_future_visible": _hmm_oracle(None),
            "smooth_after_y1_1": _hmm_oracle(1),
            "smooth_after_y1_0": _hmm_oracle(0),
            "filter_roots_after_future_visible": [["root-y0", "v1"]],
            "smooth_roots_after_future_visible": [["root-y0", "v1"], ["root-y1", "v1"]],
        },
        "causal": {
            "condition_bad_t1": condition,
            "population_do_bad_t1": intervene,
            "public_e03_aap": 1.0,
            "public_e03_population_do": 0.5,
            "ambiguous_abduction_posterior_u1": 0.8,
            "ambiguous_aap_pmf": [[0, 0.2], [1, 0.8]],
            "ambiguous_population_do_pmf": [[0, 0.5], [1, 0.5]],
            "condition_patient_roots": [["root-treatment", "v1"]],
            "population_do_patient_roots": [],
            "aap_patient_roots": [["root-treatment", "v1"], ["root-outcome", "v1"]],
        },
        "uncertainty": {
            "same_mean_distribution_a": [[-1, 0.5], [1, 0.5]],
            "same_mean_distribution_b": [[0, 1.0]],
            "measurement_value_kinds": [
                "exact",
                "interval",
                "below_detection",
                "masked",
                "missing",
                "conflicting",
            ],
            "outcome_axes": [
                "coverage",
                "identification",
                "numerics",
                "replay",
                "safety",
            ],
            "flattened_confidence_present": False,
        },
        "provenance": {
            "authoritative_raw_roots": [["root-r1", "v1"]],
            "decoded_roots": [["root-r1", "v1"]],
            "actually_consumed_roots": [["root-r1", "v1"]],
            "synthetic_bridge_ids_in_roots": [],
            "fanout_root_union": [["root-r1", "v1"]],
            "two_repeat_root_union": [["root-r1", "v1"], ["root-r2", "v1"]],
        },
        "versions": {
            "requested": {
                "root": "v1",
                "artifact": "a1",
                "mapping": "map-v1",
                "bridge": "bridge-v1",
                "knowledge": "knowledge-v1",
                "model": "model-v1",
                "solver": "solver-v1",
            },
            "compiled": {
                "root": "v1",
                "artifact": "a1",
                "mapping": "map-v1",
                "bridge": "bridge-v1",
                "knowledge": "knowledge-v1",
                "model": "model-v1",
                "solver": "solver-v1",
            },
            "executed": {
                "root": "v1",
                "artifact": "a1",
                "mapping": "map-v1",
                "bridge": "bridge-v1",
                "knowledge": "knowledge-v1",
                "model": "model-v1",
                "solver": "solver-v1",
            },
            "decoded": {
                "root": "v1",
                "artifact": "a1",
                "mapping": "map-v1",
                "bridge": "bridge-v1",
                "knowledge": "knowledge-v1",
                "model": "model-v1",
                "solver": "solver-v1",
            },
            "behavior_fingerprint": "fingerprint:model-v1",
            "expected_behavior_fingerprint": "fingerprint:model-v1",
            "old_and_new_coexist": True,
        },
        "rebuild": {
            "incremental_digest": "sha256:new-active-result",
            "clean_fresh_process_digest": "sha256:new-active-result",
            "hot_cache_poison_digest": "sha256:poison",
            "old_cut_digest_before_delta": "sha256:old-result",
            "old_cut_digest_after_delta": "sha256:old-result",
            "fresh_process": True,
            "active_roots_incremental": [["root-r1", "v2"]],
            "active_roots_clean": [["root-r1", "v2"]],
        },
        "capability": {
            "dbn_aap_status": "unsupported",
            "dbn_aap_capability_origin": "unsupported",
            "dbn_aap_native_witness": None,
            "scm_aap_status": "ok",
            "scm_aap_capability_origin": "native_scm",
            "scm_aap_native_witness": {"steps": ["abduction", "action", "prediction"]},
        },
    }


def _gate_m01(report: Mapping[str, Any]) -> bool:
    native = report["native_ir"]
    return (
        native["portable_source_removed_before_execution"] is True
        and native["opaque_portable_payload_paths"] == []
        and native["native_semantic_mutation_changed_result"] is True
        and native["decode_used_native_addresses"] is True
    )


def _gate_m02(report: Mapping[str, Any]) -> bool:
    independence = report["independence"]
    a, b = independence["impl_a"], independence["impl_b"]
    forbidden = {
        "prototype.reference_models",
        "prototype.model_subkernel",
        "other bridge implementation",
    }
    imports_a, imports_b = set(a["repo_imports"]), set(b["repo_imports"])
    hashes_a = set(a["repo_executable_dependency_hashes"])
    hashes_b = set(b["repo_executable_dependency_hashes"])
    return (
        report["report_producer"] == "external_holdout_runner"
        and not (imports_a | imports_b) & forbidden
        and not hashes_a & hashes_b
        and a["process_root"] != b["process_root"]
    )


def _gate_m03(report: Mapping[str, Any]) -> bool:
    dynamic = report["dynamic"]
    expected = _hmm_oracle(None)
    return _close(dynamic["filter_before_future_visible"], expected) and _close(
        dynamic["filter_after_future_visible"], expected
    ) and dynamic["filter_roots_after_future_visible"] == [["root-y0", "v1"]]


def _gate_m04(report: Mapping[str, Any]) -> bool:
    dynamic = report["dynamic"]
    return (
        _close(dynamic["smooth_before_future_visible"], _hmm_oracle(None))
        and _close(dynamic["smooth_after_y1_1"], _hmm_oracle(1))
        and _close(dynamic["smooth_after_y1_0"], _hmm_oracle(0))
        and not _close(dynamic["smooth_after_y1_1"], dynamic["filter_after_future_visible"])
        and dynamic["smooth_roots_after_future_visible"]
        == [["root-y0", "v1"], ["root-y1", "v1"]]
    )


def _gate_m05(report: Mapping[str, Any]) -> bool:
    protocol = _load_json(PUBLIC_PROTOCOL_PATH)
    condition, intervene = _e02_oracle(protocol)
    causal = report["causal"]
    return (
        _close(causal["condition_bad_t1"], condition)
        and _close(causal["population_do_bad_t1"], intervene)
        and not _close(condition, intervene)
        and causal["condition_patient_roots"] == [["root-treatment", "v1"]]
        and causal["population_do_patient_roots"] == []
    )


def _gate_m06(report: Mapping[str, Any]) -> bool:
    causal = report["causal"]
    return (
        _close(causal["public_e03_aap"], 1.0)
        and _close(causal["public_e03_population_do"], 0.5)
        and _close(causal["ambiguous_abduction_posterior_u1"], 0.8)
        and causal["ambiguous_aap_pmf"] == [[0, 0.2], [1, 0.8]]
        and causal["ambiguous_population_do_pmf"] == [[0, 0.5], [1, 0.5]]
        and causal["aap_patient_roots"]
        == [["root-treatment", "v1"], ["root-outcome", "v1"]]
    )


def _gate_m07(report: Mapping[str, Any]) -> bool:
    uncertainty = report["uncertainty"]
    required_kinds = {
        "exact",
        "interval",
        "below_detection",
        "masked",
        "missing",
        "conflicting",
    }
    required_axes = {"coverage", "identification", "numerics", "replay", "safety"}
    return (
        uncertainty["same_mean_distribution_a"] == [[-1, 0.5], [1, 0.5]]
        and uncertainty["same_mean_distribution_b"] == [[0, 1.0]]
        and uncertainty["same_mean_distribution_a"] != uncertainty["same_mean_distribution_b"]
        and set(uncertainty["measurement_value_kinds"]) == required_kinds
        and set(uncertainty["outcome_axes"]) == required_axes
        and uncertainty["flattened_confidence_present"] is False
    )


def _gate_m08(report: Mapping[str, Any]) -> bool:
    provenance = report["provenance"]
    return (
        provenance["decoded_roots"] == provenance["authoritative_raw_roots"]
        and provenance["actually_consumed_roots"] == provenance["authoritative_raw_roots"]
        and provenance["synthetic_bridge_ids_in_roots"] == []
    )


def _gate_m09(report: Mapping[str, Any]) -> bool:
    provenance = report["provenance"]
    return (
        provenance["fanout_root_union"] == [["root-r1", "v1"]]
        and provenance["two_repeat_root_union"]
        == [["root-r1", "v1"], ["root-r2", "v1"]]
    )


def _gate_m10(report: Mapping[str, Any]) -> bool:
    versions = report["versions"]
    return (
        versions["requested"]
        == versions["compiled"]
        == versions["executed"]
        == versions["decoded"]
        and versions["behavior_fingerprint"] == versions["expected_behavior_fingerprint"]
        and versions["old_and_new_coexist"] is True
    )


def _gate_m11(report: Mapping[str, Any]) -> bool:
    rebuild = report["rebuild"]
    return (
        rebuild["fresh_process"] is True
        and rebuild["incremental_digest"] == rebuild["clean_fresh_process_digest"]
        and rebuild["clean_fresh_process_digest"] != rebuild["hot_cache_poison_digest"]
        and rebuild["old_cut_digest_before_delta"] == rebuild["old_cut_digest_after_delta"]
        and rebuild["active_roots_incremental"] == rebuild["active_roots_clean"]
    )


def _gate_m12(report: Mapping[str, Any]) -> bool:
    capability = report["capability"]
    dbn_honest = (
        capability["dbn_aap_status"] == "unsupported"
        and capability["dbn_aap_capability_origin"] == "unsupported"
        and capability["dbn_aap_native_witness"] is None
    )
    scm_honest = (
        capability["scm_aap_status"] == "ok"
        and capability["scm_aap_capability_origin"] == "native_scm"
        and capability["scm_aap_native_witness"]
        == {"steps": ["abduction", "action", "prediction"]}
    )
    return dbn_honest and scm_honest


GATES: dict[str, Callable[[Mapping[str, Any]], bool]] = {
    "M01_CANONICAL_ECHO": _gate_m01,
    "M02_SHARED_EXECUTABLE_HELPER": _gate_m02,
    "M03_FUTURE_IN_FILTER": _gate_m03,
    "M04_NO_FUTURE_IN_SMOOTH": _gate_m04,
    "M05_DO_AS_CONDITION": _gate_m05,
    "M06_AAP_AS_POPULATION_DO": _gate_m06,
    "M07_UNCERTAINTY_FLATTEN": _gate_m07,
    "M08_RAW_ROOT_REWRITTEN": _gate_m08,
    "M09_PATH_COUNT_AS_ROOT_COUNT": _gate_m09,
    "M10_LATEST_VERSION_REWRITE": _gate_m10,
    "M11_CACHE_AS_CLEAN_REBUILD": _gate_m11,
    "M12_UNSUPPORTED_RELABEL": _gate_m12,
}


def evaluate_report(report: Mapping[str, Any]) -> dict[str, Any]:
    results: dict[str, bool] = {}
    errors: dict[str, str] = {}
    for mutant_id in MUTANT_IDS:
        try:
            results[mutant_id] = bool(GATES[mutant_id](report))
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            results[mutant_id] = False
            errors[mutant_id] = f"{type(exc).__name__}: {exc}"
    failed = [mutant_id for mutant_id, passed in results.items() if not passed]
    return {
        "gate_version": "bridge-mutation-gate-v1",
        "passed": not failed,
        "essential_mutants": len(MUTANT_IDS),
        "killed_or_rejected": len(MUTANT_IDS) - len(failed),
        "failed_gates": failed,
        "gate_results": results,
        "errors": errors,
    }


def apply_known_bad_mutant(report: Mapping[str, Any], mutant_id: str) -> dict[str, Any]:
    out = deepcopy(report)
    if mutant_id == "M01_CANONICAL_ECHO":
        out["native_ir"]["opaque_portable_payload_paths"] = ["/native_ir/canonical_envelope"]
        out["native_ir"]["decode_used_native_addresses"] = False
    elif mutant_id == "M02_SHARED_EXECUTABLE_HELPER":
        out["independence"]["impl_a"]["repo_executable_dependency_hashes"] = ["sha256:shared-helper"]
        out["independence"]["impl_b"]["repo_executable_dependency_hashes"] = ["sha256:shared-helper"]
    elif mutant_id == "M03_FUTURE_IN_FILTER":
        out["dynamic"]["filter_after_future_visible"] = _hmm_oracle(1)
        out["dynamic"]["filter_roots_after_future_visible"] = [
            ["root-y0", "v1"],
            ["root-y1", "v1"],
        ]
    elif mutant_id == "M04_NO_FUTURE_IN_SMOOTH":
        out["dynamic"]["smooth_after_y1_1"] = _hmm_oracle(None)
        out["dynamic"]["smooth_after_y1_0"] = _hmm_oracle(None)
        out["dynamic"]["smooth_roots_after_future_visible"] = [["root-y0", "v1"]]
    elif mutant_id == "M05_DO_AS_CONDITION":
        out["causal"]["population_do_bad_t1"] = out["causal"]["condition_bad_t1"]
        out["causal"]["population_do_patient_roots"] = [["root-treatment", "v1"]]
    elif mutant_id == "M06_AAP_AS_POPULATION_DO":
        out["causal"]["public_e03_aap"] = out["causal"]["public_e03_population_do"]
        out["causal"]["ambiguous_aap_pmf"] = deepcopy(out["causal"]["ambiguous_population_do_pmf"])
    elif mutant_id == "M07_UNCERTAINTY_FLATTEN":
        out["uncertainty"]["same_mean_distribution_a"] = 0.0
        out["uncertainty"]["same_mean_distribution_b"] = 0.0
        out["uncertainty"]["flattened_confidence_present"] = True
    elif mutant_id == "M08_RAW_ROOT_REWRITTEN":
        out["provenance"]["decoded_roots"] = [["bridge:synthetic", "v1"]]
        out["provenance"]["actually_consumed_roots"] = [["bridge:synthetic", "v1"]]
        out["provenance"]["synthetic_bridge_ids_in_roots"] = ["bridge:synthetic"]
    elif mutant_id == "M09_PATH_COUNT_AS_ROOT_COUNT":
        out["provenance"]["fanout_root_union"] = [
            ["root-r1:path-a", "v1"],
            ["root-r1:path-b", "v1"],
        ]
    elif mutant_id == "M10_LATEST_VERSION_REWRITE":
        out["versions"]["executed"]["model"] = "model-v2"
        out["versions"]["behavior_fingerprint"] = "fingerprint:model-v2"
    elif mutant_id == "M11_CACHE_AS_CLEAN_REBUILD":
        out["rebuild"]["clean_fresh_process_digest"] = out["rebuild"]["hot_cache_poison_digest"]
        out["rebuild"]["fresh_process"] = False
    elif mutant_id == "M12_UNSUPPORTED_RELABEL":
        out["capability"]["dbn_aap_status"] = "ok"
        out["capability"]["dbn_aap_capability_origin"] = "native_dbn"
        out["capability"]["dbn_aap_native_witness"] = {"steps": ["forecast"]}
    else:
        raise KeyError(f"unknown mutant_id: {mutant_id}")
    return out


def self_test() -> dict[str, Any]:
    spec = _load_json(SPEC_PATH)
    declared = tuple(item["mutant_id"] for item in spec["hard_mutants"])
    if declared != MUTANT_IDS or tuple(GATES) != MUTANT_IDS:
        raise AssertionError("JSON spec, gate registry, and fixed order disagree")
    baseline = _baseline_report()
    baseline_result = evaluate_report(baseline)
    if not baseline_result["passed"]:
        raise AssertionError(f"known-good baseline failed: {baseline_result}")
    killed: dict[str, list[str]] = {}
    for mutant_id in MUTANT_IDS:
        result = evaluate_report(apply_known_bad_mutant(baseline, mutant_id))
        if mutant_id not in result["failed_gates"]:
            raise AssertionError(f"essential mutant survived its own gate: {mutant_id}: {result}")
        killed[mutant_id] = result["failed_gates"]
    return {
        "gate_version": spec["gate_version"],
        "public_protocol_version": _load_json(PUBLIC_PROTOCOL_PATH)["schema_version"],
        "baseline_passed": True,
        "essential_mutants": len(MUTANT_IDS),
        "essential_mutants_killed": len(killed),
        "failed_gate_map": killed,
        "hmm_oracle": {
            "filter_x0_y0_0": _hmm_oracle(None),
            "smooth_x0_y0_0_y1_1": _hmm_oracle(1),
            "smooth_x0_y0_0_y1_0": _hmm_oracle(0),
        },
        "e02_oracle": dict(
            zip(("condition_bad_t1", "population_do_bad_t1"), _e02_oracle(_load_json(PUBLIC_PROTOCOL_PATH)))
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="prove all known-bad mutants are rejected")
    parser.add_argument("--report", type=Path, help="evaluate an external runner report")
    parser.add_argument("--write-baseline", type=Path, help="write the synthetic known-good self-test report")
    args = parser.parse_args()
    if args.write_baseline:
        args.write_baseline.write_text(
            json.dumps(_baseline_report(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if args.report:
        result = evaluate_report(_load_json(args.report))
    else:
        result = self_test()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.get("passed", result.get("baseline_passed", False)) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MUTANT_IDS",
    "apply_known_bad_mutant",
    "evaluate_report",
    "self_test",
]
