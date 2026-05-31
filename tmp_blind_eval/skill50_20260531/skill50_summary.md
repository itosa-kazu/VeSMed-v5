# Skill50 Real-Case Ranking Batch - 2026-05-31

- Batch: `skill50_20260531`
- Case source: active real PMC/PubMed case pool copied to `tmp_blind_eval/skill50_20260531/cases`
- Selection: 50 single-manifold cases, one per expected active disease when possible, excluding `skill20_20260531`
- Validation mode: `grid`, `time_grid_n=17`, `max_combo_size=1`, `top_n=10`

## Results

- Baseline validation: `50/50 PASS`
- Baseline top-10 audit: `49 PASS_MARGIN_GE10`, `1 LOW_MARGIN_LT3`
- Low-margin item: `CHIKUNGUNYA_KIDNEY_TX_ARTHRALGIA_AKI_PMC6979562`; expected `D-CHIKUNGUNYA`, top2 `D-ACUTE-HIV`, margin `1.31`
- Final validation after repair: `50/50 PASS`
- Final top-10 audit: `50 PASS_MARGIN_GE10`, no low-margin cases, no skipped cases
- Focused regression: chikungunya + dengue + acute HIV active cases, `9/9 PASS`, no low-margin cases

## Repair Ledger

| case_id | expected | observed issue | failure class | repair action | final result |
| --- | --- | --- | --- | --- | --- |
| `CHIKUNGUNYA_KIDNEY_TX_ARTHRALGIA_AKI_PMC6979562` | `D-CHIKUNGUNYA` | Expected disease was top1 but acute HIV was top2 with margin `1.31` | Top-10 plausibility / source-context geometry gap | Added generic `arboviral_outbreak_or_aedes_contact_presence` as an epidemiologic finding for chikungunya and dengue; runtime derives it from explicit Aedes/arboviral outbreak risk context without treating it as a neutral background context. | `PASS_MARGIN_GE10`, margin `73.71` |

## Evidence Files

- Manifest: `skill50_manifest.json`
- Baseline report: `skill50_baseline.txt`
- Baseline audit: `skill50_baseline_audit.md`
- Final report: `skill50_after_arbovirus_context.txt`
- Final audit: `skill50_after_arbovirus_context_audit.md`
- Focused regression: `focused_arbovirus_hiv_after_context.txt`
- Focused audit: `focused_arbovirus_hiv_after_context_audit.md`
