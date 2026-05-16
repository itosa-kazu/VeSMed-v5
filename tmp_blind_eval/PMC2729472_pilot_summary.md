# PMC2729472 blind full-text extraction pilot

## Source

- URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC2729472/
- PMCID: PMC2729472
- PMID: 19707473
- Case: 68-year-old male with 2 days of worsening right upper quadrant pain, nausea/vomiting, no fever/chills, RUQ tenderness, Murphy sign, normal WBC, normal bilirubin/transaminases, mildly elevated alkaline phosphatase, and CT showing gallbladder wall thickening, pericholecystic fluid, and multiple gallstones.

## Files

- Blind extraction: `tmp_blind_eval/extractions/PMC2729472_blind_extraction.json`
- Source notes: `tmp_blind_eval/extractions/PMC2729472_source_notes.md`
- Ranking input copy with expected label and runtime-only alias normalization: `tmp_blind_eval/cases_for_ranking/v5_case_PMC2729472_BLIND_EVAL.json`
- Initial ranking output: `tmp_blind_eval/blind_PMC2729472_result.txt`
- Final ranking output after runtime fixes: `tmp_blind_eval/blind_PMC2729472_after_runtime_fix6.txt`

## Extraction QA

- The blind extraction file has no `expected_manifold`, `expected_manifolds`, or `disease_label_per_paper` field.
- Record-only items with `use_in_ranking` true: 0.
- Disease-encoded ordinary observation axes: 0.
- Negative evidence was preserved for fever and chills.
- Operative management, gallstone composition, paper interpretation, and postoperative course were record-only.

## Ranking-Copy Normalization

The blind extraction used valid generic concepts, but several were not directly consumed by the current runner. The ranking copy only normalized runtime representation:

- Flattened `diagnostics.labs` into top-level `labs`.
- Normalized demographic sex from `male` to `M`.
- Mapped aliases such as `aspartate_aminotransferase -> serum_ast`, `alanine_aminotransferase -> serum_alt`, `fever_presence -> fever_history_presence`.
- Mapped `cholelithiasis_sludge_context_probability -> gallstone_or_biliary_sludge_context_probability` for the current registry/runtime.

## Blind Ranking Result

Initial output `tmp_blind_eval/blind_PMC2729472_result.txt` passed top-1 but exposed a non-top plausibility failure: acute viral hepatitis ranked too high despite normal bilirubin, AST, and ALT.

Final output after runtime fixes: `tmp_blind_eval/blind_PMC2729472_after_runtime_fix6.txt`.

Top single-manifold ranks:

1. 急性胆嚢炎 / Acute cholecystitis / `D-ACUTE-CHOLECYSTITIS`: logP -142.01
2. 急性膵炎 / Acute pancreatitis / `D-ACUTE-PANCREATITIS`: logP -429.03
3. 憩室炎 / Diverticulitis / `D-DIVERTICULITIS`: logP -448.50
4. バッド・キアリ症候群 / Budd-Chiari syndrome / `D-BUDD-CHIARI-SYNDROME`: logP -470.01
5. 腸閉塞 / Bowel obstruction / `D-BOWEL-OBSTRUCTION`: logP -486.06
6. 化膿性肝膿瘍 / Pyogenic liver abscess / `D-PYOGENIC-LIVER-ABSCESS`: logP -488.65
7. 絞扼性腸閉塞 / Strangulated bowel obstruction / `D-STRANGULATED-BOWEL-OBSTRUCTION`: logP -489.66
8. アメーバ性肝膿瘍 / Amoebic liver abscess / `D-AMOEBIC-LIVER-ABSCESS`: logP -498.41
9. 腎盂腎炎 / Pyelonephritis / `D-PYELONEPHRITIS`: logP -501.90
10. 消化管穿孔 / Perforated viscus / `D-PERFORATED-VISCUS`: logP -520.05

Validation: PASS. Expected `D-ACUTE-CHOLECYSTITIS`, best single was `D-ACUTE-CHOLECYSTITIS`.

OOD/null model:

- `logP_best_known = -142.01`
- `logP_background_only = -537.60`
- `delta_to_null_best_known = +395.60`

## Runtime Fixes

- Fixed likelihood sigma coordinate mixing when disease axes are log-scale but background overrides are linear/raw-scale. Normal AST/ALT now penalize hepatitis-like diseases in the same evaluation space.
- Added bidirectional alias bridging for `cholelithiasis_sludge_context_probability` and `gallstone_or_biliary_sludge_context_probability`.
- Added explicit core-anchor requirements for acute viral hepatitis, dengue, and acetaminophen toxicity so nonspecific abdominal or gallbladder findings cannot substitute for disease-defining evidence.
- Expanded male-case anatomic gating to include Fitz-Hugh-Curtis syndrome, postpartum endometritis, peripartum cardiomyopathy, and septic abortion.

## Plausibility Audit

- First rank is correct and supported by RUQ pain, Murphy sign, CT gallbladder wall thickening, pericholecystic fluid, and gallstones.
- The remaining top alternatives are abdominal/hepatobiliary mimics rather than impossible sex/anatomic candidates or viral/toxic hepatitis without core evidence.
- Acute hepatitis A moved down to logP -630.70, dengue to -776.87, and acetaminophen toxicity to -901.41.
- The runner still required a normalized ranking copy because blind extraction can produce reasonable generic aliases that the current runtime does not consume directly. A future batch tool should automate this alias-normalization layer and report every alias conversion.

## Takeaway

The second full-text blind extraction workflow runs end to end under the stricter standard: top-1 is correct, and the leading non-top diseases are now medically plausible broad abdominal/hepatobiliary differentials.
