# PMC9107358 Blind Extraction Source Notes

Source: https://pmc.ncbi.nlm.nih.gov/articles/PMC9107358/
PMCID: PMC9107358
PMID: 35578608
DOI: 10.1155/2022/3672248

## Access

- Primary PMC HTML access showed a reCAPTCHA interstitial in the browser tool.
- Full text was retrieved as PMC JATS XML through NCBI EFetch:
  `https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id=PMC9107358&retmode=xml`
- The PMC XML supplementary-material pointer named `3672248.f1.docx`; direct supplementary download showed a CloudPMC download challenge, and the OA package link returned unavailable during this extraction. The main article body contained the necessary admission, pre-antidote course, and late peak-value facts used here.
- Local `distillations/cases` files were intentionally not read.
- `master_axes.json` was consulted only as a neutral axis_id naming registry.

## Ranking Evidence Window

Used as rankable evidence:

- Demographics from the same article abstract: 43-year-old, 55 kg female.
- Pre-existing and exposure context: reported ingestion of an unknown quantity of acetaminophen, clonidine, and alcohol; possible ingestion time 45 minutes to 4.5 hours before presentation.
- Admission vitals and neurologic status: respiratory rate 8, oxygen saturation 99% on room air, blood pressure 98/62 mmHg, heart rate 50 with minimum 45, Glasgow coma score 3, reduced conscious state.
- Admission labs: acetaminophen 41 mg/L, AST 25 IU/L, ALT 20 IU/L, INR 1.1, lactate 2.1 mmol/L, ethanol 0.37%.
- Pre-acetylcysteine repeat data: acetaminophen 39 mg/L four hours later; at 38 h post-ingestion generalized abdominal pain, MAP 52 mmHg, lactate 5.9 mmol/L, CT mesenteric edema/pericholecystic fluid/periportal edema/diffuse bowel wall edema with reduced enhancement/pancolitis, ALT 489 U/L, INR 1.5, acetaminophen 85 mg/L.

## Record-Only Evidence

Not used for ranking:

- Title-level diagnosis wording and paper-level interpretation.
- Intubation, non-use of charcoal/lavage, acetylcysteine decisions, extubation, noradrenaline, continuous renal replacement therapy, transplant-team decision, and prolonged ICU course.
- Surgical-team interpretation that the CT/clinical picture was not acute surgical pathology.
- Fulminant hepatic failure label, oliguric acute kidney injury requiring CRRT, peak ALT/INR/creatinine, mild encephalopathy, return to baseline, and discharge outcome.
- Later husband-provided details that the tablets were a combination product containing acetaminophen, dextromethorphan, and chlorphenamine.
- Metabolite AUC/CYP-fraction analysis and discussion-level causal framing about delayed absorption.

## Ambiguity And Unit Notes

- The source writes respiratory rate as "8 bpm"; it was interpreted as 8 breaths/min.
- Ethanol is reported as "0.37%" without a precise laboratory convention; no mg/dL conversion was made.
- The abstract says ALT 25 U/L, while the case-report body reports AST 25 IU/L and ALT 20 IU/L; the body values were encoded.
- Acetaminophen values are reported as mg/L with micromol/L equivalents; JSON encodes mg/L as mcg/mL because they are numerically equivalent.
- Peak creatinine is reported only as 138 micromol/L in late course and was kept record-only.

## Boundary Check

- No hidden target-label field, paper-diagnosis field, or diagnosis-result field was written.
- No ordinary observation axis uses a disease-specific observation suffix.
- Rankable facts are diagnosis-neutral clinical axes; treatment, procedures, final interpretation, response, late outcome, and discussion-level causal explanations are `use_in_ranking=false`.
