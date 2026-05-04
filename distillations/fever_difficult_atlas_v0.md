# Fever Difficult Atlas v0

目标：先做一组互相很像、真实诊断困难的发热类 disease manifolds，用来压力测试 V5 的机制涌现诊断，而不是单纯扩大病种数量。

## 当前已纳入

| disease_id | 说明 | 角色 |
| --- | --- | --- |
| D137 | Adult-onset Still disease, classic systemic non-MAS | AOSD / sepsis / HLH mimic core |
| D-SEPSIS-GN | Gram-negative community-acquired sepsis | bacterial sepsis core |
| D-TTP | Acquired immune TTP | thrombocytopenia / hemolysis mimic and comorbidity stressor |

## 优先蒸馏批次

每批只蒸 1-2 个 disease。每批保存后立刻跑现有 11 个 real case，确认新 manifold 没把旧 case 错吸走；再加入对应 PMC 正例和近邻 mimic / OOD case。

### Batch 1

| disease_id | disease leaf | 为什么先做 |
| --- | --- | --- |
| D-HLH-MAS | Secondary HLH / macrophage activation syndrome | AOSD、sepsis、lymphoma、SLE 都会撞到的高危发热陷阱；测试 ferritin、cytopenia、fibrinogen、organ failure event hazards |
| D-SLE-FLARE | Systemic lupus erythematosus flare with fever | 和 infection、TTP、HLH/MAS 互相混；测试 complement、cytopenia、renal、serositis、immunosuppression risk modulation |

### Batch 2

| disease_id | disease leaf | 为什么做 |
| --- | --- | --- |
| D-TB-DISSEMINATED | Disseminated / miliary tuberculosis | FUO / sepsis / lymphoma / AOSD mimic；需要把慢性发热、weight loss、hyponatremia、granulomatous burden、immunosuppression 画进状态空间 |
| D-LYMPHOMA-FEVER | Lymphoma-associated fever / inflammatory presentation | B symptoms、LDH、ferritin、cytopenia、HLH trigger；测试恶性肿瘤 fever mimic，不靠“肿瘤标签”硬判 |

### Batch 3

| disease_id | disease leaf | 为什么做 |
| --- | --- | --- |
| D-INFECTIVE-ENDOCARDITIS | Subacute infective endocarditis | FUO、sepsis、vasculitis、immune complex renal disease mimic；需要 vegetation/embolic/valvular context axes |
| D-MPA | Microscopic polyangiitis / 顕微鏡的多発血管炎 | fever + renal/pulmonary capillaritis + inflammatory markers；和 infection、TB、SLE、AOSD 都容易混；不把 GPA/EGPA 合进同一个 umbrella manifold |

### Batch 4

| disease_id | disease leaf | 为什么做 |
| --- | --- | --- |
| D-DRESS | DRESS / severe drug hypersensitivity syndrome | fever + rash + eosinophilia + hepatitis/AKI；测试 treatment/risk context、drug exposure 不可观测上下文；旧已蒸 ID D-DRUG-FEVER-DRESS 先保留为 legacy |
| D-INFECTIOUS-MONONUCLEOSIS | Infectious mononucleosis / 伝染性単核球症 | fever、lymphadenopathy、transaminitis、atypical lymphocytosis；和 lymphoma/AOSD/SLE/HLH 边界近；不要把 CMV mononucleosis-like illness 合进同一 first-layer manifold |

### Batch 5

| disease_id | disease leaf | 为什么做 |
| --- | --- | --- |
| D-MIS-A | Multisystem inflammatory syndrome in adults | fever、rash、conjunctival/mucosal、shock/myocarditis；和 sepsis/AOSD/HLH 高度重叠；Kawasaki-like 作为 mimic/phenotype，不写进 ID |
| D-LEPTOSPIROSIS | Leptospirosis | fever + renal/liver/thrombocytopenia/sepsis mimic；测试 exposure context 和 multi-organ event hazards；severe/Weil 作为病程严重度或 subtype |

## 每个 disease 蒸馏必须覆盖

- `latent_mechanisms`：先画隐藏机制，不直接蒸诊断标签。
- `mechanism_edges`：机制到 observed axes / event hazards / mortality hazard。
- `axes`：至少覆盖 fever vitals、CBC、CRP/PCT、ferritin、liver/renal/coagulation、signature qualitative axes、event hazards、唯一 mortality hazard。
- `axis_couplings`：只写真实残余 covariance 或事件链，不写全矩阵。
- `risk_factors`：免疫抑制、年龄、妊娠、CKD、malignancy、drug exposure 等对表现和 hazard 的变形。
- `treatments`：不规定固定 target 数；每个治疗输出最小充分因果作用路径，写清直接改变的机制轴、显性 axis、event hazard 或 context axis；副作用通过 event hazard / hazard_drift 进入 outcome，不靠只改 mortality_hazard 过关。

## 每批验证

1. 保存新 distillation 后确认 `master_axes.json` 已更新。
2. 跑 `python v5_joint_sde_case_test.py`。
3. 看现有 11 个 case 是否仍 PASS；重点看 top-2 margin 和 largest residuals。
4. 为新 disease 加至少 1 个真实 PMC 正例 case，记录 PMID / PMCID / URL / paper diagnosis。
5. 加至少 1 个近邻 mimic / OOD case：例如 AOSD vs HLH、SLE vs sepsis、TB vs lymphoma、endocarditis vs vasculitis。
6. 失败时只能改通用机制、axis、coupling、risk modifier、treatment effect；不能删 case evidence 或加病例级 hardcode。

## 当前度量解释

现有 `11/11 PASS` 只是三病 atlas 的 sanity check。发热 atlas 扩到 10-12 个相似病后，核心指标改为：

- 旧 case 是否被新 manifold 错吸走。
- 新 disease 正例 top-1 / top-3 是否合理。
- mimic case 的 top-2 / top-3 是否符合临床困难点。
- OOD case 的 `delta_to_null_best_known` 是否能反映“atlas 内证据不足”，runtime 仍不写硬阈值。
