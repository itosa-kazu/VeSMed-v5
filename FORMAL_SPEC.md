# 动态临床状态表示与诊疗计算：候选无关形式化控制面

> **规范名**：`K0 Formal Control Plane`  
> **规范版本**：`v0.1`（2026-07-13 pre-bridge 研究基线）
> **状态**：2026-07-14 bridge 反证已重开 Checkpoint 3/7；本文现在是待重新比较的目标合同，不是当前已选固定核心、生产架构认证或临床有效性声明。
> **规范性依据**：`FIRST_PRINCIPLES.md`、`REQUIREMENTS.md`。  
> **验证性依据**：`ARCHITECTURE_TESTS.md`、`EXPERIMENTS.md`。  
> **研究性依据**：`research_notes/01–14`。  
> **读法**：`必须/不得` 是 v0.1 的规范性约束；`可以/建议` 是非规范性实现说明。

本文冻结的是不同候选为了被公平比较、被安全拼装而必须共享的**语义控制面假说**；它曾在 pre-bridge 比较后被保留为研究参考架构的固定部分，但当前只保留为需求/基线。它只回答：

> **谁，在什么作用域和时间截面，基于哪些合格且可追溯的输入，使用哪些版本化知识/模型，执行哪一类封闭查询，并以什么能力、覆盖、识别、数值与安全状态返回结果。**

本文不回答，也不得偷偷预设：患者动力学最终应由时间证据逻辑、图、状态空间、概率程序、因果模型、重写系统或开放系统中的哪一家承担。

## 0. 一句话边界

共同内核只统一：

> **谁，在什么作用域和时间截面，基于哪些合格且可追溯的输入，使用哪些版本化知识/模型，执行了哪一类封闭查询，并以什么能力、覆盖、识别和数值状态返回结果。**

共同内核不统一：

> **“患者世界状态是什么”“一步更新是什么”“不确定性是什么”“两个动态模块怎样组合”“两个运行结果何时等价”。**

后一组问题必须由明确的能力子内核回答。若把它们塞进 `Node(payload)`、`Rule(fn)`、`Component(callback)` 或一个万能 `update(state, any)`，形式上的原语减少了，实际语义只是转移到了不可审计的宿主代码。

因此本文提出的是一个 **semantic control plane / audit boundary**，不是“万能患者容器”，也不是披着混合架构名字的预定赢家。

### 0.1 `K0` 与能力子内核的分层

一个合规运行时写作：

```text
Runtime[F] = K0 ⊗ EvidenceAuthority[KE] ⊗ KF
           ⊗ Bridges ⊗ PhysicalStore ⊗ Solvers
```

- `K0`：artifact/ledger port 合同、身份与作用域、时间/版本切面、证据 witness 合同、封闭查询、正交结果和共同不变量；它不是持久化账本，也不持有另一份事实；
- `EvidenceAuthority[KE]`：一个且仅一个权威 evidence/action/knowledge 历史实现；完整参考 profile 以 TEL/TMS 语义实现 `KE`；
- `KF`：某一语义家族的原生能力子内核，例如证据逻辑 `K_E`、因果状态 `K_C`、重写/开放系统 `K_R`；
- `Bridges`：显式、版本化的跨语义转换；
- `PhysicalStore`：`EvidenceAuthority` 或其他模块背后的可替换物理持久化，不是第二语义事实源；
- `Solvers`：按能力家族注册、带诊断和误差合同的求解器。

这里的 `K_E` 若指 evidence/TEL 能力，就是同一个 `EvidenceAuthority`；不得再实例化一份“K0 ledger”与一份“TEL ledger”。K0 对 source/root/version/cut 的类型和不变量进行验证，TEL/TMS 参考实现负责权威保存、资格投影、撤回和重放。缓存、模型输入和派生 read model 都只能引用该权威历史的冻结版本。

`⊗` 在这里表示“受合同约束的装配”，**不是**一个全局代数运算。它不承诺结合、交换、线性、概率乘法或行为等价。合法组合律只能由具体 `KF` 的 manifest 声明。

尤其不存在以下 K0 对象：

```text
PatientState : Any
update       : PatientState × Any -> PatientState
compose      : Component × Component -> Component
confidence   : Result -> Float
```

K0 的结果/审计合同可以引用某子内核保存的 `NativeStateRef`，但 K0 不复制该 native state，也不得把它提升为统一的、可被所有候选解释为同一含义的 `PatientState`。

### 0.2 完整参考 profile 与局部降级

`K0` 本身是最小共同控制面，不是完整临床计算运行时。pre-bridge target profile 曾要求下列四组能力全部可用；它们现在是重开后待比较的需求，不是已胜出的联邦。物理实现可以合并，但 capability、witness 和事实权威不得合并语义：

| 能力端口 | 完整参考实现 | 缺失时的合法降级 |
|---|---|---|
| `EvidenceAuthority` | TEL/TMS：事实/action/knowledge 版本、cut、roots、撤回、回放、任务投影 | 不是一个可接受的临床事实运行时；只可做离线 schema/contract 验证 |
| `StateDynamics` | DBN/SSM/ODE/SDE 等带 observation model 的子内核 | `Filter/Smooth/Forecast` 为 typed `Unsupported`；evidence/replay 仍可用 |
| `Causal` | 显式 conditioning、mechanism replacement、AAP/shared-world 的 causal 子内核 | `Intervene/IndividualCounterfactual` 为 typed `Unsupported`；不得以 action-conditioned forecast 代替 |
| `RewriteOpenSafety` | typed rewrite/open machine：动作 typestate、reachability、ports/wiring、feedback/invariant | 相应 action-effect、reachability、组合和 safety query 为 typed `Unsupported`；不得自动执行或默认相加 |

“完整”指能力覆盖，不表示真实医学模型已经验证。对只读病历回放等受限用途，可以有明确的降级 profile；每次结果必须说明当前 profile、缺失 capability 和实际 origin。

### 0.3 合规等级、当前代码子集与记号

候选实现只有在同时满足以下条件时，才能称为 **K0-v0.1 conformant**：

1. 能导入/导出本文的封闭控制面类型，不能用 `Any` 跳过判别；
2. 所声称的共同不变量通过机器测试；
3. 未原生支持的 query 返回 typed `Unsupported`，不以自由 callback 冒充；
4. 所有 companion/foreign 能力在 manifest、witness 与实验计账中可见；
5. 结果携带冻结 cut、版本向量、证据 witness、能力来源和正交诊断。

当前 `prototype/contract.py` 只声明为 **`K0-executable-subset-v0.1`**，用于让候选、隔离 runner 和反例可运行；它没有满足下表全部规范，因此不得仅因导入该类就自称 `K0-v0.1 conformant`：

| 规范对象 | `prototype/contract.py` 当前实现 | 合规判断/剩余差距 |
|---|---|---|
| role/action/scope | `SemanticRole`、`Scope` 是压缩枚举/字段子集 | 可运行子集；未覆盖规范中的完整 `ActionPhase`、semantic scope、tenant/actor/purpose/jurisdiction |
| clocks/cut | `ClockSet` + `QuerySpec.as_known_at/valid_at` | 可运行子集；未完整表达 actor-specific availability、transaction/version vector、偏序与外部/random snapshot |
| source/value | `SourceArtifact.value/context/raw_payload` 的 Python 注解含 `Any/Mapping` | 只作传输载体；公共 `validate()` 实际只接受 exact-builtin JSON-like 图。仍缺按 `value_kind` 静态封闭的全量 `MeasuredValue` sum type |
| closed query | `QueryKind` enum + `QuerySpec` tagged envelope | query kind 封闭，但各构造子的 body 仍由候选/module validator 动态检查，弱于本规范的 `ClosedQuery<Q>` 静态和类型 |
| product outcome | `CapabilityResult` 有兼容 `status`、7 个字符串轴和 JSON witness | 仅覆盖核心实验轴；字符串值域、`value: Any`、缺 completeness/availability/applicability/replay/safety 等，均弱于 `Outcome<T>` |
| manifest/module | `CandidateManifest` + 各候选 closed IR validator | 足够实验计账，不是完整 `CapabilityClaim`/foreign contract 的机器证明 |
| authority/storage | 候选各自的实验内存态 | 只有 TEL 原型承担参考 evidence authority 语义；`ClinicalKernel` 不得被解释为另一权威账本 |

因此本文件中出现的 `Outcome<T>`、`ValueOf<Q>` 和完整时钟/作用域是**规范目标**；参考代码的字符串或 `Any` 不能反过来降低规范。相反，代码输出只能被表述为“通过了可执行子集测试”，直到静态构造子、缺失结果轴、完整 cut 和持久 evidence-authority conformance 都补齐。

#### 0.3.1 可执行子集的 exact-builtin 与预算边界

子集仍有不可绕过的真实运行边界。`validate_json_like()` 必须在 `deepcopy`、哈希、序列化和解释之前执行，并且只接受 exact `None/bool/int/float/str/dict/list`（Python 合同为不可变传输便利额外接受 exact `tuple`，wire 上仍是 JSON array）。它拒绝对象子类、任意 `Mapping`、dataclass、Enum、callable、非字符串 dict key、循环和非有限浮点数。

冻结的 PoC 预算为：

```text
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 65_536
MAX_JSON_BYTES = 1_048_576
```

超限返回 typed contract failure；不得先运行用户钩子、静默截断或提升预算。求解器和 search 的时间/步数/内存预算仍由具体能力合同声明，并映射到 `ResourceBudgetExceeded`/相应 typed diagnostics。

本文使用：

- `A + B` 表示判别联合（sum type），不是数值加法；
- `A × B` 表示乘积类型；
- `Option<A>` 表示显式可无值；
- `Result<A,E>` 表示成功或类型化失败；
- `℘(A)` 表示有限集合；
- `⊥` 表示没有合法值/未定义，不等于 0、false 或阴性；
- `≅` 表示由相应语义家族定义的等价，不预设 bitwise equality。

---

## 1. 核心签名与对象

令 2026-07-13 pre-bridge 面板在 13 个候选家族、3 个原子原型和冻结反例范围内提出、并留待 bridge 实验检验的共同内核签名为：

```text
K0 = (MetaTypes, IdentityAndScope, LedgerPortContract,
      TimeVersionCuts, WitnessContracts, Capabilities,
      ClosedQueries, Outcomes, Invariants)
```

这是语义签名，不是第二份记录集合。`LedgerPortContract` 规定权威 evidence 实现必须接受/返回什么，以及身份、cut、witness、撤回和重放必须满足哪些不变量；实际记录只由唯一 `EvidenceAuthority` 保存。其物理存储可以使用 MVCC、不可变日志、关系表或内容寻址对象，只要历史版本、资格判断和重放语义等价即可。

### 1.1 闭合元类型与开放医学词汇

内核闭合且需版本化的，是少量认识论/操作元类型：

```text
EpistemicRole =
    MeasuredObservation | ReportedStatement
  | DeterministicDerivation | StatisticalInference | Hypothesis

ActionPhase =
    Proposed | Planned | Requested | Ordered
  | Started | PartiallyPerformed | Performed
  | Paused | Refused | Cancelled | Stopped | NotPerformed

Polarity = Supports | Refutes

NoValueReason =
    NotAsked | NotObserved | NotRecorded | UnableToAssess
  | NotApplicable | Withheld | Masked

ClockRole =
    Occurrence | ReferenceInterval | Collection | AvailableToActor
  | SourceRecorded | KernelCommitted | ActionExecution
```

医学内容保持开放、版本化：

```text
ConceptRef = (namespace, concept_id, terminology_version)
UnitRef    = (system, unit_id, version)
```

新增疾病、药物、检查或一般临床概念只增加 `ConceptRef`、schema 和知识包；不增加核心 opcode。真正出现新的认识论角色或时间角色时，应升级 `K0` 版本并提供迁移，而不是藏进自由 metadata。

### 1.2 作用域、值域与时间角色

#### 1.2.1 作用域不是自由标签

```text
Scope = {
  tenant       : TenantId,
  subject      : SubjectId,
  encounter    : Option<EncounterId>,
  episode      : Option<EpisodeId>,
  specimen     : Option<SpecimenId>,
  device       : Option<DeviceId>,
  body_site    : Option<ConceptRef>,
  actor        : Option<ActorId>,
  jurisdiction : Option<JurisdictionId>,
  purpose      : PurposeOfUse
}
```

`scope_compatible(s1,s2,bridge)` 必须由字段相等、明确的父子关系，或版本化 `ScopeBridge` 证明；同名 analyte、同一病区、相同时间或自然语言相似不能代替证明。标本属于患者不意味着标本值可无条件升级为全身状态；设备读数属于设备与主体的联合 scope。

一般知识、患者证据、模型输出与任务政策另有正交作用域：

```text
SemanticScope = GeneralKnowledge | PatientEvidence
              | ModelOutput | TaskPolicy | OperationalReceipt
```

跨 `SemanticScope` 只能通过声明输入输出角色的 bridge；指南知识不能成为患者已实施事实，模型输出不能成为新的 raw evidence root。

#### 1.2.2 测量值是判别联合

```text
MeasuredValue<A> =
    Exact(value:A, unit:UnitRef)
  | Interval(low:A, high:A, closure, unit:UnitRef)
  | BelowDetection(limit:A, unit:UnitRef)
  | AboveDetection(limit:A, unit:UnitRef)
  | Ordinal(code:ConceptRef)
  | ExplicitNoValue(reason:NoValueReason)

MeasurementContext = {
  method, assay_version, device?, specimen?, body_site?,
  support_conditions[], reference_range?, detection_limit?,
  reliability?, ascertainment_scope?, operator?,
  terminology_and_unit_mapping_versions[]
}
```

`BelowDetection(0.01)` 不等于 `Exact(0)`；`Masked` 不等于 `NotRecorded`；无任何记录时也不允许凭空创建 `ExplicitNoValue`。

#### 1.2.3 时间是有角色、可未知的对象

```text
TimeValue = Known(Instant)
          | Bounded(Interval<Instant>)
          | Unknown(TimeUnknownReason)

Times = Map<ClockRole, TimeValue>

PartialOrder = set<HappensBefore(EventId, EventId, ReasonRef)>
```

每个时间值必须携带 `ClockRole`。同一墙钟值和 transaction 排序都不自动生成临床 happens-before；只有显式依赖、通信、workflow transition 或能力模型中的因果边才产生偏序。

### 1.3 不能再压缩的五类持久对象

#### A. `SourceArtifact`

```text
SourceArtifact {
  artifact_id, artifact_version, source_system_id,
  immutable_raw_bytes_or_text, source_locator,
  received_at, integrity_digest, access_policy
}
```

它保存原文、原值、原单位和 source span 的最终锚点。权威 source store 可以保存任意**惰性字节或文本**，但控制面只传其 digest/locator 或通过 exact-builtin 预算验证的 JSON-like 副本；不得把任意宿主对象当 raw payload 送入运行时。raw 只用于往返、隔离与审计，**任何医学计算不得直接从 raw payload 取语义**。必须先经版本化 adapter 生成 proposed typed record，再验证接纳。

#### B. `Statement<T>`：封闭和类型，不是一枚自由 `role` 字符串

```text
Statement<T> =
    Observed {
      statement_id, logical_id, version, atom:T,
      polarity_or_censored_value, scope, times,
      measurement_context, root_occurrence, source_span
    }
  | Reported { ... root_occurrence, source_span ... }
  | Deterministic {
      statement_id, atom:T, polarity,
      proof, transform_version, scope, times
    }
  | Inferred {
      statement_id, estimand:T, value,
      proof, model_run_id, scope, times
    }
  | Hypothesized { ... proof, hypothesis_space_version ... }
```

`Observed/Reported` 才能引入外部 evidence root；`Deterministic/Inferred/Hypothesized` 只能继承输入 roots，不能重新铸成 raw root。显式 `NoValueReason` 只能由真实工作流/记录证据产生；完全没有 record 时仍是 unknown，不能凭空构造 `NotObserved`。

#### C. `ActionRecord`

```text
ActionRecord {
  action_id, idempotency_key, subject_scope,
  concept, phase:ActionPhase, dose_or_extent,
  request_time?, execution_interval?, receipt_artifact?,
  predecessor_action_event?, policy_model_exposure?, version,
  transition_proof, supersedes?
}
```

动作阶段按 typestate 转移，而不是任意覆盖。最少允许的转移关系由版本化 workflow schema 给出；例如 `Ordered -> Started -> PartiallyPerformed/Performed -> Stopped`，而 `Cancelled -> Performed` 必须有新的 action identity 或显式纠正。

```text
EffectToken = {
  action_id, subject_scope, concept, realized_extent,
  active_interval, receipt_root, transition_proof
}

issue_effect(a) is defined iff
    a.phase in {Started, PartiallyPerformed, Performed}
  ∧ valid_execution_receipt(a.receipt_artifact)
  ∧ legal_action_history(a.action_id)
```

只有满足上述条件的记录可以生成 `EffectToken`；计划、医嘱、模拟和政策建议没有从类型上到 `EffectToken` 的隐式转换。撤销/停止关闭实际作用区间，不倒写历史。

#### D. `KnowledgeArtifact`

```text
KnowledgeArtifact =
    TerminologyMap | TypedAdapter | DeterministicRule
  | SafetyInvariant | DynamicModel | ObservationModel
  | CausalModel | InteractionModel | TaskPolicy | UtilityContract

common fields = (id, version, effective_interval,
                 registered_transaction, content_digest,
                 declared_scope, assumptions, supersedes?)
```

能力模型不得只是一段未声明边界的宿主函数。原生模型以 `ModelBundle<F>` 注册：

```text
ModelBundle<F> = {
  family:F, schema_version, closed_ir,
  capabilities:set<Capability>, coverage_contract,
  assumptions, solver_contracts[], ports[], invariants[]
}
```

一般知识、患者证据、任务政策和模型输出分别属于不同作用域；跨域使用必须通过显式 bridge。一个指南知识包不能直接生成“该患者已给药”的事实。

#### E. `ComputationRecord`

```text
ComputationRecord {
  result_id, closed_query, temporal_cut, version_vector,
  outcome_product, frozen_evidence_witness,
  frozen_native_witness, environment_snapshot, created_at
}
```

解释在执行时冻结；`explain(result_id)` 只能读取 witness，不得事后调用 LLM 重新编一个解释。

### 1.4 身份至少四分，不能只用一个 `source_group_id`

1. **Proposition identity**：两条记录是否在说同一命题；
2. **Artifact/version identity**：哪一份文档/消息的哪一版本；
3. **Evidence-root occurrence identity**：现实中哪一次最小 evidence-producing act；
4. **Dependence-family membership**：同一标本、设备、文档、校准批次、采样时段等可重叠来源族。

同一 root 可以属于多个 dependence family；同一 artifact 可含多个 roots；两个不同 roots 也可能高度相关。稳定 root id 解决重复摄取，不能自动证明统计独立。

版本关系也是类型化关系：

```text
VersionDelta = Corrects(old,new) | Retracts(old,reason)
             | Supersedes(old,new) | Expires(old,interval)
```

`Retracts` 是记录资格变化，不是对临床命题的 `Refutes`；`Corrects` 也不删除旧 cut 中的旧版本。对任一 transaction cut，同一 `logical_id` 的 active version 必须由版本图和登记顺序确定，出现分叉且无仲裁时返回 `ConflictingVersions`，不得 last-write-wins。

### 1.5 条件性最小与删除反例

| 删除的对象/区分 | 立即无法满足的反例 |
|---|---|
| `SourceArtifact` | T29/T45 无法保留不可表达输入和 raw round-trip |
| Statement 构造子分型 | T06/T49 推断可伪装原始观察并自证 |
| `ActionRecord`/typestate | T37/T48 计划、取消与实际实施混同 |
| `KnowledgeArtifact` 版本 | T23/T36 无法区分当时规则与今天重释 |
| `ComputationRecord` + frozen witness | T25/T35/T40 结果不可确定重放或事后解释漂移 |
| typed scope/identity | T41 两个患者、标本或设备串线 |

这只证明这些区分在本次候选/反例范围内有已知删除见证，不声称已从数学上证明不可约或全局最小；`S-MIN-02` 消融是继续检验该主张的方法，而不是已经完成的不可约性证明。

---

## 2. 时间与版本：资格切面，不是一个时间戳

### 2.1 时间对象

每个时间值是 `Known(value) | Bounded(interval) | Unknown(reason)`，禁止用另一个 clock role 猜补。`SourceRecorded` 与 `KernelCommitted` 也分开；中央 transaction 序号只用于确定重放，不产生临床因果顺序。

并发以偏序表示：

```text
HappensBefore(a,b) only if:
  explicit dependency | communication | workflow transition | causal model edge
```

相同墙钟时间或存储先后不产生 `HappensBefore`。

### 2.2 `TemporalCut`

```text
TemporalCut {
  target_window,
  actor_visibility_cut,
  transaction_revision_cut,
  evidence_use_policy,
  evidence_snapshot_id,
  knowledge_model_policy_version_vector,
  external_response_snapshot,
  randomness_policy,
  principal_and_authorization
}
```

内核只做**可见性、版本、作用域与访问资格**判断。某项旧肌酐对当前剂量是否 stale、对趋势模型是否仍相关，是版本化 task/model eligibility policy 的决定，不能被一个全局 `expires_at` 伪装成普适真理。

对 record `r` 和 query `q`，最低资格谓词为：

```text
admissible(r,q) :=
    scope_compatible(r.scope, q.scope)
  ∧ visible_to(r, q.principal, q.actor_visibility_cut)
  ∧ committed_by(r, q.transaction_revision_cut)
  ∧ active_version_at(r, q.transaction_revision_cut)
  ∧ authorized(r, q.principal)
```

是否落入 target window、是否适合 filter/smooth/forecast，再由该 closed query 的时间政策判断。不能把 `clinically_relevant(r,q)` 留作自由 callback。

### 2.3 三种必须分名的历史模式

1. `ReplayAsThen`：旧 evidence prefix + 旧知识/模型/政策/外部响应快照；
2. `ReinterpretCurrentTheory`：同一个旧 evidence prefix + 当前知识版本；
3. `RetrospectiveReconstruction`：目标仍在过去，但显式允许后来或晚到证据，通常执行 smoothing。

第 2 与第 3 不得都叫 `reinterpret_now`。重放也不等于个体反事实：重放换的是信息/版本切面；反事实换的是同一单位世界中的干预机制。

---

## 3. 证据与推导代数：只统一审计，不统一 belief

### 3.1 Grounded proof terms

```text
Proof ::= Root(root_occurrence_version)
        | Apply(transform_version, premises[], assumptions[])
        | ModelRun(model_version, solver_version,
                   premises[], assumptions[], native_artifact_ref)
```

```text
roots(Root(r))                  = {r}
roots(Apply(_, ps, _))         = union(roots(p) for p in ps)
roots(ModelRun(_,_,ps,_,_))    = union(roots(p) for p in ps)
```

Proof term 保留“共同使用”和“替代推导”的结构；`roots()` 只是幂等 identity 投影。不能把整个 proof 强制成 `x*x=x` 后丢掉推导结构，也不能把 semiring 系数、路径数或 root 数解释成独立票数。

证明项的最小类型判断为：

```text
Γ ; C ; V ⊢ p : Claim<A> @ Scope
```

其中 `Γ` 是当前 eligible roots 与已注册知识，`C` 是 temporal cut，`V` 是版本向量。三个引入规则分别是：

```text
[ROOT]
admissible(r,C) ∧ role(r) in {Observed, Reported}
--------------------------------------------------
Γ;C;V ⊢ Root(r) : claim(r) @ scope(r)

[APPLY]
Γ;C;V ⊢ p_i : A_i   rule_v : (A_1...A_n) -> B
scope/time compatible   conflict_policy satisfied
--------------------------------------------------
Γ;C;V ⊢ Apply(rule_v,p_1...p_n) : B

[MODEL]
Γ;C;V ⊢ p_i : A_i   model_v : Query<A_i...> -> B
coverage/solver/assumption contracts evaluated
--------------------------------------------------
Γ;C;V ⊢ ModelRun(model_v,...) : B + TypedFailure
```

`[APPLY]` 与 `[MODEL]` 只继承 premises 的 roots。若规则使用显式先验，先验必须是版本化 `KnowledgeArtifact`/model assumption，并进入 witness；它不能伪装成患者 evidence root。

替代推导保留为 `Alternative(p1,p2,...)`，共同前提保留为 DAG 共享节点。proof 的组合代数至少满足：

```text
roots(Alternative(p,p)) = roots(p)           // 根身份幂等
roots(Apply(f,p...p))    = roots(p)           // fan-out 不复制 root
Alternative(p,q) ≅ Alternative(q,p)         // 仅审计集合顺序无关
Apply(f,p,q) !≅ Apply(f,q,p) unless declared  // 规则参数不默认交换
```

这些定律仅约束 evidence conservation；它们不定义概率加法、似然乘积或临床置信度。

### 3.2 显式命题的双支持读出

对可正反断言的命题 `p`：

```text
ClaimEvidence(p) = (W_plus(p), W_minus(p))
```

其中 `W_plus/W_minus` 是 proof 集或共享 proof DAG 的根。仅作审计读出时：

| `W+` | `W-` | 认识状态 |
|---|---|---|
| 空 | 空 | unknown |
| 非空 | 空 | supported |
| 空 | 非空 | refuted |
| 非空 | 非空 | conflicting |

这是局部、非爆炸的四态读出，不是完整 uncertainty algebra。连续值、区间、posterior、可达集和随机轨迹不得被迫离散成四态；它们由相应子内核返回，并与该证据状态正交。

形式上，局部读出函数为：

```text
support_state(p,C) =
  Unknown      if W_plus(p,C)=∅ and W_minus(p,C)=∅
  Supported    if W_plus(p,C)≠∅ and W_minus(p,C)=∅
  Refuted      if W_plus(p,C)=∅ and W_minus(p,C)≠∅
  Conflicting  if W_plus(p,C)≠∅ and W_minus(p,C)≠∅
```

对不相关命题 `q`，`Conflicting(p)` 不产生 `q`；所有推导都必须命中显式规则前件。这是局部 paraconsistent 读出，不宣称 K0 提供完整的矛盾逻辑。

规则必须声明冲突前提政策，例如只接受 `supported-only`，或允许 `has-positive-support`；内核不默默替规则选边。临床阴性只能来自 explicit refuting root/derivation，不能来自 negation-as-failure。

### 3.3 更正、撤回与递归

- 更正/撤回是**版本资格变化**，不是一个负临床命题；
- 旧 transaction cut 仍看到旧版本，新 cut 按 supersession/retraction 选择 active roots；
- 实现可用 DRed、TMS、差分数据流或 clean rebuild，内核不预定算法；
- 行为 oracle 为：

```text
incremental_eval(history + delta, cut)
  == clean_eval(active_records(history + delta, cut), cut)
```

- 有替代 proof 时结论保留且 witness 缩减；只依赖被撤回 root 时失效。

派生结构不必一律是 DAG。允许 grounded least fixed point、合法递归和有良定性证明的生理反馈；禁止的是没有外部 root/已执行 action/显式先验承诺，却由认识论 SCC 凭空产生或增加支持质量。无穷 provenance、无固定点、多固定点或不收敛必须成为 typed diagnostics。

### 3.4 Provenance 不等于统计依赖

概率模块若联合消费多个 roots，必须引用：

```text
DependenceAssumption {
  id, version, applicable_roots_or_families,
  model_kind, parameters_or_bounds, scope, validity_domain
}
```

默认状态是“未声明可因子化”，不是“相互独立”。同一 root 的多个 deterministic transforms 可以被 joint model 合法消费，但复制、转述或改名不能仅因路径数增加独立信息质量。证据可以跨任务和多个结论复用；它不是消耗一次即消失的线性资源。

---

## 4. 封闭操作与 Query Algebra

### 4.1 控制面操作

```text
EvidenceAuthority.store_source(SourceArtifact)
adapt(source_id, TypedAdapterVersion) -> ProposedRecords
accept_or_quarantine(ProposedRecords) -> IngestReceipt
EvidenceAuthority.append_correction_or_retraction(VersionDelta) -> DeltaReceipt
EvidenceAuthority.record_action_event(ActionRecord) -> Receipt
register_schema(SchemaPackage) -> ValidationReceipt
register_module(FamilyModelBundle) -> ValidationReceipt
compose(FamilyWiring) -> CompositionReceipt | UnsupportedComposition
invoke(ClosedQuery) -> Outcome<ValueOf<Query>>
fetch_frozen_witness(result_id) -> AuditWitness
```

K0 验证并路由这些 port；真正改变权威历史的三个操作只由唯一 `EvidenceAuthority` 实现。`accept_or_quarantine` 成功后写入同一 authority，不能同时更新一份 K0 store 和一份 TEL store。其他子内核只消费带 cut/witness 的快照或引用。

外部动作必须另设具 capability token 的 `request_action`，且外部 receipt 回来后才调用 `record_action_event`。`simulate_intervention` 永不修改事实层。

### 4.2 Closed Query 是和类型，不是自由 JSON

```text
ClosedQuery =
    EvidenceView(scope, cut, projection)
  | Explain(result_id)
  | FilterState(target, cut, model_ref)
  | SmoothState(target, later_evidence_policy, cut, model_ref)
  | Forecast(target, horizon, action_regime?, model_ref)
  | Condition(estimand, observation_set, model_ref)
  | Intervene(estimand, do_set, population,
              causal_model_ref, identification_contract)
  | IndividualCounterfactual(unit, factual_cut, do_set,
                             causal_model_ref, shared_world_policy)
  | Reachability(initial_set, target_set, system_ref, strategy?)
  | TaskProjection(task_contract, cut)
  | EvaluatePolicy(actions, goals, utility, constraints,
                   authorization, model_refs)
  | VerifyInvariant(invariant_ref, scope, cut)
  | ReplayProjection(replay_mode, temporal_cut, version_vector)
```

查询构造子到能力与值类型的映射是规范的一部分：

| Query 构造子 | 必需 capability | `ValueOf<Q>` |
|---|---|---|
| `EvidenceView` | `EvidenceProjection` | `EvidenceProjectionValue` |
| `Explain` | `FrozenExplanation` | `AuditWitness` |
| `FilterState` | `Filtering` | `BeliefAtTime<S,U>` |
| `SmoothState` | `Smoothing` | `BeliefTrajectory<S,U>` |
| `Forecast` | `Forecasting` | `TrajectoryDistribution<S,U>` 或声明的 set-valued 对应物 |
| `Condition` | `ProbabilisticConditioning` | `ConditionalDistribution<U>` |
| `Intervene` | `PopulationIntervention` | `InterventionalDistribution<U>` |
| `IndividualCounterfactual` | `UnitCounterfactual` | `CounterfactualDistribution<U>` |
| `Reachability` | `Reachability` | `ReachabilitySet<C>` |
| `TaskProjection` | `TaskReadModel` | `TaskView<T>` |
| `EvaluatePolicy` | `DecisionAnalysis` | `ParetoActionSet<A>` |
| `VerifyInvariant` | `InvariantChecking` | `InvariantReport` |
| `ReplayProjection` | `Replay` | `ReplayArtifact<T>` |

其中 `S`、`U`、`C` 都是某个能力子内核的类型参数，不是 K0 统一患者状态。manifest 必须列出：

```text
CapabilityClaim = {
  capability, origin:Native | Companion(module_id),
  supported_query_variants, coverage_contract,
  required_assumptions, native_witness_kind,
  failure_modes
}
```

缺能力时只允许 `runtime_capability=Unsupported(boundary)`；不允许 fallback 到语义不同的近似 query，除非调用方显式请求另一个构造子。

硬边界：

- `FilterState != SmoothState`；
- `Condition != Intervene != IndividualCounterfactual`；
- action-conditioned forecast 不自动获得 `do()` 语义；
- 独立重采样两个模拟患者不等于同一患者共享外生背景的反事实；
- `TaskProjection` 只读；
- `EvaluatePolicy` 缺 goals/utility/constraints 时不得输出“唯一最优”；
- `record_action_event` 是摄取，不是 query；
- replay、past-state reconstruction、reachability 和 counterfactual 互不替代。

每个 query 声明所需 capability；候选没有时返回 `unsupported`，不得通过任意规则模拟后宣称原生支持。

---

## 5. Outcome 与 Failure：正交乘积，不是一枚 flat status

```text
Outcome<T> {
  execution: Completed | Blocked | Failed,
  completeness: Full | Partial | None,
  input_validity: Valid | Invalid(reasons),
  runtime_capability: Supported | Unsupported(boundary),

  field_availability: Available | Unknown(reason)
                    | Masked | Unauthorized | NotApplicable,
  claim_evidence: Supported | Refuted | Unknown
                | Conflicting | NotApplicable,
  applicability: Applicable | Conditional | NotApplicable | Unknown,
  coverage: InDomain | Partial(domain_gap) | OutOfModel | Unknown,
  identification: Identified | PartiallyIdentified(bounds)
                | AssumptionDependent | NotIdentified | NotApplicable,
  numerics: Exact | Converged | Approximate(bounds,error_budget)
          | NonConverged | NoSolution | MultipleSolutions
          | ResourceBudgetExceeded | StrategyDependent | NotApplicable,
  replay: Reproducible | MissingSnapshot | VersionUnavailable
        | NondeterministicBoundary | NotApplicable,
  safety: Passed | Violated(invariants) | NotEvaluated,

  value: T?, assumptions: [], diagnostics: [],
  temporal_cut, versions,
  evidence_witness_ref, native_witness_ref
}
```

`ValueOf<Query>` 也是封闭类型，例如 `EvidenceProjection`、`ClaimSet`、`PosteriorBelief`、`TrajectoryDistribution`、`CounterfactualDistribution`、`ReachabilitySet`、`ParetoActionSet`，不能退回 `value:any`。

形式上：

```text
Outcome<T> = Exec × Completeness × InputValidity × Capability
           × Availability × ClaimEvidence × Applicability
           × Coverage × Identification × Numerics
           × Replayability × Safety × Option<T>
           × Assumptions × Diagnostics × WitnessRefs
```

不存在规范函数 `flatten : Outcome<T> -> confidence:Float`。产品层若定义排序或门限，必须作为版本化 `TaskPolicy/UtilityContract`，并保留原始 outcome 乘积。`Completed` 只表示执行路径结束，不推出 `Full`、`InDomain`、`Identified`、`Converged` 或 `Passed`。

### 5.1 Failure taxonomy

1. **Contract rejection**：type/unit/scope/time/action-transition/role-coercion 错；
2. **Quarantine**：不可无损表达、adapter 未验证、raw canary 泄漏；
3. **Capability unsupported**：候选没有所需子语义；
4. **Evidence no-answer**：insufficient/conflicting/not-applicable/masked；
5. **Coverage no-answer**：out-of-model/partial/unknown；
6. **Causal no-answer**：not-identified/positivity failure/shared-world unavailable；
7. **Composition failure**：port mismatch/missing interaction/state ownership conflict/ill-posed feedback；
8. **Numerical failure**：nonconvergence/no or multiple solutions/approximation overflow；
9. **Replay failure**：版本、外部响应、随机源或环境快照缺失；
10. **Invariant/internal failure**：证据守恒、future leak、安全 invariant 等被破坏。

这些维度可同时出现：例如证据冲突、模型 out-of-domain、因果未识别，但数值求解本身正常。任何 downstream bridge 若要消除 taint，必须输出显式 resolution proof，不能把多维失败洗成 `ok`。

---

## 6. 明确不可统一的能力子内核

| 能力 | 必须由谁定义 | 共同内核绝不默认 |
|---|---|---|
| 逻辑派生 | temporal rules / Datalog / rewrite logic | closed-world negation、冲突选边 |
| 潜在状态与过滤 | SSM/DBN/PPL/集合估计器 | “当前记录集合就是 patient state” |
| 生理动力学 | transition kernel、ODE/SDE、reaction/rewrite system | 加法叠加、Markov、连续性 |
| 观察生成 | explicit observation model | 观察等于真实状态、缺失随机 |
| 干预因果 | SCM/causal PPL/带因果合同的 controlled system | conditioning 等于 `do` |
| 个体反事实 | abduction-action-prediction + shared exogenous policy | 重新抽样另一个患者 |
| 不确定性 | probability/set/interval/possible-world semantics | root 数等于概率、unknown=0 |
| 动态组合 | family-specific wiring/interaction algebra | 事件并集、因子乘积、向量相加是同一 compose |
| 政策与效用 | decision/policy subkernel | 最大风险改善自动等于唯一最佳行动 |
| OOD/coverage | model-specific support/coverage contract | 开放词汇或检索失败自动给 OOD |
| 数值良定性 | solver + model contract | 程序返回浮点数即有效 |
| 执行等价 | family native semantics | proof 等价、分布等价、bisimulation、normal form 等同 |

尤其禁止以下等同：

```text
撤回 != 反向生理转移 != inverse rewrite
历史重放 != 个体反事实 != reachability
evidence provenance != causal graph != execution trace
unknown/conflict != posterior uncertainty != nondeterministic branch
事件并集 != 机制组合 != open-system wiring
```

共同内核只接受各子内核的 typed capability、假设、witness 和 failure；不声称存在一个统一 evaluator。

---

## 7. 组合合同

### 7.1 Port 与组件

```text
Port {
  port_id, direction, multiplicity,
  semantic_concept, epistemic_role,
  subject/specimen/site binding,
  value_domain, unit_dimension,
  time_basis, latency_or_delay,
  state_ownership,
  uncertainty_semantics,
  provenance_policy,
  version
}

Component {
  component_id, version, family,
  capabilities, input_ports, output_ports,
  private_state_schema, reads, writes,
  assumptions, guarantees, invariants,
  behavior_artifact, coverage_contract
}
```

### 7.2 合法 wiring 的必要条件

1. subject/encounter/specimen/site 显式统一，不能按名字粘合；
2. concept/value/unit 兼容；转换必须是版本化 bridge module；
3. time basis 可转换且转换规则显式；
4. `Observation/LatentState/ActionReceipt/ModelOutput/Policy` 不隐式强转；
5. 每个持久或潜在 state 有唯一 owner，或明确共享引用，不复制“同一肾脏”；
6. 共享噪声与统计依赖显式；
7. 已知需要的 interaction 必须存在；未建模、未检索、冲突、近似和“已有无重要交互证据”分别返回；
8. feedback 有 delay、唯一固定点证明，或能返回多解/无解/不收敛诊断；
9. 组合保持 evidence roots 与 proof 映射，不因 fan-out 复制根；
10. 注册顺序不制造语义；若策略本来依赖顺序，必须声明并进入 outcome；
11. 只有在声明的子代数中才要求结合、交换或幂等，不把它们设成全局定律。

语义转换不能藏在 wire 中。单位转换、evidence-to-likelihood、receipt-to-effect-interval、model-output-to-policy 都是可版本化、可计费的显式 bridge。

### 7.3 允许的组合操作不是一个万能 `compose`

```text
parallel_disjoint(A,B)     // 仅 state/effect footprints 可证不相交
wire(A.out, B.in, bridge?) // typed directional connection
interact(A,B,I)            // 显式 interaction component
feedback(A, loop, proof_or_solver_contract)
```

同一 wiring graph 和 interaction set 下，若组件无隐藏全局副作用，重括号应同构；否则 manifest 必须拒绝 associativity claim。未声明必要交互时返回 `UnsupportedComposition`，绝不默认 `f_A + f_B`。

---

## 8. 展开 foreign callback：防止 `Rule(fn)` 作弊

### 8.1 Track A 的封闭 IR

首轮 Native track 的领域模块只能使用按家族区分的封闭 IR：

```text
TELBundle = RelationSchema + EventKind + TemporalRuleAST
          + ProjectionAST + InvariantAST

CausalStateBundle = TypedVariable + ClosedExpressionAST + DistributionAST
                  + Initial/Transition/Observation/InterventionSpec
                  + ExogenousSharingPolicy

RewriteOpenBundle = Sort + Constructor + EquationAST + RewriteRuleAST
                  + StrategyAST + Component/Port/WiringSpec
```

禁止 `Custom/Any/eval`、可执行字符串、SQL/prompt/bytecode、函数值、动态网络调用。macro 按完全展开后的 IR 计 primitive 和 operator 使用。

### 8.2 确需 foreign operator 时的完整账本

Companion track 可注册 foreign operator，但必须展开为：

```text
ForeignOperatorContract {
  operator_id, semantic_family, version, code_digest,
  runtime_and_dependency_snapshot,
  typed_input_ports, typed_output_ports,
  declared_reads, declared_writes, side_effect_policy,
  epistemic_effect, state_effect, observation_effect,
  domain_and_coverage_contract,
  machine_checkable_preconditions, postconditions,
  determinism_or_randomness, seed_policy,
  solver_and_approximation_contract,
  declarative_provenance_map,
  failure_map, timeout_and_resource_policy,
  composition_laws_claimed,
  replay_bundle, validation_fixtures,
  assumptions, security_boundary
}
```

`provenance_map`、pre/post 与 coverage 不能再次是 callback；它们必须用受限 Constraint/Proof AST。无法声明输入依赖的 opaque model，其输出只能标为 `Inferred + opaque/approximate`，不得承担 deterministic safety invariant 或 100% trace 能力。

若 foreign code 内嵌疾病分支、阈值、插补、医学映射或交互，它们按展开后的实际语义逐项计入 `G_general/K_extra/S_patch`，不能把一个插件加载器计成“1 个原语”。adapter 只允许句法运输；医学规范化、单位换算和 missingness 判断都是显式模块。

### 8.3 机器门禁

- schema 禁止无 discriminator 的 union 和语义对象上的 `additionalProperties:true`；
- hash grammar、opcode registry、解释器、adapter、solver、模型和环境；
- 运行 alpha-renaming、事件/模块乱序、raw-payload canary、冷缓存重放和 companion ablation；
- witness 必须经撤回/扰动验证，返回“全部输入”不算真实依赖；
- 未申报环境读取、网络调用、foreign boundary 或 oracle/test-id 引用，整次 run 标 `Invalid`。

---

## 9. 必须机器检查的不变量

| ID | 不变量/性质 |
|---|---|
| K-I01 | 稳定 root/action id 重复摄取幂等；真正复测保留不同 occurrence |
| K-I02 | scope/specimen/unit/method 不兼容在消费前失败；raw/span/mapping version 可往返 |
| K-I03 | cut 外未来记录扰动不改变 cut 内结果；unknown clock 不被猜补；transaction order 不制造 HB |
| K-I04 | 固定 evidence/knowledge/model/policy/external/random 快照的重放语义等价 |
| K-I05 | alias、转述、deterministic clone 不增加 `roots()` 或独立支持质量 |
| K-I06 | 每个 derived output 有 eligible roots、知识/模型版本和 frozen witness |
| K-I07 | 无根认识论 SCC 不产生支持；grounded fixed point 与良定生理反馈仍可合法 |
| K-I08 | 局部冲突不爆炸、不 last-write-wins；missing/masked/NA/OOD/negative 正交 |
| K-I09 | correction/retraction 后增量结果等于 clean rebuild，替代支持保留 |
| K-I10 | task projection 不改 source-of-record；模型输出不能重新成为 raw root |
| K-I11 | `condition/do/counterfactual` 类型隔离；同单位反事实共享声明的外生背景 |
| K-I12 | 计划/医嘱无 effect；只有 performed/exposure interval 生效；state 与 observation effect 分离 |
| K-I13 | 决策缺 goals/utility/constraints/authorization 时不声称唯一最优 |
| K-I14 | port role/scope/unit/time/ownership 兼容；缺必要 interaction 时局部 unsupported，不默认相加 |
| K-I15 | 只对 manifest 声明的子代数检查结合/交换/顺序不变；反馈失败返回 typed numerics |
| K-I16 | coverage、identification、numerics、safety 和 replay taint 不得在下游无 proof 洗成 ok |
| K-I17 | foreign operator 的实际语义提供者和 companion 层完整计账；adapter 不偷补医学语义 |
| K-I18 | 新疾病/药物/检查的 core signature/主分支修改数为 0；真正核心升级有版本与迁移 |
| K-I19 | LLM/NLP 只生成 proposed artifact；未通过 schema、scope、time、source-span 与医学验收的内容不得成为 accepted root |
| K-I20 | 权限遮蔽保留为 `Masked/Unauthorized`；不得因不可见而生成 absent/negative，也不得在 witness 泄漏内容 |
| K-I21 | censored/区间/检测限值不被静默拍成 exact scalar；单位、方法与转换版本始终在 proof 中 |
| K-I22 | 在线模型/政策更新有独立版本、暴露范围、回滚与数据谱系；策略诱导观察不被静默当作自然史 |
| K-I23 | K0 不构造统一 `PatientState`，不把 evidence projection 当世界真值；native state 只能由声明能力的子内核解释 |
| K-I24 | `Explain(result_id)` 只读执行时冻结 witness；后续知识、缓存、LLM 或网络变化不改变既有解释 |
| K-I25 | 原始载荷只可经 typed adapter 进入语义层；raw-payload canary 不得被规则、模型或测试 oracle 直接消费 |
| K-I26 | 一般知识、患者 evidence、模型输出、任务 policy 与 operational receipt 跨作用域转换必须有显式 bridge proof |

这 26 条不变量覆盖 T01–T50 与 E01–E08 的共同安全边界；动态数值正确性仍需各 family 的 reference simulator/oracle，不能由 K0 自证。

---

## 10. 三个首轮 Pareto profile 的可实现统一 API

下面三者是**原型 profile，不是第一、第二、第三名**。每个 profile 的 companion 都必须计入 primitive、blast radius 和消融账本。

### 10.1 公共控制接口

```text
CandidateRuntime<Family> {
  describe() -> Manifest<Family>
  validate(bundle: ModelBundle<Family>) -> ValidationReceipt
  load_history(history, environment_snapshot) -> Handle<Family>
  invoke<Q>(handle, query: ClosedQuery<Q>) -> Outcome<ValueOf<Q>>
  apply_delta(handle, EvidenceDelta) -> DeltaReceipt | Unsupported
  compose(bundles[], wiring: FamilyWiring<Family>)
      -> CompositionReceipt | UnsupportedComposition
  fetch_frozen_witness(result_id) -> NativeWitness
}
```

K0 负责 canonical workload、cut/版本合同、公共 outcome 与 audit envelope；`EvidenceAuthority` 在该合同下决定具体记录资格并生成冻结 evidence witness。adapter 只能转发或执行已声明的 typed transform，不能实现隐藏临床规则。

### 10.2 Profile A：Evidence-first（C10 TEL + C14 typed temporal logic/provenance）

原生语义可抽象为：

```text
H_C       = eligible versioned records at cut C
T_P       : H_C -> least grounded fixed point of typed rules P
Project_Q : (H_C, T_P(H_C)) -> EvidenceProjectionValue
```

`T_P` 可以由时间 Datalog、TMS、关系代数或等价执行器实现；其等价 oracle 是相同 active roots、规则版本和 cut 下的声明式结果/证明等价，不要求物理执行顺序相同。

- 权威状态：不可变 evidence/action/knowledge 版本历史及其 cut projection；这是完整运行时唯一的 `EvidenceAuthority`，不是 K0 之外的第二副本；
- 原生 query：`EvidenceView`、`Replay*`、`TaskProjection`、规则派生、`Explain`、`VerifyInvariant`；
- delta：DRed/TMS/差分或 rebuild，必须通过 K-I09；
- native witness：proof term / provenance DAG / event slice；
- compose：schema/rule module union，但先做类型、stratification、循环和版本检查；
- `Filter/Forecast/Do/Counterfactual` 若无显式动态/因果 bundle 必须 `Unsupported`，不能用 `Rule(fn)` 冒充。

最小可实现后端：SQLite/Postgres bitemporal tables + typed positive Datalog/rewrite materializer + proof DAG；event sourcing 不是强制物理实现。

### 10.3 Profile B：Causal-state（C03 state-space + C07 causal PPL/SCM capability）

原生语义至少显式区分：

```text
X_t ~ P_θ(X_t | X_<t, A_<t, U)        // latent transition/world
Y_t ~ P_θ(Y_t | X_≤t, A_≤t, M_t)     // observation/ascertainment
A_t = realized EffectToken or policy input

filter_t = P(X_t,U | Y_available_by_t, A_performed_by_t)
smooth_t = P(X_t,U | Y_allowed_after_t, A_history)
do(a)    = replace declared action mechanism, not condition on A=a
cf(a')   = abduce U from factual world; replace mechanism; predict with shared U
```

这里的 `X_t`、`U` 和分布族由 bundle 定义；K0 不为它们规定坐标、维数、Markov 性、连续/离散性或随机解释。

- 权威计算态：仅对该模型运行而言的 latent trajectory/exogenous variables/belief；外层 TEL/TMS `EvidenceAuthority` 仍是唯一 evidence authority，belief 不回写成 raw root；
- 原生 query：`FilterState`、`SmoothState`、`Forecast`、`Condition`；只有模型声明 mechanism replacement 和 identification contract 时才支持 `Intervene`；
- `IndividualCounterfactual` 要求 factual abduction + shared exogenous/noise policy，禁止独立重采样；
- delta：可从 checkpoint 重滤或全重算，算法不限但结果需满足 clean-rebuild oracle；
- native witness：model graph/program address、observation/transition factors、seed、solver diagnostics、posterior/trajectory artifact；不能冒充 evidence provenance；
- compose：因子乘积、state product 或 shared mechanism 只有在 model contract 声明时成立；共享患者 state 不得复制。

最小可实现后端：typed state/observation/intervention IR + exact/particle solver + causal mechanism IR；普通 action-conditioned SSM 不标 `do/counterfactual` capability。

### 10.4 Profile C：Typed rewrite/open composition（C13 + C17）

原生语义可抽象为：

```text
Configuration C : typed term in signature Σ
Step_R           : C -> set<C × RewriteWitness>
Reach_R(C,G)     : least/search-bounded reachable set under strategy G
OpenComponent    : (InputPorts, State, OutputPorts, Behavior_R)
```

若重写关系非终止、非合流或策略敏感，结果必须带 `StrategyDependent/ResourceBudgetExceeded/MultipleSolutions`；不能把任意找到的一条路径冒充唯一病程。

- 权威计算态：typed configuration、private component state、residual behavior；
- 原生 query：step/search、`Reachability`、`VerifyInvariant`、声明语义下的 forecast set；
- action：只有 `EvidenceAuthority` 按 K0 合同签发的 performed `EffectToken` 可触发 patient/observation rewrite；
- native witness：rewrite trace、normal form、reachability witness 或 bisimulation certificate；
- compose：typed ports + explicit interaction + feedback validator；重括号只在已声明无副作用子代数中要求同构；
- 撤回：proof-carrying terms 或 companion rebuild/TMS，必须通过 K-I09；
- alternate rewrite branch 不自动叫反事实，stochastic rewrite 不自动叫 posterior；没有 causal bundle 时 `Intervene/IndividualCounterfactual` 为 `Unsupported`。

最小可实现后端：closed term/sort/rewrite AST + strategy/termination diagnostics + typed open-component wiring IR。

### 10.5 公平归因

同一结果同时有：

```text
evidence_witness  // EvidenceAuthority 按 K0 合同冻结：roots、可见时间、版本、proof closure
native_witness    // 候选：factor subgraph / proof / rewrite trace / reachability
  capability_origin // benchmark attribution：native 或具体 companion
```

`runtime_capability` 只报告当前执行是否支持；`capability_origin` 属于 benchmark manifest/ablation，不污染临床结果语义。能力归因给最深层真正提供语义者。若 Profile B 靠外层 TEL 才重放，重放能力记为 companion；若 Profile A 调 causal solver 才做 `do`，因果能力记给 causal companion。这样不会把“混合后能做”误报成某家族原生全能。

---

## 11. 规范算法（候选无关伪码）

伪码规定**可观察语义**，不规定索引、数据库、增量算法或求解器。实现可替换算法，但必须给出相同 cut、版本、witness 和 typed failure。

### 11.1 A1：求一个 query 的合格记录集

```text
function ELIGIBLE_RECORDS(history H, query q, cut C):
    require validate_closed_query(q)
    require validate_cut(C)

    versions := { r in H |
        commit_time(r) <= C.transaction_revision_cut }

    active, version_conflicts := RESOLVE_VERSION_GRAPH(versions, C)
    if unresolved(version_conflicts):
        return Partial(active_without_conflicts,
                       diagnostics=version_conflicts)

    eligible := ∅
    excluded := ∅
    for r in active:
        reasons := []
        if not scope_compatible(r.scope, q.scope): reasons += ScopeMismatch
        if not visible_to(r, C.principal, C.actor_visibility_cut):
            reasons += MaskedOrNotYetAvailable
        if not authorized(r, C.principal, C.principal_and_authorization):
            reasons += Unauthorized
        if not query_time_policy(q).accepts(r.times, C.target_window):
            reasons += OutsideTargetWindowOrUnknownClock
        if not evidence_use_policy(C).accepts(r): reasons += PolicyExcluded

        if reasons = []: eligible += r
        else: excluded += (r.reference_without_secret_payload, reasons)

    assert all(r.known_time <= C.actor_visibility_cut for r in eligible
               when known_time is Known)
    return EligibleSet(eligible, excluded, C, version_vector(active))
```

`Unknown` time不满足依赖具体时点的谓词；实现不得用 collection/commit time 猜补。权限排除的诊断可以暴露“存在 masked 项”，但不得泄漏其值。

### 11.2 A2：原始输入、适配与隔离

```text
function INGEST(raw, adapter_version, principal):
    source := STORE_IMMUTABLE_SOURCE(raw, digest(raw), principal)
    adapter := LOAD_CLOSED_TYPED_ADAPTER(adapter_version)
    proposed := adapter.parse(source)        // 只生成 ProposedRecord

    failures := VALIDATE(
        discriminator, concept/unit versions, scope bindings,
        clock roles, source spans, measurement context,
        occurrence identity, action typestate, raw round-trip)

    if failures != ∅:
        QUARANTINE(source, proposed, failures)
        return IngestReceipt(Quarantined, failures, source.id)

    for p in proposed:
        if occurrence_version_exists(p.root_occurrence, p.version):
            assert semantic_digest(existing(p)) = semantic_digest(p)
            mark_idempotent_retry(p)
        else:
            ACCEPT(p, proof=Root(p.root_occurrence_version))

    return IngestReceipt(Accepted, accepted_ids, source.id)
```

adapter 只能做声明的句法解析和版本化映射；医学插补、`missing -> false`、单位近似与疾病判断必须是独立 artifact，不能藏在 `parse`。

### 11.3 A3：封闭查询调度与结果冻结

```text
function INVOKE(runtime R, query q): Outcome<ValueOf(q)>
    if not member(q, ClosedQuery): return ContractRejected(OpenQuery)

    cut_result := FREEZE_AND_VALIDATE_CUT(q.cut)
    if cut_result.failed: return Outcome(replay=MissingSnapshot, value=None)

    eligible := ELIGIBLE_RECORDS(R.history, q, cut_result.cut)
    claim := R.manifest.capability_for(tag(q))
    if claim = None:
        return Outcome(execution=Blocked, completeness=None,
                       runtime_capability=Unsupported(tag(q)), value=None,
                       temporal_cut=cut_result.cut)

    native := DISPATCH_TO_DECLARED_ORIGIN(claim.origin, eligible, q)
    outcome := NORMALIZE_WITHOUT_ERASING(native,
        coverage, identification, numerics, applicability,
        safety, replayability, field_availability)

    witness := FREEZE(
        exact eligible roots used by native,
        proof closure, cut, all version digests,
        assumptions, external/random/environment snapshots,
        native witness, capability origin)

    assert roots(witness) subset_of roots(eligible)
    assert no_unproved_taint_downgrade(outcome)
    result_id := STORE_IMMUTABLE(ComputationRecord(q,outcome,witness))
    return outcome.with(result_id, witness.refs)
```

`NORMALIZE_WITHOUT_ERASING` 只把家族诊断嵌入 Outcome 乘积；它不得把 `NotIdentified`、`OutOfModel`、`NonConverged` 或 `Unsafe` 洗成一个普通值。

### 11.4 A4：有根、局部非爆炸的派生

```text
function GROUNDED_DERIVE(eligible roots E, typed rules P):
    W_plus, W_minus := empty shared proof maps
    queue := all accepted Root(e) for e in E

    while queue not empty:
        p := pop(queue)
        add p to polarity_bucket(claim(p))
        for rule in rules_enabled_by(p):
            premises := MATCH_EXPLICIT_PREMISES(rule, W_plus, W_minus)
            if not rule.conflict_policy.accepts(premises): continue
            if not scope_time_types_match(rule, premises): continue
            q := Apply(rule.version, premises, rule.assumptions)
            assert roots(q) = union(roots(x) for x in premises)
            if q adds a new typed proof: queue.push(q)

    for epistemic SCC in dependency_graph(W_plus,W_minus):
        if no Root/EffectToken/declared prior reaches SCC:
            remove unsupported proofs from SCC
            emit IllegalSelfSupport(SCC)

    return ClaimEvidenceMap(W_plus,W_minus)
```

合法生理反馈不由此算法求解，而交给有固定点/求解器合同的 native subkernel；认识论 SCC 与动态 feedback 不能共用“有环”这一粗标签。

### 11.5 A5：更正、撤回与增量一致性

```text
function APPLY_DELTA(handle h, VersionDelta d):
    CHECK_VERSION_TRANSITION(d)
    append_only(h.history, d)
    active_new := ELIGIBLE_RECORDS(h.history, h.query, h.cut)

    if h.family.supports_native_delta:
        inc := h.family.incremental_update(d, active_new)
    else:
        inc := h.family.clean_rebuild(active_new)

    if validation_mode:
        clean := h.family.clean_rebuild(active_new)
        assert family_equivalent(inc.value, clean.value)
        assert witness_roots(inc) = witness_roots(clean)

    assert every surviving derived claim has at least one active proof
    assert no inactive root occurs in frozen_new_witness(inc)
    return DeltaReceipt(inc, changed_claims, invalidated_proofs)
```

历史 `ComputationRecord` 不被改写；新 cut 生成新 result。替代 proof 尚存时只缩减 witness，不删除结论。

### 11.6 A6：动作生命周期与效应发行

```text
function RECORD_ACTION_EVENT(event e):
    previous := latest_active_action_version(e.action_id)
    require workflow_schema(e.concept).allows(previous.phase, e.phase)
    require idempotency_key_consistent(e)
    append_only(action_history, e)

    if e.phase in {Started, PartiallyPerformed, Performed}
       and valid_execution_receipt(e.receipt_artifact):
        token := EffectToken(realized_extent_from_receipt(e),
                             actual_execution_interval(e),
                             Root(e.receipt_root))
        emit token to state-effect and/or observation-effect ports
    else:
        emit no EffectToken

    if e.phase in {Paused, Cancelled, Stopped, Refused, NotPerformed}:
        close_only_existing_effect_interval_if_applicable(e)
```

`simulate_intervention` 使用假设性 do-set，永不调用本算法、永不写 action history。

### 11.7 A7：端口与组合验证

```text
function VALIDATE_COMPOSITION(components M, wiring W):
    for edge (a.out -> b.in, bridge?) in W:
        require directions_and_multiplicity_match(a,b)
        require scope_binding_proved(a,b,bridge)
        require concept_value_unit_compatible(a,b,bridge)
        require time_basis_compatible(a,b,bridge)
        require epistemic_roles_compatible(a,b,bridge)
        require provenance_and_uncertainty_semantics_preserved(a,b,bridge)

    require unique_state_owner_or_explicit_shared_reference(M,W)
    require no hidden global reads/writes(M)
    require all_required_interactions_present_or_return_unsupported(M,W)

    for feedback loop L in W:
        require delay(L) or unique_fixed_point_proof(L)
                or solver_contract_can_report_no/multiple/nonconverged(L)

    laws := intersection_of_explicitly_claimed_laws(M,W)
    return FamilyWiring(W, laws, interaction_set, validation_witness)
```

任何 bridge 都是独立模块并计入复杂度；wire 不得执行隐藏的单位换算、likelihood 变换或患者身份合并。

### 11.8 A8：三种历史读出的确定性重放

```text
function REPLAY(target_cut C, mode, requested_query q):
    switch mode:
      ReplayAsThen:
        evidence_cut := C.actor_visibility_cut
        versions := snapshots.effective_as_of(C.transaction_revision_cut)
      ReinterpretCurrentTheory:
        evidence_cut := C.actor_visibility_cut
        versions := current_knowledge_model_policy_versions
      RetrospectiveReconstruction:
        evidence_cut := explicitly_allowed_later_evidence_cut
        versions := q.requested_version_policy

    require all terminology/model/policy/external/random/environment snapshots
    q2 := q.with(TemporalCut(C.target_window, evidence_cut, versions, ...))
    result := INVOKE(cold_runtime_without_unkeyed_cache, q2)
    assert cache_key_contains(all cut and version dimensions)
    return result
```

重放缺快照时必须 `Replay=MissingSnapshot/VersionUnavailable`，不能偷偷调用当前外部服务。

### 11.9 A9：foreign boundary 门禁

```text
function REGISTER_FOREIGN(contract F, executable B):
    require digest(B) = F.code_digest
    require closed_schema(F.inputs,F.outputs,F.failure_map)
    require declarative_constraint_ast(F.pre,F.post,F.provenance_map)
    require environment/dependency/random/network/side_effect declaration complete
    require validation_fixtures_pass(F,B)
    require raw_canary, alpha_rename, reorder, timeout, replay tests pass
    if F claims safety invariant and is opaque: reject claim
    register capability origin = Companion(F.operator_id)
```

无法通过门禁的组件可留在实验隔离区，但它的输出是 `Invalid/Unsupported`，不能计为 Track A 原生能力。

### 11.10 A10：解释读取

```text
function EXPLAIN(result_id, principal):
    c := immutable ComputationRecord[result_id]
    require authorized_for_witness(principal,c)
    return redact_without_semantic_reinterpretation(
        c.frozen_evidence_witness,
        c.frozen_native_witness,
        c.outcome_product,
        c.temporal_cut,
        c.version_vector)
```

解释是冻结审计对象，不是“现在根据结果再生成一段看起来合理的话”。自然语言渲染可以更新，但必须引用同一 witness，并明确 renderer 版本。

---

## 12. 测试到规范的追踪矩阵

下表中的 `Ixx` 是 `K-Ixx` 的简写。一个测试可能触发更多不变量；这里列的是决定性最小映射，不是唯一覆盖关系。

### 12.1 T01–T50

| 测试 | 主要规范点 | 共同不变量 | 需要的 native/行为 oracle |
|---|---|---|---|
| T01 | `EffectToken`、state/observation 分离 | I12, I23 | 支持治疗下的 task/state projection 不与无治疗碰撞 |
| T02 | 测量上下文与作用域 | I02, I12, I21 | 高流量氧与室内空气观测不同构 |
| T03 | observation effect 独立端口 | I12, I23 | 退热后正常值不否定潜在机制 |
| T04 | treatment/device/context typed ports | I02, I12 | β 阻滞与起搏器修饰可区分 |
| T05 | observation model、既往 action | I11, I12, I21 | 抗菌药后阴性培养不等于无感染 |
| T06 | proof roots 幂等 | I05, I06 | 三个派生词只保留一个 occurrence root |
| T07 | dependence family ≠ provenance | I05, I16 | 未声明独立时联合模型返回假设/部分结果 |
| T08 | 双支持与多假说 | I08, I23 | 两机制可并存，不强制单标签 |
| T09 | context-conditioned model | I14, I23 | 同一疾病 schema 可被个体上下文调制 |
| T10 | 双支持、非爆炸 | I08 | 正反来源并存为 `Conflicting` |
| T11 | `ExplicitNoValue` 约束 | I08, I21 | 无记录不生成 refuting root |
| T12 | `TemporalCut`/A1 | I03 | 09:00 不见 12:00 结果，13:00 可见 |
| T13 | knowledge/evidence visibility | I03, I10 | 首诊回放无最终诊断及其派生 |
| T14 | subject baseline/context scope | I02, I23 | 同一 raw 值因基线不同得到不同读出 |
| T15 | 只读 `TaskProjection` | I10, I26 | 两任务视图不同且 source-of-record 不变 |
| T16 | interaction component | I14, I15 | 无非线性交互合同即 `UnsupportedComposition` |
| T17 | 双效应端口 | I12, I14 | state effect 与 observation effect 分别追踪 |
| T18 | `Condition`/`Intervene` 边界 | I11, I16 | 无识别合同不做唯一治疗归因 |
| T19 | query-specific time eligibility | I03 | 当前排除 stale，历史 cut 仍保留 |
| T20 | coverage outcome | I16, I23 | 合法返回 `OutOfModel/Partial` |
| T21 | 内容扩展协议 | I18 | 新药只加 module，不改 K0 opcode |
| T22 | typed adapter/quarantine | I02, I18, I25 | 新方法未注册时隔离，不伪装旧方法 |
| T23 | 三种 replay mode | I04 | 当时规则与当前理论产生可区分结果 |
| T24 | A5 truth maintenance | I09 | 仅依赖撤回 root 的 proof 消失，替代支持保留 |
| T25 | A8 冷重放 | I03, I04 | 固定快照语义等价且无 future leak |
| T26 | `SafetyInvariant` 独立于检索 | I16, I26 | 适用域内必执行，漏召回不影响结果 |
| T27 | occurrence identity 与依赖 | I01, I05 | 两次实测两个 roots，三次改写一个 root |
| T28 | ClaimEvidence/多模型 | I08, I16 | 多假说保留各自支持、反对、未知 |
| T29 | raw source + quarantine | I02, I25 | 不可表达设备状态保留 raw 且 typed failure |
| T30 | adapter 规范化与 source span | I02, I25 | 等价改写语义同构，原文 provenance 不同 |
| T31 | grounded SCC | I07 | 无根循环不增信；合法 fixed point 分流到 native |
| T32 | transaction version graph | I03, I09 | 旧快照不变，新 cut 递归更新 |
| T33 | unit/method bridge | I02, I21 | 无版本化转换即拒绝合并 |
| T34 | fan-out proof algebra | I05, I06 | 两模块汇总不复制 root |
| T35 | solver/outcome 乘积 | I16 | 算法、种子、误差和收敛状态齐全 |
| T36 | knowledge version/retraction | I04, I09 | 事实不变；新规则视图撤派生，旧视图可复现 |
| T37 | action typestate/A6 | I12 | 只有实际实施区间生成 EffectToken |
| T38 | port validator/A7 | I14 | 接口不匹配在运行前 typed failure |
| T39 | model disagreement | I15, I16 | 不兼容模型不静默平均；保留仲裁/冲突 |
| T40 | 完整 cache key/A8 | I03, I04 | 冷缓存与缓存结果语义等价 |
| T41 | typed `Scope` | I02 | 患者/就诊/标本不串线 |
| T42 | `MeasuredValue` sum type | I02, I21 | 检测限/超量程不转 exact scalar |
| T43 | ascertainment scope | I08, I21 | 无观察机会不产生阴性证据 |
| T44 | 局部 paraconsistent 读出 | I08 | rash 冲突不推出无关 fracture |
| T45 | raw round-trip | I02, I21, I25 | 两次规范化仍可回到 raw/span/mapping version |
| T46 | `EvaluatePolicy` 合同 | I13, I16 | 无目标/效用/约束不返回唯一最优 |
| T47 | 模型/政策暴露谱系 | I22 | 更新可回滚，策略诱导数据有标记 |
| T48 | action/event 幂等 | I01, I12 | 重试不重复施效，取消关闭实际区间 |
| T49 | `SemanticScope`/bridge | I10, I26 | 指南不等于患者已给药 |
| T50 | 权限与信息状态正交 | I20 | masked/unauthorized 不变成 absent 且不泄漏 |

### 12.2 E01–E08

| 实验 | K0 只负责 | 必需原生能力/参考 oracle | 主要不变量 |
|---|---|---|---|
| E01 治疗掩盖下过滤/停药预测/反事实 | 正确 cut、EffectToken、query 类型、witness | Causal-state 的显式 transition/observation/action；filter/forecast/counterfactual 数值 oracle | I11, I12, I23 |
| E02 `see`/`do` 符号反转 | 禁止 query 降级，报告 identification | SCM/causal PPL 的 mechanism replacement 与已知解析答案 | I11, I16 |
| E03 同患者共享外生背景 | 冻结 factual cut 与 shared-world policy | abduction-action-prediction；paired-noise 参考模拟 | I11, I16 |
| E04 不规则非线性滞后/脉冲 | clocks、solver diagnostics、effect interval | SSM/ODE/SDE/rewrite 中声明的动态 oracle | I03, I12, I15, I16 |
| E05 同表型两机制选择性干预 | 多假说、coverage、query 类型 | 显式 latent mechanisms 与选择性 action mechanism | I08, I11, I23 |
| E06 三模块非线性共病/药代 | typed ports、interaction presence、failure | open/rewrite/causal-state 的非线性交互参考模拟 | I14, I15, I16 |
| E07 括号/注册/并发顺序 | 只检查 manifest 声明的代数律 | family-specific 同构/分布/可达集等价 oracle | I03, I15 |
| E08 合法反馈 vs 自证 | 区分 epistemic SCC 和 dynamic loop | grounded proof oracle；动态固定点/多解/不收敛 oracle | I07, I15, I16 |

本矩阵刻意把“共同控制面通过”与“native 数值/因果/动态正确”分开。K0 不能因为成功路由 E01–E08 就领取动态能力分；能力归因仍由 manifest、witness 和 companion ablation 决定。

---

## 13. 版本、迁移与“固定核心”的含义

### 13.1 不触发 K0 升级的内容扩展

下列变化只增加版本化 artifact/bundle，不改变 K0 opcode：

- 新疾病、药物、检查、设备、单位或术语概念；
- 新的 deterministic rule、安全 invariant、动态/观察/因果/交互模型；
- 新 task projection、utility contract 或知识版本；
- 在既有 `ClockRole/EpistemicRole/ClosedQuery` 中可完整表达的新 workflow。

扩展接受条件为：schema/port 验证通过、测试 fixture 通过、blast radius 中 K0 主分支修改数为 0、旧版本仍可 replay。

### 13.2 必须显式升级 K0 的语义变化

若出现以下情况，宁可发布 `K0-v0.2`，也不得塞进自由 metadata：

- 新的认识论角色无法由现有 sum type 无损表达；
- 新时间角色会改变 admissibility 或历史问题的含义；
- 新 closed query 与既有 query 在因果/信息边界上不可等价；
- Outcome 需要新的正交 failure 维度；
- 既有 proof/action/scope 不变量被真实反例推翻。

升级包必须包含：旧到新类型的 total/partial migration、不可迁移项的 quarantine 策略、旧 runtime 的读取路径、重放差异说明、对应新增反例与消融证据。固定核心的含义是**普通医学词汇扩展不改控制面**，不是永远拒绝纠正核心语义。

### 13.3 兼容性

```text
migrate : Artifact<K0-v_old> × MigrationPlan<v_old,v_new>
       -> Result<Artifact<K0-v_new>, MigrationFailure>
```

只有当目标版本可以无损承载原语义时，`migrate` 才能成功。升级或降级都不得丢 scope、clock、proof、action phase 或 Outcome 诊断；否则返回 typed `MigrationFailure` 并保留 raw artifact。

---

## 14. 尚未解决与可推翻条件

1. Proof DAG、四态支持与增量撤回在大规模递归下是否会爆炸，需实测；
2. 哪些 `DependenceAssumption` 足以安全支持联合 likelihood，不能由 K0 决定；
3. dynamic/causal/rewrite 三家之间的 bridge 是否会比显式混合架构更复杂，需按展开 IR 与 blast radius 计账；
4. typed port registry 是否会退化为另一个由自由文本/LLM 决定的全局瓶颈，需 alpha-renaming 与 hidden holdout 攻击；
5. `ReinterpretCurrentTheory` 与 `RetrospectiveReconstruction` 的产品需求边界必须在测试数据中冻结；
6. 若任一单一家族可在不隐藏完整 K0、无 foreign callback、无额外特例的条件下原生通过所有 HARD 和 E01–E08，则应缩减或推翻本共同内核；
7. 若某个 K0 原语消融后所有硬测试、trace 和 failure 语义均不变，应删除该原语；
8. 本草案不证明诊断准确、治疗获益、临床校准、公平性或生产安全，这些仍属于 `REQUIREMENTS.md` 的部署边界。

## 15. v0.1 pre-bridge 冻结基线（历史；当前已重开）

在 2026-07-13 pre-bridge 阶段，本研究覆盖的 13 个候选家族、3 个原子原型与冻结反例曾支持以下待证共同内核，而不是一个万能 `PatientState`：

```text
typed evidence/action/knowledge ledger contract
+ multi-role time and version cuts
+ grounded proof and retraction semantics
+ closed query and product outcome algebra
+ typed composition contracts and fail-closed invariants
```

该 pre-bridge K0 基线只固定上述类型、身份、cut、port 和审计合同；唯一权威 evidence 历史由 TEL/TMS `EvidenceAuthority` 参考子内核实现。完整参考联邦还必须装配 state/dynamics、causal 与 typed rewrite/open safety 能力；缺失能力按第 0.2 节局部降级，不得静默代答。

它故意不规定患者动力学、概率、因果、反事实、重写和组合的唯一语义。这个“不统一”不是缺口，而是防止候选用无类型 payload 或自由 callback 把互不等价的问题伪装成一个核心原语的主要约束。

这里的“最小共同内核”只是有删除反例支持的**历史经验性研究基线**，不是不可约性定理。本文既未穷举全部可能 calculus，也未证明七类 K0 承诺彼此不可导出；第 14 节的消融、新 calculus 和 hidden holdout 都可以收缩或推翻它。当前 Python 参考代码也只是第 0.3 节的可执行子集，不能把“可运行”升级为“已实现完整形式规范”。

2026-07-14 bridge 轮已经触发这种重开：冻结 A/B 的 bridge-stability 主张在实现层为 `HYPOTHESIS_FAIL`；sealed 41-case corpus 在实验层为 `HARNESS_INCOMPLETE`（H01–H30 原预注册集，H31–H41 post-seal/pre-execution addendum）。因此本规范当前是 Checkpoint 3/7 的目标合同和待证基线，不是已经胜出的固定核心；该结果淘汰冻结 A/B 的合规 bridge 主张，但不构成 K0 family 或所有 versioned bridge 的不可能性证明。
