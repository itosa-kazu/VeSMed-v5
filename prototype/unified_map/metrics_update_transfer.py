"""Executable PRE-FREEZE runtime metrics for M15 and M16.

The functions in this module compute formula summaries for update consistency
and post-seal readout transfer.  They do not bind an expected-cell registry,
candidate custody, raw evidence roots, benchmark semantics, or freeze
authority.  Consequently every result is explicitly caller-asserted,
coverage-incomplete PRE-FREEZE evidence and cannot close M15/M16.

M15 keeps four measurements separate.  Exact incremental/replay identity and
batch/sequential behavioral identity emit hard mismatch facts.  Query-order
purity is also an exact hard check.  Oracle-relative score movement is
descriptive: informative evidence is *not* required to improve every case,
and no-information controls carry no improvement expectation.

M16 checks only the protocol shape asserted by a caller.  Digest strings,
booleans, worker names, and score rows are not custody evidence.  Formal novelty
eligibility and original-scope falsification therefore remain typed-unavailable
until raw bundles, transcripts, file-access traces, scope authority, and score
roots are independently bound.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    validate_json_like,
)
from .state import (
    HarnessStateRecord,
    SealedState,
    StatePayload,
    compute_state_hash,
)


BENCHMARK_STATUS = "PRE-FREEZE"
EVIDENCE_QUALIFICATION = "runtime_only"
AUTHORITY_CLAIM = "not_claimed"
FREEZE_AUTHORITY_STATUS = "not_claimed"
CROSS_METRIC_AGGREGATION = "forbidden"
METRIC_TARGET_CLOSURE = "not_implemented_unbound"

M15_RESULT_SCHEMA = "ucm-m15-update-consistency-result/1"
M16_RESULT_SCHEMA = "ucm-m16-sealed-state-novel-readout-result/1"

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class Task(str, Enum):
    DIAGNOSIS = "diagnosis"
    NATURAL_FORECAST = "natural_forecast"
    INTERVENTION_FORECAST = "intervention_forecast"
    RECURSIVE_UPDATE = "recursive_update"


class InformationKind(str, Enum):
    INFORMATIVE_OBSERVATION = "informative_observation"
    INFORMATIVE_TREATMENT_RESPONSE = "informative_treatment_response"
    NO_INFORMATION_CONTROL = "no_information_control"


class ScoreDirection(str, Enum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class ReadoutKind(str, Enum):
    DIAGNOSIS = "diagnosis"
    ROLLOUT = "rollout"


class NoveltyRelation(str, Enum):
    GENUINELY_NEW_SEMANTIC_READOUT = "genuinely_new_semantic_readout"
    EXISTING_OUTPUT = "existing_output"
    RENAME = "rename"
    DETERMINISTIC_PROJECTION = "deterministic_projection"


class OriginalYMembershipBasis(str, Enum):
    EXACT_ORIGINAL_Y_SEMANTIC_MEMBER = "exact_original_y_semantic_member"
    TARGET_SCOPE_EXTENSION_OUTSIDE_ORIGINAL_Y = (
        "target_scope_extension_outside_original_y"
    )


class ReadoutInput(str, Enum):
    SEALED_STATE = "sealed_state"
    NEW_LABEL = "new_label"
    RAW_HISTORY = "raw_history"
    EXISTING_OUTPUT = "existing_output"
    TASK_SPECIFIC_LATENT = "task_specific_latent"


class SampleEfficiencyStatus(str, Enum):
    DEFINED = "defined"
    UNDEFINED_TARGET_NOT_REACHED = "undefined_target_not_reached"


class OriginalScopeDisposition(str, Enum):
    INCONCLUSIVE_UNBOUND_EVIDENCE = "inconclusive_unbound_evidence"


M15_MISSING_AUTHORITIES = (
    "expected_cell_registry_binding",
    "benchmark_scope_authority",
    "candidate_identity_and_seal_authority",
    "raw_update_evidence_root",
    "raw_query_trace_root",
    "raw_score_evidence_root",
    "common_coverage_authority",
)

M16_MISSING_AUTHORITIES = (
    "candidate_seal_custody_authority",
    "source_scope_authority",
    "target_scope_authority",
    "raw_readout_bundle_root",
    "worker_transcript_root",
    "file_access_trace_root",
    "original_y_membership_authority",
    "raw_score_evidence_root",
)


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    if any(ord(character) < 0x20 for character in value):
        raise ProtocolViolation(f"{label} contains a control character")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a lowercase SHA-256 digest")
    return value


def _bytes(value: object, label: str) -> bytes:
    if type(value) is not bytes:
        raise ProtocolViolation(f"{label} must be exact bytes")
    return value


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ProtocolViolation(f"{label} must be an exact boolean")
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ProtocolViolation(f"{label} must be an exact positive integer")
    return value


def _number(value: object, label: str) -> float:
    if type(value) not in {int, float}:
        raise ProtocolViolation(f"{label} must be an exact finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ProtocolViolation(f"{label} must be an exact finite number") from exc
    if not math.isfinite(result):
        raise ProtocolViolation(f"{label} must be an exact finite number")
    return result


def _derived(value: float, label: str) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise ProtocolViolation(f"{label} derived arithmetic is non-finite")
    return value


def _derived_sum(values: tuple[float, ...], label: str) -> float:
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError) as exc:
        raise ProtocolViolation(f"{label} derived arithmetic overflow") from exc
    return _derived(result, label)


def _enum(value: object, enum_type: type[Enum], label: str) -> Any:
    if type(value) is not enum_type:
        raise ProtocolViolation(f"{label} must be typed {enum_type.__name__}")
    return value


def _json_object(value: object, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact JSON object")
    validate_json_like(value, path=label)
    # ``validate_json_like`` establishes the structural contract, but a Python
    # integer can still exceed the runtime JSON encoder's conversion limit.
    # Exercise the same canonicalization used by the result at this boundary
    # so hostile magnitudes cannot leak native encoder exceptions later.
    try:
        canonical_json_bytes(value)
    except (OverflowError, RecursionError, ValueError) as exc:
        raise ProtocolViolation(
            f"{label} is not representable as canonical JSON"
        ) from exc
    return value


def _exact_typed_tuple(
    value: object,
    item_type: type,
    label: str,
    *,
    allow_empty: bool = False,
) -> tuple[Any, ...]:
    if type(value) is not tuple or (not allow_empty and not value):
        qualifier = "possibly-empty" if allow_empty else "non-empty"
        raise ProtocolViolation(f"{label} must be a {qualifier} tuple")
    if any(type(item) is not item_type for item in value):
        raise ProtocolViolation(f"{label} must contain typed {item_type.__name__}")
    return value


def _metric_envelope(schema_version: str) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "benchmark_status": BENCHMARK_STATUS,
        "evidence_qualification": EVIDENCE_QUALIFICATION,
        "authority_claim": AUTHORITY_CLAIM,
        "freeze_authority_status": FREEZE_AUTHORITY_STATUS,
        "cross_metric_aggregate_score": CROSS_METRIC_AGGREGATION,
        "metric_target_closure": METRIC_TARGET_CLOSURE,
    }


@dataclass(frozen=True, slots=True)
class EvaluationGrain:
    """The exact M15 row grain; no dimension may be silently collapsed."""

    world_id: str
    case_id: str
    cut_id: str
    task: Task
    replicate_id: str
    horizon_id: str
    policy_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "world_id",
            "case_id",
            "cut_id",
            "replicate_id",
            "horizon_id",
            "policy_id",
        ):
            _name(getattr(self, field_name), f"grain.{field_name}")
        _enum(self.task, Task, "grain.task")

    @property
    def key(self) -> tuple[str, ...]:
        return (
            self.world_id,
            self.case_id,
            self.cut_id,
            self.task.value,
            self.replicate_id,
            self.horizon_id,
            self.policy_id,
        )

    def to_wire(self) -> dict[str, str]:
        return {
            "world_id": self.world_id,
            "case_id": self.case_id,
            "cut_id": self.cut_id,
            "task": self.task.value,
            "replicate_id": self.replicate_id,
            "horizon_id": self.horizon_id,
            "policy_id": self.policy_id,
        }


@dataclass(frozen=True, slots=True)
class RuntimeStateIdentity:
    """One runtime state record plus the complete state-hash preimage.

    ``HarnessStateRecord.state_hash`` is a domain-separated digest over the
    candidate/model/scope/catalog bindings, payload metadata, cut, and payload
    bytes.  It is intentionally *not* ``sha256(payload_bytes)``.  M15 retains
    the payload digest separately so callers cannot conflate the two identities.

    This validates caller-provided runtime identity syntax and internal
    consistency only.  It does not establish custody or benchmark coverage.
    """

    record: HarnessStateRecord
    payload: StatePayload

    def __post_init__(self) -> None:
        if type(self.record) is not HarnessStateRecord:
            raise ProtocolViolation(
                "runtime_state.record must be typed HarnessStateRecord"
            )
        if type(self.payload) is not StatePayload:
            raise ProtocolViolation("runtime_state.payload must be typed StatePayload")
        if self.record.payload_size_bytes != len(self.payload.payload):
            raise ProtocolViolation(
                "runtime_state.record.payload_size_bytes does not match payload bytes"
            )
        expected_hash = compute_state_hash(
            self.payload,
            candidate_bundle_digest=self.record.candidate_bundle_digest,
            model_digest=self.record.model_digest,
            scope_digest=self.record.scope_digest,
            catalog_digest=self.record.catalog_digest,
            as_of_available_at=self.record.as_of_available_at,
        )
        if self.record.state_hash != expected_hash:
            raise ProtocolViolation(
                "runtime_state.record.state_hash does not match the complete "
                "compute_state_hash preimage"
            )

    @classmethod
    def from_sealed_state(cls, state: SealedState) -> "RuntimeStateIdentity":
        if type(state) is not SealedState:
            raise ProtocolViolation("runtime state must be typed SealedState")
        return cls(record=state.record, payload=state.candidate_input.payload)

    @property
    def state_hash(self) -> str:
        return self.record.state_hash

    @property
    def payload_bytes(self) -> bytes:
        return self.payload.payload

    @property
    def payload_bytes_digest(self) -> str:
        return digest_bytes(self.payload_bytes)

    def hash_preimage_wire(self) -> dict[str, Any]:
        """Return the non-secret metadata portion of ``compute_state_hash``."""

        return {
            "candidate_bundle_digest": self.record.candidate_bundle_digest,
            "model_digest": self.record.model_digest,
            "scope_digest": self.record.scope_digest,
            "catalog_digest": self.record.catalog_digest,
            "codec": self.payload.codec,
            "schema_version": self.payload.schema_version,
            "state_class": self.payload.state_class.value,
            "as_of_available_at": self.record.as_of_available_at,
        }


@dataclass(frozen=True, slots=True)
class UpdateIdentityObservation:
    grain: EvaluationGrain
    information_kind: InformationKind
    incremental_state: RuntimeStateIdentity
    replay_state: RuntimeStateIdentity
    batch_behavior: dict[str, Any]
    sequential_behavior: dict[str, Any]

    def __post_init__(self) -> None:
        if type(self.grain) is not EvaluationGrain:
            raise ProtocolViolation("update.grain must be typed EvaluationGrain")
        _enum(self.information_kind, InformationKind, "update.information_kind")
        if type(self.incremental_state) is not RuntimeStateIdentity:
            raise ProtocolViolation(
                "update.incremental_state must be typed RuntimeStateIdentity"
            )
        if type(self.replay_state) is not RuntimeStateIdentity:
            raise ProtocolViolation(
                "update.replay_state must be typed RuntimeStateIdentity"
            )
        _json_object(self.batch_behavior, "update.batch_behavior")
        _json_object(self.sequential_behavior, "update.sequential_behavior")


@dataclass(frozen=True, slots=True)
class QueryOrderObservation:
    grain: EvaluationGrain
    first_order: tuple[str, ...]
    second_order: tuple[str, ...]
    first_pre_state: RuntimeStateIdentity
    first_post_state: RuntimeStateIdentity
    second_pre_state: RuntimeStateIdentity
    second_post_state: RuntimeStateIdentity
    first_outputs_by_query: dict[str, Any]
    second_outputs_by_query: dict[str, Any]

    def __post_init__(self) -> None:
        if type(self.grain) is not EvaluationGrain:
            raise ProtocolViolation("query.grain must be typed EvaluationGrain")
        for label, order in (
            ("query.first_order", self.first_order),
            ("query.second_order", self.second_order),
        ):
            _exact_typed_tuple(order, str, label)
            for index, query_id in enumerate(order):
                _name(query_id, f"{label}[{index}]")
            if len(set(order)) != len(order):
                raise ProtocolViolation(f"{label} contains duplicate query ids")
        if set(self.first_order) != set(self.second_order):
            raise ProtocolViolation("query orders must contain the same query-id set")
        if self.first_order == self.second_order:
            raise ProtocolViolation("query orders must be distinct permutations")
        for field_name in (
            "first_pre",
            "first_post",
            "second_pre",
            "second_post",
        ):
            if type(getattr(self, f"{field_name}_state")) is not RuntimeStateIdentity:
                raise ProtocolViolation(
                    f"query.{field_name}_state must be typed RuntimeStateIdentity"
                )
        first = _json_object(
            self.first_outputs_by_query, "query.first_outputs_by_query"
        )
        second = _json_object(
            self.second_outputs_by_query, "query.second_outputs_by_query"
        )
        if set(first) != set(self.first_order) or set(second) != set(self.first_order):
            raise ProtocolViolation(
                "query output keys must exactly equal the query-id set"
            )


@dataclass(frozen=True, slots=True)
class OracleScoreChangeObservation:
    grain: EvaluationGrain
    information_kind: InformationKind
    readout_kind: ReadoutKind
    score_direction: ScoreDirection
    candidate_before: int | float
    candidate_after: int | float
    oracle_before: int | float
    oracle_after: int | float

    def __post_init__(self) -> None:
        if type(self.grain) is not EvaluationGrain:
            raise ProtocolViolation("score_change.grain must be typed EvaluationGrain")
        _enum(self.information_kind, InformationKind, "score_change.information_kind")
        _enum(self.readout_kind, ReadoutKind, "score_change.readout_kind")
        _enum(self.score_direction, ScoreDirection, "score_change.score_direction")
        for field_name in (
            "candidate_before",
            "candidate_after",
            "oracle_before",
            "oracle_after",
        ):
            _number(getattr(self, field_name), f"score_change.{field_name}")


def _rate(numerator: int, denominator: int, label: str) -> float:
    if denominator <= 0:
        raise ProtocolViolation(f"{label} denominator must be positive")
    return _derived(float(numerator) / float(denominator), label)


@dataclass(frozen=True, slots=True)
class UpdateConsistencyResult:
    incremental_replay: dict[str, Any]
    batch_sequential: dict[str, Any]
    query_order_purity: dict[str, Any]
    oracle_directional_changes: tuple[dict[str, Any], ...]
    coverage_diagnostics: dict[str, Any]

    def to_wire(self) -> dict[str, Any]:
        wire = _metric_envelope(M15_RESULT_SCHEMA)
        wire.update(
            {
                "cross_submetric_aggregate_score": "forbidden",
                "input_evidence": "caller_asserted_unbound",
                "expected_registry_binding": "absent",
                "coverage_complete": False,
                "hard_gate_evidence_eligible": False,
                "missing_authorities": list(M15_MISSING_AUTHORITIES),
                "coverage_diagnostics": self.coverage_diagnostics,
                "incremental_replay_exact_identity": self.incremental_replay,
                "batch_sequential_behavioral_identity": self.batch_sequential,
                "query_order_purity": self.query_order_purity,
                "oracle_relative_directional_changes": list(
                    self.oracle_directional_changes
                ),
                "directional_interpretation": (
                    "descriptive_by_information_kind; informative rows are not "
                    "required to improve individually; no-information controls "
                    "carry no improvement requirement"
                ),
                "directional_formula_qualification": "provided_exposure_only",
            }
        )
        validate_json_like(wire)
        return wire

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


def _grain_wire_with(observation: Any, **extra: Any) -> dict[str, Any]:
    row: dict[str, Any] = observation.grain.to_wire()
    row.update(extra)
    return row


def update_consistency(
    updates: tuple[UpdateIdentityObservation, ...],
    queries: tuple[QueryOrderObservation, ...],
    score_changes: tuple[OracleScoreChangeObservation, ...],
) -> UpdateConsistencyResult:
    """Compute unbound M15 formula summaries without claiming coverage closure."""

    _exact_typed_tuple(updates, UpdateIdentityObservation, "updates")
    _exact_typed_tuple(queries, QueryOrderObservation, "queries")
    _exact_typed_tuple(score_changes, OracleScoreChangeObservation, "score_changes")

    update_keys = [row.grain.key for row in updates]
    query_keys = [row.grain.key for row in queries]
    score_keys = [
        row.grain.key + (row.information_kind.value, row.readout_kind.value)
        for row in score_changes
    ]
    if len(set(update_keys)) != len(update_keys):
        raise ProtocolViolation("updates contain a duplicate exact evaluation grain")
    if len(set(query_keys)) != len(query_keys):
        raise ProtocolViolation("queries contain a duplicate exact evaluation grain")
    if len(set(score_keys)) != len(score_keys):
        raise ProtocolViolation(
            "score_changes contain a duplicate exact evaluation grain"
        )

    update_grains = {row.grain.key: row.grain.to_wire() for row in updates}
    query_grains = {row.grain.key: row.grain.to_wire() for row in queries}
    score_grains = {row.grain.key: row.grain.to_wire() for row in score_changes}
    update_key_set = set(update_grains)
    query_key_set = set(query_grains)
    score_key_set = set(score_grains)
    common_key_set = update_key_set & query_key_set & score_key_set
    provided_grain_sets_aligned = update_key_set == query_key_set == score_key_set

    def grain_rows(
        mapping: dict[tuple[str, ...], dict[str, str]],
    ) -> list[dict[str, str]]:
        return [mapping[key] for key in sorted(mapping)]

    coverage_diagnostics = {
        "coverage_basis": "provided_exposure_only",
        "expected_registry_binding": "absent",
        "coverage_complete": False,
        "provided_grain_sets_aligned": provided_grain_sets_aligned,
        "coverage_mismatch": not provided_grain_sets_aligned,
        "common_grain_count": len(common_key_set),
        "updates": {
            "provided_grain_count": len(update_grains),
            "grains": grain_rows(update_grains),
        },
        "queries": {
            "provided_grain_count": len(query_grains),
            "grains": grain_rows(query_grains),
        },
        "score_changes": {
            "provided_grain_count": len(score_grains),
            "grains": grain_rows(score_grains),
        },
    }

    sorted_updates = sorted(updates, key=lambda row: row.grain.key)
    state_match_rows: list[dict[str, Any]] = []
    state_mismatches: list[dict[str, Any]] = []
    batch_rows: list[dict[str, Any]] = []
    batch_mismatches: list[dict[str, Any]] = []
    for row in sorted_updates:
        hash_match = row.incremental_state.state_hash == row.replay_state.state_hash
        payload_bytes_match = (
            row.incremental_state.payload_bytes == row.replay_state.payload_bytes
        )
        exact_match = hash_match and payload_bytes_match
        base = _grain_wire_with(
            row,
            information_kind=row.information_kind.value,
        )
        state_row = {
            **base,
            "incremental_state_hash": row.incremental_state.state_hash,
            "replay_state_hash": row.replay_state.state_hash,
            "incremental_payload_bytes_digest": (
                row.incremental_state.payload_bytes_digest
            ),
            "replay_payload_bytes_digest": row.replay_state.payload_bytes_digest,
            "incremental_state_hash_preimage": (
                row.incremental_state.hash_preimage_wire()
            ),
            "replay_state_hash_preimage": row.replay_state.hash_preimage_wire(),
            "hash_match": hash_match,
            "payload_bytes_match": payload_bytes_match,
            "exact_match": exact_match,
        }
        state_match_rows.append(state_row)
        if not exact_match:
            state_mismatches.append(
                {
                    **base,
                    "hard_fact": "incremental_replay_state_mismatch",
                    "incremental_state_hash": row.incremental_state.state_hash,
                    "replay_state_hash": row.replay_state.state_hash,
                    "incremental_payload_bytes_digest": (
                        row.incremental_state.payload_bytes_digest
                    ),
                    "replay_payload_bytes_digest": (
                        row.replay_state.payload_bytes_digest
                    ),
                    "incremental_state_hash_preimage": (
                        row.incremental_state.hash_preimage_wire()
                    ),
                    "replay_state_hash_preimage": (
                        row.replay_state.hash_preimage_wire()
                    ),
                    "hash_match": hash_match,
                    "payload_bytes_match": payload_bytes_match,
                }
            )

        batch_match = canonical_json_bytes(row.batch_behavior) == canonical_json_bytes(
            row.sequential_behavior
        )
        batch_row = {
            **base,
            "batch_behavior_digest": digest_bytes(
                canonical_json_bytes(row.batch_behavior)
            ),
            "sequential_behavior_digest": digest_bytes(
                canonical_json_bytes(row.sequential_behavior)
            ),
            "behavioral_match": batch_match,
        }
        batch_rows.append(batch_row)
        if not batch_match:
            batch_mismatches.append(
                {
                    **base,
                    "hard_fact": "batch_sequential_behavior_mismatch",
                    "batch_behavior_digest": digest_bytes(
                        canonical_json_bytes(row.batch_behavior)
                    ),
                    "sequential_behavior_digest": digest_bytes(
                        canonical_json_bytes(row.sequential_behavior)
                    ),
                }
            )

    sorted_queries = sorted(queries, key=lambda row: row.grain.key)
    query_rows: list[dict[str, Any]] = []
    query_mismatches: list[dict[str, Any]] = []
    for row in sorted_queries:
        same_start_hash = (
            row.first_pre_state.state_hash == row.second_pre_state.state_hash
        )
        same_start_payload_bytes = (
            row.first_pre_state.payload_bytes == row.second_pre_state.payload_bytes
        )
        first_hash_pure = (
            row.first_pre_state.state_hash == row.first_post_state.state_hash
        )
        first_payload_bytes_pure = (
            row.first_pre_state.payload_bytes == row.first_post_state.payload_bytes
        )
        second_hash_pure = (
            row.second_pre_state.state_hash == row.second_post_state.state_hash
        )
        second_payload_bytes_pure = (
            row.second_pre_state.payload_bytes == row.second_post_state.payload_bytes
        )
        outputs_match = canonical_json_bytes(
            row.first_outputs_by_query
        ) == canonical_json_bytes(row.second_outputs_by_query)
        pure = (
            same_start_hash
            and same_start_payload_bytes
            and first_hash_pure
            and first_payload_bytes_pure
            and second_hash_pure
            and second_payload_bytes_pure
            and outputs_match
        )
        base = _grain_wire_with(row)
        query_rows.append(
            {
                **base,
                "first_order": list(row.first_order),
                "second_order": list(row.second_order),
                "first_pre_state_hash": row.first_pre_state.state_hash,
                "first_post_state_hash": row.first_post_state.state_hash,
                "second_pre_state_hash": row.second_pre_state.state_hash,
                "second_post_state_hash": row.second_post_state.state_hash,
                "first_pre_payload_bytes_digest": (
                    row.first_pre_state.payload_bytes_digest
                ),
                "first_post_payload_bytes_digest": (
                    row.first_post_state.payload_bytes_digest
                ),
                "second_pre_payload_bytes_digest": (
                    row.second_pre_state.payload_bytes_digest
                ),
                "second_post_payload_bytes_digest": (
                    row.second_post_state.payload_bytes_digest
                ),
                "first_pre_state_hash_preimage": (
                    row.first_pre_state.hash_preimage_wire()
                ),
                "first_post_state_hash_preimage": (
                    row.first_post_state.hash_preimage_wire()
                ),
                "second_pre_state_hash_preimage": (
                    row.second_pre_state.hash_preimage_wire()
                ),
                "second_post_state_hash_preimage": (
                    row.second_post_state.hash_preimage_wire()
                ),
                "first_outputs_digest": digest_bytes(
                    canonical_json_bytes(row.first_outputs_by_query)
                ),
                "second_outputs_digest": digest_bytes(
                    canonical_json_bytes(row.second_outputs_by_query)
                ),
                "same_start_hash": same_start_hash,
                "same_start_payload_bytes": same_start_payload_bytes,
                "first_order_hash_unchanged": first_hash_pure,
                "first_order_payload_bytes_unchanged": first_payload_bytes_pure,
                "second_order_hash_unchanged": second_hash_pure,
                "second_order_payload_bytes_unchanged": second_payload_bytes_pure,
                "outputs_by_query_match": outputs_match,
                "pure": pure,
            }
        )
        if not pure:
            query_mismatches.append(
                {
                    **base,
                    "hard_fact": "query_order_impurity",
                    "first_order": list(row.first_order),
                    "second_order": list(row.second_order),
                    "first_pre_state_hash": row.first_pre_state.state_hash,
                    "first_post_state_hash": row.first_post_state.state_hash,
                    "second_pre_state_hash": row.second_pre_state.state_hash,
                    "second_post_state_hash": row.second_post_state.state_hash,
                    "first_pre_payload_bytes_digest": (
                        row.first_pre_state.payload_bytes_digest
                    ),
                    "first_post_payload_bytes_digest": (
                        row.first_post_state.payload_bytes_digest
                    ),
                    "second_pre_payload_bytes_digest": (
                        row.second_pre_state.payload_bytes_digest
                    ),
                    "second_post_payload_bytes_digest": (
                        row.second_post_state.payload_bytes_digest
                    ),
                    "first_pre_state_hash_preimage": (
                        row.first_pre_state.hash_preimage_wire()
                    ),
                    "first_post_state_hash_preimage": (
                        row.first_post_state.hash_preimage_wire()
                    ),
                    "second_pre_state_hash_preimage": (
                        row.second_pre_state.hash_preimage_wire()
                    ),
                    "second_post_state_hash_preimage": (
                        row.second_post_state.hash_preimage_wire()
                    ),
                    "first_outputs_digest": digest_bytes(
                        canonical_json_bytes(row.first_outputs_by_query)
                    ),
                    "second_outputs_digest": digest_bytes(
                        canonical_json_bytes(row.second_outputs_by_query)
                    ),
                    "same_start_hash": same_start_hash,
                    "same_start_payload_bytes": same_start_payload_bytes,
                    "first_order_hash_unchanged": first_hash_pure,
                    "first_order_payload_bytes_unchanged": (first_payload_bytes_pure),
                    "second_order_hash_unchanged": second_hash_pure,
                    "second_order_payload_bytes_unchanged": (second_payload_bytes_pure),
                    "outputs_by_query_match": outputs_match,
                }
            )

    directional_rows: list[dict[str, Any]] = []
    for row in sorted(
        score_changes,
        key=lambda item: (
            item.information_kind.value,
            item.readout_kind.value,
            item.grain.key,
        ),
    ):
        before_gap = _derived(
            abs(float(row.candidate_before) - float(row.oracle_before)),
            "oracle-relative before gap",
        )
        after_gap = _derived(
            abs(float(row.candidate_after) - float(row.oracle_after)),
            "oracle-relative after gap",
        )
        improvement = _derived(
            before_gap - after_gap, "oracle-relative gap improvement"
        )
        if improvement > 0.0:
            movement = "toward_oracle"
        elif improvement < 0.0:
            movement = "away_from_oracle"
        else:
            movement = "unchanged"
        directional_rows.append(
            _grain_wire_with(
                row,
                information_kind=row.information_kind.value,
                readout_kind=row.readout_kind.value,
                score_direction=row.score_direction.value,
                candidate_before=float(row.candidate_before),
                candidate_after=float(row.candidate_after),
                oracle_before=float(row.oracle_before),
                oracle_after=float(row.oracle_after),
                oracle_relative_gap_before=before_gap,
                oracle_relative_gap_after=after_gap,
                oracle_relative_gap_improvement=improvement,
                movement=movement,
                individual_improvement_gate=(
                    "none"
                    if row.information_kind is InformationKind.NO_INFORMATION_CONTROL
                    else "not_applied"
                ),
            )
        )

    directional_groups: list[dict[str, Any]] = []
    group_keys = sorted(
        {
            (row["information_kind"], row["readout_kind"], row["task"])
            for row in directional_rows
        }
    )
    for information_kind, readout_kind, task in group_keys:
        members = [
            row
            for row in directional_rows
            if (
                row["information_kind"],
                row["readout_kind"],
                row["task"],
            )
            == (information_kind, readout_kind, task)
        ]
        improvements = tuple(
            float(member["oracle_relative_gap_improvement"]) for member in members
        )
        total = _derived_sum(improvements, "directional group improvement sum")
        mean = _derived(total / float(len(members)), "directional group mean")
        directional_groups.append(
            {
                "information_kind": information_kind,
                "readout_kind": readout_kind,
                "task": task,
                "exact_denominator_rows": len(members),
                "toward_oracle_count": sum(
                    member["movement"] == "toward_oracle" for member in members
                ),
                "away_from_oracle_count": sum(
                    member["movement"] == "away_from_oracle" for member in members
                ),
                "unchanged_count": sum(
                    member["movement"] == "unchanged" for member in members
                ),
                "sum_oracle_relative_gap_improvement": total,
                "mean_oracle_relative_gap_improvement": mean,
                "aggregate_movement": (
                    "toward_oracle"
                    if mean > 0.0
                    else "away_from_oracle"
                    if mean < 0.0
                    else "unchanged"
                ),
                "improvement_requirement": (
                    "none"
                    if information_kind == InformationKind.NO_INFORMATION_CONTROL.value
                    else "report_aggregate_direction_without_per_row_gate"
                ),
                "rows": members,
            }
        )

    incremental_matches = sum(row["exact_match"] for row in state_match_rows)
    batch_matches = sum(row["behavioral_match"] for row in batch_rows)
    pure_queries = sum(row["pure"] for row in query_rows)
    return UpdateConsistencyResult(
        incremental_replay={
            "rate_qualification": "provided_exposure_only",
            "hard_gate_evidence_eligible": False,
            "exact_match_numerator": incremental_matches,
            "exact_denominator_rows": len(state_match_rows),
            "exact_match_rate": _rate(
                incremental_matches, len(state_match_rows), "incremental replay rate"
            ),
            "rows": state_match_rows,
            "provided_exposure_mismatch_facts": state_mismatches,
        },
        batch_sequential={
            "rate_qualification": "provided_exposure_only",
            "hard_gate_evidence_eligible": False,
            "behavioral_match_numerator": batch_matches,
            "exact_denominator_rows": len(batch_rows),
            "behavioral_match_rate": _rate(
                batch_matches, len(batch_rows), "batch sequential rate"
            ),
            "rows": batch_rows,
            "provided_exposure_mismatch_facts": batch_mismatches,
        },
        query_order_purity={
            "rate_qualification": "provided_exposure_only",
            "hard_gate_evidence_eligible": False,
            "pure_numerator": pure_queries,
            "exact_denominator_rows": len(query_rows),
            "purity_rate": _rate(
                pure_queries, len(query_rows), "query-order purity rate"
            ),
            "rows": query_rows,
            "provided_exposure_mismatch_facts": query_mismatches,
        },
        oracle_directional_changes=tuple(directional_groups),
        coverage_diagnostics=coverage_diagnostics,
    )


@dataclass(frozen=True, slots=True)
class NovelReadoutCard:
    readout_id: str
    candidate_seal_digest: str
    source_scope_digest: str
    target_scope_digest: str
    candidate_build_worker_id: str
    readout_worker_id: str
    history_baseline_worker_id: str
    candidate_sealed_before_target_reveal: bool
    candidate_base_digest_before: str
    candidate_base_digest_after: str
    readout_inputs: tuple[ReadoutInput, ...]
    history_baseline_inputs: tuple[ReadoutInput, ...]
    novelty_relation: NoveltyRelation
    novelty_basis_digest: str
    in_original_y: bool
    original_y_membership_basis: OriginalYMembershipBasis
    original_y_membership_evidence_digest: str
    score_direction: ScoreDirection
    sample_efficiency_target_score: int | float

    def __post_init__(self) -> None:
        for field_name in (
            "readout_id",
            "candidate_build_worker_id",
            "readout_worker_id",
            "history_baseline_worker_id",
        ):
            _name(getattr(self, field_name), f"readout_card.{field_name}")
        for field_name in (
            "candidate_seal_digest",
            "source_scope_digest",
            "target_scope_digest",
            "candidate_base_digest_before",
            "candidate_base_digest_after",
            "novelty_basis_digest",
            "original_y_membership_evidence_digest",
        ):
            _digest(getattr(self, field_name), f"readout_card.{field_name}")
        _bool(
            self.candidate_sealed_before_target_reveal,
            "readout_card.candidate_sealed_before_target_reveal",
        )
        _bool(self.in_original_y, "readout_card.in_original_y")
        _exact_typed_tuple(self.readout_inputs, ReadoutInput, "readout_card.inputs")
        if len(set(self.readout_inputs)) != len(self.readout_inputs):
            raise ProtocolViolation("readout_card.inputs contains duplicates")
        _exact_typed_tuple(
            self.history_baseline_inputs,
            ReadoutInput,
            "readout_card.history_baseline_inputs",
        )
        if len(set(self.history_baseline_inputs)) != len(self.history_baseline_inputs):
            raise ProtocolViolation(
                "readout_card.history_baseline_inputs contains duplicates"
            )
        _enum(self.novelty_relation, NoveltyRelation, "readout_card.novelty_relation")
        if (
            self.novelty_relation is NoveltyRelation.GENUINELY_NEW_SEMANTIC_READOUT
            and self.source_scope_digest == self.target_scope_digest
        ):
            raise ProtocolViolation(
                "a genuinely new semantic readout requires distinct source and "
                "target scope digests"
            )
        _enum(
            self.original_y_membership_basis,
            OriginalYMembershipBasis,
            "readout_card.original_y_membership_basis",
        )
        expected_membership = (
            self.original_y_membership_basis
            is OriginalYMembershipBasis.EXACT_ORIGINAL_Y_SEMANTIC_MEMBER
        )
        if self.in_original_y is not expected_membership:
            raise ProtocolViolation(
                "in_original_y contradicts original_y_membership_basis"
            )
        _enum(self.score_direction, ScoreDirection, "readout_card.score_direction")
        _number(
            self.sample_efficiency_target_score,
            "readout_card.sample_efficiency_target_score",
        )


@dataclass(frozen=True, slots=True)
class NovelReadoutScorePoint:
    train_examples: int
    state_only_score: int | float
    history_baseline_score: int | float

    def __post_init__(self) -> None:
        _positive_int(self.train_examples, "readout_point.train_examples")
        _number(self.state_only_score, "readout_point.state_only_score")
        _number(self.history_baseline_score, "readout_point.history_baseline_score")


@dataclass(frozen=True, slots=True)
class NovelReadoutEvaluation:
    card: NovelReadoutCard
    points: tuple[NovelReadoutScorePoint, ...]

    def __post_init__(self) -> None:
        if type(self.card) is not NovelReadoutCard:
            raise ProtocolViolation(
                "readout_evaluation.card must be typed NovelReadoutCard"
            )
        _exact_typed_tuple(
            self.points, NovelReadoutScorePoint, "readout_evaluation.points"
        )
        counts = [point.train_examples for point in self.points]
        if counts != sorted(counts) or len(set(counts)) != len(counts):
            raise ProtocolViolation(
                "readout_evaluation train_examples must be unique and strictly increasing"
            )


def _reaches_target(score: float, target: float, direction: ScoreDirection) -> bool:
    if direction is ScoreDirection.MINIMIZE:
        return score <= target
    return score >= target


def _sample_efficiency_wire(
    points: tuple[NovelReadoutScorePoint, ...],
    *,
    representation: str,
    target: float,
    direction: ScoreDirection,
) -> dict[str, Any]:
    score_field = (
        "state_only_score"
        if representation == "state_only"
        else "history_baseline_score"
    )
    reached = [
        point.train_examples
        for point in points
        if _reaches_target(float(getattr(point, score_field)), target, direction)
    ]
    if reached:
        status = SampleEfficiencyStatus.DEFINED
        examples: int | None = min(reached)
    else:
        status = SampleEfficiencyStatus.UNDEFINED_TARGET_NOT_REACHED
        examples = None
    return {
        "status": status.value,
        "train_examples_to_target": examples,
        "target_score": target,
        "score_direction": direction.value,
        "exact_denominator_curve_points": len(points),
    }


@dataclass(frozen=True, slots=True)
class NovelReadoutTransferResult:
    readouts: tuple[dict[str, Any], ...]

    def to_wire(self) -> dict[str, Any]:
        wire = _metric_envelope(M16_RESULT_SCHEMA)
        wire.update(
            {
                "cross_readout_aggregate_score": "forbidden",
                "input_evidence": "caller_asserted_unbound",
                "evidence_status": "unverified_caller_assertions",
                "expected_registry_binding": "absent",
                "coverage_complete": False,
                "freeze_gate_eligible": False,
                "missing_authorities": list(M16_MISSING_AUTHORITIES),
                "readouts": list(self.readouts),
                "formal_novel_readout_exact_denominator": {
                    "status": "unavailable_unbound_evidence",
                    "value": None,
                },
                "provided_protocol_shape_candidate_count": sum(
                    bool(row["protocol_shape_candidate"]) for row in self.readouts
                ),
                "reported_card_count": len(self.readouts),
            }
        )
        validate_json_like(wire)
        return wire

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


def sealed_state_novel_readout_transfer(
    evaluations: tuple[NovelReadoutEvaluation, ...],
) -> NovelReadoutTransferResult:
    """Compute unbound M16 shape/formula summaries without formal eligibility."""

    _exact_typed_tuple(evaluations, NovelReadoutEvaluation, "evaluations")
    readout_ids = [evaluation.card.readout_id for evaluation in evaluations]
    if len(set(readout_ids)) != len(readout_ids):
        raise ProtocolViolation("evaluations contain duplicate readout_id")

    rows: list[dict[str, Any]] = []
    required_inputs = {ReadoutInput.SEALED_STATE, ReadoutInput.NEW_LABEL}
    required_history_inputs = {ReadoutInput.RAW_HISTORY, ReadoutInput.NEW_LABEL}
    for evaluation in sorted(evaluations, key=lambda item: item.card.readout_id):
        card = evaluation.card
        target = float(card.sample_efficiency_target_score)
        base_frozen = (
            card.candidate_base_digest_before == card.candidate_base_digest_after
        )
        independent_worker = card.readout_worker_id != card.candidate_build_worker_id
        history_worker_independent = card.history_baseline_worker_id not in {
            card.candidate_build_worker_id,
            card.readout_worker_id,
        }
        inputs_compliant = set(card.readout_inputs) == required_inputs
        history_inputs_compliant = (
            set(card.history_baseline_inputs) == required_history_inputs
        )
        genuinely_novel = (
            card.novelty_relation is NoveltyRelation.GENUINELY_NEW_SEMANTIC_READOUT
        )

        hard_violations: list[str] = []
        if not card.candidate_sealed_before_target_reveal:
            hard_violations.append("candidate_not_sealed_before_target_reveal")
        if not base_frozen:
            hard_violations.append("candidate_base_changed_after_seal")
        if not independent_worker:
            hard_violations.append("readout_worker_not_independent")
        if not history_worker_independent:
            hard_violations.append("history_baseline_worker_not_independent")
        if not inputs_compliant:
            if ReadoutInput.RAW_HISTORY in card.readout_inputs:
                hard_violations.append("history_reread_violation")
            if ReadoutInput.EXISTING_OUTPUT in card.readout_inputs:
                hard_violations.append("existing_output_input_violation")
            if ReadoutInput.TASK_SPECIFIC_LATENT in card.readout_inputs:
                hard_violations.append("task_specific_latent_input_violation")
            missing = sorted(
                item.value for item in required_inputs - set(card.readout_inputs)
            )
            extra = sorted(
                item.value for item in set(card.readout_inputs) - required_inputs
            )
            if missing:
                hard_violations.append(
                    "required_readout_input_missing:" + ",".join(missing)
                )
            if extra and not any(
                violation.endswith("_violation") for violation in hard_violations
            ):
                hard_violations.append("forbidden_readout_input:" + ",".join(extra))
        if not history_inputs_compliant:
            hard_violations.append("history_baseline_input_contract_violation")
        if not genuinely_novel:
            hard_violations.append("not_novel:" + card.novelty_relation.value)

        protocol_shape_candidate = not hard_violations
        state_efficiency = _sample_efficiency_wire(
            evaluation.points,
            representation="state_only",
            target=target,
            direction=card.score_direction,
        )
        history_efficiency = _sample_efficiency_wire(
            evaluation.points,
            representation="history",
            target=target,
            direction=card.score_direction,
        )
        final_point = evaluation.points[-1]
        state_score = float(final_point.state_only_score)
        history_score = float(final_point.history_baseline_score)
        history_gap = _derived(
            history_score - state_score
            if card.score_direction is ScoreDirection.MINIMIZE
            else state_score - history_score,
            "state-only versus history oriented gap",
        )

        disposition = OriginalScopeDisposition.INCONCLUSIVE_UNBOUND_EVIDENCE

        rows.append(
            {
                "readout_id": card.readout_id,
                "candidate_seal_digest": card.candidate_seal_digest,
                "source_scope_digest": card.source_scope_digest,
                "target_scope_digest": card.target_scope_digest,
                "caller_asserted_candidate_sealed_before_target_reveal": (
                    card.candidate_sealed_before_target_reveal
                ),
                "candidate_base_digest_before": card.candidate_base_digest_before,
                "candidate_base_digest_after": card.candidate_base_digest_after,
                "candidate_base_digest_strings_equal": base_frozen,
                "candidate_build_worker_id": card.candidate_build_worker_id,
                "readout_worker_id": card.readout_worker_id,
                "history_baseline_worker_id": card.history_baseline_worker_id,
                "readout_worker_id_distinct_from_candidate_builder": (
                    independent_worker
                ),
                "history_worker_id_distinct_from_candidate_and_readout": (
                    history_worker_independent
                ),
                "readout_inputs": sorted(item.value for item in card.readout_inputs),
                "state_only_input_contract_satisfied": inputs_compliant,
                "history_baseline_inputs": sorted(
                    item.value for item in card.history_baseline_inputs
                ),
                "history_baseline_input_contract_satisfied": history_inputs_compliant,
                "caller_asserted_input_shape_includes_raw_history": (
                    "history_reread_violation" in hard_violations
                ),
                "novelty_relation": card.novelty_relation.value,
                "novelty_basis_digest": card.novelty_basis_digest,
                "protocol_shape_candidate": protocol_shape_candidate,
                "evidence_status": "unverified_caller_assertions",
                "freeze_gate_eligible": False,
                "formal_novel_readout_eligibility": {
                    "status": "unavailable_unbound_evidence",
                    "value": None,
                },
                "caller_asserted_in_original_y": card.in_original_y,
                "original_y_membership_basis": card.original_y_membership_basis.value,
                "original_y_membership_evidence_digest": card.original_y_membership_evidence_digest,
                "postseal_new_readout_score": state_score,
                "score_direction": card.score_direction.value,
                "postseal_new_readout_sample_efficiency": state_efficiency,
                "history_baseline_sample_efficiency": history_efficiency,
                "postseal_history_baseline_gap": history_gap,
                "state_only_vs_history_interpretation": (
                    "positive_favors_state_only; zero_tie; negative_favors_history"
                ),
                "curve_points": [
                    {
                        "train_examples": point.train_examples,
                        "state_only_score": float(point.state_only_score),
                        "history_baseline_score": float(point.history_baseline_score),
                    }
                    for point in evaluation.points
                ],
                "exact_denominator_curve_points": len(evaluation.points),
                "protocol_shape_violation_facts": hard_violations,
                "original_scope_sufficiency_disposition": disposition.value,
                "formal_original_scope_falsification": {
                    "status": "unavailable_unbound_evidence",
                    "value": None,
                },
                "missing_authorities": list(M16_MISSING_AUTHORITIES),
                "formula_qualification": "provided_exposure_only",
            }
        )

    return NovelReadoutTransferResult(readouts=tuple(rows))
