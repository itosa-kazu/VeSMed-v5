# Unified Clinical Map 形式规格与最终合规判定

> 状态：**FROZEN-v1 semantics + executed final conformance verdict。**
> 本文规定 UCM 患者世界模型必须表达什么、允许看到什么以及什么证据可以支持什么声明。数值阈值、wire schema、W01–W20 生成器、oracle、probe 集合和 freeze digest 已由 `BENCHMARK_V1_FREEZE.json` 固定；末节给出实际候选判定。
> 规范词：`MUST / MUST NOT / SHOULD / MAY` 分别表示硬要求、硬禁止、默认要求和允许选择。
> 边界：K0 的隔离执行、canonical JSON、hash、append-only result 等模式可以作为测试基础设施；K0、TEL、接口或路由本身不是 UCM，也不能作为本规格的满足证据。

## 1. 研究对象与符号

一个 benchmark episode 在概率空间上包含：

- 隐藏患者状态或机制 `X_t`；
- 跨时间稳定或缓慢变化的个体背景 `Theta`；
- 已实施动作 `A_t`；
- 生理状态转移核 `K_X`；
- 观察生成与可获得过程 `K_O`；
- 当前诊断目标 `G_t`；
- 未来事件、轨迹和结局 `Y_{t:T}`；
- 评价用效用 `u(Y, policy)`。

这些对象属于 simulator/judge 的私有真值层。候选不得读取 `X_t`、`Theta` 的 oracle 值、未发生未来、未实施动作下的反事实、utility truth、case/test/world ID 或 generator seed。

候选可以学习一个跨患者只读模型制品：

```text
M = 训练后冻结的全局参数、结构、diagnose/rollout 参数与 catalog
```

单个患者截至 cut 的唯一可持续对象是：

```text
Z_s = Phi_M(H_s^pub; r)
```

其中 `s` 是**可获得时间 cut**，`H_s^pub` 是候选截至该 cut 合法可见的公开历史，`r` 是显式 inference seed。`Z_s` 可以是向量、belief、图、粒子集、预测测试向量、typed program 或动态结构；数据结构名称不构成合规或充分性证据。

## 2. 时间与公开历史

### 2.1 三种时间

每个公开 event `e` 至少区分：

```text
occurred_at(e)  患者世界中发生的时间
collected_at(e) 采样或测量的时间；不适用时可为空
available_at(e) 候选第一次可以读取该 event 的时间
```

候选在 cut `s` 的公开信息 sigma-algebra 是：

```text
F_s^pub = sigma({ public_projection(e) : available_at(e) <= s })
```

发生过但尚未 `available` 的事件 MUST NOT 进入 `H_s^pub` 或 `Z_s`。late-arriving observation 在新的 cut 可以修正对过去的 belief，但不得改变旧 state bytes 或让旧 cut 的输出事后获得该信息。

### 2.2 公开历史

`H_s^pub` 是按 benchmark 冻结规则排序、截至 `s` 可见的以下 typed events：

```text
PublicEvent = ObservationAvailable
            | PerformedTreatment
            | PlannedTreatment
            | TestOrdered
            | TestPerformed
            | ContextUpdate
```

公开 payload MAY 包含临床数值、单位、观察条件、事件时间和不带语义答案的去重 token。它 MUST NOT 包含 `hidden_state`、`oracle`、`future`、`actual_future`、`reward_to_come`、`expected_answer`、split、test/world/case ID 或可恢复这些字段的编码。

`PlannedTreatment` 只是关于决策过程的观察证据；只有 `PerformedTreatment` 可以触发生理 action transition。`TestOrdered` 与 `TestPerformed` 也不等于结果已经 `available`。

### 2.3 历史可见性原则

1. `initialize` MAY 读取初始 cut 的全部 `H_s^pub`。
2. 初始化后，`update` 只能读取旧 `Z`、本次新可见 delta、显式 `advance_to` 和显式 seed。
3. base candidate 的 `diagnose`、`rollout` MUST NOT 读取 `H_s^pub`、患者文件、episode cache 或另一份患者表示。OOD 由 parent 对同一 state 的这两类输出做 exact projection，不存在 `ood` candidate RPC；novel readout 只能由 candidate seal 后的独立 extension worker 读取 sealed state，仍不得读取历史。
4. query MUST NOT 预先告知 state producer 随后会问哪个任务、世界、动作或读出。
5. full-history baseline MAY 把 `H_s^pub` 明文保存为状态，但必须声明 `full_history_baseline` 并照常计算长度、内存与时间增长；其他候选不得把 raw history 或其可逆压缩伪装成紧凑状态。

## 3. Scope：任何“充分”声明都必须带范围

UCM 的声明范围记为：

```text
S = (P, O, A, Q, Pi, Tau, Gamma, Y, U, D, R)
```

其中：

- `P`：人口、宿主背景和机制支持域；
- `O`：观察类型、精度、缺失与可获得过程；
- `A`：可实施治疗和其他生理动作 catalog；
- `Q`：允许的检查 catalog；
- `Pi`：允许的开环/自适应未来策略及最大组合长度；
- `Tau`：预测 horizon 集合；
- `Gamma`：诊断目标的行为相关粒度；
- `Y`：需要保留的未来状态、观察、事件和结局闭包；
- `U`：固定 benchmark utility/价值函数集合；
- `D`：比较概率分布与行为的距离；
- `R`：训练数据、资源、隔离和识别假设。

`S` 只冻结语义闭包和执行协议。`R` 可以绑定 TRAIN5/EVAL5 的 closed schema、各五个 replicate、zipped pairing 和时序，但 MUST NOT 包含 raw seed、实际 tuple、`TRAIN5_PRECOMMIT.json`/EVAL5 commitment 值或 panel digest；这些只能在 code-owned semantic freeze 之后进入运行 authority chain。

所有结果 MUST 引用 `scope_id` 或其 digest。脱离 `S` 的“这是充分/最小/统一状态”是无效声明。

加入新检查、新治疗、更长 horizon、新宿主人群或新结局会产生新范围 `S'`。旧 `Z^[S]` 对 `S'` 的合法响应只有：

1. 证明原状态在新范围仍充分；
2. 通过已声明的局部 refinement/migration 细分状态；
3. 返回 `scope_insufficient` 并指出缺少的信息；
4. 承认必须重新学习或扩大状态。

不得把未知 action 静默映射到最相近旧 action，也不得把旧范围结论无条件外推到 `S'`。

## 4. 共享患者状态

### 4.1 患者状态、模型和 query 分离

运行时对象必须分为：

```text
M        跨患者、训练后冻结的只读 ModelArtifact
Z_s      单患者、单 cut 的唯一 SharedPatientState
q        非患者特异的 typed query
Y_hat    readout prediction
L        runner 持有的审计/lineage ledger
```

`M` MAY 包含不同 head 的全局参数，但 MUST NOT 在评估时吸收患者特异 latent。`q` MAY 指定 horizon、policy、输出字段和固定 utility，但 MUST NOT 携带患者历史、真实未来或答案。`L` 中的 state hash、episode handle 和 test metadata 不传给候选。

### 4.2 closed state

`Z_s` MUST 是可序列化、closed-schema、惰性的数据值。它不得依赖：

- 内存地址、callback、进程对象或文件/网络句柄；
- module global、SQLite、临时文件、GPU cache 或远端服务中的第二份患者数据；
- 上一次 query 的调用顺序；
- wall clock、PID、临时路径或未声明 RNG；
- 当前/未来 task、test、world、case 或预期答案。

若候选使用粒子、采样器或递归 RNG continuation，继续计算所需的患者特异随机状态必须显式包含在 `Z_s` 中，或由 runner 显式 seed 完全决定。

### 4.3 canonical identity

每个状态 envelope SHOULD 至少绑定：

```text
protocol_version
candidate_id
model_digest
catalog/scope_digest
state_schema_version
cut.available_time
representation
declared_state_class
```

canonical bytes 与 `state_hash` 由 runner 计算，候选不能自报后要求信任。确切 canonicalization 和 domain separator 将随 benchmark v1 冻结；本草案不宣称其已冻结。

同一 cut 的 diagnosis、no-op、continue、stop、A/B/C rollout 必须由 runner 实际传入**同一份 exact state bytes**，并在外层 transcript 记录同一 `consumed_state_hash`。OOD 是 parent 对这些同-state diagnose+rollout rows 的冻结 exact projection，不发起额外 candidate call；novel readout 则在 candidate seal 后由独立封印的 extension worker 读取该 sealed state。hash 只证明 operational identity，不证明语义充分或最小。

### 4.4 operational closure 与 semantic unity

二者必须分开报告：

- `operational_state_closure`：fresh process 只凭 `M + Z + q` 可以完成 readout，只凭 `M + Z + delta` 可以更新；没有别的患者对象跨调用存活。
- `semantic_unity`：`Z` 不是 `(z_diagnosis, z_natural, z_treatment)` 三块互不相干 task state 的机械拼接，也没有 task-exclusive update path。

`semantic_unity` 至少要求：

1. patient-dependent computation graph 只有一个持久 state root；
2. `initialize/update` 与 task 无关；
3. natural 与 treatment 使用同一 controlled transition core；
4. 没有 task-exclusive persistent store、checkpoint slot 或 history re-encoder；
5. 同一 informative update 后，所有读出都从新 `Z` 重新计算；
6. state component audit、history deletion、post-seal independent extension-worker novel readout 和 collision evidence 不支持 task multiplexing 或隐藏完整历史；W04/base 已有 output bundle 的字段、改名或确定性重投影不计 novel-readout evidence。

有限黑箱 I/O 测试不能证明 opaque payload 内部不存在三块 latent。无法审计时，最高只能标 `operationally_closed_shared_state`，`semantic_unity=INCOMPLETE`。

## 5. 统一更新算子

候选必须提供一个与 task 无关的递推算子：

```text
Z_{s'} = U_M(Z_s, Delta_(s,s'], advance_to=s'; r')
```

其中 `Delta_(s,s']` 只含在旧 cut 后新变得可见的公开 events。即使没有新 event，时间推进也必须以空 delta 加显式 `advance_to` 表达；候选不得自行读取墙钟。

对于公开历史拼接，更新闭合要求：

```text
Phi_M(H_s^pub append Delta) ~= U_M(Phi_M(H_s^pub), Delta)
```

`~=` 在 benchmark 冻结的 state canonical equality 或受控 readout 容差内判断。必须检验：

1. incremental update 与 clean replay 等价；
2. 同一 event 重复投递幂等；
3. 合法 batching 与逐 event 更新等价；
4. late event 在新 cut 被正确吸收，但不污染旧 cut；
5. query 前后更新结果不依赖 query 顺序；
6. 空 delta 的时间推进只依赖显式 cut；
7. 实际动作一经 `Performed` 就进入 factual lineage，随后 response 再继续更新；
8. 更新失败返回 typed status，不得保留或回退到隐藏 task state。

informative update 不被强制要求改变 hash：行为上无信息或重复 event 可以得到相同表示。反过来，仅 hash 改变也不证明吸收了信息；必须检查下游受控行为。

## 6. 诊断与 rollout

### 6.1 诊断

诊断读出是：

```text
D_M(Z_s, q_D) -> P_hat(Gamma_s | Z_s), support, status
```

它 MUST：

- 输出 `Gamma` 中机制/疾病/病程类型的概率分布，并允许 `unknown`/`abstain`；
- 使用与 scope 一致的标签粒度；行为不可区分的标签应保留不确定性，而不是靠名字强拆状态；
- 只读取 `M`、`Z_s` 和非患者特异 `q_D`；
- 不把诊断 label 当成 rollout 的隐藏输入捷径。

为了同时支持诊断和未来行为，scope 中的诊断 target 定义为行为相关 quotient。正式充分性判断使用当前 target 与未来的联合对象：

```text
W^[S] = (Gamma_s, Y_{s:s+tau} for tau in Tau)
```

若 benchmark 需要区分两个临床名字，但其 `Gamma` 和所有范围内未来完全相同，则那是标签评价问题，不应伪造一个动力学状态差异。

### 6.2 单一 controlled rollout

所有自然病程与治疗反事实必须调用同一个语义入口：

```text
R_M(Z_s, pi, q_R; r) -> P_hat(Y_{s:s+tau} | Z_s, do(pi)), support, status
```

natural forecast 只是选择特定 `pi`，不是第二套 dynamics。rollout MAY 在单次调用内创建 ephemeral simulation scratch，但 scratch 必须完全由 `M + Z + pi + seed` 派生，不能持久化、回写模型或成为 factual state。

rollout 必须返回可评分分布，而不只是点估计；所有 policy 使用同一 outcome schema。治疗选择由 judge 以冻结 utility 对预测分布做统一 argmax/tie-break，候选自带 recommender 只能是附加输出。

### 6.3 factual update 与 counterfactual query 分开

```text
Z_s --query do(A)--> prediction only
Z_s --query do(B)--> prediction only
Z_s --actual PerformedTreatment(A) + response--> U(...) = Z_s'
```

counterfactual query MUST 是纯函数：

- 不改变 factual `Z_s`、模型制品或文件；
- A/B/no-op 的调用顺序置换不改变各自输出；
- 不读取实际发生的未来来预测未实施动作；
- 不生成 factual child state。

只有实际可见事件通过 `update` 生成新 lineage state。

## 7. Action 与 policy 语义

未来策略采用 typed sum：

```text
FuturePolicy = NoNewAction
             | ContinueCurrent(explicit_schedule)
             | StopControllable(explicit_stop_schedule)
             | Do(treatment_or_test_schedule)
             | CompositePolicy(ordered_or_adaptive_actions)
```

### 7.1 `NoNewAction`

cut 后不新增可控 action。已经实施的药物、既往暴露、装置、延迟队列与生理后效仍按同一 dynamics 持续或衰减。`NoNewAction` 既不自动补下一剂，也不自动撤销既往作用。

### 7.2 `ContinueCurrent`

按 query 中显式 schedule 继续当前治疗。schedule 必须写明可执行动作、剂量/强度、时间与终止条件。它不是 no-op，也不能根据患者隐藏未来临时补剂量，除非 scope 中登记的是可适应 policy。

### 7.3 `StopControllable`

显式取消 cut 后本来会发生的可控给药/治疗/装置操作。它不反转已经发生的暴露或不可逆后果，也不等于“从未治疗”。

### 7.4 `Do(action)`

从同一 factual `Z_s` fork，在指定时间执行 action，并按干预后的转移/观察过程生成未来：

```text
P(Y | Z_s, do(A=a))
```

这不能实现成观察条件 `P(Y | A=a, Z_s)`。检查 action 可以改变信息可获得性，并在世界定义允许时产生生理或观察成本；检查结果只有在 `available_at` 后才供适应 policy 使用。

### 7.5 观察通道与生理通道

action effect 必须能区分：

1. 改变隐藏生理状态；
2. 只改变 observation channel；
3. 同时改变两者；
4. 只改变未来信息结构。

“观察恢复正常”不得自动等价为“内部机制恢复正常”。W05–W07 已进入冻结 benchmark，用于攻击该混淆。

## 8. 受控行为等价与充分性

### 8.1 精确等价

对 scope `S` 中两个公开历史 `h,h'`，定义：

```text
h ~_S h'
iff
for every pi in Pi and tau in Tau:
Law(Gamma_s, Y_[s,s+tau] | h, do(pi))
  = Law(Gamma_s, Y_[s,s+tau] | h', do(pi))
```

策略可以在 scope 允许时根据随后可见结果自适应。等价比较的是给定**公开历史**的条件分布，而不是 simulator 已实现但候选不可见的单个 hidden state。两个完全相同的公开历史即使对应不同 hidden realization，也应形成同一 belief；不能把不可观测真类型泄漏给候选来“消灭碰撞”。

### 8.2 充分、递推和最小

编码器 `Phi` 在 `S` 上：

- **预测—干预充分**：`Phi(h)=Phi(h') => h ~_S h'`；
- **递推闭合**：存在统一 `U`，使任何合法新 event 都能只从旧 state 更新；
- **相对最小**：`h ~_S h' => Phi(h)=Phi(h')` 也成立；
- **有限状态**：表示尺寸对 scope 内 history length 有冻结上界；
- **动态状态**：尺寸可随被证明有必要的新行为区分增长。

相对最小不等于向量维数最低或文件最小。不同坐标若存在保留更新和全部受控未来的双向变换，可表达同一个行为状态。

### 8.3 近似等价

现实候选按行为距离评价：

```text
d_S(h,h') = sup_(pi in Pi, tau in Tau)
             D(Law(W^[S] | h, do(pi)),
               Law(W^[S] | h', do(pi)))
```

并单独检查 utility 差：

```text
risk_gap_S(h,h') = sup_(pi in Pi)
                    | E[u | h, do(pi)] - E[u | h', do(pi)] |
```

`D`、probe 近似、`epsilon_equivalent`、`delta_distinguishable` 和 catastrophic regret margin 必须由 oracle 数值误差与世界 effect gap 预先导出并在 benchmark freeze 中登记；不得看到候选结果后反推。

### 8.4 collision 与 false split

- **状态碰撞**：候选把两段按其状态或冻结 probe 判为相同/极近，但 oracle 显示 `d_S` 显著，尤其存在相反最佳治疗或 catastrophic regret。
- **虚假拆分**：oracle 显示两历史在 `S` 上等价，但候选保留明显不同的行为状态。

危险碰撞是硬失败；虚假拆分主要降低简洁性、样本效率和迁移性。跨架构主度量必须使用冻结行为 probes，而不是候选自报 latent 欧氏距离。

## 9. 信息边界与执行角色

| 角色 | 可以读取 | 必须不能读取 |
|---|---|---|
| trainer | public train stream、允许的 validation、catalog、训练 seed | hidden test、oracle truth、future、finalist test seed |
| state-worker | 只读 `M`、初始 public history或 `Z+delta`、scope、显式 seed | task kind、future query set、history outside cut、judge files |
| head-worker | 只读 `M`、同一 exact `Z`、非患者 query、显式 seed；仅执行 `diagnose/rollout` | raw history、simulator、oracle、patient cache、其他患者、`ood/readout` RPC |
| extension-worker | candidate seal 后只读 sealed `M/Z`、独立 extension artifact、non-patient query、显式 seed | raw history、base encoder/updater mutation、candidate-private cache；不得把 W04/base 已有 bundle 当 novel target |
| judge | hidden state、oracle、utility、test metadata、candidate output | 不受候选调用或修改 |
| runner | 调度、sandbox、hash、lineage、audit、append-only result；从同-state diagnose+rollout rows 投影 OOD | 不把 private judge data投影给候选 |

base patient runtime surface 始终且仅为 `initialize/update/diagnose/rollout`。最强结构检查是 cross-process state closure：产生 `Z` 的 worker 销毁后，删除 episode 临时目录；base `diagnose/rollout`、post-seal extension worker 与后续 update 分别在 fresh process 中只凭允许输入完成。

native/GPU 候选若只经过 CPython audit hook，必须如实记录较低 isolation assurance。隔离证据不足是 `INCOMPLETE`，不是候选自动 PASS。

## 10. 操作状态与失败输出

候选 operation 的 typed status 已由 executable benchmark v1 contract 固定为：

```text
ok | abstain | scope_insufficient | unsupported |
invalid_input | numerical_failure
```

- `abstain` 表示在声明范围内证据不足；仍计入 risk/coverage。
- `scope_insufficient` 表示 query 超出所声明 `S`；若 query 实际属于已声明范围，则计为失败。
- `unsupported` 不是免费跳过；必需 query 上计入 coverage failure。
- `invalid_input` 只用于 schema/值域错误，不能用来拒答困难但合法 case。
- `numerical_failure` 必须保留 raw diagnostics，不得丢弃该 episode。

合规 axis 使用三值：

```text
PASS       现有执行证据覆盖并通过该 axis
FAIL       执行证据证明候选或 run 违反该 axis
INCOMPLETE harness、隔离或证据不足，不能据此判 PASS
```

## 11. benchmark v1 failure-code registry

> 下列 code 是 benchmark v1 的稳定命名。其 executable authority、metric triggers、
> thresholds 与测试映射由 `research/unified_map/BENCHMARK_V1_FREEZE.json` 及其绑定的
> contract/source bytes 给出；本文是人读说明，不覆盖 manifest。任何 code 出现都必须
> 保存原始 evidence record。`INCOMPLETE` 与候选 `FAIL` 必须分开，不得压成一句 verdict。

| Code | 触发条件 | 级别 | 直接影响 |
|---|---|---|---|
| `UCM-F001-FUTURE_LEAK` | state/update/readout 接触 cut 后 future 或 actual outcome | HARD | run ineligible |
| `UCM-F002-ORACLE_TRUE_STATE_ACCESS` | 候选接触 hidden state、oracle、counterfactual truth | HARD | run ineligible |
| `UCM-F003-TEST_ID_BRANCH` | 结果依赖 test/world/case/name/opaque handle 而非语义输入 | HARD | run ineligible |
| `UCM-F004-HEAD_HISTORY_ACCESS` | 任一 head 重读 raw history 或重新编码历史 | HARD | 非共享状态 |
| `UCM-F005-TASK_SPECIFIC_STATE` | 存在 diagnosis/natural/treatment 专属患者 latent/update path | HARD | semantic unity FAIL |
| `UCM-F006-HIDDEN_PATIENT_CACHE` | module/global/file/GPU/remote cache 保存第二患者状态 | HARD | operational closure FAIL |
| `UCM-F007-STATE_FANOUT_MISMATCH` | 同 cut 多 readout 未实际消费同一 state bytes/hash | HARD | shared identity FAIL |
| `UCM-F008-STATE_NOT_CLOSED` | fresh process 仅凭 state 无法 readout/update | HARD | operational closure FAIL |
| `UCM-F009-MODEL_MUTATION` | query/update 把患者信息写入只读模型或配置 | HARD | run ineligible |
| `UCM-F010-UPDATE_NOT_RECURSIVE` | 必须重读旧完整历史或 task state 才能更新 | HARD | shared-state claim FAIL |
| `UCM-F011-TIME_VISIBILITY_VIOLATION` | 使用尚未 available 的 observation 或污染旧 cut | HARD | temporal leakage |
| `UCM-F012-QUERY_MUTATES_FACT` | counterfactual query 改变 factual state/model/后续输出 | HARD | counterfactual invalid |
| `UCM-F013-SPLIT_TRANSITION_CORE` | natural 与 treatment 使用不同患者 dynamics/入口 | HARD | semantic unity FAIL |
| `UCM-F014-ACTION_SEMANTICS_CONFLATED` | no-op/continue/stop/do/planned/performed 被混同 | HARD | affected policy results invalid |
| `UCM-F015-CONDITIONING_AS_INTERVENTION` | 以 `P(Y|A)` 冒充 `P(Y|do(A))` 且无识别依据 | HARD | intervention claim invalid |
| `UCM-F016-DANGEROUS_COLLISION` | 冻结 probe 发现相反治疗/灾难 regret 的错误合并 | HARD | candidate ineligible for UCM Pareto |
| `UCM-F017-OOD_FORCED_MATCH` | 指定 OOD 被高置信强配并产生 unsafe action | HARD | OOD gate FAIL |
| `UCM-F018-FULL_HISTORY_MISCLAIM` | 可恢复完整历史却声明 compressed shared state | HARD | compact-UCM claim invalid |
| `UCM-F019-UPDATE_INCONSISTENT` | replay、batching、幂等或 query-order invariant 失败 | HARD/SCOPED | affected update claim FAIL |
| `UCM-F020-NONREPRODUCIBLE` | 同 seal/seed/env 无法重放 state/prediction/metric | HARD | primary result ineligible |
| `UCM-F021-REQUIRED_QUERY_UNSUPPORTED` | 已声明 scope 内必需 readout/action 返回 unsupported | COVERAGE | 计入失败，不得删分母 |
| `UCM-F022-INVALID_DISTRIBUTION` | 概率不归一、NaN/Inf、schema 无效或 outcome 不可评分 | HARD/QUERY | affected record invalid |
| `UCM-F023-RESULT_EVIDENCE_LOSS` | run 覆盖旧结果、缺 raw/seed/seal/checksum | HARD | evidence not auditable |
| `UCM-F024-SCOPE_OVERCLAIM` | 将范围内/合成证据外推为全局或临床结论 | CLAIM | 降低声明上限并纠正文档 |
| `UCM-E001-SEMANTIC_UNITY_UNVERIFIED` | opaque state 无法排除三块 task latent | INCOMPLETE | 只能称 operationally closed |
| `UCM-E002-ISOLATION_INCOMPLETE` | sandbox 无法排除 native/外部 escape | INCOMPLETE | 对应泄漏 axis 不得 PASS |
| `UCM-E003-HARNESS_INCOMPLETE` | mutation 未被杀、oracle/probe/runner 证据不完整 | INCOMPLETE | benchmark 不能证明候选合规 |

同一 run 可同时有候选级 failure 与 harness-level incomplete。例如外部确定性反例可以证明 `UCM-F016`，而 sealed corpus 缺必要 probe 仍可同时是 `UCM-E003`。两条证据链不得互相抵消。

## 12. 声明阶梯与上限

| Level | 可允许的声明 | 最低证据 |
|---|---|---|
| `L0-SPECIFICATION_ONLY` | 已提出明确、可证伪规格或假说 | 文档；无运行结论 |
| `L1-ENCODABLE` | 某表示能编码示例 | 构造例；不证明闭合/充分 |
| `L2-RUNNABLE` | 能 update、diagnose、no-op 与 treatment rollout | 可运行 demo；不证明共享或充分 |
| `L3-BENCHMARK_SUPPORTED` | 在指明的冻结 scope 上通过硬门并形成 Pareto 结果 | benchmark freeze digest、raw evidence、所需 worlds/seeds、合规 vector |
| `L4-POSTFREEZE_REDTEAM_SUPPORTED` | candidate seal 后新反例未推翻指明范围 | 独立 red-team run；失败也必须保留 |
| `L5-INDEPENDENT_IMPLEMENTATION_SUPPORTED` | 第二实现路径复现核心结果 | 独立 source/model seal 与独立 run |

声明上限规则：

1. benchmark 未冻结时，最高不得使用 `BENCHMARK_SUPPORTED`。
2. 只有 state hash 相同，最高只能说 exact payload fan-out；不能说 semantic unity。
3. `operational_state_closure=PASS` 但 `semantic_unity=INCOMPLETE` 时，只能称 operationally closed candidate，不能称“已找到 UCM”。
4. 任一 HARD failure 使该 run 不可进入 UCM Pareto；失败 raw evidence仍保留。
5. red-team 后修改候选产生新 candidate seal；不得把修复后结果倒算成旧 primary run 通过。
6. full-history、separate-task、true-state 和 K0-only 是 baseline/upper bound/negative control，不具备普通共享候选的 waiver 继承权。
7. 即使达到 `L5`，结论仍限定为**已冻结合成微型世界和声明 scope**；不得声称临床有效、生产安全、真实世界因果已识别、全局最优或普遍存在有限 UCM。

历史 Phase 1 的证据上限曾为 `L0-SPECIFICATION_ONLY`。最终执行证据见第 15 节；该历史句不再描述当前状态。

## 13. 最小合规 evidence vector

正式 runner 不应输出一句总 `PASS`，而应至少保留：

```json
{
  "operational_state_closure": "PASS|FAIL|INCOMPLETE",
  "semantic_unity": "PASS|FAIL|INCOMPLETE",
  "shared_state_identity": "PASS|FAIL|INCOMPLETE",
  "head_history_isolation": "PASS|FAIL|INCOMPLETE",
  "no_secondary_patient_state": "PASS|FAIL|INCOMPLETE",
  "oracle_true_state_isolation": "PASS|FAIL|INCOMPLETE",
  "future_time_isolation": "PASS|FAIL|INCOMPLETE",
  "test_id_name_invariance": "PASS|FAIL|INCOMPLETE",
  "cache_process_isolation": "PASS|FAIL|INCOMPLETE",
  "action_semantics": "PASS|FAIL|INCOMPLETE",
  "online_update_lineage": "PASS|FAIL|INCOMPLETE",
  "dangerous_collision_gate": "PASS|FAIL|INCOMPLETE",
  "parent_projected_ood_gate": "PASS|FAIL|INCOMPLETE",
  "reproducibility": "PASS|FAIL|INCOMPLETE",
  "eligible_for_pareto": false,
  "failure_codes": [],
  "decisive_evidence_records": []
}
```

`INCOMPLETE` 从不等于通过。aggregate 必须能从 append-only raw states、updates、
predictions、oracle judge rows、audit transcript 和 checksums 重建。benchmark v1 的
result/metric authority 已由 `BENCHMARK_V1_FREEZE.json` 的 `metric_contract`、
`split_protocol` 及其冻结 runner/contract source bytes 固定；后续 schema 变更必须产生
新 benchmark 版本，不能回写 v1。

## 14. 可推翻本规格候选原理的证据

本文将受控行为等价作为候选核心原理，但不把它宣布为全局定理。以下任一可运行证据都可能要求修订：

1. 存在对全部登记受控未来等价、却为某个必须保留的当前诊断任务提供不同正确答案的历史，且无法通过 `Gamma` quotient 解决；
2. 存在不能由公开历史条件分布描述、但又不允许读取 hidden truth 的可审计个体化决策目标；
3. 递推状态在有限 scope 中被证明必须无界保存完整历史；
4. 新动作/检查序列使每个有限 partition 持续被拆分，且不存在稳定动态 refinement；
5. 所有 operationally closed 候选都被 separate-task baseline 严格支配，或因危险碰撞淘汰。

发生这些结果时，正确结论可以是“只存在局部/动态/无压缩共享状态”或“有限共享状态不存在”。不得增加 task-specific latent 来保护 UCM 名称。

## 15. 最终执行合规裁决

### 15.1 Frozen authority 与实验覆盖

```text
status: FROZEN-v1
worlds/panels: 20 / 21
freeze root: sha256:8acb6623c2fdf79008240c5f5967b2143c4fb5e7bb87a4e8aa9f72e77ef33a2d
metrics: M01--M16
primary replicates: R01--R05
primary rows per full candidate: 1680
canonical experiment index: 38 total / 30 eligible / 8 ineligible / 1 failed attempt
```

EXP-033 F10、EXP-034 F14、EXP-035 F18 在完整 primary scope 的 unsafe
forced-known OOD 分别为 5、21、5，三者 `hard_gate_pass=false`。因此 **primary
eligible Pareto 为空**。EXP-038 F22 v2 虽是有信用的第 30 个实质实验，也因 1 个
危险碰撞与 1 个 unsafe OOD 被 `ABANDON`；失败实验仍计科学证据，不计成功候选。

### 15.2 F18 最终合规向量

| Field | Verdict | Decisive evidence / boundary |
|---|---|---|
| `operational_state_closure` | PASS in implemented scope | initialize/update/diagnose/rollout 与 demo 使用可序列化 shared state |
| `shared_state_identity` | PASS in implemented scope | diagnosis、no-op、A/B/C 与 update 前后均绑定同一 patient-state hash |
| `head_history_isolation` | PASS | heads 读取 `SharedPatientState`，不在 query 时重读 history |
| `no_secondary_patient_state` | PASS | stateless heads；无 task-specific patient latent/cache |
| `oracle_true_state_isolation` | PASS | candidate wire 不含 hidden truth；B01 单列 privileged upper bound |
| `future_time_isolation` | PASS | future/oracle 只在 judge target/score 路径 |
| `test_id_name_invariance` | PASS | candidate-visible wire 排除 world/test/case/seed identifiers |
| `cache_process_isolation` | PASS on tested paths | query-order、empty/nonempty update replay 与 cold rehydrate checks 无差异 |
| `action_semantics` | PASS only for registered catalog | v2 已登记 actions 的 query side-effect free；不代表 unseen operator 支持 |
| `online_update_lineage` | PASS in registered catalog | public delta 产生新 bound state；REPRO5 update/replay differences 全为 0 |
| `dangerous_collision_gate` | LOCAL PASS ONLY | primary measured F18 pairs与 v2 committed 8 rows 无 dangerous collision；未关闭未知 collision classes |
| `parent_projected_ood_gate` | **PRIMARY FAIL** | EXP-035 有 5 个 unsafe forced-known OOD；v2 的 16/16 local OOD pass 不得冲销 primary |
| `new_check_sufficiency` | **OPEN_WORLD_SCOPE_FAILURE** | v2 216 rollout rows 均 scope-insufficient/abstain；extension fit + visible-history replay 必需 |
| `new_treatment_sufficiency` | **OPEN_WORLD_SCOPE_FAILURE** | opposite-response rows 全部需 migration；safe abstention 不是支持 |
| `new_combination_sufficiency` | MIXED / NOT GENERALIZED | registered natural query 可调用；extension operator 仍 out-of-scope，未预登记 accuracy pass threshold |
| `new_task_sufficiency` | **INCONCLUSIVE** | state/history/true-state capacity ladder无预登记判定标准；数值排序不能证明充分或失败 |
| `state_minimality` | **NOT SUPPORTED** | v2 history-deletion trio 中 4 个 oracle-equivalent rows 均被 false-split |
| `same_state_multi_timescale` | LOCAL PASS / OPEN-WORLD FAIL | 同一旧-catalog state 服务 1/24/168h natural queries；新 check plan 仍需 migration |
| `reproducibility` | **FULL FROZEN CORE PASS** | REPRO5: 1,680 episodes、28,720 rollouts、260 pairs，全部 max-abs differences 与 failure counters 为 0 |
| `eligible_for_primary_pareto` | **false** | primary OOD hard failure 不可由任何均值、lite pack 或 reproduction 补偿 |

### 15.3 CONFIRM5-lite 与 secondary 证据边界

`20260719T090636Z-POSTSEAL-CONFIRM5-25eeeb5ec6` 是
`supplemental_all_world_lite`：W01--W20、C01--C05、train4/val1/test2、pair0，
`complete_benchmark=false`、`no_pair_collision_evidence=true`。F10/F18 在该 scope
通过，只能形成 lite 局部 Pareto；scope receipt
`sha256:cde9098636c7e9186c398bb1b8dd42c0b866580df828aa0f14e4454889a9edc9`
还披露此前一次未 finalization attempt 已加载 private seed。公开 reveal 证明
commitment preimage，不把 lite 提升成 primary confirmation。

M09/M10/M11/M13/M16 secondary battery 明示
`formal_frozen_metric_claim=false`。它只能产生 exploratory descriptions，尤其不能把
novel-readout 数值次序当 `new_task_sufficiency` 的裁决。

### 15.4 Red-team v2 与 evidence level

Strict source-distinct v2 bundle root 是
`sha256:d3b0ecfd8722e9863d84d3bd88ffa30d9e00b04976ac48b50cd00f02f34040b3`，
verdict digest 是
`sha256:805f5264fb6ffd2308628dbdd312ab7500d1c56a65fb1ec0803fafaa91b17bf5`。
它对 sealed F18 与 independent F18 给出一致的局部结构结果，同时明确推翻开放世界
extension closure。旧 red-team v1 是 reused-fixture exploratory run，不给 v2 或 L4
信用。

F18 的正向声明上限仍是 **`L2-RUNNABLE` + source-distinct reproduction evidence**：

- 未达到 `L3-BENCHMARK_SUPPORTED`，因为 primary OOD hard gate 失败；
- v2 已执行但发现 open-world scope failure，故没有
  `L4-POSTFREEZE_REDTEAM_SUPPORTED` 正向结论；
- REPRO5 精确复现 sealed core，不能越过失败的 L3/L4 门，也不重算 oracle metrics、
  不修复 OOD；
- W16/W17 S1 extension-only pairs 按 frozen runner 排除在 primary REPRO5 pair scope，
  需要独立 extension reveal。误开这些 pairs 的旧 run
  `20260719T095421Z-I18-full-repro-f77211903c` 已留
  `FAILED_UNFINALIZED` receipt、0 credit。

### 15.5 允许的最终语义声明

唯一允许的结论是：**有限封闭合成目录内存在局部可用的近似 shared state；当前没有
合格 primary winner，开放世界 UCM 未建立。** Primary eligible Pareto 为空；
CONFIRM5-lite 的 F10/F18 仅为 scope-relative descriptive Pareto。不得声称 clinical
validity、production safety、全局 finite-state existence/nonexistence、L4 或 global
optimality。新任务 sufficiency 保持未知，不得把 `INCONCLUSIVE` 改写为成功或失败。
