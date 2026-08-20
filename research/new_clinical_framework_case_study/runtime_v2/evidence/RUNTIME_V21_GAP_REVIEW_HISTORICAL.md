# Runtime v2.1 case-blind gap review

## Outcome

**当前 runtime 是显著加强后的结构候选，但还不能做 final seal。**

- 独立复跑：`36/36` runtime tests PASS；`6/6` fresh/cold ledger replay PASS。
- 12 个并发 process：`8192` 个联合假说，初始化约 `1.64 s`，canonical state 约 `2.00 MB`，峰值追踪内存约 `12.95 MB`。
- mode guard/hysteresis、geometry、action lifecycle、动态 OOD、response memory、collision→planner、local refinement→action dynamics 均已有可执行证据。
- 当前 manifest/seal 全部过期；完整 wire field-consumption 证据和完整 refinement non-regression corpus 仍缺失。
- 本审计没有读取任何临床病例，因此**没有回答复杂真实病例能否正确定位、更新、预测或选择动作**。

按 runtime gap review：`EVIDENCE_INCOMPLETE_NOT_READY_FOR_FINAL_SEAL`。按 30-gate contract 的聚合优先级，如果现在强行汇总，则因 blind/case/report artifacts 未齐而是 `HARNESS_INCOMPLETE`。本轮 neutral-runtime 独立 probe 未留下结构 hard fail。

## Bound snapshot

```text
architecture: d83b910f3cd32c777f126b245c2652e88fccb31aaa125b455f4c5af90cc4575c
wire schema:  9804d21e8032f571b6cfd414c08b31891eab8856bc0502e0000df4b7d53f80d1
gate contract:a00b963fd090d4accb304b343075661a5bfd6ecf2fc8371843a0a974e9fe3798
runtime source:62a8338252de29e36d3d3c112f852e57b490e99e9cc985f376ea11e45deac7f4
```

Runtime source hash preimage：排除 `evidence/**`、`__pycache__/**` 和本审计报告后，对 20 个 runtime 文件按 `path\0file_sha256\0byte_count` 排序连接再 SHA-256。

## Decisive evidence

### 已修复并独立确认

1. **canonical wire 是 query authority**：给 `_internal_payload` 注入恶意 cache，不改变 forecast。
2. **common-source cross-factor 去重**：不同 factor、相同 `source_result_id` 不再重复提高后验。
3. **mode guard + hysteresis**：同坐标不同 mode 可产生相反方向；guard 开关和 hysteresis hold 均有测试。
4. **geometry 真正介入**：禁用 topology 会改变 inference 与 plan selection。
5. **action response memory**：动作后的 coordinate 观察生成 response window/summary，且只标 `descriptive_only`。
6. **dynamic OOD**：unmapped evidence 提高 `unmodeled_process`、`mapping_gap`、`scope_gap`，诊断输出 `partial_answer_only`。
7. **collision 接入 planner**：同旧状态、同新动作、相反响应的 witness 使原本会被选中的 `ACT` 被排除。
8. **local refinement 接入动作动力学**：正/负 separator 形成相反 stratum posterior，同一动作出现相反 effect direction。

### 原 `PL-LED-002` 缺口已修复

构造两个等价 observation：

```text
same factor_id
same source_result_id
same value
different event_id
```

按 gate 规定的“先 ingest，再 re-ingest 等价 rendering”顺序，结果：

```text
canonical bytes equal:true
processed ids before: ["one"]
processed ids after:  ["one"]
```

当前实现会在 ledger commit 前识别等价 same-source rendering，并直接作为 canonical no-op，不再写入 event lineage。独立 probe 与新增 unit test 一致，因此 `PL-LED-002` PASS。

### 两项仍是证据缺口，不是已证明的代码错误

- `PL-STATE-002`：schema validation、tamper fail-closed、动态 response/OOD 已有；但缺少对 frozen wire 中**每个必需字段**的完整 behavior-consumption trace。当前 structural harness 也给出 `EVIDENCE_MISSING`。
- `PL-REF-004`：已有 local split、migration、process marginal non-regression；但 old-scope manifest 只封了 process marginals/有限输出，并未覆盖所有 unaffected diagnosis/forecast/action/plan queries。

## Architecture gates G01–G18

| Gate | Result | Decisive evidence / gap |
|---|---|---|
| G01 | PASS | Future events cannot alter old state or old-head outputs. |
| G02 | PASS | Planned/performed separated; response arrives only at availability cut. |
| G03 | PASS | Exact event-id、equivalent same-source rendering、fresh/cold replay 全部 byte exact。 |
| G04 | PASS | All heads consume the same hash; poisoned private cache is ignored. |
| G05 | PASS | Query purity/order and fail-closed control-plane authority tested. |
| G06 | PASS | Signed negative evidence and registered same-source clone/common-child invariance pass. |
| G07 | PASS | Factorial concurrency; 12 processes → 8192 joint hypotheses. |
| G08 | PASS | Local modes, opposite directions, guards, hysteresis and ablation. |
| G09 | PASS | Support masking and action-memory twins differ. |
| G10 | PASS | Geometry affects inference/planning; ablation changes result. |
| G11 | PASS | Lifecycle matrix is executable. `no_new_action` and explicit continue have the same physiology for an already-active exposure by architecture §8, but distinct policy trace. |
| G12 | PASS | Dynamic OOD residual, scope gap and explicit abstention. |
| G13 | PASS | Observed post-action change enters canonical response memory used by subsequent shared-state queries. |
| G14 | PASS | Collision witness can block unsafe planner choice; no separator returns typed unidentifiable. |
| G15 | **EVIDENCE_MISSING** | Local split/action modulation/migration pass; full old-scope query corpus absent. |
| G16 | **FAIL** | Current source has no current final manifest/seal; old manifests mismatch 11/10 files. |
| G17 | PASS | Effect claims carry status/assumptions/scope; planner excludes unidentifiable and collided action. |
| G18 | NOT_EXECUTED | This reviewer intentionally read no case. |

## Perfect-landing gate summary

```text
PASS             20
FAIL              0
EVIDENCE_MISSING  5   PL-BLIND-001, PL-LED-001, PL-STATE-002,
                       PL-REF-004, PL-REPORT-001
NOT_EXECUTED      5   PL-DX-001, PL-DX-002, PL-PRED-001,
                       PL-PRED-002, PL-CASE-001
```

详细逐 gate 机器结果见 `RUNTIME_V21_GAP_REVIEW.json`。

## Manifest / seal drift

| Artifact | Current finding |
|---|---|
| `evidence/manifest.json` | 11 hash mismatches; binds old `19/19` runtime |
| `evidence/WIRE_CHECKPOINT_MANIFEST_v2.1.json` | 10 hash mismatches; nonfinal checkpoint |
| `evidence/FREEZE_SEAL.json` | still binds old manifest; byte-identical to `FREEZE_SEAL_v2.0_SUPERSEDED.json` |
| `evidence/WIRE_CHECKPOINT_SEAL_v2.1.json` | explicitly `NONFINAL_CHECKPOINT_NOT_FINAL_RUNTIME_FREEZE` |

这不是意外：runtime owner 正等待 gap review 后才 seal。但它意味着 G16 在当前审计切面仍不能 PASS。

## Minimum next steps

1. 生成完整 `field_consumption_trace`，覆盖 frozen wire 每个必需字段，包括“非法修改会 fail closed”的路径。
2. 把 refinement non-regression 扩展为所有 unaffected diagnosis/forecast/action/plan query 的冻结 corpus。
3. 原样重跑 36 runtime tests、6 ledger tests、structural harness 和独立 equivalent-rendering probe。
4. 最后生成绑定新源码、36/36、6/6 和结构证据的 runtime v2.1 manifest/seal；绝不能复用 19/19 seal。
5. 真实病例 replay 必须另做：本报告只证明/否证结构能力，不能证明临床 readout。

## Boundary

本审计没有读取病例、`CASE_SELECTION`、文章、expected diagnosis 或 case model pack。它不能评价临床参数是否正确，也不能把 neutral fixture 的结构成功解释为真实医学有效性。
