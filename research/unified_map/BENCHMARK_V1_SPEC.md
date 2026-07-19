# UCM executable benchmark v1 — immutable freeze specification

> This file is part of the `FROZEN-v1` source closure.  Do not edit it after
> the freeze manifest has been issued.  A semantic fix requires a new benchmark
> version; old results remain attached to v1.

## Purpose

Benchmark v1 tests one bounded synthetic claim: whether one candidate-produced
patient state can support diagnosis, natural-history prediction, intervention
prediction and recursive update across the executable W01–W20 micro-worlds.
It is not evidence of clinical validity.

The authoritative semantics are the exact source bytes of the frozen world
generators/oracles plus `prototype/unified_map/benchmark_v1_contract.py`.  The
older PRE-FREEZE formal-scope/typed-DSL track is retained as assurance research,
but is not an authority for this executable benchmark.  It attempted to restate
working Python semantics in a second language and consumed more control-plane
work than the research objective permits.

## Frozen panel

- W01–W14 and W16–W20 each contribute one panel.
- W15 contributes two independently scored panels:
  `W15A-randomized-identifiable` and
  `W15B-observational-nonidentified`.
- Total: 20 worlds, 21 panels.
- Every world supplies a deterministic public-history generator, hidden
  simulator state held by the judge, diagnostic target, all declared policies,
  counterfactual oracle, outcome distribution and expected utility.

## Corpus schedule

There are five precommitted replicate tuples.  Each tuple uses an independent
training, validation and sealed-test root seed.  Per panel and replicate:

- training: 32 episodes;
- validation: 8 episodes;
- sealed test: 16 episodes.

Training rows may contain judge-generated supervised targets for every declared
policy/horizon.  Inference rows expose only the public history and public
catalog.  Hidden state, generator seed, episode index, world/test identifiers
and unobserved future are never candidate inputs.

Five model seeds are mandatory for a complete candidate.  Screening runs may
use a strict subset but cannot be labelled a complete W01–W20 benchmark.

## Shared-state requirement

The candidate must expose exactly one serialized `SharedPatientState` per
patient cut.  Diagnosis and rollout receive that state and a non-patient query;
they do not receive the history.  Natural and intervention forecasts call the
same rollout function with different `ActionPlan` values.  Update receives the
old state plus a newly available public delta and returns a successor state.

The state hash binds the canonical payload, declared distance vector, schema
and compactness class.  A tuple of diagnosis/natural/treatment-specific patient
states is a `separate_task_baseline`, not a UCM candidate.

## Forecast target

World oracle DTOs are heterogeneous by design.  The fixed judge projection
hashes every finite numeric central-trajectory/probability leaf (excluding
variance, covariance and numerical diagnostics) into a signed 32-dimensional
signature.  Expected utility is scored separately and is not projected twice.
The projection code and hash domain are frozen source bytes.

## Measurements and decisions

The benchmark records M01–M16 as declared by the executable contract.  Primary
episode scores are diagnosis accuracy/NLL/Brier, natural and intervention
signature RMSE, utility error and oracle treatment regret.  Collision, OOD,
leakage, update, extension, new-readout, sample-efficiency, compactness, resource
and seed-stability probes are reported separately.  No compensating single
score is allowed.

Hard failures include attributable dangerous treatment collision, leakage,
task-private patient state, actual-future conditioning, intervention/condition
confusion, unsafe forced-known OOD, update inconsistency and irreproducibility.
Only hard-gate survivors enter a per-metric Pareto comparison.

## Freeze and change rule

`research/unified_map/BENCHMARK_V1_FREEZE.json` contains the exact source file
hashes, source-tree root, catalog/panel digests, metric-contract digest and seed
commitments.  The seed reveal is published only after candidate artifacts are
sealed.  Verification re-reads every file and live-rebuilds the catalog and
metric contract.  The freeze manifest is append-only.  Any frozen-byte drift
invalidates v1 execution and requires a new benchmark version.
