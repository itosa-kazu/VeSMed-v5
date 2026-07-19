# Unified Clinical Map（UCM）一手来源账本

> **核验日期**：2026-07-15。
> **状态**：`ACTIVE / UCM track only`；本文件不修改、替代或继承根目录 K0 的 `SOURCES.md`。
> **纳入规则**：核心证据只保留原始论文、正式会议/期刊正文、作者原稿或机构保存的原文；不以教科书、综述、博客或搜索结果摘要作为核心证据。有 DOI 时优先给 DOI；无 DOI 时给可复核的会议或作者正文。
> **核验状态**：`VERIFIED-DOI` 表示 DOI 已解析并核对标题/作者/年份；`VERIFIED-PRIMARY` 表示官方会议页、PMLR/NeurIPS 正文、作者原稿或机构原文已核对；`TODO-unverified` 不得进入架构结论。当前核心表没有 `TODO-unverified` 条目。
> **解释边界**：这些来源各自只证明局部形式结果、明确假设下的定理或论文内原型结果，**没有任何一篇证明临床 UCM 存在**。下文“UCM 可运行候选”是本研究由来源导出的可证伪工程假说，不是原作者的临床结论。

## 0. 核验与使用规则

1. 每个已纳入文献家族分开写明：状态定义、干预语义、部分可观察处理、有限维与可识别条件、最根本反例，以及映射到本轨相关 `F01`–`F11` 的可运行候选；没有直接一手支撑的工程家族不从相邻论文外推定理保证。
2. “能表示”不等于“从数据可识别”；“对固定 reward/policy 充分”不等于“对所有检查、治疗和新读出充分”；“action-conditioned”也不自动等于从观察性数据识别出的 `do(action)`。
3. 有限维结论只能在来源写明的 rank、有限隐藏状态、闭合 invariant subspace、有限变量/有限阶或其他条件内使用。没有一般“有限临床 UCM 必然存在”的定理。
4. DOI/链接可达只证明出版物身份；正文命题仍按各条“支持/不支持”窄化。若后续发现元数据或命题无法复核，必须原位降级为 `TODO-unverified`，不能猜测补全。
5. 根本判据是冻结实验类下的 action/check-indexed future-law 等价；任何候选仍须由 W01–W20、碰撞、OOD、新检查、新治疗和新任务读出运行证据裁决。

## 1. 本研究冻结的“状态充分性”判据

令可见历史为 `H_t=(o_0,a_0,...,o_t)`，允许的未来实验（等待、检查、治疗序列）为 `e in E`，未来可见轨迹与结局为 `Y^e_{t:}`。UCM 的强判据是：

```text
Z_t = phi(H_t)

H_t ~ H'_t
iff
for every allowed future experiment e:
    Law(Y^e_{t:} | H_t) = Law(Y^e_{t:} | H'_t)
```

候选若只保留某一个 reward、某一种自然病程、某一个检查集或训练时任务的充分信息，就不能据此声称对 UCM 的全部任务充分。新增检查或治疗会扩大 `E`，从而可能严格细分旧状态。这一判据与 PSR/causal-state/behavioral equivalence 的共同核心相近，但本研究额外要求 **action/intervention-indexed futures**，不能把无控制时间序列的预测充分性直接提升成治疗充分性。

统一实现合规接口（仅为测试，不是“接口即地图”）：

```python
z_t = encoder(history_visible_at_t)
diagnosis = diagnosis_readout(z_t)
future = rollout(z_t, action_sequence)
z_next = update(z_t, action_taken, new_observation)
```

`diagnosis_readout`、`rollout`、`update` 都只能读同一个 `z_t`；不得再读完整历史、模拟器真状态、未来、world id 或任务专用 hidden state。

## 2. 架构家族对照表（定义、保证、边界、候选）

### F1. 经典受控状态空间 / realization / system identification

- **状态定义**：`x_{t+1}=f(x_t,u_t,w_t)`, `y_t=h(x_t,v_t)`；线性情形为 `(A,B,C,D)`。行为学表述不先指定输入输出，而把系统定义成允许轨迹集合；状态承担“给定当前值即可拼接相容过去与未来”的角色。
- **为什么充分**：在模型正确且 Markov state 完整时，给定 `x_t` 和未来输入，未来与更早历史条件独立。Ho–Kalman 从 Markov parameters/Hankel 结构构造最小有限维线性 realization；Willems 给出有限维 LTI 行为的轨迹级刻画。
- **干预**：原生支持输入/控制 `u_t`，但 `u_t` 是否等于因果 `do()` 仍取决于系统边界与混杂假设；从被选择的历史治疗回归出 `B` 不是自动的因果识别。
- **部分可观察**：状态空间模型允许 observation map；需要 Kalman/particle/nonlinear filter 才能从历史形成状态后验。仅把当前观测当状态不够。
- **可识别性**：线性 realization 通常只识别到 similarity transform；需要持续激励、可控/可观与秩条件。非线性结构和参数可能不可识别。
- **有限维保证**：有限 Hankel rank/LTI realization 时有；Takens 只在紧致有限维流形、generic observation、确定性自治动力学等条件下给有限 delay embedding，不覆盖噪声、任意控制与反事实。一般过程没有统一有限维保证。
- **最根本反例 / 限制**：W03/W14 直接击穿 `z_t=o_t`；W15 击穿把观察治疗相关性当控制作用；新机制可令固定维 realization 不闭合。
- **UCM 可运行候选映射**：`F02-SSM` 使用小型 controlled nonlinear SSM + shared particle belief（而不是 posterior mean）作为 `Z_t`，另跑线性 Ho–Kalman/N4SID 基线；`F01` 的人工机制向量也可复用本节的 filter/controlled-transition 语义，但人工坐标是否闭合只能由消融和碰撞实验决定。训练只看合法历史，统一 action-conditioned transition 与 observation head；用 W03/W04/W14/W15 检查遗漏机制、路径依赖与混杂。

关键一手来源（每条先写“直接支持”，分号后写“不支持/条件边界”）：

1. **[SSM-01 · VERIFIED-DOI]** R. E. Kalman, “A New Approach to Linear Filtering and Prediction Problems” (1960), DOI [10.1115/1.3662552](https://doi.org/10.1115/1.3662552)。原始递推 filter 把隐藏状态预测、观测更新和估计协方差统一；保证依赖线性/噪声模型。
2. **[SSM-02 · VERIFIED-DOI]** B. L. Ho & R. E. Kalman, “Effective construction of linear state-variable models from input/output functions” (1966), DOI [10.1524/auto.1966.14.112.545](https://doi.org/10.1524/auto.1966.14.112.545)，[NASA 原文重印记录](https://ntrs.nasa.gov/citations/19670049337)。由 input/output Markov parameters 构造最小有限维 realization；不覆盖一般非线性、任意部分可观察过程或因果识别。
3. **[SSM-03 · VERIFIED-DOI]** J. C. Willems, “From time series to linear system—Part I. Finite dimensional linear time invariant systems” (1986), DOI [10.1016/0005-1098(86)90066-X](https://doi.org/10.1016/0005-1098(86)90066-X)。把 dynamical system 作为轨迹族并刻画何时存在有限维 LTI realization；这是强条件下的存在结果，不是任意临床过程的压缩定理。
4. **[SSM-04 · VERIFIED-DOI]** J. C. Willems, “From time series to linear system—Part II. Exact modelling” (1986), DOI [10.1016/0005-1098(86)90005-1](https://doi.org/10.1016/0005-1098(86)90005-1)。从 truncated behavior/时间序列研究 exact model 与 minimal state realization；“exact”针对该 LTI 行为类。
5. **[SSM-05 · VERIFIED-DOI]** P. Van Overschee & B. De Moor, “N4SID: Subspace algorithms for the identification of combined deterministic-stochastic systems” (1994), DOI [10.1016/0005-1098(94)90230-5](https://doi.org/10.1016/0005-1098(94)90230-5)。给出 stochastic/deterministic LTI 的 subspace identification；输出 realization 坐标不是唯一生理机制。
6. **[SSM-06 · VERIFIED-DOI]** F. Takens, “Detecting strange attractors in turbulence” (1981), DOI [10.1007/BFb0091924](https://doi.org/10.1007/BFb0091924)。generic delay embedding 给自治有限维确定性动力学的观测重建条件；不能外推到随机、非平稳、受控或未知干预的 UCM。
7. **[SSM-07 · VERIFIED-DOI]** S. L. Brunton, J. L. Proctor & J. N. Kutz, “Sparse Identification of Nonlinear Dynamics with Control” (2016), DOI [10.1016/j.ifacol.2016.10.249](https://doi.org/10.1016/j.ifacol.2016.10.249)。SINDYc 从候选函数库稀疏识别受控动力学；库遗漏和状态不可见会直接破坏结构恢复。

### F2. POMDP belief state

- **状态定义**：`b_t(s)=P(S_t=s | H_t)`；不是 MAP 隐状态，而是对隐藏 Markov state 的完整后验。
- **为什么充分**：当 transition/observation model 已知且隐藏状态 Markov 时，Bayes belief update 使 belief 成为 fully observed belief-MDP 的信息状态；任何未来 action-observation-reward distribution 可由 belief 推出。
- **干预**：行动是 transition kernel 的索引，原生支持计划/控制；但从非随机行为数据估计 action kernel 仍需 coverage/因果假设。
- **部分可观察**：这是它的主问题；新观察用 Bayes update 回写同一 belief。
- **可识别性**：belief 的充分性假设正确的 latent model；仅从 observation-action 数据恢复 latent states 需要可辨识/秩/探索条件，隐藏标签通常只到 permutation。
- **有限维保证**：有限隐藏状态 `|S|` 时 belief 位于 `|S|-1` 维 simplex；连续 state、未知静态参数或非参数 model 时 belief 是分布对象，通常无限维。
- **最根本反例 / 限制**：错误/过粗 latent state 会在 W04/W17 产生治疗碰撞；用 posterior mean 代替分布会丢多峰；未知新机制 W18 不在闭合 simplex 内。
- **UCM 可运行候选 `F02-BELIEF`**：对每个 microworld 只给 candidate 合法 observation/action alphabet，不给真状态；用小型离散 latent model 的 exact Bayes filter 或 learned HMM/POMDP EM，`Z_t` 为完整 belief + 参数后验（若启用）。所有三类读出都由同一 belief rollout 求期望。

关键一手来源（每条先写“直接支持”，分号后写“不支持/条件边界”）：

1. **[POMDP-01 · VERIFIED-DOI]** K. J. Åström, “Optimal Control of Markov Processes with Incomplete State Information I” (1965), DOI [10.1016/0022-247X(65)90154-X](https://doi.org/10.1016/0022-247X(65)90154-X)，[作者机构存档](https://lup.lub.lu.se/record/8867084)。原始不完全状态信息控制论证把条件状态分布作为 information state；充分性依赖给定 Markov model。
2. **[POMDP-02 · VERIFIED-DOI]** R. D. Smallwood & E. J. Sondik, “The Optimal Control of Partially Observable Markov Processes over a Finite Horizon” (1973), DOI [10.1287/opre.21.5.1071](https://doi.org/10.1287/opre.21.5.1071)。有限 POMDP 在 belief simplex 上规划，并导出 finite-horizon value 的 piecewise-linear/convex 结构；simplex 连续且求解复杂度仍高。
3. **[POMDP-03 · VERIFIED-DOI]** E. J. Sondik, “The Optimal Control of Partially Observable Markov Processes over the Infinite Horizon: Discounted Costs” (1978), DOI [10.1287/opre.26.2.282](https://doi.org/10.1287/opre.26.2.282)。出版页明确 state space 是 occupancy-probability distributions 的 unit simplex；给出无限期折扣控制的逼近/收敛路线，不是任意连续未知模型的有限算法。

### F3. Predictive State Representation / controlled PSR / Observable Operator Model

- **状态定义**：一组“tests”的成功概率；test 是从现在开始执行一个未来 action sequence 并看到指定 observation sequence 的事件。核心 test predictions 构成 `Z_t`，history 只通过这些 predictions 影响未来。
- **为什么充分**：若 system-dynamics/Hankel matrix 有有限 rank，选取一组 core tests 后，其他 tests 的预测是 core predictions 的函数（线性 PSR 是线性函数）；update 直接在可观察预测上进行。
- **干预**：controlled PSR 的 tests 显式包含未来动作，因此比无控制 causal states/IB 更接近 UCM 强判据。
- **部分可观察**：不要求 latent physical state 可见；状态本身由可观 action-observation tests 定义。
- **可识别性**：spectral PSR/OOM 需要 exploration/有效 sampling、observable matrix/full-rank 等条件；能识别的通常是预测等价 representation，不是唯一机制坐标。
- **有限维保证**：有限 linear dimension/Hankel rank 时成立；一般 nonlinear/continuous process 可为无限 rank。有限 POMDP 有有限 PSR rank 上界，但低阶可学习性不是无条件的。
- **最根本反例 / 限制**：若训练 tests 不含某治疗或检查，两个 histories 可在已有 core tests 下相等、却被 W16/W17 新 test 拆分；只预测有限 horizon 会漏 W05/W14 长延迟。
- **UCM 可运行候选 `F03-PSR`**：枚举 benchmark freeze 时的 action/check tests，构造 empirical Hankel，SVD 定秩并学习 action-observation operators；`Z_t` 是 core test prediction vector。冻结后把新 check/treatment 作为 withheld columns/actions，测旧 `Z_t` 是否线性/非线性可读或必须扩维重训。

关键一手来源（每条先写“直接支持”，分号后写“不支持/条件边界”）：

1. **[PSR-01 · VERIFIED-PRIMARY]** M. L. Littman, R. S. Sutton & S. Singh, “Predictive Representations of State” (NeurIPS 2001), [会议原文](https://proceedings.neurips.cc/paper_files/paper/2001/hash/1e4d36177d71bbb3558e43af9577d70e-Abstract.html)。以 multi-step, action-conditional future-observation predictions 表示 state；论文给有限 POMDP 构造维数不超过该 POMDP latent-state 数的 linear PSR，但不证明所有系统 finite rank，也不保证该构造在有限样本下可稳健学习。
2. **[PSR-02 · VERIFIED-PRIMARY]** S. Singh, M. R. James & M. R. Rudary, “Predictive State Representations: A New Theory for Modeling Dynamical Systems” (UAI 2004), [作者重存原稿](https://arxiv.org/abs/1207.4167)。引入 system-dynamics matrix，以 histories × tests 的预测结构导出 PSR 并比较 HMM/POMDP 表达力；实验集合改变会改变矩阵/秩。
3. **[PSR-03 · VERIFIED-DOI]** H. Jaeger, “Observable Operator Models for Discrete Stochastic Time Series” (2000), DOI [10.1162/089976600300015411](https://doi.org/10.1162/089976600300015411)。OOM 以 observable operators刻画 linearly dependent processes 并给 constructive learning；原文是无控制离散序列，不能直接当治疗模型。
4. **[PSR-04 · VERIFIED-DOI]** B. Boots, S. M. Siddiqi & G. J. Gordon, “Closing the learning-planning loop with predictive state representations” (2011), DOI [10.1177/0278364911404092](https://doi.org/10.1177/0278364911404092)。在其 rank/sampling assumptions 下给 computationally efficient、statistically consistent spectral PSR learner，并在视觉机器人任务闭环 planning；不是 finite-sample clinical safety 保证。

### F4. Computational mechanics causal states / behavioral equivalence

- **状态定义**：把具有相同条件未来分布的 pasts 放入同一 equivalence class，`epsilon(past)=[past]`；epsilon-machine 是 causal-state 转移结构。
- **为什么充分**：causal state 对未来预测充分，并在相应定义下是最小 predictive statistic；unifilar update 允许新符号更新同一状态。
- **干预**：经典 causal states 针对无控制随机过程；要满足 UCM，必须把 action/check policy 固定为外生输入，或定义对所有未来 action sequences 的 transducer/controlled causal equivalence。仅自然序列 causal state 不能通过 W04。
- **部分可观察**：从 observed pasts 定义，不要求 hidden generator 可见；但有限数据重建会有 truncation/model-selection 误差。
- **可识别性**：知道真实 process distribution 时 equivalence 定义明确；有限样本只能估计，稀有严重分支很容易被错误合并。
- **有限维保证**：没有一般保证；简单有限隐藏 HMM 也可诱导无限 predictive/causal states，有限 causal-state 假设必须实测。
- **最根本反例 / 限制**：只按自然未来等价会合并 W04；有限 horizon 会合并 W05/W14；新 action 扩大 experiment set 可细分旧 partition。
- **UCM 可运行候选 `F04-CAUSAL-STATE`**：构造 action-observation suffix tree，对 histories 的多 action、multi-horizon future distribution 做两样本距离/MDL 合并，状态为 cluster posterior；强制包含 rare-harm action outcomes，并用 W17 freeze 后 refinement 记录增长代价。

关键一手来源（每条先写“直接支持”，分号后写“不支持/条件边界”）：

1. **[CSTATE-01 · VERIFIED-DOI]** J. P. Crutchfield & K. Young, “Inferring Statistical Complexity” (1989), DOI [10.1103/PhysRevLett.63.105](https://doi.org/10.1103/PhysRevLett.63.105)。从 measurement sequences 的递归结构重建 minimal equations of motion，奠定 epsilon-machine 路线；该短文不含受控治疗语义。
2. **[CSTATE-02 · VERIFIED-DOI]** C. R. Shalizi & J. P. Crutchfield, “Computational Mechanics: Pattern and Prediction, Structure and Simplicity” (2001), DOI [10.1023/A:1010388907793](https://doi.org/10.1023/A:1010388907793)，[作者原稿](https://arxiv.org/abs/cond-mat/9907176)。给 causal-state partition 的 predictive sufficiency、minimality/uniqueness 条件；这些是对指定 stationary stochastic process 的结果，不含治疗干预语义。
3. **[CSTATE-03 · VERIFIED-DOI]** N. Barnett & J. P. Crutchfield, “Computational Mechanics of Input-Output Processes: Structured Transformations and the ε-Transducer” (2015), DOI [10.1007/s10955-015-1327-5](https://doi.org/10.1007/s10955-015-1327-5), [作者页/正文](https://csc.ucdavis.edu/~cmg/compmech/pubs/et1.htm)。把 causal-state 思路扩展到有 input 的 memoryful channel，是 controlled behavioral-state 最直接的原始形式来源；输入过程与可实施治疗之间仍需 benchmark 语义连接。
4. **[CSTATE-04 · VERIFIED-PRIMARY]** A. Zhang et al., “Learning Causal State Representations of Partially Observable Environments” (2019), [作者原稿](https://arxiv.org/abs/1906.10437)。以 joint action-observation histories 的 coarsest predictive partition近似 POMDP causal states，并在明确 Lipschitz assumptions 下连接 bisimulation；神经近似实验不证明 exact/minimal recovery。
5. **[CSTATE-05 · VERIFIED-DOI]** S. Marzen & J. P. Crutchfield, “Informational and Causal Architecture of Discrete-Time Renewal Processes” (2015), DOI [10.3390/e17074891](https://doi.org/10.3390/e17074891)，[作者页](https://csc.ucdavis.edu/~cmg/compmech/pubs/dtrp.htm)。论文分析的 Simple Nonunifilar Source 由简单两状态 HMM 生成，却有 infinite-state epsilon-machine presentation；这是“有限 generative HMM 并不蕴含有限最小 predictive/causal-state map”的直接反例。它不证明所有有限 HMM 都会产生无限 predictive state。

### F5. Bisimulation / MDP state abstraction

- **状态定义**：经典 MDP bisimulation 要求被合并 states 对每个 action 有相同 immediate reward，且转移到每个 equivalence block 的概率相同；metric 版本把差异变成距离。
- **为什么充分**：在固定 reward/action MDP 下，exact bisimulation quotient 保持 value/relevant control behavior；它是任务相关行为等价，不自动保持所有未来观测或所有新任务。
- **干预**：原生逐 action 比较 transition；新增 action 可拆分 quotient。
- **部分可观察**：经典定义作用于 MDP state；POMDP 中必须先在 histories/beliefs 上做，不能直接把 observation 当 state。
- **可识别性**：从 samples 学 transition/reward similarity 需要 coverage；rare action/outcome 未采到会假合并。
- **有限维保证**：有限 MDP 的 exact quotient 有限；连续/近似 metric 只有误差界和函数逼近，不保证有限最小 code。
- **最根本反例 / 限制**：reward-conditioned abstraction 会丢失未参与训练的新诊断/检查 readout；W19 平均误差很小仍可有 catastrophic collision。只训练最优 policy 下 transitions 不能保证 off-policy treatment sufficiency。
- **UCM 可运行候选 `F04-BISIM`**：在 history/belief embeddings 上，以 **全 action 的 observation+outcome distribution** 而非单 reward 训练/求解 approximate bisimulation；另做 reward-only ablation 作为预期失败基线。新任务 readout必须冻结 encoder 后训练。

关键一手来源（每条先写“直接支持”，分号后写“不支持/条件边界”）：

1. **[BISIM-01 · VERIFIED-DOI]** R. Givan, T. Dean & M. Greig, “Equivalence notions and model minimization in Markov decision processes” (2003), DOI [10.1016/S0004-3702(02)00376-4](https://doi.org/10.1016/S0004-3702(02)00376-4), [作者正文](https://cs.brown.edu/people/tdean/publications/archive/GivanetalAIJ-03.pdf)。定义 stochastic/MDP bisimulation reduction，并证明 reduced model 的 optimal policy 可 lift；结论针对给定 MDP/reward。
2. **[BISIM-02 · VERIFIED-PRIMARY]** N. Ferns, P. Panangaden & D. Precup, “Metrics for Finite Markov Decision Processes” (AAAI 2004), [会议原文](https://cdn.aaai.org/AAAI/2004/AAAI04-124.pdf), [作者原稿](https://arxiv.org/abs/1207.4114)。给 bisimulation metric 与 value difference bounds；metric 近不等于所有新任务/观测 future law 相同。
3. **[BISIM-03 · VERIFIED-PRIMARY]** L. Li, T. J. Walsh & M. L. Littman, “Towards a Unified Theory of State Abstraction for MDPs” (ISAIM 2006), [作者原稿](https://thomasjwalsh.net/pub/aima06Towards.pdf)。比较多种 value/model-preserving abstractions及其正负结果；越 task-specific 的 abstraction 越不能作为 UCM 强充分性证据。
4. **[BISIM-04 · VERIFIED-PRIMARY]** C. Gelada et al., “DeepMDP: Learning Continuous Latent Space Models for Representation Learning” (ICML 2019), [PMLR 原文](https://proceedings.mlr.press/v97/gelada19a.html)。用 reward prediction + latent next-state distribution losses学习 continuous abstraction并给相应误差保证；训练 reward 是 representation 保留什么的组成部分，因此必须以新任务 probe 检查。

### F6. Dynamic SCM / causal representation

- **状态定义**：时刻 `t` 的 endogenous mechanism variables、必要的 lag variables/host parameters，以及在部分可观察时对 exogenous/latent variables 的 posterior；结构方程描述跨时机制。
- **为什么充分**：仅当变量集合闭合、结构方程和 exogenous distribution 正确且所保留 lags 使过程 Markov 时，当前 causal state 足以生成自然与介入未来。SCM 的优势是 intervention 语义，不是自动的 predictive sufficiency。
- **干预**：`do(A_t=a)` 用替换相应 structural equation 表达；sequential plan 可逐期作用。它把干预与普通 conditioning 区分开。
- **部分可观察**：latent/exogenous variables 可建模，但在线 `Z_t` 必须是其 posterior/particle set；只保存可见 endogenous point estimate 不充分。
- **可识别性**：观察分布一般不能唯一确定 causal graph/latent representation；顺序可忽略性、front/back-door、实验 intervention 或特定 CRL 假设才给局部识别。完美 intervention 下的 CRL 结果仍只在论文明确假设内成立。
- **有限维保证**：固定 finite-order、finite-variable SCM 可有限；未知对象/机制或非 Markov memory 需要增长 state。posterior 本身仍可能无限维。
- **最根本反例 / 限制**：W15 隐藏混杂令 `P(Y|A,H)` 不等于 `P(Y|do(A),H)`；cyclic SCM 可无解、多解或不诱导唯一分布；unsupervised disentanglement/CRL 无额外假设不可识别。
- **UCM 可运行候选 `F05-DSCM`**：固定通用 dynamic SCM schema（不读 world id），学习每个 mechanism structural transition 与 observation equations；`Z_t` 是 mechanism/exogenous particles。训练中显式区分 observational policy 与 randomized intervention episodes；在 W15 做 g-formula/intervention holdout，在 W13/W20 测非线性机制与历史依赖。

关键一手来源（每条先写“直接支持”，分号后写“不支持/条件边界”）：

1. **[CAUSAL-01 · VERIFIED-PRIMARY]** J. Pearl & J. M. Robins, “Probabilistic Evaluation of Sequential Plans from Causal Models with Hidden Variables” (UAI 1995), [作者原稿](https://arxiv.org/abs/1302.4977)。给出带隐藏变量的 sequential plans 可评估条件；不是“任意隐藏混杂都可识别”。
2. **[CAUSAL-02 · VERIFIED-DOI]** J. Robins, “A new approach to causal inference in mortality studies with a sustained exposure period” (1986), DOI [10.1016/0270-0255(86)90088-6](https://doi.org/10.1016/0270-0255(86)90088-6)。g-computation/时变 exposure 的原始路线；识别依赖明确的纵向因果假设。
3. **[CAUSAL-03 · VERIFIED-DOI]** S. A. Murphy, “Optimal Dynamic Treatment Regimes” (2003), DOI [10.1111/1467-9868.00389](https://doi.org/10.1111/1467-9868.00389)。DTR 是随 evolving status 定制的一串 decision rules；它本身没有证明存在一个对诊断、所有检查和反事实都充分的共享 state。
4. **[CAUSAL-04 · VERIFIED-DOI]** S. Bongers et al., “Foundations of Structural Causal Models with Cycles and Latent Variables” (2021), DOI [10.1214/21-AOS2064](https://doi.org/10.1214/21-AOS2064)。循环/latent SCM 需要 solvability 等附加条件；某些模型无解、多解或不产生唯一 observational/interventional/counterfactual distribution。
5. **[CAUSAL-05 · VERIFIED-PRIMARY]** F. Locatello et al., “Challenging Common Assumptions in the Unsupervised Learning of Disentangled Representations” (ICML 2019), [PMLR 原文](https://proceedings.mlr.press/v97/locatello19a.html)。无 inductive bias/supervision 时，unsupervised disentanglement 一般不可识别；latent 坐标看似可解释不是机制恢复证据。
6. **[CAUSAL-06 · VERIFIED-PRIMARY]** I. Khemakhem et al., “Variational Autoencoders and Nonlinear ICA: A Unifying Framework” (AISTATS 2020), [PMLR 原文](https://proceedings.mlr.press/v108/khemakhem20a.html)。在 auxiliary variable、条件 exponential-family 等条件下给 nonlinear ICA/latent identifiability；这些条件必须在 benchmark 中显式满足，不能默认。
7. **[CAUSAL-07 · VERIFIED-PRIMARY]** K. Ahuja et al., “Interventional Causal Representation Learning” (ICML 2023), [PMLR 原文](https://proceedings.mlr.press/v202/ahuja23a.html)。在 perfect do interventions 等明确条件下，latent causal factors 可识别到 permutation/scaling；正好可转成 randomized-intervention candidate，但不覆盖混杂的 observational EHR。

### F7. Koopman / observable operator / latent linear dynamics

- **状态定义**：选 observables `g(x)`，Koopman operator 线性推进函数 `g(x_{t+1}) = K g(x_t)`；EDMD 用有限 dictionary 近似。受控版本学习 input-indexed/operator-with-control dynamics。
- **为什么充分**：只有当 chosen observables 构成闭合 invariant subspace，且包含重建未来所需的 state/outputs 时，有限 `g(x_t)` 才精确充分；一般 EDMD 只是投影近似。
- **干预**：DMDc 可从数据区分 autonomous dynamics 与 actuation effect；更一般 nonlinear control 常需 action-indexed Koopman operators、bilinear lifted model 或扩展 state，不能把单一 autonomous `K` 当所有治疗。
- **部分可观察**：原始 Koopman 假设 state/observable functions 可求；部分观察时需 delay coordinates/filter/latent encoder，识别保证随之改变。
- **可识别性**：operator/eigenfunctions 依赖 sampling measure、dictionary 与 excitation；不同 lift 可给同样有限数据拟合。DMDc 需要输入与自然动力学可分辨。
- **有限维保证**：完整 Koopman 通常无限维。Brunton et al. 直接证明：包含原 state 的精确有限维 invariant subspace 对多固定点/复杂 attractor 的一般非线性系统很稀有。
- **最根本反例 / 限制**：W13 非线性共病、W17 新 action、OOD off-attractor rollout 会暴露有限 dictionary closure error；多 attractor 系统不能由一个包含 state 的全局有限线性 lift 精确表示。
- **UCM 可运行候选 `F06-KOOPMAN`**：action-conditioned EDMD/DMDc，dictionary 只由合法 observations/delays 学得；`Z_t=psi(history)`，一个 operator family rollout 所有 actions。必须保存 one-step closure residual 和 multi-step interventional error，若 residual/OOD 高则拒绝而不是继续线性外推。

关键一手来源（每条先写“直接支持”，分号后写“不支持/条件边界”）：

1. **[KOOP-01 · VERIFIED-DOI]** B. O. Koopman, “Hamiltonian Systems and Transformation in Hilbert Space” (1931), DOI [10.1073/pnas.17.5.315](https://doi.org/10.1073/pnas.17.5.315)。奠定在函数空间上线性演化的自治算子视角；不是有限维数据算法。
2. **[KOOP-02 · VERIFIED-DOI]** M. O. Williams, I. G. Kevrekidis & C. W. Rowley, “A Data-Driven Approximation of the Koopman Operator: Extending Dynamic Mode Decomposition” (2015), DOI [10.1007/s00332-015-9258-5](https://doi.org/10.1007/s00332-015-9258-5)。EDMD 用 dictionary/Galerkin 近似 operator；结果受字典与采样支配。
3. **[KOOP-03 · VERIFIED-DOI]** J. L. Proctor, S. L. Brunton & J. N. Kutz, “Dynamic Mode Decomposition with Control” (2016), DOI [10.1137/15M1013857](https://doi.org/10.1137/15M1013857)。把 actuation 纳入 low-order input-output identification；适合 `F06-KOOPMAN` 最小实现。
4. **[KOOP-04 · VERIFIED-DOI]** S. L. Brunton et al., “Koopman Invariant Subspaces and Finite Linear Representations of Nonlinear Dynamical Systems for Control” (2016), DOI [10.1371/journal.pone.0150171](https://doi.org/10.1371/journal.pone.0150171)。论文明确给出包含原 state 的有限维 exact invariant subspace 的强限制；不支持“任意非线性系统总有一个全局、有限且精确的 Koopman lift”。
5. **[KOOP-05 · VERIFIED-DOI]** M. Korda & I. Mezić, “Linear predictors for nonlinear dynamical systems: Koopman operator meets model predictive control” (2018), DOI [10.1016/j.automatica.2018.03.046](https://doi.org/10.1016/j.automatica.2018.03.046)。展示近似 lifted linear predictor 接 MPC；工程效用不等于全局 exactness。

### F8. Neural world model / recurrent stochastic state model (RSSM)

- **状态定义**：learned deterministic recurrent memory `h_t` 与 stochastic latent `s_t`（或 VAE code + RNN hidden）；action-conditioned transition 在 latent space rollout，observation/reward/value heads读取 latent。
- **为什么充分**：没有一般定理。只有训练 objective 覆盖的 observation/outcome/action futures 被准确、校准预测，且 frozen 新读出也可从 latent 恢复时，实验上才支持近似充分。
- **干预**：action-conditioned imagination 原生支持候选治疗 rollout，但行为 policy coverage 外的 actions 容易 model exploitation；“action input”仍不自动消除观察数据混杂。
- **部分可观察**：RSSM 的 recurrent deterministic path + stochastic posterior 专门汇总 observation history；是实用优势。
- **可识别性**：neural latent 通常只到可逆变换甚至更弱；reward/value-only objective 可主动丢掉诊断或新检查需要的信息。
- **有限维保证**：由 hidden size 强制有限，只是近似预算，不是环境存在有限 sufficient state 的证明。
- **最根本反例 / 限制**：Ha–Schmidhuber 直接展示 controller 会利用 learned world 的误差；PlaNet/RSSM 的部分可观察 rollout 成功不提供 OOD 校准或新任务充分性保证；MuZero 只学 policy/value/reward-relevant model，是“任务充分但非 UCM 充分”的强边界示例。
- **UCM 可运行候选 `F07-RSSM`**：单个 RSSM latent 同时训练全 action observation-distribution、mechanism posterior、outcome trajectories；三 heads 不得各有 recurrent memory。冻结 encoder 后加 unseen check/new-task probes；再用 adversarial planner 找 model exploitation，W19 用 tail-risk而非均值 loss。

关键一手来源（每条先写“直接支持”，分号后写“不支持/条件边界”）：

1. **[WORLD-01 · VERIFIED-PRIMARY]** D. Ha & J. Schmidhuber, “Recurrent World Models Facilitate Policy Evolution” (NeurIPS 2018), [会议原文](https://proceedings.neurips.cc/paper/2018/hash/2de5d16682c3c35007e4e92982f1a2ba-Abstract.html)。VAE code + action-conditioned MDN-RNN hidden 支持 imagined rollouts；“cheating the world model”是 UCM 必测的模型利用反例。
2. **[WORLD-02 · VERIFIED-PRIMARY]** D. Hafner et al., “Learning Latent Dynamics for Planning from Pixels” (ICML 2019), [PMLR 原文](https://proceedings.mlr.press/v97/hafner19a.html)。PlaNet/RSSM 用 deterministic+stochastic latent 与 multi-step latent overshooting 处理部分可观察控制；论文不建立 OOD 校准、因果识别、诊断充分性或冻结后新读出充分性。
3. **[WORLD-03 · VERIFIED-PRIMARY]** D. Hafner et al., “Dream to Control: Learning Behaviors by Latent Imagination” (ICLR 2020), [会议页](https://iclr.cc/virtual_2020/poster_S1lOTC4tDS.html)，[作者原稿](https://arxiv.org/abs/1912.01603)。共享 latent imagination 可训练 policy；其成功指标是既定 control tasks，不证明诊断/新 readout sufficiency。
4. **[WORLD-04 · VERIFIED-DOI]** J. Schrittwieser et al., “Mastering Atari, Go, chess and shogi by planning with a learned model” (2020), DOI [10.1038/s41586-020-03051-4](https://doi.org/10.1038/s41586-020-03051-4)。MuZero 明确只预测 planning-relevant policy/value/reward；因此是 task-oriented latent 不能自动叫 unified map 的第一手边界证据。

### F9. Information bottleneck / predictive sufficient statistic

- **状态定义**：从 past/history `H` 压缩出 `Z`，在最小化 `I(H;Z)` 的同时保留关于 relevant variable 的 `I(Z;Y)`；predictive IB 把 `Y` 取为 future。
- **为什么充分**：一般 IB 解是受 rate/complexity 约束的 lossy code，不是 exact sufficient statistic。只有零预测损失/无限相关性极限且 target 包含 UCM 所有 action-indexed future tests 时，才接近强判据。
- **干预**：经典 IB/过去-未来 IB 没有 intervention；必须把 future target 改成按计划动作索引的联合预测，且训练覆盖每个 action，否则 W04/W17 必败。
- **部分可观察**：以 history 为输入可处理；但有限窗口本身可能漏 long memory。
- **可识别性**：给定 joint distribution 可定义最优 tradeoff；有限样本 density/variational bounds、encoder nonuniqueness 和 local optima 不保证恢复最小 causal state。
- **有限维保证**：codebook/latent dimension 可被预算限制，但 exact finite sufficient representation 没有一般保证；随着预测精度提高，所需维度可发生 phase transition/继续增长。
- **最根本反例 / 限制**：只把自然 future 或单一 clinical outcome 当 `Y`，会压掉治疗异质性、新检查和新任务信息；IB 高分也可能产生危险 state collision。
- **计划假说 `H-CPIB-planned`**：controlled predictive IB：encoder 读合法 history；decoder 随机抽取 action/check sequence，预测完整 multi-horizon observation+outcome distribution；增加 compression sweep 画 state-size—collision—regret Pareto，而不预设单一 beta。它是历史 planned slot，不是实际 `EXP-025`；实际 `EXP-025` 是 F18。

关键一手来源（每条先写“直接支持”，分号后写“不支持/条件边界”）：

1. **[IB-01 · VERIFIED-PRIMARY]** N. Tishby, F. Pereira & W. Bialek, “The Information Bottleneck Method” (Allerton 1999/author version 2000), [作者原稿](https://arxiv.org/abs/physics/0004057)。定义压缩 `X` 同时保留关于 `Y` 的信息；相关变量选择决定何种信息会被删除。
2. **[IB-02 · VERIFIED-DOI]** F. Creutzig, A. Globerson & N. Tishby, “Past-future information bottleneck in dynamical systems” (2009), DOI [10.1103/PhysRevE.79.041925](https://doi.org/10.1103/PhysRevE.79.041925)。把 past 压缩为预测 future 的 state，展示精度增加时 state dimension/结构 phase transitions；论文主结果不是受控干预充分性。
3. **[IB-03 · VERIFIED-DOI]** S. Still, J. P. Crutchfield & C. J. Ellison, “Optimal Causal Inference: Estimating Stored Information and Approximating Causal Architecture” (2010), DOI [10.1063/1.3489885](https://doi.org/10.1063/1.3489885), [作者原稿](https://arxiv.org/abs/0708.1580)。用 causal shielding/rate-distortion 形成 causal-state 近似层级；有限数据需显式 complexity control。
4. **[IB-04 · VERIFIED-DOI]** D. Blackwell, “Equivalent Comparisons of Experiments” (1953), DOI [10.1214/aoms/1177729032](https://doi.org/10.1214/aoms/1177729032)。Blackwell experiment comparison 提供“对所有决策问题不损失”的严格参照；它提醒 UCM 不能只用单任务 readout 证明 sufficiency。

### F10. Dynamic treatment regimes（决策层；不是单独 UCM 答案）

- **状态定义**：每期 decision rule 以 evolving observed status/history/tailoring variables 为输入；DTR 文献通常不主张这些变量是所有未来任务的最小 sufficient state。
- **充分性**：只针对目标 mean outcome 与所建模 regime；一个最优 policy 可以在很多不同 world models 上相同，因此 policy/value 不能反推统一患者地图。
- **干预**：明确 sequential treatment/regime，但 action rule 或 Q-function 本身不是 patient world state。
- **部分可观察**：latent disease state 通常不由 DTR 本身解决；若 tailoring history 未形成充分 information state，策略仍可遗漏治疗效应修饰因素。
- **可识别性**：观察性 regime effect 依赖 consistency、positivity、sequential exchangeability 等 longitudinal causal assumptions；论文不把这些假设变成数据自动可检验的事实。
- **有限维保证**：取决于 chosen tailoring history；历史可以增长，DTR 形式本身不给一般有限维状态保证。
- **最根本反例 / 限制**：W03 可有相同最优治疗却不同诊断/自然过程；W16 新检查需要比旧 policy 更多信息。
- **UCM 用法**：只作为 `Z_t` 上的 policy/regret evaluation layer，和 randomized sequential experiment 数据生成方案；不得把 action rule 或 Q-function 本身命名为 UCM。

来源见 F6 的 Robins、Murphy 与 Pearl–Robins。它们支持 sequential intervention/decision 的形式与识别边界，不支持共享状态存在性。

### F11. Reaction network / mechanism graph / compositional dynamics

- **状态定义**：固定 species/mechanism 的 counts 或 concentrations，reaction channels 由 stoichiometry 与 propensities/rate laws 驱动；open dynamical systems另有 input/output ports。图结构不是状态本身，当前 species vector（或其 posterior）才是动态 state。
- **为什么充分**：在网络、rate laws 与 Markov assumptions 正确时，当前 counts/concentrations + inputs 决定下一步分布/ODE drift；Gillespie 的 chemical master equation 情形给 exact stochastic path sampler。
- **干预**：可改变 inflow、reaction channel/rate、加入 treatment species 或 mechanism modulation；必须区分改变 observation channel 与改变内部 reactions（W06/W07）。
- **部分可观察**：原始 network dynamics不自动解决；只观测部分 species 时需 Bayesian filter，`Z_t` 应为网络 state posterior。
- **可识别性**：即便完整连续观测所有 species，也可能存在不同 networks/parameters 产生同一 dynamics；Craciun–Pantea 给直接反例。结构正确不等于参数可识别。
- **有限维保证**：固定有限 species/reactions 时 state 有限维（stochastic counts 的 state space仍可无限）；新增机制/检查可能扩图扩维。组合范畴保证按 typed ports 组装，不保证组装后的临床语义正确或低维。
- **最根本反例 / 限制**：W13 非线性共病可由交叉 reaction 表示，但若只线性叠加子图会失败；W18 新机制不在固定 graph；不同 networks 的动态等价说明“解释性图”不一定可辨真。
- **UCM 可运行候选 `F08-RXN`**：通用有限 mechanism nodes + stochastic reaction channels + treatment inputs，particle filter posterior 为共享 `Z_t`；另做 compositional variant 用 open ports 组合 A/B/comorbidity modules。用 W13 检查是否必须新增 cross-module reactions，用 W18 记录 graph-growth/OOD 而非强行归类。

关键一手来源（每条先写“直接支持”，分号后写“不支持/条件边界”）：

1. **[RXN-01 · VERIFIED-DOI]** D. T. Gillespie, “Exact Stochastic Simulation of Coupled Chemical Reactions” (1977), DOI [10.1021/j100540a008](https://doi.org/10.1021/j100540a008)。在 well-mixed Markov reaction assumptions 下 exact 采样 reaction paths；患者系统不自动满足这些物理假设。
2. **[RXN-02 · VERIFIED-DOI]** G. Craciun & C. Pantea, “Identifiability of chemical reaction networks” (2008), DOI [10.1007/s10910-007-9307-x](https://doi.org/10.1007/s10910-007-9307-x)。构造 rate constants 不唯一、乃至不同 networks 产生相同 dynamics 的情形；不支持从有限 trajectory fit 自动恢复唯一真实机制图，也不意味着每个给定网络都不可识别。
3. **[RXN-03 · VERIFIED-DOI]** J. C. Baez & B. S. Pollard, “A Compositional Framework for Reaction Networks” (2017), DOI [10.1142/S0129055X17500283](https://doi.org/10.1142/S0129055X17500283)，[作者原稿](https://arxiv.org/abs/1704.02051)。open reaction networks 通过 boundaries 组合，并有到 open dynamical systems 的 functor；black-boxing 讨论 steady-state input-output relation，不等于保留全部 transient patient state。
4. **[RXN-04 · VERIFIED-PRIMARY]** D. Vagner, D. I. Spivak & E. Lerman, “Algebras of Open Dynamical Systems on the Operad of Wiring Diagrams” (2015), [作者原稿](https://arxiv.org/abs/1408.1598)。typed wiring diagrams 给一般/线性 ODE open systems 的组合语法；端口可组合不证明内部 state 充分、可识别或医学正确。
5. **[RXN-05 · VERIFIED-DOI]** J. C. Baez, B. Fong & B. S. Pollard, “A Compositional Framework for Markov Processes” (2016), DOI [10.1063/1.4941578](https://doi.org/10.1063/1.4941578)，[作者原稿](https://arxiv.org/abs/1508.06448)。open CTMC 可组合/black-box；其 steady-state boundary behavior 可能丢 transient/内部差异，恰可用于构造“黑箱相同但治疗未来不同”的碰撞测试。

## 3. 从文献直接导出的可证伪实验（不是更多综述）

| 实验假说 | 正式候选映射 | 直接来源 | 最小实现 | 主要世界 | 淘汰条件 |
|---|---|---|---|---|---|
| H-LIN：有限 Hankel rank 的 action-observation process 可由小型 realization 统一 | `F02-SSM`；`F01` 共享 filter 语义 | SSM-02/03/04/05 | Ho–Kalman/N4SID，state 只来自历史 I/O | W01–W03, W08 | rank 随 horizon/新 action 持续增长；干预 rollout 高误差 |
| H-BELIEF：正确 finite latent POMDP 的完整 belief 是 exact shared state | `F02-BELIEF` | POMDP-01/02/03 | exact tabular Bayes filter | W01–W07, W16–W17 | posterior mean ablation 与 full belief 同样好则检查 benchmark；full belief 仍碰撞说明 latent model 过粗/错 |
| H-CPSR：action-indexed core-test predictions 可绕过 latent mechanism identifiability | `F03-PSR` | PSR-01/02/04 | spectral/empirical controlled PSR | W02–W08, W16–W17 | withheld treatment/check 造成旧 state collision，且不能低代价扩展 |
| H-CSTATE：对所有允许 actions 的 future-law equivalence 给最小行为 state | `F04-CAUSAL-STATE` | CSTATE-02/03/05 | controlled suffix tree + distributional merge | W03–W05, W14, W17, W19 | rare harm 被合并；state count 随 horizon 无界增长 |
| H-BISIM：全 action observation/outcome bisimulation 比 reward-only abstraction 更接近 UCM | `F04-BISIM` | BISIM-01/02/03/04 | exact tabular quotient + learned metric | W04, W16–W19 | frozen new readout 无法恢复或 treatment regret 上升 |
| H-DSCM：机制 posterior + surgical interventions 能统一 observational 与 randomized future | `F05-DSCM` | CAUSAL-01/02/04/07 | dynamic SCM particle filter | W12–W15, W20 | W15 把 confounded association 当 do-effect；latent CRL 多 seed 不可对齐且预测不稳定 |
| H-KOOP：受控有限 lift 在低非线性世界给高效 shared state，但在多 attractor/交互世界失效 | `F06-KOOPMAN` | KOOP-02/03/04 | DMDc/EDMD + closure residual | W01, W03, W13, W17 | residual 低却反事实错；或需要随 world/task 专属 dictionary 分支 |
| H-RSSM：单 RSSM 可给强平均近似，但需 red-team 防 task collapse/model exploitation | `F07-RSSM` | WORLD-01/02/03/04 | one RSSM, no per-head RNN | W01–W20 | any head bypasses `Z_t`；W19 tail collision；adversarial planner exploits model |
| H-CPIB：controlled predictive target 可画出 compression—collision Pareto | `H-CPIB-planned`（历史计划，未映射到实际 EXP ID） | IB-01/02/03/04 | action-sequence-conditioned VIB | W03–W05, W14, W16–W19 | 压缩仅保持训练 readout；新 task/check 不从 frozen `Z_t` 可读 |
| H-RXN：局部 mechanism modules 可组合，但 cross-module reactions 决定是否真正闭合 | `F08-RXN` | RXN-01/02/03/04/05 | stochastic reaction network + PF | W10–W13, W18, W20 | 仅端口拼接无法表示 synergy/antagonism；等价 networks 无法区分却输出过度机制确信 |

### 3.1 其余正式候选的文献声明上限

- `F09 symbolic-neural hybrid` 是把 `F01/F05/F08` 的显式状态与 `F07` 的共享 residual 组合起来的**工程假说**。上述来源分别支持局部 dynamics、intervention 或 learned rollout；没有来源证明把它们拼成 tuple 后自动成为语义统一、无重复计数且最小的状态。
- `F10 bounded attention/memory` 保留为运行候选，但本核心证据链不把 QKV、attention 权重或长上下文论文当作状态充分性定理。是否成为 UCM 只由固定容量、增量更新、禁止重读历史、新任务 readout 与碰撞实验判定。
- `F11 typed program-state/rewrite` 保留为运行候选，但“规则可执行/可组合”不推出 predictive sufficiency、因果识别或有限 state。当前文件不借相邻形式系统文献提升其证据等级。
- 因此 `F09`–`F11` 可以参与公平实验，却不能在实验前使用“文献已证明统一地图”作为先验优势。未来若为它们新增来源，必须按本文件同样的支持/不支持格式逐条核验；无法确认的条目必须标 `TODO-unverified`。

## 4. 严格结论上限

1. **最强 existence 候选**是“对所有允许 action/check futures 的行为等价类”；它给语义定义，不给一般有限维、可学习或临床可识别保证。
2. **有限 belief/finite-rank PSR/finite causal-state/finite Koopman lift**都只在各自强条件下存在；不能串联成“总有有限 UCM”的证明。
3. **SCM/reaction network**给 intervention 和机制组合语义，但结构/latent variables 可能不可识别；可解释坐标不是来自数据的自动真值。
4. **world model/IB/bisimulation**容易对训练任务充分、对新检查/治疗/读出不充分；因此 freeze 后 extension 与 new-task probe 是核心，不是附加测试。
5. **DTR 是决策规则，不是患者 state**；**compositional wiring 是组装规则，不是 sufficiency**；**Koopman 是 observable evolution，不是有限维保证**。
6. 若最强候选的 state 数/维度随 horizon、actions、checks 持续增长，或存在任意小压缩都会造成 W19 catastrophic collision 的族，则应报告“仅局部/近似共享状态”或有限 UCM 的最小反例，而不是用完整历史/RNN 隐藏容量掩盖失败。

## 5. 最终 source-to-experiment disposition

文献完成的是“生成互相可证伪的状态假说”，不是用引文替实验回答 UCM。当前机器
账本是 38 total / 30 eligible；以下所有结论都由合成运行裁决，不能升级为原论文或
临床结论。

| Source idea | Implemented evidence | Final interpretation |
|---|---|---|
| Belief / POMDP | F02, F10 | 分布/不确定性是 state 的一部分；当前 open-world belief 在 primary 仍不稳健 |
| Controlled PSR / predictive tests | F03, F17 | action-indexed futures 有用；有限 landmark/kernel compression 可产生 collision |
| Causal states / bisimulation | F04, F11, F13, F18, F21 | controlled quotient 是有效语义核心；point collapse 不安全，minimality 未证明 |
| Dynamic SCM | F05, F15 | 显式 action/mechanism interactions 有局部价值；识别与 unseen composition 不自动成立 |
| Koopman / observable operators | F06, F14, F18 | 改善合成 trajectory prediction；不推出 finite closure 或 OOD safety |
| Neural world state | F07, F15 | 单一 latent 可运行；浅 residual/random encoder 未形成合格前沿 |
| Reaction/mechanism graph | F08 | fixed graph 未形成合格候选；compositional/open-system 文献只支持下一 native-extension 假说的结构动机 |
| Catalog-closed switching particle belief | F22 | action-conditioned particle/switching state修复了 legal-policy totality；EXP-038 v2 仍有 1 collision + 1 unsafe OOD，已 `ABANDON` |
| Program state | F16 | executability/typing 不防止量化丢失 behaviorally relevant distinctions |
| Full history / K0 | B02 / B04 | history 是 information baseline；K0 是 evidence machinery，二者都不是 UCM 答案 |

### 5.1 当前证据如何限制文献外推

1. **Primary full evaluations**：F10/F14/F18 的 unsafe forced-known OOD 为
   5/21/5，全部 hard-fail；没有文献先验可以补偿该失败。
2. **CONFIRM5-lite**：F10/F18 只在 train4/val1/test2/pair0 的 committed lite scope
   通过。它给局部 descriptive Pareto，不证明 belief/causal-state 理论条件在开放世界
   成立。
3. **Strict red-team v2**：closed-catalog OOD/collision 有局部支持；new check 与
   opposite-response treatment 需要 extension fit + visible-history replay；new task
   inconclusive；state nonminimal。这与文献中“允许 experiment set 改变会细分等价类”
   的边界一致，而非对所有 finite states 的不可能性定理。
4. **Full REPRO5**：独立实现与 sealed F18 在 1,680 episodes、28,720 rollout queries、
   260 pairs 上精确一致；reproduction 证明 implementation equivalence，不证明正确性，
   也不修复 primary OOD。
5. **Secondary M09/M10/M11/M13/M16** 明示
   `formal_frozen_metric_claim=false`；尤其 novel-readout 数值排序不是 state
   sufficiency 的正式检验。

### 5.2 最终来源结论上限

没有任何一手来源预测 F18 会成功，也没有任何来源支持把这些 synthetic results 升级
为 clinical/production/global claim。有限 belief、PSR、causal state、bisimulation 与
Koopman invariant subspace 只在各自 finite/rank/closure/observability 假设下成立；
SCM/reaction-network 的机制坐标也可能不可识别。

运行证据只支持：**有限封闭合成目录中的 shared state 有局部价值；当前没有合格
primary winner，open-world UCM 未建立。** Primary eligible Pareto 为空；lite 局部
Pareto 为 F10/F18。任意开放世界 finite UCM 的存在或不存在、新任务充分性、临床有效
性、production safety 和 global optimality 都保持未知。

### 5.3 下一文献驱动实验，不是新引用结论

下一项应将 controlled predictive-state 与 compositional/open-system 思路实现为
**native scope-extension architecture**，使用 fresh preregistration + commit/reveal；
同 pack 比较 sealed F18、F10、true-state、full-history、separate-task。禁止
visible-history replay，预冻结 new check/new treatment/new task thresholds，并强制
pair/OOD/false-split/state-growth gates。只有运行结果可决定 local-growth hypothesis，
不能因 compositional 文献存在就预先把它写成成功。
