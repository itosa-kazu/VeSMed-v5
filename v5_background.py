"""
Risk-factor-adjusted base-measure helpers.

These modifiers are used only when an axis falls back to the global/background
measure. If a candidate disease manifold already owns an axis, disease-specific
risk modulation remains responsible for that axis.
"""
import copy
import json
from pathlib import Path


ROOT = Path(__file__).parent.resolve()
BACKGROUND_MODIFIERS_PATH = ROOT / "background_modifiers.json"
CONDITION_SCOPE_PATH = ROOT / "condition_scope.json"


BASE_MEASURE_OVERRIDES = {
    "blood_culture_bacterial_load": {"unit": "CFU_per_mL", "baseline_range": (1e-9, 1e-6), "log_scale": True},
    "blood_culture_positivity_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.02), "log_scale": False},
    "pathogen_identification_confidence": {"unit": "probability_0_1", "baseline_range": (0.0, 0.05), "log_scale": False},
    "gram_negative_bacteremia_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.03), "log_scale": False},
    "active_antibiotic_coverage_probability": {"unit": "probability_0_1", "baseline_range": (0.6, 0.95), "log_scale": False},
    "ceftriaxone_susceptibility_probability": {"unit": "probability_0_1", "baseline_range": (0.55, 0.95), "log_scale": False},
    "piperacillin_tazobactam_susceptibility_probability": {"unit": "probability_0_1", "baseline_range": (0.6, 0.95), "log_scale": False},
    "carbapenem_susceptibility_probability": {"unit": "probability_0_1", "baseline_range": (0.8, 0.99), "log_scale": False},
    "esbl_risk_activity": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.2), "log_scale": False},
    "pseudomonas_risk_activity": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.15), "log_scale": False},
    "carbapenem_resistance_risk_activity": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.08), "log_scale": False},
    "healthcare_associated_resistance_risk_activity": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.15), "log_scale": False},
    "initial_inactive_antibiotic_exposure_activity": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.15), "log_scale": False},
    "urinary_source_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.2), "log_scale": False},
    "biliary_source_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.1), "log_scale": False},
    "intra_abdominal_source_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.12), "log_scale": False},
    "pulmonary_source_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.12), "log_scale": False},
    "catheter_source_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.08), "log_scale": False},
    "urinary_obstruction_activity": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.08), "log_scale": False},
    "biliary_obstruction_activity": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.08), "log_scale": False},
    "obstructive_pyelonephritis_activity": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.08), "log_scale": False},
    "intra_abdominal_abscess_activity": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.08), "log_scale": False},
    "pneumonia_infiltrate_extent": {"unit": "relative_extent_0_1", "baseline_range": (0.0, 0.08), "log_scale": False},
    "infected_catheter_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.08), "log_scale": False},
    "drainable_focus_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.12), "log_scale": False},
    "source_control_need": {"unit": "relative_activity_0_1", "baseline_range": (0.0, 0.15), "log_scale": False},
    "source_control_adequacy": {"unit": "relative_activity_0_1", "baseline_range": (0.75, 1.0), "log_scale": False},
}


def load_background_modifiers(path=BACKGROUND_MODIFIERS_PATH):
    if not path.exists():
        return {"modifiers": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_condition_scope(path=CONDITION_SCOPE_PATH):
    if not path.exists():
        return {"conditions": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def _as_str(value):
    return "" if value is None else str(value).strip()


def _category_matches(category, patterns):
    category = _as_str(category)
    return "*" in patterns or category in patterns


def _normalize_context_item(item):
    return {
        "factor": _as_str(item.get("factor")),
        "category": _as_str(item.get("category")),
        "scope": _as_str(item.get("scope")),
        "source": item.get("source"),
    }


def background_context_for_case(case):
    """Return case-level context for base-measure adjustment.

    This is intentionally disease-agnostic. Disease-specific context filtering
    still happens in the disease runtime.
    """
    context = [_normalize_context_item(item) for item in case.get("risk_context", [])]
    demo = case.get("demographics") or {}
    age = demo.get("age")
    sex = _as_str(demo.get("sex")).lower()

    if isinstance(age, (int, float)):
        if age < 50:
            context.append({"factor": "age", "category": "age_18_49", "scope": "", "source": "demographics"})
        elif age < 65:
            context.append({"factor": "age", "category": "age_50_64", "scope": "", "source": "demographics"})
        elif age < 80:
            context.append({"factor": "age", "category": "age_65_79", "scope": "", "source": "demographics"})
        else:
            context.append({"factor": "age", "category": "age_ge80", "scope": "", "source": "demographics"})
        if age > 60:
            context.append({"factor": "age", "category": "older_adult_over_60_years", "scope": "", "source": "demographics"})
        if age >= 65:
            context.append({"factor": "age", "category": "older_adult_over_65", "scope": "", "source": "demographics"})

    if sex in ("f", "female"):
        context.append({"factor": "sex", "category": "female", "scope": "", "source": "demographics"})
    elif sex in ("m", "male"):
        context.append({"factor": "sex", "category": "male", "scope": "", "source": "demographics"})

    return context


def _condition_scope_for_factor(factor, condition_scope):
    return (condition_scope.get("conditions") or {}).get(factor) or {}


def _skip_background_for_context(item, candidate, condition_scope):
    explicit_scope = item.get("scope")
    if explicit_scope in ("disease_manifold", "disease_specific_modifier"):
        return True

    scope = _condition_scope_for_factor(item.get("factor"), condition_scope)
    blocked = set(scope.get("skip_background_modifier_when_candidate_contains") or [])
    return bool(blocked.intersection(set(candidate)))


def _matching_axis_modulations(axis_id, context, candidate, background_modifiers, condition_scope):
    matches = []
    for mod in background_modifiers.get("modifiers") or []:
        factor = _as_str(mod.get("factor"))
        categories = [_as_str(c) for c in (mod.get("categories") or ["*"])]
        axis_mod = (mod.get("axis_modulations") or {}).get(axis_id)
        if not factor or axis_mod is None:
            continue
        for raw_item in context:
            item = _normalize_context_item(raw_item)
            if item["factor"] != factor:
                continue
            if not _category_matches(item["category"], categories):
                continue
            if _skip_background_for_context(item, candidate, condition_scope):
                continue
            matches.append((item, axis_mod))
    return matches


def _parse_pair(value):
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        try:
            lo = float(value[0])
            hi = float(value[1])
        except (TypeError, ValueError):
            return None
        return (min(lo, hi), max(lo, hi))
    return None


def _multiply_interval(interval, factor_interval):
    lo, hi = interval
    flo, fhi = factor_interval
    values = [lo * flo, lo * fhi, hi * flo, hi * fhi]
    return (min(values), max(values))


def _add_interval(interval, add_interval):
    lo, hi = interval
    alo, ahi = add_interval
    return (lo + alo, hi + ahi)


def _widen_interval(interval, factor):
    factor_interval = _parse_pair(factor)
    if factor_interval is None:
        return interval
    f = max(1.0, 0.5 * (factor_interval[0] + factor_interval[1]))
    lo, hi = interval
    center = 0.5 * (lo + hi)
    half_width = 0.5 * (hi - lo) * f
    return (center - half_width, center + half_width)


def _converted_override(axis_mod, axis, axis_id, convert_value):
    override = _parse_pair(axis_mod.get("baseline_range_override"))
    if override is None:
        return None
    unit = axis_mod.get("unit") or axis.get("unit")
    target_unit = axis.get("unit")
    lo = convert_value(override[0], unit, target_unit, axis_id)
    hi = convert_value(override[1], unit, target_unit, axis_id)
    return (min(lo, hi), max(lo, hi))


def apply_background_modifiers_to_axis(axis, context, candidate, background_modifiers, condition_scope, convert_value):
    axis_id = axis.get("axis_id")
    if not axis_id:
        return axis

    adjusted = copy.deepcopy(axis)
    baseline = _parse_pair(adjusted.get("baseline_range"))
    if baseline is None:
        return adjusted

    applied = []
    for item, axis_mod in _matching_axis_modulations(
        axis_id,
        context,
        candidate,
        background_modifiers,
        condition_scope,
    ):
        override = _converted_override(axis_mod, adjusted, axis_id, convert_value)
        if override is not None:
            baseline = override
        factor = _parse_pair(axis_mod.get("baseline_factor"))
        if factor is not None:
            baseline = _multiply_interval(baseline, factor)
        add = _parse_pair(axis_mod.get("baseline_add"))
        if add is not None:
            baseline = _add_interval(baseline, add)
        baseline = _widen_interval(baseline, axis_mod.get("widen_factor"))
        applied.append({
            "factor": item["factor"],
            "category": item["category"],
            "rationale": axis_mod.get("rationale"),
        })

    if not applied:
        return adjusted

    if adjusted.get("log_scale"):
        baseline = (max(1e-12, baseline[0]), max(1e-12, baseline[1]))
    elif axis_id != "body_temperature":
        baseline = (max(0.0, baseline[0]), max(0.0, baseline[1]))
    adjusted["baseline_range"] = (min(baseline), max(baseline))
    adjusted["_source"] = "risk_factor_adjusted_background"
    adjusted["_applied_background_modifiers"] = applied
    return adjusted


def adjust_background_axes(background_axes, case, candidate, background_modifiers, condition_scope, convert_value):
    context = background_context_for_case(case)
    return {
        axis_id: apply_background_modifiers_to_axis(
            axis,
            context,
            candidate,
            background_modifiers,
            condition_scope,
            convert_value,
        )
        for axis_id, axis in background_axes.items()
    }
