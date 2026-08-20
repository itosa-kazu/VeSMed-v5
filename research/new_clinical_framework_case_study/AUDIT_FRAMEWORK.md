# 新临床框架最小内核只读审计

日期：2026-07-20  
审计范围：`framework.py`、`tests/test_contracts.py`；为验证 `refine()` 是否真的可用，另只读核对了 `tests/test_refinement.py` 与 `refinement_experiment.py`。  
边界：本审计不读取、不比较、也不援引 V5。这里审计的是用户新提出的框架及其当前独立实现。

## 结论先行

当前代码**不是这个新框架的完整最小实现**。它实现得最扎实的是：

1. 一份可 canonical JSON 序列化的共享状态；
2. diagnosis / rollout / plan 消费同一 state hash；
3. future-availability、planned/performed 的最低限度隔离；
4. fresh-process recursive update 的 exact-once 路径；
5. 一个独立、有限 shadow world 中的“新治疗触发局部拆分”思想实验。

但四个核心数学部件中，三个仍主要是**接口或序数占位**：

| 新框架部件 | 当前实现判断 |
|---|---|
| 机制／拓扑分支的不确定分布 | 有归一化 score mass，但不是真正 posterior；不支持并发 active branches |
| 分支内局部连续坐标 | 有字段，但几乎所有坐标都由同一个 scalar `load` 复制或取反得到 |
| 代偿／失代偿离散模式 | 有字段并影响 drift，但只是全局趋势阈值；没有 guard、hysteresis 或 branch-local mode transition |
| 动作相关历史摘要 | 有 latest/previous/trend/count 和 exposure map；但不能表达 start/continue/stop、剂量、持续时间、洗脱和累积暴露 |
| 因子图 | **未实现联合推断**；只是把 observation 分桶、平均后加分 |
| 混合受控动力学 | **未实现真正的混合动力学**；是固定 mode drift 加关键词解析出的常数 action effect |
| 分支／分层几何 | 有独立 `branch_distance()`，但没有进入 diagnosis、rollout 或 plan |
| 共享状态 | 机械合同基本成立，是目前最强的部分；但 payload 仍可原地篡改，事件重放不幂等 |
| 局部细化 | shadow-world 思想实验成立；`FrameworkModel.refine()` 本身没有可用迁移与新观测推断闭环 |

因此最准确的状态是：

> **聊天中的架构没有被当前实验推翻；当前代码只验证了其中一部分工程合同。它还没有实现足以检验整套临床架构的推断与动力学内核。**

---

## 什么叫“硬门禁”

这里的硬门禁不是 AUROC 拍一个阈值，也不是“病例最后猜对病名”。它是一个可由单个反例击穿的结构合同。例如：

- future event 改变了旧 cut state：时间门禁失败；
- diagnosis 与 treatment rollout 用的不是同一份 state bytes：共享状态门禁失败；
- 同一个 observation copy 十次就得到十倍证据：因子依赖门禁失败；
- `continue support` 与 `stop support` 给出相同未来：动作历史门禁失败；
- topology flag 开关不改变任何 diagnosis/plan，而几何只在测试函数里单独调用：几何集成门禁失败；
- 新治疗暴露碰撞后，系统既不拆分也不返回 unidentifiable：局部细化门禁失败。

硬门禁回答的是“代码有没有声称的能力”，不是“这个能力在临床上有多准”。

---

## P1：会改变架构结论的关键问题

### P1-1 因子图没有做联合生成／联合推断，`branch_posterior` 不是 posterior

证据：

- `_make_factor_assignment()` 把每个 child **只分配给一个 factor**（`framework.py:241-249`）。
- `_recompute_belief()` 对 factor 内 child severity 取平均，乘一个来源数启发式，再对关联 branch 加正分（`framework.py:460-479`）。
- 随后只是对累计 score 做 `exp` 归一化（`framework.py:480-495`）。
- 模型文件里的 ordinal likelihood、条件概率、measurement context、negative likelihood、latent-state integration 均未被 runtime 使用。
- `_make_factor_branch_map()` 还用 `COMPLEMENT`、`ADAMTS13`、`TAKOTSUBO` 等字符串关键词猜 branch（`framework.py:271-297`），而不是执行声明的生成图。

这能防住“同一 `source_result_id` 的十份复制”，但不能做到：

```text
P(observations | latent state, branch, mode, action context)
→ posterior over branch/mode/local coordinates
```

负证据尤其失真。实测：

```text
无观察：             unknown=0.20, B_ANTI_GBM=0.16
anti-GBM assay 阴性：unknown=0.05, B_ANTI_GBM=0.19
anti-GBM assay 阳性：unknown=0.05, B_ANTI_GBM=0.278...
```

阴性 assay 没有反驳 `B_ANTI_GBM`，反而因为“已识别观察”降低 unknown mass，使该 branch 从 0.16 升到 0.19。

**判断：因子图和规范 posterior 门禁失败。** 当前只能称“typed evidence bucket + normalized compatibility score”。

### P1-2 两个复杂病例要求“并发过程”，当前 categorical branch posterior 无法表示

当前 `branch_posterior` 强制所有候选 branch 加总到 `1-unknown_mass`（`framework.py:481-495`）。它表达的是“这些 branch 中哪一个”，而不是“哪些 process 同时 active”。并且每个 branch 都复制同一份全局 `mode_posterior`（`framework.py:512-535`）。

这在两个病例上都是具体结构失败：

1. `PMC10448002` 同一阶段可同时存在：原始肾脏疾病假说、微血管病过程、肾活检后血肿／失血，以及暂时待排的 HIT。它们不是只能选一个的互斥病名。
2. `PMC7005653` 明确同时存在急性肝衰竭、Takotsubo 心功能障碍和随后休克；肝脏可处于 decompensated，心脏在早期仍 compensated，之后才发生模式切换。

当前引擎不能表达：

```text
P(active process set, per-process mode, local coordinates | public history)
```

只能表达一个竞争式 simplex 和一个全局 mode。

**判断：对这两个“全流程复杂病例”，状态本体门禁失败。** 需要 active-set／factorial branches、product strata，或允许多个机制分支同时激活；mode 至少应 branch-local 或 compartment-local。

### P1-3 分支／分层几何没有进入任何临床推断或计划

`branch_distance()` 确实实现了同 branch 欧氏距离和跨 branch 最短路（`framework.py:651-679`），但：

- `topology` option 除初始化外没有在 belief、diagnose、transition、plan 中读取；
- `diagnose()` 只排序现有 mass（`framework.py:541-553`）；
- `_transition()` 和 `plan()` 不调用 `branch_distance()`（`framework.py:560-649`）；
- 跨 branch distance 完全忽略两端 local coordinates，仅返回无权图边数。

实测 `topology=True/False` 时 diagnosis posterior 和 rollout trajectory 完全相同。

`test_branch_topology_distance_is_not_flat_chart_distance` 只单独调用距离函数（`tests/test_contracts.py:276-298`），因此证明“有这个 utility”，没有证明“几何负责什么患者临床上接近”。

**判断：几何集成门禁失败。** 当前是未接线的演示函数。

### P1-4 混合受控动力学是关键词常数模型，关键动作语义发生反转

当前 transition：

- 取 mode 的最大概率，映射为固定 drift（`framework.py:582-585`）；
- 把**所有 performed action exposure** 的 level 相加，当作 residual support（`framework.py:586-587`）；
- 从 action 文本里搜 `reduce/suppress/improve/support/stop` 决定 `-0.08`，搜 `increase/start/harm` 决定 `+0.06`（`framework.py:588-597`）；
- 一次计算 final load，再把同一个 final 数值复制到每个 trajectory step（`framework.py:597-608`）；
- rollout 中不发生 branch/mode transition，也没有 guard、jump、hysteresis 或 posterior propagation。

实测存在决定性反例：

```text
A_NO_NEW_ACTION              expected burden 0.3028
A_CONTINUE_EXISTING_SUPPORT  expected burden 0.2437
A_STOP_EXISTING_SUPPORT      expected burden 0.2437
A_PLASMA_EXCHANGE_LIKE       expected burden 0.3028
A_RED_CELL_SUPPORT           expected burden 0.2437
```

`continue` 和 `stop` 完全相同，且两者都被关键词 `support/stop` 解释为改善；`PLASMA_EXCHANGE_LIKE` 的 `branch_dependent_down` 不含受支持关键词，因而没有作用。

此外，`PARTIALLY_IDENTIFIED` rollout 仍被 `plan()` 当作 valid candidate（只排除 `UNIDENTIFIABLE`；`framework.py:641-648`）。也就是说，系统可以基于人为常数效果选择因果未识别动作。

**判断：mixed controlled dynamics、no-op/continue/stop、因果诚实门禁失败。**

### P1-5 `FrameworkModel.refine()` 没有形成可运行的局部迁移闭环

`refine()` 只追加：child node、新 observation node、新 action 和 lineage（`framework.py:681-721`）。它没有：

- parent → child 的 state migration kernel；
- old state 到新 model digest 的迁移 API；
- child local charts / child mode / child factor likelihood 的必要补全；
- 将 `new_observation` 接入 factor；
- parent branch 替换／聚合语义；
- old-query non-regression 的 runtime 验证。

实测：

```text
refine 后 child branch 出现在 branch_posterior 中：是
新增 O_NEW_MARKER 被识别：否（recognized=0, unrecognized=1）
旧 state 迁移到 refined model：ValueError: state belongs to a different model version
```

`tests/test_refinement.py` 的七个绿色测试没有调用 `FrameworkModel.refine()`。它们调用的是独立 `refinement_experiment.py` 中手写的 `child_posterior()`、utility table 和 refinement record。这很好地验证了**思想实验**，但没有验证当前 engine 的 local refinement。

**判断：局部细化思想 STRUCTURALLY SUPPORTED；runtime refinement 门禁失败。**

### P1-6 两个真实病例目前没有进入模型；直接 replay 为 0 个 observation 被识别

`test_both_independent_case_schemas_normalize_monotonically` 只检查 schema 可加载、cut 单调、终点 event 数一致（`tests/test_contracts.py:60-70`），不调用 `FrameworkModel` 做逐 cut inference。

直接把两个已归一化病例送入对应模型，实测：

```text
PMC10448002: 74 events，39 rankable observations
recognized=0, unrecognized=39
posterior = 每个已知 branch 0.16, unknown=0.20

PMC7005653: 65 normalized events，52 rankable observations
recognized=0, unrecognized=52
posterior = 每个已知 branch 0.1333..., unknown=0.20
```

原因是病例使用诊断中立 concept（如 `platelet_count`, `serum_ast`），而模型节点是 `O_PLATELET_COUNT_RELATIVE`、`ast_ordinal` 等；当前 `framework.py` 没有执行 concept mapping / measurement normalization。

更严重的是，全体 observation 都 unmapped 时 unknown mass 仍停在 0.20，因为 `factor_strengths` 为空走固定 prior 分支（`framework.py:480-493`）。所以 unknown/OOD 机制也没有在真实 replay 中工作。

**判断：当前没有完成任何真实复杂病例 end-to-end 测试；real-case gate 和 unknown branch gate 失败。** 这不是病例证明框架思想错误，而是实验尚未触达框架主张。

### P1-7 recursive state 只在 exact-once delta 下闭合；重复投递会改写 mode

`update()` 没有保存全局 consumed event set 并去重（`framework.py:376-386, 397-458`）。`lineage.consumed_event_digests` 只保存本次 delta，不阻止同一 event 再消费。

实测把相同的第二次 observation 重投一次：

```text
唯一投递后 mode: recovering=0.72
重复投递后 mode: compensated=0.72
history count: 2 → 3
```

原因是重复 latest 把 trend 从负数改写成 0。`test_recursive_update_is_closed_over_serialized_state` 证明 fresh process 在**精确 delta、只投一次**时闭合（`tests/test_contracts.py:157-164`），没有覆盖 event redelivery。

**判断：共享状态 closure 部分通过，但事件账本幂等门禁失败。**

---

## P2：不会立刻否定结构，但必须在下一轮修正

### P2-1 `SharedPatientState` 不是实际不可变对象

`@dataclass(frozen=True)` 只冻结 `payload` 属性绑定；内部 dict 仍可通过 `state.payload[...]` 原地修改（`framework.py:100-125`）。`_assert_state()` 只核对 `model_digest`（`framework.py:537-539`）。实测可将 `B_ANTI_GBM` mass 改为 `999`，`diagnose()` 仍接受。

应把 canonical bytes 设为权威，或深冻结并验证 state seal / schema / normalization。

### P2-2 `_severity()` 丢失单位、方向、reference range 和 measurement context

任意 >1 数值都用 `log1p(abs(value))/10`（`framework.py:36-76`）。这会把：

- platelet `92,000` 解释成极高“severity”；
- AST 12,760、bilirubin 5.3、INR 3.5 放到无医学单位的同一映射；
- “低才危险”和“高才危险”混为一谈；
- measurement context、assay quality、normal range 完全丢弃。

这解释了为什么目前的 local coordinates 不能称临床连续状态。

### P2-3 local chart 坐标是一个 scalar load 的别名

每个 branch 的普通坐标都等于同一个 `load`；reserve/stability 是 `1-load`；recovery 是全局 mean trend（`framework.py:512-531`）。没有 branch-specific state estimation、坐标 covariance 或 chart transition。

因此“分支内局部连续坐标”目前是 schema shape，不是已实现的局部动力状态。

### P2-4 action exposure 没有生命周期

任何 `PerformedTreatment` 都被设为 `active=True`，没有 stop、end、dose change、decay、cumulative exposure 或 washout（`framework.py:416-423`）。在真实 HAV case 中，转院、插管、导管检查、升压支持、plasma exchange 都可能以默认 level 留在 exposure map，并在 rollout 中被统一当作 residual support。

planned action 不改变 physiology 这条最低门禁通过，但 performed action memory 远未达到“足以支持当前动作集合”的标准。

### P2-5 mode test 不是 hysteresis test

测试用“marked→mild”和“none→mild”制造不同 trend（`tests/test_contracts.py:249-274`），证明 history-derived mode 会改变固定 drift；它没有测试：

- 相同 local continuous coordinates + 不同 prior mode；
- entry/exit guard 不同；
- 跨阈值后撤回负荷仍不立即回原 mode；
- branch-local mode transition。

所以只能标记“mode 字段进入 transition”，不能标记“hysteresis 已实现”。

### P2-6 tests 多为实现同源的自洽性测试，缺少独立 oracle

19 项测试全部绿色，但其中：

- 12 项是 `test_contracts.py` 的机械合同；
- 7 项是独立 finite shadow world 的 refinement 思想实验；
- 0 项是两例真实病例的逐 cut state / diagnosis / forecast / action replay；
- 0 项测试 calibration、negative evidence、concurrent branches、branch-local modes、topology in planning、real action semantics 或 causal identification。

绿色测试应报告为“当前已声明的窄合同通过”，不能报告为“新框架已通过复杂病例”。

---

## T01-T22 门禁状态

| ID | 当前状态 | 审计说明 |
|---|---|---|
| T01 future availability | 通过 | 旧 cut bytes 不受 future event 影响 |
| T02 planned vs performed | 部分通过 | planned 不触发；但 performed start/continue/stop 语义不足 |
| T03 recursive closure | 部分通过 | fresh process exact-once delta 通过；重复投递失败 |
| T04 head isolation | 通过（接口级） | readout 只接 state；未做恶意 side-channel 测试 |
| T05 exact shared bytes | 通过 | 三类 readout 回报同一 hash |
| T06 query purity | 通过 | 顺序不改变 state/output |
| T07 common-cause evidence | 部分通过 | 同 source copy 去重；没有真正 joint factor inference |
| T08 support masking | 部分通过 | exposure 会改 rollout；但所有 exposure 被统一当 support |
| T09 mode hysteresis | 失败 | 只有趋势阈值和固定 drift，无 hysteresis/guard/transition |
| T10 branch geometry | 部分通过 | distance utility 可复现；未进入 diagnosis/plan |
| T11 no-op/continue/stop | 失败 | continue 与 stop 实测完全相同且方向错误 |
| T12 unknown branch | 失败 | 全部真实 observation unmapped 时 unknown 仍为 0.20 |
| T13 dynamic identification | 未测 | 没有真实 response→update→all rollouts 联动测试 |
| T14 natural/treatment core | 机械通过 | 共用 `_transition()`；但 transition 是占位动力学 |
| T15 dangerous collision | shadow-world 通过 | current FrameworkModel 无 collision detector |
| T16 false split | shadow-world 部分覆盖 | 未对 runtime representation 做 cohort false-split 审计 |
| T17 action regret | shadow-world 通过 | synthetic oracle only；没有 clinical / frozen baseline 结果 |
| T18 unseen treatment split | shadow-world 通过 | engine `refine()` 未通过 |
| T19 local migration | 失败 | 无 old-state migration；old model state 被 digest gate 拒绝 |
| T20 unobservable split | shadow-world 通过 | engine 无 child posterior inference/abstention pipeline |
| T21 new check | shadow-world 通过 | engine 新 observation 未接 factor，实测 unmapped |
| T22 schema/version lineage | 部分通过 | 有 digest/lineage metadata；没有可执行 migration evidence |

---

## 对用户两个核心问题的直接回答

### 1. 聊天里的架构答案被推翻了吗？

**没有。** 被推翻的是更强的说法：

> “现有代码和绿色测试已经实现并验证了这个架构，可以据此判断复杂病例效果良好。”

目前证据只支持：共享状态合同可做；mode/topology/factor/refinement 可以定义接口；有限 shadow world 中“新动作触发局部细化”逻辑自洽。

目前证据不支持：真正联合因子推断、并发机制状态、混合动力学、几何驱动的临床邻近、因果治疗计划、真实病例全流程效果。

### 2. 不存在一个理想模型吗？

在**冻结的 actions/checks/horizon/outcomes/tolerance 范围**内，可以抽象定义“理想的行为等价状态”：两段历史对范围内所有策略产生相同未来分布，就合并；否则拆开。

但这不推出一个永久、唯一、有限的全医学模型。新治疗、新检查、新结局会改变等价关系，地图必须局部细化。当前 `refinement_experiment.py` 只证明了这个有限世界逻辑；它没有证明真实临床状态可被当前坐标有限识别。

---

## 验证记录

执行：

```powershell
$env:PYTHONPATH=(Resolve-Path research\new_clinical_framework_case_study)
python -m unittest discover -s research\new_clinical_framework_case_study\tests -v
```

结果：`19 tests passed`。

补充只读探针验证了：

- negative assay 不能反驳 branch；
- topology on/off 对诊断和 rollout 无影响；
- continue/stop 未来完全相同；
- state payload 可原地篡改；
- duplicate event 可把 recovering 改成 compensated；
- `FrameworkModel.refine()` 新 observation unmapped 且无 old-state migration；
- 两个真实病例 direct replay 的 recognized observations 均为 0。

这些探针没有修改源码或病例。

## 下一步（按信息量排序）

1. 先把状态本体改成可表示并发 active processes + branch/compartment-local modes；否则两个选定复杂病例从类型上就装不进去。
2. 接通 diagnosis-neutral concept mapping 和 measurement normalization，做两个病例逐 cut replay；在此之前不要讨论排名效果。
3. 用声明式 likelihood / factor kernels 替换字符串关键词和 severity 加分；至少要让可靠 negative evidence 能反驳 branch。
4. 将 topology/geometry 真正接入 posterior regularization、邻近检索或 planning，并做 on/off 行为反例。
5. 实现 action lifecycle 与真正的 no-op/continue/stop；停止从 action 文本关键词推 effect。
6. 实现 branch-local hybrid transitions、guards 与 hysteresis；rollout 每一步都推进 state/posterior，而不是复制 final 值。
7. 把 local refinement 合并进同一 engine：new check factor、child posterior、migration kernel、旧 query non-regression、unidentifiable 全部必须在 `FrameworkModel` 上测试。
8. 增加 event-id/digest 的 cumulative dedup 与 state seal 验证。

在以上 1-7 之前，最诚实的结论是：**架构候选仍成立；当前 runtime 只是共享状态骨架和若干概念占位，尚未完成对整套架构的有效实验。**
