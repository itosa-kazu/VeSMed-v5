"""
V5: AOSD (D137) 最优治疗 emergent ranking

输入: distillations/v5_D137.json
方法:
  1. mortality_hazard axis = 唯一决定 lifespan 的轴 (其他 axes 在当前 schema 下与 hazard 无 coupling)
  2. untreated trajectory: baseline -> peak -> plateau -> decline
  3. 每个治疗的 trajectory_modifications.mortality_hazard_in_D137 应用到 trajectory
     - peak_value_factor: 把 peak hazard 乘以这个因子 (越低越好)
     - plateau_duration_factor: 把 plateau 长度乘以这个因子 (越短越好)
     - decline_half_life_days: 治疗后 hazard 衰减的半衰期 (越短越好)
  4. lifespan = E[min(T_death, T_max)] = ∫₀^T_max exp(-Λ(t)) dt
     其中 Λ(t) = ∫₀^t λ(s) ds 是 cumulative hazard
  5. Monte Carlo 抽样 trajectory params 区间 N=500 次, 取 mean lifespan
  6. ranking by mean lifespan ↑ → emergent first-line

注意: 11/14 治疗没标 mortality_hazard 修饰, 这些等价于 untreated, 所以 ranking 末尾会 tied at baseline.
"""
import json
import sys
from pathlib import Path
import numpy as np

ROOT = Path(__file__).parent
DEFAULT_PATH = ROOT / "distillations" / "v5_D137.json"
T_MAX_YEARS = 50.0
T_MAX_DAYS = T_MAX_YEARS * 365.25
DT = 1.0  # 1 day step
N_SAMPLES = 500
RNG = np.random.default_rng(42)


def sample_uniform(rng, lo_hi):
    return rng.uniform(lo_hi[0], lo_hi[1])


def build_hazard_curve(baseline, peak_day, peak_value, plateau, decline_hl,
                       T_max_days=T_MAX_DAYS, dt=DT):
    peak_val = peak_value
    plateau_dur = plateau
    decline_half_life = decline_hl
    """Construct hazard(t) curve.
    Phase 1 (rise):    t in [0, peak_day),                log-linear from baseline -> peak_val
    Phase 2 (plateau): t in [peak_day, peak_day+plateau), stay at peak_val
    Phase 3 (decline): t > peak_day+plateau,              exponential decay back toward baseline
    """
    ts = np.arange(0, T_max_days + dt, dt)
    h = np.empty_like(ts)
    rise_end = peak_day
    plateau_end = peak_day + plateau_dur

    for i, t in enumerate(ts):
        if t < rise_end:
            frac = t / max(rise_end, 1e-9)
            h[i] = baseline * (peak_val / baseline) ** frac if baseline > 0 else peak_val * frac
        elif t < plateau_end:
            h[i] = peak_val
        else:
            decay_t = t - plateau_end
            decay = peak_val * (0.5 ** (decay_t / max(decline_half_life, 1e-9)))
            h[i] = max(baseline, decay)
    return ts, h


def rmst_lifespan_days(hazard_curve, ts, dt=DT):
    """E[min(T_death, T_max)] = ∫₀^T_max exp(-Λ(t)) dt"""
    Lambda = np.cumsum(hazard_curve) * dt
    survival = np.exp(-Lambda)
    return float(np.trapezoid(survival, ts))


def get_untreated_hazard_params(d):
    for a in d["axes"]:
        if a.get("category") == "derived_hazard":
            return {
                "axis_id": a["axis_id"],
                "baseline": a["baseline_range"],
                "peak_day": a["peak_day_range"],
                "peak_value": a["peak_value_range"],
                "plateau": a["plateau_duration_days"],
                "decline_hl": a["decline_half_life_days"],
            }
    raise ValueError("no derived_hazard axis")


def apply_treatment(untreated_sample, mod):
    """untreated_sample: dict of scalar params; mod: trajectory_modifications.mortality_hazard"""
    if mod is None:
        return untreated_sample
    sampled = dict(untreated_sample)
    if "peak_value_factor" in mod:
        f = sample_uniform(RNG, mod["peak_value_factor"])
        sampled["peak_value"] = sampled["peak_value"] * f
    if "plateau_duration_factor" in mod:
        f = sample_uniform(RNG, mod["plateau_duration_factor"])
        sampled["plateau"] = sampled["plateau"] * f
    if "decline_half_life_days" in mod:
        # treatment overrides decline half-life
        sampled["decline_hl"] = sample_uniform(RNG, mod["decline_half_life_days"])
    return sampled


def simulate_one_treatment(haz_axis_id, hazard_params, treatment, n_samples=N_SAMPLES):
    """Returns (mean_lifespan_days, p25_days, p75_days, has_mod)"""
    mod = None
    if treatment is not None:
        mods = treatment.get("trajectory_modifications") or {}
        mod = mods.get(haz_axis_id)
    has_mod = mod is not None

    lifespans = []
    for _ in range(n_samples):
        sample = {
            "baseline": sample_uniform(RNG, hazard_params["baseline"]),
            "peak_day": sample_uniform(RNG, hazard_params["peak_day"]),
            "peak_value": sample_uniform(RNG, hazard_params["peak_value"]),
            "plateau": sample_uniform(RNG, hazard_params["plateau"]),
            "decline_hl": sample_uniform(RNG, hazard_params["decline_hl"]),
        }
        sample = apply_treatment(sample, mod)
        ts, h = build_hazard_curve(**{k: sample[k] for k in
                                      ["baseline", "peak_day", "peak_value",
                                       "plateau", "decline_hl"]})
        lifespans.append(rmst_lifespan_days(h, ts))
    arr = np.array(lifespans)
    return arr.mean(), np.percentile(arr, 25), np.percentile(arr, 75), has_mod


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    if not path.is_absolute():
        path = ROOT / path
    d = json.loads(path.read_text(encoding="utf-8"))
    haz = get_untreated_hazard_params(d)
    haz_axis_id = haz["axis_id"]
    print(f"disease    : {d.get('disease','?')}  (file: {path.name})")
    print(f"hazard axis: {haz_axis_id}")
    print(f"untreated:   baseline={haz['baseline']}  peak_day={haz['peak_day']}  "
          f"peak_value={haz['peak_value']}  plateau={haz['plateau']}  "
          f"decline_hl={haz['decline_hl']}")
    print(f"T_max = {T_MAX_YEARS} years (RMST horizon), N samples = {N_SAMPLES}")
    print()

    results = []
    # untreated baseline
    m, p25, p75, _ = simulate_one_treatment(haz_axis_id, haz, None)
    results.append(("(no treatment / baseline)", m, p25, p75, False))
    # each treatment
    for t in d["treatments"]:
        m, p25, p75, has_mod = simulate_one_treatment(haz_axis_id, haz, t)
        results.append((t["drug"], m, p25, p75, has_mod))

    # rank by mean lifespan desc
    results.sort(key=lambda x: -x[1])

    print("=" * 96)
    print(f"  rank | mean lifespan (yr) | p25-p75 (yr)     | has_hazard_mod | drug")
    print("-" * 96)
    for i, (drug, m, p25, p75, has) in enumerate(results, 1):
        marker = "[YES]" if has else "[no] "
        print(f"  {i:4d} | {m/365.25:>8.2f}           | {p25/365.25:>5.2f} - {p75/365.25:<5.2f}    | {marker:14s} | {drug}")
    print("=" * 96)
    print()
    print("解读:")
    print("  - 标 [YES] = LLM 显式蒸了 mortality_hazard 修饰")
    print("  - 标 [no]  = 没蒸 mortality_hazard 修饰 (LLM 漏标), 等价于无治疗 baseline")
    print("  - emergent first-line = ranking 第 1 的治疗 (期望: methylpred pulse / anakinra)")


if __name__ == "__main__":
    main()
