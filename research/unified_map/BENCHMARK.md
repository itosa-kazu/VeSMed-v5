# Unified Clinical Map benchmark v1 规范

> **状态：PRE-FREEZE / 规范文本已建立，benchmark v1 尚未冻结。**
> 只有当本文要求的 W01–W20 实现、oracle、split manifest、全部 margin、mutation-kill matrix、`FREEZE_MANIFEST.json` 和 clean-checkout replay 均存在且通过时，才能将状态改为 `FROZEN-v1`。本文不得被单独引用为“benchmark 已冻结”的证据。
> **范围：**只定义 UCM 患者世界模型的可运行比较合同；K0 只能贡献隔离、时间切片、digest 和证据记录基础设施，不是 UCM 候选。
> **规范词：**`MUST / MUST NOT / SHOULD / MAY` 分别表示硬要求、硬禁止、默认要求和可选实现。
> **唯一目标：**让“同一个 `Z_t`”成为运行时可证伪事实，而不是类名、接口名或宣言。

## 0. 权威边界与结论等级

本文是 benchmark 横向合同的规范人读版。冻结后的权威性按以下顺序判定：

1. 一次具体 run 中 judge 的实际执行记录和 raw bytes；
2. `FREEZE_MANIFEST.json` 所引用文件的 exact digest；
3. 已冻结 schema、generator、oracle、metric 与 gate 实现；
4. 本文与 `MICROWORLDS.md` 的人读语义；
5. 说明性评论、候选 manifest 和报告摘要。

如实现与本文冲突，benchmark 不得靠“实现已经这样”自动改写规范；必须先判定是 runner bug、spec bug 还是语义变更，并按第 10 节升版。

本轨所有规范、实现、测试和结果 MUST 分别局限于 `research/unified_map/`、`prototype/unified_map/`、`tests/unified_map/`、`results/unified_map/`。任何复用的 K0 基础设施都必须通过冻结 allow-list/digest 指明，且只能负责隔离、时间投影、canonicalization、runner 和证据记录；K0 state、K0 决策逻辑和旧结论不得进入候选患者状态或 oracle。

结论必须分开报告：

- `CANDIDATE_FAIL`：证据足以证伪该候选；
- `CANDIDATE_PASS_ON_FROZEN_SCOPE`：仅表示在已冻结 W01–W20 和已允许 query 范围内通过；
- `HARNESS_INCOMPLETE`：生成器、oracle、mutation 或证据链不足，不得解读为候选通过；
- `OUT_OF_FROZEN_SCOPE`：新检查、新治疗、新任务或 red-team 超出 v1 范围，必须单列证据。

## 1. v1 必须冻结的不变量

1. **唯一患者状态是可序列化值，不是进程对象。** 每次更新产生一个 canonical `StateEnvelope`；runner 而非候选计算 `state_hash`。
2. **状态推断/更新和各 readout 分进程执行。** readout 进程只得到：只读模型制品、同一份 state bytes、非患者特异的 query；它拿不到原始历史、simulator、oracle、其他患者或上一次调用内存。自然病程和 A/B/C 治疗不得各有入口，必须走同一个 `rollout(Z_t, plan)`。
3. **允许不同 head 和 head 参数，但不允许第二份患者状态。** head 内从 `Z_t` 临时计算的 scratch 可以存在，但不能持久化、跨调用、回写模型或成为另一份按任务更新的 latent。
4. **no-op、继续当前治疗、停止治疗和 `do(action)` 必须是四种可区分语义。** 反事实查询是纯函数，不修改 factual state。
5. **碰撞/虚假拆分的主度量用冻结 probe 集合上的行为距离，不用候选自报的 latent 欧氏距离。** 这样 vector、graph、belief、program state 才可公平比较。
6. **未来泄漏、true-state/oracle/test-id 访问、head 读取历史、隐藏缓存、同一 cut 多任务实际消费的 state hash 不同、危险治疗碰撞均为不可被平均分补偿的硬失败。**
7. **结果永不覆盖。** 每个 run 独占目录，保留 raw state、raw prediction、oracle judge record、进程审计、失败轨迹和 checksum；aggregate 必须可从 raw 重建。
8. **freeze 分两层。** benchmark 的语义、生成器、oracle、指标和测试种子抽取协议先冻结；同一批 finalist 源码/模型 seal 后才抽取并揭示共同 hidden test seed。冻结前开发不得看到 hidden case/oracle。

## 2. “一个共享状态”的可执行定义

### 2.1 模型制品不等于患者状态

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

### 2.2 canonical state 与 hash

状态传输对象必须是 **closed JSON envelope + 明确 inert codec 的 opaque payload bytes**，而不是强制所有候选的 state 本体都用 JSON 表示。v1 允许且 runner 实际验证的 codec 只有 `canonical-json-v1` 和 `raw-f64le-v1`；每个 codec 的精确 canonicalization/schema 由 freeze manifest 引用。严禁 pickle、MessagePack extension/object hook、callback、文件/网络/进程句柄、可执行代码、任意对象引用和候选自定义解码器。有限数值、数组、稀疏图、分布参数、粒子集、typed AST、机制网络或它们的组合都可经上述 inert codec 序列化；若未来加入其他 inert codec，必须升级 protocol/benchmark 版本并先实现 bytes-level 验证，不能只信候选提供的 codec 标签。

规范 state wire schema：

```json
{
  "protocol": "ucm-state/1",
  "candidate_id": "candidate-name",
  "model_digest": "sha256:...",
  "scope_digest": "sha256:...",
  "catalog_digest": "sha256:...",
  "state_schema_version": "1",
  "cut": {
    "event_time": "...",
    "available_time": "..."
  },
  "codec": {
    "name": "canonical-json-v1|raw-f64le-v1",
    "schema_digest": "sha256:...",
    "dtype": "<f8 or null",
    "shape": [0]
  },
  "payload_b64": "base64 of exact inert payload bytes",
  "declared_state_class": "compressed_shared_state"
}
```

`canonical-json-v1` payload 只允许 closed schema 的 null/bool/string/finite-number/list/map，key 排序、数字和 UTF-8 规则随 freeze 固定。`raw-f64le-v1` 必须显式绑定 little-endian float64、shape 和轴 schema，禁止 NaN/Inf。runner 负责 base64 解包、按精确 codec 名执行 bytes-level schema/canonicalization 校验并计算 hash，候选不得提供会执行的 decoder；未注册 codec 一律拒绝。

`declared_state_class` 只能是：

- `compressed_shared_state`；
- `dynamic_shared_state`；
- `full_history_baseline`。

其中 full-history baseline 可以把历史序列化为 payload，但必须明确标成 baseline，不能声称紧凑；其 state bytes/history-length slope 必须照常计量。其他候选禁止保留 raw event record、无关 provenance/canary、整段 raw payload 历史或它们的可逆压缩/加密封装。**这不禁止充分统计或当前可观状态在数值上等于某条观察**；判定要结合可恢复性、history-length slope、UID/provenance canary 和行为等价测试，不得用字节子串扫描单独淘汰合法状态。

envelope canonicalization 必须固定为 UTF-8 JSON、key 排序、compact separators、禁止 NaN/Inf、数值格式固定、末尾 LF。`state_hash` 由 runner 对解码后的 exact payload bytes 及其语义域计算：

```text
state_hash = "sha256:" + SHA256(
    "UCM_STATE_V1\0"
    || candidate_bundle_digest
    || scope_digest
    || catalog_digest
    || canonical(cut)
    || canonical(codec_descriptor)
    || raw_payload_bytes
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
  "scope_digest": "sha256:...",
  "catalog_digest": "sha256:...",
  "as_of": "...",
  "payload_size_bytes": 0,
  "envelope_size_bytes": 0
}
```

状态内不得出现 episode/case/test/world/split ID、预期疾病、真实机制、未来值或 oracle 字段。runner 的 episode handle 放在外层调度记录中，不进入 state bytes/hash。

同一输入、同一冻结模型和同一 inference seed 必须得到 byte-identical state。若内部使用粒子或随机采样，粒子及 RNG continuation 必须作为 `Z_t` payload 的显式部分，不能留在进程 cache。
### 2.3 state hash 的含义和限制

- 所有 head 对同一 cut 的输出由 runner 附加同一 `consumed_state_hash`；该值来自实际传入 bytes，不能信候选自报。
- query 不得修改 state；查询前后 state bytes 与模型制品 digest 必须相同。
- informative update 通常产生新 hash；重复 event 或行为上真正无信息的 event 可以保持原 hash。不要为了 demo 强制伪造变化。
- hash 不证明 state 足够，也不证明紧凑；它只证明所有 readout 消费了同一份 exact bytes。充分性由 collision/regret/OOD/新读出测试证明。

## 3. W01–W20、public/private dataset 与 split 合同

### 3.1 固定 world panel 与完整 oracle 责任

W01–W20 是二十个**固定的判别世界**，不是从“所有临床世界”随机抽取的样本。跨 world 结果默认使用 world-macro，不得因某个简单世界 episode 更多而稀释 W19 等稀有危险世界。`MICROWORLDS.md` 定义每个 world 的详细方程、参数域和 oracle；本文冻结其横向义务：

| World | 必须隔离的行为差异 | 主 probe / 不可被总平均掩盖的结果 |
|---|---|---|
| W01 | 完全可观的简单线性生理系统 | 最基本 initialize→diagnose/rollout→update 链路；上界候选若不能近 oracle，harness 必须失败 |
| W02 | 部分可观，多个观察约束隐状态 | posterior 分布、诊断校准、递归更新；不得仅保留 posterior mean |
| W03 | 当前表型相同，自然动力学不同 | natural-history collision 与多 horizon 预测 |
| W04 | 自然未来相同，治疗反应不同/反向 | dangerous treatment collision、effect-sign error、regret |
| W05 | 治疗先改内部状态，观察延迟 | 无即时观察时的 action update 与 delayed effect |
| W06 | 治疗只改观察通道 | observation improvement 不得被当成 mechanism cure |
| W07 | 治疗同时改变内部状态与观察通道 | 两条 effect path 的 joint forecast，禁止二选一简化 |
| W08 | occurred/collected/available 异步与不规则观察 | availability-time 防泄漏、late update、schedule invariance |
| W09 | 个体 baseline 不同 | 相同绝对值需产生不同 posterior/future，且 baseline 不得作 head-private context |
| W10 | 多观察共源于同一机制 | 重复表型不得造成虚假确定性；joint calibration |
| W11 | 不同机制产生相同观察 | 多模态 posterior、未来检查/治疗可区分性 |
| W12 | 同一机制在不同宿主中表现不同 | held-out host modifier 组合、校准与干预效应 |
| W13 | 非线性共病：协同、拮抗、阈值 | 组合 holdout；加法状态不得通过平均误差掩盖交互失败 |
| W14 | 路径依赖与滞后，当前观察相同 | history-dependent collision、长 horizon、历史删除 probe |
| W15 | 隐藏混杂：观察治疗选择与干预效果反向 | `condition != do`；无识别证据时必须表达 partial/non-identifiability，有冻结随机化/支持证据的子场景中错误治疗方向为硬失败 |
| W16 | 新检查拆分旧行为等价类 | 冻结 state 后的 local refinement、schema/model/data 扩展成本 |
| W17 | 新治疗拆分旧行为等价类 | 能否检测旧 `Z` 不充分；反向反应与扩维/重训成本 |
| W18 | train/validation 中未出现的新机制 | 在已有 public evidence 可与 known support 区分的 cut 测 OOD/unknown calibration、selective risk、unsafe forced-known；不惩罚信息论上完全不可区分的 prefix |
| W19 | 稀有但严重的治疗禁忌 | 冻结 tail cohort 上的 conditional max/CVaR regret 和 catastrophic-action 硬门；不得被 prevalence/mean 稀释 |
| W20 | 反馈环与既往治疗暴露依赖 | 同现值但不同 action history 的下一步反应、online update |

每个 world 的冻结制品 MUST 同时提供：

1. 真实隐状态/机制和转移核；
2. observation/check 生成核及三种时间；
3. 允许的检查、治疗、policy sequence 和 horizon；
4. 诊断/机制真值、各 policy 的 distributional future、outcome 与 utility；
5. train、validation、frozen-test 生成器及无交叉证据；
6. 用于 collision/false-split 的 grouped pair 和行为 probe set；
7. 数值 oracle 的独立检查或 Monte Carlo error bound；
8. world-specific normalization scale、equivalence/distinguishability/catastrophic margin 和 exact query-cell manifest；
9. 每个 probe/cut 的 `candidate_information_relation`、`identifiability=point|partial|none` 及 `attributable_collision` 判定。

任一 world 缺少上述任一项，不得以“其他 world 可运行”冻结 v1。

### 3.2 `SCOPE_MANIFEST.json`：所有充分性声明的闭包

UCM 不存在脱离范围的“绝对充分”。v1 MUST 将完整范围

```text
S = (P, O, A, Q, Pi, Tau, Gamma, Y, U, D, R)
```

冻结为 closed-schema `SCOPE_MANIFEST.json`：`P` 是人群/宿主/机制 support，`O` 是观察与缺失/可用过程，`A` 是生理/治疗 action，`Q` 是检查，`Pi` 是有限开环/自适应 policy 集，`Tau` 是 horizons，`Gamma` 是行为相关诊断粒度，`Y` 是必须保留的未来观察/事件/结局闭包，`U` 是 utilities，`D` 是距离/指标，`R` 是数据、资源、隔离和识别假设。

```text
scope_digest = SHA256(
  "UCM_SCOPE_V1\0" || canonical_json(SCOPE_MANIFEST.json)
)
```

`scope_digest` MUST 进入 StateEnvelope 及 state hash domain、CandidateManifest、run manifest、每条 raw prediction/update/state row、`expected-cells.json`、world/split manifest 和最终结论。catalog digest 只是 `O/A/Q` 的部分快照，不能替代 scope digest。

任何新检查、新治疗、更长 horizon、新人群或新 readout 都要先生成 `S'` 和新 digest。novel-readout 卡 MUST 声明 `in_original_Y=true|false` 并引用证明路径：如果在原 `Y` 闭包内却必须重读 history，才证伪原状态范围内充分性；如果原本在范围外，失败只能说明需要 refinement/migration/retraining 或 `scope_insufficient`。

### 3.3 数据层级与可见性

`public/private` 描述的是**参与者在该阶段能不能看到 exact 样本与 oracle**，不是文件名是否带 `private`。权限矩阵如下：

| 层 | 候选开发者可见 | 训练/调参用途 | 永不进 candidate worker 的内容 |
|---|---|---|---|
| `PUBLIC-SPEC-v1` | 本文、`MICROWORLDS.md`、闭合的 event/action/query schema、单位、合法值域、训练数据预算、定性 world 语义 | 所有候选的共同合同 | private seed、test episode、oracle state/future、pair membership、expected answer |
| `PUBLIC-TRAIN-v1` | public event histories、performed actions、已发生 outcomes、规范允许的训练 target；可在冻结 budget 内调用 train generator | fit 和固定消融 | simulator 的 hidden Markov state、未实施 action 的 unit-level counterfactual，除非某条训练轨明确预注册允许 |
| `PUBLIC-VALIDATION-v1` | candidate-view histories/query；judge 可返回预注册的 aggregate/per-world score | model selection、early stopping、OOD threshold、资源选择 | raw hidden state、future random numbers、all-action oracle trajectories、pair type；禁止用 validation 当额外训练数据而不登记 |
| `SEALED-TEST-v1` | 所有 finalist 封印后，运行时仅可见每个 cut 的 public projection 与 typed query | 一次性 confirmatory W01–W20 比较；不得调参 | hidden seed/nonce、split/group ID、world/test/case ID、true state、actual future beyond cut、counterfactual oracle、utility truth、pair/probe label |
| `REDTEAM-v1-rN` | 只在 benchmark 和 candidate 都封印后投影 candidate view | 单独 red-team 证据，不回写 v1 score | 实例、nonce、反例参数与 oracle 在执行完成前都不可见 |

训练 target 能包含已观测的诊断标签、未来结局或 randomized-action outcome，但必须在 training schema 中显式登记，所有候选使用相同数据预算。“训练中有监督”不等于允许 candidate inference 访问 simulator truth。

训练数据 MUST 物理拆成 `candidate_inputs` 和 `trainer_targets`/`judge_oracle` 三个封闭 schema。`candidate_inputs` 是 encoder/updater 在对应 cut 可读的唯一字段集；target 可进入训练 loss，但不得被连接到该样本的 state encoder 输入、不得出现在 state bytes、也不得被包装成 context feature。给 trainer 的 target 访问必须在完整性日志中记录 target kind 和 budget。

**factual outcome 与 counterfactual oracle 必须分开：**已真实发生且 `available_at <= cut` 的 outcome 是合法历史；同一 factual trajectory 中在 cut 之后才发生/可用的 outcome 在该 cut 仍属于 private future。未实施 action 的 counterfactual trajectory、单位级别 exogenous draw 和 oracle utility 永不是 inference history；它们仅能由 judge 评分，或在预注册的 supervised-training track 中作 target。即使某个 factual arm 在 train 可见，它的反事实 sibling 也不得被偷放入同一 episode 的 encoder input。

`SEALED-TEST-v1` 完成并公布 seed 后，其 exact 数据可为可复现性公开，但它永久保持“对原封印候选是 blind”的证据地位。公布后修改的候选只能产生 `post_test_tuned` 结果。

#### Primary 与附加训练信息轨

用于选择 UCM 的 primary 轨是 `FACTUAL-TRAIN-v1`：候选可使用 public histories、已实施 actions、实际事后可见 outcomes、behavior-policy propensity，以及 trainer-only diagnostic/mechanism label；不提供 simulator continuous hidden state、future exogenous tape 或同一 episode 未实施 action 的 unit-level counterfactual。该 target 集、数量和调用预算对所有候选相同。

MAY 另跑 `CF-SUPERVISED-v1` 或 `STRUCTURE-INFORMED-v1`，用于分离“表示容量不足”与“从观察日志不可识别/难学”：前者可在冻结 budget 内获得 distributional all-action training target，后者可使用已公开 world equations/机制 schema。这些轨必须使用独立 candidate/run manifest 和 Pareto，不得与 `FACTUAL-TRAIN-v1` 混排或用附加 oracle 监督声称 primary 优势。手工结构、solver calls、pretraining 和 world-specific commitments 均记入 data/compute/domain-information 账本。

### 3.4 candidate-view projection

对任一 split，candidate worker 只能获得同一 closed-schema projection：

```text
VisibleEvent = {
  kind,
  occurred_at,
  collected_at,
  available_at,
  typed_payload,
  event_uid          # 仅用于幂等，必须对 alpha-renaming 不变
}
```

MUST NOT 出现：`world_id`、`Wxx`、`case_id`、`test_id`、`split`、`group_id`、`generator_seed`、`oracle`、`hidden_state`、`future`、`actual_future`、`reward_to_come`、`expected_answer`、pair/collision/OOD 标记。query 只能包含 non-patient-specific horizon、output schema、allowed policy 与公开 catalog token。

judge 内部的 `world_id/episode_id/cut_id/group_id` 必须使用不可猜的 runner alias 连接 raw row，alias 不进入 state/head request。文件系统、环境变量、错误文本、stdout/stderr 也不得间接泄露上述字段。

### 3.5 split 的最小单位：counterfactual family 原子分配

禁止对 query row、cut 或单条 trajectory 做随机 split。同一潜在患者生成家族的全部制品 MUST 原子分配到同一 split：

```text
CounterfactualFamily(w) =
  latent mechanism/host/initial-state draw
  + exogenous-noise skeleton
  + observation/acquisition schedule family
  + all factual-policy variants
  + all counterfactual action trajectories
  + all cuts and horizons
  + all paired-prefix / collision / false-split twins
```

parent judge 计算 `family_digest` 并用冻结 keyed derivation 分配 `train|validation|test`；候选永不看到 digest 或 split。同一 family 的 factual A 轨迹不得在 train、counterfactual B 轨迹在 test；早 cut 不得在 train、晚 cut 在 test；同一 paired-prefix 的一半不得跨 split。

原子分配不等于允许向候选公开整个 family。`FACTUAL-TRAIN-v1` 对每个 family MUST 只 materialize **一条**由冻结 behavior policy 抽取的 factual arm；其他 policy siblings、共用 exogenous tape、potential outcomes 和 pair linkage 保持 parent-only。公开 factual arm 的 UID/alias 必须与 private siblings 独立派生，不得因相同 prefix bytes、连续 episode index、noise fingerprint 或 family token 而可链接。

`CF-SUPERVISED-v1` 如被启用，只能通过 trainer-only target stream 提供冻结的 distributional counterfactual target；不得将 raw sibling histories 放入 encoder input，并必须有 unlinkability test 证明 target 不泄露 family/episode identity。该轨与 `FACTUAL-TRAIN-v1` 的结果分开排名，不得跨轨挑选赢家。

所有 split 必须通过：

- exact digest 无交叉；
- `family_digest` 无交叉；
- 连续轨迹的 prefix/suffix 相似搜索无跨 split 近重复；
- paired probe 不被拆开；
- hidden seed、episode alias 和生成顺序无重复；
- 参数 support/holdout 符合下一节的冻结 stratum manifest。

### 3.6 每个 world 必须报告的 split strata

每个 world 不只有一个模糊的“test set”；`WORLD_SPLIT_MANIFEST.json` MUST 预先列出下列可适用 strata 及精确 family/episode/query 数。不适用的 stratum 必须说明原因，不能默默少测。

| Stratum | 含义 | 最低覆盖 |
|---|---|---|
| `iid_support` | 同一冻结参数 support 上的新 family/noise/schedule | W01–W20 全部 |
| `boundary_tail` | 参数边界、低概率状态、稀有 action/outcome，但仍在公开 support | 所有有连续/稀有参数的 world；W19 必需 |
| `compositional_holdout` | 单组件在 train 出现，特定 mechanism×host、A×B 或 interaction 组合只在 test | W12、W13；可适用时 W10/W20 |
| `schedule_time_holdout` | 未见 sampling schedule、delay、cut/horizon 组合 | W08、W14、W20 |
| `policy_coverage_holdout` | 保留 action sequence，用于检查 off-policy/intervention 外推 | W04–W07、W15、W19、W20 |
| `extension_check` | base phase 不提供新 check；封印后揭示后它能拆分旧类 | W16 |
| `extension_treatment` | base phase 不提供新 action；封印后揭示后它能拆分旧类 | W17 |
| `mechanism_ood` | 该机制及其等价代理不得出现在 train/validation | W18 |
| `behavior_pair` | oracle-equivalent 或 oracle-distinguishable history pair，用于 collision/false split | W03、W04、W11、W14、W16–W20；其他可构造 world SHOULD 提供 |

`extension_check` / `extension_treatment` 中，base 模型与初始 state schema 必须先封印。可允许的新 operator/schema migration/retraining budget 必须由 freeze manifest 精确列出；扩展后不得将新数据静默编入旧 primary score。

### 3.7 五 replicate panel：训练 seed 与隐藏评估 seed 分离

CONFIRM 的随机性 MUST 拆成两个不同时间点封印的 tuple，不能在抽到隐藏 test seed 之后再训练或挑模型。

`TRAIN5-v1` 在训练前公开并写入 semantic freeze；每个候选必须按五个 `training_replicate_id` 训练并封印五个 artifact：

```text
model_initialization_seed
training_data_seed
training_order_seed
```

`EVAL5-v1` 只在至少三个不同 family finalist 的 **全部五个** source/config/model artifact 同时封印后抽取并 commit；每个隐藏 `evaluation_replicate_id` 包含：

```text
world_process_noise_seed
observation_schedule_seed
evaluation_episode_seed
analysis_seed
```

两类 seed 都由用途域隔离的冻结 KDF/PRNG 派生，并分别保存 tuple digest。`CONFIRM5-v1` 定义为五个预封印 TRAIN5 artifact 与五个 EVAL5 hidden replicate 的冻结一一配对；同一 `evaluation_replicate_id`/corpus 被所有候选共享。不得在五个 artifact 中按 hidden 表现挑一个，也不得扩成事后挑优的 5×5 搜索。确定性候选可将模型随机项标为 `not_applicable`，但仍须在训练前声明 artifact 复用规则，并跑五个独立 EVAL5 replicate。

- `DEV5-v1`：训练与评估的完整 tuple 均公开、固定，用于 30+ 搜索实验；只是 development evidence。
- `CONFIRM5-v1`：使用预公开 TRAIN5 artifact panel + post-artifact-seal 的共同 hidden EVAL5 corpus。
- `REPRO5-v1`：source-distinct 独立实现使用独立预提交 TRAIN5 panel；其五个 artifact 封印后再抽独立 hidden EVAL5 commitment。
- `REDTEAM5-v1-rN`：candidate freeze 后的独立攻击 seed，不是 v1 primary corpus。

五个 required pairing 中的 crash/OOM/NaN 是 raw 结果，不得换 artifact、换 seed 或丢弃。任一 required cell 缺失使 run 为 `INCOMPLETE`。所有候选使用同一 episode/action/horizon manifest，以支持 paired comparison。

### 3.8 数据预算、选模和防泄漏

Primary 比较使用 `compute-matched-v1` 轨：freeze manifest 必须对所有候选冻结 train family/episode/query 数、validation 评分调用次数、超参数 attempt 上限、wall/CPU/GPU 预算和 early-stop 规则。`family-native-unconstrained` 可单列作能力参考，但不得和 matched track 混成一个赢家。

防泄漏 MUST 至少覆盖：

1. train/validation/test/red-team 的 family-atomic 无交叉证明；
2. 同一可见 prefix + 不同 secret future/oracle 在 cut 时产生 exact 相同 state/output；
3. late result 在 `available_at` 前对旧 cut 无影响；
4. 动作/观察/UID 的 opaque alpha-renaming 不改变同构结果；
5. candidate process 无法读取 repo test/oracle/results 路径、网络、共享内存、上一 worker 的临时文件；
6. 候选封印 timestamp 先于 hidden seed reveal 和首条 test raw row；
7. hidden test 不得用于 threshold、checkpoint、结构、状态维数或读出选择；
8. 公布后修改的结果强制标记 `post_test_tuned`，不得覆盖原 blind run。

每个 world/split/training-replicate/evaluation-replicate 的精确 family、episode、cut、horizon、policy 和 pair 数必须写入机读 `expected-cells.json`，且每个 cell 必须带与 world/split/run manifest 一致的 `scope_digest`。本文不以一个通用比例伪装精确计数；**`expected-cells.json` 未 materialize 或 scope join 未 fail-closed 前 v1 就仍是 PRE-FREEZE**。

## 4. 候选协议：值传递、分角色、可隔离

### 4.1 四类进程角色

实现 MAY 复用已有 K0 isolated runner 的“parent judge 与 candidate view 物理分离、canonical digest、audit transcript”基础设施，但 MUST 使用全新的 UCM wire protocol，且不得导入 K0 的候选状态或结论：

1. `trainer`：只能见 train generator/cases 与允许的 validation；产出冻结 `ModelArtifact`。
2. `state-worker`：只做 `initialize/update`，收到 prior state 和 newly available event batch；不能收到 task kind。
3. `head-worker`：只做 `diagnose/rollout/ood/readout`，收到只读模型、同一 state、query；不能收到历史。自然与干预未来仅由 `rollout` 的 typed plan 区分。
4. `judge`：唯一持有 oracle、true state、未发生未来、utility truth 和 test ID；候选进程不可导入或读其文件。

纯 Python 候选可沿用 `python -I -S`、最小 allow-list package、audit hook。使用 PyTorch/native/GPU 的候选必须放进无网络、只读模型挂载、空临时目录、系统调用/文件访问受限的 OS container/AppContainer；仅靠 CPython audit hook 不足时，结果必须标 `isolation_assurance=python_only`，不得声称已防住 native escape。

### 4.2 规范接口

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

### 4.3 `CandidateManifest`

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
  "scope_digest": "sha256:...",
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

### 4.4 `UpdateResult`

候选返回值不包含它无权知道的 runner hash：

```json
{
  "protocol": "ucm-update-result/1",
  "new_state": {},
  "status": "ok|scope_insufficient|unsupported|invalid_input|numerical_failure",
  "diagnostics": {}
}
```

runner 验证/封存 `new_state` 后在外层 update ledger 附加：

```json
{
  "prior_state_hash": "sha256:...",
  "consumed_event_batch_digest": "sha256:...",
  "new_state_hash": "sha256:...",
  "scope_digest": "sha256:...",
  "candidate_status": "ok"
}
```

候选不得收到或自报 `prior_state_hash/new_state_hash/event_batch_digest`；这些都是 runner 根据实际传入/返回 bytes 计算的证据字段。

`newly_available_events` 是相对于 prior cut 的增量 public view，并带显式 `advance_to`。即使 event 列表为空，时间推进也必须通过 `update(state, {advance_to, events: []})` 表达；state-worker 不得自行读墙钟。state-worker 不得自行读取完整历史；runner 另行做 clean replay oracle，用于比较 incremental 与从初始事件逐步 replay 的结果。

### 4.5 readout 输出

所有 readout 公共 envelope：

```json
{
  "protocol": "ucm-prediction/1",
  "prediction_kind": "diagnosis|forecast|counterfactual|ood|novel_readout",
  "status": "ok|abstain|scope_insufficient|unsupported|invalid_input|numerical_failure",
  "distribution": {},
  "identification": {
    "kind": "point|partial|none",
    "effect_set": null,
    "utility_set": null,
    "assumptions_digest": "sha256:..."
  },
  "support": {
    "ood_score": 0.0,
    "unknown_probability": 0.0
  },
  "diagnostics": {}
}
```

上述是 candidate output；runner transcript 在外层增加 `query_digest/input_state_hash/consumed_state_hash/scope_digest`，并验证调用前后 exact state bytes 与 model digest 未变。不要把 evaluator hash 暴露给候选后再相信它回显。

诊断必须输出机制/疾病类型 posterior（含 `unknown`）；轨迹必须输出可评分分布而不只是点预测；反事实必须对每个 policy 输出相同 outcome schema。`identification.kind=partial|none` 时，`effect_set/utility_set` 必须是冻结 schema 的集值结果而不是点效应伪精确。`abstain` 表示范围内证据不足；`scope_insufficient` 只能用于 query 超出已声明 `S`；`unsupported` 不是免费跳过；`invalid_input` 只用于输入 schema/值域错误；`numerical_failure` 必须保留 raw diagnostics。在已声明 scope 的 required cell 上，后四类状态中除合法 abstain 外都计入对应 coverage/failure。

治疗选择由 judge 使用候选预测分布/识别集和冻结 utility 计算，而不是允许每个候选另写不可审计的 treatment recommender。point-identified cell 使用统一 argmax/tie-break；partial/none cell 使用第 7.4 节冻结的 set-valued/minimax-regret rule。候选自报推荐只是附加信息，不替代 judge 的可比较决策。

## 5. 时间、action、no-op 与更新语义

### 5.1 三种时间不能塌缩

每个 event 至少有：

- `occurred_at`：患者世界中发生；
- `collected_at`：检查/采集；
- `available_at`：候选在此后才可见。

state cut 以 `available_at <= cut.available_time` 决定可见性；发生过但尚未 available 的结果不得进入 state。区间使用冻结的半开/闭规则，并有 boundary 与 `+epsilon` 测试。

### 5.2 action 的 typed sum

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
             | CompositePolicy(ordered_or_adaptive_actions)
```

硬语义：

- `NoNewAction`：从 cut 后不施加新的 action；state 中既往治疗造成的持续/衰减效应仍按动力学演化。
- `ContinueCurrent`：按 request 中显式 schedule 继续给药/治疗，**不是** no-op。
- `StopControllable`：显式停止未来可控暴露，不能用 no-op 暗示。
- `Do(A)`：从同一 factual state fork，在指定时间执行 A；不是观察到历史上选择 A 的 conditioning。
- `CompositePolicy`：必须是 world manifest 冻结的有限有向无环 policy tree；adaptive branch 只能读该 hypothetical rollout 中已 `available` 的检查/观察，不能读 private state 或未来结果。
- `PlannedTreatment`：可以作为关于决策过程的观察证据，但不能触发生理 treatment effect；只有 `PerformedTreatment` 进入 action transition。
- 退热药等 observation-channel action 与 mechanism/state action 必须分开；W06/W07 检验二者。

### 5.3 counterfactual purity

对 A/B/C 和 no-op 的每个查询都从同一 exact state bytes 开始，在 fresh head-worker 执行：

```text
Z_t --query NoNewAction--> predicted future only
Z_t --query Do(A)-------> predicted future only
Z_t --query Do(B)-------> predicted future only
Z_t --query Do(C)-------> predicted future only
```

这些调用不得创建 factual new state。只有实际 `PerformedTreatment` 和随后 available 的真实 response 通过 `update` 产生 `Z_{t+}`。A/B/C 查询顺序置换后，每个 policy 的结果必须相同；模型/state 文件 digest 前后必须相同。

### 5.4 online update invariants

1. `incremental update == clean event replay`（canonical hash 或冻结数值容差内行为等价）。
2. 同一 event ID 重复投递幂等；不得重复计数。
3. 同一 causal order 的单条更新与合法 batching 等价。
4. late-arriving observation 按 event time 与 available time 正确吸收，不得倒泄漏到旧 cut。
5. query 是只读的；任何 query 前后 update 结果不受 query 顺序影响。
6. 实际治疗反应到来后，diagnosis、natural forecast、treatment forecasts 都必须从新的同一 hash 重算；不得只更新其中一个 task latent。
7. 空 delta 仍可推进到新的 cut；调用结果只由显式 `advance_to` 决定，不得依赖 wall clock/PID/调用次数。
8. 未知的新 action 若不在已声明 `S` 内，必须返回 typed `scope_insufficient`；若已在 scope 内却未实现，返回 `unsupported` 并计 required-cell failure。两者都不能以高置信默认映射到旧 action。

## 6. 硬合规测试矩阵

每项都要有至少一个故意作弊 mutant，证明 harness 会杀死它。`HARD_FAIL` 不得用其他指标补偿。

最强结构门是 **cross-process state closure**：worker A 执行 `initialize` 后立即销毁；删除其 episode 临时目录；只保留只读 candidate bundle、catalog 和 sealed state payload；diagnosis/no-op/A/B/C 分别在 fresh workers 中运行；后续 `update` 也必须在 fresh worker 中只凭 `old state + delta + explicit seed` 成功。若 payload 只是内存/文件 handle，或另有患者缓存，这一步会直接失败。

| ID | 自动测试 | 通过条件 | 主要杀死的作弊/缺陷 | 级别 |
|---|---|---|---|---|
| C01 | exact shared-state fan-out | diagnose/no-op/A/B/C/ood 的 runner transcript 均附加同一实际输入 hash | 为不同 head 生成/传入不同 state；不单独证明 blob 内 semantic unity | HARD |
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
| C19 | condition/do separation | W15 observational-only 子面板不得伪称 point identification；冻结 randomized/support-identifiable 子面板中必须区分反向 association 与 `do(A)` effect | conditioning 冒充干预，或在无识别时伪精确 | HARD |
| C20 | observation/state channel separation | W05–W07 中观察改善不被等同为机制恢复 | observation-is-state | HARD |
| C21 | online update lineage | prior hash、event digest、new hash 可核；new heads 全读 new hash | task 独立 update | HARD |
| C22 | incremental/replay/batch | incremental、合法 batch、clean replay 行为等价 | stale update/cache | HARD |
| C23 | late-event old-cut stability | 未来才 available 的 correction/response 不改变旧 cut | 后见信息倒灌 | HARD |
| C24 | attributable exact/functional dangerous collision | 仅当 pair 已冻结为 `attributable_collision=true`、区分证据对候选合法可用且 public-posterior oracle 证明相反治疗方向/灾难 regret 时，不得同 hash 或功能不可区分 | 可归因的危险状态合并；不惩罚 private-truth twins | HARD |
| C25 | OOD fail-closed | W18 中第 7.6 节高置信强配 + 非 abstain + judge 选出 unsafe/catastrophic action 不得发生 | closed-world 强配导致危险 action | HARD |
| C26 | novel-readout isolation | 冻结 state encoder；新 head 只见 state，不见 history | “迁移”时重新读原史 | HARD |
| C27 | full-history disclosure | raw/history canary 若出现在 state，必须声明 full-history baseline | 伪装压缩状态 | HARD for misclaim |
| C28 | run reproducibility | seal、seed、环境相同可重放 raw prediction/metric | 不可复现 | HARD |
| C29 | query preannouncement denial | initialize/update 不知道随后会问 diagnosis/A/B/新任务；改变 future query set 不改 state | 按未来任务造 state | HARD |
| C30 | explicit RNG/clock isolation | PID、tmp path、wall clock、调用排列变化时，同显式 seed 结果相同 | 隐式 RNG/时钟状态 | HARD |
| C31 | undeclared history-memory probe | 无关 provenance canary、event UID/顺序重命名和 history-length ladder 检查可恢复性/size slope | 压缩/加密暗存原史 | HARD for misclaim |
| C32 | single controlled rollout entry | no-op/continue/A/B/C 动态调用同一 `rollout`，无 task-specific transition entry | 自然/治疗两套世界模型 | HARD |
| C33 | patient-state-root audit | patient-dependent computation graph 只有一个跨调用 root；无 task-exclusive persistent roots；可审计候选必须 PASS | blob 内三套 latent 串联 | HARD；无法获得证据则 semantic_unity=INCOMPLETE |

### 6.1 防缓存第二状态的具体执行顺序

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

### 6.2 防 test-id/name 分支

静态 grep 只能作提示，不能作主要证据。主要证据是：

- candidate view 根本不含 W01/Wxx、case ID、expected disease；
- runner 用不可预测 opaque episode handle，handle 不进入 state worker；
- 生成同构的 alpha-renamed world/action/observation/mechanism vocabulary；
- 打乱注册/字段/episode 顺序；
- 同一语义不同名称结果同构，不同语义相似名称仍不同；
- sealed source 后再抽 hidden seed。

### 6.3 合规 runner 也要自测

v1 MUST 内置下列故意作弊/错语义 mutation candidates。“源码看起来有检查”不是证据；每个 mutant 必须被实际执行，并产生预注册 failure code。
失败码使用 `FORMAL_SPEC.md` 的 `UCM-F*` / `UCM-E*` registry；测试可在 evidence record 中增加 subtype，但不得另起一套不可对齐的主 failure code。

| Mutant | 攻击/缺陷 | 必须被杀死的门 |
|---|---|---|
| `GlobalSecondState` | module global 保存患者/task latent | C04/C05/C15, `UCM-F006-HIDDEN_PATIENT_CACHE` |
| `FileHandleState` | payload 仅存内存/文件 handle 或路径 | cross-process closure/C07/C09, `UCM-F008-STATE_NOT_CLOSED` |
| `RawHistoryHead` | head 在 query 时打开原始历史 | C02/C09, `UCM-F004-HEAD_HISTORY_ACCESS` |
| `TrainerTargetSmuggler` | adapter 把 diagnostic target、future label 或 counterfactual sibling 并入同样本 encoder/state input | public/target/oracle projection gate + C07–C12, `UCM-F001-FUTURE_LEAK` 或 `UCM-F002-ORACLE_TRUE_STATE_ACCESS` |
| `HistoryInBlob` | 将完整历史压缩/加密后伪装为紧凑 state | C27/C31, `UCM-F018-FULL_HISTORY_MISCLAIM` |
| `MutableCheckpoint` | 把 patient latent 写入模型权重/配置 | C06, `UCM-F009-MODEL_MUTATION` |
| `WarmFutureCache` | 后期 future 查询污染旧 cut | C05/C10/C12/C23, `UCM-F001-FUTURE_LEAK` 或 `UCM-F011-TIME_VISIBILITY_VIOLATION` |
| `AvailabilityOffByOne` | 在 `available_at > cut` 时提前消费结果 | C11, `UCM-F011-TIME_VISIBILITY_VIOLATION` |
| `TrueStateReader` | 读 simulator hidden state | C08/C09, `UCM-F002-ORACLE_TRUE_STATE_ACCESS` |
| `FutureReader` | 读 future/oracle/results 文件 | C08–C12, `UCM-F001-FUTURE_LEAK` 或 `UCM-F002-ORACLE_TRUE_STATE_ACCESS` |
| `TestIdSwitch` | 按 case/test/Wxx 返回预制答案 | C13/C14, `UCM-F003-TEST_ID_BRANCH` |
| `WorldNameSwitch` | 按 disease/world/action 名称分支 | C13/C14, `UCM-F003-TEST_ID_BRANCH` |
| `ImplicitRNGState` | 依赖调用次数、PID、clock 或隐式 RNG | C04/C05/C28/C30, `UCM-F020-NONREPRODUCIBLE` |
| `QuerySmuggler` | initialize 预先知道随后会问哪个 task/action | C03/C29, `UCM-F005-TASK_SPECIFIC_STATE` |
| `QueryReencoder` | diagnosis/rollout 各自从 history 重建 latent | C01–C03/C29/C32, `UCM-F004-HEAD_HISTORY_ACCESS` 或 `UCM-F005-TASK_SPECIFIC_STATE` |
| `CounterfactualMutator` | 查询 A 修改 factual state，影响 B/diagnosis | C16, `UCM-F012-QUERY_MUTATES_FACT` |
| `NoOpMeansStop` | no-op 清除既往治疗作用/暗中停药 | C17, `UCM-F014-ACTION_SEMANTICS_CONFLATED` |
| `PlanMeansPerformed` | 将 plan/order 当成已实施 action | C18, `UCM-F014-ACTION_SEMANTICS_CONFLATED` |
| `ActionAsConditioning` | 用观察治疗相关性回答 `do(A)` | C19/W15, `UCM-F015-CONDITIONING_AS_INTERVENTION` |
| `NonIdPointEstimate` | 在合法 identified set 跨零/跨相反 action 时伪报 point effect | C19/W15, `UCM-F015-CONDITIONING_AS_INTERVENTION` |
| `ObservationEqualsMechanism` | 退热/显示改善被当成内部机制恢复 | C20/W05–W07, `UCM-F014-ACTION_SEMANTICS_CONFLATED` |
| `ReplayBatchDivergence` | incremental、batch 与 clean replay 对同一事件集产生不同行为 | C22, `UCM-F019-UPDATE_INCONSISTENT` |
| `DoubleCountEvent` | 重复 event UID 被再次计入状态 | C22, `UCM-F019-UPDATE_INCONSISTENT` |
| `TripleLatentBlob` | 将三套互不更新的 task latent 串为一个 blob | C21/C26/C32/C33 + dependency audit, `UCM-F005-TASK_SPECIFIC_STATE` 或 `UCM-E001-SEMANTIC_UNITY_UNVERIFIED` |
| `UnsafeClosedWorld` | W18 强制归入 known 并选危险 action | C25/W18, `UCM-F017-OOD_FORCED_MATCH` |
| `DangerousMeanCompressor` | 平均压缩合并 W04/W19 相反治疗反应 | C24/W04/W19, `UCM-F016-DANGEROUS_COLLISION` |

freeze 前 MUST 生成 `mutation-kill-matrix.json`，记录 mutant source digest、执行 seed、预期 gate/failure code、实际 decisive record 与 killed boolean。上表每个 mutant 都要被至少一个与攻击语义相符的门杀死，且 C01–C33 每个门至少有一个定向 mutant 覆盖；仅因进程崩溃、schema 不合法或无关 timeout 而“没有输出”不算有效 kill。任一目标 mutant 存活、只被无关门杀死或任一 gate 无覆盖，benchmark 必须标 `HARNESS_INCOMPLETE`，不得宣布候选合规。

为防止 detector 过度拒绝合法实现，mutation suite 还 MUST 包含 specificity controls：显式 seed 的 stochastic state、合法不同内部坐标但相同行为的 serialization、宣告正确 waiver 的 FullHistoryBaseline，以及在 nonidentified W15 子面板正确返回 identified set 的 `CorrectNonidentifiedSet`。它们应通过自己允许的 gate/分类，不得被误报为普通作弊候选。

攻击**家族与判定规则**是 public freeze 的一部分；但 hidden twin 的 exact prefix/future、UID/action alias mapping、canary nonce/位置、fresh-worker 调度顺序、warm-cache 预热值和 syscall trap path MUST 由 candidate seal 后的 private seed 生成。这些实例在 reveal 前不得进入候选源码、配置或开发日志。

### 6.4 同一个 hash 仍不能单独证明 semantic unity

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

## 7. 统一指标：定义、分母和不可合并边界

所有指标至少按 `candidate × model_seed × world × episode × cut × horizon × policy` 保存 raw row，再汇总。不能只报总体平均。独立采样单位是 episode/world seed，不是同一 episode 内的多个 query row；置信区间须按独立单位 cluster bootstrap。

### 7.1 诊断与校准

- 候选 MUST 对 world 冻结的 mechanism/disease/dynamics partition 输出归一化 posterior（含 `unknown`）。若 oracle 能枚举 `P(label | public history)`，primary 是预测 posterior 对 oracle posterior 的 cross-entropy/NLL 和 multiclass Brier；若只保留实现 latent label，则对 realized label 计算相同 proper score，且必须跨 episode 聚合才能解读为校准。
- primary diagnostic partition MUST 与冻结 query scope 下的行为可区分性对齐。若两个 private disease/mechanism 名称在所有允许检查、等待和干预下都产生相同未来分布，benchmark 不得用私密名称强迫 UCM 拆分它们；该名称最多作为非 primary 描述性 target。
- multilabel world 的 label set 和 dependence score 必须由 world manifest 冻结；不得将多模态后验强行转成单一 top-1 真值。
- descriptive：top-1、top-k、macro recall；不单独据此选 winner。
- calibration：15-bin equal-mass ECE、classwise ECE、reliability bins；概率区间用 50/80/95% empirical coverage。
- 概率只为数值计算 clip 到 `[1e-12, 1-1e-12]`，raw output 仍保存；输出非法概率直接合规失败。
- `unknown` 是显式类别/质量，不能事后从低置信猜测。

### 7.2 自然病程预测

分别报告 `NoNewAction` 和 `ContinueCurrent`，不得混成一项：

- 连续单变量：CRPS（primary）、oracle scale 标准化 MAE/RMSE、interval coverage。
- 离散观察/事件：NLL、Brier。
- 多变量轨迹：energy score 或 world 冻结的 joint proper score；另报每轴误差，避免平均掩盖关键轴。
- 结局：survival/event probability 的 integrated Brier/NLL；固定时点 utility distribution error。
- 校准：每个 horizon 的 50/80/95% interval/region coverage、discrete event reliability 和 calibration slope/intercept；不得用点预测回避分布校准。
- 每个 world manifest 冻结的 horizon 独立报告，不允许先平均 horizon；跨 world 的 short/medium/long 锨点仅在语义一致时才聚合。

### 7.3 干预预测

对每个允许 policy/action sequence：

- 与自然预测相同的 trajectory proper score；
- treatment-effect error：候选与 oracle 的 outcome/utility contrast 误差；
- effect-sign error；
- 每个 policy/horizon 的 interval/event calibration 与 coverage；不得只校准 factual/no-op arm；
- 若 oracle 有 unit-level paired counterfactual，报告 PEHE/ITE error；否则只报 distributional effect，禁止伪称 individual effect。
- 若冻结信息/数据只支持 partial identification，候选必须输出 effect/utility identified set 或 typed abstention；报告 set coverage、set width 与 false-certainty rate。不得用 private simulator 的实现真效应惩罚一个对 public history 合理的 nonidentified posterior。
- worst-policy、worst-world、worst-episode 必须保留。

### 7.4 治疗后悔

后悔的主定义取决于该 cell 的冻结 `identifiability`，不能用 private simulator realized type 假装所有反事实都已从 public evidence 识别。

**point-identified cell**：judge 用冻结 utility `U_w` 和候选预测统一选择：

```text
a_oracle = argmax_a E_oracle[U_w | do(a), H_t]
a_hat    = argmax_a E_candidate[U_w | do(a), Z_t]
regret   = E_oracle[U_w | do(a_oracle)] - E_oracle[U_w | do(a_hat)]
```

报告 raw regret、normalized regret = `regret / (max_a V_oracle(a)-min_a V_oracle(a))`（零分母为 N/A）、mean/median/p95/max/CVaR95、effect-sign error 和 catastrophic-action rate。tie-break 与 optimal-action tolerance 由 world manifest 冻结，候选不得自定。

**partial/nonidentified cell**：oracle 先基于 public history、合法训练信息和 `assumptions_digest` 构造兼容模型/效用集合 `M_id(H_t)`，而不是暴露 realized private model。候选必须返回 effect/utility identified sets。统一 judge 报告：

- oracle identified-set coverage、候选 set width 和 Hausdorff/set-bound error；
- set-valued optimal actions（在至少一个兼容模型中最优）与 uniformly dominated actions；
- 对每个 action 的 robust regret bound `sup_{m in M_id} [max_b V_m(b)-V_m(a)]`；
- judge 按冻结 minimax-regret/tie rule 从候选 utility set 选择的 action 及其 oracle robust-regret interval；
- false-certainty rate：候选给 point/high-confidence effect，但合法 identified set 跨零、跨相反 action 或比候选区间更宽。

realized private simulator type 上的 single-path regret MAY 作为 `descriptive_realization_regret` 保存，但不得作为 partial/none cell 的 primary 排名或 collision/catastrophic hard gate。只有当候选/统一 judge 选择的 action 在 **所有** `M_id(H_t)` 兼容模型中都超过冻结 catastrophic margin，或候选在 point-identified cell 选择灾难 action，才能触发 attributable hard failure。

W19 MUST 在候选运行前固定 `tail_cohort_digest`、该 cohort 的暴露数、identifiability、contraindicated action 和 catastrophic margin。必须同时报告 full-population regret 和 `regret | tail_cohort` 的 mean/max/CVaR95/catastrophic rate；partial-identification tail 另报 robust bounds。不得通过改变稀有例 prevalence、在总体 bootstrap 中漏抽，或用 abstain 从分母删除来规避该 cohort 的覆盖/安全报告。
### 7.5 collision 与 false split

不同表示没有自然统一的 latent 距离，因此 v1 采用冻结 probe set `Q_w` 的**行为距离**。对同一 cut 的两个历史 `h_i,h_j`：

```text
D_oracle(i,j) = max over q in Q_w of world_normalized_distance(
                    P_oracle(. | h_i, q), P_oracle(. | h_j, q))

D_candidate(i,j) = max over q in Q_w of same_distance(
                    P_hat(. | Z_i, q), P_hat(. | Z_j, q))
```

`Q_w` 必须覆盖允许的等待、未来检查、no-op、continue 和所有冻结 treatment/action sequence。`world_normalized_distance` 由 world oracle 预注册：有限分布优先 TV；连续轨迹用按 oracle scale 归一的 Wasserstein/energy distance；utility contrast 归一到 `[0,1]`。不能由候选选择。

`P_oracle(. | h,q)` 必须是**仅以候选在该 cut 可获得的 public history、已冻结 training-information regime 和允许的 query 为条件**的 posterior predictive，不是私密 realized latent state 的单路径未来。两个 public prefix exact 相同但 private truth 不同的 twin，正确 `Z_t` 应是同一 belief，不是被要求猜中 private truth。

每个 pair 必须预注册 `candidate_information_relation`、`identifiability` 和 `attributable_collision`。只有当区分信息在 public history/合法 training support 中存在、oracle posterior predictive 在冻结 probe 上可区分，且候选仍功能合并时，collision 才能归因给状态表示。不可识别子群的高置信伪精确可另行触发 false-certainty gate，但不得伪造“本应拆分”的 state collision。

冻结三个 margin：

- `epsilon_equivalent_w`：oracle 数值误差内可视为行为相同；
- `delta_distinguishable_w`：临床/决策上确定可区分；
- `epsilon_candidate_same`：候选实际没有可用区分的容差。

定义：

- raw exact collision flag：`state_hash_i == state_hash_j` 且 `D_oracle >= delta_distinguishable`。
- raw functional near-collision flag：`D_candidate <= epsilon_candidate_same` 且 `D_oracle >= delta_distinguishable`。
- attributable collision：上述 raw flag 成立，且 pair manifest 预注册 `attributable_collision=true`、区分信息已在 public history/合法 training support 中可用，`D_oracle` 来自 public-posterior predictive。
- attributable dangerous collision：attributable collision 成立，且 point-identified oracle optimal-action sets 不相交/effect sign 相反/后悔超 catastrophic margin，或 partial-identified 情形下候选合并后的动作在所有兼容模型中均为 catastrophic。
- functional false split：`D_oracle <= epsilon_equivalent` 且 `D_candidate >= delta_distinguishable`。
- structural redundancy：oracle 等价但 canonical state hash/bytes 不同；作为简洁性诊断，不单独硬失败。exact hash 不同不能自动等于“明显拆分”。

报告分母：raw collision rate 的分母是所有 oracle-distinguishable frozen pairs；另报 attributable collision rate，分母仅为 `attributable_collision=true` pairs；false-split rate 的分母是所有 oracle-equivalent pairs。还要报告 max missed oracle distance、max spurious candidate distance 和所有 pair IDs/轨迹。**只有任一 attributable exact 或 functional dangerous collision 才是 collision 硬失败**。private-truth twins 上的错误拆分/伪精确进 future-leak/false-certainty/identifiability gate，不得伪称 attributable collision。非危险 near-collision 进 Pareto 与 worst-case 报告，不能只报平均率。

### 7.6 OOD/open-world

候选只用 validation 选择 OOD threshold，并在 model seal 中记录；test 后不得调阈值。报告：

- AUROC、AUPRC（OOD 为 positive）；
- FPR@95TPR、TPR@固定低 FPR；
- selective risk-coverage curve/AURC；
- known-case coverage 与 OOD abstention；
- `unknown_probability` Brier/NLL 与 calibration；
- OOD 上的 treatment regret/unsafe non-abstain rate。

v1 冻结高置信强配指示条件：W18 **已出现冻结 public OOD evidence** 的 designated unseen-mechanism cut 上，`max_known_probability >= 0.90` 且 `unknown_probability <= 0.10`。满足该条件记一次 `forced_known_high_confidence`；如候选不 abstain，且统一 judge 依其预测选出 oracle 定义的 catastrophic/unsafe action，则是不可补偿硬失败。不危险的高置信强配仍是 OOD/calibration 失败证据，但不单独混成 catastrophic gate。在 public prefix 上与 known mechanism 信息论不可区分的 pre-evidence cut 只评分 posterior/calibration 和后续更新，不得要求候选预知 OOD private label。候选自身用于 abstain 的 threshold 只能在 validation 上选定并写入 model seal。

### 7.7 时间泄漏

冻结 paired-prefix fixtures：future A/B、actual outcome A/B、late result A/B 在 cut 前 public bytes 完全相同。记录：

- `state_leak_rate = nonidentical_state_hash_pairs / identical_prefix_pairs`；
- `prediction_leak_rate` 与 max pre-availability output divergence；
- boundary error count；
- old-cut instability count。

同模型、同 inference seed、同 prefix 时容忍度为 exact bytes/hash；任何差异都是硬失败。若候选只输出采样而非显式分布，必须用 common random numbers 并同时保存样本，但 v1 应优先要求显式 distribution。

### 7.8 sample efficiency、组合泛化与稳定性

- 固定 train fractions：`1%, 5%, 10%, 25%, 50%, 100%`（每层至少有预注册最小 episode 数）。
- 对诊断/自然/干预 proper score 分别画 learning curve，报告 log-sample 轴 AUC；不得只用最好 checkpoint。
- 新机制组合/新宿主修饰/非线性共病单独报告 held-out gap。
- 完整候选至少 5 model seeds；报告 mean、SD、min/max、paired 95% CI。环境 seed 与 model seed 分开保存。

### 7.9 更新一致性

至少四项：

- exact incremental-vs-replay hash match rate；
- batch-vs-sequential behavioral match；
- query-order purity；
- informative new observation/treatment response 后，各 head 相对于 oracle 的 posterior/forecast/effect score change。

最后一项不要求“每次都变好”，而是与 oracle 信息方向比较；无信息 observation 不应被强迫改变 state。

### 7.10 新检查、新治疗、新任务和历史删除

冻结候选后运行：

- 新检查：新增 observation operator 后，原 collision pair 能否局部拆开；记录模型/状态 schema migration、retrain examples、artifact delta bytes、core diff LOC、旧 benchmark 回归。
- 新治疗：新增 action 后，旧等价类是否被检测为不再充分；若必须完全重写核心，记录 hard extensibility failure。
- 新任务 readout：卡片先声明 `source_scope_digest`、`target_scope_digest`、`in_original_Y=true|false` 及判定依据；冻结 state encoder/updater/dynamics，仅允许用 train split 的 `(state,new_label)` 训练新 head，禁止 raw history。只有 `in_original_Y=true` 却无法从 state 读出时才证伪原 scope 充分性；范围外 readout 仅评估 refinement/migration 与扩展成本。报告 score、样本效率和 history baseline gap。
- 历史删除：删除冻结片段，比较 state/prediction/oracle 行为；发现真正需要的记忆与无效记忆。
- 时间尺度：对 world manifest 冻结的 short/medium/long horizons（有临床时间单位的 world SHOULD 包含 1h/24h/7d 锨点）分开测 state bytes、误差和 collision，检查 state 是否随 horizon/task 膨胀。

### 7.11 简洁性与计算成本

分别保存而不做单一“复杂度分”：

- canonical state raw bytes、scalar/node/edge/particle 数；
- canonical bytes 经同一压缩器后的 bytes（仅作辅助，不能隐藏 raw）；
- state size 对 history length 的 slope；
- model artifact bytes 与 train FLOPs/time；
- initialize/update/各 head 的 cold p50/p95/p99 latency；
- peak RSS/GPU memory；
- extension core diff LOC、changed files、schema migration count。

full-history baseline 预期有线性 state-size slope；允许作为无压缩上界，但不得进入“紧凑 UCM”候选声明。

### 7.12 聚合、缺失值和不确定性

主聚合顺序 MUST 是：

1. 先在 `world × replicate × task × horizon/policy × stratum` 内从 raw episode/query 计算 metric；
2. 然后在每个 world 内按冻结 query-cell weight 聚合；
3. 再对二十个 world 等权得到 world-macro；
4. 最后在五个 replicate 上报告 mean、SD、min/max 与 CI。

episode-weighted 数值 MAY 作敏感性分析，但不得取代 world-macro。horizon、policy、stratum 和 W19 稀有禁忌必须单列；不得先平均再判断硬门。

v1 冻结以下不确定性计算：

- `seed_CI95`：五个 replicate-level world-macro 使用 `t(df=4)` 区间；
- `paired_delta_CI95`：候选与 baseline 在相同 replicate/corpus 上的差值使用 `t(df=4)`；
- `episode_CI95`：在每个 `world×replicate×family` 内 cluster bootstrap，不得将同一 family 的 query 当独立样本；
- `hierarchical_bootstrap_CI95`：固定 W01–W20，重采 replicate cluster 和 world 内 family cluster，**10,000** 次；
- bounded rate：附 Wilson 或 Clopper–Pearson exact interval，并报告暴露数。

world 在主 CI 中是固定面板，不重采。若附加 world-resampled CI，必须标为 `exploratory_superpopulation_sensitivity`，不得声称代表真实临床世界。bootstrap 的 `analysis_seed` 与候选输出随机性域隔离，其 exact 值进 freeze manifest。

crash、OOM、NaN、invalid probability、`unsupported` 和 `abstain` 都是有语义的 raw outcome，不得从分母删除。其中：

- `unsupported/invalid/crash` 使 required-cell coverage 不完整，decision-grade run 为 `INCOMPLETE` 或 `INELIGIBLE`；
- `abstain` 保留在 OOD/selective-risk 分母，不免除 known-case coverage 代价；
- 硬门使用 event-level 事实，不因 CI 跨过 0 而被豁免；
- 零次灾难不等于零风险，必须同时报告 exact upper bound。

## 8. 硬淘汰与 Pareto 输出

### 8.1 不可补偿的 run-level 硬失败

先分清证据责任：

- 若 generator/oracle/split/judge/mutation detector 自身不完整，该单元是 `HARNESS_INCOMPLETE`；不得倒置成候选 PASS 或 FAIL。
- 若 harness 完整而候选违反下列任一硬门，是 `CANDIDATE_FAIL` 且 `eligibility=INELIGIBLE`。
- 若 run 缺 required cell/raw/seal 但无法归因于候选还是 harness，是 `RUN_INCOMPLETE`，不得进 Pareto，必须保留 crash evidence。

| 硬门类 | 任一即淘汰的事实 |
|---|---|
| single shared state | C01–C07/C21/C29/C32/C33 中任一 HARD FAIL；head 重读原史、query 重编码第二表示、task-specific persistent latent/cache、多 patient-state root、rollout 使用不同 dynamics |
| privileged information | true state、oracle、future/late result、actual factual outcome beyond cut、test/case/world/split ID 或 expected answer 泄漏；按名称/ID 分支 |
| closure and purity | sealed state 无法在 fresh worker 独立复水；query 改变 factual state/model；输出依赖调用顺序、PID、墙钟、隐式 RNG 或他患者 |
| action/time semantics | no-op/continue/stop 混淆；planned 当 performed；availability-time 泄漏；在 W05–W07 将 observation channel 当 mechanism state；在 W15 将 treatment-conditioned association 当 `do(A)` effect，于 point-identifiable 子面板导致冻结 effect-sign/最优 action 方向错误，或在 nonidentified 子面板输出伪精确点效应 |
| dangerous sufficiency failure | 任一 **attributable** exact 或 functional dangerous collision；W19 在 point-identified 或所有兼容模型均 catastrophic 时选择预注册禁忌 action；上述门不受 mean/CI 补偿 |
| OOD safety | W18 满足第 7.6 节高置信 forced-known 条件、不 abstain，且 judge 依候选预测选出冻结 unsafe/catastrophic action |
| update/readout | incremental/replay 行为不一致、late event 倒流、实际 action/response 只更新一个 task latent、novel-readout 重读 history |
| coverage and numerical validity | 任一 required query 以 `unsupported`、`invalid`、`crash` 或 `NaN` 跳过；概率不归一/越界；所需 prediction distribution 不可评分 |
| reproducibility/integrity | raw results、seed tuple、source/model/config seal、expected-cell 或 checksum 不全；同 seal/seed 无法重放；hidden reveal 后静默改 benchmark/candidate；覆盖原 run |
| representation misclaim | full history 或可逆压缩/加密原史伪装为 compressed state；opaque 多 latent blob 无法完成 semantic-unity 审计却宣称已证明 UCM |

`semantic_unity=INCOMPLETE` 的 opaque 候选 MAY 保留为探索性性能比较，但 `winner_eligible=false`，不得进入“已证明的 UCM” Pareto。false split、非危险 near-collision、一般预测误差和资源成本不单独触发硬门；它们在通过硬门后决定 Pareto/支配关系。

失败 run 仍 MUST 保存全部 raw evidence；不得删除“难看”的结果，也不得用一次修复后重跑覆盖原失败。

### 8.2 通过硬门槛后的 Pareto 轴

独立展示：diagnosis proper score、natural forecast、intervention forecast、regret tail、calibration、OOD、sample efficiency、collision、false split、state size/slope、extension cost、latency/memory、new-readout transfer。禁止用一个可调权重总分掩盖失败。

与 `SeparateTaskBaseline/capacity_matched` 比较时，diagnosis、natural forecast、intervention forecast 必须**逐任务**通过冻结的 paired practical-noninferiority margin/CI；任一任务失败即失去 winner/selection 资格，其他优势不得抵消。同时还必须在样本效率、跨任务一致性、组合泛化、紧凑性或 novel-task transfer 中至少一项达到冻结 practical advantage，才可主张共享状态有实际收益。`best_effort_reference` 只作能力参照，不用于 noninferiority 判定。

### 8.3 四类规定 baseline 的 waiver 不能污染候选门

豁免只能精确绑定到下表的 baseline ID 和违规类；任何子类、wrapper、组合候选或“为了公平”不得继承 waiver。

| Baseline | 唯一允许的 waiver | 仍必须遵守 | 证据资格 |
|---|---|---|---|
| `TrueStateUpperBound` | parent-only oracle adapter MAY 读 simulator full Markov state、exogenous modifiers 和 oracle transition | 不得将 truth 传入普通 candidate worker；必须跑同一 metric/query-cell schema、保存 raw/seal，且明确 `privileged=true` | `upper_bound_only`；用于 oracle/harness 自检，永不是 UCM 候选 |
| `SeparateTaskBaseline` | MAY 使用 diagnosis/natural/treatment 三个独立 patient latent/model/update path | 相同 public data、compute/capacity 账本、hidden isolation、raw results、test seal；不得读 oracle/future | `baseline_only`, `shared_state_compliant=false`；提供放弃共享约束的性能参照 |
| `FullHistoryBaseline` | `Z_t` MAY 是截至 cut 的完整 **visible** history，query MAY 重扫该封存历史 | 不含 hidden state/future；必须披露 state bytes/history-length slope/query re-encoding 成本，必须标 `full_history_baseline` | `baseline_only`；无压缩信息参照，不得宣称紧凑 UCM |
| `K0OnlyBaseline` | MAY 只执行 K0 控制面/证据传输，而无患者 world-state dynamics | 相同 candidate-view 投影与审计；不得从 K0 内部加入未披露预测模型 | `negative_control`；应证明控制面自身不能完成患者地图任务 |

报告 MUST 对每个豁免显示 `waiver_code`、实际触发的 compliance failures 和 `ucm_eligible=false`；不能因为豁免是预期的，就显示成普通 UCM `PASS`。所有 baseline 仍必须跑可适用的同一 W01–W20 指标；`unsupported` 不得被填成零误差。
`SeparateTaskBaseline` MUST 有两个不可混合的 manifest：`capacity_matched`（总参数/训练数据/计算预算与共享候选匹配）用于 practical noninferiority；`best_effort_reference` 用于说明放弃共享约束的能力上界。不得用 best-effort 参数预算却标成 matched，也不得在不同指标上事后挑选两者的较好值。
`TrueStateUpperBound` 若在可解析/可枚举 world 上无法达到预注册 oracle 容差，或 FullHistoryBaseline 与 clean visible-history replay 不一致，应先判 `HARNESS_INCOMPLETE`，不得用此错误上界评审普通候选。

## 9. raw result schema 与不可覆盖目录

每个 run MUST 使用以下不可覆盖布局（可增加文件，不能省略 required 文件）：

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

`run_id` MUST 符合：

```text
YYYYMMDDTHHMMSSZ-<candidate>-<config8>-<nonce8>
```

目录必须以 exclusive create 建立，已存在就 abort。先写临时目录，finalize 时生成排序 checksum manifest 和 `FINALIZED.json`，再原子 rename；finalized 后只读。任何修正创建新 run，并用 `supersedes_run_id` 关联，绝不覆盖旧 raw。

### 9.1 `RUN_MANIFEST.json`

```json
{
  "schema_version": "ucm-run-manifest/1",
  "run_id": "...",
  "run_class": "development|sealed_validation|sealed_test|post_test_tuned|redteam|reproduction",
  "status": "running|finalized|crashed|ineligible",
  "benchmark_id": "UCM-BENCHMARK-v1",
  "benchmark_freeze_digest": "sha256:...",
  "scope_digest": "sha256:...",
  "hidden_corpus_digest": "sha256:...",
  "candidate_id": "...",
  "candidate_source_seal": "sha256:...",
  "model_artifact_digest": "sha256:...",
  "git_commit": "...",
  "git_dirty": false,
  "training_replicate_id": "train-01",
  "evaluation_replicate_id": "eval-01",
  "training_seed_tuple_digest": "sha256:...",
  "evaluation_seed_tuple_digest": "sha256:...",
  "train_data_digest": "sha256:...",
  "validation_data_digest": "sha256:...",
  "runtime": {"python": "...", "os": "...", "container": "...", "dependency_lock": "sha256:..."},
  "isolation_assurance": "python_audit|os_sandbox|container",
  "started_at": "...",
  "finished_at": "...",
  "supersedes_run_id": null
}
```

### 9.2 raw prediction row

至少包含：

```json
{
  "schema_version": "ucm-raw-prediction/1",
  "record_id": "opaque",
  "split": "train|validation|test|redteam",
  "world_alias": "opaque-to-candidate",
  "episode_alias": "runner-only",
  "cut_alias": "runner-only",
  "training_replicate_id": "train-01",
  "evaluation_replicate_id": "eval-01",
  "training_seed_tuple_digest": "sha256:...",
  "evaluation_seed_tuple_digest": "sha256:...",
  "scope_digest": "sha256:...",
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
所有 `states/updates/predictions/oracle-judge/per-query/expected-cells` row MUST 都带同一 `scope_digest`；联结时发现 digest 不同必须 fail closed，不得把 `S` 与 `S'` 的输出聚合成同一 primary score。

### 9.3 aggregate 的最低字段

- 每个 world/task/horizon/policy/seed 的 point estimate 与 cluster-bootstrap CI；
- coverage/unsupported/invalid/crash count；
- hard compliance vector，不是一个布尔值；
- collision/false split pair denominator、count、rate、worst pair；
- regret distribution 尤其 p95/max/CVaR/W19；
- OOD risk-coverage；
- state/runtime/resource statistics；
- mutation-kill matrix digest；
- raw record count 与 checksum，证明 aggregate 可追溯。

## 10. benchmark v1 冻结机制

### 10.1 freeze 的内容

`FREEZE_MANIFEST.json` 必须逐文件记录 exact bytes SHA-256，并覆盖：

1. 本文、`SCOPE_MANIFEST.json`/`scope_digest`、`MICROWORLDS.md`、W01–W20 机读 semantic/world manifests 和版本；
2. public train/validation 与 sealed-test generators，以及每个 generator 的参数 support；
3. independent oracle/reference enumerators，oracle 数值容差或 Monte Carlo error-bound 实现；
4. observation/action/policy/utility/time/diagnosis/output schemas 和 catalog digest；
5. `candidate_inputs`、`trainer_targets`、`judge_oracle` 的 public/private projection 代码与 schema；
6. family-atomic split 算法、stratum support、near-duplicate detector、`WORLD_SPLIT_MANIFEST.json`；
7. seed derivation domain、DEV5 panel、hidden seed draw/commit/reveal protocol；
8. `expected-cells.json`：每个 world/split/replicate/family/cut/horizon/policy/pair 的精确 required 单元；
9. 行为 probe query/pair sets，distance/normalization scale，`epsilon_equivalent`、`delta_distinguishable`、`epsilon_candidate_same`、catastrophic margin；
10. metrics、15-bin calibration 规则、world/cell weights、缺失处理、CI/bootstrap 单元/次数/analysis seed；
11. C01–C33 hard-gate spec、sandbox policy、mutation candidates、specificity controls 与 expected kill matrix；
12. candidate request/response/state schemas、canonicalization/hash domain、runner/judge/result schemas；
13. baseline waiver registry，及 compute/data/hyperparameter/capacity budgets；
14. runner、judge、aggregator、raw-to-summary rebuilder 与 replay entrypoints；
15. dependency locks、container/AppContainer image digest、OS/CPU/GPU/BLAS/CUDA/thread/determinism 配置；
16. 已知 harness limitations、不可验证的 semantic-unity 边界与当前 `HARNESS_INCOMPLETE` 项。

canonical freeze manifest 自身 MUST 使用 UTF-8 sorted compact JSON + LF，并生成独立 `.sha256` sidecar，避免 self-hash。SHOULD 同时生成可读 `FREEZE_REPORT.md`，但 JSON/bytes 为权威。

### 10.2 两阶段 seed commit/reveal

为同时满足“先冻结 benchmark”与“不能按 hidden case 调候选”：

1. **semantic freeze**：上一节 16 类制品全部定稿，生成 `benchmark_freeze_digest`；任一 PRE-FREEZE 阻断项未解决则不能进入下一步。
2. **TRAIN5 precommit**：发布五个 training tuple/digest；所有 finalist 只能据此训练五个 artifact，不接触 EVAL5 seed。
3. **candidate panel seal**：对至少三个不同 family finalist 的全部五个 source/config/model artifact，同时记录 dependency lock、training/validation data digest、OOD threshold、training tuple digest 和 timestamp。
4. **fresh EVAL5 commitment**：在最后一个 artifact seal 之后抽取 256-bit `seed` 和独立 `nonce`；首先只公布 `SHA256("UCM-CONFIRM5-v1\0" || seed || nonce)`、抽取程序 digest 和 timestamp。
5. **generate once and seal corpus**：用冻结 generator 生成共同 W01–W20 hidden EVAL5 corpus、opaque aliases/顺序、paired probes 和 `expected-cells`；对 candidate-view corpus 与 judge-only oracle 分别记录 exact digest，不公布 raw private bytes。
6. **isolated paired execution**：按冻结的一一配对运行所有 finalist；候选只见 public projection，judge 持有 hidden oracle；失败候选不得换 artifact/seed 或重生成 corpus。
7. **finalize before reveal**：raw 完整性、checksum、全部 artifact seal 和 corpus digest 校验完成；每个 run 先标记 finalized/incomplete，不允许看到 oracle 后补跑 required cell。
8. **reveal and replay**：公布 EVAL5 seed/nonce/generator/oracle digest，验证 commitment，并在 clean checkout 重建 exact corpus/summary。

上述状态转移 MUST 用不可覆盖制品记录：`FREEZE_MANIFEST.json`、`CANDIDATE_SEALS.jsonl`、`CONFIRM5_COMMIT.json`、`SEALED_CORPUS_MANIFEST.json`、`CONFIRM5_FINALIZATION.json`、`CONFIRM5_REVEAL.json`。后一制品必须引用前一制品 digest 形成 hash chain。`SEALED_CORPUS_MANIFEST` 公开时只包含 candidate-view/judge-only corpus digest、cell count 和 commitment，不含可逆推 hidden seed 或 private oracle rows。

同一比较中的候选必须跑同一个 hidden corpus。hidden reveal 后修改候选会创建 `run_class=post_test_tuned`，不能替代 primary sealed result。独立复现 MUST 使用 source-distinct 实现 seal 和独立 `REPRO5-v1` fresh seed commitment，不得复用 CONFIRM5 已公布样本冒充 blind reproduction。

开发期 30 个实验使用 train/validation 或已标明的 public mini benchmark；不能反复查看 primary hidden test。至少 3 个完整候选的 primary W01–W20 对比应在 seal 后共同运行。

### 10.3 冻结前 benchmark 自证

freeze 只有在以下自动测试通过后有效：

- W01–W20 各有 true hidden mechanisms、transition、observation、tests、treatments、all-action counterfactual、diagnostic truth、utility、train/val/test generator；
- generator 同 seed byte-reproducible，不同 split 在 exact/family/prefix-near-duplicate/pair 四层均无交叉；
- `candidate_inputs` 与 `trainer_targets/judge_oracle` 物理分离，并有恶意 target-smuggling fixture 证明 encoder/update 无法读 target；
- oracle 概率归一、有限 world 可独立枚举，随机 oracle 有预注册 Monte Carlo error bound；
- no-op/continue/stop/do、planned/performed、event/available time 的关系测试通过；
- candidate public projection 不含 oracle/true state/future/test/case/world/split/family ID，且 factual/counterfactual sibling 不被并入 encoder input；
- C01–C33 全部可执行，且第 6.3 节所有 mutants 被语义正确的 gate 杀死，specificity controls 不被误杀；
- `expected-cells.json` 与实际 raw 记录 exact 对应，崩溃/超时也有占位 raw outcome；
- result raw -> per-query -> per-episode/family -> per-world/replicate -> aggregate/CI 可由独立 rebuilder 重建；
- four-baseline waiver registry 只豁免指定类，wrapper/普通候选无法继承；
- candidate seal→hidden commitment→corpus seal→finalize→reveal 时序有可核 timestamp/digest 链；
- exact manifest/sidecar/replay 在 clean checkout 通过。

若 semantics 已冻结但某隐藏 case 不可执行或 mutation 未被杀，结论必须拆开：候选假说是否失败与 harness 是否完整是两条证据链，不能用绿色 checksum 把 `HARNESS_INCOMPLETE` 说成候选通过。

### 10.4 修改规则

- 拼写/说明变更若不影响 bytes/semantics，也创建新 documentation commit，但不替换旧 freeze manifest。
- runner bugfix：保留 v1 原结果，创建 `v1.0.1` 与 migration note，并在旧/新 runner 都重放；不得静默回写。
- generator/oracle/metric/margin/utility/pair set 的语义变化：创建 benchmark v2。
- frozen 后新增反例属于 `redteam-v1-rN`，不得回灌 v1 primary score；单独 report，并决定是否证伪候选或促成 v2。
- 所有 raw results 保留，即使候选崩溃、作弊或 benchmark 后来发现问题。

## 11. benchmark 构建顺序

1. 先实现 public/target/oracle 三层 schemas、canonicalization、runner-computed hash、append-only result writer 和 split/expected-cell manifest；此时不实现真实 UCM 候选。
2. 写 `TrueStateUpperBound`（明确不合规，仅校验 oracle/metric 上界）、`FullHistoryBaseline`、`SeparateTaskBaseline` 和 `K0OnlyBaseline`。
3. 实现第 6.3 节全部作弊 mutants 和 specificity controls，先让 C01–C33 产生完整 mutation-kill matrix。
4. 对 W01/W02/W04/W08/W15/W18/W19/W20 建 vertical slice：初始化→同 state 多 head→A/B/no-op→真实 action/response update→new state。
5. 扩到 W01–W20，生成 train/validation/private-test split、probe pair/query set、utility、margins 与 exact expected cells。
6. 跑 clean-checkout replay、manifest/checksum、split leakage audit、raw-to-aggregate/CI rebuild；只有此后才生成 benchmark v1 semantic freeze。
7. 候选开发只能消费 public train/validation API；至少三个不同 family finalist 同时 seal 后，共同 hidden CONFIRM5 test 才一次生成和运行。

## 12. PRE-FREEZE 阻断项

下表是**当前 PRE-FREEZE 状态的客观阻断清单**。它们不是可在看到候选 test 结果后再调的参数；必须由 world oracle 数值误差、生成器保证的 effect gap、固定 utility 和预注册资源预算导出，并在任何真实候选读取 sealed-test 前完成。

| 阻断制品 | 完成证据 |
|---|---|
| W01–W20 每 world 的 exact parameter support、public train/validation generator 和 private test generator | 机读 world manifest + same-seed replay + support/property tests |
| 每 world 的 diagnostic truth、counterfactual distribution、utility 和 independent oracle check | 枚举一致性或预注册 Monte Carlo error bound |
| `epsilon_equivalent`、`delta_distinguishable`、`epsilon_candidate_same`、catastrophic regret margin | 写入 world manifest，且小于/大于 oracle error/effect-gap 的推导记录 |
| 连续/多变量轨迹的 oracle scale、distance/proper score 和 axis weight | 冻结 metric config + oracle upper-bound sanity test |
| train fraction `1/5/10/25/50/100%` 的绝对 family/episode 数 | data-budget manifest，每层非零且 nested/digest 可核 |
| 每 world/split/replicate 的 family/episode/cut/horizon/policy/pair 数 | `expected-cells.json`；能从 generator manifest 重建 |
| horizon 集合、allowed action-sequence 集合和 tie-break | 每 world finite query manifest；不允许 runner 临时广播未冻结 query |
| late event/batch 的 canonical ordering、boundary 开闭性与 duplicate policy | schema + boundary/epsilon/batch permutation tests |
| W16/W17 新检查/新治疗的 base freeze、retrain/data/schema-migration budget | base semantic digest + post-candidate extension digest + exact budget config |
| shared candidate 相对 capacity-matched separate-task baseline 的逐任务 practical-equivalence/noninferiority margins | 在 validation/utility scale 上预注册，且不使用 sealed-test ranking 反推 |
| OS/native isolation 实现 | pure-Python primary MAY 使用 `python_audit` + fresh process；任何 native extension/GPU/neural runtime 的 decision-grade run MUST 使用 `os_sandbox` 或 `container` 并产生 access transcript |
| 全部 C01–C33 + mutation/specificity controls | `mutation-kill-matrix.json` 每个 target mutant 被正确门 kill，无 survivor/误杀 |
| freeze manifest、sidecar 与 clean-checkout raw→summary replay | exact digest 通过，已知限制不存在未申报 `HARNESS_INCOMPLETE` |

W18 高置信强配指示阈值已由第 7.6 节固定为 `max_known>=0.90` 且 `unknown<=0.10`；CI hierarchical bootstrap 次数已由第 7.12 节固定为 10,000。它们不再是未决项。任一上表制品缺失时，文档标题下的状态 MUST 保持 `PRE-FREEZE`。

## 13. v1 合规判定输出格式

不要输出一句 `PASS`。输出 evidence vector：

```json
{
  "benchmark_status": "FROZEN-v1|PRE-FREEZE|HARNESS_INCOMPLETE",
  "run_verdict": "CANDIDATE_PASS_ON_FROZEN_SCOPE|CANDIDATE_FAIL|RUN_INCOMPLETE|HARNESS_INCOMPLETE|BASELINE_ONLY",
  "public_private_projection": "PASS|FAIL|INCOMPLETE",
  "family_atomic_split": "PASS|FAIL|INCOMPLETE",
  "expected_cells_complete": "PASS|FAIL|INCOMPLETE",
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
  "mutation_kill_matrix": "PASS|FAIL|INCOMPLETE",
  "reproducibility": "PASS|FAIL|INCOMPLETE",
  "waiver_code": null,
  "eligible_for_pareto": false,
  "winner_eligible": false,
  "decisive_evidence_records": []
}
```

`INCOMPLETE` 表示 harness/证据不足，不等于候选通过。只有所有 hard axes 为 PASS 才进入 UCM Pareto；一个 FAIL 即 ineligible。可保留 `semantic_unity=INCOMPLETE` 的 opaque 候选作为探索性比较，但不能把它当已证明的统一地图赢家。最终 demo 的每个诊断/自然/A/B/C/更新输出必须由 runner 把 `consumed_state_hash`/`prior_state_hash`/`new_state_hash` 连成可核链。

---

### 本规范的核心判断

接口统一本身没有价值；**值传递的唯一 canonical state + 物理隔离的 heads + hidden oracle judge + 行为碰撞 probe + append-only raw evidence** 才能把“一张地图”变成可运行、可攻击、可推翻的主张。若某候选必须在 readout 时重新接触历史、依赖任务缓存，或在新治疗加入后才能发现旧 `Z_t` 丢失关键差异，则应直接报告该共享状态在相应范围内不充分，而不是用新的 head/state 包装继续宣称统一。
