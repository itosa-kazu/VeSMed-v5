# V5 Layer 3 LLM Distillation Prompt v0

> Legacy design note. The active prompt is generated from `v5_layer3_prompt_ui.html`,
> which now uses a mechanism-first schema plus disease-class modules
> (infection / immune-inflammatory / hematology-TMA / generic).
> Current active schema asks for `latent_mechanisms` and `mechanism_edges`
> before ordinary axes/couplings. Complication/event hazard axes and
> hazard_drift / event_transition couplings still support chains like
> platelet_count low -> major_bleeding_hazard -> intracranial_hemorrhage_hazard
> -> mortality_hazard can affect RMST through the V5 state space instead of
> hardcoded toxicity penalties. `axis_couplings` is now reserved for residual
> covariance and true event transitions, not hidden pathophysiologic engines.
> Active prompt also requires `treatment_modifier` axes for patient-specific
> usability/contraindication context: allergy or severe hypersensitivity,
> pregnancy, renal/hepatic limits, active infection/reactivation risk,
> bleeding/procedure risk, volume overload, and major drug-interaction context.
> These must be consumed through treatment `required_context_axes` and
> `effect_modifiers`, not left as free-text caveats. They are patient-context
> priors/observations, not disease-course axes, so the active prompt tells LLMs
> not to give them peak/plateau/decline trajectory parameters by default.

## Design Rationale

Layer 3 蒸馏的核心范式：LLM 的输出不是数据点（"day 7 ferritin = 8000"）、也不是频率统计（"AOSD 中 70% ferritin > 5000"）、也不是虚拟病人轨迹样本，而是**每个 lab/生理轴的解析曲线参数化形式**——每个参数都是区间 `[low, high]`，编码认知不确定性。这种形式同时充当 SDE 的 MaxEnt reference measure 和锚点约束：区间宽度直接反映 LLM 对该知识点的把握程度，不窄缩也不捏造精度。为什么要"完全自由"（axes 自由 + shape 自由）：预设 axes 会引入锚定偏差，强迫 LLM 填充它不擅长的轴；让 LLM 自己选择 AOSD 病程的关键轴，正是让 LLM 内部知识库直接决定 reference measure 的支撑域，避免设计者的先验假设密输入到数据来源层。同样，预定义 shape vocabulary（"急升缓降"/"双相"等）会限制 LLM 的表达能力；自由文本描述 shape 然后在后处理中解析，是更诚实的做法。

---

## Variant 1: Minimal

```
You are a clinical expert. Your task: describe the laboratory and physiologic course of
Adult-onset Still's disease (AOSD), classic systemic subtype, untreated, not progressing
to MAS, from day 0 to day 90.

Output format: YAML list. Each list item = one lab/physiologic axis you consider important
for characterizing the AOSD disease course. YOU decide which axes to include and how many.

For each axis, describe its course as analytic curve parameters. All numeric fields must be
intervals [low, high], not point values. The interval should reflect your genuine uncertainty —
widen it when you are unsure; do NOT narrow it to look precise.

For each axis, include at minimum:
- axis_name: (your choice)
- unit: (your choice)
- shape_description: free text describing the curve shape over days 0-90
- baseline_range: [low, high]  # typical value before disease onset
- peak_day_range: [low, high]  # day of peak (null if monotonic or no clear peak)
- peak_value_range: [low, high]  # value at peak
- knowledge_confidence: high / medium / low  # your assessment of the evidence basis
- notes: any caveats or important nuances (optional)

Do not enumerate shape types; describe the shape in plain language.
If you are uncertain whether a particular axis belongs, include it and set
knowledge_confidence: low rather than omitting it.
```

---

## Variant 2: Structured

```
You are a senior clinical expert with combined expertise in rheumatology, general internal
medicine, and quantitative physiology.

TASK
----
Describe the laboratory and physiologic disease course of:

  Disease: Adult-onset Still's disease (AOSD)
  Subtype: classic systemic, untreated, not progressing to MAS
  Time window: day 0 (symptom onset) through day 90

You will produce a YAML document. Each entry in the YAML represents one lab or physiologic
axis that you judge important for characterizing this disease course. YOU decide which axes
to include and how many — there is no required number. Choose axes that best represent the
temporal dynamics of this disease course based on your training knowledge.

OUTPUT FORMAT (YAML)
--------------------
Produce a YAML list. Each list item follows this schema:

- axis_name: string            # your chosen name, e.g. "serum_ferritin", "body_temperature"
  unit: string                 # physical unit, e.g. "ng/mL", "°C", "g/L"
  log_scale: true|false        # true if the axis is best interpreted on log scale
  shape_free_text: string      # free text describing the curve shape over days 0-90
                               # (do not use a fixed vocabulary; describe naturally)
  baseline_range: [low, high]      # value before symptom onset (typical healthy/pre-disease)
  peak_day_range: [low, high]      # day of peak relative to day 0; null if no clear peak
  peak_value_range: [low, high]    # value at peak; null if monotonic
  plateau_duration_days: [low, high]  # days the axis stays near peak; null if no plateau
  decline_half_life_days: [low, high] # approximate half-life of decline; null if no decline
  second_peak: string          # free text if a second peak occurs; null otherwise
  knowledge_confidence: high|medium|low  # your confidence in the numbers above
  additional_notes: string     # caveats, subtype variation, important nuances; null if none

Not all fields need to be filled. If a field does not apply to this axis, set it to null.

CALIBRATION RULES
-----------------
1. All numeric fields must be intervals [low, high], never point values.
2. Widen intervals when you are uncertain. Do not narrow them to appear precise.
3. If your knowledge of a particular axis is weak, include it anyway and set
   knowledge_confidence: low, then explain in additional_notes.
4. Estimates from textbooks or review articles in your training data are acceptable.
   You do not need exact PMID citations — rough impressions are fine.
5. Do not anchor on any particular number of axes. Add as many as you judge relevant.

OUTPUT
------
Produce only the YAML list. No preamble, no explanation, no trailing text.
```

---

## Trade-off

**Variant 1（Minimal）**：prompt 更短（约 120 词），对 LLM 几乎零锚定，连字段名也是 LLM 自由选择。好处是更能观察 LLM 自然浮现的知识结构；缺点是不同运行之间字段名可能不一致，程序解析需要额外的 normalization 步骤。

**Variant 2（Structured）**：prompt 更长（约 280 词），提供字段名 hint，输出的 YAML 结构在多次运行之间稳定，Python 直接解析。轻微锚定风险仅在字段语义层面（`peak_day_range` 等通用概念），axes 内容和 shape 描述仍完全自由。

**建议先试 Variant 2**：静态 PoC 阶段已经验证了 "自由选 axes + 结构化参数" 的模式可行（LLM 稳定选出了 9 个有临床意义的轴）；Variant 2 字段结构与后续 Python 解析/SDE 构造直接对接，省去 normalization 开销。Variant 1 留作对照实验：如果 Variant 2 的字段 hint 被怀疑引入偏差，再用 Variant 1 跑一遍比较 axes 覆盖率。

---

## Verification Pipeline（收到 LLM YAML 输出后）

1. **解析 YAML**：读取所有 axis 条目，提取 `axis_name`、`unit`、`log_scale`、各区间字段。

2. **构造 reference SDE**：
   - 每个 axis 的 `baseline_range` → 健康吸引子位置（MaxEnt 先验中心）
   - `peak_day_range` + `peak_value_range` + `decline_half_life_days` → 病程轨迹约束
   - 区间宽度 → 扩散系数 σ 的上下界
   - `shape_free_text` → 辅助判断 drift 函数 f(x, t) 的定性形态

3. **Forward simulate**：在构造好的 reference SDE 下，分别为 AOSD、Healthy、MAS 三个条件跑 particle filter，生成各条件下的边际密度 ρ(x | condition)。

4. **Likelihood ranking**：对静态 PoC 的 3 个真实案例（AOSD 案例、Healthy 案例、MAS 案例），分别计算在三个条件密度下的 log-likelihood，判断排名。

5. **PASS 标准**：
   - AOSD 案例在 AOSD 条件下 log-likelihood 最高
   - Healthy 案例在 Healthy 条件下最高
   - MAS 案例在 MAS 条件下最高
   - 3/3 PASS，与静态 PoC 结果对齐

**⚠️ Axis 映射问题（重要）**：LLM 自由选择的 axes 很可能与静态 PoC 使用的 9 个 axes（如 `log10_serum_ferritin`、`CRP`、`absolute_neutrophil_count` 等）不完全重合，甚至命名不同。在执行步骤 4 之前，需要：

- **方案 A（推荐）**：人工做 axis 映射表——将 LLM 选出的 axis 与静态 PoC 案例数据的变量做语义对齐（如 LLM 的 `"ferritin"` → PoC 的 `log10_serum_ferritin`），然后用映射后的 PoC 案例数据做 ranking。
- **方案 B**：如果 LLM 选出了静态 PoC 完全没有的 axis，需要为 3 个案例补充该 axis 的真实观测值，再做 ranking。

建议在动手写 Python 验证脚本前，先人工过一遍 LLM 输出的 axes 列表，确认映射方案。
