#!/usr/bin/env python3
"""Compile source-supported availability evidence to conservative replay cuts.

Intervals are released at their supported upper bound, never their lower bound.
Unknown or partial-order-only availability without a supported latest bound is
withheld.  The compiler never derives clinical availability from publication
order and never splits a reported batch into artificial micro-cuts.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Mapping, NoReturn, Sequence


SCHEMA_VERSION = "ncf.primary-availability-ledger.v1"
OUTPUT_VERSION = "ncf.compiled-guaranteed-availability.v1"
KINDS = {"EXACT", "INTERVAL", "REPORTED_BATCH", "PARTIAL_ORDER", "UNKNOWN"}


class AvailabilityError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise AvailabilityError(message)


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        _fail(f"{label} must be a finite numeric ordinal epoch")
    return float(value)


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def compile_ledger(ledger: Mapping[str, Any]) -> dict[str, Any]:
    if ledger.get("schema_version") != SCHEMA_VERSION:
        _fail("availability ledger schema_version mismatch")
    if ledger.get("publication_order_used_as_clinical_availability") is not False:
        _fail("publication order must never be used as clinical availability")
    rows = ledger.get("events")
    if not isinstance(rows, list):
        _fail("events must be a list")
    ids: set[str] = set()
    released: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    batches: dict[str, float] = {}
    for index, row in enumerate(rows):
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("source_event_id"), str)
            or not row.get("source_event_id")
        ):
            _fail(f"event {index} missing source_event_id")
        event_id = row["source_event_id"]
        if event_id in ids:
            _fail(f"duplicate source_event_id: {event_id}")
        ids.add(event_id)
        evidence = row.get("availability_evidence")
        if not isinstance(evidence, Mapping) or evidence.get("kind") not in KINDS:
            _fail(f"event {event_id} has invalid availability evidence")
        kind = evidence["kind"]
        release: float | None = None
        if kind == "EXACT":
            release = _finite(evidence.get("exact_epoch"), f"{event_id}.exact_epoch")
        elif kind == "INTERVAL":
            lower = _finite(evidence.get("earliest_epoch"), f"{event_id}.earliest_epoch")
            upper = _finite(evidence.get("latest_epoch"), f"{event_id}.latest_epoch")
            if upper < lower:
                _fail(f"event {event_id} interval upper bound precedes lower bound")
            release = upper
        elif kind == "REPORTED_BATCH":
            batch = evidence.get("batch_id")
            if not isinstance(batch, str) or not batch:
                _fail(f"event {event_id} reported batch lacks batch_id")
            release = _finite(evidence.get("latest_epoch"), f"{event_id}.latest_epoch")
            prior = batches.setdefault(batch, release)
            if prior != release:
                _fail(f"reported batch {batch} would be split across cuts")
        elif kind == "PARTIAL_ORDER":
            if evidence.get("latest_epoch") is not None:
                release = _finite(evidence.get("latest_epoch"), f"{event_id}.latest_epoch")
        if release is None:
            withheld.append(
                {
                    "source_event_id": event_id,
                    "reason": "availability_unknown",
                    "measurement_uncertainty_required": True,
                }
            )
            continue
        runtime_event = row.get("runtime_event")
        if not isinstance(runtime_event, Mapping):
            _fail(f"event {event_id} lacks runtime_event object")
        if "available_at" in runtime_event:
            _fail(f"event {event_id} runtime_event pre-populates available_at")
        compiled = copy.deepcopy(dict(runtime_event))
        compiled["available_at"] = release
        released.append(
            {
                "source_event_id": event_id,
                "guaranteed_available_epoch": release,
                "availability_kind": kind,
                "runtime_event": compiled,
            }
        )
    released.sort(key=lambda row: (row["guaranteed_available_epoch"], row["source_event_id"]))
    cuts: dict[float, list[str]] = {}
    for row in released:
        cuts.setdefault(row["guaranteed_available_epoch"], []).append(row["source_event_id"])
    result: dict[str, Any] = {
        "schema_version": OUTPUT_VERSION,
        "source_ledger_canonical_sha256": _canonical_sha(ledger),
        "release_semantics": "LATEST_POSSIBLE_AVAILABILITY_GUARANTEED_NO_LATER_THAN_CUT",
        "released_events": released,
        "withheld_events": sorted(withheld, key=lambda row: row["source_event_id"]),
        "cut_manifest": [
            {"cut": cut, "released_source_event_ids": sorted(event_ids)}
            for cut, event_ids in sorted(cuts.items())
        ],
    }
    result["compiled_sha256"] = _canonical_sha(result)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            _fail(f"refusing to overwrite output: {args.output}")
        ledger = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(ledger, Mapping):
            _fail("input must be JSON object")
        result = compile_ledger(ledger)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = args.output.with_suffix(args.output.suffix + ".tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, args.output)
        print(json.dumps({"status": "PASS", "compiled_sha256": result["compiled_sha256"]}, sort_keys=True))
        return 0
    except (AvailabilityError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL_CLOSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
