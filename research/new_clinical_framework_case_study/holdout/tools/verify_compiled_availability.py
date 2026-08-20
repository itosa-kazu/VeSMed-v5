#!/usr/bin/env python3
"""Fresh-replay the frozen availability compiler and emit a sealed-tool proof.

This verifier performs no clinical interpretation.  It binds one raw timing-
assertion ledger to one deterministic compiled availability artifact, reruns
the exact compiler in a fresh offline subprocess, and requires exact bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence

from producer_replay_verifier import (
    ADAPTER_ID,
    COMPARISON_MODE,
    POLICY_SCHEMA_VERSION,
    ProducerReplayError,
    build_invocation_descriptor,
    canonical_json_bytes,
    invocation_sha256,
    verify_automated_producer_replay,
)


PROOF_VERSION = "NCF-AVAILABILITY-COMPILER-PROOF-1.0.0"
PRODUCER_ID = "availability-epoch-compiler-v1"
COMPILER_REL = "holdout/tools/compile_availability_epochs.py"
VERIFIER_REL = "holdout/tools/verify_compiled_availability.py"
FROZEN_ASSETS = (
    COMPILER_REL,
    "holdout/tools/test_compile_availability_epochs.py",
    "holdout/schemas/primary_availability_ledger.schema.json",
    "holdout/schemas/compiled_guaranteed_availability.schema.json",
    VERIFIER_REL,
    "holdout/tools/test_verify_compiled_availability.py",
    "holdout/schemas/availability_compiler_proof.schema.json",
    "holdout/tools/producer_replay_verifier.py",
)


class VerificationError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise VerificationError(message)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _resolve(root: Path, path: Path, label: str) -> tuple[Path, bytes]:
    root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        _fail(f"{label} escapes study root")
    cursor = root
    for part in rel.parts:
        cursor /= part
        if cursor.is_symlink():
            _fail(f"{label} contains symlink")
    if not resolved.is_file():
        _fail(f"{label} is not a file")
    return resolved, resolved.read_bytes()


def _ref(root: Path, path: Path) -> dict[str, Any]:
    resolved, raw = _resolve(root, path, "artifact")
    return {"path": resolved.relative_to(root).as_posix(), "sha256": _sha(raw), "bytes": len(raw)}


def _load(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not UTF-8 JSON: {exc}")
    if not isinstance(value, dict):
        _fail(f"{label} must be an object")
    return value


def _artifact_rows(value: Any) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if {"path", "sha256", "bytes"}.issubset(value):
            rows.append(value)
        for child in value.values():
            rows.extend(_artifact_rows(child))
    elif isinstance(value, list):
        for child in value:
            rows.extend(_artifact_rows(child))
    return rows


def _verify_seal(root: Path, seal_path: Path) -> tuple[dict[str, Any], str]:
    _, raw = _resolve(root, seal_path, "combined preprimary seal")
    seal = _load(raw, "combined preprimary seal")
    digest = seal.get("payload_sha256")
    unsigned = dict(seal)
    unsigned.pop("payload_sha256", None)
    if (
        seal.get("status") != "SEALED_BEFORE_PRIMARY_CASE_SELECTION"
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or _sha(canonical_json_bytes(unsigned)) != digest
    ):
        _fail("combined preprimary seal is invalid")
    inventory = {
        row["path"]: row
        for row in _artifact_rows(seal.get("bindings"))
        if isinstance(row.get("path"), str)
    }
    for rel in FROZEN_ASSETS:
        row = inventory.get(rel)
        if row is None:
            _fail(f"combined seal omits frozen availability asset: {rel}")
        actual = _ref(root, root / Path(*PurePosixPath(rel).parts))
        if row.get("sha256") != actual["sha256"] or row.get("bytes") != actual["bytes"]:
            _fail(f"frozen availability asset drift: {rel}")
    return seal, digest


def verify(
    study_root: Path,
    source_ledger_path: Path,
    compiled_output_path: Path,
    combined_seal_path: Path,
) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    source_path, source_raw = _resolve(root, source_ledger_path, "source availability ledger")
    output_path, output_raw = _resolve(root, compiled_output_path, "compiled availability")
    source_value = _load(source_raw, "source availability ledger")
    output_value = _load(output_raw, "compiled availability")
    _, seal_digest = _verify_seal(root, combined_seal_path)
    if source_value.get("schema_version") != "ncf.primary-availability-ledger.v1":
        _fail("source availability schema_version mismatch")
    if output_value.get("schema_version") != "ncf.compiled-guaranteed-availability.v1":
        _fail("compiled availability schema_version mismatch")
    if output_value.get("source_ledger_canonical_sha256") != _sha(canonical_json_bytes(source_value)):
        _fail("compiled availability does not bind source ledger")

    compiler_path = root / Path(*PurePosixPath(COMPILER_REL).parts)
    tool_ref = _ref(root, compiler_path)
    input_ref = {"ref_id": "availability_input", **_ref(root, source_path)}
    output_ref = {"ref_id": "availability_output", **_ref(root, output_path)}
    refs = {"availability_input": input_ref, "availability_output": output_ref}
    paths = {"availability_input": source_path, "availability_output": output_path}
    values = {"availability_input": source_value, "availability_output": output_value}
    policy = {
        "schema_version": POLICY_SCHEMA_VERSION,
        "adapter_id": ADAPTER_ID,
        "argv_template": ["--input", "{input:availability}", "--output", "{output}"],
        "required_input_slots": {
            "availability": {"json_schema_versions": ["ncf.primary-availability-ledger.v1"]}
        },
        "check_arg_contract": {},
        "output_contract": {
            "mode": "SINGLE_FILE",
            "json_schema_versions": ["ncf.compiled-guaranteed-availability.v1"],
        },
        "timeout_seconds": 60,
        "working_directory": "STUDY_ROOT",
        "network_policy": "APPLICATION_SOCKET_GUARD_OFFLINE",
        "comparison": COMPARISON_MODE,
    }
    claim: dict[str, Any] = {
        "adapter_id": ADAPTER_ID,
        "input_ref_ids": {"availability": "availability_input"},
        "check_args": {},
        "invocation_sha256": "0" * 64,
    }
    descriptor = build_invocation_descriptor(
        producer_id=PRODUCER_ID,
        tool_ref=tool_ref,
        replay_policy=policy,
        replay_claim=claim,
        source_refs=refs,
        output_ref_id="availability_output",
    )
    claim["invocation_sha256"] = invocation_sha256(descriptor)
    replay = verify_automated_producer_replay(
        study_root=root,
        producer_id=PRODUCER_ID,
        tool_ref=tool_ref,
        tool_path=compiler_path,
        replay_policy=policy,
        replay_claim=claim,
        source_refs=refs,
        source_paths=paths,
        source_values=values,
        output_ref_id="availability_output",
    ).to_dict()
    return {
        "schema_version": PROOF_VERSION,
        "status": "PASS",
        "producer_id": PRODUCER_ID,
        "source_ledger": _ref(root, source_path),
        "compiled_output": _ref(root, output_path),
        "compiler": tool_ref,
        "verifier": _ref(root, root / Path(*PurePosixPath(VERIFIER_REL).parts)),
        "combined_preprimary_seal_payload_sha256": seal_digest,
        "invocation_sha256": claim["invocation_sha256"],
        "fresh_replay": replay,
    }


def _write(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        _fail(f"refusing to overwrite proof: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", required=True, type=Path)
    parser.add_argument("--source-ledger", required=True, type=Path)
    parser.add_argument("--compiled-output", required=True, type=Path)
    parser.add_argument("--combined-seal", required=True, type=Path)
    parser.add_argument("--output-proof", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        proof = verify(
            args.study_root,
            args.source_ledger,
            args.compiled_output,
            args.combined_seal,
        )
        _write(args.output_proof, proof)
        print(json.dumps({"status": "PASS", "invocation_sha256": proof["invocation_sha256"]}, sort_keys=True))
        return 0
    except (VerificationError, ProducerReplayError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL_CLOSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
