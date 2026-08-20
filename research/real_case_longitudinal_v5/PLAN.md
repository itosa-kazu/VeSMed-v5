# V5 real-case longitudinal stress test plan

## Objective

Replay two complex published cases from admission to outcome against the current
active V5 atlas without modifying disease distillations or active case files.

## Cases

1. PMC10448002: complement-mediated TMA initially treated as anti-GBM disease.
2. PMC7005653: hepatitis A acute liver failure with a day-2 Takotsubo/cardiogenic-shock transition.

## Execution

1. Build immutable cumulative evidence cuts using only information available at
   each clinical time point.
2. Run the current geometry-first diagnosis runtime against all active disease
   manifolds at every cut.
3. Run repeated-axis history-collision and action-history ablations, then record
   exactly which parts of history survive the current nearest-value-per-axis
   preparation step. Do not overclaim a full history-vs-snapshot benchmark.
4. Run the current treatment-vector-field simulator only where the expected
   active manifold and treatment schema support the query.
5. Audit state-transition, comorbidity/OOD, observation/action separation,
   counterfactual-identification, and provenance behavior.
6. Preserve failures. Do not repair distillations from these cases during this
   experiment.

## Deliverables

- `FIRST_PRINCIPLES.md`
- `REQUIREMENTS.md`
- staged case JSONs under `staged_cases/`
- reproducible harness and machine-readable results
- Chinese evidence report with exact runtime boundaries
