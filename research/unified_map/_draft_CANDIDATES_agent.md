# Unified Clinical Map 候选与基线公平比较矩阵（工作草案）

> 状态：候选枚举/实验合同草案；**不是 benchmark freeze，不是实现清单，不选赢家**。
> 范围：只讨论患者世界模型及共享状态 `Z_t`。K0 只可复用为隔离、时间切片、candidate-view 与审计基础设施，不获得任何 UCM 动力学能力。
> 本表列出 11 个实质不同的候选家族和 4 个强制基线。未来至少实现其中 8 个候选家族；不能把同一家族的网络宽度、粒子数或超参数变化重复计成新家族。

## 1. 所有候选共同接受的 UCM 合同

### 1.1 共享患者状态的最小运行签名

所有合规候选都必须暴露同一类运行闭环；具体 `Z_t` 可以是向量、分布、图、程序配置或其他可序列化对象。

```text
initialize(public_context, model_version) -> Z_0
update(Z_t, newly_available_event)          -> Z_t_plus

diagnose(Z_t)                              -> mechanism/disease posterior
assess_support(Z_t)                        -> in-map support / OOD uncertainty
predict_test(Z_t, test_spec, horizon)       -> result distribution
rollout(Z_t, no_op_or_policy, horizon)      -> future trajectory/outcome distribution
rollout(Z_t, hypothetical_action_sequence)  -> counterfactual trajectory/outcome distribution
readout(Z_t, frozen_new_task_spec)           -> new-task prediction
```

严格含义：

1. `diagnose`、自然病程 `rollout`、治疗 `rollout` 的初始患者对象必须是**完全相同的序列化状态字节、`state_id` 与 `state_hash`**。
2. 头可以有不同的全局、冻结、无患者记忆的参数；不得有 head-private 的患者 latent、RNN hidden、KV cache、检索索引或历史副本。
3. 假设性动作、检查、预测 horizon 和效用函数是 query 输入，不属于患者信息。实际已执行治疗及其后续观察必须作为新事件调用 `update`，产生新的 `state_id`。
4. query 内允许从 `Z_t` 的克隆产生临时 rollout 状态；这些状态必须只由 `Z_t + query action + query RNG` 派生、随 query 销毁并进入 trace，不能回写患者状态或跨 query 缓存。
5. 全局模型参数不算单患者状态；任何在线学习得到的患者专属参数、posterior、粒子、图拓扑、程序寄存器、计时器或暴露记忆都必须放入 `Z_t` 并参与哈希和大小统计。
6. 候选不得在 query 时重新读取原始历史。唯一例外是明确标记为不压缩基线的 B01；它不能因此宣称通过共享紧凑状态门。
7. `Z_t=(Z_diag,Z_natural,Z_treatment)` 的物理拼接不构成统一地图。若三块由独立 task-conditioned encoder/update 维护，或自然/治疗预测各有一套患者动力学，则按 task-specific latent 硬失败处理。

### 1.2 统一信息边界

除 B03 True-state upper bound 外，候选与基线只能看到冻结生成器给出的 `candidate_view`：

- 截至 cut 已可获得的观察、检查结果和真实治疗暴露；
- 公开的 observation/action/test schema、时间字段和训练划分；
- 当前 query 的动作、检查、horizon 或 readout 规范。

它们不得看到：模拟器隐藏真状态、未发生未来、其他反事实轨迹、oracle label 的内部生成字段、冻结测试答案、world/test ID 或可反推出测试分支的私有元数据。

### 1.3 公平比较不是“所有模型同一个参数量”

不同家族需要不同结构先验，必须把先验和算力拆开记录，而不是混成一个总分。

| 公平轴 | 冻结规则 |
|---|---|
| 数据 | 同一 train/validation/frozen-test 生成器、相同可见 histories、相同样本数；counterfactual 训练监督是否可见必须对所有候选一致。 |
| 结构知识 | `K0/schema-only` 轨只给 observation/action/test 类型；任何 world-specific 机制名、拓扑、方程族或规则都记为 `structure-informed`，只与同知识层比较。隐藏状态实现值/真参数只允许 B03。 |
| 调参 | 相同 trial 上限、validation 可见度和停止规则；freeze 后不得根据 W01-W20 test 或 red-team 修改候选。 |
| 计算 | 同时报小/中等共同预算和 unconstrained Pareto 结果；报告训练/推理时间、峰值内存、全局参数量。 |
| 状态成本 | 统计序列化后的单患者 `Z_t` 字节、维度/节点/粒子/slot 数和随时间增长率。手写规则、图拓扑及 feature dictionary 计入全局描述长度。 |
| 读出 | 每个家族可用其原生 stateless query，但必须报告 head 参数与调用图；冻结新任务另用受限 probe，只能读取已存 `Z_t`。 |
| 随机性 | 完整候选至少 5 seeds；相同数据 seeds，模型 seeds 独立记录；报告 per-world 分布和最坏 seed，不只报均值。 |
| 失败 | 不支持的 query 必须显式 `unsupported`；不能静默退化成关联预测、历史重编码或 oracle lookup。 |

### 1.4 共同防伪门（每个候选另有家族专属审计）

| Gate | 自动检查 | 硬失败信号 |
|---|---|---|
| UCM-G01 输入隔离 | update 进程只得到旧 `Z` 与一个新事件；query 进程只得到冻结模型、`Z` 与 query spec。阻断 history/oracle 文件、网络、subprocess 与环境旁路。 | 头读取 history、oracle、未来或 patient-specific 外部缓存。 |
| UCM-G02 可重放状态 | 序列化 `Z`，重启干净进程后以同一 query seed 重跑三类 query。 | 结果依赖未序列化 hidden/KV/RNG/global mutable state。 |
| UCM-G03 同哈希多读出 | 对 diagnosis、no-op、A/B treatment 记录完全相同的输入 `state_hash`；query 不得改变该 hash。 | 某任务先执行隐式 re-encode/update，或三个任务的患者状态 hash 不同。 |
| UCM-G04 无 task-conditioned update | 对同一事件流，在不同 query 顺序及不发 query 时，最终 `Z` 必须一致。 | `task_id`、query 类型或既往 head 输出改变 state construction/update。 |
| UCM-G05 缓存清扫 | query 前清空进程并随机化 patient ID、文件名和调用顺序；枚举持久 per-patient allocation。 | 换 ID/顺序后结果改变，或发现未计入 `Z` 的患者对象。 |
| UCM-G06 污点与泄漏 | 对 future/oracle/test-id 字段做 canary/taint；扫描分支、特征和序列化对象。 | canary 到达 `Z`/output，或按 world/test/disease/expected-answer 分支。 |
| UCM-G07 动力学谱系 | trace 自然与治疗 rollout 的初始状态和状态演化算子；允许 action-conditioned operator，不允许另一个患者 encoder。 | 治疗 query 从历史生成新 latent，或调用与共享状态无谱系关系的患者模型。 |
| UCM-G08 新任务冻结读出 | 冻结 encoder/update 和已有 `Z`，训练小型新 readout；运行时不挂 history。 | 新任务必须重编码历史或启用新的患者记忆才能工作。 |
| UCM-G09 分块伪统一审计 | 检查 update/transition 计算图、state namespace、head 可见域及 coordinate/group ablation。 | 三个互不通信、由任务损失各自维护的 latent 仅被打包进一个容器。 |
| UCM-G10 大小诚实 | 序列化所有 per-patient posterior、particles、memory slots、program registers 与缓存。 | 把增长历史/KV/检索库称作全局参数，或漏报患者专属对象。 |

`UCM-G09` 不要求每个坐标被每个头读取；它禁止的是三套没有共同更新/演化语义的患者表示被物理拼接。合法因子化状态可以有局部组件，但必须由同一个 task-agnostic update 管理，并共同定义从当前患者到允许未来的分布。

## 2. 候选家族矩阵 A：状态、更新与 query 语义

| ID | 架构家族与实质差异 | 共享状态对象 `Z_t` | 在线 update | diagnosis / natural / treatment query 如何只从同一 `Z_t` 出发 |
|---|---|---|---|---|
| C01 | **人工机制状态向量**。坐标语义由人显式规定，不是纯 learned latent。 | 对宿主基线、机制活性、病程 phase、治疗暴露/滞后变量的联合 posterior（不能只保存点估计）；可用高斯、离散混合或粒子表示。 | 显式 transition + observation model 的 Bayesian/ensemble/particle filter；实际 action event 更新暴露与机制坐标。 | diagnosis 读机制 posterior；no-op 与治疗从同一 posterior 按同一 dynamics 前推，动作只改变声明的 transition/observation channel；结果通过共同 outcome decoder 读取。 |
| C02 | **经典 latent state-space / DBN / POMDP belief**。状态是生成模型隐藏 Markov state 的 belief，而非手工临床坐标或未来测试向量。 | `P(X_t, theta, mode ∣ H_t)` 的充分参数或带权粒子，含使系统 Markov 所需的宿主/暴露记忆。 | prediction-correction filter；不规则时间用 `delta_t` transition，动作进入受控 transition/observation kernel。 | diagnosis 是 belief 上 mechanism/type 的边缘；natural/treatment 都从同一 belief 经 `T(X' ∣ X,a)` 和 observation/outcome kernel rollout；POMDP policy 只能读取 belief。 |
| C03 | **Controlled Predictive State Representation (PSR)**。不用隐藏机制值定义状态，而用一组 future tests 在动作序列下的预测。 | 冻结 core tests 的预测向量/矩阵（或其低秩充分统计），每一维明确对应未来观察/检查在 intervention sequence 下的概率或矩。 | 观察-动作到来后用 PSR update operator 和 normalizer 更新 core-test predictions。 | diagnosis 是 predictive state 的 stateless calibrated readout；natural/treatment 由同一 predictive operators 组合得到未来测试、轨迹和 outcome；不得另建 hidden mechanism filter。 |
| C04 | **Causal-state / behavioral-equivalence / controlled bisimulation**。状态是历史对所有允许未来实验行为的等价类，而不是预先选坐标。 | history-equivalence class 的 ID/posterior，或近似 behavioral metric embedding；等价关系相对于冻结的 checks/actions/horizons 明确定义。 | 新 action/observation 触发 deterministic/probabilistic successor class；不确定分类时更新 class posterior。 | diagnosis 是 class 到 mechanism posterior；natural/treatment 使用同一 class transition/output kernels。若两历史在某允许 intervention 下未来不同，就不能得到同一 class。 |
| C05 | **Dynamic Structural Causal Model (DSCM)**。核心是时序结构方程、外生背景和 `do` mechanism replacement，不等同于普通 action-conditioned SSM。 | 当前 endogenous variables、时间不变/慢变 exogenous factors `U`、机制参数与其 joint posterior；反事实 twin 共享同一 posterior over `U`。 | 对新观察做 abduction/filter；对已执行 action 用 action mechanism 更新；保持 observation effect 与 state effect 分开。 | diagnosis 读机制/`U` posterior；natural 用原结构方程；treatment 用同一 posterior 做 abduction-action-prediction 并替换指定机制，不能把 `A=a` 条件化冒充 `do(A=a)`。 |
| C06 | **Koopman / observable-operator / latent linear dynamics**。承诺存在有限或近似有限的 lift，使时间/动作演化可由可组合算子表示。 | lifted state/belief `z_t=phi(history sufficient statistic)` 及必要 uncertainty；固定 feature dictionary 或 learned encoder 的输出。 | filtering 后应用 `K_a(delta_t)`；新 observation 通过共享 correction operator 更新 lift。 | diagnosis 是 `z` 的 readout；natural/treatment 从相同 `z` 反复组合 no-op/action-specific operators，再由共同 observation/outcome decoders 读取。 |
| C07 | **Neural world model**（首个最小实例可用 RSSM；neural ODE/SDE 是同家族的重大变体，不自动多算家族）。核心是 learned stochastic recurrent world state。 | 单一 recurrent deterministic state + stochastic latent posterior 参数/样本，连同必要 exposure memory；所有部分都序列化。 | amortized observation encoder + shared recurrent/action transition + posterior correction；输入不含 task ID。 | diagnosis head 读同一 latent；no-op/治疗 imagination 都从该 latent 经同一 action-conditioned transition 展开；不同 stateless decoder 可读 mechanism、observation、outcome。 |
| C08 | **Mechanism graph / reaction network / graph dynamical system**。核心是局部机制节点、边和组合动力学；与 DSCM 的差别是强调开放组合、守恒/反应/局部相互作用，不以 `do` 识别为唯一原语。 | 类型化动态 graph：node activity/concentration posterior、edge/interaction mode、host context、timers/exposure；可含动态拓扑但必须序列化。 | 图 filter/message passing + ODE/CTMC/reaction/event step；动作改变明确 node/edge/rate 或 observation port。 | diagnosis 读 node/edge mechanism posterior；natural/treatment 从同一 graph state 按同一 local dynamics 积分，动作作为局部图干预；outcome 从 graph trajectory 读取。 |
| C09 | **Symbolic-neural hybrid**。显式机制/约束与 learned residual 同属一个复合世界状态；不是把 C01/C08 和 C07 的三个任务输出做 late fusion。 | `Z=(typed explicit mechanism state, residual latent posterior)`；residual 的作用域、维数、约束及违反约束的预算均显式。 | 先/同时执行 mechanistic transition 与共享 neural residual/filter correction；residual 只能修正声明的 dynamics/observation components。 | 三类 query 从同一复合状态和同一 hybrid transition 出发；显式路径提供 mechanism/`do` 语义，residual 处理未建模 dynamics；禁止 residual 直连某一任务的答案缓存。 |
| C10 | **有界 attention/memory state**。研究问题是固定容量、在线更新的 memory 是否成为充分状态；若每次重读全史或容量随史增长则退化为 B01。QKV 本身不算医学语义。 | 固定 `M` 个可序列化 memory slots + summary/control latent + slot uncertainty/age；没有外部患者检索库。 | 每个新事件仅对旧 slots 做 task-agnostic read/write/compress；query 不得写 slots。 | stateless diagnosis/no-op/treatment query 可用不同 query token 注意同一 slot bytes；未来 rollout 从同一 summary/memory 初始化，不能在 query 时重新 attention 原始 history。 |
| C11 | **Program-state / typed probabilistic rewriting**。状态是可执行机制配置、fluent/资源/计时器和残余程序，而非连续 latent。 | 类型化 configuration/multiset、numeric registers、pending timers、action typestate 与 distribution over configurations。 | 新 observation/action/time tick 触发封闭 rewrite rules；概率/连续量用 stochastic rule 或数值 register update。 | diagnosis 是配置/机制分支 posterior；natural/treatment 都克隆同一 configuration 并以 no-op/假设 action 驱动同一 rule engine；outcome 由生成 trace 读出。 |

## 3. 候选家族矩阵 B：可证伪主张、判别世界、弱点与最小实现

下列“判别世界”不是候选可跳过的世界；**每个候选最终都必须跑 W01-W20**。这里仅列最能区分该家族核心假说的世界。

| ID | 可证伪预测（不是预设结论） | 适用范围 / 高信息量判别世界 | 结构性弱点 / 最根本反例 | 最小但完整的首个实现 | 避免 task-specific latent 的家族专属审计点 |
|---|---|---|---|---|---|
| C01 | 若人工坐标确实包含所有控制相关 modifier 与记忆，则同一 posterior 应同时给出校准诊断和低后悔治疗；删掉 treatment-response modifier 后，W04/W19 必须出现可定位碰撞，而加入该坐标应消除碰撞而不是靠治疗 bonus。 | W01–W07、W09–W14、W19–W20；W16/W17 检验坐标扩展。 | ontology omission；手工先验可能偷看 oracle；有限坐标对未知机制、非线性共病和长记忆脆弱；点估计会丢不确定性。 | 4–12 个有语义坐标的 hybrid discrete/Gaussian 或 particle filter，显式 state/observation/action kernels；先在 K0/schema-only 和 structure-informed 轨分开跑。 | 坐标表、update 方程和所有 head 的 read-set 全披露；禁止 `diagnosis_logits`、`treatment_embedding` 私有坐标；coordinate-group ablation 检查是否只是三块任务向量拼接。 |
| C02 | 在模型正确且 belief 足够时，W01/W02 的 exact filter 应接近 B03 的 Bayes 分布；W14/W20 若在补齐 Markov memory 后仍碰撞，则不是调隐藏维度能解释。普通 action-conditioned likelihood 在 W15 若把 `see` 当 `do`，必须判因果失败。 | W01–W09、W14–W15、W20；W18 测 model misspecification。 | latent 不可识别、模式/维数选择困难；历史依赖导致 state augmentation；观察性数据不能自动识别 intervention；粒子退化与 OOD 过度自信。 | 小型 finite DBN/POMDP exact filter 加一个连续/混合 particle-filter 实例；belief 本身序列化。 | 检查无 smoother/future evidence；diagnosis 与 treatment 不得各自保留 filter；粒子、参数 posterior、resampling ancestry 全在 `Z`；policy 无额外 history。 |
| C03 | 在冻结 action/test 集上，若有限 linear PSR rank 假说成立，core-test state 相同的历史应有相同未来分布；W03/W04 的差异必须被某个自然/受控 test 捕获。W16/W17 加新 check/action 后若 rank 增长，旧 state 应显式报告不足或扩维，不能继续假称充分。 | W02–W04、W08、W11、W14、W16–W17、W19–W20。 | core tests 数量爆炸；off-policy action coverage 不足；估计可能产生不合法概率；机制标签未必可识别；动作集合变化会破坏充分性。 | finite controlled microworld 的 tabular/spectral PSR：冻结一组短 core tests，学习 update operators，输出校准 future-test probabilities。 | core-test 清单 freeze；query 不得临时新增 history encoder；diagnosis head 只能读预测向量；验证预测向量不是分别缓存的 diag/natural/treatment outputs。 |
| C04 | 在有限、完全已知的 frozen experiment class 下，exact behavioral partition 应同时达到零危险碰撞和零虚假拆分（允许统计误差）；W17 新动作可合法推翻旧等价类。若近似 embedding 把治疗方向相反历史合并，核心表示假说直接失败。 | W03–W04、W11、W14、W16–W17、W19–W20。 | “所有未来政策”不可枚举；经验等价受数据覆盖和 horizon 限制；近似距离阈值主观；罕见灾难可能被平均 metric 淹没；class 数可与历史数同阶。 | 不读取 hidden state 的 finite-history future-signature learner + partition refinement；另做 oracle partition 只能作为分析仪器，不能计候选结果。 | 等价类只由 train future distributions 建立并在 test 前冻结；oracle partition 不得进入 encoder；class ID/posterior 是唯一患者对象；新 action 导致的 refinement 需版本化，不能按 test ID 分支。 |
| C05 | W15 中正确 DSCM 的 `P(Y ∣ do(A))` 应与混杂的 `P(Y ∣ A)` 可区分；W06/W07 中 observation-channel intervention 不能被解释为内部机制恢复。反事实 twins 若不共享同一 abducted `U` posterior，个体反事实语义失败。 | W04–W07、W10–W15、W19–W20。 | graph/方程误设；隐藏混杂和 causal effect 不可识别；循环、异步和反馈使 SCM 展开复杂；world-specific graph 先验成本高；OOD 机制缺席。 | linear/nonlinear small dynamic SCM：显式 endogenous/exogenous 变量、observation equations、abduction-action-prediction 和 particle posterior。 | 记录每个 intervention 的 mechanism replacement；禁止 treatment head 使用另一个 confounder posterior；同一 `U` posterior 驱动 no-op/A/B；condition 与 do 调用路径必须可区分审计。 |
| C06 | 若 lift 近似 invariant，长 horizon 误差应主要来自一步 lift/decoder 误差并遵守算子组合，而非随 query 任务切换；W04 必须由同一 `z` 上 action-specific operator 区分。若加入阈值共病后任何有限 lift 都快速膨胀，则有限线性化假说受反例限制。 | W01、W03–W05、W07、W13–W14、W17、时间尺度 red-team。 | 有限 invariant subspace 常不存在；partial observation 的 lift 仍需 filter/memory；混合阈值/非平稳 dynamics 破坏线性组合；unseen action/operator 外推差。 | EDMDc/observable operator：固定 polynomial/RBF dictionary 或小 encoder，action-conditioned `K_a`, observation correction 与 shared decoders。 | 禁止 diagnosis/treatment 各自学习不同 `phi`；所有 operators 的输入 state hash 相同；decoder 无 history skip connection；报告 dictionary/encoder 和 query-specific operator 参数。 |
| C07 | 单一 RSSM latent 若学到控制充分状态，应在 W03/W04 同时降低自然与治疗碰撞，而不是一项变好另一项恶化；冻结 encoder 后新 task 可从 `Z` 读出。W18/W19 若高置信错治，说明 likelihood fit 不等于安全共享地图。 | W02–W15、W18–W20；W16/W17 测冻结扩展。 | 黑箱 entanglement、latent collapse、关联替代因果、calibration/OOD 弱、训练目标泄漏、容量可能记忆全史；难解释为什么合并。 | 小型 RSSM：一个 deterministic recurrent core + 一个 stochastic posterior，联合 observation/mechanism/outcome losses，同一 action transition imagination。 | 只能有一个 patient recurrent core；搜索模型对象中的 task-specific RNN/KV；移除 history skip；state 序列化后跨进程复现；分别 mask deterministic/stochastic 部分检查头是否有私有替代 latent。 |
| C08 | 真实局部机制与相互作用若由 graph 表示，W10/W13 的共源和非线性共病应通过同一节点/interaction 解释；新共病或新治疗应主要增加局部 node/edge/rate，而非重写全核。若平行拼图仍无法产生协同/拮抗，组合主张失败。 | W05–W07、W10–W13、W16–W17、W20。 | topology/kinetics misspecification；hidden mechanism 不可辨识；graph/state explosion；“画图”不等于可运行 dynamics；共享节点可能错误双算。 | 6–15 节点 typed reaction/graph ODE 或 CTMC，加 particle/ensemble observation filter、显式 interaction edge 与 action rate modifiers。 | 所有任务只能读同一 graph snapshot；禁止 head-private subgraph/message cache；每个动态 cache 进 `Z`；动作必须改 node/edge/rate 或 observation port，不能只给治疗输出加 bonus。 |
| C09 | hybrid 若真有价值，应在显式模型受控失配时以共享 residual 同时改善自然和干预预测，同时保留 W15 的 do/observation 分离；zero-residual ablation 应退回显式父模型。若 residual 单独即可还原 task label 或三个 residual 分支互不相干，则只是隐藏任务模型。 | W05–W15、W18–W20；机制失配/组合 holdout。 | residual 可吞掉全部语义、破坏守恒/单调/因果约束、重复计数机制、审计和调参成本高；OOD residual 外推危险。 | C01 或 C08 的小显式模型 + 一个仅修正 shared transition/observation 的低维 stochastic residual；硬限制 residual ports。 | residual 包含在 state hash；禁止 residual→diagnosis/treatment-only direct path；检查 shared residual transition、zero/shuffle residual ablation、显式与 residual information duplication；无三个 task residual。 |
| C10 | 固定 `M` slots 若是近似充分状态，应在 W14/W20 和长 horizon 下维持 bounded collision/regret；历史删除只在删除的信息已被 slots 吸收时不影响结果。若性能只随 `M≈history length` 恢复，或 query 时需重读 history，则它是 B01，不是紧凑 UCM。 | W03–W04、W08–W09、W14、W19–W20；历史删除和时间尺度实验。 | attention 没有因果/状态语义保证；固定 memory 遗忘罕见禁忌；slot 写入难校准；不同 query token 可形成事实上的任务私有读取；无界 memory 退化成历史库。 | 在线 recurrent memory transformer/compressive memory，固定少量 slots，单一 write rule；stateless heads 和 action-conditioned transition。 | slots/summary 全序列化且容量固定；禁外部 retrieval 与 raw-history cross-attention；query 只读不写；不允许 per-task slot banks；报告每个 head 的 attention 但 QKV 不作为充分性证据。 |
| C11 | 若 typed program configuration 是充分状态，W05/W06/W20 的延迟、observation-only effect 和 treatment typestate 应由同一 rewrite trace正确区分；新机制/action 应通过局部规则扩展。若规则必须按 world/disease/test ID 分支，或连续不确定性只能另接黑箱任务模型，则核心假说失败。 | W05–W08、W13–W14、W16–W17、W20；W02/W18 检验 uncertainty/OOD。 | state/rule explosion；连续概率校准弱；手写规则和优先级脆弱；并发/冲突/数值 integration 复杂；程序配置可变相保留完整史。 | typed probabilistic multiset rewriting：10–30 条封闭规则、numeric registers、timers、action typestate、distribution over configurations。 | rule registry 无 world/test/disease/expected-answer predicate；三个 query clone 同一 config；无 head-private agenda/cache；residual event log 若随历史增长必须计入状态并判是否退化 B01。 |

## 4. 四个强制基线矩阵

四个基线用于回答不同问题，不能互相替代，也不能进入“合规 UCM 候选”计数。

| ID | 基线 | “状态”与 update/query | 可证伪用途与主要世界 | 结构性弱点 / 不得声称 | 最小实现 | 审计点 |
|---|---|---|---|---|---|---|
| B01 | **Full-history oracle-like baseline**（只保留完整 *visible* history；不含隐藏真状态） | `Z_t` 是截至 cut 的不可变完整 candidate-view history；update 只 append。每个 query 可从头扫描历史并建立临时表示。 | 给 W08/W14/W20 路径依赖提供“不因压缩丢信息”的参照；与候选比较 state size、历史删除和新任务迁移。若它也失败 W15/W17，说明完整史本身不提供 causal identification 或 unseen-action knowledge。 | 状态长度无界；query-time re-encoding；可能有 task-specific 临时 latent；因此是无压缩信息基线，不通过紧凑共享状态门，也不是 oracle truth。 | canonical event history + 一个通用 history-conditioned sequence/query engine；若使用多个 task heads必须披露，不能与 B02 混称。 | 严禁 simulator true state/future；所有历史字段受 cut；完整历史字节计入状态成本；明确标记豁免 G01 query-history 禁令且因此 UCM-compliance=false。 |
| B02 | **Separate-task baseline** | 三个独立状态/模型 `Z_D,Z_N,Z_T` 分别 update；诊断、自然预测、治疗各读自己的最佳表示。 | 测三任务专用优化的性能上界/竞争线。共享候选不能在任一任务不可接受退化，且应在样本效率、一致性、组合泛化、紧凑性或新任务迁移至少一项占优。 | 按定义违反一张地图；三项输出可互相矛盾；参数/样本/患者状态成本通常更高。高单项得分不能证明 UCM。 | 三个容量/调参预算透明的独立 HMM/GRU/causal predictor，分别针对 A/B/C 任务训练；总预算与单模型预算都报告。 | 明确保留三个 hash，绝不把 tuple 包装成一个 hash；同样做 future/oracle 污点测试；性能只作 Pareto comparator，shared-state gate 必须失败。 |
| B03 | **True-state upper bound** | `Z_t` 直接是模拟器完整 Markov hidden state、exogenous modifiers、必要 exposure/history variables；oracle transition/observation/counterfactual engine update/query。 | 给所有 W01–W20 提供 Bayes/Monte-Carlo 上界并校验 world oracle。若 B03 在 W20 仍碰撞，说明“true state”漏了治疗历史或 benchmark/oracle 有 bug，而不是候选问题。 | 运行时不可获得，存在明确 privileged leakage；不能训练/调参后降格为候选，不能支持现实有效性主张。 | oracle adapter 在隔离父进程读取 true state，固定 seeds 做 exact/高样本 rollout，输出同一 metrics schema。 | 物理隔离并标 `privileged=true`；candidate process 无法 import/read；结果不参与合规排名，只用于 upper-bound 和 harness self-test。 |
| B04 | **K0-only negative-control baseline** | “状态”只有合格 evidence 引用、temporal cut、版本/审计 envelope；没有患者 mechanism、transition、observation 或 intervention model。update 只做合法 ingestion/versioning。 | 应正确拒绝或在 diagnosis/natural/treatment 指标上保持无信息；证明控制面、路由、QKV、接口一致性本身不能完成患者地图。若它得到非平凡临床分数，应调查隐藏 callback/model、label leakage 或 evaluator 给分错误。 | 没有世界动力学、causal state 或 shared patient state；不得借用 K0 后面的现有 SSM/SCM/rewrite 子核并把结果记给 K0。 | 复用现有隔离/cut/candidate-view 测试基础设施；临床 query 返回 typed `unsupported`，metrics 按冻结规则记缺失/失败而非偷偷 fallback。 | manifest 必须为空 clinical capability；阻断 foreign callback、LLM、lookup table 和 candidate plugin；仅允许审计元数据，不能把 history reference 叫作 UCM state。 |

### 4.1 B01 与 B03 的名称隔离

- B01 的 “oracle-like” 仅指**不压缩任何已允许看见的历史**，仍然不知道真实隐藏机制和未发生反事实。
- B03 才能读取 simulator true state/parameters/counterfactual oracle；它必须在独立进程和结果分组中标成 privileged upper bound。
- 两者若混在一起，无法判断候选失败来自压缩、系统识别还是 causal information 不足。

## 5. 家族去重与实验计数规则

以下变化**不能**新增一个架构家族：

1. 同一 RSSM/SSM 只改 hidden size、layer 数、粒子数、学习率或 optimizer；
2. C06 只换一个 feature dictionary 而 state/update/query 语义不变；
3. C08 把 graph neural network、ODE reaction graph 的执行器互换，但仍是同一机制图状态主张（可以算重大消融，不自动算新家族）；
4. 给任一候选加 attention、Transformer encoder、LLM 或 QKV，但共享状态语义未改变；这些是实现工具，不是新患者地图；
5. 把 C01/C02/C05 三个 task 模型的输出拼成一个 JSON；这是 B02 的包装；
6. 在 K0/TEL 里存 candidate handle、history pointer 或任意 payload；这是控制面/存储，不是 UCM；
7. 将完整 history 压进 lossless blob、KV cache、检索库或可逆 embedding；若单患者描述长度仍随历史增长，按 B01 类退化报告；
8. 为 Wxx、疾病名、预期机制、测试 ID、seed 或答案写专属分支。

以下变化可登记为**重大架构/消融实验**，但需事先写可证伪假说：

- C02 从 fixed latent Markov state 改成显式 semi-Markov/path-memory augmentation；
- C03 因新 action/test 导致 core-test rank 扩张，并比较局部扩维与全重建；
- C04 从 exact finite partition 到数据学习 approximate behavioral metric；
- C05 添加/移除共享 `U` 的个体反事实语义；
- C06 比较固定解析 lift 与 learned invariant lift；
- C07 比较 RSSM 与 continuous-time neural SDE，但仍只计一个家族；
- C08 显式 interaction node 对比平行图简单相加；
- C09 改变 residual 的合法 ports/约束，而不是只改宽度；
- C10 bounded slots 对比随历史增长 memory，以确认是否退化 B01；
- C11 deterministic rewrite 对比 probabilistic configuration belief。

## 6. 结果记录必须支持的横向裁决

候选和基线统一输出下面的原始证据，最终不以单一总分选胜者：

```text
run_id, candidate_family, implementation_id, code_hash, benchmark_hash
knowledge_tier, train/validation/test generator hashes, seeds, tuning budget
per-world/per-task raw metrics and calibration bins
state_hash before every query; updated_state_hash after every real event
serialized state size and growth curve; global model/handwritten description size
collision pairs, action causing divergence, regret severity, false splits
OOD score/decision, unsupported queries, failure traces
new-check/new-action/new-task extension diff and retraining cost
train/inference wall time, peak memory, particles/nodes/slots/configurations
all UCM-G01..G10 traces and family-specific audit outputs
```

先应用硬淘汰：泄漏、task-specific latent、危险治疗碰撞、`see=do`、高置信强塞 OOD、测试专属分支、不可复现、或伪装完整历史。通过后才按诊断、自然预测、干预预测、治疗后悔、校准、OOD、样本效率、状态简洁性、扩展代价、计算和可解释性画 Pareto 前沿。

本草案不对 C01–C11 排序；每一行都是待实验推翻的状态假说。
