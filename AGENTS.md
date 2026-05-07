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

### Agent Reasoning Effort

所有被派去做 disease distillation、axis ontology audit、real PMC case expansion、医学结构化或治疗语义补全的 subagent，默认必须使用 `reasoning_effort: "xhigh"`。这是质量优先的铁律；除非用户明确要求降级，或任务完全是非医学、非质量关键的机械操作，否则不要用 `high` / `medium` / `low`。

新增 disease leaf 时默认采用 **one disease, one agent**：每个新病单独派一个 `xhigh` agent 负责该病的 distillation / ontology audit / real case 结构化与质量审查，写入范围按 disease 文件和对应 case 文件隔离，避免多个 agent 修改同一 disease 造成冲突。

扩展 atlas 的当前目标是 200 个 disease leaves。新增 disease 时优先 common + critical；每个 disease leaf 原则上配套至少 3 个真实 PMC/PubMed real cases，除非确实找不到，不能只新增 disease JSON 而没有病例压测。

### Disease Leaf Granularity

第一层 disease manifold 必须蒸到“临床流形稳定、医生能独立假设”的具体 disease leaf，不用过宽 umbrella 诊断。

原则：

- 如果 umbrella 内部的机制、典型器官轴、治疗毒性/适应证、mimic 关系明显不同，就必须拆 leaf。
- 例：`ANCA-associated vasculitis` 太宽，不能作为第一层 disease leaf；应拆为 `D-MPA`（Microscopic polyangiitis / 顕微鏡的多発血管炎）、`D-GPA`、`D-EGPA` 等独立 manifold。
- `disease_id` 也会被 LLM 当成医学输入，因此不能把 disease name 之外的病因、mimic、亚型或近邻病写进 ID。例：`Disease: Infectious mononucleosis` 不能配 `D-EBV-CMV-MONO-LIKE`，因为 `CMV` 会污染蒸馏；应使用 `D-INFECTIOUS-MONONUCLEOSIS`，CMV mononucleosis-like illness 未来单独蒸。
- `D-LYMPHOMA-FEVER` 过宽，只能作为 legacy umbrella 暂存；不能为了 ALCL case 被 `D-MIS-A` 吸走而调 case 或加语义补丁。正确下一步是拆成 subtype disease leaves，例如 `D-ALCL`、`D-HODGKIN-LYMPHOMA`、`D-DLBCL`、`D-IVLBCL`，并为每个 subtype 加 PMC real case。
- `complicated` / `uncomplicated` 这类限定通常不是第一层 disease leaf 名本身。例：尿路感染应先蒸 `D-PYELONEPHRITIS`（Pyelonephritis / 腎盂腎炎）；`uncomplicated pyelonephritis`、`complicated pyelonephritis`、`obstructive pyelonephritis`、`emphysematous pyelonephritis` 等先放 risk/context/source-control/event axes，未来需要时再在 `D-PYELONEPHRITIS` 下做第二层 subtype distillation。
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
- **新增 axis 必须横向公平审查**：给某个 disease / disease family 补 axis 时，必须同时检查当前 atlas 里的竞争病和近邻 mimic 是否也应医学真实地拥有该 axis 或其 parent axis / satellite。该补的同步补，不该有的明确不补；不能只给目标病增加解释力、让其他真实也会出现该证据的疾病被不公平扣分。横向补轴仍必须符合真实医学，不能为了“公平”把不存在或极罕见、非稳定的特征硬塞进别的病。
- **补轴不是单病补丁**：任何因为 real case 失败而发现的漏轴，都要先判断这是目标病独有、某个疾病家族共有，还是多个 mimic 都应拥有。若是 family/near-neighbor 共有轴，必须同步补到医学上真实相关的竞争 manifold；若只给失败目标病补而不补其他同样会出现该证据的病，本质上就是变相过拟合，禁止这样做。

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
- **每新增一个 disease leaf，必须同步新增至少 1 个真实 PMC/PubMed case**，并把该 case 纳入 smoke test。不能只新增 distillation JSON 而没有真实病例压测。
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

## 2026-05-06 Current-Atlas Regression Memory

- Full current-atlas regression must not default to large Monte Carlo over every case and every disease. With 88 manifolds and 240 real cases, naive single-disease scoring at `N_MC=1000` means ~21M candidate samples before combo expansion. This is too slow for routine regression.
- `v5_joint_sde_case_test.py` now supports fast deterministic full-regression mode:
  - `VESMED_SCORE_MODE=grid`
  - `VESMED_TIME_GRID_N=21`
  - `VESMED_MAX_COMBO_SIZE=1`
- Use the fast grid mode as the routine whole-atlas smoke test. Use high-MC mode only for focused failures, close top-2 cases, and small new-disease batches.
- The 2026-05-06 full current-atlas fast regression loaded 240 case JSON files. Single-manifold validation was `223/238 PASS`; one combo case was not expected to pass because combo scoring was intentionally off; one case had no expected label.
- Current priority failures to audit without hardpatching:
  - `AIHA_EBV_COLD_PMC12004763`: expected `D-AIHA`, got `D-BABESIOSIS`
  - `AIHA_PEMBROLIZUMAB_PMC6827724`: expected `D-AIHA`, got `D-ALL`
  - `BABESIOSIS_OVERWHELMING_PARASITEMIA_PMC7585322`: expected `D-BABESIOSIS`, got `D-MALARIA-FALCIPARUM`
  - `CMV_MONO_POST_SPLENECTOMY_PMC10860906`: expected `D-CMV-MONO`, got `D-STEC-HUS`
  - `COMPLEMENT_MEDIATED_TMA_APS_ANTIGBM_OVERLAP_PMC10448002`: expected `D-COMPLEMENT-MEDIATED-TMA`, got `D-CATASTROPHIC-APS`
  - `COMPLEMENT_MEDIATED_TMA_SEVERE_PANCOLITIS_NEURO_PMC3262387`: expected `D-COMPLEMENT-MEDIATED-TMA`, got `D-ALL`
  - `COVID19_HEMOPTYSIS_HEMATURIA_PMC8355942`: expected `D-COVID19-ACUTE`, got `D-ADENOVIRUS-INFECTION`
  - `HISTOPLASMOSIS_DISSEMINATED_AIDS_BONE_MARROW_PMC10040219`: expected `D-HISTOPLASMOSIS-DISSEMINATED`, got `D-ADENOVIRUS-INFECTION`
  - `HLH_MAS_DERMATOMYOSITIS_PMC7281037`: expected `D-HLH-MAS`, got `D137`
  - `HODGKIN_AOSD_MASK_PMC4847271`: expected `D-HODGKIN-LYMPHOMA`, got `D-ALCL`
  - `IVLBCL_PULMONARY_RANDOM_SKIN_BIOPSY_PMC3962888`: expected `D-IVLBCL`, got `D-LEGIONELLA-PNEUMONIA`
  - `PJP_RA_ABATACEPT_PMC4182847`: expected `D-PJP-PNEUMONIA`, got `D-ADENOVIRUS-INFECTION`
  - `PJP_RENAL_TRANSPLANT_HYPERCALCEMIA_PMC11024830`: expected `D-PJP-PNEUMONIA`, got `D-NOCARDIOSIS`
  - `STAPH_AUREUS_BACTEREMIA_CERVICAL_MYELITIS_OSTEOMYELITIS_PMC5444316`: expected `D-STAPH-AUREUS-BACTEREMIA`, got `D-BRUCELLOSIS`
  - `VERTEBRAL_OSTEOMYELITIS_CAMPYLOBACTER_PSOAS_PMC11002916`: expected `D-VERTEBRAL-OSTEOMYELITIS`, got `D-CLOSTRIDIOIDES-DIFFICILE-SEVERE`
- Audit these failures by evidence flow first: case JSON structured evidence -> `load_case` consumed axes -> expected manifold axes/mechanism_edges -> stealing manifold axes/mechanism_edges. Do not delete evidence, narrow a competing disease, or add disease-specific ranking rules to make a case pass.

Follow-up after generic evidence/runtime fixes:

- Two generic fixes were added before further disease-specific work:
  - Clamp bounded 0-1 axes (`present_absent_0_1`, `probability_0_1`, `relative_activity_0_1`, `severity_score_0_1`) after risk modulation. This fixed impossible values such as asplenia/immunosuppression activity becoming >1.
  - Let `load_case` consume explicit `axis_id` records from nonstandard rankable sections while still excluding `confirmatory_*`, actual treatment, outcome, follow-up, and treatment sections. It also handles safe qualitative values such as `high_grade_fever` and `normal`.
- After these fixes, full current-atlas fast regression improved to `225/238 PASS` in single-manifold validation. The two recovered cases were:
  - `BABESIOSIS_OVERWHELMING_PARASITEMIA_PMC7585322`
  - `VERTEBRAL_OSTEOMYELITIS_CAMPYLOBACTER_PSOAS_ABSCESS_PMC11002916`
- Remaining 13 failures should be treated as audit targets, not patch targets:
  - AIHA triggered by EBV or immune-checkpoint inhibitor: likely trigger/combo context and risk-context ontology issues, not pure AIHA manifold failure alone.
  - CMV mono after splenectomy: post-splenectomy/severe CMV context versus STEC-HUS mimic; confirmatory CMV evidence remains excluded.
  - Complement-mediated TMA overlap cases: one is true APS/anti-GBM overlap; one is bloody diarrhea/pancolitis TMA and naturally mimics STEC-HUS.
  - COVID hemoptysis/hematuria: presentation-only overlaps adenovirus; SARS-CoV-2 PCR is confirmatory and excluded.
  - Disseminated histoplasmosis in AIDS: likely AIDS/OI risk-context matching plus disseminated histoplasmosis GI/septic-shock axis coverage issue.
  - HLH/MAS with dermatomyositis: close margin versus AOSD; likely needs dermatomyositis trigger/combo handling and/or pure-prompt HLH refresh.
  - Hodgkin vs ALCL: lymphoma subtype presentation-only family-cluster issue; do not force subtype without biopsy/IHC context.
  - IVLBCL pulmonary case: pulmonary infection mimic with high procalcitonin; likely needs IVLBCL pulmonary/B-symptom axis audit, but biopsy remains confirmatory.
  - PJP cases: likely immunosuppression/risk-context ontology mismatch and treatment_modifier/context axes being mishandled in diagnostic likelihood.
- SAB cervical myelitis/osteomyelitis: likely combo `D-STAPH-AUREUS-BACTEREMIA + D-VERTEBRAL-OSTEOMYELITIS` and missing SAB metastatic CNS/spinal inflammatory axes.

2026-05-06 follow-up after principled axis/runtime fixes:

- Do not use broad fuzzy runtime semantic matching for risk factors by default. It caused over-broad prior/risk modulation and did not materially fix the focused failures. Risk modifiers should match exact structured risk context or controlled `present`-style category semantics unless a future ontology layer makes synonymy explicit.
- `treatment_modifier` axes are host/treatment context axes, not ordinary disease-course peaks. If a distillation contains such an axis but omits its time structure, `v5_joint_sde_case_test.py` now treats it as a persistent context axis by default (`peak_day_range=[-365,0]`, long plateau/decline) while still excluding it from disease `t_max` inference. This avoids the false behavior where high immunosuppression or renal dose-adjustment context is scored as impossible merely because the JSON omitted boilerplate timing.
- Horizontal fairness audit was applied before fixing PJP/SAB: ESR was added across pneumonia/OI/bacteremia competitors where medically real, and SAB metastatic CNS/spinal axes were added to `D-STAPH-AUREUS-BACTEREMIA` instead of making a case-specific ranking rule.
- Full current-atlas fast regression after these fixes: 240 case JSON files loaded; single-manifold validation `229/238 PASS`; combo case intentionally off in that full run. Separate combo check with `VESMED_MAX_COMBO_SIZE=2` and `VESMED_ONLY_COMBO_CASES=1` was `1/1 PASS` (`D137+D-TTP`).
- Recovered from the 13 post-loader failures: `COVID19_HEMOPTYSIS_HEMATURIA`, both PJP cases, and `STAPH_AUREUS_BACTEREMIA_CERVICAL_MYELITIS_OSTEOMYELITIS`.
- Remaining 9 single failures:
  - `AIHA_EBV_COLD_PMC12004763`: expected `D-AIHA`, got `D-BABESIOSIS`
  - `AIHA_PEMBROLIZUMAB_PMC6827724`: expected `D-AIHA`, got `D-ALL`
  - `CMV_MONO_POST_SPLENECTOMY_PMC10860906`: expected `D-CMV-MONO`, got `D-STEC-HUS`
  - `COMPLEMENT_MEDIATED_TMA_APS_ANTIGBM_OVERLAP_PMC10448002`: expected `D-COMPLEMENT-MEDIATED-TMA`, got `D-CATASTROPHIC-APS`
  - `COMPLEMENT_MEDIATED_TMA_SEVERE_PANCOLITIS_NEURO_PMC3262387`: expected `D-COMPLEMENT-MEDIATED-TMA`, got `D-STEC-HUS`
  - `HISTOPLASMOSIS_DISSEMINATED_AIDS_BONE_MARROW_PMC10040219`: expected `D-HISTOPLASMOSIS-DISSEMINATED`, got `D-ADENOVIRUS-INFECTION`
  - `HLH_MAS_DERMATOMYOSITIS_PMC7281037`: expected `D-HLH-MAS`, got `D137`
  - `HODGKIN_AOSD_MASK_PMC4847271`: expected `D-HODGKIN-LYMPHOMA`, got `D-ALCL`
  - `IVLBCL_PULMONARY_RANDOM_SKIN_BIOPSY_PMC3962888`: expected `D-IVLBCL`, got `D-LEGIONELLA-PNEUMONIA`
- Lymphoma presentation-only rule is accepted by the user: if the case lacks biopsy/IHC/flow/cytogenetics evidence in the ranking set, a lymphoma subtype case may be considered family-level acceptable when lymphoma-family leaves occupy the top cluster. Once subtype-specific pathology/immunophenotype/genetics evidence is included, the exact subtype leaf should be expected to rank first.

## 2026-05-06 Fail Repair + New Leaf Memory

- Fail 修复最高原则：不能为了测试结果删除 evidence、窄化竞品 disease、或加 runtime 诊断标签补丁。先查 `case JSON -> load_case consumed axes -> expected manifold axes/mechanism_edges -> stealing manifold axes/mechanism_edges`，只能做通用 runtime、本体、真实医学轴和横向公平补轴。
- 本轮 9 个残余 single fail 经过医学真实轴补充后，full current-atlas fast regression 从 `229/238 PASS` 提升到 `237/238 PASS`；唯一剩余为 `HODGKIN_AOSD_MASK_PMC4847271` 被 `D-ALCL` 抢走，按 lymphoma presentation-only family-cluster 原则接受。
- 新增三片 disease leaf，并各配 1 个真实 PMC case：
  - `D-DERMATOMYOSITIS`: case `DERMATOMYOSITIS_RESPIRATORY_MUSCLE_WEAKNESS_PMC12831999` / PMID `41589189` / PMC `PMC12831999`
  - `D-EVANS-SYNDROME`: case `EVANS_SYNDROME_PERICARDIAL_EFFUSION_PMC11330688` / PMID `39156320` / PMC `PMC11330688`
  - `D-HEPARIN-INDUCED-THROMBOCYTOPENIA`: case `HIT_DVT_HEPARIN_PMC3279506` / PMID `22312443` / PMC `PMC3279506`
- Evans 初测被 `D-ALL` 抢走的根因不是诊断标签，而是 axis ontology 混单位：`reticulocyte_count` 同时被用作 absolute count (`10^9/L`) 和 percentage (`percent`)。修复原则已锁：
  - `reticulocyte_count` = absolute reticulocyte count, unit `10^9/L`
  - `reticulocyte_percentage` = reticulocyte percentage, unit `percent`
  - 两者不能互相 convert；没有 RBC count 时不能从一个硬算另一个。
  - 对真实会改变网织红细胞反应的近邻病，必须横向公平补另一种报告形式，而不是只补目标 disease。
- TTP-SLE 回归被 `D-COMPLEMENT-MEDIATED-TMA` 抢走时，根因是 TTP 有 `anti_adamts13_igg_inhibitor_titer`，但 case 结构化为 `anti_adamts13_antibody_positivity_probability`，两者没有接上。修复原则：诊断 context finding 和 quantitative measurement 可以是 parent/child 或相邻 axis；真实临床同一证据族必须在 disease manifold 中有可消费路径。
- TMA 家族横向补轴原则：给 `D-TTP` 补黄疸、AST/ALT、WBC/ANC、anti-ADAMTS13 positivity 时，同步审查 `D-COMPLEMENT-MEDIATED-TMA`、`D-STEC-HUS`、`D-CATASTROPHIC-APS`。凡是微血管病性溶血/缺血/系统炎症真实会出现的轴，也要给近邻病补；不能只给目标病增加解释力。
- 本轮最终回归结果：
  - Full current-atlas fast grid (`VESMED_SCORE_MODE=grid`, `VESMED_TIME_GRID_N=21`, `VESMED_MAX_COMBO_SIZE=1`): 243 case JSON loaded; single-manifold validation `240/241 PASS`; combo intentionally off.
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`): `1/1 PASS`, `AOSD_TTP_CONCURRENT_PMC7523203` ranks `D137+D-TTP`.
  - Remaining single fail: `HODGKIN_AOSD_MASK_PMC4847271` expected `D-HODGKIN-LYMPHOMA`, best `D-ALCL`; accepted as lymphoma-family presentation-only ambiguity unless subtype pathology/IHC/flow/genetics is used as ranking evidence.

## 2026-05-06 New Batch Memory: ASyS / Kawasaki / Anti-GBM

- 新增 disease leaf 必须执行 one disease, one agent：本轮分别用 3 个 `xhigh` worker 审查 `D-ANTISYNTHETASE-SYNDROME`、`D-KAWASAKI-DISEASE`、`D-ANTI-GBM-DISEASE`，每个 agent 只负责自己的 disease JSON 和 3 个 PMC case JSON。
- 新增 3 个 common/critical disease leaves，各配 3 个真实 PMC/PubMed cases：
  - `D-ANTISYNTHETASE-SYNDROME`: `PMC6679997` / PMID `31376837`, `PMC10515292` / PMID `37746430`, `PMC11046532` / PMID `36697016`
  - `D-KAWASAKI-DISEASE`: `PMC5341178` / PMID `28274249`, `PMC5878266` / PMID `29593004`, `PMC7296651` / PMID `32539746`
  - `D-ANTI-GBM-DISEASE`: `PMC2475522` / PMID `18590526`, `PMC5175522` / PMID `28028414`, `PMC6357502` / PMID `30704432`
- Case evidence rule reinforced: all real presentation information must be preserved and rankable when it is a true observed presentation finding. Do not remove inconvenient evidence such as mediastinal/hilar lymphadenopathy just to make the expected disease rank first.
- Confirmatory evidence rule reinforced: final diagnosis, biopsy/pathology, serology that is only available as confirmatory diagnosis context, and follow-up outcomes remain in `confirmatory_findings` or non-ranking sections with `use_in_ranking:false` unless the test objective explicitly includes post-workup diagnostic evidence.
- Antisynthetase PMC10515292 is an accepted presentation-only mimic exposure: the real case has fever/weight loss, oxygen-requiring ILD, and large mediastinal/hilar lymphadenopathy; when anti-Jo1 and biopsy are excluded, `D-DLBCL` ranks first. Do not hard-fix by deleting lymphadenopathy, adding ASyS-specific lymphoma-like nodes only for this case, or ranking anti-Jo1 by default. If a future mode includes diagnostic workup evidence, anti-Jo1/biopsy can be consumed there.
- Full current-atlas fast grid after this batch:
  - `VESMED_SCORE_MODE=grid`, `VESMED_TIME_GRID_N=21`, `VESMED_MAX_COMBO_SIZE=1`
  - 252 cases loaded; single-manifold validation `248/250 PASS`; combo intentionally off.
  - Single fails: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL` (accepted mimic exposure), and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL` (accepted lymphoma-family presentation-only ambiguity).
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) remains `1/1 PASS` with `AOSD_TTP_CONCURRENT_PMC7523203` ranking `D137+D-TTP`.

## 2026-05-06 New Batch Memory: RA flare / Sickle ACS / SEA

- The next 3-disease loop used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-RA-FLARE`: rheumatoid arthritis systemic flare.
  - `D-SICKLE-CELL-ACUTE-CHEST`: sickle cell acute chest syndrome.
  - `D-SPINAL-EPIDURAL-ABSCESS`: spinal epidural abscess.
- Each new disease leaf has 3 real PMC/PubMed case JSON files:
  - `D-RA-FLARE`: `PMC8009616`, `PMC12547289`, `PMC11110478`.
  - `D-SICKLE-CELL-ACUTE-CHEST`: `PMC10897885`, `PMC6733779`, `PMC6378019`.
  - `D-SPINAL-EPIDURAL-ABSCESS`: `PMC6092525`, `PMC7568137`, `PMC9062902`.
- RA flare source selection rule from this batch: do not label Felty syndrome, immune-checkpoint-inhibitor induced arthritis, or unrelated RA comorbidity papers as ordinary `D-RA-FLARE` cases just to reach a case count. Use clean RA flare cases or defer the leaf.
- Sickle cell acute chest syndrome is trigger-agnostic at first-layer leaf level. Infection, VOC, fat embolism, COVID trigger, and undiagnosed HbSC/SCD context stay as mechanisms/risk context, not separate prompt qualifiers.
- Spinal epidural abscess rankable evidence may include presentation MRI pattern and early microbiology context, but operative aspirate culture, final susceptibility, and treatment response should remain confirmatory/non-ranking unless testing a post-workup mode.
- UI roadmap policy was tightened: `parse_roadmap_presets()` now filters out disease ids that already have `distillations/v5_*.json`; completed leaves appear through the distilled-atlas dropdown, not as future roadmap candidates. Default next UI roadmap candidate is `D-RHEUMATIC-FEVER`.
- Focused new-batch fast grid (`RA_FLARE,SICKLE_CELL_ACUTE_CHEST,SPINAL_EPIDURAL_ABSCESS`) loaded 9 cases and was `9/9 PASS`.
- Full current-atlas fast grid after this batch:
  - 261 case JSON files loaded.
  - Single-manifold validation `257/259 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) remains `1/1 PASS` with `AOSD_TTP_CONCURRENT_PMC7523203` ranking `D137+D-TTP`.

## 2026-05-06 New Batch Memory: ARF / DKA / Acute Myocarditis

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-RHEUMATIC-FEVER`: acute rheumatic fever.
  - `D-DIABETIC-KETOACIDOSIS`: diabetic ketoacidosis.
  - `D-ACUTE-MYOCARDITIS`: acute myocarditis.
- New real PMC/PubMed cases:
  - `D-RHEUMATIC-FEVER`: `PMC4867803`, `PMC6239074`, `PMC6374571`.
  - `D-DIABETIC-KETOACIDOSIS`: `PMC3962942`, `PMC7380362`, `PMC8818290`.
  - `D-ACUTE-MYOCARDITIS`: `PMC5329895`, `PMC9128271`, `PMC6946433`, `PMC5304557`.
- ARF source rule: chorea-only or delayed-heavy sources can be real ARF, but should not be used to pull the first-layer acute ARF leaf away from fever/arthritis/carditis/rash presentations unless the test objective is specifically delayed neurologic ARF.
- DKA source rule: euglycemic DKA, COVID-triggered DKA, pancreatitis/HTG overlap, and severe electrolyte complications are contexts/spectrum within `D-DIABETIC-KETOACIDOSIS`; do not put those qualifiers in the disease name or prompt.
- Acute myocarditis source rule: sepsis-associated myocarditis and STEMI/ACS mimics are legitimate presentation cases, but blood/urine culture speciation, normal coronary angiography, CMR final read, biopsy/autopsy, and treatment response must stay confirmatory/non-ranking unless testing post-workup diagnosis.
- Focused new-batch fast grid (`RHEUMATIC_FEVER,DIABETIC_KETOACIDOSIS,ACUTE_MYOCARDITIS`) loaded 10 cases and was `10/10 PASS`.
- UI roadmap default after this batch is `D-FAMILIAL-MEDITERRANEAN-FEVER`; completed leaves are filtered out of roadmap presets by the server.
- AP/DKA overlap rule from regression: `ACUTE_PANCREATITIS_HTG_DKA_NO_PAIN_PMC10291989` is not a pure AP single-manifold case. It has CT/lipase/triglyceride evidence for AP and glucose/anion gap/bicarbonate/pH/ketone/HbA1c evidence for DKA, so it is modeled as `D-ACUTE-PANCREATITIS + D-DIABETIC-KETOACIDOSIS`. Do not delete the DKA evidence or force AP single ranking to pass.
- Combo anchor runtime principle: combo eligibility can no longer be hand-coded only for AOSD/sepsis/TTP. `v5_joint_sde_case_test.py` now adds a conservative generic anchor score from disease-owned, high-specificity observed axes while still ignoring generic fever/vitals/inflammation. This is a general mechanism for future true combined manifolds, not a disease-specific AP/DKA patch.
- Horizontal case evidence repair applied to acute pancreatitis cases: rankable imaging findings such as peripancreatic fat stranding, pancreatic edema/enlargement, and peripancreatic fluid collection are mapped into structured axes where the original paper provides them. Final paper diagnosis and treatment response remain non-ranking confirmatory evidence.
- Final ARF/DKA/myocarditis batch regression:
  - Full current-atlas fast grid (`VESMED_SCORE_MODE=grid`, `VESMED_TIME_GRID_N=21`, `VESMED_MAX_COMBO_SIZE=1`): 271 case JSON files loaded; single-manifold validation `266/268 PASS`; combo intentionally off (`0/2`).
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`): `2/2 PASS`, with `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.
  - Remaining single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.

## 2026-05-06 New Batch Memory: FMF / AHTR / Acute Transplant Rejection

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-FAMILIAL-MEDITERRANEAN-FEVER`: familial Mediterranean fever.
  - `D-TRANSFUSION-REACTION-HEMOLYTIC`: acute hemolytic transfusion reaction.
  - `D-TRANSPLANT-REJECTION-ACUTE`: acute transplant rejection.
- New real PMC/PubMed cases:
  - `D-FAMILIAL-MEDITERRANEAN-FEVER`: `PMC9445484`, `PMC3282977`, `PMC9751738`.
  - `D-TRANSFUSION-REACTION-HEMOLYTIC`: `PMC3483495`, `PMC3055152`, `PMC8851284`.
  - `D-TRANSPLANT-REJECTION-ACUTE`: `PMC11398963`, `PMC8790395`, `PMC8305082`.
- FMF source rule: recurrent fever/serositis/acute abdomen/chest attacks/AA amyloid renal presentation can be rankable if observed. MEFV genetics, Tel-Hashomer adjudication, colchicine response, and final paper diagnosis stay confirmatory/non-ranking unless testing post-workup mode.
- Acute hemolytic transfusion reaction source rule: keep this leaf distinct from FNHTR/TRALI/TACO/delayed hemolytic transfusion reaction. Final blood-bank adjudication, antibody ID, crossmatch, DAT/IAT, and treatment response are confirmatory/non-ranking unless the workflow explicitly has post-workup evidence.
- Acute transplant rejection source rule: organ type is context, not part of first-layer disease name. Biopsy/Banff/pathology/C4d/DSA/MMDx/dd-cfDNA/final adjudication stay confirmatory/non-ranking for presentation-only tests. Do not hardcode "transplant = rejection"; infection, drug/CNI toxicity, vascular/obstructive graft complications, sepsis, ALF, myocarditis, and allograft vasculopathy remain real mimics.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-POLYMYOSITIS`. `D-DRESS` was removed as a duplicate candidate because the current active atlas already has `D-DRUG-FEVER-DRESS` for DRESS.
- Focused new-batch fast grid (`FAMILIAL_MEDITERRANEAN_FEVER,TRANSFUSION_REACTION_HEMOLYTIC,TRANSPLANT_REJECTION_ACUTE`) loaded 9 cases and was `9/9 PASS`.
- Full current-atlas fast grid after this batch:
  - 280 case JSON files loaded.
  - Single-manifold validation `275/277 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-07 New Batch Memory: ESBL Bacteremia / CLABSI / HHS

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-ESBL-ENTEROBACTERALES-BACTEREMIA`: ESBL Enterobacterales bacteremia.
  - `D-CENTRAL-LINE-ASSOCIATED-BLOODSTREAM-INFECTION`: central line-associated bloodstream infection.
  - `D-HYPEROSMOLAR-HYPERGLYCEMIC-STATE`: hyperosmolar hyperglycemic state.
- New real PMC/PubMed cases:
  - `D-ESBL-ENTEROBACTERALES-BACTEREMIA`: `PMC6312905` / PMID `30600660`, `PMC6092525` / PMID `30128293`, `PMC8365431` / PMID `34429959`.
  - `D-CENTRAL-LINE-ASSOCIATED-BLOODSTREAM-INFECTION`: `PMC8464211` / PMID `34603589`, `PMC10704788` / PMID `38062360`, `PMC12763422` / PMID `41487767`.
  - `D-HYPEROSMOLAR-HYPERGLYCEMIC-STATE`: `PMC8984746` / PMID `34670070`, `PMC4241748` / PMID `25431711`, `PMC7158592` / PMID `32300498`.
- Resistance-phenotype leaf rule: ESBL bacteremia is not a presentation-only diagnosis. It requires post-microbiology resistance-phenotype evidence. Runtime now supports `distillation_scope.candidate_requires_diagnostic_stage`; `D-ESBL-ENTEROBACTERALES-BACTEREMIA` is only eligible when the case has `diagnostic_stage: "post_microbiology_resistance_phenotype"`. This avoids forcing ordinary sepsis presentations into ESBL while allowing ESBL phenotype, ceftriaxone non-susceptibility, and carbapenem susceptibility to be rankable in explicit post-microbiology tests.
- Legacy case migration: `SEPSIS_ECOLI_PMC6312905_APN_bacteremia` was reclassified to `D-ESBL-ENTEROBACTERALES-BACTEREMIA` because the paper diagnosis and structured observations explicitly identify persistent ESBL-producing E. coli bacteremia; the newer ESBL case from the same PMCID is the better structured version, but both now test the same post-microbiology resistance leaf.
- CLABSI source rule: keep this leaf separate from organism-level bacteremia leaves and source organisms. Central-line presence, differential time to positivity, catheter-tip culture, exit-site/tunnel infection, persistent bacteremia, septic thrombophlebitis, septic embolization, and line removal/source control can be rankable when available. Organism species, susceptibility, and treatment response remain confirmatory/non-ranking unless testing post-workup mode.
- HHS boundary rule: first-layer HHS remains pure. Mixed DKA/HHS, T1DM adolescent HHS, ODS, rhabdomyolysis, stroke, sepsis trigger, and renal failure are context/event axes or future combo/subtype, not disease-name qualifiers.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-TRAPS`.
- Focused new-batch fast grid (`ESBL_ENTEROBACTERALES_BACTEREMIA,CENTRAL_LINE_ASSOCIATED_BLOODSTREAM_INFECTION,HYPEROSMOLAR_HYPERGLYCEMIC_STATE`) loaded 9 cases and was `9/9 PASS`.
- Full current-atlas fast grid after this batch:
  - 335 case JSON files loaded.
  - Single-manifold validation `330/332 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-07 New Batch Memory: TRAPS / CAPS / Aplastic Anemia

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-TRAPS`: TNF receptor-associated periodic syndrome.
  - `D-CAPS`: cryopyrin-associated periodic syndrome.
  - `D-APLASTIC-ANEMIA`: aplastic anemia.
- New real PMC/PubMed cases:
  - `D-TRAPS`: `PMC7606205` / PMID `33154839`, `PMC7865531` / PMID `33530412`, `PMC6441500` / PMID `31007959`.
  - `D-CAPS`: `PMC9918341` / PMID `36765385`, `PMC11961156` / PMID `40171048`, `PMC4943435` / PMID `25766347`, `PMC12312474` / PMID `40757135`.
  - `D-APLASTIC-ANEMIA`: `PMC3048477` / PMID `21324109`, `PMC9289335` / PMID `35860154`, `PMC7981752` / PMID `33768838`.
- Autoinflammatory fever rule: TRAPS/CAPS/FMF/AOSD share fever, rash, myalgia/arthralgia, CRP/SAA/ferritin, serositis, and amyloidosis hazards. Do not make genotype or treatment response rankable in presentation mode. Family history, attack duration/frequency, trigger sensitivity, rash morphology, hearing/eye/CNS/bone findings, and SAA/amyloid organ damage can be rankable when actually observed at presentation.
- CAPS ontology repair from this batch: composite axes were renamed to single-concept axes. `cold_or_stress_triggered_episode_activity_in_D-CAPS` became `trigger_sensitive_episode_activity_in_D-CAPS`; `biologic_hypersensitivity_or_injection_site_intolerance_activity` became `biologic_treatment_intolerance_activity`.
- TRAPS ontology repair from this batch: `injection_reaction_or_biologic_access_barrier_context` became `biologic_treatment_persistence_barrier_context`.
- Marrow-failure boundary rule: aplastic anemia presentation ranking should use CBC/reticulocyte/bleeding/infection evidence. Bone-marrow cellularity, PNH clone, cytogenetics, final diagnosis, treatment response, and long-term outcome stay confirmatory/non-ranking unless explicitly testing post-workup marrow-failure mode.
- Derived CBC pattern rule added from regression: isolated severe thrombocytopenia is a real presentation-level derived lab pattern and must be structured when the case text says Hb/WBC/coagulation are preserved. `isolated_thrombocytopenia_activity` was added to `D-ITP` and `D-HEPARIN-INDUCED-THROMBOCYTOPENIA`, and ITP cases were structured with this observation. This is not an ITP-only patch; it is the fair counterpart to `pancytopenia_activity` in marrow-failure diseases.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-PULMONARY-EMBOLISM`.
- Focused new-batch fast grid (`TRAPS,CAPS,APLASTIC_ANEMIA,ITP,HIT`) loaded 15 cases and was `15/15 PASS`.
- Full current-atlas fast grid after this batch:
  - 345 case JSON files loaded.
  - Single-manifold validation `340/342 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-07 New Batch Memory: PE / Pericarditis / Acute Cholecystitis

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-PULMONARY-EMBOLISM`: pulmonary embolism.
  - `D-PERICARDITIS`: acute pericarditis.
  - `D-ACUTE-CHOLECYSTITIS`: acute cholecystitis.
- New real PMC/PubMed cases:
  - `D-PULMONARY-EMBOLISM`: `PMC9912511` / PMID `36759780`, `PMC5128386` / PMID `27920878`, `PMC6392842` / PMID `29851836`.
  - `D-PERICARDITIS`: `PMC3331659` / PMID `22942636`, `PMC6198527` / PMID `30348082`, `PMC8224196` / PMID `34219937`.
  - `D-ACUTE-CHOLECYSTITIS`: `PMC2729472` / PMID `19707473`, `PMC8921967` / PMID `35350677`, `PMC8214500` / PMID `34164250`.
- Ontology repair from this batch: composite axis names were normalized to umbrella single-concept names:
  - `central_or_saddle_pulmonary_embolus_activity` -> `central_pulmonary_embolus_activity`.
  - `right_atrial_or_ventricular_thrombus_activity` -> `right_heart_thrombus_activity`.
  - `post_cardiac_or_thoracic_injury_context_probability` -> `post_pericardial_injury_context_probability`.
  - `colchicine_intolerance_or_toxicity_risk_context` -> `colchicine_use_limitation_context`.
  - `gallstone_or_biliary_sludge_context_probability` -> `cholelithiasis_sludge_context_probability`.
  - `pain_radiation_to_back_or_right_shoulder_activity` -> `referred_biliary_pain_radiation_activity`.
- PE boundary rule: massive/submassive/provoked/unprovoked/saddle/right-heart-thrombus presentations are severity/location/context axes or future subtype, not disease-name qualifiers. CTPA/VQ/echo/duplex findings can be rankable when available as diagnostic-stage evidence; final diagnosis, treatment response, and long-term outcome remain confirmatory/non-ranking.
- Pericarditis boundary rule: viral/idiopathic/purulent/tuberculous/uremic/post-procedure/myopericarditis remain context/event/risk axes or future related leaves. Positional pleuritic chest pain, rub, diffuse ST elevation, PR depression, inflammatory labs, effusion, and tamponade physiology can be rankable when available.
- Acute cholecystitis boundary rule: calculous/acalculous/emphysematous/gangrenous/perforated presentations stay as spectrum/context/event/source-control axes or future subtype. Ultrasound/CT gallbladder findings can be rankable when presentation-stage imaging is available; operative pathology and treatment response stay confirmatory/non-ranking.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-BRAIN-ABSCESS`.
- Focused new-batch/near-neighbor fast grid (`PULMONARY_EMBOLISM,PERICARDITIS,ACUTE_CHOLECYSTITIS,ACUTE_PANCREATITIS`) loaded 14 cases; single-manifold validation was `13/13 PASS`; the only focused failure was the intentionally single-disabled `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` combo.
- Full current-atlas fast grid after this batch:
  - 354 case JSON files loaded.
  - Single-manifold validation `349/351 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-06 New Batch Memory: Polymyositis / Drug Fever / Alcoholic Hepatitis

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-POLYMYOSITIS`: polymyositis.
  - `D-DRUG-FEVER`: simple drug fever.
  - `D-ALCOHOLIC-HEPATITIS`: alcoholic hepatitis.
- New real PMC/PubMed cases:
  - `D-POLYMYOSITIS`: `PMC9338774`, `PMC4124644`, `PMC8147826`.
  - `D-DRUG-FEVER`: `PMC4964257`, `PMC5073694`, `PMC11166378`.
  - `D-ALCOHOLIC-HEPATITIS`: `PMC10934003`, `PMC11089831`, `PMC10563462`.
- Polymyositis source rule: keep the first-layer leaf pure. Dermatomyositis, antisynthetase syndrome, inclusion-body myositis, and immune-mediated necrotizing myopathy are mimics/context or future leaves. EMG, muscle biopsy, myositis antibodies, final diagnosis, and treatment response stay confirmatory/non-ranking unless testing post-workup mode.
- Simple drug fever source rule: this leaf must not absorb DRESS, SJS/TEN, serotonin syndrome, NMS, malignant hyperthermia, TSS, infection, or drug-induced organ injury. Dechallenge/rechallenge, negative infection workup, final adjudication, and fever resolution after stopping a drug are confirmatory/non-ranking for presentation-only tests.
- Alcoholic hepatitis source rule: acute liver failure, cholangitis, viral hepatitis, DILI, decompensated cirrhosis, pancreatitis, sepsis, and portal vein thrombosis remain mimics/context/event axes, not part of the disease name. Biopsy/final adjudication/treatment response/outcome remain confirmatory/non-ranking.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-TRANSFUSION-REACTION-FNHTR`.
- Focused new-batch fast grid (`POLYMYOSITIS,DRUG_FEVER,ALCOHOLIC_HEPATITIS`) loaded 9 cases and was `9/9 PASS`.
- Full current-atlas fast grid after this batch:
  - 289 case JSON files loaded.
  - Single-manifold validation `284/286 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-06 New Batch Memory: FNHTR / Strep Pyogenes Bacteremia / Pseudomonas Bacteremia

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-TRANSFUSION-REACTION-FNHTR`: febrile non-hemolytic transfusion reaction.
  - `D-STREP-PYOGENES-BACTEREMIA`: Streptococcus pyogenes bacteremia.
  - `D-PSEUDOMONAS-BACTEREMIA`: Pseudomonas aeruginosa bacteremia.
- New real PMC/PubMed cases:
  - `D-TRANSFUSION-REACTION-FNHTR`: `PMC2860765` cases 3/7/11 plus PMID `6837570`.
  - `D-STREP-PYOGENES-BACTEREMIA`: `PMC3122791`, `PMC5622333`, `PMC6370406`.
  - `D-PSEUDOMONAS-BACTEREMIA`: `PMC6531848`, `PMC10931707`, `PMC5080512`.
- FNHTR source rule: keep this leaf separate from acute hemolytic transfusion reaction, delayed hemolytic transfusion reaction, TRALI, TACO, sepsis, and allergic/anaphylactic transfusion reaction. HLA/leukocyte antibody workup, negative hemolysis/TRALI/TACO/sepsis workup, dechallenge, and later tolerance are confirmatory/non-ranking unless testing post-workup mode. Treatment-safety context axes such as `acute_liver_injury_activity` and `respiratory_depression_risk_context` should be explicit `treatment_modifier` axes when referenced by treatments, not phantom references.
- Bacteremia leaf rule: organism-level bacteremia leaves can exist, but source diseases and syndromic complications stay as source/context/event axes or separate leaves. For `D-STREP-PYOGENES-BACTEREMIA`, necrotizing fasciitis, TSS, cellulitis, pneumonia, postpartum sepsis, and endocarditis are not part of the disease name. For `D-PSEUDOMONAS-BACTEREMIA`, central-line infection, neutropenia, pneumonia, UTI, ecthyma gangrenosum, endocarditis, and resistance phenotype are context/risk/treatment modifiers or future leaves.
- Blood-culture species, susceptibility, resistance mechanism, emm typing, and final source adjudication are confirmatory/non-ranking for presentation-only tests unless explicitly testing post-workup mode. Do not hardcode pathogen identity into diagnosis ranking to beat `D-SEPSIS-GN` or other bacteremia leaves.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-ITP`.
- Focused new-batch fast grid (`TRANSFUSION_REACTION_FNHTR,STREP_PYOGENES_BACTEREMIA,PSEUDOMONAS_BACTEREMIA`) loaded 10 cases and was `10/10 PASS`.
- Full current-atlas fast grid after this batch:
  - 299 case JSON files loaded.
  - Single-manifold validation `294/296 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-06 New Batch Memory: ITP / Cellulitis / SBP

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-ITP`: immune thrombocytopenia.
  - `D-CELLULITIS`: cellulitis.
  - `D-SPONTANEOUS-BACTERIAL-PERITONITIS`: spontaneous bacterial peritonitis.
- New real PMC/PubMed cases:
  - `D-ITP`: `PMC10628603` / PMID `37942396`, `PMC5960737` / PMID `29854891`, `PMC6340514` / PMID `30659003`.
  - `D-CELLULITIS`: `PMC2804019` / PMID `20062550`, `PMC11759070` / PMID `39867156`, `PMC12228951` / PMID `40621324`.
  - `D-SPONTANEOUS-BACTERIAL-PERITONITIS`: `PMC7249951` / PMID `32481254`, `PMC8383539` / PMID `34434317`, `PMC8175418` / PMID `34104612`.
- ITP source rule: keep first-layer ITP separate from TTP, DIC, HIT, leukemia/marrow failure, Evans syndrome, SLE-related thrombocytopenia, drug-induced thrombocytopenia, and pregnancy-specific thrombocytopenia. Bone marrow, platelet antibody testing, exclusion workup, treatment response, and final paper diagnosis stay confirmatory/non-ranking unless testing post-workup mode.
- Cellulitis source rule: keep cellulitis separate from erysipelas, necrotizing fasciitis, septic arthritis, osteomyelitis, DVT, vasculitis, contact dermatitis, toxic shock syndrome, and organism-level bacteremia leaves. Blood culture species, susceptibility, final source adjudication, operative findings, and treatment response stay confirmatory/non-ranking for presentation-only tests.
- SBP source rule: keep spontaneous bacterial peritonitis separate from secondary peritonitis, cholangitis, pyelonephritis, acute decompensated cirrhosis without SBP, and organism-specific sepsis. Ascitic PMN/WBC/culture evidence can be rankable when it is presentation paracentesis data; culture species, final source exclusion, and treatment response remain confirmatory/non-ranking unless testing post-workup mode.
- SBP axis-coupling note: ascitic total WBC, neutrophil fraction, and absolute PMN count are a parent/derived measurement triangle. Couplings should keep them numerically coherent without turning the PMN threshold into a hard diagnosis label.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-ASPIRATION-PNEUMONIA`.
- Focused new-batch fast grid (`ITP,CELLULITIS,SPONTANEOUS_BACTERIAL_PERITONITIS`) loaded 12 matching cases and was `12/12 PASS`.
- Full current-atlas fast grid after this batch:
  - 308 case JSON files loaded.
  - Single-manifold validation `303/305 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-06 New Batch Memory: Aspiration Pneumonia / Appendicitis / Diverticulitis

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-ASPIRATION-PNEUMONIA`: aspiration pneumonia.
  - `D-APPENDICITIS`: acute appendicitis.
  - `D-DIVERTICULITIS`: acute diverticulitis.
- New real PMC/PubMed cases:
  - `D-ASPIRATION-PNEUMONIA`: `PMC8666202` / PMID `34934540`, `PMC3790037` / PMID `24101960`, `PMC11835467` / PMID `39968446`.
  - `D-APPENDICITIS`: `PMC10590198` / PMID `37868373`, `PMC11364456` / PMID `39220170`, `PMC12414484` / PMID `40922864`.
  - `D-DIVERTICULITIS`: `PMC9393316` / PMID `36017297`, `PMC6176041` / PMID `30305862`, `PMC10997493` / PMID `38586678`.
- Aspiration pneumonia source rule: keep this leaf separate from ordinary bacterial pneumonia leaves, chemical pneumonitis without infection, lung abscess/empyema, pneumococcal/legionella/mycoplasma pneumonia, PJP, influenza/COVID, pulmonary embolism, and heart failure. Witnessed aspiration, dependent infiltrates, airway material, oxygenation, fever, sputum, and aspiration-risk context can be rankable when present at presentation; culture species, susceptibility, bronchoscopy final interpretation, and treatment response are confirmatory/non-ranking unless testing post-workup mode.
- Appendicitis source rule: keep first-layer appendicitis pure. Perforated, appendicolith-associated, abscess/phlegmon, duplicated appendix, pregnancy, pediatric, right-sided, and elderly presentations are spectrum/context/event axes or future subtype, not disease-name qualifiers. Operative/pathology confirmation and treatment response stay confirmatory/non-ranking.
- Diverticulitis source rule: keep first-layer diverticulitis pure. Uncomplicated/complicated, perforated, abscess, right-sided, cecal, hepatic-flexure, elderly, or immunocompromised presentations are spectrum/context/event/location axes or future subtype. Surgery/pathology/final diagnosis/treatment response remain confirmatory/non-ranking.
- Treatment schema repair from this batch: `D-APPENDICITIS` initially used list-shaped `trajectory_modifications`; main agent normalized these to runtime-readable object-shaped `trajectory_modifications` and preserved the original additive direction/magnitude effects as `push_targets`. This was an engineering schema repair, not a medical ranking patch.
- Axis ontology note: `anorexia_activity` and `anorexia_poor_appetite_activity` are known synonym debt already present before this batch. Do not create additional poor-appetite synonyms; future ontology audit should merge these consistently across disease and case JSON.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-PELVIC-INFLAMMATORY-DISEASE`.
- Focused new-batch fast grid (`ASPIRATION_PNEUMONIA,APPENDICITIS,DIVERTICULITIS`) loaded 9 cases and was `9/9 PASS`.
- Full current-atlas fast grid after this batch:
  - 317 case JSON files loaded.
  - Single-manifold validation `312/314 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-06 New Batch Memory: PID / Acute Prostatitis / Enterococcal Bacteremia

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-PELVIC-INFLAMMATORY-DISEASE`: pelvic inflammatory disease.
  - `D-ACUTE-PROSTATITIS`: acute bacterial prostatitis.
  - `D-ENTEROCOCCAL-BACTEREMIA`: enterococcal bacteremia.
- New real PMC/PubMed cases:
  - `D-PELVIC-INFLAMMATORY-DISEASE`: `PMC12399346` / PMID `40901240`, `PMC11283372` / PMID `39070315`, `PMC3533887` / PMID `23031581`.
  - `D-ACUTE-PROSTATITIS`: `PMC5903498` / PMID `29686573`, `PMC4156639` / PMID `25158781`, `PMC5521102` / PMID `28732492`.
  - `D-ENTEROCOCCAL-BACTEREMIA`: `PMC9340997` / PMID `35899534`, `PMC7768448` / PMID `33158120`, `PMC10324793` / PMID `37427050`.
- PID source rule: first-layer PID remains pure. TOA, ruptured TOA, postpartum context, IUD/post-sterilization, gonococcal/chlamydial etiology, and septic physiology are spectrum/context/event/source-control axes or future related leaves, not disease-name qualifiers. NAAT/culture species, operative/laparoscopic/pathology confirmation, final diagnosis, treatment response, and outcome are confirmatory/non-ranking unless testing post-workup mode.
- Acute prostatitis source rule: first-layer acute bacterial prostatitis remains pure. Prostatic abscess, trauma/instrumentation, urinary retention, MRSA/MSSA/ESBL, bacteremia, and septic shock are context/event/treatment-modifier axes or future subtype/related leaves. Culture species/susceptibility, definitive abscess confirmation, and treatment response stay confirmatory/non-ranking unless available as presentation imaging/lab evidence.
- Enterococcal bacteremia source rule: first-layer enterococcal bacteremia remains pure. Species, VRE/HLAR, dialysis catheter, urinary/biliary/intra-abdominal source, endocarditis, and shock are source/risk/treatment/event axes or related leaves. Blood-culture species, susceptibility, TEE final vegetation, source adjudication, treatment response, and follow-up outcome stay confirmatory/non-ranking for presentation-only ranking.
- Axis ontology repair from this batch: composite axes with `or` were normalized to one-concept axes: `endometritis_activity`, `tubal_fluid_collection_activity`, `extraprostatic_inflammatory_extension_activity`, and `recent_genitourinary_instrumentation_context_probability`. `qt_prolongation_hazard` was added as a real treatment-safety event hazard because PID treatments referenced QT-active drug risk.
- Future scope warning: if `D-TUBO-OVARIAN-ABSCESS`, postpartum endometritis, renal/perinephric abscess, or additional bacteremia/source leaves are added, apply condition-scope checks to avoid double-counting PID/TOA, GU source, and bacteremia facts as both a disease manifold and a background/context modifier.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-ESBL-ENTEROBACTERALES-BACTEREMIA`.
- Focused new-batch fast grid (`PELVIC_INFLAMMATORY_DISEASE,ACUTE_PROSTATITIS,ENTEROCOCCAL_BACTEREMIA`) loaded 9 cases and was `9/9 PASS`.
- Full current-atlas fast grid after this batch:
  - 326 case JSON files loaded.
  - Single-manifold validation `321/323 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-07 New Batch Memory: Brain Abscess / Empyema / Lung Abscess

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-BRAIN-ABSCESS`: brain abscess.
  - `D-EMPYEMA`: pleural empyema.
  - `D-LUNG-ABSCESS`: lung abscess.
- New real PMC/PubMed cases:
  - `D-BRAIN-ABSCESS`: `PMC7857860` / PMID `33536050`, `PMC10454062` / PMID `37623049`, `PMC3970313` / PMID `24693470`.
  - `D-EMPYEMA`: `PMC3716031` / PMID `23882393`, `PMC10406000` / PMID `37554852`, `PMC6350234` / PMID `30723543`.
  - `D-LUNG-ABSCESS`: `PMC6736456` / PMID `31464925`, `PMC9792334` / PMID `36579261`, `PMC7125289` / PMID `32246299`.
- Brain abscess source rule: keep first-layer brain abscess pure. Etiology/source contexts such as hematogenous spread, odontogenic/oropharyngeal source, endovascular septic emboli, pulmonary suppurative infection, sinus/otogenic source, trauma/neurosurgery, Nocardia/fungal context, ventriculitis, hydrocephalus, and mass effect are context/event/source-control axes or separate disease leaves, not disease-name qualifiers. Aspirate culture, operative pathology, TEE after diagnosis, and treatment response are confirmatory/non-ranking unless testing post-workup mode.
- Empyema source rule: keep pleural empyema separate from pneumonia, lung abscess, TB pleuritis, malignant effusion, pulmonary embolism, and subdiaphragmatic abscess. Presentation imaging, pleural fluid gross pus/pH/glucose/loculation, hypoxemia, and source-control need can be rankable when available; culture species, final source adjudication, surgery/pathology, and treatment response stay confirmatory/non-ranking unless testing post-workup mode.
- Lung abscess source rule: keep first-layer lung abscess pure. Aspiration context, anaerobic/actinomycotic/nocardial/fungal pathogens, empyema, bronchopleural fistula, septic emboli, TB/cancer mimic, and drainage failure are context/event/source-control axes or separate leaves. Microbiology, bronchoscopy/pathology, and post-drainage response are confirmatory/non-ranking unless present at the tested stage.
- Axis ontology repair from this batch: composite `_or_` axis IDs were normalized to one-concept names before regression: `neurobehavioral_change_activity`, `language_disturbance_activity`, `odontogenic_oropharyngeal_source_probability_in_D-BRAIN-ABSCESS`, `endovascular_septic_embolic_source_probability_in_D-BRAIN-ABSCESS`, `pulmonary_suppurative_infection_source_probability_in_D-BRAIN-ABSCESS`, `direct_cns_inoculation_context_probability_in_D-BRAIN-ABSCESS`, `right_to_left_cardiac_shunt_context_probability_in_D-BRAIN-ABSCESS`, `atypical_chronic_pathogen_probability_in_D-EMPYEMA`, and `chronic_recurrent_empyema_hazard_in_D-EMPYEMA`.
- Horizontal fairness checks done in focused regression: new brain abscess cases were tested against Nocardia, invasive aspergillosis, toxoplasmosis, bacterial meningitis, HSV encephalitis, infective endocarditis, pneumonia, PE, sepsis, and pyogenic liver abscess; empyema/lung abscess cases were tested against pneumonia, aspiration pneumonia, TB, PE, sepsis, and source-control neighbors. Existing Nocardia CNS abscess case still ranked `D-NOCARDIOSIS`, so the new brain abscess leaf did not steal that organism-level manifold.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-ORBITAL-CELLULITIS`.
- Focused new-batch fast grid (`BRAIN_ABSCESS,EMPYEMA,LUNG_ABSCESS`) loaded 10 matching cases and was `10/10 PASS`.
- Full current-atlas fast grid after this batch:
  - 363 case JSON files loaded.
  - Single-manifold validation `358/360 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-07 New Batch Memory: Orbital Cellulitis / Diabetic Foot Infection / CAUTI

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-ORBITAL-CELLULITIS`: orbital cellulitis.
  - `D-DIABETIC-FOOT-INFECTION`: diabetic foot infection.
  - `D-CATHETER-ASSOCIATED-UTI`: catheter-associated urinary tract infection.
- New real PMC/PubMed cases:
  - `D-ORBITAL-CELLULITIS`: `PMC3168817` / PMID `22567060`, `PMC8047292` / PMID `33884351`, `PMC12211202` / PMID `40598082`.
  - `D-DIABETIC-FOOT-INFECTION`: `PMC10823834` / PMID `38292109`, `PMC10626598` / PMID `37910441`, `PMC9173686` / PMID `35674634`.
  - `D-CATHETER-ASSOCIATED-UTI`: `PMC9682002` / PMID `36439230`, `PMC11458280` / PMID `39376831`, `PMC9081951` / PMID `35541297`.
- Orbital cellulitis source rule: keep first-layer orbital cellulitis separate from preseptal cellulitis, sinusitis, cavernous sinus thrombosis, meningitis, brain abscess, SJS/TEN ocular disease, thyroid orbitopathy, IgG4/GPA orbital disease, and orbital tumor. Presentation-time proptosis, painful/restricted extraocular movement, chemosis, visual acuity, postseptal CT/MRI inflammation, subperiosteal/orbital abscess, and source-control need can be rankable; operative drainage, culture species/susceptibility, final source adjudication, and treatment response stay confirmatory/non-ranking unless testing post-workup mode.
- Diabetic foot infection source rule: keep first-layer DFI separate from generic cellulitis, necrotizing fasciitis, septic arthritis, osteomyelitis-only leaf, ischemia/trauma/gout/DVT, bacteremia/sepsis, and hyperglycemic crisis. Diabetes, neuropathy, PAD, chronic ulcer, wound depth, drainage, gas, deep collection, and foot source-control need can be rankable when presentation evidence exists; culture/susceptibility, operative/pathology confirmation, and treatment response stay confirmatory/non-ranking.
- CAUTI source rule: keep catheter-associated UTI separate from pyelonephritis, acute prostatitis, CLABSI, organism-level bacteremia, asymptomatic bacteriuria/colonization, catheter trauma/obstruction without infection, renal/perinephric abscess, and urosepsis. Catheter/device context, urinary symptoms, pyuria/nitrite/leukocyte esterase/urine WBC, obstruction/retention, and source-control need can be rankable; culture species/susceptibility and final source adjudication remain confirmatory/non-ranking unless testing post-workup mode.
- Axis ontology repair from this batch: composite `_or_` axis IDs were normalized before regression: `periocular_direct_inoculation_context_probability_in_D-ORBITAL-CELLULITIS`, `purulent_periocular_discharge_activity_in_D-ORBITAL-CELLULITIS`, `bone_exposure_sign_presence_in_D-DIABETIC-FOOT-INFECTION`, `urinary_catheter_dysfunction_activity`, `catheter_associated_bladder_wall_abnormality_activity`, `upper_urinary_tract_pain_tenderness_activity`, `catheter_biofilm_pathogen_probability`, and `upper_tract_suppurative_complication_hazard_in_D-CATHETER-ASSOCIATED-UTI`.
- Horizontal fairness notes: DFI introduced diabetes/PAD/neuropathy/chronic ulcer/deep foot infection axes that should be considered for cellulitis, necrotizing fasciitis, septic arthritis, future diabetic foot osteomyelitis, and DKA/HHS when medically true. CAUTI introduced urinary catheter and urine-test axes that should be aligned with pyelonephritis, acute prostatitis, and future asymptomatic bacteriuria/colonization. Orbital cellulitis introduced ocular/orbital axes that should be shared carefully with preseptal cellulitis, sinusitis, cavernous sinus thrombosis, brain abscess/meningitis, SJS/TEN, IgG4/GPA orbital disease, and orbital tumor without letting noninfectious mimics claim bacterial purulence/source-control axes.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-RENAL-ABSCESS`.
- Focused new-batch fast grid (`ORBITAL_CELLULITIS,DIABETIC_FOOT_INFECTION,CATHETER_ASSOCIATED_UTI`) loaded 9 cases and was `9/9 PASS`.
- Full current-atlas fast grid after this batch:
  - 372 case JSON files loaded.
  - Single-manifold validation `367/369 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-07 New Batch Memory: Renal Abscess / TOA / Epididymo-Orchitis

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-RENAL-ABSCESS`: renal abscess.
  - `D-TUBO-OVARIAN-ABSCESS`: tubo-ovarian abscess.
  - `D-EPIDIDYMO-ORCHITIS`: epididymo-orchitis.
- Real PMC/PubMed cases:
  - `D-RENAL-ABSCESS`: `PMC10822679` / PMID `38283446`, `PMC10704059` / PMID `38077678`, `PMC8170294` / PMID `34104703`.
  - `D-TUBO-OVARIAN-ABSCESS`: `PMC12399346` / PMID `40901240`, `PMC3533887` / PMID `23031581`, `PMC11283372` / PMID `39070315`.
  - `D-EPIDIDYMO-ORCHITIS`: `PMC7160564` / PMID `32322510`, `PMC9837258` / PMID `36643286`, `PMC7402548` / PMID `32775073`.
- Ontology note: three older PID case files using the same TOA PMCs were removed and replaced by the `D-TUBO-OVARIAN-ABSCESS` leaf versions. This is not a ranking patch: once TOA is an independent first-layer leaf, PID complicated by a formed tubo-ovarian abscess should resolve to the more specific TOA manifold when abscess evidence is present.
- Renal abscess source rule: keep first-layer renal abscess separate from pyelonephritis, perinephric abscess, renal cyst/tumor, bacteremia/endocarditis, and urosepsis. Flank/CVA findings, renal rim-enhancing lesion, abscess size/count/liquefaction, pyuria/culture context, obstruction, and source-control need can be rankable when present; culture species, aspirate result, procedure success, and post-drainage response stay confirmatory/non-ranking unless testing post-workup mode.
- TOA source rule: keep first-layer TOA separate from PID without abscess, postpartum endometritis, septic abortion, appendicitis, diverticulitis, ovarian torsion/tumor, ectopic pregnancy, and generic sepsis. Complex adnexal mass, abscess size, pelvic tenderness, peritonitis/rupture, and source-control need can be rankable; operative/pathology confirmation, culture species, and treatment response stay confirmatory/non-ranking unless testing post-workup mode.
- Epididymo-orchitis source rule: keep first-layer epididymo-orchitis separate from testicular torsion, Fournier gangrene, acute prostatitis, CAUTI/UTI, testicular tumor, hernia, and STI organism-level labels. Scrotal pain/swelling/tenderness, epididymal/testicular Doppler findings, pyuria/urine context, STI/instrumentation context, abscess/ischemia hazards, and source-control need can be rankable when presentation evidence exists; culture species, operative pathology, and treatment response stay confirmatory/non-ranking.
- Axis ontology repair from this batch: composite or phantom references were normalized before regression: `retroperitoneal_back_pain_activity_in_D-RENAL-ABSCESS`, `contiguous_extrarenal_extension_hazard_in_D-RENAL-ABSCESS`, `procedural_bleeding_risk_context_activity`, `atypical_granulomatous_pathogen_context_probability`, and `severe_beta_lactam_reaction_history_activity`.
- Horizontal fairness notes: renal/perinephric abscess, pyelonephritis, CAUTI, prostatitis, endocarditis, and S. aureus bacteremia share GU-source and hematogenous-seeding evidence; TOA/PID/postpartum/septic-abortion leaves share pelvic inflammatory axes but must avoid double-counting PID and formed abscess as the same fact; epididymo-orchitis shares urinary/STI/instrumentation axes with prostatitis/CAUTI/PID and future torsion/Fournier/tumor mimics.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-POSTPARTUM-ENDOMETRITIS`.
- Focused new-batch grid (`RENAL_ABSCESS,TUBO_OVARIAN_ABSCESS,EPIDIDYMO_ORCHITIS`) loaded 9 cases and was `9/9 PASS`.
- Full current-atlas grid after this batch:
  - 378 unique case JSON files loaded.
  - Single-manifold validation `373/375 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-07 New Batch Memory: Postpartum Endometritis / Perinephric Abscess / Septic Abortion

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-POSTPARTUM-ENDOMETRITIS`: postpartum endometritis.
  - `D-PERINEPHRIC-ABSCESS`: perinephric abscess.
  - `D-SEPTIC-ABORTION`: septic abortion.
- Real PMC/PubMed cases:
  - `D-POSTPARTUM-ENDOMETRITIS`: `PMC6615581` / PMID `31312545`, `PMC6500617` / PMID `31139481`, `PMC8384018` / PMID `34485067`.
  - `D-PERINEPHRIC-ABSCESS`: `PMC9979943` / PMID `36896437`, `PMC9803770` / PMID `36593858`, `PMC6707826` / PMID `31497419`.
  - `D-SEPTIC-ABORTION`: `PMC12811538` / PMID `41551360`, `PMC10083041` / PMID `37041893`, `PMC5692239` / PMID `29188070`.
- Postpartum endometritis source rule: keep first-layer postpartum endometritis separate from PID, TOA, septic abortion, pyelonephritis, CAUTI, appendicitis, diverticulitis, toxic shock syndrome, streptococcal bacteremia, and generic sepsis. Postpartum timing, uterine tenderness, lochia abnormality, pelvic pain, endomyometrial inflammation/necrosis, and source-control need can be rankable when present; culture species, operative/pathology confirmation, and treatment response remain confirmatory/non-ranking unless testing post-workup mode.
- Perinephric abscess source rule: keep first-layer perinephric abscess separate from renal abscess, pyelonephritis, CAUTI, renal cyst/tumor/hematoma/urinoma, bacteremia/endocarditis, appendicitis/diverticulitis, and generic sepsis. Perinephric collection, capsular/retroperitoneal extension, renal mass effect, pyuria/urinary obstruction context, imaging source-control need, and adjacent-organ complications can be rankable; aspirate culture, procedure success, and post-drainage response stay confirmatory/non-ranking unless testing post-workup mode.
- Septic abortion source rule: keep first-layer septic abortion separate from postpartum endometritis, PID, TOA, retained products without infection, ectopic pregnancy, toxic shock syndrome, DIC, and generic sepsis. Recent pregnancy termination/loss context, uterine tenderness, retained infected products, foul discharge/bleeding, shock, DIC, necrotizing myometritis, and source-control need can be rankable; culture species, surgical pathology, and treatment response remain confirmatory/non-ranking unless testing post-workup mode.
- Axis ontology repair from this batch: composite `_or_` and typo axes were normalized before regression: `intrapartum_ascending_infection_risk_context_activity`, `recent_urinary_tract_device_instrumentation_context_probability_in_D-PERINEPHRIC-ABSCESS`, `renal_mass_effect_activity_in_D-PERINEPHRIC-ABSCESS`, `peritoneal_extension_pyoperitoneum_activity_in_D-PERINEPHRIC-ABSCESS`, `perinephric_noninfectious_fluid_collection_context_activity_in_D-PERINEPHRIC-ABSCESS`, `abscess_breach_fistulization_hazard_in_D-PERINEPHRIC-ABSCESS`, `recent_pregnancy_termination_loss_context_activity`, `intrauterine_free_gas_activity`, `necrotizing_myometritis_hazard_in_D-SEPTIC-ABORTION`, and `vascular_erosion_mycotic_aneurysm_hazard_in_D-PERINEPHRIC-ABSCESS`. Missing treatment-context axes such as beta-lactam allergy, renal-dose adjustment need, MRSA coverage need, carbapenem susceptibility, and antifungal/Candida glabrata coverage context were added where treatments referenced them.
- Horizontal fairness notes: postpartum endometritis, septic abortion, PID, TOA, pyelonephritis/CAUTI, and abdominal surgical mimics share pelvic/urinary/intra-abdominal fever axes; renal and perinephric abscess leaves share GU-source, obstruction, imaging collection, source-control, and bacteremia-seeding evidence. When adding future PJI, CRE Enterobacterales bacteremia, viral meningitis, and encephalitis leaves, re-check shared fever, source-control, hardware/device, CNS, resistant-organism, and treatment-coverage axes rather than giving one leaf exclusive explanatory power.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-PROSTHETIC-JOINT-INFECTION`.
- Current atlas count after this batch: 139 disease manifolds and 387 real case JSON files.
- Focused new-batch grid (`POSTPARTUM_ENDOMETRITIS,PERINEPHRIC_ABSCESS,SEPTIC_ABORTION`) loaded 9 cases and was `9/9 PASS`.
- Full current-atlas grid after this batch:
  - 387 case JSON files present; 384 single-manifold cases and 2 combo cases were scorable in this run.
  - Single-manifold validation `382/384 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-07 New Batch Memory: PJI / Viral Meningitis / CRE Enterobacterales Bacteremia

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-PROSTHETIC-JOINT-INFECTION`: prosthetic joint infection.
  - `D-VIRAL-MENINGITIS`: viral meningitis.
  - `D-CRE-ENTEROBACTERALES-BACTEREMIA`: carbapenem-resistant Enterobacterales bacteremia. This replaces the broader roadmap wording `Carbapenem-resistant Enterobacterales infection`, which was too umbrella-like for a first-layer leaf.
- Real PMC/PubMed cases:
  - `D-PROSTHETIC-JOINT-INFECTION`: `PMC10469548` / PMID `37662443`, `PMC7269968` / PMID `32518752`, `PMC5496303` / PMID `28706395`.
  - `D-VIRAL-MENINGITIS`: `PMC12682333` / PMID `41362530`, `PMC6115539` / PMID `30167375`, `PMC12475911` / PMID `41018432`.
  - `D-CRE-ENTEROBACTERALES-BACTEREMIA`: `PMC4576028` / PMID `26386029`, `PMC7242868` / PMID `32461908`, `PMC4802673` / PMID `27051575`.
- PJI source rule: keep first-layer PJI separate from native septic arthritis, vertebral osteomyelitis, cellulitis, diabetic foot infection, aseptic loosening, mechanical failure, generic bacteremia, and generic sepsis. Prosthesis presence, joint pain/swelling, sinus tract/drainage, synovial WBC/PMN, periprosthetic collection/gas/loosening, implant-retention feasibility, and source-control need can be rankable; culture species, operative pathology, definitive revision outcome, and treatment response remain confirmatory/non-ranking unless testing post-workup mode.
- Viral meningitis source rule: keep first-layer viral meningitis separate from HSV encephalitis, bacterial meningitis, autoimmune encephalitis, VZV encephalitis, West Nile neuroinvasive disease, sepsis, migraine, and drug-induced aseptic meningitis. CSF lymphocytic pleocytosis, normal/near-normal glucose, headache/photophobia/meningismus, viral PCR context, rash/parotitis/genital-herpes context, and low brain-parenchymal injury can be rankable when present. Encephalitic deficits, temporal lobe hemorrhage/edema, seizures, and focal brain MRI should pull toward encephalitis leaves when they are structured.
- CRE Enterobacterales bacteremia source rule: keep this bloodstream leaf separate from CRE UTI/pneumonia without bacteremia, ESBL bacteremia, Pseudomonas/Enterococcus/S. aureus bacteremia, CLABSI source leaf, generic sepsis, and septic shock. KPC/NDM/OXA-48/VIM/IMP, active coverage, source site, catheter/device context, prior carbapenem exposure, colonization/outbreak context, renal dosing, and source-control adequacy are treatment-context/risk/source axes, not disease-name qualifiers.
- Runtime evidence-loader fix from this batch: `v5_joint_sde_case_test.py` now consumes `mapped_axes` arrays in mapped evidence sections and includes `clinical_course_events` as rankable mapped evidence when not explicitly `use_in_ranking: false`. For duplicate 0-1 activity/probability/hazard axes, later or stronger positive mapped evidence can replace an earlier negative value. Root cause: the existing HSV-2 encephalitis hemorrhage case stored day-7 altered mental status, focal deficit, temporal hemorrhage, and mass effect in `clinical_course_events` / `imaging.mapped_axes`, but runtime only used day-0 observations and ignored those structured fields; viral meningitis therefore won on a meningitis-like initial CSF phenotype. This is a generic evidence ingestion fix, not a disease-specific ranking patch.
- Axis ontology repair from this batch: composite mechanism/axis identifiers were normalized before regression, including `M_PJI_ENTRY_PORTAL_ACTIVITY`, `M_PJI_WOUND_COMMUNICATION_ACTIVITY`, `M_PJI_SYSTEMIC_SPILLOVER_ACTIVITY`, `M_PJI_PERSISTENT_INFECTION_ACTIVITY`, `recent_joint_implant_surgery_context_activity_in_D-PROSTHETIC-JOINT-INFECTION`, `M_CRE_EB_CARBAPENEM_RESISTANCE_ACTIVITY`, `postoperative_deep_surgical_site_source_probability`, `endovascular_infection_hazard_in_D-CRE-ENTEROBACTERALES-BACTEREMIA`, `M_VIRAL_MENINGITIS_MENINGEAL_VIRAL_INVASION_ACTIVITY`, and `M_VIRAL_MENINGITIS_RECURRENT_HERPESVIRUS_ACTIVITY`.
- Horizontal fairness notes: PJI and native septic arthritis should share synovial-fluid and local joint inflammation axes but not double-count prosthesis/biofilm facts; viral meningitis, HSV/VZV encephalitis, bacterial meningitis, brain abscess, autoimmune encephalitis, and West Nile disease need shared CNS symptoms/CSF/imaging axes with parenchymal injury used to separate meningitis from encephalitis; CRE/ESBL/CLABSI/UTI/abscess/bacteremia leaves need shared active-coverage, carbapenemase, catheter/source-control, and renal-dose treatment-context axes.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-ERYSIPELAS`.
- Current atlas count after this batch: 142 disease manifolds and 396 real case JSON files.
- Focused new-batch grid (`PROSTHETIC_JOINT_INFECTION,VIRAL_MENINGITIS,CRE_ENTEROBACTERALES_BACTEREMIA,HSV_ENCEPHALITIS_HSV2_HEMORRHAGE`) loaded 10 cases and was `10/10 PASS`.
- Full current-atlas grid after this batch:
  - 396 case JSON files present; 393 single-manifold cases and 2 combo cases were scorable in this run.
  - Single-manifold validation `391/393 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-07 New Batch Memory: Erysipelas / Autoimmune Encephalitis / VZV Encephalitis

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-ERYSIPELAS`: erysipelas.
  - `D-AUTOIMMUNE-ENCEPHALITIS`: autoimmune encephalitis.
  - `D-VZV-ENCEPHALITIS`: varicella-zoster virus encephalitis.
- Real PMC/PubMed cases:
  - `D-ERYSIPELAS`: `PMC11257657` / PMID `39027802`, `PMC12488269` / PMID `41041112`, `PMC12626943` / PMID `41268563`.
  - `D-AUTOIMMUNE-ENCEPHALITIS`: `PMC5078958` / PMID `27776544`, `PMC5747773` / PMID `29103007`, `PMC8798333` / PMID `35116439`.
  - `D-VZV-ENCEPHALITIS`: `PMC6861030` / PMID `31763593`, `PMC4335817` / PMID `25738170`, `PMC4017713` / PMID `24864218`.
- Erysipelas source rule: keep first-layer erysipelas separate from cellulitis, necrotizing fasciitis, diabetic foot infection, zoster, DRESS/SJS/TEN, septic arthritis, toxic shock syndrome, streptococcal bacteremia, and generic sepsis. Sharply demarcated raised superficial erythema, dermal lymphatic pattern, skin barrier portal, chronic edema/lymphedema, bullous or hemorrhagic superficial lesions, and bacteremic/shock hazards can be rankable when present; culture organism and response to antibiotics remain confirmatory/non-ranking unless testing post-workup mode.
- Autoimmune encephalitis source rule: keep first-layer autoimmune encephalitis as a stable syndrome leaf covering anti-NMDAR/LGI1/CASPR2/GABAB and related contexts, but do not mix HSV/VZV encephalitis, viral/bacterial meningitis, brain abscess, CNS lupus, sarcoidosis/Behcet CNS disease, toxic-metabolic delirium, or primary psychiatric disease into the disease name. Antibody type, tumor/teratoma context, FBDS, hyponatremia/SIADH, CSF/MRI/EEG, and immunotherapy context are axes or future subtypes.
- VZV encephalitis source rule: keep VZV brain-parenchymal/CNS disease separate from VZV meningitis without encephalitis, HSV encephalitis, viral meningitis, West Nile neuroinvasive disease, autoimmune encephalitis, bacterial meningitis, brain abscess, stroke/vasculopathy without encephalitis, zoster skin disease alone, and sepsis. Rash may be absent; immunosuppression, vasculopathy/stroke, CSF VZV PCR/intrathecal antibody, MRI lesions, seizures/focal deficits, and active antiviral coverage are axes/context, not extra disease-name qualifiers.
- Runtime/case-structure repair from this batch:
  - `v5_joint_sde_case_test.py` now uses `log10(1+x)` only for zero-inclusive CSF log axes. The first broad attempt applied this to all zero-inclusive log axes and regressed hematology cases; it was narrowed after evidence showed the true numerical pathology was CSF zero-cell counts.
  - `D-HSV-ENCEPHALITIS` was missing real CSF HSV PCR axes. Added `csf_viral_pcr_positivity`, `csf_hsv_pcr_positivity`, `csf_hsv1_pcr_positivity`, and `csf_hsv2_pcr_positivity`, with mechanism edges from CNS HSV replication.
  - Existing HSV encephalitis case microbiology was structured into those PCR axes. This fixed `HSV_ENCEPHALITIS_NORMAL_CSF_PMC4717694`, where HSV-1 PCR positivity and temporal/limbic MRI were real evidence but normal CSF cell counts previously over-penalized HSV.
  - Existing disseminated cryptococcosis meningitis/fungemia case microbiology was mapped into existing cryptococcal culture/antigen axes (`csf_culture_positivity`, `blood_culture_positivity_probability`, `csf_cryptococcal_antigen_titer`, `serum_cryptococcal_antigen_titer`, `tissue_cryptococcus_detection_probability`). This fixed a VZV encephalitis steal caused by unconsumed fungal microbiology evidence.
- Axis ontology repair from this batch: composite `_or_` names were normalized before regression, including `erysipelas_truncal_involvement_activity_in_D-ERYSIPELAS`, `chronic_edema_context_activity`, `non_gas_pathogen_probability_in_D-ERYSIPELAS`, `M_ERYSIPELAS_SYSTEMIC_SPILLOVER_ACTIVITY`, `M_ERYSIPELAS_DELAYED_EFFECTIVE_THERAPY_ACTIVITY`, `catatonic_unresponsiveness_activity`, `brain_mri_nonspecific_activity_in_D-AUTOIMMUNE-ENCEPHALITIS`, `eeg_slowing_activity`, `acute_psychiatric_activation_activity`, `mri_posterior_fossa_lesion_activity_in_D-VZV-ENCEPHALITIS`, `mri_cns_surface_enhancement_activity_in_D-VZV-ENCEPHALITIS`, `advanced_hiv_immunodeficiency_activity`, `M_VZV_NEUROINVASION_ACTIVITY`, and `M_VZV_INADEQUATE_ANTIVIRAL_EXPOSURE_ACTIVITY`. VZV also gained the treatment-referenced `oxygen_saturation` vital axis.
- Horizontal fairness notes: SSTI leaves should share bullous/hemorrhagic lesion, barrier disruption, edema/lymphedema, shock, and source-control axes where medically true, while sharply demarcated raised border and superficial lymphatic pattern stay more erysipelas-specific. CNS leaves need shared CSF/MRI/EEG/seizure/mental-status axes, but pathogen-specific PCR/antigen/antibody and parenchymal injury evidence must be structured instead of left as text. Opportunistic CNS infections in transplant/HIV hosts need microbiology axes consumed before ranking against VZV/AE.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-WEST-NILE-NEUROINVASIVE-DISEASE`.
- Current atlas count after this batch: 145 disease manifolds and 405 real case JSON files.
- Focused new-batch grid (`ERYSIPELAS,AUTOIMMUNE_ENCEPHALITIS,VZV_ENCEPHALITIS,HSV_ENCEPHALITIS_NORMAL_CSF`) loaded 10 cases and was `10/10 PASS`.
- Full current-atlas grid after this batch:
  - 405 case JSON files present; 402 single-manifold cases and 2 combo cases were scorable in this run.
  - Single-manifold validation `400/402 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` -> `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` -> `D-ALCL`.
  - Separate combo run (`VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.

## 2026-05-07 New Batch Memory: West Nile / Dengue / Chikungunya

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-WEST-NILE-NEUROINVASIVE-DISEASE`: West Nile neuroinvasive disease.
  - `D-DENGUE`: dengue.
  - `D-CHIKUNGUNYA`: chikungunya.
- Real PMC/PubMed cases:
  - `D-WEST-NILE-NEUROINVASIVE-DISEASE`: `PMC3121680`, `PMC5039274`, `PMC4899671`.
  - `D-DENGUE`: `PMC9090125`, `PMC6206890`, `PMC6082042`.
  - `D-CHIKUNGUNYA`: `PMC7304265`, `PMC6979562`, `PMC6614379`.
- West Nile source rule: keep neuroinvasive WNV separate from viral meningitis, HSV/VZV encephalitis, autoimmune encephalitis, bacterial meningitis, and generic arboviral fever. Encephalitis/meningitis/myelitis pattern, flaccid paralysis, CSF, MRI, immunosuppression, and mosquito/season context are axes or context, not extra disease-name qualifiers.
- Dengue source rule: keep first-layer dengue pure. DHF/DSS, severe dengue, dengue hepatitis, AKI, bleeding, pregnancy, and serotype/travel context are event/risk/source axes or future subtypes, not disease-name qualifiers.
- Chikungunya source rule: keep first-layer chikungunya pure. Acute febrile polyarthralgia, rash, chronic arthritis, neurologic disease, severe skin disease, and travel/vector context are axes or future subtypes, not disease-name qualifiers.
- Horizontal fairness notes: arboviral leaves must share fever, rash, thrombocytopenia, transaminitis, CNS, arthralgia, travel/vector, and exposure axes where medically true. Dengue-specific capillary leak/hemorrhage and chikungunya-specific severe arthralgia/chronic arthritis should not be claimed by generic viral fever leaves unless clinically true.
- UI roadmap after this batch: completed leaves are active; default next candidate became `D-MEASLES`.
- Current atlas count after this batch: 147 disease manifolds and 414 real case JSON files.
- Focused new-batch grid (`WEST_NILE,DENGUE,CHIKUNGUNYA`) was `9/9 PASS`.
- Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) remained `2/2 PASS`.

## 2026-05-07 New Batch Memory: Measles / Acute Hepatitis A / Acute Hepatitis B

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-MEASLES`: measles.
  - `D-ACUTE-HEPATITIS-A`: acute hepatitis A.
  - `D-ACUTE-HEPATITIS-B`: acute hepatitis B.
- Real PMC/PubMed cases:
  - `D-MEASLES`: `PMC6910791`, `PMC10625051`, `PMC7308916`.
  - `D-ACUTE-HEPATITIS-A`: `PMC3784234`, `PMC3482082`, `PMC10238316`.
  - `D-ACUTE-HEPATITIS-B`: `PMC2783051`, `PMC3103261`, `PMC8163517`.
- Measles source rule: keep first-layer measles pure. Pneumonia, encephalitis, SSPE, immunosuppression, vaccine failure, pregnancy, and outbreak context are axes/risk/event contexts or future subtypes, not disease-name qualifiers.
- HAV/HBV source rule: keep acute hepatitis A and acute hepatitis B separate leaves. Fulminant hepatitis, cholestatic pattern, renal failure, extrahepatic immune manifestations, pregnancy, chronic HBV, reactivation, and coinfection are axes/risk/event contexts or future subtypes.
- Serology/final diagnosis rule: pathogen serology can be rankable only when it is available at the tested clinical stage. Final diagnosis labels, treatment response, and follow-up outcome remain confirmatory/non-ranking unless testing post-workup mode.
- Horizontal fairness notes: viral exanthem and viral hepatitis leaves must share fever/rash/transaminitis/bilirubin/coagulation/encephalopathy axes where true. Hepatitis-specific serology should separate HAV/HBV/HEV/EBV/CMV and drug-induced hepatitis without deleting nonspecific liver-injury evidence from mimics.
- UI roadmap after this batch: completed leaves are active; default next candidate became `D-ACUTE-HEPATITIS-E`.
- Current atlas count after this batch: 150 disease manifolds and 423 real case JSON files.
- Focused new-batch grid (`MEASLES,ACUTE_HEPATITIS_A,ACUTE_HEPATITIS_B`) was `9/9 PASS`.
- Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) remained `2/2 PASS`.

## 2026-05-07 New Batch Memory: Acute Hepatitis E / Amoebic Liver Abscess / Strongyloides Hyperinfection

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-ACUTE-HEPATITIS-E`: acute hepatitis E.
  - `D-AMOEBIC-LIVER-ABSCESS`: amoebic liver abscess.
  - `D-STRONGYLOIDES-HYPERINFECTION`: Strongyloides hyperinfection.
- Real PMC/PubMed cases:
  - `D-ACUTE-HEPATITIS-E`: `PMC10719760`, `PMC10961495`, `PMC6795373`.
  - `D-AMOEBIC-LIVER-ABSCESS`: `PMC12512644`, `PMC10874467`, `PMC8909445`.
  - `D-STRONGYLOIDES-HYPERINFECTION`: `PMC7157694`, `PMC6439959`, `PMC6992991`.
- HEV source rule: keep first-layer acute hepatitis E pure. Pregnancy, immunosuppression, chronic HEV, fulminant hepatitis, neurologic/renal manifestations, and zoonotic/travel context are axes/risk/event contexts or future subtypes.
- Amoebic liver abscess source rule: keep first-layer amoebic liver abscess separate from pyogenic liver abscess, echinococcosis, hepatocellular tumor, biliary infection, and generic sepsis. Solitary right-lobe abscess, travel/enteric exposure, serology/antigen, pleuropulmonary extension, rupture hazard, and drainage need are axes/context; final aspirate/microbiology and response remain confirmatory/non-ranking unless available at the tested stage.
- Strongyloides hyperinfection source rule: keep hyperinfection separate from uncomplicated strongyloidiasis, eosinophilic disorders, bacterial pneumonia/sepsis, meningitis, and GI bleeding mimics. Steroid/HTLV/immunosuppression context, larval burden, pulmonary/GI dissemination, enteric bacteremia, eosinophil suppression, and septic complications are axes/risk/event contexts.
- Runtime/axis repair from this batch: oxygen requirement and hypoxemia evidence were added horizontally across invasive bloodstream infection, sepsis, pneumonia, and near-neighbor severe infection leaves after a transient ESBL bacteremia case steal by Nocardiosis exposed missing respiratory-severity evidence. This was a horizontal fairness fix, not a one-case patch.
- Horizontal fairness notes: hepatitis leaves share liver injury/synthetic dysfunction/encephalopathy axes; liver abscess leaves share imaging collection, source-control, rupture, pleuropulmonary extension, and sepsis axes; strongyloides, nocardiosis, aspergillosis, TB, bacterial sepsis, and pneumonia leaves share immunosuppression and pulmonary/systemic severity axes where true.
- UI roadmap after this batch: completed leaves are active; default next candidate became `D-TRICHINELLOSIS`.
- Current atlas count after this batch: 153 disease manifolds and 432 real case JSON files.
- Focused new-batch grid (`ACUTE_HEPATITIS_E,AMOEBIC_LIVER_ABSCESS,STRONGYLOIDES_HYPERINFECTION`) was `9/9 PASS`.
- Full current-atlas grid at this point was `427/429 PASS` for single-manifold cases; the unchanged failures remained the accepted antisynthetase/DLBCL and Hodgkin/ALCL presentation-only ambiguities.
- Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) remained `2/2 PASS`.

## 2026-05-07 New Batch Memory: Trichinellosis / IgA Vasculitis / Cryoglobulinemic Vasculitis

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-TRICHINELLOSIS`: trichinellosis.
  - `D-IGA-VASCULITIS`: IgA vasculitis.
  - `D-CRYOGLOBULINEMIC-VASCULITIS`: cryoglobulinemic vasculitis.
- Real PMC/PubMed cases:
  - `D-TRICHINELLOSIS`: `PMC7392432`, `PMC11117173`, `PMC3326967`.
  - `D-IGA-VASCULITIS`: `PMC6739011`, `PMC5384843`, `PMC8043251`.
  - `D-CRYOGLOBULINEMIC-VASCULITIS`: `PMC8519709`, `PMC5413707`, `PMC11144169`.
- Trichinellosis source rule: keep first-layer trichinellosis pure. Food exposure, eosinophilia, myositis, periorbital edema, fever, diarrhea, myocarditis, CNS disease, and respiratory compromise are axes/risk/event contexts, not disease-name qualifiers.
- IgA vasculitis source rule: keep first-layer IgA vasculitis separate from ANCA vasculitis, cryoglobulinemic vasculitis, HUS/TTP, SLE nephritis, septic emboli, drug rash, and meningococcemia. Palpable purpura, arthralgia, abdominal pain/GI bleeding, nephritis, IgA biopsy context, and renal hazard are axes/context.
- Cryoglobulinemic vasculitis source rule: keep first-layer cryoglobulinemic vasculitis separate from IgA vasculitis, ANCA vasculitis, SLE, lymphoma fever, hepatitis-associated hepatitis leaves, and nonspecific neuropathy/renal disease. HCV/lymphoproliferative context, low C4, cryoglobulins, purpura, MPGN, neuropathy, ischemic lesions, and hyperviscosity/renal hazards are axes/context.
- Horizontal fairness notes: small-vessel vasculitis leaves must share purpura, renal, neuropathy, GI, complement, autoantibody, and biopsy axes where true. Do not give one vasculitis leaf exclusive credit for generic purpura/nephritis; separation should come from disease-specific serology, complement pattern, organ distribution, and mechanism.
- UI roadmap after this batch: completed leaves are active; default next candidate became `D-URTICARIAL-VASCULITIS`.
- Current atlas count after this batch: 156 disease manifolds and 441 real case JSON files.
- Focused new-batch grid (`TRICHINELLOSIS,IGA_VASCULITIS,CRYOGLOBULINEMIC_VASCULITIS`) was `9/9 PASS`.
- Full current-atlas grid at this point was `436/438 PASS` for single-manifold cases; the unchanged failures remained the accepted antisynthetase/DLBCL and Hodgkin/ALCL presentation-only ambiguities.
- Separate combo run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) remained `2/2 PASS`.

## 2026-05-07 New Batch Memory: Urticarial Vasculitis / MCTD / Systemic Sclerosis Renal Crisis

- The next loop again used one `xhigh` worker per disease, with disjoint write scopes:
  - `D-URTICARIAL-VASCULITIS`: urticarial vasculitis.
  - `D-MIXED-CONNECTIVE-TISSUE-DISEASE`: mixed connective tissue disease.
  - `D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS`: systemic sclerosis renal crisis.
- Real PMC/PubMed cases:
  - `D-URTICARIAL-VASCULITIS`: `PMC2650979` / PMID `19270838`, `PMC6203196` / PMID `30359231`, `PMC11580351` / PMID `39575061`.
  - `D-MIXED-CONNECTIVE-TISSUE-DISEASE`: `PMC5208556` / PMID `28083450`, `PMC11466346` / PMID `39399181`, `PMC7303452` / PMID `32418955`.
  - `D-SYSTEMIC-SCLEROSIS-RENAL-CRISIS`: `PMC5720533` / PMID `29318207`, `PMC10589050` / PMID `37868671`, `PMC10198668` / PMID `37214048`.
- Urticarial vasculitis source rule: keep first-layer urticarial vasculitis separate from ordinary urticaria, serum sickness, SLE, cryoglobulinemic vasculitis, IgA vasculitis, ANCA vasculitis, infection-triggered urticaria, and drug eruption. Lesions lasting over 24 hours, residual hyperpigmentation/purpura, hypocomplementemia, leukocytoclastic vasculitis, angioedema, renal/pulmonary/systemic involvement, and complement/anti-C1q context are axes/context.
- MCTD source rule: keep first-layer MCTD separate from SLE, systemic sclerosis, polymyositis/dermatomyositis, antisynthetase syndrome, Sjogren disease, and overlap labels that do not have the MCTD anti-U1-RNP phenotype. Raynaud, swollen hands, synovitis, myositis, sclerodactyly, ILD/PAH, anti-U1-RNP, ANA, and chronic overlap organ involvement are axes/context, not extra disease-name qualifiers.
- SRC source rule: keep systemic sclerosis renal crisis as a specific emergency leaf, not generic AKI/hypertensive emergency/TMA. Abrupt hypertension, rapidly rising creatinine, renin-angiotensin activation, microangiopathic hemolysis, thrombocytopenia, proteinuria/hematuria, systemic sclerosis context, steroid exposure, ACE-inhibitor treatment response context, dialysis hazard, and mortality hazard are axes/context.
- Runtime evidence-loader repair from this batch: `v5_joint_sde_case_test.py` now accepts risk-factor `modulation` written either as a dict or a list. Root cause was structurally valid distillation output using list-form modulation where runtime expected dict.
- Runtime qualitative-evidence repair from this batch: qualitative positive/negative observations now map generically by axis type. Negative evidence maps to 0 for probability/severity/presence axes and to a low finite value for log measurements; positive evidence maps to 1 for probability/severity/presence axes and otherwise to an appropriate disease-range midpoint. This prevents qualitative "negative" serology from becoming a pathological numeric zero on log axes.
- Background/base-measure repair from this batch: antibody/self-antibody/Coombs missing-axis fallback now has healthy-negative base ranges instead of inheriting disease-positive baselines from autoimmune leaves. Example policy: probability/relative axes default near 0-0.05, assay/index axes near 0-0.9, IU/U/mL axes near 0-10 with log-safe lower bound, and ANA reciprocal near 1-80 when log-scaled.
- MCTD distillation repair was medical and generalizable, not a ranking patch:
  - Chronic autoantibody axes and mechanisms such as anti-RNP/U1-RNP/ANA/anti-Sm/SSA should be present from presentation or persistent when clinically true, not modeled as late acute peaks.
  - Chronic scleroderma-like, ILD, PAH, Raynaud, swollen-hands, and overlap-organ axes should be allowed at presentation when they represent established disease background.
  - MCTD gained medically true overlap axes/edges for low/mild anti-dsDNA overlap, antiphospholipid antibody activity, direct Coombs positivity, hemolytic anemia activity, systolic/diastolic blood pressure, AST, and ALT.
- New general distillation audit rule: chronic autoimmune serology and established organ phenotype axes must be modeled as persistent/background-present when clinically true. Otherwise acute flare timing forces impossible disease-time alignment and can mimic another leaf for the wrong reason.
- New general missing-axis rule: antibody results are not ordinary labs for base fallback. Negative antibody evidence should usually be normal and should not be penalized just because another autoimmune disease leaf has a positive antibody baseline.
- Horizontal fairness notes: urticarial/IgA/cryoglobulinemic/ANCA/SLE vasculitis leaves must share purpura, complement, renal, pulmonary, neuropathy, and biopsy axes where true; MCTD/SLE/systemic sclerosis/myositis/antisynthetase/Sjogren leaves must share chronic autoimmune serology and overlap-organ axes where true; SRC/TMA/TTP/HUS/hypertensive emergency/renal vasculitis leaves must share AKI, hypertension, MAHA, thrombocytopenia, renal urinalysis, and dialysis hazards where true.
- UI roadmap after this batch: completed leaves are active; default next candidate is `D-POLYMYALGIA-RHEUMATICA`.
- Current atlas count after this batch: 159 disease manifolds and 450 real case JSON files.
- Focused new-batch grid (`URTICARIAL_VASCULITIS,MIXED_CONNECTIVE_TISSUE_DISEASE,SYSTEMIC_SCLEROSIS_RENAL_CRISIS`) was `9/9 PASS`.
- Full current-atlas grid after this batch:
  - 450 case JSON files loaded.
  - Single-manifold validation `445/447 PASS`; combo intentionally off.
  - The two single failures are unchanged accepted presentation-only ambiguities: `ANTISYNTHETASE_PULMONARY_JO1_PMC10515292` expected `D-ANTISYNTHETASE-SYNDROME` but best `D-DLBCL`, and `HODGKIN_AOSD_MASK_PMC4847271` expected `D-HODGKIN-LYMPHOMA` but best `D-ALCL`.
  - The two combo failures in the full single-mode run are expected because `MAX_COMBO_SIZE=1`: `D-ACUTE-PANCREATITIS+D-DIABETIC-KETOACIDOSIS` and `D137+D-TTP`.
  - Separate combo-only run (`VESMED_ONLY_COMBO_CASES=1`, `VESMED_MAX_COMBO_SIZE=2`) is `2/2 PASS`.
- This batch was committed and pushed as `b455920 Add connective tissue renal crisis manifolds`.
- User requested stopping after this batch. Do not launch the next disease-distillation agents until the user explicitly asks to continue.
