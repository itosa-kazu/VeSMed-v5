# PMC6946433 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC6946433/
- PMCID: PMC6946433
- PMID: 31689871
- DOI: 10.1097/MD.0000000000017833
- Browser access to the interactive PMC page was blocked by a reCAPTCHA interstitial in the browser tool.
- Full text was retrieved as NCBI EFetch JATS XML:
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=PMC6946433&retmode=xml`

## Extraction Boundary

- Included for ranking: age/sex, chronic risk context, initial symptoms, initial vital signs, initial blood tests, urinalysis, ECG findings, chest radiography, bedside echocardiography, and same-episode emergent coronary/left ventricular angiography.
- Kept record-only: article title, paper diagnostic interpretation, initial treating-team diagnostic labels, treatment, pacing response, culture results with uncertain timing relative to snapshot, day-4 course, pacemaker implantation, discharge, 15-month follow-up, and discussion-level causal framing.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field or final diagnosis field was added.
- No ordinary diagnosis-specific disease-suffixed observed axes were used.

## Evidence Pointers

- Article metadata: PMCID, PMID, DOI, article title, journal, and publication details.
- Abstract: patient concern summary, paper diagnosis, intervention, outcome, and lesson fields retained only as record-only boundary context.
- Case report paragraph 1: age/sex, type 2 diabetes, hyperlipidemia, chronic kidney disease, chest pain, dizziness, nausea, cold sweats, fever, bradycardia, hypotension, WBC, band neutrophils, creatinine, CPK, troponin I, CRP, normal electrolytes/liver function, urinalysis, ECG, chest radiography, bedside echocardiography, initial diagnostic labels, treatment, pacing, coronary angiography, LV angiography, and transfer due to unstable hemodynamics.
- Figure 1 caption: inferior-lead ST-segment elevation with complete atrioventricular block.
- Figure 2 caption: normal epicardial coronary arteries and mid-to-apical inferior wall akinesia.
- Case report paragraph 2: E coli blood/urine cultures, response to antibiotics, persistent intermittent CAVB, pacemaker implantation, discharge, and 15-month follow-up retained as record-only.
- Discussion: final etiologic interpretation and mechanism discussion retained as record-only.

## Axis Notes

- Axis IDs were chosen as diagnosis-neutral generic labels without reading local disease distillations or local case files.
- Parent/satellite structure was used for fever/body temperature, troponin elevation/troponin I, pyuria/urine WBC count, ST elevation/inferior-lead ST elevation, and regional wall motion abnormality/inferior wall akinesia.
- Normal coronary arteries were represented as absent `coronary_artery_stenosis_presence`, not as a disease label.
- Culture positivity was kept out of ranking because the narrative reports it after acute treatment/workup and does not state availability at the initial diagnostic snapshot.

## Ambiguities

- The case text does not report respiratory rate, oxygen saturation, lactate, platelet count, hemoglobin, BNP, exact AST/ALT/bilirubin values, or urine culture colony count.
- The patient had chronic kidney disease, but no baseline creatinine is reported; creatinine 2.1 mg/dL was still extracted as a presentation measurement.
- Coronary angiography and left ventricular angiography occurred after initial treatment steps but before the paper's final etiologic interpretation; they were included as same-episode diagnostic workup facts.
- Blood and urine cultures were likely obtained during workup, but the result timing is not explicit; they are record-only.
