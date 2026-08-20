# Real-case “perfect landing” pre-registered gates

Status: **FROZEN BEFORE HOLDOUT INSPECTION**  
Gate version: `NCF-PLG-1.0.0`  
Architecture: `NCF-ARCH-1.0.0`  
Machine contract: `PERFECT_LANDING_GATES.json`

## 1. Purpose and blindness boundary

This document freezes what the phrase “the architecture lands perfectly on one
real case” is allowed to mean. It was written against the architecture contract,
not against the selected holdout. The gate author did not inspect a case-selection
file, article, diagnosis, event ledger, model pack, or expected output for the new
holdout.

The gate is strictly independent of every other VeSMed architecture. Passing
requires a self-contained NCF runtime, state schema, model pack and evidence tree.
An import, runtime fallback, data lookup, score, or hidden call into a different
architecture is `HF-IND-001`, even if the result is clinically correct.

Bound architecture inputs at freeze time:

```text
ARCHITECTURE_FINAL_v1.md
  sha256 d83b910f3cd32c777f126b245c2652e88fccb31aaa125b455f4c5af90cc4575c
architecture_final_v1.schema.json
  sha256 9804d21e8032f571b6cfd414c08b31891eab8856bc0502e0000df4b7d53f80d1
```

The case identity, expected diagnosis and article-derived future trajectory are
**not inputs to this gate**. The gate files must be hashed/sealed before those
items are opened by the implementing/evaluating path. If that temporal ordering
cannot be proved, the verdict is `HARNESS_INCOMPLETE`, not pass.

## 2. “Perfect” is a conjunction of facets, not top-1 diagnosis

Six independent facet verdicts are mandatory:

1. `STRUCTURE_PERFECT`: G01–G17 are executable end to end in the real runtime,
   including the required case-independent counterexamples.
2. `CASE_REPRESENTATION_PERFECT`: every public event is faithfully typed,
   temporally available, provenance-linked and either consumed or explicitly
   justified as non-rankable; no clinically consequential item silently drops.
3. `DIAGNOSTICALLY_LOCALIZED`: stagewise positive and reliable negative evidence
   moves the right processes in the right direction, concurrent processes can
   coexist, and decisive available evidence localizes the relevant process(es)
   without a diagnosis label or future outcome side channel.
4. `PREDICTIVELY_CASE_CONSISTENT`: forecasts were emitted before the next cut,
   used the same shared state and transition core, and the realized trajectory is
   not a zero-support contradiction. This is **case consistency**, never
   calibration or population-level predictive validity.
5. `ACTION_COUNTERFACTUAL_HONEST`: performed/planned/continued/stopped/washout
   actions are distinct; factual and counterfactual state are isolated; each
   effect carries an identification status and assumptions; an unidentifiable
   individual effect is not converted into a unique answer.
6. `OPEN_WORLD_REFINEMENT_HONEST`: unmapped/misfit evidence raises epistemic
   residual; dangerous collisions are detected; refinement is local and
   migratable; absence of a separating observation yields typed abstention.

Only the conjunction of all applicable hard gates may be called:

```text
PERFECT_LANDING_WITHIN_FROZEN_CASE_SCOPE
```

Even that phrase proves only that this frozen implementation expressed and
replayed this frozen case without violating the registered contracts. It does
not prove calibrated probabilities, causal correctness, general clinical
effectiveness, state minimality/sufficiency, or a universal “perfect medicine
map”.

### Evidence that is only `CASE-CONSISTENT`

The following can support a case-bounded readout but can never establish
“perfect” by themselves:

- the final published diagnosis is top-1;
- the eventual treatment response has the same sign as a rollout;
- the realized path falls inside one predicted interval;
- the mode/process narrative looks clinically plausible;
- the terminal outcome is reproduced after it is already public;
- a toy/synthetic refinement experiment passes outside the real runtime.

In particular, **final-diagnosis correctness cannot rescue any hard fail**. A
label-leaking classifier that names the disease but lacks concurrency, local
modes, honest OOD or honest counterfactuals is `FAILED`.

## 3. Result and hard-fail semantics

Every gate emits exactly one of:

```text
PASS
FAIL
NOT_APPLICABLE
NOT_EXECUTED
EVIDENCE_MISSING
```

- `FAIL`, `NOT_EXECUTED`, or `EVIDENCE_MISSING` on any applicable `hard` gate
  makes the overall perfect-landing verdict `FAILED`.
- `NOT_APPLICABLE` is legal only for a gate marked conditional and must include
  machine-readable proof that its trigger was absent. It is not a substitute for
  an unimplemented capability: the case-independent counterexample gates are
  always applicable.
- If blind ordering, artifact hashes, case-source provenance, or replay
  independence is unprovable, use `HARNESS_INCOMPLETE`.
- A clinically surprising but non-zero-probability future is not automatically a
  structural fail. It lowers the prediction facet to `CASE_INCONSISTENT` only
  under the frozen scoring rule. A future assigned zero/undefined support, or a
  forecast generated after seeing it, is a hard fail.
- Correct `UNIDENTIFIABLE` or `PARTIALLY_IDENTIFIED` output can be a **pass**. It
  is more correct than a fabricated point counterfactual.

## 4. Frozen hard gates

The JSON file is normative for exact procedures/evidence fields. This table is
the human index.

| Test ID | G | Facet | Decisive pass condition | Hard failure |
|---|---|---|---|---|
| `PL-IND-001` | scope | independence | runtime dependency/import/IO trace contains only NCF assets and approved libraries | any other architecture supplies state, data, score or fallback |
| `PL-BLIND-001` | G16/G18 | integrity | gate seal predates holdout identity/article/ledger/model inspection | ordering or hashes unprovable |
| `PL-LED-001` | G01/G02/G03 | representation | typed events separate occurrence, availability, hypothesis, action and outcome; no invented clock time | future/result/action semantics collapsed |
| `PL-LED-002` | G03 | representation | exact-once ingestion and fresh-process replay are byte-identical | duplicate changes state or replay diverges |
| `PL-STATE-001` | G04/G05 | structure | diagnosis, no-action forecast, action forecast and plan consume identical canonical state hash | task-specific recoding/cache/history side channel |
| `PL-STATE-002` | G07/G08/G09/G12 | structure | state validates the frozen wire schema and carries factorial processes, local coordinates/modes, action lifecycle and epistemic residual | required component absent or decorative constant |
| `PL-TIME-001` | G01/G05 | time | adding/removing events unavailable at cut leaves prior state bytes and all outputs unchanged | any future leakage |
| `PL-TIME-002` | G02 | time/action | planned action has no physiological transition; performed action changes exposure only when available | plan treated as performed or response leaks backward |
| `PL-FACT-001` | G06 | factor graph | every rankable fact has typed parent/generation path; reliable negative evidence produces directionally correct likelihood | severity-only positive scoring or ignored negative evidence |
| `PL-FACT-002` | G06 | factor graph | cloned same-source evidence and alternate renderings do not increase posterior certainty | correlated/duplicate evidence is counted as independent votes |
| `PL-CONC-001` | G07 | concurrency | non-exclusive process marginals can be simultaneously high and are not normalized to sum one | single mutually exclusive disease simplex |
| `PL-CONC-002` | G07/G13 | concurrency | activation/withdrawal of one process does not erase an independently supported co-active process | new complication overwrites existing process |
| `PL-MODE-001` | G08 | local modes | at least two relevant process/organ domains can hold distinct mode posteriors and couplings | one global mode is the only runtime state |
| `PL-MODE-002` | G08 | local modes | same coordinates/different mode twin yields different direction with guard/hysteresis; mode ablation breaks it | mode is merely renamed severity |
| `PL-SUPPORT-001` | G09/G11 | action history | same observed output/different support lifecycle twin yields different latent reserve/future | supported normal output treated as natural stability |
| `PL-GEOM-001` | G10 | geometry | topology/geometry ablation changes the preregistered neighbor/inference/plan counterexample in the expected direction | geometry utility is disconnected from runtime |
| `PL-DX-001` | G06/G07/G12/G18 | diagnosis | stagewise positive and negative evidence updates relevant concurrent processes directionally; no label/future injection | final top-1 achieved without evidence-responsive localization |
| `PL-DX-002` | G18 | diagnosis | after decisive publicly available evidence, the published process is localized and incompatible alternatives fall for explicit factors; co-processes remain expressible | correct label only after outcome/diagnosis disclosure, unexplained ties or mutually exclusive collapse |
| `PL-PRED-001` | G04/G11/G18 | prediction | every eligible cut has sealed pre-next-cut no-action/current-policy forecast from shared transition core | retrospective forecast or missing transition |
| `PL-PRED-002` | G08/G13/G18 | prediction | realized local-coordinate/mode/process changes have defined support and pass frozen case-consistency scoring | zero/undefined support or wrong mode machinery |
| `PL-ACT-001` | G02/G09/G11 | actions | no-op/continue/start/hold/stop/dose/washout are distinct where applicable and factual query order is pure | lifecycle actions collapse or counterfactual mutates factual state |
| `PL-ACT-002` | G13/G17 | counterfactual | action response updates the single state and all queries; outputs include identification class, assumptions, scope and uncertainty | unique individual effect asserted when not identified |
| `PL-OOD-001` | G12 | OOD | unmapped/conflicting/generation-misfit evidence changes the corresponding residual; known-process posterior cannot hide it | fixed unknown mass or silent dropping |
| `PL-OOD-002` | G12/G18 | OOD | case-independent unknown-process perturbation forces residual/abstention rather than confident known-branch choice | closed-world forced choice |
| `PL-REF-001` | G14 | refinement | opposite-response same-state witness is detected and blocks unsafe unique planning | dangerous collision is silent |
| `PL-REF-002` | G14/G17 | unidentifiable | when no public/safe observation separates response subtypes, runtime returns typed `UNIDENTIFIABLE` or an honest bound | guessed subtype or unique action sign |
| `PL-REF-003` | G15/G16 | refinement | an available separating check locally splits only the affected stratum; old states migrate with lineage | global rebuild, new check unavailable before result, or old state silently invalidated |
| `PL-REF-004` | G15/G16 | refinement | all unaffected old-scope queries pass frozen non-regression tolerance after refinement | unrelated outputs drift without declared scope change |
| `PL-CASE-001` | G18 | representation | all clinically consequential public facts/actions/results are consumed, or explicitly mapped to epistemic residual with rationale | decisive evidence/action silently unmapped |
| `PL-REPORT-001` | G18 | conclusion | report exposes each facet, every gate result, hashes, failures and limits; no top-1-based override | a single overall “success” hides failed facets |

## 5. Real-case evidence protocol

For every public-information cut, the evaluator must preserve:

```text
cut_id
available_event_ids and their source locators
canonical state bytes + sha256 + parent hash
consumed_state_hash for every query head
active-process marginals/joint summaries
process/organ-local coordinates with uncertainty
local mode posteriors and couplings
action instances and lifecycle state
epistemic residual components
factor contributions, including negative evidence and shared-source groups
pre-next-cut forecast artifact and creation/seal time
diagnosis, forecast, plan and identifiability readouts
```

All cuts must be replayed in a fresh process. The published final diagnosis,
terminal outcome, and later response may be used only as **later verification
targets**, never as earlier inputs.

The case representation gate does not demand that narrative boilerplate become a
rankable variable. It demands a complete denominator and an explicit disposition:
`rankable_consumed`, `record_only_nonrankable`, `epistemic_residual`, or
`excluded_with_reason`. A clinically consequential fact cannot be placed in the
last two categories merely to protect a score.

## 6. Prediction and diagnosis scoring boundary

Thresholds and scoring functions must be sealed before model output inspection.
At minimum they must specify:

- eligible prediction cuts/horizons and missing-follow-up handling;
- probability/support rule for continuous observations and discrete modes;
- directional evidence assertions for decisive positive and negative findings;
- process-localization rule that permits multiple co-active processes;
- tie/abstention semantics;
- baseline comparison and tolerance;
- OOD residual response rule;
- local-refinement non-regression tolerance.

The single case may yield `PREDICTIVELY_CASE_CONSISTENT`, but cannot yield
`CALIBRATED`. A stochastic miss can be reported as case inconsistency without
claiming architectural impossibility. In contrast, unavailable evidence use,
zero-support states that the architecture claims cannot represent, disconnected
geometry/modes, or a missing concurrent-process representation are hard
architectural failures.

## 7. Verdict lattice

Machine aggregation is deterministic:

```text
if blindness/provenance/replay evidence is missing:
    HARNESS_INCOMPLETE
elif any applicable hard gate != PASS:
    FAILED
elif any required facet is below its pass state:
    CASE_CONSISTENT_ONLY or STRUCTURALLY_PERFECT_CASE_INCONSISTENT
else:
    PERFECT_LANDING_WITHIN_FROZEN_CASE_SCOPE
```

Permitted facet states are enumerated in the JSON. Reports must not collapse
`STRUCTURE_PERFECT` and `PREDICTIVELY_CASE_CONSISTENT`, and must not turn an
honest `UNIDENTIFIABLE` counterfactual into failure merely because no unique
treatment answer exists.

## 8. Claims permanently forbidden from one holdout

Regardless of result, do not claim:

- calibrated diagnostic or prognostic probabilities;
- true individual treatment effects for unperformed actions;
- general superiority to clinical practice or other architectures;
- completeness/minimality of the patient state;
- absence of all dangerous collisions;
- population, hospital or time-distribution generalization;
- a unique, finite, permanent map of all medicine.

The strongest allowed positive sentence is:

> Under the frozen case, scope, model and gates, the independent NCF runtime
> expressed the concurrent processes and local modes, replayed the public
> trajectory without temporal leakage, produced case-consistent forecasts, and
> remained honest about OOD and unidentified counterfactuals.

