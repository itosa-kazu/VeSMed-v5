# Final Architecture Holdout Protocol

> This file is the high-level overview.  The normative, executable primary
> protocol is `PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.md/.json`, with frozen
> scoring in `PRIMARY_HOLDOUT_SCORING_v1.json`.  Any conflict is resolved in
> favor of those versioned contracts and their combined pre-primary seal.

## Objective

Freeze the revised new clinical-map architecture, then test one previously
unused real longitudinal case from admission to terminal reported outcome.  The
experiment is independent of VeSMed V5.

## Separation of roles

1. **Architecture freeze** sees no holdout case.
2. **Gate, runtime, and generic-model freeze** see no primary holdout case.
3. **Primary case selection occurs only after those seals exist.** The case
   scout/extractor sees the source article but not the runtime model or
   its scoring behavior.
4. **Generic clinical model builder** receives only a broad presentation domain
   and a diagnosis-neutral schema; it does not receive the case event stream,
   values, chronology, or reported outcome.
5. **Concept mapper** receives only the frozen model node registry and a set of
   diagnosis-neutral source concept identifiers; it does not receive values,
   chronology, hypotheses, or outcomes.
6. **Runtime evaluator** consumes sealed artifacts and may not feed holdout
   failures back into the model during the primary run.
7. **Independent auditor** verifies seals, no-future leakage, gate coverage, and
   conclusion boundaries.

## Frozen artifacts before primary replay

- final architecture specification and machine schema;
- perfect-landing gate specification;
- generic process/factor/dynamics model pack;
- diagnosis-neutral event ledger;
- concept map;
- source and artifact hashes.

For the primary preregistered verdict, the architecture, gate, runtime and
generic-model seals must also predate selection of the case identity. A case
seen earlier may be retained as a rehearsal case but is ineligible for the
primary verdict.

## Primary replay

At every information cut:

```text
public event delta
  -> recursive SharedPatientState update
  -> concurrent active-process posterior
  -> per-process/organ local coordinates and modes
  -> no-new-action forecast
  -> registered-action forecasts and feasibility
  -> OOD/epistemic residual
```

All queries must consume exact same canonical state bytes.  Later source facts
are used only after the relevant cut and only for post-hoc scoring.

## Interpretation

`PERFECT_LANDING_WITHIN_FROZEN_CASE_SCOPE` is allowed only when the executable
final scorer receives exactly all 30 frozen hard gates as `PASS` and every
frozen complex real-case coverage item as `PASS`. Missing, duplicate, unknown,
not-executed, evidence-missing or not-applicable hard gates are
`HARNESS_INCOMPLETE`; a complete evaluated bundle with any failure is
`FAILED`. A correct final label alone is insufficient.  If any required capability is absent or a
clinically decisive observation is outside the frozen model, report the exact
failure class: architecture, implementation, model/content, data/evidence, or
unidentifiable.

Every gate and complex-case coverage result must reference a content-addressed
evidence object that is inside the sealed study root and binds the exact subject
ID, claimed result, machine-checkable assertions, source path, and SHA-256.
Missing, stale, cross-gate, or internally inconsistent evidence is
`HARNESS_INCOMPLETE`; a bare path or prose claim can never satisfy a gate.

No real case report identifies the patient's untreated individual
counterfactual.  Treatment-effect claims must therefore remain
`UNIDENTIFIABLE` unless supported by separately identified evidence within the
frozen scope.
