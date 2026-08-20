# New Clinical Framework Runtime v2.1

Status: `EXECUTABLE_SKELETON / NOT_CLINICALLY_CALIBRATED`  
Boundary: this package is independent of VeSMed V5 and contains no case-specific rule.

## 1. Why v2 exists

The first research runtime proved useful serialization and query-purity contracts,
but its runtime state was internally inconsistent with its own model cards: known
branches were forced onto one simplex, every branch copied one global mode,
negative observations could only add evidence, topology was a detached utility,
action exposure had no lifecycle, OOD mass was mostly a count heuristic, and a
model refinement made old states unreadable.

Runtime v2 replaces those placeholders with one small, explicit computation
contract.  It is deliberately a finite exact engine, not a clinical product.

## 2. Frozen state equation

For a declared task scope, the shared state is:

```text
S_t = (
  P(Z_1..Z_n, U | H_t),
  {q_i(x_i), q_i(m_i), q_i(s_i)} for every declared process i,
  action lifecycle ledger,
  finite history/evidence summaries,
  epistemic residuals,
  schema/model/migration lineage
)
```

Where:

- `Z_i in {0,1}` is whether known process `i` is active.  Multiple `Z_i` may be
  one simultaneously.  They never compete for a single 100% disease vote.
- `U in {0,1}` is an unmodelled-process hypothesis.  It may coexist with known
  processes; it is not merely an `other` class.
- `x_i` is a process-local continuous coordinate vector.  Coordinates from two
  different processes are not silently treated as the same axis.
- `m_i` is that process's own discrete mode distribution.  Different organs or
  processes may be recovering and decompensating at the same time.
- `s_i` is an optional process-local behavioral stratum. It exists only after
  a demonstrated collision and never replaces the process activation bit.
- `H_t` contains only public events available at cut `t`.

The exact joint table is intentionally limited to small research scopes.  The
validator rejects more than `inference.max_exact_processes` processes rather
than silently pretending the factorial posterior is a flat ranking.

## 3. Typed signed emission factors

An observation declares a value type and one or more process emission factors.
Each factor has an active and inactive distribution from the same typed family:

```text
LLR_i(y) = log p(y | Z_i=1) - log p(y | Z_i=0)
```

Implemented families are:

- `bernoulli` (`p_true`),
- `categorical` (`probabilities`),
- `gaussian` (`mean`, `sd`).

Consequently a reliable negative assay can produce a negative LLR and refute a
process.  Each consumed observation records its signed direct and topologically
propagated contributions.  The runtime is a declared log-linear factor engine;
these likelihoods are not claimed to be calibrated clinical frequencies.

`source_result_id` is the common-parent evidence identity. Repeated renderings or
different derived child factors from one public source cannot multiply evidence.
Reusing an `event_id` with changed bytes is an error rather than a silent
overwrite. Every event also carries provenance, an occurrence interval, record
time and availability time; observations separately carry sample and result
times. Non-rankable facts emit a neutral disposition message instead of silently
disappearing from the evidence denominator.

## 4. Factorial inference and topology

Initialization enumerates all configurations of the known process bits and the
unknown bit.  Independent activation priors and optional co-activation log
potentials define the initial joint table.  Observation factors update that
table exactly and it is renormalized with log-sum-exp.

Topology is part of inference, not a display-only distance:

```text
propagated_LLR(j) = direct_LLR(i)
                    * inference_coupling
                    * exp(-shortest_path_distance(i,j) / distance_scale)
```

The coefficient is scope-declared and may be zero.  The evidence trace exposes
every propagated term.  A topology ablation therefore changes the posterior.
This is only a minimum geometry kernel; it does not identify medically correct
edge lengths or couplings.

## 5. Process-local coordinates and modes

Every process declares its own coordinate chart, priors, bounds and objective
weights.  An emission may also declare a typed coordinate measurement update.
Every process separately declares mode priors and coordinate drift by mode.  A
typed observation can update only the named process's mode posterior.
Optional executable guards transfer mode probability only at declared enter
thresholds and reverse it only at separate exit thresholds; values between the
two thresholds produce an explicit hysteresis hold. A runtime ablation disables
guards without changing any other model term.

Forward dynamics combine:

1. posterior-weighted drift from that process's local modes;
2. active/washout action effects;
3. declared cross-process coordinate couplings;
4. topology-mediated action spillover.

Thus one process can recover while another decompensates, and one organ process
can alter another's future without collapsing them into one global label.

## 6. Action lifecycle

Only performed lifecycle events affect state:

- `ActionStarted`,
- `ActionContinued`,
- `ActionDoseChanged`,
- `ActionHeld`,
- `ActionStopped`,
- `ActionCompleted`.

Each exposure instance stores start time, last update, dose, cumulative
exposure, active/held/stopped/completed status, lifecycle cursors, and remaining washout.  Advancing
time accrues exposure before applying events.  Stopping an action ends new
exposure and starts its declared washout; it is therefore observably different
from continuing it.  Planned actions are record-only and do not alter dynamics.

Candidate policies can start, continue, hold, dose-change or stop exposures and
are simulated on a copy of the exact shared state. `UNIDENTIFIABLE` and
`OUT_OF_SCOPE` policies are returned with traces but cannot be selected. Diagnosis, natural
forecast and every policy rollout report the same consumed state hash.

## 7. OOD and epistemic residuals

The state reports separate quantities rather than one magic unknown score:

- `unknown_process_probability`: marginal posterior of `U`;
- `mapping_residual`: beta-smoothed fraction of rankable observations that the
  model could not map;
- `model_misfit_residual`: bounded summary of poor likelihood under every known
  emission for mapped observations, including independent-source measurement
  conflicts;
- counts of mapped, unmapped and deduplicated evidence.

A mapped observation can update the unknown bit through declared
`unknown_likelihood` versus `reference_likelihood`.  An unmapped observation
updates it through the scope-declared `unmapped_event_log_bayes_factor`.  The
runtime returns the continuous residuals and does not hard-code a clinical
abstention threshold.

Every rollout also emits bounded truncated-normal coordinate support and
categorical activation, direction and local-mode support.
`score_predictive_support` applies their frozen log score and reports
zero/undefined support explicitly.

## 8. Topology in planning

Action effects name a target process and local coordinate.  When enabled, a
declared `planning_coupling` and shortest-path kernel propagate part of that
effect to neighboring processes.  The rollout records direct and spillover
terms.  The planner minimizes a declared expected coordinate burden plus action
cost.  Removing topology can therefore change both simulated trajectories and
policy selection.

This proves integration only.  It does not establish a valid treatment effect,
utility function, dose-response curve or patient-level counterfactual.

## 9. Versioning and migration

State and model have independent schema versions and a model digest.  Normal
updates require an exact digest match.  Cross-version reading is possible only
through an explicit migration record that names process, coordinate, mode and
action mappings.

Two executable paths are supplied:

1. v2-to-v2 model migration, which aggregates mapped joint configurations and
   expands newly introduced processes from their declared priors;
2. legacy v1-state import, which converts the old mutually exclusive simplex
   into an independent factorial approximation and records that information
   loss in migration warnings.

No migration is silent.  The target state records source hash, source and target
model digests, migration id, warnings and dropped identifiers.

Behavioral refinement has an additional fail-closed path. The finite collision
evaluator requires two compatible worlds with the same old-state signature and
old-action behavior but opposite response to a new action. Without a registered
available separating observation it returns `UNIDENTIFIABLE` and changes no
model. With one, only the implicated process gets child strata and an explicit
migration is emitted. Before consuming the separator, diagnosis, natural
forecast, every unaffected action rollout and the restricted unaffected plan
are frozen and rerun at absolute tolerance `1e-12`; drift fails closed.

## 10. Runtime invariants

1. Joint configuration probabilities are finite, non-negative and sum to one.
2. Marginals are derived from, never stored independently of, that joint table.
3. All local coordinates remain within declared bounds.
4. Every process has its own normalized mode posterior.
5. Future events cannot affect an earlier cut.
6. Duplicate delivery is exactly-once; conflicting reuse of an event id fails.
   After a cold restore this guarantee requires the state-bound, content-addressed
   ledger sidecar because the frozen architecture wire exposes only an aggregate
   digest and processed IDs. Missing proof fails closed.
7. Planned actions cannot alter exposure or dynamics.
8. Query methods are pure and consume the same canonical state bytes.
9. A changed model digest requires an explicit migration.
10. Execution switches are part of that digest and cannot reinterpret one state.
11. All inference, topology and action contributions are traceable.

## 11. Implemented versus deliberately absent

Implemented in this directory:

- exact small-scope factorial posterior including a coexisting unknown bit;
- typed signed emissions and negative evidence;
- common-parent source deduplication and event idempotency;
- process-local coordinates and mode posteriors;
- cross-process drift coupling;
- complete start/continue/hold/dose-change/stop/complete/washout action bookkeeping;
- candidate policies that can continue, hold, dose-change or stop existing exposures;
- planner exclusion of `UNIDENTIFIABLE` and `OUT_OF_SCOPE` policies;
- topology in inference and action planning;
- executable mode guards with separated enter/exit hysteresis thresholds;
- decomposed OOD residuals;
- typed event provenance/time semantics, record-only disposition and conflict residuals;
- continuous/discrete predictive support with a frozen scoring API;
- strict `SharedPatientStateV1` canonical serialization, content-addressed ledger
  proof, model binding and explicit migration;
- executable behavioral collision evaluation and local-only stratum refinement;
- typed `UNIDENTIFIABLE` when collision worlds lack separating public information;
- full unaffected-query non-regression enforcement across refinement;
- deterministic unit tests and a runnable neutral demo.

Not implemented or not established:

- particle/variational inference for large process atlases;
- learning, calibration, uncertainty intervals or clinical parameter sources;
- joint multivariate residual/censoring/missing-not-at-random measurement models;
- learned or fitted stochastic mode-jump/guard parameters;
- causal identification of treatment effects;
- atlas-scale automatic collision search (the finite witness evaluator and local
  refinement execution path are implemented);
- clinical utility/QALY/safety constraints;
- any claim that a real case is diagnosed, forecast or treated correctly.

The next valid experiment is to freeze a generic v2 model independently, then
map and replay a new real case without altering the runtime or model from that
case's expected answer.
