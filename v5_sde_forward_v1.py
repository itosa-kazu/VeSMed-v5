"""
v5 SDE forward simulate v1 — marginalize over t (no external day猜测)

vs v0 改动:
  - 废: case 外部指定 day (CASE_DAY = {AOSD: 11, MAS: 10, healthy: 14})
  - 用: 每次 MC 采样 t ~ Uniform(0, 90), trajectory 自己挑最 fit 的 day
  - log P(case | AOSD) = log [(1/T) ∫₀^T ρ(case | t) dt]
                      = logsumexp_k [ joint_log_p_at_t_k ] - log(N_MC)

为什么这么改:
  1. healthy case 不用瞎填 day
  2. AOSD case 不用从 paper 里挖 day=11
  3. MAS case 不用猜 day
  4. 合并症时每个病独立 marginalize 自己的 t (互不干扰)
"""
import json
import re
import numpy as np
from scipy import stats
from scipy.special import logsumexp
from pathlib import Path

ROOT = Path(r"C:\Users\wangw\Desktop\vesmed_v5_poc")
LLM_YAML_PATH = ROOT / "v5_AOSD.txt"
CASE_PATHS = {
    "case1_AOSD":    ROOT / "v5_aosd_case_data.json",
    "case2_healthy": ROOT / "v5_healthy_case_data.json",
    "case3_MAS":     ROOT / "v5_mas_case_data.json",
}
RESULT_PATH = ROOT / "v5_sde_forward_v1_result.txt"

N_MC = 10000
SEED = 42
T_MAX = 90  # AOSD 病程窗口 0-90 天

# Axis mapping: same as v0
AXIS_MAPPING = {
    "body_temperature_daily_maximum":    ("peak_body_temperature",          False, 1.0,  False),
    "serum_ferritin":                    ("log10_serum_ferritin",           True,  1.0,  True),
    "glycosylated_ferritin_fraction":    ("glycosylated_ferritin_fraction", False, 1.0,  False),
    "c_reactive_protein":                ("CRP",                            True,  1.0,  False),
    "absolute_neutrophil_count":         ("absolute_neutrophil_count",      False, 1.0,  False),
    "platelet_count":                    ("platelet_count",                 False, 1.0,  False),
    "aspartate_aminotransferase":        ("log10_AST",                      True,  1.0,  True),
    "fibrinogen":                        ("fibrinogen",                     False, 0.01, False),
    "interleukin_18":                    ("log10_serum_IL18",               True,  1.0,  True),
}
CASE_TO_LLM = {v[0]: k for k, v in AXIS_MAPPING.items()}


def parse_interval(s):
    s = s.strip()
    if s.lower() == "null" or s == "":
        return None
    m = re.match(r'\[\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\]', s)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    return None


def parse_yaml_axes(path):
    text = path.read_text(encoding="utf-8")
    blocks = re.split(r'(?m)^- axis_name:', text)[1:]
    axes = []
    for blk in blocks:
        blk = "- axis_name:" + blk
        ax = {}
        for line in blk.splitlines():
            m = re.match(r'\s*(?:- )?([a-z_]+):\s*(.*)$', line)
            if not m:
                continue
            ax[m.group(1)] = m.group(2).strip()
        out = {
            "name": ax.get("axis_name", "").strip().strip('"'),
            "unit": ax.get("unit", "").strip().strip('"'),
            "log_scale": ax.get("log_scale", "false").lower() == "true",
            "knowledge_confidence": ax.get("knowledge_confidence", "").strip(),
        }
        for f in ["baseline_range", "peak_day_range", "peak_value_range",
                  "plateau_duration_days", "decline_half_life_days"]:
            out[f] = parse_interval(ax.get(f, "null"))
        axes.append(out)
    return axes


def sample_mu_at_day(axis, t, rng):
    """day t 的 axis μ (LLM 区间内 uniform 采样参数后给出)。t < 0 触发 baseline mode。"""
    baseline = rng.uniform(*axis["baseline_range"])
    if t < 0 or axis["peak_day_range"] is None:
        return baseline

    peak_day = rng.uniform(*axis["peak_day_range"])
    peak_value = rng.uniform(*axis["peak_value_range"])
    plateau_dur = 0.0 if axis["plateau_duration_days"] is None else rng.uniform(*axis["plateau_duration_days"])
    plateau_end = peak_day + plateau_dur

    if t <= 0:
        return baseline
    elif t < peak_day:
        return baseline + (peak_value - baseline) * t / peak_day
    elif t < plateau_end:
        return peak_value
    else:
        if axis["decline_half_life_days"] is None:
            return peak_value
        hl = rng.uniform(*axis["decline_half_life_days"])
        decay = 0.5 ** ((t - plateau_end) / max(hl, 1e-6))
        return baseline + (peak_value - baseline) * decay


def axis_sigma(axis, log_scale):
    lo, hi = axis["baseline_range"]
    if log_scale:
        lo = max(lo, 1e-3)
        sigma = (np.log10(hi) - np.log10(lo)) / 4
        sigma = max(sigma, 0.1)
    else:
        sigma = (hi - lo) / 4
        avg = (lo + hi) / 2
        sigma = max(sigma, 0.05 * abs(avg) if avg != 0 else 0.05)
    return sigma


def case_log_marginal(axes_by_name, case, n_mc, seed, mode, t_max=T_MAX):
    """
    Marginal log likelihood = log [(1/T) ∫ ρ(case | t) dt]
    每次 MC: 采样 t ~ U(0, t_max) (或 t=-1 if healthy mode), 然后对每 axis 采样 LLM 参数, 算 joint log p.
    最后 logsumexp over MC - log(N) = marginal.
    """
    rng = np.random.default_rng(seed)

    observed = []
    for case_key, val_dict in case["axes_values"].items():
        if val_dict["missing"]:
            continue
        if case_key not in CASE_TO_LLM:
            continue
        llm_name = CASE_TO_LLM[case_key]
        if llm_name not in axes_by_name:
            continue
        axis = axes_by_name[llm_name]
        log_scale = AXIS_MAPPING[llm_name][1]
        unit_factor = AXIS_MAPPING[llm_name][2]
        case_is_log10 = AXIS_MAPPING[llm_name][3]
        observed.append({
            "case_key": case_key, "llm_name": llm_name, "axis": axis,
            "log_scale": log_scale, "unit_factor": unit_factor,
            "case_is_log10": case_is_log10,
            "x_case": val_dict["value"],
            "sigma": axis_sigma(axis, log_scale),
        })

    log_joint_per_mc = np.zeros(n_mc)
    per_axis_lps = np.zeros((n_mc, len(observed)))
    t_samples = np.zeros(n_mc)

    for k in range(n_mc):
        t = -1.0 if mode == "healthy" else rng.uniform(0, t_max)
        t_samples[k] = t

        joint = 0.0
        for j, ax in enumerate(observed):
            mu_llm = sample_mu_at_day(ax["axis"], t, rng)
            mu_case = mu_llm * ax["unit_factor"]

            if ax["log_scale"]:
                mu_for_lh = np.log10(max(mu_case, 1e-10))
                x_for_lh = ax["x_case"] if ax["case_is_log10"] else np.log10(max(ax["x_case"], 1e-10))
            else:
                mu_for_lh = mu_case
                x_for_lh = ax["x_case"]

            lp = stats.norm.logpdf(x_for_lh, mu_for_lh, ax["sigma"])
            joint += lp
            per_axis_lps[k, j] = lp

        log_joint_per_mc[k] = joint

    log_marginal = logsumexp(log_joint_per_mc) - np.log(n_mc)

    # diagnostic: implied "best day" (the t that maximized joint log p)
    best_k = np.argmax(log_joint_per_mc)
    best_t = t_samples[best_k]
    best_joint = log_joint_per_mc[best_k]

    # diagnostic: posterior over day, rough hist
    weights = np.exp(log_joint_per_mc - log_joint_per_mc.max())
    weights = weights / weights.sum()
    weighted_t_mean = np.sum(weights * t_samples)
    weighted_t_std = np.sqrt(np.sum(weights * (t_samples - weighted_t_mean) ** 2))

    # per-axis: 在 best_t 那次 MC 的 log p (诊断用)
    contributions = [
        (ax["case_key"], ax["llm_name"], ax["x_case"], per_axis_lps[best_k, j])
        for j, ax in enumerate(observed)
    ]

    return {
        "log_marginal": log_marginal,
        "best_t": best_t,
        "best_joint": best_joint,
        "weighted_t_mean": weighted_t_mean,
        "weighted_t_std": weighted_t_std,
        "contributions": contributions,
    }


def main():
    print("[load] LLM YAML...")
    axes = parse_yaml_axes(LLM_YAML_PATH)
    axes_by_name = {a["name"]: a for a in axes}
    print(f"  {len(axes)} axes parsed")
    print(f"  axes covered by case mapping: {sum(1 for n in axes_by_name if n in AXIS_MAPPING)}/{len(AXIS_MAPPING)}")

    print("\n[load] cases...")
    cases = {}
    for name, p in CASE_PATHS.items():
        cases[name] = json.loads(p.read_text(encoding="utf-8"))

    print(f"\n[run] forward simulate (N_MC={N_MC}, t marginalized over [0, {T_MAX}])...")
    results = {}
    for name, case in cases.items():
        print(f"  {name}...")
        r_aosd = case_log_marginal(axes_by_name, case, N_MC, SEED, mode="trajectory")
        r_healthy = case_log_marginal(axes_by_name, case, N_MC, SEED, mode="healthy")
        log10_LR = (r_aosd["log_marginal"] - r_healthy["log_marginal"]) / np.log(10)
        results[name] = {
            "aosd": r_aosd,
            "healthy": r_healthy,
            "log10_LR": log10_LR,
        }
        print(f"    log P_AOSD = {r_aosd['log_marginal']:+.3f}")
        print(f"      best day = {r_aosd['best_t']:5.1f},  posterior day mean = {r_aosd['weighted_t_mean']:5.1f} ± {r_aosd['weighted_t_std']:.1f}")
        print(f"    log P_Healthy = {r_healthy['log_marginal']:+.3f}")
        print(f"    log10 LR = {log10_LR:+.3f}")

    # ============ Report ============
    L = []
    L.append("=" * 76)
    L.append(" v5 SDE Forward Simulate v1 — Day Marginalized (Curve Distillation)")
    L.append("=" * 76)
    L.append("")
    L.append(f"日期: 2026-04-30")
    L.append(f"N_MC: {N_MC}, seed: {SEED}, t_max: {T_MAX}")
    L.append(f"LLM 蒸馏: {len(axes)} axes (v5_AOSD.txt)")
    L.append(f"Case 用 axes: {len(AXIS_MAPPING)} (重合于静态 PoC 9 axes)")
    L.append("")
    L.append("Reference measure:")
    L.append("  - AOSD trajectory: μ_i(t), t ~ Uniform(0, 90)  (marginalize over day)")
    L.append("  - Healthy baseline: μ_i = baseline 恒定 (time-invariant)")
    L.append("v0 → v1 改动:")
    L.append("  - 废 CASE_DAY = {AOSD:11, MAS:10, healthy:14} 外部指定")
    L.append("  - log P(case | AOSD) = log [(1/T) ∫ ρ(case | t) dt]  (内部 marginal)")
    L.append("  - 报告 best_day (max joint log p) + posterior day mean ± std")
    L.append("")

    for name, r in results.items():
        case = cases[name]
        L.append("=" * 76)
        L.append(f" {name}")
        L.append("=" * 76)
        L.append(f"  case_id: {case['case_id']}")
        if case.get("pmid"):
            L.append(f"  PMID: {case['pmid']}")
        L.append(f"  diagnosis: {case['diagnosis']}")
        L.append(f"  observed axes (with mapping): {len(r['aosd']['contributions'])}")
        L.append("")
        L.append(f"  log P (marginal):")
        L.append(f"    AOSD trajectory : {r['aosd']['log_marginal']:+10.3f}")
        L.append(f"    Healthy baseline: {r['healthy']['log_marginal']:+10.3f}")
        L.append(f"    log10 LR        : {r['log10_LR']:+10.3f}  (>0 = AOSD-like)")
        L.append("")
        L.append(f"  AOSD trajectory implied day:")
        L.append(f"    best_day        : {r['aosd']['best_t']:5.1f}")
        L.append(f"    posterior mean  : {r['aosd']['weighted_t_mean']:5.1f} ± {r['aosd']['weighted_t_std']:.1f}")
        L.append("")
        L.append(f"  per-axis log_pdf at best_day (AOSD):")
        for case_key, llm_name, x_case, lp in r["aosd"]["contributions"]:
            L.append(f"    {case_key:35s} x={x_case:>10.3f}  log p={lp:+8.3f}")
        L.append("")

    # ranking
    L.append("=" * 76)
    L.append(" Ranking (log10 LR)")
    L.append("=" * 76)
    sorted_names = sorted(results.keys(), key=lambda n: -results[n]["log10_LR"])
    for i, name in enumerate(sorted_names):
        L.append(f"  {i+1}. {name:18s} log10 LR = {results[name]['log10_LR']:+10.3f}")
    L.append("")

    # validation
    L.append("=" * 76)
    L.append(" 验证")
    L.append("=" * 76)
    aosd_lr = results["case1_AOSD"]["log10_LR"]
    healthy_lr = results["case2_healthy"]["log10_LR"]
    mas_lr = results["case3_MAS"]["log10_LR"]
    aosd_best_t = results["case1_AOSD"]["aosd"]["best_t"]
    mas_best_t = results["case3_MAS"]["aosd"]["best_t"]

    L.append(f"  [1] AOSD case → AOSD > Healthy?  log10 LR = {aosd_lr:+.3f} {'PASS' if aosd_lr > 0 else 'FAIL'}")
    L.append(f"  [2] Healthy case → AOSD < Healthy? log10 LR = {healthy_lr:+.3f} {'PASS' if healthy_lr < 0 else 'FAIL'}")
    L.append(f"  [3] MAS case → AOSD > Healthy?    log10 LR = {mas_lr:+.3f} {'PASS' if mas_lr > 0 else 'FAIL'}")
    L.append(f"  [4] 极端度: MAS > AOSD?            MAS({mas_lr:+.3f}) > AOSD({aosd_lr:+.3f}) {'PASS' if mas_lr > aosd_lr else 'FAIL'}")
    L.append("")
    L.append(f"  Bonus: AOSD case implied day = {aosd_best_t:.1f}  (paper says day 11)")
    L.append(f"         MAS  case implied day = {mas_best_t:.1f}  (推测 acute phase)")
    L.append("")
    L.append("注意:")
    L.append("  - day 不再外部指定, trajectory 自己挑最 fit 的 day")
    L.append("  - implied day 离 paper-reported day 越近, 说明 trajectory 拟合越准")
    L.append("  - 极端度 [4] 可能仍 FAIL (AOSD trajectory 不能容纳 MAS subtype 的 PLT 暴跌)")
    L.append("    → 真要解需 LLM 单独蒸 MAS trajectory")

    text = "\n".join(L)
    print()
    print(text)
    RESULT_PATH.write_text(text, encoding="utf-8")
    print(f"\n[done] result written to {RESULT_PATH}")


if __name__ == "__main__":
    main()
