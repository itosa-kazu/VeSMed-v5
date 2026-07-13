# 候选家族研究 06：类型系统、代数数据类型、重写系统与逻辑编程

> 研究状态：Checkpoint 2/3 的候选调查草稿。本文只比较固定核心架构，不修改现有 VeSMed V5 runtime，也不据此提前决定最终架构。
>
> 证据标准：优先原论文、正式语言规范、官方手册和作者托管论文；所有“适合本临床问题”的判断都是本文基于来源作出的架构推论，不冒充来源原结论。

## 0. 结论先行（但不是最终选型）

1. **类型系统/ADT 不是完整的动态临床架构。** 它最擅长规定“什么对象可构造、什么操作被允许、哪些状态根本不能表示”，但它本身没有病程演化、推断调度、证据撤回或历史回放语义。把它当完整运行模型会在动态语义处另造一套隐形架构。
2. **类型系统是极有价值的固定内核约束层。** 尤其适合：认识论分层、`unknown`/`conflict` 的穷尽表示、计划与实施的 typestate 区分、纯推断与外部动作的 effect/capability 隔离、LLM 输出的可信边界。
3. **“非法状态不可表示”与“开放世界局部扩展”存在真实张力。** 闭合 ADT 给出穷尽匹配，却会因每个新医学概念而重新编译；开放 variant/row polymorphism 降低扩展爆炸，却使安全消费者必须显式处理未知扩展。可行分界是：**核心认识论状态闭合，医学词汇是带版本的开放数据 ID**，不能把每个疾病/检查做成核心构造子。
4. **线性类型不应拿来“一次性消费证据”。** 一条原始证据可合法支持多个结论；真正要去重的是其稳定来源身份。线性/仿射能力更适合一次性执行权、锁、授权或外部副作用。证据应持久引用，并携带幂等来源集合。
5. **重写逻辑是本组最像“动态固定核心”的候选。** 它把状态写成项、把局部变化写成有标签规则，并已有执行、搜索和模型检查工具。但若不额外限定，非合流、非终止和策略依赖会让临床结论取决于规则触发顺序；概率、不确定性和证据血缘也不是免费获得。
6. **Datalog/逻辑编程是本组最强的声明式推断与任务投影候选。** 正 Datalog 的最小不动点、局部规则和 provenance semiring 很适合可复查推导；但 `negation as failure` 绝不能被当作临床阴性，撤回、冲突、多解释、概率和时间都要求明确选定语义，不能笼统写成“用逻辑就解决”。
7. **ECS 与黑板架构必须单列，不能并入上述家族。** ECS 是身份—数据—行为的运行时组织/数据布局；黑板是异构知识源的协作与调度框架。两者都能做外层实现，但标准形式都没有足够的时间、证据、冲突和不变量语义，作为固定临床语义核心会产生大量隐形约定。
8. 本组值得进入后续原型赛的不是“纯类型系统”，而是两个可区分候选：
   - **typed provenance-carrying rewrite kernel**；
   - **typed temporal Datalog + explicit polarity + provenance/TMS**。
   类型/ADT/effect 是二者的共同安全层，不应被误算作第三套完整世界模型。

---

## 1. 不要把五个候选混成一个“规则系统”

| 候选 | 它主要回答什么 | 标准核心原语 | 它不自动回答什么 |
|---|---|---|---|
| 类型系统 / ADT / refinement / effect | 哪些值和程序是合法的 | 类型、构造子、函数、判断/证明、effect/capability | 世界如何随时间变化、如何选择或迭代规则 |
| 重写系统 / rewriting logic | 一个局部状态怎样变成另一个局部状态 | 项、等式、带标签重写规则、策略/可达性 | 临床不确定性如何量化、证据身份如何守恒 |
| 逻辑编程 / Datalog / ASP / CHR | 哪些结论由哪些事实和规则蕴含 | 事实、谓词、规则、不动点或稳定模型、查询 | 行动的物理执行、观察通道、概率校准 |
| Entity–Component–System | 运行时对象、数据和处理循环怎样组织 | entity ID、component data、system | 认识论层级、阴性/未知、血缘、历史真值 |
| 黑板架构 | 多个异构知识源如何共享中间假说并被调度 | blackboard、knowledge sources、controller | 全局语义一致性、因果时间、安全不变量 |

“都能写规则”不是同一种架构。类型判断是合法性元层；重写是变化语义；Datalog 是蕴含/查询语义；ECS 是数据组织；黑板是协作控制。

---

## 2. 候选 T：类型系统 + 代数数据类型 + refinement/typestate/effect

### 2.1 最小形式视图

普通 ADT 用和类型、积类型与递归类型规定可构造值。其临床价值不在“用 Rust/Haskell”，而在下列设计原则：

```text
核心闭合枚举（长期稳定）
  EpistemicKind = Observed | Reported | Deterministic | Inferred | Hypothesis
  ActionState   = Planned | Ordered | Requested | Administered | Cancelled
  Polarity      = SupportsPresence | SupportsAbsence

医学内容（开放、版本化数据）
  ConceptRef = {namespace, concept_id, version}

不能压成 nullable/Option 的认识状态
  KnowledgeState<a> =
      Supported(a)
    | ExplicitlyRefuted(EvidenceRef)
    | NotAsked
    | NotMeasured
    | Unevaluable(Reason)
    | InsufficientEvidence
    | Conflict(NonEmpty<ClaimRef>)
    | NotApplicable(Reason)
    | OutOfModel(RawPayload)
```

`Option<a>` 只能区分有/无，无法区分未问、未查、不可评价、证据不足、冲突、不适用和模型外，因此不足以通过硬性 unknown 测试。

一个候选的可信对象边界可写成：

```text
RawCandidate --parse/validate--> AcceptedObservation

AcceptedObservation = {
  evidence_id: EvidenceId,
  concept: ResolvedConceptRef,
  value: TypedValue,
  polarity: Polarity,
  epistemic_kind: Observed | Reported,
  event_time: Interval,
  collected_at: Optional<Instant>,
  available_at: Instant,
  recorded_at: Instant,
  valid_until: Optional<Instant>,
  context: MeasurementContext,
  provenance: NonEmpty<SourceAnchor>
}

DerivedClaim = {
  rule_id, rule_version, as_of,
  premises: NonEmptySet<ClaimId>,
  root_sources: NonEmptySet<EvidenceId>,
  conclusion
}
```

这里“时间有序”“provenance 非空”“推导无自证环”等不是普通字段类型能全部保证的，需要 smart constructor、refinement 或运行时 proof object。

### 2.2 统一候选模板

| 问题 | 类型/ADT 候选的回答 |
|---|---|
| 基本原语 | 闭合核心 ADT、开放医学 `ConceptRef`、带 refinement 的记录、typestate、effect row、capability token、总函数/受控 partial function |
| 状态放在哪里 | 持久不可变值或版本化快照；类型只规定形状，不规定事实存储/事件历史 |
| 时间怎样表示 | `event/collection/available/recorded/valid_until` 的不同字段类型；`KnownAt<τ>` 可作抽象接口，但动态时间比较仍需运行时验证 |
| 观察怎样表示 | `Observed`/`Reported` 构造子，带方法、支持治疗、可靠度、来源与测量上下文；绝不直接构造 latent state |
| 干预怎样表示 | typestate 区分 `Planned/Ordered/Administered`；`Administered` 必须携带执行证据。系统发出外部动作需 `ExecuteIntervention` capability/effect |
| 不确定性怎样表示 | 穷尽 ADT；数值分布可放在 `Supported<Distribution>`，但类型不替概率语义作选择 |
| 共病怎样组合 | 可用积/列表/开放集合表示多个机制；非线性交互必须由另一个计算语义定义，ADT 自身不会涌现交互 |
| 证据血缘 | `DerivedClaim` 必须含 premise 与根证据的非空、幂等集合；类型保证“字段存在”，不能保证入口没有把同源文本误分成两个 EvidenceId |
| 如何扩展新知识 | 新疾病/药物/检查作为 registry 数据和规则模块，不增加核心构造子；真正新增认识论类别才升级核心 schema |
| 怎样生成任务坐标 | `Projection<TaskTag>` 或总函数 `Snapshot -> DiagnosticView/SafetyView/...`；phantom/task types 可阻止把不同任务的坐标误混 |
| 天然解决 | 非法组合、穷尽 unknown/conflict、计划与实施分离、纯推断与副作用隔离、边界解码失败显式化 |
| 需要补丁 | 转移/推断引擎、概率/因果语义、事件历史、撤回与增量重算、任务调度、证据 ID 规范化 |
| 最坏失败 | “所有值都 type-correct”但医学语义全错；为每个医学词建构造子造成全局重编译；用 `Any/string/map` 逃逸后只剩类型幻觉 |

### 2.3 “非法状态不可表示”的精确边界

可静态或构造期排除的例子：

- `Administered` 没有 administration record；
- `DerivedClaim` 没有 premises/rule version；
- “未提及”被写成明确阴性（如果 API 根本不提供这种强制转换）；
- 推断函数拥有 `ExecuteIntervention` effect；
- 诊断坐标被直接喂给药物安全 API；
- 未识别 concept 被静默转成已识别 concept；
- 需要 `NonEmpty` 的血缘是空集合。

不能仅凭类型排除的例子：

- LLM 把“否认胸痛”抽成“有胸痛”；
- 两条不同 EvidenceId 实际来自同一份原始体温记录；
- 医学规则本身错、过时或遗漏关键条件；
- 概率模型错误地假设证据独立；
- 动态 `available_at > as_of` 的事实通过了一个漏写检查的入口；
- 外部世界实际给了药，但系统没收到回执；或反之收到伪回执。

所以可证明命题应写成：“在受信 constructor、规则编译器和 effect handler 的假设下，系统不能构造某类**编码中的非法状态**”，不能写成“类型保证医疗正确”。

### 2.4 effect 与 capability：适合约束行动，不适合代替证据

建议把计算能力分开：

```text
normalize : RawCandidate -> <Validate> Result<AcceptedObservation, Rejection>
infer     : Snapshot -> <ReadAsOf, Derive> Set<DerivedClaim>
plan      : Snapshot -> <ReadAsOf, PlanIntervention> PlannedAction
execute   : (AuthorizedAction, ExecuteCapability) -o
            <ExecuteIntervention> RequestReceipt
record_external_administration : AdministrationEvidence -> AdministeredAction
```

- effect row 使函数签名暴露其潜在副作用；Koka 的形式结果说明“无某 effect”的类型可以对应实际行为保证，但只对已形式化的语言语义成立。
- capability 使“能描述一个动作”不等于“有权发出这个动作”。
- `ExecuteCapability` 可做线性/仿射资源，避免重复执行请求。
- **EvidenceRef 不应线性消费。** 同一 ECG 或体温记录可被诊断、安全和科研投影同时合法引用；应以稳定 `EvidenceId` + 幂等集合做去重。
- 系统外已实施治疗必须能由执行证据直接记录，不能要求它曾由本系统 plan；否则真实急救/外院给药会变成不可表示。

### 2.5 闭合 ADT 与开放世界的处理原则

闭合 variant 的优势是穷尽匹配；开放 variant/row polymorphism 的优势是局部扩展。两者不能无代价兼得：

1. 核心语义类型（观察/推断/计划/实施/冲突/模型外）应闭合，新增构造子属于核心版本升级。
2. 医学概念不应是 variant 构造子，而是外部可解析的 `ConceptRef` 数据；新病、新药、新检查只增加 registry 与规则。
3. 未识别扩展必须成为 `Unresolved/OutOfModel`，安全路径默认拒绝；绝不能通配后忽略。
4. 真正使用 extensible variant 的消费者必须有显式 default case。OCaml 官方手册也明确：对 extensible variant 的 pattern matching 需要 default case 处理未知构造子。
5. schema 版本、规则版本和概念版本都要进入 provenance；否则旧证据“重新解释”无法复查。

### 2.6 LLM 可填契约：只能产出不可信候选

推荐分层，不让 LLM 直接构造 trusted ADT：

```text
1. LLM -> RawCandidate(JSON + source span + uncertainty)
2. JSON Schema -> 仅结构/局部约束
3. terminology resolver -> ResolvedConcept | UnresolvedConcept
4. semantic validator -> 时间顺序、单位、上下文、证据身份、跨字段不变量
5. smart constructor -> AcceptedObservation / Rejection
6. rule engine -> DerivedClaim（LLM 无权直接写入）
```

必须区分：

- JSON Schema 能验证结构和关键词约束，不证明医学语义；
- host-language type checker 只信 decoder 返回的值；decoder/validator 属于 TCB；
- LLM 可提议新规则，但规则应进 quarantine，经过 type/effect check、反例测试、版本签名和人工审查后才可执行；
- 任何未知字段、未知枚举值、无法解析 unit/concept 都应显式拒绝或保留 raw provenance，不应静默丢弃。

### 2.7 可证明不变量与证明负担

| 不变量 | 可能证明方式 | 真实限制 |
|---|---|---|
| 计划不等于已实施 | ADT/typestate，`Administered` constructor 要 execution evidence | 外部证据真实性不由类型保证 |
| 纯推断不能发治疗请求 | effect/capability typing | unsafe/FFI/错误 handler 可破坏；需缩小 TCB |
| unknown 不会被当 false | 无 `KnowledgeState -> Bool` 的默认总转换；所有 pattern match 穷尽 | 新代码可故意写错误映射；需 lint/审计 |
| 所有推导都有非空血缘 | `NonEmpty` refinement | 同源事实是否被分配同一 ID 属于入口治理 |
| as-of 查询不读未来 | `Snapshot<τ>` 抽象接口 + constructor 检查 | 动态时间/数据库查询仍需运行时实现正确 |
| 任务投影不混型 | `Projection<TaskTag>` | 同一投影内部的医学计算仍可能错 |

**关键结论：** 类型证明适合“安全壳”和局部程序性质；它不是临床世界模型，也不自动证明知识库的全局一致性。

---

## 3. 候选 R：类型化项重写 / rewriting logic

### 3.1 正式核心

重写逻辑可写为重写理论：

```text
R = (Σ, E, Rules)
```

- `Σ`：带 sort 的签名，定义状态项和构造子；
- `E`：等式/结构公理，定义哪些项表示同一状态（如 multiset 的结合、交换，来源集合的幂等）；
- `Rules`：有标签、可带条件的局部转换 `l -> r if C`；
- 一次重写既可解释为状态转移，也可解释为一次逻辑推导。

用于本问题时，推荐状态不是“可任意覆盖的当前病人对象”，而是：

```text
KernelState = <History, MaterializedClaims, PendingActions, RuleSetVersion, AsOf>
```

原始事件只 append/tombstone，不被推断规则擦除；可丢弃、过期和撤回的是 materialized claim，而非原始血缘。

### 3.2 统一候选模板

| 问题 | 重写逻辑候选的回答 |
|---|---|
| 基本原语 | typed term/sort、equation、labeled guarded rewrite rule、配置的组合运算、策略/搜索 |
| 状态放在哪里 | 一个可组合的全局项或 multiset configuration；局部规则只匹配和改写相关子项 |
| 时间怎样表示 | 时间是显式状态和 guard；instantaneous rule 与 tick/time-advance rule 分开，或以 `as_of` 重物化历史 |
| 观察怎样表示 | 不可变 `Observation` 项；观察到的正常值不直接重写成 latent-normal，必须经带上下文的显式规则 |
| 干预怎样表示 | `Planned/Authorized/RequestSent/Administered` 项与有能力约束的转移；治疗对内部状态和观察通道是两组不同规则 |
| 不确定性怎样表示 | 显式多个分支/项、权重扩展或概率重写；标准 rewriting logic 并不自带临床概率或置信语义 |
| 共病怎样组合 | configuration 是可组合 multiset；多项 LHS 的规则可表达非线性交互和条件性 |
| 证据血缘 | 每个产生 derived term 的规则必须把 `rule_id/version/premise_ids/root_sources` 带到 RHS；重写逻辑本身不会自动替设计者补血缘 |
| 如何扩展新知识 | 加模块、sort 的数据实例或局部规则；若规则只依赖稳定接口，blast radius 小 |
| 怎样生成任务坐标 | 纯 equational normalization、readout rewrite 或 query；读出规则必须与改变病人状态的规则分层 |
| 天然解决 | 局部变化、并发/组合、转移可执行、可达性搜索、反例路径、显式策略、有限抽象上的不变量/LTL 检查 |
| 需要补丁 | 双/多时间、开放世界状态、provenance 纪律、概率语义、撤回/TMS、规则版本、确定性 materialization |
| 最坏失败 | 非合流导致结果依赖执行顺序；循环导致不终止；组合状态爆炸；“策略”暗中变成疾病优先级 hardcode |

### 3.3 两个必须分开的 rewrite 层

如果把所有医学变化都放在一个自由重写池里，最坏故障不可接受。至少分成：

1. **规范化层 `E/canonicalization`**
   - 单位、同义 concept、source-set union、结构正规化；
   - 应尽量证明 termination + Church–Rosser/confluence；
   - 同一输入不应因规则顺序产生两个 canonical form。
2. **变化/推断层 `Rules`**
   - 病程事件、干预、观察通道、假说生成；
   - 多个解释可合法并存，因此不能靠“强行合流成单一诊断”解决；
   - 非确定性必须输出显式分支/possible explanations，而不是默认策略选中一个后丢弃其余。

Maude 官方手册明确区分：功能模块要求 Church–Rosser，而系统重写规则可以不合流、也可以不终止，此时策略选择至关重要。这正是本候选的力量，也是临床安全风险。

### 3.4 临床反例的规则形状

正常血氧依赖高流量氧疗：

```text
[observe-spo2]
Observation(e1, SpO2=98%, support=HFNO(60L), available_at=a), a <= as_of
  -> ObservedValue(SpO2=98%, context=HFNO(60L), roots={e1})

禁止直接：
ObservedValue(SpO2=98%) -> LatentState(Oxygenation=Normal)
```

计划与实施：

```text
[request]
Authorized(plan, capability) -> RequestSent(receipt)

[record-administration]
AdministrationEvidence(e2, drug, dose, time) -> Administered(..., roots={e2})

不存在 Planned -> Administered 规则。
```

同源改写去重：

```text
root_sources(HighTemp(e1)) = {e1}
root_sources(Fever(e1))    = {e1}
root_sources(Temp42(e1))   = {e1}

union 使用 ACI + idempotence，不能把三个 derived term 当三份独立根证据。
```

### 3.5 证明能力与证据缺口

已有 Maude 工具链支持 search、invariant/LTL model checking、termination/Church–Rosser/coherence 检查；Real-Time Maude 说明显式时钟和 tick rule 可编码实时/混合系统。

但应把证明结论写窄：

- 有限状态或给定抽象上没有找到未来信息泄漏，不等于无限临床状态已完全证明；
- bounded search 未发现反例不是全局证明；
- 概率、连续动力学和无限值域会迅速造成状态爆炸；
- 如果规则库每次扩展都破坏 confluence/termination/coherence，局部扩展只是表面上的；
- 规则优先级和 strategy 必须版本化、可追踪并算入核心语义，不能藏在 scheduler。

### 3.6 本候选的淘汰条件

在统一原型中若出现任一项，则“自由重写系统作为固定核心”应淘汰或大幅收缩：

1. 相同历史和相同规则版本因执行顺序给出不同 materialized clinical state，且差异没有显式分支语义；
2. 新增一条局部药物规则频繁破坏全局 termination/confluence；
3. 为避免循环而依赖大量 ad hoc priority；
4. provenance 只能靠每条规则人工复制且漏写无法由 type checker 拒绝；
5. 30 个压力测试需要把事件溯源、TMS、概率、查询和类型系统全部作为互不约束的外挂，核心反而没有减少原语。

---

## 4. 候选 L：逻辑编程（Datalog / ASP / CHR 必须区分）

### 4.1 基线候选：typed temporal Datalog + explicit polarity + provenance

正 Datalog 的状态可理解为 extensional facts，加规则最小不动点得到 intensional facts。一个适合压力测试的关系骨架是：

```text
observation(
  evidence_id, subject_id, concept_id, typed_value, polarity,
  event_start, event_end, collected_at, available_at, recorded_at, valid_until,
  method, support_context, source_anchor
)

derived(
  claim_id, rule_id, rule_version, as_of,
  premise_ids, root_evidence_ids, proposition, polarity
)

usable(E, T) :- observation(E, ..., Available, ..., Expires, ...),
                Available <= T,
                (Expires = none ; T < Expires).
```

绝对禁止：

```text
absent(Symptom) :- not present(Symptom).
```

临床阴性必须有 `polarity=SupportsAbsence` 的原始证据；`not present` 最多表示在一个已封闭关系的当前 materialization 里没有找到 tuple，不能表示“患者没有症状”。

### 4.2 统一候选模板

| 问题 | 逻辑编程候选的回答 |
|---|---|
| 基本原语 | typed relation/fact、Horn/Datalog rule、query、fixpoint；可选显式 negation、stable model、constraint store、provenance annotation |
| 状态放在哪里 | EDB 原始事实 + IDB 派生事实/materialized views；若要回放，EDB 必须来自版本化事件历史 |
| 时间怎样表示 | 关系参数与强制 `available_at <= as_of` guard；普通 Datalog 没有自动的临床时间语义 |
| 观察怎样表示 | 独立 `observation/reported` 谓词，带 polarity、方法、context 和 source；不与 latent/hypothesis 谓词混表 |
| 干预怎样表示 | `planned/ordered/administered` 不同谓词；规则可推演后果，但外部执行仍需 capability/receipt 层 |
| 不确定性怎样表示 | 显式支持正/负的四态、possible worlds/stable models、概率扩展；必须选一个有明确定义的语义 |
| 共病怎样组合 | 多前提规则、递归和高阶关系可写交互；交互知识仍需显式规则，可能组合爆炸 |
| 证据血缘 | provenance semiring/derivation DAG/TMS；`+` 表示替代推导、`×` 表示共同使用，但不等于统计独立性 |
| 如何扩展新知识 | 加 facts/rules/views，通常不改求值器；规则的非局部相互作用仍需 regression |
| 怎样生成任务坐标 | 查询或 materialized view，自然支持多个 task-specific readout |
| 天然解决 | 声明式局部规则、递归、固定点、多个推导、查询投影、解释路径、增量物化 |
| 需要补丁 | 开放世界纪律、显式阴性、双/多时间、概率/因果、撤回、冲突策略、外部动作 capability |
| 最坏失败 | negation-as-failure 把未知变阴性；递归+negation 出现多/无稳定模型；provenance 爆炸；局部规则导致全局意外结论 |

### 4.3 provenance semiring 能做什么，不能做什么

Green、Karvounarakis、Tannen 的 provenance semiring 把关系 tuple 标注推广到关系代数和 Datalog：

- `x + y`：结论可由两个替代支持得到；
- `x * y`：某个推导共同使用两份输入；
- 保留多项式可恢复“为什么得到该 tuple”。

临床使用必须再加两条限制：

1. **推导次数不是独立证据数。** `Fever(e1)`、`HighTemp(e1)`、`Temp42(e1)` 的三条路径仍只有根证据 `{e1}`。不能把多项式项数或系数直接当置信度。
2. 同时保留：
   - 完整 derivation expression（可审计路径）；
   - `root_sources : Set<EvidenceId>` 的幂等投影（去重/独立性检查）。

递归 Datalog 的 provenance 甚至可能是形式幂级数；解释大小和存储爆炸必须进入运行成本测试。

### 4.4 删除、撤回与多解释

普通正 Datalog 的单调性很适合追加事实，但测试 24 要求删除原始证据后所有依赖自动失效，需要额外机制：

- DRed/delete-and-rederive 或 counting 增量视图维护；
- Doyle TMS / de Kleer ATMS 式 justification 与 assumption set；
- versioned rematerialization。

ATMS 的重要价值是同时保留多组假设环境并避免把一个当前选择当唯一世界；但它是 reasoning subsystem，不是完整的时间/观察/行动架构。

### 4.5 冲突/unknown：三条不同路线，不得混称“逻辑支持”

1. **显式四态/双支持**
   - 用 `(has_positive_support, has_negative_support)` 得到 neither / true-only / false-only / both；
   - 最适合保留 unknown 与 conflict；
   - 不自动给出“冲突时信哪边”。
2. **possible worlds / contradiction-aware Datalog**
   - 可保留多个一致解释；
   - 世界数和概率计算可能昂贵，且“如何拆冲突”本身是一项语义决定。
3. **ASP / stable model semantics**
   - 很适合默认、选择和组合搜索；
   - 程序可能有多个稳定模型或无稳定模型；若 UI 只展示求解器找到的第一个，就重新引入隐式单分类。

因此，不可在架构文档中只写“使用逻辑编程表示冲突”。必须写清具体语义、是否允许爆炸、如何输出多模型、如何处理无模型。

### 4.6 CHR 是约束多集重写，不等于 Datalog

Constraint Handling Rules (CHR) 使用多头 multiset rewrite rule 操作 constraint store，兼有逻辑/重写特点：

- 多头规则自然表达“两个机制/药物/风险同时出现才触发交互”；
- simplification/simpagation 可删除或保留约束；
- confluence、termination 可分析；
- justification 扩展可支持逻辑撤回。

风险：

- 实际 CHR 常有 committed-choice/精化操作语义；若程序不合流，结果可能依赖触发顺序；
- propagation history 防止同一规则实例反复触发，不等于同源临床证据去重；
- host language 的类型/mode 有时只是声明而非强制检查；
- 仍需显式时间、血缘、unknown/conflict、概率和行动 capability。

CHR 可以作为 typed rewrite 原型的实现参照，但不应被当作“Datalog 的同义实现”。

### 4.7 本候选的淘汰条件

1. 任何压力测试中以 relation 缺席推断临床阴性；
2. as-of 查询可以绕过统一 availability guard；
3. 删除输入后依赖结论仍残留；
4. 多个 stable models/冲突世界被静默压成一个；
5. provenance 的多条语法路径被当成多份独立证据；
6. 新增局部规则导致无法解释的全局循环或模型爆炸，且没有静态 lint/依赖分析/预算拒绝机制。

---

## 5. 独立对照候选 E：Entity–Component–System（ECS）

ECS 不是类型系统、重写逻辑或逻辑编程。Unity 官方定义把 identity、data、behavior 分成 entity、component 和 system；entity 本身只是 ID，components 存数据，systems 处理数据。

### 5.1 统一候选模板

| 问题 | ECS 候选的回答 |
|---|---|
| 基本原语 | entity ID、component data、system、world/query/archetype |
| 状态放在哪里 | entity 关联的 component 集合，通常为当前运行状态 |
| 时间怎样表示 | 必须自行加 timestamp/event components 和历史 store；帧更新不是临床双/多时间 |
| 观察怎样表示 | Observation components；component 缺席很容易被误读为否定 |
| 干预怎样表示 | command/action components + systems；计划/实施、授权/回执都需额外组件协议 |
| 不确定性怎样表示 | 另加 status/conflict/hypothesis components；标准 ECS 不定义其逻辑 |
| 共病怎样组合 | 多 components + matching systems，组合和局部扩展容易；非线性交互写在 system 中 |
| 证据血缘 | 另加 provenance graph/IDs；ECS query 本身不保存推导路径 |
| 如何扩展新知识 | 加 component/system，数据布局与并行处理通常很好；系统依赖和调度仍有全局影响 |
| 怎样生成任务坐标 | 不同 systems/queries 选择 component 组合 |
| 天然解决 | 组合式运行时数据组织、批处理、缓存局部性、并行系统 |
| 需要补丁 | 几乎所有临床语义：时间、证据、unknown、冲突、重放、撤回、因果/概率 |
| 最坏失败 | component presence 被当真值；derived components 重复计数；system 顺序成为隐形医学语义；删除 component 丢历史 |

### 5.2 压力测试判决

ECS 的 3 个原语很少，但这是**运行时组织的最小性**，不是语义最小性。要通过测试 6、11、13、23–27，必须再造事件历史、provenance、truth maintenance、时态查询和类型不变量。届时核心语义实际来自外挂，而不是 ECS。因此：

- 可保留为优化/执行层 D 的候选；
- 作为固定核心 A，目前是硬失败；
- “新增 component 不改 entity class”不能证明新增医学知识不改核心语义。

---

## 6. 独立对照候选 B：黑板架构

Hearsay-II 的黑板架构让独立 knowledge sources 通过共享 hypotheses 协作，并用控制器调度最有希望的增量动作。它天然适合异构专家/LLM 代理共享中间假说，但这属于协作与资源调度，不等于临床真值语义。

### 6.1 统一候选模板

| 问题 | 黑板候选的回答 |
|---|---|
| 基本原语 | blackboard、分层 hypotheses、knowledge sources、controller/scheduler |
| 状态放在哪里 | 共享 blackboard 的当前 hypotheses/partial solutions |
| 时间怎样表示 | Hearsay-II 可按 speech time 组织 hypotheses，但临床 `occur/collect/available/record/valid` 仍需另建 |
| 观察怎样表示 | 某一层的输入/假说；若没有 typed partition，观察、推断和计划很容易混写 |
| 干预怎样表示 | knowledge source 写 action proposal；实际执行权、回执和状态转移不是标准黑板语义 |
| 不确定性怎样表示 | 多个竞争 hypotheses 可并存，并可带评分；评分含义由各 knowledge source 定义 |
| 共病怎样组合 | 多知识源共同修改 hypotheses，表达力强但组合语义不统一 |
| 证据血缘 | Hearsay-II 有 interlinked hypotheses，但通用黑板不保证根证据守恒或去重 |
| 如何扩展新知识 | 加 knowledge source 相对局部；controller 和共享 schema 可能成为全局瓶颈 |
| 怎样生成任务坐标 | task-specific knowledge source/readout 或不同 blackboard level |
| 天然解决 | 异构模块协作、多假说、机会式推理、资源有限时的调度 |
| 需要补丁 | 类型、时态、provenance、撤回、冲突逻辑、安全 capability、确定性重放 |
| 最坏失败 | 调度优先级决定医学结论；共享可变状态污染；知识源相互强化形成自证环；回放非确定 |

### 6.2 压力测试判决

- 黑板对测试 8、18、28（多解释并存）很自然；
- 对测试 6、13、24–27 没有原生保证；
- “controller 优先运行最有希望知识源”是计算资源策略，不得被解释为疾病 posterior；
- 让 LLM agents 写 blackboard 更易集成，却会把核心语义正确性托付给调度和 prompt，违反任务边界。

最合理定位是输入/推断模块的**协作外壳**或优化层，而不是固定核心。

---

## 7. 30 项统一压力测试矩阵

记号：

- **N**：该形式主义原生或用极小、惯用构造即可表达；
- **C**：只有把额外语义明确写入固定核心才能通过，不能算形式主义免费能力；
- **F**：标准/朴素形态会违反硬不变量，不能作为 standalone 核心；
- 本表评价的是家族的朴素强项与补丁负担，不是尚未实现的原型实测分数。

与仓库总表的 `H/P/F/U` 记号对应时：本文 `N` 只表示“有希望以该家族惯用原语通过”（约等于预判 `H`），`C` 表示“需要显式补充核心契约”（约等于 `P`），`F` 同为硬失败；在原型未运行前，二者都不能冒充实测 `PASS`。

列：`T`=类型/ADT/effect 单独；`R`=typed rewriting logic；`L`=typed Datalog/显式 polarity/provenance；`E`=ECS；`B`=黑板。

| # | 压力情形 | T | R | L | E | B | 决定性说明 |
|---:|---|:---:|:---:|:---:|:---:|:---:|---|
| 1 | 正常 BP 依赖升压药 | C | N | C | C | C | 都必须把支持治疗放入观察 context；类型只区分，R 可直接定义 observation-channel rule |
| 2 | 正常 SpO2 依赖高流量氧 | C | N | C | C | C | 禁止 `normal observed -> latent normal` 的默认转换 |
| 3 | 无热但刚退热 | C | N | C | C | C | 观察通道受 intervention 修饰，不是单一布尔事实 |
| 4 | β 阻滞剂/起搏下无心动过速 | C | N | C | C | C | 同上；ECS/黑板不会自动强制 context |
| 5 | 抗菌药后培养阴性 | C | N | C | C | C | 显式采样与给药时序；缺 guard 即失败 |
| 6 | 同次体温派生三标签不可三票 | C | C | C | F | F | 需要稳定 root EvidenceId + 幂等 source set；provenance polynomial 也不等于独立性 |
| 7 | 发热/CRP/WBC 共享来源 | C | C | C | F | C | 必须显式 latent/common-cause 或依赖结构，任何家族都不会自动发现 |
| 8 | 同表型来自两机制 | N | N | N | C | N | sums/branches/multiple derivations/blackboard hypotheses 都自然支持 |
| 9 | 同病不同表现 | C | N | N | C | N | R/L/黑板可保留多模式；类型本身无生成模型 |
| 10 | 两记录冲突 | N | N | C | C | C | ADT 可原生 `Conflict`；L 必须选四态/possible-world 语义，黑板仅“共存”不等于冲突处理 |
| 11 | 病历未提某症状 | N | C | C | F | C | `NotAsked/NotMentioned` 显式构造；component/tuple 缺席不可当阴性 |
| 12 | 采样后数小时结果才可用 | C | C | C | C | C | 标准 rewrite 没有知识时间；R/L 都必须显式加入 `available_at` 与统一 cutoff guard |
| 13 | 未来最终诊断不得进过去 | C | C | C | F | F | R/L 可编码双时间查询，但都不是各自最小形式自动携带；ECS/黑板当前态默认易泄漏 |
| 14 | 同肌酐不同个人基线 | C | N | N | C | C | baseline 是 context/subject parameter；不能只按绝对值类型 |
| 15 | 同患者两任务不同坐标 | N | C | N | N | N | typed projection 与 Datalog query 最自然；R 要独立 readout 层 |
| 16 | 共病非线性交互 | F | N | N | C | C | 纯类型无运行语义；R 多项 LHS、L 多前提规则自然但知识仍需显式 |
| 17 | 治疗改内部状态又改观察方式 | F | N | C | C | C | R 可分两类 transition；其它需另加动态/因果语义 |
| 18 | 改善可由自然病程或治疗 | C | N | N | C | N | 必须保留多解释，不强行单因；概率归因仍非免费 |
| 19 | 观察过期 | C | N | C | C | C | `valid_until` + materialization/retraction；仅 timestamp 字段不够 |
| 20 | 新病不属已知模板 | C | C | C | C | C | 都需显式 OOD/OutOfModel readout；“可存未知 ID”不等于会检测 OOD |
| 21 | 新增药物局部修改 | C | N | N | N | N | T 只有把药物作为数据而非构造子才局部；所有候选仍需交互 regression |
| 22 | 新增检查不改核心 | C | N | N | N | N | 同上；新检查若要求新语义类型则应版本升级 |
| 23 | 新理论重释旧证据 | F | C | C | F | F | 需要原始历史 + 规则版本 + 重物化；不是类型/ECS/黑板的原生性质 |
| 24 | 删除原证据使依赖失效 | F | C | C | F | F | R 需 justification/retraction；L 需 DRed/TMS；静态类型不能维护动态依赖 |
| 25 | 历史回放只用当时已知 | F | C | C | F | F | R 需显式历史/as-of，L 需 temporal EDB；current-state ECS/黑板硬失败 |
| 26 | 罕见安全规则不能靠检索想起 | N | N | N | C | F | 编译期 capability/始终装载规则可保证；机会式黑板调度不够 |
| 27 | 独立来源 vs 同源改写 | C | C | C | F | C | lineage 可表达，但“独立”是来源语义，不由路径数量自动推出 |
| 28 | 同时保留多个候选解释 | N | N | N | C | N | ADT set、rewrite branches、possible worlds/ATMS、blackboard hypotheses |
| 29 | 无法表达须显式报错 | N | N | C | C | F | closed types/sorted terms 最强；L 要 schema/type check；黑板自由对象易静默容忍 |
| 30 | 自然语言改写不改变核心状态 | C | C | C | C | C | 这是输入适配与 canonicalization 合约；没有任何候选能凭核心形式主义自动保证 |

### 7.1 由矩阵得出的硬结论

- **T 单独淘汰为完整核心**：测试 16、17、23–25 暴露它没有动态/推断/回放语义；但保留为所有强候选的安全层。
- **ECS standalone 淘汰**：最关键的证据守恒、unknown、future leakage、撤回、回放均要外挂。
- **黑板 standalone 淘汰**：多假说强，但确定性、来源守恒和安全规则覆盖不足。
- **R 与 L 保留进入原型**，但都还没有天然通过所有硬测试：R 最大风险是非合流/非终止/策略；L 最大风险是 closed-world negation、撤回和模型/血缘爆炸。
- 测试 6、7、20、27、30 对所有家族都不是免费能力，是后续统一原型最有区分力的反例。

### 7.2 与固定要求及补充测试 T31–T40 的映射

这组候选必须至少覆盖 `REQUIREMENTS.md` 中的 `R-EPI-01/02`、`R-TIME-01..03`、`R-UNC-01/02`、`R-PROV-01..03`、`R-INT-01/02`、`R-COMP-01/02`、`R-OPEN-01`、`R-REP-01` 和 `R-SAFE-01/02`。类型层主要承担 `R-EPI-01`、`R-UNC-01`、`R-INT-01`、`R-SAFE-01` 的构造边界；动态候选 R/L 则必须证明其余时序、依赖和执行不变量。不能因为共享了 typed decoder，就把动态候选缺失的能力记成类型层已替它通过。

| 补充测试 | T | R | L | E | B | 关键判别 |
|---|:---:|:---:|:---:|:---:|:---:|---|
| T31 推断循环不得增信 | C | C | C | F | F | 正 Datalog 有最小不动点，但 provenance/support 聚合仍需幂等约束；R 必须检查 critical cycle/strategy |
| T32 晚到修正不篡改旧快照 | F | C | C | F | F | 两者都需双时间 append-only 事实与选择性重物化 |
| T33 单位/方法不可比须拒绝 | N | N | C | C | F | sorted/refined term 最直接；转换规则仍须版本化并留 trace |
| T34 同证据跨模块汇总仍幂等 | C | C | C | F | F | 任一家族都必须按 root EvidenceId 合并，不能按路径数计票 |
| T35 连续近似 posterior 可审计 | C | C | C | C | C | 算法、参数、seed、近似误差是跨家族的 model-call 契约，不由本组形式主义免费提供 |
| T36 停用知识规则后的新旧重放 | F | C | C | F | F | R 要规则集版本 + 重物化；L 要 program version + view maintenance |
| T37 动作阶段合法转换 | N | N | C | C | F | typestate/重写最自然；任何执行 effect 仍需外部 receipt |
| T38 交互模块接口不匹配 | N | N | C | C | F | sort/type/module signature 可加载前拒绝；自由黑板对象最易静默忽略 |
| T39 模型不兼容不得无记录平均 | N | N | N | C | C | 可把 disagreement 作为显式和类型/分支/假说集；仲裁不是自动正确 |
| T40 历史回放不得命中未来缓存 | F | C | C | F | F | cache key 必须含双 cutoff、规则/概念/模型版本；缓存属于优化层但要服从语义层 |

这里的 `N/C/F` 仍是设计前预判。尤其 T31、T34、T40 必须用故障注入验证，不能靠类型签名或规则文本“看起来正确”判过。

---

## 8. 工程指标与预期 Pareto 位置（待原型实测，不伪造总分）

| 维度 | T 类型/ADT | R 重写逻辑 | L Datalog/逻辑 | E ECS | B 黑板 |
|---|---|---|---|---|---|
| 原语表面数量 | 低 | 低—中 | 低 | 极低 | 低 |
| 为通过硬测试所需语义外挂 | 极高 | 中 | 中 | 极高 | 极高 |
| 非法状态静态排除 | 最强 | 强（若 typed/sorted） | 中 | 弱—中 | 弱 |
| 局部变化/干预语义 | 无 | 最强 | 中 | 强但无临床语义 | 中 |
| 声明式推断/任务查询 | 弱 | 中 | 最强 | 中 | 中 |
| provenance 理论基础 | 需自建 | 需契约 | 最强 | 无 | 局部链接但不统一 |
| 历史回放 | 无 | 强（显式历史时） | 中—强 | 弱 | 弱 |
| unknown/conflict | 强表示 | 强表示、需规则 | 需显式选择语义 | 弱 | 多假说强、真值语义弱 |
| 扩展 blast radius | 闭合 ADT 高；数据 ID 低 | 通常低，受 critical pairs 影响 | 通常低，受全局依赖影响 | 低布局、高语义 | 低模块、高调度 |
| 最危险静默错误 | type-correct semantic bug | 顺序/策略依赖 | NAF=阴性、模型选择 | component absence=否定 | scheduler=医学判断 |

不能仅凭“核心原语少”给 ECS/黑板高分；必须把为通过压力测试新增的协议、特殊规则和隐藏调度算入 **Special-case count** 与 **Core primitive count**。

---

## 9. 建议的判别原型，而非继续文字争论

建议让 R 与 L 使用完全同一份输入协议和同一组核心概念，只实现五个高信息量测试：

1. **T6/27 同源去重**：一个体温 EvidenceId 派生三表述；另有两份真正独立来源。输出完整 derivation 与 root-source set。
2. **T12/13/25 时间回放**：采样、可用、记录时间不同；`as_of` 前后两次重放必须不同且无未来泄漏。
3. **T10/28 冲突与多解释**：相互冲突记录 + 两个机制，不允许静默选择单一解释。
4. **T24 撤回**：删除/作废一个原始证据，所有且仅有依赖它的派生失效。
5. **T29 非法状态**：尝试创建无执行证据的 `Administered`、无 premises 的 `Derived`、未知字段/概念；必须显式拒绝。

公平约束：

- 两个原型共享同一 typed input decoder；
- 不允许某个候选拥有额外医学特例；
- 记录核心原语、规则数、额外 guard 数、代码行、全量/增量耗时、trace 大小、replay correctness、rule-order sensitivity；
- R 原型随机化规则顺序，检测 materialization 是否漂移；
- L 原型分别开启/禁用 negation，证明 missing 不会成为 negative；
- 新增一个药物规则后重新测 global confluence/dependency graph，量化 extension blast radius。

**最有价值的下一项判别实验：** 在相同 10 万事件、1 万派生和 5% 撤回流量下，比较 typed rewrite materializer 与 provenance Datalog/DRed 的 trace completeness、增量成本、规则顺序敏感性和删除正确性。这个实验比再讨论“规则还是图”更能推翻候选。

---

## 10. 第一手来源账本

### 10.1 类型、ADT、refinement、typestate、effect/capability

1. **Milner, Tofte, Harper, MacQueen, _The Definition of Standard ML (Revised)_, 1997.** 形式语言规范，给出 core/module 的静态与动态语义以及 datatype/type inference 背景。  
   URL: https://smlfamily.github.io/sml97-defn.pdf
2. **Rust Reference, “Enumerations”.** 官方规范：enum 同时定义名义枚举类型和构造子；zero-variant enum 无合法值。支持“用构造子限定可表示状态”的基础命题。  
   URL: https://doc.rust-lang.org/reference/items/enumerations.html
3. **OCaml Manual, “Polymorphic variants” 与 “Extensible variant types”.** 官方手册：开放/可扩展 variant 的模块化能力及未知构造子必须有 default case 的代价。  
   URLs: https://ocaml.org/manual/5.2/polyvariant.html ; https://ocaml.org/manual/5.5/extensiblevariants.html
4. **Rondon, Kawaguchi, Jhala, “Liquid Types”, PLDI 2008.** 原论文/作者托管 PDF：以受限 refinement predicate 与推断结合验证数据结构/程序性质。  
   URL: https://ranjitjhala.github.io/static/liquid_types.pdf  
   DOI: https://doi.org/10.1145/1379022.1375602
5. **Strom, Yemini, “Typestate: A Programming Language Concept for Enhancing Software Reliability”, IEEE TSE 1986.** 原论文记录：typestate 在特定上下文限制可用操作，并在编译期发现语法合法但语义未定义的序列。  
   URL: https://research.ibm.com/publications/typestate-a-programming-language-concept-for-enhancing-software-reliability  
   DOI: https://doi.org/10.1109/TSE.1986.6312929
6. **Wadler, “Linear Types Can Change the World!”, 1990.** 原作者托管版本：线性值恰好使用一次；本文据此推论一次性 execution capability 合适、持久临床证据不合适。  
   URL: https://homepages.inf.ed.ac.uk/wadler/papers/linear/linear.ps
7. **Leijen, “Koka: Programming with Row-polymorphic Effect Types”, MSR-TR-2013-79.** 原论文：effect 出现在类型签名、row polymorphism、以及缺少某 effect 所对应的行为保证。  
   URL: https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/koka-effects-2013.pdf
8. **Plotkin, Pretnar, “Handlers of Algebraic Effects”, ESOP 2009.** 原论文：对 exception、state、time、nondeterminism、concurrency 等 algebraic effects 的统一 handler 处理。  
   URL: https://www.pure.ed.ac.uk/ws/portalfiles/portal/17909848/Plotkin_Pretnar_2009_Handlers_of_Algebraic_Effects.pdf  
   DOI: https://doi.org/10.1007/978-3-642-00590-9_7
9. **JSON Schema Draft 2020-12 Core/Validation.** 官方规范：JSON Schema 描述/验证 JSON 结构和约束；本文明确不把结构验证扩大解释为医学语义证明。  
   URLs: https://json-schema.org/draft/2020-12/json-schema-core ; https://json-schema.org/draft/2020-12/json-schema-validation

### 10.2 重写逻辑

10. **Meseguer, “Conditional Rewriting Logic as a Unified Model of Concurrency”, TCS 1992.** 原论文：条件重写 modulo 结构公理；并发重写对应逻辑推导，具有 sound/complete 与 initial model 结果。  
    DOI/URL: https://doi.org/10.1016/0304-3975(92)90182-F
11. **Maude Manual 3.5.1, 2025.** 官方手册：sort、equation、rule、strategy、search、invariant/LTL model checking；并明确 system rules 可不终止、不合流，策略选择关键。  
    URL: https://maude.cs.illinois.edu/manual/
12. **Ölveczky, Meseguer, “Real-Time Maude: A Tool for Simulating and Analyzing Real-Time and Hybrid Systems”.** 原作者项目页：显式 timed modules、不同时间前进策略和有界时态分析。  
    URL: https://maude.cs.illinois.edu/papers/abstract/OMrealtimemaude_2000.html
13. **Maude LTL Logical Model Checker.** 官方工具说明：有限 fixpoint、bounded verification、真实/可能伪反例等不同结果，支持本文对证明边界的限定。  
    URL: https://maude.cs.illinois.edu/tools/lmc/

### 10.3 Datalog、provenance、撤回、冲突、CHR

14. **Abiteboul, Hull, Vianu, _Foundations of Databases_, 1995.** 作者公开版权威教材：Datalog、递归/negation、incomplete information、dynamic aspects。  
    URL: https://webdam.di.ens.fr/Alice/
15. **Green, Karvounarakis, Tannen, “Provenance Semirings”, PODS 2007.** 原论文：semiring 统一 why-provenance、incomplete/probabilistic/bag 语义，并扩展到 Datalog。  
    URL: https://www.cs.ucdavis.edu/~green/papers/pods07.pdf  
    DOI: https://doi.org/10.1145/1265530.1265535
16. **Gupta, Mumick, Subrahmanian, “Maintaining Views Incrementally”, SIGMOD 1993.** 原论文：counting 与 Delete-and-Rederive，处理插入/删除/更新和 recursive views。  
    DOI/URL: https://doi.org/10.1145/170036.170066
17. **Doyle, “A Truth Maintenance System”, Artificial Intelligence 1979.** 原论文：记录 belief reasons、belief revision、explanation 与 dependency-directed backtracking。  
    DOI/URL: https://doi.org/10.1016/0004-3702(79)90008-0
18. **de Kleer, “An Assumption-Based TMS”, Artificial Intelligence 1986.** 原论文：assumption sets、多潜在解并行、矛盾信息和撤回。  
    URL: https://www.dekleer.org/Publications/An%20Assumption-Based%20TMS.pdf  
    DOI: https://doi.org/10.1016/0004-3702(86)90080-9
19. **Gelfond, Lifschitz, “The Stable Model Semantics for Logic Programming”, 1988.** 原始 stable-model 语义；作者后续一手综述给出多个等价定义及 ASP 角色。  
    Metadata: https://dblp.org/rec/conf/iclp/GelfondL88  
    Author review: https://www.cs.utexas.edu/~vl/papers/13defs.pdf
20. **Abiteboul, Deutch, Vianu, “Deduction with Contradictions in Datalog”, ICDT 2014.** 原论文：在矛盾下的 Datalog 推导、possible worlds、非确定性与概率复杂度。  
    URL: https://openproceedings.org/2014/conf/icdt/AbiteboulDV14.pdf  
    DOI: https://doi.org/10.5441/002/icdt.2014.17
21. **Belnap, “A Useful Four-Valued Logic”, 1977.** 原著书目记录，支持 true/false/neither/both 型信息状态的理论来源；本文没有把其逻辑直接等同于完整临床 uncertainty。  
    URL: https://philpapers.org/rec/BELAUF
22. **Frühwirth, “Theory and Practice of Constraint Handling Rules”, Journal of Logic Programming 1998.** 原论文：CHR syntax/semantics、confluence 及与 constraint logic programming 的结合。  
    DOI/URL: https://doi.org/10.1016/S0743-1066(98)10005-5
23. **CHR project bibliography/official project site.** 一手项目说明把 CHR 定义为 multi-headed multiset rewrite rule language，并列 confluence/termination/justification 工作。  
    URL: https://dtai.cs.kuleuven.be/projects/CHR/biblio/

### 10.4 ECS 与黑板

24. **Unity Entities Manual, “Entity Component System concepts”.** 官方实现文档：entity 是 ID，components 持数据，systems 处理数据，ECS 分离 identity/data/behavior。  
    URL: https://docs.unity.cn/Packages/com.unity.entities%401.0/manual/concepts-intro.html
25. **Flecs Manual, “Entities and Components”.** 官方 ECS 手册：entity 是唯一标识、其本身不含状态，支持对 ECS 原语的交叉核验。  
    URL: https://www.flecs.dev/flecs/md_docs_2EntitiesComponents.html
26. **Erman, Hayes-Roth, Lesser, Reddy, “The Hearsay-II Speech-Understanding System: Integrating Knowledge to Resolve Uncertainty”, ACM Computing Surveys 1980.** 原论文：独立 processes/knowledge sources、分层 hypotheses、共享黑板和资源调度。  
    URL: https://mas.cs.umass.edu/Documents/Erman_Hearsay80.pdf  
    DOI: https://doi.org/10.1145/356810.356816
27. **Hayes-Roth, “A Blackboard Architecture for Control”, Artificial Intelligence 1985.** 原论文：把 domain/control problem 分开，并讨论机会式控制架构的强弱。  
    DOI/URL: https://doi.org/10.1016/0004-3702(85)90063-3

---

## 11. 当前证据缺口与推翻条件

1. 尚未对本仓库 30 测试实现 R/L 同输入原型；因此所有 `N/C/F` 是文献约束下的架构预判，不是运行实证。
2. 尚未证明一个足够表达临床交互的重写子语言能同时保持可接受的 confluence/termination/verification 成本。
3. 尚未证明 provenance Datalog 在递归、多时间、5% 撤回和多解释下 trace 不爆炸。
4. 尚未选择冲突的最终语义；四态、possible worlds、ATMS 与 stable models 各保留不同信息，不能无证据合并。
5. 若原型显示：
   - R 在局部扩展时规则顺序稳定、trace 更小、撤回更便宜，且不需大量 strategy 特例，则 R 得到强支持；
   - L 在同样测试上能以单一固定点/显式多模型语义完成时间、撤回、冲突与血缘，且 extension blast radius 更小，则 L 得到强支持；
   - 二者都必须外挂同样大的事件/TMS/概率内核，说明应重新搜索更小共同核心，而不是强行选赢家。
