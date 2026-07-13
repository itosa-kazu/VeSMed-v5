# 候选家族研究：向量/张量、动态贝叶斯网络/因子图、状态空间/POMDP/控制

> **研究阶段**：候选调查与统一预判；不是最终决策，也不把现有 V5 设计当作答案。  
> **调查日期**：2026-07-13。  
> **边界**：这里只比较三组候选家族。输入适配、事件存储、概率推断、控制优化可以组合，但不能把一个家族没有的语义偷偷借给它后仍称为“原生能力”。

## 0. 比较口径与防止“能力借用”

### 0.1 记号

- **N（native）**：候选的标准原语直接给出该语义；只需填写领域模型/参数，不需新增另一种核心对象。
- **P（patch/companion）**：可以实现，但必须增加伴随层、额外类型或更强变体；该项不能记作原候选的天然优势。
- **F（vanilla failure）**：朴素/标准候选会违反测试不变量；若用补丁修好，架构身份已经实质改变。
- **O（outside but gated）**：主要属于输入适配层，但核心必须用契约/校验门拒绝不合法输入，不能完全推给 LLM。
- `N*`：只有显式采用表中所写的受控、因果化、分解化或非线性变体才成立；例如普通贝叶斯网络的条件概率不能自动冒充干预语义。
- `A/B` 复合标记：斜线前是该家族某个数学子能力，斜线后是端到端不变量的结论；例如 `N/P` 表示 filtering 数学原生，但要保证 as-known replay 仍需补事件门。

### 0.2 三个不能混同的层级

1. **数组可编码任何东西，不等于数组定义了语义。** 给数组无限加通道，确实能塞进来源、时间、状态、概率和动作；但若合法关系、更新、失效、血缘、不变量都由外部程序定义，固定核心其实是那个外部程序，不是数组。
2. **因子图不等于动态/因果模型。** 因子图原生表达“全局函数如何分解为局部函数”以及边缘化计算；时间、生成方向、干预、行动、效用必须来自 DBN、因果 BN 或影响图等额外语义。
3. **状态空间模型不等于 POMDP。** SSM 给出潜在状态、转移和观察；POMDP 再增加行动、行动条件转移/观察、效用和策略。约束安全、因果可识别性、事件血缘仍不是自动获得的。

---

## 1. 传统高维向量或张量状态

### 1.1 最小形式

最朴素形式是某时刻患者向量

\[
x_t=(x_{t,1},\ldots,x_{t,d})\in\mathbb{R}^d,
\]

或带患者、时间、特征、上下文等 mode 的多维数组

\[
X\in\mathbb{R}^{N_{patient}\times N_{time}\times N_{feature}\times N_{context}\times\cdots}.
\]

Kolda 与 Bader 的权威综述把 tensor 定义为 multidimensional / N-way array，并讨论 CP、Tucker 等分解；这能说明数组及低秩分解的数学能力，但**不提供临床事件、证据、干预或时间可见性的语义**。[S1] Deep Patient 是高维 EHR 表示经过无监督学习得到通用患者表示的真实例子，证明这一路线适合预测表征；它没有证明该向量可以作为可审计临床世界模型内核。[S2] Limestone 则证明 patient×diagnosis×medication 等多源张量分解可用于候选 phenotype 生成；它支持“张量擅长统计共现”，并不把 factor 自动赋予病理机制语义。[S23]

### 1.2 统一问题回答

| 问题 | 向量/张量候选的回答 |
|---|---|
| 基本原语 | 坐标、数值、数组 shape；常见附属物是 mask、embedding、距离/相似度、线性或神经读出。 |
| 状态放在哪里 | 一个向量/张量切片。最朴素实现把记录到的观测直接当“状态”；若另设 latent vector，则生成/解释语义由外部模型提供。 |
| 时间 | 作为额外 mode、固定时间桶、位置编码或窗口。多时钟、异步事件、有效期并非数组自身语义；不规则时间常被分箱、插值或改成 ragged/event 表示。 |
| 观察 | 写入某坐标；缺失常由 mask/特殊值/插补表示。若没有强类型，`0`、阴性、未检查、未询问、无效和不适用容易碰撞。 |
| 干预 | 作为额外特征/通道；要表达 `x_{t+1}=F(x_t,u_t)` 或干预同时改变观察映射，就已引入状态空间/因果模型。 |
| 不确定性 | 额外均值/方差/置信度通道、分布参数或 ensemble；普通点向量没有不确定性语义，更没有“冲突/不适用/模型外”等认识论类型。 |
| 共病 | 拼接、相加、Hadamard/张量积或交给任意非线性函数；没有哪一种是天然正确的组合律，也不保证局部扩展。 |
| 证据血缘 | 不原生保存。必须另存 source/event ID、派生图或 event log；池化/embedding 后通常不可逆。 |
| 新知识扩展 | 新增坐标/mode。固定 shape、训练权重、相似度和下游模型往往同时变化，blast radius 大；稀疏 registry 能减轻但不是数学保证。 |
| 任务坐标 | 这是其最强项：切片、投影、metric learning、task head 都很直接；但不同任务需要不同投影，不能把一个距离当万能临床相似度。 |

### 1.3 天然优势

- 数值计算、稀疏存储、GPU/线性代数生态成熟；批量比较和临时任务投影便宜。
- 对已定 schema、已定时间窗、已定预测任务，工程基线简单且可量化。
- 张量保留多个 mode，比把所有内容先展平成单向量更少丢结构；低秩分解可发现共变模式。[S1]
- 向量是很好的**计算视图/缓存/模型输入**，即使它不是事实和语义的唯一保存层。
- 同一时间序列接多个 task head 是成熟工程路线；真实 ICU benchmark 已用共享临床时间序列同时做死亡、失代偿、住院时长和 phenotype 等任务。[S25]

### 1.4 必须补的东西

至少要外加：强类型事件、状态/观察/推断/计划/已执行动作分离、多时钟、来源与派生 DAG、显式缺失代数、状态转移/观察模型、因果干预、模型版本、开放世界/OOD、硬安全约束和 schema error。GRU-D 的原始工作本身就要在 `T×D` 临床时间序列外显式增加 missing mask 与 time interval，说明“多一个数组维度”不是完整缺失语义。[S24] 补完上述全部对象后，“核心”已经不再是向量。

### 1.5 最坏失败

最危险的不是报错，而是**语义碰撞后仍能输出高置信数字**：升压药下正常血压与未治疗正常血压落在同一点；未提及被填成 0；同一体温的三个同义派生特征被当三票；embedding 忘掉来源，删除原始事实也无法撤回推断。EHR 概念的统计关联还会随 healthcare process events 改变，[S27] 所以 latent factor 可能混入照护流程，而非纯生理机制。这个家族会产生低表面复杂度、高静默错误率。

---

## 2. 动态贝叶斯网络（DBN）与因子图

### 2.1 最小形式与家族边界

DBN 把时间片内/跨时间片的随机变量依赖写成局部条件分布，例如

\[
p(x_{0:T},o_{0:T})=p(x_0)\prod_{t=0}^{T}p(o_t\mid x_t)
\prod_{t=0}^{T-1}p(x_{t+1}\mid x_t).
\]

状态可分解为多个变量，而不是一个枚举状态。Murphy 的博士论文明确说明 DBN 以 factored state 推广 HMM，并允许比线性高斯 Kalman 模型更广的分布。[S3]

因子图写成

\[
F(z_1,\ldots,z_n)=\prod_a f_a(z_{N(a)}),
\]

变量节点与局部函数节点构成二部图；sum-product 利用局部分解计算边缘函数，在树上精确，在有环图上可能只能近似。[S4] 因此本节实际评分对象是**“DBN 的概率/时间语义 + 因子图的局部分解与推断”**。只给一张无向因子图，不能领取时间和干预能力。

### 2.2 统一问题回答

| 问题 | DBN/因子图候选的回答 |
|---|---|
| 基本原语 | 有类型/有域的随机变量、局部因子或条件概率核、图边、证据赋值、时间片模板；影响图再加 decision/utility。 |
| 状态放在哪里 | 某时间片隐藏变量的联合赋值；系统知识态是其 posterior，而不是患者真实状态本身。 |
| 时间 | 标准 2-slice DBN 重复离散模板。CTBN 以局部连续时间 Markov 跳变强度表达“何时跳、跳到何值”，可处理连续时间事件，但仍只有过程时间，不自动包含采集/可见/记录/有效/过期等知识时钟。[S5] |
| 观察 | 观测节点或证据因子；未观察即不施加该 likelihood，所以“未提及≠阴性”较自然。要区分未问、未查、不适用、冲突等仍需显式类型/变量；而且只有在 missingness 可忽略的假设成立时，单纯边缘化缺失才无偏，informative missingness 必须建模。[S19] |
| 干预 | 普通 DBN 只给条件分布。要解释 `do(a)`、反事实或行动选择，需因果 DBN/SCM 或影响图；观察到治疗与实施治疗不是同一个运算。[S13][S14] 影响图明确增加 decision/utility 节点，不能把这两个原语算作裸 BN 自带。[S20] |
| 不确定性 | 联合分布、边缘 posterior、MAP、多峰解释原生；但单一概率分布不自动区分 aleatory、epistemic、数据冲突、模型不适配。 |
| 共病 | 共享变量、潜在共同原因、交互因子和跨时耦合都可局部写出，非线性交互可用任意因子；代价是 treewidth/状态基数爆炸。 |
| 证据血缘 | 图结构说明“哪些模型因子依赖哪些变量”，但消息或 posterior 不是事实级血缘。必须让每个证据因子携带不可变 source/event ID，保留派生关系和版本。 |
| 新知识扩展 | 理想上添加变量/局部因子；但域扩张会改变 CPT 归一化，junction tree/缓存/近似器可能全局重建。只有定义模块接口与边界变量后，blast radius 才可控。 |
| 任务坐标 | posterior marginal、conditional、MAP、expected utility 都是自然 query；不同任务可查询不同变量/效用，无需唯一距离。 |

### 2.3 天然优势

- 共享炎症机制导致发热、CRP、白细胞变化，可用一个 latent parent 到三个观测，而非三项朴素独立投票。
- 同一表型由不同机制产生、同一疾病有不同亚型、多个候选同时保留，都可由多峰 posterior / mixture / hierarchical variables 表达。
- 缺测作为“无 evidence factor”处理自然；动作、状态、观察若显式建成不同节点，认识论分离比平面向量强。
- 因子分解提供局部知识单元和统一消息传递；Kschischang 等证明许多看似不同的算法（含 forward-backward、Kalman filter）可视为 sum-product 实例。[S4]

### 2.4 必须补的东西

- **因果/行动语义**：条件相关不等于干预；Pearl 的工作说明从非实验数据识别因果效应需要可检查假设。[S13] Murphy 的动态治疗制度同样显式依赖 potential outcomes 和识别假设，而不是把观察到的治疗直接当动作核。[S14]
- **事件与知识时间**：过程时间片不能替代 `occurred/collected/available/recorded/valid/expires`。FHIR Observation 甚至把临床有效时间 `effective[x]` 与结果可供医务人员使用的 `issued` 分开。[S15]
- **血缘与可撤回**：每条证据必须保留独立 factor identity、来源及派生边；压缩后的 posterior/消息不能回答“删掉哪条原始证据后哪些结论失效”。FHIR Provenance 也把 entity、activity、agent、occurred、recorded 和 versioned target 当独立记录。[S16]
- **开放世界、模型错误与硬安全**：固定变量集合天然闭世界；需 null/unknown/model-discrepancy、schema failure、约束动作/形式规则层。

W3C PROV-DM 的 entity–activity–agent 与 derivation 模型可作为第一手血缘参照。[S21] 数据库 provenance semiring 证明“把注释沿代数运算传播”有形式化路径，[S22] 但把 probability semiring 与 provenance 组合会改变计算代数，而且仍不自动补齐临床多时钟、动作本体和失效规则；因此不能倒算为普通 factor graph 的原生能力。

### 2.5 计算边界与最坏失败

Cooper 证明一般 Bayesian belief network 的概率推断是 NP-hard。[S6] 因子图在低 treewidth/局部结构上非常有利，但复杂共病交互会形成大 clique 或 loopy graph；近似消息传递可能不给可靠误差界。

最坏失败是**结构错而后验极其自信**：把同一体温的三个改写当三个条件独立 evidence factors；遗漏共同原因；把治疗选择中的混杂关系当药效；在 loopy approximate inference 下仍返回看似精确的概率。图的可视性帮助审计，但并不保证图正确。

---

## 3. 状态空间模型、部分可观测系统、POMDP 与控制

### 3.1 最小形式与家族层级

离散时间受控状态空间骨架为

\[
x_{t+1}\sim T(\cdot\mid x_t,a_t),\qquad
o_t\sim Z(\cdot\mid x_t,a_{t-1},c_t).
\]

其中 `x_t` 是患者可能存在但不可直接见的状态，`o_t` 是实际观测，`a_t` 是已实施动作，`c_t` 是测量条件。知识态为

\[
b_t(x)=P(x_t=x\mid o_{\le t},a_{<t},\text{available by }t).
\]

Kalman 1960/1961 的线性高斯过滤工作奠定了状态转移、观测、估计误差协方差和递推过滤的经典形式。[S7][S8] Smallwood–Sondik 与 Kaelbling–Littman–Cassandra 给出有限 POMDP 的隐藏内部状态、概率观察、belief state、行动和策略/价值框架。[S9][S10]

应分别记账：

- **线性高斯 SSM**：`x'=Ax+Bu+w, y=Cx+v`；简洁可解，但对离散事件、多峰疾病机制和非线性交互很受限。
- **非线性/混合/连续时间 SSM**：允许 SDE、离散 mode、非高斯噪声和不规则观测；表达强但推断近似化。
- **POMDP**：在生成模型上增加 action、reward/cost、policy；才开始回答“下一步做什么”。
- **因果/约束 POMDP**：再加入可识别干预语义和安全约束。普通 reward 大惩罚不等同于可证明安全；受约束 POMDP 是额外模型家族，[S17] 甚至最新工作显示普通 C-POMDP 的跨时约束可出现对安全关键应用不理想的时间不一致行为。[S18]

### 3.2 统一问题回答

| 问题 | SSM/POMDP/控制候选的回答 |
|---|---|
| 基本原语 | latent state、action/control、transition kernel/dynamics、observation、observation kernel、initial belief；POMDP 再加 objective/reward、policy。 |
| 状态放在哪里 | 患者真实状态是假定存在的一条隐藏过程；belief/particle cloud 是系统对它的不确定性，二者原生分离。 |
| 时间 | 标准模型为离散步；连续时间 ODE/SDE、jump/hybrid、semi-Markov 可扩展。过程时间仍不等于结果可见时间和记录时间，后两者需事件层。 |
| 观察 | 由隐藏状态经有噪声、可受动作/测量上下文影响的 `Z` 生成；“正常观察≠内部正常”是该家族最天然解决的问题。 |
| 干预 | `a_t` 改变 transition；若 `Z` 也依赖 action，治疗还可改变表现/可观测性。POMDP 统一检查动作与治疗动作。参数从观察数据学习时仍有因果识别问题。[S13][S14] |
| 不确定性 | 转移噪声、观测噪声、参数后验和 belief 原生；但认识论状态枚举、冲突、模型外仍需类型与 model discrepancy。 |
| 共病 | 状态因子化、多个 mode、耦合非线性 drift/transition；能表达非加性交互，但组合律与模块边界不是标准 SSM 自动给出的。 |
| 证据血缘 | belief 对未来决策可是充分统计量，但不是审计充分统计量。过滤递推压缩历史后，不能无损解释每个 posterior 坐标来自哪些原始事件，也难以删除任意旧证据。 |
| 新知识扩展 | 新药增加 action/effect model，新检查增加 observation channel，新病增加 latent mode/transition。固定矩阵/固定状态集会全局变形；只有 factored/compositional plugin 规范才局部。 |
| 任务坐标 | 对同一 belief 定义不同 readout、loss/reward、约束或 policy；诊断、严重度、安全、预后可用不同投影，不需唯一距离。 |

### 3.3 天然优势

- **观察—真实状态分离最直接**：支持下正常血压/血氧、药物掩蔽发热/心率、抗菌药后培养阴性，可由动作同时影响 `T` 与 `Z` 表达。
- **时间和过期自然**：旧观察在其发生时更新 belief，随后经 dynamics 前推；随着过程噪声累计，不确定性自然扩大，而不是把旧值永远当当前值。
- **诊断—治疗交错**：POMDP 可同时评价获取信息的检查动作与改变患者的治疗动作。Hauskrecht 与 Fraser 的缺血性心脏病工作明确以此为医学优势，同时也报告精确求解实际上只适合小问题。[S11]
- **多个解释并存**：belief 可多峰；filter、prediction、counterfactual simulation 和任务 readout 使用同一生成骨架。

### 3.4 必须补的东西

1. **事件溯源和双/多时钟**：标准过滤只按收到的 observation 更新；要做合规 replay，必须保留 observation 的发生/采集/available/recorded/valid/expires、模型版本和 action actual/planned 类型。[S15][S16]
2. **可撤回血缘**：belief compression 不可替代 provenance DAG。任意旧证据删除通常需要从 checkpoint 前重放，或保留完整 factorization/dependency graph。
3. **因果识别**：定义 `T(x'|x,a)` 是模型声明，不代表观察性 EHR 已识别该药的因果效应。需要试验、可检验 causal assumptions、potential outcomes/SCM 等。[S13][S14]
4. **开放世界**：固定 latent state/action/observation space 会把新病投影到最接近的已知状态。open-set recognition 文献明确把未知类别风险与 closed-set 分类分开。[S26] 必须有 health/null、unknown/model discrepancy、OOD 和明确拒答；一个枚举的 `UNKNOWN` 只能是保护槽，不等于无限可扩展语义。
5. **局部组合接口**：任意大 `f(x,a)` 或 `T` 虽能表达一切，却会成为单点语义瓶颈；需规定机制模块的读写集合、交互项、优先/冲突和组合律。
6. **硬安全**：reward shaping 不能保证罕见禁忌永不被近似策略违反；需要显式 action constraint/temporal invariant，且执行不依赖检索召回。[S17][S18]

### 3.5 计算边界与最坏失败

Papadimitriou 与 Tsitsiklis 证明部分可观测版本的相关策略计算问题为 PSPACE-complete；不能把“POMDP 表达统一”误写成“可精确扩展到全临床”。[S12] Kaelbling 等同样把精确求解复杂度与近似作为核心问题。[S10]

最坏失败是**模型错误经过控制回路被放大**：遗漏了重要历史使所谓 state 不满足 Markov 性；错误 observation kernel 把治疗掩蔽当病情改善；由混杂数据学出的 action effect 被当因果；固定闭世界 belief 仍归一化为 100%；错误 reward 促成危险策略。与向量的静态碰撞相比，这里错误会主动改变未来数据分布。

---

## 4. 30 项统一压力测试的预判

> 本表评价“候选家族本身”。`P` 不是说做不到，而是说完成后必须把补丁计入核心原语、special-case count 和 extension blast radius。对 DBN 的 `N*` 默认要求状态、动作、观察节点显式分型；对 SSM 的 `N*` 默认要求非线性/混合或 factored 版本，而非线性高斯固定矩阵。

| # | 压力测试（简写） | 向量/张量 | DBN/因子图 | SSM/POMDP/控制 | 硬性判断与理由 |
|---:|---|---|---|---|---|
| 1 | 正常 BP + 大剂量升压药 | P | N* | N | 必须区分 latent perfusion/hemodynamics、观测 BP 与已实施 action；平面坐标会碰撞。 |
| 2 | 正常 SpO2 + 高流量氧 | P | N* | N | 同上；action-conditioned state/observation 是关键。 |
| 3 | 无发热 + 刚用退热药 | P | N* | N | 药物可同时改状态轨迹和外显；不能把 afebrile 当无炎症。 |
| 4 | 正常 HR + β 阻滞/固定起搏 | P | N* | N | 需设备/药物上下文进入 observation mechanism。 |
| 5 | 培养阴性 + 采样前抗菌药 | P | N* | N | 时间先后和 action-dependent sensitivity 必须入模型。 |
| 6 | 一次体温派生三标签不得三票 | F | P | P | 概率/状态模型也不会自动知道三项同源；必须有 source lineage 与 deterministic derivation。属证据守恒硬测试。 |
| 7 | 发热/CRP/WBC 共享来源 | P | N | N | covariance/低秩 factor 可作统计补丁，但不能保证共同病理来源；显式 latent common cause/factored dynamics 才有依赖语义。 |
| 8 | 同表型、两机制 | F | N | N | 相同 observed vector 是同一点；要同时保留两个机制假说需外部 latent hypothesis/generative model。 |
| 9 | 同病异质表现 | P | N | N | hierarchical/subtype/random effects 或多模态 trajectory。 |
| 10 | 两记录冲突 | P | P | P | source mode/噪声模型可补上，但“显式保留冲突、来源与可靠度”仍需事件类型。 |
| 11 | 病历未提某症状 | P | N | N | DBN/SSM 无 observation 就不更新；向量必须防止默认 0。若要细分未问/未查仍全都需 typed status。 |
| 12 | 采样后数小时才可得 | P | P | P | 可增加多个 time mode，但过程时间不等于 knowledge time；需 `collected` 与 `available/issued` 事件字段。 |
| 13 | 最终诊断不得进入过去判断 | P | N/P | N/P | 双时态 tensor 可补；filtering 本身可只用过去，smoothing 会用未来；都必须用 as-of API + available-time event log 强制选择。 |
| 14 | 同肌酐、不同个人基线 | P | N | N | patient parameter/background latent/context variable 可原生调制 likelihood。 |
| 15 | 同患者、两个任务坐标 | N | N | N | 三者都能做不同投影/query/readout；但向量底层语义仍可能错。 |
| 16 | 共病非线性交互 | P | N* | N* | arbitrary factor/nonlinear transition 可表达；计算和局部模块组合仍是重大权衡。 |
| 17 | 治疗同时改内部状态与观察方式 | F | N* | N | DBN 需 action 同时指向 state/observation；POMDP 的 `T`/`Z` 直接对应。仅加 treatment feature 不够。 |
| 18 | 改善可能自然病程或治疗 | F | P | P | 两者可建 counterfactual，但从观察数据归因需 causal identification，不能只靠条件概率。 |
| 19 | 旧观察过期 | P | N | N | 动态模型按 observation time 前推并增加不确定性；向量需手写 TTL/decay。法定有效期仍需事件字段。 |
| 20 | 新病不属已知模板 | F | F | F | 三种固定空间都闭世界；必须有 model-discrepancy/OOD/拒答。属开放世界硬测试。 |
| 21 | 新药只局部改知识 | F | P | P | 局部 factor/effect module 可实现，但标准固定 CPT/transition/action space 不保证小 blast radius。 |
| 22 | 新检查不改核心 | F/P | P | P | 通用插件式 observation contract 可做到；固定 shape/graph/kernel 仍需扩域和重建。 |
| 23 | 新理论重释旧证据 | F | P | P | 必须保留 immutable raw events、模型版本并 replay；posterior/vector 快照不够。 |
| 24 | 删除原证据，依赖推断全失效 | F | P | P | 需 source identity、dependency DAG 或从 checkpoint 重放；压缩 posterior/belief 不能任意“反更新”。硬血缘测试。 |
| 25 | 任意历史点只用当时已知 | P | P | P | 完整双时态 event tensor/ledger 可补；还需模型版本和 deterministic replay，filter 算法只是其中一部分。 |
| 26 | 罕见安全规则不靠检索想起 | F | P | P | 需 always-on hard constraint/形式不变量；普通 likelihood/reward 不等于保证。硬安全测试。 |
| 27 | 独立来源 vs 同源多改写 | F | P | P | 模型能表达 conditional dependence，前提是输入保留来源/派生关系；来源丢失后不可恢复。 |
| 28 | 多候选解释并存 | N | N | N | 向量可保留完整 non-exclusive score vector 而不 argmax；DBN/SSM 的 posterior/belief 更进一步给出概率语义。 |
| 29 | 无法表达必须显式报错 | P | P | P | 三者裸实现都倾向投影或忽略；strict schema/capability check + model failure 类型可补，但缺少即为硬失败。 |
| 30 | 换自然语言不应改核心状态 | O/P | O/P | O/P | 主要攻击抽取/标准化层，但核心必须只接收 canonical typed facts、保留原文并做等价输入 contract test。 |

### 4.1 不能由总分掩盖的硬失败簇

1. **血缘/回放簇（6, 12, 13, 23, 24, 25, 27）**：三家都需要持久事件/血缘语义。DBN/SSM 的“历史”与“posterior”不能替代审计历史。
2. **开放世界/能力错误簇（20, 29）**：三家标准形式都失败；给闭世界加一个 `unknown` 值只是 guardrail，不是开放词汇与未知机制的完整解法。
3. **安全簇（26）**：概率接近零、巨大负 reward 或向量阈值都不等于形式上的不可执行；必须有独立可验证 constraint semantics。
4. **因果归因簇（18，且影响 1–5、17）**：能模拟 action-conditioned transition 不等于从 EHR 识别了 action effect。

### 4.2 暂时的 Pareto 观察（不是选择）

- 向量/张量在计算成本、临时投影、生态上最强，但作为唯一事实内核时被大量硬测试击穿；它更像派生计算视图。
- DBN/因子图在局部依赖、共享来源、多解释和 query 上强；其主要风险是条件独立结构错误、因果语义借用、treewidth 和 provenance 缺口。
- SSM/POMDP 在“真实状态—观察—行动—时间—belief”骨架上最贴合前 5、17、19；其主要风险是固定闭世界、模型/奖励错配、血缘压缩、组合接口缺失和规划不可解。
- 目前的证据更像在提示**概率动态内核与事件/血缘/约束内核可能都不可省**，但这只是下一阶段应检验的假说，不能在三家调查未与其他候选正面对比前写进 DECISION。

---

## 5. 原语数量与“低原语假象”

以下只是最小语法盘点，不是加权评分：

| 家族 | 表面最小原语 | 为覆盖本任务通常还需 | 关键解释 |
|---|---|---|---|
| 向量/张量 | coordinate/value、array shape、projection | mask/status、event、clock、source、derivation、transition、observation model、action、uncertainty、constraint | 表面原语最少是因为把语义外包；不能据此称更优雅。 |
| DBN/因子图 | typed variable、factor/kernel、evidence、time template | action/utility、causal intervention、multi-clock event、source/derivation、unknown/error、constraint | 局部 factor 是真组合优势，但 provenance factor 与医学概率 factor 不应混成一物。 |
| SSM/POMDP | latent state、action、transition、observation、observation kernel、belief、readout/reward | multi-clock event、source/derivation、causal identification、module composition、unknown/error、constraint | 核心对象较多但分别对应不同本体；需要验证哪些能由更小代数统一而不丢语义。 |

---

## 6. 下一阶段最有区分力的原型实验

这些实验比继续写综述更能判别架构；三家必须使用同一事件和医学概念，不得给某家多配特例。

1. **支持治疗下的正常值**：输入 `vasopressor administered → BP measured normal`，分别输出 latent hemodynamic estimate、观测解释和血缘。检测观察/状态碰撞。
2. **同源三改写撤回**：一条温度 event 派生 fever/high-fever；证明只产生一份独立 evidence mass。删除原 event 后，三派生与所有结论必须失效。
3. **available-time replay**：标本 10:00 采集、14:00 发布；回放 12:00 与 15:00，前者不得使用结果。再在 2027 模型版本重释同一旧 event。
4. **新药 blast-radius**：新增只影响一个 mechanism 和一个 observation sensitivity 的药，统计核心文件、全局表、recompile/retrain/rebuild 数。
5. **未知病/无法表达**：给一个 atlas 外机制和一个 schema 外观察；候选必须区分“低 likelihood”“未知病”“输入无法表达”，不得归一化成已知 top-1。
6. **硬安全与近似推断**：加入极罕见禁忌，故意让语义检索不召回、让近似 posterior 有误；执行器仍必须拒绝动作。
7. **因果反例**：构造 indication confounding：病重者更常用药且结局更差。检验普通 DBN/SSM 是否把相关误学成伤害，因果扩展需公开其识别假设。

每个实验至少记录：核心原语数、额外特例数、extension blast radius、trace completeness、replay correctness、collision、silent-error、运行时间及近似误差声明。

---

## 7. 已核实的第一手/权威来源

> 链接均于 2026-07-13 访问核对。这里写“支持什么”，避免用来源为其未证明的架构结论背书。

| ID | 来源 | 本记录采用的证据范围 |
|---|---|---|
| S1 | Kolda TG, Bader BW. *Tensor Decompositions and Applications*. SIAM Review 2009. DOI: [10.1137/07070111X](https://doi.org/10.1137/07070111X) | tensor 是 N-way array；CP/Tucker 等分解与应用。没有临床语义主张。 |
| S2 | Miotto R, Li L, Kidd BA, Dudley JT. *Deep Patient: An Unsupervised Representation to Predict the Future of Patients from the Electronic Health Records*. Scientific Reports 2016. DOI: [10.1038/srep26094](https://doi.org/10.1038/srep26094) | learned patient vector/representation 可用于未来疾病预测的真实 EHR 实例；不证明可审计核心。 |
| S3 | Murphy KP. *Dynamic Bayesian Networks: Representation, Inference and Learning*. UC Berkeley PhD thesis, 2002. [Berkeley record](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2002/8174.html), [author page/full text](https://www.cs.ubc.ca/~murphyk/Thesis/thesis.html) | DBN 的 factored state、对 HMM/Kalman 模型的推广、精确/近似推断范围。 |
| S4 | Kschischang FR, Frey BJ, Loeliger H-A. *Factor Graphs and the Sum-Product Algorithm*. IEEE TIT 2001. DOI: [10.1109/18.910572](https://doi.org/10.1109/18.910572), [author-hosted PDF](https://www.isiweb.ee.ethz.ch/papers/arch/aloe-2001-1.pdf) | 二部 factor graph、全局函数的局部乘积分解、sum-product、树/环上的推断差异。 |
| S5 | Nodelman U, Shelton CR, Koller D. *Continuous Time Bayesian Networks*. UAI 2002. [author page and corrected PDF](https://ai.stanford.edu/~nodelman/papers/ctbn.html) | 有限状态连续时间、局部 transition intensity、事件序列生成语义和近似推断。 |
| S6 | Cooper GF. *The Computational Complexity of Probabilistic Inference Using Bayesian Belief Networks*. Artificial Intelligence 1990. DOI: [10.1016/0004-3702(90)90060-D](https://doi.org/10.1016/0004-3702(90)90060-D) | 一般 Bayesian network probabilistic inference NP-hard。 |
| S7 | Kalman RE. *A New Approach to Linear Filtering and Prediction Problems*. Journal of Basic Engineering 1960. DOI: [10.1115/1.3662552](https://doi.org/10.1115/1.3662552) | state-transition 方法、线性过滤/预测、估计误差协方差递推。 |
| S8 | Kalman RE, Bucy RS. *New Results in Linear Filtering and Prediction Theory*. Journal of Basic Engineering 1961. DOI: [10.1115/1.3658902](https://doi.org/10.1115/1.3658902) | 连续时间线性过滤、Riccati variance equation、估计与控制对偶。 |
| S9 | Smallwood RD, Sondik EJ. *The Optimal Control of Partially Observable Markov Processes over a Finite Horizon*. Operations Research 1973. DOI: [10.1287/opre.21.5.1071](https://doi.org/10.1287/opre.21.5.1071) | 隐藏内部 Markov 状态、概率观察、有限期 belief/value 结构。 |
| S10 | Kaelbling LP, Littman ML, Cassandra AR. *Planning and Acting in Partially Observable Stochastic Domains*. Artificial Intelligence 1998. DOI: [10.1016/S0004-3702(98)00023-X](https://doi.org/10.1016/S0004-3702(98)00023-X) | POMDP、belief update、策略与精确/近似规划复杂度。 |
| S11 | Hauskrecht M, Fraser H. *Planning Treatment of Ischemic Heart Disease with Partially Observable Markov Decision Processes*. Artificial Intelligence in Medicine 2000. DOI: [10.1016/S0933-3657(99)00042-1](https://doi.org/10.1016/S0933-3657(99)00042-1), [author PDF](https://people.cs.pitt.edu/~milos/research/AIMJ-2000.pdf) | 医学诊断/治疗交错、部分可观测和行动不确定性；同时明确精确解只适合小问题。 |
| S12 | Papadimitriou CH, Tsitsiklis JN. *The Complexity of Markov Decision Processes*. Mathematics of Operations Research 1987. DOI: [10.1287/moor.12.3.441](https://doi.org/10.1287/moor.12.3.441) | 部分可观测版本的 PSPACE-completeness 与在线最优策略计算限制。 |
| S13 | Pearl J. *Causal Diagrams for Empirical Research*. Biometrika 1995. DOI: [10.1093/biomet/82.4.669](https://doi.org/10.1093/biomet/82.4.669) | 非实验因果效应的图语言、识别取决于可声明的结构/假设；用于否定“条件=干预”。 |
| S14 | Murphy SA. *Optimal Dynamic Treatment Regimes*. JRSS B 2003. DOI: [10.1111/1467-9868.00389](https://doi.org/10.1111/1467-9868.00389), [University of Michigan copy](https://deepblue.lib.umich.edu/items/accf4ac0-901f-49e0-a412-dc90c4016588) | 随时间按患者状态定制的治疗决策规则；用 potential outcomes 明示识别/估计问题。 |
| S15 | HL7. *FHIR R5 Observation definitions*. [official specification](https://hl7.org/fhir/R5/observation-definitions.html) | `effective[x]`（临床/生理相关时间）与 `issued`（结果可获得时间）不同，支持多时钟要求。 |
| S16 | HL7. *FHIR R5 Provenance*. [official specification](https://hl7.org/fhir/R5/provenance.html), [element definitions](https://hl7.org/fhir/R5/provenance-definitions.html) | entity/activity/agent、target/version、occurred 与 recorded；导入/转换也可形成 provenance。 |
| S17 | Poupart P et al. *Approximate Linear Programming for Constrained Partially Observable Markov Decision Processes*. AAAI 2015. DOI: [10.1609/aaai.v29i1.9655](https://doi.org/10.1609/aaai.v29i1.9655) | C-POMDP 是在主目标外显式施加其他目标约束的扩展，而非普通 POMDP 自动能力。 |
| S18 | Ho QH et al. *Recursively-Constrained Partially Observable Markov Decision Processes*. UAI/PMLR 2024. [PMLR paper](https://proceedings.mlr.press/v244/ho24a.html) | 普通 C-POMDP 可能违反 successive decisions 的 optimal substructure 并在安全关键场景产生不理想行为；递归历史约束是进一步扩展。 |
| S19 | Rubin DB. *Inference and Missing Data*. Biometrika 1976. DOI: [10.1093/biomet/63.3.581](https://doi.org/10.1093/biomet/63.3.581) | missingness mechanism 何时可忽略的正式条件；支持“无 evidence factor”并非对所有临床缺失过程都充分。 |
| S20 | Shachter RD. *Evaluating Influence Diagrams*. Operations Research 1986. DOI: [10.1287/opre.34.6.871](https://doi.org/10.1287/opre.34.6.871) | chance、decision、value/utility 的决策图语义和求值；用于界定普通 BN 与决策模型边界。 |
| S21 | W3C. *PROV-DM: The PROV Data Model*. W3C Recommendation 2013. [official specification](https://www.w3.org/TR/2013/REC-prov-dm-20130430/) | entity、activity、agent、generation、usage、derivation 等 provenance 原语。 |
| S22 | Green TJ, Karvounarakis G, Tannen V. *Provenance Semirings*. PODS 2007. DOI: [10.1145/1265530.1265535](https://doi.org/10.1145/1265530.1265535) | 关系查询的统一 provenance annotation/semiring 形式；是概率计算可研究的伴随方向，不是 DBN 原生血缘。 |
| S23 | Ho JC et al. *Limestone: High-throughput Candidate Phenotype Generation via Tensor Factorization*. Journal of Biomedical Informatics 2014. DOI: [10.1016/j.jbi.2014.07.001](https://doi.org/10.1016/j.jbi.2014.07.001) | 多源 EHR tensor factorization 用于 phenotype candidate generation；支持统计共现用途，不支持因果机制解释。 |
| S24 | Che Z et al. *Recurrent Neural Networks for Multivariate Time Series with Missing Values*. Scientific Reports 2018. DOI: [10.1038/s41598-018-24271-9](https://doi.org/10.1038/s41598-018-24271-9) | `T×D` 临床序列需额外 mask 与 time interval 才处理 informative missingness 的原始模型例。 |
| S25 | Harutyunyan H et al. *Multitask Learning and Benchmarking with Clinical Time Series Data*. Scientific Data 2019. DOI: [10.1038/s41597-019-0103-9](https://doi.org/10.1038/s41597-019-0103-9) | 同一 ICU 时间序列的多任务 benchmark；支持多个任务 readout 的工程可行性。 |
| S26 | Scheirer WJ et al. *Toward Open Set Recognition*. IEEE TPAMI 2013. DOI: [10.1109/TPAMI.2012.256](https://doi.org/10.1109/TPAMI.2012.256) | 正式区分 closed-set 与 unknown/open-set 风险；支持“固定分类空间不会自然拒绝未知”。 |
| S27 | Hripcsak G, Albers DJ. *Correlating Electronic Health Record Concepts with Healthcare Process Events*. JAMIA 2013. DOI: [10.1136/amiajnl-2013-001922](https://doi.org/10.1136/amiajnl-2013-001922) | EHR 概念关联受 healthcare process 事件影响的实证；警示统计 latent factor 不等同纯生理机制。 |

## 8. 本轮结论的限制与可推翻条件

- 这是基于标准形式与 30 个测试的**纸面预判**，尚未用统一原型测代码量、更新成本、数值误差和审计负担。
- 本节把最强合理变体与朴素变体分开标注，但家族边界仍可能影响评判；正式比较必须冻结每个候选允许的原语预算。
- `N` 只代表表达/更新语义自然，不代表医学参数可获得、因果效应已识别或计算可行。
- 如果最小向量原型能在不引入事件/图/状态转移等新核心对象的前提下通过血缘、回放、开放世界和硬安全测试，应推翻“向量只适合派生视图”的预判。
- 如果 DBN/因子图原型在真实共病交互下无需全局重建、能给近似误差界并完整撤回证据，应上调其组合与审计评价。
- 如果 factored/continuous POMDP 在相同知识量下能局部扩展、完整 replay、可靠 OOD、可证明硬约束且在预算内求解，应上调其固定核心适配度；反之，若这些都靠外部系统，它只是动态概率计算组件。
