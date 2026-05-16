# PMC5951991 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC5951991/
- PMCID: PMC5951991
- PMID: 29850408
- DOI: 10.21037/cdt.2017.11.06
- Browser access to the interactive PMC page was blocked by a reCAPTCHA interstitial.
- NCBI EFetch JATS XML was retrieved for the PMCID:
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=5951991&rettype=full&retmode=xml`
- The EFetch XML preserved article identifiers and abstract but did not expose the body case-presentation section in this environment.
- The case-presentation body was therefore extracted from the publisher full-text HTML for the same article:
  `https://cdt.amegroups.org/article/view/17501/html`

## Extraction Boundary

- Included for ranking: demographics, baseline hypertension and medication context, presenting chest pain/headache/dizziness, severe bilateral arm blood pressure, 24-hour blood-pressure pattern, EKG, echocardiography, renal-function normality statement, abdominal duplex findings, invasive angiography, and pre-intervention CT angiography findings.
- Kept record-only: article title, paper diagnostic framing, medication changes after presentation, nonperformed bicycle ergometry, intervention decision, stent procedure, procedural result, 1.5-year follow-up, treatment response, and discussion-level causal/classification statements.
- Existing local `distillations/cases` files were intentionally not read.
- No paper diagnosis/manifold field was added.
- No ordinary diagnosis-specific disease-suffixed observed axes were used.

## Evidence Pointers

- Case presentation paragraph 1: age, sex, height, weight, BMI, arterial hypertension history, current chest pain, discrete headaches, dizziness, absence of prior pain attacks, absence of further cardiovascular risk factors, sigmoid diverticulosis, bilateral blood pressure up to 210/110 mmHg, and initial valsartan/torasemide medication context.
- Case presentation paragraph 1, record-only boundary: antihypertensive regimen modification to candesartan, hydrochlorothiazide, and lercanidipine.
- Case presentation paragraph 2 and Figure 1: 24-hour blood pressure measurement with reversed circadian rhythm and nighttime average 150/90 mmHg.
- Case presentation paragraph 2: EKG indifference type, ST depression in II/III/aVF, diastolic septal thickness 14 mm, E/A ratio 0.85, and bicycle ergometry not feasible due to difficult blood-pressure control.
- Case presentation paragraph 3: inconspicuous renal function, right-sided borderline variable renal resistance index on duplex, right renal artery not demonstrated, no relevant coronary stenosis on invasive angiography, high-grade dynamic ostial right renal artery stenosis, pressure gradient 5-35 mmHg, thoracic aorta kinking, dissection/flap involving the right renal artery, and reduced right kidney perfusion.
- Figure 2 caption: moving aortic flap, false lumen, ostial stenosis, aortic flap ending near the proximal right renal artery, right kidney supplied by false and true lumen, delayed-imaging renal density difference of left 235 HU vs right 158 HU, and post-stent appearance retained as record-only.
- Case presentation final paragraph: stent intervention and 1.5-year follow-up retained as record-only.
- Discussion paragraphs: mechanism, prognosis, classification, and therapy rationale retained as record-only.

## Registry Notes

- Reused or followed existing generic axis style for `chest_pain_presence`, `headache_presence`, `dizziness_presence`, `severe_hypertension_presence`, `systolic_blood_pressure`, `diastolic_blood_pressure`, `mean_arterial_pressure`, `nocturnal_hypertension_presence`, `inferior_lead_st_depression_presence`, `interventricular_septal_thickness_diastolic_mm`, `mitral_e_a_ratio`, `renal_function_abnormality_presence`, and vascular imaging findings.
- Suggested neutral axis IDs were used where exact registry matches were not checked: `bilateral_arm_blood_pressure_elevation_presence`, `reversed_circadian_blood_pressure_rhythm_presence`, `right_renal_resistive_index_variability_presence`, `right_renal_artery_ostial_stenosis_presence`, `dynamic_vascular_stenosis_presence`, `aortic_flap_or_membrane_presence`, `descending_aortic_dissection_flap_presence`, `right_renal_artery_involvement_by_aortic_flap_presence`, `false_lumen_prolapse_into_right_renal_artery_presence`, and `right_kidney_hypoperfusion_presence`.

## Ambiguities

- The article does not report exact heart rate, temperature, respiratory rate, oxygen saturation, creatinine, BUN, eGFR, CBC, inflammatory markers, D-dimer, troponin, urinalysis, renin/aldosterone, or numeric renal resistance index.
- The source says renal function was inconspicuous but gives no numeric renal-function value; this was encoded as absence of renal-function abnormality with a quality note.
- The 24-hour blood-pressure recording appears after medication modification in the narrative but before endovascular intervention; it was kept rankable as diagnostic workup evidence, while the medication change itself was record-only.
- The CT text contains diagnostic language. The extraction represents the underlying observable vascular findings with neutral imaging axes and keeps the article-level diagnostic framing record-only.
