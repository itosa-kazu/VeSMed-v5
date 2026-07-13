# 动态临床状态架构研究计划

> 状态：Checkpoint 1–8 曾关闭；bridge 执行轮已封存但完成门禁未达成，Checkpoint 3/7 现已重开
> 研究日期：2026-07-13 起  
> 核心承诺：不预设 V5/SDE、高维向量、图、概率模型或任何混合方案为答案。

## 1. 研究问题

在明确的临床语义、安全不变量和工程压力测试范围内，寻找一套**目前最有支持的固定核心架构**。固定核心只规定：基本对象、合法关系、状态更新、时间、证据、干预、不确定性、组合与不变量；疾病、机制、药物、检查、人群知识属于可扩展内容；LLM/术语适配属于输入层；检索、缓存、QKV 与并行化属于优化层。

本研究不声称数学意义上的全局最优。若证据只支持 Pareto 前沿，则交付 Pareto 前沿、最小共同内核和下一项判别实验。

## 2. 非目标

- 不制作临床产品，不作临床有效性或监管合规声明。
- 不用已有 V5 结果证明新架构正确；旧实现只作为候选、失败样本和迁移约束。
- 不把“某模型能表达”偷换为“表达自然、可审计、可安全扩展”。
- 不把 LLM、向量检索、提示词或 UI 当固定语义内核。
- 不通过病例特例、疾病专属加分或额外人工规则偏袒某一原型。

## 3. 评价方法

顺序固定为：

1. **硬约束淘汰**：未来信息泄漏、未知当阴性、同源证据重复、推断自证、计划动作当实施等任一硬失败均不得用平均分掩盖。
2. **Pareto 支配**：比较表达完整性、核心最小性、局部扩展、审计、回放、计算与人工负担。
3. **权衡说明**：保留不可同时优化的候选和适用边界。
4. **辅助评分**：只作展示，不决定硬约束结果。

统一工程指标：核心原语数、特例数、扩展爆炸半径、追踪完整度、回放正确率、表示碰撞、伪区分、非法循环、未知处理、人工审核负担、代码量与增量更新成本。

## 4. 检查点

### Checkpoint 1（已完成）：问题定义与第一原理要求

- 结果：冻结 HARD/SOFT 要求、反目标、反例和五问门禁；不把“原语少”当硬安全替代品。

- 交付：`FIRST_PRINCIPLES.md`、`REQUIREMENTS.md` 初稿。
- 判别工作：每项要求绑定反例、可观测不变量和硬/软等级。
- 退出条件：能判断一个候选是根本不合格，还是仅实现尚缺功能。

### Checkpoint 2（已完成）：跨领域研究与候选搜集

- 结果：按状态对象、演化算子、查询语义去重后调查 13 个候选家族；来源证据与不支持的主张均落盘。

- 交付：`SOURCES.md`、`CANDIDATES.md`、`RESEARCH_LOG.md`。
- 至少覆盖 8 个真正不同的候选家族；候选必须按同一问卷回答。
- 第一手来源优先；引用逐项记录“来源实际支持什么”，不以二手概述代证据。

### Checkpoint 3（原已完成；2026-07-14 重开）：候选统一形式化

- 结果：否决万能 `PatientState/update`；冻结最小共同控制面 `K0` 与不可互换的 TEL、causal/state、rewrite/open 原生语义。

- 为每个候选定义原语、状态、合法操作、读出、组合、失败语义。
- 形成候选无关协议：摄取事件、推进知识时间、撤回来源、历史回放、任务投影、解释追踪、局部扩展。
- 先确定协议，后写候选代码，避免按赢家定制测试。

### Checkpoint 4（已完成）：压力测试

- 结果：冻结 T01–T50 与 E01–E08 共 58 个 candidate-view/oracle-view workload；用错误实现与红队变体证明判别力。

- 交付：`ARCHITECTURE_TESTS.md`、机器可读测试数据和统一测试驱动。
- 覆盖用户给出的 30 项情形，并补充派生证据递归撤回、单位/方法冲突、并发晚到数据、机制循环和不可表示输入。
- 每项说明攻击假设、预期不变量、硬/软等级和失败含义。

### Checkpoint 5（已完成）：前三名原型

- 结果：实现 3 个原子候选（TEL、dynamic causal/state、typed rewrite/open）；另实现 K0 federation 与 public-model subkernel 作为判别仪器，不把它们虚增为新候选家族。

- 从完成调查后的候选中选 3 个，而非预先指定赢家。
- 使用相同概念、事件、规则预算和测试接口。
- 每个原型输出完整推导轨迹、指标清单和失败原因。

### Checkpoint 6（已完成）：红队与修订

- 结果：从同进程 v1 诊断基线，经 v2 进程隔离，修订到 v3 CPython audit-hook allowlist；同时修复 eligibility、轨迹覆盖、外部 clean rebuild、对象/callback 逃逸、mask/时间/动作生命周期等缺陷。

- 做证据复制、删除、晚到、未来泄漏、冲突、开放世界、非线性交互和表达改写攻击。
- 修复必须区分“内核自然修复”与“新增特例”；特例计入指标。
- 检查是否陷入对单一候选的小修小补，必要时返回候选搜索。

### Checkpoint 7（原已完成；2026-07-14 重开）：选择或 Pareto 前沿

- 结果：没有原子赢家；冻结条件性 `K0 + 显式异构能力子内核` 研究参考架构与分维度 Pareto，未声称全局最优或不可约性定理。

- 交付：`DECISION.md`、`FORMAL_SPEC.md`、`THREATS_TO_VALIDITY.md`。
- 当时仅称“在明确条件和测试范围内最有支持的架构”；bridge 反证后该称谓撤回为历史基线。
- 列最强反对意见、尚未统一的冲突和可推翻选择的新证据。

### Checkpoint 8（已完成）：完整交付

- 结果：文档、两张架构图、形式规范、4 类 typed 扩展包、演示、58-workload 隔离面板、复杂度/爆炸半径快照与自动测试均已落盘并可运行。

- 交付：`ARCHITECTURE.md`、`README.md`、`prototype/`、`tests/`、`examples/`。
- 两张一页图：内核图、候选决策图。
- 三个例子：最小全过程、局部扩展、明确拒绝判断。
- 一条 10 分钟演示命令、一条完整测试命令；在干净环境实际运行。

## 5. 防偏差门禁

- Checkpoint 1 和第一轮候选地图完成前不写候选实现。
- 旧 V5/SDE 架构必须与其他候选接受同一测试，不能因仓库已有代码获得额外规则预算。
- 候选被保留的理由和被淘汰的反例同时记录。
- 测试数据与候选实现分离；任何候选专属适配都计入 special-case count。
- 原型只证明语义与执行路径，不证明真实临床准确性。
- 每个主要阶段更新 `STATUS.md` 的五问。

## 6. Bridge 执行轮及下一步

Checkpoint 1–8 关闭后执行了**源码互异、分别冻结且无跨 import 的双实现 bridge round-trip round**；它不是独立团队/第二机器复现。预注册门禁及当前裁决如下：

1. **满足**：候选先 seal，随后以 fresh seed reveal corpus；source/corpus/manifest hash 和静态 import closure 可复查。
2. **未满足**：A 无法在允许投影中完整编译 portable DBN/SCM；B 的完整 executable-model/query round-trip audit 缺失。
3. **部分满足**：A/B 的 filter/smooth 数值核心与 B 的 condition/do/AAP 数值成立；A causal base 不可无损投影，Panel B 还接受非法 cross-world policy。
4. **未满足**：raw-root、scope、clock、version、coverage、uncertainty 没有端到端同时保持；A/B 均有 hard counterexample。
5. **失败**：B correction/retraction 的数值与 clean rebuild 相等，但 active-root authority 和 executable audit 不等；A 没有 preregistered concrete delta fixture。
6. **部分满足**：静态 LOC、承诺向量和 blast radius 已计；A 无 latency telemetry，B 的 p95 样本量不足，完整 error/trace vector 不成立。
7. **未满足**：M01 在 A/B 均未被杀死；M02–M12 未由 candidate runner 执行。synthetic 12/12 只验证 judge，不是 candidate kill matrix。

当前双标签裁决为 **`HYPOTHESIS_FAIL`（冻结实现层）+ `HARNESS_INCOMPLETE`（sealed 41-case corpus 层）**。H01–H30 是原预注册集，H31–H41 是 post-seal/pre-execution addendum。这足以淘汰冻结 A/B 的合规 bridge 主张并重开 Checkpoint 3/7，但不足以证明所有 K0-family/所有 versioned bridge 不可能。下一轮先冻结完整物化、append-only 的 operational probe pack，再比较收缩 K0、richer typed bridge 或新 calculus；即便未来通过，也只增加当前 context-of-use 下的支持，不升级为临床认证。
