#!/usr/bin/env python3
"""Compile one replay-verifiable v3 evidence row from evaluator output.

This compiler is intentionally not a medical evaluator.  It only binds one
already-computed subject row to the frozen producer replay policy.  The final
scorer independently re-opens every source JSON pointer and fresh-replays the
producer, so this compiler cannot turn a failing check into a passing gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence

from producer_replay_verifier import build_invocation_descriptor, invocation_sha256


EVIDENCE_SCHEMA_VERSION = "ncf.primary-gate-evidence.v3"
EVALUATION_SCHEMA_VERSION = "ncf.primary-case-gate-evaluation.v1"
CASE_PRODUCER_ID = "primary-case-gate-evaluator-case-v1"
REPORT_PRODUCER_ID = "primary-case-gate-evaluator-report-v1"
TOOL_REL = "holdout/tools/primary_case_gate_evaluator.py"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class CompileError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise CompileError(message)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _relative_ref(root: Path, path: Path, ref_id: str) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        _fail(f"artifact outside study root: {path}")
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _fail(f"symlink artifact forbidden: {path}")
    if not resolved.is_file():
        _fail(f"artifact is not a file: {path}")
    raw = resolved.read_bytes()
    if not raw:
        _fail(f"empty artifact forbidden: {path}")
    return {
        "ref_id": ref_id,
        "path": PurePosixPath(*rel.parts).as_posix(),
        "sha256": _digest(raw),
        "bytes": len(raw),
    }


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not UTF-8 JSON: {exc}")
    if not isinstance(value, Mapping):
        _fail(f"{label} must be an object")
    return value


def _content_ref(row: Mapping[str, Any]) -> dict[str, Any]:
    required = {"path", "sha256", "bytes"}
    if not required.issubset(row):
        _fail("sealed evaluator tool ref is incomplete")
    result = {key: row[key] for key in ("path", "sha256", "bytes")}
    if (
        result["path"] != TOOL_REL
        or not isinstance(result["sha256"], str)
        or SHA256_RE.fullmatch(result["sha256"]) is None
        or isinstance(result["bytes"], bool)
        or not isinstance(result["bytes"], int)
        or result["bytes"] < 1
    ):
        _fail("sealed evaluator tool ref is invalid")
    return result


def _pointer(base: str, index: int, field: str) -> str:
    return f"/{base}/{index}/{field}"


def compile_evidence(
    study_root: Path,
    *,
    evaluation_path: Path,
    manifest_path: Path,
    scoring_path: Path,
    seal_path: Path,
    subject_kind: str,
    subject_id: str,
) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    evaluation_ref = _relative_ref(root, evaluation_path, "producer_artifact")
    manifest_ref = _relative_ref(root, manifest_path, "input_manifest")
    evaluation = _load_json(evaluation_path, "evaluation output")
    manifest = _load_json(manifest_path, "input manifest")
    scoring = _load_json(scoring_path, "scoring contract")
    seal = _load_json(seal_path, "combined pre-primary seal")
    if evaluation.get("schema_version") != EVALUATION_SCHEMA_VERSION:
        _fail("evaluation schema mismatch")
    if manifest.get("schema_version") != "ncf.primary-case-gate-evaluator-input.v1":
        _fail("input manifest schema mismatch")
    expected_context = "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR"
    if manifest.get("execution_context") != expected_context or evaluation.get("execution_context") != expected_context:
        _fail("gate evaluator manifest/output must be external post-role-DAG execution")
    if subject_kind not in {"GATE", "COMPLEX_COVERAGE"} or not subject_id:
        _fail("subject kind/id invalid")

    base = "gate_results" if subject_kind == "GATE" else "coverage_results"
    rows = evaluation.get(base)
    if not isinstance(rows, list):
        _fail(f"evaluation {base} missing")
    matches = [
        (index, row)
        for index, row in enumerate(rows)
        if isinstance(row, Mapping)
        and row.get("subject_kind") == subject_kind
        and row.get("subject_id") == subject_id
    ]
    if len(matches) != 1:
        _fail("subject must occur exactly once in evaluator output")
    row_index, row = matches[0]
    claimed = row.get("computed_result")
    checks = row.get("checks")
    if claimed not in {"PASS", "FAIL"} or not isinstance(checks, list) or not checks:
        _fail("evaluator subject row malformed")
    passed_values = [check.get("passed") for check in checks if isinstance(check, Mapping)]
    if len(passed_values) != len(checks) or any(not isinstance(item, bool) for item in passed_values):
        _fail("evaluator checks must expose deterministic booleans")
    if (claimed == "PASS") != all(passed_values):
        _fail("computed_result is inconsistent with evaluator checks")

    producer_id = REPORT_PRODUCER_ID if subject_id == "PL-REPORT-001" else CASE_PRODUCER_ID
    expected_subcommand = "evaluate-report" if producer_id == REPORT_PRODUCER_ID else "evaluate-case"
    if manifest.get("stage") != ("REPORT_CONSISTENCY" if producer_id == REPORT_PRODUCER_ID else "CASE_EVALUATION"):
        _fail("manifest stage does not match producer")

    policy_rows = (
        scoring.get("final_scorer_contract", {})
        .get("evidence_producer_policy", {})
        .get("sealed_automated_generators", [])
    )
    matches_policy = [row for row in policy_rows if isinstance(row, Mapping) and row.get("producer_id") == producer_id]
    if len(matches_policy) != 1:
        _fail("frozen producer policy missing or duplicate")
    producer_policy = matches_policy[0]
    allowed = producer_policy.get("allowed_subjects", {}).get(subject_kind, [])
    if subject_id not in allowed:
        _fail("producer is not allowed for requested subject")
    replay_policy = producer_policy.get("replay_contract")
    if not isinstance(replay_policy, Mapping):
        _fail("producer replay policy missing")

    try:
        tool_row = seal["bindings"]["primary_execution"]["primary_case_gate_evaluator"]
    except (KeyError, TypeError):
        _fail("combined seal lacks primary_case_gate_evaluator binding")
    if not isinstance(tool_row, Mapping):
        _fail("combined seal evaluator binding malformed")
    tool_ref = _content_ref(tool_row)
    actual_tool = _relative_ref(root, root / TOOL_REL, "evaluator_tool")
    if any(tool_ref[key] != actual_tool[key] for key in ("path", "sha256", "bytes")):
        _fail("combined seal evaluator binding differs from current tool")

    source_refs = {
        manifest_ref["ref_id"]: manifest_ref,
        evaluation_ref["ref_id"]: evaluation_ref,
    }
    replay = {
        "adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
        "input_ref_ids": {"input_manifest": manifest_ref["ref_id"]},
        "check_args": {"subcommand": expected_subcommand},
        "invocation_sha256": "0" * 64,
    }
    descriptor = build_invocation_descriptor(
        producer_id=producer_id,
        tool_ref=tool_ref,
        replay_policy=replay_policy,
        replay_claim=replay,
        source_refs=source_refs,
        output_ref_id=evaluation_ref["ref_id"],
    )
    replay["invocation_sha256"] = invocation_sha256(descriptor)

    assertions = [
        {
            "assertion_id": f"{subject_id}.computed_result",
            "source_ref_id": evaluation_ref["ref_id"],
            "observed_json_pointer": _pointer(base, row_index, "computed_result"),
            "observed": claimed,
            "expected": claimed,
            "operator": "EQ",
        }
    ]
    for check_index, passed in enumerate(passed_values):
        assertions.append(
            {
                "assertion_id": f"{subject_id}.check.{check_index}.passed",
                "source_ref_id": evaluation_ref["ref_id"],
                "observed_json_pointer": f"/{base}/{row_index}/checks/{check_index}/passed",
                "observed": passed,
                "expected": True,
                "operator": "EQ",
            }
        )
    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "claimed_result": claimed,
        "producer": {
            "policy": "SEALED_AUTOMATED_GENERATOR",
            "producer_id": producer_id,
            "tool_ref": tool_ref,
            "artifact_ref_id": evaluation_ref["ref_id"],
            "replay": replay,
        },
        "source_artifact_refs": [manifest_ref, evaluation_ref],
        "assertions": assertions,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--scoring-contract", required=True, type=Path)
    parser.add_argument("--combined-seal", required=True, type=Path)
    parser.add_argument("--subject-kind", required=True, choices=("GATE", "COMPLEX_COVERAGE"))
    parser.add_argument("--subject-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = Path(__file__).resolve().parents[2]
    try:
        result = compile_evidence(
            root,
            evaluation_path=args.evaluation,
            manifest_path=args.manifest,
            scoring_path=args.scoring_contract,
            seal_path=args.combined_seal,
            subject_kind=args.subject_kind,
            subject_id=args.subject_id,
        )
        if args.output.exists():
            _fail(f"refusing to overwrite output: {args.output}")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_json_bytes(result) + b"\n")
    except (CompileError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
