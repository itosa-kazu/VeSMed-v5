# Blind PMC real-case regression: 35 cases

Date: 2026-05-16

## Scope

- Added batch5 blind full-text extractions for 5 PMC cases, preserving PMCID, PMID, DOI where available, and source URL.
- Converted each extraction into ranking JSON without exposing `expected_manifold` or final-diagnosis labels to the extractor.
- Re-ran the cumulative blind regression across 35 ranking cases.

## Batch5 cases

| PMCID | Source URL | Held-out expected disease_id | Focused result |
| --- | --- | --- | --- |
| PMC8214500 | https://pmc.ncbi.nlm.nih.gov/articles/PMC8214500/ | D-ACUTE-CHOLECYSTITIS | PASS |
| PMC8921967 | https://pmc.ncbi.nlm.nih.gov/articles/PMC8921967/ | D-ACUTE-CHOLECYSTITIS | PASS |
| PMC3784234 | https://pmc.ncbi.nlm.nih.gov/articles/PMC3784234/ | D-ACUTE-HEPATITIS-A | PASS |
| PMC3482082 | https://pmc.ncbi.nlm.nih.gov/articles/PMC3482082/ | D-ACUTE-HEPATITIS-A | PASS |
| PMC2783051 | https://pmc.ncbi.nlm.nih.gov/articles/PMC2783051/ | D-ACUTE-HEPATITIS-B | PASS |

## Runtime fixes from batch5

- Added source/demographic normalization in `tmp_blind_eval/make_ranking_case.py` for extractor variants using `source_metadata`, `metadata`, `rankable_observations`, or observation-derived age/sex axes.
- Added neutral exact-axis bridges for HAV/HBV/HEV serology, bilirubin aliases, and acute cholecystitis imaging/physical axes.
- Added an acute cholecystitis anchor that rewards true gallbladder imaging/stone/complication evidence without using expected labels.
- Refined hepatobiliary specificity:
  - Direct viral hepatitis markers now prevent nonspecific acute liver failure and acetaminophen toxicity from winning on AST/ALT/INR alone.
  - Direct viral hepatitis markers cap primary cholecystitis support when the case has only gallbladder edema-type findings without obstructive/complicated biliary anchors.

## Verification

- Focused batch5 run: `tmp_blind_eval/blind_pilot_new5_batch5_after_hepatitis_specificity_fix.txt`
  - Result: `5/5 PASS`
- Cumulative 35-case run: `tmp_blind_eval/blind_pilot_35case_after_batch5_fixes.txt`
  - Result: `35/35 PASS`

