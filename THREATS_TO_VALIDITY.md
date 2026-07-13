# 有效性威胁、结论边界与可推翻条件

> **状态**：最终审计版，2026-07-13。预注册威胁框架予以保留；原先的运行值证据槽现已用 `panel-v3` 实值或“未测量”明确封口。  
> **适用范围**：本仓库关于“动态临床状态表示与诊疗计算固定核心”的文献研究、候选去重、统一测试、三个原型与最终 Pareto/决策。  
> **目的**：限定什么证据能支持什么结论，并提前写下什么新证据会推翻当前判断。本文不是部署安全证明、临床有效性证明或监管合规声明。

## 0. 先限定允许得出的结论

本研究把结论分成四级，低级证据不得被升级成高级结论：

| 级别 | 可支持的结论 | 不足以支持 |
|---|---|---|
| L1 形式/反例 | 某种具体语义承诺是否能表示一个反例；某不变量是否由定义保证 | 某软件实现正确、可扩展或临床有效 |
| L2 原型运行 | 本仓库指定版本的实现，在冻结工作负载、oracle 和环境下是否通过 | 整个候选家族必然通过/失败；真实医院可用 |
| L3 工程外推 | 在更大合成负载、故障注入和多实现复现下的性能、维护与组合趋势 | 临床收益、校准、因果可识别性或监管符合性 |
| L4 临床/部署 | 多中心、前瞻或回顾外部验证下的校准、决策收益、安全、工作流与治理证据 | 本 PoC 当前没有这一级证据 |

因此最终文档最多可以声称：**在已列出的来源、反例、冻结测试和本仓库原型范围内，某架构或某 Pareto 组合目前证据最强。** 不得声称“全局最优”“临床已验证”“可直接用于诊疗”或“候选家族已被一个玩具实现证明”。

### 0.1 家族、语义 profile、原型与部署必须分名

```text
candidate family
  -> semantic profile（本研究实际比较的承诺）
      -> prototype implementation（本仓库代码实例）
          -> deployment system（尚未构建/验证）
```

- 原型失败首先是**实例证据**；只有存在定义级反例，或补救必须引入会改变候选身份的 companion，才可上升为 profile/family 层结论。
- 原型成功首先是**存在性证据**；只有独立实现、扩规模和外部数据复现后，才可推断稳健性。
- 混合架构不能把 companion 的能力记给主候选，也不能把复杂性藏在 DSL、知识包、foreign callback、适配器或人工审核中。

## 1. 威胁登记总表

`当前状态` 中的“开放”表示缓解措施已设计但仍可能没有运行证据；“结构性”表示即使实验通过也不会消失。

| ID | 有效性威胁 | 主要受威胁结论 | 当前状态 |
|---|---|---|---|
| V01 | 搜索范围、关键词、语言与可获得性造成来源偏差 | 候选空间足够全面；文献支持强度可比较 | 开放 |
| V02 | 来源到主张的过度外推、候选粒度不一致 | 家族间比较公平；某来源支持本研究实现 | 开放 |
| V03 | 测试偏置与 oracle 自证 | 通过率反映语义能力而非测试方言 | 部分缓解；bridge 已 seal/reveal，但 sealed 41-case corpus 整体为 `HARNESS_INCOMPLETE` |
| V04 | 选择后见偏差、基准污染与 winner-first 修订 | shortlist/赢家不是研究者偏好产物 | 开放；bridge 源码先冻结，但 B 的最早 dry-run 字节未保留 |
| V05 | 玩具模型向复杂临床世界外推 | 小例子通过意味着真实病程可处理 | 结构性 |
| V06 | 单个 prototype 代表整个 family | 家族保留/淘汰结论 | 结构性 |
| V07 | primitive、LOC、特例数与 blast radius 可被游戏 | “更小、更通用、更易扩展”的比较 | 部分实测；bridge LOC/提交向量已计，认知/人工成本仍开放 |
| V08 | 混合架构堆层、能力归因漂移与 companion 洗白 | 固定核心确实最小；混合方案不是功能拼盘 | 已出现冻结实现层反证；family-level 仍结构性 |
| V09 | 医学知识覆盖、参数真实性和测量模型缺失 | 生理/诊断/治疗输出有医学意义 | 结构性 |
| V10 | 因果识别、反事实可识别与 transportability 缺失 | `do`/反事实输出可被数据识别 | 结构性 |
| V11 | 概率校准、外部验证和决策效用缺失 | belief/hazard/ranking 数值可用于临床决策 | 结构性 |
| V12 | 计算复杂度、可判定性、终止性和数值稳定性 | 表达完整且始终可计算；规模可接受 | 开放；只验证小规模语义，未测性能曲线 |
| V13 | 时间、actor、权限和可见性记录不完备 | 历史回放没有未来泄漏；“当时可见”可确定 | 结构性 |
| V14 | 旧 V5 结果陈旧、执行路径漂移和可变 registry | 既有 V5 的负面/正面证据仍代表当前系统 | 开放 |
| V15 | 部署、监管、伦理、安全和人因边界未验证 | 架构选择等于可落地医疗产品 | 结构性 |
| V16 | LLM 输入、蒸馏、代码生成和评审风险 | 语义模块/医学知识正确且可追责 | 开放 |
| V17 | 随机性、环境、实现质量与工程者效应 | 候选性能差异来自架构而非实现偶然 | 开放；已有双实现源码，仍无独立团队/第二机 |
| V18 | 开放世界/OOD 与“万能拒绝”互相冒充 | 能拒绝即代表处理未知良好 | 开放 |
| V19 | 临床数据选择、测量误差与病例代表性 | 压力测试覆盖真实分布和少数群体 | 结构性 |
| V20 | 在线学习、知识更新与反馈闭环未被长期测试 | 可重放、校准和安全在生命周期内保持 | 结构性 |

## 2. 研究与来源层威胁

### V01. 搜索与来源偏差

**威胁机制**

- 搜索由当前团队设定关键词，可能偏向英语、计算机科学与可公开访问材料，低估临床信息学、控制工程、形式化方法或非英语传统。
- “固定核心”不是各领域统一术语；相同思想可能以 workflow、digital twin、belief state、event calculus、open system、truth maintenance 等不同名字出现。
- 优先原始论文能降低二手误读，却可能漏掉后续负面结果、工程失败和成熟标准中的实践约束。
- 当前候选停止扩张是研究预算决定，不是对搜索空间穷尽的证明。

**已采用的缓解**

1. `SOURCES.md` 对每个来源分别记录“实际支持什么”和“不支持什么”，不以引用数量代替证据强度。
2. 搜索跨状态空间、概率、因果、事件/逻辑、过程/反应、类型/重写、组合系统、图/世界模型及临床标准，并按语义承诺去重，而不是按品牌名计数。
3. 优先规范、原始论文和正式文档；保留反方材料和每个家族的根本缺口。
4. 最终只称“当前搜索范围内”，并公开未检索或证据薄弱领域。

**残余风险**

不存在可执行的“所有可能架构”全集；负面工程经验常不发表。来源覆盖即使很广，也不能证明没有更好的未发现家族。

**什么新证据会改变结论**

- 一种此前未纳入、且原生同时满足硬不变量的独立 calculus；
- 已纳入家族的权威来源证明我们误解其时间、干预、回放或组合语义；
- 系统综述、成熟临床部署或负面复现显示当前文献权重排序错误。

### V02. 来源外推与候选粒度不一致

**威胁机制**

同一候选名可能覆盖从数学 calculus 到完整平台的不同尺度。例如“POMDP”是决策模型，“digital twin”常是系统模式，“Transformer”是计算层；把这些当同粒度家族会制造假胜负。论文证明某定理，也不等于本原型实现了其前提。

**已采用的缓解**

- `CANDIDATES.md` 按“状态对象 + 演化/更新算子 + 查询语义”去重；工具、存储、参数化后端和安全元层不冒充独立动态家族。
- 每个来源主张限定到 family/profile/instance 层，并标出前提。
- 对 Petri/reaction、types/rewrite、ECS/blackboard、category/operad/sheaf 等近邻明确拆分或合并理由。

**残余风险**

家族边界仍有判断性；过度合并会掩盖重要变体，过度拆分会让一个传统获得多票。数学上等价的编码也可能在工程性质上显著不同。

**什么新证据会改变结论**

- 构造出保持查询语义、复杂度和审计性质的双向翻译，证明两个候选确属同一 profile；
- 反例证明当前合并家族内部存在不可互译的状态或演化语义；
- 独立专家复核认为候选问卷在粒度上系统性偏向某家族。

## 3. 测试、oracle 与选择层威胁

### V03. 测试偏置与 oracle 自证

**威胁机制**

早期 T01–T50 以证据、时间、回放和 truth maintenance 为主，天然偏向 ledger/logic；若统一接口也长得像事件账本，就会把接口适配成本误当架构缺陷。反过来，E01–E08 的参考模拟器、预期反事实或组合定律若由候选设计者写成，也可能只证明 oracle 与自己一致。候选还能通过“全部 unsupported”逃避错误答案。

**已采用的缓解**

1. 将输入冻结为候选无关的**语义工作负载**，不要求内部采用同一事件 API。
2. 分设 exact、metamorphic、reference 三类 oracle；允许证明项、因子子图、重写轨迹或可达性证据等不同原生 witness。
3. 增加 E01–E08，覆盖 filtering、`see/do`、共享外生背景、非线性滞后、机制分叉、非线性组合、组合律和反馈合法性。
4. 预注册 candidate-view 与隐藏 oracle-view，做错误实现、符号翻转、时间泄漏、重复证据、断链撤回等 mutation；设置 honesty probes，拒绝必须带有正确 typed failure/coverage，不能万能拒绝。
5. Native、Companion 与 ablation 分开运行，防止共享外壳替候选完成语义工作。

**残余风险**

reference simulator 仍是人造模型；metamorphic relation 也可能遗漏共同错误。测试数量增加不能替代独立 oracle 作者、形式证明或真实数据外部验证。

**什么新证据会改变结论**

- 独立团队构造的反例使当前赢家失败；
- mutation suite 无法杀死已知错误实现；
- 替代 reference implementation 对同一冻结 workload 给出实质不同裁决；
- 去掉 ledger-heavy 或 dynamics-heavy 面板后 Pareto 次序发生系统性翻转。

**`panel-v3` 实值与未测项**：最终隔离面板执行 58 个 workload × 8 个候选/赛道组合，共 464 个 fresh-process run，`harness_error=0`；加入 bridge 完整性回归后的当前全量结果为 `135 passed, 7 subtests passed`。已知恶意实现（stack/oracle 读取、正确 payload 夹在 refusal 中、稀疏/重复/垃圾轨迹、万能拒绝、query echo、空 `OK`、伪 clean rebuild）都有自动回归并被拒绝为 semantic PASS。`ExperimentalModelSubkernel` 对 E01–E08 为 8/8 semantic/numerical PASS。

没有预先枚举一个封闭 mutation 总体，因此**不报告 kill-rate 百分比**；没有第二位 oracle 作者/第二 reference implementation，所以 **oracle disagreement 未测量**；万能拒绝只在专门攻击与正向 liveness workload 上验证，未定义可泛化的“检出率”。分面板结果已分别保存，但没有做足以估计选择偏差的系统敏感性曲线。

**2026-07-14 bridge holdout 实值与未测项**：四个 source-distinct、无跨 import 的候选/面板源码先 seal；随后抽取 fresh seed，并生成、冻结 portable authority/model/cut/query corpus 与 hidden oracle。per-candidate projection 由各 runner 在 reveal 之后生成，不是 seal 时已经存在的 candidate-view/oracle-view 文件。这也不是独立团队复现。sealed 41-case corpus 中 H01–H30 是原预注册集，H31–H41 是 post-seal/pre-execution 静态审计 addendum；全体只有 4 个 case 指向具体 base object，35 个是 descriptor-only，H09/H20/H21 含 dangling query refs，且 H09 与 descriptor-only 集合重叠。其 candidate verdict 没有任何 `CANDIDATE_FAIL`，所以 corpus 层只能得出 `HARNESS_INCOMPLETE`，不能单独推出实现层失败。`HYPOTHESIS_FAIL` 另由单独记账的确定性 post-seal external hard counterexamples 支撑，尤其是 B 的 M01 execution/recovery split-brain，以及 A 的 typed uncertainty-result failure 和其他 root/cut/version 反例；这 42 个 external/red-team probes 不能提升为 hidden H-case。synthetic mutation judge 的 12/12 也不能写成候选实现的 12/12 kill matrix。

### V04. 选择后见偏差与 benchmark 污染

**威胁机制**

研究者已经知道旧 V5、TEL、causal/state 和 typed rewrite 的优缺点；在看到运行结果后改 hard/soft 等级、权重、参数、工作负载或 shortlist，会把探索伪装成确认。原型开发者读取全部测试也可能写出逐例补丁。

**已采用的缓解**

- 顺序固定为硬约束淘汰 → Pareto → 权衡说明；不以加权总分覆盖硬失败。
- 在候选实现前冻结 `FIRST_PRINCIPLES.md`、`REQUIREMENTS.md`、工作负载、oracle、manifest 和记账规则；后续变更必须记录理由、时间和受影响结果。
- special-case ledger 区分共享领域承诺、候选必要适配、通用修复与测试后补丁；winner-first 修订计入 `S_patch`。
- 最终同时报告首轮结果和任何修订后结果，不删除失败轨迹。

**残余风险**

本研究不是双盲；作者同时参与需求、实现和裁决。即使预注册，早期需求本身也可能受既有架构经验影响。

bridge 轮在源码冻结、per-candidate runner 与 hash/sidecar 上降低了 winner-first 修订风险；A/redteam 支持 exact-byte replay，B 因保存 timing telemetry 只支持剔除时序字段后的结构化语义 replay。B 的最早未提交 dry-run 只保留 SHA-256，没有保留原始字节。run02 与 run03 已按 parent hash 保留，因此可审计后续链，但不能声称该分支拥有完整 WORM/append-only 运行历史。

**什么新证据会改变结论**

- 盲化 holdout 或独立团队重跑改变 Pareto 前沿；
- 替换合理的 hard/soft 边界后赢家不稳定；
- 发现候选专属代码直接匹配 case/test id 或隐藏 oracle 参数；
- 原始 git 历史显示结论后改动了基准而未重跑全部候选。

### V05. 玩具模型外推

**威胁机制**

T/E 面板刻意小而可判定，只能验证语义和执行路径。真实临床系统有高维混杂、稀疏且非随机观察、异步多主体、非平稳流程、罕见相互作用、长期反馈和制度约束。小规模反例通过不证明在真实知识规模、病程跨度或并发负载下仍有效。

**已采用的缓解**

- 把原型目标明确限定为 semantic witness，不把 ranking、hazard、counterfactual 当临床结论。
- 除精确小例外，设计不规则采样、非线性反馈、共病/药代组合、晚到/撤回/冲突和扩展爆炸半径测试。
- 计划报告规模曲线、超时/内存/数值失败与“正确拒绝”，而不是只报通过数。

**残余风险**

合成 workload 无法覆盖真实文书、接口故障、跨院语义漂移和临床行动后果。无论原型结果多好，L4 临床有效性仍为空。

**什么新证据会改变结论**

- 多中心去标识化真实回放、前瞻 silent trial 或临床模拟显示同一不变量和性能趋势；
- 放大主体、事件、知识版本、并发和时间跨度后出现超线性崩溃或语义退化；
- 真实病例暴露测试中不存在的新角色、时钟、观察过程或作用域。

**`panel-v3` 实值与未测项**：已验证规模仅为 58 个小型 synthetic workload、8 个配置、464 个隔离子进程；每个 workload 的 timeout 上限为 30 秒，最终面板 0 harness errors。该运行没有采集逐例峰值内存、吞吐、并发、事件数/变量数放大曲线或长时间稳定性，因此**最大可扩展规模、时延/内存曲线均未测量**。T35 只验证数值合同/拒绝边界，没有任何候选以真实大规模 solver 通过；这些结果仍不等于临床验证。

### V06. Prototype 与 family 混淆

**威胁机制**

原型可能因为编码错误、时间预算、库选择或作者熟悉度失败；也可能通过 companion 实现了家族本身不提供的能力。用三个小实现淘汰整个 DBN、SCM、PPL、rewrite 或 open-system 家族会犯生态谬误。

**已采用的缓解**

- 所有失败归类为：实现 bug、profile 可自然补齐、当前基本表示冲突、必须 companion、或家族定义级反例。
- family 淘汰只针对明确宣传版本（例如“裸向量是唯一核心”），保留其作为投影/求解器/模块的价值。
- 对最终 shortlist 要求 Native/Companion/ablation；能力归属按消融结果而非名称。

**残余风险**

“自然补齐”与“改变候选身份”仍有主观判断；一个更成熟的库或不同语义变体可能大幅改善结果。

**什么新证据会改变结论**

- 同家族第二个独立实现通过原型失败的硬测试且不增加身份改变型 companion；
- 形式证明表明被判为 companion 的能力其实可由家族原语定义；
- 原型 bug 修复后 Pareto 归属改变；
- 专家复核确认我们测试的是非典型或稻草人变体。

### V07. Primitive / LOC / 特例 / blast radius 计量可游戏

**威胁机制**

- 一个 `eval`、`Rule(fn)`、万能 JSON 或外部 solver 可伪装成“一个原语”。
- LOC 可通过压行、代码生成、依赖外包或把逻辑移入数据/提示词而减少。
- 特例可改名为通用 rule；扩展爆炸半径若只数文件，会奖励巨型单文件或配置泥球。
- 手工审核负担、知识包复杂度和模型训练成本可能不进入代码指标。

**已采用的缓解**

1. primitive profile 计闭合 IR 构造子、组合子、状态槽、foreign escape hatch、外部 solver/模型、知识承诺和运行时服务，不报单个裸整数。
2. foreign callback 必须登记类型、读写集、确定性、版本、失败、资源限制与 witness；不能按一个原语免费计算。
3. LOC 仅为辅值，同时报告语义 LOC、配置/规则量、依赖、生成器、人工步骤和宏展开。
4. blast radius 使用依赖图上的 schema/rule/query/migration/test/recompute/review 向量，并验证局部扩展前后旧结果。
5. `G_general`、`K_shared`、`K_extra`、`S_patch` 分账，测试后补丁不能伪装成共享医学知识。

**残余风险**

任何复杂度指标都可被边界选择影响；不可完全把认知复杂度、调试成本和未来维护性压成数字。

**什么新证据会改变结论**

- 等语义宏展开或全依赖盘点后，所谓最小核心的 primitive/knowledge/operation 总负担显著上升；
- 独立维护者完成同一扩展时，改动面与作者测量明显不同；
- 删除 foreign operator 或 companion 后大部分通过项消失；
- 以语义依赖图重算后 Pareto 次序改变。

**`panel-v3` 实值与未测项**（机械计量见 `results/metrics-final.json`）：

| 实现 | manifest unique primitives | foreign-boundary declarations | nonblank/non-comment LOC | test/oracle dispatch sites | static special-case indicators |
|---|---:|---:|---:|---:|---:|
| TemporalEvidenceLedger | 20 | 3 | 1,996 | 0 | 0 |
| CausalStateCandidate | 8 | 1 | 2,080 | 0 | 0 |
| RewriteOpenCandidate | 29 | 0 | 3,013 | 0 | 0 |
| ClinicalKernel | 7 | 2 | 694 | 0 | 0 |
| ExperimentalModelSubkernel | 7 | 0 | 1,202 | 0 | 0 |

四个 typed extension 包可通过公开 API 运行时注册而不修改 fixed-core 文件；回归中既有 answer 的语义改变量为 0，runtime 中 extension-id 专属分支命中数为 0。`metrics-current.json` 已含前三个包，因此它们从零写入时的历史 repo diff 未测量；第四个 test-method 包有静态 before/after，差分报告 knowledge-extension 新增 1、fixed-core added/modified/removed 均为 0，并将 harness 修改 5 个文件单独列出。这里的 foreign 数是 manifest **边界声明数**，不是动态调用次数；动态 foreign 调用量、人工 authoring/review 时间、认知复杂度和独立维护者成本均未测量。不得把上述列压成唯一总分。

bridge 轮另做了静态边界盘点：四个冻结实现/面板源码共 `244,694 bytes / 5,609 physical lines / 4,768 strict LOC`，两个候选 runner 共 `132,402 / 2,727 / 2,454`，合计 `377,096 / 8,336 / 7,222`；全部 AST import 均来自标准库，冻结 A/B 互相导入为 0，两个 runner 只动态加载各自候选。实验提交区间共有 14 个 commits、32 个 experiment-only 新文件、12,101 insertions、0 deletions，核心 runtime 与 schema migration 改动均为 0。这些是实现边界与 blast-radius 证据，不等于认知复杂度、独立维护成本或 family-level 最小性证明。

### V08. 混合架构复杂度与能力归因

**威胁机制**

当前证据很可能支持 TEL、causal/state、typed rewrite/open composition 的互补组合。但“混合”可能只是堆叠多个完整系统：身份、时间、失败、版本和作用域被重复表示，跨层翻译成为新核心，组合顺序产生不一致，最终没有稳定的最小边界。

**已采用的缓解**

- 先定义最小共同语义内核，再把概率、因果、动力学、优化和术语知识作为显式 capability 子内核；不以“万能 compose”遮蔽接口条件。
- 每个组件声明 typed ports、时钟、读写集、知识版本、适用域、失败和 witness；共享同一证据身份，不复制事实世界。
- 做 Native/Companion/ablation 与 E06–E08，检查非线性相互作用、括号/注册顺序、反馈和认识论自证。
- 复杂度归属到整个闭包，包括适配器、同步、迁移、监控和人工运维。

**残余风险**

小规模组件能组合不代表长期演化时仍兼容；接口稳定性、版本协商和跨 solver 不确定性可能成为主要成本。混合方案可能最终比单一较弱架构更难验证。

bridge holdout 已把这种风险从纯假设推进到冻结实现层反证：A/B 都没有在各自 runner 中证明 root、scope/time/cut/version、filter/smooth 与 condition/do/AAP 经跨内核转换后保持；external reference 还观察到 A 的三通道 typed result 缺失、B 的 evidence/record uncertainty sidecar 不活跃，以及 B 的 recovery-tape split-brain。B 的 model-level aleatoric/epistemic/measurement 参数扰动本身是 live 的，不能与 sidecar 缺口混为一谈。由于 sealed 41-case fixture 未物化完整，这些证据只能淘汰冻结 A/B 的合规 bridge 主张，不能外推为所有 versioned bridge 或 K0 family 不可能。相应地，Checkpoint 3/7 已重开。

**什么新证据会改变结论**

- 单一候选以更少总承诺原生通过硬测试和动态/因果面板；
- 组合次序、版本或部分故障导致临床可见差异；
- 适配层占主要 LOC、运行时或错误率；
- 形式化接口/契约能证明组合保持关键不变量，且独立实现复现。

## 4. 医学、因果与统计层威胁

### V09. 医学知识、参数与观察模型缺失

**威胁机制**

架构能够表达轴、机制、治疗和风险，并不表示其中医学知识完整或正确。PoC 参数可来自人工范围、LLM 蒸馏或玩具函数；单位、检测限、设备、治疗对观察通道的影响、共病交互和疾病谱覆盖可能不真实。正确 calculus 也会在错误知识上稳定地产生错误输出。

**已采用的缓解**

- 将临床知识、患者证据、任务政策和模型输出分层、版本化并带 provenance；架构比较使用共享的冻结领域承诺。
- 本研究测试语义不变量，不以期望疾病 top-1 反向调知识；医学补轴/机制需横向 mimic 公平审查。
- 数值结果附 knowledge/model/version、适用域、coverage、单位/方法和 typed failure。

**残余风险**

没有系统性的专家知识验证、真实测量模型、全疾病 atlas 或治疗效应估计。本研究无法证明任何输出在医学上准确。

**什么新证据会改变结论**

- 独立多学科专家按预注册标准审查知识包并达到一致；
- 真实多中心数据支持参数、测量过程和交互；
- 外部病例暴露系统性漏轴、错误方向或不公平 mimic 几何；
- 同一架构替换高质量知识后仍产生结构性错误，说明问题不只是知识质量。

### V10. 因果识别与反事实不可识别

**威胁机制**

SCM/causal PPL 能表达 `do`、abduction–action–prediction 和共享外生背景，但表达不保证观测数据能识别效应。未测混杂、选择偏差、治疗指征混杂、positivity 违反、干扰、动态治疗策略和模型错设会使多个 SCM 与同一观测分布兼容，却给出不同反事实。

**已采用的缓解**

- 把“可表达”“可计算”“可识别”“已估计”设为不同状态；不以程序返回数值代替 identifiability。
- 因果查询必须带假设、目标人群、时间/版本、识别 witness 或明确 `unidentified/partially_identified`；在可能时输出 bounds。
- E02/E03 只用完全已知的合成 SCM 验证运算语义，不冒充真实因果证据。

**残余风险**

真实临床决策通常无法验证个体反事实；共享外生噪声本身也是模型假设。即使形式识别，估计误差与 transportability 仍未解决。

**什么新证据会改变结论**

- 随机试验、自然实验或可辩护的识别设计支持目标效应；
- sensitivity analysis 显示结论对未测混杂稳健/不稳健；
- 多个同样拟合数据的 causal model 给出相反治疗建议；
- 独立 identifiability checker 或形式证明确认/否定当前查询。

### V11. 校准、外部验证与决策效用缺失

**威胁机制**

likelihood、posterior、hazard、rank 或 delta 即使计算正确，也可能未校准、跨院失效或没有决策净收益。top-1 命中不等于概率可靠；拒绝率、亚群公平性、伤害权重和临床 workflow 均未验证。

**已采用的缓解**

- 当前原型不宣称临床概率；数值结果必须区分模型分数、概率、assertion、coverage 和 utility。
- 未来验证预先要求 discrimination、calibration、decision curve/utility、亚群、时间漂移、外部中心和 failure coverage 分开报告。
- policy/action 层显式承载目标、偏好、授权和约束，不把诊断分数直接当行动。

**残余风险**

目前没有 L4 证据；即使后续回顾验证良好，也不保证行动建议改善结局或不制造自动化偏差。

**什么新证据会改变结论**

- 时间外/地域外验证显示稳定校准与有益净收益；
- 亚群或中心间系统性失准、拒绝不公平或 policy harm；
- silent deployment 与前瞻研究证实/否定工作流收益；
- 重新校准需求频率高到破坏“稳定核心”的运维假设。

### V12. 计算、可判定性、终止性与数值稳定性

**威胁机制**

开放世界概率程序可能推断不可控；一般重写可能不终止/不合流；递归 Datalog、TMS、sheaf/optimization、POMDP 与非线性 SDE 可能组合爆炸；反馈回路可能无唯一解。浮点、Monte Carlo、近似推断和超时会把计算失败伪装成医学不确定性。

**已采用的缓解**

- 固定核心要求 typed computation failure，将 `unsupported`、`unidentified`、`timeout`、`nonconvergent`、`numerical_error`、`resource_exhausted` 与临床未知分开。
- Track A 使用闭合 IR、受限递归/重写策略、显式资源预算和 solver manifest；foreign operator 登记确定性与数值诊断。
- 报告收敛、有效样本量/误差界、随机种子、容差、超时、内存和规模曲线；对小模型与解析/枚举 reference 对照。

**残余风险**

有表达力的通用系统不可能普遍保证可判定和可扩展；受限子语言的边界可能排除重要临床模型。小规模数值稳定不外推到高维病程。

**什么新证据会改变结论**

- 给出所选内核关键子语言的终止、合流、复杂度或误差保证；
- 压力规模下出现静默数值错误、结果对种子/容差/求解器敏感或资源超预算；
- 一个更受限的候选以可接受表达损失换来显著更强保证；
- 真实 workload 显示大多数查询只能依赖不透明 foreign solver。

**`panel-v3` 实值与未测项**：同一 Windows/CPython 环境下 `panel-v2` 与 `panel-v3` 的 8 组 classification counts 完全一致；`panel-v3` 的 464 个隔离 run 为 0 harness errors。面板只记录 seed `1103`，没有多 seed 分布。T35 的第二轮 oracle 修复已改为由 parent judge 从公开 closed recurrence 独立生成 0–24 小时完整 25 坐标，并拒绝稀疏/重复/垃圾轨迹；最终所有候选在 T35 均为 `HONEST_UNSUPPORTED`，所以这证明的是“不能伪过”，**不是 solver 已通过**。超时率、非收敛率、内存/复杂度曲线、容差扫描和 solver disagreement 均未测量。

### V13. 时间、actor、权限与可见性不确定

**威胁机制**

“发生时间”“标本时间”“设备生成时间”“系统接收时间”“临床签署时间”“某 actor 可见时间”不是一个总序。晚到、回填、时钟漂移、批量导入、权限屏蔽、break-glass、转院与口头信息会使“当时知道什么”不可由数据库时间戳完全恢复。缺少 actor-specific visibility 时，presentation-only replay 仍可能泄漏未来或误删当时可见信息。

**已采用的缓解**

- 内核使用多角色时间、部分序、valid/known/transaction/version/availability 与 actor/tenant/purpose scope；禁止单 `timestamp` 冒充全部语义。
- 区分 `replay_as_then`、`reinterpret_now` 和 `current_best_view`；无可验证 visibility 时必须返回 coverage gap，而非猜测。
- 权限/遮蔽记录与临床否定分开；masked 不得解释为 absent。

**残余风险**

历史系统可能从未记录可见性、时钟来源或访问控制状态，因此严格回放在信息论上无法恢复。事件的“真实发生时间”也可能只有区间或叙述性证据。

**什么新证据会改变结论**

- 有端到端审计日志、消息队列 offset、签署/查看日志和时钟校准，能验证 actor-specific replay；
- 对同一历史 case 的多 actor 重建出现不同但合法视图；
- 发现当前时间模型仍无法表达区间、不确定时间、因果顺序或批量晚到；
- 独立回放与当时保存快照逐项一致/不一致。

### V18. 开放世界、OOD 与万能拒绝

**威胁机制**

支持 `unsupported/unknown` 不等于能检测 OOD；反之，候选可通过拒绝全部困难请求维持“安全”。基于 health reference 的相对证据也不是普适 OOD 判定，更不是临床阈值。

**已采用的缓解**

- 分开 epistemic unknown、coverage gap、atlas outside、model OOD、computation failure 和 policy refusal。
- honesty probes 同时要求该答的能答、该拒绝的给正确理由；运行时只输出证据量/coverage，不在固定核心写死通用二值阈值。
- 对拒绝率、选择性风险和错误自信分开报告。

**残余风险**

开放集识别本身依赖参考分布和部署环境；新医院、新设备、新疾病与分布漂移无法靠语义内核自动解决。

**什么新证据会改变结论**

- 预注册的未知疾病、设备/中心漂移和 adversarial near-OOD 数据验证选择性性能；
- 候选主要靠拒绝取得硬测试优势；
- health-reference delta 与真实 OOD/健康状态在外部数据上不对应；
- 新方法在相同 coverage 下显著降低错误自信。

## 5. 既有系统、部署与输入层威胁

### V14. 老 V5 证据陈旧与执行路径漂移

**威胁机制**

仓库中的旧 `*_result.txt`、设计文档、文件名和注释可能不代表当前 runtime。2026-07-13 被动审计只对记录的 git 快照和 SHA-256 有效；`start_ui.py` 启动会重建 `master_axes.json`，使“审计前状态”“启动后状态”和旧结果可能不同。治疗模拟的当前阻塞、静态 endpoint likelihood、病例压缩、future evidence 或 label 通道等结论，在代码修复后也可能过时。

**已采用的缓解**

- 遵循 runtime > 流量 > actively served assets > 配置 > 持久产物/源码注释的证据顺序；不把旧结果文件当当前证明。
- 审计记录 commit、关键文件哈希、真正 UI 入口、只读扫描方法及未运行会写盘入口的原因。
- 把 V5 分为 family capability、当前表示冲突、实现缺失和 runtime blocker；不以当前实例淘汰整个 SSM/SDE 家族。
- 若 V5 进入后续比较，必须在隔离副本/干净工作树运行统一协议并保存环境与原始输出。

**残余风险**

审计仍可能漏掉环境变量、外部服务、未提交状态或替代入口。代码一旦变化，行号和部分结论立即漂移；历史结果的生成环境可能无法恢复。

**什么新证据会改变结论**

- 新 commit 修复当前表示/执行缺口并在统一 T/E 面板通过，且无 disease/test 特例；
- 捕获的 live trace 证明当前主路径与审计重建不同；
- 可复现环境重跑旧结果并验证其输入、版本和输出完整一致；
- registry 写盘行为、label leakage 或 treatment blocker 被实证移除。

### V15. 部署、监管、伦理、安全与人因边界

**威胁机制**

固定语义核心只是医疗软件的一部分。隐私、网络安全、身份与访问、知情同意、数据驻留、审计保留、模型变更控制、临床责任、界面、人因、告警疲劳、故障恢复、互操作认证、质量体系和地区监管均未由原型覆盖。

**已采用的缓解**

- `REQUIREMENTS.md` 将部署硬边界与核心架构能力分开；缺失任一部署证据不得被核心测试通过掩盖。
- action lifecycle 包含 proposed/authorized/administered/cancelled/failed，计划不等于实施；policy 与临床状态分离。
- 最终架构文档列明 intended use、非用途、人工监督、failure mode、版本/回滚和需要的外部治理组件。

**残余风险**

本 PoC 没有完成威胁建模、隐私影响评估、临床风险管理、可用性工程、质量体系或任何辖区审批。即使语义正确，糟糕 UI/工作流仍可造成伤害。

**什么新证据会改变结论**

- 明确 intended use 后完成适用地区的法规分类、质量/风险管理与安全/隐私评估；
- 临床人因研究、故障演练、红队和 incident data 支持/否定部署假设；
- 监管或标准要求使某些当前“外层”能力必须进入固定核心；
- 实际 workflow 显示授权、责任或 override 语义无法由现有 action/policy 边界表达。

### V16. LLM 输入、蒸馏、代码生成与评审风险

**威胁机制**

LLM 可能幻觉来源、混淆 disease leaf、生成无效单位/范围、把期望答案写进轴或 ID、复制病例细节造成过拟合、提出 disease-specific bonus、制造不可执行代码，或在长上下文中遵循不可信 artifact 的注入。多个 agent 使用同类模型也不构成真正独立证据。

**已采用的缓解**

- LLM 只能提出 versioned `KnowledgeArtifact`/代码变更，不能直接成为患者事实或权威医学判断；每项产物保留 prompt/model/version/provenance。
- 病名-only distillation、distillation/case agent 分离、第三方 audit、quarantine→review→active 门禁，以及 focused + broad regression，防止病例回灌与单病例补丁。
- 医学内容需来源和人工审查；结构由 schema、类型、单位、引用与不变量检查；运行行为优先于注释/生成说明。
- artifact 一律视为不可信输入，禁止其改变研究目标、oracle 或权限边界。

**残余风险**

人工 reviewer 也可能被流畅文本锚定；同模型/同训练语料带来的相关错误难以由“多 agent”消除。知识审查规模扩大后，人工注意力成为瓶颈。

**什么新证据会改变结论**

- 独立临床专家盲审发现高比例语义/引用/单位错误；
- 不同模型、非 LLM 基线或人工编写模块在相同协议下显著更可靠；
- prompt injection/red-team 能越过 quarantine 或改变权威状态；
- 来源核验、schema/type checker 与回归能稳定捕获预植入错误。

### V17. 随机性、环境、实现质量与工程者效应

**威胁机制**

Python/库版本、平台、BLAS、hash/order、随机种子、求解器容差和并发调度会影响结果。开发者对某候选更熟悉，会给它更好的优化、调试和解释；不同总代码预算也会造成不公平。

**已采用的缓解**

- 保存 run id、git commit、环境锁、命令、seed、参数、原始 **JSON bundle**（metadata、summary 与逐候选结果 JSON）和 stderr；一条命令从干净环境重跑。
- 先跑正确性再优化；共享 workload/oracle，不共享候选语义帮助；同预算记录开发时间、候选专属 LOC 和依赖。
- 随机候选多 seed，报告分布而非最佳 run；确定性面板要求 byte/semantic stable 或解释合法非确定性。
- 以故意错误实现验证 harness；尽可能由非实现者复核 trace。

**残余风险**

时间预算与作者经验无法完全匹配；玩具标准库实现也可能不代表成熟生态。环境锁不能消除硬件/数值差异。

**什么新证据会改变结论**

- 不同机器、实现者或第二语言实现无法复现；
- 增加合理优化后某候选从被支配变为 Pareto；
- seed/solver/容差变化导致硬裁决翻转；
- 成熟库实现与本原型在能力或复杂度上显著不同。

**`panel-v3` 与 bridge 实值/未测项**：最终 panel 证据包为 `results/20260713T120910Z-panel-v3/`，环境是 Windows 11、CPython 3.12.13、seed `1103`、`python -I -S` fresh process；`panel-v2` 与 `panel-v3` 在同机上的 classification counts 一致。bridge 轮有两套冻结候选源码、两个候选 runner 与两个 public panel 实现，并对 panel E01–E06 做了 separate-process 外部数值参考核验；这降低了“只有一个 bridge 实现”的风险，但两套实现仍来自同一研究环境，不构成独立团队或跨语言复现。当前回归为 `135 passed, 7 subtests passed`。**第二台机器、独立团队、第二语言、多 seed/solver/容差矩阵、逐候选开发与调试预算均未测量**，因此这里只能主张同环境可重复，而不是跨环境复现。

### V19. 临床数据与病例代表性

**威胁机制**

PMC/PubMed case report 偏罕见、严重和可发表表现，通常有回顾性完整信息；它们不代表常见门诊、早期未分化状态、阴性病例、不同人群或真实 missingness。结构化过程还会丢失叙事不确定性、时间区间和来源冲突。

**已采用的缓解**

- 病例用于发现语义缺口与压测，不用来估计患病率或宣称总体性能；presentation-only 与 post-workup 分开。
- 原始文本、结构化映射、时间/来源和不确定性并存，可逆规范化；缺失不转成阴性。
- 后续临床验证需按中心、场景、人口学、设备、严重度和时间切片抽样，并保留连续入组或合适对照。

**残余风险**

当前研究没有代表性临床 cohort，不能估计 prevalence、calibration、fairness 或 workflow impact。文献病例的“正确答案”本身也可能依赖最终检查，不适用于当时诊断。

**什么新证据会改变结论**

- 连续、多中心、时间外真实 cohort 与可靠 observation-process 元数据；
- 早期 presentation 与最终诊断分离后，候选结论发生改变；
- 亚群/设备/中心分析暴露作用域或公平性失败；
- 双人独立结构化和 adjudication 显示当前映射不可靠。

### V20. 在线学习、知识更新与反馈闭环

**威胁机制**

系统建议会改变检查与治疗，从而改变未来训练数据；把采纳行为当疗效证据会形成认识论自证。术语、指南、模型和本地流程更新也可能使历史重放、校准和组件接口漂移。短期静态测试不能验证多年演化。

**已采用的缓解**

- 区分生理反馈、观察政策、行动、模型输出和模型更新；模型输出不得成为自身独立证据根。
- 患者状态、知识版本、模型版本、policy 与训练数据 lineage 分开；支持 as-then 与 reinterpret-now。
- 在线学习默认 proposal/quarantine/offline evaluation 后再发布，要求 rollback、shadow/silent 验证与变更审计。

**残余风险**

长期 performative effects、概念漂移、机构适配和模型供应链无法由本轮 PoC 观测。版本过多也可能使维护成本反超固定核心收益。

**什么新证据会改变结论**

- 长期 shadow/部署日志显示建议改变数据生成机制与校准；
- 版本迁移或回放不能重现当时输出；
- E08/反馈红队发现输出经间接路径自证；
- 多轮知识/模型升级证明局部扩展与回滚仍保持不变量。

## 6. 决策时的强制门禁

最终 `DECISION.md` 无论选择单一候选还是 Pareto/混合方案，都必须执行以下门禁：

1. **不以总分赎回硬失败**：未来泄漏、未知当阴性、同源重复、计划当实施、非法自证等任一硬失败单列。
2. **不从实例跳到家族**：每条淘汰结论标注 `implementation`、`profile` 或 `family` 层，以及为何能上升。
3. **不把 companion 洗成 native**：Native/Companion/ablation 三份结果和全部依赖同时报告。
4. **不把运行数值叫临床概率**：没有外部校准、识别与效用证据时，只称模型输出。
5. **不隐藏失败与拒绝**：typed failure、coverage、超时、非收敛和拒绝率与通过项同等公开。
6. **不删首轮结果**：所有后见修复进入 special-case/变更账本并全量重跑。
7. **不以旧 artifact 证明当前行为**：决策只引用带 commit、hash、环境和原始输出的当前运行。
8. **不把“当前最有根据”写成“唯一正确”**：明确适用范围、Pareto 牺牲项和最强反对意见。

## 7. 最终证据槽：实值与明确未测量项

最终证据包括 `results/20260713T120910Z-panel-v3/` 的 **JSON bundle**，以及 `results/bridge-holdout/` 的冻结 manifest、逐实现运行包和最终双标签报告。每个空缺都必须读作“未测量”，不能读作通过。

| 证据 | 当前实值 | 仍未测量/开放 |
|---|---|---|
| 基准完整性 | panel 有 58 个 checked-in workload；`workload_files=sha256:6cb8ac4557709b6a052b4940563ef82879f832a5bea8cdccd65ac7c2a4e1a878`，candidate-view 集合 `sha256:bb1492c75c01201dd47632d829478187dc7ef9295239b87278acde92e730ea83`，oracle-view 集合 `sha256:5397a1cffdd12fa29c24d7f3b625abeaa5ce9f3731e0f61c491537031cf2ec67`；bridge H01–H30 原预注册集及 H31–H41 addendum 已冻结/reveal | bridge 只有 4 个 case 指向具体 base object，35 个 descriptor-only；H09/H20/H21 含 dangling refs（H09 与 descriptor-only 重叠），故 41-case suite 未完整执行 |
| Harness 独立性 | panel protocol `vesmed-isolated-candidate/3`：464 fresh-process run、0 harness errors；bridge A/B 使用分离 runner 与 frozen hash pin；42 个 post-seal probe、public external references 与 synthetic mutation judge 均单独记账 | 未定义封闭 mutation 总体，故无 kill-rate；候选 runner 只执行 M01，M02–M12 未执行；无第二 oracle/reference 实现；external probes 不得提升为 hidden H-case |
| Native/Companion | TEL `36 PASS / 20 HONEST_UNSUPPORTED / 2 FAIL`（native 与 companion 相同）；causal `3/53/2`（两赛道相同）；rewrite `31/23/4`（两赛道相同）；kernel `36/20/2`；model `13/44/1`，其中 E01–E08 为 8/8 PASS | 三个原子候选的 generic public-model adapter 未实现；相同 companion 数不是 companion 带来增益 |
| 复杂度 | panel primitive/foreign/LOC 分别为 TEL `20/3/1996`、causal `8/1/2080`、rewrite `29/0/3013`、kernel `7/2/694`、model `7/0/1202`；bridge 冻结源码+runner 为 `7,222 strict LOC`、14 commits、32 个 experiment-only 新文件，核心 runtime/schema migration 改动 0 | 动态调用量、知识审核/人工时间、宏展开、认知成本与独立维护成本未测量 |
| 扩展性 | 4 个 typed extension 包；运行时固定核心文件改动 0、extension-id runtime 分支 0、旧 answer 语义改变量 0；其中第四个包的静态 before/after fixed-core 改动 0 | 前三个包无 authoring 前快照；多轮 schema 迁移、全量重算、独立维护者审核成本未测量 |
| 数值/性能 | seed `1103`；T35 parent-judge closed recurrence 要求完整 25 坐标并杀死 sparse/garbage；v2/v3 classification counts 同机一致 | T35 无候选通过；多 seed、容差/solver disagreement、逐例 latency、内存、并发与规模曲线未测量 |
| 可复现性 | panel commit `13c31d22f14904b2cd50a9e913dedbf60a1138c2`（dirty 状态摘要已记录）；bridge 逻辑实验工件 checkpoint 为 `abac08786f642c28ba76d8940c60fe1906ab9945`，exact-byte Git packaging checkpoint 为 `d08a8e5b12377890499703b6de6bed1f90c4aa98`（后者只加 `.gitattributes`/字节封装，不改实验语义；二者均不含本次最终报告/文档）；Windows 11 / CPython 3.12.13；当前 `135 passed, 7 subtests passed`，bridge 专项 `16 passed`；26 个决策依赖工件从 packaging checkpoint 直接复核 Git blob bytes/SHA，report/runner/freeze hashes 与 replay 命令已保存 | 第二机器、第二语言和独立团队未完成；B 的最早 dry-run 只剩 SHA，故不能主张完整 WORM 历史 |
| Bridge 裁决 | 冻结 A/B 为 `HYPOTHESIS_FAIL`；sealed 41-case corpus（H01–H30 preregistered + H31–H41 addendum）整体为 `HARNESS_INCOMPLETE`；两者不可互相补偿 | 不证明所有 versioned bridge 或 K0 family 不可能；需要完整 operational probe pack 后重跑 |
| 临床边界 | 明确为 synthetic architecture semantics benchmark | 无真实临床 cohort、外部校准、临床效用、人因、安全、监管或 L4 验证 |

## 8. 结论稳定性判据

若出现以下任一情况，必须重开候选搜索或把最终选择降级为未决，而不是继续为既有赢家打补丁：

- 合理替代 oracle、独立复现或盲化 holdout 使硬裁决翻转；
- 冻结 bridge 实现在 root/cut/version/uncertainty/recovery 等不可补偿 hard invariant 上出现反例；
- 赢家的关键能力主要来自 companion、foreign callback 或测试后特例；
- 扩规模后出现不可接受的非终止、数值不稳定、组合顺序依赖或全局重算；
- 新候选以更小的**总语义闭包**满足同一硬不变量；
- 真实数据揭示当前核心无法表达的新身份、时间、可见性、观察过程或行动角色；
- 临床识别、校准、效用、安全或监管证据与 PoC 的架构假设冲突。

2026-07-14 的冻结 bridge 轮已经触发新增的 bridge hard-invariant 判据：实现层出现不可补偿 hard failure，且 sealed 41-case harness 未物化完整。因此原 Checkpoint 3/7 选择被明确重开；这不等于上面其余 family-level 条件已被满足。后续不得继续把当前 bridge 描述为“已证明稳定”，也不得用 post-seal probes 或 public panel 代替完整 hidden suite。

反之，即使三个原型全部通过，也只能提高 L2 级信心。要把结论推进到 L3/L4，仍需独立实现、规模与故障研究、真实多中心外部验证、因果识别审查、临床效用、人因、安全和监管证据。
