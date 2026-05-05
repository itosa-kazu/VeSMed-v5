"""
v5 SDE forward simulate v2 — 4-way ranking (AOSD / HLH / Healthy 三流形 × 3 case)

vs v1 改动:
  - 加 HLH 流形 (v5_D-HLH.txt) → AOSD/HLH/Healthy 三方 ranking
  - YAML parser 兼容 '* axis_name:' (LLM 偶尔用错的 list marker)
  - 加 JSON parser (.json 自动切, 未来 schema)
  - LLM log_scale 从 axis 自己读 (流形内部一致, 不再硬编码在 mapping)

期待:
  - case1_AOSD  → AOSD 最高
  - case2_health→ Healthy 最高
  - case3_MAS   → HLH > AOSD (PLT 55, fibrinogen 1.35 在 HLH 流形 nadir 区间内)
"""
import json
import re
import numpy as np
from scipy import stats
from scipy.special import logsumexp
from pathlib import Path

ROOT = Path(r"C:\Users\wangw\Desktop\vesmed_v5_poc")

MANIFOLDS = {
    "AOSD": ROOT / "v5_AOSD.txt",
    "HLH":  ROOT / "v5_D-HLH.txt",
}

CASE_PATHS = {
    "case1_AOSD":    ROOT / "v5_aosd_case_data.json",
    "case2_healthy": ROOT / "v5_healthy_case_data.json",
    "case3_MAS":     ROOT / "v5_mas_case_data.json",
}

RESULT_PATH = ROOT / "v5_sde_forward_v2_result.txt"
N_MC = 10000
SEED = 42
T_MAX_BY_LABEL = {"AOSD": 90, "HLH": 60}


# Case axis name → (LLM axis name in this manifold, unit_factor, case_is_already_log10)
AOSD_MAPPING = {
    "peak_body_temperature":          ("body_temperature_daily_maximum",  1.0,  False),
    "log10_serum_ferritin":           ("serum_ferritin",                  1.0,  True),
    "glycosylated_ferritin_fraction": ("glycosylated_ferritin_fraction",  1.0,  False),
    "CRP":                            ("c_reactive_protein",              1.0,  False),
    "absolute_neutrophil_count":      ("absolute_neutrophil_count",       1.0,  False),
    "platelet_count":                 ("platelet_count",                  1.0,  False),
    "log10_AST":                      ("aspartate_aminotransferase",      1.0,  True),
    "fibrinogen":                     ("fibrinogen",                      0.01, False),  # mg/dL→g/L
    "log10_serum_IL18":               ("interleukin_18",                  1.0,  True),
}

HLH_MAPPING = {
    "peak_body_temperature":          ("body_temperature",                1.0,  False),
    "log10_serum_ferritin":           ("serum_ferritin",                  1.0,  True),
    # glycosylated_ferritin_fraction: HLH 流形 LLM 没蒸 → skip
    "CRP":                            ("c_reactive_protein",              1.0,  False),
    "absolute_neutrophil_count":      ("absolute_neutrophil_count",       1.0,  False),
    "platelet_count":                 ("platelet_count",                  1.0,  False),
    "log10_AST":                      ("aspartate_aminotransferase_ast",  1.0,  True),
    "fibrinogen":                     ("fibrinogen",                      1.0,  False),  # 已 g/L
    "log10_serum_IL18":               ("plasma_il18",                     1.0,  True),
}

MAPPING_BY_LABEL = {"AOSD": AOSD_MAPPING, "HLH": HLH_MAPPING}


# ---------- parsers ----------

def parse_interval(s):
    if s is None:
        return None
    if isinstance(s, list):
        if len(s) < 2:
            return None
        return (float(s[0]), float(s[1]))
    s = str(s).strip()
    if s.lower() in ("null", "none", "~", ""):
        return None
    m = re.match(r'\[\s*([-\d.eE+]+)\s*,\s*([-\d.eE+]+)\s*\]', s)
    if m:
        return (float(m.group(1)), float(m.group(2)))
    return None


def parse_yaml_axes(path: Path):
    """Tolerant YAML parser: accept both '- axis_name:' and '* axis_name:'."""
    text = path.read_text(encoding="utf-8")
    text = re.sub(r'(?m)^\*\s+axis_name:', '- axis_name:', text)
    blocks = re.split(r'(?m)^- axis_name:', text)[1:]
    axes = []
    for blk in blocks:
        blk = "- axis_name:" + blk
        ax = {}
        for line in blk.splitlines():
            m = re.match(r'\s*(?:- )?([a-z0-9_]+):\s*(.*)$', line)
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


def parse_json_axes(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "axes" in data:
        data = data["axes"]
    axes = []
    for raw in data:
        out = {
            "name": str(raw.get("axis_name", "")).strip(),
            "unit": str(raw.get("unit", "")).strip(),
            "log_scale": bool(raw.get("log_scale", False)),
            "knowledge_confidence": str(raw.get("knowledge_confidence", "")).strip(),
        }
        for f in ["baseline_range", "peak_day_range", "peak_value_range",
                  "plateau_duration_days", "decline_half_life_days"]:
            out[f] = parse_interval(raw.get(f))
        axes.append(out)
    return axes


def load_axes(path: Path):
    """嗅探内容: 以 [ 或 { 开头 → JSON; 否则 YAML. 不依赖文件扩展名 (UI 默认 save 成 .txt)."""
    text = path.read_text(encoding="utf-8")
    stripped = text.lstrip()
    if path.suffix == ".json" or stripped.startswith('[') or stripped.startswith('{'):
        return parse_json_axes(path)
    return parse_yaml_axes(path)


# ---------- SDE forward ----------

def sample_mu_at_day(axis, t, rng):
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


def axis_sigma(axis):
    lo, hi = axis["baseline_range"]
    if axis["log_scale"]:
        lo = max(lo, 1e-3)
        hi = max(hi, lo * 1.01)
        sigma = (np.log10(hi) - np.log10(lo)) / 4
        sigma = max(sigma, 0.1)
    else:
        spread = (hi - lo) / 4
        avg = (lo + hi) / 2
        if avg == 0:
            sigma = max(spread, 0.5)
        else:
            sigma = max(spread, 0.05 * abs(avg))
    return sigma


def build_observed(axes_by_name, case, mapping):
    observed = []
    for case_key, val_dict in case["axes_values"].items():
        if val_dict["missing"]:
            continue
        if case_key not in mapping:
            continue
        llm_name, unit_factor, case_is_log10 = mapping[case_key]
        if llm_name not in axes_by_name:
            continue
        axis = axes_by_name[llm_name]
        observed.append({
            "case_key": case_key,
            "llm_name": llm_name,
            "axis": axis,
            "unit_factor": unit_factor,
            "case_is_log10": case_is_log10,
            "x_case": val_dict["value"],
            "sigma": axis_sigma(axis),
        })
    return observed


def case_log_marginal(observed, n_mc, seed, mode, t_max):
    rng = np.random.default_rng(seed)
    n = len(observed)
    if n == 0:
        return {
            "log_marginal": float("nan"),
            "best_t": float("nan"),
            "weighted_t_mean": float("nan"),
            "weighted_t_std": float("nan"),
            "contributions": [],
            "n_observed": 0,
        }

    log_joint_per_mc = np.zeros(n_mc)
    per_axis_lps = np.zeros((n_mc, n))
    t_samples = np.zeros(n_mc)

    for k in range(n_mc):
        t = -1.0 if mode == "healthy" else rng.uniform(0, t_max)
        t_samples[k] = t

        joint = 0.0
        for j, ax in enumerate(observed):
            mu_llm = sample_mu_at_day(ax["axis"], t, rng)
            mu_case = mu_llm * ax["unit_factor"]

            if ax["axis"]["log_scale"]:
                mu_for_lh = np.log10(max(mu_case, 1e-10))
                x_for_lh = ax["x_case"] if ax["case_is_log10"] else np.log10(max(ax["x_case"], 1e-10))
            else:
                mu_for_lh = mu_case
                x_for_lh = (10 ** ax["x_case"]) if ax["case_is_log10"] else ax["x_case"]

            lp = stats.norm.logpdf(x_for_lh, mu_for_lh, ax["sigma"])
            joint += lp
            per_axis_lps[k, j] = lp

        log_joint_per_mc[k] = joint

    log_marginal = logsumexp(log_joint_per_mc) - np.log(n_mc)

    best_k = int(np.argmax(log_joint_per_mc))
    best_t = float(t_samples[best_k])

    weights = np.exp(log_joint_per_mc - log_joint_per_mc.max())
    weights = weights / weights.sum()
    weighted_t_mean = float(np.sum(weights * t_samples))
    weighted_t_std = float(np.sqrt(np.sum(weights * (t_samples - weighted_t_mean) ** 2)))

    contributions = [
        (ax["case_key"], ax["llm_name"], ax["x_case"], float(per_axis_lps[best_k, j]))
        for j, ax in enumerate(observed)
    ]

    return {
        "log_marginal": float(log_marginal),
        "best_t": best_t,
        "weighted_t_mean": weighted_t_mean,
        "weighted_t_std": weighted_t_std,
        "contributions": contributions,
        "n_observed": n,
    }


# ---------- main ----------

def main():
    print("[load] manifolds...")
    manifolds = {}
    for label, path in MANIFOLDS.items():
        axes = load_axes(path)
        manifolds[label] = {
            "label": label,
            "path": path,
            "axes_by_name": {a["name"]: a for a in axes},
            "n_axes": len(axes),
        }
        n_mapped = sum(1 for case_axis, (llm_axis, _, _) in MAPPING_BY_LABEL[label].items()
                       if llm_axis in manifolds[label]["axes_by_name"])
        print(f"  {label:8s}: {len(axes):3d} axes  (mapping covers {n_mapped}/{len(MAPPING_BY_LABEL[label])} case axes)")

    print("\n[load] cases...")
    cases = {}
    for name, p in CASE_PATHS.items():
        cases[name] = json.loads(p.read_text(encoding="utf-8"))
        n_obs = sum(1 for v in cases[name]["axes_values"].values() if not v["missing"])
        print(f"  {name:14s}: {n_obs} observed axes")

    print(f"\n[run] forward simulate (N_MC={N_MC})...")
    results = {}
    for case_name, case in cases.items():
        results[case_name] = {}
        for manifold_label, manifold in manifolds.items():
            mapping = MAPPING_BY_LABEL[manifold_label]
            t_max = T_MAX_BY_LABEL[manifold_label]
            observed = build_observed(manifold["axes_by_name"], case, mapping)
            r = case_log_marginal(observed, N_MC, SEED, mode="trajectory", t_max=t_max)
            r["t_max"] = t_max
            results[case_name][manifold_label] = r
        # Healthy (涌现): 不蒸馏, 用任一 disease 流形的 baseline_range (LLM 在每个流形对健康人估计应一致).
        # TODO 多流形蒸完后改成跨流形 mean baseline_range (真正的"涌现交集").
        observed_h = build_observed(manifolds["AOSD"]["axes_by_name"], case, AOSD_MAPPING)
        r_h = case_log_marginal(observed_h, N_MC, SEED, mode="healthy", t_max=T_MAX_BY_LABEL["AOSD"])
        r_h["t_max"] = T_MAX_BY_LABEL["AOSD"]
        results[case_name]["Healthy"] = r_h

    # =========== Report ===========
    L = []
    L.append("=" * 84)
    L.append(" v5 SDE Forward Simulate v2 — 4-way ranking (AOSD / HLH / Healthy)")
    L.append("=" * 84)
    L.append(f"日期: 2026-04-30   N_MC: {N_MC}   seed: {SEED}")
    L.append("")
    L.append("流形:")
    for label, m in manifolds.items():
        n_mapped = sum(1 for case_axis, (llm_axis, _, _) in MAPPING_BY_LABEL[label].items()
                       if llm_axis in m["axes_by_name"])
        L.append(f"  {label:8s}: {m['n_axes']:3d} axes (蒸馏)  / mapping {n_mapped}/{len(MAPPING_BY_LABEL[label])}  / t_max={T_MAX_BY_LABEL[label]}d")
    L.append(f"  Healthy : 退化 mode (用 AOSD axes baseline_range, t=-1)")
    L.append("")

    for case_name, case in cases.items():
        L.append("=" * 84)
        L.append(f" {case_name}   {case['case_id']}   {case['diagnosis']}")
        L.append("=" * 84)
        r = results[case_name]
        L.append(f"  log P (marginal):")
        for label in ["AOSD", "HLH", "Healthy"]:
            rr = r[label]
            extra = ""
            if label != "Healthy" and not np.isnan(rr["log_marginal"]):
                extra = f"   (best_t={rr['best_t']:5.1f}, post={rr['weighted_t_mean']:5.1f}±{rr['weighted_t_std']:.1f})"
            L.append(f"    {label:8s}: {rr['log_marginal']:+12.3f}  [n_obs={rr['n_observed']}]{extra}")
        sorted_by_lm = sorted(["AOSD", "HLH", "Healthy"], key=lambda x: -r[x]["log_marginal"])
        L.append(f"  → ranking: {' > '.join(sorted_by_lm)}")
        L.append("")
        L.append(f"  per-axis log_pdf at HLH best_t:")
        for case_key, llm_name, x_case, lp in r["HLH"]["contributions"]:
            L.append(f"    {case_key:35s} → {llm_name:35s} x={x_case:>10.3f}  log p={lp:+8.3f}")
        L.append("")

    # =========== Summary table ===========
    L.append("=" * 84)
    L.append(" 4-way Ranking 表")
    L.append("=" * 84)
    L.append(f"  {'Case':18s}  {'AOSD':>12s}  {'HLH':>12s}  {'Healthy':>12s}  {'best':>10s}")
    L.append(f"  {'-'*18}  {'-'*12}  {'-'*12}  {'-'*12}  {'-'*10}")
    for case_name in cases:
        r = results[case_name]
        a = r["AOSD"]["log_marginal"]
        h = r["HLH"]["log_marginal"]
        hl = r["Healthy"]["log_marginal"]
        best_label = max(("AOSD", a), ("HLH", h), ("Healthy", hl), key=lambda x: x[1])[0]
        L.append(f"  {case_name:18s}  {a:+12.3f}  {h:+12.3f}  {hl:+12.3f}  {best_label:>10s}")
    L.append("")

    # =========== Validation ===========
    L.append("=" * 84)
    L.append(" 验证 (Pass / Fail)")
    L.append("=" * 84)
    L.append("")
    L.append("[A] 流形归属 check (每个 case 应落在正确的流形)")
    expected = {
        "case1_AOSD":    "AOSD",
        "case2_healthy": "Healthy",
        "case3_MAS":     "HLH",
    }
    pass_count = 0
    total = 0
    for i, (case_name, exp) in enumerate(expected.items(), 1):
        r = results[case_name]
        ranks = sorted(["AOSD", "HLH", "Healthy"], key=lambda x: -r[x]["log_marginal"])
        ok = ranks[0] == exp
        total += 1
        if ok:
            pass_count += 1
        L.append(f"  [{i}] {case_name:18s} expected: {exp:8s}  got: {ranks[0]:8s}  {'PASS' if ok else 'FAIL'}")

    L.append("")
    L.append("[B] 跨流形分离强度 check (V5 时代极端度, 替代 v1 [4]: MAS_LR > AOSD_LR)")
    mas_hlh   = results["case3_MAS"]["HLH"]["log_marginal"]
    mas_aosd  = results["case3_MAS"]["AOSD"]["log_marginal"]
    sep_mas   = mas_hlh - mas_aosd
    ok_mas    = sep_mas > 0
    total += 1
    if ok_mas: pass_count += 1
    L.append(f"  [4] MAS  case: HLH({mas_hlh:+.2f}) > AOSD({mas_aosd:+.2f})?   Δ={sep_mas:+.2f} nat  {'PASS' if ok_mas else 'FAIL'}")

    aosd_aosd = results["case1_AOSD"]["AOSD"]["log_marginal"]
    aosd_hlh  = results["case1_AOSD"]["HLH"]["log_marginal"]
    sep_aosd  = aosd_aosd - aosd_hlh
    ok_aosd   = sep_aosd > 0
    total += 1
    if ok_aosd: pass_count += 1
    L.append(f"  [5] AOSD case: AOSD({aosd_aosd:+.2f}) > HLH({aosd_hlh:+.2f})?  Δ={sep_aosd:+.2f} nat  {'PASS' if ok_aosd else 'FAIL'}")

    L.append("")
    L.append(f"  → {pass_count}/{total} PASS  ([A] 3 ranking + [B] 2 separation)")
    L.append("")
    L.append("注:")
    L.append("  - HLH 流形 = trigger-agnostic 蒸馏 (rheum/感染/肿瘤/药物 都 collapse 进同流形)")
    L.append("  - v1 的 [4] 极端度 (MAS_LR > AOSD_LR_in_AOSD_manifold) 在 v2 已过时")
    L.append("    → v2 改成 [4][5] 跨流形分离: 每个 case 应在其正确流形最 fit, 且和别的流形拉开")
    L.append("  - MAS case 在 HLH 比 AOSD 流形高 ≈ trigger-agnostic 流形精确容纳 cytopenia 特征")
    L.append("  - AOSD case 在 AOSD 比 HLH 流形高 ≈ AOSD non-MAS 流形排除嗜中性球减少特征")

    text = "\n".join(L)
    print()
    print(text)
    RESULT_PATH.write_text(text, encoding="utf-8")
    print(f"\n[done] result written to {RESULT_PATH}")


if __name__ == "__main__":
    main()
