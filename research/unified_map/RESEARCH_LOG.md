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
