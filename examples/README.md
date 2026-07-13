# 五个可复查示例

这些示例不是临床病例诊断，而是最小架构语义演示。运行：

```powershell
python -m prototype.demo > examples/demo_output.json
```

## 1. 原始事实到临时坐标

[`01_minimal_observation.json`](01_minimal_observation.json) 是一条体温观察：

- `raw_observation`，不是隐藏炎症状态；
- 有独立 `artifact_id` 和 `source_id`；
- 有发生/采集/可见/记录时间；
- 带单位、subject/encounter scope 和可往返的原文。

演示分别查询：

- TEL 的 `fever` evidence coordinate；
- rewrite 的 `rewrite_fever` coordinate；
- finite DBN 的 `inflammation::I` posterior coordinate。

三个结果共享可追踪的 root，但 `capability_origin` 不同。它们不是一个被重复命名的 `PatientState`。

## 2. 同一事实层的两种只读 task projection

`demo_2_read_only_task_projections` 在**同一个 kernel、同一组 artifacts、同一 target、同一 subject、同一 `valid_at` 与同一 `as_known_at`** 上运行两个查询；除 `query_id` 外，唯一的语义差异是：

- `task="diagnosis"`：可见 `hypothesis`、观察、确定性派生和已实施事件；
- `task="medication_safety"`：可见观察、确定性派生和已实施事件，但排除 `hypothesis`。

示例中的 `candidate-H` 与 `exposure-X` 都是 opaque token，只用于证明 semantic-role partition；**不表示诊断成立、药物适用、治疗有效或存在因果关系**。这里验证的是 role eligibility，不是临床 relevance classifier。两个 projection 都是 read model；`source_of_record_unchanged=true` 证明查询前后的 audit projection 相同。

应检查：

- 两个结果的 `claim_partition.semantic_roles` 确实不同；
- 两边共同保留同一个 `temperature` root 和 `recorded_exposure`；
- `hypothesis` 只出现在 diagnosis projection；
- 两边 `origin.subkernel` 都是 `evidence`，没有伪装成统一 `PatientState`。

## 3. Late evidence 与双时间 cut

`demo_3_late_evidence_and_time_cut` 中，`late-measurement-record` 的事件时间是 `08:15`，但直到 `10:00` 才 `available/recorded`：

- `as_known_at=09:00` 返回 typed `insufficient`，不能偷看未来记录；
- `as_known_at=11:00` 返回 `ok`，并把该 source 放进 provenance；
- 两次查询的 `valid_at` 都是 `08:30`，因此差异来自 knowledge cut，而不是改写 event time。

这演示的是 bitemporal visibility，不是对迟到信息作任何临床解释。

## 4. 局部扩展

[`02_extension_module.json`](02_extension_module.json) 增加一个版本化的封闭规则：有根 `fever` 推导出 `needs_clinician_review`。新增模块不修改 `contract.py`、`kernel.py` 或候选解释器的核心分支。

这个例子证明的是“模块注册路径局部”，不证明任意新疾病知识都必然正确。真实扩展仍需医学证据、适用域、横向公平审查和回归。

## 5. 明确拒绝

[`03_refusal_query.json`](03_refusal_query.json) 请求 finite DBN 回答同一患者 counterfactual。DBN 只定义 transition/observation/filter/forecast，没有 SCM 的共享外生背景，因此必须返回 typed `unsupported`；系统不能把 forecast 或 population intervention 改名为个体反事实。

## 输出审计点

在 `demo_output.json` 中检查：

- `status/capability`；
- `origin`：真正执行的 subkernel；
- `versions`：kernel、module、bridge/model 版本；
- `time_cut`：`as_known_at` 与 `valid_at` 不混用；
- `evidence_witness.root_sources`；
- refusal 的 `diagnostics`，不能只有空值或伪 `OK`。

## 6. 四类可执行扩展包与 blast radius

`examples/extensions/` 下的四个文件本身就是封闭、可注册的 typed module
payload；测试通过唯一公开入口 `ClinicalKernel.register_module(payload)` 加载，
没有专用 loader、callback、字符串求值或 extension-id 分支：

| 扩展包 | 原生语义/公开路径 | 可直接计数的 authoring footprint | 新增行为 |
|---|---|---:|---|
| [`disease_acute_kidney_injury_architecture_toy.json`](extensions/disease_acute_kidney_injury_architecture_toy.json) | finite DBN / causal-state module | 2 variables，3 probability blocks | 新增显式 `module::AKI` filter 坐标 |
| [`intervention_norepinephrine_architecture_toy.json`](extensions/intervention_norepinephrine_architecture_toy.json) | finite SCM / causal-state module | 3 variables，2 equations | 新增显式 `do(NOREPINEPHRINE=...)` population intervention |
| [`task_projection_renal_safety_review.json`](extensions/task_projection_renal_safety_review.json) | temporal evidence / task projection | 1 projection | 新增 `renal_safety_review_v1` 封闭投影 |
| [`test_method_cystatin_c_architecture_toy.json`](extensions/test_method_cystatin_c_architecture_toy.json) | temporal evidence / closed derivation rule | 1 method-qualified rule | 仅匹配指定 assay；保留 value、unit 与单一 source root |

这些数值只是**解释器与扩展边界测试参数**，不构成临床校准、治疗效果主张，
也不进入 active disease atlas。它们刻意使用 generic observation concepts，
避免把疾病身份编码进普通观察轴。

[`tests/test_extensions.py`](../tests/test_extensions.py) 对 blast radius 做机械验证：

1. 四个 payload 均经同一个公开注册 API 成功进入正确 subkernel；
2. 注册前已有 evidence answer 的 status、claim、value、root 和 time cut 改变量为
   **0**；注册 drug module 后旧 disease coordinate 的语义改变量也为 **0**；
3. `prototype/**/*.py` 中四个 extension `module_id` 命中数为 **0**，即没有
   extension-specific runtime 分支；
4. test-method rule 只消费匹配 method 的测量，且派生值保持原 value、unit 与一个 root；
5. 注册 task module 后 `versions.modules` 会诚实增加一个版本项。这是 registry
   provenance 的预期变化，不伪装成“字节级完全没变”。

复核：

```powershell
python -m pytest tests/test_extensions.py -q
```

回归测试位于 [`../tests/test_demo.py`](../tests/test_demo.py)，覆盖 projection role partition、read-only 不变性、late-evidence cut 与 typed refusal。

## 7. 11 项原型要求的阅读索引

完整的 demo→test→workload→output 对照见
[`../EXPERIMENTS.md` 的 10.1 节](../EXPERIMENTS.md)。本目录内可先按下表定位；没有塞进
`demo_output.json` 的攻击性分支，必须看 frozen workload 的 isolated capture，不能靠示例
文字宣称通过。

| 原型要求 | 本目录入口 | 对应攻击测试 |
|---|---|---|
| 带时间/来源的事实 | `01_minimal_observation.json`、`demo_1.../ingest` | T12、T25 |
| 状态/观察/推断/干预分离 | `demo_1...` 三个 native coordinate；`demo_2.../shared_artifact_ingests` | T01、T17、T37、T49 |
| 新证据更新 | `demo_3...` 的两个 knowledge cut | T12、T32 |
| 旧证据过期 | 不在 happy-path demo 中伪装；运行 T19 | T19 |
| 药物改变 state/observation relation | E01 public model；本目录 norepinephrine package 只证明 closed SCM extension | T17、E01、E05 |
| 同源去重 | `demo_1...` 三坐标的共同 root | T06、T27、T34 |
| 冲突和未知 | 由隔离 workload 输出 typed state | T10、T11、T28、T44、T50 |
| 历史回放 | `demo_3...` 的 bitemporal read；完整修正/缓存攻击在 panel | T23、T25、T32、T40 |
| 两个任务坐标 | `demo_2.../diagnosis` 与 `demo_2.../medication_safety` | T15 |
| 新疾病/机制/任务/检查方法不改核心 | `extensions/disease_...json`、`extensions/intervention_...json`、`extensions/task_...json`、`extensions/test_method_...json` | T21、T22、E06 与 `test_extensions.py` |
| 坐标/结论血缘 | `demo_output.json` 每个短结果的 `evidence_witness` | T06、T24、T34、T45 |

特别区分两个概念：demo 自带的 **diagnosis / medication_safety** 是验证同一事实层上的
两种只读投影；`task_projection_renal_safety_review.json` 则验证新增一个 task projection
包的局部扩展路径。后者注册成功不能替代前者的 read-only/role-partition 断言。
