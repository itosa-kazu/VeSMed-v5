# VeSMed V5 PoC Agent Instructions

本文件是 Codex / 其他 agent 进入 `vesmed_v5_poc` 时的项目级说明。新 session 先读本文件，再按需读 `V5_SDE_DESIGN_v0.md`。

## 语言与产物

- 与用户交流用中文。
- 面向最终 UI / 病名 / 变量名的成品文字优先日文；工程内部说明可以中文。
- 医学 case 必须来自真实文献，优先 PMC / PubMed case report。不要用 synthetic case。

## 当前主线

**VeSMed-V5 是新主线。旧 BN / CPT / Noisy-OR 架构只作为 baseline，不再作为主架构继续推进。**

V5 架构已经 lock：

```text
状态空间    = R^n 实数向量
演化        = SDE: dx = f(x,t)dt + sigma(x,t)dW + A(t)dt
治疗        = vector field push / reshape: A(t) 作用到 drift / sigma / theta
合并症      = 多 vector field 线性叠加: f_AOSD + f_HTN + f_CKD
诊断        = particle filter / likelihood ranking 倒推 P(t, manifold | case)
预后        = forward simulate
反事实      = 改 A(t) 重跑
流形        = SDE reference measure / attractor 区域
健康/死亡   = 涌现，不单独蒸馏成 disease manifold
```

不要重新争论：

- V5 vs BN
- SDE 是否正确
- vector field 叠加是否正确
- 是否单独蒸 healthy / death
- outcome 函数怎么定
- treatment 是否应另起一套系统
- first-line 是否由 LLM 直接给标签

这些问题已在 `V5_SDE_DESIGN_v0.md` 和 `C:\Users\wangw\Desktop\VeSMed-v3\.claude-memory\project_v5_*.md` 中锁定。

## 5 大对象本体

```text
状态空间 R^n = 高低不平的山坡
病人        = 山坡上滚的小球
病          = 山坡低洼 / attractor / 永久几何
治疗        = 推球的手 / 临时外力 / do() 干预
Risk factor = 球的内在属性 / theta_i 个体调制
噪声        = 山坡上的风 / sigma dW
```

“球”的数学实体：

```text
真实病人状态      = 隐变量 X_t ∈ R^n，在某个时刻是一个点
个体属性/底子     = θ_i，例如 CKD、免疫抑制、年龄、遗传
病程              = 随机路径 {X_t}_{t≥0}
我们对病人的不确定性 = posterior distribution / particle cloud: P(X_t, θ_i, M | observations)
```

所以“球”本体不是云；真实病人是一条隐藏路径。云是我们在诊断/预测时对这条路径和个体参数的不确定性近似。

病与治疗的本体不同：

- 病是永久几何：`f(x, disease)`
- 治疗是临时力：`+A(t)` 或对 `f / sigma / theta` 的干预
- background risk factor 是“球本身”的属性，例如 CKD 让 creatinine/BUN 的 base measure 本来就偏高。
- disease-specific risk factor 是“球掉进某个病地形后，这个地形如何变形/如何显影”，例如 CKD + sepsis 让 PCT 清除慢、AKI/hazard 更重。
- 合并症是“多加一个地形”：`f_A + f_B`；纵向并发症是病程中触发/进入新的地形。

防重算规则：

```text
如果 condition 只是 risk factor:
    用 background modifier 或 disease-specific modifier

如果 condition 已建成 disease manifold:
    用 f_condition 叠加
    不再用它的 background modifier 解释同一组 axes
```

同一个临床事实不能既作为“球属性”又作为“完整地形”对同一 axis 叠两次。CKD 如果只是背景，用 CKD background modifier；如果已经有 `f_CKD`，就让 `f_CKD` 解释 creatinine/BUN/eGFR 等 CKD 轴。

## Emergence-First 原则

默认原则：**能从 SDE / likelihood / forward simulation / RMST argmax 涌现的，不手写标签；实在不能涌现的才加结构。**

禁止为了短期结果直接打语义补丁，例如：

- 不加 `first_line: true`
- 不加 `diagnosis_should_be: sepsis`
- 不加硬编码“某药永远第一”
- 不靠删除 case evidence 让 ranking 通过

允许加结构的条件：

1. 该信息是 runtime 当前不可观测的外部上下文，例如药敏、CT 所见、source control 是否完成。
2. 该信息不是某个已有 axis / coupling / treatment effect 可以自然推出的。
3. 加结构前必须说明“为什么这块不能从现有状态涌现”。
4. 加结构后必须进入通用机制，例如 axis、coupling、risk modifier、treatment effect modifier、base measure modifier，而不是单病例 hardcode。

例：ceftriaxone 在 Ralstonia case 排太高，不应补丁成“Ralstonia 不用 ceftriaxone”。正确做法是加入 `ceftriaxone_susceptibility_probability` / `active_antibiotic_coverage_probability`，并让 antibiotic vector field 被这些 axes 调制。原因是药敏不是病人生命体征和常规 labs 能可靠涌现的隐藏上下文，需要由培养/药敏证据进入状态空间。

治疗 4 模式：

- `push_state`: 推 state x，例如升 MAP
- `reshape_landscape`: 改 disease drift / attractor，例如抗生素、糖皮质激素、生物制剂
- `modulate_sigma`: 改变生理噪声
- `modulate_theta`: 改个体参数，例如长期骨髓抑制、感染易感性

## 蒸馏原则

每个 disease leaf 一次 per-disease 全栈蒸馏，输出：

- `axes`: lab / vital / physical / qualitative axes，必须含一个 `category: "derived_hazard"` 的 mortality axis
- `trajectory params`: `baseline_range`, `peak_day_range`, `peak_value_range`, `plateau_duration_days`, `decline_half_life_days`
- `axis_couplings`: 临床上真正重要的 axis-axis 联动 / 反向关系 / 时间滞后，用于 joint SDE；不要强迫填写所有 axis pair
- `treatments`: 该病上下文里的所有标准治疗，按 4 模式表示
- `risk_factors`: 年龄、性别、遗传、合并症等对 prior / trajectory / hazard / treatment / axis response / coupling 的调制
- `supportive_care`

LLM 只蒸数字和结构，不蒸临床判断标签。不要加入 `first_line`, `preferred`, `guideline_recommended`, `indication_strength` 这类字段。first-line 由 forward simulate + outcome argmax 涌现。

### Disease Leaf Granularity

第一层 disease manifold 必须蒸到“临床流形稳定、医生能独立假设”的具体 disease leaf，不用过宽 umbrella 诊断。

原则：

- 如果 umbrella 内部的机制、典型器官轴、治疗毒性/适应证、mimic 关系明显不同，就必须拆 leaf。
- 例：`ANCA-associated vasculitis` 太宽，不能作为第一层 disease leaf；应拆为 `D-MPA`（Microscopic polyangiitis / 顕微鏡的多発血管炎）、`D-GPA`、`D-EGPA` 等独立 manifold。
- `disease_id` 也会被 LLM 当成医学输入，因此不能把 disease name 之外的病因、mimic、亚型或近邻病写进 ID。例：`Disease: Infectious mononucleosis` 不能配 `D-EBV-CMV-MONO-LIKE`，因为 `CMV` 会污染蒸馏；应使用 `D-INFECTIOUS-MONONUCLEOSIS`，CMV mononucleosis-like illness 未来单独蒸。
- `D-LYMPHOMA-FEVER` 过宽，只能作为 legacy umbrella 暂存；不能为了 ALCL case 被 `D-MIS-A` 吸走而调 case 或加语义补丁。正确下一步是拆成 subtype disease leaves，例如 `D-ALCL`、`D-HODGKIN-LYMPHOMA`、`D-DLBCL`、`D-IVLBCL`，并为每个 subtype 加 PMC real case。
- 第一层先诊断到具体 leaf；如果未来需要更细分亚型，再在已诊断 leaf 内做第二层 subtype distillation。

## Prompt 策略

当前 `v5_layer3_prompt_ui.html` 采用“纯病名 + 工程 schema”：

- 给 LLM 的 disease-specific 医学输入只能是 `Disease: <病名> (id: <ID>)`。病名是唯一医学约束。
- prompt 不再注入 disease-class module，不给感染病/免疫病/TMA 等医学抽取清单，不给 subtype、病因、严重度、固定时间窗或鉴别诊断提示。
- 通用主 schema 仍然是 mechanism-first：`latent_mechanisms` / `mechanism_edges` / `axes` / `axis_couplings` / `treatments` / `risk_factors` / `supportive_care`。
- 默认使用一次性 semantic JSON 蒸馏：LLM 输出完整临床语义，但不输出 boilerplate/null/空字段/泛泛解释；程序负责 normalize 和补结构。
- 同一个 LLM session 内的两段式蒸馏保留为 fallback，只有某个病仍然输出过长时使用：
  - Stage 1: `latent_mechanisms` / `mechanism_edges` / `axes` / `axis_couplings`
  - Stage 2: 基于 Stage 1 上下文输出 patch：`axes_add` / `mechanism_edges_add` / `axis_couplings_add` / `treatments` / `risk_factors` / `supportive_care`
  - UI 负责把 Stage 2 patch merge 回 Stage 1，再保存最终 `v5_<DISEASE_ID>.json`
- LLM 只负责从病名本身推断临床语义：哪些机制/axis/edge/treatment/risk factor 重要、方向、宽范围和上下文。程序负责 boilerplate、空数组、null/default、pretty print、patch merge、sigma/covariance/background fallback 和机制 gate scaling。
- 工程约束可以写进 prompt：合法 JSON、字段 schema、range 必须 `[low, high]`、axis 粒度、axis_id 命名、禁止 `first_line/preferred/indication_strength` 这类标签字段。
- `master_axes.json` 可以作为 **axis_id 命名 registry** 注入 prompt，用来跨 session 复用已有 axis_id；必须明确它不是医学 checklist，不能因为 registry 里有某 axis 就要求 LLM 输出该 axis。注入内容尽量只含 `axis_id/category/unit/log_scale`，不要带 disease provenance / seen_in 这类医学暗示。
- 工程约束不能变成医学内容约束：不能告诉 LLM 某类病必须考虑哪些机制、哪些 mimic、哪些治疗禁忌、哪些事件 hazard。否则 prompt 会污染 disease manifold。

### Disease-Name Scope（病名即天然分单位）

第一层 disease manifold 蒸馏的 prompt 中，`diseaseName` **必须只是病名本身**。病名就是天然分单位，也是唯一医学约束。

禁止在病名之外追加限定词；如果某个词本来就是本次要蒸的病名本体的一部分，可以保留，否则不要写进 prompt。

常见错误是把这些内容作为额外修饰语塞进去：
- 病因/分型：`Secondary` / `Primary` / `Familial` / `acquired/idiopathic` / `gram-negative` / `gram-positive`
- 来源：`community-acquired` / `nosocomial`
- 表现/严重度：`with fever` / `with shock` / `non-shock` / `severe` / `subacute` / `disseminated` / `miliary`
- 机制限定：`ADAMTS13 severely deficient` / `trigger-agnostic` / `inflammatory presentation`

**Why:**
带亚型限定的 prompt 会让 LLM 自动把限定外的合法表现排除掉。已发生的事故（2026-05-03）：`Secondary HLH/MAS` 让 HLH 蒸馏排除 primary/familial HLH；`Bacterial sepsis (gram-negative, community-acquired)` 让 SEPSIS 蒸馏排除 nosocomial septic shock + DIC + leukopenic 表现，结果 Ralstonia case 在 SEPSIS 上 d_dimer peak `[2,15]` 完全爆掉、被新版 HLH 压过去。

**正确做法：**
- 第一层蒸馏只描述"这片地形"全谱。
- 亚型分化交给 `risk_factors` 的 P_disease_ratio + axis_response_modulation + treatment_effect_modulation；treatment 适用性交给 `treatment_modifier` axes。
- 必要时再做第二层 subtype distillation，先诊断到本病再分型。
- UI preset 的 diseaseName 也要同步清理；如果未来要分 subtype，先诊断到本病，再做第二层 subtype distillation。

## Mechanism Edges, Axis Coupling 与 Risk Factor Modulation

`latent_mechanisms` / `mechanism_edges` / `axis_couplings` 在蒸馏同一个 disease 时一起蒸出来，不要事后猜。

规则：

- 先列病理机制，再列机制到 axis/event/outcome 的边；例如 `microthrombotic_activity -> platelet_count down`、`microthrombotic_activity -> serum_ldh up`。
- 只列临床上有意义的残余联动，例如 CRP 与 fever 同步、lactate 与 MAP 反向。
- 不要列全矩阵；没有临床意义或知识很弱的 axis pair 不要硬填。
- 如果 A 和 B 主要是被隐藏机制 C 共同推动，不要写 A -> B；写 C -> A 和 C -> B。
- 如果联动只在某个阶段或上下文成立，用 `conditionality` 写清楚。
- 如果某个 risk factor 会让疾病表现“变形”，必须写进 `risk_factors[*].modulation[*].axis_response_modulation` 或 `coupling_modulation`。
- 例：免疫抑制状态下，sepsis 本该发热、CRP/WBC 升高，但反应可能被压低；这不是“不像 sepsis”，而是 risk factor 把 fever / CRP / WBC response 和 CRP-temperature coupling 调弱。

### Complication / Event Hazards

V5 天然兼容并发症链条，但 prompt 必须让 LLM 把链条里的“坑”画进状态空间。不要写病例级硬规则，例如 `if platelet < 20 then death += X`。

正确结构：

```text
platelet_count low
  -> major_bleeding_hazard up
  -> intracranial_hemorrhage_hazard up
  -> mortality_hazard_in_D-TTP up
  -> RMST down
```

工程规则：

- 重大并发症/事件风险使用 `category: "event_hazard"` 的 axis，例如 `major_bleeding_hazard`、`intracranial_hemorrhage_hazard`、`acute_kidney_injury_hazard`、`ards_hazard`、`dic_hazard`、`mas_hlh_hazard`。
- `mortality_hazard_in_<DISEASE_ID>` 仍然是唯一 `category: "derived_hazard"` 的 lifespan outcome hazard。
- `axis_couplings` 支持 `coupling_type`: `noise_correlation` / `drift` / `hazard_drift` / `event_transition` / `mixed`。
- `noise_correlation` 只用于 joint covariance；`hazard_drift` / `event_transition` 才能让某个 axis 的系统性变化推高/降低 hazard target。
- 治疗副作用也应该通过 event hazard 进入 outcome：例如 caplacizumab 推高 `major_bleeding_hazard`，再由 bleeding/ICH hazard drift 推高 mortality hazard，而不是外贴 toxicity penalty。
- 常见事件 hazard axis 尽量跨病复用；只有机制或定义明显 disease-specific 时才 suffix disease id。

## Latent Mechanism DAG

最新原则：所有真正会推动病程的因果边，优先落到病理机制上。

```text
latent_mechanism (0..1 hidden activity)
  -> observed axes / event hazards / mortality hazard
```

工程规则：
- 新蒸馏必须先输出 `latent_mechanisms`，再输出 `mechanism_edges`。
- `latent_mechanisms` 是隐藏的 0-1 机制轴，例如 `microthrombotic_activity`、`immune_adamts13_inhibition_activity`、`bacterial_burden_activity`、`vasodilatory_shock_activity`、`cytokine_storm_activity`。
- `mechanism_edges` 只表达因果身份：`source_id`、`target_id`、`effect_on_target`、`edge_type`、`lag_days_range`、rationale、confidence。
- 不要让 LLM 手填医学齿轮参数；具体幅度由 source mechanism activity 和 target axis 的 background/disease range 自动接上。
- 如果 A 和 B 只是因为隐藏机制 C 同时升高/降低，不要写 A -> B 或 B -> A；写 C -> A 和 C -> B。
- `axis_couplings` 以后只保留两类：残余 covariance / noise correlation，和真实事件链如 bleeding -> ICH -> mortality。
- 治疗优先修改机制轴；例如 TPE 降低 `immune_adamts13_inhibition_activity`，抗生素降低 `bacterial_burden_activity`，IL-1 blockade 降低 `cytokine_storm_activity`。

Runtime 状态：
- `v5_joint_sde_case_test.py` 会把 `latent_mechanisms` 读成 `category: "latent_mechanism"` 的隐藏 axis。
- `mechanism_edges` 在诊断和治疗 runtime 里作为机制 gate 使用：机制强度越高，下游 axis 越接近疾病轨迹；机制被治疗压低，下游 axis 越回到背景。
- 旧 distillation 没有 `latent_mechanisms` 仍然兼容；重蒸后自然进入新结构。

## Outcome Lock

Outcome 已锁为 lifespan-only RMST：

```text
outcome(treatment) = E[lifespan] = E[min(T_death, T_max)]
T_death = SDE 过程中由 mortality_hazard rate 决定的 first jump / first passage time
```

死亡不是硬阈值区域，也不单独蒸馏。每个 disease leaf 的 `mortality_hazard_in_<DISEASE_ID>` 是 disease fundamental description，跟 ferritin / CRP trajectory 同级。

PoC 阶段接受 QOL 缺失；QOL 是未来第二维。

## Axis Ontology

跨病字段一致靠 `master_axes.json`。

规则：

- 同一临床概念必须复用同一 `axis_id`，例如 `serum_ferritin`
- disease-specific hazard 使用 `mortality_hazard_in_<DISEASE_ID>`
- 新 disease 蒸馏 prompt 要注入当前 `master_axes.json` 的 axis_id registry（naming-only，不作为医学清单）
- 保存新 distillation 后更新 `master_axes.json`
- 定期 review 合并同义 axis、统一 unit / log_scale
- 采用旧项目三层变量原则：Finding 只回答有没有，Measurement 保留原始数值，Satellite 只在 parent Finding=present 时描述属性/分布/大小/形态。禁止把 absent + severity 混在一个 axis 里。
- 例：先有 `pathologic_lymphadenopathy_presence=1`，再用 satellite/measurement 描述 `mediastinal_lymphadenopathy_activity`、`largest_nodal_mass_diameter_cm`。不要直接把“CT 有淋巴结包块”拍成 `0.5`。
- V5 JSON 用 `axis_role` 标注三层角色：`finding` / `measurement` / `satellite`。当 satellite 或 child measurement 有明确上位 Finding 时，必须写 `parent_axis_id`；runtime 只在 parent present 时消费 child，并避免 parent + child 对同一临床事实粗细双算。
- OPQRST 属于同一原则：先有症状是否存在的主变量，再把 onset/provocation/quality/radiation/severity/timing 作为卫星变量；没有完成拆分前可以保留旧的 compact activity axis，但不能为了排名删除原文证据。
- **缺 axis 时允许补 ontology**：如果 audit 发现某个 disease manifold 漏了真实、重要、符合实际医学的临床 axis，agent 可以直接补进该 disease 的 `axes`，并同步补 `mechanism_edges` / case structured observations / `master_axes.json`。这不是排名补丁；禁止为了让某个 case 过而发明不存在或不稳定的特征、删除证据、调窄竞品疾病范围。补完必须跑相关 case 与全量回归，报告是否引入退化。

当前 `start_ui.py` 会在保存 distillation 时自动 rebuild `master_axes.json`。

## Missing Axis / Base Measure Policy

核心规则：**某 disease 没有蒸某个 observed axis 时，不能跳过。**

卖菜大爷版：

```text
一个病没写某个指标
= 这个病没有资格解释这个指标异常
= 按这个病人的 base measure / 背景算
```

工程规则：

- 诊断 ranking 应使用病例里所有可用 observed axes。
- 如果 disease schema 含该 axis，用 disease trajectory 计算 likelihood。
- 如果 disease schema 不含该 axis，用 base-measure/background axis 计算 likelihood。
- base measure 优先从 `master_axes.json` 元数据 + 所有 distillation 的 `baseline_range` 合成。
- base measure 后续必须支持 risk-factor-adjusted fallback：先按 `case.risk_context` 调整背景，再计算 missing-axis likelihood。
- 对明显“正常应接近 0”的 axis，例如 rash / sore throat / blood culture positivity，fallback 应是接近 absent / negative。
- 不允许因为某 disease 少写 axis 而获得免扣分优势。
- 防 double count：如果 disease 含该 axis，用 disease trajectory + disease-specific risk modulation；如果 disease 不含该 axis，用 background/base measure + global background modifier。不要两个同时叠在同一个 axis 上。

例：

```text
patient serum_ferritin = 6175
D137 有 serum_ferritin -> 用 AOSD trajectory 算
D-SEPSIS-GN 没有 serum_ferritin -> 用 ferritin base measure 算 -> sepsis 扣分

patient 有 CKD, creatinine = 2.0
某 disease 没有 serum_creatinine -> 用 CKD-adjusted creatinine background 算，而不是完全健康人背景
```

## Unknown Disease / OOD Detection Policy

核心规则：**case 来自未蒸 manifold 时，"未知病" 必须通过 likelihood 对比涌现，不允许 runtime 写死任何 "logP < X 算未知" 的硬阈值。**

卖菜大爷版：

```text
病人来了
系统从已知 N 个病里挑一个最像的
但还要跟 "啥病也没有，纯背景" 比一下
已知病比纯背景明显好 -> 真是这病
已知病并不比纯背景好  -> 我们 atlas 里没有，这是未知病
```

工程规则：

- 诊断 runtime 对每个 case 同时输出：
  - `logP_best_disease`：在已知 manifolds 中的最佳 logP
  - `logP_background_only`：不挂任何 disease，纯 base_measure_background 下的 logP（risk-factor-adjusted）
  - `delta_to_null = logP_best_disease - logP_background_only`
- runtime 不输出 "未知病/已知病" 二值标签，只输出 delta。是否把它二值化由下游消费者（UI / 医生工作流）按 Bayes factor 惯例（BF>10 ≈ delta>2.3）决定。
- 不允许在 runtime 写 `if delta < threshold: return "unknown"`，**因为这又会变成拍脑袋的阈值**。
- `base_measure_background` 由 `v5_background.py` 的 risk-factor-adjusted 合成器提供，与 missing-axis fallback 共用同一套底子。

防错规则：

```text
PoC 阶段已知 atlas 只有 D137 / D-SEPSIS-GN / D-TTP 三片山。
真实世界绝大部分 case 都不在这三片山里。
没有 OOD 检测时，系统会把肺炎、心衰、TB 都强行塞进 sepsis，输出"看上去自信但其实不像"的诊断。
这比拒绝诊断风险高得多。
任何接入临床场景的 demo 必须先打开 OOD 检测。
```

例：

```text
case 1: 真 sepsis
  logP_D-SEPSIS-GN = -45
  logP_background_only = -120
  delta = +75 -> 强证据是 sepsis

case 2: 肺炎 (atlas 没蒸)
  logP_D-SEPSIS-GN = -200 (best)
  logP_background_only = -210
  delta = +10 -> 弱证据，下游应判定为 "未知病/不在 atlas"

case 3: 健康人
  logP_D-SEPSIS-GN = -300 (best)
  logP_background_only = -50
  delta = -250 -> 已知病比纯背景差太多，下游判定为 "未知病或健康"
```

跟 Outcome Lock / Missing Axis Policy / Emergence-First 一样属于**项目级硬规则**，不允许重新讨论是否要写阈值，只允许讨论 delta 怎么算 / null model 怎么改进。

## 当前工程状态

当前目录是 V5 PoC 工程场：

- `V5_SDE_DESIGN_v0.md`: V5 架构 lock 文档
- `v5_layer3_prompt_ui.html` + `start_ui.py`: LLM distillation prompt UI 和保存 server
- `distillations/v5_D137.json`: AOSD non-MAS 新 schema 蒸馏
- `distillations/v5_D-SEPSIS-GN.json`: sepsis 旧版新 schema 蒸馏；包含药敏/耐药、active coverage、感染源、影像/source-control axes、treatment `effect_modifiers`
- `distillations/v5_D-TTP.json`: acquired/immune TTP 新 schema 蒸馏
- `master_axes.json`: 当前 axis registry
- `background_modifiers.json`: global/base-measure risk factor modifiers；只用于 missing-axis fallback，不直接改 disease trajectory
- `condition_scope.json`: condition scope registry；防止同一 condition 既当球属性又当 disease manifold 对同一组 axes 双算
- `v5_background.py`: risk-factor-adjusted base-measure helper
- `v5_sde_forward_v2.py`: 旧 AOSD / HLH / Healthy ranking PoC
- `v5_treatment_emerge.py`: AOSD treatment RMST ranking PoC
- `patch_v0_hazard_completion.py`: hazard 补丁脚本
- `v5_current_schema_case_test.py`: 当前 schema 的 AOSD vs sepsis 真实 PMC case smoke test；已实装 missing-axis base-measure fallback
- `v5_joint_sde_case_test.py`: joint SDE case ranking；消费 `latent_mechanisms` / `mechanism_edges` / `axis_couplings`、risk-factor modulation，并支持 2-disease vector-field superposition
- `v5_joint_sde_treatment_sim.py`: joint SDE treatment vector-field simulation；消费 `latent_mechanisms` / `mechanism_edges` / `treatments`，支持 `reshape_landscape` / `push_state` / `sigma_modulation`、同病多治疗 bundle 和 timed-stage policies，按 RMST 排名治疗策略

已完成：

- V5 PoC v2：AOSD / HLH / Healthy 三流形，3 case，5/5 PASS
- 架构 lock
- outcome lock
- per-disease 全栈 prompt / UI 初版
- D137 与 D-SEPSIS-GN distillation 初版
- D-TTP distillation 初版
- `master_axes.json` 初版
- missing-axis base-measure fallback：真实 case ranking 不再跳过 disease 未蒸的 observed axes
- MaxEnt base-measure 规则已锁：missing axis 不跳过、不乱补 disease trajectory，而是回到 risk-factor-adjusted base measure；球属性和地形不得对同一 axis 双算
- `background_modifiers.json` / `condition_scope.json` / `v5_background.py` 已实装，并已接入 `v5_current_schema_case_test.py`、`v5_joint_sde_case_test.py`、`v5_joint_sde_treatment_sim.py`
- distillation prompt 已升级为纯病名输入 + mechanism-first 工程 schema；新增 `latent_mechanisms` / `mechanism_edges`
- distillation prompt 只允许 disease-specific 医学输入来自病名本身；不再用感染病/免疫病/TMA module 强制抽医学清单
- distillation prompt 已升级 complication/event hazard schema：新增 `event_hazard` axis 与 `hazard_drift` / `event_transition` couplings，用于把出血、ICH、AKI、ARDS、DIC、MAS/HLH 等并发症链条接入 RMST
- `D137` 已用 mechanism-first one-shot 重蒸：7 latent mechanisms、36 mechanism_edges、46 explicit axes、14 couplings、11 treatments；AOSD 与 sepsis/TTP case ranking 仍 PASS
- `D-TTP` 已用 mechanism-first one-shot 重蒸：6 latent mechanisms、25 mechanism_edges、55 explicit axes、16 couplings、11 treatments；TTP 治疗语义已把 TPE / steroid / rituximab / caplacizumab 分开
- `D-SEPSIS-GN` 的既有 JSON 已包含药敏/耐药、active coverage、感染源、影像/source-control axes、treatment effect modifiers；后续重蒸必须使用纯病名 prompt
- joint SDE runtime v0 已实现：多轴联合 covariance、risk factor 调制、A+B 合并流形锚点门槛、标准化 vector-field 叠加
- joint SDE PMC case test 当前结果（2026-05-03，atlas = D137 / D-SEPSIS-GN / D-TTP / D-HLH-MAS / D-SLE-FLARE）：single-manifold 11/12 PASS；combo-manifold 1/1 PASS。唯一 FAIL 是 SEPSIS_KIDNEY_TX_RALSTONIA 被 D-HLH-MAS 抢去；不要为通过该 case 打补丁，需先用纯病名 prompt 重蒸受旧 prompt 污染的 manifold，再按真实 case 复测。
- `D-HLH-MAS` 现有 JSON：8 latent mechanisms、56 mechanism_edges、69 explicit axes、12 couplings、15 treatments、10 risk_factors；可解析，但来自旧 prompt 语义，后续应按纯病名 prompt 重蒸。
- `D-SLE-FLARE` 现有 JSON (2026-05-02)：11 latent mechanisms、69 mechanism_edges、92 explicit axes、18 couplings、16 treatments、10 risk_factors；可解析，但后续应按纯病名 prompt 重蒸。
- OOD / unknown-disease null-model check 已接入 `v5_joint_sde_case_test.py`：每个 case 输出 `logP_best_known`、`logP_background_only`、`delta_to_null_best_known`；runtime 不写硬阈值
- 已加入复杂 PMC cases：肾移植免疫抑制 sepsis、AOSD+TTP、SLE-associated TTP
- treatment vector field runtime v0 已实现：治疗会改变 joint state target、push 指标、调 sigma、改变 mortality_hazard，并输出 30-day RMST 排名与 day-7 axis movement；runtime 已能消费 `required_context_axes` / `effect_modifiers`
- treatment runtime 已支持同病多治疗 bundle：按 treatment lane 组合互补治疗，避免两个抗生素、TPE+plasma infusion bridge 这类替代方案混搭；同一 axis 的多治疗 `trajectory_modifications` 会先合并再应用，避免弱 add-on 覆盖强 core therapy
- treatment runtime 已支持 timed-stage policies：同一 bundle 内可让慢效/后线 add-on 延迟启动，输出 label 形如 `rituximab@day1`、`anakinra_100mg_daily@day2`；当前不是 lab-response adaptive branch
- mechanism DAG runtime v0 已实现：`latent_mechanisms` 被读成隐藏 0-1 axis，`mechanism_edges` 会让机制强度 gate 下游 axes/event hazards/outcome；旧 distillation 仍兼容
- 新版 sepsis treatment runtime 初测：ESBL E. coli case 排 `ertapenem_iv` 第一；肾移植 Ralstonia case 不再乱排 `ceftriaxone` 第一，当前排 `meropenem_iv` 第一、`piperacillin_tazobactam_iv` 第二
- 新版 TTP treatment runtime 初测：TTP_SLE case 最优为 `urgent_daily_therapeutic_plasma_exchange + high_dose_glucocorticoids + rituximab`；`caplacizumab` 作为条件性 add-on 不再单药压过 TPE；`rituximab@day1` 等 timed-stage 候选也会进入排名
- `D-SEPSIS-GN` / `D137` / `D-TTP` 已补 patient-usability `treatment_modifier` axes 和 treatment `effect_modifiers`：beta-lactam/penicillin 过敏、妊娠、肝肾限制、活动感染/再激活风险、出血/抗凝、血浆反应、容量负荷等上下文已能调制治疗排序；所有 `treatment_modifier` axes 已归一为“上下文轴”，默认不带 disease-course 峰值曲线

仍待做：

- **重蒸 D-SEPSIS-GN（2026-05-03 触发）**：现有蒸馏受旧 prompt 限定污染，Ralstonia case 失败是该污染暴露出来的结果。重蒸时只给纯病名，不在 prompt 中指定应覆盖的子谱、事件、mimic 或治疗上下文；重蒸后用真实 case 复测。
- **修 distillation phantom axis 引用（2026-05-03 本体已拍板，工程实装待讨论）**：5 处 treatment 引用本 manifold 没定义的 axis。诊断 ranking 不踩（已验证），但治疗模拟会借用别的 manifold baseline，语义糊涂。**本体修正**（用户拍板）：每个 axis 都属于某个疾病；`serum_glucose`/`serum_amylase`/`serum_lipase`/`serum_potassium`/`serum_bicarbonate`/`oxygen_saturation` 不是"球的全局属性"，它们的主家疾病（糖尿病/急性胰腺炎/CKD/酸中毒/ARDS-呼衰）只是 atlas **还没蒸**。**关键原则**：LLM 必须能自由引用 atlas 还没有的 axis——否则"激素副作用→血糖升高"这类真临床关系根本蒸不出来；phantom 引用是 atlas 该长大的信号，系统应"学"，不应"挡"。工程方向：(1) `master_axes.json` 加 `pending_axes` 节占位（axis_id + unit + 健康 baseline + pending_owner_disease 标注），引用得到、健康 baseline fallback；以后蒸主家疾病时 axis 升级为正式 disease-owned；(2) `serum_amylase_lipase` 拆成 `serum_amylase` 和 `serum_lipase` 两个 axis（Claude 把两个独立测的化验项混成了一个）；(3) `start_ui.py` 保存时**不拒绝**新 axis 引用，而是把不在三池里的引用自动登记到 `pending_axes_candidates`（含首次引用来源），保存仍然成功，UI 提示用户补 baseline + owner；(4) prompt 已加 AXIS NAMING RULE (one axis = one measurable value)，禁拼接独立 lab（如 `serum_amylase_lipase`），但**明确鼓励**自由引用 atlas 还没有的 axis。详见 `project_distillation_phantom_axis_references.md`。
- 把 missing-axis fallback 从 smoke test 提炼为正式 inference helper
- **蒸馏后检查 event hazard 结构**：检查输出是否用 `event_hazard` 和 `hazard_drift` / `event_transition` 表达 outcome-relevant events；不要在 prompt 里给 disease-specific event 清单。
- **蒸馏后检查 treatment 结构**：检查 `trajectory_modifications` 是否有临床可解释的显性 axis 作用；不在 prompt 里规定固定数量，也不靠只改 `mortality_hazard` 过关。
- `side_effects` 与 `effect_scale` 的关系已拍板并实装：`scale=0` 表示治疗根本不给，整段治疗和副作用都跳过；`scale>0` 表示全剂量给药但疗效可打折，副作用不随疗效打折。不需要 `binding` schema 字段。
- **副作用进入 outcome 的方向已定**：走 event hazard / hazard_drift，不走人工 toxicity penalty。当前还需要新字段蒸馏与 runtime 广泛验证。
- **治疗蒸馏原则（2026-05-04）**：不在 prompt 里规定每个治疗必须改固定数量的 axis/mechanism。正确原则是“最小充分因果作用路径”：每个治疗写清它在该疾病中直接改变的 latent mechanism / observed axis / event hazard / treatment-context axis，写清疗效、无效、禁忌和毒性的 context modifier；下游变化应通过 mechanism_edges / axis_couplings / hazard_drift 涌现。禁止只写 `mortality_hazard` 这种黑箱终点效应，除非确实不存在临床上有意义的中间机制或 axis。
- 继续细化 sepsis case evidence：真实病例 JSON 需要显式抽 drug susceptibility / actual antibiotic / initial inactive therapy / CT finding / source control done/not done
- 针对 Ralstonia case 补实际药敏和可用治疗项（如 TMP-SMX、amikacin、pip-tazo）后再验证治疗排序是否贴近原文
- 用当前新 schema 做 AOSD vs sepsis vs healthy ranking
- 真实 PMC cases 扩充到 `distillations/cases/`
- v4: 更多横向/纵向合并症压力测试；纵向并发症触发后叠加新 manifold 的机制
- v0.1: hierarchical / smoothing / Euler innovation / selection model / identifiability assumptions

## 测试真实病例的规则

找 PMC case 时：

- 必须记录 `PMID` / `PMCID` / URL / paper diagnosis
- **真实病例信息不得只停留在 free text**：原文出现的 presentation-time 症状、体征、影像状态、微生物/药敏、治疗前 labs/vitals，都要保留原文 `source_text_value`，并尽可能投到结构化 `observations` / `lab_trajectories` / `risk_context`。free-text `presentation_summary` / `presenting_symptoms` 只能作为人读摘要，不能替代 runtime evidence。
- **结构化后必须进入测试**：测试 runtime 应消费病例中所有可映射的 observed axes；若 axis 尚未被任何 disease 拥有，0-1 qualitative/probability/relative_activity 轴先走 background fallback，不允许静默丢弃。真正缺 ontology 的 axis 应作为 pending axis 暴露给后处理。
- 不要使用确诊性检查作为普通 diagnostic evidence，例如活检、培养定种、ADAMTS13 等可作为 source/context，但 ranking evidence 优先用 presentation-time labs/vitals/symptoms
- 优先选有足够现有 axes 可映射的 case：temperature, HR, BP/MAP, WBC/ANC, platelet, CRP, ferritin, AST/ALT, creatinine, lactate, procalcitonin, fibrinogen 等
- 保留原文值，不为了排名修改 evidence
- 若单位不同，用显式转换并在 case JSON 记录
- 画像/查体证据优先保留原始测量值；有尺寸就用 cm/mm 等原始单位建轴，例如 `largest_nodal_mass_diameter_cm`、`splenic_long_axis_cm`。只有原文只写 present/absent 时才用 0/1 presence/activity；不要把“CT 显示 lymph node packets”这种模糊描述拍成 0.5。
- 测试失败要报告失败和原因，不要通过删 evidence 或调参过拟合
- 对需要病理/免疫表型才能分型的疾病族（例如 lymphoma），presentation-only 测试不应强迫具体 subtype leaf 必须第一；合理目标是同一 family 的 leaf 占据上位 cluster，提示“在 lymphoma 区域但 subtype 未分清”。只有 biopsy / IHC / flow / cytogenetics 等 subtype-specific evidence 进入 confirmatory/context evidence 后，才要求具体 subtype leaf 明确第一。

当前已有 disease manifolds：

- `D137`: Adult-onset Still's disease (AOSD)
- `D-SEPSIS-GN`: Bacterial sepsis（蒸馏旧版带额外限定，待按纯病名 prompt 重蒸）
- `D-TTP`: Thrombotic thrombocytopenic purpura（蒸馏旧版带额外限定，待按纯病名 prompt 重蒸）
- `D-HLH-MAS`: Hemophagocytic lymphohistiocytosis / macrophage activation syndrome（现有 JSON 可解析，待按纯病名 prompt 重蒸）
- `D-SLE-FLARE`: Systemic lupus erythematosus flare（蒸馏旧版带额外限定，待按纯病名 prompt 重蒸）

新 case 建议放到：

```text
distillations/cases/
```

测试脚本输出建议放到：

```text
distillations/case_test_result.txt
distillations/joint_sde_case_test_result.txt
distillations/joint_sde_treatment_result.txt
```

## 重要参考

- `V5_SDE_DESIGN_v0.md`
- `v5_layer3_prompt_ui.html`
- `C:\Users\wangw\Desktop\VeSMed-v3\CLAUDE.md`
- `C:\Users\wangw\Desktop\VeSMed-v3\.claude-memory\MEMORY.md`
- `C:\Users\wangw\Desktop\VeSMed-v3\.claude-memory\project_v5_architecture_v0_locked.md`
- `C:\Users\wangw\Desktop\VeSMed-v3\.claude-memory\project_v5_ontology.md`
- `C:\Users\wangw\Desktop\VeSMed-v3\.claude-memory\project_v5_per_disease_full_stack.md`
- `C:\Users\wangw\Desktop\VeSMed-v3\.claude-memory\project_v5_axis_ontology_registry.md`
- `C:\Users\wangw\Desktop\VeSMed-v3\.claude-memory\project_v5_emergent_first_line.md`
