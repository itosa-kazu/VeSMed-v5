from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from repair_obgyn_failure_clusters_20260526 import upsert_mechanism_edge
from repair_remaining_failure_clusters_20260526 import (
    ROOT,
    DIST,
    load_disease,
    measurement_axis,
    qualitative_axis,
    set_fields,
    upsert_axis,
    write_disease,
)


CASE_DIR = DIST / "cases"


def load_case(case_id: str) -> tuple[Path, dict]:
    path = CASE_DIR / f"v5_case_{case_id}.json"
    return path, json.loads(path.read_text(encoding="utf-8-sig"))


def write_case(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upsert_case_observation(case: dict, observation: dict) -> bool:
    observations = case.setdefault("observations", [])
    axis_id = observation["axis_id"]
    for existing in observations:
        if existing.get("axis_id") == axis_id:
            changed = False
            for key, value in observation.items():
                if existing.get(key) != value:
                    existing[key] = value
                    changed = True
            return changed
    observations.append(observation)
    return True


def rename_case_axis(case: dict, old_axis_id: str, new_observation: dict) -> bool:
    changed = False
    observations = case.setdefault("observations", [])
    for existing in observations:
        if existing.get("axis_id") == old_axis_id:
            for key in list(existing):
                if key not in new_observation:
                    existing.pop(key, None)
                    changed = True
            for key, value in new_observation.items():
                if existing.get(key) != value:
                    existing[key] = value
                    changed = True
            return changed
    return upsert_case_observation(case, new_observation)


def axis_mod(
    axis_id: str,
    effect: str | None = None,
    magnitude: list[float] | None = None,
    rationale: str | None = None,
    *,
    peak_value_factor: list[float] | None = None,
    baseline_value_factor: list[float] | None = None,
    sigma_factor: list[float] | None = None,
) -> dict:
    out = {"axis_id": axis_id}
    if effect is not None:
        out["effect"] = effect
    if magnitude is not None:
        out["magnitude_factor_range"] = magnitude
    if peak_value_factor is not None:
        out["peak_value_factor"] = peak_value_factor
    if baseline_value_factor is not None:
        out["baseline_value_factor"] = baseline_value_factor
    if sigma_factor is not None:
        out["sigma_factor"] = sigma_factor
    if rationale:
        out["clinical_rationale"] = rationale
    return out


def merge_present_risk_mod(
    data: dict,
    factor: str,
    risk_type: str,
    p_ratio: list[float],
    mods: list[dict],
    rationale: str,
) -> bool:
    risk_factors = data.setdefault("risk_factors", [])
    for rf in risk_factors:
        if rf.get("factor") != factor:
            continue
        changed = False
        if rf.get("type") != risk_type and rf.get("risk_type") != risk_type:
            rf.pop("risk_type", None)
            rf["type"] = risk_type
            changed = True
        if rf.get("clinical_rationale") != rationale:
            rf["clinical_rationale"] = rationale
            changed = True
        if rf.get("knowledge_confidence") != "high":
            rf["knowledge_confidence"] = "high"
            changed = True
        present = rf.setdefault("modulation", {}).setdefault("present", {})
        if present.get("P_disease_ratio") != p_ratio:
            present["P_disease_ratio"] = p_ratio
            changed = True
        existing = {
            item.get("axis_id"): item
            for item in present.get("axis_response_modulation", [])
            if isinstance(item, dict) and item.get("axis_id")
        }
        for mod in mods:
            if existing.get(mod["axis_id"]) != mod:
                existing[mod["axis_id"]] = mod
                changed = True
        ordered = list(existing.values())
        if present.get("axis_response_modulation") != ordered:
            present["axis_response_modulation"] = ordered
            changed = True
        return changed

    risk_factors.append(
        {
            "factor": factor,
            "type": risk_type,
            "modulation": {"present": {"P_disease_ratio": p_ratio, "axis_response_modulation": mods}},
            "clinical_rationale": rationale,
            "knowledge_confidence": "high",
        }
    )
    return True


def repair_salicylate_geometry() -> list[str]:
    changed: list[str] = []
    path, sal = load_disease("D-SALICYLATE-TOXICITY")

    for axis_id in [
        "chronic_salicylate_accumulation_context_presence",
        "topical_or_bismuth_salicylate_exposure_presence",
    ]:
        axis = next(a for a in sal["axes"] if a.get("axis_id") == axis_id)
        updates = {
            "peak_value_range": [0.0, 0.35],
            "clinical_interpretation": (
                "Route/subtype context for salicylate poisoning. It should explain the case when present, "
                "but absence of this alternative exposure route must not be treated as evidence against salicylate toxicity."
            ),
        }
        fields = set_fields(axis, updates)
        changed.extend(f"D-SALICYLATE-TOXICITY:{field}" for field in fields)

    epigastric = qualitative_axis(
        "epigastric_pain_presence",
        "qualitative",
        "present_absent_0_1",
        "satellite",
        "abdominal_pain_presence",
        [0.0, 0.04],
        [0.0, 0.85],
        "Epigastric discomfort or pain is a reusable satellite of abdominal pain from gastric irritation, including salicylate overdose.",
        peak_day=[0.0, 2.0],
        plateau=[0.0, 7.0],
        decline=[0.1, 14.0],
    )
    if upsert_axis(sal, epigastric):
        changed.append("D-SALICYLATE-TOXICITY:axis:epigastric_pain_presence")
    if upsert_mechanism_edge(
        sal,
        "M_SAL_TOX_EXPOSURE_ABSORPTION_BURDEN",
        "epigastric_pain_presence",
        "increase",
        "Salicylate exposure can irritate gastric mucosa and present as epigastric discomfort.",
        lag=[0.0, 1.0],
    ):
        changed.append("D-SALICYLATE-TOXICITY:edge:M_SAL_TOX_EXPOSURE_ABSORPTION_BURDEN->epigastric_pain_presence")

    massive_aspirin_mods = [
        axis_mod("acute_high_dose_salicylate_ingestion_presence", "higher_peak", [2.0, 5.0]),
        axis_mod("salicylate_exposure_intensity", "higher_peak", [1.3, 2.0]),
        axis_mod("serum_salicylate_concentration_mg_dl", "higher_peak", [1.15, 1.8]),
        axis_mod("metabolic_acidosis_presence", "higher_peak", [1.2, 2.0]),
        axis_mod("metabolic_acidosis_severity", "higher_peak", [1.2, 2.0]),
        axis_mod("abdominal_pain_presence", "higher_peak", [1.2, 1.8]),
        axis_mod("epigastric_pain_presence", "higher_peak", [1.2, 2.0]),
        axis_mod("nausea_presence", "higher_peak", [1.2, 1.8]),
    ]
    for factor in ["intentional_massive_aspirin_overdose", "intentional_massive_salicylate_overdose"]:
        if merge_present_risk_mod(
            sal,
            factor,
            "toxin_exposure_context",
            [5.0, 50.0],
            massive_aspirin_mods,
            "Massive aspirin/salicylate ingestion strongly supports salicylate toxicity and raises acute exposure burden, level, acid-base, and GI-irritation axes.",
        ):
            changed.append(f"D-SALICYLATE-TOXICITY:risk:{factor}")
    if merge_present_risk_mod(
        sal,
        "enteric_coated_aspirin_delayed_absorption_context",
        "toxin_kinetic_context",
        [1.2, 5.0],
        [
            axis_mod("enteric_coated_aspirin_exposure_presence", "higher_peak", [2.0, 5.0]),
            axis_mod("salicylate_level_rebound_or_rising_presence", "higher_peak", [1.5, 3.0]),
            axis_mod("serum_salicylate_concentration_mg_dl", "more_variable", [1.5, 3.0]),
        ],
        "Enteric-coated aspirin or pharmacobezoar context prolongs absorption and makes delayed or persistent salicylate levels plausible.",
    ):
        changed.append("D-SALICYLATE-TOXICITY:risk:enteric_coated_aspirin_delayed_absorption_context")

    write_disease(path, sal)

    for case_id, source_text in [
        (
            "SALICYLATE_TOXICITY_ENTERIC_COATED_PHARMACOBEZOAR_PMC6292349",
            "500 enteric-coated 325 mg aspirin tablets, total 162.5 g",
        ),
        (
            "SALICYLATE_TOXICITY_REBOUND_SLED_PMC11093619",
            "intentional massive aspirin overdose",
        ),
    ]:
        cpath, case = load_case(case_id)
        if upsert_case_observation(
            case,
            {
                "axis_id": "acute_high_dose_salicylate_ingestion_presence",
                "value": 1.0,
                "unit": "present_absent_0_1",
                "source_text_value": source_text,
                "use_in_ranking": True,
                "axis_role": "satellite",
                "parent_axis_id": "salicylate_exposure_presence",
                "category": "toxin_exposure",
            },
        ):
            changed.append(f"{case_id}:obs:acute_high_dose_salicylate_ingestion_presence")
        write_case(cpath, case)

    return changed


def repair_methanol_geometry() -> list[str]:
    changed: list[str] = []
    path, meth = load_disease("D-METHANOL-POISONING")

    if merge_present_risk_mod(
        meth,
        "intentional_high_dose_methanol_ingestion",
        "toxin_exposure_context",
        [5.0, 50.0],
        [
            axis_mod("toxic_alcohol_exposure_presence", "higher_peak", [1.5, 3.0]),
            axis_mod("methanol_exposure_probability", "higher_peak", [1.5, 3.0]),
            axis_mod("reported_methanol_ingestion_volume_ml", "higher_peak", [1.1, 2.0]),
            axis_mod("time_from_methanol_exposure_to_care_hours", "more_variable", [8.0, 25.0]),
        ],
        "A credible high-dose methanol ingestion history is upstream source geometry even before osmolal gap, anion gap, or serum methanol results are available.",
    ):
        changed.append("D-METHANOL-POISONING:risk:intentional_high_dose_methanol_ingestion")
    if merge_present_risk_mod(
        meth,
        "reported_95_percent_methanol_solution_ingestion_context",
        "toxin_exposure_context",
        [20.0, 100.0],
        [
            axis_mod("toxic_alcohol_exposure_presence", "higher_peak", [2.0, 4.0]),
            axis_mod("methanol_exposure_probability", "higher_peak", [2.0, 4.0]),
            axis_mod("reported_methanol_ingestion_volume_ml", "higher_peak", [1.1, 2.0], sigma_factor=[1.5, 3.0]),
            axis_mod("time_from_methanol_exposure_to_care_hours", "more_variable", [10.0, 30.0]),
        ],
        "A reported ingestion of a 95 percent methanol solution is high-specificity methanol source evidence even when confirmatory methanol testing is unavailable at presentation.",
    ):
        changed.append("D-METHANOL-POISONING:risk:reported_95_percent_methanol_solution_ingestion_context")
    if merge_present_risk_mod(
        meth,
        "early_presentation_before_formate_acidosis_context",
        "toxin_kinetic_context",
        [3.0, 20.0],
        [
            axis_mod("metabolic_acidosis_presence", "lower_peak", [0.05, 0.25]),
            axis_mod("metabolic_acidosis_severity", "lower_peak", [0.05, 0.25]),
            axis_mod("anion_gap", "lower_peak", [0.1, 0.4]),
            axis_mod("serum_bicarbonate", "more_variable", [2.0, 4.0]),
            axis_mod("time_from_methanol_exposure_to_care_hours", "more_variable", [10.0, 30.0]),
        ],
        "Very early methanol presentations can be dominated by parent-alcohol exposure and coingestants before formate accumulation produces high anion gap metabolic acidosis.",
    ):
        changed.append("D-METHANOL-POISONING:risk:early_presentation_before_formate_acidosis_context")
    if merge_present_risk_mod(
        meth,
        "ethanol_coformulation_delayed_formate_context",
        "toxin_kinetic_context",
        [3.0, 20.0],
        [
            axis_mod("coingested_ethanol_probability", "higher_peak", [1.5, 3.0]),
            axis_mod("metabolic_acidosis_presence", "lower_peak", [0.1, 0.4]),
            axis_mod("metabolic_acidosis_severity", "lower_peak", [0.1, 0.4]),
            axis_mod("anion_gap", "lower_peak", [0.2, 0.6]),
            axis_mod("serum_bicarbonate", "more_variable", [1.5, 2.5]),
        ],
        "Co-formulated or therapeutic ethanol can delay ADH conversion to formate, so early methanol presentations may lack high anion gap metabolic acidosis.",
    ):
        changed.append("D-METHANOL-POISONING:risk:ethanol_coformulation_delayed_formate_context")
    if merge_present_risk_mod(
        meth,
        "flunitrazepam_coingestion_respiratory_depression_context",
        "coingestion_context",
        [2.0, 10.0],
        [
            axis_mod("sedative_opioid_or_anesthetic_exposure_presence", "higher_peak", [2.0, 4.0]),
            axis_mod("sedative_opioid_or_anesthetic_exposure_degree", "higher_peak", [1.5, 3.0]),
            axis_mod("arterial_pco2", baseline_value_factor=[1.2, 1.5], sigma_factor=[1.5, 3.0]),
            axis_mod("respiratory_rate", "lower_peak", [0.4, 0.8]),
            axis_mod("mental_status_abnormality_presence", "higher_peak", [1.2, 2.0]),
        ],
        "Sedative coingestion can explain early hypercapnia and drowsiness without requiring formate-driven acidosis at presentation.",
    ):
        changed.append("D-METHANOL-POISONING:risk:flunitrazepam_coingestion_respiratory_depression_context")

    write_disease(path, meth)

    cpath, case = load_case("METHANOL_POISONING_EARLY_INGESTION_NO_GAP_PMC12450070")
    risk_context = case.setdefault("risk_context", [])
    for item in [
        {
            "factor": "reported_95_percent_methanol_solution_ingestion_context",
            "category": "toxin_exposure_context",
            "source_text_value": "intentionally ingesting 200-250 mL of a solution containing 95% methanol",
        },
        {
            "factor": "early_presentation_before_formate_acidosis_context",
            "category": "toxin_kinetic_context",
            "source_text_value": "presentation about 1.5 hours after ingestion with normal anion gap and bicarbonate before formate acidosis emerged",
        },
    ]:
        if not any(existing.get("factor") == item["factor"] for existing in risk_context):
            risk_context.append(item)
            changed.append(f"METHANOL_POISONING_EARLY_INGESTION_NO_GAP_PMC12450070:risk:{item['factor']}")
    if rename_case_axis(
        case,
        "time_since_salicylate_exposure_hours",
        {
            "axis_id": "time_from_methanol_exposure_to_care_hours",
            "value": 1.5,
            "unit": "hours",
            "source_text_value": "ingestion occurred approximately 1.5 hours before ED arrival",
            "use_in_ranking": True,
            "axis_role": "measurement",
            "category": "source_context",
            "parent_axis_id": "methanol_exposure_probability",
        },
    ):
        changed.append("METHANOL_POISONING_EARLY_INGESTION_NO_GAP_PMC12450070:rename:time_from_methanol_exposure_to_care_hours")
    if upsert_case_observation(
        case,
        {
            "axis_id": "coingested_ethanol_probability",
            "value": 1.0,
            "unit": "probability_0_1",
            "source_text_value": "solution contained ethanol as a co-formulation; fraction was approximately 5%",
            "use_in_ranking": True,
            "axis_role": "satellite",
            "parent_axis_id": "methanol_exposure_probability",
            "category": "toxin_kinetic_context",
        },
    ):
        changed.append("METHANOL_POISONING_EARLY_INGESTION_NO_GAP_PMC12450070:obs:coingested_ethanol_probability")
    write_case(cpath, case)
    return changed


def repair_cyanide_geometry() -> list[str]:
    changed: list[str] = []
    path, cyan = load_disease("D-CYANIDE-POISONING")

    severe_mods = [
        axis_mod("cyanide_exposure_probability", "higher_peak", [1.5, 3.0]),
        axis_mod("cyanide_exposure_intensity", "higher_peak", [1.5, 3.0]),
        axis_mod("industrial_cyanide_exposure_presence", "higher_peak", [1.5, 3.0]),
        axis_mod("hypotension_presence", "higher_peak", [1.2, 2.0]),
        axis_mod("systolic_blood_pressure", baseline_value_factor=[0.55, 0.75], sigma_factor=[1.2, 1.8]),
        axis_mod("diastolic_blood_pressure", baseline_value_factor=[0.65, 0.85], sigma_factor=[1.2, 1.8]),
        axis_mod("glasgow_coma_scale_score", peak_value_factor=[2.0, 3.0], sigma_factor=[1.1, 1.6]),
        axis_mod("serum_lactate", "higher_peak", [1.1, 1.8]),
    ]
    for factor in ["occupational_sodium_cyanide_tank_exposure", "cyanide_gas_environment_detected"]:
        if merge_present_risk_mod(
            cyan,
            factor,
            "toxin_exposure_context",
            [5.0, 50.0],
            severe_mods,
            "Documented occupational sodium-cyanide exposure is high-specificity source geometry and can drive rapid coma, lactic acidosis, and cardiovascular collapse.",
        ):
            changed.append(f"D-CYANIDE-POISONING:risk:{factor}")
    write_disease(path, cyan)

    cpath, case = load_case("CYANIDE_POISONING_OCCUPATIONAL_SODIUM_CYANIDE_PMC3229413")
    for obs in [
        {
            "axis_id": "cyanide_exposure_probability",
            "value": 1.0,
            "unit": "probability_0_1",
            "source_text_value": "occupational sodium cyanide tank exposure with cyanide gas detected",
            "use_in_ranking": True,
            "axis_role": "satellite",
            "parent_axis_id": "cyanide_exposure_presence",
            "category": "toxin_exposure_context",
        },
        {
            "axis_id": "cyanide_exposure_intensity",
            "value": 0.8,
            "unit": "severity_score_0_1",
            "source_text_value": "cyanide gas environment during tank cleaning with severe collapse and lactic acidosis",
            "use_in_ranking": True,
            "axis_role": "satellite",
            "parent_axis_id": "cyanide_exposure_presence",
            "category": "toxin_exposure_context",
        },
        {
            "axis_id": "industrial_cyanide_exposure_presence",
            "value": 1.0,
            "unit": "present_absent_0_1",
            "source_text_value": "sodium cyanide used in nickel and chrome plating tank cleaning",
            "use_in_ranking": True,
            "axis_role": "satellite",
            "parent_axis_id": "cyanide_exposure_presence",
            "category": "toxin_exposure_context",
        },
    ]:
        if upsert_case_observation(case, obs):
            changed.append(f"CYANIDE_POISONING_OCCUPATIONAL_SODIUM_CYANIDE_PMC3229413:obs:{obs['axis_id']}")
    write_case(cpath, case)
    return changed


def repair_beta_blocker_geometry() -> list[str]:
    changed: list[str] = []
    path, beta = load_disease("D-BETA-BLOCKER-TOXICITY")

    if merge_present_risk_mod(
        beta,
        "massive_metoprolol_overdose_context",
        "exposure_severity_context",
        [8.0, 50.0],
        [
            axis_mod("beta_blocker_exposure_intensity", "higher_peak", [1.5, 3.0]),
            axis_mod("metoprolol_exposure_probability", "higher_peak", [1.5, 3.0]),
            axis_mod("metoprolol_ingested_dose_mg", "higher_peak", [1.1, 2.0]),
            axis_mod("somnolence_or_coma_presence", "higher_peak", [4.0, 8.0]),
            axis_mod("mental_status_abnormality_presence", "higher_peak", [1.5, 3.0]),
            axis_mod("hypotension_presence", "higher_peak", [1.5, 3.0]),
            axis_mod("systolic_blood_pressure", baseline_value_factor=[0.55, 0.75], sigma_factor=[1.2, 1.8]),
            axis_mod("diastolic_blood_pressure", baseline_value_factor=[0.65, 0.85], sigma_factor=[1.2, 1.8]),
            axis_mod("serum_glucose", "more_variable", [2.0, 4.0]),
            axis_mod("serum_potassium", "more_variable", [1.5, 3.0], baseline_value_factor=[1.05, 1.2]),
            axis_mod("respiratory_depression_presence", "higher_peak", [1.2, 2.0]),
            axis_mod("oxygen_saturation", "more_variable", [1.5, 3.0]),
        ],
        "Massive metoprolol overdose can produce profound CNS depression, shock, respiratory compromise, and wider glucose/potassium behavior than mild therapeutic beta-blocker toxicity.",
    ):
        changed.append("D-BETA-BLOCKER-TOXICITY:risk:massive_metoprolol_overdose_context")
    write_disease(path, beta)

    cpath, case = load_case("BETA_BLOCKER_TOXICITY_METOPROLOL_ECMO_PMC8103398")
    for obs in [
        {
            "axis_id": "beta_blocker_exposure_intensity",
            "value": 1.0,
            "unit": "severity_score_0_1",
            "source_text_value": "100 tablets of 75 mg metoprolol tartrate, total 7500 mg",
            "use_in_ranking": True,
            "axis_role": "satellite",
            "parent_axis_id": "beta_blocker_exposure_presence",
            "category": "toxin_exposure_context",
        },
        {
            "axis_id": "time_since_beta_blocker_exposure_hours",
            "value": 7.0,
            "unit": "hours",
            "value_range": [6.0, 8.0],
            "source_text_value": "overdose was thought to be 6 to 8 hours prior to admission",
            "use_in_ranking": True,
            "axis_role": "measurement",
            "parent_axis_id": "beta_blocker_exposure_presence",
            "category": "temporal_context",
        },
    ]:
        if upsert_case_observation(case, obs):
            changed.append(f"BETA_BLOCKER_TOXICITY_METOPROLOL_ECMO_PMC8103398:obs:{obs['axis_id']}")
    write_case(cpath, case)
    return changed


def rebuild_master_axes() -> None:
    subprocess.run(
        [sys.executable, "-c", "import start_ui; start_ui.build_master_axes()"],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    changed: list[str] = []
    changed.extend(repair_salicylate_geometry())
    changed.extend(repair_methanol_geometry())
    changed.extend(repair_cyanide_geometry())
    changed.extend(repair_beta_blocker_geometry())
    rebuild_master_axes()
    print(f"changed={len(changed)}")
    for item in changed:
        print(item)


if __name__ == "__main__":
    main()
