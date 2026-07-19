"""Fail-closed verifier for the post-selection UCM candidate seal."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .benchmark_v1_runner import verify_run_bundle
from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes


def verify_candidate_seal(path: Path, *, repo_root: Path | None = None) -> dict[str, Any]:
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    raw = path.read_bytes()
    try:
        seal = json.loads(raw.decode("utf-8", errors="strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("candidate seal is not valid JSON") from exc
    if type(seal) is not dict or canonical_json_bytes(seal) != raw:
        raise ProtocolViolation("candidate seal is not canonical JSON")
    if seal.get("protocol") != "ucm-candidate-seal/1":
        raise ProtocolViolation("candidate seal protocol mismatch")
    for member in seal["candidate_source_binding"]["files"]:
        source = repo_root / member["relative_path"]
        source_raw = source.read_bytes()
        if len(source_raw) != member["byte_length"] or digest_bytes(source_raw) != member["sha256"]:
            raise ProtocolViolation("sealed candidate source drifted")
    run_path = repo_root / seal["complete_run"]["relative_path"]
    summary = verify_run_bundle(run_path)
    manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
    if (
        summary["run_id"] != seal["complete_run"]["run_id"]
        or manifest["bundle_root"] != seal["complete_run"]["bundle_root"]
        or summary["source_binding"]["source_digest"]
        != seal["complete_run"]["source_digest"]
    ):
        raise ProtocolViolation("candidate seal/run binding mismatch")
    return seal


__all__ = ["verify_candidate_seal"]

