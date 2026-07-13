# 候选架构跨家族综合：去重分类、统一合同与当前 Pareto 状态

> **范围**：本文件综合 `research_notes/02_state_models.md` 至 `research_notes/08_graph_world.md` 的候选研究。它只做候选边界澄清、统一模板比较和原型优先级登记，**不选择最终赢家，也不修改 `CANDIDATES.md`**。`08_graph_world.md` 已于本文件定稿前落盘，并已按其实际内容核对图、world model、digital twin 与 Transformer 的边界。

## 0. 结论边界与状态口径

### 0.1 本文比较的是“语义承诺”，不是产品名或实现名

候选只有在它改变了以下至少一项时才单列：

1. 什么是持久状态或世界状态；
2. 什么操作构成状态演化；
3. 观察、行动、推断和反事实分别是什么对象；
4. 不确定性或多世界如何解释；
5. 模块组合和扩展的合法性由什么规则决定。

反之，仅更换 solver、神经网络 backbone、存储引擎或语法外壳，不算新家族。家族可以相交或构成严格扩展；本文会明确这种关系，避免把同一骨架换名后虚增候选数。

### 0.2 三类状态标记

| 标记 | 含义 | 不含义 |
|---|---|---|
| **H-CORE** | 在当前硬要求下，**作为唯一固定临床核心**已经硬淘汰；缺口不是调参可修 | 不等于其数学工具或实现完全无用 |
| **R-COMP** | 保留为分层架构中的明确组件、语义合同或执行后端 | 不等于已证明可承担完整核心 |
| **P-PROT** | 在至少一个硬维度上目前不被其他候选支配，值得进入统一原型/Pareto 实测 | 不等于领先、胜出或可绕过其他硬门 |

一个候选可以同时是 `H-CORE + R-COMP`，也可以是 `H-CORE + P-PROT`：前者说明整核被淘汰但组件保留；后者说明其**窄角色**进入 Pareto 原型，而非宣布它单独满足全部要求。本文没有 `WINNER` 状态。

### 0.3 去重决定

1. **SSM 与 POMDP 分开**：前者的核心是隐藏状态—转移—观察—过滤，后者再增加行动、效用/约束和策略；诊断估计与序贯决策是不同语义承诺。
2. **DBN/因子图与 SSM 不互相冒充**：前者首先是随机变量依赖的局部分解；后者首先是一个状态过程及 observation contract。某一具体模型可以同时属于二者，但两种架构主张的天然优势与失败面不同。
3. **普通 PPL、SCM、causal PPL 分开**：`sample/observe`、结构机制替换、以及可执行多世界程序不是同一个操作。
4. **Event Calculus 与 Situation Calculus 不重复计数**：两者归为“符号事件/动作演算”一个家族，作为异步事件中心与动作历史中心的替代语义。LTL/MTL/TLA 只记为验证元层。
5. **Petri 网与反应网络只计一个骨架**：二者共享“多重集状态 + 局部消耗/产生变迁 + stoichiometric incidence”内核；离散 token、ODE 浓度和 CTMC propensity 是同一骨架的语义实现，不拆成两个候选。
6. **类型/ADT/refinement/effect 不计动态候选**：它们约束什么状态和动作可表示，却不定义患者如何随时间演化。
7. **裸范畴、裸 operad、裸 sheaf 不计动态候选**：只有组件本身带 private state/update/readout 的开放机器系统才列为 C17；若 sheaf 的 section 本身是时间/上下文行为，则以 C20“temporal behavioral sheaf”另行审计，不能靠 sheaf 术语偷领动态生成能力。
8. **Transformer/RNN/GRU 不单列**：它们是 transition、encoder、readout 或调度器实现。World Models/PlaNet/Dreamer 的稳定骨架归入 learned SSM/POMDP 变体，而不是按模型名重复计数。
9. **digital twin 不凭名称单列**：它是实体—数字表示同步、模型集成和生命周期治理模式；除非声明具体状态、更新、观察和干预语义，否则不是独立动态演算。

### 0.4 每个候选的统一字段

下文每个候选都回答同一组问题：`原语 / 状态 / 时间 / 观察 / 干预 / 不确定性 / 共病 / 血缘 / 扩展 / 任务坐标 / 天然优势 / 必补 / 最坏失败`。其中：

- **状态**必须区分患者真实状态、系统知识态和持久记录；
- **时间**必须说明过程时间是否等同于发生、采集、可见、记录、有效、过期时间；
- **血缘**必须说明能否追到独立原始证据并支持撤回，不能把模型因果边或计算 trace 冒充 evidence provenance；
- **任务坐标**指诊断、严重度、预后、治疗、反事实、安全、审计等 readout 如何从同一核心派生，不是假设存在一个万能相似度。

---

## 1. 候选全景与非重复性理由

| ID | 真正不同的家族 | 与最近邻候选的决定性差别 | 当前状态摘要 |
|---|---|---|---|
| C01 | 向量/张量快照表示 | 数组坐标本身是状态容器；没有转移、观察或因果语义 | `H-CORE + R-COMP` |
| C02 | DBN / 因子化时序图模型 | 以局部概率因子和图分解为核心 | `H-CORE + P-PROT` |
| C03 | 隐状态空间模型 / filtering dynamics | 以隐藏过程、转移核、观察核和 belief update 为核心 | `H-CORE + P-PROT` |
| C04 | POMDP / 受控 belief 决策 | 在 C03 上增加行动、效用/约束、策略与信息价值 | `H-CORE + P-PROT` |
| C05 | 结构因果模型（SCM） | 结构方程和机制替换定义 `do` 与同一单位反事实 | `H-CORE + P-PROT` |
| C06 | 通用概率程序（PPL） | 随机程序 trace + conditioning；无默认 causal operator | `H-CORE + R-COMP` |
| C07 | 因果概率程序（causal PPL） | 把 intervention、多世界共享和 AAP 做成可执行程序变换 | `H-CORE + P-PROT` |
| C08 | 开放宇宙关系概率/因果程序 | 对象数、身份及按需实例化本身可不确定 | `H-CORE + R-COMP` |
| C09 | 符号事件/动作演算 | 事件或已执行动作经惯性/后继公理改变 fluent | `H-CORE + R-COMP` |
| C10 | Temporal Evidence Ledger（TEL） | 不可变版本事件、多时间、血缘、撤回和 as-of projection 是核心 | `H-CORE + P-PROT` |
| C11 | 多重集变迁系统（Petri–reaction 骨架） | 资源/物种多重集经局部消耗—产生规则演化 | `H-CORE + P-PROT` |
| C12 | 进程代数 / 并发协议演算 | residual process、同步、隐藏和行为等价定义状态与组合 | `H-CORE + R-COMP` |
| C13 | 类型化重写逻辑 | 一般项代数、等式理论、带条件重写和搜索/策略 | `H-CORE + P-PROT` |
| C14 | 类型化时态逻辑编程 + provenance/TMS | EDB/IDB、规则最小不动点、声明式 query 和推导血缘 | `H-CORE + P-PROT` |
| C15 | ECS 运行时组织 | entity-component 数据布局与 system 批处理，而非临床世界语义 | `H-CORE + R-COMP` |
| C16 | 黑板/共享工作区架构 | 异构 knowledge source 由 controller 机会式协作 | `H-CORE + R-COMP` |
| C17 | 类型化开放组合动态系统 | 带状态行为的开放机器按 port/wiring/cospan 组合 | `H-CORE + P-PROT` |
| C18 | 普通 RDF/OWL 知识图谱 | 以 subject–predicate–object 与本体蕴含组织陈述 | `H-CORE + R-COMP` |
| C19 | 类型化双时间事件超图 | 以事实发生实例、n 元角色、版本、多时间和 lineage 边组织共享事实 | `H-CORE + P-PROT` |
| C20 | Temporal sheaf / behavioral consistency system | 以局部时间/上下文 behavior sections、restriction 与 gluing 判定全局一致性 | `H-CORE + R-COMP` |

上述 20 项是**被审计的架构主张**，不是 20 个都具备患者动态核心资格：C01、C15、C16、C18 是明确的表示/运行/协作对照，C19 是事实语义底座。去掉这些对照后，仍有至少 12 个具有不同状态或演化/查询语义的候选；因此数量不依赖把类型元层、Petri/CRN 同骨架或神经网络实现名重复计数。

---

## 2. 统一模板逐候选登记

### C01. 向量/张量快照表示

**证据基线**：`research_notes/02_state_models.md` §§1, 4–6, 8。  
**状态**：`H-CORE + R-COMP`；硬淘汰为唯一语义核心，保留为计算视图、缓存、模型输入和任务投影。

| 字段 | 统一回答 |
|---|---|
| 原语 | 数值坐标、shape/mode、mask、embedding、距离或 task head。 |
| 状态 | 一个向量或张量切片；若另设 latent vector，其生成与解释语义来自外部模型。 |
| 时间 | 时间桶、额外 mode、窗口或位置编码；不自带异步事件、多时间或有效期。 |
| 观察 | 写入坐标；缺失靠 mask/特殊值/插补，若无强类型会把 `0/阴性/未测/不适用` 碰撞。 |
| 干预 | 额外通道或特征；一旦规定 `F(x,a)` 已借入状态空间/因果模型。 |
| 不确定性 | 点向量不自带；可另附方差、distribution head、ensemble，但冲突与模型外仍无语义。 |
| 共病 | 拼接、相加、乘积或任意网络；没有天然正确组合律，非线性交互容易成为黑箱。 |
| 血缘 | 不原生保存；池化/embedding 常不可逆，同源派生易被重复计票。 |
| 扩展 | 新增坐标看似局部，却可能改变 shape、权重、相似度和全部 task heads。 |
| 任务坐标 | 投影、切片、metric learning 和多 head 极其便宜，是本家族最强点。 |
| 天然优势 | GPU/线性代数生态、批量计算、稀疏存储、已定 schema/任务的工程效率。 |
| 必补 | 类型化事件、观测/状态/行动分离、多时间、provenance、转移/观察模型、因果、OOD、硬约束。 |
| 最坏失败 | 语义碰撞后仍输出高置信数值：治疗支持下的正常与真实正常同点，未提及变 0，派生同义项变多票，删除源证据无法撤回。 |

### C02. DBN / 因子化时序图模型

**证据基线**：`research_notes/02_state_models.md` §§2, 4–6, 8。  
**状态**：`H-CORE + P-PROT`；作为完整临床核心硬失败，但在结构化概率推断、多解释与局部因子化维度进入原型 Pareto。

| 字段 | 统一回答 |
|---|---|
| 原语 | 有域随机变量、条件概率核/局部因子、图边、证据赋值、时间片模板；影响图另加 decision/utility。 |
| 状态 | 某时间片隐藏变量的联合赋值；系统知识态是 posterior，而非患者真值。 |
| 时间 | 2-slice DBN 的离散重复模板；CTBN 可连续时间跳变，但均不自动给知识可见/记录时间。 |
| 观察 | 观测节点或 evidence factor；未观察时不施 likelihood，informative missingness 必须另建。 |
| 干预 | 普通 DBN 只有条件分布；`do`、反事实和策略要借因果 DBN/SCM/影响图。 |
| 不确定性 | 联合分布、边缘 posterior、MAP、多峰解释原生；冲突、模型错配、aleatory/epistemic 区分仍需结构。 |
| 共病 | 共享潜因、交互因子和跨时耦合可局部写；treewidth 与变量基数可能爆炸。 |
| 血缘 | 模型依赖图不是事实血缘；每个 evidence factor 仍需不可变源 ID、规则版本和派生 DAG。 |
| 扩展 | 加变量/因子可局部，但域扩张、归一化、junction tree 和近似器可能全局重建。 |
| 任务坐标 | posterior marginal、conditional、MAP、expected utility 等 query；不需要统一距离。 |
| 天然优势 | 共享原因避免朴素重复投票；多种疾病解释可并存；局部分解支持消息传递。 |
| 必补 | causal action semantics、多时间事件、provenance/撤回、open-world/model discrepancy、数值推断状态、硬安全。 |
| 最坏失败 | 图结构错却 posterior 极自信：遗漏共同原因、同源 evidence 乘法、将治疗选择混杂当药效，loopy 近似仍给伪精确概率。 |

### C03. 隐状态空间模型 / filtering dynamics

**证据基线**：`research_notes/02_state_models.md` §3；learned world-model 边界由 `research_notes/08_graph_world.md` §2 交叉核对。  
**状态**：`H-CORE + P-PROT`；患者动态与 observation separation 的 Pareto 原型，不能兼任事实账本、因果识别和安全内核。

| 字段 | 统一回答 |
|---|---|
| 原语 | latent state、initial belief、transition/dynamics、observation、observation kernel、filter/smoother；可为 ODE/SDE/jump/hybrid/RSSM。 |
| 状态 | 患者假定存在一条隐藏过程；belief/particles 是系统对其不确定性，二者原生分离。 |
| 时间 | 离散步或连续/混合过程时间；结果何时采集、发布、记录和过期仍需事件层。 |
| 观察 | 隐状态经带噪且可依赖设备/支持治疗的 observation model 产生；正常读数不等于内部正常。 |
| 干预 | 受控 SSM 令 action 改变 transition，也可改变 observation channel；观察数据学到的 action effect 并不自动因果。 |
| 不确定性 | process noise、measurement noise、belief、参数 posterior；单模型随机 latent 不等于校准的 epistemic/OOD。 |
| 共病 | factorized state、多个 mode、耦合 drift/transition；能表达非加性交互，但无标准模块组合律。 |
| 血缘 | filter belief 可是决策充分统计量，但不是审计充分统计量；任意旧证据撤回通常要 checkpoint 重放。 |
| 扩展 | 新检查增 observation channel，新药增 control/effect，新病增 mode；固定 state schema 容易全局变形。 |
| 任务坐标 | filtering、smoothing、forecast、hazard/readout 和多任务 heads 从同一 belief 派生。 |
| 天然优势 | 观察—真实状态分离、旧证据随动力学自然衰减、多峰估计、连续预测。 |
| 必补 | 不可变多时间事件账本、causal identification、provenance、open-set/null/model discrepancy、组合接口、硬安全。 |
| 最坏失败 | Markov state 漏史、observation kernel 把治疗掩蔽当改善、混杂 action effect 进入闭环；模型错误被控制和未来数据分布放大。 |

**去重注记**：World Models/PlaNet/Dreamer 的稳定架构原语是 `belief update + action-conditioned latent transition + observation/outcome heads + rollout`，属于本候选（若加策略/效用则跨入 C04）；VAE、MDN-RNN、GRU、categorical latent 或 Transformer 只是实现选择，不另计家族。

### C04. POMDP / 受控 belief 序贯决策

**证据基线**：`research_notes/02_state_models.md` §3；world-model planning 的补充证据见 `research_notes/08_graph_world.md` §2。  
**状态**：`H-CORE + P-PROT`；在“检查与治疗交错、信息价值、受约束决策”上进入 Pareto，不能把 reward 或 learned transition 冒充因果与安全证明。

| 字段 | 统一回答 |
|---|---|
| 原语 | C03 的 state/transition/observation/belief，加 action、objective/reward/cost、policy；安全版本另加 constraints/shield。 |
| 状态 | policy 消费 belief state；真实患者状态仍是隐藏变量，不是 belief 点估计。 |
| 时间 | 通常离散 decision epochs；continuous-time/semi-Markov 可扩展，多知识时钟仍缺。 |
| 观察 | action 后获得 observation 并更新 belief；可显式建检查的灵敏度、代价和延迟。 |
| 干预 | 检查动作与治疗动作都是 decision，但必须分 planned/authorized/performed，且 effect kernel 需因果可用。 |
| 不确定性 | belief 和随机转移/观察原生；model uncertainty、distribution shift、不可识别效应需另列。 |
| 共病 | 在 factored/hybrid state 中共同演化；联合 action/state space 和交互造成组合爆炸。 |
| 血缘 | policy 所用 belief 不保留逐证据 lineage；需要独立可回放输入和决策 receipt。 |
| 扩展 | 新 action、observation、constraint 或 latent mode 会改变规划空间与 value approximation。 |
| 任务坐标 | diagnosis belief、value of information、treatment value、risk constraints 和 policy query 直接关联。 |
| 天然优势 | 统一“下一项检查还是立即治疗”、部分可见下的闭环行动与长期后果。 |
| 必补 | causal identification、bitemporal event/provenance、hard constraints、OOD/refusal、policy uncertainty、可解释决策合同。 |
| 最坏失败 | 错误 reward、近似 value 或混杂 action model 产生危险策略；闭世界 belief 总和仍为 1；C-POMDP 约束可能时间不一致。 |

### C05. 结构因果模型（SCM）

**证据基线**：`research_notes/03_causal_probprog.md` §§3–4, 8–9, 12, 14。  
**状态**：`H-CORE + P-PROT`；纯 SCM 作为整核硬淘汰，但 observation/intervention/counterfactual 与 AAP 语义不可替代，动态 SCM 进入因果语义 Pareto 原型。

| 字段 | 统一回答 |
|---|---|
| 原语 | 外生变量、内生变量、结构函数、外生分布、子模型/机制替换、causal query。 |
| 状态 | 事实世界中的结构方程解；患者知识态是 `P(U,V|evidence)`，不是已确认点。 |
| 时间 | time-indexed variables 或 dynamic/cyclic SCM；标准 SCM 不表达何时获知、记录、过期。 |
| 观察 | 对显式 observation mechanism 的输出条件化，不能直接把测量值当 latent truth。 |
| 干预 | hard `do` 替换方程；临床药物更常是 soft/mechanism intervention，经 PK/PD 作用。 |
| 不确定性 | `P_U`、参数/模型集合和 posterior；未问、冲突、不可识别不是自动的概率类别。 |
| 共病 | 多机制共享变量、共同进入非线性结构函数；交互必须显式建模。 |
| 血缘 | 因果父节点解释世界生成，不说明文档/抽取/推导来源；必须另建 evidence provenance。 |
| 扩展 | 增变量/模块；新增混杂、反馈和交互常迫使修改旧函数，模块自治需验证。 |
| 任务坐标 | observational、interventional、counterfactual query 与不同 outcome/readout。 |
| 天然优势 | conditioning 与 doing 的正式分离；abduction→action→prediction 保持同一患者世界；共享机制和反事实一致性。 |
| 必补 | typed evidence store、多时间 replay、provenance、identification status、覆盖/OOD、循环解存在唯一性、推断诊断。 |
| 最坏失败 | 一个拟合良好但因果结构错误的模型，给出高置信错误干预；AAP 语法正确也不等于 effect 可识别。 |

### C06. 通用概率程序（PPL）

**证据基线**：`research_notes/03_causal_probprog.md` §5, §§8–9, 12, 14。  
**状态**：`H-CORE + R-COMP`；普通 PPL 作为因果或完整临床核心硬淘汰，保留为不确定生成模型与推断算法的执行宿主。

| 字段 | 统一回答 |
|---|---|
| 原语 | 宿主计算、`sample`、`observe/score`、`return`；可选随机地址、trace、effect handler。 |
| 状态 | 一次 execution trace 及其 posterior；程序可动态生成控制流和对象。 |
| 时间 | 代码中的索引、递归、ODE/CTMC solver 或事件，不自带临床 typed time。 |
| 观察 | likelihood/conditioning，适合自定义 measurement model。 |
| 干预 | 普通 PPL 没有 `do`；改程序或 effect handler 不等于已定义因果世界共享。 |
| 不确定性 | 概率分布、潜变量、参数/结构先验和 posterior 原生；认识论状态另需类型。 |
| 共病 | 函数组合和共享随机变量；地址、重复 score、共享噪声和交互接口由作者负责。 |
| 血缘 | execution trace 记录随机选择，不记录 clinical source family、抽取活动、规则版本和删除级联。 |
| 扩展 | 加函数/模块容易，但控制流变化会改 trace addresses、推断器和版本兼容。 |
| 任务坐标 | 任意 posterior query/readout 可编程。 |
| 天然优势 | 表达复杂不确定生成过程、递归对象、自定义 likelihood，并允许替换推断算法。 |
| 必补 | causal/multi-world semantics、identification、typed time、evidence provenance、coverage/OOD、显式 numerical failure。 |
| 最坏失败 | 程序可运行、后验似乎收敛，却实现了错误查询；近似推断再叠一层无界误差，仍输出精确小数。 |

### C07. 因果概率程序（causal PPL）

**证据基线**：`research_notes/03_causal_probprog.md` §6, §§8–14。  
**状态**：`H-CORE + P-PROT`；整核仍缺事件/血缘/安全，但作为可执行因果子内核进入 Pareto 原型。

| 字段 | 统一回答 |
|---|---|
| 原语 | PPL 基元，加 exogenous/mechanism、intervention point/program transform、事实/反事实 world 管理和 typed query。 |
| 状态 | 多世界 execution traces 与 posterior；个体反事实按 policy 共享事实世界经 abduction 得到的外生背景。 |
| 时间 | 仍由模型代码定义；无默认 occurrence/available/recorded/expiry。 |
| 观察 | 只在 factual world 条件化；必须防止观察被错误复制到反事实分支。 |
| 干预 | 机制替换、soft intervention 或 effect handler，是相对普通 PPL 的决定性增量。 |
| 不确定性 | posterior、参数/结构先验、近似推断；identification uncertainty 必须和采样误差分开。 |
| 共病 | 机制程序组合并显式写交互；typed causal signature 可减少接线错误。 |
| 血缘 | world/trace 地址仍不是 clinical source/derivation lineage。 |
| 扩展 | 新机制模块可局部加入，但 causal signature、随机地址、推断和版本兼容会受影响。 |
| 任务坐标 | 同一事实 posterior 上执行 diagnosis/prognosis/intervention/counterfactual/safety query。 |
| 天然优势 | observation、intervention、soft mechanism change 和 AAP counterfactual 可执行；模型与推断器解耦。 |
| 必补 | bitemporal evidence、provenance/撤回、identification/refusal、OOD、审计 DSL、数值诊断、硬不变量。 |
| 最坏失败 | 多世界程序写对，但因果假设错、effect 不可识别、近似推断未收敛，仍返回有小数点的错误答案。 |

### C08. 开放宇宙关系概率/因果程序

**证据基线**：`research_notes/03_causal_probprog.md` §7, §§8–14。  
**状态**：`H-CORE + R-COMP`；保留对象数/身份不确定与按需实例化能力，不能把“无界对象”偷换成“能发明未知医学概念”。

| 字段 | 统一回答 |
|---|---|
| 原语 | types、relations/random functions、对象生成过程、未知 identity/count、关系模板；因果变体再加 causal laws/intervention。 |
| 状态 | possible world 中对象集合、身份关系和变量赋值；系统持有其 posterior。 |
| 时间 | 时间索引或 causal event 顺序；不自动给多时态日志与未来信息隔离。 |
| 观察 | 对未知对象、匹配/链接和关系实例条件化，可推断多个记录是否同源对象。 |
| 干预 | 取决于具体 causal extension；BLOG 式普通关系 PPL 不天然有 `do/AAP`。 |
| 不确定性 | 对象数量、身份、关系和参数 posterior；概念级 unknown/OOD 仍缺。 |
| 共病 | 关系模板可实例化多个机制/病灶/暴露并共享对象；交互仍需 causal law。 |
| 血缘 | 对象 identity posterior 不是证据来源 identity；文档/抽取/推导血缘必须另存。 |
| 扩展 | 新对象实例可按需生成；新增 predicate/type/mechanism 仍修改签名和模型。 |
| 任务坐标 | object linkage、病灶计数、关系查询、causal/probabilistic readout。 |
| 天然优势 | 未知数量对象、身份歧义、关系模板化和稀疏实例化。 |
| 必补 | 概念开放/OOD、多时间事件、provenance、causal identification、可判定/可计算限制、安全。 |
| 最坏失败 | 系统对模型签名内的无限对象很灵活，却把签名外新病强配为已知关系；或对象生成导致不可判定/推断爆炸。 |

### C09. 符号事件/动作演算（EC-like；SC 为替代模块）

**证据基线**：`research_notes/04_temporal_event.md` §§1–2, 3.2–3.8, 9。  
**状态**：`H-CORE + R-COMP`；保留事件—fluent/动作—后继语义，单独不能承担连续潜状态、概率和事实级血缘。

| 字段 | 统一回答 |
|---|---|
| 原语 | EC：event、fluent、time、happens/initiates/terminates/holdsAt/inertia；SC：situation、action、`do(a,s)`、precondition、successor-state axiom。 |
| 状态 | EC 中某时点成立的 fluent 集；SC 中动作历史所到 situation；均不是原始证据存档。 |
| 时间 | EC 适合异步事件与区间；SC 偏串行动作历史。二者都不自动给 valid/transaction/availability 多时态。 |
| 观察 | observation event 可触发或支持 fluent；必须阻止瞬时测量默认无限惯性。 |
| 干预 | 只有实际执行 action/event 才 initiate/terminate；计划、医嘱、拒绝需不同对象。 |
| 不确定性 | 标准演算是逻辑真假/默认推理；概率、冲突、unknown 需明确扩展，禁止 negation-as-failure 充当阴性。 |
| 共病 | 并行 fluent 与 context-dependent effect axioms；间接效应和交互要显式规则，易 ramification explosion。 |
| 血缘 | 可给出事件导致 fluent 的逻辑路径，但不自动保存原始 artifact、同源组和版本撤回。 |
| 扩展 | 增 event/fluent/effect axioms；successor-state/ramification 可能发生非局部冲突。 |
| 任务坐标 | holds-at、历史状态、动作可执行性、计划/回归、时态安全 query。 |
| 天然优势 | 惯性、事件起止、迟到的过去事件、动作是否真正发生及符号时态查询。 |
| 必补 | 多时间账本、provenance/TMS、概率 observation/state model、规则版本、开放世界、连续 dynamics。 |
| 最坏失败 | 把“未见事件”当“未发生”；错误惯性让旧观察永久有效；交互/间接效应规则爆炸；未来记录泄入历史判断。 |

### C10. Temporal Evidence Ledger（TEL）

**证据基线**：`research_notes/04_temporal_event.md` §§3–10。  
**状态**：`H-CORE + P-PROT`；单独不是诊疗动力学，但作为 temporal/evidence kernel 在未来隔离、回放、血缘和撤回上进入 Pareto 原型。

| 字段 | 统一回答 |
|---|---|
| 原语 | `Subject/Object, EventVersion, TypedTime, Claim, ProvenanceToken, RuleVersion, Projection, Invariant/QueryCut`。 |
| 状态 | durable source 是不可变版本事件日志；当前/历史/任务状态是带 input cut 与规则版本的可丢弃 projection。 |
| 时间 | occurrence、collected、actor-available、recorded/tx、valid interval、expires、invalidates；支持区间与偏序。 |
| 观察 | 带方法、设备、标本、支持治疗上下文、极性、源 ID 的 immutable event；默认不惯性持续。 |
| 干预 | planned/ordered/started/administered/adjusted/stopped/not-performed 分型；只有 performed event 产生 effect。 |
| 不确定性 | 最低为正/反支持四态和 missing reasons；概率大小、相关性、latent competition 需显式概率层。 |
| 共病 | 并行 hypotheses/claims 与版本化 interaction rules；保存时序和来源，不自动估计交互强度。 |
| 血缘 | root source group 的幂等 support set + 完整 derivation DAG；撤回发负 delta，经 IVM/TMS 级联失效。 |
| 扩展 | 新检查/药物/疾病/任务加 schema、rule 或 projection，不改 journal/replay 核；新理论以 RuleVersion 重解释。 |
| 任务坐标 | `Projection(prefix, rule_version, task, query_cut)`；明确分 `replay_as_then` 与 `reinterpret_now`。 |
| 天然优势 | 多时间、未来信息隔离、法证回放、规则版本、同源去重、撤回传播、多 read models。 |
| 必补 | 连续/隐状态动力学、measurement likelihood、因果 effect、概率融合、OOD posterior；还需验证 IVM 与全量重算等价。 |
| 最坏失败 | event type/reducer 变万能垃圾桶；actor availability 伪精确；新 reducer 改写过去；递归/否定撤回不一致；只能追到黑箱调用。 |

### C11. 多重集变迁系统（Petri–reaction 单骨架）

**证据基线**：`research_notes/05_process_networks.md` §§1, 3–7。  
**状态**：`H-CORE + P-PROT`；保留资源、机制动力学、非线性交互、并发和可达性并进入机制维度 Pareto；Petri 与 reaction **只记一个骨架**。

| 字段 | 统一回答 |
|---|---|
| 原语 | typed place/species、多重集 marking/count/concentration、局部 transition/reaction、pre/post stoichiometry；可选 guard、rate/propensity、open ports。 |
| 状态 | 离散 token marking `N^S`，或同一 stoichiometric skeleton 的浓度 `R^S_{>=0}`；不是证据知识态。 |
| 时间 | timed firing、ODE 连续时间或 CTMC reaction time；不含采集/可见/记录/有效时间。 |
| 观察 | labeled transition、observation token 或 state observable；measurement process/likelihood 和可靠度需另建。 |
| 干预 | firing、改变 rate/initial condition/input flow、添加/抑制 reaction；计划/实施 lifecycle 需类型层。 |
| 不确定性 | nondeterminism、SPN/CTMC aleatory randomness；epistemic posterior、冲突、模型外不原生。 |
| 共病 | 子网并置、共享 place/species、同步 transition、多输入反应和反馈；非加性作用自然。 |
| 血缘 | 普通 marking/浓度聚合会丢 token 来源；unfolding 是过程因果偏序，不等于临床 evidence provenance。 |
| 扩展 | 加局部 transition/reaction 不改 solver；共享 species、rate 校准和全局 invariants 仍可能扩散。 |
| 任务坐标 | marking/observable、reachability、invariant、steady state、hazard/readout。 |
| 天然优势 | 资源守恒、非负性、竞争/同步、局部机制、非线性质量作用、随机演化和干预 effect。 |
| 必补 | typed event/evidence ledger、多时钟、observation/filter、provenance/TMS、open-world、task projections、delay/non-Markov memory。 |
| 最坏失败 | `0` 同时表示不存在/未测；聚合抹去来源；参数不可辨识；Markov/瞬时假设错；reachability 或规则展开爆炸。 |

**合并理由**：Petri `M' = M-Pre+Post` 与 reaction `X(t)=X(0)+Σ Y_r(∫λ_r)(y'_r-y_r)` 共享同一 incidence/stoichiometric update。前者强调离散资源与并发，后者强调 rate、ODE/CTMC 和浓度极限；这是两种语义实现，不是两个固定核心。

### C12. 进程代数 / 并发协议演算

**证据基线**：`research_notes/05_process_networks.md` §2, §§4–7。  
**状态**：`H-CORE + R-COMP`；硬淘汰为患者事实/动力学整核，保留为控制面、工作流与组件协议 DSL。

| 字段 | 统一回答 |
|---|---|
| 原语 | action、prefix、choice、parallel composition、synchronization、restriction/hiding、renaming、recursion。 |
| 状态 | residual process term 或 LTS node；临床数值数据需 data-carrying process/外部 store。 |
| 时间 | 经典 CCS/CSP 无定量时间；Timed CSP、PEPA 等是专门扩展，不统一临床多时间。 |
| 观察 | visible actions；`τ`/hiding 支持部分可见行为，但没有 measurement likelihood。 |
| 干预 | action/communication/process replacement；擅长编排，不定义生理 effect map。 |
| 不确定性 | nondeterministic choice；概率/Markov rate 取决于具体 calculus，不是 epistemic posterior。 |
| 共病 | `P || Q`、共享 channel/action 和动态连接；行为交互强，数值非线性需外部方程。 |
| 血缘 | trace 保留 action 顺序，但 hiding/weak equivalence 故意抹去内部差异，与完整审计有张力。 |
| 扩展 | 新 process 经接口组合；全局 alphabet、同步集合和 state product 仍可扩散。 |
| 任务坐标 | observer/test process、refinement、temporal query、可选 reward extension。 |
| 天然优势 | 协议、并发、同步、deadlock/divergence、安全/活性精化和动态连接。 |
| 必补 | typed clinical store、多时间事件、认识论类型、provenance/TMS、概率 filter、task readout。 |
| 最坏失败 | 连续生理被编码为巨型 process；同步 rendezvous 冒充异步病历；行为 quotient 抹掉必要来源；状态空间指数爆炸。 |

### C13. 类型化重写逻辑

**证据基线**：`research_notes/06_types_rewrite.md` §3, §§7–11。  
**状态**：`H-CORE + P-PROT`；作为完整临床核心仍缺概率/证据纪律，但局部可执行转移、搜索和反例路径进入 Pareto 原型。

| 字段 | 统一回答 |
|---|---|
| 原语 | typed term/sort、equation/structural axiom、labeled guarded rewrite rule、configuration operator、strategy/search。 |
| 状态 | 可组合全局项或 multiset configuration；建议把 immutable History、MaterializedClaims、PendingActions、RuleSetVersion 分区。 |
| 时间 | 显式 clock/as-of term、instantaneous rule 与 tick rule；临床多时间仍须统一 schema。 |
| 观察 | 不可变 `Observation` 项；观察到正常值不能直接 rewrite 为 latent-normal。 |
| 干预 | `Planned/Authorized/RequestSent/Administered` 不同项与 capability-constrained transition；治疗对 state/observation 分开写。 |
| 不确定性 | 非确定分支、显式 weighted/probabilistic rewriting；标准重写逻辑无临床 posterior 语义。 |
| 共病 | multiset configuration + 多项 LHS rule 可表达条件交互与并发。 |
| 血缘 | 必须强制 RHS 携带 rule/version/premise/root-source；重写逻辑本身不会自动生成证据守恒。 |
| 扩展 | 加 module/sort/rule；稳定接口下局部，但新规则可能破坏 termination/confluence/coherence。 |
| 任务坐标 | equational normalization、readout rewrite、search/query；读出规则须与患者变化规则分层。 |
| 天然优势 | 局部状态变化、并发、可执行语义、reachability、反例路径、有限抽象上的 model checking。 |
| 必补 | bitemporal event/provenance、TMS、概率、规则版本、确定 materialization、开放世界和预算拒绝。 |
| 最坏失败 | 非合流让结论依执行顺序；循环不终止；strategy/priority 暗中成为疾病 hardcode；组合状态爆炸。 |

### C14. 类型化时态逻辑编程 + provenance/TMS

**证据基线**：`research_notes/06_types_rewrite.md` §4, §§7–11。  
**状态**：`H-CORE + P-PROT`；以 positive temporal Datalog + explicit polarity + root provenance + IVM/TMS 进入 Pareto 原型；ASP/CHR 不可偷换成同一语义。

| 字段 | 统一回答 |
|---|---|
| 原语 | typed EDB fact/relation、Horn/Datalog rule、query、least fixpoint；扩展含 explicit polarity、provenance annotation、TMS/IVM。 |
| 状态 | 版本化 EDB 事件 + IDB/materialized derived facts；历史源不能被当前事实表覆盖。 |
| 时间 | relation 参数和强制 `available_at <= as_of` guard；普通 Datalog 不自动提供临床时间类型。 |
| 观察 | 独立 observation/reported predicate，带 polarity、method、context、source；不与 latent/hypothesis 混表。 |
| 干预 | planned/ordered/administered 分谓词；规则可推后果，实际执行需 capability/receipt。 |
| 不确定性 | 首选正/负支持四态；possible worlds、ASP stable models 或概率扩展必须明确选一种，不得混称。 |
| 共病 | 多前提和递归规则可写交互；交互知识与可能的组合爆炸均显式。 |
| 血缘 | semiring/derivation DAG + 幂等 root-source set；`+` 是替代推导、`×` 是共同使用，不代表统计独立。 |
| 扩展 | 加 facts/rules/views 通常不改求值器；全局 dependency/cycle/negation 仍需 lint 和 regression。 |
| 任务坐标 | task-specific query 或 materialized view，天然支持多个 readout。 |
| 天然优势 | 声明式局部规则、固定点、递归、多推导解释、查询投影、增量物化和删除重算。 |
| 必补 | explicit unknown/negative discipline、多时间、概率/因果、撤回、冲突 policy、动作 capability、推断预算。 |
| 最坏失败 | negation-as-failure 把未知变阴性；多/无 stable model 被静默压成一个；provenance 爆炸；局部规则触发全局意外循环。 |

**边界注记**：CHR 是约束多集重写，归入 C13/C11 的实现参考；ASP 若作为非单调 possible-world 求解器参赛，应另立明确原型合同，不能把其多/无 stable-model 风险藏在本条的 positive Datalog 基线中。

### C15. Entity–Component–System（ECS）运行时组织

**证据基线**：`research_notes/06_types_rewrite.md` §5, §§7–11。  
**状态**：`H-CORE + R-COMP`；硬淘汰为临床语义核心，只保留高性能数据布局、批处理和执行层候选；不计入“动态世界模型”数量。

| 字段 | 统一回答 |
|---|---|
| 原语 | entity ID、component data、system、world/query/archetype。 |
| 状态 | entity 当前关联的 component 集；通常是可变运行时状态。 |
| 时间 | frame/system update；临床 timestamp、历史和多时间必须另加 event components/store。 |
| 观察 | Observation component；component 缺席极易被误读为否定。 |
| 干预 | command/action components + systems；计划/实施、授权/回执需额外协议。 |
| 不确定性 | status/conflict/hypothesis components 外加，标准 ECS 不定义逻辑。 |
| 共病 | 多 components 与 matching systems，组合/局部布局容易；交互语义藏在 systems。 |
| 血缘 | 另加 provenance graph/IDs；query 不保存 derivation。 |
| 扩展 | 加 component/system 对布局友好；system dependency、ordering 和 scheduler 仍全局影响。 |
| 任务坐标 | 不同 systems/queries 选择 component 组合。 |
| 天然优势 | 数据导向组织、cache locality、批处理、并行执行和热路径优化。 |
| 必补 | 几乎全部临床语义：事件、时间、证据、unknown/conflict、重放、撤回、因果、概率、安全。 |
| 最坏失败 | component presence 被当 truth；derived component 重复计数；system 顺序成为隐性医学语义；删除 component 同时删除历史。 |

### C16. 黑板 / 共享工作区架构

**证据基线**：`research_notes/06_types_rewrite.md` §6, §§7–11。  
**状态**：`H-CORE + R-COMP`；硬淘汰为临床事实与推理语义核心，保留为异构模块/agent 协作和资源调度外壳；不计入动态世界模型数量。

| 字段 | 统一回答 |
|---|---|
| 原语 | shared blackboard、分层 hypotheses、knowledge sources、controller/scheduler。 |
| 状态 | blackboard 上当前 hypotheses/partial solutions，通常共享可变。 |
| 时间 | 可按任务阶段或领域时间组织，但 clinical occurrence/available/recorded/valid 需另建。 |
| 观察 | 输入或低层 hypothesis；没有 typed partition 时 observation、inference、plan 容易混写。 |
| 干预 | knowledge source 写 action proposal；实际执行能力、receipt 和 effect 不是标准语义。 |
| 不确定性 | 竞争 hypotheses 和评分；不同 knowledge source 的 score 可能不可比较。 |
| 共病 | 多知识源共同修改 hypotheses，表达力强而组合律不统一。 |
| 血缘 | hypothesis link 可给局部解释，但不保证 root evidence 守恒、同源去重或撤回。 |
| 扩展 | 加 knowledge source 相对局部；controller、共享 schema 和调度策略成为瓶颈。 |
| 任务坐标 | task-specific knowledge source/readout 或 blackboard level。 |
| 天然优势 | 异构模块协作、多假说、机会式推理、有限资源下的调度。 |
| 必补 | 类型、多时间、provenance/TMS、冲突逻辑、capability、安全、确定性重放。 |
| 最坏失败 | scheduler priority 决定医学结论；共享状态污染；知识源互相强化成自证环；相同输入无法确定重放。 |

### C17. 类型化开放组合动态系统

**证据基线**：`research_notes/07_compositional.md` §§2–12。  
**状态**：`H-CORE + P-PROT`；裸 category/operad 不参赛，只有带具体 state/update/readout 的 open machines 进入组合性 Pareto 原型。

| 字段 | 统一回答 |
|---|---|
| 原语 | typed port/interface、private state、input/output、behavior/update/readout、operadic wiring 或 structured boundary gluing、interaction component。 |
| 状态 | 各组件 private state + 显式共享/边界变量；组合后状态由行为代数决定，禁止复制同一患者共享状态。 |
| 时间 | 由组件 behavior（离散、连续、hybrid、temporal behavior）提供；组合语法本身无多知识时钟。 |
| 观察 | typed input/output port，必须标明 epistemic role、unit、subject、context 和 clock contract。 |
| 干预 | action port 与 state/observation effect component；必须区分 planned/performed 并验证 feedback well-posedness。 |
| 不确定性 | 取决于组件 behavior（relation/probability/set）；组合框架不自动提供临床 posterior/unknown。 |
| 共病 | 子系统并列、共享边界和显式 interaction boxes；非线性交互不会从平行组合自动涌现。 |
| 血缘 | 只有 trace-preserving morphism/readout 才可保留；传统 black-boxing 可能故意丢内部 trace。 |
| 扩展 | 稳定 typed ports 下增加组件可局部；interaction/port/readout 数量可能成为新爆炸点。 |
| 任务坐标 | versioned trace-preserving readout maps；不同任务可读同一组合行为。 |
| 天然优势 | 局部组件互连、层级组合、接口化扩展、状态/输入/输出分离、替换和复用。 |
| 必补 | 多时间 event ledger、epistemic ADT、provenance/TMS、action lifecycle、OOD、feedback validator、共享状态/交互合同。 |
| 最坏失败 | 数学上 coherent 地组合了语义错误组件；每对疾病都需专属 glue；错误 topology/ports 制造伪一致；black-box readout 丢血缘。 |

### C18. 普通 RDF/OWL 声明式知识图谱

**证据基线**：`research_notes/08_graph_world.md` §§1.1–1.7。  
**状态**：`H-CORE + R-COMP`；裸 RDF/OWL 图作为完整动态核心硬淘汰，保留术语、本体、异构关系、交换和查询层；不计入动态世界模型数量。

| 字段 | 统一回答 |
|---|---|
| 原语 | IRI/literal、subject–predicate–object triple、graph、ontology axiom、entailment/query；reification/named graph 是额外建模。 |
| 状态 | 当前 assertion graph 或 entailment closure；它是陈述集合，不是患者隐藏生理状态。 |
| 时间 | RDF 抽象模型本身 atemporal、graph 是 static snapshot；时间 vocabulary 只是被描述内容，不给更新/replay。 |
| 观察 | 可建 observation node/triples；若直接以 proposition triple 表示，会合并不同测量 occurrence。 |
| 干预 | planned/administered/effect 可作为关系陈述，但 `affects` edge 不是 `do`、transition 或 dose-response operator。 |
| 不确定性 | OWL open-world 防止“没写即假”；confidence literal、冲突 claim、概率和 model discrepancy 均需外加语义。 |
| 共病 | graph union、共享节点和 interaction relation 直观；union 不规定竞争、门控、速率或状态更新。 |
| 血缘 | named graph/PROV vocabulary 可承载来源，但普通 triple identity 不是 evidence occurrence identity，也无递归撤回。 |
| 扩展 | 新 IRI/axiom/edge 易加入；ontology closure、shape、materialization 和 query 可能非局部变化。 |
| 任务坐标 | SPARQL/CONSTRUCT、subgraph、metapath 或 graph feature projection。 |
| 天然优势 | 术语互操作、异构关系、开放词汇、图查询、本体蕴含和人可读关联。 |
| 必补 | occurrence identity、typed multi-time、claim isolation、PROV/TMS、dynamic/causal/probability interpreter、coverage、fail-closed safety。 |
| 最坏失败 | 把 path/association 当因果；把 retrieved/materialized subgraph 当完整世界；相同 triple 合并独立测量，或多次 ETL 改写又被重复计票。 |

### C19. 以发生实例为中心的类型化双时间事件超图

**证据基线**：`research_notes/08_graph_world.md` §§1.1–1.7。  
**状态**：`H-CORE + P-PROT`；单独不能执行患者动力学，但作为共享事实、证据、冲突假说与多任务视图底座进入表示层 Pareto 原型。

| 字段 | 统一回答 |
|---|---|
| 原语 | typed entity、稳定 ID 的 occurrence/hyperedge、n-ary role ports、claim status、typed times、version、graph/view。 |
| 状态 | `G(valid_at, known_by, knowledge_version)` 是当时可知的 assertion view，不是 latent `X_t`；潜状态只能是估计 claim。 |
| 时间 | occurrence/valid、known/available、recorded/transaction、expiry/invalidation 等 typed annotations 与 as-of view。 |
| 观察 | 独立 occurrence 绑定 subject、value/unit、method、specimen、device、treatment context、source 和可见时间。 |
| 干预 | planned/order/administered/stopped 等 occurrence 类型；effect hyperedge 可指 state/observation，但不会自动执行 `do/T`。 |
| 不确定性 | 多 claim、支持/反对、reliability、冲突可并存；联合概率、来源相关性和 OOD 仍需计算层。 |
| 共病 | graph union、共享机制实体、n-ary interaction occurrence；incidence 不规定动力学交互强度。 |
| 血缘 | occurrence identity + Entity/Activity/Agent/use/generation/derivation/invalidation；幂等 roots 和递归撤回仍需 provenance/TMS algebra。 |
| 扩展 | 加 entity/type/role/shape 通常局部；ontology、shape、closure、readout 和 execution module 仍可能扩散。 |
| 任务坐标 | versioned SPARQL/CONSTRUCT/subgraph/readout，从同一 evidence cut 生成 diagnosis/safety/prognosis views 并保留 trace。 |
| 天然优势 | 认识论角色显式、n-ary 上下文、每次事实发生 identity、多时间、异构语义、局部扩词和可视审计。 |
| 必补 | 真值维护/IVM、完整 coverage 状态、probabilistic/causal/dynamic engine、OOD、capability、安全 monitor。 |
| 最坏失败 | “所有东西都是图”掩盖无 interpreter；named graph 被臆定为来源/时间；stale/partial query 漏禁忌；relation/context class 膨胀成特例森林。 |

**与 C10 的边界**：C19 首先规定“事实/发生实例/角色如何表示和互联”；C10 首先规定“版本事件如何按多时间、规则版本和知识截断重放及撤回”。强实现可能同时满足两者，但能力归属必须逐项计账，不能因数据存成图便宣称已具备 TEL 的 IVM/replay semantics。

### C20. Temporal sheaf / behavioral consistency system

**证据基线**：`research_notes/07_compositional.md` §§2.5, 4–5, 7–12。  
**状态**：`H-CORE + R-COMP`；裸 sheaf 不参赛；当 sections 是时间/上下文 behaviors 时，保留为局部—全局一致性与冲突 witness 模块，不单独承担动态生成和诊疗推断。

| 字段 | 统一回答 |
|---|---|
| 原语 | context/time category or site、presheaf/sheaf `F:C^op→Set`、local section、restriction map、cover、matching family、gluing/global section。 |
| 状态 | 各局部上下文/时间窗上的 behavior sections 及其兼容关系；不是必然存在的单一全局 patient state。 |
| 时间 | 时间区间/上下文作为 base category objects，restriction 表示缩到子区间；不自动含 knowledge/record/expiry clocks。 |
| 观察 | 某局部 context 上的 section；跨设备/角色/时间的一致性通过 overlap restrictions 检查。 |
| 干预 | 可作为改变局部 behavior/上下文的 morphism 或 section，但没有标准 `do`、action lifecycle 或 effect identification。 |
| 不确定性 | 多个局部/全局 sections 或无 global section 可表达歧义/不一致；概率权重和 noisy gluing 需额外 measure/metric/optimizer。 |
| 共病 | 各机制局部行为在共享 overlap 上匹配；无法 gluing 可暴露不兼容，但不会自动给 interaction dynamics。 |
| 血缘 | restriction/gluing diagram 能给 consistency witness，不记录原始 artifact、同源根和删除级联。 |
| 扩展 | 新 context/cover/restriction 可局部加入；topology 与 restriction contract 的改变可能重写全部一致性结论。 |
| 任务坐标 | 按任务选 context cover/restriction，查询局部兼容、global sections 或 obstruction。 |
| 天然优势 | 保留局部语境、检测跨上下文不一致、避免强行全局单值、表达时间行为的限制关系。 |
| 必补 | event/provenance ledger、动态 generator、causal/probability semantics、action lifecycle、OOD、安全与 approximate-gluing refusal。 |
| 最坏失败 | 错误 topology/restriction 让错误模型“完美一致”；nearest-section 优化静默平滑真实冲突；无 global section 被误读成患者不存在或单一诊断失败。 |

---

## 3. 不另计家族、但必须单独审计的三种高频主张

### 3.1 Learned generative world model：C03/C04 的参数化子型

World Models、PlaNet、Dreamer 的共同合同是 `posterior/belief update + action-conditioned latent transition + observation/reward/continue heads + rollout`。这与 C03 的 nonlinear state-space skeleton 相同；加入 MPC/actor/critic/value 后属于 C04。因此不按 VAE、RSSM、Dreamer 版本或 Transformer backbone 重复计数。

| 字段组 | 审计摘要 |
|---|---|
| 原语/状态/时间 | stochastic/deterministic latent、belief、action、transition、encoder/decoder、rollout；通常单一 model time/horizon。 |
| 观察/干预/不确定性 | encoder/filter 与 decoder 分离 latent/observation；action-conditioned prediction 不自动等于 `do`；stochastic latent 不等于 calibrated epistemic/OOD。 |
| 共病/血缘/扩展 | 非线性 transition 表达强但 monolithic；证据压入 latent/weights 后 root identity 和局部撤回丢失；新 observation/action 往往需全局训练。 |
| 任务坐标/优势 | filtering、forecast、imagination rollout、多个 outcome/value heads；患者个体化 assimilation 和高阶预测强。 |
| 必补/最坏失败 | authoritative event ledger、causal validity、coverage/VVUQ、安全 invariant；最坏是 controller 主动利用模型误差，混杂 treatment effect 进入现实反馈。 |

### 3.2 Digital twin：部署/生命周期系统模式，不是统一 calculus

数字孪生的稳定主张是 physical counterpart 与 virtual representation 通过数据获取/同化和反馈持续耦合，并管理 model/data 生命周期。其内部可以是 ODE/PDE、SSM、SCM、KG 或混合系统，所以不凭 `twin` 名称增加一个动态内核。保留它作为部署、同步、context-of-use、VVUQ/credibility 和模型治理参考；拒绝用品牌名替代状态、因果、时间、血缘或撤回语义。

### 3.3 Transformer/QKV/统一隐状态：计算层，不是权威事实本体

| 字段组 | 审计摘要 |
|---|---|
| 原语/状态/时间 | token/embedding、position、Q/K/V、attention、MLP、hidden/KV cache；position/causal mask 不是 clinical multi-time/as-of replay。 |
| 观察/干预/不确定性 | 任意对象均可 token 化，但 action token 只是条件输入；softmax 不区分 unknown/conflict/OOD，需 schema 与独立 gate。 |
| 共病/血缘/扩展 | 高阶上下文强；attention 不是 derivation provenance；全局参数更新无局部 blast-radius 上界。 |
| 任务坐标/优势 | 输入适配、检索/调度、近似推断、多模态融合和多任务 readout 是合理强项。 |
| 必补/最坏失败 | typed immutable events、provenance、dynamic/causal operator、coverage、deterministic invariant；最坏是未来泄漏、同源增信、检索漏禁忌、条件相关冒充干预且输出流畅。 |

因此 Transformer 可参数化 C02/C03/C04/C07/C14/C17 的某些 operator，但 operator 的合法性来自这些显式合同，不来自 QKV 本身。

---

## 4. 硬淘汰、保留角色与当前 Pareto 前沿

### 4.1 全量状态账本

| ID | 单独作为完整固定核心 | 当前研究态 | 仍保留的严格角色 | 不允许偷领的能力 |
|---|---|---|---|---|
| C01 | **硬淘汰** | R-COMP | 数值视图、缓存、模型输入、task projection | 事件、动态、因果、血缘 |
| C02 | **硬淘汰** | **P-PROT** | factored probability、共享潜因、多解释 inference | `do`、多时间、证据撤回 |
| C03 | **硬淘汰** | **P-PROT** | latent dynamics、observation model、filter/forecast | 事实账本、因果识别、OOD 证书 |
| C04 | **硬淘汰** | **P-PROT** | information/treatment action 的 belief decision | reward 即安全、condition 即 intervention |
| C05 | **硬淘汰** | **P-PROT** | `do`、mechanism change、AAP counterfactual | evidence provenance、effect 已识别 |
| C06 | **硬淘汰** | R-COMP | 复杂概率生成程序与推断宿主 | `sample/observe` 即因果、trace 即血缘 |
| C07 | **硬淘汰** | **P-PROT** | 可执行 SCM/AAP、soft intervention、多世界 inference | identification、bitemporal/provenance |
| C08 | **硬淘汰** | R-COMP | 未知对象数/身份、关系模板实例化 | 无界对象即开放医学概念 |
| C09 | **硬淘汰** | R-COMP | event/action effect、inertia、历史动作语义 | 概率、连续潜态、来源独立性 |
| C10 | **硬淘汰** | **P-PROT** | 多时间 evidence/replay/provenance/withdrawal kernel | likelihood、因果 effect、latent physiology |
| C11 | **硬淘汰** | **P-PROT** | 资源/机制变迁、守恒、非线性 interaction | epistemic posterior、病历血缘 |
| C12 | **硬淘汰** | R-COMP | 并发协议、工作流、deadlock/refinement | 患者数值世界、证据语义 |
| C13 | **硬淘汰** | **P-PROT** | 可执行局部转移、搜索、反例/model checking | 概率与 provenance 自动正确 |
| C14 | **硬淘汰** | **P-PROT** | 声明式 derivation、fixpoint、query、TMS/IVM | NAF 即阴性、路径数即证据数 |
| C15 | **硬淘汰** | R-COMP | 高性能 runtime/data layout | component presence 即 clinical truth |
| C16 | **硬淘汰** | R-COMP | 异构模块/agent 协作调度 | scheduler score 即 posterior |
| C17 | **硬淘汰** | **P-PROT** | typed interfaces、open machine composition、局部替换 | wiring correctness 即医学正确 |
| C18 | **硬淘汰** | R-COMP | 术语、本体、声明关系、交换与查询 | graph path 即 causal dynamics |
| C19 | **硬淘汰** | **P-PROT** | occurrence-centered typed fact/claim graph | 图内存了程序即执行了程序 |
| C20 | **硬淘汰** | R-COMP | local-to-global behavior consistency、冲突 witness | gluing 即真实融合/causal evolution |

**为什么“单独整核”一列全部硬淘汰并不等于没有候选**：当前硬需求同时跨越事实/知识时间、潜在状态、概率、因果、行动、安全、血缘和组合。02–08 中没有任何一个原子家族原生覆盖这些互相正交的语义。研究问题因此变成：哪一组最小、可证明接口能组成固定核心，以及哪些能力可以由一个更强共同原语吸收。现在直接从某个原子家族宣布赢家，反而会把外挂能力错误记给它。

### 4.2 当前 Pareto 前沿按“不可互换维度”登记

| Pareto 维度 | 当前不被支配的候选 | 判别点 | 仍缺的另一维度 |
|---|---|---|---|
| 概率分解与多解释 | C02 | 共享潜因、局部 factor、posterior modes、treewidth/近似诊断 | causal/evidence time/provenance |
| 连续/混合潜状态与 observation separation | C03 | 支持治疗下正常观察、stale evidence、filter/forecast | bitemporal/identification/lineage |
| 序贯信息与治疗决策 | C04 | value of information、constraint、closed-loop policy | effect identification、hard safety proof |
| 干预与个体反事实语义 | C05、C07 | `condition` vs `do`、AAP 世界共享、soft mechanism change | evidence kernel、coverage、推断状态 |
| 时间/证据/撤回 | C10 | as-then vs reinterpret-now、actor visibility、negative delta、root identity | latent/probability/causal dynamics |
| 机制非线性/资源/守恒 | C11 | multi-input interaction、ODE/CTMC/token firing、invariants | observation posterior、clinical provenance |
| 可执行规则与反例路径 | C13 | local rewrite、strategy visibility、reachability、confluence/termination | calibrated uncertainty、evidence discipline |
| 声明式推导与 truth maintenance | C14 | explicit polarity、least fixpoint、provenance roots、deletion | continuous dynamics、causal effect |
| 组合接口与局部扩展 | C17 | typed ports、shared-state ownership、interaction box、feedback validator | evidence/time/unknown |
| 事实 occurrence 与 n-ary context | C19 | measurement identity、roles、typed times、claim isolation、graph query | interpreter/TMS/probability/causal |

`P-PROT` 是**分维度 Pareto**，不是把这十项排成一条总榜。一个候选在某维度领先，不能抵消任何硬门失败。

### 4.3 明确硬淘汰的宣传版本

以下主张不再进入原型争论；除非出现能直接推翻相应反例的新证据，否则按硬淘汰处理：

1. “一个高维向量/embedding 足以同时成为事实、状态、时间、证据和决策核心”；
2. “普通 PPL 的 `sample/observe` 天然具有 `do` 和个体 counterfactual 语义”；
3. “RDF/OWL/超图能保存方程，所以图本身已经执行患者动力学”；
4. “Petri 网和 reaction network 是两个独立固定骨架”，或反过来把 stochastic/continuous semantics 无成本计给普通 P/T 网；
5. “类型系统、LTL 或裸范畴论本身就是患者动态模型”；
6. “ECS component、黑板 hypothesis 或 Transformer hidden/KV state 是唯一权威临床事实源”；
7. “attention heatmap、execution trace、causal DAG 或 graph path 自动等于 evidence provenance”；
8. “digital twin”名称本身保证 causal validity、VVUQ、双时间、撤回或监管可信度；
9. “生成 likelihood 高/rollout 逼真即 atlas coverage 或 intervention validity”；
10. “OWL 开放世界、无限变量、未知对象或可生成新字符串等于概念级开放世界与安全 OOD”。

---

## 5. 候选原型 shortlist（不排序、不选赢家）

### 5.1 第一轮最有区分力的九个原型

| 原型 | 被检验的候选 | 最小实现合同 | 一票否决的观察 |
|---|---|---|---|
| S1 | C10 TEL | immutable event versions、typed clocks、root provenance、rule version、`replay_as_then`/`reinterpret_now`、negative-delta withdrawal | 使用未来 evidence；撤回后 dependent claim 残留；两种 replay 混同 |
| S2 | C19 event hypergraph | occurrence IDs、n-ary roles、valid/known/recorded times、claim status、versioned graph query；**不借 TEL reducer** | proposition 合并 measurement identity；partial query 被当完整；更新无明确语义 |
| S3 | C14 temporal Datalog/TMS | positive typed rules、explicit polarity、mandatory availability guard、root-set provenance、DRed/ATMS-style alternative supports | NAF 变阴性；删 root 不撤回；多 derivation 被当独立 evidence |
| S4 | C13 typed rewriting | normalization 与 transition 两层、immutable observations、typed action lifecycle、rule/version roots、search/model-check | 同输入因 rule order 得不同结论且无显式分支；priority 成医学 hardcode |
| S5 | C02 DBN | factored latent/observation variables、shared cause、evidence factor identity、exact/approx status、OOD/null comparator | 同源三票；图错仍无 diagnostic；近似误差无状态 |
| S6 | C03 SSM | latent transition、context-dependent observation model、irregular filtering、multimodal belief、checkpoint replay、model discrepancy | 支持治疗下正常被当 latent normal；smoother 未来泄漏；闭世界过信 |
| S7 | C05/C07 双实现对照 | 同一 SCM/AAP oracle 分别用 structural evaluator 与 causal-PPL multi-world executor；显式 identification status | factual evidence 泄入 counterfactual；反事实重抽患者；conditioning 冒充 doing |
| S8 | C11 multiset transition | 同一 incidence skeleton 提供 discrete-token 与 ODE/CTMC semantics；open ports、interaction、conservation tests | 把两种 semantics 算两个核心；`0` 混合未测；参数不可识别却给机制结论 |
| S9 | C17 open machines | typed ports、private/shared state contract、explicit interaction boxes、associative wiring test、feedback well-posedness validator | 每个 disease pair 专属 glue；共享患者被复制；错误连接未 fail closed |

S7 把 C05 与 C07 放在**同一个医学模型与 query oracle**上，是为了比较“语义定义”与“程序执行”而不让两边医学内容不同；它们仍是两个实现候选，不合并能力记账。S8 明确只建一个 Petri–reaction incidence skeleton，以运行语义开关比较，而不是产出两套网络。

### 5.2 第二轮附着原型

- **C04 POMDP/C-POMDP**：只在 S5/S6/S7 的 observation/action effect 通过 causal-validity gate 后挂接；否则 policy 只会放大模型错。必测检查信息价值、planned vs performed、hard constraint、time consistency 和 policy exploit。
- **C09 Event Calculus**：作为 S1 的 alternate projection/transition semantics，专测迟到事件、inertia、initiate/terminate 和 ramification；Situation Calculus 只有证明动作历史中心带来不可替代能力时才追加。
- **C08 open-universe relational**：给 S7 增加未知对象数/identity 的病例，但不得把新 predicate/OOD 能力算入。
- **C20 temporal sheaf**：给 S9/S2 增加跨设备/角色/时间窗的 compatibility witness；必须同时测试错误 topology 和拒绝 noisy gluing。

### 5.3 公平实验合同

所有 shortlist 原型使用同一组不可变输入 fixtures 和同一组外部 oracle，但能力记账遵守以下规则：

1. **原始 fixture 不等于免费 TEL**：测试 harness 可以提供完整事件清单；若候选需要自行解释时间、来源、撤回，相关代码和原语计入候选补丁。
2. **医学内容相同**：相同 observation model、causal assumptions、interaction facts 和 safety rules；不得给预期答案一方更多知识。
3. **历史查询双轨**：as-known-then 与 current-theory-on-old-evidence 是不同 oracle。
4. **不允许静默降级**：unsupported、out-of-model、identification failure、numerical nonconvergence、partial retrieval 必须是 typed result。
5. **同源证据幂等**：复制、改写或多路径派生不增加 root evidence count。
6. **计划不等于实施**：只有 performed/administration receipt 可进入 action effect。
7. **全量与增量等价**：撤回/更正后的 IVM/TMS 结果必须等于从相同 cut 全量重算。
8. **安全 manifest 不经 top-k retrieval**：罕见禁忌以完整、版本固定的 deterministic scope 执行。
9. **报告真实成本**：primitive count、patch count、核心修改数、规则/端口/interaction 数、人工审核时间、trace 大小、推断误差、延迟和内存全部计入。

---

## 6. 必需但不计入动态候选数量的正交元层

| 元层 | 必须提供的合同 | 为什么不算动态候选 |
|---|---|---|
| Type/ADT/refinement/typestate | unknown/negative/conflict/not-applicable/out-of-model；unit/subject/context；planned→authorized→performed；capability | 约束合法状态和操作，不定义时间演化 |
| Effect/capability system | read/write/execute 权限、外部副作用、receipt、fail-closed | 约束行动边界，不估计患者状态 |
| LTL/MTL/TLA/model checking | future-leak、action lifecycle、安全/活性、期限和 replay 不变量 | 规范/验证 trace，不生成临床世界 |
| Numerical inference diagnostics | convergence、ESS、residual、error bound、approximation/model version | 说明计算是否可信，不给医学本体 |
| Coverage/OOD/VVUQ | support domain、model discrepancy、context of use、abstention/refusal | 校验适用性，不替代 dynamics |
| Identity/unit/schema registry | canonical concept、evidence occurrence、source group、units、schema error | 保证互操作和拒绝，不是转移算子 |

这些元层可能是最终固定核心的组成部分，但**不得用来把任何动态候选的原生能力评分抬高**；反过来，动态候选也不能因“程序里能编码一个 type checker”就宣称元层已被自然吸收。

---

## 7. 本轮综合的可推翻条件与下一步

以下结果会改变当前 Pareto/淘汰状态：

1. 某个更小共同原语在不借第二权威状态源的前提下，同时证明多时间 replay、root provenance/withdrawal、latent observation separation、`do/AAP`、OOD 和 hard safety；
2. shortlist 原型显示某候选所谓天然优势完全由补丁提供，移除候选本体后性能/正确性不变；
3. 某候选在相同医学内容下稳定通过 hard cases，但其最近邻候选必然失败，且 primitive/patch/audit cost 更低；
4. 新知识扩展实验显示 core engine 修改数、task readout 修改数或 interaction 数出现不可接受的非局部增长；
5. 任一原型发生静默未来泄漏、同源增信、planned-as-performed、partial-retrieval-as-absence 或 unsupported-as-known，直接触发该版本硬淘汰。

**当前可复查结论只有三条**：

- 没有证据支持把任何一个原子家族直接宣布为完整固定核心；
- 当前非支配能力分布在 evidence/time、latent probability、causal query、mechanism dynamics、truth maintenance 与 composition 等不同维度；
- 下一步应运行上述统一原型和 hard oracles，再决定最小混合，而不是先按现有 V5、术语流行度或实现便利选赢家。
