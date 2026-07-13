# 关键第一手来源去重整合

> 范围：从 `research_notes/01_first_principles.md` 至 `07_compositional.md` 中挑出对最终架构论证最有区分力的来源；`08` 完成后再做一次定向并入。这里不是把各笔记的书目机械拼接，而是把重复出现的来源合并，并把每个来源能支持的命题压到最窄。  
> 核验口径：`正式规范` 指标准组织发布的规范、Recommendation、法规或官方互操作规范；`原论文` 指原始研究/形式化论文；`权威教材/综述` 指正文已核对的教材、学位论文或领域综述；`官方文档（非规范）` 只证明相应产品/工具明示的行为；`仅书目` 只证明出版物存在，不能支撑正文命题。  
> 重要边界：下列来源证明的是某种形式工具、数据标准或验证框架**具有什么局部能力或边界**；它们不共同证明某个临床核心架构已经正确，更不证明临床有效性、安全性或全局最优性。

## 1. 临床语义、时间、血缘、缺失与部署边界

| ID | 来源（URL/DOI） | 来源类型 | 本研究只用它支持的有限命题 | 明确不支持什么 |
|---|---|---|---|---|
| CLIN-01 | HL7 FHIR R5：[Observation definitions](https://hl7.org/fhir/R5/observation-definitions.html)、[Condition](https://hl7.org/fhir/R5/condition.html)、[ClinicalImpression](https://hl7.org/fhir/R5/clinicalimpression.html)、[Specimen definitions](https://hl7.org/fhir/R5/specimen-definitions.html)、[DiagnosticReport definitions](https://hl7.org/fhir/R5/diagnosticreport-definitions.html) | 正式规范 | 正式交换模型分别建模测量/时点判断、诊断问题和临床评估；`effective[x]`、`issued`、标本采集/接收等字段也表明临床相关时间与结果可用时间不能合并。 | 不证明 FHIR 资源就是合适的内部计算内核；不保证来源系统完整填写这些字段，也不提供潜在状态、概率推断或严格双时态回放。 |
| CLIN-02 | HL7 FHIR R5：[Provenance](https://hl7.org/fhir/R5/provenance.html) 与 [element definitions](https://hl7.org/fhir/R5/provenance-definitions.html) | 正式规范 | 可显式记录 target/version、agent、activity、entity、occurred 与 recorded，以及导入、转换、修订等来源关系。 | 不证明两份证据独立或可靠；不提供推断依赖代数、撤回级联或生理因果。 |
| CLIN-03 | HL7 FHIR R5：[Workflow](https://hl7.org/fhir/R5/workflow.html) | 正式规范 | definition、request 与 event 是不同工作流模式；request 表示意图且不保证动作实际发生。 | 不证明整个 FHIR workflow 足以表达复杂临床动力学、治疗效果或动作安全策略。 |
| CLIN-04 | HL7 FHIR R5：[DataAbsentReason](https://hl7.org/fhir/R5/valueset-data-absent-reason.html) | 正式规范 | `unknown`、`asked-unknown`、`not-asked`、`masked`、`not-applicable`、`unsupported`、`error`、`not-performed` 等缺值原因在正式临床互操作词表中被区分。 | 不给出这些状态的统计 missingness mechanism、推断规则或临床处置含义；更不允许把任一缺值自动当阴性。 |
| CLIN-05 | Regenstrief Institute, [UCUM 2.2 specification](https://ucum.org/ucum) | 正式规范 | 数值与单位可以用可计算、无歧义的语法通信，并可检查量纲与换算。 | 不证明两项检测在标本、方法、校准或临床意义上可比，也不解决术语映射和参考范围版本。 |
| CLIN-06 | W3C, [PROV-DM](https://www.w3.org/TR/prov-dm/) 与 [PROV-CONSTRAINTS](https://www.w3.org/TR/prov-constraints/), Recommendations, 2013 | 正式规范 | Entity/Activity/Agent、generation/usage/derivation/invalidation 等可形成互操作血缘；约束规范给出 generation、usage 等事件的顺序/一致性约束。 | 血缘不等于真值、可靠度或统计独立性；标准不自动完成删除后的全图真值维护，也不定义临床证据权重。 |
| CLIN-07 | Snodgrass & Ahn, [“A Taxonomy of Time in Databases”](https://doi.org/10.1145/318898.318921), SIGMOD 1985 | 原论文 | 区分 valid time 与 transaction time；同一现实时间事实可随数据库知识时间变化，从形式上支持“当时所知”与“现在回看过去”的分离。 | 双时态仍不覆盖采集、结果发布、actor-specific visibility、规则版本、过期时间等全部临床时钟。 |
| CLIN-08 | Rubin, [“Inference and Missing Data”](https://doi.org/10.1093/biomet/63.3.581), *Biometrika* 1976 | 原论文 | 是否可忽略 missingness process 取决于明确条件；“没有记录”不能普遍当作无信息或随机缺失。 | 不给出 EHR 特有的观察机会模型，也不把 missingness reason 直接转成诊断概率。 |
| CLIN-09 | W3C, [OWL 2 Web Ontology Language Primer](https://www.w3.org/TR/owl2-primer/), Recommendation, 2012 | 正式规范 | 开放世界语义下，知识库未陈述某事实不蕴含该事实为假；类、公理和推理可在声明式本体中扩展。 | 不提供统计 OOD 检测、概率校准、时间回放或临床观察生成模型。 |
| CLIN-10 | IMDRF, [*Software as a Medical Device: Clinical Evaluation* (N41)](https://www.imdrf.org/documents/software-medical-device-samd-clinical-evaluation) | 正式监管指南 | valid clinical association、analytical/technical validation 与 clinical validation 是不同证据层；部署论证不能由表示或单元测试替代。 | 不选择内部架构，也不证明任一原型已达到临床有效性或监管可接受性。 |
| CLIN-11 | Moons et al., [PROBAST+AI](https://doi.org/10.1136/bmj-2024-082505), *BMJ* 2025 | 原论文（方法学框架） | 预测模型的开发质量、性能评价偏倚风险和对目标用途/人群的 applicability 必须分开评估。 | 不规定动态临床状态内核，也不能从一个仓库内 benchmark 推出跨机构临床可迁移性。 |
| CLIN-12 | Agniel, Kohane & Weber, [“Biases in electronic health record data due to processes within the healthcare system”](https://doi.org/10.1136/bmj.k1479), *BMJ* 2018 | 原论文（真实 EHR 实证） | 真实 EHR 中记录的有无和检测频率会受到医疗流程系统性影响，并可携带预测信息；观察机会本身不能被当作无关缺失。 | 记录频率有信息不等于它是疾病因果证据，也不证明任何特定 missingness/observation model 已被正确识别。 |
| CLIN-13 | Cheng et al., [“Blood Culture Results Before and After Antimicrobial Administration in Patients With Severe Manifestations of Sepsis”](https://pubmed.ncbi.nlm.nih.gov/31525774/), *Annals of Internal Medicine* 2019 | 原论文（前瞻性诊断研究） | 在该研究人群中，抗菌药给药后的血培养敏感度低于给药前，提供“干预会改变观察通道”的真实临床反例。 | 单一研究不能定义所有病原体、药物和采样场景的通用观察模型，也不直接识别个体治疗效应。 |
| CLIN-14 | Green, Karvounarakis & Tannen, [“Provenance Semirings”](https://doi.org/10.1145/1265530.1265535), PODS 2007；[作者 PDF](https://www.cs.ucdavis.edu/~green/papers/pods07.pdf) | 原论文 | 为 base tuples 分配 token 后，可用 semiring annotation 保留查询结果的多条推导组合，并统一若干 why-provenance/bag/incomplete/probabilistic database 语义。 | 多项式路径或系数不能直接当“独立临床证据票数”；否定、递归撤回、来源克隆和医学依赖仍需额外语义。 |

## 2. 向量、DBN、因子图、状态空间、POMDP 与决策模型

| ID | 来源（URL/DOI） | 来源类型 | 本研究只用它支持的有限命题 | 明确不支持什么 |
|---|---|---|---|---|
| STATE-01 | Kolda & Bader, [“Tensor Decompositions and Applications”](https://doi.org/10.1137/07070111X), *SIAM Review* 2009 | 权威综述 | tensor 是 N-way array；CP/Tucker 等分解能压缩或发现多路数组结构。 | tensor 坐标本身不提供临床认识论类型、干预、来源、开放世界或历史回放语义。 |
| STATE-02 | Murphy, [*Dynamic Bayesian Networks: Representation, Inference and Learning*](https://www2.eecs.berkeley.edu/Pubs/TechRpts/2002/8174.html), PhD thesis, 2002 | 权威学位论文 | DBN 以 factored state 和跨时间条件依赖统一 HMM、Kalman 等模型，并系统讨论精确/近似推断。 | 不证明 DBN 会自动选对临床变量、因果方向、时间粒度或证据血缘。 |
| STATE-03 | Kschischang, Frey & Loeliger, [“Factor Graphs and the Sum-Product Algorithm”](https://doi.org/10.1109/18.910572), IEEE TIT 2001 | 原论文 | 二部 factor graph 将全局函数分解为局部 factors；sum-product 的正确性/代价依赖图结构，环图通常需近似。 | factor edge 不自动区分生理因果、统计相关、观察通道和证据派生，也不提供事件时间。 |
| STATE-04 | Nodelman, Shelton & Koller, [“Continuous Time Bayesian Networks”](https://ai.stanford.edu/~nodelman/papers/ctbn.html), UAI 2002 | 原论文 | 有限状态连续时间过程可用局部 conditional intensity 建模，避免固定时间片并生成异步事件轨迹。 | CTBN 的连续时间不是 knowledge-time；有限状态及局部强度也不自动覆盖连续生理量、血缘和动作语义。 |
| STATE-05 | Kalman, [“A New Approach to Linear Filtering and Prediction Problems”](https://doi.org/10.1115/1.3662552), 1960 | 原论文 | 在线性动态与噪声假设下，隐藏状态估计和观测应分开，并可递推更新估计与误差协方差。 | 不支持把任意临床系统假定为线性高斯，也不提供疾病本体、治疗决策、证据去重或开放世界。 |
| STATE-06 | Kaelbling, Littman & Cassandra, [“Planning and Acting in Partially Observable Stochastic Domains”](https://doi.org/10.1016/S0004-3702(98)00023-X), *Artificial Intelligence* 1998 | 权威综述/方法论文 | POMDP 明确区分隐藏状态、观察、行动、belief update 与策略；精确规划存在严重计算限制。 | POMDP 不原生区分记录/可见时间、来源身份、知识版本和计划与已实施动作；状态与效用仍须人为建模。 |
| STATE-07 | Shachter, [“Evaluating Influence Diagrams”](https://doi.org/10.1287/opre.34.6.871), *Operations Research* 1986 | 原论文 | chance、decision 与 value/utility 是不同节点/语义，概率信念不足以单独决定行动。 | 不提供临床效用函数、伦理授权、安全约束或证据账本；也不证明 influence diagram 应是唯一内核。 |
| STATE-08 | Scheirer et al., [“Toward Open Set Recognition”](https://doi.org/10.1109/TPAMI.2012.256), IEEE TPAMI 2013 | 原论文 | closed-set 分类与需控制 unknown/open-space risk 的 open-set 问题不同；固定已知类归一化不会自然产生可靠拒绝。 | 不提供临床 OOD 阈值、健康 reference、校准方案或开放世界知识表示。 |
| STATE-09 | Åström, [“Optimal Control of Markov Processes with Incomplete State Information”](https://doi.org/10.1016/0022-247X%2865%2990154-X), *Journal of Mathematical Analysis and Applications* 1965 | 原论文 | 隐藏系统状态、可获得观察信息和控制策略可以在不完全状态信息下严格分离；belief/information state 有成熟控制理论来源。 | 不证明临床过程满足 Markov 假设，也不要求最终内核采用 POMDP；不提供 EHR 血缘、知识时间和医学状态变量。 |

## 3. 结构因果模型、概率编程与开放宇宙

| ID | 来源（URL/DOI） | 来源类型 | 本研究只用它支持的有限命题 | 明确不支持什么 |
|---|---|---|---|---|
| CAUSAL-01 | Pearl, [“An Introduction to Causal Inference”](https://pmc.ncbi.nlm.nih.gov/articles/PMC2836213/), 2010 | 权威方法综述 | SCM/因果图在明确结构假设下区分 association、intervention 与 counterfactual；`do` 不是普通条件化。 | 数据拟合本身不证明箭头或机制正确；来源不提供临床事件账本、知识时间或部署验证。 |
| CAUSAL-02 | Bongers et al., [“Foundations of Structural Causal Models with Cycles and Latent Variables”](https://doi.org/10.1214/21-AOS2064), *Annals of Statistics* 2021 | 原论文 | 循环 SCM 可能无解、多解，且未必诱导唯一 observational/interventional/counterfactual distribution；需要额外 solvability 条件。 | 不证明所有生理反馈都不适合 SCM；也不提供工程级时间、血缘和模型版本方案。 |
| CAUSAL-03 | Ibeling & Icard, [“On Open-Universe Causal Reasoning”](https://proceedings.mlr.press/v115/ibeling20a.html), UAI 2020 | 原论文 | 结构方程/simulation model 可扩展到可数无限变量，并给出相应干预与反事实语义；丰富程序下某些推理会不可判定。 | 这里的“开放宇宙”是变量空间层面，不等于运行时新医学概念、未知疾病识别或安全 OOD。 |
| CAUSAL-04 | Gordon et al., [“Probabilistic Programming”](https://doi.org/10.1145/2593882.2593900), FOSE 2014 | 权威综述 | 普通 PPL 的核心是在程序中加入随机采样并对 observations conditioning，从而把模型与通用推断分开。 | sampling/conditioning 不自动提供 `do`、反事实同一性、因果识别、临床 provenance 或审计回放。 |
| CAUSAL-05 | Milch et al., [“BLOG: Probabilistic Models with Unknown Objects”](https://www.ocf.berkeley.edu/~dlong/publications/blog-ijcai05.pdf), IJCAI 2005 | 原论文 | 可能世界可含变化且无界的对象数量，可表达对象身份和存在数量不确定。 | 对象数开放不等于概念/schema 开放；模型声明、类型和生成过程仍须预先给定。 |
| CAUSAL-06 | Tavares et al., [“A Language for Counterfactual Generative Models”](https://proceedings.mlr.press/v139/tavares21a.html), ICML 2021 | 原论文 | OmegaC 通过额外语言操作让概率程序表达“给定事实证据后干预过去”的反事实，说明普通 `observe` 之外还需专门因果语义。 | 不解决 causal discovery、可识别性、临床血缘或 as-of replay；给定 simulator 错误时反事实仍会错误。 |
| CAUSAL-07 | Zhang, Tian & Bareinboim, [“Partial Counterfactual Identification from Observational and Experimental Data”](https://proceedings.mlr.press/v162/zhang22ab.html), ICML 2022 | 原论文 | 反事实量常不能从给定观察/实验分布点识别；可以求 tight bounds，但计算可转化为昂贵的 polynomial program。 | 不支持“只要有 SCM/PPL 就能给可信个体反事实点估计”，也不给出临床数据所需假设。 |

## 4. 事件/动作逻辑、事件溯源、流与增量维护

| ID | 来源（URL/DOI） | 来源类型 | 本研究只用它支持的有限命题 | 明确不支持什么 |
|---|---|---|---|---|
| TEMP-01 | Kowalski & Sergot, [“A Logic-based Calculus of Events”](https://doi.org/10.1007/BF03037383), 1986；[作者 PDF](https://www.doc.ic.ac.uk/~rak/papers/event%20calculus.pdf) | 原论文 | Event Calculus 以事件、时间区间/性质及启动终止关系推理变化，且事件描述可乱序吸收；知识撤销可通过新增有效期结束的信息表达。 | 原始 EC 不提供概率临床推断、双时态、actor visibility、证据去重或自动因果发现。 |
| TEMP-02 | Lamport, [“The Temporal Logic of Actions”](https://doi.org/10.1145/177492.177726), TOPLAS 1994；[作者页](https://www.microsoft.com/en-us/research/publication/the-temporal-logic-of-actions/) | 原论文 | action 可作为前后状态关系，系统行为与 safety/liveness 性质可在同一逻辑中表达并用于 refinement 验证。 | TLA 不选择临床状态变量，不估计概率，也不替代事件存储、证据血缘或医学知识。 |
| TEMP-03 | Akidau et al., [“The Dataflow Model”](https://www.vldb.org/pvldb/vol8/p1792-Akidau.pdf), PVLDB 2015 | 原论文 | event time 与 processing time 不同；无界流会乱序和迟到，正确性、延迟与成本需要显式权衡。 | watermark 不是某临床角色实际看到结果的证明，也不能作为可靠的历史知识截断。 |
| TEMP-04 | Microsoft Azure Architecture Center, [“Event Sourcing pattern”](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing) | 官方文档（非规范） | 该模式明确使用 append-only event store、replay/rehydration、materialized views、compensating events，并列出顺序、版本、幂等、projection lag 与隐私删除风险。 | 不是正式标准；普通 event sourcing 不定义 valid/available time、临床证据资格或“按当时知识”回放。 |
| TEMP-05 | Gupta, Mumick & Subrahmanian, [“Maintaining Views Incrementally”](https://doi.org/10.1145/170036.170066), SIGMOD 1993 | 原论文 | insertion/deletion/update 可增量传播到关系/Datalog materialized views；counting 能在一个 derivation 删除后保留其他 derivations。 | derivation 数不等于独立临床证据数，也不提供来源身份、因果或非单调临床语义。 |
| TEMP-06 | Budiu et al., [“DBSP: Automatic Incremental View Maintenance for Rich Query Languages”](https://doi.org/10.14778/3587136.3587137), PVLDB 2023 | 原论文 | 可把数据库变化视为流并自动计算 query delta，覆盖关系代数、集合/多重集、聚合、嵌套及单调/非单调递归。 | DBSP 是执行/增量化框架，不判断医学规则正确，也不自动提供 why-provenance、因果或审计策略。 |

## 5. Petri 网、进程代数与反应网络

| ID | 来源（URL/DOI） | 来源类型 | 本研究只用它支持的有限命题 | 明确不支持什么 |
|---|---|---|---|---|
| PROC-01 | Murata, [“Petri Nets: Properties, Analysis and Applications”](https://doi.org/10.1109/5.24143), *Proceedings of the IEEE* 1989 | 权威综述 | P/T 网以 place、transition、arc、marking、firing 表达并发、同步、资源竞争及 invariant；扩展网增加颜色、时间或随机性。 | token 不天然是临床证据或患者；基础网不提供多时钟、概率 observation model、血缘或开放世界。 |
| PROC-02 | ISO/IEC, [15909-1:2019](https://www.iso.org/standard/67235.html) | 正式规范 | high-level Petri nets 有标准化的概念、图形表示和数学语义范围。 | 标准化语法不证明 Petri 网适合作为临床核心，也不提供医学知识、统计推断或审计血缘。 |
| PROC-03 | Baez & Master, [“Open Petri Nets”](https://doi.org/10.1017/S0960129520000043), MSCS 2020 | 原论文 | 明确输入/输出 places 后，Petri nets 可沿边界粘合并形成组合结构，同时保留 operational/reachability 语义。 | 边界可组合不自动识别正确临床模块、共享患者状态、证据依赖或非线性交互。 |
| PROC-04 | Brookes, Hoare & Roscoe, [“A Theory of Communicating Sequential Processes”](https://doi.org/10.1145/828.833), JACM 1984 | 原论文 | CSP 以通信、并行、选择和 nondeterminism 建模进程，并给出 traces/failures 等数学语义。 | 不提供共享临床事实存储、概率过滤、知识时间或证据来源；把所有医学语义编码成 action 名不等于解决。 |
| PROC-05 | Gillespie, [“Exact Stochastic Simulation of Coupled Chemical Reactions”](https://doi.org/10.1021/j100540a008), 1977 | 原论文 | 在规定反应通道与 propensity 的 well-mixed Markov 化学体系中，可精确采样 chemical master equation 的随机事件路径，并区分确定性 rate equation 与随机模型。 | 不证明患者系统满足这些物理假设，也不表达临床观察、知识时间、干预授权或证据血缘。 |
| PROC-06 | Anderson & Kurtz, [“Continuous Time Markov Chain Models for Chemical Reaction Networks”](https://people.math.wisc.edu/~dfanderson/papers/SURVEY_AndKurtz.pdf), 2011 | 权威综述 | species counts、reaction intensity、random time-change 给出 CTMC 语义，并解释 ODE/diffusion 极限及 delay 等扩展边界。 | 不自动把医学机制映射为反应，也不保证 reduction/approximation 保留临床关键风险。 |
| PROC-07 | Hucka et al., [*SBML Level 3 Version 2 Core Release 2*](https://sbml.org/specifications/sbml-level-3/version-2/core/release-2/sbml-level-3-version-2-release-2-core.pdf), 2019 | 正式规范 | SBML 标准化 species、reaction、rule、event、delay 等计算模型交换结构，并明确自己不是 universal modelling language。 | SBML history annotation 不等于底层概念模型的完整 provenance；规范不提供临床语义、推断或安全不变量。 |

## 6. 类型、重写、逻辑与真值维护

| ID | 来源（URL/DOI） | 来源类型 | 本研究只用它支持的有限命题 | 明确不支持什么 |
|---|---|---|---|---|
| TYPE-01 | Rondon, Kawaguchi & Jhala, [“Liquid Types”](https://doi.org/10.1145/1379022.1375602), PLDI 2008；[作者 PDF](https://ranjitjhala.github.io/static/liquid_types.pdf) | 原论文 | 受限 refinement predicates 可与类型推断结合，静态验证一类数据/程序不变量。 | refinement 只能证明已编码的性质；不能证明医学模型、规则或输入事实真实完整，也不适合直接承载概率信念。 |
| TYPE-02 | Strom & Yemini, [“Typestate: A Programming Language Concept for Enhancing Software Reliability”](https://doi.org/10.1109/TSE.1986.6312929), IEEE TSE 1986 | 原论文 | typestate 可按对象当前抽象状态限制合法操作，在编译期发现语法合法但语义未定义的调用序列。 | 不提供患者状态估计、临床时间、证据不确定性或规则知识；运行时外部世界仍可能违背类型假设。 |
| TYPE-03 | Meseguer, [“Conditional Rewriting Logic as a Unified Model of Concurrency”](https://doi.org/10.1016/0304-3975(92)90182-F), TCS 1992 | 原论文 | 条件重写 modulo 结构公理可把局部状态变换与并发统一为逻辑推导，并给出 soundness/completeness 和 initial-model 结果。 | 一般重写系统不自动终止或合流；规则语法本身不提供概率、来源独立性、临床时间或正确医学机制。 |
| TYPE-04 | Doyle, [“A Truth Maintenance System”](https://doi.org/10.1016/0004-3702(79)90008-0), *Artificial Intelligence* 1979 | 原论文 | 显式记录 belief reasons 后，可在假设/矛盾变化时修订当前信念、解释和依赖。 | 经典 TMS 不自动处理概率、双时态、并发、多来源独立性或临床 observation model。 |
| TYPE-05 | de Kleer, [“An Assumption-Based TMS”](https://doi.org/10.1016/0004-3702(86)90080-9), *Artificial Intelligence* 1986 | 原论文 | ATMS 用 assumption environments 同时维护多个候选解释，并在矛盾和撤回下保留可行 environments。 | 不给解释分配可信后验，也不解决时间、因果识别、证据来源真实性或组合爆炸。 |
| TYPE-06 | Abiteboul, Deutch & Vianu, [“Deduction with Contradictions in Datalog”](https://doi.org/10.5441/002/icdt.2014.17), ICDT 2014；[正文](https://openproceedings.org/2014/conf/icdt/AbiteboulDV14.pdf) | 原论文 | 在存在矛盾的数据库/Datalog 设定中，可形式化 possible worlds、非确定推导及其复杂度，而不是让经典爆炸静默污染全部结论。 | 不等于完整临床 uncertainty 类型系统，也不自动给出冲突裁决、概率权重、时间和血缘。 |
| TYPE-07 | Belnap, [“A Useful Four-Valued Logic”](https://doi.org/10.1007/978-94-010-1161-7_2), 1977 | 原论文/书章 | `true`、`false`、`neither`、`both` 一类信息状态说明不完整与不一致信息可有非爆炸的形式语义。 | 四值逻辑不能替代 typed missingness、概率/区间、来源、时间、适用性或 OOD；它也不决定冲突应如何临床处置。 |

## 7. 范畴、operad、开放系统与 sheaf

| ID | 来源（URL/DOI） | 来源类型 | 本研究只用它支持的有限命题 | 明确不支持什么 |
|---|---|---|---|---|
| COMP-01 | Fong & Spivak, [*An Invitation to Applied Category Theory*](https://doi.org/10.1017/9781108668804), Cambridge UP 2019 | 权威教材 | 对称幺半范畴、cospan、hypergraph category、operad 与 sheaf 是不同组合工具；组合语法与选择的具体语义必须分开。 | 不证明范畴论本身减少临床原语、特例或错误，也不选择患者、证据、时间和干预语义。 |
| COMP-02 | Vagner, Spivak & Lerman, [“Algebras of Open Dynamical Systems on the Operad of Wiring Diagrams”](https://arxiv.org/abs/1408.1598), 2015 | 原论文/预印本 | typed wiring diagram 可给开放 dynamical systems 提供层级组合语法；选择相应 algebra 后，盒子可获得一般/线性微分方程语义。 | 端口类型相合不等于临床语义相合；不自动识别共享患者状态、证据血缘、不确定性或共病交互。 |
| COMP-03 | Baez & Courser, [“Structured Cospans”](https://arxiv.org/abs/1911.04630), TAC 2020 | 原论文 | 在明确范畴条件下，`L(a) → x ← L(b)` 形式可沿边界 pushout 粘合，得到对称幺半/双范畴结构。 | pushout 不提供方向性因果、时间、随机性或医学正确边界；错误接口也能被形式上完美组合。 |
| COMP-04 | Schultz, Spivak & Vasilakopoulou, [“Dynamical Systems and Sheaves”](https://doi.org/10.1007/s10485-019-09565-x), 2020 | 原论文 | interval sheaf 可表示随时间的 signals/behaviours，开放机器可用 span 组合；组合保持 totality/determinism 需要明确条件。 | 单一 interval 时间不区分发生与获知时间；组合良定性不是无条件的，也不提供临床概率和 provenance。 |
| COMP-05 | Robinson, [“Sheaves are the canonical data structure for sensor integration”](https://doi.org/10.1016/j.inffus.2016.12.002), *Information Fusion* 2017 | 原论文 | sheaf/presheaf 可表达异构局部域、restriction maps、全局一致性与 consistency radius；现实噪声下可把拼接转成优化问题。 | 最近全局截面不天然是安全临床解释；topology、度量、容差和融合目标都是额外语义，冲突也不应被强行抹平。 |

## 8. 去重与证据使用规则

1. **同一来源只保留一次**：W3C PROV-DM、Green 等 provenance semiring、Snodgrass–Ahn、Rubin、Baez–Pollard 等在多份笔记重复出现时，只在最直接的领域保留一条；跨领域结论引用同一 ID。
2. **正式规范只证明规范写了什么**：FHIR、UCUM、W3C、ISO、SBML、IMDRF 可证明字段/语义/合规证据层的存在，但不能凭“符合标准”推出内部计算正确或临床有效。
3. **表达力不等于原生安全性**：论文能编码某结构，只能记作“可表达”；只有形式语义或运行测试明确强制不变量时，才能记作“核心保证”。
4. **理论 trace 不等于临床 lineage**：概率程序 execution trace、图上的 parent edge、Petri token history、重写 derivation 和 W3C PROV 各回答不同问题，禁止互换。
5. **开放世界、开放集合、开放宇宙分开**：OWL 的未陈述不为假、open-set recognition 的未知类别风险、BLOG/open-universe 的未知对象数量是三种不同命题。
6. **部署证据另列**：IMDRF 与 PROBAST+AI 约束最终声明的上限；架构压力测试通过只能支持语义/工程命题，不能冒充 clinical validation。

## 9. 仅书目线索（不进入核心支撑链）

下列条目在分项笔记中只有书目/元数据记录，故不用于上述架构结论：

| 线索 | 状态 | 当前只允许说什么 | 若要升级需做什么 |
|---|---|---|---|
| Carl Adam Petri, *Kommunikation mit Automaten* (1962), [Hamburg bibliography record](https://www2.informatik.uni-hamburg.de/TGI/publikationen/public/1962/Petri62/Petri62_eng.html) | 仅书目 | Petri 1962 dissertation 的历史出版信息存在。 | 打开并核对正文/可靠译本后，才可用来支持具体形式定义。 |
| C. Ramchandani, *Analysis of Asynchronous Concurrent Systems by Timed Petri Nets* (1974), [bibliography record](https://www2.informatik.uni-hamburg.de/TGI/pnbib/r/ramchandani_c1.html) | 仅书目 | 有该 timed Petri net 技术报告的书目信息。 | 核对 MIT 正文后再引用其 timed semantics 或分析结论。 |
| Gelfond & Lifschitz, “The Stable Model Semantics for Logic Programming” (1988), [DBLP metadata](https://dblp.org/rec/conf/iclp/GelfondL88) | 仅书目 | 原始会议文献的出版元数据可核实。 | 打开原文或作者正式重印本；目前只能把[作者后续综述](https://www.cs.utexas.edu/~vl/papers/13defs.pdf)另作二级依据。 |

## 10. 尚待并入

- `research_notes/08_*` 尚未生成；待其完成后，只补入知识图谱/超图、world model、数字孪生或 Transformer 方向中真正改变比较结论的少数第一手来源，并继续保持总关键来源数不超过 60。
- 本整合不修改 `SOURCES.md`；正式账本升级由主任务在逐条复核后决定。
