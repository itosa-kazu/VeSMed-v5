# Unified Clinical Map 研究计划

> 轨道：`UCM`（Unified Clinical Map）
> 状态：**FINAL SYNTHETIC RESEARCH EVIDENCE（30/30 实质实验门槛已满足；无合格 primary UCM winner；开放世界 UCM 未建立）**
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
- 实现前协议曾要求 semantic freeze 只冻结 TRAIN5/EVAL5 protocol/schema、五-panel、zipped pairing 与时序，不含 raw seed 或 panel digest，并在 code-owned `FROZEN-v1` 后、训练前发布 `TRAIN5_PRECOMMIT.json`；实际执行未建立这条 TRAIN5/EVAL5 authority chain，因此不能声称 confirmatory。
- candidate snapshot 冻结后才物化 red-team 的秘密参数、seed 和 oracle。

## 5. 阶段与退出门

### Phase 0 — 被动映射与边界（已完成）

交付：本计划、仓库映射、K0 复用白名单/禁用清单。

退出门：

- 冻结资产的内容 hash 已记录；
- UCM 目录和 import 隔离检查已定义；
- 当前 git revision/status 已进入研究日志。

### Phase 1 — 第一原理和可证伪假说（历史阶段记录）

历史状态：**当时规格初版已完成，仍处于 PRE-FREEZE 一致性审查；不构成运行证据。**

交付：

- `FIRST_PRINCIPLES.md`
- `HYPOTHESES.md`
- `FORMAL_SPEC.md` 初版

退出门：

- “同一状态”由受控未来行为等价定义，而非外观或接口身份；
- 明确精确、近似、有限范围、动态增长和不可压缩五种可能；
- 每个候选家族有可杀死的预测，不能只列优点。

### Phase 2 — W01–W20 与 benchmark v1

状态：**已完成 executable freeze。** `BENCHMARK_V1_FREEZE.json` 以 exact
source bytes、live runtime canary、20 worlds / 21 panels、M01–M16 executable
contract、5 个 seed commitments 和 append-only verifier 发行 `FROZEN-v1`。
以下第 102–125 行保留的是 executable freeze 之前的 gap snapshot，不是当前
freeze/experiment 状态。早期正式 PRE-FREEZE 语义规格已覆盖 W01–W20；pre-split
family/strata/corpus 的结构 authority 与 portable compliance/mutation
harness 已落地，但仍只是 scaffold。authority-bound exact expected-cell
receipts、external mutation raw-preimage custody 与 atomic run-store
publication、C01–C33 全覆盖、16/16 collector-owned extractors、external
custody 和 clean freeze replay 在那个 snapshot 中尚未齐全。26/26 malicious mutants
与 4/4 specificity controls 当时已有 live decisive records，但只覆盖 21/33 gates；
这些历史数字不能覆盖后来的 executable freeze/current bundle verifiers。
`UCM-E002-ISOLATION_INCOMPLETE` 与 `UCM-E003-HARNESS_INCOMPLETE` 只描述该旧
snapshot，不是当前 final evidence status。

二十个 patient-bound upper-bound evaluator 现已汇入一个 fresh-process
live-replay suite：20 个 world members、21 个独立 panels（W15A/W15B 分开）、
94 个 per-world cells、43 个 state bindings。它完成的是 privileged upper-bound
执行覆盖；各 world 仍保留异质 estimand，因此不是 expected-cell corpus、候选、
正式 B01 或 freeze authority。**在该历史快照时**候选/架构信用为 0，实验账本为 0/30；当前机器权威是 `38 total / 30 eligible / 8 ineligible / 1 failed attempt`，见第 10 节和 `EXPERIMENTS.md` 第 21 节。

当时最近一次只读 freeze dependency gap map（不是 freeze artifact）显示 16/16
axes 为 `INCOMPLETE`，315-shard coverage lock 未就绪，正式 scope/corpus pins
未建立。该历史 formal producer 精确保留 654 个语义 gap：539 个由 world scope
拥有，115 个由 metric registry 拥有；metric runtime inventory 仍是 111 targets、
`closed_target_count=0`。W20 已把行为无关的 raw `evidence_count` 与 history provenance 移出
sealed state identity：count 为 5/6 的 pair 现在同 state hash，且 9/9 个
horizon-4 policy semantics exact-equal。该已知 false split 已修复，但完整
minimal behavioral quotient 仍未证明，`minimal_quotient_claimed=false` 保持不变。

交付：

- `MICROWORLDS.md`
- 20 个世界生成器、私有 hidden state/oracle 和只读 public history；
- train/validation/frozen-test split；
- 统一诊断、自然预测、治疗预测、更新、parent 从同-state `diagnose+rollout` 精确投影的 OOD、碰撞和 regret 评价；
- 合规作弊样本与自动杀死测试。

退出门：

1. W01–W20 均能生成、重放和对所有允许动作给出反事实真值；
2. candidate package 不含 simulator hidden state、未来或 test seed；
3. true-state 上界和简单错误候选证明评分方向正确；
4. 状态碰撞、虚假拆分和任务绕过测试具有正/负对照；
5. freeze manifest 覆盖代码、参数域、split、oracle、指标、测试和 TRAIN5/EVAL5 协议，但不包含 confirmatory raw seed/panel digest；
6. `FREEZE_MANIFEST.json` 与 sidecar 生成后 append-only，测试能检测静默漂移。

早期 654 个 typed-scope gap 与 12 个 mutation coverage gap 作为后续 assurance
backlog 保留，但它们要求把可运行 Python 世界再翻译成第二套 DSL，已超出用户规定的
约 20% 理论/控制工作预算，因此不再是 executable freeze 的必要条件。冻结源若有
任何语义修复必须升版；不得原地修改 v1。

**本门已经通过；允许开始 Phase 3。**

### Phase 3 — 基线与 8+ 架构家族（历史执行计划）

本阶段原计划在 code-owned `FROZEN-v1` 后先发布 `TRAIN5_PRECOMMIT.json`，再实现四个规定基线：full-history、separate-task、true-state upper bound、K0-only negative control。实际运行完成了 8+ 家族和基线/控制实验，但 primary 没有建立完整 TRAIN5/EVAL5 authority chain；后来的五-replicate full evaluations 因此只能是 development evidence。再后的 CONFIRM5-lite 有公开 commitment/reveal，但 scope 仅 train4/val1/test2/pair0、`complete=false`。base candidate runtime 始终只有 `initialize/update/diagnose/rollout`，OOD 是 parent projection，new-readout 只能走 candidate seal 后的独立 extension worker：

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

### Phase 4 — 30+ 个登记实验（历史最低预算；当前机器计数为 30 eligible / 38 total）

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

### Phase 5 — candidate freeze 后 red-team（历史目标协议）

在最强候选和比较候选的代码/参数 hash 冻结后，才揭示：

- 新检查；
- 新治疗及相反反应；
- 新非线性共病组合；
- candidate seal 后的独立 extension-worker 未训练新读出（W04/base 已有 output bundle 不得计 novel）；
- 历史删除；
- 1h/24h/7d 时间尺度；
- 观察通道干预、隐藏混杂、罕见灾难禁忌；
- 任务专属 latent/缓存/重读历史作弊攻击。

结果只追加到 `REDTEAM.md` 与新 run bundle，不回写 benchmark v1。

### Phase 6 — 选择、复现与演示（历史目标协议）

先按硬失败淘汰，再报告 Pareto，不设置掩盖失败的单总分。

完整 demo 必须显示同一 `state_id/state_hash` 被诊断、no-op、治疗 A/B/C 读取；真实动作和新观察到达后生成新 state；另展示 parent 从这些同-state diagnose+rollout rows 投影的 OOD/信息不足结果，不新增 candidate OOD RPC。

最终交付：

- `DECISION.md`：验证/仅合成支持/失败/未知明确分区；
- `ARCHITECTURE.md`：最强候选（如有）；
- `FORMAL_SPEC.md`：状态、更新、观察、动作和等价；
- `PLAIN_CHINESE.md`：无数学背景可读；
- 可复现命令、原始输出和独立实现结果。

## 6. benchmark v1 预定冻结顺序（历史协议；未完整执行 TRAIN5/EVAL5 链）

冻结必须按以下顺序执行，避免候选反向塑造 oracle：

1. 写完 W01–W20 语义规格和生成参数域；
2. 写生成器和 oracle；
3. 写候选不可见的真值层与公开历史导出层；
4. 写统一指标和硬淘汰逻辑；
5. 写 honest/cheating/degenerate 测试候选验证判别力；
6. 冻结 TRAIN5/EVAL5 的 closed tuple schema、五-panel、zipped pairing、KDF/PRNG domain 和时序；不生成或写入 confirmatory raw seed/panel digest；
7. 运行重复性、counterfactual consistency、split isolation 测试；
8. 生成文件清单、SHA-256 和 freeze manifest；
9. 提交 freeze checkpoint 并由 code-owned issuer 获得 `FROZEN-v1`；
10. 发布 `TRAIN5_PRECOMMIT.json` 的五个 actual training tuple/digest；
11. 才开始候选训练；至少三个 family 各五个 artifact seal 后依次做 EVAL5 commit、corpus seal、execution/finalization 与 reveal。

若冻结后发现 benchmark bug：保持 v1 结果，记录 bug，创建 v1.1/v2；不得覆盖 v1 或只改 oracle 不改版本。

## 7. 决策规则

硬失败（任一即淘汰该 run/候选主张）：

- 未来/真状态/反事实/test-id 泄漏；
- 诊断、预测、治疗没有读取同一状态；
- query head 重读历史或使用 task-specific patient latent；
- 观察条件与干预语义混淆；
- 方向相反治疗患者发生危险碰撞；
- 关联冒充干预；
- parent 从同-state diagnose+rollout projection 判定 OOD 被高置信强塞已知状态；
- 新治疗要求按测试重写核心；
- 无法复现或覆盖旧结果；
- 完整历史记忆器冒充紧凑状态。

通过硬门后才比较诊断、自然预测、干预预测、regret、calibration、样本效率、OOD、简洁性、扩展性、计算成本和可解释性的 Pareto 前沿。

共享候选相对 separate-task baseline 必须在三任务无不可接受退化，并在样本效率、跨任务一致性、组合泛化、紧凑性或新任务迁移中至少一项有明确优势；否则如实报告被支配。

## 8. 停止与阻塞报告

预算耗尽或没有可防御的高信息增益实验时不虚构成功。停止报告必须列：全部路径、被反例杀死的假说、当前最强候选、最大未知、有限状态证据、局部范围、最可能改变结论的实验，以及继续所需数据/算力/数学工具/独立实现者。

## 9. 历史执行计划（已执行主体运行；仍有证据协议缺口）

1. 保持 `BENCHMARK_V1_FREEZE.json` 及其 31 个 frozen source files 不变；任何
   必要修复升为 v1.1/v2，v1 结果不覆盖。
2. 使用冻结 seed commitments 物化 train/validation corpus；候选 seal 前不公开
   sealed-test seed reveal。
3. 实现统一 runner 与 FullHistory、SeparateTask、TrueStateUpperBound、K0Only
   四个基线，并证明 diagnosis/natural/intervention 三头读取同一 state hash。
4. 按人工机制向量、belief state、PSR、causal state、dynamic SCM、Koopman、
   neural world model、mechanism graph 八个家族开始 executable experiments。
5. 每 5 个实验新增反例，每 10 个实验做架构级复盘；至少 3 个候选进入
   20 worlds × 21 panels × 5 seeds 的完整运行。
6. 26/26 mutation 与 21/33 gate 结果保留作合规 evidence boundary；补 gate 只在
   它直接审查真实候选时进行，不再优先于世界模型实验。

候选禁令不妨碍在 Phase 2 使用**不参与 Pareto 的 harness mutation/specificity controls**验证检测器；这些 controls 不能被登记为架构实验或 UCM 候选。
同理，Phase 2 的 judge-only true-state upper-bound probe 只校验 world/oracle/
metric 与共享状态执行链，必须保持 `privileged=true`、
`eligibility=upper_bound_only`、`experiment_status=NOT_COUNT_ELIGIBLE`；它不能计入
当时的 0/30 实验账本，也不能被称为已开放的正式 B01 候选。

## 10. 当前完成审计与前向计划

### 10.1 已完成且有机器 authority 的项目

| 目标要求 | 当前证据 | 判定 |
|---|---|---|
| 隔离轨道 | `research/prototype/tests/results/unified_map`；K0 仅复用 custody/test pattern | **已验证** |
| W01--W20 benchmark v1 + oracle freeze | 20 worlds / 21 panels；freeze root `sha256:8acb6623c2fdf79008240c5f5967b2143c4fb5e7bb87a4e8aa9f72e77ef33a2d` | **已验证** |
| 至少 8 个不同架构家族 | F01--F22 中多种 hand/belief/PSR/quotient/SCM/Koopman/neural/graph/path/kernel/program/ensemble/switching-particle states | **已验证（合成实现）** |
| 至少 30 个实质实验 | `EXPERIMENT_INDEX.json`: 38 total / **30 count-eligible** / 8 ineligible / 1 failed attempt / 0 evidence gaps | **已验证** |
| 三候选全 W01--W20×5 | EXP-033 F10、EXP-034 F14、EXP-035 F18；各 **1,680** rows，R01--R05 | **已验证运行；三者 hard-fail** |
| freeze 后 red-team | strict source-distinct v2 bundle `sha256:d3b0ecfd8722e9863d84d3bd88ffa30d9e00b04976ac48b50cd00f02f34040b3` | **已执行；结论混合/失败，不给 L4** |
| 独立复现 | `20260719T101913Z-I18-full-repro-01c908cb1b`，bundle `sha256:deee6e6339d88d500a52770052f20a14cfac30ac43b2c839574a377be08257af` | **exact core reproduction** |
| raw/config/source/hash/run IDs | index 与各 manifest/bundle；gzip raw 有逐文件 digest；`FINAL_EVIDENCE.json` root `sha256:54106a834a6343574381407a2c080db32349ad722e72a57acc0af95bfc3e8b04` | **已验证 custody** |

机器计数绝不能再写成 `32+4`。EXP-033--035 是 repeat full evaluations、EXP-036
是 privileged control、EXP-037 是 `FAILED_UNFINALIZED` architecture attempt，均不重复
计入 30；EXP-038 F22 v2 是第 30 个 eligible 实质实验，但因 1 collision + 1 unsafe
OOD 正式 `ABANDON`。

### 10.2 Primary、supplemental 与 exploratory 证据不得混合

1. **Primary development full runs**：F10/F14/F18 的 unsafe forced-known OOD 分别为
   **5 / 21 / 5**；三者 hard gate 全部失败。Primary eligible Pareto 因而为空。
2. **Supplemental CONFIRM5-lite**：batch
   `20260719T090636Z-POSTSEAL-CONFIRM5-25eeeb5ec6`，scope receipt
   `sha256:cde9098636c7e9186c398bb1b8dd42c0b866580df828aa0f14e4454889a9edc9`；
   W01--W20、C01--C05、train4/val1/test2、pair0，`complete=false` 且没有 collision
   evidence。F10/F18 在这个 lite scope 上通过并形成局部 Pareto，但不能覆盖 primary
   失败。公开 reveal 存在；receipt 同时披露一个未 finalization attempt 曾读取 seed。
3. **Secondary battery**：M09/M10/M11/M13/M16、1,307 rows，明确
   `formal_frozen_metric_claim=false`；只作探索，不能制造正式 winner。
4. **Red-team v1**：reused-fixture exploratory only。**Red-team v2** 才是 strict
   source-distinct bundle；其 OOD/collision 只有 local support，新 check/treatment 是
   open-world scope failure，新 task inconclusive，history deletion 显示 nonminimal state。
5. **REPRO5**：1,680 episodes、28,720 rollout queries、260 pairs、全部差异 0、failure
   counters 0。它不重算 oracle metric，也不修复 F18 primary OOD。此前
   `20260719T095421Z-I18-full-repro-f77211903c` 因误开 W16/W17 S1 extension pairs 而
   `FAILED_UNFINALIZED`、0 credit；正式 run 按 frozen runner 排除这些 pairs。

### 10.3 最终研究裁决

- **已验证**：完整工程执行链、同一 shared-state contract、冻结合成 benchmark、30 个
  eligible 实质实验、三次 full primary、strict v2、full source-distinct exact reproduction。
- **仅合成局部支持**：有限封闭 catalog 内，F10/F18 有可用 shared-state 行为；F18 在
  v2 committed collision/OOD probes 上局部安全。
- **失败**：没有普通候选通过 primary hard gate；F22 v2 被淘汰；strict v2 证明 F18
  不能在不 extension-fit 且不重放 visible history 的条件下原生吸收新 check/new
  treatment；exploratory M11 对 F10/F14/F22 也显示同一 scope gap，但不是冻结 verdict。
- **尚未知**：新任务 sufficiency、任意开放世界有限状态的存在或不存在、临床有效性、
  production safety、global optimality。

因此结论不是“找到 UCM winner”，而是：**有限封闭合成目录的 shared state 有局部
支持；当前无合格 primary winner，开放世界 UCM 未建立。** Primary eligible Pareto
为空；CONFIRM5-lite 的局部 descriptive Pareto 为 F10/F18，不能跨 scope 外推。

### 10.4 唯一最高信息增益下一实验

新实验必须 fresh preregister 并使用新的 commitment/reveal，研究 **native
scope-extension architecture**，而非继续调 F18/F22 超参数：

- 同一 unopened pack 比较 native extension candidate、sealed F18、F10、true-state
  upper bound、full-history 与 separate-task baseline；
- 禁止用 visible-history replay 迁移旧患者；extension 必须从旧 state + 新公开 delta
  原生、局部、可审计地生成新 state；
- 对 new check、opposite-response new treatment、new task 事先冻结 pass/fail threshold；
- 恢复 pair probes，强制 collision、OOD、false split、cost/state growth 与旧 scope
  regression 门；
- 若无法同时通过，就报告动态增长/无压缩/开放世界失败，而不是添加第二患者状态。

这项实验最直接区分：失败究竟来自当前 monolithic catalog architecture，还是公开历史
下根本没有可原生扩展的有限 shared state。
