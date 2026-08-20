# Runtime v2.1 stable interface

This directory is a case-blind, non-V5 structural runtime.  See
`DESIGN.md` for semantics and limitations.

## Direct API

```python
from runtime_v2 import (
    RuntimeV2, SharedPatientState, build_event_ledger_proof,
    load_events_json, save_state_json,
)

runtime = RuntimeV2.from_json("path/to/model.json")
events = load_events_json("path/to/events.json")

state = runtime.initialize(events, cut=0)
state = runtime.update(state, events, advance_to=1)

# Canonical SharedPatientStateV1 bytes do not contain per-event hashes.  Keep
# this state-bound proof beside the state for fail-closed cold replay.
proof = build_event_ledger_proof(state)
cold = SharedPatientState.from_bytes(state.to_bytes())
state = runtime.update(cold, new_events, advance_to=2, event_ledger_proof=proof)

diagnosis = runtime.diagnose(state)
natural = runtime.forecast(state, horizon=2)
support_score = runtime.score_predictive_support(natural, realized_next_cut)
plan = runtime.plan(
    state,
    [
        {"policy_id": "NO_NEW_ACTION", "start_actions": []},
        {
            "policy_id": "START_REGISTERED_ACTION",
            "start_actions": [{"action_id": "ACTION_ID", "dose": 1.0}],
        },
    ],
    horizon=2,
)

wire_bytes = state.to_bytes()
wire_hash = state.state_hash
save_state_json(state, "state.json")
```

`diagnose`, `forecast`, and `plan` are pure and return
`consumed_state_hash`.  `update` is incremental and event-idempotent. Exact
duplicate delivery at the same cut preserves byte-identical canonical state.
Cold updates with prior events require the content-addressed ledger proof; an
ID-only cold state fails closed rather than guessing whether bytes match. A state
bound to another model digest is rejected until passed through
`migrate_v2_state` or `import_legacy_v1_state`.
Execution switches such as topology and mode guards are included in that digest.

Public events use `new-clinical-runtime.event.v2.1`: every event requires a
source result id, an explicit occurrence interval, record time and availability
time; observations additionally require sample interval and result time.

## JSON contracts

- `schemas/model_v2.schema.json`
- `schemas/event_v2.schema.json`
- `schemas/state_v2.schema.json` (alias of `../../architecture_final_v1.schema.json`)
- `schemas/migration_v2.schema.json`

The Python validator additionally checks cross-object references and runtime
invariants that JSON Schema alone cannot express.

## Neutral demo

```powershell
cd C:\Users\wangw\Documents\vesmed\research\new_clinical_framework_case_study
python -m runtime_v2.demo
```

The demo deliberately uses abstract `PROCESS_A/B/C`.  It is not a synthetic
clinical case and provides no medical evidence.

## Tests

```powershell
python -m unittest discover -s runtime_v2/tests -v
```

These tests cover factorial co-activation, negative evidence, local modes,
executable hysteresis guards, coordinates, complete action lifecycle/policy
operations, identifiability-aware planner exclusion, OOD residuals, topology
ablations, content-addressed cold replay, behavioral collision witnesses,
conflicting-measurement residuals, record-only disposition, scoreable predictive
support, local stratum refinement with full-query non-regression, serialization,
exact-once event delivery, and both migration paths.
