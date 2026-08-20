#!/usr/bin/env python3
"""Post-seal, write-once NCBI byte retriever for the NCF primary holdout.

This program has deliberately no eligibility logic.  In ``search`` mode it
retrieves only the two exact ESearch URLs frozen in the execution protocol. In
``source`` mode it retrieves PubMed identity XML and, when a PMCID was supplied
in an identifier-only request, PMC full-text XML.  The response body is stored
byte-for-byte; decoding or clinical screening is left to later, offline roles.

Network access is fail-closed: HTTPS GET only, the single frozen NCBI host,
exact canonical URLs, no proxies, and no redirects.  Every output is
write-once.  The combined pre-primary seal is verified before the first
request, including the hash of this executable and all capture schemas.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import re
import socket
import ssl
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, NoReturn, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    HTTPSHandler,
    ProxyHandler,
    Request,
    build_opener,
)

from validate_primary_search_snapshot import canonical_request_url


SCHEMA_VERSION = "NCF-PRIMARY-NCBI-RETRIEVER-1.0.0"
SEARCH_MANIFEST_VERSION = "NCF-PRIMARY-SEARCH-RETRIEVAL-MANIFEST-1.0.0"
SOURCE_REQUEST_VERSION = "NCF-PRIMARY-SOURCE-IDENTIFIER-REQUEST-1.0.0"
SOURCE_MANIFEST_VERSION = "NCF-PRIMARY-SOURCE-RETRIEVAL-MANIFEST-1.0.0"
ALLOWED_HOST = "eutils.ncbi.nlm.nih.gov"
REL_PROTOCOL = PurePosixPath("holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json")
REL_COMBINED_SEAL = PurePosixPath("holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json")
REL_TOOL = PurePosixPath("holdout/tools/retrieve_primary_ncbi_assets.py")
REL_TOOL_TEST = PurePosixPath("holdout/tools/test_retrieve_primary_ncbi_assets.py")
REL_SOURCE_REQUEST_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_source_identifier_request.schema.json"
)
REL_SOURCE_MANIFEST_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_source_retrieval_manifest.schema.json"
)
REL_SEARCH_MANIFEST_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_search_retrieval_manifest.schema.json"
)
REL_SEARCH_MANIFEST = PurePosixPath(
    "holdout/evidence/PRIMARY_SEARCH_RETRIEVAL_MANIFEST.json"
)
REL_SEARCH_PAYLOAD_ROOT = PurePosixPath(
    "holdout/evidence/primary_search_raw/payloads"
)
REL_SOURCE_ROOT = PurePosixPath("holdout/evidence/primary_source_raw")
REL_SCREENING_REQUEST = PurePosixPath(
    "holdout/evidence/PRIMARY_SOURCE_IDENTIFIERS_SCREENING.json"
)
REL_SELECTED_REQUEST = PurePosixPath(
    "holdout/evidence/PRIMARY_SOURCE_IDENTIFIERS_SELECTED.json"
)
REL_SCREENING_SOURCE_MANIFEST = PurePosixPath(
    "holdout/evidence/PRIMARY_SOURCE_RETRIEVAL_MANIFEST_SCREENING.json"
)
REL_SELECTED_SOURCE_MANIFEST = PurePosixPath(
    "holdout/evidence/PRIMARY_SOURCE_RETRIEVAL_MANIFEST_SELECTED.json"
)
PMID = re.compile(r"^[1-9][0-9]*$")
PMCID = re.compile(r"^PMC[1-9][0-9]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
MAX_BODY_BYTES = 64 * 1024 * 1024


class RetrievalError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise RetrievalError(message)


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


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _load_object(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        _fail(f"{label} missing or symlink: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid {label}: {exc}")
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a JSON object")
    return value


def _root_path(root: Path, rel: PurePosixPath, *, must_exist: bool) -> Path:
    if rel.is_absolute() or ".." in rel.parts:
        _fail(f"non-canonical path: {rel.as_posix()}")
    base = root.resolve(strict=True)
    path = base.joinpath(*rel.parts)
    resolved = path.resolve(strict=must_exist)
    try:
        resolved.relative_to(base)
    except ValueError:
        _fail(f"path escapes study root: {rel.as_posix()}")
    if must_exist and (not resolved.is_file() or resolved.is_symlink()):
        _fail(f"required regular non-symlink file missing: {rel.as_posix()}")
    if not must_exist:
        # Existing parents must not redirect writes through a symlink.
        parent = resolved.parent
        probe = parent
        while probe != base and not probe.exists():
            probe = probe.parent
        if probe.is_symlink():
            _fail(f"output parent is a symlink: {rel.as_posix()}")
    return resolved


def _artifact_ref(root: Path, rel: PurePosixPath) -> dict[str, Any]:
    path = _root_path(root, rel, must_exist=True)
    raw = path.read_bytes()
    return {"path": rel.as_posix(), "sha256": _sha_bytes(raw), "bytes": len(raw)}


def _assert_bound_artifact(
    root: Path,
    row: Any,
    expected_rel: PurePosixPath,
    label: str,
) -> None:
    if not isinstance(row, Mapping) or row.get("path") != expected_rel.as_posix():
        _fail(f"combined seal {label} path mismatch")
    actual = _artifact_ref(root, expected_rel)
    if dict(row) != actual:
        _fail(f"combined seal {label} hash/bytes mismatch")


def _validate_preseal(root: Path) -> tuple[Mapping[str, Any], str, str]:
    protocol_path = _root_path(root, REL_PROTOCOL, must_exist=True)
    seal_path = _root_path(root, REL_COMBINED_SEAL, must_exist=True)
    protocol = _load_object(protocol_path, "execution protocol")
    seal = _load_object(seal_path, "combined pre-primary seal")
    if protocol.get("status") != "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION":
        _fail("execution protocol is not frozen before search")
    if seal.get("status") != "SEALED_BEFORE_PRIMARY_CASE_SELECTION":
        _fail("combined pre-primary seal status is not executable")
    sealed_at = seal.get("sealed_at")
    if not isinstance(sealed_at, str) or not sealed_at:
        _fail("combined pre-primary sealed_at missing")
    payload_sha = seal.get("payload_sha256")
    if not isinstance(payload_sha, str) or not SHA256.fullmatch(payload_sha):
        _fail("combined pre-primary payload_sha256 missing")
    unsigned = dict(seal)
    unsigned.pop("payload_sha256", None)
    if _sha_bytes(_canonical_bytes(unsigned)) != payload_sha:
        _fail("combined pre-primary payload_sha256 mismatch")
    bindings = seal.get("bindings")
    primary = bindings.get("primary_execution") if isinstance(bindings, Mapping) else None
    if not isinstance(primary, Mapping):
        _fail("combined seal primary_execution binding missing")
    for key, rel, label in (
        ("protocol_json", REL_PROTOCOL, "execution protocol"),
        ("ncbi_retriever", REL_TOOL, "NCBI retriever"),
        ("ncbi_retriever_test", REL_TOOL_TEST, "NCBI retriever tests"),
        (
            "source_identifier_request_schema",
            REL_SOURCE_REQUEST_SCHEMA,
            "source identifier request schema",
        ),
        (
            "source_retrieval_manifest_schema",
            REL_SOURCE_MANIFEST_SCHEMA,
            "source retrieval manifest schema",
        ),
        (
            "raw_search_retrieval_schema",
            REL_SEARCH_MANIFEST_SCHEMA,
            "search retrieval manifest schema",
        ),
    ):
        _assert_bound_artifact(root, primary.get(key), rel, label)
    contract = protocol.get("selection", {}).get("raw_search_validation", {})
    expected = {
        "retriever": REL_TOOL.as_posix(),
        "retriever_test_source": REL_TOOL_TEST.as_posix(),
        "retriever_network_policy": "HTTPS_GET_EXACT_URL_ONLY_NO_REDIRECT_NO_PROXY",
    }
    if any(contract.get(key) != value for key, value in expected.items()):
        _fail("execution protocol does not bind the frozen NCBI retriever")
    source_capture = protocol.get("selection", {}).get("source_capture", {})
    expected_source = {
        "retriever": REL_TOOL.as_posix(),
        "retriever_test_source": REL_TOOL_TEST.as_posix(),
        "identifier_request_schema": REL_SOURCE_REQUEST_SCHEMA.as_posix(),
        "retrieval_manifest_schema": REL_SOURCE_MANIFEST_SCHEMA.as_posix(),
        "network_policy": "HTTPS_GET_EXACT_URL_ONLY_NO_REDIRECT_NO_PROXY",
        "eligibility_logic": "FORBIDDEN",
    }
    if any(source_capture.get(key) != value for key, value in expected_source.items()):
        _fail("execution protocol source_capture contract mismatch")
    return protocol, payload_sha, sealed_at


def _parse_aware_time(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        _fail(f"invalid {label}: {exc}")
    if parsed.tzinfo is None:
        _fail(f"{label} must include a timezone")
    return parsed


def _assert_post_seal_time(sealed_at: str, retrieved_at: str) -> None:
    if _parse_aware_time(retrieved_at, "retrieved_at") < _parse_aware_time(
        sealed_at, "combined pre-primary sealed_at"
    ):
        _fail("retrieval time precedes the combined pre-primary seal")


def canonical_pubmed_identity_url(pmid: str) -> str:
    if not PMID.fullmatch(pmid):
        _fail(f"invalid PMID: {pmid}")
    params = [("db", "pubmed"), ("id", pmid), ("retmode", "xml")]
    return (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
        + urlencode(params, quote_via=quote, safe="")
    )


def canonical_pmc_fulltext_url(pmcid: str) -> str:
    if not PMCID.fullmatch(pmcid):
        _fail(f"invalid PMCID: {pmcid}")
    params = [("db", "pmc"), ("id", pmcid), ("retmode", "xml")]
    return (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
        + urlencode(params, quote_via=quote, safe="")
    )


def _validate_exact_url(url: str, allowed_urls: Iterable[str]) -> None:
    allowed = set(allowed_urls)
    if url not in allowed:
        _fail("network request URL is not in the exact frozen allowlist")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or parts.hostname != ALLOWED_HOST
        or parts.port not in (None, 443)
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
    ):
        _fail("network request violates HTTPS/domain/port/userinfo policy")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise RetrievalError(f"redirect forbidden: HTTP {code}")


class NcbiHttpsGetter:
    """Minimal transport with exact URL, method, redirect, proxy and socket guards."""

    def __init__(self, allowed_urls: Iterable[str], *, timeout: float = 30.0):
        self.allowed_urls = frozenset(allowed_urls)
        if not self.allowed_urls:
            _fail("network allowlist cannot be empty")
        for url in self.allowed_urls:
            _validate_exact_url(url, self.allowed_urls)
        if timeout <= 0 or timeout > 120:
            _fail("timeout must be in (0, 120]")
        self.timeout = timeout

    @contextmanager
    def _socket_guard(self):
        original = socket.create_connection

        def guarded(address, *args, **kwargs):  # noqa: ANN001
            host = str(address[0]).rstrip(".").lower()
            port = int(address[1])
            if host != ALLOWED_HOST or port != 443:
                raise RetrievalError(f"socket destination forbidden: {host}:{port}")
            return original(address, *args, **kwargs)

        socket.create_connection = guarded
        try:
            yield
        finally:
            socket.create_connection = original

    def __call__(self, url: str) -> bytes:
        _validate_exact_url(url, self.allowed_urls)
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json, application/xml, text/xml;q=0.9",
                "User-Agent": "NCF-primary-holdout-retriever/1.0",
            },
        )
        if request.get_method() != "GET":
            _fail("only HTTP GET is permitted")
        context = ssl.create_default_context()
        opener = build_opener(ProxyHandler({}), _NoRedirect(), HTTPSHandler(context=context))
        try:
            with self._socket_guard(), opener.open(request, timeout=self.timeout) as response:
                if response.geturl() != url:
                    _fail("final response URL differs from exact canonical request URL")
                status = getattr(response, "status", None)
                if status != 200:
                    _fail(f"NCBI HTTP status is not 200: {status}")
                body = response.read(MAX_BODY_BYTES + 1)
        except RetrievalError:
            raise
        except (HTTPError, URLError, TimeoutError, OSError, http.client.HTTPException) as exc:
            _fail(f"NCBI retrieval failed: {exc}")
        if not body or len(body) > MAX_BODY_BYTES:
            _fail("NCBI response is empty or exceeds the frozen byte limit")
        return body


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _fail(f"refusing to overwrite output: {path}")
    try:
        with path.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        _fail(f"refusing to overwrite output: {path}")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _validate_esearch_response(raw: bytes, query: Mapping[str, Any]) -> None:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{query.get('query_id')}: NCBI ESearch response is not JSON: {exc}")
    result = value.get("esearchresult") if isinstance(value, Mapping) else None
    if not isinstance(result, Mapping) or result.get("errorlist") or value.get("error"):
        _fail(f"{query.get('query_id')}: NCBI ESearch response reports an error")
    for key in ("count", "retmax", "retstart"):
        if not isinstance(result.get(key), str) or not result[key].isdigit():
            _fail(f"{query.get('query_id')}: invalid ESearch {key}")
    ids = result.get("idlist")
    expected = min(int(result["count"]), int(query["retmax"]))
    if (
        int(result["retstart"]) != 0
        or int(result["retmax"]) != expected
        or not isinstance(ids, list)
        or len(ids) != expected
        or any(not isinstance(item, str) or not PMID.fullmatch(item) for item in ids)
        or len(set(ids)) != len(ids)
    ):
        _fail(f"{query.get('query_id')}: incomplete or invalid exact first page")


def retrieve_search(
    *,
    study_root: Path,
    getter_factory: Callable[[Iterable[str]], Callable[[str], bytes]] = NcbiHttpsGetter,
    now: Callable[[], str] = _utc_now,
) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    protocol, seal_sha, sealed_at = _validate_preseal(root)
    timestamp = now()
    _assert_post_seal_time(sealed_at, timestamp)
    queries = protocol.get("selection", {}).get("queries")
    if (
        not isinstance(queries, list)
        or [row.get("query_id") for row in queries if isinstance(row, Mapping)] != ["Q1", "Q2"]
    ):
        _fail("protocol does not contain exact ordered Q1/Q2")
    manifest_path = _root_path(root, REL_SEARCH_MANIFEST, must_exist=False)
    planned_paths = [
        _root_path(
            root,
            REL_SEARCH_PAYLOAD_ROOT / f"{query['query_id']}.response.json",
            must_exist=False,
        )
        for query in queries
    ]
    if manifest_path.exists() or any(path.exists() for path in planned_paths):
        _fail("search capture is write-once and an output already exists")
    urls = [canonical_request_url(row) for row in queries]
    getter = getter_factory(urls)
    bodies: list[bytes] = []
    for url, query in zip(urls, queries):
        raw = getter(url)
        _validate_esearch_response(raw, query)
        bodies.append(raw)
    rows: list[dict[str, Any]] = []
    paths: list[tuple[Path, bytes]] = []
    for query, url, raw in zip(queries, urls, bodies):
        rel = REL_SEARCH_PAYLOAD_ROOT / f"{query['query_id']}.response.json"
        path = _root_path(root, rel, must_exist=False)
        paths.append((path, raw))
        rows.append(
            {
                "query_id": query["query_id"],
                "request_url": url,
                "raw_payload_ref": {
                    "path": rel.as_posix(),
                    "sha256": _sha_bytes(raw),
                    "bytes": len(raw),
                },
            }
        )
    manifest = {
        "schema_version": SEARCH_MANIFEST_VERSION,
        "retrieved_at": timestamp,
        "query_runs": rows,
    }
    for path, raw in paths:
        _write_once(path, raw)
    _write_once(manifest_path, _canonical_bytes(manifest))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "CAPTURED",
        "mode": "search",
        "combined_preprimary_payload_sha256": seal_sha,
        "manifest_ref": _artifact_ref(root, REL_SEARCH_MANIFEST),
    }


def _validate_identifier_request(
    root: Path, purpose: str, request_rel: PurePosixPath
) -> tuple[Mapping[str, Any], list[dict[str, str | None]]]:
    expected_rel = REL_SCREENING_REQUEST if purpose == "SCREENING" else REL_SELECTED_REQUEST
    if request_rel != expected_rel:
        _fail(f"{purpose} identifier request path must be {expected_rel.as_posix()}")
    request = _load_object(_root_path(root, request_rel, must_exist=True), "source identifier request")
    if set(request) != {"schema_version", "purpose", "identifiers"}:
        _fail("identifier request contains non-identifier fields")
    if request.get("schema_version") != SOURCE_REQUEST_VERSION or request.get("purpose") != purpose:
        _fail("identifier request schema_version/purpose mismatch")
    rows = request.get("identifiers")
    if not isinstance(rows, list) or not rows:
        _fail("identifier request must contain at least one identifier row")
    parsed: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping) or set(row) - {"pmid", "pmcid"} or "pmid" not in row:
            _fail("identifier row may contain only pmid and optional pmcid")
        pmid = row.get("pmid")
        pmcid = row.get("pmcid")
        if not isinstance(pmid, str) or not PMID.fullmatch(pmid):
            _fail("identifier row PMID invalid")
        if pmcid is not None and (not isinstance(pmcid, str) or not PMCID.fullmatch(pmcid)):
            _fail("identifier row PMCID invalid")
        key = f"{pmid}|{pmcid or ''}"
        if key in seen:
            _fail("duplicate identifier row")
        seen.add(key)
        parsed.append({"pmid": pmid, "pmcid": pmcid})
    return request, parsed


def retrieve_sources(
    *,
    study_root: Path,
    purpose: str,
    request_rel: PurePosixPath,
    getter_factory: Callable[[Iterable[str]], Callable[[str], bytes]] = NcbiHttpsGetter,
    now: Callable[[], str] = _utc_now,
) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    if purpose not in {"SCREENING", "SELECTED"}:
        _fail("source retrieval purpose must be SCREENING or SELECTED")
    protocol, seal_sha, sealed_at = _validate_preseal(root)
    timestamp = now()
    _assert_post_seal_time(sealed_at, timestamp)
    del protocol  # Contract validation is the only protocol use; no clinical logic exists here.
    _request, identifiers = _validate_identifier_request(root, purpose, request_rel)
    manifest_rel = (
        REL_SCREENING_SOURCE_MANIFEST
        if purpose == "SCREENING"
        else REL_SELECTED_SOURCE_MANIFEST
    )
    manifest_path = _root_path(root, manifest_rel, must_exist=False)
    planned_rels: list[PurePosixPath] = []
    purpose_root = REL_SOURCE_ROOT / purpose.lower()
    for row in identifiers:
        planned_rels.append(
            purpose_root / "identity" / f"PMID-{row['pmid']}.pubmed.xml"
        )
        if row["pmcid"] is not None:
            planned_rels.append(
                purpose_root / "fulltext" / f"PMCID-{row['pmcid']}.pmc.xml"
            )
    planned_paths = [_root_path(root, rel, must_exist=False) for rel in planned_rels]
    if manifest_path.exists() or any(path.exists() for path in planned_paths):
        _fail("source capture is write-once and an output already exists")
    urls: list[str] = []
    for row in identifiers:
        urls.append(canonical_pubmed_identity_url(str(row["pmid"])))
        if row["pmcid"] is not None:
            urls.append(canonical_pmc_fulltext_url(str(row["pmcid"])))
    getter = getter_factory(urls)
    retrieved: dict[str, bytes] = {url: getter(url) for url in urls}
    if any(
        not raw.strip()
        or not raw.lstrip().startswith(b"<")
        or b"<ERROR>" in raw.upper()
        for raw in retrieved.values()
    ):
        _fail("NCBI identity/full-text response is not non-empty XML bytes")
    entries: list[dict[str, Any]] = []
    outputs: list[tuple[PurePosixPath, bytes]] = []
    for row in identifiers:
        pmid = str(row["pmid"])
        identity_url = canonical_pubmed_identity_url(pmid)
        identity_raw = retrieved[identity_url]
        identity_rel = purpose_root / "identity" / f"PMID-{pmid}.pubmed.xml"
        entry: dict[str, Any] = {
            "pmid": pmid,
            "pmcid": row["pmcid"],
            "identity_request_url": identity_url,
            "identity_payload_ref": {
                "path": identity_rel.as_posix(),
                "sha256": _sha_bytes(identity_raw),
                "bytes": len(identity_raw),
            },
            "fulltext_request_url": None,
            "fulltext_payload_ref": None,
        }
        outputs.append((identity_rel, identity_raw))
        if row["pmcid"] is not None:
            pmcid = str(row["pmcid"])
            fulltext_url = canonical_pmc_fulltext_url(pmcid)
            fulltext_raw = retrieved[fulltext_url]
            fulltext_rel = purpose_root / "fulltext" / f"PMCID-{pmcid}.pmc.xml"
            entry["fulltext_request_url"] = fulltext_url
            entry["fulltext_payload_ref"] = {
                "path": fulltext_rel.as_posix(),
                "sha256": _sha_bytes(fulltext_raw),
                "bytes": len(fulltext_raw),
            }
            outputs.append((fulltext_rel, fulltext_raw))
        entries.append(entry)
    manifest = {
        "schema_version": SOURCE_MANIFEST_VERSION,
        "purpose": purpose,
        "retrieved_at": timestamp,
        "combined_preprimary_payload_sha256": seal_sha,
        "identifier_request_ref": _artifact_ref(root, request_rel),
        "entries": entries,
        "eligibility_assessed": False,
    }
    physical_outputs = [(_root_path(root, rel, must_exist=False), raw) for rel, raw in outputs]
    for path, raw in physical_outputs:
        _write_once(path, raw)
    _write_once(manifest_path, _canonical_bytes(manifest))
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "CAPTURED",
        "mode": "source",
        "purpose": purpose,
        "combined_preprimary_payload_sha256": seal_sha,
        "manifest_ref": _artifact_ref(root, manifest_rel),
        "identifier_count": len(identifiers),
        "eligibility_assessed": False,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, required=True)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("search")
    source = sub.add_parser("source")
    source.add_argument("--purpose", choices=("SCREENING", "SELECTED"), required=True)
    source.add_argument("--identifier-request", type=str, required=True)
    args = parser.parse_args(argv)
    try:
        if args.mode == "search":
            result = retrieve_search(study_root=args.study_root)
        else:
            rel = PurePosixPath(args.identifier_request)
            if rel.is_absolute() or ".." in rel.parts or rel.as_posix() != args.identifier_request:
                _fail("identifier request path must be canonical relative POSIX path")
            result = retrieve_sources(
                study_root=args.study_root,
                purpose=args.purpose,
                request_rel=rel,
            )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (RetrievalError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
