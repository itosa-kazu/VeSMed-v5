# 候选家族研究 05：Petri 网、进程代数、反应网络

> 研究日期：2026-07-13  
> 范围：普通/有色/时间/随机/开放 Petri 网；CCS/CSP/ACP/π-calculus 及时间/随机扩展；确定性/随机/开放/规则式反应网络。  
> 判定记号：**H** = 家族原语或已建立的标准变体天然通过；**P** = 需要通用补充层，不能靠该家族核心单独保证；**F** = 核心发生语义碰撞或需要换成另一种架构才自然；**U** = 当前证据不足。  
> 标签：`〔族〕` 表示家族本性；`〔CPN〕`、`〔Timed-CSP〕` 等表示只对该具体变体成立。

## 0. 可复核结论（先给结论，不提前选最终架构）

1. **反应网络与普通 P/T Petri 网不是两个独立的结构骨架。** 二者都是“类型/物种 + 多重集输入输出 + 反应/变迁”；区别主要在语义：Petri 网强调可达性、资源和真并发，反应网络再赋予质量作用 ODE 或 CTMC 速率。Baez–Pollard 明确把 reaction network 与 Petri net 视为同一结构的两种表述。因此若候选总数需要“真正不同”，只能把二者当成**同一重写骨架的两种运行语义**，不能靠改名凑两个候选。
2. **三个家族对并发、资源争用、局部交互和模块组合都有真实优势。** Petri 网最自然地表达资源守恒、并发使能和离散干预；进程代数最自然地表达组件协议、同步/隐藏、行为等价和接口组合；反应网络最自然地表达多机制非线性耦合与随机演化。
3. **三个家族都不能单独充当本项目所需的完整临床固定核心。** 它们均未原生规定：真实状态/观察/陈述/推断/计划/已执行动作的认识论类型；发生/采集/可得/记录/有效/过期等多时钟；证据根 ID、同源去重、删除传播和规则版本；部分可观测下的后验；开放世界拒答；多任务临时坐标。
4. **Petri 网是三者中最接近“执行语义子内核”的候选。** 有色 token 可承载类型和来源，时间网可延迟可见性，展开/事件结构可保留因果偏序，开放网可组合；但这些仍不能自动得到证据守恒和临床推断。若把不可变证据账本、真值维护、概率观察模型和任务读出全部外挂，得到的是混合架构，而不是“Petri 网已经解决”。
5. **进程代数适合作为协议/工作流/干预编排层，不适合作为唯一临床状态本体。** 其行为等价通常故意隐藏内部动作；这与“任何结论必须完整回溯到原始证据”存在结构性张力。
6. **反应网络适合作为机制动力学模块，不适合作为证据和认识论内核。** 浓度/计数会聚合并抹去个体来源；随机轨迹的不确定性也不是“我们不知道患者真实状态”的认识论不确定性。

当前建议是**全部保留到 Pareto 前沿的子系统角色**，但不把任何一个家族直接宣布为全系统赢家：

- Petri/事件结构：候选的离散变迁、资源、安全不变量、并发因果子内核；
- 进程代数：候选的组件协议、干预编排和行为精化层；
- 反应网络：候选的机制非线性和随机动力学层；
- 三者共同缺的证据/时间/推断语义必须由其他候选正面竞争，而不能用“token/action/species 什么都能装”掩盖。

---

## 1. 家族 A：Petri 网

### 1.1 家族边界与正式核心

普通 P/T Petri 网可写为：

\[
N=(P,T,Pre,Post,M_0),\qquad M\in\mathbb N^{P}
\]

- `P`：place；
- `T`：transition；
- `Pre, Post`：输入/输出弧的自然数权重；
- `M`：marking，即每个 place 的 token 多重集计数；
- 当 `M >= Pre(:,t)` 时 `t` 使能，发射后 `M' = M-Pre(:,t)+Post(:,t)`。

Murata 的定义和 firing rule 明确展示了 place、transition、弧权重、初始 marking，以及发射时消耗/产生 token 的语义。其资源解释不是比喻：place 可表示资源，transition 消耗并释放资源。

标准扩展不是一个单一、自动兼容的语义包：

- **Colored Petri Nets (CPN)**：token 携带类型化数据值，弧表达式和 guard 操作数据；
- **Timed Petri Nets / timed CPN**：为 transition/place/token 引入时间；Jensen 的 timed CPN 使用全局模型时钟和 token earliest-use timestamp；
- **Stochastic Petri Nets (SPN/GSPN)**：给发射延迟/速率分布，常导出 CTMC；
- **Occurrence nets / unfoldings**：把一次次变迁发生展开成无环因果事件，暴露因果、并发和冲突；
- **Open Petri nets**：指定输入/输出 place，以 gluing 和 monoidal composition 组合；
- **Workflow nets**：增加 workflow 入口/出口与 soundness 条件。

ISO/IEC 15909-1:2019 规范了 high-level Petri nets 的 syntax/semantics，但“有色 + 多种时间 + 随机 + 证据血缘 + 概率观测”并没有一个被该标准统一锁定的临床语义。

### 1.2 统一模板

| 维度 | Petri 网回答 | 判定 |
|---|---|---|
| 基本原语 | place、transition、arc、marking/token；CPN 再加 color set、表达式、guard | 原语少，执行语义清楚 |
| 状态放在哪里 | 当前 marking；CPN 是各 place 上有色 token 的多重集 | `〔族〕` 天然 |
| 时间 | P/T 核心无时间；timed CPN/TPN 加时钟或 timestamp | `〔变体〕` 可表达单一模型时间；临床多时钟仍需 P |
| 观察 | 可将观测建成 labeled transition 或 observation token；不可观察 transition 可用于诊断 | `〔族〕` 可建模，但观察/真实状态分型不被核心强制，P |
| 干预 | 已发生干预是一次 transition firing；药物库存/通路/设备是资源 token；计划动作可放另一 place | 执行动作天然；“计划≠执行”需类型不变量，P |
| 不确定性 | 基本 firing 是 nondeterminism；SPN 是随机时间/选择；CPN 可承载分布 | 三者都不自动等于 epistemic posterior，P |
| 共病组合 | 并置子网、共享 place、同步 transition；open net 通过接口 gluing | `〔族/open PN〕` 强 |
| 非线性交互 | P/T 更新是线性计量，但多输入使能、竞争资源、反馈产生离散非线性；CPN guard/随机 rate 可更一般 | 强于纯加法；连续生理非线性不如 CRN 自然 |
| 证据血缘 | 普通 token 同质，marking 丢失个体祖先；CPN 可携带 source IDs；unfolding 给事件因果偏序 | 只到“可编码”；同源去重/删除传播仍需 provenance 代数与 TMS，P |
| 局部扩展 | hierarchical/open CPN 允许按 port/socket 或 input/output 组合局部子网 | 接口稳定时 H；共享 place 名和全局 color type 仍会扩大 blast radius |
| 部分可观测 | labeled/unobservable transitions + unfolding 可求与观测一致的运行集合 | `〔具体诊断算法〕` H 于集合估计；概率后验 P |
| 任务读出 | marking query、invariant、reachability、CTL-like query、reward/monitor place | 读出是外部查询，不是唯一万能距离；多任务可行但需 P |
| 天然解决 | 并发、同步、资源互斥、离散 intervention、deadlock/liveness、局部因果、守恒不变量 | 很强 |
| 必须补的通用层 | epistemic ADT、多时钟证据事件、不可变根证据、幂等 lineage、概率观察/过滤、真值维护、任务 projector、开放世界拒答 | 至少 7 个通用补充概念 |
| 最坏失败 | 所有临床事实都被拍成 token；普通 token 合并后来源消失；一个 timestamp 冒充六种时间；扩展弧/guard 破坏可分析性；状态空间爆炸 | 核心风险高 |

### 1.3 证据血缘：能保存“因果”不等于已经满足“证据守恒”

Petri unfolding/事件结构可记录 `e1 < e2`（事件因果依赖），这比纯序列好；Benveniste 等还展示了在无全局时间、传感器只有局部视图时，用 net unfolding 做异步诊断。但临床证据守恒还要求：

```text
原始温度记录 source=e1
  -> 温度升高
  -> 发热
  -> 高热
```

三个下游事实必须共享根集合 `{e1}`，不能在评分时变三票。普通 marking 只留下 token 数，无法知道 token 来自哪次发生；CPN 即使给 token 增加 `roots: Set[EvidenceId]`，也还要规定：

- 合并用集合并集而不是计数相加；
- 同一根证据在同一读出中幂等；
- 每个派生 token 保存规则版本与完整 parent edges；
- 删除 `e1` 时依赖它的所有派生 token 失效；
- 重新解释要从不可变原始事件重放，而不是逆 firing 猜历史。

因此 `CPN + source set` 是**可行编码**，不是 Petri 网家族的现成保证。若不明确这一点，Petri 网会在测试 6/24/27 静默通过演示但语义失败。

### 1.4 计算与验证边界

- CPN 文献明确承认 state-space explosion；复杂系统可能无法构造完整状态空间。
- 更强的理论下界更严峻：一般 Petri-net reachability 已知为非 primitive-recursive/Ackermannian 量级。不能把“可达性可判定”误写成“临床规模可运行”。
- unfolding 可减少独立并发事件所有交错造成的爆炸，但有循环、数据色彩和大量个体 evidence 时仍可能很大。
- 复杂 guard、任意宿主语言表达式、inhibitor/reset 等扩展会让不同工具和可判定性结论分裂；原型必须冻结一个小子语言。

### 1.5 最强保留角色与淘汰条件

**保留角色**：离散 event/transition 语义、资源和干预、并发因果、安全不变量。  
**不能单独承担**：完整认识论、连续/混合临床状态估计、证据删除与后验、多任务读出。  
**淘汰为核心候选的证据**：若在统一原型中，为通过时间/血缘/不确定性测试必须把 token color 变成一个完整事件数据库 + 概率程序 + TMS，而 Petri firing 只剩薄壳，则 Petri 网不应被称为核心，只应是某个执行后端。

---

## 2. 家族 B：进程代数

### 2.1 家族边界与正式核心

以 CCS/CSP 风格写一个最小语法：

\[
P ::= 0 \mid a.P \mid P+Q \mid P\parallel Q \mid P\setminus L \mid P[f] \mid X
\]

- `0`：不再行动；
- `a.P`：先发生 action `a`，再成为 `P`；
- `+`：选择/非确定性；
- `||`：并发组合和可能同步；
- restriction/hiding：限制或把内部 action 变成不可观察 `τ`；
- relabel/recursion：接口改名与长期行为。

状态不是一个医学向量，而是**当前 residual process term / labeled transition system 节点**。Hoare 的原始 CSP 把输入、输出和并行组合作为基本结构；Brookes–Hoare–Roscoe 给出 traces/failures/divergences 等数学模型；π-calculus 通过传递 channel names 支持运行时改变连接拓扑。

家族同样存在语义分支：

- CSP/CCS/ACP 的同步、选择、隐藏和等价关系并不完全相同；
- Timed CSP 把时间加入 trace/failure 语义；
- PEPA、stochastic π-calculus 等给 action 加 rate，导出 CTMC；
- 概率 choice、非确定 choice 和 Markov timing 如何组合，需要具体 calculus 明确，不能统称“进程代数天然有概率”。

### 2.2 统一模板

| 维度 | 进程代数回答 | 判定 |
|---|---|---|
| 基本原语 | action、prefix、choice、parallel composition、restriction/hiding、renaming、recursion | 原语紧凑但行为导向 |
| 状态放在哪里 | residual process / LTS node；数据需 data-carrying process 或外部 store | 离散协议状态 H；临床数值状态 P |
| 时间 | 经典 CCS/CSP 无定量时间；Timed CSP 等另加 timed traces/stability | `〔Timed-CSP〕` H；家族统一性 P |
| 观察 | visible action 是观测；hiding 产生 `τ`；weak equivalence 忽略内部动作 | 部分可见行为 H；测量模型/可靠度 P |
| 干预 | action、通信、process replacement；设备/药物可作为协调进程 | 编排 H；生理 effect map P |
| 不确定性 | choice 表示 nondeterminism；PEPA/stochastic π 提供 Markov rate | 行为/随机不确定性 H 于变体；epistemic posterior P |
| 共病组合 | `P_A \|\| P_B`，共享 channel/action 同步；π-calculus 可动态改变连接 | `〔族〕` 强 |
| 非线性交互 | 同步、反馈、竞争和动态 channel 可产生非加性行为 | 离散交互强；数值非线性需额外数据/方程 |
| 证据血缘 | trace 保留 action 序列；但 hiding/weak bisimulation/行为 quotient 故意消除内部差异 | 与完整审计有结构张力，P |
| 局部扩展 | 新 process 通过接口 channel 组合；π 支持移动拓扑 | 接口良好时 H；全局 alphabet/synchronization 改动可扩散 |
| 部分可观测 | `τ`、hiding、testing、failures/refinement 可分析外部可见行为 | 行为可观察性 H；隐状态后验 P |
| 任务读出 | test process、observer、modal/temporal logic、refinement assertion、reward extension | 多任务可外挂，P |
| 天然解决 | 协议、并发组件、同步、deadlock/divergence、安全/活性精化、动态连接 | 很强 |
| 必须补的通用层 | typed clinical store、认识论类型、多时钟、不可变 event/provenance、概率 observation/filter、TMS/replay、task projection | 至少 7 个 |
| 最坏失败 | 把连续生理状态编码成庞大 process state；同步 rendezvous 误代替异步临床消息；隐藏动作抹去审计细节；多种扩展互不统一；并发积造成状态爆炸 | 核心风险高 |

### 2.3 部分可观测与证据审计之间的张力

进程代数非常擅长回答“外部观察者能否区分两个系统”。π-calculus 原始论文以 labeled transition system 和 strong/weak bisimulation 为语义，并明确 weak bisimulation 中 internal actions 不可见；CSP/FDR 的 traces、failures、divergences 则适合验证安全、拒绝和发散。

但临床审计问的是另一件事：**即使两个执行在行为上等价，也可能必须保留不同的来源、测量方法和证据质量。** 若：

```text
P1 = lab_A?e1 -> infer?x -> P
P2 = copied_note?e1 -> infer?x -> P
```

隐藏内部步骤后，两者可能在行为读出上等价；对临床证据独立性却绝不等价。因此：

- 行为等价可用于组件替换；
- provenance equivalence 必须更细，不能直接采用 weak equivalence；
- action 必须携带 evidence ID、event/available time、actor、rule version；
- 仍需不可变日志和派生 DAG，不能只存当前 residual process。

这说明进程代数很适合**控制面**，但不能让行为 quotient 成为事实存储层。

### 2.4 时间、随机性和状态爆炸边界

- Timed CSP 是经典 CSP 的专门扩展，不是原始家族默认语义。
- PEPA 设计目标是在保持组合性的同时生成 continuous-time Markov process；stochastic π-calculus 也直接从 specification 产生 CTMC。二者证明“可扩展到随机”，但不证明“任意临床不确定性已统一”。
- FDR 的官方文档指出，normalisation 在病理例子中可使状态空间指数增大。并发临床模块、数据参数和时间一同加入后，必须面对有限化/抽象，而非只靠等价检查。
- CSP 的同步通信若直接映射到病历系统，会把异步采集/延迟结果/重复消息错误压成 rendezvous；必须显式建 mailbox/buffer process，这会增加原语和状态。

### 2.5 最强保留角色与淘汰条件

**保留角色**：干预与工作流协议、组件接口、并发协调、安全/活性精化、动态连接。  
**不能单独承担**：定量隐状态、证据认识论、来源去重、贝叶斯过滤、真实/观察分离。  
**淘汰为核心候选的证据**：若统一原型需要先实现 typed event store、概率世界模型和 provenance DAG，进程表达式只用来排序几次 action，则它应降级为 orchestration DSL。

---

## 3. 家族 C：反应网络 / 生化网络

### 3.1 家族边界与正式核心

反应网络定义为物种集合 `S`、反应集合 `R`，每个反应有输入/输出复合物：

\[
y_r \longrightarrow y'_r,\qquad y_r,y'_r\in\mathbb N^S.
\]

确定性质量作用语义：

\[
\dot x = \sum_r k_r x^{y_r}(y'_r-y_r).
\]

`x` 是非负浓度；多输入反应产生乘积项，因此非线性交互是原生的。随机语义可写为 random time-change CTMC：

\[
X(t)=X(0)+\sum_r Y_r\!\left(\int_0^t \lambda_r(X(s))ds\right)(y'_r-y_r),
\]

其中 `Y_r` 为独立单位 Poisson processes，`λ_r` 为 reaction propensity。Gillespie 给出 exact stochastic simulation；Anderson–Kurtz 系统化了 CTMC、master equation、随机时间变换及确定性极限。

重要变体：

- **Open reaction networks**：输入/输出 species 作为接口，组合得到 open dynamical systems；
- **Rule-based systems（κ-calculus、BioNetGen/BNGL）**：结构化 molecule/agent + 局部 graph-rewrite rule，不必枚举所有复合体；
- **SBML**：可交换的模型表示，含 species、reaction、rule、event、delay 等，但其规范明确不是 universal quantitative modelling language。

### 3.2 统一模板

| 维度 | 反应网络回答 | 判定 |
|---|---|---|
| 基本原语 | species、complex/multiset、reaction、rate/propensity、state count/concentration | 小而统一 |
| 状态放在哪里 | `x in R^S_{>=0}` 浓度，或 `X in N^S` 分子计数 | 机制状态 H；临床证据状态 F |
| 时间 | ODE 连续时间或 CTMC reaction time；经典反应假定瞬时完成 | 生理时间 H；结果可得/记录/有效时间 F/P |
| 观察 | 通常以 observable/function 读取 species；这不是 measurement process/likelihood | 需 observation model，P |
| 干预 | 改 rate、初值、input/output flow、添加/抑制 reaction；SBML event 可在 trigger 后延迟 assignment | 动力学干预 H；计划/执行与证据语义 P |
| 不确定性 | CTMC 表示系统内在随机性；参数分布可另加 | aleatory H；epistemic state uncertainty/filter P |
| 共病组合 | 共享 species/reactions；开放网接口 gluing；多输入质量作用产生非线性 | `〔族/open CRN〕` 很强 |
| 非线性交互 | `x^y` 乘积、反馈、竞争、催化、守恒结构 | 三家最自然 |
| 证据血缘 | 浓度/计数聚合；同一 species 的来源通常不可区分 | `〔族核心〕` F；粒子/规则式身份追踪也不等于临床 provenance |
| 局部扩展 | 新 reaction/species 不改 solver；open/rule-based 模块提高组合性 | engine blast radius 小；参数和共享 species 的验证 blast radius 可能全局 |
| 部分可观测 | latent ODE/CTMC 可与 observation model/滤波器组合 | 反应核心没有 likelihood/filter，P |
| 任务读出 | state observable、steady-state black box、hazard/reward function | 函数读出可行；任务坐标与证据解释需 P |
| 天然解决 | 守恒、非负性、反馈、多机制非线性、噪声、机制干预、涌现动力学 | 很强 |
| 必须补的通用层 | typed event/evidence ledger、多时钟 observation model、Bayesian inference、provenance/TMS、open-world rejection、task projection、non-Markov memory/delay | 至少 7 个 |
| 最坏失败 | 用 concentration=0 同时表示真实不存在/未测/缺记录；聚合抹去来源；速率参数不可辨识；Markov/瞬时反应假设错；规则展开组合爆炸；拟合相关不等于可审计因果 | 对本项目是硬风险 |

### 3.3 非线性交互和组合性是真优势，但不能外推为认识论正确

反应网络对测试 16“多病共存产生非线性交互”有最直接表示。例如两个机制活动 `A`、`B` 共同触发风险：

\[
A+B\xrightarrow{k}A+B+Shock
\]

质量作用项为 `kAB`，不是简单 `f_A+f_B`。开放反应网络还给出按输入/输出接口组合、并把组合映射为 open dynamical system 的正式框架。

但以下推论不成立：

```text
能生成非线性轨迹
  != 能从部分且延迟的病历观测估计轨迹
  != 能区分未测与阴性
  != 能证明某结论依赖哪些原始记录
  != 能在删除记录后自动撤回推断
```

随机 CRN 的 `X(t)` 是系统真实随机状态模型；患者 posterior `P(X_t, theta, M | observations)` 需要另外的 observation likelihood、prior 与 filtering/smoothing。不能把 Gillespie 路径集合直接叫“诊断不确定性”。

### 3.4 规则式反应网络的真实贡献与边界

κ-calculus/BNGL 把 molecule 视为结构化对象，以局部图重写规则描述相互作用。Danos 等证明规则 refinement 可在调整 rate 时保持 stochastic semantics；BioNetGen 文献说明一个 rule 可代表巨大 reaction class，避免手工枚举近无限状态。

这对“新增局部机制不重写核心”和组合爆炸是强证据，但仍有边界：

- 规则的局部 context 是物理/分子 context，不是证据来源与记录语境；
- pattern matching 的多个实例决定 propensity，不会自动做 clinical evidence dedup；
- network-free simulation 减少显式网络展开，不消除 parameter identifiability 和 posterior inference；
- BioNetGen 的 `observables` 是对 species pattern 浓度的函数读出，不是采样方法、可靠度、采集时间和可见时间模型。

### 3.5 最强保留角色与淘汰条件

**保留角色**：机制动力学、非线性 coupling、随机演化、干预 effect、守恒/稳态分析。  
**不能单独承担**：认识论和证据内核、病历事件时间、血缘、撤回、开放世界。  
**淘汰为核心候选的证据**：如果在统一压力测试中，必须先通过另一套 event/provenance/probabilistic-programming 系统把病历变成 posterior，再把 posterior 的某些维度喂给 CRN，则 CRN 是世界模型模块而非全系统核心。

---

## 4. 30 项统一压力测试

### 4.1 读表规则

- H 只在单元格指明的成熟变体下成立；未指明时是家族本性。
- P 表示可通过**通用且可复用**的补充层，不允许病例专用规则。
- F 表示若只保留该家族的典型状态语义会发生信息碰撞；外挂另一个完整架构后虽能做，但不能再声称本家族独立通过。

| # | 压力测试 | Petri 网 | 进程代数 | 反应网络 |
|---:|---|---|---|---|
| 1 | 正常 BP 但依赖大剂量升压药 | **P**〔CPN〕需分真实循环状态、观测和 pressor firing | **P** 需 typed store/effect map | **P** 可建药物作用，但需独立 observation model |
| 2 | 正常 SpO2 但依赖高流量氧 | **P** 同 #1 | **P** 同 #1 | **P** 同 #1 |
| 3 | 无发热但刚用退热药 | **P** 状态/测量/药物 token 分型 | **P** action protocol 不自动给 observation semantics | **P** 药效 dynamics 可建，采样语义另加 |
| 4 | 无心动过速但 β 阻滞/起搏 | **P** | **P** | **P** |
| 5 | 抗菌药前后导致培养阴性 | **P** 采样 transition 与药物 transition 可排序，但 sensitivity model 另加 | **P** action 顺序 H，检测 likelihood P | **P** 可建 killing；culture observation P |
| 6 | 同一体温衍生三种事实不得三票 | **P**〔CPN+root set〕普通 marking 会丢 lineage | **P** action 必须带 source ID + 幂等读出 | **F**〔population core〕species/浓度聚合不保存证据祖先 |
| 7 | 发热/CRP/WBC 共享炎症来源 | **P** 共享上游 place/transition H，避免证据重复投票 P | **P** 共享 hidden process H，统计相关读出 P | **P** 共享 mechanism reaction H，后验/去重 P |
| 8 | 同表型由两机制产生 | **H** 多 transition 到同 observation place | **H** choice/hidden alternative traces | **H** 多 reaction/pathway 到同 species/observable |
| 9 | 同病异质表现 | **H**〔CPN/SPN〕branching/colors/rates | **H**〔nondet/stochastic variant〕 | **H**〔stochastic/parameterized CRN〕 |
| 10 | 两项记录冲突 | **P** 有色 evidence token 可并存，冲突语义另加 | **P** 并发 action 可保留，truth status 另加 | **F**〔concentration core〕聚合值会覆盖/平均；需外部 evidence ledger |
| 11 | 未提及症状不等于阴性 | **P** 不能让“无 token”同时表示 false/unknown | **P** 无 action/refusal 不等于临床阴性，需 ADT | **F**〔species core〕`0`/缺 species 与未观察天然碰撞 |
| 12 | 采样后数小时结果才可得 | **H**〔timed CPN〕可做 sampled→pending→available；六时钟仍 P | **H**〔Timed-CSP+buffer〕可分 action 时间 | **P** SBML event/delay 可延迟 dynamics，但 epistemic available-time 另加 |
| 13 | 未来最终诊断不得进入过去判断 | **H**〔occurrence log/trace prefix〕按前缀重放 | **H**〔timed trace〕按可见 action 前缀精化 | **P** 轨迹向前因果，但诊断证据日志不是 CRN 核心 |
| 14 | 同肌酐、不同个人基线 | **P** CPN 可带 baseline context，likelihood/readout 另加 | **P** 参数化 process/store | **P** 初值/parameter 可异，但从测量解释 baseline 需 inference |
| 15 | 同患者两任务需不同坐标 | **P** query/reward/projector | **P** observer/test/reward | **P** observable/readout function |
| 16 | 共病非线性交互 | **H** 多输入 transition、共享资源、guard | **H** synchronization/feedback/dynamic channels | **H** mass-action product/feedback 最自然 |
| 17 | 治疗既改状态又改观察方式 | **P** 两条 typed effect path | **P** parallel effect processes + store | **P** state reaction H，observation channel P |
| 18 | 改善可能自然病程或治疗所致 | **P** 分支可保留；因果归因需 SCM/posterior | **P** alternative traces 可留；概率归因另加 | **P** 可跑 counterfactual dynamics；可识别归因/后验另加 |
| 19 | 观察过期 | **H**〔timed CPN〕expiry transition/token timestamp；valid-time 类型仍 P | **H**〔Timed-CSP〕timeout process；临床有效性规则 P | **P** degradation reaction 不等于 evidence expiry；需事件层 |
| 20 | 新病不属于任何模板 | **P** no-enabled/dead marking 不等于安全 OOD；需 reference/reject readout | **P** refusal/deadlock 不等于临床未知；需 OOD policy | **P** poor fit 与参数错/未知机制不可由 dynamics 单独区分 |
| 21 | 新增药物只局部改知识 | **H**〔hierarchical/open PN〕稳定 ports 下加子网 | **H** 新 process/channel module | **H**〔open/rule-based CRN〕加 reactions/rules 不改 solver |
| 22 | 新增检查不改核心 | **H**〔generic colored observation schema〕仅加 color/converter；若改全局 color type 则退为 P | **P** 新 action 容易影响 alphabet/synchronization/specs | **P** 新 observable 不改 solver，但 measurement semantics 在外部 |
| 23 | 新理论重解释旧证据 | **P** 保留原始 event 后换 transitions/rules 重放 | **P** 换 process spec 后重放 action log | **F**〔state trajectory core〕没有原始证据 DAG；需外部事件溯源 |
| 24 | 删除原证据，依赖推断自动失效 | **P**〔CPN lineage + TMS〕普通逆 firing 不够 | **P** source-tagged action log + 从头重放/TMS | **F**〔aggregate core〕浓度轨迹无 evidence dependency graph |
| 25 | 历史回放只用当时可知信息 | **H**〔timed occurrence/event log〕 | **H**〔timed visible trace prefix〕 | **F**〔plain ODE/CTMC〕模型时间轨迹不等于 knowledge-time replay |
| 26 | 关键安全规则不能依赖检索想起 | **H** invariant/guard/forbidden marking，可模型检查 | **H** refinement/assertion/deadlock property | **P** 物理 invariant 可做；临床 deontic hard rule 需 hybrid guard |
| 27 | 独立来源与同源改写须区分 | **P**〔colored roots/unfolding〕 | **P** action/source identity + provenance readout | **F**〔aggregate core〕来源混入同一 species 后不可恢复 |
| 28 | 多个解释并存，不强制单分类 | **H** reachable markings/unfolding branches | **H** nondeterministic/hidden alternatives | **H** stochastic trajectories/competing mechanisms；posterior 权重 P |
| 29 | 无法表达时显式报错 | **P** typed color/schema validator；deadlock 本身不是语义错误 | **P** total parser/type checker + explicit error process | **P** schema validator；未建 reaction 可能静默缺项 |
| 30 | 自然语言改写不应改核心状态 | **P** 输入 normalization/ontology 在 C 层 | **P** 同左 | **P** 同左 |

### 4.2 按失败簇汇总

不要把表格压成单一总分；但硬失败簇很清楚：

1. **并发/资源/组合簇（8/9/16/21/28）**：三家都强；反应网络的数值非线性最自然，Petri 的资源守恒和真并发最自然，进程代数的接口协议最自然。
2. **认识论/证据簇（1–7、10–11、17、23–24、27）**：三家均需第二层；反应网络的 aggregate state 在 6/10/11/23/24/27 是结构性硬失败。
3. **时间/回放簇（12/13/19/25）**：timed Petri/CSP 能表达事件推进和前缀，但临床多时钟仍需 typed event；纯 CRN 的物理时间不能替代 knowledge time。
4. **推断/任务/OOD 簇（14/15/18/20）**：三家都没有现成 posterior + open-world + task-coordinate semantics。
5. **安全形式验证簇（26/29）**：Petri 与进程代数具有成熟 invariant/refinement 工具；但“未建模必须报错”仍依赖 schema/type completeness contract。

---

## 5. 建议的最小判别原型（不把补丁藏在模型里）

### 5.1 统一接口

后续若三者进入 prototype 比较，必须使用同一接口并报告每个补充层：

```python
class ArchitectureCandidate:
    def ingest(self, event): ...          # 带 source_id 与六类时间
    def advance(self, to_time): ...
    def retract(self, source_id): ...
    def replay(self, knowledge_time): ...
    def project(self, task): ...
    def explain(self, output_id): ...
    def extend(self, module): ...
```

禁止在适配器里悄悄实现完整事件溯源/概率图，再把结果算作 Petri、CSP 或 CRN 的天然能力。每个候选的报告必须拆成：

```text
native kernel LOC
generic adapter LOC
provenance/TMS LOC
observation/inference LOC
task readout LOC
candidate-specific exceptions
```

### 5.2 五个最小有区分力实验

1. **IV line resource**：两种治疗竞争一条静脉通路。Petri 用一个 resource token；CSP 用 `IVLine` 协调进程；CRN 若用“静脉线浓度”会暴露物理量语义不自然。
2. **shared-root fever**：一条温度源派生三条事实，输出必须只计一个根；删除根后全部失效。最能检验 token/action/species 是否真的保存 lineage。
3. **sample vs available**：08:00 采样、12:00 出结果、14:00 记录；在 10:00 replay 不得看见结果。最能区分 model time 与 knowledge time。
4. **two hidden mechanisms**：两个机制产生相同发热；只观测发热时必须保留两个解释。随后给独立化验再更新权重。Petri/CSP 可给集合但权重层暴露；CRN 必须接 observation likelihood/filter。
5. **diagnosis vs safety projection**：同一底层事件，诊断读出强调机制解释，安全读出强调禁忌和资源。检查是否只是改 query，还是复制/污染底层状态。

### 5.3 预期原语/补丁审计（不是总评分）

| 家族 | 最小本家族原语 | 为本项目预计必须新增的通用语义 |
|---|---:|---|
| P/T Petri | 4–5（place/transition/arc/marking/firing） | typed evidence、multi-time、lineage/TMS、observation/filter、task/OOD；若全加约 6–7 类 |
| 进程代数 | 6–8（action/prefix/choice/parallel/hide/rename/recursion/LTS） | typed store、multi-time、provenance log、probability/filter、TMS、task/OOD；约 6–7 类 |
| 反应网络 | 5（species/complex/reaction/rate/state） | event/evidence、multi-time、observation/filter、provenance/TMS、task/OOD、memory/delay；约 7 类 |

这张表的用途是暴露“万能表达”的代价，不是用主观权重选冠军。

---

## 6. 经核实的第一手/规范来源

以下来源的官方、作者或出版记录与链接于 2026-07-13 逐项核对；付费 DOI 以出版元数据与作者副本交叉核实。括号内只写该来源直接支持的结论，不把推论冒充原文。

### 6.1 Petri 网

1. Carl Adam Petri, *Kommunikation mit Automaten* (1962 dissertation), [University of Hamburg bibliography record](https://www2.informatik.uni-hamburg.de/TGI/publikationen/public/1962/Petri62/Petri62_eng.html).（历史原始来源；本笔记的现代形式定义不依赖其摘要。）
2. Tadao Murata, “Petri Nets: Properties, Analysis and Applications,” *Proceedings of the IEEE* 77(4), 1989, [author-hosted/teaching mirror PDF](https://docenti.ing.unipi.it/~a009435/issw/extra/murata.pdf), [DOI](https://doi.org/10.1109/5.24143).（权威综述；P/T 五元组、使能/发射、并发、资源、invariant、高层/随机网。）
3. ISO/IEC 15909-1:2019, [official standard page](https://www.iso.org/standard/67235.html).（high-level Petri net syntax/semantics 的正式标准范围。）
4. Kurt Jensen, “An Introduction to the Practical Use of Coloured Petri Nets,” [Aarhus author PDF](https://cs.au.dk/fileadmin/site_files/cs/research_areas/centers_and_projects/cpn/An_Introduction_to_the_Practical_Use_of.pdf).（token data value、timed token timestamp、hierarchy、state-space query 与 state explosion。）
5. C. Ramchandani, *Analysis of Asynchronous Concurrent Systems by Timed Petri Nets* (MIT Project MAC TR-120, 1974), [Petri-net bibliography record](https://www2.informatik.uni-hamburg.de/TGI/pnbib/r/ramchandani_c1.html).（timed Petri net 原始论文记录。）
6. M. K. Molloy, “Performance Analysis Using Stochastic Petri Nets,” *IEEE Transactions on Computers* C-31(9), 1982, [DOI](https://doi.org/10.1109/TC.1982.1676110).（stochastic Petri-net 早期原始来源。）
7. John C. Baez and Jade Master, “Open Petri Nets,” *Mathematical Structures in Computer Science* 30(3), 2020, [publisher open-access page](https://www.cambridge.org/core/journals/mathematical-structures-in-computer-science/article/open-petri-nets/4D1BC7F05BE8CB0C83C65F7CDF70AF2F), [DOI](https://doi.org/10.1017/S0960129520000043).（input/output place、gluing、symmetric monoidal composition、operational/reachability semantics。）
8. Glynn Winskel, “Event Structures” (UCAM-CL-TR-95), [Cambridge official record and PDF](https://www.cl.cam.ac.uk/techreports/UCAM-CL-TR-95.html).（事件发生、因果依赖、与 Petri/CCS/CSP 的关系。）
9. Albert Benveniste, Eric Fabre, Stefan Haar, Claude Jard, “Diagnosis of Asynchronous Discrete Event Systems: A Net Unfolding Approach,” *IEEE TAC* 48(5), 2003, [author PDF](https://pagesperso.ls2n.fr/~jard-c/Publis/Jard_RI20.pdf), [DOI](https://doi.org/10.1109/TAC.2003.811249).（局部传感器、无全局时间、异步报告、unfolding 诊断。）
10. Jérôme Leroux, “The Reachability Problem for Petri Nets is Not Primitive Recursive,” [arXiv](https://arxiv.org/abs/2104.12695).（Ackermannian/non-primitive-recursive reachability 下界。）
11. W. M. P. van der Aalst, “The Application of Petri Nets to Workflow Management,” *Journal of Circuits, Systems and Computers* 8(1), 1998, [author PDF](https://vdaalst.com/publications/p53.pdf), [DOI](https://doi.org/10.1142/S0218126698000043).（workflow-net 建模、soundness/verification 与 workflow 工具。）

### 6.2 进程代数

12. C. A. R. Hoare, “Communicating Sequential Processes,” *CACM* 21(8), 1978, [DOI](https://doi.org/10.1145/359576.359585), [Oxford record](https://www.cs.ox.ac.uk/publications/publication8253-abstract.html).（输入/输出作为 primitive、并行组合作为结构方法。）
13. S. D. Brookes, C. A. R. Hoare, A. W. Roscoe, “A Theory of Communicating Sequential Processes,” *JACM* 31(3), 1984, [author PDF](https://www.cs.ox.ac.uk/people/bill.roscoe/publications/4.pdf), [DOI](https://doi.org/10.1145/828.833).（CSP 数学模型、nondeterminism、traces/failures 基础。）
14. J. A. Bergstra, J. W. Klop, “Process Algebra for Synchronous Communication,” *Information and Control* 60, 1984, [Utrecht repository](https://dbc.library.uu.nl/handle/1874/13707).（merge、communication、mutual exclusion、synchronous cooperation 的代数规范。）
15. Robin Milner, Joachim Parrow, David Walker, “A Calculus of Mobile Processes, I,” *Information and Computation* 100(1), 1992, [publisher-version PDF](https://www.pure.ed.ac.uk/ws/files/16426053/A_Calculus_of_Mobile_Processes_I.pdf), [DOI](https://doi.org/10.1016/0890-5401%2892%2990008-4).（通信 names、动态 linkage、LTS、strong/weak bisimulation、内部不可观察 action。）
16. G. M. Reed, A. W. Roscoe, “A Timed Model for Communicating Sequential Processes,” *TCS* 58, 1988, [author PDF](https://www.cs.ox.ac.uk/people/bill.roscoe/publications/17.pdf), [DOI](https://doi.org/10.1016/0304-3975%2888%2990030-8).（Timed CSP 的专门模型。）
17. Jane Hillston, *A Compositional Approach to Performance Modelling* / PEPA, 1996, [Cambridge chapter](https://www.cambridge.org/core/books/abs/compositional-approach-to-performance-modelling/performance-evaluation-process-algebra/5B5199AC5C4480C5951384A6B7FCA892), [author bibliography/full-text links](https://www.dcs.ed.ac.uk/pepa/papers/).（组合式 process algebra 到 continuous-time Markov process。）
18. Corrado Priami, “Stochastic π-Calculus,” *The Computer Journal* 38(7), 1995, [publisher page](https://academic.oup.com/comjnl/article/38/7/578/400773), [DOI](https://doi.org/10.1093/comjnl/38.7.578).（从 stochastic π specification 直接导出 CTMC。）
19. FDR documentation, [official CSP refinement manual](https://www.cs.ox.ac.uk/projects/concurrency-tools/fdr-2.94-html-manual/fdr2manual_5.html), [current FDR docs](https://cocotec.io/fdr/manual/index.html).（traces/failures/divergences/refinement；normalisation 最坏指数放大。）

### 6.3 反应网络 / 规则式生化网络

20. F. Horn, R. Jackson, “General Mass Action Kinetics,” *Archive for Rational Mechanics and Analysis* 47, 1972, [DOI](https://doi.org/10.1007/BF00251225).（general mass-action kinetics 的原始理论来源。）
21. Daniel T. Gillespie, “Exact Stochastic Simulation of Coupled Chemical Reactions,” *J. Phys. Chem.* 81(25), 1977, [publisher DOI page](https://pubs.acs.org/doi/10.1021/j100540a008), [full-text teaching mirror](https://www.cl.cam.ac.uk/teaching/2425/Bioinfo/papers/DanielGillespie1.pdf).（确定性 reaction-rate 与随机 master-equation 两种语义；exact SSA。）
22. David F. Anderson, Thomas G. Kurtz, “Continuous Time Markov Chain Models for Chemical Reaction Networks,” 2011, [author PDF](https://people.math.wisc.edu/~dfanderson/papers/SURVEY_AndKurtz.pdf).（species counts 为 CTMC state、reaction intensity、random time-change、ODE/diffusion limits、delay 边界。）
23. John C. Baez, Blake S. Pollard, “A Compositional Framework for Reaction Networks,” *Reviews in Mathematical Physics* 29, 2017, [author PDF](https://math.ucr.edu/home/baez/RxNet.pdf), [DOI](https://doi.org/10.1142/S0129055X17500283).（reaction network 与 Petri net 的结构同一性、质量作用非线性 rate equation、开放网与组合 functor。）
24. Vincent Danos, Cosimo Laneve, “Formal Molecular Biology,” *TCS* 325(1), 2004, [Edinburgh official record](https://www.research.ed.ac.uk/en/publications/formal-molecular-biology/), [DOI](https://doi.org/10.1016/j.tcs.2004.03.065).（κ-calculus、domain-level interaction、shared-name bonds、causality/self-assembly、到 π-calculus 的编码。）
25. Vincent Danos et al., “Rule-Based Modelling, Symmetries, Refinements,” FMSB 2008, [author PDF](https://fontana.hms.harvard.edu/sites/fontana.hms.harvard.edu/files/documents/FMSB_08.pdf), [author record](https://www.di.ens.fr/~feret/publications/fmsb2008.shtml).（partial-complex rules、combinatorial compression、保持 stochastic semantics 的 refinement。）
26. James R. Faeder, Michael L. Blinov, William S. Hlavacek, “Rule-Based Modeling of Biochemical Systems with BioNetGen,” *Methods in Molecular Biology* 500, 2009, [author/tool PDF](https://vcell.org/bionetgen/downloads/BioNetGen-book.pdf), [PubMed](https://pubmed.ncbi.nlm.nih.gov/19399430/).（structured molecules、graph-rewrite rules、reaction-class expansion、ODE/SSA analysis、组合爆炸。）
27. Michael Hucka et al., *SBML Level 3 Version 2 Core Release 2*, 2019, [official specification PDF](https://sbml.org/specifications/sbml-level-3/version-2/core/release-2/sbml-level-3-version-2-release-2-core.pdf), [official index](https://sbml.org/documents/specifications/level-3/version-2/core/).（species/reaction/rule/event/delay 的交换格式；明确非 universal language；history annotation 只记录 encoding history，不覆盖 underlying conceptual-model provenance。）

---

## 7. 当前证据缺口与下一判别步骤

### 7.1 证据缺口

- 尚未用同一份机器测试实现三个 minimal interpreters；因此 H/P/F 是形式语义审查，不是 runtime benchmark。
- 未比较具体工具的增量更新性能，例如 CPN Tools、FDR、BioNetGen/NFsim；工具性能不能反推家族语义正确性。
- stochastic Petri net / stochastic process algebra / stochastic CRN 在某些受限模型间可互译；尚未测量翻译后 provenance、state count 和 readout 是否保持。
- “部分可观测”文献多来自故障诊断，不等于临床 Bayesian state estimation；不能把 diagnosability 结果外推为诊断准确性证据。

### 7.2 最有价值的下一实验

实现第 5.2 节五个微型实验，严格统计：

1. native primitive count；
2. generic adapter LOC；
3. special-case count；
4. source-root trace completeness；
5. replay correctness；
6. 删除源证据后的 invalidation completeness；
7. 两个任务 readout 是否共享同一底层事实而不复制；
8. 新增药物/检查的 core-file blast radius；
9. 状态数/运行时间随并发模块数增长曲线。

若 Petri 网在不引入完整外部 TMS 的情况下能通过 6/24/27，并保持历史 replay 和概率部分观测，则其核心地位增强；若做不到，它应明确降级为 transition/event 执行语义。若反应网络可在不破坏模块性和可辨识性的情况下接入统一 observation/provenance 接口，则其机制层地位增强，但这仍不自动使其成为证据核心。
