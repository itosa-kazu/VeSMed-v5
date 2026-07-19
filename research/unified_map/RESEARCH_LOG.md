# UCM Research Log

> Append-only human-readable index. Raw run evidence belongs under `results/unified_map/<run_id>/`; this file never substitutes for manifests, tests or raw outputs.

## 2026-07-15 — Track creation checkpoint

### Outcome

- Created branch `codex/unified-clinical-map` from K0 checkpoint `0795bc49c4aadb1d5d7cb8951044d9601ecb51a3`.
- Created the isolated research root `research/unified_map/`.
- Added candidate-neutral `PLAN.md` and `FIRST_PRINCIPLES.md` plus draft benchmark, candidate, experiment, source and red-team material.
- Committed and pushed checkpoint `4e0c5ebf2d711a1ea0161412b99535376728087b`.

### Evidence boundary

- This checkpoint contains research framing only.
- It does **not** prove W01–W20 exist, benchmark v1 is frozen, any candidate is implemented, any experiment has run, or a finite UCM exists.
- Candidate implementation remains closed until the benchmark freeze gate passes.

### Decision

`KEEP`: the independent track and first-principles definition are aligned with the goal; proceed to executable microworlds and benchmark self-tests.

## 2026-07-15 — K0 isolation inventory

### Hypothesis

UCM can reuse neutral experiment infrastructure patterns without importing K0 patient semantics or changing frozen K0 evidence.

### Action

- Added `K0_REUSE_BOUNDARY.md`.
- Recorded exact bytes and hashes in `K0_FROZEN_INVENTORY.json` for:
  - `results/20260713T120910Z-panel-v3/`;
  - historical K0 decision documents at base commit `0795bc4`.
- Added an AST import boundary and byte-identity regression test.

### Verification

```text
python -m pytest -q -p no:cacheprovider tests/unified_map/test_k0_isolation.py
4 passed in 2.02s
```

### Decision

`KEEP`: this proves only byte/import isolation. It is not UCM dynamics evidence and will not be counted among the 30 architecture experiments.

## Current gate

```text
Phase 0 repository boundary: PASS
Phase 1 first-principles draft: PASS, formal review in progress
Phase 2 W01–W20 executable specification: IN PROGRESS
benchmark v1 semantic freeze: NOT REACHED
candidate implementation permission: CLOSED
architecture experiments completed: 0 / 30
full candidates completed: 0 / 3
post-freeze red-team: NOT STARTED
```

## 2026-07-15 — Isolated harness primitives checkpoint

### Outcome

- Added candidate-visible versus judge-private typed schemas.
- Added harness-owned inert state serialization and content identity.
- Added append-only atomic result bundles with byte inventories.
- Added branch/order-independent keyed world randomness.
- Added counterfactual-family atomic split/KDF/commitment primitives.
- Added candidate-neutral diagnosis, trajectory, regret, OOD-AUROC and
  collision/false-split metrics.

### Verification

```text
python -m pytest -q -p no:cacheprovider tests/unified_map
65 passed in 2.32s

python -m pytest -q -p no:cacheprovider
200 passed, 7 subtests passed in 45.63s
```

The full-suite run first exposed a duplicate pytest module name
(`tests/test_metrics.py` versus the UCM metric test); the UCM file was renamed
and the clean full collection then passed.

### Evidence boundary

This checkpoint proves protocol data closure, exact hashes, output
non-overwrite, split atomicity checks and K0 byte/import isolation for the
implemented primitives. It does **not** prove the fresh-worker candidate
boundary, W01–W20 oracles, benchmark freeze, semantic unity, or any candidate
performance.

### Decision

`KEEP`: use these primitives as the benchmark harness substrate. Candidate
implementation remains closed until the full PRE-FREEZE checklist passes.

## 2026-07-15 — Candidate protocol and portable closure controls

### Outcome

- Added exact `initialize/update/diagnose/rollout` value envelopes.
- Bound harness state identity to candidate bundle, model, full scope,
  catalog, cut metadata, codec/schema/class and exact inert payload bytes.
- Added same-state fanout records for diagnosis and all rollout policies.
- Added fresh Python process execution with empty cwd, environment allow-list,
  explicit seeds and method-phase Python audit denial.
- Added honest specificity control and four executable malicious controls for
  global patient cache, head history access, query mutation and hidden RNG.

### Verification

```text
python -m pytest -q -p no:cacheprovider \
  tests/unified_map/test_state_hash.py \
  tests/unified_map/test_candidate_protocol.py \
  tests/unified_map/test_shared_state_compliance.py \
  tests/unified_map/test_compliance_negative_controls.py
30 passed in 9.12s
```

### Evidence boundary

The portable battery can show exact payload fanout and catch the registered
Python mutations. It explicitly emits both
`UCM-E001-SEMANTIC_UNITY_UNVERIFIED` and
`UCM-E002-ISOLATION_INCOMPLETE`: an opaque blob may still multiplex task
latents, and method-phase Python auditing does not exclude import-time or
native/Windows-kernel escape. These axes are **INCOMPLETE**, not PASS.

### Decision

`KEEP AS PRE-FREEZE HARNESS`: this is operational evidence only. Decision-grade
native candidates still require the stronger frozen isolation profile and the
remaining C01–C33 mutation matrix.

## 2026-07-15 — Append-only freeze tooling checkpoint

### Outcome

- Added exact byte inventory for the isolated UCM roots only.
- Added canonical `PRE-FREEZE` / `FROZEN-v1` manifests with required-path and
  blocker gates.
- Added non-overwriting manifest sidecars and byte-drift verification.
- Kept split-seed commit and reveal as separate append-only, hash-chained
  artifacts; raw seed/reveal material is rejected from the freeze manifest.

### Verification

```text
python -m pytest -q -p no:cacheprovider tests/unified_map/test_freeze_manifest.py
8 passed
```

### Evidence boundary

This is freeze **tooling**, not a benchmark freeze. No `FREEZE_MANIFEST.json`
has been emitted and benchmark status remains `PRE-FREEZE`; unresolved oracle,
independent-reference and isolation blockers still prevent `FROZEN-v1`.

### Decision

`KEEP AS PRE-FREEZE TOOLING`: commit separately from the still-changing
microworld implementations.

## 2026-07-15 — W16–W20 executable pre-freeze checkpoint

### Outcome

- Materialized deterministic generators, public catalogs, policy sets,
  judge-side counterfactual outputs and focused fixtures for W16–W20.
- Added two-stage check/treatment extension controls, attributable OOD tags,
  fixed 1/64 population-tail allocation plus a separate probe cohort, and
  exposure-memory collision/false-split fixtures.

### Verification

```text
python -m pytest -q -p no:cacheprovider tests/unified_map/test_worlds_w16_w20.py
39 passed
```

### Evidence boundary

`PRE-FREEZE PROTOTYPE`, not an oracle sign-off. The focused tests prove the
implemented invariants and candidate projection only. Independent
production/reference posterior solvers are not yet present. In particular,
the continuous-state counterfactual paths currently use a latest-observation
Gaussian approximation; W20's different-history/same-state fixture must be
revalidated against the specified full public-history posterior before it can
serve as a freeze oracle. The extension runner and final tail hard-gate
aggregator are also not yet wired.

### Decision

`KEEP FOR ITERATION`: checkpoint these executable worlds without changing the
benchmark status or opening candidate implementation.

## 2026-07-15 — W01–W05 executable pre-freeze checkpoint

### Outcome

- Materialized deterministic generators, public catalogs, finite policy sets,
  posterior-aware counterfactual paths and focused collision/false-split
  fixtures for W01–W05.
- Kept candidate/public DTOs separate from sampled judge truth and preserved
  no-new-action semantics without synthetic zero-dose events.

### Verification

```text
python -m pytest -q -p no:cacheprovider tests/unified_map/test_worlds_w01_w05.py
31 passed
```

### Evidence boundary

`PRE-FREEZE PROTOTYPE`. Native adaptive-check DTOs, exact event-index
semantics, several preregistered probe families, complete future propensity
ledgers and independent oracle certification remain open. W03/W04 matched
fixtures must not enter headline calibration as ordinary IID population rows
until their conditioning/weight contracts are finalized.

### Decision

`KEEP FOR ITERATION`: this commit supplies the shared world helper layer used
by later worlds, but does not satisfy the semantic-freeze gate.

## 2026-07-15 — W11–W15 executable pre-freeze checkpoint

### Outcome

- Materialized deterministic generators, finite policy sets, judge-side
  counterfactual outputs and paired fixtures for W11–W14.
- Split W15 into a randomized-identifiable panel and an observationally
  nonidentified SCM-twin panel. The latter returns an identified set and
  abstention contract rather than scoring a private realized point effect.

### Verification

```text
python -m pytest -q -p no:cacheprovider tests/unified_map/test_worlds_w11_w15.py
44 passed
```

### Evidence boundary

`PRE-FREEZE PROTOTYPE`. W11–W14 currently condition key counterfactual paths
on judge-side realized cut state; independent public-history posterior
production/reference solvers have not been implemented. Their green focused
tests therefore do not certify candidate-facing probability oracles. W15's
identification boundary is exercised, but its end-to-end evaluator integration
still remains outside this checkpoint.

### Decision

`KEEP FOR ITERATION`: preserve the executable semantics and W15 negative
control while leaving the benchmark freeze gate closed.

## 2026-07-15 — W06–W10 executable pre-freeze checkpoint

### Outcome

- Materialized public-history posterior paths for observation-channel versus
  latent effects (W06), joint effects (W07), delayed/out-of-sequence evidence
  (W08), personal baselines (W09), and grouped-measurement tail risk (W10).
- Added focused availability, private-swap, alpha-renaming, grouping,
  baseline/deviation and query-purity fixtures.

### Verification

```text
python -m pytest -q -p no:cacheprovider tests/unified_map/test_worlds_w06_w10.py
17 passed
```

### Evidence boundary

`PRE-FREEZE PROTOTYPE`. These tests exercise the current public-history
filters and numerical diagnostics, but do not yet constitute independent
production/reference oracle certification. Adaptive check policies still use
the provisional planned-action encoding, and population/probe assembly plus
final evaluator gates remain to be wired and audited before freeze.

### Decision

`KEEP FOR ITERATION`: checkpoint W06–W10 independently from the other world
groups; benchmark status remains `PRE-FREEZE`.

## 2026-07-15 — Fail-closed C01–C33 mutation matrix registry

### Outcome

- Added an executable registry for all C01–C33 gates, 26 required malicious
  controls, and four specificity controls.
- A kill counts only when the actual decisive gate and failure code match the
  mutant contract and an exact record digest is present; crashes, timeouts and
  unrelated failures do not count.
- Freeze readiness now fails closed for missing mutant executions, uncovered
  gates, survivors, or false-positive rejection of a specificity control.

### Verification

```text
python -m pytest -q -p no:cacheprovider tests/unified_map/test_mutation_matrix.py
6 passed
```

### Evidence boundary

This checkpoint freezes the **registry and evidence validator only**. It does
not claim that the 26 mutant implementations or 33 decisive detector records
already exist. An empty matrix correctly reports `HARNESS_INCOMPLETE`.

### Decision

`KEEP AS PRE-FREEZE HARNESS`: next wire real mutation executions into this
matrix; never synthesize `killed=true` from declarations.

## 2026-07-15 — First real mutation execution records

### Outcome

- Wired eight malicious controls through the real fresh-worker
  compliance runner into mutation-matrix observations.
- Produced decisive record digests for hidden global/file state, head history
  access, future/true-state reads, model mutation, query mutation and implicit
  RNG, plus one passing explicit-seed specificity control.
- The partial matrix deliberately remains `HARNESS_INCOMPLETE` rather than
  treating those four kills as coverage of the whole contract.

### Verification

```text
python -m pytest -q -p no:cacheprovider tests/unified_map/test_mutation_runner.py
2 passed
```

### Evidence boundary

Current executed coverage is exactly C02, C04, C06, C07, C08, C16 and C30,
with 8/26 mutants and 1/4 specificity controls. Remaining declarations have no
kill evidence yet and therefore block freeze.

### Decision

`KEEP`: extend this runner with real controls and decisive transcripts; never
fill uncovered cells with synthetic test rows.

## 2026-07-15 — Clean interface replay and fail-closed freeze audit

### Outcome

- Preserved a clean, commit-bound UCM test replay at source revision
  `1d0222a0cd4409aab076c62d10b146f6d7898241` under
  `results/unified_map/pre_freeze/20260715-1d0222a-full-suite/`.
- Added a 16-axis freeze evidence collector whose contracts cannot be replaced
  by callers. Producer-reported `PASS` values are not accepted: a check can
  pass only through collector-owned extraction from digest-bound raw bytes.
- Implemented one typed extractor for the mutation matrix. It reconstructs
  each observation, reruns the matrix evaluator, and requires canonical report
  equality plus witnessed source and decisive-record bytes.

### Verification

```text
clean archived replay: 439 passed in 183.79s
freeze audit / manifest / mutation registry: 33 passed in 0.35s
```

### Evidence boundary

All sixteen freeze axes remain typed `INCOMPLETE`. Fifteen axes intentionally
have no collector-owned extractor yet; the mutation axis is also incomplete
because the committed execution matrix does not cover all 26 mutants, C01-C33
and four specificity controls. The archived green pytest log is regression
evidence, not freeze authorization.

### Decision

`KEEP AS PRE-FREEZE EVIDENCE BOUNDARY`: add typed extractors and raw artifacts
axis by axis. Do not materialize a `FREEZE_MANIFEST` from test names or
producer-authored summaries.

## 2026-07-15 — Remove private split identity from W03/W18/W19 scoring

### Outcome

- W03 now uses one frozen public drift prior for scoring rather than the
  judge-private `episode.split`.
- W18 now uses one public scoring prior/support envelope across train,
  validation and sealed-test while leaving generator quotas unchanged.
- W19 now uses one public marker kernel (`sensitivity=.98`, `FPR=.02`, tail
  prior `1/64`) while preserving the finite generator quota of exactly one
  tail episode per 64 rows.
- Added private-swap tests that retain byte-identical public histories while
  replacing split, case/environment keys, generator seed, hidden state,
  targets, future, propensities, utility and oracle anchors.

### Verification

```text
W18/W19 public-prior + semantic + registry tests: 65 passed in 28.01s
```

### Evidence boundary

These fixes remove a concrete forbidden information path from scoring. They do
not prove the full split contract: a pre-split counterfactual-family manifest,
family/prefix/pair no-overlap audit, authoritative exact expected cells and
public-versus-judge-only stratum separation are still absent.

### Decision

`KEEP`: scoring is now invariant to private split swaps in W03/W18/W19, but
benchmark v1 remains `PRE-FREEZE` and candidate implementation stays closed.

## 2026-07-16 — Pre-split strata and typed corpus authority graph

### Outcome

- Rejected the uncommitted `event.payload.risk_score` shortcut because the live
  W01--W20 generators do not emit that field. Row-local `behavior_pair` labels
  remain development proxies; benchmark authority now comes from pre-split
  family topology and typed public/judge stratum rules.
- Bound family-atomic assignments, materialization receipts, public/judge
  strata and candidate/judge canonical JSONL joins through exactly 13 typed
  authority roots.
- Bound the same authority audit digest into the `world_generators`,
  `projection_boundary`, `split_isolation` and `expected_cells` freeze-axis
  contracts. Digest-shaped authority smuggling through public `event_uid`
  values is rejected.

### Verification

```text
f348535: family/strata verification 241 passed
aebab79: corpus/freeze main verification 40 passed
aebab79: independent targeted verification 13 passed + 4 passed
```

### Evidence boundary

This is structural `PRE_FREEZE_SCAFFOLD` evidence only.
`freeze_grade_evidence=false`,
`live_pre_split_materialization_complete=false`, and the unconditional
`UCM-E003-HARNESS_INCOMPLETE` blocker for independent custody and atomic
publication remain fixed. The four authority-bound freeze axes still lack
collector-owned typed extractors. `evaluation_cells.py` still consumes the
legacy `ucm-pre-split-family-*/1` lineage and row-reported strata; exact
authority-bound W09/W10/W18/W19 query/oracle/request/response receipts do not
yet exist.

### Decision

`KEEP AS PRE-FREEZE AUTHORITY SCAFFOLD`: no benchmark freeze, candidate gate,
architecture experiment or decision gate is opened.

## 2026-07-16 — Portable execution boundary and live mutation-source binding

### Outcome

- Commit `fde49cd` bound exact candidate/model/harness/runtime inventories,
  isolated bytecode caches, a trusted `PREPARED` handshake, one execution
  deadline plus declared cleanup grace, and a closed candidate-versus-harness
  failure taxonomy.
- Commit `57d3f6e` bound mutation execution to exact live source/runtime
  identity before and after each control, made transient tamper/restore
  attempts fail closed, and retained typed crash/incomplete handling.
- The executable partial matrix now has real evidence for 14/26 malicious
  controls, 3/4 specificity controls and 10/33 decisive gates.

### Verification

```text
fde49cd: candidate/compliance/shared verification 137 passed
fde49cd: clean detached compatibility replay 8 passed
57d3f6e: mutation runner/matrix final suite 262 passed in 2304.23s
57d3f6e: candidate/compliance/shared regression 138 passed in 556.70s
57d3f6e: independent focused audit 31 passed; P0/P1 findings 0
```

### Evidence boundary

Portable execution is explicitly not freeze-grade isolation.
`HarnessTamperControl` demonstrates a live same-process Python audit-hook
bypass, so `UCM-E002-ISOLATION_INCOMPLETE` remains fixed; native-extension and
Windows-kernel escape are also outside this assurance boundary. The mutation
matrix remains `HARNESS_INCOMPLETE`: 12 mutants, one specificity control and
23 gates still lack decisive coverage. The runner returns only
`tuple[MutationObservation, ...]`; exact pre/post source witnesses, raw report
transcripts and decisive-record preimages are reduced to digests and are not
atomically persisted by `run_store.py`. Raw custody and freeze-audit replay
therefore remain `UCM-E003-HARNESS_INCOMPLETE`.

### Decision

`KEEP AS PRE-FREEZE HARNESS`: benchmark v1 remains unfrozen; UCM candidate
architectures remain 0 and registered experiments remain 0.

## 2026-07-17 — W01 true-state shared-map vertical slice

### Outcome

- Added a judge-only W01 true-state upper-bound probe whose inert dynamic state
  contains exactly the Markov coordinates `x`, invariant `class_index` and the
  current availability cut.
- Diagnosis, no-new-action prediction, treatment A1 prediction and treatment
  A2 prediction all consume the same harness-computed state hash.
- A newly available factual treatment/observation panel recursively updates
  that state, creates a new hash with an exact parent/delta link, and both
  updated diagnosis and updated rollout consume only the new hash.
- The probe quotients W01 alpha-renamed equivalent histories to one state hash
  while separating the registered behavior-collision pair and its different
  optimal treatments.

### Key evidence

```text
artifact: results/unified_map/pre_freeze/20260717-w01-true-state-probe/vertical-slice.json
artifact sha256: 3703de6d2698524443079323d47ca96a5c6f2598673852c704e81bb9a1329f2e
initial state: sha256:c4c5aac89fdac16f1aec4c02673b9239a59a3cf4f677de24c60ff968e9078a53
updated state: sha256:299ca0a762f44a11a3a4f1e9382e62361e4cd5ebef1c18e83751baa1e246169f
```

The artifact records all four runtime assertions as true:
`initial_heads_consumed_one_hash`, `update_changed_hash`,
`update_parent_link_closed`, and `updated_heads_consumed_new_hash`.

### Verification

```text
true-state probe focused: 5 passed
W01-W05 world/oracle regression: 72 passed
Ruff and py_compile: passed
```

### Evidence boundary

This is a TRAIN-fixture Phase-2 oracle/metric sanity probe, not a deployable
candidate or completed architecture experiment.  Its manifest is explicitly
`privileged=true`, `eligibility=upper_bound_only`, `freeze_grade=false`, and
the artifact is `PRE-FREEZE` / `NOT_COUNT_ELIGIBLE`.  Candidate families and
the formal B01 run remain closed; the experiment ledger therefore remains
0/30.

### Decision

`KEEP AS PATIENT-MODEL VERTICAL SLICE`: use this exact state/query/update shape
to close W02/W04/W08/W15/W18/W19/W20 before resuming only the freeze work that
directly blocks real candidate experiments.

## 2026-07-17 — W02 partial-observation upper-bound vertical slice

### Outcome

- Added a W02 judge-only shared state containing the actual two-dimensional
  latent physiology and invariant mechanism class, while ordinary W02 scoring
  continues to use only the public two-component Kalman-mixture belief.
- On the committed TRAIN fixture, the public history supports an almost exactly
  balanced diagnostic belief (`C0=0.5004869708409363`,
  `C1=0.49951302915906365`), while the privileged true-state upper bound is
  correctly one-hot (`C0=1.0`, `C1=0.0`).
- Diagnosis and no-op/A1/A2 predictions consume one state hash.  A factual
  treatment plus newly available partial observation advances the same map
  using the parent-only next latent truth, and updated heads consume the linked
  new hash.
- Added an independent one-step numeric check of class-specific transition,
  treatment push and process covariance so the private oracle path is not
  accepted only because the probe calls it.

### Key evidence

```text
artifact: results/unified_map/pre_freeze/20260717-w02-true-state-probe/vertical-slice.json
artifact sha256: b6202d839c8eb0d5180c22bedd0d348b77cd2f75f803e21c12a5db626c0c57db
initial state: sha256:7d462b9b02b1a86ee0d56e8337774e838484a75db3f142084d15168e1a7f8f7e
updated state: sha256:327aaa98b31701454abd36813bc788ea75e3f4f9a25d06d1c8a164ad76ff151a
```

### Verification

```text
W02 probe focused: 4 passed
W01/W02 plus W01-W05 world/oracle/research-contract regression: 84 passed
Ruff and py_compile: passed
```

### Evidence boundary

This remains a TRAIN-fixture Phase-2 upper-bound sanity probe.  The update may
read judge-only next latent truth because W02 is partially observed; an
ordinary UCM candidate may not.  The manifest remains `privileged=true`,
`eligibility=upper_bound_only`, and `freeze_grade=false`.  It is not a formal
B01 run and does not change the 0/30 experiment ledger.

### Decision

`KEEP`: W02 now proves the intended distinction between a hidden patient state
and the observer's belief over that state.  Continue with W04, where identical
natural course but opposite treatment response attacks insufficient shared
states directly.

## 2026-07-17 — W04 dangerous treatment-collision vertical slice

### Outcome

- Added a W04 judge-only shared state containing the scalar dynamic state plus
  the invariant treatment-response modifier.  The modifier is part of patient
  state because it changes counterfactual response even when untreated natural
  history is identical.
- Constructed a registered collision pair at the same observed scalar
  (`x=0.4`).  Both members have exactly the same no-new-action trajectory, but
  class C0 selects A1 and class C1 selects A2 under the common utility.
- Diagnosis and no-op/A1/A2 counterfactual heads consume one sealed state hash
  per patient.  A visible A1 response recursively advances that same map and
  closes the parent/delta link for both response classes.
- Added an independent numeric one-step check: from `x=0.4`, A1 moves C0 to
  mean `0.068` and C1 to mean `0.968`, with variance `0.04^2` in both cases.

### Key evidence

```text
artifact: results/unified_map/pre_freeze/20260717-w04-dangerous-collision-probe/vertical-slice.json
artifact sha256: 70918ade781e3318e4ddab205b00d7811d1e548a6888ec541d566f85a2cab84f
C0 initial state: sha256:11c73e91bfeaca708afb4c31a938790476aa01c38aea18898b84c6cdb225543f
C1 initial state: sha256:015b76ec9330888a2022bbceaf73ec91ddc1c228556cd8d03b372d8670cb5064
C0 best action: single_A1
C1 best action: single_A2
```

The artifact records all five claims as true: `same_natural_course`,
`opposite_optimal_treatments`, `modifier_prevents_state_collision`,
`all_heads_share_patient_state`, and `updates_close_parent_links`.

### Verification

```text
W04 probe focused: 3 passed
W01/W02/W04 plus W01-W05 world/oracle/research-contract regression: 95 passed
Ruff and py_compile: passed
```

### Evidence boundary

This is still a privileged TRAIN-fixture Phase-2 upper-bound sanity probe, not
a learned candidate or formal B01 experiment.  Its manifest remains
`privileged=true`, `eligibility=upper_bound_only`, `freeze_grade=false`, and
the artifact remains `PRE-FREEZE` / `NOT_COUNT_ELIGIBLE`; the experiment ledger
therefore remains 0/30.

### Decision

`KEEP`: a treatment-response modifier is a required patient-state coordinate
whenever untreated history cannot identify opposing treatment effects.  Move
next to W08 to test asynchronous availability, out-of-sequence evidence and
active-course typestate through the same state and recursive update contract.

## 2026-07-17 — W08 asynchronous-availability vertical slice

### Outcome

- Added a W08 judge-only shared state containing the two-dimensional latent
  physiology, invariant mechanism class, current signed treatment exposure and
  remaining course microticks.  The rollout heads cannot reread public history.
- Diagnosis, no-new-action, A1 and A2 counterfactuals consume one sealed state
  hash and project both observable channels from the same patient map.
- A factual A1 course plus an out-of-sequence result collected at `-1` and only
  available at `+1` recursively creates a new state with an exact parent/delta
  link.  Updated diagnosis and rollout consume only that new state.
- The updated no-new-action rollout continues the already performed A1 course;
  it does not misread `NoNewAction` as stopping a treatment with three
  microticks remaining.
- A private fixture with identical public prefix and two differently ordered
  pending report values produces the same pre-availability state hash.  The
  pending-value digests differ, proving the equality is not a vacuous swap.

### Key evidence

```text
artifact: results/unified_map/pre_freeze/20260717-w08-asynchronous-availability-probe/vertical-slice.json
artifact sha256: fe0ae3376994898db16fa7487c99697bebb91c44f62a4995f4163f4110b448ce
initial state: sha256:503252e92ac5875013b0469254dd5edfd912a1d3f729403325a2562419942bbc
updated state: sha256:8cf97e6f54c9fda0b50d5e0661b92509b6edb29a2405648c5c78b8efeebbc8d5
pending left: sha256:82d3eea019adbd66d58c27fff4755301a8398c415071acc9f7086d66626696c0
pending right: sha256:e2565cc3317e9749b098a0d60ded3fd9ebef76506339d18e4a874afbc2c9c6ef
```

All seven artifact assertions are true, including pre-availability exclusion,
collection/availability timestamp preservation, shared-head consumption,
parent-linked recursive update and active-course typestate retention.

### Verification

```text
W08 probe focused: 4 passed
W08 plus W06-W10 world/oracle/research-contract regression: 63 passed
W01/W02/W04/W08 plus W01-W10 combined regression: 143 passed
Ruff and py_compile: passed
```

### Evidence boundary

This is a privileged true-state upper bound.  Its recursive update may receive
judge-only next physiology, but the serialized state deliberately excludes a
collected report value until its `available_at` cut.  It is not a learned
filter, a formal B01 experiment or freeze-grade evidence.  The manifest remains
`privileged=true`, `eligibility=upper_bound_only`, `freeze_grade=false`; the
experiment ledger remains 0/30.

### Decision

`KEEP`: W08 proves that asynchronous evidence and treatment-course typestate
can remain inside one recursively updated patient map without leaking pending
results or inventing a task-private rollout state.  Continue with W15, where
observational association and interventional effect must be separated without
splitting the patient representation by task.

## 2026-07-17 — W15 condition/do and nonidentification vertical slice

### Outcome

- Added one W15 causal-state contract with two explicitly different evidence
  regimes.  W15A stores judge-known severity/confounder for an upper-bound
  dynamic state and binds the structural treatment effect identified by the
  public randomized anchor.  W15B stores only the public SCM equivalence class
  and deliberately excludes the realized private SCM.
- W15A diagnosis, no-new-action and `do(A1)` consume one state hash.  The
  first-step `do(A1)` severity effect is exactly `-0.35`; a separate estimate
  from 400 public randomized-anchor episodes is `-0.26012181044303`, preserving
  the beneficial sign without reading the private confounder.
- A factual A1/outcome panel recursively updates W15A state with an exact
  parent/delta link.  Updated diagnosis and rollout consume only the new state.
- W15B's exact public twins have judge-only structural effects `+1` and `-1`
  but produce the same state hash.  Both no-action and `do(A1)` heads return
  the full ATE identified set `[-1,+1]` and `recommendation=abstain`, rather
  than leaking private SCM identity into a confident point estimate.

### Key evidence

```text
artifact: results/unified_map/pre_freeze/20260717-w15-causal-separation-probe/vertical-slice.json
artifact sha256: bc42d240464d58dbc5933bec7763416b3cfc238ca5dc150f9ed310f90369f588
W15A initial: sha256:13527dd926795b2562c2c2acb3492c532a1983ca7cf3fc5e973c6d4f4643909d
W15A updated: sha256:597bae77e53ab9808faf321798db48cb0f46d838cca6f3a7ceec1410e7b657ff
W15B Mplus/Mminus shared state: sha256:871903e346efa11897bb2aeeec4e4d5bf58592c7c1778768b4cea3a14163bb25
identified do effect: -0.35
public randomized-anchor estimate: -0.26012181044303
```

All nine artifact assertions are true, including shared-head state use,
identified-effect sign, recursive update closure, private-SCM twin quotienting,
opposite red-team effects and honest nonidentified abstention.

### Verification

```text
W15 probe focused: 4 passed
W15 plus W11-W15 world/oracle/strata/research-contract regression: 111 passed
Ruff and py_compile: passed
```

### Evidence boundary

W15A remains a privileged true-state upper bound, while W15B is an honest
public-equivalence-class state precisely because a true private-SCM point state
would be an invalid causal answer.  This slice does not train a causal model or
open formal B01.  Its manifest remains `eligibility=upper_bound_only` and
`freeze_grade=false`; the experiment ledger remains 0/30.

### Decision

`KEEP`: the shared patient representation may contain an identified causal
effect or an identified set, depending on evidence, but it must never collapse
the latter to a private realized mechanism unavailable to the observer.
Continue with W18 to test OOD/rejection behavior through the same state API.

## 2026-07-17 — W18 public-evidence OOD and rejection vertical slice

### Outcome

- Added a W18 shared public belief state containing the latest two-channel
  observation, the frozen four-component mechanism posterior and known-support
  feasibility.  It is derived only from candidate-visible evidence; private
  mechanism identity is excluded.
- An unseen C2 fixture and a feasible known C0 fixture with byte-identical
  public evidence produce the same state hash.  Their judge tags differ
  (`OOD_IRREDUCIBLE` versus `KNOWN`), but the state correctly refuses to split
  them or force OOD from unavailable truth.
- Diagnosis and no-action/A1 rollouts consume the same initial state.  A new
  complete public pair (`obs_0=0.8`, `obs_1=0.0`) recursively updates that state,
  raises `unknown` from `0.770700636942675` to `1.0`, and makes every updated
  head return `abstain`.
- A known-support extreme control (`obs_0=obs_1=1.35`) remains `C0=1.0` and is
  not rejected, preventing a blanket tail-value abstention rule.

### Key evidence

```text
artifact: results/unified_map/pre_freeze/20260717-w18-public-ood-probe/vertical-slice.json
artifact sha256: 81b0951ab27096b4d6f58470e2cbdc2ad066485f523b41370740097c9b230705
irreducible unseen/known shared state: sha256:9b631e20530a0b4273c9781327569df24201f0f83b3a55a8b9b21681dd5c598d
public-OOD updated state: sha256:ac8acb21eded375e5bce0777b1a2b6016b9afb253b5028cc33d6ac09aea9c240
initial unknown probability: 0.770700636942675
updated unknown probability: 1.0
```

All nine artifact assertions are true, including irreducible-alias quotienting,
non-forced initial handling, parent-linked public update, shared-head state use,
post-evidence abstention and known-extreme specificity.

### Verification

```text
W18 probe focused: 4 passed
W18 plus W16-W20/public-prior/semantic/research-contract regression: 78 passed
Ruff and py_compile: passed
```

### Evidence boundary

The state itself uses public evidence only, but it is still an upper-bound
probe because the frozen analytic support model and unknown-reference dynamics
are benchmark oracle knowledge, not learned candidate parameters.  It is not a
formal B01 experiment and remains `freeze_grade=false`; the experiment ledger
remains 0/30.

### Decision

`KEEP`: rejection is a state property induced by attributable public evidence,
not by private atlas membership and not by a generic tail threshold.  Continue
with W19 to test whether a rare catastrophic contraindication remains explicit
instead of being erased by prevalence-weighted mean compression.

## 2026-07-17 — W19 rare catastrophic contraindication vertical slice

### Outcome

- Added a compact W19 shared public belief state containing sufficient
  statistics for the latent physiology plus posterior rare-tail mass from the
  public marker kernel.  The realized private tail bit is excluded.
- A common patient and a private tail patient with identical public history
  produce the same state hash and begin with the frozen population tail
  probability `1/64 = 0.015625`; no private truth leaks into diagnosis or
  treatment heads.
- Diagnosis and no-action/A1/A2 counterfactuals consume one state.  A factual
  safe A2 response plus a positive marker recursively creates a new state and
  raises tail probability to `0.4375`.
- From that same updated state, A1 exposes tail-only regret
  `44.9973503221698` and catastrophic-action probability `0.4375`, so its head
  returns `contraindicated`.  A2 has zero catastrophic-action probability and
  remains eligible.  The rare tail cannot be averaged away by expected utility.

### Key evidence

```text
artifact: results/unified_map/pre_freeze/20260717-w19-rare-contraindication-probe/vertical-slice.json
artifact sha256: 508e839c216403893ae9b97166cca8eaf9ece59d69624aa816c3a562b369c2b8
unidentified common/tail shared state: sha256:a80e8e289175cf2be989b28929afc68fd51f9998208c16a05eab3d99880a6e78
marker/response updated state: sha256:f24de228c002e8e152983c39aea22344a89ef15adf0b0b193dde081449736ddf
tail probability: 0.015625 -> 0.4375
A1 tail-only regret: 44.9973503221698
A1 catastrophic-action probability: 0.4375
```

All eight artifact assertions are true, including private-alias quotienting,
prevalence preservation, shared-head state use, parent-linked response update,
positive-marker posterior movement, A1 hard-gate exposure and A2 specificity.

### Verification

```text
W19 probe focused: 4 passed
W19 plus W16-W20/public-prior/semantic/research-contract regression: 78 passed
Ruff and py_compile: passed
```

### Evidence boundary

This state is public-evidence-derived, but the posterior kernel, catastrophic
margin and conditional tail utility are frozen benchmark oracle knowledge.  It
therefore remains an upper-bound probe, not a trained candidate or formal B01
run; `freeze_grade=false` and the experiment ledger remains 0/30.

### Decision

`KEEP`: a sufficiently informative patient state must retain small posterior
mass when that mass changes treatment safety, and treatment heads must expose
conditional tail risk rather than compress it into the population mean.
Continue with W20, the final priority vertical slice.

## 2026-07-17 — W20 feedback-memory and Markov-closure vertical slice

### Outcome

- Added a compact W20 shared public Bayesian state containing posterior mean
  and variance for physiology plus exact public exposure memory `r`.  All query
  heads read this state and cannot rescan full history.
- Constructed two patients with the same posterior physiology (`mean=0.70`)
  but different public exposure memory.  Their state hashes differ.  A1 moves
  the low-exposure patient to first-step mean `0.33` but the high-exposure
  patient to `1.08`, proving that omitting `r` creates a dangerous treatment
  collision.
- Constructed two different full histories with the same complete
  `(posterior_mean, posterior_variance, r, evidence_count)`; they produce the
  same state hash, proving that raw history is not required once sufficient
  statistics close.
- A factual A1 plus response observation incrementally updates the low-exposure
  state with an exact parent/delta link.  The new `r` crosses the response
  threshold, so the next A1 direction reverses while updated diagnosis and
  rollout heads consume only the new state.

### Key evidence

```text
artifact: results/unified_map/pre_freeze/20260717-w20-feedback-memory-probe/vertical-slice.json
artifact sha256: 28399f26c0bd050236f181fec1caceae49bb3fa08747e31864d67f35579323e4
low-exposure state: sha256:f3e367b577fbaa2b59211bb8cc33cead498a8d8ea54b38c493b730ae79931995
high-exposure state: sha256:95e25ad9323e58bd35fb6bc8381c31969cb9c2dd69423ede281f295cba5cce3b
false-split shared state: sha256:51f2e2d52d8f37a04be431994c571f0fb7ebd81a973abe1a1e50a2932f30efc2
response-updated state: sha256:93cd0a96ab186027a83d0e146a14c53d3fa579e82807d371188393f85e21c76d
low/high A1 first-step means: 0.33 / 1.08
```

All eight artifact assertions are true, including dangerous-collision
separation, sufficient-history quotienting, shared-head state use,
parent-linked incremental update and post-update response reversal.

### Verification

```text
W20 probe focused: 4 passed
W20 plus Bayesian/W16-W20/research-contract regression: 68 passed
all eight priority probes plus W01-W20 relevant world/oracle regression: 320 passed
Ruff and py_compile: passed
```

### Evidence boundary

The state is public-evidence-derived, but the transition/filter constants are
frozen benchmark oracle knowledge.  This remains an upper-bound Phase-2 probe,
not a trained candidate, formal B01 run or architecture experiment.  The
manifest remains `eligibility=upper_bound_only`, `freeze_grade=false`, and the
experiment ledger remains 0/30.

### Decision

`KEEP AND CLOSE PRIORITY VERTICAL-SLICE SET`: W01/W02/W04/W08/W15/W18/W19/W20
now provide executable shared-state, multi-head and recursive-update evidence.
The next highest-information step is to turn these exact executions into real
evaluator cells and oracle/metric upper-bound sanity rows; do not return to
detached control-plane hardening unless such a cell exposes a concrete blocker.

## 2026-07-18 — W01 patient-bound upper-bound evaluator template

### Outcome

- Added the first typed evaluator for a real privileged patient-world execution
  rather than projecting caller-declared scalars into the ordinary candidate
  evaluator.  It byte-replays the committed W01 vertical slice and then
  rematerializes exact diagnosis/rollout queries, head responses, judge oracle
  records and a source-distinct scalar-recursion reference oracle.
- The evaluator stores the complete deterministic preimage of both sealed state
  hashes (payload, model/scope/catalog bindings and availability cut), excluding
  only the execution nonce that is not an input to `compute_state_hash`.
- Six cells now cover initial diagnosis, no-action conditional-mean forecast,
  A1/A2 expected-utility comparison, recursive update, updated diagnosis and
  updated no-action forecast.  All heads are bound to the correct initial or
  updated state and the update has an exact parent/delta join.
- Diagnosis log loss/Brier, trajectory RMSE/MAE and treatment regret are rebuilt
  by code from raw candidate/oracle bytes.  Deliberately degraded controls have
  worse scores, while the true-state row has zero mean error and zero regret.
  Re-signing an altered response, query, state lineage, status or metric cannot
  preserve a valid report.

### Key evidence

```text
implementation: prototype/unified_map/upper_bound_evaluator.py
tests: tests/unified_map/test_upper_bound_evaluator.py
artifact: results/unified_map/pre_freeze/20260718-w01-upper-bound-evaluator/sanity-bundle.json
artifact sha256: 80840d898f542b48451ed38668889d101acc19afa489ced4273d6d1ccde8314b
bundle root: sha256:448af6d423d78900dbfaad580ea032190ad7c2481fb36a04d79b69137bcdd230
cells: 6
stable state bindings: 2
source-distinct oracle cells: 2
ledger credit: 0
```

### Verification

```text
W01 upper-bound evaluator focused: 9 passed
W01 evaluator + all eight probes + state/metrics/oracle/candidate-protocol/evaluator regression: 254 passed
Ruff and py_compile: passed
source vertical slice: canonical and byte-identical live replay
```

### Evidence boundary

This is a mean-trajectory and expected-utility **sanity evaluator**, not a
proper full-distribution score.  The updated cut currently has only the judge
path, not a source-distinct second oracle.  The bundle therefore hard-codes
`PRE-FREEZE`, `upper_bound_only`, `NOT_COUNT_ELIGIBLE`, `analysis_weight=0`,
`candidate_gate=NOT_APPLICABLE` and `benchmark_freeze_evidence=false`.  It is
neither a formal B01 run nor an architecture experiment; the ledger remains
0/30.

### Decision

`KEEP AND GENERALIZE PER WORLD`: use this execution-bound, collector-owned
contract for W02/W04/W08/W15/W18/W19/W20.  Do not force their belief-mixture,
identified-set, rare-tail or feedback semantics through the W01 point-mean
extractor.

## 2026-07-18 — Eight-world patient-bound upper-bound evaluator suite

### Outcome

- Generalized the W01 execution-bound evaluator contract with seven
  world-specific collectors for W02/W04/W08/W15/W18/W19/W20.  Each collector
  replays its committed vertical-slice bytes and rebuilds state bindings,
  queries/heads, judge material and metrics from the live world path instead of
  accepting caller-declared scores.
- Indexed the eight heterogeneous reports without pretending that their
  estimands are homogeneous.  The suite contains 58 cells and 27 state
  bindings across 8/20 worlds.  W03/W05/W06/W07/W09/W10/W11/W12/W13/W14/W16/
  W17 remain outside this patient-bound suite.
- Preserved the per-world evidence boundaries: W15B reports an identified set
  rather than a private point effect; W18's two-point OOD ranking is only a
  sanity witness; W19 retains panel/tail separation; W20 reports marginal
  moments and expected utility rather than a joint temporal law.
- The W20 collector found, rather than hid, a compactness failure.  A legal Q1
  event triplet changes only `evidence_count` from 5 to 6.  Posterior mean,
  posterior variance and exposure memory remain equal, and all nine enumerated
  horizon-4 policy semantics are exact-equal, but the state hashes differ.

### Key evidence

```text
suite index: results/unified_map/pre_freeze/20260718-eight-world-upper-bound-suite/suite-index.json
member reports: results/unified_map/pre_freeze/20260718-eight-world-upper-bound-suite/members/W01.json ... W20.json
suite root: sha256:25d8d2f7cfbfe276268c106b2f58fa6e014638c301e7d2ae05c0561d92b1d68c
member-set root: sha256:ac3c34dcb12e01c10e612d8fd48d85e8dcfcc264bd69a1177fba0444aae78bb2
W20 member root: sha256:440af3bf7aee3ca9e1103f4ff921623918f6f41bad4067cf903034f2539fe41d
status: VALID_PRE_FREEZE_EIGHT_WORLD_SANITY_INDEX
covered worlds: W01, W02, W04, W08, W15, W18, W19, W20
coverage: 8/20 worlds; 12 worlds missing
cells: 58
state bindings: 27
all members live replayed: true
candidate performance claimed: false
formal freeze authority: false
ledger credit: 0

W20 false-split pair: W20-evidence-count-false-split
left/right state hashes:
  sha256:f3e367b577fbaa2b59211bb8cc33cead498a8d8ea54b38c493b730ae79931995
  sha256:7a37d7aa7a364072497e8e1d4d83a361cd64545845238bc53b4ef3dbe37297f6
state distance: 1.0
oracle behavior distance: 0.0
cross-applied regret: 0.0
classification: false_split=true, dangerous_collision=false
```

### Freeze dependency gap map

The read-only dependency snapshot was taken against source revision `6dbb4d8`;
it is a planning map, not a scope manifest, collector artifact or freeze
authorization.

```text
formal research/unified_map/freeze directory: absent
freeze axes: 16/16 INCOMPLETE; 16/16 formal axis artifacts missing
collector checks: 12/123 have a typed extractor; 111/123 remain unextracted
registry readiness blockers: 52
  pre_split_family_authority: 21
  dual_channel_stratum_authority: 21
  W16/W17 extension authority: 10
315-shard coverage lock: ready=false; query counts empty; authority pins unset
mutation execution: 18/26 mutants, 4/4 specificity controls, 14/33 gates
code-owned freeze issuers I001/I002: disabled
```

The shortest dependency-respecting route is therefore: clean committed source
and formal `SCOPE_MANIFEST` -> 21-panel family/stratum authority -> W16/W17
extension authority -> corpus pins and exact expected cells -> mutation/runtime/
replay closure -> the remaining collector-owned extractors -> code-owned freeze
issuer.  This order does not grant credit to the eight-world suite.

### Verification

```text
suite generation: eight member reports plus one canonical index materialized
suite verify-only: passed; every member matched a fresh live adapter replay
W20 false split: 9/9 horizon-4 policy semantics exact-equal
document whitespace check: git diff --check
```

### Evidence boundary

The suite is privileged, partial, per-world heterogeneous and not a frozen
expected-cell corpus.  It remains `PRE-FREEZE`, `upper_bound_only`,
`NOT_COUNT_ELIGIBLE`, `analysis_weight=0` and `ledger_credit=0`.  It is neither
a candidate nor a formal B01 run and provides no candidate/freeze/architecture
credit.  Registered experiments remain 0/30.

### Decision

`KEEP AS EXECUTION-BOUND SANITY MACHINERY`: use the eight reports to drive the
remaining authority and extractor work, but do not expand sideways into
candidate families before benchmark freeze.  Keep the W20 false split open and
`minimal_quotient_claimed=false` until the behavior-inert counter is quotiented
out and the full policy panel is replayed.

## 2026-07-18 — Twenty-world upper-bound execution suite

### Outcome

The patient-bound PRE-FREEZE upper-bound execution layer now covers all W01--W20
world adapters and all 21 registry panels. W15A and W15B remain separate panel
identities. This closes executable upper-bound coverage only; it does not close
the formal scope, expected-cell corpus, split/strata authority or freeze chain.

W20's known behavior-inert `evidence_count` false split was repaired. Raw
history/count remain in independent provenance, while the sealed behavior state
contains only the public posterior/exposure statistics used by the frozen
horizon-4 policy semantics. The repaired pair has different histories and raw
counts 5/6 but the same state hash and exact-equal semantics for all 9 policies.
`minimal_quotient_claimed=false` remains mandatory.

### Clean committed evidence

The artifact was generated and then live-verified in an isolated detached
worktree at committed revision `51a9a95`; unrelated PRE-FREEZE scope/metric
drafts in the main worktree were not imported.

```text
artifact: results/unified_map/pre_freeze/20260718-twenty-world-upper-bound-suite/
suite file sha256: 882ec9455bb7803b5a223136969559e07ac1e21cf77aa103fb649b2c57e83922
suite root: sha256:b2dafe80b6464edfb38b1e5369c9fd9381db98ad699f53904c316290e9673834
member-set root: sha256:7f55200ffdb6fd7f8c994a9bf986a573e419e2315bb04cd52e1dc1bc7da4a52a
members/worlds/panels: 20/20/21
cells/state bindings: 94/43
member files: 20 exact canonical WXX.json files
total artifact files/bytes: 21 / 1,038,791
status: VALID_PRE_FREEZE_TWENTY_WORLD_TWENTY_ONE_PANEL_SANITY_INDEX
candidate performance claimed: false
formal benchmark coverage claimed: false
formal freeze authority: false
ucm eligible: false
ledger credit: 0
```

### Verification

```text
W03--W14 focused regression: 75 passed
W16/W17 + W20 focused regression: 30 passed
full suite integration: 7 passed in 227.71s
clean committed materialization: passed
clean committed verify-only + exact member directory: passed in 159.2s
W20 repaired pair: raw counts 5/6, same state hash, 9/9 policy semantics equal
member tree tamper: one extra byte rejected; one extra file rejected
```

### Evidence boundary and next step

The suite remains privileged, heterogeneous, `upper_bound_only`,
`NOT_COUNT_ELIGIBLE` and zero-credit. It is not a candidate, formal B01,
expected-cell corpus or benchmark freeze. The next dependency-respecting work is
the typed 11-axis scope plus panel/split/strata authority and metric semantics;
the suite must not be used to bypass those gates or start candidate experiments.

## 2026-07-19 — Formal-scope checkpoint and portable mutation closure

### Outcome

Two previously uncommitted PRE-FREEZE infrastructure batches were isolated into
reproducible checkpoints and pushed to `codex/unified-clinical-map`:

- `b68e1ad` builds the fail-closed formal-scope producer, exact W16/W17 transition
  protocols and metric runtime binding inventory. The live producer remains
  `PRE-FREEZE`, emits no `ScopeManifest`, and reports 654 exact gaps: 539
  world-owned plus 115 metric-registry-owned. Transition, task, seed and producer
  source-closure predecessors contribute zero gaps. The runtime metric inventory
  remains 111 targets with `closed_target_count=0` and coverage
  `72 formula_executable_unbound / 14 partial_formula_coverage_unbound /
  17 partial_untrusted_collector / 8 unimplemented`.
- `119f9cd` executes all 26 malicious mutation subjects and all four specificity
  controls as 30 real cases. Every mutant has a same-row decisive record and all
  specificity controls pass. Gate coverage is 21/33, so the result remains
  `HARNESS_INCOMPLETE`; it is not a freeze result.

The formal producer deliberately records each metric semantic gap once under the
metric registry while requiring an exact world-to-metric cross-reference. A stale
test that counted the same 115 gaps under both predecessors was corrected; no gap
was deleted or reclassified as closed.

### Verification

```text
metric runtime bindings: 17 passed
world scope fragments: 19 passed
scope transition protocols: 44 passed
formal scope producer: 28 passed
adjacent scope/metric/freeze tests: 197 passed
directed mutation controls: 6 passed
mutation matrix: 13 passed
mutation evidence: 149 passed
full live 30-case mutation execution: 1 passed in 1560.71s
mutation-runner remainder before six focused fixes: 275 passed, 6 failed
the six exact failing nodes after fixes: 6 passed
```

The six focused fixes were one protocol-fixture version drift, deterministic
detection of a rewritten `inspect.ismodule`, and explicit isolated access to the
approved interpreter's `purelib` under `python -S`. The full mutation-runner
remainder has not yet been rerun after those focused fixes; the log therefore does
not claim a fresh all-file green run.

### Evidence boundary and next step

Both checkpoints are candidate-neutral PRE-FREEZE machinery. They receive no
architecture, experiment or Pareto credit; the formal experiment ledger remains
0/30. The next semantic work is to close the 539 world-owned and 115 metric-owned
gaps, plus the remaining 12 compliance gates, rather than add more control-plane
hardening that does not directly remove a freeze blocker.
