#!/usr/bin/env python3
"""Deterministically assemble the primary-holdout evidence bundles.

The pipeline is deliberately split in two.  ``assemble-nonreport`` produces
the exact 29 non-report gates and seven complexity checks consumed by the
frozen report builder.  ``assemble-final`` adds the independently replayable
PL-REPORT-001 evidence and emits the exact 30-gate bundle consumed by the final
scorer.

This program never accepts a result on the command line and never creates
manual PASS evidence.  Every result is read from an allow-listed, combined-
sealed producer artifact and is bound to a fresh-replay descriptor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence

from compile_primary_case_gate_evidence import compile_evidence as compile_case_evidence
from producer_replay_verifier import build_invocation_descriptor, invocation_sha256


GATE_BUNDLE_SCHEMA = "ncf.primary-gate-evidence-bundle.v1"
COVERAGE_BUNDLE_SCHEMA = "ncf.primary-complex-case-coverage.v1"
ASSEMBLY_SCHEMA = "ncf.primary-final-evidence-assembly.v1"
EVIDENCE_SCHEMA = "ncf.primary-gate-evidence.v3"
STRUCTURAL_SCHEMA = "ncf.structural-gate-results.v1"
EVENT_SCHEMA = "ncf.holdout.fresh-process-replay-report.v1"
CASE_EVALUATION_SCHEMA = "ncf.primary-case-gate-evaluation.v1"
CASE_MANIFEST_SCHEMA = "ncf.primary-case-gate-evaluator-input.v1"
ALL_SEALED_SCHEMA = "NCF-ALL-SEALED-ARTIFACTS-AFTER-REPLAY-1.0.0"
COMBINED_SEAL_REL = "holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json"
SCORING_REL = "holdout/PRIMARY_HOLDOUT_SCORING_v1.json"
GATES_REL = "holdout/PERFECT_LANDING_GATES.json"
STRUCTURAL_TOOL_REL = "holdout/tools/structural_gate_harness.py"
EVENT_TOOL_REL = "holdout/tools/event_ledger_replay.py"
CASE_TOOL_REL = "holdout/tools/primary_case_gate_evaluator.py"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_COVERAGE = (
    "recursive_updates",
    "at_least_two_local_domains",
    "concurrent_process_target_from_oracle",
    "delayed_information",
    "reliable_negative_evidence",
    "performed_action_lifecycle_with_response",
    "prospective_pre_next_cut_forecasts",
)
CASE_GATE_IDS = ("PL-BLIND-001", "PL-LED-001", "PL-DX-002", "PL-PRED-002", "PL-CASE-001")
REPORT_GATE_ID = "PL-REPORT-001"


class AssemblyError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise AssemblyError(message)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8") + b"\n"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _load_json(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        _fail(f"{label} missing, non-file, or symlink: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not UTF-8 JSON: {exc}")
    if not isinstance(value, Mapping):
        _fail(f"{label} must be an object")
    return value


def _canonical_rel(root: Path, path: Path) -> str:
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
    return PurePosixPath(*rel.parts).as_posix()


def _content_ref(root: Path, path: Path, *, ref_id: str | None = None) -> dict[str, Any]:
    rel = _canonical_rel(root, path)
    raw = path.resolve(strict=True).read_bytes()
    if not raw:
        _fail(f"empty artifact forbidden: {path}")
    row: dict[str, Any] = {"path": rel, "sha256": _sha(raw), "bytes": len(raw)}
    return ({"ref_id": ref_id, **row} if ref_id is not None else row)


def _resolve_ref(root: Path, ref: Any, label: str) -> Path:
    if not isinstance(ref, Mapping) or set(ref) - {"path", "sha256", "bytes", "data_class", "schema_id", "ref_id", "role"}:
        _fail(f"{label} malformed")
    path_text, digest, size = ref.get("path"), ref.get("sha256"), ref.get("bytes")
    if (
        not isinstance(path_text, str)
        or not isinstance(digest, str)
        or SHA256_RE.fullmatch(digest) is None
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
    ):
        _fail(f"{label} content fields invalid")
    rel = Path(path_text)
    if rel.is_absolute() or ".." in rel.parts or rel.as_posix() != path_text:
        _fail(f"{label} path is not canonical relative path")
    candidate = root
    for part in rel.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            _fail(f"{label} traverses symlink")
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (FileNotFoundError, OSError, ValueError):
        _fail(f"{label} does not resolve inside study root")
    raw = resolved.read_bytes()
    if len(raw) != size or _sha(raw) != digest:
        _fail(f"{label} hash/byte mismatch")
    return resolved


def _plain_ref(ref: Mapping[str, Any]) -> dict[str, Any]:
    return {key: ref[key] for key in ("path", "sha256", "bytes")}


def _same_ref(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return _plain_ref(left) == _plain_ref(right)


def _verify_preprimary(root: Path, seal_path: Path) -> Mapping[str, Any]:
    expected = (root / COMBINED_SEAL_REL).resolve(strict=True)
    if seal_path.resolve(strict=True) != expected:
        _fail("combined seal must be the frozen canonical pre-primary seal")
    try:
        from build_pre_primary_holdout_seal import verify_seal
        verification = verify_seal(root)
    except Exception as exc:
        _fail(f"combined pre-primary seal verification failed: {exc}")
    if verification.get("status") != "PASS":
        _fail("combined pre-primary seal verifier did not return PASS")
    seal = _load_json(seal_path, "combined pre-primary seal")
    payload = seal.get("payload_sha256")
    if payload != verification.get("payload_sha256") or not isinstance(payload, str) or SHA256_RE.fullmatch(payload) is None:
        _fail("combined seal payload binding mismatch")
    return seal


def _policy(scoring: Mapping[str, Any], producer_id: str) -> Mapping[str, Any]:
    rows = scoring.get("final_scorer_contract", {}).get("evidence_producer_policy", {}).get("sealed_automated_generators", [])
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("producer_id") == producer_id]
    if len(matches) != 1:
        _fail(f"frozen producer policy missing/duplicate: {producer_id}")
    return matches[0]


def _sealed_tool(root: Path, seal: Mapping[str, Any], key: str, expected_rel: str) -> dict[str, Any]:
    try:
        row = seal["bindings"]["primary_execution"][key]
    except (KeyError, TypeError):
        _fail(f"combined seal missing producer tool binding: {key}")
    if not isinstance(row, Mapping) or set(row) != {"path", "sha256", "bytes"} or row.get("path") != expected_rel:
        _fail(f"combined seal producer tool binding malformed: {key}")
    current = _content_ref(root, root / expected_rel)
    if current != dict(row):
        _fail(f"combined seal producer tool differs from current file: {key}")
    return current


def _assert_manifest_ref(manifest: Mapping[str, Any], role: str, expected: Mapping[str, Any]) -> None:
    rows = manifest.get("inputs")
    if not isinstance(rows, list):
        _fail("case evaluator manifest inputs missing")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("role") == role]
    if len(matches) != 1 or not _same_ref(matches[0], expected):
        _fail(f"case evaluator manifest does not bind {role}")


def _verify_all_sealed(root: Path, path: Path, case_manifest: Mapping[str, Any]) -> dict[str, Any]:
    inventory = _load_json(path, "all-sealed-after-replay inventory")
    if set(inventory) != {"schema_version", "evaluator_run_id", "replay_sealed", "oracle_contents_included", "artifacts"}:
        _fail("all-sealed inventory top-level keys mismatch")
    if (
        inventory.get("schema_version") != ALL_SEALED_SCHEMA
        or inventory.get("replay_sealed") is not True
        or inventory.get("oracle_contents_included") is not False
    ):
        _fail("all-sealed inventory status/schema mismatch")
    rows = inventory.get("artifacts")
    if not isinstance(rows, list) or not rows:
        _fail("all-sealed inventory artifacts missing")
    paths: set[str] = set()
    classes: set[str] = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or set(row) != {"path", "sha256", "bytes", "data_class", "schema_id"}:
            _fail(f"all-sealed artifact[{index}] malformed")
        data_class, schema_id = row.get("data_class"), row.get("schema_id")
        if not isinstance(data_class, str) or not data_class or not isinstance(schema_id, str) or not schema_id:
            _fail(f"all-sealed artifact[{index}] class/schema invalid")
        if row["path"] in paths or data_class in classes:
            _fail("all-sealed inventory duplicate path or data_class")
        paths.add(str(row["path"])); classes.add(data_class)
        _resolve_ref(root, row, f"all-sealed artifact[{index}]")
    required = {"runtime_output", "replay_seal", "mapped_observation_consumption"}
    if not required.issubset(classes):
        _fail("all-sealed inventory omits runtime/replay/consumption closure")
    inventory_ref = _content_ref(root, path)
    _assert_manifest_ref(case_manifest, "all_sealed_artifacts_after_replay", inventory_ref)
    return {
        "inventory_ref": inventory_ref,
        "artifact_count": len(rows),
        "artifact_classes": sorted(classes),
        "all_artifacts_content_verified": True,
    }


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def _write_evidence(root: Path, output_dir: Path, evidence: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(evidence["subject_kind"])
    subject = str(evidence["subject_id"])
    path = output_dir / "evidence" / f"{kind}-{subject}.json"
    _write_json(path, evidence)
    return _content_ref(root, path)


def _source_ref(root: Path, path: Path, ref_id: str) -> dict[str, Any]:
    return _content_ref(root, path, ref_id=ref_id)


def _structural_evidence(
    root: Path, seal: Mapping[str, Any], scoring: Mapping[str, Any], results_path: Path, subject_id: str
) -> dict[str, Any]:
    artifact = _load_json(results_path, "structural gate results")
    if artifact.get("schema_version") != STRUCTURAL_SCHEMA or artifact.get("produced_by") != STRUCTURAL_TOOL_REL:
        _fail("structural gate result schema/producer mismatch")
    policy = _policy(scoring, "structural-gate-harness-v1")
    allowed = policy.get("allowed_subjects", {}).get("GATE")
    rows = artifact.get("gate_results")
    if not isinstance(allowed, list) or not isinstance(rows, list):
        _fail("structural producer policy/results malformed")
    actual_ids = [row.get("gate_id") for row in rows if isinstance(row, Mapping)]
    if len(actual_ids) != len(rows) or set(actual_ids) != set(allowed) or len(actual_ids) != len(set(actual_ids)):
        _fail("structural result gate coverage differs from frozen producer scope")
    matches = [(i, row) for i, row in enumerate(rows) if row.get("gate_id") == subject_id]
    if len(matches) != 1:
        _fail(f"structural gate missing/duplicate: {subject_id}")
    index, row = matches[0]
    result = row.get("result")
    if result not in {"PASS", "FAIL"}:
        _fail(f"structural gate is incomplete: {subject_id}")
    tool_ref = _sealed_tool(root, seal, "structural_gate_harness", STRUCTURAL_TOOL_REL)
    output_ref = _source_ref(root, results_path, "producer_artifact")
    replay = {
        "adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
        "input_ref_ids": {},
        "check_args": {"generated_at": str(artifact.get("generated_at"))},
        "invocation_sha256": "0" * 64,
    }
    descriptor = build_invocation_descriptor(
        producer_id="structural-gate-harness-v1", tool_ref=tool_ref,
        replay_policy=policy["replay_contract"], replay_claim=replay,
        source_refs={"producer_artifact": output_ref}, output_ref_id="producer_artifact",
    )
    replay["invocation_sha256"] = invocation_sha256(descriptor)
    return {
        "schema_version": EVIDENCE_SCHEMA, "subject_kind": "GATE", "subject_id": subject_id,
        "claimed_result": result,
        "producer": {"policy": "SEALED_AUTOMATED_GENERATOR", "producer_id": "structural-gate-harness-v1", "tool_ref": tool_ref, "artifact_ref_id": "producer_artifact", "replay": replay},
        "source_artifact_refs": [output_ref],
        "assertions": [{"assertion_id": f"{subject_id}.result", "source_ref_id": "producer_artifact", "observed_json_pointer": f"/gate_results/{index}/result", "observed": result, "expected": result, "operator": "EQ"}],
    }


def _event_evidence(
    root: Path, seal: Mapping[str, Any], scoring: Mapping[str, Any], report_path: Path,
    bundle_path: Path, model_path: Path, *, kind: str, subject_id: str,
) -> dict[str, Any]:
    report = _load_json(report_path, "event-ledger replay report")
    if report.get("schema_version") != EVENT_SCHEMA:
        _fail("event-ledger replay report schema mismatch")
    policy = _policy(scoring, "event-ledger-fresh-replay-v1")
    allowed = policy.get("allowed_subjects", {}).get(kind)
    if not isinstance(allowed, list) or subject_id not in allowed:
        _fail(f"event replay producer not allowed for {kind}:{subject_id}")
    contract_rows = policy.get("assertion_contract", {}).get("subject_assertions", {}).get(kind, {}).get(subject_id)
    if not isinstance(contract_rows, list) or not contract_rows:
        _fail("event replay assertion contract missing")
    tool_ref = _sealed_tool(root, seal, "event_ledger_replay", EVENT_TOOL_REL)
    bundle_ref = _source_ref(root, bundle_path, "bundle")
    model_ref = _source_ref(root, model_path, "model")
    report_ref = _source_ref(root, report_path, "producer_artifact")
    source_refs = {"bundle": bundle_ref, "model": model_ref, "producer_artifact": report_ref}
    replay = {"adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1", "input_ref_ids": {"bundle": "bundle", "model": "model"}, "check_args": {}, "invocation_sha256": "0" * 64}
    descriptor = build_invocation_descriptor(
        producer_id="event-ledger-fresh-replay-v1", tool_ref=tool_ref,
        replay_policy=policy["replay_contract"], replay_claim=replay,
        source_refs=source_refs, output_ref_id="producer_artifact",
    )
    replay["invocation_sha256"] = invocation_sha256(descriptor)
    assertions = []
    truth = []
    for index, contract in enumerate(contract_rows):
        pointer = contract.get("json_pointer")
        if not isinstance(pointer, str) or not pointer.startswith("/") or "/" in pointer[1:]:
            _fail("event replay pointer outside supported scalar top-level contract")
        key = pointer[1:].replace("~1", "/").replace("~0", "~")
        if key not in report:
            _fail(f"event replay report lacks contracted pointer: {pointer}")
        observed, expected, operator = report[key], contract.get("expected"), contract.get("operator")
        if operator != "EQ":
            _fail("event replay compiler currently requires EQ exact-pointer contract")
        passed = type(observed) is type(expected) and observed == expected
        truth.append(passed)
        assertions.append({"assertion_id": f"{subject_id}.check.{index}", "source_ref_id": "producer_artifact", "observed_json_pointer": pointer, "observed": observed, "expected": expected, "operator": operator})
    result = "PASS" if all(truth) else "FAIL"
    return {
        "schema_version": EVIDENCE_SCHEMA, "subject_kind": kind, "subject_id": subject_id,
        "claimed_result": result,
        "producer": {"policy": "SEALED_AUTOMATED_GENERATOR", "producer_id": "event-ledger-fresh-replay-v1", "tool_ref": tool_ref, "artifact_ref_id": "producer_artifact", "replay": replay},
        "source_artifact_refs": [bundle_ref, model_ref, report_ref], "assertions": assertions,
    }


def _result_rows(evidence_by_id: Mapping[str, tuple[str, Mapping[str, Any]]], order: Sequence[str], key: str) -> list[dict[str, Any]]:
    if set(evidence_by_id) != set(order) or len(evidence_by_id) != len(order):
        _fail(f"exact {key} evidence coverage not achieved")
    return [{key: item, "result": evidence_by_id[item][0], "evidence_refs": [dict(evidence_by_id[item][1])]} for item in order]


def _verify_evidence_ref(root: Path, ref: Any, kind: str, subject_id: str, result: str) -> None:
    path = _resolve_ref(root, ref, f"{kind}:{subject_id} evidence")
    value = _load_json(path, f"{kind}:{subject_id} evidence")
    if (
        value.get("schema_version") != EVIDENCE_SCHEMA
        or value.get("subject_kind") != kind
        or value.get("subject_id") != subject_id
        or value.get("claimed_result") != result
        or value.get("producer", {}).get("policy") != "SEALED_AUTOMATED_GENERATOR"
    ):
        _fail(f"{kind}:{subject_id} evidence subject/result/producer mismatch")


def _verify_bundle(root: Path, bundle: Mapping[str, Any], *, expected_ids: Sequence[str], key: str, kind: str) -> None:
    rows_key = "gate_results" if key == "gate_id" else "checks"
    rows = bundle.get(rows_key)
    if not isinstance(rows, list) or [row.get(key) for row in rows if isinstance(row, Mapping)] != list(expected_ids):
        _fail(f"bundle does not contain exact ordered {key} set")
    for row in rows:
        result, refs = row.get("result"), row.get("evidence_refs")
        if result not in {"PASS", "FAIL"} or not isinstance(refs, list) or len(refs) != 1:
            _fail(f"bundle row malformed: {row.get(key)}")
        _verify_evidence_ref(root, refs[0], kind, str(row[key]), str(result))


def _assembly_manifest(
    root: Path, *, phase: str, seal: Mapping[str, Any], seal_path: Path,
    all_sealed: Mapping[str, Any], inputs: Sequence[Path], outputs: Sequence[Path],
    gate_ids: Sequence[str], coverage_ids: Sequence[str], evidence_paths: Sequence[Path],
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": ASSEMBLY_SCHEMA,
        "phase": phase,
        "combined_preprimary_seal": _content_ref(root, seal_path),
        "combined_preprimary_payload_sha256": seal["payload_sha256"],
        "all_sealed_inventory": dict(all_sealed["inventory_ref"]),
        "all_sealed_verification": {
            "all_artifacts_content_verified": True,
            "artifact_count": all_sealed["artifact_count"],
            "artifact_classes": all_sealed["artifact_classes"],
        },
        "inputs": [_content_ref(root, path) for path in inputs],
        "outputs": [_content_ref(root, path) for path in outputs],
        "gate_ids": list(gate_ids),
        "coverage_ids": list(coverage_ids),
        "evidence_files": [_content_ref(root, path) for path in evidence_paths],
        "invariants": {
            "manual_pass_evidence_forbidden": True,
            "all_results_source_derived": True,
            "exact_gate_coverage": True,
            "exact_complex_coverage": True,
        },
    }
    value["assembly_sha256"] = _sha(canonical_json_bytes(value)[:-1])
    return value


def assemble_nonreport(
    root: Path, *, structural_results: Path, event_report: Path, event_bundle: Path, model: Path,
    case_evaluation: Path, case_manifest: Path, all_sealed_inventory: Path,
    combined_seal: Path, output_dir: Path,
) -> dict[str, Path]:
    root = root.resolve(strict=True)
    seal = _verify_preprimary(root, combined_seal)
    scoring = _load_json(root / SCORING_REL, "scoring contract")
    gates = _load_json(root / GATES_REL, "gate contract")
    gate_order = [row.get("id") for row in gates.get("gates", []) if isinstance(row, Mapping)]
    if len(gate_order) != 30 or len(set(gate_order)) != 30 or gate_order[-1] != REPORT_GATE_ID:
        _fail("frozen gate contract is not exact ordered 30-gate v1.1")
    nonreport_order = gate_order[:-1]
    case_doc = _load_json(case_evaluation, "case evaluation")
    manifest_doc = _load_json(case_manifest, "case evaluator manifest")
    if case_doc.get("schema_version") != CASE_EVALUATION_SCHEMA or manifest_doc.get("schema_version") != CASE_MANIFEST_SCHEMA or manifest_doc.get("stage") != "CASE_EVALUATION":
        _fail("case evaluation/manifest schema or stage mismatch")
    seal_ref = _content_ref(root, combined_seal)
    _assert_manifest_ref(manifest_doc, "preprimary_seal", seal_ref)
    all_sealed = _verify_all_sealed(root, all_sealed_inventory, manifest_doc)
    _sealed_tool(root, seal, "primary_case_gate_evaluator", CASE_TOOL_REL)

    output_dir.mkdir(parents=True, exist_ok=True)
    if output_dir.is_symlink():
        _fail("output directory may not be a symlink")
    gate_ev: dict[str, tuple[str, Mapping[str, Any]]] = {}
    coverage_ev: dict[str, tuple[str, Mapping[str, Any]]] = {}
    evidence_paths: list[Path] = []

    structural_allowed = _policy(scoring, "structural-gate-harness-v1")["allowed_subjects"]["GATE"]
    for gate_id in structural_allowed:
        if gate_id == "PL-LED-002":
            continue
        evidence = _structural_evidence(root, seal, scoring, structural_results, gate_id)
        ref = _write_evidence(root, output_dir, evidence)
        gate_ev[gate_id] = (str(evidence["claimed_result"]), ref)
        evidence_paths.append(root / ref["path"])

    for kind, subject_id, target in (
        ("GATE", "PL-LED-002", gate_ev),
        ("COMPLEX_COVERAGE", "recursive_updates", coverage_ev),
    ):
        evidence = _event_evidence(root, seal, scoring, event_report, event_bundle, model, kind=kind, subject_id=subject_id)
        ref = _write_evidence(root, output_dir, evidence)
        target[subject_id] = (str(evidence["claimed_result"]), ref)
        evidence_paths.append(root / ref["path"])

    case_rows = case_doc.get("gate_results")
    coverage_rows = case_doc.get("coverage_results")
    if not isinstance(case_rows, list) or [row.get("subject_id") for row in case_rows if isinstance(row, Mapping)] != list(CASE_GATE_IDS):
        _fail("case evaluation does not contain exact ordered five case gates")
    if not isinstance(coverage_rows, list) or [row.get("subject_id") for row in coverage_rows if isinstance(row, Mapping)] != list(REQUIRED_COVERAGE[1:]):
        _fail("case evaluation does not contain exact ordered six coverage checks")
    for kind, ids, target in (("GATE", CASE_GATE_IDS, gate_ev), ("COMPLEX_COVERAGE", REQUIRED_COVERAGE[1:], coverage_ev)):
        for subject_id in ids:
            evidence = compile_case_evidence(
                root, evaluation_path=case_evaluation, manifest_path=case_manifest,
                scoring_path=root / SCORING_REL, seal_path=combined_seal,
                subject_kind=kind, subject_id=subject_id,
            )
            ref = _write_evidence(root, output_dir, evidence)
            target[subject_id] = (str(evidence["claimed_result"]), ref)
            evidence_paths.append(root / ref["path"])

    gate_bundle = {
        "schema_version": GATE_BUNDLE_SCHEMA,
        "contract_id": gates["contract_id"],
        "contract_version": gates["contract_version"],
        "correct_diagnosis_reported": False,
        "gate_results": _result_rows(gate_ev, nonreport_order, "gate_id"),
    }
    coverage_bundle = {"schema_version": COVERAGE_BUNDLE_SCHEMA, "checks": _result_rows(coverage_ev, REQUIRED_COVERAGE, "coverage_id")}
    gate_path = output_dir / "nonreport_gate_results.json"
    coverage_path = output_dir / "complex_coverage.json"
    _write_json(gate_path, gate_bundle); _write_json(coverage_path, coverage_bundle)
    manifest = _assembly_manifest(
        root, phase="NONREPORT", seal=seal, seal_path=combined_seal, all_sealed=all_sealed,
        inputs=[structural_results, event_report, event_bundle, model, case_evaluation, case_manifest, all_sealed_inventory],
        outputs=[gate_path, coverage_path], gate_ids=nonreport_order, coverage_ids=REQUIRED_COVERAGE,
        evidence_paths=evidence_paths,
    )
    manifest_path = output_dir / "nonreport_assembly.json"; _write_json(manifest_path, manifest)
    return {"gate_bundle": gate_path, "coverage_bundle": coverage_path, "assembly_manifest": manifest_path}


def assemble_final(
    root: Path, *, nonreport_gates: Path, coverage_bundle: Path, nonreport_assembly: Path,
    report_evaluation: Path, report_manifest: Path, all_sealed_inventory: Path,
    combined_seal: Path, output_dir: Path,
) -> dict[str, Path]:
    root = root.resolve(strict=True)
    seal = _verify_preprimary(root, combined_seal)
    gates = _load_json(root / GATES_REL, "gate contract")
    gate_order = [row.get("id") for row in gates.get("gates", []) if isinstance(row, Mapping)]
    if len(gate_order) != 30 or gate_order[-1] != REPORT_GATE_ID:
        _fail("frozen gate contract is not exact ordered 30-gate v1.1")
    nonreport_doc = _load_json(nonreport_gates, "nonreport gate bundle")
    coverage_doc = _load_json(coverage_bundle, "complex coverage bundle")
    assembly_doc = _load_json(nonreport_assembly, "nonreport assembly manifest")
    if assembly_doc.get("schema_version") != ASSEMBLY_SCHEMA or assembly_doc.get("phase") != "NONREPORT":
        _fail("nonreport assembly manifest schema/phase mismatch")
    if not _same_ref(assembly_doc.get("combined_preprimary_seal", {}), _content_ref(root, combined_seal)) or assembly_doc.get("combined_preprimary_payload_sha256") != seal.get("payload_sha256"):
        _fail("nonreport assembly is not bound to current combined seal")
    if not _same_ref(assembly_doc.get("all_sealed_inventory", {}), _content_ref(root, all_sealed_inventory)):
        _fail("nonreport assembly is not bound to supplied all-sealed inventory")
    # Re-verify every closure artifact without relying on the old manifest's booleans.
    dummy_manifest = {"inputs": [{"role": "all_sealed_artifacts_after_replay", **_content_ref(root, all_sealed_inventory)}]}
    all_sealed = _verify_all_sealed(root, all_sealed_inventory, dummy_manifest)
    _verify_bundle(root, nonreport_doc, expected_ids=gate_order[:-1], key="gate_id", kind="GATE")
    _verify_bundle(root, coverage_doc, expected_ids=REQUIRED_COVERAGE, key="coverage_id", kind="COMPLEX_COVERAGE")

    report_doc = _load_json(report_evaluation, "report evaluation")
    report_manifest_doc = _load_json(report_manifest, "report evaluator manifest")
    if (
        report_doc.get("schema_version") != CASE_EVALUATION_SCHEMA
        or report_manifest_doc.get("schema_version") != CASE_MANIFEST_SCHEMA
        or report_manifest_doc.get("stage") != "REPORT_CONSISTENCY"
    ):
        _fail("report evaluation/manifest schema or stage mismatch")
    rows = report_doc.get("gate_results")
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("subject_id") != REPORT_GATE_ID:
        _fail("report evaluation must contain exactly PL-REPORT-001")
    evidence = compile_case_evidence(
        root, evaluation_path=report_evaluation, manifest_path=report_manifest,
        scoring_path=root / SCORING_REL, seal_path=combined_seal,
        subject_kind="GATE", subject_id=REPORT_GATE_ID,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    report_ref = _write_evidence(root, output_dir, evidence)
    final_rows = [dict(row) for row in nonreport_doc["gate_results"]] + [{"gate_id": REPORT_GATE_ID, "result": evidence["claimed_result"], "evidence_refs": [report_ref]}]
    final_bundle = {
        "schema_version": GATE_BUNDLE_SCHEMA,
        "contract_id": gates["contract_id"],
        "contract_version": gates["contract_version"],
        "correct_diagnosis_reported": bool(nonreport_doc.get("correct_diagnosis_reported", False)),
        "gate_results": final_rows,
    }
    final_gate_path = output_dir / "final_gate_results.json"
    final_coverage_path = output_dir / "complex_coverage.json"
    _write_json(final_gate_path, final_bundle); _write_json(final_coverage_path, coverage_doc)
    _verify_bundle(root, final_bundle, expected_ids=gate_order, key="gate_id", kind="GATE")
    _verify_bundle(root, coverage_doc, expected_ids=REQUIRED_COVERAGE, key="coverage_id", kind="COMPLEX_COVERAGE")
    evidence_paths = [root / row["evidence_refs"][0]["path"] for row in final_rows]
    evidence_paths.extend(root / row["evidence_refs"][0]["path"] for row in coverage_doc["checks"])
    manifest = _assembly_manifest(
        root, phase="FINAL", seal=seal, seal_path=combined_seal, all_sealed=all_sealed,
        inputs=[nonreport_gates, coverage_bundle, nonreport_assembly, report_evaluation, report_manifest, all_sealed_inventory],
        outputs=[final_gate_path, final_coverage_path], gate_ids=gate_order, coverage_ids=REQUIRED_COVERAGE,
        evidence_paths=evidence_paths,
    )
    manifest_path = output_dir / "final_assembly.json"; _write_json(manifest_path, manifest)
    return {"gate_bundle": final_gate_path, "coverage_bundle": final_coverage_path, "assembly_manifest": manifest_path}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, default=Path(__file__).resolve().parents[2])
    sub = parser.add_subparsers(dest="command", required=True)
    non = sub.add_parser("assemble-nonreport")
    for name in ("structural-results", "event-report", "event-bundle", "model", "case-evaluation", "case-manifest", "all-sealed-inventory", "combined-seal", "output-dir"):
        non.add_argument(f"--{name}", required=True, type=Path)
    final = sub.add_parser("assemble-final")
    for name in ("nonreport-gates", "coverage-bundle", "nonreport-assembly", "report-evaluation", "report-manifest", "all-sealed-inventory", "combined-seal", "output-dir"):
        final.add_argument(f"--{name}", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "assemble-nonreport":
            result = assemble_nonreport(
                args.study_root, structural_results=args.structural_results, event_report=args.event_report,
                event_bundle=args.event_bundle, model=args.model, case_evaluation=args.case_evaluation,
                case_manifest=args.case_manifest, all_sealed_inventory=args.all_sealed_inventory,
                combined_seal=args.combined_seal, output_dir=args.output_dir,
            )
        else:
            result = assemble_final(
                args.study_root, nonreport_gates=args.nonreport_gates, coverage_bundle=args.coverage_bundle,
                nonreport_assembly=args.nonreport_assembly, report_evaluation=args.report_evaluation,
                report_manifest=args.report_manifest, all_sealed_inventory=args.all_sealed_inventory,
                combined_seal=args.combined_seal, output_dir=args.output_dir,
            )
        print(json.dumps({"status": "PASS", **{k: str(v) for k, v in result.items()}}, sort_keys=True))
        return 0
    except (AssemblyError, OSError, ValueError) as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
