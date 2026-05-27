"""Repair candidemia source-context and organism-identity geometry.

This is a geometry repair, not a runtime ranking rule:

* Candida species identity axes are microbiology/pathogen identity axes. They
  should not be context-neutral treatment modifiers for non-Candida candidates
  in post-workup ranking.
* Candidemia catheter/source-control axes already exist but were missing
  trajectory parameters, causing central line and catheter-source observations
  to score against baseline.
* Active antifungal coverage is treatment context, not an ordinary diagnostic
  observation. Preserve it outside ranking observations in cases where it
  describes therapy timing after cultures.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DISTILL_DIR = ROOT / "distillations"
CASE_DIR = DISTILL_DIR / "cases"

CANDIDEMIA_PATH = DISTILL_DIR / "v5_D-CANDIDEMIA.json"
CASE_PATHS = [
    CASE_DIR / "v5_case_CANDIDEMIA_AURIS_PICC_TPN_PMC7386129.json",
    CASE_DIR / "v5_case_CANDIDEMIA_GLabrata_URINARY_SEPSIS_PMC4052353.json",
]

SPECIES_AXES = {
    "candida_auris_probability",
    "candida_glabrata_probability",
    "candida_parapsilosis_probability",
    "candida_krusei_probability",
}

SPECIES_AXIS_TRAJECTORY = {
    "peak_day_range": [0.0, 30.0],
    "peak_value_range": [0.0, 1.0],
    "plateau_duration_days": [1.0, 365.0],
    "decline_half_life_days": [7.0, 365.0],
}

SOURCE_AXIS_TRAJECTORIES = {
    "central_venous_catheter_present": {
        "peak_day_range": [-365.0, 0.0],
        "plateau_duration_days": [1.0, 3650.0],
        "decline_half_life_days": [1.0, 30.0],
    },
    "catheter_source_probability": {
        "peak_day_range": [0.0, 14.0],
        "plateau_duration_days": [1.0, 90.0],
        "decline_half_life_days": [1.0, 21.0],
    },
    "source_control_need": {
        "peak_day_range": [0.0, 14.0],
        "plateau_duration_days": [0.5, 90.0],
        "decline_half_life_days": [1.0, 30.0],
    },
}


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def axis_map(data: dict) -> dict[str, dict]:
    return {axis.get("axis_id"): axis for axis in data.get("axes", []) if axis.get("axis_id")}


def repair_candidemia() -> list[str]:
    data = load_json(CANDIDEMIA_PATH)
    axes = axis_map(data)
    changes: list[str] = []

    for axis_id in sorted(SPECIES_AXES):
        axis = axes.get(axis_id)
        if not axis:
            continue
        if axis.get("category") != "microbiology":
            axis["category"] = "microbiology"
            changes.append(f"{axis_id}: category=microbiology")
        if axis.get("axis_role") != "measurement":
            axis["axis_role"] = "measurement"
            changes.append(f"{axis_id}: axis_role=measurement")
        axis.setdefault(
            "ontology_note",
            "Candida species identity is post-workup microbiology/pathogen identity; treatment implications are handled separately by treatment modifiers.",
        )
        for key, value in SPECIES_AXIS_TRAJECTORY.items():
            if axis.get(key) != value:
                axis[key] = value
                changes.append(f"{axis_id}: {key}={value}")

    for axis_id, params in SOURCE_AXIS_TRAJECTORIES.items():
        axis = axes.get(axis_id)
        if not axis:
            raise KeyError(f"Missing candidemia source axis: {axis_id}")
        for key, value in params.items():
            if axis.get(key) != value:
                axis[key] = value
                changes.append(f"{axis_id}: {key}={value}")

    save_json(CANDIDEMIA_PATH, data)
    return changes


def move_active_antifungal_observation(path: Path) -> list[str]:
    data = load_json(path)
    moved = []
    retained = []
    for item in data.get("observations", []) or []:
        if item.get("axis_id") != "active_antifungal_coverage_probability":
            retained.append(item)
            continue
        moved_item = dict(item)
        moved_item["use_in_ranking"] = False
        moved_item["ranking_exclusion_reason"] = (
            "Treatment coverage timing is management context, not disease-identity geometry."
        )
        moved_item.setdefault("category", "treatment_context")
        moved.append(moved_item)

    if not moved:
        return []

    data["observations"] = retained
    bucket = data.setdefault("actual_treatment", [])
    existing = {
        (
            item.get("axis_id"),
            item.get("source_text_value"),
            item.get("value"),
        )
        for item in bucket
        if isinstance(item, dict)
    }
    for item in moved:
        key = (item.get("axis_id"), item.get("source_text_value"), item.get("value"))
        if key not in existing:
            bucket.append(item)

    save_json(path, data)
    return [f"{path.name}: moved active_antifungal_coverage_probability to actual_treatment"]


def rebuild_master_axes() -> None:
    subprocess.run(
        [sys.executable, "-c", "import start_ui; start_ui.build_master_axes()"],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    changes = repair_candidemia()
    for path in CASE_PATHS:
        changes.extend(move_active_antifungal_observation(path))
    rebuild_master_axes()
    print(json.dumps({"changed": changes}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
