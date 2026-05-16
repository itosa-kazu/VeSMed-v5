# Blind PMC Real-Case Pilot: 25-Case Checkpoint

Date: 2026-05-16

## Scope

This checkpoint extends the blind PMC/PubMed real-case regression set from 20 to 25 cases.

Batch 3 cases:

| PMCID | PMID | Expected disease_id for evaluation copy | Top single-manifold result |
| --- | --- | --- | --- |
| PMC3383153 | 22745881 | D-ACUTE-LIMB-ISCHEMIA | D-ACUTE-LIMB-ISCHEMIA |
| PMC8916920 | 35295364 | D-ACUTE-KIDNEY-INJURY | D-ACUTE-KIDNEY-INJURY |
| PMC12074618 | 40365554 | D-ACUTE-LIVER-FAILURE | D-ACUTE-LIVER-FAILURE |
| PMC10961495 | 38521515 | D-ACUTE-HEPATITIS-E | D-ACUTE-HEPATITIS-E |
| PMC6388855 | 30820375 | D-ACUTE-HIV | D-ACUTE-HIV |

Blind extraction files preserve PMCID/PMID/source URL and do not contain expected labels. Treatment response, final diagnosis, and late discussion details remain record-only.

## Fixes From Batch 3

- Added runtime aliases and focused anchor support for acute limb ischemia, acute kidney injury, acute liver failure, and acute HIV.
- Added unit conversion for common per-uL hematology values to 10^9/L.
- Completed AKI/rhabdomyolysis-relevant axes for D-ACUTE-KIDNEY-INJURY: AST, ALT, LDH, hemoglobinuria, and severe hypervolemia.
- Completed Wilson-context ALF raw evidence axes for D-ACUTE-LIVER-FAILURE: ceruloplasmin, serum copper, 24-hour urinary copper, slit-lamp corneal ring, and hemolysis evidence.
- Normalized bilirubin values in the PMC12074618 ranking copy from umol/L-equivalent source values to mg/dL.

## Verification

Focused batch-3 run:

```powershell
$env:VESMED_CASE_DIR='tmp_blind_eval\cases_for_ranking'
$env:VESMED_CASE_FILTER='PMC3383153,PMC8916920,PMC12074618,PMC10961495,PMC6388855'
$env:VESMED_SCORE_MODE='grid'
$env:VESMED_TIME_GRID_N='17'
$env:VESMED_MAX_COMBO_SIZE='1'
$env:VESMED_RESULT_PATH='tmp_blind_eval\blind_pilot_new5_batch3_after_alf_wilson_axes.txt'
python .\v5_joint_sde_case_test.py
```

Result: `Single-manifold validation: 5/5 PASS`

Cumulative 25-case run:

```powershell
$env:VESMED_CASE_DIR='tmp_blind_eval\cases_for_ranking'
$env:VESMED_SCORE_MODE='grid'
$env:VESMED_TIME_GRID_N='17'
$env:VESMED_MAX_COMBO_SIZE='1'
$env:VESMED_RESULT_PATH='tmp_blind_eval\blind_pilot_25case_after_batch3_fixes.txt'
python .\v5_joint_sde_case_test.py
```

Result: `Single-manifold validation: 25/25 PASS`
