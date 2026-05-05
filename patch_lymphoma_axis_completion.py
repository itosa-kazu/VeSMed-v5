from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DISTILL = ROOT / "distillations"
CASE_DIR = DISTILL / "cases"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upsert_by_id(items: list[dict], key: str, item: dict) -> None:
    value = item[key]
    for i, existing in enumerate(items):
        if existing.get(key) == value:
            merged = dict(existing)
            merged.update({k: v for k, v in item.items() if v is not None})
            items[i] = merged
            return
    items.append(item)


def edge_key(edge: dict) -> tuple:
    return (
        edge.get("source_id"),
        edge.get("target_id"),
        edge.get("effect_on_target"),
        edge.get("edge_type"),
    )


def upsert_edge(edges: list[dict], edge: dict) -> None:
    key = edge_key(edge)
    for i, existing in enumerate(edges):
        if edge_key(existing) == key:
            merged = dict(existing)
            merged.update({k: v for k, v in edge.items() if v is not None})
            edges[i] = merged
            return
    edges.append(edge)


def remove_edges(edges: list[dict], *, source: str | None = None, targets: set[str] | None = None) -> list[dict]:
    kept = []
    for edge in edges:
        if source is not None and edge.get("source_id") != source:
            kept.append(edge)
            continue
        if targets is not None and edge.get("target_id") not in targets:
            kept.append(edge)
            continue
    return kept


def axis(
    axis_id: str,
    *,
    display_name: str,
    category: str,
    unit: str,
    baseline: list[float],
    peak: list[float],
    peak_day: list[float],
    role: str = "finding",
    parent: str | None = None,
    log_scale: bool = False,
    shape: str,
    confidence: str = "medium",
) -> dict:
    return {
        "axis_id": axis_id,
        "display_name": display_name,
        "category": category,
        "axis_role": role,
        "parent_axis_id": parent,
        "unit": unit,
        "log_scale": log_scale,
        "baseline_range": baseline,
        "peak_day_range": peak_day,
        "peak_value_range": peak,
        "plateau_duration_days": [7, 90],
        "decline_half_life_days": [7, 60],
        "shape_free_text": shape,
        "knowledge_confidence": confidence,
    }


def mechanism(
    mechanism_id: str,
    *,
    display_name: str,
    clinical_meaning: str,
    baseline: list[float],
    peak: list[float],
    peak_day: list[float],
    confidence: str = "medium",
) -> dict:
    return {
        "mechanism_id": mechanism_id,
        "display_name": display_name,
        "clinical_meaning": clinical_meaning,
        "unit": "relative_activity_0_1",
        "log_scale": False,
        "baseline_range": baseline,
        "peak_day_range": peak_day,
        "peak_value_range": peak,
        "plateau_duration_days": [14, 180],
        "decline_half_life_days": [14, 90],
        "knowledge_confidence": confidence,
    }


def edge(
    source: str,
    target: str,
    effect: str,
    *,
    rationale: str,
    edge_type: str = "mechanism_to_axis",
    lag: list[float] | None = None,
    phase: str = "whole_course",
    conditionality: str | None = None,
    confidence: str = "medium",
) -> dict:
    return {
        "source_id": source,
        "target_id": target,
        "effect_on_target": effect,
        "edge_type": edge_type,
        "lag_days_range": lag if lag is not None else [0, 30],
        "phase": phase,
        "conditionality": conditionality,
        "clinical_rationale": rationale,
        "knowledge_confidence": confidence,
    }


def add_observation(case: dict, obs: dict) -> None:
    observations = case.setdefault("observations", [])
    for existing in observations:
        if existing.get("axis_id") == obs.get("axis_id") and existing.get("source_text_value") == obs.get("source_text_value"):
            existing.update(obs)
            return
    observations.append(obs)


def patch_distillation(filename: str, axes: list[dict], edges: list[dict], mechanisms: list[dict] | None = None) -> None:
    path = DISTILL / filename
    data = load_json(path)
    data.setdefault("latent_mechanisms", [])
    data.setdefault("mechanism_edges", [])
    data.setdefault("axes", [])
    for mech in mechanisms or []:
        upsert_by_id(data["latent_mechanisms"], "mechanism_id", mech)
    for ax in axes:
        upsert_by_id(data["axes"], "axis_id", ax)
    for ed in edges:
        upsert_edge(data["mechanism_edges"], ed)
    save_json(path, data)


def common_course_axes(peak_antibiotic: list[float] = [0.2, 1.0]) -> list[dict]:
    return [
        axis(
            "fever_history_activity",
            display_name="Persistent or recurrent fever history",
            category="clinical_course_context",
            unit="severity_score_0_1",
            baseline=[0, 0.05],
            peak=[0.2, 1.0],
            peak_day=[0, 180],
            shape="History-level fever burden over days to months, distinct from a single measured body temperature.",
            confidence="medium",
        ),
        axis(
            "antibiotic_nonresponse_activity",
            display_name="Lack of clinical response to standard antibacterial therapy",
            category="clinical_course_context",
            unit="relative_activity_0_1",
            baseline=[0, 0.05],
            peak=peak_antibiotic,
            peak_day=[2, 60],
            shape="Persistent fever, inflammation, or organ findings despite antibacterial therapy that should have covered ordinary bacterial infection.",
            confidence="medium",
        ),
    ]


def respiratory_axes(peak_dyspnea: list[float], peak_cough: list[float]) -> list[dict]:
    return [
        axis(
            "dyspnea_activity",
            display_name="Dyspnea / breathlessness activity",
            category="physical_finding",
            unit="severity_score_0_1",
            baseline=[0, 0.05],
            peak=peak_dyspnea,
            peak_day=[0, 180],
            shape="Patient-reported or observed breathlessness from pulmonary, cardiac, mediastinal, anemia, or systemic inflammatory involvement.",
            confidence="medium",
        ),
        axis(
            "cough_activity",
            display_name="Cough activity",
            category="physical_finding",
            unit="severity_score_0_1",
            baseline=[0, 0.05],
            peak=peak_cough,
            peak_day=[0, 180],
            shape="Dry or productive cough as a symptom axis; mechanism depends on pulmonary, airway, cardiac, or mediastinal involvement.",
            confidence="medium",
        ),
    ]


def lymphoma_shared_axes() -> list[dict]:
    return (
        common_course_axes([0.3, 1.0])
        + respiratory_axes([0, 0.6], [0, 0.5])
        + [
            axis(
                "blood_culture_positivity_probability",
                display_name="Blood culture positivity probability",
                category="microbiology_context",
                unit="probability_0_1",
                baseline=[0, 0.03],
                peak=[0, 0.08],
                peak_day=[0, 30],
                shape="Probability that standard blood cultures grow a causative bacterium; expected to remain low in uncomplicated lymphoma fever.",
                confidence="medium",
            )
        ]
    )


def patch_lymphoma_family() -> None:
    lymphoma_files = {
        "v5_D-ALCL.json": {
            "cytokine": "lymphoma_b_symptom_cytokine_activity",
            "tumor": "lymphoma_tumor_burden_activity",
            "resp": "M_ALCL_EXTRANODAL_VISCERAL_INFILTRATION",
        },
        "v5_D-HODGKIN-LYMPHOMA.json": {
            "cytokine": "lymphoma_b_symptom_cytokine_activity",
            "tumor": "lymphoma_tumor_burden_activity",
            "resp": "reticuloendothelial_lymphoid_expansion_activity",
        },
        "v5_D-DLBCL.json": {
            "cytokine": "M_DLBCL_B_SYMPTOM_CYTOKINE_ACTIVITY",
            "tumor": "M_DLBCL_TUMOR_BURDEN",
            "resp": "M_DLBCL_EXTRANODAL_VISCERAL_INFILTRATION",
        },
        "v5_D-IVLBCL.json": {
            "cytokine": "M_IVLBCL_B_SYMPTOM_CYTOKINE",
            "tumor": "M_IVLBCL_INTRAVASCULAR_LYMPHOMA_PROLIFERATION",
            "resp": "M_IVLBCL_PULMONARY_INVOLVEMENT",
        },
    }
    for filename, sources in lymphoma_files.items():
        dyspnea_peak = [0.2, 0.95] if filename == "v5_D-IVLBCL.json" else [0, 0.6]
        cough_peak = [0.1, 0.8] if filename == "v5_D-IVLBCL.json" else [0, 0.5]
        axes = common_course_axes([0.3, 1.0]) + respiratory_axes(dyspnea_peak, cough_peak) + [
            axis(
                "blood_culture_positivity_probability",
                display_name="Blood culture positivity probability",
                category="microbiology_context",
                unit="probability_0_1",
                baseline=[0, 0.03],
                peak=[0, 0.08],
                peak_day=[0, 30],
                shape="Probability that standard blood cultures grow a causative bacterium; expected to remain low in uncomplicated lymphoma fever.",
                confidence="medium",
            )
        ]
        edges = [
            edge(
                sources["cytokine"],
                "fever_history_activity",
                "increase",
                rationale="Lymphoma cytokine activity produces recurrent or persistent fever over weeks to months.",
            ),
            edge(
                sources["cytokine"],
                "antibiotic_nonresponse_activity",
                "increase",
                rationale="Fever and inflammatory markers persist when the driver is lymphoma biology rather than ordinary bacterial infection.",
                lag=[2, 30],
            ),
            edge(
                sources["resp"],
                "dyspnea_activity",
                "increase",
                rationale="Pulmonary, mediastinal, extranodal, or microvascular lymphoma involvement can produce breathlessness.",
                conditionality="Most prominent with pulmonary IVLBCL, mediastinal bulky disease, pleural/pericardial involvement, or severe anemia.",
            ),
            edge(
                sources["resp"],
                "cough_activity",
                "increase",
                rationale="Pulmonary or mediastinal lymphoma involvement can produce cough.",
                conditionality="More likely with airway/mediastinal compression or pulmonary infiltration.",
            ),
            edge(
                sources["tumor"],
                "blood_culture_positivity_probability",
                "decrease",
                rationale="Pure lymphoma fever does not produce bacterial bloodstream growth, although secondary infection can override this.",
            ),
        ]
        patch_distillation(filename, axes, edges)


def patch_alcl_inflammatory_neutrophilia() -> None:
    axes = [
        axis(
            "absolute_neutrophil_count",
            display_name="Absolute neutrophil count",
            category="lab_value",
            unit="10^9/L",
            role="measurement",
            baseline=[2, 7],
            peak=[1, 25],
            peak_day=[0, 180],
            shape="Untreated systemic ALCL can show cytokine-driven neutrophilia or leukemoid inflammation; marrow infiltration or chemotherapy can later drive neutropenia.",
            confidence="medium",
        )
    ]
    edges = [
        edge(
            "lymphoma_b_symptom_cytokine_activity",
            "absolute_neutrophil_count",
            "increase",
            rationale="Systemic ALCL can produce IL-6/G-CSF-like inflammatory neutrophilia before chemotherapy.",
            confidence="medium",
        )
    ]
    patch_distillation("v5_D-ALCL.json", axes, edges)


def patch_dlbcl_primary_splenic() -> None:
    axes = [
        axis(
            "erythrocyte_sedimentation_rate",
            display_name="Erythrocyte sedimentation rate",
            category="lab_value",
            unit="mm_per_hr",
            role="measurement",
            baseline=[0, 20],
            peak=[30, 140],
            peak_day=[0, 90],
            shape="Often elevated in inflammatory or B-symptomatic DLBCL; reflects cytokine-driven acute-phase proteins and anemia.",
            confidence="high",
        ),
        axis(
            "primary_splenic_dlbcl_pattern_activity",
            display_name="Primary splenic DLBCL-dominant imaging pattern",
            category="imaging_pattern",
            unit="relative_activity_0_1",
            role="satellite",
            parent="splenic_lesion_presence",
            baseline=[0, 0.01],
            peak=[0.2, 1.0],
            peak_day=[0, 90],
            shape="Dominant splenic mass/nodular splenic infiltration with absent or minimal nodal disease at presentation.",
            confidence="medium",
        )
    ]
    mechanisms = [
        mechanism(
            "M_DLBCL_NODAL_DISTRIBUTION",
            display_name="Nodal DLBCL distribution",
            clinical_meaning="An anatomic distribution of DLBCL in which disease is expressed as pathologic lymphadenopathy or nodal mass. This is common, but it is not required for extranodal or primary splenic DLBCL.",
            baseline=[0, 0.03],
            peak=[0, 0.95],
            peak_day=[0, 90],
            confidence="high",
        ),
        mechanism(
            "M_DLBCL_PRIMARY_SPLENIC_EXTRANODAL_PATTERN",
            display_name="Primary splenic / isolated extranodal DLBCL distribution",
            clinical_meaning="An anatomic distribution of DLBCL in which disease is dominated by splenic parenchymal involvement and may lack clinically apparent lymphadenopathy. It explains abdominal pain, early satiety, splenomegaly, splenic nodules, high LDH, and the absence of nodal disease without excluding DLBCL.",
            baseline=[0, 0.01],
            peak=[0.2, 0.95],
            peak_day=[0, 90],
            confidence="medium",
        )
    ]
    edges = [
        edge("M_DLBCL_B_SYMPTOM_CYTOKINE_ACTIVITY", "erythrocyte_sedimentation_rate", "increase", rationale="DLBCL-associated IL-6/acute-phase activity and anemia can markedly raise ESR.", confidence="high"),
        edge("M_DLBCL_NODAL_DISTRIBUTION", "pathologic_lymphadenopathy_presence", "increase", rationale="Nodal-distribution DLBCL is observed as pathologic lymph node enlargement.", confidence="high"),
        edge("M_DLBCL_NODAL_DISTRIBUTION", "lymphadenopathy_activity", "increase", rationale="Nodal-distribution DLBCL produces palpable or imaging-visible lymphadenopathy.", confidence="high"),
        edge("M_DLBCL_NODAL_DISTRIBUTION", "mediastinal_lymphadenopathy_activity", "increase", rationale="Mediastinal nodes are one possible nodal compartment in DLBCL.", conditionality="Only when nodal DLBCL involves mediastinum.", confidence="medium"),
        edge("M_DLBCL_NODAL_DISTRIBUTION", "deep_abdominal_lymphadenopathy_activity", "increase", rationale="Retroperitoneal, mesenteric, or abdominal nodal disease reflects nodal DLBCL distribution.", conditionality="Only when nodal DLBCL involves deep abdominal nodes.", confidence="medium"),
        edge("M_DLBCL_NODAL_DISTRIBUTION", "bulky_nodal_mass_activity", "increase", rationale="High nodal burden can form bulky nodal conglomerates.", conditionality="Only when nodal disease is bulky.", confidence="medium"),
        edge("M_DLBCL_NODAL_DISTRIBUTION", "largest_nodal_mass_diameter_cm", "increase", rationale="Measured nodal mass diameter is a satellite of nodal-distribution DLBCL.", conditionality="Only when a nodal mass is measured.", confidence="medium"),
        edge("M_DLBCL_PRIMARY_SPLENIC_EXTRANODAL_PATTERN", "primary_splenic_dlbcl_pattern_activity", "increase", rationale="This mechanism is the imaging distribution axis itself.", confidence="medium"),
        edge("M_DLBCL_PRIMARY_SPLENIC_EXTRANODAL_PATTERN", "splenic_lesion_presence", "increase", rationale="Primary splenic DLBCL presents with focal or multinodular splenic lesions.", confidence="high"),
        edge("M_DLBCL_PRIMARY_SPLENIC_EXTRANODAL_PATTERN", "splenic_lesion_burden", "increase", rationale="Dominant splenic involvement increases splenic lesion burden.", confidence="high"),
        edge("M_DLBCL_PRIMARY_SPLENIC_EXTRANODAL_PATTERN", "splenic_long_axis_cm", "increase", rationale="Bulky splenic infiltration can enlarge the spleen substantially.", confidence="high"),
        edge("M_DLBCL_PRIMARY_SPLENIC_EXTRANODAL_PATTERN", "splenomegaly_activity", "increase", rationale="Splenic parenchymal infiltration produces palpable and imaging-defined splenomegaly.", confidence="high"),
        edge("M_DLBCL_PRIMARY_SPLENIC_EXTRANODAL_PATTERN", "extranodal_lesion_presence", "increase", rationale="Primary splenic disease is an extranodal presentation of DLBCL.", confidence="high"),
        edge("M_DLBCL_PRIMARY_SPLENIC_EXTRANODAL_PATTERN", "pathologic_lymphadenopathy_presence", "decrease", rationale="By definition, primary splenic DLBCL can present without clinically apparent nodal disease.", confidence="medium"),
        edge("M_DLBCL_PRIMARY_SPLENIC_EXTRANODAL_PATTERN", "lymphadenopathy_activity", "decrease", rationale="Nodal activity may be absent in isolated primary splenic presentations.", confidence="medium"),
        edge("M_DLBCL_PRIMARY_SPLENIC_EXTRANODAL_PATTERN", "abdominal_pain_activity", "increase", rationale="Splenic capsular stretch and mass effect can cause left upper abdominal pain.", confidence="medium"),
        edge("M_DLBCL_PRIMARY_SPLENIC_EXTRANODAL_PATTERN", "early_satiety_activity", "increase", rationale="Large splenomegaly can compress the stomach and cause early satiety.", confidence="medium"),
    ]
    path = DISTILL / "v5_D-DLBCL.json"
    data = load_json(path)
    data["mechanism_edges"] = remove_edges(
        data.get("mechanism_edges", []),
        source="M_DLBCL_TUMOR_BURDEN",
        targets={
            "pathologic_lymphadenopathy_presence",
            "lymphadenopathy_activity",
            "mediastinal_lymphadenopathy_activity",
            "deep_abdominal_lymphadenopathy_activity",
            "bulky_nodal_mass_activity",
            "largest_nodal_mass_diameter_cm",
        },
    )
    save_json(path, data)
    patch_distillation("v5_D-DLBCL.json", axes, edges, mechanisms)


def patch_hodgkin_inflammatory_mimic() -> None:
    axes = [
        axis(
            "antiinflammatory_treatment_nonresponse_activity",
            display_name="Persistent inflammatory syndrome despite anti-inflammatory/immunosuppressive treatment",
            category="clinical_course_context",
            unit="relative_activity_0_1",
            baseline=[0, 0.05],
            peak=[0.2, 1.0],
            peak_day=[7, 90],
            shape="Failure of fever, cytopenia/anemia, lymphadenopathy, or acute-phase reactants to resolve with glucocorticoid or conventional anti-inflammatory immunosuppression before a tissue diagnosis.",
            confidence="medium",
        ),
        axis(
            "arthritis_activity",
            display_name="Inflammatory arthritis activity",
            category="physical_finding",
            unit="severity_score_0_1",
            baseline=[0, 0.03],
            peak=[0, 0.45],
            peak_day=[14, 180],
            shape="Paraneoplastic inflammatory arthralgia or arthritis can occur in Hodgkin lymphoma but is less central than in AOSD.",
            confidence="low",
        ),
        axis(
            "myalgia_activity",
            display_name="Myalgia activity",
            category="physical_finding",
            unit="severity_score_0_1",
            baseline=[0, 0.05],
            peak=[0, 0.5],
            peak_day=[14, 180],
            shape="Constitutional cytokine-driven muscle pain can accompany Hodgkin lymphoma inflammatory presentations.",
            confidence="low",
        ),
        axis(
            "pericardial_effusion_activity",
            display_name="Pericardial effusion activity",
            category="imaging_finding",
            unit="severity_score_0_1",
            baseline=[0, 0.02],
            peak=[0, 0.5],
            peak_day=[30, 180],
            shape="Small to moderate pericardial effusion from mediastinal lymphoma, lymphatic obstruction, or serosal inflammation.",
            confidence="medium",
        ),
        axis(
            "serum_potassium",
            display_name="Serum potassium",
            category="lab_value",
            unit="mmol/L",
            role="measurement",
            baseline=[3.5, 5.0],
            peak=[3.0, 6.5],
            peak_day=[0, 14],
            shape="Usually normal in untreated Hodgkin lymphoma; can rise with tumor lysis risk or fall with poor intake, renal handling, or treatment context.",
            confidence="medium",
        ),
    ]
    edges = [
        edge("lymphoma_b_symptom_cytokine_activity", "antiinflammatory_treatment_nonresponse_activity", "increase", rationale="Steroids or conventional anti-inflammatory treatment may transiently blunt symptoms but do not remove the Hodgkin tumor driver.", lag=[7, 60], confidence="medium"),
        edge("lymphoma_b_symptom_cytokine_activity", "arthritis_activity", "increase", rationale="Hodgkin lymphoma can rarely mimic autoinflammatory disease through paraneoplastic inflammatory arthralgia or arthritis.", confidence="low"),
        edge("lymphoma_b_symptom_cytokine_activity", "myalgia_activity", "increase", rationale="Cytokine-driven constitutional inflammation can produce myalgia.", confidence="low"),
        edge("reticuloendothelial_lymphoid_expansion_activity", "pericardial_effusion_activity", "increase", rationale="Mediastinal nodal disease can cause pericardial involvement or lymphatic obstruction.", confidence="medium"),
        edge("reticuloendothelial_lymphoid_expansion_activity", "bulky_nodal_mass_activity", "increase", rationale="Classical Hodgkin lymphoma, especially nodular sclerosis, commonly presents with bulky mediastinal nodal packets.", confidence="high"),
    ]
    patch_distillation("v5_D-HODGKIN-LYMPHOMA.json", axes, edges)


def patch_ivlbcl_occult_pattern() -> None:
    axes = [
        axis(
            "pathologic_lymphadenopathy_presence",
            display_name="Pathologic lymphadenopathy presence",
            category="imaging_finding",
            unit="present_absent_0_1",
            role="finding",
            baseline=[0, 0.01],
            peak=[0, 0.1],
            peak_day=[0, 240],
            shape="Clinically significant lymph-node enlargement; typically absent or minimal in IVLBCL despite systemic disease.",
            confidence="high",
        ),
        axis(
            "multiorgan_microvascular_lymphoma_pattern_activity",
            display_name="Occult multiorgan microvascular lymphoma pattern",
            category="clinical_pattern",
            unit="relative_activity_0_1",
            role="satellite",
            parent=None,
            baseline=[0, 0.02],
            peak=[0.2, 0.95],
            peak_day=[30, 240],
            shape="Fever with neurologic, pulmonary, renal, hepatic, marrow, or adrenal dysfunction out of proportion to nodal or mass lesions.",
            confidence="high",
        ),
    ]
    edges = [
        edge("M_IVLBCL_DEFECTIVE_HOMING_CD29_CD54", "pathologic_lymphadenopathy_presence", "decrease", rationale="Defective homing/extravasation keeps malignant cells intravascular and prevents ordinary nodal mass formation.", confidence="high"),
        edge("M_IVLBCL_DEFECTIVE_HOMING_CD29_CD54", "lymphadenopathy_activity", "decrease", rationale="Absence of clinically apparent lymphadenopathy is a classic IVLBCL clue.", confidence="high"),
        edge("M_IVLBCL_INTRAVASCULAR_LYMPHOMA_PROLIFERATION", "multiorgan_microvascular_lymphoma_pattern_activity", "increase", rationale="Intravascular lymphoma can involve brain, lung, kidney, liver, spleen, marrow, skin, and adrenal vessels without a dominant mass.", confidence="high"),
        edge("M_IVLBCL_MICROVASCULAR_OCCLUSION_ISCHEMIA", "multiorgan_microvascular_lymphoma_pattern_activity", "increase", rationale="Patchy organ dysfunction from microvascular occlusion creates the occult multisystem pattern.", confidence="high"),
        edge("M_IVLBCL_DIAGNOSTIC_DELAY", "antibiotic_nonresponse_activity", "increase", rationale="FUO or pulmonary IVLBCL is frequently treated as infection before tissue diagnosis, with no true antibacterial response.", lag=[3, 60], confidence="high"),
        edge("M_IVLBCL_PULMONARY_INVOLVEMENT", "dyspnea_activity", "increase", rationale="Pulmonary capillary lymphoma produces exertional dyspnea and hypoxemia.", confidence="high"),
        edge("M_IVLBCL_PULMONARY_INVOLVEMENT", "cough_activity", "increase", rationale="Diffuse interstitial or ground-glass pulmonary involvement can produce dry cough.", confidence="medium"),
    ]
    patch_distillation("v5_D-IVLBCL.json", axes, edges)


def patch_mimic_fairness_axes() -> None:
    configs = {
        "v5_D137.json": {
            "source": "aosd_autoinflammatory_cytokine_activity",
            "antibiotic_peak": [0.4, 1.0],
            "extra_axes": [],
            "rationale": "AOSD often presents as antibiotic-refractory fever because the driver is sterile autoinflammation.",
        },
        "v5_D-TB-DISSEMINATED.json": {
            "source": "mtb_pathogen_burden_activity",
            "antibiotic_peak": [0.3, 1.0],
            "extra_axes": respiratory_axes([0.1, 0.8], [0.2, 0.9]),
            "rationale": "Ordinary antibacterial regimens do not treat disseminated TB; pulmonary disease drives cough and dyspnea.",
        },
        "v5_D-DRUG-FEVER-DRESS.json": {
            "source": "infection_mimic_activity",
            "antibiotic_peak": [0.2, 0.9],
            "extra_axes": respiratory_axes([0, 0.7], [0, 0.6]),
            "rationale": "DRESS may be misread as infection and fail to improve until the culprit drug is stopped and immune injury controlled.",
        },
        "v5_D-MIS-A.json": {
            "source": "infection_mimic_activity",
            "antibiotic_peak": [0.2, 0.9],
            "extra_axes": respiratory_axes([0, 0.7], [0, 0.5]),
            "rationale": "MIS-A can mimic sepsis but is driven by delayed post-infectious hyperinflammation.",
        },
        "v5_D-HLH-MAS.json": {
            "source": "macrophage_activation_activity",
            "antibiotic_peak": [0.2, 0.9],
            "extra_axes": respiratory_axes([0, 0.7], [0, 0.5]),
            "rationale": "HLH/MAS fever may persist despite antibacterial therapy unless the trigger and immune activation are controlled.",
        },
        "v5_D-SLE-FLARE.json": {
            "source": "infection_mimic_activity",
            "antibiotic_peak": [0.1, 0.7],
            "extra_axes": respiratory_axes([0, 0.8], [0, 0.5]),
            "rationale": "SLE flare, pneumonitis, or serositis can mimic infection and persist despite antibiotics.",
        },
        "v5_D-GPA.json": {
            "source": "M_GPA_GRANULOMATOUS_INFLAMMATION",
            "antibiotic_peak": [0.2, 0.9],
            "extra_axes": respiratory_axes([0.1, 0.8], [0.2, 0.9]),
            "rationale": "Pulmonary/ENT GPA is commonly treated as infection before vasculitis is recognized.",
        },
        "v5_D-MPA.json": {
            "source": "M_PULMONARY_CAPILLARITIS",
            "antibiotic_peak": [0.2, 0.9],
            "extra_axes": respiratory_axes([0.1, 0.9], [0.1, 0.7]),
            "rationale": "MPA pulmonary capillaritis or ILD can mimic pneumonia but does not respond to antibacterial therapy.",
        },
        "v5_D-EGPA.json": {
            "source": "M_EGPA_EOSINOPHIL_RICH_GRANULOMATOUS_INFLAMMATION",
            "antibiotic_peak": [0.2, 0.9],
            "extra_axes": respiratory_axes([0.1, 0.9], [0.2, 0.9]),
            "rationale": "EGPA asthma/eosinophilic lung disease is often misread as infection before eosinophilic vasculitis is recognized.",
        },
        "v5_D-INFECTIOUS-MONONUCLEOSIS.json": {
            "source": "cd8_reactive_lymphocyte_expansion_activity",
            "antibiotic_peak": [0.2, 0.8],
            "extra_axes": [],
            "rationale": "EBV infectious mononucleosis does not respond to antibacterial therapy.",
        },
    }
    for filename, cfg in configs.items():
        path = DISTILL / filename
        if not path.exists():
            continue
        if filename == "v5_D-INFECTIOUS-MONONUCLEOSIS.json":
            data = load_json(path)
            data["mechanism_edges"] = [
                e
                for e in data.get("mechanism_edges", [])
                if e.get("source_id") != "ebv_t_cell_immune_activation_activity"
                and e.get("target_id") != "lymphoma_tumor_burden_activity"
            ]
            save_json(path, data)
        axes = common_course_axes(cfg["antibiotic_peak"]) + cfg["extra_axes"]
        edges = [
            edge(cfg["source"], "fever_history_activity", "increase", rationale="The disease can present with persistent or recurrent fever over the observed clinical history."),
            edge(cfg["source"], "antibiotic_nonresponse_activity", "increase", rationale=cfg["rationale"], lag=[2, 60]),
        ]
        if any(a["axis_id"] == "dyspnea_activity" for a in cfg["extra_axes"]):
            edges.append(edge(cfg["source"], "dyspnea_activity", "increase", rationale="Pulmonary, cardiac, serosal, anemia, or systemic inflammatory involvement can cause dyspnea.", confidence="medium"))
        if any(a["axis_id"] == "cough_activity" for a in cfg["extra_axes"]):
            edges.append(edge(cfg["source"], "cough_activity", "increase", rationale="Pulmonary or airway involvement can cause cough.", confidence="medium"))
        patch_distillation(filename, axes, edges)


def patch_cases() -> None:
    dlbcl_case = CASE_DIR / "v5_case_DLBCL_PRIMARY_SPLENIC_PMC10348431.json"
    case = load_json(dlbcl_case)
    add_observation(
        case,
        {
            "axis_id": "primary_splenic_dlbcl_pattern_activity",
            "value": 1.0,
            "unit": "relative_activity_0_1",
            "source_text_value": "primary splenic DLBCL with multinodular splenic involvement and absence of other organs' involvement",
        },
    )
    save_json(dlbcl_case, case)

    hodgkin_case = CASE_DIR / "v5_case_HODGKIN_AOSD_MASK_PMC4847271.json"
    case = load_json(hodgkin_case)
    add_observation(
        case,
        {
            "axis_id": "antiinflammatory_treatment_nonresponse_activity",
            "value": 1.0,
            "unit": "relative_activity_0_1",
            "day": 42,
            "source_text_value": "After steroid and immunosuppressive treatment, inflammatory markers and anemia persisted before lymph node biopsy",
        },
    )
    add_observation(
        case,
        {
            "axis_id": "bulky_nodal_mass_activity",
            "value": 0.6,
            "unit": "relative_activity_0_1",
            "day": 42,
            "source_text_value": "widened mediastinum and lymph node packets in computed scan of the chest",
        },
    )
    save_json(hodgkin_case, case)

    ivlbcl_ams_case = CASE_DIR / "v5_case_IVLBCL_AMS_MULTIORGAN_PMC6935686.json"
    case = load_json(ivlbcl_ams_case)
    add_observation(
        case,
        {
            "axis_id": "pathologic_lymphadenopathy_presence",
            "value": 0.0,
            "unit": "present_absent_0_1",
            "source_text_value": "there was no lymphadenopathy",
        },
    )
    add_observation(
        case,
        {
            "axis_id": "multiorgan_microvascular_lymphoma_pattern_activity",
            "value": 1.0,
            "unit": "relative_activity_0_1",
            "source_text_value": "multiorgan IVLBCL involving brain, kidneys, liver, spleen, and lungs with no lymphadenopathy",
        },
    )
    save_json(ivlbcl_ams_case, case)


def main() -> None:
    patch_lymphoma_family()
    patch_alcl_inflammatory_neutrophilia()
    patch_dlbcl_primary_splenic()
    patch_hodgkin_inflammatory_mimic()
    patch_ivlbcl_occult_pattern()
    patch_mimic_fairness_axes()
    patch_cases()


if __name__ == "__main__":
    main()
