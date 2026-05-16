# PMC10590198 blind full-text extraction pilot

## Source

- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC10590198/
- PMCID: PMC10590198
- PMID: 37868373
- Case: 34-year-old male with acute right lower quadrant abdominal pain, mild systemic symptoms, focal RLQ tenderness/guarding, and preoperative CT showing appendicolith, 18 mm enlarged appendix, wall thickening, mild RLQ free fluid, and no loculated collection.

## Files

- Blind extraction: `tmp_blind_eval/extractions/PMC10590198_blind_extraction.json`
- Source notes: `tmp_blind_eval/extractions/PMC10590198_source_notes.md`
- Ranking input copy with expected label added only for evaluation: `tmp_blind_eval/cases_for_ranking/v5_case_PMC10590198_BLIND_EVAL.json`
- Ranking output: `tmp_blind_eval/blind_PMC10590198_result.txt`
- Ranking output after runtime fix: `tmp_blind_eval/blind_PMC10590198_after_runtime_fix.txt`
- Baseline existing-JSON output: `tmp_blind_eval/baseline_PMC10590198_result.txt`

## Extraction QA

- The blind extraction file has no `expected_manifold`, `expected_manifolds`, or `disease_label_per_paper` field.
- Ranking evidence items: 29 pre-treatment observations/imaging findings.
- Record-only items with `use_in_ranking` true: 0.
- Disease-encoded ordinary observation axes: 0.
- The explicit negative vomiting statement was encoded as `vomiting_presence = 0.0`.

## Initial Blind Ranking Result

Top single-manifold ranks from `tmp_blind_eval/blind_PMC10590198_result.txt`:

1. 消化管穿孔 / Perforated viscus / `D-PERFORATED-VISCUS`: logP -266.88
2. 卵管卵巣膿瘍 / Tubo-ovarian abscess / `D-TUBO-OVARIAN-ABSCESS`: logP -305.20
3. 急性憩室炎 / Acute diverticulitis / `D-DIVERTICULITIS`: logP -311.30
4. 骨盤内炎症性疾患 / Pelvic inflammatory disease / `D-PELVIC-INFLAMMATORY-DISEASE`: logP -311.59
5. 急性虫垂炎 / Acute appendicitis / `D-APPENDICITIS`: logP -317.33
6. 潰瘍性大腸炎重症再燃 / Ulcerative colitis severe flare / `D-ULCERATIVE-COLITIS-SEVERE-FLARE`: logP -317.56
7. クローン病再燃 / Crohn disease flare / `D-CROHN-DISEASE-FLARE`: logP -325.66

Validation: FAIL. Expected `D-APPENDICITIS`, best single was `D-PERFORATED-VISCUS`.

OOD/null model:

- `logP_best_known = -266.88`
- `logP_background_only = -437.91`
- `delta_to_null_best_known = +171.04`

## Plausibility Audit

- `D-PERFORATED-VISCUS` is not a reasonable first rank for this preoperative presentation: CT did not report free air or a perforation finding, vitals were stable, and the case specifically had appendiceal-localizing CT evidence.
- `D-TUBO-OVARIAN-ABSCESS`, `D-PELVIC-INFLAMMATORY-DISEASE`, and `D-ECTOPIC-PREGNANCY` appearing high in a male case indicates the current ranking pipeline is not sufficiently applying sex/anatomic impossibility as prior/context gating.
- `D-DIVERTICULITIS`, `D-CROHN-DISEASE-FLARE`, and possibly `D-ULCERATIVE-COLITIS-SEVERE-FLARE` are plausible broad GI mimics, but they should not outrank appendicitis when appendicolith + 18 mm appendix + wall thickening are present.
- The blind extraction improves source fidelity compared with the existing structured case because it correctly preserves the negative vomiting statement.

## Takeaway

The full-text blind extraction workflow is feasible and catches extraction-quality issues. The initial ranking failure was traced to runtime ingestion and feasibility gaps rather than the blind extraction itself.

## Runtime Fix and Post-Fix Result

Applied runtime fixes in `v5_joint_sde_case_test.py`:

- `imaging` / mapped evidence sections now consume direct `axis_id` records, not only legacy `mapped_axis_id(s)` / `mapped_axes`. This lets blind extractor output such as `appendicolith_presence`, `appendiceal_diameter_mm`, and `appendiceal_wall_thickening_activity` enter likelihood scoring.
- Case JSON loading accepts UTF-8 BOM with `utf-8-sig`.
- Sex/anatomic feasibility prior strongly penalizes anatomically impossible reproductive leaves, e.g. male case vs tubo-ovarian abscess / PID / ectopic pregnancy / ovarian torsion.
- `D-APPENDICITIS` anchor support now explicitly recognizes appendicolith, appendiceal diameter, appendiceal dilation, appendiceal wall thickening, periappendiceal inflammatory findings, and RLQ pain.

Post-fix top single-manifold ranks from `tmp_blind_eval/blind_PMC10590198_after_runtime_fix.txt`:

1. 急性虫垂炎 / Acute appendicitis / `D-APPENDICITIS`: logP -330.98
2. 消化管穿孔 / Perforated viscus / `D-PERFORATED-VISCUS`: logP -534.71
3. 急性憩室炎 / Acute diverticulitis / `D-DIVERTICULITIS`: logP -579.10
4. 潰瘍性大腸炎重症再燃 / Ulcerative colitis severe flare / `D-ULCERATIVE-COLITIS-SEVERE-FLARE`: logP -584.52
5. クローン病再燃 / Crohn disease flare / `D-CROHN-DISEASE-FLARE`: logP -592.63

Validation: PASS. Expected `D-APPENDICITIS`, best single was `D-APPENDICITIS`.

OOD/null model after fix:

- `logP_best_known = -330.98`
- `logP_background_only = -704.87`
- `delta_to_null_best_known = +373.89`

Post-fix plausibility audit:

- The first rank is correct.
- The next ranks are plausible broad abdominal differentials rather than anatomically impossible pelvic/reproductive diagnoses.
- Female reproductive candidates are still reported but are pushed down by feasibility prior when the case demographics report male sex.
