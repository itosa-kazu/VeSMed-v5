# PMC5385992 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC5385992/
- PMCID: PMC5385992
- PMID: 28444079
- DOI: 10.5935/0103-507X.20170015
- The normal PMC HTML page was checked on 2026-05-16 but the browser view reached a reCAPTCHA interstitial.
- Full text was retrieved as JATS XML through NCBI EFetch:
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=5385992&retmode=xml`

## Extraction Boundary

- Included for ranking: case-report body facts from exposure through initial reference-ED presentation, initial vital signs, respiratory examination, ABG/laboratory data, and initial chest X-ray/CT findings.
- Kept record-only: article title/diagnostic framing, pre-referral treatments, noninvasive ventilation setup as treatment, ICU medications, serial treatment response, discharge course, and outpatient follow-up.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field, final diagnosis field, or disease-specific ordinary observation axis was added.

## Evidence Pointers

- Case report paragraph 1: age/sex, chemical inhalation exposure while cleaning a swimming pool, early dyspnea/cough/sputum/epigastric pain, first care at about 30 minutes, 3-hour worsening, SpO2 drop, cyanosis, burning chest pain, blood-tinged sputum, and absent smoking/respiratory disease/comorbidity history.
- Case report paragraph 2: afebrile state, heart rate, respiratory rate, blood pressure, SpO2 on 10 L/min oxygen, decreased chest expansion, decreased vesicular breath sounds, basilar crackles, and initial NIV settings.
- Case report paragraph 3: ABG values, leukocytosis with neutrophil predominance, normal electrolytes/coagulation/liver/canalicular enzymes, initial chest X-ray infiltrates, and initial chest CT findings.
- Case report paragraph 6: ICU medications, noninvasive ventilation course, serial oxygenation improvement, discharge, and outpatient follow-up, all retained as record-only.

## Axis Notes

- Reused registry-style neutral IDs where available: `dyspnea_presence`, `cough_presence`, `sputum_production_presence`, `hemoptysis_presence`, `cyanosis_presence`, `heart_rate`, `respiratory_rate`, `oxygen_saturation`, `arterial_pao2`, `arterial_paco2`, `arterial_pH`, `white_blood_cell_count`, `neutrophil_fraction`, `pulmonary_infiltrate_presence`, `pulmonary_consolidation_presence`, `ground_glass_opacity_presence`, and `pulmonary_artery_trunk_diameter_cm`.
- Suggested generic neutral IDs were used for concepts not clearly present in the registry, including `chemical_inhalation_exposure_presence`, `chlorine_gas_exposure_probability`, `pre_reference_ed_worsening_duration_hours`, `mucoid_sputum_presence`, `burning_chest_pain_quality_presence`, `pretransfer_oxygen_saturation_nadir`, and `decreased_chest_expansion_presence`.
- All record-only entries explicitly carry `use_in_ranking: false`.

## Boundary Doubts

- The article reports serial PaO2/FiO2 values during NIV; these were excluded from rankable observations because they are embedded in treatment-response chronology.
- The initial ABG appears near the start of ventilatory support, but the exact FiO2 at blood draw is not fully explicit; therefore PaO2/FiO2 was not derived as a rankable axis.
- The leukocyte count unit is awkward in the article text. It was normalized as 27.84 x 10^9/L based on the clinically intended 27,840/mm3 magnitude.
- The CT phrase interpreting pulmonary arterial trunk enlargement as pulmonary hypertension was kept record-only; the diameter measurement itself was retained as rankable imaging evidence.
