# 病例审计（运行任何排名之前完成）

检查内容（PROTOCOL.md 第 4 节）：
- `validate_case.py` 能加载；
- 首诊描述（vignette）与 V5 实际读到的证据（`audit_parity.py` 输出）是同一范围；
- vignette 不含诊断名、论文信息、确诊性检查、治疗、结局。

审计人：主 agent。审计时没有运行任何排名，也没有看过任何测试结果。

## 批次 A、C（12 例）

全部能加载，没有泄露诊断。定性值（「正常范围内」「心动过速」「肌酐低于参考下限」）都带了定性单位（`normal_flag_only` / `qualitative_positive`），runtime 打分时会换算成数值，不会按字面的 0 和 1 计算，因此不需要修改。

逐例备注：

| 病例 | 备注 |
|---|---|
| HLH_PEDIATRIC_REFRACTORY_FEVER_PMC13578911 | 一致 |
| WNND_MENINGOENCEPHALITIS_MULTISYSTEM_PMC13615839 | 一致；首诊时没有脑脊液结果 |
| SEPSIS_MYROIDES_PEMPHIGUS_SKIN_PMC13588114 | 一致；原文血压 142/112 照原样保留 |
| DIC_INTRAPELVIC_POVIDONE_IODINE_PMC13522237 | 一致；术中灌注聚维酮碘的经过两边都有 |
| SALICYLATE_TOPICAL_INFANT_PMC13264415 | 一致；外用水杨酸暴露属于首诊病史，两边都有 |
| TSS_STREPTOCOCCAL_CHEST_WALL_PHLEGMON_PMC13527185 | 一致 |
| DGI_ACUTE_HEPATITIS_BACTEREMIA_PMC12751404 | 一致；无数值生命体征 |
| CAEBV_PEDIATRIC_PULMONARY_HYPERTENSION_PMC12963054 | 一致；vignette 无 EBV 相关字样 |
| MALARIA_FALCIPARUM_PEDIATRIC_SEVERE_MOF_PMC13521499 | 一致；血涂片不参与排名，也不在 vignette 中 |
| ANTI_GBM_ELDERLY_FEVER_CRESCENTIC_GN_PMC13474007 | 一致；抗 GBM 抗体和活检不参与排名 |
| PJI_KNEE_REVISION_ACUTE_PMC13522984 | 一致；关节液结果两边都有 |
| VZV_ENCEPHALITIS_RASHLESS_MULTIFOCAL_PMC13560155 | 一致；mNGS 不参与排名 |

批次 B 中已写出文件的病例（Q 热、STEC-HUS、二期梅毒、IgG4 相关病、氰化物中毒）也初步看过：

| 病例 | 备注 |
|---|---|
| SECONDARY_SYPHILIS_PALMOPLANTAR_RASH_ARTHRITIS_PMC13579659 | 小差异：JSON 的 risk_context 有 `household_contact_illness=present`，vignette 没有提到。只多给了 V5 一条背景信息，不影响 LLM 的公平性，照原样保留 |
| CYANIDE_POISONING_INTENTIONAL_KCN_INGESTION_PMC13589660 | 一致；现场发现的氰化钾包装是首诊时的暴露信息，两边都有 |
| 其余 | 一致 |

批次 B 最终确认（交报告后）：

| 病例 | 备注 |
|---|---|
| ECTOPIC_PREGNANCY_RECURRENT_TUBAL_UNRUPTURED_PMC13478268 | 小差异：risk_context 有产科史（G4P0、两次人工流产）和「无盆腔感染史」，vignette 没写。只多给了 V5 背景信息，照原样保留。vignette 写了「既往输卵管妊娠切除输卵管」，属于首诊病史，按规则保留 |
| Q 热、STEC-HUS、二期梅毒、IgG4 相关病、氰化物中毒 | 与上表一致，确认 |

审计结论：18 例全部通过，锁定。主分析 10 例为 leaf 顺序 1–10；leaf 11–18 的 8 例为附录。
