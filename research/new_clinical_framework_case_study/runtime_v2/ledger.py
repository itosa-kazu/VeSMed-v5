"""Content-addressed event-ledger proofs for cold state restoration.

``SharedPatientStateV1`` intentionally carries an aggregate ledger digest and
the processed identifiers, but not every event content hash.  This sidecar is
therefore the fail-closed proof needed to distinguish an exact replay from an
``event_id`` collision after canonical state bytes have crossed a process
boundary.  It is bound to both the canonical state hash and ledger digest.
"""

from __future__ import annotations

import copy
from typing import Any, Mapping

from .schema import SharedPatientState, digest


LEDGER_PROOF_SCHEMA_VERSION = "new-clinical-runtime.event-ledger-proof.v2.1"


def ledger_entries_digest(entries: Mapping[str, str]) -> str:
    """Digest the complete sorted ``event_id -> event_digest`` map."""

    return digest(
        [
            {"event_id": str(event_id), "event_digest": str(event_digest)}
            for event_id, event_digest in sorted(entries.items())
        ]
    )


def build_event_ledger_proof(
    state: SharedPatientState,
    entries: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Export a state-bound proof from a warm state or supplied ledger map."""

    if entries is None:
        if state._event_ledger_proof is not None:
            return copy.deepcopy(state._event_ledger_proof)
        if state._internal_payload is None:
            raise ValueError("cold state lacks event ledger entries; external proof is required")
        entries = state._internal_payload.get("event_ledger", {})
    normalized = {str(key): str(value) for key, value in entries.items() if value is not None}
    processed = list(state.payload["event_lineage"]["processed_event_ids"])
    if set(normalized) != set(processed):
        raise ValueError("ledger proof entries do not match processed_event_ids")
    proof_digest = ledger_entries_digest(normalized)
    if proof_digest != state.payload["event_lineage"]["event_ledger_digest"]:
        raise ValueError("ledger proof entries do not match event_ledger_digest")
    return {
        "schema_version": LEDGER_PROOF_SCHEMA_VERSION,
        "state_hash": state.state_hash,
        "event_ledger_digest": proof_digest,
        "entries": [
            {"event_id": event_id, "event_digest": normalized[event_id]}
            for event_id in sorted(normalized)
        ],
    }


def attach_event_ledger_proof(
    state: SharedPatientState,
    proof: Mapping[str, Any],
) -> SharedPatientState:
    """Validate and attach a content-addressed proof without changing bytes."""

    row = copy.deepcopy(dict(proof))
    if row.get("schema_version") != LEDGER_PROOF_SCHEMA_VERSION:
        raise ValueError("unsupported event ledger proof schema")
    if row.get("state_hash") != state.state_hash:
        raise ValueError("event ledger proof is bound to another state hash")
    entries_list = row.get("entries")
    if not isinstance(entries_list, list):
        raise ValueError("event ledger proof entries must be a list")
    entries: dict[str, str] = {}
    for item in entries_list:
        if not isinstance(item, Mapping) or not item.get("event_id") or not item.get("event_digest"):
            raise ValueError("malformed event ledger proof entry")
        event_id = str(item["event_id"])
        if event_id in entries:
            raise ValueError(f"duplicate event id in ledger proof: {event_id}")
        entries[event_id] = str(item["event_digest"])
    if set(entries) != set(state.payload["event_lineage"]["processed_event_ids"]):
        raise ValueError("event ledger proof ids do not match canonical state")
    proof_digest = ledger_entries_digest(entries)
    if row.get("event_ledger_digest") != proof_digest:
        raise ValueError("event ledger proof self-digest mismatch")
    if proof_digest != state.payload["event_lineage"]["event_ledger_digest"]:
        raise ValueError("event ledger proof does not match canonical state")
    normalized = build_event_ledger_proof(state, entries)
    return SharedPatientState(
        state.to_dict(),
        copy.deepcopy(state._internal_payload),
        normalized,
    )


__all__ = [
    "LEDGER_PROOF_SCHEMA_VERSION",
    "attach_event_ledger_proof",
    "build_event_ledger_proof",
    "ledger_entries_digest",
]
