# UCM Architecture — final evidence-bounded result

> Status: **NO HARD-GATE-ELIGIBLE ARCHITECTURE**. The work supports a bounded,
> closed-catalog shared state, not an open-world or clinical Unified Clinical Map.

Canonical machine-derived decision evidence:
`research/unified_map/FINAL_EVIDENCE.json`, root
`sha256:54106a834a6343574381407a2c080db32349ad722e72a57acc0af95bfc3e8b04`.

## Outcome

`F18-causal-operator-ensemble-state-v1` is the sealed architecture studied most
deeply. It is a real one-state implementation: diagnosis, no-treatment forecast,
every treatment counterfactual and online update use the same immutable patient
object. It is nevertheless **not a winner**. Its complete frozen run has five
unsafe forced-known OOD decisions, so its UCM claim ceiling remains
`L2-RUNNABLE`. Exact independent reproduction and bounded red-team successes do
not waive that hard failure.

The strongest statement supported by all current evidence is:

> A finite recursive shared state is useful inside a fixed synthetic catalog,
> but the tested learned states do not establish a unified state that remains
> sufficient when mechanisms, checks, treatments or tasks are opened up.

## 1. Evidence authority and accounting

```text
benchmark: W01--W20 / 21 panels / M01--M16 / R01--R05
freeze root:
  sha256:8acb6623c2fdf79008240c5f5967b2143c4fb5e7bb87a4e8aa9f72e77ef33a2d

EXPERIMENT_INDEX.json:
  38 total
  30 count-eligible substantive experiments
  8 count-ineligible controls/repeated full runs/failed attempt
  1 failed attempt (EXP-037)
```

`EXP-037` is the failed F22-v1 attempt and is not counted. `EXP-038` is the
repaired F22-v2 ordinary screen; it is count-eligible, but its preregistered rule
requires **ABANDON** because the finalized run contains one dangerous collision
and one unsafe forced-known OOD decision. Experiment count and architecture
selection are deliberately separate.

The three complete ordinary evaluations each cover all W01--W20, all five
replicates and 1,680 sealed-test episode rows:

| Run | Family | Unsafe forced-known OOD | Hard gate | Role |
|---|---|---:|---|---|
| EXP-033 | F10 | 5 | fail | ineligible low-regret/compact comparator |
| EXP-034 | F14 | 21 | fail | ineligible lifted-dynamics comparator |
| EXP-035 | F18 | 5 | fail | sealed bounded red-team/reproduction subject |

Therefore the **primary eligible Pareto set is empty**.

## 2. F18 shared-state data path

The catalog-specific global model `M` is cross-patient and read-only after fit.
The only patient-specific object visible to a head is:

```text
SharedPatientState Z_t
  schema_version
  canonical payload bytes
  distance_vector
  state_hash
```

Candidate-visible events are folded once in availability order. The payload
contains observation summaries, treatment/check counts, two recursive ordered
event sketches, and the representation derived from them. Heads do not receive
raw history, simulator state, future observations, case/world/test identifiers,
or task-private patient latents.

F18 combines three views of that one public-history accumulator:

1. a soft controlled-behavior quotient over diagnosis and the catalog's
   action/horizon futures;
2. continuous lifted operator observables, rather than only a point class;
3. support/ambiguity coordinates used to express catalog support and unknown
   probability.

Its fan-out is:

```text
diagnosis              = D_M(Z_t)
future(no-op, h)       = R_M(Z_t, no-op, h)
future(do(A), h)       = R_M(Z_t, A, h)
future(do(B), h)       = R_M(Z_t, B, h)
updated patient state  = U_M(Z_t, VisibleDelta)
```

The heads are stateless, but their action/horizon readouts are catalog-specific.
That distinction matters: source-code reuse is not evidence that a patient state
can absorb a previously unseen check or treatment locally.

## 3. Executed closed loop

`prototype/unified_map/demo_v1.py` has a materialized run at
`results/unified_map/demo/20260719T073939Z-DEMO-956e6ca844/`.
Diagnosis plus no-op/A/B/C forecasts all consume the same pre-update hash:

```text
sha256:1282d5968795563ce3462df506842ad6a2acc2ad0386abf699c1a7b0f4b3a352
```

After the model selects a treatment using predicted utility, only the performed
treatment and newly visible synthetic observations enter `VisibleDelta`. The
same update path produces:

```text
sha256:87503e34df85a56b122b53a1d7b2015095f0a28a73a30d2c5622283e3f486b28
```

All post-update heads then consume that one new hash. This proves the runnable
one-state data flow; it does not prove prediction quality or safety.

## 4. Complete independent reproduction

The source-distinct implementation in `prototype/unified_map/independent_f18.py`
does not import `candidate_families.py` and separately implements the public
history fold, state wire, fit and heads. The full run is:

```text
results/unified_map/reproduction/
  20260719T101913Z-I18-full-repro-01c908cb1b

1,680 sealed episodes
28,720 rollout queries
260 primary-scope pair probes
five replicates, all 20 worlds / 21 panels
```

W16/W17 `S1` extension pairs are excluded exactly as in the frozen primary
runner because they require the separate extension reveal. All recorded state,
diagnosis, rollout, utility, update/replay and pair-distance maximum differences
are `0.0`; all four failure counters are zero.

This proves byte/numeric equivalence of I18 to sealed F18 over the declared
scope. It neither recomputes oracle accuracy metrics nor repairs F18's OOD hard
failure, and therefore does not promote F18 above `L2-RUNNABLE`.

## 5. Supplemental CONFIRM5 lite

The committed/revealed supplemental batch is:

```text
results/unified_map/postseal_confirm5_lite_t4_s2_p0/
  20260719T090636Z-POSTSEAL-CONFIRM5-25eeeb5ec6

scope: all W01--W20, R01--R05
per panel/seed: train 4, validation 1, sealed test 2
pair_probe_limit: 0
complete_benchmark: false
```

F10 and F18 pass this **lite** hard gate. F14 has 9 unsafe OOD decisions and
B02V2 has 10. B03V2 has separate task states and remains an ineligible negative
comparator even where its counters are zero. Within only this small, pair-free
sample, F10 and F18 are mutually nondominated: F10 is smaller/faster, while F18
has better dynamics/regret. This is a supplemental local Pareto observation,
not a replacement for the complete primary runs and not collision evidence.

## 6. Source-distinct red-team v2

The formal bundle and machine-derived verdict are:

```text
results/unified_map/redteam_v2/20260719T093209Z-RT2-6337a6ad2d
bundle root:
  sha256:d3b0ecfd8722e9863d84d3bd88ffa30d9e00b04976ac48b50cd00f02f34040b3
verdict: research/unified_map/REDTEAM_V2_VERDICT.json
```

Both sealed F18 and I18 were evaluated on the committed source-distinct pack.
The correct interpretation is mixed:

- **Closed-catalog local support:** unsafe forced-known OOD is `0/16`; dangerous
  collisions are `0/8`; known-action queries are state-only and side-effect
  free on this pack.
- **Open-world scope failure:** every unseen-check and opposite-response unseen-
  treatment row abstains safely, but actual support requires extension fitting
  and replay of visible history. There is no replay-free local state migration.
- **New nonlinear combination is mixed:** primary-catalog natural queries remain
  callable, while the extension-check half is scope-insufficient; no frozen
  accuracy threshold permits a broader compositional claim.
- **New task unknown:** the matched capacity ladder is descriptive and has no
  preregistered decision threshold, so the result is `INCONCLUSIVE`.
- **Minimality not supported:** F18 separates all four oracle-equivalent
  history-deletion controls in the verdict battery.

Zero failures on a bounded pack do not override five primary OOD hard failures,
nor do safe abstentions demonstrate support for an unseen operator.

## 7. Exploratory secondary metrics

The 1,307-row secondary battery at
`results/unified_map/secondary/20260719T090245Z-SECONDARY-25cd492973/` is marked
`formal_frozen_metric_claim=false` and must remain descriptive:

- M09 normalized error-AUC order starts F16, F10, F14, F22, F18;
- M11 finds F10/F14/F18/F22 all scope-insufficient for new check/treatment;
  **each family** replays 3,396 visible-history bytes across its two probes;
- M13 mean Python `tracemalloc` peak increments are approximately F22 49.0 KB,
  F10 49.7 KB, F18 191 KB and F14 399 KB; native allocator coverage is not
  guaranteed;
- M16 state/history/true-state readout order changes by family and capacity, so
  it is descriptive and inconclusive, not a sufficiency proof.

## 8. Final architecture disposition

| Evidence class | Supported statement |
|---|---|
| Verified | Freeze/custody, 38/30 experiment accounting, three full five-seed runs, runnable one-state fan-out/update, exact full-scope F18/I18 equivalence |
| Synthetic local support | F10/F18 lite Pareto trade-off; F18 closed-catalog RT2 OOD/collision/action behavior on the committed pack |
| Failed | Every complete ordinary candidate fails unsafe OOD; F22-v2 is abandoned; F18 cannot add unseen checks/treatments without extension fit and history replay; F18 minimality is unsupported |
| Unknown | Novel-task sufficiency, a general finite/dynamic UCM, transfer to real patients, clinical effectiveness, production safety and global optimality |

The supported architecture is therefore a **scope-relative finite shared state**,
not an open-world unified state.

## 9. Next highest-information experiment

Pre-register a new architecture/version rather than rescuing abandoned F22 in
place. Before any evaluation, seal its source and publish a fresh
commitment/reveal chain for a source-distinct pack. The architecture must natively
support `S1` state refinement for one held-out check and one held-out treatment
using only the old state, public extension parameters and the new visible delta:

- no core refit and no complete visible-history replay;
- nonzero opposite-response and collision pair probes;
- a fresh unknown-mechanism OOD set with a frozen zero-unsafe hard gate;
- an attribution-valid new-task comparison against same-capacity state,
  full-history and true-state views with numeric thresholds frozen in advance;
- relevant/irrelevant/redundant deletion controls to test minimality;
- B02V2/B03V2 and sealed F10/F18 comparators under the same pack.

This has the highest information gain because it directly distinguishes
“F18/F22 were merely monolithic catalog fits” from “the declared observation
regime cannot support replay-free open-world shared state refinement.”
