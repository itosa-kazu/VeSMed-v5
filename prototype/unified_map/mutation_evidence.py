"""Typed, content-addressed raw evidence for portable mutation executions.

This module is deliberately inert: it never runs a candidate, a compliance
probe, or a subprocess.  A producer supplies raw JSON-like preimages to
``MutationEvidenceBuilder`` during one execution.  The builder immediately
canonicalizes those preimages, stores them in a content-addressed blob table,
and emits a closed bundle whose mutation matrix is recomputed from the typed
observations.

Protocol version 2 is intentionally PRE-FREEZE.  Portable Python isolation and
external evidence custody are not complete, so every bundle carries fixed
``UCM-E002`` and ``UCM-E003`` blockers.  Those fields are code-owned and cannot
be cleared by a caller.
"""

from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .candidate_protocol import (
    DiagnoseResponse,
    Operation,
    RolloutResponse,
    StateResponse,
    _delta_from_wire,
    _diagnosis_query_from_wire,
    _history_from_wire,
    _rollout_query_from_wire,
    request_from_wire,
    response_from_wire,
)
from .mutation_matrix import (
    GATE_SPECS,
    REGISTRY_DIGEST,
    MutationObservation,
    ObservationOutcome,
    SubjectKind,
    evaluate_mutation_matrix,
)
from .schema import (
    DiagnosisQuery,
    RolloutQuery,
    VisibleDelta,
    VisibleHistory,
    event_sort_key,
)


MUTATION_EVIDENCE_PROTOCOL = "ucm-mutation-evidence-bundle/2"
MUTATION_EXECUTION_CONTEXT_PROTOCOL = "ucm-mutation-execution-context/2"
MUTATION_INPUT_PREIMAGE_PROTOCOL = "ucm-mutation-input-preimage/2"
MUTATION_PRE_SOURCE_WITNESS_PROTOCOL = "ucm-mutation-pre-source-witness/1"
MUTATION_POST_SOURCE_WITNESS_PROTOCOL = "ucm-mutation-post-source-witness/1"
MUTATION_SOURCE_RECORD_PROTOCOL = "ucm-mutation-source-record/1"
MUTATION_REPORT_TRANSCRIPT_PROTOCOL = "ucm-mutation-report-transcript/2"
MUTATION_ERROR_TRANSCRIPT_PROTOCOL = "ucm-mutation-error-transcript/1"
MUTATION_DECISION_RECORD_PROTOCOL = "ucm-mutation-decision-record/2"
MUTATION_DECISIVE_RECORD_PROTOCOL = "ucm-mutation-decisive-record/2"

BENCHMARK_ID = "UCM-BENCHMARK-v1"
PRE_FREEZE_STATUS = "PRE-FREEZE"
ISOLATION_INCOMPLETE_CODE = "UCM-E002-ISOLATION_INCOMPLETE"
HARNESS_INCOMPLETE_CODE = "UCM-E003-HARNESS_INCOMPLETE"
MUTATION_EVIDENCE_BLOCKERS = (
    ISOLATION_INCOMPLETE_CODE,
    HARNESS_INCOMPLETE_CODE,
)

_DIGEST_LENGTH = len("sha256:") + 64
_EXECUTION_BINDING_KEYS = frozenset(
    {
        "candidate_bundle_digest",
        "candidate_model_digest",
        "harness_bundle_digest",
        "import_inventory_digest",
        "module_origin",
    }
)
_HEAD_RECORD_KEYS = frozenset(
    {
        "candidate_bundle_digest",
        "candidate_model_digest",
        "consumed_state_hash",
        "harness_bundle_digest",
        "import_inventory_digest",
        "isolation",
        "module_origin",
        "operation",
        "request_digest",
        "response_digest",
        "seed",
    }
)
_REPORT_REQUIRED_FIELDS = frozenset(
    {
        "runner_protocol",
        "control_class_name",
        "expected_candidate",
        "execution_seed",
        "candidate",
        "operational_state_closure",
        "semantic_unity",
        "isolation_completeness",
        "isolation_assurance",
        "failure_codes",
        "candidate_bundle_digest",
        "candidate_model_digest",
        "harness_bundle_digest",
        "import_inventory_digest",
        "module_origin",
        "execution_binding",
        "execution_binding_error",
        "pre_source_witness_digest",
        "post_source_witness_digest",
        "post_source_witness_error",
        "harness_stable_during_execution",
        "findings",
        "head_records",
        "paired_semantic_equivalence",
        "input_preimage_digest",
        "invocation_transcript_digest",
        "request_records",
    }
)
_SOURCE_REQUIRED_FIELDS = frozenset(
    {
        "runner_protocol",
        "execution_bound_source_witness",
        "execution_bound_source_witness_digest",
        "harness_stable_during_execution",
        "post_source_witness_digest",
        "pre_source_witness_digest",
    }
)
_FINDING_KEYS = frozenset(
    {"gate", "verdict", "failure_code", "detail", "evidence"}
)
_PAIRED_EVIDENCE_KEYS = frozenset(
    {
        "protocol",
        "comparison",
        "absolute_tolerance",
        "relative_tolerance",
        "phases",
        "passed",
    }
)
_PAIRED_PHASE_KEYS = frozenset(
    {
        "phase",
        "honest_state_digest",
        "affine_state_digest",
        "state_serializations_distinct",
        "honest_behavior_digest",
        "affine_behavior_digest",
        "semantic_behavior_equivalent",
    }
)
_INPUT_PREIMAGE_KEYS = frozenset(
    {"history", "diagnosis_query", "rollout_query", "delta"}
)
_REQUEST_RECORD_KEYS = frozenset(
    {
        "operation",
        "seed",
        "execution_mode",
        "executor_protocol",
        "parent_pid",
        "worker_pid",
        "isolation",
        "import_inventory_digest",
        "harness_bundle_digest",
        "candidate_bundle_digest",
        "candidate_model_digest",
        "module_origin",
        "invocation_nonce",
        "executor_receipt",
        "status",
        "request_wire",
        "request_digest",
        "request_fully_sent",
        "received_request_digest",
        "response_wire",
        "response_digest",
        "failure_origin",
        "failure_code",
    }
)
_EXECUTION_CONTEXT_KEYS = frozenset(
    {
        "benchmark_id",
        "runtime_metadata",
        "portable_runner_contract",
        "runtime_import_cache_contract_digest",
        "source_preparation_error",
    }
)
_SOURCE_PREPARATION_ERROR_KEYS = frozenset(
    {"stage", "exception_type", "message"}
)
_EXECUTION_ERROR_KEYS = _SOURCE_PREPARATION_ERROR_KEYS
_SOURCE_WITNESS_KEYS = frozenset(
    {
        "protocol",
        "control",
        "execution_seed",
        "control_mro",
        "source_identity_anchors",
        "external_attribute_identities",
        "external_global_dispatch",
        "external_class_surfaces",
        "external_runtime_object_identities",
        "external_runtime_values",
        "runtime_import_cache",
        "module_source_digests",
        "live_module_code_bindings",
        "live_detector_code_digests",
        "live_protocol_code_digests",
        "live_runtime_constants",
        "freeze_critical_runtime_contract",
        "critical_alias_identities",
        "expected_candidate",
        "expected_live_execution_binding",
        "portable_runner_contract",
        "semantic_probe_contract",
        "enabled_semantic_probes",
        "runtime_metadata",
    }
)
_SOURCE_WITNESS_LIST_FIELDS = frozenset(
    {
        "control_mro",
        "source_identity_anchors",
        "external_attribute_identities",
        "external_class_surfaces",
        "external_runtime_object_identities",
        "critical_alias_identities",
    }
)
_SOURCE_WITNESS_OBJECT_FIELDS = frozenset(
    {
        "external_global_dispatch",
        "external_runtime_values",
        "runtime_import_cache",
        "module_source_digests",
        "live_module_code_bindings",
        "live_detector_code_digests",
        "live_protocol_code_digests",
        "live_runtime_constants",
        "freeze_critical_runtime_contract",
        "expected_live_execution_binding",
        "portable_runner_contract",
        "runtime_metadata",
    }
)
_CANONICAL_FAILURE_CODES_BY_GATE = {
    gate.gate_id: frozenset(gate.allowed_failure_codes) for gate in GATE_SPECS
}
_CANONICAL_FAILURE_CODES = frozenset(
    failure_code
    for failure_codes in _CANONICAL_FAILURE_CODES_BY_GATE.values()
    for failure_code in failure_codes
)
_MUTANT_DECISION_KEYS = frozenset(
    {
        "runner_protocol",
        "decision_kind",
        "expected_gate",
        "expected_failure_code",
        "report_available",
        "harness_stable_during_execution",
        "execution_binding_complete",
        "harness_incomplete",
        "decision_processing_complete",
        "derived_outcome",
        "actual_gate",
        "actual_failure_code",
        "input_preimage_digest",
        "invocation_transcript_digest",
    }
)
_SPECIFICITY_DECISION_KEYS = frozenset(
    {
        "runner_protocol",
        "decision_kind",
        "classification",
        "report_available",
        "harness_stable_during_execution",
        "execution_binding_complete",
        "probe_incomplete",
        "report_processing_complete",
        "semantic_equivalence_passed",
        "derived_outcome",
        "input_preimage_digest",
        "invocation_transcript_digest",
    }
)
_ALLOWED_SCOPE_INCOMPLETE_CODES = frozenset(
    {
        "UCM-E001-SEMANTIC_UNITY_UNVERIFIED",
        ISOLATION_INCOMPLETE_CODE,
    }
)
_FIXED_SCOPE_FINDINGS = frozenset(
    {
        (
            "semantic-unity-boundary",
            "incomplete",
            "UCM-E001-SEMANTIC_UNITY_UNVERIFIED",
        ),
        (
            "portable-isolation-boundary",
            "incomplete",
            ISOLATION_INCOMPLETE_CODE,
        ),
    }
)
# This is the code-owned portable execution registry, not caller metadata.  The
# full matrix registry remains bound separately by REGISTRY_DIGEST; these are
# the rows for which mutation_runner has an executable compliance control.
_PORTABLE_MUTATION_CONTRACTS = (
    ("GlobalSecondState", "GlobalSecondStateControl", "C04", "UCM-F006-HIDDEN_PATIENT_CACHE", (), "replay_ddrr"),
    ("FileHandleState", "FileHandleStateControl", "C07", "UCM-F008-STATE_NOT_CLOSED", (), "empty"),
    ("RawHistoryHead", "RawHistoryHeadControl", "C02", "UCM-F004-HEAD_HISTORY_ACCESS", (), "empty"),
    ("TrainerTargetSmuggler", "TrainerTargetSmugglerControl", "C08", "UCM-F002-ORACLE_TRUE_STATE_ACCESS", (), "empty"),
    ("QueryReencoder", "QueryReencoderControl", "C02", "UCM-F004-HEAD_HISTORY_ACCESS", (), "empty"),
    ("MutableCheckpoint", "MutableCheckpointControl", "C06", "UCM-F009-MODEL_MUTATION", (), "empty"),
    ("TrueStateReader", "TrueStateReaderControl", "C08", "UCM-F002-ORACLE_TRUE_STATE_ACCESS", (), "empty"),
    ("FutureReader", "FutureReaderControl", "C08", "UCM-F001-FUTURE_LEAK", (), "empty"),
    ("CounterfactualMutator", "QueryMutatorControl", "C16", "UCM-F012-QUERY_MUTATES_FACT", (), "empty"),
    ("ImplicitRNGState", "ImplicitRNGControl", "C30", "UCM-F020-NONREPRODUCIBLE", (), "replay_ddrr"),
    ("HistoryInBlob", "HistoryInBlobControl", "C27", "UCM-F018-FULL_HISTORY_MISCLAIM", ("full_history_disclosure",), "replay_ddrr"),
    ("WarmFutureCache", "WarmFutureCacheControl", "C23", "UCM-F001-FUTURE_LEAK", ("warm_future_old_cut",), "replay_ddrr"),
    ("ReplayBatchDivergence", "ReplayBatchDivergenceControl", "C22", "UCM-F019-UPDATE_INCONSISTENT", ("update_consistency",), "replay_ddrr"),
    ("DoubleCountEvent", "DoubleCountEventControl", "C22", "UCM-F019-UPDATE_INCONSISTENT", ("update_consistency",), "replay_ddrr"),
    ("NonIdPointEstimate", "NonIdPointEstimateControl", "C19", "UCM-F015-CONDITIONING_AS_INTERVENTION", ("nonidentified_set",), "replay_ddrr"),
    ("DangerousMeanCompressor", "DangerousMeanCompressorControl", "C24", "UCM-F016-DANGEROUS_COLLISION", ("dangerous_collision",), "replay_ddrr"),
    ("UnsafeClosedWorld", "UnsafeClosedWorldControl", "C25", "UCM-F017-OOD_FORCED_MATCH", ("unsafe_closed_world",), "replay_ddrr"),
)
# Empty head records mean that the candidate failed before a successful head
# response could be materialized; they do not mean that an arbitrary prefix is
# decisive evidence.  These are the exact live request stages reached by each
# code-owned empty-head subject.  The final row is always the sole candidate
# worker error and therefore no later request may be fabricated.
_EMPTY_HEAD_TERMINAL_REQUEST_TOPOLOGIES = {
    "FileHandleState": (("initialize", 0, "worker_error"),),
    "RawHistoryHead": (
        ("initialize", 0, "success"),
        ("initialize", 0, "success"),
        ("diagnose", 1, "worker_error"),
    ),
    "TrainerTargetSmuggler": (("initialize", 0, "worker_error"),),
    "QueryReencoder": (
        ("initialize", 0, "success"),
        ("initialize", 0, "success"),
        ("diagnose", 1, "worker_error"),
    ),
    "MutableCheckpoint": (("initialize", 0, "worker_error"),),
    "TrueStateReader": (
        ("initialize", 0, "success"),
        ("initialize", 0, "success"),
        ("diagnose", 1, "worker_error"),
    ),
    "FutureReader": (
        ("initialize", 0, "success"),
        ("initialize", 0, "success"),
        ("diagnose", 1, "success"),
        ("diagnose", 1, "success"),
        ("rollout", 2, "worker_error"),
    ),
    "CounterfactualMutator": (
        ("initialize", 0, "success"),
        ("initialize", 0, "success"),
        ("diagnose", 1, "success"),
        ("diagnose", 1, "success"),
        ("rollout", 2, "worker_error"),
    ),
}
_PORTABLE_SPECIFICITY_CONTRACTS = (
    (
        "ExplicitSeedStochasticState",
        "HonestSeededControl",
        "ordinary_candidate",
        ("full_history_disclosure", "update_consistency", "warm_future_old_cut"),
        "replay_ddrr",
    ),
    (
        "BehaviorEquivalentSerialization",
        "BehaviorEquivalentSerializationControl",
        "ordinary_candidate",
        ("update_consistency",),
        "replay_ddrr",
    ),
    (
        "DeclaredFullHistoryBaseline",
        "DeclaredFullHistoryBaselineControl",
        "baseline_only",
        ("full_history_disclosure",),
        "replay_ddrr",
    ),
    (
        "CorrectNonidentifiedSet",
        "CorrectNonidentifiedSetControl",
        "ordinary_candidate",
        ("nonidentified_set",),
        "replay_ddrr",
    ),
)
_PORTABLE_SEMANTIC_PROBE_PROTOCOL = "ucm-portable-semantic-probes/5"
UPDATE_CONSISTENCY_LINEAGE_XOR_MASK = 0x6A09E667F3BCC909
_SUBJECT_ENVELOPE_KEYS = frozenset(
    {
        "protocol",
        "run_id",
        "execution_context_digest",
        "subject_id",
        "subject_kind",
        "execution_seed",
        "references",
        "payload",
    }
)


def _closed_object(value: object, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ProtocolViolation(
            f"{label} must be a closed object with keys {sorted(keys)!r}"
        )
    return value


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise ProtocolViolation(f"{label} contains an invalid Unicode surrogate") from exc
    return value


def _digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or len(value) != _DIGEST_LENGTH
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    return value


def _seed(value: object, label: str) -> int:
    if type(value) is not int or not 0 <= value < 2**64:
        raise ProtocolViolation(f"{label} must be an unsigned 64-bit integer")
    return value


def _optional_digest(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _digest(value, label)


def _canonical_bytes(value: Any, label: str) -> bytes:
    """Normalize every JSON encoding failure to the protocol exception type."""

    try:
        return canonical_json_bytes(value)
    except ProtocolViolation:
        raise
    except (UnicodeEncodeError, RecursionError, TypeError, ValueError, OverflowError) as exc:
        raise ProtocolViolation(f"{label} cannot be canonically encoded") from exc


def _json_digest(value: Any, label: str) -> str:
    try:
        return digest_json(value)
    except ProtocolViolation:
        raise
    except (UnicodeEncodeError, RecursionError, TypeError, ValueError, OverflowError) as exc:
        raise ProtocolViolation(f"{label} cannot be canonically digested") from exc


def _module_origin(value: object, label: str) -> str:
    origin = _name(value, label)
    if (
        origin.startswith("/")
        or "\\" in origin
        or ":" in origin
        or any(part in {"", ".", ".."} for part in origin.split("/"))
    ):
        raise ProtocolViolation(
            f"{label} must be a canonical bundle-relative POSIX path"
        )
    return origin


def _expected_module_origin(candidate: str) -> str:
    module_name, separator, qualname = candidate.partition(":")
    if (
        separator != ":"
        or not module_name
        or not qualname
        or module_name.strip() != module_name
        or qualname.strip() != qualname
    ):
        raise ProtocolViolation("code-owned candidate identity is malformed")
    return _module_origin(
        module_name.replace(".", "/") + ".py",
        "code-owned candidate module_origin",
    )


def _portable_subject_identity(
    observation: MutationObservation,
) -> tuple[
    str,
    str,
    int,
    str | None,
    str | None,
    str | None,
    tuple[str, ...],
    str,
]:
    rows: list[
        tuple[
            str,
            str,
            str,
            int,
            str | None,
            str | None,
            str | None,
            tuple[str, ...],
            str,
        ]
    ] = []
    rows.extend(
        (
            "mutant",
            subject_id,
            control,
            index,
            None,
            gate,
            code,
            probes,
            head_record_shape,
        )
        for index, (
            subject_id,
            control,
            gate,
            code,
            probes,
            head_record_shape,
        ) in enumerate(
            _PORTABLE_MUTATION_CONTRACTS
        )
    )
    rows.extend(
        (
            "specificity_control",
            subject_id,
            control,
            len(_PORTABLE_MUTATION_CONTRACTS) + index,
            classification,
            None,
            None,
            probes,
            head_record_shape,
        )
        for index, (
            subject_id,
            control,
            classification,
            probes,
            head_record_shape,
        ) in enumerate(
            _PORTABLE_SPECIFICITY_CONTRACTS
        )
    )
    matches = [
        (
            control,
            row_index,
            classification,
            gate,
            code,
            probes,
            head_record_shape,
        )
        for (
            subject_kind,
            subject_id,
            control,
            row_index,
            classification,
            gate,
            code,
            probes,
            head_record_shape,
        ) in rows
        if (subject_kind, subject_id)
        == (observation.subject_kind.value, observation.subject_id)
    ]
    if len(matches) != 1:
        raise ProtocolViolation(
            "mutation evidence subject is not in the code-owned portable registry"
        )
    (
        control,
        row_index,
        classification,
        gate,
        code,
        probes,
        head_record_shape,
    ) = matches[0]
    return (
        control,
        f"prototype.unified_map.compliance:{control}",
        row_index,
        classification,
        gate,
        code,
        probes,
        head_record_shape,
    )


def portable_runner_contract(runner_protocol: str) -> dict[str, Any]:
    """Return the code-owned full portable registry for execution context binding."""

    _name(runner_protocol, "portable runner contract runner_protocol")
    return {
        "runner_protocol": runner_protocol,
        "runner_semantic_probe_protocol_alias": _PORTABLE_SEMANTIC_PROBE_PROTOCOL,
        "update_consistency_lineage_xor_mask": (
            UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
        ),
        "mutation_cases": [
            {
                "matrix_subject_id": subject_id,
                "control_class_name": control,
                "decisive_gate": gate,
                "expected_failure_code": failure_code,
                "semantic_probes": list(probes),
                "head_record_shape": head_record_shape,
            }
            for (
                subject_id,
                control,
                gate,
                failure_code,
                probes,
                head_record_shape,
            ) in _PORTABLE_MUTATION_CONTRACTS
        ],
        "specificity_cases": [
            {
                "subject_id": subject_id,
                "control_class_name": control,
                "classification": classification,
                "semantic_probes": list(probes),
                "head_record_shape": head_record_shape,
            }
            for (
                subject_id,
                control,
                classification,
                probes,
                head_record_shape,
            ) in _PORTABLE_SPECIFICITY_CONTRACTS
        ],
    }


def _validate_base_seed_execution_domain(base_seed: object, label: str) -> int:
    """Mirror every code-owned portable row's uint64 seed preconditions."""

    checked_base_seed = _seed(base_seed, label)
    row_profiles = tuple(
        (index, probes)
        for index, (*_identity, probes, _head_record_shape) in enumerate(
            _PORTABLE_MUTATION_CONTRACTS
        )
    ) + tuple(
        (len(_PORTABLE_MUTATION_CONTRACTS) + index, probes)
        for index, (*_identity, probes, _head_record_shape) in enumerate(
            _PORTABLE_SPECIFICITY_CONTRACTS
        )
    )
    for row_index, semantic_probes in row_profiles:
        execution_seed = checked_base_seed + row_index
        if execution_seed + 3 >= 2**64:
            raise ProtocolViolation(
                f"{label} and all code-owned derived operation seeds must fit "
                "unsigned 64-bit integer"
            )
        if (
            "update_consistency" in semantic_probes
            and (
                execution_seed ^ UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
            )
            + 2
            >= 2**64
        ):
            raise ProtocolViolation(
                f"{label} code-owned update-consistency lineage seeds must fit "
                "unsigned 64-bit integer"
            )
    return checked_base_seed


def _decode_canonical_json(payload: bytes, label: str) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation(f"{label} payload must be exact bytes")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProtocolViolation(f"{label} is not UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be a JSON object")
    try:
        canonical = _canonical_bytes(value, label)
    except ProtocolViolation as exc:
        if isinstance(exc.__cause__, UnicodeEncodeError):
            raise ProtocolViolation(
                f"{label} contains an invalid Unicode surrogate"
            ) from exc
        raise
    if canonical != payload:
        raise ProtocolViolation(f"{label} is not canonical JSON bytes")
    return value


@dataclass(frozen=True, slots=True)
class ContentAddressedBlob:
    """One exact byte preimage, addressed only by its SHA-256 digest."""

    payload: bytes

    def __post_init__(self) -> None:
        if type(self.payload) is not bytes:
            raise ProtocolViolation("blob payload must be exact bytes")

    @property
    def digest(self) -> str:
        return digest_bytes(self.payload)

    def to_wire(self) -> dict[str, Any]:
        return {
            "bytes": len(self.payload),
            "encoding": "base64",
            "payload_b64": base64.b64encode(self.payload).decode("ascii"),
            "sha256": self.digest,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ContentAddressedBlob":
        body = _closed_object(
            value,
            frozenset({"bytes", "encoding", "payload_b64", "sha256"}),
            "content-addressed blob",
        )
        if body["encoding"] != "base64":
            raise ProtocolViolation("blob encoding must be base64")
        if type(body["bytes"]) is not int or body["bytes"] < 0:
            raise ProtocolViolation("blob bytes must be a non-negative exact int")
        encoded = body["payload_b64"]
        if type(encoded) is not str:
            raise ProtocolViolation("blob payload_b64 must be an exact string")
        try:
            payload = base64.b64decode(encoded.encode("ascii"), validate=True)
        except (UnicodeEncodeError, ValueError) as exc:
            raise ProtocolViolation("blob payload_b64 is not valid base64") from exc
        if base64.b64encode(payload).decode("ascii") != encoded:
            raise ProtocolViolation("blob payload_b64 is not canonical base64")
        if len(payload) != body["bytes"]:
            raise ProtocolViolation("blob byte length does not match payload")
        claimed = _digest(body["sha256"], "blob sha256")
        blob = cls(payload)
        if blob.digest != claimed:
            raise ProtocolViolation("blob sha256 does not match payload bytes")
        return blob


def _observation_from_wire(value: object) -> MutationObservation:
    body = _closed_object(
        value,
        frozenset(
            {
                "subject_id",
                "subject_kind",
                "source_digest",
                "execution_seed",
                "outcome",
                "actual_gate",
                "actual_failure_code",
                "decisive_record_digest",
                "classification",
            }
        ),
        "mutation observation",
    )
    try:
        subject_kind = SubjectKind(body["subject_kind"])
        outcome = ObservationOutcome(body["outcome"])
    except (TypeError, ValueError) as exc:
        raise ProtocolViolation("mutation observation contains an unknown enum") from exc
    return MutationObservation(
        subject_id=body["subject_id"],
        subject_kind=subject_kind,
        source_digest=body["source_digest"],
        execution_seed=body["execution_seed"],
        outcome=outcome,
        actual_gate=body["actual_gate"],
        actual_failure_code=body["actual_failure_code"],
        decisive_record_digest=body["decisive_record_digest"],
        classification=body["classification"],
    )


@dataclass(frozen=True, slots=True)
class MutationEvidenceRecord:
    """Typed references from one matrix observation to all raw preimages."""

    run_id: str
    execution_context_digest: str
    observation: MutationObservation
    pre_source_witness_digest: str
    post_source_witness_digest: str
    source_record_digest: str
    report_transcript_digest: str | None
    error_transcript_digest: str
    decision_record_digest: str

    def __post_init__(self) -> None:
        _name(self.run_id, "evidence record run_id")
        _digest(self.execution_context_digest, "record execution_context_digest")
        if type(self.observation) is not MutationObservation:
            raise ProtocolViolation("record observation must be MutationObservation")
        _seed(self.observation.execution_seed, "record observation execution_seed")
        for field_name in (
            "pre_source_witness_digest",
            "post_source_witness_digest",
            "source_record_digest",
            "error_transcript_digest",
            "decision_record_digest",
        ):
            _digest(getattr(self, field_name), f"record {field_name}")
        _optional_digest(
            self.report_transcript_digest, "record report_transcript_digest"
        )
        if self.observation.source_digest != self.source_record_digest:
            raise ProtocolViolation(
                "observation source_digest must equal source_record_digest"
            )
        if self.observation.outcome in {
            ObservationOutcome.KILLED,
            ObservationOutcome.PASSED,
        }:
            if self.observation.decisive_record_digest is None:
                raise ProtocolViolation("killed/passed observation needs decisive record")
            if self.report_transcript_digest is None:
                raise ProtocolViolation("killed/passed observation needs report transcript")
        elif self.observation.decisive_record_digest is not None:
            raise ProtocolViolation(
                "non-killed/non-passed observation cannot claim a decisive record"
            )
        if self.observation.subject_kind is SubjectKind.MUTANT:
            if self.observation.outcome not in {
                ObservationOutcome.KILLED,
                ObservationOutcome.SURVIVED,
                ObservationOutcome.CRASHED,
                ObservationOutcome.TIMED_OUT,
            }:
                raise ProtocolViolation("mutant observation has an invalid outcome")
            if self.observation.classification is not None:
                raise ProtocolViolation("mutant observation cannot have classification")
        else:
            if self.observation.outcome not in {
                ObservationOutcome.PASSED,
                ObservationOutcome.REJECTED,
                ObservationOutcome.CRASHED,
                ObservationOutcome.TIMED_OUT,
            }:
                raise ProtocolViolation("specificity observation has an invalid outcome")
            if self.observation.classification is None:
                raise ProtocolViolation(
                    "specificity observation requires a classification"
                )
        if self.observation.outcome is ObservationOutcome.KILLED:
            if (
                self.observation.actual_gate is None
                or self.observation.actual_failure_code is None
            ):
                raise ProtocolViolation("killed observation needs gate and failure code")
        elif (
            self.observation.actual_gate is not None
            or self.observation.actual_failure_code is not None
        ):
            raise ProtocolViolation(
                "only a killed observation may carry gate/failure code"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "execution_context_digest": self.execution_context_digest,
            "observation": self.observation.to_wire(),
            "pre_source_witness_digest": self.pre_source_witness_digest,
            "post_source_witness_digest": self.post_source_witness_digest,
            "source_record_digest": self.source_record_digest,
            "report_transcript_digest": self.report_transcript_digest,
            "error_transcript_digest": self.error_transcript_digest,
            "decision_record_digest": self.decision_record_digest,
        }

    @classmethod
    def from_wire(cls, value: object) -> "MutationEvidenceRecord":
        body = _closed_object(
            value,
            frozenset(
                {
                    "run_id",
                    "execution_context_digest",
                    "observation",
                    "pre_source_witness_digest",
                    "post_source_witness_digest",
                    "source_record_digest",
                    "report_transcript_digest",
                    "error_transcript_digest",
                    "decision_record_digest",
                }
            ),
            "mutation evidence record",
        )
        return cls(
            run_id=body["run_id"],
            execution_context_digest=body["execution_context_digest"],
            observation=_observation_from_wire(body["observation"]),
            pre_source_witness_digest=body["pre_source_witness_digest"],
            post_source_witness_digest=body["post_source_witness_digest"],
            source_record_digest=body["source_record_digest"],
            report_transcript_digest=body["report_transcript_digest"],
            error_transcript_digest=body["error_transcript_digest"],
            decision_record_digest=body["decision_record_digest"],
        )


def _record_sort_key(record: MutationEvidenceRecord) -> tuple[str, str, int, str]:
    row = record.observation
    return (
        row.subject_kind.value,
        row.subject_id,
        row.execution_seed,
        row.source_digest,
    )


def _subject_envelope(
    *,
    protocol: str,
    run_id: str,
    execution_context_digest: str,
    subject_id: str,
    subject_kind: SubjectKind,
    execution_seed: int,
    references: dict[str, Any],
    payload: Any,
) -> dict[str, Any]:
    if type(references) is not dict:
        raise ProtocolViolation("subject envelope references must be an exact dict")
    validate_json_like(references, path="$.references")
    validate_json_like(payload, path="$.payload")
    return {
        "protocol": protocol,
        "run_id": run_id,
        "execution_context_digest": execution_context_digest,
        "subject_id": subject_id,
        "subject_kind": subject_kind.value,
        "execution_seed": execution_seed,
        "references": references,
        "payload": payload,
    }


def _validate_subject_blob(
    payload: bytes,
    *,
    protocol: str,
    record: MutationEvidenceRecord,
    expected_references: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    body = _closed_object(
        _decode_canonical_json(payload, label),
        _SUBJECT_ENVELOPE_KEYS,
        label,
    )
    expected = {
        "protocol": protocol,
        "run_id": record.run_id,
        "execution_context_digest": record.execution_context_digest,
        "subject_id": record.observation.subject_id,
        "subject_kind": record.observation.subject_kind.value,
        "execution_seed": record.observation.execution_seed,
    }
    for key, value in expected.items():
        if body[key] != value:
            raise ProtocolViolation(f"{label} {key} binding mismatch")
    if body["references"] != expected_references:
        raise ProtocolViolation(f"{label} reference binding mismatch")
    validate_json_like(body["payload"], path=f"$.{label}.payload")
    return body


def _finding_gate_tokens(value: object) -> frozenset[str]:
    if type(value) is not str:
        raise ProtocolViolation("report finding gate must be an exact string")
    return frozenset(
        token
        for token in value.replace("/", " ").replace("-", " ").split()
        if len(token) == 3 and token.startswith("C") and token[1:].isdigit()
    )


def _payload_object(body: dict[str, Any], label: str) -> dict[str, Any]:
    payload = body["payload"]
    if type(payload) is not dict:
        raise ProtocolViolation(f"{label} payload must be an exact object")
    return payload


def _typed_input_preimage(
    value: object,
) -> tuple[VisibleHistory, DiagnosisQuery, RolloutQuery, VisibleDelta | None]:
    """Parse the four runner inputs through the executable wire protocols.

    A JSON object merely shaped *like* an input is not evidence of the input
    that the candidate protocol can consume.  The round trips below bind this
    bundle to the same closed parsers and canonical wire encoders used at the
    candidate boundary.
    """

    body = _closed_object(value, _INPUT_PREIMAGE_KEYS, "input preimage payload")
    try:
        history = _history_from_wire(body["history"])
        diagnosis_query = _diagnosis_query_from_wire(body["diagnosis_query"])
        rollout_query = _rollout_query_from_wire(body["rollout_query"])
        delta = (
            None if body["delta"] is None else _delta_from_wire(body["delta"])
        )
    except ProtocolViolation:
        raise
    except (TypeError, ValueError) as exc:  # pragma: no cover - parser guard.
        raise ProtocolViolation("input preimage failed typed protocol parsing") from exc
    round_trips = (
        ("history", history.to_wire()),
        ("diagnosis_query", diagnosis_query.to_wire()),
        ("rollout_query", rollout_query.to_wire()),
        ("delta", None if delta is None else delta.to_wire()),
    )
    for field_name, round_trip in round_trips:
        if body[field_name] != round_trip:
            raise ProtocolViolation(
                f"input preimage {field_name} is not an exact typed wire round trip"
            )
    return history, diagnosis_query, rollout_query, delta


def _merged_input_history(
    history: VisibleHistory, delta: VisibleDelta | None
) -> VisibleHistory | None:
    if delta is None or delta.advance_to < history.as_of_available_at:
        return None
    existing = {event.event_uid for event in history.events}
    if any(event.event_uid in existing for event in delta.events):
        return None
    return VisibleHistory(
        events=tuple(sorted(history.events + delta.events, key=event_sort_key)),
        as_of_available_at=delta.advance_to,
        catalog_digest=history.catalog_digest,
    )


def _scored_semantic_projection(response: object) -> dict[str, Any]:
    """Project a typed head response onto the frozen scored surface.

    This deliberately mirrors the compliance probe rather than comparing a
    response digest: metadata and diagnostics are not diagnosis/rollout
    semantics and therefore cannot prove or disprove F001/F019.
    """

    if isinstance(response, DiagnoseResponse):
        return {
            "operation": "diagnose",
            "status": response.result.status.value,
            "probabilities": response.result.probabilities,
        }
    if isinstance(response, RolloutResponse):
        return {
            "operation": "rollout",
            "status": response.result.status.value,
            "observable_predictions": response.result.observable_predictions,
            "utility_prediction": response.result.utility_prediction,
        }
    raise ProtocolViolation("semantic projection requires a typed head response")


def _scored_semantic_equal(left: object, right: object) -> bool:
    """Use the compliance protocol's frozen recursive numeric comparator."""

    if type(left) is bool or type(right) is bool:
        return type(left) is type(right) and left == right
    if type(left) in {int, float} and type(right) in {int, float}:
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-9)
    if type(left) is not type(right):
        return False
    if type(left) is dict:
        return set(left) == set(right) and all(
            _scored_semantic_equal(left[key], right[key]) for key in left
        )
    if type(left) is list:
        return len(left) == len(right) and all(
            _scored_semantic_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def _validate_request_records(
    value: object,
    *,
    input_preimage_digest: str,
    history: VisibleHistory,
    diagnosis_query: DiagnosisQuery,
    rollout_query: RolloutQuery,
    delta: VisibleDelta | None,
    execution_seed: int,
    expected_subject_id: str,
    expected_failure_code: str | None,
    expected_semantic_probes: tuple[str, ...],
    expected_head_record_shape: str,
    observation_outcome: ObservationOutcome,
    head_records: list[dict[str, Any]],
    expected_execution_binding: dict[str, str] | None = None,
) -> tuple[str, frozenset[str], dict[str, Any]]:
    """Validate an ordered, exact invocation transcript and its state lineage."""

    _digest(input_preimage_digest, "request transcript input_preimage_digest")
    if type(value) is not list:
        raise ProtocolViolation("report request_records must be an exact list")

    history_wire = history.to_wire()
    diagnosis_wire = diagnosis_query.to_wire()
    rollout_wire = rollout_query.to_wire()
    delta_wire = None if delta is None else delta.to_wire()
    merged = _merged_input_history(history, delta)
    merged_wire = None if merged is None else merged.to_wire()
    from . import compliance as compliance_module

    evaluator_probe_counts = compliance_module.EVALUATOR_PROBE_REQUEST_COUNTS
    evaluator_probe_order = tuple(
        probe
        for probe in compliance_module._EVALUATOR_PROBE_ORDER
        if probe in expected_semantic_probes
    )
    main_length = 8 if delta is not None else 6
    evaluator_start = main_length
    if "update_consistency" in expected_semantic_probes:
        evaluator_start += 10
    if "warm_future_old_cut" in expected_semantic_probes:
        evaluator_start += 7
    evaluator_ranges: dict[str, tuple[int, int]] = {}
    cursor = evaluator_start
    for probe in evaluator_probe_order:
        count = evaluator_probe_counts[probe]
        evaluator_ranges[probe] = (cursor, cursor + count)
        cursor += count
    evaluator_indices = frozenset(
        index
        for start, end in evaluator_ranges.values()
        for index in range(start, end)
    )
    matching_control_names = [
        row[1]
        for row in (*_PORTABLE_MUTATION_CONTRACTS, *_PORTABLE_SPECIFICITY_CONTRACTS)
        if row[0] == expected_subject_id
    ]
    if len(matching_control_names) != 1:
        raise ProtocolViolation("request transcript subject has no unique control")
    expected_control_class_name = matching_control_names[0]
    decisive = observation_outcome in {
        ObservationOutcome.KILLED,
        ObservationOutcome.PASSED,
    }
    merged_history_probes = frozenset(
        {"update_consistency", "warm_future_old_cut"}
    )
    if (
        decisive
        and merged_history_probes.intersection(expected_semantic_probes)
        and merged is None
    ):
        raise ProtocolViolation(
            "decisive semantic probe transcript requires a non-null, formally "
            "mergeable input delta"
        )
    lineage_seed = execution_seed ^ UPDATE_CONSISTENCY_LINEAGE_XOR_MASK
    allowed_seeds = {
        Operation.INITIALIZE: {execution_seed, lineage_seed},
        Operation.DIAGNOSE: {execution_seed + 1, lineage_seed + 1},
        Operation.ROLLOUT: {execution_seed + 2, lineage_seed + 2},
        Operation.UPDATE: {execution_seed + 3, lineage_seed},
    }

    successful_state_wires: list[dict[str, Any]] = []
    success_records: list[dict[str, Any]] = []
    record_statuses: list[str] = []
    sent_coverage: set[str] = set()
    main_attempts: dict[Operation, int] = {operation: 0 for operation in Operation}
    main_successes: dict[Operation, int] = {operation: 0 for operation in Operation}
    fresh_main_sequence: list[tuple[str, int]] = []
    fresh_main_positions: list[int] = []
    fresh_main_records: list[dict[str, Any]] = []
    typed_responses: list[object | None] = []
    actual_probe_evidence: dict[str, Any] = {}
    invocation_nonces: list[str] = []
    executor_receipts: list[str] = []
    observed_code_owned_bindings: list[dict[str, str]] = []

    for index, record_value in enumerate(value):
        record = _closed_object(
            record_value,
            _REQUEST_RECORD_KEYS,
            f"request record {index}",
        )
        validated_record_bytes = compliance_module._validated_request_record_bytes(
            record
        )
        if validated_record_bytes != _canonical_bytes(
            record, f"request record {index}"
        ):
            raise ProtocolViolation(
                f"request record {index} differs from the code-owned canonical "
                "executor receipt"
            )
        invocation_nonces.append(record["invocation_nonce"])
        executor_receipts.append(record["executor_receipt"])
        executor_binding_fields = (
            "candidate_bundle_digest",
            "candidate_model_digest",
            "harness_bundle_digest",
            "import_inventory_digest",
            "module_origin",
        )
        if record["executor_protocol"] == (
            compliance_module._UNVERIFIED_EXECUTOR_RECEIPT_PROTOCOL
        ):
            if any(record[field] is not None for field in executor_binding_fields):
                raise ProtocolViolation(
                    "unverified executor record cannot claim a live source binding"
                )
        else:
            if decisive and any(
                record[field] is None for field in executor_binding_fields
            ):
                raise ProtocolViolation(
                    "decisive code-owned executor record lacks its live source binding"
                )
            if all(record[field] is not None for field in executor_binding_fields):
                observed_code_owned_bindings.append(
                    {field: record[field] for field in executor_binding_fields}
                )
        if decisive and evaluator_probe_order:
            expected_executor_protocol = {
                "fresh": compliance_module._FRESH_EXECUTOR_RECEIPT_PROTOCOL,
                "sequential": (
                    compliance_module._SEQUENTIAL_EXECUTOR_RECEIPT_PROTOCOL
                ),
            }.get(record["execution_mode"])
            expected_isolation = {
                "fresh": compliance_module._FRESH_ISOLATION_PROTOCOL,
                "sequential": compliance_module._SEQUENTIAL_ISOLATION_PROTOCOL,
            }.get(record["execution_mode"])
            if (
                record["executor_protocol"] != expected_executor_protocol
                or record["isolation"] != expected_isolation
                or type(record["worker_pid"]) is not int
                or record["worker_pid"] == record["parent_pid"]
            ):
                raise ProtocolViolation(
                    "decisive evaluator transcript requires exact code-owned "
                    "fresh/sequential process receipts"
                )
        if record["execution_mode"] not in {"fresh", "sequential"}:
            raise ProtocolViolation(
                f"request record {index} execution_mode must be fresh or sequential"
            )
        if record["status"] not in {"success", "worker_error", "harness_error"}:
            raise ProtocolViolation(f"request record {index} has an unknown status")
        try:
            request = request_from_wire(record["request_wire"])
        except ProtocolViolation as exc:
            raise ProtocolViolation(
                f"request record {index} request_wire is not a typed request"
            ) from exc
        if _canonical_bytes(
            request.to_wire(), f"request record {index} typed request"
        ) != _canonical_bytes(
            record["request_wire"], f"request record {index} request_wire"
        ):
            raise ProtocolViolation(
                f"request record {index} request_wire is not an exact round trip"
            )
        operation = request.operation
        if record["operation"] != operation.value or record["seed"] != request.seed:
            raise ProtocolViolation(
                f"request record {index} operation/seed differs from request_wire"
            )
        _seed(record["seed"], f"request record {index} seed")
        if request.seed not in allowed_seeds[operation]:
            raise ProtocolViolation(
                f"request record {index} seed is outside the code-owned execution lineage"
            )
        expected_request_digest = _json_digest(
            record["request_wire"], f"request record {index} request_wire"
        )
        if record["request_digest"] != expected_request_digest:
            raise ProtocolViolation(f"request record {index} request_digest mismatch")

        status = record["status"]
        record_statuses.append(status)
        fully_sent = record["request_fully_sent"]
        if fully_sent not in {None, False, True} or type(fully_sent) not in {
            type(None),
            bool,
        }:
            raise ProtocolViolation(
                f"request record {index} request_fully_sent must be bool or null"
            )
        received_digest = record["received_request_digest"]
        if fully_sent is True:
            if not (
                received_digest == expected_request_digest
                or (status == "harness_error" and received_digest is None)
            ):
                raise ProtocolViolation(
                    f"request record {index} received_request_digest mismatch"
                )
        elif received_digest is not None:
            raise ProtocolViolation(
                f"request record {index} unsent request cannot claim receipt"
            )

        response_wire = record["response_wire"]
        response_digest = record["response_digest"]
        failure_origin = record["failure_origin"]
        failure_code = record["failure_code"]
        parsed_response = None
        if status == "success":
            if fully_sent is not True or received_digest != expected_request_digest:
                raise ProtocolViolation(
                    f"request record {index} success lacks sent/received proof"
                )
            if failure_origin is not None or failure_code is not None:
                raise ProtocolViolation(
                    f"request record {index} success cannot carry failure fields"
                )
            if type(response_wire) is not dict:
                raise ProtocolViolation(
                    f"request record {index} success needs a response_wire"
                )
            try:
                parsed_response = response_from_wire(response_wire)
            except ProtocolViolation as exc:
                raise ProtocolViolation(
                    f"request record {index} response_wire is not a typed response"
                ) from exc
            if _canonical_bytes(
                parsed_response.to_wire(),
                f"request record {index} typed response",
            ) != _canonical_bytes(
                response_wire, f"request record {index} response_wire"
            ):
                raise ProtocolViolation(
                    f"request record {index} response_wire is not an exact round trip"
                )
            if parsed_response.operation is not operation:
                raise ProtocolViolation(
                    f"request record {index} response operation mismatch"
                )
            expected_response_digest = _json_digest(
                response_wire, f"request record {index} response_wire"
            )
            if response_digest != expected_response_digest:
                raise ProtocolViolation(
                    f"request record {index} response_digest mismatch"
                )
        else:
            if status == "worker_error":
                if response_wire is not None or response_digest is not None:
                    raise ProtocolViolation(
                        f"request record {index} worker_error cannot carry a response"
                    )
                if (
                    fully_sent is not True
                    or received_digest != expected_request_digest
                    or failure_origin != "candidate"
                    or failure_code not in _CANONICAL_FAILURE_CODES
                ):
                    raise ProtocolViolation(
                        f"request record {index} worker_error fields are inconsistent"
                    )
            else:
                if (
                    failure_origin != "harness"
                    or failure_code != HARNESS_INCOMPLETE_CODE
                    or (fully_sent is not True and received_digest is not None)
                    or (
                        fully_sent is True
                        and received_digest not in {None, expected_request_digest}
                    )
                ):
                    raise ProtocolViolation(
                        f"request record {index} harness_error fields are inconsistent"
                    )
                if (response_wire is None) is not (response_digest is None):
                    raise ProtocolViolation(
                        f"request record {index} harness_error response is partial"
                    )
                if response_wire is not None:
                    if fully_sent is not True or received_digest != expected_request_digest:
                        raise ProtocolViolation(
                            f"request record {index} harness_error cannot bind a "
                            "response without exact sent/received proof"
                        )
                    if type(response_wire) is not dict:
                        raise ProtocolViolation(
                            f"request record {index} harness_error response_wire "
                            "must be an exact object or null"
                        )
                    try:
                        parsed_response = response_from_wire(response_wire)
                    except ProtocolViolation as exc:
                        raise ProtocolViolation(
                            f"request record {index} harness_error response_wire "
                            "is not a typed response"
                        ) from exc
                    if (
                        _canonical_bytes(
                            parsed_response.to_wire(),
                            f"request record {index} typed harness response",
                        )
                        != _canonical_bytes(
                            response_wire,
                            f"request record {index} harness response_wire",
                        )
                        or parsed_response.operation is not operation
                    ):
                        raise ProtocolViolation(
                            f"request record {index} harness_error response "
                            "round-trip/operation mismatch"
                        )
                    if response_digest != _json_digest(
                        response_wire,
                        f"request record {index} harness_error response_wire",
                    ):
                        raise ProtocolViolation(
                            f"request record {index} harness_error response_digest mismatch"
                        )
        typed_responses.append(parsed_response)

        # Bind every main/legacy semantic payload to the exact runner input,
        # not merely to a self-consistent request digest.  Evaluator-fixture
        # suffixes are regenerated from code-owned worlds below; they must not
        # be mistaken for caller-supplied main inputs.
        evaluator_fixture_record = index in evaluator_indices
        if evaluator_fixture_record:
            pass
        elif operation is Operation.INITIALIZE:
            request_history = request.history.to_wire()
            if request.seed == execution_seed:
                allowed_histories = [history_wire]
                # Sequential semantic probes may replay the later public cut;
                # they are not a replacement for the main fresh initialize.
                if record["execution_mode"] == "sequential" and merged_wire is not None:
                    allowed_histories.append(merged_wire)
                if not any(
                    _canonical_bytes(
                        request_history,
                        f"request record {index} initialize history",
                    )
                    == _canonical_bytes(
                        allowed,
                        f"request record {index} allowed initialize history",
                    )
                    for allowed in allowed_histories
                ):
                    raise ProtocolViolation(
                        f"request record {index} main initialize history differs from input"
                    )
            elif not any(
                _canonical_bytes(
                    request_history,
                    f"request record {index} lineage initialize history",
                )
                == _canonical_bytes(
                    item,
                    f"request record {index} allowed lineage history",
                )
                for item in (history_wire, merged_wire)
                if item is not None
            ):
                raise ProtocolViolation(
                    f"request record {index} lineage initialize history is not input/merged"
                )
            if (
                _canonical_bytes(
                    request_history,
                    f"request record {index} sent initialize history",
                )
                == _canonical_bytes(
                    history_wire, f"request record {index} input history"
                )
                and fully_sent is True
            ):
                sent_coverage.add("history")
        elif operation is Operation.DIAGNOSE:
            if _canonical_bytes(
                request.query.to_wire(),
                f"request record {index} diagnosis query",
            ) != _canonical_bytes(
                diagnosis_wire, f"request record {index} input diagnosis query"
            ):
                raise ProtocolViolation(
                    f"request record {index} diagnosis query differs from input"
                )
            if fully_sent is True:
                sent_coverage.add("diagnosis_query")
        elif operation is Operation.ROLLOUT:
            if _canonical_bytes(
                request.query.to_wire(), f"request record {index} rollout query"
            ) != _canonical_bytes(
                rollout_wire, f"request record {index} input rollout query"
            ):
                raise ProtocolViolation(
                    f"request record {index} rollout query differs from input"
                )
            if fully_sent is True:
                sent_coverage.add("rollout_query")
        else:
            if delta_wire is None or _canonical_bytes(
                request.delta.to_wire(), f"request record {index} update delta"
            ) != _canonical_bytes(
                delta_wire, f"request record {index} input update delta"
            ):
                raise ProtocolViolation(
                    f"request record {index} update delta differs from input"
                )
            if fully_sent is True:
                sent_coverage.add("delta")

        if operation is not Operation.INITIALIZE:
            request_state = record["request_wire"]["state"]
            if request_state not in successful_state_wires:
                raise ProtocolViolation(
                    f"request record {index} state was not produced by a prior "
                    "successful StateResponse"
                )

        main_seed = {
            Operation.INITIALIZE: execution_seed,
            Operation.DIAGNOSE: execution_seed + 1,
            Operation.ROLLOUT: execution_seed + 2,
            Operation.UPDATE: execution_seed + 3,
        }[operation]
        if (
            index < main_length
            and request.seed == main_seed
            and record["execution_mode"] == "fresh"
        ):
            fresh_main_sequence.append((operation.value, request.seed))
            fresh_main_positions.append(index)
            fresh_main_records.append(record)
            main_attempts[operation] += 1
            if status == "success":
                main_successes[operation] += 1

        if status == "success":
            assert parsed_response is not None
            success_records.append(record)
            if type(parsed_response) is StateResponse:
                successful_state_wires.append(response_wire["state"])

    expected_fresh_main_sequence = [
        (Operation.INITIALIZE.value, execution_seed),
        (Operation.INITIALIZE.value, execution_seed),
        (Operation.DIAGNOSE.value, execution_seed + 1),
        (Operation.DIAGNOSE.value, execution_seed + 1),
        (Operation.ROLLOUT.value, execution_seed + 2),
        (Operation.ROLLOUT.value, execution_seed + 2),
    ]
    if delta is not None:
        expected_fresh_main_sequence.extend(
            [
                (Operation.UPDATE.value, execution_seed + 3),
                (Operation.UPDATE.value, execution_seed + 3),
            ]
        )
    if fresh_main_sequence != expected_fresh_main_sequence[
        : len(fresh_main_sequence)
    ] or len(fresh_main_sequence) > len(expected_fresh_main_sequence):
        raise ProtocolViolation(
            "fresh main requests are not the exact code-owned ordered flow prefix"
        )
    if fresh_main_positions != list(range(len(fresh_main_positions))):
        raise ProtocolViolation(
            "fresh main flow must be the physical request_records prefix before "
            "semantic/sequential invocations"
        )
    for left_index, right_index, label in (
        (0, 1, "initialize"),
        (2, 3, "diagnose"),
        (4, 5, "rollout"),
        (6, 7, "update"),
    ):
        if len(fresh_main_records) > right_index and (
            fresh_main_records[left_index]["request_digest"]
            != fresh_main_records[right_index]["request_digest"]
        ):
            raise ProtocolViolation(
                f"fresh main {label} replay pair must use one exact request wire"
            )
    state_consumers = [
        fresh_main_records[index]["request_wire"]["state"]
        for index in (2, 4, 6)
        if len(fresh_main_records) > index
    ]
    if state_consumers and any(
        state_wire != state_consumers[0] for state_wire in state_consumers[1:]
    ):
        raise ProtocolViolation(
            "fresh main diagnose/rollout/update requests must consume one shared "
            "initialize state wire"
        )

    if main_length != len(expected_fresh_main_sequence):
        raise ProtocolViolation("code-owned main request length drifted")

    def require_exact_shape(
        records: list[dict[str, Any]],
        expected: list[tuple[str, str, int]],
        label: str,
    ) -> None:
        actual = [
            (record["execution_mode"], record["operation"], record["seed"])
            for record in records
        ]
        if actual != expected:
            raise ProtocolViolation(
                f"{label} differs from the code-owned exact invocation shape"
            )

    def require_successful_records(
        records: list[dict[str, Any]], label: str
    ) -> None:
        if any(record["status"] != "success" for record in records):
            raise ProtocolViolation(f"{label} must contain only successful invocations")

    def response_at(index: int) -> object:
        response = typed_responses[index]
        if response is None:
            raise ProtocolViolation(
                f"request record {index} lacks the successful typed response "
                "required by a decisive comparison"
            )
        return response

    def head_behavior(diagnosis_index: int, rollout_index: int) -> dict[str, Any]:
        return {
            "diagnosis": _scored_semantic_projection(response_at(diagnosis_index)),
            "rollout": _scored_semantic_projection(response_at(rollout_index)),
        }

    def raw_head_behavior(
        diagnosis_index: int, rollout_index: int
    ) -> dict[str, Any]:
        return {
            "diagnosis": value[diagnosis_index]["response_wire"],
            "rollout": value[rollout_index]["response_wire"],
        }

    def validate_update_consistency_suffix(
        consistency: list[dict[str, Any]], *, absolute_offset: int
    ) -> dict[str, Any]:
        require_exact_shape(
            consistency,
            [
                ("fresh", Operation.INITIALIZE.value, lineage_seed),
                ("fresh", Operation.UPDATE.value, lineage_seed),
                ("fresh", Operation.INITIALIZE.value, lineage_seed),
                ("fresh", Operation.UPDATE.value, lineage_seed),
                ("fresh", Operation.DIAGNOSE.value, lineage_seed + 1),
                ("fresh", Operation.ROLLOUT.value, lineage_seed + 2),
                ("fresh", Operation.DIAGNOSE.value, lineage_seed + 1),
                ("fresh", Operation.ROLLOUT.value, lineage_seed + 2),
                ("fresh", Operation.DIAGNOSE.value, lineage_seed + 1),
                ("fresh", Operation.ROLLOUT.value, lineage_seed + 2),
            ],
            "update-consistency suffix",
        )
        require_successful_records(consistency, "update-consistency suffix")
        if (
            consistency[0]["request_wire"]["history"] != history_wire
            or consistency[2]["request_wire"]["history"] != merged_wire
        ):
            raise ProtocolViolation(
                "update-consistency initialize histories differ from input/merged"
            )
        lineage_initial_state = consistency[0]["response_wire"]["state"]
        incremental_state = consistency[1]["response_wire"]["state"]
        replay_state = consistency[2]["response_wire"]["state"]
        duplicate_state = consistency[3]["response_wire"]["state"]
        if consistency[1]["request_wire"]["state"] != lineage_initial_state:
            raise ProtocolViolation(
                "update-consistency first update does not consume lineage initialize"
            )
        if consistency[3]["request_wire"]["state"] != incremental_state:
            raise ProtocolViolation(
                "update-consistency duplicate update does not consume incremental state"
            )
        expected_head_states = (
            incremental_state,
            incremental_state,
            replay_state,
            replay_state,
            duplicate_state,
            duplicate_state,
        )
        if tuple(
            record["request_wire"]["state"] for record in consistency[4:]
        ) != expected_head_states:
            raise ProtocolViolation(
                "update-consistency head calls do not bind all three actual lineages"
            )
        incremental_behavior = head_behavior(
            absolute_offset + 4, absolute_offset + 5
        )
        replay_behavior = head_behavior(absolute_offset + 6, absolute_offset + 7)
        duplicate_behavior = head_behavior(
            absolute_offset + 8, absolute_offset + 9
        )
        return {
            "incremental_behavior_digest": _json_digest(
                incremental_behavior, "incremental scored behavior"
            ),
            "replay_behavior_digest": _json_digest(
                replay_behavior, "replay scored behavior"
            ),
            "duplicate_behavior_digest": _json_digest(
                duplicate_behavior, "duplicate scored behavior"
            ),
            "incremental_equals_replay": _scored_semantic_equal(
                incremental_behavior, replay_behavior
            ),
            "duplicate_event_is_idempotent": _scored_semantic_equal(
                incremental_behavior, duplicate_behavior
            ),
        }

    def validate_warm_future_suffix(
        warm: list[dict[str, Any]],
        *,
        absolute_offset: int,
        main_state_wire: dict[str, Any],
    ) -> dict[str, Any]:
        require_exact_shape(
            warm,
            [
                ("sequential", Operation.INITIALIZE.value, execution_seed),
                ("sequential", Operation.DIAGNOSE.value, execution_seed + 1),
                ("sequential", Operation.ROLLOUT.value, execution_seed + 2),
                ("sequential", Operation.INITIALIZE.value, execution_seed),
                ("sequential", Operation.UPDATE.value, execution_seed + 3),
                ("sequential", Operation.DIAGNOSE.value, execution_seed + 1),
                ("sequential", Operation.ROLLOUT.value, execution_seed + 2),
            ],
            "warm-future suffix",
        )
        require_successful_records(warm, "warm-future suffix")
        if (
            warm[0]["request_wire"]["history"] != merged_wire
            or warm[3]["request_wire"]["history"] != history_wire
        ):
            raise ProtocolViolation(
                "warm-future initialize histories differ from merged/input history"
            )
        warm_state_consumers = (
            warm[1]["request_wire"]["state"],
            warm[2]["request_wire"]["state"],
            warm[4]["request_wire"]["state"],
            warm[5]["request_wire"]["state"],
            warm[6]["request_wire"]["state"],
        )
        if any(state != main_state_wire for state in warm_state_consumers):
            raise ProtocolViolation(
                "warm-future sequence does not query/update the sealed main state"
            )
        before_behavior = head_behavior(2, 4)
        before_raw_wire = raw_head_behavior(2, 4)
        after_initialize_behavior = head_behavior(
            absolute_offset + 1, absolute_offset + 2
        )
        after_initialize_raw_wire = raw_head_behavior(
            absolute_offset + 1, absolute_offset + 2
        )
        after_update_behavior = head_behavior(
            absolute_offset + 5, absolute_offset + 6
        )
        after_update_raw_wire = raw_head_behavior(
            absolute_offset + 5, absolute_offset + 6
        )
        return {
            "before_behavior_digest": _json_digest(
                before_behavior, "warm-future before scored behavior"
            ),
            "before_raw_wire_digest": _json_digest(
                before_raw_wire, "warm-future before raw behavior"
            ),
            "after_initialize_later_digest": _json_digest(
                after_initialize_behavior,
                "warm-future after-initialize scored behavior",
            ),
            "after_initialize_later_raw_wire_digest": _json_digest(
                after_initialize_raw_wire,
                "warm-future after-initialize raw behavior",
            ),
            "after_update_old_delta_digest": _json_digest(
                after_update_behavior, "warm-future after-update scored behavior"
            ),
            "after_update_old_delta_raw_wire_digest": _json_digest(
                after_update_raw_wire, "warm-future after-update raw behavior"
            ),
            "initialize_later_stable": _scored_semantic_equal(
                before_behavior, after_initialize_behavior
            ),
            "update_old_delta_stable": _scored_semantic_equal(
                before_behavior, after_update_behavior
            ),
            "initialize_later_raw_exact": before_raw_wire
            == after_initialize_raw_wire,
            "update_old_delta_raw_exact": before_raw_wire
            == after_update_raw_wire,
        }

    def validate_warm_cold_suffix(
        warm_cold: list[dict[str, Any]],
        *,
        main_state_wire: dict[str, Any],
    ) -> None:
        require_exact_shape(
            warm_cold,
            [
                ("sequential", Operation.INITIALIZE.value, execution_seed),
                ("sequential", Operation.DIAGNOSE.value, execution_seed + 1),
                ("sequential", Operation.ROLLOUT.value, execution_seed + 2),
            ],
            "warm-cold suffix",
        )
        require_successful_records(warm_cold, "warm-cold suffix")
        if warm_cold[0]["request_wire"]["history"] != history_wire or any(
            record["request_wire"]["state"] != main_state_wire
            for record in warm_cold[1:]
        ):
            raise ProtocolViolation(
                "warm-cold sequence does not bind input history and sealed main state"
            )

    def evaluator_probe_shape(probe: str) -> list[tuple[str, str, int]]:
        if probe == "nonidentified_set":
            return [
                ("fresh", Operation.INITIALIZE.value, execution_seed),
                ("fresh", Operation.INITIALIZE.value, execution_seed),
                ("fresh", Operation.ROLLOUT.value, execution_seed + 2),
                ("fresh", Operation.ROLLOUT.value, execution_seed + 2),
                ("fresh", Operation.ROLLOUT.value, execution_seed + 2),
                ("fresh", Operation.ROLLOUT.value, execution_seed + 2),
            ]
        if probe == "dangerous_collision":
            endpoint = [
                ("fresh", Operation.INITIALIZE.value, execution_seed),
                ("fresh", Operation.DIAGNOSE.value, execution_seed + 1),
                *[
                    ("fresh", Operation.ROLLOUT.value, execution_seed + 2)
                    for _ in range(8)
                ],
            ]
            return endpoint + endpoint
        if probe == "unsafe_closed_world":
            endpoint = [
                ("fresh", Operation.INITIALIZE.value, execution_seed),
                ("fresh", Operation.DIAGNOSE.value, execution_seed + 1),
                ("fresh", Operation.ROLLOUT.value, execution_seed + 2),
                ("fresh", Operation.ROLLOUT.value, execution_seed + 2),
            ]
            return endpoint * 4
        raise ProtocolViolation("unknown evaluator probe shape")

    def validate_evaluator_probe(probe: str) -> dict[str, Any]:
        start, end = evaluator_ranges[probe]
        records = value[start:end]
        require_exact_shape(
            records,
            evaluator_probe_shape(probe),
            f"{probe} evaluator suffix",
        )
        require_successful_records(records, f"{probe} evaluator suffix")
        artifact = compliance_module._rebuild_evaluator_probe_artifact(
            probe=probe,
            control_class_name=expected_control_class_name,
            seed=execution_seed,
            request_start=start,
            request_records=records,
        )
        if artifact["request_record_count"] != evaluator_probe_counts[probe]:
            raise ProtocolViolation("evaluator artifact request count mismatch")
        actual_probe_evidence[probe] = artifact
        return artifact

    if decisive and not main_attempts[Operation.INITIALIZE]:
        raise ProtocolViolation("killed/passed transcript lacks attempted main initialize")
    if observation_outcome is ObservationOutcome.PASSED:
        if any(status != "success" for status in record_statuses):
            raise ProtocolViolation(
                "passed transcript cannot contain worker/harness error records"
            )
        if fresh_main_sequence != expected_fresh_main_sequence:
            raise ProtocolViolation(
                "passed transcript lacks the exact complete fresh main request flow"
            )
        semantic_suffix = value[main_length:]
        expected_suffix_shape: list[tuple[str, str, int]] = []
        if "update_consistency" in expected_semantic_probes:
            expected_suffix_shape.extend(
                [
                    ("fresh", Operation.INITIALIZE.value, lineage_seed),
                    ("fresh", Operation.UPDATE.value, lineage_seed),
                    ("fresh", Operation.INITIALIZE.value, lineage_seed),
                    ("fresh", Operation.UPDATE.value, lineage_seed),
                    ("fresh", Operation.DIAGNOSE.value, lineage_seed + 1),
                    ("fresh", Operation.ROLLOUT.value, lineage_seed + 2),
                    ("fresh", Operation.DIAGNOSE.value, lineage_seed + 1),
                    ("fresh", Operation.ROLLOUT.value, lineage_seed + 2),
                    ("fresh", Operation.DIAGNOSE.value, lineage_seed + 1),
                    ("fresh", Operation.ROLLOUT.value, lineage_seed + 2),
                ]
            )
        if "warm_future_old_cut" in expected_semantic_probes:
            expected_suffix_shape.extend(
                [
                    ("sequential", Operation.INITIALIZE.value, execution_seed),
                    ("sequential", Operation.DIAGNOSE.value, execution_seed + 1),
                    ("sequential", Operation.ROLLOUT.value, execution_seed + 2),
                    ("sequential", Operation.INITIALIZE.value, execution_seed),
                    ("sequential", Operation.UPDATE.value, execution_seed + 3),
                    ("sequential", Operation.DIAGNOSE.value, execution_seed + 1),
                    ("sequential", Operation.ROLLOUT.value, execution_seed + 2),
                ]
            )
        for probe in evaluator_probe_order:
            expected_suffix_shape.extend(evaluator_probe_shape(probe))
        # The warm-vs-cold sequence is part of every successful compliance
        # evaluation, independent of optional semantic probes.
        expected_suffix_shape.extend(
            [
                ("sequential", Operation.INITIALIZE.value, execution_seed),
                ("sequential", Operation.DIAGNOSE.value, execution_seed + 1),
                ("sequential", Operation.ROLLOUT.value, execution_seed + 2),
            ]
        )
        require_exact_shape(
            semantic_suffix,
            expected_suffix_shape,
            "passed transcript semantic-probe/warm suffix",
        )

        main_state_wire = fresh_main_records[2]["request_wire"]["state"]
        suffix_offset = 0
        if "update_consistency" in expected_semantic_probes:
            consistency = semantic_suffix[:10]
            consistency_evidence = validate_update_consistency_suffix(
                consistency, absolute_offset=main_length
            )
            if not (
                consistency_evidence["incremental_equals_replay"]
                and consistency_evidence["duplicate_event_is_idempotent"]
            ):
                raise ProtocolViolation(
                    "passed update-consistency transcript contains actual scored "
                    "semantic divergence"
                )
            suffix_offset = 10
        if "warm_future_old_cut" in expected_semantic_probes:
            warm = semantic_suffix[suffix_offset : suffix_offset + 7]
            warm_evidence = validate_warm_future_suffix(
                warm,
                absolute_offset=main_length + suffix_offset,
                main_state_wire=main_state_wire,
            )
            if not all(
                warm_evidence[field]
                for field in (
                    "initialize_later_stable",
                    "update_old_delta_stable",
                    "initialize_later_raw_exact",
                    "update_old_delta_raw_exact",
                )
            ):
                raise ProtocolViolation(
                    "passed warm-future transcript contains actual old-cut drift"
                )
            suffix_offset += 7
        for probe in evaluator_probe_order:
            start, end = evaluator_ranges[probe]
            expected_relative_start = main_length + suffix_offset
            if start != expected_relative_start or end - start != evaluator_probe_counts[probe]:
                raise ProtocolViolation("evaluator probe suffix offset drifted")
            validate_evaluator_probe(probe)
            suffix_offset += evaluator_probe_counts[probe]
        warm_cold = semantic_suffix[suffix_offset : suffix_offset + 3]
        validate_warm_cold_suffix(warm_cold, main_state_wire=main_state_wire)
        if any(
            _canonical_bytes(
                value[main_index]["response_wire"],
                "passed fresh response wire",
            )
            != _canonical_bytes(
                warm_cold[warm_index]["response_wire"],
                "passed sequential response wire",
            )
            for main_index, warm_index in ((0, 0), (2, 1), (4, 2))
        ):
            raise ProtocolViolation(
                "passed warm-cold transcript differs from fresh response wires"
            )
        required_successes = {
            Operation.INITIALIZE: 2,
            Operation.DIAGNOSE: 2,
            Operation.ROLLOUT: 2,
        }
        if delta is not None:
            required_successes[Operation.UPDATE] = 2
        if any(
            main_successes[operation] < count
            for operation, count in required_successes.items()
        ):
            raise ProtocolViolation(
                "passed transcript lacks the complete repeated main invocation flow"
            )
        required_coverage = {"history", "diagnosis_query", "rollout_query"}
        if delta is not None:
            required_coverage.add("delta")
        if not required_coverage.issubset(sent_coverage):
            raise ProtocolViolation("passed transcript lacks actual input coverage")
    elif observation_outcome is ObservationOutcome.KILLED:
        if "harness_error" in record_statuses:
            raise ProtocolViolation(
                "killed transcript cannot contain harness_error records"
            )
        worker_error_indices = [
            index
            for index, record in enumerate(value)
            if record["status"] == "worker_error"
        ]
        if worker_error_indices:
            terminal_index = worker_error_indices[0]
            if (
                len(worker_error_indices) != 1
                or terminal_index != len(value) - 1
                or value[terminal_index]["failure_code"] != expected_failure_code
            ):
                raise ProtocolViolation(
                    "killed transcript worker_error must be one terminal record "
                    "with the code-owned decisive failure code"
                )
        comparison_failure = (
            expected_failure_code == "UCM-F006-HIDDEN_PATIENT_CACHE"
            or (
                expected_failure_code == "UCM-F001-FUTURE_LEAK"
                and "warm_future_old_cut" in expected_semantic_probes
            )
            or expected_failure_code == "UCM-F019-UPDATE_INCONSISTENT"
            or expected_failure_code == "UCM-F020-NONREPRODUCIBLE"
            or expected_failure_code
            in {
                "UCM-F015-CONDITIONING_AS_INTERVENTION",
                "UCM-F016-DANGEROUS_COLLISION",
                "UCM-F017-OOD_FORCED_MATCH",
            }
        )
        if expected_head_record_shape == "replay_ddrr":
            if fresh_main_sequence != expected_fresh_main_sequence:
                raise ProtocolViolation(
                    "replay killed transcript lacks the exact complete fresh main flow"
                )
            required_coverage = {"history", "diagnosis_query", "rollout_query"}
            if "update_consistency" in expected_semantic_probes and delta is not None:
                required_coverage.add("delta")
            if not required_coverage.issubset(sent_coverage):
                raise ProtocolViolation(
                    "replay killed transcript lacks actual input coverage"
                )
        else:
            expected_topology = _EMPTY_HEAD_TERMINAL_REQUEST_TOPOLOGIES.get(
                expected_subject_id
            )
            if expected_topology is None:
                raise ProtocolViolation(
                    "code-owned empty-head subject lacks a terminal request topology"
                )
            actual_topology = [
                (
                    record["execution_mode"],
                    record["operation"],
                    record["seed"],
                    record["status"],
                    record["failure_code"],
                )
                for record in value
            ]
            exact_topology = [
                (
                    "fresh",
                    operation,
                    execution_seed + seed_offset,
                    status,
                    expected_failure_code if status == "worker_error" else None,
                )
                for operation, seed_offset, status in expected_topology
            ]
            if actual_topology != exact_topology:
                raise ProtocolViolation(
                    "empty-head killed transcript differs from the code-owned "
                    "exact terminal request topology"
                )

        allowed_response_drift_positions: set[int] = set()
        if comparison_failure:
            require_successful_records(
                value, "code-owned comparison killed transcript"
            )
            if fresh_main_sequence != expected_fresh_main_sequence:
                raise ProtocolViolation(
                    "code-owned comparison killed transcript lacks the exact "
                    "complete fresh main flow"
                )
            main_state_wire = fresh_main_records[2]["request_wire"]["state"]
            killed_suffix = value[main_length:]
            if expected_failure_code in {
                "UCM-F015-CONDITIONING_AS_INTERVENTION",
                "UCM-F016-DANGEROUS_COLLISION",
                "UCM-F017-OOD_FORCED_MATCH",
            }:
                probe = {
                    "UCM-F015-CONDITIONING_AS_INTERVENTION": "nonidentified_set",
                    "UCM-F016-DANGEROUS_COLLISION": "dangerous_collision",
                    "UCM-F017-OOD_FORCED_MATCH": "unsafe_closed_world",
                }[expected_failure_code]
                require_exact_shape(
                    killed_suffix,
                    evaluator_probe_shape(probe)
                    + [
                        ("sequential", Operation.INITIALIZE.value, execution_seed),
                        ("sequential", Operation.DIAGNOSE.value, execution_seed + 1),
                        ("sequential", Operation.ROLLOUT.value, execution_seed + 2),
                    ],
                    f"{probe} killed evaluator/warm suffix",
                )
                artifact = validate_evaluator_probe(probe)
                report_failures = artifact["evaluation_report"]["failures"]
                if [item["code"] for item in report_failures] != [expected_failure_code]:
                    raise ProtocolViolation(
                        "evaluator killed artifact lacks its one exact decisive issue"
                    )
                validate_warm_cold_suffix(
                    killed_suffix[evaluator_probe_counts[probe] :],
                    main_state_wire=main_state_wire,
                )
            elif expected_failure_code == "UCM-F020-NONREPRODUCIBLE":
                require_exact_shape(
                    killed_suffix,
                    [],
                    "UCM-F020 killed suffix",
                )
                # Only the second replay response in each exact main head pair
                # may differ.  Initialize/update replay drift is never F020
                # evidence for this code-owned subject.
                allowed_response_drift_positions.update({3, 5})
                if not any(
                    _canonical_bytes(
                        value[left]["response_wire"],
                        "F020 first replay response wire",
                    )
                    != _canonical_bytes(
                        value[right]["response_wire"],
                        "F020 second replay response wire",
                    )
                    for left, right in ((2, 3), (4, 5))
                ):
                    raise ProtocolViolation(
                        "UCM-F020 killed transcript lacks actual main head replay drift"
                    )
            elif expected_failure_code == "UCM-F006-HIDDEN_PATIENT_CACHE":
                validate_warm_cold_suffix(
                    killed_suffix, main_state_wire=main_state_wire
                )
                if len(killed_suffix) != 3:
                    # validate_warm_cold_suffix diagnoses short records; this
                    # explicit length also prevents a valid prefix plus tails.
                    raise ProtocolViolation(
                        "UCM-F006 killed suffix differs from exact warm-cold shape"
                    )
                warm_offset = main_length
                allowed_response_drift_positions.update(
                    {warm_offset, warm_offset + 1, warm_offset + 2}
                )
                if not any(
                    _canonical_bytes(
                        value[main_index]["response_wire"],
                        "F006 fresh response wire",
                    )
                    != _canonical_bytes(
                        value[warm_offset + warm_index]["response_wire"],
                        "F006 sequential response wire",
                    )
                    for main_index, warm_index in ((0, 0), (2, 1), (4, 2))
                ):
                    raise ProtocolViolation(
                        "UCM-F006 killed transcript lacks actual warm/fresh raw drift"
                    )
            elif expected_failure_code == "UCM-F001-FUTURE_LEAK":
                require_exact_shape(
                    killed_suffix,
                    [
                        ("sequential", Operation.INITIALIZE.value, execution_seed),
                        ("sequential", Operation.DIAGNOSE.value, execution_seed + 1),
                        ("sequential", Operation.ROLLOUT.value, execution_seed + 2),
                        ("sequential", Operation.INITIALIZE.value, execution_seed),
                        ("sequential", Operation.UPDATE.value, execution_seed + 3),
                        ("sequential", Operation.DIAGNOSE.value, execution_seed + 1),
                        ("sequential", Operation.ROLLOUT.value, execution_seed + 2),
                        ("sequential", Operation.INITIALIZE.value, execution_seed),
                        ("sequential", Operation.DIAGNOSE.value, execution_seed + 1),
                        ("sequential", Operation.ROLLOUT.value, execution_seed + 2),
                    ],
                    "UCM-F001 killed semantic/warm suffix",
                )
                warm_evidence = validate_warm_future_suffix(
                    killed_suffix[:7],
                    absolute_offset=main_length,
                    main_state_wire=main_state_wire,
                )
                validate_warm_cold_suffix(
                    killed_suffix[7:], main_state_wire=main_state_wire
                )
                if (
                    warm_evidence["initialize_later_stable"]
                    and warm_evidence["update_old_delta_stable"]
                ):
                    raise ProtocolViolation(
                        "UCM-F001 killed transcript lacks actual scored old-cut drift"
                    )
                actual_probe_evidence["warm_future_old_cut"] = warm_evidence
                # Only the four old-head responses compared by C23 may drift.
                # The two initialize responses, the update response, and the
                # final warm-cold sequence remain subject to exact replay.
                allowed_response_drift_positions.update(
                    {
                        main_length + 1,
                        main_length + 2,
                        main_length + 5,
                        main_length + 6,
                    }
                )
            else:
                require_exact_shape(
                    killed_suffix,
                    [
                        ("fresh", Operation.INITIALIZE.value, lineage_seed),
                        ("fresh", Operation.UPDATE.value, lineage_seed),
                        ("fresh", Operation.INITIALIZE.value, lineage_seed),
                        ("fresh", Operation.UPDATE.value, lineage_seed),
                        ("fresh", Operation.DIAGNOSE.value, lineage_seed + 1),
                        ("fresh", Operation.ROLLOUT.value, lineage_seed + 2),
                        ("fresh", Operation.DIAGNOSE.value, lineage_seed + 1),
                        ("fresh", Operation.ROLLOUT.value, lineage_seed + 2),
                        ("fresh", Operation.DIAGNOSE.value, lineage_seed + 1),
                        ("fresh", Operation.ROLLOUT.value, lineage_seed + 2),
                        ("sequential", Operation.INITIALIZE.value, execution_seed),
                        ("sequential", Operation.DIAGNOSE.value, execution_seed + 1),
                        ("sequential", Operation.ROLLOUT.value, execution_seed + 2),
                    ],
                    "UCM-F019 killed consistency/warm suffix",
                )
                consistency_evidence = validate_update_consistency_suffix(
                    killed_suffix[:10], absolute_offset=main_length
                )
                validate_warm_cold_suffix(
                    killed_suffix[10:], main_state_wire=main_state_wire
                )
                if (
                    consistency_evidence["incremental_equals_replay"]
                    and consistency_evidence["duplicate_event_is_idempotent"]
                ):
                    raise ProtocolViolation(
                        "UCM-F019 killed transcript lacks actual scored consistency drift"
                    )
                actual_probe_evidence["update_consistency"] = consistency_evidence
        else:
            allowed_response_drift_positions = set()

        # Repeated exact requests are deterministic unless the differing
        # response occupies a comparison position fixed above.  This replaces
        # the former failure-code-wide F020 escape hatch with a positional one.
        baseline_response_by_request: dict[str, str] = {}
        for index, record in enumerate(value):
            if record["status"] != "success":
                continue
            request_digest = record["request_digest"]
            baseline = baseline_response_by_request.setdefault(
                request_digest, record["response_digest"]
            )
            if (
                record["response_digest"] != baseline
                and index not in allowed_response_drift_positions
            ):
                raise ProtocolViolation(
                    "repeated successful request response drift is outside the "
                    "code-owned comparison position"
                )

    else:
        allowed_response_drift_positions = set()

    if observation_outcome is not ObservationOutcome.KILLED:
        # PASSED and partial/non-decisive retained reports never have a
        # response-drift exception.  Same request bytes must mean same response
        # bytes everywhere in their retained transcript.
        baseline_response_by_request: dict[str, str] = {}
        for record in value:
            if record["status"] != "success":
                continue
            request_digest = record["request_digest"]
            baseline = baseline_response_by_request.setdefault(
                request_digest, record["response_digest"]
            )
            if record["response_digest"] != baseline:
                raise ProtocolViolation(
                    "repeated successful request response drift lacks a "
                    "code-owned decisive comparison"
                )

    if len(invocation_nonces) != len(set(invocation_nonces)):
        raise ProtocolViolation(
            "request transcript reused a code-owned invocation nonce"
        )
    if len(executor_receipts) != len(set(executor_receipts)):
        raise ProtocolViolation(
            "request transcript reused a code-owned executor receipt"
        )
    if observed_code_owned_bindings:
        first_binding = observed_code_owned_bindings[0]
        if any(binding != first_binding for binding in observed_code_owned_bindings[1:]):
            raise ProtocolViolation(
                "request transcript spliced distinct live execution bindings"
            )
        if (
            expected_execution_binding is not None
            and first_binding != expected_execution_binding
        ):
            raise ProtocolViolation(
                "request transcript live binding differs from report execution binding"
            )

    # A head record is derived only from one successful request/response pair.
    # The candidate-visible state wire has already been checked against the
    # ordered StateResponse lineage above.  Recomputing the separate harness
    # ``consumed_state_hash`` seal is intentionally still part of fixed E003;
    # it cannot be promoted from a caller-supplied digest in this bundle.
    consumed_success_indices: set[int] = set()
    previous_success_index = -1
    for head_index, head in enumerate(head_records):
        matches = [
            success_index
            for success_index, request_record in enumerate(success_records)
            if success_index not in consumed_success_indices
            and success_index > previous_success_index
            and request_record["execution_mode"] == "fresh"
            and request_record["operation"] == head["operation"]
            and request_record["seed"] == head["seed"]
            and request_record["request_digest"] == head["request_digest"]
            and request_record["response_digest"] == head["response_digest"]
        ]
        if not matches:
            raise ProtocolViolation(
                f"report head record {head_index} is not bound one-to-one to a "
                "distinct ordered fresh success request record"
            )
        selected = matches[0]
        consumed_success_indices.add(selected)
        previous_success_index = selected

    transcript_digest = _json_digest(value, "closed request_records transcript")
    return transcript_digest, frozenset(sent_coverage), actual_probe_evidence


def _validate_paired_semantic_evidence(
    value: object,
    *,
    expected_phases: tuple[str, ...],
) -> None:
    paired = _closed_object(
        value,
        _PAIRED_EVIDENCE_KEYS,
        "paired semantic equivalence evidence",
    )
    if paired["protocol"] != _PORTABLE_SEMANTIC_PROBE_PROTOCOL:
        raise ProtocolViolation("paired semantic evidence protocol mismatch")
    if paired["comparison"] != "paired-honest-vs-affine-scored-semantics":
        raise ProtocolViolation("paired semantic evidence comparison mismatch")
    if type(paired["absolute_tolerance"]) is not float or paired[
        "absolute_tolerance"
    ] != 1e-9:
        raise ProtocolViolation("paired semantic evidence absolute tolerance mismatch")
    if type(paired["relative_tolerance"]) is not float or paired[
        "relative_tolerance"
    ] != 0.0:
        raise ProtocolViolation("paired semantic evidence relative tolerance mismatch")
    phases = paired["phases"]
    if type(phases) is not list or len(phases) not in {1, 2}:
        raise ProtocolViolation("paired semantic evidence phases are incomplete")
    phase_names: list[str] = []
    for index, phase_value in enumerate(phases):
        phase = _closed_object(
            phase_value,
            _PAIRED_PHASE_KEYS,
            f"paired semantic phase {index}",
        )
        phase_name = phase["phase"]
        if phase_name not in {"initialize", "update"}:
            raise ProtocolViolation("paired semantic evidence has an unknown phase")
        phase_names.append(phase_name)
        for digest_field in (
            "honest_state_digest",
            "affine_state_digest",
            "honest_behavior_digest",
            "affine_behavior_digest",
        ):
            _digest(phase[digest_field], f"paired semantic phase {digest_field}")
        if phase["honest_state_digest"] == phase["affine_state_digest"]:
            raise ProtocolViolation("paired semantic states are not serialization-distinct")
        if phase["state_serializations_distinct"] is not True:
            raise ProtocolViolation("paired semantic state distinction is not proven")
        if phase["semantic_behavior_equivalent"] is not True:
            raise ProtocolViolation("paired semantic behavior equivalence is not proven")
    if phase_names != list(expected_phases):
        raise ProtocolViolation(
            "paired semantic phase order/set differs from the input delta"
        )
    if paired["passed"] is not True:
        raise ProtocolViolation("paired semantic evidence is not a pass")


def _validate_decisive_source_witness(
    witness: dict[str, Any],
    *,
    label: str,
    expected_control: str,
    expected_candidate: str,
    expected_execution_seed: int,
    expected_semantic_probes: tuple[str, ...],
    expected_runner_contract: dict[str, Any],
    execution_context_payload: dict[str, Any],
) -> None:
    witness = _closed_object(witness, _SOURCE_WITNESS_KEYS, label)
    if witness["protocol"] != "ucm-portable-control-source-binding/18":
        raise ProtocolViolation(f"{label} protocol mismatch")
    if witness["control"] != expected_control:
        raise ProtocolViolation(f"{label} control identity mismatch")
    _seed(witness["execution_seed"], f"{label} execution_seed")
    if witness["execution_seed"] != expected_execution_seed:
        raise ProtocolViolation(f"{label} execution seed mismatch")
    if witness["expected_candidate"] != expected_candidate:
        raise ProtocolViolation(f"{label} candidate identity mismatch")
    if witness["enabled_semantic_probes"] != list(expected_semantic_probes):
        raise ProtocolViolation(f"{label} semantic probe contract mismatch")
    if witness["portable_runner_contract"] != expected_runner_contract:
        raise ProtocolViolation(f"{label} portable runner contract mismatch")
    if witness["semantic_probe_contract"] != _PORTABLE_SEMANTIC_PROBE_PROTOCOL:
        raise ProtocolViolation(f"{label} semantic probe protocol mismatch")
    if witness["runtime_metadata"] != execution_context_payload["runtime_metadata"]:
        raise ProtocolViolation(f"{label} runtime metadata mismatch")
    for list_field in _SOURCE_WITNESS_LIST_FIELDS:
        values = witness[list_field]
        if type(values) is not list or any(type(item) is not dict for item in values):
            raise ProtocolViolation(
                f"{label} {list_field} must be an exact list of objects"
            )
    if type(witness["enabled_semantic_probes"]) is not list or any(
        type(item) is not str for item in witness["enabled_semantic_probes"]
    ):
        raise ProtocolViolation(
            f"{label} enabled_semantic_probes must be an exact string list"
        )
    for object_field in _SOURCE_WITNESS_OBJECT_FIELDS:
        if type(witness[object_field]) is not dict:
            raise ProtocolViolation(
                f"{label} {object_field} must be an exact object"
            )
    if _json_digest(witness["runtime_import_cache"], label) != execution_context_payload[
        "runtime_import_cache_contract_digest"
    ]:
        raise ProtocolViolation(f"{label} runtime import cache binding mismatch")


def _validate_record_semantics(
    record: MutationEvidenceRecord,
    *,
    expected_runner_protocol: str,
    expected_base_seed: int,
    expected_paired_phases: tuple[str, ...],
    input_preimage_digest: str,
    input_history: VisibleHistory,
    input_diagnosis_query: DiagnosisQuery,
    input_rollout_query: RolloutQuery,
    input_delta: VisibleDelta | None,
    execution_context_payload: dict[str, Any],
    pre_body: dict[str, Any],
    post_body: dict[str, Any],
    source_body: dict[str, Any],
    report_body: dict[str, Any] | None,
    error_body: dict[str, Any],
    decision_body: dict[str, Any],
    decisive_body: dict[str, Any] | None,
) -> None:
    observation = record.observation
    (
        expected_control,
        code_owned_candidate,
        row_index,
        expected_classification,
        expected_gate,
        expected_failure_code,
        expected_semantic_probes,
        expected_head_record_shape,
    ) = _portable_subject_identity(observation)
    expected_execution_seed = expected_base_seed + row_index
    _seed(expected_execution_seed, "code-owned subject execution_seed")
    if observation.execution_seed != expected_execution_seed:
        raise ProtocolViolation(
            "observation execution_seed differs from base_seed plus code-owned row index"
        )
    if observation.classification != expected_classification:
        raise ProtocolViolation(
            "observation classification differs from the code-owned subject mapping"
        )
    if observation.outcome is ObservationOutcome.KILLED and (
        observation.actual_gate != expected_gate
        or observation.actual_failure_code != expected_failure_code
    ):
        raise ProtocolViolation(
            "killed observation differs from the code-owned decisive gate/failure code"
        )
    pre = _payload_object(pre_body, "pre-source witness")
    post = _payload_object(post_body, "post-source witness")
    for label, witness in (
        ("pre-source witness", pre),
        ("post-source witness", post),
    ):
        if witness.get("control") != expected_control:
            raise ProtocolViolation(
                f"{label} control differs from the code-owned subject mapping"
            )
        _seed(witness.get("execution_seed"), f"{label} execution_seed")
        if witness["execution_seed"] != observation.execution_seed:
            raise ProtocolViolation(f"{label} execution seed mismatch")
        if witness.get("enabled_semantic_probes") != list(expected_semantic_probes):
            raise ProtocolViolation(
                f"{label} semantic probes differ from the code-owned subject mapping"
            )
        witnessed_candidate = witness.get("expected_candidate")
        if witnessed_candidate is not None and witnessed_candidate != code_owned_candidate:
            raise ProtocolViolation(
                f"{label} candidate differs from the code-owned subject mapping"
            )
    decision = _payload_object(decision_body, "decision record")
    if decision.get("derived_outcome") != observation.outcome.value:
        raise ProtocolViolation(
            "decision record derived_outcome differs from typed observation"
        )
    if observation.subject_kind is SubjectKind.MUTANT:
        decision = _closed_object(
            decision, _MUTANT_DECISION_KEYS, "mutant decision record"
        )
        if (
            decision["expected_gate"] != expected_gate
            or decision["expected_failure_code"] != expected_failure_code
        ):
            raise ProtocolViolation(
                "mutant decision differs from the code-owned gate/failure mapping"
            )
        if decision["actual_gate"] != observation.actual_gate:
            raise ProtocolViolation("mutant decision actual_gate mismatch")
        if (
            decision["actual_failure_code"]
            != observation.actual_failure_code
        ):
            raise ProtocolViolation(
                "mutant decision actual_failure_code mismatch"
            )
        decision_boolean_fields = (
            "report_available",
            "harness_stable_during_execution",
            "execution_binding_complete",
            "harness_incomplete",
            "decision_processing_complete",
        )
    else:
        decision = _closed_object(
            decision,
            _SPECIFICITY_DECISION_KEYS,
            "specificity decision record",
        )
        if decision["classification"] != expected_classification:
            raise ProtocolViolation(
                "specificity decision classification mismatch"
            )
        decision_boolean_fields = (
            "report_available",
            "harness_stable_during_execution",
            "execution_binding_complete",
            "probe_incomplete",
            "report_processing_complete",
        )
        if decision["semantic_equivalence_passed"] not in {
            None,
            True,
            False,
        } or type(decision["semantic_equivalence_passed"]) not in {
            type(None),
            bool,
        }:
            raise ProtocolViolation(
                "specificity decision semantic_equivalence_passed must be bool or null"
            )
    for field_name in decision_boolean_fields:
        if type(decision[field_name]) is not bool:
            raise ProtocolViolation(
                f"decision record {field_name} must be an exact bool"
            )
    if decision["input_preimage_digest"] != input_preimage_digest:
        raise ProtocolViolation("decision input_preimage_digest binding mismatch")
    _digest(
        decision["invocation_transcript_digest"],
        "decision invocation_transcript_digest",
    )
    if decision["report_available"] is not (report_body is not None):
        raise ProtocolViolation(
            "decision report_available differs from raw report presence"
        )

    error_transcript = _closed_object(
        _payload_object(error_body, "error transcript"),
        frozenset({"runner_protocol", "status", "errors"}),
        "error transcript payload",
    )
    if error_transcript["runner_protocol"] != expected_runner_protocol:
        raise ProtocolViolation("error transcript runner_protocol differs from bundle runner")
    errors = error_transcript["errors"]
    if type(errors) is not list or any(type(item) is not dict for item in errors):
        raise ProtocolViolation("error transcript errors must be a list of objects")
    for index, error_value in enumerate(errors):
        error = _closed_object(
            error_value,
            _EXECUTION_ERROR_KEYS,
            f"error transcript error {index}",
        )
        _name(error["stage"], f"error transcript error {index} stage")
        _name(
            error["exception_type"],
            f"error transcript error {index} exception_type",
        )
        if type(error["message"]) is not str:
            raise ProtocolViolation(
                f"error transcript error {index} message must be a string"
            )
        try:
            error["message"].encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ProtocolViolation(
                f"error transcript error {index} message contains an invalid "
                "Unicode surrogate"
            ) from exc
    expected_error_status = "error" if errors else "none"
    if error_transcript["status"] != expected_error_status:
        raise ProtocolViolation("error transcript status differs from its errors")
    requires_error = observation.outcome in {
        ObservationOutcome.CRASHED,
        ObservationOutcome.TIMED_OUT,
    }
    if requires_error != bool(errors):
        raise ProtocolViolation(
            "error transcript presence is inconsistent with observation outcome"
        )

    if (
        execution_context_payload["source_preparation_error"] is not None
        and observation.outcome is not ObservationOutcome.CRASHED
    ):
        raise ProtocolViolation(
            "source preparation failure must produce a crashed observation"
        )

    # Any retained report, including a partial CRASHED/REJECTED report, must
    # still carry a closed, typed invocation transcript.  Completeness is
    # outcome-sensitive inside the validator; raw partial evidence is not
    # discarded merely because it cannot support a matrix decision.
    if report_body is None:
        if decision["invocation_transcript_digest"] != _json_digest(
            [], "empty invocation transcript"
        ):
            raise ProtocolViolation(
                "decision without a report must bind the empty invocation transcript"
            )
    else:
        retained_report = _payload_object(report_body, "report transcript")
        missing_report_fields = _REPORT_REQUIRED_FIELDS.difference(retained_report)
        extra_report_fields = set(retained_report).difference(_REPORT_REQUIRED_FIELDS)
        if missing_report_fields or extra_report_fields:
            raise ProtocolViolation(
                "report does not have the exact required execution fields; "
                f"missing={sorted(missing_report_fields)!r}, "
                f"extra={sorted(extra_report_fields)!r}"
            )
        if retained_report["runner_protocol"] != expected_runner_protocol:
            raise ProtocolViolation("report runner_protocol differs from bundle runner")
        if retained_report["input_preimage_digest"] != input_preimage_digest:
            raise ProtocolViolation("report input_preimage_digest binding mismatch")
        retained_invocation_digest, _, _ = _validate_request_records(
            retained_report["request_records"],
            input_preimage_digest=input_preimage_digest,
            history=input_history,
            diagnosis_query=input_diagnosis_query,
            rollout_query=input_rollout_query,
            delta=input_delta,
            execution_seed=observation.execution_seed,
            expected_subject_id=observation.subject_id,
            expected_failure_code=expected_failure_code,
            expected_semantic_probes=expected_semantic_probes,
            expected_head_record_shape=expected_head_record_shape,
            observation_outcome=observation.outcome,
            head_records=[],
        )
        if retained_report["invocation_transcript_digest"] != retained_invocation_digest:
            raise ProtocolViolation("report invocation_transcript_digest mismatch")
        if decision["invocation_transcript_digest"] != retained_invocation_digest:
            raise ProtocolViolation(
                "decision invocation_transcript_digest binding mismatch"
            )

    if observation.outcome not in {
        ObservationOutcome.KILLED,
        ObservationOutcome.PASSED,
    }:
        if decisive_body is not None:
            raise ProtocolViolation("non-decisive outcome has a decisive blob")
        return

    if execution_context_payload["source_preparation_error"] is not None:
        raise ProtocolViolation(
            "killed/passed evidence cannot follow a source preparation error"
        )
    _digest(
        execution_context_payload["runtime_import_cache_contract_digest"],
        "decisive runtime import cache contract digest",
    )

    if report_body is None or decisive_body is None:
        raise ProtocolViolation("killed/passed evidence lacks report or decisive blob")
    if errors:
        raise ProtocolViolation("killed/passed evidence contains execution errors")
    if _canonical_bytes(
        pre_body["payload"], "pre-source witness payload"
    ) != _canonical_bytes(post_body["payload"], "post-source witness payload"):
        raise ProtocolViolation("killed/passed evidence has unstable pre/post witness")
    expected_runner_contract = portable_runner_contract(expected_runner_protocol)
    for label, witness in (
        ("pre-source witness", pre),
        ("post-source witness", post),
    ):
        _validate_decisive_source_witness(
            witness,
            label=label,
            expected_control=expected_control,
            expected_candidate=code_owned_candidate,
            expected_execution_seed=observation.execution_seed,
            expected_semantic_probes=expected_semantic_probes,
            expected_runner_contract=expected_runner_contract,
            execution_context_payload=execution_context_payload,
        )

    source = _payload_object(source_body, "source record")
    report = _payload_object(report_body, "report transcript")
    missing_report_fields = _REPORT_REQUIRED_FIELDS.difference(report)
    extra_report_fields = set(report).difference(_REPORT_REQUIRED_FIELDS)
    if missing_report_fields or extra_report_fields:
        raise ProtocolViolation(
            "killed/passed report does not have the exact required execution fields; "
            f"missing={sorted(missing_report_fields)!r}, "
            f"extra={sorted(extra_report_fields)!r}"
        )
    if report["runner_protocol"] != expected_runner_protocol:
        raise ProtocolViolation("report runner_protocol differs from bundle runner")
    if report["input_preimage_digest"] != input_preimage_digest:
        raise ProtocolViolation("report input_preimage_digest binding mismatch")
    if (
        observation.subject_kind is SubjectKind.MUTANT
        and report["paired_semantic_equivalence"] is not None
    ):
        raise ProtocolViolation("mutant report cannot carry paired specificity evidence")
    for verdict_field in (
        "operational_state_closure",
        "semantic_unity",
        "isolation_completeness",
    ):
        if report[verdict_field] not in {"pass", "fail", "incomplete"}:
            raise ProtocolViolation(f"report {verdict_field} has an unknown verdict")
    _name(report["isolation_assurance"], "report isolation_assurance")

    findings = report["findings"]
    failure_codes = report["failure_codes"]
    if type(findings) is not list or any(type(item) is not dict for item in findings):
        raise ProtocolViolation("report transcript findings must be a list of objects")
    if type(failure_codes) is not list or any(
        type(item) is not str or not item or item.strip() != item
        for item in failure_codes
    ):
        raise ProtocolViolation(
            "report transcript failure_codes must be a canonical string list"
        )
    derived_failure_codes: list[str] = []
    for index, finding in enumerate(findings):
        if set(finding) != _FINDING_KEYS:
            raise ProtocolViolation(
                f"report finding {index} must be one closed finding record"
            )
        _name(finding["gate"], f"report finding {index} gate")
        verdict = finding["verdict"]
        if verdict not in {"pass", "fail", "incomplete"}:
            raise ProtocolViolation(f"report finding {index} has an unknown verdict")
        failure_code = finding["failure_code"]
        if failure_code is not None:
            _name(failure_code, f"report finding {index} failure_code")
        if verdict == "fail":
            if failure_code is None:
                raise ProtocolViolation(
                    f"report failed finding {index} lacks a failure code"
                )
            if failure_code not in _CANONICAL_FAILURE_CODES:
                raise ProtocolViolation(
                    f"report failed finding {index} has a non-canonical failure code"
                )
            gate_tokens = _finding_gate_tokens(finding["gate"])
            if not gate_tokens or any(
                token not in _CANONICAL_FAILURE_CODES_BY_GATE
                for token in gate_tokens
            ):
                raise ProtocolViolation(
                    f"report failed finding {index} has an unknown gate token"
                )
            if not any(
                failure_code in _CANONICAL_FAILURE_CODES_BY_GATE[token]
                for token in gate_tokens
            ):
                raise ProtocolViolation(
                    f"report failed finding {index} has a gate/failure mismatch"
                )
            if failure_code not in derived_failure_codes:
                derived_failure_codes.append(failure_code)
        elif verdict == "pass" and failure_code is not None:
            raise ProtocolViolation(
                f"report passed finding {index} cannot carry a failure code"
            )
        if type(finding["detail"]) is not str:
            raise ProtocolViolation(f"report finding {index} detail must be a string")
        try:
            finding["detail"].encode("utf-8")
        except UnicodeEncodeError as exc:
            raise ProtocolViolation(
                f"report finding {index} detail contains an invalid Unicode surrogate"
            ) from exc
        if type(finding["evidence"]) is not dict:
            raise ProtocolViolation(
                f"report finding {index} evidence must be an exact object"
            )
    if any(
        item.get("failure_code") == HARNESS_INCOMPLETE_CODE for item in findings
    ) or HARNESS_INCOMPLETE_CODE in failure_codes:
        raise ProtocolViolation("killed/passed report contains harness-incomplete finding")
    if failure_codes != derived_failure_codes:
        raise ProtocolViolation(
            "report failure_codes do not equal the ordered unique failed findings"
        )
    invalid_incomplete = [
        item
        for item in findings
        if item["verdict"] == "incomplete"
        and item["failure_code"] not in _ALLOWED_SCOPE_INCOMPLETE_CODES
    ]
    if invalid_incomplete:
        raise ProtocolViolation(
            "killed/passed report contains a non-scope incomplete finding"
        )
    if report["semantic_unity"] != "incomplete":
        raise ProtocolViolation(
            "decisive report must retain semantic-unity incompleteness"
        )
    if report["isolation_completeness"] != "incomplete":
        raise ProtocolViolation(
            "decisive report must retain isolation incompleteness"
        )
    fixed_scope_rows = [
        (item["gate"], item["verdict"], item["failure_code"])
        for item in findings
        if item["failure_code"] in _ALLOWED_SCOPE_INCOMPLETE_CODES
    ]
    if (
        len(fixed_scope_rows) != len(_FIXED_SCOPE_FINDINGS)
        or set(fixed_scope_rows) != _FIXED_SCOPE_FINDINGS
    ):
        raise ProtocolViolation(
            "decisive report lacks the exact fixed scope findings"
        )
    if report["execution_binding_error"] is not None:
        raise ProtocolViolation("killed/passed report has incomplete execution binding")
    execution_binding = report["execution_binding"]
    if (
        type(execution_binding) is not dict
        or set(execution_binding) != _EXECUTION_BINDING_KEYS
        or any(
            type(key) is not str
            or not key
            or type(value) is not str
            or not value
            or value.strip() != value
            for key, value in execution_binding.items()
        )
    ):
        raise ProtocolViolation(
            "killed/passed report lacks the exact execution binding identity"
        )
    for digest_field in _EXECUTION_BINDING_KEYS.difference({"module_origin"}):
        _digest(execution_binding[digest_field], f"execution binding {digest_field}")
    _module_origin(execution_binding["module_origin"], "execution binding module_origin")
    if execution_binding["module_origin"] != _expected_module_origin(
        code_owned_candidate
    ):
        raise ProtocolViolation(
            "execution binding module_origin differs from the code-owned control "
            "module derived from the expected candidate"
        )
    expected_candidate = pre.get("expected_candidate")
    if expected_candidate != code_owned_candidate:
        raise ProtocolViolation("pre-source witness lacks its exact candidate identity")
    if report["control_class_name"] != expected_control:
        raise ProtocolViolation("report control identity mismatch")
    if report["expected_candidate"] != expected_candidate:
        raise ProtocolViolation("report expected candidate identity mismatch")
    if report["candidate"] != expected_candidate:
        raise ProtocolViolation("report candidate identity mismatch")
    _seed(report["execution_seed"], "report execution_seed")
    if report["execution_seed"] != observation.execution_seed:
        raise ProtocolViolation("report execution seed mismatch")
    for field_name in _EXECUTION_BINDING_KEYS:
        if report[field_name] != execution_binding[field_name]:
            raise ProtocolViolation(
                f"report {field_name} differs from its execution binding"
            )
    head_records = report["head_records"]
    if type(head_records) is not list:
        raise ProtocolViolation("report head_records must be an exact list")
    if expected_head_record_shape == "empty":
        if head_records:
            raise ProtocolViolation(
                "report head_records differ from the code-owned empty subject shape"
            )
    elif expected_head_record_shape == "replay_ddrr":
        if len(head_records) != 4:
            raise ProtocolViolation(
                "report head_records must contain the code-owned exact DDRR replay shape"
            )
    else:  # pragma: no cover - guarded by the module-owned registry literal.
        raise ProtocolViolation("code-owned head record shape is unknown")
    observed_head_operations: list[tuple[str, int]] = []
    for index, head_record in enumerate(head_records):
        if type(head_record) is not dict or set(head_record) != _HEAD_RECORD_KEYS:
            raise ProtocolViolation(
                f"report head record {index} must be one closed execution record"
            )
        for field_name in _EXECUTION_BINDING_KEYS:
            if head_record[field_name] != execution_binding[field_name]:
                raise ProtocolViolation(
                    f"report head record {index} execution binding mismatch"
                )
        operation = head_record["operation"]
        expected_seed = {
            "diagnose": observation.execution_seed + 1,
            "rollout": observation.execution_seed + 2,
        }.get(operation)
        _seed(head_record["seed"], f"report head record {index} seed")
        if expected_seed is None or head_record["seed"] != expected_seed:
            raise ProtocolViolation(
                f"report head record {index} operation/seed binding mismatch"
            )
        observed_head_operations.append((operation, head_record["seed"]))
        for digest_field in (
            "consumed_state_hash",
            "request_digest",
            "response_digest",
        ):
            _digest(
                head_record[digest_field],
                f"report head record {index} {digest_field}",
            )
        if head_record["isolation"] != "fresh-python-process-audit-v2":
            raise ProtocolViolation(
                f"report head record {index} isolation protocol mismatch"
            )
    expected_head_operations = [
        ("diagnose", observation.execution_seed + 1),
        ("diagnose", observation.execution_seed + 1),
        ("rollout", observation.execution_seed + 2),
        ("rollout", observation.execution_seed + 2),
    ]
    if (
        expected_head_record_shape == "replay_ddrr"
        and observed_head_operations != expected_head_operations
    ):
        raise ProtocolViolation(
            "report head_records do not contain the exact replay operation/seed sequence"
        )
    if (
        expected_head_record_shape == "replay_ddrr"
        and len(
            {
                head_record["consumed_state_hash"]
                for head_record in head_records
            }
        )
        != 1
    ):
        raise ProtocolViolation(
            "report replay head_records do not bind one shared consumed state"
        )
    if expected_head_record_shape == "replay_ddrr":
        pair_indices = ((0, 1), (2, 3))
        request_bound_fields = _HEAD_RECORD_KEYS.difference(
            {"response_digest"}
        )
        for left_index, right_index in pair_indices:
            if any(
                head_records[left_index][field_name]
                != head_records[right_index][field_name]
                for field_name in request_bound_fields
            ):
                raise ProtocolViolation(
                    "report replay operation pair request/state/binding drifted"
                )
        response_pair_drift = any(
            head_records[left_index]["response_digest"]
            != head_records[right_index]["response_digest"]
            for left_index, right_index in pair_indices
        )
        if response_pair_drift and not (
            expected_failure_code == "UCM-F020-NONREPRODUCIBLE"
            and "UCM-F020-NONREPRODUCIBLE" in failure_codes
        ):
            raise ProtocolViolation(
                "report replay response drift lacks the code-owned canonical "
                "UCM-F020-NONREPRODUCIBLE failure"
            )
        if (
            expected_failure_code == "UCM-F020-NONREPRODUCIBLE"
            and observation.outcome is ObservationOutcome.KILLED
            and not response_pair_drift
        ):
            raise ProtocolViolation(
                "UCM-F020 decisive report lacks actual DDRR head-pair response drift"
            )
    (
        invocation_transcript_digest,
        _actual_input_coverage,
        actual_probe_evidence,
    ) = _validate_request_records(
        report["request_records"],
        input_preimage_digest=input_preimage_digest,
        history=input_history,
        diagnosis_query=input_diagnosis_query,
        rollout_query=input_rollout_query,
        delta=input_delta,
        execution_seed=observation.execution_seed,
        expected_subject_id=observation.subject_id,
        expected_failure_code=expected_failure_code,
        expected_semantic_probes=expected_semantic_probes,
        expected_head_record_shape=expected_head_record_shape,
        observation_outcome=observation.outcome,
        head_records=head_records,
        expected_execution_binding=execution_binding,
    )
    if report["invocation_transcript_digest"] != invocation_transcript_digest:
        raise ProtocolViolation("report invocation_transcript_digest mismatch")
    if report["harness_stable_during_execution"] is not True:
        raise ProtocolViolation("killed/passed report does not prove stable harness")
    if report["post_source_witness_error"] is not None:
        raise ProtocolViolation("killed/passed report has a post-witness error")
    if report["pre_source_witness_digest"] != _json_digest(
        pre, "pre-source witness"
    ):
        raise ProtocolViolation("report pre-source witness digest mismatch")
    if report["post_source_witness_digest"] != _json_digest(
        post, "post-source witness"
    ):
        raise ProtocolViolation("report post-source witness digest mismatch")
    if pre.get("expected_live_execution_binding") != execution_binding:
        raise ProtocolViolation("pre-source witness execution binding mismatch")

    missing_source_fields = _SOURCE_REQUIRED_FIELDS.difference(source)
    extra_source_fields = set(source).difference(_SOURCE_REQUIRED_FIELDS)
    if missing_source_fields or extra_source_fields:
        raise ProtocolViolation(
            "killed/passed source record does not have the exact execution fields; "
            f"missing={sorted(missing_source_fields)!r}, "
            f"extra={sorted(extra_source_fields)!r}"
        )
    if source["runner_protocol"] != expected_runner_protocol:
        raise ProtocolViolation("source record runner_protocol differs from bundle runner")
    executed_source = source["execution_bound_source_witness"]
    executed_source = _closed_object(
        executed_source,
        frozenset({"protocol", "harness_witness", "execution_binding"}),
        "executed source witness",
    )
    if executed_source["protocol"] != "ucm-portable-executed-source-binding/2":
        raise ProtocolViolation("executed source witness protocol mismatch")
    if executed_source["harness_witness"] != pre:
        raise ProtocolViolation("executed source witness does not bind the pre witness")
    if executed_source["execution_binding"] != execution_binding:
        raise ProtocolViolation("executed source witness execution binding mismatch")
    if source["execution_bound_source_witness_digest"] != _json_digest(
        executed_source, "executed source witness"
    ):
        raise ProtocolViolation("executed source witness digest mismatch")
    if source["pre_source_witness_digest"] != _json_digest(
        pre, "pre-source witness"
    ):
        raise ProtocolViolation("source record pre-source witness digest mismatch")
    if source["post_source_witness_digest"] != _json_digest(
        post, "post-source witness"
    ):
        raise ProtocolViolation("source record post-source witness digest mismatch")
    if source["harness_stable_during_execution"] is not True:
        raise ProtocolViolation("source record does not prove stable harness")

    if decision.get("runner_protocol") != expected_runner_protocol:
        raise ProtocolViolation("decision runner_protocol differs from bundle runner")
    if decision.get("input_preimage_digest") != input_preimage_digest:
        raise ProtocolViolation("decision input_preimage_digest binding mismatch")
    if decision.get("invocation_transcript_digest") != invocation_transcript_digest:
        raise ProtocolViolation("decision invocation_transcript_digest binding mismatch")
    if decision.get("report_available") is not True:
        raise ProtocolViolation("decisive decision does not bind an available report")
    if decision.get("harness_stable_during_execution") is not True:
        raise ProtocolViolation("decisive decision does not bind a stable harness")
    if decision.get("execution_binding_complete") is not True:
        raise ProtocolViolation("decisive decision lacks complete execution binding")
    decisive = _payload_object(decisive_body, "decisive record")
    if decisive.get("input_preimage_digest") != input_preimage_digest:
        raise ProtocolViolation("decisive input_preimage_digest binding mismatch")
    if decisive.get("invocation_transcript_digest") != invocation_transcript_digest:
        raise ProtocolViolation("decisive invocation_transcript_digest binding mismatch")
    expected_payload_digests = {
        "source_record_payload_digest": _json_digest(source, "source record"),
        "report_transcript_payload_digest": _json_digest(report, "report transcript"),
        "decision_record_payload_digest": _json_digest(decision, "decision record"),
    }
    for field_name, expected_digest in expected_payload_digests.items():
        if decisive.get(field_name) != expected_digest:
            raise ProtocolViolation(
                f"decisive record {field_name} does not bind its raw payload"
            )

    if observation.outcome is ObservationOutcome.KILLED:
        decision = _closed_object(
            decision, _MUTANT_DECISION_KEYS, "mutant decision record"
        )
        if report["operational_state_closure"] != "fail":
            raise ProtocolViolation(
                "killed mutant report must have operational closure FAIL"
            )
        decisive = _closed_object(
            decisive,
            frozenset(
                {
                    "runner_protocol",
                    "decision_kind",
                    "candidate",
                    "finding",
                    "source_record_payload_digest",
                    "report_transcript_payload_digest",
                    "decision_record_payload_digest",
                    "runtime_metadata",
                    "input_preimage_digest",
                    "invocation_transcript_digest",
                }
            ),
            "mutant decisive record",
        )
        if decisive["runtime_metadata"] != execution_context_payload["runtime_metadata"]:
            raise ProtocolViolation(
                "mutant decisive runtime metadata differs from execution context"
            )
        code_matches = [
            item
            for item in findings
            if item.get("verdict") == "fail"
            and item.get("failure_code") == observation.actual_failure_code
        ]
        if len(code_matches) != 1:
            raise ProtocolViolation(
                "killed observation is not derived from exactly one matching "
                "report finding for its failure code"
            )
        matches = [
            item
            for item in code_matches
            if observation.actual_gate in _finding_gate_tokens(item.get("gate"))
        ]
        if len(matches) != 1:
            raise ProtocolViolation(
                "killed observation is not derived from one matching report finding"
            )
        finding_evidence = matches[0]["evidence"]
        if observation.actual_failure_code == "UCM-F019-UPDATE_INCONSISTENT":
            actual_consistency = actual_probe_evidence.get("update_consistency")
            if type(actual_consistency) is not dict:
                raise ProtocolViolation(
                    "UCM-F019 finding lacks an actual update-consistency transcript"
                )
            evidence_fields = (
                "incremental_behavior_digest",
                "replay_behavior_digest",
                "duplicate_behavior_digest",
                "incremental_equals_replay",
                "duplicate_event_is_idempotent",
            )
            if any(
                finding_evidence.get(field_name)
                != actual_consistency[field_name]
                for field_name in evidence_fields
            ):
                raise ProtocolViolation(
                    "UCM-F019 finding evidence differs from actual scored "
                    "incremental/replay/duplicate responses"
                )
        if (
            observation.actual_failure_code == "UCM-F001-FUTURE_LEAK"
            and "warm_future_old_cut" in expected_semantic_probes
        ):
            actual_warm = actual_probe_evidence.get("warm_future_old_cut")
            if type(actual_warm) is not dict:
                raise ProtocolViolation(
                    "UCM-F001 finding lacks an actual warm-future transcript"
                )
            evidence_fields = (
                "before_behavior_digest",
                "before_raw_wire_digest",
                "after_initialize_later_digest",
                "after_initialize_later_raw_wire_digest",
                "after_update_old_delta_digest",
                "after_update_old_delta_raw_wire_digest",
                "initialize_later_stable",
                "update_old_delta_stable",
                "initialize_later_raw_exact",
                "update_old_delta_raw_exact",
            )
            if any(
                finding_evidence.get(field_name) != actual_warm[field_name]
                for field_name in evidence_fields
            ):
                raise ProtocolViolation(
                    "UCM-F001 finding evidence differs from actual old-cut "
                    "semantic/raw responses"
                )
        evaluator_probe_by_code = {
            "UCM-F015-CONDITIONING_AS_INTERVENTION": "nonidentified_set",
            "UCM-F016-DANGEROUS_COLLISION": "dangerous_collision",
            "UCM-F017-OOD_FORCED_MATCH": "unsafe_closed_world",
        }
        evaluator_probe = evaluator_probe_by_code.get(
            observation.actual_failure_code
        )
        if evaluator_probe is not None:
            actual_artifact = actual_probe_evidence.get(evaluator_probe)
            if type(actual_artifact) is not dict or _canonical_bytes(
                finding_evidence, "stored evaluator finding evidence"
            ) != _canonical_bytes(
                actual_artifact, "rebuilt evaluator finding evidence"
            ):
                raise ProtocolViolation(
                    "evaluator finding evidence differs from the exact rebuilt "
                    "request/fixture/oracle/manifest/report artifact"
                )
        if observation.actual_failure_code not in failure_codes:
            raise ProtocolViolation(
                "killed observation failure code is absent from report failure_codes"
            )
        if decisive.get("decision_kind") != "mutant_kill":
            raise ProtocolViolation("mutant kill has the wrong decisive decision_kind")
        if decisive["runner_protocol"] != expected_runner_protocol:
            raise ProtocolViolation("mutant decisive runner_protocol mismatch")
        if decisive["candidate"] != report["candidate"]:
            raise ProtocolViolation("mutant decisive candidate mismatch")
        if decisive["finding"] != matches[0]:
            raise ProtocolViolation("mutant decisive finding differs from report")
        if decision.get("decision_kind") != "mutant-observation":
            raise ProtocolViolation("mutant decision has the wrong decision_kind")
        if decision.get("actual_gate") != observation.actual_gate:
            raise ProtocolViolation("mutant decision actual_gate mismatch")
        if decision.get("actual_failure_code") != observation.actual_failure_code:
            raise ProtocolViolation("mutant decision actual_failure_code mismatch")
        if decision.get("expected_gate") != observation.actual_gate:
            raise ProtocolViolation("mutant decision expected_gate mismatch")
        if decision.get("expected_failure_code") != observation.actual_failure_code:
            raise ProtocolViolation("mutant decision expected_failure_code mismatch")
        if decision.get("harness_incomplete") is not False:
            raise ProtocolViolation("mutant decisive decision is harness-incomplete")
        if decision.get("decision_processing_complete") is not True:
            raise ProtocolViolation("mutant decisive decision processing is incomplete")
    else:
        decision = _closed_object(
            decision,
            _SPECIFICITY_DECISION_KEYS,
            "specificity decision record",
        )
        decisive = _closed_object(
            decisive,
            frozenset(
                {
                    "runner_protocol",
                    "decision_kind",
                    "candidate",
                    "classification",
                    "source_record_payload_digest",
                    "report_transcript_payload_digest",
                    "decision_record_payload_digest",
                    "runtime_metadata",
                    "input_preimage_digest",
                    "invocation_transcript_digest",
                }
            ),
            "specificity decisive record",
        )
        if decisive["runtime_metadata"] != execution_context_payload["runtime_metadata"]:
            raise ProtocolViolation(
                "specificity decisive runtime metadata differs from execution context"
            )
        if report.get("operational_state_closure") != "pass":
            raise ProtocolViolation(
                "passed specificity control lacks operational closure PASS"
            )
        if failure_codes or any(item.get("verdict") == "fail" for item in findings):
            raise ProtocolViolation(
                "passed specificity control contains a failed finding"
            )
        if (
            head_records[0] != head_records[1]
            or head_records[2] != head_records[3]
        ):
            raise ProtocolViolation(
                "passed specificity replay heads are not internally consistent"
            )
        paired = report["paired_semantic_equivalence"]
        if observation.subject_id == "BehaviorEquivalentSerialization":
            try:
                _validate_paired_semantic_evidence(
                    paired,
                    expected_phases=expected_paired_phases,
                )
            except ProtocolViolation as exc:
                raise ProtocolViolation(
                    "passed behavior-equivalent control lacks closed paired evidence"
                ) from exc
        elif paired is not None:
            raise ProtocolViolation(
                "non-paired specificity control cannot carry paired evidence"
            )
        if observation.subject_id == "CorrectNonidentifiedSet":
            actual_artifact = actual_probe_evidence.get("nonidentified_set")
            c19_passes = [
                item
                for item in findings
                if item.get("gate") == "C19-nonidentified-effect-set"
                and item.get("verdict") == "pass"
                and item.get("failure_code") is None
            ]
            if (
                type(actual_artifact) is not dict
                or len(c19_passes) != 1
                or _canonical_bytes(
                    c19_passes[0].get("evidence"),
                    "stored CorrectNonidentifiedSet evidence",
                )
                != _canonical_bytes(
                    actual_artifact,
                    "rebuilt CorrectNonidentifiedSet evidence",
                )
                or actual_artifact["evaluation_report"]["failures"] != []
            ):
                raise ProtocolViolation(
                    "CorrectNonidentifiedSet lacks one exact rebuilt C19 pass artifact"
                )
        if decisive.get("decision_kind") != "specificity_pass":
            raise ProtocolViolation(
                "specificity pass has the wrong decisive decision_kind"
            )
        if decisive["runner_protocol"] != expected_runner_protocol:
            raise ProtocolViolation("specificity decisive runner_protocol mismatch")
        if decisive["candidate"] != report["candidate"]:
            raise ProtocolViolation("specificity decisive candidate mismatch")
        if decisive["classification"] != observation.classification:
            raise ProtocolViolation("specificity decisive classification mismatch")
        if decision.get("decision_kind") != "specificity-observation":
            raise ProtocolViolation("specificity decision has the wrong decision_kind")
        if decision.get("classification") != observation.classification:
            raise ProtocolViolation("specificity decision classification mismatch")
        if decision.get("probe_incomplete") is not False:
            raise ProtocolViolation("specificity decisive decision has incomplete probes")
        if decision.get("report_processing_complete") is not True:
            raise ProtocolViolation("specificity report processing is incomplete")
        expected_semantic_equivalence = None if paired is None else True
        if (
            decision.get("semantic_equivalence_passed")
            is not expected_semantic_equivalence
        ):
            raise ProtocolViolation(
                "specificity decision paired-probe state differs from report"
            )


@dataclass(frozen=True, slots=True)
class MutationEvidenceBundle:
    """Closed same-run mutation evidence plus its recomputed matrix bytes."""

    run_id: str
    benchmark_id: str
    base_seed: int
    runner_protocol: str
    registry_digest: str
    execution_context_digest: str
    matrix_blob_digest: str
    records: tuple[MutationEvidenceRecord, ...]
    blobs: tuple[ContentAddressedBlob, ...]

    def __post_init__(self) -> None:
        _name(self.run_id, "bundle run_id")
        if self.benchmark_id != BENCHMARK_ID:
            raise ProtocolViolation(f"bundle benchmark_id must be {BENCHMARK_ID!r}")
        _validate_base_seed_execution_domain(self.base_seed, "bundle base_seed")
        _name(self.runner_protocol, "bundle runner_protocol")
        if self.registry_digest != REGISTRY_DIGEST:
            raise ProtocolViolation("bundle registry_digest differs from live registry")
        _digest(self.execution_context_digest, "bundle execution_context_digest")
        _digest(self.matrix_blob_digest, "bundle matrix_blob_digest")
        if type(self.records) is not tuple or any(
            type(record) is not MutationEvidenceRecord for record in self.records
        ):
            raise ProtocolViolation("bundle records must be an exact typed tuple")
        if type(self.blobs) is not tuple or any(
            type(blob) is not ContentAddressedBlob for blob in self.blobs
        ):
            raise ProtocolViolation("bundle blobs must be an exact typed tuple")
        if self.records != tuple(sorted(self.records, key=_record_sort_key)):
            raise ProtocolViolation("bundle records are not canonically sorted")
        record_identities = tuple(
            (
                record.observation.subject_kind.value,
                record.observation.subject_id,
                record.observation.execution_seed,
            )
            for record in self.records
        )
        if len(record_identities) != len(set(record_identities)):
            raise ProtocolViolation("bundle contains duplicate subject execution identity")
        if self.blobs != tuple(sorted(self.blobs, key=lambda blob: blob.digest)):
            raise ProtocolViolation("bundle blobs are not canonically digest-sorted")
        blob_digests = tuple(blob.digest for blob in self.blobs)
        if len(blob_digests) != len(set(blob_digests)):
            raise ProtocolViolation("bundle contains duplicate blob digests")
        self._validate_content_closure()

    @property
    def observations(self) -> tuple[MutationObservation, ...]:
        return tuple(record.observation for record in self.records)

    def blob_bytes(self, digest: str) -> bytes:
        _digest(digest, "requested blob digest")
        for blob in self.blobs:
            if blob.digest == digest:
                return blob.payload
        raise ProtocolViolation(f"bundle does not contain blob {digest}")

    def _validate_content_closure(self) -> None:
        blob_map = {blob.digest: blob.payload for blob in self.blobs}
        context_payload = blob_map.get(self.execution_context_digest)
        if context_payload is None:
            raise ProtocolViolation("execution context blob is missing")
        context = _closed_object(
            _decode_canonical_json(context_payload, "execution context blob"),
            frozenset(
                {
                    "protocol",
                    "run_id",
                    "benchmark_id",
                    "runner_protocol",
                    "registry_digest",
                    "base_seed",
                    "input_preimage_digest",
                    "payload",
                }
            ),
            "execution context blob",
        )
        expected_context = {
            "protocol": MUTATION_EXECUTION_CONTEXT_PROTOCOL,
            "run_id": self.run_id,
            "benchmark_id": self.benchmark_id,
            "runner_protocol": self.runner_protocol,
            "registry_digest": self.registry_digest,
            "base_seed": self.base_seed,
        }
        for key, value in expected_context.items():
            if context[key] != value:
                raise ProtocolViolation(f"execution context {key} binding mismatch")
        execution_context_payload = _closed_object(
            context["payload"],
            _EXECUTION_CONTEXT_KEYS,
            "execution context payload",
        )
        if execution_context_payload["benchmark_id"] != self.benchmark_id:
            raise ProtocolViolation(
                "execution context payload benchmark_id binding mismatch"
            )
        if type(execution_context_payload["runtime_metadata"]) is not dict:
            raise ProtocolViolation(
                "execution context runtime_metadata must be an exact object"
            )
        if execution_context_payload[
            "portable_runner_contract"
        ] != portable_runner_contract(self.runner_protocol):
            raise ProtocolViolation(
                "execution context portable runner contract differs from code-owned registry"
            )
        runtime_cache_digest = execution_context_payload[
            "runtime_import_cache_contract_digest"
        ]
        source_preparation_error = execution_context_payload[
            "source_preparation_error"
        ]
        if source_preparation_error is None:
            _digest(
                runtime_cache_digest,
                "execution context runtime import cache contract digest",
            )
        else:
            if runtime_cache_digest is not None:
                raise ProtocolViolation(
                    "source preparation failure cannot carry a runtime cache digest"
                )
            source_preparation_error = _closed_object(
                source_preparation_error,
                _SOURCE_PREPARATION_ERROR_KEYS,
                "source preparation error",
            )
            if source_preparation_error["stage"] != "runtime-import-preparation":
                raise ProtocolViolation("source preparation error stage mismatch")
            _name(
                source_preparation_error["exception_type"],
                "source preparation exception_type",
            )
            message = source_preparation_error["message"]
            if type(message) is not str:
                raise ProtocolViolation(
                    "source preparation error message must be a string"
                )
            try:
                message.encode("utf-8")
            except UnicodeEncodeError as exc:
                raise ProtocolViolation(
                    "source preparation error message contains an invalid Unicode surrogate"
                ) from exc
        input_digest = _digest(
            context["input_preimage_digest"], "context input_preimage_digest"
        )
        input_payload = blob_map.get(input_digest)
        if input_payload is None:
            raise ProtocolViolation("input preimage blob is missing")
        input_body = _closed_object(
            _decode_canonical_json(input_payload, "input preimage blob"),
            frozenset({"protocol", "run_id", "payload"}),
            "input preimage blob",
        )
        if (
            input_body["protocol"] != MUTATION_INPUT_PREIMAGE_PROTOCOL
            or input_body["run_id"] != self.run_id
        ):
            raise ProtocolViolation("input preimage run/protocol binding mismatch")
        input_preimage = _closed_object(
            input_body["payload"],
            _INPUT_PREIMAGE_KEYS,
            "input preimage payload",
        )
        (
            input_history,
            input_diagnosis_query,
            input_rollout_query,
            input_delta,
        ) = _typed_input_preimage(input_preimage)
        expected_paired_phases = (
            ("initialize", "update")
            if input_delta is not None
            else ("initialize",)
        )

        expected_blob_digests = {
            self.execution_context_digest,
            input_digest,
            self.matrix_blob_digest,
        }
        for record in self.records:
            if record.run_id != self.run_id:
                raise ProtocolViolation("record run_id differs from bundle run_id")
            if record.execution_context_digest != self.execution_context_digest:
                raise ProtocolViolation(
                    "record execution context differs from bundle context"
                )
            subject_blobs: dict[str, dict[str, Any]] = {}
            role_specs = (
                (
                    "pre_source_witness_digest",
                    MUTATION_PRE_SOURCE_WITNESS_PROTOCOL,
                    {},
                ),
                (
                    "post_source_witness_digest",
                    MUTATION_POST_SOURCE_WITNESS_PROTOCOL,
                    {},
                ),
                (
                    "source_record_digest",
                    MUTATION_SOURCE_RECORD_PROTOCOL,
                    {
                        "pre_source_witness_digest": record.pre_source_witness_digest,
                        "post_source_witness_digest": record.post_source_witness_digest,
                    },
                ),
                (
                    "error_transcript_digest",
                    MUTATION_ERROR_TRANSCRIPT_PROTOCOL,
                    {
                        "source_record_digest": record.source_record_digest,
                        "report_transcript_digest": record.report_transcript_digest,
                    },
                ),
                (
                    "decision_record_digest",
                    MUTATION_DECISION_RECORD_PROTOCOL,
                    {
                        "pre_source_witness_digest": record.pre_source_witness_digest,
                        "post_source_witness_digest": record.post_source_witness_digest,
                        "source_record_digest": record.source_record_digest,
                        "report_transcript_digest": record.report_transcript_digest,
                        "error_transcript_digest": record.error_transcript_digest,
                        "input_preimage_digest": input_digest,
                    },
                ),
            )
            for field_name, protocol, references in role_specs:
                artifact_digest = getattr(record, field_name)
                payload = blob_map.get(artifact_digest)
                if payload is None:
                    raise ProtocolViolation(f"record blob is missing: {field_name}")
                subject_blobs[field_name] = _validate_subject_blob(
                    payload,
                    protocol=protocol,
                    record=record,
                    expected_references=references,
                    label=field_name,
                )
                expected_blob_digests.add(artifact_digest)
            report_body: dict[str, Any] | None = None
            if record.report_transcript_digest is not None:
                payload = blob_map.get(record.report_transcript_digest)
                if payload is None:
                    raise ProtocolViolation("record report transcript blob is missing")
                report_body = _validate_subject_blob(
                    payload,
                    protocol=MUTATION_REPORT_TRANSCRIPT_PROTOCOL,
                    record=record,
                    expected_references={
                        "source_record_digest": record.source_record_digest,
                        "input_preimage_digest": input_digest,
                    },
                    label="report_transcript_digest",
                )
                expected_blob_digests.add(record.report_transcript_digest)
            decisive_digest = record.observation.decisive_record_digest
            decisive_body: dict[str, Any] | None = None
            if decisive_digest is not None:
                payload = blob_map.get(decisive_digest)
                if payload is None:
                    raise ProtocolViolation("record decisive blob is missing")
                decisive_body = _validate_subject_blob(
                    payload,
                    protocol=MUTATION_DECISIVE_RECORD_PROTOCOL,
                    record=record,
                    expected_references={
                        "source_record_digest": record.source_record_digest,
                        "report_transcript_digest": record.report_transcript_digest,
                        "decision_record_digest": record.decision_record_digest,
                        "input_preimage_digest": input_digest,
                        "invocation_transcript_digest": _payload_object(
                            report_body, "report transcript"
                        ).get("invocation_transcript_digest"),
                    },
                    label="decisive_record_digest",
                )
                expected_blob_digests.add(decisive_digest)
            _validate_record_semantics(
                record,
                expected_runner_protocol=self.runner_protocol,
                expected_base_seed=self.base_seed,
                expected_paired_phases=expected_paired_phases,
                input_preimage_digest=input_digest,
                input_history=input_history,
                input_diagnosis_query=input_diagnosis_query,
                input_rollout_query=input_rollout_query,
                input_delta=input_delta,
                execution_context_payload=execution_context_payload,
                pre_body=subject_blobs["pre_source_witness_digest"],
                post_body=subject_blobs["post_source_witness_digest"],
                source_body=subject_blobs["source_record_digest"],
                report_body=report_body,
                error_body=subject_blobs["error_transcript_digest"],
                decision_body=subject_blobs["decision_record_digest"],
                decisive_body=decisive_body,
            )

        matrix_payload = blob_map.get(self.matrix_blob_digest)
        if matrix_payload is None:
            raise ProtocolViolation("mutation matrix blob is missing")
        recomputed = evaluate_mutation_matrix(self.observations).canonical_bytes()
        if matrix_payload != recomputed:
            raise ProtocolViolation(
                "matrix blob does not equal registry recomputation from records"
            )
        actual_blob_digests = set(blob_map)
        if actual_blob_digests != expected_blob_digests:
            missing = sorted(expected_blob_digests - actual_blob_digests)
            orphan = sorted(actual_blob_digests - expected_blob_digests)
            raise ProtocolViolation(
                f"bundle blob closure mismatch; missing={missing!r}, orphan={orphan!r}"
            )

    def _body(self) -> dict[str, Any]:
        return {
            "protocol": MUTATION_EVIDENCE_PROTOCOL,
            "status": PRE_FREEZE_STATUS,
            "blockers": list(MUTATION_EVIDENCE_BLOCKERS),
            "freeze_grade_evidence": False,
            "portable_isolation_complete": False,
            "external_custody_verified": False,
            "run_id": self.run_id,
            "benchmark_id": self.benchmark_id,
            "base_seed": self.base_seed,
            "runner_protocol": self.runner_protocol,
            "registry_digest": self.registry_digest,
            "execution_context_digest": self.execution_context_digest,
            "matrix_blob_digest": self.matrix_blob_digest,
            "records": [record.to_wire() for record in self.records],
            "blobs": [blob.to_wire() for blob in self.blobs],
        }

    def to_wire(self) -> dict[str, Any]:
        body = self._body()
        body["bundle_digest"] = _json_digest(body, "mutation evidence bundle")
        return body

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_wire(), "mutation evidence bundle")

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes())

    @classmethod
    def from_canonical_bytes(cls, payload: bytes) -> "MutationEvidenceBundle":
        body = _closed_object(
            _decode_canonical_json(payload, "mutation evidence bundle"),
            frozenset(
                {
                    "protocol",
                    "status",
                    "blockers",
                    "freeze_grade_evidence",
                    "portable_isolation_complete",
                    "external_custody_verified",
                    "run_id",
                    "benchmark_id",
                    "base_seed",
                    "runner_protocol",
                    "registry_digest",
                    "execution_context_digest",
                    "matrix_blob_digest",
                    "records",
                    "blobs",
                    "bundle_digest",
                }
            ),
            "mutation evidence bundle",
        )
        fixed = {
            "protocol": MUTATION_EVIDENCE_PROTOCOL,
            "status": PRE_FREEZE_STATUS,
            "blockers": list(MUTATION_EVIDENCE_BLOCKERS),
            "freeze_grade_evidence": False,
            "portable_isolation_complete": False,
            "external_custody_verified": False,
        }
        for key, value in fixed.items():
            if body[key] != value:
                raise ProtocolViolation(f"bundle code-owned field differs: {key}")
        claimed_digest = _digest(body["bundle_digest"], "bundle_digest")
        unsigned = {key: value for key, value in body.items() if key != "bundle_digest"}
        if _json_digest(unsigned, "unsigned mutation evidence bundle") != claimed_digest:
            raise ProtocolViolation("mutation evidence bundle self-digest mismatch")
        if type(body["records"]) is not list:
            raise ProtocolViolation("bundle records must be a list")
        if type(body["blobs"]) is not list:
            raise ProtocolViolation("bundle blobs must be a list")
        records = tuple(MutationEvidenceRecord.from_wire(row) for row in body["records"])
        blobs = tuple(ContentAddressedBlob.from_wire(row) for row in body["blobs"])
        return cls(
            run_id=body["run_id"],
            benchmark_id=body["benchmark_id"],
            base_seed=body["base_seed"],
            runner_protocol=body["runner_protocol"],
            registry_digest=body["registry_digest"],
            execution_context_digest=body["execution_context_digest"],
            matrix_blob_digest=body["matrix_blob_digest"],
            records=records,
            blobs=blobs,
        )


class MutationEvidenceBuilder:
    """Single-use builder that captures raw preimages before they can be lost."""

    def __init__(
        self,
        *,
        run_id: str,
        runner_protocol: str,
        base_seed: int,
        input_preimage: Any,
        execution_context: Any,
    ) -> None:
        self.run_id = _name(run_id, "builder run_id")
        self.runner_protocol = _name(runner_protocol, "builder runner_protocol")
        self.base_seed = _validate_base_seed_execution_domain(
            base_seed, "builder base_seed"
        )
        self._blobs: dict[str, ContentAddressedBlob] = {}
        self._records: list[MutationEvidenceRecord] = []
        self._sealed = False
        input_body = {
            "protocol": MUTATION_INPUT_PREIMAGE_PROTOCOL,
            "run_id": self.run_id,
            "payload": input_preimage,
        }
        input_digest = self._add_json_blob(input_body)
        self._input_preimage_digest = input_digest
        context_body = {
            "protocol": MUTATION_EXECUTION_CONTEXT_PROTOCOL,
            "run_id": self.run_id,
            "benchmark_id": BENCHMARK_ID,
            "runner_protocol": self.runner_protocol,
            "registry_digest": REGISTRY_DIGEST,
            "base_seed": self.base_seed,
            "input_preimage_digest": input_digest,
            "payload": execution_context,
        }
        self.execution_context_digest = self._add_json_blob(context_body)

    @property
    def input_preimage_digest(self) -> str:
        """Content digest of the exact four-input preimage (read-only)."""

        return self._input_preimage_digest

    def _ensure_open(self) -> None:
        if self._sealed:
            raise RuntimeError("mutation evidence builder is already finalized")

    def _add_blob(self, payload: bytes) -> str:
        self._ensure_open()
        blob = ContentAddressedBlob(payload)
        self._blobs.setdefault(blob.digest, blob)
        return blob.digest

    def _add_json_blob(self, value: Any) -> str:
        try:
            validate_json_like(value)
            payload = _canonical_bytes(value, "mutation evidence JSON blob")
        except ProtocolViolation as exc:
            if isinstance(exc.__cause__, UnicodeEncodeError):
                raise ProtocolViolation(
                    "mutation evidence contains an invalid Unicode surrogate"
                ) from exc
            raise
        return self._add_blob(payload)

    def _add_subject_blob(
        self,
        *,
        protocol: str,
        subject_id: str,
        subject_kind: SubjectKind,
        execution_seed: int,
        references: dict[str, Any],
        payload: Any,
    ) -> str:
        return self._add_json_blob(
            _subject_envelope(
                protocol=protocol,
                run_id=self.run_id,
                execution_context_digest=self.execution_context_digest,
                subject_id=subject_id,
                subject_kind=subject_kind,
                execution_seed=execution_seed,
                references=references,
                payload=payload,
            )
        )

    def add_record(
        self,
        *,
        subject_id: str,
        subject_kind: SubjectKind,
        execution_seed: int,
        outcome: ObservationOutcome,
        actual_gate: str | None,
        actual_failure_code: str | None,
        classification: str | None,
        pre_source_witness: Any,
        post_source_witness: Any,
        source_record: Any,
        report_transcript: Any | None,
        error_transcript: Any,
        decision_record: Any,
        decisive_record: Any | None,
    ) -> MutationEvidenceRecord:
        self._ensure_open()
        _name(subject_id, "builder subject_id")
        if type(subject_kind) is not SubjectKind:
            raise ProtocolViolation("builder subject_kind must be SubjectKind")
        _seed(execution_seed, "builder execution_seed")
        if type(outcome) is not ObservationOutcome:
            raise ProtocolViolation("builder outcome must be ObservationOutcome")
        if outcome in {ObservationOutcome.KILLED, ObservationOutcome.PASSED}:
            if decisive_record is None:
                raise ProtocolViolation("killed/passed record needs decisive raw preimage")
            if report_transcript is None:
                raise ProtocolViolation("killed/passed record needs raw report transcript")
        elif decisive_record is not None:
            raise ProtocolViolation("non-decisive outcome cannot supply decisive preimage")

        identity = {
            "subject_id": subject_id,
            "subject_kind": subject_kind,
            "execution_seed": execution_seed,
        }
        pre_digest = self._add_subject_blob(
            protocol=MUTATION_PRE_SOURCE_WITNESS_PROTOCOL,
            references={},
            payload=pre_source_witness,
            **identity,
        )
        post_digest = self._add_subject_blob(
            protocol=MUTATION_POST_SOURCE_WITNESS_PROTOCOL,
            references={},
            payload=post_source_witness,
            **identity,
        )
        source_digest = self._add_subject_blob(
            protocol=MUTATION_SOURCE_RECORD_PROTOCOL,
            references={
                "pre_source_witness_digest": pre_digest,
                "post_source_witness_digest": post_digest,
            },
            payload=source_record,
            **identity,
        )
        report_digest = (
            self._add_subject_blob(
                protocol=MUTATION_REPORT_TRANSCRIPT_PROTOCOL,
                references={
                    "source_record_digest": source_digest,
                    "input_preimage_digest": self.input_preimage_digest,
                },
                payload=report_transcript,
                **identity,
            )
            if report_transcript is not None
            else None
        )
        error_digest = self._add_subject_blob(
            protocol=MUTATION_ERROR_TRANSCRIPT_PROTOCOL,
            references={
                "source_record_digest": source_digest,
                "report_transcript_digest": report_digest,
            },
            payload=error_transcript,
            **identity,
        )
        decision_digest = self._add_subject_blob(
            protocol=MUTATION_DECISION_RECORD_PROTOCOL,
            references={
                "pre_source_witness_digest": pre_digest,
                "post_source_witness_digest": post_digest,
                "source_record_digest": source_digest,
                "report_transcript_digest": report_digest,
                "error_transcript_digest": error_digest,
                "input_preimage_digest": self.input_preimage_digest,
            },
            payload=decision_record,
            **identity,
        )
        decisive_digest = (
            self._add_subject_blob(
                protocol=MUTATION_DECISIVE_RECORD_PROTOCOL,
                references={
                    "source_record_digest": source_digest,
                    "report_transcript_digest": report_digest,
                    "decision_record_digest": decision_digest,
                    "input_preimage_digest": self.input_preimage_digest,
                    "invocation_transcript_digest": (
                        report_transcript.get("invocation_transcript_digest")
                        if type(report_transcript) is dict
                        else None
                    ),
                },
                payload=decisive_record,
                **identity,
            )
            if decisive_record is not None
            else None
        )
        observation = MutationObservation(
            subject_id=subject_id,
            subject_kind=subject_kind,
            source_digest=source_digest,
            execution_seed=execution_seed,
            outcome=outcome,
            actual_gate=actual_gate,
            actual_failure_code=actual_failure_code,
            decisive_record_digest=decisive_digest,
            classification=classification,
        )
        record = MutationEvidenceRecord(
            run_id=self.run_id,
            execution_context_digest=self.execution_context_digest,
            observation=observation,
            pre_source_witness_digest=pre_digest,
            post_source_witness_digest=post_digest,
            source_record_digest=source_digest,
            report_transcript_digest=report_digest,
            error_transcript_digest=error_digest,
            decision_record_digest=decision_digest,
        )
        identity_key = (subject_kind.value, subject_id, execution_seed)
        if any(
            (
                existing.observation.subject_kind.value,
                existing.observation.subject_id,
                existing.observation.execution_seed,
            )
            == identity_key
            for existing in self._records
        ):
            raise ProtocolViolation("builder contains duplicate subject execution identity")
        self._records.append(record)
        return record

    def finalize(self) -> MutationEvidenceBundle:
        self._ensure_open()
        records = tuple(sorted(self._records, key=_record_sort_key))
        matrix_bytes = evaluate_mutation_matrix(
            tuple(record.observation for record in records)
        ).canonical_bytes()
        matrix_digest = self._add_blob(matrix_bytes)
        self._sealed = True
        return MutationEvidenceBundle(
            run_id=self.run_id,
            benchmark_id=BENCHMARK_ID,
            base_seed=self.base_seed,
            runner_protocol=self.runner_protocol,
            registry_digest=REGISTRY_DIGEST,
            execution_context_digest=self.execution_context_digest,
            matrix_blob_digest=matrix_digest,
            records=records,
            blobs=tuple(sorted(self._blobs.values(), key=lambda blob: blob.digest)),
        )


__all__ = [
    "BENCHMARK_ID",
    "ContentAddressedBlob",
    "HARNESS_INCOMPLETE_CODE",
    "ISOLATION_INCOMPLETE_CODE",
    "MUTATION_DECISION_RECORD_PROTOCOL",
    "MUTATION_DECISIVE_RECORD_PROTOCOL",
    "MUTATION_ERROR_TRANSCRIPT_PROTOCOL",
    "MUTATION_EVIDENCE_BLOCKERS",
    "MUTATION_EVIDENCE_PROTOCOL",
    "MUTATION_EXECUTION_CONTEXT_PROTOCOL",
    "MUTATION_INPUT_PREIMAGE_PROTOCOL",
    "MUTATION_POST_SOURCE_WITNESS_PROTOCOL",
    "MUTATION_PRE_SOURCE_WITNESS_PROTOCOL",
    "MUTATION_REPORT_TRANSCRIPT_PROTOCOL",
    "MUTATION_SOURCE_RECORD_PROTOCOL",
    "MutationEvidenceBuilder",
    "MutationEvidenceBundle",
    "MutationEvidenceRecord",
    "PRE_FREEZE_STATUS",
    "UPDATE_CONSISTENCY_LINEAGE_XOR_MASK",
    "portable_runner_contract",
]
