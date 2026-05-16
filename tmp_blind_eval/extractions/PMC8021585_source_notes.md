# PMC8021585 Blind Extraction Source Notes

## Access
- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC8021585/
- PMCID: PMC8021585
- PMID: 33795268
- DOI: 10.1136/bcr-2020-239110
- Browser access through the web tool showed a reCAPTCHA interstitial.
- Direct HTTP access to the PMC HTML succeeded and was used for full-text extraction.
- NCBI EFetch XML was checked; it returned metadata and the notice that the publisher does not allow full-text XML download.

## Extraction Boundary
- Included for ranking: demographics, chronic risk context, 5-day presentation symptoms, vital signs at emergency surgical referral, abdominal/rectal/chest exam findings, initial ED/referral labs, and contrast CT abdomen/pelvis findings.
- Kept record-only: article title, prior clinician differential labels, antibiotic discharge context, repeated post-snapshot laboratory deterioration, clinician diagnostic hypotheses, treatment, operative findings, pathology, recovery, follow-up, and discussion-level epidemiology/prognosis.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field or final diagnosis field was added.
- No ordinary diagnosis-specific disease-suffixed observed axes were used.

## Evidence Pointers
- Case presentation paragraph 1: age, sex, former smoking history, hypothyroidism, hypercholesterolemia, 5-day gradually worsening abdominal pain, blood-stained diarrhoea, and coffee-ground vomiting.
- Case presentation paragraph 2: blood pressure, heart rate, confusion, agitation, GCS 14/15, abdominal distension, guarding, generalized tenderness, sluggish bowel sounds, altered blood on digital rectal exam, and unremarkable chest exam.
- Investigations paragraph 1: WCC 18.3 x 10^9/L, CRP 135 mg/L, lactate 3.36 mmol/L, urea 8.7 mmol/L, normal serum creatinine, and normal liver function tests.
- Investigations paragraph 2 and Figures 1-3: long-segment thrombotic occlusion of the superior mesenteric vein, extension to proximal portal vein, CT findings consistent with significant acute small bowel ischemia, and no obvious intramural gas.
- Investigations final paragraph: repeated WCC, CRP, creatinine, urea, AST, albumin, and ammonia deterioration retained as record-only because it is described after the initial diagnostic imaging/workup.
- Differential diagnosis, Treatment, Outcome/follow-up, and Discussion sections: clinician labels, treatment course, surgery, pathology, recovery, and discussion retained as record-only.

## Registry Notes
- Used diagnosis-neutral generic axis IDs only, including `abdominal_pain_presence`, `diarrhea_presence`, `bloody_diarrhea_presence`, `vomiting_presence`, `coffee_ground_emesis_presence`, `systolic_blood_pressure`, `diastolic_blood_pressure`, `heart_rate`, `confusion_presence`, `glasgow_coma_scale`, `abdominal_distension_presence`, `abdominal_guarding_presence`, `generalized_abdominal_tenderness_presence`, `decreased_bowel_sounds_presence`, `rectal_blood_presence`, `white_blood_cell_count`, `c_reactive_protein`, `serum_lactate`, `blood_urea`, and `intramural_bowel_gas_presence`.
- Vessel/anatomy-specific imaging axes were kept generic and not disease-suffixed: `superior_mesenteric_vein_thrombotic_occlusion_presence`, `long_segment_venous_thrombus_presence`, `portal_vein_thrombus_extension_presence`, and `acute_small_bowel_ischemia_ct_presence`.
- Relevant negative findings were represented as neutral absent/present axes where the article provided explicit negatives: normal initial creatinine, normal initial liver function tests, unremarkable chest exam, and absence of obvious intramural gas.

## Ambiguities
- The article does not provide initial temperature, respiratory rate, oxygen saturation, platelet count, coagulation studies, or exact initial creatinine/liver-function values.
- The repeated laboratory panel appears after the initial CT diagnosis/workup narrative; it was retained as `record_only` to avoid mixing post-snapshot deterioration into blind ranking.
- The article's title and CT wording are diagnostically explicit. The title is record-only; the CT findings were retained for ranking because they are source-observed diagnostic workup facts, expressed with diagnosis-neutral axis IDs.
