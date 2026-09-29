# 病例搜索日志：D-Q-FEVER 批次（leaf 7–12）

搜索工具：Europe PMC REST API（`OPEN_ACCESS:y AND FIRST_PDATE:[2025-01-01 TO 2026-12-31]`，按发表日期新→旧），全文用 `fullTextXML`。
排除表：`frozen/known_pmcids.txt`。未读取任何 `distillations/v5_*.json`，未运行任何排名。

---

## 7. D-Q-FEVER — Q fever

检索式：
- `"Q fever" AND "case report" ...`（151 条）
- `("Q fever" OR Coxiella) AND ("case report" OR "case presentation") ...`（378 条，本地按日期排序、标题过滤）
- `("Q fever" OR "Coxiella burnetii") AND FIRST_PDATE:[2026-06-01 TO 2026-12-31]`（198 条，不限 "case report" 字样，用于补漏最新文献）

按日期由新到旧逐一检查的候选：

| # | PMCID | 日期 | 题目（简） | 结论 |
|---|---|---|---|---|
| 1 | PMC13603785 / PMC13568565 / PMC13581212 / PMC13564772 / PMC13610484 等 | 2026-09 | 野生动物血清学、体外实验、环境测序等 | 拒：非人类病例报告 |
| 2 | PMC13418860 | 2026-09-01 | 阿联酋奶牛群 C. burnetii 血清流行 | 拒：兽医研究，非人类病例 |
| 3 | **PMC13597175** | 2026-09-01（EPMC）/ pub-date 2026-09-22 | Q Fever Visceral Abscesses After Contact With Native Australian Marsupials（MJA） | **接受**（Clinical Record 1） |
| 4 | PMC13559915 | 2026-08-26 | 巴西亚马逊一例 Q 热的流行病学调查 | 比已接受者旧；未采用 |
| 5 | PMC13547048 | 2026-08-24 | 免疫抑制患者急性 Q 热表现为脓毒症 | 拒：入院主诉为同时发生的急性缺血性脑卒中（右 MCA M1–M2 闭塞），入院时无热，Q 热表现在住院第 2–3 天才出现——两病合并，不是单一主诊断的首诊 |
| 6 | PMC13494853 | 2026-08-21 | Emerging Q Fever Infection in Türkiye | 拒：32 例病例系列 |
| 7 | PMC13478004 | 2026-08-11 | DKA 纠正后的急性 Q 热 | 拒：首诊为糖尿病酮症酸中毒，两病合并 |
| 8 | PMC13407519 | 2026-07-14 | 腹膜透析相关腹膜炎（C. burnetii） | 拒：主诊断为反复 PD 相关腹膜炎，mNGS 仅 2 reads、多重感染，论文称"concomitant"，不明确对应 Q fever |
| 9 | PMC13382502 | 2026-07-07 | 广西误诊急性 Q 热 | 符合条件，但比已接受者旧（第一轮检索先看了它；补漏检索找到更新的 PMC13597175） |

说明：PMC13597175 是两名患者的临床记录（叙述性，非病例系列表格）。取 Clinical Record 1（64 岁男性，急性 Q 热合并脾脓肿、重症肺炎、休克）；Clinical Record 2 的肝脓肿与 D-PYOGENIC-LIVER-ABSCESS 存在重叠，且首诊信息更少，故不用。脾脓肿是同一 Q 热感染的并发症（脓肿穿刺液 Q 热 PCR 阳性），不属于两病合并；atlas 中无脾脓肿 leaf。

**结果：ACCEPTED**
- case_id：`Q_FEVER_SEVERE_PNEUMONIA_SPLENIC_LESION_PMC13597175`
- PMCID：PMC13597175；PMID 42772849；发表：2026-09-22（Med J Aust；EPMC firstPublicationDate 2026-09-01）
- 论文诊断：Acute Q fever complicated by splenic abscess
- validate_case.py：consumed_axes = 31（含 runtime 桥接出的 altered_mental_status_activity、hepatomegaly_activity 等）
- pending 轴（3）：`largest_splenic_lesion_diameter_cm`、`tropical_region_residence_presence`、`wild_animal_carcass_handling_presence`
- 首诊定量指标：体温、血压（MAP）、SpO2、FiO2、血小板、肌酐、总胆红素、ALT、AST
- 单位换算：肌酐 246 µmol/L ÷ 88.4 = 2.78 mg/dL；总胆红素 36 µmol/L ÷ 17.1 = 2.11 mg/dL；MAP = (88 + 2×50)/3 = 62.7 mmHg

---

## 8. D-STEC-HUS — Shiga toxin-associated hemolytic uremic syndrome

检索式：
- `("hemolytic uremic syndrome" OR "haemolytic uraemic syndrome" OR "Shiga toxin" OR STEC OR "E. coli O157" OR "Escherichia coli O157") AND ("case report" OR "case presentation") ...`（594 条，本地按日期排序、标题过滤）
- `("hemolytic uremic syndrome" OR ... OR O157) AND FIRST_PDATE:[2026-01-01 TO 2026-12-31]`（2049 条，不限 "case report" 字样，标题过滤后排除 atypical/complement/C3/CD46/CFH）

按日期由新到旧检查的候选：

| # | PMCID | 日期 | 题目（简） | 结论 |
|---|---|---|---|---|
| 1 | PMC13605367 | 2026-09-19 | EHEC O157 与空肠弯曲菌合并感染的右半结肠炎（Interesting Images） | 拒：无 HUS；两种病原合并感染 |
| 2 | PMC13569862 | 2026-09-07 | 静脉滥用缓释羟考酮所致 TMA | 拒：药物性 TMA，非 STEC |
| 3 | PMC13505536 | 2026-08-21 | 产后复发性 aHUS（C3 变异） | 拒：补体介导（更对应 D-COMPLEMENT-MEDIATED-TMA） |
| 4 | PMC13491588 | 2026-08-20 | 恙虫病合并溶血 | 拒：非 HUS |
| 5 | PMC13434026 | 2026-08-03 | 伴严重神经并发症的 HUS，eculizumab 治疗 | 拒：粪培养大肠杆菌阴性、未做 Shiga 毒素检测、C3 降低、CFHR3/CFHR1 缺失，论文按补体介导 TMA 处理——不能明确为 STEC-HUS |
| 6 | PMC13413293 / PMC13384603 / PMC13337012 / PMC13419854 / PMC13416571 / PMC13380191 / PMC13322129 / PMC13255280 / PMC13222131 / PMC13159203 / PMC13189715 / PMC13117088 / PMC13202841 / PMC13053955 | 2026-04 至 2026-07 | 各类 atypical/补体介导 HUS、狼疮/妊娠/钩体相关 TMA | 拒：非 STEC（标题即可判断） |
| 7 | PMC13149246 | 2026-04-23 | 阿维菌素中毒相关 HUS | 拒：非 STEC |
| 8 | **PMC13133695** | 2026-04-01 | STEC-associated HUS following neoadjuvant chemotherapy for advanced ovarian cancer（Cureus） | **接受** |

说明：卵巢癌为既往合并症（背景 / risk context），首诊为血性腹泻 + 腹痛后出现 HUS 三联征；论文明确排除化疗性 TMA、诊断为 STEC-HUS。住院后期的阴沟肠杆菌菌血症属病程事件，放入 non-ranking。

**结果：ACCEPTED**
- case_id：`STEC_HUS_ADULT_OVARIAN_CANCER_CHEMOTHERAPY_PMC13133695`
- PMCID：PMC13133695；PMID 42078274；发表：2026-04-01（Cureus）
- 论文诊断：STEC-associated hemolytic uremic syndrome（成人，晚期卵巢癌新辅助化疗中）
- validate_case.py：consumed_axes = 39
- pending 轴（4）：`bowel_wall_submucosal_edema_presence`、`monocyte_fraction`、`omental_caking_presence`、`peritoneal_deposits_presence`
- 首诊定量指标：CRP、WBC 及分类、Hb、血小板、肌酐、BUN、LDH、AST、ALT、GGT、破碎红细胞比例、Na、K、Cl（论文未报告生命体征）
- 单位换算：肌酐 250 µmol/L ÷ 88.4 = 2.83 mg/dL；BUN 16.3 mmol/L × 2.8 = 45.6 mg/dL；Hb 125 g/L = 12.5 g/dL；LDH/AST/ALT/GGT µkat/L × 60 = U/L（1128.6 / 49.8 / 31.2 / 60）

---

## 通用判定口径（leaf 9–12 同样适用）

- 排序键：Europe PMC `firstPublicationDate`（即检索 `P_PDATE_D` 所用日期）；XML pub-date 不同时在 case JSON 中注明。
- 条件 4 计数：生命体征（血压算 1 项、心率、呼吸、体温、SpO2）+ 每个化验项目各算 1 项；GCS 等评分不计入。
- 病原血清学 / 自身抗体 / 疾病定义性指标（如 IgG4）/ 毒物检测 → non-ranking。

---

## 9. D-SECONDARY-SYPHILIS — Secondary syphilis

检索式：
- `("secondary syphilis" OR syphilis OR "Treponema pallidum") AND ("case report" OR "case presentation") AND FIRST_PDATE:[2026-03-01 TO 2026-12-31]`（890 条，标题过滤）
- `("secondary syphilis" OR syphilitic OR syphilis) AND FIRST_PDATE:[2026-08-15 TO 2026-12-31]`（329 条，不限 "case report"，补漏）

按 EPMC 日期由新到旧检查的候选：

| # | PMCID | EPMC 日期 | 题目（简） | 结论 |
|---|---|---|---|---|
| 1 | PMC13599879 / PMC13585726 / PMC13595202 等 | 2026-09 | 流行病学 / 生物标志物研究 | 拒：非病例报告 |
| 2 | PMC13600129 | 2026-09-17 | 先天梅毒（研究论文） | 拒：先天梅毒，非二期梅毒 |
| 3 | PMC13586552 | 2026-09-17 | PDE-5 抑制剂掩盖的坏死性梅毒感染（阴茎） | 拒：局部坏死性软组织感染（术中培养金黄色葡萄球菌）+ 梅毒性溃疡，分期未写为二期；非单一"二期梅毒"诊断 |
| 4 | **PMC13579659** | 2026-09-17（XML pub-date 2026-09-03） | Syphilis causing elevation of anti-CCP（Front Med） | **接受** |
| 5 | PMC13597189 | 2026-09-15 | 掌跖不受累的丘疹鳞屑型二期梅毒（IDCases 图文） | 拒：首诊无定量生命体征/常规化验（仅 VDRL/TPHA 等血清学），< 5 项 |
| 6 | PMC13562801 | 2026-09-10 | 肉芽肿性二期梅毒 3 例 | 拒：3 例病例系列、无定量化验/生命体征 |

说明：若改用 XML pub-date（09-03），更新的 #5、#6 也都不满足条件，结论不变。该患者出院 4 天后因视力改变再入院、诊断神经梅毒——属同一感染的后续病程，放在 clinical_course_events（non-ranking）。自身抗体（anti-CCP 45、ANA 1:320、RF 12、dsDNA 1.0）与 RPR/梅毒螺旋体抗体、CMV 抗体指数一律 non-ranking；CRP 184 mg/L、ESR 85 mm/h 为入院前一周急诊值，按 day −7 记录。

**结果：ACCEPTED**
- case_id：`SECONDARY_SYPHILIS_PALMOPLANTAR_RASH_ARTHRITIS_PMC13579659`
- PMCID：PMC13579659；PMID：检索日尚未分配；发表：2026-09-03（XML）/ 2026-09-17（EPMC）
- 论文诊断：Early secondary syphilis（伴 anti-CCP、ANA 假阳性；出院后出现神经梅毒）
- validate_case.py：consumed_axes = 41
- pending 轴（本人新建 2）：`generalized_lymphadenopathy_presence`、`tender_lymphadenopathy_presence`；另有 2 个由 runtime 桥接自动生成、不在 registry 的轴：`palmoplantar_rash_severity`、`partial_thromboplastin_time`
- 首诊定量指标：血压、心率、体温、SpO2、aPTT（另有 anti-CCP、ANA、RF、dsDNA 数值但不参与排名）
- 单位换算：MAP = (106 + 2×71)/3 = 82.7 mmHg

---

## 10. D-IGG4-RELATED-DISEASE — IgG4-related disease

检索式：
- `("IgG4-related" OR "IgG4 related" OR IgG4-RD OR "autoimmune pancreatitis" OR Mikulicz OR IgG4) AND ("case report" OR "case presentation") AND FIRST_PDATE:[2026-05-01 TO 2026-12-31]`（483 条，标题过滤）
- `(IgG4 OR "autoimmune pancreatitis" OR "Mikulicz disease" OR "retroperitoneal fibrosis") AND FIRST_PDATE:[2026-08-20 TO 2026-12-31]`（256 条，补漏）

| # | PMCID | 日期 | 题目（简） | 结论 |
|---|---|---|---|---|
| 1 | PMC13603072 / PMC13606985 / PMC13583740 等 | 2026-09/10 | 队列研究、生信、试验方案 | 拒：非病例报告 |
| 2 | PMC13613280 | 2026-09-25 | 干燥综合征相关炎性假瘤，利妥昔单抗 | 拒：组织 IgG4/IgG < 5%、血清 IgG4 正常，论文明确排除 IgG4-RD |
| 3 | PMC13614082 | 2026-09-21 | 甲状腺眼病 + IgG4 相关眼眶病（糖尿病患者） | 拒：两病合并（TED + IgG4-ROD），17 年慢性病程，无首诊定量化验 |
| 4 | PMC13605139 | 2026-09-17 | 初疑 IgG4 相关肺病的肺部肿块再评估 | 拒：最终诊断为亚急性侵袭性曲霉病 |
| 5 | PMC13577855 | 2026-09-07 | 特发性纵隔 + 腹膜后纤维化 | 拒：血清 IgG4 正常、病理不支持，论文诊断特发性纤维化而非 IgG4-RD |
| 6 | PMC13507706 | 2026-08-25 | GPA 伴胰腺/肾假瘤 | 拒：GPA，非 IgG4-RD |
| 7 | **PMC13598822** | 2026-08-24 | IgG4-RD with a biphasic clinical course of spontaneous remission and relapse（Cureus） | **接受** |

说明：结构化的是 Day 1 初次就诊（上腹痛 6 天、胰酶升高、MRI 胰体 4×2 cm 肿块）。血清 IgG4 224 mg/dL 为疾病定义性血清学指标，放 non-ranking；EUS-FNA 细胞学、诊断标准判定、32 个月后以 IgG4 硬化性胆管炎复发均为 non-ranking。未采用复发时点作为 snapshot，因为其病史中已含"自身免疫性胰腺炎"诊断。

**结果：ACCEPTED**
- case_id：`IGG4_RD_PANCREATIC_MASS_EPIGASTRIC_PAIN_PMC13598822`
- PMCID：PMC13598822；PMID 42781405；发表：2026-08-24（Cureus）
- 论文诊断：IgG4-related disease（首发为 probable type 1 autoimmune pancreatitis，自发缓解；2.5 年后以 IgG4 相关硬化性胆管炎复发）
- validate_case.py：consumed_axes = 27
- pending 轴（3）：`main_pancreatic_duct_dilation_presence`、`pancreatic_lesion_restricted_diffusion_presence`、`pancreatic_mass_largest_diameter_cm`
- 首诊定量指标：淀粉酶、脂肪酶、总蛋白、白蛋白、总胆红素、AST、ALT、ALP、GGT、WBC、CRP（未报告生命体征）
- 单位换算：CRP 0.21 mg/dL × 10 = 2.1 mg/L；WBC 7.5 × 10³/µL = 7.5 × 10⁹/L

---

## 11. D-CYANIDE-POISONING — Cyanide poisoning

检索式：`(cyanide OR "hydrogen cyanide" OR amygdalin OR "apricot kernel" OR cassava OR hydroxocobalamin OR nitroprusside OR acetonitrile OR "smoke inhalation") AND ("case report" OR "case presentation" OR poisoning) AND FIRST_PDATE:[2025-01-01 TO 2026-12-31]`（2863 条，标题过滤后逐条看）

| # | PMCID | 日期 | 题目（简） | 结论 |
|---|---|---|---|---|
| 1 | PMC13558369 / PMC13501378 / PMC13598110 等 | 2026-08/09 | 木薯育种、氰化物前药等基础研究 | 拒：非病例报告 |
| 2 | **PMC13589660** | 2026-08-20 | Complete recovery following intentional potassium cyanide poisoning despite delayed hydroxocobalamin（Cureus） | **接受** |

说明：诊断基于现场证据（空的"5 g 氰化钾"包装、遗书）与临床表现，未做血氰测定；可能合并服用抗抑郁药但未证实——论文主诊断仍是氰化物中毒（单一主诊断）。现场暴露史属首诊可得信息，作为 risk_context 参与排名；血硫氰酸盐 0.66 mg/dL、血乙醇阴性等毒物检测放 non-ranking。

**结果：ACCEPTED**
- case_id：`CYANIDE_POISONING_INTENTIONAL_KCN_INGESTION_PMC13589660`
- PMCID：PMC13589660；PMID 42763735；发表：2026-08-20（Cureus）
- 论文诊断：Suspected intentional potassium cyanide poisoning（up to 5 g）
- validate_case.py：consumed_axes = 64
- pending 轴（本人新建 5）：`bitter_almond_odor_presence`、`head_ct_acute_abnormality_presence`、`mean_corpuscular_hemoglobin`、`mean_corpuscular_hemoglobin_concentration`、`mood_disorder_history_presence`；另有 runtime 桥接生成的 `shock_activity`
- 首诊定量指标：血压、心率、SpO2、动脉血气（pH、HCO3、PCO2、PO2、乳酸、BE）、血常规、尿素、肌酐、Na、K、Mg、Ca、AST、ALT、PT、INR、CK、CRP、血糖
- 单位换算：MAP = (75 + 2×45)/3 = 55.0 mmHg；尿素 41.5 mg/dL × 28/60 = BUN 19.4 mg/dL；总钙 2.40 mmol/L × 4.008 = 9.62 mg/dL；10³/µL = 10⁹/L；10⁶/µL = 10¹²/L

---

## 12. D-ECTOPIC-PREGNANCY — Ectopic pregnancy

检索式：`("ectopic pregnancy" OR "tubal pregnancy" OR "heterotopic pregnancy" OR "cesarean scar pregnancy" OR "interstitial pregnancy" OR "cornual pregnancy" OR "ovarian pregnancy" OR "abdominal pregnancy" OR "cervical pregnancy") AND ("case report" OR "case presentation") AND FIRST_PDATE:[2026-06-01 TO 2026-12-31]`（109 条）

| # | PMCID | 日期 | 题目（简） | 结论 |
|---|---|---|---|---|
| 1 | PMC13580525 | 2026-09-17 | 33 周残角子宫妊娠破裂、活产 | 拒：论文按米勒管畸形残角妊娠破裂处理，未作为异位妊娠讨论；临床上更接近 D-UTERINE-RUPTURE，不明确对应本 leaf |
| 2 | PMC13564104 | 2026-09-11 | 妊娠期孤立性输卵管扭转 | 拒：非异位妊娠 |
| 3 | PMC13546761 | 2026-09-07 | 药物流产后胎盘植入 + 子宫 AVM（未识别的瘢痕妊娠） | 拒：多种病变叠加（稽留流产、瘢痕妊娠、AVM、植入、子宫内膜炎），首诊仅 hCG 1 项定量 |
| 4 | PMC13559882 | 2026-09-05 | 推定原发腹腔妊娠后的石胎 | 拒：首诊定量仅 Hb、β-hCG（< 5 项） |
| 5 | PMC13568741 | 2026-09-04 | 自发性宫内外同时妊娠伴输卵管破裂 | 拒：定量仅血压、心率（贫血/白细胞增多无数值），< 5 项 |
| 6 | PMC13499891 | 2026-08-21 | 宫角（angular）妊娠 | 拒：angular pregnancy 属宫内妊娠，且无定量指标 |
| 7 | PMC13541665 | 2026-08-21 | 埃博拉治疗单元内的破裂异位妊娠 | 拒：同时确诊疟疾（发热），两病合并 |
| 8 | PMC13505760 | 2026-08-21 | 非交通性残角妊娠引产失败后单角子宫破裂 | 拒：子宫破裂 / 残角妊娠，不对应本 leaf |
| 9 | PMC13570784 / PMC13506271 | 2026-08-13 / 08-12 | 早孕黄体囊肿扭转；小肠绒癌误诊为异位妊娠 | 拒：最终诊断非异位妊娠 |
| 10 | PMC13544758 | 2026-08-06 | 破裂间质部妊娠 "pack-and-compress" | 拒：首诊定量仅血压、心率、Hb、β-hCG = 4 项（GCS 不计），< 5 |
| 11 | PMC13546082 | 2026-08-06 | 自发间质部宫内外同时妊娠 | 拒：定量仅 Hb 两次，无生命体征数值 |
| 12 | PMC13453425 | 2026-08-05 | 输卵管妊娠合并部分性葡萄胎 | 拒：生命体征与常规化验仅写"正常"无数值，定量仅 β-hCG |
| 13 | **PMC13478268** | 2026-08-03 | Successful conservative treatment of contralateral recurrent ectopic pregnancy with high β-HCG after unilateral salpingectomy（Front Med） | **接受** |

说明：未破裂的右侧输卵管异位妊娠（对侧曾因输卵管妊娠切除），甲氨蝶呤保守治疗成功，无手术病理。既往输卵管切除的指征（异位妊娠）属首诊病史，用中性轴 `prior_salpingectomy_presence` 编码，原文保留在 source_text_value；vignette 中照原文保留该病史（需主 agent 审核时知悉）。治疗第 1 天出现的 20 mm 盆腔积液放 clinical_course_events。

**结果：ACCEPTED**
- case_id：`ECTOPIC_PREGNANCY_RECURRENT_TUBAL_UNRUPTURED_PMC13478268`
- PMCID：PMC13478268；PMID 42609394；发表：2026-08-03（Front Med）
- 论文诊断：Recurrent right tubal ectopic pregnancy after contralateral salpingectomy, unruptured, β-hCG > 5,000 IU/L，重复 MTX 保守治疗
- validate_case.py：consumed_axes = 38
- pending 轴（7）：`adnexal_mass_largest_diameter_cm`、`adnexal_mass_peripheral_vascularity_presence`、`adnexal_thickening_on_exam_presence`、`corpus_luteum_presence`、`endometrial_thickness_mm`、`prior_salpingectomy_presence`（以及 registry 内已有轴均正常消费）
- 首诊定量指标：血压、心率、呼吸、体温、β-hCG、Hb、ALT、AST
- 单位换算：MAP = (109 + 2×70)/3 = 83.0 mmHg；Hb 119 g/L = 11.9 g/dL；13 mm = 1.3 cm

---

## 汇总

| leaf | 结果 | case_id | PMCID |
|---|---|---|---|
| D-Q-FEVER | ACCEPTED | Q_FEVER_SEVERE_PNEUMONIA_SPLENIC_LESION_PMC13597175 | PMC13597175 |
| D-STEC-HUS | ACCEPTED | STEC_HUS_ADULT_OVARIAN_CANCER_CHEMOTHERAPY_PMC13133695 | PMC13133695 |
| D-SECONDARY-SYPHILIS | ACCEPTED | SECONDARY_SYPHILIS_PALMOPLANTAR_RASH_ARTHRITIS_PMC13579659 | PMC13579659 |
| D-IGG4-RELATED-DISEASE | ACCEPTED | IGG4_RD_PANCREATIC_MASS_EPIGASTRIC_PAIN_PMC13598822 | PMC13598822 |
| D-CYANIDE-POISONING | ACCEPTED | CYANIDE_POISONING_INTENTIONAL_KCN_INGESTION_PMC13589660 | PMC13589660 |
| D-ECTOPIC-PREGNANCY | ACCEPTED | ECTOPIC_PREGNANCY_RECURRENT_TUBAL_UNRUPTURED_PMC13478268 | PMC13478268 |

给主 agent 审核的提示：
- 氰化物病例 vignette 含现场"氰化钾"包装、异位妊娠病例 vignette 含"既往输卵管妊娠行输卵管切除"——两者均为论文首诊原文信息，按规则保留，但会使 LLM 侧明显容易，审核时请知悉。
- vignette 文件名按规定用 `<CASE_ID>.txt`，case_id 含病名；交给 LLM 时应只传文件内容。
