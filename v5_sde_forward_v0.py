"""
v5 SDE forward simulate v0 — first PoC of curve-distillation paradigm.

输入:
  - v5_AOSD.txt: LLM 蒸馏的 38-axis 曲线参数 (baseline / peak_day / peak_value / plateau / decline / log_scale)
  - v5_aosd_case_data.json:    AOSD real (PMC7725026)
  - v5_healthy_case_data.json: Healthy reference (Tietz)
  - v5_mas_case_data.json:     MAS real (PMC8148416)

工程简化 (v0):
  1. 每个 axis 独立 (no correlation matrix — LLM 没给)
  2. SDE 退化为 time-varying Gaussian: x_i(t) ~ Normal(μ_i(t), σ_i)
  3. μ_i(t) 分段函数: baseline → linear rise → plateau → optional decline
  4. σ_i 从 baseline_range 宽度估 (width / 4)
  5. log_scale=true 的 axis 在 log10 space 算
  6. 区间不确定性: Monte Carlo, 每次 uniform-sample 区间内参数
  7. 2-way 比较: AOSD trajectory vs Healthy baseline (无 MAS reference)

期望:
  - AOSD case: log10 LR > 0 (AOSD trajectory > healthy baseline)
  - Healthy case: log10 LR < 0
  - MAS case: log10 LR > 0 (但因为只有 AOSD trajectory，无法 vs MAS subtype)
"""
import json
import re
import numpy as np
from scipy import stats
from pathlib import Path

ROOT = Path(r"C:\Users\wangw\Desktop\vesmed_v5_poc")
LLM_YAML_PATH = ROOT / "v5_AOSD.txt"
CASE_PATHS = {
    "case1_AOSD":    ROOT / "v5_aosd_case_data.json",
    "case2_healthy": ROOT / "v5_healthy_case_data.json",
    "case3_MAS":     ROOT / "v5_mas_case_data.json",
}
RESULT_PATH = ROOT / "v5_sde_forward_v0_result.txt"

# Case 在病程哪一天 (从 source_quote / 临床判断)
CASE_DAY = {
    "case1_AOSD": 11,        # PMC7725026: "CRP 208 mg/L on day 11 of admission"
    "case2_healthy": 14,     # 健康人无病程; 用 day=14 (假设 AOSD 中段) 测试 → 健康值离 AOSD trajectory peak 远, log10 LR 应 << 0
    "case3_MAS": 10,         # PMC8148416: 急性期推测 day 10
}

N_MC = 10000
SEED = 42

# ============================================================================
# Axis mapping: LLM 38-axis name → static PoC 9-axis case key
# ============================================================================
# case 数据用的是 static PoC 的 9 个 key。这里把 LLM 的 axis 映射回去。
# 还要处理 unit 差异和 log_scale。

AXIS_MAPPING = {
    # LLM axis name : (case key, log_x_for_likelihood, unit_factor_llm_to_case, case_is_already_log10)
    # log_x_for_likelihood: True 表示在 log10 space 算 likelihood
    # unit_factor: case_value = LLM_value * factor (用于把 LLM 给的 native unit 转到 case 的 unit)
    # case_is_already_log10: case 给的值是否已经是 log10 (case key 含 log10_*)
    "body_temperature_daily_maximum":    ("peak_body_temperature",          False, 1.0,  False),
    "serum_ferritin":                    ("log10_serum_ferritin",           True,  1.0,  True),   # case 已 log10
    "glycosylated_ferritin_fraction":    ("glycosylated_ferritin_fraction", False, 1.0,  False),
    "c_reactive_protein":                ("CRP",                            True,  1.0,  False),  # case native, 需 log10
    "absolute_neutrophil_count":         ("absolute_neutrophil_count",      False, 1.0,  False),
    "platelet_count":                    ("platelet_count",                 False, 1.0,  False),
    "aspartate_aminotransferase":        ("log10_AST",                      True,  1.0,  True),   # case 已 log10
    "fibrinogen":                        ("fibrinogen",                     False, 0.01, False),  # LLM mg/dL → case g/L
    "interleukin_18":                    ("log10_serum_IL18",               True,  1.0,  True),   # case 已 log10
}

# Reverse: case key → LLM axis name
CASE_TO_LLM = {v[0]: k for k, v in AXIS_MAPPING.items()}


# ============================================================================
# Parse v5_AOSD.txt (loose YAML, manually)
# ============================================================================
def parse_yaml_axes(path):
    """简单 YAML parser, 只处理 v5_AOSD.txt 的结构."""
    text = path.read_text(encoding="utf-8")
    # 把每个 - axis_name 块切开
    blocks = re.split(r'(?m)^- axis_name:', text)[1:]  # 第一个 split 是 ""
    axes = []
    for blk in blocks:
        # restore the prefix
        blk = "- axis_name:" + blk
        ax = {}
        for line in blk.splitlines():
            m = re.match(r'\s*(?:- )?([a-z_]+):\s*(.*)$', line)
            if not m:
                continue
            key = m.group(1)
            val = m.group(2).strip()
            ax[key] = val
        # parse fields
        out = {
            "name": ax.get("axis_name", "").strip().strip('"'),
            "unit": ax.get("unit", "").strip().strip('"'),
            "log_scale": ax.get("log_scale", "false").lower() == "true",
            "shape_free_text": ax.get("shape_free_text", ""),
            "knowledge_confidence": ax.get("knowledge_confidence", "").strip(),
            "additional_notes": ax.get("additional_notes", ""),
        }
        # numeric interval fields
        for f in ["baseline_range", "peak_day_range", "peak_value_range",
                  "plateau_duration_days", "decline_half_life_days"]:
            v = ax.get(f, "null").strip()
            out[f] = parse_interval(v)
        out["second_peak"] = ax.get("second_peak", "null")
        axes.append(out)
    return axes


def parse_interval(s):
    """'[200, 1000]' → (200.0, 1000.0); 'null' → None"""
    s = s.strip()
    if s.lower() == "null" or s == "":
        return None
    m = re.match(r'\[\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\]', s)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    return None


# ============================================================================
# Trajectory model: μ_i(t) from LLM curve params
# ============================================================================
def sample_mu_at_day(axis, t, rng):
    """
    在 day t, 单个 axis 的 μ (区间内 uniform 采样一组参数后给出 μ).
    返回 mu (in LLM's native unit).
    """
    baseline = rng.uniform(*axis["baseline_range"])

    # 没有 peak: 恒定 baseline (差別诊断 axes / 下降型 axes)
    if axis["peak_day_range"] is None:
        # 简化: 这次先不处理下降型 (active < baseline) — 都 当 baseline 模式
        return baseline

    peak_day = rng.uniform(*axis["peak_day_range"])
    peak_value = rng.uniform(*axis["peak_value_range"])

    if axis["plateau_duration_days"] is None:
        plateau_dur = 0.0
    else:
        plateau_dur = rng.uniform(*axis["plateau_duration_days"])

    plateau_end = peak_day + plateau_dur

    if t <= 0:
        return baseline
    elif t < peak_day:
        # 线性升
        return baseline + (peak_value - baseline) * t / peak_day
    elif t < plateau_end:
        # plateau
        return peak_value
    else:
        # decline (or persist if half_life=null)
        if axis["decline_half_life_days"] is None:
            return peak_value
        else:
            hl = rng.uniform(*axis["decline_half_life_days"])
            decay = 0.5 ** ((t - plateau_end) / max(hl, 1e-6))
            return baseline + (peak_value - baseline) * decay


def axis_sigma(axis, log_scale_for_likelihood):
    """
    σ 估计: 用 baseline_range 宽度 / 4.
    如果 log_scale_for_likelihood, σ 在 log10 space 算 (从 baseline 区间 log 后取 width/4).
    """
    lo, hi = axis["baseline_range"]
    if log_scale_for_likelihood:
        # 区间转 log10 (注意 lo > 0)
        lo = max(lo, 1e-3)  # 避免 log(0)
        log_lo = np.log10(lo)
        log_hi = np.log10(hi)
        sigma = (log_hi - log_lo) / 4
        # 加底（避免 σ 太小）
        sigma = max(sigma, 0.1)
    else:
        sigma = (hi - lo) / 4
        sigma = max(sigma, 0.05 * abs(lo + hi) / 2 if (lo + hi) != 0 else 0.05)
    return sigma


# ============================================================================
# Likelihood: P(case obs | day=t, reference)
# ============================================================================
def log_pdf_axis(axis, t, x_case, log_scale_for_likelihood, unit_factor, case_is_already_log10, n_mc, rng):
    """
    单 axis 在 day=t 下, x_case (case unit) 的 log marginal pdf, MC over LLM 区间不确定.
    返回 log_pdf scalar (logsumexp over MC).
    """
    log_pdfs = np.zeros(n_mc)
    sigma = axis_sigma(axis, log_scale_for_likelihood)

    for k in range(n_mc):
        mu_llm_unit = sample_mu_at_day(axis, t, rng)
        mu_case_unit = mu_llm_unit * unit_factor

        if log_scale_for_likelihood:
            mu_for_lh = np.log10(max(mu_case_unit, 1e-10))
            if case_is_already_log10:
                x_for_lh = x_case  # 已是 log10
            else:
                x_for_lh = np.log10(max(x_case, 1e-10))  # native → log10
        else:
            x_for_lh = x_case
            mu_for_lh = mu_case_unit

        log_pdfs[k] = stats.norm.logpdf(x_for_lh, mu_for_lh, sigma)

    from scipy.special import logsumexp
    return logsumexp(log_pdfs) - np.log(n_mc)


def case_log_likelihood(axes_by_name, case, day, n_mc, seed, mode="trajectory"):
    """
    case 在指定 day, 在 reference (mode='trajectory' = AOSD; mode='healthy' = baseline) 下的 log likelihood.
    Sum over observed axes (case key 有 mapping 到 LLM axis 的 + value not missing).
    """
    rng = np.random.default_rng(seed)
    total_log_p = 0.0
    contributions = []  # 每个 axis 的贡献

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
        x_case = val_dict["value"]

        if mode == "healthy":
            t_eff = -1  # baseline mode
        else:
            t_eff = day

        axis_rng = np.random.default_rng(seed + hash(llm_name) % 1000)
        lp = log_pdf_axis(axis, t_eff, x_case, log_scale, unit_factor, case_is_log10, n_mc, axis_rng)
        total_log_p += lp
        contributions.append((case_key, llm_name, x_case, lp))

    return total_log_p, contributions


# ============================================================================
# Main
# ============================================================================
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
    print(f"  {len(cases)} cases")

    print("\n[run] forward simulate + likelihood...")
    results = {}
    for name, case in cases.items():
        day = CASE_DAY.get(name)
        if day is None:
            day = 0  # healthy reference
        print(f"  {name} (day={day})...")
        lp_aosd, contrib_aosd = case_log_likelihood(axes_by_name, case, day, N_MC, SEED, mode="trajectory")
        lp_healthy, contrib_healthy = case_log_likelihood(axes_by_name, case, day, N_MC, SEED, mode="healthy")
        log10_LR = (lp_aosd - lp_healthy) / np.log(10)
        results[name] = {
            "day": day,
            "lp_aosd": lp_aosd,
            "lp_healthy": lp_healthy,
            "log10_LR": log10_LR,
            "contrib_aosd": contrib_aosd,
            "contrib_healthy": contrib_healthy,
        }
        print(f"    log P_AOSD = {lp_aosd:+.3f}, log P_Healthy = {lp_healthy:+.3f}, log10 LR = {log10_LR:+.3f}")

    # =========================================================================
    # Report
    # =========================================================================
    L = []
    L.append("=" * 76)
    L.append(" v5 SDE Forward Simulate v0 — Curve Distillation Paradigm 第一跑")
    L.append("=" * 76)
    L.append("")
    L.append(f"日期: 2026-04-29")
    L.append(f"N_MC: {N_MC}, seed: {SEED}")
    L.append(f"LLM 蒸馏: {len(axes)} axes (v5_AOSD.txt)")
    L.append(f"Case 用 axes: {len(AXIS_MAPPING)} (重合于静态 PoC 9 axes)")
    L.append("")
    L.append("Reference measure:")
    L.append("  - AOSD trajectory: μ_i(t) 时间剧本 (baseline → peak → plateau → optional decline)")
    L.append("  - Healthy baseline: μ_i 恒定 baseline_range")
    L.append("简化:")
    L.append("  - axes 独立 (no correlation)")
    L.append("  - σ_i = baseline_range width / 4")
    L.append("  - log_scale=true 的 axis 在 log10 space 算")
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
        L.append(f"  effective day: {r['day']}")
        L.append(f"  observed axes (with mapping): {len(r['contrib_aosd'])}")
        L.append("")
        L.append(f"  log P (sum over axes):")
        L.append(f"    AOSD trajectory : {r['lp_aosd']:+10.3f}")
        L.append(f"    Healthy baseline: {r['lp_healthy']:+10.3f}")
        L.append(f"    log10 LR        : {r['log10_LR']:+10.3f}  (>0 = AOSD-like, <0 = Healthy-like)")
        L.append("")
        L.append(f"  per-axis log_pdf (AOSD trajectory):")
        for case_key, llm_name, x_case, lp in r["contrib_aosd"]:
            L.append(f"    {case_key:35s} x={x_case:>10.3f}  log p={lp:+8.3f}")
        L.append("")
        L.append(f"  per-axis log_pdf (Healthy baseline):")
        for case_key, llm_name, x_case, lp in r["contrib_healthy"]:
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
    L.append(" 验证 (2-way: AOSD trajectory vs Healthy baseline)")
    L.append("=" * 76)
    aosd_lr = results["case1_AOSD"]["log10_LR"]
    healthy_lr = results["case2_healthy"]["log10_LR"]
    mas_lr = results["case3_MAS"]["log10_LR"]
    L.append(f"  [1] AOSD case → AOSD trajectory > Healthy baseline?")
    L.append(f"      log10 LR = {aosd_lr:+.3f} {'PASS' if aosd_lr > 0 else 'FAIL'}")
    L.append(f"  [2] Healthy case → Healthy baseline > AOSD trajectory?")
    L.append(f"      log10 LR = {healthy_lr:+.3f} {'PASS' if healthy_lr < 0 else 'FAIL'}")
    L.append(f"  [3] MAS case → AOSD trajectory > Healthy baseline?")
    L.append(f"      log10 LR = {mas_lr:+.3f} {'PASS' if mas_lr > 0 else 'FAIL'}")
    L.append(f"  [4] 极端度: MAS log10 LR > AOSD log10 LR?")
    L.append(f"      MAS ({mas_lr:+.3f}) > AOSD ({aosd_lr:+.3f}) {'PASS' if mas_lr > aosd_lr else 'FAIL'}")
    L.append("")
    L.append("注意:")
    L.append("  - 没有 MAS-specific reference, 这次只能比 vs Healthy")
    L.append("  - MAS subtype 区分 需要单独蒸馏 MAS trajectory 才能做")
    L.append("  - 静态 PoC 之前用 GMM components 区分 MAS subtype, 在 v5 SDE 里需要单独 trajectory")

    text = "\n".join(L)
    print()
    print(text)

    RESULT_PATH.write_text(text, encoding="utf-8")
    print(f"\n[done] result written to {RESULT_PATH}")


if __name__ == "__main__":
    main()
