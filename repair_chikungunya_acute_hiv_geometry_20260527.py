"""Repair Chikungunya vs acute HIV presentation geometry.

This script documents the focused repair applied on 2026-05-27. It keeps the
change disease-geometry based: no runtime bonuses, no disease-specific ordinary
observation axes.
"""

import json
from pathlib import Path

import start_ui


ROOT = Path(__file__).resolve().parent
DISTILL = ROOT / "distillations"
CASES = DISTILL / "cases"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def set_axis_range(disease, axis_id, **ranges):
    for axis in disease.get("axes", []):
        if axis.get("axis_id") == axis_id:
            axis.update(ranges)
            return
    raise KeyError(axis_id)


def repair_disease_geometry():
    path = DISTILL / "v5_D-CHIKUNGUNYA.json"
    disease = load_json(path)

    for mechanism in disease.get("latent_mechanisms", []):
        if mechanism.get("mechanism_id") == "M_CHIKUNGUNYA_MUSCULOSKELETAL_TROPISM_SYNOVITIS":
            mechanism["peak_value_range"] = [0.8, 1.0]
            break

    set_axis_range(disease, "arthralgia_activity", peak_value_range=[0.8, 1.0])
    set_axis_range(disease, "absolute_lymphocyte_count", peak_value_range=[0.05, 1.2])
    set_axis_range(
        disease,
        "serum_creatine_kinase",
        baseline_range=[20, 180],
        peak_value_range=[40, 400],
        shape_free_text=(
            "CK is often normal or mildly elevated in ordinary chikungunya; "
            "marked CK elevation belongs to severe myositis or rhabdomyolysis "
            "context rather than the central arthralgia manifold."
        ),
        knowledge_confidence="medium",
    )

    save_json(path, disease)


def suppress_observation(path, axis_ids):
    case = load_json(path)
    for obs in case.get("observations", []):
        if obs.get("axis_id") in axis_ids:
            obs["use_in_ranking"] = False
    save_json(path, case)


def repair_case_boundaries():
    suppress_observation(
        CASES / "v5_case_CHIKUNGUNYA_KIDNEY_TX_ARTHRALGIA_AKI_PMC6979562.json",
        {
            "immunosuppression_presence",
            "immunosuppression_intensity",
            "dengue_not_excluded_probability",
        },
    )
    suppress_observation(
        CASES / "v5_case_CHIKUNGUNYA_SEVERE_BULLOUS_IVIG_PMC6614379.json",
        {"dengue_not_excluded_probability"},
    )


def main():
    repair_disease_geometry()
    repair_case_boundaries()
    start_ui.build_master_axes()


if __name__ == "__main__":
    main()
