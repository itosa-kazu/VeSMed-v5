# 新临床动态地图：最小可运行、可证伪规格（Draft）

> 状态：**独立候选规格，未验证。**
>
> 边界：本文形式化的是用户提出的**新框架**，不是 VeSMed V5，也不以 V5
> 的实现、病例结果或失败作为本框架的证据。本文只规定最小对象、运行合同和
> 证伪方法；具体医学机制和参数仍需独立证据。

## 0. 一句话定义

在一个明确冻结的临床范围内，系统维护一份患者的递归 belief state：它同时表示
患者可能位于哪些机制/拓扑分支、各分支上的连续位置、当前离散运行模式，以及
已实施动作仍在产生的效应。诊断、自然病程预测和治疗反事实必须读取这份**同一
状态**，由同一个受控混合动力学产生结果。

```text
患者公开事件流
      │  统一递推更新（与随后要问的任务无关）
      ▼
SharedPatientState Z_t
├── 机制／拓扑分支的后验分布
├── 各分支内局部连续状态的条件分布
├── 代偿／失代偿等离散模式的条件分布
├── 个体背景与测量上下文的不确定性
└── 足以推进当前动作集合的动作历史摘要
      │
      ├── 诊断 readout
      ├── NoNewAction / 当前策略自然预测
      └── do(policy) 治疗反事实 rollout
```

## 1. 任何结论都必须绑定范围

本框架的声明范围记为：

\[
\mathcal S=(\mathcal P,\mathcal O,\mathcal Q,\mathcal A,\Pi,
\mathcal T,\mathcal Y,\mathcal U,\Gamma,\mathcal D,\varepsilon)
\]

- `P`：适用人群、宿主背景和机制支持域；
- `O`：可用观察、精度、缺失机制和可获得过程；
- `Q`：可实施检查；
- `A`：可实施生理动作/治疗；
- `Pi`：允许查询的开环或自适应策略；
- `T`：预测时间范围；
- `Y`：必须保留的未来观察、状态、事件和结局；
- `U`：固定价值函数集合；
- `Gamma`：诊断 readout 的粒度；
- `D`：比较未来分布的距离；
- `epsilon`：允许的近似误差。

“充分”“最小”“相同患者状态”都只能相对于 `S` 成立。加入新检查、新治疗、
更长 horizon 或新结局后，得到的是新范围 `S'`，旧状态不得被默认为仍然充分。

## 2. 世界真值、公开历史与共享状态

### 2.1 隐藏患者状态

患者世界的隐藏状态写成：

\[
X_t=(B_t,M_t,\Xi_t,\Theta,R_t)
\]

- `B_t`：机制/拓扑分支。它可以是单分支，也可以是允许交互的 active branch set；
- `M_t`：离散运行模式，如稳定、代偿紧张、失代偿、恢复；
- `Xi_t in M_(B_t,M_t)`：该分支/模式局部坐标图中的连续状态；
- `Theta`：年龄、遗传、器官储备等稳定或慢变个体参数；
- `R_t`：已实施动作的残余效应与路径依赖状态。

`X_t` 是世界真值，运行时系统不能直接读取。

### 2.2 公开事件流

系统只能读取截至 cut 已可获得的 typed events：

```yaml
PublicEvent:
  event_id: string
  event_type: ObservationAvailable | TestOrdered | TestPerformed |
              PlannedTreatment | PerformedTreatment | ContextUpdate
  occurred_at: timestamp | interval
  collected_at: timestamp | null
  available_at: timestamp
  concept_id: diagnosis_neutral_id | null
  value: typed_value | null
  unit: string | null
  measurement_context: object
  provenance: object
```

硬约束：

1. `available_at > cut` 的事实不能进入状态；
2. `PlannedTreatment != PerformedTreatment`，只有后者能改变生理状态；
3. `TestOrdered/TestPerformed != ObservationAvailable`；
4. 未检查、检查阴性、无法评价和结果尚不可得必须是不同状态；
5. 迟到结果可以在新 cut 更新对过去的 belief，不能反写旧 cut。

### 2.3 唯一共享状态

运行时患者对象是：

\[
\mathsf Z_t = P(B_t,M_t,\Xi_t,\Theta,R_t\mid H_t^{pub})
\]

最小 wire schema：

```yaml
SharedPatientState:
  protocol_version: string
  model_digest: sha256
  scope_digest: sha256
  state_schema_version: string
  available_cut: timestamp

  components:
    - branch_id: string
      mode_id: string
      posterior_mass: number
      local_chart_id: string
      local_state_distribution:       # Gaussian/particles/mixture/typed belief
        representation: string
        payload: object
      theta_distribution: object
      action_memory_distribution: object

  unknown_branch_mass: number
  pending_observation_model: object
  explicit_inference_rng_state: object | null
  lineage:
    parent_state_hash: sha256 | null
    consumed_event_digests: [sha256]
```

`components.posterior_mass + unknown_branch_mass = 1`。状态可以用粒子、混合分布或
其他表示，但必须可序列化；不能依赖内存 cache、隐藏患者文件或 query 调用顺序。

## 3. 动作相关历史摘要到底保存什么

不是把全部病历再塞进状态，也不是只保存“用过某药=yes”。`R_t` 必须保存当前
action catalog 推进未来所必需的路径信息，例如：

```yaml
ActionMemory:
  active_support_settings: object
  residual_exposures:                 # branch-conditioned PK/PD 可不同
    treatment_id: {level, decay_state}
  cumulative_toxicity_loads: object
  delayed_effect_queues: object
  last_mode_transition: {from, to, occurred_at} | null
  hysteresis_variables: object
  refractory_or_tolerance_state: object
```

它必须通过统一递推更新：

\[
R_{t+\Delta}=G_R(R_t,\text{performed actions},\Delta;B,M,\Xi,\Theta)
\]

若当前 action set 下不存在有界摘要，必须显式声明 `full_history_baseline` 或
`scope_insufficient`，不得把可逆压缩的全历史冒充“最小状态”。

## 4. 因子图：内部状态如何生成症状和检查

观察不是隐藏状态本身。给定隐藏状态和测量上下文，观察生成模型分解为局部因子：

\[
P(O_t, A_t^{avail}\mid X_t,C_t)
\propto
\prod_k \psi_k(O_{k,t},\operatorname{Pa}_k(X_t),C_{k,t})
\prod_j \phi_j(A_{j,t}^{avail},C_{j,t})
\]

- `psi_k`：内部机制、连续状态、模式和既往干预如何共同产生某项观察；
- `C_k`：测量方法、吸氧/升压药背景、采样质量、单位、个人基线；
- `phi_j`：检查选择、结果延迟和缺失过程；
- 多个观察若共享上游机制，必须通过共同 latent 连接，不能假设它们独立后重复计票。

例如：

```text
炎症活动 + 免疫反应能力 + 退热药残余效应 -> 体温
灌注 + 肾脏储备 + 利尿/升压支持           -> 尿量
泵功能 + 血管张力 + 容量 + 升压支持       -> 测得血压
```

因子图只是一种**观察生成分解**。给因子取了医学名字，不等于其因果身份已经被证明。

## 5. 混合受控动力学

### 5.1 分支/模式内部连续演化

在固定 `(B=b,M=m)` 的局部 chart 中：

\[
d\Xi_t=f_{b,m}(\Xi_t,\Theta,R_t,a_t)dt
+G_{b,m}(\Xi_t,\Theta,R_t,a_t)dW_t
\]

\[
dR_t=g_{b,m}(R_t,\Xi_t,\Theta,a_t)dt+dJ_t^a
\]

`a_t` 必须来自已实施动作；`dJ_t^a` 表示给药、插管、手术等离散动作注入。

### 5.2 离散模式与拓扑分支切换

分支/模式转移由条件 hazard 或 guard 定义：

\[
P((B,M)_{t+dt}=(b',m')\mid X_t,do(a_t))
=\lambda_{(b,m)\to(b',m')}(X_t,a_t)dt+o(dt)
\]

这允许：

- 代偿 -> 失代偿 -> 恢复，且进入与退出阈值不同（滞后）；
- 一个新机制分支被激活、缓解或与既有分支交互；
- 器官支持启动后进入不同维数/不同合法坐标的 stratum；
- 突然冲击直接触发跳变，而不是强迫所有恶化都有缓慢预警。

### 5.3 belief 的预测与观测更新

动作后预测：

\[
\bar{\mathsf Z}_{t+\Delta}
=\int K_{\Delta}^{do(a)}(x'\mid x)\mathsf Z_t(dx)
\]

新观察可得后更新：

\[
\mathsf Z_{t+\Delta}(dx')
\propto P(o_{t+\Delta}\mid x',c)\bar{\mathsf Z}_{t+\Delta}(dx')
\]

晚到观察需要固定窗 smoothing 或把受影响历史摘要纳入 state；采用哪种方案必须在
scope 中声明，不能临时重读全部患者历史。

## 6. 分支/分层几何负责什么

全局患者空间是 strata 的并：

\[
\mathcal X=\bigcup_{b,m}\mathcal M_{b,m}
\]

同一 stratum 内可使用局部 metric：

\[
d_{b,m}(z,z')^2=(z-z')^T G_{b,m}(z)(z-z')
\]

跨 stratum 距离必须沿合法 bridge/transition 图计算，而不能直接平均不兼容坐标：

\[
d_{geo}(x,x')=\inf_{\gamma:x\leadsto x'}
\left[\sum \operatorname{Length}_{G}(\gamma_k)+
\sum \operatorname{BridgeCost}(e_k)\right]
\]

但 `d_geo` 只是建模先验和计算工具。临床正确性的最终距离必须由范围内受控未来定义：

\[
d_{\mathcal S}(h,h')=
\sup_{\pi\in\Pi,\tau\in\mathcal T}
D\left(P(Y_{t:t+\tau}\mid h,do(\pi)),
P(Y_{t:t+\tau}\mid h',do(\pi))\right)
\]

若几何上“很近”却存在相反最佳治疗，则几何错了；不能用漂亮可视化覆盖行为反例。

## 7. 诊断、自然预测、治疗必须真正共享状态

状态更新不预先知道下一步会问什么：

```text
initialize(public_history, scope) -> SharedPatientState
update(old_state, newly_available_events, advance_to) -> SharedPatientState
```

三种 readout 均读取同一份 exact state bytes：

```text
diagnose(M, Z_t, gamma_query)
  -> P(mechanism/branch/mode/diagnostic quotient | Z_t)

rollout(M, Z_t, NoNewAction, horizon)
  -> P(future trajectory/outcome | Z_t)

rollout(M, Z_t, do(policy), horizon)
  -> P(future trajectory/outcome | Z_t, do(policy))
```

自然预测只是 `rollout` 的一个 policy，不允许另建自然病程动力学。治疗 query 是纯函数：
A/B/no-op 的查询顺序不能改变结果，也不能改变 factual state。只有实际发生且后来可见的
`PerformedTreatment + response` 才能通过 `update` 生成新状态。

“共享”至少要求：

1. 单患者只有一个持久 state root；
2. initialize/update 不依赖任务名；
3. diagnose/rollout 不重读原病历；
4. natural/treatment 使用同一 transition core；
5. 任一新 observation 更新后，三个 readout 都从新 state 重算；
6. 不允许 `(diagnosis_state,natural_state,treatment_state)` 三个黑箱机械拼接后改名为共享状态。

## 8. 状态碰撞与新治疗触发局部细化

### 8.1 定义

- **状态碰撞**：两段公开历史被编码成相同/极近状态，但其登记策略下的未来分布可区分；
- **危险碰撞**：存在相反最佳动作、灾难性 regret 或不同模式转移风险；
- **虚假拆分**：所有登记未来均等价，但系统仍保留显著不同状态。

任何 exact dangerous collision 都是硬失败，平均 AUROC 不能补偿。

### 8.2 新治疗 `a*` 到来时的合法流程

```text
绑定新范围 S' = S + a*
        ↓
在旧状态内寻找 opposite-response / high-regret pair
        ↓
若没有碰撞：证明旧状态对登记 probes 暂时仍充分
若发现碰撞：冻结反例并定位受影响 stratum
        ↓
寻找在动作前可获得的新观察、检查或可递推历史摘要
        ↓
建立 parent stratum -> child strata 的局部迁移
        ↓
验证旧动作/旧患者不发生无关退化
```

版本化局部迁移：

```yaml
StateRefinement:
  from_scope_digest: sha256
  to_scope_digest: sha256
  affected_parent_strata: [string]
  child_strata: [string]
  discriminator_source: existing_state | new_public_check | post_action_response
  migration_kernel: object           # 旧状态通常迁移为 child 上的分布
  preserved_old_queries: [query_id]
  unresolved_collision_classes: [string]
```

硬边界：

- 新治疗后的响应可以更新**以后**的状态，但不能凭空告诉治疗前该给谁用药；
- 若分型变量在任何治疗前公开观察中都没有信息，系统必须输出
  `scope_insufficient/unidentifiable`，不能确定性把患者塞入 child；
- 新检查只能在结果 `available` 后收缩 posterior；
- 局部细化不能借机全局重写旧患者历史或用 case ID 记答案；
- 受影响区域外的旧 readout 必须通过非回归测试。

## 9. 最小可运行实现

不需要先实现全医学。一个最小 engine 只需：

```text
分支：B1 / B2 / unknown
局部连续变量：disease_load, reserve
模式：compensated / decompensated
动作记忆：support_level, residual_probe_effect
观察：surface_output, recovery_rate
动作：NoNewAction, ContinueSupport, SmallProbe, TreatmentA, TreatmentB
```

要求构造：

1. 两名患者当前 `surface_output` 完全相同；
2. 他们位于不同分支，对 A/B 反应相反；
3. 小探针在风险可接受时产生不同恢复轨迹并更新 branch posterior；
4. 同一连续位置在 compensated/decompensated 模式下具有相反 drift；
5. 外部支持可以暂时掩盖低 reserve；
6. 新治疗依赖一个旧观察不可辨认的 subtype，触发 collision；
7. 加入新检查后只局部拆分对应 stratum；若不加入检查则正确 abstain。

这个 toy world 只证明 engine 能按规格运行，不证明真实人体具有相同机制。

## 10. 必须预注册并实际执行的验收测试

### A. 信息与状态合同

| ID | 测试 | 通过条件 |
|---|---|---|
| T01 | future availability | 删除未来 event 后旧 cut state bytes 与输出不变 |
| T02 | planned vs performed | 仅 planned action 不触发生理转移 |
| T03 | recursive closure | fresh process 仅凭 `M+old Z+delta` 得到同一新状态 |
| T04 | head isolation | diagnosis/rollout 无法读取 raw history 或患者 cache |
| T05 | exact shared bytes | 三类 readout 的 `consumed_state_hash` 完全相同 |
| T06 | query purity | A/B/no-op 调用顺序不改变输出或 factual state |

### B. 结构能力

| ID | 测试 | 通过条件 |
|---|---|---|
| T07 | common-cause evidence | 共享上游的两个观察不会被当成两份独立证据 |
| T08 | support masking | 相同表面输出、不同 support/action memory 得到不同风险 |
| T09 | mode hysteresis | 相同连续坐标、不同 mode 可产生相反 drift；删除 mode 会失败 |
| T10 | branch geometry | 跨分支近邻不使用无定义欧氏平均；合法 path distance 可复现 |
| T11 | no-op/continue/stop | 三种 policy 在残余治疗存在时给出可区分未来 |
| T12 | unknown branch | 所有已知分支解释不足时保留 unknown mass/abstain |

### C. 统一状态与决策能力

| ID | 测试 | 通过条件 |
|---|---|---|
| T13 | dynamic identification | 新响应进入一次统一 update 后，诊断与全部 rollout 一起改变 |
| T14 | natural/treatment core | no-action 与治疗预测调用相同 transition implementation |
| T15 | dangerous collision | opposite-response pair 相同/近状态时测试必须硬失败 |
| T16 | false split | 行为等价 pair 被明显拆开时报告压缩失败 |
| T17 | action regret | 在可识别范围内，策略 regret 不劣于冻结简单基线 |

### D. 开放世界与局部细化

| ID | 测试 | 通过条件 |
|---|---|---|
| T18 | unseen treatment split | 新治疗暴露旧 collision，系统不静默外推 |
| T19 | local migration | 只拆受影响 stratum，旧 query 在容差内保持 |
| T20 | unobservable split | 没有治疗前信息时返回 unidentifiable，而不是猜 subtype |
| T21 | new check | 结果 available 后 posterior 收缩；available 前不变 |
| T22 | schema/version lineage | 新旧 scope/state 版本和迁移证据可追溯 |

阈值（分布距离、calibration、regret、模式切换延迟、非回归容差）必须在看到候选
结果前冻结。只跑几个绿色示例不能证明充分性。

## 11. 两个复杂真实病例应怎样用于测试

每个病例从入院到结局按 `available_at` 建立多个 cut。每个 cut 必须记录：

1. 同一 state hash；
2. branch/mode posterior 与 unknown mass；
3. 局部连续状态及不确定性；
4. 当前 action memory；
5. 自然病程 rollout；
6. 若干可行治疗 rollout；
7. 新事件到来后的统一 update；
8. 主要因子贡献、冲突与不可识别项。

病例回放的高价值反例包括：

- 相同表面指标但支持强度不同；
- 新并发过程出现导致 branch posterior 分叉；
- 代偿到失代偿的 mode 切换；
- 治疗掩盖观察；
- 治疗响应反过来更新机制 belief；
- 恢复后模式退出但残余 action effect 仍存在；
- 新治疗需要旧状态未保存的新分型信息。

真实病例测试必须冻结病例结构化结果后再运行，不能依据 expected diagnosis 修地图。

## 12. 一两个病例能证明什么、不能证明什么

### 能证明或证伪的工程命题

- 事件时间和 future-leak 合同是否正确；
- 一个 shared state 是否真的被三个 readout 消费；
- 状态能否递推、序列化并在 fresh process 重建；
- 模式、动作历史、分支和局部坐标在病例中是否可表达；
- 输出是否自洽，是否暴露明显状态碰撞、双计数或非法动作；
- 该具体病例是否构成当前模型的反例。

### 不能从一两个病例得到的结论

- 不能证明 branch posterior 是校准概率；
- 不能证明因子图边是真实因果关系；
- 不能证明治疗反事实正确或某治疗造成了病例结局；
- 不能证明状态充分、最小，或危险碰撞已经消失；
- 不能证明能泛化到其他医院、人群、病程或未知机制；
- 不能证明优于静态模型、完整历史模型或独立任务模型；
- 不能证明“全医学存在有限理想模型”；
- 不能用病例中恰好发生的一条轨迹验证所有未发生治疗分支。

需要这些结论时，至少还要有：冻结的多病例/多中心测试、外部验证、随机或可识别的
动作比较、collision search、calibration、baseline comparison，以及对新检查/新治疗的
预注册 extension experiment。

## 13. 本规格的可证伪结论

下列任一结果都要求缩小或放弃当前版本，而不是继续打补丁：

1. 在冻结 scope 内，任何有限递归状态都必须保留无界完整历史；
2. 同一 shared state 持续产生相反最佳动作，且没有可获得信息可局部细化；
3. 独立诊断/预测/治疗模型在公平容量和数据下稳定严格支配共享状态；
4. 新动作每次都迫使全局重构，无法局部迁移且旧能力不能保持；
5. mode/branch 只是重命名，删除后预测、更新和 collision 指标不变；
6. 因子图不改善校准或依赖处理，只增加不可识别 latent；
7. 反事实结论主要来自无法检验的结构假设，而系统不报告识别边界。

届时合法结论可以是：只存在局部、动态、带完整历史或任务相关的状态；不存在当前
scope 下可压缩的统一状态。框架名称不能成为免受反例攻击的理由。
