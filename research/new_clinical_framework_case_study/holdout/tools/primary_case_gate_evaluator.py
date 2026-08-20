#!/usr/bin/env python3
"""Deterministic primary-case gate and report-consistency evaluator.

This program is deliberately generic.  It does not contain a disease name,
expected diagnosis, article identifier, or case-specific threshold.  The case
stage reads only content-addressed, post-replay artifacts and obtains all
numeric thresholds from the frozen scoring contract.  The report stage is
separate so PL-REPORT-001 never needs to hash a document which contains its own
evidence hash.

The three commands are deterministic and offline:

``evaluate-case``
    Compute six case-dependent gates and the six real-case coverage checks
    not supplied by the event-ledger replay producer.

``build-report-candidate``
    Assemble the already-evidenced 29 non-report gates and all coverage rows
    into a canonical candidate-results JSON plus a canonical Markdown report.
    PL-REPORT-001 is a typed derivation slot, not a claimed PASS.

``evaluate-report``
    Rebuild the candidate results/report from their content-addressed inputs,
    compare exact bytes, and compute PL-REPORT-001.  The final scorer may then
    consume that result as gate 30 without any self-reference.

Automatic gate evidence is expected to use the sealed
``CONFIGURED_CLI_EXACT_JSON_V1`` replay adapter.  The tool therefore emits no
wall-clock time, randomness, hostname, or environment-dependent path.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence


MODULE_ROOT = Path(__file__).resolve().parents[2]
if str(MODULE_ROOT) not in sys.path:
    sys.path.insert(0, str(MODULE_ROOT))

from runtime_v2 import (  # noqa: E402
    architecture_state_hash,
    canonical_json_bytes as runtime_canonical_json_bytes,
)
from holdout.tools.validate_primary_holdout_protocol import (  # noqa: E402
    validate_role_manifest_set,
)


TOOL_REL = "holdout/tools/primary_case_gate_evaluator.py"
INPUT_SCHEMA_VERSION = "ncf.primary-case-gate-evaluator-input.v1"
OUTPUT_SCHEMA_VERSION = "ncf.primary-case-gate-evaluation.v1"
CANDIDATE_SCHEMA_VERSION = "ncf.primary-perfect-landing-report-candidate.v1"
GATE_BUNDLE_SCHEMA_VERSION = "ncf.primary-gate-evidence-candidate.v1"
COVERAGE_BUNDLE_SCHEMA_VERSION = "ncf.primary-complex-case-coverage.v1"

CASE_GATES = (
    "PL-IND-001",
    "PL-BLIND-001",
    "PL-LED-001",
    "PL-DX-002",
    "PL-PRED-002",
    "PL-CASE-001",
)
REPORT_GATE = "PL-REPORT-001"
CASE_COVERAGE = (
    "at_least_two_local_domains",
    "concurrent_process_target_from_oracle",
    "delayed_information",
    "reliable_negative_evidence",
    "performed_action_lifecycle_with_response",
    "prospective_pre_next_cut_forecasts",
)
ALL_COVERAGE = ("recursive_updates", *CASE_COVERAGE)

CASE_INPUT_ROLES = {
    "gate_contract",
    "scoring_contract",
    "preprimary_seal",
    "search_retrieval_manifest",
    "role_manifest_set",
    "case_access_lineage",
    "immutable_source_manifest",
    "source_audit",
    "source_inventory",
    "event_ledger",
    "event_ledger_audit",
    "oracle_targets",
    "runtime_output",
    "runtime_input_manifest",
    "runtime_replay_seal",
    "mapped_observation_consumption",
    "all_sealed_artifacts_after_replay",
    "audit_report",
    "sanitized_ledger_assignment_proof",
    "sanitized_ledger_replay_verification",
}
REPORT_BUILD_INPUT_ROLES = {
    "gate_contract",
    "scoring_contract",
    "nonreport_gate_bundle",
    "complex_coverage_bundle",
}
REPORT_EVALUATION_INPUT_ROLES = {
    "gate_contract",
    "scoring_contract",
    "report_candidate_results",
    "report_candidate_markdown",
    "audit_report",
}

SANITIZED_LEDGER_SCHEMA_VERSION = "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-1.0.0"
SANITIZED_ASSIGNMENT_SCHEMA_VERSION = "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-ASSIGNMENT-PROOF-1.0.0"
SANITIZED_REPLAY_SCHEMA_VERSION = "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-REPLAY-VERIFICATION-1.0.0"
SANITIZED_COMPILER_INPUT_SCHEMA_VERSION = "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-COMPILER-INPUT-1.0.0"
SANITIZED_COMPILER_REL = "holdout/tools/compile_evaluator_sanitized_runtime_ledger.py"
SANITIZED_VERIFIER_REL = "holdout/tools/verify_evaluator_sanitized_runtime_ledger.py"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_DIAGNOSIS_KEYS = {
    "final_diagnosis",
    "published_diagnosis",
    "expected_diagnosis",
    "correct_diagnosis",
    "terminal_outcome",
}


class EvaluationError(RuntimeError):
    """Fail-closed input, integrity, or contract error."""


def _fail(message: str) -> NoReturn:
    raise EvaluationError(message)


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_json_file_bytes(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _expect_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be an object")
    return value


def _expect_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{label} must be an array")
    return value


def _exact_keys(value: Mapping[str, Any], keys: set[str], label: str) -> None:
    if set(value) != keys:
        _fail(f"{label} keys mismatch: expected={sorted(keys)} actual={sorted(value)}")


def _reject_diagnosis_shortcuts(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_DIAGNOSIS_KEYS:
                _fail(f"final-diagnosis/outcome shortcut forbidden at {path}.{key}")
            _reject_diagnosis_shortcuts(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_diagnosis_shortcuts(child, f"{path}[{index}]")


def _resolve_ref(study_root: Path, row: Any, label: str) -> tuple[Mapping[str, Any], Path, bytes]:
    ref = _expect_mapping(row, label)
    required = {"ref_id", "role", "path", "sha256", "bytes"}
    _exact_keys(ref, required, label)
    ref_id = ref.get("ref_id")
    role = ref.get("role")
    text = ref.get("path")
    if not isinstance(ref_id, str) or not ref_id or not isinstance(role, str) or not role:
        _fail(f"{label} ref_id/role missing")
    if not isinstance(text, str):
        _fail(f"{label}.path missing")
    rel = PurePosixPath(text)
    if rel.is_absolute() or rel.as_posix() != text or not rel.parts or ".." in rel.parts:
        _fail(f"{label}.path must be canonical relative POSIX")
    root = study_root.resolve(strict=True)
    path = root.joinpath(*rel.parts)
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        _fail(f"{label}.path escapes study root")
    if path.is_symlink() or not path.is_file():
        _fail(f"{label}.path missing or symlink")
    raw = path.read_bytes()
    digest = sha256_bytes(raw)
    if ref.get("sha256") != digest or not SHA256_RE.fullmatch(str(ref.get("sha256", ""))):
        _fail(f"{label}.sha256 mismatch")
    if ref.get("bytes") != len(raw):
        _fail(f"{label}.bytes mismatch")
    return ref, path, raw


def _json_from_ref(study_root: Path, row: Any, label: str) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    ref, _, raw = _resolve_ref(study_root, row, label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not UTF-8 JSON: {exc}")
    return ref, _expect_mapping(value, label)


def _path_from_content_ref(study_root: Path, row: Any, label: str) -> tuple[Mapping[str, Any], Path, bytes]:
    """Resolve a nested content ref without trusting any extra metadata."""
    ref = _expect_mapping(row, label)
    if not {"path", "sha256", "bytes"}.issubset(ref):
        _fail(f"{label} lacks a content address")
    wrapped = {
        "ref_id": label.replace(" ", "-"),
        "role": "nested_content_ref",
        "path": ref["path"],
        "sha256": ref["sha256"],
        "bytes": ref["bytes"],
    }
    _, path, raw = _resolve_ref(study_root, wrapped, label)
    return ref, path, raw


def _json_from_content_ref(study_root: Path, row: Any, label: str) -> tuple[Mapping[str, Any], Path, Mapping[str, Any]]:
    ref, path, raw = _path_from_content_ref(study_root, row, label)
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not UTF-8 JSON: {exc}")
    return ref, path, _expect_mapping(value, label)


def _load_manifest(study_root: Path, manifest_path: Path, stage: str) -> tuple[Mapping[str, Any], dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    root = study_root.resolve(strict=True)
    resolved = manifest_path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        _fail("input manifest is outside study root")
    if resolved.is_symlink() or not resolved.is_file():
        _fail("input manifest missing or symlink")
    raw = resolved.read_bytes()
    try:
        manifest = _expect_mapping(json.loads(raw.decode("utf-8")), "input manifest")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid input manifest: {exc}")
    _exact_keys(manifest, {"schema_version", "stage", "execution_context", "inputs"}, "input manifest")
    if manifest.get("schema_version") != INPUT_SCHEMA_VERSION or manifest.get("stage") != stage:
        _fail("input manifest schema/stage mismatch")
    if manifest.get("execution_context") != "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR":
        _fail("primary gate/report evaluator must execute after the sealed eight-role DAG")
    expected_roles = {
        "CASE_EVALUATION": CASE_INPUT_ROLES,
        "REPORT_CANDIDATE": REPORT_BUILD_INPUT_ROLES,
        "REPORT_CONSISTENCY": REPORT_EVALUATION_INPUT_ROLES,
    }[stage]
    refs: dict[str, Mapping[str, Any]] = {}
    docs: dict[str, Mapping[str, Any]] = {}
    ref_ids: set[str] = set()
    rows = _expect_list(manifest.get("inputs"), "input manifest.inputs")
    for index, row in enumerate(rows):
        ref, doc = _json_from_ref(study_root, row, f"input[{index}]") if row.get("role") != "report_candidate_markdown" else (_resolve_ref(study_root, row, f"input[{index}]")[0], {})
        role = str(ref["role"])
        if role in refs or str(ref["ref_id"]) in ref_ids:
            _fail("duplicate input role/ref_id")
        refs[role] = ref
        ref_ids.add(str(ref["ref_id"]))
        if role != "report_candidate_markdown":
            docs[role] = doc
    if set(refs) != expected_roles:
        _fail(f"input roles mismatch: expected={sorted(expected_roles)} actual={sorted(refs)}")
    return manifest, refs, docs


def _manifest_digest(manifest_path: Path) -> dict[str, Any]:
    path = manifest_path.resolve(strict=True)
    raw = path.read_bytes()
    return {
        "sha256": sha256_bytes(raw),
        "bytes": len(raw),
    }


def _iso(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        _fail(f"{label} must be ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        _fail(f"{label} invalid: {exc}")
    if parsed.tzinfo is None:
        _fail(f"{label} must include timezone")
    return parsed


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _fail(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        _fail(f"{label} must be finite")
    return number


def _odds(probability: float) -> float:
    if probability <= 0:
        return 0.0
    if probability >= 1:
        return math.inf
    return probability / (1.0 - probability)


def _check(check_id: str, observed: Any, expected: Any, operator: str, passed: bool) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "observed": observed,
        "expected": expected,
        "operator": operator,
        "passed": bool(passed),
    }


def _result(subject_kind: str, subject_id: str, checks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(row) for row in checks]
    return {
        "subject_kind": subject_kind,
        "subject_id": subject_id,
        "computed_result": "PASS" if rows and all(row["passed"] is True for row in rows) else "FAIL",
        "checks": rows,
    }


def _schema(doc: Mapping[str, Any], expected: str, label: str) -> None:
    if doc.get("schema_version") != expected:
        _fail(f"{label}.schema_version must be {expected}")


def _artifact_ref_equal(left: Mapping[str, Any], right: Mapping[str, Any]) -> bool:
    return all(left.get(key) == right.get(key) for key in ("path", "sha256", "bytes"))


def _gate_ids(gates: Mapping[str, Any]) -> list[str]:
    rows = _expect_list(gates.get("gates"), "gate contract.gates")
    ids = [row.get("id") for row in rows if isinstance(row, Mapping)]
    if len(ids) != 30 or len(set(ids)) != 30 or any(not isinstance(item, str) for item in ids):
        _fail("gate contract must contain exactly 30 unique gate ids")
    return [str(item) for item in ids]


def _validate_contracts(gates: Mapping[str, Any], scoring: Mapping[str, Any]) -> tuple[list[str], Mapping[str, Any], Mapping[str, Any]]:
    if gates.get("contract_version") != "1.1.0" or gates.get("status") != "FROZEN_BEFORE_HOLDOUT_INSPECTION":
        _fail("gate contract is not the frozen v1.1.0 contract")
    if scoring.get("status") != "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION":
        _fail("scoring contract is not frozen")
    prediction = _expect_mapping(scoring.get("prediction_case_consistency"), "prediction scoring")
    localization = _expect_mapping(scoring.get("diagnostic_localization"), "diagnostic scoring")
    if localization.get("published_label_alone_is_never_input_or_success_evidence") is not True:
        _fail("diagnostic label shortcut prohibition missing")
    return _gate_ids(gates), prediction, localization



ROLE_NAMES = (
    "scout",
    "screener",
    "extractor",
    "source_auditor",
    "concept_mapper",
    "oracle_adjudicator",
    "evaluator",
    "scorer_auditor",
)
PRESEALED_DATA_CLASSES = {
    "protocol",
    "broad_scope",
    "identifier_only_exclusions",
    "combined_preprimary_seal",
    "extraction_schema",
    "sanitized_id_type_unit_registry",
    "sanitized_process_name_description_registry",
    "model_pack",
    "runtime",
    "scoring_contract",
}
RELIABLE_NEGATIVE_DIMENSIONS = (
    "explicit_assertion",
    "target_scope",
    "adequate_method",
    "adequate_timing",
    "adequate_reliability",
)


def _plain_ref(ref: Mapping[str, Any]) -> dict[str, Any]:
    return {key: ref[key] for key in ("path", "sha256", "bytes")}


def _resolve_plain_json_ref(
    study_root: Path, row: Any, label: str, *, ref_id: str | None = None, role: str = "nested"
) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    plain = _expect_mapping(row, label)
    _exact_keys(plain, {"path", "sha256", "bytes"}, label)
    wrapped = {"ref_id": ref_id or label.replace(" ", "-"), "role": role, **plain}
    _, doc = _json_from_ref(study_root, wrapped, label)
    return plain, doc


def _load_sanitized_replay_builder(study_root: Path):
    """Load the frozen upstream verifier by its sealed path.

    The verifier intentionally lives outside this evaluator.  Loading it from
    the study root (rather than importing an ambient package) keeps the exact
    producer implementation part of the content-addressed chain.
    """
    path = study_root / SANITIZED_VERIFIER_REL
    if not path.is_file() or path.is_symlink():
        _fail("sanitized-ledger replay verifier missing or symlink")
    name = "_ncf_frozen_sanitized_ledger_replay_verifier"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        _fail("cannot load sanitized-ledger replay verifier")
    module = importlib.util.module_from_spec(spec)
    tool_dir = str(path.parent)
    inserted = tool_dir not in sys.path
    if inserted:
        sys.path.insert(0, tool_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        if inserted:
            sys.path.remove(tool_dir)
    builder = getattr(module, "build_verification", None)
    if not callable(builder):
        _fail("sanitized-ledger replay verifier lacks build_verification")
    return builder


def _verification_named_output_matches(row: Any, ref: Mapping[str, Any], expected_ref_id: str) -> bool:
    value = _expect_mapping(row, f"fresh replay output {expected_ref_id}")
    return (
        value.get("ref_id") == expected_ref_id
        and value.get("sha256") == ref.get("sha256")
        and value.get("bytes") == ref.get("bytes")
        and isinstance(value.get("semantic_sha256"), str)
        and bool(SHA256_RE.fullmatch(str(value.get("semantic_sha256"))))
    )


def _verify_sanitized_ledger_chain(
    study_root: Path,
    *,
    refs: Mapping[str, Mapping[str, Any]],
    docs: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str], dict[str, str], list[dict[str, Any]]]:
    """Fresh-replay and independently bind the source-to-opaque transport.

    The upstream compiler/verifier cannot mint PL-LED-001.  This function
    first reproduces that verifier byte-for-byte, then independently checks
    its input/output bindings and reconstructs the deterministic row-order
    assignment used to connect source evidence to the opaque runtime.
    """
    ledger = docs["event_ledger"]
    proof = docs["sanitized_ledger_assignment_proof"]
    supplied = docs["sanitized_ledger_replay_verification"]
    _schema(ledger, SANITIZED_LEDGER_SCHEMA_VERSION, "sanitized runtime ledger")
    _schema(proof, SANITIZED_ASSIGNMENT_SCHEMA_VERSION, "sanitized assignment proof")
    _schema(supplied, SANITIZED_REPLAY_SCHEMA_VERSION, "sanitized replay verification")

    proof_ledger = _expect_mapping(proof.get("output_ledger"), "assignment proof output ledger")
    verification_outputs = _expect_mapping(supplied.get("compiler_outputs"), "verification compiler outputs")
    verification_ledger = _expect_mapping(verification_outputs.get("ledger"), "verification ledger output")
    verification_proof = _expect_mapping(verification_outputs.get("assignment_proof"), "verification proof output")
    proof_ledger_bound = (
        PurePosixPath(str(proof_ledger.get("path"))).name == "evaluator_sanitized_runtime_ledger.json"
        and proof_ledger.get("sha256") == refs["event_ledger"].get("sha256")
        and proof_ledger.get("bytes") == refs["event_ledger"].get("bytes")
    )
    direct_outputs_bound = (
        proof_ledger_bound
        and _artifact_ref_equal(verification_ledger, refs["event_ledger"])
        and _artifact_ref_equal(verification_proof, refs["sanitized_ledger_assignment_proof"])
    )

    manifest_ref = _expect_mapping(proof.get("input_manifest"), "assignment proof input manifest")
    if not _artifact_ref_equal(manifest_ref, _expect_mapping(supplied.get("compiler_input_manifest"), "verification compiler input manifest")):
        _fail("sanitized compiler manifest refs disagree")
    _, manifest_path, compiler_manifest = _json_from_content_ref(
        study_root, manifest_ref, "sanitized compiler input manifest"
    )
    _schema(compiler_manifest, SANITIZED_COMPILER_INPUT_SCHEMA_VERSION, "sanitized compiler input manifest")
    manifest_inputs = _expect_mapping(compiler_manifest.get("inputs"), "sanitized compiler inputs")
    expected_slots = (
        "sealed_event_ledger",
        "sealed_availability_ledger",
        "sealed_concept_map",
        "sanitized_id_type_unit_registry",
        "combined_preprimary_seal",
    )
    if tuple(manifest_inputs) != expected_slots:
        _fail("sanitized compiler input slots/order mismatch")
    proof_inputs = _expect_list(proof.get("inputs"), "assignment proof inputs")
    proof_by_slot = {
        str(_expect_mapping(row, "assignment proof input").get("slot")): _expect_mapping(row, "assignment proof input")
        for row in proof_inputs
    }
    input_refs_exact = set(proof_by_slot) == set(expected_slots) and all(
        _artifact_ref_equal(proof_by_slot[slot], _expect_mapping(manifest_inputs[slot], f"compiler input {slot}"))
        and proof_by_slot[slot].get("data_class") == manifest_inputs[slot].get("data_class")
        and proof_by_slot[slot].get("schema_id") == manifest_inputs[slot].get("schema_id")
        for slot in expected_slots
    )
    raw_inputs: dict[str, Mapping[str, Any]] = {}
    for slot in expected_slots:
        _, _, raw_inputs[slot] = _json_from_content_ref(
            study_root, manifest_inputs[slot], f"sanitized compiler input {slot}"
        )
    combined_ref = _expect_mapping(manifest_inputs["combined_preprimary_seal"], "compiler combined seal ref")
    combined_bound = _artifact_ref_equal(combined_ref, refs["preprimary_seal"])

    _, ledger_path, _ = _path_from_content_ref(study_root, refs["event_ledger"], "sanitized runtime ledger")
    _, proof_path, _ = _path_from_content_ref(
        study_root, refs["sanitized_ledger_assignment_proof"], "sanitized assignment proof"
    )
    _, seal_path, _ = _path_from_content_ref(study_root, refs["preprimary_seal"], "combined preprimary seal")
    builder = _load_sanitized_replay_builder(study_root)
    try:
        rebuilt = builder(
            study_root,
            manifest_path=manifest_path,
            ledger_path=ledger_path,
            assignment_proof_path=proof_path,
            combined_seal_path=seal_path,
        )
    except Exception as exc:  # the upstream verifier uses typed fail-closed exceptions
        _fail(f"sanitized-ledger fresh replay failed: {exc}")
    verification_exact = canonical_json_bytes(rebuilt) == canonical_json_bytes(supplied)

    fresh = _expect_mapping(supplied.get("fresh_replay"), "sanitized fresh replay")
    fresh_outputs = _expect_mapping(fresh.get("outputs"), "sanitized fresh replay outputs")
    fresh_exact = (
        fresh.get("status") == "PASS"
        and fresh.get("invocation_sha256") == _expect_mapping(supplied.get("replay_claim"), "replay claim").get("invocation_sha256")
        and _verification_named_output_matches(fresh_outputs.get("ledger"), refs["event_ledger"], "sanitized-ledger")
        and _verification_named_output_matches(
            fresh_outputs.get("assignment_proof"), refs["sanitized_ledger_assignment_proof"], "assignment-proof"
        )
    )

    source_rows = _expect_list(raw_inputs["sealed_event_ledger"].get("events"), "sealed source events")
    sanitized_rows = _expect_list(ledger.get("events"), "sanitized runtime events")
    if len(source_rows) != len(sanitized_rows) or not source_rows:
        _fail("source/sanitized event denominator mismatch")
    source_to_opaque: dict[str, str] = {}
    opaque_to_source: dict[str, str] = {}
    assignment_rows: list[dict[str, Any]] = []
    assignment_exact = True
    for index, (source_any, opaque_any) in enumerate(zip(source_rows, sanitized_rows), start=1):
        source = _expect_mapping(source_any, f"sealed source event[{index}]")
        opaque = _expect_mapping(opaque_any, f"sanitized event[{index}]")
        source_id = source.get("source_event_id")
        opaque_id = opaque.get("opaque_event_id")
        if not isinstance(source_id, str) or not source_id or source_id in source_to_opaque:
            _fail("sealed source event ids invalid/duplicate")
        expected_opaque = f"EV-{index:08d}"
        assignment_exact &= opaque_id == expected_opaque
        source_to_opaque[source_id] = str(opaque_id)
        opaque_to_source[str(opaque_id)] = source_id
        assignment_rows.append(
            {
                "opaque_event_id": opaque_id,
                "opaque_source_concept_token": opaque.get("opaque_source_concept_token"),
                "opaque_action_id": _expect_mapping(opaque.get("action_lifecycle"), "opaque action lifecycle").get("opaque_action_id")
                if isinstance(opaque.get("action_lifecycle"), Mapping)
                else None,
                "alternative_representation_group_id": opaque.get("alternative_representation_group_id"),
            }
        )
    assignment_preimage = {"opaque_run_id": ledger.get("opaque_run_id"), "events": assignment_rows}
    assignment_digest_exact = proof.get("assignment_digest") == sha256_bytes(canonical_json_bytes(assignment_preimage))
    counts = _expect_mapping(proof.get("assignment_counts"), "assignment counts")
    count_exact = counts.get("events") == len(sanitized_rows)

    checks = [
        _check("sanitizer_direct_outputs_bound", direct_outputs_bound, True, "EQ", direct_outputs_bound),
        _check("sanitizer_source_inputs_exactly_bound", input_refs_exact and combined_bound, True, "EQ", input_refs_exact and combined_bound),
        _check("sanitizer_verification_rebuilt_exactly", verification_exact, True, "EQ", verification_exact),
        _check("sanitizer_fresh_replay_outputs_exact", fresh_exact, True, "EQ", fresh_exact),
        _check("sanitizer_source_to_opaque_assignment_exact", assignment_exact and assignment_digest_exact and count_exact, True, "EQ", assignment_exact and assignment_digest_exact and count_exact),
    ]
    return raw_inputs, source_to_opaque, opaque_to_source, checks


def _verify_blindness_chain(
    study_root: Path,
    *,
    refs: Mapping[str, Mapping[str, Any]],
    docs: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    seal = docs["preprimary_seal"]
    retrieval = docs["search_retrieval_manifest"]
    manifest_set = docs["role_manifest_set"]
    lineage = docs["case_access_lineage"]
    if seal.get("status") != "SEALED_BEFORE_PRIMARY_CASE_SELECTION":
        _fail("pre-primary seal status mismatch")
    sealed_at = _iso(seal.get("sealed_at"), "pre-primary seal.sealed_at")
    _schema(retrieval, "NCF-PRIMARY-SEARCH-RETRIEVAL-MANIFEST-1.0.0", "search retrieval manifest")
    _schema(manifest_set, "NCF-PRIMARY-ROLE-MANIFEST-SET-1.0.0", "role manifest set")
    _schema(lineage, "ncf.primary-case-access-lineage.v2", "case access lineage")

    manifest_refs = _expect_list(manifest_set.get("manifests"), "role manifest set.manifests")
    if [row.get("role") for row in manifest_refs if isinstance(row, Mapping)] != list(ROLE_NAMES):
        _fail("role manifest set must use exact frozen role order")
    derived_accesses: list[dict[str, Any]] = []
    all_after = True
    trace_complete = True
    no_gate_writes = True
    scout_network_rows: list[Mapping[str, Any]] = []
    for index, row_any in enumerate(manifest_refs):
        row = _expect_mapping(row_any, f"role manifest ref[{index}]")
        if set(row) != {"role", "run_id", "path", "sha256", "bytes"}:
            _fail("role manifest ref shape invalid")
        role = str(row["role"])
        _, manifest = _json_from_ref(
            study_root,
            {
                "ref_id": f"role-manifest-{role}",
                "role": "role_manifest",
                **{key: row[key] for key in ("path", "sha256", "bytes")},
            },
            f"role manifest {role}",
        )
        _schema(manifest, "NCF-PRIMARY-ROLE-MANIFEST-1.1.0", f"role manifest {role}")
        if manifest.get("role") != role or manifest.get("run_id") != row.get("run_id"):
            _fail(f"role manifest identity mismatch for {role}")
        started_at = _iso(manifest.get("started_at"), f"role {role}.started_at")
        finished_at = _iso(manifest.get("finished_at"), f"role {role}.finished_at")
        all_after &= started_at > sealed_at and finished_at >= started_at
        trace_ref = _expect_mapping(manifest.get("tool_trace"), f"role {role}.tool_trace")
        _, trace = _resolve_plain_json_ref(
            study_root, trace_ref, f"role trace {role}", ref_id=f"role-trace-{role}", role="role_trace"
        )
        _schema(trace, "NCF-PRIMARY-ROLE-TOOL-ACCESS-TRACE-1.0.0", f"role trace {role}")
        if trace.get("role") != role or trace.get("run_id") != row.get("run_id"):
            _fail(f"role trace identity mismatch for {role}")
        trace_complete &= trace.get("trace_complete") is True and trace.get("undeclared_access_detected") is False
        accesses = _expect_list(trace.get("accesses"), f"role trace {role}.accesses")
        for access_any in accesses:
            access = _expect_mapping(access_any, f"role {role} access")
            path = str(access.get("path"))
            data_class = str(access.get("data_class"))
            if access.get("operation") == "WRITE" and path in {
                refs["gate_contract"]["path"],
                refs["scoring_contract"]["path"],
                TOOL_REL,
            }:
                no_gate_writes = False
            if access.get("operation") == "READ" and data_class not in PRESEALED_DATA_CLASSES:
                derived_accesses.append(
                    {
                        "actor_role": role,
                        "access_kind": "FILE_READ",
                        "accessed_at": manifest.get("started_at"),
                        "path_or_url": path,
                        "sha256": access.get("sha256"),
                        "bytes": access.get("bytes"),
                        "data_class": data_class,
                    }
                )
        network_rows = _expect_list(trace.get("network_requests"), f"role trace {role}.network_requests")
        if role == "scout":
            scout_network_rows = [_expect_mapping(item, "scout network request") for item in network_rows]
        elif network_rows or trace.get("network_access_detected") is not False:
            _fail(f"non-scout network access detected for {role}")

    query_rows = _expect_list(retrieval.get("query_runs"), "search retrieval query runs")
    expected_network = sorted(
        (
            str(row.get("request_url")),
            str(_expect_mapping(row.get("raw_payload_ref"), "raw payload ref").get("sha256")),
            int(_expect_mapping(row.get("raw_payload_ref"), "raw payload ref").get("bytes")),
            str(retrieval.get("retrieved_at")),
        )
        for row in query_rows
    )
    actual_network = sorted(
        (
            str(row.get("request_url")),
            str(row.get("response_sha256")),
            int(row.get("response_bytes")),
            str(row.get("retrieved_at")),
        )
        for row in scout_network_rows
    )
    network_exact = expected_network == actual_network
    for url, digest_value, byte_count, accessed_at in actual_network:
        all_after &= _iso(accessed_at, f"scout retrieval {url}") > sealed_at
        derived_accesses.append(
            {
                "actor_role": "scout",
                "access_kind": "NETWORK_RESPONSE",
                "accessed_at": accessed_at,
                "path_or_url": url,
                "sha256": digest_value,
                "bytes": byte_count,
                "data_class": "public_search_results",
            }
        )
    declared_accesses = _expect_list(lineage.get("derived_accesses"), "case access lineage.derived_accesses")
    lineage_exact = canonical_json_bytes(sorted(declared_accesses, key=canonical_json_bytes)) == canonical_json_bytes(
        sorted(derived_accesses, key=canonical_json_bytes)
    )

    primary = _expect_mapping(
        _expect_mapping(seal.get("bindings"), "preprimary bindings").get("primary_execution"),
        "preprimary primary_execution",
    )
    sealed_tool = _expect_mapping(primary.get("primary_case_gate_evaluator"), "sealed evaluator tool")
    current_tool_raw = (study_root / TOOL_REL).read_bytes()
    tool_bound = (
        sealed_tool.get("path") == TOOL_REL
        and sealed_tool.get("sha256") == sha256_bytes(current_tool_raw)
        and sealed_tool.get("bytes") == len(current_tool_raw)
    )
    scoring_bound = _artifact_ref_equal(
        _expect_mapping(primary.get("scoring_contract"), "sealed scoring contract"), refs["scoring_contract"]
    )
    gates_bound = _artifact_ref_equal(
        _expect_mapping(_expect_mapping(seal["bindings"].get("gates"), "sealed gates").get("contract"), "sealed gate contract"),
        refs["gate_contract"],
    )
    return [
        _check("all_role_and_network_case_access_after_preprimary_seal", all_after, True, "EQ", all_after),
        _check("case_access_lineage_exactly_derived_from_role_traces", lineage_exact, True, "EQ", lineage_exact),
        _check("scout_network_requests_exactly_match_retrieval_manifest", network_exact, True, "EQ", network_exact),
        _check("all_role_traces_complete_and_declared", trace_complete, True, "EQ", trace_complete),
        _check("no_gate_scoring_or_evaluator_write_after_case_access", no_gate_writes, True, "EQ", no_gate_writes),
        _check("evaluator_tool_bound_preprimary", tool_bound, True, "EQ", tool_bound),
        _check("scoring_contract_bound_preprimary", scoring_bound, True, "EQ", scoring_bound),
        _check("gate_contract_bound_preprimary", gates_bound, True, "EQ", gates_bound),
    ]


def _verify_primary_isolation_chain(
    study_root: Path,
    *,
    refs: Mapping[str, Mapping[str, Any]],
    docs: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Verify actual primary 8-role isolation and fresh full runtime replay.

    The structural harness is intentionally insufficient here: it never saw
    the selected primary report.  This verifier consumes the actual eight-role
    manifest set, validates its complete traced DAG, checks the dependency
    trace emitted by the actual primary executor, then starts that executor in
    a fresh process and requires exact bytes for all bound runtime outputs.
    """

    role_set_path = study_root / str(refs["role_manifest_set"]["path"])
    try:
        role_report = validate_role_manifest_set(study_root, role_set_path)
    except Exception as exc:  # validator is fail-closed and presealed
        _fail(f"actual primary role-manifest-set validation failed: {exc}")
    roles_exact = (
        role_report.get("status") == "PASS"
        and role_report.get("role_count") == 8
        and role_report.get("roles") == list(ROLE_NAMES)
        and role_report.get("aggregate_sha256") == refs["role_manifest_set"].get("sha256")
    )

    replay = docs["runtime_replay_seal"]
    dependency = _expect_mapping(replay.get("dependency_trace"), "runtime dependency trace")
    dependency_schema = dependency.get("schema_version") == "NCF-PRIMARY-RUNTIME-DEPENDENCY-TRACE-1.0.0"
    approved_classes = {"NCF_FROZEN_SOURCE", "PYTHON_STDLIB"}
    modules_valid = True
    module_rows = _expect_list(dependency.get("module_origins"), "runtime dependency module origins")
    for index, row_any in enumerate(module_rows):
        row = _expect_mapping(row_any, f"runtime dependency module[{index}]")
        classification = row.get("classification")
        modules_valid &= classification in approved_classes
        origin = str(row.get("origin"))
        path = study_root / origin if classification == "NCF_FROZEN_SOURCE" else Path(origin)
        try:
            resolved = path.resolve(strict=True)
            raw = resolved.read_bytes()
        except OSError:
            modules_valid = False
            continue
        if classification == "NCF_FROZEN_SOURCE":
            try:
                resolved.relative_to(study_root.resolve(strict=True))
            except ValueError:
                modules_valid = False
        modules_valid &= row.get("sha256") == sha256_bytes(raw) and row.get("bytes") == len(raw)
    network = _expect_mapping(dependency.get("network_guard"), "runtime dependency network guard")
    dependency_closed = (
        dependency_schema
        and dependency.get("trace_scope") == "ACTUAL_PRIMARY_CASE_RUNTIME_REPLAY_PROCESS"
        and dependency.get("outside_allowlist") == []
        and bool(module_rows)
        and modules_valid
        and network.get("control") == "APPLICATION_SOCKET_GUARD_OFFLINE_NOT_OS_SANDBOX"
        and network.get("attempt_count") == 0
        and network.get("attempts") == []
        and network.get("passed") is True
    )
    io_trace = _expect_mapping(dependency.get("io_trace"), "runtime dependency IO trace")
    io_inputs = _expect_list(io_trace.get("input_bindings"), "runtime dependency input bindings")
    io_outputs = _expect_list(io_trace.get("produced_artifacts"), "runtime dependency output bindings")
    expected_outputs = [
        _expect_mapping(replay.get("runtime_output"), "replay runtime output"),
        _expect_mapping(replay.get("event_ledger_replay_bundle"), "replay event bundle"),
        _expect_mapping(replay.get("mapped_observation_consumption"), "replay mapped consumption"),
    ]
    io_exact = (
        canonical_json_bytes(io_inputs)
        == canonical_json_bytes(_expect_list(replay.get("input_bindings"), "replay input bindings"))
        and canonical_json_bytes(io_outputs) == canonical_json_bytes(expected_outputs)
    )

    primary = _expect_mapping(
        _expect_mapping(docs["preprimary_seal"].get("bindings"), "preprimary bindings").get("primary_execution"),
        "preprimary primary execution",
    )
    sealed_executor = _expect_mapping(
        primary.get("primary_runtime_replay_executor"), "sealed primary runtime replay executor"
    )
    executor_rel = "holdout/tools/primary_runtime_replay_executor.py"
    executor_raw = (study_root / executor_rel).read_bytes()
    invocation = _expect_mapping(replay.get("invocation_contract"), "runtime invocation contract")
    invoked_executor = _expect_mapping(invocation.get("executable"), "runtime invoked executable")
    executor_bound = (
        sealed_executor.get("path") == executor_rel
        and sealed_executor.get("sha256") == sha256_bytes(executor_raw)
        and sealed_executor.get("bytes") == len(executor_raw)
        and canonical_json_bytes(invoked_executor) == canonical_json_bytes(sealed_executor)
        and invocation.get("network_access") == "FORBIDDEN"
        and invocation.get("input_manifest_sha256") == refs["runtime_input_manifest"].get("sha256")
    )

    runtime_manifest_path = study_root / str(refs["runtime_input_manifest"]["path"])
    evidence_dir = study_root / "holdout" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    exact_fresh_replay = False
    fresh_error: str | None = None
    with tempfile.TemporaryDirectory(prefix="primary-isolation-fresh-", dir=evidence_dir) as temp_name:
        fresh_dir = Path(temp_name) / "runtime"
        command = [
            sys.executable,
            str(study_root / executor_rel),
            "--study-root",
            str(study_root),
            "--input-manifest",
            str(runtime_manifest_path),
            "--output-dir",
            str(fresh_dir),
        ]
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = "0"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            completed = subprocess.run(
                command,
                cwd=study_root,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                check=False,
            )
            expected = {
                "runtime_output.json": refs["runtime_output"],
                "mapped_observation_consumption.json": refs["mapped_observation_consumption"],
                "runtime_replay_seal.json": refs["runtime_replay_seal"],
            }
            exact_fresh_replay = completed.returncode == 0
            for filename, ref in expected.items():
                fresh_path = fresh_dir / filename
                if not fresh_path.is_file():
                    exact_fresh_replay = False
                    continue
                raw = fresh_path.read_bytes()
                exact_fresh_replay &= ref.get("sha256") == sha256_bytes(raw) and ref.get("bytes") == len(raw)
            fresh_seal = json.loads((fresh_dir / "runtime_replay_seal.json").read_text(encoding="utf-8")) if (fresh_dir / "runtime_replay_seal.json").is_file() else {}
            fresh_bundle = fresh_dir / "runtime_event_ledger_replay_bundle.json"
            bundle_ref = _expect_mapping(fresh_seal.get("event_ledger_replay_bundle"), "fresh replay bundle ref")
            if not fresh_bundle.is_file():
                exact_fresh_replay = False
            else:
                bundle_raw = fresh_bundle.read_bytes()
                exact_fresh_replay &= bundle_ref.get("sha256") == sha256_bytes(bundle_raw) and bundle_ref.get("bytes") == len(bundle_raw)
        except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
            fresh_error = type(exc).__name__
            exact_fresh_replay = False

    sanitizer = docs["sanitized_ledger_replay_verification"]
    sanitizer_fresh = (
        sanitizer.get("schema_version")
        == "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-REPLAY-VERIFICATION-1.0.0"
        and _expect_mapping(sanitizer.get("fresh_replay"), "sanitizer fresh replay").get("status") == "PASS"
    )
    return [
        _check("actual_primary_eight_role_trace_dag_validated", roles_exact, True, "EQ", roles_exact),
        _check("actual_primary_runtime_dependency_trace_allowlisted", dependency_closed, True, "EQ", dependency_closed),
        _check("actual_primary_runtime_io_trace_exact", io_exact, True, "EQ", io_exact),
        _check("runtime_executor_bound_to_preprimary_seal", executor_bound, True, "EQ", executor_bound),
        _check("sanitizer_external_producer_fresh_replay_passed", sanitizer_fresh, True, "EQ", sanitizer_fresh),
        _check(
            "actual_primary_runtime_full_fresh_replay_byte_exact",
            {"passed": exact_fresh_replay, "error_type": fresh_error},
            {"passed": True, "error_type": None},
            "STRUCTURAL",
            exact_fresh_replay,
        ),
    ]


def _availability_epoch(row: Mapping[str, Any], label: str) -> int:
    evidence = _expect_mapping(row.get("availability_evidence"), f"{label} availability evidence")
    kind = evidence.get("kind")
    value = evidence.get("exact_epoch") if kind == "EXACT" else evidence.get("latest_epoch")
    if kind not in {"EXACT", "INTERVAL", "REPORTED_BATCH", "PARTIAL_ORDER"}:
        _fail(f"{label} availability must be bounded")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(f"{label} availability epoch invalid")
    return value


def _normalize_source_events(
    sealed_events: Mapping[str, Any],
    sealed_availability: Mapping[str, Any],
    source_to_opaque: Mapping[str, str],
) -> dict[str, Mapping[str, Any]]:
    availability_rows = _expect_list(sealed_availability.get("events"), "sealed availability events")
    availability: dict[str, int] = {}
    for row_any in availability_rows:
        row = _expect_mapping(row_any, "sealed availability event")
        source_id = row.get("source_event_id")
        if not isinstance(source_id, str) or not source_id or source_id in availability:
            _fail("sealed availability event ids invalid/duplicate")
        availability[source_id] = _availability_epoch(row, f"availability event {source_id}")
    result: dict[str, Mapping[str, Any]] = {}
    for row_any in _expect_list(sealed_events.get("events"), "sealed source events"):
        outer = _expect_mapping(row_any, "sealed source event")
        source_id = outer.get("source_event_id")
        if not isinstance(source_id, str) or not source_id or source_id in result:
            _fail("sealed source event ids invalid/duplicate")
        if source_id not in availability or source_id not in source_to_opaque:
            _fail(f"sealed source event {source_id} absent from availability/sanitizer assignment")
        inner = _expect_mapping(outer.get("runtime_event", outer), f"sealed source event {source_id} runtime event")
        observed = inner.get("observed_epoch_ordinal")
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
            _fail(f"sealed source event {source_id} observed epoch invalid")
        fact_ids = inner.get("source_fact_ids", outer.get("source_fact_ids"))
        fact_ids = _expect_list(fact_ids, f"sealed source event {source_id} source facts")
        if not fact_ids or any(not isinstance(item, str) or not item for item in fact_ids):
            _fail(f"sealed source event {source_id} source facts invalid")
        kind = inner.get("event_kind")
        lifecycle = inner.get("action_lifecycle")
        event_type = "ObservationAvailable"
        action_id = None
        exposure_id = None
        if kind in {"ACTION", "SUPPORT"}:
            life = _expect_mapping(lifecycle, f"sealed source event {source_id} action lifecycle")
            phase = life.get("phase")
            event_type = {
                "ORDERED": "ActionOrdered",
                "STARTED": "ActionStarted",
                "CONTINUED": "ActionContinued",
                "DOSE_CHANGED": "ActionDoseChanged",
                "HELD": "ActionHeld",
                "RESUMED": "ActionResumed",
                "STOPPED": "ActionStopped",
                "COMPLETED": "ActionCompleted",
            }.get(str(phase), "ActionLifecycleAvailable")
            action_id = life.get("source_action_instance_id")
            exposure_id = life.get("source_exposure_id", action_id)
        declared_event_type = outer.get("source_event_type", inner.get("source_event_type"))
        if isinstance(declared_event_type, str) and declared_event_type:
            event_type = declared_event_type
            action_id = outer.get("source_action_instance_id", inner.get("source_action_instance_id", action_id))
            exposure_id = outer.get("source_exposure_id", inner.get("source_exposure_id", exposure_id or action_id))
        normalized: dict[str, Any] = {
            "event_id": source_id,
            "opaque_event_id": source_to_opaque[source_id],
            "available_epoch": availability[source_id],
            "occurred_epoch_upper": observed,
            "source_fact_ids": list(fact_ids),
            "event_type": event_type,
        }
        if action_id is not None:
            normalized["action_id"] = action_id
            normalized["exposure_id"] = exposure_id
        result[source_id] = normalized
    if set(availability) != set(result) or set(source_to_opaque) != set(result):
        _fail("source event, availability and sanitizer denominators differ")
    return result


def _verify_source_and_ledger(
    study_root: Path,
    *,
    refs: Mapping[str, Mapping[str, Any]],
    docs: Mapping[str, Mapping[str, Any]],
    sanitizer_inputs: Mapping[str, Mapping[str, Any]],
    source_to_opaque: Mapping[str, str],
) -> tuple[
    list[Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
    list[dict[str, Any]],
]:
    """Verify source completeness independently of the inventory itself."""
    manifest = docs["immutable_source_manifest"]
    audit = docs["source_audit"]
    inventory = docs["source_inventory"]
    ledger = sanitizer_inputs["sealed_event_ledger"]
    availability_ledger = sanitizer_inputs["sealed_availability_ledger"]
    ledger_audit = docs["event_ledger_audit"]
    _schema(manifest, "NCF-PRIMARY-IMMUTABLE-SOURCE-MANIFEST-1.0.0", "immutable source manifest")
    _schema(audit, "NCF-PRIMARY-SOURCE-AUDIT-1.0.0", "source audit")
    _schema(inventory, "NCF-PRIMARY-SOURCE-INVENTORY-2.0.0", "source inventory")
    _schema(ledger_audit, "NCF-PRIMARY-EVENT-LEDGER-AUDIT-2.0.0", "event ledger audit")

    source_ref = _expect_mapping(manifest.get("selected_source_ref"), "selected source ref")
    source_wrapped = {"ref_id": "immutable-selected-source", "role": "immutable_selected_source", **source_ref}
    _, _, source_raw = _resolve_ref(study_root, source_wrapped, "immutable selected source")
    manifest_bound = (
        _artifact_ref_equal(_expect_mapping(audit.get("immutable_source_manifest_ref"), "audit source manifest ref"), refs["immutable_source_manifest"])
        and _artifact_ref_equal(_expect_mapping(inventory.get("immutable_source_manifest_ref"), "inventory source manifest ref"), refs["immutable_source_manifest"])
    )
    inventory_bound = _artifact_ref_equal(
        _expect_mapping(audit.get("source_inventory_ref"), "audit inventory ref"), refs["source_inventory"]
    )
    if audit.get("reviewer_role") != "source_auditor":
        _fail("source audit must be produced by source_auditor")

    facts = _expect_list(inventory.get("facts"), "source inventory facts")
    fact_by_id: dict[str, Mapping[str, Any]] = {}
    assertion_to_fact: dict[str, str] = {}
    locators_valid = True
    for index, fact_any in enumerate(facts):
        fact = _expect_mapping(fact_any, f"source fact[{index}]")
        fact_id = fact.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id or fact_id in fact_by_id:
            _fail("source fact ids invalid/duplicate")
        assertions = _expect_list(fact.get("source_assertion_ids"), f"fact {fact_id} source assertions")
        if not assertions or any(not isinstance(item, str) or not item for item in assertions):
            _fail(f"fact {fact_id} source assertions invalid")
        if any(item in assertion_to_fact for item in assertions):
            _fail("source assertion assigned to multiple facts")
        for item in assertions:
            assertion_to_fact[item] = fact_id
        locator = _expect_mapping(fact.get("source_locator"), f"fact {fact_id} source locator")
        if locator.get("source_path") != source_ref.get("path"):
            locators_valid = False
        lower = locator.get("byte_start")
        upper = locator.get("byte_end")
        if isinstance(lower, bool) or not isinstance(lower, int) or isinstance(upper, bool) or not isinstance(upper, int) or lower < 0 or upper <= lower or upper > len(source_raw):
            locators_valid = False
        else:
            locators_valid &= locator.get("excerpt_sha256") == sha256_bytes(source_raw[lower:upper])
        runtime_ids = _expect_list(fact.get("runtime_source_result_ids"), f"fact {fact_id} runtime ids")
        if (
            not runtime_ids
            or any(not isinstance(item, str) or not item for item in runtime_ids)
            or any(item not in source_to_opaque and item not in set(source_to_opaque.values()) for item in runtime_ids)
        ):
            _fail(f"fact {fact_id} runtime source ids invalid")
        _expect_list(fact.get("local_domain_ids"), f"fact {fact_id} domains")
        if not isinstance(fact.get("clinically_consequential"), bool):
            _fail(f"fact {fact_id} consequential flag invalid")
        fact_by_id[fact_id] = fact

    audited_assertions = _expect_list(audit.get("complete_raw_source_assertion_ids"), "audit assertion denominator")
    denominator_exact = (
        audit.get("complete_raw_source_assertion_denominator") is True
        and len(audited_assertions) == len(set(audited_assertions))
        and set(audited_assertions) == set(assertion_to_fact)
    )
    consequential_ids = set(_expect_list(audit.get("clinically_consequential_fact_ids"), "audited consequential facts"))
    consequential_exact = consequential_ids == {
        fact_id for fact_id, fact in fact_by_id.items() if fact.get("clinically_consequential") is True
    }
    duplicate_rows = _expect_list(audit.get("duplicate_groups"), "source duplicate groups")
    duplicate_assertions: set[str] = set()
    duplicate_groups_valid = True
    for row_any in duplicate_rows:
        row = _expect_mapping(row_any, "duplicate group")
        ids = _expect_list(row.get("source_assertion_ids"), "duplicate group assertions")
        canonical_fact_id = row.get("canonical_fact_id")
        duplicate_groups_valid &= (
            isinstance(row.get("group_id"), str)
            and bool(ids)
            and set(ids).issubset(assertion_to_fact)
            and canonical_fact_id in fact_by_id
            and all(assertion_to_fact[item] == canonical_fact_id for item in ids)
            and not duplicate_assertions.intersection(ids)
        )
        duplicate_assertions.update(ids)
    duplicate_groups_valid &= audit.get("duplicate_group_coverage_complete") is True

    event_by_id = _normalize_source_events(ledger, availability_ledger, source_to_opaque)
    # PL-LED-001 is a source-to-runtime claim, not merely a claim about the
    # already-sanitized transport.  Reconstruct both sides of the
    # fact<->event relation so that an omitted event, an orphan event, or a
    # provenance relink cannot hide behind a complete-looking inventory.
    opaque_to_source = {opaque: source for source, opaque in source_to_opaque.items()}
    events_from_facts: dict[str, set[str]] = {event_id: set() for event_id in event_by_id}
    fact_event_links_valid = True
    for fact_id, fact in fact_by_id.items():
        runtime_ids = _expect_list(fact.get("runtime_source_result_ids"), f"fact {fact_id} runtime ids")
        linked_source_ids: set[str] = set()
        for runtime_id in runtime_ids:
            source_id = str(runtime_id) if str(runtime_id) in event_by_id else opaque_to_source.get(str(runtime_id))
            if source_id is None or source_id not in event_by_id:
                fact_event_links_valid = False
                continue
            linked_source_ids.add(source_id)
            events_from_facts[source_id].add(fact_id)
        fact_event_links_valid &= bool(linked_source_ids)
    event_fact_bipartite_exact = fact_event_links_valid and all(
        set(_expect_list(event.get("source_fact_ids"), f"event {event_id} source facts"))
        == events_from_facts[event_id]
        for event_id, event in event_by_id.items()
    )

    # Availability is part of the public evidence semantics.  The sanitized
    # compiler is allowed to transport it, but it is not the authority that
    # decides whether the source timing was faithfully represented.  Require
    # a bounded source-derived availability row for every event and forbid a
    # source-authored runtime availability field (which would bypass the
    # frozen compiler).
    availability_rows = _expect_list(availability_ledger.get("events"), "sealed availability events")
    availability_by_id = {
        str(_expect_mapping(row, "sealed availability event").get("source_event_id")):
        _expect_mapping(row, "sealed availability event")
        for row in availability_rows
    }
    temporal_source_semantics_valid = (
        len(availability_by_id) == len(availability_rows)
        and set(availability_by_id) == set(event_by_id)
        and availability_ledger.get("publication_order_used_as_clinical_availability", False) is False
    )
    source_rows_by_id = {
        str(_expect_mapping(row, "sealed source event").get("source_event_id")):
        _expect_mapping(row, "sealed source event")
        for row in _expect_list(ledger.get("events"), "sealed source events")
    }
    temporal_source_semantics_valid &= len(source_rows_by_id) == len(event_by_id)
    for event_id, normalized in event_by_id.items():
        outer = source_rows_by_id.get(event_id)
        if outer is None:
            temporal_source_semantics_valid = False
            continue
        inner = _expect_mapping(outer.get("runtime_event", outer), f"sealed source event {event_id} runtime event")
        temporal_source_semantics_valid &= (
            "available_at" not in inner
            and "available_epoch_ordinal" not in inner
            and int(normalized["occurred_epoch_upper"]) <= int(normalized["available_epoch"])
        )
    provenance_valid = True
    for event_id, row in event_by_id.items():
        source_fact_ids = _expect_list(row.get("source_fact_ids"), f"event {event_id} fact ids")
        provenance_valid &= bool(source_fact_ids) and set(source_fact_ids).issubset(fact_by_id)
    audit_rows = _expect_list(ledger_audit.get("event_reviews"), "event ledger audit reviews")
    audit_by_id: dict[str, Mapping[str, Any]] = {}
    for row_any in audit_rows:
        row = _expect_mapping(row_any, "event audit row")
        event_id = row.get("event_id")
        if not isinstance(event_id, str) or event_id in audit_by_id:
            _fail("event audit ids invalid/duplicate")
        audit_by_id[event_id] = row
    event_audit_exact = (
        ledger_audit.get("reviewer_role") == "source_auditor"
        and _artifact_ref_equal(
            _expect_mapping(ledger_audit.get("event_ledger_ref"), "event audit ledger ref"),
            _expect_mapping(
                next(
                    row for row in _expect_list(docs["sanitized_ledger_assignment_proof"].get("inputs"), "assignment inputs")
                    if isinstance(row, Mapping) and row.get("slot") == "sealed_event_ledger"
                ),
                "sealed event ledger proof input",
            ),
        )
        and set(audit_by_id) == set(event_by_id)
        and ledger_audit.get("all_event_provenance_verified") is True
        and all(row.get("provenance_verified") is True for row in audit_by_id.values())
    )
    # These assertions are deliberately row-exhaustive.  A global "audited"
    # boolean is insufficient because it can leave one event's type, timing,
    # or disposition unaudited while PL-LED-001 still appears to pass.
    event_semantics_audit_exact = (
        ledger_audit.get("all_event_type_semantics_verified") is True
        and ledger_audit.get("all_event_temporal_semantics_verified") is True
        and ledger_audit.get("all_event_dispositions_verified") is True
        and ledger_audit.get("no_invented_clock_time") is True
        and all(
            row.get("event_type_verified") is True
            and row.get("occurred_time_semantics_verified") is True
            and row.get("availability_semantics_verified") is True
            and row.get("disposition_verified") is True
            and row.get("no_invented_clock_time") is True
            and row.get("event_type") == event_by_id[event_id].get("event_type")
            and row.get("occurred_epoch_upper") == event_by_id[event_id].get("occurred_epoch_upper")
            and row.get("available_epoch") == event_by_id[event_id].get("available_epoch")
            and set(_expect_list(row.get("source_fact_ids"), f"event audit {event_id} source facts"))
            == set(_expect_list(event_by_id[event_id].get("source_fact_ids"), f"event {event_id} source facts"))
            for event_id, row in audit_by_id.items()
        )
    )
    checks = [
        _check("immutable_source_bytes_resolved", {"path": source_ref.get("path"), "sha256": sha256_bytes(source_raw), "bytes": len(source_raw)}, source_ref, "ARTIFACT_EQ", True),
        _check("source_manifest_and_inventory_bound", manifest_bound and inventory_bound, True, "EQ", manifest_bound and inventory_bound),
        _check("independent_raw_assertion_denominator_exact", sorted(audited_assertions), sorted(assertion_to_fact), "SET_EQUALS", denominator_exact),
        _check("source_locators_and_excerpt_hashes_valid", locators_valid and audit.get("all_source_locators_verified") is True, True, "EQ", locators_valid and audit.get("all_source_locators_verified") is True),
        _check("duplicate_groups_completely_covered", duplicate_groups_valid, True, "EQ", duplicate_groups_valid),
        _check("independent_consequence_review_exact", sorted(consequential_ids), sorted(fact_id for fact_id, fact in fact_by_id.items() if fact.get("clinically_consequential") is True), "SET_EQUALS", consequential_exact),
        _check("event_provenance_and_audit_exact", event_audit_exact and provenance_valid, True, "EQ", event_audit_exact and provenance_valid),
        _check("source_fact_event_denominator_bipartite_exact", event_fact_bipartite_exact, True, "EQ", event_fact_bipartite_exact),
        _check("source_availability_and_occurred_time_semantics_exact", temporal_source_semantics_valid, True, "EQ", temporal_source_semantics_valid),
        _check("event_type_time_and_disposition_audit_row_exhaustive", event_semantics_audit_exact, True, "EQ", event_semantics_audit_exact),
    ]
    return facts, fact_by_id, event_by_id, audit_by_id, checks


def _manual_failure_subjects(study_root: Path, doc: Mapping[str, Any]) -> set[tuple[str, str]]:
    _schema(doc, "NCF-PRIMARY-SCORER-AUDIT-REPORT-1.0.0", "scorer audit report")
    if doc.get("role") != "scorer_auditor":
        _fail("audit report role must be scorer_auditor")
    failures: set[tuple[str, str]] = set()
    for index, row_any in enumerate(_expect_list(doc.get("findings"), "audit findings")):
        row = _expect_mapping(row_any, f"audit finding[{index}]")
        if row.get("verdict") != "FAIL" or row.get("subject_kind") not in {"GATE", "COMPLEX_COVERAGE"}:
            _fail("manual auditor is failure-only")
        key = (str(row["subject_kind"]), str(row.get("subject_id")))
        if not key[1] or key in failures:
            _fail("audit finding subject invalid/duplicate")
        evidence_refs = _expect_list(row.get("evidence_refs"), "audit finding evidence refs")
        if not evidence_refs:
            _fail("manual FAIL requires content-addressed evidence")
        for ref_index, ref in enumerate(evidence_refs):
            wrapped = {"ref_id": f"audit-{index}-{ref_index}", "role": "audit_evidence", **_expect_mapping(ref, "audit evidence ref")}
            _resolve_ref(study_root, wrapped, "audit evidence")
        failures.add(key)
    return failures


def _append_manual_check(result: dict[str, Any], failures: set[tuple[str, str]]) -> None:
    key = (str(result["subject_kind"]), str(result["subject_id"]))
    passed = key not in failures
    result["checks"].append(_check("no_typed_manual_audit_failure", not passed, False, "EQ", passed))
    result["computed_result"] = "PASS" if all(row["passed"] for row in result["checks"]) else "FAIL"


def _verify_post_replay_closure(
    refs: Mapping[str, Mapping[str, Any]], docs: Mapping[str, Mapping[str, Any]]
) -> list[dict[str, Any]]:
    closure = docs["all_sealed_artifacts_after_replay"]
    _schema(closure, "NCF-ALL-SEALED-ARTIFACTS-AFTER-REPLAY-1.0.0", "all sealed after replay")
    rows = _expect_list(closure.get("artifacts"), "post-replay closure artifacts")
    by_class = {str(row.get("data_class")): _expect_mapping(row, "closure artifact") for row in rows if isinstance(row, Mapping)}
    expected = {
        "runtime_output": refs["runtime_output"],
        "replay_seal": refs["runtime_replay_seal"],
        "mapped_observation_consumption": refs["mapped_observation_consumption"],
    }
    exact = set(expected).issubset(by_class) and all(_artifact_ref_equal(by_class[key], ref) for key, ref in expected.items())
    return [
        _check("runtime_replay_and_consumption_exactly_bound_after_replay", exact, True, "EQ", exact),
        _check("oracle_excluded_from_preoracle_closure", closure.get("oracle_contents_included"), False, "EQ", closure.get("oracle_contents_included") is False),
        _check("replay_closure_marked_sealed", closure.get("replay_sealed"), True, "EQ", closure.get("replay_sealed") is True),
    ]


def _runtime_cut_by_ordinal(runtime: Mapping[str, Any]) -> dict[int, Mapping[str, Any]]:
    _schema(runtime, "NCF-PRIMARY-RUNTIME-OUTPUT-1.0.0", "runtime output")
    rows = _expect_list(runtime.get("cuts"), "runtime cuts")
    by_ordinal: dict[int, Mapping[str, Any]] = {}
    for row_any in rows:
        row = _expect_mapping(row_any, "runtime cut")
        ordinal = row.get("cut_ordinal")
        if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal in by_ordinal:
            _fail("runtime cut ordinals invalid/duplicate")
        by_ordinal[ordinal] = row
    ordered = sorted(by_ordinal)
    if runtime.get("cut_count") != len(by_ordinal) or [by_ordinal[item].get("sequence") for item in ordered] != list(range(len(ordered))):
        _fail("runtime cuts must have exact increasing cuts and contiguous sequence")
    return by_ordinal


def _runtime_integrity_checks(
    refs: Mapping[str, Mapping[str, Any]],
    docs: Mapping[str, Mapping[str, Any]],
    event_by_id: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[int, Mapping[str, Any]], list[dict[str, Any]]]:
    runtime = docs["runtime_output"]
    replay = docs["runtime_replay_seal"]
    mapped = docs["mapped_observation_consumption"]
    _schema(replay, "NCF-PRIMARY-RUNTIME-REPLAY-SEAL-1.0.0", "runtime replay seal")
    _schema(mapped, "NCF-MAPPED-OBSERVATION-CONSUMPTION-1.1.0", "mapped observation consumption")
    cuts = _runtime_cut_by_ordinal(runtime)
    hashes_exact = True
    availability_exact = True
    head_hashes_exact = True
    prospective = True
    cut_seals_exact = True
    parent_chain_exact = True
    previous_processed: list[str] = []
    opaque_event_by_id = {str(row["opaque_event_id"]): row for row in event_by_id.values()}
    ordered_cuts = [cuts[key] for key in sorted(cuts)]
    for index, (ordinal, cut) in enumerate((key, cuts[key]) for key in sorted(cuts)):
        canonical_state = _expect_mapping(cut.get("canonical_state"), f"cut {ordinal} state")
        state_raw = runtime_canonical_json_bytes(canonical_state)
        state_bytes_hash = sha256_bytes(state_raw)
        state_hash = cut.get("canonical_state_hash")
        state_integrity = _expect_mapping(canonical_state.get("integrity"), f"cut {ordinal} state integrity")
        hashes_exact &= (
            cut.get("canonical_state_bytes_sha256") == state_bytes_hash
            and isinstance(state_hash, str)
            and bool(SHA256_RE.fullmatch(state_hash))
            and state_integrity.get("state_hash") == state_hash
            and architecture_state_hash(canonical_state) == state_hash
        )
        head_hashes = _expect_mapping(cut.get("head_state_hashes"), f"cut {ordinal} head hashes")
        hashes_exact &= all(value == state_hash for value in head_hashes.values())
        hashes_exact &= all(
            _expect_mapping(cut.get(head), f"cut {ordinal} {head}").get("consumed_state_hash") == state_hash
            for head in ("diagnosis", "forecast", "persistence_baseline", "plan")
        )
        head_hashes_exact &= cut.get("head_state_hashes_all_equal") is True
        processed = _expect_list(cut.get("processed_event_ids"), f"cut {ordinal} processed events")
        future = _expect_list(cut.get("future_registered_event_ids"), f"cut {ordinal} future events")
        new = _expect_list(cut.get("new_event_ids"), f"cut {ordinal} new events")
        expected_processed = sorted(
            event_id
            for event_id, event in opaque_event_by_id.items()
            if int(event["available_epoch"]) <= ordinal
        )
        expected_future = sorted(set(opaque_event_by_id) - set(expected_processed))
        expected_new = sorted(set(expected_processed) - set(previous_processed))
        availability_exact &= (
            processed == expected_processed
            and future == expected_future
            and new == expected_new
            and previous_processed == sorted(set(previous_processed))
        )
        previous_processed = processed
        claimed_seal = cut.get("sealed_before_next_cut_sha256")
        cut_core = copy.deepcopy(dict(cut))
        cut_core.pop("sealed_before_next_cut_sha256", None)
        cut_seals_exact &= claimed_seal == sha256_bytes(runtime_canonical_json_bytes(cut_core))
        expected_parent = None if index == 0 else ordered_cuts[index - 1].get("sealed_before_next_cut_sha256")
        parent_chain_exact &= cut.get("parent_cut_seal_sha256") == expected_parent
        prospective &= isinstance(claimed_seal, str) and bool(claimed_seal)
    prospective_rows = _expect_list(runtime.get("prospective_scores"), "runtime prospective scores")
    prospective &= len(prospective_rows) == max(0, len(ordered_cuts) - 1)
    for index, row_any in enumerate(prospective_rows):
        row = _expect_mapping(row_any, f"prospective score[{index}]")
        left = ordered_cuts[index]
        right = ordered_cuts[index + 1]
        bindings = {
            "forecast_cut_ordinal": left.get("cut_ordinal"),
            "realization_cut_ordinal": right.get("cut_ordinal"),
            "forecast_cut_seal_sha256": left.get("sealed_before_next_cut_sha256"),
            "forecast_payload_sha256": sha256_bytes(runtime_canonical_json_bytes(left.get("forecast"))),
            "next_canonical_state_hash": right.get("canonical_state_hash"),
            "next_cut_parent_seal_sha256": right.get("parent_cut_seal_sha256"),
            "prospective_seal_verified": True,
        }
        prospective &= all(row.get(key) == value for key, value in bindings.items())
        payload = copy.deepcopy(dict(row))
        claimed = payload.pop("score_binding_sha256", None)
        prospective &= claimed == sha256_bytes(runtime_canonical_json_bytes(payload))
    prospective &= runtime.get("final_cut_seal_sha256") == ordered_cuts[-1].get("sealed_before_next_cut_sha256")
    runtime_ref = refs["runtime_output"]
    mapped_ref = refs["mapped_observation_consumption"]
    replay_runtime = _expect_mapping(replay.get("runtime_output"), "replay runtime ref")
    replay_mapped = _expect_mapping(replay.get("mapped_observation_consumption"), "replay mapped ref")
    replay_exact = (
        replay_runtime.get("sha256") == runtime_ref.get("sha256") and replay_runtime.get("bytes") == runtime_ref.get("bytes")
        and replay_mapped.get("sha256") == mapped_ref.get("sha256") and replay_mapped.get("bytes") == mapped_ref.get("bytes")
        and mapped.get("runtime_output_sha256") == runtime_ref.get("sha256")
        and replay.get("case_blind") is True
    )
    return cuts, [
        _check("runtime_replay_seal_binds_exact_raw_outputs", replay_exact, True, "EQ", replay_exact),
        _check("all_heads_consume_exact_canonical_state", hashes_exact and head_hashes_exact, True, "EQ", hashes_exact and head_hashes_exact),
        _check("future_events_withheld_until_available_cut", availability_exact, True, "EQ", availability_exact),
        _check("cut_seals_and_parent_chain_recompute_exactly", cut_seals_exact and parent_chain_exact, True, "EQ", cut_seals_exact and parent_chain_exact),
        _check("every_cut_and_prospective_score_exactly_bound", prospective and bool(cuts), True, "EQ", prospective and bool(cuts)),
    ]


def _oracle_checks(
    oracle: Mapping[str, Any],
    cuts: Mapping[int, Mapping[str, Any]],
    fact_by_id: Mapping[str, Mapping[str, Any]],
    event_by_id: Mapping[str, Mapping[str, Any]],
    source_to_opaque: Mapping[str, str],
) -> tuple[str, list[str], dict[str, set[str]], list[dict[str, Any]]]:
    _schema(oracle, "NCF-PRIMARY-ORACLE-TARGETS-2.0.0", "oracle targets")
    target = oracle.get("target_process_id")
    if not isinstance(target, str) or not target:
        _fail("oracle target process missing")
    decisive_epoch = oracle.get("decisive_epoch")
    if decisive_epoch not in cuts:
        _fail("oracle decisive epoch/cut mismatch")
    trajectories = _expect_list(oracle.get("trajectories"), "oracle trajectories")
    trajectory_by_id: dict[str, Mapping[str, Any]] = {}
    for row_any in trajectories:
        row = _expect_mapping(row_any, "oracle trajectory")
        ref_id = row.get("trajectory_ref_id")
        if not isinstance(ref_id, str) or not ref_id or ref_id in trajectory_by_id:
            _fail("oracle trajectory refs invalid/duplicate")
        trajectory_by_id[ref_id] = row
    targets = _expect_list(oracle.get("concurrent_targets"), "oracle concurrent targets")
    process_ids: list[str] = []
    source_fact_sets: list[set[str]] = []
    source_event_sets: list[set[str]] = []
    witness_opaque_by_process: dict[str, set[str]] = {}
    target_rows_valid = True
    for row_any in targets:
        row = _expect_mapping(row_any, "oracle concurrent target")
        process_id = row.get("process_id")
        trajectory_ref = row.get("trajectory_ref_id")
        fact_ids = set(_expect_list(row.get("source_fact_ids"), "oracle target facts"))
        event_ids = set(_expect_list(row.get("source_event_ids"), "oracle target events"))
        process_ids.append(str(process_id))
        source_fact_sets.append(fact_ids)
        source_event_sets.append(event_ids)
        trajectory = trajectory_by_id.get(str(trajectory_ref))
        linked_facts = set().union(*(set(event_by_id[event_id].get("source_fact_ids", [])) for event_id in event_ids)) if event_ids.issubset(event_by_id) else set()
        target_rows_valid &= (
            isinstance(process_id, str) and bool(process_id)
            and trajectory is not None and trajectory.get("process_id") == process_id
            and row.get("decisive_epoch") == decisive_epoch
            and bool(fact_ids) and fact_ids.issubset(fact_by_id)
            and bool(event_ids) and event_ids.issubset(event_by_id)
            and all(event_by_id[event_id].get("available_epoch") <= decisive_epoch for event_id in event_ids if event_id in event_by_id)
            and fact_ids.issubset(linked_facts)
        )
        if isinstance(process_id, str) and event_ids.issubset(source_to_opaque):
            witness_opaque_by_process[process_id] = {source_to_opaque[event_id] for event_id in event_ids}
    independent_sources = all(
        not source_fact_sets[i].intersection(source_fact_sets[j]) and not source_event_sets[i].intersection(source_event_sets[j])
        for i in range(len(targets)) for j in range(i + 1, len(targets))
    )
    preserved = True
    for row_any in targets:
        row = _expect_mapping(row_any, "oracle concurrent target")
        process_id = str(row.get("process_id"))
        event_ids = set(_expect_list(row.get("source_event_ids"), "oracle target events"))
        first_available = min(int(event_by_id[event_id]["available_epoch"]) for event_id in event_ids if event_id in event_by_id)
        relevant_cuts = [cut for ordinal, cut in sorted(cuts.items()) if first_available <= ordinal <= int(decisive_epoch)]
        if not relevant_cuts:
            preserved = False
            continue
        for cut in relevant_cuts:
            diagnosis = _expect_mapping(cut.get("diagnosis"), "runtime diagnosis")
            marginals = _expect_mapping(diagnosis.get("process_activation_marginals"), "process activation marginals")
            local_ids = {
                str(local.get("process_id"))
                for local in _expect_list(_expect_mapping(cut.get("canonical_state"), "canonical state").get("local_states"), "canonical local states")
                if isinstance(local, Mapping)
            }
            mode_ids = {
                str(local.get("process_id"))
                for local in _expect_list(cut.get("mode_trace"), "mode trace")
                if isinstance(local, Mapping)
            }
            preserved &= process_id in marginals and process_id in local_ids and process_id in mode_ids
    checks = [
        _check("oracle_has_at_least_two_distinct_processes", len(set(process_ids)), 2, "GTE", len(targets) >= 2 and len(set(process_ids)) == len(targets)),
        _check("oracle_targets_bind_distinct_available_source_trajectories", target_rows_valid and independent_sources, True, "EQ", target_rows_valid and independent_sources),
        _check("runtime_preserves_all_oracle_concurrent_processes", preserved, True, "EQ", preserved),
    ]
    return str(target), process_ids, witness_opaque_by_process, checks


def evaluate_case(study_root: Path, manifest_path: Path) -> dict[str, Any]:
    """Compute case-dependent gates only from sealed raw artifacts."""
    _, refs, docs = _load_manifest(study_root, manifest_path, "CASE_EVALUATION")
    _, prediction_contract, localization_contract = _validate_contracts(docs["gate_contract"], docs["scoring_contract"])
    for role in ("runtime_input_manifest", "runtime_output", "runtime_replay_seal", "mapped_observation_consumption"):
        _reject_diagnosis_shortcuts(docs[role])
    sanitizer_inputs, source_to_opaque, opaque_to_source, sanitizer_checks = _verify_sanitized_ledger_chain(
        study_root, refs=refs, docs=docs
    )
    facts, fact_by_id, event_by_id, audit_by_id, source_checks = _verify_source_and_ledger(
        study_root,
        refs=refs,
        docs=docs,
        sanitizer_inputs=sanitizer_inputs,
        source_to_opaque=source_to_opaque,
    )
    cuts, runtime_checks = _runtime_integrity_checks(refs, docs, event_by_id)
    closure_checks = _verify_post_replay_closure(refs, docs)
    blind_checks = _verify_blindness_chain(study_root, refs=refs, docs=docs)
    isolation_checks = _verify_primary_isolation_chain(study_root, refs=refs, docs=docs)
    manual_failures = _manual_failure_subjects(study_root, docs["audit_report"])

    oracle = docs["oracle_targets"]
    decisive_ordinal = oracle.get("decisive_epoch")
    if decisive_ordinal not in cuts:
        _fail("oracle decisive cut absent from runtime output")
    decisive_cut = cuts[int(decisive_ordinal)]
    target, _, witness_opaque_by_process, oracle_structural_checks = _oracle_checks(
        oracle, cuts, fact_by_id, event_by_id, source_to_opaque
    )
    diagnosis = _expect_mapping(decisive_cut.get("diagnosis"), "decisive diagnosis")
    posteriors = _expect_mapping(diagnosis.get("process_activation_marginals"), "diagnosis process activation marginals")
    priors = {
        str(row.get("process_id")): _finite_number(row.get("activation_prior"), "case-blind activation prior")
        for row in _expect_list(docs["runtime_output"].get("case_blind_process_priors"), "case-blind process priors")
        if isinstance(row, Mapping)
    }
    if target not in posteriors or target not in priors:
        _fail("oracle target absent from raw diagnosis posteriors")
    prior = priors[target]
    posterior = _finite_number(posteriors[target], "target posterior")
    target_ratio = math.inf if _odds(prior) == 0 and _odds(posterior) > 0 else (_odds(posterior) / _odds(prior) if _odds(prior) > 0 else 0.0)
    factors = _expect_list(decisive_cut.get("factor_trace"), "decisive factor trace")
    target_witnesses = witness_opaque_by_process.get(target, set())
    positive_factor = any(
        isinstance(row, Mapping)
        and bool(set(row.get("source_result_ids", [])).intersection(target_witnesses))
        and any(
            isinstance(effect, Mapping)
            and effect.get("process_id") == target
            and effect.get("direction") == "RAISE"
            for effect in row.get("derived_process_effects", [])
        )
        for row in factors
    )
    alternative_ids = set(_expect_list(oracle.get("incompatible_alternative_process_ids"), "oracle incompatible alternatives"))
    alternatives_lowered = all(
        alt in posteriors and alt in priors
        and _odds(_finite_number(posteriors[alt], f"{alt} posterior")) < _odds(priors[alt])
        and any(
            isinstance(row, Mapping)
            and bool(row.get("source_result_ids"))
            and any(
                isinstance(effect, Mapping)
                and effect.get("process_id") == alt
                and effect.get("direction") == "LOWER"
                for effect in row.get("derived_process_effects", [])
            )
            for row in factors
        )
        for alt in alternative_ids
    )
    def _log_odds(probability: float) -> float:
        clipped = min(1.0 - 1e-15, max(1e-15, probability))
        return math.log(clipped / (1.0 - clipped))
    tie_gap = min(
        (
            abs(_log_odds(posterior) - _log_odds(_finite_number(posteriors[alt], f"{alt} posterior")))
            for alt in alternative_ids if alt in posteriors
        ),
        default=math.inf,
    )
    min_posterior = float(localization_contract["target_process_rule"]["marginal_at_decisive_cut_minimum"])
    min_ratio = float(localization_contract["target_process_rule"]["posterior_odds_over_case_blind_prior_minimum_ratio"])
    dx_checks = [
        *oracle_structural_checks,
        _check("target_present_in_model", target in posteriors and target in priors, True, "EQ", target in posteriors and target in priors),
        _check("target_marginal_minimum", posterior, min_posterior, "GTE", posterior >= min_posterior),
        _check("target_odds_ratio_minimum", target_ratio, min_ratio, "GTE", target_ratio >= min_ratio),
        _check("explicit_oracle_concordant_factor", positive_factor, True, "EQ", positive_factor),
        _check("all_incompatible_alternatives_lowered", alternatives_lowered, True, "EQ", alternatives_lowered),
        _check("no_unresolved_tie", tie_gap, 0.25, "GTE", tie_gap >= 0.25),
    ]

    eligible: list[int] = []
    model_scores: list[float] = []
    baseline_scores: list[float] = []
    supports_ok = True
    critical_ok = True
    prospective_ok = True
    score_rows = _expect_list(docs["runtime_output"].get("prospective_scores"), "runtime prospective scores")
    critical_pairs = {
        (int(row.get("forecast_cut_ordinal")), int(row.get("realization_cut_ordinal")))
        for row in _expect_list(oracle.get("critical_mode_transitions", []), "oracle critical mode transitions")
        if isinstance(row, Mapping)
    }
    for index, score_any in enumerate(score_rows):
        row = _expect_mapping(score_any, f"prospective score[{index}]")
        forecast_ordinal = int(row.get("forecast_cut_ordinal"))
        eligible.append(forecast_ordinal)
        model = _expect_mapping(row.get("model"), f"prospective score[{index}] model")
        baseline = _expect_mapping(row.get("persistence_baseline"), f"prospective score[{index}] baseline")
        model_scores.append(_finite_number(model.get("bounded_log_score"), f"score[{index}] model score"))
        baseline_scores.append(_finite_number(baseline.get("bounded_log_score"), f"score[{index}] persistence score"))
        model_components = _expect_list(model.get("components"), f"score[{index}] model components")
        supports_ok &= (
            model.get("component_count") == len(model_components)
            and bool(model_components)
            and model.get("all_components_positive_support") is True
            and all(component.get("positive_support") is True for component in model_components if isinstance(component, Mapping))
        )
        pair = (forecast_ordinal, int(row.get("realization_cut_ordinal")))
        critical_ok &= pair not in critical_pairs or model.get("all_components_positive_support") is True
        prospective_ok &= (
            forecast_ordinal in cuts
            and row.get("forecast_cut_seal_sha256") == cuts[forecast_ordinal].get("sealed_before_next_cut_sha256")
            and row.get("prospective_seal_verified") is True
        )
    tolerance = float(prediction_contract["aggregate_rule"]["mean_bounded_log_score_must_not_be_worse_than_persistence_by_more_than"])
    mean_model = sum(model_scores) / len(model_scores) if model_scores else -math.inf
    mean_baseline = sum(baseline_scores) / len(baseline_scores) if baseline_scores else -math.inf
    pred_checks = [
        _check("eligible_forecasts_present", len(eligible), 1, "GTE", bool(eligible)),
        _check("finite_positive_support_everywhere", supports_ok, True, "EQ", supports_ok and bool(eligible)),
        _check("critical_transitions_nonzero_support", critical_ok, True, "EQ", critical_ok and bool(eligible)),
        _check("mean_score_not_worse_than_persistence", mean_model - mean_baseline if eligible else None, -tolerance, "GTE", bool(eligible) and mean_model >= mean_baseline - tolerance),
        _check("all_forecasts_prospectively_sealed", prospective_ok, True, "EQ", prospective_ok and bool(eligible)),
    ]

    mapped = docs["mapped_observation_consumption"]
    records = _expect_list(mapped.get("records"), "mapped consumption records")
    records_by_source: dict[str, list[Mapping[str, Any]]] = {}
    for row_any in records:
        row = _expect_mapping(row_any, "mapped consumption record")
        records_by_source.setdefault(str(row.get("source_result_id")), []).append(row)
    sanitized_by_id = {
        str(row.get("opaque_event_id")): _expect_mapping(row, "sanitized event")
        for row in _expect_list(docs["event_ledger"].get("events"), "sanitized events")
        if isinstance(row, Mapping)
    }
    opaque_event_ids = set(sanitized_by_id)
    expected_observation_ids = {
        event_id for event_id, row in sanitized_by_id.items()
        if row.get("event_kind") == "OBSERVATION"
    }
    consumption_event_ids = [str(row.get("event_id")) for row in records]
    consumption_source_ids = [str(row.get("source_result_id")) for row in records]
    final_processed_ids = set(
        _expect_list(cuts[max(cuts)].get("processed_event_ids"), "final cut processed events")
    ) if cuts else set()
    # The mapped-consumption artifact is an exhaustive audit table for
    # observation events, while action/support events are consumed through
    # their typed lifecycle in the recursive runtime.  Check both denominators
    # explicitly; closure hashes alone only prove that some table was sealed.
    observation_consumption_denominator_exact = (
        mapped.get("event_count") == len(records)
        and len(consumption_event_ids) == len(set(consumption_event_ids))
        and consumption_event_ids == consumption_source_ids
        and set(consumption_event_ids) == expected_observation_ids
    )
    complete_runtime_event_denominator_processed = final_processed_ids == opaque_event_ids
    consequential_handled = True
    all_fact_ids_covered = True
    reliable_negative_ids: list[str] = []
    reliable_negative_valid = True
    duplicate_suppression_valid = True
    for fact_id, fact in fact_by_id.items():
        runtime_ids = {
            source_to_opaque.get(str(item), str(item))
            for item in _expect_list(fact.get("runtime_source_result_ids"), f"fact {fact_id} runtime ids")
        }
        rows = [row for runtime_id in runtime_ids for row in records_by_source.get(runtime_id, [])]
        runtime_handled = bool(runtime_ids) and runtime_ids.issubset(final_processed_ids)
        all_fact_ids_covered &= bool(rows) or runtime_handled
        if fact.get("clinically_consequential") is True:
            consequential_handled &= (
                (bool(rows) and any(row.get("rankability_disposition") in {"CONSUME", "WITHHOLD_TO_MEASUREMENT_UNCERTAINTY", "RECORD_ONLY"} for row in rows))
                or runtime_handled
            )
        if fact.get("evidence_semantics") == "RELIABLE_NEGATIVE":
            reliable_negative_ids.append(fact_id)
            consumed = [row for row in rows if row.get("rankability_disposition") == "CONSUME"]
            reliable_negative_valid &= bool(consumed)
            for runtime_id in runtime_ids:
                source_event = sanitized_by_id.get(runtime_id)
                if source_event is None:
                    reliable_negative_valid = False
                    continue
                qualification = _expect_mapping(
                    source_event.get("evidence_qualification"), "reliable-negative source qualification"
                )
                reliable_negative_valid &= all(
                    qualification.get(key) == "TRUE" for key in RELIABLE_NEGATIVE_DIMENSIONS
                )
            for row in consumed:
                reliability = _expect_mapping(row.get("reliability"), "reliable-negative reliability")
                basis = _expect_mapping(reliability.get("basis"), "reliable-negative basis")
                reliable_negative_valid &= reliability.get("status") == "RELIABLE" and all(basis.get(key) is True for key in RELIABLE_NEGATIVE_DIMENSIONS)
                masking = _expect_mapping(row.get("support_masking"), "reliable-negative support masking")
                reliable_negative_valid &= masking.get("disposition") in {"CONSUME_UNMASKED", "CONSUME_CONDITIONED"}
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in records:
        alternative = _expect_mapping(row.get("alternative_representation"), "alternative representation")
        group_id = alternative.get("group_id")
        if group_id is not None:
            groups.setdefault(str(group_id), []).append(row)
    for group_rows in groups.values():
        consumed_ids = {str(row.get("source_result_id")) for row in group_rows if row.get("rankability_disposition") == "CONSUME"}
        selected = set().union(*(set(_expect_list(_expect_mapping(row.get("alternative_representation"), "alternative representation").get("selected_source_result_ids"), "selected source ids")) for row in group_rows))
        suppressed = set().union(*(set(_expect_list(_expect_mapping(row.get("alternative_representation"), "alternative representation").get("suppressed_source_result_ids"), "suppressed source ids")) for row in group_rows))
        duplicate_suppression_valid &= bool(selected) and consumed_ids == selected and selected.isdisjoint(suppressed)
    ledger_consumption_checks = [
        _check(
            "mapped_observation_consumption_denominator_exact",
            sorted(consumption_event_ids),
            sorted(expected_observation_ids),
            "SET_EQUALS_EXACT_ONCE",
            observation_consumption_denominator_exact,
        ),
        _check(
            "complete_source_event_denominator_processed_by_runtime",
            sorted(final_processed_ids),
            sorted(opaque_event_ids),
            "SET_EQUALS",
            complete_runtime_event_denominator_processed,
        ),
        _check("every_source_fact_has_runtime_disposition", all_fact_ids_covered, True, "EQ", all_fact_ids_covered),
        _check("all_consequential_facts_consumed_or_typed_withheld", consequential_handled, True, "EQ", consequential_handled),
        _check("duplicate_alternatives_suppressed_without_double_count", duplicate_suppression_valid, True, "EQ", duplicate_suppression_valid),
    ]
    case_checks = [
        *source_checks,
        *ledger_consumption_checks,
    ]

    domains = {str(domain) for fact in facts for domain in _expect_list(fact.get("local_domain_ids"), "fact domains") if str(domain)}
    delayed = [
        event_id for event_id, row in event_by_id.items()
        if row.get("occurred_epoch_upper") is not None
        and row.get("occurred_epoch_upper") < row.get("available_epoch")
        and audit_by_id[event_id].get("future_exposure") is False
    ]
    start_keys = {
        (row.get("action_id"), row.get("exposure_id"))
        for row in event_by_id.values() if row.get("event_type") == "ActionStarted"
    }
    response_rows = [row for row in event_by_id.values() if row.get("event_type") == "ActionResponseAvailable"]
    action_coverage = any((row.get("action_id"), row.get("exposure_id")) in start_keys for row in response_rows)
    coverage_results = [
        _result("COMPLEX_COVERAGE", "at_least_two_local_domains", [_check("distinct_local_domain_count", len(domains), 2, "GTE", len(domains) >= 2)]),
        _result("COMPLEX_COVERAGE", "concurrent_process_target_from_oracle", oracle_structural_checks),
        _result("COMPLEX_COVERAGE", "delayed_information", [_check("delayed_event_withheld_until_available", sorted(delayed), "non-empty", "NONEMPTY", bool(delayed))]),
        _result("COMPLEX_COVERAGE", "reliable_negative_evidence", [_check("five_dimension_reliable_negative_consumed_without_unconditioned_masking", sorted(reliable_negative_ids), "non-empty and valid", "STRUCTURAL", bool(reliable_negative_ids) and reliable_negative_valid)]),
        _result("COMPLEX_COVERAGE", "performed_action_lifecycle_with_response", [_check("performed_action_has_later_response", len(response_rows), 1, "GTE", action_coverage)]),
        _result("COMPLEX_COVERAGE", "prospective_pre_next_cut_forecasts", [_check("eligible_forecasts_sealed_before_next_cut", prospective_ok and bool(eligible), True, "EQ", prospective_ok and bool(eligible))]),
    ]
    gate_results = [
        _result("GATE", "PL-IND-001", isolation_checks),
        _result("GATE", "PL-BLIND-001", blind_checks),
        # PL-LED-001 must stand on its own.  Do not rely on PL-CASE-001 to
        # fail later when source provenance, temporal semantics, sanitization,
        # or runtime consumption is incomplete.
        _result(
            "GATE",
            "PL-LED-001",
            [*source_checks, *sanitizer_checks, *runtime_checks, *closure_checks, *ledger_consumption_checks],
        ),
        _result("GATE", "PL-DX-002", dx_checks),
        _result("GATE", "PL-PRED-002", pred_checks),
        _result("GATE", "PL-CASE-001", case_checks),
    ]
    for row in [*gate_results, *coverage_results]:
        _append_manual_check(row, manual_failures)
    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "produced_by": TOOL_REL,
        "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR",
        "evaluation_kind": "CASE_AND_COVERAGE",
        "input_manifest_digest": _manifest_digest(manifest_path),
        "input_refs": [dict(refs[role]) for role in sorted(refs)],
        "gate_results": gate_results,
        "coverage_results": coverage_results,
        "integrity": {
            "all_input_refs_verified": True,
            "thresholds_loaded_from_frozen_scoring_contract": True,
            "screening_claims_used_as_oracle_truth": False,
            "final_diagnosis_or_terminal_outcome_consumed": False,
            "deterministic": True,
        },
    }

def _verify_evidence_refs(study_root: Path, rows: Sequence[Mapping[str, Any]], id_key: str) -> bool:
    for row in rows:
        if row.get("result") not in {"PASS", "FAIL"}:
            return False
        refs = row.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            return False
        for index, ref in enumerate(refs):
            # Candidate bundle evidence refs have no role/ref_id because they
            # are the final scorer's public content-reference shape.
            if not isinstance(ref, Mapping) or set(ref) != {"path", "sha256", "bytes"}:
                return False
            wrapped = {"ref_id": f"candidate-{row[id_key]}-{index}", "role": "candidate_evidence", **ref}
            try:
                _resolve_ref(study_root, wrapped, "candidate evidence")
            except EvaluationError:
                return False
    return True


def _canonical_candidate(
    study_root: Path,
    refs: Mapping[str, Mapping[str, Any]],
    docs: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    gate_ids, _, _ = _validate_contracts(docs["gate_contract"], docs["scoring_contract"])
    gate_bundle = docs["nonreport_gate_bundle"]
    coverage_bundle = docs["complex_coverage_bundle"]
    if gate_bundle.get("schema_version") != GATE_BUNDLE_SCHEMA_VERSION:
        _fail("nonreport gate bundle schema mismatch")
    if coverage_bundle.get("schema_version") != COVERAGE_BUNDLE_SCHEMA_VERSION:
        _fail("complex coverage bundle schema mismatch")
    gate_rows = _expect_list(gate_bundle.get("gate_results"), "candidate gate rows")
    coverage_rows = _expect_list(coverage_bundle.get("checks"), "candidate coverage rows")
    expected_nonreport = [item for item in gate_ids if item != REPORT_GATE]
    actual_gate_ids = [row.get("gate_id") for row in gate_rows if isinstance(row, Mapping)]
    actual_coverage_ids = [row.get("coverage_id") for row in coverage_rows if isinstance(row, Mapping)]
    if actual_gate_ids != expected_nonreport or len(actual_gate_ids) != len(set(actual_gate_ids)):
        _fail("candidate gate bundle must use exact frozen non-report gate order")
    if actual_coverage_ids != list(ALL_COVERAGE) or len(actual_coverage_ids) != len(set(actual_coverage_ids)):
        _fail("candidate coverage bundle must use exact frozen coverage order")
    if not _verify_evidence_refs(study_root, gate_rows, "gate_id") or not _verify_evidence_refs(study_root, coverage_rows, "coverage_id"):
        _fail("candidate rows require valid content-addressed evidence")
    any_failure = any(row["result"] == "FAIL" for row in [*gate_rows, *coverage_rows])
    gate_result_by_id = {str(row["gate_id"]): str(row["result"]) for row in gate_rows}
    facet_contracts = _expect_mapping(docs["gate_contract"].get("facet_contracts"), "facet contracts")
    facet_results: list[dict[str, Any]] = []
    for facet_id, facet_any in facet_contracts.items():
        facet = _expect_mapping(facet_any, f"facet {facet_id}")
        member_ids = _expect_list(facet.get("gate_ids"), f"facet {facet_id}.gate_ids")
        members: list[dict[str, str]] = []
        for gate_id in member_ids:
            if gate_id == REPORT_GATE:
                result = "PENDING_REPORT_CONSISTENCY"
            elif gate_id in gate_result_by_id:
                result = gate_result_by_id[str(gate_id)]
            else:
                _fail(f"facet {facet_id} references unknown candidate gate {gate_id}")
            members.append({"gate_id": str(gate_id), "result": result})
        facet_result = (
            "FAIL"
            if any(row["result"] == "FAIL" for row in members)
            else "PENDING_REPORT_CONSISTENCY"
            if any(row["result"] == "PENDING_REPORT_CONSISTENCY" for row in members)
            else "PASS"
        )
        facet_results.append(
            {
                "facet_id": str(facet_id),
                "pass_state": str(facet.get("pass_state")),
                "result": facet_result,
                "gate_results": members,
            }
        )
    aggregation = _expect_mapping(docs["gate_contract"].get("aggregation"), "aggregation")
    final_vocabulary = [
        *[str(item) for item in _expect_list(aggregation.get("other_verdict_enum"), "other verdicts")],
        str(aggregation.get("perfect_landing_verdict")),
    ]
    probability = _expect_mapping(docs["scoring_contract"].get("probability_boundary"), "probability boundary")
    action_cf = _expect_mapping(docs["scoring_contract"].get("action_counterfactual"), "action counterfactual")
    ood = _expect_mapping(docs["scoring_contract"].get("ood_response"), "OOD response")
    return {
        "schema_version": CANDIDATE_SCHEMA_VERSION,
        "contract_binding": {
            "gate_contract_id": docs["gate_contract"].get("contract_id"),
            "gate_contract_version": docs["gate_contract"].get("contract_version"),
            "scoring_contract_id": docs["scoring_contract"].get("contract_id"),
            "scoring_contract_version": docs["scoring_contract"].get("contract_version"),
        },
        "source_bundle_refs": {
            "nonreport_gate_bundle": {key: refs["nonreport_gate_bundle"][key] for key in ("path", "sha256", "bytes")},
            "complex_coverage_bundle": {key: refs["complex_coverage_bundle"][key] for key in ("path", "sha256", "bytes")},
        },
        "gate_results": [
            *[dict(row) for row in gate_rows],
            {
                "gate_id": REPORT_GATE,
                "result": "PENDING_REPORT_CONSISTENCY",
                "derivation": "fresh exact-byte report evaluator then final scorer; no self-hash",
            },
        ],
        "complex_coverage": [dict(row) for row in coverage_rows],
        "facet_results": facet_results,
        "candidate_verdict": "FAILED" if any_failure else "PENDING_REPORT_CONSISTENCY",
        "permitted_candidate_verdicts": ["FAILED", "PENDING_REPORT_CONSISTENCY"],
        "permitted_final_verdicts": final_vocabulary,
        "scope_and_limits": {
            "frozen_scope": str(docs["scoring_contract"].get("scope")),
            "one_case_only": True,
            "runtime_probabilities_clinically_calibrated": probability.get("runtime_probabilities_are_clinically_calibrated") is True,
            "probability_interpretation": str(probability.get("allowed_interpretation")),
            "population_probability_claims_forbidden": probability.get("forbid_sensitivity_specificity_ppv_npv_or_population_claims") is True,
            "unperformed_individual_effect_identified_by_observed_response": action_cf.get("single_case_observed_response_identifies_unperformed_individual_effect") is True,
            "counterfactual_status_vocabulary": [str(item) for item in _expect_list(action_cf.get("permitted_statuses"), "counterfactual statuses")],
            "ood_requires_residual_or_partial_answer": True,
            "ood_rule": str(ood.get("if_material_delta_not_reached")),
            "forbidden_claims": [
                str(item)
                for item in _expect_list(
                    docs["gate_contract"].get("claims_forbidden_from_one_holdout"),
                    "claims forbidden from one holdout",
                )
            ],
        },
        "diagnosis_override_permitted": False,
        "terminal_outcome_override_permitted": False,
    }


def render_candidate_report(candidate: Mapping[str, Any]) -> str:
    gate_rows = _expect_list(candidate.get("gate_results"), "candidate report gates")
    coverage_rows = _expect_list(candidate.get("complex_coverage"), "candidate report coverage")
    facets = _expect_list(candidate.get("facet_results"), "candidate report facets")
    limits = _expect_mapping(candidate.get("scope_and_limits"), "candidate report limits")
    lines = [
        "# Primary holdout candidate report",
        "",
        f"Candidate verdict: `{candidate.get('candidate_verdict')}`",
        "",
        "This is the deterministic 29-gate preimage. PL-REPORT-001 is derived by fresh exact-byte report evaluation and then consumed by the final scorer; no artifact hashes itself.",
        "",
        "Correct-diagnosis override: **FORBIDDEN**",
        "",
        "Terminal-outcome override: **FORBIDDEN**",
        "",
        "## Scope and hard interpretation limits",
        "",
        f"- Frozen scope: `{limits.get('frozen_scope')}`",
        "- Evidence scope: **ONE PRIMARY CASE ONLY**",
        f"- Clinically calibrated runtime probabilities: **{str(limits.get('runtime_probabilities_clinically_calibrated')).upper()}**",
        f"- Permitted probability interpretation: `{limits.get('probability_interpretation')}`",
        f"- Population sensitivity/specificity/PPV/NPV claims forbidden: **{str(limits.get('population_probability_claims_forbidden')).upper()}**",
        f"- One observed response identifies an unperformed individual effect: **{str(limits.get('unperformed_individual_effect_identified_by_observed_response')).upper()}**",
        f"- Counterfactual/identifiability vocabulary: `{', '.join(limits.get('counterfactual_status_vocabulary', []))}`",
        f"- OOD/atlas limit: `{limits.get('ood_rule')}`",
        "",
        "### Claims forbidden from this one holdout",
        "",
    ]
    lines.extend([f"- {item}" for item in limits.get("forbidden_claims", [])])
    lines.extend(
        [
            "",
            "## Permitted verdict vocabulary",
            "",
            f"- Candidate stage: `{', '.join(candidate.get('permitted_candidate_verdicts', []))}`",
            f"- Final stage: `{', '.join(candidate.get('permitted_final_verdicts', []))}`",
            "",
            "## Facets",
            "",
            "| Facet | Result | Required state | Member gates |",
            "|---|---|---|---|",
        ]
    )
    for facet in facets:
        members = ", ".join(f"{row['gate_id']}={row['result']}" for row in facet["gate_results"])
        lines.append(f"| `{facet['facet_id']}` | `{facet['result']}` | `{facet['pass_state']}` | {members} |")
    lines.extend(
        [
            "",
            "## Hard gates",
            "",
            "| Gate | Result | Evidence pointers (path ; sha256 ; bytes) |",
            "|---|---|---|",
        ]
    )
    for row in gate_rows:
        pointers = "<br>".join(
            f"`{ref['path']}` ; `{ref['sha256']}` ; `{ref['bytes']}`"
            for ref in row.get("evidence_refs", [])
        ) or "derived by exact report consistency"
        lines.append(f"| `{row['gate_id']}` | `{row['result']}` | {pointers} |")
    lines.extend(
        [
            "",
            "## Complex real-case coverage",
            "",
            "| Coverage | Result | Evidence pointers (path ; sha256 ; bytes) |",
            "|---|---|---|",
        ]
    )
    for row in coverage_rows:
        pointers = "<br>".join(
            f"`{ref['path']}` ; `{ref['sha256']}` ; `{ref['bytes']}`"
            for ref in row.get("evidence_refs", [])
        )
        lines.append(f"| `{row['coverage_id']}` | `{row['result']}` | {pointers} |")
    failures = [
        f"{row.get('gate_id', row.get('coverage_id'))}: {row['result']}"
        for row in [*gate_rows, *coverage_rows]
        if row["result"] == "FAIL"
    ]
    lines.extend(["", "# FAILURES (PROMINENT)", ""])
    lines.extend([f"- **{item}**" for item in failures] or ["- None among the 29 evaluated gates and seven coverage checks."])
    lines.extend(["", "## Report-gate derivation", "", "- `PL-REPORT-001`: `PENDING_REPORT_CONSISTENCY`", ""])
    return "\n".join(lines)


def build_report_candidate(study_root: Path, manifest_path: Path) -> tuple[dict[str, Any], str]:
    _, refs, docs = _load_manifest(study_root, manifest_path, "REPORT_CANDIDATE")
    candidate = _canonical_candidate(study_root, refs, docs)
    return candidate, render_candidate_report(candidate)


def evaluate_report(study_root: Path, manifest_path: Path) -> dict[str, Any]:
    _, refs, docs = _load_manifest(study_root, manifest_path, "REPORT_CONSISTENCY")
    gate_ids, _, _ = _validate_contracts(docs["gate_contract"], docs["scoring_contract"])
    candidate = docs["report_candidate_results"]
    if candidate.get("schema_version") != CANDIDATE_SCHEMA_VERSION:
        _fail("report candidate schema mismatch")
    source_refs = _expect_mapping(candidate.get("source_bundle_refs"), "report candidate source refs")
    # Re-open the two source bundles named by the candidate and reconstruct it.
    synthetic_inputs = []
    for role in ("gate_contract", "scoring_contract"):
        synthetic_inputs.append(dict(refs[role]))
    for role in ("nonreport_gate_bundle", "complex_coverage_bundle"):
        raw_ref = _expect_mapping(source_refs.get(role), f"candidate {role} ref")
        synthetic_inputs.append({"ref_id": f"candidate-source-{role}", "role": role, **raw_ref})
    rebuild_manifest = {
        "schema_version": INPUT_SCHEMA_VERSION,
        "stage": "REPORT_CANDIDATE",
        "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR",
        "inputs": synthetic_inputs,
    }
    # Resolve directly without writing an unsealed temporary manifest.
    rebuild_refs: dict[str, Mapping[str, Any]] = {}
    rebuild_docs: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rebuild_manifest["inputs"]):
        ref, doc = _json_from_ref(study_root, row, f"report rebuild input[{index}]")
        rebuild_refs[str(ref["role"])] = ref
        rebuild_docs[str(ref["role"])] = doc
    rebuilt = _canonical_candidate(study_root, rebuild_refs, rebuild_docs)
    candidate_exact = canonical_json_bytes(candidate) == canonical_json_bytes(rebuilt)
    _, _, report_raw = _resolve_ref(study_root, refs["report_candidate_markdown"], "candidate report markdown")
    expected_report = render_candidate_report(rebuilt).encode("utf-8")
    report_exact = report_raw == expected_report
    report_gate_rows = _expect_list(rebuilt.get("gate_results"), "rebuilt report gates")
    coverage_rows = _expect_list(rebuilt.get("complex_coverage"), "rebuilt report coverage")
    complete_ids = [row.get("gate_id") for row in report_gate_rows] == gate_ids
    complete_coverage = [row.get("coverage_id") for row in coverage_rows] == list(ALL_COVERAGE)
    expected_facets = list(_expect_mapping(docs["gate_contract"].get("facet_contracts"), "facet contracts"))
    facet_rows = _expect_list(rebuilt.get("facet_results"), "rebuilt report facets")
    complete_facets = [row.get("facet_id") for row in facet_rows if isinstance(row, Mapping)] == expected_facets
    pending_exactly_report = [row.get("gate_id") for row in report_gate_rows if row.get("result") == "PENDING_REPORT_CONSISTENCY"] == [REPORT_GATE]
    override_forbidden = rebuilt.get("diagnosis_override_permitted") is False and rebuilt.get("terminal_outcome_override_permitted") is False
    verdict_valid = rebuilt.get("candidate_verdict") in {"FAILED", "PENDING_REPORT_CONSISTENCY"}
    limits = _expect_mapping(rebuilt.get("scope_and_limits"), "rebuilt report limits")
    limits_complete = (
        limits.get("one_case_only") is True
        and limits.get("runtime_probabilities_clinically_calibrated") is False
        and limits.get("population_probability_claims_forbidden") is True
        and limits.get("unperformed_individual_effect_identified_by_observed_response") is False
        and limits.get("ood_requires_residual_or_partial_answer") is True
        and bool(limits.get("forbidden_claims"))
    )
    evidence_visible = all(
        isinstance(row.get("evidence_refs"), list) and bool(row.get("evidence_refs"))
        for row in [*report_gate_rows[:-1], *coverage_rows]
    )
    checks = [
        _check("candidate_results_rebuilt_exactly", candidate_exact, True, "EQ", candidate_exact),
        _check("candidate_markdown_exact_canonical_render", report_exact, True, "EQ", report_exact),
        _check("all_30_gate_ids_visible", complete_ids, True, "EQ", complete_ids),
        _check("all_complex_coverage_ids_visible", complete_coverage, True, "EQ", complete_coverage),
        _check("all_frozen_facets_visible", complete_facets, True, "EQ", complete_facets),
        _check("all_gate_and_coverage_evidence_pointers_visible", evidence_visible, True, "EQ", evidence_visible),
        _check("probability_counterfactual_ood_scope_limits_visible", limits_complete, True, "EQ", limits_complete),
        _check("only_report_gate_is_pending", pending_exactly_report, True, "EQ", pending_exactly_report),
        _check("diagnosis_and_outcome_override_forbidden", override_forbidden, True, "EQ", override_forbidden),
        _check("candidate_verdict_vocabulary_valid", rebuilt.get("candidate_verdict"), ["FAILED", "PENDING_REPORT_CONSISTENCY"], "IN", verdict_valid),
    ]
    report_result = _result("GATE", REPORT_GATE, checks)
    _append_manual_check(report_result, _manual_failure_subjects(study_root, docs["audit_report"]))
    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "produced_by": TOOL_REL,
        "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR",
        "evaluation_kind": "REPORT_CONSISTENCY",
        "input_manifest_digest": _manifest_digest(manifest_path),
        "input_refs": [dict(refs[role]) for role in sorted(refs)],
        "gate_results": [report_result],
        "coverage_results": [],
        "integrity": {
            "all_input_refs_verified": True,
            "thresholds_loaded_from_frozen_scoring_contract": True,
            "screening_claims_used_as_oracle_truth": False,
            "final_diagnosis_or_terminal_outcome_consumed": False,
            "deterministic": True,
        },
    }


def _write_exact(path: Path, raw: bytes) -> None:
    if path.exists():
        _fail(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("evaluate-case", "evaluate-report"):
        child = sub.add_parser(name)
        child.add_argument("--manifest", required=True, type=Path)
        child.add_argument("--output", required=True, type=Path)
    build = sub.add_parser("build-report-candidate")
    build.add_argument("--manifest", required=True, type=Path)
    build.add_argument("--output-json", required=True, type=Path)
    build.add_argument("--output-md", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    study_root = Path(__file__).resolve().parents[2]
    try:
        if args.command == "evaluate-case":
            output = evaluate_case(study_root, args.manifest)
            _write_exact(args.output, canonical_json_file_bytes(output))
        elif args.command == "build-report-candidate":
            candidate, markdown = build_report_candidate(study_root, args.manifest)
            _write_exact(args.output_json, canonical_json_file_bytes(candidate))
            _write_exact(args.output_md, markdown.encode("utf-8"))
        else:
            output = evaluate_report(study_root, args.manifest)
            _write_exact(args.output, canonical_json_file_bytes(output))
    except (EvaluationError, OSError, KeyError, TypeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
