# Blind PMC Real-Case Regression: 50 Cases

Date: 2026-05-16

## Scope

- Cases: 50 real PMC/PubMed cases.
- Active atlas: 306 single-disease manifolds.
- Ranking mode: grid, `VESMED_TIME_GRID_N=17`, `VESMED_MAX_COMBO_SIZE=1`.
- Result file: `tmp_blind_eval/blind_pilot_50case_after_batch7_fixes.txt`.

## Batch 7 Additions

Cases 41-50 added from source full text, preserving PMCID/PMID/source URL:

- PMC2637259 -> `D-CARBON-MONOXIDE-POISONING`
- PMC9790177 -> `D-SALICYLATE-TOXICITY`
- PMC9771788 -> `D-HYPERKALEMIA`
- PMC6442909 -> `D-NECROTIZING-FASCIITIS`
- PMC3089931 -> `D-PNEUMOTHORAX`
- PMC8752403 -> `D-INTUSSUSCEPTION`
- PMC3514212 -> `D-DENGUE`
- PMC6040519 -> `D-BACTERIAL-MENINGITIS`
- PMC5572045 -> `D-GUILLAIN-BARRE-SYNDROME`
- PMC9485698 -> `D-SUBARACHNOID-HEMORRHAGE`

## Result

- New batch focused regression: 10/10 PASS.
- Cumulative regression: 50/50 PASS.
- OOD/null-model output remains delta-only; no hard unknown-disease threshold was added.

## Runtime Fixes

- Added high-specificity direct-anchor handling for carbon monoxide poisoning, salicylate toxicity, hyperkalemia, pneumothorax, intussusception, necrotizing fasciitis, dengue, Guillain-Barre syndrome, bacterial meningitis, and adrenal crisis.
- Added unexplained high-specificity evidence penalties for direct dengue markers, bacterial CSF microbiology, peripheral neuropathy electrodiagnostics, and direct adrenal-insufficiency endocrine evidence.
- Added unit conversions for temperature, salicylate/toxin concentration, CSF protein, count units, glucose, pCO2, and CSF WBC.
- Added neutral axis aliases and derived observations needed by the new blind cases.
- Tightened DKA gating so acidosis alone does not count without hyperglycemia or ketone evidence.
- Added age/context gating for pregnancy-related diseases.
- Made tumor lysis syndrome require TLS-specific context or biochemical evidence instead of ranking from hyperkalemia/AKI alone.

## QA

- `python -m py_compile .\v5_joint_sde_case_test.py .\tmp_blind_eval\make_ranking_case.py`: PASS.
- New extraction JSON parse check: 10/10 PASS.
- Forbidden extraction leakage grep (`expected*`, `disease_label_per_paper`, ordinary `*_in_D-*`): 0 matches.
- Ranking copies source URL null check: 0 matches.

