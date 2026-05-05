"""
v5 流体架构 PoC：AOSD case + GMM(区间) + MC10000 → LR 区间

核心计算:
  LR_AOSD(x*) = ρ_disease(x*) / ρ_healthy(x*)

x* 是 9 维向量（缺失轴 NaN，会被 marginalize out）。
ρ 是 LLM 蒸馏的 GMM-with-interval-params。
MC 10000 次：每次在每个区间内 uniform 采样 → 一组点估计 → 一个 ρ → 一个 LR。
最后输出 LR 的 5/50/95 percentile + min/max。
"""
import json
import numpy as np
from scipy.special import logsumexp
from scipy.stats import multivariate_normal as mvn

GMM_PATH = r"C:\Users\wangw\Desktop\AOSD.txt"
CASE_PATH = r"C:\Users\wangw\Desktop\v5_aosd_case_data.json"
RESULT_PATH = r"C:\Users\wangw\Desktop\v5_aosd_poc_result.txt"

N_MC = 10000
SEED = 42
EPS = 1e-6


def higham_psd_corr(corr, eps=EPS):
    """Project a (possibly invalid) correlation matrix to nearest PSD,
    keeping diagonal = 1."""
    corr = (corr + corr.T) / 2.0
    np.fill_diagonal(corr, 1.0)
    eigvals, eigvecs = np.linalg.eigh(corr)
    eigvals_clipped = np.clip(eigvals, eps, None)
    M = eigvecs @ np.diag(eigvals_clipped) @ eigvecs.T
    d = np.sqrt(np.diag(M))
    M = M / np.outer(d, d)
    np.fill_diagonal(M, 1.0)
    return M


def sample_component(component_dict, rng):
    """In each [low, high] interval, uniform sample one value -> one concrete component."""
    weight = rng.uniform(*component_dict["weight"])
    n = len(component_dict["mu"])
    mu = np.array([rng.uniform(lo, hi) for lo, hi in component_dict["mu"]])
    sigma = np.array([rng.uniform(lo, hi) for lo, hi in component_dict["sigma"]])

    # Sample correlation matrix elementwise
    corr = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            lo, hi = component_dict["corr"][i][j]
            corr[i, j] = rng.uniform(lo, hi)

    # Project to valid PSD correlation
    corr = higham_psd_corr(corr)

    # Build covariance Σ = corr * outer(σ, σ)
    Sigma = corr * np.outer(sigma, sigma)
    # Numerical safety
    Sigma = (Sigma + Sigma.T) / 2.0
    return weight, mu, Sigma


def sample_gmm_concrete(gmm_dict, rng):
    """Sample one concrete GMM (list of (w, mu, Sigma))."""
    components = [sample_component(c, rng) for c in gmm_dict["components"]]
    # Normalize weights to sum to 1
    weights = np.array([c[0] for c in components])
    weights = weights / weights.sum()
    return [(weights[k], components[k][1], components[k][2]) for k in range(len(components))]


def log_marginal_gmm_pdf(components, x_obs, obs_idx):
    """log p(x_obs) for a concrete GMM, marginalizing out unobserved axes.

    For multivariate Gaussian, marginalizing out axes is just taking sub-mean
    and sub-covariance on the observed axes.
    """
    log_pieces = []
    for w, mu, Sigma in components:
        mu_obs = mu[obs_idx]
        Sigma_obs = Sigma[np.ix_(obs_idx, obs_idx)]
        # Numerical safety on sub-matrix
        Sigma_obs = (Sigma_obs + Sigma_obs.T) / 2.0
        # Add tiny ridge for stability
        Sigma_obs = Sigma_obs + EPS * np.eye(len(obs_idx))
        try:
            lp = mvn.logpdf(x_obs, mu_obs, Sigma_obs, allow_singular=True)
        except Exception:
            return -np.inf
        log_pieces.append(np.log(max(w, 1e-300)) + lp)
    return logsumexp(log_pieces)


def main():
    # Load
    with open(GMM_PATH, encoding="utf-8") as f:
        gmm = json.load(f)
    with open(CASE_PATH, encoding="utf-8") as f:
        case = json.load(f)

    # Build x*
    axis_keys = [
        "peak_body_temperature",
        "log10_serum_ferritin",
        "glycosylated_ferritin_fraction",
        "CRP",
        "absolute_neutrophil_count",
        "platelet_count",
        "log10_AST",
        "fibrinogen",
        "log10_serum_IL18",
    ]
    x_star_full = np.array(
        [case["axes_values"][k]["value"] if not case["axes_values"][k]["missing"] else np.nan
         for k in axis_keys]
    )
    obs_idx = np.array(case["observed_axes_indices"])
    x_obs = x_star_full[obs_idx]

    print(f"[setup] axes total = {len(axis_keys)}")
    print(f"[setup] observed = {len(obs_idx)} (indices {list(obs_idx)})")
    print(f"[setup] missing = {[i for i in range(9) if i not in obs_idx]}")
    print(f"[setup] x* full = {x_star_full}")
    print(f"[setup] x* observed = {x_obs}")
    print(f"[setup] N_MC = {N_MC}, seed = {SEED}")

    # MC loop
    rng = np.random.default_rng(SEED)
    log_LRs = np.zeros(N_MC)
    log_pds = np.zeros(N_MC)
    log_phs = np.zeros(N_MC)
    n_invalid = 0

    for i in range(N_MC):
        comp_d = sample_gmm_concrete(gmm["rho_disease"], rng)
        comp_h = sample_gmm_concrete(gmm["rho_healthy"], rng)
        lp_d = log_marginal_gmm_pdf(comp_d, x_obs, obs_idx)
        lp_h = log_marginal_gmm_pdf(comp_h, x_obs, obs_idx)
        if not (np.isfinite(lp_d) and np.isfinite(lp_h)):
            n_invalid += 1
            log_LRs[i] = np.nan
        else:
            log_pds[i] = lp_d
            log_phs[i] = lp_h
            log_LRs[i] = lp_d - lp_h

    valid = np.isfinite(log_LRs)
    log_LRs_v = log_LRs[valid]
    log_pds_v = log_pds[valid]
    log_phs_v = log_phs[valid]

    print(f"\n[MC] valid samples = {valid.sum()}/{N_MC}, invalid = {n_invalid}")

    # Stats
    pcts = [1, 5, 25, 50, 75, 95, 99]
    stats = {p: float(np.percentile(log_LRs_v, p)) for p in pcts}
    log_LR_min = float(log_LRs_v.min())
    log_LR_max = float(log_LRs_v.max())
    log_LR_med = float(np.median(log_LRs_v))

    # Build result text
    lines = []
    lines.append("=" * 72)
    lines.append(" v5 流体架构 PoC — AOSD real case 实测")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"日期: 2026-04-29")
    lines.append(f"Case: PMID {case['pmid']} / {case['pmc_id']}")
    lines.append(f"  Title: {case['title']}")
    lines.append(f"  URL: {case['url']}")
    lines.append(f"  Diagnosis: {case['diagnosis']}")
    lines.append("")
    lines.append("观测 6/9 轴 (缺失: glycosylated_ferritin, platelet, IL-18)")
    lines.append("")
    lines.append("x* full vector:")
    for i, k in enumerate(axis_keys):
        v = case["axes_values"][k]
        marker = "  " if v["missing"] else "*"
        val = "MISSING" if v["missing"] else f"{v['value']}"
        lines.append(f"  [{marker}] axis {i:1d} {k:36s} = {val} ({v['unit']})")
    lines.append("")
    lines.append("=" * 72)
    lines.append(" MC 结果 (10000 次 uniform sampling in intervals)")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"valid samples: {valid.sum()} / {N_MC} (invalid: {n_invalid})")
    lines.append("")
    lines.append("log10 LR distribution (NOTE: 用 log10 因为 LR 远超 float64):")
    log10_LR_min = log_LR_min / np.log(10)
    log10_LR_max = log_LR_max / np.log(10)
    log10_LR_med = log_LR_med / np.log(10)
    lines.append(f"  min        : log10_LR = {log10_LR_min:+.3f}")
    lines.append(f"  1%         : log10_LR = {stats[1]/np.log(10):+.3f}")
    lines.append(f"  5%         : log10_LR = {stats[5]/np.log(10):+.3f}")
    lines.append(f"  25%        : log10_LR = {stats[25]/np.log(10):+.3f}")
    lines.append(f"  50% (med)  : log10_LR = {log10_LR_med:+.3f}")
    lines.append(f"  75%        : log10_LR = {stats[75]/np.log(10):+.3f}")
    lines.append(f"  95%        : log10_LR = {stats[95]/np.log(10):+.3f}")
    lines.append(f"  99%        : log10_LR = {stats[99]/np.log(10):+.3f}")
    lines.append(f"  max        : log10_LR = {log10_LR_max:+.3f}")
    lines.append("")
    lines.append("(LR 数量级太大没法用 float 直接表示，用 log10 看)")
    lines.append("")
    lines.append("分项: log p(x* | disease) vs log p(x* | healthy)")
    lines.append(f"  log p_d median = {np.median(log_pds_v):+.3f}")
    lines.append(f"  log p_h median = {np.median(log_phs_v):+.3f}")
    lines.append("")
    lines.append("=" * 72)
    lines.append(" 临床判读")
    lines.append("=" * 72)
    lines.append("")
    if log10_LR_med > 2:
        verdict = "强烈支持 AOSD (log10 LR > 2 = LR > 100, Oxford CEBM 阈值)"
    elif log10_LR_med > 1:
        verdict = "倾向 AOSD (log10 LR > 1 = LR > 10)"
    elif log10_LR_med > 0.3:
        verdict = "弱支持 AOSD"
    elif log10_LR_med > -0.3:
        verdict = "中性"
    else:
        verdict = "倾向不是 AOSD"
    lines.append(f"  log10 LR median = {log10_LR_med:+.3f} → {verdict}")
    if log10_LR_med > 100:
        lines.append("  [WARN] log10 LR 极大 (>100)，提示模型 misspecification:")
        lines.append("     可能原因: 健康人 GMM 方差过窄 / CRP 等长尾变量未 log-transform")
    lines.append("")
    lr_orders = (log_LR_max - log_LR_min) / np.log(10)
    if lr_orders < 1:
        stab = "极稳定"
    elif lr_orders < 3:
        stab = "稳定"
    elif lr_orders < 6:
        stab = "中等波动"
    else:
        stab = "高波动 (区间宽 > 6 数量级，警示)"
    lines.append(f"  LR 区间跨度: {lr_orders:.2f} 数量级 → {stab}")
    lines.append("")
    lines.append(f"  期望: AOSD 真实 case → LR_AOSD >> 1 (理想 > 100)")
    lines.append("")
    lines.append("=" * 72)
    lines.append(" 工程 metrics")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"  N_MC: {N_MC}")
    lines.append(f"  invalid samples: {n_invalid} ({100*n_invalid/N_MC:.2f}%)")
    lines.append(f"  Higham PSD projection applied per sample")
    lines.append(f"  observed axes: {len(obs_idx)}/9 (marginalized 3 missing)")
    lines.append("")

    text = "\n".join(lines)
    print()
    print(text)

    with open(RESULT_PATH, "w", encoding="utf-8") as f:
        f.write(text)

    print()
    print(f"[done] result written to {RESULT_PATH}")


if __name__ == "__main__":
    main()
