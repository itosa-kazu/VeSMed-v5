"""Deterministically select the primary NCF holdout without model access.

Before selection, the tool invokes the frozen combined-seal verifier.  That
verifier revalidates only the case-blind architecture/runtime/generic-model and
execution assets already bound by the seal; it never opens a primary article,
oracle, expected diagnosis, case event ledger, mapping, or replay output.  The
selector then reads the frozen protocol, identifier-only exclusions, a complete
search-result snapshot, and a complete eligibility-screening manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Mapping, NoReturn, Sequence

from build_pre_primary_holdout_seal import SealError as CombinedSealError
from build_pre_primary_holdout_seal import verify_seal as verify_combined_seal
from validate_primary_case_screening import ScreeningValidationError
from validate_primary_case_screening import validate_case_screening
from validate_primary_search_snapshot import SearchValidationError
from validate_primary_search_snapshot import validate_search_snapshot


PROTOCOL_VERSION = "1.1.0"
SEARCH_SCHEMA_VERSION = "NCF-PRIMARY-SEARCH-SNAPSHOT-1.0.0"
SCREEN_SCHEMA_VERSION = "NCF-PRIMARY-CASE-SCREENING-1.1.0"
OUTPUT_SCHEMA_VERSION = "NCF-PRIMARY-CASE-SELECTION-1.1.0"
SELECTION_DOMAIN = "NCF-PRIMARY-SELECTION-v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
REL_PREPRIMARY = Path("holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json")
REL_PROTOCOL = Path("holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json")
REL_EXCLUSIONS = Path("holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json")
REL_SEARCH_SNAPSHOT = Path("holdout/evidence/PRIMARY_CASE_SEARCH_SNAPSHOT.json")
REL_SCREENING = Path("holdout/evidence/PRIMARY_CASE_SCREENING.json")
REL_SCREENING_EVIDENCE_INDEX = Path(
    "holdout/evidence/PRIMARY_SCREENING_EVIDENCE_INDEX.json"
)
REL_SELECTION_OUTPUT = Path("holdout/evidence/PRIMARY_HOLDOUT_SELECTION.json")


class SelectionError(RuntimeError):
    """Fail-closed selection or integrity error."""


def _fail(message: str) -> NoReturn:
    raise SelectionError(message)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _load(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        _fail(f"{label} missing or symlink: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid {label}: {exc}")
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a JSON object")
    return value


def _assert_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        _fail(f"{label} must be lowercase SHA-256")
    return value


def _canonical_study_input(path: Path, study_root: Path, rel: Path, label: str) -> Path:
    """Require a fixed, non-symlink input below the inferred study root."""

    expected = (study_root / rel).resolve(strict=False)
    try:
        actual = path.resolve(strict=True)
    except OSError as exc:
        _fail(f"{label} missing: {exc}")
    if path.is_symlink() or actual != expected:
        _fail(f"{label} path must be the canonical {rel.as_posix()}")
    return actual


def _canonical_new_output(path: Path, study_root: Path, rel: Path, label: str) -> Path:
    expected = (study_root / rel).resolve(strict=False)
    actual = path.resolve(strict=False)
    if path.is_symlink() or actual != expected:
        _fail(f"{label} path must be the canonical {rel.as_posix()}")
    root = study_root.resolve(strict=True)
    cursor = actual.parent
    while cursor != root:
        if cursor.is_symlink():
            _fail(f"{label} parent may not be a symlink")
        if root not in cursor.parents:
            _fail(f"{label} path escapes study root")
        cursor = cursor.parent
    return actual


def _infer_and_verify_study_root(preprimary_path: Path) -> Path:
    """Infer the fixed study root and run the complete combined verifier."""

    try:
        resolved = preprimary_path.resolve(strict=True)
    except OSError as exc:
        _fail(f"pre-primary seal missing: {exc}")
    if preprimary_path.is_symlink():
        _fail("pre-primary seal may not be a symlink")
    # .../<study>/holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json
    if len(resolved.parents) < 3:
        _fail("pre-primary seal path has no canonical study root")
    study_root = resolved.parents[2]
    _canonical_study_input(preprimary_path, study_root, REL_PREPRIMARY, "pre-primary seal")
    try:
        verification = verify_combined_seal(study_root, resolved)
    except (CombinedSealError, OSError) as exc:
        _fail(f"pre-primary combined seal verification failed: {exc}")
    if not isinstance(verification, Mapping) or verification.get("status") != "PASS":
        _fail("pre-primary combined seal verifier did not return PASS")
    return study_root


def _assert_bound_artifact(
    row: Any,
    *,
    expected_rel: Path,
    actual_path: Path,
    label: str,
) -> None:
    artifact = row if isinstance(row, Mapping) else None
    if artifact is None:
        _fail(f"pre-primary seal missing {label} binding")
    if artifact.get("path") != expected_rel.as_posix():
        _fail(f"pre-primary {label} binding path mismatch")
    expected_sha = _assert_sha(artifact.get("sha256"), f"sealed {label} sha256")
    if _sha256_file(actual_path) != expected_sha:
        _fail(f"{label} differs from pre-primary seal")
    if artifact.get("bytes") != actual_path.stat().st_size:
        _fail(f"{label} byte count differs from pre-primary seal")


def _validate_preprimary(
    seal: Mapping[str, Any],
    protocol_path: Path,
    exclusions_path: Path,
) -> str:
    if seal.get("status") != "SEALED_BEFORE_PRIMARY_CASE_SELECTION":
        _fail("pre-primary seal status is not eligible for selection")
    payload_sha = _assert_sha(seal.get("payload_sha256"), "pre-primary payload_sha256")
    unsigned = dict(seal)
    unsigned.pop("payload_sha256", None)
    if _sha256_bytes(_canonical_bytes(unsigned)) != payload_sha:
        _fail("pre-primary payload_sha256 does not match canonical payload")
    bindings = seal.get("bindings")
    if not isinstance(bindings, Mapping):
        _fail("pre-primary seal missing bindings")
    execution_binding = bindings.get("primary_execution")
    if not isinstance(execution_binding, Mapping):
        _fail("pre-primary seal missing primary execution binding")
    _assert_bound_artifact(
        execution_binding.get("protocol_json"),
        expected_rel=REL_PROTOCOL,
        actual_path=protocol_path,
        label="execution protocol",
    )
    exclusion_binding = bindings.get("primary_holdout_exclusions")
    if not isinstance(exclusion_binding, Mapping):
        _fail("pre-primary seal missing exclusion binding")
    _assert_bound_artifact(
        exclusion_binding.get("artifact"),
        expected_rel=REL_EXCLUSIONS,
        actual_path=exclusions_path,
        label="identifier-only exclusions",
    )
    return payload_sha


def _validate_queries(protocol: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
    if protocol.get("protocol_version") != PROTOCOL_VERSION:
        _fail("execution protocol version mismatch")
    if protocol.get("status") != "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION":
        _fail("execution protocol is not frozen")
    if snapshot.get("schema_version") != SEARCH_SCHEMA_VERSION:
        _fail("search snapshot schema_version mismatch")
    expected = protocol.get("selection", {}).get("queries")
    actual = snapshot.get("query_runs")
    if not isinstance(expected, list) or not isinstance(actual, list) or len(actual) != len(expected):
        _fail("search snapshot does not contain the exact frozen query set")
    expected_by_id = {row.get("query_id"): row for row in expected if isinstance(row, Mapping)}
    actual_by_id = {row.get("query_id"): row for row in actual if isinstance(row, Mapping)}
    if set(actual_by_id) != set(expected_by_id):
        _fail("search query ids differ from frozen protocol")
    for query_id, row in expected_by_id.items():
        seen = actual_by_id[query_id]
        for key in ("query", "sort", "retmax"):
            if seen.get(key) != row.get(key):
                _fail(f"search query {query_id} changed frozen field {key}")
        raw_ref = seen.get("raw_response_ref")
        if not isinstance(raw_ref, Mapping):
            _fail(f"{query_id}.raw_response_ref missing")
        _assert_sha(raw_ref.get("sha256"), f"{query_id}.raw_response_ref.sha256")
        ids = seen.get("ordered_case_ids")
        if not isinstance(ids, list) or any(not isinstance(item, str) or not item for item in ids):
            _fail(f"{query_id}.ordered_case_ids invalid")
    canonical = snapshot.get("canonical_case_ids")
    if not isinstance(canonical, list) or len(set(canonical)) != len(canonical):
        _fail("canonical_case_ids must be unique list")
    union = sorted({item for row in actual for item in row["ordered_case_ids"]})
    if canonical != union:
        _fail("canonical_case_ids must equal sorted union of complete query results")


def _stable_selection_bindings(
    protocol: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    eligible: Sequence[str],
) -> tuple[str, str, str]:
    """Return hashes of selection-relevant semantics only.

    Winner selection must not depend on timestamps, JSON serialization, seal
    generation metadata, filesystem metadata, or any other executor-controlled
    salt.  The frozen query semantics, exact raw ordered identifier projection,
    and exact eligible identifier set are the complete selection domain.
    """

    selection = protocol.get("selection")
    if not isinstance(selection, Mapping):
        _fail("selection protocol missing")
    sources = selection.get("sources")
    queries = selection.get("queries")
    raw_search = selection.get("raw_search_validation")
    if not isinstance(sources, list) or any(not isinstance(item, str) for item in sources):
        _fail("frozen selection sources invalid")
    if not isinstance(queries, list) or not isinstance(raw_search, Mapping):
        _fail("frozen query contract invalid")
    query_contract_rows: list[dict[str, Any]] = []
    for row in queries:
        if not isinstance(row, Mapping):
            _fail("frozen query contract row invalid")
        query_contract_rows.append(
            {
                "query_id": row.get("query_id"),
                "query": row.get("query"),
                "sort": row.get("sort"),
                "retmax": row.get("retmax"),
            }
        )
    query_contract = {
        "sources": list(sources),
        "provider": raw_search.get("provider"),
        "queries": query_contract_rows,
    }
    query_contract_sha = _sha256_bytes(_canonical_bytes(query_contract))

    actual_runs = snapshot.get("query_runs")
    if not isinstance(actual_runs, list):
        _fail("search snapshot query_runs invalid")
    actual_by_id = {
        row.get("query_id"): row for row in actual_runs if isinstance(row, Mapping)
    }
    raw_projection: list[dict[str, Any]] = []
    for query in query_contract_rows:
        query_id = query["query_id"]
        seen = actual_by_id.get(query_id)
        if not isinstance(seen, Mapping):
            _fail(f"missing raw identifier projection for {query_id}")
        ids = seen.get("ordered_case_ids")
        if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
            _fail(f"invalid raw identifier projection for {query_id}")
        raw_projection.append({"query_id": query_id, "ordered_case_ids": list(ids)})
    raw_projection_sha = _sha256_bytes(_canonical_bytes(raw_projection))

    eligible_ids = sorted(eligible)
    if len(eligible_ids) != len(set(eligible_ids)):
        _fail("eligible identifier set contains duplicates")
    eligible_set_sha = _sha256_bytes(_canonical_bytes(eligible_ids))
    return query_contract_sha, raw_projection_sha, eligible_set_sha


def _eligible_candidates(
    protocol: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    screening: Mapping[str, Any],
    exclusions: Mapping[str, Any],
    search_sha: str,
) -> list[str]:
    if screening.get("schema_version") != SCREEN_SCHEMA_VERSION:
        _fail("screening schema_version mismatch")
    if screening.get("search_snapshot_sha256") != search_sha:
        _fail("screening is not bound to exact search snapshot bytes")
    rows = screening.get("candidates")
    if not isinstance(rows, list):
        _fail("screening candidates must be a list")
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            _fail("screening candidate must be an object")
        cid = row.get("canonical_case_id")
        if not isinstance(cid, str) or not cid or cid in by_id:
            _fail("screening candidate ids must be unique non-empty strings")
        by_id[cid] = row
    canonical_ids = snapshot.get("canonical_case_ids")
    if set(by_id) != set(canonical_ids):
        missing = sorted(set(canonical_ids) - set(by_id))
        extra = sorted(set(by_id) - set(canonical_ids))
        _fail(f"every retrieved candidate must be screened; missing={missing}, extra={extra}")
    excluded = exclusions.get("excluded_case_ids")
    if not isinstance(excluded, list) or any(not isinstance(item, str) for item in excluded):
        _fail("identifier-only exclusions invalid")
    excluded_set = set(excluded)
    required_criteria = set(protocol.get("selection", {}).get("eligibility", {}))
    eligible: list[str] = []
    for cid, row in by_id.items():
        criteria = row.get("criteria")
        if not isinstance(criteria, Mapping) or set(criteria) != required_criteria:
            _fail(f"{cid}: criteria set does not exactly match frozen eligibility contract")
        computed = all(value is True for value in criteria.values()) and cid not in excluded_set
        if row.get("eligible") is not computed:
            _fail(f"{cid}: eligible flag disagrees with criteria/exclusion set")
        if computed:
            eligible.append(cid)
    minimum = protocol.get("selection", {}).get("minimum_eligible_candidates")
    if not isinstance(minimum, int) or minimum < 1:
        _fail("invalid frozen minimum eligible candidate count")
    if len(eligible) < minimum:
        _fail(f"HARNESS_INCOMPLETE: only {len(eligible)} eligible candidates, need {minimum}")
    return sorted(eligible)


def select(
    *,
    preprimary_path: Path,
    protocol_path: Path,
    exclusions_path: Path,
    search_snapshot_path: Path,
    screening_path: Path,
    screening_evidence_index_path: Path,
) -> dict[str, Any]:
    study_root = _infer_and_verify_study_root(preprimary_path)
    protocol_path = _canonical_study_input(
        protocol_path, study_root, REL_PROTOCOL, "execution protocol"
    )
    exclusions_path = _canonical_study_input(
        exclusions_path, study_root, REL_EXCLUSIONS, "identifier-only exclusions"
    )
    search_snapshot_path = _canonical_study_input(
        search_snapshot_path, study_root, REL_SEARCH_SNAPSHOT, "search snapshot"
    )
    screening_path = _canonical_study_input(
        screening_path, study_root, REL_SCREENING, "screening manifest"
    )
    screening_evidence_index_path = _canonical_study_input(
        screening_evidence_index_path,
        study_root,
        REL_SCREENING_EVIDENCE_INDEX,
        "screening evidence index",
    )
    preprimary = _load(preprimary_path, "pre-primary seal")
    protocol = _load(protocol_path, "execution protocol")
    exclusions = _load(exclusions_path, "identifier-only exclusions")
    snapshot = _load(search_snapshot_path, "search snapshot")
    screening = _load(screening_path, "screening manifest")
    payload_sha = _validate_preprimary(preprimary, protocol_path, exclusions_path)
    try:
        validate_search_snapshot(
            study_root=study_root,
            protocol=protocol,
            snapshot=snapshot,
        )
    except (SearchValidationError, OSError) as exc:
        _fail(f"raw search snapshot validation failed: {exc}")
    _validate_queries(protocol, snapshot)
    search_sha = _sha256_file(search_snapshot_path)
    try:
        screening_validation = validate_case_screening(
            study_root=study_root,
            protocol_path=protocol_path,
            search_snapshot_path=search_snapshot_path,
            screening_path=screening_path,
            exclusions_path=exclusions_path,
            evidence_index_path=screening_evidence_index_path,
        )
    except (ScreeningValidationError, OSError) as exc:
        _fail(f"content-addressed screening validation failed: {exc}")
    if screening_validation.get("status") != "PASS":
        _fail("content-addressed screening validator did not return PASS")
    eligible = screening_validation.get("eligible_candidate_ids")
    if not isinstance(eligible, list) or any(not isinstance(item, str) for item in eligible):
        _fail("content-addressed screening validator returned invalid eligible ids")
    query_contract_sha, raw_projection_sha, eligible_set_sha = _stable_selection_bindings(
        protocol, snapshot, eligible
    )
    scored = []
    for cid in eligible:
        preimage = (
            f"{SELECTION_DOMAIN}\n{query_contract_sha}\n{raw_projection_sha}\n"
            f"{eligible_set_sha}\n{cid}"
        ).encode("utf-8")
        scored.append({"canonical_case_id": cid, "selection_digest": _sha256_bytes(preimage)})
    scored.sort(key=lambda row: (row["selection_digest"], row["canonical_case_id"]))
    selected = scored[0]
    screening_by_id = {
        row["canonical_case_id"]: row
        for row in screening.get("candidates", [])
        if isinstance(row, Mapping) and isinstance(row.get("canonical_case_id"), str)
    }
    eligible_complexity_packet_refs = [
        {
            "canonical_case_id": cid,
            "packet_ref": screening_by_id[cid][
                "opaque_concurrent_process_candidate_packet_ref"
            ],
        }
        for cid in sorted(eligible)
    ]
    result: dict[str, Any] = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "algorithm": "lexicographically_smallest_sha256",
        "selection_domain": SELECTION_DOMAIN,
        "pre_primary_payload_sha256": payload_sha,
        "execution_protocol_sha256": _sha256_file(protocol_path),
        "search_snapshot_sha256": search_sha,
        "screening_manifest_sha256": _sha256_file(screening_path),
        "screening_evidence_index_sha256": _sha256_file(
            screening_evidence_index_path
        ),
        "exclusions_sha256": _sha256_file(exclusions_path),
        "frozen_query_contract_sha256": query_contract_sha,
        "raw_ordered_identifier_projection_sha256": raw_projection_sha,
        "canonical_eligible_id_set_sha256": eligible_set_sha,
        "eligible_candidate_count": len(scored),
        "eligible_candidate_digests": scored,
        "eligible_complexity_packet_refs": eligible_complexity_packet_refs,
        "selected_case_id": selected["canonical_case_id"],
        "selected_digest": selected["selection_digest"],
        "human_override_permitted": False,
    }
    result["selection_record_sha256"] = _sha256_bytes(_canonical_bytes(result))
    return result


def verify_selection_record(
    *,
    preprimary_path: Path,
    protocol_path: Path,
    exclusions_path: Path,
    search_snapshot_path: Path,
    screening_path: Path,
    screening_evidence_index_path: Path,
    selection_record_path: Path,
) -> dict[str, Any]:
    """Recompute selection from sealed inputs and verify canonical record bytes."""

    study_root = _infer_and_verify_study_root(preprimary_path)
    record_path = _canonical_study_input(
        selection_record_path, study_root, REL_SELECTION_OUTPUT, "selection record"
    )
    record = _load(record_path, "selection record")
    claimed_self_hash = _assert_sha(
        record.get("selection_record_sha256"), "selection record self hash"
    )
    unsigned = dict(record)
    unsigned.pop("selection_record_sha256", None)
    if _sha256_bytes(_canonical_bytes(unsigned)) != claimed_self_hash:
        _fail("selection record self hash mismatch")
    expected = select(
        preprimary_path=preprimary_path,
        protocol_path=protocol_path,
        exclusions_path=exclusions_path,
        search_snapshot_path=search_snapshot_path,
        screening_path=screening_path,
        screening_evidence_index_path=screening_evidence_index_path,
    )
    if dict(record) != expected:
        _fail("selection record differs from deterministic recomputation")
    canonical_file_bytes = _canonical_bytes(expected) + b"\n"
    if record_path.read_bytes() != canonical_file_bytes:
        _fail("selection record bytes are not canonical")
    return {
        "status": "PASS",
        "selected_case_id": expected["selected_case_id"],
        "selection_record_sha256": expected["selection_record_sha256"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", choices=["select", "verify"], default="select")
    parser.add_argument("--preprimary", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--search-snapshot", type=Path, required=True)
    parser.add_argument("--screening", type=Path, required=True)
    parser.add_argument("--screening-evidence-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "verify":
            result = verify_selection_record(
                preprimary_path=args.preprimary,
                protocol_path=args.protocol,
                exclusions_path=args.exclusions,
                search_snapshot_path=args.search_snapshot,
                screening_path=args.screening,
                screening_evidence_index_path=args.screening_evidence_index,
                selection_record_path=args.output,
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        result = select(
            preprimary_path=args.preprimary,
            protocol_path=args.protocol,
            exclusions_path=args.exclusions,
            search_snapshot_path=args.search_snapshot,
            screening_path=args.screening,
            screening_evidence_index_path=args.screening_evidence_index,
        )
        study_root = args.preprimary.resolve(strict=True).parents[2]
        output = _canonical_new_output(
            args.output, study_root, REL_SELECTION_OUTPUT, "selection output"
        )
        if output.exists():
            _fail(f"refusing to overwrite selection output: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        temp = output.with_suffix(output.suffix + ".tmp")
        temp.write_bytes(_canonical_bytes(result) + b"\n")
        os.replace(temp, output)
        print(json.dumps({"status": "SELECTED", "selected_case_id": result["selected_case_id"]}))
        return 0
    except (SelectionError, OSError) as exc:
        print(f"FAIL_CLOSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
