"""Seed-authority adapter for reproducible UCM benchmark v1 replays.

Before the public reveal, the runner consumes the private seed-secret wire.
After the reveal, an independent reproducer must be able to consume the public
seed-reveal wire without reconstructing a file that pretends to be private.
This module accepts either canonical artifact, verifies that it opens the live
freeze commitments, and returns the common seed material used by execution.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .benchmark_v1_freeze import (
    SEED_REVEAL_SCHEMA,
    SEED_SECRET_SCHEMA,
    build_seed_reveal,
    verify_freeze_manifest_bytes,
    verify_seed_reveal,
)
from .canonical import ProtocolViolation, canonical_json_bytes


def _decode_canonical_object(path: Path, label: str) -> dict[str, Any]:
    """Decode exact compact-JSON-plus-LF bytes and reject duplicate keys."""

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(f"{label} is unavailable") from exc

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolViolation(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
        )
    except ProtocolViolation:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ProtocolViolation(f"{label} is not valid JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"{label} is not canonical compact JSON plus LF")
    return value


def load_seed_authority(
    freeze_path: Path,
    authority_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load a private secret or public reveal against the live freeze.

    The second return value is a normalized private-shaped execution wire.  It
    is an in-memory adapter only; callers must preserve the third return value
    in provenance rather than relabelling a public reveal as a private secret.
    """

    try:
        freeze_raw = freeze_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation("benchmark freeze manifest is unavailable") from exc
    freeze = verify_freeze_manifest_bytes(freeze_raw)
    authority = _decode_canonical_object(authority_path, "benchmark seed authority")
    schema = authority.get("schema_version")
    if schema == SEED_SECRET_SCHEMA:
        # This validates exact private schema, seed bounds/order, and every
        # frozen commitment.  No reveal bytes are written or published here.
        build_seed_reveal(authority, freeze)
        execution_secret = authority
        provenance = {
            "authority_kind": "private_seed_secret",
            "authority_schema_version": SEED_SECRET_SCHEMA,
            "seed_preimages_published": False,
        }
    elif schema == SEED_REVEAL_SCHEMA:
        # Public reveal has a distinct schema and also binds freeze_root.
        verify_seed_reveal(authority, freeze)
        execution_secret = {
            "schema_version": SEED_SECRET_SCHEMA,
            "benchmark_id": authority["benchmark_id"],
            "replicates": authority["replicates"],
        }
        provenance = {
            "authority_kind": "public_seed_reveal",
            "authority_schema_version": SEED_REVEAL_SCHEMA,
            "seed_preimages_published": True,
        }
    else:
        raise ProtocolViolation("benchmark seed authority schema mismatch")
    return freeze, execution_secret, provenance


__all__ = ["load_seed_authority"]
