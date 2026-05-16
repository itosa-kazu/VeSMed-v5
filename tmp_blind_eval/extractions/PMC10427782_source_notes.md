# PMC10427782 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC10427782/
- PMCID: PMC10427782
- PMID: 37593269
- DOI: 10.7759/cureus.41983
- Browser access to the interactive PMC page was blocked by a reCAPTCHA interstitial in the browser tool.
- Full text was retrieved as PMC JATS XML through NCBI/PMC OAI:
  `https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi?verb=GetRecord&identifier=oai:pubmedcentral.nih.gov:10427782&metadataPrefix=pmc`

## Extraction Boundary

- Included for ranking: age/sex, diabetes history, initial symptoms and duration, initial blood glucose, initial blood pressure/shock physiology, ECG finding as reported in the case section, elevated cardiac biomarkers, oxygen saturation with oxygen-flow context, echocardiography, and coronary angiography before revascularization.
- Kept record-only: author diagnostic labels/framing, norepinephrine, oxygen as treatment, IABP, PCI setup, intra-procedural arrhythmia/asystole/CPR/intubation/temporary pacing, predilatation, thrombosuction, intracoronary medications, stenting, post-intervention TIMI flow, LCx chronic-total-occlusion interpretation after procedure, hemodynamic improvement, ICU support course, discharge medications, follow-up outcome, and discussion-level causal/prognostic framing.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field or final diagnosis field was added.
- No ordinary diagnosis-specific disease-suffixed observed axes were used.

## Evidence Pointers

- Case presentation paragraph 1: 60-year-old man, diabetes for four years, severe retrosternal chest pain, difficulty breathing, orthopnea, 10-hour duration, blood glucose 140 mg/dL, blood pressure 72/38 mmHg, and ECG interpreted as anterior-wall acute MI.
- Case presentation paragraph 2: elevated cardiac troponin T and NT-proBNP, norepinephrine/oxygen given, oxygen saturation 94% on 6 L/min oxygen, echocardiographic severe LAD-territory hypokinesia, EF 20%, no mechanical complications, and coronary angiography showing total thrombotic LMCA occlusion.
- Case presentation paragraph 3: right-dominant circulation, normal right coronary artery, collateral supply to left system, and Rentrop grade 1.
- Case presentation paragraphs 4-6 and Figures 4-5: IABP, PCI setup, intra-procedural ventricular tachycardia/asystole/CPR/intubation/TPI, ballooning, thrombosuction, intracoronary medications, drug-eluting stent, TIMI flow results, post-procedure improvement, discharge, and follow-up retained as record-only.
- Discussion and conclusion: general causal, prognostic, and management framing retained as record-only only.

## Registry Notes

- Reused or aligned with existing diagnosis-neutral axis IDs where available: `diabetes_mellitus_presence`, `blood_glucose`, `chest_pain_presence`, `dyspnea_presence`, `orthopnea_presence`, `shock_presence`, `hypotension_presence`, `systolic_blood_pressure`, `diastolic_blood_pressure`, `mean_arterial_pressure`, `oxygen_saturation`, `supplemental_oxygen_flow_rate`, `left_ventricular_systolic_dysfunction_presence`, `left_ventricular_ejection_fraction`, `regional_wall_motion_abnormality_presence`, `regional_wall_motion_abnormality_severity`, and `coronary_occlusion_presence`.
- Suggested generic axis IDs were used where an exact neutral registry ID was not confirmed: `diabetes_duration_years`, `retrosternal_chest_pain_presence`, `chest_pain_duration_hours`, `dyspnea_duration_hours`, `ecg_anterior_wall_acute_ischemic_pattern_presence`, `troponin_t_elevated_presence`, `nt_pro_bnp_elevated_presence`, `left_anterior_descending_territory_wall_motion_abnormality_presence`, `cardiac_mechanical_complication_presence`, `left_main_coronary_artery_occlusion_presence`, `coronary_thrombus_presence`, `right_coronary_artery_abnormality_presence`, `right_dominant_coronary_circulation_presence`, `coronary_collateral_flow_presence`, and `rentrop_collateral_grade`.

## Ambiguities

- The case body states that ECG suggested anterior-wall acute MI but does not provide exact ST-segment measurements or involved leads. The extraction encodes this as a neutral acute ischemic ECG-pattern axis and does not add a final-diagnosis label.
- The source uses the term `CS`; for rankable observations this was reduced to generic shock/hypotension plus objective blood pressure. The etiologic cardiogenic framing is record-only.
- Troponin T and NT-proBNP are only described as elevated; no numeric values or reference ranges are reported.
- Oxygen saturation was measured on 6 L/min oxygen after oxygen had already been administered; no room-air saturation is available.
- Coronary angiography is a diagnostic test rather than treatment response, so the pre-revascularization LMCA occlusion and thrombus findings were kept rankable. PCI details and post-intervention TIMI results were kept record-only.
- No heart rate, respiratory rate, temperature, lactate, pH, creatinine, CBC, electrolytes, CRP, or detailed physical examination findings are provided in the case body.
