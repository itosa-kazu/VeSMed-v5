# PMC6009803 Blind Extraction Source Notes

## Access

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC6009803/
- PMCID: PMC6009803
- PMID: 29942881
- DOI: 10.1016/j.tjem.2018.01.004
- The PMC page opened through the browser tool returned a reCAPTCHA interstitial.
- Full text was retrieved as JATS XML through NCBI EFetch on 2026-05-16:
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=PMC6009803&retmode=xml`

## Extraction Boundary

- This article contains three case vignettes. The JSON file extracts Case 1 only to preserve a single-case demographics and snapshot structure.
- Included for ranking: Case 1 demographics, past clinical context, initial ED symptoms, physical findings, vital signs, ECG findings, and qualitative pre-response chest imaging.
- Kept record-only: article title framing, Case 2/Case 3 presence, sublingual nitroglycerin, BiPAP, IV nitroglycerin boluses/infusion, noninvasive ventilation response, post-treatment vital normalization, later interpretation, diuretic/digoxin treatment, discharge outcome, and discussion-level causal framing.
- Existing local `distillations/cases` files were intentionally not read.
- No expected diagnosis/manifold field, final diagnosis field, disease_label_per_paper field, or paper-title-derived diagnosis field was added.

## Evidence Pointers

- Case presentations, Case 1 opening sentence: 65-year-old female; past history of heart failure and hypertension; acute dyspnea and chest tightness.
- Case presentations, Case 1 examination sentence: anxious and diaphoretic appearance.
- Case presentations, Case 1 vital signs sentence: BP 213/91 mm Hg, pulse rate 103 bpm, respiratory rate 36/min, SpO2 92% on high-flow oxygen mask, temperature 36 C.
- Case presentations, Case 1 exam/imaging sentence: orthopnea, bilateral basal rales, chest X-ray and bedside ultrasound interpreted as acute pulmonary edema.
- Case presentations, Case 1 ECG sentence: sinus tachycardia and nonspecific ST-T changes.
- Case presentations, Case 1 treatment/outcome sentences: all treatment, response, later interpretation, and discharge facts retained as record-only.

## Ambiguities And Extraction Choices

- SpO2 was measured on high-flow oxygen mask; room-air saturation and oxygen flow rate are not provided.
- Pulse rate was mapped to `heart_rate`.
- MAP was calculated from the reported BP as `(213 + 2 * 91) / 3 = 131.7 mmHg`.
- Blood tests were described only as unremarkable, so no broad normal-lab rankable axis was added and no specific analyte was inferred.
- The source gives qualitative pulmonary edema imaging only; it does not provide B-line count, edema extent, pleural effusion status, cardiac silhouette size, BNP, troponin, arterial blood gas, or creatinine values for Case 1.
- The source says "acute" dyspnea but does not quantify symptom duration.
- The article title and discussion disclose diagnostic/treatment framing; those were not used as ranking evidence.
