# 动态临床状态与诊疗计算：候选架构地图

> **状态：post-experiment 候选地图。** 本文依据 `research_notes/02_state_models.md` 至 `08_graph_world.md` 的已核实研究，统一 13 个候选家族的边界、问卷、硬淘汰、组件保留和 Pareto 位置；其中 3 个原子候选已实现并进入 v3 隔离实验。结论是**没有原子赢家**，条件性研究参考选择为 `K0 + 显式异构能力子内核`；详细裁决见 `DECISION.md`。逐项模板与证据映射见 `research_notes/12_candidate_synthesis.md`，外部来源见 `SOURCES.md`。

## 1. 比较合同

### 1.1 三种“状态”必须分开

任何候选若把以下三者压成同一对象，先判为语义风险而不是“统一”：

1. **PatientTrueState**：现实患者的隐藏生理/病理状态或路径；
2. **SystemBelief**：基于某一 evidence/knowledge cutoff 与 model version 的 posterior、hypotheses 或估计；
3. **AuthoritativeRecord**：发生过的观察、陈述、动作、来源、版本、更正和撤回记录。

一个 belief 可以是预测/决策的充分统计量，却通常不是审计的充分统计量。一个事件日志可以完整记录当时知道什么，却不等于患者真实生理状态。一个 latent trajectory 可以预测未来，却不能替代原始证据身份。

### 1.2 统一问卷

每个真正候选都必须显式回答同一 13 项，不能用“图/程序/向量能编码一切”回避：

1. **原语**：固定 kernel primitives 是什么？
2. **状态**：真实状态、知识态、持久记录分别在哪里？
3. **时间**：过程时间与 occurrence/collected/available/recorded/valid/expiry 如何区分？
4. **观察**：原始观察、患者陈述、潜态估计、推断和假说是否分型？
5. **干预**：planned/ordered/performed 是否分开；conditioning 与 `do()` 是否是不同运算？
6. **不确定性**：数值分布与 unknown/conflict/not-applicable/out-of-model 是否都可表达？
7. **共病**：共享状态、非线性交互和“未声明组合”怎样处理？
8. **血缘**：原始证据 identity、同源去重、推导路径、版本和撤回是否可追？
9. **扩展**：新增疾病、药物、检查、对象或任务的 core/readout blast radius 多大？
10. **任务坐标**：诊断、严重度、安全、预后、反事实如何从同一核心生成不同 readout？
11. **天然优势**：哪些是标准原语自然提供，而非外挂？
12. **补丁**：通过硬要求还需哪些通用层；补完后核心身份是否已改变？
13. **最坏失败**：系统会拒绝、显式报错，还是静默给出高置信错误？

### 1.3 状态标记

| 标记 | 含义 |
|---|---|
| **H-CORE** | 作为**唯一完整固定临床核心**硬淘汰；不等于其组件价值为零 |
| **R-COMP** | 保留为分层架构中的组件、合同或执行后端 |
| **P-PROT** | 在至少一个硬维度上不被支配，进入过原型化 shortlist；实际是否实现见第 7 节，不表示胜出 |

原子家族可以同时是 `H-CORE + P-PROT`：整核不合格，但某个窄语义进入 Pareto。`P-PROT` 是 selection-history 标记，不表示 13 家族都写了代码；本轮实际实现 3 个聚合 profile，见第 7 节。本文没有 `WINNER` 状态。

## 2. 去重规则：什么不算一个新家族

1. **SSM 与 POMDP 分开**：SSM 的承诺是 hidden state/transition/observation/filter；POMDP 再加入 action、utility/constraint、policy 和信息价值。
2. **DBN 与 SSM 不互相冒充**：DBN 首先是有向 factored probability；SSM 首先是状态过程与 observation contract。具体模型可同时属于两者，但自然强项和失败面不同。Factor graph 只是 factorization/inference IR，不单列动态候选。
3. **SCM 与普通 PPL 分开，causal PPL 不虚增世界模型**：SCM 定义 mechanism replacement、`do` 与 AAP；普通 PPL 只有随机程序和 conditioning；causal PPL 作为 SCM/AAP 的可执行器参与对照，不另算一套患者世界本体。
4. **Event Calculus 与 Situation Calculus 合为一个超族**：前者偏异步事件与 inertia，后者偏动作历史与 successor-state axioms；只有证明不可替代收益才同时实现。LTL/MTL/TLA 是验证层，不是动态候选。
5. **Petri 与 reaction network 只计一个骨架**：二者共享多重集状态、局部消耗/产生和 incidence/stoichiometric update；token firing、ODE 和 CTMC 是运行语义，不是两个核心。
6. **类型/ADT/refinement/effect 不计动态候选**：它们约束合法状态、行动和 capability，却不定义患者如何演化。
7. **裸 category/operad/cospan/sheaf 不计**：只有带具体 private state/update/readout 的 open machines，或 sections 本身是时间行为的 temporal sheaf，才可审计为候选。
8. **World Models/PlaNet/Dreamer 归入 learned SSM/POMDP**：稳定原语是 belief update、action-conditioned latent transition、observation/outcome heads 和 rollout；VAE、RSSM、RNN、GRU、Transformer 是实现。
9. **Transformer/QKV 不单列世界语义**：它是 encoder、transition、近似推断、检索/调度或 readout 算法。hidden/KV state 不自动成为可审计患者状态。
10. **Digital twin 不凭名称单列 formal kernel**：它是 physical–digital synchronization、模型集成、生命周期和 VVUQ 治理模式；内部模型未冻结前没有统一 calculus。

## 3. 十三个真正不同的候选家族

| ID | 家族 | 区别性骨架 | 当前状态 |
|---|---|---|---|
| D01 | DBN / CTBN | 时间重复的局部 CPD 或条件强度矩阵分解联合动态 | `H-CORE + P-PROT` |
| D02 | 广义 SSM / SDE / hybrid state space | hidden process、transition、observation、belief/filtering | `H-CORE + P-PROT` |
| D03 | POMDP / constrained POMDP | 在 D02 上增加 action、objective、policy 与约束 | `H-CORE + P-PROT` |
| D04 | Dynamic SCM | 结构方程、mechanism replacement、`do`、AAP counterfactual | `H-CORE + P-PROT` |
| D05 | 开放宇宙关系式因果过程 | 对象数、identity 和关系实例可随机生成并演化 | `H-CORE + R-COMP` |
| D06 | Event / Situation Calculus 超族 | event/action 经 inertia 或 successor-state axioms 改变 fluent | `H-CORE + R-COMP` |
| D07 | Temporal Evidence Ledger | 不可变多时间事件、provenance、rule version、projection、withdrawal | `H-CORE + P-PROT` |
| D08 | 多重集变迁 / Petri–reaction 骨架 | marking/count/concentration 经局部 stoichiometric transition 演化 | `H-CORE + P-PROT` |
| D09 | 进程代数 | residual process 经 prefix/choice/parallel/sync/hiding 形成 LTS | `H-CORE + R-COMP` |
| D10 | Typed Rewriting Logic | 项代数 modulo equations 经带标签局部规则变迁和搜索 | `H-CORE + P-PROT` |
| D11 | Positive Temporal Datalog + provenance/TMS | EDB 经 Horn rules 得到最小不动点 IDB，并支持撤回重物化 | `H-CORE + P-PROT` |
| D12 | 类型化开放组合动态机器 | 带状态行为的组件按 typed ports/wiring/boundary gluing 组合 | `H-CORE + P-PROT` |
| D13 | Temporal sheaf / behavioral system | 局部时间/上下文 sections 经 restriction 与 gluing 检查全局行为 | `H-CORE + R-COMP` |

以下逐项都使用同一模板；原始来源和长版反例见对应 `research_notes/02–07` 与 `12_candidate_synthesis.md`。

### D01. DBN / CTBN

- **原语/状态**：有域随机变量、局部 CPD/conditional intensity、时间模板、evidence；患者真状态是变量赋值，知识态是 posterior。
- **时间/观察/干预**：DBN 用离散 slices，CTBN 用连续时间 jump；都缺知识可见/记录时间。观察是 evidence node/factor；普通 DBN 的条件分布不是 `do`，需 SCM/影响图。
- **不确定性/共病**：联合 posterior、多峰和 missing marginalization 原生；共享 latent causes、交互因子可表达共病，但 treewidth/基数会爆炸。
- **血缘/扩展/任务**：模型边不是 evidence provenance；需 source IDs 和 derivation DAG。加局部因子看似局部，junction tree/近似器可能全局变化。任务以 marginal/MAP/expected utility query 生成。
- **优势/补丁/失败**：强在共享原因、多个解释和 factorized inference；补 causal action、多时间、撤回、OOD、安全与数值诊断。最坏是结构错、同源 evidence 相乘、loopy approximation 仍给极自信 posterior。**状态：P-PROT。**

### D02. 广义 SSM / SDE / hybrid state space

- **原语/状态**：latent state、initial belief、transition/dynamics、observation kernel、filter/smoother；真实患者是假定存在的隐藏路径，belief/particles 是系统不确定性。
- **时间/观察/干预**：离散、ODE/SDE、jump/hybrid 均可；过程时间不等于结果采集/发布/记录/过期。观察由可依赖设备/支持治疗的 `Z` 生成；control 可改 transition 与 observation channel。
- **不确定性/共病**：process/measurement noise、belief、参数 posterior 原生；单一随机 latent 不等于 epistemic/OOD。共病可用 factorized state、modes 和耦合 drift，但无默认组合律。
- **血缘/扩展/任务**：belief 不是审计充分统计量，旧证据撤回需 event log + checkpoint replay。新检查/action/mode 可能改全局 signature。支持 filter、forecast、hazard、多个 readout。
- **优势/补丁/失败**：最自然地区分潜态和观察，处理 stale evidence 与连续预测。补 bitemporal ledger、causal identification、provenance、open-set、组合接口和硬安全。最坏是治疗掩蔽被当改善，混杂 action effect 进入闭环。**状态：P-PROT。**

**World-model 子型**：World Models/PlaNet/Dreamer 是 learned nonlinear D02；若再用 MPC/actor/critic 则跨入 D03。生成 likelihood、逼真 rollout 和 stochastic latent 都不是 coverage、causal validity 或 evidence lineage 证书；“cheating the world model”说明 policy 会主动利用模型误差。

### D03. POMDP / constrained POMDP

- **原语/状态**：D02 的 state/transition/observation/belief，加 action、reward/cost、policy；安全版本再加 explicit constraints/shield。
- **时间/观察/干预**：通常按 decision epochs；检查动作产生信息，治疗动作改变过程。planned/authorized/performed 仍需分型，观察数据学得的 action kernel 仍需因果验证。
- **不确定性/共病**：belief 与随机转移/观察原生；model uncertainty、distribution shift、effect identifiability 需另列。factored/hybrid state 可放共病，但联合 action/state 空间爆炸。
- **血缘/扩展/任务**：policy 所用 belief 不保存逐证据 lineage；新 action、constraint、observation 会改变规划空间。任务原生包括 value of information、treatment value 和 risk-constrained policy。
- **优势/补丁/失败**：强在“下一项检查还是立即治疗”的闭环决策；补 causal effect、event/provenance、hard constraints、OOD/refusal、policy uncertainty。最坏是错误 reward/model 被策略放大，闭世界 belief 仍归一化为 1。**状态：P-PROT；本轮未实现，保留为后续 policy 层候选。**

### D04. Dynamic SCM

- **原语/状态**：外生/内生变量、结构函数、外生分布、机制版本、submodel/intervention、causal query；事实世界状态是方程解，知识态是 `P(U,V|evidence)`。
- **时间/观察/干预**：用 time-indexed variables、dynamic/cyclic equations；标准 SCM 无 available/recorded time。观察应经过 explicit measurement mechanism；hard `do` 替换方程，药物更常是 soft/mechanism intervention。
- **不确定性/共病**：`P_U`、参数/模型 posterior；unknown/conflict/identification failure 需类型。共病由共享机制和非线性结构函数组合，交互必须显式。
- **血缘/扩展/任务**：causal parents 不是文档/派生 provenance。加变量/混杂/反馈可能改旧函数。任务自然分 observational、interventional、counterfactual；个体反事实走 abduction→action→prediction。
- **优势/补丁/失败**：conditioning 与 doing、同一患者多世界语义不可替代。补 typed evidence、多时间 replay、provenance、identification status、coverage/OOD、循环解和 inference diagnostics。最坏是拟合好但结构错，给出高置信错误干预。**状态：P-PROT。**

**执行对照**：causal PPL 可把 mechanism、intervention point、多世界共享和 AAP 编成可执行程序；它是 D04 的强 executor，不因 `sample/observe` 或 effect handler 自动解决 identification、时间与 provenance。

### D05. 开放宇宙关系式因果过程

- **原语/状态**：types、relations/random functions、对象生成、未知 object count/identity、关系模板与 causal laws；possible world 同时包含对象集合和赋值。
- **时间/观察/干预**：时间索引或 causal event order；缺 bitemporal history。观察可推断多个记录是否指同一未知对象；`do/AAP` 取决于具体 causal extension。
- **不确定性/共病**：对象数、identity、relations 和参数 posterior；概念级 unknown 仍不原生。多个病灶/机制可实例化并共享对象，交互仍需 law。
- **血缘/扩展/任务**：object identity posterior 不是 source identity。新实例可按需生成，但新 predicate/type 仍改模型签名。适合 linkage、病灶计数、关系与 causal query。
- **优势/补丁/失败**：强在未知对象和身份歧义。补概念 OOD、多时间、provenance、identification、可计算限制和安全。最坏是对签名内无限对象灵活，却把签名外新病强配为已知；或推断不可判定。**状态：R-COMP。**

### D06. Event / Situation Calculus 超族

- **原语/状态**：EC 的 event/fluent/happens/initiates/terminates/holdsAt/inertia；SC 的 situation/action/`do(a,s)`/successor-state axiom。状态是成立 fluent 或动作历史所到 situation。
- **时间/观察/干预**：EC 适合异步 event/interval，SC 偏串行动作历史；均缺知识/记录时间。瞬时观察不能默认无限 inertia；只有 performed event/action 改状态。
- **不确定性/共病**：标准逻辑无 calibrated posterior；禁止用 negation-as-failure 表示临床阴性。共病是并行 fluents 与 context-dependent effect axioms，ramification/interaction 要显式。
- **血缘/扩展/任务**：逻辑因果路径不是 artifact/source provenance；加 axioms 可能非局部冲突。任务是 holds-at、历史状态、动作可执行性、planning/regression。
- **优势/补丁/失败**：强在惯性、事件起止、迟到的过去事件和“动作是否发生”。补 bitemporal ledger、provenance/TMS、概率 observation、规则版本和连续 dynamics。最坏是未见即未发生、旧观察永久有效、ramification explosion。**状态：R-COMP。**

### D07. Temporal Evidence Ledger（TEL）

- **原语/状态**：Subject/Object、EventVersion、TypedTime、Claim、ProvenanceToken、RuleVersion、Projection、Invariant/QueryCut；不可变 journal 是记录源，状态视图是可重建 projection。
- **时间/观察/干预**：occurrence/collected/actor-available/recorded/valid/expiry/invalidation 分型。观察是带 method/device/specimen/context/source 的 occurrence；planned/ordered/administered/stopped 分开，只有 performed 产生 effect。
- **不确定性/共病**：最低支持正/反证据四态与 missing reasons；概率另层。并行 hypotheses 与版本化 interaction rules 可保留共病时序，但不估计强度。
- **血缘/扩展/任务**：幂等 root-source set + derivation DAG；retraction 发 negative delta，经 IVM/TMS 失效。新 schema/rule/projection 不改 journal。明确分 `replay_as_then` 与 `reinterpret_now`。
- **优势/补丁/失败**：时间、未来隔离、法证 replay、版本、同源去重、撤回最强。补 latent dynamics、likelihood、causal effect、OOD；必须验证 incremental=full recompute。最坏是 reducer 变万能逻辑、availability 伪精确、新规则改写过去。**状态：P-PROT。**

### D08. 多重集变迁 / Petri–reaction 骨架

- **原语/状态**：typed place/species、marking/count/concentration、transition/reaction、pre/post stoichiometry、guard/rate/propensity、open ports。
- **时间/观察/干预**：timed firing、ODE 或 CTMC process time；无采集/可见/记录时间。观察是 label/token/state observable，不是 measurement likelihood。干预可 firing、改 rate/initial/input、抑制 reaction。
- **不确定性/共病**：nondeterminism、SPN/CTMC aleatory；非 epistemic posterior。子网并置、共享 species、多输入反应和反馈自然表达非线性共病。
- **血缘/扩展/任务**：marking/浓度聚合会丢来源；unfolding 是过程偏序而非 clinical provenance。加局部 transition 不改 solver，但共享 species/rate 可全局影响。任务含 reachability、invariant、steady state、hazard。
- **优势/补丁/失败**：强在资源、守恒、非负性、并发和机制非线性。补 event ledger、observation/filter、TMS、OOD、task readout 和 delay。最坏是 `0` 混合不存在/未测、参数不可辨识、state/reaction explosion。**状态：P-PROT；本轮未实现；未来若实现，Petri 与 CRN 只计一个骨架。**

### D09. 进程代数

- **原语/状态**：action、prefix、choice、parallel/synchronization、restriction/hiding、renaming、recursion；状态是 residual process/LTS node。
- **时间/观察/干预**：经典 CCS/CSP 无定量时间；Timed/PEPA 是扩展。visible action/`τ` 表达行为可见性，不是 measurement model；干预擅长协议编排，不给生理 effect。
- **不确定性/共病**：nondeterministic/probabilistic/Markov choice 取决于 calculus；非 epistemic posterior。`P||Q` 和 channel 共享表达并发交互。
- **血缘/扩展/任务**：trace 有 action 顺序，但 hiding/weak equivalence 会抹内部来源。新 process 经接口加入；alphabet/synchronization/state product 仍扩散。任务为 observer、refinement、safety/liveness。
- **优势/补丁/失败**：强在工作流、并发、deadlock、组件协议。补 typed clinical store、多时间、provenance/TMS、probability filter。最坏是连续生理变巨型 process、同步冒充异步病历、行为 quotient 抹审计。**状态：R-COMP。**

### D10. Typed Rewriting Logic

- **原语/状态**：typed terms/sorts、equations、labeled guarded rewrite rules、configuration、strategy/search；状态建议分 History、MaterializedClaims、PendingActions、RuleSetVersion。
- **时间/观察/干预**：显式 clock/as-of 与 tick rules；观察是 immutable term；Planned/Authorized/RequestSent/Administered 是不同项与 capability transition。
- **不确定性/共病**：非确定分支或概率重写需显式；multiset configuration 和 multi-term LHS 可写并发/非线性交互。
- **血缘/扩展/任务**：必须由类型强制 RHS 携带 rule/version/premise/root sources。加 module/rule 可局部，却可能破坏 termination/confluence/coherence。任务含 normalization、readout rewrite、reachability、counterexample。
- **优势/补丁/失败**：局部可执行变化、搜索和模型检查强。补 bitemporal/provenance discipline、TMS、概率、确定 materialization、open-world。最坏是 rule order 决定结论、循环不终止、strategy/priority 变医学 hardcode。**状态：P-PROT。**

### D11. Positive Temporal Datalog + provenance/TMS

- **原语/状态**：typed EDB facts、Horn rules、least fixpoint IDB、query、explicit polarity、provenance/TMS/IVM；版本化 EDB 是源，IDB 是派生视图。
- **时间/观察/干预**：关系参数与强制 `available_at<=as_of` guard。Observation/Statement/Hypothesis 分谓词；planned/ordered/administered 分谓词，执行需 capability/receipt。
- **不确定性/共病**：正/负支持四态优先；possible worlds/ASP/probability 必须声明具体语义。多前提/递归规则可写 interaction，但会组合爆炸。
- **血缘/扩展/任务**：semiring/derivation DAG + 幂等 root set；DRed/ATMS 支持 alternative supports 和撤回。加 facts/rules/views 通常不改 evaluator；任务是 query/materialized view。
- **优势/补丁/失败**：声明式推导、解释、固定点、incremental materialization 强。补 continuous/probabilistic/causal dynamics、conflict policy、预算。最坏是 NAF 把 unknown 变阴性、多/无 stable model 静默压一、provenance 爆炸。**状态：P-PROT。**

CHR 是约束多集重写，归入 D08/D10 的实现参考；ASP 若参赛必须作为非单调 possible-world solver 单列合同，不能偷并入本条 positive Datalog 基线。

### D12. 类型化开放组合动态机器

- **原语/状态**：typed ports、private state、input/output、behavior/update/readout、operadic wiring/structured boundary gluing、explicit interaction component。
- **时间/观察/干预**：时间由具体 behavior 提供，组合语法无 knowledge clocks。Port 必须带 epistemic role/unit/subject/context/clock。Action port 与 state/observation effect 分开，并验证 feedback well-posedness。
- **不确定性/共病**：由组件 behavior 的 relation/probability/set 决定。共病通过 shared boundaries 与 interaction boxes；平行组合不会自动产生非线性交互。
- **血缘/扩展/任务**：只有 trace-preserving morphism/readout 保留 lineage。稳定接口下新增组件局部，但 port/interaction/readout 可成为新爆炸点。任务为 versioned trace-preserving maps。
- **优势/补丁/失败**：局部互连、层级组合、替换和状态/输入/输出分离最强。补 event ledger、epistemic ADT、TMS、action lifecycle、OOD、feedback validator。最坏是数学上 coherent 地组合错误模块，或每对病都要专属 glue。**状态：P-PROT。**

### D13. Temporal sheaf / behavioral system

- **原语/状态**：context/time category、presheaf/sheaf、local section、restriction、cover、matching family、gluing/global section；状态是局部 behaviors 与兼容关系，不保证有单一全局 state。
- **时间/观察/干预**：time intervals/contexts 为 base objects，restriction 缩到子区间；无 knowledge clocks。观察是 local section；干预可改变 behavior/context，但无标准 `do` 或 action lifecycle。
- **不确定性/共病**：多个/不存在 global sections 可表达歧义/不一致；probability/noisy gluing 需 measure/metric。共病通过共享 overlap 匹配，interaction dynamics 不自动生成。
- **血缘/扩展/任务**：restriction diagram 是 consistency witness，不是 source provenance。新 context/cover 可加，但 topology 改变可能重写结论。任务是 compatibility/global-section/obstruction query。
- **优势/补丁/失败**：强在保留局部语境和发现跨上下文不一致。补 event/provenance、dynamic generator、causal/probability、OOD。最坏是错误 topology 得到完美伪一致，nearest-section 平滑真实冲突。**状态：R-COMP。**

## 4. 重要表示、执行和部署主张：保留但不计为动态家族

| 主张 | 严格定位 | 状态与最坏失败 |
|---|---|---|
| 向量/张量 | 计算视图、缓存、模型输入、task projection | `H-CORE + R-COMP`；语义碰撞、来源丢失、同源多票后仍高置信 |
| Factor graph | D01 等模型的无向 factorization/message-passing IR | `H-CORE + R-COMP`；无方向图不自带时间、因果或动态 |
| 普通 PPL | probabilistic model/inference 宿主 | `H-CORE + R-COMP`；`sample/observe` 实现错误 query 仍可收敛 |
| RDF/OWL KG | 术语、本体、二元声明、交换和查询 | `H-CORE + R-COMP`；path/association 被误读成 causal dynamics |
| occurrence-centered typed bitemporal hypergraph | 事实发生、n-ary roles、claim status、多时间、versioned graph views | `H-CORE + P-PROT` 事实 substrate；图能存程序不等于会执行、撤回或做概率/因果 |
| ECS | runtime data layout、批处理、并行执行 | `H-CORE + R-COMP`；component presence/system order 变隐性医学真值 |
| 黑板/shared workspace | 异构模块/agent 协作与调度 | `H-CORE + R-COMP`；scheduler score 变 posterior，模块自证循环 |
| Transformer/QKV | adapter、context model、retrieval/scheduling、operator parameterization、readout | `H-CORE + R-COMP`；未来泄漏、同源增信、attention 伪 provenance、top-k 漏禁忌 |
| Digital twin | physical–digital lifecycle、assimilation、model services、feedback、VVUQ/context-of-use | R-COMP system pattern；“twin”品牌掩盖内部未经验证回归器 |

最强事实图应以每次 observation/action/claim **occurrence identity** 为中心，而不是用同一 proposition triple 合并多次独立测量；但它仍是 assertion view，不是 latent physiology。它与 D07 TEL 可以在实现中重叠：前者规定事实和 n-ary roles 如何表示，后者规定 version event 如何按 knowledge cut、rule version 和 negative delta replay/withdraw。能力必须逐项归属。

## 5. 正交必需元层，不计动态候选

| 元层 | 固定合同 |
|---|---|
| Type/ADT/refinement/typestate | unknown/negative/conflict/not-applicable/out-of-model；unit/subject/context；planned→authorized→performed |
| Effect/capability | read/write/execute 权限、外部副作用、receipt、fail-closed |
| LTL/MTL/TLA/model checking | future-leak、action lifecycle、安全/活性、deadline、replay invariant |
| Numerical diagnostics | convergence、ESS/residual/error bound、approximation 与 model version |
| Coverage/OOD/VVUQ | support domain、model discrepancy、context of use、abstention/refusal |
| Identity/unit/schema registry | canonical concept、evidence occurrence、source group、unit、schema error |

这些可能进入最终固定核心，但不得给某个动态候选“免费加分”；动态候选也不能因通用表达力声称已经自然吸收它们。

## 6. 硬淘汰与当前 Pareto

### 6.1 已硬淘汰的宣传版本

以下主张不再进入原型争论，除非出现直接推翻相应反例的新证据：

1. 一个高维向量/embedding 同时充当事实、患者状态、时间、证据和决策核心；
2. 普通 PPL 的 conditioning 天然等于 `do`/个体 counterfactual；
3. RDF/OWL/超图能存方程，所以图本身已执行动态、撤回、概率与安全；
4. Petri 与 reaction network 是两个独立骨架，或把 ODE/CTMC 能力无成本记给普通 P/T net；
5. 类型系统、时态逻辑、裸范畴/operad/sheaf 本身就是患者演化模型；
6. ECS、黑板、Transformer hidden/KV state 是唯一权威临床事实源；
7. attention、execution trace、causal DAG、graph path 自动等于 evidence provenance；
8. digital twin 名称、逼真 rollout 或高 likelihood 自动保证 causal validity、coverage、VVUQ 和安全；
9. OWL open-world、无限对象或可生成新字符串等于概念级 OOD 与安全拒答。

### 6.2 分维度 Pareto 前沿

| 维度 | 当前候选 | 不能抵消的缺口 |
|---|---|---|
| 概率分解/多解释 | D01 | causal、knowledge time、provenance |
| latent/observation separation 与 forecast | D02 | event ledger、identification、lineage |
| sequential information/treatment decision | D03 | effect validity、hard safety proof |
| intervention/AAP | D04 + causal-PPL executor | evidence kernel、coverage、inference status |
| time/evidence/withdrawal | D07 | latent/probability/causal dynamics |
| mechanism nonlinearity/resource/conservation | D08 | observation posterior、clinical provenance |
| executable rules/counterexamples | D10 | calibrated uncertainty、evidence discipline |
| declarative derivation/TMS | D11 | continuous dynamics、causal effect |
| composition/local extension | D12 | evidence time、unknown、lineage |
| occurrence/n-ary fact substrate | typed bitemporal hypergraph | interpreter、TMS、probability、causal |

在本研究调查的 13 个家族及其被分析版本中，没有发现一个原子家族原生覆盖事实/知识时间、潜在状态、概率、因果、行动、安全、血缘和组合。因此“所有被调查原子家族都 H-CORE”不是没有候选，而是说明本次研究的固定核心若存在，应优先寻找**小而可审计的共同接口与显式分家能力**；不能把外挂能力都记给一个流行名称。这不是对未调查 calculus 的不可能性证明。

## 7. Post-experiment 原型与隔离结果

### 7.1 实际实现：3 个原子候选，2 个判别仪器

文献阶段曾保留 DBN、SSM、SCM、TEL/TMS、rewrite、multiset transition、open machines 等更宽的判别 shortlist。实现阶段没有把相近骨架虚增成九个浅原型，而是按“不可互换原生状态 + 查询语义”收敛为三个深一些的原子 profile：

| 角色 | 文件 | 主要映射家族 | 原生承诺 | 明确不冒充 |
|---|---|---|---|---|
| 原子 A：TEL | `prototype/candidates/temporal_ledger.py` | D07，带受限的 D11 materialization/TMS 能力 | occurrence/root、multi-time cut、versioned replay、withdrawal、task projection | latent state、概率 forecast、`do`/AAP |
| 原子 B：dynamic causal/state | `prototype/candidates/causal_state.py` | D01/D02/D04 的 finite 可执行子集 | finite DBN filter/forecast；finite SCM condition/`do`/shared-`U` AAP | 权威事件账本、历史撤回、一般连续 dynamics |
| 原子 C：typed rewrite/open | `prototype/candidates/rewrite_open.py` | D10/D12 的 finite 可执行子集 | typed transition、动作 typestate、conflict、reachability、显式 wiring | 校准 posterior、自动因果识别、权威 evidence replay |
| K0/federation 判别仪器 | `prototype/kernel.py` | 第 5 节控制面 + 受控联邦 | 显式路由、版本化 bridge、origin/witness/failure 保留 | 新的患者动力学家族；不给原子候选免费语义 |
| public-model 判别仪器 | `prototype/model_subkernel.py` | E01–E08 的封闭公共模型 | 独立执行动态/因果/组合 reference problem | 第 14 个候选家族；临床模型或真实校准 |

未实现为原子代码的 D03、D05、D06、D08、D09、D13 等，其位置仍来自文献、形式反例和统一问卷，不能把“三个实现没赢”误写成对所有未实现 calculus 的实验性不可能证明。

### 7.2 v3 决策证据面板

当前可用于决策的原始运行位于：

```text
results/20260713T120910Z-panel-v3/
```

它对 58 个 workload 使用 fresh `python -I -S`，候选 stdin 只含 `candidate_view`，oracle 留在父进程；CPython audit hook 约束读 allowlist，并阻断 subprocess/network/native-loader。该边界只适用于已审计 pure-Python 候选，**不是 OS sandbox**。

| 面板 | Native：PASS / HONEST_UNSUPPORTED / FAIL | Companion | 可读出的有限结论 |
|---|---:|---:|---|
| TEL | 36 / 20 / 2 | 36 / 20 / 2 | ledger/time/trace 覆盖最宽之一，但不执行 E dynamics；companion 未补出缺失语义 |
| causal/state | 3 / 53 / 2 | 3 / 53 / 2 | 在已注册 finite model 上有原生 state/causal 能力，但对 audit/TEL 面板大多诚实拒绝 |
| rewrite/open | 31 / 23 / 4 | 31 / 23 / 4 | 动作/规则/组合有真实覆盖，但不提供概率/causal dynamics；companion 未改变边界 |
| K0 kernel instrument | 36 / 20 / 2 | N/A | 证明显式路由/bridge 可运行；不能把 36 个 PASS 记给某一原子家族 |
| public-model instrument | 13 / 44 / 1 | N/A | E01–E08 数值/因果/组合 reference 可执行；不是完整临床核心 |

这些数字不是排行榜：`HONEST_UNSUPPORTED` 证明 typed boundary，而不是能力完成；各候选的 `not_applicable` 与原生问题不同；公开 fixture 也不能替代隐藏 holdout。v1 (`results/20260713T200000Z-panel-v1/`) 有同进程/oracle 与判别力缺陷，只是红队前基线；v2 (`results/20260713T115159Z-panel-v2/`) 是无 audit-hook 文件 allowlist 的过渡隔离版。二者均不承担最终决策证据。

### 7.3 公平合同在实验后的状态

1. candidate-view、oracle-view、reference model 与候选代码分离；结果记录环境与哈希。
2. as-known-then、reinterpret-now、smooth、forecast、condition、`do` 和 AAP 是不同 query，不允许悄悄降级。
3. PASS 同时要求正确行为、semantic eligibility、typed boundary、必要 trace 和完整数值坐标；manifest 自报不算行为。
4. 复制/改写/多路径不增加 root evidence；删除 root 的增量结果由 runner 外部 replay 对照 clean rebuild。
5. planned/ordered 与 performed 分离；unsupported、out-of-model、not-identified、conflict、numerical failure 正交保留。
6. 候选解释器使用封闭 IR；静态指标中五个候选/仪器实现的 literal T/E ID 与 oracle/reference dispatch 计数均为 0。该扫描只是迎合下界，不证明没有领域特例。
7. Native/Companion 分开报告；本次三个原子候选两赛道的分类相同，不能宣称 adapter 已带来免费语义，也不能据此证明所有 companion 永远无用。
8. 实验没有比较真实临床准确性、校准、目标规模性能、权限隐私、人因、监管或独立团队复现。

## 8. Post-experiment 结论与下一步

当前可复查结论限于：

1. 在调查的 13 个家族、实现的 3 个原子原型、58 个公开 workload 与 v3 pure-Python 威胁模型内，没有证据支持一个原子候选直接成为完整固定核心；
2. 非支配能力分布在 evidence/time、latent probability、causal query、truth maintenance、动作安全与 composition 等不同维度；
3. 最有支持的研究参考选择是条件性 `K0 + 唯一 evidence authority + 显式 state/dynamics、causal、rewrite/open 子内核`，不是“把所有东西混在一个对象里”；
4. 任一原型若出现静默未来泄漏、同源增信、planned-as-performed、partial-retrieval-as-absence、unsupported-as-known 或 model output 自证为 evidence root，该实现版本立即硬淘汰；
5. 该选择不是全局最优或数学不可约性证明；未实现候选、其他 calculus、独立 holdout 或新的 context-of-use 均可重画 Pareto。

下一项信息增益最高的实验不是第四个品牌原型，而是**独立双实现 bridge round-trip holdout**：将同一冻结 evidence cut 分别编译为 DBN/SSM 与 SCM native IR，往返 root/clock/version/uncertainty，保持 `filter != smooth` 与 `condition != do != AAP`，并在删除/更正 root 后对照 clean rebuild；同时量化 bridge LOC、人工承诺、错误率、延迟与 blast radius。若失败，当前 K0/联邦边界必须收缩或推翻。

本文件保留可证伪的候选地图；正式权衡、反对意见和推翻条件见 `DECISION.md`、`EXPERIMENTS.md`、`REDTEAM.md` 与 `THREATS_TO_VALIDITY.md`。
