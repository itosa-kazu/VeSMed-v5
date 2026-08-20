#!/usr/bin/env python3
"""Compile the evaluator's post-replay closure without a role-DAG cycle.

Topology (frozen): six upstream role manifests -> evaluator post-replay receipt
(this input manifest) -> this closure -> evaluator manifest -> scorer/auditor ->
final eight-role manifest set.  The compiler therefore MUST NOT consume either
the evaluator manifest that will contain its output or the later scorer
manifest.  A separate verifier cross-checks those two future artifacts.

The public ``artifacts`` member intentionally remains the exact evaluator
inventory required by the frozen role contract: nine inputs plus the three
declared evaluator outputs.  Broader provenance is bound under
``producer_inputs`` and ``lineage`` and never changes the role-DAG inventory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence


PRODUCER_ID = "post-replay-inventory-compiler-v1"
INPUT_VERSION = "NCF-POST-REPLAY-INVENTORY-COMPILER-INPUT-1.0.0"
OUTPUT_VERSION = "NCF-ALL-SEALED-ARTIFACTS-AFTER-REPLAY-1.0.0"
TOOL_REL = "holdout/tools/compile_all_sealed_artifacts_after_replay.py"
UPSTREAM_ROLES = [
    "scout", "screener", "extractor", "source_auditor",
    "concept_mapper", "oracle_adjudicator",
]
EVALUATOR_INPUT_CLASSES = {
    "evaluator_sanitized_runtime_ledger",
    "sealed_concept_map",
    "model_pack",
    "runtime",
    "scoring_contract",
    "protocol",
    "combined_preprimary_seal",
    "oracle_seal_hash_only",
    "sanitized_id_type_unit_registry",
}
DECLARED_OUTPUT_CLASSES = {
    "runtime_output", "replay_seal", "mapped_observation_consumption",
}
EXECUTOR_CLASSES = {
    "runtime_output": "ncf.data.runtime-output.v1",
    "runtime_event_ledger_replay_bundle": "ncf.holdout.event-ledger-replay-bundle.v1",
    "mapped_observation_consumption": "ncf.mapped-observation-consumption.v1",
    "replay_seal": "ncf.data.replay-seal.v1",
}
SAFE_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class CompileError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise CompileError(message)


def _canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest_rows(rows: Sequence[Mapping[str, Any]]) -> str:
    ordered = sorted(
        ({key: row[key] for key in ("path", "sha256", "bytes", "data_class", "schema_id")} for row in rows),
        key=lambda row: (row["data_class"], row["path"], row["sha256"]),
    )
    return _sha(_canonical_bytes(ordered))


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be an object")
    return value


def _safe_rel(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or not SAFE_PATH.fullmatch(value):
        _fail(f"{label} path is not a safe relative path")
    pure = PurePosixPath(value)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        _fail(f"{label} path escapes the study root")
    return pure.as_posix()


def _resolve(root: Path, rel: str, label: str) -> Path:
    path = root.joinpath(*PurePosixPath(rel).parts)
    if path.is_symlink():
        _fail(f"{label} may not be a symlink")
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError):
        _fail(f"{label} is missing or outside the study root: {rel}")
    cursor = root
    for part in PurePosixPath(rel).parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _fail(f"{label} traverses a symlink: {rel}")
    if not resolved.is_file():
        _fail(f"{label} is not a regular file: {rel}")
    return resolved


def _artifact(root: Path, row_any: Any, label: str) -> tuple[dict[str, Any], bytes]:
    row = _mapping(row_any, label)
    required = {"path", "sha256", "bytes", "data_class", "schema_id"}
    if set(row) - (required | {"role", "run_id"}) or not required.issubset(row):
        _fail(f"{label} artifact fields are not closed")
    rel = _safe_rel(row["path"], label)
    if not isinstance(row["sha256"], str) or not SHA256.fullmatch(row["sha256"]):
        _fail(f"{label} sha256 malformed")
    if isinstance(row["bytes"], bool) or not isinstance(row["bytes"], int) or row["bytes"] < 1:
        _fail(f"{label} bytes malformed")
    if not isinstance(row["data_class"], str) or not row["data_class"]:
        _fail(f"{label} data_class malformed")
    if not isinstance(row["schema_id"], str) or not row["schema_id"]:
        _fail(f"{label} schema_id malformed")
    raw = _resolve(root, rel, label).read_bytes()
    if len(raw) != row["bytes"] or _sha(raw) != row["sha256"]:
        _fail(f"{label} content identity mismatch")
    return {key: row[key] for key in required}, raw


def _json(raw: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        _fail(f"{label} is not UTF-8 JSON: {exc}")
    return _mapping(value, label)


def _identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(row[key] for key in ("path", "sha256", "bytes", "data_class", "schema_id"))


def _validate_input_shape(value: Mapping[str, Any]) -> None:
    required = {
        "schema_version", "producer_id", "evaluator_run_id", "protocol",
        "combined_preprimary_seal", "upstream_role_manifests", "evaluator_inputs",
        "sanitizer", "executor_outputs", "oracle_seal_hash_only",
        "topology_attestations",
    }
    if set(value) != required:
        _fail("compiler input fields do not match the frozen schema")
    if value["schema_version"] != INPUT_VERSION or value["producer_id"] != PRODUCER_ID:
        _fail("compiler input version/producer mismatch")
    run_id = value["evaluator_run_id"]
    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", run_id):
        _fail("evaluator_run_id malformed")
    topology = _mapping(value["topology_attestations"], "topology attestations")
    expected_topology = {
        "six_upstream_manifests_closed_before_compile": True,
        "evaluator_receipt_excludes_closure_self_reference": True,
        "scorer_manifest_not_available_to_compiler": True,
        "final_eight_role_set_verified_only_after_scorer": True,
    }
    if dict(topology) != expected_topology:
        _fail("topology attestations must be exact and all true")


def _validate_upstream_manifests(root: Path, rows_any: Any) -> list[dict[str, Any]]:
    if not isinstance(rows_any, list) or len(rows_any) != 6:
        _fail("exactly six upstream role manifests are required")
    result: list[dict[str, Any]] = []
    documents: dict[str, Mapping[str, Any]] = {}
    for index, expected_role in enumerate(UPSTREAM_ROLES):
        row = _mapping(rows_any[index], f"upstream manifest[{index}]")
        if set(row) != {"role", "run_id", "path", "sha256", "bytes", "data_class", "schema_id"}:
            _fail("upstream role manifest ref fields mismatch")
        if row["role"] != expected_role or row["data_class"] != "role_execution_manifest":
            _fail("upstream role manifests must use frozen order and class")
        if row["schema_id"] != "ncf.primary-role-execution-manifest.v1.1":
            _fail("upstream role manifest schema mismatch")
        artifact, raw = _artifact(root, row, f"upstream role manifest {expected_role}")
        manifest = _json(raw, f"upstream role manifest {expected_role}")
        if manifest.get("schema_version") != "NCF-PRIMARY-ROLE-MANIFEST-1.1.0":
            _fail("upstream role manifest version mismatch")
        if manifest.get("role") != expected_role or manifest.get("run_id") != row["run_id"]:
            _fail("upstream role manifest identity mismatch")
        documents[expected_role] = manifest
        result.append({**artifact, "role": expected_role, "run_id": row["run_id"]})
    # Each manifest is validated against the frozen role/schema/tool-access
    # contract.  Then ROLE_OUTPUT edges are cross-checked against this exact
    # six-manifest prefix; an attestation alone is never accepted as closure.
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from holdout.tools.validate_primary_holdout_protocol import validate_role_manifest
    except Exception as exc:
        _fail(f"frozen role-manifest validator unavailable: {exc}")
    by_role = {row["role"]: row for row in result}
    for row in result:
        report = validate_role_manifest(root, root / row["path"])
        if report.get("status") != "PASS" or report.get("role") != row["role"]:
            _fail(f"upstream role manifest did not validate: {row['role']}")
    for consumer_role, manifest in documents.items():
        for input_row in manifest.get("inputs", []):
            producer = input_row.get("producer", {})
            if producer.get("kind") != "ROLE_OUTPUT":
                continue
            producer_role = producer.get("role")
            if producer_role not in by_role:
                _fail(f"upstream prefix references a future/out-of-prefix role: {consumer_role}->{producer_role}")
            prefix_ref = by_role[producer_role]
            if any(
                producer.get(source_key) != prefix_ref[target_key]
                for source_key, target_key in (
                    ("run_id", "run_id"), ("manifest_path", "path"),
                    ("manifest_sha256", "sha256"), ("manifest_bytes", "bytes"),
                )
            ):
                _fail(f"upstream prefix producer binding mismatch: {producer_role}->{consumer_role}")
    return result


def _validate_executor(root: Path, rows_any: Any) -> tuple[dict[str, dict[str, Any]], Mapping[str, Any]]:
    rows = _mapping(rows_any, "executor outputs")
    if set(rows) != set(EXECUTOR_CLASSES):
        _fail("executor output set must contain exactly four frozen outputs")
    artifacts: dict[str, dict[str, Any]] = {}
    documents: dict[str, Mapping[str, Any]] = {}
    for key, schema_id in EXECUTOR_CLASSES.items():
        artifact, raw = _artifact(root, rows[key], f"executor output {key}")
        if artifact["data_class"] != key or artifact["schema_id"] != schema_id:
            _fail(f"executor output type mismatch: {key}")
        artifacts[key] = artifact
        documents[key] = _json(raw, f"executor output {key}")
    seal = documents["replay_seal"]
    if seal.get("schema_version") != "NCF-PRIMARY-RUNTIME-REPLAY-SEAL-1.0.0":
        _fail("runtime replay seal version mismatch")
    binding_names = {
        "runtime_output": "runtime_output",
        "event_ledger_replay_bundle": "runtime_event_ledger_replay_bundle",
        "mapped_observation_consumption": "mapped_observation_consumption",
    }
    for seal_key, artifact_key in binding_names.items():
        binding = _mapping(seal.get(seal_key), f"replay seal {seal_key}")
        artifact = artifacts[artifact_key]
        expected = {
            "filename": PurePosixPath(artifact["path"]).name,
            "schema_id": artifact["schema_id"],
            "sha256": artifact["sha256"],
            "bytes": artifact["bytes"],
        }
        if dict(binding) != expected:
            _fail(f"replay seal does not bind exact executor output: {seal_key}")
    unsigned = dict(seal)
    payload_hash = unsigned.pop("seal_payload_sha256", None)
    if payload_hash != _digest_value(unsigned):
        _fail("runtime replay seal payload hash mismatch")
    if _digest_artifact_triple(artifacts) != seal.get("artifact_set_digest"):
        _fail("runtime replay seal artifact_set_digest mismatch")
    fresh = _mapping(seal.get("fresh_process_replay"), "runtime fresh replay")
    if fresh.get("status") != "PASS":
        _fail("runtime executor fresh-process replay did not PASS")
    return artifacts, seal


def _digest_value(value: Any) -> str:
    # RuntimeV2's digest is the canonical JSON hash without the trailing file newline.
    return _sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _digest_artifact_triple(artifacts: Mapping[str, Mapping[str, Any]]) -> str:
    rows = [
        {
            "filename": PurePosixPath(artifacts[key]["path"]).name,
            "schema_id": artifacts[key]["schema_id"],
            "sha256": artifacts[key]["sha256"],
            "bytes": artifacts[key]["bytes"],
        }
        for key in ("runtime_output", "runtime_event_ledger_replay_bundle", "mapped_observation_consumption")
    ]
    return _digest_value(rows)


def compile_closure(study_root: Path, input_manifest: Path) -> tuple[dict[str, Any], bytes]:
    root = study_root.resolve(strict=True)
    manifest_path = input_manifest if input_manifest.is_absolute() else root / input_manifest
    try:
        manifest_path = manifest_path.resolve(strict=True)
        manifest_path.relative_to(root)
    except (FileNotFoundError, ValueError):
        _fail("compiler input manifest must be inside the study root")
    if manifest_path.is_symlink():
        _fail("compiler input manifest may not be a symlink")
    manifest_raw = manifest_path.read_bytes()
    value = _json(manifest_raw, "compiler input manifest")
    _validate_input_shape(value)

    protocol, _ = _artifact(root, value["protocol"], "protocol")
    combined, _ = _artifact(root, value["combined_preprimary_seal"], "combined seal")
    if protocol["data_class"] != "protocol" or combined["data_class"] != "combined_preprimary_seal":
        _fail("protocol/combined seal data classes mismatch")
    upstream = _validate_upstream_manifests(root, value["upstream_role_manifests"])

    evaluator_inputs_any = value["evaluator_inputs"]
    if not isinstance(evaluator_inputs_any, list) or len(evaluator_inputs_any) != 9:
        _fail("evaluator input inventory must contain exactly nine artifacts")
    evaluator_inputs: list[dict[str, Any]] = []
    for index, row in enumerate(evaluator_inputs_any):
        artifact, _ = _artifact(root, row, f"evaluator input[{index}]")
        evaluator_inputs.append(artifact)
    by_input_class = {row["data_class"]: row for row in evaluator_inputs}
    if len(by_input_class) != 9 or set(by_input_class) != EVALUATOR_INPUT_CLASSES:
        _fail("evaluator input classes must match the frozen nine-class receipt")
    if _identity(by_input_class["protocol"]) != _identity(protocol):
        _fail("evaluator protocol input differs from compiler protocol")
    if _identity(by_input_class["combined_preprimary_seal"]) != _identity(combined):
        _fail("evaluator combined seal input differs from compiler combined seal")

    sanitizer_any = _mapping(value["sanitizer"], "sanitizer lineage")
    if set(sanitizer_any) != {"ledger", "assignment_proof", "replay_verification"}:
        _fail("sanitizer lineage fields mismatch")
    sanitizer: dict[str, dict[str, Any]] = {}
    expected_sanitizer = {
        "ledger": "evaluator_sanitized_runtime_ledger",
        "assignment_proof": "evaluator_sanitized_runtime_ledger_assignment_proof",
        "replay_verification": "evaluator_sanitized_runtime_ledger_replay_verification",
    }
    sanitizer_docs: dict[str, Mapping[str, Any]] = {}
    for key, data_class in expected_sanitizer.items():
        artifact, raw = _artifact(root, sanitizer_any[key], f"sanitizer {key}")
        if artifact["data_class"] != data_class:
            _fail(f"sanitizer data class mismatch: {key}")
        sanitizer[key] = artifact
        sanitizer_docs[key] = _json(raw, f"sanitizer {key}")
    if _identity(sanitizer["ledger"]) != _identity(by_input_class["evaluator_sanitized_runtime_ledger"]):
        _fail("sanitizer ledger differs from evaluator ledger input")
    proof = sanitizer_docs["assignment_proof"]
    verification = sanitizer_docs["replay_verification"]
    if proof.get("output_ledger", {}).get("sha256") != sanitizer["ledger"]["sha256"]:
        _fail("sanitizer assignment proof does not bind ledger")
    if verification.get("status") != "PASS":
        _fail("sanitizer replay verification did not PASS")
    verification_output = (
        verification.get("compiler_outputs", {}).get("ledger")
        if isinstance(verification.get("compiler_outputs"), Mapping)
        else None
    )
    if isinstance(verification_output, Mapping) and verification_output.get("sha256") != sanitizer["ledger"]["sha256"]:
        _fail("sanitizer replay verification does not bind ledger")

    executor, _ = _validate_executor(root, value["executor_outputs"])
    declared_outputs = [
        executor["runtime_output"], executor["replay_seal"], executor["mapped_observation_consumption"]
    ]
    if {row["data_class"] for row in declared_outputs} != DECLARED_OUTPUT_CLASSES:
        _fail("declared evaluator output classes mismatch")

    oracle, _ = _artifact(root, value["oracle_seal_hash_only"], "oracle seal hash only")
    if oracle["data_class"] != "oracle_seal_hash_only":
        _fail("oracle seal hash-only data class mismatch")
    if _identity(oracle) != _identity(by_input_class["oracle_seal_hash_only"]):
        _fail("oracle seal differs from evaluator input")

    artifacts = sorted([*evaluator_inputs, *declared_outputs], key=lambda row: (row["data_class"], row["path"]))
    if len({_identity(row) for row in artifacts}) != 12:
        _fail("post-replay role inventory contains duplicates")
    producer_inputs = sorted(
        [
            *[{key: row[key] for key in ("path", "sha256", "bytes", "data_class", "schema_id")} for row in upstream],
            sanitizer["ledger"], sanitizer["assignment_proof"], sanitizer["replay_verification"],
            executor["runtime_output"], executor["runtime_event_ledger_replay_bundle"],
            executor["mapped_observation_consumption"], executor["replay_seal"],
            oracle, combined, protocol,
        ],
        key=lambda row: (row["data_class"], row["path"]),
    )
    if len(producer_inputs) != 16 or len({_identity(row) for row in producer_inputs}) != 16:
        _fail("producer input inventory must contain 16 distinct content identities")
    manifest_rel = manifest_path.relative_to(root).as_posix()
    upstream_digest = _sha(_canonical_bytes([
        {key: row[key] for key in ("role", "run_id", "path", "sha256", "bytes")}
        for row in upstream
    ]))
    closure: dict[str, Any] = {
        "schema_version": OUTPUT_VERSION,
        "evaluator_run_id": value["evaluator_run_id"],
        "replay_sealed": True,
        "oracle_contents_included": False,
        "artifacts": artifacts,
        "producer_id": PRODUCER_ID,
        "topology_order": [
            "six_upstream_role_manifests_closed",
            "evaluator_post_replay_receipt_closed",
            "post_replay_inventory_compiled",
            "evaluator_manifest_closed",
            "scorer_auditor_consumes_inventory",
            "final_eight_role_manifest_set_closed",
        ],
        "producer_inputs": producer_inputs,
        "lineage": {
            "compiler_input_manifest": {
                "path": manifest_rel,
                "sha256": _sha(manifest_raw),
                "bytes": len(manifest_raw),
            },
            "upstream_role_manifest_set_digest": upstream_digest,
            "evaluator_input_inventory_digest": _digest_rows(evaluator_inputs),
            "producer_input_inventory_digest": _digest_rows(producer_inputs),
            "self_reference_forbidden": True,
        },
        "executor_internal_bundle": executor["runtime_event_ledger_replay_bundle"],
        "inventory_sha256": _digest_rows(artifacts),
    }
    closure["closure_payload_sha256"] = _sha(_canonical_bytes(closure))
    return closure, _canonical_bytes(closure)


def _write_once(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            _fail(f"refusing to overwrite non-identical closure: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.parent.is_symlink():
        _fail("output parent may not be a symlink")
    temp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    try:
        with temp.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--stdout-only", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = args.study_root.resolve(strict=True)
        _, raw = compile_closure(root, args.input_manifest)
        if args.stdout_only:
            if args.output is not None:
                _fail("--stdout-only and --output are mutually exclusive")
            sys.stdout.buffer.write(raw)
        else:
            if args.output is None:
                _fail("--output is required unless --stdout-only is used")
            output = args.output if args.output.is_absolute() else root / args.output
            try:
                output.resolve(strict=False).relative_to(root)
            except ValueError:
                _fail("output must remain inside study root")
            _write_once(output, raw)
            report = {"status": "PASS", "output": output.relative_to(root).as_posix(), "sha256": _sha(raw), "bytes": len(raw)}
            sys.stdout.buffer.write(_canonical_bytes(report))
        return 0
    except Exception as exc:
        sys.stderr.buffer.write(_canonical_bytes({"status": "FAIL", "error_type": type(exc).__name__, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["CompileError", "compile_closure", "main"]
