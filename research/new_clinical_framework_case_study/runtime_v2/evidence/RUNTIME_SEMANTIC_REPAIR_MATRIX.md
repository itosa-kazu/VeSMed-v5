# NCF Runtime v2 semantic repair matrix

Status: **INDEPENDENTLY VERIFIED COMPONENT CANDIDATE — not a clinical-validity claim**  
Architecture: `NCF-ARCH-1.0.0`  
Scope: `runtime_v2` only; VeSMed V5 is explicitly out of scope.

## Verification snapshot

The following checks were rerun after the last runtime source change (the
Boolean-history cold-query repair):

- complete runtime suite: **132/132 PASS**;
- semantic probe suite: **23/23 PASS**;
- frozen-schema representative states: **7/7 PASS** (completed exposure,
  delayed evidence, migration, refinement, OOD, dynamic activation, canonical
  deserialization);
- ledger + refinement + structural focused suite: **19/19 PASS**;
- structural harness: **24/24 PL gates PASS; G01--G17 PASS**;
- generic 13-process model: **9/9 content checks and 11/11 runtime probes PASS**;
- `compileall`: **PASS**.

The root coordinator independently repeated the 132-test runtime suite, the
23 semantic probes, the structural harness and the generic checks on the same
source snapshot.  The evidence is bound by the final component manifest; this
matrix is not itself a combined-study seal.

## Closed runtime counterexamples

`VERIFIED` means that the implementation fix, a focused regression, the full
runtime suite, and the independent rerun all passed on the same source
snapshot.  It does not mean that the generic parameters are clinically
calibrated.

| ID | Contract area | Decisive pre-fix counterexample | Implemented closure | Status |
|---|---|---|---|---|
| W01 | shared posterior | Rehashed marginal disagreed with the joint and heads diverged | Redundant posterior views are recomputed and compared | VERIFIED |
| W02 | claim provenance | A rehashed `UNIDENTIFIABLE -> IDENTIFIED` edit authorized a counterfactual | Claims are rederived from the frozen model/state | VERIFIED |
| W03 | local modes | Schema-valid mass 1.5 was published then silently normalized | IDs, domains and normalization are validated at every public boundary | VERIFIED |
| W04 | scope/lineage | A forged scope/digest could describe a different runtime | Full model-bound scope and registry equality | VERIFIED |
| W05 | materialized digests | Factor/action/history bodies could disagree with their digests | All materialized digests and referential closures are recomputed | VERIFIED |
| H01 | numeric history | Cold restore lost previous/trend/count and changed the next update | Typed sufficient numeric history survives warm/cold replay byte-exactly | VERIFIED |
| H02 | Boolean history | `True -> False` was treated as numeric trend `-1`, producing a warm state that cold query could not decode | Boolean values are excluded from quantitative trend calculation; count/provenance remain; third update is warm/cold byte-exact | VERIFIED |
| A01 | lifecycle time | Late-reported start accrued from the wrong time | Retrospective lifecycle changes require replay/smoothing and otherwise fail closed | VERIFIED |
| A02 | exact-source action | Same source under a new event id could apply twice | Content-bound semantic identity and exact-once source handling | VERIFIED |
| A03 | plan to start | Planned and performed records split lineage | Deterministic plan-to-start lifecycle migration | VERIFIED |
| A04 | dose/unit | Negative/NaN/incompatible doses entered rollout | Finite nonnegative dose and declared-unit validation | VERIFIED |
| A05 | hold/stop | Hold and stop were behaviorally indistinguishable | Resumable hold, terminal stop, and policy lifecycle are distinct | VERIFIED |
| A06 | completion/washout | Completion lost residual effect or emitted an illegal operation | Legal completed state plus decaying residual in warm/cold paths | VERIFIED |
| A07 | exposure identity | Restart overwrote an earlier exposure | Immutable action-instance identity and lineage | VERIFIED |
| A08 | unknown action | Unregistered performed action disappeared after a warning | Unknown performed action fails closed / remains typed OOD | VERIFIED |
| A09 | continuing causal claim | Natural forecast ignored an ongoing unidentifiable exposure | Identification status covers every continuing exposure | VERIFIED |
| T01 | time advance | Clock-only update and forecast used different physiology | One transition kernel for factual advance and forecast | VERIFIED |
| T02 | horizon | Zero became one step; fractional and over-scope horizons were mishandled | Finite positive fractional semantics and typed nonexecution outside scope | VERIFIED |
| T03 | immutability | Post-construction spec mutation changed answers under a stale digest | Defensive copies plus construction-bound integrity checks | VERIFIED |
| S01 | model validation | NaN/Inf, invalid priors and illegal dynamics constructed | Recursive finite/domain/normalization validation | VERIFIED |
| E01 | reliability | Reliability was trace-only | Reliability scales evidence and local updates | VERIFIED |
| E02 | one public source | Multiple concepts from one result were first-wins/order-dependent | Typed multi-member source factor; exact-once and permutation-safe | VERIFIED |
| E03 | nonrankable evidence | Withheld/nonrankable fact vanished as if absent | Canonical record-only disposition plus typed residual/provenance | VERIFIED |
| E04 | known-factor misfit | Extreme mapped value raised aggregate misfit without provenance | Typed `known_factor_misfit` with source identity | VERIFIED |
| E05 | delayed observation | Old sample overwrote current local state | Delayed identity may update evidence; stale numeric state needs smoothing or typed refusal | VERIFIED |
| E06 | stale recursive event | A late stale event differed from cold replay | Replay/smoothing required; otherwise fail closed | VERIFIED |
| E07 | partial order | Overlapping action/observation intervals fabricated response | No response attribution without an order proof | VERIFIED |
| E08 | support masking | The same observation under support and no support updated identically | Measurement likelihood conditions on support/context | VERIFIED |
| E09 | shared common cause | Correlated observations were multiplied or one was discarded | Declared atomic `SAME_SOURCE_RESULT` / `SHARED_LATENT_INSTANCE` joint factors, content-bound and cold/permutation exact | VERIFIED |
| M01 | migration authority | Source state/spec was not fully authenticated | Source wire is validated against its exact source model | VERIFIED |
| M02 | evidence migration | Dedup/provenance was lost across migration | Factor/source identities and historical messages are remapped and closed | VERIFIED |
| M03 | history references | Old factor/mode/action ids survived or disappeared | Referential mode/factor/action/history remapping | VERIFIED |
| M04 | local stratum | Nonuniform stratum posterior reset to prior | Explicit maps/allocation and old-scope non-regression | VERIFIED |
| M05 | legacy import | Invalid parent digest and hidden loss | Schema-valid lineage plus explicit information-loss residual | VERIFIED |
| R01 | collision semantics | Same-sign values with incompatible safe actions were called no collision | Value, safety and optimal-action compatibility are compared | VERIFIED |
| R02 | local non-regression | Projection erased unrelated strata | Only the affected split path is masked | VERIFIED |
| R03 | genuinely new action | Refinement could only modify an existing action | Explicit new-action registration, scope extension and migration | VERIFIED |
| R04 | refined geometry | Opposite-response children had zero distance | Stratum topology/distance enters rollout and planning | VERIFIED |
| P01 | partial identification | One point estimate selected a partially identified action | Complete outcome sets are used for robust selection; incomplete/effect-only bounds abstain | VERIFIED |
| P02 | epistemic control | Severe OOD still forced a known-model action | OOD/unidentifiability is operative and produces typed abstention | VERIFIED |
| D01 | dynamic processes | Rollout froze process activation; local-state semantics double-weighted activity | Exact declared activation joint plus `q(x,m | active)` local propagation, joint-conditional coupling, reset-on-entry/reentry, and explicit factorization disclosure | VERIFIED WITH DECLARED APPROXIMATION |

## Deliberate boundaries still not implemented

These are not hidden failures and must not be described as solved:

1. **No generic effect-bound to outcome-bound propagation.** Effect-only
   intervals are rejected; robust planning requires a complete externally
   supplied outcome identified set.
2. **Common-cause factors are atomic and synchronous.** Cross-state,
   asynchronous or incomplete groups require a smoothing/replay model and
   currently fail closed.
3. **Retrospective stale evidence/actions require replay or smoothing.** The
   recursive runtime does not silently backfill them.
4. **Conditional-active mean-field local state is an approximation.**
   Activation-local selection correlations and cross-process local-state
   correlations outside the declared assumptions are `OUT_OF_SCOPE` and are
   disclosed in every relevant head.
5. **The canonical wire is a sufficient current-state representation, not a
   complete process-entry/exit biography or a complete transitive migration
   chain.**
6. **Content addressing is not signer authenticity.** SHA-256 lineage proves
   byte identity/integrity, not who authored or clinically validated it.
7. **The generic model is structural and case-blind, not clinically
   calibrated.** Passing the runtime and structural harness makes no diagnosis,
   treatment-benefit, or patient-safety claim.

## Release boundary

The runtime component may be manifested and component-sealed on this exact
source/evidence snapshot.  A combined protocol/primary-study seal remains a
separate step and must not be inferred from this component result.
