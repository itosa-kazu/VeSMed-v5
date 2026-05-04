"""
Current-schema V5 case ranking test.

Inputs:
  - distillations/v5_D137.json
  - distillations/v5_D-SEPSIS-GN.json
  - distillations/cases/v5_case_*.json

This is intentionally a lightweight PoC:
  - marginalizes a single presentation snapshot over disease day t
  - compares D137 vs D-SEPSIS-GN on every observed axis
  - if a disease did not distill an observed axis, scores that axis against a
    synthesized healthy background instead of skipping it
"""
import json
import math
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
RESULT_PATH = DISTILL_DIR / "case_test_result.txt"

MANIFOLDS = {
    "D137": DISTILL_DIR / "v5_D137.json",
    "D-SEPSIS-GN": DISTILL_DIR / "v5_D-SEPSIS-GN.json",
}

BACKGROUND_MODIFIERS = v5_background.load_background_modifiers()
CONDITION_SCOPE = v5_background.load_condition_scope()

T_MAX_BY_DISEASE = {
    "D137": 90.0,
    "D-SEPSIS-GN": 30.0,
}

N_MC = 5000
SEED = 42


HEALTHY_OVERRIDES = {
    # Vitals
    "body_temperature": {"unit": "°C", "baseline_range": (36.5, 37.5), "log_scale": False},
    "heart_rate": {"unit": "beats_per_min", "baseline_range": (60.0, 90.0), "log_scale": False},
    "respiratory_rate": {"unit": "breaths_per_min", "baseline_range": (12.0, 20.0), "log_scale": False},
    "systolic_blood_pressure": {"unit": "mmHg", "baseline_range": (100.0, 140.0), "log_scale": False},
    "mean_arterial_pressure": {"unit": "mmHg", "baseline_range": (70.0, 100.0), "log_scale": False},
    "oxygen_saturation": {"unit": "%", "baseline_range": (95.0, 100.0), "log_scale": False},
    "urine_output": {"unit": "mL/kg/hr", "baseline_range": (0.5, 1.5), "log_scale": False},
    # Common labs where current sepsis baseline_range represents disease presentation,
    # not healthy. These overrides keep missing-axis fallback from inheriting disease values.
    "serum_procalcitonin": {"unit": "ng/mL", "baseline_range": (0.02, 0.1), "log_scale": True},
    "blood_culture_positivity_probability": {"unit": "probability_0_1", "baseline_range": (0.0, 0.02), "log_scale": False},
    "blood_culture_bacterial_load": {"unit": "CFU_per_mL", "baseline_range": (1e-9, 1e-6), "log_scale": True},
    "blood_urea_nitrogen": {"unit": "mg/dL", "baseline_range": (7.0, 20.0), "log_scale": False},
    "serum_creatinine": {"unit": "mg/dL", "baseline_range": (0.6, 1.2), "log_scale": False},
    "serum_lactate": {"unit": "mmol/L", "baseline_range": (0.5, 2.0), "log_scale": False},
}


def parse_interval(value):
    if value is None:
        return None
    if isinstance(value, list) and len(value) >= 2:
        lo = float(value[0])
        hi = float(value[1])
        if not (math.isfinite(lo) and math.isfinite(hi)):
            return None
        return (min(lo, hi), max(lo, hi))
    return None


def load_manifold(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    axes = {}
    for raw in data.get("axes", []):
        axis_id = raw.get("axis_id")
        if not axis_id or raw.get("category") == "derived_hazard":
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
        axes[axis_id] = axis
    return {
        "disease": data.get("disease", path.stem),
        "axes": axes,
    }


def load_master_axes(path=ROOT / "master_axes.json"):
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {a["axis_id"]: a for a in data.get("axes", []) if a.get("axis_id")}


def build_background_axes(manifolds, master_axes):
    """Build base-measure fallback axes.

    If a disease does not model an observed axis, it should not get a free pass.
    The fallback axis represents "nothing special is happening on this axis".
    It starts from master_axes metadata and disease baseline ranges, with small
    overrides for axes whose current distillation baseline is not truly healthy.
    """
    by_axis = {}
    for manifold in manifolds.values():
        for axis_id, axis in manifold["axes"].items():
            if axis.get("baseline_range") is None:
                continue
            entry = by_axis.setdefault(axis_id, {
                "axis_id": axis_id,
                "category": axis.get("category"),
                "unit": axis.get("unit"),
                "log_scale": bool(axis.get("log_scale", False)),
                "ranges": [],
            })
            if entry.get("unit") is None:
                entry["unit"] = axis.get("unit")
            entry["log_scale"] = bool(entry["log_scale"] or axis.get("log_scale", False))
            lo, hi = axis["baseline_range"]
            unit = entry.get("unit") or axis.get("unit")
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
            "ranges": [],
        })

    background = {}
    for axis_id, entry in by_axis.items():
        override = HEALTHY_OVERRIDES.get(axis_id) or v5_background.BASE_MEASURE_OVERRIDES.get(axis_id)
        if override:
            baseline = override["baseline_range"]
            unit = override["unit"]
            log_scale = override["log_scale"]
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
            "baseline_range": baseline,
            "peak_day_range": None,
            "peak_value_range": None,
            "plateau_duration_days": None,
            "decline_half_life_days": None,
            "_source": "base_measure_background",
        }
    return background


def background_axes_for_case(background_axes, case, candidate):
    return v5_background.adjust_background_axes(
        background_axes,
        case,
        (candidate,),
        BACKGROUND_MODIFIERS,
        CONDITION_SCOPE,
        convert_value,
    )


def load_case(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    observations = {}
    for obs in data.get("observations", []):
        axis_id = obs.get("axis_id")
        if not axis_id:
            continue
        value = obs.get("value")
        if value is None:
            continue
        observations[axis_id] = {
            "value": float(value),
            "unit": obs.get("unit"),
        }
    for traj in data.get("lab_trajectories", []):
        axis_id = traj.get("axis_id")
        obs_list = traj.get("observations") or []
        numeric = [o for o in obs_list if o.get("value") is not None]
        if not axis_id or not numeric or axis_id in observations:
            continue
        first = sorted(numeric, key=lambda o: float(o.get("day", 0)))[0]
        observations[axis_id] = {
            "value": float(first["value"]),
            "unit": traj.get("unit"),
        }
    data["observations_by_axis"] = observations
    return data


def norm_unit(unit):
    if unit is None:
        return ""
    return (
        str(unit)
        .replace("µ", "u")
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

    # Concentration conventions used in current case/distillation files.
    if src in ("mg/dl", "mgperdl") and dst in ("mg/l", "mgperl"):
        return value * 10.0
    if src in ("mg/l", "mgperl") and dst in ("mg/dl", "mgperdl"):
        return value / 10.0
    if src in ("g/l", "gperl") and dst in ("g/dl", "gperdl"):
        return value / 10.0
    if src in ("g/dl", "gperdl") and dst in ("g/l", "gperl"):
        return value * 10.0

    # Creatinine: umol/L to mg/dL. Keep axis guard to avoid applying to other analytes.
    if axis_id == "serum_creatinine" and src in ("umol/l", "umolperl", "umol/l") and dst in ("mg/dl", "mgperdl"):
        return value / 88.4
    if axis_id == "serum_creatinine" and src in ("mg/dl", "mgperdl") and dst in ("umol/l", "umolperl", "umol/l"):
        return value * 88.4

    # Platelets/WBC: k/uL, 10^3/uL, and 10^9/L are numerically equivalent.
    if src in ("k/ul", "103/ul", "109/l") and dst in ("109/l", "k/ul", "103/ul"):
        return value

    # ESR spelling variants.
    if src in ("mm/hr", "mmperhr", "mm/hour", "mmperhour") and dst in ("mmperhr", "mm/hr", "mm/hour", "mmperhour"):
        return value

    return value


def sample_uniform(rng, interval):
    lo, hi = interval
    if lo == hi:
        return lo
    return float(rng.uniform(lo, hi))


def sample_mu_at_day(axis, t, rng):
    baseline = sample_uniform(rng, axis["baseline_range"])
    peak_day_range = axis.get("peak_day_range")
    peak_value_range = axis.get("peak_value_range")
    if t < 0 or peak_day_range is None or peak_value_range is None:
        return baseline

    peak_day = max(sample_uniform(rng, peak_day_range), 1e-6)
    peak_value = sample_uniform(rng, peak_value_range)
    plateau = 0.0 if axis.get("plateau_duration_days") is None else sample_uniform(rng, axis["plateau_duration_days"])
    plateau_end = peak_day + max(plateau, 0.0)

    if t <= 0:
        return baseline
    if t < peak_day:
        return baseline + (peak_value - baseline) * (t / peak_day)
    if t < plateau_end:
        return peak_value

    hl_range = axis.get("decline_half_life_days")
    if hl_range is None:
        return peak_value
    hl = max(sample_uniform(rng, hl_range), 1e-6)
    decay = 0.5 ** ((t - plateau_end) / hl)
    return baseline + (peak_value - baseline) * decay


def axis_sigma(axis):
    ranges = [axis.get("baseline_range"), axis.get("peak_value_range")]
    ranges = [r for r in ranges if r is not None]
    values = []
    for lo, hi in ranges:
        values.extend([lo, hi])
    if not values:
        return 1.0

    if axis.get("log_scale"):
        logs = [math.log10(max(v, 1e-12)) for v in values if v > 0]
        if not logs:
            return 0.5
        spread = max(logs) - min(logs)
        return max(spread / 6.0, 0.15)

    spread = max(values) - min(values)
    typical = max(abs(float(np.median(values))), 1.0)
    return max(spread / 6.0, 0.08 * typical, 1e-6)


def logpdf_value(axis, observed_value, mu):
    sigma = axis_sigma(axis)
    if axis.get("log_scale"):
        x = math.log10(max(observed_value, 1e-12))
        m = math.log10(max(mu, 1e-12))
    else:
        x = observed_value
        m = mu
    z = (x - m) / sigma
    return float(-0.5 * z * z - math.log(sigma) - 0.5 * math.log(2.0 * math.pi))


def score_case_on_axes(case, manifold, axis_ids, background_axes=None, n_mc=N_MC, seed=SEED):
    rng = np.random.default_rng(seed)
    obs = case["observations_by_axis"]
    background_axes = background_axes or {}
    if background_axes:
        background_axes = background_axes_for_case(background_axes, case, manifold["disease"])
    usable_axis_ids = [a for a in axis_ids if a in obs and (a in manifold["axes"] or a in background_axes)]
    if not usable_axis_ids:
        return {
            "log_marginal": float("nan"),
            "mean_log_per_axis": float("nan"),
            "n_axes": 0,
            "best_t": float("nan"),
            "axis_ids": [],
            "best_contribs": [],
            "fallback_axes": [],
        }

    t_max = T_MAX_BY_DISEASE.get(manifold["disease"], 90.0)
    log_joint = np.zeros(n_mc)
    t_samples = np.zeros(n_mc)
    contribs = np.zeros((n_mc, len(usable_axis_ids)))

    for i in range(n_mc):
        t = float(rng.uniform(0.0, t_max))
        t_samples[i] = t
        total = 0.0
        for j, axis_id in enumerate(usable_axis_ids):
            axis = manifold["axes"].get(axis_id) or background_axes[axis_id]
            obs_record = obs[axis_id]
            observed_value = convert_value(
                obs_record["value"],
                obs_record.get("unit"),
                axis.get("unit"),
                axis_id,
            )
            mu = sample_mu_at_day(axis, t, rng)
            lp = logpdf_value(axis, observed_value, mu)
            contribs[i, j] = lp
            total += lp
        log_joint[i] = total

    log_marginal = float(logsumexp(log_joint) - math.log(n_mc))
    best_i = int(np.argmax(log_joint))
    return {
        "log_marginal": log_marginal,
        "mean_log_per_axis": log_marginal / len(usable_axis_ids),
        "n_axes": len(usable_axis_ids),
        "best_t": float(t_samples[best_i]),
        "axis_ids": usable_axis_ids,
        "fallback_axes": [a for a in usable_axis_ids if a not in manifold["axes"]],
        "best_contribs": [
            (
                axis_id,
                convert_value(
                    case["observations_by_axis"][axis_id]["value"],
                    case["observations_by_axis"][axis_id].get("unit"),
                    (manifold["axes"].get(axis_id) or background_axes[axis_id]).get("unit"),
                    axis_id,
                ),
                (manifold["axes"].get(axis_id) or background_axes[axis_id]).get("unit"),
                "fallback" if axis_id not in manifold["axes"] else "disease",
                float(contribs[best_i, j]),
            )
            for j, axis_id in enumerate(usable_axis_ids)
        ],
    }


def main():
    manifolds = {label: load_manifold(path) for label, path in MANIFOLDS.items()}
    master_axes = load_master_axes()
    background_axes = build_background_axes(manifolds, master_axes)
    all_common_axes = set.intersection(*(set(m["axes"]) for m in manifolds.values()))

    case_paths = sorted(CASE_DIR.glob("v5_case_*.json"))
    cases = [load_case(path) for path in case_paths]

    lines = []
    lines.append("=" * 92)
    lines.append("V5 current-schema PMC case ranking test")
    lines.append("=" * 92)
    lines.append(f"N_MC={N_MC}, seed={SEED}")
    lines.append("")
    lines.append("Manifolds:")
    for label, manifold in manifolds.items():
        lines.append(f"  {label:12s}: {len(manifold['axes'])} non-hazard axes")
    lines.append(f"Common non-hazard axes across compared manifolds: {len(all_common_axes)}")
    lines.append(f"Base-measure axes for missing-axis scoring: {len(background_axes)}")
    lines.append("")

    total = 0
    passed = 0
    for case in cases:
        expected = case.get("expected_manifold")
        if expected not in manifolds:
            continue

        obs_axes = set(case["observations_by_axis"])
        common_axes = sorted(obs_axes & all_common_axes)
        all_observed_axes = sorted(obs_axes)
        lines.append("-" * 92)
        lines.append(f"{case['case_id']}  expected={expected}")
        lines.append(f"source: PMID {case.get('source_pmid')} / {case.get('source_pmcid')} / {case.get('source_url')}")
        lines.append(f"paper diagnosis: {case.get('disease_label_per_paper')}")
        lines.append(f"observed axes: {len(obs_axes)}; common-test axes: {len(common_axes)}")
        if common_axes:
            lines.append("common axes: " + ", ".join(common_axes))
        lines.append("")

        full_scores = {}
        for label, manifold in manifolds.items():
            full_scores[label] = score_case_on_axes(case, manifold, all_observed_axes, background_axes, seed=SEED)

        if not all_observed_axes:
            lines.append("[A] full observed-axis ranking skipped: no numeric observations")
            lines.append("")
            continue

        best = max(full_scores.items(), key=lambda kv: kv[1]["mean_log_per_axis"])[0]
        ok = best == expected
        total += 1
        passed += int(ok)
        lines.append("[A] full observed-axis ranking with risk-factor-adjusted base-measure fallback")
        for label, score in sorted(full_scores.items()):
            lines.append(
                f"  {label:12s} mean={score['mean_log_per_axis']:+8.3f} "
                f"logP={score['log_marginal']:+9.3f} n={score['n_axes']:2d} best_t={score['best_t']:5.1f}"
            )
            if score["fallback_axes"]:
                lines.append(f"    fallback axes: {', '.join(score['fallback_axes'])}")
        lines.append(f"  -> best={best}  {'PASS' if ok else 'FAIL'}")
        lines.append("")

        common_scores = {}
        for label, manifold in manifolds.items():
            common_scores[label] = score_case_on_axes(case, manifold, common_axes, seed=SEED)

        lines.append("[B] old common-axis ranking (diagnostic only; missing axes skipped)")
        if not common_axes:
            lines.append("  skipped: no common numeric observations")
        else:
            common_best = max(common_scores.items(), key=lambda kv: kv[1]["mean_log_per_axis"])[0]
            for label, score in sorted(common_scores.items()):
                lines.append(
                    f"  {label:12s} mean={score['mean_log_per_axis']:+8.3f} "
                    f"logP={score['log_marginal']:+9.3f} n={score['n_axes']:2d} best_t={score['best_t']:5.1f}"
                )
            lines.append(f"  -> best={common_best}")
        lines.append("")

        lines.append("[C] disease-only available-axis support (coverage diagnostic; no fallback)")
        for label, manifold in sorted(manifolds.items()):
            available_axes = sorted(obs_axes & set(manifold["axes"]))
            score = score_case_on_axes(case, manifold, available_axes, seed=SEED)
            missing = sorted(obs_axes - set(manifold["axes"]))
            lines.append(
                f"  {label:12s} mean={score['mean_log_per_axis']:+8.3f} "
                f"logP={score['log_marginal']:+9.3f} n={score['n_axes']:2d} best_t={score['best_t']:5.1f}"
            )
            if missing:
                lines.append(f"    missing observed axes in {label}: {', '.join(missing)}")
            worst = sorted(score["best_contribs"], key=lambda x: x[4])[:4]
            if worst:
                lines.append("    worst fitted axes: " + "; ".join(
                    f"{axis_id}={value:g} {unit} {source} lp={lp:+.2f}" for axis_id, value, unit, source, lp in worst
                ))
        lines.append("")

    lines.append("=" * 92)
    lines.append(f"Validation: {passed}/{total} PASS on full observed-axis ranking with risk-factor-adjusted base-measure fallback")
    lines.append("")
    lines.append("Notes:")
    lines.append("  - This is a current-schema smoke test, not v4 joint SDE.")
    lines.append("  - Missing disease axes are scored against synthesized base measure, adjusted by case risk_context when applicable.")
    lines.append("  - The old common-axis section is retained only to show what changed.")
    lines.append("  - Disease-only available-axis support exposes ontology coverage gaps.")
    lines.append("  - No treatment effect is applied in this diagnostic ranking test.")

    text = "\n".join(lines)
    RESULT_PATH.write_text(text, encoding="utf-8")
    print(text)
    print(f"\n[done] wrote {RESULT_PATH}")


if __name__ == "__main__":
    main()
