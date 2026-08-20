"""Fail-closed checks for the NCF primary real-case execution protocol."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from urllib.parse import urlsplit
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence


EXPECTED_IDENTIFIABILITY = [
    "IDENTIFIED_WITHIN_SCOPE",
    "PARTIALLY_IDENTIFIED",
    "UNIDENTIFIABLE",
    "OUT_OF_SCOPE",
]
EXPECTED_ROLES = [
    "scout",
    "screener",
    "extractor",
    "source_auditor",
    "concept_mapper",
    "oracle_adjudicator",
    "evaluator",
    "scorer_auditor",
]

ROLE_TRACE_SCHEMA_ID = "ncf.primary-role-tool-access-trace.v1"
ROLE_TRACE_SCHEMA_VERSION = "NCF-PRIMARY-ROLE-TOOL-ACCESS-TRACE-1.0.0"
COMBINED_SEAL_PATH = "holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json"
SANITIZED_RUNTIME_SCHEMA_PATH = "holdout/schemas/evaluator_sanitized_runtime_ledger.schema.json"
ALL_SEALED_REPLAY_SCHEMA_PATH = "holdout/schemas/primary_all_sealed_artifacts_after_replay.schema.json"
SEALED_CONCEPT_MAP_SCHEMA_PATH = "holdout/schemas/sealed_concept_map.schema.json"
SANITIZED_LEDGER_ASSIGNMENT_PROOF_SCHEMA_PATH = (
    "holdout/schemas/evaluator_sanitized_runtime_ledger_assignment_proof.schema.json"
)
SANITIZED_LEDGER_REPLAY_VERIFICATION_SCHEMA_PATH = (
    "holdout/schemas/evaluator_sanitized_runtime_ledger_replay_verification.schema.json"
)
SANITIZED_LEDGER_COMPILER_PRODUCER_ID = (
    "evaluator-sanitized-runtime-ledger-compiler-v1"
)
SANITIZED_LEDGER_COMPILER_PATH = (
    "holdout/tools/compile_evaluator_sanitized_runtime_ledger.py"
)
SANITIZED_LEDGER_COMPILER_TEST_PATH = (
    "holdout/tools/test_compile_evaluator_sanitized_runtime_ledger.py"
)
SANITIZED_LEDGER_COMPILER_INPUT_SCHEMA_PATH = (
    "holdout/schemas/evaluator_sanitized_runtime_ledger_compiler_input.schema.json"
)
SANITIZED_LEDGER_REPLAY_VERIFIER_PATH = (
    "holdout/tools/verify_evaluator_sanitized_runtime_ledger.py"
)
SANITIZED_LEDGER_REPLAY_VERIFIER_TEST_PATH = (
    "holdout/tools/test_verify_evaluator_sanitized_runtime_ledger.py"
)
SANITIZED_LEDGER_LOGICAL_BASENAME = "evaluator_sanitized_runtime_ledger.json"
EXPECTED_PACKAGED_EVALUATOR_OUTPUTS = {
    "runtime_output", "replay_seal",
}
EXPECTED_CONTROLLED_VALUE_CODES = {
    "PRESENT", "ABSENT", "POSITIVE", "NEGATIVE", "NORMAL", "ABNORMAL",
    "LOW", "MEDIUM", "HIGH", "UNKNOWN", "ORDERED", "STARTED", "CONTINUED",
    "DOSE_CHANGED", "HELD", "RESUMED", "STOPPED", "COMPLETED",
    "IMPROVED", "UNCHANGED", "WORSENED",
}
EXPECTED_ACTION_LIFECYCLE_PHASES = [
    "ORDERED", "STARTED", "CONTINUED", "DOSE_CHANGED", "HELD", "RESUMED",
    "STOPPED", "COMPLETED",
]
EXPECTED_ACTION_DOSE_PHASES = ["STARTED", "CONTINUED", "DOSE_CHANGED", "RESUMED"]
EXPECTED_ACTION_NO_DOSE_PHASES = ["ORDERED", "HELD", "STOPPED", "COMPLETED"]
EXPECTED_EVIDENCE_QUALIFICATION_FIELDS = {
    "explicit_assertion", "target_scope", "adequate_method", "adequate_timing",
    "adequate_reliability",
}
EXPECTED_TRISTATE_VALUES = ["TRUE", "FALSE", "UNKNOWN"]
EXPECTED_SANITIZED_UNITS = [
    None, "mIU/L", "mmHg", "mmol/L", "ng/dL", "percent", "ug/dL", "xULN",
]
EXPECTED_SANITIZED_ACTION_DOSE_UNITS = [None]
SANITIZED_NUMBER_PATTERN = (
    r"^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$"
)
SANITIZED_NONNEGATIVE_NUMBER_PATTERN = (
    r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$"
)

# These values are duplicated deliberately.  The validator is part of the
# pre-primary sealed code surface; comparing the protocol to a code-owned
# constant prevents a coordinated edit of allow/forbid/root lists from
# self-authorising a weaker isolation policy.
EXPECTED_ROLE_POLICIES: dict[str, dict[str, Any]] = {
    "scout": {
        "allowed_input_data_classes": [
            "protocol", "broad_scope", "identifier_only_exclusions", "combined_preprimary_seal",
        ],
        "allowed_output_data_classes": [
            "public_search_results", "search_retrieval_manifest", "search_snapshot",
            "immutable_candidate_source_snapshot", "candidate_source_evidence_index",
        ],
        "forbidden_data_classes": [
            "model_pack", "model_registry", "runtime_source", "runtime_output",
            "oracle_contents", "expected_diagnosis",
        ],
        "case_identity_exposure": "PERMITTED",
        "network_access_policy": "REQUIRED_NCBI_HTTPS_GET_ONLY",
    },
    "screener": {
        "allowed_input_data_classes": [
            "protocol", "identifier_only_exclusions", "public_search_results",
            "search_retrieval_manifest", "search_snapshot",
            "immutable_candidate_source_snapshot", "candidate_source_evidence_index",
        ],
        "allowed_output_data_classes": [
            "candidate_screening", "deterministic_selection_result",
            "immutable_selected_source", "immutable_source_manifest",
            "opaque_concurrent_process_candidate_packet",
        ],
        "forbidden_data_classes": [
            "model_pack", "model_registry", "runtime_source", "runtime_output",
            "oracle_contents", "expected_diagnosis",
        ],
        "case_identity_exposure": "PERMITTED",
        "network_access_policy": "FORBIDDEN",
    },
    "extractor": {
        "allowed_input_data_classes": [
            "deterministic_selection_result", "immutable_selected_source",
            "immutable_source_manifest", "extraction_schema", "protocol",
        ],
        "allowed_output_data_classes": [
            "source_inventory", "event_ledger", "diagnosis_neutral_mapper_packet", "availability_ledger",
        ],
        "forbidden_data_classes": [
            "model_pack", "model_registry", "runtime_source", "runtime_output", "scoring_output",
        ],
        "case_identity_exposure": "PERMITTED",
        "network_access_policy": "FORBIDDEN",
    },
    "source_auditor": {
        "allowed_input_data_classes": [
            "candidate_screening", "deterministic_selection_result", "immutable_selected_source",
            "immutable_source_manifest", "source_inventory", "event_ledger",
            "availability_ledger", "diagnosis_neutral_mapper_packet",
            "opaque_concurrent_process_candidate_packet", "protocol",
        ],
        "allowed_output_data_classes": [
            "source_audit", "sealed_source_inventory", "sealed_event_ledger", "sealed_availability_ledger",
            "sealed_diagnosis_neutral_mapper_packet",
            "sealed_opaque_concurrent_process_candidate_packet",
        ],
        "forbidden_data_classes": ["model_pack", "runtime_output", "scoring_output"],
        "case_identity_exposure": "PERMITTED",
        "network_access_policy": "FORBIDDEN",
    },
    "concept_mapper": {
        "allowed_input_data_classes": [
            "sealed_diagnosis_neutral_mapper_packet", "sanitized_id_type_unit_registry", "protocol",
        ],
        "allowed_output_data_classes": ["sealed_concept_map", "concept_mapping_report"],
        "forbidden_data_classes": [
            "case_identity", "event_values", "chronology", "hypotheses", "diagnosis", "outcome",
            "likelihoods", "priors", "couplings", "model_pack", "runtime_output",
        ],
        "case_identity_exposure": "FORBIDDEN",
        "network_access_policy": "FORBIDDEN",
    },
    "oracle_adjudicator": {
        "allowed_input_data_classes": [
            "immutable_selected_source", "sealed_source_inventory", "sealed_event_ledger",
            "sealed_availability_ledger", "sealed_opaque_concurrent_process_candidate_packet",
            "sanitized_process_name_description_registry", "protocol",
        ],
        "allowed_output_data_classes": ["oracle_contents", "oracle_seal_hash_only"],
        "forbidden_data_classes": [
            "model_numeric_parameters", "model_pack", "runtime_output", "scoring_output",
        ],
        "case_identity_exposure": "PERMITTED",
        "network_access_policy": "FORBIDDEN",
    },
    "evaluator": {
        "allowed_input_data_classes": [
            "evaluator_sanitized_runtime_ledger", "sealed_concept_map", "model_pack",
            "runtime", "scoring_contract", "protocol", "combined_preprimary_seal",
            "oracle_seal_hash_only", "sanitized_id_type_unit_registry",
        ],
        "allowed_output_data_classes": [
            "runtime_output", "replay_seal", "mapped_observation_consumption",
            "all_sealed_artifacts_after_replay",
        ],
        "forbidden_data_classes": [
            "oracle_contents", "final_diagnosis_before_replay_seal",
            "terminal_outcome_before_replay_seal", "future_events_at_old_cut",
            "case_identity", "pmid", "pmcid", "doi", "source_title", "source_locator",
            "opaque_concurrent_process_candidate_packet",
            "sealed_opaque_concurrent_process_candidate_packet",
        ],
        "case_identity_exposure": "FORBIDDEN",
        "network_access_policy": "FORBIDDEN",
    },
    "scorer_auditor": {
        "allowed_input_data_classes": [
            "all_sealed_artifacts_after_replay", "mapped_observation_consumption", "oracle_contents",
            "source_audit", "concept_mapping_report", "sealed_source_inventory",
            "sealed_event_ledger", "sealed_availability_ledger",
            "sealed_opaque_concurrent_process_candidate_packet",
        ],
        "allowed_output_data_classes": ["audit_report"],
        "forbidden_data_classes": ["artifact_modification"],
        "case_identity_exposure": "PERMITTED",
        "network_access_policy": "FORBIDDEN",
    },
}

EXPECTED_PRESEALED_ROOT_ASSET_PATHS = {
    "protocol": "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json",
    "broad_scope": "holdout/generic_model/MODEL_SCOPE.md",
    "identifier_only_exclusions": "holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json",
    "combined_preprimary_seal": COMBINED_SEAL_PATH,
    "extraction_schema": "architecture_final_v1.schema.json",
    "sanitized_id_type_unit_registry": "holdout/generic_model/mapper_sanitized_registry.json",
    "sanitized_process_name_description_registry": "holdout/generic_model/oracle_sanitized_process_registry.json",
    "model_pack": "holdout/generic_model/model_pack.json",
    "runtime": "runtime_v2/evidence/manifest.json",
    "scoring_contract": "holdout/PRIMARY_HOLDOUT_SCORING_v1.json",
}

EXPECTED_PRODUCER_CONSUMER_EDGES = [
    {"producer_role": "scout", "data_class": "public_search_results", "consumer_roles": ["screener"]},
    {
        "producer_role": "scout",
        "data_class": "search_retrieval_manifest",
        "consumer_roles": ["screener"],
    },
    {"producer_role": "scout", "data_class": "search_snapshot", "consumer_roles": ["screener"]},
    {
        "producer_role": "scout",
        "data_class": "immutable_candidate_source_snapshot",
        "consumer_roles": ["screener"],
    },
    {
        "producer_role": "scout",
        "data_class": "candidate_source_evidence_index",
        "consumer_roles": ["screener"],
    },
    {
        "producer_role": "screener",
        "data_class": "candidate_screening",
        "consumer_roles": ["source_auditor"],
    },
    {
        "producer_role": "screener",
        "data_class": "deterministic_selection_result",
        "consumer_roles": ["extractor", "source_auditor"],
    },
    {
        "producer_role": "screener",
        "data_class": "immutable_selected_source",
        "consumer_roles": ["extractor", "source_auditor", "oracle_adjudicator"],
    },
    {
        "producer_role": "screener",
        "data_class": "immutable_source_manifest",
        "consumer_roles": ["extractor", "source_auditor"],
    },
    {
        "producer_role": "screener",
        "data_class": "opaque_concurrent_process_candidate_packet",
        "consumer_roles": ["source_auditor"],
    },
    {
        "producer_role": "extractor",
        "data_class": "source_inventory",
        "consumer_roles": ["source_auditor"],
    },
    {"producer_role": "extractor", "data_class": "event_ledger", "consumer_roles": ["source_auditor"]},
    {
        "producer_role": "extractor",
        "data_class": "availability_ledger",
        "consumer_roles": ["source_auditor"],
    },
    {
        "producer_role": "extractor",
        "data_class": "diagnosis_neutral_mapper_packet",
        "consumer_roles": ["source_auditor"],
    },
    {
        "producer_role": "source_auditor",
        "data_class": "source_audit",
        "consumer_roles": ["scorer_auditor"],
    },
    {
        "producer_role": "source_auditor",
        "data_class": "sealed_source_inventory",
        "consumer_roles": ["oracle_adjudicator", "scorer_auditor"],
    },
    {
        "producer_role": "source_auditor",
        "data_class": "sealed_event_ledger",
        "consumer_roles": ["oracle_adjudicator", "scorer_auditor"],
    },
    {
        "producer_role": "source_auditor",
        "data_class": "sealed_availability_ledger",
        "consumer_roles": ["oracle_adjudicator", "scorer_auditor"],
    },
    {
        "producer_role": "source_auditor",
        "data_class": "sealed_diagnosis_neutral_mapper_packet",
        "consumer_roles": ["concept_mapper"],
    },
    {
        "producer_role": "source_auditor",
        "data_class": "sealed_opaque_concurrent_process_candidate_packet",
        "consumer_roles": ["oracle_adjudicator", "scorer_auditor"],
    },
    {
        "producer_role": "concept_mapper",
        "data_class": "sealed_concept_map",
        "consumer_roles": ["evaluator"],
    },
    {
        "producer_role": "concept_mapper",
        "data_class": "concept_mapping_report",
        "consumer_roles": ["scorer_auditor"],
    },
    {
        "producer_role": "oracle_adjudicator",
        "data_class": "oracle_contents",
        "consumer_roles": ["scorer_auditor"],
    },
    {
        "producer_role": "oracle_adjudicator",
        "data_class": "oracle_seal_hash_only",
        "consumer_roles": ["evaluator"],
    },
    {
        "producer_role": "evaluator",
        "data_class": "all_sealed_artifacts_after_replay",
        "consumer_roles": ["scorer_auditor"],
    },
    {
        "producer_role": "evaluator",
        "data_class": "mapped_observation_consumption",
        "consumer_roles": ["scorer_auditor"],
    },
]

EXPECTED_EXTERNAL_PRODUCER_EDGES = [
    {
        "producer_id": SANITIZED_LEDGER_COMPILER_PRODUCER_ID,
        "data_class": "evaluator_sanitized_runtime_ledger",
        "consumer_roles": ["evaluator"],
        "producer_kind": "SEALED_EXECUTABLE_OUTPUT",
        "assignment_proof_schema_id": (
            "ncf.evaluator-sanitized-runtime-ledger-assignment-proof.v1"
        ),
        "assignment_proof_schema_path": SANITIZED_LEDGER_ASSIGNMENT_PROOF_SCHEMA_PATH,
        "replay_verification_schema_id": (
            "ncf.evaluator-sanitized-runtime-ledger-replay-verification.v1"
        ),
        "replay_verification_schema_path": (
            SANITIZED_LEDGER_REPLAY_VERIFICATION_SCHEMA_PATH
        ),
    }
]

EXPECTED_DATA_CLASS_SCHEMA_IDS = {
    "all_sealed_artifacts_after_replay": "ncf.data.all-sealed-artifacts-after-replay.v1",
    "audit_report": "ncf.data.audit-report.v1",
    "availability_ledger": "ncf.data.availability-ledger.v1",
    "broad_scope": "ncf.data.broad-scope.v1",
    "candidate_screening": "ncf.data.candidate-screening.v1",
    "candidate_source_evidence_index": "ncf.data.candidate-source-evidence-index.v1",
    "combined_preprimary_seal": "ncf.data.combined-preprimary-seal.v1",
    "concept_mapping_report": "ncf.data.concept-mapping-report.v1",
    "deterministic_selection_result": "ncf.data.deterministic-selection-result.v1",
    "diagnosis_neutral_mapper_packet": "ncf.data.diagnosis-neutral-mapper-packet.v1",
    "event_ledger": "ncf.data.event-ledger.v1",
    "evaluator_sanitized_runtime_ledger": "ncf.evaluator-sanitized-runtime-ledger.v1",
    "extraction_schema": "ncf.data.extraction-schema.v1",
    "identifier_only_exclusions": "ncf.data.identifier-only-exclusions.v1",
    "immutable_candidate_source_snapshot": "ncf.data.immutable-candidate-source-snapshot.v1",
    "immutable_selected_source": "ncf.data.immutable-selected-source.v1",
    "immutable_source_manifest": "ncf.data.immutable-source-manifest.v1",
    "mapped_observation_consumption": "ncf.mapped-observation-consumption.v1",
    "model_pack": "ncf.data.model-pack.v1",
    "oracle_contents": "ncf.data.oracle-contents.v1",
    "oracle_seal_hash_only": "ncf.data.oracle-seal-hash-only.v1",
    "opaque_concurrent_process_candidate_packet": (
        "ncf.opaque-concurrent-process-candidate-packet.v1"
    ),
    "protocol": "ncf.data.protocol.v1",
    "public_search_results": "ncf.data.public-search-results.v1",
    "replay_seal": "ncf.data.replay-seal.v1",
    "runtime": "ncf.data.runtime.v1",
    "runtime_output": "ncf.data.runtime-output.v1",
    "sanitized_id_type_unit_registry": "ncf.data.sanitized-id-type-unit-registry.v1",
    "sanitized_process_name_description_registry": "ncf.data.sanitized-process-name-description-registry.v1",
    "scoring_contract": "ncf.data.scoring-contract.v1",
    "sealed_availability_ledger": "ncf.data.sealed-availability-ledger.v1",
    "sealed_concept_map": "ncf.data.sealed-concept-map.v1",
    "sealed_diagnosis_neutral_mapper_packet": "ncf.data.sealed-diagnosis-neutral-mapper-packet.v1",
    "sealed_event_ledger": "ncf.data.sealed-event-ledger.v1",
    "sealed_opaque_concurrent_process_candidate_packet": (
        "ncf.sealed-opaque-concurrent-process-candidate-packet.v1"
    ),
    "sealed_source_inventory": "ncf.data.sealed-source-inventory.v1",
    "search_retrieval_manifest": "ncf.data.search-retrieval-manifest.v1",
    "search_snapshot": "ncf.data.search-snapshot.v1",
    "source_audit": "ncf.data.source-audit.v1",
    "source_inventory": "ncf.data.source-inventory.v1",
}


class ProtocolError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise ProtocolError(message)


def _load(path: Path, label: str) -> Mapping[str, Any]:
    if not path.is_file() or path.is_symlink():
        _fail(f"{label} missing or symlink: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid {label}: {exc}")
    if not isinstance(value, Mapping):
        _fail(f"{label} must be JSON object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _schema_ref(schema_root: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        _fail(f"only local JSON Schema refs are allowed: {ref}")
    node: Any = schema_root
    for raw in ref[2:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, Mapping) or key not in node:
            _fail(f"unresolvable JSON Schema ref: {ref}")
        node = node[key]
    if not isinstance(node, Mapping):
        _fail(f"JSON Schema ref is not an object: {ref}")
    return node


def _validate_schema_instance(
    value: Any,
    schema: Mapping[str, Any],
    *,
    schema_root: Mapping[str, Any] | None = None,
    at: str = "$",
) -> None:
    """Validate the deliberately small, frozen JSON-Schema subset used here.

    The project has no third-party JSON-Schema dependency.  This validator is
    therefore local and fail closed: unsupported keywords in the role schemas
    are rejected during preflight rather than silently ignored.
    """

    root = schema if schema_root is None else schema_root
    if "$ref" in schema:
        ref = schema.get("$ref")
        if not isinstance(ref, str):
            _fail(f"invalid JSON Schema ref at {at}")
        _validate_schema_instance(value, _schema_ref(root, ref), schema_root=root, at=at)
        return
    allowed_keywords = {
        "$schema", "$id", "$defs", "type", "additionalProperties", "required",
        "properties", "const", "enum", "minLength", "pattern", "format",
        "items", "uniqueItems", "minItems", "maxItems", "minimum",
        "oneOf", "allOf", "if", "then", "else", "not",
    }
    unknown = set(schema) - allowed_keywords
    if unknown:
        _fail(f"unsupported JSON Schema keyword(s) at {at}: {sorted(unknown)}")

    def matches(candidate_schema: Mapping[str, Any], candidate_at: str) -> bool:
        try:
            _validate_schema_instance(value, candidate_schema, schema_root=root, at=candidate_at)
        except ProtocolError:
            return False
        return True

    all_of = schema.get("allOf")
    if all_of is not None:
        if not isinstance(all_of, list) or any(not isinstance(row, Mapping) for row in all_of):
            _fail(f"invalid JSON Schema allOf at {at}")
        for index, branch in enumerate(all_of):
            _validate_schema_instance(value, branch, schema_root=root, at=f"{at}.allOf[{index}]")
    one_of = schema.get("oneOf")
    if one_of is not None:
        if not isinstance(one_of, list) or any(not isinstance(row, Mapping) for row in one_of):
            _fail(f"invalid JSON Schema oneOf at {at}")
        match_count = sum(
            matches(branch, f"{at}.oneOf[{index}]")
            for index, branch in enumerate(one_of)
        )
        if match_count != 1:
            _fail(f"JSON Schema oneOf match count is {match_count}, expected 1 at {at}")
    negated = schema.get("not")
    if negated is not None:
        if not isinstance(negated, Mapping):
            _fail(f"invalid JSON Schema not at {at}")
        if matches(negated, f"{at}.not"):
            _fail(f"JSON Schema not matched at {at}")
    condition = schema.get("if")
    if condition is not None:
        if not isinstance(condition, Mapping):
            _fail(f"invalid JSON Schema if at {at}")
        branch_key = "then" if matches(condition, f"{at}.if") else "else"
        branch = schema.get(branch_key)
        if branch is not None:
            if not isinstance(branch, Mapping):
                _fail(f"invalid JSON Schema {branch_key} at {at}")
            _validate_schema_instance(value, branch, schema_root=root, at=f"{at}.{branch_key}")
    expected_type = schema.get("type")
    type_ok = {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
    }.get(expected_type, True)
    if expected_type is not None and not type_ok:
        _fail(f"JSON Schema type mismatch at {at}: expected {expected_type}")
    if "const" in schema and value != schema["const"]:
        _fail(f"JSON Schema const mismatch at {at}")
    if "enum" in schema:
        enum = schema["enum"]
        if not isinstance(enum, list) or value not in enum:
            _fail(f"JSON Schema enum mismatch at {at}")
    if isinstance(value, str):
        minimum_length = schema.get("minLength")
        if isinstance(minimum_length, int) and len(value) < minimum_length:
            _fail(f"JSON Schema minLength failure at {at}")
        pattern = schema.get("pattern")
        if isinstance(pattern, str) and re.search(pattern, value) is None:
            _fail(f"JSON Schema pattern failure at {at}")
        if schema.get("format") == "date-time":
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                _fail(f"JSON Schema date-time failure at {at}")
            if parsed.tzinfo is None:
                _fail(f"JSON Schema date-time must include timezone at {at}")
    if isinstance(value, int) and not isinstance(value, bool):
        minimum = schema.get("minimum")
        if isinstance(minimum, int) and value < minimum:
            _fail(f"JSON Schema minimum failure at {at}")
    if isinstance(value, list):
        if isinstance(schema.get("minItems"), int) and len(value) < schema["minItems"]:
            _fail(f"JSON Schema minItems failure at {at}")
        if isinstance(schema.get("maxItems"), int) and len(value) > schema["maxItems"]:
            _fail(f"JSON Schema maxItems failure at {at}")
        if schema.get("uniqueItems") is True:
            keys = [json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for item in value]
            if len(keys) != len(set(keys)):
                _fail(f"JSON Schema uniqueItems failure at {at}")
        item_schema = schema.get("items")
        if item_schema is not None:
            if not isinstance(item_schema, Mapping):
                _fail(f"invalid JSON Schema items at {at}")
            for index, item in enumerate(value):
                _validate_schema_instance(item, item_schema, schema_root=root, at=f"{at}[{index}]")
    if isinstance(value, Mapping):
        required = schema.get("required", [])
        if not isinstance(required, list) or any(not isinstance(key, str) for key in required):
            _fail(f"invalid JSON Schema required at {at}")
        missing = set(required) - set(value)
        if missing:
            _fail(f"JSON Schema required property missing at {at}: {sorted(missing)}")
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            _fail(f"invalid JSON Schema properties at {at}")
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(properties)
            if extra:
                _fail(f"JSON Schema additional property at {at}: {sorted(extra)}")
        for key, child in value.items():
            child_schema = properties.get(key)
            if child_schema is not None:
                if not isinstance(child_schema, Mapping):
                    _fail(f"invalid JSON Schema property definition at {at}.{key}")
                _validate_schema_instance(child, child_schema, schema_root=root, at=f"{at}.{key}")


def _canonical_path_bytes(
    study_root: Path, rel: Any, label: str
) -> tuple[str, Path, bytes]:
    if not isinstance(rel, str) or not rel or "\\" in rel:
        _fail(f"{label} path must be a canonical POSIX relative path")
    posix = PurePosixPath(rel)
    if posix.is_absolute() or rel != posix.as_posix() or any(part in {"", ".", ".."} for part in posix.parts):
        _fail(f"{label} path is not canonical relative: {rel}")
    root = study_root.resolve(strict=True)
    path = root.joinpath(*posix.parts)
    # Check every lexical component with lstat before any target-following
    # is_file/stat/read operation.  This rejects symlinks and Windows reparse
    # points (including junctions) rather than inspecting their targets first.
    cursor = root
    for part in posix.parts:
        cursor = cursor / part
        try:
            metadata = os.lstat(cursor)
        except OSError:
            _fail(f"{label} missing or unreadable: {rel}")
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
        if stat.S_ISLNK(metadata.st_mode) or attributes & reparse_flag:
            _fail(f"{label} path contains symlink/reparse point: {rel}")
    if not stat.S_ISREG(os.lstat(path).st_mode):
        _fail(f"{label} missing or not a regular file: {rel}")
    resolved = path.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        _fail(f"{label} path escapes study root: {rel}")
    if resolved.relative_to(root).as_posix() != rel:
        _fail(f"{label} path does not name its canonical file: {rel}")
    # A single read supplies both the verified digest/size and, for JSON
    # callers, the bytes that will be parsed.  Do not hash one file version and
    # reopen a second version for semantic validation.
    payload = resolved.read_bytes()
    return rel, resolved, payload


def _canonical_artifact_bytes(
    study_root: Path, row: Mapping[str, Any], label: str
) -> tuple[str, Path, bytes]:
    rel, resolved, payload = _canonical_path_bytes(study_root, row.get("path"), label)
    if hashlib.sha256(payload).hexdigest() != row.get("sha256") or len(payload) != row.get("bytes"):
        _fail(f"{label} artifact hash/size mismatch: {rel}")
    return rel, resolved, payload


def _canonical_artifact(study_root: Path, row: Mapping[str, Any], label: str) -> tuple[str, Path]:
    rel, path, _ = _canonical_artifact_bytes(study_root, row, label)
    return rel, path


def _json_from_verified_bytes(payload: bytes, label: str) -> Mapping[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid {label}: {exc}")
    if not isinstance(value, Mapping):
        _fail(f"{label} must be JSON object")
    return value


def _canonical_json_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _combined_seal_inventory(value: Any) -> dict[str, tuple[str, int]]:
    """Collect every content-addressed artifact embedded in a combined seal.

    A repeated path is permitted only when every occurrence binds the same
    digest and byte count.  The combined seal builder uses the same
    ``path/sha256/bytes`` record shape throughout its nested bindings.
    """

    inventory: dict[str, tuple[str, int]] = {}

    def visit(node: Any) -> None:
        if isinstance(node, Mapping):
            if {"path", "sha256", "bytes"}.issubset(node):
                path = node.get("path")
                sha256 = node.get("sha256")
                byte_count = node.get("bytes")
                if (
                    not isinstance(path, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", str(sha256 or ""))
                    or not isinstance(byte_count, int)
                    or isinstance(byte_count, bool)
                    or byte_count < 1
                ):
                    _fail("combined seal contains malformed artifact inventory row")
                identity = (str(sha256), byte_count)
                previous = inventory.get(path)
                if previous is not None and previous != identity:
                    _fail(f"combined seal binds one path to multiple contents: {path}")
                inventory[path] = identity
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return inventory


def _verify_combined_seal_ref(
    study_root: Path, seal_ref: Any, label: str
) -> tuple[dict[str, tuple[str, int]], Mapping[str, Any]]:
    if not isinstance(seal_ref, Mapping) or set(seal_ref) != {"path", "sha256", "bytes"}:
        _fail(f"{label} must be an exact content reference")
    rel, _, payload = _canonical_artifact_bytes(study_root, seal_ref, label)
    if rel != COMBINED_SEAL_PATH:
        _fail(f"{label} must bind the canonical combined pre-primary seal")
    seal = _json_from_verified_bytes(payload, label)
    if (
        seal.get("format_version") != "NCF-PRE-PRIMARY-HOLDOUT-SEAL-1.0.0"
        or seal.get("seal_id") != "NCF-PRE-PRIMARY-HOLDOUT-SEAL"
        or seal.get("status") != "SEALED_BEFORE_PRIMARY_CASE_SELECTION"
    ):
        _fail(f"{label} is not a valid pre-primary combined seal")
    expected = seal.get("payload_sha256")
    unsigned = dict(seal)
    unsigned.pop("payload_sha256", None)
    if expected != _canonical_json_sha256(unsigned):
        _fail(f"{label} payload self-hash mismatch")
    blindness = seal.get("case_blindness")
    if not isinstance(blindness, Mapping) or (
        blindness.get("case_content_read_by_builder") is not False
        or blindness.get("case_identity_selected") is not False
    ):
        _fail(f"{label} case-blindness attestation invalid")
    return _combined_seal_inventory(seal), seal


def _assert_acyclic_roles(edges: Sequence[tuple[str, str]]) -> None:
    graph = {role: set() for role in EXPECTED_ROLES}
    indegree = {role: 0 for role in EXPECTED_ROLES}
    for producer, consumer in edges:
        if consumer not in graph[producer]:
            graph[producer].add(consumer)
            indegree[consumer] += 1
    ready = [role for role in EXPECTED_ROLES if indegree[role] == 0]
    seen: list[str] = []
    while ready:
        role = ready.pop(0)
        seen.append(role)
        for child in sorted(graph[role]):
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if len(seen) != len(EXPECTED_ROLES):
        _fail("role producer-consumer graph is cyclic")


def _schema_node(schema: Mapping[str, Any], *path: str) -> Mapping[str, Any]:
    node: Any = schema
    for key in path:
        if not isinstance(node, Mapping) or key not in node:
            _fail(f"role schema missing node: {'/'.join(path)}")
        node = node[key]
    if not isinstance(node, Mapping):
        _fail(f"role schema node is not object: {'/'.join(path)}")
    return node


def _assert_closed_object_schema(
    node: Mapping[str, Any], *, required: set[str], properties: set[str], label: str
) -> None:
    if node.get("type") != "object" or node.get("additionalProperties") is not False:
        _fail(f"{label} must remain a closed object schema")
    if set(node.get("required", [])) != required:
        _fail(f"{label} required fields weakened or changed")
    actual_properties = node.get("properties")
    if not isinstance(actual_properties, Mapping) or set(actual_properties) != properties:
        _fail(f"{label} property set weakened or changed")


def _validate_role_schema_structure(
    role_schema: Mapping[str, Any], aggregate_schema: Mapping[str, Any], trace_schema: Mapping[str, Any]
) -> None:
    _assert_closed_object_schema(
        role_schema,
        required={
            "schema_version", "role", "run_id", "started_at", "finished_at",
            "case_identity_exposed", "inputs", "outputs", "observed_data_classes",
            "attestations", "prompt_or_command", "tool_trace", "parent_packet",
        },
        properties={
            "schema_version", "role", "run_id", "started_at", "finished_at",
            "case_identity_exposed", "inputs", "outputs", "observed_data_classes",
            "attestations", "prompt_or_command", "tool_trace", "parent_packet",
        },
        label="role manifest schema",
    )
    content_ref = _schema_node(role_schema, "$defs", "contentRef")
    _assert_closed_object_schema(
        content_ref,
        required={"path", "sha256", "bytes"},
        properties={"path", "sha256", "bytes"},
        label="role contentRef schema",
    )
    if _schema_node(content_ref, "properties", "bytes").get("minimum") != 1:
        _fail("role contentRef bytes minimum weakened")
    if _schema_node(content_ref, "properties", "sha256").get("$ref") != "#/$defs/sha256":
        _fail("role contentRef sha256 binding weakened")
    if _schema_node(content_ref, "properties", "path").get("minLength") != 1:
        _fail("role contentRef path constraint weakened")
    producer = _schema_node(role_schema, "$defs", "producer")
    _assert_closed_object_schema(
        producer,
        required={"kind"},
        properties={
            "kind", "seal", "role", "run_id", "manifest_path", "manifest_sha256", "manifest_bytes",
            "producer_id", "assignment_proof", "replay_verification",
        },
        label="role producer schema",
    )
    if _schema_node(producer, "properties", "kind").get("enum") != [
        "PRESEALED_ROOT", "ROLE_OUTPUT", "SEALED_EXECUTABLE_OUTPUT"
    ]:
        _fail("role producer kind enum weakened")
    if _schema_node(producer, "properties", "seal").get("$ref") != "#/$defs/contentRef":
        _fail("role producer combined-seal binding weakened")
    if _schema_node(producer, "properties", "manifest_sha256").get("$ref") != "#/$defs/sha256":
        _fail("role producer manifest hash binding weakened")
    if _schema_node(producer, "properties", "manifest_bytes").get("minimum") != 1:
        _fail("role producer manifest byte constraint weakened")
    if _schema_node(producer, "properties", "producer_id").get("const") != (
        SANITIZED_LEDGER_COMPILER_PRODUCER_ID
    ):
        _fail("role sealed-executable producer id weakened")
    if _schema_node(producer, "properties", "assignment_proof").get("$ref") != (
        "#/$defs/contentRef"
    ):
        _fail("role sealed-executable assignment proof binding weakened")
    if _schema_node(producer, "properties", "replay_verification").get("$ref") != (
        "#/$defs/contentRef"
    ):
        _fail("role sealed-executable replay verification binding weakened")
    for definition, required in (
        ("inputArtifact", {"path", "sha256", "bytes", "data_class", "schema_id", "producer"}),
        ("outputArtifact", {"path", "sha256", "bytes", "data_class", "schema_id"}),
    ):
        node = _schema_node(role_schema, "$defs", definition)
        _assert_closed_object_schema(
            node,
            required=required,
            properties=required,
            label=f"role {definition} schema",
        )
        for key in ("path", "sha256", "bytes", "data_class", "schema_id"):
            if key not in _schema_node(node, "properties"):
                _fail(f"role {definition} property binding missing: {key}")
        if _schema_node(node, "properties", "sha256").get("$ref") != "#/$defs/sha256":
            _fail(f"role {definition} sha256 binding weakened")
        if _schema_node(node, "properties", "bytes").get("minimum") != 1:
            _fail(f"role {definition} byte constraint weakened")
    if _schema_node(role_schema, "$defs", "inputArtifact", "properties", "producer").get("$ref") != "#/$defs/producer":
        _fail("role input producer binding weakened")
    attestations = _schema_node(role_schema, "properties", "attestations")
    required_attestations = {
        "only_declared_inputs_observed", "no_forbidden_data_class_observed",
        "no_undeclared_output_written", "no_artifact_modified_after_input_hash",
    }
    _assert_closed_object_schema(
        attestations,
        required=required_attestations,
        properties=required_attestations | {"notes"},
        label="role attestations schema",
    )
    for key in required_attestations:
        if _schema_node(attestations, "properties", key).get("const") is not True:
            _fail(f"role attestation const weakened: {key}")
    if _schema_node(role_schema, "properties", "case_identity_exposed").get("type") != "boolean":
        _fail("case_identity_exposed schema weakened")
    for key, ref in (
        ("inputs", "#/$defs/inputArtifact"),
        ("outputs", "#/$defs/outputArtifact"),
    ):
        node = _schema_node(role_schema, "properties", key)
        if node.get("type") != "array" or _schema_node(node, "items").get("$ref") != ref:
            _fail(f"role {key} array schema weakened")
    observed_schema = _schema_node(role_schema, "properties", "observed_data_classes")
    if observed_schema.get("type") != "array" or observed_schema.get("uniqueItems") is not True:
        _fail("role observed_data_classes array schema weakened")
    for key in ("prompt_or_command", "tool_trace", "parent_packet"):
        if _schema_node(role_schema, "properties", key).get("$ref") != "#/$defs/contentRef":
            _fail(f"role {key} contentRef binding weakened")

    _assert_closed_object_schema(
        aggregate_schema,
        required={"schema_version", "protocol", "manifests"},
        properties={"schema_version", "protocol", "manifests"},
        label="role manifest set schema",
    )
    manifest_ref = _schema_node(aggregate_schema, "$defs", "manifestRef")
    manifest_ref_fields = {"role", "run_id", "path", "sha256", "bytes"}
    _assert_closed_object_schema(
        manifest_ref,
        required=manifest_ref_fields,
        properties=manifest_ref_fields,
        label="role manifestRef schema",
    )
    aggregate_content_ref = _schema_node(aggregate_schema, "$defs", "contentRef")
    _assert_closed_object_schema(
        aggregate_content_ref,
        required={"path", "sha256", "bytes"},
        properties={"path", "sha256", "bytes"},
        label="role aggregate contentRef schema",
    )
    if _schema_node(aggregate_schema, "properties", "protocol").get("$ref") != "#/$defs/contentRef":
        _fail("role manifest set protocol contentRef binding weakened")
    manifest_array = _schema_node(aggregate_schema, "properties", "manifests")
    if (
        manifest_array.get("type") != "array"
        or manifest_array.get("minItems") != len(EXPECTED_ROLES)
        or manifest_array.get("maxItems") != len(EXPECTED_ROLES)
        or _schema_node(manifest_array, "items").get("$ref") != "#/$defs/manifestRef"
    ):
        _fail("role manifest set array cardinality/binding weakened")

    if trace_schema.get("$id") != ROLE_TRACE_SCHEMA_ID:
        _fail("role tool access trace schema id mismatch")
    trace_required = {
        "schema_version", "role", "run_id", "execution_kind", "case_identity_exposed",
        "prompt_or_command_sha256", "parent_packet_sha256", "tool_lineage", "accesses",
        "network_requests",
        "trace_complete", "undeclared_access_detected", "network_access_detected",
    }
    _assert_closed_object_schema(
        trace_schema,
        required=trace_required,
        properties=trace_required,
        label="role tool access trace schema",
    )
    if _schema_node(trace_schema, "properties", "trace_complete").get("const") is not True:
        _fail("role tool trace completeness const weakened")
    if _schema_node(trace_schema, "properties", "undeclared_access_detected").get("const") is not False:
        _fail("role tool trace undeclared-access const weakened")
    if _schema_node(trace_schema, "properties", "network_access_detected").get("type") != "boolean":
        _fail("role tool trace network-access flag schema weakened")
    if _schema_node(trace_schema, "properties", "schema_version").get("const") != ROLE_TRACE_SCHEMA_VERSION:
        _fail("role tool trace schema version weakened")
    if _schema_node(trace_schema, "properties", "execution_kind").get("enum") != [
        "AGENT", "SCRIPT", "HYBRID"
    ]:
        _fail("role tool trace execution_kind enum weakened")
    for key, definition in (("tool_lineage", "toolLineage"), ("accesses", "access")):
        array = _schema_node(trace_schema, "properties", key)
        if (
            array.get("type") != "array"
            or array.get("minItems") != 1
            or array.get("uniqueItems") is not True
            or _schema_node(array, "items").get("$ref") != f"#/$defs/{definition}"
        ):
            _fail(f"role tool trace {key} array schema weakened")
    tool_lineage = _schema_node(trace_schema, "$defs", "toolLineage")
    tool_fields = {"tool_id", "version_or_build", "invocation_id"}
    _assert_closed_object_schema(
        tool_lineage,
        required=tool_fields,
        properties=tool_fields,
        label="role tool lineage schema",
    )
    network_array = _schema_node(trace_schema, "properties", "network_requests")
    if (
        network_array.get("type") != "array"
        or network_array.get("uniqueItems") is not True
        or _schema_node(network_array, "items").get("$ref") != "#/$defs/networkRequest"
    ):
        _fail("role tool trace network_requests array schema weakened")
    network_request = _schema_node(trace_schema, "$defs", "networkRequest")
    network_fields = {
        "sequence", "method", "request_url", "response_sha256", "response_bytes", "retrieved_at"
    }
    _assert_closed_object_schema(
        network_request,
        required=network_fields,
        properties=network_fields,
        label="role tool trace network request schema",
    )
    if _schema_node(network_request, "properties", "method").get("const") != "GET":
        _fail("role tool trace network method weakened")
    if _schema_node(network_request, "properties", "sequence").get("minimum") != 0:
        _fail("role tool trace network sequence constraint weakened")
    if _schema_node(network_request, "properties", "request_url").get("minLength") != 1:
        _fail("role tool trace network request URL constraint weakened")
    if _schema_node(network_request, "properties", "response_sha256").get("$ref") != "#/$defs/sha256":
        _fail("role tool trace network response hash binding weakened")
    if _schema_node(network_request, "properties", "response_bytes").get("minimum") != 1:
        _fail("role tool trace network response byte constraint weakened")
    if _schema_node(network_request, "properties", "retrieved_at").get("format") != "date-time":
        _fail("role tool trace network retrieval timestamp constraint weakened")
    access = _schema_node(trace_schema, "$defs", "access")
    access_fields = {
        "sequence", "operation", "artifact_kind", "path", "sha256", "bytes",
        "data_class", "schema_id", "access_count",
    }
    _assert_closed_object_schema(
        access, required=access_fields, properties=access_fields, label="role tool trace access schema"
    )
    if _schema_node(access, "properties", "operation").get("enum") != ["READ", "WRITE"]:
        _fail("role tool trace operation enum weakened")
    if _schema_node(access, "properties", "artifact_kind").get("enum") != [
        "INPUT", "OUTPUT", "PROMPT_OR_COMMAND", "PARENT_PACKET"
    ]:
        _fail("role tool trace artifact_kind enum weakened")
    for key in ("sequence", "access_count"):
        expected_minimum = 0 if key == "sequence" else 1
        if _schema_node(access, "properties", key).get("minimum") != expected_minimum:
            _fail(f"role tool trace {key} constraint weakened")
    if _schema_node(access, "properties", "sha256").get("$ref") != "#/$defs/sha256":
        _fail("role tool trace sha256 binding weakened")
    if _schema_node(access, "properties", "bytes").get("minimum") != 1:
        _fail("role tool trace bytes constraint weakened")


def _validate_sanitized_runtime_schema_structure(schema: Mapping[str, Any]) -> None:
    if schema.get("$id") != "ncf.evaluator-sanitized-runtime-ledger.v1":
        _fail("evaluator sanitized runtime ledger schema id mismatch")
    top_fields = {
        "schema_version", "opaque_run_id", "identity_removed", "source_text_removed",
        "source_locator_removed", "reversible_source_ids_removed", "events",
    }
    _assert_closed_object_schema(
        schema, required=top_fields, properties=top_fields,
        label="evaluator sanitized runtime ledger schema",
    )
    for key in (
        "identity_removed", "source_text_removed", "source_locator_removed",
        "reversible_source_ids_removed",
    ):
        if _schema_node(schema, "properties", key).get("const") is not True:
            _fail(f"evaluator sanitized runtime ledger attestation weakened: {key}")
    if _schema_node(schema, "properties", "opaque_run_id").get("pattern") != "^RUN-[0-9a-f]{64}$":
        _fail("evaluator sanitized runtime ledger opaque run id weakened")
    events = _schema_node(schema, "properties", "events")
    if (
        events.get("type") != "array" or events.get("minItems") != 1
        or _schema_node(events, "items").get("$ref") != "#/$defs/event"
    ):
        _fail("evaluator sanitized runtime ledger events schema weakened")
    event = _schema_node(schema, "$defs", "event")
    required = {
        "opaque_event_id", "opaque_source_concept_token", "event_kind", "typed_value", "unit",
        "observed_epoch_ordinal", "available_epoch_ordinal", "reliability",
    }
    _assert_closed_object_schema(
        event,
        required=required,
        properties=required | {
            "action_lifecycle", "evidence_qualification",
            "alternative_representation_group_id",
        },
        label="evaluator sanitized runtime event schema",
    )
    if _schema_node(event, "properties", "opaque_event_id").get("pattern") != "^EV-[0-9]{8}$":
        _fail("evaluator sanitized runtime event id weakened")
    if _schema_node(event, "properties", "opaque_source_concept_token").get("pattern") != "^SC-[0-9]{8}$":
        _fail("evaluator sanitized source concept token weakened")
    if _schema_node(event, "properties", "event_kind").get("enum") != [
        "OBSERVATION", "ACTION", "SUPPORT"
    ]:
        _fail("evaluator sanitized event kind weakened")
    if _schema_node(event, "properties", "typed_value").get("$ref") != "#/$defs/typedValue":
        _fail("evaluator sanitized typed value binding weakened")
    if _schema_node(event, "properties", "unit").get("enum") != EXPECTED_SANITIZED_UNITS:
        _fail("evaluator sanitized unit registry enum weakened")
    for key in ("observed_epoch_ordinal", "available_epoch_ordinal"):
        time_node = _schema_node(event, "properties", key)
        if time_node.get("type") != "integer" or time_node.get("minimum") != 0:
            _fail(f"evaluator sanitized relative time constraint weakened: {key}")
    if _schema_node(event, "properties", "reliability").get("enum") != [
        "HIGH", "MEDIUM", "LOW", "UNKNOWN"
    ]:
        _fail("evaluator sanitized reliability enum weakened")
    action_lifecycle = _schema_node(event, "properties", "action_lifecycle")
    _assert_closed_object_schema(
        action_lifecycle,
        required={"opaque_action_id", "phase"},
        properties={"opaque_action_id", "phase", "dose", "dose_unit"},
        label="evaluator sanitized action lifecycle schema",
    )
    if _schema_node(action_lifecycle, "properties", "opaque_action_id").get("pattern") != (
        "^ACT-[0-9]{8}$"
    ):
        _fail("evaluator sanitized action id weakened")
    if _schema_node(action_lifecycle, "properties", "phase").get("enum") != (
        EXPECTED_ACTION_LIFECYCLE_PHASES
    ):
        _fail("evaluator sanitized action lifecycle phase weakened")
    if _schema_node(action_lifecycle, "properties", "dose").get("$ref") != (
        "#/$defs/nonnegativeDose"
    ):
        _fail("evaluator sanitized action lifecycle dose binding weakened")
    if _schema_node(action_lifecycle, "properties", "dose_unit").get("enum") != (
        EXPECTED_SANITIZED_ACTION_DOSE_UNITS
    ):
        _fail("evaluator sanitized action lifecycle dose unit registry weakened")
    expected_dose_condition = [
        {
            "properties": {"phase": {"enum": EXPECTED_ACTION_DOSE_PHASES}},
            "required": ["dose", "dose_unit"],
        },
        {
            "properties": {"phase": {"enum": EXPECTED_ACTION_NO_DOSE_PHASES}},
            "allOf": [
                {"not": {"required": ["dose"]}},
                {"not": {"required": ["dose_unit"]}},
            ],
        },
    ]
    if action_lifecycle.get("oneOf") != expected_dose_condition:
        _fail("evaluator sanitized action lifecycle dose/phase contract weakened")
    evidence_qualification = _schema_node(event, "properties", "evidence_qualification")
    _assert_closed_object_schema(
        evidence_qualification,
        required=EXPECTED_EVIDENCE_QUALIFICATION_FIELDS,
        properties=EXPECTED_EVIDENCE_QUALIFICATION_FIELDS,
        label="evaluator sanitized observation evidence qualification schema",
    )
    for field in EXPECTED_EVIDENCE_QUALIFICATION_FIELDS:
        if _schema_node(evidence_qualification, "properties", field).get("enum") != (
            EXPECTED_TRISTATE_VALUES
        ):
            _fail(f"evaluator sanitized evidence qualification weakened: {field}")
    alternative_group = _schema_node(
        event, "properties", "alternative_representation_group_id"
    )
    expected_alternative_group = [
        {"type": "string", "pattern": "^ARG-[0-9]{8}$"},
        {"const": None},
    ]
    if alternative_group.get("oneOf") != expected_alternative_group:
        _fail("evaluator sanitized alternative representation group weakened")
    expected_lifecycle_condition = [
        {
            "if": {
                "properties": {"event_kind": {"enum": ["ACTION", "SUPPORT"]}},
                "required": ["event_kind"],
            },
            "then": {"required": ["action_lifecycle"]},
            "else": {"not": {"required": ["action_lifecycle"]}},
        },
        {
            "if": {
                "properties": {"event_kind": {"const": "OBSERVATION"}},
                "required": ["event_kind"],
            },
            "then": {
                "required": [
                    "evidence_qualification", "alternative_representation_group_id"
                ]
            },
            "else": {
                "allOf": [
                    {"not": {"required": ["evidence_qualification"]}},
                    {"not": {"required": ["alternative_representation_group_id"]}},
                ]
            },
        },
    ]
    if event.get("allOf") != expected_lifecycle_condition:
        _fail("evaluator sanitized action lifecycle conditional weakened")
    nonnegative_dose = _schema_node(schema, "$defs", "nonnegativeDose")
    _assert_closed_object_schema(
        nonnegative_dose,
        required={"kind", "canonical"},
        properties={"kind", "canonical"},
        label="evaluator sanitized nonnegative action dose schema",
    )
    if _schema_node(nonnegative_dose, "properties", "kind").get("const") != "NUMBER":
        _fail("evaluator sanitized action dose kind weakened")
    if _schema_node(nonnegative_dose, "properties", "canonical").get("pattern") != (
        SANITIZED_NONNEGATIVE_NUMBER_PATTERN
    ):
        _fail("evaluator sanitized action dose canonical number weakened")
    typed_value = _schema_node(schema, "$defs", "typedValue")
    _assert_closed_object_schema(
        typed_value, required={"kind", "canonical"}, properties={"kind", "canonical"},
        label="evaluator sanitized typed value schema",
    )
    if _schema_node(typed_value, "properties", "kind").get("enum") != [
        "NUMBER", "BOOLEAN", "CODE", "NULL"
    ]:
        _fail("evaluator sanitized typed value kind weakened")
    if _schema_node(typed_value, "properties", "canonical").get("type") != "string":
        _fail("evaluator sanitized typed value canonical type weakened")
    expected_typed_value_branches = [
        {
            "properties": {
                "kind": {"const": "NUMBER"},
                "canonical": {"pattern": SANITIZED_NUMBER_PATTERN},
            },
            "required": ["kind", "canonical"],
        },
        {
            "properties": {
                "kind": {"const": "BOOLEAN"},
                "canonical": {"enum": ["true", "false"]},
            },
            "required": ["kind", "canonical"],
        },
        {
            "properties": {
                "kind": {"const": "CODE"},
                "canonical": {"enum": sorted(EXPECTED_CONTROLLED_VALUE_CODES)},
            },
            "required": ["kind", "canonical"],
        },
        {
            "properties": {
                "kind": {"const": "NULL"},
                "canonical": {"const": "null"},
            },
            "required": ["kind", "canonical"],
        },
    ]
    if typed_value.get("oneOf") != expected_typed_value_branches:
        _fail("evaluator sanitized typed value canonical branches weakened")


def _assert_identity_neutral_runtime_ledger(value: Mapping[str, Any]) -> None:
    forbidden_keys = {
        "case_id", "canonical_case_id", "pmid", "pmcid", "doi", "title", "source_title",
        "source_locator", "source_url", "url", "citation", "article", "source_text",
        "raw_text", "verbatim", "quote", "source_result_id", "document_id",
    }
    identifier_pattern = re.compile(
        r"(?:\bPMID\s*:?\s*\d+\b|\bPMC\d+\b|https?://|\b10\.\d{4,9}/\S+)", re.IGNORECASE
    )

    def visit(node: Any, at: str) -> None:
        if isinstance(node, Mapping):
            for key, child in node.items():
                lowered = str(key).lower()
                top_level_attestations = {
                    "identity_removed", "source_text_removed", "source_locator_removed",
                    "reversible_source_ids_removed",
                }
                if at == "$" and lowered in top_level_attestations:
                    visit(child, f"{at}.{key}")
                    continue
                if lowered in forbidden_keys or any(
                    marker in lowered for marker in ("source_locator", "source_text", "article_title")
                ):
                    _fail(f"evaluator sanitized runtime ledger contains identity/source field at {at}.{key}")
                visit(child, f"{at}.{key}")
        elif isinstance(node, list):
            for index, child in enumerate(node):
                visit(child, f"{at}[{index}]")
        elif isinstance(node, str) and identifier_pattern.search(node):
            _fail(f"evaluator sanitized runtime ledger contains reversible identity at {at}")

    visit(value, "$")


def _validate_all_sealed_replay_schema_structure(schema: Mapping[str, Any]) -> None:
    if schema.get("$id") != EXPECTED_DATA_CLASS_SCHEMA_IDS["all_sealed_artifacts_after_replay"]:
        _fail("all-sealed-after-replay schema id mismatch")
    fields = {
        "schema_version", "evaluator_run_id", "replay_sealed",
        "oracle_contents_included", "artifacts",
    }
    _assert_closed_object_schema(
        schema, required=fields, properties=fields,
        label="all-sealed-after-replay schema",
    )
    if _schema_node(schema, "properties", "replay_sealed").get("const") is not True:
        _fail("all-sealed-after-replay replay seal const weakened")
    if _schema_node(schema, "properties", "oracle_contents_included").get("const") is not False:
        _fail("all-sealed-after-replay oracle exclusion const weakened")
    artifacts = _schema_node(schema, "properties", "artifacts")
    if (
        artifacts.get("type") != "array" or artifacts.get("minItems") != 1
        or artifacts.get("uniqueItems") is not True
        or _schema_node(artifacts, "items").get("$ref") != "#/$defs/artifactRef"
    ):
        _fail("all-sealed-after-replay inventory array weakened")
    artifact_ref = _schema_node(schema, "$defs", "artifactRef")
    ref_fields = {"path", "sha256", "bytes", "data_class", "schema_id"}
    _assert_closed_object_schema(
        artifact_ref, required=ref_fields, properties=ref_fields,
        label="all-sealed-after-replay artifact ref schema",
    )
    if _schema_node(artifact_ref, "properties", "sha256").get("$ref") != "#/$defs/sha256":
        _fail("all-sealed-after-replay artifact hash binding weakened")


def _sanitized_registry_rows(
    registry: Mapping[str, Any],
) -> dict[str, tuple[str, str, Any]]:
    observations = registry.get("observations")
    actions = registry.get("actions")
    if not isinstance(observations, list) or not isinstance(actions, list):
        _fail("sanitized id/type/unit registry malformed")
    registry_rows: dict[str, tuple[str, str, Any]] = {}
    for row in observations:
        if not isinstance(row, Mapping) or set(row) != {"concept_id", "unit", "value_type"}:
            _fail("sanitized observation registry row malformed")
        concept_id = row["concept_id"]
        if (
            not isinstance(concept_id, str)
            or not concept_id
            or concept_id in registry_rows
            or row["value_type"] not in {"NUMBER", "BOOLEAN", "CATEGORICAL"}
            or row["unit"] not in EXPECTED_SANITIZED_UNITS
        ):
            _fail(f"sanitized observation registry id/type/unit invalid: {concept_id}")
        registry_rows[concept_id] = ("OBSERVATION", row["value_type"], row["unit"])
    for row in actions:
        if not isinstance(row, Mapping) or set(row) != {"action_id", "entity_type", "unit"}:
            _fail("sanitized action registry row malformed")
        action_id = row["action_id"]
        if (
            not isinstance(action_id, str)
            or not action_id
            or action_id in registry_rows
            or row["entity_type"] != "ACTION"
            or row["unit"] not in EXPECTED_SANITIZED_ACTION_DOSE_UNITS
        ):
            _fail(f"sanitized action registry id/type/unit invalid: {action_id}")
        registry_rows[action_id] = ("ACTION", "ACTION", row["unit"])
    return registry_rows


def _validate_sealed_concept_map_schema_structure(
    schema: Mapping[str, Any], registry: Mapping[str, Any]
) -> None:
    if schema.get("$id") != EXPECTED_DATA_CLASS_SCHEMA_IDS["sealed_concept_map"]:
        _fail("sealed concept map schema id mismatch")
    _assert_closed_object_schema(
        schema, required={"schema_version", "mappings"},
        properties={"schema_version", "mappings"}, label="sealed concept map schema",
    )
    mappings = _schema_node(schema, "properties", "mappings")
    if (
        mappings.get("type") != "array" or mappings.get("minItems") != 1
        or mappings.get("uniqueItems") is not True
        or _schema_node(mappings, "items").get("$ref") != "#/$defs/mapping"
    ):
        _fail("sealed concept map mappings schema weakened")
    mapping = _schema_node(schema, "$defs", "mapping")
    fields = {
        "opaque_source_concept_token", "mapped_id", "entity_type", "value_type",
        "unit", "mapping_status",
    }
    _assert_closed_object_schema(
        mapping, required=fields, properties=fields, label="sealed concept map mapping schema"
    )
    if _schema_node(mapping, "properties", "opaque_source_concept_token").get(
        "pattern"
    ) != "^SC-[0-9]{8}$":
        _fail("sealed concept map opaque source token weakened")
    expected_mapped_ids = sorted(_sanitized_registry_rows(registry))
    mapped_id = _schema_node(mapping, "properties", "mapped_id")
    if mapped_id.get("type") != "string" or mapped_id.get("enum") != expected_mapped_ids:
        _fail("sealed concept map mapped_id registry enum weakened")
    if _schema_node(mapping, "properties", "unit").get("enum") != EXPECTED_SANITIZED_UNITS:
        _fail("sealed concept map unit registry enum weakened")
    if _schema_node(mapping, "properties", "mapping_status").get("const") != "MAPPED":
        _fail("sealed concept map mapping status weakened")


def _validate_sanitized_ledger_against_map_and_registry(
    ledger: Mapping[str, Any], concept_map: Mapping[str, Any], registry: Mapping[str, Any],
    model_pack: Mapping[str, Any], combined_preprimary_seal: Mapping[str, Any],
) -> None:
    seal_payload_sha256 = combined_preprimary_seal.get("payload_sha256")
    if (
        not isinstance(seal_payload_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", seal_payload_sha256) is None
    ):
        _fail("combined pre-primary seal payload digest malformed")
    expected_run_id = f"RUN-{seal_payload_sha256}"
    if ledger.get("opaque_run_id") != expected_run_id:
        _fail("sanitized runtime ledger opaque run id is not derived from combined seal")

    registry_rows = _sanitized_registry_rows(registry)
    model_actions = model_pack.get("actions")
    if not isinstance(model_actions, list) or not model_actions:
        _fail("frozen model pack has no action registry")
    dose_reference_by_action: dict[str, float] = {}
    for row in model_actions:
        if not isinstance(row, Mapping) or not isinstance(row.get("action_id"), str):
            _fail("frozen model pack action row malformed")
        action_id = row["action_id"]
        if action_id in dose_reference_by_action:
            _fail(f"frozen model pack duplicates action id: {action_id}")
        try:
            dose_reference = float(row["dose_reference"])
        except (KeyError, TypeError, ValueError):
            _fail(f"frozen model pack action dose reference malformed: {action_id}")
        if not math.isfinite(dose_reference) or dose_reference <= 0:
            _fail(f"frozen model pack action dose reference invalid: {action_id}")
        dose_reference_by_action[action_id] = dose_reference

    mapping_by_token: dict[str, Mapping[str, Any]] = {}
    ordered_mapping_tokens: list[str] = []
    for mapping_index, row in enumerate(concept_map["mappings"], start=1):
        token = row["opaque_source_concept_token"]
        expected_token = f"SC-{mapping_index:08d}"
        if token != expected_token:
            _fail(
                "sealed concept map source tokens are not canonical one-based "
                f"mapper-row ids: expected {expected_token}, got {token}"
            )
        if token in mapping_by_token:
            _fail(f"sealed concept map duplicates opaque token: {token}")
        expected = registry_rows.get(row["mapped_id"])
        if expected is None or (row["entity_type"], row["value_type"], row["unit"]) != expected:
            _fail(f"sealed concept map row does not exactly bind sanitized registry: {token}")
        mapping_by_token[token] = row
        ordered_mapping_tokens.append(token)

    seen_event_ids: set[str] = set()
    ledger_source_tokens: set[str] = set()
    ordered_ledger_source_tokens: list[str] = []
    action_histories: dict[str, list[tuple[int, str]]] = {}
    action_bindings: dict[str, tuple[str, str]] = {}
    canonical_action_ids: dict[str, str] = {}
    canonical_alternative_group_ids: dict[str, str] = {}
    for event_index, event in enumerate(ledger["events"], start=1):
        event_id = event["opaque_event_id"]
        expected_event_id = f"EV-{event_index:08d}"
        if event_id != expected_event_id:
            _fail(
                "sanitized runtime event ids are not canonical one-based row ids: "
                f"expected {expected_event_id}, got {event_id}"
            )
        if event_id in seen_event_ids:
            _fail(f"sanitized runtime ledger duplicates opaque_event_id: {event_id}")
        seen_event_ids.add(event_id)
        token = event["opaque_source_concept_token"]
        if token not in ledger_source_tokens:
            ordered_ledger_source_tokens.append(token)
        ledger_source_tokens.add(token)
        mapping = mapping_by_token.get(token)
        if mapping is None:
            _fail(f"sanitized runtime event lacks a sealed concept mapping: {token}")
        expected_kind = mapping["entity_type"]
        if event["event_kind"] == "OBSERVATION" and expected_kind != "OBSERVATION":
            _fail(f"sanitized runtime observation maps to non-observation: {token}")
        if event["event_kind"] in {"ACTION", "SUPPORT"} and expected_kind != "ACTION":
            _fail(f"sanitized runtime action/support maps to non-action: {token}")
        if event["available_epoch_ordinal"] < event["observed_epoch_ordinal"]:
            _fail(f"sanitized runtime availability precedes observation: {token}")
        lifecycle = event.get("action_lifecycle")
        if event["event_kind"] == "OBSERVATION":
            if lifecycle is not None:
                _fail(f"sanitized runtime observation carries action lifecycle: {token}")
            qualification = event.get("evidence_qualification")
            if (
                not isinstance(qualification, Mapping)
                or set(qualification) != EXPECTED_EVIDENCE_QUALIFICATION_FIELDS
                or any(value not in EXPECTED_TRISTATE_VALUES for value in qualification.values())
            ):
                _fail(f"sanitized runtime observation evidence qualification invalid: {token}")
            alternative_group = event.get("alternative_representation_group_id")
            if alternative_group is not None and (
                not isinstance(alternative_group, str)
                or re.fullmatch(r"ARG-[0-9]{8}", alternative_group) is None
            ):
                _fail(f"sanitized runtime alternative representation group invalid: {token}")
            if alternative_group is not None:
                expected_group = canonical_alternative_group_ids.setdefault(
                    alternative_group,
                    f"ARG-{len(canonical_alternative_group_ids) + 1:08d}",
                )
                if alternative_group != expected_group:
                    _fail(
                        "sanitized runtime alternative group ids are not canonical "
                        f"first-occurrence ids: expected {expected_group}, got {alternative_group}"
                    )
        elif lifecycle is None:
            _fail(f"sanitized runtime action/support lacks action lifecycle: {token}")
        elif (
            "evidence_qualification" in event
            or "alternative_representation_group_id" in event
        ):
            _fail(f"sanitized runtime action/support carries observation qualification: {token}")
        if event["unit"] != mapping["unit"]:
            _fail(f"sanitized runtime unit differs from sealed registry mapping: {token}")
        typed = event["typed_value"]
        kind = typed["kind"]
        canonical = typed["canonical"]
        expected_value_kind = {
            "NUMBER": "NUMBER", "BOOLEAN": "BOOLEAN", "CATEGORICAL": "CODE", "ACTION": "CODE",
        }[mapping["value_type"]]
        if kind != "NULL" and kind != expected_value_kind:
            _fail(f"sanitized runtime value kind differs from registry: {token}")
        if kind == "NUMBER":
            try:
                numeric = float(canonical)
            except ValueError:
                _fail(f"sanitized runtime number is not numeric: {token}")
            if not math.isfinite(numeric):
                _fail(f"sanitized runtime number is not finite: {token}")
        elif kind == "BOOLEAN" and canonical not in {"true", "false"}:
            _fail(f"sanitized runtime boolean is not canonical: {token}")
        elif kind == "CODE" and canonical not in EXPECTED_CONTROLLED_VALUE_CODES:
            _fail(f"sanitized runtime categorical/action code is not controlled: {token}")
        elif kind == "NULL" and canonical != "null":
            _fail(f"sanitized runtime null is not canonical: {token}")
        if lifecycle is not None and (kind != "CODE" or canonical != lifecycle["phase"]):
            _fail(f"sanitized runtime action value/lifecycle phase mismatch: {token}")
        if lifecycle is not None:
            phase = lifecycle["phase"]
            if phase not in EXPECTED_ACTION_LIFECYCLE_PHASES:
                _fail(f"sanitized runtime author lifecycle phase is forbidden: {phase}")
            has_dose = "dose" in lifecycle
            has_dose_unit = "dose_unit" in lifecycle
            if phase in EXPECTED_ACTION_DOSE_PHASES:
                if not has_dose or not has_dose_unit:
                    _fail(f"sanitized runtime active action phase lacks dose/unit: {token}")
                dose = lifecycle["dose"]
                if dose.get("kind") != "NUMBER":
                    _fail(f"sanitized runtime action dose is not typed NUMBER: {token}")
                dose_canonical = dose.get("canonical")
                if (
                    not isinstance(dose_canonical, str)
                    or re.fullmatch(SANITIZED_NONNEGATIVE_NUMBER_PATTERN, dose_canonical) is None
                ):
                    _fail(f"sanitized runtime action dose is not canonical nonnegative: {token}")
                dose_number = float(dose_canonical)
                if not math.isfinite(dose_number) or dose_number < 0:
                    _fail(f"sanitized runtime action dose is not finite nonnegative: {token}")
                dose_reference = dose_reference_by_action.get(mapping["mapped_id"])
                if dose_reference is None or dose_number > dose_reference:
                    _fail(
                        f"sanitized runtime action dose exceeds frozen model reference: {token}"
                    )
                if lifecycle["dose_unit"] != mapping["unit"]:
                    _fail(f"sanitized runtime action dose unit differs from sealed registry: {token}")
            elif has_dose or has_dose_unit:
                _fail(f"sanitized runtime non-dosing phase carries dose/unit: {token}")
            action_id = lifecycle["opaque_action_id"]
            expected_action_id = canonical_action_ids.setdefault(
                action_id, f"ACT-{len(canonical_action_ids) + 1:08d}"
            )
            if action_id != expected_action_id:
                _fail(
                    "sanitized runtime action ids are not canonical first-occurrence ids: "
                    f"expected {expected_action_id}, got {action_id}"
                )
            binding = (mapping["mapped_id"], event["event_kind"])
            previous_binding = action_bindings.setdefault(action_id, binding)
            if previous_binding != binding:
                _fail(f"opaque action id changes mapped action or event kind: {action_id}")
            action_histories.setdefault(action_id, []).append(
                (event["observed_epoch_ordinal"], phase)
            )

    if ledger_source_tokens != set(ordered_mapping_tokens):
        _fail(
            "sealed concept map token inventory is not exactly the sanitized ledger token set: "
            f"missing={sorted(ledger_source_tokens-set(ordered_mapping_tokens))} "
            f"extra={sorted(set(ordered_mapping_tokens)-ledger_source_tokens)}"
        )
    if ordered_ledger_source_tokens != ordered_mapping_tokens:
        _fail(
            "sealed concept map token order does not equal canonical sanitized-ledger "
            "source-concept first-occurrence order"
        )

    legal_next = {
        "ORDERED": {"STARTED"},
        "STARTED": {"CONTINUED", "DOSE_CHANGED", "HELD", "STOPPED", "COMPLETED"},
        "CONTINUED": {"CONTINUED", "DOSE_CHANGED", "HELD", "STOPPED", "COMPLETED"},
        "DOSE_CHANGED": {"CONTINUED", "DOSE_CHANGED", "HELD", "STOPPED", "COMPLETED"},
        "HELD": {"RESUMED", "STOPPED", "COMPLETED"},
        "RESUMED": {"CONTINUED", "DOSE_CHANGED", "HELD", "STOPPED", "COMPLETED"},
        "STOPPED": set(),
        "COMPLETED": set(),
    }
    for action_id, history in action_histories.items():
        if history[0][1] not in {"ORDERED", "STARTED", "CONTINUED"}:
            _fail(f"opaque action lifecycle has no valid initial state: {action_id}")
        for (prior_epoch, prior_phase), (epoch, phase) in zip(history, history[1:]):
            if epoch < prior_epoch:
                _fail(f"opaque action lifecycle observed epoch regresses: {action_id}")
            if phase not in legal_next[prior_phase]:
                _fail(
                    f"opaque action lifecycle transition is illegal: "
                    f"{action_id}:{prior_phase}->{phase}"
                )


def _content_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: row[key] for key in ("path", "sha256", "bytes")}


def _typed_artifact_identity(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in ("path", "sha256", "bytes", "data_class", "schema_id")
    }


def _validate_external_sanitized_ledger_assignment_proof(
    study_root: Path,
    binding: Mapping[str, Any],
    *,
    role_inputs_by_class: Mapping[str, Mapping[str, Any]],
    sanitized_ledger: Mapping[str, Any],
    combined_inventory: Mapping[str, tuple[str, int]],
    combined_seal: Mapping[str, Any],
) -> Mapping[str, Any]:
    proof_schema = _load(
        study_root / SANITIZED_LEDGER_ASSIGNMENT_PROOF_SCHEMA_PATH,
        "sanitized-ledger assignment proof schema",
    )
    if proof_schema.get("$id") != (
        "ncf.evaluator-sanitized-runtime-ledger-assignment-proof.v1"
    ):
        _fail("sanitized-ledger assignment proof schema id mismatch")
    proof = _json_from_verified_bytes(
        binding["proof_payload"], "sanitized-ledger assignment proof"
    )
    _validate_schema_instance(proof, proof_schema)
    if proof.get("producer_id") != SANITIZED_LEDGER_COMPILER_PRODUCER_ID:
        _fail("sanitized-ledger assignment proof producer id mismatch")
    ledger_input = binding["input_artifact"]
    if PurePosixPath(str(ledger_input.get("path", ""))).name != (
        SANITIZED_LEDGER_LOGICAL_BASENAME
    ):
        _fail("evaluator sanitized ledger path does not use frozen logical basename")
    proof_ledger = proof.get("output_ledger")
    expected_logical_ledger = {
        "path": SANITIZED_LEDGER_LOGICAL_BASENAME,
        **{
            key: ledger_input[key]
            for key in ("sha256", "bytes", "data_class", "schema_id")
        },
    }
    if proof_ledger != expected_logical_ledger:
        _fail(
            "sanitized-ledger assignment proof does not bind the canonical logical "
            "ledger basename plus evaluator ledger content/type"
        )

    payload_sha256 = combined_seal.get("payload_sha256")
    if (
        proof.get("combined_preprimary_seal_payload_sha256") != payload_sha256
        or proof.get("opaque_run_id") != f"RUN-{payload_sha256}"
        or proof.get("opaque_run_id") != sanitized_ledger.get("opaque_run_id")
    ):
        _fail("sanitized-ledger assignment proof combined-seal/run binding mismatch")

    expected_algorithm = {
        "run_id": "RUN_PREFIX_PLUS_FULL_COMBINED_PREPRIMARY_PAYLOAD_SHA256",
        "event_id": "CANONICAL_LEDGER_ROW_ORDER_DECIMAL8_START1",
        "source_concept_id": "CANONICAL_LEDGER_FIRST_OCCURRENCE_DECIMAL8_START1",
        "action_id": "CANONICAL_LEDGER_FIRST_OCCURRENCE_DECIMAL8_START1",
        "alternative_group_id": "CANONICAL_LEDGER_FIRST_OCCURRENCE_DECIMAL8_START1",
    }
    if proof.get("assignment_algorithm") != expected_algorithm:
        _fail("sanitized-ledger assignment proof algorithm mismatch")

    source_tokens: set[str] = set()
    action_ids: set[str] = set()
    alternative_groups: set[str] = set()
    digest_events: list[dict[str, Any]] = []
    for event in sanitized_ledger["events"]:
        source_tokens.add(event["opaque_source_concept_token"])
        lifecycle = event.get("action_lifecycle")
        action_id = lifecycle.get("opaque_action_id") if isinstance(lifecycle, Mapping) else None
        if action_id is not None:
            action_ids.add(action_id)
        alternative_group = event.get("alternative_representation_group_id")
        if alternative_group is not None:
            alternative_groups.add(alternative_group)
        digest_events.append(
            {
                "opaque_event_id": event["opaque_event_id"],
                "opaque_source_concept_token": event["opaque_source_concept_token"],
                "opaque_action_id": action_id,
                "alternative_representation_group_id": alternative_group,
            }
        )
    expected_counts = {
        "events": len(sanitized_ledger["events"]),
        "source_concepts": len(source_tokens),
        "actions": len(action_ids),
        "alternative_groups": len(alternative_groups),
    }
    if proof.get("assignment_counts") != expected_counts:
        _fail("sanitized-ledger assignment proof counts mismatch")
    expected_digest = _canonical_json_sha256(
        {"opaque_run_id": sanitized_ledger["opaque_run_id"], "events": digest_events}
    )
    if proof.get("assignment_digest") != expected_digest:
        _fail("sanitized-ledger assignment proof digest mismatch")

    expected_input_slots = [
        "sealed_event_ledger",
        "sealed_availability_ledger",
        "sealed_concept_map",
        "sanitized_id_type_unit_registry",
        "combined_preprimary_seal",
    ]
    proof_inputs = proof.get("inputs")
    if (
        not isinstance(proof_inputs, list)
        or [row.get("slot") for row in proof_inputs] != expected_input_slots
    ):
        _fail("sanitized-ledger assignment proof input slots/order mismatch")
    expected_schema_ids = {
        "sealed_event_ledger": "ncf.data.sealed-event-ledger.v1",
        "sealed_availability_ledger": "ncf.data.sealed-availability-ledger.v1",
        "sealed_concept_map": "ncf.data.sealed-concept-map.v1",
        "sanitized_id_type_unit_registry": "ncf.data.sanitized-id-type-unit-registry.v1",
        "combined_preprimary_seal": "ncf.data.combined-preprimary-seal.v1",
    }
    proof_inputs_by_slot: dict[str, Mapping[str, Any]] = {}
    for row in proof_inputs:
        slot = row["slot"]
        if row.get("data_class") != slot or row.get("schema_id") != expected_schema_ids[slot]:
            _fail(f"sanitized-ledger assignment proof input typing mismatch: {slot}")
        _canonical_artifact_bytes(
            study_root, row, f"sanitized-ledger compiler proof input {slot}"
        )
        proof_inputs_by_slot[slot] = row
    for direct_slot in (
        "sealed_concept_map",
        "sanitized_id_type_unit_registry",
        "combined_preprimary_seal",
    ):
        direct = role_inputs_by_class.get(direct_slot)
        if direct is None or _typed_artifact_identity(proof_inputs_by_slot[direct_slot]) != (
            _typed_artifact_identity(direct)
        ):
            _fail(
                "sanitized-ledger assignment proof does not bind evaluator direct input: "
                f"{direct_slot}"
            )

    manifest_ref = proof.get("input_manifest")
    manifest_rel, manifest_payload = _validate_lineage_ref(
        study_root, manifest_ref, "sanitized-ledger compiler input manifest"
    )
    compiler_input_schema = _load(
        study_root / SANITIZED_LEDGER_COMPILER_INPUT_SCHEMA_PATH,
        "sanitized-ledger compiler input schema",
    )
    if compiler_input_schema.get("$id") != (
        "ncf.evaluator-sanitized-runtime-ledger-compiler-input.v1"
    ):
        _fail("sanitized-ledger compiler input schema id mismatch")
    compiler_manifest = _json_from_verified_bytes(
        manifest_payload, "sanitized-ledger compiler input manifest"
    )
    _validate_schema_instance(compiler_manifest, compiler_input_schema)
    manifest_inputs = compiler_manifest.get("inputs")
    if not isinstance(manifest_inputs, Mapping) or list(manifest_inputs) != expected_input_slots:
        _fail("sanitized-ledger compiler input manifest slots/order mismatch")
    for slot in expected_input_slots:
        if _typed_artifact_identity(manifest_inputs[slot]) != _typed_artifact_identity(
            proof_inputs_by_slot[slot]
        ):
            _fail(f"sanitized-ledger proof/manifest input mismatch: {slot}")

    expected_assets = [
        ("compiler", SANITIZED_LEDGER_COMPILER_PATH),
        ("compiler_test", SANITIZED_LEDGER_COMPILER_TEST_PATH),
        ("compiler_input_schema", SANITIZED_LEDGER_COMPILER_INPUT_SCHEMA_PATH),
        ("ledger_output_schema", SANITIZED_RUNTIME_SCHEMA_PATH),
        ("assignment_proof_schema", SANITIZED_LEDGER_ASSIGNMENT_PROOF_SCHEMA_PATH),
    ]
    frozen_assets = proof.get("frozen_assets")
    if (
        not isinstance(frozen_assets, list)
        or [(row.get("asset_role"), row.get("path")) for row in frozen_assets]
        != expected_assets
    ):
        _fail("sanitized-ledger assignment proof frozen asset set/order mismatch")
    for row in frozen_assets:
        rel, _, payload = _canonical_artifact_bytes(
            study_root, row, f"sanitized-ledger frozen asset {row['asset_role']}"
        )
        expected_identity = combined_inventory.get(rel)
        if expected_identity != (hashlib.sha256(payload).hexdigest(), len(payload)):
            _fail(
                "sanitized-ledger assignment proof asset absent from combined seal: "
                f"{rel}"
            )

    occupied_paths = {
        row["path"] for row in proof_inputs
    } | {ledger_input["path"], binding["proof_path"]}
    if manifest_rel in occupied_paths:
        _fail("sanitized-ledger compiler input manifest path overlaps an input/output/proof")
    return proof


def _validate_external_sanitized_ledger_replay_verification(
    study_root: Path,
    binding: Mapping[str, Any],
    *,
    assignment_proof: Mapping[str, Any],
    role_inputs_by_class: Mapping[str, Mapping[str, Any]],
    combined_inventory: Mapping[str, tuple[str, int]],
    combined_seal: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Fresh-replay the frozen compiler and require an exact cited verification.

    ``assignment_proof`` deliberately carries a logical output basename so that
    it is byte-reproducible in an isolated replay directory.  The independent
    verification artifact binds that logical proof to the evaluator's actual
    ledger path and then re-executes the exact compiler in a fresh subprocess.
    It is lineage metadata inspected by this validator, not clinical input made
    visible to the evaluator role.
    """

    schema_path = study_root / SANITIZED_LEDGER_REPLAY_VERIFICATION_SCHEMA_PATH
    verification_schema = _load(
        schema_path, "sanitized-ledger replay verification schema"
    )
    if verification_schema.get("$id") != (
        "ncf.evaluator-sanitized-runtime-ledger-replay-verification.v1"
    ):
        _fail("sanitized-ledger replay verification schema id mismatch")
    verification = _json_from_verified_bytes(
        binding["verification_payload"],
        "sanitized-ledger replay verification",
    )
    _validate_schema_instance(verification, verification_schema)

    ledger_input = role_inputs_by_class["evaluator_sanitized_runtime_ledger"]
    proof_ref = binding["producer"]["assignment_proof"]
    expected_ledger_ref = _content_identity(ledger_input)
    expected_proof_ref = _content_identity(proof_ref)
    if verification.get("compiler_outputs") != {
        "ledger": expected_ledger_ref,
        "assignment_proof": expected_proof_ref,
    }:
        _fail(
            "sanitized-ledger replay verification does not bind exact evaluator "
            "ledger and assignment proof paths/content"
        )
    if verification.get("compiler_input_manifest") != assignment_proof.get(
        "input_manifest"
    ):
        _fail(
            "sanitized-ledger replay verification does not bind exact compiler manifest"
        )
    if verification.get("combined_preprimary_seal_payload_sha256") != (
        combined_seal.get("payload_sha256")
    ):
        _fail("sanitized-ledger replay verification combined-seal binding mismatch")

    # The verification schema and executable/test surface are themselves part
    # of the pre-primary seal.  Do not accept a post-seal verifier or schema
    # merely because it can emit a syntactically plausible PASS document.
    for rel, label in (
        (
            SANITIZED_LEDGER_REPLAY_VERIFICATION_SCHEMA_PATH,
            "sanitized-ledger replay verification schema",
        ),
        (SANITIZED_LEDGER_REPLAY_VERIFIER_PATH, "sanitized-ledger replay verifier"),
        (
            SANITIZED_LEDGER_REPLAY_VERIFIER_TEST_PATH,
            "sanitized-ledger replay verifier test",
        ),
    ):
        _, _, payload = _canonical_path_bytes(study_root, rel, label)
        if combined_inventory.get(rel) != (
            hashlib.sha256(payload).hexdigest(), len(payload)
        ):
            _fail(f"{label} is absent from the bound combined pre-primary seal")

    manifest_path = study_root.joinpath(
        *PurePosixPath(assignment_proof["input_manifest"]["path"]).parts
    )
    ledger_path = study_root.joinpath(*PurePosixPath(ledger_input["path"]).parts)
    proof_path = study_root.joinpath(*PurePosixPath(binding["proof_path"]).parts)
    combined_seal_input = role_inputs_by_class["combined_preprimary_seal"]
    combined_seal_path = study_root.joinpath(
        *PurePosixPath(combined_seal_input["path"]).parts
    )
    try:
        # Import locally so the preflight/role contract can still be parsed as
        # a static module.  build_verification executes the compiler in a fresh
        # subprocess and performs exact-byte + canonical-JSON comparison of
        # both ledger and proof outputs.
        from verify_evaluator_sanitized_runtime_ledger import (  # type: ignore
            build_verification,
        )

        freshly_verified = build_verification(
            study_root,
            manifest_path=manifest_path,
            ledger_path=ledger_path,
            assignment_proof_path=proof_path,
            combined_seal_path=combined_seal_path,
        )
    except (ImportError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        _fail(f"sanitized-ledger compiler exact fresh replay failed: {exc}")
    if _canonical_json_bytes(verification) != _canonical_json_bytes(freshly_verified):
        _fail(
            "sanitized-ledger replay verification is forged, stale, or not the "
            "exact fresh-replay result"
        )
    return verification


def _validate_role_policy_contract(
    protocol: Mapping[str, Any],
    role_schema: Mapping[str, Any],
    aggregate_schema: Mapping[str, Any],
    trace_schema: Mapping[str, Any],
) -> None:
    _validate_role_schema_structure(role_schema, aggregate_schema, trace_schema)
    if role_schema.get("$id") != "ncf.primary-role-execution-manifest.v1.1":
        _fail("role manifest schema id mismatch")
    if aggregate_schema.get("$id") != "ncf.primary-role-manifest-set.v1":
        _fail("role manifest set schema id mismatch")
    role_enum = role_schema.get("$defs", {}).get("role", {}).get("enum")
    aggregate_role_enum = aggregate_schema.get("$defs", {}).get("role", {}).get("enum")
    if role_enum != EXPECTED_ROLES or aggregate_role_enum != EXPECTED_ROLES:
        _fail("role schemas do not contain the exact required role set")
    required_manifest_fields = {
        "schema_version", "role", "run_id", "started_at", "finished_at",
        "case_identity_exposed", "inputs", "outputs", "observed_data_classes",
        "attestations", "prompt_or_command", "tool_trace", "parent_packet",
    }
    if set(role_schema.get("required", [])) != required_manifest_fields:
        _fail("role manifest schema required fields mismatch")
    if role_schema.get("additionalProperties") is not False:
        _fail("role manifest schema must reject additional properties")
    if role_schema.get("properties", {}).get("schema_version", {}).get("const") != "NCF-PRIMARY-ROLE-MANIFEST-1.1.0":
        _fail("role manifest schema version mismatch")
    if aggregate_schema.get("properties", {}).get("schema_version", {}).get("const") != "NCF-PRIMARY-ROLE-MANIFEST-SET-1.0.0":
        _fail("role manifest set schema version mismatch")
    aggregate_items = aggregate_schema.get("properties", {}).get("manifests", {})
    if aggregate_items.get("minItems") != len(EXPECTED_ROLES) or aggregate_items.get("maxItems") != len(EXPECTED_ROLES):
        _fail("role manifest set schema must require one entry per exact role")

    roles = protocol.get("roles")
    if not isinstance(roles, Mapping) or list(roles) != EXPECTED_ROLES:
        _fail("execution protocol roles must be the exact frozen ordered role set")
    policy_keys = {
        "allowed_input_data_classes", "allowed_output_data_classes",
        "forbidden_data_classes", "case_identity_exposure", "network_access_policy",
    }
    produced_by: dict[str, str] = {}
    all_allowed_classes: set[str] = set()
    for role in EXPECTED_ROLES:
        policy = roles.get(role)
        if not isinstance(policy, Mapping) or set(policy) != policy_keys:
            _fail(f"role policy fields mismatch: {role}")
        if dict(policy) != EXPECTED_ROLE_POLICIES[role]:
            _fail(f"role policy differs from frozen exact policy: {role}")
        parsed: dict[str, list[str]] = {}
        for key in ("allowed_input_data_classes", "allowed_output_data_classes", "forbidden_data_classes"):
            values = policy.get(key)
            if not isinstance(values, list) or not values or any(not isinstance(item, str) or not item for item in values):
                _fail(f"role {role} {key} must be a non-empty string list")
            if len(values) != len(set(values)):
                _fail(f"role {role} {key} must be unique")
            parsed[key] = values
        if set(parsed["allowed_input_data_classes"]) & set(parsed["forbidden_data_classes"]):
            _fail(f"role {role} has input/forbidden class overlap")
        if set(parsed["allowed_output_data_classes"]) & set(parsed["forbidden_data_classes"]):
            _fail(f"role {role} has output/forbidden class overlap")
        if policy.get("case_identity_exposure") not in {"FORBIDDEN", "PERMITTED"}:
            _fail(f"role {role} case identity exposure policy invalid")
        expected_network_policy = (
            "REQUIRED_NCBI_HTTPS_GET_ONLY" if role == "scout" else "FORBIDDEN"
        )
        if policy.get("network_access_policy") != expected_network_policy:
            _fail(f"role {role} network access policy invalid")
        all_allowed_classes.update(parsed["allowed_input_data_classes"])
        all_allowed_classes.update(parsed["allowed_output_data_classes"])
        for data_class in parsed["allowed_output_data_classes"]:
            if data_class in produced_by:
                _fail(f"data class has multiple producer roles: {data_class}")
            produced_by[data_class] = role

    contract = protocol.get("role_manifest")
    if not isinstance(contract, Mapping):
        _fail("role_manifest contract missing")
    required_contract_values = {
        "schema_version": "NCF-PRIMARY-ROLE-MANIFEST-1.1.0",
        "schema_id": "ncf.primary-role-execution-manifest.v1.1",
        "aggregate_schema_version": "NCF-PRIMARY-ROLE-MANIFEST-SET-1.0.0",
        "aggregate_schema_id": "ncf.primary-role-manifest-set.v1",
        "required_roles": EXPECTED_ROLES,
        "required_for_every_role": True,
        "exact_input_output_paths_sha256_bytes_and_schema_id": True,
        "observed_data_classes_must_equal_input_data_classes": True,
        "case_identity_exposure_policy_enforced": True,
        "forbidden_access_attestations": True,
        "canonical_relative_in_root_non_symlink_paths_only": True,
        "input_output_path_overlap_forbidden": True,
        "content_addressed_prompt_command_tool_trace_and_parent_packet_required": True,
        "structured_tool_access_trace_required": True,
        "tool_access_trace_schema_version": ROLE_TRACE_SCHEMA_VERSION,
        "tool_access_trace_schema_id": ROLE_TRACE_SCHEMA_ID,
        "observed_access_must_be_mechanically_derived_from_trace": True,
        "role_specific_network_access_must_be_mechanically_traced": True,
        "all_allowed_input_output_data_classes_required_exactly_once": True,
        "presealed_root_inputs_must_bind_exact_combined_seal_artifacts": True,
        "producer_consumer_exact_output_input_binding_required": True,
        "complete_manifest_set_and_acyclic_dag_required": True,
        "nonterminal_outputs_must_be_consumed_or_exactly_packaged": True,
        "evaluator_identity_forbidden_and_sanitized_runtime_ledger_required": True,
        "sealed_executable_output_producer_proof_required": True,
        "all_sealed_after_replay_inventory_schema_id": EXPECTED_DATA_CLASS_SCHEMA_IDS[
            "all_sealed_artifacts_after_replay"
        ],
        "source_authored_action_lifecycle_phases": EXPECTED_ACTION_LIFECYCLE_PHASES,
        "source_authored_washout_forbidden": True,
        "washout_must_be_derived_by_frozen_runtime": True,
        "action_result_must_be_separate_observation": True,
        "action_dose_semantics": "NORMALIZED_INTENSITY_ZERO_TO_MODEL_DOSE_REFERENCE",
        "clinical_free_text_dose_units_forbidden": True,
        "observation_evidence_qualification_required": True,
        "support_masking_must_be_derived_by_frozen_runtime": True,
        "shared_filesystem_is_not_os_enforced_isolation": True,
        "missing_prompt_tool_or_input_lineage_verdict": "HARNESS_INCOMPLETE",
    }
    for key, expected in required_contract_values.items():
        if contract.get(key) != expected:
            _fail(f"role_manifest contract mismatch: {key}")
    roots = contract.get("presealed_root_data_classes")
    if (
        not isinstance(roots, list)
        or roots != list(EXPECTED_PRESEALED_ROOT_ASSET_PATHS)
        or any(item not in all_allowed_classes for item in roots)
    ):
        _fail("role_manifest presealed_root_data_classes invalid")
    if contract.get("presealed_root_asset_paths") != EXPECTED_PRESEALED_ROOT_ASSET_PATHS:
        _fail("role_manifest presealed_root_asset_paths differs from frozen exact binding")
    schema_ids = contract.get("data_class_schema_ids")
    if not isinstance(schema_ids, Mapping) or set(schema_ids) != all_allowed_classes:
        _fail("role_manifest data_class_schema_ids must exactly cover allowed input/output classes")
    if dict(schema_ids) != EXPECTED_DATA_CLASS_SCHEMA_IDS:
        _fail("role_manifest data_class_schema_ids differ from frozen exact schema bindings")

    edge_rows = contract.get("producer_consumer_edges")
    if edge_rows != EXPECTED_PRODUCER_CONSUMER_EDGES:
        _fail("role_manifest producer_consumer_edges differ from frozen exact DAG")
    if not isinstance(edge_rows, list) or not edge_rows:
        _fail("role_manifest producer_consumer_edges missing")
    external_edge_rows = contract.get("external_producer_edges")
    if external_edge_rows != EXPECTED_EXTERNAL_PRODUCER_EDGES:
        _fail("role_manifest external_producer_edges differ from frozen exact contract")
    external_input_keys = {
        (consumer, row["data_class"])
        for row in EXPECTED_EXTERNAL_PRODUCER_EDGES
        for consumer in row["consumer_roles"]
    }
    seen_edge_classes: set[tuple[str, str, str]] = set()
    graph_edges: list[tuple[str, str]] = []
    for row in edge_rows:
        if not isinstance(row, Mapping) or set(row) != {"producer_role", "data_class", "consumer_roles"}:
            _fail("producer_consumer edge malformed")
        producer = row.get("producer_role")
        data_class = row.get("data_class")
        consumers = row.get("consumer_roles")
        if producer not in EXPECTED_ROLES or produced_by.get(data_class) != producer:
            _fail(f"producer_consumer edge has wrong producer: {data_class}")
        if not isinstance(consumers, list) or not consumers or len(consumers) != len(set(consumers)):
            _fail(f"producer_consumer edge consumers invalid: {data_class}")
        for consumer in consumers:
            if consumer not in EXPECTED_ROLES or data_class not in roles[consumer]["allowed_input_data_classes"]:
                _fail(f"producer_consumer edge has invalid consumer: {producer}->{consumer}:{data_class}")
            key = (producer, consumer, data_class)
            if key in seen_edge_classes:
                _fail(f"duplicate producer_consumer edge: {key}")
            seen_edge_classes.add(key)
            graph_edges.append((producer, consumer))
    # Every non-root allowed input must have exactly one declared upstream edge.
    for consumer in EXPECTED_ROLES:
        for data_class in roles[consumer]["allowed_input_data_classes"]:
            if data_class in roots:
                continue
            if (consumer, data_class) in external_input_keys:
                continue
            matching = [key for key in seen_edge_classes if key[1] == consumer and key[2] == data_class]
            if len(matching) != 1:
                _fail(f"non-root input lacks exactly one producer edge: {consumer}:{data_class}")
    edge_output_classes = {(producer, data_class) for producer, _, data_class in seen_edge_classes}
    terminal_outputs = {
        ("scorer_auditor", data_class)
        for data_class in roles["scorer_auditor"]["allowed_output_data_classes"]
    }
    packaged_outputs = {
        ("evaluator", data_class) for data_class in EXPECTED_PACKAGED_EVALUATOR_OUTPUTS
    }
    for producer in EXPECTED_ROLES:
        for data_class in roles[producer]["allowed_output_data_classes"]:
            key = (producer, data_class)
            if key not in edge_output_classes | terminal_outputs | packaged_outputs:
                _fail(f"role output is orphaned from the frozen DAG/package: {producer}:{data_class}")
    _assert_acyclic_roles(graph_edges)


def _wire_identifiability(schema: Mapping[str, Any]) -> list[str]:
    try:
        values = schema["$defs"]["identifiabilityClaim"]["properties"]["status"]["enum"]
    except (KeyError, TypeError):
        _fail("architecture schema has no identifiabilityClaim.status.enum")
    if not isinstance(values, list) or any(not isinstance(item, str) for item in values):
        _fail("architecture identifiability enum invalid")
    return values


def validate_preprimary_contracts(study_root: Path) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    holdout = root / "holdout"
    architecture = _load(root / "architecture_final_v1.schema.json", "architecture schema")
    gates = _load(holdout / "PERFECT_LANDING_GATES.json", "gate contract")
    gate_seal = _load(holdout / "PERFECT_LANDING_GATES.seal.json", "gate seal")
    protocol = _load(holdout / "PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json", "execution protocol")
    scoring = _load(holdout / "PRIMARY_HOLDOUT_SCORING_v1.json", "scoring contract")
    role_schema = _load(holdout / "schemas/primary_role_execution_manifest.schema.json", "role schema")
    role_set_schema = _load(holdout / "schemas/primary_role_manifest_set.schema.json", "role manifest set schema")
    role_trace_schema = _load(
        holdout / "schemas/primary_role_tool_access_trace.schema.json", "role tool access trace schema"
    )
    sanitized_runtime_schema = _load(
        root / SANITIZED_RUNTIME_SCHEMA_PATH, "evaluator sanitized runtime ledger schema"
    )
    sanitized_ledger_compiler_input_schema = _load(
        root / SANITIZED_LEDGER_COMPILER_INPUT_SCHEMA_PATH,
        "evaluator sanitized runtime ledger compiler input schema",
    )
    sanitized_ledger_assignment_proof_schema = _load(
        root / SANITIZED_LEDGER_ASSIGNMENT_PROOF_SCHEMA_PATH,
        "evaluator sanitized runtime ledger assignment proof schema",
    )
    sanitized_ledger_replay_verification_schema = _load(
        root / SANITIZED_LEDGER_REPLAY_VERIFICATION_SCHEMA_PATH,
        "evaluator sanitized runtime ledger replay verification schema",
    )
    all_sealed_replay_schema = _load(
        root / ALL_SEALED_REPLAY_SCHEMA_PATH, "all-sealed-after-replay schema"
    )
    sealed_concept_map_schema = _load(
        root / SEALED_CONCEPT_MAP_SCHEMA_PATH, "sealed concept map schema"
    )
    mapper_registry = _load(
        root / EXPECTED_PRESEALED_ROOT_ASSET_PATHS["sanitized_id_type_unit_registry"],
        "sanitized id/type/unit registry",
    )
    search_schema = _load(holdout / "schemas/primary_case_search_snapshot.schema.json", "search schema")
    raw_search_schema = _load(
        holdout / "schemas/primary_raw_search_response.schema.json", "raw search response schema"
    )
    raw_search_retrieval_schema = _load(
        holdout / "schemas/primary_search_retrieval_manifest.schema.json",
        "raw search retrieval manifest schema",
    )
    screening_schema = _load(holdout / "schemas/primary_case_screening.schema.json", "screening schema")
    screening_evidence_schema = _load(
        holdout / "schemas/primary_screening_evidence.schema.json",
        "screening evidence schema",
    )
    complexity_claims_schema = _load(
        holdout / "schemas/primary_opaque_concurrent_process_candidate_claims.schema.json",
        "opaque concurrent-process claims schema",
    )
    complexity_packet_schema = _load(
        holdout / "schemas/primary_opaque_concurrent_process_candidate_packet.schema.json",
        "opaque concurrent-process packet schema",
    )
    sealed_complexity_packet_schema = _load(
        holdout / "schemas/primary_sealed_opaque_concurrent_process_candidate_packet.schema.json",
        "sealed opaque concurrent-process packet schema",
    )
    mapped_observation_schema = _load(
        holdout / "schemas/mapped_observation_consumption.schema.json",
        "mapped observation consumption schema",
    )
    runtime_replay_input_schema = _load(
        holdout / "schemas/primary_runtime_replay_input_manifest.schema.json",
        "primary runtime replay input manifest schema",
    )
    runtime_output_schema = _load(
        holdout / "schemas/primary_runtime_output.schema.json",
        "primary runtime output schema",
    )
    runtime_replay_seal_schema = _load(
        holdout / "schemas/primary_runtime_replay_seal.schema.json",
        "primary runtime replay seal schema",
    )
    final_result_schema = _load(
        holdout / "schemas/primary_holdout_final_result.schema.json",
        "final holdout result schema",
    )
    gate_evidence_schema = _load(
        holdout / "schemas/primary_gate_evidence.schema.json",
        "gate evidence schema",
    )
    availability_schema = _load(
        holdout / "schemas/primary_availability_ledger.schema.json",
        "availability ledger schema",
    )
    structural_gate_evidence_schema = _load(
        holdout / "tools/structural_gate_evidence.schema.json",
        "structural gate evidence schema",
    )
    structural_gate_results_schema = _load(
        holdout / "tools/structural_gate_results.schema.json",
        "structural gate results schema",
    )

    wire_enum = _wire_identifiability(architecture)
    gate_enum = gates.get("identifiability_enum")
    if wire_enum != EXPECTED_IDENTIFIABILITY or gate_enum != wire_enum:
        _fail(f"gate identifiability enum does not exactly match wire: gate={gate_enum}, wire={wire_enum}")
    if gates.get("contract_version") != "1.1.0":
        _fail("gate contract must be corrected version 1.1.0")
    artifacts = gate_seal.get("artifacts")
    if not isinstance(artifacts, list):
        _fail("gate seal artifacts missing")
    expected_gate_hashes = {
        "PERFECT_LANDING_GATES.md": _sha(holdout / "PERFECT_LANDING_GATES.md"),
        "PERFECT_LANDING_GATES.json": _sha(holdout / "PERFECT_LANDING_GATES.json"),
        "../ARCHITECTURE_FINAL_v1.md": _sha(root / "ARCHITECTURE_FINAL_v1.md"),
        "../architecture_final_v1.schema.json": _sha(root / "architecture_final_v1.schema.json"),
    }
    sealed = {row.get("path"): row.get("sha256") for row in artifacts if isinstance(row, Mapping)}
    if any(sealed.get(path) != digest for path, digest in expected_gate_hashes.items()):
        _fail("gate seal does not bind current gate/architecture bytes")

    if protocol.get("status") != "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION":
        _fail("execution protocol status is not frozen")
    if protocol.get("protocol_version") != "1.1.0" or protocol.get("gate_contract_version") != "1.1.0":
        _fail("execution protocol version/binding mismatch")
    required_bindings = protocol.get("required_preprimary_bindings")
    required_selection_chain = {
        "preprimary_combined_seal_tool",
        "preprimary_combined_seal_test_source",
        "selection_tool",
        "selection_tool_test_source",
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
        "protocol_validator_test_source",
        "role_manifest_schema",
        "role_manifest_set_schema",
        "role_tool_access_trace_schema",
        "evaluator_sanitized_runtime_ledger_schema",
        "evaluator_sanitized_runtime_ledger_compiler_tool",
        "evaluator_sanitized_runtime_ledger_compiler_test_source",
        "evaluator_sanitized_runtime_ledger_compiler_input_schema",
        "evaluator_sanitized_runtime_ledger_compiler_output_schema",
        "evaluator_sanitized_runtime_ledger_assignment_proof_schema",
        "evaluator_sanitized_runtime_ledger_replay_verifier_tool",
        "evaluator_sanitized_runtime_ledger_replay_verifier_test_source",
        "evaluator_sanitized_runtime_ledger_replay_verifier_output_schema",
        "all_sealed_artifacts_after_replay_schema",
        "sealed_concept_map_schema",
        "search_snapshot_schema",
        "event_ledger_replay_tool",
        "event_ledger_replay_test_source",
        "structural_gate_harness_tool",
        "structural_gate_harness_test_source",
        "structural_gate_evidence_schema",
        "structural_gate_results_schema",
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
    }
    if (
        not isinstance(required_bindings, list)
        or len(required_bindings) != len(set(required_bindings))
        or not required_selection_chain.issubset(set(required_bindings))
    ):
        _fail("required_preprimary_bindings omit a selection-chain asset")
    selection = protocol.get("selection")
    if not isinstance(selection, Mapping) or selection.get("minimum_eligible_candidates") != 3:
        _fail("execution protocol minimum eligible candidates must be 3")
    eligibility = selection.get("eligibility")
    if (
        not isinstance(eligibility, Mapping)
        or eligibility.get("minimum_concurrent_process_target_candidates") != 2
    ):
        _fail("selection must require at least two concurrent process target candidates")
    complexity = selection.get("opaque_concurrent_process_candidate_contract")
    required_complexity = {
        "minimum_required_target_count": 2,
        "model_blind": True,
        "disease_name_blind": True,
        "same_preterminal_epoch_coactivity_required": True,
        "independent_source_assertion_per_target_required": True,
        "minimum_temporally_separated_source_witnesses_per_target": 2,
        "trackable_trajectory_per_target_required": True,
        "duplicate_observations_of_same_process_count_once": True,
        "claims_schema": "holdout/schemas/primary_opaque_concurrent_process_candidate_claims.schema.json",
        "packet_schema": "holdout/schemas/primary_opaque_concurrent_process_candidate_packet.schema.json",
        "sealed_packet_schema": "holdout/schemas/primary_sealed_opaque_concurrent_process_candidate_packet.schema.json",
        "compiler_validator": "holdout/tools/compile_opaque_concurrent_process_candidates.py",
        "test_source": "holdout/tools/test_compile_opaque_concurrent_process_candidates.py",
        "raw_data_class": "opaque_concurrent_process_candidate_packet",
        "sealed_data_class": "sealed_opaque_concurrent_process_candidate_packet",
        "evaluator_access": "FORBIDDEN",
        "disallowed_compiler_inputs": [
            "model_pack", "runtime", "runtime_output", "oracle_contents",
            "expected_diagnosis", "terminal_outcome", "scoring_output",
        ],
        "insufficient_target_count_effect": "CASE_INELIGIBLE",
    }
    if not isinstance(complexity, Mapping) or dict(complexity) != required_complexity:
        _fail("opaque concurrent-process candidate contract mismatch")
    queries = selection.get("queries")
    if not isinstance(queries, list) or [row.get("query_id") for row in queries] != ["Q1", "Q2"]:
        _fail("execution protocol must contain exactly frozen Q1/Q2")
    if selection.get("manual_skip_or_substitution_forbidden") is not True:
        _fail("manual selection override must be forbidden")
    expected_preimage = (
        "NCF-PRIMARY-SELECTION-v1 + newline + frozen_query_contract_sha256 + "
        "newline + raw_ordered_identifier_projection_sha256 + newline + "
        "canonical_eligible_id_set_sha256 + newline + canonical_case_id"
    )
    if (
        selection.get("selection_digest_preimage") != expected_preimage
        or selection.get("selection_hash_excludes_executor_metadata") is not True
    ):
        _fail("selection digest admits executor-controlled metadata grinding")
    raw_search = selection.get("raw_search_validation")
    required_raw_search = {
        "raw_response_schema": "holdout/schemas/primary_raw_search_response.schema.json",
        "retrieval_manifest_schema": "holdout/schemas/primary_search_retrieval_manifest.schema.json",
        "snapshot_schema": "holdout/schemas/primary_case_search_snapshot.schema.json",
        "executable": "holdout/tools/validate_primary_search_snapshot.py",
        "test_source": "holdout/tools/test_validate_primary_search_snapshot.py",
        "compiler": "holdout/tools/compile_primary_search_snapshot.py",
        "compiler_test_source": "holdout/tools/test_compile_primary_search_snapshot.py",
        "compiler_network_access": False,
        "provider": "NCBI_PUBMED_ESEARCH_JSON",
        "raw_path_prefix": "holdout/evidence/primary_search_raw/",
        "raw_payload_path_prefix": "holdout/evidence/primary_search_raw/payloads/",
        "request_url_policy": "canonical HTTPS NCBI ESearch URL; fixed parameter order; RFC3986 percent-encoding",
        "retrieved_count_must_equal_idlist_length": True,
        "ordered_case_ids_projection": "PMID:<idlist item>, exact source order",
        "raw_hash_mismatch_or_incomplete_page_verdict": "HARNESS_INCOMPLETE",
    }
    if not isinstance(raw_search, Mapping):
        _fail("raw search validation contract missing")
    for key, expected in required_raw_search.items():
        if raw_search.get(key) != expected:
            _fail(f"raw search validation contract mismatch: {key}")
    source = protocol.get("source_contract")
    if not isinstance(source, Mapping) or source.get("nonmention_semantics") != "UNKNOWN_NEVER_NEGATIVE":
        _fail("non-mention must be explicitly unknown, never negative")
    availability = protocol.get("availability_contract")
    if not isinstance(availability, Mapping):
        _fail("availability contract missing")
    required_availability = {
        "publication_order_is_not_clinical_availability": True,
        "exact_clock_only_if_reported": True,
        "preserve_intervals_and_partial_order": True,
        "same_reported_batch_same_cut": True,
        "forbid_single_event_microcuts_for_artificial_resolution": True,
    }
    for key, expected in required_availability.items():
        if availability.get(key) is not expected:
            _fail(f"availability contract missing invariant: {key}")
    availability_compiler = availability.get("compiler")
    required_availability_compiler = {
        "executable": "holdout/tools/compile_availability_epochs.py",
        "input_schema": "holdout/schemas/primary_availability_ledger.schema.json",
        "test_source": "holdout/tools/test_compile_availability_epochs.py",
        "interval_release": "latest_possible_epoch",
        "unknown_or_unbounded_partial_order": "WITHHOLD_TO_MEASUREMENT_UNCERTAINTY",
    }
    if not isinstance(availability_compiler, Mapping):
        _fail("availability compiler contract missing")
    for key, expected in required_availability_compiler.items():
        if availability_compiler.get(key) != expected:
            _fail(f"availability compiler contract mismatch: {key}")
    expected_transport_ids = {
        "contract_id": "NCF-OPAQUE-TRANSPORT-ID-1.0.0",
        "case_blind": True,
        "role_selected_payload_forbidden": True,
        "run_id": {
            "format": "RUN-<combined_preprimary_seal.payload_sha256>",
            "regex": "^RUN-[0-9a-f]{64}$",
            "digest_source": "combined_preprimary_seal.payload_sha256",
            "full_digest_required": True,
        },
        "sequential_ids": {
            "opaque_event_id": {
                "prefix": "EV-", "regex": "^EV-[0-9]{8}$",
                "order": "canonical_sanitized_event_ledger_row_order",
            },
            "opaque_action_id": {
                "prefix": "ACT-", "regex": "^ACT-[0-9]{8}$",
                "order": "first_occurrence_in_canonical_sanitized_event_ledger_order",
            },
            "opaque_source_concept_token": {
                "prefix": "SC-", "regex": "^SC-[0-9]{8}$",
                "order": "first_occurrence_in_canonical_sanitized_event_ledger_order",
            },
            "alternative_representation_group_id": {
                "prefix": "ARG-", "regex": "^ARG-[0-9]{8}$",
                "order": "first_occurrence_in_canonical_sanitized_event_ledger_order",
            },
        },
        "sequence_start": 1,
        "decimal_width": 8,
        "zero_padded": True,
        "independent_validator_recomputation_required": True,
        "missing_duplicate_or_noncanonical_id_verdict": "HARNESS_INCOMPLETE",
        "reordering_with_retained_old_ids_forbidden": True,
        "arbitrary_hash_or_payload_derived_suffix_forbidden": True,
        "concept_map_order_must_equal_source_token_first_occurrence_order": True,
    }
    transport_ids = protocol.get("opaque_transport_id_contract")
    if not isinstance(transport_ids, Mapping) or dict(transport_ids) != expected_transport_ids:
        _fail("opaque transport id contract mismatch")
    primary_execution_assets = protocol.get("primary_execution_asset_contract")
    if not isinstance(primary_execution_assets, Mapping):
        _fail("primary execution asset contract missing")
    if set(primary_execution_assets) != {
        "event_ledger_replay",
        "structural_gate_harness",
        "producer_replay_verifier",
        "opaque_concurrent_process_candidate_compiler",
        "evaluator_sanitized_runtime_ledger_compiler",
        "evaluator_sanitized_runtime_ledger_replay_verifier",
        "primary_case_gate_evaluator",
        "primary_case_gate_evidence_compiler",
        "primary_runtime_replay_executor",
        "preprimary_binding_scope",
        "generated_primary_results_bound_preprimary",
    }:
        _fail("primary execution asset contract keys mismatch")
    required_event_replay = {
        "executable": "holdout/tools/event_ledger_replay.py",
        "test_source": "holdout/tools/test_event_ledger_replay.py",
    }
    event_replay = primary_execution_assets.get("event_ledger_replay")
    if not isinstance(event_replay, Mapping):
        _fail("event-ledger replay asset contract missing")
    if set(event_replay) != set(required_event_replay):
        _fail("event-ledger replay asset contract keys mismatch")
    for key, expected in required_event_replay.items():
        if event_replay.get(key) != expected:
            _fail(f"event-ledger replay asset contract mismatch: {key}")
    required_structural_harness = {
        "executable": "holdout/tools/structural_gate_harness.py",
        "test_source": "holdout/tools/test_structural_gate_harness.py",
        "evidence_schema": "holdout/tools/structural_gate_evidence.schema.json",
        "results_schema": "holdout/tools/structural_gate_results.schema.json",
    }
    structural_harness = primary_execution_assets.get("structural_gate_harness")
    if not isinstance(structural_harness, Mapping):
        _fail("structural-gate harness asset contract missing")
    if set(structural_harness) != set(required_structural_harness):
        _fail("structural-gate harness asset contract keys mismatch")
    for key, expected in required_structural_harness.items():
        if structural_harness.get(key) != expected:
            _fail(f"structural-gate harness asset contract mismatch: {key}")
    exact_execution_assets = {
        "producer_replay_verifier": {
            "executable": "holdout/tools/producer_replay_verifier.py",
            "test_source": "holdout/tools/test_producer_replay_verifier.py",
        },
        "opaque_concurrent_process_candidate_compiler": {
            "executable": "holdout/tools/compile_opaque_concurrent_process_candidates.py",
            "test_source": "holdout/tools/test_compile_opaque_concurrent_process_candidates.py",
            "claims_schema": "holdout/schemas/primary_opaque_concurrent_process_candidate_claims.schema.json",
            "packet_schema": "holdout/schemas/primary_opaque_concurrent_process_candidate_packet.schema.json",
            "sealed_packet_schema": "holdout/schemas/primary_sealed_opaque_concurrent_process_candidate_packet.schema.json",
        },
        "evaluator_sanitized_runtime_ledger_compiler": {
            "producer_id": "evaluator-sanitized-runtime-ledger-compiler-v1",
            "executable": SANITIZED_LEDGER_COMPILER_PATH,
            "test_source": SANITIZED_LEDGER_COMPILER_TEST_PATH,
            "input_schema": SANITIZED_LEDGER_COMPILER_INPUT_SCHEMA_PATH,
            "output_schema": SANITIZED_RUNTIME_SCHEMA_PATH,
            "assignment_proof_schema": SANITIZED_LEDGER_ASSIGNMENT_PROOF_SCHEMA_PATH,
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
        },
        "evaluator_sanitized_runtime_ledger_replay_verifier": {
            "executable": SANITIZED_LEDGER_REPLAY_VERIFIER_PATH,
            "test_source": SANITIZED_LEDGER_REPLAY_VERIFIER_TEST_PATH,
            "output_schema": SANITIZED_LEDGER_REPLAY_VERIFICATION_SCHEMA_PATH,
        },
        "primary_case_gate_evaluator": {
            "executable": "holdout/tools/primary_case_gate_evaluator.py",
            "test_source": "holdout/tools/test_primary_case_gate_evaluator.py",
            "runtime_integration_test_source": "holdout/tools/test_primary_case_gate_evaluator_runtime.py",
            "input_schema": "holdout/schemas/primary_case_gate_evaluator_input.schema.json",
            "output_schema": "holdout/schemas/primary_case_gate_evaluation.schema.json",
            "report_candidate_schema": "holdout/schemas/primary_report_candidate.schema.json",
        },
        "primary_case_gate_evidence_compiler": {
            "executable": "holdout/tools/compile_primary_case_gate_evidence.py",
            "test_source": "holdout/tools/test_compile_primary_case_gate_evidence.py",
            "output_schema": "holdout/schemas/primary_gate_evidence.schema.json",
        },
        "primary_runtime_replay_executor": {
            "execution_role": "evaluator",
            "executable": "holdout/tools/primary_runtime_replay_executor.py",
            "test_source": "holdout/tools/test_primary_runtime_replay_executor.py",
            "input_manifest_schema": "holdout/schemas/primary_runtime_replay_input_manifest.schema.json",
            "runtime_output_schema": "holdout/schemas/primary_runtime_output.schema.json",
            "replay_seal_schema": "holdout/schemas/primary_runtime_replay_seal.schema.json",
            "mapped_observation_consumption_schema": "holdout/schemas/mapped_observation_consumption.schema.json",
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
        },
    }
    for asset_name, expected in exact_execution_assets.items():
        actual = primary_execution_assets.get(asset_name)
        if not isinstance(actual, Mapping) or dict(actual) != expected:
            _fail(f"{asset_name} asset contract mismatch")
    if (
        primary_execution_assets.get("preprimary_binding_scope")
        != "generator_source_tests_and_output_schemas_only"
        or primary_execution_assets.get("generated_primary_results_bound_preprimary") is not False
    ):
        _fail("primary execution binding must exclude generated primary results")
    oracle = protocol.get("oracle")
    if not isinstance(oracle, Mapping) or oracle.get("must_be_sealed_before_first_runtime_output") is not True or oracle.get("evaluator_may_receive_only_oracle_hash") is not True:
        _fail("oracle pre-output seal and evaluator blindness are mandatory")
    mapping_contract = protocol.get("mapping_consumption_contract")
    if not isinstance(mapping_contract, Mapping):
        _fail("mapped-observation consumption contract missing")
    hard_rules = mapping_contract.get("hard_rules")
    if not isinstance(hard_rules, list) or len(hard_rules) < 7:
        _fail("mapped-observation hard rules incomplete")

    if scoring.get("status") != "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION":
        _fail("scoring contract is not frozen")
    if scoring.get("gate_contract_version") != "1.1.0":
        _fail("scoring gate binding mismatch")
    statuses = scoring.get("action_counterfactual", {}).get("permitted_statuses")
    if statuses != wire_enum:
        _fail("scoring identifiability enum differs from architecture wire")
    if scoring.get("representation", {}).get("nonmention_as_negative_tolerance") != 0:
        _fail("scoring must tolerate zero nonmention-as-negative errors")
    if scoring.get("representation", {}).get("invented_availability_time_tolerance") != 0:
        _fail("scoring must tolerate zero invented availability times")
    final_scorer_contract = scoring.get("final_scorer_contract")
    if not isinstance(final_scorer_contract, Mapping):
        _fail("final scorer contract missing")
    required_scorer_values = {
        "executable": "holdout/tools/final_primary_holdout_scorer.py",
        "result_schema": "holdout/schemas/primary_holdout_final_result.schema.json",
        "test_source": "holdout/tools/test_final_primary_holdout_scorer.py",
        "required_gate_count": 30,
        "missing_duplicate_unknown_or_malformed_gate_verdict": "HARNESS_INCOMPLETE",
        "all_gate_evidence_complete_with_any_hard_gate_fail_verdict": "FAILED",
        "complex_case_coverage_missing_or_malformed_verdict": "HARNESS_INCOMPLETE",
        "complex_case_coverage_complete_with_any_failure_verdict": "FAILED",
        "correct_diagnosis_override_forbidden": True,
        "evidence_schema": "holdout/schemas/primary_gate_evidence.schema.json",
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
    for key, expected in required_scorer_values.items():
        if final_scorer_contract.get(key) != expected:
            _fail(f"final scorer contract mismatch: {key}")
    producer_policy = final_scorer_contract.get("evidence_producer_policy")
    if not isinstance(producer_policy, Mapping):
        _fail("final scorer evidence producer policy missing")
    expected_producers = json.loads('[{"allowed_subjects":{"COMPLEX_COVERAGE":[],"GATE":["PL-IND-001","PL-LED-002","PL-STATE-001","PL-STATE-002","PL-TIME-001","PL-TIME-002","PL-FACT-001","PL-FACT-002","PL-CONC-001","PL-CONC-002","PL-MODE-001","PL-MODE-002","PL-SUPPORT-001","PL-GEOM-001","PL-DX-001","PL-PRED-001","PL-ACT-001","PL-ACT-002","PL-OOD-001","PL-OOD-002","PL-REF-001","PL-REF-002","PL-REF-003","PL-REF-004"]},"artifact_produced_by_required":true,"artifact_schema_versions":["ncf.structural-gate-results.v1"],"assertion_contract":{"mode":"SUBJECT_RESULT_ROW_EXACT_V1","result_array_json_pointers":{"GATE":"/gate_results"},"result_field":"result","schema_version":"ncf.producer-assertion-contract.v1","subject_id_field":"gate_id","subject_kind_field":null},"producer_id":"structural-gate-harness-v1","replay_contract":{"adapter_id":"CONFIGURED_CLI_EXACT_JSON_V1","argv_template":["--output","{output_dir}","--generated-at","{check:generated_at}"],"check_arg_contract":{"generated_at":{"json_pointer":"/generated_at","pattern":"^\\\\d{4}-\\\\d{2}-\\\\d{2}T\\\\d{2}:\\\\d{2}:\\\\d{2}Z$","source":"OUTPUT_JSON_POINTER"}},"comparison":"EXACT_BYTES_AND_CANONICAL_JSON","network_policy":"APPLICATION_SOCKET_GUARD_OFFLINE","output_contract":{"artifact_relative_path":"structural_gate_results.json","json_schema_versions":["ncf.structural-gate-results.v1"],"manifest_json_pointer":"/evidence_manifest","manifest_path_field":"path","mode":"DIRECTORY_MANIFEST"},"required_input_slots":{},"schema_version":"ncf.producer-replay-policy.v1","timeout_seconds":300,"working_directory":"STUDY_ROOT"},"tool_path":"holdout/tools/structural_gate_harness.py"},{"allowed_subjects":{"COMPLEX_COVERAGE":["recursive_updates"],"GATE":["PL-LED-002"]},"artifact_produced_by_required":false,"artifact_schema_versions":["ncf.holdout.fresh-process-replay-report.v1"],"assertion_contract":{"mode":"SUBJECT_EXACT_POINTERS_V1","schema_version":"ncf.producer-assertion-contract.v1","subject_assertions":{"COMPLEX_COVERAGE":{"recursive_updates":[{"expected":"PASS","json_pointer":"/status","operator":"EQ"},{"expected":true,"json_pointer":"/recursive_fresh_process_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/cold_prefix_replay_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/cold_full_history_replay_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/deterministic_event_order_validated","operator":"EQ"},{"expected":true,"json_pointer":"/available_time_boundary_validated","operator":"EQ"}]},"GATE":{"PL-LED-002":[{"expected":"PASS","json_pointer":"/status","operator":"EQ"},{"expected":true,"json_pointer":"/recursive_fresh_process_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/cold_prefix_replay_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/cold_full_history_replay_byte_exact","operator":"EQ"},{"expected":true,"json_pointer":"/deterministic_event_order_validated","operator":"EQ"},{"expected":true,"json_pointer":"/available_time_boundary_validated","operator":"EQ"}]}}},"producer_id":"event-ledger-fresh-replay-v1","replay_contract":{"adapter_id":"CONFIGURED_CLI_EXACT_JSON_V1","argv_template":["verify","--bundle","{input:bundle}","--model","{input:model}","--report","{output}"],"check_arg_contract":{},"comparison":"EXACT_BYTES_AND_CANONICAL_JSON","network_policy":"APPLICATION_SOCKET_GUARD_OFFLINE","output_contract":{"json_schema_versions":["ncf.holdout.fresh-process-replay-report.v1"],"mode":"SINGLE_FILE"},"required_input_slots":{"bundle":{"json_schema_versions":["ncf.holdout.event-ledger-replay-bundle.v1"]},"model":{"json_schema_versions":["new-clinical-runtime.model.v2.0"]}},"schema_version":"ncf.producer-replay-policy.v1","timeout_seconds":300,"working_directory":"STUDY_ROOT"},"tool_path":"holdout/tools/event_ledger_replay.py"},{"allowed_subjects":{"COMPLEX_COVERAGE":["at_least_two_local_domains","concurrent_process_target_from_oracle","delayed_information","reliable_negative_evidence","performed_action_lifecycle_with_response","prospective_pre_next_cut_forecasts"],"GATE":["PL-BLIND-001","PL-LED-001","PL-DX-002","PL-PRED-002","PL-CASE-001"]},"artifact_produced_by_required":true,"artifact_schema_versions":["ncf.primary-case-gate-evaluation.v1"],"assertion_contract":{"check_expected_field":"expected","check_id_field":"check_id","check_observed_field":"observed","check_operator_field":"operator","check_pass_field":"passed","checks_field":"checks","mode":"SUBJECT_RESULT_ROW_EXHAUSTIVE_CHECKS_V1","result_array_json_pointers":{"COMPLEX_COVERAGE":"/coverage_results","GATE":"/gate_results"},"result_field":"computed_result","schema_version":"ncf.producer-assertion-contract.v1","subject_id_field":"subject_id","subject_kind_field":"subject_kind"},"producer_id":"primary-case-gate-evaluator-case-v1","replay_contract":{"adapter_id":"CONFIGURED_CLI_EXACT_JSON_V1","argv_template":["{check:subcommand}","--manifest","{input:input_manifest}","--output","{output}"],"check_arg_contract":{"subcommand":{"allowed_values":["evaluate-case"],"source":"SEALED_ENUM"}},"comparison":"EXACT_BYTES_AND_CANONICAL_JSON","network_policy":"APPLICATION_SOCKET_GUARD_OFFLINE","output_contract":{"json_schema_versions":["ncf.primary-case-gate-evaluation.v1"],"mode":"SINGLE_FILE"},"required_input_slots":{"input_manifest":{"json_schema_versions":["ncf.primary-case-gate-evaluator-input.v1"]}},"schema_version":"ncf.producer-replay-policy.v1","timeout_seconds":300,"working_directory":"STUDY_ROOT"},"tool_path":"holdout/tools/primary_case_gate_evaluator.py"},{"allowed_subjects":{"COMPLEX_COVERAGE":[],"GATE":["PL-REPORT-001"]},"artifact_produced_by_required":true,"artifact_schema_versions":["ncf.primary-case-gate-evaluation.v1"],"assertion_contract":{"check_expected_field":"expected","check_id_field":"check_id","check_observed_field":"observed","check_operator_field":"operator","check_pass_field":"passed","checks_field":"checks","mode":"SUBJECT_RESULT_ROW_EXHAUSTIVE_CHECKS_V1","result_array_json_pointers":{"COMPLEX_COVERAGE":"/coverage_results","GATE":"/gate_results"},"result_field":"computed_result","schema_version":"ncf.producer-assertion-contract.v1","subject_id_field":"subject_id","subject_kind_field":"subject_kind"},"producer_id":"primary-case-gate-evaluator-report-v1","replay_contract":{"adapter_id":"CONFIGURED_CLI_EXACT_JSON_V1","argv_template":["{check:subcommand}","--manifest","{input:input_manifest}","--output","{output}"],"check_arg_contract":{"subcommand":{"allowed_values":["evaluate-report"],"source":"SEALED_ENUM"}},"comparison":"EXACT_BYTES_AND_CANONICAL_JSON","network_policy":"APPLICATION_SOCKET_GUARD_OFFLINE","output_contract":{"json_schema_versions":["ncf.primary-case-gate-evaluation.v1"],"mode":"SINGLE_FILE"},"required_input_slots":{"input_manifest":{"json_schema_versions":["ncf.primary-case-gate-evaluator-input.v1"]}},"schema_version":"ncf.producer-replay-policy.v1","timeout_seconds":300,"working_directory":"STUDY_ROOT"},"tool_path":"holdout/tools/primary_case_gate_evaluator.py"}]')
    if producer_policy.get("sealed_automated_generators") != expected_producers:
        _fail("final scorer automated evidence producer allowlist mismatch")
    expected_manual = {
        "policy_id": "NCF-MANUAL-INDEPENDENT-AUDITOR-FAILURE-ONLY-1.0.0",
        "required_role": "scorer_auditor",
        "required_role_manifest_schema_version": "NCF-PRIMARY-ROLE-MANIFEST-1.1.0",
        "required_audit_output_data_class": "audit_report",
        "pass_permitted": False,
        "fail_permitted": True,
        "unautomated_positive_result": "HARNESS_INCOMPLETE",
    }
    if producer_policy.get("manual_independent_auditor") != expected_manual:
        _fail("manual independent auditor policy must remain failure-only")

    _validate_role_policy_contract(protocol, role_schema, role_set_schema, role_trace_schema)
    _validate_sanitized_runtime_schema_structure(sanitized_runtime_schema)
    if sanitized_ledger_compiler_input_schema.get("$id") != (
        "ncf.evaluator-sanitized-runtime-ledger-compiler-input.v1"
    ):
        _fail("sanitized-ledger compiler input schema id mismatch")
    if sanitized_ledger_assignment_proof_schema.get("$id") != (
        "ncf.evaluator-sanitized-runtime-ledger-assignment-proof.v1"
    ):
        _fail("sanitized-ledger assignment proof schema id mismatch")
    if sanitized_ledger_replay_verification_schema.get("$id") != (
        "ncf.evaluator-sanitized-runtime-ledger-replay-verification.v1"
    ):
        _fail("sanitized-ledger replay verification schema id mismatch")
    _validate_all_sealed_replay_schema_structure(all_sealed_replay_schema)
    _validate_sealed_concept_map_schema_structure(sealed_concept_map_schema, mapper_registry)
    if search_schema.get("$id") != "ncf.primary-case-search-snapshot.v1":
        _fail("search snapshot schema id mismatch")
    if raw_search_schema.get("$id") != "ncf.primary-raw-search-response.v1":
        _fail("raw search response schema id mismatch")
    if raw_search_retrieval_schema.get("$id") != "ncf.primary-search-retrieval-manifest.v1":
        _fail("raw search retrieval manifest schema id mismatch")
    if screening_schema.get("$id") != "ncf.primary-case-screening.v1":
        _fail("screening schema id mismatch")
    if screening_schema.get("properties", {}).get("schema_version", {}).get("const") != "NCF-PRIMARY-CASE-SCREENING-1.1.0":
        _fail("screening schema version mismatch")
    if screening_evidence_schema.get("$id") != "ncf.primary-screening-evidence.v1":
        _fail("screening evidence schema id mismatch")
    if screening_evidence_schema.get("$defs", {}).get("index", {}).get("properties", {}).get("schema_version", {}).get("const") != "NCF-PRIMARY-SCREENING-EVIDENCE-INDEX-1.1.0":
        _fail("screening evidence schema version mismatch")
    for schema, expected, label in (
        (complexity_claims_schema, "ncf.opaque-concurrent-process-candidate-claims.v1", "complexity claims"),
        (complexity_packet_schema, "ncf.opaque-concurrent-process-candidate-packet.v1", "complexity packet"),
        (sealed_complexity_packet_schema, "ncf.sealed-opaque-concurrent-process-candidate-packet.v1", "sealed complexity packet"),
    ):
        if schema.get("$id") != expected:
            _fail(f"{label} schema id mismatch")
    if mapped_observation_schema.get("$id") != "ncf.mapped-observation-consumption.v1":
        _fail("mapped observation consumption schema id mismatch")
    if mapped_observation_schema.get("properties", {}).get("schema_version", {}).get("const") != "NCF-MAPPED-OBSERVATION-CONSUMPTION-1.1.0":
        _fail("mapped observation consumption schema version mismatch")
    for schema, schema_id, version, label in (
        (runtime_replay_input_schema, "ncf.primary-runtime-replay-input-manifest.v1", "NCF-PRIMARY-RUNTIME-REPLAY-INPUT-MANIFEST-1.0.0", "runtime replay input"),
        (runtime_output_schema, "ncf.data.runtime-output.v1", "NCF-PRIMARY-RUNTIME-OUTPUT-1.0.0", "runtime output"),
        (runtime_replay_seal_schema, "ncf.data.replay-seal.v1", "NCF-PRIMARY-RUNTIME-REPLAY-SEAL-1.0.0", "runtime replay seal"),
    ):
        if schema.get("$id") != schema_id or schema.get("properties", {}).get("schema_version", {}).get("const") != version:
            _fail(f"{label} schema identity mismatch")
    if final_result_schema.get("$id") != "ncf.primary-holdout-final-result.v1":
        _fail("final result schema id mismatch")
    if gate_evidence_schema.get("$id") != "ncf.primary-gate-evidence.v3":
        _fail("gate evidence schema id mismatch")
    if availability_schema.get("$id") != "ncf.primary-availability-ledger.v1":
        _fail("availability ledger schema id mismatch")
    if structural_gate_evidence_schema.get("$id") != "ncf.structural-gate-evidence.v1":
        _fail("structural gate evidence schema id mismatch")
    if structural_gate_results_schema.get("$id") != "ncf.structural-gate-results.v1":
        _fail("structural gate results schema id mismatch")
    selector = holdout / "tools/select_primary_holdout.py"
    selector_test = holdout / "tools/test_select_primary_holdout.py"
    raw_search_validator = holdout / "tools/validate_primary_search_snapshot.py"
    raw_search_validator_test = holdout / "tools/test_validate_primary_search_snapshot.py"
    raw_search_compiler = holdout / "tools/compile_primary_search_snapshot.py"
    raw_search_compiler_test = holdout / "tools/test_compile_primary_search_snapshot.py"
    screening_validator = holdout / "tools/validate_primary_case_screening.py"
    screening_validator_test = holdout / "tools/test_validate_primary_case_screening.py"
    complexity_compiler = holdout / "tools/compile_opaque_concurrent_process_candidates.py"
    complexity_compiler_test = holdout / "tools/test_compile_opaque_concurrent_process_candidates.py"
    sanitized_ledger_compiler = root / SANITIZED_LEDGER_COMPILER_PATH
    sanitized_ledger_compiler_test = root / SANITIZED_LEDGER_COMPILER_TEST_PATH
    sanitized_ledger_replay_verifier = root / SANITIZED_LEDGER_REPLAY_VERIFIER_PATH
    sanitized_ledger_replay_verifier_test = root / SANITIZED_LEDGER_REPLAY_VERIFIER_TEST_PATH
    preprimary_seal_tool = holdout / "tools/build_pre_primary_holdout_seal.py"
    preprimary_seal_test = holdout / "tools/test_pre_primary_holdout_seal.py"
    protocol_validator_test = holdout / "tools/test_validate_primary_holdout_protocol.py"
    if not selector.is_file() or not selector_test.is_file():
        _fail("deterministic selector tool/test source missing")
    if not raw_search_validator.is_file() or not raw_search_validator_test.is_file():
        _fail("raw search snapshot validator/test source missing")
    if not raw_search_compiler.is_file() or not raw_search_compiler_test.is_file():
        _fail("raw search snapshot compiler/test source missing")
    if not screening_validator.is_file() or not screening_validator_test.is_file():
        _fail("primary case screening validator/test source missing")
    if not complexity_compiler.is_file() or not complexity_compiler_test.is_file():
        _fail("opaque concurrent-process compiler/test source missing")
    if not sanitized_ledger_compiler.is_file() or not sanitized_ledger_compiler_test.is_file():
        _fail("evaluator sanitized runtime ledger compiler/test source missing")
    if (
        not sanitized_ledger_replay_verifier.is_file()
        or not sanitized_ledger_replay_verifier_test.is_file()
    ):
        _fail("evaluator sanitized runtime ledger replay verifier/test source missing")
    if not preprimary_seal_tool.is_file() or not preprimary_seal_test.is_file():
        _fail("pre-primary combined seal tool/test source missing")
    if not protocol_validator_test.is_file():
        _fail("primary protocol validator test source missing")
    final_scorer = holdout / "tools/final_primary_holdout_scorer.py"
    final_scorer_test = holdout / "tools/test_final_primary_holdout_scorer.py"
    if not final_scorer.is_file() or not final_scorer_test.is_file():
        _fail("final scorer executable/test source missing")
    availability_compiler_tool = holdout / "tools/compile_availability_epochs.py"
    availability_compiler_test = holdout / "tools/test_compile_availability_epochs.py"
    if not availability_compiler_tool.is_file() or not availability_compiler_test.is_file():
        _fail("availability compiler executable/test source missing")
    event_ledger_replay = holdout / "tools/event_ledger_replay.py"
    event_ledger_replay_test = holdout / "tools/test_event_ledger_replay.py"
    structural_gate_harness = holdout / "tools/structural_gate_harness.py"
    structural_gate_harness_test = holdout / "tools/test_structural_gate_harness.py"
    if not event_ledger_replay.is_file() or not event_ledger_replay_test.is_file():
        _fail("event-ledger replay executable/test source missing")
    if not structural_gate_harness.is_file() or not structural_gate_harness_test.is_file():
        _fail("structural-gate harness executable/test source missing")
    producer_replay_verifier = holdout / "tools/producer_replay_verifier.py"
    producer_replay_verifier_test = holdout / "tools/test_producer_replay_verifier.py"
    primary_case_gate_evaluator = holdout / "tools/primary_case_gate_evaluator.py"
    primary_case_gate_evaluator_test = holdout / "tools/test_primary_case_gate_evaluator.py"
    primary_case_gate_evaluator_runtime_test = (
        holdout / "tools/test_primary_case_gate_evaluator_runtime.py"
    )
    primary_gate_evidence_compiler = holdout / "tools/compile_primary_case_gate_evidence.py"
    primary_gate_evidence_compiler_test = holdout / "tools/test_compile_primary_case_gate_evidence.py"
    primary_runtime_replay_executor = holdout / "tools/primary_runtime_replay_executor.py"
    primary_runtime_replay_executor_test = holdout / "tools/test_primary_runtime_replay_executor.py"
    for tool, test, label in (
        (producer_replay_verifier, producer_replay_verifier_test, "producer replay verifier"),
        (primary_case_gate_evaluator, primary_case_gate_evaluator_test, "primary case gate evaluator"),
        (primary_gate_evidence_compiler, primary_gate_evidence_compiler_test, "primary gate evidence compiler"),
        (primary_runtime_replay_executor, primary_runtime_replay_executor_test, "primary runtime replay executor"),
    ):
        if not tool.is_file() or not test.is_file():
            _fail(f"{label} executable/test source missing")
    if not primary_case_gate_evaluator_runtime_test.is_file():
        _fail("primary case gate evaluator runtime integration test source missing")

    return {
        "status": "PASS",
        "architecture_identifiability_enum": wire_enum,
        "gate_contract_version": gates["contract_version"],
        "execution_protocol_version": protocol["protocol_version"],
        "scoring_contract_version": scoring["contract_version"],
        "frozen_query_count": len(queries),
        "minimum_eligible_candidates": selection["minimum_eligible_candidates"],
        "artifacts": {
            "execution_protocol_md": _sha(holdout / "PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.md"),
            "execution_protocol_json": _sha(holdout / "PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json"),
            "scoring_contract": _sha(holdout / "PRIMARY_HOLDOUT_SCORING_v1.json"),
            "preprimary_seal_tool": _sha(preprimary_seal_tool),
            "preprimary_seal_test": _sha(preprimary_seal_test),
            "selector": _sha(selector),
            "selector_test": _sha(selector_test),
            "raw_search_validator": _sha(raw_search_validator),
            "raw_search_validator_test": _sha(raw_search_validator_test),
            "raw_search_compiler": _sha(raw_search_compiler),
            "raw_search_compiler_test": _sha(raw_search_compiler_test),
            "screening_validator": _sha(screening_validator),
            "screening_validator_test": _sha(screening_validator_test),
            "complexity_compiler": _sha(complexity_compiler),
            "complexity_compiler_test": _sha(complexity_compiler_test),
            "evaluator_sanitized_runtime_ledger_compiler": _sha(
                sanitized_ledger_compiler
            ),
            "evaluator_sanitized_runtime_ledger_compiler_test": _sha(
                sanitized_ledger_compiler_test
            ),
            "evaluator_sanitized_runtime_ledger_compiler_input_schema": _sha(
                root / SANITIZED_LEDGER_COMPILER_INPUT_SCHEMA_PATH
            ),
            "evaluator_sanitized_runtime_ledger_assignment_proof_schema": _sha(
                root / SANITIZED_LEDGER_ASSIGNMENT_PROOF_SCHEMA_PATH
            ),
            "evaluator_sanitized_runtime_ledger_replay_verifier": _sha(
                sanitized_ledger_replay_verifier
            ),
            "evaluator_sanitized_runtime_ledger_replay_verifier_test": _sha(
                sanitized_ledger_replay_verifier_test
            ),
            "evaluator_sanitized_runtime_ledger_replay_verification_schema": _sha(
                root / SANITIZED_LEDGER_REPLAY_VERIFICATION_SCHEMA_PATH
            ),
            "protocol_validator_test": _sha(protocol_validator_test),
            "role_manifest_schema": _sha(holdout / "schemas/primary_role_execution_manifest.schema.json"),
            "role_manifest_set_schema": _sha(holdout / "schemas/primary_role_manifest_set.schema.json"),
            "role_tool_access_trace_schema": _sha(
                holdout / "schemas/primary_role_tool_access_trace.schema.json"
            ),
            "evaluator_sanitized_runtime_ledger_schema": _sha(
                root / SANITIZED_RUNTIME_SCHEMA_PATH
            ),
            "all_sealed_artifacts_after_replay_schema": _sha(
                root / ALL_SEALED_REPLAY_SCHEMA_PATH
            ),
            "sealed_concept_map_schema": _sha(root / SEALED_CONCEPT_MAP_SCHEMA_PATH),
            "search_snapshot_schema": _sha(holdout / "schemas/primary_case_search_snapshot.schema.json"),
            "raw_search_response_schema": _sha(holdout / "schemas/primary_raw_search_response.schema.json"),
            "raw_search_retrieval_schema": _sha(holdout / "schemas/primary_search_retrieval_manifest.schema.json"),
            "screening_schema": _sha(holdout / "schemas/primary_case_screening.schema.json"),
            "screening_evidence_schema": _sha(
                holdout / "schemas/primary_screening_evidence.schema.json"
            ),
            "complexity_claims_schema": _sha(
                holdout / "schemas/primary_opaque_concurrent_process_candidate_claims.schema.json"
            ),
            "complexity_packet_schema": _sha(
                holdout / "schemas/primary_opaque_concurrent_process_candidate_packet.schema.json"
            ),
            "sealed_complexity_packet_schema": _sha(
                holdout / "schemas/primary_sealed_opaque_concurrent_process_candidate_packet.schema.json"
            ),
            "mapped_observation_schema": _sha(holdout / "schemas/mapped_observation_consumption.schema.json"),
            "final_scorer": _sha(final_scorer),
            "final_scorer_test": _sha(final_scorer_test),
            "final_result_schema": _sha(holdout / "schemas/primary_holdout_final_result.schema.json"),
            "gate_evidence_schema": _sha(holdout / "schemas/primary_gate_evidence.schema.json"),
            "availability_compiler": _sha(availability_compiler_tool),
            "availability_compiler_test": _sha(availability_compiler_test),
            "availability_schema": _sha(holdout / "schemas/primary_availability_ledger.schema.json"),
            "event_ledger_replay": _sha(event_ledger_replay),
            "event_ledger_replay_test": _sha(event_ledger_replay_test),
            "structural_gate_harness": _sha(structural_gate_harness),
            "structural_gate_harness_test": _sha(structural_gate_harness_test),
            "structural_gate_evidence_schema": _sha(holdout / "tools/structural_gate_evidence.schema.json"),
            "structural_gate_results_schema": _sha(holdout / "tools/structural_gate_results.schema.json"),
            "producer_replay_verifier": _sha(producer_replay_verifier),
            "producer_replay_verifier_test": _sha(producer_replay_verifier_test),
            "primary_case_gate_evaluator": _sha(primary_case_gate_evaluator),
            "primary_case_gate_evaluator_test": _sha(primary_case_gate_evaluator_test),
            "primary_case_gate_evaluator_runtime_test": _sha(
                primary_case_gate_evaluator_runtime_test
            ),
            "primary_gate_evidence_compiler": _sha(primary_gate_evidence_compiler),
            "primary_gate_evidence_compiler_test": _sha(primary_gate_evidence_compiler_test),
            "primary_case_gate_evaluator_input_schema": _sha(
                holdout / "schemas/primary_case_gate_evaluator_input.schema.json"
            ),
            "primary_case_gate_evaluation_schema": _sha(
                holdout / "schemas/primary_case_gate_evaluation.schema.json"
            ),
            "primary_report_candidate_schema": _sha(
                holdout / "schemas/primary_report_candidate.schema.json"
            ),
            "primary_runtime_replay_executor": _sha(primary_runtime_replay_executor),
            "primary_runtime_replay_executor_test": _sha(primary_runtime_replay_executor_test),
            "primary_runtime_replay_input_manifest_schema": _sha(
                holdout / "schemas/primary_runtime_replay_input_manifest.schema.json"
            ),
            "primary_runtime_output_schema": _sha(
                holdout / "schemas/primary_runtime_output.schema.json"
            ),
            "primary_runtime_replay_seal_schema": _sha(
                holdout / "schemas/primary_runtime_replay_seal.schema.json"
            ),
        },
    }


def _walk_keys(value: Any, prefix: str = "$"):
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield prefix, str(key)
            yield from _walk_keys(child, f"{prefix}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_keys(child, f"{prefix}[{index}]")


def validate_mapper_packet(study_root: Path, packet_path: Path) -> dict[str, Any]:
    protocol = _load(study_root / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json", "execution protocol")
    packet = _load(packet_path, "mapper packet")
    contract = protocol.get("mapper_packet")
    allowed = set(contract.get("allowed_fields", []))
    forbidden = set(contract.get("forbidden_fields", []))
    concepts = packet.get("concepts")
    if set(packet) != {"schema_version", "concepts", "packet_sha256"}:
        _fail("mapper packet top-level fields are not minimal")
    if not isinstance(concepts, list):
        _fail("mapper packet concepts must be list")
    for index, row in enumerate(concepts):
        if not isinstance(row, Mapping):
            _fail(f"mapper concept {index} must be object")
        keys = set(row)
        if not keys.issubset(allowed) or "source_concept_id" not in keys:
            _fail(f"mapper concept {index} contains non-allowed fields: {sorted(keys - allowed)}")
    for path, key in _walk_keys(packet):
        if key in forbidden:
            _fail(f"mapper packet contains forbidden key {key} at {path}")
    expected = packet.get("packet_sha256")
    payload = dict(packet)
    payload.pop("packet_sha256", None)
    actual = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if expected != actual:
        _fail("mapper packet self hash mismatch")
    return {"status": "PASS", "concept_count": len(concepts), "packet_sha256": actual}


def _manifest_path_ref(
    study_root: Path, manifest_path: Path, label: str
) -> tuple[str, Path, bytes]:
    """Read a caller-selected manifest without resolving through a link first."""

    root = study_root.resolve(strict=True)
    candidate = manifest_path if manifest_path.is_absolute() else root / manifest_path
    try:
        rel = candidate.relative_to(root).as_posix()
    except ValueError:
        _fail(f"{label} must be an existing canonical file under the study root")
    return _canonical_path_bytes(root, rel, label)


def _role_contract_inputs(
    study_root: Path,
) -> tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]:
    protocol = _load(study_root / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json", "execution protocol")
    role_schema = _load(
        study_root / "holdout/schemas/primary_role_execution_manifest.schema.json", "role manifest schema"
    )
    aggregate_schema = _load(
        study_root / "holdout/schemas/primary_role_manifest_set.schema.json", "role manifest set schema"
    )
    trace_schema = _load(
        study_root / "holdout/schemas/primary_role_tool_access_trace.schema.json",
        "role tool access trace schema",
    )
    _validate_role_policy_contract(protocol, role_schema, aggregate_schema, trace_schema)
    return protocol, role_schema, aggregate_schema, trace_schema


def _validate_lineage_ref(
    study_root: Path, row: Any, label: str
) -> tuple[str, bytes]:
    if not isinstance(row, Mapping):
        _fail(f"{label} must be a content-addressed object")
    rel, _, payload = _canonical_artifact_bytes(study_root, row, label)
    return rel, payload


def _artifact_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(key) for key in ("path", "sha256", "bytes", "data_class", "schema_id"))


def _trace_access_identity(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(
        row.get(key)
        for key in (
            "operation", "artifact_kind", "path", "sha256", "bytes", "data_class", "schema_id"
        )
    )


def _validate_role_manifest_value(
    study_root: Path,
    manifest: Mapping[str, Any],
    protocol: Mapping[str, Any],
    role_schema: Mapping[str, Any],
    trace_schema: Mapping[str, Any],
    *,
    manifest_rel: str,
) -> dict[str, Any]:
    _validate_schema_instance(manifest, role_schema)
    role = manifest["role"]
    policy = protocol["roles"][role]
    input_allowed = set(policy["allowed_input_data_classes"])
    output_allowed = set(policy["allowed_output_data_classes"])
    forbidden = set(policy["forbidden_data_classes"])
    inputs = manifest["inputs"]
    outputs = manifest["outputs"]
    input_class_list = [row["data_class"] for row in inputs]
    output_class_list = [row["data_class"] for row in outputs]
    if len(input_class_list) != len(set(input_class_list)):
        _fail(f"role {role} duplicates an input data class")
    if len(output_class_list) != len(set(output_class_list)):
        _fail(f"role {role} duplicates an output data class")
    input_classes = set(input_class_list)
    output_classes = set(output_class_list)
    if input_classes != input_allowed:
        _fail(
            f"role {role} inputs must contain every frozen allowed class exactly once; "
            f"missing={sorted(input_allowed-input_classes)} extra={sorted(input_classes-input_allowed)}"
        )
    if output_classes != output_allowed:
        _fail(
            f"role {role} outputs must contain every frozen allowed class exactly once; "
            f"missing={sorted(output_allowed-output_classes)} extra={sorted(output_classes-output_allowed)}"
        )
    declared_observed = set(manifest["observed_data_classes"])
    exposed_classes = declared_observed | input_classes | output_classes
    if exposed_classes & forbidden:
        _fail(f"role {role} exposes forbidden classes: {sorted(exposed_classes&forbidden)}")
    if policy["case_identity_exposure"] == "FORBIDDEN" and manifest["case_identity_exposed"] is not False:
        _fail(f"role {role} must not be exposed to case identity")
    start = datetime.fromisoformat(manifest["started_at"].replace("Z", "+00:00"))
    finish = datetime.fromisoformat(manifest["finished_at"].replace("Z", "+00:00"))
    if finish < start:
        _fail(f"role {role} finished_at precedes started_at")

    schema_ids = protocol["role_manifest"]["data_class_schema_ids"]
    roots = set(protocol["role_manifest"]["presealed_root_data_classes"])
    edge_rows = protocol["role_manifest"]["producer_consumer_edges"]
    edge_set = {
        (row["producer_role"], consumer, row["data_class"])
        for row in edge_rows
        for consumer in row["consumer_roles"]
    }
    input_paths: set[str] = set()
    output_paths: set[str] = set()
    external_metadata_paths: set[str] = set()
    input_payloads: dict[str, bytes] = {}
    output_payloads: dict[str, bytes] = {}
    combined_seal_ref: Mapping[str, Any] | None = None
    combined_inventory: dict[str, tuple[str, int]] | None = None
    combined_seal_value: Mapping[str, Any] | None = None
    external_producer_bindings: list[dict[str, Any]] = []
    for index, row in enumerate(inputs):
        rel, _, input_payload = _canonical_artifact_bytes(
            study_root, row, f"role {role} input[{index}]"
        )
        if rel in input_paths:
            _fail(f"role {role} duplicates input path: {rel}")
        input_paths.add(rel)
        data_class = row["data_class"]
        input_payloads[data_class] = input_payload
        if row["schema_id"] != schema_ids[data_class]:
            _fail(f"role {role} input schema_id mismatch: {data_class}")
        producer = row["producer"]
        kind = producer.get("kind")
        if kind == "PRESEALED_ROOT":
            if set(producer) != {"kind", "seal"} or data_class not in roots:
                _fail(f"role {role} has invalid PRESEALED_ROOT input: {data_class}")
            if rel != EXPECTED_PRESEALED_ROOT_ASSET_PATHS[data_class]:
                _fail(f"role {role} PRESEALED_ROOT path mismatch: {data_class}")
            seal_ref = producer.get("seal")
            if combined_seal_ref is None:
                if not isinstance(seal_ref, Mapping):
                    _fail(f"role {role} PRESEALED_ROOT seal reference missing")
                combined_seal_ref = seal_ref
                combined_inventory, combined_seal_value = _verify_combined_seal_ref(
                    study_root, seal_ref, f"role {role} combined pre-primary seal"
                )
            elif seal_ref != combined_seal_ref:
                _fail(f"role {role} root inputs bind different combined seals")
            assert combined_inventory is not None and combined_seal_ref is not None
            identity = (row["sha256"], row["bytes"])
            if data_class == "combined_preprimary_seal":
                if _artifact_identity(row)[:3] != (
                    combined_seal_ref["path"], combined_seal_ref["sha256"], combined_seal_ref["bytes"]
                ):
                    _fail(f"role {role} combined seal input does not bind its producer seal")
            elif combined_inventory.get(rel) != identity:
                _fail(f"role {role} root input is absent from the bound combined seal: {data_class}")
        elif kind == "ROLE_OUTPUT":
            expected_keys = {
                "kind", "role", "run_id", "manifest_path", "manifest_sha256", "manifest_bytes"
            }
            if set(producer) != expected_keys:
                _fail(f"role {role} ROLE_OUTPUT producer lineage is incomplete")
            producer_role = producer.get("role")
            if producer_role == role or (producer_role, role, data_class) not in edge_set:
                _fail(f"role {role} input has unauthorized producer edge: {producer_role}:{data_class}")
            producer_manifest_rel = producer.get("manifest_path")
            if not isinstance(producer_manifest_rel, str):
                _fail(f"role {role} producer manifest path missing")
            producer_row = {
                "path": producer_manifest_rel,
                "sha256": producer.get("manifest_sha256"),
                "bytes": producer.get("manifest_bytes"),
            }
            _, _, producer_payload = _canonical_artifact_bytes(
                study_root, producer_row, f"role {role} producer manifest"
            )
            producer_manifest = _json_from_verified_bytes(
                producer_payload, f"role {role} producer manifest"
            )
            _validate_schema_instance(producer_manifest, role_schema)
            if producer_manifest.get("role") != producer_role or producer_manifest.get("run_id") != producer.get("run_id"):
                _fail(f"role {role} producer manifest identity mismatch")
            comparable = {key: row[key] for key in ("path", "sha256", "bytes", "data_class", "schema_id")}
            if comparable not in producer_manifest.get("outputs", []):
                _fail(f"role {role} input is not an exact producer output: {data_class}:{rel}")
        elif kind == "SEALED_EXECUTABLE_OUTPUT":
            if (
                set(producer) != {
                    "kind", "producer_id", "assignment_proof",
                    "replay_verification",
                }
                or role != "evaluator"
                or data_class != "evaluator_sanitized_runtime_ledger"
                or producer.get("producer_id") != SANITIZED_LEDGER_COMPILER_PRODUCER_ID
            ):
                _fail(
                    f"role {role} has invalid SEALED_EXECUTABLE_OUTPUT input: {data_class}"
                )
            proof_rel, proof_payload = _validate_lineage_ref(
                study_root,
                producer.get("assignment_proof"),
                "evaluator sanitized-ledger assignment proof",
            )
            verification_rel, verification_payload = _validate_lineage_ref(
                study_root,
                producer.get("replay_verification"),
                "evaluator sanitized-ledger replay verification",
            )
            if (
                proof_rel == verification_rel
                or proof_rel in external_metadata_paths
                or verification_rel in external_metadata_paths
                or proof_rel in input_paths
                or verification_rel in input_paths
            ):
                _fail("sealed-executable assignment proof path overlaps or duplicates input")
            external_metadata_paths.update({proof_rel, verification_rel})
            external_producer_bindings.append(
                {
                    "data_class": data_class,
                    "input_artifact": dict(row),
                    "proof_path": proof_rel,
                    "proof_payload": proof_payload,
                    "verification_path": verification_rel,
                    "verification_payload": verification_payload,
                    "producer": dict(producer),
                }
            )
        else:
            _fail(f"role {role} input producer kind invalid")
    for index, row in enumerate(outputs):
        rel, _, output_payload = _canonical_artifact_bytes(
            study_root, row, f"role {role} output[{index}]"
        )
        if rel in output_paths:
            _fail(f"role {role} duplicates output path: {rel}")
        output_paths.add(rel)
        data_class = row["data_class"]
        output_payloads[data_class] = output_payload
        if row["schema_id"] != schema_ids[data_class]:
            _fail(f"role {role} output schema_id mismatch: {data_class}")
    if input_paths & output_paths:
        _fail(f"role {role} input/output paths overlap: {sorted(input_paths&output_paths)}")
    if external_metadata_paths & (input_paths | output_paths):
        _fail("sealed-executable lineage metadata overlaps a role input/output")

    prompt_rel, _ = _validate_lineage_ref(
        study_root, manifest["prompt_or_command"], f"role {role} prompt_or_command"
    )
    trace_rel, trace_payload = _validate_lineage_ref(
        study_root, manifest["tool_trace"], f"role {role} tool_trace"
    )
    parent_rel, _ = _validate_lineage_ref(
        study_root, manifest["parent_packet"], f"role {role} parent_packet"
    )
    lineage_paths = {prompt_rel, trace_rel, parent_rel}
    if len(lineage_paths) != 3:
        _fail(f"role {role} lineage refs must name three distinct artifacts")
    if lineage_paths & (input_paths | output_paths):
        _fail(f"role {role} lineage artifact overlaps a declared input/output")
    if lineage_paths & external_metadata_paths:
        _fail("sealed-executable lineage metadata overlaps role lineage")

    if role == "evaluator":
        if (
            len(external_producer_bindings) != 1
            or combined_inventory is None
            or combined_seal_value is None
        ):
            _fail("evaluator lacks one verified external sanitized-ledger producer binding")
        _, _, schema_payload = _canonical_path_bytes(
            study_root, SANITIZED_RUNTIME_SCHEMA_PATH,
            "evaluator sanitized runtime ledger schema",
        )
        sanitized_schema = _json_from_verified_bytes(
            schema_payload, "evaluator sanitized runtime ledger schema"
        )
        _validate_sanitized_runtime_schema_structure(sanitized_schema)
        sanitized_ledger = _json_from_verified_bytes(
            input_payloads["evaluator_sanitized_runtime_ledger"],
            "evaluator sanitized runtime ledger",
        )
        _validate_schema_instance(sanitized_ledger, sanitized_schema)
        _assert_identity_neutral_runtime_ledger(sanitized_ledger)
        role_inputs_by_class = {row["data_class"]: row for row in inputs}
        external_assignment_proof = _validate_external_sanitized_ledger_assignment_proof(
            study_root,
            external_producer_bindings[0],
            role_inputs_by_class=role_inputs_by_class,
            sanitized_ledger=sanitized_ledger,
            combined_inventory=combined_inventory,
            combined_seal=combined_seal_value,
        )
        event_ids = [row["opaque_event_id"] for row in sanitized_ledger["events"]]
        if len(event_ids) != len(set(event_ids)):
            _fail("evaluator sanitized runtime ledger duplicates opaque_event_id")
        _, _, concept_map_schema_payload = _canonical_path_bytes(
            study_root, SEALED_CONCEPT_MAP_SCHEMA_PATH, "sealed concept map schema"
        )
        concept_map_schema = _json_from_verified_bytes(
            concept_map_schema_payload, "sealed concept map schema"
        )
        registry = _json_from_verified_bytes(
            input_payloads["sanitized_id_type_unit_registry"],
            "sanitized id/type/unit registry",
        )
        _validate_sealed_concept_map_schema_structure(concept_map_schema, registry)
        concept_map = _json_from_verified_bytes(
            input_payloads["sealed_concept_map"], "sealed concept map"
        )
        _validate_schema_instance(concept_map, concept_map_schema)
        model_pack = _json_from_verified_bytes(
            input_payloads["model_pack"], "frozen model pack"
        )
        combined_preprimary_seal = _json_from_verified_bytes(
            input_payloads["combined_preprimary_seal"],
            "combined pre-primary seal",
        )
        _validate_sanitized_ledger_against_map_and_registry(
            sanitized_ledger, concept_map, registry, model_pack,
            combined_preprimary_seal,
        )
        _validate_external_sanitized_ledger_replay_verification(
            study_root,
            external_producer_bindings[0],
            assignment_proof=external_assignment_proof,
            role_inputs_by_class=role_inputs_by_class,
            combined_inventory=combined_inventory,
            combined_seal=combined_seal_value,
        )
        _, _, all_sealed_schema_payload = _canonical_path_bytes(
            study_root, ALL_SEALED_REPLAY_SCHEMA_PATH, "all-sealed-after-replay schema"
        )
        all_sealed_schema = _json_from_verified_bytes(
            all_sealed_schema_payload, "all-sealed-after-replay schema"
        )
        _validate_all_sealed_replay_schema_structure(all_sealed_schema)
        all_sealed = _json_from_verified_bytes(
            output_payloads["all_sealed_artifacts_after_replay"],
            "all-sealed-after-replay inventory",
        )
        _validate_schema_instance(all_sealed, all_sealed_schema)
        if all_sealed["evaluator_run_id"] != manifest["run_id"]:
            _fail("all-sealed-after-replay evaluator run_id mismatch")
        expected_inventory = {
            _artifact_identity(row)
            for row in [*inputs, *outputs]
            if row["data_class"] != "all_sealed_artifacts_after_replay"
        }
        actual_inventory = {_artifact_identity(row) for row in all_sealed["artifacts"]}
        if len(actual_inventory) != len(all_sealed["artifacts"]):
            _fail("all-sealed-after-replay inventory duplicates an artifact/class")
        if actual_inventory != expected_inventory:
            _fail(
                "all-sealed-after-replay inventory is not exact; "
                f"missing={sorted(expected_inventory-actual_inventory, key=str)} "
                f"extra={sorted(actual_inventory-expected_inventory, key=str)}"
            )
    elif external_producer_bindings:
        _fail(f"non-evaluator role {role} carries a sealed-executable input")

    trace = _json_from_verified_bytes(trace_payload, f"role {role} tool access trace")
    _validate_schema_instance(trace, trace_schema)
    if (
        trace.get("role") != role
        or trace.get("run_id") != manifest["run_id"]
        or trace.get("case_identity_exposed") is not manifest["case_identity_exposed"]
    ):
        _fail(f"role {role} tool access trace identity mismatch")
    if trace.get("prompt_or_command_sha256") != manifest["prompt_or_command"]["sha256"]:
        _fail(f"role {role} tool access trace prompt binding mismatch")
    if trace.get("parent_packet_sha256") != manifest["parent_packet"]["sha256"]:
        _fail(f"role {role} tool access trace parent binding mismatch")

    network_requests = trace["network_requests"]
    network_detected = trace["network_access_detected"]
    if network_detected is not bool(network_requests):
        _fail(f"role {role} network access flag/request list mismatch")
    if [row["sequence"] for row in network_requests] != list(range(len(network_requests))):
        _fail(f"role {role} network request sequence must be contiguous and ordered")
    if policy["network_access_policy"] == "FORBIDDEN":
        if network_detected or network_requests:
            _fail(f"role {role} is forbidden from network access")
    else:
        if not network_detected or not network_requests:
            _fail("role scout must record its required source-retrieval network requests")
        allowed_hosts = {
            "eutils.ncbi.nlm.nih.gov", "pubmed.ncbi.nlm.nih.gov",
            "pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov",
        }
        for request in network_requests:
            parsed = urlsplit(request["request_url"])
            if (
                parsed.scheme != "https"
                or parsed.hostname not in allowed_hosts
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in {None, 443}
                or parsed.fragment
            ):
                _fail(f"role scout network request is outside canonical NCBI HTTPS surface")

    expected_accesses: list[tuple[Any, ...]] = []
    for row in inputs:
        expected_accesses.append(
            ("READ", "INPUT", *_artifact_identity(row))
        )
    for row in outputs:
        expected_accesses.append(
            ("WRITE", "OUTPUT", *_artifact_identity(row))
        )
    for kind, ref, data_class, schema_id in (
        (
            "PROMPT_OR_COMMAND", manifest["prompt_or_command"],
            "role_prompt_or_command", "ncf.role.prompt-or-command.v1",
        ),
        (
            "PARENT_PACKET", manifest["parent_packet"],
            "role_parent_packet", "ncf.role.parent-packet.v1",
        ),
    ):
        expected_accesses.append(
            (
                "READ", kind, ref["path"], ref["sha256"], ref["bytes"], data_class, schema_id,
            )
        )
    accesses = trace["accesses"]
    if [row["sequence"] for row in accesses] != list(range(len(accesses))):
        _fail(f"role {role} tool access trace sequence must be contiguous and ordered")
    actual_accesses = [_trace_access_identity(row) for row in accesses]
    if len(actual_accesses) != len(set(actual_accesses)):
        _fail(f"role {role} tool access trace duplicates a logical access")
    if len(actual_accesses) != len(expected_accesses) or set(actual_accesses) != set(expected_accesses):
        missing = sorted(set(expected_accesses) - set(actual_accesses), key=str)
        extra = sorted(set(actual_accesses) - set(expected_accesses), key=str)
        _fail(f"role {role} tool access trace is not exact; missing={missing} extra={extra}")
    traced_input_classes = {
        row["data_class"]
        for row in accesses
        if row["operation"] == "READ" and row["artifact_kind"] == "INPUT"
    }
    if traced_input_classes != input_allowed or declared_observed != traced_input_classes:
        _fail(f"role {role} observed data classes do not match mechanically traced inputs")
    traced_classes = {row["data_class"] for row in accesses}
    if traced_classes & forbidden:
        _fail(f"role {role} trace exposes forbidden classes: {sorted(traced_classes&forbidden)}")
    return {
        "role": role,
        "run_id": manifest["run_id"],
        "manifest_path": manifest_rel,
        "input_count": len(inputs),
        "output_count": len(outputs),
        "inputs": inputs,
        "outputs": outputs,
        "started_at": start,
        "finished_at": finish,
        "trace_path": trace_rel,
        "external_producer_bindings": external_producer_bindings,
    }


def validate_role_manifest(study_root: Path, manifest_path: Path) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    manifest_rel, canonical_path, manifest_payload = _manifest_path_ref(
        root, manifest_path, "role execution manifest"
    )
    protocol, role_schema, _, trace_schema = _role_contract_inputs(root)
    manifest = _json_from_verified_bytes(manifest_payload, "role execution manifest")
    validated = _validate_role_manifest_value(
        root, manifest, protocol, role_schema, trace_schema, manifest_rel=manifest_rel
    )
    return {
        "status": "PASS",
        "role": validated["role"],
        "input_count": validated["input_count"],
        "output_count": validated["output_count"],
        "manifest_sha256": hashlib.sha256(manifest_payload).hexdigest(),
    }


def validate_role_manifest_set(study_root: Path, aggregate_path: Path) -> dict[str, Any]:
    root = study_root.resolve(strict=True)
    aggregate_rel, canonical_aggregate, aggregate_payload = _manifest_path_ref(
        root, aggregate_path, "role manifest set"
    )
    protocol, role_schema, aggregate_schema, trace_schema = _role_contract_inputs(root)
    aggregate = _json_from_verified_bytes(aggregate_payload, "role manifest set")
    _validate_schema_instance(aggregate, aggregate_schema)
    protocol_ref = aggregate["protocol"]
    protocol_rel, _ = _canonical_artifact(root, protocol_ref, "role manifest set protocol")
    if protocol_rel != "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json":
        _fail("role manifest set protocol must bind the canonical frozen protocol")

    rows_by_role: dict[str, Mapping[str, Any]] = {}
    manifests_by_role: dict[str, Mapping[str, Any]] = {}
    validated_by_role: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(aggregate["manifests"]):
        role = row["role"]
        if role in rows_by_role:
            _fail(f"role manifest set duplicates role: {role}")
        _, _, manifest_payload = _canonical_artifact_bytes(
            root, row, f"role manifest set manifests[{index}]"
        )
        manifest = _json_from_verified_bytes(manifest_payload, f"role manifest {role}")
        _validate_schema_instance(manifest, role_schema)
        if manifest.get("role") != role or manifest.get("run_id") != row.get("run_id"):
            _fail(f"role manifest set identity mismatch: {role}")
        rows_by_role[role] = row
        manifests_by_role[role] = manifest
        validated_by_role[role] = _validate_role_manifest_value(
            root, manifest, protocol, role_schema, trace_schema, manifest_rel=row["path"]
        )
    if list(rows_by_role) != EXPECTED_ROLES:
        _fail("role manifest set must list every role exactly once in frozen order")

    if len({row["run_id"] for row in aggregate["manifests"]}) != len(EXPECTED_ROLES):
        _fail("role manifest set run_id values must be unique")

    global_output_paths: dict[str, str] = {}
    global_artifact_identities: dict[str, tuple[Any, ...]] = {}
    actual_graph_edges: list[tuple[str, str]] = []
    actual_class_edges: set[tuple[str, str, str]] = set()
    actual_external_edges: set[tuple[str, str, str]] = set()
    for role in EXPECTED_ROLES:
        for artifact_row in [
            *validated_by_role[role]["inputs"], *validated_by_role[role]["outputs"]
        ]:
            identity = _artifact_identity(artifact_row)[1:]
            path = artifact_row["path"]
            previous = global_artifact_identities.get(path)
            if previous is not None and previous != identity:
                _fail(f"one artifact path is declared with conflicting identity/data class: {path}")
            global_artifact_identities[path] = identity
        for output in validated_by_role[role]["outputs"]:
            path = output["path"]
            if path in global_output_paths:
                _fail(f"multiple roles declare the same output path: {path}")
            global_output_paths[path] = role
    for consumer in EXPECTED_ROLES:
        for input_row in validated_by_role[consumer]["inputs"]:
            producer = input_row["producer"]
            if producer["kind"] == "SEALED_EXECUTABLE_OUTPUT":
                actual_external_edges.add(
                    (producer["producer_id"], consumer, input_row["data_class"])
                )
                proof = _json_from_verified_bytes(
                    next(
                        binding["proof_payload"]
                        for binding in validated_by_role[consumer][
                            "external_producer_bindings"
                        ]
                        if binding["data_class"] == input_row["data_class"]
                    ),
                    "aggregate sanitized-ledger assignment proof",
                )
                proof_inputs = {row["slot"]: row for row in proof["inputs"]}
                expected_upstream = {
                    "sealed_event_ledger": (
                        "source_auditor", "sealed_event_ledger"
                    ),
                    "sealed_availability_ledger": (
                        "source_auditor", "sealed_availability_ledger"
                    ),
                    "sealed_concept_map": ("concept_mapper", "sealed_concept_map"),
                }
                for slot, (producer_role, data_class) in expected_upstream.items():
                    expected_outputs = [
                        row
                        for row in manifests_by_role[producer_role]["outputs"]
                        if row["data_class"] == data_class
                    ]
                    if (
                        len(expected_outputs) != 1
                        or _typed_artifact_identity(proof_inputs[slot])
                        != _typed_artifact_identity(expected_outputs[0])
                    ):
                        _fail(
                            "external sanitizer proof does not bind exact role output: "
                            f"{producer_role}:{slot}"
                        )
                continue
            if producer["kind"] != "ROLE_OUTPUT":
                continue
            producer_role = producer["role"]
            producer_ref = rows_by_role.get(producer_role)
            if producer_ref is None:
                _fail(f"consumer {consumer} references producer outside aggregate: {producer_role}")
            if (
                producer["run_id"] != producer_ref["run_id"]
                or producer["manifest_path"] != producer_ref["path"]
                or producer["manifest_sha256"] != producer_ref["sha256"]
                or producer["manifest_bytes"] != producer_ref["bytes"]
            ):
                _fail(f"consumer {consumer} producer aggregate binding mismatch: {producer_role}")
            comparable = {key: input_row[key] for key in ("path", "sha256", "bytes", "data_class", "schema_id")}
            if comparable not in manifests_by_role[producer_role]["outputs"]:
                _fail(f"consumer {consumer} input is not exact aggregate producer output")
            actual_graph_edges.append((producer_role, consumer))
            actual_class_edges.add((producer_role, consumer, input_row["data_class"]))
            if validated_by_role[producer_role]["finished_at"] > validated_by_role[consumer]["started_at"]:
                _fail(f"consumer {consumer} started before producer {producer_role} finished")
    expected_class_edges = {
        (row["producer_role"], consumer, row["data_class"])
        for row in EXPECTED_PRODUCER_CONSUMER_EDGES
        for consumer in row["consumer_roles"]
    }
    if actual_class_edges != expected_class_edges:
        _fail(
            "role manifest set does not instantiate the complete frozen DAG; "
            f"missing={sorted(expected_class_edges-actual_class_edges)} "
            f"extra={sorted(actual_class_edges-expected_class_edges)}"
        )
    expected_external_edges = {
        (row["producer_id"], consumer, row["data_class"])
        for row in EXPECTED_EXTERNAL_PRODUCER_EDGES
        for consumer in row["consumer_roles"]
    }
    if actual_external_edges != expected_external_edges:
        _fail(
            "role manifest set does not instantiate exact sealed-executable edge; "
            f"missing={sorted(expected_external_edges-actual_external_edges)} "
            f"extra={sorted(actual_external_edges-expected_external_edges)}"
        )
    _assert_acyclic_roles(actual_graph_edges)
    return {
        "status": "PASS",
        "aggregate_path": aggregate_rel,
        "aggregate_sha256": hashlib.sha256(aggregate_payload).hexdigest(),
        "role_count": len(rows_by_role),
        "roles": EXPECTED_ROLES,
    }


def _write_report(path: Path | None, report: Mapping[str, Any]) -> None:
    if path is None:
        return
    if path.exists():
        _fail(f"refusing to overwrite report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=["preflight", "validate-mapper-packet", "validate-role-manifest", "validate-role-manifest-set"],
    )
    parser.add_argument("--study-root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--input", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "preflight":
            report = validate_preprimary_contracts(args.study_root)
        elif args.command == "validate-mapper-packet":
            if args.input is None:
                _fail("--input required")
            report = validate_mapper_packet(args.study_root, args.input)
        elif args.command == "validate-role-manifest":
            if args.input is None:
                _fail("--input required")
            report = validate_role_manifest(args.study_root, args.input)
        else:
            if args.input is None:
                _fail("--input required")
            report = validate_role_manifest_set(args.study_root, args.input)
        _write_report(args.report, report)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    except (ProtocolError, OSError) as exc:
        print(f"FAIL_CLOSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
