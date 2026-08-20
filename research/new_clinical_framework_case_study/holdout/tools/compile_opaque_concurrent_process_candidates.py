#!/usr/bin/env python3
"""Compile and verify diagnosis-name-free concurrent-process eligibility packets.

The compiler deliberately has no model, runtime, oracle, diagnosis, outcome or
network input.  It accepts only source-bound, opaque candidate claims and emits
deterministic opaque process ids plus content-addressed source assertions.
Clinical truth remains a human/source-audit responsibility; this program proves
the packet's structure, coactivity, independent evidence and non-drift.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence


CLAIMS_VERSION = "NCF-OPAQUE-CONCURRENT-PROCESS-CANDIDATE-CLAIMS-1.0.0"
PACKET_VERSION = "NCF-OPAQUE-CONCURRENT-PROCESS-CANDIDATE-PACKET-1.0.0"
PRODUCED_BY = "holdout/tools/compile_opaque_concurrent_process_candidates.py"
MINIMUM_TARGETS = 2
SOURCE_ROOT = PurePosixPath("holdout/evidence/primary_screening_sources")
CLAIMS_ROOT = PurePosixPath("holdout/evidence/primary_complexity_candidates/claims")
PACKETS_ROOT = PurePosixPath("holdout/evidence/primary_complexity_candidates/packets")
DISTINCTNESS_BASES = {
    "DISTINCT_LOCAL_DOMAIN",
    "INDEPENDENT_ACTION_RESPONSE",
    "INDEPENDENT_TRAJECTORY",
}


class ComplexityPacketError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise ComplexityPacketError(message)


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _artifact_ref(path: Path, root: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha_bytes(path.read_bytes()),
        "bytes": path.stat().st_size,
    }


def _strict(value: Any, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        _fail(f"{label} must contain exactly {sorted(keys)}")
    return value


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


def _safe_existing_file(
    root: Path,
    path_text: Any,
    *,
    label: str,
    required_parent: PurePosixPath | None = None,
) -> Path:
    if not isinstance(path_text, str) or not path_text:
        _fail(f"{label} path missing")
    rel = PurePosixPath(path_text)
    if rel.is_absolute() or ".." in rel.parts or rel.as_posix() != path_text:
        _fail(f"{label} path is not canonical")
    if required_parent is not None and (
        len(rel.parts) != len(required_parent.parts) + 1
        or rel.parts[: len(required_parent.parts)] != required_parent.parts
    ):
        _fail(f"{label} must be directly under {required_parent.as_posix()}")
    resolved_root = root.resolve(strict=True)
    candidate = resolved_root / Path(*rel.parts)
    cursor = candidate
    while cursor != resolved_root:
        if cursor.is_symlink():
            _fail(f"{label} path contains a symlink")
        if resolved_root not in cursor.parents and cursor != resolved_root:
            _fail(f"{label} escapes study root")
        cursor = cursor.parent
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (FileNotFoundError, ValueError):
        _fail(f"{label} missing or escapes study root")
    if not resolved.is_file():
        _fail(f"{label} is not a file")
    return resolved


def _validate_ref(
    root: Path,
    ref: Any,
    *,
    label: str,
    required_parent: PurePosixPath | None = None,
) -> tuple[dict[str, Any], Path]:
    row = _strict(ref, {"path", "sha256", "bytes"}, label)
    path = _safe_existing_file(
        root, row.get("path"), label=label, required_parent=required_parent
    )
    expected = _artifact_ref(path, root.resolve(strict=True))
    if dict(row) != expected:
        _fail(f"{label} content reference mismatch")
    return expected, path


def _validate_locator(locator: Any, source_bytes: bytes, label: str) -> dict[str, Any]:
    row = _strict(locator, {"byte_start", "byte_end", "excerpt_sha256"}, label)
    start, end, digest = row.get("byte_start"), row.get("byte_end"), row.get("excerpt_sha256")
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
    if not isinstance(digest, str) or digest != _sha_bytes(source_bytes[start:end]):
        _fail(f"{label} excerpt hash mismatch")
    return {"byte_start": start, "byte_end": end, "excerpt_sha256": digest}


def _opaque_id(prefix: str, seed: Any) -> str:
    return f"{prefix}-{_sha_bytes(_canonical_bytes(seed))[:24]}"


def compile_claims(*, study_root: Path, claims_path: Path) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    try:
        rel_claims = claims_path.resolve(strict=True).relative_to(root).as_posix()
    except (FileNotFoundError, ValueError):
        _fail("claims path must be an existing file inside study root")
    claims_file = _safe_existing_file(
        root, rel_claims, label="claims", required_parent=CLAIMS_ROOT
    )
    claims = _load_object(claims_file, "complexity claims")
    _strict(
        claims,
        {
            "schema_version",
            "canonical_case_id",
            "terminal_verification_epoch_index",
            "model_blind",
            "disease_name_used",
            "process_candidates",
            "pairwise_distinctness_witnesses",
        },
        "complexity claims",
    )
    if claims.get("schema_version") != CLAIMS_VERSION:
        _fail("claims schema_version mismatch")
    case_id = claims.get("canonical_case_id")
    terminal = claims.get("terminal_verification_epoch_index")
    if not isinstance(case_id, str) or not case_id:
        _fail("canonical_case_id missing")
    if not isinstance(terminal, int) or isinstance(terminal, bool) or terminal < 1:
        _fail("terminal_verification_epoch_index invalid")
    if claims.get("model_blind") is not True or claims.get("disease_name_used") is not False:
        _fail("claims must be model-blind and must not use a disease name")

    raw_candidates = claims.get("process_candidates")
    if not isinstance(raw_candidates, list):
        _fail("process_candidates must be an array")

    claims_ref = _artifact_ref(claims_file, root)
    packet_id = _opaque_id("OCP", claims_ref)
    compiled_candidates: list[dict[str, Any]] = []
    assertion_fingerprints_by_candidate: list[set[tuple[Any, ...]]] = []
    all_source_refs: dict[tuple[str, str, int], dict[str, Any]] = {}

    for index, candidate in enumerate(raw_candidates):
        row = _strict(
            candidate,
            {"active_epoch_indices", "trajectory_witnesses"},
            f"process_candidates[{index}]",
        )
        active = row.get("active_epoch_indices")
        witnesses = row.get("trajectory_witnesses")
        if (
            not isinstance(active, list)
            or not active
            or any(not isinstance(x, int) or isinstance(x, bool) or x < 0 for x in active)
            or active != sorted(set(active))
        ):
            _fail(f"process_candidates[{index}].active_epoch_indices must be sorted unique integers")
        if not isinstance(witnesses, list) or len(witnesses) < 2:
            _fail(f"process_candidates[{index}] needs at least two trajectory witnesses")
        if any(epoch >= terminal for epoch in active):
            _fail(f"process_candidates[{index}] active epochs must be preterminal")

        process_id = _opaque_id("PC", {"packet_id": packet_id, "index": index})
        compiled_witnesses: list[dict[str, Any]] = []
        witness_epochs: set[int] = set()
        fingerprints: set[tuple[Any, ...]] = set()
        for witness_index, witness in enumerate(witnesses):
            witness_row = _strict(
                witness,
                {"epoch_index", "source_artifact_ref", "locator"},
                f"process_candidates[{index}].trajectory_witnesses[{witness_index}]",
            )
            epoch = witness_row.get("epoch_index")
            if (
                not isinstance(epoch, int)
                or isinstance(epoch, bool)
                or epoch < 0
                or epoch >= terminal
                or epoch not in active
            ):
                _fail(f"process_candidates[{index}] witness epoch is not an active preterminal epoch")
            source_ref, source_path = _validate_ref(
                root,
                witness_row.get("source_artifact_ref"),
                label=f"process_candidates[{index}] witness source",
                required_parent=SOURCE_ROOT,
            )
            locator = _validate_locator(
                witness_row.get("locator"),
                source_path.read_bytes(),
                f"process_candidates[{index}] witness locator",
            )
            fingerprint = (
                source_ref["path"],
                locator["byte_start"],
                locator["byte_end"],
                locator["excerpt_sha256"],
            )
            if fingerprint in fingerprints:
                _fail(f"process_candidates[{index}] repeats one source assertion")
            fingerprints.add(fingerprint)
            witness_epochs.add(epoch)
            all_source_refs[(source_ref["path"], source_ref["sha256"], source_ref["bytes"])] = source_ref
            assertion_id = _opaque_id(
                "SA", {"packet_id": packet_id, "process_index": index, "fingerprint": fingerprint}
            )
            compiled_witnesses.append(
                {
                    "assertion_id": assertion_id,
                    "epoch_index": epoch,
                    "source_artifact_ref": source_ref,
                    **locator,
                }
            )
        if len(witness_epochs) < 2:
            _fail(f"process_candidates[{index}] trajectory is not trackable across two epochs")
        compiled_witnesses.sort(key=lambda x: (x["epoch_index"], x["assertion_id"]))
        compiled_candidates.append(
            {
                "opaque_process_candidate_id": process_id,
                "active_epoch_indices": active,
                "trajectory_assertion_refs": compiled_witnesses,
            }
        )
        assertion_fingerprints_by_candidate.append(fingerprints)

    # Every submitted target must be simultaneously active before terminal.
    coactive = (
        sorted(set.intersection(*(set(x["active_epoch_indices"]) for x in compiled_candidates)))
        if compiled_candidates
        else []
    )

    for index, own in enumerate(assertion_fingerprints_by_candidate):
        others = set().union(
            *(s for other_index, s in enumerate(assertion_fingerprints_by_candidate) if other_index != index)
        )
        if not (own - others):
            _fail(f"process_candidates[{index}] has no independent source assertion")

    raw_distinctness = claims.get("pairwise_distinctness_witnesses")
    if not isinstance(raw_distinctness, list):
        _fail("pairwise_distinctness_witnesses must be an array")
    required_pairs = set(itertools.combinations(range(len(compiled_candidates)), 2))
    seen_pairs: set[tuple[int, int]] = set()
    compiled_distinctness: list[dict[str, Any]] = []
    for witness_index, witness in enumerate(raw_distinctness):
        row = _strict(
            witness,
            {"candidate_indices", "basis", "source_artifact_ref", "locator"},
            f"pairwise_distinctness_witnesses[{witness_index}]",
        )
        pair_value = row.get("candidate_indices")
        if (
            not isinstance(pair_value, list)
            or len(pair_value) != 2
            or any(not isinstance(x, int) or isinstance(x, bool) for x in pair_value)
        ):
            _fail("distinctness candidate_indices must contain two integers")
        pair = tuple(sorted(pair_value))
        if pair not in required_pairs or pair in seen_pairs:
            _fail("distinctness pair is invalid, duplicate, or out of range")
        seen_pairs.add(pair)
        basis = row.get("basis")
        if basis not in DISTINCTNESS_BASES:
            _fail("distinctness basis invalid")
        source_ref, source_path = _validate_ref(
            root,
            row.get("source_artifact_ref"),
            label=f"distinctness witness {pair}",
            required_parent=SOURCE_ROOT,
        )
        locator = _validate_locator(
            row.get("locator"), source_path.read_bytes(), f"distinctness witness {pair} locator"
        )
        all_source_refs[(source_ref["path"], source_ref["sha256"], source_ref["bytes"])] = source_ref
        fingerprint = (
            source_ref["path"],
            locator["byte_start"],
            locator["byte_end"],
            locator["excerpt_sha256"],
        )
        assertion_id = _opaque_id("SA", {"packet_id": packet_id, "pair": pair, "fingerprint": fingerprint})
        compiled_distinctness.append(
            {
                "opaque_process_candidate_ids": [
                    compiled_candidates[pair[0]]["opaque_process_candidate_id"],
                    compiled_candidates[pair[1]]["opaque_process_candidate_id"],
                ],
                "basis": basis,
                "source_assertion_ref": {
                    "assertion_id": assertion_id,
                    "epoch_index": coactive[0]
                    if coactive
                    else min(
                        compiled_candidates[pair[0]]["active_epoch_indices"]
                        + compiled_candidates[pair[1]]["active_epoch_indices"]
                    ),
                    "source_artifact_ref": source_ref,
                    **locator,
                },
            }
        )
    if seen_pairs != required_pairs:
        _fail("every candidate pair requires exactly one distinctness witness")
    compiled_distinctness.sort(key=lambda x: x["opaque_process_candidate_ids"])

    return {
        "schema_version": PACKET_VERSION,
        "packet_id": packet_id,
        "canonical_case_id": case_id,
        "input_claims_ref": claims_ref,
        "model_blind": True,
        "disease_name_used": False,
        "terminal_verification_epoch_index": terminal,
        "target_count": len(compiled_candidates) if coactive else 0,
        "minimum_required_target_count": MINIMUM_TARGETS,
        "qualifies": len(compiled_candidates) >= MINIMUM_TARGETS and bool(coactive),
        "process_candidates": compiled_candidates,
        "pairwise_distinctness_witnesses": compiled_distinctness,
        "coactive_preterminal_epoch_indices": coactive,
        "source_artifact_refs": [all_source_refs[key] for key in sorted(all_source_refs)],
        "produced_by": PRODUCED_BY,
    }


def validate_packet(*, study_root: Path, packet_path: Path) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    try:
        rel_packet = packet_path.resolve(strict=True).relative_to(root).as_posix()
    except (FileNotFoundError, ValueError):
        _fail("packet path must be an existing file inside study root")
    packet_file = _safe_existing_file(
        root, rel_packet, label="packet", required_parent=PACKETS_ROOT
    )
    packet = _load_object(packet_file, "complexity packet")
    if packet.get("schema_version") != PACKET_VERSION:
        _fail("packet schema_version mismatch")
    input_ref, claims_path = _validate_ref(
        root,
        packet.get("input_claims_ref"),
        label="packet input claims",
        required_parent=CLAIMS_ROOT,
    )
    expected = compile_claims(study_root=root, claims_path=claims_path)
    if packet != expected:
        _fail("packet does not exactly match deterministic recompilation")
    return {
        "status": "PASS",
        "packet_ref": _artifact_ref(packet_file, root),
        "input_claims_ref": input_ref,
        "target_count": packet["target_count"],
        "coactive_preterminal_epoch_indices": packet["coactive_preterminal_epoch_indices"],
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    compile_parser = sub.add_parser("compile")
    compile_parser.add_argument("--study-root", type=Path, required=True)
    compile_parser.add_argument("--input", type=Path, required=True)
    compile_parser.add_argument("--output", type=Path, required=True)
    validate_parser = sub.add_parser("validate")
    validate_parser.add_argument("--study-root", type=Path, required=True)
    validate_parser.add_argument("--packet", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "compile":
            root = args.study_root.resolve(strict=True)
            expected_output = root / Path(*PACKETS_ROOT.parts) / args.output.name
            if args.output.resolve(strict=False) != expected_output.resolve(strict=False):
                _fail(f"output must be directly under {PACKETS_ROOT.as_posix()}")
            packet = compile_claims(study_root=root, claims_path=args.input)
            _write_json(expected_output, packet)
            print(json.dumps({"status": "PASS", "packet_ref": _artifact_ref(expected_output, root)}, sort_keys=True))
        else:
            print(json.dumps(validate_packet(study_root=args.study_root, packet_path=args.packet), sort_keys=True))
    except (ComplexityPacketError, OSError) as exc:
        print(json.dumps({"status": "HARNESS_INCOMPLETE", "error": str(exc)}, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
