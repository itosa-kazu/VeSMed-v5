"""
Patch v0 distillations: 补 mortality_hazard 修饰漏标 + 修 sepsis hazard axis 命名错误.

By Claude Opus 4.7 — 用临床知识填. 区间宽 (knowledge_confidence: low/medium 反映).
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
DISTILL = ROOT / "distillations"


# ---------- D137 (AOSD non-MAS) ----------
# 11 个治疗缺 mortality_hazard_in_D137. acetaminophen 是 push_state + 纯对症, 跳过 (按 rule 7 exception).
D137_HAZARD_PATCHES = {
    "ibuprofen_or_naproxen_antiinflammatory_dose": {
        # NSAID: 主要对症, 但抑炎对 disease course 有 mild effect
        "peak_value_factor": [0.7, 0.95],
        "plateau_duration_factor": [0.7, 1.0],
        "decline_half_life_days": [40, 90],
    },
    "methotrexate_10_to_25mg_weekly": {
        # AOSD 经典 steroid-sparing DMARD, onset 慢但 disease-modifying
        "peak_value_factor": [0.3, 0.7],
        "plateau_duration_factor": [0.3, 0.7],
        "decline_half_life_days": [10, 40],
    },
    "canakinumab_150_to_300mg_every_4_to_8_weeks": {
        # 长效 anti-IL1, 跟 anakinra 同类
        "peak_value_factor": [0.1, 0.6],
        "plateau_duration_factor": [0.1, 0.6],
        "decline_half_life_days": [1, 10],
    },
    "tocilizumab_8mgkg_every_4_weeks_or_162mg_weekly": {
        # anti-IL6, refractory AOSD 重要
        "peak_value_factor": [0.15, 0.6],
        "plateau_duration_factor": [0.15, 0.55],
        "decline_half_life_days": [1, 8],
    },
    "sarilumab_200mg_every_2_weeks": {
        # anti-IL6 (类似 TCZ)
        "peak_value_factor": [0.15, 0.65],
        "plateau_duration_factor": [0.15, 0.6],
        "decline_half_life_days": [2, 10],
    },
    "cyclosporine_2_to_5mgkg_per_day": {
        # T-cell 抑制, 偶用 in MAS-边缘 AOSD
        "peak_value_factor": [0.3, 0.75],
        "plateau_duration_factor": [0.3, 0.7],
        "decline_half_life_days": [5, 20],
    },
    "azathioprine_1_to_2mgkg_per_day": {
        # steroid-sparing immunosuppressant
        "peak_value_factor": [0.4, 0.85],
        "plateau_duration_factor": [0.4, 0.85],
        "decline_half_life_days": [10, 30],
    },
    "leflunomide_10_to_20mg_daily": {
        # DMARD, 中等 effect
        "peak_value_factor": [0.4, 0.85],
        "plateau_duration_factor": [0.4, 0.85],
        "decline_half_life_days": [10, 30],
    },
    "etanercept_or_adalimumab_tnf_inhibitor": {
        # TNFi: AOSD 效果 mediocre (不如 IL-1 / IL-6 阻断), 但比 untreated 好
        "peak_value_factor": [0.5, 0.9],
        "plateau_duration_factor": [0.5, 0.9],
        "decline_half_life_days": [10, 30],
    },
    "intravenous_immunoglobulin_2gkg_total_course": {
        # IVIG: refractory AOSD 偶用, mild benefit
        "peak_value_factor": [0.5, 0.95],
        "plateau_duration_factor": [0.5, 0.9],
        "decline_half_life_days": [5, 30],
    },
    # acetaminophen_antipyretic_dose: push_state + 纯对症 → 跳过
}


# ---------- D-SEPSIS-GN (gram-negative non-shock sepsis) ----------
# LLM 错把 sofa_score 当 derived_hazard. 修正:
#   - sofa_score → category 改回 lab_value (它就是临床 score, 不是 hazard rate)
#   - 新加 mortality_hazard_in_D-SEPSIS-GN (events_per_day, log_scale)
#   - 给 13 个治疗加 mortality_hazard 修饰 (acetaminophen 跳过)

D_SEPSIS_NEW_HAZARD_AXIS = {
    "axis_id": "mortality_hazard_in_D-SEPSIS-GN",
    "category": "derived_hazard",
    "unit": "events_per_day",
    "log_scale": True,
    "shape_free_text": (
        "For gram-negative non-shock community-acquired sepsis with timely empirical antibiotic, "
        "daily mortality hazard rises in first 1-3 days as bacteremia/cytokines peak, then declines "
        "as cultures clear and SOFA improves. Untreated/late-antibiotic curve is much steeper and "
        "stays elevated longer; with appropriate empirical coverage and source control, hazard "
        "decays over 5-21 days. Hazard reflects the integrated risk of cardiovascular collapse, "
        "AKI, ARDS, DIC, embolic events, secondary infection."
    ),
    "baseline_range": [1e-5, 5e-5],
    "peak_day_range": [1, 4],
    "peak_value_range": [3e-4, 5e-3],   # ~0.03%-0.5% per day at peak (non-shock subset)
    "plateau_duration_days": [2, 7],
    "decline_half_life_days": [5, 21],
    "second_peak": (
        "Possible during organ-complication phase (AKI, ARDS, secondary nosocomial infection, "
        "C. difficile after broad-spectrum antibiotic, recurrent bacteremia)."
    ),
    "knowledge_confidence": "medium",
    "additional_notes": (
        "Hazard rate (events/day, log scale) — NOT the SOFA score (that is a separate axis). "
        "Filled by Opus 4.7 to satisfy V5 schema requiring real hazard rate; LLM distillation "
        "had mistakenly labeled sofa_score as derived_hazard."
    ),
}

D_SEPSIS_HAZARD_PATCHES = {
    "early_active_intravenous_beta_lactam_antibiotic": {
        # 第一剂适当抗生素 within 1 hour: 决定性. Surviving Sepsis Campaign 核心.
        "peak_value_factor": [0.05, 0.3],
        "plateau_duration_factor": [0.05, 0.25],
        "decline_half_life_days": [1, 5],
    },
    "ceftriaxone": {
        # 标准 community-acquired emp coverage. 大多数 GN 敏感.
        "peak_value_factor": [0.08, 0.35],
        "plateau_duration_factor": [0.08, 0.3],
        "decline_half_life_days": [1, 5],
    },
    "piperacillin_tazobactam": {
        # 广谱, 重症/院内 风险时优先
        "peak_value_factor": [0.05, 0.3],
        "plateau_duration_factor": [0.05, 0.25],
        "decline_half_life_days": [1, 5],
    },
    "cefepime": {
        # 抗 Pseudomonas / 重症 ICU
        "peak_value_factor": [0.05, 0.3],
        "plateau_duration_factor": [0.05, 0.25],
        "decline_half_life_days": [1, 5],
    },
    "meropenem_or_ertapenem": {
        # 多耐药 / ESBL 风险时
        "peak_value_factor": [0.05, 0.3],
        "plateau_duration_factor": [0.05, 0.25],
        "decline_half_life_days": [1, 5],
    },
    "aminoglycoside_single_dose_adjunct": {
        # 与 β-lactam 联用对 GN 早期协同, 单独效果有限
        "peak_value_factor": [0.6, 0.95],
        "plateau_duration_factor": [0.6, 0.9],
        "decline_half_life_days": [3, 14],
    },
    "source_control_procedure": {
        # 引流/手术清除感染源: 决定性 (UTI obstruction, 胆管炎, 脓肿)
        "peak_value_factor": [0.1, 0.5],
        "plateau_duration_factor": [0.1, 0.4],
        "decline_half_life_days": [1, 5],
    },
    "intravenous_crystalloid_fluid": {
        # push_state: 30 mL/kg 早期复苏 → SBP/MAP push, 间接 hazard ↓
        "peak_value_factor": [0.5, 0.85],
        "plateau_duration_factor": [0.5, 0.85],
        "decline_half_life_days": [5, 20],
    },
    # acetaminophen: 纯对症 → 跳过
    "supplemental_oxygen": {
        # push_state: 低氧 → SpO2 push, 改善 hazard (尤其在 ARDS 边缘)
        "peak_value_factor": [0.5, 0.9],
        "plateau_duration_factor": [0.5, 0.9],
        "decline_half_life_days": [3, 14],
    },
    "insulin_protocol_for_stress_hyperglycemia": {
        # van den Berghe 等 — 适度血糖控制 modest mortality benefit
        "peak_value_factor": [0.7, 0.95],
        "plateau_duration_factor": [0.7, 0.95],
        "decline_half_life_days": [5, 30],
    },
    "renal_dose_adjustment_and_nephrotoxin_avoidance": {
        # modulate_theta: 防医源 AKI → 间接 hazard ↓ modest
        "peak_value_factor": [0.7, 0.95],
        "plateau_duration_factor": [0.7, 0.9],
        "decline_half_life_days": [10, 30],
    },
    "antibiotic_deescalation_and_oral_stepdown": {
        # 减少 C.diff / 二重感染, 改善后期 hazard 而非 peak
        "peak_value_factor": [0.85, 1.0],   # 不影响 peak (peak 是早期, deescalation 是后期)
        "plateau_duration_factor": [0.6, 0.9],
        "decline_half_life_days": [3, 10],
    },
}


def patch_d137():
    p = DISTILL / "v5_D137.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    haz_id = "mortality_hazard_in_D137"
    n_patched = 0
    for t in d["treatments"]:
        drug = t["drug"]
        if drug not in D137_HAZARD_PATCHES:
            continue
        mods = t.setdefault("trajectory_modifications", {}) or {}
        if haz_id in mods:
            continue
        mods[haz_id] = D137_HAZARD_PATCHES[drug]
        t["trajectory_modifications"] = mods
        n_patched += 1
        print(f"  D137 patched: {drug}")
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  D137 total patched: {n_patched}")


def patch_sepsis():
    p = DISTILL / "v5_D-SEPSIS-GN.json"
    d = json.loads(p.read_text(encoding="utf-8"))

    # 1. 修 sofa_score: derived_hazard -> lab_value (它是 score, 不是 hazard rate)
    for a in d["axes"]:
        if a.get("axis_id") == "sofa_score":
            a["category"] = "lab_value"
            print(f"  sepsis: sofa_score category fixed: derived_hazard -> lab_value")
            break

    # 2. 检查 mortality_hazard_in_D-SEPSIS-GN 是否已存在 (idempotent)
    haz_id = "mortality_hazard_in_D-SEPSIS-GN"
    has_real_hazard = any(a.get("axis_id") == haz_id for a in d["axes"])
    if not has_real_hazard:
        d["axes"].append(D_SEPSIS_NEW_HAZARD_AXIS)
        print(f"  sepsis: added new axis {haz_id}")

    # 3. 给治疗加 mortality_hazard 修饰
    n_patched = 0
    for t in d["treatments"]:
        drug = t["drug"]
        if drug not in D_SEPSIS_HAZARD_PATCHES:
            continue
        mods = t.setdefault("trajectory_modifications", {}) or {}
        if haz_id in mods:
            continue
        mods[haz_id] = D_SEPSIS_HAZARD_PATCHES[drug]
        t["trajectory_modifications"] = mods
        n_patched += 1
        print(f"  sepsis patched: {drug}")
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  sepsis total patched: {n_patched}")


if __name__ == "__main__":
    print("=" * 60)
    print("V5 hazard patch (Opus 4.7)")
    print("=" * 60)
    patch_d137()
    print()
    patch_sepsis()
    print()
    print("done. now restart server (or POST /save) to rebuild master_axes.")
