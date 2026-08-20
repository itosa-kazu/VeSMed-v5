#!/usr/bin/env python3
"""Fresh-process validator for primary case mechanical closure artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence


COMPILER_REL = "holdout/tools/compile_primary_case_mechanical_closure.py"
STATIC_REPLAY_ASSETS = (
    COMPILER_REL,
    "holdout/tools/compile_availability_epochs.py",
    "holdout/tools/verify_compiled_availability.py",
    "holdout/tools/producer_replay_verifier.py",
    "holdout/tools/verify_evaluator_sanitized_runtime_ledger.py",
    "holdout/tools/compile_evaluator_sanitized_runtime_ledger.py",
    "holdout/tools/test_compile_availability_epochs.py",
    "holdout/tools/test_verify_compiled_availability.py",
    "holdout/schemas/primary_availability_ledger.schema.json",
    "holdout/schemas/compiled_guaranteed_availability.schema.json",
    "holdout/schemas/availability_compiler_proof.schema.json",
)


class ValidationError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise ValidationError(message)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _inside(root: Path, path: Path, label: str) -> Path:
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        _fail(f"{label} escapes study root")
    if not resolved.is_file() or resolved.is_symlink():
        _fail(f"{label} must be a non-symlink file")
    return resolved


def _artifact_rows(value: Any) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if (
            isinstance(value.get("path"), str)
            and isinstance(value.get("sha256"), str)
            and isinstance(value.get("bytes"), int)
        ):
            rows.append(value)
        for child in value.values():
            rows.extend(_artifact_rows(child))
    elif isinstance(value, list):
        for child in value:
            rows.extend(_artifact_rows(child))
    return rows


def _canonical_source_path(root: Path, rel_text: Any, label: str) -> Path:
    if not isinstance(rel_text, str) or not rel_text:
        _fail(f"{label} path missing")
    rel = PurePosixPath(rel_text)
    if rel.is_absolute() or ".." in rel.parts or re.match(r"^[A-Za-z]:", rel_text):
        _fail(f"{label} path is not canonical in-root")
    return _inside(root, root / Path(*rel.parts), label)


def _build_replay_snapshot(
    root: Path,
    aggregate: Path,
    clone_root: Path,
    excluded_relative_paths: set[str],
) -> dict[Path, bytes]:
    """Copy the exact content-addressed closure into a same-layout clean root."""

    queue = [aggregate, *[root / Path(*PurePosixPath(rel).parts) for rel in STATIC_REPLAY_ASSETS]]
    originals: dict[Path, bytes] = {}
    while queue:
        source = _inside(root, queue.pop(), "closure snapshot artifact")
        rel = source.relative_to(root).as_posix()
        if rel in excluded_relative_paths or source in originals:
            continue
        raw = source.read_bytes()
        originals[source] = raw
        target = clone_root / Path(*PurePosixPath(rel).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        if source.suffix.lower() != ".json":
            continue
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for index, row in enumerate(_artifact_rows(value)):
            child = _canonical_source_path(root, row.get("path"), f"nested content ref {rel}:{index}")
            child_raw = child.read_bytes()
            if row.get("sha256") != _sha(child_raw) or row.get("bytes") != len(child_raw):
                _fail(f"nested content ref hash/bytes mismatch: {rel}:{index}")
            queue.append(child)
    return originals


def validate(
    study_root: Path,
    role_manifest_set: Path,
    event_ledger_audit: Path,
    case_access_lineage: Path,
) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    aggregate = _inside(root, role_manifest_set, "role manifest set")
    audit = _inside(root, event_ledger_audit, "event ledger audit")
    lineage = _inside(root, case_access_lineage, "case access lineage")
    compiler = _inside(root, root / COMPILER_REL, "mechanical closure compiler")
    before = {path: path.read_bytes() for path in (aggregate, audit, lineage, compiler)}
    with tempfile.TemporaryDirectory(prefix=".ncf-closure-replay-", dir=root) as raw_temp:
        temp = Path(raw_temp)
        clone_root = temp / "study"
        clone_root.mkdir()
        audit_rel = audit.relative_to(root).as_posix()
        lineage_rel = lineage.relative_to(root).as_posix()
        snapshot_before = _build_replay_snapshot(
            root,
            aggregate,
            clone_root,
            {audit_rel, lineage_rel},
        )
        replay_aggregate = clone_root / aggregate.relative_to(root)
        replay_compiler = clone_root / Path(*PurePosixPath(COMPILER_REL).parts)
        replay_audit = clone_root / audit.relative_to(root)
        replay_lineage = clone_root / lineage.relative_to(root)
        completed = subprocess.run(
            [
                sys.executable,
                str(replay_compiler),
                "--study-root", str(clone_root),
                "--role-manifest-set", str(replay_aggregate),
                "--event-ledger-audit", str(replay_audit),
                "--case-access-lineage", str(replay_lineage),
            ],
            cwd=clone_root,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                key: value for key, value in os.environ.items()
                if key in {"SystemRoot", "WINDIR", "PATH"}
            } | {
                "PYTHONHASHSEED": "0",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONIOENCODING": "utf-8",
                "TZ": "UTC",
                "NO_PROXY": "*",
                "HTTP_PROXY": "http://127.0.0.1:9",
                "HTTPS_PROXY": "http://127.0.0.1:9",
            },
            timeout=120,
            check=False,
        )
        if completed.returncode != 0:
            _fail(f"fresh compiler replay failed: {completed.returncode}")
        replay_audit_raw = replay_audit.read_bytes()
        replay_lineage_raw = replay_lineage.read_bytes()
        if any(path.read_bytes() != raw for path, raw in snapshot_before.items()):
            _fail("fresh replay modified a source closure artifact")
    if any(path.read_bytes() != raw for path, raw in before.items()):
        _fail("fresh replay modified an original input/tool")
    if replay_audit_raw != before[audit]:
        _fail("event ledger audit exact replay mismatch")
    if replay_lineage_raw != before[lineage]:
        _fail("case access lineage exact replay mismatch")
    for raw, version, label in (
        (before[audit], "NCF-PRIMARY-EVENT-LEDGER-AUDIT-1.0.0", "event audit"),
        (before[lineage], "NCF-PRIMARY-CASE-ACCESS-LINEAGE-1.0.0", "access lineage"),
    ):
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _fail(f"{label} is not UTF-8 JSON: {exc}")
        if not isinstance(value, Mapping) or value.get("schema_version") != version or value.get("status") != "PASS":
            _fail(f"{label} identity/status mismatch")
    return {
        "schema_version": "NCF-PRIMARY-CASE-MECHANICAL-CLOSURE-VALIDATION-1.0.0",
        "status": "PASS",
        "role_manifest_set_sha256": _sha(before[aggregate]),
        "event_ledger_audit_sha256": _sha(before[audit]),
        "case_access_lineage_sha256": _sha(before[lineage]),
        "compiler_sha256": _sha(before[compiler]),
        "comparison": "EXACT_BYTES_FRESH_PROCESS",
        "medical_judgment_performed": False,
    }


def _write(path: Path | None, value: Mapping[str, Any]) -> None:
    if path is None:
        return
    if path.exists():
        _fail(f"refusing to overwrite report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--role-manifest-set", type=Path, required=True)
    parser.add_argument("--event-ledger-audit", type=Path, required=True)
    parser.add_argument("--case-access-lineage", type=Path, required=True)
    parser.add_argument("--output-report", type=Path)
    args = parser.parse_args(argv)
    try:
        report = validate(
            args.study_root,
            args.role_manifest_set,
            args.event_ledger_audit,
            args.case_access_lineage,
        )
        _write(args.output_report, report)
        print(json.dumps(report, sort_keys=True))
        return 0
    except (ValidationError, OSError, subprocess.SubprocessError) as exc:
        print(f"FAIL_CLOSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
