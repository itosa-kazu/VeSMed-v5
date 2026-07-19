# UCM 实验注册、执行、统计与决策

> 状态：**Phase 1 正式研究登记规则；benchmark v1 尚未冻结，候选实验完成数为 0/30。**
> 边界：只规定 UCM 轨道的 experiment registry、运行循环、统计和选择；不修改 K0 结论，不把 K0 当 UCM 候选。
> 证据口径：下文 `EXP-001`–`EXP-040` 目前只是 `PLANNED` 预算槽位，不是已冻结 preregistration、不是 run、不是已完成实验，也不能计入完成数。
> 权威性：实际完成事实将来自未来 append-only registry event 与不可覆盖 run bundle；本 Markdown 是规则和派生的人类可读视图，不能自行把计划升级为证据。

## 0. 当前完成账本

截至本文建立时，权威计数如下：

| 完成门 | 当前值 | 目标 | 说明 |
|---|---:|---:|---|
| benchmark v1 freeze | 0 | 1 | 尚未冻结；因此不得运行普通候选 |
| `DECIDED` 且 `count_eligible=true` 的重大实验 | **0** | **至少 30** | 计划卡、代码草图和 harness fixture 均不计数 |
| 非局部参数调整的重大实验 | **0** | **至少 20** | 下文预留 35 个结构槽位不等于已完成 |
| 完整 W01–W20 共享候选 | **0** | 至少 3 | 每个仍须至少 5 seed |
| 完整候选的五-seed panels | **0** | 至少 3 | 缺任一 required seed/cell 不完整 |
| 独立实现复现 | **0** | 至少 1 | 必须 source-distinct |
| candidate-freeze 后 red-team | **0** | 至少 1 轮 | 不得回写 benchmark v1 |
| cadence counterexample | **0** | 每完成 5 个实验至少 1 个 | 当前 `completion_ordinal=0`，尚未触发 |
| cadence architecture review | **0** | 每完成 10 个实验 1 次 | 当前尚未触发 |

计数只能由 registry 重放得出。未来如本表与 registry events 冲突，以通过 integrity check 的 registry 和 raw run evidence 为准，并通过追加 correction 更新本文，不得直接改写历史。

## 1. 先固定“实验”“运行”和“证据”的含义

为防止把五个 seed、一次失败重跑或一组超参数冒充多个重大实验，使用六层对象：

| 对象 | 含义 | 是否计入 30+ |
|---|---|---:|
| `PlannedSlot` | 本文预算矩阵中的待办位置；未冻结 experiment card | 否 |
| `Experiment` | 一个预先写明假说、已知失败、最小结构改动、可证伪预测和决定规则的科学比较 | 只有 `count_eligible=true` 且完成决定后计 1 |
| `Attempt` | 一个冻结 candidate/config/code/benchmark hash 后的执行尝试 | 否 |
| `Run` | 一个不可覆盖的 runner 调用；可以包含整个 5-seed × W01–W20 矩阵 | 否 |
| `Cell` | 一个 `candidate × world × replicate_seed × split × task/horizon` 原始结果单元 | 否 |
| `Analysis` | 只从冻结 raw 重算的统计、碰撞、Pareto 和决定材料 | 否 |

计数规则：

1. 同一实验的 smoke、screen、full、retry、5 个 seed 和复算分析都只算一个实验。
2. 学习率、层数、隐藏维度、优化器或 seed sweep 整体最多算一个 `optimization_only` 实验，且不计入“至少 20 个非局部调参”。
3. 一个网格的每个格子不能分别登记成实验；网格是同一个实验的一组 attempt。
4. 只有在**第一份 raw 产生前**冻结 experiment card，且最后有 `keep/revert/refine/abandon` 决定，才可计数。
5. 未完成、hash 漂移、缺 seed、缺 world 或隔离未证明的 run 必须保留，但不计入完成数。
6. 四个规定 baseline 是实质运行，但为保守起见**不用于满足 30 个重大候选/消融最低数**。下文另外预留 36 个结构实验槽位。
7. 独立复现、confirmatory rerun 和 post-freeze red-team 是额外强制证据，不靠重复计数凑 30。

## 2. 证据状态机：不能把“跑过”写成“证明了”

### 2.1 Experiment 状态

```text
PLANNED             # 仅预算槽位；不是实验事实，不计数
  -> DRAFT
DRAFT
  -> PREREGISTERED
  -> FROZEN
  -> RUNNING
  -> RAW_COMPLETE
  -> VERIFIED
  -> DECIDED
  -> SUPERSEDED        # 只表示后续已有新版本；旧记录仍有效且不可删除

任一阶段 -> INVALIDATED    # 说明证据为什么失效；不能删掉重来
任一未完成阶段 -> STOPPED  # 预算/方向停止；仍保留
```

`registered_at < frozen_at < first_raw_at` 必须由自动测试验证。产生 raw 后不得修改 hypothesis、falsifier、seed policy、primary metrics、decision rule 或 `count_eligible`。

只有同时满足以下条件，`major_count` 才增加 1：

```text
status == DECIDED
and count_eligible == true
and at least one valid run has raw evidence
and required seeds/cells for the preregistered stage are complete
and decision in {keep, revert, refine, abandon}
```

`PLANNED`、`DRAFT`、`PREREGISTERED`、`FROZEN`、只有代码没有 run、只有 smoke 没有卡片要求的证据、`INVALIDATED` 和 `STOPPED` 都不计。失败候选在有效证据和正式 `revert/abandon` 决定后可以计一个已完成实验；无效 harness run 不可以。

### 2.2 三类失败必须分开

| 类别 | 例子 | 可以得出的结论 |
|---|---|---|
| `RUN_INVALID / HARNESS_INCOMPLETE` | 隔离未启动、raw 缺失、benchmark hash 漂移、oracle judge 崩溃、源码快照缺失 | 本 run 不能用于架构裁决；**不等于候选假说失败** |
| `CANDIDATE_HARD_FAIL` | 经有效隔离 run 证明未来泄漏、非共享状态、危险碰撞、干预语义错误 | 淘汰该冻结候选；平均分不能补偿 |
| `SCIENTIFIC_FAIL` | 合规且可运行，但被支配、样本效率差、扩展代价过高或表示假说无效 | `revert/refine/abandon`，保留完整证据 |

尤其不能再把“报告/重放包自洽”升级成“候选能力成立”，也不能因 harness 缺证据就宣布表示假说失败。

## 3. 目录与不可覆盖 artifact bundle

只在新轨道写入：

```text
research/unified_map/
  EXPERIMENTS.md
  registry/
    events.v1.jsonl                 # 唯一手写/追加事实源
    head.v1.json                    # 派生的当前链头
    schemas/*.schema.json
    preregistrations/EXP-*.json
    reviews/AR-*.md
    counterexamples/CE-*.json

prototype/unified_map/experiment/
  registry.py
  runner.py
  aggregate.py
  integrity.py
  pareto.py

tests/unified_map/
  test_registry_*.py
  test_run_bundle_*.py
  test_statistics_*.py
  test_cadence_*.py

results/unified_map/
  runs/<run_id>/
  objects/sha256/<digest>            # 大 checkpoint/source bundle 的内容寻址对象
```

一次 run 的最低 bundle：

```text
results/unified_map/runs/<run_id>/
  preregistration.json              # experiment card 的冻结副本
  run-manifest.json                 # 身份、scope、expected cells、状态
  candidate-manifest.json           # family/state/base CandidateMethod 能力声明；无 OOD/readout head 元数据
  config.canonical.json
  provenance.json                   # Git、环境、依赖、隔离、时间
  source-manifest.json              # 逐文件 path/bytes/SHA-256
  benchmark-freeze-manifest.json    # benchmark v1 的冻结副本/引用
  seeds.json                        # replicate tuple 与 commit/reveal 记录
  raw/
    <world>/<replicate>/episodes.jsonl.zst
    <world>/<replicate>/predictions.jsonl.zst
    <world>/<replicate>/states.jsonl.zst
    <world>/<replicate>/events.jsonl.zst
    <world>/<replicate>/stdout.log
    <world>/<replicate>/stderr.log
  compliance/checks.json
  compliance/access-trace.jsonl.zst
  collisions/dangerous.jsonl.zst
  collisions/false-splits.jsonl.zst
  failures/trajectories.jsonl.zst
  resources/telemetry.jsonl.zst
  aggregate/metrics-by-cell.jsonl.zst
  aggregate/metrics-by-world.json
  aggregate/metrics-by-seed.json
  aggregate/summary.json
  aggregate/pareto-vector.json
  integrity/hashes.json
  COMPLETE.json | INCOMPLETE.json
```

原始输出要求：

- 保存诊断分布、自然轨迹分布、每个允许动作/动作序列的反事实分布、真实动作后的更新、utility/regret 组成项，不只保存最后标量。
- 保存每个时点实际传给 `diagnose` 与 no-op/A/B/C `rollout` 的同一 `state_id/state_hash`、状态 blob 的内容 hash、canonical byte length 和结构摘要；OOD 仅由 parent 对这些 rows 投影。
- 保存 timeout、NaN、异常、拒绝、OOM、非收敛和缺失 cell；不能只保存成功样本。
- “最坏病例”必须由冻结规则从全部 raw 自动选出，不能人工挑选。
- checkpoint/训练数据索引/预处理器/adapter 都算 candidate artifact；只给 Git commit 而不保存 dirty/untracked 内容不够。
- canonical JSON 是权威元数据；Parquet/图表只是可重建派生物。

### 3.1 原子发布和中断

1. `run_id` 目标和同名 lock 使用 exclusive create；已存在即失败。
2. runner 先写同文件系统 staging；完成后写 `integrity/hashes.json`，最后原子 rename。
3. hash root 覆盖除 `integrity/hashes.json` 和终态 marker 外的所有 path+bytes；终态 marker 再由 registry event hash 覆盖。
4. 进程崩溃时 staging 不删除，恢复工具将其发布为 `INCOMPLETE`；重跑必须取得新 `run_id` 并写 `retry_of`。
5. `COMPLETE.json` 出现后任何 byte 改变都使 integrity test 失败；修正分析只能新建 analysis/run，不能回写。

## 4. Registry：目标是“不能静默作弊”，不是虚构 WORM

本地 Git + SHA-256 只能做到**篡改可检测**，不能宣称对拥有整个磁盘和 Git 历史的人密码学不可篡改。真实不可抵赖还需外部 remote/tag/signature anchor。仓库内最低方案：

1. `registry/events.v1.jsonl` 只追加事件；每个事件含 `seq`、`prev_event_hash`、`payload_hash`、`event_hash`。
2. `event_hash = SHA256(canonical_json(event_without_event_hash))`；首事件的 `prev_event_hash` 为固定零 hash。
3. 每个 milestone 把链头写入 Git commit；若有远端/签名能力，再记录 remote commit/tag/signature。
4. CI 从头重放事件链、重建 experiment snapshot、核对每个 artifact Merkle/root hash；删除、重排、改写都失败。
5. `head.v1.json`、Markdown 表和 Pareto 表全部是派生视图，不能反过来覆盖事件源。
6. 注册失败、run invalid、hard fail 和 abandon 事件都不能删除；允许追加 correction 事件并指向被纠正事件。

建议事件类型：

```text
benchmark.semantic_frozen
train5.precommitted
experiment.registered
experiment.frozen
run.allocated
run.completed
run.incomplete
analysis.verified
decision.recorded
counterexample.frozen
architecture_review.recorded
candidate.panel_sealed
eval5.committed
corpus.sealed
confirmation.finalized
eval5.revealed
redteam.frozen
artifact.invalidated
correction.appended
```

## 5. Experiment card 和 run manifest 最低 schema

### 5.1 Experiment card

```json
{
  "schema_version": "ucm-experiment-card/1",
  "experiment_id": "EXP-005",
  "title": "...",
  "family_id": "manual-mechanism-state",
  "parent_experiment_id": null,
  "change_class": "architecture_family",
  "count_eligible": true,
  "local_adjustment_streak": 0,
  "hypothesis": "...",
  "known_failure": ["W04 treatment-response aliasing"],
  "architecture_delta": "...",
  "predicted_improvements": ["..."],
  "predicted_regressions": ["..."],
  "falsifier": ["..."],
  "state_contract": {
    "state_schema_hash": "sha256:...",
    "update_semantics": "recursive",
    "diagnose_rollout_receive_history": false,
    "task_specific_latent": false
  },
  "planned_stages": ["contract", "screen-b1", "full-b1-if-gated"],
  "primary_metric_ids": ["..."],
  "hard_gate_policy_hash": "sha256:...",
  "noninferiority_policy_hash": "sha256:...",
  "seed_policy_id": "dev5-v1",
  "compute_budget_id": "matched-v1",
  "decision_rule": {"keep": "...", "revert": "...", "refine": "...", "abandon": "..."},
  "next_experiment_by_outcome": {"supported": "...", "refuted": "...", "inconclusive": "..."},
  "registered_at_utc": "...",
  "frozen_at_utc": null
}
```

卡片冻结前必须回答：改动要修哪个已知失败；什么观测会证明只是参数问题；什么观测会杀死表示假说；若结果不显著，下一项信息增益最高的实验是什么。

### 5.2 Run manifest

```json
{
  "schema_version": "ucm-run/1",
  "run_id": "UCM-B1-EXP005-full-<UTC>-<nonce>",
  "experiment_id": "EXP-005",
  "attempt_index": 1,
  "retry_of": null,
  "evidence_tier": "development|decision_grade|confirmatory|reproduction|redteam",
  "stage": "contract|screen|full|extension|redteam",
  "candidate_id": "...",
  "candidate_family": "...",
  "benchmark_id": "ucm-benchmark-v1",
  "benchmark_freeze_hash": "sha256:...",
  "panel_id": "W01-W20/full-v1",
  "world_ids": ["W01", "...", "W20"],
  "replicate_ids": ["R0", "R1", "R2", "R3", "R4"],
  "expected_cell_count": 100,
  "completed_cell_count": 0,
  "hashes": {
    "candidate_code_bundle": "sha256:...",
    "candidate_manifest": "sha256:...",
    "adapter_code": "sha256:...",
    "config": "sha256:...",
    "runner_code": "sha256:...",
    "evaluator_code": "sha256:...",
    "public_generator": "sha256:...",
    "sealed_oracle_commitment": "sha256:...",
    "dependency_lock": "sha256:...",
    "environment": "sha256:..."
  },
  "git": {"commit": "...", "dirty": false, "status_digest": "sha256:...", "patch_digest": null},
  "isolation": {"mode": "...", "candidate_view_only": true, "oracle_in_parent": true},
  "status": "allocated"
}
```

`expected_cell_count` 实际还要乘任务、horizon、action query；上例 100 只表示最外层 world×replicate，不能被误读为全部 query 数。完整性由冻结的 `expected-cells.json` 精确枚举，不靠一个计数猜测。

## 6. ID、hash、源码和环境规则

### 6.1 ID

- `experiment_id` 单调分配且永不复用：`EXP-001`。
- `run_id` 建议：`UCM-<benchmark>-<experiment>-<stage>-<UTC-microseconds>-<128bit nonce>`。
- 名字只方便人读；身份由 manifest hash 决定。run_id 不编码结果、赢家或 PASS。
- state identity 使用候选的 canonical state serialization 生成 `state_hash`；同一 cut 的 base `diagnose` 与所有 `rollout` plan 必须接收完全相同 bytes/hash。

### 6.2 Hash 覆盖

决定级 run 至少冻结并保存：

1. benchmark spec、W01–W20 generator、oracle、split、metric、hard-gate、collision policy；
2. candidate core、state serializer、`initialize/update/diagnose/rollout`、训练代码、预处理、adapter；post-seal extension worker 的 source/config/artifact 另行封印；
3. config 的 canonical bytes；
4. 依赖 lock、Python/平台/CPU/GPU/BLAS/CUDA/线程数和 deterministic flags；
5. training/validation/test data manifest 与 seed derivation；
6. runner/judge/aggregator/statistics 代码；
7. source tree 的逐文件清单和可复现 archive。

Git commit 只是一个索引。若 worktree dirty，必须保存 exact patch、untracked file bytes 和完整 source bundle；否则该 run 不能升为 `decision_grade`。benchmark 冻结本身不得依赖 dirty 状态。

### 6.3 Canonical config

- JSON key 排序、UTF-8、禁止 NaN/Infinity、数值/单位显式、schema version 固定。
- 默认值在 hash 前全部 materialize；环境变量和 CLI override 必须写入 config。
- 同一 config/hash 在 seed 间不得变化；runner 在每个 cell 开始前复核。
- 发现中途 drift：发布 `INCOMPLETE`，不得把前后 cell 拼成一个有效 run。

## 7. 五 seed 公平协议

### 7.1 一个 replicate 不是一个含糊的整数

semantic freeze 只冻结两种 closed tuple schema、各五个 replicate、用途域隔离的 KDF/PRNG、zipped one-to-one pairing 与时序；它不包含任何实际 tuple、raw seed 或 panel digest：

```text
# TRAIN5-v1 schema
model_initialization_seed
training_data_seed
training_order_seed

# EVAL5-v1 schema
world_process_noise_seed
observation_schedule_seed
evaluation_episode_seed
analysis_seed  # 只用于 bootstrap，不能影响模型输出
```

code-owned `FROZEN-v1` 后、任何 finalist 训练前，`TRAIN5_PRECOMMIT.json` 才发布五个 actual training tuple/digest。至少三个不同 family 各自五个 source/config/model artifact 全部 seal 后，才允许 commit 隐藏 EVAL5；五个 TRAIN5 artifact 与五个 EVAL5 replicate 按冻结 ID 顺序 zipped 配对，不得展开为 5×5。实际 tuple 由冻结 derivation 函数在各自 authority 阶段生成并进入 post-freeze evidence chain。确定性候选可把不适用训练项记录为 `not_applicable`，但仍须在五个独立 EVAL5 replicate 上运行。

### 7.2 三套 seed，不混淆证据地位

1. `DEV5-v1`：公开、固定；用于 30+ 搜索，结果是 development evidence。
2. `CONFIRM5-v1`：严格执行 `semantic freeze → TRAIN5_PRECOMMIT.json → 至少 3 family × 5 candidate seals → EVAL5 commit → corpus seal → isolated execution/finalization → reveal`；所有候选共享同一五-replicate hidden corpus，用于 W01–W20 confirmatory comparison。
3. `REPRO5/REDTEAM5-v1`：独立实现和 post-freeze red-team 的新 commitment/reveal；不得回流调参后仍称独立验证。

commit/reveal 不能阻止未来所有研究者看到 seed，但能证明本轮 candidate snapshot 先于 EVAL5 commit/reveal。TRAIN5 actual values 也只能出现在 `FROZEN-v1` 后的 precommit，不得回填 semantic scope。候选修改后必须新建 experiment；不能继续引用旧 confirmatory 地位。

### 7.3 禁止 seed cherry-pick

- 五个 replicate 全部是 required；失败 seed、OOM、NaN 也进入 raw 和稳定性统计。
- 不得“补一个表现正常的新 seed”替换失败 seed。
- 缺任一 required cell 时 run 为 incomplete；完整重跑使用新 run_id。
- 每个 candidate 使用同一 episode/action/horizon manifest，支持 paired comparison。
- 调试 seed 与 test seed 分开；任何 candidate 根据 frozen test 输出改动，下一结果降为 development，不能称 confirmatory。

### 7.4 数据、调参和计算预算公平性

- 所有候选读取同一 public history/event schema、同一 train/validation generator manifest 和同一 evaluation episode/action/horizon manifest；candidate adapter 只能做格式转换，不能补医学/世界语义。
- 主要选择使用 `compute-matched-v1`：冻结训练轨迹数、validation 查询次数、超参数尝试上限和总 wall/GPU/CPU 预算。另可提供 `family-native-unconstrained` 作为能力参考，但不能与 matched track 混成一个赢家结论。
- 所有 hyperparameter attempt 都进入 registry；不能只登记最佳尝试。选择规则只能读 validation，frozen test 不参与 early stopping、模型选择或 threshold 调整。
- 非学习方法的求解调用、手工结构构建时间和 domain commitments 同样计成本；神经模型的预训练、checkpoint、搜索预算也不能藏在 run 外。
- family-specific solver/representation 是允许的，但 companion layer、preprocessor、cache、ensemble member 和 task head 全部进入 code/state/parameter/latency/extension 账本。
- separate-task baseline 同时报 aggregate-capacity-matched 与 best-effort reference；前者用于公平 noninferiority，后者说明放弃共享约束可达到的上界，二者不得混称一个 baseline。

## 8. 每个实验的固定执行循环

```text
0. REGISTER
   写 hypothesis / known failure / architecture delta / falsifier / decision rule。

1. FREEZE
   冻结 card、candidate/config/source/benchmark hash；验证没有 raw 先于 freeze。

2. CONTRACT GATE
   跑 schema、共享状态、无历史旁路、无未来/真状态/test-id、更新 API、可重放单测。
   失败则停止评分；先判 run invalid 还是 candidate hard fail。

3. MINIMAL COMPLETE CHANGE
   只实现卡片声明的最小结构改动；额外改动自动使 attempt invalid，需新卡片。

4. SCREEN-B1
   跑 benchmark v1 冻结的统一小面板，不得按候选临时挑“擅长世界”。
   同时包含已知失败的定向 probe，但该 probe 必须在卡片冻结前列出。

5. FULL-B1 GATE
   满足冻结门槛才进入 W01–W20；最低三名候选的 confirmatory full run 另有强制规则。

6. RAW VERIFY
   核对 expected cells、hash、isolation trace、同一 state hash、seed、成本、summary 可重算。

7. ANALYZE
   逐 world/seed/task 报告；碰撞、regret、OOD、最坏轨迹、false split、更新一致性和成本。

8. DECIDE
   按预注册规则选择 keep/revert/refine/abandon；不允许以事后总分解释。

9. NEXT INFORMATION GAIN
   登记下一实验；若到 5/10 实验 cadence 边界，先完成反例/架构复盘才能继续。
```

建议证据 tier：

| Tier | 最低要求 | 能否进入最终 Pareto |
|---|---|---:|
| `diagnostic` | 单元/smoke，可 in-process | 否 |
| `development` | 隔离 screen/full + DEV5 | 只能用于搜索 |
| `decision_grade` | W01–W20、5 seed、完整 raw、所有合规门 | 是 |
| `confirmatory` | FROZEN→`TRAIN5_PRECOMMIT.json`→至少 3 family×5 seals→EVAL5 commit/corpus/finalize/reveal 的 CONFIRM5 | 是，优先 |
| `reproduction` | source-distinct 独立实现 + 新 seeds | 是，单列 |
| `redteam` | candidate freeze 后新反例/扩展 | 是，不能回写 v1 |

## 9. 五 seed 聚合和置信区间

### 9.1 先聚合 cell，再聚合 world，最后才跨 world

1. 每个 `world × seed × task × horizon/action` 先独立算 metric。
2. 每个 world 等权形成 macro；不能让 episode 多的简单世界淹没 W19 等稀有灾难世界。
3. 同时保留 episode-weighted 值作敏感性分析，但不替代 world-macro。
4. utility/regret 同时报告原生单位、冻结的 world-normalized 值、mean/median/p95/max/CVaR；平均 regret 不能掩盖方向相反治疗或罕见灾难。
5. 所有 raw seed 值在 finalization 后按 reveal protocol 展示并进入 run evidence；它们不得写入 semantic freeze/scope。只写均值属于不完整报告。

### 9.2 主 CI 与敏感性 CI

W01–W20 是固定 benchmark，不假装是从“所有临床世界”随机抽样。主不确定性分两层报告：

- `seed_CI95`：先得到五个 seed-level world-macro 值，再用 `t(df=4)` 区间；同时报告 min/max。它反映训练/过程随机稳定性，五 seed 很少，区间宽应如实保留。
- `paired_delta_CI95`：候选与 baseline 使用相同 replicate，针对五个 seed-level paired delta 用 `t(df=4)`；这是 noninferiority/优势比较的主区间。
- `episode_CI95`：在每个 `world×seed` 内对 episode 分层 bootstrap，再按冻结规则汇总；反映有限 episode 噪声。
- `hierarchical_bootstrap_CI95`：固定 20 个 world，不重采 world；重采 seed cluster 和各 world 内 episode，至少 10,000 次，作为敏感性分析。
- `world_resampled_CI95`：若做，必须标记为 exploratory super-population sensitivity，不能冒充对真实临床世界的外推。

对 bounded event rate 可附 Wilson/Clopper–Pearson exact interval。零次灾难不等于零风险，必须同时报告暴露数和 exact upper bound。W19 出现一次冻结定义的 catastrophic contraindication failure 即触发 hard gate，CI 不能补偿。

### 9.3 校准、OOD 和多重比较

- 诊断和 trajectory distribution 用冻结 proper scoring rule、calibration curve/ECE/Brier/NLL；不能只报 top-1 accuracy。
- OOD 报 AUROC、AUPRC、固定覆盖率下的 false-known rate、选择性风险和校准；类别比例必须冻结。
- 不用大量未校正 p-value 选赢家。开发阶段 CI 标记 exploratory；top-3 同时冻结后的 confirmatory comparison 才支持选择性主张。
- 对多 primary objective 的“稳健支配”，使用冻结的 practical-equivalence margin，并报告同时/成对 CI；CI 相交时结论是 `uncertain dominance`，不是随意挑点估计赢家。
- 所有 CI 算法、bootstrap seed、replicate 数和缺失处理在 benchmark v1 冻结；summary 必须可从 raw bit-for-bit 或容差内重算。

## 10. 碰撞、虚假拆分和最坏病例不能被平均掉

每个 valid run 自动生成：

```text
dangerous treatment collisions
natural-history collisions
new-test/new-treatment revealed collisions
false splits under controlled-future equivalence
OOD forced-known cases
largest absolute and standardized regret
worst calibration bins
largest update inconsistency
state-size / latency / memory tails
```

连续表示不得通过任意缩放逃避 collision。候选在运行前声明 canonical state metric/serialization；judge 使用 benchmark 冻结的等价 probe、action-conditional future divergence 和 practical threshold，而不是候选事后选择 epsilon。若两个历史的治疗方向相反却被同一可执行状态/等价类合并，直接 hard fail。

虚假拆分不作为安全 hard fail，但进入 state simplicity/description length：未来在全部允许检查和干预下等价的历史若被拆成大量状态，需要付出 dimension/bytes/active-node/MDL 代价。

## 11. 硬淘汰：先判语义，再谈 Pareto

### 11.1 Candidate hard fail code

failure code 的权威 registry 在 `FORMAL_SPEC.md`。本文件不再创建一套漂移的 `H-*` 别名。任一经有效 harness 证明的下列事件，候选不能进入 Pareto：

| Formal code | 实验层触发摘要 |
|---|---|
| `UCM-F001-FUTURE_LEAK` | 状态产生使用未来观察、真实未来或实际反事实结果 |
| `UCM-F002-ORACLE_TRUE_STATE_ACCESS` | 读取 simulator hidden state/oracle（true-state upper bound 除外） |
| `UCM-F003-TEST_ID_BRANCH` | 按 world/test/case ID、疾病名或预期答案分支 |
| `UCM-F005-TASK_SPECIFIC_STATE` / `UCM-F007-STATE_FANOUT_MISMATCH` / `UCM-F013-SPLIT_TRANSITION_CORE` | 三任务未读取同一状态，或实际维护多套患者 dynamics/state |
| `UCM-F004-HEAD_HISTORY_ACCESS` | head 或治疗 query 绕过 state 重读原始历史 |
| `UCM-F005-TASK_SPECIFIC_STATE` / `UCM-F006-HIDDEN_PATIENT_CACHE` | 保存 task-specific patient latent/cache 作为第二状态 |
| `UCM-F010-UPDATE_NOT_RECURSIVE` / `UCM-F019-UPDATE_INCONSISTENT` | 新观察/动作未通过同一递推更新，或 replay/batch/query-order 不一致 |
| `UCM-F014-ACTION_SEMANTICS_CONFLATED` / `UCM-F015-CONDITIONING_AS_INTERVENTION` | 混淆 no-op/continue/stop/do/planned/performed，或关联冒充干预 |
| `UCM-F016-DANGEROUS_COLLISION` | 治疗反应方向相反/灾难禁忌的患者被危险合并 |
| `UCM-F017-OOD_FORCED_MATCH` | 冻结定义下将未知机制高置信强塞入已知状态 |
| `UCM-F018-FULL_HISTORY_MISCLAIM` | 完整历史记忆器声称紧凑有限状态；诚实标注 full-history baseline 不触发 |
| `UCM-F020-NONREPRODUCIBLE` | exact bundle、环境和 seed 下超出冻结容差且非确定性无法解释 |
| `UCM-F023-RESULT_EVIDENCE_LOSS` | 覆盖旧结果、缺 raw/seed/seal/checksum 或 summary 无法追溯 |
| `UCM-F024-SCOPE_OVERCLAIM` | 新检查/治疗超出旧 scope 却通过测试专属重写继续声称原状态充分 |

若 sandbox、mutation kill、oracle 或 probe 证据不足，应记录 `UCM-E001`–`UCM-E003` 的 `INCOMPLETE`，不能伪装成候选 PASS，也不能直接升级为上述 candidate failure。

自动合规的最低执行方式：

- `initialize(history)` 在 task 未知时只执行一次；base fresh workers 的 `diagnose` 与所有 `rollout` plan 只收到同一只读 state blob 和 query/action。
- head worker 禁止文件、网络、全局 cache、raw history、oracle；访问 trace 归档。不存在 candidate `ood/readout` RPC 或 heads metadata；OOD 由 parent 从同-state rows 精确投影。
- update worker 只收到 `previous_state + new_visible_event/action`，不能收到完整历史；full-history baseline 作为 `reference_only` 单列。
- state serialization 在 `diagnose/rollout` 前后 hash 不变；若有随机读出，随机源显式传入并记录。
- treatment A/B/no-op 在互相隔离的 fresh worker 读取同一 pre-action state。
- 自动扫描只是辅助；“把三套 latent 拼进一个 object”仍需 state schema、field access、post-seal extension-worker novel-readout 和 behavioral-equivalence 审查，接口同名不等于共享语义。W04/base 已有 output bundle 不得改名冒充 novel readout。

### 11.2 不是 hard fail、但会使 run 无效的情况

缺 source bytes、runner crash、judge/oracle bug、sandbox 未证明、raw 不完整、benchmark drift、summary 无法重算都先归 `RUN_INVALID`。只有在同 hash 有效重放仍证明候选行为错误时，才升级为 candidate failure。

## 12. Pareto、noninferiority 和 baseline 规则

### 12.1 进入前沿的资格

候选同时满足以下条件才进入最终 UCM Pareto：

1. 真正共享状态合规，无 hard fail；
2. W01–W20 完整、五 seed、raw/CI/cost 完整；
3. benchmark/candidate/config/seed/analysis hash 均冻结；
4. 至少一次 exact replay 或 source-distinct reproduction 能重建核心结果；
5. 没有把 K0、LLM 整段历史、任务 latent 或 full history 冒充紧凑状态。

`true-state`、`separate-task`、`K0-only` 永远 `reference_only`；`full-history` 可作为无压缩行为基线，但不得凭分数成为“有限紧凑 UCM”赢家。

### 12.2 不做单总分

至少保留以下向量，不允许把安全失败用平均总分洗掉：

```text
diagnostic discrimination + calibration
natural-course distributional prediction
interventional trajectory prediction
mean/tail/max treatment regret
dangerous collision + false split
OOD/open-world behavior
sample-efficiency curve/AUC
new-mechanism/comorbidity composition
online update consistency
post-seal independent-extension novel-task readout
state bytes/dimension/active structure/MDL
new-test/new-treatment extension diff + retraining cost
latency/memory/training compute
interpretability rubric + native mechanism witness
```

同时输出：

- 点估计 non-dominated frontier；
- 按预冻结 practical-equivalence margins 的 uncertainty-aware frontier；
- pairwise paired-delta CI；
- 无法判定支配的候选集合。

候选 A 只有在所有 primary objective 都不差于 B 的冻结容忍区间，且至少一项有超出最小有意义差异的改进时，才称 robustly dominates。若五 seed 不足以判定，写 `uncertain`，不按个人偏好选。

### 12.3 对 separate-task baseline 的硬比较

benchmark freeze 前为诊断、自然预测、干预预测/治疗 regret 分别写 noninferiority margin。共享候选必须：

1. 三任务的 paired CI 均未越过不可接受退化边界；且
2. 在样本效率、跨任务一致性、组合泛化、紧凑性或 candidate-seal 后 independent-extension 新任务迁移中，至少一项 paired CI 超过预定义有意义优势。

否则标记：

- `shared_state_dominated`；或
- `evidence_inconclusive`；

不能因“看起来更统一”强行胜出。

## 13. keep / revert / refine / abandon

决定必须引用 experiment card 的原始假说、paired delta、CI、hard-gate 和 collision artifact：

| 决定 | 允许条件 | 后果 |
|---|---|---|
| `keep` | 无 hard fail；假说按预注册方向成立；进入/扩展 Pareto 或新增不可替代能力 | 该 candidate hash 成为后续可引用 parent |
| `revert` | 最小改动引入 hard fail、明确退化或未修复目标失败 | active lineage 回到 parent hash；artifact 不删除 |
| `refine` | 表示假说尚未被反例杀死，且有预先声明的参数/估计/优化诊断支持可修复 | 下一实验必须具体写修复预测；local streak +1 |
| `abandon` | 表示级反例、持续被支配、扩展需重写核心，或四次连续局部调整无实质进展 | 关闭该方向；只有 10-experiment architecture review 提出新结构假说才可重开 |

“实质进展”定义为：无新增 hard fail，并在卡片指定 target 上越过冻结的最小有意义差异或消除预注册 counterexample；只改善训练 loss、点估计微涨或换 seed 不算。

同一家族同一核心假说连续四个 `optimization_only/local_parameter` experiment 未实质进展，registry 必须拒绝第五个同类注册，要求 `architecture_level_change` 或 `abandon/refocus`。

## 14. 每 5 个实验反例、每 10 个实验架构复盘

registry 维护两个计数：

- `completion_ordinal`：所有已 `DECIDED` 的实验，包括 baseline；用于 5/10 cadence。
- `major_count`：只计 count-eligible 结构/重大消融；用于 30+ 完成门。

### 14.1 Counterexample gate

每当 `completion_ordinal % 5 == 0`：

1. 在下一实验开始前冻结至少一个 `CE-<ordinal>-*`；
2. 记录攻击时的当前 Pareto leader candidate/config/code hash；
3. 写被攻击的状态充分性假说、两个行为可区分历史、允许检查/动作和 oracle；
4. 禁止出现 candidate/test-ID 分支；反例必须实例化一般机制；
5. 在当前 leader、至少一个近邻候选和必要 baseline 上运行；
6. 结果进入 `COLLISIONS.md` 和独立 challenge run，不静默改写 benchmark v1。

开发期反例是 append-only challenge track。candidate freeze 后的 red-team 使用新 seed/参数/oracle，证据地位单独标记。

### 14.2 Architecture review gate

每当 `completion_ordinal % 10 == 0`，必须生成 `AR-<ordinal>.md` 并回答：

1. 当前最强候选的核心假说是什么？
2. 它在哪些世界/反例中失败？
3. 失败是参数/识别/优化问题，还是表示问题？证据是什么？
4. 是否把诊断、预测、治疗偷偷拆成 task-specific state？
5. 是否应回退到受控未来行为等价/充分统计的基础定义？
6. 搜索空间是否缺少新家族？下一 10 个实验如何重新分配？

CI 应有 gate 测试：到达 cadence 边界而缺 CE/AR、leader hash、oracle/hash 或运行记录时，禁止登记下一批。

## 15. 40 项 planned experiment registry（当前完成 0）

下表是**架构级预算地图**，不是冻结 preregistration，更不是宣称这些实现或结果已存在。所有行当前统一为 `status=PLANNED`、`valid_run_count=0`、`decision=null`、`counts_toward_completed=0`。只有单独生成并在 raw 之前冻结 experiment card、完成要求的有效 run/analysis、记录正式决定后，某行才可进入完成计数。最终卡片必须在运行前进一步写明参数域和量化 falsifier；若届时发现更高信息增益路径，允许通过 append-only registry 记录取消/替代，但不能把未跑计划计数。

### 15.1 规定 baseline 计划（不用于凑 30 个重大候选/消融）

| ID | 类型 | 假说/用途 | 关键 falsifier / 限制 |
|---|---|---|---|
| EXP-001 | True-state upper bound | 验证 oracle、evaluator 和任务可解上限 | 仍远离 oracle 表示 harness/oracle 错；只作不可部署上界 |
| EXP-002 | Full-history baseline | 允许历史全保留时，行为充分性能达到什么水平 | 记录 bytes/latency；不得声称压缩状态 |
| EXP-003 | Separate-task baseline | 测量不共享状态时三个任务各自最佳参考 | 天生不合规，只用于 noninferiority/优势比较 |
| EXP-004 | K0-only negative control | 证明控制面/接口不能替代患者世界状态 | 若动态任务异常高分，先怀疑泄漏或 evaluator；通过独立 subprocess 调用，不让 UCM import K0 语义代码 |

### 15.2 36 个结构实验计划槽位（其中最多 35 个可在实际完成后 count-eligible）

| ID | 家族/结构改动 | 主要假说 | 首要攻击点/杀死条件 |
|---|---|---|---|
| EXP-005 | 人工机制 point vector | 小型显式机制向量足够统一三任务 | W02/W11 后验多峰或 W04 相反治疗被 point state 合并 |
| EXP-006 | 人工机制 probability/belief vector | 同一机制变量的 posterior distribution 修复点估计碰撞 | 状态仍不能保留动作条件分歧，或尺寸随历史无界增长 |
| EXP-007 | 经典 DBN/latent SSM belief | Bayes belief 是部分可观察系统的共享充分状态 | W13/W14/W20 结构错配导致系统性碰撞 |
| EXP-008 | switching/hybrid POMDP belief | 离散病程型 + 连续生理 belief 处理模式切换 | 新机制/新治疗必须全局重建，或 mode aliasing |
| EXP-009 | finite controlled PSR | 对未来 tests/actions 的预测本身可作为 state | W16/W17 加测试/治疗后旧 PSR 无法局部细化 |
| EXP-010 | kernel/nonlinear controlled PSR | 非线性 predictive tests 能处理殊途同归和阈值 | 样本复杂度/状态秩爆炸，W19 tail action response 丢失 |
| EXP-011 | exact causal-state partition（有限世界） | 受控未来分布等价类给出最小行为状态 | 有限样本下不可识别；同类内存在 action divergence |
| EXP-012 | approximate bisimulation state | 容差行为等价可换取紧凑且低 regret 的近似地图 | 小 representation distance 却产生大治疗 regret |
| EXP-013 | dynamic SCM posterior state | 内生状态 + exogenous host posterior 支持诊断与 do() | W15 混杂下仍把关联当干预，或 counterfactual 不可识别却过度自信 |
| EXP-014 | SCM abduction-action-prediction state | 保留个体外生 posterior 能支持同患者反事实和更新 | posterior 不能在线递推，或 W20 治疗历史丢失 |
| EXP-015 | fixed-dictionary controlled Koopman | 动作算子在线性 lifted state 中统一演化/控制 | W13 阈值/新动作使有限 dictionary 崩溃 |
| EXP-016 | learned nonlinear Koopman dictionary | 学习 observables 可压缩非线性共同动力学 | 只拟合观察相关，不保留治疗方向；extension 需重训全部核心 |
| EXP-017 | RSSM shared stochastic state | 单一 deterministic+stochastic belief 支持三头和递归更新 | head 私有 latent/hidden cache，或 W19 mode collapse |
| EXP-018 | neural ODE/SDE filtering state | 连续时间 belief 处理异步、延迟和多尺度 | W08 acquisition-time 泄漏/混淆，W14 path dependence 丢失 |
| EXP-019 | Bayesian reaction/mechanism network | 局部机制节点 + 反应动力学可解释且可组合 | W11 多机制 posterior 或 W13 非加性交互失败 |
| EXP-020 | learned graph dynamical system | 可学习边修复手工网络缺失同时保留共享 state | 图 attention 每次重读历史或新组合产生不稳定捷径 |
| EXP-021 | symbolic-neural residual hybrid | 显式机制负责 do()，共享 residual 修复模型错配 | residual 吞掉因果语义，关闭 residual 后能力完全消失 |
| EXP-022 | typed program-state/rewrite dynamics | 可执行机制程序可作为更新、预测、干预的同一 state | query-specific rewrite/callback 隐藏第二状态或状态爆炸 |
| EXP-023 | bounded recurrent attention state | attention 只在 update 时压缩到固定 state，可处理长历史 | query 时重读 memory/history；W14/W20 超出窗口即碰撞 |
| EXP-024 | dynamically expandable memory state | 必要时增长结构比固定向量更适合新检查/新治疗 | 增长退化为完整历史，false split/bytes 无界 |
| EXP-025 | action-conditional information bottleneck | 最小化状态同时保留受控未来可降低 false split | bottleneck 优化平均 loss，牺牲 W19 稀有禁忌 |
| EXP-026 | nonparametric Bayesian latent-state model | 状态数可随新机制增长且保留不确定性 | OOD 被吸入旧簇，或新簇增长导致不可控 false split |
| EXP-027 | distribution over structural hypotheses | 保留多种机制图 posterior 可修复 W11/W18 epistemic uncertainty | ensemble 只是多个任务模型包装，或无法定义单一可更新 state |
| EXP-028 | factored/compositional controlled state | 因子状态 + 局部 action operator 支持新共病组合 | W13 非线性交互需要 case-specific cross-factor patch |
| EXP-029 | action-conditioning structural ablation | 比较去掉 action history/operator 后是否立即破坏统一性 | W04/W17/W20 不下降则检查任务是否真正测试干预 |
| EXP-030 | posterior-to-point collapse ablation | 测量 distributional state 是否为共享充分性的必要部分 | 若无退化，复杂 posterior 可能是虚假拆分/多余成本 |
| EXP-031 | observation-channel collapse ablation | 显式区分内部状态和 measurement channel 是必要的 | W06/W07 不退化则 benchmark/候选可能偷看内部状态 |
| EXP-032 | time/lag removal ablation | event/acquisition/availability time 与 lag state 是必要的 | W08/W14/W20 不退化则时间任务判别力不足 |
| EXP-033 | host-baseline/context removal ablation | baseline/host modifier 必须进入同一 state 而非额外 head | W09/W12/W19 不退化则模型可能使用旁路 context |
| EXP-034 | additive-comorbidity ablation | 非线性交互结构对 W13 和新组合必要 | 加法模型等价说明复杂结构未提供证据或 W13 太弱 |
| EXP-035 | finite-window vs recursive path-state | 哪些历史必须保留可由 W14/W20 行为差异确定 | 窗口外历史改变未来却 state 不变；或递归 state 只是原史缓存 |
| EXP-036 | fixed schema vs local refinement | 新检查/新治疗应局部 split state，而非重建全核心 | W16/W17 加扩展导致全量重训/旧状态不可迁移 |
| EXP-037 | private-latent compliance mutant | 验证 shared-state checker 能杀死“一个容器三套 latent” | 若未被 hard gate 杀死，harness incomplete；本项可保守不计重大完成数 |
| EXP-038 | post-seal extension-worker novel-readout transfer | 真共享 state 应支持独立 extension worker 从 sealed state 学到训练时未见的新读出且不重读历史；W04/base 已有 bundle 不计 novel | 新任务只能靠 raw history/重训 encoder，或只是重命名既有输出；表明 state 不充分或实验无效 |
| EXP-039 | compositional operator ablation | 结构化 operator 而非容量带来新共病组合泛化 | 打乱/移除 composition law 后不退化，说明组合主张未证实 |
| EXP-040 | single-scale vs hierarchical multi-timescale state | 同一 state 能稳定支持 1h/24h/7d，而非每 horizon 私有 latent | state 随 horizon 线性膨胀或某尺度出现系统性 collision |

即便保守排除 EXP-037，预算仍预留 35 个可能 `count_eligible` 的结构候选/消融槽位，超过 30；它们都不是单纯学习率/层数/隐藏维度调整。这里的 `35` 是搜索预算容量，**当前完成数仍是 0**。

## 16. Full benchmark、top-3、独立复现和 red-team

### 16.1 至少三名真正 UCM 候选跑满

搜索完成后，按 development Pareto 和结构多样性冻结至少三名：

- 来自至少三个不同 `family_id`；
- 都通过 shared-state/leakage contract；
- `FROZEN-v1` 后先绑定同一 `TRAIN5_PRECOMMIT.json` 训练；各 family 五个 candidate/config/code/model artifact 全部 seal 后才 EVAL5 commit，并只在 corpus seal、执行和 finalization 后 reveal；
- 每名都运行 W01–W20 × 5 replicate × 全 task/action/horizon；
- 不以 baseline、同一家族三个 hidden-size 变体或 invalid mutant 凑数。

若不足三个合规家族，不能降低门槛，目标仍未完成；应新增家族/修复 harness。

### 16.2 最强候选独立实现

winner freeze 后创建 `REPRO-*`：

1. 独立实现者只拿 formal state/update/readout spec 和 public candidate protocol；
2. 禁止 import/copy 原候选源码、checkpoint、private cache；做 source-distinct hash/import audit；
3. 使用新实现路径/数值库或不同算法实现同一核心语义；
4. 用 `REPRO5` 跑完整 W01–W20；
5. 原结果和复现结果分别报告，不能把“共同读同一旧库”称独立复现。

### 16.3 Freeze 后 red-team

在 winner/top comparators hash 冻结后才 materialize：

- 新检查拆分；
- 新治疗相反效应；
- 新非线性共病组合；
- candidate seal 后的独立 extension-worker 新任务读出（W04/base 已有 bundle 不得计 novel）；
- 历史删除；
- 1h/24h/7d；
- 新 OOD 机制、罕见灾难禁忌、观察通道干预和隐藏混杂；
- task latent、cache、query 重读历史、test-ID 分支等作弊攻击。

red-team 不修改 benchmark v1。失败后允许建立 v2/新 candidate，但原 frozen failure 必须保留，且修复后的结果不再具有原始盲测地位。

## 17. 最低自动测试清单

未来实现 registry/runner 时至少添加：

```text
test_registry_hash_chain_and_monotonic_seq
test_registry_correction_is_append_only
test_run_id_exclusive_create_and_no_overwrite
test_atomic_publish_preserves_incomplete_attempt
test_manifest_hash_covers_source_config_runner_benchmark
test_dirty_commit_without_source_bundle_not_decision_grade
test_freeze_timestamp_precedes_first_raw
test_benchmark_v1_drift_requires_new_version
test_expected_cells_exactly_match_raw
test_five_seed_panel_has_no_replacement_or_drop
test_candidate_hash_constant_across_cells
test_summary_and_ci_recompute_from_raw
test_hard_fail_never_enters_pareto
test_invalid_harness_does_not_become_candidate_failure
test_reference_only_baselines_cannot_win_ucm
test_same_state_hash_reaches_diagnose_and_all_rollout_plans
test_diagnose_rollout_update_and_extension_cannot_read_raw_history_or_cache
test_oracle_true_state_future_and_test_id_are_unreadable
test_counterexample_required_after_each_five_decisions
test_architecture_review_required_after_each_ten_decisions
test_fifth_local_no_progress_tweak_is_rejected
test_top3_are_distinct_families_full_w01_w20_five_seeds
test_confirm_authority_chain_freeze_train5_precommit_3x5_seals_eval5_commit_corpus_finalize_reveal
test_independent_reproduction_is_source_distinct
test_redteam_artifacts_do_not_rewrite_benchmark_v1
```

## 18. 推荐实现顺序（仍不运行候选）

1. 等 `benchmark_v1` 的 world/oracle/metric/hard-gate schema 定稿，填充本文件中的 policy hash 引用；不得保留可事后解释的 `TBD` 门槛。
2. 先实现 registry event schema、hash chain、run bundle schema、atomic publisher 和 raw re-aggregation verifier。
3. 用 honest/cheating/degenerate **harness fixtures** 验证 hard gate，不把它们算候选实验。
4. 先完成 benchmark v1 semantic freeze；该 freeze 只绑定 TRAIN5/EVAL5 protocol/schema/五-panel/zipped/timing，不含 raw seed/panel digest。`FROZEN-v1` 后再发布 `TRAIN5_PRECOMMIT.json` 并启动实验；只有至少三个 family×五 artifact seal 后才建立 EVAL5 commitment、corpus seal、finalization 与 reveal chain。
5. 所有实验按固定循环运行；先保留失败 raw，再决定，不“清理”历史。
6. 每五/十次 cadence gate 由 CI 强制，不靠人工记忆。

## 19. 当前证据状态与禁止声明

- 没有任何候选已实现或已运行；
- 重大实验完成账本是 **0/30**；`EXP-001`–`EXP-040` 只是 planned slots，一个都不能计为完成；
- 没有 winner、Pareto 前沿或有限 UCM 存在性结论；
- 五 seed 只支持冻结合成 benchmark 内的稳定性估计，不支持真实临床有效性；
- hash 链是仓库内篡改检测，不是外部签名 WORM；
- K0 的历史结果只提供原子发布/hash/隔离模式经验，不能提供 UCM 动力学证据。

## 20. FROZEN-v1 executable experiment ledger

> 本节从 commit `9d0608f` 的 executable freeze 后开始，覆盖第 15 节未冻结的
> 计划编号。机器 run bundle 中的 `experiment_id` 是唯一实际编号；第 15 节保留为
> 历史搜索预算，不得用其旧含义重解释以下 raw results。

### 20.1 Shared execution contract

本批 11 个 screening 全部使用：

```text
freeze_root: sha256:8acb6623c2fdf79008240c5f5967b2143c4fb5e7bb87a4e8aa9f72e77ef33a2d
worlds: W01,W04,W08,W15A,W15B,W18,W19,W20 (7 slots / 8 panels)
replicate: R01
train/test: 12 / 6 episodes per panel
pair probes: 19 per run
runner+candidate source digest: sha256:c04704383c297696f7b2e545b9bccd18afa5f9d63f19ab3ca54cd7e72b6a3323
raw custody: each run has manifest.json, summary.json, raw-episodes.jsonl, raw-pairs.jsonl
status: screening only; none may be called complete W01-W20 benchmark
```

每个 ordinary family 的 patient state 由一个 public-history accumulator 产生；
diagnosis 和所有自然/治疗 rollout 只收到同一 `SharedPatientState`。这次共同的
accumulator 本身被 W08 反例杀死，因此“八个 transform/head 不同”不能被夸大为
八个端到端充分的地图；下一批必须改变 history-to-state architecture。

### 20.2 Results

| Experiment | Family / hypothesis | diag acc | natural RMSE | intervention RMSE | regret | mean bytes | dangerous collision | unsafe OOD | false split | decision |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| EXP-001 | F01 hand mechanism vector：固定显式统计足够 | .786 | .326 | .373 | 2.401 | 2,184 | 1 | 2 | 3 | refine |
| EXP-002 | F02 Gaussian belief：posterior 修复 point alias | .679 | .369 | .556 | 1.141 | 1,791 | 4 | 2 | 1 | abandon v1 |
| EXP-003 | F03 controlled predictive state：低秩 future-test state | .786 | .326 | .375 | 2.384 | 2,026 | 1 | 2 | 3 | refine |
| EXP-004 | F04 causal-state clustering：行为 quotient 更低 regret | .702 | .320 | .359 | **.680** | 1,912 | 1 | 2 | 3 | keep/refine |
| EXP-005 | F05 dynamic SCM interactions：显式 host/action interaction | .738 | .262 | .301 | 2.501 | 2,081 | 1 | 2 | 3 | refine action semantics |
| EXP-006 | F06 polynomial Koopman：lift 改善 rollout | .738 | **.207** | **.266** | 1.748 | 2,306 | 1 | 2 | 3 | keep/refine |
| EXP-007 | F07 single neural latent：非线性共享 state | .714 | .280 | .351 | 2.828 | 2,371 | 1 | 2 | 3 | abandon shallow ELM |
| EXP-008 | F08 mechanism graph：fixed local message passing | .690 | .268 | .335 | 2.158 | 2,392 | 1 | 2 | 3 | abandon fixed ring |
| EXP-009 | B02 full visible history：无压缩信息基线 | .786 | .326 | .373 | 2.401 | 4,084 | **0** | 2 | 6 | keep baseline only |
| EXP-010 | B03 separate-task state：不共享参考 | .786 | .326 | .373 | 2.401 | 2,913 | 1 | 2 | 3 | keep illegal comparator |
| EXP-011 | B04 K0-only：控制面不能替代患者地图 | .548 | .383 | .571 | 1.013 | 1,779 | **5** | 2 | 0 | keep negative control |

所有 run 的 `update_replay_failure_count=0`、`query_order_failure_count=0`；
它们只证明实现的递归/查询纯度 smoke gate，不抵消 collision/OOD hard failure。

### 20.3 Fixed-loop cards

#### EXP-001 — F01 mechanism vector

- 假说/已知失败：少量 last/mean/slope/exposure 机制统计应区分 W04/W19。
- 最小改动：87 维公共 accumulator 直接作为 state，所有 heads 用同一 ridge readout。
- 测试/运行：candidate+runner 6 tests green；run
  `20260719T023121Z-EXP-001-7ef593ca2e`。
- 证据：诊断较强，但 W08 exact collision 1、unsafe OOD 2、regret 2.401。
- 决定/下一步：`refine`；加入顺序/availability 递归记忆，而非调 ridge。

#### EXP-002 — F02 Gaussian belief

- 假说/已知失败：显式 posterior 可修复 point-state alias。
- 最小改动：class-conditioned diagonal Gaussian posterior 是唯一 patient state。
- 运行：`20260719T023152Z-EXP-002-cd13333510`。
- 证据：collision 反增至 4，intervention RMSE .556；posterior 坐标没有保留
  action-conditioned future。
- 决定：`abandon v1`；下一版本必须对行为/动作建 posterior，不再仅按 diagnosis class。

#### EXP-003 — F03 controlled PSR

- 假说/已知失败：训练时所有 action/horizon future tests 的低秩预测可直接作为 state。
- 最小改动：ridge 预测完整 test vector，再以 SVD 取最多 24 个 core coordinates。
- 运行：`20260719T023156Z-EXP-003-0bf248e2dc`。
- 证据：与 F01 几乎相同，W08 collision 与 OOD 未修复，说明输入历史压缩先丢信息。
- 决定：`refine`；先修 history state，再研究 core-test rank/new action。

#### EXP-004 — F04 causal-state clustering

- 假说/已知失败：按全部诊断+受控未来行为聚类比表型向量更接近 quotient。
- 最小改动：behavior target k-means，state 为 feature-to-cluster posterior。
- 运行：`20260719T023200Z-EXP-004-892bf558a2`。
- 证据：本批最低 regret .680、状态较小；仍有 W08 collision 1、OOD 2。
- 决定：`keep/refine`；当前 development leader，但 hard gate 未过，不能进 Pareto winner。

#### EXP-005 — F05 dynamic SCM interactions

- 假说/已知失败：last/mean/slope × treatment exposure 显式交互改善 do() 预测。
- 最小改动：64 维 structural interaction state，统一线性 action/horizon heads。
- 运行：`20260719T023205Z-EXP-005-624e359e1b`。
- 证据：forecast 明显改善，但 regret 2.501；观测拟合未变成安全动作选择。
- 决定：`refine`；必须拆 association 与 intervention operator，不调正则补救。

#### EXP-006 — F06 Koopman lift

- 假说/已知失败：固定二次 observable lift 可线性化非线性轨迹。
- 最小改动：base、square、相邻 product 组成 95 维 shared lift。
- 运行：`20260719T023209Z-EXP-006-6897ba5f6f`。
- 证据：自然/干预 RMSE 本批最优，但 regret 1.748、W08 collision、OOD 均失败。
- 决定：`keep/refine`；作为 forecast Pareto 参照，不能称统一地图赢家。

#### EXP-007 — F07 neural world latent

- 假说/已知失败：一个 32 维非线性 tanh latent 可共享三任务。
- 最小改动：seeded random neural encoder + single latent + stateless heads。
- 运行：`20260719T023214Z-EXP-007-4e42aef15e`。
- 证据：regret 2.828 为 ordinary families 最差，仍 collision/OOD。
- 决定：`abandon shallow ELM`；下一 neural 路线必须递归建模 action/observation，不只换非线性投影。

#### EXP-008 — F08 mechanism graph

- 假说/已知失败：局部机制节点/message passing 保留组合结构。
- 最小改动：16 observation nodes 的两轮 ring message passing + exposure nodes。
- 运行：`20260719T023218Z-EXP-008-389cd03a63`。
- 证据：forecast 中等、regret 2.158；固定 ring 没有可证机制含义，hard failures 未变。
- 决定：`abandon fixed ring`；只有 learned/declared mechanism edges 才值得继续。

#### EXP-009 — B02 full-history baseline

- 用途：判定 W08 collision 是否来自可见历史压缩。
- 最小改动：payload 保留 exact visible history；heads 仍只读 state 内的 stored representation。
- 运行：`20260719T023222Z-EXP-009-15e2fa0807`。
- 证据：危险 collision 从 1 降到 0，但 bytes 4,084、false splits 6、OOD 仍 2。
- 决定：`keep baseline only`；证明 W08 差异可观察且 compact accumulator 丢失，不证明完整史是好 UCM。

#### EXP-010 — B03 separate-task baseline

- 用途：披露三套 patient latent 的非法 comparator。
- 最小改动：payload 明示 `task_states={diagnosis,natural,intervention}`；不包装成合规。
- 运行：`20260719T023227Z-EXP-010-6336703880`。
- 证据：未带来性能优势，仍 collision/OOD；`shared_state_compliant_by_design=false`。
- 决定：`keep illegal comparator`；永不进入 UCM winner。

#### EXP-011 — B04 K0-only negative control

- 用途：验证 custody/timing/接口元数据不能完成患者动力学。
- 最小改动：state 只有 as-of 和 event-count 类控制元数据。
- 运行：`20260719T023231Z-EXP-011-710d7fc132`。
- 证据：diagnosis .548、forecast 最差、危险 collision 5；控制面不能替代患者地图。
- 决定：`keep negative control`；不计架构成功。

### 20.4 Cadence counterexamples and architecture review

#### CE-005 — W08 ordered/availability history collision

在 EXP-005 完成后，W08 `probe-fixtures` group 2 对 F01/F03/F04/F05/F06/F07/F08
均给出相同 state、不同受控未来。EXP-005 的 decisive witness：

```text
left_state_hash = right_state_hash =
  sha256:9e5965b1112d50fba8a398fb5e09444c290c58a0dbc856dc4e3d4b5e9ff07d89
candidate_distance: 0.0
oracle_behavior_distance: 1.4725555397536851
classification: dangerous_collision
```

B02 full-history 的同批 collision 为 0，故 root cause 是共享 public accumulator
删除了事件顺序/availability path，不是世界不可识别。下一实验必须改 state update
architecture；调 ridge/hidden size 不具信息增益。

#### CE-010 — W18 confident forced-known OOD

EXP-010 cadence 后，所有 ordinary candidates 和 baselines 在两个 W18 test episodes
把大量/全部 `unknown` posterior 压到约 `1e-9`：

```text
episode 0: target unknown=1.0, predicted unknown≈1e-9, brier≈0.999999998
episode 1: target unknown=0.829774, predicted unknown≈1e-9, brier=0.688524899
classification: unsafe_non_abstain
```

这证明 closed-set nonnegative ridge normalization 不能冒充 OOD。下一批必须让
support/epistemic uncertainty 成为同一 patient state 的一部分，而不是在 head 外贴阈值。

#### AR-010 — first architecture review

1. **当前最强假说**：F04 的 behavior-target quotient 是最低 regret 路线；F06 是
   forecast Pareto 路线。
2. **失败世界**：共同在 W08 顺序/availability pair 危险碰撞，在 W18 强制 known；
   W15/W20 等价 pair 还出现 false split。
3. **参数还是表示**：是表示问题。八个 family 共用的 history accumulator 已丢掉
   W08 决定性信息；B02 保留完整可见史便消除 collision。OOD 则是 state 中没有
   support/epistemic 坐标。
4. **是否偷拆三任务**：F01–F08 没有；同一 state hash 到达 diagnosis 与全部 rollout。
   B03 明确违规且只作 comparator。
5. **是否回到基础定义**：是。先保留能改变任意允许 action future 的 path/support，
   再做 quotient；不能先按诊断表型压缩。
6. **搜索空间缺口/下一批**：加入 recursive order-aware state、support-aware belief、
   action-conditioned update、非参数 OOD、history deletion 和 W08/W18 focused gates；
   暂停 shallow neural/fixed ring 局部调参。

当前计数：11 个机器运行完成；其中 8 个是 distinct family screening、3 个 baseline。
它们都包含实质架构差异，但全部 hard-fail，完整 benchmark 仍为 0/3，不能给 winner。
