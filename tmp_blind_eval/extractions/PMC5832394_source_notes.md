# PMC5832394 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC5832394/
- PMCID: PMC5832394
- PMID: 29507848
- DOI: 10.7759/cureus.2000
- Browser access to the interactive PMC page returned a reCAPTCHA interstitial on 2026-05-16.
- Full text was retrieved as PMC JATS XML through PMC OAI-PMH:
  `https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/?verb=GetRecord&identifier=oai:pubmedcentral.nih.gov:5832394&metadataPrefix=pmc`

## Extraction Boundary

- This article contains two case vignettes. The JSON file extracts Case 1 only to preserve the existing single-case demographics and snapshot structure used by current `tmp_blind_eval/extractions` examples.
- Included for ranking: Case 1 demographics, chronic exposure/risk context, ED presentation symptoms and negative review-of-systems facts, initial physical examination, Table 1 laboratory/urine-screen findings, toxicology, chest x-ray, echocardiogram, head CT, and early objective urine osmolality/sodium values.
- Kept record-only: article title/abstract diagnostic framing, Case 2 scope, treatment, treatment response, diagnostic interpretations, sodium correction after saline/D5W, later outcome, education, and discussion-level pathophysiology/management framing.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field, paper diagnosis label field, final diagnosis field, or ordinary disease-specific observed axis was added.

## Evidence Pointers

- Case presentation, Case 1 history paragraph: age/sex; seizure earlier that day; negative fall/head trauma; chronic alcohol and beer intake; poor diet; smoking; COPD/seizure/mood disorder history; home trazodone, risperidone, phenytoin; negative intravenous drug use, travel, hepatitis history, excessive water intake, diarrhea, vomiting, temperature intolerance, edema, headache, cough, hemoptysis, chest pain, fever, night sweats, and weight loss.
- Case presentation, Case 1 physical paragraph: malnourished and lethargic appearance; respiratory distress; BP 127/83, HR 110, RR 20, room-air oxygen saturation 85%, no fever, BMI 16; normal pupils; euvolemic appearance; no murmurs/gallops; wheezing, rhonchi, and decreased breath sounds; epigastric tenderness without rebound; no organomegaly; disorientation to time, confusion, normal deep tendon reflexes, no tremor/asterixis, GCS 14.
- Case presentation, Table 1: initial ED CBC, chemistry, liver tests, INR, TSH, serum osmolality, urine specific gravity, and trace urine ketones.
- Case presentation, Case 1 hospital course paragraph: urine toxicology positive for cannabinoids and opioids; chest x-ray unremarkable; echocardiogram with mild ventricular hypertrophy and no diastolic dysfunction; non-contrast head CT with cerebral atrophy and no acute changes.
- Case presentation, Case 1 diagnostic workup paragraph: urine osmolality 72 mOsm/kg H2O and urine sodium 19 mmol/L were extracted as objective course observations; the article's interpretation of these values is record-only.

## Registry And Unit Notes

- Reused registry-compatible diagnosis-neutral axis IDs where available, including `chronic_heavy_alcohol_use_presence`, `chronic_alcohol_exposure_duration_years`, `low_solute_intake_context_presence`, `poor_oral_intake_presence`, `known_copd_presence`, `smoking_context_presence`, `intravenous_drug_use_exposure_activity`, `recent_travel_exposure_presence`, `ssri_snri_or_antipsychotic_exposure_presence`, `seizure_presence`, `fall_presence`, `head_trauma_exposure_presence`, `diarrhea_presence`, `vomiting_presence`, `lower_extremity_edema_presence`, `headache_presence`, `cough_presence`, `hemoptysis_presence`, `chest_pain_presence`, `fever_presence`, `night_sweats_presence`, `unintentional_weight_loss_presence`, `malnutrition_presence`, `lethargy_presence`, `respiratory_distress_presence`, `systolic_blood_pressure`, `diastolic_blood_pressure`, `heart_rate`, `respiratory_rate`, `hypoxemia_presence`, `oxygen_saturation`, `body_mass_index`, `pupillary_light_reaction_impairment_presence`, `clinical_euvolemia_presence`, `cardiac_murmur_presence`, `wheezing_presence`, `rhonchi_presence`, `decreased_breath_sounds_presence`, `disorientation_presence`, `confusion_presence`, `tremor_presence`, `asterixis_presence`, `glasgow_coma_scale_score`, `white_blood_cell_count`, `hemoglobin`, `hematocrit`, `platelet_count`, `serum_sodium`, `serum_potassium`, `serum_chloride`, `serum_bicarbonate`, `blood_urea_nitrogen`, `serum_creatinine`, `serum_glucose`, `serum_calcium`, `serum_phosphate`, `serum_magnesium`, `aspartate_aminotransferase`, `alanine_aminotransferase`, `serum_total_protein`, `serum_albumin`, `serum_alkaline_phosphatase`, `serum_bilirubin_total`, `serum_bilirubin_direct`, `coagulation_inr`, `serum_uric_acid`, `thyroid_stimulating_hormone`, `serum_osmolality`, `urine_specific_gravity`, `urine_ketone_activity`, `opioid_exposure_presence`, `urine_osmolality`, and `urine_sodium`.
- Suggested neutral axis IDs were used where exact registry matches were not found or were too disease-framed: `daily_beer_intake_cans`, `seizure_disorder_history_presence`, `mood_disorder_history_presence`, `cigarette_smoking_pack_years`, `hepatitis_history_presence`, `antiseizure_drug_exposure_presence`, `excessive_free_water_intake_presence`, `temperature_intolerance_presence`, `cardiac_gallop_presence`, `epigastric_tenderness_presence`, `rebound_tenderness_presence`, `bowel_movement_abnormality_presence`, `organomegaly_presence`, `disorientation_to_time_presence`, `deep_tendon_reflex_abnormality_presence`, `urine_cannabinoid_screen_positive_presence`, `chest_xray_abnormality_presence`, `left_ventricular_hypertrophy_presence`, `diastolic_dysfunction_presence`, `brain_ct_cerebral_atrophy_presence`, and `acute_intracranial_ct_abnormality_presence`.
- WBC and platelet values reported as x10^3/uL were stored as numerically equivalent x10^9/L.
- Serum osmolarity was stored under `serum_osmolality` because the source unit is mOsm/kg.
- Trace urine ketones were mapped to `urine_ketone_activity = 0.2`.
- Urine osmolality and urine sodium timing is imperfect: the article states they were not checked in the ED and later reports values before giving its diagnostic interpretation, but the exact timing relative to saline exposure is not fully specified.
