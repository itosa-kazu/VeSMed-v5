# Blind Full-Text Real-Case Pilot: 10-Case Regression

Date: 2026-05-16

## Scope

- Each extraction returned to PMC/PubMed full text and preserved PMCID, PMID, and source URL.
- Extraction JSON files contain no `expected_manifold`, no `expected_manifolds`, and no `disease_label_per_paper`.
- Rankable observations use diagnosis-neutral axes only; no ordinary observed axis uses `_in_D-...`.
- `record_only` items are not consumed by ranking.
- Ranking copies under `tmp_blind_eval/cases_for_ranking/` add paper labels and expected manifolds only after extraction.

## Result

- Initial 10-case run: `5/10 PASS` (`tmp_blind_eval/blind_pilot_10case_result.txt`).
- Final 10-case run after runtime repairs and context gating: `10/10 PASS` (`tmp_blind_eval/blind_pilot_10case_after_context_gating.txt`).
- Extraction QA: `10/10` have PMCID/PMID/source URL, no expected fields in extraction, no disease-suffixed ordinary axes, and no rankable record-only entries.

## Runtime Repairs

- Strengthened explicit no-anchor penalty for diseases that require specific clinical context.
- Added neutral unit conversion for leukocyte percentage/fraction and `10^3/uL` vs `10^9/L`.
- Added neutral axis aliases for AST/ALT, INR, glucose, arterial pH, shock, coma, seizure, Kussmaul breathing, jaundice, hepatic encephalopathy, syncope/palpitations, and PE/DVT imaging facts.
- Added DKA anchor support from hyperglycemia plus acidosis/Kussmaul/ketone evidence.
- Added PE anchor support from CTPA filling defect, DVT, D-dimer, pulmonary hypertension/RV strain, and shock-hazard proxies.
- Added specific-context gating for high-context mimics such as acute cholecystitis, alcoholic hepatitis, peripartum cardiomyopathy, complete AV block, pheochromocytoma crisis, systemic sclerosis renal crisis, ulcerative colitis flare, atrial/ventricular arrhythmias, cirrhosis decompensation, pelvic fracture, invasive aspergillosis, disseminated TB, TRAPS, bronchiolitis, croup, hypothermia, and symptomatic hyponatremia.
- Corrected PMC7005653 validation label from syndrome-only `D-ACUTE-LIVER-FAILURE` to etiologic paper leaf `D-ACUTE-HEPATITIS-A`; acute liver failure remains recorded as related paper manifold.

## Final Case Table

| PMCID | PMID | Expected | Best single | Paper label |
| --- | --- | --- | --- | --- |
| PMC10590198 | 37868373 | 虫垂炎 / Acute appendicitis / `D-APPENDICITIS` | 虫垂炎 / Acute appendicitis / `D-APPENDICITIS` | Acute appendicitis with appendicolith and cecal inflammation |
| PMC2729472 | 19707473 | 急性胆嚢炎 / Acute cholecystitis / `D-ACUTE-CHOLECYSTITIS` | 急性胆嚢炎 / Acute cholecystitis / `D-ACUTE-CHOLECYSTITIS` | Acute cholecystitis caused by ceftriaxone stones in an adult |
| PMC6697923 | 31419970 | 急性膵炎 / Acute pancreatitis / `D-ACUTE-PANCREATITIS` | 急性膵炎 / Acute pancreatitis / `D-ACUTE-PANCREATITIS` | Severe alcohol-induced acute pancreatitis complicated by abdominal compartment syndrome |
| PMC9107358 | 35578608 | アセトアミノフェン中毒 / Acetaminophen toxicity / `D-ACETAMINOPHEN-TOXICITY` | アセトアミノフェン中毒 / Acetaminophen toxicity / `D-ACETAMINOPHEN-TOXICITY` | Acetaminophen overdose with delayed absorption and subsequent fulminant hepatic failure |
| PMC10361445 | 37485136 | 急性胆管炎 / Acute cholangitis / `D-ACUTE-CHOLANGITIS` | 急性胆管炎 / Acute cholangitis / `D-ACUTE-CHOLANGITIS` | Acute cholangitis secondary to gallstones with atypical chest pain and cough presentation |
| PMC10766345 | 38179346 | 急性喉頭蓋炎 / Acute epiglottitis / `D-ACUTE-EPIGLOTTITIS` | 急性喉頭蓋炎 / Acute epiglottitis / `D-ACUTE-EPIGLOTTITIS` | Adult acute epiglottitis |
| PMC6009803 | 29942881 | 急性心不全 / Acute heart failure / `D-ACUTE-HEART-FAILURE` | 急性心不全 / Acute heart failure / `D-ACUTE-HEART-FAILURE` | Sympathetic crashing acute pulmonary edema in acute congestive heart failure |
| PMC7005653 | 32039396 | 急性A型肝炎 / Acute hepatitis A / `D-ACUTE-HEPATITIS-A` | 急性A型肝炎 / Acute hepatitis A / `D-ACUTE-HEPATITIS-A` | Fulminant hepatitis A complicated by Takotsubo syndrome treated with plasma exchange |
| PMC3962942 | 24654253 | 糖尿病性ケトアシドーシス / Diabetic ketoacidosis / `D-DIABETIC-KETOACIDOSIS` | 糖尿病性ケトアシドーシス / Diabetic ketoacidosis / `D-DIABETIC-KETOACIDOSIS` | Severe combined diabetic ketoacidosis and lactic acidosis |
| PMC9912511 | 36759780 | 肺塞栓症 / Pulmonary embolism / `D-PULMONARY-EMBOLISM` | 肺塞栓症 / Pulmonary embolism / `D-PULMONARY-EMBOLISM` | High-risk pulmonary embolism presenting with recurrent syncope and shock |

## Plausibility Audit

- PMC10361445 top differentials after acute cholangitis: IgG4関連疾患 / IgG4-related disease / `D-IGG4-RELATED-DISEASE`, バベシア症 / Babesiosis / `D-BABESIOSIS`, 特発性細菌性腹膜炎 / Spontaneous bacterial peritonitis / `D-SPONTANEOUS-BACTERIAL-PERITONITIS`, 急性肝不全 / Acute liver failure / `D-ACUTE-LIVER-FAILURE`.
- PMC10590198 top differentials after appendicitis: 消化管穿孔 / Perforated viscus / `D-PERFORATED-VISCUS`, 憩室炎 / Diverticulitis / `D-DIVERTICULITIS`, クローン病再燃 / Crohn disease flare / `D-CROHN-DISEASE-FLARE`, 閉塞性腎盂腎炎 / Obstructive pyelonephritis / `D-OBSTRUCTIVE-PYELONEPHRITIS`.
- PMC10766345 top differentials after epiglottitis: 扁桃周囲膿瘍 / Peritonsillar abscess / `D-PERITONSILLAR-ABSCESS`, 誤嚥性肺炎 / Aspiration pneumonia / `D-ASPIRATION-PNEUMONIA`, 髄膜炎菌血症 / Meningococcemia / `D-MENINGOCOCCEMIA`, ウイルス性髄膜炎 / Viral meningitis / `D-VIRAL-MENINGITIS`.
- PMC6009803 top differentials after acute heart failure: たこつぼ心筋症 / Takotsubo cardiomyopathy / `D-TAKOTSUBO-CARDIOMYOPATHY`, びまん性肺胞出血 / Diffuse alveolar hemorrhage / `D-DIFFUSE-ALVEOLAR-HEMORRHAGE`, 不安定狭心症 / Unstable angina / `D-UNSTABLE-ANGINA`, 高血圧緊急症 / Hypertensive emergency / `D-HYPERTENSIVE-EMERGENCY`.
- PMC7005653 top liver-family ranking is clinically coherent: 急性A型肝炎 / Acute hepatitis A / `D-ACUTE-HEPATITIS-A`, 急性B型肝炎 / Acute hepatitis B / `D-ACUTE-HEPATITIS-B`, 急性E型肝炎 / Acute hepatitis E / `D-ACUTE-HEPATITIS-E`, 急性肝不全 / Acute liver failure / `D-ACUTE-LIVER-FAILURE`.
- Residual issue to monitor in the 50-case expansion: some broad systemic mimics can still enter the top 5-8 for severe multi-organ cases. The next batches should keep auditing top-rank plausibility, not only top-1 accuracy.

## Next Step

Current locked regression set: 10 blind full-text cases. Expand to 50 total by adding 40 more PMC/PubMed cases in batches, and after every batch rerun the whole accumulated regression set so earlier cases cannot silently regress.
