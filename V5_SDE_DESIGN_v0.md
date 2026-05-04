# V5 SDE 设计文档 v0

> **2026-04-30 lock 版**
>
> Author: itosa-kazu (project lead) + Claude (assistant) + Codex (adversarial reviewer)
> Status: 架构层 lock, 工程层路线图明确

---

## 0. 文档目的

把 V5 流体架构在 2026-04-30 lock 的所有架构判断 + Schema 设计 + 工程路线图集中到一份正式文档。

新 session 读这份文档:
- 不再讨论 V5 vs BN
- 不再讨论 SDE 是不是对
- 不再讨论 outcome 函数怎么定
- 直接进入 schema 工程实装阶段

Codex 评审任何架构层质疑都引这份文档应答。

---

## 1. 系统名 + 总体定位

**VeSMed-V5 (流体架构 / SDE 架构)**

继承 v3.x 的临床医学项目, 抛弃 BN 离散架构, 改用连续状态空间 SDE。

定位: 多疾病连续诊断 + 治疗反事实推理 + 合并症横向叠加 系统。

---

## 2. 5 大组件 ontology

(参 [project_v5_ontology.md])

V5 系统由 5 类对象构成。山坡 + 小球比喻贯穿:

```
状态空间 ℝⁿ        = 高低不平的山坡 (永久几何)
病人              = 山坡上滚的小球
病                = 山坡的低洼 (attractor 几何, 永久结构)
治疗              = 推球的手 (临时外力, do() 干预)
Risk factor       = 球的内在属性 (弹性/质量, 个体调制)
噪声              = 山坡上的风 (永远的随机晃动)
```

### 2.1 详细对照

| 组件 | 本体 | 数学形态 | 永久? | LLM 蒸 | 旧 BN 等价 |
|---|---|---|---|---|---|
| 状态轴 | 物理量 | x ∈ ℝⁿ | - | name + unit | 节点 V |
| 病 | 山坡几何 | drift `f(x, disease)` | ✅ | trajectory params | 边 + CPT |
| Risk factor | 球内在属性 | `θ_individual` 调制 f 或 σ | ✅ (个体特征) | per disease 一起 | R01 / R02 / Gain modulation |
| 治疗 | 外加力 | `+A(t)` | ❌ | per disease 一起 (4 模式) | (BN 时代 4 轮迭代终于到这里) |
| 噪声 | 系统随机性 | `σ(x,t) dW` | ✅ | baseline_range 隐含 | (BN 没显式) |

### 2.1.0 “球”的数学实体

比喻里的“球”在数学上拆成两层：

```
真实病人状态 X_t ∈ R^n：某一时刻是一个隐藏点
个体参数 θ_i：年龄、遗传、CKD、免疫抑制等底子
病程 {X_t}：SDE 下的一条随机路径
```

我们运行 particle filter / likelihood ranking 时看到的“一团云”不是病人本体，而是后验不确定性：

```
P(X_t, θ_i, M | observations)
```

其中 `M` 是候选 disease manifold / manifold set。工程上的 particles 是对这团 posterior cloud 的数值近似；真实病人对应其中一条未知路径。

### 2.1.1 Risk factor / Disease manifold scope

同一个临床 condition 必须先定 scope，避免 double count：

```
background risk factor = 改球本身 / 改 base measure
disease-specific risk factor = 改某个 disease 地形如何显影 / 如何恶化
disease manifold = 新增一块地形 f_condition
```

例：CKD 只是背景时，解释的是 “CKD 球” 的 creatinine/BUN/eGFR base measure；CKD 作为 sepsis-specific modifier 时，解释的是 sepsis 中 PCT 清除慢、AKI/hazard 更重；CKD 若已建成 `f_CKD`，则作为合并症地形叠加，不再同时用 CKD background modifier 抬高同一组肾功能 axes。

推理规则：

```
如果 disease 含某 axis:
    用 disease trajectory + disease-specific risk modulation

如果 disease 不含某 axis:
    用 risk-factor-adjusted base measure

如果 condition 已作为 disease manifold 进入 candidate:
    用 f_condition
    不再用该 condition 的 background modifier 解释同一组 axes
```

### 2.1.2 Emergence-first 原则

V5 默认原则：能由动力学和反事实模拟涌现的，不手写标签；不能涌现时才加结构，并解释为什么不能涌现。

```
first-line treatment -> forward simulate + RMST argmax 涌现
诊断 ranking          -> likelihood / posterior 涌现
合并症                -> vector field 叠加涌现
死亡/预后             -> mortality_hazard + first-passage / jump 涌现
```

允许“补结构”的条件：

1. 信息是现有状态空间不可观测的外部上下文，例如药敏、影像所见、source control 是否完成。
2. 信息不能由当前 axes / couplings / risk modifiers / treatment vector field 自然推出。
3. 结构必须进入通用机制，而不是单病例 hardcode。
4. 每次补结构都要写清楚“为什么不能涌现”。

例：抗生素具体是否有效不能从发热、CRP、PCT 自然推出，因为需要药敏/耐药/感染源控制证据；所以补 `active_antibiotic_coverage_probability`、`ceftriaxone_susceptibility_probability`、`source_control_adequacy` 这类 state axes / treatment effect modifiers，而不是补“ceftriaxone 在某病例禁用”的规则。

### 2.2 病 vs 治疗 — 核心本体论区分 (user 2026-04-30 洞察)

| | 病 | 治疗 |
|---|---|---|
| 本体 | 几何 (geometry) | 力 (force) |
| 永久? | ✅ 一直在 | ❌ 推时才有 |
| 自然 vs 干预 | 自然 (Layer 1) | 人为 (Layer 2 / do()) |
| 数学 | drift `f` 自身的形状 | drift 上加一项 `+A(t)` |

字段格式可以相似 (都是 JSON), 但**描述对象本体不同**.

### 2.3 治疗的 4 种作用模式

| 模式 | 作用对象 | 比喻 | 数学 | 例子 |
|---|---|---|---|---|
| ① push | 球 (state x) | 推球 | `+A_push(t)` 加到 dx/dt | norepinephrine push MAP |
| ② reshape | 山坡几何 (drift f) | 把低洼填平/切走 | `f(x; A_reshape)` 改 drift 形状 | 抗生素杀菌, cortisol 抑制 AOSD attractor |
| ③ stir | 风 (噪声 σ) | 调风幅 | `σ(x; A_σ) dW` 改 σ | 镇静药减生理变异 |
| ④ reshape ball | 球内在 (θ_individual) | 改球弹性 | `θ_individual ← g(A_history)` | 化疗骨髓抑制改长期 baseline |

---

## 3. 3 层 taxonomy (架构 / Schema / 实装)

### Layer 1: 架构 (锁定不动)

```
状态空间    = ℝⁿ (实数向量)
演化        = SDE: dx = f(x,t)dt + σ(x,t)dW + A(t)dt
治疗        = vector field push: + A(t) (改 drift)
合并症      = 多 vector field 线性叠加: f_AOSD + f_HTN + f_CKD
诊断        = particle filter 倒推 P(t, manifold | case)
预后        = forward simulate
反事实      = 改 A(t) 重跑 (path-wise counterfactual)
流形        = SDE 的 reference measure (attractor 区域)
健康/死亡   = 边界条件涌现, 不蒸
```

**这套数学不再变**。

### Layer 2: Schema (调整可)

LLM 蒸馏格式, 详 §6.

### Layer 3: 实装 (engineering)

- v2 (2026-04-30 完成): marginal Gaussian over t. 5/5 PASS (3 case × 3 流形)
- v3 (per-axis 独立 OU): **跳过** (跟 v2 ranking 数字一致, 仅 demo, 没 substantive 升级)
- v4: 真 SDE (axis 联动 + 横向合并症叠加 + 治疗 vector field)
- v0.1 升级 (5 件): hierarchical / smoothing / 离散化 / selection / identifiability

---

## 4. 蒸馏方针

### 4.1 蒸馏 = 疾病轨迹 only (健康/死亡 涌现)

(参 [project_v5_distill_disease_only.md])

| 概念 | 蒸馏? | 来源 |
|---|---|---|
| 疾病轨迹 | ✅ LLM 蒸馏 | 局部 trajectory |
| 健康 | ❌ 不蒸馏 | 各 disease 流形 baseline_range 涌现交集 |
| 死亡 | ❌ 不蒸馏 | hazard rate 高的状态自然涌现 (软"死亡区域") |

### 4.2 蒸细组合粗 (信息论必然)

- 子集 → 父集 = 加权混合, 零损耗
- 反向不可: 父集 → 子集 = 边际化失 mode + axis 相关性

工程上: 蒸至「LLM 教科书章节颗粒度 ∩ 临床可区分颗粒度」的最细 leaf.

### 4.3 Convergent endpoint 蒸一个

HLH/cytokine storm 等多病终末收束态 = trigger-agnostic, 蒸一个父集就够。Trigger 信息从前驱轨迹推断, 不从 endpoint 状态推。

### 4.4 蒸馏粒度

| Spectrum | Leaf 数 |
|---|---|
| AOSD spectrum | 3 (classic systemic non-MAS / chronic articular / MAS-progression) |
| Sepsis spectrum | 3 (gram-neg non-shock / gram-pos non-shock / septic shock) |
| HLH spectrum | 1 (trigger-agnostic, convergent endpoint) |
| TMA spectrum | 4 (acquired TTP / congenital TTP / aHUS / STEC-HUS) |
| 平均 | 3-4 leaves / umbrella |

---

## 5. Per-disease 全栈蒸馏 (每病 4 层)

(参 [project_v5_per_disease_full_stack.md])

### 5.1 核心方案

每个 disease leaf 蒸一次 LLM call, 输出 4 层全栈:

1. **病 axes** (含 mortality_hazard axis, 跟 trajectory 同级)
2. **病 trajectory params** (peak/plateau/decline 等)
3. **该病所有治疗** (Type 1/2/3/4 全列)
4. **该病 risk factor** (年龄/性别/基因/合并症 modulation)

唯一例外: **DDI matrix per-pair** (跨病独立化学相互作用).

### 5.2 为什么 per-disease 全栈 (vs per-drug + per-RF)

**临床真相: 治疗 + risk factor 都 context-dependent**.

例: norepinephrine 跨病:

| | Sepsis | 心衰 | AOSD |
|---|---|---|---|
| 主要病理 | Vasoplegia | 心肌泵衰 | 罕用 |
| Target MAP | 65 | 65-70 | n/a |

数学上 push MAP 都一样, 但**临床细节因病而异**. 蒸 universal schema 抹平真相.

### 5.3 工程量

| 蒸馏类型 | per-disease 全栈 |
|---|---|
| Disease (含治疗 + RF + mortality_hazard) | ~1500 |
| DDI per-pair | ~100 |
| **总 LLM call** | **~1600** |

### 5.4 自动绕开治疗汚染問題

不假装"untreated", 直接表达 trajectory + treatment effect delta. LLM 不用 pretend.

---

## 6. Schema 设计

### 6.1 完整 schema (per-disease 全栈)

参考 `v5_layer3_prompt_ui.html` 的 TEMPLATE。骨架:

```json
{
  "disease": "<DISEASE_ID>",
  "axes": [
    /* regular trajectory axes (ferritin, PLT, ...) */
    /* + mortality_hazard axis (category: "derived_hazard", 必含) */
  ],
  "treatments": [
    /* Type 1/2/3/4 全列, 含 trajectory_modifications / push_targets / sigma_modulation / theta_changes */
  ],
  "risk_factors": [
    /* age / sex / genetic / comorbidity 各自 modulation */
  ],
  "supportive_care": [...]
}
```

### 6.2 Mortality_hazard axis 必含 (V5 outcome 必需)

每病 axes 数组里必含一个 category: `"derived_hazard"` 的 axis:

```json
{
  "axis_id": "mortality_hazard_in_AOSD",
  "category": "derived_hazard",
  "unit": "events_per_day",
  "log_scale": true,
  "baseline_range": [0.0001, 0.001],          // 早期 ≈ 0
  "peak_value_range": [0.001, 0.05],          // 峰值死亡率
  "peak_day_range": [...],
  "knowledge_confidence": "high"
}
```

跟 trajectory 同级, **是 disease 的 fundamental description**, 不是为 outcome 设计的.

### 6.3 Treatments 4 模式

| Mode | 字段 |
|---|---|
| `push_state` | `push_targets` (target axis + direction + magnitude) |
| `reshape_landscape` | `trajectory_modifications` (per axis factor) |
| `modulate_sigma` | `sigma_modulation` (axes + factor) |
| `modulate_theta` | `theta_changes` (covariate + direction + duration) |

每个治疗都有 `side_effects` (per axis push), `onset_delay_days`, `carryover_after_stop_days`, `context_specific_role`.

### 6.4 Risk factors

```json
{
  "factor": "age",
  "type": "continuous",
  "modulation": {
    "young_adult_15_25": { "P_disease_ratio": [1.5, 2.5], "trajectory_modulation": null },
    "elderly_>60":       { "P_disease_ratio": [0.3, 0.5], "trajectory_modulation": "blunted_inflammation" }
  }
}
```

跟旧 BN R01/R02 prior + Gain modulation 同型.

Risk factor 分两类责任范围：

- Global/background modifier：只回答“这个人就算没有当前 disease，axis 的 base measure 如何变化”。用于 missing-axis / base-measure fallback。
- Disease-specific modifier：只回答“这个人得了该 disease 后，该 disease 的表现、联动、hazard、治疗效果如何变化”。用于 disease schema 已含该 axis 的情况。

不能把同一个 condition 对同一个 axis 的 background modifier 和 disease-specific modifier 同时叠加。MaxEnt 规则是：没有 disease-specific 约束时才回到 adjusted base measure。

### 6.5 Schema 设计原则

**Axis 联动 (v4 加)**:
- 软相关 (相关系数 -1 to +1), 不是硬 cluster
- 临床联动统计性 (HLH 三联 95% 同步, 5% 早期异步)

**定性观察 (腹痛/皮疹/关节痛)**:
- 投射成数值 axis (NRS / binary / count)
- 跟 lab 数值 axis 平等处理, 保持 ℝⁿ 状态空间统一

---

## 7. Axis ontology registry

(参 [project_v5_axis_ontology_registry.md])

### 7.1 问题

跨 session 蒸不同病, LLM 自由命名 → "rash" / "skin_eruption" / "cutaneous_lesions" 跨病错位.

### 7.2 解法: master_axes.json 渐进式 registry

`vesmed_v5_poc/master_axes.json`:

```json
{
  "axes": [
    {
      "axis_id": "skin_eruption",
      "preferred_name_en": "skin_eruption",
      "synonyms": ["rash", "cutaneous_lesions"],
      "category": "physical_finding",
      "unit_canonical": "severity_0_10",
      "log_scale": false,
      "first_distilled_in": "AOSD",
      "used_in_diseases": ["AOSD", "SLE", "Kawasaki", "DRESS"]
    }
  ]
}
```

### 7.3 蒸馏 workflow

```
Phase 0 (one-time): 初始化 master_axes.json (从已蒸 AOSD + HLH 抽取)
   ↓
Phase 1 (每次蒸新病): 
  - prompt 要求 axis_id snake_case
  - LLM 输出 axis_id (用同一概念在所有病)
  - 后处理 update master_axes.json
   ↓
Phase 2 (定期): Codex review master_axes.json (合并近义 / 单位标准化)
```

### 7.4 Phase 0 现状

需新建 master_axes.json + 从 AOSD (39 axes) + HLH (82 axes) 抽取 axis_id, 标 synonyms / unit / log_scale。预估 60-100 axes 起步。

---

## 8. Outcome 函数 LOCK = Lifespan-only RMST

(参 [project_v5_emergent_first_line.md])

### 8.1 核心原则: 只蒸数字, first-line emerge

LLM 只蒸数字 (trajectory params + hazard ratios), **不蒸 first_line / preferred 等临床判断标签**.

First-line 是 emergent property: forward simulate + outcome argmax.

跟临床共识对齐 = 架构对错的实证检验 (validation 标准).

### 8.2 Outcome 公式 LOCK

```
outcome(treatment) = E[lifespan] = RMST = E[min(T_death, T_max)]

T_death = SDE first-passage time:
          状态 x 时, hazard rate h(x) = combine(各流形 mortality_hazard_axis(x))
          T_death 是 hazard rate 决定的 first jump time
          ← 不画硬阈值, hazard 高的状态 = 软"死亡区域"涌现
```

### 8.3 Hazard rate 是 disease 内在描述

不是 V5 为 outcome 设计的人工概念, 是病的 fundamental property:
- 跟 ferritin trajectory 同级
- "AOSD 1 年死亡率 5%" 是 disease 内在数字
- 寿命跟 hazard 数学等价 (互为定义, 不是副产物)

类比物理: 加速度 (fundamental) vs 位置 (积分得到).

### 8.4 Codex 7 处隐藏选择 — lifespan-only 框架下

| # | 选择 | 状态 |
|---|---|---|
| 1 距离 metric | ✅ 完全解决 (用 hazard) |
| 2 坐标归一化 | ✅ 完全解决 (hazard 同 unit) |
| 3 健康集合 | ⚠️ 部分简化 (hazard ≈ 1 区间) |
| 4 死亡域 | ⚠️ 部分简化 (hazard rate, 不画硬阈值) |
| 5 T_horizon | ❌ → 转为 T_max 数值 (~100 年) |
| 6 distribution vs point | ❌ 不需要 (lifespan-only 不积分多维) |
| 7 ensemble 聚合 | ❌ 不需要 (E[T_death] 直接) |

**lifespan-only 框架下, Codex 7 处剩 2 处 explicit**:
- 多流形 hazard 合并方式 (max / sum / weighted)
- T_max 数值

### 8.5 Trade-off

- ❌ 失 QOL 维度 (痛苦 / 残疾 / 副作用)
- 例: 100 年植物人 vs 90 年健康人, lifespan-only 选前者 (反直觉)
- PoC 阶段接受 (lifespan dominates 大多数决策)
- 未来可加 QOL 第二维 (lexicographic / Pareto)

### 8.6 跟成熟数学同型

- First-passage time (Kolmogorov, Feller 1950s)
- Survival analysis with state-dependent hazard (Cox 1972 + state-space extension)
- RMST (Royston & Parmar 2011, 临床流行病学标准)
- Jump diffusion SDE (death as absorbing jump)

V5 outcome = 这些成熟工具在 SDE 上的实例化, 不是独创.

---

## 9. 合并症处理

### 9.1 纵向合并症 (先 X 后 Y) ✅ V5 已能解

机制: day-track ranking, 每 t 找最 fit 流形, 时间序列展示流形迁移.

例: AOSD non-MAS → MAS (= cytokine storm)

### 9.2 横向合并症 (同时 X+Y+Z) → v4 必要

V5 解法 = vector field 线性叠加:

```
dx/dt = f_AOSD(x) + f_HTN(x) + f_CKD(x) + A(t) + σdW
```

- 不蒸联合流形 (笛卡尔积爆炸)
- 力是线性叠加 → 不需要枚举组合
- 必要前提: axis 联动 schema (v4 升级目标)
- 与 risk factor 不冲突：risk factor 是球属性 / modifier；合并症是新增地形。一个 condition 如果已经作为 `f_condition` 叠加，就不要再把它的 background modifier 叠到同一组 axes 上。

### 9.3 纵向并发症触发

纵向并发症不是普通 risk factor，而是“滚着滚着进入新地形”：

```
AOSD axes 显示 MAS/HLH transition risk 升高
=> 按概率/门槛触发
=> candidate 从 f_AOSD 变为 f_AOSD + f_HLH
```

早期实现可先用 transition_risk / hazard axis 表示；完整实现应在触发后叠加新的 disease manifold。

---

## 10. v0.1 架构升级 (5 件) — Layer 3 directionally correct

(参 [project_v5_architecture_v0_locked.md], Codex 审查后修正)

### 10.1 Codex 揭出的 5 漏洞

1. Marginal noise ≠ individual U (最大)
2. PF filtering ≠ abduction
3. dW conditioning ill-posed
4. Selection bias
5. Identifiability

### 10.2 v0.1 5 件升级

| # | 升级 | 等价于 | 难度 |
|---|---|---|---|
| ① Hierarchical 两层 (group σ + individual θ_i) | 旧 BN R01/R02 prior + Gain modulation 移植 | substantive |
| ② Smoothing inference (forward-backward) | 算法升级 | 工程 |
| ③ Euler 离散化 (dW → ε_k) | 软升级 | 微小 |
| ④ Selection model | PoC 阶段 memory 写明, 后实装 | 元层 |
| ⑤ Identifiability assumptions explicit | 假设清单 memory | 元层 |

### 10.3 V5 距 Layer 3

```
v2 (现): Layer 1 + 部分 Layer 2 群体平均
v4 (axis 联动 + 治疗): Layer 2 完整 + Layer 3 path-wise 情景模拟
v0.1 (= v5): Layer 3 directionally correct
严格 Pearl Layer 3: 远期 (强数据 + 完整证明)
```

### 10.4 架构强于数据原则 (user 洞察)

> 架构对 + 弱数据 → 方向对, 误差有界
> 架构错 + 强数据 → 系统性错, 救不了

V5 v0.1 升级是架构升级, 数据 (LLM 蒸的 trajectory) 弱也能给方向对的答案.

---

## 11. 路线图

```
当前 (2026-04-30):
  ✅ V5 PoC v2 (3 流形, 5/5 PASS)
  ✅ 架构 lock (本文档)
  ✅ Outcome 函数 lock (lifespan-only RMST)

下一步 (短期, 1-2 周):
  □ #14 升级蒸馏 prompt (4 层全栈 + mortality_hazard 必含) ← 已完成
  □ Phase 0: 初始化 master_axes.json (从 AOSD + HLH 抽取)
  □ #6/#7: 蒸 sepsis (D-SEPSIS-GN) + TTP (D-TTP) 用新 prompt
  □ #8: 5-way ranking (AOSD/HLH/Sepsis/TTP/Healthy 涌现)

中期 (1-2 月):
  □ #12 v4 实装: axis 联动 + joint SDE + 横向合并症叠加 + 治疗 vector field
  □ 多病合并症验证: 找 PMC 合并症 case (如 AOSD + CKD)
  □ Forward simulate + first-passage time 实装 + RMST 计算

长期 (3-12 月):
  □ #13 v0.1 升级 (hierarchical / smoothing / 离散化 / selection / identifiability)
  □ Layer 3 path-wise counterfactual 验证
  □ 扩到全 430 疾病
  □ QOL 第二维 (lexicographic / Pareto, future extension)
```

---

## 12. 不变 / 可变 — 终态判断

### 12.1 不再讨论 (架构 lock)

- ❌ V5 vs BN
- ❌ SDE 是不是对的
- ❌ vector field 叠加是不是对的
- ❌ 蒸馏 = 疾病 only 是不是对的
- ❌ Outcome 函数怎么定 (lifespan-only RMST 已 lock)
- ❌ 治疗本体跟病不同 (4 模式)
- ❌ 涌现 first-line 原则
- ❌ Per-disease 全栈蒸馏

### 12.2 仍在讨论 (Schema 调整 / 工程实装)

- Axis 联动 schema 具体形式 (相关系数 / cluster / free text)
- master_axes.json 初始化细节
- v0.1 5 件升级实装顺序
- QOL 第二维设计 (future)
- 多流形 hazard 合并方式 (max / sum / weighted, 1 个 explicit choice)

---

## 13. 参考 memory 索引

V5 架构层判断分散在多个 memory file, 设计文档 v0 是它们的整合:

- [project_v5_fluid_architecture_decision.md] — V5 路线起点 (2026-04-29)
- [project_v5_three_case_poc_success.md] — PoC 3/3 PASS
- [project_v5_curve_distillation_paradigm.md] — 曲线蒸馏范式
- [project_v5_distill_disease_only.md] — 蒸馏 = 疾病 only + 蒸细组合粗
- [project_v5_architecture_v0_locked.md] — 3 层 taxonomy + Codex 修正 + v0.1
- [project_v5_ontology.md] — 5 大组件 + 4 治疗模式
- [project_v5_per_disease_full_stack.md] — Per-disease 全栈蒸馏 (4 层)
- [project_v5_axis_ontology_registry.md] — master_axes.json 跨 session 一致性
- [project_v5_emergent_first_line.md] — Outcome 函数 LOCK = lifespan-only RMST

---

## 14. Codex 评审应答 cheatsheet

新 session 中 Codex / 学生质疑常见问题 + 标准应答:

| 质疑 | 应答 |
|---|---|
| 为什么 SDE 而不是 GMM | SDE 解合并症 (vector field 叠加), GMM 不能 |
| v3 是不是该写 | 跳过, ranking 跟 v2 一致, 直接 v4 解合并症 |
| HLH 为什么不分 trigger 子集 | Convergent endpoint, trigger 信息从前驱轨迹推断 |
| 治疗为什么不另起一套 | do() 干预 ≠ 状态对象, 本体不同, 但 schema 形式可以相似 |
| 为什么不单独蒸 healthy/death | 涌现, 不是流形 |
| Layer 3 反事实 v4 就能做吗 | ❌ v4 只到 path-wise simulation, 严格 Layer 3 = v0.1 升级 |
| SDE = continuous-time SCM 等价吗 | 部分对, 严格表达需要 Itô map; exogenous 不只是 dW |
| outcome 为什么不蒸 indication_strength | First-line 是 emergent property, 跟 cost emerges 同源 |
| 为什么 lifespan-only 不考虑 QOL | PoC 阶段简化, lifespan dominates 大多数决策, QOL 后期加 |
| Hazard rate 是不是为算寿命设计的 | 否, 是 disease fundamental description, 寿命数学等价 |
| 为什么不 per-drug 蒸馏 | 临床 context-dependent, universal schema 反而错 |
| 跨病字段不一致怎么办 | master_axes.json 渐进式 ontology registry |

---

## 15. 改动历史

- 2026-04-29: V5 流体架构决定 (废 BN, 用 SDE)
- 2026-04-30: 完整架构 lock + outcome 函数 lock + 设计文档 v0 写就

---

> **End of V5 SDE Design v0**
>
> 新 session 看完这份文档 + CLAUDE.md V5 主线 section, 应该能直接进入工程实装阶段, 不再回头讨论架构。
