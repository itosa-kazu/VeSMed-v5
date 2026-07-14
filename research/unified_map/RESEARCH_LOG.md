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
