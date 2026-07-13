# Machine-readable architecture benchmark protocol

> **Purpose**: turn `T01–T50` and `E01–E08` into one runnable, candidate-neutral benchmark without treating a manifest, a trace string, or a candidate's own claim as evidence of correctness. This note specifies the wire contract, workload schema, oracle classes, Python API, directory layout, fairness accounting, and the smallest credible implementation sequence. It does **not** select an architecture and does not modify runtime code.

## 0. Non-negotiable protocol rules

1. **The candidate sees inputs, not answers.** A workload file is compiled into a `candidate_view` and a runner-only `oracle_view`. The candidate process receives only the former. Reference latent paths, expected values, assertion predicates, comparison branch IDs, and tolerances remain runner-side.
2. **A declaration is never a pass.** `manifest.declared_capabilities` is compared with observed behavior only to measure honesty. It cannot satisfy any semantic, numerical, provenance, temporal, or composition oracle.
3. **Every pass has a behavior witness.** The runner must have actually called the candidate and evaluated the returned result, a later state, or a relation between two independent executions. A static feature checklist is not an oracle.
4. **Explicit refusal and correctness are separate dimensions.** `unsupported` can pass `boundary_explicit` while failing `behavior_correct` and, for a HARD requirement, failing the hard gate. An implementation that returns `unsupported` for everything therefore scores zero semantic coverage.
5. **The common adapter is syntax-only.** It may frame JSON, validate schema, launch a process, and canonicalize transport-level ordering. Deduplication, time filtering, unit conversion, missingness interpretation, causal semantics, provenance construction, clinical inference, and composition are candidate semantics and may not be supplied by the harness.
6. **Reference simulators are judges, not libraries.** Candidate code cannot import them. Public model commitments may be shared as `K_shared`; hidden state paths, oracle seeds, exact enumerations, and comparison code stay in the runner.
7. **One workload, several independent verdicts.** Results retain at least `behavior_correct`, `boundary_explicit`, `claim_consistent`, `trace_complete`, `numerical_fidelity`, and `hard_gate`. They are not collapsed into a weighted score.
8. **Clean rebuild is the neutral retraction oracle.** A candidate need not implement a truth-maintenance system, but its incremental result after correction/retraction must equal a fresh instance built from the surviving event versions.
9. **Equivalent workload transformations are first-class tests.** Duplicate delivery, independent-event permutation, future append, paraphrase, module registration order, composition bracketing, and concept renaming are executed on separate fresh sessions and compared by the runner.
10. **Family capability and prototype coverage are distinct.** A report may say “the family can express X, this prototype did not”; machine results still record the prototype as `honest_unsupported` and not as passing X.

---

## 1. Proposed repository layout

The benchmark should be a new, isolated package rather than being wired into the legacy V5 runtime:

```text
archbench/
  pyproject.toml
  README.md
  protocol_version.txt
  schemas/
    workload.schema.json
    artifact.schema.json
    knowledge_package.schema.json
    operation.schema.json
    query.schema.json
    capability_result.schema.json
    candidate_manifest.schema.json
    assertion_result.schema.json
    run_record.schema.json
  src/archbench/
    api.py                  # Python Protocol + dataclasses/TypedDict
    jsonrpc.py              # language-neutral JSONL subprocess transport
    schema.py               # JSON Schema validation only
    canonical_json.py       # transport equality/hashing; no clinical semantics
    runner.py               # phase/branch execution and fresh-session isolation
    oracle_registry.py      # allowlisted runner-side oracle IDs
    verdicts.py             # independent verdict dimensions; no total score
    provenance_checks.py    # witness/root invariants
    temporal_checks.py      # cut and future-leak invariants
    metamorphic.py          # branch transformations and comparisons
    capability_checks.py    # claim-versus-observed and refusal checks
    accounting.py           # primitive/special-case/blast ledgers
    run_store.py            # content-addressed, non-overwriting result bundles
  commitments/
    shared/v1/
      concepts.json
      units.json
      clinical_relations.json
      action_effects.json
      interface_types.json
    extensions/
      new_disease_module.json
      new_drug_module.json
      new_test_method.json
  workloads/
    T/
      T01.json ... T50.json
    E/
      E01.json ... E08.json
    holdout/
      aliases.enc.json      # released only by the runner
      isomorphic_domain.enc.json
      parameter_seeds.enc.json
  oracles/
    predicates.py
    semantic.py
    temporal.py
    provenance.py
    actions.py
    causal.py
    composition.py
    reference/
      common.py
      e01_masked_dynamics.py
      e02_confounding.py
      e03_shared_exogenous.py
      e04_lagged_nonlinear.py
      e05_selective_mechanisms.py
      e06_composed_pk.py
      e08_feedback.py
    golden/                 # trusted oracle outputs and analytic limit cases
  candidates/
    <candidate_id>/
      manifest.json
      adapter.py            # transport/native mapping, charged if semantic
      native/
      companions/
        <layer_id>/
      modules/
  tests/
    contract/
      test_schema_roundtrip.py
      test_rpc_lifecycle.py
      test_result_statuses.py
      test_candidate_view_excludes_oracles.py
    harness/
      test_oracle_selftests.py
      test_metamorphic_engine.py
      test_clean_rebuild_engine.py
      test_run_isolation.py
      test_no_manifest_pass.py
    reference/
      test_e01_limits.py ... test_e08_limits.py
      test_seed_reproducibility.py
    workloads/
      test_T_panel.py       # parametrized over T01..T50
      test_E_panel.py       # parametrized over E01..E08
    mutation/
      test_known_time_mutants.py
      test_unknown_negative_mutants.py
      test_provenance_duplication_mutants.py
      test_do_conditioning_mutants.py
      test_order_dependence_mutants.py
    accounting/
      test_track_isolation.py
      test_ablation_receipts.py
      test_special_case_ledger.py
      test_blast_radius.py
  results/
    <run_id>/
      run_record.json
      candidate_manifest.snapshot.json
      candidate_code_hashes.json
      workload_hashes.json
      raw_rpc.jsonl
      branch_results/
      assertions.jsonl
      verdict_matrix.json
      primitive_profile.json
      special_cases.json
      blast_radius.json
```

`test_T_panel.py` and `test_E_panel.py` are parametrized loaders; there is no need to duplicate Python logic in 58 files. Each JSON workload remains independently hashable and reviewable.

---

## 2. Separation of the four judge mechanisms

The protocol uses four mechanisms. They answer different questions and must not be substituted for each other.

| Mechanism | What is executed | What it can prove | What it cannot prove |
|---|---|---|---|
| **Behavior oracle** | Calls a candidate, inspects its result and subsequent externally visible state | exact information state, typed error, no collision, hypothesis coexistence, source roots, replay cuts, action interval, interface failure | quantitative trajectory accuracy unless a numerical reference exists |
| **Capability honesty** | Compares manifest claim, actual status, diagnostic detail, and pre/post state | refusal is explicit, stable, non-mutating, and claim-consistent | that the refused capability is implemented; honesty is not semantic coverage |
| **Reference simulator** | Independently generates/solves a public toy model and compares candidate outputs | numerical/relational fidelity for filtering, forecast, interventional and compositional queries within a declared tolerance | clinical validity, general family expressiveness, or correctness outside the toy model |
| **Metamorphic oracle** | Runs transformed but semantically related workloads on fresh sessions and compares outputs | idempotency, future isolation, order/bracketing invariance, clean rebuild, paraphrase/isomorphism robustness | absolute correctness if both branches are identically wrong; pair with at least one anchor behavior oracle |

### 2.1 Verdict record

Every assertion returns a machine record rather than a bare boolean:

```json
{
  "assertion_id": "T12.no_future_visibility",
  "workload_id": "T12",
  "oracle_kind": "behavior|honesty|reference|metamorphic",
  "dimension": "temporal|epistemic|audit|causal|dynamic|composition|safety|extension",
  "hard_gate": true,
  "passed": false,
  "observed": {"json_pointer": "/value/claims", "digest": "sha256:..."},
  "expected": {"predicate": "all_known_from_lte", "cut": "..."},
  "evidence_refs": ["rpc:00017", "result:q-at-09", "branch:fresh-rebuild"],
  "diagnostic": "claim lab-1 was available only at 12:00",
  "oracle_version": "temporal.no_future_visibility@1"
}
```

The workload verdict is a vector:

```json
{
  "behavior_correct": false,
  "boundary_explicit": true,
  "claim_consistent": true,
  "trace_complete": null,
  "numerical_fidelity": null,
  "order_robust": null,
  "hard_gate": false,
  "classification": "HONEST_UNSUPPORTED"
}
```

Allowed classifications are `PASS`, `FAIL`, `HONEST_UNSUPPORTED`, `DISHONEST_CLAIM`, `INVALID_RESULT`, `NUMERICAL_FAILURE`, `HARNESS_ERROR`, and `NOT_RUN`. `HARNESS_ERROR` never becomes a candidate failure; it blocks publication until fixed.

### 2.2 Honesty probes cannot be gamed by universal refusal

For every declared capability, the runner executes at least one positive probe, one boundary probe, and a pre/post snapshot check:

1. If the manifest says `supported`, returning `unsupported` yields `claim_consistent=false` and `behavior_correct=false`.
2. If it says `unsupported`, a typed refusal with `missing_capability`, `unsupported_scope`, and no state mutation yields only `boundary_explicit=true`; semantic coverage remains false.
3. A generic `unsupported` with no operation, scope, or reason fails boundary honesty.
4. `unsupported` after partial mutation fails both honesty and behavior.
5. Returning canned `ok` without satisfying the behavior oracle fails behavior even if the capability claim is consistent.
6. Returning canned answers keyed by test ID is attacked by hidden isomorphic-domain, parameter, branch-order, and alias variants and is entered in `S_patch` if detected by review or instrumentation.

---

## 3. Machine-readable workload envelope

Use JSON, JSON Schema 2020-12, UTC RFC 3339 timestamps, and content hashes. JSON is only the interchange format; it does not count as a candidate primitive.

### 3.1 Top-level workload schema

```json
{
  "$schema": "../schemas/workload.schema.json",
  "protocol_version": "1.0.0",
  "workload_id": "T12",
  "title": "sample at 08:00, result available at 12:00",
  "panel": "T",
  "requirements": ["R-TIME-01", "R-REP-01"],
  "severity": "HARD",
  "tags": ["bitemporal", "future-leak"],
  "candidate_input": {
    "knowledge_packages": ["shared/v1"],
    "branches": [
      {
        "branch_id": "main",
        "fresh_session": true,
        "steps": [
          {"step_id": "i1", "op": "ingest", "artifacts": ["artifact:lab-1"]},
          {"step_id": "q09", "op": "query", "query": "query:state-at-09", "capture": "r09"},
          {"step_id": "q13", "op": "query", "query": "query:state-at-13", "capture": "r13"}
        ]
      }
    ]
  },
  "oracle_view": {
    "assertions": [
      {
        "assertion_id": "no-future",
        "kind": "behavior",
        "oracle_id": "temporal.claim_visibility@1",
        "args": {"result": "main:r09", "forbid_artifact": "lab-1"},
        "hard_gate": true
      },
      {
        "assertion_id": "visible-later",
        "kind": "behavior",
        "oracle_id": "semantic.claim_present@1",
        "args": {"result": "main:r13", "artifact": "lab-1"},
        "hard_gate": true
      }
    ]
  },
  "fixtures": {
    "artifacts": [],
    "queries": [],
    "modules": []
  }
}
```

The loader physically strips `oracle_view`, assertion IDs, hidden variant selectors, and reference outputs before constructing the RPC request stream. Candidate subprocesses run with a candidate-only working directory. This is not intended as a hostile-code security boundary, but it prevents accidental oracle coupling and makes leakage auditable.

### 3.2 Artifact schema

The boundary artifact represents what arrived, not the candidate's world-state data structure:

```json
{
  "artifact_id": "lab-1",
  "artifact_version": 1,
  "replaces_version": null,
  "invalidates": [],
  "artifact_role": "observation|subject_statement|request|action_event|report|proposed_extraction|knowledge_assertion",
  "scope": {
    "subject_id": "P1",
    "encounter_id": "E1",
    "specimen_id": "S1",
    "device_id": "D1",
    "site_id": "ICU",
    "body_site": null
  },
  "times": {
    "occurrence": {"start": "...", "end": "...", "precision": "second"},
    "effective": {"start": "...", "end": null},
    "collected_at": "...",
    "available_from": "...",
    "recorded_at": "...",
    "expires_at": null,
    "happens_before": []
  },
  "content": {
    "concept_id": "serum_creatinine",
    "information_state": "present|absent|not_asked|not_tested|unable_to_assess|insufficient|conflicting|not_applicable|out_of_model|masked",
    "polarity": "positive|negative|unknown",
    "value": {
      "kind": "quantity|censored_quantity|code|boolean|interval|text|none",
      "magnitude": 1.8,
      "unit": "mg/dL",
      "comparator": null,
      "lower": null,
      "upper": null
    },
    "method_id": "assay-v1",
    "detection_limit": null,
    "conditions": ["on_high_flow_oxygen"],
    "reliability": {"kind": "declared", "value": 0.95}
  },
  "action": null,
  "ascertainment": {
    "opportunity_id": "window-1",
    "expected": true,
    "observed": true,
    "selection_process_id": "routine-labs-v1"
  },
  "source": {
    "source_system": "fixture",
    "source_record_id": "row-17",
    "source_family_id": "tube-S1",
    "independence_assertion_id": null,
    "author_id": "device-D1"
  },
  "visibility": {"class": "visible|masked|unauthorized", "policy_version": "p1"},
  "raw": {
    "media_type": "application/json",
    "payload": {},
    "payload_sha256": "sha256:...",
    "source_spans": [{"start": 0, "end": 12}],
    "mapping_version": "fixture-map-v1"
  }
}
```

Key distinctions are forced at the boundary so that candidates cannot claim the test was underspecified:

- `artifact_id` is stable delivery identity; `source_family_id` expresses possible shared origin; neither automatically proves statistical independence.
- `available_from` controls what may enter an as-known query; `effective`/`occurrence` controls what time the claim is about.
- censored quantities use comparator and detection limit, never magic numeric values.
- action events use a dedicated structure:

```json
{
  "action_id": "norepi-course-1",
  "stage": "requested|ordered|started|partially_performed|performed|paused|refused|cancelled|stopped",
  "dose": {"kind": "quantity", "magnitude": 0.2, "unit": "ug/kg/min"},
  "actual_interval": {"start": "...", "end": "..."},
  "idempotency_key": "pump-event-889",
  "reason": null
}
```

### 3.3 Knowledge/module package schema

Domain commitments are data, not hidden runner logic:

```json
{
  "package_id": "shared-v1",
  "version": "1.0.0",
  "known_from": "...",
  "valid_interval": {"start": "...", "end": null},
  "scope": "general_knowledge",
  "imports": [],
  "ports": [
    {
      "port_id": "map_observation",
      "semantic_type": "Observation[MAP]",
      "direction": "input",
      "subject_scope": "same_subject",
      "unit": "mm[Hg]",
      "time_role": "effective",
      "context_contract": ["support_conditions_preserved"]
    }
  ],
  "commitments": [
    {
      "commitment_id": "abx-modifies-culture-sensitivity",
      "kind": "observation_effect",
      "inputs": ["antibiotic_performed"],
      "targets": ["culture_observation_process"],
      "semantics": {"public_model_id": "culture-sensitivity-v1"}
    }
  ],
  "declared_composition": {
    "operator": "typed_wiring",
    "laws": [],
    "unsupported_if": ["interaction_required_but_absent"]
  },
  "integrity": {"sha256": "sha256:..."}
}
```

There is no arbitrary runner-supplied callback in this schema. A candidate may compile commitments into factors, rules, equations, rewrites, or components. The compiler belongs to that candidate and is counted as adapter/generator code. `K_shared` is the same semantic commitment even when its native encodings differ.

### 3.4 Query schema

```json
{
  "query_id": "q1",
  "kind": "facts_at|hypotheses|projection|state_estimate|forecast|observational|interventional|individual_counterfactual|safety_check|history|explanation|composition",
  "scope": {"subject_id": "P1", "encounter_id": "E1"},
  "time_cut": {
    "valid_at": "...",
    "known_at": "...",
    "recorded_at_or_before": "...",
    "replay_mode": "replay_as_then|reinterpret_now",
    "knowledge_selector": {"mode": "as_then|explicit", "versions": []}
  },
  "task": {
    "task_id": "diagnosis|severity|medication_safety|audit|custom",
    "goals": [],
    "utility": null,
    "constraints": [],
    "authorization": null
  },
  "targets": ["perfusion_impairment"],
  "conditioning": [],
  "interventions": [],
  "horizon": null,
  "return_contract": {
    "accepted_value_kinds": ["set", "interval", "distribution", "qualitative"],
    "require_evidence_witness": true,
    "require_native_witness": true
  }
}
```

The separate `conditioning` and `interventions` arrays prevent a transport-layer ambiguity between `see` and `do`. `individual_counterfactual` additionally requires a factual evidence cut and `cross_world_policy: share_abduced_exogenous`.

### 3.5 Workload operations

The operation union is deliberately small:

```text
ingest(artifacts)
query(query_contract)
revise(target_artifact_id, correction_or_retraction)
replay(query_contract, input_cut, knowledge_cut, mode)
register_module(module_package)
compose(component_ids, typed_wiring)
simulate(query_or_action_plan)
explain(result_id)
snapshot(scope)
```

`snapshot` exposes only the candidate's documented external semantic state/result digest; it is used to detect mutation on refused operations. It does not require candidates to reveal private caches.

---

## 4. Candidate-neutral Python and JSONL APIs

### 4.1 Python protocol

The concrete Python surface should be a factory plus an isolated session. Methods return data structures validated against JSON Schema; they do not inherit a shared semantic implementation.

```python
from __future__ import annotations
from typing import Any, Mapping, Protocol, Sequence

Json = Mapping[str, Any]

class CandidateSession(Protocol):
    def ingest(self, artifacts: Sequence[Json]) -> Json: ...
    def query(self, query: Json) -> Json: ...
    def revise(self, revision: Json) -> Json: ...
    def replay(self, request: Json) -> Json: ...
    def register_module(self, package: Json) -> Json: ...
    def compose(self, request: Json) -> Json: ...
    def simulate(self, request: Json) -> Json: ...
    def explain(self, result_id: str) -> Json: ...
    def snapshot(self, scope: Json) -> Json: ...
    def close(self) -> None: ...

class CandidateFactory(Protocol):
    def manifest(self) -> Json: ...
    def create(self, run_context: Json) -> CandidateSession: ...
```

A candidate can implement all operations with a single native evaluator or explicitly return a typed unsupported result. The runner never subclasses the candidate with a default clinical behavior.

### 4.2 Language-neutral JSONL transport

Every Python call has a one-request/one-response JSONL equivalent:

```json
{"protocol":"archbench/1.0","request_id":"0001","op":"query","payload":{...}}
{"protocol":"archbench/1.0","request_id":"0001","result":{...}}
```

The process handshake reports protocol version and code/layer hashes, not semantic passes. Candidate stderr is captured as diagnostics and cannot replace a result. Timeouts become `NUMERICAL_FAILURE` or `HARNESS_ERROR` according to whether the process was responsive to a health probe.

### 4.3 Capability result schema

```json
{
  "result_id": "r-001",
  "status": "ok|unsupported|insufficient|conflicting|out_of_model|invalid_input|numerical_failure|internal_error",
  "semantic_role": "fact_projection|inference|hypothesis|forecast|policy|audit|none",
  "value_kind": "exact|set|interval|distribution|trajectory|qualitative|none",
  "value": null,
  "assumptions": [
    {"assumption_id":"a1","kind":"identification|independence|approximation|coverage|composition","text":"...","scope":{}}
  ],
  "coverage": {
    "modeled": [],
    "unmodeled": [],
    "unknown": [],
    "applicability": "in_domain|partial|out_of_model|unknown"
  },
  "time_cut": {
    "valid_at": "...",
    "known_at": "...",
    "knowledge_versions": []
  },
  "information_state": "present|absent|unknown|conflicting|not_applicable|out_of_model|masked|null",
  "evidence_witness": {
    "root_ids": [],
    "source_family_ids": [],
    "independence_assumptions": [],
    "derivations": [
      {"node_id":"d1","operator_id":"rule-or-model","version":"v1","input_ids":[],"output_ids":[]}
    ]
  },
  "native_witness": {
    "kind": "proof_term|factor_subgraph|event_slice|rewrite_trace|reachability|program_address|solver_certificate|none",
    "payload": null,
    "digest": "sha256:..."
  },
  "diagnostics": {
    "capability_code": null,
    "unsupported_scope": null,
    "identification_status": "identified|partially_identified|not_identified|not_applicable|unknown",
    "solver_status": "exact|converged|bounded|not_converged|multiple_solutions|no_solution|not_run",
    "algorithm": null,
    "tolerance": null,
    "error_bound": null,
    "seeds": [],
    "warnings": []
  },
  "versions": {
    "candidate": "...",
    "knowledge": [],
    "model": [],
    "terminology": [],
    "layers_used": []
  }
}
```

Candidates are not forced to fabricate a native DAG. `native_witness.kind=none` is honest, but any test requiring a provenance or native explanation then fails that dimension. A computation call stack does not satisfy `evidence_witness`.

---

## 5. Oracle DSL and runner-side registry

Workload JSON may reference only versioned, allowlisted `oracle_id` values. It cannot embed Python or candidate-specific code.

### 5.1 Simple predicate DSL

Simple assertions use JSON Pointer plus a closed operator set:

```json
{
  "oracle_id": "predicate.json@1",
  "args": {
    "result": "main:r1",
    "path": "/status",
    "op": "eq|ne|in|contains|subset|superset|lt|lte|gt|gte|approx|is_null|is_typed_error",
    "expected": "ok"
  }
}
```

Complex semantic checks are named runner functions such as:

```text
temporal.no_future_visibility@1
temporal.expired_not_current_but_historical@1
provenance.unique_roots@1
provenance.no_support_from_rootless_cycle@1
provenance.incremental_equals_clean_rebuild@1
semantic.no_collision@1
semantic.local_conflict_nonexplosive@1
actions.only_performed_interval_has_effect@1
causal.see_do_sign_reversal@1
causal.shared_exogenous_counterfactual@1
composition.typed_interface_failure@1
composition.bracketing_equivalence@1
numerical.trajectory_within_tolerance@1
```

Each oracle implementation is pure over captured RPC records/reference outputs, has its own unit tests, and emits an `AssertionResult` with the exact evidence paths it inspected.

### 5.2 Metamorphic branch schema

```json
{
  "assertion_id": "duplicate-delivery-idempotent",
  "kind": "metamorphic",
  "oracle_id": "metamorphic.semantic_equivalence@1",
  "args": {
    "left": "baseline:q",
    "right": "duplicate:q",
    "ignore_paths": ["/result_id", "/diagnostics/runtime_ms"],
    "compare": ["value", "information_state", "evidence_witness/root_ids"]
  }
}
```

The runner never mutates a live session to create both sides unless the relation explicitly tests an incremental operation. Otherwise each branch uses a fresh process, fresh store, and a randomized transport request ID.

### 5.3 Reference comparison schema

```json
{
  "assertion_id": "e04-forecast",
  "kind": "reference",
  "oracle_id": "numerical.trajectory_within_tolerance@1",
  "args": {
    "candidate": "irregular:q-forecast",
    "reference_id": "E04.forecast@1",
    "metric": "rmse_and_phase",
    "absolute_tolerance": 0.08,
    "relative_tolerance": 0.15,
    "coverage_required": 0.9,
    "seed_policy": {"seeds": [1103, 2207, 3301, 4409, 5519], "aggregate": "median_and_worst"}
  }
}
```

An interval/set-valued candidate may pass a safety-containment assertion if the reference path is contained and the interval is finite/non-vacuous; it does not receive a probability-calibration label. A probabilistic candidate reports proper scores/calibration where applicable. These are separate fidelity columns.

---

## 6. Coverage map for T01–T50

All rows execute a real candidate branch. “Honesty” below is an additional verdict, never the sole passing condition for a HARD behavior.

| ID | Main behavior exercised | Primary oracle(s) | Required companion branch / anchor |
|---|---|---|---|
| T01 | support-dependent MAP vs natural MAP | exact result relation + `semantic.no_collision` | paired untreated branch; evidence roots inspected |
| T02 | high-flow SpO2 context retained | exact + no-collision | room-air isomorphic branch |
| T03 | antipyretic affects manifestation, not proof of no inflammation | exact absence-of-illegal-inference | no-drug branch anchor |
| T04 | beta blocker and pacer contexts remain distinct | exact + three-way no-collision | registration/order permutation |
| T05 | pre-culture antibiotic modifies observation process | exact assumption/coverage + no invalid “no infection” | antibiotic/no-antibiotic pair |
| T06 | three derived fever labels share one root | provenance unique-root count | duplicate-derived-label metamorphism |
| T07 | fever/CRP/WBC shared dependence not presumed independent | evidence-family/independence witness check | independence metadata removed/added pair |
| T08 | same phenotype supports multiple hypotheses | set containment + no forced singleton | hypothesis order permutation |
| T09 | context locally modulates observation relation | no-collision + unchanged disease identity contract | immunosuppressed/ordinary pair |
| T10 | two oxygen records conflict without overwrite | exact `conflicting`, both roots retained | input-order permutation |
| T11 | unmentioned rash remains unknown/not-asked | exact information state | explicit-negative branch anchor |
| T12 | collection/availability cut prevents future leak | temporal visibility exact | 09:00 vs 13:00 queries |
| T13 | final diagnosis excluded from presentation replay | temporal exact + future-append invariance | branch without final diagnosis |
| T14 | same creatinine, different baseline gives different readout | no-collision | baseline swap pair |
| T15 | two task projections differ without mutating facts | exact task readout + snapshot invariance | projection order permutation |
| T16 | unknown nonlinear interaction is not silent addition | typed unresolved/unsupported + honesty | interaction-present anchor; E06 provides numeric discrimination |
| T17 | state and observation effects are separately visible | exact dual-channel witness | stop/start interval pair |
| T18 | temporal succession alone does not force causation | multi-explanation/identification-status exact | stronger-identification branch anchor |
| T19 | expiry affects current, not historical view | temporal exact | current vs historical query |
| T20 | unseen disease may be out-of-model | exact coverage/status | nearby-known-model branch to prevent universal refusal |
| T21 | new disease is local extension | behavioral extension result + blast-radius instrumentation | pre/post module registration; old-suite rerun |
| T22 | new measurement method is isolated/local | typed method behavior + blast radius | incompatible-method negative probe |
| T23 | as-then and reinterpret-now differ with same raw facts | replay exact | two knowledge-version branches |
| T24 | retracting a temperature invalidates only dependents | clean-rebuild equivalence + provenance exact | independent second-root branch |
| T25 | arbitrary historical replay excludes all future inputs | temporal trace invariant | multiple random cutoffs and future append |
| T26 | safety invariant survives retrieval miss | exact safety outcome | retrieval-index removed branch |
| T27 | two instruments vs three paraphrases have 2 vs 1 roots | provenance counts + support relation | paired metamorphic branches |
| T28 | infection and sterile inflammation coexist | hypothesis set containment | evidence-strength perturbation |
| T29 | unknown device gives typed quarantine with raw payload | exact invalid-input preservation + honesty/non-mutation | known-device positive probe |
| T30 | equivalent language normalizes isomorphically | semantic-isomorphism metamorphism | original spans/provenance remain distinct |
| T31 | rootless reasoning cycle creates no support | fixed-point/provenance exact | rooted-cycle positive branch; E08 feedback distinction |
| T32 | late correction creates new view and updates dependents | clean rebuild + old-cut replay exact | old/new transaction cuts |
| T33 | incompatible units/methods fail; legal conversion traced | exact typed error/conversion witness | convertible and non-convertible branches |
| T34 | two module paths do not multiply one root | root-set idempotence metamorphism | direct vs fan-out/fan-in branch |
| T35 | approximate posterior exposes solver/seed/error status | result diagnostics exact + reference tolerance when implemented | forced nonconvergence boundary probe |
| T36 | knowledge-rule removal affects new interpretation, not raw facts | versioned replay + clean rebuild | as-then/now pair |
| T37 | only performed action interval creates effects | action lifecycle exact | requested/refused/cancelled/performed branches |
| T38 | incompatible component ports fail before execution | typed composition error + non-mutation honesty | compatible wiring positive probe |
| T39 | incompatible probabilistic modules remain disagreement or explicit arbitration | exact assumptions/disagreement | single-model anchor; no unrecorded averaging |
| T40 | cache cannot inject future result into replay | cached-vs-fresh metamorphism | warm-cache and cold-cache branches |
| T41 | subject/encounter/specimen scope does not cross | exact isolation + invalid wiring | same-subject positive control |
| T42 | censoring and assay limits remain non-point values | exact value kind/method preservation | alternate detection-limit branch |
| T43 | no observation opportunity does not imply negative | exact ascertainment/missingness | observed-negative branch anchor |
| T44 | rash contradiction remains local and non-explosive | exact conflict + unrelated-query invariance | remove-one-side branches |
| T45 | normalization round-trips to raw value/unit/span/version | provenance/raw round-trip exact | mapping-version reinterpretation |
| T46 | no unique treatment optimum without goals/utility | typed insufficient/unsupported policy claim + honesty | explicit-utility positive probe |
| T47 | policy-induced observations and online updates are versioned/rollbackable | exact exposure/model version + replay | rollback/clean rebuild branch |
| T48 | duplicate action delivery is idempotent; cancellation stops effect | metamorphic duplicate + action interval exact | partial/performed/cancel sequence |
| T49 | general knowledge does not become patient fact without bridge | scope exact + provenance | legal bridge positive branch |
| T50 | masked is distinct from absent/negative | exact information state + no-collision | visible-negative and unknown branches |

Each row has at least one positive anchor so a candidate cannot satisfy the panel by rejecting every input. Where the architecture legitimately does not implement a component capability, the report shows both the honest boundary and the failed full-core requirement.

---

## 7. Coverage map and reference specifications for E01–E08

The E panel uses dimensionless toy models. It assesses architecture semantics and numerics, not medical parameter validity.

### E01 — treatment-masked latent dynamics

- Public model: latent impairment `S in [0,1]`, performed support `U in [0,1]`, observation `MAP = 75 - 25*S + 18*U + eps`. Transition is `dS/dt = 0.08*(1-S) - 0.18*U*S`; support therefore changes both state evolution and observation.
- Candidate input: public model package, irregular noisy MAP observations, actual support intervals, and query cuts. Hidden `S(t)` and noise seed are withheld.
- Behavior anchors: natural MAP near 70 and supported MAP near 70 must not collide; query differentiates state estimate, stop-support forecast, and `do(U=0)` counterfactual.
- Reference: RK4 at a much finer step than candidate output, plus seeded observation noise; compare state/forecast trajectory and direction after stop. A safe interval candidate is judged by coverage and width; distribution candidates also get log/CRPS-style fidelity.
- Metamorphic: append future observations and verify earlier filtering unchanged; compare continued vs stopped support.

### E02 — confounding and see/do reversal

- Exact finite SCM: `P(H=severe)=0.5`; `P(T=1|severe)=0.9`, `P(T=1|mild)=0.1`; bad-outcome probabilities are severe `(T0=.90,T1=.60)` and mild `(T0=.20,T1=.05)`.
- Exact oracle: `P(Y_bad|T=1)=0.545`, `P(Y_bad|T=0)=0.270`, while `P(Y_bad|do(T=1))=0.325 < P(Y_bad|do(T=0))=0.550`.
- The candidate must produce distinct observational/interventional operations and list identification assumptions. Returning the same number fails behavior. Typed `unsupported` can pass honesty only.
- Reference uses exact enumeration, not Monte Carlo.

### E03 — same-unit counterfactual shares exogenous background

- Public SCM includes a binary individual response variable `R`, treatment, and repeated outcome. The factual post-treatment trajectory updates `P(R|e_factual)`.
- The individual counterfactual oracle performs abduction, replaces the treatment mechanism, then predicts while retaining the posterior over the same `R`. A population `do(T=0)` samples the population prior over `R`.
- Required relation: individual counterfactual differs from population intervention whenever factual evidence is informative about `R`; posterior mass over `R` is shared across worlds.
- Reference uses exact enumeration over `R` and noise states. A fresh unconditioned patient masquerading as the individual counterfactual is a hard causal failure.

### E04 — irregular nonlinear lagged dynamics

- Public model: pathogen `B` follows logistic growth with a finite antibiotic pulse; inflammation is a saturating Hill response; CRP is a first-order lag `dC/dt=(hill(B)-C)/tau`.
- Reference simulator uses an adaptive/fine-step integration checked against halved-step convergence. Candidate sees irregular observation times and public equations, not the hidden dense path.
- Queries: filter, as-known smoothing, 24-hour forecast. Oracles cover no future leak, rising-vs-falling phase discrimination at the same CRP, delayed peak after the pulse, trajectory error, and multi-seed diagnostics.
- Metamorphic variants jitter sampling schedules without changing the underlying path and append future points after the filter cut.

### E05 — same phenotype, two mechanisms, selective intervention

- Public two-mode model: infection and sterile inflammation both raise fever/CRP; antipyretic changes only temperature observation, while antibiotic changes only infection mechanism.
- Exact/small-state reference computes hypothesis weights or safe hypothesis sets across time.
- Oracles require both hypotheses before discriminating evidence, no selective loss after antipyretic, relative support change after mechanism-specific response, and order-aware forecast without treating action order as file order.
- A set-valued candidate passes safe containment if it retains all non-excluded modes; it does not receive probabilistic calibration credit.

### E06 — nonlinear three-module composition

- Public modules: infection `A`, renal clearance `B`, drug PK/toxicity `C`; explicit interaction `I` defines saturating clearance and nonlinear efficacy/toxicity curves through typed ports.
- Candidate runs `A`, `A+C`, `A+B+C`, `A+B+C+I`, then substitutes a second `B` with the same interface.
- Without `I`, correct behavior is an explicit unresolved/unsupported composition, not implicit addition. With `I`, reference ODE/finite-difference trajectories must differ from an independent sum and remain within tolerance.
- Instrumentation records whether A/C/core changed during B substitution. Interface mismatch is a build-time behavior oracle, not a manifest assertion.

### E07 — composition laws and order robustness

- Four fresh branches execute `(A tensor B) tensor C`, `A tensor (B tensor C)`, randomized registration orders, and permutations of independent updates.
- The runner compares only laws the candidate's formal signature claims. Claiming associativity and violating it is both behavior failure and claim inconsistency. Not claiming a law is not automatically failure if the candidate explicitly defines an order; accidental hash/file order remains failure.
- The anchor branch checks the composed system actually uses all three modules, preventing a candidate from being “invariant” by ignoring them.

### E08 — valid feedback vs epistemic self-support

- Case 1: contraction `x_(n+1)=0.4*x_n+0.6`, with unique fixed point 1. Behavior/reference oracle requires convergence or a certified interval containing the unique solution.
- Case 2: `A supported_by B`, `B supported_by A`, with no evidence root. Provenance oracle requires zero generated support.
- Case 3: `x=x+1` (no solution) and `x=x` without a boundary condition (non-unique). Result must be `no_solution` / `multiple_solutions` / explicitly strategy-dependent, not an arbitrary value.
- A universal “reject all cycles” fails Case 1; a universal “run all cycles” fails Cases 2/3. This combines exact, reference fixed-point, and behavior oracles.

### 7.1 Frozen public parameter records for the first implementation

The prose above must be compiled into ordinary JSON packages. To avoid every prototype silently solving a different toy problem, the first benchmark version should freeze at least the following public records (later changes require a benchmark-version bump):

```json
{
  "E01": {
    "state": {"S0_prior": {"kind":"beta","alpha":8,"beta":2}, "bounds":[0,1]},
    "control": {"U_bounds":[0,1], "performed_intervals":[[4,12]]},
    "dynamics": "dS_dt = 0.08*(1-S) - 0.18*U*S",
    "observation": "MAP = 75 - 25*S + 18*U + Normal(0,1.5)",
    "observation_hours": [0,2,4,6,9,12,15,20],
    "query_hours": [9,12,18,24]
  },
  "E02": {
    "P_severe": 0.5,
    "P_treated_given_severe": 0.9,
    "P_treated_given_mild": 0.1,
    "P_bad": {"severe_T0":0.90,"severe_T1":0.60,"mild_T0":0.20,"mild_T1":0.05}
  },
  "E03": {
    "R": {"values":[0,1],"probabilities":[0.5,0.5]},
    "structural_equation": "Y = R*(1+T) + (1-R)*(-T)",
    "factual_evidence": {"T":1,"Y":2},
    "queries": ["individual_cf(T=0)","population_do(T=0)"]
  },
  "E04": {
    "initial": {"B":0.08,"C":0.0118},
    "parameters": {"r":0.35,"K":1.0,"k_abx":1.0,"hill_h":3,"hill_K":0.35,"tau_hours":6.0},
    "dynamics": [
      "dB_dt = r*B*(1-B/K) - k_abx*A*B",
      "I = B^hill_h/(hill_K^hill_h+B^hill_h)",
      "dC_dt = (I-C)/tau_hours"
    ],
    "pulse": {"A":1,"start_hour":6,"end_hour":10},
    "observation_hours": [0,3,7,11,16,24,31],
    "query_hours": [7,16,24,40]
  },
  "E05": {
    "prior": {"infection":0.5,"sterile":0.5},
    "pre_treatment_phenotype_likelihood": {"infection":0.8,"sterile":0.8},
    "P_response_after_antipyretic": {"infection":0.8,"sterile":0.8},
    "P_mechanism_response_after_antibiotic": {"infection":0.9,"sterile":0.2}
  },
  "E06": {
    "initial": {"burden":0.25,"drug_amount":0.0,"renal_capacity":0.45},
    "parameters": {"r_burden":0.25,"CL0":0.8,"Km":0.3,"Emax":0.9,"EC50":0.4,"Tmax":0.7},
    "ports": ["A.drug_effect<-I.efficacy","I.burden<-A.burden","I.amount<-C.amount","I.renal<-B.capacity","C.clearance<-I.clearance"],
    "interaction_equations": [
      "clearance = CL0*renal*amount/(Km+amount)",
      "efficacy = Emax*amount/(EC50+amount)",
      "toxicity = (amount^2/(Tmax^2+amount^2))*(1-renal)",
      "dBurden_dt = r_burden*burden*(1-burden)-efficacy*burden"
    ]
  },
  "E08": {
    "contraction": "x_next=0.4*x+0.6",
    "no_solution": "x=x+1",
    "non_unique": "x=x"
  }
}
```

The E03 record has an analytic oracle: factual `T=1,Y=2` implies `R=1`; therefore the same-unit counterfactual at `T=0` is `Y=1`, while the population intervention has `E[Y|do(T=0)]=0.5`. The model is intentionally dimensionless and minimal: it tests cross-world identity, not treatment realism.

For E01/E04/E06, units in the equations are benchmark time units/hours as stated. The JSON package must also include observation-noise distributions, prior/initial uncertainty, numerical horizon, and public semantic port types. Hidden files contain realized noise and dense latent paths only. The default reference grid is at most `1/600` of an hour; step halving must change reported golden query values by less than `1e-5` before candidate tolerances are set. Candidate tolerance is then frozen from task relevance and observation noise, not tuned after seeing candidate results.

---

## 8. Shared tests versus candidate-specific code

### 8.1 Fully shared

The following code and data are identical for every candidate:

- schemas, canonical fixture artifacts, queries, public `K_shared`, extension packages;
- workload phase/branch graphs and hidden metamorphic transformations;
- runner lifecycle, process isolation, timeouts, raw RPC capture, hashing;
- oracle implementations, reference simulators, tolerances, seeds, and verdict logic;
- clean-rebuild construction and branch comparison;
- result envelope validation and evidence/native-witness inspection;
- run record, environment capture, and Pareto-table generation.

### 8.2 Candidate-owned and charged

- mapping canonical artifacts/queries into native objects and mapping native answers back;
- compiling `K_shared` into rules/factors/equations/rewrites/components;
- stores, solvers, inference/planning engines, provenance/time layers, validators, OOD layers;
- generated schemas, indexes, caches, migrations, model weights, and runtime callbacks;
- all native and companion configuration needed to reproduce behavior.

### 8.3 Forbidden shared semantic help

The runner must not provide a universal reducer, unit converter, provenance graph, bitemporal filter, causal engine, hypothesis updater, or module composer to all candidates while calling those features “transport.” If such a service is intentionally tested as a shared companion, it is versioned, appears in every applicable Track B primitive profile, and its ablation is run. Its behavior cannot be credited to Track A.

---

## 9. Native/companion tracks and fair accounting

### 9.1 Track definitions

**Track A — native** permits:

- the candidate's fixed formal signature and execution semantics;
- minimal serialization/deserialization that preserves fields one-to-one;
- ordinary persistence required by the native semantics;
- its normal generic solver if that solver is part of the claimed family instance.

It does **not** permit a hidden bitemporal/provenance/causal/validation layer in the adapter.

**Track B — deployable companion** permits named, reusable semantic layers. Each layer must have:

```json
{
  "layer_id": "bitemporal-ledger-v1",
  "semantic_responsibilities": ["known_time_filter", "revision_history"],
  "code_roots": ["companions/bitemporal"],
  "primitive_profile": {},
  "foreign_escapes": [],
  "dependencies": [],
  "configuration_hash": "sha256:..."
}
```

If a candidate passes only in Track B, the report names the resulting hybrid, e.g. “SSM + temporal evidence companion,” rather than crediting the bare SSM.

### 9.2 Required ablations

For `n` companion layers, do not require all `2^n` subsets by default. Run:

1. native only;
2. all companions;
3. leave-one-layer-out for every layer;
4. any pair whose declared responsibilities overlap;
5. the minimal passing subset found by delta debugging, recorded as an empirical attribution rather than proof of theoretical minimality.

Each result includes `versions.layers_used`; the runner also launches configurations with layer code physically absent, so self-reported layer receipts are not the sole attribution evidence.

### 9.3 Primitive profile

Report a vector, not a scalar:

```text
P = (
  typed object/value constructors,
  state/update operators,
  time/visibility operators,
  uncertainty/belief operators,
  intervention/counterfactual operators,
  composition/wiring operators,
  query/readout operators,
  built-in invariant/constraint forms,
  persistence/replay operators,
  foreign semantic escape hatches
)
```

Rules for fairness:

- `Node(payload)`, `Rule(fn)`, `Factor(fn)`, `Component(fn)`, or an unrestricted callback is not one primitive. Expand the semantic families implemented behind it and list every registered callable.
- A generic compiler from `K_shared` to native forms counts once as a generator/adapter plus its output schema; test-ID or concept-specific branches count separately as patches.
- A standard numerical solver counts as one solver dependency plus each semantic model family supplied to it; the solver does not magically supply causal, provenance, or time semantics.
- Transport JSON, schema validation, hashing, and process launch are common and uncharged. Any defaulting or interpretation beyond structural validation is charged.
- Manual review remains necessary for semantic irreducibility; machine counts are evidence, not a proof that two primitives are conceptually equal.

### 9.4 Runtime instrumentation instead of self-report alone

The runner snapshots code hashes and records:

- loaded modules/layers and their content hashes;
- registered rules/factors/rewrites/components/callbacks through instrumented registries;
- knowledge/module packages consumed;
- persistent migrations, generated artifacts, cache/index rebuilds;
- which code roots changed during extension experiments;
- subprocess command, environment, dependencies, wall time, peak RSS, and seed set.

Python AST/import inspection can flag test-ID branches and unregistered callbacks, but it is not treated as complete for dynamic languages. The final primitive/special-case ledger combines instrumentation with review.

### 9.5 Special-case ledger

Every post-freeze change is classified:

```json
{
  "change_id": "...",
  "class": "K_shared|K_extra|G_general|S_case_id|S_concept|S_numeric|S_adapter|S_execution",
  "applies_to": [],
  "rationale": "...",
  "code_or_data_hashes": [],
  "introduced_after_workload_freeze": true
}
```

- Equivalent encodings of a shared medical/mathematical commitment are `K_shared`, not rule-candidate penalties.
- Extra identification, independence, closure, prior, or interaction assumptions are `K_extra` even if encoded in a neural weight or factor.
- Generic architecture algorithms are `G_general`.
- A test ID, fixture UUID, narrow concept name, magic threshold/bonus, adapter inference, or scheduling workaround is an `S_*` patch.
- Hidden holdout aliases and an isomorphic second vocabulary test whether a supposedly general rule is actually a concept branch.

### 9.6 Blast-radius measurement

For each extension package, the runner:

1. hashes code, schemas, generated artifacts, persistent store, models, and caches;
2. installs the extension through `register_module`;
3. executes its positive/negative behavior probes;
4. reruns all old workloads;
5. repeats from a fresh store and from a historical store;
6. records the before/after vector from `EXPERIMENTS.md`.

File count is only supplementary. Core signature/semantics changes, knowledge-module edits, migrations, model retraining, historical reprocessing, invalidated generated artifacts, and old-test changes are the primary costs.

---

## 10. Minimal credible implementation plan

### Stage 0 — freeze the contract

Implement schemas, API, JSONL transport, run store, and 4–6 dummy candidates:

- `echo_ok`: returns structurally valid but semantically empty `ok`;
- `always_unsupported`: refuses everything;
- `last_write_wins`: intentionally collapses conflict;
- `future_leaker`: ignores `known_at`;
- `do_equals_condition`: maps intervention to conditioning;
- `root_duplicator`: counts derivation paths as evidence roots.

The harness is not accepted until the corresponding workloads reject these mutants for the expected reason. This directly tests that manifests and pretty envelopes cannot pass.

### Stage 1 — T panel, exact and metamorphic first

Implement T01–T50 fixtures and runner-side oracles in groups:

1. roles/scope/unknown: T08–T11, T20, T28–T30, T41–T44, T49–T50;
2. time/replay/version: T12–T13, T19, T23, T25, T32, T36, T40;
3. provenance/revision/idempotency: T06–T07, T24, T27, T31, T34, T45, T48;
4. observation/intervention/task: T01–T05, T14–T18, T26, T35, T37, T46–T47;
5. composition/extension: T21–T22, T33, T38–T39.

For every group, add an intentionally defective mutant and an anchor positive control before running real candidates.

### Stage 2 — exact reference causal models

Implement E02 and E03 by exhaustive enumeration. They are small, deterministic, and catch the most dangerous semantic substitution (`observe` for `do`, or new-unit sampling for same-unit counterfactual) before any ODE code is trusted.

### Stage 3 — dynamic references

Implement E01, E04, E05, E06, and E08 using a small runner-only numerical package:

- deterministic fixed/fine-step RK4 plus step-halving checks for golden paths;
- seeded noise generation with stored seed lists;
- exact small-state enumeration where possible;
- explicit nonconvergence/multiple/no-solution fixtures;
- output at common query times, never require candidate internal time steps.

Validate analytic limits such as `U=0`, zero noise, zero interaction, and contraction fixed points. Store golden results with simulator code/version/hash, but regenerate them in CI and compare to the checked-in digest.

### Stage 4 — E07 and extension instrumentation

Add fresh-session branch permutations, wiring brackets, module substitution, leave-one-companion-out runs, code/artifact hashes, and blast-radius records.

### Stage 5 — candidate execution

For each candidate:

1. validate manifest and isolate Track A;
2. run contract probes and the full T/E panel;
3. run Track B, leave-one-layer-out, and minimal-subset ablations;
4. run extension packages and hidden variants;
5. publish raw RPC, all assertions, semantic/honesty/fidelity vectors, primitive profile, patch ledger, and blast radius;
6. do not publish a weighted winner. Feed the independent columns into the final hard-gate and Pareto analysis.

---

## 11. Harness verification and anti-self-confirmation tests

The benchmark itself needs evidence.

### 11.1 Mutation requirements

Before accepting a workload panel, the following mutations must be killed:

| Mutant | Must be caught by |
|---|---|
| Replace `available_from <= known_at` with occurrence-time comparison | T12, T13, T25, T40 |
| Map all missing states to `absent` | T11, T43, T50 |
| Deduplicate by text rather than stable source ID | T06, T27, T30, T34 |
| Count each derivation path as an independent root | T06, T24, T27, T31, T34 |
| Make revisions overwrite old transaction state | T23, T25, T32, T36 |
| Treat request/order as performed action | T17, T37, T48 |
| Map `do(T)` to `observe(T)` | E02, E03 |
| Resample exogenous response in individual counterfactual | E03 |
| Default missing interaction to addition | T16, E06 |
| Depend on file/hash/registration order | T10, T25, E07 |
| Reject every loop | E08 contraction case |
| Accept every loop | T31 and E08 rootless/nonunique cases |

A workload whose relevant mutant survives is not yet a valid discriminator.

### 11.2 Reference simulator verification

- exact enumeration cross-checks E02/E03;
- RK4 outputs are checked under step halving and analytic zero-effect limits;
- reference outputs include parameter, code, solver, seed, and environment hashes;
- candidate and oracle implementations may use the same public equations but not the same executable code;
- an independent review checks signs, units, query cuts, and tolerances before freeze;
- tolerance changes after candidate results are visible require a new benchmark version and rerun of all candidates.

### 11.3 Result publication rules

- Raw RPC and assertion evidence precede summaries.
- A summary is regenerated only from immutable raw records.
- `manifest` claims, family-theory notes, and prototype behavior are separate fields.
- Every missing result is `NOT_RUN` with a reason; it is never silently omitted.
- A HARD failure remains visible even if all numerical metrics are excellent.
- `unsupported` remains visible both as honest boundary and failed coverage.
- Reference-model performance is explicitly labeled “within benchmark toy model,” never “clinically accurate.”

---

## 12. Minimal manifest: useful for reproducibility, never an oracle

```json
{
  "candidate_id": "typed-rewrite-prototype",
  "candidate_version": "0.1.0",
  "formal_signature": {"document": "FORMALISM.md", "sha256": "sha256:..."},
  "execution_semantics": {"document": "SEMANTICS.md", "sha256": "sha256:..."},
  "entrypoint": ["python", "-m", "candidate.rpc"],
  "required_runtime": {"python": ">=3.11", "dependencies_lock": "sha256:..."},
  "tracks": {
    "native": {"code_roots": ["native"], "layers": []},
    "companion": {"code_roots": ["native", "companions"], "layers": ["..."]}
  },
  "declared_capabilities": {
    "query.state_estimate": "supported|unsupported|partial",
    "query.interventional": "supported|unsupported|partial",
    "query.individual_counterfactual": "supported|unsupported|partial",
    "operation.retract": "supported|unsupported|partial",
    "operation.compose": "supported|unsupported|partial"
  },
  "declared_composition_laws": [],
  "failure_types": [],
  "primitive_profile_claim": {},
  "foreign_escape_hatches": [],
  "companion_layers": [],
  "semantic_adapters": [],
  "safety_monitors": [],
  "domain_knowledge_packages": [],
  "generated_artifacts": [],
  "caches": []
}
```

The runner validates the document and later emits `claim_consistency`. It never translates a `supported` string into a PASS.

---

## 13. One-command target and definition of “runnable”

The eventual package should support:

```powershell
python -m archbench run --candidate candidates/<id> --tracks native,companion --panel all --out results
python -m pytest archbench/tests
python -m archbench verify-run results/<run_id>
```

“Runnable” means all of the following, not merely importing successfully:

1. all schemas and 58 workload files validate;
2. candidate process is actually invoked and raw RPC is saved;
3. every workload has at least one executed behavior/reference/metamorphic assertion;
4. honesty is reported separately and universal refusal cannot pass HARD behavior;
5. reference simulators pass analytic/golden self-tests;
6. required mutants are killed;
7. native, companion, and ablation runs are distinguishable by code/layer hashes;
8. rerunning with the same inputs, versions, and seeds reproduces semantic results;
9. summaries verify against immutable raw result hashes;
10. no result claims clinical validity or global architectural optimality.

## 14. Recommended implementation decision

Adopt this protocol before implementing candidate logic. The highest-value first slice is not a broad feature matrix: it is the schema/runner plus T12, T24, T31, T38, E02, E03, E07, and E08 together with their deliberately broken mutants. That slice exercises future isolation, correction semantics, epistemic cycles, interface safety, conditioning-vs-intervention, same-unit counterfactuals, composition-order robustness, and legitimate-vs-illegal feedback. Once the harness demonstrably rejects wrong implementations for the right reasons, filling the remaining JSON workloads is mechanical and candidate prototypes can be compared without giving the future favorite a privileged API.
