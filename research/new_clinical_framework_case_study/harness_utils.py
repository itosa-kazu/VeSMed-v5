"""Experiment-only utilities for the independent clinical-map case study.

This module intentionally contains no patient dynamics.  It is allowed to
canonicalize public artifacts, seal files, and load event ledgers, but it must
not duplicate or patch the implementation in ``framework.py``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


def canonical_json_bytes(value: Any) -> bytes:
    """Return a deterministic UTF-8 JSON encoding suitable for evidence hashes."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise TypeError(f"{path}:{line_number}: JSONL row must be an object")
            rows.append(row)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def seal_files(root: Path, paths: Iterable[Path], *, role: str) -> dict[str, Any]:
    """Create a deterministic manifest for pre-experiment frozen artifacts.

    The returned manifest records both raw-file and canonical-JSON hashes.  A
    blind model file therefore cannot be silently rewritten with knowledge of
    the case outcome while retaining the same seal.
    """

    entries: list[dict[str, Any]] = []
    for raw_path in sorted((Path(p) for p in paths), key=lambda p: p.as_posix()):
        path = raw_path if raw_path.is_absolute() else root / raw_path
        relative = path.resolve().relative_to(root.resolve()).as_posix()
        payload = path.read_bytes()
        entry: dict[str, Any] = {
            "path": relative,
            "bytes": len(payload),
            "sha256": sha256_bytes(payload),
        }
        if path.suffix.lower() == ".json":
            entry["canonical_json_sha256"] = sha256_json(json.loads(payload))
        entries.append(entry)
    manifest = {
        "protocol": "new-clinical-framework-artifact-seal/1",
        "role": role,
        "entries": entries,
    }
    manifest["seal_sha256"] = sha256_json(manifest)
    return manifest


def assert_seal(root: Path, manifest: Mapping[str, Any]) -> None:
    expected = dict(manifest)
    claimed = expected.pop("seal_sha256", None)
    if claimed != sha256_json(expected):
        raise AssertionError("artifact seal manifest itself was modified")
    for entry in manifest.get("entries", []):
        path = root / entry["path"]
        if file_sha256(path) != entry["sha256"]:
            raise AssertionError(f"sealed artifact changed: {entry['path']}")


def availability_key(value: Any) -> tuple[int, float | str]:
    """Comparable key for the deliberately small experiment time vocabulary."""

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (0, float(value))
    if isinstance(value, str):
        try:
            return (0, float(value))
        except ValueError:
            return (1, value)
    raise TypeError(f"unsupported available_at value: {value!r}")


def events_available_at(events: Iterable[Mapping[str, Any]], cut: Any) -> list[dict[str, Any]]:
    cut_key = availability_key(cut)
    return [dict(row) for row in events if availability_key(row["available_at"]) <= cut_key]


def newly_available_events(
    events: Iterable[Mapping[str, Any]], previous_cut: Any, next_cut: Any
) -> list[dict[str, Any]]:
    low = availability_key(previous_cut)
    high = availability_key(next_cut)
    return [
        dict(row)
        for row in events
        if low < availability_key(row["available_at"]) <= high
    ]


@dataclass(frozen=True)
class EvidenceBoundary:
    source: str
    evidence_kind: str
    supports: tuple[str, ...]
    does_not_support: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "evidence_kind": self.evidence_kind,
            "supports": list(self.supports),
            "does_not_support": list(self.does_not_support),
        }


REAL_CASE_BOUNDARY = EvidenceBoundary(
    source="PMC/PubMed case report factual replay",
    evidence_kind="real_case_factual_trajectory",
    supports=(
        "event-ledger integrity",
        "posterior update direction",
        "next observed event consistency",
        "action feasibility and mode representation",
    ),
    does_not_support=(
        "individual treatment counterfactual truth",
        "population calibration",
        "general clinical efficacy",
    ),
)

SYNTHETIC_BOUNDARY = EvidenceBoundary(
    source="independent synthetic shadow-world oracle",
    evidence_kind="synthetic_causal_oracle",
    supports=(
        "known counterfactual transition checks",
        "dangerous collision and regret checks",
        "local refinement mechanics",
    ),
    does_not_support=(
        "clinical treatment effectiveness",
        "real-world parameter calibration",
        "clinical validation",
    ),
)
