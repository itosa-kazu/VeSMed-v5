# UCM benchmark v1 微型临床世界 W01–W20

> **状态：PRE-FREEZE。** 本文是 W01–W20 的正式语义规格，但尚不等于 benchmark v1 已冻结。只有对应生成器、独立 oracle、public/private projection、paired probes、误差界、split audit、expected cells 和合规 mutation tests 全部实现并进入 `FREEZE_MANIFEST.json` 后，状态才可改为 `FROZEN-v1`。
>
> 本文只定义可判定的合成世界，不声称模拟真实临床有效性。候选 API、共享状态隔离、raw result、统一指标和冻结程序以 `BENCHMARK.md` 与 `FORMAL_SPEC.md` 为准。所有 wire 名称保持中性；`Wxx`、split、case/test/pair ID、hidden state、future、oracle 和 seed 永不进入 candidate request。

## 0. W01–W20 共用的可执行约定

### 0.1 中性命名和作用域

所有世界共用下列内部符号，禁止把世界名、疾病名或预期答案编码进普通 observation/action 名：

| 符号 | judge/private 含义 | candidate-visible 形式 |
|---|---|---|
| `x_k` | 第 `k` 个离散时点的动态真实状态，可为向量 | 永不直接暴露；W01 的无噪声观测恰好等于它不等于暴露 private object |
| `theta` | episode 内不变的连续参数或基线 | 只通过允许的 context/observation 间接或显式观测 |
| `c` | 中性离散机制类 `C0/C1/...` | 训练 target 可给中性 class；test 时不作为输入 |
| `r_k` | 既往动作的持续暴露/效应记忆 | 只通过已实施动作历史和观察推断 |
| `d_k` | 延迟队列/有时间戳的旧状态缓冲 | 不暴露 |
| `a_k` | decision/policy 中的 treatment choice | `NoNewAction/A1/A2`；只有 A1/A2 可产生 `PerformedTreatment`，`NoNewAction` 从不伪造成 zero-dose event |
| `q_k` | 已实施 check action | typed `Q0/Q1/Q2` |
| `o_k` | 检查产生的可见值 | typed `obs_0/obs_1/...` |
| `epsilon, eta` | process / observation exogenous noise | 不暴露 seed 或 realized noise |

候选拿到的是冻结 catalog 中的中性 action/observation schema。runner 可以在 wire 层再做 alias permutation；`W01`、`probe-pair-17`、`test`、episode index、environment seed 等仅存在于 judge ledger，不进入请求、state bytes 或 query。

### 0.2 时间、step 内顺序和 cut

除 W08 外，基础步长为一个抽象临床时间单位，历史为 `k=-4,-3,-2,-1,0`，主要 query cut 为 `k=0`，未来 horizon 为 `H in {1,4,8}`。W08 用四个 microtick 表示一个基础时间单位，但 wire timestamp 精确到 microtick。

每个 interval `[k,k+1]` 的顺序冻结为：

1. 在 decision time `k`，runner 先交付所有 `available_at <= k` 且尚未交付的事件；
2. factual behavior policy **只读取此时 public history**，选择 treatment/check；
3. `PerformedTreatment`、`TestOrdered`、`TestPerformed` 在真实发生时立即成为 public event；planned 不等于 performed；
4. treatment 作用于 `x_k -> x_{k+1}`，并可更新 `r_{k+1}`；
5. check 在 world 声明的 collection phase 采样，默认采样 post-transition `x_{k+1}`；
6. check result 仅在其 `available_at` 到达后成为 `ObservationAvailable`；发生/采集但未 available 的结果留在 private queue；
7. 同一 timestamp 的 public event canonical order 为 `(available_at, occurred_at, kind_rank, event_uid)`；event UID 只用于去重，做 alpha-renaming 后语义必须不变。

`NoNewAction`、`ContinueCurrent`、`StopControllable` 和 `Do(action schedule)` 是不同 policy。反事实 query 是纯读；只有实际 `PerformedTreatment`/新结果通过 `update` 改 factual state。

### 0.3 随机性和 structural counterfactual

- `clip(v,l,u)=min(max(v,l),u)`；`sigmoid(z)=1/(1+exp(-z))`。
- 所有未特别说明的高斯噪声彼此独立，且 independent across episode/time。
- 每个 episode 的 private exogenous tape 包括 `theta,c,x_-4,epsilon_{-3:8},eta,...`。factual 和每条 action counterfactual 共用同一条 pre-cut tape。
- **unit-level paired counterfactual**：从同一 `x_0,theta,c` fork，未来各 action 分支复用相同 process-noise quantiles/common random numbers；用于 ITE/paired regret。
- **distributional oracle**：对 future exogenous tape 积分。线性高斯世界用解析 mixture/Kalman；带 clip/threshold 的世界用独立枚举，或至少 16 个独立 Owen-scrambled Sobol replicate、每个 `2^14` points。误差界从 replicate 间方差计算（不能给单个固定QMC序列伪造普通MC SE），并保证各冻结主要指标的 99% CI 半宽 `< 0.005`。
- factual realized future 不能进入 cut-time state或反事实输入；actual future 只供 judge 事后评分。

### 0.4 数据暴露和 public projection

每个 candidate-visible event schema 均 `additionalProperties:false`，只允许：

```json
{
  "kind": "ObservationAvailable|PerformedTreatment|TestOrdered|TestPerformed|ContextAvailable",
  "occurred_at": 0,
  "collected_at": 0,
  "available_at": 0,
  "event_uid": "opaque-random",
  "payload": {}
}
```

public history MUST NOT 含：`world_id/case_id/test_id/split/episode_index/generator_seed/environment_seed/x/theta/c/epsilon/oracle/future/actual_future/expected_action/expected_label/reward_to_come`。训练用诊断 label、实现过的 factual future、action propensity 和训练 loss target 通过 trainer-only target stream 交付，不回填 patient event，也不允许 state/head 在 test 时访问。

训练 stream 提供：

- public prefix 和 factual action/check log；
- 每个 factual decision 的已知 propensity；
- 之后实际 available 的 factual observations/outcome/utility；
- episode 结束后的中性 diagnostic target `C*`；
- 预注册比例的 randomized-probe episodes。

默认不提供 simulator state或同一 episode 的全部未实施 treatment 结果。显式 `TrueStateUpperBound` 可读取 private truth，但只能标为 upper bound waiver。

### 0.5 finite policy set 和 all-action oracle

“所有治疗下的反事实”在 v1 指对每个 world 冻结的有限 `policy_set` 全部求分布，不允许只算候选推荐的 action。若无另行说明，H=4 的公共 policy 形状为：

- `P0 = NoNewAction`；
- `P1 = Do(A1 at k=0)`；
- `P2 = Do(A2 at k=0)`（若世界无 A2 则省略）；
- `P3 = Do(A1 at k=0,1,2,3)`；
- `P4 = Do(A2 at k=0,1,2,3)`（若适用）；
- 所有 check-only policy；
- 每个 world 明列的 adaptive check-then-treat policy。

H=1 取上述 policy 的第一步；H=8 将 constant schedule 延长到 8 步，single-dose policy只在 `k=0` 施行。oracle 对每个 policy 输出：未来 latent/outcome truth（judge-only）、candidate-visible observations 的联合/边缘分布、event/utility 分布、expected utility、diagnostic class posterior。检查本身除明列生理效应外不改变 latent state，但计入 utility cost。

factual behavior policy不是 oracle baseline policy。它只生成观察性日志，必须记录 exact propensity；它不得读取 hidden `c/theta/x`，只能读 public history。每个 decision 另混入 `epsilon_explore=0.10` 的均匀 action/check，保证支持度。

### 0.6 split、seed 和 freeze 规则

每个世界默认生成：

| split | episode 数/环境 seed | 是否 candidate 可见 | 用途 |
|---|---:|---|---|
| train | 4096 | 是；含 trainer target stream | fit 与固定 train fractions `1/5/10/25/50/100%` |
| validation | 1024 | 是；case-level oracle 不直接导出 | config/threshold 选择 |
| frozen-test | 2048 + private probe pairs | seal 后只运行一次 | primary judge |

至少五个 model seed 使用同一套环境 corpus。episode RNG key 为

```text
K = HMAC-SHA256(master_seed,
    "UCM-BENCH-v1|semantic_version|world_slot|split|episode_index|stream_name")
```

再用 `PCG64DXSM(K[0:128])`；Gaussian/Uniform/Bernoulli 的调用顺序写进 generator contract。test `master_seed` 在 finalist seal 后 commit/reveal。不同 split 使用不同 master namespace，并对量化后的完整 private parameter/tape digest 去重；任意 digest 重复就重抽。pair fixture 使用单独 `pair_family/pair_index` key，不把 pair identity给 candidate。

每个世界的小节必须列出：train/validation/test 的参数 support或组合 holdout。test 支持不能靠藏 world name实现。若 hidden test reveal 后更改生成器、transition、utility、pair family或 margin，应创建 benchmark v2；bugfix 另建 patch version并保留旧结果。

### 0.7 probe pair、behavior distance 与统一失败门

对每个 pair `(h_i,h_j)`，judge在同一 frozen query/probe set上算 oracle behavior distance：

```text
D_oracle = max(
  TV(diagnostic posterior),
  max_policy,horizon W1(outcome_i,outcome_j)/scale_w,
  max_policy |E[U_i]-E[U_j]|/utility_scale_w,
  max_future_check TV/normalized-W1
)
```

候选行为距离用同一输出 schema与 scale。每个 world 下列 margins 在看 candidate test 前冻结：

- `epsilon_equivalent`：oracle 数值误差内等价；
- `delta_distinguishable`：行为上必须区分；
- `catastrophic_regret`：单 episode oracle regret 达此值视为灾难动作。

硬门：

1. `state_hash_i == state_hash_j` 且 `D_oracle >= delta_distinguishable` 为 exact collision；若最优 action sets 不相交、effect sign相反或 regret 超过 `catastrophic_regret`，为 **exact dangerous collision，run-level hard failure**。
2. `D_candidate <= epsilon_candidate_same=0.03` 且 `D_oracle >= delta_distinguishable` 为 functional near-collision；须保存 worst pair，超过灾难 margin为 hard failure。
3. `D_oracle <= epsilon_equivalent` 且 `D_candidate >= delta_distinguishable` 为 false split；不单独硬淘汰，但进入简洁性/Pareto。
4. identical public prefix、同模型/同 explicit seed但 private future/oracle不同，state hash或pre-availability output任何 byte差异都是 future leak hard failure。
5. 任何 head从历史/true state/test ID/cache取得信息、治疗 query构造第二状态、actual future改变prior counterfactual，均由总合同硬淘汰，不能被世界均分抵消。

以下各节的“主要失败判据”是在共用硬门之上增加的 world-specific 判据。

---

## W01：完全可观察的线性控制系统

### 1. Hidden state / parameters 与诊断真值

这是 plumbing/metric sanity world；所有动态状态和机制类通过无噪声允许观测可见，不考验 hidden-state inference。

```text
x_k = [x0_k, x1_k]^T in R^2
c in {C0,C1}, P(c)=0.5
A_C0 = [[0.82,  0.10], [ 0.00, 0.75]]
A_C1 = [[0.92,  0.18], [-0.05, 0.80]]
B      = [-0.35, 0.20]^T
sigma_process = diag([0.04,0.04])
```

`c` 是动力学类别，不是疾病名。每个 routine observation 都显式携带 `obs_2 in {0,1}` 作为 exact public mechanism context，因此“完全可观察”包含 class。diagnostic truth 为 `c`；continuous-state truth 为 `x_0`。

### 2. Transition equations

动作编码 `u(NoNewAction)=0, u(A1)=+1, u(A2)=-1`：

```text
x_{k+1} = A_c x_k + B*u(a_k) + epsilon_{k+1}
epsilon_{k+1} ~ N(0, sigma_process sigma_process^T)
```

不 clip。该参数下两个 `A_c` 稳定；oracle和独立 reference 必须验证谱半径 `<1`。

### 3. Observation process、checks/actions

- `Q0/full_panel`：post-transition，立即 available；返回 `obs_0=x0`, `obs_1=x1`, `obs_2=0/1`，**零 observation noise**。
- 每个历史 step自动执行 Q0；未来 check-only query也允许 Q0，cost=0。
- treatments：A1/A2 可 single-dose或constant；NoNewAction=no new action。
- 当前 action不会改变当下已经 available的 `x_k`，只改变 `x_{k+1}`。

虽然数值恰好等于 private state，candidate仍只收到 typed observation DTO；不得给 simulator object、future noise或private field。

### 4. Factual behavior policy

用最后一条 public `obs_0=y`：

```text
logit(NoNewAction)=0
logit(A1)=+1.2*y
logit(A2)=-1.2*y
pi_b = 0.90*softmax(logits) + 0.10*Uniform(NoNewAction,A1,A2)
```

每步自动 Q0。policy 只读 y；propensity随训练 record保存。

### 5. Counterfactual oracle 与 utility

线性高斯递推给 exact multivariate Normal。对全部 `P0..P4` 和 H={1,4,8}解析计算 mean/covariance；reference implementation用 `2^18` Sobol样本核对 mean `<1e-3`、covariance max error `<2e-3`。

```text
U = - sum_{j=1..H} gamma^(j-1) *
        (x0_j^2 + 0.5*x1_j^2 + 0.05*u(a_{j-1})^2)
gamma = 0.97
```

judge统一按 expected U 选 action；tie-break `P0 < P1 < P2 < P3 < P4`。

### 6. Generator / split

- train：`x_-4 ~ Uniform([-1,1]^2)`，C0/C1各半；所有 action都有support。
- validation：同机制，`x_-4 ~ Uniform([-1.15,1.15]^2)`，按 class×初始quadrant分层。
- frozen-test：80%同 validation support；20%从边界壳 `max(|x0|,|x1|) in [1.15,1.35]`；不改变 transition。
- 所有 split在 `c × sign(x0) × sign(x1)` 8格内近似等量，cell count差不超过1。

### 7. 配对反例 / probe

1. **危险合并 pair**：采样 `v in [0.55,0.95]`，两个 cut state为 `[+v,-v/2]` 与 `[-v,+v/2]`，当前面板完全公开；它们的 oracle最优 action方向相反。若合并说明连显式状态都没保留。
2. **等价重排 pair**：同一 `x,c`，仅 event UID、同 timestamp Q0字段顺序和无语义 provenance nonce不同；canonical public semantics相同。oracle所有行为相同，用于 false split/UID branch。
3. **full replay pair**：逐步 update得到的 state与一次 initialize同一有序公开历史，行为必须一致；exact hash是强要求但行为等价是最低要求。

### 8. Margins 与主要失败判据

```text
outcome_scale=2.0, utility_scale=8.0
epsilon_equivalent=0.005
delta_distinguishable=0.20
catastrophic_regret=0.40
```

除共用硬门外：full-state预测 RMSE >0.05（H=1）或 oracle-available class accuracy <0.999，属于 plumbing failure；A1/A2 effect sign error为 major failure；W01不过不得进入更复杂 world 的性能结论。

---

## W02：部分可观察的两维系统

### 1. Hidden state / parameters 与诊断真值

```text
x_k=[x0_k,x1_k]^T
c in {C0,C1}, P(c)=0.5
A_C0=[[0.85, 0.25],[-0.10,0.80]]
A_C1=[[0.85,-0.25],[ 0.10,0.80]]
B=[-0.30,0.12]^T
Q=diag([0.06^2,0.06^2])
x_-4 ~ N([0,0], diag([0.8^2,0.8^2]))
```

candidate永远不直接见 `x,c`。diagnostic truth=`c`；oracle diagnosis是 `P(c|public H_k)`，不是泄漏realized class的one-hot posterior。

### 2. Transition equations

```text
u(NoNewAction)=0, u(A1)=+1, u(A2)=-1
x_{k+1}=A_c x_k+B*u(a_k)+epsilon_{k+1}
epsilon~N(0,Q)
```

### 3. Observation process、checks/actions

所有采样 post-transition：

```text
Q0: obs_0 = [1.0, 1.0] x + eta0, eta0~N(0,0.18^2), delay=0, cost=0.01
Q1: obs_1 = [1.0, 0.0] x + eta1, eta1~N(0,0.08^2), delay=1, cost=0.04
Q2: obs_2 = [0.0, 1.0] x + eta2, eta2~N(0,0.08^2), delay=1, cost=0.04
```

每步至多一个check。treatments A1/A2同 W01 action semantics。future policy set为 P0–P4，加：

- `P5=Do(Q1 at 0), then at result availability choose A1 if posterior E[x0]>0 else A2`；
- `P6=Do(Q2 at 0), then choose A1 if posterior E[x1]>0 else A2`。

adaptive阈值和tie-break由judge固定，不由候选推荐器决定。

### 4. Factual behavior policy

令 `y` 为最后 available Q0（缺失时0），`v`为最近四个Q0的sample variance（不足2条取0.25）：

```text
Pr(Q0)=0.45
Pr(Q1)=0.275 + 0.15*sigmoid(|y|-0.5)
Pr(Q2)=1-Pr(Q0)-Pr(Q1)
action logits=[0, +0.9*y, -0.9*y]
```

对check和treatment各自再混入10% uniform。它不读取x/c。

### 5. Counterfactual oracle 与 utility

oracle为两个class-conditioned Kalman filter的exact mixture：每个component保存 weight、mean、covariance；延迟Q1/Q2用一阶augmented state `[x_k,x_{k-1}]`。action rollout保持mixture，不做moment collapse。独立reference对离散class枚举并以Sobol积分continuous state。

```text
U=-sum gamma^(j-1)*(x0_j^2+0.7*x1_j^2
   +0.05*u_j^2+0.04*I(check_j in {Q1,Q2}))
gamma=0.97
```

输出未来检查分布、state-derived outcome和U分布。

### 6. Generator / split

- train：上列prior，history check schedule由behavior policy；randomized-probe占20%。
- validation：initial correlation `Corr(x0,x1)` 分层取 `{-0.35,0,+0.35}`，但marginal scale不变。
- frozen-test：60%沿用train prior；20%为Q1/Q2稀疏史（历史仅一个targeted check）；20%为check order组合holdout（train中未连续出现Q2→Q1，test强制该顺序），transition/observation kernels不变。
- 每split对class与每种末次check分层；test不把class或schedule ID暴露给candidate。

### 7. 配对反例 / probe

1. **相同末次表型、不同belief**：pair的cut-time Q0值精确相同；一条历史在早期Q1支持`x0>0`，另一条Q2/轨迹支持`x0<0`。构造器用条件Gaussian抽样并只接受 `D_oracle>=0.25` 且最优action集合不交的pair。
2. **belief-equivalent pair**：搜索两组不同Q1/Q2值，使class mixture weights及每component的information vector/matrix在`1e-10`内相等；未来oracle distance `<0.005`。用于惩罚保存无效raw history。
3. **irreducible ambiguity pair**：public history逐bytes相同、private realized `c`相反；cut时state/output必须相同。以后允许check可能分开posterior，但候选不得在结果available前猜realized truth。

### 8. Margins 与主要失败判据

```text
outcome_scale=2.5, utility_scale=10.0
epsilon_equivalent=0.01
delta_distinguishable=0.20
catastrophic_regret=0.50
```

major failure：把posterior强制one-hot、Q1/Q2 available前更新、mixture moment collapse导致action sign错误、H=4 natural trajectory normalized-W1>0.20。exact dangerous collision或private class泄漏仍为hard failure。

---

## W03：相同当前表型、不同自然动力学

### 1. Hidden state / parameters 与诊断真值

```text
x_k scalar
c in {C0,C1}; s_C0=-1, s_C1=+1; P=0.5
drift magnitude d ~ Uniform(0.20,0.30), fixed per episode
sigma_process=0.035
```

`c`表示动力学方向；diagnostic truth=`c`。当前routine phenotype只测`x_0`，不直接显示`c,d`。

### 2. Transition equations

```text
u(NoNewAction)=0, u(A1)=-1, u(A2)=+1
x_{k+1}=x_k + d*s_c + 0.30*u(a_k) + epsilon_{k+1}
epsilon~N(0,0.035^2)
```

A1抵消上升型，A2抵消下降型；错误方向会加速偏离0。

### 3. Observation process、checks/actions

- Q0：`obs_0=x+N(0,0.04^2)`，delay=0，cost=0；历史每步都有。
- Q1：`obs_1=x+N(0,0.015^2)`，delay=1，cost=0.03。
- A1/A2 single或constant。policy set P0–P4，另有Q1-then-one-step correction policy。

### 4. Factual behavior policy

令 `slope_hat=last(Q0)-previous(Q0)`，不足2条取0：

```text
logit(NoNewAction)=0.4
logit(A1)=+2.0*slope_hat
logit(A2)=-2.0*slope_hat
Pr(Q1)=0.15+0.35*sigmoid(|slope_hat|-0.12)
```

各decision混入10% uniform；不读取c/d。

### 5. Counterfactual oracle 与 utility

给定 `c,d` 时是linear Gaussian；oracle对d的truncated-uniform posterior做64-point Gauss-Legendre，class精确枚举，reference用Sobol。输出future x/obs/U。

```text
U=-sum_{j=1..H} gamma^(j-1)*(x_j^2+0.04*u_j^2+0.03*I(Q1_j))
gamma=0.97
```

### 6. Generator / split

- train：`d in [0.20,0.27]`，一般trajectory由方程生成；每class各半。
- validation：`d in [0.20,0.30]`，加入20% exact-current-match pairs。
- frozen-test：`d in [0.23,0.30]`；40%为current-match family，20%为历史采样缺一条但仍可从趋势推断，40%普通。
- exact-current-match生成：先采 `v_-2` 和future noise tape，分别反向解两个class的 `x_-2,x_-1` 并选择Q0 observation noise，使两个`obs_0(k=0)` canonical value相同到`1e-12`；早期trend方向相反。conditioning/rejection权重由oracle修正，不能把pair当普通population样本算校准。

### 7. 配对反例 / probe

1. **核心碰撞 pair**：cut时所有当前Q0/Q1数值相同，前两步趋势相反；C0/C1在P0下H=4自然future均值至少相差1.6，最优constant action相反。
2. **时间顺序攻击**：同一multiset的三条Q0被按正确与反序时间排列；它们不是等价史，未来方向相反。只做bag aggregation会碰撞。
3. **等价额外记录**：同一trajectory追加一个明确标记为retracted/invalid、从未成为ObservationAvailable的order record；public clinical semantics不变，不应拆state。

### 8. Margins 与主要失败判据

```text
outcome_scale=1.5, utility_scale=6.0
epsilon_equivalent=0.005
delta_distinguishable=0.30
catastrophic_regret=0.60
```

核心pair任何exact合并均为dangerous hard failure。只看current snapshot、忽略event order、natural forecast effect-sign错、诊断posterior不随trend更新为major failure。

---

## W04：相同自然病程、不同治疗响应

### 1. Hidden state / parameters 与诊断真值

```text
x_k scalar
c in {C0,C1}; g_C0=+1, g_C1=-1; P=0.5
rho=0.92; b=0.15; sigma_process=0.04
```

在所有NoNewAction/no-new-action分支，`c`不进入自然动力学；它只调制治疗方向。diagnostic truth=`c`，其行为意义来自treatment response而非untreated phenotype。

### 2. Transition equations

令 `u(NoNewAction)=0,u(A1)=+1,u(A2)=-1`：

```text
x_{k+1}=rho*x_k+b-0.45*g_c*u(a_k)+epsilon_{k+1}
epsilon~N(0,0.04^2)
```

因此A1对C0降低x、对C1升高x；A2反之。NoNewAction时两个class完全同分布。

### 3. Observation process、checks/actions

- Q0 routine：`obs_0=x+N(0,0.05^2)`，delay=0，cost=0，每步自动。
- Q1 response marker：binary `obs_1 in {-1,+1}`，`Pr(obs_1=g_c)=0.95`，delay=1，cost=0.06；它是中性可测marker，不是class ID。
- history randomized micro-probe A1可在k=-4出现；其effect在k=-3通过Q0可见，随后generator用A2 washout使cut-time x匹配。candidate只见真实actions/results，不见c。
- treatments A1/A2；P0–P4全部oracle化，另有Q1-result-adaptive：`obs_1=+1 -> A1`, `-1 -> A2`。

### 4. Factual behavior policy

```text
Pr(Q1 at a decision)=0.25
logit(NoNewAction)=0.2
logit(A1)=+0.8*latest_obs_1 (missing=>0)
logit(A2)=-0.8*latest_obs_1
```

另混10% uniform，且30%训练episode在pre-cut做随机micro-probe；policy只看available marker/Q0。propensity完整记录。

### 5. Counterfactual oracle 与 utility

class枚举、continuous linear Gaussian exact。no-op rollout必须证明两个class在相同x posterior下完全相同；A1/A2 effect contrast必须反号。

```text
U=-sum gamma^(j-1)*(x_j^2+0.06*I(a_j!=NoNewAction)+0.06*I(Q1_j))
gamma=0.97
```

judge用posterior expected U，不能用realized c替candidate选择。

### 6. Generator / split

- train：`x_-4~Uniform(-0.5,1.2)`；Q1敏感度/特异度固定0.95；micro-probe与无probe均有support。
- validation：20% marker缺失、20% marker矛盾（由合法5% error生成）、60%普通。
- frozen-test：30% exact-phenotype opposite-response pairs，20%仅靠old micro-probe可辨、20% noisy/discordant marker、30%普通。test不更改marker error rate。
- class balance在每个availability pattern内各半；禁止由缺失模式泄漏class。

### 7. 配对反例 / probe

1. **核心危险pair**：两个history的最近三次Q0和cut-time x posterior相同到`1e-8`，但一个早期Q1/micro-probe支持C0，另一个支持C1；P0未来相同，A1/A2 treatment effect sign相反，最优action sets不交。
2. **不可识别pair**：public prefix逐bytes相同、private class相反且无Q1/probe；正确state是50/50 belief，不得泄漏地拆为realized class。
3. **自然预测等价pair**：相同x posterior但class posterior不同；若query scope仅P0，其natural trajectory必须一致；完整scope仍必须因A1/A2而区分。报告scope-sensitive collision而不是把natural head强行分开。

### 8. Margins 与主要失败判据

```text
outcome_scale=1.8, utility_scale=7.0
epsilon_equivalent=0.005
delta_distinguishable=0.35
catastrophic_regret=0.75
```

核心pair合并或A1/A2 effect sign任一反转是hard failure；仅凭no-op充分性压缩掉`c`是representation failure；不可识别prefix输出高置信class是leak/calibration major failure。

---

## W05：治疗只改变内部状态，观察响应延迟

### 1. Hidden state / parameters 与诊断真值

augmented Markov state：

```text
x_k scalar                 # internal level
r_k scalar                 # internal treatment-effect reservoir
c in {C0,C1}; lambda_C0=0.35, lambda_C1=0.65
D_k=[x_k,x_{k-1},x_{k-2}]  # judge delay buffer
P(c)=0.5
```

class决定effect reservoir清除速度；diagnostic truth=`c`。treatment不直接写observation，只有内部x变化在固定两步后被routine channel看到。

### 2. Transition equations

令 dose `u(NoNewAction)=0,u(A1)=1,u(A2)=-1`：

```text
r_{k+1}=lambda_c*r_k+0.80*u(a_k)
x_{k+1}=0.94*x_k+0.12-0.50*r_{k+1}+epsilon_{k+1}
epsilon~N(0,0.045^2)
D_{k+1}=[x_{k+1},x_k,x_{k-1}]
```

A1推动内部x下降，A2反向；既往dose在no-new-action下仍按lambda衰减，不能被no-op擦除。

### 3. Observation process、checks/actions

- Q0 delayed routine：在k+1 nominally collected，但值为`obs_0=x_{k-1}+eta`, `eta~N(0,0.05^2)`；`available_at=k+1`。等价为固定physiological/reporting lag=2。
- Q1 internal-fast check：`obs_1=x_{k+1}+N(0,0.10^2)`，delay=1，cost=0.08；提供可选较快但噪声更高的probe。
- A1/A2 single/constant；P0–P4，加Q1-after-dose policy。
- performed action本身在decision time立即public；不能等到Q0变化才更新state。

### 4. Factual behavior policy

令 `y` 为最新available Q0，`dy`为最近两条Q0差：

```text
action logits=[0.3, +0.9*y+0.4*dy, -0.9*y-0.4*dy]
Pr(Q1)=0.10+0.35*sigmoid(|dy|-0.15)
```

混10% uniform。policy不知道x/r/c，仅看public delayed stream和performed history。

### 5. Counterfactual oracle 与 utility

对每个class在augmented `[x,r,D]` 上做exact linear-Gaussian filter/rollout；class mixture不collapse。future observation distribution必须反映两步延迟，latent outcome/utility按current internal x算。

```text
U=-sum gamma^(j-1)*(x_j^2+0.05*I(A1/A2)+0.08*I(Q1))
gamma=0.97
```

counterfactual fork保留cut前r；P0仅停止新增动作，不清零r。

### 6. Generator / split

- train：`x_-4~Uniform(0,1.5)`, `r_-4~Uniform(-0.3,0.3)`；每class各半；history中至少一次action的episode占50%。
- validation：dose-to-cut gap分层 `{0,1,2,3}`，Q1 presence各半。
- frozen-test：25% action刚发生但Q0尚无变化；25%既往action residual仍在；20% fast/slow clearance class对照；30%普通。constant与single-dose均有support。
- history generator必须保存完整delay buffer private truth，但public只出现已有Q0/Q1。

### 7. 配对反例 / probe

1. **核心延迟pair**：同一pre-action public history fork为实际A1与NoNewAction；A1 event已public，但接下来两条Q0通过common-noise构造成相同。内部`x,r`和H=4 utility明显不同，state必须在action update时已分开。
2. **no-op residual pair**：cut-time Q0相同，一个history刚有A1且`r>0`，另一个无暴露`r=0`。查询P0时前者仍继续内部效应；若no-op清零或忽略r将碰撞。
3. **available-before-response leak pair**：prefix逐bytes相同但private未来Q0一个改善、一个不改善；response available前state/output必须exact相同，available后通过update才可分开。
4. **replay pair**：performed action与晚到Q1按batch或sequential update，最终行为一致。

### 8. Margins 与主要失败判据

```text
outcome_scale=2.0, utility_scale=8.0
epsilon_equivalent=0.01
delta_distinguishable=0.30
catastrophic_regret=0.65
```

把即时Q0不变解释为治疗无效、直到response才更新action、no-op清除r、把future response偷进prior state，均为major/hard语义失败；核心pair危险合并为hard failure。

---

## W06：治疗只改变观察通道

### 1. Hidden state / parameters 与诊断真值

```text
x_k scalar                  # physiological state
r_k scalar                  # observation-channel exposure, not physiology
c in {C0,C1}; rho_C0=0.88, rho_C1=0.97
b_C0=0.08, b_C1=0.03
P(c)=0.5
```

`c` 是自然动力学类，diagnostic truth=`c`。A1绝不进入`x`方程；它只让routine读数暂时下降。`r`属于执行正确观测模型所需的channel state，不能被解释成病理改善。

### 2. Transition equations

```text
x_{k+1}=rho_c*x_k+b_c+epsilon_{k+1}, epsilon~N(0,0.04^2)
r_{k+1}=0.25*r_k+I(a_k=A1)
```

NoNewAction=no new action；本世界无A2。即使A1反复给药，`x`的counterfactual分布与P0完全相同（在common noise下unit-level `x`也相同）。

### 3. Observation process、checks/actions

- Q0 channel-sensitive routine：`obs_0=x_{k+1}-0.75*r_{k+1}+N(0,0.05^2)`，delay=0，cost=0。
- Q1 channel-independent check：`obs_1=x_{k+1}+N(0,0.08^2)`，delay=1，cost=0.10。
- A1：channel-shift action，single/constant；每dose utility cost=0.30。
- policy set：P0、P1(single A1)、P3(constant A1)、Q1-only，以及`Q1 then never A1`。A1后读数降低不是internal outcome。

### 4. Factual behavior policy

令`y`为最新available Q0：

```text
Pr(A1)=0.10+0.75*sigmoid(1.4*(y-0.45))
Pr(Q1)=0.08+0.35*sigmoid(|y-0.50|-0.25)
```

各自混入10% uniform/no-action。policy只读public y；A1更常用于高读数，形成会诱骗关联模型的日志，但本世界的do-effect仍严格为0。

### 5. Counterfactual oracle 与 utility

oracle在augmented `[x,r]` 上做class-mixture Kalman filter。必须分别输出latent-outcome和channel observation：

```text
U=-sum gamma^(j-1)*(x_j^2
   +0.60*max(0, E[obs_0_j | x_j,r_j])^2
   +0.30*I(a_j=A1)+0.10*I(q_j=Q1))
gamma=0.97
```

对任意cut history：

```text
P(x_future | do(A1),H) == P(x_future | do(NoNewAction),H)
ATE_x(A1 vs NoNewAction)=0
ATE_obs0(A1 vs NoNewAction)<0
```

解析oracle与独立SCM fork必须逐episode验证第一式在floating tolerance `1e-12` 内成立。

### 6. Generator / split

- train：`x_-4~Uniform(0,1.4)`, `r_-4=0`；40% history含A1；每class各半。
- validation：dose-to-cut gap `{0,1,2,3}` 与Q1有/无分层。
- frozen-test：30% masked-high-state pairs，20% A1 constant后Q0表面正常，20%Q1 delayed，30%普通；另保留同prefix/private future swap。
- action assignment 在给定 public history 后与 hidden truth 条件独立；边际上允许因 public y 与 class/x 相关。

### 7. 配对反例 / probe

1. **masked-state核心pair**：构造`(x=0.55,r=0)`和`(x=1.30,r=1)`，共用noise使cut Q0均为0.55；histories中的performed A1不同且可见。后者latent risk高、channel rebound明显。fixture只接受“低x侧NoNewAction、高x侧A1”的oracle最优集合不交实例：A1只带来surface utility而不改善x；只存当前读数会危险合并。
2. **channel-vs-cure pair**：同一pre-action state fork A1/P0；下一步Q0显著不同但`x`和所有不含action-cost的latent outcomes逐sample完全相同。若候选预测A1改善x即观察条件/干预语义混淆。
3. **future-result leak pair**：cut prefix相同，private未来Q1相反；Q1 available前state/hash/output相同。
4. **equivalent decay pair**：两种dose history产生相同posterior `(x,r,c)`，但raw action条数不同；未来behavior相同，测试false split/完整历史暗存。

### 8. Margins 与主要失败判据

```text
outcome_scale=1.5, utility_scale=5.0
epsilon_equivalent=0.005
delta_distinguishable=0.25
catastrophic_regret=0.30
```

预测`A1`对latent x有绝对ATE `>0.03`、将Q0下降等同x恢复、或不能复现“surface relief但latent不变”均为major；masked pair若合并并产生不相交最优动作/regret≥0.30，为exact dangerous collision hard failure。

---

## W07：治疗同时改变内部状态和观察通道

### 1. Hidden state / parameters 与诊断真值

```text
x_k scalar                  # physiological state
r_k scalar                  # channel exposure
c in {C0,C1}; beta_C0=0.18, beta_C1=0.30
rho=0.95; b=0.12; P(c)=0.5
```

`c`决定真实state response强度，diagnostic truth=`c`。动作既经`beta_c`改变x，又经更大的channel shift改变Q0；两条路径不可合并。

### 2. Transition equations

剂量`dose(NoNewAction)=0,dose(A1)=1,dose(A2)=2`：

```text
r_{k+1}=0.35*r_k+dose(a_k)
x_{k+1}=rho*x_k+b-beta_c*dose(a_k)+epsilon_{k+1}
epsilon~N(0,0.045^2)
```

### 3. Observation process、checks/actions

```text
Q0: obs_0=x_{k+1}-0.55*r_{k+1}+N(0,0.05^2), delay=0, cost=0
Q1: obs_1=x_{k+1}+N(0,0.09^2),             delay=1, cost=0.10
```

A1/A2可single/constant。P0–P4全部oracle化，并有Q1-result-adaptive dose policy：posterior `E[x]>0.8`给A2，`0.35..0.8`给A1，否则NoNewAction。

### 4. Factual behavior policy

令`y`为最新Q0：

```text
logit(NoNewAction)=0.2
logit(A1)=1.0*(y-0.25)
logit(A2)=1.5*(y-0.75)
Pr(Q1)=0.10+0.40*sigmoid(|y-0.45|-0.25)
```

action/check各混10% uniform；不读取x/r/c。

### 5. Counterfactual oracle 与 utility

class-mixture augmented Kalman exact。oracle必须分解但评分不要求候选显式分解：

```text
total Q0 contrast = state-mediated contrast + channel contrast
state-mediated mean contrast at j=1 = -beta_c*dose
channel contrast at j=1 = -0.55*dose
```

```text
U=-sum gamma^(j-1)*(x_j^2+0.04*dose_j^2+0.10*I(Q1))
gamma=0.97
```

高dose可能因state benefit值得，也可能因quadratic cost不值得；judge从完整posterior算expected U。

### 6. Generator / split

- train：`x_-4~Uniform(0,1.6)`, `r_-4~Uniform(0,0.5)`；class/dose balance由randomized 20% probe保证。
- validation：dose-to-cut gap和Q1availability全组合。
- frozen-test：25%相同Q0但不同`x,r`；25% immediate Q0 improvement远大于latent improvement；20% C0/C1 response-strength contrast；30%普通。
- train不出现`A2→A1`两步sequence；frozen-test 15%使用该组合，以测operator composition而不是world-ID branch。

### 7. 配对反例 / probe

1. **same-readout不同internal pair**：选任意`v in [0.45,0.75]`，构造untreated `(x=v,r=0)`与treated `(x=v+0.55,r=1)`，Q0相同；history/action可区分。未来latent、Q1和最优dose不同。
2. **direct+mediated decomposition pair**：同一pre-state forkA1/P0；candidate需预测Q0大幅变、x仅按beta小幅变。若把全部Q0 contrast写入x，会在H=4和Q1上失败。
3. **response-class pair**：相同current x/r/Q0，但早期Q1 response支持C0或C1；A2效应量不同，某些边界episode最优A1/A2不同。
4. **hypothetical purity pair**：先query A2再queryP0与反序调用，所有输出/state bytes相同；query不能累积r。

### 8. Margins 与主要失败判据

```text
outcome_scale=1.8, utility_scale=6.0
epsilon_equivalent=0.01
delta_distinguishable=0.25
catastrophic_regret=0.45
```

把全部observed contrast当state effect、把动作只当channel effect而漏掉真实beta、hypothetical query改变factual r、或same-readout pair危险合并为major/hard failure。

---

## W08：异步、延迟和不规则观察

### 1. Hidden state / parameters 与诊断真值

本世界一个基础单位含4个microtick，`Delta=0.25`。history为`n=-16..0`，H={4,16,32} microticks，分别对应1/4/8基础单位。

```text
x_n=[x0_n,x1_n]^T
c in {C0,C1}, P=0.5
F_C0=[[-0.08, 0.04],[-0.02,-0.12]]
F_C1=[[-0.04,-0.06],[ 0.05,-0.10]]
B=[-0.28,0.10]^T
sigma=diag([0.05,0.05])
L_n=(x_n,x_{n-1},...,x_{n-8})  # private lag buffer
e_n in {-1,0,+1}                 # currently active signed exposure
m_n in {0,1,2,3,4}               # remaining microticks in current course
```

诊断真值=`c`。候选必须从带occurred/collected/available time的public事件递推belief。

### 2. Transition equations

```text
dose(NoNewAction)=0,dose(A1)=+1,dose(A2)=-1
u_n = e_n if m_n>0 else 0
x_{n+1}=x_n+Delta*(F_c*x_n+B*u_n)+sqrt(Delta)*sigma*epsilon_{n+1}
epsilon~N(0,I)
```

Treatment course只能在每4个microtick的decision boundary开始；选择 A1/A2 后令 `(e_n,m_n)=(+1,4)` 或 `(-1,4)`，每次transition后 `m_{n+1}=max(m_n-1,0)`，到0时`e=0`。performed event在course起始tick可见。mid-course cut时：`NoNewAction`不启动新course但已performed course完成剩余ticks；`ContinueCurrent`在下一boundary按同方向再启动4 ticks；`StopControllable`从当前tick起令`m=0,e=0`，并产生显式performed stop event。

### 3. Observation process、checks/actions

- Q0：在任意microtick采`obs_0=x0_n+N(0,0.10^2)`；delay `d0 in {0,1,4,8}`，概率`{0.35,0.30,0.25,0.10}`。
- Q1：采`obs_1=x1_n+N(0,0.10^2)`；delay `d1 in {1,3,6}`，概率`{0.40,0.35,0.25}`。
- `TestOrdered.occurred_at=order time`；`TestPerformed.occurred_at=collected_at=n`；其 `ObservationAvailable.occurred_at=collected_at=n, available_at=n+d`。result payload不得在available前出现。
- Q0/Q1 cost=0.03；A1/A2为相反方向控制。
- policy set含：P0、A1/A2持续4 ticks、constant每boundary重复、Q0/Q1-only，以及两条adaptive policy：result available后若`obs>0`在下一boundary A1，否则A2。未来尚未available的已采样结果属于factual private queue，counterfactual fork保留其存在但不能给candidate。

### 4. Factual behavior policy

在每个microtick，以最后available observation `y`（无则0）决定是否order check：

```text
Pr(order any check)=0.12+0.30*sigmoid(|y|-0.45)
Pr(Q0 | order)=0.55
```

每4 ticks的treatment logits `[0.2, +0.8*y, -0.8*y]`；均混10% uniform。policy只读available events，绝不读已采未回结果。

### 5. Counterfactual oracle 与 utility

对每个class使用包含9个lag state的linear-Gaussian filter；late result按其`collected_at`更新对应lag component，再把信息向当前传播（out-of-sequence Kalman update）。class weight由marginal likelihood更新。独立reference使用batch Gaussian conditioning整段已available measurement design matrix，必须与incremental oracle在mean/cov `1e-8`内一致。

```text
U=-sum_{microtick j=1..H} Delta*gamma^(j-1)*
   (x0_j^2+0.6*x1_j^2+0.04*u_j^2)
   -0.03*(number of checks ordered)
gamma=0.995
```

### 6. Generator / split

- train：Q0 delays `{0,1,4}`，Q1 delays `{1,3}`；irregular schedule由behavior生成。
- validation：加入Q1 delay=6及同timestamp多结果batch；不加入Q0 delay=8。
- frozen-test：完整delay support；20% out-of-order arrival，15% `available_at=cut`边界，15% `cut+1`，20%相同clinical samples不同availability schedule，30%普通。
- test的长delay仍在公开catalog声明support中；隐藏的是draw，不是存在性。
- timestamp均为integer microtick序列化，不用浮点，防0.1 boundary歧义。

### 7. 配对反例 / probe

1. **identical-prefix future swap**：同一public bytes，private late result/future noise相反；cut前state/output必须byte-identical。
2. **collection-time collision pair**：cut时最后available数值相同，一个采于`n=0`、另一个采于`n=-8`且刚available；它们对current x的信息不同，未来behavior distance需≥0.25。
3. **availability-equivalent pair**：相同collection/value/actions，结果一个早到一个晚到；若两者在cut前没有改变任何factual decision且cut时都available，则batch oracle posterior相同。candidate behavior应相同，测试是否无意义保留delivery history。
4. **boundary pair**：`available_at=cut`必须见；`cut+1`必须不可见。仅改private未到result不得改state。
5. **batch/sequential pair**：同cut同一组新available events按一个batch或canonical sequential update，最终behavior一致。

### 8. Margins 与主要失败判据

```text
outcome_scale=2.5, utility_scale=10.0
epsilon_equivalent=0.01
delta_distinguishable=0.22
catastrophic_regret=0.55
```

按occurred/collected而非available泄漏、忽略collection timestamp、晚到结果回写并改变旧cut state、batch/order不一致、或query时偷读pending result均为hard/major failure。

---

## W09：个体基线不同

### 1. Hidden state / parameters 与诊断真值

```text
b static scalar baseline
x_k scalar deviation from baseline
c in {C0,C1}; rho_C0=0.78, rho_C1=0.96
P(c)=0.5
absolute level l_k=b+x_k
```

基线`b`不是疾病/机制；它改变相同absolute observation的解释。diagnostic truth是四类`C00/C01/C10/C11`：第一位为dynamic class c，第二位为cut deviation indicator `I(x_0>=0.55)`。oracle diagnosis保留threshold附近不确定性。

### 2. Transition equations

剂量`dose(NoNewAction)=0,dose(A1)=0.45,dose(A2)=0.80`：

```text
b_{k+1}=b_k
x_{k+1}=rho_c*x_k+0.08-dose(a_k)+epsilon_{k+1}
epsilon~N(0,0.04^2)
```

强动作在x已接近0时可能造成负向偏离；目标是`x=0`而不是absolute `l=0`。

### 3. Observation process、checks/actions

- Q0 absolute routine：`obs_0=b+x_{k+1}+N(0,0.05^2)`，delay=0，cost=0。
- Q1 baseline reference：`obs_1=b+N(0,0.04^2)`，delay=1，cost=0.06；历史baseline records是合法ContextAvailable/ObservationAvailable，不直接给private b。
- Q2 deviation-sensitive check：`obs_2=x_{k+1}+N(0,0.10^2)`，delay=1，cost=0.10。
- A1/A2 single/constant；P0–P4，加Q1/Q2-then-dose adaptive policy。

### 4. Factual behavior policy

只用public absolute值`y`和最近available baseline estimate`bhat`（缺失取population mean0）：

```text
z=y-bhat
logit(NoNewAction)=0.3
logit(A1)=0.8*z
logit(A2)=1.2*(z-0.45)
Pr(Q1)=0.12+0.25*I(no baseline result in history)
Pr(Q2)=0.08+0.25*sigmoid(|z|-0.40)
```

混10% uniform。policy对缺baseline时可能次优，但不读取真实b/x/c。

### 5. Counterfactual oracle 与 utility

对static b和dynamic x做augmented Kalman + class mixture；Q1更新b并通过posterior covariance更新x。utility只惩罚偏离个体baseline：

```text
U=-sum gamma^(j-1)*(x_j^2+0.05*I(A1)+0.10*I(A2)
                           +0.06*I(Q1)+0.10*I(Q2))
gamma=0.97
```

oracle另输出absolute future observations，确保状态既保留baseline也保留deviation。

### 6. Generator / split

- train：`b~Uniform(-0.8,0.8)`, `x_-4~Uniform(-0.2,1.0)`；70%有至少一条pre-cut Q1。
- validation：`b~Uniform(-1.0,1.0)`；baseline missingness分层。
- frozen-test：70%同validation；15% baseline壳`[-1.25,-1.0] U [1.0,1.25]`；15% anti-correlated组合（高b低x/低b高x）在train中稀少。每个b bin内class/deviation平衡。
- 缺Q1的概率仅由public random schedule决定，不能和diagnostic label私下关联。

### 7. 配对反例 / probe

1. **same-absolute核心pair**：`(b=0.20,x=0.80)`与`(b=0.80,x=0.20)`，共用noise使Q0=1.00；pre-cut Q1/baseline histories不同。前者需要强action，后者A2可能过度，最优action可不交。
2. **baseline uncertainty pair**：同Q0均值，一个有精确Q1、一个无baseline record；posterior mean可相同但variance/tail不同，risk-sensitiveexpected utility与check value不同。
3. **interior translation probe**：只在 `b,b+delta` 都距其split prior边界至少0.30且 `|delta|<=0.10` 时，同时平移b及absolute Q0/Q1；生成后由oracle筛选，只有treatment-contrast distance `<=epsilon_equivalent` 的pair才进入fixture。它是经oracle验证的近似等价probe，不宣称有界prior下全域exact平移不变；future absolute observation相应平移。
4. **private-b leak pair**：public prefix相同，private b/x分解不同且未做Q1/Q2；candidate必须保持mixture，不得猜true decomposition。

### 8. Margins 与主要失败判据

```text
outcome_scale=1.5, utility_scale=6.0
epsilon_equivalent=0.01
delta_distinguishable=0.28
catastrophic_regret=0.55
```

same-absolute pair碰撞、translation probe下treatment effect改变、未观测b被one-hot猜出、或强动作在低deviation者造成灾难regret均为major/hard failure。

---

## W10：多个观察共享同一个机制来源

### 1. Hidden state / parameters 与诊断真值

```text
x_k scalar shared mechanism activity
c in {C0,C1}; rho_C0=0.82, rho_C1=0.96; P=0.5
specimen shock s_{k,g}~N(0,0.25^2), shared within specimen group g
sensor loadings h=[1.0,0.8,1.2]
sensor noise eta_j~N(0,0.06^2), independent conditional on (x,s)
```

`c`是dynamics class，diagnostic truth=`c`。三个sensor不是三个独立机制证据；同一`specimen_uid`内共享`s`。specimen UID是随机去重/group key，alpha-renaming后语义不变。

### 2. Transition equations

```text
dose(NoNewAction)=0,dose(A1)=0.35,dose(A2)=0.65
x_{k+1}=rho_c*x_k+0.10-dose(a_k)+epsilon_{k+1}
epsilon~N(0,0.055^2)
```

### 3. Observation process、checks/actions

- Q0 single panel：一个specimen，一个sensor `obs_0=h0*x+s+eta0`，delay=0，cost=0.02。
- Q1 correlated full panel：同一specimen同时返回三sensor vector `y=h*x+s*1+eta`，joint covariance `Sigma=0.25^2*11^T+0.06^2*I`，delay=1，cost=0.05。
- Q2 independent replicate：两个不同specimen group，各测sensor0，independent `s`; delay=1，cost=0.10。
- A1/A2 single/constant；P0–P4，加Q1/Q2后按posterior tail `Pr(x>0.9)`选择dose的adaptive policies。

### 4. Factual behavior policy

令`y`为最新available sensor均值：

```text
Pr(Q0)=0.45
Pr(Q1)=0.30+0.15*sigmoid(y-0.5)
Pr(Q2)=1-Pr(Q0)-Pr(Q1)
action logits=[0.3,0.8*y,1.2*(y-0.7)]
```

check/action各混10% uniform。policy只能读available grouped observations，不能读x/s/c。

### 5. Counterfactual oracle 与 utility

每个class为scalar Kalman filter，但Q1必须使用完整joint covariance，不能把三sensor likelihood相乘为独立。对于prior `x~N(mu,P)`和同specimen panel：

```text
J_panel = h^T Sigma^{-1} h
v_panel = h^T Sigma^{-1} y
P_post^{-1}=P^{-1}+J_panel
mu_post=P_post*(P^{-1}*mu+v_panel)
```

Q2的两个specimen covariance block diagonal。oracle输出Gaussian tail event `E=I(x_H>0.9)`，并用它进入utility：

```text
U=-sum gamma^(j-1)*(x_j^2+0.05*I(A1)+0.12*I(A2)+check_cost)
  -1.5*I(max_{j<=H} x_j>0.9)
gamma=0.97
```

Gaussian first-crossing event用16个独立 Owen-scrambled Sobol replicates、每个`2^14` paths；以replicate间方差给99%误差界并要求半宽`<0.005`。mean/cov部分另有解析reference；单个固定Sobol序列不得自报普通MC SE。

### 6. Generator / split

- train：Q0/Q1/Q2全有support；同specimen panel占40%，独立replicate占20%；`x_-4~Uniform(0,1.2)`。
- validation：panel subset `{0,1}`, `{0,2}`, `{0,1,2}`及missing sensor组合。
- frozen-test：25% same-mean/different-grouping，20%高相关concordant panel，20% posterior-equivalent nullspace pairs，15%未见subset`{1,2}`，20%普通。
- 任何split中specimen UID随机且与c/x/s独立；同一个realized sample被duplicate event重复交付仅用于idempotence mutant，不算新证据。

### 7. 配对反例 / probe

1. **same values, different grouping**：三条相同sensor值，一条history来自同一specimen，另一条来自三个independent specimen；均值相同但posterior precision/tail risk不同。构造器只接受最优check/treatment或expected utility差达到delta的pair。
2. **posterior-equivalent nullspace pair**：对同一Q1 design，抽向量`z`满足`h^T Sigma^{-1} z=0`，令`y'=y+z`；两history raw panel不同但`J,v`相同，posterior及所有future behavior exact等价。保存full raw panel导致false split。
3. **concordant-overconfidence probe**：同specimen三sensor同时高；正确posterior variance受shared s下限限制。按独立likelihood会过度自信，诊断ECE/tail action regret暴露。
4. **duplicate-event pair**：同一event_uid被重发与只发一次必须idempotent；换UID但明确`specimen_uid+collected_at+assay slot`相同的duplicate按schema typed reject，不能当独立机制证据。
5. **independent-evidence pair**：与duplicate相反，两个不同specimen UID是真正独立证据；把所有相关表型一概折叠也会漏信息。

### 8. Margins 与主要失败判据

```text
outcome_scale=1.6, utility_scale=7.0
epsilon_equivalent=0.008
delta_distinguishable=0.22
catastrophic_regret=0.50
```

把同specimen sensors当条件独立导致posterior variance低估>30%、same-group/different-group pair碰撞、nullspace pair严重false split、duplicate非幂等、或独立replicates被错误折叠，均为major；若引发相反最优动作/灾难regret则hard failure。

---

## 11. W01–W10 实现清单与 freeze 前自证

正式合并/冻结前，每个 world module 必须 materialize 下列对象；只有文字存在不算 benchmark 可执行：

```text
WorldSpec
  .semantic_version
  .public_catalog                 # neutral IDs, no W/case/test identity
  .hidden_state_schema
  .parameter_schema_and_support
  .transition(state, performed_action, exogenous)
  .collect(check, state, exogenous)
  .availability_queue
  .behavior_policy(public_history) -> action/check propensities
  .public_projection(private_episode, cut)
  .diagnostic_oracle(public_history)
  .counterfactual_oracle(public_history, policy, horizon)
  .utility(private_trajectory, performed_actions/checks)
  .train_generator(seed)
  .validation_generator(seed)
  .private_test_generator(committed_seed)
  .probe_pair_generator(committed_seed)
  .margins
```

必须有两个独立oracle路径：生产oracle与reference enumerator/analytic solution，不得互相调用同一核心transition helper后声称独立。freeze gate至少运行：

1. 同seed生成exact bytes；不同split无private tape digest重复；
2. public projection字段allow-list与poison accessor测试；
3. W01–W10每个policy/horizon均有oracle distribution、utility与finite normalization；
4. factual behavior propensity只依赖public prefix，counterfactual replay不能改变pre-cut propensity；
5. pair generator确实达到声明的`epsilon/delta`，未达到就重抽而不是降低margin；
6. W04 NoNewAction class invariance、W06 latent ATE=0、W07 dual-path decomposition、W08 batch/incremental oracle、W09 translation关系、W10 joint covariance sufficient statistics均通过代数/metamorphic test；
7. identical-prefix private future swap对candidate request bytes exact相同；
8. test/world/pair/split/seed/true-state/future字段不在worker address space；
9. all raw outcomes可从private tape重放，aggregate可从raw judge rows重建；
10. 上述world-specific主要失败均至少有一个恶意negative-control candidate被杀死。

### 决定性边界

- W01–W10绿色只能证明这些有限world/scope上的证据，不能证明一般临床世界存在有限UCM。
- 同一public prefix对应不同private truth时，正确共享state是posterior/belief；不能把无法识别的realized truth当碰撞，也不能用泄漏“解决”。
- 新检查/新治疗改变行为等价关系时，应报告旧scope state不充分或扩展state；不得为测试编号写分支。
- 本文件没有实现候选，也没有修改正式`MICROWORLDS.md`；正式freeze必须由manifest逐byte覆盖生成器、oracle、schema、pair和margin。

---

## W11：不同机制产生相同观察

### 1. Hidden state / parameters 与诊断真值

```text
x_k=[x0_k,x1_k]>=0; c in {C0,C1}; P(c)=0.5
C0 initialization concentrates mass in x0; C1 in x1
```

诊断真值 `c` 表示当前主导机制；routine 总量不能单独辨别来源。

### 2. Transition equations

```text
x0_{k+1}=0.92*x0_k+0.08-0.42*I(A1)+epsilon0
x1_{k+1}=0.76*x1_k+0.20-0.42*I(A2)+epsilon1
epsilon_j~N(0,0.035^2); values reflected at 0
```

A1只作用x0，A2只作用x1；不同机制可在cut产生同一总量但自然衰减和治疗响应不同。

### 3. Observation process、allowed checks/actions

- Q0：`obs_0=x0+x1+N(0,0.05^2)`，delay=0，cost=0。
- Q1：`obs_1=x0-x1+N(0,0.08^2)`，delay=1，cost=0.07。
- actions：A1、A2 single/constant；policies 为 P0–P4、Q1-only、Q1-sign→A1/A2。

### 4. Factual behavior policy

令最新Q0为y：action logits `[NoNewAction, A1, A2]=[0.3,0.7y,0.7y]`；`Pr(Q1)=0.15+0.30*sigmoid(y-0.5)`，均混10% uniform。

### 5. Diagnostic truth、counterfactual oracle 与 utility

oracle为两类截断线性Gaussian mixture（生产用反射粒子/Sobol，reference用二维quadrature），从同一posterior fork全部policy。

```text
U=-sum gamma^(j-1)*((x0_j+x1_j)^2+0.25*x0_j*x1_j
   +0.06*I(A1/A2)+0.07*I(Q1)); gamma=0.97
```

输出 `P(c|H)`、自然/检查/干预轨迹和utility分布。

### 6. Train / validation / frozen-test

train覆盖单机制与20%混合状态；validation提高混合至35%；test为40% IID、30% same-Q0 opposite-source pairs、15% Q1缺失、15% Q1矛盾噪声。每个Q0 severity bin内class平衡。

### 7. 配对反例

核心pair为 `(x0=v,x1=0)` 与 `(0,v)`，Q0用common noise做成相同，既往Q1/轨迹提供来源证据；自然future和最优A1/A2相反。另造posterior等价但raw Q0/Q1历史不同的false-split pair。public prefix完全相同而private来源相反时，正确state是mixture，不得泄漏拆分。

### 8. Margins 与主要失败判据

`epsilon=0.01, delta=0.28, catastrophic_regret=0.55, outcome_scale=1.8, utility_scale=7`。按总量单轴合并核心pair、错误治疗靶向或把不可识别private source one-hot化为hard/major failure。

---

## W12：同一机制在不同宿主中产生不同观察

### 1. Hidden state / parameters 与诊断真值

```text
x_k>=0 shared mechanism activity
h in {0.60,1.40} host expression modifier
c=C0 iff h=0.60 else C1; P(c)=0.5
beta_h in {0.22,0.42}
```

诊断真值为host-response class `c`；x的机制身份相同，不把host另造疾病。

### 2. Transition equations

```text
x_{k+1}=0.91*x_k+0.10-beta_h*I(A1)+epsilon, epsilon~N(0,0.04^2)
```

A2为host-neutral gentle action：effect `-0.18`。h同时改变表达和A1 response。

### 3. Observation process、allowed checks/actions

- Q0：`obs_0=h*x+N(0,0.05^2)`，delay=0。
- Q1 host marker：`obs_1=h+N(0,0.06^2)`，delay=1，cost=0.06。
- Q2 direct mechanism：`obs_2=x+N(0,0.10^2)`，delay=1，cost=0.09。
- A1/A2 single/constant；加 Q1/Q2→posterior-optimal action policy。

### 4. Factual behavior policy

仅按最新Q0 y：logits `[0.3,0.9y,0.6y]`；无host marker时 `Pr(Q1)=0.30`，否则0.08；`Pr(Q2)=0.12+0.20*sigmoid(|y|-0.5)`；混10% uniform。

### 5. Diagnostic truth、counterfactual oracle 与 utility

host枚举、x Gaussian/quadrature mixture；不得用Q0大小直接替代x。

```text
U=-sum gamma^(j-1)*(x_j^2+0.20*(h*x_j)^2
  +0.06*I(A1/A2)+check_cost); gamma=0.97
```

oracle同时输出host-modified observation与shared mechanism trajectory。

### 6. Train / validation / frozen-test

train在两host内覆盖`x in [0,1.2]`；validation hold out一部分same-Q0组合；test 30% same-Q0/different-host、20% same-x/different-expression、20% marker missing、30% IID。host×x strata平衡，missingness只依public schedule。

### 7. 配对反例

`(h=.6,x=1.0)` 与 `(h=1.4,x=3/7)` 有相同Q0 mean=.6，但latent risk和A1 effect不同；历史Q1/Q2可区分。same-x/different-host pair则未来Q0不同但mechanism trajectory在NoNewAction下相同。完全相同prefix但private h不同应保留posterior而非猜truth。

### 8. Margins 与主要失败判据

`epsilon=.01, delta=.25, catastrophic_regret=.50, outcome_scale=1.6, utility_scale=6`。将expression强度当mechanism、漏掉host treatment modulation或same-Q0危险碰撞为major/hard failure。

---

## W13：非线性共病交互

### 1. Hidden state / parameters 与诊断真值

```text
x_k=[x0_k,x1_k] in [0,1.5]^2
c in {C0,C1,C2}: synergy, antagonism, threshold; balanced
phi_C0=+0.70*x0*x1
phi_C1=-0.35*min(x0,x1)
phi_C2=+1.00*max(x0*x1-0.36,0)
```

诊断真值 `c` 是interaction class，不是两个单机制label的拼接。

### 2. Transition equations

```text
z_k=phi_c(x_k)
x0_{k+1}=clip(.88*x0+.06+.12*z-.35*I(A1)+epsilon0,0,1.5)
x1_{k+1}=clip(.84*x1+.08+.12*z-.35*I(A2)+epsilon1,0,1.5)
epsilon_j~N(0,.03^2)
```

Composite(A1,A2)同时作用两式；interaction不是独立bonus，进入共同dynamics和outcome一次。

### 3. Observation process、allowed checks/actions

Q0=`x0+x1+noise(.05)`；Q1返回两分量各`noise(.08)`，delay=1,cost=.08；Q2=`z+noise(.07)`,delay=1,cost=.10。允许NoNewAction、A1、A2、Composite(A1,A2) single/constant和check-adaptive policies。

### 4. Factual behavior policy

按public Q0与最近Q1，softmax四动作 `[.3,.7*y,.7*y,1.0*(y-.8)]`；Q1/Q2各至少0.15概率，另10% uniform；不读c或private components。

### 5. Diagnostic truth、counterfactual oracle 与 utility

生产oracle为class枚举+16×`2^14` scrambled-Sobol路径；reference为固定二维grid/transition quadrature。

```text
U=-sum gamma^(j-1)*((x0+x1+z)^2+.05*dose_count+.08*Q1+.10*Q2)
gamma=.97
```

全部单独/联合action必须从同一posterior fork；禁止用单病效果相加冒充oracle。

### 6. Train / validation / frozen-test

train含单轴状态及组合矩形中60%的cells；validation含另20%；test冻结最后20%组合cells、threshold两侧`x0*x1=.36±.03`和三interaction class。各单轴值训练已见，holdout只在新组合/interaction region。

### 7. 配对反例

同一 `(x0+x1)` 与相同单轴marginals但interaction class/乘积不同，联合action效应和hazard不同；核心threshold pair跨`.36`且当前Q0几乎相同。false-split pair使用不同单轴路径收敛到同一 `(x0,x1,c)`。

### 8. Margins 与主要失败判据

`epsilon=.01, delta=.30, catastrophic_regret=.70, outcome_scale=2, utility_scale=9`。简单线性叠加导致联合action effect误差>20%、threshold pair合并、或为test组合写分支为major/hard failure。

---

## W14：路径依赖与滞后

### 1. Hidden state / parameters 与诊断真值

```text
x_k scalar current activity
r_k scalar finite path-memory
r_{k+1}=0.75*r_k+x_{k+1}
c=C0 if r_0<0.9 else C1
```

诊断真值是cut memory regime；同一current x可有不同r。

### 2. Transition equations

```text
x_{k+1}=.90*x_k+.08-.32*I(A1)+.10*tanh(r_k-1)+epsilon
r_{k+1}=.75*r_k+x_{k+1}; epsilon~N(0,.04^2)
```

A2清除部分memory而非立即x：`r_{k+1}`额外`-0.45`，x式不变。

### 3. Observation process、allowed checks/actions

Q0=`x+N(0,.05^2)`立即；Q1=`r+N(0,.10^2)`delay1,cost.08。允许A1/A2 single/constant、Q1-adaptive。history必须保留有时间顺序的Q0/actions。

### 4. Factual behavior policy

以最新Q0 y和近三步公开EWMA `rhat`：logits `[.3,.8y,.7rhat]`；`Pr(Q1)=.12+.30*sigmoid(rhat-.8)`；混10% uniform。

### 5. Diagnostic truth、counterfactual oracle 与 utility

augmented `[x,r]` class-free nonlinear filter，oracle class由posterior event `r<.9`读出。

```text
U=-sum gamma^(j-1)*(x_j^2+.45*r_j^2+.06*I(A1/A2)+.08*I(Q1)); gamma=.97
```

### 6. Train / validation / frozen-test

burn-in生成合法r。train覆盖单峰与短pulse history；validation覆盖间歇pulse；test 30% same-current/different-memory、20% same-sufficient-state/different-history、20%长gap、30% IID。

### 7. 配对反例

核心pair当前Q0/x相同，一条历史长期高x故r高，另一条短暂spike故r低；P0未来和A1/A2最优不同。false-split pair用不同早期轨迹但在cut达到相同posterior `(x,r)`；所有未来行为等价，不能保留完整路径冒充必要memory。

### 8. Margins 与主要失败判据

`epsilon=.01, delta=.28, catastrophic_regret=.60, outcome_scale=1.8, utility_scale=8`。snapshot collision、action lag错位>1 step、或相同充分统计仍按raw history拆分为major/hard failure。

---

## W15：隐藏混杂与可识别性（两个预注册子面板）

### 1. Hidden state / parameters 与诊断真值

两个子面板必须分开报告，不能平均：

```text
W15A: x_k severity, u static confounder, c=severity class
W15B: u~Bern(.5), m in {Mplus,Mminus} with prior .5; behavior A1 iff u=1
```

W15A有随机化识别锚；W15B两SCM产生exact相同observational law但do-effect相反。W15B diagnostic target只含可见severity/u posterior，**不含不可识别private m**。

### 2. Transition equations

W15A：

```text
x_{k+1}=.92*x_k+.20*u-.35*I(A1)+epsilon, epsilon~N(0,.04^2)
```

W15B为单步potential-outcome SCM，observed action `a=u` 且observed outcome总为`Y=a`：

```text
Mplus : Y(0)=0, Y(1)=1
Mminus: if u=0: [Y(0),Y(1)]=[0,-1]
        if u=1: [Y(0),Y(1)]=[2, 1]
```

故Mplus ATE=+1，Mminus ATE=-1，但 `(A,Y)` joint bytes相同。

### 3. Observation process、allowed checks/actions

W15A Q0 noisy x，Q1 noisy u；A1/NoNewAction。W15B public只含pre-action neutral context、performed A=`u`和随后Y；无测量能识别m。反事实queries仍为Do(A1)/NoNewAction，但W15B允许返回`unsupported/identified_set`。

### 4. Factual behavior policy

W15A：70%按public Q0 severity-driven `Pr(A1)=sigmoid(1.5y)`，30%由public randomized-arm event以0.5概率给A1；exact propensity记录。W15B：`A=u`，无overlap；不能伪造positivity。两者policy都不读取future。

### 5. Diagnostic truth、counterfactual oracle 与 utility

W15A oracle以随机ized arm识别SCM并算`P(x,u|H,do(a))`；utility=`-sum(x^2+.05A1)`。W15B可归责oracle是观测证据下的SCM posterior mixture/identified set：ATE support=`{-1,+1}`、mean=0；不得用private realized m给候选打点效应分。utility=`Y-.05*A1`，但treatment recommendation应abstain，因为最优action随m相反。

### 6. Train / validation / frozen-test

W15A train/val/test均固定30% randomized anchor，test hold out severity×u组合；另做ablation移除anchor但不混入主分。W15B三split对m各半、public observational corpus exact配对；private m仅judge保存。任何split都不把panel名或m传candidate。

### 7. 配对反例

W15A同Q0但Q1/u posterior不同；naive日志中A1患者结局更差，randomized do-effect仍改善。W15B twin pair public history逐bytes相同而private m相反；相同state/不确定effect是正确答案，不是collision；若候选凭private m拆分即leak。另以Mplus/Mminus分别fork相同u证明effect sign相反。

### 8. Margins 与主要失败判据

两panel共同 `epsilon=.005, delta=.35`；W15A `catastrophic_regret=.60`，W15B不对不可识别unit truth记regret，而记unsafe-confident rate。W15A把`P(Y|A,H)`当`P(Y|do(A),H)`或effect sign错为hard failure；W15B若窄区间排除±1、`unknown/unsupported<.5`且强配action为causal overclaim hard failure。正确诚实不确定不得扣成预测失败。

---

## W16：新增检查拆分旧状态（两阶段扩展）

### 1. Hidden state / parameters 与诊断真值

```text
x_k scalar; c in {C0,C1}, P=.5
Stage S0 diagnostic truth=E0 (single old-scope equivalence class)
Stage S1 diagnostic truth=c after new check catalog is activated
```

c在S0的所有允许future中完全无行为作用；旧state合并C0/C1是正确最小化，不是collision。

### 2. Transition equations

```text
x_{k+1}=.90*x_k+.10-.30*I(A1)+epsilon; epsilon~N(0,.04^2)
```

S0/S1 transition和treatment均不改；c只决定S1新检查的observation operator。

### 3. Observation process、allowed checks/actions

S0只含Q0=`x+N(0,.05^2)`和A1。候选、模型和一批S0 state先seal。S1才揭示Q2：binary `Pr(obs_2=1|C1)=.95, Pr(...|C0)=.05`，delay1,cost.08。Q2 result必须通过`update(old_Z,new_event)`；head不得重读history。S1 policy含Q2-only及Q2-result-adaptive A1/NoNewAction。

### 4. Factual behavior policy

S0按public Q0决定A1并混10%探索。S1 test factual arm以0.5概率order Q2，独立于c；result前后action仍只读已available public H。

### 5. Diagnostic truth、counterfactual oracle 与 utility

S0 oracle对c边缘化并验证所有C0/C1 histories behavior exact等价。S1 oracle增加Q2 future/result distribution和`P(c|Q2)`；utility=`-sum(x^2+.05A1+.08Q2)`，因此Q2主要提供diagnostic/readout信息。old state在见result前可合法给prior-predictive；result后必须局部细化。

### 6. 两阶段 train / validation / frozen-test

- S0 semantic freeze→train/val→candidate/model/state seals；extension pack digest预先commit但Q2 ID、参数、fixtures不揭示。
- seal后reveal S1 catalog/operator；禁止改S0 primary result。
- S1记录：无需retrain、局部operator fit、或full retrain；state schema migration bytes、core diff LOC、训练examples、旧benchmark回归均保存。
- frozen extension用512 episodes+256 branch pairs；不并入S0总分。

### 7. 配对反例

同一个sealed old state fork出Q2 result 0/1；update后diagnostic posterior相反且new state hash应不同。result available前private value swap必须exact同state/output。另以private c相反但S0 public behavior相同的pair确认旧scope不因真值泄漏false split。

### 8. Margins 与主要失败判据

S0 `epsilon=.005`；S1 `delta=.30, catastrophic_regret=.40`。新result后仍碰撞、head查询时重读完整history、或在available前分开为hard failure。旧state对未知Q2先报`scope_insufficient`是诚实限制，不算PASS但不作危险失败；高置信编造则hard。局部扩展成本进入Pareto。

---

## W17：新增治疗拆分旧状态（两阶段扩展）

### 1. Hidden state / parameters 与诊断真值

```text
x_k scalar; c in {C0,C1}; g_C0=+1,g_C1=-1
S0 diagnostic truth=E0; S1仍报告E0但治疗响应需c
```

history可含一次性neutral context `obs_1`（95%反映g），但S0没有可重复该context的check；它对S0未来完全无关，最小state可合法丢弃。

### 2. Transition equations

S0：

```text
x_{k+1}=.92*x_k+.10-.25*I(A1)+epsilon
```

S1新增A2后：

```text
x_{k+1}=.92*x_k+.10-.25*I(A1)-.55*g_c*I(A2)+epsilon
```

因此旧NoNewAction/A1行为对class相同，新A2 response方向相反。

### 3. Observation process、allowed checks/actions

Q0=`x+N(0,.05^2)`；S0 actions只有A1。S1 action catalog新增A2 single/constant；首次query直接作用于**已seal S0 state**，不提供raw history/context。若需迁移，只能在第一次query判定scope不足并返回`scope_insufficient`后，由runner明确授权offline replay并生成新state lineage，不能暗中读取history。

### 4. Factual behavior policy

S0按Q0选择A1并10%探索。S1独立extension corpus随机分配A2/NoNewAction以提供验证响应；assignment只读public H并记录propensity。

### 5. Diagnostic truth、counterfactual oracle 与 utility

S0 oracle验证class-conditioned全部future exact相同。S1枚举class belief并输出A2 opposite effects：

```text
U=-sum gamma^(j-1)*(x_j^2+.05*A1+.08*A2); gamma=.97
```

judge接受两种诚实结果：old Z已保留足够信息并正确预测；或明确`scope_insufficient`。不接受无证据高置信A2。

### 6. 两阶段 train / validation / frozen-test

同W16 seal/commit/reveal顺序；S1为512 episodes+256 old-state pairs。context在S0 train/val中存在但alias随机，不能泄漏extension。记录是否需history replay、schema migration、retrain examples/core diff和S0 regression；S1不能回写S0 score。

### 7. 配对反例

两history当前Q0/x及S0 oracle相同，早期context分别支持C0/C1；S0 behavior-equivalent，S1 A2 effect sign/最优action相反。若old Z合并，正确是scope_insufficient；若声称支持却给同一强action即dangerous collision。另测相同old Z在A2 query前后bytes不变。

### 8. Margins 与主要失败判据

S0 `epsilon=.005`；S1 `delta=.40, catastrophic_regret=.80`。scope_insufficient是`HONEST_LIMIT`，不算扩展PASS；高置信合并、query时偷偷re-encode history或静默改old state为hard failure。全重训可产生新候选版本但记最高extension cost，不能替换sealed result。

---

## W18：未见机制与可归责 OOD

### 1. Hidden state / parameters 与诊断真值

```text
x_k in [-1.5,1.5]
c in {C0,C1,C2}; train/val primary only C0,C1
s_C0=+1, s_C1=-1, s_C2=0
```

C2是frozen-test unseen mechanism。diagnostic schema含`unknown`；只在public history对known support有决定性反证时记“可归责 OOD”。

### 2. Transition equations

```text
x_{k+1}=rho_c*x_k+b_c-beta_c*I(A1)+epsilon
(rho,b,beta): C0=(.85,.10,.30), C1=(.85,-.10,-.30), C2=(.55,.35,-.55)
epsilon~Uniform(-.03,.03)
```

A1在C2方向与known常见选择不同，OOD上非abstain有真实风险。

### 3. Observation process、allowed checks/actions

Q0返回二元：`obs_0=x+eta0`, `obs_1=s_c*x+eta1`, `eta_j~Uniform(-.03,.03)`；Q1精密版noise±.01、cost.08。允许A1/NoNewAction和Q1-adaptive。连续值与IDs均不直接标C2。

### 4. Factual behavior policy

按public `obs_0` sign随机选择A1，minimum propensity .15；`Pr(Q1)=.20+.25*I(known-kernel residual>0.15)`，residual只由public catalog公式算，不读c。

### 5. Diagnostic truth、counterfactual oracle 与 utility

finite-class bounded-noise filter/interval enumerator。定义attributable mask：`max_{C0,C1} P(H|c)=0`（实现容差为support interval严格不交）或frozen Bayes factor `<1e-6`；C2但history与known overlap者标`OOD_IRREDUCIBLE`，不得因未猜出private c而处罚。

```text
U=-sum gamma^(j-1)*(x_j^2+.08*A1+.08*Q1); gamma=.97
```

OOD treatment应abstain/unsupported；judge另存private oracle仅算unsafe non-abstain regret。

### 6. Train / validation / frozen-test

train仅C0/C1；validation加入不同的公开development anomaly `Cdev(s=.5)`用于定OOD threshold，绝不出现C2；test固定20%C2，其中一半attributable、一半overlap/irreducible，另含20%低密度但合法known extremes防“稀有=OOD”。C2 prevalence与aliases不入request。

### 7. 配对反例

attributable C2 fixture取`|x|>=.5`，其`obs_1≈0`与known `±x` bounded support不交；known-extreme pair虽低密度仍满足某known invariant，不应拒绝。另造public prefix相同的C2/known-overlap pair，候选不得泄漏拆分。

### 8. Margins 与主要失败判据

`epsilon=.005, delta=.35, catastrophic_regret=.75`；预注册强配阈值 `known_probability>=.90, unknown<=.10`。attributable C2上强配且给unsafe A1为hard failure；known extreme误拒、OOD_IRREDUCIBLE被当可归责错误、或用world/test alias检测为major/hard。报告AUROC/AUPRC、FPR@95TPR、AURC和unsafe non-abstain，不只报accuracy。

---

## W19：罕见但严重的治疗禁忌（固定 tail）

### 1. Hidden state / parameters 与诊断真值

```text
x_k>=0; h in {0,1}; P_tail(h=1)=1/64 exactly by stratified family allocation
c=C0 if h=0 else C1
```

C1是contraindication tail；diagnostic truth=c。tail count不依随机seed是否“碰巧出现”。

### 2. Transition equations

```text
h=0: x_{k+1}=.9*x_k+.12-.50*I(A1)-.22*I(A2)+epsilon
h=1: x_{k+1}=.9*x_k+.12+1.40*I(A1)-.22*I(A2)+epsilon
epsilon~N(0,.04^2)
catastrophic_event=I(h=1 and A1 performed)
```

A1多数人强效、tail灾难；A2对所有人温和安全。

### 3. Observation process、allowed checks/actions

Q0=`x+N(0,.05^2)`；Q1 marker binary，sensitivity/specificity=.98，delay1,cost.08。允许A1/A2/no-action single/constant与Q1-adaptive；marker不是private h本身。

### 4. Factual behavior policy

按Q0给A1/A2且20%完全随机；有available positive Q1时A1 propensity仍保留.02用于识别但必须记录。policy只读public marker，不能读h。

### 5. Diagnostic truth、counterfactual oracle 与 utility

h mixture exact linear-Gaussian；catastrophic event为structural jump：

```text
U=-sum gamma^(j-1)*(x_j^2+.05*A1+.08*A2+.08*Q1)
  -30*I(catastrophic_event); gamma=.97
```

必须报告mean、p95、max、CVaR95、tail-only regret和catastrophic-action rate；均值不得抵消tail。

### 6. Train / validation / frozen-test

每4096 train固定64 tail、1024 validation固定16、2048 test固定32，位置由secret permutation；headline population metric按exact `1/64` mixture。另有256 tail/common配对probe但不进入population prevalence/aggregate mean。每split tail内marker true/false与action support按确定配额；任何raw tail不能被丢弃或oversample后冒充总体率。

### 7. 配对反例

相同Q0/x，早期Q1/response分别支持h=0/1；前者最优A1，后者最优A2/NoNewAction，A1 regret至少30。另有marker未做且public prefix相同/private h不同的pair，正确state为1% mixture而不是猜个体truth。

### 8. Margins 与主要失败判据

`epsilon=.005, delta=.45, catastrophic_regret=10, outcome_scale=2, utility_scale=30`。任何有可用marker证据的tail与common exact危险合并、tail给A1或用总体mean掩盖均为hard failure；tail recall/校准差但安全abstain记major而非伪PASS。

---

## W20：反馈环与治疗历史依赖

### 1. Hidden state / parameters 与诊断真值

```text
x_k scalar current activity
r_k>=0 exponentially decayed exposure memory
r_-4=0 and every subsequent performed dose is public
dose(A1)=1.0, dose(A2)=0.5
c=C0 if r_k<.75 else C1
```

诊断真值是cut response-memory regime。完整action history不是state truth；`(x,r)`是本世界的exact finite sufficient statistic。

### 2. Transition equations

```text
gain(r)=+.40 if r<.75 else -.35
x_{k+1}=.90*x_k+.10-gain(r_k)*dose(a_k)+epsilon, epsilon~N(0,.04^2)
r_{k+1}=.50*r_k+dose(a_k)
```

低暴露时dose降低x；高暴露时response反转并升高x。NoNewAction dose=0但r继续衰减；ContinueCurrent按显式schedule给dose。

### 3. Observation process、allowed checks/actions

Q0=`x+N(0,.05^2)`立即；Q1=`r+N(0,.08^2)`delay1,cost.08。允许A1/A2 single/constant、stop/continue和Q1-adaptive。Performed action必须立即更新r belief，即使Q0尚无变化。

### 4. Factual behavior policy

以public Q0 y及从performed history可算的`rhat`：logits `[.3,.9*y-.6*rhat,.6*y-.3*rhat]`；`Pr(Q1)=.10+.30*sigmoid(rhat-.6)`；混10% uniform。generator burn-in产生合法r，不暗置暴露。

### 5. Diagnostic truth、counterfactual oracle 与 utility

当前可执行 runtime 的 production oracle 使用 covariance-form Bayesian filter
加有限 branch enumeration；source-distinct reference 使用 information-form update
加独立实现的 enumeration。旧稿中的 scrambled-Sobol / r-grid quadrature 描述
不匹配实际执行路径，现不再作为 W20 实现声明。PRE-FREEZE upper-bound slice
把 public posterior mean/variance 与 `r` round 到 12 位，只支持当前
policy-conditioned marginal moments 与 expected-utility sanity；尚未证明 joint
temporal law、proper calibration 或 minimal quotient。当前 evaluator 已将 raw
history digest 与 `evidence_count` 留在独立 provenance，而不纳入 sealed behavior
state identity；合法额外 Q1 令 raw count 从 5 变 6 时，posterior、exposure、
state hash 与全部 9 个 horizon-4 policy semantics 均保持相同。这只关闭已知
counter false split，不构成完整 minimal quotient 证明。

```text
U=-sum gamma^(j-1)*(x_j^2+.06*dose_j^2+.08*Q1); gamma=.97
```

所有query从同一r posterior fork；hypothetical dose不得回写factual memory。

### 6. Train / validation / frozen-test

train覆盖单dose与washout；validation覆盖重复dose；test 25% same-Q0/different-r response-reversal、25% different-history/same-sufficient-state、20% stop/continue、15% threshold `.75±.03`、15% IID。原子dose和decay均在train，hidden只hold out组合。

### 7. 配对反例

- **暴露记忆碰撞**：当前Q0/x相同，一条history无近期dose使r低，另一条重复dose使r高；下一A1 effect sign和最优action相反。
- **充分统计false-split**：H1执行A1后一个NoNewAction step得到r=.5；H2最后一步执行A2得到r=.5，构造器反解初始x/common noise使cut `(x,r)` posterior相同。raw histories不同但全部future behavior等价。
- **purity**：A1/A2 query顺序、重复query和cold worker不得改变r/state。

### 8. Margins 与主要失败判据

`epsilon=.008, delta=.38, catastrophic_regret=.80, outcome_scale=1.8, utility_scale=8`。只看current x导致response-sign collision、no-op清零r、query累积memory为hard failure；保存整个history并持续拆分same `(x,r)` histories为false-split/紧凑性major failure。

---

## W11–W20 freeze 前最低自证

1. 每world materialize `generator/oracle/public_projection/policy_set/probe_pairs/margins`，production/reference oracle不共享核心计算路径。
2. W15A randomized anchor与W15B nonidentifiable twin分开出表；W15B不得用private SCM identity评分可归责point effect。
3. W16/W17严格按 `semantic/extension commitment → candidate/model/state seal → reveal → state-only first query → optional explicit migration` 执行，extension结果不回写primary。
4. W18 raw row必须带judge-only `OOD_ATTRIBUTABLE/OOD_IRREDUCIBLE/KNOWN_EXTREME`，但candidate request不能带；只有前者支持强制OOD归责。
5. W19 population fixed tail与额外probe分母分开，tail raw records一个不少；headline、tail、CVaR同时报告。
6. W20自动验证`(x,r)` Markov closure及两组不同history相同充分统计的oracle等价，避免“完整历史总是更安全”的伪结论。
7. 每个world至少一个恶意negative control被预期失败码杀死；所有private future swap在cut前生成exact相同candidate bytes。
