#!/usr/bin/env python3
"""Independently replay and verify the post-replay closure after all 8 roles close."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence


STUDY_ROOT = Path(__file__).resolve().parents[2]
if str(STUDY_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDY_ROOT))

from holdout.tools.compile_all_sealed_artifacts_after_replay import (  # noqa: E402
    PRODUCER_ID,
    CompileError,
    _canonical_bytes,
    _identity,
    _json,
    _mapping,
    _sha,
    compile_closure,
)
from holdout.tools.validate_primary_holdout_protocol import (  # noqa: E402
    validate_role_manifest_set,
)


VERSION = "NCF-POST-REPLAY-INVENTORY-REPLAY-VERIFICATION-1.0.0"
TOOL_REL = "holdout/tools/verify_all_sealed_artifacts_after_replay.py"
COMPILER_REL = "holdout/tools/compile_all_sealed_artifacts_after_replay.py"
ROLE_ORDER = [
    "scout", "screener", "extractor", "source_auditor", "concept_mapper",
    "oracle_adjudicator", "evaluator", "scorer_auditor",
]


class VerificationError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise VerificationError(message)


def _rel_file(root: Path, path: Path, label: str) -> tuple[str, bytes]:
    candidate = path if path.is_absolute() else root / path
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, ValueError):
        _fail(f"{label} missing or outside study root")
    if candidate.is_symlink() or not resolved.is_file():
        _fail(f"{label} must be a non-symlink regular file")
    return resolved.relative_to(root).as_posix(), resolved.read_bytes()


def _content_ref(root: Path, path: Path, label: str) -> dict[str, Any]:
    rel, raw = _rel_file(root, path, label)
    return {"path": rel, "sha256": _sha(raw), "bytes": len(raw)}


def _artifact_ref_from_path(root: Path, path: Path, row: Mapping[str, Any]) -> dict[str, Any]:
    ref = _content_ref(root, path, str(row.get("data_class", "artifact")))
    return {**ref, "data_class": row["data_class"], "schema_id": row["schema_id"]}


def _load_manifest_set(root: Path, path: Path) -> tuple[Mapping[str, Any], dict[str, Mapping[str, Any]]]:
    _, raw = _rel_file(root, path, "final role manifest set")
    aggregate = _json(raw, "final role manifest set")
    rows = aggregate.get("manifests")
    if not isinstance(rows, list) or [row.get("role") for row in rows if isinstance(row, Mapping)] != ROLE_ORDER:
        _fail("final role manifest set must contain the frozen 8-role order")
    manifests: dict[str, Mapping[str, Any]] = {}
    for row_any in rows:
        row = _mapping(row_any, "final role manifest ref")
        manifest_path = root / PurePosixPath(str(row["path"]))
        rel, manifest_raw = _rel_file(root, manifest_path, f"{row['role']} manifest")
        if (
            rel != row["path"]
            or _sha(manifest_raw) != row["sha256"]
            or len(manifest_raw) != row["bytes"]
        ):
            _fail(f"final role manifest content mismatch: {row['role']}")
        manifest = _json(manifest_raw, f"{row['role']} manifest")
        if manifest.get("role") != row["role"] or manifest.get("run_id") != row["run_id"]:
            _fail(f"final role manifest identity mismatch: {row['role']}")
        manifests[str(row["role"])] = manifest
    return aggregate, manifests


def _typed(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("path", "sha256", "bytes", "data_class", "schema_id")}


def verify(
    study_root: Path,
    compiler_input: Path,
    closure_path: Path,
    final_role_manifest_set: Path,
) -> tuple[dict[str, Any], bytes]:
    root = study_root.resolve(strict=True)
    input_ref = _content_ref(root, compiler_input, "compiler input manifest")
    closure_ref = _content_ref(root, closure_path, "post-replay closure")
    final_ref = _content_ref(root, final_role_manifest_set, "final role manifest set")
    _, input_raw = _rel_file(root, compiler_input, "compiler input manifest")
    compiler_input_doc = _json(input_raw, "compiler input manifest")
    _, closure_raw = _rel_file(root, closure_path, "post-replay closure")
    closure = _json(closure_raw, "post-replay closure")
    expected, expected_raw = compile_closure(root, compiler_input)
    if expected_raw != closure_raw:
        _fail("in-process closure replay is not byte-exact")

    compiler = root / COMPILER_REL
    compiler_raw = compiler.read_bytes()
    command = [
        sys.executable, str(compiler), "--study-root", str(root),
        "--input-manifest", str((root / input_ref["path"])), "--stdout-only",
    ]
    completed = subprocess.run(
        command, cwd=root, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, check=False,
        env={**os.environ, "PYTHONHASHSEED": "0"},
    )
    if completed.returncode != 0:
        _fail(f"fresh compiler replay failed: {completed.stderr.decode('utf-8', errors='replace')}")
    if completed.stdout != closure_raw:
        _fail("fresh compiler replay is not byte-exact")

    aggregate, manifests = _load_manifest_set(root, final_role_manifest_set)
    validation = validate_role_manifest_set(root, root / final_ref["path"])
    if validation.get("status") != "PASS" or validation.get("role_count") != 8:
        _fail("final eight-role manifest set did not validate")

    upstream_rows = compiler_input_doc["upstream_role_manifests"]
    final_rows = {row["role"]: row for row in aggregate["manifests"]}
    upstream_exact = all(
        all(source[key] == final_rows[source["role"]][key] for key in ("role", "run_id", "path", "sha256", "bytes"))
        for source in upstream_rows
    )
    if not upstream_exact:
        _fail("compiler upstream manifests differ from final set")

    evaluator = manifests["evaluator"]
    scorer = manifests["scorer_auditor"]
    expected_inputs = {_identity(row) for row in compiler_input_doc["evaluator_inputs"]}
    actual_inputs = {_identity(_typed(row)) for row in evaluator["inputs"]}
    if expected_inputs != actual_inputs:
        _fail("evaluator manifest inputs differ from compiler receipt")
    executor = compiler_input_doc["executor_outputs"]
    expected_outputs = {
        _identity(executor["runtime_output"]),
        _identity(executor["replay_seal"]),
        _identity(executor["mapped_observation_consumption"]),
    }
    closure_output = next(
        (row for row in evaluator["outputs"] if row["data_class"] == "all_sealed_artifacts_after_replay"),
        None,
    )
    if closure_output is None:
        _fail("evaluator manifest omits post-replay closure")
    actual_outputs = {
        _identity(_typed(row)) for row in evaluator["outputs"]
        if row["data_class"] != "all_sealed_artifacts_after_replay"
    }
    closure_typed = {
        **closure_ref,
        "data_class": "all_sealed_artifacts_after_replay",
        "schema_id": "ncf.data.all-sealed-artifacts-after-replay.v1",
    }
    if expected_outputs != actual_outputs or _identity(_typed(closure_output)) != _identity(closure_typed):
        _fail("evaluator manifest outputs differ from compiler receipt/closure")
    if evaluator.get("run_id") != expected.get("evaluator_run_id"):
        _fail("evaluator run id differs from compiled closure")

    scorer_closure = [row for row in scorer["inputs"] if row["data_class"] == "all_sealed_artifacts_after_replay"]
    if len(scorer_closure) != 1 or _identity(_typed(scorer_closure[0])) != _identity(closure_typed):
        _fail("scorer does not consume the exact compiled closure")

    bundle = compiler_input_doc["executor_outputs"]["runtime_event_ledger_replay_bundle"]
    if _identity(closure["executor_internal_bundle"]) != _identity(bundle):
        _fail("closure executor internal bundle mismatch")
    producer_by_class: dict[str, list[Mapping[str, Any]]] = {}
    for row in closure["producer_inputs"]:
        producer_by_class.setdefault(str(row["data_class"]), []).append(row)
    for key, row in compiler_input_doc["sanitizer"].items():
        matches = producer_by_class.get(str(row["data_class"]), [])
        if len(matches) != 1 or _identity(matches[0]) != _identity(row):
            _fail(f"closure sanitizer lineage mismatch: {key}")
    if closure.get("oracle_contents_included") is not False or "oracle_contents" in producer_by_class:
        _fail("oracle contents leaked into post-replay closure")
    closure_rel = closure_ref["path"]
    if any(row["path"] == closure_rel for row in closure["producer_inputs"]):
        _fail("closure illegally self-references through producer_inputs")
    if closure["lineage"].get("compiler_input_manifest") != input_ref:
        _fail("closure compiler input lineage mismatch")

    checks = {
        "fresh_compiler_byte_exact": True,
        "final_eight_role_manifest_set_valid": True,
        "upstream_manifests_exact": True,
        "evaluator_manifest_exact": True,
        "scorer_consumes_exact_closure": True,
        "executor_internal_bundle_exact": True,
        "sanitizer_lineage_exact": True,
        "oracle_contents_excluded": True,
        "self_reference_absent": True,
    }
    report: dict[str, Any] = {
        "schema_version": VERSION,
        "producer_id": PRODUCER_ID,
        "status": "PASS",
        "compiler": {"path": COMPILER_REL, "sha256": _sha(compiler_raw), "bytes": len(compiler_raw)},
        "compiler_input_manifest": input_ref,
        "closure": closure_ref,
        "final_role_manifest_set": final_ref,
        "checks": checks,
        "fresh_replay": {
            "process_exit_code": completed.returncode,
            "stdout_sha256": _sha(completed.stdout),
            "recompiled_closure_sha256": _sha(expected_raw),
            "byte_exact": True,
        },
    }
    report["report_payload_sha256"] = _sha(_canonical_bytes(report))
    return report, _canonical_bytes(report)


def _write_once(path: Path, raw: bytes) -> None:
    if path.exists():
        if path.is_symlink() or path.read_bytes() != raw:
            _fail(f"refusing to overwrite non-identical verification report: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
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
    parser.add_argument("--study-root", type=Path, default=STUDY_ROOT)
    parser.add_argument("--compiler-input", type=Path, required=True)
    parser.add_argument("--closure", type=Path, required=True)
    parser.add_argument("--final-role-manifest-set", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = args.study_root.resolve(strict=True)
        _, raw = verify(root, args.compiler_input, args.closure, args.final_role_manifest_set)
        output = args.output if args.output.is_absolute() else root / args.output
        try:
            output.resolve(strict=False).relative_to(root)
        except ValueError:
            _fail("verification output must remain inside study root")
        _write_once(output, raw)
        sys.stdout.buffer.write(_canonical_bytes({"status": "PASS", "output": output.relative_to(root).as_posix(), "sha256": _sha(raw), "bytes": len(raw)}))
        return 0
    except Exception as exc:
        sys.stderr.buffer.write(_canonical_bytes({"status": "FAIL", "error_type": type(exc).__name__, "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["VerificationError", "verify", "main"]
