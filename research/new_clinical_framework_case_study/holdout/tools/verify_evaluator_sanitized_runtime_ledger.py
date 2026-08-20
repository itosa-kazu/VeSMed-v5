#!/usr/bin/env python3
"""Fresh-replay the sealed sanitized-ledger compiler and seal both outputs.

This verifier is an upstream provenance check only.  It cannot mint
``PL-LED-001``.  The primary case gate evaluator must independently consume
the source denominator, sanitized ledger, assignment proof, and this exact
verification artifact before it can compute that gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence

from producer_replay_verifier import (
    ADAPTER_ID,
    ProducerReplayError,
    build_invocation_descriptor,
    canonical_json_bytes,
    invocation_sha256,
    sha256_bytes,
    verify_automated_producer_replay,
)


TOOL_REL = "holdout/tools/verify_evaluator_sanitized_runtime_ledger.py"
COMPILER_REL = "holdout/tools/compile_evaluator_sanitized_runtime_ledger.py"
PRODUCER_ID = "evaluator-sanitized-runtime-ledger-compiler-v1"
SCHEMA_VERSION = "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-REPLAY-VERIFICATION-1.0.0"
MANIFEST_SCHEMA_VERSION = "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-COMPILER-INPUT-1.0.0"
LEDGER_SCHEMA_VERSION = "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-1.0.0"
PROOF_SCHEMA_VERSION = "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-ASSIGNMENT-PROOF-1.0.0"

REPLAY_POLICY: Mapping[str, Any] = {
    "schema_version": "ncf.producer-replay-policy.v1",
    "adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
    "argv_template": [
        "compile",
        "--study-root", "{study_root}",
        "--manifest", "{input:input_manifest}",
        "--output-ledger", "{output:ledger}",
        "--assignment-proof", "{output:assignment_proof}",
    ],
    "required_input_slots": {
        "input_manifest": {
            "json_schema_versions": [MANIFEST_SCHEMA_VERSION],
            "materialization": "VERIFIED_ORIGINAL_PATH",
        },
    },
    "check_arg_contract": {},
    "output_contract": {
        "mode": "NAMED_FILES",
        "outputs": {
            "ledger": {
                "artifact_relative_path": "evaluator_sanitized_runtime_ledger.json",
                "json_schema_versions": [LEDGER_SCHEMA_VERSION],
            },
            "assignment_proof": {
                "artifact_relative_path": "evaluator_sanitized_runtime_ledger_assignment_proof.json",
                "json_schema_versions": [PROOF_SCHEMA_VERSION],
            },
        },
    },
    "timeout_seconds": 300,
    "working_directory": "STUDY_ROOT",
    "network_policy": "APPLICATION_SOCKET_GUARD_OFFLINE",
    "comparison": "EXACT_BYTES_AND_CANONICAL_JSON",
}


class SanitizedLedgerReplayError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise SanitizedLedgerReplayError(message)


def _load(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        _fail(f"{label}_missing_or_symlink")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label}_invalid_json:{exc}")
    if not isinstance(value, Mapping):
        _fail(f"{label}_not_object")
    return value


def _relative_ref(root: Path, path: Path, *, ref_id: str | None = None) -> dict[str, Any]:
    root = root.resolve(strict=True)
    resolved = path.resolve(strict=True)
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        _fail("artifact_outside_study_root")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _fail("artifact_symlink_forbidden")
    raw = resolved.read_bytes()
    value: dict[str, Any] = {
        "path": relative.as_posix(),
        "sha256": sha256_bytes(raw),
        "bytes": len(raw),
    }
    return {"ref_id": ref_id, **value} if ref_id is not None else value


def _sealed_ref(row: Any, expected_path: str, label: str) -> Mapping[str, Any]:
    if not isinstance(row, Mapping):
        _fail(f"{label}_binding_missing")
    ref = {key: row.get(key) for key in ("path", "sha256", "bytes")}
    if ref["path"] != expected_path:
        _fail(f"{label}_path_mismatch")
    return ref


def _seal_payload_sha256(seal: Mapping[str, Any]) -> str:
    expected = seal.get("payload_sha256")
    if not isinstance(expected, str):
        _fail("combined_seal_payload_sha256_missing")
    payload = dict(seal)
    payload.pop("payload_sha256", None)
    actual = sha256_bytes(canonical_json_bytes(payload))
    if actual != expected:
        _fail("combined_seal_payload_sha256_mismatch")
    return expected


def build_verification(
    study_root: Path,
    *,
    manifest_path: Path,
    ledger_path: Path,
    assignment_proof_path: Path,
    combined_seal_path: Path,
) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    manifest = _load(manifest_path, "compiler_input_manifest")
    ledger = _load(ledger_path, "sanitized_ledger")
    proof = _load(assignment_proof_path, "assignment_proof")
    seal = _load(combined_seal_path, "combined_preprimary_seal")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        _fail("compiler_input_manifest_schema_mismatch")
    if ledger.get("schema_version") != LEDGER_SCHEMA_VERSION:
        _fail("sanitized_ledger_schema_mismatch")
    if proof.get("schema_version") != PROOF_SCHEMA_VERSION or proof.get("producer_id") != PRODUCER_ID:
        _fail("assignment_proof_identity_mismatch")
    seal_payload_sha = _seal_payload_sha256(seal)
    if proof.get("combined_preprimary_seal_payload_sha256") != seal_payload_sha:
        _fail("assignment_proof_combined_seal_binding_mismatch")
    try:
        execution = seal["bindings"]["primary_execution"]
        compiler_sealed = _sealed_ref(
            execution["evaluator_sanitized_runtime_ledger_compiler"],
            COMPILER_REL,
            "compiler",
        )
        verifier_sealed = _sealed_ref(
            execution["evaluator_sanitized_runtime_ledger_replay_verifier"],
            TOOL_REL,
            "verifier",
        )
    except (KeyError, TypeError):
        _fail("combined_seal_sanitized_ledger_producer_bindings_missing")
    compiler_path = root.joinpath(*PurePosixPath(COMPILER_REL).parts)
    verifier_path = root.joinpath(*PurePosixPath(TOOL_REL).parts)
    compiler_actual = _relative_ref(root, compiler_path)
    verifier_actual = _relative_ref(root, verifier_path)
    if dict(compiler_sealed) != compiler_actual:
        _fail("compiler_differs_from_combined_seal")
    if dict(verifier_sealed) != verifier_actual:
        _fail("verifier_differs_from_combined_seal")

    manifest_ref = _relative_ref(root, manifest_path, ref_id="compiler-input-manifest")
    ledger_ref = _relative_ref(root, ledger_path, ref_id="sanitized-ledger")
    proof_ref = _relative_ref(root, assignment_proof_path, ref_id="assignment-proof")
    source_refs = {
        manifest_ref["ref_id"]: manifest_ref,
        ledger_ref["ref_id"]: ledger_ref,
        proof_ref["ref_id"]: proof_ref,
    }
    source_paths = {
        manifest_ref["ref_id"]: manifest_path,
        ledger_ref["ref_id"]: ledger_path,
        proof_ref["ref_id"]: assignment_proof_path,
    }
    source_values = {
        manifest_ref["ref_id"]: manifest,
        ledger_ref["ref_id"]: ledger,
        proof_ref["ref_id"]: proof,
    }
    replay = {
        "adapter_id": ADAPTER_ID,
        "input_ref_ids": {"input_manifest": manifest_ref["ref_id"]},
        "output_ref_ids": {"ledger": ledger_ref["ref_id"], "assignment_proof": proof_ref["ref_id"]},
        "check_args": {},
        "invocation_sha256": "0" * 64,
    }
    descriptor = build_invocation_descriptor(
        producer_id=PRODUCER_ID,
        tool_ref=compiler_sealed,
        replay_policy=REPLAY_POLICY,
        replay_claim=replay,
        source_refs=source_refs,
    )
    replay["invocation_sha256"] = invocation_sha256(descriptor)
    verified = verify_automated_producer_replay(
        study_root=root,
        producer_id=PRODUCER_ID,
        tool_ref=compiler_sealed,
        tool_path=compiler_path,
        replay_policy=REPLAY_POLICY,
        replay_claim=replay,
        source_refs=source_refs,
        source_paths=source_paths,
        source_values=source_values,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "produced_by": TOOL_REL,
        "producer_id": PRODUCER_ID,
        "status": "PASS",
        "verifier_tool": verifier_actual,
        "compiler_tool": compiler_actual,
        "compiler_input_manifest": {key: manifest_ref[key] for key in ("path", "sha256", "bytes")},
        "compiler_outputs": {
            "ledger": {key: ledger_ref[key] for key in ("path", "sha256", "bytes")},
            "assignment_proof": {key: proof_ref[key] for key in ("path", "sha256", "bytes")},
        },
        "combined_preprimary_seal_payload_sha256": seal_payload_sha,
        "replay_policy_sha256": sha256_bytes(canonical_json_bytes(REPLAY_POLICY)),
        "replay_claim": replay,
        "fresh_replay": verified.to_dict(),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("verify", nargs="?")
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--assignment-proof", type=Path, required=True)
    parser.add_argument("--combined-seal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        value = build_verification(
            args.study_root,
            manifest_path=args.manifest,
            ledger_path=args.ledger,
            assignment_proof_path=args.assignment_proof,
            combined_seal_path=args.combined_seal,
        )
        if args.output.exists():
            _fail("refusing_to_overwrite_verification")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_json_bytes(value) + b"\n")
    except (OSError, KeyError, TypeError, ValueError, ProducerReplayError, SanitizedLedgerReplayError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "PRODUCER_ID",
    "REPLAY_POLICY",
    "SCHEMA_VERSION",
    "SanitizedLedgerReplayError",
    "build_verification",
]
