# 候选家族 07：范畴论、Operad、Sheaf 与开放/组合系统

> 调查日期：2026-07-13  
> 目的：判断这些抽象是否真的减少固定原语、病例特例和扩展爆炸半径，而不是把“节点、边、函数”改名为“对象、态射、函子”。  
> 证据边界：下列来源证明的是数学/工程上的组合性质；本轮没有找到它们能提高临床诊断安全性或准确性的直接临床验证。因此，本文件只评价其作为固定架构候选的结构能力，不作临床有效性推断。

## 0. 先给结论

1. **“范畴论”本身不是一个可运行的临床语义内核。** 它规定组合应满足什么定律，却不规定什么是患者状态、观察、证据、知识时间、已实施动作或未知。裸范畴论作为独立候选应因严重欠规格而淘汰；把所有内容都叫对象/态射只是在换术语。
2. **真正有工程价值的是“类型化开放组件 + 一个统一的组合律”。** Operad/布线图适合表达“多个局部组件怎样接成整体”；structured cospan 适合表达“沿明确边界怎样粘合”；二者可以把组合语法与 ODE、关系、随机过程等语义分开。这对 `R-COMP-01` 有实质帮助，但并不自动满足证据、时间和不确定性要求。
3. **Sheaf 的价值不同：它形式化“局部上下文能否一致拼成全局”。** 它能把上下文冲突表现为不存在全局截面，并可在时间区间上表示行为；这不是普通图的同义改写。但严格相等的粘合在噪声临床数据中不现实，近似粘合又引入度量和优化语义。错误的覆盖/限制映射会让错误模型“完美一致”。
4. **共病非线性交互不会从平行组合自动涌现。** `A ⊗ B` 通常只把状态并列；竞争、饱和、协同、共享生理量仍须作为可复用交互组件或同一机制层语义显式声明。若每个疾病对都要一个专属交互盒，核心文件虽不变，知识量仍会呈平方甚至更坏增长。
5. **任务读出可以抽象成函子/自然变换，但“存在一个函子”不是实现。** 诊断、安全和预后读出是否保持组合必须逐一证明；强行要求读出严格保持张量会漏掉跨组件风险。传统 black-box functor 还会主动忘掉内部结构，若不携带 trace，会直接违反 `R-PROV-01`。
6. **本家族最合理的定位是组合外壳，不是完整内核。** 可进入原型赛道的版本是“类型化开放行为组件 + operadic wiring（或 structured cospan）+ 显式交互 + trace-preserving task readout”；它仍需外接/内嵌双时间事件、证据血缘、撤回、信息状态和开放世界拒绝语义。
7. **候选计数不要虚增。** 裸范畴、对称幺半范畴、operad、wiring diagram、decorated/structured cospan 多数是同一“组合系统”家族的不同表达层，不应伪装成五个真正不同的架构。Sheaf/局部到全局一致性可以单列为另一家族，或作为开放机器的时间/上下文语义。

## 1. 已核实的第一手来源

| 来源 | 来源性质 | 本轮实际采用的结论 | 不支持的外推 |
|---|---|---|---|
| Fong & Spivak, [*An Invitation to Applied Category Theory: Seven Sketches in Compositionality*](https://doi.org/10.1017/9781108668804), Cambridge UP, 2019；[MIT OCW 课程与开放教材入口](https://ocw.mit.edu/courses/18-s097-applied-category-theory-january-iap-2019/pages/lecture-videos-and-readings/) | 权威教材/出版社与官方课程 | 对称幺半范畴、cospan、hypergraph category、operad、sheaf 是组合结构的不同工具；组合律与具体语义必须区分 | 不证明其适合临床内核 |
| Spivak, [*The operad of wiring diagrams*](https://arxiv.org/abs/1305.0297), 2013 | 原始论文 | wiring diagram 可层级嵌套；选定一个 operad algebra 才决定盒子和布线的具体语义；typed wiring 要求相接端口类型匹配 | 端口类型匹配不等于医学语义正确 |
| Vagner, Spivak & Lerman, [*Algebras of Open Dynamical Systems on the Operad of Wiring Diagrams*](https://arxiv.org/abs/1408.1598), 2015 v2 | 原始论文 | 以有输入/输出端口的盒子为语法，以一般或线性微分方程为 algebra 语义；组合后状态变量为各组件状态变量的不交并/乘积式汇集 | 不提供证据血缘、临床不确定性或共病共享状态的自动识别 |
| Yau, [*Operads of Wiring Diagrams*](https://doi.org/10.1007/978-3-319-95001-3), LNM 2192, Springer, 2018；[预印本](https://arxiv.org/abs/1512.01602) | 权威专著/有限表示定理 | 通用有向 wiring operad 可有限表示，但仍需 8 个生成元和 28 个生成关系；无向版本为 6 个生成元和 17 个关系 | “有限表示”不等于“最小临床核心” |
| Fong, [*Decorated Cospans*](https://arxiv.org/abs/1502.00872), TAC 30, 2015 | 原始论文 | morphism 是带 decoration 的 cospan `X → N ← Y`；可由 lax monoidal functor 生成对称幺半范畴 | decoration 的医学意义仍需另行定义 |
| Baez & Courser, [*Structured Cospans*](https://arxiv.org/abs/1911.04630), TAC 35, 2020 | 原始论文 | structured cospan 形式为 `L(a) → x ← L(b)`；在有限余极限/左伴随等条件下获得对称幺半/双范畴结构；实例包括电路、Petri 网和反应网络 | pushout 粘合本身不提供方向性因果、时间或随机语义 |
| Baez & Pollard, [*A Compositional Framework for Reaction Networks*](https://arxiv.org/abs/1704.02051), Rev. Math. Phys. 29, 2017 | 原始论文 | 开放反应网络可按边界组合；存在到开放动力系统的函子及到稳态输入输出关系的 black-boxing | 结论限于相应反应网络/动力系统语义，不能直接推广为临床任务读出正确性 |
| Baez, Fong & Pollard, [*A Compositional Framework for Markov Processes*](https://arxiv.org/abs/1508.06448), J. Math. Phys. 57, 2016 | 原始论文 | 开放详细平衡 Markov 过程形成可组合类别；black-box functor 保持组合并给出稳态边界关系 | 不是一般非平稳临床推断，也不保留内部证据 trace |
| Lerman, [*Networks of Open Systems*](https://arxiv.org/abs/1705.04814), 2017 | 原始论文 | operad 的层级系统组合与系统间 morphism 可放在同一代数结构中；可从小开放系统构造大系统 | 不自动产生临床上正确的组件边界或交互 |
| Schultz, Spivak & Vasilakopoulou, [*Dynamical Systems and Sheaves*](https://doi.org/10.1007/s10485-019-09565-x), Applied Categorical Structures 28, 2020；[开放预印本](https://arxiv.org/abs/1609.08086) | 同行评审原始论文 | interval sheaf 表示随时间的信号/行为；开放机器用 span 表达；论文给出组合保持 totality/determinism 的条件 | 一条 interval 时间并不自动区分事件时间与知识时间；组合良定性不是无条件的 |
| Robinson, [*Sheaves are the canonical data structure for sensor integration*](https://doi.org/10.1016/j.inffus.2016.12.002), Information Fusion 36, 2017；[开放预印本](https://arxiv.org/abs/1603.01446) | 同行评审原始论文 | sheaf/presheaf 可表示异构传感域、限制映射、全局一致性、consistency radius；精确交叠相等在现实中不合理，因此转为“最近全局截面”优化 | 不证明 nearest global section 在临床冲突中安全；度量和融合目标仍是外加语义 |
| Abramsky & Brandenburger, [*The Sheaf-Theoretic Structure of Non-Locality and Contextuality*](https://doi.org/10.1088/1367-2630/13/11/113036), New J. Phys. 13, 2011；[开放预印本](https://arxiv.org/abs/1102.0264) | 同行评审原始论文 | 在其测量上下文框架内，contextuality 对应全局截面存在性的障碍；说明“局部相容未必存在统一全局赋值”可被严格表达 | 这是量子基础结果；在本文件中只作结构类比，不是临床 contextuality 的经验依据 |
| Myers, [*Double Categories of Open Dynamical Systems*](https://arxiv.org/abs/2005.05956), 2020 | 原始扩展摘要 | 双范畴可同时表示系统互连和不同方向的系统 morphism；轨迹、稳态、周期轨道等可组合 | 增加表达力也增加原语与实现负担；尚无临床证据 |

## 2. 五种最小形式

### 2.1 裸范畴/对称幺半范畴：只给组合语法

最小范畴由：

- 对象 `A, B, ...`；
- morphism `f: A → B`；
- 恒等 `id_A`；
- 顺序组合 `g ∘ f`；
- 结合律和恒等律；

组成。对称幺半范畴再加：

- 平行组合 `A ⊗ B` 与 `f ⊗ g`；
- 单位对象 `I`；
- 交换/结合 coherence。

它保证“先怎样分组再组合”不改变含义，但**没有告诉我们对象和箭头是什么**。若把患者、观察、推断、计划、实施动作全部塞成同一种 morphism，范畴定律不会阻止计划升压药改变患者状态，也不会阻止未来诊断回流成证据。

**判定：**可作为 formalization metalanguage；作为独立架构，因 `R-EPI-01`、`R-TIME-*`、`R-PROV-*`、`R-UNC-*` 全部未定义而淘汰。

### 2.2 Colored operad：一条规则组合任意多个局部盒子

最小形式：

- colors：接口/盒子类型；
- 多输入操作 `ω: (X1, …, Xn) → Y`：一张 wiring diagram；
- substitution：把每个小盒内部继续替换为 wiring diagram；
- identity 与输入置换；
- 一个 algebra `A`，把语法变成具体语义：

```text
A(ω): A(X1) × ... × A(Xn) → A(Y)
A(ω ∘ (ω1,...,ωn)) = A(ω) ∘ (A(ω1),...,A(ωn))
```

Operad 真正减少的是**层级布线的重复实现**：只实现一次 substitution/coherence，就能按同一规则组合新组件。它没有减少具体动态、证据或不确定性的语义数量；这些全部位于 algebra 中。

### 2.3 Structured cospan：沿明确边界做 canonical gluing

给定接口类别 `A`、内部系统类别 `X` 和接口嵌入 `L: A → X`，一个开放系统是：

```text
L(a)  →  x  ←  L(b)
 input   body   output
```

两个系统在共同边界 `b` 上顺序组合时，对内部对象做 pushout；平行组合通常由 coproduct 给出。优势是“从哪个边界连接”成为一等结构，组合引擎不需认识具体疾病名。

但 pushout 表达的是**识别/粘合**，不是“条件性影响”“药物抑制机制”或“观测由潜在状态生成”。若两个接口只因都叫 `creatinine` 就被识别，可能把潜在肾功能、血清测量和药物清除参数错误压成一个对象。方向、时间、概率和因果仍要放进 `X` 或 decoration。

### 2.4 开放动态机器：状态、输入、输出是组件边界

确定性连续时间的最小直觉形式可写成：

```text
M = (S, I, O, f, g)
f: S × I → TS       # 状态更新/向量场
g: S → O            # 输出/观察
```

随机版本可把 `f` 换成 transition kernel、生成元或行为关系。wiring 把某些输出接到其他组件的输入，组合状态通常为各局部状态的乘积/汇集。

这使以下建模变得自然：

- 生理组件产生潜在状态；
- 测量组件把状态和测量条件变成观察；
- 治疗作为输入或独立干预组件，同时接到状态动力学与观测通道；
- 非线性交互作为额外组件，而不是核心 `if disease_name`。

但组合良定性不是免费的。Schultz 等的论文明确指出：仅要求输入映射 total/deterministic **不能在反馈组合下闭合**；还要给输出增加 inertia/delay 条件，才能让 total/deterministic machines 对 wiring 操作闭合。临床中的“监测值 → 自动滴定 → 生理值”正是可能形成无延迟代数环的场景。

### 2.5 Sheaf/presheaf：局部信息、限制与是否能全局拼接

在上下文/时间区间组成的 site 或偏序 `C` 上，一个 presheaf 是：

```text
F: C^op → Set
U ↦ F(U)                         # 上下文 U 上允许的局部状态/记录
V ⊆ U ↦ ρ(U,V): F(U) → F(V)     # 忘掉或限制到更小上下文
```

若覆盖 `{Ui → U}` 上的一组局部 section 在所有重叠处相容，且存在唯一 `s ∈ F(U)` 粘合它们，则 `F` 是 sheaf。

临床解释可以是：

- `U` 是时间区间、测量条件、科室视角或它们的积；
- section 是该上下文中有资格成立的观察/行为；
- restriction 是截短时间、忘掉某个条件或投影到共享字段；
- 不相容局部 section 导致没有全局 section，冲突不会被“最后写入者获胜”静默覆盖。

但“上下文是什么、覆盖怎样选、restriction 做什么”包含主要领域语义。Sheaf 保证给定这些结构后的局部到全局性质；它不保证建模者选对了结构。

## 3. 是否真的减少原语和特例

### 3.1 有实质减少的部分

| 问题 | 组合结构带来的真实压缩 |
|---|---|
| 局部组件接线 | `compose/tensor` 或 operadic substitution 实现一次，而不是每加一病/药写一个执行分支 |
| 层级模型 | “一张由小布线组成的布线仍是一张布线”，不同粒度使用同一组合律 |
| 接口检查 | colored port 可在执行前拒绝明显类型不匹配；无法表达可显式报错 |
| 拓扑粘合 | cospan 用 pushout 统一实现沿共享边界连接，不需手写图合并算法 |
| 局部一致性 | sheaf 的 restriction/gluing 统一表达局部记录是否能组成全局一致赋值 |
| 语法/语义分离 | 同一 wiring 可由 ODE、关系、随机过程等不同 algebra 解释；可比较语义而不重写布线 |
| 组件化读出 | 若 task readout 真是（lax）monoidal functor，可从局部读出组合整体读出 |

### 3.2 没有减少、只是转移位置的部分

| 项目硬问题 | 仍需额外定义的结构 |
|---|---|
| `R-EPI-01` 角色分离 | state/observation/report/inference/hypothesis/plan/executed-action 的 nominal 或 refinement type |
| `R-TIME-01..03` | 至少 event/effective time 与 knowledge/availability time；interval sheaf 单独一轴不够 |
| `R-PROV-01..03` | 原始 evidence identity、依赖集合/semiring、规则版本、truth maintenance 与递归撤回 |
| `R-UNC-01` | absent/not-asked/not-tested/unevaluable/conflict/not-applicable/out-of-model 的信息状态代数 |
| `R-OPEN-01` | 模型外/不可表达/证据不足的拒绝语义；类型不匹配只覆盖其中一小部分 |
| 同源证据去重 | 共享上游机制并不阻止下游 fever/CRP/WBC 在评分器中被错误独立相乘 |
| 非线性共病 | 可复用 interaction mechanism、共享状态身份和无已知组合律时的 `unsupported` |
| 安全不变量 | 必须在类型/契约/验证器中实现，不能指望 wiring 或检索自动满足 |
| LLM 规范化 | 属于输入适配层；范畴结构不能保证同义文本得到同一医学状态 |

### 3.3 “有限生成”不等于最小

Yau 对通用 wiring operad 的有限表示结果很有启发：有向版本需要 8 个生成元和 28 个生成关系，无向版本需要 6 个生成元和 17 个关系。这证明布线语法可以由有限规则生成，但也直接反驳“用了 operad 就只剩一个 compose 原语”的宣传。

本项目统计 `Core primitive count` 时应列出**暴露给领域建模者/解释器的 signature**，而不是把数学库内部 28 条关系全算成医学原语；同时也不能把这些 coherence/反馈限制藏起来报“1 个原语”。

## 4. 局部模型拼接：什么时候自然，什么时候是假拼接

### 4.1 自然场景

以下条件同时成立时，开放系统/operad 的局部扩展有真实优势：

1. 组件有稳定、语义充分的 typed interface；
2. 内部实现只依赖自己的 state 和 ports，不偷读全局 disease registry；
3. 接线本身有明确临床意义；
4. 所需反馈具有 delay/inertia 或另有良定性证明；
5. 未声明交互返回 `unsupported/unresolved`，而不是默认相加；
6. 新组件的语义属于既有 algebra，或能通过显式 algebra morphism 转换。

此时新增检查/药物通常只增加一个组件定义及布线，核心解释器修改数可以为 0。

### 4.2 假拼接一：同类型不等于同语义

若所有端口都用 `float`，`SpO2=98`、`MAP=70`、`dose=5` 可以在类型系统中任意相接，得到“形式合法、医学荒谬”的系统。即使端口名不同，`oxygen_saturation` 仍需区分：

- 潜在氧合状态；
- 室内空气脉氧读数；
- 高流量氧疗下脉氧读数；
- 动脉血气；
- 测量质量/灌注影响。

若最终靠自由文本 port metadata 由 LLM 判断能否相接，组合结构没有降低语义瓶颈。

### 4.3 假拼接二：平行组合复制共享患者

将 `sepsis` 与 `CKD` 两个盒子做 `⊗`，通常得到 `S_sepsis × S_CKD`。若两个盒子各自都有 creatinine/renal clearance，组合会产生两份“同一肾脏”。随后再用名字合并，容易双算或错误识别。

正确做法需要至少一种：

- 共享 physiology component，疾病只通过 ports 修改它；
- 明确 state ownership 与同一实体 identity；
- 一个可复用的 sepsis–renal interaction mechanism；
- 或关系/约束语义允许两个局部视图指向同一底层状态。

这些是实际医学架构决策，不由 `⊗` 自动决定。

### 4.4 假拼接三：交互盒爆炸

可以为每个非线性交互加一个小盒子，这保持核心稳定，却可能把知识负担转成：

```text
n 个疾病/药物组件
→ O(n²) 个 pair interaction
→ 更高阶组合时潜在 O(2^n) context-specific interaction
```

只有当交互能按共享资源、受体、清除机制、器官储备、饱和过程等**机制级组件复用**时，组合架构才真正降低扩展成本。若仍是 `interaction_DiseaseA_DiseaseB`，只是把疾病专属 `if` 改成疾病专属 box。

## 5. 上下文不一致：Sheaf 能发现什么，不能决定什么

### 5.1 真正的优势

Sheaf 把“不同上下文中的值如何投影到共同语义”显式化。对两个记录 `s_U`、`s_V`，只有：

```text
ρ(U,U∩V)(s_U) = ρ(V,U∩V)(s_V)
```

才可精确粘合。若氧疗条件不同，而系统没有合法 restriction 把二者转换到共同可比语义，它们就不会因数值相同被自动合并。相反，两份确实声称同一时间/方法/部位的冲突测量会在重叠处不一致。

Abramsky–Brandenburger 的结果严格展示了：在其测量覆盖框架内，局部可用的分布/赋值可能存在全局截面障碍。对本项目的启示只是**“拒绝强制单一全局真值”具有成熟数学形式**；不能把量子 contextuality 直接当临床证据。

### 5.2 精确相等不现实，近似融合不是中立操作

Robinson 明确指出，在传感器域交集上要求 restriction 后完全相等“quite unrealistic”，因此转向寻找离观测 assignment 最近的 global section，并用 consistency radius 衡量失真。

这引出三项不能隐藏的额外原语：

1. 每个局部观测空间的距离/伪距离；
2. 不同来源/字段怎样加权；
3. 没有可接受全局 section 时是拒绝、保留冲突，还是强制投影。

在临床系统中，默认取 nearest global section 可能把真正的病例混淆、单位错误或时间错位“修正”为一份看似一致的患者。`R-UNC-01` 要求保留冲突，因此更安全的默认是：presheaf assignment + inconsistency witness 为一等输出；是否融合由任务规则明确决定。

### 5.3 最坏失败：错误 topology 得到完美一致

若 site 的覆盖没有把两个应比较的记录放在有重叠的上下文中，它们永远不会冲突；若 restriction 错把两位同名患者或两种测量方法投影为同一实体，它们会被强制粘合。Sheaf 只能保证**相对于给定 topology/restriction 的一致性**，不能验证 topology 是否医学正确。

### 5.4 时间能力的边界

Schultz 等以闭时间区间为 site，section 表示区间上的信号/行为，restriction 是截短，因而非常适合连续/离散轨迹的拼接。但本项目至少有：

- 事件/有效时间；
- 采集时间；
- 结果可见/知识时间；
- 记录时间；
- 过期时间；
- 规则/模型版本时间。

单一 interval sheaf 不能自动区分这些。可以把 base 扩成 event-time × knowledge-time 的积 site，或把 bitemporal event log 放在 sheaf 外；无论哪种都增加明确原语。若只把所有时间都投到一个 interval，`R-TIME-01` 仍失败。

## 6. 共病组合与治疗/观察分离

### 6.1 开放系统的优势

开放组件能自然把以下三条路径拆开：

```text
therapy ──→ latent physiology dynamics
therapy ──→ observation channel / test sensitivity
latent physiology + measurement context ──→ observed value
```

因此“抗菌药降低病原负荷”和“抗菌药使培养更易阴性”可以是两个可追踪输出，而不是把阴性培养直接解释成无感染。升压药、高流量氧、退热药、β 阻滞剂也可沿同一结构表达。这是本家族对 `R-OBS-02`、`R-INT-02` 最实质的贡献。

### 6.2 仍需显式类型和状态机

把治疗当输入端口不区分：计划、下单、配药、开始、实际输注、暂停和停止。只有 `executed administration event` 能驱动患者状态；其余是工作流/意图。若所有动作都接到 `therapy_input`，开放系统会忠实执行错误语义。因此 `R-INT-01` 仍需独立动作类型和实施状态机。

### 6.3 非线性交互必须可复用且可拒绝

`CKD` 改变药物清除、两个 QT 延长药共同提高风险、感染与免疫抑制共同压低发热反应，都不能由普通 tensor 自动推出。可接受的组合契约是：

```text
compose(A, B, interactions=known_mechanism_components)
if required interaction semantics is absent:
    return UnsupportedComposition(...)
```

而不是：

```text
f_total = f_A + f_B  # 无条件默认
```

## 7. 多任务读出：函子有用，但 black box 可能过度遗忘

### 7.1 最小形式

对每项任务 `τ`，可以尝试定义：

```text
R_τ: C_clinical → D_τ
```

其中 `C_clinical` 是开放组件/行为类别，`D_τ` 是诊断坐标、安全约束或预后分布类别。若 `R_τ` 保持组合，则不同层级的模型能复用同一读出逻辑。Baez 等对电路、Markov 过程、反应网络给出了特定稳态语义下真正可证明的 black-box functor，说明这种想法不是空话。

### 7.2 临床任务不一定保持严格组合

两个单独用药各自“安全”，合用却可能因同一通道、清除或 QT 风险而不安全。若强行要求：

```text
Safety(A ⊗ B) = Safety(A) ⊗ Safety(B)
```

就会漏掉交互。可行选择是：

- 先把显式交互组件接入完整系统，再读出；
- 让读出是 lax monoidal，允许合并时新增交叉结构；
- 或承认该任务读出非局部，不能从局部摘要拼得。

“读出是函子”必须成为待验证假说，而非架构公理。

### 7.3 传统 black-boxing 与审计的冲突

Black-boxing 的目的正是忘掉内部结构、只保留边界行为。临床审计要求每个坐标 100% 追到原始证据和规则版本。若诊断读出只返回边界关系而丢掉内部 witness/derivation，就违反 `R-PROV-01`。

原型若采用读出函子，target 必须至少携带：

```text
(value_or_distribution, evidence_ids, rule_versions, unresolved_conflicts, assumptions)
```

并验证 composition 时 trace 不丢失、同源 evidence 不增殖。可以称为 trace-preserving semantics；不能直接复用“忘掉内部”的 black box 作为最终任务输出。

### 7.4 扩展爆炸半径可能转移到每个任务

新增药物组件可以做到核心解释器 0 修改，但诊断、安全、预后、科研四个 readout algebra 可能各需新增解释。如果新概念总要改所有任务代码，核心 blast radius 虽为 0，`S-AUTH-01` 仍很差。应分别统计：

- core engine modifications；
- component knowledge files；
- interaction modules；
- task algebra/readout modules；
- migration/compatibility adapters。

## 8. 对统一压力测试的预期表现

图例：`N`=该结构原生提供；`C`=选对具体 algebra/type/site 后可提供；`E`=必须外加独立机制；`F`=若仅用该结构会硬失败。

| 压力测试群 | 裸范畴 | Operad/开放机器 | Structured cospan | Sheaf/presheaf | 说明 |
|---|---:|---:|---:|---:|---|
| 1–5 支持治疗掩蔽观察 | F | C | E | C | 开放机器可拆 state/observation；sheaf 可保留条件，但动力学需另加 |
| 6 同一体温三种改写去重 | F | E | E | E | 没有一个结构原生提供 evidence identity/依赖集合 |
| 7 fever/CRP/WBC 共享来源 | F | C/E | E | E | 可建共享机制组件，但评分依赖仍要联合语义 |
| 8 同表型多机制 | F | C | E | C | relation/Dist algebra 或多个局部 section 可保留多解 |
| 9 同病异表现 | F | C | E | C | 取决于具体行为/概率 algebra，不是 wiring 性质 |
| 10 冲突记录 | F | E | E | N | presheaf assignment 可留下 gluing obstruction；仍不能自动裁决 |
| 11 未提症状 | F | E | E | E | 无 section 不能区分未询问、未检查与不存在，需 epistemic ADT |
| 12–13 晚到结果/未来泄漏 | F | E | E | C/E | interval sheaf 管有效区间；知识时间需第二轴或 event log |
| 14 同肌酐不同基线 | F | C | E | C | 前提是 baseline/context 是 typed input，不是裸数值 |
| 15 两任务不同坐标 | E | C | E | C | functor/sheaf morphism 可表达；需保 trace 且不回写事实层 |
| 16 共病非线性交互 | F | C | E | E | 必须显式 interaction/shared state；tensor 不自动产生 |
| 17 治疗改状态也改观察 | F | N/C | E | C/E | 开放机器最自然；sheaf 只表示上下文/行为关系 |
| 18 自然病程 vs 治疗作用 | F | C | E | C | 需因果/概率语义；组合语法不识别反事实 |
| 19 观察过期 | F | E/C | E | C | 时间 section 可限制，但过期政策与知识时间另定义 |
| 20 模型外疾病 | F | E | E | E | 不存在 global section 也可能是数据冲突/建模错误，不能等同 OOD |
| 21–22 新药/新检查局部扩展 | F | N/C | N/C | C | 接口稳定时核心修改可为 0；任务 algebra 仍可能要改 |
| 23 新理论重释旧证据 | F | E | E | E | 需要知识版本与 immutable evidence log |
| 24 删除证据递归失效 | F | E | E | E | 需要 truth maintenance；restriction 不是依赖撤回 |
| 25 as-of 历史回放 | F | E | E | C/E | 仍需 availability time、规则版本与确定性执行 |
| 26 安全规则不得靠检索 | F | E | E | E | 应由 invariant engine/typed contract 执行 |
| 27 独立来源 vs 多次改写 | F | E | E | E | site 上不同局部来源仍不等于统计独立性 |
| 28 多解释并存 | F | C | E | C | 选择 Rel/Dist/sets-of-behaviors 语义，而非确定函数 |
| 29 无法表达显式报错 | E | C | C | C | 精确 port/site schema 可拒绝；粗类型仍会静默错接 |
| 30 自然语言改写不变 | F | E | E | E | 属于术语/输入适配契约，组合数学不解决 |

**硬结论：**本家族单独不能通过当前 `REQUIREMENTS.md`。它最强的是 `R-COMP-01`、条件性满足 `R-COMP-02`、`R-OBS-02` 和 `R-TASK-01`；证据守恒、双时间、撤回、开放世界必须由其他固定语义补齐。

## 9. 原语、特例和扩展成本账本

| 版本 | 不可隐藏的最小 signature | 主要补丁压力 | 核心扩展半径 | 最坏失败 |
|---|---|---|---|---|
| 裸对称幺半范畴 | objects、morphisms、id、compose、tensor、unit/symmetry/coherence | 几乎所有临床语义 | 看似 0，实为未定义 | 把错误模型证明成“组合一致” |
| Colored operad + algebra | colors、multi-operations、identity、substitution、permutation；每种语义一个 algebra | 反馈、共享状态、跨 algebra 转换、interaction boxes | 接口稳定时 engine=0；algebra/readout 需扩展 | well-typed but medically wrong wiring；交互盒平方爆炸 |
| Structured cospan | `A,X,L`、两条 legs、pushout compose、coproduct tensor；动态 decoration | 方向、时间、随机/因果、实体身份 | 网络拓扑扩展优 | pushout 错误识别不同临床实体/层次 |
| Open dynamical machine | typed ports、state、update relation/kernel、readout、wiring；反馈良定性契约 | action lifecycle、epistemic state、provenance、OOD | 新组件通常 engine=0 | 无延迟反馈无解/多解；乘积状态重复同一患者 |
| Sheaf/presheaf | site/cover、sections、restriction、gluing；若噪声再加 metric/optimization | topology 设计、bitemporal、provenance、非线性融合 | 新局部域可较局部 | 错 site 产生伪一致；nearest global section 擦掉真实冲突 |
| 组合外壳 + 全部安全语义 | 上述开放组件再加 bitemporal events、evidence DAG、epistemic ADT、versioned readouts | 实现/审核负担高 | 有希望达到 engine=0 | “最小范畴内核”名义下实际藏了一个复杂混合架构 |

## 10. 建议进入原型的最小版本

这不是最终选择，只是本家族中最有判别力的实验对象：

```text
1. Typed interface
   Port = (semantic_id, epistemic_role, direction, value_type,
           unit, subject_identity, context_contract, clock_contract)

2. Open behavior component
   Component = (ports, private_state_schema, behavior_relation,
                assumptions, version)

3. Composition
   operadic wiring / structured boundary gluing
   + explicit interaction components
   + feedback well-posedness validator

4. Task readout
   versioned trace-preserving maps, not trace-erasing black boxes

5. External capabilities that must be counted as core if required
   bitemporal immutable event/evidence log
   epistemic-state ADT
   provenance/truth-maintenance DAG
   unsupported/out-of-model result types
```

### 10.1 最小判别病例

建议只用一个很小但能击穿抽象宣传的组件图：

1. `shock physiology`：潜在灌注状态；
2. `vasopressor administration`：只有实际给药事件才能输入；
3. `BP measurement`：输出 MAP，携带给药条件与时间；
4. `inflammation mechanism`：共同输出 temperature/CRP/WBC；
5. `sepsis` 与 `CKD`：共享 renal physiology，不得各复制一份 creatinine；
6. `drug clearance interaction`：非线性、未提供时组合明确失败；
7. `diagnosis readout` 与 `medication-safety readout`：输出不同坐标，trace 指向相同原始证据。

### 10.2 必跑断言

- 不同括号分组组合得到同构行为和同一 evidence identity；
- 新增一个药物组件时 core engine 修改数为 0；
- 未声明必要交互时返回 `UnsupportedComposition`，不默认相加；
- 无 delay/inertia 的反馈被 validator 拒绝；
- 同一体温派生三种标签后，独立证据数不增加；
- 两个 task readout 不回写事实层且均保留完整 trace；
- 撤回原始体温后所有仅依赖它的输出失效——预计这会证明 operad/sheaf 本身不足，必须由 truth maintenance 层完成；
- 两个上下文冲突的测量形成 inconsistency witness，而不是被 nearest-section 默认平滑。

### 10.3 判断“真的压缩”还是“换术语”的淘汰指标

出现任一项，应降低或淘汰本候选：

1. 每加一个 disease pair 都要一个专属 glue/interaction；
2. port type 数量和原 axes 一一对应，但合法连接仍靠自由文本/LLM 判断；
3. 每个新概念都要修改所有 task readout 代码；
4. evidence/replay/unknown 等大部分语义由另一个系统承担，而报告仍声称“operad 是固定核心”；
5. 为通过反馈测试不断添加 ad hoc delay，而无统一 well-posedness contract；
6. sheaf topology/restriction 由病例结果反向调到能粘合；
7. black-box readout 丢失 provenance；
8. 组合后产生重复共享状态，靠名字去重。

## 11. 最强反对意见与推翻条件

### 对当前保留判断的最强反对意见

把开放系统/operad 仅称为“外壳”可能低估了它的约束价值：如果状态、观察、治疗和任务本来就都可表示为同一类 typed time-based machine，那么 sheaf machine algebra 也许能把看似外加的多种能力纳入一个统一结构，而非混合拼装。

### 为什么现在仍不能据此选它为核心

现有第一手成果展示了系统互连、时间行为、稳态 black-boxing 和局部到全局一致性；尚未展示以下组合在同一小内核内成立：

- 双时间 as-of replay；
- 证据 identity、同源去重与递归撤回；
- 计划/实施动作生命周期；
- 临床信息状态代数；
- 开放世界拒绝；
- trace-preserving 多任务读出；
- 共病共享状态与非线性交互的可扩展知识工程。

### 会提升该候选地位的证据

1. 一个不靠病例专属规则的参考实现，通过全部硬性压力测试；
2. 新疾病/药物/检查各自核心修改数为 0，且 task readout 修改有可证明的局部上界；
3. 反馈、共享状态和交互组合有统一的静态 validator；
4. provenance/truth maintenance 可作为同一 algebra 的自然组成且不会增殖 evidence identity；
5. 与事件溯源/类型化规则候选相比，以更少 signature 和更低人工审核负担达到同等 trace/replay 正确性。

### 会淘汰该候选作为核心、只保留为文档语言的证据

1. 原型的大多数安全语义仍来自独立 event/provenance/rule engine；
2. 核心组合只覆盖线性或无交互子集，真实共病大量落入专属 glue；
3. port refinement/type registry 成为新的全局语义瓶颈；
4. sheaf 近似融合在冲突或错误上下文测试中产生静默“共识”；
5. task readout 无法既保持组合又保留完整 evidence trace。

## 12. 给候选总表的建议表述

**候选名：**类型化开放组合系统（operadic wiring / structured cospan；可选 temporal sheaf behavior）  
**定位：**强组合外壳，非完整证据语义  
**当前状态：**保留进入小型判别原型，但不得先验成为赢家  
**天然解决：**局部组件互连、层级组合、接口化扩展、状态/输入/输出分离、条件性的任务读出复用  
**必须补齐：**双时间事件、证据血缘/撤回、信息状态、动作生命周期、开放世界、trace-preserving readout、反馈良定性、共享状态/交互  
**最坏失败：**把语义错误的组件组成一个数学上完全 coherent 的系统；或以大量专属 port/interaction/readout 把原来的特例换名隐藏  
**本轮 Pareto 判断：**在 `局部可组合性/核心执行分支稳定` 上很强，在 `证据守恒/历史重放/显式未知` 上弱；sheaf 在 `局部冲突/时间行为` 上强，但在 `因果干预/临床融合安全` 上弱。当前证据支持把它们放入 Pareto 前沿调查，而不支持单独选为固定核心。
