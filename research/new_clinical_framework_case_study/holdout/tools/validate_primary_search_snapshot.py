"""Validate exact raw PubMed bytes, captures, and a primary search snapshot.

This tool performs no network access and makes no selection.  Each snapshot
query row must be an exact projection of a content-addressed capture, which in
turn binds the untouched HTTP response bytes and the canonical URL reconstructed
from the frozen Q1/Q2 parameters.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence
from urllib.parse import quote, urlencode


RAW_SCHEMA_VERSION = "NCF-PRIMARY-RAW-SEARCH-RESPONSE-1.0.0"
SNAPSHOT_SCHEMA_VERSION = "NCF-PRIMARY-SEARCH-SNAPSHOT-1.0.0"
RAW_PROVIDER = "NCBI_PUBMED_ESEARCH_JSON"
RAW_ROOT = PurePosixPath("holdout/evidence/primary_search_raw")
PAYLOAD_ROOT = RAW_ROOT / "payloads"
ESearch_ENDPOINT = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class SearchValidationError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise SearchValidationError(message)


def _load(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        _fail(f"{label} missing or symlink: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid {label}: {exc}")
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a JSON object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_request_url(query: Mapping[str, Any]) -> str:
    """Return one byte-stable RFC3986 URL for a frozen query."""

    params = [
        ("db", "pubmed"),
        ("term", str(query.get("query", ""))),
        ("sort", str(query.get("sort", ""))),
        ("retmax", str(query.get("retmax", ""))),
        ("retstart", "0"),
        ("retmode", "json"),
    ]
    return ESearch_ENDPOINT + "?" + urlencode(params, quote_via=quote, safe="")


def _safe_bound_path(
    study_root: Path,
    path_text: Any,
    *,
    required_parent: PurePosixPath,
    required_suffix: str,
    label: str,
) -> Path:
    if not isinstance(path_text, str):
        _fail(f"{label} path missing")
    rel = PurePosixPath(path_text)
    if rel.is_absolute() or ".." in rel.parts or rel.as_posix() != path_text:
        _fail(f"{label} path is not canonical")
    if (
        len(rel.parts) != len(required_parent.parts) + 1
        or rel.parts[: len(required_parent.parts)] != required_parent.parts
    ):
        _fail(f"{label} must be directly under {required_parent.as_posix()}")
    if not rel.name.endswith(required_suffix):
        _fail(f"{label} has wrong suffix")
    root = study_root.resolve(strict=True)
    candidate = root / Path(*rel.parts)
    if candidate.is_symlink():
        _fail(f"{label} missing or symlink")
    cursor = candidate.parent
    while cursor != root:
        if cursor.is_symlink():
            _fail(f"{label} parent is a symlink")
        if root not in cursor.parents:
            break
        cursor = cursor.parent
    path = candidate.resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError:
        _fail(f"{label} escapes study root")
    if not path.is_file():
        _fail(f"{label} missing or symlink")
    return path


def _assert_ref(
    *,
    study_root: Path,
    ref: Any,
    required_parent: PurePosixPath,
    required_suffix: str,
    require_bytes: bool,
    label: str,
) -> Path:
    expected_keys = {"path", "sha256", "bytes"} if require_bytes else {"path", "sha256"}
    if not isinstance(ref, Mapping) or set(ref) != expected_keys:
        _fail(f"{label} ref must contain exactly {sorted(expected_keys)}")
    path = _safe_bound_path(
        study_root,
        ref.get("path"),
        required_parent=required_parent,
        required_suffix=required_suffix,
        label=label,
    )
    digest = ref.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        _fail(f"{label} sha256 invalid")
    if _sha(path) != digest:
        _fail(f"{label} sha256 mismatch")
    if require_bytes and ref.get("bytes") != path.stat().st_size:
        _fail(f"{label} byte count mismatch")
    return path


def _as_nonnegative_int(value: Any, label: str) -> int:
    if not isinstance(value, str) or not value.isdigit():
        _fail(f"{label} must be a decimal string")
    return int(value)


def parse_exact_payload(payload_path: Path, expected_query: Mapping[str, Any]) -> list[str]:
    """Parse the untouched response bytes and prove first-page completeness."""

    raw = _load(payload_path, f"{expected_query.get('query_id')} exact raw response bytes")
    result = raw.get("esearchresult")
    query_id = str(expected_query.get("query_id"))
    if not isinstance(result, Mapping):
        _fail(f"{query_id}: raw response has no esearchresult")
    if result.get("errorlist") or raw.get("error"):
        _fail(f"{query_id}: raw response reports a search error")
    count = _as_nonnegative_int(result.get("count"), f"{query_id}.count")
    returned_retmax = _as_nonnegative_int(result.get("retmax"), f"{query_id}.retmax")
    retstart = _as_nonnegative_int(result.get("retstart"), f"{query_id}.retstart")
    if retstart != 0:
        _fail(f"{query_id}: raw response is not the first result page")
    requested_retmax = int(expected_query.get("retmax"))
    ids = result.get("idlist")
    if (
        not isinstance(ids, list)
        or any(not isinstance(item, str) or not item.isdigit() for item in ids)
        or len(set(ids)) != len(ids)
    ):
        _fail(f"{query_id}: raw response idlist invalid or duplicated")
    expected_count = min(count, requested_retmax)
    if returned_retmax != expected_count or len(ids) != expected_count:
        _fail(
            f"{query_id}: incomplete raw result page; expected {expected_count} ids, "
            f"RetMax={returned_retmax}, len(idlist)={len(ids)}"
        )
    return [f"PMID:{item}" for item in ids]


def validate_capture(
    *,
    study_root: Path,
    expected_query: Mapping[str, Any],
    capture_ref: Any,
) -> tuple[list[str], str]:
    query_id = str(expected_query.get("query_id"))
    expected_capture_rel = (RAW_ROOT / f"{query_id}.capture.json").as_posix()
    if not isinstance(capture_ref, Mapping) or capture_ref.get("path") != expected_capture_rel:
        _fail(f"{query_id}: raw capture path must be {expected_capture_rel}")
    capture_path = _assert_ref(
        study_root=study_root,
        ref=capture_ref,
        required_parent=RAW_ROOT,
        required_suffix=".capture.json",
        require_bytes=False,
        label=f"{query_id} raw capture",
    )
    capture = _load(capture_path, f"{query_id} raw search capture")
    if capture.get("schema_version") != RAW_SCHEMA_VERSION:
        _fail(f"{query_id}: raw capture schema_version mismatch")
    if capture.get("provider") != RAW_PROVIDER or capture.get("query_id") != query_id:
        _fail(f"{query_id}: raw capture provider/query identity mismatch")
    if not isinstance(capture.get("retrieved_at"), str) or not capture["retrieved_at"]:
        _fail(f"{query_id}: raw capture retrieved_at missing")
    request = capture.get("request")
    if not isinstance(request, Mapping) or set(request) != {
        "database", "query", "sort", "retmax", "retstart", "retmode", "request_url"
    }:
        _fail(f"{query_id}: raw capture request shape mismatch")
    expected_request = {
        "database": "pubmed",
        "query": expected_query.get("query"),
        "sort": expected_query.get("sort"),
        "retmax": expected_query.get("retmax"),
        "retstart": 0,
        "retmode": "json",
        "request_url": canonical_request_url(expected_query),
    }
    if dict(request) != expected_request:
        _fail(f"{query_id}: raw capture request or canonical URL differs from frozen query")
    payload_ref = capture.get("raw_payload_ref")
    expected_payload_rel = (PAYLOAD_ROOT / f"{query_id}.response.json").as_posix()
    if not isinstance(payload_ref, Mapping) or payload_ref.get("path") != expected_payload_rel:
        _fail(f"{query_id}: exact raw payload path must be {expected_payload_rel}")
    payload_path = _assert_ref(
        study_root=study_root,
        ref=payload_ref,
        required_parent=PAYLOAD_ROOT,
        required_suffix=".json",
        require_bytes=True,
        label=f"{query_id} exact raw payload",
    )
    ids = parse_exact_payload(payload_path, expected_query)
    if capture.get("retrieved_count") != len(ids):
        _fail(f"{query_id}: retrieved_count differs from len(idlist)")
    return ids, _sha(payload_path)


def validate_search_snapshot(
    *, study_root: Path, protocol: Mapping[str, Any], snapshot: Mapping[str, Any]
) -> dict[str, Any]:
    if snapshot.get("schema_version") != SNAPSHOT_SCHEMA_VERSION:
        _fail("search snapshot schema_version mismatch")
    if not isinstance(snapshot.get("retrieved_at"), str) or not snapshot["retrieved_at"]:
        _fail("search snapshot retrieved_at missing")
    expected_queries = protocol.get("selection", {}).get("queries")
    rows = snapshot.get("query_runs")
    if not isinstance(expected_queries, list) or not isinstance(rows, list):
        _fail("frozen queries or snapshot query_runs missing")
    if [row.get("query_id") for row in expected_queries if isinstance(row, Mapping)] != ["Q1", "Q2"]:
        _fail("frozen protocol must contain exact Q1/Q2 order")
    if len(rows) != len(expected_queries) or any(not isinstance(row, Mapping) for row in rows):
        _fail("search snapshot must contain exactly one row per frozen query")
    if [row.get("query_id") for row in rows] != ["Q1", "Q2"]:
        _fail("search snapshot query rows must be exact Q1/Q2 order")

    union: set[str] = set()
    raw_hashes: dict[str, str] = {}
    retrieved_counts: dict[str, int] = {}
    for expected_query, row in zip(expected_queries, rows):
        query_id = expected_query["query_id"]
        for key in ("query_id", "query", "sort", "retmax"):
            if row.get(key) != expected_query.get(key):
                _fail(f"{query_id}: snapshot differs from frozen query field {key}")
        exact_ids, payload_sha = validate_capture(
            study_root=study_root,
            expected_query=expected_query,
            capture_ref=row.get("raw_response_ref"),
        )
        if row.get("ordered_case_ids") != exact_ids:
            _fail(f"{query_id}: snapshot ordered_case_ids differ from exact raw response")
        union.update(exact_ids)
        raw_hashes[query_id] = payload_sha
        retrieved_counts[query_id] = len(exact_ids)
    canonical = snapshot.get("canonical_case_ids")
    if canonical != sorted(union):
        _fail("canonical_case_ids must equal sorted union of exact raw responses")
    return {
        "status": "PASS",
        "query_count": len(rows),
        "canonical_case_count": len(union),
        "retrieved_count_by_query": retrieved_counts,
        "raw_payload_sha256_by_query": raw_hashes,
    }


def validate_search_snapshot_files(
    *, study_root: Path, protocol_path: Path, snapshot_path: Path
) -> dict[str, Any]:
    return validate_search_snapshot(
        study_root=study_root,
        protocol=_load(protocol_path, "execution protocol"),
        snapshot=_load(snapshot_path, "search snapshot"),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_search_snapshot_files(
            study_root=args.study_root,
            protocol_path=args.protocol,
            snapshot_path=args.snapshot,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (SearchValidationError, OSError) as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
