# Unified Clinical Map 研究计划

> 轨道：`UCM`（Unified Clinical Map）
> 状态：**Phase 2（W01–W20 executable benchmark），benchmark v1 尚未冻结；禁止实现候选**
> 起始日期：2026-07-15
> 研究边界：患者世界模型层；不是 K0/TEL/控制面续作
> 完成标准：以仓库根目录 goal 附件中的 15 项完成条件为准，本文件不能缩小它们。

## 1. 唯一研究问题

是否存在一个由截至当前的可见历史 `H_t` 推断出的共享患者状态 `Z_t`，使得：

1. 诊断是从 `Z_t` 读出当前机制/疾病/病程类型的不确定分布；
2. 自然病程预测是让 `Z_t` 在 no-op 或当前治疗延续策略下演化；
3. 治疗预测是从同一个 `Z_t` 改变动作并比较反事实轨迹；
4. 新观察和真实治疗反应通过同一更新算子把 `Z_t` 更新为 `Z_{t+1}`；
5. 以上读出不得绕过 `Z_t` 重读原始历史，也不得使用任务专属的第二患者状态。

本研究允许结论是：

- 在冻结范围内存在有限或近似共享状态；
- 只在某些世界/时间尺度/动作集合内存在；
- 需要动态增长的状态；
- 只能保留完整历史；
- 或存在推翻有限共享状态的最小反例。

## 2. 不得偷换的问题

以下都不是 UCM 的答案：

- K0、TEL、证据账本、权限、审计、路由、QKV、callback 或 `payload:any`；
- 分别训练的诊断/预测/治疗隐藏状态外包一层同名接口；
- 每次查询重新从完整历史计算一个任务专用表示；
- LLM/attention 能读取长病历，因此“自然拥有状态”；
- 只证明可编码，不证明预测充分、干预语义、最小性与可扩展性；
- 以模拟器真状态、未发生未来、任务标签、测试编号或疾病名泄漏答案；
- 用 K0 的安全测试结果替代患者动力学结果。

完整历史只作为明确标注、计入尺寸和成本的无压缩基线；`true_state` 只作不可部署上界。

## 3. 仓库隔离边界

UCM 的唯一可写主路径：

```text
research/unified_map/   研究合同、来源、实验与结论
prototype/unified_map/  微型世界、候选、runner、evaluator、demo
tests/unified_map/      benchmark、合规、反事实、扩展、red-team 测试
results/unified_map/    append-only run bundle
```

硬边界：

1. 不修改 `results/20260713T120910Z-panel-v3/` 及既有 K0 决策/原始结果。
2. UCM 包不得 import `prototype.kernel`、`prototype.contract`、TEL/SCM/rewrite 候选或 bridge 实现。
3. 可复用的只有 pytest 入口、append-only run、canonical JSON、hash、隔离执行等**基础设施模式**；复制到 UCM 后拥有独立 schema/version，不能继承 K0 患者语义。
4. 既有 K0 测试继续原样运行；UCM 测试使用 `tests/unified_map/` 独立发现。
5. 每次结果使用唯一 `run_id`，以临时目录原子写入，目标存在即失败。

## 4. 工作量纪律

- 至少 80% 工作量用于可执行世界、候选、训练/求解、benchmark、反例和淘汰。
- 文献、形式化、治理和接口工作总计不超过约 20%。
- benchmark v1 冻结前不得实现候选。
- benchmark v1 冻结后，任何 oracle/生成器/评分修复都必须升 benchmark 版本；旧结果不能冒充新版本结果。
- candidate snapshot 冻结后才物化 red-team 的秘密参数、seed 和 oracle。

## 5. 阶段与退出门

### Phase 0 — 被动映射与边界（已完成）

交付：本计划、仓库映射、K0 复用白名单/禁用清单。

退出门：

- 冻结资产的内容 hash 已记录；
- UCM 目录和 import 隔离检查已定义；
- 当前 git revision/status 已进入研究日志。

### Phase 1 — 第一原理和可证伪假说

状态：**规格初版已完成；仍随 PRE-FREEZE 一致性审查修正，不构成运行证据。**

交付：

- `FIRST_PRINCIPLES.md`
- `HYPOTHESES.md`
- `FORMAL_SPEC.md` 初版

退出门：

- “同一状态”由受控未来行为等价定义，而非外观或接口身份；
- 明确精确、近似、有限范围、动态增长和不可压缩五种可能；
- 每个候选家族有可杀死的预测，不能只列优点。

### Phase 2 — W01–W20 与 benchmark v1

状态：**进行中。** 正式 PRE-FREEZE 语义规格已覆盖 W01–W20；pre-split
family/strata/corpus 的结构 authority 与 portable compliance/mutation
harness 已落地，但仍只是 scaffold。authority-bound exact expected-cell
receipts、mutation raw-preimage custody 与 atomic run-store publication、
26/26 mutants、4/4 specificity controls、C01–C33 decisive coverage、16/16
collector-owned extractors、external custody 和 clean freeze replay 尚未齐全。
`UCM-E002-ISOLATION_INCOMPLETE` 与 `UCM-E003-HARNESS_INCOMPLETE` 均保持有效。

交付：

- `MICROWORLDS.md`
- 20 个世界生成器、私有 hidden state/oracle 和只读 public history；
- train/validation/frozen-test split；
- 统一诊断、自然预测、治疗预测、更新、OOD、碰撞和 regret 评价；
- 合规作弊样本与自动杀死测试。

退出门：

1. W01–W20 均能生成、重放和对所有允许动作给出反事实真值；
2. candidate package 不含 simulator hidden state、未来或 test seed；
3. true-state 上界和简单错误候选证明评分方向正确；
4. 状态碰撞、虚假拆分和任务绕过测试具有正/负对照；
5. freeze manifest 覆盖代码、参数、split、oracle、指标和测试；
6. `FREEZE_MANIFEST.json` 与 sidecar 生成后 append-only，测试能检测静默漂移。

**只有本门通过后才允许开始 Phase 3。**

### Phase 3 — 基线与 8+ 架构家族

先实现四个规定基线：full-history、separate-task、true-state upper bound、K0-only negative control。随后至少实现八个实质不同家族：

1. 人工机制状态向量；
2. latent SSM/DBN/POMDP belief；
3. controlled PSR；
4. causal-state / behavioral-equivalence / bisimulation；
5. dynamic SCM；
6. Koopman/observable operator；
7. neural world model；
8. mechanism graph/reaction network；
9. symbolic-neural hybrid；
10. attention/memory；
11. program-state/typed rewriting；
12. 新发现的原创候选。

每个家族必须提交：共享状态 schema、更新算子、读出、训练可见信息、状态距离、尺寸、可证伪预测和已知反例。

### Phase 4 — 30+ 个登记实验

最低预算：

- 30 个有实质差异的实验；
- 至少 20 个不是学习率/层数/隐藏维度调参；
- 至少 3 个候选进入完整 W01–W20；
- 完整候选至少 5 个随机种子；
- 最强候选有第二条独立实现路径；
- 每 5 个实验生成至少一个新反例；
- 每 10 个实验重新审查共享状态假说和架构搜索空间。

每次实验固定保存 hypothesis、known failure、最小改动、测试门、seed、config、代码/benchmark hash、逐世界原始结果、置信区间、最坏病例、collision、regret、OOD、成本和 keep/revert/refine/abandon 决策。

连续四次只做同一家族局部参数调整且无实质进展，强制 abandon/refocus。

### Phase 5 — candidate freeze 后 red-team

在最强候选和比较候选的代码/参数 hash 冻结后，才揭示：

- 新检查；
- 新治疗及相反反应；
- 新非线性共病组合；
- 未训练新读出；
- 历史删除；
- 1h/24h/7d 时间尺度；
- 观察通道干预、隐藏混杂、罕见灾难禁忌；
- 任务专属 latent/缓存/重读历史作弊攻击。

结果只追加到 `REDTEAM.md` 与新 run bundle，不回写 benchmark v1。

### Phase 6 — 选择、复现与演示

先按硬失败淘汰，再报告 Pareto，不设置掩盖失败的单总分。

完整 demo 必须显示同一 `state_id/state_hash` 被诊断、no-op、治疗 A/B/C 读取；真实动作和新观察到达后生成新 state；另展示 OOD/信息不足拒绝。

最终交付：

- `DECISION.md`：验证/仅合成支持/失败/未知明确分区；
- `ARCHITECTURE.md`：最强候选（如有）；
- `FORMAL_SPEC.md`：状态、更新、观察、动作和等价；
- `PLAIN_CHINESE.md`：无数学背景可读；
- 可复现命令、原始输出和独立实现结果。

## 6. benchmark v1 冻结顺序

冻结必须按以下顺序执行，避免候选反向塑造 oracle：

1. 写完 W01–W20 语义规格和生成参数域；
2. 写生成器和 oracle；
3. 写候选不可见的真值层与公开历史导出层；
4. 写统一指标和硬淘汰逻辑；
5. 写 honest/cheating/degenerate 测试候选验证判别力；
6. 生成 train/validation/test seed；
7. 运行重复性、counterfactual consistency、split isolation 测试；
8. 生成文件清单、SHA-256 和 freeze manifest；
9. 提交 freeze checkpoint；
10. 才开始候选实现。

若冻结后发现 benchmark bug：保持 v1 结果，记录 bug，创建 v1.1/v2；不得覆盖 v1 或只改 oracle 不改版本。

## 7. 决策规则

硬失败（任一即淘汰该 run/候选主张）：

- 未来/真状态/反事实/test-id 泄漏；
- 诊断、预测、治疗没有读取同一状态；
- query head 重读历史或使用 task-specific patient latent；
- 观察条件与干预语义混淆；
- 方向相反治疗患者发生危险碰撞；
- 关联冒充干预；
- OOD 被高置信强塞已知状态；
- 新治疗要求按测试重写核心；
- 无法复现或覆盖旧结果；
- 完整历史记忆器冒充紧凑状态。

通过硬门后才比较诊断、自然预测、干预预测、regret、calibration、样本效率、OOD、简洁性、扩展性、计算成本和可解释性的 Pareto 前沿。

共享候选相对 separate-task baseline 必须在三任务无不可接受退化，并在样本效率、跨任务一致性、组合泛化、紧凑性或新任务迁移中至少一项有明确优势；否则如实报告被支配。

## 8. 停止与阻塞报告

预算耗尽或没有可防御的高信息增益实验时不虚构成功。停止报告必须列：全部路径、被反例杀死的假说、当前最强候选、最大未知、有限状态证据、局部范围、最可能改变结论的实验，以及继续所需数据/算力/数学工具/独立实现者。

## 9. 当前下一批动作

1. 先闭合 Phase 2 的患者世界模型 vertical slice，而不是继续无限扩张
   evidence machinery。W01/W02/W04/W08/W15 的 patient-state vertical slice 已完成；
   下一步按 W18/W19/W20 顺序证明同一 state 能同时支持
   diagnosis、no-op、A/B intervention 和 response update。
2. 用这些 vertical slice 生成真实 evaluator cells 和 oracle/metric upper-bound
   sanity evidence；authority-bound expected-cell receipts 只围绕实际 W01–W20
   query/response 流扩展，不再脱离患者任务单独堆协议层。
3. 在真实 vertical slice 已闭合的基础上，补完 26/26 malicious mutants、4/4
   specificity controls、C01–C33 decisive coverage 与 mutation raw custody；
   crash、timeout 或错误 gate 不得算 kill。
4. 为 16/16 freeze axes 实现 collector-owned typed extractors，完成 clean
   checkout replay、external custody 与一次性 atomic publication；没有直接阻塞
   semantic freeze 的新 hardening 不进入本轮。
5. 只有上述 PRE-FREEZE 阻断项清零并提交 freeze checkpoint 后，才把 Phase 2
   probe 升级为正式 B01 run，并打开 F01–F12、B02–B04 和候选架构实验。

候选禁令不妨碍在 Phase 2 使用**不参与 Pareto 的 harness mutation/specificity controls**验证检测器；这些 controls 不能被登记为架构实验或 UCM 候选。
同理，Phase 2 的 judge-only true-state upper-bound probe 只校验 world/oracle/
metric 与共享状态执行链，必须保持 `privileged=true`、
`eligibility=upper_bound_only`、`experiment_status=NOT_COUNT_ELIGIBLE`；它不能计入
0/30 实验账本，也不能被称为已开放的正式 B01 候选。
