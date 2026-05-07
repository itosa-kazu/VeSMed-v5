"""
V5 joint SDE case ranking test.

This is the first full-vector runtime for current V5 distillations:
  - state x is a joint vector over observed axes
  - per-disease vector fields are superposed for comorbidity candidates
  - axis_couplings become a correlated diffusion / covariance matrix
  - risk_factors modulate prior, axis response, sigma, and coupling strength

For case ranking we score a presentation snapshot by marginalizing over latent
disease day(s). The endpoint likelihood uses the Gaussian marginal of a
mean-reverting joint SDE in transformed axis space.
"""
import itertools
import json
import math
import os
import re
import sys
from pathlib import Path

import numpy as np
from scipy.special import logsumexp

import v5_background

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROOT = Path(__file__).parent.resolve()
DISTILL_DIR = ROOT / "distillations"
CASE_DIR = DISTILL_DIR / "cases"
RESULT_PATH = DISTILL_DIR / "joint_sde_case_test_result.txt"

MANIFOLD_ORDER_HINTS = ("D137", "D-SEPSIS-GN", "D-TTP")


def env_int(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value >= 0 else default


def env_bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def env_csv(name):
    raw = os.environ.get(name, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


MANIFOLD_FILTER = env_csv("VESMED_MANIFOLD_FILTER")
MANIFOLD_EXCLUDE = env_csv("VESMED_MANIFOLD_EXCLUDE")


def distillation_disease_id(path, data):
    disease = (data.get("disease") or "").strip()
    if disease:
        return disease
    stem = path.stem
    if stem.startswith("v5_"):
        return stem[3:]
    return stem


def is_manifold_distillation(data):
    if not isinstance(data, dict):
        return False
    if data.get("case_id"):
        return False
    if not (data.get("disease") or isinstance(data.get("axes"), list)):
        return False
    axes = data.get("axes")
    return isinstance(axes, list) and any(isinstance(axis, dict) and axis.get("axis_id") for axis in axes)


def manifold_order_key(item):
    label, _ = item
    try:
        return (MANIFOLD_ORDER_HINTS.index(label), "")
    except ValueError:
        return (len(MANIFOLD_ORDER_HINTS), label)


def discover_manifold_paths(distill_dir=DISTILL_DIR):
    """Discover current V5 disease manifolds from distillations/.

    Case JSON and archived files are not loaded: this scans only root
    distillations/v5_*.json and requires a disease distillation shape.
    """
    paths = {}
    for path in sorted(distill_dir.glob("v5_*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not is_manifold_distillation(data):
            continue
        disease_id = distillation_disease_id(path, data)
        if not disease_id:
            continue
        if MANIFOLD_FILTER and not any(token in disease_id or token in path.name for token in MANIFOLD_FILTER):
            continue
        if MANIFOLD_EXCLUDE and any(token in disease_id or token in path.name for token in MANIFOLD_EXCLUDE):
            continue
        if disease_id in paths:
            raise ValueError(f"Duplicate disease distillation id {disease_id!r}: {paths[disease_id]} and {path}")
        paths[disease_id] = path
    if not paths:
        raise RuntimeError(f"No V5 disease distillations found in {distill_dir}")
    return dict(sorted(paths.items(), key=manifold_order_key))


MANIFOLD_PATHS = discover_manifold_paths()

BACKGROUND_MODIFIERS = v5_background.load_background_modifiers()
CONDITION_SCOPE = v5_background.load_condition_scope()

T_MAX_BY_DISEASE = {
    "D137": 90.0,
    "D-SEPSIS-GN": 30.0,
    "D-TTP": 30.0,
}

N_MC = env_int("VESMED_N_MC", 2500)
SEED = 20260430
COMBO_LOG_PENALTY = -2.0
MAX_COMBO_SIZE = env_int("VESMED_MAX_COMBO_SIZE", 2)
CASE_FILTER = env_csv("VESMED_CASE_FILTER")
ONLY_COMBO_CASES = env_bool("VESMED_ONLY_COMBO_CASES", False)
SCORE_MODE = os.environ.get("VESMED_SCORE_MODE", "mc").strip().lower()
TIME_GRID_N = max(env_int("VESMED_TIME_GRID_N", 31), 1)
COMBO_ANCHOR_THRESHOLD = 2.0
COMBO_MISSING_ANCHOR_PENALTY = -60.0
PARENT_FINDING_PRESENT_THRESHOLD = 0.5
GENERIC_ANCHOR_MAX_AXIS_FRACTION = 0.12
GENERIC_ANCHOR_SCORE_CAP = 4.0

NOISE_COUPLING_TYPES = {"", "noise_correlation", "mixed"}
DRIFT_COUPLING_TYPES = {"drift", "hazard_drift", "event_transition", "mixed"}
LATENT_MECHANISM_CATEGORY = "latent_mechanism"


GENERIC_ANCHOR_EXCLUDED_CATEGORIES = {
    "derived_hazard",
    LATENT_MECHANISM_CATEGORY,
    "vital",
}

GENERIC_ANCHOR_LOW_SPECIFICITY_AXES = {
    "body_temperature",
    "heart_rate",
    "respiratory_rate",
    "systolic_blood_pressure",
    "diastolic_blood_pressure",
    "mean_arterial_pressure",
    "oxygen_saturation",
    "white_blood_cell_count",
    "absolute_neutrophil_count",
    "neutrophil_fraction",
    "lymphocyte_fraction",
    "serum_crp",
    "erythrocyte_sedimentation_rate",
    "serum_ldh",
    "serum_albumin",
    "serum_creatinine",
    "blood_urea_nitrogen",
    "serum_sodium",
    "serum_potassium",
    "serum_chloride",
}

_AXIS_MANIFOLD_FREQUENCY_CACHE = {}


HEALTHY_OVERRIDES = {
    "body_temperature": {"unit": "°C", "baseline_range": (36.5, 37.5), "log_scale": False},
    "heart_rate": {"unit": "beats_per_min", "baseline_range": (60.0, 90.0), "log_scale": False},
    "respiratory_rate": {"unit": "breaths_per_min", "baseline_range": (12.0, 20.0), "log_scale": False},
    "systolic_blood_pressure": {"unit": "mmHg", "baseline_range": (100.0, 140.0), "log_scale": False},
    "mean_arterial_pressure": {"unit": "mmHg", "baseline_range": (70.0, 100.0), "log_scale": False},
    "oxygen_saturation": {"unit": "%", "baseline_range": (95.0, 100.0), "log_scale": False},
    "urine_output": {"unit": "mL/kg/hr", "baseline_range": (0.5, 1.5), "log_scale": False},
    "white_blood_cell_count": {"unit": "10^9/L", "baseline_range": (4.0, 10.0), "log_scale": False},
    "absolute_neutrophil_count": {"unit": "10^9/L", "baseline_range": (2.0, 7.0), "log_scale": False},
    "neutrophil_fraction": {"unit": "percent", "baseline_range": (40.0, 75.0), "log_scale": False},
    "lymphocyte_fraction": {"unit": "percent", "baseline_range": (20.0, 45.0), "log_scale": False},
    "monocyte_fraction": {"unit": "percent", "baseline_range": (2.0, 10.0), "log_scale": False},
    "eosinophil_fraction": {"unit": "percent", "baseline_range": (0.0, 6.0), "log_scale": False},
    "basophil_fraction": {"unit": "percent", "baseline_range": (0.0, 2.0), "log_scale": False},
    "hemoglobin": {"unit": "g/dL", "baseline_range": (12.0, 17.0), "log_scale": False},
    "hematocrit": {"unit": "percent", "baseline_range": (36.0, 50.0), "log_scale": False},
    "platelet_count": {"unit": "10^9/L", "baseline_range": (150.0, 350.0), "log_scale": False},
    "serum_crp": {"unit": "mg/L", "baseline_range": (0.2, 5.0), "log_scale": True},
    "erythrocyte_sedimentation_rate": {"unit": "mm_per_hr", "baseline_range": (0.0, 20.0), "log_scale": False},
    "serum_procalcitonin": {"unit": "ng/mL", "baseline_range": (0.02, 0.1), "log_scale": True},
    "serum_lactate": {"unit": "mmol/L", "baseline_range": (0.5, 2.0), "log_scale": False},
    "serum_creatinine": {"unit": "mg/dL", "baseline_range": (0.6, 1.2), "log_scale": False},
    "blood_urea_nitrogen": {"unit": "mg/dL", "baseline_range": (7.0, 20.0), "log_scale": False},
    "serum_sodium": {"unit": "mmol/L", "baseline_range": (135.0, 145.0), "log_scale": False},
    "serum_potassium": {"unit": "mmol/L", "baseline_range": (3.5, 5.0), "log_scale": False},
    "serum_chloride": {"unit": "mmol/L", "baseline_range": (98.0, 107.0), "log_scale": False},
    "serum_bicarbonate": {"unit": "mmol/L", "baseline_range": (22.0, 29.0), "log_scale": False},
    "serum_calcium": {"unit": "mg/dL", "baseline_range": (8.5, 10.5), "log_scale": False},
    "serum_magnesium": {"unit": "mg/dL", "baseline_range": (1.7, 2.4), "log_scale": False},
    "serum_phosphate": {"unit": "mg/dL", "baseline_range": (2.5, 4.5), "log_scale": False},
    "thyroid_stimulating_hormone": {"unit": "mIU/L", "baseline_range": (0.4, 4.5), "log_scale": False},
    "left_ventricular_ejection_fraction": {"unit": "percent", "baseline_range": (55.0, 70.0), "log_scale": False},
    "serum_ferritin": {"unit": "ng/mL", "baseline_range": (20.0, 250.0), "log_scale": True},
    "serum_ldh": {"unit": "U/L", "baseline_range": (120.0, 240.0), "log_scale": True},
    "serum_ast": {"unit": "U/L", "baseline_range": (10.0, 40.0), "log_scale": False},
    "serum_alt": {"unit": "U/L", "baseline_range": (7.0, 56.0), "log_scale": False},
    "serum_albumin": {"unit": "g/dL", "baseline_range": (3.5, 5.0), "log_scale": False},
    "serum_bilirubin_total": {"unit": "mg/dL", "baseline_range": (0.3, 1.2), "log_scale": True},
    "serum_bilirubin_indirect": {"unit": "mg/dL", "baseline_range": (0.1, 1.0), "log_scale": True},
    "serum_haptoglobin": {"unit": "mg/dL", "baseline_range": (30.0, 200.0), "log_scale": False},
    "reticulocyte_count": {"unit": "10^9/L", "baseline_range": (25.0, 100.0), "log_scale": False},
    "schistocyte_fraction": {"unit": "percent_red_cells", "baseline_range": (0.0, 0.5), "log_scale": False},
    "adamts13_activity": {"unit": "percent_of_normal", "baseline_range": (50.0, 150.0), "log_scale": False},
    "anti_adamts13_igg_inhibitor_titer": {"unit": "BU", "baseline_range": (0.0, 0.4), "log_scale": False},
    "ultra_large_vwf_multimer_activity": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.1), "log_scale": False},
    "serum_fibrinogen": {"unit": "mg/dL", "baseline_range": (200.0, 400.0), "log_scale": False},
    "d_dimer": {"unit": "µg/mL_FEU", "baseline_range": (0.05, 0.5), "log_scale": True},
    "prothrombin_time_inr": {"unit": "INR", "baseline_range": (0.9, 1.2), "log_scale": False},
    "activated_partial_thromboplastin_time": {"unit": "seconds", "baseline_range": (25.0, 40.0), "log_scale": False},
    "blood_culture_positivity_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.02), "log_scale": False},
    "blood_culture_bacterial_load": {"unit": "CFU_per_mL", "baseline_range": (1e-9, 1e-6), "log_scale": True},
}


def parse_interval(value):
    if value is None:
        return None
    if isinstance(value, list) and len(value) >= 2:
        lo = float(value[0])
        hi = float(value[1])
        if math.isfinite(lo) and math.isfinite(hi):
            return (min(lo, hi), max(lo, hi))
    if isinstance(value, tuple) and len(value) == 2:
        return (float(min(value)), float(max(value)))
    return None


def midpoint(interval, default=1.0):
    interval = parse_interval(interval)
    if interval is None:
        return default
    return 0.5 * (interval[0] + interval[1])


def norm_unit(unit):
    if unit is None:
        return ""
    return (
        str(unit)
        .replace("µ", "u")
        .replace("μ", "u")
        .replace("^", "")
        .replace(" ", "")
        .replace("_", "")
        .lower()
    )


def convert_value(value, from_unit, to_unit, axis_id):
    src = norm_unit(from_unit)
    dst = norm_unit(to_unit)
    if not src or not dst or src == dst:
        return value

    if src in ("mg/dl", "mgperdl") and dst in ("mg/l", "mgperl"):
        return value * 10.0
    if src in ("mg/l", "mgperl") and dst in ("mg/dl", "mgperdl"):
        return value / 10.0
    if src in ("g/l", "gperl") and dst in ("g/dl", "gperdl"):
        return value / 10.0
    if src in ("g/dl", "gperdl") and dst in ("g/l", "gperl"):
        return value * 10.0
    if src in ("fraction", "ratio") and dst in ("percent", "%", "percentage"):
        return value * 100.0
    if src in ("percent", "%", "percentage") and dst in ("fraction", "ratio"):
        return value / 100.0

    if axis_id == "serum_creatinine" and src in ("umol/l", "umolperl") and dst in ("mg/dl", "mgperdl"):
        return value / 88.4
    if axis_id == "serum_creatinine" and src in ("mg/dl", "mgperdl") and dst in ("umol/l", "umolperl"):
        return value * 88.4
    if axis_id == "serum_creatinine" and src in ("mg/l", "mgperl") and dst in ("mg/dl", "mgperdl"):
        return value / 10.0

    if axis_id == "blood_urea_nitrogen" and src in ("mmol/l", "mmolperl") and dst in ("mg/dl", "mgperdl"):
        return value * 2.801
    if axis_id == "blood_urea_nitrogen" and src in ("g/l", "gperl") and dst in ("mg/dl", "mgperdl"):
        return value * 46.7

    if src in ("k/ul", "103/ul", "109/l") and dst in ("109/l", "k/ul", "103/ul"):
        return value
    if src in ("mm/hr", "mmperhr", "mm/hour", "mmperhour") and dst in ("mmperhr", "mm/hr", "mm/hour", "mmperhour"):
        return value
    if src in ("ug/mlfeu", "ug/ml", "mg/lfeu", "mg/l") and dst in ("ug/mlfeu", "ug/ml", "mg/lfeu", "mg/l"):
        return value
    return value


def observation_value_for_axis(obs, axis, axis_id):
    """Convert a case observation into the axis unit without inventing precision.

    Some PMC reports only state that a lab was normal. Encoding that as numeric
    zero is wrong for log-scale measurements such as CRP, where 0 mg/L becomes a
    mathematical extreme rather than "within the reference range".
    """
    value = obs.get("value")
    src = norm_unit(obs.get("unit"))
    if src == "normalflagonly":
        baseline = parse_interval(axis.get("baseline_range"))
        if baseline is None:
            return 0.0 if float(value) <= 0.5 else 1.0
        if float(value) <= 0.5:
            return midpoint(baseline)
        peak = parse_interval(axis.get("peak_value_range"))
        return midpoint(peak, midpoint(baseline))
    return convert_value(value, obs.get("unit"), axis.get("unit"), axis_id)


def raw_axis_records(data):
    for raw in data.get("axes", []) or []:
        yield raw

    for raw in data.get("latent_mechanisms", []) or []:
        axis = dict(raw)
        axis_id = axis.get("mechanism_id") or axis.get("axis_id") or axis.get("id")
        if not axis_id:
            continue
        axis["axis_id"] = axis_id
        axis["category"] = LATENT_MECHANISM_CATEGORY
        axis.setdefault("unit", "relative_activity_0_1")
        axis.setdefault("log_scale", False)
        axis.setdefault("baseline_range", axis.get("inactive_range") or [0.0, 0.05])
        axis.setdefault("peak_value_range", axis.get("active_range") or [0.6, 1.0])
        axis.setdefault("peak_day_range", None)
        axis.setdefault("plateau_duration_days", None)
        axis.setdefault("decline_half_life_days", None)
        axis.setdefault(
            "shape_free_text",
            axis.get("description") or axis.get("clinical_meaning") or "Latent pathophysiologic mechanism activity.",
        )
        yield axis


def normalize_effect_on_target(value):
    text = str(value or "").strip().lower()
    if text in ("increase", "increases", "up", "higher", "raises", "source_up_increases_target"):
        return "increase"
    if text in ("decrease", "decreases", "down", "lower", "lowers", "source_up_decreases_target"):
        return "decrease"
    if text == "source_down_increases_target":
        return "decrease"
    if text == "source_down_decreases_target":
        return "increase"
    return None


def normalize_mechanism_edge(raw):
    edge = dict(raw)
    source = (
        edge.get("source_id")
        or edge.get("source")
        or edge.get("source_axis_id")
        or edge.get("source_mechanism_id")
    )
    target = (
        edge.get("target_id")
        or edge.get("target")
        or edge.get("target_axis_id")
        or edge.get("target_mechanism_id")
    )
    effect = normalize_effect_on_target(
        edge.get("effect_on_target")
        or edge.get("direction")
        or edge.get("effect_direction")
    )
    if not source or not target or effect is None:
        return None
    edge["source_axis_id"] = source
    edge["target_axis_id"] = target
    edge["effect_on_target"] = effect
    edge.setdefault("edge_type", "pathophysiology")
    return edge


def apply_treatment_modifier_context_defaults(axis):
    if axis.get("category") != "treatment_modifier":
        return axis
    if axis.get("peak_value_range") is None or axis.get("peak_day_range") is not None:
        return axis
    axis = dict(axis)
    axis["peak_day_range"] = [-365.0, 0.0]
    axis["plateau_duration_days"] = axis.get("plateau_duration_days") or [30.0, 3650.0]
    axis["decline_half_life_days"] = axis.get("decline_half_life_days") or [30.0, 365.0]
    return axis


def load_manifold(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    axes = {}
    for raw in raw_axis_records(data):
        if not raw.get("axis_id"):
            continue
        axis = dict(raw)
        for key in [
            "baseline_range",
            "peak_day_range",
            "peak_value_range",
            "plateau_duration_days",
            "decline_half_life_days",
        ]:
            axis[key] = parse_interval(axis.get(key))
        if axis["baseline_range"] is None:
            continue
        axis = apply_treatment_modifier_context_defaults(axis)
        axes[axis["axis_id"]] = axis
    mechanism_edges = []
    for raw in (data.get("mechanism_edges") or []) + (data.get("causal_edges") or []):
        edge = normalize_mechanism_edge(raw)
        if edge is not None:
            mechanism_edges.append(edge)
    mechanism_edges_by_target = {}
    for edge in mechanism_edges:
        mechanism_edges_by_target.setdefault(edge.get("target_axis_id"), []).append(edge)
    return {
        "disease": data.get("disease", path.stem),
        "distillation_scope": data.get("distillation_scope") or {},
        "axes": axes,
        "latent_mechanisms": data.get("latent_mechanisms") or [],
        "mechanism_edges": mechanism_edges,
        "mechanism_edges_by_target": mechanism_edges_by_target,
        "axis_couplings": data.get("axis_couplings") or [],
        "risk_factors": data.get("risk_factors") or [],
        "treatments": data.get("treatments") or [],
    }


def load_master_axes(path=ROOT / "master_axes.json"):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {a["axis_id"]: a for a in data.get("axes", []) if a.get("axis_id")}


def build_background_axes(manifolds, master_axes):
    by_axis = {}
    for manifold in manifolds.values():
        for axis_id, axis in manifold["axes"].items():
            if axis.get("category") == "derived_hazard":
                continue
            entry = by_axis.setdefault(axis_id, {
                "axis_id": axis_id,
                "category": axis.get("category"),
                "unit": axis.get("unit"),
                "log_scale": bool(axis.get("log_scale", False)),
                "axis_role": axis.get("axis_role"),
                "parent_axis_id": axis.get("parent_axis_id"),
                "ranges": [],
            })
            for meta_key in ("axis_role", "parent_axis_id"):
                if not entry.get(meta_key) and axis.get(meta_key):
                    entry[meta_key] = axis.get(meta_key)
            unit = entry.get("unit") or axis.get("unit")
            lo, hi = axis["baseline_range"]
            entry["ranges"].append((
                convert_value(lo, axis.get("unit"), unit, axis_id),
                convert_value(hi, axis.get("unit"), unit, axis_id),
            ))

    for axis_id, meta in master_axes.items():
        by_axis.setdefault(axis_id, {
            "axis_id": axis_id,
            "category": meta.get("category"),
            "unit": meta.get("unit") or meta.get("unit_canonical"),
            "log_scale": bool(meta.get("log_scale", False)),
            "axis_role": meta.get("axis_role"),
            "parent_axis_id": meta.get("parent_axis_id"),
            "ranges": [],
        })

    for axis_id, meta in HEALTHY_OVERRIDES.items():
        by_axis.setdefault(axis_id, {
            "axis_id": axis_id,
            "category": "background_measurement",
            "unit": meta.get("unit"),
            "log_scale": bool(meta.get("log_scale", False)),
            "axis_role": "measurement",
            "parent_axis_id": None,
            "ranges": [],
        })

    background = {}
    for axis_id, entry in by_axis.items():
        override = HEALTHY_OVERRIDES.get(axis_id) or v5_background.BASE_MEASURE_OVERRIDES.get(axis_id)
        if override:
            baseline = override["baseline_range"]
            unit = override["unit"]
            log_scale = override["log_scale"]
        elif entry.get("category") == LATENT_MECHANISM_CATEGORY:
            baseline = (0.0, 0.05)
            unit = entry.get("unit") or "relative_activity_0_1"
            log_scale = False
        elif entry["ranges"]:
            lows = [r[0] for r in entry["ranges"]]
            highs = [r[1] for r in entry["ranges"]]
            baseline = (min(lows), max(highs))
            unit = entry.get("unit")
            log_scale = entry.get("log_scale", False)
        else:
            unit = entry.get("unit")
            category = entry.get("category")
            if category in ("physical_finding", "qualitative") or norm_unit(unit) in (
                "severityscore01",
                "probability01",
                "relativeactivity01",
            ):
                baseline = (0.0, 0.05)
                log_scale = False
            else:
                continue
        background[axis_id] = {
            "axis_id": axis_id,
            "category": entry.get("category"),
            "unit": unit,
            "log_scale": log_scale,
            "axis_role": entry.get("axis_role"),
            "parent_axis_id": entry.get("parent_axis_id"),
            "baseline_range": baseline,
            "peak_day_range": None,
            "peak_value_range": None,
            "plateau_duration_days": None,
            "decline_half_life_days": None,
            "_source": "base_measure_background",
        }
    return background


def fallback_axis_from_observation(axis_id, obs):
    unit = obs.get("unit")
    if norm_unit(unit) not in ("severityscore01", "probability01", "relativeactivity01", "presentabsent01"):
        return None
    return {
        "axis_id": axis_id,
        "category": "qualitative",
        "unit": unit,
        "log_scale": False,
        "baseline_range": [0.0, 0.05],
        "peak_day_range": None,
        "peak_value_range": None,
        "plateau_duration_days": None,
        "decline_half_life_days": None,
        "_source": "case_observation_background_fallback",
    }


MAPPED_EVIDENCE_SECTIONS = (
    "imaging",
    "pathology",
    "procedures",
    "diagnostics",
    "physical_exam",
    "microbiology",
    "clinical_course_events",
)
DIRECT_AXIS_SECTION_SKIP = {
    "demographics",
    "risk_context",
    "lab_trajectories",
    "observations",
    "course_observations",
    *MAPPED_EVIDENCE_SECTIONS,
}
NON_RANKING_SECTION_PREFIXES = (
    "confirmatory",
    "actual_treatment",
    "outcome",
    "follow_up",
    "treatment",
    "supportive",
)


def mapped_axis_ids(item):
    ids = []
    if item.get("mapped_axis_id"):
        ids.append(item.get("mapped_axis_id"))
    raw_ids = item.get("mapped_axis_ids")
    if isinstance(raw_ids, list):
        ids.extend(raw_ids)
    return [axis_id for axis_id in ids if axis_id]


def mapped_axis_items(item):
    for axis_id in mapped_axis_ids(item):
        yield axis_id, item

    raw_axes = item.get("mapped_axes")
    if not isinstance(raw_axes, list):
        return
    for axis_item in raw_axes:
        if not isinstance(axis_item, dict):
            continue
        axis_id = axis_item.get("axis_id") or axis_item.get("mapped_axis_id")
        if axis_id:
            yield axis_id, axis_item


def can_infer_qualitative_mapped_axis(axis_id):
    qualitative_markers = (
        "_activity",
        "_presence",
        "_probability",
        "_severity",
        "_extent",
        "_need",
        "presence_in_",
        "activity_in_",
        "hazard_in_",
    )
    measurement_markers = (
        "_size_",
        "_diameter_",
        "_gradient_",
        "_count",
        "_days",
        "_mmhg",
        "_cm",
        "_mm",
    )
    if any(marker in axis_id for marker in measurement_markers):
        return False
    if axis_id.endswith("_hazard") or "_hazard_" in axis_id:
        return False
    return any(marker in axis_id for marker in qualitative_markers)


def mapped_item_is_negative(item):
    text = " ".join(
        str(item.get(key, ""))
        for key in ("finding", "result", "source_text_value")
    ).lower()
    negative_patterns = (
        r"\bnegative\b",
        r"\bnormal\b",
        r"\bno\b",
        r"no_",
        r"\bwithout\b",
        r"\babsent\b",
        r"\bresolved\b",
        r"\bdisappeared\b",
        r"\bclear\b",
        r"not\s+found",
        r"not\s+noted",
    )
    return any(re.search(pattern, text) for pattern in negative_patterns)


def infer_mapped_observation(item, axis_id, axis_item=None):
    if item.get("use_in_ranking") is False:
        return None
    axis_item = axis_item or item
    if axis_item.get("use_in_ranking") is False:
        return None
    value = axis_item.get("value")
    if value is not None:
        return value, axis_item.get("unit") or item.get("unit") or "severity_score_0_1"
    if not can_infer_qualitative_mapped_axis(axis_id):
        return None
    merged_item = {**item, **axis_item}
    if mapped_item_is_negative(merged_item):
        return 0.0, "severity_score_0_1"
    return 1.0, "severity_score_0_1"


def infer_direct_observation(axis_id, value, unit, qualitative_value=None):
    if value is not None:
        return value, unit
    if qualitative_value is None:
        return None

    q = str(qualitative_value).strip().lower()
    if not q:
        return None
    normalized_unit = norm_unit(unit)
    if axis_id == "body_temperature":
        if any(token in q for token in ("afebrile", "denied_fever", "no_fever")):
            return 36.8, unit or "degC"
        if any(token in q for token in ("high_grade_fever", "hyperpyrexia")):
            return 39.0, unit or "degC"
        if "fever" in q or "febrile" in q:
            return 38.5, unit or "degC"

    if normalized_unit in ("presentabsent01", "probability01", "relativeactivity01", "severityscore01"):
        if mapped_item_is_negative({"source_text_value": q}):
            return 0.0, unit
        return 1.0, unit

    if q in ("normal", "within_normal_limits", "within_reference_range"):
        override = HEALTHY_OVERRIDES.get(axis_id) or v5_background.BASE_MEASURE_OVERRIDES.get(axis_id)
        if override:
            return midpoint(override.get("baseline_range")), unit or override.get("unit")
    return None


def iter_direct_axis_section_items(data):
    for section, records in data.items():
        if section in DIRECT_AXIS_SECTION_SKIP:
            continue
        if any(section.startswith(prefix) for prefix in NON_RANKING_SECTION_PREFIXES):
            continue
        if not isinstance(records, list):
            continue
        for item in records:
            if isinstance(item, dict) and item.get("axis_id"):
                yield section, item


def background_axes_for_case(background_axes, case, candidate):
    """Return risk-adjusted background axes needed by this case/candidate.

    The full master/background ontology is now thousands of axes. Case ranking
    only needs observed axes, so adjusting the entire ontology for every
    candidate turns the regression into mostly repeated background bookkeeping.
    """
    candidate = tuple(candidate)
    cache = case.setdefault("_background_axes_cache", {})
    if candidate in cache:
        return cache[candidate]

    context = v5_background.background_context_for_case(case)
    adjusted = {}
    for axis_id, obs in case.get("observations_by_axis", {}).items():
        axis = background_axes.get(axis_id)
        if axis is not None:
            adjusted[axis_id] = v5_background.apply_background_modifiers_to_axis(
                axis,
                context,
                candidate,
                BACKGROUND_MODIFIERS,
                CONDITION_SCOPE,
                convert_value,
            )
            continue
        fallback = fallback_axis_from_observation(axis_id, obs)
        if fallback is not None:
            adjusted[axis_id] = fallback
    cache[candidate] = adjusted
    return adjusted


def case_item_rankable(item):
    return item.get("use_in_ranking") is not False


def load_case(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    observations = {}

    def add_observation(axis_id, value, unit):
        if not axis_id or value is None:
            return
        value = float(value)
        if axis_id in observations:
            old = observations[axis_id]
            normalized_unit = norm_unit(unit or old.get("unit"))
            if normalized_unit in ("presentabsent01", "probability01", "relativeactivity01", "severityscore01") or axis_id.endswith("_hazard") or "_hazard_" in axis_id:
                if value > float(old.get("value", 0.0)):
                    observations[axis_id] = {"value": value, "unit": unit or old.get("unit")}
            return
        observations[axis_id] = {"value": value, "unit": unit}

    for obs in data.get("observations", []):
        if not case_item_rankable(obs):
            continue
        inferred = infer_direct_observation(obs.get("axis_id"), obs.get("value"), obs.get("unit"), obs.get("qualitative_value"))
        if inferred is not None:
            value, unit = inferred
            add_observation(obs.get("axis_id"), value, unit)

    for obs in data.get("course_observations", []):
        if not case_item_rankable(obs):
            continue
        inferred = infer_direct_observation(obs.get("axis_id"), obs.get("value"), obs.get("unit"), obs.get("qualitative_value"))
        if inferred is not None:
            value, unit = inferred
            add_observation(obs.get("axis_id"), value, unit)

    for traj in data.get("lab_trajectories", []):
        if not case_item_rankable(traj):
            continue
        axis_id = traj.get("axis_id")
        inferred = infer_direct_observation(axis_id, traj.get("value"), traj.get("unit"), traj.get("qualitative_value"))
        if inferred is not None:
            value, unit = inferred
            add_observation(axis_id, value, unit)
        numeric = [
            o
            for o in ((traj.get("observations") or []) + (traj.get("time_series") or []))
            if o.get("value") is not None and case_item_rankable(o)
        ]
        if not axis_id or not numeric or axis_id in observations:
            continue
        first = sorted(numeric, key=lambda o: float(o.get("day", 0)))[0]
        observations[axis_id] = {"value": float(first["value"]), "unit": traj.get("unit")}

    for section in MAPPED_EVIDENCE_SECTIONS:
        records = data.get(section)
        if not isinstance(records, list):
            continue
        for item in records:
            if not isinstance(item, dict):
                continue
            for axis_id, axis_item in mapped_axis_items(item):
                inferred = infer_mapped_observation(item, axis_id, axis_item)
                if inferred is None:
                    continue
                value, unit = inferred
                add_observation(axis_id, value, unit)

    for _section, item in iter_direct_axis_section_items(data):
        if not case_item_rankable(item):
            continue
        inferred = infer_direct_observation(item.get("axis_id"), item.get("value"), item.get("unit"), item.get("qualitative_value"))
        if inferred is None:
            continue
        value, unit = inferred
        add_observation(item.get("axis_id"), value, unit)

    data["observations_by_axis"] = observations
    return data


def sample_uniform(rng, interval):
    lo, hi = interval
    if lo == hi:
        return lo
    if rng is None:
        return 0.5 * (lo + hi)
    return float(rng.uniform(lo, hi))


def inferred_t_max(manifold):
    horizons = []
    for axis in manifold.get("axes", {}).values():
        if axis.get("category") in ("derived_hazard", "treatment_modifier"):
            continue
        peak = parse_interval(axis.get("peak_day_range"))
        plateau = parse_interval(axis.get("plateau_duration_days"))
        if peak is None:
            continue
        horizon = peak[1]
        if plateau is not None:
            horizon += 0.5 * plateau[1]
        horizons.append(horizon)
    if not horizons:
        return 90.0
    return float(np.clip(np.percentile(horizons, 75), 14.0, 365.0))


def disease_t_max(disease, manifold):
    override = T_MAX_BY_DISEASE.get(disease)
    if override is not None:
        return override
    if "_t_max" not in manifold:
        manifold["_t_max"] = inferred_t_max(manifold)
    return manifold["_t_max"]


def sample_mu_and_baseline(axis, t, rng):
    baseline = sample_uniform(rng, axis["baseline_range"])
    peak_day_range = axis.get("peak_day_range")
    peak_value_range = axis.get("peak_value_range")
    if t < 0 or peak_day_range is None or peak_value_range is None:
        return baseline, baseline

    peak_day = max(sample_uniform(rng, peak_day_range), 1e-6)
    peak_value = sample_uniform(rng, peak_value_range)
    plateau = 0.0 if axis.get("plateau_duration_days") is None else sample_uniform(rng, axis["plateau_duration_days"])
    plateau_end = peak_day + max(plateau, 0.0)

    if t <= 0:
        mu = baseline
    elif t < peak_day:
        mu = baseline + (peak_value - baseline) * (t / peak_day)
    elif t < plateau_end:
        mu = peak_value
    else:
        hl_range = axis.get("decline_half_life_days")
        if hl_range is None:
            mu = peak_value
        else:
            hl = max(sample_uniform(rng, hl_range), 1e-6)
            decay = 0.5 ** ((t - plateau_end) / hl)
            mu = baseline + (peak_value - baseline) * decay
    return mu, baseline


def axis_sigma(axis):
    cached = axis.get("_axis_sigma")
    if cached is not None:
        return cached
    ranges = [axis.get("baseline_range"), axis.get("peak_value_range")]
    values = []
    for interval in ranges:
        if interval is not None:
            values.extend([interval[0], interval[1]])
    if not values:
        return 1.0

    if axis.get("log_scale"):
        if zero_inclusive_log_axis(axis):
            logs = [math.log10(max(v, 0.0) + 1.0) for v in values]
        else:
            logs = [math.log10(max(v, 1e-12)) for v in values if v > 0]
        if not logs:
            return 0.5
        sigma = max((max(logs) - min(logs)) / 6.0, 0.15)
        axis["_axis_sigma"] = sigma
        return sigma

    spread = max(values) - min(values)
    ordered = sorted(float(v) for v in values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        median = ordered[mid]
    else:
        median = 0.5 * (ordered[mid - 1] + ordered[mid])
    typical = max(abs(median), 1.0)
    sigma = max(spread / 6.0, 0.08 * typical, 1e-6)
    axis["_axis_sigma"] = sigma
    return sigma


def zero_inclusive_log_axis(axis):
    if not axis.get("log_scale"):
        return False
    axis_id = axis.get("axis_id", "")
    if axis.get("category") != "csf" and not axis_id.startswith("csf_"):
        return False
    for interval in (axis.get("baseline_range"), axis.get("peak_value_range")):
        if interval is not None and min(interval) <= 0:
            return True
    return False


def transform(axis, value):
    if axis.get("log_scale"):
        if zero_inclusive_log_axis(axis):
            return math.log10(max(value, 0.0) + 1.0)
        return math.log10(max(value, 1e-12))
    return float(value)


def inverse_transform(axis, z):
    if axis.get("log_scale"):
        if zero_inclusive_log_axis(axis):
            return max((10.0 ** z) - 1.0, 0.0)
        return 10.0 ** z
    return float(z)


def deterministic_seed(parts):
    s = SEED
    for part in parts:
        for ch in str(part):
            s = (s * 131 + ord(ch)) % (2**32 - 1)
    return s


def auto_demographic_context(case, disease):
    out = []
    demo = case.get("demographics") or {}
    age = demo.get("age")
    sex = str(demo.get("sex", "")).upper()

    if sex in ("F", "FEMALE"):
        out.append({"factor": "sex", "category": "female", "source": "demographics"})
    elif sex in ("M", "MALE"):
        out.append({"factor": "sex", "category": "male", "source": "demographics"})

    if isinstance(age, (int, float)):
        if disease == "D-SEPSIS-GN":
            category = "age_18_49" if age < 50 else "age_50_64" if age < 65 else "age_65_79" if age < 80 else "age_ge80"
        elif disease == "D137":
            category = "young_adult_16_to_35_years" if age <= 35 else "middle_adult_36_to_60_years" if age <= 60 else "older_adult_over_60_years"
        elif disease == "D-TTP":
            category = "younger_adult_18_40" if age <= 40 else "middle_age_40_65" if age <= 65 else "older_adult_over_65"
        else:
            category = None
        if category:
            out.append({"factor": "age", "category": category, "source": "demographics"})
    return out


def case_risk_context(case, disease):
    ctx = []
    for item in case.get("risk_context", []):
        if not case_item_rankable(item):
            continue
        applies = item.get("applies_to")
        if applies is None or disease in applies or "*" in applies:
            ctx.append(item)
    ctx.extend(auto_demographic_context(case, disease))
    return ctx


def matched_risk_payload(manifold, context):
    by_key = {(c.get("factor"), c.get("category")) for c in context}
    by_factor = {}
    for item in context:
        by_factor.setdefault(item.get("factor"), []).append(item)
    axis_mods = {}
    coupling_mods = []
    log_prior = 0.0

    for rf in manifold["risk_factors"]:
        factor = rf.get("factor")
        for category, mod in (rf.get("modulation") or {}).items():
            if (
                (factor, category) not in by_key
                and not risk_factor_present_match(factor, category, by_factor)
            ):
                continue
            p_ratio = midpoint(mod.get("P_disease_ratio"), 1.0)
            if p_ratio > 0:
                log_prior += math.log(min(max(p_ratio, 0.05), 50.0))
            for item in iter_axis_response_modulation_items(mod.get("axis_response_modulation")):
                axis_mods.setdefault(item.get("axis_id"), []).append(item)
            for item in iter_risk_modulation_items(mod.get("coupling_modulation")):
                coupling_mods.append(item)
    return axis_mods, coupling_mods, log_prior


def iter_axis_response_modulation_items(raw):
    if raw is None:
        return
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(raw, dict):
        for axis_id, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("axis_id", axis_id)
                yield item
            elif isinstance(value, str):
                yield {"axis_id": axis_id, "effect": value}


def iter_risk_modulation_items(raw):
    if raw is None:
        return
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                yield item
        return
    if isinstance(raw, dict):
        for key, value in raw.items():
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("coupling_id", key)
                yield item


def risk_context_item_is_positive(item):
    value = item.get("value")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value <= 0:
        return False

    category = str(item.get("category", "")).lower()
    negative_markers = (
        "absent",
        "denied",
        "negative",
        "not_reported",
        "not_identified",
        "not_known",
        "none",
        "no_",
        "without",
        "ruled_out",
    )
    return not any(marker in category for marker in negative_markers)


def risk_factor_present_match(factor, category, by_factor):
    """Match factor-level positive context to generic ``present`` modulation.

    New distillations commonly write risk-factor modulation as
    ``factor -> present`` while real case JSON stores the factor with a
    contextual category such as ``immunosuppression`` or ``comorbidity``.
    Exact category matches remain authoritative; this fallback only bridges
    positive evidence for the same factor to the generic ``present`` bucket.
    """
    if category != "present":
        return False
    return any(risk_context_item_is_positive(item) for item in by_factor.get(factor, []))


def observed_value(case, axis_id):
    obs = case["observations_by_axis"].get(axis_id)
    if not obs:
        return None
    return obs["value"]


def observed_absent(case, axis_id):
    obs = case["observations_by_axis"].get(axis_id)
    if not obs:
        return False
    unit = norm_unit(obs.get("unit"))
    if unit not in ("presentabsent01", "probability01", "relativeactivity01", "severityscore01"):
        return False
    return float(obs["value"]) < PARENT_FINDING_PRESENT_THRESHOLD


def conditional_axis_ids(case, candidate, manifolds, background_axes):
    """Observed axes eligible for likelihood under finding/measurement/satellite ontology.

    Satellite and measurement axes with a parent finding are conditional on the
    parent not being explicitly absent. This preserves the old V3 principle:
    first ask whether the finding exists; only then score its distribution,
    size, or other satellite attributes.
    """
    obs = case["observations_by_axis"]
    eligible = set()
    children_by_parent = {}
    for axis_id in obs:
        axis = eval_axis(axis_id, candidate, manifolds, background_axes)
        if axis is None:
            continue
        parent_axis_id = axis.get("parent_axis_id")
        if parent_axis_id and observed_absent(case, parent_axis_id):
            continue
        eligible.add(axis_id)
        if parent_axis_id:
            children_by_parent.setdefault(parent_axis_id, set()).add(axis_id)

    axis_ids = []
    for axis_id in eligible:
        if (
            axis_id in children_by_parent
            and observed_value(case, axis_id) is not None
            and not observed_absent(case, axis_id)
        ):
            continue
        axis_ids.append(axis_id)
    return sorted(axis_ids)


def axis_manifold_frequency(manifolds):
    cache_key = tuple(manifolds)
    cached = _AXIS_MANIFOLD_FREQUENCY_CACHE.get(cache_key)
    if cached is not None:
        return cached
    freq = {}
    for manifold in manifolds.values():
        for axis_id, axis in manifold["axes"].items():
            if axis.get("category") == "derived_hazard":
                continue
            freq[axis_id] = freq.get(axis_id, 0) + 1
    _AXIS_MANIFOLD_FREQUENCY_CACHE[cache_key] = freq
    return freq


def observed_axis_activity_against_disease(axis_id, axis, obs, background_axis):
    peak = parse_interval(axis.get("peak_value_range"))
    baseline = parse_interval(axis.get("baseline_range"))
    if peak is None or baseline is None:
        return 0.0
    try:
        obs_value = observation_value_for_axis(obs, axis, axis_id)
        baseline_mid = midpoint(baseline)
        peak_mid = midpoint(peak, baseline_mid)
        z_obs = transform(axis, obs_value)
        z_base = transform(axis, baseline_mid)
        z_peak = transform(axis, peak_mid)
    except Exception:
        return 0.0

    span = z_peak - z_base
    if abs(span) < 1e-6:
        return 0.0
    progress = (z_obs - z_base) / span
    if progress <= 0.0:
        return 0.0

    bg_axis = background_axis or axis
    try:
        bg_mid = midpoint(parse_interval(bg_axis.get("baseline_range")) or baseline, baseline_mid)
        z_bg = transform(axis, convert_value(bg_mid, bg_axis.get("unit"), axis.get("unit"), axis_id))
    except Exception:
        z_bg = z_base
    bg_span = abs(z_obs - z_bg) / max(abs(span), 1e-6)
    return clamp01(min(progress, bg_span))


def generic_component_anchor_support(case, disease, manifolds, background_axes):
    """Use disease-owned, high-specificity observed axes as combo anchors.

    This is intentionally conservative. It does not say "this disease should
    win"; it only asks whether adding this vector field has independent evidence
    beyond generic fever/inflammation/vital-sign noise.
    """
    manifold = manifolds[disease]
    freq = axis_manifold_frequency(manifolds)
    max_freq = max(3, int(math.ceil(len(manifolds) * GENERIC_ANCHOR_MAX_AXIS_FRACTION)))
    score = 0.0

    for axis_id, obs in case["observations_by_axis"].items():
        axis = manifold["axes"].get(axis_id)
        if axis is None:
            continue
        category = str(axis.get("category") or "").strip().lower()
        if category in GENERIC_ANCHOR_EXCLUDED_CATEGORIES:
            continue
        if axis_id in GENERIC_ANCHOR_LOW_SPECIFICITY_AXES:
            continue
        axis_freq = freq.get(axis_id, 0)
        if axis_freq > max_freq:
            continue
        activity = observed_axis_activity_against_disease(axis_id, axis, obs, background_axes.get(axis_id))
        if activity < 0.45:
            continue

        if axis_freq <= 2:
            specificity = 1.25
        elif axis_freq <= 5:
            specificity = 1.0
        else:
            specificity = 0.7

        if "imaging" in category or "pathology" in category or "microbiology" in category:
            category_weight = 1.25
        elif category == "treatment_modifier":
            category_weight = 0.65
        elif "lab" in category:
            category_weight = 0.85
        else:
            category_weight = 0.75

        score += min(activity * specificity * category_weight, 1.5)
        if score >= GENERIC_ANCHOR_SCORE_CAP:
            return GENERIC_ANCHOR_SCORE_CAP
    return min(score, GENERIC_ANCHOR_SCORE_CAP)


def component_anchor_support(case, disease, manifolds, background_axes):
    """Require disease-specific evidence before allowing a combo to turn on.

    Without this, a broad second manifold can overfit generic fever/CRP/WBC axes.
    The anchors are not diagnostic labels; they are high-specificity observed axes
    that justify adding another vector field to the state equation.
    """
    score = 0.0
    obs = case["observations_by_axis"]

    if disease == "D137":
        ferritin = observed_value(case, "serum_ferritin")
        if ferritin is not None and ferritin >= 1000:
            score += 2.0
        glyco = observed_value(case, "glycosylated_ferritin_fraction")
        if glyco is not None and glyco <= 20:
            score += 2.0
        for axis_id in ("evanescent_rash_activity", "sore_throat_activity", "arthritis_activity"):
            value = observed_value(case, axis_id)
            if value is not None and value >= 0.4:
                score += 1.0

    elif disease == "D-SEPSIS-GN":
        pct = observed_value(case, "serum_procalcitonin")
        if pct is not None and pct >= 2.0:
            score += 2.0
        culture = observed_value(case, "blood_culture_positivity_probability")
        if culture is not None and culture >= 0.5:
            score += 2.0
        if "blood_culture_bacterial_load" in obs:
            score += 1.5
        lactate = observed_value(case, "serum_lactate")
        map_value = observed_value(case, "mean_arterial_pressure")
        if lactate is not None and lactate >= 2.5:
            score += 1.0
            if map_value is not None and map_value < 65:
                score += 1.0

    elif disease == "D-TTP":
        adam = observed_value(case, "adamts13_activity")
        if adam is not None and adam <= 10:
            score += 3.0
        inhibitor = observed_value(case, "anti_adamts13_igg_inhibitor_titer")
        if inhibitor is not None and inhibitor >= 0.5:
            score += 2.0
        platelet = observed_value(case, "platelet_count")
        if platelet is not None:
            if platelet <= 30:
                score += 2.0
            elif platelet <= 50:
                score += 1.5
            elif platelet <= 80:
                score += 0.5
        schisto = observed_value(case, "schistocyte_fraction")
        if schisto is not None and schisto >= 1.0:
            score += 2.0
        hapto = observed_value(case, "serum_haptoglobin")
        if hapto is not None and hapto <= 20:
            score += 1.5
        ldh = observed_value(case, "serum_ldh")
        hb = observed_value(case, "hemoglobin")
        if ldh is not None and hb is not None and ldh >= 500 and hb <= 10:
            score += 1.0

    return max(score, generic_component_anchor_support(case, disease, manifolds, background_axes))


def combo_anchor_penalty(case, candidate, manifolds, background_axes):
    if len(candidate) <= 1:
        return 0.0, {}
    support = {
        disease: component_anchor_support(case, disease, manifolds, background_axes)
        for disease in candidate
    }
    penalty = 0.0
    for value in support.values():
        if value < COMBO_ANCHOR_THRESHOLD:
            penalty += COMBO_MISSING_ANCHOR_PENALTY * (COMBO_ANCHOR_THRESHOLD - value)
    return penalty, support


def is_bounded_0_1_axis(axis):
    return norm_unit(axis.get("unit")) in (
        "presentabsent01",
        "probability01",
        "relativeactivity01",
        "severityscore01",
    )


def apply_axis_modulations(axis_id, axis, mu, baseline, sigma, mods, rng):
    for mod in mods:
        effect = mod.get("effect")
        direction = str(mod.get("direction") or mod.get("effect_direction") or "").strip().lower()
        factor = midpoint(mod.get("magnitude_factor_range") or mod.get("factor_range"), 1.0)
        if effect in ("blunted_response", "lower_peak"):
            mu = baseline + factor * (mu - baseline)
        elif effect == "higher_peak":
            mu = baseline + factor * (mu - baseline)
        elif effect == "higher_baseline":
            mu = mu * factor
            baseline = baseline * factor
        elif effect == "lower_baseline":
            mu = mu * factor
            baseline = baseline * factor
        elif effect == "more_variable":
            sigma *= max(factor, 1.0)
        elif effect == "less_variable":
            sigma *= min(max(factor, 0.1), 1.0)
        elif effect == "delayed_peak":
            pass
        elif direction in ("up", "increase", "increased", "higher", "raise", "raises"):
            mu = baseline + max(factor, 1.0) * (mu - baseline)
        elif direction in ("down", "decrease", "decreased", "lower", "lowers", "blunted", "attenuated"):
            if factor > 1.0:
                factor = 1.0 / factor
            mu = baseline + min(max(factor, 0.05), 1.0) * (mu - baseline)
    if is_bounded_0_1_axis(axis):
        mu = clamp01(mu)
        baseline = clamp01(baseline)
    elif axis.get("log_scale"):
        mu = max(mu, 1e-12)
    elif axis_id not in ("body_temperature",):
        mu = max(mu, 0.0)
    return mu, baseline, sigma


def eval_axis(axis_id, candidate, manifolds, background_axes):
    for disease in candidate:
        axis = manifolds[disease]["axes"].get(axis_id)
        if axis and axis.get("category") != "derived_hazard":
            return axis
    return background_axes.get(axis_id)


def mechanism_edges_to(manifold, target_axis_id):
    indexed = manifold.get("mechanism_edges_by_target")
    if indexed is not None:
        return indexed.get(target_axis_id, [])
    return [
        edge
        for edge in manifold.get("mechanism_edges", [])
        if edge.get("target_axis_id") == target_axis_id
    ]


def clamp01(value):
    return max(min(float(value), 1.0), 0.0)


def axis_activity(axis, value, background_axis=None):
    """Map a hidden mechanism/source value to 0..1 activity.

    Mechanism nodes are intentionally unit-light: relative 0..1 axes use their
    value directly; other axes are normalized between inactive/background and
    disease-active ranges.
    """
    unit = norm_unit(axis.get("unit"))
    if unit in ("relativeactivity01", "probability01", "severityscore01"):
        return clamp01(value)

    inactive = parse_interval((background_axis or {}).get("baseline_range")) or parse_interval(axis.get("baseline_range"))
    active = parse_interval(axis.get("peak_value_range")) or parse_interval(axis.get("baseline_range"))
    inactive_mid = midpoint(inactive, 0.0)
    active_mid = midpoint(active, inactive_mid)
    denom = active_mid - inactive_mid
    if abs(denom) < 1e-9:
        return 0.0
    return clamp01((value - inactive_mid) / denom)


def edge_adjusted_delta(raw_delta, edge):
    effect = edge.get("effect_on_target")
    if effect == "increase":
        return abs(raw_delta)
    if effect == "decrease":
        return -abs(raw_delta)
    return raw_delta


def mechanism_activity_for_axis(
    disease,
    source_axis_id,
    t_by_disease,
    manifolds,
    background_axes,
    risk_payloads,
    rng,
    seen=None,
    cache=None,
):
    """Return effective 0..1 mechanism activity, including upstream mechanism gates."""
    cache = cache if cache is not None else {}
    if source_axis_id in cache:
        return cache[source_axis_id]

    manifold = manifolds[disease]
    source_axis = manifold["axes"].get(source_axis_id)
    if source_axis is None:
        return 0.0

    source_mu, source_baseline = sample_mu_and_baseline(source_axis, t_by_disease[disease], rng)
    sigma = axis_sigma(source_axis)
    mods = risk_payloads[disease]["axis_mods"].get(source_axis_id, [])
    source_mu, _, _ = apply_axis_modulations(source_axis_id, source_axis, source_mu, source_baseline, sigma, mods, rng)
    activity = axis_activity(source_axis, source_mu, background_axes.get(source_axis_id))

    seen = set(seen or ())
    if source_axis_id in seen:
        cache[source_axis_id] = clamp01(activity)
        return cache[source_axis_id]
    seen.add(source_axis_id)

    parent_signals = []
    for edge in mechanism_edges_to(manifold, source_axis_id):
        parent_axis_id = edge.get("source_axis_id")
        parent_axis = manifold["axes"].get(parent_axis_id)
        if parent_axis is None or parent_axis.get("category") != LATENT_MECHANISM_CATEGORY:
            continue
        parent_activity = mechanism_activity_for_axis(
            disease,
            parent_axis_id,
            t_by_disease,
            manifolds,
            background_axes,
            risk_payloads,
            rng,
            seen,
            cache,
        )
        if edge.get("effect_on_target") == "decrease":
            parent_activity = 1.0 - parent_activity
        parent_signals.append(clamp01(parent_activity))

    if parent_signals:
        activity = min(activity, max(parent_signals))

    cache[source_axis_id] = clamp01(activity)
    return cache[source_axis_id]


def mechanism_gate_for_target(disease, target_axis_id, t_by_disease, manifolds, background_axes, risk_payloads, rng):
    """Return dominant latent-mechanism activity for a target axis, if modeled."""
    manifold = manifolds[disease]
    candidates = []
    cache = {}
    for edge in mechanism_edges_to(manifold, target_axis_id):
        source_axis_id = edge.get("source_axis_id")
        source_axis = manifold["axes"].get(source_axis_id)
        if source_axis is None:
            continue
        activity = mechanism_activity_for_axis(
            disease,
            source_axis_id,
            t_by_disease,
            manifolds,
            background_axes,
            risk_payloads,
            rng,
            cache=cache,
        )
        candidates.append((activity, edge))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])


def combo_axis_endpoint(axis_id, candidate, t_by_disease, manifolds, background_axes, risk_payloads, rng):
    axis_eval = eval_axis(axis_id, candidate, manifolds, background_axes)
    if axis_eval is None:
        return None
    bg_axis = background_axes.get(axis_id) or axis_eval
    bg_mu, _ = sample_mu_and_baseline(bg_axis, -1.0, rng)
    bg_mu = convert_value(bg_mu, bg_axis.get("unit"), axis_eval.get("unit"), axis_id)
    z_bg = transform(axis_eval, bg_mu)

    raw_deltas = []
    strengths = []
    sigmas = [axis_sigma(bg_axis)]
    sources = []

    for disease in candidate:
        axis = manifolds[disease]["axes"].get(axis_id)
        if axis is None or axis.get("category") == "derived_hazard":
            continue
        mu, baseline = sample_mu_and_baseline(axis, t_by_disease[disease], rng)
        axis_mods = risk_payloads[disease]["axis_mods"].get(axis_id, [])
        sigma = axis_sigma(axis)
        mu, baseline, sigma = apply_axis_modulations(axis_id, axis, mu, baseline, sigma, axis_mods, rng)
        mu = convert_value(mu, axis.get("unit"), axis_eval.get("unit"), axis_id)
        z_mu = transform(axis_eval, mu)
        raw_delta = z_mu - z_bg
        gate = mechanism_gate_for_target(disease, axis_id, t_by_disease, manifolds, background_axes, risk_payloads, rng)
        if gate is not None:
            activity, edge = gate
            raw_delta = edge_adjusted_delta(raw_delta, edge) * activity
        raw_deltas.append(raw_delta)
        strengths.append(abs(raw_delta) / max(sigma, 1e-6))
        sigmas.append(sigma)
        sources.append(disease)

    if not raw_deltas:
        z = z_bg
        sigma = axis_sigma(bg_axis)
        source = bg_axis.get("_source", "base_measure_background")
    else:
        signs = {1 if d > 0 else -1 if d < 0 else 0 for d in raw_deltas}
        signs.discard(0)
        if len(signs) > 1 and len(raw_deltas) > 1:
            dominant = int(np.argmax(strengths))
            z_delta = raw_deltas[dominant] + 0.05 * sum(d for i, d in enumerate(raw_deltas) if i != dominant)
            source = sources[dominant] + "_dominant_vector"
        else:
            z_delta = sum(raw_deltas)
            source = "+".join(sources)
        z = z_bg + z_delta
        sigma = max(sigmas) * (1.15 if len(candidate) > 1 else 1.0)

    mu_out = inverse_transform(axis_eval, z)
    if not axis_eval.get("log_scale") and axis_id != "body_temperature":
        mu_out = max(mu_out, 0.0)
    return axis_eval, mu_out, max(sigma, 1e-6), source


def coupling_to_corr(c):
    rel = c.get("relationship", "")
    corr = parse_interval(c.get("correlation_range"))
    if corr is not None:
        r = 0.5 * (corr[0] + corr[1])
    elif rel in ("negative_correlation", "opposite_direction"):
        r = -0.45
    else:
        r = 0.45
    if rel in ("negative_correlation", "opposite_direction"):
        r = -abs(r)
    elif rel in ("positive_correlation", "same_direction", "source_leads_target", "target_leads_source"):
        if corr is None:
            r = abs(r)
    return float(np.clip(r, -0.95, 0.95))


def coupling_type(c):
    return str(c.get("coupling_type") or "noise_correlation").strip().lower()


def is_noise_coupling(c):
    return coupling_type(c) in NOISE_COUPLING_TYPES


def is_drift_coupling(c):
    return coupling_type(c) in DRIFT_COUPLING_TYPES and bool(c.get("effect_direction"))


def apply_coupling_mod(r, mod):
    effect = mod.get("effect")
    factor = midpoint(mod.get("factor_range"), 1.0)
    if effect in ("weaken", "decouple"):
        r *= factor
    elif effect == "strengthen":
        r *= factor
    elif effect == "invert":
        r *= -factor
    elif effect == "delay":
        r *= min(factor, 0.8)
    return float(np.clip(r, -0.95, 0.95))


def nearest_corr_psd(corr):
    corr = 0.5 * (corr + corr.T)
    vals, vecs = np.linalg.eigh(corr)
    vals = np.clip(vals, 1e-6, None)
    psd = (vecs * vals) @ vecs.T
    d = np.sqrt(np.clip(np.diag(psd), 1e-12, None))
    psd = psd / np.outer(d, d)
    np.fill_diagonal(psd, 1.0)
    return psd


def build_corr(axis_ids, candidate, manifolds, risk_payloads, background_axes):
    idx = {a: i for i, a in enumerate(axis_ids)}
    corr = np.eye(len(axis_ids))

    for disease in candidate:
        for c in manifolds[disease]["axis_couplings"]:
            if not is_noise_coupling(c):
                continue
            src = c.get("source_axis_id")
            tgt = c.get("target_axis_id")
            if src not in idx or tgt not in idx:
                continue
            r = coupling_to_corr(c)
            i, j = idx[src], idx[tgt]
            if abs(r) > abs(corr[i, j]):
                corr[i, j] = corr[j, i] = r

    for disease in candidate:
        for mod in risk_payloads[disease]["coupling_mods"]:
            src = mod.get("source_axis_id")
            tgt = mod.get("target_axis_id")
            if src not in idx or tgt not in idx:
                continue
            i, j = idx[src], idx[tgt]
            corr[i, j] = corr[j, i] = apply_coupling_mod(corr[i, j], mod)

    return nearest_corr_psd(corr)


def mvn_logpdf(x, mu, sigmas, corr):
    sigmas = np.maximum(np.asarray(sigmas, dtype=float), 1e-6)
    cov = corr * np.outer(sigmas, sigmas)
    jitter = 1e-6
    for _ in range(5):
        try:
            chol = np.linalg.cholesky(cov + np.eye(len(x)) * jitter)
            diff = x - mu
            sol = np.linalg.solve(chol, diff)
            quad = float(sol @ sol)
            logdet = 2.0 * float(np.sum(np.log(np.diag(chol))))
            return -0.5 * (quad + logdet + len(x) * math.log(2.0 * math.pi))
        except np.linalg.LinAlgError:
            jitter *= 10.0
    return float("-inf")


def use_grid_scoring():
    return SCORE_MODE in {"grid", "fast", "deterministic"}


def iter_candidate_time_samples(candidate, manifolds, rng):
    if use_grid_scoring():
        for i in range(TIME_GRID_N):
            q = (i + 0.5) / TIME_GRID_N
            yield {
                disease: float(q * disease_t_max(disease, manifolds[disease]))
                for disease in candidate
            }, None
        return

    for _ in range(N_MC):
        yield {
            disease: float(rng.uniform(0.0, disease_t_max(disease, manifolds[disease])))
            for disease in candidate
        }, rng


def iter_background_samples(rng):
    if use_grid_scoring():
        yield None
        return
    for _ in range(N_MC):
        yield rng


def score_candidate(case, candidate, manifolds, background_axes):
    background_axes = background_axes_for_case(background_axes, case, candidate)
    rng = np.random.default_rng(deterministic_seed(candidate + (case.get("case_id"),)))
    obs = case["observations_by_axis"]
    axis_ids = conditional_axis_ids(case, candidate, manifolds, background_axes)
    if not axis_ids:
        return None

    risk_payloads = {}
    anchor_penalty, anchor_support = combo_anchor_penalty(case, candidate, manifolds, background_axes)
    log_prior = COMBO_LOG_PENALTY * (len(candidate) - 1) + anchor_penalty
    for disease in candidate:
        axis_mods, coupling_mods, lp = matched_risk_payload(
            manifolds[disease],
            case_risk_context(case, disease),
        )
        risk_payloads[disease] = {
            "axis_mods": axis_mods,
            "coupling_mods": coupling_mods,
            "log_prior": lp,
        }
        log_prior += lp

    corr = build_corr(axis_ids, candidate, manifolds, risk_payloads, background_axes)
    log_joint = []
    best = None
    best_lp = float("-inf")

    for t_by_disease, sample_rng in iter_candidate_time_samples(candidate, manifolds, rng):
        x = []
        mu = []
        sigmas = []
        contrib_meta = []
        for axis_id in axis_ids:
            endpoint = combo_axis_endpoint(axis_id, candidate, t_by_disease, manifolds, background_axes, risk_payloads, sample_rng)
            if endpoint is None:
                continue
            axis, mu_value, sigma, source = endpoint
            obs_value = observation_value_for_axis(obs[axis_id], axis, axis_id)
            x.append(transform(axis, obs_value))
            mu.append(transform(axis, mu_value))
            sigmas.append(sigma)
            contrib_meta.append((axis_id, obs_value, axis.get("unit"), mu_value, source))

        lp = mvn_logpdf(np.asarray(x), np.asarray(mu), np.asarray(sigmas), corr) + log_prior
        log_joint.append(lp)
        if lp > best_lp:
            best_lp = lp
            best = {
                "t_by_disease": t_by_disease,
                "mu": mu,
                "x": x,
                "sigmas": sigmas,
                "meta": contrib_meta,
            }

    log_marginal = float(logsumexp(log_joint) - math.log(len(log_joint)))
    return {
        "candidate": "+".join(candidate),
        "candidate_tuple": candidate,
        "log_marginal": log_marginal,
        "mean_log_per_axis": log_marginal / len(axis_ids),
        "n_axes": len(axis_ids),
        "axis_ids": axis_ids,
        "log_prior": log_prior,
        "anchor_support": anchor_support,
        "best": best,
    }


def score_background_null(case, background_axes):
    """Score the case under a pure risk-adjusted background model.

    This is the OOD/null comparison: no disease vector field, no disease prior,
    and no disease couplings. The runtime returns the delta; downstream decides
    how much Bayes-factor evidence is enough for an in-atlas call.
    """
    background_axes = background_axes_for_case(background_axes, case, ())
    rng = np.random.default_rng(deterministic_seed(("background_null", case.get("case_id"))))
    obs = case["observations_by_axis"]
    axis_ids = conditional_axis_ids(case, tuple(), {}, background_axes)
    if not axis_ids:
        return None

    corr = build_corr(axis_ids, tuple(), {}, {}, background_axes)
    log_joint = []
    best = None
    best_lp = float("-inf")

    for sample_rng in iter_background_samples(rng):
        x = []
        mu = []
        sigmas = []
        contrib_meta = []
        for axis_id in axis_ids:
            axis = background_axes[axis_id]
            mu_value, _ = sample_mu_and_baseline(axis, -1.0, sample_rng)
            obs_value = observation_value_for_axis(obs[axis_id], axis, axis_id)
            x.append(transform(axis, obs_value))
            mu.append(transform(axis, mu_value))
            sigmas.append(axis_sigma(axis))
            contrib_meta.append((axis_id, obs_value, axis.get("unit"), mu_value, axis.get("_source", "base_measure_background")))

        lp = mvn_logpdf(np.asarray(x), np.asarray(mu), np.asarray(sigmas), corr)
        log_joint.append(lp)
        if lp > best_lp:
            best_lp = lp
            best = {
                "mu": mu,
                "x": x,
                "sigmas": sigmas,
                "meta": contrib_meta,
            }

    log_marginal = float(logsumexp(log_joint) - math.log(len(log_joint)))
    return {
        "candidate": "background_only",
        "candidate_tuple": tuple(),
        "log_marginal": log_marginal,
        "mean_log_per_axis": log_marginal / len(axis_ids),
        "n_axes": len(axis_ids),
        "axis_ids": axis_ids,
        "log_prior": 0.0,
        "anchor_support": {},
        "best": best,
    }


def expected_tuple(case):
    if case.get("expected_manifolds"):
        return tuple(case["expected_manifolds"])
    if case.get("expected_manifold"):
        return (case["expected_manifold"],)
    return tuple()


def candidate_tuples(labels):
    singles = [(label,) for label in labels]
    pairs = list(itertools.combinations(labels, 2)) if MAX_COMBO_SIZE >= 2 else []
    return singles + pairs


def candidate_allowed_for_case(case, candidate, manifolds):
    """Apply case-stage eligibility for leaves that require post-workup evidence."""
    case_stage = case.get("diagnostic_stage")
    for disease in candidate:
        scope = manifolds[disease].get("distillation_scope") or {}
        if not isinstance(scope, dict):
            continue
        required_stage = scope.get("candidate_requires_diagnostic_stage")
        if required_stage and case_stage != required_stage:
            return False
    return True


def main():
    manifolds = {label: load_manifold(path) for label, path in MANIFOLD_PATHS.items()}
    background_axes = build_background_axes(manifolds, load_master_axes())
    cases = [load_case(path) for path in sorted(CASE_DIR.glob("v5_case_*.json"))]
    if CASE_FILTER:
        cases = [
            case for case in cases
            if any(token in case.get("case_id", "") or token in str(case.get("source_pmcid", "")) for token in CASE_FILTER)
        ]
    if ONLY_COMBO_CASES:
        cases = [case for case in cases if len(expected_tuple(case)) > 1]
    candidates = candidate_tuples(tuple(MANIFOLD_PATHS))

    lines = []
    lines.append("=" * 100)
    lines.append("V5 joint SDE PMC case ranking test")
    lines.append("=" * 100)
    lines.append(
        f"N_MC={N_MC}, seed={SEED}, combo_penalty={COMBO_LOG_PENALTY}, "
        f"combo_anchor_threshold={COMBO_ANCHOR_THRESHOLD}"
    )
    if use_grid_scoring():
        lines.append(f"Score mode: {SCORE_MODE} time_grid_n={TIME_GRID_N} (deterministic midpoint parameter sampling)")
    else:
        lines.append(f"Score mode: {SCORE_MODE} monte_carlo_samples={N_MC}")
    lines.append("Runtime features: joint covariance from axis_couplings; risk-factor axis/coupling modulation; vector-field superposition for 2-disease candidates.")
    lines.append(f"Manifold discovery: {len(MANIFOLD_PATHS)} root distillation files from {DISTILL_DIR / 'v5_*.json'}")
    lines.append(f"Candidate sets: singles={len(manifolds)}, total_ranked={len(candidates)}, max_combo_size={MAX_COMBO_SIZE}")
    if CASE_FILTER:
        lines.append(f"Case filter: {', '.join(CASE_FILTER)}")
    if ONLY_COMBO_CASES:
        lines.append("Case filter: expected_manifolds length > 1")
    lines.append(f"Cases loaded for this run: {len(cases)}")
    lines.append("")
    lines.append("Manifolds:")
    for label, manifold in manifolds.items():
        nonhaz = sum(1 for a in manifold["axes"].values() if a.get("category") != "derived_hazard")
        mechanisms = sum(1 for a in manifold["axes"].values() if a.get("category") == LATENT_MECHANISM_CATEGORY)
        lines.append(
            f"  {label:12s}: axes={nonhaz:2d}, mechanisms={mechanisms:2d}, "
            f"mech_edges={len(manifold.get('mechanism_edges', [])):2d}, "
            f"couplings={len(manifold['axis_couplings']):2d}, risk_factors={len(manifold['risk_factors']):2d}"
        )
    lines.append(f"Base-measure/background axes: {len(background_axes)}")
    lines.append("")

    total_single = total_combo = pass_single = pass_combo = 0
    for case in cases:
        expected = expected_tuple(case)
        if not expected or not set(expected).issubset(set(MANIFOLD_PATHS)):
            continue

        lines.append("-" * 100)
        lines.append(f"{case['case_id']}  expected={'+'.join(expected)}")
        lines.append(f"source: PMID {case.get('source_pmid')} / {case.get('source_pmcid')} / {case.get('source_url')}")
        lines.append(f"paper diagnosis: {case.get('disease_label_per_paper')}")
        lines.append(f"observed axes: {len(case['observations_by_axis'])}")
        if case.get("risk_context"):
            ctx = "; ".join(f"{r.get('factor')}={r.get('category')}" for r in case["risk_context"])
            lines.append(f"risk context: {ctx}")

        scores = []
        for cand in candidates:
            if not candidate_allowed_for_case(case, cand, manifolds):
                continue
            score = score_candidate(case, cand, manifolds, background_axes)
            if score is not None:
                scores.append(score)
        scores.sort(key=lambda s: -s["log_marginal"])
        best_overall = scores[0]
        single_scores = [s for s in scores if len(s["candidate_tuple"]) == 1]
        best_single = max(single_scores, key=lambda s: s["log_marginal"])
        background_null = score_background_null(case, background_axes)

        lines.append("")
        lines.append("[joint SDE ranking: all candidates]")
        for score in scores:
            marker = "*" if score is best_overall else " "
            anchor = ""
            if score["anchor_support"]:
                anchor = " anchors=" + ",".join(f"{k}:{v:.1f}" for k, v in score["anchor_support"].items())
            lines.append(
                f"{marker} {score['candidate']:23s} logP={score['log_marginal']:+10.2f} "
                f"mean={score['mean_log_per_axis']:+8.3f} n={score['n_axes']:2d} prior={score['log_prior']:+6.2f}{anchor}"
            )

        lines.append("")
        lines.append("[best single-manifold diagnostic]")
        for score in sorted(single_scores, key=lambda s: -s["log_marginal"]):
            marker = "*" if score is best_single else " "
            lines.append(
                f"{marker} {score['candidate']:12s} logP={score['log_marginal']:+10.2f} "
                f"mean={score['mean_log_per_axis']:+8.3f} prior={score['log_prior']:+6.2f}"
            )

        lines.append("")
        lines.append("[OOD/null-model check: known manifold(s) vs pure background]")
        if background_null is None:
            lines.append("  background_only: no scorable observed axes")
        else:
            delta_best = best_overall["log_marginal"] - background_null["log_marginal"]
            delta_single = best_single["log_marginal"] - background_null["log_marginal"]
            lines.append(
                f"  logP_best_known={best_overall['log_marginal']:+10.2f} "
                f"candidate={best_overall['candidate']}"
            )
            lines.append(
                f"  logP_best_single={best_single['log_marginal']:+10.2f} "
                f"candidate={best_single['candidate']}"
            )
            lines.append(
                f"  logP_background_only={background_null['log_marginal']:+10.2f} "
                f"mean={background_null['mean_log_per_axis']:+8.3f} n={background_null['n_axes']:2d}"
            )
            lines.append(f"  delta_to_null_best_known={delta_best:+10.2f}")
            lines.append(f"  delta_to_null_best_single={delta_single:+10.2f}")
            lines.append("  interpretation: runtime outputs deltas only; no hard unknown-disease threshold is applied.")

        if len(expected) == 1:
            total_single += 1
            ok = best_single["candidate_tuple"] == expected
            pass_single += int(ok)
            lines.append(f"single validation: best_single={best_single['candidate']}  {'PASS' if ok else 'FAIL'}")
        else:
            total_combo += 1
            ok = set(best_overall["candidate_tuple"]) == set(expected)
            pass_combo += int(ok)
            lines.append(f"combo validation: best_overall={best_overall['candidate']}  {'PASS' if ok else 'FAIL'}")

        best = best_overall["best"]
        if best:
            t_text = ", ".join(f"{k}=day{v:.1f}" for k, v in best["t_by_disease"].items())
            lines.append(f"best latent times: {t_text}")
            residuals = []
            for (axis_id, obs_value, unit, mu_value, source), x, m, sigma in zip(best["meta"], best["x"], best["mu"], best["sigmas"]):
                z = abs((x - m) / max(sigma, 1e-6))
                residuals.append((z, axis_id, obs_value, unit, mu_value, source))
            worst = sorted(residuals, reverse=True)[:5]
            lines.append("largest standardized residuals: " + "; ".join(
                f"{axis_id} obs={obs_value:g} {unit} mu={mu_value:g} via={source} z={z:.1f}"
                for z, axis_id, obs_value, unit, mu_value, source in worst
            ))
        lines.append("")

    lines.append("=" * 100)
    lines.append(f"Single-manifold validation: {pass_single}/{total_single} PASS")
    lines.append(f"Combo-manifold validation:  {pass_combo}/{total_combo} PASS")
    lines.append("")
    lines.append("Notes:")
    lines.append("  - This runtime consumes latent_mechanisms, mechanism_edges, axis_couplings, and risk-factor modulation fields.")
    lines.append("  - Pair candidates are two-disease vector-field superpositions, not labels emitted by the LLM.")
    lines.append("  - Opposing disease forces are combined in standardized axis space so a strong TTP platelet-consumption field is not canceled by weak AOSD reactive thrombocytosis.")
    lines.append("  - OOD/null-model check reports logP_best_known - logP_background_only; it deliberately does not apply a hard unknown-disease threshold.")
    lines.append("  - Culture/ADAMTS13-confirmatory axes are allowed if present in the case JSON; remove them from case evidence if testing presentation-only diagnosis.")

    text = "\n".join(lines)
    RESULT_PATH.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[done] wrote {RESULT_PATH}")


if __name__ == "__main__":
    main()
