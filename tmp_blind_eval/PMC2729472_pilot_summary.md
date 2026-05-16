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
- Ranking output: `tmp_blind_eval/blind_PMC2729472_result.txt`

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

Top single-manifold ranks from `tmp_blind_eval/blind_PMC2729472_result.txt`:

1. 急性胆嚢炎 / Acute cholecystitis / `D-ACUTE-CHOLECYSTITIS`: logP -207.96
2. 急性A型肝炎 / Acute hepatitis A / `D-ACUTE-HEPATITIS-A`: logP -220.09
3. 急性膵炎 / Acute pancreatitis / `D-ACUTE-PANCREATITIS`: logP -420.94
4. 急性E型肝炎 / Acute hepatitis E / `D-ACUTE-HEPATITIS-E`: logP -439.47
5. 急性B型肝炎 / Acute hepatitis B / `D-ACUTE-HEPATITIS-B`: logP -455.18
6. 腸閉塞 / Bowel obstruction / `D-BOWEL-OBSTRUCTION`: logP -486.06
7. 絞扼性腸閉塞 / Strangulated bowel obstruction / `D-STRANGULATED-BOWEL-OBSTRUCTION`: logP -490.52
8. 消化管穿孔 / Perforated viscus / `D-PERFORATED-VISCUS`: logP -520.05
9. 急性虫垂炎 / Acute appendicitis / `D-APPENDICITIS`: logP -553.27
10. 急性胆管炎 / Acute cholangitis / `D-ACUTE-CHOLANGITIS`: logP -605.15

Validation: PASS. Expected `D-ACUTE-CHOLECYSTITIS`, best single was `D-ACUTE-CHOLECYSTITIS`.

OOD/null model:

- `logP_best_known = -207.96`
- `logP_background_only = -537.59`
- `delta_to_null_best_known = +329.64`

## Plausibility Audit

- First rank is correct and supported by RUQ pain, Murphy sign, CT gallbladder wall thickening, pericholecystic fluid, and gallstones.
- Acute pancreatitis, bowel obstruction, perforated viscus, appendicitis, and cholangitis are plausible broad abdominal differentials, but their lower ranks are appropriate for this evidence set.
- Acute hepatitis A ranking second is medically suspicious because the case reports normal bilirubin, AST, and ALT. This suggests the hepatitis manifolds or runtime scoring are not sufficiently penalizing normal transaminases/bilirubin when abdominal pain and mild ALP elevation are present.
- The runner still required a normalized ranking copy because blind extraction can produce reasonable generic aliases that the current runtime does not consume directly. A future batch tool should automate this alias-normalization layer and report every alias conversion.

## Takeaway

The second full-text blind extraction workflow also runs end to end. Top-1 passed and the main differential list is mostly plausible, but the new non-top plausibility standard found a remaining issue: acute hepatitis manifolds can sit too high despite normal hepatocellular labs.
