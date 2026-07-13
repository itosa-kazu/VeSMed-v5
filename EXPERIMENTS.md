# 原型与实验记录

> 当前阶段：**预注册协议 + 最终实际执行记录**。第 1–11 节保留实验冻结前的
> 设计与判据；第 12–18 节记录 panel 红队后真正执行的结果，第 19 节记录 bridge
> counterevidence。在 v1–v3 panel 谱系中，只有 `results/20260713T120910Z-panel-v3/`
> 是 decision-grade panel；bridge 证据另由 `results/bridge-holdout/` 记账。v1、v2 均只保留为
> 可审计的失效/中间诊断证据。这里没有用通过数选“万能赢家”。

## 1. 实验问题

不是证明某候选“什么都能编码”，而是比较：

1. 它用原生语义能通过哪些硬不变量；
2. 为通过其余测试需要哪些通用伴随层、额外领域假设或特例；
3. 动态、因果、组合和审计能力是否同时成立；
4. 新知识加入后影响范围与历史可重放性；
5. 失败时能否明确拒绝，而不是静默给出错误。

## 2. 共同语义工作负载

所有候选读取同一 canonical workload，但不要求内部使用同一数据结构。workload 包含：

- source artifacts 与稳定 source identity；
- subject/encounter/specimen/device/site scope；
- valid/effective、collected、available、recorded/transaction、expiry；
- artifact role（observation/report/request/performed intervention/inference/hypothesis）；
- explicit information state 与 raw payload；
- task/query contract；
- versioned domain commitments；
- expected relation/metamorphic/numeric oracle。

传输 JSON 只是测试协议，不计为任何候选的核心原语。

## 3. 候选必须提交的 manifest

```text
candidate_id / version
formal_signature
execution_semantics
required_store / solver / runtime
companion_layers
semantic_adapters
safety_monitors
domain_knowledge_packages
generated_artifacts / caches
declared_composition_laws
declared_query_capabilities
failure/result types
```

任何 `Rule(fn)`、`Factor(fn)`、`Component(fn)`、`Node(payload)`、宿主语言 callback 都必须报告 foreign escape hatch 和实际承担的语义族。

## 4. 候选无关控制面与分家执行语义

具体方法名可不同，但测试适配器只允许转发下列行为，不得偷偷实现临床语义。公共控制面不定义统一 `PatientState` 或万能 `update`：

```text
ingest(source_artifact) -> accepted | typed_error
invoke(closed_query, temporal_cut, version_vector) -> capability_result
correct_or_retract(source_id, new_version) -> delta / affected result
replay(cut, replay_as_then | reinterpret_now) -> result
register_module(module) -> accepted | interface_error
compose(wiring) -> system | unsupported_composition
explain(result_id) -> native witness + audit envelope
```

`closed_query` 是封闭并列类型，至少区分 `evidence_view / filter / smooth / forecast / condition / intervene / same-patient-counterfactual / task_projection / policy_evaluation / reachability / invariant_check`。`performed_action` 是输入事件；`propose_action` 是政策输出；二者都不是 `simulate_intervention` 的别名。`register_module` 只接受按 TEL、causal-state、rewrite/open 家族分开的封闭 IR，禁止 callback、SQL、prompt、bytecode 和自由 `Any`。

撤回的行为 oracle 是：增量 delta 后的结果必须等于从剩余输入 clean rebuild；不强迫候选实现 TMS。

## 5. 正交结果 envelope

```json
{
  "status": "compatibility-summary-only",
  "validation": "valid|invalid",
  "capability": "native|companion|unsupported",
  "epistemic": "supported|refuted|unknown|conflicting|not_applicable",
  "coverage_status": "in_domain|partial|out_of_model|unknown",
  "identification": "identified|partially_identified|not_identified|not_applicable",
  "computation": "exact|approximate|nonconverged|no_solution|multiple_solutions|not_applicable",
  "value_kind": "exact|set|interval|distribution|qualitative|none",
  "value": null,
  "assumptions": [],
  "coverage": {},
  "time_cut": {},
  "evidence_witness": {},
  "native_witness": {},
  "diagnostics": {},
  "versions": {}
}
```

`native_witness` 可是 proof term、factor subgraph、event slice、rewrite trace、reachability witness 或版本化程序地址。audit envelope 不替候选制造其原本没有的血缘。单一 `status=ok` 不得洗掉 `conflict + out_of_model + not_identified + solver_ok` 这种可同时成立的状态。

## 6. 两条赛道与消融

### Track A：Native

只允许候选固定签名、执行语义和最小序列化。用于判断家族天然能力。

### Track B：Companion

允许加入通用时间、provenance、验证器、求解器或 OOD 伴随层。所有伴随层计入 primitive profile、代码量、special-case ledger 与 blast radius。

### Ablation

逐层关闭伴随能力，证明每个测试通过来自哪里。最终候选若只在 Track B 通过，报告中必须称其为明确的混合架构。

## 7. 共享领域承诺账本

```text
K_shared  所有候选相同的医学/数学承诺
K_extra   某候选额外引入的领域假设
G_general 候选通用架构/算法规则
S_patch   面向测试或窄缺口、不可普遍复用的补丁
```

同一“抗菌药改变培养敏感性”在 rule、factor、ODE 或 transition 中都算同一个 `K_shared`，不能只惩罚规则候选。冻结测试后，含 case/test ID、无依据 concept branch、阈值/bonus、adapter 偷补语义或窄调度分支的改动计入 `S_patch`。

## 8. 三类 oracle

1. **Exact**：明确状态、错误类型或 trace root；
2. **Relational/metamorphic**：重复不变性、未来扰动不变性、clean rebuild 等价、组合括号等价；
3. **Reference simulator**：E01–E06 的数值轨迹/分布/可达集容差。

随机候选必须多 seed；确定性候选不被迫伪造概率。宽集合可通过安全包含，但不获得“校准概率”能力标签。

## 9. 评价账本

### Primitive profile

```text
P = (
  object/value constructors,
  state/update operators,
  time/visibility operators,
  uncertainty/belief operators,
  composition/wiring operators,
  query/readout operators,
  built-in invariant/constraint forms,
  foreign semantic escape hatches
)
```

### Special cases

分别报告 `S_case_id`、`S_concept`、`S_numeric`、`S_adapter`、`S_execution`。

### Blast radius

```text
B = (
  core_signature_changes,
  core_semantics_units_changed,
  adapter_units_changed,
  existing_knowledge_modules_changed / total,
  persistent_migrations,
  generated_artifacts_invalidated / total,
  models_retrained / total,
  historical_records_reprocessed / total,
  caches_rebuilt / total,
  existing_tests_modified,
  existing_tests_failed,
  wall_time,
  peak_memory
)
```

文件数和 LOC 只作附录；它们不能跨单体/模块化实现公平比较。

## 10. 预注册实验集

- `T01–T50`：认识论、时间、证据、开放世界、动作与失败语义；
- `E01–E08`：动态过滤/预测、`see/do`、同一患者反事实、不规则非线性轨迹、选择性干预、非线性共病组合、组合律和反馈良定性；
- 三个预注册扩展语义类：new disease、new drug、new test method；另有一个 task projection 扩展示例；
- 隐藏 holdout：概念别名、参数、模块注册顺序、第二套同构医学词汇。

### 10.1 用户要求的 11 项原型演示 crosswalk

这 11 项不是由一段 happy-path JSON 自报完成。每项都必须能落到一个真实执行入口、
一个自动测试或冻结 workload，以及可检查的 output/capture。`demo_output.json` 是面向人的
短演示；T/E workload 才负责攻击性分支。下表不把某个候选的显式 `unsupported` 写成
“已实现该能力”。

| # | 要演示的能力 | 具体 demo / 扩展入口 | 自动测试或冻结 workload | 可检查的输出 |
|---:|---|---|---|---|
| 1 | 输入带时间和来源的患者事实 | [`examples/01_minimal_observation.json`](examples/01_minimal_observation.json)；`python -m prototype.demo` 的 `demo_1_raw_to_distinct_coordinates` | [`tests/test_contract.py`](tests/test_contract.py)、T12、T25 | [`examples/demo_output.json`](examples/demo_output.json) `/demo_1_raw_to_distinct_coordinates/ingest`，以及各 result 的 `time_cut`/`evidence_witness` |
| 2 | 区分潜在状态、观察、推断和干预 | demo 1 的 evidence/rewrite/causal 三坐标 + demo 2 的 typed hypothesis/performed exposure | [`tests/test_kernel.py::test_explicit_routes_keep_native_states_and_capability_origins_separate`](tests/test_kernel.py)、T01、T17、T37、T49 | `demo_output.json` `/demo_1.../{evidence_coordinate,rewrite_coordinate,causal_state_coordinate}` 与 `/demo_2.../shared_artifact_ingests`；每项 `origin.subkernel` 不同 |
| 3 | 更新新证据 | `demo_3_late_evidence_and_time_cut` 让同一 late evidence 在新 knowledge cut 后可见；T32 另执行真实 correction/version update | [`tests/test_demo.py::test_late_evidence_respects_knowledge_cut_without_changing_event_time`](tests/test_demo.py)、T12、T32 | `demo_output.json` `/demo_3.../{as_known_at_09_00,as_known_at_11_00}`；isolated JSON `/runs/T32/captures` 显示 correction 前后版本 |
| 4 | 旧证据过期 | T19 的同一 artifact 在历史 cut 可见、expiry 后当前 cut 不再消费；边界还由 half-open interval 单测覆盖 | [`tests/test_redteam_contract_causal.py::test_valid_time_defaults_to_cut_and_uses_half_open_end_and_expiry`](tests/test_redteam_contract_causal.py)、T19 | isolated JSON `/runs/T19/captures` 与 `/assertions`；历史 root 保留、当前 effect 不可见。该能力不伪装成 demo 里“删除记录” |
| 5 | 药物同时修改状态/表现关系 | E01 的去甲肾上腺素 public model 明分 state drift 与即时 MAP observation channel；T17 检查双通道，E05 检查退热/抗菌药选择性 | [`tests/test_model_subkernel.py::test_all_e_panel_models_execute_against_runner_without_hidden_judging_data`](tests/test_model_subkernel.py)、T17、E01、E05 | isolated JSON `/runs/E01/captures` 中 filter/forecast/counterfactual 分开；不能只凭 [`intervention_norepinephrine_architecture_toy.json`](examples/extensions/intervention_norepinephrine_architecture_toy.json) 的 action/outcome SCM 声称双通道已完成 |
| 6 | 避免同源证据重复计数 | demo 1 的三种坐标回到同一 thermometer source；T06/T27/T34 分别攻击派生同义词、独立仪器与 fan-out/fan-in | [`tests/test_temporal_ledger.py::test_duplicate_delivery_and_three_derivations_keep_one_root`](tests/test_temporal_ledger.py)、T06、T27、T34 | `demo_output.json` 三坐标的 `evidence_witness.root_sources`；isolated assertion 的 root cardinality |
| 7 | 保留冲突和未知 | T10/T44 保留局部 conflict，T11 保留未提及，T28 保留多假说，T50 保留 masked | [`tests/test_temporal_ledger.py::test_conflict_is_local_and_plan_is_not_performed`](tests/test_temporal_ledger.py)、[`tests/test_redteam_tel.py::test_masked_payload_is_redacted_in_ingest_query_explain_and_rebuild`](tests/test_redteam_tel.py)、T10、T11、T28、T44、T50 | isolated JSON 对应 `information_state`、`coverage_status`、`diagnostics`；masked output 不含原 payload |
| 8 | 历史回放 | demo 3 给出相同 event time 的两个 knowledge cut；T23 比较 as-then/reinterpret-now，T25/T32/T40 攻击未来、修正与热缓存 | [`tests/test_temporal_ledger.py::test_future_result_is_not_visible_at_past_cut`](tests/test_temporal_ledger.py)、[`tests/test_benchmark_contract.py::WorkloadContractTests::test_clean_rebuild_is_external_replay_not_candidate_method`](tests/test_benchmark_contract.py)、T23、T25、T32、T40 | `demo_output.json` `/demo_3...`；isolated captures 中的版本、cut、root visibility 和 external rebuild call |
| 9 | 生成两个任务临时坐标 | 同一 facts/cut 上的 **`diagnosis`** 与 **`medication_safety`** 两个只读 projection；只按 semantic-role eligibility 分区，不声称临床 relevance | [`tests/test_demo.py::test_same_evidence_cut_yields_distinct_read_only_task_projections`](tests/test_demo.py)、T15 | `demo_output.json` `/demo_2_read_only_task_projections/{diagnosis,medication_safety}`，以及 `source_of_record_unchanged=true` |
| 10 | 新疾病/机制加入而不改核心 | 四个实际 checked-in typed package：[`disease_acute_kidney_injury_architecture_toy.json`](examples/extensions/disease_acute_kidney_injury_architecture_toy.json)、[`intervention_norepinephrine_architecture_toy.json`](examples/extensions/intervention_norepinephrine_architecture_toy.json)、[`task_projection_renal_safety_review.json`](examples/extensions/task_projection_renal_safety_review.json)、[`test_method_cystatin_c_architecture_toy.json`](examples/extensions/test_method_cystatin_c_architecture_toy.json) | [`tests/test_extensions.py`](tests/test_extensions.py)、T21、T22、E06 | 注册 receipt 的 `closed_ir=true`；AKI filter、norepinephrine population `do`、新增 `renal_safety_review_v1` task projection；test-method 仅匹配指定 assay，并保留 value/unit/单一 root；runtime 中 extension ID 命中数为 0。参数仅是 architecture toy，不是临床校准 |
| 11 | 每个坐标/结论输出证据血缘 | `run_demo()` 的 `_short` 保留 `evidence_witness`、origin、versions、time cut；`explain`/retraction 另有候选单测 | [`tests/test_kernel.py::test_candidate_api_clean_rebuild_and_kernel_explanation`](tests/test_kernel.py)、[`tests/test_temporal_ledger.py::test_retraction_invalidates_dependents_and_matches_clean_rebuild`](tests/test_temporal_ledger.py)、T06、T24、T34、T45 | `demo_output.json` 每个 result 的 `evidence_witness.root_sources`；isolated output 的 calls/captures/justifications 可回到 raw root 与 module/version |

扩展包的完整 blast-radius 机械证明见 [`examples/README.md`](examples/README.md)；两个
内置 task projection 与新增 `renal_safety_review_v1` 是三个不同测试点，不能把 task
extension 的注册成功误算成前两个投影的正确性。

## 11. 运行记录格式

每次运行创建不可覆盖的 `run_id`，保存：

```text
requirements version
tests version
candidate manifest hash
K_shared/K_extra/S_patch hashes
code revision
runtime/environment
seed set
raw machine results
summary generated from raw results
```

硬约束先淘汰；其余分别形成 Audit/Epistemic 和 Dynamics/Causality/Composition 两张 Pareto 表，不生成一个可掩盖硬失败的总分。

## 12. panel 运行谱系：为什么 v1–v3 中只有 panel-v3 可用于决策

三个目录都保留，且都不可覆盖；版本号表示证据有效性演进，不表示三个结果可以混在
一起累计：

| 运行 | 证据地位 | 决策使用 | 失效或保留原因 |
|---|---|---:|---|
| [`20260713T200000Z-panel-v1`](results/20260713T200000Z-panel-v1/) | 红队前 baseline | **否** | 候选与 oracle/参考实现同进程，候选可以通过 import/introspection 触达评分材料；语义资格、payload 完整性和 typed refusal 的判据也过弱。红队因此推翻该 baseline；其较高 PASS 数不能再解释为候选能力。 |
| [`20260713T115159Z-panel-v2`](results/20260713T115159Z-panel-v2/) | 隔离修复后的中间诊断 | **否** | 已做到 fresh `python -I -S`、只经 stdin 提供 `candidate_view`，但随后复核发现 T35 的数值/单位 oracle 仍需修正，而且 worker 仍可用已知绝对路径越过临时复制树读取宿主文件。即使 v2 与 v3 的聚合计数相同，v2 的隔离证明仍不成立。 |
| [`20260713T120910Z-panel-v3`](results/20260713T120910Z-panel-v3/) | 最终 isolated panel | **是** | 修正 T35，并加入 CPython audit-hook 读路径 allowlist，同时封锁 subprocess、network 与 native loader；每 workload 使用新进程，oracle 只留在 parent judge。它是 panel 谱系唯一的 decision-grade 数据；第 19 节 bridge counterevidence 是另一条证据链。 |

具体红队攻击、复现和修复状态见 [`REDTEAM.md`](REDTEAM.md)。v3 的隔离边界仍明确
限定为“受审计的纯 Python 候选”，**不是操作系统安全沙箱**。

## 13. panel-v3 的实际执行条件与完整性

- `run_id`：`20260713T120910Z-panel-v3`
- runner / benchmark：`architecture-experiment-v2` / `archbench-runner-v1.1`
- 运行环境：Windows 11，CPython 3.12.13，单 seed `1103`
- 进程协议：`vesmed-isolated-candidate/3`；每个 candidate × workload 都启动新的
  `python -I -S` 进程
- 输入隔离：candidate stdin 只有 `candidate_view`；`oracle_view` 与判定逻辑只在
  parent judge
- 矩阵：5 个 native（TEL、causal-state、rewrite/open、ClinicalKernel、model
  subkernel）+ 3 个 atomic companion（TEL、causal-state、rewrite/open）
- 工作负载：`T01–T50` + `E01–E08`，每条赛道 58 个，共 **464 个候选-工作负载
  运行**
- `runs[*].harness_errors` 聚合：**0**。这只证明本次 harness 没有运行错误；不把
  candidate 的真实 `FAIL` 或诚实拒绝改写成成功。

结果分类必须按下述三分法读，不能把分母不同的 PASS 数当总分：

- `PASS`：该 workload 的全部 hard assertions 在语义合格的结果上通过；
- `HONEST_UNSUPPORTED`：能力边界被 typed、可操作地拒绝；它不是能力通过，也不是
  静默错误；
- `FAIL`：候选给出了语义合格但违反 hard oracle 的答案，或其边界表达本身违反 hard
  oracle。

## 14. panel-v3 最终结果：综合与 T/E 分面

表中每格均为 `PASS / HONEST_UNSUPPORTED / FAIL`。综合分母为 58，T 分面为 50，
E 分面为 8；完整 axis 计数（hard / behavior / boundary / trace / numerical）保存在
[`summary.json`](results/20260713T120910Z-panel-v3/summary.json)，不在此压成一个分数。

| 候选 | 轨道 | 综合 P/HU/F | T01–T50 P/HU/F | E01–E08 P/HU/F | 真实 FAIL IDs |
|---|---|---:|---:|---:|---|
| Temporal Evidence Ledger | native | **36 / 20 / 2** | **36 / 12 / 2** | **0 / 8 / 0** | T18, T20 |
| Temporal Evidence Ledger | companion | **36 / 20 / 2** | **36 / 12 / 2** | **0 / 8 / 0** | T18, T20 |
| Dynamic causal-state | native | **3 / 53 / 2** | **3 / 45 / 2** | **0 / 8 / 0** | T18, T20 |
| Dynamic causal-state | companion | **3 / 53 / 2** | **3 / 45 / 2** | **0 / 8 / 0** | T18, T20 |
| Rewrite/open composition | native | **31 / 23 / 4** | **31 / 15 / 4** | **0 / 8 / 0** | T18, T20, T30, T45 |
| Rewrite/open composition | companion | **31 / 23 / 4** | **31 / 15 / 4** | **0 / 8 / 0** | T18, T20, T30, T45 |
| ClinicalKernel（K0 路由组合） | native | **36 / 20 / 2** | **36 / 12 / 2** | **0 / 8 / 0** | T18, T20 |
| Experimental model subkernel | native | **13 / 44 / 1** | **5 / 44 / 1** | **8 / 0 / 0** | T20 |

### 14.1 不能误读的两个结果

1. **model subkernel 对 E01–E08 是 8/8 PASS。** 这是一个重要的正结果：封闭 public
   model IR 能执行 filtering/forecasting、`see/do`、same-patient counterfactual、
   nonlinear/irregular dynamics、selective intervention、comorbidity composition、
   associativity 与 feedback well-posedness 的冻结 oracle。它不证明 model
   subkernel 能承担 TEL 的审计/历史语义，也不构成临床校准。
2. TEL、causal-state、rewrite/open 与 K0 kernel 在 E01–E08 都是 8 个
   `HONEST_UNSUPPORTED`，而不是 8 个 PASS 或 8 个 FAIL。这正是需要异质 model
   subkernel 的证据；不能用一个原子家族冒充全套动态/因果计算核心。

### 14.2 为什么 native 与 companion 聚合结果完全相同

“完全相同”只指本次 hard verdict 计数，**不代表 companion 无成本**：

- TEL 与 rewrite/open 的当前 companion manifest 仍为空，native/companion 的 58 条
  call transcript 也逐字相同；因此这两组只是“没有实际新增伴随层”的负消融，不是
  一个免费增强的成功实验。
- causal-state companion 加入 `append-only transaction-cut adapter`；47/58 个 call
  transcript 因 capability/transaction-cut 元数据而不同，但没有任何 workload 的最终
  classification 改变。
- 本轮没有测 wall time、peak memory、迁移、运维、缓存失效和长期维护成本。因此能说的
  只有“在当前 58 条 hard verdict 上未观察到增益”，不能说“伴随层无成本”，也不能因
  聚合计数相同推断内部语义完全相同。

## 15. panel-v3 的真实 FAIL 解释

这些 ID 来自 raw `runs[*].verdict.classification == "FAIL"`，不是 harness exception：

| Workload | 受影响候选 | 决定性失败 |
|---|---|---|
| T18 | TEL、causal-state、rewrite/open、ClinicalKernel；model 通过 | 请求 `identification_status` 时，前四者返回 typed `unsupported`，但 `identification=not_applicable`；hard oracle 要求显式 `not_identified` 或 typed `insufficient`，所以“拒绝了查询”仍不足以证明没有虚构可识别性。 |
| T20 | **全部五个候选** | OOD/coverage oracle 要求 `coverage_status=out_of_model`；实际结果是 `not_evaluated` 或 `partial`（有的同时为 unsupported/insufficient）。这是边界表达失败，不能因拒绝可操作而降格成 HU。 |
| T30 | rewrite/open | 两套词汇同构的输入均保持 live root，但 canonical result digest 不等，语言无关语义同构失败。 |
| T45 | rewrite/open | raw root trace 本身通过，但 `raw_value` 与 `span` 没有在可审计输出中 round-trip，完整原始字段血缘失败。 |

E01–E08 没有 `FAIL`；model 是 8 PASS，其余四个组合/原子候选是诚实不支持。以上 FAIL
在决策中保留，没有通过改 oracle、删除 evidence 或把拒绝自动算 PASS 来消除。

## 16. 规模、原语、反特例扫描与扩展 blast radius

静态快照来自 [`results/metrics-final.json`](results/metrics-final.json)。LOC 只描述本次
实现，不作为跨语义家族的优劣分数；原语数是 manifest 的 unique leaf string 口径。

| 候选实现文件 | physical LOC | nonblank/noncomment LOC | manifest unique primitives | static special-case indicators |
|---|---:|---:|---:|---:|
| `causal_state.py` | 2,244 | 2,080 | 8 | **0** |
| `kernel.py` | 780 | 694 | 7 | **0** |
| `model_subkernel.py` | 1,312 | 1,202 | 7 | **0** |
| `rewrite_open.py` | 3,308 | 3,013 | 29 | **0** |
| `temporal_ledger.py` | 2,167 | 1,996 | 20 | **0** |

五个文件的 literal Txx/Exx ID、test/oracle identity dispatch、benchmark/workload/reference
import 和汇总 static special-case indicator 均为 **0**。这是排除已知“按测试号答题”机制
的静态下界，不是对所有领域过拟合的数学证明；后者仍需要 holdout。

四个已签入 typed extension package 的可执行实验得到：

- new disease：`disease_acute_kidney_injury_architecture_toy.json`
- new drug/intervention：`intervention_norepinephrine_architecture_toy.json`
- new task projection：`task_projection_renal_safety_review.json`
- new test method：`test_method_cystatin_c_architecture_toy.json`
- 运行时注册期间 7 个 fixed-core 文件无需改动；旧 answer/disease coordinate 的语义
  delta 为 0，且四个 extension ID 在 runtime 源码中的命中数为 0
- 四个 extension `module_id` 在 `prototype/**/*.py` 的命中数均为 0；没有新增
  extension-specific runtime branch
- 公开注册 API 全部成功；注册前旧 evidence answer 的 status/claim/value/root/time
  cut 语义 delta 为 0，注册 drug 后旧 disease coordinate 的语义 delta 也为 0

这里的“registration-time core blast=0”不等于系统任何字节都不变：module registry 的
`versions.modules` 必须诚实增加版本项，extension 文件本身也当然是新增 authoring
artifact。机械测试见 [`tests/test_extensions.py`](tests/test_extensions.py)。
[`metrics-current.json`](results/metrics-current.json) 已含前三个扩展，所以它们没有
authoring 前静态快照；最终新增的 test-method 包有 before/after，
[`results/metrics-final-vs-current.json`](results/metrics-final-vs-current.json) 记录
knowledge-extension 新增 1、fixed-core added/modified/removed 均为 0，同时把 5 个 harness
文件修改单独记账。

## 17. 本轮没有测量、因而不能主张的指标

1. **性能**：没有正式测 latency、throughput、wall time 分布、peak memory、并发、
   大规模记录/模块下的复杂度拐点，也没有比较 companion 的运行成本。
2. **第二台机器复现**：最终 panel 只在 metadata 所列 Windows/CPython 环境执行；没有
   第二台机器、第二个 OS 或独立团队复跑。
3. **完整隐藏 holdout**：2026-07-14 已完成 candidate seal→fresh seed→corpus reveal，并执行
   首轮 A/B runner；但 corpus 只有 4 个 concrete base、35 个 descriptor-only case；H09/H20/H21
   含 dangling query refs，其中 H09 与 descriptor-only 集合重叠。A 为 `0 PASS / 4 ADAPTER_UNREPRESENTABLE / 37 HARNESS_INCOMPLETE`，B 为
   `0 PASS / 41 HARNESS_INCOMPLETE`。因此整体仍是 `HARNESS_INCOMPLETE`；post-seal probe 和
   static special=0 都不能替代完整 blinded executable holdout。
4. **临床有效性**：58 条都是 synthetic architecture-semantics workload。没有验证
   临床诊断准确率、校准、治疗效益、患者结局、外部效度或 active atlas 的医学质量。
5. **随机鲁棒性**：metadata 只有 seed `1103`；当前受测实现是确定性的，故足以重放
   本轮结果，但不能外推到未来随机 particle/filter/optimizer 的多 seed 校准。

因此 panel-v3 支持的是“固定控制面 + 异质语义子核”的架构选择证据，不是临床部署
许可，也不是全局最优性证明。

## 18. 可复现命令、raw 路径与 hash 锚点

### 18.1 重跑

归档 run id 不允许覆盖。以下命令用一个新 ID 重跑同一当前协议；要核对 v3，应比较
各 panel 的 classification/axis summary 与 metadata 内嵌 hash，而不是强行复用旧目录：

```powershell
$PY = 'C:\Users\wangw\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

& $PY -m prototype.experiment `
  --output-root results `
  --run-id '<NEW_UTC_RUN_ID>-panel-v3-repro' `
  --candidate tel --candidate causal --candidate rewrite --candidate kernel --candidate model `
  --track native --track companion `
  --panel T --panel E `
  --timeout 30

& $PY -m prototype.metrics --output 'results/metrics-repro.json'
& $PY -m pytest tests/test_extensions.py -q

Get-FileHash -Algorithm SHA256 `
  results/20260713T120910Z-panel-v3/metadata.json, `
  results/20260713T120910Z-panel-v3/summary.json, `
  results/metrics-final.json
```

默认是 isolated 模式；`--in-process` 只允许做诊断，不能生成决策证据。完整 raw 输出是
8 个 `*-native.json` / `*-companion.json` 文件，每个文件保留 58 条 runs、calls、captures、
assertions、typed result 与 verdict。

### 18.2 决策所用的 hash

下列 digest 直接来自
[`metadata.json#/hashes`](results/20260713T120910Z-panel-v3/metadata.json)；该文件还保存
全部 58 个逐 workload candidate/oracle view hash：

| 对象 | SHA-256 |
|---|---|
| requirements | `f5694f36177d0403f2516c3c80977957b94115ff67f5575297356134d4bfac46` |
| formal spec | `cc212675793276f734cc611d122984cd0b263fb79a3bd0d742a963b798de9e39` |
| benchmark code | `8f09db4022bb1e2a74991c598d0a344aa7212ddcc2f61db1a2f45fe6dd8e7c4b` |
| workload files | `6cb8ac4557709b6a052b4940563ef82879f832a5bea8cdccd65ac7c2a4e1a878` |
| selected candidate views | `bb1492c75c01201dd47632d829478187dc7ef9295239b87278acde92e730ea83` |
| selected oracle views | `5397a1cffdd12fa29c24d7f3b625abeaa5ce9f3731e0f61c491537031cf2ec67` |
| TEL code bundle | `76066d950bd6972ea09b9c5f25248c505f3f164f34bf9ea61b426c121bf59038` |
| causal-state code bundle | `32cf8c04596304f5c5785317eac642ba06bbfb352469703b2e617237ac86f018` |
| rewrite/open code bundle | `7cefc3b9c30beae0a29e9bfc164dfb8ce72b4a95cceaf8f7594f6b09a355b11d` |
| ClinicalKernel code bundle | `ae466248dff8b8ae4a1e59f21c9d004ca579c167d707d343ea1729bd46750270` |
| model subkernel code bundle | `2fbe1ccb34b58330131b0a63f664487c352201e65038283b01a5ecd0e7a3ca70` |

关键归档文件的实际 file hash：

| 文件 | SHA-256 |
|---|---|
| `panel-v3/metadata.json` | `b9c9b650162d91d44cf99610355741bef8377732a0cbed7ef2a12aff7f0a1abc` |
| `panel-v3/summary.json` | `d2617444b58fe4441a740c15b5efd9fb720dfe9e6d883adf7339b971747847e3` |
| `results/metrics-final.json` | `fef8c5c17411f3b4e6fc035d422ec37c653041a9f3f6b90cca4d20813ed16581` |
| `results/metrics-final-vs-current.json` | `9412b3b253a3f7d54eb2adea993e14c00f350a7ddddc1e828c5992a223cefd5c` |

`metrics-final.json` 内部另有去掉时间戳与自 hash 字段后计算的稳定 snapshot digest
`8ff17a7aebd57cbcd060d3262318ace02c7b70273db7b1101bcc0ae1e64165cf`；差分报告的稳定
digest 为 `701bf2048bd02d2199997c2b005b8a9e0b2cb5f5fd1c6c9965f0f03c3720de09`。它们与整个
JSON 文件的 byte hash 不是同一口径。

本次 metadata 记录的 Git commit 是 `13c31d22f14904b2cd50a9e913dedbf60a1138c2`，但
`dirty=true`，并保存
`status_digest=sha256:db584798f4e654534c7dad4abdee5ef47d786dad6916dcbfbcedd459fe71e9ad`。
所以仅 checkout 该 commit **不能**宣称字节级复现；必须同时核对上表的代码、workload、
view 与 raw 文件 hashes。这一限制保留在记录中，不用 commit 标签掩盖。

## 19. Bridge round-trip 执行轮（2026-07-14）

本轮按 [`tests/bridge_holdout/PREREGISTRATION.md`](tests/bridge_holdout/PREREGISTRATION.md)
冻结 A/B bridge 和 A/B public panel，之后 reveal 新 seed/corpus。最终裁决不是一个总分：

- 冻结实现层：**`HYPOTHESIS_FAIL`**；A/B 均存在非补偿 hard failure，M01 均未杀死；
- sealed 41-case corpus 层：**`HARNESS_INCOMPLETE`**；H01–H30 是原预注册集，H31–H41 是 post-seal/pre-execution 静态审计 addendum，41 个描述不等于 41 个 executable fixtures；
- public E01–E06 与基础 finite DBN/SCM 数值成功只证明 solver/core liveness，不能补偿
  raw/root/cut/version/uncertainty/recovery failure；
- synthetic 12-mutant self-test 只证明外部 judge predicate，不能冒充 candidate kill matrix。

四个冻结源码合计 `244,694 bytes / 5,609 physical lines / 4,768 strict LOC`；两个 runner
合计 `132,402 / 2,727 / 2,454`。`eca17d3..abac087` 只新增 32 个实验文件，core runtime
修改 0、schema migration 0。A 无 latency telemetry；B 只有 4/4/7 个 compile/recover/run
样本，报告明确不支持 stable p95。

原始 A/B/redteam、hash、机器摘要、完整结论和重放命令见
[`results/bridge-holdout/REPORT.md`](results/bridge-holdout/REPORT.md)。B 的 run-02/run-03 已保留，
但最早未提交 dry-run 只剩 SHA、bytes 已丢失；本轮不能声称完整 WORM 历史。
