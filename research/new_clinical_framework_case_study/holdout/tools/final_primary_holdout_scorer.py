#!/usr/bin/env python3
"""Fail-closed final scorer for the frozen 30-gate primary holdout.

The scorer does not diagnose a patient and cannot turn a correct published
diagnosis into a positive verdict.  It only aggregates already-sealed gate
evidence and case-specific complexity coverage against the frozen contracts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, NoReturn, Sequence

from producer_replay_verifier import (
    ProducerReplayError,
    verify_automated_producer_replay,
)


TOOL_PATH = Path(__file__).resolve()
STUDY_ROOT = TOOL_PATH.parents[2]
GATES_PATH = STUDY_ROOT / "holdout/PERFECT_LANDING_GATES.json"
SCORING_PATH = STUDY_ROOT / "holdout/PRIMARY_HOLDOUT_SCORING_v1.json"
RESULT_SCHEMA_PATH = STUDY_ROOT / "holdout/schemas/primary_holdout_final_result.schema.json"
EVIDENCE_SCHEMA_VERSION = "ncf.primary-gate-evidence.v3"
PREPRIMARY_SEAL_REL = "holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json"
ROLE_MANIFEST_SCHEMA_VERSION = "NCF-PRIMARY-ROLE-MANIFEST-1.1.0"

INPUT_SCHEMA_VERSION = "ncf.primary-gate-evidence-bundle.v1"
COVERAGE_SCHEMA_VERSION = "ncf.primary-complex-case-coverage.v1"
OUTPUT_SCHEMA_VERSION = "ncf.primary-holdout-final-result.v1"
POSITIVE_VERDICT = "PERFECT_LANDING_WITHIN_FROZEN_CASE_SCOPE"
INCOMPLETE_VERDICT = "HARNESS_INCOMPLETE"
FAILED_VERDICT = "FAILED"

ALLOWED_GATE_RESULTS = {"PASS", "FAIL", "EVIDENCE_MISSING", "NOT_EXECUTED", "NOT_APPLICABLE"}
COMPLETE_GATE_RESULTS = {"PASS", "FAIL"}
REQUIRED_COMPLEX_COVERAGE = [
    "recursive_updates",
    "at_least_two_local_domains",
    "concurrent_process_target_from_oracle",
    "delayed_information",
    "reliable_negative_evidence",
    "performed_action_lifecycle_with_response",
    "prospective_pre_next_cut_forecasts",
]


class ScoringError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise ScoringError(message)


def _load(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        _fail(f"{label} missing or symlink: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid {label}: {exc}")
    if not isinstance(value, Mapping):
        _fail(f"{label} must be a JSON object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _strict_equal(left: Any, right: Any) -> bool:
    """JSON-type-strict equality (unlike Python, ``True != 1``)."""

    try:
        return _canonical_sha(left) == _canonical_sha(right)
    except (TypeError, ValueError):
        return False


def _canonical_content_ref(ref: Mapping[str, Any]) -> dict[str, Any]:
    return {"path": ref["path"], "sha256": ref["sha256"], "bytes": ref["bytes"]}


def _resolve_content_ref(
    root: Path,
    ref: Any,
    *,
    label: str,
    named: bool = False,
    parse_json: bool = True,
) -> tuple[Path, Any] | None:
    required = {"path", "sha256", "bytes"} | ({"ref_id"} if named else set())
    if not isinstance(ref, Mapping) or set(ref) != required:
        return None
    path_text = ref.get("path")
    sha = ref.get("sha256")
    size = ref.get("bytes")
    if (
        not isinstance(path_text, str)
        or not isinstance(sha, str)
        or len(sha) != 64
        or any(ch not in "0123456789abcdef" for ch in sha)
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 1
        or (named and (not isinstance(ref.get("ref_id"), str) or not ref.get("ref_id")))
    ):
        return None
    rel = Path(path_text)
    if rel.is_absolute() or ".." in rel.parts or rel.as_posix() != path_text or path_text in {"", "."}:
        return None

    # Reject a symlink at any path component, including one that resolves to a
    # different location still inside the study root.
    candidate = root
    for part in rel.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            return None
    try:
        path = candidate.resolve(strict=True)
        path.relative_to(root)
    except (FileNotFoundError, OSError, ValueError):
        return None
    if not path.is_file() or path.stat().st_size != size or _sha(path) != sha:
        return None
    if not parse_json:
        return path, None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return path, value


def _json_pointer(value: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise ValueError("invalid JSON pointer")
    current = value
    if pointer == "":
        return current
    for raw in pointer.split("/")[1:]:
        index = 0
        while index < len(raw):
            if raw[index] == "~" and (index + 1 >= len(raw) or raw[index + 1] not in "01"):
                raise ValueError("invalid JSON pointer escape")
            index += 2 if raw[index] == "~" else 1
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping):
            if token not in current:
                raise KeyError(token)
            current = current[token]
        elif isinstance(current, list):
            if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
                raise ValueError("invalid array index")
            index = int(token)
            if index >= len(current):
                raise IndexError(index)
            current = current[index]
        else:
            raise TypeError("pointer traverses scalar")
    return current


def _numeric(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("numeric operator requires numbers")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("numeric operator requires finite numbers")
    return number


def _evaluate_operator(operator: str, observed: Any, expected: Any) -> bool:
    if operator == "EQ":
        return _strict_equal(observed, expected)
    if operator == "NE":
        return not _strict_equal(observed, expected)
    if operator in {"GT", "GTE", "LT", "LTE"}:
        left, right = _numeric(observed), _numeric(expected)
        return {"GT": left > right, "GTE": left >= right, "LT": left < right, "LTE": left <= right}[operator]
    if operator in {"CONTAINS", "NOT_CONTAINS"}:
        if isinstance(observed, str) and isinstance(expected, str):
            present = expected in observed
        elif isinstance(observed, list):
            present = any(_strict_equal(item, expected) for item in observed)
        elif isinstance(observed, Mapping) and isinstance(expected, str):
            present = expected in observed
        else:
            raise TypeError("CONTAINS requires string, array, or object")
        return present if operator == "CONTAINS" else not present
    if operator == "SET_EQUALS":
        if not isinstance(observed, list) or not isinstance(expected, list):
            raise TypeError("SET_EQUALS requires arrays")
        left = {_canonical_sha(item) for item in observed}
        right = {_canonical_sha(item) for item in expected}
        return left == right
    if operator == "LENGTH_EQ":
        if not isinstance(observed, (str, list, Mapping)) or isinstance(expected, bool) or not isinstance(expected, int):
            raise TypeError("LENGTH_EQ requires a sized JSON value and integer")
        return len(observed) == expected
    raise ValueError(f"unsupported operator: {operator}")


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _contract_gate_ids(gates: Mapping[str, Any]) -> list[str]:
    if gates.get("contract_id") != "NCF-PERFECT-LANDING-GATES" or gates.get("contract_version") != "1.1.0":
        _fail("unexpected gate contract identity/version")
    rows = gates.get("gates")
    if not isinstance(rows, list) or len(rows) != 30:
        _fail("frozen gate contract must contain exactly 30 gates")
    ids: list[str] = []
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("id"), str):
            _fail("invalid gate row in frozen contract")
        if str(row.get("severity", "")).lower() != "hard":
            _fail("all 30 frozen gates must remain hard")
        ids.append(row["id"])
    if len(set(ids)) != 30:
        _fail("frozen gate IDs are not unique")
    return ids


def _normalize_rows(
    supplied: Any,
    expected_ids: Sequence[str],
    id_key: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    supplied_rows = supplied if isinstance(supplied, list) else []
    expected = set(expected_ids)
    by_id: dict[str, list[Mapping[str, Any]]] = {}
    malformed = 0
    for row in supplied_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get(id_key), str):
            malformed += 1
            continue
        by_id.setdefault(str(row[id_key]), []).append(row)
    duplicates = sorted(key for key, rows in by_id.items() if len(rows) != 1)
    unknown = sorted(key for key in by_id if key not in expected)
    missing = [key for key in expected_ids if key not in by_id]
    normalized: list[dict[str, Any]] = []
    invalid_results: list[str] = []
    missing_evidence: list[str] = []
    for key in expected_ids:
        candidates = by_id.get(key, [])
        row = candidates[0] if len(candidates) == 1 else {}
        result = row.get("result")
        evidence = row.get("evidence_refs")
        if result not in ALLOWED_GATE_RESULTS:
            invalid_results.append(key)
            result = "EVIDENCE_MISSING"
        if (
            not isinstance(evidence, list)
            or not evidence
            or any(
                not isinstance(item, Mapping)
                or set(item) != {"path", "sha256", "bytes"}
                or not isinstance(item.get("path"), str)
                or not isinstance(item.get("sha256"), str)
                or isinstance(item.get("bytes"), bool)
                or not isinstance(item.get("bytes"), int)
                or item.get("bytes", 0) < 1
                for item in evidence
            )
        ):
            missing_evidence.append(key)
            evidence = []
        normalized.append(
            {
                id_key: key,
                "result": result,
                "evidence_refs": evidence,
                "failure_class": row.get("failure_class") if isinstance(row.get("failure_class"), str) else None,
                "source_presence": len(candidates) == 1,
            }
        )
    exact = not (malformed or duplicates or unknown or missing or invalid_results or missing_evidence)
    return normalized, {
        "exact": exact,
        "supplied_count": len(supplied_rows),
        "expected_count": len(expected_ids),
        "missing_ids": missing,
        "duplicate_ids": duplicates,
        "unknown_ids": unknown,
        "malformed_row_count": malformed,
        "invalid_result_ids": invalid_results,
        "missing_evidence_ids": missing_evidence,
    }


def _producer_contract(scoring: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], Mapping[str, Any]]:
    final = scoring.get("final_scorer_contract")
    if not isinstance(final, Mapping):
        return {}, {}
    policy = final.get("evidence_producer_policy")
    if not isinstance(policy, Mapping):
        return {}, {}
    rows = policy.get("sealed_automated_generators")
    manual = policy.get("manual_independent_auditor")
    if not isinstance(rows, list) or not isinstance(manual, Mapping):
        return {}, {}
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("producer_id"), str):
            return {}, {}
        if row["producer_id"] in by_id:
            return {}, {}
        by_id[row["producer_id"]] = row
    return by_id, manual


def _subject_allowed(config: Mapping[str, Any], kind: str, subject_id: str) -> bool:
    allowed = config.get("allowed_subjects")
    return (
        isinstance(allowed, Mapping)
        and isinstance(allowed.get(kind), list)
        and subject_id in allowed[kind]
    )


def _pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _validate_automated_assertion_binding(
    *,
    contract: Any,
    artifact: Any,
    assertions: Sequence[Mapping[str, Any]],
    source_ref_id: str,
    subject_kind: str,
    subject_id: str,
    claimed_result: str,
) -> tuple[bool, str]:
    """Bind an automated evidence claim to its exact producer result.

    Fresh replay proves that the artifact was produced by the sealed program.
    It does *not* prove that an arbitrary true JSON pointer in that artifact is
    evidence for the claimed subject.  This function closes that second gap by
    deriving the only permitted assertion set from a frozen, per-producer
    assertion contract and requiring exact, exhaustive coverage.
    """

    if not isinstance(contract, Mapping) or contract.get("schema_version") != "ncf.producer-assertion-contract.v1":
        return False, "producer_assertion_contract_missing_or_malformed"
    if not isinstance(artifact, Mapping):
        return False, "producer_assertion_artifact_not_object"
    mode = contract.get("mode")
    expected: dict[str, tuple[Any, str]] = {}

    if mode in {"SUBJECT_RESULT_ROW_EXACT_V1", "SUBJECT_RESULT_ROW_EXHAUSTIVE_CHECKS_V1"}:
        base_keys = {
            "schema_version",
            "mode",
            "result_array_json_pointers",
            "subject_id_field",
            "subject_kind_field",
            "result_field",
        }
        exhaustive = mode == "SUBJECT_RESULT_ROW_EXHAUSTIVE_CHECKS_V1"
        required_keys = base_keys | (
            {"checks_field", "check_id_field", "check_observed_field", "check_expected_field", "check_operator_field", "check_pass_field"}
            if exhaustive else set()
        )
        if set(contract) != required_keys:
            return False, "producer_assertion_contract_result_row_keys_mismatch"
        arrays = contract.get("result_array_json_pointers")
        subject_id_field = contract.get("subject_id_field")
        subject_kind_field = contract.get("subject_kind_field")
        result_field = contract.get("result_field")
        if (
            not isinstance(arrays, Mapping)
            or set(arrays) - {"GATE", "COMPLEX_COVERAGE"}
            or not isinstance(arrays.get(subject_kind), str)
            or not isinstance(subject_id_field, str)
            or not subject_id_field
            or (subject_kind_field is not None and (not isinstance(subject_kind_field, str) or not subject_kind_field))
            or not isinstance(result_field, str)
            or not result_field
        ):
            return False, "producer_assertion_contract_result_row_malformed"
        array_pointer = arrays[subject_kind]
        try:
            rows = _json_pointer(artifact, array_pointer)
        except (KeyError, IndexError, TypeError, ValueError):
            return False, "producer_assertion_subject_array_missing"
        if not isinstance(rows, list):
            return False, "producer_assertion_subject_array_not_array"
        matches: list[tuple[int, Mapping[str, Any]]] = []
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            if row.get(subject_id_field) != subject_id:
                continue
            if subject_kind_field is not None and row.get(subject_kind_field) != subject_kind:
                continue
            matches.append((index, row))
        if len(matches) != 1:
            return False, "producer_assertion_subject_row_not_exactly_once"
        row_index, row = matches[0]
        computed_result = row.get(result_field)
        if computed_result not in {"PASS", "FAIL"} or computed_result != claimed_result:
            return False, "producer_assertion_subject_result_mismatch"
        result_pointer = f"{array_pointer}/{row_index}/{_pointer_token(result_field)}"
        expected[result_pointer] = (claimed_result, "EQ")

        if exhaustive:
            checks_field = contract.get("checks_field")
            check_id_field = contract.get("check_id_field")
            check_observed_field = contract.get("check_observed_field")
            check_expected_field = contract.get("check_expected_field")
            check_operator_field = contract.get("check_operator_field")
            check_pass_field = contract.get("check_pass_field")
            names = (
                checks_field,
                check_id_field,
                check_observed_field,
                check_expected_field,
                check_operator_field,
                check_pass_field,
            )
            if any(not isinstance(name, str) or not name for name in names):
                return False, "producer_assertion_contract_check_fields_malformed"
            checks = row.get(str(checks_field))
            if not isinstance(checks, list) or not checks:
                return False, "producer_assertion_subject_checks_missing"
            check_ids: set[str] = set()
            recomputed: list[bool] = []
            for check_index, check in enumerate(checks):
                if not isinstance(check, Mapping):
                    return False, "producer_assertion_subject_check_malformed"
                check_id = check.get(str(check_id_field))
                passed = check.get(str(check_pass_field))
                operator = check.get(str(check_operator_field))
                if (
                    not isinstance(check_id, str)
                    or not check_id
                    or check_id in check_ids
                    or not isinstance(passed, bool)
                    or not isinstance(operator, str)
                ):
                    return False, "producer_assertion_subject_check_malformed"
                check_ids.add(check_id)
                try:
                    actual = _evaluate_operator(
                        operator,
                        check.get(str(check_observed_field)),
                        check.get(str(check_expected_field)),
                    )
                except (TypeError, ValueError):
                    return False, "producer_assertion_subject_check_operator_invalid"
                if actual is not passed:
                    return False, "producer_assertion_subject_check_pass_not_recomputable"
                recomputed.append(actual)
                pointer = (
                    f"{array_pointer}/{row_index}/{_pointer_token(str(checks_field))}/"
                    f"{check_index}/{_pointer_token(str(check_pass_field))}"
                )
                expected[pointer] = (True, "EQ")
            derived_result = "PASS" if all(recomputed) else "FAIL"
            if computed_result != derived_result:
                return False, "producer_assertion_subject_result_not_derived_from_all_checks"

    elif mode == "SUBJECT_EXACT_POINTERS_V1":
        if set(contract) != {"schema_version", "mode", "subject_assertions"}:
            return False, "producer_assertion_contract_exact_pointer_keys_mismatch"
        by_kind = contract.get("subject_assertions")
        by_subject = by_kind.get(subject_kind) if isinstance(by_kind, Mapping) else None
        rows = by_subject.get(subject_id) if isinstance(by_subject, Mapping) else None
        if not isinstance(rows, list) or not rows:
            return False, "producer_assertion_subject_exact_pointer_contract_missing"
        truth: list[bool] = []
        for row in rows:
            if not isinstance(row, Mapping) or set(row) != {"json_pointer", "expected", "operator"}:
                return False, "producer_assertion_subject_exact_pointer_contract_malformed"
            pointer = row.get("json_pointer")
            operator = row.get("operator")
            if not isinstance(pointer, str) or not isinstance(operator, str) or pointer in expected:
                return False, "producer_assertion_subject_exact_pointer_contract_malformed"
            try:
                observed = _json_pointer(artifact, pointer)
                truth.append(_evaluate_operator(operator, observed, row.get("expected")))
            except (KeyError, IndexError, TypeError, ValueError):
                return False, "producer_assertion_subject_exact_pointer_not_recomputable"
            expected[pointer] = (row.get("expected"), operator)
        derived_result = "PASS" if all(truth) else "FAIL"
        if claimed_result != derived_result:
            return False, "producer_assertion_subject_result_not_derived_from_exact_pointers"
    else:
        return False, "producer_assertion_contract_mode_unknown"

    actual: dict[str, Mapping[str, Any]] = {}
    for assertion in assertions:
        pointer = assertion.get("observed_json_pointer")
        if not isinstance(pointer, str) or pointer in actual:
            return False, "producer_assertion_pointer_duplicate_or_malformed"
        actual[pointer] = assertion
    if set(actual) != set(expected):
        return False, "producer_assertion_coverage_not_exact"
    for pointer, (expected_value, operator) in expected.items():
        assertion = actual[pointer]
        if (
            assertion.get("source_ref_id") != source_ref_id
            or assertion.get("operator") != operator
            or not _strict_equal(assertion.get("expected"), expected_value)
        ):
            return False, "producer_assertion_contract_value_or_operator_mismatch"
    return True, "PASS"


def _validate_role_manifest_for_manual_failure(
    manifest: Any,
    audit_ref: Mapping[str, Any],
    manual_policy: Mapping[str, Any],
) -> bool:
    if not isinstance(manifest, Mapping):
        return False
    if (
        manifest.get("schema_version") != manual_policy.get("required_role_manifest_schema_version")
        or manifest.get("role") != manual_policy.get("required_role")
        or manifest.get("case_identity_exposed") is not True
    ):
        return False
    attestations = manifest.get("attestations")
    required_attestations = {
        "only_declared_inputs_observed",
        "no_forbidden_data_class_observed",
        "no_undeclared_output_written",
        "no_artifact_modified_after_input_hash",
    }
    if not isinstance(attestations, Mapping) or any(attestations.get(key) is not True for key in required_attestations):
        return False
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        return False
    expected = _canonical_content_ref(audit_ref)
    return any(
        isinstance(row, Mapping)
        and all(row.get(key) == value for key, value in expected.items())
        and row.get("data_class") == manual_policy.get("required_audit_output_data_class")
        for row in outputs
    )


def _validate_evidence(
    gate_rows: Sequence[Mapping[str, Any]],
    coverage_rows: Sequence[Mapping[str, Any]],
    study_root: Path | None,
    scoring: Mapping[str, Any],
    sealed_artifacts: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    invalid: list[dict[str, str]] = []
    validated = 0
    if study_root is None:
        return {
            "all_valid": False,
            "validated_artifact_count": 0,
            "invalid_artifacts": [{"subject_id": "*", "reason": "study_root_not_supplied"}],
        }
    if sealed_artifacts is None:
        return {
            "all_valid": False,
            "validated_artifact_count": 0,
            "invalid_artifacts": [{"subject_id": "*", "reason": "verified_combined_seal_producer_index_not_supplied"}],
        }
    root = study_root.resolve(strict=True)
    automated_policy, manual_policy = _producer_contract(scoring)
    if not automated_policy or not manual_policy:
        return {
            "all_valid": False,
            "validated_artifact_count": 0,
            "invalid_artifacts": [{"subject_id": "*", "reason": "evidence_producer_policy_missing_or_malformed"}],
        }

    # A single producer artifact may support several gates.  It is regenerated
    # once per exact invocation digest and then reused only after the replay
    # claim, source refs, and tool binding are shown to be identical.
    replay_cache: dict[str, bool] = {}
    for kind, id_key, rows in (
        ("GATE", "gate_id", gate_rows),
        ("COMPLEX_COVERAGE", "coverage_id", coverage_rows),
    ):
        for row in rows:
            subject_id = str(row[id_key])
            result = row["result"]
            refs = row.get("evidence_refs", [])
            for ref in refs:
                loaded = _resolve_content_ref(root, ref, label="evidence reference")
                if loaded is None:
                    invalid.append({"subject_id": subject_id, "reason": "evidence_ref_invalid_or_content_mismatch"})
                    continue
                _, evidence = loaded
                if not isinstance(evidence, Mapping):
                    invalid.append({"subject_id": subject_id, "reason": "evidence_not_object"})
                    continue
                if set(evidence) != {
                    "schema_version",
                    "subject_kind",
                    "subject_id",
                    "claimed_result",
                    "producer",
                    "source_artifact_refs",
                    "assertions",
                }:
                    invalid.append({"subject_id": subject_id, "reason": "evidence_top_level_malformed"})
                    continue
                if (
                    evidence.get("schema_version") != EVIDENCE_SCHEMA_VERSION
                    or evidence.get("subject_kind") != kind
                    or evidence.get("subject_id") != subject_id
                    or evidence.get("claimed_result") != result
                ):
                    invalid.append({"subject_id": subject_id, "reason": "evidence_subject_or_result_binding_mismatch"})
                    continue

                source_rows = evidence.get("source_artifact_refs")
                if not isinstance(source_rows, list) or not source_rows:
                    invalid.append({"subject_id": subject_id, "reason": "source_artifact_refs_missing"})
                    continue
                source_values: dict[str, Any] = {}
                source_refs: dict[str, Mapping[str, Any]] = {}
                source_paths: dict[str, Path] = {}
                source_ok = True
                for source_ref in source_rows:
                    loaded_source = _resolve_content_ref(root, source_ref, label="source artifact", named=True)
                    if loaded_source is None:
                        source_ok = False
                        break
                    ref_id = str(source_ref["ref_id"])
                    if ref_id in source_values:
                        source_ok = False
                        break
                    source_refs[ref_id] = source_ref
                    source_paths[ref_id] = loaded_source[0]
                    source_values[ref_id] = loaded_source[1]
                if not source_ok:
                    invalid.append({"subject_id": subject_id, "reason": "source_artifact_ref_invalid_or_content_mismatch"})
                    continue

                producer = evidence.get("producer")
                producer_source_id: str | None = None
                automated_assertion_contract: Mapping[str, Any] | None = None
                if not isinstance(producer, Mapping):
                    invalid.append({"subject_id": subject_id, "reason": "producer_missing_or_malformed"})
                    continue
                if producer.get("policy") == "SEALED_AUTOMATED_GENERATOR":
                    if set(producer) != {
                        "policy",
                        "producer_id",
                        "tool_ref",
                        "artifact_ref_id",
                        "replay",
                    }:
                        invalid.append({"subject_id": subject_id, "reason": "automated_producer_malformed"})
                        continue
                    config = automated_policy.get(str(producer.get("producer_id")))
                    tool_ref = producer.get("tool_ref")
                    if (
                        not isinstance(config, Mapping)
                        or not isinstance(tool_ref, Mapping)
                        or set(tool_ref) != {"path", "sha256", "bytes"}
                    ):
                        invalid.append({"subject_id": subject_id, "reason": "automated_producer_not_allowed"})
                        continue
                    assertion_contract = config.get("assertion_contract")
                    if not isinstance(assertion_contract, Mapping):
                        invalid.append({"subject_id": subject_id, "reason": "producer_assertion_contract_missing_or_malformed"})
                        continue
                    automated_assertion_contract = assertion_contract
                    tool_path = config.get("tool_path")
                    sealed = sealed_artifacts.get(str(tool_path)) if isinstance(tool_path, str) else None
                    if (
                        not _subject_allowed(config, kind, subject_id)
                        or sealed is None
                        or _canonical_content_ref(tool_ref) != _canonical_content_ref(sealed)
                        or tool_ref.get("path") != tool_path
                        or _resolve_content_ref(root, tool_ref, label="producer tool", parse_json=False) is None
                    ):
                        invalid.append({"subject_id": subject_id, "reason": "producer_tool_not_exact_combined_sealed_allowed_generator"})
                        continue
                    producer_source_id = str(producer.get("artifact_ref_id"))
                    artifact = source_values.get(producer_source_id)
                    schema_versions = config.get("artifact_schema_versions")
                    if (
                        artifact is None
                        or not isinstance(artifact, Mapping)
                        or not isinstance(schema_versions, list)
                        or artifact.get("schema_version") not in schema_versions
                        or (
                            config.get("artifact_produced_by_required") is True
                            and artifact.get("produced_by") != tool_path
                        )
                    ):
                        invalid.append({"subject_id": subject_id, "reason": "producer_artifact_not_bound_to_allowed_generator_contract"})
                        continue
                    replay = producer.get("replay")
                    replay_contract = config.get("replay_contract")
                    if not isinstance(replay, Mapping) or not isinstance(replay_contract, Mapping):
                        invalid.append({"subject_id": subject_id, "reason": "producer_replay_contract_missing_or_malformed"})
                        continue
                    invocation_claim = replay.get("invocation_sha256")
                    if not isinstance(invocation_claim, str):
                        invalid.append({"subject_id": subject_id, "reason": "producer_replay_invocation_missing"})
                        continue
                    replay_cache_key = _canonical_sha(
                        {
                            "producer_id": producer.get("producer_id"),
                            "tool_ref": tool_ref,
                            "artifact_ref_id": producer_source_id,
                            "replay": replay,
                            "source_refs": {
                                key: source_refs[key] for key in sorted(source_refs)
                            },
                        }
                    )
                    if replay_cache_key not in replay_cache:
                        try:
                            replay_result = verify_automated_producer_replay(
                                study_root=root,
                                producer_id=str(producer.get("producer_id")),
                                tool_ref=tool_ref,
                                tool_path=(root / str(tool_path)).resolve(strict=True),
                                replay_policy=replay_contract,
                                replay_claim=replay,
                                source_refs=source_refs,
                                source_paths=source_paths,
                                source_values=source_values,
                                output_ref_id=producer_source_id,
                            )
                        except (ProducerReplayError, OSError, ValueError) as exc:
                            invalid.append({
                                "subject_id": subject_id,
                                "reason": f"producer_fresh_replay_failed:{exc}",
                            })
                            continue
                        replay_cache[replay_cache_key] = replay_result.status == "PASS"
                    if replay_cache.get(replay_cache_key) is not True:
                        invalid.append({"subject_id": subject_id, "reason": "producer_fresh_replay_not_pass"})
                        continue
                elif producer.get("policy") == "MANUAL_INDEPENDENT_AUDITOR":
                    if set(producer) != {
                        "policy",
                        "policy_id",
                        "auditor_role_manifest_ref_id",
                        "audit_record_ref_id",
                    }:
                        invalid.append({"subject_id": subject_id, "reason": "manual_auditor_producer_malformed"})
                        continue
                    if producer.get("policy_id") != manual_policy.get("policy_id"):
                        invalid.append({"subject_id": subject_id, "reason": "manual_auditor_policy_mismatch"})
                        continue
                    # A human audit can surface a hard failure, but cannot mint
                    # a positive machine-verification result.  An unautomated
                    # positive gate is HARNESS_INCOMPLETE by construction.
                    if result == "PASS" or manual_policy.get("pass_permitted") is not False:
                        invalid.append({"subject_id": subject_id, "reason": "manual_auditor_pass_cannot_complete_gate"})
                        continue
                    producer_source_id = str(producer.get("audit_record_ref_id"))
                    role_ref_id = str(producer.get("auditor_role_manifest_ref_id"))
                    audit_ref = source_refs.get(producer_source_id)
                    if (
                        manual_policy.get("fail_permitted") is not True
                        or audit_ref is None
                        or role_ref_id not in source_values
                        or not _validate_role_manifest_for_manual_failure(
                            source_values[role_ref_id], audit_ref, manual_policy
                        )
                    ):
                        invalid.append({"subject_id": subject_id, "reason": "manual_auditor_independence_or_artifact_binding_invalid"})
                        continue
                else:
                    invalid.append({"subject_id": subject_id, "reason": "producer_policy_unknown"})
                    continue

                assertions = evidence.get("assertions")
                if not isinstance(assertions, list) or not assertions:
                    invalid.append({"subject_id": subject_id, "reason": "assertions_missing_or_malformed"})
                    continue
                assertion_ids: set[str] = set()
                truth: list[bool] = []
                assertions_ok = True
                for assertion in assertions:
                    required = {
                        "assertion_id",
                        "source_ref_id",
                        "observed_json_pointer",
                        "observed",
                        "expected",
                        "operator",
                    }
                    assertion_keys = set(assertion) if isinstance(assertion, Mapping) else set()
                    if not isinstance(assertion, Mapping) or assertion_keys not in (
                        required,
                        required | {"notes"},
                    ):
                        assertions_ok = False
                        break
                    assertion_id = assertion.get("assertion_id")
                    source_id = assertion.get("source_ref_id")
                    if (
                        not isinstance(assertion_id, str)
                        or not assertion_id
                        or assertion_id in assertion_ids
                        or not isinstance(source_id, str)
                        or source_id != producer_source_id
                        or source_id not in source_values
                    ):
                        assertions_ok = False
                        break
                    assertion_ids.add(assertion_id)
                    try:
                        extracted = _json_pointer(source_values[source_id], assertion["observed_json_pointer"])
                        if not _strict_equal(extracted, assertion["observed"]):
                            assertions_ok = False
                            break
                        truth.append(
                            _evaluate_operator(
                                str(assertion["operator"]),
                                assertion["observed"],
                                assertion["expected"],
                            )
                        )
                    except (KeyError, IndexError, TypeError, ValueError):
                        assertions_ok = False
                        break
                if not assertions_ok:
                    invalid.append({"subject_id": subject_id, "reason": "deterministic_assertion_invalid_or_not_source_derived"})
                    continue
                if automated_assertion_contract is not None:
                    bound, reason = _validate_automated_assertion_binding(
                        contract=automated_assertion_contract,
                        artifact=source_values[producer_source_id],
                        assertions=assertions,
                        source_ref_id=producer_source_id,
                        subject_kind=kind,
                        subject_id=subject_id,
                        claimed_result=result,
                    )
                    if not bound:
                        invalid.append({"subject_id": subject_id, "reason": reason})
                        continue
                if result == "PASS" and not all(truth):
                    invalid.append({"subject_id": subject_id, "reason": "pass_claim_operator_check_failed"})
                    continue
                if result == "FAIL" and all(truth):
                    invalid.append({"subject_id": subject_id, "reason": "fail_claim_contains_no_failed_operator_check"})
                    continue
                if result not in {"PASS", "FAIL"}:
                    invalid.append({"subject_id": subject_id, "reason": "incomplete_status_cannot_be_evidence_complete"})
                    continue
                validated += 1
    return {
        "all_valid": not invalid,
        "validated_artifact_count": validated,
        "invalid_artifacts": invalid,
    }


def score_documents(
    gates: Mapping[str, Any],
    scoring: Mapping[str, Any],
    gate_bundle: Mapping[str, Any],
    coverage_bundle: Mapping[str, Any],
    *,
    generated_at: str | None = None,
    gates_sha256: str = "0" * 64,
    scoring_sha256: str = "0" * 64,
    study_root: Path | None = None,
    sealed_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    gate_ids = _contract_gate_ids(gates)
    if scoring.get("contract_id") != "NCF-PRIMARY-HOLDOUT-SCORING" or scoring.get("contract_version") != "1.0.0":
        _fail("unexpected scoring contract identity/version")
    if scoring.get("verdict_boundary", {}).get("all_30_hard_gates_must_pass") is not True:
        _fail("scoring contract does not require all 30 hard gates")
    if scoring.get("verdict_boundary", {}).get("correct_final_label_can_override_failure") is not False:
        _fail("scoring contract permits diagnosis override")

    bundle_header_ok = (
        gate_bundle.get("schema_version") == INPUT_SCHEMA_VERSION
        and gate_bundle.get("contract_id") == gates.get("contract_id")
        and gate_bundle.get("contract_version") == gates.get("contract_version")
    )
    coverage_header_ok = coverage_bundle.get("schema_version") == COVERAGE_SCHEMA_VERSION
    normalized_gates, gate_coverage = _normalize_rows(gate_bundle.get("gate_results"), gate_ids, "gate_id")
    normalized_coverage, complex_coverage = _normalize_rows(
        coverage_bundle.get("checks"), REQUIRED_COMPLEX_COVERAGE, "coverage_id"
    )
    gate_coverage["header_valid"] = bundle_header_ok
    gate_coverage["exact"] = gate_coverage["exact"] and bundle_header_ok
    complex_coverage["header_valid"] = coverage_header_ok
    complex_coverage["exact"] = complex_coverage["exact"] and coverage_header_ok
    evidence_integrity = _validate_evidence(
        normalized_gates,
        normalized_coverage,
        study_root,
        scoring,
        sealed_artifacts,
    )

    reason_codes: list[str] = []
    if not gate_coverage["exact"]:
        reason_codes.append("GATE_COVERAGE_INCOMPLETE_OR_INVALID")
    if not complex_coverage["exact"]:
        reason_codes.append("COMPLEX_CASE_COVERAGE_INCOMPLETE_OR_INVALID")
    if any(row["result"] not in COMPLETE_GATE_RESULTS for row in normalized_gates):
        reason_codes.append("HARD_GATE_NOT_EXECUTED_OR_EVIDENCE_MISSING")
    if any(row["result"] not in COMPLETE_GATE_RESULTS for row in normalized_coverage):
        reason_codes.append("COMPLEX_COVERAGE_NOT_EXECUTED_OR_EVIDENCE_MISSING")
    if not evidence_integrity["all_valid"]:
        reason_codes.append("EVIDENCE_INTEGRITY_INVALID")

    incomplete = bool(reason_codes)
    gate_failures = [row["gate_id"] for row in normalized_gates if row["result"] == "FAIL"]
    coverage_failures = [row["coverage_id"] for row in normalized_coverage if row["result"] == "FAIL"]
    if incomplete:
        verdict = INCOMPLETE_VERDICT
    elif gate_failures or coverage_failures:
        verdict = FAILED_VERDICT
        if gate_failures:
            reason_codes.append("ONE_OR_MORE_HARD_GATES_FAILED")
        if coverage_failures:
            reason_codes.append("COMPLEX_REAL_CASE_COVERAGE_FAILED")
    else:
        verdict = POSITIVE_VERDICT
        reason_codes.append("ALL_30_HARD_GATES_AND_COMPLEX_CASE_COVERAGE_PASS")

    diagnosis_reported = bool(gate_bundle.get("correct_diagnosis_reported", False))
    report: dict[str, Any] = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "contract_binding": {
            "gate_contract_id": gates["contract_id"],
            "gate_contract_version": gates["contract_version"],
            "gate_contract_sha256": gates_sha256,
            "scoring_contract_id": scoring["contract_id"],
            "scoring_contract_version": scoring["contract_version"],
            "scoring_contract_sha256": scoring_sha256,
        },
        "gate_coverage": gate_coverage,
        "gate_results": normalized_gates,
        "complex_case_coverage": {**complex_coverage, "checks": normalized_coverage},
        "evidence_integrity": evidence_integrity,
        "diagnosis_override": {
            "correct_diagnosis_reported": diagnosis_reported,
            "used_to_override_gate_failure": False,
        },
        "verdict": verdict,
        "reason_codes": reason_codes,
    }
    unsigned = dict(report)
    report["result_sha256"] = _canonical_sha(unsigned)
    return report


def _verified_sealed_artifact_index(study_root: Path) -> dict[str, Mapping[str, Any]]:
    """Return exact pre-primary artifact refs only after full seal verification."""

    try:
        from build_pre_primary_holdout_seal import verify_seal

        verification = verify_seal(study_root)
    except Exception as exc:  # translated to the scorer's fail-closed type
        _fail(f"pre-primary combined seal verification failed: {exc}")
    if verification.get("status") != "PASS":
        _fail("pre-primary combined seal verifier did not return PASS")
    seal = _load(study_root / PREPRIMARY_SEAL_REL, "pre-primary combined seal")
    try:
        execution = seal["bindings"]["primary_execution"]
    except (KeyError, TypeError):
        _fail("combined seal lacks primary_execution bindings")
    if not isinstance(execution, Mapping):
        _fail("combined seal primary_execution binding is malformed")
    result: dict[str, Mapping[str, Any]] = {}
    for row in execution.values():
        if not isinstance(row, Mapping) or set(row) != {"path", "sha256", "bytes"}:
            continue
        path = row.get("path")
        if not isinstance(path, str) or path in result:
            _fail("combined seal contains invalid/duplicate primary execution artifact")
        result[path] = dict(row)
    if not result:
        _fail("combined seal contains no primary execution artifacts")
    return result


def score_files(gate_bundle_path: Path, coverage_bundle_path: Path, *, study_root: Path = STUDY_ROOT) -> dict[str, Any]:
    gates_path = study_root / "holdout/PERFECT_LANDING_GATES.json"
    scoring_path = study_root / "holdout/PRIMARY_HOLDOUT_SCORING_v1.json"
    sealed_artifacts = _verified_sealed_artifact_index(study_root)
    return score_documents(
        _load(gates_path, "gate contract"),
        _load(scoring_path, "scoring contract"),
        _load(gate_bundle_path, "gate evidence bundle"),
        _load(coverage_bundle_path, "complex coverage bundle"),
        gates_sha256=_sha(gates_path),
        scoring_sha256=_sha(scoring_path),
        study_root=study_root,
        sealed_artifacts=sealed_artifacts,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-results", type=Path, required=True)
    parser.add_argument("--complex-coverage", type=Path, required=True)
    parser.add_argument("--study-root", type=Path, default=STUDY_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.output.exists():
            _fail(f"refusing to overwrite output: {args.output}")
        report = score_files(args.gate_results, args.complex_coverage, study_root=args.study_root)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = args.output.with_suffix(args.output.suffix + ".tmp")
        temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, args.output)
        print(json.dumps({"verdict": report["verdict"], "result_sha256": report["result_sha256"]}, sort_keys=True))
        return 0 if report["verdict"] == POSITIVE_VERDICT else 2
    except (ScoringError, OSError) as exc:
        print(f"FAIL_CLOSED: {exc}")
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
