# UCM State Collisions and False Splits

> Status: no candidate runs exist yet. This file defines the append-only review index; machine-readable pair evidence will live in each run bundle under `failures/collisions.jsonl` and `failures/false-splits.jsonl`.

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

None. Planned pairs and synthetic examples do not count as observed collisions.
