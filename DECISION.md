# 架构决策：固定可信控制面，而不是固定一种患者状态

> 决策版本：`K0-v0.1`  
> 日期：2026-07-13  
> 结论强度：**在本研究明确要求、来源与 T01–T50 / E01–E08 测试范围内，当前最有支持的架构**；不是数学意义上的全局最优，也不是临床有效性证明。

## 1. 决策摘要

在本研究调查的 **13 个候选家族与 3 个原子原型**中，我们**没有找到一个能独自承担全部冻结职责的数学状态对象**。这里不是对所有可能 calculus 的不可能性证明；它只说明本次被调查的向量/图/概率/日志/重写/因果/开放机器方案若作为唯一核心，至少有一项冻结反例无法无损处理。

当前决策是把固定核心限制为一个小的可信控制面：

```text
K0 = (
  TypedArtifactRole,
  IdentityAndScope,
  TypedTimeAndCut,
  VersionedDerivationAndProvenance,
  ClosedQueryAlgebra,
  ProductResultAndFailure,
  InvariantEnforcement
)
```

K0 固定“**谁，在什么时间切片，基于哪些有资格的证据和模型版本，执行了哪一种查询，产生了什么带边界的结果**”的合同、身份、cut 与不变量。它不是一份持久化病历，也不与 TEL 各保存一套事实；它有意不固定唯一 `PatientState`、统一 `update()` 或统一的组合律。

患者动力学、观察模型、因果反事实、证据维护和组件组合由**语义分家的能力子内核**承担：

1. **Temporal Evidence Ledger（TEL/TMS）**：完整参考联邦中**唯一**的 evidence authority，保存权威事实/action/knowledge 版本，负责知识时间、证据根、撤回、回放与任务投影；K0 只规定其 ledger port；
2. **causal/state subkernel**：隐藏状态过滤/预测，以及 SCM 的 conditioning、`do` 和同一患者反事实；
3. **typed rewrite/open-machine subkernel**：局部规则、动作生命周期、类型化端口、显式交互和可达性；
4. 以后可按同一合同接入 Petri/reaction、POMDP、temporal Datalog 等，但不能伪装成现有子内核的“一个字段”。

因此，本决策不是“把几个热门名词拼起来”，而是：**固定不可绕过的语义边界；只在查询确实需要时调用相应原生 calculus；不把它们压成一个万能状态。**

这里的“参考核心”首先是一个**架构研究假说**。仓库中的 `ClinicalKernel` 只是 K0 合同、路由和部分子内核协作的可执行子集，`ExperimentalModelSubkernel` 只是公共实验模型的封闭解释器；当前没有一个实现、也没有一个已接线的组合实现通过全部 hard workload。二者不能被拼成一个未经测试的“完整实现”，更不能因为三个原子原型覆盖较窄就自动成为赢家。

完整参考 profile 要求 TEL/TMS evidence authority、state/dynamics、causal、typed rewrite/open safety 四组能力齐备；物理上可以合并部署，语义上必须分别归因。局部降级是合法但可见的：缺 state/dynamics 则 filter/smooth/forecast 为 `unsupported`；缺 causal 则 `do`/同患者反事实为 `unsupported`；缺 rewrite/open 则动作 effect、reachability、组合和相应 safety query 为 `unsupported`；缺 evidence authority 时只剩离线合同验证，不构成临床事实运行时。其他子内核不得静默代答。

## 2. 为什么这是当前证据支持的条件性最小承诺

“最小”在这里指：对本次 13 个家族、3 个原型和冻结反例，删除任一列出的 K0 承诺都有已知失败见证，且未发现更小的已调查候选能无特例覆盖全部边界。我们没有完成形式化不可约性证明，也未穷举全部可能 calculus；新的消融、hidden holdout 或单一新 calculus 可以推翻该用语。

### 2.1 三类状态不可无损合并

必须区分：

- **AuthoritativeRecord**：实际收到的观察、陈述、动作、版本、更正和撤回；
- **SystemBelief**：某个 evidence/model cut 下的 posterior、假说或轨迹估计；
- **PatientTrueState**：模型假定存在、但通常不可直接观测的真实生理路径。

事件日志可完整回答“当时知道什么”，却不能自动预测患者；posterior 可作为某项预测的充分统计量，却不能恢复原始来源和更正历史；真实状态是模型对象，不应因一次推断被重新铸成原始事实。任何单状态方案都会在这三者之间制造错误等号。

### 2.2 四类关系也不可压成一张边

- evidence derivation：某个结论由哪些证据和规则得到；
- causal mechanism：改变某变量的机制会怎样改变后果；
- execution trace：程序实际执行了哪些步骤；
- temporal relation：何时发生、何时可见、何时有效。

它们可互相引用，但不是同一种边。图结构能存下这些对象，不等于已经定义其运算语义。

### 2.3 撤回、反事实与倒放不是同一操作

- 撤回改变某个知识版本中证据的资格；
- 生理逆演化是另一个动力学问题；
- 同患者反事实要共享经事实证据后验化的外生背景；
- 历史回放只允许使用当时可见的证据和版本；
- retrospective smoothing 则故意允许后来的证据估计过去状态。

将它们统一成 `update(state, event)` 会掩盖最关键的区别。K0 因此只统一调用合同和审计 envelope，不统一其内部数学。

## 3. 候选调查与硬淘汰

调查按“状态对象 + 演化/更新算子 + 查询语义”操作性去重后保留 13 个在本研究中具有不同关键语义的家族：DBN/CTBN、SSM/SDE、POMDP、dynamic SCM、开放宇宙关系因果、Event/Situation Calculus、TEL、Petri/reaction、进程代数、typed rewriting、temporal Datalog/TMS、typed open machines、temporal sheaf。此分类不是对所有架构空间的完备划分。

以下只被淘汰为**唯一完整核心**；它们仍可作为投影、求解器或组件：

| 被淘汰的唯一核心主张 | 决定性反例 |
|---|---|
| 一个向量/embedding 同时代表事实、潜态、时间、证据和决策 | 同源证据、冲突、撤回与未来 cut 无法从数值位置可靠恢复 |
| 裸知识图/万能超图就是执行核心 | 存储关系不定义惯性、概率、`do`、撤回或数值失败 |
| 普通 PPL conditioning 就是干预/个体反事实 | `P(Y\|T)`、`P(Y\|do(T))` 和共享外生背景的 AAP 可给不同答案 |
| 单一 SSM/SDE 就是完整临床核心 | belief 不是权威事实日志或证据血缘；可见时间也不是过程时间 |
| 单一事件日志/规则系统就是患者动力学 | 回放正确不产生 latent filtering、连续预测或因果识别 |
| Petri/reaction 或 process algebra 单独覆盖全部问题 | 机制并发/守恒强，但 clinical evidence、observation likelihood 与知识时间缺失 |
| 类型系统、逻辑、范畴/operad/sheaf 本身就是患者演化 | 它们约束合法结构或组合，不自动给出患者如何变化 |
| Transformer/QKV、ECS、黑板或 digital twin 品牌可充当权威核心 | 它们是执行/学习/部署模式，未给出可审计的固定临床语义 |

硬淘汰不使用加权平均。未来泄漏、未知变阴性、同源重复增信、计划动作被当实施、推断自证或无法表达时静默近似，任何一项都足以否定该具体版本。

## 4. 原型结果与正确解释

### 4.1 哪一轮结果有决策资格

三轮结果必须分开：

1. `results/20260713T200000Z-panel-v1/` 是**已失效的红队前基线**。红队证明原 runner 存在同进程 oracle 暴露、semantic-eligibility 不严、稀疏轨迹可误过以及部分 fixture 区分力不足；它只保留为失败证据，不能用于候选排名或本决策。
2. `results/20260713T115159Z-panel-v2/` 是隔离 runner 接线后的**中间诊断运行**。它用于确认流水线和结果格式，不作为本节的决策数据。
3. 本节唯一使用的结果是不可覆盖的 `results/20260713T120910Z-panel-v3/`：58 个冻结 workload，候选在 fresh `python -I -S` 子进程中只接收 candidate-view，oracle/reference 留在父进程。v3 的全部 native/companion panel 合计 **0 个 harness error**。

因此，下面的计数不是从 v1/v2 挑选的最好结果，也不与旧计数混算。

### 4.2 v3 Native 总结果

| v3 Native 实现 | PASS | HONEST_UNSUPPORTED | FAIL | 未完成的 hard workload |
|---|---:|---:|---:|---|
| TEL | 36 | 20 | 2 | `T18`, `T20` |
| causal/state | 3 | 53 | 2 | `T18`, `T20` |
| rewrite/open | 31 | 23 | 4 | `T18`, `T20`, `T30`, `T45` |
| `ClinicalKernel`（K0/reference kernel） | 36 | 20 | 2 | `T18`, `T20` |
| `ExperimentalModelSubkernel` | 13 | 44 | 1 | `T20` |

`HONEST_UNSUPPORTED` 只证明边界没有静默伪造答案，**不等于所需行为已实现**。因此没有任何一行通过全部 hard workload。特别是被选择为研究参考的 `ClinicalKernel` 仍在 `T18`（未识别干预效果应返回正确 identification 边界，而不是 `not_applicable`）和 `T20`（开放世界/OOD coverage 必须显式为 `out_of_model`）上 FAIL；它只能被称为 `FORMAL_SPEC.md` 的 **partial executable subset**，不能称为已验证完整 K0。

### 4.3 E/T 分面与失败归因

| v3 Native 实现 | E01–E08 | T01–T50 | T 面板 FAIL ID |
|---|---|---|---|
| TEL | 0 PASS / 8 HONEST_UNSUPPORTED / 0 FAIL | 36 PASS / 12 HONEST_UNSUPPORTED / 2 FAIL | `T18`, `T20` |
| causal/state | 0 / 8 / 0 | 3 / 45 / 2 | `T18`, `T20` |
| rewrite/open | 0 / 8 / 0 | 31 / 15 / 4 | `T18`, `T20`, `T30`, `T45` |
| `ClinicalKernel` | 0 / 8 / 0 | 36 / 12 / 2 | `T18`, `T20` |
| `ExperimentalModelSubkernel` | **8 / 0 / 0** | 5 / 44 / 1 | `T20` |

这个分面阻止两种相反误读：

- 三个原子原型在 E01–E08 上均为**全拒绝**，所以 v3 没有从公共 E envelope 证明它们的数值 dynamics/causal 能力；不能拿它们的 T 通过数当“完整临床计算能力”。
- `ExperimentalModelSubkernel` 在 E01–E08 上 8/8 PASS，只证明封闭公共实验模型解释器覆盖了这八个合成模型；它在 T20 仍 FAIL，且未与 `ClinicalKernel` 形成一项已经按 58 个 workload 验证过的完整组合。不能把两个实现各自的通过集合做集合并集后宣称“全通过”。

rewrite/open 的额外 FAIL 也保留在账本中：`T30` 的语义同构未保持，`T45` 的 raw value/span round-trip 不完整。三种原子候选的 Companion 轨与各自 Native 轨得到相同分类计数；这只说明当前 companion 消融未在分类计数上拉开差异，**不证明 companion 的语义或工程成本为零**。

v3 的正确结论是：**当前实现面板中没有通过全部 hard workload 的候选；原子实现各有原生强项，reference kernel 和 model subkernel 也都只是部分覆盖。** K0 的选择来自角色不可混淆、fail-closed 边界、候选家族分析和 Pareto 结构的合取，而不是“原子失败，所以混合方案自动获胜”，也不是按 PASS 数取最大值。

### 4.4 当前 Pareto 前沿

| 需要的能力 | 非支配原生语义 | 不能用它抵消的缺口 |
|---|---|---|
| 事实、知识时间、撤回、回放 | TEL / temporal Datalog-TMS | 不提供 latent physiology 或 `do` |
| 隐藏状态、观察通道、filter/forecast | SSM/DBN | 不提供权威证据身份与因果识别 |
| 干预与同患者替代历史 | dynamic SCM / causal PPL executor | 不提供病历知识时间与文档血缘 |
| 局部变迁、动作 typestate、反例搜索 | typed rewriting | calibrated probability 与可识别性需另层 |
| 非线性机制、资源与守恒 | Petri/reaction | 临床观察/证据语义需另层 |
| 稳定接口下的局部组合 | typed open machines | 组合语法不自动生成正确交互方程 |

本次候选集不存在可用一个加权总分合理消除的唯一赢家；这正是选择条件性最小共同 K0、保留原生子内核作为**下一轮可反驳假说**的原因，而不是对架构空间作全称断言。当前 Pareto 判断只覆盖本研究的 13 个候选家族、3 个原子原型和 58 个 workload；它不是全局最优性、不可约性或临床有效性证明。

## 5. 固定什么，不固定什么

### 5.1 固定

1. artifact role、identity、subject/encounter/specimen/device/site scope；
2. occurrence/effective、collection、availability、record/transaction、expiry、performed-action interval；
3. evidence/root/version identity、权威 ledger port 和可重建 proof；实际权威历史只存于 TEL/TMS evidence authority；
4. `filter`、`smooth`、`forecast`、`condition`、`intervene`、`counterfactual`、`project`、`replay` 等封闭查询类型；
5. validation、capability、epistemic、coverage、identification、computation 等正交结果轴；
6. 模块注册、bridge、solver、policy 的版本和适用域；
7. fail-closed 不变量，以及每项结果的 capability origin。

### 5.2 不固定

- 疾病、检查、药物、机制和人群参数；
- 任何唯一疾病坐标、唯一距离或统一 latent dimension；
- SDE、ODE、DBN、SCM 或规则作为所有问题的默认执行器；
- LLM、向量检索、QKV、缓存或数据库物理布局；
- 未经声明的共病组合律或交互相加；
- 一个能把任意 callback/SQL/prompt/bytecode 包成 `Node(payload)` 的逃逸口。

## 6. 选择的代价

1. **它不是一条万能公式。** 使用者必须选择查询类型，并为相应子内核提供有效模型。
2. **bridge 是真实复杂性。** 从证据 cut 到模型输入的映射必须版本化、可追踪、可拒绝；它不能被称为“只是适配器”而不计成本。
3. **可能存在多个并行状态。** ledger projection、filter belief、SCM world posterior 和 rewrite configuration 都可同时存在；K0 通过角色和来源阻止它们互相冒充，而不是强迫相等。
4. **组合不会自动正确。** typed ports 可拒绝单位/角色错误，但正确的非线性交互仍需领域知识和验证。
5. **计算可能更贵。** 为保留原始证据、版本、原生 witness 和多模型结果，需要比单一向量更多存储与审计工作。

这些是显式成本，不是被总分掩盖的缺陷。

## 7. 最强反对意见与回应

### 反对 1：K0 只是“接口治理”，没有回答患者状态如何产生

这个反对意见部分成立。K0 不声称生成患者动力学，也不充当 evidence store；它声明哪些问题不能由同一种状态无损回答。完整参考运行时还必须有唯一 TEL/TMS evidence authority，以及经过验证的 dynamics、causal、rewrite/open 子内核。若未来发现一种更小 calculus 能原生、无逃逸口地同时通过所有不变量，K0 应被收缩或替代。

### 反对 2：混合架构只是把复杂性堆起来

如果每个子内核复制一份权威事实，或 bridge 隐式补医学语义，这一反对成立。因此最终结构要求：TEL/TMS evidence authority 的 ledger root 是唯一事实权威；K0 只固定 port/identity/cut/witness 合同；模型输出只能是版本化派生产物；每个查询标注原生能力来源；bridge 计入 primitive/adapter/blast-radius 账本。没有这些约束的“混合”不被本决策接受。

### 反对 3：强类型会妨碍开放世界

类型化并不要求预先穷举所有医学概念。固定的是 artifact/query/result/module contract；新概念可作为版本化领域内容加入。真正未知的字段应进入 typed quarantine/raw preservation，而不是被猜成最近的已知类型。

### 反对 4：真实临床准确率没有验证

正确。本研究只验证架构语义、反例处理和可执行路径，不证明疾病模型准确、治疗安全或临床效益。任何临床使用仍需独立数据、校准、外部验证、context-of-use VVUQ、监管和人类监督。

## 8. 会推翻或改变本决策的证据

出现下列任一项，应重新打开架构选型：

1. 一个更小的单 calculus，在没有 foreign callback 和第二权威事实源的条件下，通过全部 T/E hard workload，并保持相等或更低扩展爆炸半径；
2. 证明 K0 某个原语可由其余原语自然导出，删除后不增加特例或静默失败；
3. 证明版本化 bridge 无法避免双重真相，且另一结构能更好地保证一致性；
4. 新反例显示当前 typed time/cut 仍允许未来泄漏或 retrospective smoothing 冒充当时判断；
5. 新反例显示 root-set provenance 仍会把依赖来源当独立来源，且现有 dependency-family/model assumption 分离不足；
6. 在大规模真实异步数据上，完整 replay/trace 的成本不可接受，而安全的压缩充分统计量可被形式证明；
7. closed IR 无法表达重要医学模型，只能普遍退化为 callback；
8. 临床 context-of-use 证明另一 Pareto 点在明确任务上严格支配本架构。

## 9. 下一项信息增益最高的实验

下一步不是增加更多架构名字，而是完成一个**双实现 bridge round-trip 实验**：

1. 同一冻结 evidence cut；
2. 分别编译为 finite DBN/SSM 与 SCM native IR；
3. 独立实现执行同一 E01–E06 公共模型；
4. 检查 raw-root/clock/version witness 是否往返，`filter != smooth`、`condition != do != AAP` 是否保持；
5. 删除或更正一个 root 后，重编译结果是否等于 clean rebuild；
6. 测量 adapter LOC、人工承诺、错误率、延迟和 blast radius。

该实验能直接判断：K0 + 分家子内核是否真是稳定边界，还是只是把困难转移到 bridge。

## 10. 决策状态

本决策冻结 `K0-v0.1` 作为**研究参考核心假说**，而不是生产或临床认证架构。三个原子原型、reference kernel、model subkernel 和隔离 harness 保留为可反驳证据。v3 没有任何实现通过全部 hard workload；`ClinicalKernel` 自身仍有 `T18`/`T20` FAIL，且 `ExperimentalModelSubkernel` 的 E01–E08 通过不能外推为临床模型正确。任何面向产品的实现都不得把“当前最有支持”缩写成“已证明正确”或“完整实现已通过”。

## 11. 证据映射与结论边界

下表只把本决策的六条关键设计理由映射到 `SOURCES.md` 中已核验的 source ID。它是**有限命题的证据地图**，不是“文献投票”：这些来源分别支持问题必须被区分、某类形式语义已经存在、或某类失败边界确实需要显式处理；没有任何一组来源单独推出 `K0`，也没有来源证明本仓库原型具有临床准确性、安全性或效益。

| 设计理由 | `SOURCES.md` source ID | 这些来源实际支持 | 这些来源不支持 |
|---|---|---|---|
| 多时间与 knowledge cut | `CLIN-01`, `CLIN-07`, `TEMP-03`, `TEMP-04` | 临床发生/有效、结果发出、标本时点，以及数据库 valid/transaction、流处理 event/processing、事件回放等时间概念彼此不可自动合并；乱序、迟到与历史重建是实在的工程问题。 | 不共同定义本研究完整的 `TypedTimeAndCut`；不证明来源系统正确填写时钟，也不证明 actor-specific visibility 或任意 as-of replay 已实现正确。 |
| 血缘、派生与撤回 | `CLIN-02`, `CLIN-06`, `CLIN-14`, `TEMP-05`, `TEMP-06`, `TYPE-04`, `TYPE-05` | provenance entity/activity/agent、生成/使用/派生/失效、查询推导路径，以及插入/删除后的增量维护和 reason/environment-based truth maintenance 都有独立形式基础。 | 血缘不等于事实为真、来源可靠或证据统计独立；推导条数不能直接当增信票数，这些来源也不自动给出临床权重与完整撤回策略。 |
| 隐状态与状态估计 | `STATE-02`, `STATE-03`, `STATE-05`, `STATE-06`, `STATE-09` | DBN/factor graph/过滤与部分可观测控制明确区分隐藏状态、观察通道、belief/filtering/prediction 和行动，并给出模型内推断语义与已知计算边界。 | 不选择正确的患者坐标、疾病机制、时间粒度或 observation model；不保证可识别、校准、跨机构有效，也不提供权威证据身份与知识时间。 |
| 因果干预与反事实 | `CAUSAL-01`, `CAUSAL-02`, `CAUSAL-06`, `CAUSAL-07` | conditioning、intervention 与 counterfactual 需要不同语义；循环模型可无解/多解，反事实也可能仅部分识别或不可给点估计。 | 不验证任一临床因果图、结构方程或个体治疗效应；拥有 SCM/PPL 语法不等于因果假设成立，也不消除可识别性与模型错设。 |
| 组合、端口与局部变迁 | `PROC-03`, `TYPE-01`, `TYPE-02`, `TYPE-03`, `COMP-01`, `COMP-02`, `COMP-03`, `COMP-04` | typed/refinement/typestate 可约束合法值和操作序列；重写、open systems、wiring diagrams、cospans 与 sheaf/open-machine 结果说明局部变迁和按边界组合可以有明确数学语义，且组合保持性质需要条件。 | 端口或类型匹配不证明医学语义匹配；形式上可组合不自动产生正确共病交互、方程、概率、因果方向或安全策略。 |
| fail-closed、安全边界与部署证据分层 | `CLIN-03`, `CLIN-04`, `CLIN-05`, `CLIN-08`, `CLIN-10`, `CLIN-11`, `CLIN-12`, `CLIN-13`, `STATE-08`, `TYPE-06`, `TYPE-07`, `NEURAL-02`, `WORLD-01`, `TWIN-01` | 计划/请求与已执行事件、缺值原因、单位、missingness/观察机会、干预改变观察通道、open-set 风险、不一致信息，以及 learned/retrieval/simulator 的模型错设边界都必须显式处理；技术验证、临床关联和临床验证是不同证据层。 | 不给出通用临床拒绝阈值、治疗授权策略或监管结论；不证明这里的拒绝、OOD、冲突与单位规则已覆盖全部风险，更不构成 clinical validation。 |

因此，本决策中的“目前最有支持”仅表示：在本研究声明的需求、**13 个候选家族、3 个原子原型和 T01–T50/E01–E08 共 58 个 workload** 范围内，`K0 + heterogeneous capability subkernels` 是当前最少混淆上述语义角色、值得继续反驳的**架构研究假说**。它并未以一个全 hard PASS 的实现建立优势，也不是由原子候选失败自动推出；它不是全局最优或不可约定理，更不是临床准确性、安全性或效益证明。原型测试只能检验合同和反例行为，不能替代真实数据校准、外部验证、context-of-use VVUQ、前瞻性临床评价、监管审查或人类监督。
