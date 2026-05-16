# Blind PMC/PubMed Real-Case Regression: 15 Cases

Date: 2026-05-16

## Scope

This batch extends the blind full-text PMC/PubMed regression set from 10 to 15 real cases.

New cases added in this batch:

| PMCID | Expected validation disease_id | Source handling |
| --- | --- | --- |
| PMC4896173 | D-ACUTE-ISCHEMIC-STROKE | Full-text source notes + blind extraction |
| PMC10427782 | D-ACUTE-MYOCARDIAL-INFARCTION | Full-text source notes + blind extraction |
| PMC4509665 | D-ANAPHYLAXIS | Full-text source notes + blind extraction |
| PMC5832394 | D-ACUTE-SYMPTOMATIC-HYPONATREMIA | Full-text source notes + blind extraction |
| PMC5385992 | D-ACUTE-RESPIRATORY-DISTRESS-SYNDROME | Full-text source notes + blind extraction |

## Blind Extraction QA

Checked 15 extraction files under `tmp_blind_eval/extractions`.

Result: PASS

- Every extraction preserves source PMCID/PMID/source URL where available.
- No extraction contains `expected`, `expected_manifold`, `expected_disease`, `final_diagnosis`, or `paper_diagnosis` fields.
- No ordinary observed `axis_id` uses a diagnosis-specific `*_in_D-*` axis.
- `record_only` entries are non-rankable.

## Ranking Result

Final result file: `tmp_blind_eval/blind_pilot_15case_after_anchor_refine.txt`

Single-manifold validation: 15/15 PASS

Focused new-5 result after runtime/ontology repair: `tmp_blind_eval/blind_pilot_new5_after_runtime_fix.txt`

New-5 validation: 5/5 PASS

## Final Top-5 Snapshot

| Case | Top 5 disease_id ranking |
| --- | --- |
| PMC10361445 | D-ACUTE-CHOLANGITIS, D-IGG4-RELATED-DISEASE, D-BABESIOSIS, D-SPONTANEOUS-BACTERIAL-PERITONITIS, D-ACUTE-LIVER-FAILURE |
| PMC10427782 | D-ACUTE-MYOCARDIAL-INFARCTION, D-UNSTABLE-ANGINA, D-ACUTE-HEART-FAILURE, D-CARDIAC-TAMPONADE, D-AORTIC-DISSECTION |
| PMC10590198 | D-APPENDICITIS, D-PERFORATED-VISCUS, D-DIVERTICULITIS, D-OBSTRUCTIVE-PYELONEPHRITIS, D-AMOEBIC-LIVER-ABSCESS |
| PMC10766345 | D-ACUTE-EPIGLOTTITIS, D-PERITONSILLAR-ABSCESS, D-ASPIRATION-PNEUMONIA, D-VIRAL-MENINGITIS, D137 |
| PMC2729472 | D-ACUTE-CHOLECYSTITIS, D-ACUTE-PANCREATITIS, D-DIVERTICULITIS, D-PYOGENIC-LIVER-ABSCESS, D-ANAPHYLAXIS |
| PMC3962942 | D-DIABETIC-KETOACIDOSIS, D-HYPEROSMOLAR-HYPERGLYCEMIC-STATE, D-HEMORRHAGIC-SHOCK, D-PERFORATED-VISCUS, D-ACUTE-PANCREATITIS |
| PMC4509665 | D-ANAPHYLAXIS, D-COPD-EXACERBATION, D-ASTHMA-EXACERBATION, D-AIRWAY-FOREIGN-BODY, D-ACUTE-HEART-FAILURE |
| PMC4896173 | D-ACUTE-ISCHEMIC-STROKE, D-TRANSIENT-ISCHEMIC-ATTACK, D-CEREBRAL-VENOUS-SINUS-THROMBOSIS, D-MYASTHENIC-CRISIS, D-ACUTE-SYMPTOMATIC-HYPONATREMIA |
| PMC5385992 | D-ACUTE-RESPIRATORY-DISTRESS-SYNDROME, D-ASPIRATION-PNEUMONIA, D-PNEUMOCOCCAL-PNEUMONIA, D-SEPSIS-GN, D-PULMONARY-TUBERCULOSIS |
| PMC5832394 case 1 | D-ACUTE-SYMPTOMATIC-HYPONATREMIA, D-HYPERTENSIVE-EMERGENCY, D-ALCOHOL-WITHDRAWAL-DELIRIUM, D-OPIOID-INTOXICATION, D-ACUTE-HEART-FAILURE |
| PMC6009803 | D-ACUTE-HEART-FAILURE, D-ACUTE-RESPIRATORY-DISTRESS-SYNDROME, D-UNSTABLE-ANGINA, D-PANIC-DISORDER, D-HYPERTENSIVE-EMERGENCY |
| PMC6697923 | D-ACUTE-PANCREATITIS, D-DIABETIC-KETOACIDOSIS, D-ASPIRATION-PNEUMONIA, D-ANAPHYLAXIS, D-ACUTE-SYMPTOMATIC-HYPONATREMIA |
| PMC7005653 | D-ACUTE-HEPATITIS-A, D-ACUTE-HEPATITIS-B, D-ACUTE-HEPATITIS-E, D-ACUTE-LIVER-FAILURE, D-ACETAMINOPHEN-TOXICITY |
| PMC9107358 | D-ACETAMINOPHEN-TOXICITY, D-ACUTE-LIVER-FAILURE, D-ULCERATIVE-COLITIS-SEVERE-FLARE, D-HEMORRHAGIC-SHOCK, D-MALARIA-FALCIPARUM |
| PMC9912511 | D-PULMONARY-EMBOLISM, D-AORTIC-DISSECTION, D-ADRENAL-CRISIS, D-SARCOIDOSIS, D-GRAVES-DISEASE |

## Repairs Made

- Added missing ARDS-relevant generic observations and mechanism edges for chemical inhalation ARDS instead of encoding disease identity into case observations.
- Strengthened context/source/organism-defined disease anchors so broad mimics cannot rank high without their defining context.
- Added neutral aliases for common source-text expressions such as oxygen flow, culprit coronary obstruction, anterior ischemic ECG, bee pollen exposure, beer potomania context, and bilateral pulmonary opacity.
- Suppressed redundant qualitative parent axes when direct measured axes already exist, reducing double counting.
- Reran the growing blind real-case regression set after every focused repair.

## Residual Notes

The pass criterion here is not only top-1 correctness. The high-ranked alternatives were also reviewed as differential plausibility signals. Some lower top-5 entries remain broad rather than ideal, but no current top-5 ordering blocks the 15-case pilot.
