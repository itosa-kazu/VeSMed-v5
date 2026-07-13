# 候选家族 04：事件演算 / 情境演算 / 时态逻辑 + 事件溯源 / 双时态 / 增量视图

> 研究日期：2026-07-13  
> 范围：只评价这一候选家族，不提前替总研究选赢家。  
> 证据政策：核心事实只引用原始论文、正式规范或官方文档；每个来源只写它实际支持的有限命题。  
> 工作结论：**这是极强的“时间—证据—回放”底座，但单独不是完整的动态临床状态与诊疗计算架构。**

## 0. 一句话判断

这组技术不能被当成一个同义词：

- **事件演算（Event Calculus, EC）**回答“哪些事件在何时使哪些 fluent 开始、终止、持续”；
- **情境演算（Situation Calculus, SC）**回答“执行一串动作后，哪些命题在所得 situation 中成立”；
- **时态逻辑（LTL/MTL/TLA）**适合声明和验证跨状态/跨时间的不变量，而不是替代临床数据模型；
- **事件溯源（Event Sourcing）**保存不可变变更历史并重放出 projection，但不会自动赋予正确的临床时间、认识论或因果语义；
- **双时态数据库（bitemporal DB）**把“事实描述何时”和“系统何时持有该版本”正交化；
- **增量视图维护（IVM）**使插入、撤回、更正能增量传播到派生视图，但不会自动给出证据独立性或医学意义。

若把它们组合成一个候选，可得到本文暂称的 **Temporal Evidence Ledger（TEL，时态证据账本）**：不可变、版本化、带多时间和血缘的证据/动作日志，经过显式规则产生可重建的任务视图，并用时态不变量守住未来信息隔离。TEL 对测试 12、13、19、23、24、25、26、27 特别强；但概率、不确定性、潜在生理状态、共病非线性和治疗效应识别仍需别的计算语义。

---

## 1. 不要把六个子家族混成一句话

| 子家族 | 原生原语与状态位置 | 原生强项 | 不原生解决的关键问题 |
|---|---|---|---|
| Event Calculus | `event`, `time`, `fluent`, `happens`, `initiates`, `terminates`, `holdsAt`；状态是由事件推出的局部持续区间 | 非顺序到达的过去事件、惯性、事件导致 fluent 起止、可执行逻辑 | 概率、证据血缘、valid/transaction/availability 多时间、连续潜在生理状态；基本 SEC 的间接效应（ramification）要显式补规则 |
| Situation Calculus | situation、action、`do(action,s)`、fluent、动作前提与 successor-state axiom；状态沿动作历史存在 | 动作效果、计划、回归、区分动作是否真正执行 | 标准形式倾向串行、全局 situation；异步外生事件、并发、迟到记录、多观察者可见性要扩展 |
| LTL / MTL / TLA | trace/behavior、状态谓词、转移 action、`always/eventually/until` 或有界时间算子 | 安全性、活性、顺序与期限约束；可模型检查反例轨迹 | 不定义临床实体、证据来源、开放世界、概率或派生语义；它是规范/验证层，不是患者状态本体 |
| Event Sourcing | append-only event stream、reducer、snapshot、projection | 审计、重放、补偿事件、多 read model | “append 顺序”不等于“临床发生顺序/何时可知”；使用最新 reducer 重放会改写过去语义；事件类型本身可能成为无约束语义垃圾桶 |
| Bitemporal DB | valid-time interval × transaction-time interval | “当前如何理解过去”与“过去当时知道什么”分离；更正仍可审计 | 只有两条系统时间轴仍不足以覆盖采集、发布、按角色可见、过期；不提供医学推理 |
| IVM / differential dataflow | base relation 的正/负 delta、query/view、派生 delta | 删除/更正自动传播；避免每次全量重算；可支持递归和聚合 | 不自动知道哪些记录同源、哪些规则安全、为什么是医学证据；递归+否定+血缘仍复杂 |

**因此总候选必须按组合来评，不能拿“事件溯源能 replay”冒充“过去判断绝不使用未来信息”，也不能拿“时态逻辑能写公式”冒充已经有临床语义。**

最小性上也不应把 EC 与 SC 两套 action calculus 同时硬塞进内核。本文的组合候选默认用 **EC-like event/fluent semantics** 处理异步临床 narrative；SC 保留为“以动作历史/计划为中心”的正面对照或可替换模块。若原型同时实现两者，必须证明新增语义而非重复表达。

---

## 2. 第一手来源与可验证的有限支持点

### 2.1 逻辑中的事件、动作和时间

1. **Kowalski & Sergot (1986), “A Logic-based Calculus of Events”**  
   - 原文 PDF（作者站）：https://www.doc.ic.ac.uk/~rak/papers/event%20calculus.pdf  
   - DOI：https://doi.org/10.1007/BF03037383  
   - 实际支持：事件被当作比时间更基本的概念；EC 用 Horn clauses + negation-as-failure 表示事件、局部时期与惯性；事件描述可按不同于实际发生的顺序被吸收；传统数据库的“删除”可表示为新增“该关系有效期结束”的知识。  
   - **不支持**：概率临床推断、双时态、多观察者 visibility、证据去重或自动因果识别。

2. **Shanahan, “The Ramification Problem in the Event Calculus”**  
   - 作者站原文：https://www.doc.ic.ac.uk/~mpsha/ramifications.pdf  
   - 实际支持：较丰富的 predicate-calculus EC 以 action/event、fluent、time point 及 `Initiates/Terminates/Releases/Happens/HoldsAt` 为本体；论文表明 concurrent action、continuous change 和间接 effect 可以用 state/causal constraints 及少量新增 predicates/axioms 扩展处理。  
   - **关键限定**：这些能力不是最简 EC 公理免费产生的；论文明确说尚未正式评估所提 ramification 解法的适用范围。因此“EC 可扩展表达交互”不能记成“自动发现临床交互”。

3. **McCarthy & Hayes (1969), “Some Philosophical Problems from the Standpoint of Artificial Intelligence”**  
   - 作者官方页与 PDF：https://www-formal.stanford.edu/jmc/mcchay69.html  
   - 实际支持：这是 situation calculus 的奠基论文；以 situation、action 和因果律形式化世界变化，并提出 frame problem。  
   - **不支持**：现代的 successor-state axiom、概率 sensing 或临床事件乱序工程实现。

4. **Reiter (1991), “The Frame Problem in the Situation Calculus: A Simple Solution (Sometimes) and a Completeness Result for Goal Regression”**  
   - DOI：https://doi.org/10.1016/B978-0-12-450010-5.50026-8  
   - 实际支持：successor-state axioms 与 goal regression 在给定条件下处理 frame problem；标题中的 “Sometimes” 本身就是适用范围限定。  
   - **不支持**：它没有给出多时间 EHR 存储或概率诊疗架构。

5. **Bacchus, Halpern & Levesque (1995/1999), noisy sensors/effectors in Situation Calculus**  
   - IJCAI 1995 原文：https://www.ijcai.org/Proceedings/95-2/Papers/116.pdf  
   - 完整版预印本：https://arxiv.org/abs/cs/9809013  
   - 实际支持：概率 belief 和 noisy sensing 可以作为 SC 的明确扩展来建立。  
   - **关键限定**：这恰好说明标准 SC 的动作/状态逻辑本身并不自动带概率不确定性；需要额外 belief/likelihood 语义。

6. **Pnueli (1977), “The Temporal Logic of Programs”**  
   - DOI：https://doi.org/10.1109/SFCS.1977.32  
   - 可读原文：https://www.dimap.ufrn.br/~richard/pubs/dim0436/papers/pnueli_temporal_1977.pdf  
   - 实际支持：用时间依赖事件和 temporal reasoning 验证顺序/并发程序行为。  
   - **不支持**：LTL 自己不是事件账本、患者本体或证据血缘模型。

7. **Lamport (1994), “The Temporal Logic of Actions”**  
   - Microsoft Research 原文页：https://www.microsoft.com/en-us/research/publication/the-temporal-logic-of-actions/  
   - DOI：https://doi.org/10.1145/177492.177726  
   - 实际支持：TLA 的 action 是带 primed/unprimed variables 的状态转移关系；系统和性质可在同一逻辑中表达，适合验证 safety/refinement。  
   - **不支持**：TLA 不替我们选择临床状态变量，也不自动生成医学 inference。

8. **Koymans (1990), “Specifying Real-Time Properties with Metric Temporal Logic”**  
   - DOI：https://doi.org/10.1007/BF01995674  
   - 实际支持：MTL 给 temporal operators 加有界时间区间，能表达“在 x 分钟内/持续 y 分钟”等实时时限。  
   - **不支持**：MTL 的度量时间不是 valid-time × knowledge-time 的数据库语义。

### 2.2 时间数据库、流处理和临床时间字段

9. **Snodgrass & Ahn (1985), “A Taxonomy of Time in Databases”**  
   - 作者站 PDF：https://www2.cs.arizona.edu/~rts/pubs/SIGMOD85.pdf  
   - DOI：https://doi.org/10.1145/318898.318921  
   - 实际支持：区分 transaction time（信息何时进入数据库）和 valid time（信息描述现实中何时成立），并保留额外 user-defined/application time；论文给出同一 valid-time 事实在不同 transaction-time 查询中答案不同的例子，正是“过去当时所知”与“现在回看过去”的分离。  
   - **不支持**：二轴本身不够表达 specimen collection、result issued、per-actor visibility、TTL/expiry 等全部临床时间。

10. **Akidau et al. (2015), “The Dataflow Model”**  
    - PVLDB 原文：https://www.vldb.org/pvldb/vol8/p1792-Akidau.pdf  
    - 实际支持：事件时间和处理时间不同；无界数据可能乱序、迟到，系统必须在正确性、延迟和成本之间作显式选择。  
    - **不支持**：watermark 不是“某临床角色在某时刻确实看见结果”的证明。

11. **Apache Beam 官方文档，Watermarks and late data**  
    - https://beam.apache.org/documentation/basics/#watermark  
    - 实际支持：event time 是数据事件时间，processing time 是流水线处理时间；watermark 只是对完整性的估计；默认 window 配置可能丢弃 watermark 后的 late data。  
    - **安全结论**：临床历史回放不能把 watermark 当知识截断，也不能接受默认丢弃迟到资料。

12. **HL7 FHIR R5 Observation / Specimen / DiagnosticReport / Provenance（官方规范）**  
    - Observation：<https://www.hl7.org/fhir/R5/observation-definitions.html>（镜像可读：<https://fhir.hl7.org/fhir/observation-definitions.html>）  
    - Specimen：<https://fhir.hl7.org/fhir/specimen-definitions.html>  
    - DiagnosticReport：<https://www.hl7.org/fhir/R5/diagnosticreport-definitions.html>  
    - Provenance：<https://www.hl7.org/fhir/provenance-definitions.html>  
    - 实际支持：`Observation.effective[x]` 是值所声称成立的生理相关时间，`Observation.issued` 是该版本向 provider 可用的时间；`Specimen.collection.collected[x]` 与 `receivedTime` 分离；`Provenance.occurred[x]` 与 `recorded` 分离。  
    - **不支持**：FHIR 不保证这些字段在所有来源都齐全，也没有单独给出本研究要求的 actor-specific visibility、推断 expiry 或完整 bitemporal replay 引擎。

### 2.3 事件溯源、增量维护和血缘

13. **Microsoft Azure Architecture Center, Event Sourcing pattern（官方文档）**  
    - https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing  
    - 实际支持：append-only event store 是 system of record；replay/rehydration 可重建 state 和 materialized views；撤销通常通过 compensating event；snapshot 只是优化；event ordering、schema version/upcasting、projection lag、幂等性都是显式风险。  
    - **不支持**：普通 event sourcing 不定义 valid time、可见时间或临床证据资格；“replay 成功”不等于“按当时知识正确重放”。

14. **Gupta, Mumick & Subrahmanian (1993), “Maintaining Views Incrementally”**  
    - DOI/ACM：https://doi.org/10.1145/170036.170066  
    - 实际支持：关系或 Datalog base relation 的 insertion、deletion、update 可增量传播到 materialized view；counting 算法记录一个 tuple 的替代 derivation 数，使一个来源删除时仍可由其他 derivation 保留。  
    - **不支持**：derivation count 不等于临床证据独立性，也不提供 source identity。

15. **Budiu et al. (2023), “DBSP: Automatic Incremental View Maintenance for Rich Query Languages”**  
    - PVLDB 原文：https://www.vldb.org/pvldb/vol16/p1601-budiu.pdf  
    - DOI：https://doi.org/10.14778/3587136.3587137  
    - 实际支持：把 IVM 定义成对数据库变化流计算 query delta；覆盖完整 relational algebra、sets/multisets、aggregation、嵌套、单调和非单调递归等丰富查询。  
    - **不支持**：DBSP 不判断医学规则是否正确，也不自动保留 why-provenance。

16. **McSherry et al. (2013), “Differential Dataflow”**  
    - CIDR 原文：https://www.cidrdb.org/cidr2013/Papers/CIDR13_Paper111.pdf  
    - Microsoft Research：https://www.microsoft.com/en-us/research/?p=163907  
    - 实际支持：差分计算可增量维护变化集合上的嵌套迭代，说明复杂递归派生不必在每次更新时全量重算。  
    - **不支持**：这只是执行模型，不是临床语义或因果模型。

17. **Green, Karvounarakis & Tannen (2007), “Provenance Semirings”**  
    - 作者 PDF：https://www.cs.ucdavis.edu/~green/papers/pods07.pdf  
    - DOI：https://doi.org/10.1145/1265530.1265535  
    - 实际支持：给 base tuples 唯一 token，用多项式/semiring annotation 表示 query result 的多条 derivation，可统一 why-provenance、bag、incomplete/probabilistic DB 等多种语义，并扩展到 Datalog。  
    - **关键限定**：原始正查询 semiring 不能直接当临床“独立票数”；同源多次 derivation 的系数也可能增加。需用 source-group token + 幂等 support union，或在评分前按 source group 聚合；否定和递归的完整 provenance 更复杂。

18. **W3C PROV-DM Recommendation (2013)**  
    - https://www.w3.org/TR/2013/REC-prov-dm-20130430/  
    - 实际支持：`Entity/Activity/Agent`、usage/generation/derivation、revision、quotation、primary source、bundle 与 invalidation 的正式互操作数据模型；规范明确指出“activity 使用了 entity 并产出另一 entity”并不自动充分证明 derivation，影响关系要明确记录；invalidation 表示实体停止可用。  
    - **不支持**：PROV 只记录血缘关系，不自动级联撤销所有下游结论，也不定义医学证据权重。

---

## 3. 统一候选模板：Temporal Evidence Ledger（TEL）

### 3.1 基本原语

建议把组合候选压到以下 **8 类核心概念**；这是本文的设计提案，不是上述论文声称的标准：

1. `Subject/Object`：患者、标本、设备、药物等稳定 identity；
2. `EventVersion`：不可变事实/观察/动作/陈述/更正的版本化 envelope；
3. `TypedTime`：发生、采集、可见、记录、有效、过期等有类型的点/区间及部分序；
4. `Claim`：带极性和认识论状态的命题，不能等同于患者真实状态；
5. `ProvenanceToken`：原始来源/同源组、生成活动和 derivation edge；
6. `RuleVersion`：显式版本化的 `derive / initiate / terminate / invalidate` 变换；
7. `Projection`：从事件前缀与规则版本得到的当前/历史/任务 read model；
8. `Invariant/QueryCut`：知识截断、角色可见性、时态安全规则和拒绝条件。

`Retraction`、`Correction`、`Expiry` 不必另造 mutable primitive；它们应是引用既有 ID 的 typed event，并通过 transaction-time + negative delta 改变当前 projection。

### 3.2 状态放在哪里

- **患者真实状态不在日志里。**日志只保存“发生过的动作”“得到的观察”“某人作出的陈述”“某模型作出的推断”。
- durable source of record 是 append-only `EventVersion` journal；
- “当前已知患者状态”“过去当时的诊断视图”“治疗安全视图”都是 `Projection(stream_prefix, rule_version, task, query_cut)`；
- projection/snapshot 是可丢弃缓存，不是新事实源；每个 projection 必须记录 `input_cut`, `rule_version`, `schema_version`, `code_hash` 和支持 token。

### 3.3 时间怎样表示：二时态是底线，不是终点

每个事件/claim 至少允许以下字段；不适用字段必须显式 absent-reason，不能偷塞一个万能 `timestamp`：

```text
t_occurrence      现实中的事件/症状/动作何时发生（点或区间）
t_collected       测量/采样何时完成（点或区间）
t_available(actor) 某个角色何时首次有资格看到该版本
t_recorded        本系统何时原子提交该版本（transaction time / monotone tx_seq）
valid_interval    该 claim 声称描述患者/实体的哪个时间区间
expires_at        该证据或推断从何时起不再可用于“当前状态”读出
invalidated_at    更正、撤回、作废或质量失败从何时起生效
```

关键区分：

- `t_occurrence` 不等于 `t_recorded`；迟到资料可以描述更早的事实；
- `t_collected` 不等于 `t_available`；培养在采样数小时/数天后才发布；
- `t_available` 应按 actor/role 建模；实验室可见、临床医生可见、本系统摄取不是同一时刻；
- `valid_interval` 是命题适用期，不是数据库版本存活期；
- `expires_at` 使证据失去当前代表性，但**不删除历史观察本身**；
- `t_recorded` 必须由系统分配单调 `tx_seq`，不能只信来源机器可回拨的墙钟；来源时间仍作为带置信区间的业务时间保留。

若来源没有可靠 `issued/available`，不得为了让 replay 看起来完整而复制 `occurrence` 或猜一个精确时间。对“本系统当时能否使用”可保守采用已证明的 `t_recorded`，同时把更早的外部可见性标为 `unknown`；此时只能证明系统级无泄漏，不能声称复现了每位临床人员真实知道的内容。

### 3.4 两种历史查询必须分开

令 `v` 为临床 valid-time，`k` 为 knowledge/transaction cutoff，`a` 为决策角色，`r` 为规则版本：

```text
Eligible(e, v, k, a) :=
    e.tx_from <= k < e.tx_to
  ∧ e.visible_to(a).from <= k < e.visible_to(a).to
  ∧ clinically_relevant(e, v)
  ∧ not invalidated_as_of(e, k)

Projection(v, k, a, r) := Eval(r, {e | Eligible(e,v,k,a)})
```

必须提供两个名字不同的 API：

1. `replay_as_then(v, k, actor)`：用 `rules@k` + 当时可见证据，复现当时系统实际有资格产生的输出；
2. `reinterpret_now(v, k, actor)`：固定当时证据前缀，但用 `rules@now` 重解释，回答“以今天理论看，当时资料意味着什么”。

如果只有一个 `replay()`，团队迟早会把“法证复现”和“新理论回算”混为一谈。

### 3.5 观察怎样表示

```text
ObservationEvent {
  event_id, subject_id, observable_code, value, unit,
  method, device, specimen_id, support_context,
  t_occurrence?, t_collected?, t_available(actor), t_recorded,
  source_artifact_id, source_group_id, reliability,
  status, supersedes?, schema_version
}
```

- 观察记录默认是瞬时/区间事件，**不是自动遵守 inertia 的 fluent**；
- 只有显式声明 `persistence_policy` 的 state estimate 才能跨时间持续；
- “BP 105/65 on norepinephrine”保存为 BP observation + 同时有效的 administered-intervention event/context，不能改写成“血压正常”；
- raw observation、deterministic transform、medical inference、diagnosis hypothesis 要有不同 type，防止 inference 成为自己的 evidence。

### 3.6 干预怎样表示

计划、医嘱、开始、实际给药/操作、剂量变化、停止、拒绝、未执行必须是不同状态/事件：

```text
Planned(a) / Ordered(a) / Started(a) / Administered(a,dose) /
Adjusted(a,dose) / Stopped(a) / NotPerformed(a,reason)
```

只有执行态事件可 `initiate/terminate` 患者或 observation-channel 的 effect fluent。药物既可改变 latent-state projection，也可改变 observation model；二者应由不同 target relation 表示，避免“治疗后正常观察 = 内部状态正常”。

### 3.7 不确定性怎样表示

这里是本家族的硬弱点：标准 EC/SC/LTL/ES/BT/IVM 都没有统一的临床不确定性语义。最低安全扩展是把正、反证据分开累计：

```text
support_plus(claim), support_minus(claim)
none/none      -> unknown
plus/none      -> supported
none/minus     -> refuted
plus/minus     -> conflict
```

并保留 `not_asked / not_tested / cannot_assess / insufficient / not_applicable / out_of_model` 原因。禁止把 EC/Prolog 的 negation-as-failure 直接映射成临床阴性。概率大小、相关性和潜在机制竞争必须交给另一个明确的概率/因果/状态模型；TEL 负责输入资格、版本、血缘和输出可审计性。

### 3.8 共病怎样组合

- 多个疾病/机制可作为并行 hypotheses 或 fluent 集合存在，不强制单分类；
- 非线性交互必须是独立、版本化 interaction rule，例如 `CKD × drug -> clearance_modifier`；
- EC 可表达 context-dependent initiates/terminates，但不会从两个单病规则自动发现交互；基本 EC 对 ramification 要显式写额外规则，规则爆炸是真风险；
- 因而 TEL 原生保存组合与交互的时序/来源，却不原生推断交互强度。

### 3.9 证据血缘与同源去重

每个最小 evidence-producing act 分配 `source_group_id`；OCR、摘要、术语规范化和三个派生 label 仍共享同一 group。`source_group_id` **不能机械等同于整份文档 ID**：同一化验单里的两个独立 assay 可能是两个 evidence units，而同一体温经三种文本改写仍是一个 unit；是否独立必须是可审计的来源/采集契约。派生结论保留：

```text
Derivation {
  output_claim_id,
  rule_version,
  input_entity_versions[],
  source_group_tokens[],
  activity_id,
  created_tx
}
```

对“独立证据数”使用幂等 support-set 语义：`x + x = x`；不要把同源的三条路径当 `3x`。两个真正独立来源是 `{x,y}`。W3C PROV 可作为交换表示，semiring/provenance polynomial 可作为计算表示，但两者都不能替代“何谓独立来源”的领域契约。

### 3.10 删除/撤回如何自动失效

1. 不物理覆盖旧事件；追加 `Retracted(target_version, reason)` 或 `Superseded(old,new)`；
2. transaction-time 关闭旧版本当前可见区间，同时保留较早 `as_of(k)` 可查询；
3. base relation 发出负 delta `-target_version`；
4. IVM/DRed/counting/differential engine 递归更新所有下游 projection；
5. 若结论还有其他 independent derivation，保留并缩减支持集；否则撤销；
6. 每个 current conclusion 的 invariant 要求所有支持 token 在当前 knowledge cut 下仍 eligible。

**event sourcing 的 compensating event 自己不会完成第 3–6 步；PROV invalidation 也不会自动 cascade。依赖索引 + 增量维护是硬要求。**

### 3.11 如何扩展新知识与生成任务坐标

- 新检查：新增 observation schema/adapter + 必要单位约束，不改 journal/replay core；
- 新药物：新增 intervention concept + effect/interaction rules，不改时间或血缘 core；
- 新疾病：新增 hypothesis/mechanism rules/projection readout，不改证据 envelope；
- 新任务：声明新的 projection query；同一 evidence prefix 可同时生成 diagnosis/severity/safety/prognosis views；
- 新理论：部署新 `RuleVersion`，保留旧版本做 forensic replay；可用新版本重算旧证据，不能覆写旧输出。

---

## 4. 必须模型检查/属性测试的安全不变量

以下公式是 TEL 的建议规范，不是任何单一来源现成给出的医疗规范：

1. **NoFutureEvidence**  
   `forall d,e in support(d): first_visible(e,d.actor) <= d.knowledge_cutoff`
2. **RecordedPrefixOnly**  
   `forall d,e in support(d): e.tx_seq <= d.input_tx_seq`
3. **NoPlanAsExecution**  
   `a.status != EXECUTED => a notin applied_interventions`
4. **NoInferenceSelfSupport**  
   derivation graph 在同一 evaluation epoch 内必须无无基础的自证 cycle；递归 fixed point 每个结论必须有 base support。
5. **NoStaleSupport**  
   current conclusion 的每个 sole support 不得已撤回、过期或 superseded。
6. **ProjectionReplayEquivalence**  
   `incremental_view(prefix k) == full_recompute(prefix k)`。
7. **SourceIdempotence**  
   重复摄取同一 `event_id/source_group_id` 不改变独立证据集合和评分。
8. **AsThenRulePinning**  
   forensic replay 使用当时 rule/schema/code hash；最新 upcaster 不得静默改变原事件意义。
9. **LateDataPreservation**  
   迟到资料不得因 watermark/default window 被丢弃；只允许明确 quarantine/质量拒绝，并保留拒绝 provenance。
10. **ExplicitUnrepresentable**  
    schema/ontology 无法无损表达的输入进入 `unmodeled` + source_text，不得静默映射到近似概念。

TLA/时态逻辑最适合验证这些系统不变量；它们不负责生成临床结论本身。

---

## 5. 30 项统一压力测试预判

### 标记

- **H**：组合候选的家族本性可直接支撑；仍需正确实现，但不需要病例特例；
- **P**：可通过一个通用、可复用的 principled extension；不是病例 hardcode，但非该家族原生；
- **F**：作为独立核心存在根本冲突或需要把问题藏进任意 reducer/rule；
- **U**：测试主要落在输入适配/医学识别等外部层，或现有证据不足以判断。

表中“原生组件”区分家族本性；“实现契约/失败点”说明具体实现若省略什么就会失败。

| # | 压力测试 | 预判 | 原生组件 | 实现契约 / 失败点 |
|---:|---|:---:|---|---|
| 1 | 血压正常但依赖大剂量升压药 | P | EC/SC 可表达动作和 context | 必须把 BP observation、实际给药、latent-state estimate 分型；仅 event log 不会自动判断循环不稳定 |
| 2 | 血氧正常但依赖高流量氧疗 | P | EC/SC | 氧疗 execution 改 observation channel 与状态推断；不能把正常读数直接写成 normal-state fluent |
| 3 | 无发热但刚用退热药 | P | EC + 多时间 | 抗热药 effect interval 与体温 observation 同窗；需要医学 effect rule，非日志本性 |
| 4 | 无心动过速但 β 阻滞剂/固定频率起搏器 | P | EC/SC | 保存药物/设备 context 与 measurement；需要 observation-model modifier |
| 5 | 培养阴性但采样前已用抗菌药 | P | EC + typed time | `antibiotic.executed < specimen.collected < result.issued` 可直接表示；阴性可靠度修饰仍需医学规则 |
| 6 | 同次体温派生“体温高/发热/高热”不得重复计数 | H（组合） | PROV + source-group + provenance algebra | 三个 claim 共享同一 source token；使用幂等 support union。单独 EC/ES 为 P/F，容易三票 |
| 7 | 发热、CRP、WBC 可能共享炎症来源 | P | provenance 可保留依赖 | raw sources 通常独立，但机制相关性不是同源；需 latent mechanism/概率因子，不可由血缘假装解决 |
| 8 | 相同表型由两个机制产生 | P | 逻辑可保留多个 hypotheses | 标准 EC 是 fluent truth，不给 posterior；需 abductive/probabilistic extension，TEL 只保留并行解释与支持 |
| 9 | 同病不同患者不同表现 | P | 局部规则可扩展 | 需参数/概率/状态模型；事件规则可表达条件分支但可能规则爆炸 |
| 10 | 两项记录冲突 | P | append-only history 可同时保存 | 禁止 classical explosion 和 NAF=negative；需正反支持四态/冲突对象。单独 EC 只会报 inconsistency |
| 11 | 病历未提某症状 | P | 事件账本不必造阴性 | 必须 open-world query；禁止 Prolog negation-as-failure 直接当“症状不存在” |
| 12 | 结果采样数小时后才可获得 | H | FHIR typed time + BT | `collected`, `issued/available`, `recorded` 分离；决策 query 以 actor visibility 截断 |
| 13 | 未来最终诊断不得进入过去判断 | H | BT + query cut + temporal invariant | 所有 support 满足 visible/recorded cutoff；只按 occurrence 排序或用最新 projection 会泄漏 |
| 14 | 同一肌酐值但个人基线不同 | P | event context 可保存 baseline | 需要临床 baseline/trajectory rule；时间家族不定义“相对基线变化” |
| 15 | 同患者在两个任务下需不同坐标 | H | ES projections + IVM | 从同一 prefix 建多个 versioned task projections，不复制/改写 source events |
| 16 | 多病共存非线性交互 | P | 并行 fluents + interaction rules | EC 不自动处理 ramification；需显式可组合交互/连续模型，存在组合爆炸 |
| 17 | 治疗既改内部状态也改观察方式 | P | SC/EC action effects | 将 state-effect 与 observation-channel-effect 分成两个 target；治疗因果强度仍需外部模型 |
| 18 | 改善可能自然病程或治疗作用 | P（保留歧义） | 多 hypothesis/血缘 | TEL 可不强制归因并保留两个 explanation；从单条轨迹识别因果效应不是本家族能解决 |
| 19 | 观察过期，不再代表当前状态 | H | valid/expiry + EC termination + IVM | raw observation 永不消失；只撤销其 current-state eligibility。把 observation 设成惯性 fluent 会灾难性过期失败 |
| 20 | 新疾病不属于任何已知模板 | P | 事实日志与 disease template 解耦 | raw observations 可保存；显式 `out_of_model/refuse` 需开放世界策略，事件家族不提供 OOD 分数 |
| 21 | 新增药物只局部修改知识 | H | typed events + versioned local rules | 增 concept/effect/interaction rules；不得修改 journal/replay engine |
| 22 | 新增检查不改核心 | H | generic observation envelope | 新 schema/adapter/units；无法表达时显式 unmodeled，不改核心时间语义 |
| 23 | 新理论重新解释旧证据 | H | immutable log + versioned projection | 必须分 `replay_as_then` 与 `reinterpret_now`；latest reducer 静默重放即失败 |
| 24 | 删除原始证据后所有依赖推断自动失效 | H（组合） | retraction event + provenance + IVM | negative delta 级联，替代 derivation 仍保留；单独 event sourcing/PROV 只有记录，没有自动 cascade |
| 25 | 任意历史时点只用当时已知信息回放 | H | BT + actor visibility + rules@k | event-time、transaction-time、available-time 和 rule version 都要 pin；snapshot 仅优化 |
| 26 | 罕见关键安全规则不依赖检索想起 | H | deterministic rules + temporal monitor | 安全 invariant 常驻执行/发布门禁；检索只能调度，不能决定规则是否存在 |
| 27 | 独立来源 vs 一个来源多次改写 | H（组合） | PROV + source-group tokens | copy/normalize/summary 共用 token；独立原始来源用不同 token。普通 event_id 不等于独立性 |
| 28 | 同时保留多个候选解释，不强制单分类 | P | 逻辑允许多模型/claims | 需显式 hypothesis-set 与不确定性语义；标准 deterministic projection 可能偷偷选唯一值 |
| 29 | 无法表达必须报错而非静默近似 | P | schema validation/temporal invariant | 需 strict typed envelope + `unmodeled` 通道；无类型 event payload 会静默吞错 |
| 30 | 自然语言改写不应改变核心状态 | U | 非该家族本性 | 若 adapter 产同一 canonical event，core 稳定；但保证 paraphrase 等价属于输入适配/ontology 测试，日志无法证明 |

### 5.1 总计（组合候选，而非任一独立子家族）

- H：12 项（6, 12, 13, 15, 19, 21–27）；
- P：17 项；
- F：0 项（**仅因为这是六子家族 + 血缘契约的组合候选**；任何单独子家族都有多项 F）；
- U：1 项（30）。

这个计数**不能当排名总分**：P 中的 7/8/9/16/17/18/20/28 是整个临床计算最难的部分，不能因“逻辑上可扩展”就当已经解决。

---

## 6. 工程指标预判

| 指标 | 预判 | 条件/说明 |
|---|---|---|
| Core primitive count | 中等，约 8 类 | 比纯 event sourcing 多，但多时间、claim、rule、provenance、projection、cut 各自不可随意合并 |
| Special-case count | 时间/回放特例可接近 0；医学规则数未知 | 依靠通用 eligibility/retraction/replay 语义，而不是为每病例写时间补丁 |
| Extension blast radius | 低到中 | 新检查/药物/病应只增 schema + local rules；若要改 reducer core，说明 event 设计失败 |
| Trace completeness | 关系/规则派生可达 100% | 前提是所有 transform 记录 input tokens + rule/code hash；opaque ML 只能记录调用，不能解释内部推导 |
| Replay correctness | 很强但容易伪通过 | 必须同时 pin evidence prefix、actor visibility、rule/schema/code version；只重放 event order 不够 |
| Collision count | 时间碰撞低；医学语义碰撞未知 | typed times 避免 occurrence/available/recorded 混同；ontology collision 仍由别层负责 |
| Spurious distinction | 中风险 | event type 爆炸、同义概念/文本改写可制造伪差异；需 canonical concept + source lineage |
| Illegal cycle count | 可检测但不自动为 0 | Datalog/EC recursion 要 stratification/fixed-point/support proof；推断自证必须被 invariant 阻止 |
| Unknown handling | 原生偏弱，扩展后中强 | NAF 危险；必须显式多态 unknown/conflict/out-of-model |
| Incremental update cost | 强 | IVM/differential dataflow 对小 delta 很有优势；复杂 negation/recursion/provenance 会增加维护成本 |
| Human audit burden | 中 | append log 很长；需要按结论裁剪 support subgraph，而不是让专家阅读全流 |

---

## 7. 最坏失败模式（红队清单）

1. **单时间戳灾难**：把 occurrence/collection/available/recorded 合成一个 `timestamp`，历史诊断立即泄漏未来资料。
2. **append 顺序伪装临床顺序**：迟到检验和补录病史会被错误解释成后来才发生。
3. **latest-code replay 改写历史**：事件没变，但新 reducer/upcaster 让“当时输出”悄然变化。
4. **projection lag 被当最新真相**：event store 已收到撤回，read model 尚未消费；临床读到已失效结论。
5. **snapshot 反客为主**：快照未绑定 stream position/rule version，重放从错误基线开始。
6. **inertia 使观察永生**：一次正常 BP/SpO2 被当持续 fluent，掩盖数小时后的恶化。
7. **NAF 把未知变阴性**：没有 `happens(symptom)` 就推出 `not symptom`。
8. **补偿事件只改业务状态，不改证据资格**：撤回原始记录后，旧推断仍在另一个 projection 中存活。
9. **同源多路派生伪独立**：原记录、摘要、术语映射各投一票；即使用普通 provenance polynomial，重复路径系数仍可能变大。
10. **watermark 丢迟到资料**：流处理默认策略丢弃“过晚”但临床关键的结果，历史永远不完整。
11. **并发事件被任意 total order**：同刻给药/采样/测量被 reducer 顺序差异改变结论；需 interval/partial order 或同 epoch fixed point。
12. **规则爆炸**：每个共病组合写一个 initiates/terminates special case；基本 EC 的 ramification 弱点在医学交互中放大。
13. **递归撤回错误**：否定、聚合、cycle 下只删直接 child，没有正确 fixed-point/DRed 更新。
14. **日志被误称现实**：记录的是观察/陈述/推断，却被 projection 命名成“患者真实状态”。
15. **不可变存储与数据删除冲突**：官方 event-sourcing 文档也提示 append-only 与隐私删除存在张力；需敏感 payload 外置/密钥销毁/受控物理删除策略，同时保存非敏感审计骨架。

---

## 8. 最小可区分原型建议

为了不让这项研究停在“都能表达”，建议实现三个同数据接口的版本：

### A. 纯 Event Sourcing baseline

- append-only JSON events + reducer + snapshots；
- 预期暴露：单时间、latest reducer、删除无级联、同源多票问题。

### B. Bitemporal Event Calculus

- event/claim 表含 valid/transaction/available times；
- `initiates/terminates/holdsAt` + open-world claim status；
- 预期改善：测试 12/13/19/25；仍暴露证据 deletion 和复杂交互问题。

### C. Bitemporal Provenance + Incremental Views（TEL）

- B 的全部内容；
- source-group token、derivation graph、negative delta、IVM；
- versioned rules/projections + TLA/property invariants；
- 目标：通过 6/12/13/15/19/21–27，并对其余 P 明确报告“缺临床概率/因果模型”而不是伪通过。

### 必做判别实验

1. 同一 specimen：`collected=09:00`, `issued=14:00`, `recorded=14:07`；`replay(12:00)` 必须看不到结果，`reinterpret_now(valid=09:00)` 可看到。
2. 15:00 更正 10:00 的体温：`as_then(11:00)` 看到旧值；`current_view(valid=10:00)` 看到更正值。
3. 删除 source `s1`：只由 `s1` 支持的结论消失；由 `s1 OR s2` 支持的结论保留并只剩 `s2`。
4. 同一 source 产生三条同义 claim：独立 evidence count 始终为 1。
5. 规则 v2 部署后：`replay_as_then` 输出保持 v1；`reinterpret_now` 可输出 v2，并展示两条 trace。
6. 全量重算与 incremental projection 对每个 event prefix 完全相等。
7. 迟到事件在 watermark 之后输入仍被保留和重算，不允许 silent drop。
8. planned vasopressor 不改变 state；administered vasopressor 才触发 effect rule。

---

## 9. 保留、淘汰与推翻条件

### 9.1 当前保留意见

- **保留为任何最终架构的强候选基础设施/语义层**：多时间、未来信息隔离、版本、证据血缘、历史回放、撤回传播和安全 monitor 很难由纯向量/纯概率模型自然替代。
- **不保留为单独的完整诊疗核心**：它没有自然给出连续潜在生理状态、measurement likelihood、相关证据权重、因果反事实、治疗效应大小或 OOD posterior。
- 最合理的角色是：**固定核心中的 temporal/evidence kernel + 可验证执行边界**，上接输入适配，下接概率/因果/状态模型，外接任务 projections。

### 9.2 最强反对意见

1. 组合后原语不再“小”：event + multi-time + provenance + rule version + IVM + monitor 可能比单一概率程序更重；
2. 所有临床语义仍可能被塞进任意 reducer/rule，形成“万能事件图”而不是真正统一；
3. 非单调逻辑、冲突、概率、continuous dynamics 和递归 IVM 的组合语义很难证明一致；
4. bitemporal + actor visibility + rule version 使查询维度和审计界面复杂；
5. 如果最终概率/因果引擎不能输出细粒度可撤销 lineage，TEL 只能追到黑箱调用，Trace completeness 不是 100%。

### 9.3 什么证据会推翻当前保留意见

- 原型无法在不加入病例特例的情况下通过 12/13/19/23–27；
- incremental 与 full recompute 在否定/递归/撤回场景持续不等价；
- actor-specific availability 无法从现实 EHR 数据可靠获得，导致“as then”只能伪精确；
- rule/schema 版本绑定成本使 forensic replay 实际不可维护；
- 一个更小的候选能以更少原语同时严格证明多时间隔离、可撤销血缘和历史回放；
- 性能测试显示每次 late correction 都造成不可接受的全局重算/存储膨胀，并且 differential/IVM 不能缓解。

## 10. 给总架构比较的最终条目

```text
候选名称：Temporal Evidence Ledger（事件/动作逻辑 + 双时态事件账本 + 血缘增量视图）
基本原语：Subject, EventVersion, TypedTime, Claim, ProvenanceToken,
          RuleVersion, Projection, Invariant/QueryCut
状态位置：不可变事件历史为记录源；患者“当前/历史/任务状态”是版本化 projection
时间：occurrence / collected / actor-available / recorded(tx) /
      valid interval / expires / invalidates，支持 interval 与 partial order
观察：有上下文和血缘的 immutable observation；默认不惯性持续
干预：planned/ordered/executed/stopped 分型；只有 executed 产生 effect
不确定性：非原生；最低需正反支持四态，概率/因果需外部正式模型
共病：并行 fluent/hypothesis + 显式 interaction rule；有规则爆炸风险
血缘：source-group token + explicit derivation + rule/code version
扩展：加 schema/rule/projection，理想情况下不改 core
任务坐标：同一 event prefix 上的多个 materialized/incremental projections
天然解决：迟到资料、多时间、未来隔离、回放、修订、撤回传播、审计
需要补丁：概率、连续潜在状态、观察模型、因果识别、开放世界/OOD
最坏失败：单 timestamp、NAF=negative、measurement inertia、latest-code replay、
          stale projection、同源多票、late-data drop、recursive retraction error
当前定位：Pareto 前沿中的 temporal/evidence kernel 候选，不是独立完整赢家
```
