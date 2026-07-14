# UCM benchmark v1：统一候选合同、硬合规、指标、结果与冻结机制（agent 草案）

> 状态：**仅供主 agent 合并决策的草案，不是已冻结 benchmark**。
> 范围：只定义 UCM 患者世界模型的可运行比较合同；不把 K0 的控制面或接口本身当作 UCM。
> 规范词：`MUST / MUST NOT / SHOULD` 分别表示硬要求、硬禁止和默认要求。
> 设计目标：让“同一个 `Z_t`”成为运行时可证伪事实，而不是类名、接口名或宣言。

## 0. 建议先冻结的结论

1. **唯一患者状态是可序列化值，不是进程对象。** 每次更新产生一个 canonical `StateEnvelope`；runner 而非候选计算 `state_hash`。
2. **状态推断/更新和各 readout 分进程执行。** readout 进程只得到：只读模型制品、同一份 state bytes、非患者特异的 query；它拿不到原始历史、simulator、oracle、其他患者或上一次调用内存。自然病程和 A/B/C 治疗不得各有入口，必须走同一个 `rollout(Z_t, plan)`。
3. **允许不同 head 和 head 参数，但不允许第二份患者状态。** head 内从 `Z_t` 临时计算的 scratch 可以存在，但不能持久化、跨调用、回写模型或成为另一份按任务更新的 latent。
4. **no-op、继续当前治疗、停止治疗和 `do(action)` 必须是四种可区分语义。** 反事实查询是纯函数，不修改 factual state。
5. **碰撞/虚假拆分的主度量用冻结 probe 集合上的行为距离，不用候选自报的 latent 欧氏距离。** 这样 vector、graph、belief、program state 才可公平比较。
6. **未来泄漏、true-state/oracle/test-id 访问、head 读取历史、隐藏缓存、state hash 不同、危险治疗碰撞均为不可被平均分补偿的硬失败。**
7. **结果永不覆盖。** 每个 run 独占目录，保留 raw state、raw prediction、oracle judge record、进程审计、失败轨迹和 checksum；aggregate 必须可从 raw 重建。
8. **freeze 分两层。** benchmark 的语义、生成器、oracle、指标和测试种子抽取协议先冻结；同一批 finalist 源码/模型 seal 后才抽取并揭示共同 hidden test seed。冻结前开发不得看到 hidden case/oracle。

## 1. “一个共享状态”的可执行定义

### 1.1 模型制品不等于患者状态

运行时对象严格分成：

- `ModelArtifact M`：训练后冻结、跨患者共享、只读；可以包含 encoder、dynamics、diagnostic/forecast heads 的全局参数。
- `SharedPatientState Z_t`：单个患者截至 `cut_t` 的全部患者特异信息；只有一份 canonical serialization。
- `Query Q`：horizon、允许动作/检查、输出变量和固定 utility 的说明；不得含患者历史、真实未来或答案。
- `Prediction Y_hat`：候选返回的预测值；runner 在进程边界外附加其实际传入的 `input_state_hash`，候选无需也不应看到 evaluator 的 state ID/hash。

不同 head 可以使用不同的全局参数，但它们必须只从同一 `Z_t` 读患者信息。以下不是“共享状态”：

- 诊断 latent、forecast latent、treatment latent 各自从历史产生；
- query 时再次调用 history encoder；
- 在全局模型文件、module global、SQLite、临时文件或 GPU cache 中保存患者特异向量；
- 把完整历史藏进模型制品或 query；
- 根据 task/test/world/disease ID 选一套患者状态。

### 1.2 canonical state 与 hash

状态必须是 closed-schema、JSON-like 的 inert data；禁止 pickle、callback、文件句柄、网络句柄、可执行代码和任意对象引用。允许的表示包括有限数值、数组、稀疏图、离散/连续分布参数、粒子集、typed AST、机制网络或它们的组合。

推荐 state wire schema：

```json
{
  "protocol": "ucm-state/1",
  "candidate_id": "candidate-name",
  "model_digest": "sha256:...",
  "catalog_digest": "sha256:...",
  "state_schema_version": "1",
  "cut": {
    "event_time": "...",
    "available_time": "..."
  },
  "representation": {},
  "declared_state_class": "compressed_shared_state"
}
```

`declared_state_class` 只能是：

- `compressed_shared_state`；
- `dynamic_shared_state`；
- `full_history_baseline`。

其中 full-history baseline 可以把历史作为 `representation`，但必须明确标成 baseline，不能声称紧凑；其 state bytes/history-length slope 必须照常计量。其他候选的 state 禁止出现 raw history event、raw observation payload 或其可逆封装。

canonicalization 必须固定为 UTF-8 JSON、key 排序、compact separators、禁止 NaN/Inf、数值格式固定、末尾 LF。`state_hash` 由 runner 对 canonical bytes 计算：

```text
state_hash = "sha256:" + SHA256(
    "UCM_STATE_V1\\0"
    || candidate_bundle_digest
    || catalog_digest
    || canonical(cut)
    || canonical(representation)
)
state_id   = "ucm-state:" + candidate_id + ":" + state_hash[7:23]
```

`state_id/state_hash` 是 harness ledger 字段，不传给候选。`parent_state_hash`、runner 的随机 `state_instance_id` 和 operation 名也只放 ledger，**不进入 content hash**；否则同一语义状态经 incremental 与 replay 两条路径会被人为拆开。

ledger 至少记录：

```json
{
  "state_instance_id": "harness-generated UUID",
  "state_hash": "sha256:...",
  "parent_state_hash": "sha256:... or null",
  "operation": "initialize|update",
  "delta_digest": "sha256:... or null",
  "candidate_bundle_digest": "sha256:...",
  "catalog_digest": "sha256:...",
  "as_of": "...",
  "payload_size_bytes": 0
}
```

状态内不得出现 episode/case/test/world/split ID、预期疾病、真实机制、未来值或 oracle 字段。runner 的 episode handle 放在外层调度记录中，不进入 state bytes/hash。

同一输入、同一冻结模型和同一 inference seed 必须得到 byte-identical state。若内部使用粒子或随机采样，粒子及 RNG continuation 必须作为 `Z_t` 的显式部分，不能留在进程 cache。

### 1.3 state hash 的含义和限制

- 所有 head 对同一 cut 的输出由 runner 附加同一 `consumed_state_hash`；该值来自实际传入 bytes，不能信候选自报。
- query 不得修改 state；查询前后 state bytes 与模型制品 digest 必须相同。
- informative update 通常产生新 hash；重复 event 或行为上真正无信息的 event 可以保持原 hash。不要为了 demo 强制伪造变化。
- hash 不证明 state 足够，也不证明紧凑；它只证明所有 readout 消费了同一份 exact bytes。充分性由 collision/regret/OOD/新读出测试证明。

## 2. 候选协议：值传递、分角色、可隔离

### 2.1 四类进程角色

推荐把已有 K0 isolated runner 的“parent judge 与 candidate view 物理分离、canonical digest、audit transcript”复用为基础设施，但使用全新的 UCM wire protocol：

1. `trainer`：只能见 train generator/cases 与允许的 validation；产出冻结 `ModelArtifact`。
2. `state-worker`：只做 `initialize/update`，收到 prior state 和 newly available event batch；不能收到 task kind。
3. `head-worker`：只做 `diagnose/rollout/ood/readout`，收到只读模型、同一 state、query；不能收到历史。自然与干预未来仅由 `rollout` 的 typed plan 区分。
4. `judge`：唯一持有 oracle、true state、未发生未来、utility truth 和 test ID；候选进程不可导入或读其文件。

纯 Python 候选可沿用 `python -I -S`、最小 allow-list package、audit hook。使用 PyTorch/native/GPU 的候选必须放进无网络、只读模型挂载、空临时目录、系统调用/文件访问受限的 OS container/AppContainer；仅靠 CPython audit hook 不足时，结果必须标 `isolation_assurance=python_only`，不得声称已防住 native escape。

### 2.2 规范接口

下列是语义接口；实际可用 JSONL RPC 实现，避免把 Python 类本身当合同。

```python
class UnifiedMapCandidate(Protocol):
    def manifest(self) -> CandidateManifest: ...

    # training role only
    def fit(self, train_stream, validation_stream, train_seed) -> FitReceipt: ...
    def freeze_model(self) -> ModelArtifact: ...

    # state-worker only; request 中没有 task/test/world ID
    def initialize(self, public_baseline_events, inference_seed) -> StateEnvelope: ...
    def update(self, prior_state, newly_available_events, inference_seed) -> UpdateResult: ...

    # head-worker only;每次可在 fresh process 中调用
    def diagnose(self, state, request) -> DiagnosticPrediction: ...
    def rollout(self, state, plan, request) -> TrajectoryPrediction: ...
    def ood(self, state, request) -> OODPrediction: ...
```

`NoNewAction`、`ContinueCurrent`、治疗 A/B/C 都调用同一个 `rollout`；forecast/counterfactual 只是 judge 按 plan 种类给结果加的标签，不能映射到两套候选实现或两套 dynamics。

不提供以下接口：

- `diagnose(history)` / `forecast(history)` / `treat(history)`；
- 独立的 `forecast_noop(...)` 与 `forecast_treatment(...)` dynamics；
- `make_state_for_task(task)`；
- `query(test_id, world_id, expected_label)`；
- `counterfactual(state, actual_future)`；
- `head.update_private_latent(...)`。

所有 candidate-visible request schema 必须 `additionalProperties: false`。可见患者 event 仅含 typed `kind/occurred_at/collected_at/available_at/payload/event_uid`；明确排除 `hidden_state/oracle/future/actual_future/reward_to_come/generator_seed/test_id/case_id/split/expected_answer`。`event_uid` 只用于去重，需有 UID/顺序 alpha-renaming 不变性测试，不能被当成世界或答案标签。

### 2.3 `CandidateManifest`

至少冻结以下字段：

```json
{
  "protocol": "ucm-candidate-manifest/1",
  "candidate_id": "...",
  "architecture_family": "psr|belief_ssm|dynamic_scm|...",
  "implementation_version": "...",
  "model_digest": "sha256:...",
  "source_seal_digest": "sha256:...",
  "dependency_lock_digest": "sha256:...",
  "state_schema_version": "...",
  "declared_state_class": "compressed_shared_state",
  "heads": ["diagnose", "rollout", "ood"],
  "uses_patient_specific_persistent_storage": false,
  "supports_online_update": true,
  "supports_late_arriving_events": true,
  "inference_determinism": "deterministic_given_seed",
  "training_data_budget": {},
  "known_limitations": []
}
```

manifest 声明不是合规证据；动态测试必须验证。

### 2.4 `UpdateResult`

```json
{
  "protocol": "ucm-update-result/1",
  "prior_state_hash": "sha256:...",
  "consumed_event_batch_digest": "sha256:...",
  "new_state": {},
  "new_state_hash": "runner-computed-after-return",
  "update_status": "ok|unsupported|invalid",
  "diagnostics": {}
}
```

`newly_available_events` 是相对于 prior cut 的增量 public view，并带显式 `advance_to`。即使 event 列表为空，时间推进也必须通过 `update(state, {advance_to, events: []})` 表达；state-worker 不得自行读墙钟。state-worker 不得自行读取完整历史；runner 另行做 clean replay oracle，用于比较 incremental 与从初始事件逐步 replay 的结果。

### 2.5 readout 输出

所有 readout 公共 envelope：

```json
{
  "protocol": "ucm-prediction/1",
  "prediction_kind": "diagnosis|forecast|counterfactual|ood|novel_readout",
  "query_digest": "sha256:...",
  "status": "ok|abstain|unsupported|invalid",
  "distribution": {},
  "support": {
    "ood_score": 0.0,
    "unknown_probability": 0.0
  },
  "diagnostics": {}
}
```

上述是 candidate output；runner transcript 在外层增加 `input_state_hash/consumed_state_hash`，并验证调用前后 exact state bytes 与 model digest 未变。不要把 evaluator hash 暴露给候选后再相信它回显。

诊断必须输出机制/疾病类型 posterior（含 `unknown`）；轨迹必须输出可评分分布而不只是点预测；反事实必须对每个 policy 输出相同 outcome schema。`unsupported` 不是免费跳过，统一计入 coverage failure。

治疗选择由 judge 使用候选预测分布和冻结 utility 计算，而不是允许每个候选另写不可审计的 treatment recommender。候选仍可输出推荐作为附加信息，但 regret 以 judge 的统一 argmax/tie-break 为准。

## 3. 时间、action、no-op 与更新语义

### 3.1 三种时间不能塌缩

每个 event 至少有：

- `occurred_at`：患者世界中发生；
- `collected_at`：检查/采集；
- `available_at`：候选在此后才可见。

state cut 以 `available_at <= cut.available_time` 决定可见性；发生过但尚未 available 的结果不得进入 state。区间使用冻结的半开/闭规则，并有 boundary 与 `+epsilon` 测试。

### 3.2 action 的 typed sum

```text
PatientEvent = ObservationAvailable
             | PerformedTreatment
             | PlannedTreatment
             | TestOrdered
             | TestPerformed
             | ContextUpdate

FuturePolicy = NoNewAction
             | ContinueCurrent(explicit_schedule)
             | StopControllable(explicit_stop_schedule)
             | Do(treatment_schedule)
             | Do(test_schedule)
             | CompositePolicy(ordered_actions)
```

硬语义：

- `NoNewAction`：从 cut 后不施加新的 action；state 中既往治疗造成的持续/衰减效应仍按动力学演化。
- `ContinueCurrent`：按 request 中显式 schedule 继续给药/治疗，**不是** no-op。
- `StopControllable`：显式停止未来可控暴露，不能用 no-op 暗示。
- `Do(A)`：从同一 factual state fork，在指定时间执行 A；不是观察到历史上选择 A 的 conditioning。
- `PlannedTreatment`：可以作为关于决策过程的观察证据，但不能触发生理 treatment effect；只有 `PerformedTreatment` 进入 action transition。
- 退热药等 observation-channel action 与 mechanism/state action 必须分开；W06/W07 检验二者。

### 3.3 counterfactual purity

对 A/B/C 和 no-op 的每个查询都从同一 exact state bytes 开始，在 fresh head-worker 执行：

```text
Z_t --query NoNewAction--> predicted future only
Z_t --query Do(A)-------> predicted future only
Z_t --query Do(B)-------> predicted future only
Z_t --query Do(C)-------> predicted future only
```

这些调用不得创建 factual new state。只有实际 `PerformedTreatment` 和随后 available 的真实 response 通过 `update` 产生 `Z_{t+}`。A/B/C 查询顺序置换后，每个 policy 的结果必须相同；模型/state 文件 digest 前后必须相同。

### 3.4 online update invariants

1. `incremental update == clean event replay`（canonical hash 或冻结数值容差内行为等价）。
2. 同一 event ID 重复投递幂等；不得重复计数。
3. 同一 causal order 的单条更新与合法 batching 等价。
4. late-arriving observation 按 event time 与 available time 正确吸收，不得倒泄漏到旧 cut。
5. query 是只读的；任何 query 前后 update 结果不受 query 顺序影响。
6. 实际治疗反应到来后，diagnosis、natural forecast、treatment forecasts 都必须从新的同一 hash 重算；不得只更新其中一个 task latent。
7. 空 delta 仍可推进到新的 cut；调用结果只由显式 `advance_to` 决定，不得依赖 wall clock/PID/调用次数。
8. 未知的新 action 必须返回 typed `state_insufficient`/`unsupported`，不能以高置信默认映射到旧 action。

## 4. 硬合规测试矩阵

每项都要有至少一个故意作弊 mutant，证明 harness 会杀死它。`HARD_FAIL` 不得用其他指标补偿。

最强结构门是 **cross-process state closure**：worker A 执行 `initialize` 后立即销毁；删除其 episode 临时目录；只保留只读 candidate bundle、catalog 和 sealed state payload；diagnosis/no-op/A/B/C 分别在 fresh workers 中运行；后续 `update` 也必须在 fresh worker 中只凭 `old state + delta + explicit seed` 成功。若 payload 只是内存/文件 handle，或另有患者缓存，这一步会直接失败。

| ID | 自动测试 | 通过条件 | 主要杀死的作弊/缺陷 | 级别 |
|---|---|---|---|---|
| C01 | exact shared-state fan-out | diagnose/no-op/A/B/C/ood 的 runner transcript 均附加同一实际输入 hash | 三套 latent 包装成统一 | HARD |
| C02 | head history denial | fresh head sandbox 中无 history 文件/对象/环境变量；读取尝试被审计拒绝 | head 偷读原史、query 时重编码 | HARD |
| C03 | state-worker task blindness | initialize/update 请求中无 task；交换下游 task 顺序不改变 state bytes | task-specific encoder/state | HARD |
| C04 | clean-process replay | 重启进程后同模型+同 state+同 query 输出相同 | module global/GPU cache 第二状态 | HARD |
| C05 | warm/cold permutation | future/cross-patient/wrong-task 预热后，目标调用等于 cold call | 未按 state hash key 的 cache | HARD |
| C06 | model immutability | 每次 patient call 前后模型、配置、依赖 mount digest 相同 | 把患者 latent 写进模型文件 | HARD |
| C07 | state closed schema | 无句柄/pickle/code；无 case/test/world/split/oracle/future 字段或 canary | 任意 payload、隐藏引用 | HARD |
| C08 | candidate-view physical isolation | worker inventory/input/transcript 无 simulator true state、oracle、future | true-state/oracle leak | HARD |
| C09 | known-path/syscall probe | 外部文件、网络、subprocess、shared memory、registry 等读取失败并留 transcript | 绕过 stdin 读答案 | HARD |
| C10 | identical-prefix divergent-future pair | 两个 future 不同但截至 cut 完全相同的 case 产生相同 state/output | future observation/outcome leak | HARD |
| C11 | availability boundary | `available_at == cut` 按冻结规则可见，`+epsilon` 不可见 | 时间 off-by-one | HARD |
| C12 | factual-outcome swap | 改变尚未发生的 factual outcome 不改变所有 pre-outcome counterfactual | 用实际未来回答反事实 | HARD |
| C13 | opaque alpha-renaming | world、mechanism、action、observation 名称整体重命名/模块乱序，行为同构 | test/world/disease name branch | HARD |
| C14 | hidden test-id canary | candidate view 没有 test ID；源码/trace 无 Wxx/known ID branch；随机执行顺序不变 | 按测试编号分支 | HARD |
| C15 | cross-patient poison | 先跑患者 P，再 fresh/同进程跑 Q，Q 与单独 cold Q 相同 | 患者缓存串线 | HARD |
| C16 | counterfactual purity/order | query 不改 state/model；A/B/C 顺序置换结果对应相同 | query side effect | HARD |
| C17 | no-op semantics | no-op、continue、stop、zero-dose 在构造世界中产生冻结的不同关系 | no-op=停药或 continue | HARD |
| C18 | plan/performed separation | plan 不触发生理 effect；performed action 触发 | 计划当实施 | HARD |
| C19 | condition/do separation | W15 中关联方向与 intervention 方向相反时，候选保持区分 | conditioning 冒充干预 | HARD |
| C20 | observation/state channel separation | W05–W07 中观察改善不被等同为机制恢复 | observation-is-state | HARD |
| C21 | online update lineage | prior hash、event digest、new hash 可核；new heads 全读 new hash | task 独立 update | HARD |
| C22 | incremental/replay/batch | incremental、合法 batch、clean replay 行为等价 | stale update/cache | HARD |
| C23 | late-event old-cut stability | 未来才 available 的 correction/response 不改变旧 cut | 后见信息倒灌 | HARD |
| C24 | exact dangerous collision | oracle 证明治疗最优方向相反的历史不得有同 hash/同预测 | 危险状态合并 | HARD |
| C25 | OOD fail-closed | W18 designated OOD 不得高置信塞入 known class 并给非 abstain 治疗 | closed-world 强配 | HARD |
| C26 | novel-readout isolation | 冻结 state encoder；新 head 只见 state，不见 history | “迁移”时重新读原史 | HARD |
| C27 | full-history disclosure | raw/history canary 若出现在 state，必须声明 full-history baseline | 伪装压缩状态 | HARD for misclaim |
| C28 | run reproducibility | seal、seed、环境相同可重放 raw prediction/metric | 不可复现 | HARD |
| C29 | query preannouncement denial | initialize/update 不知道随后会问 diagnosis/A/B/新任务；改变 future query set 不改 state | 按未来任务造 state | HARD |
| C30 | explicit RNG/clock isolation | PID、tmp path、wall clock、调用排列变化时，同显式 seed 结果相同 | 隐式 RNG/时钟状态 | HARD |
| C31 | undeclared history-memory probe | 无关 provenance canary、event UID/顺序重命名和 history-length ladder 检查可恢复性/size slope | 压缩/加密暗存原史 | HARD for misclaim |
| C32 | single controlled rollout entry | no-op/continue/A/B/C 动态调用同一 `rollout`，无 task-specific transition entry | 自然/治疗两套世界模型 | HARD |
| C33 | patient-state-root audit | patient-dependent computation graph 只有一个跨调用 root；无 task-exclusive persistent roots | blob 内三套 latent 串联 | HARD/INCOMPLETE |

### 4.1 防缓存第二状态的具体执行顺序

不能只查 Python 属性名。至少运行以下序列并比较 exact outputs：

```text
cold(Q@Z_old)
warm(Z_future) -> Q@Z_old
warm(other_patient) -> Q@Z_old
warm(diagnosis@Z_old) -> treatment@Z_old
warm(treatment@Z_old) -> diagnosis@Z_old
process_restart -> Q@Z_old
query permutation [A,B,no-op] vs [no-op,B,A]
```

同时记录文件系统 diff、模型 digest、进程 RSS、打开句柄、网络和子进程审计。head 每次 fresh process 是主防线；warm 序列是为了杀死允许复用 worker 时的隐藏状态。

### 4.2 防 test-id/name 分支

静态 grep 只能作提示，不能作主要证据。主要证据是：

- candidate view 根本不含 W01/Wxx、case ID、expected disease；
- runner 用不可预测 opaque episode handle，handle 不进入 state worker；
- 生成同构的 alpha-renamed world/action/observation/mechanism vocabulary；
- 打乱注册/字段/episode 顺序；
- 同一语义不同名称结果同构，不同语义相似名称仍不同；
- sealed source 后再抽 hidden seed。

### 4.3 合规 runner 也要自测

建议内置至少 12 个 mutation candidates：`HistoryPeeker`、`TaskTripleLatent`、`WarmCache`、`FutureReader`、`TrueStateReader`、`TestIdSwitch`、`WorldNameSwitch`、`QueryReencoder`、`ActionAsConditioning`、`NoOpMeansStop`、`ObservationEqualsMechanism`、`FullHistoryDisguised`。freeze 前必须生成 mutation-kill matrix；任一目标 mutant 未被杀死，benchmark 只能标 `HARNESS_INCOMPLETE`，不能据此宣布候选合规。

### 4.4 同一个 hash 仍不能单独证明 semantic unity

黑箱候选可以把 `(z_diagnosis, z_natural, z_treatment)` 串成一个 blob，让三个 head 各读一段；它会通过 exact hash 与 fresh-process closure，但仍违反研究目标。v1 必须把结论拆成：

- `operational_state_closure`：运行时只有 sealed payload 能跨调用生存；可由进程隔离硬证。
- `semantic_unity`：payload 不是三套任务状态的机械拼接；需要 source/计算图与反例证据。

`semantic_unity=PASS` 至少要求：

1. patient-dependent computation graph 只有一个 state producer/root，`initialize/update` 不接收 task；
2. natural/treatment 共用同一 controlled `rollout(Z, plan)` 和同一 transition core；
3. 无 task-exclusive persistent store、checkpoint slot 或独立 update path；
4. state component/byte-tile occlusion 生成 head-dependency matrix；若恰好呈 diagnosis-only、natural-only、treatment-only 三个互不相交 block，触发 `SUSPECT_MULTIPLEXED_TASK_STATE` 人工/源码审计；
5. 同一 informative update 对三个任务的改变能由同一 state change 解释；
6. 冻结 state 后的新任务 head 只读 state 仍可学习，且不重新接触 history；
7. collision、false split、history deletion 和 state-size evidence 不支持隐藏完整历史/任务拼接。

不能审计的 opaque blob 最多标 `operationally_closed_shared_state`；其 `semantic_unity` 必须是 `INCOMPLETE`，不得作为“已证明找到 UCM”的最终证据。这里应诚实承认：有限黑箱 I/O 测试无法数学证明内部没有三块 latent。

## 5. 统一指标：定义、分母和不可合并边界

所有指标至少按 `candidate × model_seed × world × episode × cut × horizon × policy` 保存 raw row，再汇总。不能只报总体平均。独立采样单位是 episode/world seed，不是同一 episode 内的多个 query row；置信区间须按独立单位 cluster bootstrap。

### 5.1 诊断与校准

- primary proper scores：multiclass/multilabel NLL、Brier score。
- descriptive：top-1、top-k、macro recall；不单独据此选 winner。
- calibration：15-bin equal-mass ECE、classwise ECE、reliability bins；概率区间用 50/80/95% empirical coverage。
- 概率只为数值计算 clip 到 `[1e-12, 1-1e-12]`，raw output 仍保存；输出非法概率直接合规失败。
- `unknown` 是显式类别/质量，不能事后从低置信猜测。

### 5.2 自然病程预测

分别报告 `NoNewAction` 和 `ContinueCurrent`，不得混成一项：

- 连续单变量：CRPS（primary）、oracle scale 标准化 MAE/RMSE、interval coverage。
- 离散观察/事件：NLL、Brier。
- 多变量轨迹：energy score 或 world 冻结的 joint proper score；另报每轴误差，避免平均掩盖关键轴。
- 结局：survival/event probability 的 integrated Brier/NLL；固定时点 utility distribution error。
- 每个 horizon（例如 1h/24h/7d）独立报告，不允许先平均 horizon。

### 5.3 干预预测

对每个允许 policy/action sequence：

- 与自然预测相同的 trajectory proper score；
- treatment-effect error：候选与 oracle 的 outcome/utility contrast 误差；
- effect-sign error；
- 若 oracle 有 unit-level paired counterfactual，报告 PEHE/ITE error；否则只报 distributional effect，禁止伪称 individual effect。
- worst-policy、worst-world、worst-episode 必须保留。

### 5.4 治疗后悔

judge 用冻结 utility `U_w` 和候选预测选择：

```text
a_oracle = argmax_a E_oracle[U_w | do(a), H_t]
a_hat    = argmax_a E_candidate[U_w | do(a), Z_t]
regret   = E_oracle[U_w | do(a_oracle)] - E_oracle[U_w | do(a_hat)]
```

同时报告：

- raw regret（保留临床 utility 单位）；
- normalized regret = `regret / (max_a V_oracle(a)-min_a V_oracle(a))`，分母为 0 时记 N/A；
- mean、median、p95、max、CVaR95；
- catastrophic-action rate（由每个 world 预注册 utility margin 决定）；
- W19 rare contraindication 单列，不能被总体平均稀释。

tie-break 必须由 benchmark 固定，候选不得自定。危险方向反转且超过预注册 margin 是硬碰撞证据。

### 5.5 collision 与 false split

不同表示没有自然统一的 latent 距离，因此 v1 采用冻结 probe set `Q_w` 的**行为距离**。对同一 cut 的两个历史 `h_i,h_j`：

```text
D_oracle(i,j) = max over q in Q_w of world_normalized_distance(
                    P_oracle(. | h_i, q), P_oracle(. | h_j, q))

D_candidate(i,j) = max over q in Q_w of same_distance(
                    P_hat(. | Z_i, q), P_hat(. | Z_j, q))
```

`Q_w` 必须覆盖允许的等待、未来检查、no-op、continue 和所有冻结 treatment/action sequence。`world_normalized_distance` 由 world oracle 预注册：有限分布优先 TV；连续轨迹用按 oracle scale 归一的 Wasserstein/energy distance；utility contrast 归一到 `[0,1]`。不能由候选选择。

冻结三个 margin：

- `epsilon_equivalent_w`：oracle 数值误差内可视为行为相同；
- `delta_distinguishable_w`：临床/决策上确定可区分；
- `epsilon_candidate_same`：候选实际没有可用区分的容差。

定义：

- exact collision：`state_hash_i == state_hash_j` 且 `D_oracle >= delta_distinguishable`。
- functional near-collision：`D_candidate <= epsilon_candidate_same` 且 `D_oracle >= delta_distinguishable`。
- dangerous collision：上述任一成立，且 oracle optimal-action sets 不相交、effect sign 相反或 oracle regret 超过 catastrophic margin。
- functional false split：`D_oracle <= epsilon_equivalent` 且 `D_candidate >= delta_distinguishable`。
- structural redundancy：oracle 等价但 canonical state hash/bytes 不同；作为简洁性诊断，不单独硬失败。exact hash 不同不能自动等于“明显拆分”。

报告分母：collision rate 的分母是所有 oracle-distinguishable frozen pairs；false-split rate 的分母是所有 oracle-equivalent pairs。还要报告 max missed oracle distance、max spurious candidate distance 和所有 pair IDs/轨迹。任一 exact dangerous collision 为硬失败；普通 near-collision 不能只报率，必须看 worst case。

### 5.6 OOD/open-world

候选只用 validation 选择 OOD threshold，并在 model seal 中记录；test 后不得调阈值。报告：

- AUROC、AUPRC（OOD 为 positive）；
- FPR@95TPR、TPR@固定低 FPR；
- selective risk-coverage curve/AURC；
- known-case coverage 与 OOD abstention；
- `unknown_probability` Brier/NLL 与 calibration；
- OOD 上的 treatment regret/unsafe non-abstain rate。

W18 designated unseen mechanism 若 `max known probability >= 0.90`、`unknown_probability <= 0.10` 且给出非 abstain 治疗，建议作为 v1 高置信强配硬失败；具体阈值必须在看候选 test 结果前写进 freeze margins。

### 5.7 时间泄漏

冻结 paired-prefix fixtures：future A/B、actual outcome A/B、late result A/B 在 cut 前 public bytes 完全相同。记录：

- `state_leak_rate = nonidentical_state_hash_pairs / identical_prefix_pairs`；
- `prediction_leak_rate` 与 max pre-availability output divergence；
- boundary error count；
- old-cut instability count。

同模型、同 inference seed、同 prefix 时容忍度为 exact bytes/hash；任何差异都是硬失败。若候选只输出采样而非显式分布，必须用 common random numbers 并同时保存样本，但 v1 应优先要求显式 distribution。

### 5.8 sample efficiency、组合泛化与稳定性

- 固定 train fractions：`1%, 5%, 10%, 25%, 50%, 100%`（每层至少有预注册最小 episode 数）。
- 对诊断/自然/干预 proper score 分别画 learning curve，报告 log-sample 轴 AUC；不得只用最好 checkpoint。
- 新机制组合/新宿主修饰/非线性共病单独报告 held-out gap。
- 完整候选至少 5 model seeds；报告 mean、SD、min/max、paired 95% CI。环境 seed 与 model seed 分开保存。

### 5.9 更新一致性

至少四项：

- exact incremental-vs-replay hash match rate；
- batch-vs-sequential behavioral match；
- query-order purity；
- informative new observation/treatment response 后，各 head 相对于 oracle 的 posterior/forecast/effect score change。

最后一项不要求“每次都变好”，而是与 oracle 信息方向比较；无信息 observation 不应被强迫改变 state。

### 5.10 新检查、新治疗、新任务和历史删除

冻结候选后运行：

- 新检查：新增 observation operator 后，原 collision pair 能否局部拆开；记录模型/状态 schema migration、retrain examples、artifact delta bytes、core diff LOC、旧 benchmark 回归。
- 新治疗：新增 action 后，旧等价类是否被检测为不再充分；若必须完全重写核心，记录 hard extensibility failure。
- 新任务 readout：冻结 state encoder/updater/dynamics，仅允许用 train split 的 `(state,new_label)` 训练新 head；禁止 raw history。报告 score、样本效率和 history baseline gap。
- 历史删除：删除冻结片段，比较 state/prediction/oracle 行为；发现真正需要的记忆与无效记忆。
- 时间尺度：1h/24h/7d 分开测 state bytes、误差和 collision，检查 state 是否随 horizon/task 膨胀。

### 5.11 简洁性与计算成本

分别保存而不做单一“复杂度分”：

- canonical state raw bytes、scalar/node/edge/particle 数；
- canonical bytes 经同一压缩器后的 bytes（仅作辅助，不能隐藏 raw）；
- state size 对 history length 的 slope；
- model artifact bytes 与 train FLOPs/time；
- initialize/update/各 head 的 cold p50/p95/p99 latency；
- peak RSS/GPU memory；
- extension core diff LOC、changed files、schema migration count。

full-history baseline 预期有线性 state-size slope；允许作为无压缩上界，但不得进入“紧凑 UCM”候选声明。

## 6. 硬淘汰与 Pareto 输出

### 6.1 不可补偿的 run-level 硬失败

- C01–C33 中标 HARD 的违规或必需语义审计为 INCOMPLETE；
- true-state/oracle/future/test-id 泄漏；
- head 读取原史或治疗 query 重建第二表示；
- exact dangerous collision；
- observation conditioning 当成 intervention；
- OOD 高置信强配并产生预注册 unsafe action；
- raw results/seed/seal 不全导致不可重放；
- benchmark/candidate 在 hidden reveal 后静默改动；
- full-history 伪装为 compressed state。

失败 run 仍必须保存全部 raw evidence，只是 `eligibility=INELIGIBLE`。不要删除“难看”的结果。

### 6.2 通过硬门槛后的 Pareto 轴

独立展示：diagnosis proper score、natural forecast、intervention forecast、regret tail、calibration、OOD、sample efficiency、collision、false split、state size/slope、extension cost、latency/memory、new-readout transfer。禁止用一个可调权重总分掩盖失败。

与 separate-task baseline 比较时，separate baseline 明确标 `shared_state_compliant=false`，只作性能上界/反证。共享候选若三任务任一出现预注册不可接受退化且没有样本效率、一致性、组合泛化、紧凑性或迁移优势，应报告被支配，而不是靠“共享”名义获胜。

### 6.3 四类规定 baseline 的 waiver 不能污染候选门

- `TrueStateUpperBound`：`eligibility=upper_bound_only`，允许 simulator truth，仅验证 oracle/metric 上界。
- `SeparateTaskBaseline`：`eligibility=baseline_only`，预期违反 single-state，提供性能比较。
- `FullHistoryBaseline`：`eligibility=baseline_only`，允许无压缩历史，提供信息上界/压缩代价比较。
- `K0OnlyBaseline`：`eligibility=negative_control`，证明控制面不是患者地图。

报告里要显示“预期 waiver/failure”，不能因为它们有显式豁免就显示成普通 UCM 合规 PASS；waiver 也不得被其他候选继承。

## 7. raw result schema 与不可覆盖目录

建议每个 run 使用：

```text
results/unified_map/<run_id>/
  RUN_MANIFEST.json
  candidate/source-manifest.json
  candidate/model-manifest.json
  candidate/model-artifact.sha256
  inputs/public-input-digests.jsonl
  raw/states.jsonl
  raw/updates.jsonl
  raw/predictions.jsonl
  raw/oracle-judge.jsonl
  raw/process-audit.jsonl
  raw/resources.jsonl
  metrics/per-query.jsonl
  metrics/per-episode.jsonl
  metrics/per-world.jsonl
  metrics/aggregate.json
  failures/compliance.json
  failures/collisions.jsonl
  failures/false-splits.jsonl
  failures/worst-trajectories.jsonl
  logs/stdout.log
  logs/stderr.log
  checksums.sha256
  FINALIZED.json
```

`run_id` 推荐：

```text
YYYYMMDDTHHMMSSZ-<candidate>-<config8>-<nonce8>
```

目录必须以 exclusive create 建立，已存在就 abort。先写临时目录，finalize 时生成排序 checksum manifest 和 `FINALIZED.json`，再原子 rename；finalized 后只读。任何修正创建新 run，并用 `supersedes_run_id` 关联，绝不覆盖旧 raw。

### 7.1 `RUN_MANIFEST.json`

```json
{
  "schema_version": "ucm-run-manifest/1",
  "run_id": "...",
  "run_class": "development|sealed_validation|sealed_test|post_test_tuned|redteam|reproduction",
  "status": "running|finalized|crashed|ineligible",
  "benchmark_id": "UCM-BENCHMARK-v1",
  "benchmark_freeze_digest": "sha256:...",
  "hidden_corpus_digest": "sha256:...",
  "candidate_id": "...",
  "candidate_source_seal": "sha256:...",
  "model_artifact_digest": "sha256:...",
  "git_commit": "...",
  "git_dirty": false,
  "model_seed": 0,
  "environment_seed_set_digest": "sha256:...",
  "train_data_digest": "sha256:...",
  "validation_data_digest": "sha256:...",
  "runtime": {"python": "...", "os": "...", "container": "...", "dependency_lock": "sha256:..."},
  "isolation_assurance": "python_audit|os_sandbox|container",
  "started_at": "...",
  "finished_at": "...",
  "supersedes_run_id": null
}
```

### 7.2 raw prediction row

至少包含：

```json
{
  "schema_version": "ucm-raw-prediction/1",
  "record_id": "opaque",
  "split": "train|validation|test|redteam",
  "world_alias": "opaque-to-candidate",
  "episode_alias": "runner-only",
  "cut_alias": "runner-only",
  "model_seed": 0,
  "environment_seed": 0,
  "state_hash": "sha256:...",
  "public_input_digest": "sha256:...",
  "query_digest": "sha256:...",
  "prediction_kind": "...",
  "policy_alias": "...",
  "horizon": "...",
  "candidate_output": {},
  "latency_ns": 0,
  "peak_rss_bytes": 0,
  "worker_exit": 0
}
```

oracle judge row 以 `record_id` 联结，但存于 parent-only 文件；候选 transcript 绝不含 oracle truth。`states.jsonl` 保存 exact canonical state bytes/base64 或 JSON 及 runner hash，以便事后验证同一状态。

### 7.3 aggregate 的最低字段

- 每个 world/task/horizon/policy/seed 的 point estimate 与 cluster-bootstrap CI；
- coverage/unsupported/invalid/crash count；
- hard compliance vector，不是一个布尔值；
- collision/false split pair denominator、count、rate、worst pair；
- regret distribution 尤其 p95/max/CVaR/W19；
- OOD risk-coverage；
- state/runtime/resource statistics；
- mutation-kill matrix digest；
- raw record count 与 checksum，证明 aggregate 可追溯。

## 8. benchmark v1 冻结机制

### 8.1 freeze 的内容

`FREEZE_MANIFEST.json` 必须逐文件记录 exact bytes SHA-256，并覆盖：

1. W01–W20 semantic spec 和版本；
2. train/validation/test generators；
3. independent oracle/reference enumerators；
4. observation/action/utility/time schema；
5. public/private projection；
6. split protocol、seed draw/commit/reveal protocol；
7. probe pair/query sets 与 collision margins；
8. metrics、calibration bins、bootstrap unit/count；
9. hard-gate spec 与 mutation candidates；
10. runner/judge/result JSON schemas；
11. dependency locks/container image digest；
12. known harness limitations。

canonical freeze manifest 自身使用 UTF-8 sorted compact JSON + LF；独立 `.sha256` sidecar，避免 self-hash。建议同时生成可读 `FREEZE_REPORT.md`，但 JSON/bytes 为权威。

### 8.2 两阶段 seed commit/reveal

为同时满足“先冻结 benchmark”与“不能按 hidden case 调候选”：

1. **semantic freeze**：冻结 generator/oracle/metric/gate/seed-draw algorithm；生成 `benchmark_freeze_digest`。
2. **candidate seal**：对进入共同 hidden test 的 finalist，记录 source tree、model artifact、dependency lock、config 和训练数据 digest。
3. **fresh common seed**：所有 finalist seal 后，抽同一个 256-bit seed；先记录 commitment `SHA256(seed || nonce)` 和 timestamp。
4. **generate once**：用冻结 generator 生成共同 W01–W20 hidden corpus、opaque aliases/顺序和 paired probes；记录 exact digest。
5. **isolated execution**：候选只见 public projection；judge 持有 hidden oracle。
6. **reveal**：执行完成后公布 seed/nonce/generator digest，使任何人可重建 exact corpus。

同一比较中的候选必须跑同一个 hidden corpus。hidden reveal 后修改候选会创建 `run_class=post_test_tuned`，不能替代 primary sealed result。独立复现应使用独立实现 seal，并最好抽第二个 fresh common seed。

开发期 30 个实验使用 train/validation 或已标明的 public mini benchmark；不能反复查看 primary hidden test。至少 3 个完整候选的 primary W01–W20 对比应在 seal 后共同运行。

### 8.3 冻结前 benchmark 自证

freeze 只有在以下自动测试通过后有效：

- W01–W20 各有 true hidden mechanisms、transition、observation、tests、treatments、all-action counterfactual、diagnostic truth、utility、train/val/test generator；
- generator 同 seed byte-reproducible，不同 split 无重复/近重复泄漏；
- oracle 概率归一、有限 world 可独立枚举，随机 oracle 有预注册 Monte Carlo error bound；
- no-op/continue/stop/do、planned/performed、event/available time 的关系测试通过；
- candidate public projection 不含 oracle/true state/future/test ID；
- C01–C33 与 mutation kill matrix 通过；
- result raw -> aggregate 可重建；
- exact manifest/sidecar/replay 在 clean checkout 通过。

若 semantics 已冻结但某隐藏 case 不可执行或 mutation 未被杀，结论必须拆开：候选假说是否失败与 harness 是否完整是两条证据链，不能用绿色 checksum 把 `HARNESS_INCOMPLETE` 说成候选通过。

### 8.4 修改规则

- 拼写/说明变更若不影响 bytes/semantics，也创建新 documentation commit，但不替换旧 freeze manifest。
- runner bugfix：保留 v1 原结果，创建 `v1.0.1` 与 migration note，并在旧/新 runner 都重放；不得静默回写。
- generator/oracle/metric/margin/utility/pair set 的语义变化：创建 benchmark v2。
- frozen 后新增反例属于 `redteam-v1-rN`，不得回灌 v1 primary score；单独 report，并决定是否证伪候选或促成 v2。
- 所有 raw results 保留，即使候选崩溃、作弊或 benchmark 后来发现问题。

## 9. 建议的最小实现顺序

1. 先实现 wire schemas、canonicalization、runner-computed hash 和 result writer；此时不实现真实候选。
2. 写 `PerfectTrueStateUpperBound`（明确不合规，仅校验 oracle/metric上界）、`FullHistoryBaseline`、`SeparateTaskBaseline` 和 `K0OnlyBaseline`。
3. 写 12 个作弊 mutants，先让 C01–C33 真正把它们杀死。
4. 对 W01/W02/W04/W08/W15/W18/W19/W20 建 vertical slice：初始化→同 state 多 head→A/B/no-op→真实 action/response update→new state。
5. 扩到 W01–W20，冻结 probe pair/query set、utility 和 margins。
6. 跑 clean-checkout replay、manifest/checksum、raw-to-aggregate rebuild；只有此后才生成 benchmark v1 freeze。
7. 候选开发只能消费 public train/validation API；共同 hidden test 在 finalist seal 后一次运行。

## 10. 合并到正式合同前必须明确的少量参数

这些不能在看到候选 test 结果后再定：

- 每个 world 的 `epsilon_equivalent`、`delta_distinguishable`、catastrophic regret margin；
- 连续轨迹的 oracle scale 与距离函数；
- W18 高置信强配阈值（草案建议 known≥0.90、unknown≤0.10）；
- train fraction 对应的绝对 episode 数；
- 每 world/split/seed 的 episode 数和 bootstrap 次数（建议 10,000）；
- horizon 集合与 allowed action-sequence 长度；
- late event/batch 的 canonical ordering；
- native/neural 候选所需的 OS isolation assurance 是否为 primary result 的硬要求；
- 新检查/新治疗允许的 retrain 与 schema migration budget；
- shared candidate 相对 separate-task baseline 的“不可接受退化”逐任务 margin。

这些值应由 world oracle 的数值误差、生成器保证的 effect gap、固定 utility 和预期资源预算导出并写入 freeze，而不是从候选排名反推。

## 11. v1 合规判定的推荐输出格式

不要输出一句 `PASS`。输出 evidence vector：

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
  "ood_gate": "PASS|FAIL|INCOMPLETE",
  "reproducibility": "PASS|FAIL|INCOMPLETE",
  "eligible_for_pareto": false,
  "decisive_evidence_records": []
}
```

`INCOMPLETE` 表示 harness/证据不足，不等于候选通过。只有所有 hard axes 为 PASS 才进入 UCM Pareto；一个 FAIL 即 ineligible。可保留 `semantic_unity=INCOMPLETE` 的 opaque 候选作为探索性比较，但不能把它当已证明的统一地图赢家。最终 demo 的每个诊断/自然/A/B/C/更新输出必须由 runner 把 `consumed_state_hash`/`prior_state_hash`/`new_state_hash` 连成可核链。

---

### 本草案的核心判断

接口统一本身没有价值；**值传递的唯一 canonical state + 物理隔离的 heads + hidden oracle judge + 行为碰撞 probe + append-only raw evidence** 才能把“一张地图”变成可运行、可攻击、可推翻的主张。若某候选必须在 readout 时重新接触历史、依赖任务缓存，或在新治疗加入后才能发现旧 `Z_t` 丢失关键差异，则应直接报告该共享状态在相应范围内不充分，而不是用新的 head/state 包装继续宣称统一。
