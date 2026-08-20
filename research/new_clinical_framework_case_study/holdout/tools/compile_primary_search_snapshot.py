"""Offline deterministic compiler for the frozen primary PubMed search.

The scout first saves the exact HTTP response bytes and a content-addressed
retrieval manifest.  This compiler performs no network access.  It validates
the canonical request URLs and exact payload bytes, then writes the two capture
manifests and the complete identifier snapshot used by the selector.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, NoReturn, Sequence

from validate_primary_search_snapshot import (
    PAYLOAD_ROOT,
    RAW_PROVIDER,
    RAW_SCHEMA_VERSION,
    SearchValidationError,
    _assert_ref,
    _load,
    canonical_request_url,
    parse_exact_payload,
    validate_search_snapshot,
)


RETRIEVAL_SCHEMA_VERSION = "NCF-PRIMARY-SEARCH-RETRIEVAL-MANIFEST-1.0.0"
SNAPSHOT_SCHEMA_VERSION = "NCF-PRIMARY-SEARCH-SNAPSHOT-1.0.0"
REL_RETRIEVAL_MANIFEST = Path("holdout/evidence/PRIMARY_SEARCH_RETRIEVAL_MANIFEST.json")
REL_SNAPSHOT = Path("holdout/evidence/PRIMARY_CASE_SEARCH_SNAPSHOT.json")
REL_PROTOCOL = Path("holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json")


class SearchCompileError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise SearchCompileError(message)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        _fail(f"refusing to overwrite compiler output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    if temp.exists():
        temp.unlink()
    try:
        temp.write_bytes(_canonical_bytes(value))
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def _fixed_path(study_root: Path, path: Path, rel: Path, label: str) -> Path:
    root = study_root.resolve(strict=True)
    expected = (root / rel).resolve(strict=False)
    actual = path.resolve(strict=False)
    if actual != expected:
        _fail(f"{label} path must be canonical {rel.as_posix()}")
    return actual


def compile_snapshot(
    *,
    study_root: Path,
    protocol: Mapping[str, Any],
    retrieval_manifest: Mapping[str, Any],
    snapshot_output: Path,
) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    snapshot_path = _fixed_path(root, snapshot_output, REL_SNAPSHOT, "snapshot output")
    if set(retrieval_manifest) != {"schema_version", "retrieved_at", "query_runs"}:
        _fail("retrieval manifest top-level shape mismatch")
    if retrieval_manifest.get("schema_version") != RETRIEVAL_SCHEMA_VERSION:
        _fail("retrieval manifest schema_version mismatch")
    retrieved_at = retrieval_manifest.get("retrieved_at")
    if not isinstance(retrieved_at, str) or not retrieved_at:
        _fail("retrieval manifest retrieved_at missing")
    expected_queries = protocol.get("selection", {}).get("queries")
    runs = retrieval_manifest.get("query_runs")
    if not isinstance(expected_queries, list) or not isinstance(runs, list):
        _fail("frozen queries or retrieval runs missing")
    if [row.get("query_id") for row in expected_queries] != ["Q1", "Q2"]:
        _fail("frozen protocol must contain exact Q1/Q2 order")
    if len(runs) != 2 or any(not isinstance(row, Mapping) for row in runs):
        _fail("retrieval manifest must contain exactly two query runs")
    if [row.get("query_id") for row in runs] != ["Q1", "Q2"]:
        _fail("retrieval manifest query runs must be exact Q1/Q2 order")

    query_rows: list[dict[str, Any]] = []
    union: set[str] = set()
    capture_paths: list[Path] = []
    for query, run in zip(expected_queries, runs):
        query_id = query["query_id"]
        if set(run) != {"query_id", "request_url", "raw_payload_ref"}:
            _fail(f"{query_id}: retrieval run shape mismatch")
        expected_url = canonical_request_url(query)
        if run.get("request_url") != expected_url:
            _fail(f"{query_id}: request_url differs from canonical frozen URL")
        expected_payload_rel = f"holdout/evidence/primary_search_raw/payloads/{query_id}.response.json"
        payload_ref = run.get("raw_payload_ref")
        if not isinstance(payload_ref, Mapping) or payload_ref.get("path") != expected_payload_rel:
            _fail(f"{query_id}: raw payload path must be {expected_payload_rel}")
        try:
            payload_path = _assert_ref(
                study_root=root,
                ref=payload_ref,
                required_parent=PAYLOAD_ROOT,
                required_suffix=".json",
                require_bytes=True,
                label=f"{query_id} exact raw payload",
            )
            ids = parse_exact_payload(payload_path, query)
        except (SearchValidationError, OSError) as exc:
            _fail(str(exc))
        capture = {
            "schema_version": RAW_SCHEMA_VERSION,
            "provider": RAW_PROVIDER,
            "query_id": query_id,
            "retrieved_at": retrieved_at,
            "request": {
                "database": "pubmed",
                "query": query["query"],
                "sort": query["sort"],
                "retmax": query["retmax"],
                "retstart": 0,
                "retmode": "json",
                "request_url": expected_url,
            },
            "raw_payload_ref": dict(run["raw_payload_ref"]),
            "retrieved_count": len(ids),
        }
        capture_path = root / f"holdout/evidence/primary_search_raw/{query_id}.capture.json"
        capture_paths.append(capture_path)
        # Hash deterministic bytes before writing so the snapshot is a pure
        # compile product, not dependent on a read-after-write race.
        capture_sha = hashlib.sha256(_canonical_bytes(capture)).hexdigest()
        query_rows.append(
            {
                "query_id": query_id,
                "query": query["query"],
                "sort": query["sort"],
                "retmax": query["retmax"],
                "ordered_case_ids": ids,
                "raw_response_ref": {
                    "path": capture_path.relative_to(root).as_posix(),
                    "sha256": capture_sha,
                },
            }
        )
        union.update(ids)

    outputs = [*capture_paths, snapshot_path]
    existing = [str(path) for path in outputs if path.exists()]
    if existing:
        _fail(f"refusing to overwrite compiler outputs: {existing}")
    snapshot = {
        "schema_version": SNAPSHOT_SCHEMA_VERSION,
        "retrieved_at": retrieved_at,
        "query_runs": query_rows,
        "canonical_case_ids": sorted(union),
    }
    for capture_path, query, run in zip(capture_paths, expected_queries, runs):
        payload_path = root / Path(*Path(run["raw_payload_ref"]["path"]).parts)
        ids = parse_exact_payload(payload_path, query)
        capture = {
            "schema_version": RAW_SCHEMA_VERSION,
            "provider": RAW_PROVIDER,
            "query_id": query["query_id"],
            "retrieved_at": retrieved_at,
            "request": {
                "database": "pubmed",
                "query": query["query"],
                "sort": query["sort"],
                "retmax": query["retmax"],
                "retstart": 0,
                "retmode": "json",
                "request_url": canonical_request_url(query),
            },
            "raw_payload_ref": dict(run["raw_payload_ref"]),
            "retrieved_count": len(ids),
        }
        _write_new(capture_path, capture)
    _write_new(snapshot_path, snapshot)
    try:
        validation = validate_search_snapshot(
            study_root=root, protocol=protocol, snapshot=snapshot
        )
    except (SearchValidationError, OSError) as exc:
        _fail(f"compiler postcondition failed: {exc}")
    return {
        "status": "COMPILED",
        "snapshot_path": snapshot_path.relative_to(root).as_posix(),
        "snapshot_sha256": _sha(snapshot_path),
        "canonical_case_count": validation["canonical_case_count"],
        "retrieved_count_by_query": validation["retrieved_count_by_query"],
    }


def compile_snapshot_files(
    *, study_root: Path, protocol_path: Path, retrieval_manifest_path: Path, snapshot_output: Path
) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    _fixed_path(root, protocol_path, REL_PROTOCOL, "execution protocol")
    _fixed_path(root, retrieval_manifest_path, REL_RETRIEVAL_MANIFEST, "retrieval manifest")
    return compile_snapshot(
        study_root=root,
        protocol=_load(protocol_path, "execution protocol"),
        retrieval_manifest=_load(retrieval_manifest_path, "retrieval manifest"),
        snapshot_output=snapshot_output,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--retrieval-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = compile_snapshot_files(
            study_root=args.study_root,
            protocol_path=args.protocol,
            retrieval_manifest_path=args.retrieval_manifest,
            snapshot_output=args.output,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (SearchCompileError, SearchValidationError, OSError) as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
