# Content-addressed event ledger and fresh-process replay

## Why this sidecar exists

`SharedPatientStateV1` contains:

```text
event_lineage.event_ledger_digest
event_lineage.processed_event_ids
```

It intentionally does **not** contain every event payload or every
`event_id -> event_digest` entry.  After canonical state bytes are loaded in a
new process, the state alone therefore cannot distinguish:

```text
same event_id + same canonical bytes   -> exact duplicate
same event_id + changed canonical bytes -> corruption/collision
```

Runtime v2.1 supplies a state-bound digest proof in `runtime_v2/ledger.py`.
`event_ledger_replay.py` is the independent holdout-harness layer that also
stores the canonical event blobs, cut sequence and expected canonical state
blobs needed for deterministic cold replay.

Neither layer changes the frozen architecture wire schema.

## Trust and binding chain

```text
canonical event payload
  -> SHA-256 event_digest
  -> event_id -> event_digest complete map
  -> event_ledger_digest
  -> SharedPatientState.event_lineage.event_ledger_digest
  -> architecture state_hash

canonical state payload (including state_hash)
  -> state_blob_sha256
  -> cut record
  -> replay bundle digest
```

The bundle contains no unverified raw shortcut.  Every event blob and state
blob is rehashed on load.  Every cut re-derives the set of events eligible at
that cut, the ledger digest, parent state binding and final binding.

## Integration pattern

Run from `research/new_clinical_framework_case_study`:

```python
from runtime_v2 import RuntimeV2
from holdout.tools.event_ledger_replay import ReplayBundleRecorder

runtime = RuntimeV2.from_json("holdout/generic_model/model_pack.json")
session = ReplayBundleRecorder(runtime)

# The store may already contain later events.  Only available_at <= cut is
# delivered to the runtime.
state_0 = session.initialize(all_public_events, cut=0)

# Events registered at an earlier cut are automatically released when their
# availability boundary is crossed.  Exact duplicates are preserved as
# delivery attempts so exact-once behavior is actually exercised.
state_1 = session.update(newly_stored_events, advance_to=1)
state_2 = session.update([], advance_to=2)

session.save("holdout/evidence/event_ledger_replay_bundle.json")
```

The harness must call the recorder rather than calling `RuntimeV2.update`
directly.  The recorder rejects changed bytes for an existing id before the
runtime is entered, including an event that is not yet available.

## Fresh-process verification

```powershell
python holdout/tools/event_ledger_replay.py verify `
  --bundle holdout/evidence/event_ledger_replay_bundle.json `
  --model holdout/generic_model/model_pack.json `
  --report holdout/evidence/fresh_process_replay.json
```

The verifier performs one complete cold-history replay with two simultaneous
properties:

1. **recursive cold edge**: for each update, create a new runtime, deserialize
   only the canonical parent bytes, attach the content-addressed proof, apply
   that cut's exact delta, and require byte-identical output;
2. **cold history prefixes**: the run starts from no state and requires every
   intermediate prefix output, through the final full available ledger, to be
   byte-identical.  It does not redundantly rerun the same prefixes O(n^2).

The report also proves that no `available_at > cut` event appears in the
processed set and that event delivery order is fixed by:

```text
(numeric available_at, event_id)
```

## Fail-closed rules

- same id and same canonical bytes at the same cut: state bytes are unchanged;
- same id and changed canonical bytes: `EventIdConflict` / runtime collision;
- cold duplicate without a ledger proof: rejected, even when it appears exact;
- proof bound to another state or aggregate ledger digest: rejected;
- tampered event blob, state blob, cut record or final binding: rejected;
- non-finite/non-numeric `available_at` or cut: rejected;
- future event at an earlier cut: stored but not delivered or processed;
- model digest different from the sealed bundle: replay rejected.

## Tests

```powershell
python -m unittest -v holdout.tools.test_event_ledger_replay
```

The test suite covers:

1. same-id/same-bytes idempotence;
2. same-id/changed-bytes failure;
3. proof-required cold duplicate validation;
4. deterministic event ordering;
5. available-time exclusion and later release;
6. blob tamper rejection;
7. an actual subprocess replay of every recursive edge and cold prefix.

## Boundary

This proves **ledger integrity and deterministic replay**, not correctness of
clinical extraction, factor mapping, diagnosis, forecasting or treatment
effects.  Those remain separate perfect-landing gates.
