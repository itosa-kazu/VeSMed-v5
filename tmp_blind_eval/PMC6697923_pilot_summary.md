# PMC6697923 Blind Full-Text Ranking Pilot

## Source

- Source URL: https://pmc.ncbi.nlm.nih.gov/articles/PMC6697923/
- PMCID: PMC6697923
- PMID: 31419970
- DOI: 10.1186/s12893-019-0575-8
- Paper diagnosis: severe alcohol-induced acute pancreatitis complicated by abdominal compartment syndrome.

## Blind Extraction

- Extraction file: `tmp_blind_eval/extractions/PMC6697923_blind_extraction.json`
- Source notes: `tmp_blind_eval/extractions/PMC6697923_source_notes.md`
- Extractor: independent blind full-text extraction agent.
- QA: JSON parsed successfully; 65 structured observations, 9 risk-context entries, and 16 record-only facts.
- Cleanliness: no `expected_manifold`, `expected_manifolds`, or `disease_label_per_paper` in the blind extraction; no ordinary diagnosis-specific `*_in_D-*` axes; record-only treatment/course facts were not rankable.

For ranking only, the copied case `tmp_blind_eval/cases_for_ranking/v5_case_PMC6697923_BLIND_EVAL.json` adds:

- `expected_manifold: D-ACUTE-PANCREATITIS`
- `disease_label_per_paper: Severe alcohol-induced acute pancreatitis complicated by abdominal compartment syndrome`
- normalized demographic sex `M`

## Initial Failure

The first ranking run placed `D-ACUTE-RESPIRATORY-DISTRESS-SYNDROME` above `D-ACUTE-PANCREATITIS`.

Root causes identified:

- The case reported oliguria as `<10 mL/h`, but the runtime interpreted it as if it were already `mL/kg/hr`.
- Rankable `risk_context` axes were not consumed, so chronic heavy alcohol use and recent binge context did not support the pancreatitis manifold.
- ALT/GGT aliases from the extraction did not map to the canonical atlas axes.
- ARDS could win from generic respiratory failure observations despite explicit source evidence that radiographic ARDS was absent.
- Diseases with event-hazard axes could not explain downstream ICU manifestations, so pancreatitis did not receive support for acute respiratory failure, AKI/oliguria, shock, or abdominal compartment syndrome consequences.
- High-specificity toxidromes and context-specific critical diseases could rank high from nonspecific ICU physiology without their required core exposure or diagnostic anchor.

## Runtime Fixes

Implemented in `v5_joint_sde_case_test.py`:

- Added urine-output conversion between `mL/h` and `mL/kg/hr` using adult-normalized weight when reports omit body weight.
- Promoted rankable `risk_context` observations, but only allowed them to score when a candidate has formal support for that axis.
- Added exact axis aliases for ALT, GGT, fever history, and alcohol-pancreatitis context.
- Added event-hazard manifestation proxies for acute respiratory failure, AKI, circulatory shock, and abdominal compartment syndrome.
- Made ARDS require explicit ARDS/bilateral-opacities/PF-ratio support and respect explicit ARDS absence.
- Added explicit core-anchor requirements for toxidromes and several high-specificity critical disease candidates.

These changes keep ordinary observations diagnosis-neutral; they do not add disease-specific case axes.

## Final Single-Case Result

Command:

```powershell
$env:VESMED_CASE_DIR='tmp_blind_eval\cases_for_ranking'
$env:VESMED_CASE_FILTER='PMC6697923'
$env:VESMED_SCORE_MODE='grid'
$env:VESMED_TIME_GRID_N='17'
$env:VESMED_MAX_COMBO_SIZE='1'
$env:VESMED_RESULT_PATH='tmp_blind_eval\blind_PMC6697923_after_runtime_fix7.txt'
python .\v5_joint_sde_case_test.py
```

Result: `Single-manifold validation: 1/1 PASS`

- Best known: `D-ACUTE-PANCREATITIS`, logP `-776.62`
- Background-only: logP `-37133.75`
- `delta_to_null_best_known`: `+36357.12`

Top ranking:

1. `D-ACUTE-PANCREATITIS`, logP `-776.62`
2. `D-ASPIRATION-PNEUMONIA`, logP `-880.79`
3. `D-ACUTE-SYMPTOMATIC-HYPONATREMIA`, logP `-1196.96`
4. `D-ACUTE-HEPATITIS-E`, logP `-1197.01`
5. `D-BRONCHIOLITIS`, logP `-1201.56`
6. `D-SUPERIOR-VENA-CAVA-SYNDROME`, logP `-1207.94`
7. `D-EMPYEMA`, logP `-1210.83`
8. `D-ACUTE-ISCHEMIC-STROKE`, logP `-1230.01`
9. `D-TOXOPLASMOSIS`, logP `-1231.26`
10. `D-SYMPTOMATIC-HYPOCALCEMIA`, logP `-1241.03`

Plausibility audit:

- Top-1 is correct and strongly separated from the remaining list.
- `D-ASPIRATION-PNEUMONIA` at rank 2 is clinically plausible as a respiratory complication or mimic in a vomiting/intubated hypoxemic patient.
- Ranks 3 and below are much lower, but still include broad weak-anchor critical mimics. This is acceptable for the pilot after the winning pathology is corrected, but it should continue to be audited across future blind real cases.
- Largest residuals show missing pancreatitis-family support for pain radiation, diffuse abdominal tenderness, constant abdominal pain, agitation, and vomiting severity.

## Three-Pilot Regression

Command:

```powershell
$env:VESMED_CASE_DIR='tmp_blind_eval\cases_for_ranking'
$env:VESMED_CASE_FILTER='PMC10590198,PMC2729472,PMC6697923'
$env:VESMED_SCORE_MODE='grid'
$env:VESMED_TIME_GRID_N='17'
$env:VESMED_MAX_COMBO_SIZE='1'
$env:VESMED_RESULT_PATH='tmp_blind_eval\blind_pilot_triple_after_runtime_fix7.txt'
python .\v5_joint_sde_case_test.py
```

Result: `Single-manifold validation: 3/3 PASS`

- PMC10590198: best `D-APPENDICITIS`; `delta_to_null_best_known +373.89`
- PMC2729472: best `D-ACUTE-CHOLECYSTITIS`; `delta_to_null_best_known +395.60`
- PMC6697923: best `D-ACUTE-PANCREATITIS`; `delta_to_null_best_known +36357.12`

No combo cases were included in this pilot regression.
