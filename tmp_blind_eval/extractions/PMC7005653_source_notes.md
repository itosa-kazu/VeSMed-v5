# PMC7005653 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC7005653/
- PMCID: PMC7005653
- PMID: 32039396
- DOI: 10.1016/j.jhepr.2019.10.004
- Browser access to the interactive PMC page showed a reCAPTCHA interstitial.
- Full text was retrieved as PMC JATS XML through PMC OAI-PMH:
  `https://pmc.ncbi.nlm.nih.gov/api/oai/v1/mh/?verb=GetRecord&identifier=oai:pubmedcentral.nih.gov:7005653&metadataPrefix=pmc`
- NCBI OA utility also confirmed an open-access record for PMC7005653.

## Extraction Boundary

- Included for ranking: age/sex, baseline health, pre-transfer and ICU-admission symptoms/labs, admission physical exam, abdominal ultrasound, initial ECG/echo/troponin status, liver biopsy component findings, and ICU day 2 objective pre-salvage-therapy deterioration.
- Kept record-only: article title/abstract diagnostic framing, serology-based etiologic interpretation, biopsy interpretation label, intubation/sedation, transplant evaluation, named cardiac syndrome framing, vasoactive treatment, plasma exchange, treatment response, late outcome, and discussion-level causal explanations.
- Existing local `distillations/cases` files were intentionally not read.
- No expected disease metadata or paper diagnosis label field was added.
- No ordinary diagnosis-specific disease-suffixed observed axes were used.

## Evidence Pointers

- Case report paragraph 1: 61-year-old woman, healthy baseline, one week of asthenia and nausea, outside-institution AST/ALT, bilirubin, INR, immediate transfer, hemodynamic stability, absent encephalopathy, jaundice, no other exam abnormalities, no recent travel, sexual risk behavior, or drug use.
- Case report paragraph 1: ICU-admission AST, ALT, GGT, alkaline phosphatase, total bilirubin, INR, ammonia, normal abdominal ultrasound, normal ECG, EF 52%, normal troponin I, and biopsy components.
- Fig. 1 caption: liver biopsy cholestasis/necroinflammation/periportal necrosis components and ventriculography/coronariography components.
- Case report paragraph 1: HCV/HBV/HEV/HIV negative and IgM anti-HAV positive were retained record-only because they directly identify etiology.
- Case report paragraph 2: ICU day 2 encephalopathy grade IV, AST, ALT, bilirubin, INR, ammonia, transcranial Doppler pulsatility index 1.5 to 1.8, ST-segment depression V1-V6, troponin I 11.19 ng/mL, EF 32%, regional hypokinesia, normal coronary arteries, and hypotension.
- Case report paragraph 2 and Fig. 2 caption: intubation, sedation, transplant evaluation, vasoactive drugs, plasma exchange, treatment response, extubation, ward transfer, and outcome were kept record-only.
- Discussion: epidemiologic, prognostic, and mechanism claims were not used as ranking evidence.

## Registry Notes

- Reused registry or already established diagnosis-neutral axis IDs where exact or close matches existed: `malaise_presence`, `nausea_presence`, `jaundice_presence`, `shock_presence`, `hepatic_encephalopathy_presence`, `acute_hepatocellular_injury_presence`, `aspartate_aminotransferase`, `alanine_aminotransferase`, `gamma_glutamyl_transferase`, `serum_alkaline_phosphatase`, `serum_bilirubin_total`, `coagulopathy_presence`, `coagulation_inr`, `hepatic_synthetic_failure_presence`, `serum_ammonia`, `left_ventricular_ejection_fraction`, `left_ventricular_systolic_dysfunction_presence`, `troponin_normal_or_no_dynamic_rise_presence`, `hepatic_encephalopathy_grade`, `raised_intracranial_pressure_sign_presence`, `st_segment_depression_presence`, `troponin_i`, `regional_wall_motion_abnormality_presence`, `regional_wall_motion_abnormality_severity`, `coronary_occlusion_presence`, and `hypotension_presence`.
- Suggested generic axis IDs were used where no exact neutral registry ID was found: `previously_healthy_context_presence`, `recent_travel_exposure_presence`, `sexual_risk_behavior_history_presence`, `drug_use_history_presence`, `extrahepatic_physical_exam_abnormality_presence`, `abdominal_ultrasound_abnormality_presence`, `ecg_abnormality_presence`, `hepatic_cholestasis_presence`, `hepatic_necroinflammation_presence`, `periportal_hepatic_necrosis_presence`, `transcranial_doppler_pulsatility_index`, `st_segment_depression_distribution_anterior_precordial_presence`, and `mid_ventricular_hypokinesia_presence`.

## Ambiguities

- The source uses `IU/L` for aminotransferases, GGT, and alkaline phosphatase. The extraction stores these as `U/L`, treating IU/L and U/L as equivalent for these enzymes.
- The source reports ammonia using a micro symbol; the extraction stores `umol/L` for ASCII compatibility.
- Transcranial Doppler pulsatility index was reported as `1.5 to 1.8`; the JSON stores midpoint `1.65` while preserving the source range.
- No exact blood pressure, heart rate, respiratory rate, temperature, or oxygen saturation values were reported at admission or day 2.
- The exact numeric value of the initial normal troponin I was not provided.
- The source gives qualitative physical examination and hemodynamic descriptions; no granular extrahepatic examination values were available.
