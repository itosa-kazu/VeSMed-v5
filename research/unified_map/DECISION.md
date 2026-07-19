# UCM Final Decision Record

> **Decision: no ordinary candidate passes the complete frozen hard gate; no
> UCM winner is selected.** Current evidence supports only a finite,
> closed-catalog, synthetic shared-state approximation.

## Outcome

The project did build genuine shared-state systems rather than API wrappers:
their diagnosis, natural-course, treatment-counterfactual and update paths read
one patient state. That operational property is necessary but not sufficient.
The complete runs show unsafe OOD behavior, and the strongest sealed subject
cannot absorb unseen checks or treatments without a new fit and visible-history
replay.

The final decision has four evidence partitions:

1. **Verified:** the frozen benchmark and oracle, machine experiment accounting,
   three complete five-seed candidate runs, one-state fan-out/update, and exact
   source-distinct reproduction of sealed F18.
2. **Synthetic local support:** useful closed-catalog prediction and bounded
   RT2 collision/OOD/action behavior; a supplemental pair-free F10/F18 trade-off.
3. **Failed:** complete-candidate OOD hard gates, F22-v2 safety gates,
   replay-free unseen-check/treatment extension, and F18 minimality support.
4. **Unknown:** novel-task sufficiency, existence of a general finite/dynamic
   UCM, and all real-clinical, production-safety and global-optimality questions.

## Key evidence block

```text
canonical final evidence:
  research/unified_map/FINAL_EVIDENCE.json
  root=sha256:54106a834a6343574381407a2c080db32349ad722e72a57acc0af95bfc3e8b04

benchmark freeze root:
  sha256:8acb6623c2fdf79008240c5f5967b2143c4fb5e7bb87a4e8aa9f72e77ef33a2d

EXPERIMENT_INDEX:
  total=38; count_eligible=30; count_ineligible=8;
  failed_attempt_count=1; evidence_gap_count=0

EXP-037 F22-v1:
  failed attempt; no finalized ordinary bundle; count-ineligible

EXP-038 F22-v2:
  finalized/count-eligible; dangerous_collision=1;
  unsafe_forced_known_ood=1; decision=ABANDON

complete primary evaluations (all W01--W20 x R01--R05; 1,680 rows each):
  EXP-033 F10: unsafe OOD=5; hard gate FAIL
  EXP-034 F14: unsafe OOD=21; hard gate FAIL
  EXP-035 F18: unsafe OOD=5; hard gate FAIL; claim ceiling L2-RUNNABLE

supplemental CONFIRM5 lite:
  run=20260719T090636Z-POSTSEAL-CONFIRM5-25eeeb5ec6
  all worlds x five seeds; train4/val1/test2; pair_limit=0; incomplete
  F10/F18 lite hard-gate pass; F14 unsafe=9; B02V2 unsafe=10;
  B03V2 separate-task baseline is ineligible

source-distinct red-team v2:
  run=20260719T093209Z-RT2-6337a6ad2d
  root=sha256:d3b0ecfd8722e9863d84d3bd88ffa30d9e00b04976ac48b50cd00f02f34040b3
  OOD unsafe=0/16; dangerous collisions=0/8 (bounded local support)
  unseen check/treatment=OPEN_WORLD_SCOPE_FAILURE
  nonlinear combination=MIXED closed-catalog support/open-world scope failure
  novel task=INCONCLUSIVE; state minimality=NOT_SUPPORTED

full independent F18 reproduction:
  run=20260719T101913Z-I18-full-repro-01c908cb1b
  1,680 episodes; 28,720 rollout queries; 260 primary-scope pairs
  all recorded max differences=0.0; all failure counters=0
  W16/W17 S1 pairs excluded per frozen runner scope
  equivalence only; no oracle metric recomputation; no OOD repair
```

## Hard-gate and Pareto decision

Unsafe forced-known OOD is noncompensating. F10, F14 and F18 are therefore
eliminated before primary Pareto selection regardless of their average forecast,
regret, size or latency. B01 is privileged, B02V2 is unbounded full history,
B03V2 has separate task states, and B04/K0-only is a negative control.

Accordingly:

- **primary hard-gate-eligible Pareto set: empty**;
- **supplemental lite local Pareto set: F10 and F18**, and only within the
  incomplete train4/val1/test2, pair-zero sample;
- **B03V2: negative/ineligible comparator**, never a shared-state point.

In the lite sample F10 is smaller/faster and F18 has lower dynamics error and
regret, so neither dominates the other. This cannot overwrite the complete
primary failures and supplies no collision evidence.

## Secondary evidence boundary

The secondary battery is explicitly exploratory (`formal_frozen_metric_claim=false`).
Its descriptive results are:

- M09 normalized error-AUC rank: F16, F10, F14, F22, F18;
- M11: F10/F14/F18/F22 are all scope-insufficient; each family replays 3,396
  visible-history bytes across its two probes;
- M13 mean Python `tracemalloc` peak increments: F22 about 49.0 KB, F10
  49.7 KB, F18 191 KB, F14 399 KB; native allocator coverage is not guaranteed;
- M16 changes ordering across views/capacities and is inconclusive.

None of these rows creates a frozen-metric winner.

## Existence interpretation

The privileged true-state control shows that every declared finite simulator has
a finite sufficient hidden state. That is an oracle existence result, not proof
that visible history identifies the state or that a learned compact map exists.
The candidate results establish a narrower proposition: a recursively updated,
finite shared state can be useful for a fixed catalog.

Red-team v2 identifies the boundary. F18 can safely abstain on unseen operators,
but abstention is not support; enabling the new check/treatment requires extension
fit plus history replay. The history-deletion controls also show unnecessary
state distinctions. Thus an open-world unified state and a minimal behavioral
quotient have **not** been established. Nor do the failures prove that every
finite or dynamically growing UCM is impossible.

## Next highest-information experiment

Run a preregistered source-distinct comparison of a **native S1 incremental
extension architecture** against sealed F10/F18, B02V2 and B03V2. Before opening
the pack:

1. seal source and publish a fresh commitment/reveal chain;
2. hold out one check and one treatment with opposite-response pairs;
3. require the old core/state lineage to refine without core refit or any
   complete visible-history replay;
4. pre-freeze nonzero pair probes, a zero-unsafe OOD hard gate, and numeric
   new-task thresholds with matched state/history/true-state capacity controls;
5. include relevant, irrelevant and redundant history-deletion controls;
6. report extension bytes, changed core bytes, state growth and old-scope
   regression as hard evidence rather than a scalar score.

This is higher information gain than another catalog-bound parameter sweep: it
directly tests the open-world/replay boundary that survived every current
closed-catalog success. Success would localize the problem to monolithic F18/F22
designs; failure under mechanism-identifying observations would strengthen the
case that this observation regime cannot support the requested replay-free state.

## Claim boundary

Nothing here establishes clinical effectiveness, real-patient calibration,
production safety, regulatory adequacy, a globally optimal architecture, or a
general impossibility theorem.

The machine-rederived claim surface is `research/unified_map/FINAL_EVIDENCE.json`;
`prototype/unified_map/final_evidence.py` rejects either receipt drift or a
semantic strengthening of this decision.
