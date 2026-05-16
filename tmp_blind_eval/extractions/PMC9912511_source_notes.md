# PMC9912511 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC9912511/
- PMCID: PMC9912511
- PMID: 36759780
- DOI: 10.1186/s12872-023-03096-z
- Browser access to the interactive PMC page returned a reCAPTCHA interstitial on 2026-05-16.
- Metadata was confirmed through NCBI PubMed ESummary for PMID 36759780.
- Full text was retrieved as PMC JATS XML through NCBI EFetch:
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=PMC9912511&retmode=xml`

## Extraction Boundary

- Included for ranking: objective presentation and admission facts from Case presentation Par7-Par8, plus objective May 8-9 course facts before thrombolysis from Par9-Par11.
- Kept record-only: article-title diagnostic framing, initial/interim/final diagnostic interpretations, neurologic/antiplatelet treatment, enoxaparin, rt-PA thrombolysis, rivaroxaban, post-treatment CTA improvement, discharge course, delayed cerebral hemorrhage, mannitol response, rivaroxaban discontinuation, and discussion-level causal/management framing.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field, paper diagnosis label field, final diagnosis field, or ordinary diagnosis-specific observed axis was added.

## Evidence Pointers

- Case presentation Par7: age/sex, syncope with gait disturbance on May 5, absence of chest distress/chest pain/dyspnea, hypertension, nifedipine use, prior cerebral infarction without sequelae, and no other disease history.
- Case presentation Par8: admission vital signs and physical exam, ECG anterior-wall T-wave change, lung HRCT fibrous cords, MRA suspected small left posterior cerebral artery aneurysm without cerebrovascular stenosis, EF 60%, D-dimer 0.44, BNP 46, and troponin 0.12.
- Case presentation Par9: recurrent syncope with palpitation on May 8, ST-T changes, CRP 5.9, D-dimer 0.46, BNP 70, troponin 0.12, and creatine kinase isozyme 2.6.
- Case presentation Par10: May 9 shock, BP 87/60, ST-T changes, D-dimer 6.19, creatine kinase isozyme 9.4, troponin 0.97, EF 65%, pulmonary hypertension, and bilateral lower-leg inter-muscular venous thrombosis.
- Case presentation Par11 and Figure captions: CTPA objective filling-defect evidence before thrombolysis; rt-PA, post-treatment CTA response, rivaroxaban, discharge, delayed cerebral hemorrhage, mannitol response, and anticoagulant discontinuation kept record-only.

## Registry And Unit Notes

- Reused registry axis IDs where exact or close diagnosis-neutral matches existed, including `syncope_presence`, `gait_disturbance_presence`, `chest_pain_presence`, `dyspnea_presence`, `heart_rate`, `systolic_blood_pressure`, `diastolic_blood_pressure`, `lower_extremity_edema_presence`, `neurologic_exam_abnormality_presence`, `left_ventricular_ejection_fraction`, `d_dimer`, `brain_natriuretic_peptide`, `serum_troponin`, `serum_crp`, `serum_ck_mb`, `shock_presence`, `pulmonary_hypertension_presence`, `deep_venous_thrombosis_presence`, and `pulmonary_arterial_filling_defect_presence`.
- Suggested neutral axis IDs were used where an exact registry match was not found: `prior_cerebral_infarction_history_presence`, `chronic_calcium_channel_blocker_use_context_presence`, `normal_vesicular_breath_sounds_presence`, `cardiac_physical_exam_abnormality_presence`, `ecg_t_wave_abnormality_presence`, `bilateral_pulmonary_fibrous_cord_ct_presence`, `suspected_left_posterior_cerebral_artery_small_aneurysm_presence`, `ecg_st_t_segment_abnormality_presence`, `bilateral_lower_leg_intermuscular_venous_thrombosis_presence`, and `main_and_bilateral_branch_pulmonary_arterial_filling_defect_presence`.
- D-dimer was kept as `ug/mL` because the source reports microg/ml but does not specify FEU versus DDU.
- Troponin was kept as generic `serum_troponin` because the source writes `Tn` without specifying I versus T.
- Creatine kinase isozyme was mapped to `serum_ck_mb`; the exact isoenzyme wording is ambiguous in the article text.
