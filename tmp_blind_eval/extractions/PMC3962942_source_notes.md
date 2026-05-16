# PMC3962942 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC3962942/
- PMCID: PMC3962942
- PMID: 24654253
- DOI: 10.1136/bcr-2014-203594
- Browser access to the PMC page showed a reCAPTCHA interstitial.
- Full text was retrieved from the same PMC source URL using PowerShell `Invoke-WebRequest` on 2026-05-16.
- PubMed metadata for PMID 24654253 was used only to confirm PMID, PMCID, and DOI.

## Extraction Boundary

- Included for ranking: demographics, history of insulin-dependent diabetes, chronic insulin exposure, unconscious presentation, HEMS pre-treatment vital/neurologic/respiratory findings where separable, tonic-clonic seizure occurrence before antiseizure sedation, first ED metabolic labs, WBC, CRP, urea/creatinine, and ECG absence of abnormalities other than sinus tachycardia.
- Kept record-only: prehospital midazolam/propofol, intubation/ventilation, normal saline response, epinephrine boluses, ICU transfer, ICU ventilation, insulin/fluids/potassium treatment, pCO2/pO2 after ventilation, normalization within 36 hours, extubation/full neurologic recovery, and discussion-level causal framing.
- Existing local `distillations/cases` files were intentionally not read.
- No target-manifold field or paper-conclusion field was added.
- No ordinary diagnosis-specific disease-suffixed observed axes were used.
- The paper title and diagnostic framing from the abstract were not used as ranking evidence.

## Evidence Pointers

- Case presentation opening: 22-year-old male, insulin-dependent diabetes, unconscious presentation by HEMS, insulin medications, and no other medications.
- Case presentation HEMS assessment: marked Kussmaul breathing, sinus tachycardia 117 bpm, blood pressure 67/30 mmHg, GCS 1-1-1, dilated pupils unresponsive to light, otherwise unremarkable physical examination, and no evidence of systemic infection.
- Case presentation seizure/transport: tonic-clonic seizure, midazolam/propofol, intubation, ventilation, refractory hypotension after normal saline, and epinephrine boluses.
- Investigations: first arterial blood gas after ED arrival with glucose 59.0 mmol/L, pH 6.57, pCO2 3.3 kPa, bicarbonate 2.0 mmol/L, pO2 51.9 kPa, lactate 13.3 mmol/L, sodium 149 mmol/L, potassium 3.9 mmol/L; hemoglobin 7.5 mmol/L, leucocytes 41.6 x 10^9/L, CRP 1 mg/L, urea 12.5 mmol/L, creatinine 165 umol/L, and ECG normal except sinus tachycardia.
- Treatment and outcome sections: ICU transfer, mechanical ventilation, normal saline then glucose 5%, potassium supplementation, IV NovoRapid insulin, metabolic normalization within 36 hours, extubation, and full neurological recovery.

## Registry Notes

- Reused registry-compatible diagnosis-neutral axis IDs where available: `diabetes_mellitus_presence`, `exogenous_insulin_exposure_context_presence`, `altered_mental_status_presence`, `coma_presence`, `glasgow_coma_scale_score`, `kussmaul_respiration_presence`, `sinus_tachycardia_presence`, `heart_rate`, `hypotension_presence`, `systolic_blood_pressure`, `diastolic_blood_pressure`, `mean_arterial_pressure`, `pupillary_abnormality_presence`, `pupillary_light_reaction_impairment_presence`, `fixed_dilated_pupil_presence`, `active_infection_evidence_activity`, `seizure_presence`, `generalized_tonic_clonic_seizure_presence`, `blood_glucose`, `arterial_pH`, `serum_bicarbonate`, `metabolic_acidosis_presence`, `serum_lactate`, `lactic_acidosis_presence`, `serum_sodium`, `serum_potassium`, `hemoglobin`, `white_blood_cell_count`, `serum_crp`, `blood_urea_nitrogen`, and `serum_creatinine`.
- Suggested neutral axis ID used because no exact registry match was found during extraction: `ecg_other_abnormality_presence`.
- No disease-suffixed ordinary observed axes were used.

## Unit And Timing Notes

- Glucose was reported as `59.0 mmol/L`; JSON stores `1063 mg/dL` with original value preserved.
- Hemoglobin was reported as `7.5 mmol/L`; JSON stores `12.1 g/dL` with original value preserved.
- Urea was reported as `12.5 mmol/L`; JSON stores BUN-equivalent `35.0 mg/dL` with original value preserved.
- Creatinine was reported as `165 umol/L`; JSON stores `1.87 mg/dL` with original value preserved.
- pCO2 `3.3 kPa` and pO2 `51.9 kPa` were not ranked because they were measured after intubation and ventilation.
- No ketone value, chloride, anion gap, respiratory rate, temperature, oxygen saturation, HbA1c, cultures, urine studies, or imaging findings were reported in the case text.
