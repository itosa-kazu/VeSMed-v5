from __future__ import annotations

import subprocess
import sys

from repair_hhs_dka_overlap_geometry_20260527 import axis_mod, merge_risk_factor
from repair_obgyn_failure_clusters_20260526 import upsert_mechanism_edge
from repair_remaining_failure_clusters_20260526 import (
    find_axis,
    load_disease,
    measurement_axis,
    qualitative_axis,
    set_fields,
    upsert_axis,
    write_disease,
)


def repair_adrenal_crisis_geometry() -> list[str]:
    path, data = load_disease("D-ADRENAL-CRISIS")
    changed: list[str] = []

    axes = [
        qualitative_axis(
            "appetite_loss_presence",
            "symptom",
            "present_absent_0_1",
            "finding",
            None,
            [0.0, 0.05],
            [0.4, 1.0],
            "Poor appetite or anorexia is common in adrenal crisis and often accompanies nausea, vomiting, weight loss, or inability to maintain oral intake.",
            peak_day=[-7.0, 2.0],
            plateau=[0.1, 30.0],
            decline=[0.2, 14.0],
        ),
        qualitative_axis(
            "appetite_loss_severity",
            "symptom",
            "severity_score_0_1",
            "satellite",
            "appetite_loss_presence",
            [0.0, 0.05],
            [0.3, 1.0],
            "Severity of appetite loss or anorexia during adrenal crisis.",
            peak_day=[-7.0, 2.0],
            plateau=[0.1, 30.0],
            decline=[0.2, 14.0],
        ),
        qualitative_axis(
            "mental_status_abnormality_presence",
            "physical_finding",
            "present_absent_0_1",
            "finding",
            None,
            [0.0, 0.03],
            [0.0, 0.9],
            "Lethargy, confusion, delirium, somnolence, or coma can occur in adrenal crisis from shock, severe hyponatremia, fever, or hypoglycemia.",
            peak_day=[0.0, 3.0],
            plateau=[0.1, 14.0],
            decline=[0.1, 7.0],
        ),
        qualitative_axis(
            "mental_status_abnormality_severity",
            "physical_finding",
            "severity_score_0_1",
            "satellite",
            "mental_status_abnormality_presence",
            [0.0, 0.03],
            [0.0, 0.9],
            "Severity of lethargy or altered mental status during adrenal crisis.",
            peak_day=[0.0, 3.0],
            plateau=[0.1, 14.0],
            decline=[0.1, 7.0],
        ),
        measurement_axis(
            "base_excess",
            "lab_value",
            "mmol/L",
            "measurement",
            None,
            [-2.5, 2.5],
            [-14.0, 4.0],
            "Base deficit can occur in adrenal crisis from shock, volume depletion, mineralocorticoid-related acidosis, renal hypoperfusion, starvation ketosis, or concurrent illness.",
            peak_day=[0.0, 3.0],
            plateau=[0.1, 10.0],
            decline=[0.2, 7.0],
        ),
        qualitative_axis(
            "ketonuria_presence",
            "urinalysis",
            "present_absent_0_1",
            "finding",
            None,
            [0.0, 0.03],
            [0.0, 0.6],
            "Urine ketones can be absent or positive during adrenal crisis, especially with vomiting, starvation, dehydration, or comorbid diabetes; degree is captured separately.",
            peak_day=[0.0, 3.0],
            plateau=[0.1, 10.0],
            decline=[0.2, 7.0],
        ),
        qualitative_axis(
            "urine_ketone_activity",
            "urinalysis",
            "severity_score_0_1",
            "satellite",
            "ketonuria_presence",
            [0.0, 0.03],
            [0.0, 0.7],
            "Degree of urine ketone positivity during adrenal crisis from starvation, vomiting, dehydration, or comorbid diabetes.",
            peak_day=[0.0, 3.0],
            plateau=[0.1, 10.0],
            decline=[0.2, 7.0],
        ),
        measurement_axis(
            "hemoglobin_a1c",
            "lab_value",
            "percent",
            "measurement",
            None,
            [4.8, 5.6],
            [4.8, 8.0],
            "Chronic glycemia context when autoimmune polyendocrine syndrome includes diabetes; not required for ordinary adrenal crisis.",
            peak_day=[-120.0, 0.0],
            plateau=[30.0, 3650.0],
            decline=[30.0, 120.0],
        ),
    ]
    for axis in axes:
        if upsert_axis(data, axis):
            changed.append(f"D-ADRENAL-CRISIS add {axis['axis_id']}")

    glucose_edits = set_fields(
        find_axis(data, "blood_glucose"),
        {
            "peak_value_range": [30.0, 320.0],
            "shape_free_text": "Can be low from impaired counterregulation; may be high when diabetes, stress hyperglycemia, steroid treatment, infection, or insulin mismatch coexists.",
        },
    )
    changed.extend(f"D-ADRENAL-CRISIS blood_glucose.{edit}" for edit in glucose_edits)

    edge_specs = [
        ("M_GASTROINTESTINAL_STRESS_RESPONSE", "appetite_loss_presence", "increase", "Adrenal crisis commonly produces anorexia and poor oral intake."),
        ("M_GASTROINTESTINAL_STRESS_RESPONSE", "appetite_loss_severity", "increase", "GI stress and cortisol deficiency can make anorexia severe."),
        ("M_ADH_MEDIATED_HYPONATREMIA", "mental_status_abnormality_presence", "increase", "Severe hyponatremia can cause lethargy or altered mental status."),
        ("M_ADH_MEDIATED_HYPONATREMIA", "mental_status_abnormality_severity", "increase", "Worsening hyponatremia increases encephalopathy severity."),
        ("M_CATECHOLAMINE_HYPORESPONSIVE_VASODILATION", "mental_status_abnormality_severity", "increase", "Shock and poor cerebral perfusion can worsen lethargy."),
        ("M_HYPERKALEMIC_ACIDOSIS_ACTIVITY", "base_excess", "decrease", "Mineralocorticoid deficiency can contribute to metabolic acidosis and base deficit."),
        ("M_EXTRACELLULAR_VOLUME_DEPLETION", "base_excess", "decrease", "Volume depletion and hypoperfusion can add lactic/base deficit physiology."),
        ("M_GASTROINTESTINAL_STRESS_RESPONSE", "ketonuria_presence", "increase", "Vomiting, reduced intake, and starvation physiology can produce urine ketones."),
        ("M_GASTROINTESTINAL_STRESS_RESPONSE", "urine_ketone_activity", "increase", "Reduced intake and vomiting can increase urine ketone degree."),
    ]
    for source, target, effect, rationale in edge_specs:
        if upsert_mechanism_edge(data, source, target, effect, rationale, confidence="medium", lag=[0.0, 3.0]):
            changed.append(f"D-ADRENAL-CRISIS edge {source}->{target}")

    if merge_risk_factor(
        data,
        "autoimmune_polyendocrine_context",
        "present",
        [3.0, 30.0],
        [
            axis_mod(
                "blood_glucose",
                "more_variable",
                [1.5, 4.0],
                "Type 1 diabetes and insulin therapy can make glucose high, low, or rapidly changing during adrenal crisis.",
            ),
            axis_mod(
                "blood_glucose",
                "higher_peak",
                [1.1, 2.5],
                "Autoimmune polyendocrine syndrome with type 1 diabetes can present with hyperglycemia during stress illness.",
            ),
            axis_mod(
                "hemoglobin_a1c",
                "higher_peak",
                [1.2, 2.5],
                "Comorbid diabetes can make chronic glycemia context abnormal without making DKA the primary manifold.",
            ),
            axis_mod(
                "ketonuria_presence",
                "higher_peak",
                [1.2, 3.0],
                "Comorbid type 1 diabetes increases probability of urine ketones during adrenal crisis or poor intake.",
            ),
            axis_mod(
                "urine_ketone_activity",
                "higher_peak",
                [1.2, 3.0],
                "Comorbid type 1 diabetes can increase urine ketone degree during adrenal crisis or poor intake.",
            ),
        ],
        "Autoimmune thyroid disease or type 1 diabetes increases probability of autoimmune adrenal insufficiency and modifies glucose/ketone interpretation.",
        risk_category="comorbidity",
    ):
        changed.append("D-ADRENAL-CRISIS autoimmune polyendocrine glucose-ketone modulation")

    if merge_risk_factor(
        data,
        "vomiting_diarrhea_or_inability_to_take_oral_steroids",
        "present",
        [4.0, 40.0],
        [
            axis_mod(
                "M_EXTRACELLULAR_VOLUME_DEPLETION",
                "higher_peak",
                [1.5, 4.0],
                "GI losses lower volume and sodium.",
            ),
            axis_mod(
                "missed_or_inadequate_steroid_replacement_activity",
                "higher_peak",
                [2.0, 6.0],
                "Vomiting blocks oral hydrocortisone absorption.",
            ),
            axis_mod(
                "ketonuria_presence",
                "higher_peak",
                [1.1, 2.0],
                "Vomiting and reduced intake increase starvation ketone probability.",
            ),
            axis_mod(
                "urine_ketone_activity",
                "higher_peak",
                [1.1, 2.0],
                "Vomiting and reduced intake increase urine ketone degree.",
            ),
            axis_mod(
                "base_excess",
                "more_variable",
                [1.2, 2.5],
                "Vomiting, dehydration, starvation, and hypoperfusion make base excess more variable.",
            ),
        ],
        "Vomiting or diarrhea amplifies volume depletion, ketosis/starvation physiology, and makes oral replacement unreliable.",
        risk_category="trigger_context",
    ):
        changed.append("D-ADRENAL-CRISIS vomiting ketone/base-excess modulation")

    if changed:
        write_disease(path, data)
    return changed


def rebuild_master_axes() -> None:
    subprocess.run(
        [sys.executable, "-c", "import start_ui; start_ui.build_master_axes()"],
        check=True,
    )


def main() -> int:
    changed = repair_adrenal_crisis_geometry()
    if changed:
        rebuild_master_axes()
    print(f"changed={len(changed)}")
    for item in changed:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
