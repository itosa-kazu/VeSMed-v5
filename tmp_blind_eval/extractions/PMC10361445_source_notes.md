# PMC10361445 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC10361445/
- PMCID: PMC10361445
- PMID: 37485136
- DOI: 10.7759/cureus.40747
- Browser access to the interactive PMC page was blocked by a reCAPTCHA interstitial in the browser tool.
- Full text was retrieved as PMC JATS XML through NCBI/PMC OAI:
  `https://www.ncbi.nlm.nih.gov/pmc/oai/oai.cgi?verb=GetRecord&identifier=oai:pubmedcentral.nih.gov:10361445&metadataPrefix=pmc`

## Extraction Boundary

- Included for ranking: initial presentation symptoms, vital signs, physical exam, initial labs, chest x-ray, EKG/troponin, and pre-treatment abdominal CT findings.
- Kept record-only: article diagnostic interpretation, sepsis protocol, antibiotics, fluids, blood culture result reported after treatment initiation, ERCP findings/procedures, stent placement, discharge medications, repeat ERCP, response to treatment, late follow-up outcome, and discussion-level causal/severity framing.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field or final diagnosis field was added.
- No ordinary diagnosis-specific disease-suffixed observed axes were used.

## Evidence Pointers

- Case presentation paragraph 1: age/sex, osteoporosis and hypothyroidism history, right-sided lower chest pain, dry cough, 20-minute cough episode, afebrile status, heart rate, respiratory rate, blood pressure, and oxygen saturation on room air.
- Case presentation paragraph 2: diaphoresis, acute distress, scleral icterus, yellow skin, normal chest inspection, absent focal chest tenderness, no murmur/S3, tachycardic regular rhythm, equal bilateral breath sounds without rales/crackles, nondistended abdomen without localized tenderness, WBC, neutrophil fraction, bandemia, bilirubin, ALP, AST, ALT, lipase, GGT, negative CXR, sinus tachycardia, and repeatedly negative high-sensitivity troponin.
- Case presentation paragraph 3 and Figure 1 caption: CT abdomen with marked common bile duct dilation, non-radiopaque calculus, and incomplete biliary obstruction.
- Case presentation paragraph 3 and Figure 2 caption: diagnosis, sepsis protocol, antibiotics/fluids, Klebsiella variicola bacteremia, ERCP stones, stone extraction, stent placement, clinical response, discharge medications, repeat ERCP, and late normalized jaundice/labs retained as record-only.
- Discussion paragraphs: causal explanation for cough/chest pain and Tokyo Guidelines grade-two framing retained as record-only.

## Registry Notes

- Reused registry axis IDs where exact or close diagnosis-neutral matches existed, including `chest_pain_presence`, `cough_presence`, `nonproductive_cough_activity`, `fever_presence`, `heart_rate`, `respiratory_rate`, `systolic_blood_pressure`, `diastolic_blood_pressure`, `mean_arterial_pressure`, `oxygen_saturation`, `diaphoresis_presence`, `jaundice_presence`, `scleral_icterus_presence`, `cardiac_murmur_presence`, `sinus_tachycardia_presence`, `crackles_presence`, `abdominal_distension_presence`, `abdominal_tenderness_presence`, `white_blood_cell_count`, `neutrophil_fraction`, `band_neutrophil_fraction`, `serum_bilirubin_total`, `serum_bilirubin_direct`, `serum_alkaline_phosphatase`, `aspartate_aminotransferase`, `alanine_aminotransferase`, `serum_lipase`, `gamma_glutamyl_transferase`, `pulmonary_infiltrate_presence`, `pulmonary_consolidation_presence`, `troponin_normal_or_no_dynamic_rise_presence`, `biliary_obstruction_activity`, and `common_bile_duct_diameter_mm`.
- Suggested generic axis IDs were used where an exact neutral registry ID was not found: `right_sided_chest_pain_presence`, `lower_chest_pain_location_presence`, `acute_distress_presence`, `chest_wall_abnormal_inspection_presence`, `chest_wall_tenderness_presence`, `third_heart_sound_presence`, `chest_xray_acute_cardiopulmonary_abnormality_presence`, `common_bile_duct_calculus_presence`, and `incomplete_biliary_obstruction_presence`.

## Ambiguities

- WBC is printed as `25.4/mm3`; the extraction stores `25.4` as `10^3/uL` because the clinical magnitude and accompanying neutrophilia/bandemia imply leukocytosis rather than 25.4 cells/mm3.
- Common bile duct size is reported as `2.9cm` in the case text and `28mm` in Figure 1; the extraction stores 29 mm and notes the caption discrepancy.
- No exact body temperature is provided despite the word `afebrile`.
- No blood culture draw time relative to antibiotics is stated; the culture result appears after treatment initiation in the narrative, so it is record-only.
