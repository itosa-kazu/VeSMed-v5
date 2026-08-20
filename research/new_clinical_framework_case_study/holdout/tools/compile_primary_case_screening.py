#!/usr/bin/env python3
"""Compile adjudicator claims into the frozen primary-case screening chain.

This tool is deliberately mechanical and offline.  It does not search, read a
case semantically, or decide whether a medical eligibility criterion is true.
An upstream adjudicator supplies every criterion judgment plus exact byte
locators.  The compiler validates immutable bindings, recomputable counts,
identity/exclusion closure, and the opaque concurrent-process packet, then
materializes the write-once claim files, ``PRIMARY_CASE_SCREENING.json``, and
``PRIMARY_SCREENING_EVIDENCE_INDEX.json``.

The distinction is intentional: medical judgment belongs to the adjudicator;
this program is evidence machinery.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence

try:
    from .compile_opaque_concurrent_process_candidates import (
        ComplexityPacketError,
        validate_packet,
    )
    from .validate_primary_case_screening import (
        CLAIM_ROOT,
        CLAIM_VERSION,
        COMPLEXITY_PACKET_ROOT,
        COUNT_CRITERIA,
        EXCLUSION_CRITERION,
        IDENTITY_ROOT,
        INDEX_VERSION,
        PROTOCOL_ELIGIBILITY,
        SCREENING_VERSION,
        ScreeningValidationError,
        SOURCE_ROOT,
        _expected_claim_name,
        _expected_complexity_packet_name,
        _expected_identity_name,
        _expected_source_name,
        _load_object,
        _normalize_identity,
        _parse_ncbi_identity_response,
        _strict_keys,
        _validate_artifact_ref,
        _validate_locator,
        validate_case_screening,
    )
except ImportError:  # direct discovery from holdout/tools
    from compile_opaque_concurrent_process_candidates import (
        ComplexityPacketError,
        validate_packet,
    )
    from validate_primary_case_screening import (
        CLAIM_ROOT,
        CLAIM_VERSION,
        COMPLEXITY_PACKET_ROOT,
        COUNT_CRITERIA,
        EXCLUSION_CRITERION,
        IDENTITY_ROOT,
        INDEX_VERSION,
        PROTOCOL_ELIGIBILITY,
        SCREENING_VERSION,
        ScreeningValidationError,
        SOURCE_ROOT,
        _expected_claim_name,
        _expected_complexity_packet_name,
        _expected_identity_name,
        _expected_source_name,
        _load_object,
        _normalize_identity,
        _parse_ncbi_identity_response,
        _strict_keys,
        _validate_artifact_ref,
        _validate_locator,
        validate_case_screening,
    )


INPUT_VERSION = "NCF-PRIMARY-CASE-SCREENING-COMPILER-INPUT-1.0.0"
SCREENING_REL = PurePosixPath("holdout/evidence/PRIMARY_CASE_SCREENING.json")
INDEX_REL = PurePosixPath("holdout/evidence/PRIMARY_SCREENING_EVIDENCE_INDEX.json")


class ScreeningCompilationError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise ScreeningCompilationError(message)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact_ref(study_root: Path, path: Path) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        rel = resolved.relative_to(root).as_posix()
    except ValueError:
        _fail(f"artifact outside study root: {path}")
    raw = resolved.read_bytes()
    return {"path": rel, "sha256": _sha_bytes(raw), "bytes": len(raw)}


def _assert_output_target(study_root: Path, path: Path, expected: PurePosixPath, label: str) -> None:
    root = study_root.resolve(strict=True)
    if path.is_symlink():
        _fail(f"{label} must not be a symlink")
    candidate = path.absolute()
    try:
        rel = candidate.relative_to(root).as_posix()
    except ValueError:
        _fail(f"{label} must be inside study root")
    if rel != expected.as_posix():
        _fail(f"{label} must be {expected.as_posix()}")
    cursor = candidate.parent
    while cursor != root:
        if cursor.is_symlink():
            _fail(f"{label} parent must not be a symlink")
        if root not in cursor.parents:
            _fail(f"{label} escapes study root")
        cursor = cursor.parent


def _atomic_write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        _fail(f"write-once output already exists: {path}")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(tmp, path)
        except FileExistsError:
            _fail(f"write-once output already exists: {path}")
    finally:
        tmp.unlink(missing_ok=True)


def _load_input(path: Path) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        _fail(f"compiler input missing or symlink: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid compiler input: {exc}")
    if not isinstance(value, Mapping):
        _fail("compiler input must be a JSON object")
    return value


def _prepare(
    *, study_root: Path, compiler_input_path: Path
) -> tuple[
    Path,
    Path,
    Path,
    list[tuple[Path, bytes]],
    Mapping[str, Any],
    list[Mapping[str, Any]],
]:
    root = study_root.resolve(strict=True)
    payload = _load_input(compiler_input_path)
    _strict_keys(
        payload,
        {
            "schema_version",
            "protocol_ref",
            "search_snapshot_ref",
            "exclusions_ref",
            "candidates",
        },
        "screening compiler input",
    )
    if payload.get("schema_version") != INPUT_VERSION:
        _fail("screening compiler input schema_version mismatch")

    protocol_path = _validate_artifact_ref(
        study_root=root, ref=payload.get("protocol_ref"), label="compiler input protocol"
    )
    search_path = _validate_artifact_ref(
        study_root=root,
        ref=payload.get("search_snapshot_ref"),
        label="compiler input search snapshot",
    )
    exclusions_path = _validate_artifact_ref(
        study_root=root, ref=payload.get("exclusions_ref"), label="compiler input exclusions"
    )
    protocol = _load_object(protocol_path, "execution protocol")
    selection = protocol.get("selection")
    if not isinstance(selection, Mapping) or selection.get("eligibility") != PROTOCOL_ELIGIBILITY:
        _fail("execution protocol eligibility contract differs from frozen semantics")
    if selection.get("minimum_eligible_candidates") != 3:
        _fail("frozen minimum eligible candidate count must equal 3")

    snapshot = _load_object(search_path, "search snapshot")
    expected_ids = snapshot.get("canonical_case_ids")
    if (
        not isinstance(expected_ids, list)
        or any(not isinstance(item, str) or not item for item in expected_ids)
        or len(expected_ids) != len(set(expected_ids))
    ):
        _fail("search snapshot canonical_case_ids invalid or duplicated")
    exclusions = _strict_keys(
        _load_object(exclusions_path, "identifier-only exclusions"),
        {"schema_version", "exclusion_set_id", "excluded_case_ids"},
        "identifier-only exclusions",
    )
    excluded_ids = exclusions.get("excluded_case_ids")
    if (
        not isinstance(excluded_ids, list)
        or any(not isinstance(item, str) or not item for item in excluded_ids)
        or len(excluded_ids) != len(set(excluded_ids))
    ):
        _fail("excluded_case_ids invalid or duplicated")
    excluded_set = {
        _normalize_identity(item, f"excluded_case_ids[{index}]")
        for index, item in enumerate(excluded_ids)
    }

    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != len(expected_ids):
        _fail("compiler input candidate count differs from complete search universe")
    if [row.get("canonical_case_id") for row in candidates if isinstance(row, Mapping)] != expected_ids:
        _fail("compiler input candidates must equal exact search universe and order")

    claim_outputs: list[tuple[Path, bytes]] = []
    screen_rows: list[Mapping[str, Any]] = []
    index_rows: list[Mapping[str, Any]] = []
    alias_owner: dict[str, str] = {}
    eligible_count = 0
    for candidate_index, untyped_row in enumerate(candidates):
        row = _strict_keys(
            untyped_row,
            {
                "canonical_case_id",
                "source_artifact_ref",
                "identity_aliases",
                "opaque_concurrent_process_candidate_packet_ref",
                "criteria",
                "screening_notes",
            },
            f"compiler input candidates[{candidate_index}]",
        )
        cid = row.get("canonical_case_id")
        assert isinstance(cid, str)
        if not isinstance(row.get("screening_notes"), str):
            _fail(f"{cid}: screening_notes must be a string")

        source_ref = row.get("source_artifact_ref")
        source_path = _validate_artifact_ref(
            study_root=root,
            ref=source_ref,
            label=f"{cid} immutable candidate source",
            required_parent=SOURCE_ROOT,
            required_name=_expected_source_name(cid),
        )
        source_bytes = source_path.read_bytes()
        if not source_bytes:
            _fail(f"{cid}: immutable candidate source is empty")

        packet_ref = row.get("opaque_concurrent_process_candidate_packet_ref")
        packet_path = _validate_artifact_ref(
            study_root=root,
            ref=packet_ref,
            label=f"{cid} opaque concurrent-process candidate packet",
            required_parent=COMPLEXITY_PACKET_ROOT,
            required_name=_expected_complexity_packet_name(cid),
        )
        try:
            packet_validation = validate_packet(study_root=root, packet_path=packet_path)
        except ComplexityPacketError as exc:
            _fail(f"{cid}: invalid opaque concurrent-process candidate packet: {exc}")
        packet = _load_object(packet_path, f"{cid} opaque concurrent-process candidate packet")
        if packet.get("canonical_case_id") != cid:
            _fail(f"{cid}: complexity packet canonical_case_id mismatch")
        target_count = packet_validation.get("target_count")
        if not isinstance(target_count, int) or isinstance(target_count, bool):
            _fail(f"{cid}: complexity packet target_count invalid")

        identity = _strict_keys(
            row.get("identity_aliases"),
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
        identity_bytes = identity_path.read_bytes()
        identity_raw = _load_object(identity_path, f"{cid} raw NCBI identity response")
        parsed_aliases = _parse_ncbi_identity_response(identity_raw, cid)
        aliases = identity.get("aliases")
        if (
            not isinstance(aliases, list)
            or any(not isinstance(item, str) for item in aliases)
            or len(aliases) != len(set(aliases))
        ):
            _fail(f"{cid}: identity aliases invalid or duplicated")
        normalized_aliases = [
            _normalize_identity(item, f"{cid}.identity_aliases[{index}]")
            for index, item in enumerate(aliases)
        ]
        if normalized_aliases != aliases or normalized_aliases != parsed_aliases:
            _fail(f"{cid}: claimed identity aliases differ from raw NCBI identity response")
        source_document_id = _normalize_identity(
            identity.get("source_document_id"), f"{cid}.source_document_id"
        )
        if source_document_id not in normalized_aliases:
            _fail(f"{cid}: source_document_id is not an NCBI-backed alias")
        identity_locators = identity.get("locators")
        if not isinstance(identity_locators, list) or not identity_locators:
            _fail(f"{cid}: raw identity response requires a precise locator")
        for locator_index, locator in enumerate(identity_locators):
            _validate_locator(locator, identity_bytes, f"{cid}.identity_aliases.locators[{locator_index}]")
        for alias in normalized_aliases:
            prior = alias_owner.get(alias)
            if prior is not None and prior != cid:
                _fail(f"{cid}: duplicate article identity alias {alias} already belongs to {prior}")
            alias_owner[alias] = cid

        criterion_rows = row.get("criteria")
        if not isinstance(criterion_rows, list) or len(criterion_rows) != len(PROTOCOL_ELIGIBILITY):
            _fail(f"{cid}: criteria must contain exactly one row per criterion")
        if [item.get("criterion_id") for item in criterion_rows if isinstance(item, Mapping)] != list(PROTOCOL_ELIGIBILITY):
            _fail(f"{cid}: criteria must follow exact frozen criterion order")

        criteria_map: dict[str, bool] = {}
        criterion_index_rows: list[Mapping[str, Any]] = []
        for criterion_index, untyped_criterion in enumerate(criterion_rows):
            criterion = untyped_criterion.get("criterion_id")
            assert isinstance(criterion, str)
            allowed = {"criterion_id", "claimed_result", "locators"}
            if criterion in COUNT_CRITERIA:
                allowed.add("actual_count")
            criterion_row = _strict_keys(
                untyped_criterion,
                allowed,
                f"{cid}.criteria[{criterion_index}]",
            )
            claimed = criterion_row.get("claimed_result")
            if not isinstance(claimed, bool):
                _fail(f"{cid}.{criterion}: claimed_result must be boolean")
            locators = criterion_row.get("locators")
            if not isinstance(locators, list) or not locators:
                _fail(f"{cid}.{criterion}: at least one source locator is required")
            for locator_index, locator in enumerate(locators):
                _validate_locator(locator, source_bytes, f"{cid}.{criterion}.locators[{locator_index}]")

            if criterion in COUNT_CRITERIA:
                actual_count = criterion_row.get("actual_count")
                if (
                    not isinstance(actual_count, int)
                    or isinstance(actual_count, bool)
                    or actual_count < 0
                ):
                    _fail(f"{cid}.{criterion}: actual_count must be a non-negative integer")
                if criterion == "minimum_concurrent_process_target_candidates" and actual_count != target_count:
                    _fail(f"{cid}.{criterion}: actual_count differs from opaque packet")
                recomputed = actual_count >= COUNT_CRITERIA[criterion]
            elif criterion == EXCLUSION_CRITERION:
                recomputed = not bool(set(normalized_aliases) & excluded_set)
            else:
                recomputed = claimed
            if claimed is not recomputed:
                _fail(f"{cid}.{criterion}: claimed result disagrees with mechanical recomputation")
            if criterion == "open_full_text_snapshot_required" and claimed and not source_document_id.startswith("PMCID:"):
                _fail(f"{cid}: open-full-text claim requires a PMCID source_document_id")

            claim: dict[str, Any] = {
                "schema_version": CLAIM_VERSION,
                "canonical_case_id": cid,
                "criterion_id": criterion,
                "claimed_result": claimed,
                "source_artifact_ref": source_ref,
                "locators": locators,
            }
            if criterion in COUNT_CRITERIA:
                claim["actual_count"] = criterion_row["actual_count"]
            claim_path = root / Path(*CLAIM_ROOT.parts) / _expected_claim_name(cid, criterion)
            claim_raw = _canonical_bytes(claim)
            claim_outputs.append((claim_path, claim_raw))
            claim_ref = {
                "path": claim_path.relative_to(root).as_posix(),
                "sha256": _sha_bytes(claim_raw),
                "bytes": len(claim_raw),
            }
            criterion_index_rows.append({"criterion_id": criterion, "evidence_ref": claim_ref})
            criteria_map[criterion] = claimed

        eligible = all(criteria_map.values())
        if eligible:
            eligible_count += 1
        screen_rows.append(
            {
                "canonical_case_id": cid,
                "eligible": eligible,
                "criteria": criteria_map,
                "source_locator": source_ref["path"],
                "opaque_concurrent_process_candidate_packet_ref": packet_ref,
                "screening_notes": row["screening_notes"],
            }
        )
        index_rows.append(
            {
                "canonical_case_id": cid,
                "identity_aliases": identity,
                "opaque_concurrent_process_candidate_packet_ref": packet_ref,
                "criterion_evidence": criterion_index_rows,
            }
        )

    if eligible_count < 3:
        _fail(f"HARNESS_INCOMPLETE: only {eligible_count} eligible candidates, need 3")
    screening = {
        "schema_version": SCREENING_VERSION,
        "search_snapshot_sha256": _artifact_ref(root, search_path)["sha256"],
        "candidates": screen_rows,
    }
    return protocol_path, search_path, exclusions_path, claim_outputs, screening, index_rows


def compile_screening(
    *,
    study_root: Path,
    compiler_input_path: Path,
    screening_output_path: Path,
    evidence_index_output_path: Path,
) -> dict[str, Any]:
    """Compile a complete write-once chain and validate the emitted artifacts."""

    root = study_root.resolve(strict=True)
    _assert_output_target(root, screening_output_path, SCREENING_REL, "screening output")
    _assert_output_target(root, evidence_index_output_path, INDEX_REL, "evidence index output")
    (
        protocol_path,
        search_path,
        exclusions_path,
        claim_outputs,
        screening,
        index_rows,
    ) = _prepare(study_root=root, compiler_input_path=compiler_input_path)

    planned_paths = [path for path, _ in claim_outputs] + [
        screening_output_path,
        evidence_index_output_path,
    ]
    if len(planned_paths) != len(set(planned_paths)):
        _fail("compiler planned duplicate output paths")
    existing = [str(path) for path in planned_paths if path.exists() or path.is_symlink()]
    if existing:
        _fail("write-once output already exists: " + ", ".join(existing))

    for claim_path, claim_raw in claim_outputs:
        _atomic_write_once(claim_path, claim_raw)
    screening_raw = _canonical_bytes(screening)
    _atomic_write_once(screening_output_path, screening_raw)
    index = {
        "schema_version": INDEX_VERSION,
        "protocol_ref": _artifact_ref(root, protocol_path),
        "search_snapshot_ref": _artifact_ref(root, search_path),
        "screening_manifest_ref": _artifact_ref(root, screening_output_path),
        "exclusions_ref": _artifact_ref(root, exclusions_path),
        "candidates": index_rows,
    }
    index_raw = _canonical_bytes(index)
    _atomic_write_once(evidence_index_output_path, index_raw)

    validation = validate_case_screening(
        study_root=root,
        protocol_path=protocol_path,
        search_snapshot_path=search_path,
        screening_path=screening_output_path,
        exclusions_path=exclusions_path,
        evidence_index_path=evidence_index_output_path,
    )
    result = {
        "status": "PASS",
        "compiler_input_sha256": _sha_bytes(compiler_input_path.read_bytes()),
        "screening_manifest_ref": _artifact_ref(root, screening_output_path),
        "screening_evidence_index_ref": _artifact_ref(root, evidence_index_output_path),
        "criterion_claim_count": len(claim_outputs),
        "eligible_candidate_ids": validation["eligible_candidate_ids"],
        "validation_payload_sha256": validation["validation_payload_sha256"],
    }
    result["compilation_payload_sha256"] = _sha_bytes(_canonical_bytes(result))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--compiler-input", type=Path, required=True)
    parser.add_argument("--screening-output", type=Path, required=True)
    parser.add_argument("--evidence-index-output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = compile_screening(
            study_root=args.study_root,
            compiler_input_path=args.compiler_input,
            screening_output_path=args.screening_output,
            evidence_index_output_path=args.evidence_index_output,
        )
    except (ScreeningCompilationError, ScreeningValidationError, OSError) as exc:
        print(json.dumps({"status": "HARNESS_INCOMPLETE", "error": str(exc)}, indent=2))
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
