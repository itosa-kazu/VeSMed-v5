#!/usr/bin/env python3
"""Build and verify the case-blind pre-primary holdout seal.

This program deliberately has a very small read surface.  It may read only the
frozen architecture, both representations of the frozen gate contract and its
component seal, case-blind runtime, case-blind generic model, and an
identifier-only exclusion list.  It never discovers or opens a case-selection
file, article, event ledger, mapping, or replay output.

The combined seal is not a replacement for the component seals.  It is the
atomic, independently-verifiable statement that *all* components were frozen
before primary holdout selection.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, NoReturn, Sequence


FORMAT_VERSION = "NCF-PRE-PRIMARY-HOLDOUT-SEAL-1.0.0"
ARCHITECTURE_VERSION = "NCF-ARCH-1.0.0"
RUNTIME_VERSION = "2.1"
GATE_CONTRACT_VERSION = "1.1.0"
EXECUTION_PROTOCOL_VERSION = "1.1.0"

# Fixed relative paths are part of the security boundary.  In particular the
# CLI cannot be pointed at an arbitrary JSON file that happens to contain a
# patient narrative.
REL_ARCH_DOC = PurePosixPath("ARCHITECTURE_FINAL_v1.md")
REL_ARCH_SCHEMA = PurePosixPath("architecture_final_v1.schema.json")
REL_GATES_MD = PurePosixPath("holdout/PERFECT_LANDING_GATES.md")
REL_GATES_JSON = PurePosixPath("holdout/PERFECT_LANDING_GATES.json")
REL_GATES_SEAL = PurePosixPath("holdout/PERFECT_LANDING_GATES.seal.json")
REL_RUNTIME_ROOT = PurePosixPath("runtime_v2")
REL_RUNTIME_MANIFEST = PurePosixPath("runtime_v2/evidence/manifest.json")
REL_RUNTIME_SEAL = PurePosixPath("runtime_v2/evidence/FREEZE_SEAL.json")
REL_MODEL_ROOT = PurePosixPath("holdout/generic_model")
REL_MODEL_PACK = PurePosixPath("holdout/generic_model/model_pack.json")
REL_MAPPER_SANITIZED_REGISTRY = PurePosixPath(
    "holdout/generic_model/mapper_sanitized_registry.json"
)
REL_MODEL_VALIDATION = PurePosixPath("holdout/generic_model/model_validation.json")
REL_MODEL_SEAL = PurePosixPath("holdout/evidence/GENERIC_MODEL_FREEZE_SEAL.json")
REL_EXCLUSIONS = PurePosixPath("holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json")
REL_EXECUTION_PROTOCOL_MD = PurePosixPath("holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.md")
REL_EXECUTION_PROTOCOL_JSON = PurePosixPath("holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json")
REL_SCORING_CONTRACT = PurePosixPath("holdout/PRIMARY_HOLDOUT_SCORING_v1.json")
REL_PREPRIMARY_SEAL_TOOL = PurePosixPath("holdout/tools/build_pre_primary_holdout_seal.py")
REL_PREPRIMARY_SEAL_TEST = PurePosixPath("holdout/tools/test_pre_primary_holdout_seal.py")
REL_SELECTOR_TOOL = PurePosixPath("holdout/tools/select_primary_holdout.py")
REL_SELECTOR_TEST = PurePosixPath("holdout/tools/test_select_primary_holdout.py")
REL_RAW_SEARCH_VALIDATOR = PurePosixPath("holdout/tools/validate_primary_search_snapshot.py")
REL_RAW_SEARCH_VALIDATOR_TEST = PurePosixPath("holdout/tools/test_validate_primary_search_snapshot.py")
REL_RAW_SEARCH_COMPILER = PurePosixPath("holdout/tools/compile_primary_search_snapshot.py")
REL_RAW_SEARCH_COMPILER_TEST = PurePosixPath("holdout/tools/test_compile_primary_search_snapshot.py")
REL_SCREENING_VALIDATOR = PurePosixPath("holdout/tools/validate_primary_case_screening.py")
REL_SCREENING_VALIDATOR_TEST = PurePosixPath("holdout/tools/test_validate_primary_case_screening.py")
REL_COMPLEXITY_COMPILER = PurePosixPath(
    "holdout/tools/compile_opaque_concurrent_process_candidates.py"
)
REL_COMPLEXITY_COMPILER_TEST = PurePosixPath(
    "holdout/tools/test_compile_opaque_concurrent_process_candidates.py"
)
REL_SANITIZED_LEDGER_COMPILER = PurePosixPath(
    "holdout/tools/compile_evaluator_sanitized_runtime_ledger.py"
)
REL_SANITIZED_LEDGER_COMPILER_TEST = PurePosixPath(
    "holdout/tools/test_compile_evaluator_sanitized_runtime_ledger.py"
)
REL_SANITIZED_LEDGER_REPLAY_VERIFIER = PurePosixPath(
    "holdout/tools/verify_evaluator_sanitized_runtime_ledger.py"
)
REL_SANITIZED_LEDGER_REPLAY_VERIFIER_TEST = PurePosixPath(
    "holdout/tools/test_verify_evaluator_sanitized_runtime_ledger.py"
)
REL_PROTOCOL_VALIDATOR = PurePosixPath("holdout/tools/validate_primary_holdout_protocol.py")
REL_PROTOCOL_VALIDATOR_TEST = PurePosixPath("holdout/tools/test_validate_primary_holdout_protocol.py")
REL_FINAL_SCORER = PurePosixPath("holdout/tools/final_primary_holdout_scorer.py")
REL_FINAL_SCORER_TEST = PurePosixPath("holdout/tools/test_final_primary_holdout_scorer.py")
REL_PRODUCER_REPLAY_VERIFIER = PurePosixPath("holdout/tools/producer_replay_verifier.py")
REL_PRODUCER_REPLAY_VERIFIER_TEST = PurePosixPath("holdout/tools/test_producer_replay_verifier.py")
REL_PRIMARY_CASE_GATE_EVALUATOR = PurePosixPath("holdout/tools/primary_case_gate_evaluator.py")
REL_PRIMARY_CASE_GATE_EVALUATOR_TEST = PurePosixPath(
    "holdout/tools/test_primary_case_gate_evaluator.py"
)
REL_PRIMARY_CASE_GATE_EVALUATOR_RUNTIME_TEST = PurePosixPath(
    "holdout/tools/test_primary_case_gate_evaluator_runtime.py"
)
REL_PRIMARY_GATE_EVIDENCE_COMPILER = PurePosixPath(
    "holdout/tools/compile_primary_case_gate_evidence.py"
)
REL_PRIMARY_GATE_EVIDENCE_COMPILER_TEST = PurePosixPath(
    "holdout/tools/test_compile_primary_case_gate_evidence.py"
)
REL_PRIMARY_RUNTIME_REPLAY_EXECUTOR = PurePosixPath(
    "holdout/tools/primary_runtime_replay_executor.py"
)
REL_PRIMARY_RUNTIME_REPLAY_EXECUTOR_TEST = PurePosixPath(
    "holdout/tools/test_primary_runtime_replay_executor.py"
)
REL_AVAILABILITY_COMPILER = PurePosixPath("holdout/tools/compile_availability_epochs.py")
REL_AVAILABILITY_COMPILER_TEST = PurePosixPath("holdout/tools/test_compile_availability_epochs.py")
REL_EVENT_LEDGER_REPLAY = PurePosixPath("holdout/tools/event_ledger_replay.py")
REL_EVENT_LEDGER_REPLAY_TEST = PurePosixPath("holdout/tools/test_event_ledger_replay.py")
REL_STRUCTURAL_GATE_HARNESS = PurePosixPath("holdout/tools/structural_gate_harness.py")
REL_STRUCTURAL_GATE_HARNESS_TEST = PurePosixPath("holdout/tools/test_structural_gate_harness.py")
REL_STRUCTURAL_GATE_EVIDENCE_SCHEMA = PurePosixPath("holdout/tools/structural_gate_evidence.schema.json")
REL_STRUCTURAL_GATE_RESULTS_SCHEMA = PurePosixPath("holdout/tools/structural_gate_results.schema.json")
REL_ROLE_MANIFEST_SCHEMA = PurePosixPath("holdout/schemas/primary_role_execution_manifest.schema.json")
REL_ROLE_MANIFEST_SET_SCHEMA = PurePosixPath("holdout/schemas/primary_role_manifest_set.schema.json")
REL_ROLE_TOOL_ACCESS_TRACE_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_role_tool_access_trace.schema.json"
)
REL_SANITIZED_RUNTIME_LEDGER_SCHEMA = PurePosixPath(
    "holdout/schemas/evaluator_sanitized_runtime_ledger.schema.json"
)
REL_SANITIZED_LEDGER_COMPILER_INPUT_SCHEMA = PurePosixPath(
    "holdout/schemas/evaluator_sanitized_runtime_ledger_compiler_input.schema.json"
)
REL_SANITIZED_LEDGER_ASSIGNMENT_PROOF_SCHEMA = PurePosixPath(
    "holdout/schemas/evaluator_sanitized_runtime_ledger_assignment_proof.schema.json"
)
REL_SANITIZED_LEDGER_REPLAY_VERIFICATION_SCHEMA = PurePosixPath(
    "holdout/schemas/evaluator_sanitized_runtime_ledger_replay_verification.schema.json"
)
REL_ALL_SEALED_REPLAY_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_all_sealed_artifacts_after_replay.schema.json"
)
REL_SEALED_CONCEPT_MAP_SCHEMA = PurePosixPath(
    "holdout/schemas/sealed_concept_map.schema.json"
)
REL_SEARCH_SNAPSHOT_SCHEMA = PurePosixPath("holdout/schemas/primary_case_search_snapshot.schema.json")
REL_RAW_SEARCH_RESPONSE_SCHEMA = PurePosixPath("holdout/schemas/primary_raw_search_response.schema.json")
REL_RAW_SEARCH_RETRIEVAL_SCHEMA = PurePosixPath("holdout/schemas/primary_search_retrieval_manifest.schema.json")
REL_SCREENING_SCHEMA = PurePosixPath("holdout/schemas/primary_case_screening.schema.json")
REL_SCREENING_EVIDENCE_SCHEMA = PurePosixPath("holdout/schemas/primary_screening_evidence.schema.json")
REL_COMPLEXITY_CLAIMS_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_opaque_concurrent_process_candidate_claims.schema.json"
)
REL_COMPLEXITY_PACKET_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_opaque_concurrent_process_candidate_packet.schema.json"
)
REL_SEALED_COMPLEXITY_PACKET_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_sealed_opaque_concurrent_process_candidate_packet.schema.json"
)
REL_MAPPED_OBSERVATION_SCHEMA = PurePosixPath("holdout/schemas/mapped_observation_consumption.schema.json")
REL_FINAL_RESULT_SCHEMA = PurePosixPath("holdout/schemas/primary_holdout_final_result.schema.json")
REL_GATE_EVIDENCE_SCHEMA = PurePosixPath("holdout/schemas/primary_gate_evidence.schema.json")
REL_PRIMARY_CASE_GATE_EVALUATOR_INPUT_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_case_gate_evaluator_input.schema.json"
)
REL_PRIMARY_CASE_GATE_EVALUATION_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_case_gate_evaluation.schema.json"
)
REL_PRIMARY_REPORT_CANDIDATE_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_report_candidate.schema.json"
)
REL_PRIMARY_RUNTIME_REPLAY_INPUT_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_runtime_replay_input_manifest.schema.json"
)
REL_PRIMARY_RUNTIME_OUTPUT_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_runtime_output.schema.json"
)
REL_PRIMARY_RUNTIME_REPLAY_SEAL_SCHEMA = PurePosixPath(
    "holdout/schemas/primary_runtime_replay_seal.schema.json"
)
REL_AVAILABILITY_SCHEMA = PurePosixPath("holdout/schemas/primary_availability_ledger.schema.json")
REL_OUTPUT = PurePosixPath("holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json")

SOURCE_SUFFIXES = {".py", ".json", ".md", ".txt", ".toml", ".yaml", ".yml"}
SOURCE_BASENAMES = {".gitignore"}
IGNORED_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".git"}

# Apply only to relative descendants of the two approved source roots.  The
# study directory itself intentionally contains "case_study" and is not tested.
# Generic runtime concepts such as ``ledger.py`` are legitimate source.  Reject
# only paths that identify an actual holdout/case artifact, not clinical-engine
# vocabulary in the abstract.
FORBIDDEN_SOURCE_TOKEN = re.compile(
    r"(?:^|/)(?:cases)(?:/|$)|"
    r"primary[_\-.]?case|case[_\-.]?selection|case[_\-.]?event[_\-.]?ledger|"
    r"patient[_\-.]?(?:record|narrative)|holdout[_\-.]?(?:article|replay)|"
    r"(?:pmc|pmid)\d{3,}",
    re.IGNORECASE,
)
SAFE_EXCLUSION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{1,127}$")


class SealError(RuntimeError):
    """A fail-closed contract or integrity failure."""


@dataclass(frozen=True)
class Artifact:
    path: str
    sha256: str
    bytes: int

    def as_dict(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "bytes": self.bytes}


def _fail(message: str) -> NoReturn:
    raise SealError(message)


def _canonical_bytes(value: Any) -> bytes:
    """Stable compact JSON used only for manifest/payload digests."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def _study_path(study_root: Path, rel: PurePosixPath) -> Path:
    root = study_root.resolve(strict=True)
    candidate = root.joinpath(*rel.parts)
    # Resolve parents even if the output does not yet exist.
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        _fail(f"path escapes study root: {rel}")
    return candidate


def _required_file(study_root: Path, rel: PurePosixPath) -> Path:
    path = _study_path(study_root, rel)
    if not path.is_file():
        _fail(f"required file is missing: {rel.as_posix()}")
    if path.is_symlink():
        _fail(f"symlink input is forbidden: {rel.as_posix()}")
    return path


def _artifact(study_root: Path, rel: PurePosixPath) -> Artifact:
    path = _required_file(study_root, rel)
    return Artifact(rel.as_posix(), _sha256_file(path), path.stat().st_size)


def _load_json(study_root: Path, rel: PurePosixPath) -> Any:
    path = _required_file(study_root, rel)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid UTF-8 JSON in {rel.as_posix()}: {exc}")


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a JSON object")
    return value


def _assert_no_bad_status(value: Any, label: str) -> None:
    bad = ("PENDING", "DRAFT", "SUPERSEDED", "INCOMPLETE", "HARNESS_INCOMPLETE", "FAIL")

    def visit(item: Any, key_path: str) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if str(key).lower() in {
                    "status",
                    "freeze_status",
                    "structural_claim_status",
                    "validation_status",
                    "result",
                }:
                    if isinstance(child, str) and any(token in child.upper() for token in bad):
                        _fail(f"{label} is not final ({key_path}.{key}={child!r})")
                visit(child, f"{key_path}.{key}")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                visit(child, f"{key_path}[{index}]")

    visit(value, label)


def _assert_hash(value: Any, expected: str, label: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        _fail(f"{label} is not a lowercase SHA-256")
    if value != expected:
        _fail(f"hash mismatch for {label}: expected {expected}, sealed {value}")


def _tree_files(study_root: Path, rel_root: PurePosixPath) -> list[Artifact]:
    root = _study_path(study_root, rel_root)
    if not root.is_dir() or root.is_symlink():
        _fail(f"source root is missing or is a symlink: {rel_root.as_posix()}")

    artifacts: list[Artifact] = []
    for current, dirnames, filenames in os.walk(root, followlinks=False):
        current_path = Path(current)
        # Reject rather than silently follow any directory symlink.
        for dirname in list(dirnames):
            child = current_path / dirname
            if child.is_symlink():
                _fail(f"symlink directory in source tree: {child.relative_to(study_root).as_posix()}")
        excluded_here = set(IGNORED_DIRS)
        # Runtime evidence is generated output, not recursive source.  The
        # authoritative manifest and freeze seal within it are hashed and
        # semantically verified as explicit component artifacts instead.
        if rel_root == REL_RUNTIME_ROOT and current_path == root:
            excluded_here.add("evidence")
        dirnames[:] = sorted(d for d in dirnames if d not in excluded_here)

        for filename in sorted(filenames):
            path = current_path / filename
            if path.is_symlink():
                _fail(f"symlink file in source tree: {path.relative_to(study_root).as_posix()}")
            rel_inside = path.relative_to(root).as_posix()
            if FORBIDDEN_SOURCE_TOKEN.search(rel_inside):
                # The offending file is rejected before it is opened.
                _fail(f"case-shaped source path forbidden in case-blind tree: {rel_inside}")
            if path.suffix.lower() not in SOURCE_SUFFIXES and path.name not in SOURCE_BASENAMES:
                continue
            rel_study = path.relative_to(study_root).as_posix()
            artifacts.append(Artifact(rel_study, _sha256_file(path), path.stat().st_size))

    if not artifacts:
        _fail(f"source tree has no hashable source files: {rel_root.as_posix()}")
    artifacts.sort(key=lambda item: item.path)
    return artifacts


def _tree_record(files: Sequence[Artifact]) -> dict[str, Any]:
    file_dicts = [item.as_dict() for item in files]
    return {
        "file_count": len(file_dicts),
        "total_bytes": sum(item["bytes"] for item in file_dicts),
        "tree_sha256": _sha256_bytes(_canonical_bytes(file_dicts)),
        "files": file_dicts,
    }


def _validate_architecture_schema(study_root: Path) -> str:
    schema = _require_mapping(_load_json(study_root, REL_ARCH_SCHEMA), "architecture schema")
    version = schema.get("$id") or schema.get("title")
    # The authoritative version is also asserted by the gate contract below.
    return str(version or ARCHITECTURE_VERSION)


def _validate_gate_contract(study_root: Path, arch: Artifact, arch_schema: Artifact) -> None:
    gates = _require_mapping(_load_json(study_root, REL_GATES_JSON), "gate contract")
    gate_seal = _require_mapping(_load_json(study_root, REL_GATES_SEAL), "gate seal")
    gate_markdown = _artifact(study_root, REL_GATES_MD)
    gate_json = _artifact(study_root, REL_GATES_JSON)
    if gates.get("status") != "FROZEN_BEFORE_HOLDOUT_INSPECTION":
        _fail("gate contract is not frozen before holdout inspection")
    if gates.get("contract_version") != GATE_CONTRACT_VERSION:
        _fail(f"gate contract must be corrected version {GATE_CONTRACT_VERSION}")
    binding = _require_mapping(gates.get("architecture_binding"), "gate architecture binding")
    if binding.get("architecture_version") != ARCHITECTURE_VERSION:
        _fail("gate contract architecture version mismatch")
    _assert_hash(binding.get("architecture_document_sha256"), arch.sha256, "gate architecture document")
    _assert_hash(binding.get("wire_schema_sha256"), arch_schema.sha256, "gate architecture schema")
    gate_rows = gates.get("gates")
    if not isinstance(gate_rows, list) or len(gate_rows) != 30:
        _fail("gate contract must contain exactly 30 gates")
    gate_ids = {row.get("id") for row in gate_rows if isinstance(row, Mapping)}
    if len(gate_ids) != 30 or None in gate_ids:
        _fail("gate IDs must be present and unique")
    if any(str(row.get("severity", "")).lower() != "hard" for row in gate_rows if isinstance(row, Mapping)):
        _fail("every gate must be HARD")
    aggregation = _require_mapping(gates.get("aggregation"), "gate aggregation")
    if aggregation.get("top1_diagnosis_can_override_failure") is not False:
        _fail("top-1 diagnosis override must be forbidden")

    architecture_schema = _require_mapping(
        _load_json(study_root, REL_ARCH_SCHEMA), "architecture schema"
    )
    try:
        wire_identifiability = architecture_schema["$defs"]["identifiabilityClaim"][
            "properties"
        ]["status"]["enum"]
    except (KeyError, TypeError):
        _fail("architecture wire identifiability enum is missing")
    expected_identifiability = [
        "IDENTIFIED_WITHIN_SCOPE",
        "PARTIALLY_IDENTIFIED",
        "UNIDENTIFIABLE",
        "OUT_OF_SCOPE",
    ]
    if wire_identifiability != expected_identifiability:
        _fail("architecture wire identifiability enum differs from frozen expected enum")
    if gates.get("identifiability_enum") != wire_identifiability:
        _fail("gate identifiability enum must exactly match architecture wire")

    if gate_seal.get("case_identity_included") is not False:
        _fail("gate seal is not case blind")
    artifacts = gate_seal.get("artifacts")
    if not isinstance(artifacts, list):
        _fail("gate seal artifacts missing")
    expected = {
        "PERFECT_LANDING_GATES.md": gate_markdown.sha256,
        "PERFECT_LANDING_GATES.json": gate_json.sha256,
        "../ARCHITECTURE_FINAL_v1.md": arch.sha256,
        "../architecture_final_v1.schema.json": arch_schema.sha256,
    }
    seen: dict[str, str] = {}
    for row in artifacts:
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str):
            _fail("invalid gate seal artifact row")
        path_text = row["path"]
        rel = PurePosixPath(path_text)
        if rel.is_absolute() or rel.as_posix() != path_text:
            _fail(f"gate seal artifact path is not canonical: {path_text!r}")
        if path_text in seen:
            _fail(f"duplicate gate seal artifact path: {path_text}")
        seen[path_text] = str(row.get("sha256", ""))
    if set(seen) != set(expected):
        _fail(
            "gate seal must bind exactly markdown, JSON, architecture, and schema; "
            f"missing={sorted(set(expected) - set(seen))}, "
            f"extra={sorted(set(seen) - set(expected))}"
        )
    for rel_text, digest in expected.items():
        _assert_hash(seen.get(rel_text), digest, f"gate seal artifact {rel_text}")


def _validate_runtime(
    study_root: Path,
    runtime_tree: Sequence[Artifact],
) -> tuple[Artifact, Artifact]:
    manifest_artifact = _artifact(study_root, REL_RUNTIME_MANIFEST)
    seal_artifact = _artifact(study_root, REL_RUNTIME_SEAL)
    manifest = _require_mapping(_load_json(study_root, REL_RUNTIME_MANIFEST), "runtime manifest")
    seal = _require_mapping(_load_json(study_root, REL_RUNTIME_SEAL), "runtime seal")

    _assert_no_bad_status(seal, "runtime seal")
    if manifest.get("manifest_kind") != "runtime_v2_1_case_blind_implementation_manifest":
        _fail("runtime manifest_kind mismatch")
    if str(manifest.get("runtime_version")) != RUNTIME_VERSION:
        _fail(f"runtime manifest must explicitly bind runtime_version={RUNTIME_VERSION}")
    if manifest.get("architecture_version") != ARCHITECTURE_VERSION:
        _fail("runtime manifest architecture version mismatch")
    if manifest.get("case_blind") is not True:
        _fail("runtime manifest must explicitly assert case_blind=true")
    if seal.get("seal_kind") != "runtime_v2_1_case_blind_freeze":
        _fail("runtime seal_kind must be runtime_v2_1_case_blind_freeze")
    if str(seal.get("runtime_version")) != RUNTIME_VERSION:
        _fail(f"runtime seal must explicitly bind runtime_version={RUNTIME_VERSION}")
    if seal.get("architecture_version") != ARCHITECTURE_VERSION:
        _fail("runtime seal architecture version mismatch")
    if seal.get("case_blind") is not True or seal.get("final") is not True:
        _fail("runtime seal must explicitly assert case_blind=true and final=true")
    if not isinstance(seal.get("frozen_at"), str):
        _fail("runtime seal frozen_at missing")
    _assert_hash(seal.get("manifest_sha256"), manifest_artifact.sha256, "runtime manifest")

    manifest_rows = manifest.get("files")
    if not isinstance(manifest_rows, list):
        _fail("runtime manifest files missing")
    manifest_by_path: dict[str, Mapping[str, Any]] = {}
    for row in manifest_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str):
            _fail("invalid runtime manifest file row")
        path_text = row["path"]
        rel = PurePosixPath(path_text)
        if (
            rel.is_absolute()
            or ".." in rel.parts
            or rel.as_posix() != path_text
            or len(rel.parts) < 2
            or rel.parts[0] != REL_RUNTIME_ROOT.as_posix()
        ):
            _fail(f"runtime manifest path outside runtime root: {rel}")
        rel_inside_runtime = PurePosixPath(*rel.parts[1:]).as_posix()
        if FORBIDDEN_SOURCE_TOKEN.search(rel_inside_runtime):
            # Reject before _artifact opens the referenced path.  Runtime
            # evidence is an explicitly manifested component input, but it is
            # not an escape hatch around the case-blind source-tree guard.
            _fail(f"case-shaped runtime manifest path forbidden before open: {rel_inside_runtime}")
        if rel.as_posix() in manifest_by_path:
            _fail(f"duplicate runtime manifest path: {rel}")
        actual = _artifact(study_root, rel)
        _assert_hash(row.get("sha256"), actual.sha256, f"runtime manifest {rel}")
        if row.get("bytes") != actual.bytes:
            _fail(f"runtime manifest byte count mismatch: {rel}")
        manifest_by_path[rel.as_posix()] = row

    missing = sorted(item.path for item in runtime_tree if item.path not in manifest_by_path)
    if missing:
        _fail(f"runtime manifest does not bind all recursive source files: {missing}")
    fresh_source_tree = _tree_record(runtime_tree)
    expected_source_summary = {
        "file_count": fresh_source_tree["file_count"],
        "total_bytes": fresh_source_tree["total_bytes"],
        "tree_sha256": fresh_source_tree["tree_sha256"],
    }
    if manifest.get("source_tree") != expected_source_summary:
        _fail("runtime manifest source_tree summary does not match current recursive source tree")
    _assert_hash(seal.get("source_tree_sha256"), fresh_source_tree["tree_sha256"], "runtime source tree")
    return manifest_artifact, seal_artifact


def _validate_generic_model(
    study_root: Path,
    model_tree: Sequence[Artifact],
    runtime_manifest_artifact: Artifact,
    runtime_seal_artifact: Artifact,
) -> tuple[Artifact, Artifact, Artifact]:
    pack_artifact = _artifact(study_root, REL_MODEL_PACK)
    validation_artifact = _artifact(study_root, REL_MODEL_VALIDATION)
    seal_artifact = _artifact(study_root, REL_MODEL_SEAL)
    validation = _require_mapping(_load_json(study_root, REL_MODEL_VALIDATION), "model validation")
    seal = _require_mapping(_load_json(study_root, REL_MODEL_SEAL), "generic model seal")

    _assert_no_bad_status(validation, "model validation")
    _assert_no_bad_status(seal, "generic model seal")
    if validation.get("architecture_version") != ARCHITECTURE_VERSION:
        _fail("generic model validation architecture version mismatch")
    if str(validation.get("runtime_version")) != RUNTIME_VERSION:
        _fail(f"generic model validation must explicitly bind runtime_version={RUNTIME_VERSION}")
    if validation.get("case_blind") is not True:
        _fail("generic model validation must assert case_blind=true")
    if validation.get("status") not in {"PASS", "FINAL_PASS"}:
        _fail("generic model validation status must be PASS or FINAL_PASS")
    if seal.get("seal_kind") != "generic_model_case_blind_freeze":
        _fail("generic model seal_kind must be generic_model_case_blind_freeze")
    if seal.get("architecture_version") != ARCHITECTURE_VERSION:
        _fail("generic model seal architecture version mismatch")
    if str(seal.get("runtime_version")) != RUNTIME_VERSION:
        _fail(f"generic model seal must bind runtime_version={RUNTIME_VERSION}")
    if seal.get("case_blind") is not True or seal.get("final") is not True:
        _fail("generic model seal must explicitly assert case_blind=true and final=true")
    if not isinstance(seal.get("sealed_at"), str):
        _fail("generic model seal sealed_at missing")
    _assert_hash(seal.get("model_pack_sha256"), pack_artifact.sha256, "generic model pack")
    _assert_hash(seal.get("validation_sha256"), validation_artifact.sha256, "generic model validation")

    sealed_source_rows = seal.get("source_files")
    if not isinstance(sealed_source_rows, list):
        _fail("generic model component seal source_files missing")
    current_source_rows = [item.as_dict() for item in model_tree]
    if sealed_source_rows != current_source_rows:
        _fail("generic model component seal does not bind the current recursive source tree")
    current_tree_sha = _tree_record(model_tree)["tree_sha256"]
    _assert_hash(seal.get("source_tree_sha256"), current_tree_sha, "generic model source tree")

    # A model validated against a superseded runtime is not a frozen compatible
    # component merely because both artifacts still say "runtime_version=2.1".
    # Bind the exact runtime manifest and component seal transitively through
    # the model validation (whose hash is itself sealed above).
    runtime_binding = _require_mapping(validation.get("runtime_binding"), "generic model runtime binding")
    if str(runtime_binding.get("runtime_version", validation.get("runtime_version"))) != RUNTIME_VERSION:
        _fail("generic model runtime binding version mismatch")
    if runtime_binding.get("seal_kind") != "runtime_v2_1_case_blind_freeze":
        _fail("generic model runtime binding seal_kind mismatch")
    _assert_hash(
        runtime_binding.get("manifest_sha256"),
        runtime_manifest_artifact.sha256,
        "generic model bound runtime manifest",
    )
    _assert_hash(
        runtime_binding.get("seal_sha256"),
        runtime_seal_artifact.sha256,
        "generic model bound runtime seal",
    )
    return pack_artifact, validation_artifact, seal_artifact


def _validate_execution_contracts(study_root: Path) -> dict[str, Artifact]:
    artifacts = {
        "protocol_md": _artifact(study_root, REL_EXECUTION_PROTOCOL_MD),
        "protocol_json": _artifact(study_root, REL_EXECUTION_PROTOCOL_JSON),
        "scoring_contract": _artifact(study_root, REL_SCORING_CONTRACT),
        "preprimary_seal_tool": _artifact(study_root, REL_PREPRIMARY_SEAL_TOOL),
        "preprimary_seal_test": _artifact(study_root, REL_PREPRIMARY_SEAL_TEST),
        "selector_tool": _artifact(study_root, REL_SELECTOR_TOOL),
        "selector_test": _artifact(study_root, REL_SELECTOR_TEST),
        "raw_search_validator": _artifact(study_root, REL_RAW_SEARCH_VALIDATOR),
        "raw_search_validator_test": _artifact(study_root, REL_RAW_SEARCH_VALIDATOR_TEST),
        "raw_search_compiler": _artifact(study_root, REL_RAW_SEARCH_COMPILER),
        "raw_search_compiler_test": _artifact(study_root, REL_RAW_SEARCH_COMPILER_TEST),
        "screening_validator": _artifact(study_root, REL_SCREENING_VALIDATOR),
        "screening_validator_test": _artifact(study_root, REL_SCREENING_VALIDATOR_TEST),
        "complexity_compiler": _artifact(study_root, REL_COMPLEXITY_COMPILER),
        "complexity_compiler_test": _artifact(study_root, REL_COMPLEXITY_COMPILER_TEST),
        "evaluator_sanitized_runtime_ledger_compiler": _artifact(
            study_root, REL_SANITIZED_LEDGER_COMPILER
        ),
        "evaluator_sanitized_runtime_ledger_compiler_test": _artifact(
            study_root, REL_SANITIZED_LEDGER_COMPILER_TEST
        ),
        "evaluator_sanitized_runtime_ledger_compiler_input_schema": _artifact(
            study_root, REL_SANITIZED_LEDGER_COMPILER_INPUT_SCHEMA
        ),
        "evaluator_sanitized_runtime_ledger_compiler_output_schema": _artifact(
            study_root, REL_SANITIZED_RUNTIME_LEDGER_SCHEMA
        ),
        "evaluator_sanitized_runtime_ledger_assignment_proof_schema": _artifact(
            study_root, REL_SANITIZED_LEDGER_ASSIGNMENT_PROOF_SCHEMA
        ),
        "evaluator_sanitized_runtime_ledger_replay_verifier": _artifact(
            study_root, REL_SANITIZED_LEDGER_REPLAY_VERIFIER
        ),
        "evaluator_sanitized_runtime_ledger_replay_verifier_test": _artifact(
            study_root, REL_SANITIZED_LEDGER_REPLAY_VERIFIER_TEST
        ),
        "evaluator_sanitized_runtime_ledger_replay_verifier_schema": _artifact(
            study_root, REL_SANITIZED_LEDGER_REPLAY_VERIFICATION_SCHEMA
        ),
        "protocol_validator": _artifact(study_root, REL_PROTOCOL_VALIDATOR),
        "protocol_validator_test": _artifact(study_root, REL_PROTOCOL_VALIDATOR_TEST),
        "final_scorer": _artifact(study_root, REL_FINAL_SCORER),
        "final_scorer_test": _artifact(study_root, REL_FINAL_SCORER_TEST),
        "producer_replay_verifier": _artifact(study_root, REL_PRODUCER_REPLAY_VERIFIER),
        "producer_replay_verifier_test": _artifact(study_root, REL_PRODUCER_REPLAY_VERIFIER_TEST),
        "primary_case_gate_evaluator": _artifact(study_root, REL_PRIMARY_CASE_GATE_EVALUATOR),
        "primary_case_gate_evaluator_test": _artifact(
            study_root, REL_PRIMARY_CASE_GATE_EVALUATOR_TEST
        ),
        "primary_case_gate_evaluator_runtime_test": _artifact(
            study_root, REL_PRIMARY_CASE_GATE_EVALUATOR_RUNTIME_TEST
        ),
        "primary_gate_evidence_compiler": _artifact(
            study_root, REL_PRIMARY_GATE_EVIDENCE_COMPILER
        ),
        "primary_gate_evidence_compiler_test": _artifact(
            study_root, REL_PRIMARY_GATE_EVIDENCE_COMPILER_TEST
        ),
        "primary_runtime_replay_executor": _artifact(
            study_root, REL_PRIMARY_RUNTIME_REPLAY_EXECUTOR
        ),
        "primary_runtime_replay_executor_test": _artifact(
            study_root, REL_PRIMARY_RUNTIME_REPLAY_EXECUTOR_TEST
        ),
        "availability_compiler": _artifact(study_root, REL_AVAILABILITY_COMPILER),
        "availability_compiler_test": _artifact(study_root, REL_AVAILABILITY_COMPILER_TEST),
        "event_ledger_replay": _artifact(study_root, REL_EVENT_LEDGER_REPLAY),
        "event_ledger_replay_test": _artifact(study_root, REL_EVENT_LEDGER_REPLAY_TEST),
        "structural_gate_harness": _artifact(study_root, REL_STRUCTURAL_GATE_HARNESS),
        "structural_gate_harness_test": _artifact(study_root, REL_STRUCTURAL_GATE_HARNESS_TEST),
        "structural_gate_evidence_schema": _artifact(study_root, REL_STRUCTURAL_GATE_EVIDENCE_SCHEMA),
        "structural_gate_results_schema": _artifact(study_root, REL_STRUCTURAL_GATE_RESULTS_SCHEMA),
        "role_manifest_schema": _artifact(study_root, REL_ROLE_MANIFEST_SCHEMA),
        "role_manifest_set_schema": _artifact(study_root, REL_ROLE_MANIFEST_SET_SCHEMA),
        "role_tool_access_trace_schema": _artifact(study_root, REL_ROLE_TOOL_ACCESS_TRACE_SCHEMA),
        "evaluator_sanitized_runtime_ledger_schema": _artifact(
            study_root, REL_SANITIZED_RUNTIME_LEDGER_SCHEMA
        ),
        "all_sealed_artifacts_after_replay_schema": _artifact(
            study_root, REL_ALL_SEALED_REPLAY_SCHEMA
        ),
        "sealed_concept_map_schema": _artifact(study_root, REL_SEALED_CONCEPT_MAP_SCHEMA),
        "search_snapshot_schema": _artifact(study_root, REL_SEARCH_SNAPSHOT_SCHEMA),
        "raw_search_response_schema": _artifact(study_root, REL_RAW_SEARCH_RESPONSE_SCHEMA),
        "raw_search_retrieval_schema": _artifact(study_root, REL_RAW_SEARCH_RETRIEVAL_SCHEMA),
        "screening_schema": _artifact(study_root, REL_SCREENING_SCHEMA),
        "screening_evidence_schema": _artifact(study_root, REL_SCREENING_EVIDENCE_SCHEMA),
        "complexity_claims_schema": _artifact(study_root, REL_COMPLEXITY_CLAIMS_SCHEMA),
        "complexity_packet_schema": _artifact(study_root, REL_COMPLEXITY_PACKET_SCHEMA),
        "sealed_complexity_packet_schema": _artifact(
            study_root, REL_SEALED_COMPLEXITY_PACKET_SCHEMA
        ),
        "mapped_observation_schema": _artifact(study_root, REL_MAPPED_OBSERVATION_SCHEMA),
        "final_result_schema": _artifact(study_root, REL_FINAL_RESULT_SCHEMA),
        "gate_evidence_schema": _artifact(study_root, REL_GATE_EVIDENCE_SCHEMA),
        "primary_case_gate_evaluator_input_schema": _artifact(
            study_root, REL_PRIMARY_CASE_GATE_EVALUATOR_INPUT_SCHEMA
        ),
        "primary_case_gate_evaluation_schema": _artifact(
            study_root, REL_PRIMARY_CASE_GATE_EVALUATION_SCHEMA
        ),
        "primary_report_candidate_schema": _artifact(
            study_root, REL_PRIMARY_REPORT_CANDIDATE_SCHEMA
        ),
        "primary_runtime_replay_input_schema": _artifact(
            study_root, REL_PRIMARY_RUNTIME_REPLAY_INPUT_SCHEMA
        ),
        "primary_runtime_output_schema": _artifact(
            study_root, REL_PRIMARY_RUNTIME_OUTPUT_SCHEMA
        ),
        "primary_runtime_replay_seal_schema": _artifact(
            study_root, REL_PRIMARY_RUNTIME_REPLAY_SEAL_SCHEMA
        ),
        "availability_schema": _artifact(study_root, REL_AVAILABILITY_SCHEMA),
    }
    protocol = _require_mapping(
        _load_json(study_root, REL_EXECUTION_PROTOCOL_JSON), "execution protocol"
    )
    scoring = _require_mapping(
        _load_json(study_root, REL_SCORING_CONTRACT), "scoring contract"
    )
    if protocol.get("status") != "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION":
        _fail("execution protocol is not frozen before case search/selection")
    if protocol.get("protocol_version") != EXECUTION_PROTOCOL_VERSION:
        _fail("execution protocol version mismatch")
    if protocol.get("architecture_version") != ARCHITECTURE_VERSION:
        _fail("execution protocol architecture version mismatch")
    if protocol.get("gate_contract_version") != GATE_CONTRACT_VERSION:
        _fail("execution protocol gate binding mismatch")
    required_bindings = protocol.get("required_preprimary_bindings")
    required_binding_names = {
        "preprimary_combined_seal_tool",
        "preprimary_combined_seal_test_source",
        "selection_tool",
        "selection_tool_test_source",
        "role_tool_access_trace_schema",
        "evaluator_sanitized_runtime_ledger_schema",
        "all_sealed_artifacts_after_replay_schema",
        "sealed_concept_map_schema",
        "raw_search_response_schema",
        "raw_search_snapshot_validator",
        "raw_search_snapshot_validator_test_source",
        "raw_search_retrieval_manifest_schema",
        "raw_search_snapshot_compiler",
        "raw_search_snapshot_compiler_test_source",
        "screening_evidence_schema",
        "screening_validator",
        "screening_validator_test_source",
        "opaque_concurrent_process_candidate_claims_schema",
        "opaque_concurrent_process_candidate_packet_schema",
        "sealed_opaque_concurrent_process_candidate_packet_schema",
        "opaque_concurrent_process_candidate_compiler_tool",
        "opaque_concurrent_process_candidate_compiler_test_source",
        "evaluator_sanitized_runtime_ledger_compiler_tool",
        "evaluator_sanitized_runtime_ledger_compiler_test_source",
        "evaluator_sanitized_runtime_ledger_compiler_input_schema",
        "evaluator_sanitized_runtime_ledger_compiler_output_schema",
        "evaluator_sanitized_runtime_ledger_assignment_proof_schema",
        "evaluator_sanitized_runtime_ledger_replay_verifier_tool",
        "evaluator_sanitized_runtime_ledger_replay_verifier_test_source",
        "evaluator_sanitized_runtime_ledger_replay_verifier_output_schema",
        "role_manifest_set_schema",
        "protocol_validator_test_source",
        "producer_replay_verifier_tool",
        "producer_replay_verifier_test_source",
        "primary_case_gate_evaluator_tool",
        "primary_case_gate_evaluator_test_source",
        "primary_case_gate_evaluator_runtime_integration_test_source",
        "primary_case_gate_evaluator_input_schema",
        "primary_case_gate_evaluation_output_schema",
        "primary_case_report_candidate_schema",
        "primary_case_gate_evidence_compiler_tool",
        "primary_case_gate_evidence_compiler_test_source",
        "primary_runtime_replay_executor_tool",
        "primary_runtime_replay_executor_test_source",
        "primary_runtime_replay_input_manifest_schema",
        "primary_runtime_output_schema",
        "primary_runtime_replay_seal_schema",
        "search_snapshot_schema",
        "event_ledger_replay_tool",
        "event_ledger_replay_test_source",
        "structural_gate_harness_tool",
        "structural_gate_harness_test_source",
        "structural_gate_evidence_schema",
        "structural_gate_results_schema",
    }
    if (
        not isinstance(required_bindings, list)
        or len(required_bindings) != len(set(required_bindings))
        or not required_binding_names.issubset(set(required_bindings))
    ):
        _fail("execution protocol required_preprimary_bindings omit a selection-chain asset")
    selection = _require_mapping(protocol.get("selection"), "selection protocol")
    queries = selection.get("queries")
    if (
        not isinstance(queries, list)
        or [row.get("query_id") for row in queries if isinstance(row, Mapping)] != ["Q1", "Q2"]
        or selection.get("minimum_eligible_candidates") != 3
        or selection.get("manual_skip_or_substitution_forbidden") is not True
        or selection.get("selection_hash_excludes_executor_metadata") is not True
        or selection.get("selection_digest_preimage")
        != (
            "NCF-PRIMARY-SELECTION-v1 + newline + frozen_query_contract_sha256 + "
            "newline + raw_ordered_identifier_projection_sha256 + newline + "
            "canonical_eligible_id_set_sha256 + newline + canonical_case_id"
        )
    ):
        _fail("execution protocol does not freeze deterministic Q1/Q2 selection")
    eligibility = _require_mapping(selection.get("eligibility"), "selection eligibility")
    if eligibility.get("minimum_concurrent_process_target_candidates") != 2:
        _fail("selection eligibility must require two concurrent process targets")
    complexity = _require_mapping(
        selection.get("opaque_concurrent_process_candidate_contract"),
        "opaque concurrent-process candidate contract",
    )
    expected_complexity = {
        "minimum_required_target_count": 2,
        "model_blind": True,
        "disease_name_blind": True,
        "same_preterminal_epoch_coactivity_required": True,
        "independent_source_assertion_per_target_required": True,
        "minimum_temporally_separated_source_witnesses_per_target": 2,
        "trackable_trajectory_per_target_required": True,
        "duplicate_observations_of_same_process_count_once": True,
        "claims_schema": REL_COMPLEXITY_CLAIMS_SCHEMA.as_posix(),
        "packet_schema": REL_COMPLEXITY_PACKET_SCHEMA.as_posix(),
        "sealed_packet_schema": REL_SEALED_COMPLEXITY_PACKET_SCHEMA.as_posix(),
        "compiler_validator": REL_COMPLEXITY_COMPILER.as_posix(),
        "test_source": REL_COMPLEXITY_COMPILER_TEST.as_posix(),
        "raw_data_class": "opaque_concurrent_process_candidate_packet",
        "sealed_data_class": "sealed_opaque_concurrent_process_candidate_packet",
        "evaluator_access": "FORBIDDEN",
        "disallowed_compiler_inputs": [
            "model_pack",
            "runtime",
            "runtime_output",
            "oracle_contents",
            "expected_diagnosis",
            "terminal_outcome",
            "scoring_output",
        ],
        "insufficient_target_count_effect": "CASE_INELIGIBLE",
    }
    if dict(complexity) != expected_complexity:
        _fail("opaque concurrent-process candidate contract mismatch")
    raw_search = _require_mapping(
        selection.get("raw_search_validation"), "raw search validation contract"
    )
    expected_raw_search = {
        "raw_response_schema": REL_RAW_SEARCH_RESPONSE_SCHEMA.as_posix(),
        "retrieval_manifest_schema": REL_RAW_SEARCH_RETRIEVAL_SCHEMA.as_posix(),
        "snapshot_schema": REL_SEARCH_SNAPSHOT_SCHEMA.as_posix(),
        "executable": REL_RAW_SEARCH_VALIDATOR.as_posix(),
        "test_source": REL_RAW_SEARCH_VALIDATOR_TEST.as_posix(),
        "compiler": REL_RAW_SEARCH_COMPILER.as_posix(),
        "compiler_test_source": REL_RAW_SEARCH_COMPILER_TEST.as_posix(),
        "compiler_network_access": False,
        "provider": "NCBI_PUBMED_ESEARCH_JSON",
        "raw_path_prefix": "holdout/evidence/primary_search_raw/",
        "raw_payload_path_prefix": "holdout/evidence/primary_search_raw/payloads/",
        "request_url_policy": "canonical HTTPS NCBI ESearch URL; fixed parameter order; RFC3986 percent-encoding",
        "retrieved_count_must_equal_idlist_length": True,
        "ordered_case_ids_projection": "PMID:<idlist item>, exact source order",
        "raw_hash_mismatch_or_incomplete_page_verdict": "HARNESS_INCOMPLETE",
    }
    for key, expected in expected_raw_search.items():
        if raw_search.get(key) != expected:
            _fail(f"raw search validation contract mismatch: {key}")
    source = _require_mapping(protocol.get("source_contract"), "source contract")
    if source.get("nonmention_semantics") != "UNKNOWN_NEVER_NEGATIVE":
        _fail("execution protocol must state nonmention is unknown, never negative")
    availability = _require_mapping(protocol.get("availability_contract"), "availability contract")
    for key in (
        "publication_order_is_not_clinical_availability",
        "exact_clock_only_if_reported",
        "preserve_intervals_and_partial_order",
        "same_reported_batch_same_cut",
        "forbid_single_event_microcuts_for_artificial_resolution",
    ):
        if availability.get(key) is not True:
            _fail(f"execution availability invariant missing: {key}")
    compiler = _require_mapping(availability.get("compiler"), "availability compiler contract")
    expected_compiler = {
        "executable": REL_AVAILABILITY_COMPILER.as_posix(),
        "input_schema": REL_AVAILABILITY_SCHEMA.as_posix(),
        "test_source": REL_AVAILABILITY_COMPILER_TEST.as_posix(),
        "interval_release": "latest_possible_epoch",
        "unknown_or_unbounded_partial_order": "WITHHOLD_TO_MEASUREMENT_UNCERTAINTY",
    }
    for key, expected in expected_compiler.items():
        if compiler.get(key) != expected:
            _fail(f"availability compiler contract mismatch: {key}")
    primary_execution_assets = _require_mapping(
        protocol.get("primary_execution_asset_contract"),
        "primary execution asset contract",
    )
    if set(primary_execution_assets) != {
        "event_ledger_replay",
        "structural_gate_harness",
        "producer_replay_verifier",
        "primary_case_gate_evaluator",
        "primary_case_gate_evidence_compiler",
        "primary_runtime_replay_executor",
        "opaque_concurrent_process_candidate_compiler",
        "evaluator_sanitized_runtime_ledger_compiler",
        "evaluator_sanitized_runtime_ledger_replay_verifier",
        "preprimary_binding_scope",
        "generated_primary_results_bound_preprimary",
    }:
        _fail("primary execution asset contract keys mismatch")
    event_replay = _require_mapping(
        primary_execution_assets.get("event_ledger_replay"),
        "event-ledger replay asset contract",
    )
    expected_event_replay = {
        "executable": REL_EVENT_LEDGER_REPLAY.as_posix(),
        "test_source": REL_EVENT_LEDGER_REPLAY_TEST.as_posix(),
    }
    if set(event_replay) != set(expected_event_replay):
        _fail("event-ledger replay asset contract keys mismatch")
    for key, expected in expected_event_replay.items():
        if event_replay.get(key) != expected:
            _fail(f"event-ledger replay asset contract mismatch: {key}")
    structural_harness = _require_mapping(
        primary_execution_assets.get("structural_gate_harness"),
        "structural-gate harness asset contract",
    )
    expected_structural_harness = {
        "executable": REL_STRUCTURAL_GATE_HARNESS.as_posix(),
        "test_source": REL_STRUCTURAL_GATE_HARNESS_TEST.as_posix(),
        "evidence_schema": REL_STRUCTURAL_GATE_EVIDENCE_SCHEMA.as_posix(),
        "results_schema": REL_STRUCTURAL_GATE_RESULTS_SCHEMA.as_posix(),
    }
    if set(structural_harness) != set(expected_structural_harness):
        _fail("structural-gate harness asset contract keys mismatch")
    for key, expected in expected_structural_harness.items():
        if structural_harness.get(key) != expected:
            _fail(f"structural-gate harness asset contract mismatch: {key}")
    replay_verifier = _require_mapping(
        primary_execution_assets.get("producer_replay_verifier"),
        "producer replay verifier asset contract",
    )
    expected_replay_verifier = {
        "executable": REL_PRODUCER_REPLAY_VERIFIER.as_posix(),
        "test_source": REL_PRODUCER_REPLAY_VERIFIER_TEST.as_posix(),
    }
    if dict(replay_verifier) != expected_replay_verifier:
        _fail("producer replay verifier asset contract mismatch")
    case_gate_evaluator = _require_mapping(
        primary_execution_assets.get("primary_case_gate_evaluator"),
        "primary case gate evaluator asset contract",
    )
    expected_case_gate_evaluator = {
        "executable": REL_PRIMARY_CASE_GATE_EVALUATOR.as_posix(),
        "test_source": REL_PRIMARY_CASE_GATE_EVALUATOR_TEST.as_posix(),
        "runtime_integration_test_source": (
            REL_PRIMARY_CASE_GATE_EVALUATOR_RUNTIME_TEST.as_posix()
        ),
        "input_schema": REL_PRIMARY_CASE_GATE_EVALUATOR_INPUT_SCHEMA.as_posix(),
        "output_schema": REL_PRIMARY_CASE_GATE_EVALUATION_SCHEMA.as_posix(),
        "report_candidate_schema": REL_PRIMARY_REPORT_CANDIDATE_SCHEMA.as_posix(),
    }
    if dict(case_gate_evaluator) != expected_case_gate_evaluator:
        _fail("primary case gate evaluator asset contract mismatch")
    gate_evidence_compiler = _require_mapping(
        primary_execution_assets.get("primary_case_gate_evidence_compiler"),
        "primary case gate evidence compiler asset contract",
    )
    expected_gate_evidence_compiler = {
        "executable": REL_PRIMARY_GATE_EVIDENCE_COMPILER.as_posix(),
        "test_source": REL_PRIMARY_GATE_EVIDENCE_COMPILER_TEST.as_posix(),
        "output_schema": REL_GATE_EVIDENCE_SCHEMA.as_posix(),
    }
    if dict(gate_evidence_compiler) != expected_gate_evidence_compiler:
        _fail("primary case gate evidence compiler asset contract mismatch")
    runtime_replay_executor = _require_mapping(
        primary_execution_assets.get("primary_runtime_replay_executor"),
        "primary runtime replay executor asset contract",
    )
    expected_runtime_replay_executor = {
        "executable": REL_PRIMARY_RUNTIME_REPLAY_EXECUTOR.as_posix(),
        "test_source": REL_PRIMARY_RUNTIME_REPLAY_EXECUTOR_TEST.as_posix(),
        "input_manifest_schema": REL_PRIMARY_RUNTIME_REPLAY_INPUT_SCHEMA.as_posix(),
        "runtime_output_schema": REL_PRIMARY_RUNTIME_OUTPUT_SCHEMA.as_posix(),
        "replay_seal_schema": REL_PRIMARY_RUNTIME_REPLAY_SEAL_SCHEMA.as_posix(),
        "mapped_observation_consumption_schema": REL_MAPPED_OBSERVATION_SCHEMA.as_posix(),
        "input_data_classes": [
            "evaluator_sanitized_runtime_ledger",
            "sealed_concept_map",
            "model_pack",
            "runtime",
            "scoring_contract",
            "protocol",
            "combined_preprimary_seal",
            "oracle_seal_hash_only",
            "sanitized_id_type_unit_registry",
        ],
        "role_manifest_and_dag_validation": "EXTERNAL_NOT_EXECUTOR_INPUT",
        "execution_role": "evaluator",
    }
    if dict(runtime_replay_executor) != expected_runtime_replay_executor:
        _fail("primary runtime replay executor asset contract mismatch")
    complexity_compiler = _require_mapping(
        primary_execution_assets.get("opaque_concurrent_process_candidate_compiler"),
        "opaque concurrent-process candidate compiler asset contract",
    )
    expected_complexity_compiler = {
        "executable": REL_COMPLEXITY_COMPILER.as_posix(),
        "test_source": REL_COMPLEXITY_COMPILER_TEST.as_posix(),
        "claims_schema": REL_COMPLEXITY_CLAIMS_SCHEMA.as_posix(),
        "packet_schema": REL_COMPLEXITY_PACKET_SCHEMA.as_posix(),
        "sealed_packet_schema": REL_SEALED_COMPLEXITY_PACKET_SCHEMA.as_posix(),
    }
    if dict(complexity_compiler) != expected_complexity_compiler:
        _fail("opaque concurrent-process candidate compiler asset contract mismatch")
    sanitized_ledger_compiler = _require_mapping(
        primary_execution_assets.get("evaluator_sanitized_runtime_ledger_compiler"),
        "evaluator sanitized runtime ledger compiler asset contract",
    )
    expected_sanitized_ledger_compiler = {
        "producer_id": "evaluator-sanitized-runtime-ledger-compiler-v1",
        "executable": REL_SANITIZED_LEDGER_COMPILER.as_posix(),
        "test_source": REL_SANITIZED_LEDGER_COMPILER_TEST.as_posix(),
        "input_schema": REL_SANITIZED_LEDGER_COMPILER_INPUT_SCHEMA.as_posix(),
        "output_schema": REL_SANITIZED_RUNTIME_LEDGER_SCHEMA.as_posix(),
        "assignment_proof_schema": REL_SANITIZED_LEDGER_ASSIGNMENT_PROOF_SCHEMA.as_posix(),
        "execution_scope": "EXTERNAL_AFTER_ROLE_DAG_CONCEPT_MAP_SEAL_BEFORE_EVALUATOR",
        "input_data_classes": [
            "sealed_event_ledger",
            "sealed_availability_ledger",
            "sealed_concept_map",
            "sanitized_id_type_unit_registry",
            "combined_preprimary_seal",
        ],
        "output_data_classes": [
            "evaluator_sanitized_runtime_ledger",
            "evaluator_sanitized_runtime_ledger_assignment_proof",
        ],
        "transport_id_assignment": {
            "opaque_run_id": "RUN_PREFIX_PLUS_FULL_COMBINED_PREPRIMARY_PAYLOAD_SHA256",
            "opaque_event_id": "CANONICAL_LEDGER_ROW_ORDER_DECIMAL8_START1",
            "opaque_source_concept_token": "CANONICAL_LEDGER_FIRST_OCCURRENCE_DECIMAL8_START1",
            "opaque_action_id": "CANONICAL_LEDGER_FIRST_OCCURRENCE_DECIMAL8_START1",
            "alternative_representation_group_id": "CANONICAL_LEDGER_FIRST_OCCURRENCE_DECIMAL8_START1",
        },
        "gate_minting": "FORBIDDEN_UPSTREAM_ARTIFACT_PRODUCER_ONLY",
    }
    if dict(sanitized_ledger_compiler) != expected_sanitized_ledger_compiler:
        _fail("evaluator sanitized runtime ledger compiler asset contract mismatch")
    sanitized_ledger_replay_verifier = _require_mapping(
        primary_execution_assets.get("evaluator_sanitized_runtime_ledger_replay_verifier"),
        "evaluator sanitized runtime ledger replay verifier asset contract",
    )
    expected_sanitized_ledger_replay_verifier = {
        "executable": REL_SANITIZED_LEDGER_REPLAY_VERIFIER.as_posix(),
        "test_source": REL_SANITIZED_LEDGER_REPLAY_VERIFIER_TEST.as_posix(),
        "output_schema": REL_SANITIZED_LEDGER_REPLAY_VERIFICATION_SCHEMA.as_posix(),
    }
    if dict(sanitized_ledger_replay_verifier) != expected_sanitized_ledger_replay_verifier:
        _fail("evaluator sanitized runtime ledger replay verifier asset contract mismatch")
    if (
        primary_execution_assets.get("preprimary_binding_scope")
        != "generator_source_tests_and_output_schemas_only"
        or primary_execution_assets.get("generated_primary_results_bound_preprimary") is not False
    ):
        _fail("primary execution binding must exclude generated primary results")
    oracle = _require_mapping(protocol.get("oracle"), "oracle contract")
    if (
        oracle.get("must_be_sealed_before_first_runtime_output") is not True
        or oracle.get("evaluator_may_receive_only_oracle_hash") is not True
    ):
        _fail("oracle must be sealed and hidden from evaluator before output")

    if scoring.get("status") != "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION":
        _fail("scoring contract is not frozen before case search/selection")
    if scoring.get("architecture_version") != ARCHITECTURE_VERSION:
        _fail("scoring architecture version mismatch")
    if scoring.get("gate_contract_version") != GATE_CONTRACT_VERSION:
        _fail("scoring gate binding mismatch")
    expected_identifiability = [
        "IDENTIFIED_WITHIN_SCOPE",
        "PARTIALLY_IDENTIFIED",
        "UNIDENTIFIABLE",
        "OUT_OF_SCOPE",
    ]
    action = _require_mapping(scoring.get("action_counterfactual"), "scoring action contract")
    if action.get("permitted_statuses") != expected_identifiability:
        _fail("scoring identifiability enum must match frozen architecture wire")
    final_scorer = _require_mapping(scoring.get("final_scorer_contract"), "final scorer contract")
    expected_final_scorer = {
        "executable": REL_FINAL_SCORER.as_posix(),
        "result_schema": REL_FINAL_RESULT_SCHEMA.as_posix(),
        "test_source": REL_FINAL_SCORER_TEST.as_posix(),
        "required_gate_count": 30,
        "missing_duplicate_unknown_or_malformed_gate_verdict": "HARNESS_INCOMPLETE",
        "all_gate_evidence_complete_with_any_hard_gate_fail_verdict": "FAILED",
        "complex_case_coverage_missing_or_malformed_verdict": "HARNESS_INCOMPLETE",
        "complex_case_coverage_complete_with_any_failure_verdict": "FAILED",
        "correct_diagnosis_override_forbidden": True,
        "evidence_schema": REL_GATE_EVIDENCE_SCHEMA.as_posix(),
        "evidence_refs_are_content_addressed_objects": True,
        "evidence_file_must_exist_under_study_root": True,
        "evidence_sha256_must_match": True,
        "evidence_subject_kind_and_id_must_match_row": True,
        "evidence_claimed_result_must_match_row": True,
        "evidence_ref_requires_sha256_and_bytes": True,
        "source_artifact_refs_are_content_addressed": True,
        "producer_tool_ref_must_match_exact_combined_seal_artifact": True,
        "deterministic_assertions_require_source_json_pointer_observed_expected_operator": True,
        "bare_passed_boolean_forbidden": True,
        "pass_requires_all_deterministic_operator_checks_true": True,
        "fail_requires_at_least_one_deterministic_operator_check_false": True,
        "unautomated_positive_gate_verdict": "HARNESS_INCOMPLETE",
    }
    for key, expected in expected_final_scorer.items():
        if final_scorer.get(key) != expected:
            _fail(f"final scorer contract mismatch: {key}")
    producer_policy = _require_mapping(
        final_scorer.get("evidence_producer_policy"),
        "final scorer evidence producer policy",
    )
    automated = producer_policy.get("sealed_automated_generators")
    expected_producers = json.loads('{"event-ledger-fresh-replay-v1":{"allowed_subjects":{"COMPLEX_COVERAGE":["recursive_updates"],"GATE":["PL-LED-002"]},"artifact_produced_by_required":false,"artifact_schema_versions":["ncf.holdout.fresh-process-replay-report.v1"],"assertion_contract":{"mode":"SUBJECT_EXACT_POINTERS_V1","schema_version":"ncf.producer-assertion-contract.v1","subject_assertions":{"COMPLEX_COVERAGE":{"recursive_updates":[{"expected":"PASS","json_pointer":"/status","operator":"EQ"},{"expected":true,"json_pointer":"/recursive_fresh_process_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/cold_prefix_replay_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/cold_full_history_replay_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/deterministic_event_order_validated","operator":"EQ"},{"expected":true,"json_pointer":"/available_time_boundary_validated","operator":"EQ"}]},"GATE":{"PL-LED-002":[{"expected":"PASS","json_pointer":"/status","operator":"EQ"},{"expected":true,"json_pointer":"/recursive_fresh_process_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/cold_prefix_replay_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/cold_full_history_replay_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/deterministic_event_order_validated","operator":"EQ"},{"expected":true,"json_pointer":"/available_time_boundary_validated","operator":"EQ"}]}}},"replay_contract":{"adapter_id":"CONFIGURED_CLI_EXACT_JSON_V1","argv_template":["verify","--bundle","{input:bundle}","--model","{input:model}","--report","{output}"],"check_arg_contract":{},"comparison":"EXACT_BYTES_AND_CANONICAL_JSON","network_policy":"APPLICATION_SOCKET_GUARD_OFFLINE","output_contract":{"json_schema_versions":["ncf.holdout.fresh-process-replay-report.v1"],"mode":"SINGLE_FILE"},"required_input_slots":{"bundle":{"json_schema_versions":["ncf.holdout.event-ledger-replay-bundle.v1"]},"model":{"json_schema_versions":["new-clinical-runtime.model.v2.0"]}},"schema_version":"ncf.producer-replay-policy.v1","timeout_seconds":300,"working_directory":"STUDY_ROOT"},"tool_path":"holdout/tools/event_ledger_replay.py"},"primary-case-gate-evaluator-case-v1":{"allowed_subjects":{"COMPLEX_COVERAGE":["at_least_two_local_domains","concurrent_process_target_from_oracle","delayed_information","reliable_negative_evidence","performed_action_lifecycle_with_response","prospective_pre_next_cut_forecasts"],"GATE":["PL-BLIND-001","PL-LED-001","PL-DX-002","PL-PRED-002","PL-CASE-001"]},"artifact_produced_by_required":true,"artifact_schema_versions":["ncf.primary-case-gate-evaluation.v1"],"assertion_contract":{"check_expected_field":"expected","check_id_field":"check_id","check_observed_field":"observed","check_operator_field":"operator","check_pass_field":"passed","checks_field":"checks","mode":"SUBJECT_RESULT_ROW_EXHAUSTIVE_CHECKS_V1","result_array_json_pointers":{"COMPLEX_COVERAGE":"/coverage_results","GATE":"/gate_results"},"result_field":"computed_result","schema_version":"ncf.producer-assertion-contract.v1","subject_id_field":"subject_id","subject_kind_field":"subject_kind"},"replay_contract":{"adapter_id":"CONFIGURED_CLI_EXACT_JSON_V1","argv_template":["{check:subcommand}","--manifest","{input:input_manifest}","--output","{output}"],"check_arg_contract":{"subcommand":{"allowed_values":["evaluate-case"],"source":"SEALED_ENUM"}},"comparison":"EXACT_BYTES_AND_CANONICAL_JSON","network_policy":"APPLICATION_SOCKET_GUARD_OFFLINE","output_contract":{"json_schema_versions":["ncf.primary-case-gate-evaluation.v1"],"mode":"SINGLE_FILE"},"required_input_slots":{"input_manifest":{"json_schema_versions":["ncf.primary-case-gate-evaluator-input.v1"]}},"schema_version":"ncf.producer-replay-policy.v1","timeout_seconds":300,"working_directory":"STUDY_ROOT"},"tool_path":"holdout/tools/primary_case_gate_evaluator.py"},"primary-case-gate-evaluator-report-v1":{"allowed_subjects":{"COMPLEX_COVERAGE":[],"GATE":["PL-REPORT-001"]},"artifact_produced_by_required":true,"artifact_schema_versions":["ncf.primary-case-gate-evaluation.v1"],"assertion_contract":{"check_expected_field":"expected","check_id_field":"check_id","check_observed_field":"observed","check_operator_field":"operator","check_pass_field":"passed","checks_field":"checks","mode":"SUBJECT_RESULT_ROW_EXHAUSTIVE_CHECKS_V1","result_array_json_pointers":{"COMPLEX_COVERAGE":"/coverage_results","GATE":"/gate_results"},"result_field":"computed_result","schema_version":"ncf.producer-assertion-contract.v1","subject_id_field":"subject_id","subject_kind_field":"subject_kind"},"replay_contract":{"adapter_id":"CONFIGURED_CLI_EXACT_JSON_V1","argv_template":["{check:subcommand}","--manifest","{input:input_manifest}","--output","{output}"],"check_arg_contract":{"subcommand":{"allowed_values":["evaluate-report"],"source":"SEALED_ENUM"}},"comparison":"EXACT_BYTES_AND_CANONICAL_JSON","network_policy":"APPLICATION_SOCKET_GUARD_OFFLINE","output_contract":{"json_schema_versions":["ncf.primary-case-gate-evaluation.v1"],"mode":"SINGLE_FILE"},"required_input_slots":{"input_manifest":{"json_schema_versions":["ncf.primary-case-gate-evaluator-input.v1"]}},"schema_version":"ncf.producer-replay-policy.v1","timeout_seconds":300,"working_directory":"STUDY_ROOT"},"tool_path":"holdout/tools/primary_case_gate_evaluator.py"},"structural-gate-harness-v1":{"allowed_subjects":{"COMPLEX_COVERAGE":[],"GATE":["PL-IND-001","PL-LED-002","PL-STATE-001","PL-STATE-002","PL-TIME-001","PL-TIME-002","PL-FACT-001","PL-FACT-002","PL-CONC-001","PL-CONC-002","PL-MODE-001","PL-MODE-002","PL-SUPPORT-001","PL-GEOM-001","PL-DX-001","PL-PRED-001","PL-ACT-001","PL-ACT-002","PL-OOD-001","PL-OOD-002","PL-REF-001","PL-REF-002","PL-REF-003","PL-REF-004"]},"artifact_produced_by_required":true,"artifact_schema_versions":["ncf.structural-gate-results.v1"],"assertion_contract":{"mode":"SUBJECT_RESULT_ROW_EXACT_V1","result_array_json_pointers":{"GATE":"/gate_results"},"result_field":"result","schema_version":"ncf.producer-assertion-contract.v1","subject_id_field":"gate_id","subject_kind_field":null},"replay_contract":{"adapter_id":"CONFIGURED_CLI_EXACT_JSON_V1","argv_template":["--output","{output_dir}","--generated-at","{check:generated_at}"],"check_arg_contract":{"generated_at":{"json_pointer":"/generated_at","pattern":"^\\\\d{4}-\\\\d{2}-\\\\d{2}T\\\\d{2}:\\\\d{2}:\\\\d{2}Z$","source":"OUTPUT_JSON_POINTER"}},"comparison":"EXACT_BYTES_AND_CANONICAL_JSON","network_policy":"APPLICATION_SOCKET_GUARD_OFFLINE","output_contract":{"artifact_relative_path":"structural_gate_results.json","json_schema_versions":["ncf.structural-gate-results.v1"],"manifest_json_pointer":"/evidence_manifest","manifest_path_field":"path","mode":"DIRECTORY_MANIFEST"},"required_input_slots":{},"schema_version":"ncf.producer-replay-policy.v1","timeout_seconds":300,"working_directory":"STUDY_ROOT"},"tool_path":"holdout/tools/structural_gate_harness.py"}}')
    if not isinstance(automated, list) or len(automated) != len(expected_producers):
        _fail("final scorer must freeze exactly the current automated evidence producer allowlist")
    automated_by_id = {
        row.get("producer_id"): row for row in automated if isinstance(row, Mapping)
    }
    if set(automated_by_id) != set(expected_producers):
        _fail("final scorer automated evidence producer ids mismatch")
    for producer_id, expected in expected_producers.items():
        row = _require_mapping(automated_by_id[producer_id], f"producer {producer_id}")
        if set(row) != {"producer_id", *expected}:
            _fail(f"final scorer producer keys mismatch: {producer_id}")
        for key, value in expected.items():
            if row.get(key) != value:
                _fail(f"final scorer producer contract mismatch: {producer_id}.{key}")
    manual = _require_mapping(
        producer_policy.get("manual_independent_auditor"),
        "manual independent auditor policy",
    )
    expected_manual = {
        "policy_id": "NCF-MANUAL-INDEPENDENT-AUDITOR-FAILURE-ONLY-1.0.0",
        "required_role": "scorer_auditor",
        "required_role_manifest_schema_version": "NCF-PRIMARY-ROLE-MANIFEST-1.1.0",
        "required_audit_output_data_class": "audit_report",
        "pass_permitted": False,
        "fail_permitted": True,
        "unautomated_positive_result": "HARNESS_INCOMPLETE",
    }
    if dict(manual) != expected_manual:
        _fail("manual independent auditor policy must remain failure-only")
    representation = _require_mapping(scoring.get("representation"), "scoring representation")
    if representation.get("nonmention_as_negative_tolerance") != 0:
        _fail("scoring must tolerate zero nonmention-as-negative errors")
    if representation.get("invented_availability_time_tolerance") != 0:
        _fail("scoring must tolerate zero invented availability times")

    for rel, expected_id, label in (
        (REL_ROLE_MANIFEST_SCHEMA, "ncf.primary-role-execution-manifest.v1.1", "role manifest schema"),
        (REL_ROLE_MANIFEST_SET_SCHEMA, "ncf.primary-role-manifest-set.v1", "role manifest set schema"),
        (
            REL_ROLE_TOOL_ACCESS_TRACE_SCHEMA,
            "ncf.primary-role-tool-access-trace.v1",
            "role tool access trace schema",
        ),
        (
            REL_SANITIZED_RUNTIME_LEDGER_SCHEMA,
            "ncf.evaluator-sanitized-runtime-ledger.v1",
            "evaluator sanitized runtime ledger schema",
        ),
        (
            REL_SANITIZED_LEDGER_COMPILER_INPUT_SCHEMA,
            "ncf.evaluator-sanitized-runtime-ledger-compiler-input.v1",
            "evaluator sanitized runtime ledger compiler input schema",
        ),
        (
            REL_SANITIZED_LEDGER_ASSIGNMENT_PROOF_SCHEMA,
            "ncf.evaluator-sanitized-runtime-ledger-assignment-proof.v1",
            "evaluator sanitized runtime ledger assignment proof schema",
        ),
        (
            REL_SANITIZED_LEDGER_REPLAY_VERIFICATION_SCHEMA,
            "ncf.evaluator-sanitized-runtime-ledger-replay-verification.v1",
            "evaluator sanitized runtime ledger replay verification schema",
        ),
        (
            REL_ALL_SEALED_REPLAY_SCHEMA,
            "ncf.data.all-sealed-artifacts-after-replay.v1",
            "all-sealed-after-replay schema",
        ),
        (
            REL_SEALED_CONCEPT_MAP_SCHEMA,
            "ncf.data.sealed-concept-map.v1",
            "sealed concept map schema",
        ),
        (REL_SEARCH_SNAPSHOT_SCHEMA, "ncf.primary-case-search-snapshot.v1", "search snapshot schema"),
        (REL_RAW_SEARCH_RESPONSE_SCHEMA, "ncf.primary-raw-search-response.v1", "raw search response schema"),
        (REL_RAW_SEARCH_RETRIEVAL_SCHEMA, "ncf.primary-search-retrieval-manifest.v1", "raw search retrieval manifest schema"),
        (REL_SCREENING_SCHEMA, "ncf.primary-case-screening.v1", "screening schema"),
        (REL_SCREENING_EVIDENCE_SCHEMA, "ncf.primary-screening-evidence.v1", "screening evidence schema"),
        (REL_MAPPED_OBSERVATION_SCHEMA, "ncf.mapped-observation-consumption.v1", "mapped observation consumption schema"),
        (REL_FINAL_RESULT_SCHEMA, "ncf.primary-holdout-final-result.v1", "final result schema"),
        (REL_GATE_EVIDENCE_SCHEMA, "ncf.primary-gate-evidence.v3", "gate evidence schema"),
        (REL_AVAILABILITY_SCHEMA, "ncf.primary-availability-ledger.v1", "availability ledger schema"),
        (REL_STRUCTURAL_GATE_EVIDENCE_SCHEMA, "ncf.structural-gate-evidence.v1", "structural gate evidence schema"),
        (REL_STRUCTURAL_GATE_RESULTS_SCHEMA, "ncf.structural-gate-results.v1", "structural gate results schema"),
    ):
        value = _require_mapping(_load_json(study_root, rel), label)
        if value.get("$id") != expected_id:
            _fail(f"{label} id mismatch")
    # Hash binding alone would happily seal a weakened role contract.  Reuse
    # the frozen semantic validator so deleted roles, asymmetric I/O policy or
    # an id-only schema fail before a combined seal can be produced.
    try:
        from validate_primary_holdout_protocol import (
            _validate_all_sealed_replay_schema_structure,
            _validate_role_policy_contract,
            _validate_sanitized_runtime_schema_structure,
            _validate_sealed_concept_map_schema_structure,
        )
    except ImportError as exc:  # pragma: no cover - fail-closed deployment guard
        _fail(f"cannot import role policy validator: {exc}")
    try:
        _validate_role_policy_contract(
            protocol,
            _require_mapping(_load_json(study_root, REL_ROLE_MANIFEST_SCHEMA), "role manifest schema"),
            _require_mapping(_load_json(study_root, REL_ROLE_MANIFEST_SET_SCHEMA), "role manifest set schema"),
            _require_mapping(
                _load_json(study_root, REL_ROLE_TOOL_ACCESS_TRACE_SCHEMA),
                "role tool access trace schema",
            ),
        )
        _validate_sanitized_runtime_schema_structure(
            _require_mapping(
                _load_json(study_root, REL_SANITIZED_RUNTIME_LEDGER_SCHEMA),
                "evaluator sanitized runtime ledger schema",
            )
        )
        _validate_all_sealed_replay_schema_structure(
            _require_mapping(
                _load_json(study_root, REL_ALL_SEALED_REPLAY_SCHEMA),
                "all-sealed-after-replay schema",
            )
        )
        _validate_sealed_concept_map_schema_structure(
            _require_mapping(
                _load_json(study_root, REL_SEALED_CONCEPT_MAP_SCHEMA),
                "sealed concept map schema",
            ),
            _require_mapping(
                _load_json(study_root, REL_MAPPER_SANITIZED_REGISTRY),
                "sanitized id/type/unit registry",
            ),
        )
    except Exception as exc:
        _fail(f"role policy/schema semantic validation failed: {exc}")
    return artifacts


def _validate_exclusions(study_root: Path) -> tuple[Artifact, int]:
    artifact = _artifact(study_root, REL_EXCLUSIONS)
    value = _require_mapping(_load_json(study_root, REL_EXCLUSIONS), "exclusion list")
    allowed_keys = {"schema_version", "exclusion_set_id", "excluded_case_ids"}
    if set(value) != allowed_keys:
        _fail(
            "exclusion list must be identifier-only and contain exactly "
            "schema_version, exclusion_set_id, excluded_case_ids"
        )
    if value.get("schema_version") != "NCF-PRIMARY-HOLDOUT-EXCLUSIONS-1.0.0":
        _fail("exclusion list schema_version mismatch")
    if not isinstance(value.get("exclusion_set_id"), str) or not value["exclusion_set_id"]:
        _fail("exclusion_set_id missing")
    ids = value.get("excluded_case_ids")
    if not isinstance(ids, list) or not ids:
        _fail("excluded_case_ids must be a non-empty list")
    if any(not isinstance(item, str) or not SAFE_EXCLUSION_ID.fullmatch(item) for item in ids):
        _fail("excluded_case_ids contain an unsafe or narrative-like value")
    if len(set(ids)) != len(ids):
        _fail("excluded_case_ids must be unique")
    return artifact, len(ids)


def _base_artifacts(study_root: Path) -> tuple[Artifact, Artifact]:
    arch = _artifact(study_root, REL_ARCH_DOC)
    arch_schema = _artifact(study_root, REL_ARCH_SCHEMA)
    _validate_architecture_schema(study_root)
    _validate_gate_contract(study_root, arch, arch_schema)
    return arch, arch_schema


def build_payload(study_root: Path, sealed_at: str | None = None) -> dict[str, Any]:
    """Construct the combined payload after all fail-closed checks pass."""

    study_root = study_root.resolve(strict=True)
    arch, arch_schema = _base_artifacts(study_root)
    runtime_tree = _tree_files(study_root, REL_RUNTIME_ROOT)
    model_tree = _tree_files(study_root, REL_MODEL_ROOT)
    runtime_manifest, runtime_seal = _validate_runtime(study_root, runtime_tree)
    model_pack, model_validation, model_seal = _validate_generic_model(
        study_root,
        model_tree,
        runtime_manifest,
        runtime_seal,
    )
    execution_contracts = _validate_execution_contracts(study_root)
    exclusions, exclusion_count = _validate_exclusions(study_root)

    gate_json = _artifact(study_root, REL_GATES_JSON)
    gate_seal = _artifact(study_root, REL_GATES_SEAL)
    timestamp = sealed_at or datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    payload: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "seal_id": "NCF-PRE-PRIMARY-HOLDOUT-SEAL",
        "status": "SEALED_BEFORE_PRIMARY_CASE_SELECTION",
        "sealed_at": timestamp,
        "case_blindness": {
            "case_content_read_by_builder": False,
            "case_identity_selected": False,
            "allowed_read_surface": [
                "frozen architecture",
                "frozen gate contract",
                "case-blind runtime",
                "case-blind generic model",
                "case-blind execution and scoring contracts",
                "deterministic selection and role-isolation schemas/tools",
                "final 30-gate executable scorer, result schema, and scorer tests",
                "conservative availability compiler, schema, and tests",
                "primary execution generators, tests, and output schemas",
                "identifier-only exclusion list",
            ],
        },
        "bindings": {
            "architecture": {
                "version": ARCHITECTURE_VERSION,
                "document": arch.as_dict(),
                "wire_schema": arch_schema.as_dict(),
            },
            "gates": {
                "contract": gate_json.as_dict(),
                "component_seal": gate_seal.as_dict(),
            },
            "runtime": {
                "version": RUNTIME_VERSION,
                "manifest": runtime_manifest.as_dict(),
                "component_seal": runtime_seal.as_dict(),
                "recursive_source_tree": _tree_record(runtime_tree),
            },
            "generic_model": {
                "model_pack": model_pack.as_dict(),
                "validation": model_validation.as_dict(),
                "component_seal": model_seal.as_dict(),
                "recursive_source_tree": _tree_record(model_tree),
            },
            "primary_execution": {
                "protocol_version": EXECUTION_PROTOCOL_VERSION,
                **{key: value.as_dict() for key, value in execution_contracts.items()},
            },
            "primary_holdout_exclusions": {
                "artifact": exclusions.as_dict(),
                "identifier_count": exclusion_count,
                "identifiers_embedded_in_combined_seal": False,
            },
        },
        "invariants": {
            "all_component_statuses_final": True,
            "all_recursive_source_files_bound": True,
            "component_seals_reverified": True,
            "execution_and_scoring_frozen_before_case_search": True,
            "deterministic_selection_tool_bound": True,
            "role_isolation_contract_bound": True,
            "final_30_gate_scorer_and_schema_bound": True,
            "availability_compiler_and_schema_bound": True,
            "primary_execution_generators_tests_and_schemas_bound": True,
            "generated_primary_results_bound_preprimary": False,
            "primary_case_may_be_selected_only_after_this_seal": True,
        },
    }
    payload["payload_sha256"] = _sha256_bytes(_canonical_bytes(payload))
    return payload


def write_seal(study_root: Path, output: Path | None = None, sealed_at: str | None = None) -> Path:
    study_root = study_root.resolve(strict=True)
    canonical_output = _study_path(study_root, REL_OUTPUT)
    output_path = output.resolve(strict=False) if output is not None else canonical_output
    if output_path != canonical_output.resolve(strict=False):
        _fail(f"output path is fixed to {REL_OUTPUT.as_posix()}")
    if output_path.exists():
        _fail(f"refusing to overwrite existing seal: {REL_OUTPUT.as_posix()}")

    # No output or temporary file is created until every input passes.
    payload = build_payload(study_root, sealed_at=sealed_at)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp = output_path.with_suffix(output_path.suffix + ".tmp")
    if temp.exists():
        temp.unlink()
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, output_path)
    finally:
        if temp.exists():
            temp.unlink()
    return output_path


def _verify_embedded_artifact(study_root: Path, row: Any, label: str) -> None:
    obj = _require_mapping(row, label)
    rel_text = obj.get("path")
    if not isinstance(rel_text, str):
        _fail(f"{label}.path missing")
    rel = PurePosixPath(rel_text)
    actual = _artifact(study_root, rel)
    _assert_hash(obj.get("sha256"), actual.sha256, label)
    if obj.get("bytes") != actual.bytes:
        _fail(f"byte count mismatch for {label}")


def _verify_tree(study_root: Path, record: Any, root: PurePosixPath, label: str) -> None:
    obj = _require_mapping(record, label)
    fresh = _tree_record(_tree_files(study_root, root))
    if obj != fresh:
        _fail(f"recursive source tree mismatch: {label}")


def verify_seal(study_root: Path, seal_path: Path | None = None) -> dict[str, Any]:
    study_root = study_root.resolve(strict=True)
    canonical_seal = _study_path(study_root, REL_OUTPUT)
    path = seal_path.resolve(strict=True) if seal_path is not None else canonical_seal
    if path != canonical_seal.resolve(strict=False):
        _fail(f"seal path is fixed to {REL_OUTPUT.as_posix()}")
    if not path.is_file() or path.is_symlink():
        _fail("combined seal is missing or is a symlink")
    try:
        payload = _require_mapping(json.loads(path.read_text(encoding="utf-8")), "combined seal")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid combined seal JSON: {exc}")
    payload = dict(payload)
    expected_digest = payload.pop("payload_sha256", None)
    _assert_hash(expected_digest, _sha256_bytes(_canonical_bytes(payload)), "combined seal payload")
    if payload.get("format_version") != FORMAT_VERSION:
        _fail("combined seal format_version mismatch")
    if payload.get("status") != "SEALED_BEFORE_PRIMARY_CASE_SELECTION":
        _fail("combined seal status mismatch")

    bindings = _require_mapping(payload.get("bindings"), "bindings")
    arch = _require_mapping(bindings.get("architecture"), "architecture binding")
    gates = _require_mapping(bindings.get("gates"), "gates binding")
    runtime = _require_mapping(bindings.get("runtime"), "runtime binding")
    model = _require_mapping(bindings.get("generic_model"), "generic model binding")
    execution = _require_mapping(bindings.get("primary_execution"), "primary execution binding")
    exclusions = _require_mapping(bindings.get("primary_holdout_exclusions"), "exclusion binding")
    for row, label in (
        (arch.get("document"), "architecture document"),
        (arch.get("wire_schema"), "architecture schema"),
        (gates.get("contract"), "gate contract"),
        (gates.get("component_seal"), "gate component seal"),
        (runtime.get("manifest"), "runtime manifest"),
        (runtime.get("component_seal"), "runtime component seal"),
        (model.get("model_pack"), "generic model pack"),
        (model.get("validation"), "generic model validation"),
        (model.get("component_seal"), "generic model component seal"),
        (execution.get("protocol_md"), "execution protocol markdown"),
        (execution.get("protocol_json"), "execution protocol contract"),
        (execution.get("scoring_contract"), "primary scoring contract"),
        (execution.get("preprimary_seal_tool"), "pre-primary combined seal tool"),
        (execution.get("preprimary_seal_test"), "pre-primary combined seal test source"),
        (execution.get("selector_tool"), "deterministic selection tool"),
        (execution.get("selector_test"), "deterministic selector test source"),
        (execution.get("raw_search_validator"), "raw search snapshot validator"),
        (execution.get("raw_search_validator_test"), "raw search snapshot validator test source"),
        (execution.get("raw_search_compiler"), "raw search snapshot compiler"),
        (execution.get("raw_search_compiler_test"), "raw search snapshot compiler test source"),
        (execution.get("screening_validator"), "primary case screening validator"),
        (execution.get("screening_validator_test"), "primary case screening validator test source"),
        (execution.get("complexity_compiler"), "opaque concurrent-process candidate compiler"),
        (
            execution.get("complexity_compiler_test"),
            "opaque concurrent-process candidate compiler test source",
        ),
        (
            execution.get("evaluator_sanitized_runtime_ledger_compiler"),
            "evaluator sanitized runtime ledger compiler",
        ),
        (
            execution.get("evaluator_sanitized_runtime_ledger_compiler_test"),
            "evaluator sanitized runtime ledger compiler test source",
        ),
        (
            execution.get("evaluator_sanitized_runtime_ledger_compiler_input_schema"),
            "evaluator sanitized runtime ledger compiler input schema",
        ),
        (
            execution.get("evaluator_sanitized_runtime_ledger_compiler_output_schema"),
            "evaluator sanitized runtime ledger compiler output schema",
        ),
        (
            execution.get("evaluator_sanitized_runtime_ledger_assignment_proof_schema"),
            "evaluator sanitized runtime ledger assignment proof schema",
        ),
        (
            execution.get("evaluator_sanitized_runtime_ledger_replay_verifier"),
            "evaluator sanitized runtime ledger replay verifier",
        ),
        (
            execution.get("evaluator_sanitized_runtime_ledger_replay_verifier_test"),
            "evaluator sanitized runtime ledger replay verifier test source",
        ),
        (
            execution.get("evaluator_sanitized_runtime_ledger_replay_verifier_schema"),
            "evaluator sanitized runtime ledger replay verification schema",
        ),
        (execution.get("protocol_validator"), "primary protocol validator"),
        (execution.get("protocol_validator_test"), "primary protocol validator test source"),
        (execution.get("final_scorer"), "final 30-gate scorer"),
        (execution.get("final_scorer_test"), "final scorer test source"),
        (execution.get("producer_replay_verifier"), "automated producer replay verifier"),
        (execution.get("producer_replay_verifier_test"), "producer replay verifier test source"),
        (execution.get("primary_case_gate_evaluator"), "primary case gate evaluator"),
        (
            execution.get("primary_case_gate_evaluator_test"),
            "primary case gate evaluator test source",
        ),
        (
            execution.get("primary_case_gate_evaluator_runtime_test"),
            "primary case gate evaluator runtime integration test source",
        ),
        (
            execution.get("primary_gate_evidence_compiler"),
            "primary case gate evidence compiler",
        ),
        (
            execution.get("primary_gate_evidence_compiler_test"),
            "primary case gate evidence compiler test source",
        ),
        (execution.get("primary_runtime_replay_executor"), "primary runtime replay executor"),
        (
            execution.get("primary_runtime_replay_executor_test"),
            "primary runtime replay executor test source",
        ),
        (execution.get("availability_compiler"), "availability epoch compiler"),
        (execution.get("availability_compiler_test"), "availability compiler test source"),
        (execution.get("event_ledger_replay"), "event-ledger replay generator"),
        (execution.get("event_ledger_replay_test"), "event-ledger replay test source"),
        (execution.get("structural_gate_harness"), "structural-gate harness"),
        (execution.get("structural_gate_harness_test"), "structural-gate harness test source"),
        (execution.get("structural_gate_evidence_schema"), "structural-gate evidence schema"),
        (execution.get("structural_gate_results_schema"), "structural-gate results schema"),
        (execution.get("role_manifest_schema"), "role manifest schema"),
        (execution.get("role_manifest_set_schema"), "role manifest set schema"),
        (execution.get("role_tool_access_trace_schema"), "role tool access trace schema"),
        (
            execution.get("evaluator_sanitized_runtime_ledger_schema"),
            "evaluator sanitized runtime ledger schema",
        ),
        (
            execution.get("all_sealed_artifacts_after_replay_schema"),
            "all-sealed-after-replay schema",
        ),
        (execution.get("sealed_concept_map_schema"), "sealed concept map schema"),
        (execution.get("search_snapshot_schema"), "search snapshot schema"),
        (execution.get("raw_search_response_schema"), "raw search response schema"),
        (execution.get("raw_search_retrieval_schema"), "raw search retrieval manifest schema"),
        (execution.get("screening_schema"), "screening schema"),
        (execution.get("screening_evidence_schema"), "screening evidence schema"),
        (execution.get("complexity_claims_schema"), "opaque concurrent-process claims schema"),
        (execution.get("complexity_packet_schema"), "opaque concurrent-process packet schema"),
        (
            execution.get("sealed_complexity_packet_schema"),
            "sealed opaque concurrent-process packet schema",
        ),
        (execution.get("mapped_observation_schema"), "mapped observation consumption schema"),
        (execution.get("final_result_schema"), "final holdout result schema"),
        (execution.get("gate_evidence_schema"), "content-addressed gate evidence schema"),
        (
            execution.get("primary_case_gate_evaluator_input_schema"),
            "primary case gate evaluator input schema",
        ),
        (
            execution.get("primary_case_gate_evaluation_schema"),
            "primary case gate evaluator output schema",
        ),
        (
            execution.get("primary_report_candidate_schema"),
            "primary report candidate schema",
        ),
        (
            execution.get("primary_runtime_replay_input_schema"),
            "primary runtime replay input manifest schema",
        ),
        (execution.get("primary_runtime_output_schema"), "primary runtime output schema"),
        (
            execution.get("primary_runtime_replay_seal_schema"),
            "primary runtime replay seal schema",
        ),
        (execution.get("availability_schema"), "availability ledger schema"),
        (exclusions.get("artifact"), "exclusion list"),
    ):
        _verify_embedded_artifact(study_root, row, label)
    _verify_tree(study_root, runtime.get("recursive_source_tree"), REL_RUNTIME_ROOT, "runtime")
    _verify_tree(study_root, model.get("recursive_source_tree"), REL_MODEL_ROOT, "generic model")

    # Repeat semantic/component verification, not just byte verification.
    fresh = build_payload(study_root, sealed_at=str(payload.get("sealed_at")))
    fresh_digest = fresh.pop("payload_sha256")
    if payload != fresh:
        _fail("combined seal no longer matches re-derived component bindings")
    _assert_hash(expected_digest, fresh_digest, "re-derived combined seal payload")
    return {
        "status": "PASS",
        "seal": REL_OUTPUT.as_posix(),
        "payload_sha256": expected_digest,
        "verified_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("build", "verify", "preflight"))
    parser.add_argument(
        "--study-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
        help="new_clinical_framework_case_study root (default: inferred)",
    )
    parser.add_argument("--sealed-at", help="test-only deterministic ISO timestamp")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            path = write_seal(args.study_root, sealed_at=args.sealed_at)
            print(json.dumps({"status": "BUILT", "path": str(path)}, ensure_ascii=False))
        elif args.command == "verify":
            print(json.dumps(verify_seal(args.study_root), ensure_ascii=False, sort_keys=True))
        else:
            payload = build_payload(args.study_root, sealed_at=args.sealed_at)
            print(
                json.dumps(
                    {
                        "status": "READY_TO_SEAL",
                        "payload_sha256": payload["payload_sha256"],
                        "runtime_source_files": payload["bindings"]["runtime"]["recursive_source_tree"]["file_count"],
                        "generic_model_source_files": payload["bindings"]["generic_model"]["recursive_source_tree"]["file_count"],
                        "excluded_case_identifier_count": payload["bindings"]["primary_holdout_exclusions"]["identifier_count"],
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
        return 0
    except (SealError, OSError) as exc:
        print(json.dumps({"status": "FAIL_CLOSED", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
