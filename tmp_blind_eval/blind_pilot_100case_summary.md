# Blind PMC/PubMed Real-Case Regression Summary

Date: 2026-05-17

## Scope

- Added blind full-text extraction and ranking copies for 50 additional real PMC cases, extending the rolling set to 100 cases.
- Each added case preserves PMCID and source URL in the ranking JSON.
- Extraction artifacts stay blind: no `expected_*`, no `disease_label_per_paper`, and no ordinary diagnosis-specific `*_in_D-*` observation axes.
- Treatments, final diagnoses, response to therapy, and discussion-only conclusions remain record-only unless needed for provenance.

## Results

- Batch 8 initial run, cases 51-100: 10/50 PASS.
- After first runtime/anchor repair: 40/50 PASS.
- After focused residual repairs: 50/50 PASS for cases 51-100.
- Cumulative 100-case regression after final adrenal/hyperkalemia repair: 100/100 PASS.

Final cumulative result file:

- `tmp_blind_eval/blind_pilot_100case_after_batch8_fixes_final2.txt`

Focused guardrail result files:

- `tmp_blind_eval/blind_pilot_batch8_adrenal_hyperkalemia_after_fix6.txt`
- `tmp_blind_eval/blind_pilot_batch8_cumulative_regressions_after_fix5.txt`

## Runtime Fix Themes

- Filled neutral axis alias gaps for real full-text wording without introducing disease-specific observed axes.
- Strengthened high-specificity direct-marker anchors where the observation is genuinely diagnostic, such as direct viral serology/PCR, vascular imaging, pathognomonic CT findings, malignancy biopsy, APS markers, and adrenal insufficiency labs.
- Preserved clinical competition: high-potassium presentations still rank hyperkalemia first when adrenal evidence is absent; adrenal crisis outranks isolated hyperkalemia only when direct adrenal evidence is strong.
- Removed a bad numeric-to-binary shortcut for peak airway pressure and derived dynamic hyperinflation only from clinically appropriate thresholds.
- Added generic derived observations for reusable concepts such as pathologic lymphadenopathy and bulky nodal disease.

## Verification

- `python -m py_compile .\v5_joint_sde_case_test.py .\tmp_blind_eval\make_ranking_case.py`
- Parsed 50/50 new blind extraction JSON files.
- Forbidden extraction fields check: 0 hits.
- Ranking source URL check for 50 new cases: 0 missing.
- Cumulative regression: `Cases loaded for this run: 100`; `Single-manifold validation: 100/100 PASS`.

## Residual Risk

- The current pass rate is still a regression-harness result, not proof that every high-ranked mimic is clinically ideal.
- Some pre-diagnostic cases remain underdetermined by presentation-only evidence; future batches should continue auditing top-10 plausibility, not just top-1.
- The runtime now has many high-specificity anchors, so future fixes should keep checking for anchor overreach against the full rolling set.
