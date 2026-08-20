"""Build immutable knowledge-time cuts for two published V5 stress cases.

The generated files live outside the active atlas.  They deliberately preserve
what was knowable at each cut and never modify a disease distillation.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "staged_cases"


def write_case(case: dict, family: str, order: int, slug: str) -> Path:
    directory = OUT / family
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"v5_case_{order:02d}_{slug}.json"
    path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def staged_base(source: dict, *, case_id: str, snapshot_day: float, label: str, expected: str) -> dict:
    return {
        "case_id": case_id,
        "source_pmid": source.get("source_pmid"),
        "source_pmcid": source.get("source_pmcid"),
        "source_url": source.get("source_url"),
        "disease_label_per_paper": source.get("disease_label_per_paper"),
        "expected_manifold": expected,
        "demographics": copy.deepcopy(source.get("demographics") or {}),
        "snapshot_day": snapshot_day,
        "diagnostic_stage": "presentation",
        "ranking_evidence_mode": "presentation",
        "snapshot_label": label,
        "risk_context": copy.deepcopy(source.get("risk_context") or []),
        "observations": [],
        "action_history": [],
        "record_only": [],
        "provenance_contract": {
            "mode": "replay_as_then",
            "future_evidence_excluded": True,
            "source_case_path": source.get("_source_case_path"),
        },
    }


def with_day(item: dict, day: float) -> dict:
    item = copy.deepcopy(item)
    item["day"] = day
    item["available_at_day"] = day
    item["use_in_ranking"] = True
    return item


def build_hav() -> list[Path]:
    source_path = ROOT / "tmp_blind_eval" / "cases_for_ranking" / "v5_case_PMC7005653_BLIND_EVAL.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["_source_case_path"] = str(source_path)
    # The source file is a day-0 snapshot and omits explicit timestamps on its
    # presentation observations.  Pin them to day 0 before replay; otherwise
    # prepare_case_data() defaults an omitted day to each later cut and silently
    # turns old observations into apparently current measurements.
    workup_axis_ids = {
        "hav_igm_positivity",
        "hepatic_cholestasis_presence",
        "hepatic_necroinflammation_presence",
        "periportal_hepatic_necrosis_presence",
    }
    base_observations = [
        with_day(o, 0.0)
        for o in source["observations"]
        if o.get("axis_id") not in workup_axis_ids
    ]
    early_workup_observations = [
        with_day(o, 0.5)
        for o in source["observations"]
        if o.get("axis_id") in workup_axis_ids
    ]
    course = copy.deepcopy(source["course_observations"])

    actions = [
        {"day": 2, "action": "endotracheal_intubation", "source_text_value": "required endotracheal intubation"},
        {"day": 2, "action": "dobutamine", "source_text_value": "dobutamine was initiated for cardiogenic shock"},
        {"day": 2, "action": "low_dose_norepinephrine", "source_text_value": "low doses of noradrenaline were initiated"},
        {"day": 2, "action": "standard_volume_plasma_exchange_session_1", "source_text_value": "plasma exchange was started as salvage therapy"},
        {"day": 3, "action": "standard_volume_plasma_exchange_session_2", "source_text_value": "three consecutive sessions over three days"},
        {"day": 4, "action": "standard_volume_plasma_exchange_session_3", "source_text_value": "three consecutive sessions over three days"},
        {"day": 9, "action": "extubation", "source_text_value": "extubated nine days after ICU admission"},
    ]

    specs = [
        (0, 0.0, "ICU admission before etiologic workup and before decompensation", False, []),
        (1, 0.5, "initial biopsy and HAV serology available before day-2 decompensation; exact within-day time unreported", True, []),
        (2, 2.0, "ICU day 2 after intubation and initial hemodynamic support, before plasma exchange", True, []),
        (3, 5.0, "after three plasma-exchange sessions; improvement reported without exact numeric values", True, [
            {
                "day": 5,
                "event": "multisystem_improvement_after_plasma_exchange",
                "source_text_value": "progressive clinical improvement with normalization of cardiac function and improvement in liver tests, ammonia, INR, and TCD pulsatility index",
                "causal_status": "post_treatment_temporal_association_not_identified_counterfactual",
            }
        ]),
        (4, 9.0, "ICU day 9: extubated", True, []),
        (5, 14.0, "ICU day 14: ALF resolved, cardiac function normalized, transferred to ward", True, []),
    ]
    paths = []
    for order, day, label, include_workup, extra_record in specs:
        case = staged_base(
            source,
            case_id=f"PMC7005653_HAV_ALF_TAKOTSUBO_CUT_{order:02d}",
            snapshot_day=day,
            label=label,
            expected="D-ACUTE-HEPATITIS-A",
        )
        case["related_manifolds_per_paper"] = ["D-ACUTE-LIVER-FAILURE"]
        case["observations"] = copy.deepcopy(base_observations)
        if include_workup:
            case["observations"].extend(copy.deepcopy(early_workup_observations))
            case["diagnostic_stage"] = "post_workup"
            case["ranking_evidence_mode"] = "all_available"
            case["time_uncertainty"] = (
                "The paper places liver biopsy and hepatotropic serology before the day-2 collapse "
                "but gives no exact within-day result times; day 0.5 is an ordering coordinate."
            )
        case["course_observations"] = [o for o in course if float(o.get("day", 0.0)) <= day]
        case["action_history"] = [
            a for a in actions
            if float(a["day"]) <= day
            and not (day == 2.0 and "plasma_exchange" in a["action"])
        ]
        case["record_only"].extend(extra_record)
        if day >= 14:
            case["course_observations"].extend([
                {
                    "day": 14,
                    "axis_id": "hepatic_encephalopathy_presence",
                    "value": 0.0,
                    "unit": "present_absent_0_1",
                    "source_text_value": "resolution of acute liver failure before transfer to the regular ward",
                    "use_in_ranking": True,
                },
                {
                    "day": 14,
                    "axis_id": "left_ventricular_systolic_dysfunction_presence",
                    "value": 0.0,
                    "unit": "present_absent_0_1",
                    "source_text_value": "normalization of cardiac function",
                    "use_in_ranking": True,
                },
                {
                    "day": 14,
                    "axis_id": "shock_presence",
                    "value": 0.0,
                    "unit": "present_absent_0_1",
                    "source_text_value": "cardiogenic shock resolved before ward transfer",
                    "use_in_ranking": True,
                },
            ])
            case["record_only"].append({
                "day": 14,
                "event": "ward_transfer",
                "source_text_value": "discharged to the regular ward following resolution of ALF and normalization of cardiac function",
            })
        paths.append(write_case(case, "PMC7005653", order, f"PMC7005653_DAY_{day:g}".replace(".", "p")))
    return paths


def build_tma() -> list[Path]:
    source_path = ROOT / "distillations" / "cases" / "v5_case_COMPLEMENT_MEDIATED_TMA_APS_ANTIGBM_OVERLAP_PMC10448002.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    source["_source_case_path"] = str(source_path)
    base = [
        with_day(o, 0.0)
        for o in source["observations"]
        if o.get("axis_id") != "active_serious_infection_activity"
    ]
    for item in base:
        if item.get("axis_id") in {"proteinuria_activity", "hematuria_activity"}:
            item["day"] = -5.0
            item["available_at_day"] = -5.0
    # This positive test was already available before admission and caused the
    # referral.  The active case used a non-registry alias, so the staged replay
    # uses the current neutral registry axis without changing any manifold.
    base.append({
        "day": 0,
        "available_at_day": 0,
        "axis_id": "anti_gbm_antibody_positivity_probability",
        "value": 1.0,
        "unit": "probability_0_1",
        "category": "lab_finding",
        "axis_role": "measurement",
        "source_text_value": "elevated IgG anti-GBM antibody titer discovered before admission",
        "available_at_presentation": True,
        "use_in_ranking": True,
    })
    early = copy.deepcopy(source["early_course_observations"])
    complement = []
    for item in source["complement_and_hemolysis_context"]:
        if item.get("axis_id") == "schistocyte_fraction":
            complement.append({
                "day": 6.5,
                "available_at_day": 6.5,
                "axis_id": "schistocytes_presence",
                "value": 1.0,
                "unit": "present_absent_0_1",
                "category": "lab_finding",
                "axis_role": "finding",
                "source_text_value": "peripheral blood smear was notable for target cells and schistocytes",
                "use_in_ranking": True,
            })
        else:
            complement.append(with_day(item, 6.5))
    workup = [
        {
            "day": 6.5,
            "available_at_day": 6.5,
            "axis_id": "renal_biopsy_tma_confirmation_activity",
            "value": 1.0,
            "unit": "present_absent_0_1",
            "category": "pathology",
            "axis_role": "finding",
            "source_text_value": "preliminary renal biopsy showed acute TMA with no evidence of anti-GBM disease",
            "use_in_ranking": True,
        },
        {
            "day": 6.5,
            "available_at_day": 6.5,
            "axis_id": "adamts13_activity",
            "value": 61.0,
            "unit": "percent",
            "category": "lab_value",
            "axis_role": "measurement",
            "source_text_value": "ADAMTS13 activity 61%, excluding severe deficiency",
            "use_in_ranking": True,
        },
        {
            "day": 6.5,
            "available_at_day": 6.5,
            "axis_id": "hit_panel_positive_activity",
            "value": 0.0,
            "unit": "present_absent_0_1",
            "category": "lab_finding",
            "axis_role": "finding",
            "source_text_value": "heparin-induced thrombocytopenia panel was negative",
            "use_in_ranking": True,
        },
    ]
    actions = [
        {"day": 0, "action": "plasmapheresis_initiation_for_presumed_anti_gbm", "source_text_value": "plasmapheresis initiated on admission"},
        {"day": 0, "action": "high_dose_intravenous_corticosteroids", "source_text_value": "high-dose intravenous steroids started for presumed anti-GBM disease"},
        {"day": 0, "action": "apixaban_to_heparin_bridge", "source_text_value": "apixaban was replaced by a heparin drip on admission while biopsy was scheduled after washout"},
        {"day": 3, "action": "renal_biopsy", "source_text_value": "renal biopsy performed after apixaban washout"},
        {"order_after_workup": True, "action": "rituximab", "source_text_value": "rituximab added after TMA diagnosis; exact day not reported"},
        {"order_after_workup": True, "action": "eculizumab", "source_text_value": "eculizumab added after TMA diagnosis; exact day not reported"},
        {"order_after_workup": True, "action": "heparin_bridge_to_chronic_warfarin", "source_text_value": "after HIT was excluded, heparin was used to bridge to chronic warfarin; exact day not reported"},
        {"order_after_workup": True, "action": "slow_prednisone_taper", "source_text_value": "a slow prednisone taper was started; exact day not reported"},
        {"order_after_workup": True, "action": "daily_plasmapheresis_continuation", "source_text_value": "plasmapheresis continued daily during hospitalization; exact session dates not reported"},
    ]

    specs = [
        (0, 0.0, "admission for positive anti-GBM antibody before biopsy", "admission"),
        (1, 4.0, "day 4 after renal biopsy: hematoma, worsening anemia and thrombocytopenia", "post_biopsy"),
        (2, 6.0, "day 6: early platelet and hemoglobin improvement before reported preliminary-biopsy workup", "early_response"),
        (3, 6.5, "post-day-6 ordering cut: biopsy TMA, complement consumption, hemolysis, ADAMTS13 61%", "workup_available"),
        (4, 15.0, "day 15 discharge; creatinine improving but no exact value reported", "discharge"),
    ]
    paths = []
    for order, day, label, phase in specs:
        case = staged_base(
            source,
            case_id=f"PMC10448002_CM_TMA_REVERSAL_CUT_{order:02d}",
            snapshot_day=day,
            label=label,
            expected="D-COMPLEMENT-MEDIATED-TMA",
        )
        case["time_uncertainty"] = (
            "The paper reports two days of hematologic improvement before the preliminary biopsy/complement work-up. "
            "Exact result times are absent; day 6.5 is an ordering coordinate, not an asserted clock time."
            if day >= 6.5 else None
        )
        if day >= 6.5:
            # At this cut the post-biopsy pathology/hemolysis work-up is now
            # explicitly available.  Keeping presentation mode here would
            # silently discard the very evidence that reversed the diagnosis.
            case["diagnostic_stage"] = "post_workup"
            case["ranking_evidence_mode"] = "all_available"
        case["observations"] = copy.deepcopy(base)
        if day >= 4:
            case["course_observations"] = [with_day(o, float(o.get("day", 4))) for o in early if float(o.get("day", 99)) <= min(day, 4)]
        else:
            case["course_observations"] = []
        if day >= 6.5:
            case["course_observations"].extend(copy.deepcopy(complement + workup))
        if day >= 6:
            for item in early:
                if float(item.get("day", -1)) == 6.0:
                    observed = with_day(item, 6.0)
                    observed["use_in_ranking"] = True
                    case["course_observations"].append(observed)
        case["action_history"] = [
            a for a in actions
            if (a.get("day") is not None and float(a["day"]) <= day)
            or (a.get("order_after_workup") and day >= 15)
        ]
        if day >= 2:
            case["record_only"].append({
                "day": 2,
                "event": "no_new_symptoms_reported_first_two_hospital_days",
                "source_text_value": "developed no new symptoms during the first two hospital days",
                "rankable": False,
                "note": "Not equivalent to a diagnosis-neutral negative infection finding.",
            })
        if day >= 6.5:
            case["record_only"].append({
                "day": 6.5,
                "event": "renal_biopsy_did_not_support_anti_gbm_disease",
                "source_text_value": "preliminary renal biopsy showed no evidence of anti-GBM disease",
                "rankable": False,
                "note": "The paper does not report a specific linear-GBM IgG stain result; do not invent one.",
            })
        if phase == "discharge":
            case["record_only"].append({
                "day": 15,
                "event": "discharge_with_improving_creatinine",
                "source_text_value": "discharged after 15 days with no new symptoms and creatinine trending downward; no exact value reported",
                "rankable": False,
            })
        paths.append(write_case(case, "PMC10448002", order, f"PMC10448002_{phase.upper()}"))
    return paths


def main() -> None:
    # Generated cuts are disposable research artifacts.  Remove stale names so
    # a changed cut schedule cannot be scored twice by a later glob/read.
    for family in ("PMC10448002", "PMC7005653"):
        directory = OUT / family
        if directory.exists():
            for path in directory.glob("v5_case_*.json"):
                path.unlink()
    paths = build_tma() + build_hav()
    manifest = {
        "generated_files": [str(p) for p in paths],
        "active_atlas_modified": False,
        "case_distillations_modified": False,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(paths)} staged case files under {OUT}")


if __name__ == "__main__":
    main()
