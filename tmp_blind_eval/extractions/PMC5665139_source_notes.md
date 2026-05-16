# PMC5665139 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC5665139/
- PMCID: PMC5665139
- PMID: 29118839
- DOI: 10.1177/1751143717701946
- Browser access to the PMC page was blocked by a reCAPTCHA interstitial.
- NCBI EFetch JATS XML was retrieved from:
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=5665139&retmode=xml`
- The EFetch XML contained front matter and abstract only, with the source comment that the publisher does not allow downloading the full text in XML form.
- Full case text was therefore read from the matching publisher full-text page:
  `https://journals.sagepub.com/doi/10.1177/1751143717701946`

## Extraction Boundary

- Included for ranking: age, sex, medical history, initial ED respiratory presentation, qualitative blood-gas/vital physiology, ICU ventilation and medication exposures before ocular symptoms, day-3 ocular symptoms, urgent ophthalmology examination, visual acuity findings, pupil/cornea/anterior chamber findings, and pre-treatment intraocular pressure measurements.
- Kept record-only: article title, source diagnostic labels, ophthalmology diagnostic interpretation, left-eye risk interpretation, ocular treatment, post-treatment IOP/symptom response, late ICU/ward/home course, and discussion-level causal/risk framing.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field or final diagnosis field was added.
- No ordinary diagnosis-specific disease-suffixed observed axes were used.

## Evidence Pointers

- Article title: paper-level diagnosis disclosure kept record-only.
- Abstract: metadata confirmation and high-level timeline; diagnostic and treatment outcome statements kept record-only.
- Case presentation paragraph 1: 69-year-old male, four-day cough and increasing shortness of breath, ED type 2 respiratory failure, tachycardia, hypotension, hypoxia, hypercapnia, mixed respiratory and metabolic acidosis, COPD history, and peripheral vascular disease history.
- Case presentation paragraph 2: ED intubation, ICU transfer, source diagnostic labels kept record-only, intravenous piperacillin/tazobactam, aminophylline, steroids, nebulised salbutamol/ipratropium, noradrenaline, extubation within 24 h, aminophylline/noradrenaline weaning, and bronchodilators for a further day.
- Case presentation paragraph 3: ICU day-3 right-sided eye pain, redness, decreased visual acuity, overnight worsening, left-eye involvement by morning, urgent ophthalmology clinic review, right-eye counting-fingers acuity, left-eye 6/18 acuity, right fixed/dilated pupil, shallow anterior chamber, and hazy cornea.
- Case presentation paragraph 4: right/left IOP 45/20 mmHg, ophthalmology diagnostic interpretation kept record-only, left markedly narrow angle as an exam fact, left-eye risk interpretation kept record-only, treatment kept record-only, and post-treatment IOP/symptom response kept record-only.
- Case presentation paragraph 5: later respiratory/ophthalmic improvement and discharge kept record-only.
- Discussion through Conclusion: general disease mechanism, symptom, risk factor, medication-causality, and monitoring recommendations kept record-only.

## Registry Notes

- Reused registry axis IDs where diagnosis-neutral matches existed, including `known_copd_presence`, `invasive_mechanical_ventilation_presence`, `recent_broad_spectrum_antibiotic_exposure_activity`, `theophylline_exposure_presence`, `aminophylline_intravenous_exposure_context_presence`, `beta_agonist_exposure_context_presence`, `vasopressor_exposure_context_probability`, `cough_presence`, `dyspnea_presence`, `respiratory_failure_presence`, `hypercapnia_presence`, `hypoxemia_presence`, `tachycardia_presence`, `hypotension_presence`, `shock_presence`, `metabolic_acidosis_presence`, `acute_eye_pain_presence`, `visual_acuity_impairment_presence`, `visual_acuity_logmar`, `pupillary_abnormality_presence`, `fixed_dilated_pupil_presence`, `shallow_anterior_chamber_presence`, `elevated_intraocular_pressure_presence`, `intraocular_pressure_mmHg`, `intraocular_pressure`, `inter_eye_iop_asymmetry_mmHg`, and `narrow_anterior_chamber_angle_presence`.
- Suggested neutral axis IDs were used where exact registry IDs were not found: `peripheral_vascular_disease_history_presence`, `critical_care_admission_context_presence`, `recent_systemic_corticosteroid_exposure_presence`, `inhaled_anticholinergic_exposure_context_presence`, `cough_duration_days`, `respiratory_acidosis_presence`, `right_eye_pain_presence`, `left_eye_symptom_involvement_presence`, `ocular_redness_presence`, `right_eye_counting_fingers_visual_acuity_presence`, and `corneal_haze_presence`.

## Ambiguities

- The source provides qualitative tachycardia, hypotension, hypoxia, hypercapnia, and mixed acidosis but no numeric vital signs or blood gas values.
- The source does not provide named laboratory values, inflammatory markers, renal function, cultures, or chest imaging findings.
- The timeline of medication discontinuation relative to ocular symptom onset is approximate: aminophylline and noradrenaline were weaned within 24 h after ICU admission, while nebulised bronchodilators continued for a further day.
- The phrase that symptoms began to affect the left eye does not specify whether pain, redness, visual acuity, or another symptom predominated before the eye exam.
- Right-eye counting-fingers acuity was not converted to a numeric logMAR value. Left-eye 6/18 acuity was converted approximately to logMAR 0.48 in the JSON.
