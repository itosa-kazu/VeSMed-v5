from __future__ import annotations

import subprocess
import sys

from repair_obgyn_failure_clusters_20260526 import upsert_mechanism_edge
from repair_remaining_failure_clusters_20260526 import (
    load_disease,
    qualitative_axis,
    upsert_axis,
    write_disease,
)
from repair_toxicology_failure_clusters_20260526 import (
    load_case,
    upsert_case_observation,
    write_case,
)


CASE_CONTEXT_OBSERVATIONS = {
    "ALCOHOL_WITHDRAWAL_DELIRIUM_AUTONOMIC_SHOCK_PMC8336347": [
        {
            "axis_id": "chronic_heavy_alcohol_use_presence",
            "value": 1.0,
            "unit": "present_absent_0_1",
            "source_text_value": "about 20-year history of alcohol use disorder and average 1.5 L wine/day, equivalent to 180 g alcohol",
            "use_in_ranking": True,
            "category": "exposure_context",
            "axis_role": "finding",
            "day": 0,
        },
        {
            "axis_id": "recent_alcohol_reduction_or_cessation_presence",
            "value": 1.0,
            "unit": "present_absent_0_1",
            "source_text_value": "alcohol was acutely withdrawn during hospitalization after persistent long-term intake",
            "use_in_ranking": True,
            "category": "trigger_context",
            "axis_role": "finding",
            "day": 5,
        },
    ],
    "ALCOHOL_WITHDRAWAL_DELIRIUM_REFRACTORY_PROPOFOL_PMC3105562": [
        {
            "axis_id": "chronic_heavy_alcohol_use_presence",
            "value": 1.0,
            "unit": "present_absent_0_1",
            "source_text_value": "heavy alcoholic for the last 8 years",
            "use_in_ranking": True,
            "category": "exposure_context",
            "axis_role": "finding",
            "day": 0,
        },
    ],
    "ALCOHOL_WITHDRAWAL_DELIRIUM_SEIZURE_DEXMEDETOMIDINE_PMC7659997": [
        {
            "axis_id": "chronic_heavy_alcohol_use_presence",
            "value": 1.0,
            "unit": "present_absent_0_1",
            "source_text_value": "history of severe alcohol dependence with multiple hospitalizations and relapses in the last 2 years",
            "use_in_ranking": True,
            "category": "exposure_context",
            "axis_role": "finding",
            "day": 0,
        },
        {
            "axis_id": "recent_alcohol_reduction_or_cessation_presence",
            "value": 1.0,
            "unit": "present_absent_0_1",
            "source_text_value": "developed symptoms within a day of stoppage of regular heavy drinking",
            "use_in_ranking": True,
            "category": "trigger_context",
            "axis_role": "finding",
            "day": 1,
        },
    ],
}


def repair_alcohol_withdrawal_geometry() -> list[str]:
    path, data = load_disease("D-ALCOHOL-WITHDRAWAL-DELIRIUM")
    changed: list[str] = []

    axes = [
        qualitative_axis(
            "psychosis_hallucination_activity",
            "neurologic_finding",
            "severity_score_0_1",
            "satellite",
            "mental_status_abnormality_presence",
            [0.0, 0.03],
            [0.0, 1.0],
            "Hallucination or psychotic perceptual disturbance severity during withdrawal delirium; visual, auditory, or tactile hallucinations may occur as part of delirium tremens.",
            peak_day=[1.0, 5.0],
            plateau=[0.1, 7.0],
            decline=[0.2, 14.0],
        ),
        qualitative_axis(
            "visual_hallucination_activity",
            "neurologic_finding",
            "severity_score_0_1",
            "satellite",
            "mental_status_abnormality_presence",
            [0.0, 0.03],
            [0.0, 1.0],
            "Visual hallucination or illusion severity during alcohol withdrawal delirium.",
            peak_day=[1.0, 5.0],
            plateau=[0.1, 7.0],
            decline=[0.2, 14.0],
        ),
    ]
    for axis in axes:
        if upsert_axis(data, axis):
            changed.append(f"D-ALCOHOL-WITHDRAWAL-DELIRIUM add {axis['axis_id']}")
        if upsert_mechanism_edge(
            data,
            "M_AWD_DELIRIUM_PERCEPTUAL_DISTURBANCE_NETWORK",
            axis["axis_id"],
            "increase",
            "The withdrawal delirium perceptual-disturbance network can produce hallucination/illusion activity as a severity satellite of abnormal mental status.",
            confidence="high",
            lag=[0.0, 2.0],
        ):
            changed.append(f"D-ALCOHOL-WITHDRAWAL-DELIRIUM edge perceptual network->{axis['axis_id']}")

    if changed:
        write_disease(path, data)
    return changed


def repair_case_context_observations() -> list[str]:
    changed: list[str] = []

    for case_id, observations in CASE_CONTEXT_OBSERVATIONS.items():
        path, case = load_case(case_id)
        case_changed = False
        for observation in observations:
            if upsert_case_observation(case, observation):
                changed.append(f"{case_id} add {observation['axis_id']}")
                case_changed = True
        if case_changed:
            write_case(path, case)
    return changed


def rebuild_master_axes() -> None:
    subprocess.run(
        [sys.executable, "-c", "import start_ui; start_ui.build_master_axes()"],
        check=True,
    )


def main() -> int:
    changed = repair_alcohol_withdrawal_geometry()
    changed.extend(repair_case_context_observations())
    if changed:
        rebuild_master_axes()
    print(f"changed={len(changed)}")
    for item in changed:
        print(f"- {item}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
