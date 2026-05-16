# Blind PMC Full-Text Pilot Summary - 40 Cases

Date: 2026-05-17

Scope:
- Cases 36-40 were extracted from original PMC/PubMed full text by separate blind agents.
- Extraction files preserve PMCID/PMID/source URL and contain no expected disease fields.
- Ranking copies under `tmp_blind_eval/cases_for_ranking/` add held-out `expected_manifold` only after extraction.
- Runtime standard remains top-1 correctness plus plausible high-ranked differentials.

Batch 6 cases:

| Case | Source | Held-out expected | Focused result |
| --- | --- | --- | --- |
| PMC10964955 | PMID 38514990 / https://pmc.ncbi.nlm.nih.gov/articles/PMC10964955/ | D-ACETAMINOPHEN-TOXICITY | PASS; APAP toxicity ranked above acute liver failure and viral hepatitis mimics |
| PMC8810263 | PMID 34176834 / https://pmc.ncbi.nlm.nih.gov/articles/PMC8810263/ | D-ACETAMINOPHEN-TOXICITY | PASS; APAP toxicity ranked above sepsis and acute liver failure mimics |
| PMC5348911 | PMID 28288603 / https://pmc.ncbi.nlm.nih.gov/articles/PMC5348911/ | D-ACUTE-ANGLE-CLOSURE-GLAUCOMA | PASS; angle closure ranked above retinal detachment and hypertensive emergency |
| PMC6075637 | PMID 30087808 / https://pmc.ncbi.nlm.nih.gov/articles/PMC6075637/ | D-ACUTE-ANGLE-CLOSURE-GLAUCOMA | PASS; angle closure ranked above headache/neurologic mimics |
| PMC7039351 | PMID 32140338 / https://pmc.ncbi.nlm.nih.gov/articles/PMC7039351/ | D-ACUTE-EPIGLOTTITIS | PASS; epiglottitis ranked above peritonsillar abscess and airway foreign body |

Runtime fixes made from this batch:
- Added neutral exact aliases and derived findings for acetaminophen exposure, serum APAP concentration, side-specific intraocular pressure, visual acuity, corneal edema, conjunctival injection, and pupil findings.
- Added disease-specific anchor support for APAP toxicity, acute angle-closure glaucoma, retinal detachment, subarachnoid hemorrhage, perforated viscus, and IgA nephropathy.
- Capped nonspecific acute viral hepatitis / acute liver failure support when toxic APAP exposure is directly observed.
- Required kidney/urine/biopsy anchors for IgA nephropathy so retinal hemorrhage or macular edema alone cannot support IgA nephropathy.

Verification:
- `python -m py_compile .\v5_joint_sde_case_test.py`: PASS
- Focused batch 6: `tmp_blind_eval/blind_pilot_new5_batch6_after_iga_anchor_fix.txt`: 5/5 PASS
- Cumulative blind pilot: `tmp_blind_eval/blind_pilot_40case_after_batch6_iga_fix.txt`: 40/40 PASS
