# Holdout integrity log

## 2026-07-20 — first candidate excluded from primary verdict

`PMC7873792` was discovered and selected at approximately 16:30 JST, while the
normative perfect-landing gate seal was not finalized until 16:53:26 JST.
Although the gate author was role-isolated and reports not reading the case, the
strict preregistration contract requires a primary holdout whose identity is
selected **after** the architecture, gate, runtime, and generic model artifacts
are frozen.

Therefore:

- `CASE_SELECTION.md` is retained as an auditable discarded candidate record;
- `PMC7873792` is **not eligible** for the primary perfect-landing verdict;
- its in-progress extraction was stopped before a case ledger was written;
- neither its article nor any impressions from it may be used by the primary
  model builder, mapper, evaluator, or auditor;
- a new case will be selected only after the generic model and runtime seals are
  complete.

This exclusion is a harness-integrity correction, not a clinical or architectural
failure.
