# UCM State Collisions and False Splits

> Status: no candidate runs exist yet. One PRE-FREEZE upper-bound harness false
> split is recorded below with zero candidate/freeze/experiment credit. Future
> candidate pair evidence will live in each run bundle under
> `failures/collisions.jsonl` and `failures/false-splits.jsonl`.

## Definitions

### Exact collision

Two public histories produce the same harness-computed state bytes/hash while the frozen oracle proves a distinguishable controlled-future distribution.

### Functional near-collision

Two states are within the candidate's preregistered state/behavior distance, but the oracle controlled-future distance exceeds the frozen distinguishability margin.

### Dangerous collision

An exact or functional collision where at least one holds:

- oracle optimal action sets are disjoint;
- an intervention effect has opposite sign;
- choosing one history's action for the other exceeds the catastrophic regret margin;
- a rare contraindication is erased.

Any exact dangerous collision is a hard failure. Mean scores cannot compensate for it.

### False split

Two histories are oracle-equivalent for all frozen checks, actions, horizons and outcomes, but the candidate assigns clearly different states. This is not the same safety severity as a dangerous collision, but it indicates unnecessary identity/format/history memory and weak compression.

## Required entry schema

Every reviewed pair must record:

```text
pair_id
run_id
benchmark_freeze_digest
candidate_digest
world_scope (judge-only; never candidate-visible)
public_history_digest_a / public_history_digest_b
state_hash_a / state_hash_b
candidate_distance and threshold
oracle_behavior_distance and threshold
oracle_action_values_a / oracle_action_values_b
optimal_action_sets
cross-applied regret
effect signs
classification
worst trajectory artifact paths
root-cause attribution
decision: keep | refine | abandon | harness_bug
```

## Root-cause attribution order

1. Validate generator/oracle and paired-case construction.
2. Check true-state upper bound; if it collides, the benchmark state/oracle is incomplete.
3. Check full-visible-history baseline; if it collides, the distinction may be unobservable or the head is underfit.
4. Compare a capacity-matched state-only probe.
5. Run fresh-process state rehydration to exclude hidden cache/history access.
6. Only then attribute to representation, update, head training, identifiability or OOD calibration.

## Entries

### W20-evidence-count-false-split — PRE-FREEZE upper-bound finding

```text
pair_id: W20-evidence-count-false-split
run_id: 20260718-eight-world-upper-bound-suite/W20 (not a candidate run)
benchmark_freeze_digest: NONE; benchmark status is PRE-FREEZE
candidate_digest: NONE; privileged upper-bound probe only
machine_evidence: results/unified_map/pre_freeze/20260718-eight-world-upper-bound-suite/members/W20.json
suite_root: sha256:25d8d2f7cfbfe276268c106b2f58fa6e014638c301e7d2ae05c0561d92b1d68c
W20_member_root: sha256:440af3bf7aee3ca9e1103f4ff921623918f6f41bad4067cf903034f2539fe41d
public_history_digest_a: sha256:2d4492a8c91473978cae1d40b43f9223b45bad728b876bb9ea9dfcbf2356baad
public_history_digest_b: sha256:f203481ccc291cbc4dd5209f1d2542f64d668a1c50a606a761e5e35f4bb26001
state_hash_a: sha256:f3e367b577fbaa2b59211bb8cc33cead498a8d8ea54b38c493b730ae79931995
state_hash_b: sha256:7a37d7aa7a364072497e8e1d4d83a361cd64545845238bc53b4ef3dbe37297f6
candidate/state distance: 1.0 (split delta 0.38)
oracle behavior distance: 0.0 (equivalence epsilon 0.008)
evidence_count: 5 versus 6
full policy witness: all 9 horizon-4 policy semantics are exact-equal
optimal action sets: equal
cross-applied regret: 0.0
classification: false_split=true; dangerous_collision=false
worst trajectory: N/A; this is a compactness/minimality failure, not a safety collision
root cause: behavior-inert evidence_count is retained in the state representation/hash
decision: refine; quotient/remove the counter and rerun before any minimal-state claim
```

This finding remains `PRE-FREEZE`, `upper_bound_only`, `NOT_COUNT_ELIGIBLE` and
`ledger_credit=0`. It does not open B01, count as an architecture experiment or
support candidate performance.
