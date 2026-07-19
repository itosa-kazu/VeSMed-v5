# UCM State Collisions and False Splits

> Status: FINAL EXECUTED LEDGER. Candidate pair evidence lives in each run's
> `raw-pairs.jsonl`; this file lists the decisive witnesses and final disposition.

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

### W20-evidence-count-false-split — PRE-FREEZE finding, repaired

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

Repair evidence (仍为 PRE-FREEZE、零 credit)：

```text
run_id: 20260718-twenty-world-upper-bound-suite/W20
machine_evidence: results/unified_map/pre_freeze/20260718-twenty-world-upper-bound-suite/members/W20.json
suite_root: sha256:b2dafe80b6464edfb38b1e5369c9fd9381db98ad699f53904c316290e9673834
W20_member_root: sha256:39405d07bced6378e1b974a73d85af8a76e0c0f0e07def38e2e4f1111a4105fa
raw evidence_count: 5 versus 6
state_hash_a = state_hash_b:
  sha256:8d60f4af66542c5f2e6f94c1dd420776919fdcd67150e12ee319f237a1fe03d9
full policy witness: 9/9 horizon-4 policy semantics exact-equal
classification: false_split=false; dangerous_collision=false
repair: raw history/count retained as audit provenance, excluded from behavior state identity
minimal_quotient_claimed: false
remaining blocker: minimal-behavioral-quotient-not-proved
```

Disposition: the specific counter-induced false split is closed. The historical
entry above is retained as the falsifier that forced the repair; it must not be
rewritten into evidence that the whole W20 quotient is minimal.

### CE-005-W08-ordered-availability-collision — FROZEN-v1 candidate hard failure

```text
run_id: 20260719T023205Z-EXP-005-624e359e1b
benchmark_freeze_digest: sha256:8acb6623c2fdf79008240c5f5967b2143c4fb5e7bb87a4e8aa9f72e77ef33a2d
world_scope: W08 / primary / probe-fixtures / group 2
left_state_hash:  sha256:9e5965b1112d50fba8a398fb5e09444c290c58a0dbc856dc4e3d4b5e9ff07d89
right_state_hash: sha256:9e5965b1112d50fba8a398fb5e09444c290c58a0dbc856dc4e3d4b5e9ff07d89
candidate_distance: 0.0 (same threshold 1e-9)
oracle_behavior_distance: 1.4725555397536851 (distinguishable threshold 0.05)
classification: dangerous_collision=true
root_cause: fixed accumulator retained unordered summary statistics but erased
            event order/availability path needed for controlled futures
cross-check: B02 full-visible-history screening had dangerous_collision_count=0
decision: refine architecture; add recursive ordered/availability memory
```

The same decisive W08 pair kills F01, F03, F04, F05, F06, F07 and F08 v1.
It is not a hyperparameter failure and cannot be compensated by their mean scores.

### CE-010-W18-forced-known — FROZEN-v1 OOD hard failure

```text
run_id: 20260719T023227Z-EXP-010-6336703880
world_scope: W18 / primary / sealed test
episode 0: target unknown=1.0; predicted unknown≈1e-9; brier≈0.999999998
episode 1: target unknown=0.8297740058; predicted unknown≈1e-9;
           brier=0.6885248990
classification: unsafe_non_abstain
root_cause: closed-set nonnegative ridge normalization; no support/epistemic state
decision: add support uncertainty inside shared patient state, not an external head gate
```

All eleven first-batch runs had two unsafe W18 rows. Full history did not fix it,
so this failure is not evidence loss alone; it is an explicit open-world modeling gap.

### CE-015 — Support exists in state but is not decision-effective

```text
runs: EXP-013 F10, EXP-015 F12
dangerous collisions: 0
unsafe forced-known OOD: 2 each
classification: OOD hard failure
root cause: support/novelty coordinates were present, but the initial diagnosis
            operation did not preserve them as unknown probability
decision: refine open-world probability semantics inside the shared state path
```

This prevents a misleading claim that merely concatenating an uncertainty
feature makes a state open-world sufficient.

### CE-020 / CE-025 — Forecast progress does not compensate OOD failure

```text
EXP-020 F13: candidate distance collisions=0; unsafe OOD=2
EXP-025 F18: natural RMSE=.172977; intervention RMSE=.201332;
             dangerous collisions=0; unsafe OOD=2
classification: hard failure despite Pareto forecast improvement
```

Both bundles are retained. The later corrected screen versions EXP-031/032 have
zero unsafe rows on the small screen, but the complete evaluation shows that the
apparent closure did not generalize. Formal RT2 later supplies a different
bounded local pass; it does not repair that complete-run failure.

### CE-030 — Point-collapse destroys behaviorally relevant uncertainty

```text
run_id: 20260719T025556Z-EXP-030-7705e42a2f
family: F21 point-collapsed causal state
dangerous_collision_count: 4
W04 decisive pair: candidate_distance=0.0; oracle_behavior_distance=41.7119
W08 decisive pair: candidate_distance=0.0; oracle_behavior_distance=.9453
decision: abandon point estimate; retain posterior/distribution as state
```

This is a direct minimal counterexample to replacing a behavioral posterior with
its argmax label. Average diagnosis or rollout scores cannot repair it.

### CE-035 — Complete primary OOD hard failure

```text
sealed candidate: F18 structural ensemble
complete run: 20260719T063049Z-EXP-035-c28452cba8
scope: all W01--W20 x R01--R05; 1,680 episode rows
measured dangerous collisions: 0
unsafe forced-known OOD: 5
candidate seal:
  sha256:f5d21dcd27d9416701937647a4b0de212cd74499f3eeb137780bfbecaafc9d57
classification: noncompensating OOD hard failure
claim ceiling: L2-RUNNABLE
```

The zero measured primary collisions are useful but cannot compensate for OOD.
F18 was sealed as an ineligible subject for further attack and reproduction, not
as a winner.

### Legacy post-selection probe — exploratory, not source-distinct

The older run `20260719T064407Z-F18-redteam-69f7a4c8e6` reported 27 reused-fixture
pairs with zero dangerous collisions/two false splits, plus reused-W18 OOD rows
with 9 forced-known and 26 false-unknown decisions. Those observations remain a
historical diagnostic signal only:

- the generator imported/reused frozen world code and fixtures;
- there was no independently authored attack pack or complete commitment/reveal
  chronology;
- the independent implementation was not evaluated on that unopened pack;
- the novel-task/deletion/time-scale probes lacked the attribution controls later
  required by the formal protocol.

It must not be called “fresh source-distinct red-team” and cannot provide an
`L4-POSTFREEZE_REDTEAM_SUPPORTED` pass.

### RT2-PAIR — final source-distinct bounded collision audit

```text
run: 20260719T093209Z-RT2-6337a6ad2d
bundle root:
  sha256:d3b0ecfd8722e9863d84d3bd88ffa30d9e00b04976ac48b50cd00f02f34040b3
subjects: sealed_f18 + independent_f18
dangerous-collision rows: 8 (4 per implementation)
recomputed dangerous collisions: 0/8
minimum oracle margin: 0.5051882769933154
minimum state distance: 1.6085491088571402
verdict: CLOSED_CATALOG_LOCAL_SUPPORT
```

The eight preregistered rows show that both implementations preserve these
specific controlled-future distinctions. They do not close untested collision
classes. CONFIRM5 lite contributes no additional collision evidence because its
pair-probe limit is zero.

### RT2-DELETE — false splits and minimality

The formal history-deletion trio contains six rows across the two implementations:

```text
oracle-distinguishable relevant-deletion rows: 2/2 separated
oracle-equivalent irrelevant/redundant rows: 4
oracle-equivalent rows collapsed: 0/4
oracle-equivalent false-split rows: 4/4
verdict: NON_MINIMAL_STATE_EVIDENCE
overall state-minimality verdict: NOT_SUPPORTED
```

F18 retains useful distinctions, but it also remembers behaviorally inert details
in this pack. It therefore has no exact/minimal behavioral quotient claim.

### RT2-OOD and open-world scope

OOD and operator expansion are separate from collision classification but bound
the interpretation:

- RT2 unsafe forced-known OOD is `0/16`, a bounded local success on this committed
  pack; it does not erase CE-035's five complete-run failures.
- All unseen-check and opposite-response unseen-treatment rows abstain safely,
  yet actual support requires extension fit plus visible-history replay. This is
  `OPEN_WORLD_SCOPE_FAILURE`, not a collision pass or local refinement.
- The RT2 novel-task result is `INCONCLUSIVE`; no preregistered threshold permits
  a sufficiency inference.

### EXP-038 — F22 refinement still collides

```text
run: 20260719T085521Z-EXP-038-046568f23d
family: F22 factorized refinement v2
dangerous_collision_count: 1
unsafe_forced_known_ood: 1
count_eligible substantive experiment: true
decision: ABANDON
```

The repaired F22 query path completed, so this is an ordinary architecture
result rather than a harness crash. Its one dangerous collision is sufficient to
abandon it under the preregistered rule.

### Final disposition

- CE-005 falsifies unordered summary state; CE-030 falsifies point-collapse of
  behaviorally relevant uncertainty.
- Full visible history can preserve information but is noncompact and is only a
  baseline; it does not solve identification or OOD by itself.
- Sealed F18 has zero dangerous collisions in the measured complete pair scope
  and `0/8` in source-distinct RT2, but this supports only those finite probes.
- F18 minimality is not supported (`4/4` oracle-equivalent deletion controls are
  split), and its complete OOD failure keeps it UCM-ineligible.
- F22-v2 adds a new concrete dangerous collision and is abandoned.
- The primary hard-gate-eligible Pareto set remains empty; the pair-free lite
  F10/F18 frontier cannot be used for a collision claim.

The next preregistered architecture comparison must use a fresh commitment/reveal
pack with nonzero opposite-response pairs, new-check and new-treatment `S1`
refinement, zero full-history replay, OOD hard thresholds, and relevant/
irrelevant/redundant deletion controls. Averages alone remain insufficient.
