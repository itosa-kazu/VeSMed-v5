# NCF Primary Real-Case Protocol Audit

## Outcome

**Protocol verdict: `READY_PENDING_RUNTIME`.  The holdout protocol is ready; the combined pre-primary seal is still blocked by the changing/unresealed runtime.**

- Scope: NCF-ARCH-1.0.0 primary real-case holdout only; no VeSMed V5 path was used.
- Primary case search/open/screen/select/replay: **not performed**.
- Protocol self-check: **PASS**.
- Targeted protocol/selection/scorer/seal suite: **77 run: 76 passed, 1 Windows symlink test skipped** because this host could not create a symlink. Equivalent path-containment and symlink rejection logic remains covered elsewhere.
- Combined seal: **not created, fail-closed** because the frozen runtime manifest no longer matches `runtime_v2/architecture_wire.py`.

## Decisive fixes

1. Frozen model-neutral complex-case eligibility, exact Q1/Q2 search snapshot, complete screening, minimum-three pool and deterministic hash selection.
2. Added conservative availability compiler: interval -> supported upper bound; same batch -> same cut; unknown/unbounded partial order -> withheld to measurement uncertainty; publication order is forbidden.
3. Made non-mention strictly `UNKNOWN_NEVER_NEGATIVE`.
4. Added role packet/manifests and mapper isolation; every mapped observation now carries method/provenance/unit/reliability/support-masking/alternative-representation disposition before it may enter factor messages.
5. Independent oracle must be sealed before runtime output; evaluator receives only its hash.
6. Required immutable full source denominator and exact source locators.
7. Frozen seven case-specific complexity checks; structural toy probes cannot substitute.
8. Corrected/versioned the identifiability enum to exactly match the architecture wire.
9. Added an executable exact-thirty final scorer. Missing/duplicate/unknown/incomplete gates are `HARNESS_INCOMPLETE`; a complete bundle with any failure is `FAILED`; only 30/30 `PASS` plus all complex-case checks `PASS` yields `PERFECT_LANDING_WITHIN_FROZEN_CASE_SCOPE`. Correct diagnosis never overrides.
10. Closed the fake-evidence path: every gate/coverage result now cites an in-root `{path, sha256}` evidence object that binds the exact subject ID, claimed result, and machine-checkable assertions. Missing files, wrong hashes, cross-gate reuse, or a false assertion hidden behind `PASS` all become `HARNESS_INCOMPLETE`.
11. Closed the selector-chain hole: selection now invokes the full combined-seal verifier, recomputes the canonical payload digest, requires canonical in-study paths, and compares the live protocol/exclusion bytes, sizes, and hashes to the exact combined bindings.
12. Closed search-completeness attestation: an offline deterministic compiler consumes a frozen retrieval manifest plus untouched PubMed ESearch response bytes, binds canonical HTTPS request URLs and payload path/hash/byte-count, emits Q1/Q2 capture manifests and the search snapshot, and runs the independent validator as a postcondition. Omission, substitution, reorder, fake hash, noncanonical URL encoding, incomplete page, or screening-universe drift fail closed.
13. Extended the combined seal to bind every execution/scoring/selection/isolation/scorer/compiler tool, schema and test source, including its own builder/test, the selector/test, raw-search compiler/validator/tests/schemas, protocol validator/test, and gate-evidence schema.

## Combined-seal execution binding

`bindings.primary_execution` now binds:

```text
protocol_version
protocol_md / protocol_json / scoring_contract
preprimary_seal_tool / preprimary_seal_test
selector_tool / selector_test
raw_search_compiler / raw_search_compiler_test
raw_search_validator / raw_search_validator_test
raw_search_response_schema / raw_search_retrieval_schema / search_snapshot_schema
protocol_validator / protocol_validator_test
final_scorer / final_scorer_test / final_result_schema
gate_evidence_schema
availability_compiler / availability_compiler_test / availability_schema
role_manifest_schema / search_snapshot_schema / screening_schema
mapped_observation_schema
```

## Verification

```text
Targeted suite: 77 run; 76 passed, 1 platform symlink test skipped
Protocol preflight: PASS
Python compile: PASS
Combined-seal preflight: FAIL_CLOSED (expected blocker)
```

Current blocker:

```text
runtime_v2/architecture_wire.py
current at 2026-07-21 08:27 JST: 95a9ab875045115c8f6f1b7c337ee4ee83cf82ebe1b69edabb7643a8a6f1a883
sealed : 71f760f56a5a9f8f49f0f695601c991e4ccd61de40b4cfcaa1e434fa071fb29e
```

A broader tools discovery run was 87 total: 81 passed, 1 platform test skipped, 3 runtime replay errors, and 2 structural-evidence failures. The replay errors are current runtime state-time regressions; the structural failures are `EVIDENCE_MISSING`. None is a protocol/compiler/selector/scorer failure, but all correctly prevent runtime freeze and case selection.

## Residual boundaries

- Role separation is audited by hashes/manifests, not enforced by an OS sandbox. Missing lineage is `HARNESS_INCOMPLETE`.
- A case report cannot identify an unperformed individual treatment counterfactual.
- The crucial complex real-case test has **not** happened: until the runtime/model are validly resealed and the combined pre-primary seal exists, no case may be selected.
