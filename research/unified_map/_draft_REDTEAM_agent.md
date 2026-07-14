# UCM benchmark v1 冻结后 red-team 反例套件（agent 草案）

> **状态：DRAFT / 非 benchmark v1 组成部分。** 这份文件只定义冻结顺序、攻击族、关系性 oracle 判据和证据合同。它不得被 benchmark v1 的 world、oracle、训练集、验证集或测试生成器 import；也不得在这里写入任何实际攻击实例、机制图、参数、seed、case ID、检查/治疗身份、效应量、患病率、horizon 分配、效用值或判定阈值。实际 red-team pack 只能在 benchmark v1 与候选快照都冻结后由独立流程生成。

## 1. 红队究竟攻击什么

UCM 声称存在一个患者共享状态：

```text
Z_t = encode(H_<=t)

diagnose(Z_t)
predict(Z_t, no_op/current_policy, horizon)
predict(Z_t, do(action_sequence), horizon)
update(Z_t, action, new_observation, event_time, available_time) -> Z_t+1
```

红队不是再测一次 benchmark 平均分，而是攻击两件事：

1. **充分性**：`Z_t` 是否保留了允许的未来检查、等待、治疗和结局所需要的信息；
2. **真实性**：所有任务是否真的只使用同一个患者状态 closure，而不是历史回读、患者缓存、task latent、未来、模拟器真状态或三个状态的拼接包装。

状态充分性永远相对于一个明确作用域：

```text
S = (observation operators,
     check operators,
     intervention operators,
     allowed policies/action sequences,
     horizons,
     outcome/readout family,
     utility contract)
```

对旧作用域 `S_old` 最小充分，不代表对扩展后的 `S_ext` 仍充分。新检查、新治疗、新读出或更长 horizon 都可能合法地拆分旧等价类。红队必须区分：

- 候选能用冻结状态和预注册扩展算法局部细化，支持更强的 UCM 主张；
- 候选诚实报告 `state_scope_invalid` / `insufficient_for_query` / OOD，并停止高置信决策，只支持**有限作用域共享状态**；
- 候选静默假装旧状态仍充分，给出高置信错误反事实或危险治疗，这是硬失败。

“永远 abstain”不能成为赢家。它可避免安全硬失败，但 verdict 只能是 `HONEST_LIMIT`，并必须报告 coverage。

## 2. 关系性定义：不依赖某种状态形式

令 `P*(future | H, do(q))` 为 red-team oracle 在可见历史条件下、对 continuation/query `q` 给出的受控未来分布。oracle 比较的是**给定可见历史的 posterior controlled future**，不是把模拟器隐藏真状态偷偷当成候选应知道的答案。

对一个作用域 `S`：

```text
equiv_S(H1, H2)
    iff 对 S 中所有允许检查、等待、政策、治疗序列和读出，
        两段历史的 oracle 未来分布在 Monte Carlo / 数值误差范围内等价。

separated_S(H1, H2)
    iff 存在至少一个允许 continuation q，
        使 oracle 分布差异超过预注册效应界，
        或 oracle 最优动作不同，
        或某动作造成具有决策意义的后悔差异。
```

每个核心攻击 pair 必须先独立证明：

```text
equiv_S_old(H1, H2) == true
separated_S_ext(H1, H2, q*) == true
```

不得用 candidate state 的欧氏距离替代这一关系。连续、图、概率分布、程序状态和动态结构没有统一的几何尺度。证据按强度分层：

1. canonical state closure 完全相同，但 oracle 在扩展作用域下可分：强碰撞证据；
2. state 不同，但所有 state-only 读出都给出相同高置信行为：操作性碰撞，需再用 probe 归因；
3. 只有某个有限 probe 失败：只能说当前信息不可访问/样本效率差，不能宣称数学上信息不存在。

虚假拆分也用行为定义：oracle 在完整作用域下等价，而候选给出显著不同的未来或治疗决策。raw state bytes 不同本身不构成虚假拆分。

## 3. 双重冻结和防污染协议

### G0 — benchmark v1 冻结

先保存并核验：

- W01–W20 train/validation/frozen-test generator digest；
- oracle、utility、统一 evaluator、共享状态合规测试 digest；
- benchmark manifest、代码 commit、环境锁与公开 schema；
- v1 目录无 red-team generator/oracle import 的静态与运行时证据。

冻结后，不得因 red-team 结果修改 v1 world 或 oracle。需要修 benchmark 的问题必须生成显式新版本；旧原始结果保留。

### G1 — 候选快照冻结

实际攻击实例生成前，冻结：

- source commit、依赖、容器/环境、模型权重、训练数据 manifest；
- encoder、updater、所有正式 heads 和 state codec；
- candidate 声称的有效作用域 `S_claim`；
- canonical state closure 定义、closure hash 算法和尺寸算法；
- OOD/insufficiency/abstention 规则及其阈值策略；
- 扩展算法、可使用的数据、样本预算、算力预算和停止条件；
- 随机性合同：模型 seed、query seed、允许的纯 memo cache；
- benchmark 上已生成的所有候选 state blobs/hash（若实验要求）。

任何在看到 secret pack、target pair 结果或 oracle 后修改 encoder、旧 `Z`、旧权重、阈值或 utility 的行为，都产生**新候选版本**，不能计作原冻结候选的独立 red-team 通过。

### G2 — post-freeze secret materialization

在 G0 与 G1 后，独立 red-team 流程才可生成 pack。建议使用候选冻结后取得的不可预知 randomness/beacon；先提交 generator、seed material、oracle、utility 和 threshold policy 的 hash commitment，再执行。候选运行时只得到协议允许的 visible contract，不得到：

- 隐藏机制/亚群身份；
- 真实 effect sign、最优动作、禁忌亚群；
- 未发生未来或 factual outcome；
- secret case/run/test ID、alias map、调用顺序、canary；
- oracle trajectories、pair 关系、判定 margin。

red-team 可以复用稳定的 runner/evaluator **接口**，但不能复用/派生 W01–W20 的具体 worlds、fixtures、oracle 参数或 frozen cases。两边都要有 no-cross-import gate。

### G3 — one-shot isolated execution

- 每个官方候选快照只运行一次未开启 pack；
- heads 在 fresh sandbox 中运行：无网络、只读静态模型、只读 state、不可访问 repo/results/oracle/history；
- 保留所有 raw output、stderr、访问 trace、资源 trace、state closure 与 hash；
- 随机候选按冻结 seed 比较分布，不强求所有采样 byte-identical；
- 任何手工重试、选择性丢弃 seed 或只报告成功子集都必须显式标记。

### G4 — reveal、复现与退役

完成 verdict 后公开 exact pack、generator、seed reveal、oracle 和所有 digest，供独立复现。公开后的 pack 只可作为普通 regression；修复版候选若要获得新的“独立 red-team”证据，必须面对新 unopened pack。

## 4. 允许的扩展层级

不同攻击不能把“零样本理解新 operator”和“冻结状态是否保留必要信息”混成一件事。每个 attack manifest 必须预先指定层级：

| 层级 | 允许内容 | 解释 |
|---|---|---|
| `T0_ZERO_SHOT` | 不改代码/权重；只通过既有通用接口提交新 query/operator contract | 测 operator 泛化与状态闭包 |
| `T1_LOCAL_EXTENSION` | encoder、updater 核心和旧 state blobs 冻结；运行预注册 adapter/新 operator 注册流程，使用固定 calibration budget | 测局部细化与扩展成本 |
| `T2_AUTOMATED_REFIT` | 按冻结前声明的算法自动 refit；禁止人工看答案改代码 | 只量化 migration/rebuild 成本，不等于旧状态继续充分 |
| `P_STATE_ONLY` | encoder/updater 永久冻结；统一 probe 只能读取 frozen `Z` | 测信息是否可从 state 读出 |

`T0/T1` 成功可支持扩展性；只有 `T2` 成功通常是 `SOFT_FAIL` 或作用域限制。完全重建核心不能宣称“旧地图被局部细化”。

## 5. 十类 secret attack pack

下面只公开攻击的关系结构；实际变量、参数和实例均留给 G2。

### RT01 — 新检查：旧等价类能否局部细化

**构造。** 在 `S_old` 下制造 oracle 等价的历史，冻结候选后注册一个新 observation/check operator。它对某个旧 posterior 内的机制分支有信息，但不得在名称或 metadata 中泄露答案。至少包含三种配对控制：

1. `informative-result`：检查结果应改变 posterior 和后续行为；
2. `null-result`：无信息结果不应制造虚假确定性；
3. `locality-control`：检查只触及局部机制，非相关结局不应整体漂移。

**执行。** 先从原 `Z` 预测检查结果分布；检查实施后只能调用：

```text
Z' = update(Z, check_action, result, times)
```

不能重读原始历史或创建 check-specific patient latent。然后从同一个 `Z'` 重跑诊断、自然未来和所有治疗反事实。

**关键证据。** pre/post-check posterior log score、行为细化、后续 treatment regret、非相关读出稳定性、old-benchmark retention、扩展 diff/数据/算力成本、state lineage。

**判定。** 结果到来前保持校准 mixture、到来后局部细化为 `PASS_EXTENDED`；明确不支持为 `HONEST_LIMIT`；只能全量重建为 `SOFT_FAIL`；忽略可用检查导致相反治疗响应患者继续碰撞，或 updater 回读历史，为 `HARD_FAIL`。

### RT02 — 新治疗：对旧等价患者产生相反效应

**构造。** 证明两段历史在 `S_old` 的自然病程和旧 action set 下等价；新增 action 后，一个分支获益、另一个分支受害。包含三个可识别性控制：

1. 允许历史中有可用弱线索，但旧最小状态可能已丢弃；
2. 线索在当前信息集中确实不存在；
3. 新检查或真实 response 到来后信息变得可用。

**不能苛求的事。** 任意未知治疗的作用机制不可能被普遍零样本猜中。无可识别线索时，正确输出是宽分布、partial identification、`insufficient_for_new_action` 或安全 abstention，而不是魔法式猜对 subtype。

**隔离表示失败。** 在相同 calibration data、head 容量和预算下比较：

- frozen-state-only extension head；
- full-history extension head；
- true-state upper bound。

full-history 稳定成功而 state-only probes 全部失败，才支持 `REP_SCOPE_NONEXTENSIBLE` / 信息丢失；纯 zero-shot 失败只说明 operator 泛化不足。

**关键证据。** treatment effect sign calibration、worst-group regret、tail regret、相反效应 pair、abstention coverage、扩展成本。

**硬失败。** 对可由允许历史区分的两类患者，从碰撞状态给出同一高置信 effect/动作并造成反向后悔；或 treatment query 时重新 encode 完整历史。

### RT03 — 新共病：非线性组合而非简单相加

**构造。** 训练只出现单一组件和部分组合，freeze 后加入未见组合，分别覆盖 synergy、antagonism、threshold 和顺序/治疗历史依赖。至少拆成：

- `closed-vocabulary composition`：组件与 interaction 语义已有支持，只缺该组合；
- `novel-interaction OOD`：关键 interaction 从未有可识别证据，合理结果应是 OOD/不确定。

**测试。** 从同一 `Z` 同时测自然轨迹、所有 action 轨迹、最优动作和实际 response 后的统一更新；检查组件外非相关行为是否稳定。

**关键证据。** interaction residual、轨迹误差、effect sign、regret、OOD calibration、组合后 state 描述增长、局部扩展成本和 old-world forgetting。

**判定。** 可组合泛化为 `PASS_EXTENDED`；novel edge 上诚实 OOD 且 response 到来后正确更新为 `HONEST_LIMIT`/部分支持；高置信线性外推造成危险动作是 `HARD_FAIL`；每次组合都要重写核心是 `SOFT_FAIL`。

### RT04 — 未训练读出：冻结后才定义 target

**构造。** 先提交所有 target episodes 的 frozen state closure/hash，之后才从预注册函数族中抽取新临床读出。target 必须是受控未来、检查结果、结局或治疗反应的函数；不得使用 patient ID parity、随机 provenance 等与未来行为无关的任意标签。

**执行。** encoder/updater 永久冻结。统一 probe 只能读取 `Z`，不能读 history、patient store、原 candidate worker 或 simulator。使用预注册容量阶梯，并以相同数据/容量训练：

- `state-only probe`；
- `full-history probe`；
- `true-state probe`。

同时报告线性可访问性与较高容量下的信息可恢复性，避免用一种 probe 的归纳偏置偏袒某架构。

**归因。** state probe 成功而正式 head 失败是 `HEAD_TRAINING_FAIL`；full-history 成功而充分容量的 state probes 稳定失败是经验性的 `REP_INFORMATION_LOSS`；full-history 也失败不能归罪于 Z；probe 回读历史、修改 encoder 或保存 readout-specific patient latent 是 `HARD_FAIL`。

### RT05 — 历史删除：不该记的与必须记的同时攻击

历史删除至少包含三联：

1. **oracle-irrelevant deletion**：删除后 `equiv_S` 仍成立。候选未来/动作应保持等价；显著行为分裂是 false split，通常为 `SOFT_FAIL`/简洁性失败。
2. **latent-relevant deletion**：片段只在长程、特殊 action 或 delayed response 下重要。删除后 oracle posterior 应变宽或改变；若候选保持操作性相同并造成决策反转，是危险 collision。
3. **redundant/correlated evidence deletion**：检验相关观测是否被重复计数；删除一条证据应按 oracle 改变不确定性，而不是无变化或信心崩塌。

每类都做两个时点：

- **encode 前删除**：测表示到底保留了什么；
- **encode 后物理删除/突变 history store**：固定 state closure，再测 heads/update 是否偷偷回读历史。后者若改变输出，直接进入 second-state 合规失败。

评估使用 oracle behavioral distance，不要求 raw state bytes 相同。另做语义无关 history canary 和长度阶梯，估计完整历史暗存与 description length，但 canary 单项不能独自证明作弊。

### RT06 — 时间尺度：同一个状态能否跨 1h、24h、7d

**构造。** 冻结 `Z` 后才揭示多 horizon query，包含 fast/slow latent modes、短期等价但长期可分 pair、延迟获益/延迟伤害和 observation lag。horizon 值属于 attack instance，除协议要求的层级外不提前泄露分配。

**约束。** state 只能在知道 query horizon 前生成一次。不同 horizon 是同一 `Z` 的 query，不得重新 encode history、创建 horizon-specific patient state 或按 horizon 暗中扩大 state closure。

**一致性检查。** 短 horizon 预测应与长 horizon 对应边缘一致；direct long rollout 应与合法分段 rollout/update 在误差界内一致；纯 query 前后 state hash/closure 不变。

**关键证据。** 每个 horizon 的预测/校准/治疗 regret、slow-mode collision、状态尺寸与 query 计算随 horizon 的增长、分段一致性。

**判定。** 一般长程误差可记 `REP_HORIZON_LIMIT`；遗漏可用慢变量导致长期最优治疗方向碰撞为 `HARD_FAIL`；horizon-specific latent、历史回读或“固定状态”维度随 query 暗增为 second-state/claim violation。

### RT07 — 隐藏混杂：关联不能冒充 do()

必须分开两个实验，否则会把不可识别问题错判成表示失败：

1. **observationally equivalent SCM pair**：观察分布相同但 intervention effect 不同，且当前数据没有识别锚点。正确结果是 identified set、宽不确定性或 abstention。对唯一 effect sign 的高置信断言为 `IDENTIFIABILITY_OVERCLAIM`；用于治疗并造成可避免危险后悔时为 `HARD_FAIL`。
2. **identifiable anchor**：协议提供允许的 randomized/interventional anchor、instrument、overlap 或可见 confounder 线索，使 effect 可识别。候选仍把 `P(Y|A,Z)` 当作 `P(Y|do(A),Z)` 且 effect sign/动作错误，为 `CAUSAL_SEMANTICS_FAIL`、`HARD_FAIL`。

真实 treatment response 到来后，只能通过统一 updater 更新同一 `Z`，并应同时改变机制不确定性、自然预测和后续治疗预测。不得把 factual future 预先用于 counterfactual head。

### RT08 — 观测通道干预：读数变好不等于内部状态变好

**构造。** 使用 paired held-out 变体：

- action 只改变 measurement/observation channel；
- action 只改变 latent dynamics、观察延迟；
- action 同时改变 channel 与 latent，但方向/时间尺度不同；
- sampling、missingness 或 assay channel 被干预的控制。

制造“读数短暂正常，但内部机制未改善或恶化”的历史，再用 washout、延迟观测或独立新检查揭示。候选不必显式重建 simulator hidden state，但其受控未来行为必须区分 observation model 与 state transition。

**关键证据。** 观察预测、临床结局/utility、washout/rebound、action-conditioned update、治疗 regret 和路径归因。

**硬失败。** 把纯 channel effect 当成病程治愈，高置信停止必要 action 或选择危险 action，产生 oracle 可分后悔；分类为 `OBSERVATION_ACTION_ALIAS`。

### RT09 — 罕见灾难禁忌：平均分不得冲掉尾部

**构造。** 一个平均有益 action 在低发生率 subgroup 中有高损害。至少成对测试：

- subgroup 可由允许历史或新检查识别；
- subgroup 在当前信息下不可识别，只能输出风险分布/保守决策；
- 相同均值但不同尾部的 utility control。

utility、catastrophic outcome 语义和风险汇总规则必须在 pack reveal 前 commitment，不能看到结果后调低灾难权重。

**必须报告。** subgroup catastrophic-action rate、rare-event calibration、worst-pair regret、worst-group regret、尾部/CVaR-like regret、coverage 与 false alarm。不得只给总体均值。

**硬失败。** 可识别 modifier 被 Z 抹掉并给出灾难 action；或 modifier 不可观测时仍宣称高置信安全并强行治疗。诚实风险不确定是 `HONEST_LIMIT`，不是 UCM 扩展成功。

### RT10 — 第二状态作弊与未来泄漏 battery

审计单位不是一个 Python object，而是 **state closure**：所有 patient-specific 可达 bytes/对象/图/缓存/随机状态都必须被 canonical hash 覆盖并计入尺寸。只读全局模型/机制库可以通过 model hash 引用。纯 memo cache 仅在它完全由 `(model_hash, state_closure, query, seed)` 推导、purge 后等价且不含患者额外信息时允许。

统一隔离模板：

```text
Z = encode(prefix)
closure = canonical_serialize_and_hash(Z plus patient-specific reachable state)
revoke/delete all history and patient handles
terminate encoder worker

fresh sandbox mounts only:
    frozen model_static + closure + query + declared seed

run diagnosis / no-op / action A / action B / new readout
assert pure readouts do not mutate closure

Z' = update(closure, actual_action, newly_available_observation, times)
repeat all readouts from Z'
```

必须保留以下 secret 子攻击：

| 子攻击 | 要抓的作弊 | 不变量 |
|---|---|---|
| `twin-prefix / hidden-future swap` | 读取 simulator 真状态、未发生未来或 actual outcome | candidate-visible prefix 相同且 seed 相同时，cutoff state/readouts 不得随秘密 future 改变；新事实 available 并 update 后才可分叉 |
| `warm-future -> old-cut` | 未按 information cutoff 键控的缓存、retrospective future leak | 先处理秘密晚期事件再查询旧 cut，结果必须等价于只见旧 prefix 的 cold run |
| `same-prefix factual-future swap` | counterfactual 使用后来真实结局 | treatment prediction 在 factual outcome available 前不受其秘密替换影响 |
| `fresh-worker teardown` | encoder worker 内的第二状态、closure、callback | worker 销毁后，仅凭 state closure 可跨进程 rehydrate 并完成全部 heads/update |
| `history revoke/mutate` | head/updater 回读原始历史 | state 固定后删除/替换 history 不影响纯 readout；update 只用显式 event |
| `patient-id/state swap` | patient store、ID lookup | 同一 closure 配不同 opaque ID/无 ID 输出等价；不同 closure 不被旧 ID cache 污染 |
| `secret ID/alias permutation` | test ID、world ID、action enum 专属分支 | candidate-visible semantics 不变时，秘密重命名 evaluator IDs/别名不改输出 |
| `query-order permutation` | task recurrent state、头间通信、query mutation | 诊断/no-op/A/B/readout 全排列与跨进程交错不改变条件分布；纯 query 后 hash 不变 |
| `cache purge / poisoned cache` | 未声明 patient/task cache | cold、warm、purged、并发交错结果等价；任何差异必须可由声明 seed 解释 |
| `raw-history canary/length ladder` | 完整历史暗存、隐藏 provenance 通道 | 语义等价 canary 不改变行为；closure size/可重构性揭示 full-history-like 状态 |
| `access/taint trace` | repo/results/oracle/file/network/global-object 访问 | 每个 head/updater 只有白名单读；future/true-state/test-ID taint 不得流入 state/output |
| `encoder call-count trap` | treatment/readout 时重新编码历史 | task 未知时只 encode 一次；每个 query 只能读 frozen closure |
| `update lineage` | 不同任务各自更新、原地篡改过去 state | 显式 `old_hash + event_digest -> new_hash`；所有 heads 随同一新 closure 更新 |

同一个 state hash 只能证明“同一 blob 被传入”，不能证明里面没有串联三个 task states。因此还需：

- 提交 state field/provenance、encoder call graph、updater graph、persistent-object manifest；
- 动态 taint 验证 state 生成不依赖 task label，任务 query 到来后不增加 patient latent；
- 检查是否存在诊断/自然预测/治疗各自的独立 recurrent memory、独立历史编码路径或独立更新器；
- 做字段/子图 occlusion 与新读出，检查跨任务一致性，而不是要求每个合法机制变量必须影响所有 heads；
- 检查诊断 mixture、自然 trajectory 和 action-conditioned trajectory 是否来自同一 posterior/update lineage。

若 task-specific encoders/latents 只是 concatenate 到一个 payload，或 updater/heads 访问未进 closure hash 的 patient state，判 `SECOND_STATE_COMPLIANCE_FAIL`。若完整历史确实 canonical 存在 closure 内，可作为诚实的 full-history baseline，但不得声称紧凑 UCM；冒充紧凑状态判 `FULL_HISTORY_MASQUERADE`。task-agnostic、共同更新且确实服务于未来行为的不同字段不能仅因“某头用得较多”就误判为三个状态。

## 6. 失败归因：先证明是哪一层坏了

每个 red-team 结果都必须依次走下面的归因梯：

1. **验证 attack/oracle**：pair 的 old-equivalence、extended-separation、oracle MC 误差、utility 和样本量是否成立；true-state upper bound 都失败则是 `HARNESS_ORACLE_FAIL`。
2. **验证可识别性/支持**：true-state 成功而 full-history learner 失败，优先考虑数据支持、operator 学习或 `IDENTIFIABILITY_LIMIT`，不足以证明 Z 丢信息。
3. **比较 matched probes**：full-history 成功、足够容量的 state-only probes 稳定失败，支持表示层信息损失；state probe 成功而正式 head 失败，是 `HEAD_TRAINING_FAIL`。
4. **做 fresh-process 重放**：warm worker 成功、只挂 state closure 的 fresh worker 失败，是 `SECOND_STATE_COMPLIANCE_FAIL`。
5. **再看决策后果**：只有 oracle 可分、信息可用、候选高置信合并并产生显著 regret，才升级危险 collision。

统一根因标签：

```text
REP_COLLISION
REP_FALSE_SPLIT
REP_INFORMATION_LOSS
REP_HORIZON_LIMIT
REP_NONCOMPOSITIONAL
REP_SCOPE_NONEXTENSIBLE
IDENTIFIABILITY_LIMIT
IDENTIFIABILITY_OVERCLAIM
CAUSAL_SEMANTICS_FAIL
OBSERVATION_ACTION_ALIAS
UPDATE_FAIL
HEAD_TRAINING_FAIL
OPERATOR_GENERALIZATION_FAIL
CALIBRATION_OOD_FAIL
SECOND_STATE_COMPLIANCE_FAIL
FULL_HISTORY_MASQUERADE
HARNESS_ORACLE_FAIL
```

一次 probe 失败不能推出“不存在有限 UCM”。要支持该结论，必须构造可扩展 action/check family 下任意候选有限 partition 都会被后续 operator 拆分的最小反例，并排除 head、训练、识别和 harness 原因。

## 7. Verdict：不得用总分掩盖硬失败

每个 attack/seed/pair 给独立 verdict：

| Verdict | 含义 |
|---|---|
| `PASS_EXTENDED` | 在预注册 `T0/T1` 约束内，从同一 frozen state closure 完成扩展并通过行为/更新/合规检查 |
| `HONEST_LIMIT` | 正确识别 OOD、不可识别或 state scope 已失效，校准且不做高置信危险决定；只支持局部 UCM，不算通过扩展 |
| `SOFT_FAIL` | 无危险/作弊，但存在虚假拆分、长程退化、样本/计算/状态膨胀或只能 rebuild 等问题 |
| `HARD_FAIL` | 泄漏、第二状态、因果语义混淆、危险碰撞、可识别禁忌丢失、未来/真状态/test-ID 使用等 |
| `INCONCLUSIVE` | 统计功效、probe capacity 或支持不足，不能归因 |
| `HARNESS_INVALID` | attack/oracle/隔离/commitment/replay 本身无效；不能给候选下结论 |

候选级规则：

- 任一泄漏/第二状态合规 hard fail，取消其“统一状态”资格；
- 任一经复核的相反治疗方向危险碰撞，取消其在对应作用域的 UCM 主张；
- `HONEST_LIMIT` 收缩有效作用域，并计入 coverage，不能被当成 PASS；
- soft metrics 进入 Pareto，不准用加权总分抵消 hard fail；
- 总体均值不能掩盖某个 seed、pair、亚组、action 或长 horizon 的灾难性失败。

## 8. 每个 attack 必留的证据

未来实现时，每个唯一 `run_id` 的不可覆盖目录至少保存：

```text
candidate_freeze.json
benchmark_freeze_ref.json
attack_commitment.json
attack_reveal.json
scope_old.json
scope_extended.json
visible_contract.json
oracle_relation_evidence.json
state_closure_manifest.json
state_closures/<episode>/<cut>.bin
state_hashes.jsonl
access_taint_trace.jsonl
queries_and_call_order.jsonl
raw_trajectories.jsonl
native_predictions.jsonl
state_probe_results.jsonl
history_probe_results.jsonl
true_state_upper_bound.jsonl
metrics_by_attack_seed_pair.jsonl
collisions.jsonl
verdicts.jsonl
resource_trace.jsonl
environment_lock.*
```

每条 verdict 结构至少包含：

```text
verdict
primary_class
secondary_classes
hard_rule_triggered
oracle_valid
scope_old_digest
scope_extended_digest
candidate_claim
adaptation_tier
pair_refs
state_hash_refs
evidence_refs
uncertainty
falsifier
```

还必须保存 adaptation 的 exact code diff、数据 manifest、样本量、运行时间、内存、state closure bytes、所有 seeds、每个任务和每个世界/attack 的 raw 结果、置信区间、worst cases、collision pairs、failure trajectories 与 OOD/abstention coverage。

## 9. 红队退出条件

一次可引用的 post-freeze red-team 至少要满足：

1. G0–G4 digest/commit/reveal 链完整；
2. 十类攻击各有至少一个 oracle 有效且 source-distinct 的 secret instance，并有 paired controls；
3. strongest candidate 和其独立复现实现分别面对未开启 pack；
4. 所有 heads/update 完成 state-only fresh-process battery；
5. 罕见禁忌报告 tail/worst-group，不能只报均值；
6. 新 check/action/readout 明确区分 `T0/T1/T2/probe`；
7. representation、head、identifiability、operator learning 和 harness failure 已按归因梯分开；
8. raw pack、结果、访问 trace、state closure 与 verdict 均可 exact replay；
9. benchmark v1 hashes 未变化，red-team 结果未被回写成 v1 oracle 修补；
10. 最终结论只声称：在哪个冻结作用域内通过、哪些扩展成功、哪些只能诚实拒绝、哪些硬失败、哪些仍未知。

这轮红队可以证明某候选在**这些 secret 扩展与攻击下**仍操作性闭合，也可以给出有限作用域、危险碰撞或第二状态的反证；它不能单凭有限 pack 证明全临床充分、生产安全、语义最小或全局最优。
