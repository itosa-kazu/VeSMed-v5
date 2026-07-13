# “最小共同语义内核”形式化草案

> 状态：Checkpoint 2/3 之间的候选无关草案，不是最终选型。  
> **已被 `FORMAL_SPEC.md` 取代**：本历史草案把 “K0 history” 写成 evidence authority；最终规范已修正为 K0 只固定 ledger port/identity/cut/witness 合同，TEL/TMS 是完整参考联邦唯一的 evidence authority。本文保留作研究路线记录，不作为架构或 conformance 依据。  
> 依据：`FIRST_PRINCIPLES.md`、`REQUIREMENTS.md`、`ARCHITECTURE_TESTS.md`、`EXPERIMENTS.md` 与 `research_notes/01–12`。  
> 本文只回答：不同候选若要被公平比较或安全拼装，最少必须共享什么合同；它**不回答**患者动力学最终应由 TEL、图、状态空间、概率程序、重写或开放系统中的哪一家承担。

## 0. 一句话边界

共同内核只统一：

> **谁，在什么作用域和时间截面，基于哪些合格且可追溯的输入，使用哪些版本化知识/模型，执行了哪一类封闭查询，并以什么能力、覆盖、识别和数值状态返回结果。**

共同内核不统一：

> **“患者世界状态是什么”“一步更新是什么”“不确定性是什么”“两个动态模块怎样组合”“两个运行结果何时等价”。**

后一组问题必须由明确的能力子内核回答。若把它们塞进 `Node(payload)`、`Rule(fn)`、`Component(callback)` 或一个万能 `update(state, any)`，形式上的原语减少了，实际语义只是转移到了不可审计的宿主代码。

因此本文提出的是一个 **semantic control plane / audit boundary**，不是“万能患者容器”，也不是披着混合架构名字的预定赢家。

---

## 1. 核心签名与对象

令最小共同内核为：

```text
K0 = (MetaTypes, Identity, Records, TimeCuts, Proofs,
      Capabilities, ClosedQueries, Outcomes, Invariants)
```

这是语义签名，不要求物理存储采用图、事件流或关系数据库。实现可以使用 MVCC、不可变日志、关系表或内容寻址对象；只要历史版本、资格判断和重放语义等价即可。

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

### 1.2 不能再压缩的五类持久对象

#### A. `SourceArtifact`

```text
SourceArtifact {
  artifact_id, artifact_version, source_system_id,
  immutable_raw_bytes_or_text, source_locator,
  received_at, integrity_digest, access_policy
}
```

它保存原文、原值、原单位和 source span 的最终锚点。raw payload 可以任意，因为它只用于往返、隔离与审计；**任何医学计算不得直接从 raw payload 取语义**。必须先经版本化 adapter 生成 proposed typed record，再验证接纳。

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
  predecessor_action_event?, policy_model_exposure?, version
}
```

只有带执行回执且 phase 为 `Started/PartiallyPerformed/Performed` 的记录可以生成 `EffectToken`；计划、医嘱、模拟和政策建议没有从类型上到 `EffectToken` 的隐式转换。撤销/停止关闭实际作用区间，不倒写历史。

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

### 1.3 身份至少四分，不能只用一个 `source_group_id`

1. **Proposition identity**：两条记录是否在说同一命题；
2. **Artifact/version identity**：哪一份文档/消息的哪一版本；
3. **Evidence-root occurrence identity**：现实中哪一次最小 evidence-producing act；
4. **Dependence-family membership**：同一标本、设备、文档、校准批次、采样时段等可重叠来源族。

同一 root 可以属于多个 dependence family；同一 artifact 可含多个 roots；两个不同 roots 也可能高度相关。稳定 root id 解决重复摄取，不能自动证明统计独立。

### 1.4 最小性删除反例

| 删除的对象/区分 | 立即无法满足的反例 |
|---|---|
| `SourceArtifact` | T29/T45 无法保留不可表达输入和 raw round-trip |
| Statement 构造子分型 | T06/T49 推断可伪装原始观察并自证 |
| `ActionRecord`/typestate | T37/T48 计划、取消与实际实施混同 |
| `KnowledgeArtifact` 版本 | T23/T36 无法区分当时规则与今天重释 |
| `ComputationRecord` + frozen witness | T25/T35/T40 结果不可确定重放或事后解释漂移 |
| typed scope/identity | T41 两个患者、标本或设备串线 |

这只证明这些区分有已知删除见证，不声称已从数学上证明全局最小；最终仍需按 `S-MIN-02` 做消融。

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
store_source(SourceArtifact)
adapt(source_id, TypedAdapterVersion) -> ProposedRecords
accept_or_quarantine(ProposedRecords) -> IngestReceipt
append_correction_or_retraction(VersionDelta) -> DeltaReceipt
record_action_event(ActionRecord) -> Receipt
register_schema(SchemaPackage) -> ValidationReceipt
register_module(FamilyModelBundle) -> ValidationReceipt
compose(FamilyWiring) -> CompositionReceipt | UnsupportedComposition
invoke(ClosedQuery) -> Outcome<ValueOf<Query>>
fetch_frozen_witness(result_id) -> AuditWitness
```

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

这些不变量分别覆盖 T01–T50 与 E01–E08 的共同安全边界；动态数值正确性仍需各 family 的 reference simulator/oracle，不能由 K0 自证。

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

K0 负责 canonical workload、cuts、版本、admissibility、公共 outcome 与 audit envelope；adapter 只能转发，不能实现临床规则。

### 10.2 Profile A：Evidence-first（C10 TEL + C14 typed temporal logic/provenance）

- 权威状态：不可变 evidence/action/knowledge 版本历史及其 cut projection；
- 原生 query：`EvidenceView`、`Replay*`、`TaskProjection`、规则派生、`Explain`、`VerifyInvariant`；
- delta：DRed/TMS/差分或 rebuild，必须通过 K-I09；
- native witness：proof term / provenance DAG / event slice；
- compose：schema/rule module union，但先做类型、stratification、循环和版本检查；
- `Filter/Forecast/Do/Counterfactual` 若无显式动态/因果 bundle 必须 `Unsupported`，不能用 `Rule(fn)` 冒充。

最小可实现后端：SQLite/Postgres bitemporal tables + typed positive Datalog/rewrite materializer + proof DAG；event sourcing 不是强制物理实现。

### 10.3 Profile B：Causal-state（C03 state-space + C07 causal PPL/SCM capability）

- 权威计算态：latent trajectory/exogenous variables/belief；外层 K0 history 仍是 evidence authority；
- 原生 query：`FilterState`、`SmoothState`、`Forecast`、`Condition`；只有模型声明 mechanism replacement 和 identification contract 时才支持 `Intervene`；
- `IndividualCounterfactual` 要求 factual abduction + shared exogenous/noise policy，禁止独立重采样；
- delta：可从 checkpoint 重滤或全重算，算法不限但结果需满足 clean-rebuild oracle；
- native witness：model graph/program address、observation/transition factors、seed、solver diagnostics、posterior/trajectory artifact；不能冒充 evidence provenance；
- compose：因子乘积、state product 或 shared mechanism 只有在 model contract 声明时成立；共享患者 state 不得复制。

最小可实现后端：typed state/observation/intervention IR + exact/particle solver + causal mechanism IR；普通 action-conditioned SSM 不标 `do/counterfactual` capability。

### 10.4 Profile C：Typed rewrite/open composition（C13 + C17）

- 权威计算态：typed configuration、private component state、residual behavior；
- 原生 query：step/search、`Reachability`、`VerifyInvariant`、声明语义下的 forecast set；
- action：只有 K0 的 performed `EffectToken` 可触发 patient/observation rewrite；
- native witness：rewrite trace、normal form、reachability witness 或 bisimulation certificate；
- compose：typed ports + explicit interaction + feedback validator；重括号只在已声明无副作用子代数中要求同构；
- 撤回：proof-carrying terms 或 companion rebuild/TMS，必须通过 K-I09；
- alternate rewrite branch 不自动叫反事实，stochastic rewrite 不自动叫 posterior；没有 causal bundle 时 `Intervene/IndividualCounterfactual` 为 `Unsupported`。

最小可实现后端：closed term/sort/rewrite AST + strategy/termination diagnostics + typed open-component wiring IR。

### 10.5 公平归因

同一结果同时有：

```text
evidence_witness  // K0：原始 roots、可见时间、版本、proof closure
native_witness    // 候选：factor subgraph / proof / rewrite trace / reachability
  capability_origin // benchmark attribution：native 或具体 companion
```

`runtime_capability` 只报告当前执行是否支持；`capability_origin` 属于 benchmark manifest/ablation，不污染临床结果语义。能力归因给最深层真正提供语义者。若 Profile B 靠外层 TEL 才重放，重放能力记为 companion；若 Profile A 调 causal solver 才做 `do`，因果能力记给 causal companion。这样不会把“混合后能做”误报成某家族原生全能。

---

## 11. 尚未解决与可推翻条件

1. Proof DAG、四态支持与增量撤回在大规模递归下是否会爆炸，需实测；
2. 哪些 `DependenceAssumption` 足以安全支持联合 likelihood，不能由 K0 决定；
3. dynamic/causal/rewrite 三家之间的 bridge 是否会比显式混合架构更复杂，需按展开 IR 与 blast radius 计账；
4. typed port registry 是否会退化为另一个由自由文本/LLM 决定的全局瓶颈，需 alpha-renaming 与 hidden holdout 攻击；
5. `ReinterpretCurrentTheory` 与 `RetrospectiveReconstruction` 的产品需求边界必须在测试数据中冻结；
6. 若任一单一家族可在不隐藏完整 K0、无 foreign callback、无额外特例的条件下原生通过所有 HARD 和 E01–E08，则应缩减或推翻本共同内核；
7. 若某个 K0 原语消融后所有硬测试、trace 和 failure 语义均不变，应删除该原语；
8. 本草案不证明诊断准确、治疗获益、临床校准、公平性或生产安全，这些仍属于 `REQUIREMENTS.md` 的部署边界。

## 12. 暂定结论

最小共同内核最有根据的形式不是一个万能 `PatientState`，而是：

```text
typed evidence/action/knowledge boundary
+ multi-role time and version cuts
+ grounded proof and retraction semantics
+ closed query and product outcome algebra
+ capability-specific model bundles
+ typed composition contracts and fail-closed invariants
```

它故意不规定患者动力学、概率、因果、反事实、重写和组合的唯一语义。这个“不统一”不是缺口，而是防止候选用无类型 payload 或自由 callback 把互不等价的问题伪装成一个核心原语的主要约束。
