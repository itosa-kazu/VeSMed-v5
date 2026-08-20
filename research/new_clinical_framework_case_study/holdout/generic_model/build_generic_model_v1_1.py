"""Deterministically upgrade the case-blind generic pack to v1.1.

This builder consumes only the archived v1.0 generic model.  It does not read
case assets.  All new values are structural toy values, not fitted clinical
probabilities or causal effects.
"""

from __future__ import annotations

import copy
import itertools
import json
import math
from pathlib import Path


HERE = Path(__file__).resolve().parent
SOURCE = HERE / "archive" / "generic-model-1.0.0" / "model_pack.json"
OUTPUT = HERE / "model_pack.json"

MODEL_VERSION = "generic-model/1.1.0"
PARAMETER_STATUS = "STRUCTURAL_TOY_NONCALIBRATED"
ACTIVATION_SOURCE_ID = "generic-model-1.1.0-activation-kernel-rule"
JOINT_SOURCE_ID = "generic-model-1.1.0-conservative-joint-factor-rule"


def rounded(value: float) -> float:
    return round(float(value), 12)


def conservative_joint_distribution(
    reference: dict, active_distributions: list[dict]
) -> dict:
    """One common-source factor without multiplying one finding per process.

    The empty active set uses the declared reference distribution.  A nonempty
    set is an equal-weight mixture of the active-process likelihoods.  Gaussian
    mixtures are moment-matched into the runtime's typed Gaussian family.  The
    rule deliberately omits unvalidated synergy and is not a clinical joint
    probability model.
    """

    if not active_distributions:
        return copy.deepcopy(reference)
    family = reference["family"]
    count = float(len(active_distributions))
    if family == "bernoulli":
        return {
            "family": "bernoulli",
            "p_true": rounded(
                sum(float(row["p_true"]) for row in active_distributions) / count
            ),
        }
    if family == "categorical":
        categories = list(reference["probabilities"])
        probabilities = {
            category: sum(
                float(row["probabilities"][category])
                for row in active_distributions
            )
            / count
            for category in categories
        }
        total = sum(probabilities.values())
        return {
            "family": "categorical",
            "floor": float(reference.get("floor", 1e-9)),
            "probabilities": {
                category: rounded(probabilities[category] / total)
                for category in categories
            },
        }
    if family == "gaussian":
        mean = sum(float(row["mean"]) for row in active_distributions) / count
        second_moment = sum(
            float(row["sd"]) ** 2 + float(row["mean"]) ** 2
            for row in active_distributions
        ) / count
        variance = max(1e-12, second_moment - mean**2)
        return {
            "family": "gaussian",
            "mean": rounded(mean),
            "sd": rounded(math.sqrt(variance)),
        }
    raise ValueError(f"unsupported distribution family: {family}")


def add_joint_factors(spec: dict) -> None:
    for observation in spec["observations"]:
        emissions = {
            row["process_id"]: row for row in observation.get("emissions", [])
        }
        process_ids = sorted(emissions)
        if len(process_ids) <= 1:
            observation.pop("joint_likelihoods", None)
            continue
        table: dict[str, dict] = {}
        for bits in itertools.product((False, True), repeat=len(process_ids)):
            active = [
                process_id
                for process_id, enabled in zip(process_ids, bits)
                if enabled
            ]
            key = ",".join(active) or "-"
            table[key] = conservative_joint_distribution(
                observation["reference_likelihood"],
                [
                    emissions[process_id]["active_likelihood"]
                    for process_id in active
                ],
            )
        observation["joint_likelihoods"] = table


def add_activation_kernels(spec: dict) -> None:
    # This makes each process's original toy activation prior the neutral
    # stationary point before mode/severity/coupling/action modifiers.
    turnover_per_step = 0.04
    for process in spec["processes"]:
        prior = float(process["activation_prior"])
        process["activation_transition"] = {
            "enter_hazard_per_step": rounded(prior * turnover_per_step),
            "withdraw_hazard_per_step": rounded(
                (1.0 - prior) * turnover_per_step
            ),
            # Dormant local state is not reused as a second, hidden diagnostic
            # vote for entry. Entry modifiers come from declared upstream
            # process couplings and causal actions instead.
            "enter_log_hazard_shift_by_mode": {},
            "enter_log_hazard_shift_by_coordinate": {},
            # The v1 wire stores q(local, mode | process active), not a
            # configuration-specific full joint.  Dynamic activation hazards
            # therefore cannot depend on the one shared local conditional.
            "withdraw_log_hazard_shift_by_mode": {},
            "withdraw_log_hazard_shift_by_coordinate": {},
            "entry_initialization": {"policy": "RESET_TO_PRIOR"},
            "exit_policy": {"policy": "SURVIVOR_CARRY_REENTRY_RESET"},
            "parameter_status": PARAMETER_STATUS,
            "source_id": ACTIVATION_SOURCE_ID,
            "version": "1.0.0",
        }

    activation_couplings = []
    seen_pairs: set[tuple[str, str]] = set()
    for coupling in spec.get("process_couplings", []):
        source = coupling["source_process_id"]
        target = coupling["target_process_id"]
        if source == target or (source, target) in seen_pairs:
            continue
        seen_pairs.add((source, target))
        strength = float(coupling["strength_per_step"])
        activation_couplings.append(
            {
                "coupling_id": f"ACTIVATION__{source}__TO__{target}",
                "source_process_id": source,
                "target_process_id": target,
                "enter_log_hazard_shift_per_step": rounded(10.0 * strength),
                "withdraw_log_hazard_shift_per_step": rounded(-5.0 * strength),
                "parameter_status": PARAMETER_STATUS,
                "source_id": ACTIVATION_SOURCE_ID,
                "version": "1.0.0",
            }
        )
    spec["process_activation_couplings"] = activation_couplings

    # Only cause/process-removing action classes modify process persistence.
    # Pure support classes remain coordinate pushes and must not masquerade as
    # process resolution.
    resolving_action_targets = {
        "ACTION_RHYTHM_STABILIZATION": "P_ARRHYTHMIA",
        "ACTION_CORONARY_REPERFUSION_CLASS": "P_MYOCARDIAL_ISCHEMIA",
        "ACTION_INFECTIOUS_SOURCE_CONTROL": "P_INFECTIOUS_BURDEN",
        "ACTION_HORMONAL_REPLACEMENT_SUPPORT": "P_HORMONAL_SUPPORT_FAILURE",
        "ACTION_ADRENERGIC_DRIVER_SUPPRESSION": "P_ADRENERGIC_DRIVE",
        "ACTION_TOXICOLOGIC_SOURCE_CONTROL": "P_TOXICOLOGIC_DRIVER",
        "ACTION_MECHANICAL_DECOMPRESSION": "P_OBSTRUCTIVE_LOAD",
    }
    for action in spec["actions"]:
        action["causal_status"] = action.get("causal_identification", {}).get(
            "status", "UNIDENTIFIABLE"
        )
        if action["causal_status"] == "OUT_OF_SCOPE":
            # The v1 placeholder contained null scalar bounds that were never
            # an identified set and are invalid under the final runtime schema.
            action.pop("identified_set", None)
        target = resolving_action_targets.get(action["action_id"])
        action["activation_effects"] = (
            [
                {
                    "process_id": target,
                    "enter_log_hazard_shift_per_unit": -0.8,
                    "withdraw_log_hazard_shift_per_unit": 1.2,
                    "parameter_status": PARAMETER_STATUS,
                    "source_id": ACTIVATION_SOURCE_ID,
                    "version": "1.0.0",
                }
            ]
            if target
            else []
        )


def build() -> dict:
    spec = json.loads(SOURCE.read_text(encoding="utf-8"))
    spec["model_version"] = MODEL_VERSION
    spec["posterior_factorization"] = {
        "representation": "conditional_active_mean_field_over_process_local_state",
        "local_state_semantics": "q(x,m|process_active)",
        "assumption_ids": [
            "active-process-joint-is-not-full-state-joint",
            "shared-local-conditional-across-active-configurations",
            "no-dormant-local-state-posterior",
            "entry-resets-to-declared-prior",
            "partial-exit-preserves-survivor-active-conditional",
        ],
        "error_tolerance": {
            "reference": "scope.tolerance",
            "epsilon": float(spec["scope"]["tolerance"]),
        },
        "unsupported_correlations_policy": "OUT_OF_SCOPE",
    }
    spec.setdefault("no_new_action_dynamics", {}).update(
        {
            "semantics": (
                "propagate the exact active-process factorial joint with declared "
                "enter/withdraw hazards; evolve q(local,mode|process_active) with "
                "process-local drift and declared process/mode couplings; continue "
                "residual effects of already-performed actions; start no new exposure"
            ),
            "local_state_semantics": "q(x,m|process_active)",
        }
    )
    spec.setdefault("parameter_epistemology", {}).update(
        {
            "joint_likelihood_composition": (
                "case-blind equal-weight mixture of active-process typed likelihoods; "
                "Gaussian mixtures are moment-matched; no synergy, calibration, or "
                "common-cause magnitude is claimed"
            ),
            "process_activation_transitions": (
                "case-blind structural toy hazards derived from the existing toy "
                "activation prior; local-state-dependent hazards are deliberately "
                "excluded by the conditional-active factorization; not incidence, "
                "resolution probability, or calibrated transition rate"
            ),
            "process_activation_couplings": (
                "deterministic directional transform of existing cross-process drift "
                "couplings; not a causal hazard ratio"
            ),
            "action_activation_effects": (
                "uniform directional placeholders only for declared cause/process-"
                "removing action classes; all patient-level counterfactuals remain "
                "UNIDENTIFIABLE"
            ),
            "posterior_factorization": (
                "the dependent active-process factorial joint is exact only over "
                "activation bits; each local coordinate/mode posterior is conditional "
                "on that process being active and is shared across active configurations"
            ),
        }
    )
    spec.setdefault("build_boundary", {}).update(
        {
            "source_model_version": "generic-model/1.0.0",
            "upgrade_builder": "build_generic_model_v1_1.py",
            "case_assets_consumed_by_upgrade": False,
        }
    )
    add_joint_factors(spec)
    add_activation_kernels(spec)
    return spec


if __name__ == "__main__":
    OUTPUT.write_text(
        json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT)
