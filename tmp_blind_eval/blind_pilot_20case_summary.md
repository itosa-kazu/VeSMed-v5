# Blind PMC regression - 20 cases

Date: 2026-05-16

## Scope

- Extended the blind real-case pilot from 15 to 20 PMC/PubMed full-text cases.
- New blind extraction cases:
  - PMC5665139 / PMID 29118839 / https://pmc.ncbi.nlm.nih.gov/articles/PMC5665139/
  - PMC10005849 / PMID 36909084 / https://pmc.ncbi.nlm.nih.gov/articles/PMC10005849/
  - PMC5951991 / PMID 29850408 / https://pmc.ncbi.nlm.nih.gov/articles/PMC5951991/
  - PMC6946433 / PMID 31689871 / https://pmc.ncbi.nlm.nih.gov/articles/PMC6946433/
  - PMC8021585 / PMID 33795268 / https://pmc.ncbi.nlm.nih.gov/articles/PMC8021585/
- Extraction QA for the new five cases found no `expected_*` fields, no `disease_label_per_paper` in blind extraction files, no ordinary `*_in_D-*` observed axes, and record-only material excluded from ranking.

## Final verification

- New five-case focused run: `tmp_blind_eval/blind_pilot_new5_batch2_after_myocarditis_axes.txt` -> 5/5 PASS.
- Cumulative run: `tmp_blind_eval/blind_pilot_20case_after_batch2_fixes_final.txt` -> 20/20 PASS.
- Focused regression repairs:
  - `tmp_blind_eval/blind_pilot_pmc7005653_after_hav_serology_axis.txt` -> HAV case restored to PASS.
  - `tmp_blind_eval/blind_pilot_pmc5832394_after_alcohol_withdrawal_gate.txt` -> hyponatremia case restored to PASS.

## Repairs made

- Canonicalized exact-axis alias handling so noncanonical source axes do not penalize candidates using incompatible legacy metadata while canonical proxy axes are available for background fallback.
- Added anchor/alias support for aortic dissection, AIP, acute myocarditis, acute mesenteric ischemia, catheter-associated UTI, obstructive pyelonephritis, perinephric abscess, babesiosis, and falciparum malaria.
- Added an explicit alcohol-withdrawal-delirium anchor gate: chronic alcohol use alone no longer activates the withdrawal delirium manifold without recent reduction/cessation or withdrawal signs.
- Added the missing AIP diagnostic axis `urine_porphobilinogen_screen_positive_presence`.
- Added clinically generic myocarditis axes for CRP, troponin elevation, regional wall-motion abnormality, and coronary stenosis context.
- Corrected PMC7005653 blind extraction policy: raw IgM anti-HAV positivity is rankable diagnostic lab evidence; the paper's resulting etiologic interpretation remains record-only.

## Notes

- The 20-case pass is a growing regression baseline, not a stopping condition. Future batches should rerun this full set after each focused atlas/runtime repair.
- High-ranked differentials should continue to be reviewed for medical plausibility, not only top-1 correctness.
