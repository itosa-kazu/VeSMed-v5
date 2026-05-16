# PMC6697923 Blind Source Notes

Source: https://pmc.ncbi.nlm.nih.gov/articles/PMC6697923/

PMCID: PMC6697923
PMID: 31419970
DOI: 10.1186/s12893-019-0575-8
Accessed: 2026-05-16 via NCBI PMC OAI JATS XML.

## Blind Boundary

- The article title and final clinical framing are visible in the source but are not used as ranking evidence.
- The extraction file intentionally has no `expected_manifold`, `expected_manifolds`, or `disease_label_per_paper`.
- Surgery, treatment, final interpretation, post-treatment improvement, later course, and outcome are record-only.
- Rankable facts use generic observed axes only. No disease-specific `*_in_D-*` observation axes were used.

## Rankable Case Facts Used

- 38-year-old Sri Lankan man.
- One day of severe constant abdominal pain radiating to the left shoulder with severe vomiting.
- Background: chronic heavy alcohol intake, recent 500 ml spirits binge 3 days before presentation, chronic liver disease attributed to alcohol, smoking, schizophrenia, obesity, and previous intravenous drug use.
- Negative background facts: no known alcoholic cardiomyopathy or neuropathy reported.
- ED arrival: GCS 15, afebrile, blood pressure 140/95 mmHg, heart rate 90/min, oxygen saturation 94% on room air.
- Abdominal exam: overt distension without tense abdomen, generalized tenderness, no peritoneal signs.
- Initial labs: lipase 7111 U/L, WBC 16 x10^9/L, lactate 2.9 mmol/L, hematocrit 0.54, ALT 222 U/L, ALP 124 U/L, GGT 457 U/L, creatinine 124 with unit not printed in article text.
- Initial CT: pancreatic inflammatory findings reported at high level; no ascites.
- Early deterioration before surgery: pale and diaphoretic appearance, respiratory distress, heart rate 150/min, lactate 3.3 mmol/L, potassium 5.5 mmol/L, hematocrit 0.56, hemoglobin 200 with unit not printed in article text, abdomen distended and firm but not tense.
- Pre-laparotomy ICU state: desaturation, increased work of breathing, agitation, invasive ventilation requirement, difficult ventilation with poor compliance, tidal volume under 200 ml at driving pressure 15 and PEEP 15, PaO2 74 mmHg on FiO2 1.0, pH 6.90, pCO2 120 mmHg, HCO3 23 mEq/L.
- Chest x-ray before surgery: mild bibasal collapse and edema, without radiographic ARDS evidence.
- Hemodynamic and renal severity before surgery: vasopressor requirement to maintain MAP, noradrenaline 45 mcg/min, vasopressin 2 mcg/min, oliguria under 10 ml/h, potassium 6.5 mmol/L.
- Trans-bladder intra-abdominal pressure: 28 mmHg.

## Record-Only Facts

- Paper title/final framing and discussion-level disease interpretation.
- Initial treatments: analgesia, anti-emetics, and intravenous fluids.
- Treatment response or nonresponse: persistent severe pain despite opioids, persistent tachycardia despite fluids.
- Prognostic score: modified Glasgow-Imrie score of six.
- Airway procedure and post-induction PEA arrest/CPR sequence.
- Bedside echo interpretation excluding hypovolemic, cardiogenic, or obstructive shock.
- Emergency decompressive laparotomy.
- Immediate post-laparotomy improvement in pulmonary compliance, pressor requirement, and blood gas.
- Operative findings: approximately 1 L ascitic fluid, retroperitoneal edema, edematous pancreas, no organ necrosis.
- Postoperative CRRT, feeding, extubation, antimicrobial treatment, later pancreatic necrosis/collections, endoscopic drainage, delayed wound closure, prolonged hospitalization, and recovery.

## Quality Notes

- Creatinine and hemoglobin units are omitted in the text. The JSON records converted values with source-original notes: creatinine treated as presumed umol/L and hemoglobin as presumed g/L.
- The initial CT description is not granular, so the JSON does not invent detailed pancreas CT morphology beyond generic pancreatic inflammatory imaging activity and absence of ascites.
- Intra-abdominal pressure is kept as a measured generic pressure axis, not as a diagnostic label.
- Objective support requirements before surgery are included as severity observations; later response to those interventions is record-only.
