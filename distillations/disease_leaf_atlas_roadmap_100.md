# VeSMed V5 Disease Leaf Atlas Roadmap to 100

原则：

- 第一层 disease manifold 蒸到临床稳定 disease leaf，不蒸过宽 umbrella。
- `disease_id` 不能夹带病名之外的 mimic、近邻病、严重度或亚型提示。
- 已蒸旧 ID 可以先保留做测试基线；新蒸馏优先使用 clean ID。
- 治疗旧 JSON 可由工程侧 compact/补 treatment vector field，不要求重复重蒸旧病。

## 当前 Atlas 审核

| 当前 ID | 状态 | 判断 |
| --- | --- | --- |
| D137 | keep | AOSD non-MAS 可作为稳定 disease leaf |
| D-SEPSIS-GN | legacy keep | 作为 PoC sepsis baseline 可保留；未来按 source/pathogen 拆细 |
| D-TTP | keep | acquired immune TTP 是合格 disease leaf |
| D-HLH-MAS | keep | HLH/MAS 是综合征型 leaf；触发因素先放 risk/context |
| D-SLE-FLARE | keep for now | 可作为 fever atlas leaf；未来可拆 lupus nephritis/pneumonitis/CNS lupus |
| D-TB-DISSEMINATED | keep | disseminated TB 是合格 leaf |
| D-LYMPHOMA-FEVER | legacy split now | 过宽；ALCL real case 被 MIS-A 吸走时不要调 case，应拆 Hodgkin / DLBCL / ALCL / IVLBCL 等 subtype leaves |
| D-INFECTIVE-ENDOCARDITIS | keep | IE 是合格 leaf；native/prosthetic/right-sided 先作 context/subtype |
| D-MPA | keep | microscopic polyangiitis 是合格 leaf |
| D-DRUG-FEVER-DRESS | legacy migrate | ID 混入 drug fever；未来 clean ID 用 D-DRESS |
| D-EBV-CMV-MONO-LIKE | polluted, replace | ID 混入 CMV；未来用 D-INFECTIOUS-MONONUCLEOSIS，CMV 另蒸 |
| D-INFECTIOUS-MONONUCLEOSIS | next clean | clean ID，替代 D-EBV-CMV-MONO-LIKE |
| D-MIS-A-KAWASAKI-LIKE | rename before distill | ID 混入 Kawasaki-like；clean ID 用 D-MIS-A |
| D-LEPTOSPIROSIS-SEVERE | rename before distill | severe 是严重度；clean ID 用 D-LEPTOSPIROSIS |

## Next 20 High-Priority Leaves

这些优先覆盖发热疑难、近邻 mimic、治疗上下文和 ICU 风险。

| priority | disease_id | disease leaf |
| --- | --- | --- |
| 1 | D-INFECTIOUS-MONONUCLEOSIS | Infectious mononucleosis |
| 2 | D-CMV-MONO | Cytomegalovirus mononucleosis-like illness |
| 3 | D-MIS-A | Multisystem inflammatory syndrome in adults |
| 4 | D-LEPTOSPIROSIS | Leptospirosis |
| 5 | D-GPA | Granulomatosis with polyangiitis |
| 6 | D-EGPA | Eosinophilic granulomatosis with polyangiitis |
| 7 | D-HODGKIN-LYMPHOMA | Hodgkin lymphoma with inflammatory fever |
| 8 | D-DLBCL | Diffuse large B-cell lymphoma |
| 9 | D-ALCL | Anaplastic large-cell lymphoma |
| 10 | D-IVLBCL | Intravascular large B-cell lymphoma |
| 11 | D-ACUTE-HIV | Acute HIV retroviral syndrome |
| 12 | D-BRUCELLOSIS | Brucellosis |
| 13 | D-Q-FEVER | Q fever |
| 14 | D-BARTONELLA-ENDOCARDITIS | Bartonella infective endocarditis |
| 15 | D-RICKETTSIOSIS-SCRUB-TYPHUS | Scrub typhus / rickettsiosis |
| 16 | D-MALARIA-FALCIPARUM | Plasmodium falciparum malaria |
| 17 | D-PYOGENIC-LIVER-ABSCESS | Pyogenic liver abscess |
| 18 | D-PJP-PNEUMONIA | Pneumocystis jirovecii pneumonia |
| 19 | D-NEUTROPENIC-FEVER | Febrile neutropenia |
| 20 | D-CAR-T-CRS | CAR-T cytokine release syndrome |

## Candidate Pool Toward 100

### Infection

| disease_id | disease leaf |
| --- | --- |
| D-CMV-MONO | Cytomegalovirus mononucleosis-like illness |
| D-ACUTE-HIV | Acute HIV retroviral syndrome |
| D-CAEBV | Chronic active EBV disease |
| D-COVID19-ACUTE | Acute COVID-19 |
| D-INFLUENZA | Influenza |
| D-ADENOVIRUS-SEVERE | Severe adenovirus infection |
| D-MYCOPLASMA-PNEUMONIA | Mycoplasma pneumoniae pneumonia |
| D-LEGIONELLA-PNEUMONIA | Legionella pneumonia |
| D-PNEUMOCOCCAL-PNEUMONIA | Pneumococcal pneumonia |
| D-STAPH-AUREUS-SEPSIS | Staphylococcus aureus sepsis / bacteremia |
| D-MRSA-BACTEREMIA | MRSA bacteremia |
| D-CANDIDEMIA | Candidemia |
| D-INVASIVE-ASPERGILLOSIS | Invasive aspergillosis |
| D-PJP-PNEUMONIA | Pneumocystis jirovecii pneumonia |
| D-NOCARDIOSIS | Nocardiosis |
| D-BRUCELLOSIS | Brucellosis |
| D-Q-FEVER | Q fever |
| D-BARTONELLA-ENDOCARDITIS | Bartonella infective endocarditis |
| D-RICKETTSIOSIS-SCRUB-TYPHUS | Scrub typhus / rickettsiosis |
| D-MALARIA-FALCIPARUM | Plasmodium falciparum malaria |
| D-BABESIOSIS | Babesiosis |
| D-TOXOPLASMOSIS-DISSEMINATED | Disseminated toxoplasmosis |
| D-HISTOPLASMOSIS-DISSEMINATED | Disseminated histoplasmosis |
| D-COCCIDIOIDOMYCOSIS-DISSEMINATED | Disseminated coccidioidomycosis |
| D-CRYPTOCOCCOSIS-DISSEMINATED | Disseminated cryptococcosis |
| D-LEISHMANIASIS-VISCERAL | Visceral leishmaniasis |
| D-TYPHOID-FEVER | Typhoid fever |
| D-NONTYPHOID-SALMONELLA-BACTEREMIA | Nontyphoidal Salmonella bacteremia |
| D-CLOSTRIDIOIDES-DIFFICILE-SEVERE | Severe Clostridioides difficile infection |
| D-COMPLICATED-PYELONEPHRITIS | Complicated pyelonephritis |
| D-PYOGENIC-LIVER-ABSCESS | Pyogenic liver abscess |
| D-VERTEBRAL-OSTEOMYELITIS | Vertebral osteomyelitis |
| D-SEPTIC-ARTHRITIS | Septic arthritis |
| D-NECROTIZING-FASCIITIS | Necrotizing fasciitis |
| D-MENINGOCOCCEMIA | Meningococcemia |
| D-BACTERIAL-MENINGITIS | Acute bacterial meningitis |
| D-HSV-ENCEPHALITIS | HSV encephalitis |
| D-DISSEMINATED-LYME | Disseminated Lyme disease |
| D-SECONDARY-SYPHILIS | Secondary syphilis |
| D-DISSEMINATED-GONOCOCCAL-INFECTION | Disseminated gonococcal infection |

### Rheumatology / Autoinflammatory

| disease_id | disease leaf |
| --- | --- |
| D-GPA | Granulomatosis with polyangiitis |
| D-EGPA | Eosinophilic granulomatosis with polyangiitis |
| D-PAN | Polyarteritis nodosa |
| D-GCA | Giant cell arteritis |
| D-TAKAYASU-ARTERITIS | Takayasu arteritis |
| D-BEHCET-DISEASE | Behcet disease |
| D-IGG4-RELATED-DISEASE | IgG4-related disease |
| D-SARCOIDOSIS | Sarcoidosis |
| D-RELAPSING-POLYCHONDRITIS | Relapsing polychondritis |
| D-ANTISYNTHETASE-SYNDROME | Antisynthetase syndrome |
| D-DERMATOMYOSITIS | Dermatomyositis |
| D-POLYMYOSITIS | Polymyositis |
| D-RA-FLARE | Rheumatoid arthritis systemic flare |
| D-SJOGREN-SYSTEMIC | Systemic Sjogren disease |
| D-CATASTROPHIC-APS | Catastrophic antiphospholipid syndrome |
| D-KAWASAKI-DISEASE | Kawasaki disease |
| D-RHEUMATIC-FEVER | Acute rheumatic fever |
| D-FAMILIAL-MEDITERRANEAN-FEVER | Familial Mediterranean fever |
| D-TRAPS | TNF receptor-associated periodic syndrome |
| D-CAPS | Cryopyrin-associated periodic syndrome |

### Hematology / Oncology / TMA

| disease_id | disease leaf |
| --- | --- |
| D-HODGKIN-LYMPHOMA | Hodgkin lymphoma |
| D-DLBCL | Diffuse large B-cell lymphoma |
| D-ALCL | Anaplastic large-cell lymphoma |
| D-IVLBCL | Intravascular large B-cell lymphoma |
| D-ACUTE-LEUKEMIA | Acute leukemia |
| D-APL | Acute promyelocytic leukemia |
| D-NEUTROPENIC-FEVER | Febrile neutropenia |
| D-CAR-T-CRS | CAR-T cytokine release syndrome |
| D-AIHA | Autoimmune hemolytic anemia |
| D-EVANS-SYNDROME | Evans syndrome |
| D-STEC-HUS | Shiga toxin-associated hemolytic uremic syndrome |
| D-COMPLEMENT-MEDIATED-TMA | Complement-mediated thrombotic microangiopathy |
| D-DIC | Disseminated intravascular coagulation |
| D-HEPARIN-INDUCED-THROMBOCYTOPENIA | Heparin-induced thrombocytopenia |
| D-SICKLE-CELL-ACUTE-CHEST | Sickle cell acute chest syndrome |

### Drug / Toxicology / Endocrine / Critical Mimics

| disease_id | disease leaf |
| --- | --- |
| D-DRUG-FEVER | Simple drug fever |
| D-DRESS | Drug reaction with eosinophilia and systemic symptoms |
| D-SJS-TEN | Stevens-Johnson syndrome / toxic epidermal necrolysis |
| D-NEUROLEPTIC-MALIGNANT-SYNDROME | Neuroleptic malignant syndrome |
| D-SEROTONIN-SYNDROME | Serotonin syndrome |
| D-MALIGNANT-HYPERTHERMIA | Malignant hyperthermia |
| D-THYROID-STORM | Thyroid storm |
| D-ADRENAL-CRISIS | Adrenal crisis |
| D-HEAT-STROKE | Heat stroke |
| D-ACUTE-PANCREATITIS | Acute pancreatitis |
| D-ALCOHOLIC-HEPATITIS | Alcoholic hepatitis |
| D-ACUTE-LIVER-FAILURE | Acute liver failure |
| D-TRANSFUSION-REACTION-FNHTR | Febrile non-hemolytic transfusion reaction |
| D-TRANSFUSION-REACTION-HEMOLYTIC | Acute hemolytic transfusion reaction |
| D-TRANSPLANT-REJECTION-ACUTE | Acute transplant rejection |

## Operational Batch Rule

- 每批 3-4 个新 disease leaf 可以并行蒸。
- 每个新 disease 至少补 1 个 PMC/PubMed positive real case。
- 每批跑现有 full single + combo smoke test。
- 如果治疗 ranking 异常，优先 compact/补 treatment vector field，不要求重蒸整个 disease。
- Lymphoma fever 拆分优先从 `D-ALCL` 开始，因为当前 ALCL FUO real case 会被 `D-MIS-A` 吸走；随后补 `D-HODGKIN-LYMPHOMA`、`D-DLBCL`、`D-IVLBCL`。
