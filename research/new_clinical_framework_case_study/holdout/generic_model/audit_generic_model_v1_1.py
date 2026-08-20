"""Case-blind content audit for the generic-model/1.1.0 candidate.

The audit deliberately reads no holdout case asset.  It verifies the
deterministic v1.0 -> v1.1 upgrade, model-schema acceptance, common-source
joint factors, dynamic activation declarations, action scope, and the explicit
activation/local posterior closure.  Runtime behavior and runtime-seal binding
are separate final gates.
"""

from __future__ import annotations

import hashlib
import importlib.util
import itertools
import json
import math
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACK = HERE / "model_pack.json"
BUILDER = HERE / "build_generic_model_v1_1.py"
SOURCE = HERE / "archive" / "generic-model-1.0.0" / "model_pack.json"
EVIDENCE = HERE.parent / "evidence" / "GENERIC_MODEL_V1_1_CONTENT_AUDIT.json"

EXPECTED_RESOLVING_ACTION_TARGETS = {
    "ACTION_RHYTHM_STABILIZATION": "P_ARRHYTHMIA",
    "ACTION_CORONARY_REPERFUSION_CLASS": "P_MYOCARDIAL_ISCHEMIA",
    "ACTION_INFECTIOUS_SOURCE_CONTROL": "P_INFECTIOUS_BURDEN",
    "ACTION_HORMONAL_REPLACEMENT_SUPPORT": "P_HORMONAL_SUPPORT_FAILURE",
    "ACTION_ADRENERGIC_DRIVER_SUPPRESSION": "P_ADRENERGIC_DRIVE",
    "ACTION_TOXICOLOGIC_SOURCE_CONTROL": "P_TOXICOLOGIC_DRIVER",
    "ACTION_MECHANICAL_DECOMPRESSION": "P_OBSTRUCTIVE_LOAD",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_builder() -> Any:
    module_spec = importlib.util.spec_from_file_location("generic_builder_v1_1", BUILDER)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError("cannot load generic builder")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


def finite_paths(value: Any, path: str = "$") -> list[str]:
    failures: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            failures.extend(finite_paths(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            failures.extend(finite_paths(child, f"{path}[{index}]"))
    elif isinstance(value, float) and not math.isfinite(value):
        failures.append(path)
    return failures


def main() -> int:
    builder = load_builder()
    model = json.loads(PACK.read_text(encoding="utf-8"))
    source = json.loads(SOURCE.read_text(encoding="utf-8"))
    rebuilt = builder.build()
    checks: list[dict[str, Any]] = []

    def check(check_id: str, passed: bool, evidence: Any) -> None:
        checks.append(
            {
                "check_id": check_id,
                "status": "PASS" if passed else "FAIL",
                "evidence": evidence,
            }
        )

    check(
        "GM11-DETERMINISTIC-BUILD",
        rebuilt == model,
        {
            "builder": str(BUILDER.relative_to(ROOT)).replace("\\", "/"),
            "source": str(SOURCE.relative_to(ROOT)).replace("\\", "/"),
            "source_sha256": sha256(SOURCE),
            "pack_sha256": sha256(PACK),
        },
    )

    # Schema/semantic validation uses the current runtime source tree but does
    # not execute a case or certify a runtime seal.
    import sys

    sys.path.insert(0, str(ROOT))
    from runtime_v2 import validate_model_spec

    validated = validate_model_spec(model)
    check(
        "GM11-RUNTIME-MODEL-SCHEMA",
        validated["model_version"] == "generic-model/1.1.0",
        {"model_version": validated["model_version"]},
    )

    build_boundary = model.get("build_boundary", {})
    check(
        "GM11-CASE-BLIND-BOUNDARY",
        build_boundary.get("case_blind") is True
        and build_boundary.get("case_assets_consumed_by_upgrade") is False
        and build_boundary.get("holdout_outcome_seen") is False
        and build_boundary.get("holdout_timeline_seen") is False
        and build_boundary.get("holdout_values_seen") is False
        and build_boundary.get("specific_case_web_search_performed") is False,
        build_boundary,
    )

    check(
        "GM11-FINITE-NUMBERS",
        not finite_paths(model),
        {"nonfinite_paths": finite_paths(model)},
    )

    joint_failures: list[str] = []
    joint_observations = 0
    joint_rows = 0
    for observation in model["observations"]:
        emissions = {
            row["process_id"]: row for row in observation.get("emissions", [])
        }
        process_ids = sorted(emissions)
        table = observation.get("joint_likelihoods")
        if len(process_ids) <= 1:
            if table is not None:
                joint_failures.append(f"{observation['concept_id']}: unexpected joint table")
            continue
        joint_observations += 1
        expected_keys = {
            ",".join(
                process_id
                for process_id, enabled in zip(process_ids, bits)
                if enabled
            )
            or "-"
            for bits in itertools.product((False, True), repeat=len(process_ids))
        }
        if set(table or {}) != expected_keys:
            joint_failures.append(f"{observation['concept_id']}: active-set coverage")
            continue
        joint_rows += len(table)
        if table["-"] != observation["reference_likelihood"]:
            joint_failures.append(f"{observation['concept_id']}: empty set != reference")
        for process_id in process_ids:
            if table[process_id] != emissions[process_id]["active_likelihood"]:
                joint_failures.append(
                    f"{observation['concept_id']}: singleton {process_id} mismatch"
                )
    check(
        "GM11-COMMON-SOURCE-JOINT-FACTORS",
        not joint_failures and joint_observations == 40 and joint_rows == 880,
        {
            "multi_process_observations": joint_observations,
            "joint_distribution_rows": joint_rows,
            "failures": joint_failures,
            "composition": model["parameter_epistemology"].get(
                "joint_likelihood_composition"
            ),
        },
    )

    activation_failures: list[str] = []
    for process in model["processes"]:
        pid = process["process_id"]
        transition = process.get("activation_transition", {})
        enter = float(transition.get("enter_hazard_per_step", -1.0))
        withdraw = float(transition.get("withdraw_hazard_per_step", -1.0))
        prior = float(process["activation_prior"])
        stationary = enter / (enter + withdraw) if enter + withdraw > 0 else math.nan
        if enter <= 0.0 or withdraw <= 0.0 or abs(stationary - prior) > 1e-12:
            activation_failures.append(f"{pid}: non-neutral base turnover")
        if transition.get("entry_initialization", {}).get("policy") != "RESET_TO_PRIOR":
            activation_failures.append(f"{pid}: entry policy")
        if (
            transition.get("exit_policy", {}).get("policy")
            != "SURVIVOR_CARRY_REENTRY_RESET"
        ):
            activation_failures.append(f"{pid}: exit policy")
        if transition.get("enter_log_hazard_shift_by_mode"):
            activation_failures.append(f"{pid}: dormant mode used for entry")
        if transition.get("enter_log_hazard_shift_by_coordinate"):
            activation_failures.append(f"{pid}: dormant coordinate used for entry")
        if transition.get("withdraw_log_hazard_shift_by_mode"):
            activation_failures.append(f"{pid}: local mode used for withdrawal")
        if transition.get("withdraw_log_hazard_shift_by_coordinate"):
            activation_failures.append(f"{pid}: local coordinate used for withdrawal")
        if transition.get("parameter_status") != "STRUCTURAL_TOY_NONCALIBRATED":
            activation_failures.append(f"{pid}: parameter epistemology")
    check(
        "GM11-PROCESS-ACTIVATION-KERNELS",
        not activation_failures and len(model["processes"]) == 13,
        {"processes": len(model["processes"]), "failures": activation_failures},
    )

    nonself_pairs = {
        (row["source_process_id"], row["target_process_id"])
        for row in source.get("process_couplings", [])
        if row["source_process_id"] != row["target_process_id"]
    }
    activation_pairs = {
        (row["source_process_id"], row["target_process_id"])
        for row in model.get("process_activation_couplings", [])
    }
    check(
        "GM11-ACTIVATION-COUPLING-COVERAGE",
        activation_pairs == nonself_pairs
        and len(model.get("process_activation_couplings", [])) == len(nonself_pairs),
        {
            "declared_pairs": len(activation_pairs),
            "expected_pairs": len(nonself_pairs),
            "missing": sorted(nonself_pairs - activation_pairs),
            "unexpected": sorted(activation_pairs - nonself_pairs),
        },
    )

    action_failures: list[str] = []
    action_effect_targets: dict[str, str] = {}
    for action in model["actions"]:
        action_id = action["action_id"]
        effects = action.get("activation_effects", [])
        if len(effects) > 1:
            action_failures.append(f"{action_id}: multiple activation targets")
        if effects:
            action_effect_targets[action_id] = effects[0]["process_id"]
        declared_status = action.get("causal_identification", {}).get("status")
        if action.get("causal_status") != declared_status:
            action_failures.append(f"{action_id}: causal status mismatch")
        if action.get("causal_status") == "OUT_OF_SCOPE":
            if action.get("effects") or effects or "identified_set" in action:
                action_failures.append(f"{action_id}: typed refusal is effectful")
    check(
        "GM11-ACTION-ACTIVATION-SCOPE",
        not action_failures
        and action_effect_targets == EXPECTED_RESOLVING_ACTION_TARGETS,
        {
            "activation_effect_targets": action_effect_targets,
            "expected": EXPECTED_RESOLVING_ACTION_TARGETS,
            "failures": action_failures,
        },
    )

    approximation = model.get("posterior_factorization", {})
    check(
        "GM11-POSTERIOR-CLOSURE-DECLARATION",
        approximation.get("representation")
        == "conditional_active_mean_field_over_process_local_state"
        and approximation.get("local_state_semantics")
        == "q(x,m|process_active)"
        and approximation.get("unsupported_correlations_policy") == "OUT_OF_SCOPE"
        and approximation.get("error_tolerance", {}).get("reference")
        == "scope.tolerance"
        and approximation.get("error_tolerance", {}).get("epsilon")
        == model["scope"]["tolerance"]
        and "active-process-joint-is-not-full-state-joint"
        in approximation.get("assumption_ids", []),
        approximation,
    )

    passed = all(row["status"] == "PASS" for row in checks)
    report = {
        "schema_version": "ncf.generic-model-content-audit.v1",
        "model_id": model["model_id"],
        "model_version": model["model_version"],
        "case_blind": True,
        "primary_holdout_inspected": False,
        "scope": "MODEL_CONTENT_ONLY_RUNTIME_BEHAVIOR_AND_SEAL_BINDING_SEPARATE",
        "status": "PASS" if passed else "FAIL",
        "artifact_hashes": {
            "build_generic_model_v1_1.py": sha256(BUILDER),
            "source_model_pack.json": sha256(SOURCE),
            "model_pack.json": sha256(PACK),
        },
        "checks": checks,
    }
    EVIDENCE.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
