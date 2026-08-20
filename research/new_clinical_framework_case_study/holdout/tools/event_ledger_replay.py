"""Case-blind, content-addressed event-ledger replay bundle.

The frozen SharedPatientStateV1 wire intentionally carries only an aggregate
event-ledger digest and the processed identifiers.  Runtime v2.1 therefore
exports a small ``event-ledger proof`` with the exact ``event_id -> digest``
map.  This module adds the holdout-harness layer that the wire cannot carry:

* canonical event payload blobs addressed by SHA-256;
* deterministic cut/delta records;
* exact duplicate/conflict checks before runtime entry;
* state-bound proof construction after a cold deserialization; and
* a fresh-process verifier that replays every prefix and compares canonical
  state bytes, not merely clinical summaries.

This file is deliberately case-blind and does not import, enumerate or inspect
any case directory.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


# Permit both ``python -m holdout.tools.event_ledger_replay`` and direct script
# execution from an arbitrary working directory.
STUDY_ROOT = Path(__file__).resolve().parents[2]
if str(STUDY_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDY_ROOT))

from runtime_v2 import (  # noqa: E402
    ARCHITECTURE_VERSION,
    RUNTIME_VERSION,
    PublicEvent,
    RuntimeV2,
    SharedPatientState,
    build_event_ledger_proof,
    canonical_json_bytes,
    digest,
)
from runtime_v2.ledger import ledger_entries_digest  # noqa: E402
from runtime_v2.architecture_wire import model_time_from_as_of  # noqa: E402


BUNDLE_SCHEMA_VERSION = "ncf.holdout.event-ledger-replay-bundle.v1"
REPORT_SCHEMA_VERSION = "ncf.holdout.fresh-process-replay-report.v1"


class EventIdConflict(ValueError):
    """The same event id was presented with different canonical bytes."""


class ReplayBundleError(ValueError):
    """A replay bundle or its binding is invalid."""


def _finite_cut(value: int | float, *, field: str = "cut") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ReplayBundleError(f"{field} must be a numeric finite value")
    number = float(value)
    if not math.isfinite(number):
        raise ReplayBundleError(f"{field} must be a numeric finite value")
    return number


def _event_sort_key(event: PublicEvent) -> tuple[float, str]:
    available_at = event.payload.get("available_at")
    return (_finite_cut(available_at, field="available_at"), event.event_id)


def _state_bytes(state: SharedPatientState) -> bytes:
    return canonical_json_bytes(state.to_dict())


def _bundle_digest(bundle: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(bundle))
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict):
        raise ReplayBundleError("bundle lacks integrity object")
    integrity.pop("bundle_digest", None)
    return digest(payload)


def _resolve_event(bundle: Mapping[str, Any], event_id: str) -> PublicEvent:
    index = bundle["event_index"][event_id]
    payload = bundle["event_blobs"][index["event_digest"]]
    return PublicEvent.from_dict(payload)


def _proof_entries_for_state(
    bundle: Mapping[str, Any], state: SharedPatientState
) -> dict[str, str]:
    result: dict[str, str] = {}
    for event_id in state.to_dict()["event_lineage"]["processed_event_ids"]:
        try:
            result[event_id] = bundle["event_index"][event_id]["event_digest"]
        except KeyError as exc:
            raise ReplayBundleError(
                f"state references event absent from replay bundle: {event_id}"
            ) from exc
    return result


class ReplayBundleRecorder:
    """Record an exact, deterministic RuntimeV2 cut sequence.

    Events may be registered before they are available.  They remain in the
    content-addressed store but are never passed to the runtime before
    ``available_at <= cut``.  Once their availability boundary is crossed,
    they are delivered automatically even when the caller passes no new event
    on that update.
    """

    def __init__(self, runtime: RuntimeV2) -> None:
        self.runtime = runtime
        self.state: SharedPatientState | None = None
        self._registered: set[str] = set()
        self.bundle: dict[str, Any] = {
            "schema_version": BUNDLE_SCHEMA_VERSION,
            "canonicalization": "RFC8785-JCS",
            "hash_algorithm": "SHA-256",
            "model_binding": {
                "model_id": str(runtime.spec["model_id"]),
                "model_digest": runtime.model_digest,
                "runtime_version": RUNTIME_VERSION,
                "architecture_version": ARCHITECTURE_VERSION,
            },
            "event_blobs": {},
            "event_index": {},
            "state_blobs": {},
            "cuts": [],
            "final_binding": None,
            "integrity": {
                "canonicalization": "RFC8785-JCS",
                "hash_algorithm": "SHA-256",
                "bundle_digest": "0" * 64,
            },
        }

    def _register(
        self, values: Iterable[PublicEvent | Mapping[str, Any]]
    ) -> list[PublicEvent]:
        submitted = [
            item if isinstance(item, PublicEvent) else PublicEvent.from_dict(item)
            for item in values
        ]
        submitted.sort(key=_event_sort_key)
        for event in submitted:
            event_id = event.event_id
            event_digest = event.event_digest
            _event_sort_key(event)  # validates numeric finite availability
            existing = self.bundle["event_index"].get(event_id)
            if existing is not None and existing["event_digest"] != event_digest:
                raise EventIdConflict(
                    f"event_id collision with changed canonical bytes: {event_id}"
                )
            blob = self.bundle["event_blobs"].get(event_digest)
            if blob is not None and canonical_json_bytes(blob) != canonical_json_bytes(
                event.to_dict()
            ):
                raise ReplayBundleError(
                    f"sha256 payload collision for event digest: {event_digest}"
                )
            self.bundle["event_blobs"][event_digest] = event.to_dict()
            self.bundle["event_index"][event_id] = {
                "event_digest": event_digest,
                "available_at": float(event.payload["available_at"]),
            }
            self._registered.add(event_id)
        return submitted

    def _processed_ids(self) -> set[str]:
        if self.state is None:
            return set()
        return set(self.state.to_dict()["event_lineage"]["processed_event_ids"])

    def _prepare_runtime_input(
        self, submitted: Sequence[PublicEvent], cut: float
    ) -> tuple[list[PublicEvent], list[str], list[str]]:
        processed = self._processed_ids()
        newly_eligible_ids = {
            event_id
            for event_id in self._registered
            if event_id not in processed
            and float(self.bundle["event_index"][event_id]["available_at"]) <= cut
        }
        counts = Counter(event.event_id for event in submitted)
        runtime_ids: list[str] = list(newly_eligible_ids)
        # Preserve repeated delivery attempts so the exact-once path is really
        # exercised.  A newly eligible id is delivered once plus every extra
        # copy submitted in this call; an already processed id is delivered as
        # many times as it was explicitly resubmitted.
        for event_id, count in counts.items():
            if float(self.bundle["event_index"][event_id]["available_at"]) > cut:
                continue
            if event_id in newly_eligible_ids:
                runtime_ids.extend([event_id] * max(0, count - 1))
            elif event_id in processed:
                runtime_ids.extend([event_id] * count)
        runtime_events = [_resolve_event(self.bundle, event_id) for event_id in runtime_ids]
        runtime_events.sort(key=_event_sort_key)
        future_ids = sorted(
            event_id
            for event_id in self._registered
            if event_id not in processed
            and float(self.bundle["event_index"][event_id]["available_at"]) > cut
        )
        return runtime_events, sorted(newly_eligible_ids), future_ids

    def initialize(
        self,
        events: Iterable[PublicEvent | Mapping[str, Any]],
        *,
        cut: int | float,
    ) -> SharedPatientState:
        if self.state is not None:
            raise ReplayBundleError("recorder is already initialized")
        cut_value = _finite_cut(cut)
        submitted = self._register(events)
        runtime_events, expected_new, future_ids = self._prepare_runtime_input(
            submitted, cut_value
        )
        state = self.runtime.initialize(runtime_events, cut=cut_value)
        self._record_cut(
            operation="initialize",
            cut=cut_value,
            submitted=submitted,
            runtime_events=runtime_events,
            expected_new=expected_new,
            future_ids=future_ids,
            parent=None,
            output=state,
        )
        self.state = state
        return state

    def update(
        self,
        events: Iterable[PublicEvent | Mapping[str, Any]],
        *,
        advance_to: int | float,
    ) -> SharedPatientState:
        if self.state is None:
            raise ReplayBundleError("recorder must be initialized before update")
        cut_value = _finite_cut(advance_to, field="advance_to")
        try:
            current_time = _finite_cut(
                model_time_from_as_of(self.state.to_dict()["as_of"]),
                field="current_state_time",
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ReplayBundleError(f"invalid typed state cut: {exc}") from exc
        if cut_value < current_time:
            raise ReplayBundleError("cut cannot move backwards")
        submitted = self._register(events)
        runtime_events, expected_new, future_ids = self._prepare_runtime_input(
            submitted, cut_value
        )
        parent = self.state
        proof = build_event_ledger_proof(parent)
        output = self.runtime.update(
            parent,
            runtime_events,
            advance_to=cut_value,
            event_ledger_proof=proof,
        )
        self._record_cut(
            operation="update",
            cut=cut_value,
            submitted=submitted,
            runtime_events=runtime_events,
            expected_new=expected_new,
            future_ids=future_ids,
            parent=parent,
            output=output,
        )
        self.state = output
        return output

    def _record_cut(
        self,
        *,
        operation: str,
        cut: float,
        submitted: Sequence[PublicEvent],
        runtime_events: Sequence[PublicEvent],
        expected_new: Sequence[str],
        future_ids: Sequence[str],
        parent: SharedPatientState | None,
        output: SharedPatientState,
    ) -> None:
        parent_processed = (
            set(parent.to_dict()["event_lineage"]["processed_event_ids"])
            if parent is not None
            else set()
        )
        expected_processed = parent_processed | set(expected_new)
        lineage = output.to_dict()["event_lineage"]
        actual_processed = set(lineage["processed_event_ids"])
        if actual_processed != expected_processed:
            raise ReplayBundleError(
                "runtime processed-event set differs from availability-bounded ledger"
            )
        entries = {
            event_id: self.bundle["event_index"][event_id]["event_digest"]
            for event_id in actual_processed
        }
        expected_ledger_digest = ledger_entries_digest(entries)
        if lineage["event_ledger_digest"] != expected_ledger_digest:
            raise ReplayBundleError("runtime event_ledger_digest is not content-addressed")

        output_bytes = _state_bytes(output)
        output_blob_digest = digest(output_bytes)
        self.bundle["state_blobs"][output_blob_digest] = output.to_dict()
        parent_bytes_digest = digest(_state_bytes(parent)) if parent is not None else None
        is_noop = parent is not None and output_bytes == _state_bytes(parent)
        if not is_noop and sorted(lineage["new_event_ids"]) != sorted(expected_new):
            raise ReplayBundleError("runtime new_event_ids differ from ledger delta")
        cut_record = {
            "sequence": len(self.bundle["cuts"]),
            "operation": operation,
            "cut": cut,
            "submitted_event_ids": [event.event_id for event in submitted],
            "runtime_input_event_ids": [event.event_id for event in runtime_events],
            "expected_new_event_ids": sorted(expected_new),
            "future_registered_event_ids": list(future_ids),
            "parent_state_blob_sha256": parent_bytes_digest,
            "parent_state_hash": parent.state_hash if parent is not None else None,
            "output_state_blob_sha256": output_blob_digest,
            "output_state_hash": output.state_hash,
            "output_event_ledger_digest": expected_ledger_digest,
            "processed_event_ids": sorted(actual_processed),
            "runtime_noop": is_noop,
        }
        self.bundle["cuts"].append(cut_record)
        self.bundle["final_binding"] = {
            "state_blob_sha256": output_blob_digest,
            "state_hash": output.state_hash,
            "event_ledger_digest": expected_ledger_digest,
            "processed_event_ids": sorted(actual_processed),
        }

    def sealed_bundle(self) -> dict[str, Any]:
        if self.state is None:
            raise ReplayBundleError("cannot seal an empty replay bundle")
        result = copy.deepcopy(self.bundle)
        result["integrity"]["bundle_digest"] = _bundle_digest(result)
        validate_bundle(result)
        return result

    def save(self, path: str | Path) -> dict[str, Any]:
        result = self.sealed_bundle()
        Path(path).write_bytes(canonical_json_bytes(result) + b"\n")
        return result


def validate_bundle(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate all content addresses, cut boundaries and state bindings."""

    bundle = copy.deepcopy(dict(value))
    if bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION:
        raise ReplayBundleError("unsupported replay bundle schema")
    if bundle.get("canonicalization") != "RFC8785-JCS":
        raise ReplayBundleError("unsupported bundle canonicalization")
    if bundle.get("hash_algorithm") != "SHA-256":
        raise ReplayBundleError("unsupported bundle hash algorithm")
    integrity = bundle.get("integrity")
    if not isinstance(integrity, dict):
        raise ReplayBundleError("bundle lacks integrity object")
    if integrity.get("bundle_digest") != _bundle_digest(bundle):
        raise ReplayBundleError("replay bundle digest mismatch")

    model_binding = bundle.get("model_binding")
    if not isinstance(model_binding, dict):
        raise ReplayBundleError("bundle lacks model binding")
    if model_binding.get("architecture_version") != ARCHITECTURE_VERSION:
        raise ReplayBundleError("bundle architecture version mismatch")
    if model_binding.get("runtime_version") != RUNTIME_VERSION:
        raise ReplayBundleError("bundle runtime version mismatch")

    event_blobs = bundle.get("event_blobs")
    event_index = bundle.get("event_index")
    state_blobs = bundle.get("state_blobs")
    cuts = bundle.get("cuts")
    if not isinstance(event_blobs, dict) or not isinstance(event_index, dict):
        raise ReplayBundleError("bundle event stores must be objects")
    if not isinstance(state_blobs, dict) or not isinstance(cuts, list) or not cuts:
        raise ReplayBundleError("bundle needs state blobs and at least one cut")

    for blob_digest, payload in event_blobs.items():
        event = PublicEvent.from_dict(payload)
        if event.event_digest != blob_digest:
            raise ReplayBundleError(f"event blob digest mismatch: {event.event_id}")
        _event_sort_key(event)
    for event_id, index in event_index.items():
        if not isinstance(index, dict) or index.get("event_digest") not in event_blobs:
            raise ReplayBundleError(f"event index points to missing blob: {event_id}")
        event = _resolve_event(bundle, event_id)
        if event.event_id != event_id:
            raise ReplayBundleError(f"event index id mismatch: {event_id}")
        if float(index.get("available_at")) != float(event.payload["available_at"]):
            raise ReplayBundleError(f"event index availability mismatch: {event_id}")
    if set(event_blobs) != {
        row["event_digest"] for row in event_index.values()
    }:
        raise ReplayBundleError("event blob store contains an unindexed or multiply-addressed blob")

    for state_blob_digest, payload in state_blobs.items():
        state = SharedPatientState.from_dict(payload)
        if digest(_state_bytes(state)) != state_blob_digest:
            raise ReplayBundleError(f"state blob digest mismatch: {state_blob_digest}")

    registered: set[str] = set()
    processed: set[str] = set()
    previous_state_blob: str | None = None
    previous_state_hash: str | None = None
    previous_cut: float | None = None
    for sequence, record in enumerate(cuts):
        if not isinstance(record, dict) or record.get("sequence") != sequence:
            raise ReplayBundleError("cut sequence is not contiguous")
        operation = record.get("operation")
        if (sequence == 0 and operation != "initialize") or (
            sequence > 0 and operation != "update"
        ):
            raise ReplayBundleError("invalid cut operation sequence")
        cut = _finite_cut(record.get("cut"), field="cut")
        if previous_cut is not None and cut < previous_cut:
            raise ReplayBundleError("cut sequence moves backwards")
        submitted_ids = record.get("submitted_event_ids")
        if not isinstance(submitted_ids, list):
            raise ReplayBundleError("submitted_event_ids must be a list")
        submitted_events = [_resolve_event(bundle, event_id) for event_id in submitted_ids]
        if submitted_events != sorted(submitted_events, key=_event_sort_key):
            raise ReplayBundleError("submitted events are not in deterministic order")
        registered.update(submitted_ids)
        new_ids = sorted(
            event_id
            for event_id in registered
            if event_id not in processed
            and float(event_index[event_id]["available_at"]) <= cut
        )
        counts = Counter(submitted_ids)
        runtime_ids: list[str] = list(new_ids)
        for event_id, count in counts.items():
            if float(event_index[event_id]["available_at"]) > cut:
                continue
            if event_id in new_ids:
                runtime_ids.extend([event_id] * max(0, count - 1))
            elif event_id in processed:
                runtime_ids.extend([event_id] * count)
        runtime_ids.sort(key=lambda event_id: _event_sort_key(_resolve_event(bundle, event_id)))
        if runtime_ids != record.get("runtime_input_event_ids"):
            raise ReplayBundleError("runtime input delta is not availability deterministic")
        if new_ids != record.get("expected_new_event_ids"):
            raise ReplayBundleError("expected new-event delta mismatch")
        future_ids = sorted(
            event_id
            for event_id in registered
            if event_id not in processed
            and float(event_index[event_id]["available_at"]) > cut
        )
        if future_ids != record.get("future_registered_event_ids"):
            raise ReplayBundleError("future-event exclusion record mismatch")

        processed.update(new_ids)
        if sorted(processed) != record.get("processed_event_ids"):
            raise ReplayBundleError("processed-event lineage mismatch")
        entries = {event_id: event_index[event_id]["event_digest"] for event_id in processed}
        expected_ledger_digest = ledger_entries_digest(entries)
        if record.get("output_event_ledger_digest") != expected_ledger_digest:
            raise ReplayBundleError("cut ledger digest mismatch")

        output_blob = record.get("output_state_blob_sha256")
        if output_blob not in state_blobs:
            raise ReplayBundleError("cut points to missing output state blob")
        output_state = SharedPatientState.from_dict(state_blobs[output_blob])
        if (
            output_state.to_dict()["model_lineage"]["model_digest"]
            != model_binding.get("model_digest")
        ):
            raise ReplayBundleError("output state model digest differs from bundle binding")
        output_lineage = output_state.to_dict()["event_lineage"]
        if set(output_lineage["processed_event_ids"]) != processed:
            raise ReplayBundleError("output state processed ids differ from bundle")
        if output_lineage["event_ledger_digest"] != expected_ledger_digest:
            raise ReplayBundleError("output state is not bound to event ledger")
        if record.get("output_state_hash") != output_state.state_hash:
            raise ReplayBundleError("output architecture state hash mismatch")
        if record.get("parent_state_blob_sha256") != previous_state_blob:
            raise ReplayBundleError("parent state blob chain mismatch")
        if record.get("parent_state_hash") != previous_state_hash:
            raise ReplayBundleError("parent state hash chain mismatch")
        if bool(record.get("runtime_noop")) != bool(
            previous_state_blob is not None and output_blob == previous_state_blob
        ):
            raise ReplayBundleError("runtime_noop flag differs from canonical state bytes")
        if not record.get("runtime_noop") and output_lineage["parent_state_hash"] != previous_state_hash:
            raise ReplayBundleError("output wire parent hash differs from replay chain")

        previous_state_blob = output_blob
        previous_state_hash = output_state.state_hash
        previous_cut = cut

    final = bundle.get("final_binding")
    if not isinstance(final, dict):
        raise ReplayBundleError("bundle lacks final binding")
    last = cuts[-1]
    expected_final = {
        "state_blob_sha256": last["output_state_blob_sha256"],
        "state_hash": last["output_state_hash"],
        "event_ledger_digest": last["output_event_ledger_digest"],
        "processed_event_ids": last["processed_event_ids"],
    }
    if final != expected_final:
        raise ReplayBundleError("final binding differs from final cut")
    return bundle


def load_bundle(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ReplayBundleError("replay bundle must contain an object")
    return validate_bundle(value)


def _replay_prefix(
    bundle: Mapping[str, Any], model_path: str | Path, last_sequence: int
) -> list[dict[str, Any]]:
    current: SharedPatientState | None = None
    results: list[dict[str, Any]] = []
    for record in bundle["cuts"][: last_sequence + 1]:
        # New runtime instance at every recursive edge.  For updates, the only
        # state input is the canonical parent bytes plus a verified sidecar
        # proof; no warm cache crosses the boundary.
        runtime = RuntimeV2.from_json(model_path)
        events = [
            _resolve_event(bundle, event_id)
            for event_id in record["runtime_input_event_ids"]
        ]
        if current is None:
            actual = runtime.initialize(events, cut=record["cut"])
        else:
            cold_parent = SharedPatientState.from_bytes(_state_bytes(current))
            proof_entries = _proof_entries_for_state(bundle, cold_parent)
            proof = build_event_ledger_proof(cold_parent, proof_entries)
            actual = runtime.update(
                cold_parent,
                events,
                advance_to=record["cut"],
                event_ledger_proof=proof,
            )
        expected_payload = bundle["state_blobs"][record["output_state_blob_sha256"]]
        expected = SharedPatientState.from_dict(expected_payload)
        actual_bytes = _state_bytes(actual)
        expected_bytes = _state_bytes(expected)
        if actual_bytes != expected_bytes:
            raise ReplayBundleError(
                f"fresh replay diverged at cut sequence {record['sequence']}: "
                f"expected {digest(expected_bytes)}, got {digest(actual_bytes)}"
            )
        results.append(
            {
                "sequence": record["sequence"],
                "cut": record["cut"],
                "canonical_state_bytes_sha256": digest(actual_bytes),
                "state_hash": actual.state_hash,
                "event_ledger_digest": actual.to_dict()["event_lineage"][
                    "event_ledger_digest"
                ],
                "processed_event_ids": actual.to_dict()["event_lineage"][
                    "processed_event_ids"
                ],
            }
        )
        current = actual
    return results


def verify_fresh_process_replay(
    bundle: Mapping[str, Any], model_path: str | Path
) -> dict[str, Any]:
    """Verify recursive cold restoration and every cold history prefix."""

    checked = validate_bundle(bundle)
    runtime = RuntimeV2.from_json(model_path)
    binding = checked["model_binding"]
    if runtime.model_digest != binding["model_digest"]:
        raise ReplayBundleError("model digest differs from replay bundle binding")
    if str(runtime.spec["model_id"]) != binding["model_id"]:
        raise ReplayBundleError("model id differs from replay bundle binding")

    recursive = _replay_prefix(checked, model_path, len(checked["cuts"]) - 1)
    # The replay above starts from no state, reconstructs every edge from cold
    # parent bytes, and compares every intermediate state.  Its intermediate
    # outputs are therefore the verified cold-history prefixes; re-running the
    # same O(n^2) prefixes would add cost but no independent state surface.
    prefix_hashes = [
        {
            "last_sequence": row["sequence"],
            "step_count": row["sequence"] + 1,
            "final_canonical_state_bytes_sha256": row[
                "canonical_state_bytes_sha256"
            ],
            "final_state_hash": row["state_hash"],
        }
        for row in recursive
    ]
    future_exclusion = [
        {
            "sequence": record["sequence"],
            "future_event_ids": record["future_registered_event_ids"],
            "none_processed_early": not bool(
                set(record["future_registered_event_ids"])
                & set(record["processed_event_ids"])
            ),
        }
        for record in checked["cuts"]
    ]
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "status": "PASS",
        "bundle_digest": checked["integrity"]["bundle_digest"],
        "model_digest": runtime.model_digest,
        "recursive_fresh_process_byte_exact": True,
        "cold_prefix_replay_byte_exact": True,
        "cold_full_history_replay_byte_exact": True,
        "deterministic_event_order_validated": True,
        "available_time_boundary_validated": all(
            row["none_processed_early"] for row in future_exclusion
        ),
        "recursive_steps": recursive,
        "cold_prefixes": prefix_hashes,
        "future_exclusion_by_cut": future_exclusion,
        "final_binding": copy.deepcopy(checked["final_binding"]),
    }
    report["report_digest"] = digest(report)
    return report


def _write_json(path: str | Path, value: Mapping[str, Any]) -> None:
    Path(path).write_bytes(canonical_json_bytes(value) + b"\n")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify = subparsers.add_parser("verify", help="fresh-process replay a sealed bundle")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--model", required=True)
    verify.add_argument("--report")
    args = parser.parse_args(argv)
    try:
        bundle = load_bundle(args.bundle)
        report = verify_fresh_process_replay(bundle, args.model)
        if args.report:
            _write_json(args.report, report)
        sys.stdout.buffer.write(canonical_json_bytes(report) + b"\n")
        return 0
    except Exception as exc:  # fail-closed CLI for the holdout harness
        error = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "status": "FAIL",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        if getattr(args, "report", None):
            _write_json(args.report, error)
        sys.stderr.buffer.write(canonical_json_bytes(error) + b"\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BUNDLE_SCHEMA_VERSION",
    "REPORT_SCHEMA_VERSION",
    "EventIdConflict",
    "ReplayBundleError",
    "ReplayBundleRecorder",
    "load_bundle",
    "validate_bundle",
    "verify_fresh_process_replay",
]
