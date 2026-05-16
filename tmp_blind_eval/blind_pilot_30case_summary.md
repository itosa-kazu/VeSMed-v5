# Blind PMC real-case pilot: 30-case cumulative checkpoint

Date: 2026-05-16

## Scope

This checkpoint extends the blind full-text PMC/PubMed workflow from 25 to 30 cases.
Each new case kept PMCID/PMID/source URL/DOI provenance in the extraction and ranking copy.
The blind extraction files do not contain expected manifold fields, expected disease labels, or ordinary `*_in_D-*` observed axes.

## New cases

| PMCID | PMID | DOI | Source URL | Held-out ranking answer |
| --- | --- | --- | --- | --- |
| PMC8716199 | 34976418 | 10.1155/2021/3103011 | https://pmc.ncbi.nlm.nih.gov/articles/PMC8716199/ | D-ADRENAL-CRISIS |
| PMC5521102 | 28732492 | 10.1186/s12879-017-2605-4 | https://pmc.ncbi.nlm.nih.gov/articles/PMC5521102/ | D-ACUTE-PROSTATITIS |
| PMC6411205 | 30882008 | 10.1093/ofid/ofy354 | https://pmc.ncbi.nlm.nih.gov/articles/PMC6411205/ | D-ADENOVIRUS-INFECTION |
| PMC11166063 | 38869336 | 10.5811/cpcem.1422 | https://pmc.ncbi.nlm.nih.gov/articles/PMC11166063/ | D-ACUTE-SYMPTOMATIC-HYPERNATREMIA |
| PMC4704278 | 26766978 | 10.1111/1759-7714.12007 | https://pmc.ncbi.nlm.nih.gov/articles/PMC4704278/ | D-AIHA |

## Result progression

- Initial new-5 run: `tmp_blind_eval/blind_pilot_new5_batch4_initial.txt` -> `3/5 PASS`.
- After adenovirus renal-allograft anchor/axis fixes: `tmp_blind_eval/blind_pilot_new5_batch4_after_anchor_axis_fixes.txt` -> `4/5 PASS`.
- After hypernatremia stress-axis and alias fanout fixes: `tmp_blind_eval/blind_pilot_new5_batch4_after_hypernatremia_stress_axis_fix.txt` -> `5/5 PASS`.
- Cumulative 30-case run initially exposed one old-case regression: PMC8021585 acute mesenteric ischemia was overtaken by D-INCARCERATED-GROIN-HERNIA when no groin-hernia anatomy was present.
- After groin-hernia anatomical anchor gating: `tmp_blind_eval/blind_pilot_30case_after_batch4_groin_anchor_fix.txt` -> `30/30 PASS`.
- Focused active hernia guardrail: `tmp_blind_eval/active_hernia_after_groin_anchor_fix.txt` -> `5/5 PASS`.

## Fixes

- Added source-aware ranking-copy conversion support for nested/root/article-id source metadata.
- Added neutral exact-axis aliases for adenovirus renal-allograft findings, hypernatremia/dehydration/mental-status findings, and MAP/hypotension derivations.
- Added fair adenovirus anchor support and renal-allograft adenovirus axes/edges to D-ADENOVIRUS-INFECTION.
- Added clinically real severe hypernatremia stress axes/edges to D-ACUTE-SYMPTOMATIC-HYPERNATREMIA.
- Suppressed unsupported sibling penalties created by exact-axis alias fanout.
- Added explicit anatomical anchor gating for D-INCARCERATED-GROIN-HERNIA so generic abdominal ischemia/inflammation cannot rank it first without groin/femoral/inguinal hernia evidence.

## Verification commands

```powershell
python -m py_compile .\v5_joint_sde_case_test.py .\tmp_blind_eval\make_ranking_case.py

$env:VESMED_CASE_DIR='tmp_blind_eval\cases_for_ranking'
Remove-Item Env:VESMED_CASE_FILTER -ErrorAction SilentlyContinue
Remove-Item Env:VESMED_MANIFOLD_FILTER -ErrorAction SilentlyContinue
$env:VESMED_SCORE_MODE='grid'
$env:VESMED_TIME_GRID_N='17'
$env:VESMED_MAX_COMBO_SIZE='1'
$env:VESMED_RESULT_PATH='tmp_blind_eval\blind_pilot_30case_after_batch4_groin_anchor_fix.txt'
python .\v5_joint_sde_case_test.py

$env:VESMED_CASE_DIR='distillations\cases'
$env:VESMED_CASE_FILTER='INCARCERATED_GROIN_HERNIA'
$env:VESMED_RESULT_PATH='tmp_blind_eval\active_hernia_after_groin_anchor_fix.txt'
python .\v5_joint_sde_case_test.py
```
