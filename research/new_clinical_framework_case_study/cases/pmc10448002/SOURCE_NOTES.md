# PMC10448002 source notes

## Source

- Gallant TL, Zheng E, Hobbs AM, Becka AJ, Bertsch RA. **Complement-Mediated Thrombotic Microangiopathy in a Patient With Antiphospholipid Syndrome and Anti-glomerular Basement Membrane Antibodies.** Cureus. 2023;15(7):e42410.
- PMCID: `PMC10448002`
- PMID: `37637585`
- DOI: `10.7759/cureus.42410`
- Article: <https://pmc.ncbi.nlm.nih.gov/articles/PMC10448002/>
- Europe PMC full-text XML: <https://www.ebi.ac.uk/europepmc/webservices/rest/PMC10448002/fullTextXML>
- Extracted XML SHA-256: `31767e6ef062340bee98b55bd37be77a3900fa9a0b8a897776db60ce12ed98e0`
- License reported in the XML: CC BY 3.0.

`case_event_stream.json` was distilled directly from the article full text, not from a VeSMed/V5 case artifact or its expected diagnosis.

## What the paper directly supports

### Before admission and admission

- A 30-year-old woman had established antiphospholipid syndrome and recent apixaban exposure, complex partial epilepsy, migraine with aura, and the stated obstetric history.
- A prior ED visit for persistent dry cough had found elevated creatinine, but the earlier numeric creatinine and exact date were not reported.
- A urinalysis five days before admission had protein `>500 mg/dL`, no red blood cells, and no red-cell casts.
- An outpatient elevated IgG anti-GBM antibody result triggered admission. The collection date and numeric titer were not reported; it was known at ED arrival.
- At admission she reported dry cough and foamy urine. Hemoglobin was `11.1 g/dL`, creatinine `1.83 mg/dL`, platelet count `92,000/mm3`, LDH `335 U/L`, and total bilirubin `0.4 mg/dL`; chest CT was described as unremarkable.

### Initial hypothesis and intervention

- The clinical team presumed anti-GBM disease and began plasmapheresis and high-dose IV corticosteroids immediately.
- Apixaban was replaced by a heparin infusion. A tunneled right-IJ plasmapheresis catheter was inserted; the first albumin-replacement plasmapheresis session occurred the night of admission.
- An ADAMTS13 sample was drawn the following morning because TTP was considered. The result was not available then.
- The article states that the first two hospital days were uneventful with no new symptoms. This global statement is **record-only** and is not expanded into unreported symptom-specific negatives.

### Biopsy and acute post-biopsy event

- Renal biopsy occurred on hospital day 3.
- The next morning (day 4), platelet count was `40,000/mm3`, hemoglobin `7.6 g/dL`, and biopsy-site pain was present. Ultrasound showed a `5.3 x 2.4 x 6.9 cm` hematoma.
- Serial CBC monitoring was chosen. Hemoglobin/hematocrit were stable over the next 24 hours, while platelets continued to fall; no further numeric nadir was given.
- The platelet fall after heparin led to a HIT-panel order. A smear was ordered to investigate schistocytes/MAHA and possible DIC. These are hypothesis and action events, not observed diagnoses at order time.

### Recovery and revised workup

- Over the following two days, platelet count improved to `110,000/mm3` and hemoglobin to `8.1 g/dL`; exact collection days within that interval were not given.
- Preliminary biopsy reporting found acute microvascular thrombotic injury and `50%` interstitial fibrosis/tubular atrophy, while the report said there was no evidence of anti-GBM disease.
- Because the paper does not provide the underlying anti-GBM immunofluorescence measurement, the latter is stored as a non-rankable `report_conclusion`; no invented “negative linear IgG staining” observation is added.
- Subsequent results were C3 `69 mg/dL`, C4 `8.0 mg/dL`, haptoglobin `<9 mg/dL`, LDH `291 U/L`, target cells and schistocytes present, HIT panel negative, and ADAMTS13 activity `61%`.
- Final biopsy morphology supported acute and chronic microvascular thrombotic injury: duplicated/multilayered GBM, endothelial injury/swelling, glomerular and arteriolar fibrin thrombi, mesangiolysis, and red-cell fragments. These are encoded as generic morphologic findings rather than a disease label.

### Later treatment and discharge

- Plasmapheresis continued daily, but individual session times were not enumerated.
- After HIT was excluded, heparin was used to bridge to chronic warfarin. The article does not specify whether and when heparin was held and restarted during the HIT evaluation.
- Rituximab and eculizumab were started, and a slow prednisone taper began, but their exact start days, doses, and order relative to one another were not reported.
- The hospitalization lasted 15 days. At discharge there were no new symptoms and creatinine was trending down, without a numeric discharge value.
- Genetic testing, further infusions, and hematology/nephrology follow-up were planned after discharge. They remain `future_plan` events and are not marked completed.

## Timing model and anti-leakage rules

The article mixes exact days with prose such as “over the following two days” and “once HIT was ruled out.” The event ledger therefore uses:

1. `occurrence_time` for when the symptom, measurement, specimen, action, or tissue state occurred;
2. `available_at` for when the care team could use the information;
3. `partial_order.after/before` where only order—not exact clock time—is supported;
4. interval-censored time when the paper supplies only a bounded narrative window.

Important examples:

- Anti-GBM antibody: obtained before admission at an unknown date, but available by ED arrival.
- ADAMTS13: sample occurred on day 1; result availability is only known to be later and before discharge.
- Renal biopsy: tissue occurrence/sample day is day 3; preliminary and final pathology become available later.
- Rituximab/eculizumab: started after the revised workup and before discharge; assigning either to a specific day would be fabrication.

The logical information cut `C4_AFTER_REVISED_WORKUP_COMPLETE` is deliberately **not assigned a hospital day**. It means that the listed pathology and laboratory results are all available. A runtime that requires a numeric timestamp must propagate an interval or branch over admissible timings; it must not silently replace the interval with a midpoint.

## Layer separation

- `observation`: direct patient report, measurement, imaging, assay, or diagnosis-neutral morphology.
- `action`: order, collection, procedure, drug, monitoring, or discharge planning.
- `clinical_hypothesis`: what the team considered or revised. It is not an observation and not hidden-state truth.
- `report_conclusion`: diagnostic wording when the source does not expose a diagnosis-neutral raw feature; it is excluded from rankable observations.
- `outcome`: realized endpoint.
- `future_plan`: planned but not realized within the report.

The article's final label of complement-mediated TMA is therefore represented as a **clinical hypothesis adopted at discharge**, with the explicit limitation that planned genetic testing was not reported as completed. The dataset does not assert an omniscient hidden mechanism.

## Deliberately not inferred

- Numeric outpatient anti-GBM titer or its collection date.
- Numeric earlier ED creatinine or exact number of weeks before admission.
- MCV or other indices behind the phrase “microcytic anemia.”
- Exact platelet nadir during the 24-hour decline.
- Exact timing among CBC recovery, preliminary pathology, complement results, HIT result, ADAMTS13 result, and final pathology beyond the paper-supported partial order.
- A specific negative immunofluorescence axis for anti-GBM disease.
- Schistocyte percentage.
- Exact targeted-therapy start days, doses, or causal attribution of recovery to a particular drug.
- Genetic confirmation of a complement regulatory abnormality.
- Completion of post-discharge plans.

## Suitability for the new-framework test

This case is useful because the observable state and clinical hypothesis change under treatment and delayed evidence:

1. a positive disease-associated antibody and kidney injury initially support one branch;
2. treatment starts before tissue confirmation;
3. biopsy creates a complication that perturbs hemoglobin and platelets;
4. competing explanations (procedure-related blood loss, HIT, severe ADAMTS13 deficiency, microangiopathic hemolysis) coexist temporarily;
5. delayed pathology and complement/hemolysis data force a branch revision;
6. actions continue while the exact mechanism remains incompletely confirmed.

The test harness must reconstruct belief over branches from this ledger. It must not read `author_diagnostic_summary_not_ground_truth` or later hypothesis updates as privileged truth at earlier cuts.
