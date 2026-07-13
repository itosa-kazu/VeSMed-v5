# 候选家族研究：类型化知识图谱/时态超图、生成式世界模型/数字孪生、Transformer/统一隐状态

> **研究阶段**：Checkpoint 2–3 的候选调查与统一形式化预判；不是最终选型。  
> **调查日期**：2026-07-13。  
> **范围纪律**：本记录研究 C02、C12、C13，但把它们严格分开。知识图谱的关系语义、世界模型的生成动力学、Transformer 的学习型计算图互不自动继承。某一候选借用另一候选或事件账本、因果模型、规则验证器后，借入能力必须记入补丁和原语预算。

## 0. 判定口径与家族边界

### 0.1 H/P/F/U

- **H（home/native）**：该家族的标准原语自然给出所需语义；只需填医学内容，不需另造核心对象或执行器。
- **P（patch/companion）**：可用一个通用补充层实现，但不能把补充层的能力归功于本候选。
- **F（failure of the candidate as sole core）**：以该候选的本体作为唯一权威核心时会违反硬不变量；修复会改变候选身份或使另一套内核成为真正事实源。
- **U（unresolved）**：现有第一手证据不足，不能把“看起来能”计为通过。

评分的是**候选作为固定核心**，不是“任意程序能否用该数据结构编码答案”。图、张量和神经网络都有通用表达力；能编码不等于已有合法状态、更新、干预、血缘、拒答和安全语义。

### 0.2 三组候选不是一个混合候选

| 候选 | 真正的架构主张 | 权威状态放在哪里 | 不应偷领的能力 |
|---|---|---|---|
| C02 类型化知识图谱/时态超图 | 世界由有类型实体、发生实例、角色关系和断言构成；状态是图视图 | assertion/event graph 及其版本化视图 | 图中存了方程不等于图会执行方程；PROV/SHACL/因果或概率引擎不是普通图自动能力 |
| C12 生成式世界模型 | 用隐藏状态、行动条件转移和观察生成模型预测未来 | latent state/belief 与模型参数 | 高预测似然不等于因果正确、证据可审计或模型外可拒答 |
| C12b 数字孪生 | 数字表示与特定物理实体/过程持续交换数据，并调用一个或多个模型 | twin instance、同步数据与其内部模型状态 | “digital twin”是系统模式，不规定统一概率、因果、时间或血缘 calculus |
| C13 Transformer/统一隐状态 | token/embedding 经 attention 和层更新形成上下文化表示及读出 | token 序列、KV/hidden activations、参数 | QKV、注意力、长上下文或 RAG 不定义临床事实、`do()`、证据独立性或硬安全规则 |

数字孪生与生成式世界模型在 CANDIDATES.md 中暂共用 C12，是因为二者都主张“内部可模拟的数字状态”；本记录仍分别审计。数字孪生可以内部采用图、ODE、有限元、状态空间模型或 Transformer，因此**不能仅凭 twin 名称算作一套已形式化的动态内核**。同理，知识图谱可以送入 Graph Transformer，世界模型也可以由 Transformer 参数化，但组合后是 C15，而不是三家同时原生通过。

---

## 1. C02：类型化知识图谱与时态超图

### 1.1 子家族必须拆清

1. **RDF/OWL 声明图**：RDF 图是 subject–predicate–object 三元组集合，predicate 表达二元关系；OWL 在其上提供声明式本体和 model-theoretic entailment。[G1][G2]
2. **reified occurrence/claim graph**：每次测量、陈述、推导或干预有独立 occurrence/claim identity；RDF 1.2 的 triple term/reifier 可表达“关于一个 proposition 的 claim/belief”，但截至本记录它仍是 2026-04-07 Candidate Recommendation，而非最终 Recommendation。[G1]
3. **类型化时态超图**：一个关系发生实例可有 `subject/result/method/specimen/context/source/...` 多个角色端口，并显式携带 valid/known/recorded/expiry。超图保留 n-ary group identity，避免把一个多方关系任意拆成会产生伪路径的二元边。[G3][G4]

最强且公平的 C02 实例不是“裸三元组库”，而是**以事实发生实例为中心、带角色、双时间、来源和版本的类型化时态超图**。不过，给图加这些字段只解决表示；执行语义仍需逐项证明。

### 1.2 最小形式与原语

可把最强实例写成：

\[
G=(V,E,\tau_V,\tau_E,\rho,\alpha),
\]

- `V`：patient、specimen、device、drug、finding、mechanism、hypothesis、source 等实体；
- `E`：有稳定 ID 的 observation/statement/inference/action occurrence；
- `τV, τE`：节点与发生实例的类型；
- `ρ(e, role)=v`：超边的角色端口，如 subject、feature、result、method、source；
- `α(e)`：时间、可靠度、版本、断言状态等注解。

最低不可隐藏的原语约有七类：实体/术语、发生实例、角色端口、类型/schema、断言状态、typed times、版本/视图。把它们都压成“节点和边”只会降低表面 primitive count，不会减少语义责任。

```text
ObservationOccurrence obs-123
  subject       -> patient-7
  feature       -> serum_creatinine
  result        -> 2.1 mg/dL
  specimen      -> serum-specimen-9
  method        -> assay-method-X
  treatment_ctx -> after-fluid-resuscitation
  valid_time    -> 2026-07-13T08:00
  known_time    -> 2026-07-13T12:00
  recorded_time -> 2026-07-13T12:04
  asserted_by   -> lab-system-A
  source        -> report-456
```

### 1.3 统一模板

| 问题 | C02 的回答 |
|---|---|
| **基本原语** | typed entity、relation occurrence/hyperedge、role、claim status、time/version annotation、graph/view。普通 RDF relation 是二元；n-ary 必须间接建模或采用超边。[G1][G3] |
| **状态放在哪里** | `G(valid_at=t, known_by=k, knowledge_version=v)` 是当时有资格知道的**断言视图**，不是患者隐藏生理真状态。潜在 `X_t` 只能作为被声明/估计的节点，除非另有动态执行模型。 |
| **时间** | RDF 1.2 Concepts 明说 RDF 抽象模型 atemporal、graph 是 static snapshot；适当 vocabulary 能描述事件和时间，但不会自动给出更新/replay 语义。[G1] Temporal RDF 的原始工作正是另加 temporal graph、entailment 和 query semantics。[G5] |
| **观察** | 最自然的表示是独立 occurrence，保留 subject、值、单位、方法、标本、条件、来源和可见时间；观察、患者陈述和推断可以用不同类型。 |
| **干预** | planned/order/administered/stopped 可用不同 occurrence 类型；effect edge 可分别指向 latent mechanism 与 observation process。但 `affects` 边不会自行成为 `do(a)`、转移核或剂量反应函数。 |
| **不确定性** | 可并存多个 claim、来源、confidence literal、支持/反对边；OWL 的开放世界防止简单把没写当假。[G2] 联合概率、校准、来源相关性、模型不适配和 paraconsistent inference 并非图原生。 |
| **共病/组合** | graph union、共享机制节点和 n-ary interaction hyperedge 很直观；但 union/incidence 不规定饱和、竞争、门控、速率或冲突时该如何更新。 |
| **证据血缘** | occurrence ID + W3C PROV 的 Entity/Activity/Agent、use/generation/derivation/invalidation 能保存来源骨架。[G6][G7] 递归撤回、根证据幂等和真值维护仍需执行代数。 |
| **扩展新知识** | 新 IRI、node/edge/shape 通常局部加入，存储核心不变；但 ontology entailment、shape、查询、物化闭包和执行模块可能非局部改变。 |
| **任务坐标/readout** | SPARQL/CONSTRUCT、子图、规则或 graph feature projection 可从同一事实图生成诊断/安全/预后视图；readout 逻辑必须版本化且保留 trace。 |

### 1.4 天然优势

- **认识论角色可见**：只要 schema 强制，ObservationClaim、PatientStatement、DerivedClaim、Hypothesis、PlannedAction 和 PerformedIntervention 不必压入同一数值槽。
- **异构上下文与 n-ary 关系**：同一 SpO2 可以绑定设备、FiO2、流量、部位、方法和可靠度；一条 relation occurrence 可有多个参与者。
- **多假说与开放词汇**：不会因 softmax 归一化而强制唯一 disease label；可先保存尚未分类的新实体和关系。
- **局部扩展与查询视图**：新增概念通常是增图，不必扩固定向量 shape；不同任务可以构造不同子图/readout。
- **审计可视化潜力**：若每次 occurrence、source、rule version 和 derivation 均有 identity，专家可读取有限 support subgraph，而不是解码隐向量。

Hetionet 证明 typed biomedical KG 能整合异质资源并用 metapath 做任务读出；它不证明患者双时间动力学或干预执行已经解决。[G13] EHR Health Knowledge Graph 的原始研究在其最佳设置下仍报告有限 recall，且概率来自 noisy-OR/Bayesian model 而非图结构自身；这提醒“图中内容”不是完整世界。[G14]

### 1.5 必须补的语义

#### A. “万能图”不是 interpreter

RDF semantics 定义 graph interpretation/entailment；SPARQL Update 定义 graph store 的 INSERT/DELETE；超图定义 incidence。这三者都不定义患者生理状态转移。[G1][G8]

```text
表示：encode(domain occurrences) -> G
读取：projection_q(G) -> task view
执行：Engine(model_version, G, latent_state, intervention)
      -> posterior / trajectory / action
```

第三行不会由前两行自然涌现。把 SDE、SCM、概率程序或规则 AST 存成图，只证明图能保存程序；真正核心是解释它的 operator/interpreter。

#### B. 开放世界不是 OOD detector

OWL 开放世界可守住“没有三元组 ≠ 断言为假”，但不能区分：未采集、query/filter 漏掉、endpoint 失败、物化过期、ontology 未覆盖或患者真的模型外。OWL Primer 还明确说明 OWL 不是数据库框架、程序语言或完整性约束语言。[G2]

SHACL 是单独的 constraint-validation 规范；它能验证 RDF data graph 对 shapes graph 的符合性，但不是状态转移、概率或 OOD 语义。[G9] `out_of_model`、coverage manifest 和 capability error 仍要显式建模。

#### C. 检索未召回不能变成不存在

图的**精确全量查询**与向量/语义检索必须分开。SPARQL federation 的 `SERVICE` 可失败，`SERVICE SILENT` 甚至把失败转成空解；远端也可能限量或截断。[G10] 因而安全关键结论至少要输出 query coverage、endpoint health、entailment/materialization version 和 truncation 状态。

罕见关键禁忌不得依靠“先语义检索相关规则再执行”。规则 manifest 应完整、版本固定、按适用域确定性执行；任何 endpoint/closure 不完整都应 fail closed。图适合存规则索引，不保证召回和执行。

#### D. proposition identity 不等于 evidence occurrence identity

RDF graph 是集合；相同 triple 只保留一个抽象命题。RDF 1.2 triple term 表示 proposition，reifier 才可代表关于该命题的不同 claim/situation；一个 proposition 可有多个 reifier。[G1] 每次独立测量必须有 occurrence ID，不能用三元组文本 identity 代替来源 identity。

PROV-DM/Constraints 给出血缘词汇与约束，但规范明确不要求消费者必须执行全部推理/验证。[G6][G7] 同源三改写去重、`s1 OR s2` 的撤回、非独立来源聚合仍需 provenance/truth-maintenance algebra。

### 1.6 最坏失败

1. 把 path、association、metapath 或共现边误读成因果链和可执行干预。
2. 把 retrieved/materialized subgraph 当成完整世界；远端失败或 stale closure 时静默漏掉禁忌。
3. 把 named graph 名称自动解释成来源、版本、信任域或时间，虽然数据模型未规定这种含义。
4. 相同 triple 合并后丢失独立测量；反过来 ETL/LLM 的多次改写又被当多份证据。
5. 把 confidence literal 当完整概率语义，忽略来源相关和模型支持域。
6. 将互相冲突的事实直接断言进经典 OWL 层，而没有 claim-level 隔离与冲突策略。
7. ontology/shape/materialization 更新产生非局部 closure 改变，却仍宣称 extension blast radius 为零。
8. relation class、context class、疾病组合 class 膨胀成新的 schema 特例森林。
9. 删除 source 只删一条边，衍生 claim、缓存 readout 和其他路径仍活着。
10. 用“所有东西都是图”掩盖图没有规定合法更新与失败模式。

### 1.7 当前定位

**保留**最强 C02 作为共享临床事实、证据、冲突假说和多任务视图的强候选底座；**淘汰“裸 RDF/OWL/超图单独就是完整动态诊疗核心”的主张**。如果补入双时间事件账本、PROV、SHACL、真值维护、因果/概率/动态引擎和安全 monitor，应按 C15 混合架构重新计算原语与补丁，不能继续把全部能力记在“图”名下。

---

## 2. C12：生成式世界模型与数字孪生

### 2.1 先拆成两个对象

#### C12a：生成式世界模型

Ha 与 Schmidhuber 的 World Models、PlaNet 和 Dreamer 系列的稳定共同骨架是 action-conditioned latent dynamics：[W1][W2][W3]

\[
b_t=q_\phi(s_t\mid o_{\le t},a_{<t}),
\]
\[
h_t=f_\phi(h_{t-1},z_{t-1},a_{t-1}),\qquad
z_t\sim p_\phi(z_t\mid h_t),
\]
\[
o_t,r_t,c_t\sim p_\phi(\cdot\mid h_t,z_t).
\]

从 posterior/belief 出发，模型在候选 action 下 rollout future latent trajectories，供 MPC、actor/critic 或任务 readout 使用。VAE、MDN-RNN、GRU、Transformer、SDE 是 encoder/transition/decoder 的实现选择；不是世界模型本体。原始 World Models 用 VAE + MDN-RNN/LSTM，PlaNet/Dreamer 用 RSSM，正说明不能把 Transformer 的 QKV 自动算入 C12。[W1][W2]

#### C12b：数字孪生

NASA 的基础描述把高保真多物理/多尺度模型、传感器更新、维护历史和 fleet history 结合，以镜像某个具体飞行器生命周期。[W9] NASEM 共识报告把 digital twin 视为计算模型与 physical counterpart 动态耦合、通过双向数据流更新并反馈决策的系统，同时把 UQ、model discrepancy、causality、identifiability 和数据/模型同化列为研究挑战。[W11]

```text
Physical counterpart
    <-> data acquisition / assimilation
Virtual representation: models + data
    -> prediction / simulation / optimization
    -> human or automated decision feedback
```

ISO/IEC 30173:2023 的公开页面确认它规范术语、系统上下文、生命周期、类型与功能视图；全文付费，因此本记录不声称未核对的具体条款。[W10] 数字孪生可以内部采用 PDE、ODE、SSM、世界模型、知识图谱或混合模型。它定义 deployment/lifecycle pattern，不给一套统一状态、证据、因果或撤回 calculus。

结论：**世界模型放进数字孪生是组合系统，不是两个名字描述同一个固定核心。**

### 2.2 统一模板

| 问题 | C12a 生成式世界模型 | C12b 数字孪生 |
|---|---|---|
| **基本原语/状态** | latent deterministic/stochastic state、belief/posterior、action、transition、encoder/observation decoder、reward/outcome/continue readout | physical counterpart、virtual representation、data exchange/assimilation、model service、prediction/decision feedback；virtual state 的内部形式未规定 |
| **时间** | 离散/连续 model time 与 rollout horizon；通常单一过程时钟 | synchronization/lifecycle 是核心系统概念，但不规定 occurred/collected/available/recorded/valid/expires |
| **观察** | encoder/update 把观察变成 posterior；decoder 给 `p(o given s)`，因此 latent state 与 observed manifestation 可自然分离 | 采集和同化来自具体 physical counterpart；观察 schema、source identity 和冲突策略由实现决定 |
| **干预** | action-conditioned transition/decoder；模拟中可分别让 action 改 state 和 observation | virtual→physical feedback 是系统闭环；“送入模型的 action”是否是可识别的临床 `do()` 未由 twin 标签保证 |
| **不确定性** | stochastic latent、ensemble、Bayesian parameter 或 particle 可表达 aleatoric/部分 epistemic；信息状态 ADT、冲突和模型外非原生 | 权威报告要求 VVUQ/credibility，但没有统一 probability 或信息状态代数 |
| **共病/组合** | arbitrary nonlinear transition 表达强；标准 monolithic latent 没有局部模块组合律或未知交互拒绝 | 可编排多个模型/尺度；接口、共享状态 ownership、组合律和不兼容行为不固定 |
| **血缘/撤回** | evidence 压进 latent/weights 后 root identity、独立性和精确撤回通常丢失 | 可外挂治理/事件账本；digital-twin 定义本身无 derivation/TMS |
| **扩展** | 新 observation/action/disease 常改 signature、encoder/decoder 并需全局训练 | 生命周期组件可替换是目标，但没有保证 core=0 modification 的计算合同 |
| **任务 readout** | 多 decoder、reward/value、QOI head、forecast 和 policy 很自然 | 多 quantity-of-interest、simulation service 和决策服务自然 |

### 2.3 真正优势

- **T01–T05/T17 的生成骨架贴题**：正常血压/血氧可由“潜在异常 + 支持行动 + observation decoder”共同产生，而非把观测直接当内部状态。
- **动态预测和治疗 rollout**：同一 posterior 可预测自然病程和不同候选 action 的未来轨迹；诊断、预后和决策读出共享动态模型。
- **共享 latent cause 与多模态 posterior**：发热/CRP/WBC 可由共同 hidden mechanism 生成；同表型可对应多个 latent explanation。
- **高阶非线性**：learned transition 可以拟合复杂交互，避免被固定线性叠加限制。
- **patient-specific assimilation**：digital twin 的核心工程价值是把个体数据持续同化到版本化模型实例，而非只用 population-average snapshot。[W9][W11]

医疗 digital twin 文献目前更多是愿景和 domain architecture。Precision Cardiology position paper 主张动态整合个体临床数据、mechanistic 与 statistical models，同时承认只有少量模型进入临床转化；Björnsson 等也是个体化用药模拟愿景，而非通用患者孪生固定内核的临床验证。[W13][W14]

### 2.4 决定性边界

#### A. latent belief 不是 PatientTrueState，也不是 evidence ledger

Dreamer latent 由 reconstruction/prediction/KL/reward/value objectives 塑形。Locatello 等证明，在缺乏关于模型/数据的 inductive bias 时，无监督 disentanglement 不可识别；这不否定有监督可解释 latent，但足以反驳“训练出 latent 坐标就自动得到稳定临床语义”。[W6]

合法身份应是：

```text
BeliefEstimate(
  model_version,
  evidence_snapshot_id,
  known_time_cutoff,
  posterior_distribution,
  approximations
)
```

它不能替代原始来源、单位、采集/可见时间、冲突 claim 和撤回 DAG。一旦事件压入 latent 或在线训练权重，无法仅凭该向量证明三条表述来自一个温度计还是三个独立温度计。

#### B. 逼真预测不等于因果正确

World Models 原始论文的 “Cheating the World Model” 是决定性内部反例：controller 找到近似模拟器中的高回报行为，但迁移到真实环境后崩溃；optimizer 会主动利用模型误差。[W1] PlaNet 同样把模型误差、多步累积和 OOD confidence 列为 model-based planning 难点。[W2]

游戏中的 action 通常直接送入 `env.step()`；临床治疗由病情选择，存在 indication confounding、positivity 和未测混杂。从观察轨迹学到的 `P(next|history,treatment)` 不自动等于 `P(next|history,do(treatment))`。[W8] 输出必须区分 conditional forecast、interventional prediction、individual counterfactual 和 recommendation。

#### C. 生成 likelihood 不是 coverage/OOD 证书

Nalisnick 等发现 VAE、flow、PixelCNN 类生成模型可能给 OOD 输入比训练数据更高的 likelihood。[W7] 因而低 reconstruction error、逼真 rollout 或高 likelihood 不能证明 atlas 覆盖患者。必须另有 coverage contract、model discrepancy、epistemic UQ、`out_of_model/refuse` 和未知设备/检查 quarantine。

#### D. recurrent time 不是临床多时间

RSSM 的 `t` 不等于检查发生、标本采集、结果可见、补录/修订、规则版本和观察过期。历史 latent trajectory也不能回答“09:00 当时知道什么”，除非先由外部 bitemporal evidence ledger 构造严格 snapshot。smoothing 整段序列还会把未来信息带回早期 latent。

#### E. digital twin 标签不等于 credibility

ASME V&V 40 要求模型可信度严谨程度与 context of use、对决策依赖和错误后果相称；FDA medical-device CM&S guidance 同样采用 risk-informed credibility assessment。[W15][W16] 这些是验证/监管框架，不是对任意 learned patient twin 的背书，也不补时间、血缘和因果语义。

### 2.5 血缘、撤回与局部扩展

如果一条证据只用于 online filtering，保留原始 event log 后可以从 checkpoint 重跑；如果它还参与在线训练，精确删除可能需要 retraining/unlearning。两种情况都不是从 latent 中局部“反更新”。新药还会扩 action space/effect model，新检查会扩 encoder/observation likelihood；标准 monolithic world model 的全局权重使 blast radius 无局部上界。

因此 C12 模块至少需要以下外部合同：

```text
AuthoritativeAuditableEventStore
  -> evidence_as_known_at(cutoff)
  -> VersionedBeliefUpdate
  -> ForecastTransition(performed_action)
  -> VersionedImaginationRollout
  -> CausalValidityGate
  -> VVUQ / Coverage Gate
  -> SafetyInvariantLayer
  -> task-specific readout
```

每次 rollout 必须绑定 model/training-data version、evidence snapshot、valid/known cutoff、initial posterior、action lifecycle、seed/trajectory IDs、horizon、support/OOD、aleatoric/epistemic uncertainty、causal validity scope 和 context of use。

### 2.6 最坏失败

1. model-internal trajectory 连贯、reward 很高，但现实 action effect 错，optimizer 主动寻找误差。
2. treatment choice confounding 被学成药物因果效应，再经 twin feedback 影响真实数据。
3. 冲突/撤回/来源差异压进同一 latent 后不可审计，模型仍输出精确小数。
4. full-sequence smoother 或缓存把未来诊断泄漏到首诊 state。
5. 生成 likelihood 对 OOD 过度自信，把未知病投进最近 latent basin。
6. 新观察/新药迫使 encoder/action signature 与全局参数改变，却宣称“twin 可无限局部扩展”。
7. 把 planned/order token 当 action，模拟了未实施治疗的作用。
8. 只验证单次 prediction accuracy，不验证多步 rollout、policy exploitation 和 context shift。
9. “digital twin”高可信品牌掩盖内部只是未经验证的回归器。
10. 罕见禁忌由模型 recall/rollout 处理，没有 independent deterministic invariant。

### 2.7 当前定位

**拒绝 C12 作为单一权威事实核心。** C12a 保留为可替换、版本化、受 causal/coverage/VVUQ gate 限制的 filtering、forecast 与治疗模拟模块；C12b 保留为部署/生命周期参考架构。若患者事实、双时间、证据撤回、版本和安全不变量由其他核心承担，应诚实报告通过测试的是混合系统，而不是“world model/digital twin 原生”。

---

## 3. C13：Transformer、QKV 与“统一隐状态”

### 3.1 最小形式

Transformer 把 token/feature embedding 经过 positional encoding、self-attention、feed-forward、residual/normalization 反复更新。单头 scaled dot-product attention 为：

\[
\operatorname{Attention}(Q,K,V)
=\operatorname{softmax}\!\left(\frac{QK^\top}{\sqrt{d_k}}\right)V.
\]

原始 Transformer 是 sequence transduction 架构，并用 mask 防止 decoder 位置看见后续输出位置；它没有声称定义临床事件、证据或干预本体。[T1] Universal Transformer 在深度方向反复应用共享的 self-attentive transition，Transformer-XL 用 segment-level recurrence 与相对位置编码延长依赖。[T2][T3] 这些工作证明“可反复更新/可带记忆的统一 hidden state”是一种强计算方式，不证明 hidden state 是合法的临床事实源。

“Transformer 是 sequence-to-sequence universal approximator”的理论结果也只讨论紧集上的连续函数逼近等表达能力。[T4] 表达力可以让网络近似一个合法 interpreter，也可以近似一个会未来泄漏、把 unknown 当 absent 的函数；它不提供类型或安全不变量。

### 3.2 统一模板

| 问题 | C13 的回答 |
|---|---|
| **基本原语** | token/embedding、position、Q/K/V linear map、attention、MLP/residual/layer update、mask、readout head；recurrent 变体再加 cache/hidden recurrence。 |
| **状态放在哪里** | 原始 tokens、各层 hidden activations、KV cache 和参数中。若只保留最终 embedding，它是不可逆压缩；若权威事实仍在外部 typed ledger，Transformer 已退为计算/读出层。 |
| **时间** | position/order、time embedding 或显式时间 token。causal mask 只限制序列位置可见性；它不理解 occurred/collected/available/recorded/valid/expires 六种时间。 |
| **观察** | 观察、动作、来源、单位都可 token 化，attention 可做上下文化；但角色合法性和 unknown/negative 的区别取决于外部 schema、训练和提示。 |
| **干预** | action token 可影响之后 hidden state/output；这只是条件生成。没有结构方程/动作核时，`observed treatment`、`planned treatment` 与 `do(treatment)` 没有形式上的不同运算。 |
| **不确定性** | token probability、ensemble、Bayesian/energy/OOD head 可外加；普通 softmax 不是 unknown/conflicting/not-applicable/model-error 的信息状态代数，也不保证校准拒答。 |
| **共病/组合** | self-attention + MLP 能学习高阶上下文交互，统一模型无需手写每个 pair；但没有声明式组合律、共享状态 ownership 或“缺交互时 unsupported”。 |
| **证据血缘** | 可记录输入 tokens、model/version、output 与 attention；hidden path 不是事实级 derivation DAG。attention weight 也不能直接当独立 evidence contribution。[T5][T6] |
| **扩展新知识** | 增加 token/文本看似 engine=0，但新药/检查能否被正确解释取决于 tokenizer、参数、上下文或再训练；全局权重更新使 blast radius 无静态上界。 |
| **任务坐标/readout** | prompt、query token、task head 和 cross-attention 很适合从共享表示生成多任务输出；这是它最强且合理的角色。 |

### 3.3 天然优势

- **上下文建模强**：同一数值可依据邻近药物、年龄、设备和病程 token 得到不同 readout；T09/T14 的统计调制可不靠固定局部窗口。
- **异步、多模态与任务读出灵活**：只要 adapter 编码时间/模态，统一模型可融合文本、表格、影像 embedding，并用不同 head/prompt 做诊断、严重度或安全任务。
- **高阶非线性和共享参数**：attention/MLP 可以学习远距离及高阶交互，不需预先枚举所有 disease pair。
- **工程生态与近似调度**：QKV、KV cache、sparse attention、retrieval 都适合作为大量候选知识/证据的计算优化层。
- **recurrent refinement**：Universal Transformer 一类反复更新能按输入复杂度进行多步处理；这值得作为 interpreter 内部算法测试，而不是事实 ontology。[T2]

这些优点解释为什么 Transformer 很可能出现在最终系统中；它们没有回答为什么 Transformer hidden state 应成为**固定核心架构的唯一权威状态**。

### 3.4 隐向量不可替代可审计事实

#### A. attention 不是 provenance

Jain 与 Wallace 在多种 NLP 任务中发现标准 attention 权重常与 gradient importance 不相关，并能找到很不同但产生相近预测的 attention 分布。[T5] Wiegreffe 与 Pinter 随后指出“attention 是否是 explanation”取决于解释定义和实验诊断，反对一刀切否定。[T6]

对本任务不需要解决整个解释性争论：即使某些 attention 可作有用提示，**它仍不满足 R-PROV-01/02 的形式契约**。provenance 要记录稳定 source occurrence、规则/模型版本、确定性派生或显式近似、根证据集合和撤回传播；attention matrix 没有这些对象，也不能证明复制同源 token 不改变支持质量。

#### B. 删除后重跑不等于真值维护

保留完整 token 序列时可以删除一条输入再全量前向，输出可能变化；但网络不会告诉我们：

- 哪些旧派生只依赖这条 evidence root；
- 哪些结论仍有 `s2` 独立支持；
- 多个改写是否属于同一根；
- 变化来自证据删除还是 model nondeterminism/version；
- 哪条安全 invariant 被触发。

若另加 immutable event IDs、dependency graph、model pinning 和 counterfactual rerun harness，则这些是 P，而不是 hidden vector 的 H。

### 3.5 时间、干预与因果边界

- **position 不是 clinical time**：把 token 按 occurrence time 排序会让 08:00 采样、12:00 才发布的结果泄漏到 09:00；按 available time 排序又会失去结果的生理有效时点。必须先有 typed multi-time event 与 `as_known_at` cut。
- **causal mask 不是 bitemporal replay**：mask 防止第 `i` 个 token 看第 `j>i` 个位置，但序列顺序本身可能不等于当时可见顺序；cache 还必须绑定 cutoff 和 model/schema version。
- **条件生成不是干预**：模型学到 `P(outcome | treatment, context)` 不等于已识别 `P(outcome | do(treatment), context)`；治疗指征混杂会被吸入权重。因果识别需要显式假设/试验或 causal model。[T7]
- **反复更新不是生理动力学**：Universal Transformer 的 depth recurrence 是计算步骤；除非状态、时间尺度、action effect 与 observation model 被另行定义，层数不能解释成临床时间。

### 3.6 RAG、检索未召回与硬安全

RAG 原始论文把 parametric seq2seq memory 与 dense-index non-parametric memory组合，并让生成器条件化于检索到的 passages；论文自己把决策 provenance 与知识更新列为待解决问题。[T8]

由该接口可直接推出一个架构边界：生成器只会使用进入其上下文的 retrieved items；未进入 top-k 的规则不会因为“真实存在”而自动执行。扩大 k、改善 recall、query rewriting 或 multi-hop retrieval 只能降低概率，不能证明罕见禁忌永不漏召回。

因此：

```text
semantic/vector retrieval = optimization / candidate discovery
deterministic rule manifest + scope check = safety semantics
```

安全规则可以先由 typed facts 精确匹配适用域，再调用 Transformer解释或生成说明；不能先问 Transformer“你想起了哪些规则”再决定执行集合。检索为空还要区分 index coverage、filter、timeout、权限、embedding mismatch 和真正不存在。

### 3.7 开放文本生成不是开放世界

Transformer 可以拼出训练 ontology 中没有的新字符串，这不等于它知道：

1. 该字符串是合法新疾病、输入适配错误还是幻觉；
2. 当前模型没有覆盖该机制；
3. 已知候选全部不足，应拒绝；
4. 哪个新概念可安全接入状态、观察与干预接口。

普通 decoder 仍会在 vocabulary 上归一化下一 token；“能生成任意病名文本”与开放集识别/coverage failure 是不同问题。需要 typed `out_of_model/unsupported/schema_error`、独立 coverage/OOD 证据和 abstention contract。[T9]

### 3.8 扩展与语言不变性

- 新术语作为字符串输入时 engine 文件可能零修改，但正确医学行为可能需要更新参数、检索库、ontology adapter、测试和 calibration；不能只数 tokenizer 是否接受字符。
- 全局权重共享是统计泛化优势，也是 blast radius 风险：一次 fine-tune 可改变不相邻概念，缺少局部上界。
- 若自然语言 token/hidden state 就是核心状态，同义改写必然产生不同 token 序列和通常不同 hidden activations，T30 的核心同构要求失败。
- 若先由 adapter 规范化成相同 typed clinical occurrence，再送入 Transformer，则 T30 可由 adapter/core contract 通过；但权威核心是 canonical event/claim，不再是原始 Transformer hidden state。

### 3.9 最坏失败

1. **高置信语义压缩**：计划用药、实际给药、观察和假说在 hidden state 中混合，输出仍语言流畅。
2. **未来泄漏**：结果按 occurrence time 或整段病历送入 attention，历史首诊 readout吸收最终诊断。
3. **同源增信**：同一体温被转述三次后 token 数/attention mass 增加，网络没有 evidence-root 幂等律。
4. **注意力伪血缘**：把可视化热图当 derivation proof，无法撤回和版本重放。
5. **检索静默漏规则**：关键禁忌未进 top-k，生成器不知道自己没看到。
6. **闭世界流畅化**：atlas 外病仍被映成最像的已知诊断或生成未经验证的新标签，没有显式 unsupported。
7. **条件相关冒充干预**：由指征混杂学到错误 action effect，再用于推荐形成反馈回路。
8. **措辞敏感**：临床等价改写形成不同 embedding/readout，产生 spurious distinction。
9. **全局更新退化**：新增药物 fine-tune 改变旧禁忌、单位或否定语义，局部扩展无法证明。
10. **cache 越界**：KV/cache 没绑定 known-time cutoff 或模型版本，历史回放读取未来/新版状态。

### 3.10 当前定位

**保留 C13 作为输入适配、检索/调度、近似推断和多任务 readout 的强计算层；淘汰“QKV/统一隐状态可作为唯一可审计临床事实核心”的版本。** 如果加入 typed immutable events、multi-time cut、provenance、causal/dynamic operator、OOD 和 deterministic invariant engine，Transformer 可以参数化这些 operator，但权威语义来自明确契约，整体应按 C15 评估。

---

## 4. 三家统一的 30 项压力测试

> 表中评的是最强合理家族版本：C02=`occurrence-centered typed temporal hypergraph`；C12a=`stochastic action-conditioned latent world model`；C12b=`consensus digital-twin system pattern`；C13=`Transformer/recurrent unified hidden state as authoritative core`。`P` 表示混合后可做，不是原生得分。

| T | 简写 | C02 | C12a | C12b | C13 | 判定要点 |
|---:|---|:---:|:---:|:---:|:---:|---|
| 01 | 正常 BP + 大剂量升压药 | H | P | P | P | 图可分 occurrence/context；world/Transformer 能条件化 action，但 typed 给药事实与 trace 需外层。 |
| 02 | 正常 SpO2 + 高流量氧 | H | P | P | P | C02 的 n-ary observation 自然；其余需显式测量上下文 contract。 |
| 03 | 无发热 + 刚用退热药 | P | P | P | P | 四者都要可执行的 state-effect/observation-effect 分离；存边或 token 不会执行。 |
| 04 | 正常 HR + β 阻滞/固定起搏 | H | P | P | P | 图能保留不同 modifier identity；模型需 typed context 才可审计。 |
| 05 | 抗菌后培养阴性 | P | P | P | P | 必须有时间化 sensitivity/observation model；association/attention 不够。 |
| 06 | 一次体温三改写不得三票 | P | F | P | F | occurrence ID 可承载但仍需 provenance algebra；latent/hidden state 没有 evidence-root 幂等律。 |
| 07 | fever/CRP/WBC 共享来源 | P | H | P | P | world model 的共同 latent cause 原生；图能画、Transformer 能学，但 likelihood 去重/因果身份需 operator。 |
| 08 | 同表型两机制 | H | H | P | P | graph 多对多与 stochastic posterior 自然；Transformer 可输出多个解释但无具名假说契约。 |
| 09 | 同病异质表现 | P | P | H | H | Transformer 上下文化、twin 个体校准自然；图/world model 仍需可执行调制与显式 patient context。 |
| 10 | 两来源冲突 | P | F | P | F | 图/twin 可外挂 conflict claims；单一 encoder/hidden update 易覆盖或平均。 |
| 11 | 未提及症状 | H | P | P | F | OWL OWA 防“缺失即假”；其他候选需显式 information-state type，Transformer 的 token absence 无契约。 |
| 12 | 采样后数小时才可见 | P | P | P | F | RDF/model/position time 都不自动是 valid+known time；C13 以序列位置作权威时基本冲突。 |
| 13 | 最终诊断不得进入过去 | P | P | P | P | 全部需 `as_known_at` evidence cut；causal mask 仅在正确排序后有用。 |
| 14 | 同肌酐、不同基线 | H | P | H | H | relation context/twin calibration/attention context 可区分；world latent 仍需显式 baseline input。 |
| 15 | 同患者不同任务坐标 | H | H | H | H | subgraph、head/QOI/readout 都自然；必须只读且 trace-preserving。 |
| 16 | 共病非线性交互 | P | P | P | P | 三个计算候选有表达力、图有 hyperedge；“未知组合显式 unresolved”和局部组合律均需合同。 |
| 17 | 治疗同时改状态与观察 | P | P | P | F | world model 有两通道骨架但需 typed action/effect；Transformer 条件 hidden update 没有两种正式 operator。 |
| 18 | 自然改善 vs 治疗作用 | H | P | P | F | 图可保留两个未决解释但不识别；其余若输出归因均需 causal assumptions，Transformer 条件序列最危险。 |
| 19 | 观察过期 | P | P | P | F | expiry/valid view 是事件语义；recurrent decay、recency attention 或窗口截断不等价。 |
| 20 | 新病在所有模板外 | P | P | P | F | OWA/生成能力都不是 OOD；需 coverage/refusal。Transformer 可生成新字符串也不等于识别模型外。 |
| 21 | 新增药物局部修改 | H | F | P | P | 图存储扩展局部；固定 world-model action space 常需改网/重训；twin/Transformer 需模块或 adapter contract。 |
| 22 | 新增检查不改核心 | H | F | P | P | C02 新 method node 局部；world encoder/signature 改变；其余需严格 schema/quarantine。 |
| 23 | 新理论重释旧证据 | P | F | P | F | 要 immutable raw events + versioned rules/models；latent/weights/hidden snapshots不可替代双版本重放。 |
| 24 | 删除原证据递归失效 | P | F | P | F | PROV 还需 TMS；latent/hidden state 无选择性撤回和独立支持证明。 |
| 25 | 任意历史点重放 | P | P | P | P | graph snapshot、model rerun、prefix attention 都要绑定双时间、模型/ontology、缓存和 seed。 |
| 26 | 安全规则不靠检索召回 | P | F | P | F | 必须 deterministic manifest/monitor；world-policy 会 exploit model error，RAG/attention 会漏召回。 |
| 27 | 两独立来源 vs 一源三改写 | P | F | P | F | occurrence/reifier 能承载 identity；其余压缩态没有 provenance semiring/根集合。 |
| 28 | 多个候选解释并存 | H | P | P | P | graph 原生非独占；world posterior/Transformer output 还需具名 hypothesis、支持/反对/unknown 与 roots。 |
| 29 | 无法表达必须显式报错 | P | P | P | F | SHACL/schema/quarantine 是通用补层；Transformer 通常仍投影到 embedding/token 并继续生成。 |
| 30 | 同义自然语言不改核心 | P | P | P | F | terminology/provenance adapter 必不可少；若语言 hidden state 就是 core，同义改写必然非同构。 |

### 4.1 矩阵摘要

- **C02：H=11 / P=19 / F=0 / U=0。** 没有 F 不是因为它完成了计算，而是宽容图几乎都能承载；19 个 P 正是“万能容器 ≠ 固定执行语义”的证据。
- **C12a：H=3 / P=19 / F=8 / U=0。** 原生强项集中在共同 latent cause、多潜因和 task readout；证据身份、扩展、重释、撤回、安全是硬缺口。
- **C12b：H=3 / P=27 / F=0 / U=0。** digital twin 是宽泛 system pattern，几乎所有细节由内部模型/数据治理决定；低 F 不能当高支持度。
- **C13：H=3 / P=13 / F=14 / U=0。** context、高阶交互和多任务 readout 强；作为权威事实 core 时在时间、血缘、开放世界、安全和语言不变性上系统性失败。

没有 U 是因为现有规范和原始论文足以判断**标准原语有没有该语义**；这不表示原型性能、人工审核负担或临床参数质量已经有证据。

---

## 5. 横向结论、原型建议与来源

### 5.1 同一个词在三家里不是同一个对象

| 词 | C02 | C12 | C13 | 必须保留的区分 |
|---|---|---|---|---|
| “state” | 截止某 cut 的 assertion subgraph/view | latent process state 或 belief；twin internal model state | hidden activation/KV cache | assertion view、患者真状态、系统 belief 和计算工作内存不能互换 |
| “edge/attention” | 声明式 relation/hyperedge | transition/decoder 的参数化依赖 | data-dependent weighted aggregation | association、生成依赖、因果边与 evidence support 不是同义词 |
| “memory” | persisted graph/claim history | recurrent latent / model parameter | context tokens/KV/parameter；RAG index | 可重放证据、预测充分统计量、计算 cache 和外部检索库不可混同 |
| “open” | 新 IRI/claim 可加入，OWA 不从缺失推出 false | 未知环境状态原则上可存在，但 signature/support 通常固定 | 可生成开放文本 | open vocabulary、open ontology、open-set refusal 和 model discrepancy 是四件事 |
| “trace” | source/derivation subgraph（若 occurrence identity 正确） | rollout trajectory | token/attention/activation trace | 执行轨迹不自动等于原始证据血缘 |

### 5.2 五个不能被“表达力”掩盖的硬攻击

#### 攻击一：隐向量审计

给同一输入一条温度记录、三条同义改写，再删除其中一个文本节点。要求输出：独立 evidence roots 数、所有依赖结论、仍有独立支持的结论。C12/C13 可以 rerun，但没有 source identity/TMS 时不能证明正确；C02 能保存 identity，却仍需根集合组合代数。**能做敏感性分析 ≠ 100% trace completeness。**

#### 攻击二：时间与可见性

`collected=08:00, result=positive, available=12:00`。在 09:00 replay：

- temporal edge 存 `08:00` 不够；
- RSSM 按 physiological time ingest 不够；
- causal attention mask 不够；
- 只有先按 `available<=09:00` 构造 evidence cut，再保留 valid time 指回 08:00，才合法。

该实验会判别谁拥有 bitemporal evidence semantics，谁只是事后把时间当 feature。

#### 攻击三：预测与干预

构造 indication confounding：重症者更常用药且结局更差。让 C12/C13 从观察序列学习，再问“给药是否改善”。若模型只给 conditional forecast，却被 UI 标成 treatment effect，属硬失败。C02 中存一条 `drug affects disease` 边同样不构成 `do()`。必须公开 causal identification status。

#### 攻击四：检索未召回

把一条罕见致命禁忌放在知识库但故意让 dense retriever top-k 漏掉、SPARQL federation endpoint 超时、materialization 落后一个版本。三家都必须报告不完整并由 independent invariant executor 拦截；空 query/retrieval 结果不得成为“没有禁忌”。

#### 攻击五：开放世界三分法

同时输入：

1. ontology 可表达但没有已知 disease model 的 observation；
2. schema 根本无法表达的新设备状态；
3. 已知模型都低支持的患者。

正确结果分别可能是 `known concept / out-of-atlas`、`schema_error/quarantine`、`insufficient/out_of_model`。OWL OWA、生成 likelihood、free-text generation 都不能自动完成此三分。

### 5.3 原语与补丁账本

| 版本 | 表面原语 | 要通过 HARD 测试还需 | 低原语假象/最坏代价 |
|---|---|---|---|
| 裸 RDF/OWL KG | node/IRI、triple、literal、entailment | occurrence identity、n-ary roles、multi-time、PROV/TMS、claim status、action/dynamics、OOD、validator/monitor | 所有东西能画成边，合法更新全部外包 |
| typed temporal hypergraph | entity、occurrence、role、type、claim status、time/version、view | transition/observation operator、probability/causality、TMS algebra、coverage/safety | relation/schema 膨胀；图中程序反客为主 |
| latent world model | latent/belief、action、transition、observation/reward decoder、readout | immutable bitemporal evidence、typed action lifecycle、provenance、causal gate、VVUQ/OOD、safety | latent 压缩使表面 core 小，审计和删除成本转到外层 |
| digital twin | counterpart、virtual representation、exchange/update、model/QOI、feedback | 取决于内部模型；几乎整个临床 semantic kernel 尚未规定 | 作为 system label 过宽，任何混合实现都可自称 twin |
| Transformer hidden core | token、embedding/position、QKV attention、MLP/update、mask/cache、head | canonical typed input、multi-time cut、provenance、dynamic/causal operator、OOD、deterministic invariant | 语义藏入全局权重；生成流畅但无静态合法性 |

### 5.4 进入统一原型的最小判别版本

不建议为 C02/C12/C13 各做一个“尽量强、但补丁预算不同”的大系统。应冻结同一输入和 companion budget，做以下三条可执行 track：

#### Track G：Typed Temporal Hypergraph

- occurrence-centered JSON/RDF-like hyperedges；
- valid/known/recorded/expiry；
- explicit source roots 与 PROV；
- graph queries 生成两个 task views；
- **故意不加入**动态/概率引擎，遇到需要 likelihood/causal effect 时显式 `UnsupportedOperator`。

这能测出 C02 是可靠事实/关系底座还是无约束万能图。

#### Track W：Latent World Model

- 小型非线性 stochastic state-space/RSSM；
- performed action 分别进入 transition 与 observation decoder；
- filtering + two-action rollout；
- 输出 latent posterior、predictive uncertainty 和 model version；
- 与一个相同模型但前置 evidence ledger、后置 coverage/causal/safety gate 的 `W+` 比较。

若只有 `W+` 通过血缘/回放/安全测试，能力应记在 companion，不得记 C12 H。

#### Track T：Transformer Readout Baseline

- 相同 typed events 序列化成 tokens；
- causal-mask as-of readout + 两个 task heads；
- 可选 RAG 仅做候选知识发现；
- 强制输出 evidence IDs，但验证这些 IDs 是 generator 猜的还是由 executor 约束的；
- 对 paraphrase、duplicate、retrieval miss、cache-cutoff 做 metamorphic tests。

若 Transformer 只有在输入先规范化为 typed canonical events 后才稳定，正确结论是“C13 是计算层”，不是“hidden state 是 core”。

### 5.5 必跑实验与量化项

1. **同源派生 + 撤回**：T06/T24/T27；删除根后 full recompute 与 incremental/TMS 结果完全一致。
2. **available-time replay**：T12/T13/T25；带未来内容的缓存故意注入，结果须与无缓存相同。
3. **support-treatment masking**：T01–T05/T17；输出 latent、observation、performed action 和各自 trace。
4. **world-model exploitation**：训练短 horizon 模型，让 optimizer 搜索误差；记录 simulator/held-out environment gap。
5. **see/do 反例**：治疗指征混杂；conditional 与 interventional API 必须不同类型。
6. **retrieval miss**：禁忌不进 top-k、endpoint failure、stale closure；invariant 仍执行，coverage failure 显式。
7. **open-world三分**：out-of-atlas、schema-error、insufficient 不得碰撞。
8. **extension blast radius**：新 drug、新 measurement method；记录 core files/branches、schema、retrain/reindex/rematerialize 范围。
9. **paraphrase metamorphism**：canonical facts 同构；hidden/raw representations 可不同但不得成为事实差异。
10. **expert audit**：对一个结论统计 source nodes、不可解释浮点运算、跨模型跳转和审核分钟数。

共同记录：Core primitive count、Special-case count、Extension blast radius、Trace completeness、Replay correctness、Collision、Spurious distinction、Illegal cycle、Unknown handling、Human audit burden、计算成本和近似误差。

### 5.6 当前 Pareto 判断（不是最终选型）

- **C02 最强实例保留**：在异构事实、角色、开放词汇、多假说、局部增图与任务 subgraph 上强；在动态、概率、因果、TMS 和安全执行上依赖补层。最合理角色是 semantic/evidence graph，而不是完整诊疗引擎。
- **C12a 保留为动态计算模块**：在 latent/observation/action、forecast、共同原因和 nonlinear rollout 上强；不能成为事实账本或因果有效性的唯一保障。
- **C12b 不作为独立 formal kernel 决赛候选**：保留为 deployment/lifecycle/VVUQ 参考架构；若不冻结内部 model contract，它无法与其他形式候选公平比较。
- **C13 作为唯一核心淘汰**：hidden state 与 attention 无法满足时间、证据守恒、开放世界、撤回和安全不变量；保留为 adapter、retrieval scheduler、approximate operator 和 readout。

目前没有证据支持把三家合称一个赢家。一个可能进入下一轮、但必须按 C15 重新计账的结构是：

```text
typed bitemporal evidence/occurrence graph
  + provenance/truth-maintenance/invariant semantics
  + versioned causal/dynamic world-model operators
  + Transformer only as adapter/scheduler/readout
  + digital-twin lifecycle/VVUQ envelope
```

这只是待原型证伪的组合假说；若能找到更小的共同原语同时给出这些硬语义，应优先压缩。

### 5.7 最强反对意见与推翻条件

#### 对 C02 保留意见的最强反对

occurrence-centered hypergraph 加到双时间、PROV、claim status、TMS 后已经接近事件账本/类型重写系统；“图”可能只是存储形状，不是不可约内核。若 C10/C09 用更少原语给出相同视图，应把 C02 降为 serialization。

#### 对 C12 模块化定位的最强反对

一个充分结构化、object-centric、causal、uncertainty-aware world model 也许能把 typed entities、multi-time belief、lineage-sensitive inference 和 modular dynamics统一在同一概率程序中。若统一原型无需独立 ledger/TMS 仍通过 T06/T12/T23–T27，应上调 C12。

#### 对 C13 淘汰核心的最强反对

Transformer 是 universal approximator，理论上可学习严格 interpreter；外部 constrained decoding、formal token language 和 proof-carrying generation 也许能使每步合法。若这些 proof/type/event objects成为权威，那么候选已经是“类型化形式内核 + Transformer executor”；只有在 hidden/QKV 本身能证明不变量时才应推翻本判断。

#### 明确推翻条件

1. C02 在不引入独立动态/因果/TMS/safety operator 的情况下通过全部 HARD 测试，并输出可复核执行语义；
2. C12 latent-only 原型能保留 source-root 幂等、任意删除、双版本 replay、可靠 OOD 和 deterministic safety，而不把完整事实账本藏在输入；
3. digital-twin 标准给出跨实现统一且可执行的临床 state/evidence/intervention semantics，而非只给 lifecycle/function views；
4. C13 对所有同义/重复/多时间/检索缺失测试有形式保证，attention/hidden trace 能满足而非近似 provenance contract；
5. 统一盲测显示上述补层的实现成本/人工负担大于一个更小候选，且后者无新增 silent failure。

---

## 6. 已核实的第一手/正式来源

> 链接于 2026-07-13 核对。每条只支持表中所写范围；架构判断是由规范原语与压力测试作出的推论。RDF 1.2 明确标为 Candidate Recommendation，不伪装成已完成 Recommendation。

### 6.1 图、时态、血缘与验证

| ID | 来源 | 本记录采用的证据范围 |
|---|---|---|
| G1 | W3C. *RDF 1.2 Concepts and Abstract Data Model*, Candidate Recommendation Snapshot 2026-04-07. [official](https://www.w3.org/TR/rdf12-concepts/) | triple/dataset、binary relation、triple term/reifier、同一 proposition 多 reifier；§1.6 明确 RDF model atemporal、graph 是 static snapshot。 |
| G2 | W3C. *OWL 2 Web Ontology Language Primer*, Recommendation 2012. [official](https://www.w3.org/TR/owl2-primer/) | open-world reasoning、声明式 ontology 的能力与其非数据库/程序/完整性验证边界。 |
| G3 | W3C. *Defining N-ary Relations on the Semantic Web*, Working Group Note 2006. [official](https://www.w3.org/TR/swbp-n-aryRelations/) | 二元 RDF relation 对 n-ary context 的间接建模模式；Note 而非规范性 Recommendation。 |
| G4 | Klamt S et al. *Hypergraphs and Cellular Networks*. PLoS Comput Biol 2009. [DOI](https://doi.org/10.1371/journal.pcbi.1000385) | hyperedge 保留 group identity；普通图投影可制造伪路径；hypergraph 算法问题依赖具体语义。 |
| G5 | Gutierrez C, Hurtado CA, Vaisman AA. *Introducing Time into RDF*. IEEE TKDE 2007. [DOI](https://doi.org/10.1109/TKDE.2007.34) | temporal labels、temporal entailment/query 是对 RDF 另加的正式扩展，反证标准 RDF 无原生时间推理。 |
| G6 | W3C. *PROV-DM: The PROV Data Model*. Recommendation 2013. [official](https://www.w3.org/TR/prov-dm/) | Entity/Activity/Agent、generation/use/derivation/invalidation 等血缘原语。 |
| G7 | W3C. *Constraints of the PROV Data Model*. Recommendation 2013. [official](https://www.w3.org/TR/prov-constraints/) | PROV validity/constraints；规范并不把应用自动变成 truth-maintenance executor。 |
| G8 | W3C. *SPARQL 1.1 Update*. Recommendation 2013. [official](https://www.w3.org/TR/sparql11-update/) | graph-store insert/delete/update 语义，不是生理状态转移或 `do()`。 |
| G9 | W3C. *Shapes Constraint Language (SHACL)*. Recommendation 2017. [official](https://www.w3.org/TR/shacl/) | data graph 对 shapes graph 的验证；是 companion validation，不是概率/动态/OOD 内核。 |
| G10 | W3C. *SPARQL 1.1 Federated Query*. Recommendation 2013. [official](https://www.w3.org/TR/sparql11-federated-query/) | `SERVICE` failure、`SERVICE SILENT` 与 remote endpoint；支持“空结果不可直接解释为不存在”。 |
| G11 | Gallo G et al. *Directed hypergraphs and applications*. Discrete Applied Mathematics 1993. [DOI](https://doi.org/10.1016/0166-218X%2893%2990045-P) | directed hypergraph 的结构/算法基础；不含临床执行语义。 |
| G12 | W3C. *RDF 1.2 Semantics*, Candidate Recommendation Snapshot 2026. [official](https://www.w3.org/TR/rdf12-semantics/) | graph model-theoretic semantics/entailment 范围；不把 mutable source state 当时间演化模型。 |
| G13 | Himmelstein DS et al. *Systematic integration of biomedical knowledge prioritizes drugs for repurposing*. eLife 2017. [DOI](https://doi.org/10.7554/eLife.26726) | Hetionet 展示 typed biomedical KG、heterogeneous integration 与 metapath readout；不证明 patient dynamics。 |
| G14 | Rotmensch M et al. *Learning a Health Knowledge Graph from Electronic Medical Records*. Sci Rep 2017. [DOI](https://doi.org/10.1038/s41598-017-05778-z) | EHR graph extraction有不完整性；概率来自额外 noisy-OR/Bayesian model，不是 graph incidence 自动产生。 |

### 6.2 世界模型与数字孪生

| ID | 来源 | 本记录采用的证据范围 |
|---|---|---|
| W1 | Ha D, Schmidhuber J. *Recurrent World Models Facilitate Policy Evolution*. NeurIPS 2018. [proceedings](https://papers.nips.cc/paper_files/paper/2018/hash/2de5d16682c3c35007e4e92982f1a2ba-Abstract.html), [author artifact](https://worldmodels.github.io/) | VAE latent + action-conditioned MDN-RNN + controller；“Cheating the World Model”实证显示 policy exploit model error。 |
| W2 | Hafner D et al. *Learning Latent Dynamics for Planning from Pixels (PlaNet)*. ICML/PMLR 2019. [paper](https://proceedings.mlr.press/v97/hafner19a.html) | RSSM、filtering posterior、latent planning，以及模型误差/多步/OOD 难点。 |
| W3 | Hafner D et al. *Dream to Control: Learning Behaviors by Latent Imagination*. ICLR 2020. [OpenReview](https://openreview.net/forum?id=S1lOTC4tDS) | 在 imagined latent trajectories 上训练 actor/critic；world model 与 decision layer 可区分。 |
| W4 | Hafner D et al. *Mastering Atari with Discrete World Models (DreamerV2)*. ICLR 2021. [conference](https://iclr.cc/virtual/2021/poster/2742) | categorical latent/RSSM；离散 latent 不自动成为具名语义变量。 |
| W5 | Hafner D et al. *Mastering Diverse Control Tasks through World Models (DreamerV3)*. Nature 2025. [DOI](https://doi.org/10.1038/s41586-025-08744-2) | encoder、recurrent/stochastic latent、dynamics/decoder/reward/continue 与 actor/critic 的现代实现；不证明临床因果有效。 |
| W6 | Locatello F et al. *Challenging Common Assumptions in the Unsupervised Learning of Disentangled Representations*. ICML/PMLR 2019. [paper](https://proceedings.mlr.press/v97/locatello19a.html) | 缺少 inductive bias 时无监督 disentanglement 不可识别；限制“latent 自然可解释”主张。 |
| W7 | Nalisnick E et al. *Do Deep Generative Models Know What They Don't Know?* ICLR 2019. [OpenReview](https://openreview.net/forum?id=H1xwNhCcYm) | 多类生成模型可能给 OOD 数据更高 likelihood；likelihood 非 coverage 证书。 |
| W8 | Pearl J. *An Introduction to Causal Inference*. Int J Biostat 2010. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC2836213/) | observation/conditioning、intervention 与 counterfactual 的区别及识别假设。 |
| W9 | Glaessgen E, Stargel D. *The Digital Twin Paradigm for Future NASA and U.S. Air Force Vehicles*. 2012. [NASA NTRS](https://ntrs.nasa.gov/citations/20120008178) | specific counterpart、多物理模型、sensor/fleet/maintenance data 与 lifecycle mirror 的基础定义。 |
| W10 | ISO/IEC 30173:2023. *Digital twin — Concepts and terminology*. [official catalog](https://www.iso.org/standard/81442.html) | 只采用公开摘要中的术语、context/lifecycle/type/function views；未核实付费全文细则。 |
| W11 | National Academies. *Foundational Research Gaps and Future Directions for Digital Twins*. Consensus Study Report 2024. [official](https://www.nationalacademies.org/publications/26894) | physical–digital dynamic coupling/双向流；UQ、discrepancy、causality、identifiability、assimilation 等研究缺口。 |
| W12 | NIST. *Digital Twins*. [official program](https://www.nist.gov/digital-twins) | forecasting、systems-of-systems、模型维护与 lifecycle 方向；没有统一临床 semantic calculus。 |
| W13 | Corral-Acero J et al. *The ‘Digital Twin’ to enable the vision of precision cardiology*. Eur Heart J 2020. [PMC](https://pmc.ncbi.nlm.nih.gov/articles/PMC7774470/) | 医疗 twin 的 mechanistic/statistical/individual-data 愿景与转化现状；position paper，不作临床验证证书。 |
| W14 | Björnsson B et al. *Digital twins to personalize medicine*. Genome Med 2020. [DOI](https://doi.org/10.1186/s13073-019-0701-3) | 个体模型进行药物模拟的愿景；不是通用患者内核实证。 |
| W15 | ASME V&V 40-2018. *Assessing Credibility of Computational Modeling through Verification and Validation: Application to Medical Devices*. [official](https://www.asme.org/codes-standards/find-codes-standards/assessing-credibility-of-computational-modeling-through-verification-and-validation-application-to-medical-devices) | context-of-use/risk-informed model credibility；不是 state architecture。 |
| W16 | FDA. *Assessing the Credibility of Computational Modeling and Simulation in Medical Device Submissions*, Guidance 2023. [official](https://www.fda.gov/regulatory-information/search-fda-guidance-documents/assessing-credibility-computational-modeling-and-simulation-medical-device-submissions) | physics/mechanistic CM&S 的 risk-informed credibility framework；不为任意 ML patient twin 背书。 |

### 6.3 Transformer、attention、检索与开放集

| ID | 来源 | 本记录采用的证据范围 |
|---|---|---|
| T1 | Vaswani A et al. *Attention Is All You Need*. NeurIPS 2017. [proceedings](https://proceedings.neurips.cc/paper_files/paper/2017/hash/3f5ee243547dee91fbd053c1c4a845aa-Abstract.html) | scaled dot-product/multi-head attention、position、decoder mask 与 seq2seq 计算边界。 |
| T2 | Dehghani M et al. *Universal Transformers*. ICLR 2019. [OpenReview](https://openreview.net/forum?id=HyzdRiR9Y7), [arXiv](https://arxiv.org/abs/1807.03819) | self-attentive recurrent computation/反复更新；depth recurrence 不是临床 process time。 |
| T3 | Dai Z et al. *Transformer-XL: Attentive Language Models beyond a Fixed-Length Context*. ACL 2019. [ACL Anthology](https://aclanthology.org/P19-1285/) | segment recurrence、relative positional encoding 与长依赖；cache/long context 不是证据账本。 |
| T4 | Yun C et al. *Are Transformers universal approximators of sequence-to-sequence functions?* ICLR 2020. [OpenReview](https://openreview.net/forum?id=ByxRM0Ntvr) | 紧集上 sequence-function universal approximation；表达力不提供领域语义/不变量。 |
| T5 | Jain S, Wallace BC. *Attention is not Explanation*. NAACL 2019. [ACL Anthology](https://aclanthology.org/N19-1357/) | 标准 attention 与 feature importance/替代 attention 的实证；用于拒绝“attention 自动等于 provenance”。 |
| T6 | Wiegreffe S, Pinter Y. *Attention is not not Explanation*. EMNLP 2019. [ACL Anthology](https://aclanthology.org/D19-1002/) | 对 T5 的定义/诊断反驳；支持谨慎结论：attention 可有解释用途，但不自动满足形式血缘。 |
| T7 | Pearl J. *Causal Diagrams for Empirical Research*. Biometrika 1995. [DOI](https://doi.org/10.1093/biomet/82.4.669) | 条件关联与干预因果效应、可识别性边界。 |
| T8 | Lewis P et al. *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks*. NeurIPS 2020. [proceedings](https://proceedings.neurips.cc/paper/2020/hash/6b493230-Abstract.html) | parametric + dense-index memory、生成条件化于 retrieved passages；论文明确 provenance/knowledge update 仍是开放问题。 |
| T9 | Scheirer WJ et al. *Toward Open Set Recognition*. IEEE TPAMI 2013. [DOI](https://doi.org/10.1109/TPAMI.2012.256) | closed-set 与 unknown/open-space risk 区别；支持“开放文本生成不等于开放集拒答”。 |

## 7. 给候选综合表的精简条目

```text
C02 strongest instance:
  occurrence-centered typed bitemporal hypergraph
  Role: semantic/evidence/claim substrate and task-view source
  Native: heterogeneous roles, open vocabulary, multiple hypotheses, local graph growth
  Missing: executable dynamics, do/probability, TMS, coverage/OOD, safety monitor
  Status: retain as substrate; reject naked graph as complete core

C12a:
  versioned action-conditioned stochastic latent world model
  Role: belief update, forecast, imagined treatment trajectories
  Native: latent/observation/action split, nonlinear dynamics, joint latent causes, readouts
  Missing: authoritative evidence, bitemporal replay, causal identification, OOD/VVUQ,
           exact deletion, local extension, deterministic safety
  Status: retain as replaceable dynamic module; reject as sole authority

C12b:
  physical-digital coupled lifecycle system pattern
  Role: deployment/synchronization/VVUQ envelope
  Native: counterpart identity, assimilation, simulation/QOI, feedback lifecycle
  Missing: one fixed formal state/evidence/intervention semantics
  Status: do not rank as independent formal kernel until internal model contract is frozen

C13:
  token/embedding + attention/recurrent hidden update + readout
  Role: adapter, scheduler/retriever, approximate computation, multi-task readout
  Native: contextualization, high-order learned interaction, flexible task heads
  Missing: typed clinical ontology, multi-time, do(), provenance/TMS, OOD, hard invariants
  Status: reject hidden/QKV as sole core; retain as optimization/execution component
```
