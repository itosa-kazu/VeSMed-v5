#!/usr/bin/env python3
"""Validate the complete, content-addressed primary-case screening chain.

This validator is deliberately offline.  It does not discover, download, or
select a case.  It proves that every candidate in the frozen search universe
has one disposition, that every true *and* false eligibility claim is bound to
an immutable source artifact and precise byte locator, and that numeric and
exclusion criteria are recomputed rather than trusted as booleans.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence

try:
    from .compile_opaque_concurrent_process_candidates import (
        ComplexityPacketError,
        validate_packet,
    )
except ImportError:  # direct discovery from holdout/tools
    from compile_opaque_concurrent_process_candidates import (
        ComplexityPacketError,
        validate_packet,
    )


SCREENING_VERSION = "NCF-PRIMARY-CASE-SCREENING-1.1.0"
INDEX_VERSION = "NCF-PRIMARY-SCREENING-EVIDENCE-INDEX-1.1.0"
CLAIM_VERSION = "NCF-PRIMARY-SCREENING-CRITERION-EVIDENCE-1.0.0"

PROTOCOL_ELIGIBILITY = {
    "single_adult_primary_case": True,
    "open_full_text_snapshot_required": True,
    "acute_icu_level_hemodynamic_collapse": True,
    "minimum_guaranteed_availability_epochs_before_terminal_verification": 5,
    "minimum_additional_organ_domains": 2,
    "minimum_concurrent_process_target_candidates": 2,
    "performed_action_with_later_response": True,
    "explicit_reliable_negative": True,
    "delayed_result_or_response": True,
    "reported_final_diagnosis_with_direct_or_convergent_basis": True,
    "must_not_be_in_presealed_exclusion_set": True,
    "must_not_require_invented_time_to_meet_criteria": True,
}
COUNT_CRITERIA = {
    "minimum_guaranteed_availability_epochs_before_terminal_verification": 5,
    "minimum_additional_organ_domains": 2,
    "minimum_concurrent_process_target_candidates": 2,
}
EXCLUSION_CRITERION = "must_not_be_in_presealed_exclusion_set"

CLAIM_ROOT = PurePosixPath("holdout/evidence/primary_screening_evidence/claims")
SOURCE_ROOT = PurePosixPath("holdout/evidence/primary_screening_sources")
IDENTITY_ROOT = PurePosixPath("holdout/evidence/primary_screening_identity")
COMPLEXITY_PACKET_ROOT = PurePosixPath(
    "holdout/evidence/primary_complexity_candidates/packets"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
PMID = re.compile(r"^PMID:([0-9]+)$")
PMCID = re.compile(r"^PMCID:PMC([0-9]+)$")
DOI = re.compile(r"^DOI:(.+)$")


class ScreeningValidationError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise ScreeningValidationError(message)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


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


def _strict_keys(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _fail(f"{label} must contain exactly {sorted(keys)}")
    return value


def _safe_in_root_path(
    study_root: Path,
    path_text: Any,
    *,
    label: str,
    required_parent: PurePosixPath | None = None,
    required_name: str | None = None,
) -> Path:
    if not isinstance(path_text, str) or not path_text:
        _fail(f"{label} path missing")
    rel = PurePosixPath(path_text)
    if rel.is_absolute() or ".." in rel.parts or rel.as_posix() != path_text:
        _fail(f"{label} path is not canonical")
    if required_parent is not None:
        if (
            len(rel.parts) != len(required_parent.parts) + 1
            or rel.parts[: len(required_parent.parts)] != required_parent.parts
        ):
            _fail(f"{label} must be directly under {required_parent.as_posix()}")
    if required_name is not None and rel.name != required_name:
        _fail(f"{label} must have canonical name {required_name}")

    root = study_root.resolve(strict=True)
    candidate = root / Path(*rel.parts)
    if candidate.is_symlink():
        _fail(f"{label} missing or symlink")
    cursor = candidate.parent
    while cursor != root:
        if cursor.is_symlink():
            _fail(f"{label} parent is a symlink")
        if root not in cursor.parents:
            _fail(f"{label} escapes study root")
        cursor = cursor.parent
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError):
        _fail(f"{label} missing or escapes study root")
    if not resolved.is_file():
        _fail(f"{label} is not a file")
    return resolved


def _relative_to_root(study_root: Path, path: Path, label: str) -> str:
    root = study_root.resolve(strict=True)
    if path.is_symlink():
        _fail(f"{label} is a symlink")
    try:
        return path.resolve(strict=True).relative_to(root).as_posix()
    except (FileNotFoundError, ValueError):
        _fail(f"{label} missing or outside study root")


def _validate_artifact_ref(
    *,
    study_root: Path,
    ref: Any,
    label: str,
    expected_path: Path | None = None,
    required_parent: PurePosixPath | None = None,
    required_name: str | None = None,
) -> Path:
    ref = _strict_keys(ref, {"path", "sha256", "bytes"}, f"{label} ref")
    path = _safe_in_root_path(
        study_root,
        ref.get("path"),
        label=label,
        required_parent=required_parent,
        required_name=required_name,
    )
    digest = ref.get("sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        _fail(f"{label} sha256 invalid")
    if _sha_file(path) != digest:
        _fail(f"{label} sha256 mismatch")
    if ref.get("bytes") != path.stat().st_size:
        _fail(f"{label} byte count mismatch")
    if expected_path is not None and path != expected_path.resolve(strict=True):
        _fail(f"{label} path does not bind the supplied artifact")
    return path


def _expected_source_name(candidate_id: str) -> str:
    return f"{_sha_bytes(candidate_id.encode('utf-8'))}.source.txt"


def _expected_complexity_packet_name(candidate_id: str) -> str:
    return f"{_sha_bytes(candidate_id.encode('utf-8'))}.complexity.packet.json"


def _expected_claim_name(candidate_id: str, criterion_id: str) -> str:
    preimage = f"{candidate_id}\n{criterion_id}".encode("utf-8")
    return f"{_sha_bytes(preimage)}.claim.json"


def _expected_identity_name(candidate_id: str) -> str:
    return f"{_sha_bytes(candidate_id.encode('utf-8'))}.identity.response.json"


def _normalize_identity(value: Any, label: str) -> str:
    if not isinstance(value, str):
        _fail(f"{label} must be a string identity")
    match = PMID.fullmatch(value)
    if match:
        return f"PMID:{int(match.group(1))}"
    match = PMCID.fullmatch(value)
    if match:
        return f"PMCID:PMC{int(match.group(1))}"
    match = DOI.fullmatch(value)
    if match and match.group(1).strip():
        return f"DOI:{match.group(1).strip().lower()}"
    _fail(f"{label} has unsupported or noncanonical namespace")


def _parse_ncbi_identity_response(raw: Mapping[str, Any], candidate_id: str) -> list[str]:
    pmid_match = PMID.fullmatch(candidate_id)
    if pmid_match is None or candidate_id != f"PMID:{int(pmid_match.group(1))}":
        _fail(f"{candidate_id}: canonical search identity must be normalized PMID:<digits>")
    pmid = str(int(pmid_match.group(1)))
    if raw.get("status") not in (None, "ok"):
        _fail(f"{candidate_id}: NCBI identity response status is not ok")
    records = raw.get("records")
    if not isinstance(records, list) or any(not isinstance(row, Mapping) for row in records):
        _fail(f"{candidate_id}: NCBI identity response records missing")
    matches = [row for row in records if str(row.get("pmid", "")) == pmid]
    if len(matches) != 1:
        _fail(f"{candidate_id}: NCBI identity response must contain exactly one matching PMID record")
    record = matches[0]
    requested = record.get("requested-id")
    if requested is not None and str(requested) != pmid:
        _fail(f"{candidate_id}: NCBI identity requested-id does not match PMID")
    if record.get("errmsg"):
        _fail(f"{candidate_id}: NCBI identity record reports an error")
    aliases = [candidate_id]
    pmcid = record.get("pmcid")
    if pmcid is not None and str(pmcid).strip():
        text = str(pmcid).strip().upper()
        aliases.append(_normalize_identity(f"PMCID:{text}", f"{candidate_id}.pmcid"))
    doi = record.get("doi")
    if doi is not None and str(doi).strip():
        aliases.append(_normalize_identity(f"DOI:{str(doi).strip()}", f"{candidate_id}.doi"))
    if len(aliases) != len(set(aliases)):
        _fail(f"{candidate_id}: NCBI identity response aliases are duplicated")
    return aliases


def _validate_locator(locator: Any, source_bytes: bytes, label: str) -> None:
    locator = _strict_keys(
        locator,
        {
            "locator_kind",
            "byte_start",
            "byte_end",
            "excerpt_sha256",
            "source_anchor",
            "assertions",
        },
        label,
    )
    kind = locator.get("locator_kind")
    if kind not in {"EXACT_EXCERPT", "WHOLE_DOCUMENT_REVIEW"}:
        _fail(f"{label}.locator_kind invalid")
    start, end = locator.get("byte_start"), locator.get("byte_end")
    if (
        not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or start < 0
        or end <= start
        or end > len(source_bytes)
    ):
        _fail(f"{label} byte range invalid")
    if kind == "WHOLE_DOCUMENT_REVIEW" and (start != 0 or end != len(source_bytes)):
        _fail(f"{label} whole-document locator must span exact source bytes")
    digest = locator.get("excerpt_sha256")
    if not isinstance(digest, str) or not SHA256.fullmatch(digest):
        _fail(f"{label}.excerpt_sha256 invalid")
    if _sha_bytes(source_bytes[start:end]) != digest:
        _fail(f"{label} excerpt sha256 mismatch")
    if not isinstance(locator.get("source_anchor"), str) or not locator["source_anchor"].strip():
        _fail(f"{label}.source_anchor missing")
    assertions = locator.get("assertions")
    if not isinstance(assertions, list) or not assertions:
        _fail(f"{label}.assertions must be a non-empty list")
    seen: set[str] = set()
    for index, assertion in enumerate(assertions):
        assertion = _strict_keys(
            assertion, {"assertion_id", "statement", "passed"}, f"{label}.assertions[{index}]"
        )
        aid = assertion.get("assertion_id")
        if not isinstance(aid, str) or not aid or aid in seen:
            _fail(f"{label} assertion ids must be unique non-empty strings")
        seen.add(aid)
        if not isinstance(assertion.get("statement"), str) or not assertion["statement"].strip():
            _fail(f"{label}.{aid} statement missing")
        if assertion.get("passed") is not True:
            _fail(f"{label}.{aid} is not a verified assertion")


def _validate_screening_shape(
    screening: Mapping[str, Any], expected_ids: list[str], search_sha: str
) -> dict[str, Mapping[str, Any]]:
    _strict_keys(
        screening,
        {"schema_version", "search_snapshot_sha256", "candidates"},
        "screening manifest",
    )
    if screening.get("schema_version") != SCREENING_VERSION:
        _fail("screening schema_version mismatch")
    if screening.get("search_snapshot_sha256") != search_sha:
        _fail("screening manifest is not bound to exact search snapshot bytes")
    rows = screening.get("candidates")
    if not isinstance(rows, list) or len(rows) != len(expected_ids):
        _fail("screening candidate count differs from complete search universe")
    if [row.get("canonical_case_id") for row in rows if isinstance(row, Mapping)] != expected_ids:
        _fail("screening candidates must equal the exact canonical search universe and order")
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        row = _strict_keys(
            row,
            {
                "canonical_case_id",
                "eligible",
                "criteria",
                "source_locator",
                "opaque_concurrent_process_candidate_packet_ref",
                "screening_notes",
            },
            f"screening candidates[{index}]",
        )
        cid = row.get("canonical_case_id")
        if not isinstance(cid, str) or not cid or cid in result:
            _fail("screening candidate ids must be unique non-empty strings")
        if not isinstance(row.get("eligible"), bool):
            _fail(f"{cid}: eligible must be boolean")
        criteria = row.get("criteria")
        if not isinstance(criteria, Mapping) or set(criteria) != set(PROTOCOL_ELIGIBILITY):
            _fail(f"{cid}: criteria set does not exactly match frozen eligibility contract")
        if any(not isinstance(value, bool) for value in criteria.values()):
            _fail(f"{cid}: every screening criterion claim must be boolean")
        if not isinstance(row.get("source_locator"), str) or not row["source_locator"]:
            _fail(f"{cid}: source_locator missing")
        if not isinstance(row.get("screening_notes"), str):
            _fail(f"{cid}: screening_notes must be a string")
        result[cid] = row
    return result


def validate_case_screening(
    *,
    study_root: Path,
    protocol_path: Path,
    search_snapshot_path: Path,
    screening_path: Path,
    exclusions_path: Path,
    evidence_index_path: Path,
) -> dict[str, Any]:
    """Validate all screening claims and return the recomputed eligible pool."""

    root = study_root.resolve(strict=True)
    supplied = {
        "protocol": protocol_path,
        "search snapshot": search_snapshot_path,
        "screening manifest": screening_path,
        "exclusions": exclusions_path,
        "screening evidence index": evidence_index_path,
    }
    for label, path in supplied.items():
        _relative_to_root(root, path, label)

    protocol = _load_object(protocol_path, "execution protocol")
    snapshot = _load_object(search_snapshot_path, "search snapshot")
    screening = _load_object(screening_path, "screening manifest")
    exclusions = _load_object(exclusions_path, "identifier-only exclusions")
    evidence_index = _load_object(evidence_index_path, "screening evidence index")

    selection = protocol.get("selection")
    if not isinstance(selection, Mapping) or selection.get("eligibility") != PROTOCOL_ELIGIBILITY:
        _fail("execution protocol eligibility contract differs from frozen semantics")
    if selection.get("minimum_eligible_candidates") != 3:
        _fail("frozen minimum eligible candidate count must equal 3")

    expected_ids = snapshot.get("canonical_case_ids")
    if (
        not isinstance(expected_ids, list)
        or any(not isinstance(item, str) or not item for item in expected_ids)
        or len(expected_ids) != len(set(expected_ids))
    ):
        _fail("search snapshot canonical_case_ids invalid or duplicated")
    search_sha = _sha_file(search_snapshot_path)
    screening_rows = _validate_screening_shape(screening, expected_ids, search_sha)

    _strict_keys(exclusions, {"schema_version", "exclusion_set_id", "excluded_case_ids"}, "exclusions")
    excluded = exclusions.get("excluded_case_ids")
    if (
        not isinstance(excluded, list)
        or any(not isinstance(item, str) or not item for item in excluded)
        or len(excluded) != len(set(excluded))
    ):
        _fail("excluded_case_ids invalid or duplicated")
    excluded_set = {
        _normalize_identity(item, f"excluded_case_ids[{index}]") for index, item in enumerate(excluded)
    }

    _strict_keys(
        evidence_index,
        {
            "schema_version",
            "protocol_ref",
            "search_snapshot_ref",
            "screening_manifest_ref",
            "exclusions_ref",
            "candidates",
        },
        "screening evidence index",
    )
    if evidence_index.get("schema_version") != INDEX_VERSION:
        _fail("screening evidence index schema_version mismatch")
    for key, label, path in (
        ("protocol_ref", "protocol", protocol_path),
        ("search_snapshot_ref", "search snapshot", search_snapshot_path),
        ("screening_manifest_ref", "screening manifest", screening_path),
        ("exclusions_ref", "exclusions", exclusions_path),
    ):
        _validate_artifact_ref(
            study_root=root,
            ref=evidence_index.get(key),
            label=f"evidence index {label}",
            expected_path=path,
        )

    candidate_rows = evidence_index.get("candidates")
    if not isinstance(candidate_rows, list) or len(candidate_rows) != len(expected_ids):
        _fail("evidence index candidate count differs from complete search universe")
    if [row.get("canonical_case_id") for row in candidate_rows if isinstance(row, Mapping)] != expected_ids:
        _fail("evidence index candidates must equal exact canonical search universe and order")

    eligible: list[str] = []
    source_hashes: dict[str, str] = {}
    identity_hashes: dict[str, str] = {}
    complexity_packet_hashes: dict[str, str] = {}
    claim_hashes: dict[str, dict[str, str]] = {}
    alias_owner: dict[str, str] = {}
    for candidate_index, candidate_row in enumerate(candidate_rows):
        candidate_row = _strict_keys(
            candidate_row,
            {
                "canonical_case_id",
                "identity_aliases",
                "opaque_concurrent_process_candidate_packet_ref",
                "criterion_evidence",
            },
            f"evidence index candidates[{candidate_index}]",
        )
        cid = candidate_row.get("canonical_case_id")
        assert isinstance(cid, str)  # established by exact-order equality above
        screen_row = screening_rows[cid]
        criteria = screen_row["criteria"]

        packet_ref = candidate_row.get("opaque_concurrent_process_candidate_packet_ref")
        packet_path = _validate_artifact_ref(
            study_root=root,
            ref=packet_ref,
            label=f"{cid} opaque concurrent-process candidate packet",
            required_parent=COMPLEXITY_PACKET_ROOT,
            required_name=_expected_complexity_packet_name(cid),
        )
        if screen_row.get("opaque_concurrent_process_candidate_packet_ref") != packet_ref:
            _fail(f"{cid}: screening manifest and evidence index bind different complexity packets")
        try:
            packet_validation = validate_packet(study_root=root, packet_path=packet_path)
        except ComplexityPacketError as exc:
            _fail(f"{cid}: invalid opaque concurrent-process candidate packet: {exc}")
        packet = _load_object(packet_path, f"{cid} opaque concurrent-process candidate packet")
        complexity_packet_hashes[cid] = _sha_file(packet_path)
        if packet.get("canonical_case_id") != cid:
            _fail(f"{cid}: complexity packet canonical_case_id mismatch")
        packet_target_count = packet_validation.get("target_count")
        packet_claim = isinstance(packet_target_count, int) and packet_target_count >= 2
        if criteria["minimum_concurrent_process_target_candidates"] is not packet_claim:
            _fail(f"{cid}: complexity criterion claim disagrees with packet target_count")

        identity = _strict_keys(
            candidate_row.get("identity_aliases"),
            {
                "provider",
                "aliases",
                "source_document_id",
                "raw_identity_response_ref",
                "locators",
            },
            f"{cid}.identity_aliases",
        )
        if identity.get("provider") != "NCBI_ID_CONVERTER_JSON":
            _fail(f"{cid}: identity provider must be NCBI_ID_CONVERTER_JSON")
        identity_path = _validate_artifact_ref(
            study_root=root,
            ref=identity.get("raw_identity_response_ref"),
            label=f"{cid} raw NCBI identity response",
            required_parent=IDENTITY_ROOT,
            required_name=_expected_identity_name(cid),
        )
        identity_raw_bytes = identity_path.read_bytes()
        identity_raw = _load_object(identity_path, f"{cid} raw NCBI identity response")
        parsed_aliases = _parse_ncbi_identity_response(identity_raw, cid)
        claimed_aliases = identity.get("aliases")
        if (
            not isinstance(claimed_aliases, list)
            or any(not isinstance(item, str) for item in claimed_aliases)
            or len(claimed_aliases) != len(set(claimed_aliases))
        ):
            _fail(f"{cid}: identity aliases invalid or duplicated")
        normalized_aliases = [
            _normalize_identity(item, f"{cid}.identity_aliases[{index}]")
            for index, item in enumerate(claimed_aliases)
        ]
        if normalized_aliases != claimed_aliases or normalized_aliases != parsed_aliases:
            _fail(f"{cid}: claimed identity aliases differ from raw NCBI identity response")
        if cid not in normalized_aliases:
            _fail(f"{cid}: raw canonical PMID alias omitted")
        source_document_id = _normalize_identity(
            identity.get("source_document_id"), f"{cid}.source_document_id"
        )
        if source_document_id not in normalized_aliases:
            _fail(f"{cid}: source_document_id is not an NCBI-backed alias")
        if criteria["open_full_text_snapshot_required"] is True and not source_document_id.startswith(
            "PMCID:"
        ):
            _fail(f"{cid}: open-full-text claim requires a PMCID source_document_id")
        identity_locators = identity.get("locators")
        if not isinstance(identity_locators, list) or not identity_locators:
            _fail(f"{cid}: raw identity response requires a precise locator")
        for locator_index, locator in enumerate(identity_locators):
            _validate_locator(
                locator,
                identity_raw_bytes,
                f"{cid}.identity_aliases.locators[{locator_index}]",
            )
        for alias in normalized_aliases:
            prior = alias_owner.get(alias)
            if prior is not None and prior != cid:
                _fail(f"{cid}: duplicate article identity alias {alias} already belongs to {prior}")
            alias_owner[alias] = cid
        identity_hashes[cid] = _sha_file(identity_path)

        criterion_rows = candidate_row.get("criterion_evidence")
        if not isinstance(criterion_rows, list) or len(criterion_rows) != len(PROTOCOL_ELIGIBILITY):
            _fail(f"{cid}: evidence index must contain exactly one row per criterion")
        if [row.get("criterion_id") for row in criterion_rows if isinstance(row, Mapping)] != list(
            PROTOCOL_ELIGIBILITY
        ):
            _fail(f"{cid}: criterion evidence must follow exact frozen criterion order")

        source_ref_canonical: Mapping[str, Any] | None = None
        per_claim_hashes: dict[str, str] = {}
        recomputed_claims: dict[str, bool] = {}
        for criterion_index, criterion_row in enumerate(criterion_rows):
            criterion_row = _strict_keys(
                criterion_row,
                {"criterion_id", "evidence_ref"},
                f"{cid}.criterion_evidence[{criterion_index}]",
            )
            criterion = criterion_row.get("criterion_id")
            assert isinstance(criterion, str)
            claim_path = _validate_artifact_ref(
                study_root=root,
                ref=criterion_row.get("evidence_ref"),
                label=f"{cid}.{criterion} evidence",
                required_parent=CLAIM_ROOT,
                required_name=_expected_claim_name(cid, criterion),
            )
            claim = _load_object(claim_path, f"{cid}.{criterion} criterion evidence")
            allowed_claim_keys = {
                "schema_version",
                "canonical_case_id",
                "criterion_id",
                "claimed_result",
                "source_artifact_ref",
                "locators",
            }
            if criterion in COUNT_CRITERIA:
                allowed_claim_keys.add("actual_count")
            _strict_keys(claim, allowed_claim_keys, f"{cid}.{criterion} criterion evidence")
            if claim.get("schema_version") != CLAIM_VERSION:
                _fail(f"{cid}.{criterion}: criterion evidence schema_version mismatch")
            if claim.get("canonical_case_id") != cid or claim.get("criterion_id") != criterion:
                _fail(f"{cid}.{criterion}: criterion evidence identity mismatch")
            claimed = claim.get("claimed_result")
            if not isinstance(claimed, bool) or claimed is not criteria[criterion]:
                _fail(f"{cid}.{criterion}: evidence claim differs from screening claim")

            source_ref = claim.get("source_artifact_ref")
            source_path = _validate_artifact_ref(
                study_root=root,
                ref=source_ref,
                label=f"{cid} immutable candidate source",
                required_parent=SOURCE_ROOT,
                required_name=_expected_source_name(cid),
            )
            if source_ref_canonical is None:
                source_ref_canonical = dict(source_ref)
            elif dict(source_ref) != dict(source_ref_canonical):
                _fail(f"{cid}: all criterion evidence must bind the same candidate source artifact")
            if screen_row.get("source_locator") != source_ref.get("path"):
                _fail(f"{cid}: screening source_locator does not bind immutable source artifact")
            source_bytes = source_path.read_bytes()
            if not source_bytes:
                _fail(f"{cid}: immutable candidate source is empty")
            locators = claim.get("locators")
            if not isinstance(locators, list) or not locators:
                _fail(f"{cid}.{criterion}: at least one precise source locator is required")
            for locator_index, locator in enumerate(locators):
                _validate_locator(
                    locator,
                    source_bytes,
                    f"{cid}.{criterion}.locators[{locator_index}]",
                )

            if criterion in COUNT_CRITERIA:
                count = claim.get("actual_count")
                if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                    _fail(f"{cid}.{criterion}: actual_count must be a non-negative integer")
                if criterion == "minimum_concurrent_process_target_candidates" and count != packet_target_count:
                    _fail(f"{cid}.{criterion}: actual_count differs from opaque packet")
                recomputed = count >= COUNT_CRITERIA[criterion]
            elif criterion == EXCLUSION_CRITERION:
                recomputed = not bool(set(normalized_aliases) & excluded_set)
            else:
                recomputed = claimed
            if claimed is not recomputed:
                _fail(f"{cid}.{criterion}: claim disagrees with independently recomputed result")
            recomputed_claims[criterion] = recomputed
            per_claim_hashes[criterion] = _sha_file(claim_path)

        computed_eligible = all(recomputed_claims.values())
        if screen_row.get("eligible") is not computed_eligible:
            _fail(f"{cid}: eligible flag disagrees with evidence-backed criteria")
        if computed_eligible:
            eligible.append(cid)
        assert source_ref_canonical is not None
        source_hashes[cid] = str(source_ref_canonical["sha256"])
        claim_hashes[cid] = per_claim_hashes

    minimum = int(selection["minimum_eligible_candidates"])
    if len(eligible) < minimum:
        _fail(f"HARNESS_INCOMPLETE: only {len(eligible)} eligible candidates, need {minimum}")

    result = {
        "status": "PASS",
        "screening_manifest_sha256": _sha_file(screening_path),
        "screening_evidence_index_sha256": _sha_file(evidence_index_path),
        "candidate_count": len(expected_ids),
        "eligible_candidate_count": len(eligible),
        "eligible_candidate_ids": eligible,
        "candidate_source_sha256": source_hashes,
        "candidate_identity_response_sha256": identity_hashes,
        "opaque_concurrent_process_candidate_packet_sha256": complexity_packet_hashes,
        "criterion_evidence_sha256": claim_hashes,
    }
    result["validation_payload_sha256"] = _sha_bytes(_canonical_bytes(result))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--search-snapshot", type=Path, required=True)
    parser.add_argument("--screening", type=Path, required=True)
    parser.add_argument("--exclusions", type=Path, required=True)
    parser.add_argument("--evidence-index", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = validate_case_screening(
            study_root=args.study_root,
            protocol_path=args.protocol,
            search_snapshot_path=args.search_snapshot,
            screening_path=args.screening,
            exclusions_path=args.exclusions,
            evidence_index_path=args.evidence_index,
        )
    except (ScreeningValidationError, OSError) as exc:
        print(json.dumps({"status": "HARNESS_INCOMPLETE", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
