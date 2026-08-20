# 新临床框架最终独立审计

日期：2026-07-20  
范围：`research/new_clinical_framework_case_study`  
边界：本审计只评价本目录中的新框架、两个真实病例回放和独立 shadow refinement；不读取、不比较、也不援引 V5。

## Outcome

最关键的“复杂真实病例能否正确定位和更新”实验已经完成，结果是：

> **事件时序、单一共享状态、序列化递归更新这些工程外壳通过；但是两个真实复杂病例的临床 readout 都失败。当前最小内核不能正确完成复杂病例的机制定位、模式更新和病例条件化动作规划。**

这没有推翻聊天中提出的架构类别，但推翻了“当前最小实现已经足够”这一更强结论。两个病例还暴露了一个必须补入架构本体的结构：**并发 active processes，以及 branch/organ-local modes**。若仍把 branch 当成互斥 simplex、mode 当成全身唯一标签，那么这两个病例在类型上就装不进去。

建议把当前总状态写成：

```text
SUPPORTED_ARCHITECTURE_CLASS
+ RUNTIME_CONTRACT_PASS
+ REAL_CASE_CLINICAL_READOUT_FAIL
+ ARCHITECTURE_REFINEMENT_REQUIRED
```

而不是“理想模型已验证”，也不应只写容易误解的 `CASE-CONSISTENT`。

## Key Evidence

### 1. 冻结与可复现性

| 证据 | 结果 |
|---|---|
| blind model seal | `10b86590e3eda50d3fd79d0d5e35a048ac46cbbaa44dfe88a6a2ef1f9c71f517`，复核通过 |
| case ledger seal | `0810f5f7e94046b04728fc5de7ab0c3082d2c4bb8affd36c84d08f7df8cd38c0`，复核通过 |
| runtime concept map seal | `55b306c084e4d2c2566c184469f1ab63d396091be81c29ee488b4da77a5703f0`，重新计算完全一致 |
| real-case result SHA-256 | `348f3e50868c90366bac3d875d1b0cfc3cb185ccb52b327f00a2dd4c463d3595`，重跑字节级一致 |
| tests | `19/19 passed` |
| case cuts | `6 + 10 = 16` |
| event counts | `109` source/raw events；展开后 `74 + 65 = 139` normalized public events |

concept mapping 是 blind model 与 case ledger 冻结后的独立产物，并单独 seal。映射卡声明未使用病例数值、结局、最终诊断或文章内容；本审计能验证该合同及 seal，但不能仅凭文件证明生成者认知层面的绝对盲法。

### 2. 真实病例一：PMC10448002

运行规模：6 cuts；39 个 rankable source observations 中映射 23 个，覆盖率 `58.97%`，16 个未映射。

临床失败：

- 最终 top branch 为 **血栓性血小板減少性紫斑病 / Thrombotic thrombocytopenic purpura / `B_TTP`**：`0.4757`；病例后续证据支持的 **補体介在性血栓性微小血管症 / Complement-mediated thrombotic microangiopathy / `B_COMPLEMENT_TMA`** 仅 `0.3404`。
- 首次就诊就被标为 `recovering=0.72`；肾活检后血肿/失血并发症 cut 仍为 `recovering=0.72`；出院时反而只标为 `compensated=0.72`，没有可靠表示“并发症后恢复”的模式转移。
- 6 个 cut 的计划动作全部相同：`A_CONTINUE_EXISTING_SUPPORT`。诊断证据、活检并发症、ADAMTS13/补体工作完成和出院均未改变动作选择。
- unknown mass 全程固定在最小值 `0.05`，尽管 41.03% rankable source observations 没有进入模型。
- 弱 ordinal next-cut direction proxy 为 `0/5`。该 proxy 不是临床指标，不能解释为准确率，但至少没有给当前预测提供正向支持。

### 3. 真实病例二：PMC7005653

运行规模：10 cuts；52 个 rankable source observations 中映射 21 个，覆盖率 `40.38%`，31 个未映射；9 个真实 performed treatments 中 0 个映射到模型 action catalog。

临床失败：

- 入院肝损伤阶段可以粗略把质量移向肝脏分支；到 day-2 cardiac workup 后，**急性冠症候群 / Acute coronary syndrome / `acute_coronary_syndrome`**、**急性心筋炎 / Acute myocarditis / `acute_myocarditis`** 与 **たこつぼ症候群 / Takotsubo syndrome / `takotsubo_syndrome`** 始终完全并列，不能利用后续冠脉/室壁运动证据完成定位。
- 休克 cut 能把 mode 从 compensated 推到 strained/decompensated，这是有限的 case-consistent 更新；但 plasma exchange、拔管和转普通病房后仍停在 `strained=0.62, decompensated=0.28`，恢复过程没有进入状态。
- 10 个 cut 全部选择 `CirculatorySupport`。原因不是病例持续需要同一动作的可信推断，而是实际 treatment/action 未映射，动作动力学只是占位规则。
- unknown mass 同样全程为 `0.05`，与 59.62% 映射缺口矛盾。
- 弱 ordinal next-cut direction proxy 为 `1/9`；同样不能当临床准确率，只说明当前自然预测没有获得有意义的病例支持。

### 4. 两例揭示的真正架构缺口

两例都不是“只能选择一个 disease branch”的世界：

- PMC10448002 可同时存在原始肾脏/免疫假说、TMA、活检后血肿/失血，以及待排的 HIT；
- PMC7005653 同时存在急性肝衰竭、Takotsubo 心功能障碍和休克，而且肝、心、循环可能处于不同 mode。

当前实现把所有 branch 压进一个总和为 `1-unknown` 的互斥 simplex，并给所有 branch 复制同一个 global mode。因此需要把原状态式补成：

```text
患者状态 =
    对 active-process set / factorial branches 的联合不确定性
  + 各 active branch/organ 内的局部连续坐标
  + branch/organ-local mode 及其耦合
  + 动作生命周期与历史摘要
  + 映射覆盖/OOD epistemic residual
```

这是**局部细化聊天架构**，不是退回扁平向量，也不是否定因子图、混合动力学或分支几何。

### 5. shadow refinement 结果

独立 finite shadow world 的结果可复现：

- 旧动作范围内，两亚型可安全合并；
- 新治疗产生一个 exact dangerous collision：同一旧状态中，亚型 A 相对响应 `+6`，亚型 B `-10`，且最优动作不相交；
- 有公开可用 biomarker 时，局部拆分把 mean oracle regret 从 `3.0` 降至 `0.0`；旧 query 与无关 stratum 不变；
- 没有任何可观察区分信息时，系统保持 `UNIDENTIFIABLE`，不强制分 child，mean oracle regret 仍为 `3.0`。

因此“新治疗暴露状态碰撞 → 找新区分检查 → 局部拆图”的**逻辑控制流成立**。但这不是当前 `FrameworkModel.refine()` 的 end-to-end 成功：实际 runtime refine 后新增 marker 仍 `recognized=0`，且旧 state 因 model digest 不同无法迁移。

## 硬门禁逐项状态

硬门禁不是拍一个 AUROC 阈值，而是可以被单个反例击穿的能力合同。

| ID | 门禁 | 当前状态 | 证据/说明 |
|---|---|---|---|
| T01 | future availability | PASS | 未来事件不改变旧 cut bytes |
| T02 | planned vs performed | PARTIAL | planned 不改变 physiology；performed 的 start/continue/stop 生命周期不完整 |
| T03 | recursive closure | PARTIAL | fresh-process exact-once delta 通过；同事件重复投递会改 mode 和 count |
| T04 | head isolation | PASS-INTERFACE | readout 只收 state；未做恶意 side-channel 测试 |
| T05 | exact shared bytes | PASS | diagnosis/no-action/action forecasts 消费同一 state hash |
| T06 | query purity | PASS | query 顺序不改变状态或输出 |
| T07 | common-cause evidence | PARTIAL | 同 source copy 去重；没有真正联合 factor likelihood/posterior |
| T08 | support masking | PARTIAL | TMA exposure 可入 state；HAV 0/9 action 映射，且 action effect 语义失真 |
| T09 | mode hysteresis | FAIL | 只有全局趋势阈值和固定 drift，无 guard/hysteresis/branch-local transition |
| T10 | branch geometry | FAIL-INTEGRATION | distance utility 存在；topology on/off 时 diagnosis 和 rollout 完全相同 |
| T11 | no-op/continue/stop | FAIL | continue 与 stop 的 burden 完全相同，且都被解释为改善 |
| T12 | unknown/OOD | FAIL | 两例映射缺口 41%/60%，unknown 仍固定 0.05 |
| T13 | dynamic identification | NOT TESTED | 没有 response → state update → all rollouts 联动的真实病例测试 |
| T14 | natural/treatment shared core | PARTIAL-MECHANICAL | 共用 `_transition()`，但 transition 是占位序数动力学 |
| T15 | dangerous collision detection | SHADOW PASS / RUNTIME FAIL | shadow witness 成立；`FrameworkModel` 无碰撞检测器 |
| T16 | false split protection | SHADOW PARTIAL | shadow 保持旧 query；没有真实 cohort false-split 审计 |
| T17 | action regret | SHADOW PASS | 有 synthetic oracle；无真实临床反事实真值 |
| T18 | unseen-treatment split | SHADOW PASS / RUNTIME FAIL | 思想实验通过；engine refinement 未闭环 |
| T19 | local state migration | FAIL | old state 被新 model digest 拒绝，无迁移 kernel |
| T20 | unobservable split abstention | SHADOW PASS / RUNTIME ABSENT | shadow 正确返回 UNIDENTIFIABLE；runtime 无 child posterior pipeline |
| T21 | new check integration | SHADOW PASS / RUNTIME FAIL | runtime 新 marker 为 unrecognized |
| T22 | schema/version lineage | PARTIAL | 有 digest/lineage；没有可执行迁移与 non-regression evidence |

## 失败分类

### A. 架构级缺口

1. **互斥单 branch + 全局单 mode 不足**：需要并发 active-process/factorial branch posterior 与 branch/organ-local modes。
2. **开放世界不确定性没有被明确纳入 state**：mapping residual、unmodeled process 与普通 observation noise 需要分开。

这两条是复杂病例对聊天框架提出的真实修正。它们不否定“局部坐标 + 因子依赖 + 混合动力学 + 分层几何 + 共享状态”。

### B. 当前实现失败

1. 因子图只是 evidence bucket + severity 平均 + score 归一化，不是联合生成/联合推断；可靠阴性 anti-GBM assay 甚至把 `B_ANTI_GBM` 从无观察时的 `0.16` 提高到 `0.19`。
2. topology/geometry 没有接入 diagnosis、forecast 或 planning。
3. controlled dynamics 是 mode 常数 drift + action 关键词常数；没有 mode jump、guard、hysteresis、branch transition 或 posterior propagation。
4. action lifecycle、event idempotency、state immutability 和 runtime refinement migration 均未完成。

### C. 模型/坐标/映射失败

1. 两例 rankable observation 覆盖仅 58.97% 与 40.38%。
2. HAV case 的 HAV serology、encephalopathy/ammonia、coronary imaging、ECG 和恢复事件缺乏安全 emission；全部 9 个 performed treatments 没有 action mapping。
3. TMA model 未把 ADAMTS13/病理/补体相关证据正确转成负证据和差异 likelihood，最终错误保留 TTP top-1。
4. local coordinates 多数是同一 scalar `load` 的复制/取反，不是已识别的 branch-local clinical state。

这些失败原则上可在不推翻架构的情况下修复，但修复后必须重新冻结模型、独立映射并重新跑 blind real cases，不能用这两例反向调参后自证成功。

### D. 原则上不可识别

1. 单病例只显示实际发生的治疗与结局，不能给出该患者未接受其他治疗时的唯一反事实。
2. PMC7005653 的恢复不能仅凭这份 case report 唯一归因于 plasma exchange；自然恢复、支持治疗和并发干预均可能贡献。
3. 两份病例不能校准 branch posterior，也不能证明跨人群治疗效果。
4. 若新治疗敏感亚型在所有可用观察和安全检查中都不可区分，则只能保留 `UNIDENTIFIABLE`；增加模型复杂度不能创造信息。

## 报告过度解读审查

`REAL_CASE_REPORT_CN.md` 已明确写出数值未校准、动作模拟不是治疗建议，并列出了两个病例的临床失败，整体边界是诚实的。

但 `case_evidence_status: CASE-CONSISTENT` 的命名容易被误读。代码中它只要求：

```text
all_query_hashes_exact && all_recursive_updates_closed
```

它不要求诊断正确、mode 正确、forecast 一致或 action 合理。建议改名为：

```text
RUNTIME_CONTRACT_CASE_REPLAY_PASS
```

并把 `clinical_case_readout_audit: FAILED` 放在同等显著位置。否则“CASE-CONSISTENT”会掩盖两例临床 readout 全部失败的事实。

## Verification

独立执行：

```powershell
$env:PYTHONPATH=(Get-Location).Path
python -m unittest discover -s tests -v
python run_experiments.py --output evidence\real_case_results_audit.json
python refinement_experiment.py
```

结果：

```text
19 tests passed
16/16 cuts exact shared-state hash
16/16 recursive updates closed
runtime concept map seal exact
real-case result byte-identical to frozen artifact
overall_status = STRUCTURALLY_CASE_CONSISTENT_BUT_CLINICAL_READOUT_FAILED
clinical_readout_status = FAILED
```

补充反例记录在 `evidence/final_audit_probes.json`：negative evidence、topology integration、continue/stop、duplicate delivery、state mutation 和 runtime refinement 均复现上述失败。

## Next Step

信息量最高的下一轮不是增加更多病例，而是先完成以下最小修复，然后重新 blind replay：

1. 把 state 改为并发 active-process/factorial branches，并给每个 branch/organ 独立 mode；
2. 实现真正的 factor likelihood/posterior，使可靠 negative evidence 能反驳 branch；
3. 把 action start/continue/stop/dose/duration/washout 和 branch-local hybrid transitions 接入同一 state；
4. 把 mapping residual/OOD pressure 显式进入 epistemic state；
5. 把 topology 接入 inference/planning，并实现 local refinement 的迁移 kernel；
6. 冻结后使用新的独立真实病例，而不是回调这两例直到通过。

## 最终一句话

> **最关键的真实病例实验给出的不是“理想模型已经找到”，而是：聊天框架的共享状态与局部细化思想仍值得保留，但当前实现临床上失败，并且架构必须补上并发机制、局部模式和开放世界不确定性，才有资格继续接受复杂病例检验。**
