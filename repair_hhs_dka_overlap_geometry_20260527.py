from __future__ import annotations

import subprocess
import sys

from repair_obgyn_failure_clusters_20260526 import upsert_mechanism_edge
from repair_remaining_failure_clusters_20260526 import (
    find_axis,
    load_disease,
    set_fields,
    upsert_axis,
    write_disease,
)


def qualitative_axis(
    axis_id: str,
    category: str,
    unit: str,
    role: str,
    parent: str | None,
    baseline: list[float],
    peak: list[float],
    text: str,
    *,
    peak_day: list[float] | None = None,
    plateau: list[float] | None = None,
    decline: list[float] | None = None,
    confidence: str = "medium",
) -> dict:
    out = {
        "axis_id": axis_id,
        "category": category,
        "unit": unit,
        "log_scale": False,
        "axis_role": role,
        "baseline_range": baseline,
        "peak_day_range": peak_day or [-30.0, 2.0],
        "peak_value_range": peak,
        "plateau_duration_days": plateau or [0.1, 30.0],
        "decline_half_life_days": decline or [0.2, 14.0],
        "clinical_interpretation": text,
        "knowledge_confidence": confidence,
    }
    if parent:
        out["parent_axis_id"] = parent
    return out


def axis_mod(axis_id: str, effect: str, magnitude: list[float], rationale: str) -> dict:
    return {
        "axis_id": axis_id,
        "effect": effect,
        "magnitude_factor_range": magnitude,
        "clinical_rationale": rationale,
    }


def merge_risk_factor(
    data: dict,
    factor: str,
    modulation_category: str,
    p_ratio: list[float],
    mods: list[dict],
    rationale: str,
    *,
    risk_category: str = "host_context",
    confidence: str = "high",
) -> bool:
    risk_factors = data.setdefault("risk_factors", [])
    for rf in risk_factors:
        if rf.get("factor") != factor:
            continue
        changed = False
        if rf.get("category") != risk_category:
            rf["category"] = risk_category
            changed = True
        if rf.get("clinical_rationale") != rationale:
            rf["clinical_rationale"] = rationale
            changed = True
        if rf.get("knowledge_confidence") != confidence:
            rf["knowledge_confidence"] = confidence
            changed = True
        modulation = rf.setdefault("modulation", {})
        bucket = modulation.setdefault(modulation_category, {})
        if bucket.get("P_disease_ratio") != p_ratio:
            bucket["P_disease_ratio"] = p_ratio
            changed = True
        existing = {
            item.get("axis_id"): item
            for item in bucket.get("axis_response_modulation", [])
            if isinstance(item, dict) and item.get("axis_id")
        }
        for mod in mods:
            if existing.get(mod["axis_id"]) != mod:
                existing[mod["axis_id"]] = mod
                changed = True
        ordered = list(existing.values())
        if bucket.get("axis_response_modulation") != ordered:
            bucket["axis_response_modulation"] = ordered
            changed = True
        return changed

    risk_factors.append(
        {
            "factor": factor,
            "category": risk_category,
            "modulation": {
                modulation_category: {
                    "P_disease_ratio": p_ratio,
                    "axis_response_modulation": mods,
                }
            },
            "clinical_rationale": rationale,
            "knowledge_confidence": confidence,
        }
    )
    return True


def add_hyperglycemic_crisis_symptom_axes(data: dict, mechanism_id: str, rationale_prefix: str) -> bool:
    changed = False
    common_axes = [
        qualitative_axis(
            "fatigue_presence",
            "symptom",
            "present_absent_0_1",
            "finding",
            None,
            [0.0, 0.05],
            [0.3, 1.0],
            "Fatigue can accompany hyperglycemic crisis through dehydration, catabolism, poor intake, and trigger illness.",
        ),
        qualitative_axis(
            "fatigue_severity",
            "symptom",
            "severity_score_0_1",
            "satellite",
            "fatigue_presence",
            [0.0, 0.05],
            [0.2, 1.0],
            "Severity of fatigue during hyperglycemic crisis.",
        ),
        qualitative_axis(
            "malaise_presence",
            "symptom",
            "present_absent_0_1",
            "finding",
            None,
            [0.0, 0.05],
            [0.3, 1.0],
            "Malaise can accompany hyperglycemic crisis through dehydration, catabolism, poor intake, and trigger illness.",
        ),
        qualitative_axis(
            "malaise_severity",
            "symptom",
            "severity_score_0_1",
            "satellite",
            "malaise_presence",
            [0.0, 0.05],
            [0.2, 1.0],
            "Severity of malaise during hyperglycemic crisis.",
        ),
    ]
    for axis in common_axes:
        changed |= upsert_axis(data, axis)
        changed |= upsert_mechanism_edge(
            data,
            mechanism_id,
            axis["axis_id"],
            "increase",
            f"{rationale_prefix} can produce {axis['axis_id']} through dehydration, catabolism, and reduced intake.",
            confidence="medium",
            lag=[0.0, 7.0],
        )
    return changed


def repair_hhs() -> list[str]:
    path, data = load_disease("D-HYPEROSMOLAR-HYPERGLYCEMIC-STATE")
    changed: list[str] = []

    if add_hyperglycemic_crisis_symptom_axes(
        data,
        "M_HHS_OSMOTIC_DIURESIS_FREE_WATER_DEFICIT_ACTIVITY",
        "HHS osmotic diuresis and prolonged hyperglycemia",
    ):
        changed.append("D-HHS fatigue/malaise axes")

    if upsert_axis(
        data,
        qualitative_axis(
            "ketonuria_presence",
            "urinalysis",
            "present_absent_0_1",
            "finding",
            None,
            [0.0, 0.03],
            [0.0, 0.95],
            "Urine ketone positivity. Typical HHS has absent or small ketonuria, but pediatric or mixed HHS-DKA presentations can have positive urine ketones; degree is captured separately by ketone severity/activity axes.",
            peak_day=[0.0, 7.0],
            plateau=[0.1, 30.0],
            decline=[1.0, 14.0],
            confidence="high",
        ),
    ):
        changed.append("D-HHS ketonuria_presence axis")
    if upsert_mechanism_edge(
        data,
        "M_HHS_KETOSIS_SUPPRESSION_ACTIVITY",
        "ketonuria_presence",
        "decrease",
        "Relative insulin activity suppresses marked ketonuria in typical HHS, while mixed presentations may still have positive low-grade urine ketones.",
        confidence="medium",
        lag=[0.0, 2.0],
    ):
        changed.append("D-HHS ketonuria edge")

    axis_updates = {
        "urine_ketone_activity": {
            "peak_value_range": [0.0, 0.65],
            "plateau_duration_days": [0.1, 10.0],
            "shape_free_text": "Ketonuria on urine dipstick; typical HHS has absent or small ketonuria, but pediatric or mixed HHS-DKA presentations may show low to moderate urine ketones.",
        },
        "blood_ketone_activity": {
            "peak_value_range": [0.0, 0.5],
            "plateau_duration_days": [0.1, 10.0],
            "shape_free_text": "Semi-quantitative blood ketone positivity; typical HHS has absent or small ketones, with low to moderate positivity possible in mixed HHS-DKA physiology.",
        },
        "serum_bicarbonate": {
            "peak_value_range": [10.0, 34.0],
            "plateau_duration_days": [0.1, 10.0],
            "shape_free_text": "Serum bicarbonate or total CO2; often normal or mildly low in HHS, with broader values when pediatric overlap ketosis, renal hypoperfusion, lactic acidosis, vomiting alkalosis, or treatment timing coexist.",
        },
        "base_excess": {
            "peak_value_range": [-18.0, 6.0],
            "plateau_duration_days": [0.1, 10.0],
            "shape_free_text": "Base excess/base deficit; often near normal or mildly negative in HHS, but mixed HHS-DKA physiology, renal hypoperfusion, lactate, and treatment timing broaden the presentation range.",
        },
        "arterial_ph": {
            "peak_value_range": [7.18, 7.45],
            "plateau_duration_days": [0.1, 10.0],
            "shape_free_text": "Arterial or venous pH; usually near normal or mildly acidemic in HHS, with moderate acidemia possible in mixed HHS-DKA physiology or concurrent lactic/renal acid-base stress.",
        },
    }
    for axis_id, updates in axis_updates.items():
        edits = set_fields(find_axis(data, axis_id), updates)
        if edits:
            changed.extend(f"D-HHS {edit}" for edit in edits)

    if merge_risk_factor(
        data,
        "pediatric_or_adolescent_hhs_context",
        "present",
        [1.2, 6.0],
        [
            axis_mod(
                "serum_glucose",
                "higher_peak",
                [1.05, 1.5],
                "Pediatric HHS can present as severe new-onset hyperglycemia.",
            ),
            axis_mod(
                "serum_osmolality",
                "higher_peak",
                [1.02, 1.25],
                "Children and adolescents with HHS may present after prolonged osmotic diuresis with marked hypertonicity.",
            ),
            axis_mod(
                "urine_ketone_activity",
                "higher_peak",
                [1.1, 2.0],
                "Pediatric and new-onset diabetes presentations can have HHS-DKA overlap with low-grade urine ketones.",
            ),
            axis_mod(
                "ketonuria_presence",
                "higher_peak",
                [1.5, 4.0],
                "Low-grade urine ketone positivity can remain present in pediatric or mixed HHS-DKA physiology.",
            ),
            axis_mod(
                "serum_bicarbonate",
                "more_variable",
                [1.2, 2.0],
                "Overlap ketosis, renal hypoperfusion, vomiting, and treatment timing make bicarbonate more variable in pediatric HHS.",
            ),
            axis_mod(
                "base_excess",
                "more_variable",
                [1.2, 2.0],
                "Overlap ketosis, renal hypoperfusion, vomiting, and treatment timing make base excess more variable in pediatric HHS.",
            ),
        ],
        "Children and adolescents can develop HHS, often with new-onset diabetes and partial DKA overlap rather than the classic older-adult phenotype.",
        confidence="medium",
    ):
        changed.append("D-HHS pediatric/adolescent overlap risk modulation")

    if merge_risk_factor(
        data,
        "limited_water_or_weight_loss_context",
        "osmotic_prodrome",
        [1.2, 5.0],
        [
            axis_mod(
                "serum_glucose",
                "higher_peak",
                [1.05, 1.4],
                "Prolonged osmotic symptoms and weight loss reflect sustained hyperglycemia before care.",
            ),
            axis_mod(
                "serum_osmolality",
                "higher_peak",
                [1.05, 1.3],
                "Free-water deficit and ongoing osmotic diuresis raise effective tonicity.",
            ),
            axis_mod(
                "corrected_serum_sodium",
                "higher_peak",
                [1.05, 1.3],
                "Weight loss and limited net water replacement expose the corrected sodium/free-water deficit signal.",
            ),
            axis_mod(
                "dehydration_activity",
                "higher_peak",
                [1.1, 2.0],
                "Sustained osmotic diuresis and weight loss increase clinical volume depletion.",
            ),
            axis_mod(
                "polydipsia_activity",
                "higher_peak",
                [1.1, 2.0],
                "A prolonged osmotic prodrome commonly produces marked thirst.",
            ),
            axis_mod(
                "polyuria_activity",
                "higher_peak",
                [1.1, 2.0],
                "A prolonged osmotic prodrome commonly produces marked polyuria.",
            ),
            axis_mod(
                "weight_loss_activity",
                "higher_peak",
                [1.1, 2.0],
                "Sustained glucosuria, dehydration, and catabolism can produce substantial weight loss.",
            ),
        ],
        "A prolonged osmotic prodrome with marked weight loss is a geometry-level HHS context because free-water deficit accumulates over time.",
    ):
        changed.append("D-HHS osmotic prodrome risk modulation")

    if changed:
        write_disease(path, data)
    return changed


def repair_dka() -> list[str]:
    path, data = load_disease("D-DIABETIC-KETOACIDOSIS")
    changed: list[str] = []

    if add_hyperglycemic_crisis_symptom_axes(
        data,
        "M_DKA_HYPERGLYCEMIA_OSMOTIC_DIURESIS_ACTIVITY",
        "DKA hyperglycemia, osmotic diuresis, and catabolism",
    ):
        changed.append("D-DKA fatigue/malaise axes")

    if upsert_axis(
        data,
        qualitative_axis(
            "ketonuria_presence",
            "urinalysis",
            "present_absent_0_1",
            "finding",
            None,
            [0.0, 0.03],
            [0.7, 1.0],
            "Urine ketone positivity is common in DKA; degree is captured separately by ketone severity/activity axes.",
            peak_day=[0.0, 2.0],
            plateau=[0.1, 5.0],
            decline=[0.2, 3.0],
            confidence="high",
        ),
    ):
        changed.append("D-DKA ketonuria_presence axis")
    if upsert_mechanism_edge(
        data,
        "M_DKA_LIPOLYSIS_KETOGENESIS_ACTIVITY",
        "ketonuria_presence",
        "increase",
        "Ketogenesis in DKA produces urine ketone positivity; severity is captured by the ketone activity axis.",
        confidence="high",
        lag=[0.0, 2.0],
    ):
        changed.append("D-DKA ketonuria edge")

    if changed:
        write_disease(path, data)
    return changed


def rebuild_master_axes() -> None:
    subprocess.run(
        [sys.executable, "-c", "import start_ui; start_ui.build_master_axes()"],
        check=True,
    )


def main() -> int:
    changed = []
    changed.extend(repair_hhs())
    changed.extend(repair_dka())
    if changed:
        rebuild_master_axes()
    print(f"changed={len(changed)}")
    for item in changed:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
