# Runtime v2.1 hard-gate audit (case-blind)

审计时间：`2026-07-20T19:08:25+09:00`  
绑定 runtime source tree：`496548b9d0401978917978030f8710dd195e814ab0968a278b8e05c1444d8c79`（sorted relative-path -> file-SHA256 canonical JSON）

## Outcome

**最新 delta reaudit 中，先前 5 个 runtime-owned hard gaps 已全部关闭，40/40 自测和 5 组独立负向/正向 probes 均通过。** 严格区分 runtime capability 与尚未执行的 primary-case gate 后，30-gate 当前结果为：

- `PASS`: **22**
- `FAIL`: **1**
- `EVIDENCE_MISSING`: **6**
- `NOT_EXECUTED`: **1**

因此 **runtime source delta = READY**，但冻结 gate set 仍是 **CONTRACT_BLOCKED / NO-SEAL**：唯一现存 FAIL 是 `PL-ACT-002` 的 gate-contract enum 与 architecture 不一致，不是 runtime-source 实现缺口。若现在机械聚合，primary blind/case evidence 尚不存在，外层 verdict 仍是 **HARNESS_INCOMPLETE**。

本审计没有读取 primary holdout selection、真实病例内容、病例 ledger 或 holdout/generic model；只执行了允许的 `PROCESS_A/B/C` neutral fixture。该 auditor 也不承担未来 primary final-case audit。

`holdout/tools/` 不在读取白名单内，其中任何 structural harness 声称均未被读取或采信。本轮 PASS 只基于 `runtime_v2` source/tests 与独立 neutral probes。

## Key Evidence

### 1. 唯一现存硬失败：gate-contract mismatch

1. **PL-ACT-002 仍无法精确机器 conformance。** architecture wire 使用 `IDENTIFIED_WITHIN_SCOPE / PARTIALLY_IDENTIFIED / UNIDENTIFIABLE / OUT_OF_SCOPE`（`architecture_final_v1.schema.json:1542-1545`），冻结 gate JSON 仍枚举 `IDENTIFIED / PARTIALLY_IDENTIFIED / UNIDENTIFIABLE`（`holdout/PERFECT_LANDING_GATES.json:49-53`）。Runtime 保持 architecture-correct；须由 gate owner 版本化并重新 seal contract。

### 2. 本轮独立关闭的 5 个 runtime-owned gaps

- **PL-LED-001 runtime capability PASS**：缺 provenance、occurred/sample/result/recorded/available time、非法时序、未知 event type、无 action_id 的 planned action 共 9 组输入全部 fail closed。
- **PL-STATE-001 PASS**：enabled、topology-off、guard-off 得到 3 个不同 `model_digest`；跨 switch 查询均拒绝，要求显式 migration。
- **PL-PRED-002 runtime capability PASS**：full realization 为 `12/12 SUPPORTED`；empty `0/12`、partial `1/12` 和越界坐标均为 `ZERO_OR_UNDEFINED_SUPPORT` 并列出缺失/零支持 component IDs。实际 case gate 因无 primary realized cuts 与 baseline comparison，仍记 `EVIDENCE_MISSING`。
- **PL-OOD-001 PASS**：same-batch 与 sequential 独立相反 measurement 均生成 `conflicting_measurements`，`model_misfit` 从 `0.05` 升至 `0.523684`。
- **PL-CASE-001 runtime disposition PASS**：`rankable=false` observation 与 `RecordOnly` 都产生 provenance-bound、reliability `0` 的 `DISPOSITION:record_only_nonrankable` measurement，并进入 recognized results。

### 3. 已经证明可执行的其他关键能力

- canonical wire 可通过 `architecture_final_v1.schema.json`，state hash 可重导。
- content-addressed ledger proof 支持跨进程 exact-once；fresh parent+delta 的 child bytes 与 heads 完全一致。
- same-source 的新 event ID / 不同 child factor 不再增加 certainty，且 canonical bytes 不变。
- factorial concurrency、local coordinates/modes、mode guard+hysteresis、support lifecycle、topology ablation、OOD unknown perturbation、migration 均有通过的 neutral witness。
- collision detector 与 planner 已接通：未提供 witness 时 toy identified action 可选；提供 opposite-response witness 后 `selected_policy_id=null` 且输出 `UNIDENTIFIABLE`。
- refinement 现在在 migration 前后冻结并重跑 `diagnose`、natural forecast、全部 unaffected single-action rollout 与 restricted plan，以 `abs_tol=1e-12` 比较；独立注入 `1e-6` forecast 偏差时 fail closed。
- 12-process boundary：8192 joint hypotheses，独立测得 initialize `1.179916s`、forecast `0.296644s`、wire `2,001,540` bytes、Python peak allocation `12,952,334` bytes。

## 30-gate result matrix

| Gate | Facet | Result | Decisive code-only reason |
|---|---|---|---|
| `PL-IND-001` | `structure` | **EVIDENCE_MISSING** | Static AST scan found only stdlib/local runtime imports, but no approved_asset_manifest plus full primary replay runtime trace exists. |
| `PL-BLIND-001` | `harness_integrity` | **EVIDENCE_MISSING** | Gate/architecture hashes match the seal, but primary holdout access lineage does not yet exist; this auditor is explicitly not the primary final-case auditor. |
| `PL-LED-001` | `case_representation` | **PASS** | Provenance and explicit partial-order times are required; invalid order, unknown type and untyped plan inputs fail closed. |
| `PL-LED-002` | `structure` | **PASS** | 40-test suite plus independent two-process replay verified exact canonical child bytes and query outputs with the content-addressed ledger proof; same-source alternate event IDs are byte-identical no-ops. |
| `PL-STATE-001` | `structure` | **PASS** | Runtime switches enter the model digest; cross-switch states are rejected and require explicit migration. |
| `PL-STATE-002` | `structure` | **PASS** | Neutral states pass the frozen architecture schema; rehashed cross_coupling/geometry edits fail closed, while history/factor/action/epistemic fields are reconstructed and consumed by updates or heads. |
| `PL-TIME-001` | `time_integrity` | **PASS** | Availability filtering is applied before consumption and the future-event invariant test passes. |
| `PL-TIME-002` | `time_integrity` | **PASS** | Plan-only, performed, hold/resume/complete, stop, dose and washout paths are distinct and availability filtered. |
| `PL-FACT-001` | `factor_graph` | **PASS** | Registered emissions have typed active/inactive likelihoods; reliable negative evidence produces signed refutation. |
| `PL-FACT-002` | `factor_graph` | **PASS** | Same source is the common-parent evidence unit; exact clones and different child factors with the same source do not change bytes or certainty. |
| `PL-CONC-001` | `concurrent_processes` | **PASS** | Exact factorial joint supports simultaneous high nonexclusive process marginals; 12-process boundary produces 8192 hypotheses. |
| `PL-CONC-002` | `concurrent_processes` | **PASS** | Process marginals persist independently under process-local evidence; no disease simplex renormalization is applied. |
| `PL-MODE-001` | `local_modes` | **PASS** | Per-process local modes and declared process/mode couplings affect forward dynamics. |
| `PL-MODE-002` | `local_modes` | **PASS** | Same-coordinate mode drift, explicit guards, separated enter/exit thresholds and hysteresis ablation are executable. |
| `PL-SUPPORT-001` | `action_counterfactual` | **PASS** | Action memory/support dependence and lifecycle-specific rollout distinguish supported from unsupported twins. |
| `PL-GEOM-001` | `structure` | **PASS** | Topology changes inference and planning in registered ablations and emits effect traces. |
| `PL-DX-001` | `diagnosis` | **EVIDENCE_MISSING** | Neutral directional likelihood behavior exists, but no primary holdout cut trace, sealed assertions or label-leak evidence exists yet. |
| `PL-DX-002` | `diagnosis` | **EVIDENCE_MISSING** | Requires decisive-cut clinical localization on the future primary holdout; intentionally not executed. |
| `PL-PRED-001` | `prediction` | **EVIDENCE_MISSING** | Runtime forecast uses the shared rollout core, but no primary cut-by-cut pre-next-cut forecast seals exist. |
| `PL-PRED-002` | `prediction` | **EVIDENCE_MISSING** | Runtime support/scorer capability passes and fails closed on missing/partial/out-of-bounds realization; primary realized cuts and frozen baseline comparison have not been executed. |
| `PL-ACT-001` | `action_counterfactual` | **PASS** | Lifecycle policies and factual updates are distinct; counterfactual calls are pure. |
| `PL-ACT-002` | `action_counterfactual` | **FAIL** | Runtime follows architecture enum IDENTIFIED_WITHIN_SCOPE/PARTIALLY_IDENTIFIED/UNIDENTIFIABLE/OUT_OF_SCOPE and excludes unresolved-collision policies, but frozen gate JSON enumerates IDENTIFIED and omits IDENTIFIED_WITHIN_SCOPE/OUT_OF_SCOPE. Exact machine conformance is impossible. |
| `PL-OOD-001` | `open_world_refinement` | **PASS** | Same-batch and sequential opposite independent measurements raise model_misfit and emit conflicting_measurements residuals. |
| `PL-OOD-002` | `open_world_refinement` | **PASS** | Unknown-process perturbation raises unmodeled/mapping residuals and exposes partial-answer abstention instead of a single forced class. |
| `PL-REF-001` | `open_world_refinement` | **PASS** | Production collision detector finds opposite-response same-state worlds; supplying the witness to plan blocks an otherwise selectable identified action. |
| `PL-REF-002` | `open_world_refinement` | **PASS** | No-separator path returns typed UNIDENTIFIABLE and collision-aware plan excludes the action. |
| `PL-REF-003` | `open_world_refinement` | **PASS** | Separating event creates a local stratum split, applies only after availability, and migrates with explicit lineage. |
| `PL-REF-004` | `open_world_refinement` | **PASS** | `execute_local_refinement` freezes and reruns diagnosis, natural forecast, every unaffected action rollout and restricted plan at `abs_tol=1e-12`; the report binds per-query before/after hashes and a synthetic `1e-6` post-migration drift fails closed. |
| `PL-CASE-001` | `case_representation` | **PASS** | rankable=false and RecordOnly events emit explicit neutral record_only_nonrankable disposition factors with provenance and recognized-result coverage. |
| `PL-REPORT-001` | `reporting` | **NOT_EXECUTED** | No primary perfect_landing_results/report exists; this case-blind runtime audit must not substitute for it. |

## Verification

```text
python -m unittest discover -s runtime_v2/tests -v
Ran 40 tests in 1.592s
OK
```

独立 probes：

```text
fresh-process replay: bytes_equal=true, queries_equal=true
12-process: hypotheses=8192, init=1.179916s, forecast=0.296644s
event contract: malformed/unknown/untyped matrix rejected=9/9
runtime switches: unique digests=3, cross-switch rejected=true
predictive support: full=SUPPORTED; empty/partial/outside=ZERO_OR_UNDEFINED_SUPPORT
collision-aware planner: selected action -> null, status=UNIDENTIFIABLE
conflict residual: batch+sequential model_misfit 0.05 -> 0.523684
record-only disposition: 2 events -> 2 neutral DISPOSITION factors, both recognized
refinement non-regression: query corpus PASS; injected 1e-6 forecast drift -> AssertionError
```

冻结输入 hash：

```text
ARCHITECTURE_FINAL_v1.md          d83b910f3cd32c777f126b245c2652e88fccb31aaa125b455f4c5af90cc4575c
architecture_final_v1.schema.json 9804d21e8032f571b6cfd414c08b31891eab8856bc0502e0000df4b7d53f80d1
PERFECT_LANDING_GATES.json         a00b963fd090d4accb304b343075661a5bfd6ecf2fc8371843a0a974e9fe3798
PERFECT_LANDING_GATES.md           8d32096bd12b5e11b850776cff152d0acd54304e430a4dfd258eda6aeea84935
runtime source tree                496548b9d0401978917978030f8710dd195e814ab0968a278b8e05c1444d8c79
runtime_v2/engine.py               ad8a8116e3ee2d81c66c7c7a76a7b0cbd1fb6cad6d0a5b010743aa6d07f70a1c
runtime_v2/schema.py               b2a1aeb5942edb9cb03ac97baa89deb7ebe4b68099f20bc07391a2aa18694de6
runtime_v2/architecture_wire.py    71f760f56a5a9f8f49f0f695601c991e4ccd61de40b4cfcaa1e434fa071fb29e
runtime_v2/refinement.py           33639d1fbc12e1872651c45e2789c9979c09000fc68f3f60f7b6aaef9e539eec
runtime_v2/schemas/event_v2.schema.json fed62dd4ac5a3cb3d633ed529d56c884ce7b51f82546e2a6d5895ae251791624
runtime_v2/tests/test_runtime_v2.py d3d077a32e012367c8b1df3463a70b8a4c6b21175bd76e0ef6122b60b6b202d3
```

机器结果：`runtime_v2/RUNTIME_GATE_GAPS.json`。

## Next Step

1. Gate owner 版本化并重新 seal identifiability enum，使 `PL-ACT-002` 与 architecture wire 一致。
2. 在该 contract 修复和最终 source hash freeze 后，由新的 primary blind evaluator 生成依赖 trace、cut seals、实际 PL-PRED-002 score/baseline、临床审查和最终 report。

Runtime source delta 当前可以 seal；完整 gate set 在 contract 修复前仍为 **NO-SEAL**，且不得把 neutral probes 表述为 `PERFECT_LANDING_WITHIN_FROZEN_CASE_SCOPE`。
