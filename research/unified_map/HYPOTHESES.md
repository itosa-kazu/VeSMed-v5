# Unified Clinical Map 可证伪假说登记册

> 状态：**Phase 1 预登记草案；benchmark v1 尚未冻结，尚无候选运行结果。**
> 用途：在实现候选前写下状态定义、预期优势、失败世界和杀死条件，防止看到结果后改写故事。
> 解释规则：本文的“预期”是待检验方向，不是已验证事实；W01–W20 的正式参数、阈值、seed、oracle 与 probe 以未来 freeze manifest 为准。

## 1. 共同判定框架

### 1.1 被检验的核心对象

每个普通候选必须给出同一递推患者状态：

```text
Z_t = Phi(H_t^public)
Z_t+ = U(Z_t, newly_available_events, performed_actions)
diagnosis = D(Z_t)
future(pi) = R(Z_t, pi)
```

`D` 与 `R` 可以是不同 head；患者特异信息只能来自同一 `Z_t`。自然病程和治疗预测必须共享 controlled transition core。任何需要 raw history、task-specific latent、oracle true state、actual future 或 test/world ID 的实现均不检验本文的正面 UCM 假说。

### 1.2 共同 hard gate

在比较性能前，每个共享候选必须通过：

- future/oracle/true-state/test-ID 隔离；
- exact state fan-out 与 fresh-process closure；
- head 不读历史、无患者 cache、模型只读；
- task-blind update 与单一 controlled rollout；
- no-op/continue/stop/do/planned/performed 语义；
- incremental/replay/batch/late-event 更新一致性；
- dangerous collision、OOD、可重复性与 raw evidence gate；
- semantic unity audit，或明确标 `INCOMPLETE` 而退出赢家主张。

HARD failure 不能由平均分补偿。通过后才比较 diagnosis、natural forecast、intervention forecast、regret tail、calibration、OOD、sample efficiency、false split、state size/slope、extension cost、latency/memory、interpretability 和 novel-readout transfer 的 Pareto 前沿。

### 1.3 公平比较条件

同一比较批次必须固定：

1. public train/validation API、共同 hidden corpus 和 episode budget；
2. action/test/observation catalog、horizon、utility 和输出 schema；
3. seeds 与 seed 抽取协议；
4. 是否给结构、参数、方程或 oracle family 的先验；
5. training compute、wall time、parameter/state-size 与 search budget；
6. calibration、abstention、OOD 和 invalid/unsupported 的分母；
7. source/model/dependency seal 与 raw result 保存规则。

若某家族拿到正确 simulator 结构或人工机制变量，而另一家族只拿 public data，必须分成 `oracle-structure`、`expert-structure`、`learned-structure` 等不同 track；不得把结构先验带来的优势冒充表示家族的学习优势。容量不可能完全相等时，至少报告 performance–data–compute–state-size Pareto，而不是只报一个赢家。

### 1.4 杀死假说的证据类型

- **表示失败**：增加合理训练/容量仍出现结构性危险碰撞、错误干预方向或更新不闭合。
- **识别失败**：表示可表达 oracle，但仅凭允许数据无法识别；必须明确依赖的随机化/结构假设。
- **优化失败**：oracle/解析版本可过，但学习版本不稳定；不能据此直接否定表示存在性。
- **实现失败**：协议、泄漏、不可重复或数值错误；该 run 无资格回答理论问题。
- **scope failure**：候选在旧 scope 成立，但新检查/治疗/horizon 使其不足；这可以支持“局部存在”，不自动支持全局不存在。

每个实验结论必须说明是哪一类，不能把绿色测试、训练失败和数学不存在混在一起。

## 2. 研究主假说

### H-UCM-01：有限 scope 内存在紧凑近似共享状态

**主张**：对冻结的 W01–W20 人群、检查、动作、horizon 和结局集合，至少存在一个比 full history 更紧凑的递推 `Z_t`，能从同一状态支持诊断、自然未来、治疗未来和在线更新。

**预注册预测**：

- 至少一个合规共享候选在三项任务中均无预注册不可接受退化；
- 相对 separate-task baseline，它至少在样本效率、跨任务一致性、组合泛化、state size 或 novel-readout transfer 中形成明确 Pareto 优势；
- state-size 对 scope 内 history length 的 slope 明显低于 full-history baseline；
- dangerous collision 为零或低于由 oracle effect gap 导出的安全 margin。

**推翻**：所有紧凑候选都发生不可接受危险碰撞、无法递推，或被 separate-task baseline 与 full-history baseline共同严格支配；只有无压缩历史能过。

**可能结论**：支持只限冻结合成 scope，不外推临床。

### H-UCM-02：自然预测充分不等于治疗充分

**主张**：只按 no-op future 压缩的状态会合并自然病程相同但治疗响应不同的历史；把 controlled futures 纳入状态定义会减少危险碰撞。

**关键世界**：W04、W17、W19；W15 用于排除把关联当干预。

**预注册对照**：同家族、相近 data/compute/state budget 的 `natural-only` 与 `controlled` 版本。

**推翻**：两版本在全部冻结 treatment probes 上行为等价，且差异不能由额外数据、容量或泄漏解释。

### H-UCM-03：同一更新可联合改变诊断与行动预测

**主张**：新观察和真实治疗响应带来的信息，可以通过一个 task-blind `U` 更新同一状态，而不是分别更新 diagnosis/forecast/treatment latent。

**关键世界**：W05–W08、W14、W20。

**预注册预测**：actual action/response 后，三类 readout 都从新 hash 重算；incremental 与 clean replay 行为等价；query 顺序不影响更新。

**推翻**：任一任务需要专属 update、历史重编码或 hidden cache 才恢复正确结果。

### H-UCM-04：固定状态的充分性依赖 scope

**主张**：新检查、新治疗和更长 horizon 会拆分部分旧行为等价类；诚实候选必须 refinement、增长或返回 `scope_insufficient`。

**关键世界/扩展**：W16、W17、1h→24h→7d、新检查、新治疗。

**预注册预测**：固定维候选在至少一个扩展上暴露不足；dynamic/refinable 候选能局部增加区分，而不静默重写全部核心。

**推翻**：某固定有限状态在预注册连续扩展序列上保持充分，并给出可验证闭包理由；单纯在有限扩展样本上没失败不等于全局推翻。

### H-UCM-05：行为状态可有多种等价坐标

**主张**：belief、PSR、causal state、图或程序状态可能通过保留 update 与 controlled future 的双向映射表达相同行为 quotient，其差异主要体现在可学习性、简洁性和扩展成本。

**预注册预测**：至少两个实质不同实现可在冻结 probe 上行为等价，但 state size、sample efficiency、interpretability 或 extension cost 位于不同 Pareto 点。

**推翻**：冻结反例稳定证明一个表示保留了另一个在同 scope、同信息预算下无法恢复的受控未来信息，且不是优化/容量差异。

### H-UCM-06：罕见灾难差异决定安全状态粒度

**主张**：平均预测良好不足以决定状态等价；罕见但相反治疗方向或高损失尾部必须保留。

**关键世界**：W19，并横向检查 W04/W17。

**预注册预测**：仅优化平均 likelihood/MSE 的压缩候选更易发生 tail collision；加入受控 tail-risk 表示/训练目标后 max/CVaR regret 改善，即使平均分变化小。

**推翻**：平均目标版本在同数据与容量下已保留所有冻结 catastrophic distinctions，tail-aware 版本没有任何可区分收益。

### H-UCM-07：冻结后的新读出能探测状态闭包

**主张**：若 novel readout 属于原 scope 的 `Y` 闭包，冻结 encoder 后只读 `Z_t` 应能学习它；必须重读历史说明状态丢失范围内信息。

**关键实验**：candidate seal 后注册 novel readout；禁止 encoder 更新和 history access。

**推翻**：所有合规紧凑候选都不能支持该范围内 readout，而 full history 可以；这会推翻对应充分性声明。若 readout 原本不在 `Y`，只说明 scope 扩张。

### H-UCM-08：全局固定有限 UCM 可能不存在

**主张**：在动作、检查、机制和时间尺度可持续扩张时，存在每次都拆分旧状态的新 probe，或存在无有限递推统计量的路径依赖。

**支持所需证据**：构造一个最小可运行反例族，证明对任意固定有限摘要都存在两段被合并的公开历史，而某允许策略使未来分布或最佳治疗方向不同。

**反对证据**：给出固定有限表示在明确无限/闭包动作族上的充分性证明和可运行验证。

**声明限制**：只观察到 state size 随当前 20 个世界增长不能证明数学不存在；它最多支持“当前候选未找到稳定上界”。

### H-UCM-09：部分可观察时正确对象是条件分布，不是泄漏的真状态

**主张**：相同公开历史对应多个 hidden realization 时，正确共享状态是 belief/预测分布；true-state upper bound 的个体确定性不能作为普通候选目标。

**关键世界**：W02、W11、W12、W18。

**预注册预测**：合规候选的 calibrated uncertainty 优于硬猜 hidden class；同 public history 不因 simulator realization 不同而产生不同 state。

**推翻**：候选仅凭公开历史可以审计地恢复个体 hidden truth，且不是 generator leakage；若这发生，说明世界并非真正部分可观察。

### H-UCM-10：观察动态与生理动态必须分离

**主张**：只追踪 observed value 的状态会把 observation-channel 改善误认为机制改善；显式或隐式分离两种通道会减少 W05–W07 collision/regret。

**推翻**：在冻结 W05–W07 中，观察值本身被 oracle 证明为充分统计量，或分离模型无任何行为差异且不是实现失败。

## 3. 架构家族假说

> 家族数按**患者状态语义与更新代数**计算，不按类名。若两个实现只有字段名、网络深度或隐藏维度不同，不计两个家族。

### F01 — 人工机制状态向量

**候选状态**：少量诊断中立机制、宿主基线、当前暴露、延迟队列和不确定性摘要组成的固定或小幅可增长向量。

**更新**：解析/Bayes/filtering rule；同一 controlled transition 接受 policy。

**为什么可能成立**：W01、低维 W02、W03、W05–W12 的 ground-truth 机制可能确有紧凑统计量；强 inductive bias 应提高样本效率和可解释性。

**可证伪预测**：在简单/可解释世界以较少样本接近 oracle；state size 小；component audit 可解释所有 head 的共同依赖。

**主要攻击**：W13 非线性共病、W14/W20 路径依赖、W16/W17 scope 扩张。若必须不断加病例专属槽位或 action-specific bonus，则 abandon，而不是继续称通用向量。

**杀死条件**：在增加医学/世界真实且跨 mimic 公平的机制变量后，仍稳定合并相反治疗患者；或 state slot 数随 history/test ID 线性增长。

### F02 — latent state-space / DBN / POMDP belief

**候选状态**：`P(X_t, Theta | H_t^pub)` 的有限参数、离散 belief 或粒子近似。

**更新**：统一 Bayes/filter update；transition/observation kernel 在 action 下演化。

**为什么可能成立**：已知有限 POMDP 与线性高斯系统中 belief 是递推充分统计量；天然表达部分可观察和不确定性。

**可证伪预测**：在 W01/W02/W08/W09/W11/W12 接近 true-state/belief oracle；incremental replay 一致；诊断校准优于 point latent。

**主要攻击**：W13 的模型错配、W14/W20 未建模记忆、W18 新机制、posterior family closure 失败。

**杀死条件**：在给定正确 family 的 oracle-structure track 仍不能通过 filtering/controlled rollout，说明实现/表示错误；在 learned track 只有无界粒子/完整历史才能避免碰撞，则有限 belief 假说失败。

### F03 — controlled Predictive State Representation

**候选状态**：对一组未来 tests 在 action sequences 下成功/结果分布的预测向量或低秩算子。

**更新**：新 observation/action 后用 PSR update 递推预测 tests。

**为什么可能成立**：直接以 controlled future 定义状态，无需为 latent disease 赋予唯一语义；适合 partial observability。

**可证伪预测**：在有限线性维 controlled worlds 上以较低 false split 逼近 causal behavior classes；W03/W04 区分优于 natural-only state。

**主要攻击**：长 action sequence、稀有 W19、W16/W17 新 tests/actions 导致 rank 增长；有限数据下预测 tests 难识别。

**杀死条件**：存在冻结 policy probe 未包含的稳定相反反应，使有限 test basis 持续 collision；扩 basis 后维度/样本成本无稳定上界。

### F04 — causal-state / behavioral-equivalence / bisimulation

**候选状态**：按全部登记 controlled future distribution 对 histories 做等价类或近似 bisimulation quotient。

**更新**：event 到来后迁移到新的 equivalence class；有限 world 可由 oracle/枚举或学习 partition。

**为什么可能成立**：它最直接逼近 FIRST_PRINCIPLES 中的状态定义，并以 false split 意义追求相对最小。

**可证伪预测**：在可枚举小世界，oracle partition 具有最低 false split 且零 dangerous collision；learned partition 随样本增多收敛。

**主要攻击**：连续空间、长 horizon、罕见动作和 adaptive policy 导致 pair/probe combinatorial explosion；approximate partition 对 tail risk 敏感。

**杀死条件**：即使在有限可枚举世界，构造出的 quotient 仍把不同 controlled futures 合并，或保留与全部行为无关的身份噪声；learned 版本若永远需要全历史索引，也只能算 baseline。

### F05 — Dynamic Structural Causal Model

**候选状态**：动态 endogenous mechanisms、exogenous/background posterior、当前 intervention/exposure 与延迟变量的联合状态。

**更新**：因果滤波；rollout 对 structural equations 做 `do(action)` 替换，而非观察 conditioning。

**为什么可能成立**：明确区分关联与干预、状态转移与观察方程，适合 W05–W07/W15。

**可证伪预测**：在给定可识别结构时，W15 treatment direction 与 oracle 一致；planned/performed 和 observation/state action 不混淆。

**主要攻击**：隐藏混杂不可识别、结构错设、部分可观察 posterior 不闭合、新机制/新共病要求重写图。

**杀死条件**：在满足已声明识别假设的 track 仍把 `P(Y|A)` 当 `P(Y|do(A))`；或 task heads 持有不同 SCM state。若仅凭观察数据不可识别，应报告 identification limit，不得用图形外观宣称解决。

### F06 — Koopman / observable operator / latent linear dynamics

**候选状态**：lifted observables 或 belief features，使每个 action 对共享 state 的演化近似线性/算子化。

**更新**：observation correction 加 action-indexed/shared operator transition。

**为什么可能成立**：W01 和部分平滑非线性系统可能有低维闭合 observables；action composition 与 long rollout 计算高效。

**可证伪预测**：W01 接近解析上界；在平滑 worlds 上 horizon 增长时误差与计算成本优于黑箱 rollout。

**主要攻击**：W13 阈值/协同、W19 rare discontinuity、W20 history dependence、OOD mechanism；有限 dictionary 不闭合。

**杀死条件**：为了每个 world/action 增加专属 observables 直到等同完整 simulator 或 task state；或 one-step 好但 multi-step/intervention 系统性漂移。

### F07 — Neural world model（RSSM / neural ODE-SDE / recurrent latent）

**候选状态**：由 task-blind encoder/update 产生的 sealed recurrent stochastic latent；所有 readout 从该 latent fan-out。

**更新**：共享 recurrent transition + observation correction；policy 作为同一 transition core 的输入。

**为什么可能成立**：高容量可拟合非线性共病、延迟、路径依赖和复杂 observation channel。

**可证伪预测**：在足够数据下 W13/W14/W20 平均预测优于固定线性候选；同一 state 可迁移 novel readout。

**主要攻击**：任务 multiplexing、query-specific history attention、poor calibration/OOD、rare W19 collision、sample/seed instability、不可审计。

**杀死条件**：移除 raw-history attention 后性能崩溃；component audit 显示互不相交的 task blocks；fresh process closure 失败；五 seed 结果不稳定；或高平均分仍产生 catastrophic regret。整段 context attention 只能作为 full-history baseline，不能计本家族合规实现。

### F08 — Mechanism graph / reaction network / graph dynamical system

**候选状态**：机制节点、宿主 modifiers、药物暴露、delay/event nodes 及其不确定性；局部边定义统一 dynamics。

**更新**：局部 message/filter update；action 修改共享图上的机制或 observation channel。

**为什么可能成立**：共享机制可解释 W10，多宿主表达可处理 W12，局部组合可能泛化新共病。

**可证伪预测**：在 train 未见组合上，正确局部 factorization 比 flat vector/black-box 更样本高效；新检查/治疗只增加局部 node/edge 而非重写全图。

**主要攻击**：W13 非局部协同/拮抗/阈值、循环反馈、图结构学习错、重复证据 double count。

**杀死条件**：只有加入 case/disease-specific shortcut edge 才过；同一临床事实在多节点重复计分；新组合必须全局重训且无局部扩展优势。

### F09 — Symbolic–neural hybrid

**候选状态**：typed mechanism/causal scaffold 上的显式状态，加共享可学习参数或受约束 residual latent。

**更新**：显式规则与单一 learned residual transition 共同更新；所有 head 读取完整共享 state。

**为什么可能成立**：可能同时获得结构外推、tail guard、非线性拟合和可审计性，形成较好 Pareto。

**可证伪预测**：相对纯 graph 提升 W13/W20，相对纯 neural 改善 W15/W18/W19、样本效率或解释性。

**主要攻击**：residual 藏 task-specific states；symbolic 与 neural 双重计算同一 evidence；guardrail 退化成 world-specific bonus。

**杀死条件**：遮蔽 residual 后暴露三块 task latent；性能依赖 test-specific symbolic branch；或结构/残差各自维护患者 state，违反 semantic unity。

### F10 — Attention / bounded memory state

**候选状态**：固定或受控增长、可序列化的 recurrent memory slots；query 只读冻结后的 memory，而不是重读 raw history。

**更新**：新 event 通过 task-blind write/update 进入 memory；readout query 不改变 memory。

**为什么可能成立**：可能保留 W14/W20 长依赖，同时选择性忘记无关历史。

**可证伪预测**：history deletion 能识别真正必要记忆；state-size slope 低于 full history；query permutation 和 novel readout 合规。

**主要攻击**：把所有 token 放进 memory、按 query 重新 attention 全史、cache 第二状态、长度无界。

**杀死条件**：state bytes 可逆恢复完整历史且未声明 baseline；或 treatment query 使用与 diagnosis 不同的 memory selection。仅“用 Transformer”不计一个 UCM 家族。

### F11 — Program-state / typed rewriting

**候选状态**：可序列化 typed AST/configuration，表示活动机制、资源、暴露、计时器、pending tests 和概率参数；禁止 executable callback/外部句柄。

**更新**：同一 rewrite semantics 消费 observation/action；rollout 在 copied program state 上执行 policy。

**为什么可能成立**：离散事件、delay、路径依赖、治疗历史和局部扩展可显式表达，适合 W08/W14/W20。

**可证伪预测**：update lineage 与 counterfactual fork 高可审计；新 action 能通过局部 typed rule 扩展；rare contraindication 可显式保留。

**主要攻击**：状态空间爆炸、连续/随机过程校准差、rule overlap、程序逐渐变成完整事件日志。

**杀死条件**：需要按 world/test 写专属 rewrite；无法给概率分布；或 AST 尺寸与 history 线性增长且没有行为压缩。

### F12 — 动态非参数行为地图

**候选状态**：可增长的 mixture/partition/automaton，以反例或新 action/test 对旧行为类做局部 refinement。

**更新**：在线 posterior/partition update；scope migration 记录 parent→children lineage。

**为什么可能成立**：若固定有限 UCM 不存在，动态地图可能是避免危险碰撞同时诚实表达未知的最小方案。

**可证伪预测**：W16/W17 与 freeze 后新检查/治疗中，只细分必要区域；旧等价区域保持不变；state growth 与新增可辨别行为而非 history length 相关。

**主要攻击**：每个 episode 建一个 leaf、无泛化、增长不可控、实质变成 full-history index。

**杀死条件**：false split 与 state count 随 episode 数近线性增长；新 probe 触发全局重建；或 local refinement 仍漏掉相反治疗状态。

## 4. 规定 baseline 的假说与用途

### B01 — True-state upper bound

允许读取 simulator true state，只校验 oracle、metric 与可达性能上界。预期在 world 定义正确时接近最佳。它违反 candidate information boundary，`eligibility=upper_bound_only`，绝不是可部署 UCM 证据。

**若失败**：优先判定 world/oracle/metric/runner 有 bug，benchmark 不得冻结。

### B02 — Full-history baseline

`Z_t = H_t^pub`，所有 head 可从这份显式 state 读数据。它可能信息最全但 state size/latency 随历史增长，`eligibility=baseline_only`。

**用途**：测压缩代价、识别任何方法都无法从 public history 得到的上限；不得称紧凑地图。

### B03 — Separate-task baseline

诊断、自然预测和治疗各自训练最强专用状态/模型。预期在某些单任务上形成性能上界，但 `shared_state_compliant=false`。

**用途**：若共享候选在所有 Pareto 轴被它严格支配，必须诚实报告共享约束当前无证据价值；不能给本 baseline UCM waiver。

### B04 — K0-only negative control

只提供控制面、typed routing、ledger 或接口，不提供患者 world state/dynamics。

**预注册预测**：它可通过部分传输/隔离基础设施测试，但无法从同一患者状态完成机制 posterior、natural/intervention rollout、regret 与 update closure。

**若意外通过**：检查是否偷用了外部 patient model、oracle 或 task-specific payload；不能得出“K0 就是 UCM”。

## 5. 候选家族与攻击世界的预注册映射

> 这是 benchmark 设计审查用的方向矩阵，不是结果。`+` 表示该家族必须展示预期优势，`!` 表示优先杀死点，`?` 表示没有方向性先验。

| 家族 | 主要预期优势 | 首要攻击世界/实验 |
|---|---|---|
| F01 机制向量 | W01–W12 的样本效率、解释性 | W13、W14、W16、W17、W20 |
| F02 belief SSM | W02、W08、W09、W11、W12 的不确定性 | W13、W18、W20、模型错设 |
| F03 controlled PSR | W03、W04 的受控预测充分性 | W17、W19、长 action sequence |
| F04 causal state | 有限世界最小 partition、低 false split | 连续空间、rare policy、probe explosion |
| F05 dynamic SCM | W05–W07、W15 干预语义 | 隐藏混杂不可识别、W18、新结构 |
| F06 Koopman | W01、平滑长 rollout、算子组合 | W13、W19、W20、long-horizon drift |
| F07 neural world model | W13、W14、W20 非线性/记忆 | W15、W18、W19、semantic-unity audit |
| F08 mechanism graph | W10、W12、新共病组合 | W13 非局部交互、double count |
| F09 symbolic-neural | 结构+非线性 Pareto | residual task multiplexing、bonus overfit |
| F10 bounded memory | W14、W20 长依赖 | history recovery、state-size slope、新读出 |
| F11 program state | W08、W14、W20、局部规则扩展 | 连续校准、rule explosion、history AST |
| F12 dynamic map | W16/W17、新检查/新治疗 | episode indexing、false split、unbounded growth |

若 freeze 前某个 W01–W20 世界不能区分任何家族假说，它需要更强 oracle/probe 或明确降为非判别 sanity test；不得等看到候选排名后再偷偷改世界。

## 6. 架构级实验登记模板

每个 experiment 在 `EXPERIMENTS.md` 与 run manifest 中至少登记：

```text
experiment_id:
hypothesis_ids:
architecture_family:
state definition:
known failure addressed:
one substantive change:
public information and structural prior:
train/validation/test eligibility:
seeds and compute budget:
hard-gate expectations:
world/task/horizon/policy metrics:
dangerous collision and regret-tail probes:
falsification criterion fixed before run:
decision: keep | refine | revert | abandon
next highest-information experiment:
```

以下不算新的重大架构实验：只改 learning rate、层数、hidden dimension、seed、batch size 或同一 loss 的小权重。若它们必要，应记为 subordinate ablation。至少 20/30 个重大实验必须改变状态语义、update、transition factorization、uncertainty representation、intervention identification、scope/refinement 或共享约束中的一项。

同一家族连续四次只有局部参数调整且没有实质进展时，必须停止该方向。每五个实验新增至少一个攻击当前最强候选的反例；每十个实验重新审查主假说、表示/识别/优化失败分类和家族覆盖。

## 7. 全 benchmark 与复现前的选择规则

只有同时满足下列条件的 candidate snapshot 才可进入 primary W01–W20 hidden comparison：

1. source/model/dependency/config 已 seal；
2. public validation 上 hard compliance 无 FAIL，关键 isolation 无 INCOMPLETE；
3. state schema、scope、训练先验和资源已登记；
4. raw result writer 与 clean replay 已验证；
5. finalist 之间使用同一 fresh common hidden corpus。

最终至少三个候选、每个至少五个 model seeds 跑完整 W01–W20；最强候选另有独立实现路径和 freeze 后 red-team。本文只登记这一最低要求，**当前并未完成，也不得提前写成已完成。**

## 8. 可能的诚实终局

实验结束后只允许从证据支持的以下结果中选择：

1. **有限局部 UCM**：在明确 `S` 内存在紧凑递推共享状态；
2. **近似/Pareto UCM**：没有唯一赢家，不同表示在安全、简洁、样本和扩展成本上形成前沿；
3. **动态 UCM**：固定状态不足，但按新行为区别局部增长的地图成立；
4. **无压缩共享状态**：只有 full history 保留所需信息；不能称紧凑地图；
5. **共享约束无实证优势**：合规共享候选被 separate-task baseline 严格支配；
6. **有限共享状态最小反例**：给出可运行、可量化、能攻击任意固定摘要的反例族；
7. **HARNESS/IDENTIFICATION INCOMPLETE**：现有世界、oracle 或数据不能判定，保持未知。

无论哪种终局，都必须区分：已验证、仅合成 scope 支持、失败、尚未知。不得因文档完整、接口统一、K0 可路由、LLM 可读历史或单任务分数高而宣布 UCM 成功；也不得声称临床有效、生产安全或全局最优。
