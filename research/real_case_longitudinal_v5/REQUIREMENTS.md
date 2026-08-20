# Requirements and acceptance criteria

## R1. Source and provenance

- Both cases must be real PMC/PubMed case reports.
- Every staged observation must retain its source text and availability time.
- Original active atlas and case artifacts must remain unchanged.

## R2. Time replay

- PMC10448002 cuts: admission; post-biopsy complication; day-6 hematologic
  response; post-day-6 TMA workup ordering cut; discharge.
- PMC7005653 cuts: ICU admission before etiologic workup; early biopsy/HAV
  serology ordering cut; day-2 collapse after initial support but before plasma
  exchange; post-plasma exchange; day 9; day 14.
- Later evidence must not appear in earlier cuts.
- Because the papers omit some exact result times, day 0.5 and day 6.5 are
  declared ordering coordinates. The runtime treats them as numeric time, so
  timing-dependent likelihood at those cuts is an explicit approximation.

## R3. Diagnostic outputs

For each cut record:

- top 10 single disease manifolds;
- rank and score of the paper-supported disease(s);
- best-known versus health-reference delta;
- largest residuals and scored-axis count;
- whether a newly emerging process is represented in the active atlas.

## R4. Dynamic architecture audit

The report must separately answer whether the current runtime:

- carries a shared posterior/state forward between cuts;
- represents discrete mode transitions;
- activates/deactivates comorbid or complication manifolds over time;
- distinguishes treatment support from intrinsic physiologic recovery;
- performs causal counterfactual estimation or only schema-driven simulation.

## R5. Treatment test

- Run live treatment simulation only for active expected manifolds.
- Compare simulator-ranked policies with the paper's actual actions.
- Do not call temporal association a validated treatment effect.

## R6. Decision rule

- **SUPPORTED**: live evidence directly demonstrates the claimed capability.
- **PARTIAL**: a useful approximation exists but a key architecture property is
  absent or unverified.
- **FAILED**: the live runtime contradicts the case or the claimed capability.
- **UNTESTABLE**: the case/runtime does not contain the information needed.
