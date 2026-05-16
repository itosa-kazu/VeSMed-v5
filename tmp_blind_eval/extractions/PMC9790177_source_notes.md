# PMC9790177 Blind Extraction Source Notes

## Source

- PMCID: PMC9790177
- PMID: 36536587
- DOI: 10.12659/AJCR.936752
- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC9790177/
- Title: Failure of Computed Tomography (CT) in Detecting an Aspirin Pharmacobezoar: A Case Report
- Journal: The American Journal of Case Reports
- Publication date: 2022-12-20

## Blinding Scope

- The JSON does not include atlas labels, target manifold identifiers, or paper-diagnosis-as-target fields.
- Ordinary clinical findings use diagnosis-neutral reusable axes only.
- Article framing, final assessment, treatments, treatment response, later endoscopy, late complications, and death are stored under `record_only` with `use_in_ranking: false`.
- Rankable facts are restricted to the patient demographics, risk context, initial ED symptoms, vital signs, initial labs, early ECG, initial chest X-ray, initial nasogastric findings, and initial head CT.

## Rankable Source Facts Used

- Abstract: patient was a 64-year-old female.
- Case Report: EMS brought the patient after reported intentional aspirin ingestion; she reported dyspnea and denied abdominal pain, vomiting, and nausea.
- Case Report: initial vitals were respiratory rate 22/min, heart rate 99/min, blood pressure 109/84 mmHg, and temperature 37.4 C.
- Case Report: GCS was 15, with inattentive behavior, blunted affect, and poor understanding of why she was at the hospital.
- Case Report: initial salicylate was 1143 mcg/mL, anion gap 23, serum bicarbonate 9 mEq/L, VBG pH 7.44 and pCO2 16.
- Case Report: respiratory alkalosis and metabolic acidosis were explicitly stated.
- Case Report: ABG values included pH 7.45, pCO2 23, pO2 250, and bicarbonate 19.
- Case Report: initial renal function and liver enzymes were normal; ethanol and acetaminophen were undetectable; lactate was normal; ammonia was 17 mcmol/L; urine drug screen was positive for benzodiazepines.
- Case Report: initial ECG was normal sinus rhythm with normal QRS and QTc intervals.
- Case Report: initial chest X-ray was normal, nasogastric tube returned dark-brown gastric contents without pill fragments, and initial head CT showed no acute intracranial abnormalities.

## Record-Only Facts Captured

- Initial and subsequent treatments: bicarbonate/glucose infusion, activated charcoal, intubation, hemodialysis, CRRT, whole-bowel irrigation, endoscopy, and gastric lavage.
- Salicylate trend after interventions: fall to 400 mcg/mL, rebound to 694 mcg/mL, rebound to 1005 mcg/mL, later values above 400 mcg/mL, and continuous decline after second endoscopy/lavage.
- Day 3 CT abdomen/pelvis findings: bibasilar pneumonia concerning for aspiration, small ascites, distended gallbladder with mild biliary ductal distention, and no gastric foreign body.
- Endoscopy findings: red blood in stomach, packet/paper wrapped around pills measuring 8-10 cm, charcoal, and additional pill remnants.
- Late complications/course: MSSA pneumonia, encephalopathy, coagulopathy, oliguria with acute kidney injury, concern for toxic tubular necrosis, palliative care, extubation, and death.

## Caveats

- The article text gives ammonia as 17 mcmol/L; JSON normalizes this to `micromol_per_L` while preserving the source wording.
- The article reports activated charcoal as 50 mg every 4 hours, which is transcribed into record_only as stated.
- Late kidney injury is not treated as an initial rankable renal abnormality because the initial comprehensive metabolic panel stated normal renal function.
