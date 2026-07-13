# 候选家族 03：结构因果模型、概率编程与开放宇宙因果程序

> 研究日期：2026-07-13  
> 研究状态：第一轮候选调查；不是最终架构决策  
> 范围：Structural Causal Models（SCM）、通用 Probabilistic Programming Languages（PPL）、causal PPL、probabilistic relational / open-universe causal programming、CP-logic  
> 判定口径：只承认形式语义和可执行行为；“原则上可编码”不等于“核心原生保证”

## 0. 结论先行

1. **SCM 是目前这批候选里对 observation / intervention / counterfactual 区分最干净的语义内核之一。** `P(Y|A=a)` 与 `P(Y|do(A=a))` 不是同一个查询；个体反事实必须执行 **abduction → action → prediction**，并让事实世界与反事实世界共享经事实证据更新后的外生背景。
2. **普通 PPL 不是因果架构。** 它通常提供 `sample` 与 `observe/condition/score`，因此原生停留在关联层；能写出生成程序，不代表程序就有可接受的因果解释。把 `condition(A=a)` 当成 `do(A=a)` 是硬错误。
3. **causal PPL 是有竞争力的执行层候选。** OmegaC、MultiVerse、ChiRho 一类工作证明，可以把 intervention、world splitting、共享外生随机性和近似推断做成程序变换或一等操作。不过它们主要解决“给定因果模型怎样执行因果查询”，并不自动解决模型是否正确、查询是否可识别、证据是否同源、历史时点可见性、知识版本或模型外疾病。
4. **“开放世界”至少有三种不同含义，不能混称。** 普通 Bayesian latent variable 只解决未知值；BLOG 解决未知对象数量与身份；open-universe causal models 允许无界变量空间。它们都不会自动发明新医学谓词、新病理机制或“未知疾病”，也不会自动拒绝 atlas 外病例。
5. **因果血缘不是证据血缘。** SCM 中 `X → Y` 表示假设的世界生成机制，不表示某个结论由哪份化验单、哪段文本、哪个抽取版本推出。PPL execution trace 记录一次运行中的随机选择，也不是耐久的 epistemic provenance。若把证据派生边塞进因果图，会把“从体温推出发热”错误写成“体温导致发热”。
6. **动态 SCM 解决的是物理/生理时间，不是 as-of knowledge time。** 事件发生、采样、结果可用、录入、有效、过期必须由独立的时态证据层控制；否则模型即使有时间轴，也会让未来报告进入过去判断。
7. **本家族不应作为完整固定核心单独胜出。** 当前证据支持的较窄结论是：保留“SCM 级 intervention/counterfactual 语义 + causal PPL 执行”作为候选内核组件；若没有类型化事件/证据/血缘/版本/覆盖失败层，则它在本任务的硬约束下被淘汰。

## 1. 必须先拆开的概念

### 1.1 四种完全不同的边

| 边 | 含义 | 例子 | 应放在哪里 |
|---|---|---|---|
| 世界因果边 | 世界中一个机制改变另一个状态 | 去甲肾上腺素作用 → 血管张力改变 | SCM / causal program |
| 观察生成边 | 内部状态在测量条件下生成读数 | 动脉氧合 + 吸氧 + 探头误差 → SpO2 | SCM observation mechanism |
| 证据派生边 | 计算或人类判断从证据得出声明 | 39.2°C 记录 → `fever_present` | provenance / derivation graph |
| 文档血缘边 | 数据从哪个来源、版本、活动产生 | 护理记录 v3 → 抽取事实 e17 | event/provenance store |

一个万能 DAG 可以画出这四类边，但如果执行引擎把它们当成同一种边，就会产生非法因果干预、推断自证和同源重复计数。因此“都能放进图”不是合格答案。

### 1.2 “开放世界”的三个层次

| 层次 | 问题 | 哪类方法能处理 | 本任务仍缺什么 |
|---|---|---|---|
| 值开放 | 某个已知变量的值未知 | SCM/PPL 对未观测随机变量边缘化 | 区分未问、未查、冲突、不适用等认识论状态 |
| 对象开放 | 不知道有几个对象、一次观测对应哪个对象 | BLOG；无界 relational/generative model | 医学概念本身仍由类型和程序给定 |
| 概念开放 | 可能存在模型未定义的新疾病、新机制、新检查语义 | 上述方法均不自动解决 | 显式 coverage/OOD、未知机制占位、版本化知识扩展与拒答 |

**关键反例：** 一个 BLOG 模型可以推断“有几个未观察到的感染灶”，但若程序只定义了细菌性和病毒性机制，它不会自动构造一种全新的免疫病。无限变量空间也不等于无限医学理论。

### 1.3 随机变量名不会自动提供认识论类型

下面五项即使都叫 `fever`，法律地位也不同：

```text
latent_state:       patient_core_temperature_state
instrument_reading: measured_temperature(evidence_id=e1)
patient_assertion:  patient_reports_feverish(evidence_id=e2)
derived_claim:      fever_present <- threshold(e1)
hypothesis:         inflammatory_fever_explanation
```

SCM/PPL 都允许把它们建成不同变量，却不强制作者这样做。若 schema 只暴露一个无类型 `fever=true`，后续无法判断它能否作为观测似然、能否被干预、能否被删除、是否只是诊断假说。因此“可建五个节点”只能记作 `△`，不能记作认识论分离原生通过。

## 2. 已核实的第一手来源

下表 URL 均在 2026-07-13 打开并核实了作者/出版信息或正文。预印本、工作坊稿和官方文档单独标注，不把它们伪装成成熟同行评审证据。

| ID | 第一手来源 | 已核实的直接支持 | 限制/证据等级 |
|---|---|---|---|
| S1 | Pearl, [An Introduction to Causal Inference](https://pmc.ncbi.nlm.nih.gov/articles/PMC2836213/) (2010, *International Journal of Biostatistics*) | SCM、surgical intervention、观测/干预/反事实查询；因果结论需要数据生成假设，不能仅从分布得到 | 权威综述/方法论文；不是临床产品架构规范 |
| S2 | Peters, Janzing, Schölkopf, [Elements of Causal Inference](https://mitpress.mit.edu/9780262344296/elements-of-causal-inference/) (MIT Press, 2017, open access) | SCM 的函数、外生变量、干预、机制不变性与因果学习基础 | 权威教材；常规表述主要面向固定变量系统 |
| S3 | Bongers et al., [Foundations of Structural Causal Models with Cycles and Latent Variables](https://doi.org/10.1214/21-AOS2064) (2021, *Annals of Statistics*) | 循环 SCM 可能无解、多解，且未必诱导唯一 observational/interventional/counterfactual distribution；需要 solvability 条件 | 同行评审；直接支持反馈系统的最坏失败 |
| S4 | Boeken & Mooij, [Dynamic Structural Causal Models](https://arxiv.org/abs/2406.01161) (2024) | 变量可为时间函数；可表达部分 SDE、time splitting、subsampling 与时间依赖干预 | UAI 2024 workshop / arXiv；作者明确对部分识别问题只给出建议，不是 bitemporal 证据系统 |
| S5 | Ibeling & Icard, [On Open-Universe Causal Reasoning](https://proceedings.mlr.press/v115/ibeling20a.html) (UAI 2020) | 将结构方程和 simulation models 扩展到可数无限变量空间；给出干预/反事实语义与限制下的等价性 | “开放宇宙”是变量空间意义；论文指出对丰富程序的某些推理一般可不可判定 |
| S6 | Ibeling & Icard, [Probabilistic Reasoning Across the Causal Hierarchy](https://ojs.aaai.org/index.php/AAAI/article/view/6577) (AAAI 2020) | association、intervention、counterfactual 三层语言严格增强；概率程序也需额外因果结构 | 形式语言结果，不提供证据血缘或临床时间模型 |
| S7 | Gordon et al., [Probabilistic Programming](https://doi.org/10.1145/2593882.2593900) (FOSE 2014) | 普通概率程序的核心是在通常程序上加入随机采样和对观察的 conditioning | 直接说明 PPL 基元中没有天然 `do` 或反事实世界 |
| S8 | Goodman et al., [Church: a Language for Generative Models](https://web.stanford.edu/~ngoodman/papers/churchUAI08_rev2.pdf) (UAI 2008) | 通用生成过程、conditional query、随机 memoization 与通用推断 | 通用表达力不等于因果或审计不变量 |
| S9 | Bingham et al., [Pyro: Deep Universal Probabilistic Programming](https://www.jmlr.org/papers/v20/18-403.html) (JMLR 2019) | 通用 PPL、近似推断、Poutine composable effect handlers | “可做程序变换”不保证变换具有正确因果语义 |
| S10 | Cusumano-Towner et al., [Gen: A General-Purpose Probabilistic Programming System with Programmable Inference](https://doi.org/10.1145/3314221.3314642) (PLDI 2019) | addressed random choices、choice map、execution trace、可编程推断及精度/效率权衡 | trace 是运行时随机选择轨迹，不是原始临床证据的耐久血缘 |
| S11 | Perov et al., [MultiVerse: Causal Reasoning using Importance Sampling in Probabilistic Programming](https://proceedings.mlr.press/v118/perov20a.html) (PMLR 2020) | 在 PPL 中执行反事实；为 abduction 显式保留噪声变量，并用 importance sampling 近似 | 原型系统；说明普通 `observe` 随机过程不足以自动完成 AAP |
| S12 | Tavares et al., [A Language for Counterfactual Generative Models](https://proceedings.mlr.press/v139/tavares21a.html) (ICML 2021) | OmegaC 给 PPL 加入类似 `do` 的操作，形式化“给定事实证据，再干预过去”的反事实 | 聚焦给定 simulation model 的反事实执行，不解决 causal discovery / provenance / as-of replay |
| S13 | Milch et al., [BLOG: Probabilistic Models with Unknown Objects](https://www.ocf.berkeley.edu/~dlong/publications/blog-ijcai05.pdf) (IJCAI 2005) | 可能世界可有变化且无界的对象数；支持对象身份不确定和针对未知对象的证据 | 对象开放，不是概念开放；模型类型与生成声明仍须事先给出 |
| S14 | Vennekens, Denecker, Bruynooghe, [CP-logic](https://doi.org/10.1017/S1471068409003767) (TPLP 2009) | 用模块化 probabilistic causal laws 表达引导过程演化的 causal events，并关联 well-founded logic program semantics | 事件的生成顺序不是临床六时间戳；有限知识库通常仍需预定义谓词/规则 |
| S15 | Zhang, Tian, Bareinboim, [Partial Counterfactual Identification from Observational and Experimental Data](https://proceedings.mlr.press/v162/zhang22ab.html) (ICML 2022) | 反事实通常不能由观察/实验分布直接点识别；可求紧界，但会化为一般昂贵的 polynomial program | 直接反驳“有 SCM/PPL 就能输出可信反事实点估计” |
| S16 | Green, Karvounarakis, Tannen, [Provenance Semirings](https://doi.org/10.1145/1265530.1265535) (PODS 2007) | 可组合追踪查询结果依赖哪些输入及不同推导组合 | 这是补齐血缘的独立理论，不是 SCM/PPL 自带属性 |
| S17 | W3C, [PROV-DM / PROV family](https://www.w3.org/groups/wg/prov/publications/) (Recommendation, 2013) | entity、activity、agent、generation、usage、derivation 与时间的标准化 provenance 对象 | 数据血缘标准本身不提供生理因果或概率推断 |
| S18 | Wang et al., [Typed Abstractions for Causal Probabilistic Programming](https://www.cl.cam.ac.uk/~jdy22/papers/typed-abstractions-for-causal-probabilistic-programming.pdf) (2026 talk paper) | 明确指出普通 PPL “by construction” 位于关联层；用 typed intervention points 和 multi-world values 约束高层查询 | 3 页新工作/报告，不足以作为成熟系统证据；文中也明确 identification 需另行处理 |

## 3. 候选 A：结构因果模型（SCM）

### 3.1 最小形式

一个概率 SCM 可写作：

\[
M=(U,V,F,P_U), \qquad V_i := f_i(PA_i,U_i)
\]

- `U`：模型外生背景/噪声；
- `V`：模型内生变量；
- `F`：每个内生变量的结构赋值；
- `P_U`：外生变量联合分布；
- observation：在事实模型诱导的分布上条件化；
- hard intervention `do(X=x)`：把 `f_X` 替换为常函数 `x`，切断原来决定 `X` 的输入；
- soft/mechanism intervention：替换或参数化一个机制，而不是把下游生理值强制为常数；
- counterfactual：事实证据更新 `U` 后，在修改过的模型中重算结果。

SCM 的最小原语数量很小，但这里的“小”有条件：若要满足本任务，仍需另外表达观察过程、证据状态、异步时间、来源、知识版本和推断覆盖。把这些全扩成普通 `V` 并不会产生类型安全。

### 3.2 统一模板评价

| 问题 | SCM 的答案 |
|---|---|
| 基本原语 | 外生变量、内生变量、结构函数、外生分布、干预/子模型、查询 |
| 状态放在哪里 | `V` 的事实世界解；对患者不确定性是 `P(U,V | evidence)`，不是一个已确认点 |
| 时间怎样表示 | 固定时间片展开 `V_t`，或 dynamic SCM 中以整段时间函数为变量；标准 SCM 没有“何时获知”语义 |
| 观察怎样表示 | 需要显式 observation mechanism，例如 `O_spo2 := h(oxygenation, oxygen_support, device, noise)`；然后对 `O_spo2` 条件化 |
| 干预怎样表示 | hard `do` 替换结构式；药物更自然地作为 action 变量经 PK/PD 机制作用，或作为 soft/mechanism intervention |
| 不确定性怎样表示 | `P_U` 与后验；模型结构/参数不确定性需再放超先验或模型集合；不能天然区分“未问/未查/冲突” |
| 共病怎样组合 | 多机制共同进入结构函数，可非线性、可共享潜变量；但所有交互必须显式建模 |
| 证据血缘怎样保存 | **不保存。** 结构父节点是世界因果父节点，不是文档/推导来源 |
| 如何扩展新知识 | 增加变量或机制模块；只有在接口与自治假设成立时才局部，新增混杂/交互常会修改旧函数 |
| 怎样生成任务坐标 | 对同一后验作不同 query/readout/loss；无需一个万能距离，但治疗决策还需要效用和安全约束 |
| 天然解决 | observation vs intervention；共享原因；多解释后验；机制性非线性交互；反事实世界一致性 |
| 需要补丁 | typed evidence/event store、bitemporal filter、provenance、model versioning、coverage/OOD、identification checker、推断诊断 |
| 最坏失败 | 一个错但拟合好的因果模型给出非常自信的错误干预/反事实结论；数据拟合不能证明箭头和不变机制正确 |

### 3.3 临床观察模型不能省略

以“SpO2 98%，但正接受高流量氧疗”为例：

```text
latent_oxygenation_t ─┐
oxygen_support_t ─────┼─> observed_spo2_t
device_context_t ─────┤
measurement_noise_t ──┘
```

对 `observed_spo2_t=98` 条件化，不等于对 `latent_oxygenation_t=normal` 条件化。类似地：

- 正常 MAP + 大剂量升压药：药物是产生正常读数的父机制；
- 抗菌药后培养阴性：药物影响病原负荷和检测敏感度；
- β 阻滞剂/固定频率起搏下心率正常：观察表型被干预或装置改写；
- 退热药后无发热：需要把退热药、体温调节状态、测量时点同时放入观察生成机制。

这正是 SCM 的强项，但也是其扩展爆炸点：若每个检查、设备、药物和条件都通过普通变量手工连边，缺边会静默产生错误独立性。

## 4. Observation、intervention 与 AAP：不能妥协的核心差别

### 4.1 Conditioning 不是 doing

考虑：

```text
U ~ Bernoulli(0.5)
A := U
Y := U
```

则：

```text
P(Y=1 | A=1)       = 1.0
P(Y=1 | do(A=1))   = 0.5
```

原因是观察 `A=1` 会筛选出 `U=1` 的事实世界；`do(A=1)` 则替换 `A` 的生成机制，并不改变 `U`。任何只支持 `observe(A=1)` 的 PPL 都不能仅凭此得到后一个答案。

临床上，观察到“已经给予广谱抗菌药”还携带医生为何给药的信息；把它当作实验随机干预会抹去 indication/confounding。反过来，模拟“现在给予药物”的效果又不能只条件化在历史上曾给药的人群。

### 4.2 个体反事实必须是 abduction → action → prediction

给定事实证据 `E=e` 和反事实动作 `do(A=a')`：

1. **Abduction**：计算 `P(U | E=e)`；
2. **Action**：只替换目标结构机制，得到 `M_{do(A=a')}`；
3. **Prediction**：在修改后的模型中使用同一个 `P(U | e)` 计算反事实结果。

最小连续例：

```text
U ~ Normal(0, 1)       # 同一患者的潜在反应背景
Y := A + U
事实：A=1 且精确观察 Y=1  => abduction 得 U=0
反事实：do(A=2)        => 同一患者 Y_cf=2
```

若程序在反事实分支重新抽 `U' ~ Normal(0,1)`，得到的是 `Normal(2,1)` 的新人群预测，不是该患者的反事实。这是普通 PPL 最容易犯、又不一定报错的错误。MultiVerse、OmegaC/ChiRho 的关键贡献正是把显式噪声/世界共享/程序变换做出来。

### 4.3 有 AAP 语法仍不等于答案可识别

SCM 完全指定时反事实可计算；现实中结构函数、混杂和外生耦合通常未完全确定。ICML 2022 的 partial counterfactual identification 结果表明，即使同时有观察和部分实验分布，反事实也可能只可给界，而且求紧界一般很昂贵。因此合格运行时至少需要：

```text
query_status ∈ {
  identified,
  partially_identified(lower, upper),
  assumption_dependent(assumption_ids),
  not_identified,
  inference_failed
}
```

“采样器返回了一个数”不能替代 identification status。

### 4.4 临床动作至少要分成五种对象

```text
planned_action        # 医嘱/方案，尚未发生
ordered_action        # 已下达，可仍未执行
administered_action   # 实际给药/操作事件
biological_exposure   # 患者真正获得的暴露，受依从、吸收、装置等影响
query_intervention    # 为反事实/策略查询而施加的机制变换
```

历史上观察到 `administered_action=a` 是事实证据，对它做 conditioning 会保留“为何接受该治疗”的信息；评估 `query_intervention=do(a)` 则要修改决策/给药机制。`planned_action` 绝不能直接成为治疗效果的父节点。安全的 causal program 还应让实际给药先通过依从、剂量、PK/PD 生成 `biological_exposure`，再影响生理机制。普通 SCM/PPL 不会凭变量名强制这些层次，因此必须由类型契约禁止计划即实施、观察即干预。

## 5. 候选 B：通用概率编程语言（PPL）

### 5.1 最小形式与优势

典型通用 PPL 是宿主程序加上：

```text
sample(address, distribution)
observe/score(address, value or likelihood)
return(value)
```

控制流、递归、函数组合和数据结构来自宿主语言。程序定义生成过程，推断器对 execution traces 做精确或近似条件推断。Church 展示了通用生成过程；Pyro 用 effect handlers 做程序变换；Gen 让随机选择有地址、choice map 和可编程 inference。

它的真实优势是：

- 能自然表达复杂非线性、递归、对象生成和自定义观察模型；
- 参数、结构和潜变量不确定性可以统一采样；
- 可以为不同模型换推断算法；
- 可把 SSM、SCM、关系模型或 simulation 作为程序，而不是固定一种图。

### 5.2 统一模板评价

| 问题 | 普通 PPL 的答案 |
|---|---|
| 基本原语 | 宿主计算 + `sample` + `observe/score` + return；有的系统再暴露 trace/address/effect handler |
| 状态放在哪里 | 一次 execution trace 及其后验分布；对象与控制流可动态生成 |
| 时间怎样表示 | 用户代码里的索引、递归、连续时间求解器或事件；语言通常不赋予临床时间类型 |
| 观察怎样表示 | likelihood/conditioning；很适合写 measurement model |
| 干预怎样表示 | **普通 PPL 没有。** 重写程序、effect handler 或额外 causal operator 才有 |
| 不确定性怎样表示 | 概率分布和后验原生；认识论状态仍要额外 ADT/类型 |
| 共病怎样组合 | 函数组合和共享随机变量；但地址冲突、重复 `score`、共享噪声与交互接口由作者负责 |
| 证据血缘怎样保存 | trace 可记录本次随机选择；不自动保存 clinical evidence ID、来源等价类、派生规则版本或删除级联 |
| 如何扩展新知识 | 添加模块/函数较容易；但控制流变化会改变 trace/address/inference，语义 blast radius 未必局部 |
| 怎样生成任务坐标 | 任意 posterior query/readout；可按任务编程 |
| 天然解决 | 表达不确定生成过程、复杂观察、动态对象、近似推断 |
| 需要补丁 | causal semantics、世界共享、identification、时态可见性、provenance、coverage、类型化失败 |
| 最坏失败 | 程序可运行且后验收敛，但它实现的是错误查询；推断近似又给结果增加第二层不可见误差 |

### 5.3 Execution trace 不等于证据血缘

Gen 的 addressed random choices / choice map 很有用，但它回答的是“这次执行抽到了什么、概率权重如何”。本任务需要的则是：

```text
conclusion c42
  <- rule r7@version3
  <- evidence e17 (lab report, source-family s5)
  <- evidence e21 (independent family s9)
```

并能在删除 `e17` 后只撤销依赖它的结果。PPL trace 默认不包含：

- 原始文档不可变 ID 与内容哈希；
- 抽取/标准化/推导活动及其版本；
- 多条表述是否来自同一 source family；
- 哪个历史时点该证据可见；
- 知识规则版本；
- 对结论的最小支持集合。

因此 PPL trace 最多是**计算诊断材料**，不能冒充 trace completeness。

## 6. 候选 C：causal PPL

### 6.1 已有路线

| 路线 | 核心做法 | 对本任务的意义 |
|---|---|---|
| MultiVerse | 将噪声显式放入 trace；importance sampling 做 abduction/counterfactual | 直接暴露普通 PPL 对 AAP 的不足 |
| OmegaC | 给通用函数式 PPL 加 `do` 风格操作和反事实语义 | 证明 causal query 可以是一等程序构造 |
| Pyro/ChiRho | 用 effect handlers 把 causal assumptions 编成 PPL，并自动生成 multi-world program | 可与现代近似推断结合；但 causal assumption 仍由模型作者负责 |
| Typed causal PPL（2026 emerging work） | typed intervention points、multi-world values、类型追踪可干预位置 | 可能把部分非法操作变成类型错误；仍不管 identification/provenance/time |

### 6.2 作为候选正式内核时至少需要的原语

```text
exogenous(name, distribution)
mechanism(output, typed_inputs, function, version)
observe(evidence_id, observation_variable, likelihood)
intervene(intervention_point, mechanism_transform)
counterfactual(factual_evidence_set, intervention_set, shared_world_policy)
query(target, information_cutoff, model_version)
```

其中 `shared_world_policy` 不能默认含糊：个体反事实通常共享事实世界经 abduction 的外生背景；群体介入分布则是另一种查询。`mechanism_transform` 也不能只支持常值替换，因为药物常改变漂移、敏感度、方差或反应机制，而不是强制某个生命体征。

### 6.3 统一模板评价

| 问题 | causal PPL 的答案 |
|---|---|
| 基本原语 | PPL 基元 + intervention point / program transform + factual/counterfactual world management |
| 状态放在哪里 | 多世界 execution traces 与后验；事实与反事实共享指定随机性 |
| 时间怎样表示 | 仍由模型代码定义；不自带 event/available/record/expiry time |
| 观察怎样表示 | factual world 上 conditioning；必须避免把观察误应用到反事实分支 |
| 干预怎样表示 | 程序变换、机制替换或 effect handler；这是真正强项 |
| 不确定性怎样表示 | 后验、结构/参数先验、近似推断；identification uncertainty 不是采样误差，需单列 |
| 共病怎样组合 | 可以组合机制程序并显式交互；类型化 effect 接口可能降低错误 |
| 证据血缘怎样保存 | 仍非原生；世界/trace 地址不等于来源血缘 |
| 如何扩展新知识 | 新机制可成为模块；但改变 causal signature、地址与推断会影响旧结果和版本兼容 |
| 怎样生成任务坐标 | 同一事实后验上运行 diagnosis/prognosis/safety/counterfactual query |
| 天然解决 | 可执行 observation/intervention/counterfactual；复杂模型与推断算法解耦 |
| 需要补丁 | 证据事件、bitemporal replay、identification/refusal、OOD、规则不变量、审计友好 DSL |
| 最坏失败 | “世界分支写对了、模型假设写错了、推断近似也没收敛”，系统仍可能返回高精度小数 |

**判定：** causal PPL 是前三名原型的合理候选，但只能以“因果执行子内核”参赛；若当作整个临床事实仓库和审计内核，则硬失败。

## 7. 候选 D：关系式、开放宇宙与因果逻辑编程

### 7.1 BLOG：未知对象与身份

BLOG 的可能世界允许对象集合本身变化，并能推断某些观测是否来自同一未知对象。对应临床例子包括：

- 影像中的多个灶是否为同一病程的不同表现；
- 多次培养是否来自同一感染源；
- 未知数量的病灶/暴露/接触者；
- 记录 linkage 与患者身份不确定性。

但 BLOG 模型仍必须声明类型、随机函数和对象生成过程。它解决的是 `#Object` 和 identity uncertainty，不是“系统从未听说过的新疾病机制”。

### 7.2 Open-universe causal models：无界变量不是无界知识

Ibeling & Icard 允许可数无限变量空间，并给结构方程和 simulation program 定义 intervention/counterfactual 语义。这证明固定有限 `V` 不是 SCM 的逻辑极限，也为按需实例化 `finding(patient,time,site,...)` 提供理论依据。

不过该工作也揭示了代价：

- 需要可计算性、良基/时间顺序、functional/monotone 等限制才能获得良好等价性；
- 对丰富概率程序的某些具体 causal influence 推理一般可能不可判定；
- 变量签名和生成程序仍然定义了什么概念可被谈论；
- 这不是持久事件日志，也不自动隔离未来信息。

### 7.3 CP-logic：事件性强，但不是完整临床时间

CP-logic 把因果知识写成 probabilistic causal laws，让 causal events 逐步产生结果；规则局部、关系式、可读性较好。它对“机制触发事件”的表达优于静态概率表。

然而：

- causal process 中“事件先后”不等于 occurrence/sample/available/record/effective/expiry 六种时间；
- well-founded model / rule firing lineage 也不自动等于原始病历 provenance；
- hard intervention、个体 AAP、连续状态和近似推断需额外机制；
- 规则冲突、negation/closed-world 选择若未严格约束，会违反“未提及不等于阴性”。

### 7.4 统一模板结论

关系/开放宇宙路线改善了**局部模板化和对象扩展**，但没有消除以下核心缺口：概念级开放、证据血缘、bitemporal replay、identification、推断失败显式化。因此它更像 causal PPL 的扩展前端，而不是单独赢家。

## 8. 动态时间：生理时间与知识时间必须分层

### 8.1 SCM/PPL 能表达的“物理时间”

- 离散展开：`X_t -> X_{t+1}`；
- 整段轨迹变量：dynamic SCM 把内生变量视为时间函数；
- 连续动力学：ODE/SDE/point process 作为机制程序；
- time-varying intervention：治疗策略随历史变化。

这足以表示治疗改变未来状态、病程滞后和部分反馈。但连续时间因果识别、离散采样偏差及时间依赖混杂仍是独立难题；“把 SDE 写进 PPL”不能自动解决。

### 8.2 SCM/PPL 不会自动表达的“知识时间”

| 时间 | 例子 | 是否应成为生理因果父节点 |
|---|---|---|
| occurred_at | 症状实际开始 | 可能，是世界事件 |
| sampled_at | 采血时间 | 影响样本代表的状态 |
| available_at | 培养结果何时可被医生知道 | 控制 as-of evidence set，不应倒流 |
| recorded_at | 何时录入 EHR | provenance / 系统时间 |
| valid_from / valid_to | 某声明代表哪段状态 | 观察适用区间 |
| expires_at | 何时不再足以代表当前状态 | 推断资格，而非生理死亡机制 |

历史回放的正确顺序应是：

```text
1. 选择 cutoff τ 和 knowledge/model version κ
2. 从不可变事件库筛选 available_at <= τ 且版本对 κ 可见的证据
3. 应用 validity/expiry 与撤销规则
4. 对所得事实证据做 abduction
5. 再运行 prediction/intervention/counterfactual query
```

若直接把所有时间字段都做成 SCM 节点，模型可能学到“晚录入导致死亡”这类数据流程相关性；若完全不建知识时间，未来最终诊断会进入过去判断。两者都不合格。

### 8.3 反馈与循环的硬风险

生理稳态常有反馈。简单地在同一时点画 `A ↔ B` 可能使 SCM 无解或多解；Bongers et al. 证明一般循环 SCM 不保证唯一 observational/interventional/counterfactual distribution。安全做法只能是二选一：

1. 用更细物理时间展开，使反馈成为跨时因果；或
2. 明确采用满足唯一可解/“simple SCM”等条件的循环类，并把 solvability 检查作为模型加载门。

沉默地用任意循环方程求一个数值固定点是硬失败。

## 9. 证据守恒：本家族的根本缺口

### 9.1 同源三次改写不能三票

压力测试 6：同一条 39.2°C 记录同时产生：

```text
e1: measured_temperature = 39.2
d1: fever = true        <- derive(e1, rule fever_threshold_v2)
d2: high_fever = true   <- derive(e1, rule high_fever_threshold_v1)
```

错误 PPL 会写三个独立 `observe/score`，似然被乘三次；错误 SCM 会把三者画成三个“证据节点”，但不标明同源。正确做法是：

- 世界模型只消费一个独立 source family 的观测似然，或用完整联合 deterministic observation model；
- `d1/d2` 保留为可查询派生声明，但 provenance polynomial / support set 都指回 `e1`；
- 任何投票/似然组合以源集合而非句子数量为单位；
- 删除 `e1` 时 `d1/d2` 自动失效。

### 9.2 因果 DAG 不能兼任 derivation DAG

`temperature_measurement -> fever_label` 是计算定义，不是世界因果；对 `fever_label` 做 `do(false)` 也不应改变真实体温。若两类边共用同一 intervention 语义，系统会允许荒谬查询。因此至少需要：

```text
CausalGraph       # 世界怎样生成和被干预
DerivationGraph   # 声明怎样由证据/规则推出
```

并由类型系统禁止对派生声明执行生理干预。Provenance semiring/W3C PROV 是可参考的补充理论，但加入后候选已经是混合架构，不再是“纯 SCM/PPL”。

## 10. 按硬要求的统一矩阵

图例：`✓` = 形式/核心原生；`△` = 可以显式建模，但默认不保证；`✗` = 需不同架构层，否则硬失败。`OU` 指 open-universe/relational 扩展。

| 要求 | 静态 SCM | 动态/循环 SCM | 普通 PPL | causal PPL | OU/relational causal |
|---|---:|---:|---:|---:|---:|
| 认识论对象分离 | △ | △ | △ | △ | △ |
| 生理/世界时间 | △ | ✓/△（取决于可解性） | △ | △ | △ |
| as-of / bitemporal 时间 | ✗ | ✗ | ✗ | ✗ | ✗ |
| 上下文化 observation model | ✓（若显式建） | ✓（若显式建） | ✓（若显式建） | ✓ | ✓ |
| observation ≠ intervention | ✓ | ✓ | ✗ | ✓ | ✓（取决于语言） |
| AAP 个体反事实 | ✓（完全 SCM） | △（须可解） | ✗ | ✓ | △/✓ |
| 概率不确定性 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 未问/未查/冲突/不适用 | △ | △ | △ | △ | △ |
| 非线性与共享机制 | ✓ | ✓ | ✓ | ✓ | ✓ |
| 共病局部组合 | △ | △ | △ | △ | △ |
| 原始证据血缘/去重 | ✗ | ✗ | ✗ | ✗ | ✗ |
| 删除证据自动失效 | ✗ | ✗ | ✗ | ✗ | ✗ |
| 多任务 query/readout | ✓ | ✓ | ✓ | ✓ | ✓ |
| 对象级开放世界 | ✗ | ✗ | △（动态程序） | △ | ✓ |
| 概念级开放/OOD 拒答 | ✗ | ✗ | ✗ | ✗ | ✗ |
| 历史回放隔离未来 | ✗ | ✗ | ✗ | ✗ | ✗ |
| 新机制局部扩展 | △ | △ | △ | △/✓（需 typed interface） | △/✓ |
| 推断自证静态禁止 | △ | △ | ✗ | △ | △ |
| identification/refusal | △（理论可判别一部分） | △ | ✗ | △ | △ |
| 人工审计 | △（函数可黑箱） | △ | △/✗ | △ | △ |
| 核心最小性 | ✓ 但功能不足 | △ | 表面少、宿主语义巨大 | △ | △/✗ |

**硬约束判定：** 任何纯 SCM/PPL 版本都因 `as-of replay + evidence lineage + concept-level unknown` 三项失败而不能独立进入最终前三；只有明确补上类型化事件/血缘/覆盖层的混合版本才有资格做原型。

## 11. 对 30 个压力测试的逐项结果

结果码：`P` = 本家族可自然通过；`C` = 条件通过，必须显式建模且可静默漏掉；`X` = 纯本家族硬失败/需要外层。

| # | 结果 | 结论 |
|---:|:---:|---|
| 1 | C | 升压药必须进入 MAP observation/state mechanism；仅观察正常 MAP 会失败 |
| 2 | C | 高流量氧疗必须进入氧合→SpO2 观察机制 |
| 3 | C | 退热药与测量时点需显式；否则无发热会被误读 |
| 4 | C | β 阻滞/起搏器需显式改写心率表现机制 |
| 5 | C | 抗菌药影响病原负荷与培养敏感度；SCM 很适合，但缺边即错 |
| 6 | X | 同源体温/发热/高热需要 provenance 去重，因果/PPL 本身不保证 |
| 7 | P | 炎症潜机制共同产生 fever/CRP/WBC 是 SCM 天然强项 |
| 8 | P | 两个潜机制可产生相同表型，后验可保留多解释 |
| 9 | P | 个体背景和机制参数可产生同病异表现 |
| 10 | C/X | 可加 source reliability/conflict model，但默认 conditioning 可能把冲突变成零概率或强行折中；冲突原文保留需证据层 |
| 11 | C | 未观测变量可边缘化；但“不提及原因”需 typed missingness 才不与阴性碰撞 |
| 12 | X | 结果可用时间不是普通动态 SCM 的原生 as-of 门 |
| 13 | X | 未来最终诊断隔离需 bitemporal evidence filter |
| 14 | P | 个体 baseline 作为变量/潜变量可自然处理相同肌酐不同意义 |
| 15 | P | 同一后验可支持诊断、安全等不同 query/readout |
| 16 | P/C | 非线性交互可表达；交互知识仍会组合爆炸 |
| 17 | P | action 可同时影响内部状态和观察过程，只要图中明确两条路径 |
| 18 | C | AAP 可比较自然病程/治疗路径，但效果可能不可识别，只能给界或拒答 |
| 19 | X | evidence expiry/validity 不是因果程序默认语义 |
| 20 | X | BLOG/OU 也不自动产生新疾病概念或安全 OOD |
| 21 | C | 新药可局部加 action→mechanism；若影响旧机制接口，blast radius 扩大 |
| 22 | C | 新检查可加 observation module；注册、单位、时间和 provenance 仍需核心外层 |
| 23 | X | 新理论重解释旧证据需要版本化事实与 model-as-of replay |
| 24 | X | PPL 可全量重跑，但无 provenance 不能可靠局部级联失效 |
| 25 | X | 只用当时可知信息需外部知识时间切片 |
| 26 | X | 稀有安全规则不能依赖概率程序是否生成/检索到，需强制 invariant/rule gate |
| 27 | X | 独立来源与同源改写之别需要 source family/provenance |
| 28 | P | 后验天然可保留多候选，不需强制单类 |
| 29 | X | 通用语言常能“写点近似”；缺 coverage/type error 时不会主动报不可表达 |
| 30 | X/C | 语义等价自然语言需输入适配契约；不是 SCM/PPL 核心能力 |

## 12. 最坏失败红队攻击

### 攻击 1：错模型、好拟合、错干预

两个 SCM 可诱导相同观察分布，却对 `do(treatment)` 给不同答案。若数据只有观察分布，图和机制方向依赖不可由拟合验证的假设。最坏结果不是报错，而是后验很窄、治疗建议很错。

**必须的防线：** 每个 causal query 输出 assumption IDs、识别状态、数据域与敏感性/界；没有 identification 证明不得把 posterior Monte Carlo error 当总不确定性。

### 攻击 2：把药物建成 `do(vital=normal)`

升压药并不把 MAP 常值钳制到 75；它改变血管张力/心排/反馈，且疗效受剂量、暴露和个体反应影响。对下游 vital 做 hard `do` 会绕过毒性、反应不足和反馈路径，产生不现实的反事实。

**必须的防线：** action variable + PK/PD/机制路径，或显式 soft/mechanism transform；禁止把临床动作默认编译为下游观察值常量替换。

### 攻击 3：反事实分支重抽患者

事实世界 abduction 后若重新采样外生噪声，个体反事实退化为新人群预测。代码仍会运行、结果看似合理。

**必须的防线：** world-sharing policy 是类型化查询的一部分；用第 4.2 节数值 oracle 做单元测试。

### 攻击 4：同源似然乘法制造伪确定性

同一体温被抽取成三个标签，三个 `observe` 将 posterior odds 人为立方。大模型文本抽取越“丰富”，错误越自信。

**必须的防线：** immutable evidence ID、source-family support set、derivation provenance；组合似然前做独立性审计。

### 攻击 5：开放世界幻觉

BLOG 能生成未知对象，open-universe SCM 能有无限变量，但若所有世界都只含已知 disease families，posterior 仍会在错误已知病之间归一化为 100%。

**必须的防线：** 独立 coverage/reference model、模型外残差与显式 `unsupported`；不要把无限变量宣传成未知病检测。

### 攻击 6：动态模型的未来泄漏

模型包含 `diagnosis_final_t+2`，推断代码直接对全 trace 条件化，再回看 `t`。动态因果图没有阻止未来可用信息进入过去后验。

**必须的防线：** inference 前按 `available_at` 建 evidence cut；测试 replay cutoff 单调性和未来隔离。

### 攻击 7：反馈方程多解

同一时点心排、MAP、血管张力互相定义，数值求解器受初始化影响选不同固定点；干预后甚至无解。PPL 可能把求解失败吞成 NaN/低权重。

**必须的防线：** 跨时展开或模型加载时证明/测试唯一可解；`no_solution/multiple_solutions` 必须是一等失败。

### 攻击 8：近似推断掩盖次要但致命 mode

VI 把多模态后验压成一个 mode，漏掉罕见但高风险机制；MCMC 未混合却给出漂亮 credible interval。因果语义正确也救不了错误数值推断。

**必须的防线：** algorithm diagnostics、跨算法对照、simulation-based calibration/coverage、重要安全 mode 的保守界；`inference_failed` 与 `not_identified` 分开。

## 13. 建议纳入统一原型的判别实验

### 13.1 三个公平版本

用同一医学变量和同一事实集实现：

1. **普通 PPL**：只有 `sample/observe`；
2. **causal PPL**：有 intervention/world split/shared noise；
3. **causal PPL + typed event/provenance shell**：再加入 evidence ID、source family、六时间戳与 model version。

不得给第 1 个版本偷偷写手工“do”分支，也不得只给第 3 个版本增加医学知识。

### 13.2 必测 oracle

```text
O1  conditioning_do_gap:
    P(Y=1 | A=1)=1, P(Y=1 | do(A=1))=0.5

O2  same_patient_counterfactual:
    U~N(0,1), Y=A+U, factual A=1,Y=1
    E[Y_do(A=2) | factual]=2
    禁止得到重新抽人的 N(2,1)

O3  support_normal_vital:
    正常 SpO2/MAP 不得把 latent untreated state 自动设正常

O4  duplicate_invariance:
    从同一 e1 派生 1 个或 10 个同义标签，posterior 不变

O5  as_of_replay:
    available_at > cutoff 的培养/最终诊断对过去输出零影响

O6  evidence_retraction:
    删除 e1 后所有且仅依赖 e1 的派生结论失效

O7  unsupported_disease:
    atlas 外病例必须产生 unsupported/coverage failure，不能只在已知病间归一化

O8  solver_and_inference_failure:
    多解循环、低 ESS、R-hat/收敛失败不得返回普通临床结论
```

### 13.3 应收集的工程指标

| 指标 | 本家族应如何记 |
|---|---|
| Core primitive count | 分开报告 SCM/PPL 原语与为了通过硬测试新增的 event/provenance/time/status 原语；不得把宿主语言算“免费” |
| Special-case count | 每个药物/检查的专用程序变换、手工地址规则、世界共享例外都计数 |
| Extension blast radius | 新药/新检查后变化的 causal signature、旧机制、推断代码、序列化 schema、回归结果数量 |
| Trace completeness | execution trace 与 clinical evidence provenance 分开计；只有后者能 100% 回到原始证据 |
| Replay correctness | 对每个 cutoff 做未来扰动测试；未来数据任意变化时过去输出必须 bitwise/semantic invariant |
| Collision count | 未问 vs 阴性、正常读数 vs 无治疗正常、群体 intervention vs 个体 counterfactual 是否被压成同一表示 |
| Illegal cycle count | 因果环可解性、推断自证环、derivation→causal 混型分别统计 |
| Unknown handling | 不只看低概率；检查模型支持域外是否显式停止 |
| Human audit burden | 审计一个结论需读多少机制代码、假设、evidence support 与 inference diagnostics |

## 14. 当前保留/淘汰建议

### 保留

- **SCM 的 intervention 与 AAP 语义**：这是本任务固定核心中很可能不可缺的一部分；任何最终架构都必须能表达等价语义，哪怕不用 SCM 术语。
- **causal PPL 作为可执行原型**：它能同时表示复杂观察机制、参数不确定性、soft interventions 与多世界反事实，适合进入前三候选原型。
- **open-universe relational 模板作为扩展机制**：对未知对象、身份和按需实例化有真实价值。

### 单独淘汰

- **普通 PPL 作为因果核心：淘汰。** 它只保证条件概率程序，不保证 doing/counterfactual。
- **纯 SCM/纯 causal PPL 作为完整临床核心：淘汰。** 缺 bitemporal evidence、provenance/deletion、概念级 unknown、强制安全 invariant。
- **“无限变量/未知对象 = 开放医学世界”：淘汰该论证。** 这是术语偷换。

### 可进入 Pareto 前沿的混合版本

```text
不可变 typed evidence events + bitemporal/as-of filter
    + provenance/derivation algebra
    + versioned causal mechanism programs
    + explicit observation / intervention / counterfactual query types
    + identification & numerical-inference status
    + coverage/OOD refusal
```

这不是“把所有东西堆起来”的许可。判别标准是：每层消除的是另一层无法自然表达的硬失败；若能用更小的共同原语同时保留类型隔离和可证明不变量，应进一步压缩。

## 15. 什么证据会改变本轮判断

以下任一实证都可能把 causal PPL 从“子内核”提升为更完整核心：

1. 一个形式化 causal PPL 同时原生提供 typed evidence identity、source-family provenance、bitemporal visibility、world sharing、mechanism versioning、coverage failure，并证明删除与 as-of 不变量；
2. 在统一 30 测试中，不借外部 event/provenance 层即可通过同源去重、历史回放和新理论重解释；
3. 能证明开放宇宙语义覆盖“新谓词/新机制”而不只是无界对象/变量，且能安全拒绝未覆盖世界；
4. 临床专家在盲审中能稳定审计复杂 mechanism programs，且人工负担显著低于类型化事件+因果子图混合架构；
5. 近似推断对多模态、稀有安全 mode 和动态治疗模型给出可验证的保守覆盖，而不是只报告采样标准误。

相反，若原型中任何一个错误只能靠“提醒模型作者小心”而不能由类型、模型加载检查或运行时拒答捕获，则不应把该能力计为架构原生通过。
