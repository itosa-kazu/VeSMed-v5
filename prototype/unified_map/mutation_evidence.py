"""Typed, content-addressed raw evidence for portable mutation executions.

This module is deliberately inert: it never runs a candidate, a compliance
probe, or a subprocess.  A producer supplies raw JSON-like preimages to
``MutationEvidenceBuilder`` during one execution.  The builder immediately
canonicalizes those preimages, stores them in a content-addressed blob table,
and emits a closed bundle whose mutation matrix is recomputed from the typed
observations.

Protocol version 1 is intentionally PRE-FREEZE.  Portable Python isolation and
external evidence custody are not complete, so every bundle carries fixed
``UCM-E002`` and ``UCM-E003`` blockers.  Those fields are code-owned and cannot
be cleared by a caller.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .mutation_matrix import (
    GATE_SPECS,
    REGISTRY_DIGEST,
    MutationObservation,
    ObservationOutcome,
    SubjectKind,
    evaluate_mutation_matrix,
)


MUTATION_EVIDENCE_PROTOCOL = "ucm-mutation-evidence-bundle/1"
MUTATION_EXECUTION_CONTEXT_PROTOCOL = "ucm-mutation-execution-context/1"
MUTATION_INPUT_PREIMAGE_PROTOCOL = "ucm-mutation-input-preimage/1"
MUTATION_PRE_SOURCE_WITNESS_PROTOCOL = "ucm-mutation-pre-source-witness/1"
MUTATION_POST_SOURCE_WITNESS_PROTOCOL = "ucm-mutation-post-source-witness/1"
MUTATION_SOURCE_RECORD_PROTOCOL = "ucm-mutation-source-record/1"
MUTATION_REPORT_TRANSCRIPT_PROTOCOL = "ucm-mutation-report-transcript/1"
MUTATION_ERROR_TRANSCRIPT_PROTOCOL = "ucm-mutation-error-transcript/1"
MUTATION_DECISION_RECORD_PROTOCOL = "ucm-mutation-decision-record/1"
MUTATION_DECISIVE_RECORD_PROTOCOL = "ucm-mutation-decisive-record/1"

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
)
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
)
_PORTABLE_SEMANTIC_PROBE_PROTOCOL = "ucm-portable-semantic-probes/4"
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
    if witness["protocol"] != "ucm-portable-control-source-binding/16":
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
    if decision.get("report_available") is not True:
        raise ProtocolViolation("decisive decision does not bind an available report")
    if decision.get("harness_stable_during_execution") is not True:
        raise ProtocolViolation("decisive decision does not bind a stable harness")
    if decision.get("execution_binding_complete") is not True:
        raise ProtocolViolation("decisive decision lacks complete execution binding")
    decisive = _payload_object(decisive_body, "decisive record")
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
        for field_name in ("history", "diagnosis_query", "rollout_query"):
            if type(input_preimage[field_name]) is not dict:
                raise ProtocolViolation(
                    f"input preimage {field_name} must be an exact object"
                )
        if input_preimage["delta"] is not None and type(
            input_preimage["delta"]
        ) is not dict:
            raise ProtocolViolation(
                "input preimage delta must be an exact object or null"
            )
        expected_paired_phases = (
            ("initialize", "update")
            if input_preimage["delta"] is not None
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
                        "source_record_digest": record.source_record_digest
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
                    },
                    label="decisive_record_digest",
                )
                expected_blob_digests.add(decisive_digest)
            _validate_record_semantics(
                record,
                expected_runner_protocol=self.runner_protocol,
                expected_base_seed=self.base_seed,
                expected_paired_phases=expected_paired_phases,
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
                references={"source_record_digest": source_digest},
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
