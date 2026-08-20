# Runtime Concept Map Card

## Outcome

已建立 106 个 concept ID 到两份盲模型的 diagnosis-neutral 语义桥；未读取 case 事件、数值、结局、最终诊断、PMC 文章或 V5。

- `PMC10448002` → `blind-tma-differential-v0`：18 个 rankable，16 个 context/action-only，31 个 record-only/unmapped。
- `PMC7005653` → `hav_takotsubo_generic_blind_v0`：12 个 rankable，0 个 context/action-only，29 个 record-only/unmapped。

运行时产物：`runtime_concept_map.json`

## Key Evidence / Contract

1. 只有 `rankable_observation` 可进入 clinical likelihood。
2. `context_or_action_only` 只更新 availability、performed-action memory 或 exposure gate，不提供疾病身份。
3. `record_only/unmapped` 的 likelihood 恒为 0；即使列出 `branch_relevant_latent_ids`，也只是语义邻接，不是 emission。
4. 全部 `value_direction = null`；此映射不从 ID 猜 positive/negative、high/low 或趋势方向。
5. `same_factor_group_ids` 必须联合折叠/调度，derived flag、summary、trend restatement 不得成为重复票。
6. hypothesis/diagnosis wording 一律不映射为观测；宽泛 bundle 未拆成具体 finding 前不排名。

## 关键未映射缺口

### PMC10448002

- `heparin_induced_thrombocytopenia_panel_result`：未说明 PF4 immunoassay 还是 functional assay，不能猜。
- `total_bilirubin`：TMA 模型注册的是 indirect bilirubin，不可偷换 analyte。
- 肾活检微血管病理：可关联 generic renal/endothelial latent，但模型没有 pathology observation/emission，均 record-only。
- `outpatient_genetic_testing_for_complement_regulation_abnormality`：未来/计划检查不是 predisposition result。
- 所有 disease hypothesis 均拒绝作为 observation。

### PMC7005653

- HAV/HBV/HCV/HEV/HIV serology：generic 模型没有 etiologic assay node。
- `hepatic_encephalopathy_grade`、进展和 `serum_ammonia`：有相关 latent/coordinate，但没有 observation emission。
- coronary imaging 与 ST depression：有 ischemic latent 语义关联，但无 coronary/ECG emission。
- ALP/GGT、cerebral pulsatility、hepatic histology、症状均无安全的 node 等价物。

## Verification

`runtime_concept_map.json` 内嵌校验：**PASS**。

已验证：106/106 inventory 覆盖；所有 observed/factor/latent/context/background/action/same-factor 引用存在；全部方向为空；rankable 必有 observed node；record-only 不含 observed node；same-factor 双向成员一致。

## Next Step

runtime 应独立 seal/hash 此映射，仅对 rankable observation 计 likelihood，公开 record-only residual，并按 same-factor group 报告贡献。
