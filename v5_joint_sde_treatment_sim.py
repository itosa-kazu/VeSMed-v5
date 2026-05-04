"""
V5 joint SDE treatment vector-field simulator.

This consumes the same current-schema distillations as the joint diagnostic
runtime, but now adds treatment vector fields:

    dx = (f_D1 + f_D2 + A_treatment(t)) dt + Sigma(x,t) dW

The output ranks treatment policies by RMST over a short clinical horizon and
shows how key axes move versus no treatment.
"""
import itertools
import math
import os
import sys
from pathlib import Path

import numpy as np

import v5_joint_sde_case_test as joint

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROOT = Path(__file__).parent.resolve()
DISTILL_DIR = ROOT / "distillations"
CASE_DIR = DISTILL_DIR / "cases"
RESULT_PATH = DISTILL_DIR / "joint_sde_treatment_result.txt"

N_PARTICLES = 260
DT = 1.0
HORIZON_DAYS = 30
KAPPA = 0.55
NOISE_SCALE = 0.06
TOP_COMBO_TREATMENTS_PER_DISEASE = 5
TOP_ROWS = 8
SUMMARY_DAY = 7
TOP_BUNDLE_BASE_TREATMENTS = 6
MAX_TREATMENTS_PER_DISEASE_BUNDLE = 4
MAX_SINGLE_DISEASE_POLICIES = 48
MAX_COMBO_OPTIONS_PER_DISEASE = 12
STAGED_POLICY_START_EPS = 1e-6


def env_csv(name):
    raw = os.environ.get(name, "")
    return [part.strip() for part in raw.split(",") if part.strip()]


CASE_FILTER = env_csv("VESMED_CASE_FILTER")

DRUG_SPECIFIC_COVERAGE_AXES = {
    "ceftriaxone_iv": "ceftriaxone_susceptibility_probability",
    "ceftriaxone_2g_iv_daily": "ceftriaxone_susceptibility_probability",
    "piperacillin_tazobactam_iv": "piperacillin_tazobactam_susceptibility_probability",
    "piperacillin_tazobactam_4_5g_iv_q6_8h": "piperacillin_tazobactam_susceptibility_probability",
    "meropenem_iv": "carbapenem_susceptibility_probability",
    "meropenem_1g_iv_q8h": "carbapenem_susceptibility_probability",
    "ertapenem_iv": "carbapenem_susceptibility_probability",
}

SEPSIS_ADJUNCT_DRUGS = {
    "source_control_procedure",
    "balanced_crystalloid_iv_resuscitation",
    "supplemental_oxygen",
}

KEY_AXIS_PRIORITY = [
    "mortality_hazard",
    "major_bleeding_hazard",
    "intracranial_hemorrhage_hazard",
    "acute_kidney_injury_hazard",
    "ards_hazard",
    "dic_hazard",
    "shock_hazard",
    "ischemic_stroke_hazard",
    "myocardial_injury_hazard",
    "mas_hlh_hazard",
    "blood_culture_bacterial_load",
    "serum_procalcitonin",
    "serum_crp",
    "body_temperature",
    "serum_lactate",
    "mean_arterial_pressure",
    "platelet_count",
    "hemoglobin",
    "serum_ldh",
    "schistocyte_fraction",
    "adamts13_activity",
    "anti_adamts13_igg_inhibitor_titer",
    "serum_ferritin",
]


def disease_hazard_axis(manifold):
    for axis_id, axis in manifold["axes"].items():
        if axis_id.startswith("mortality_hazard_in_") and axis.get("category") == "derived_hazard":
            return axis_id
    for axis_id, axis in manifold["axes"].items():
        if "mortality_hazard" in axis_id and axis.get("category") == "derived_hazard":
            return axis_id
    for axis_id, axis in manifold["axes"].items():
        if axis.get("category") == "derived_hazard":
            return axis_id
    return None


def policy_start_day(treatment):
    return max(float(treatment.get("_policy_start_day") or 0.0), 0.0)


def scheduled_treatment(treatment, start_day):
    start_day = max(float(start_day or 0.0), 0.0)
    if start_day <= STAGED_POLICY_START_EPS:
        return treatment
    staged = dict(treatment)
    staged["_policy_start_day"] = start_day
    return staged


def policy_treatment_label(disease, treatment):
    label = f"{disease}:{treatment.get('drug')}"
    start_day = policy_start_day(treatment)
    if start_day > STAGED_POLICY_START_EPS:
        label += f"@day{start_day:g}"
    return label


def policy_name(policy):
    if not policy:
        return "(no treatment)"
    return " + ".join(policy_treatment_label(d, t) for d, t in policy)


def midpoint(interval, default=1.0):
    return joint.midpoint(interval, default)


def interval_mid(value, default=0.0):
    parsed = joint.parse_interval(value)
    if parsed is None:
        return default
    return 0.5 * (parsed[0] + parsed[1])


def treatment_onset(treatment):
    return max(interval_mid(treatment.get("onset_delay_days"), 0.0), 0.0)


def treatment_active(treatment, elapsed_day):
    return elapsed_day >= policy_start_day(treatment) + treatment_onset(treatment)


def value_from_params(baseline, peak_day, peak_value, plateau, half_life, t):
    peak_day = max(float(peak_day), 1e-6)
    plateau_end = peak_day + max(float(plateau), 0.0)
    if t <= 0:
        return baseline
    if t < peak_day:
        return baseline + (peak_value - baseline) * (t / peak_day)
    if t < plateau_end:
        return peak_value
    if half_life is None:
        return peak_value
    hl = max(float(half_life), 1e-6)
    decay = 0.5 ** ((t - plateau_end) / hl)
    return baseline + (peak_value - baseline) * decay


def scaled_factor(interval, effect_scale, default=1.0):
    factor = midpoint(interval, default)
    return max(0.0, 1.0 + effect_scale * (factor - 1.0))


def scaled_half_life(mod, half_life, effect_scale):
    target = midpoint(mod.get("decline_half_life_days"), half_life if half_life is not None else 30.0)
    if target is None:
        return None
    base = half_life if half_life is not None else target
    return max(1e-6, base + effect_scale * (target - base))


def treatment_axis_ids(treatment):
    ids = set((treatment.get("trajectory_modifications") or {}).keys())
    ids.update(treatment.get("required_context_axes") or [])
    for item in treatment.get("effect_modifiers") or []:
        if item.get("axis_id"):
            ids.add(item["axis_id"])
    for item in treatment.get("push_targets") or []:
        if item.get("axis_id"):
            ids.add(item["axis_id"])
    for item in treatment.get("side_effects") or []:
        if item.get("axis_id"):
            ids.add(item["axis_id"])
    sigma = treatment.get("sigma_modulation") or {}
    for axis_id in sigma.get("axes") or []:
        ids.add(axis_id)
    return ids


def context_axis_value(axis_id, case, candidate, manifolds, background_axes):
    obs = case["observations_by_axis"].get(axis_id)
    axis = background_axes.get(axis_id) or eval_axis(axis_id, candidate, manifolds, background_axes)
    if axis is None:
        return None, None
    if obs is not None:
        return (
            joint.convert_value(obs["value"], obs.get("unit"), axis.get("unit"), axis_id),
            axis,
        )
    baseline = joint.parse_interval(axis.get("baseline_range"))
    if baseline is None:
        return None, axis
    return midpoint(baseline), axis


def treatment_drug(treatment):
    return treatment.get("drug") or ""


def treatment_specific_context_axis_value(axis_id, treatment, case, candidate, manifolds, background_axes):
    if axis_id == "active_antibiotic_coverage_probability":
        coverage_axis = DRUG_SPECIFIC_COVERAGE_AXES.get(treatment_drug(treatment))
        if coverage_axis:
            value, axis = context_axis_value(coverage_axis, case, candidate, manifolds, background_axes)
            if value is not None:
                return value, axis
    return context_axis_value(axis_id, case, candidate, manifolds, background_axes)


def axis_weight_for_condition(value, axis, modifier):
    """Continuous [0,1] weight for how fully the modifier's condition is met.

    For probability / activity / severity axes already on [0,1] the axis value
    *is* the weight; the runtime does not invent thresholds. For axes outside
    [0,1] the schema must supply an explicit ``threshold``; absent that the
    modifier is treated as inactive. ``unknown`` triggers when value is missing.
    """
    condition = modifier.get("condition")

    if condition == "unknown":
        return 1.0 if value is None else 0.0
    if value is None:
        return 0.0

    threshold = modifier.get("threshold")
    if isinstance(threshold, (int, float)):
        T = float(threshold)
        v = float(value)
        if condition in ("high", "above_threshold", "present"):
            return 1.0 if v >= T else 0.0
        if condition in ("low", "below_threshold", "absent"):
            return 1.0 if v <= T else 0.0
        return 0.0

    unit = joint.norm_unit(axis.get("unit") if axis else "")
    if unit in ("probability01", "relativeactivity01", "severityscore01"):
        v = max(min(float(value), 1.0), 0.0)
        if condition in ("high", "present"):
            return v
        if condition in ("low", "absent"):
            return 1.0 - v
        return 0.0

    return 0.0


def treatment_effect_scale(treatment, case, candidate, manifolds, background_axes):
    """Continuous treatment efficacy scaling driven by axis values.

    Each effect_modifier is evaluated by reading the real axis value, mapping
    it to a [0,1] weight, and combining with the distillation's factor_range.
    No hardcoded cutoffs, no fallback factors. If factor_range is missing the
    modifier is skipped rather than fabricated.
    """
    scale = 1.0
    for modifier in treatment.get("effect_modifiers") or []:
        axis_id = modifier.get("axis_id")
        if not axis_id:
            continue
        value, axis = treatment_specific_context_axis_value(
            axis_id,
            treatment,
            case,
            candidate,
            manifolds,
            background_axes,
        )
        weight = axis_weight_for_condition(value, axis, modifier)

        factor = midpoint(modifier.get("factor_range"), None)
        if factor is None:
            continue

        effect = modifier.get("effect")
        if effect == "required_for_effect":
            scale *= factor * weight
        elif effect in ("blocks", "weakens", "contraindicates", "requires_source_control"):
            f = max(min(factor, 1.0), 0.0)
            scale *= (1.0 - weight) + f * weight
        elif effect == "strengthens":
            f = max(factor, 1.0)
            scale *= 1.0 + (f - 1.0) * weight
        elif effect == "changes_toxicity":
            # Efficacy unchanged; toxicity is captured by side-effect axes / future QOL ranking.
            continue

    return max(scale, 0.0)


def treatment_hazard_rank_key(disease, treatment, manifolds):
    haz_id = disease_hazard_axis(manifolds[disease])
    mod = (treatment.get("trajectory_modifications") or {}).get(haz_id)
    if not mod:
        return 999.0
    peak = midpoint(mod.get("peak_value_factor"), 1.0)
    plateau = midpoint(mod.get("plateau_duration_factor"), 1.0)
    decline = midpoint(mod.get("decline_half_life_days"), 30.0)
    onset = treatment_onset(treatment)
    return peak * 3.0 + plateau + decline / 30.0 + onset / 10.0


def disease_policy_options(disease, manifolds, limit=None):
    treatments = list(manifolds[disease].get("treatments") or [])
    treatments.sort(key=lambda t: treatment_hazard_rank_key(disease, t, manifolds))
    if limit is not None:
        treatments = treatments[:limit]
    return [None] + treatments


def is_antimicrobial(treatment):
    drug_class = str(treatment.get("drug_class") or "").lower()
    drug = treatment_drug(treatment).lower()
    antimicrobial_terms = (
        "antibiotic",
        "antimicrobial",
        "beta_lactam",
        "betalactam",
        "cephalosporin",
        "ceftriaxone",
        "cefepime",
        "ceftazidime",
        "piperacillin",
        "tazobactam",
        "carbapenem",
        "meropenem",
        "ertapenem",
        "imipenem",
        "aztreonam",
        "aminoglycoside",
        "fluoroquinolone",
        "ciprofloxacin",
    )
    text = f"{drug_class} {drug}"
    return any(term in text for term in antimicrobial_terms)


def is_sepsis_adjunct(treatment):
    return treatment_drug(treatment) in SEPSIS_ADJUNCT_DRUGS


def treatment_lane(treatment):
    """Clinical lane used to avoid combining alternative therapies as a bundle."""
    drug = treatment_drug(treatment).lower()
    drug_class = str(treatment.get("drug_class") or "").lower()
    role = str(treatment.get("empiric_or_definitive_role") or "").lower()
    mode = str(treatment.get("mode") or "").lower()
    text = " ".join([drug, drug_class, role, mode])

    if is_antimicrobial(treatment):
        return "antimicrobial"
    if "source_control" in drug:
        return "source_control"
    if "plasma_exchange" in text or "plasma_replacement" in text or "plasma_infusion" in text:
        return "plasma_replacement"
    if "glucocorticoid" in text or "steroid" in text or "prednisone" in text or "prednisolone" in text:
        return "glucocorticoid"
    if "anti_cd20" in text or "rituximab" in text:
        return "b_cell_depletion"
    if "anti_vwf" in text or "caplacizumab" in text:
        return "anti_vwf"
    if "il-1" in text or "il1" in text:
        return "il1_blockade"
    if "il-6" in text or "il6" in text:
        return "il6_blockade"
    if "jak" in text:
        return "jak_inhibition"
    if "tnf" in text:
        return "tnf_blockade"
    if "calcineurin" in text or "cyclosporine" in text:
        return "calcineurin_inhibition"
    if "blood_product" in text:
        if "platelet" in drug:
            return "platelet_transfusion"
        if "red_blood" in drug or "rbc" in drug:
            return "red_cell_transfusion"
        return "blood_product"
    if "dialysis" in text or "kidney_replacement" in text or "renal_support" in text:
        return "renal_support"
    if "icu" in text or "critical_care" in text:
        return "critical_care"
    return drug_class or drug


def compatible_treatment_bundle(treatments):
    lanes = set()
    for treatment in treatments:
        lane = treatment_lane(treatment)
        if lane in lanes:
            return False
        lanes.add(lane)
    return True


def include_in_default_bundle_base(treatment):
    role = str(treatment.get("empiric_or_definitive_role") or "").lower()
    if role == "context_dependent" and not is_antimicrobial(treatment) and not is_sepsis_adjunct(treatment):
        return False
    return True


def bundle_base_treatments(disease, manifolds):
    treatments = [
        t
        for t in manifolds[disease].get("treatments") or []
        if include_in_default_bundle_base(t)
    ]
    ranked = sorted(treatments, key=lambda t: treatment_hazard_rank_key(disease, t, manifolds))
    base = list(ranked[:TOP_BUNDLE_BASE_TREATMENTS])

    # Keep practical adjuncts available even when they mainly push state rather
    # than reshape mortality directly.
    if disease == "D-SEPSIS-GN":
        base.extend(t for t in treatments if is_sepsis_adjunct(t))

    out = []
    seen = set()
    for treatment in base:
        drug = treatment_drug(treatment)
        if drug in seen:
            continue
        seen.add(drug)
        out.append(treatment)
    return out


def bundle_rank_key(disease, treatments, manifolds):
    if not treatments:
        return -1.0
    ranks = [min(treatment_hazard_rank_key(disease, t, manifolds), 12.0) for t in treatments]
    stage_penalty = sum(policy_start_day(t) for t in treatments) / 30.0
    return (sum(ranks) / math.sqrt(len(ranks))) + 0.05 * len(ranks) + stage_penalty


def default_stage_day(treatment, peer_treatments):
    """Generic protocol timing from distilled treatment roles and lanes.

    This is intentionally weak clinical structure: it does not hard-code a
    disease guideline. Distillation supplies lanes/roles; runtime only delays
    slower or rescue lanes when a same-disease bundle already has an immediate
    core therapy.
    """
    lane = treatment_lane(treatment)
    role = str(treatment.get("empiric_or_definitive_role") or "").lower()
    peer_lanes = {treatment_lane(t) for t in peer_treatments if t is not treatment}

    if lane in ("antimicrobial", "source_control", "plasma_replacement", "glucocorticoid"):
        return 0.0
    if lane in ("critical_care", "renal_support", "red_cell_transfusion", "platelet_transfusion"):
        return 0.0
    if lane == "anti_vwf":
        return 0.0
    if lane == "b_cell_depletion":
        return 1.0 if "plasma_replacement" in peer_lanes else 0.0
    if role == "rescue":
        return 3.0
    if lane in ("il1_blockade", "il6_blockade", "jak_inhibition", "calcineurin_inhibition"):
        return 2.0 if "glucocorticoid" in peer_lanes else 0.0
    if lane in ("conventional_dmard", "tnf_blockade"):
        return 7.0 if "glucocorticoid" in peer_lanes else 0.0
    if role == "bridge":
        return 0.0
    return 0.0


def staged_policy_variant(option):
    if not option:
        return None
    treatments = [t for _, t in option]
    staged_items = []
    changed = False
    for disease, treatment in option:
        start_day = default_stage_day(treatment, treatments)
        if start_day > STAGED_POLICY_START_EPS:
            changed = True
        staged_items.append((disease, scheduled_treatment(treatment, start_day)))
    return tuple(staged_items) if changed else None


def disease_bundle_options(disease, manifolds, limit):
    base = bundle_base_treatments(disease, manifolds)
    options = [tuple()]

    for size in range(1, min(MAX_TREATMENTS_PER_DISEASE_BUNDLE, len(base)) + 1):
        for combo in itertools.combinations(base, size):
            if not compatible_treatment_bundle(combo):
                continue
            options.append(tuple((disease, treatment) for treatment in combo))
            staged = staged_policy_variant(options[-1])
            if staged is not None:
                options.append(staged)

    deduped = []
    seen = set()
    for option in options:
        key = tuple(sorted((treatment_drug(treatment), policy_start_day(treatment)) for _, treatment in option))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(option)

    deduped.sort(key=lambda option: bundle_rank_key(disease, [t for _, t in option], manifolds))
    return deduped[:limit]


def make_policies(candidate, manifolds, case=None):
    if len(candidate) == 1:
        disease = candidate[0]
        return disease_bundle_options(disease, manifolds, MAX_SINGLE_DISEASE_POLICIES)

    option_lists = []
    for disease in candidate:
        option_lists.append(disease_bundle_options(disease, manifolds, MAX_COMBO_OPTIONS_PER_DISEASE))

    policies = []
    for combo in itertools.product(*option_lists):
        policy = tuple(item for option in combo for item in option)
        policies.append(policy)
    return policies


def policy_by_disease(policy):
    out = {}
    for disease, treatment in policy:
        out.setdefault(disease, []).append(treatment)
    return out


def sample_axis_value(axis, disease_day, elapsed_day, treatments, treatment_scales, rng):
    baseline = joint.sample_uniform(rng, axis["baseline_range"])
    peak_day = joint.sample_uniform(rng, axis["peak_day_range"]) if axis.get("peak_day_range") else None
    peak_value = joint.sample_uniform(rng, axis["peak_value_range"]) if axis.get("peak_value_range") else None
    plateau = joint.sample_uniform(rng, axis["plateau_duration_days"]) if axis.get("plateau_duration_days") else 0.0
    half_life = joint.sample_uniform(rng, axis["decline_half_life_days"]) if axis.get("decline_half_life_days") else None

    if peak_day is None or peak_value is None:
        value = baseline
    else:
        value = value_from_params(baseline, peak_day, peak_value, plateau, half_life, disease_day)

    sigma = joint.axis_sigma(axis)
    axis_id = axis["axis_id"]

    peak_factor = 1.0
    plateau_factor = 1.0
    treated_half_lives = []
    has_trajectory_mod = False
    for treatment in treatments:
        if not treatment_active(treatment, elapsed_day):
            continue
        effect_scale = treatment_scales.get(id(treatment), 1.0)
        if effect_scale == 0:
            continue
        mod = (treatment.get("trajectory_modifications") or {}).get(axis_id)
        if mod and peak_day is not None and peak_value is not None:
            has_trajectory_mod = True
            peak_factor *= scaled_factor(mod.get("peak_value_factor"), effect_scale, 1.0)
            plateau_factor *= scaled_factor(mod.get("plateau_duration_factor"), effect_scale, 1.0)
            hl = scaled_half_life(mod, half_life, effect_scale)
            if hl is not None:
                treated_half_lives.append(hl)

    if has_trajectory_mod:
        treated_peak = peak_value * peak_factor
        treated_plateau = plateau * plateau_factor
        treated_hl = min(treated_half_lives) if treated_half_lives else half_life
        value = value_from_params(baseline, peak_day, treated_peak, treated_plateau, treated_hl, disease_day)

    for treatment in treatments:
        if not treatment_active(treatment, elapsed_day):
            continue
        effect_scale = treatment_scales.get(id(treatment), 1.0)
        # scale=0 = 这治疗根本不会给（医生看到耐药 / 没脓包 / etc 直接放弃）。
        # 整段跳过：没 trajectory 改变、没 push、没 sigma 改变、也没副作用。
        # 副作用是剂量挂钩，不是疗效挂钩，所以 scale > 0 时副作用维持全量。
        if effect_scale == 0:
            continue
        mod = (treatment.get("trajectory_modifications") or {}).get(axis_id)
        if mod and peak_day is not None and peak_value is not None:
            pass

        for push in treatment.get("push_targets") or []:
            if push.get("axis_id") != axis_id:
                continue
            mag = interval_mid(push.get("magnitude_range"), 0.0)
            if push.get("direction") == "down":
                mag = -mag
            value += effect_scale * mag

        for side in treatment.get("side_effects") or []:
            if side.get("axis_id") != axis_id:
                continue
            mag = interval_mid(side.get("magnitude_range"), 0.0)
            if side.get("direction") == "down":
                mag = -mag
            value += mag

        sigma_mod = treatment.get("sigma_modulation") or {}
        if axis_id in (sigma_mod.get("axes") or []):
            factor = midpoint(sigma_mod.get("factor"), 1.0)
            sigma *= 1.0 + effect_scale * (factor - 1.0)

    if axis.get("log_scale"):
        value = max(value, 1e-12)
    elif axis_id != "body_temperature":
        value = max(value, 0.0)
    return value, max(sigma, 1e-6)


def eval_axis(axis_id, candidate, manifolds, background_axes):
    for disease in candidate:
        axis = manifolds[disease]["axes"].get(axis_id)
        if axis:
            return axis
    return background_axes.get(axis_id)


def treatment_mechanism_activity_for_axis(
    disease,
    source_axis_id,
    disease_days,
    elapsed_day,
    manifolds,
    background_axes,
    treatments_by_disease,
    treatment_scales,
    rng,
    seen=None,
    cache=None,
):
    """Return treated 0..1 mechanism activity, including upstream mechanism gates."""
    cache = cache if cache is not None else {}
    if source_axis_id in cache:
        return cache[source_axis_id]

    manifold = manifolds[disease]
    source_axis = manifold["axes"].get(source_axis_id)
    if source_axis is None:
        return 0.0

    value, _ = sample_axis_value(
        source_axis,
        disease_days[disease],
        elapsed_day,
        treatments_by_disease.get(disease, []),
        treatment_scales,
        rng,
    )
    activity = joint.axis_activity(source_axis, value, background_axes.get(source_axis_id))

    seen = set(seen or ())
    if source_axis_id in seen:
        cache[source_axis_id] = joint.clamp01(activity)
        return cache[source_axis_id]
    seen.add(source_axis_id)

    parent_signals = []
    for edge in joint.mechanism_edges_to(manifold, source_axis_id):
        parent_axis_id = edge.get("source_axis_id")
        parent_axis = manifold["axes"].get(parent_axis_id)
        if parent_axis is None or parent_axis.get("category") != joint.LATENT_MECHANISM_CATEGORY:
            continue
        parent_activity = treatment_mechanism_activity_for_axis(
            disease,
            parent_axis_id,
            disease_days,
            elapsed_day,
            manifolds,
            background_axes,
            treatments_by_disease,
            treatment_scales,
            rng,
            seen,
            cache,
        )
        if edge.get("effect_on_target") == "decrease":
            parent_activity = 1.0 - parent_activity
        parent_signals.append(joint.clamp01(parent_activity))

    if parent_signals:
        activity = min(activity, max(parent_signals))

    cache[source_axis_id] = joint.clamp01(activity)
    return cache[source_axis_id]


def treatment_mechanism_gate_for_target(
    disease,
    target_axis_id,
    disease_days,
    elapsed_day,
    manifolds,
    background_axes,
    treatments_by_disease,
    treatment_scales,
    rng,
):
    """Return dominant treated latent-mechanism activity for a downstream axis."""
    manifold = manifolds[disease]
    candidates = []
    cache = {}
    for edge in joint.mechanism_edges_to(manifold, target_axis_id):
        source_axis_id = edge.get("source_axis_id")
        source_axis = manifold["axes"].get(source_axis_id)
        if source_axis is None:
            continue
        activity = treatment_mechanism_activity_for_axis(
            disease,
            source_axis_id,
            disease_days,
            elapsed_day,
            manifolds,
            background_axes,
            treatments_by_disease,
            treatment_scales,
            rng,
            cache=cache,
        )
        candidates.append((activity, edge))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])


def target_for_axis(axis_id, candidate, disease_days, elapsed_day, manifolds, background_axes, treatments_by_disease, treatment_scales, rng):
    axis_eval = eval_axis(axis_id, candidate, manifolds, background_axes)
    if axis_eval is None:
        return None

    bg_axis = background_axes.get(axis_id) or axis_eval
    bg_mu, _ = joint.sample_mu_and_baseline(bg_axis, -1.0, rng)
    bg_mu = joint.convert_value(bg_mu, bg_axis.get("unit"), axis_eval.get("unit"), axis_id)
    z_bg = joint.transform(axis_eval, bg_mu)

    raw_deltas = []
    strengths = []
    sigmas = [joint.axis_sigma(bg_axis)]
    sources = []

    for disease in candidate:
        axis = manifolds[disease]["axes"].get(axis_id)
        if axis is None:
            continue
        value, sigma = sample_axis_value(
            axis,
            disease_days[disease],
            elapsed_day,
            treatments_by_disease.get(disease, []),
            treatment_scales,
            rng,
        )
        value = joint.convert_value(value, axis.get("unit"), axis_eval.get("unit"), axis_id)
        z_value = joint.transform(axis_eval, value)
        delta = z_value - z_bg
        gate = treatment_mechanism_gate_for_target(
            disease,
            axis_id,
            disease_days,
            elapsed_day,
            manifolds,
            background_axes,
            treatments_by_disease,
            treatment_scales,
            rng,
        )
        if gate is not None:
            activity, edge = gate
            delta = joint.edge_adjusted_delta(delta, edge) * activity
        raw_deltas.append(delta)
        strengths.append(abs(delta) / max(sigma, 1e-6))
        sigmas.append(sigma)
        sources.append(disease)

    if not raw_deltas:
        z = z_bg
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

    value = joint.inverse_transform(axis_eval, z)
    if not axis_eval.get("log_scale") and axis_id != "body_temperature":
        value = max(value, 0.0)
    return axis_eval, value, max(max(sigmas), 1e-6), source


def axis_reference_z(axis_id, axis, background_axes):
    bg_axis = background_axes.get(axis_id) or axis
    baseline = joint.parse_interval(bg_axis.get("baseline_range")) or joint.parse_interval(axis.get("baseline_range"))
    ref_value = midpoint(baseline, None)
    if ref_value is None:
        return None
    ref_value = joint.convert_value(ref_value, bg_axis.get("unit"), axis.get("unit"), axis_id)
    return joint.transform(axis, ref_value)


def coupling_source_signal(coupling, source_axis_id, source_axis, source_z, background_axes):
    """Return a saturated 0..1 activation weight for a drift coupling.

    Distilled effect_size_range is interpreted downstream as a maximum target
    sigma shift, not as an unbounded per-source-sigma multiplier.
    """
    direction = str(coupling.get("effect_direction") or "")
    if not direction:
        return 0.0

    threshold = midpoint(coupling.get("activation_threshold_range"), None)
    if threshold is None:
        ref_z = axis_reference_z(source_axis_id, source_axis, background_axes)
    else:
        ref_z = joint.transform(source_axis, threshold)
    if ref_z is None:
        return 0.0

    sigma = max(joint.axis_sigma(source_axis), 1e-6)
    if direction.startswith("source_up_"):
        raw = (source_z - ref_z) / sigma
    elif direction.startswith("source_down_"):
        raw = (ref_z - source_z) / sigma
    else:
        return 0.0
    raw = max(float(raw), 0.0)
    return raw / (1.0 + raw)


def coupling_target_sign(coupling):
    direction = str(coupling.get("effect_direction") or "")
    if direction.endswith("_increases_target"):
        return 1.0
    if direction.endswith("_decreases_target"):
        return -1.0
    return 0.0


def apply_drift_couplings_to_target(target, axis_ids, candidate, manifolds, background_axes):
    """Apply distilled causal/hazard couplings to treatment targets.

    Existing couplings without ``coupling_type`` remain covariance-only. New
    ``hazard_drift`` / ``event_transition`` couplings let treatment-moved axes
    push event hazards or mortality hazard in transformed state space.
    """
    idx = {axis_id: i for i, axis_id in enumerate(axis_ids)}
    adjusted = target.copy()

    for disease in candidate:
        for coupling in manifolds[disease]["axis_couplings"]:
            if not joint.is_drift_coupling(coupling):
                continue
            source_axis_id = coupling.get("source_axis_id")
            target_axis_id = coupling.get("target_axis_id")
            if source_axis_id not in idx or target_axis_id not in idx:
                continue

            source_axis = eval_axis(source_axis_id, candidate, manifolds, background_axes)
            target_axis = eval_axis(target_axis_id, candidate, manifolds, background_axes)
            if source_axis is None:
                continue
            if target_axis is None:
                continue

            effect_size = interval_mid(coupling.get("effect_size_range"), None)
            sign = coupling_target_sign(coupling)
            if effect_size is None or sign == 0.0:
                continue

            signal = coupling_source_signal(
                coupling,
                source_axis_id,
                source_axis,
                adjusted[idx[source_axis_id]],
                background_axes,
            )
            if signal == 0.0:
                continue

            target_sigma = max(joint.axis_sigma(target_axis), 1e-6)
            max_shift = min(abs(effect_size), 2.0) * target_sigma
            drift = sign * max_shift * signal
            adjusted[idx[target_axis_id]] += max(min(drift, 2.0 * target_sigma), -2.0 * target_sigma)

    return adjusted


def axes_for_policy(case, candidate, policy, manifolds, background_axes):
    axis_ids = set(case["observations_by_axis"])
    for disease in candidate:
        haz_id = disease_hazard_axis(manifolds[disease])
        if haz_id:
            axis_ids.add(haz_id)
    for _, treatment in policy:
        axis_ids.update(treatment_axis_ids(treatment))

    # Coupling closure lets treatment-altered axes carry joint noise and
    # hazard/event drift through short complication chains.
    for _ in range(8):
        before = len(axis_ids)
        changed = set(axis_ids)
        for disease in candidate:
            for edge in manifolds[disease].get("mechanism_edges", []):
                src = edge.get("source_axis_id")
                tgt = edge.get("target_axis_id")
                if src in changed:
                    axis_ids.add(tgt)
                if tgt in changed:
                    axis_ids.add(src)
            for c in manifolds[disease]["axis_couplings"]:
                src = c.get("source_axis_id")
                tgt = c.get("target_axis_id")
                if src in changed:
                    axis_ids.add(tgt)
                if tgt in changed and joint.is_noise_coupling(c):
                    axis_ids.add(src)
        if len(axis_ids) == before:
            break

    return sorted(a for a in axis_ids if eval_axis(a, candidate, manifolds, background_axes) is not None)


def canonical_axis_ids(case, candidate, manifolds, background_axes):
    """Return the union of axis_ids across every treatment of the candidate
    manifold(s). All policies for a given case run on this same set, so RMST
    gains are comparable instead of depending on which drugs the policy
    happens to expose to the simulator."""
    full_policy = tuple(
        (disease, treatment)
        for disease in candidate
        for treatment in (manifolds[disease].get("treatments") or [])
    )
    return axes_for_policy(case, candidate, full_policy, manifolds, background_axes)


def initial_state(case, axis_ids, candidate, start_days, manifolds, background_axes, treatments_by_disease, treatment_scales, rng):
    xs = []
    for axis_id in axis_ids:
        axis_eval = eval_axis(axis_id, candidate, manifolds, background_axes)
        obs = case["observations_by_axis"].get(axis_id)
        if obs is not None:
            value = joint.convert_value(obs["value"], obs.get("unit"), axis_eval.get("unit"), axis_id)
        else:
            endpoint = target_for_axis(axis_id, candidate, start_days, 0.0, manifolds, background_axes, treatments_by_disease, treatment_scales, rng)
            value = endpoint[1]
        xs.append(joint.transform(axis_eval, value))
    return np.asarray(xs, dtype=float)


def simulate_policy(case, candidate, policy, manifolds, background_axes, start_days, axis_ids=None):
    # Use the case-level seed (not policy-dependent) so policies share the same MC
    # noise stream and gains are paired comparisons instead of independent samples.
    rng = np.random.default_rng(joint.deterministic_seed((case["case_id"], "treatment")))
    background_axes = joint.background_axes_for_case(background_axes, case, candidate)
    treatments_by_disease = policy_by_disease(policy)
    treatment_scales = {
        id(treatment): treatment_effect_scale(treatment, case, candidate, manifolds, background_axes)
        for _, treatment in policy
    }
    if axis_ids is None:
        axis_ids = axes_for_policy(case, candidate, policy, manifolds, background_axes)
    if not axis_ids:
        return None

    risk_payloads = {}
    for disease in candidate:
        axis_mods, coupling_mods, log_prior = joint.matched_risk_payload(
            manifolds[disease],
            joint.case_risk_context(case, disease),
        )
        risk_payloads[disease] = {
            "axis_mods": axis_mods,
            "coupling_mods": coupling_mods,
            "log_prior": log_prior,
        }

    corr = joint.build_corr(axis_ids, candidate, manifolds, risk_payloads)
    haz_ids = [disease_hazard_axis(manifolds[d]) for d in candidate]
    haz_ids = [h for h in haz_ids if h in axis_ids]
    haz_idx = [axis_ids.index(h) for h in haz_ids]

    x0 = initial_state(case, axis_ids, candidate, start_days, manifolds, background_axes, treatments_by_disease, treatment_scales, rng)
    x = np.tile(x0, (N_PARTICLES, 1))
    cumulative_hazard = np.zeros(N_PARTICLES)
    rmst = np.zeros(N_PARTICLES)
    day_means = {}

    for step in range(1, int(HORIZON_DAYS / DT) + 1):
        elapsed = step * DT
        disease_days = {
            disease: min(start_days.get(disease, 0.0) + elapsed, joint.T_MAX_BY_DISEASE.get(disease, 90.0))
            for disease in candidate
        }

        target = []
        sigmas = []
        for axis_id in axis_ids:
            endpoint = target_for_axis(axis_id, candidate, disease_days, elapsed, manifolds, background_axes, treatments_by_disease, treatment_scales, rng)
            axis_eval, value, sigma, _ = endpoint
            target.append(joint.transform(axis_eval, value))
            sigmas.append(sigma)
        target = np.asarray(target)
        target = apply_drift_couplings_to_target(target, axis_ids, candidate, manifolds, background_axes)
        sigmas = np.asarray(sigmas)

        cov = joint.nearest_corr_psd(corr) * np.outer(sigmas, sigmas)
        chol = np.linalg.cholesky(cov + np.eye(len(axis_ids)) * 1e-6)
        noise = rng.normal(size=(N_PARTICLES, len(axis_ids))) @ chol.T
        x = x + KAPPA * (target - x) * DT + NOISE_SCALE * math.sqrt(DT) * noise

        hazard = np.zeros(N_PARTICLES)
        for idx in haz_idx:
            axis = eval_axis(axis_ids[idx], candidate, manifolds, background_axes)
            raw = np.array([joint.inverse_transform(axis, z) for z in x[:, idx]])
            hazard += np.clip(raw, 0.0, 5.0)
        cumulative_hazard += hazard * DT
        rmst += np.exp(-cumulative_hazard) * DT

        if step in (SUMMARY_DAY, HORIZON_DAYS):
            means = {}
            for j, axis_id in enumerate(axis_ids):
                axis = eval_axis(axis_id, candidate, manifolds, background_axes)
                vals = np.array([joint.inverse_transform(axis, z) for z in x[:, j]])
                means[axis_id] = float(np.mean(vals))
            day_means[step] = means

    return {
        "policy": policy,
        "name": policy_name(policy),
        "candidate": "+".join(candidate),
        "rmst_mean": float(np.mean(rmst)),
        "rmst_p25": float(np.percentile(rmst, 25)),
        "rmst_p75": float(np.percentile(rmst, 75)),
        "axis_ids": axis_ids,
        "day_means": day_means,
    }


def expected_tuple(case):
    return joint.expected_tuple(case)


def start_days_for_case(case, candidate, manifolds, background_axes):
    explicit = case.get("treatment_start_days") or {}
    if explicit:
        return {
            disease: min(float(explicit.get(disease, 0.0)), joint.T_MAX_BY_DISEASE.get(disease, 90.0))
            for disease in candidate
        }

    snapshot_day = case.get("snapshot_day")
    if isinstance(snapshot_day, (int, float)):
        return {
            disease: min(float(snapshot_day), joint.T_MAX_BY_DISEASE.get(disease, 90.0))
            for disease in candidate
        }

    score = joint.score_candidate(case, candidate, manifolds, background_axes)
    if not score or not score.get("best"):
        return {disease: 0.0 for disease in candidate}
    return score["best"]["t_by_disease"]


def axis_delta_summary(best, baseline):
    day = SUMMARY_DAY if SUMMARY_DAY in best["day_means"] else max(best["day_means"])
    best_means = best["day_means"].get(day, {})
    base_means = baseline["day_means"].get(day, {})
    deltas = []
    changed = set()
    for _, treatment in best["policy"]:
        changed.update(treatment_axis_ids(treatment))
    hazard_axes = {
        axis_id
        for axis_id in set(best_means) | set(base_means)
        if axis_id.startswith("mortality_hazard")
    }
    for axis_id in changed | set(KEY_AXIS_PRIORITY) | hazard_axes:
        if axis_id not in best_means or axis_id not in base_means:
            continue
        b = best_means[axis_id]
        u = base_means[axis_id]
        if not (math.isfinite(b) and math.isfinite(u)):
            continue
        delta = b - u
        if axis_id.startswith("mortality_hazard"):
            priority = -100
        else:
            try:
                priority = KEY_AXIS_PRIORITY.index(axis_id)
            except ValueError:
                priority = 99
        deltas.append((priority, abs(delta), axis_id, b, u, delta))
    deltas.sort(key=lambda x: (x[0], -x[1]))
    return day, deltas[:6]


def main():
    manifolds = {label: joint.load_manifold(path) for label, path in joint.MANIFOLD_PATHS.items()}
    background_axes = joint.build_background_axes(manifolds, joint.load_master_axes())
    cases = [joint.load_case(path) for path in sorted(CASE_DIR.glob("v5_case_*.json"))]
    if CASE_FILTER:
        cases = [
            case for case in cases
            if any(token in case.get("case_id", "") or token in str(case.get("source_pmcid", "")) for token in CASE_FILTER)
        ]

    lines = []
    lines.append("=" * 108)
    lines.append("V5 joint SDE treatment vector-field simulation")
    lines.append("=" * 108)
    lines.append(f"N_PARTICLES={N_PARTICLES}, horizon={HORIZON_DAYS}d, dt={DT}, kappa={KAPPA}, noise_scale={NOISE_SCALE}")
    lines.append("Treatment policies, including same-disease bundles and timed stages, are ranked by RMST over the horizon. Candidate disease/combo is taken from each case's expected manifold(s).")
    lines.append(f"Manifold discovery: {len(manifolds)} root distillation files from {DISTILL_DIR / 'v5_*.json'}")
    if CASE_FILTER:
        lines.append(f"Case filter: {', '.join(CASE_FILTER)}")
    lines.append(f"Cases loaded for this run: {len(cases)}")
    lines.append("")

    for case in cases:
        candidate = expected_tuple(case)
        if not candidate or not set(candidate).issubset(set(manifolds)):
            continue

        start_days = start_days_for_case(case, candidate, manifolds, background_axes)
        policies = make_policies(candidate, manifolds, case)
        case_axes = canonical_axis_ids(case, candidate, manifolds, background_axes)
        results = []
        for policy in policies:
            result = simulate_policy(case, candidate, policy, manifolds, background_axes, start_days, axis_ids=case_axes)
            if result:
                results.append(result)
        results.sort(key=lambda r: -r["rmst_mean"])

        baseline = next(r for r in results if not r["policy"])
        best = results[0]
        gain = best["rmst_mean"] - baseline["rmst_mean"]

        lines.append("-" * 108)
        lines.append(f"{case['case_id']}  candidate={'+'.join(candidate)}")
        lines.append(f"source: PMID {case.get('source_pmid')} / {case.get('source_pmcid')} / {case.get('source_url')}")
        lines.append("start latent days: " + ", ".join(f"{d}=day{v:.1f}" for d, v in start_days.items()))
        lines.append("")
        lines.append("Top treatment vector fields by RMST:")
        for i, r in enumerate(results[:TOP_ROWS], 1):
            gain_i = r["rmst_mean"] - baseline["rmst_mean"]
            lines.append(
                f"  {i:2d}. RMST={r['rmst_mean']:6.2f}d "
                f"[p25={r['rmst_p25']:5.2f}, p75={r['rmst_p75']:5.2f}] "
                f"gain={gain_i:+6.2f}d  {r['name']}"
            )

        lines.append(f"Best vs no treatment: {best['name']}  gain={gain:+.2f}d over {HORIZON_DAYS}d")
        day, deltas = axis_delta_summary(best, baseline)
        if deltas:
            lines.append(f"Axis movement at day {day} vs no treatment:")
            for _, _, axis_id, treated, untreated, delta in deltas:
                lines.append(f"  {axis_id:45s} treated={treated:10.4g}  untreated={untreated:10.4g}  delta={delta:+10.4g}")
        lines.append("")

    lines.append("=" * 108)
    lines.append("Notes:")
    lines.append("  - reshape_landscape changes disease trajectory targets including mortality_hazard when distilled.")
    lines.append("  - latent_mechanisms / mechanism_edges let treatments change hidden disease engines and propagate to downstream axes.")
    lines.append("  - push_state adds an explicit treatment force to axes such as MAP, oxygen saturation, hemoglobin, fever, or potassium.")
    lines.append("  - sigma_modulation changes diffusion amplitude for specified axes.")
    lines.append("  - required_context_axes/effect_modifiers can scale treatment force by susceptibility, active coverage, source control, contraindications, or toxicity context when distilled.")
    lines.append("  - same-disease bundle generation combines complementary treatment lanes and avoids duplicate alternatives such as two antibiotics or TPE plus plasma-infusion bridge.")
    lines.append("  - timed-stage policies can start slower add-ons later, shown as labels such as rituximab@day1 or anakinra@day2.")
    lines.append("  - hazard_drift/event_transition couplings can let treatment-moved axes push event hazards or mortality_hazard; old couplings without coupling_type remain covariance-only.")
    lines.append("  - This is treatment runtime v0.1; it has timed stages but does not yet branch on simulated follow-up response.")

    text = "\n".join(lines)
    RESULT_PATH.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[done] wrote {RESULT_PATH}")


if __name__ == "__main__":
    main()
