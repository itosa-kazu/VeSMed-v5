"""Exact-byte coverage projection for one authority-bound benchmark shard.

This module is deliberately downstream of the pre-split family graph and the
unified candidate/judge corpus artifact.  It does not create denominator,
query-template, pair-threshold, expected-cell, freeze, or run authority.  Its
only job is to project facts already bound by exact parent bytes into a typed
population/probe inventory which a later 315-cell composite can re-derive.

Parsing a projection proves canonical self-consistency only.  Authority-aware
callers must use :func:`verify_shard_coverage_projection_bytes`, which rebuilds
the complete projection from the supplied parent bytes and requires exact
byte equality.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from threading import RLock
from typing import Any
from weakref import ReferenceType, ref

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    domain_digest,
    reject_privileged_keys,
    validate_json_like,
)
from .corpus_authority import (
    parse_authority_bound_corpus_audit_bytes,
    parse_authority_bound_corpus_scope_contract_bytes,
    parse_unified_corpus_authority_artifact_bytes,
)
from .evaluator import EvaluationCohort, EvaluationSplit
from .family_manifest import (
    FamilySplit,
    MaterializationRole,
    PairSemantic,
    parse_family_materialization_authority_artifact_set_bytes,
)
from .schema import PRIVILEGED_FIELD_NAMES
from .world_registry import WORLD_REGISTRY, registry_digest
from .worlds.base import WorldSplit


PROJECTION_PROTOCOL = "ucm-shard-corpus-coverage-projection/1"
INCOMPLETE_ISOLATION_CODE = "UCM-E002-ISOLATION_INCOMPLETE"
INCOMPLETE_HARNESS_CODE = "UCM-E003-HARNESS_INCOMPLETE"

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_WORLD_RE = re.compile(r"W(?:0[1-9]|1[0-9]|20)\Z")
_REPLICATE_RE = re.compile(r"(?:train|eval)-0[1-5]\Z")
_MAX_CORPUS_BYTES = 512 * 1024 * 1024
_MAX_CORPUS_ROWS = 100_000
_MAX_LINE_BYTES = 16 * 1024 * 1024

_RECORD_ROOT_DOMAIN = b"UCM\0SHARD_COVERAGE_RECORD_SET_V1\0"
_RECEIPT_SUBSET_ROOT_DOMAIN = b"UCM\0SHARD_COVERAGE_RECEIPT_SUBSET_V1\0"
_COHORT_SLOT_DOMAIN = b"UCM\0SHARD_COVERAGE_COHORT_SLOT_V1\0"
_PAIR_INSTANCE_DOMAIN = b"UCM\0SHARD_COVERAGE_PAIR_INSTANCE_V1\0"
_PAIR_TOPOLOGY_ROOT_DOMAIN = b"UCM\0SHARD_COVERAGE_PAIR_TOPOLOGY_V1\0"
_PAIR_ENDPOINT_BINDING_DOMAIN = b"UCM\0SHARD_COVERAGE_PAIR_ENDPOINT_BINDING_V1\0"
_PAIR_ENDPOINT_SET_ROOT_DOMAIN = b"UCM\0SHARD_COVERAGE_PAIR_ENDPOINT_SET_V1\0"
_AUTHORITY_ROOT_SET_DOMAIN = b"UCM\0SHARD_COVERAGE_AUTHORITY_ROOT_SET_V1\0"
_IDENTITY_DOMAIN = b"UCM\0SHARD_COVERAGE_IDENTITY_V1\0"

_CANDIDATE_PUBLIC_ROW_KEYS = frozenset(
    {"schema_version", "record_id", "catalog", "public_history", "scope_digest"}
)
_CANDIDATE_AUTHORITY_KEYS = frozenset(
    {
        "assigned_split",
        "atomic_link_digest",
        "authority_digest",
        "behavior_pair",
        "combined_labels",
        "family_assignment_digest",
        "family_digest",
        "family_materialization_receipt_digest",
        "family_source_digest",
        "judge_frozen_labels",
        "materialization_slot_digest",
        "member_digest",
        "pair_digest",
        "pair_id",
        "pair_side",
        "pre_split_allocation_manifest_digest",
        "strata",
        "stratum",
    }
)
_ROLE_COHORT_PAIRS = (
    (MaterializationRole.STANDARD_ROW, EvaluationCohort.POPULATION),
    (MaterializationRole.RELEASE_STAGE_ROW, EvaluationCohort.POPULATION),
    (MaterializationRole.W19_ASSIGNMENT_ROW, EvaluationCohort.POPULATION),
    (MaterializationRole.PROBE_ROW, EvaluationCohort.PROBE),
    (MaterializationRole.PAIR_SIDE, EvaluationCohort.PROBE),
)
_ROLE_COHORT_MAP = dict(_ROLE_COHORT_PAIRS)
_ROLE_COHORT_CONTRACT_DIGEST = digest_json(
    [
        {"materialization_role": role.value, "cohort": cohort.value}
        for role, cohort in _ROLE_COHORT_PAIRS
    ]
)

_SEALED_OBJECT_REFS: dict[int, tuple[ReferenceType[Any], str]] = {}
_SEALED_OBJECT_REFS_LOCK = RLock()


def _seal_or_validate_once(
    value: object,
    *,
    expected_digest: str,
    allow_initialization: bool,
) -> None:
    """Retain the first body digest outside a caller-mutable frozen object."""

    _digest(expected_digest, "projection seal digest")
    object_id = id(value)
    with _SEALED_OBJECT_REFS_LOCK:
        existing = _SEALED_OBJECT_REFS.get(object_id)
        initialized = existing is not None and existing[0]() is value
        try:
            stored = object.__getattribute__(value, "_sealed_body_digest")
        except AttributeError:
            if not allow_initialization or initialized:
                raise ProtocolViolation("projection first seal is missing")
            object.__setattr__(value, "_sealed_body_digest", expected_digest)

            def discard(dead: ReferenceType[Any]) -> None:
                with _SEALED_OBJECT_REFS_LOCK:
                    current = _SEALED_OBJECT_REFS.get(object_id)
                    if current is not None and current[0] is dead:
                        del _SEALED_OBJECT_REFS[object_id]

            _SEALED_OBJECT_REFS[object_id] = (ref(value, discard), expected_digest)
            return
        if initialized and existing[1] != expected_digest:
            raise ProtocolViolation("projection changed after construction")
        if stored != expected_digest:
            raise ProtocolViolation("projection changed after construction")
        if not initialized:

            def discard(dead: ReferenceType[Any]) -> None:
                with _SEALED_OBJECT_REFS_LOCK:
                    current = _SEALED_OBJECT_REFS.get(object_id)
                    if current is not None and current[0] is dead:
                        del _SEALED_OBJECT_REFS[object_id]

            _SEALED_OBJECT_REFS[object_id] = (ref(value, discard), expected_digest)


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    return value


def _exact_keys(value: object, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    actual = frozenset(value)
    if actual != keys:
        raise ProtocolViolation(
            f"{label} has non-canonical fields; "
            f"missing={sorted(keys - actual)!r}, extra={sorted(actual - keys)!r}"
        )
    return value


def _decode_canonical_object(payload: bytes, label: str) -> dict[str, Any]:
    if type(payload) is not bytes or not payload:
        raise ProtocolViolation(f"{label} must be non-empty exact bytes")
    if len(payload) > _MAX_CORPUS_BYTES:
        raise ProtocolViolation(f"{label} exceeds the code-owned byte limit")

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ProtocolViolation(f"{label} contains duplicate object key {key!r}")
            result[key] = item
        return result

    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=object_pairs,
            parse_constant=lambda token: (_ for _ in ()).throw(
                ProtocolViolation(f"{label} contains forbidden constant {token}")
            ),
        )
    except ProtocolViolation:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProtocolViolation(f"{label} is not strict canonical JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} root must be an exact object")
    try:
        validate_json_like(value, path=label)
        canonical = canonical_json_bytes(value)
    except (ProtocolViolation, UnicodeEncodeError, RecursionError) as exc:
        raise ProtocolViolation(f"{label} contains invalid JSON values") from exc
    if canonical != payload:
        raise ProtocolViolation(f"{label} bytes are not canonical JSON + LF")
    return value


@dataclass(frozen=True, slots=True)
class _JsonlRow:
    record_id: str
    value: dict[str, Any]
    line_digest: str


def _parse_canonical_jsonl(payload: bytes, *, label: str) -> tuple[_JsonlRow, ...]:
    if type(payload) is not bytes or not payload:
        raise ProtocolViolation(f"{label} must be non-empty exact bytes")
    if len(payload) > _MAX_CORPUS_BYTES:
        raise ProtocolViolation(f"{label} exceeds the code-owned byte limit")
    if payload.startswith(b"\xef\xbb\xbf"):
        raise ProtocolViolation(f"{label} must not contain a UTF-8 BOM")
    if not payload.endswith(b"\n") or b"\r" in payload:
        raise ProtocolViolation(f"{label} must use exact LF framing")
    lines = payload.splitlines(keepends=True)
    if not lines or len(lines) > _MAX_CORPUS_ROWS or b"".join(lines) != payload:
        raise ProtocolViolation(f"{label} line framing/count is invalid")
    rows: list[_JsonlRow] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        row_label = f"{label}[{index}]"
        if not line.endswith(b"\n") or line == b"\n" or len(line) > _MAX_LINE_BYTES:
            raise ProtocolViolation(f"{row_label} has invalid line framing/size")
        value = _decode_canonical_object(line, row_label)
        record_id = _name(value.get("record_id"), f"{row_label} record_id")
        if record_id in seen:
            raise ProtocolViolation(f"{label} contains duplicate record_id {record_id!r}")
        seen.add(record_id)
        rows.append(_JsonlRow(record_id, value, digest_bytes(line)))
    return tuple(rows)


def _split_from_family(value: FamilySplit) -> EvaluationSplit:
    if value is FamilySplit.TRAIN:
        return EvaluationSplit.TRAIN
    if value is FamilySplit.VALIDATION:
        return EvaluationSplit.VALIDATION
    if value is FamilySplit.SEALED_TEST:
        return EvaluationSplit.TEST
    raise ProtocolViolation("family split enum identity is invalid")


def _world_split(value: EvaluationSplit) -> WorldSplit:
    if value is EvaluationSplit.TRAIN:
        return WorldSplit.TRAIN
    if value is EvaluationSplit.VALIDATION:
        return WorldSplit.VALIDATION
    if value is EvaluationSplit.TEST:
        return WorldSplit.SEALED_TEST
    raise ProtocolViolation("projection split must be train, validation, or test")


def _cohort_from_role(value: MaterializationRole) -> EvaluationCohort:
    if type(value) is not MaterializationRole or value not in _ROLE_COHORT_MAP:
        raise ProtocolViolation("materialization role enum identity is invalid")
    return _ROLE_COHORT_MAP[value]


def _family_split_from_evaluation(value: EvaluationSplit) -> FamilySplit:
    if value is EvaluationSplit.TRAIN:
        return FamilySplit.TRAIN
    if value is EvaluationSplit.VALIDATION:
        return FamilySplit.VALIDATION
    if value is EvaluationSplit.TEST:
        return FamilySplit.SEALED_TEST
    raise ProtocolViolation("projection split has no family authority mapping")


def _panel(world_slot: str, panel_id: str) -> Any:
    declaration = WORLD_REGISTRY.get(world_slot)
    if declaration is None:
        raise ProtocolViolation("projection world is outside W01--W20")
    matches = tuple(panel for panel in declaration.panels if panel.panel_id == panel_id)
    if len(matches) != 1:
        raise ProtocolViolation("projection panel is absent or ambiguous in live registry")
    return matches[0]


@dataclass(frozen=True, slots=True)
class ShardProjectionIdentity:
    benchmark_id: str
    benchmark_revision: str
    scope_digest: str
    registry_digest: str
    world_slot: str
    panel_id: str
    split: EvaluationSplit
    training_replicate_id: str
    evaluation_replicate_id: str

    def __post_init__(self) -> None:
        _name(self.benchmark_id, "projection benchmark_id")
        _name(self.benchmark_revision, "projection benchmark_revision")
        _digest(self.scope_digest, "projection scope_digest")
        _digest(self.registry_digest, "projection registry_digest")
        if type(self.world_slot) is not str or _WORLD_RE.fullmatch(self.world_slot) is None:
            raise ProtocolViolation("projection world_slot must be W01--W20")
        _name(self.panel_id, "projection panel_id")
        if type(self.split) is not EvaluationSplit or self.split not in {
            EvaluationSplit.TRAIN,
            EvaluationSplit.VALIDATION,
            EvaluationSplit.TEST,
        }:
            raise ProtocolViolation("projection split is outside benchmark v1")
        if (
            type(self.training_replicate_id) is not str
            or _REPLICATE_RE.fullmatch(self.training_replicate_id) is None
            or not self.training_replicate_id.startswith("train-")
        ):
            raise ProtocolViolation("projection training replicate is invalid")
        if (
            type(self.evaluation_replicate_id) is not str
            or _REPLICATE_RE.fullmatch(self.evaluation_replicate_id) is None
            or not self.evaluation_replicate_id.startswith("eval-")
        ):
            raise ProtocolViolation("projection evaluation replicate is invalid")
        if self.training_replicate_id[6:] != self.evaluation_replicate_id[5:]:
            raise ProtocolViolation("projection replicate pair must be zipped, not Cartesian")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        body = {
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "scope_digest": self.scope_digest,
            "registry_digest": self.registry_digest,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "split": self.split.value,
            "family_split": _family_split_from_evaluation(self.split).value,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
        }
        return {**body, "identity_digest": domain_digest(_IDENTITY_DOMAIN, (canonical_json_bytes(body),))}

    @property
    def identity_digest(self) -> str:
        return self.to_wire()["identity_digest"]

    @classmethod
    def from_wire(cls, value: object) -> "ShardProjectionIdentity":
        row = _exact_keys(
            value,
            frozenset(
                {
                    "benchmark_id",
                    "benchmark_revision",
                    "scope_digest",
                    "registry_digest",
                    "world_slot",
                    "panel_id",
                    "split",
                    "family_split",
                    "training_replicate_id",
                    "evaluation_replicate_id",
                    "identity_digest",
                }
            ),
            "projection identity",
        )
        try:
            split = EvaluationSplit(row["split"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("projection identity split is invalid") from exc
        result = cls(
            row["benchmark_id"],
            row["benchmark_revision"],
            row["scope_digest"],
            row["registry_digest"],
            row["world_slot"],
            row["panel_id"],
            split,
            row["training_replicate_id"],
            row["evaluation_replicate_id"],
        )
        _digest(row["identity_digest"], "projection identity_digest")
        if canonical_json_bytes(row) != canonical_json_bytes(result.to_wire()):
            raise ProtocolViolation("projection identity is stale or re-signed")
        return result


@dataclass(frozen=True, slots=True)
class ProjectionParentBindings:
    unified_artifact_digest: str
    unified_authority_body_digest: str
    family_artifact_digest: str
    family_authority_body_digest: str
    scope_artifact_digest: str
    scope_authority_body_digest: str
    audit_artifact_digest: str
    audit_authority_body_digest: str
    candidate_corpus_digest: str
    judge_corpus_digest: str
    family_receipt_exact_set_root: str
    authority_root_count: int
    authority_root_set_digest: str

    def __post_init__(self) -> None:
        for field_name in self.__dataclass_fields__:
            if field_name == "authority_root_count":
                continue
            _digest(getattr(self, field_name), f"projection parent {field_name}")
        if type(self.authority_root_count) is not int or self.authority_root_count != 13:
            raise ProtocolViolation("projection parent authority_root_count must be 13")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {name: getattr(self, name) for name in self.__dataclass_fields__}

    @classmethod
    def from_wire(cls, value: object) -> "ProjectionParentBindings":
        keys = frozenset(cls.__dataclass_fields__)
        row = _exact_keys(value, keys, "projection parent bindings")
        return cls(**{key: row[key] for key in cls.__dataclass_fields__})


@dataclass(frozen=True, slots=True)
class ProjectedRecord:
    record_id: str
    cohort: EvaluationCohort
    materialization_role: MaterializationRole
    family_digest: str
    authority_digest: str
    member_digest: str
    materialization_slot_digest: str
    receipt_artifact_digest: str
    receipt_authority_body_digest: str
    candidate_line_digest: str
    judge_line_digest: str
    public_history_digest: str
    stage_label: str
    cut_digest: str
    query_cell_digest: str
    atomic_link_digest: str | None
    pair_digest: str | None
    pair_semantic: PairSemantic | None
    pair_side: int | None
    raw_request_digest: str
    raw_response_digest: str

    def __post_init__(self) -> None:
        _name(self.record_id, "projected record_id")
        if type(self.cohort) is not EvaluationCohort:
            raise ProtocolViolation("projected cohort must be typed")
        if type(self.materialization_role) is not MaterializationRole:
            raise ProtocolViolation("projected materialization role must be typed")
        if _cohort_from_role(self.materialization_role) is not self.cohort:
            raise ProtocolViolation("projected cohort contradicts code-owned role mapping")
        for value, label in (
            (self.family_digest, "family_digest"),
            (self.authority_digest, "authority_digest"),
            (self.member_digest, "member_digest"),
            (self.materialization_slot_digest, "materialization_slot_digest"),
            (self.receipt_artifact_digest, "receipt_artifact_digest"),
            (self.receipt_authority_body_digest, "receipt_authority_body_digest"),
            (self.candidate_line_digest, "candidate_line_digest"),
            (self.judge_line_digest, "judge_line_digest"),
            (self.public_history_digest, "public_history_digest"),
            (self.cut_digest, "cut_digest"),
            (self.query_cell_digest, "query_cell_digest"),
            (self.raw_request_digest, "raw_request_digest"),
            (self.raw_response_digest, "raw_response_digest"),
        ):
            _digest(value, f"projected record {label}")
        _name(self.stage_label, "projected record stage_label")
        if self.atomic_link_digest is not None:
            _digest(self.atomic_link_digest, "projected record atomic_link_digest")
        if self.materialization_role is MaterializationRole.PAIR_SIDE:
            _digest(self.pair_digest, "projected pair_digest")
            if type(self.pair_semantic) is not PairSemantic:
                raise ProtocolViolation("projected pair semantic must be typed")
            if type(self.pair_side) is not int or self.pair_side not in {0, 1}:
                raise ProtocolViolation("projected pair side must be exact integer 0/1")
        elif (
            self.pair_digest is not None
            or self.pair_semantic is not None
            or self.pair_side is not None
        ):
            raise ProtocolViolation("non-pair projected record cannot claim pair authority")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "record_id": self.record_id,
            "cohort": self.cohort.value,
            "materialization_role": self.materialization_role.value,
            "family_digest": self.family_digest,
            "authority_digest": self.authority_digest,
            "member_digest": self.member_digest,
            "materialization_slot_digest": self.materialization_slot_digest,
            "receipt_artifact_digest": self.receipt_artifact_digest,
            "receipt_authority_body_digest": self.receipt_authority_body_digest,
            "candidate_line_digest": self.candidate_line_digest,
            "judge_line_digest": self.judge_line_digest,
            "public_history_digest": self.public_history_digest,
            "stage_label": self.stage_label,
            "cut_digest": self.cut_digest,
            "query_cell_digest": self.query_cell_digest,
            "atomic_link_digest": self.atomic_link_digest,
            "pair_digest": self.pair_digest,
            "pair_semantic": (
                None if self.pair_semantic is None else self.pair_semantic.value
            ),
            "pair_side": self.pair_side,
            "raw_request_digest": self.raw_request_digest,
            "raw_response_digest": self.raw_response_digest,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ProjectedRecord":
        keys = frozenset(cls.__dataclass_fields__)
        row = _exact_keys(value, keys, "projected record")
        try:
            cohort = EvaluationCohort(row["cohort"])
            role = MaterializationRole(row["materialization_role"])
            pair_semantic = (
                None
                if row["pair_semantic"] is None
                else PairSemantic(row["pair_semantic"])
            )
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("projected record enum value is invalid") from exc
        return cls(
            record_id=row["record_id"],
            cohort=cohort,
            materialization_role=role,
            pair_semantic=pair_semantic,
            **{
                key: row[key]
                for key in cls.__dataclass_fields__
                if key
                not in {
                    "record_id",
                    "cohort",
                    "materialization_role",
                    "pair_semantic",
                }
            },
        )


@dataclass(frozen=True, slots=True)
class ProjectedCohort:
    cohort: EvaluationCohort
    coverage_slot_digest: str
    record_count: int
    expected_source_count: int | None
    record_set_root: str
    receipt_subset_root: str

    def __post_init__(self) -> None:
        if type(self.cohort) is not EvaluationCohort:
            raise ProtocolViolation("projected cohort summary must be typed")
        _digest(self.coverage_slot_digest, "projected cohort coverage_slot_digest")
        if type(self.record_count) is not int or self.record_count < 0:
            raise ProtocolViolation("projected cohort record_count is invalid")
        if self.expected_source_count is not None and (
            type(self.expected_source_count) is not int or self.expected_source_count < 0
        ):
            raise ProtocolViolation("projected expected_source_count is invalid")
        if self.cohort is EvaluationCohort.POPULATION:
            if self.expected_source_count is None:
                raise ProtocolViolation("population projection needs registry count")
        elif self.expected_source_count is not None:
            raise ProtocolViolation("probe projection cannot invent a registry denominator")
        _digest(self.record_set_root, "projected cohort record_set_root")
        _digest(self.receipt_subset_root, "projected cohort receipt_subset_root")

    @property
    def registry_count_matches(self) -> bool | None:
        if self.expected_source_count is None:
            return None
        return self.record_count == self.expected_source_count

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "cohort": self.cohort.value,
            "coverage_slot_digest": self.coverage_slot_digest,
            "record_count": self.record_count,
            "expected_source_count": self.expected_source_count,
            "registry_count_matches": self.registry_count_matches,
            "record_set_root": self.record_set_root,
            "receipt_subset_root": self.receipt_subset_root,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ProjectedCohort":
        row = _exact_keys(
            value,
            frozenset(
                {
                    "cohort",
                    "coverage_slot_digest",
                    "record_count",
                    "expected_source_count",
                    "registry_count_matches",
                    "record_set_root",
                    "receipt_subset_root",
                }
            ),
            "projected cohort summary",
        )
        try:
            cohort = EvaluationCohort(row["cohort"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("projected cohort enum is invalid") from exc
        result = cls(
            cohort,
            row["coverage_slot_digest"],
            row["record_count"],
            row["expected_source_count"],
            row["record_set_root"],
            row["receipt_subset_root"],
        )
        if type(row["registry_count_matches"]) not in {bool, type(None)}:
            raise ProtocolViolation("registry_count_matches must be exact bool or null")
        if row["registry_count_matches"] is not result.registry_count_matches:
            raise ProtocolViolation("registry_count_matches is not derived")
        return result


@dataclass(frozen=True, slots=True)
class ProjectedPair:
    pair_instance_digest: str
    pair_digest: str
    pair_semantic: PairSemantic
    stage_label: str
    cut_digest: str
    query_cell_digest: str
    endpoints: tuple[ProjectedRecord, ProjectedRecord]
    endpoint_binding_root: str

    def __post_init__(self) -> None:
        _digest(self.pair_instance_digest, "projected pair instance digest")
        _digest(self.pair_digest, "projected pair digest")
        if type(self.pair_semantic) is not PairSemantic:
            raise ProtocolViolation("projected pair semantic must be typed")
        _name(self.stage_label, "projected pair stage_label")
        _digest(self.cut_digest, "projected pair cut_digest")
        _digest(self.query_cell_digest, "projected pair query_cell_digest")
        if type(self.endpoints) is not tuple or len(self.endpoints) != 2 or any(
            type(item) is not ProjectedRecord for item in self.endpoints
        ):
            raise ProtocolViolation("projected pair requires two typed endpoints")
        for endpoint in self.endpoints:
            endpoint.__post_init__()
        if tuple(item.pair_side for item in self.endpoints) != (0, 1):
            raise ProtocolViolation("projected pair endpoints must be exact ordered sides 0/1")
        if any(
            item.cohort is not EvaluationCohort.PROBE
            or item.materialization_role is not MaterializationRole.PAIR_SIDE
            or item.pair_digest != self.pair_digest
            or item.pair_semantic is not self.pair_semantic
            or item.stage_label != self.stage_label
            or item.cut_digest != self.cut_digest
            or item.query_cell_digest != self.query_cell_digest
            for item in self.endpoints
        ):
            raise ProtocolViolation("projected pair endpoints are cross-bound")
        if len({item.family_digest for item in self.endpoints}) != 1 or len(
            {item.authority_digest for item in self.endpoints}
        ) != 1:
            raise ProtocolViolation("projected pair endpoints cross family authority")
        if any(item.family_digest != item.authority_digest for item in self.endpoints):
            raise ProtocolViolation("projected pair family/authority identity differs")
        for attribute in (
            "record_id",
            "member_digest",
            "materialization_slot_digest",
            "receipt_artifact_digest",
            "receipt_authority_body_digest",
        ):
            if len({getattr(item, attribute) for item in self.endpoints}) != 2:
                raise ProtocolViolation(f"projected pair endpoints reuse {attribute}")
        _digest(self.endpoint_binding_root, "projected pair endpoint_binding_root")

    def to_wire(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "pair_instance_digest": self.pair_instance_digest,
            "pair_digest": self.pair_digest,
            "pair_semantic": self.pair_semantic.value,
            "stage_label": self.stage_label,
            "cut_digest": self.cut_digest,
            "query_cell_digest": self.query_cell_digest,
            "endpoints": [item.to_wire() for item in self.endpoints],
            "endpoint_binding_root": self.endpoint_binding_root,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ProjectedPair":
        row = _exact_keys(
            value,
            frozenset(
                {
                    "pair_instance_digest",
                    "pair_digest",
                    "pair_semantic",
                    "stage_label",
                    "cut_digest",
                    "query_cell_digest",
                    "endpoints",
                    "endpoint_binding_root",
                }
            ),
            "projected pair",
        )
        endpoints = row["endpoints"]
        if type(endpoints) is not list:
            raise ProtocolViolation("projected pair endpoints must be a list")
        try:
            pair_semantic = PairSemantic(row["pair_semantic"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("projected pair semantic is invalid") from exc
        return cls(
            row["pair_instance_digest"],
            row["pair_digest"],
            pair_semantic,
            row["stage_label"],
            row["cut_digest"],
            row["query_cell_digest"],
            tuple(ProjectedRecord.from_wire(item) for item in endpoints),
            row["endpoint_binding_root"],
        )


@dataclass(frozen=True, slots=True)
class ProjectionBlocker:
    code: str
    artifact: str
    detail: str

    def __post_init__(self) -> None:
        if self.code not in {INCOMPLETE_ISOLATION_CODE, INCOMPLETE_HARNESS_CODE}:
            raise ProtocolViolation("projection blocker code is not code-owned")
        _name(self.artifact, "projection blocker artifact")
        _name(self.detail, "projection blocker detail")

    def to_wire(self) -> dict[str, str]:
        self.__post_init__()
        return {"code": self.code, "artifact": self.artifact, "detail": self.detail}

    @classmethod
    def from_wire(cls, value: object) -> "ProjectionBlocker":
        row = _exact_keys(
            value,
            frozenset({"code", "artifact", "detail"}),
            "projection blocker",
        )
        return cls(row["code"], row["artifact"], row["detail"])


def _fixed_blockers(
    population: ProjectedCohort,
    probe: ProjectedCohort,
    *,
    registry_declares_probes: bool,
) -> tuple[ProjectionBlocker, ...]:
    blockers = [
        ProjectionBlocker(
            INCOMPLETE_ISOLATION_CODE,
            "execution_isolation",
            "portable Python isolation is not a freeze-grade kernel boundary",
        ),
        ProjectionBlocker(
            INCOMPLETE_HARNESS_CODE,
            "external_custody",
            "external immutable custody and atomic publication are not established",
        ),
        ProjectionBlocker(
            INCOMPLETE_HARNESS_CODE,
            "coverage_contracts",
            "independent denominator, query-template, and pair-threshold authority is absent",
        ),
    ]
    if population.registry_count_matches is not True:
        blockers.append(
            ProjectionBlocker(
                INCOMPLETE_HARNESS_CODE,
                "population_denominator",
                "derived population record_count does not equal the live registry denominator",
            )
        )
    if registry_declares_probes and probe.record_count == 0:
        blockers.append(
            ProjectionBlocker(
                INCOMPLETE_HARNESS_CODE,
                "probe_inventory",
                "live registry declares probes but this shard projects no probe records",
            )
        )
    return tuple(blockers)


@dataclass(frozen=True, slots=True, weakref_slot=True)
class ShardCoverageProjectionV1:
    identity: ShardProjectionIdentity
    parents: ProjectionParentBindings
    records: tuple[ProjectedRecord, ...]
    population: ProjectedCohort
    probe: ProjectedCohort
    registry_declares_probes: bool
    pairs: tuple[ProjectedPair, ...]
    pair_topology_root: str
    pair_endpoint_bindings_root: str
    blockers: tuple[ProjectionBlocker, ...]
    _sealed_body_digest: str = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self._validate(allow_seal_initialization=True)

    @property
    def structurally_complete(self) -> bool:
        self._validate()
        return False

    @property
    def population_registry_count_matches(self) -> bool:
        self._validate()
        return self.population.registry_count_matches is True

    @property
    def benchmark_freeze_eligible(self) -> bool:
        self._validate()
        return False

    def _body_unchecked(self) -> dict[str, Any]:
        return {
            "schema_version": PROJECTION_PROTOCOL,
            "status": "PRE-FREEZE",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_role": "judge_only",
            "role_cohort_contract_digest": _ROLE_COHORT_CONTRACT_DIGEST,
            "coverage_structurally_complete": False,
            "population_registry_count_matches": (
                self.population.registry_count_matches is True
            ),
            "registry_declares_probes": self.registry_declares_probes,
            "identity": self.identity.to_wire(),
            "parents": self.parents.to_wire(),
            "records": [item.to_wire() for item in self.records],
            "cohorts": {
                "population": self.population.to_wire(),
                "probe": self.probe.to_wire(),
            },
            "pairs": {
                "pair_count": len(self.pairs),
                "endpoint_count": 2 * len(self.pairs),
                "pair_topology_root": self.pair_topology_root,
                "pair_endpoint_bindings_root": self.pair_endpoint_bindings_root,
                "entries": [item.to_wire() for item in self.pairs],
            },
            "blockers": [item.to_wire() for item in self.blockers],
        }

    def _validate(self, *, allow_seal_initialization: bool = False) -> dict[str, Any]:
        if type(self.identity) is not ShardProjectionIdentity:
            raise ProtocolViolation("projection identity has wrong type")
        self.identity.__post_init__()
        if type(self.parents) is not ProjectionParentBindings:
            raise ProtocolViolation("projection parents have wrong type")
        self.parents.__post_init__()
        if type(self.records) is not tuple or any(
            type(item) is not ProjectedRecord for item in self.records
        ):
            raise ProtocolViolation("projection records must be a typed tuple")
        for item in self.records:
            item.__post_init__()
        ordered_records = tuple(sorted(self.records, key=lambda item: item.record_id))
        if self.records != ordered_records:
            raise ProtocolViolation("projection records must be canonical by record_id")
        for attribute in (
            "record_id",
            "materialization_slot_digest",
            "receipt_artifact_digest",
            "receipt_authority_body_digest",
            "candidate_line_digest",
            "judge_line_digest",
            "raw_request_digest",
            "raw_response_digest",
        ):
            values = [getattr(item, attribute) for item in self.records]
            if len(values) != len(set(values)):
                raise ProtocolViolation(f"projection records reuse {attribute}")
        if type(self.population) is not ProjectedCohort or type(self.probe) is not ProjectedCohort:
            raise ProtocolViolation("projection cohorts must be typed")
        self.population.__post_init__()
        self.probe.__post_init__()
        if (
            self.population.cohort is not EvaluationCohort.POPULATION
            or self.probe.cohort is not EvaluationCohort.PROBE
        ):
            raise ProtocolViolation("projection cohort summaries are swapped")
        if type(self.registry_declares_probes) is not bool:
            raise ProtocolViolation("registry_declares_probes must be exact boolean")
        derived_population = tuple(
            item for item in self.records if item.cohort is EvaluationCohort.POPULATION
        )
        derived_probe = tuple(
            item for item in self.records if item.cohort is EvaluationCohort.PROBE
        )
        if self.population != _cohort_summary(
            self.identity,
            EvaluationCohort.POPULATION,
            derived_population,
            expected_source_count=self.population.expected_source_count,
        ):
            raise ProtocolViolation("population summary is not record-derived")
        if self.probe != _cohort_summary(
            self.identity,
            EvaluationCohort.PROBE,
            derived_probe,
            expected_source_count=None,
        ):
            raise ProtocolViolation("probe summary is not record-derived")
        if type(self.pairs) is not tuple or any(
            type(item) is not ProjectedPair for item in self.pairs
        ):
            raise ProtocolViolation("projection pairs must be a typed tuple")
        for item in self.pairs:
            item.__post_init__()
        if self.pairs != tuple(sorted(self.pairs, key=lambda item: item.pair_instance_digest)):
            raise ProtocolViolation("projection pairs are not canonically ordered")
        expected_pairs = _derive_pairs(self.identity, derived_probe)
        if self.pairs != expected_pairs:
            raise ProtocolViolation("projection pair inventory is not record-derived")
        pair_topology_root, endpoint_root = _pair_roots(self.identity, self.pairs)
        if self.pair_topology_root != pair_topology_root:
            raise ProtocolViolation("projection pair topology root is stale")
        if self.pair_endpoint_bindings_root != endpoint_root:
            raise ProtocolViolation("projection pair endpoint root is stale")
        _digest(self.pair_topology_root, "projection pair_topology_root")
        _digest(self.pair_endpoint_bindings_root, "projection pair_endpoint_bindings_root")
        if type(self.blockers) is not tuple or any(
            type(item) is not ProjectionBlocker for item in self.blockers
        ):
            raise ProtocolViolation("projection blockers must be a typed tuple")
        for item in self.blockers:
            item.__post_init__()
        if self.blockers != _fixed_blockers(
            self.population,
            self.probe,
            registry_declares_probes=self.registry_declares_probes,
        ):
            raise ProtocolViolation("projection blockers are not code-owned and derived")
        body = self._body_unchecked()
        validate_json_like(body)
        expected_digest = digest_json(body)
        _seal_or_validate_once(
            self,
            expected_digest=expected_digest,
            allow_initialization=allow_seal_initialization,
        )
        return body

    def to_wire(self) -> dict[str, Any]:
        body = self._validate()
        return {**body, "projection_body_digest": self._sealed_body_digest}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def body_digest(self) -> str:
        self._validate()
        return self._sealed_body_digest

    @classmethod
    def from_canonical_bytes(cls, payload: bytes) -> "ShardCoverageProjectionV1":
        row = _decode_canonical_object(payload, "shard coverage projection")
        _exact_keys(
            row,
            frozenset(
                {
                    "schema_version",
                    "status",
                    "freeze_grade_evidence",
                    "benchmark_freeze_eligible",
                    "authority_role",
                    "role_cohort_contract_digest",
                    "coverage_structurally_complete",
                    "population_registry_count_matches",
                    "registry_declares_probes",
                    "identity",
                    "parents",
                    "records",
                    "cohorts",
                    "pairs",
                    "blockers",
                    "projection_body_digest",
                }
            ),
            "shard coverage projection",
        )
        fixed = {
            "schema_version": PROJECTION_PROTOCOL,
            "status": "PRE-FREEZE",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "authority_role": "judge_only",
            "role_cohort_contract_digest": _ROLE_COHORT_CONTRACT_DIGEST,
        }
        for key, expected in fixed.items():
            if type(row[key]) is not type(expected) or row[key] != expected:
                raise ProtocolViolation(f"projection code-owned field differs: {key}")
        records_wire = row["records"]
        blockers_wire = row["blockers"]
        if type(records_wire) is not list or type(blockers_wire) is not list:
            raise ProtocolViolation("projection records/blockers must be lists")
        cohorts = _exact_keys(
            row["cohorts"],
            frozenset({"population", "probe"}),
            "projection cohorts",
        )
        pairs = _exact_keys(
            row["pairs"],
            frozenset(
                {
                    "pair_count",
                    "endpoint_count",
                    "pair_topology_root",
                    "pair_endpoint_bindings_root",
                    "entries",
                }
            ),
            "projection pairs",
        )
        if type(pairs["entries"]) is not list:
            raise ProtocolViolation("projection pair entries must be a list")
        result = cls(
            identity=ShardProjectionIdentity.from_wire(row["identity"]),
            parents=ProjectionParentBindings.from_wire(row["parents"]),
            records=tuple(ProjectedRecord.from_wire(item) for item in records_wire),
            population=ProjectedCohort.from_wire(cohorts["population"]),
            probe=ProjectedCohort.from_wire(cohorts["probe"]),
            registry_declares_probes=row["registry_declares_probes"],
            pairs=tuple(ProjectedPair.from_wire(item) for item in pairs["entries"]),
            pair_topology_root=pairs["pair_topology_root"],
            pair_endpoint_bindings_root=pairs["pair_endpoint_bindings_root"],
            blockers=tuple(ProjectionBlocker.from_wire(item) for item in blockers_wire),
        )
        if type(pairs["pair_count"]) is not int or pairs["pair_count"] != len(result.pairs):
            raise ProtocolViolation("projection pair_count is not derived")
        if type(pairs["endpoint_count"]) is not int or pairs["endpoint_count"] != (
            2 * len(result.pairs)
        ):
            raise ProtocolViolation("projection endpoint_count is not derived")
        if type(row["coverage_structurally_complete"]) is not bool or (
            row["coverage_structurally_complete"] is not False
        ):
            raise ProtocolViolation("projection completeness flag is not derived")
        if type(row["population_registry_count_matches"]) is not bool or (
            row["population_registry_count_matches"]
            is not result.population_registry_count_matches
        ):
            raise ProtocolViolation("population registry flag is not derived")
        _digest(row["projection_body_digest"], "projection_body_digest")
        if payload != result.canonical_bytes:
            raise ProtocolViolation("projection is non-canonical, stale, or re-signed")
        return result


def _cohort_summary(
    identity: ShardProjectionIdentity,
    cohort: EvaluationCohort,
    records: tuple[ProjectedRecord, ...],
    *,
    expected_source_count: int | None,
) -> ProjectedCohort:
    coverage_slot_digest = domain_digest(
        _COHORT_SLOT_DOMAIN,
        (
            canonical_json_bytes(
                {
                    "shard_identity_digest": identity.identity_digest,
                    "cohort": cohort.value,
                }
            ),
        ),
    )
    record_wires = [item.to_wire() for item in records]
    receipt_wires = [
        {
            "record_id": item.record_id,
            "materialization_slot_digest": item.materialization_slot_digest,
            "receipt_artifact_digest": item.receipt_artifact_digest,
            "receipt_authority_body_digest": item.receipt_authority_body_digest,
        }
        for item in records
    ]
    return ProjectedCohort(
        cohort,
        coverage_slot_digest,
        len(records),
        expected_source_count,
        domain_digest(
            _RECORD_ROOT_DOMAIN,
            (
                coverage_slot_digest.encode("ascii"),
                cohort.value.encode("ascii"),
                canonical_json_bytes(record_wires),
            ),
        ),
        domain_digest(
            _RECEIPT_SUBSET_ROOT_DOMAIN,
            (
                coverage_slot_digest.encode("ascii"),
                cohort.value.encode("ascii"),
                canonical_json_bytes(receipt_wires),
            ),
        ),
    )


def _pair_endpoint_binding(
    record: ProjectedRecord,
    *,
    pair_instance_digest: str,
) -> dict[str, Any]:
    return {
        "pair_instance_digest": pair_instance_digest,
        "pair_digest": record.pair_digest,
        "pair_semantic": (
            None if record.pair_semantic is None else record.pair_semantic.value
        ),
        "pair_side": record.pair_side,
        "record_id": record.record_id,
        "family_digest": record.family_digest,
        "authority_digest": record.authority_digest,
        "member_digest": record.member_digest,
        "materialization_slot_digest": record.materialization_slot_digest,
        "receipt_artifact_digest": record.receipt_artifact_digest,
        "receipt_authority_body_digest": record.receipt_authority_body_digest,
        "candidate_line_digest": record.candidate_line_digest,
        "judge_line_digest": record.judge_line_digest,
    }


def _derive_pairs(
    identity: ShardProjectionIdentity,
    probe_records: tuple[ProjectedRecord, ...],
) -> tuple[ProjectedPair, ...]:
    grouped: dict[tuple[str, str, str, str], list[ProjectedRecord]] = {}
    for record in probe_records:
        if record.materialization_role is not MaterializationRole.PAIR_SIDE:
            continue
        assert record.pair_digest is not None
        key = (
            record.pair_digest,
            record.stage_label,
            record.cut_digest,
            record.query_cell_digest,
        )
        grouped.setdefault(key, []).append(record)
    pairs: list[ProjectedPair] = []
    for (pair_digest, stage, cut, query), endpoints in grouped.items():
        ordered = tuple(sorted(endpoints, key=lambda item: item.pair_side))
        if len(ordered) != 2 or tuple(item.pair_side for item in ordered) != (0, 1):
            raise ProtocolViolation("pair instance does not contain exact sides 0 and 1")
        semantics = {item.pair_semantic for item in ordered}
        if len(semantics) != 1 or None in semantics:
            raise ProtocolViolation("pair instance has conflicting or absent semantics")
        pair_semantic = next(iter(semantics))
        assert type(pair_semantic) is PairSemantic
        instance_payload = {
            "shard_identity_digest": identity.identity_digest,
            "pair_digest": pair_digest,
            "pair_semantic": pair_semantic.value,
            "stage_label": stage,
            "cut_digest": cut,
            "query_cell_digest": query,
        }
        instance_digest = domain_digest(
            _PAIR_INSTANCE_DOMAIN, (canonical_json_bytes(instance_payload),)
        )
        endpoint_root = domain_digest(
            _PAIR_ENDPOINT_BINDING_DOMAIN,
            (
                canonical_json_bytes(
                    [
                        _pair_endpoint_binding(
                            item,
                            pair_instance_digest=instance_digest,
                        )
                        for item in ordered
                    ]
                ),
            ),
        )
        pairs.append(
            ProjectedPair(
                instance_digest,
                pair_digest,
                pair_semantic,
                stage,
                cut,
                query,
                ordered,  # type: ignore[arg-type]
                endpoint_root,
            )
        )
    return tuple(sorted(pairs, key=lambda item: item.pair_instance_digest))


def _pair_roots(
    identity: ShardProjectionIdentity,
    pairs: tuple[ProjectedPair, ...],
) -> tuple[str, str]:
    topology = {
        "shard_identity_digest": identity.identity_digest,
        "pairs": [
            {
                "pair_instance_digest": item.pair_instance_digest,
                "pair_digest": item.pair_digest,
                "pair_semantic": item.pair_semantic.value,
                "stage_label": item.stage_label,
                "cut_digest": item.cut_digest,
                "query_cell_digest": item.query_cell_digest,
                "sides": [0, 1],
            }
            for item in pairs
        ],
    }
    endpoints = {
        "shard_identity_digest": identity.identity_digest,
        "pairs": [
            {
                "pair_instance_digest": item.pair_instance_digest,
                "endpoint_binding_root": item.endpoint_binding_root,
            }
            for item in pairs
        ],
    }
    return (
        domain_digest(_PAIR_TOPOLOGY_ROOT_DOMAIN, (canonical_json_bytes(topology),)),
        domain_digest(
            _PAIR_ENDPOINT_SET_ROOT_DOMAIN,
            (canonical_json_bytes(endpoints),),
        ),
    )


def _authority_root_set_digest(
    scope: Any,
    identity: ShardProjectionIdentity,
) -> str:
    rows = sorted(
        (item.to_wire() for item in scope.roots),
        key=lambda item: item["root_id"],
    )
    if len(rows) != 13 or len({item["root_id"] for item in rows}) != 13:
        raise ProtocolViolation("projection authority roots must be an exact set of 13")
    return domain_digest(
        _AUTHORITY_ROOT_SET_DOMAIN,
        (
            identity.identity_digest.encode("ascii"),
            canonical_json_bytes(rows),
        ),
    )


def _validate_projectable_row_semantics(
    *,
    scope: Any,
    candidate: _JsonlRow,
    judge: _JsonlRow,
    evidence: Any,
) -> None:
    """Replay deterministic public/judge joins from the supplied exact bytes.

    Strata classifier/allocation preimages are not embedded in the current
    unified artifact, so this intentionally cannot re-issue their labels.  The
    fixed E003 coverage-contract/custody blockers remain until a later layer
    supplies those exact preimages.  Everything that *is* present here is
    rechecked rather than trusting the embedded audit's empty blocker list.
    """

    candidate_wire = candidate.value
    judge_wire = judge.value
    if frozenset(candidate_wire) != _CANDIDATE_PUBLIC_ROW_KEYS:
        raise ProtocolViolation("candidate row is not the exact closed public schema")
    if candidate_wire.get("schema_version") != "ucm-candidate-public-episode/1":
        raise ProtocolViolation("candidate row schema_version is invalid")
    if judge_wire.get("schema_version") != "ucm-judge-private-episode/1":
        raise ProtocolViolation("judge row schema_version is invalid")
    reject_privileged_keys(
        candidate_wire,
        forbidden=PRIVILEGED_FIELD_NAMES | _CANDIDATE_AUTHORITY_KEYS,
        path=f"$.candidate[{candidate.record_id}]",
    )
    if candidate_wire.get("scope_digest") != scope.scope_digest:
        raise ProtocolViolation("candidate row scope does not exact-join")
    judge_scope_keys = tuple(
        key for key in ("scope_digest", "record_scope_digest") if key in judge_wire
    )
    if len(judge_scope_keys) != 1 or judge_wire[judge_scope_keys[0]] != scope.scope_digest:
        raise ProtocolViolation("judge row scope does not exact-join")
    if (
        type(judge_wire.get("world_slot")) is not str
        or judge_wire["world_slot"] != scope.world_slot
        or type(judge_wire.get("panel_id")) is not str
        or judge_wire["panel_id"] != scope.panel_id
        or type(judge_wire.get("split")) is not str
        or judge_wire["split"] != scope.split.value
        or judge_wire["split"] != evidence.assigned_split.value
    ):
        raise ProtocolViolation("judge row world/panel/split does not exact-join")
    public_history = candidate_wire.get("public_history")
    if type(public_history) is not dict or public_history.get(
        "protocol"
    ) != "ucm-visible-history/1":
        raise ProtocolViolation("candidate public_history is invalid")
    public_history_digest = digest_json(public_history)
    if (
        public_history_digest != evidence.public_history_digest
        or judge_wire.get("public_history_digest") != public_history_digest
    ):
        raise ProtocolViolation("candidate/judge public history does not exact-join")
    catalog = candidate_wire.get("catalog")
    if type(catalog) is not dict or public_history.get("catalog_digest") != digest_json(
        catalog
    ):
        raise ProtocolViolation("candidate catalog and history do not exact-join")
    hidden_state = judge_wire.get("hidden_state_at_cut")
    if hidden_state is None:
        raise ProtocolViolation("judge hidden_state_at_cut is absent")
    validate_json_like(hidden_state, path="judge hidden_state_at_cut")
    if digest_json(hidden_state) != evidence.hidden_state_at_cut_digest:
        raise ProtocolViolation("judge hidden state does not exact-join receipt")
    strata = judge_wire.get("strata")
    if (
        type(strata) is not list
        or not strata
        or any(type(item) is not str or not item for item in strata)
        or len(strata) != len(set(strata))
    ):
        raise ProtocolViolation("judge strata must be a non-empty unique string list")
    if judge_wire.get("unverified_declared_strata") != []:
        raise ProtocolViolation("unverified judge strata cannot enter projection")


def _derive_records(
    *,
    ledger: Any,
    scope: Any,
    candidate_rows: tuple[_JsonlRow, ...],
    judge_rows: tuple[_JsonlRow, ...],
) -> tuple[ProjectedRecord, ...]:
    receipts = ledger.receipts
    candidate_ids = tuple(item.record_id for item in candidate_rows)
    judge_ids = tuple(item.record_id for item in judge_rows)
    if candidate_ids != judge_ids:
        raise ProtocolViolation("candidate and judge record order does not exact-join")
    receipt_by_record = {item.evidence.record_id: item for item in receipts}
    if len(receipt_by_record) != len(receipts) or set(candidate_ids) != set(receipt_by_record):
        raise ProtocolViolation("corpus record exact set differs from receipt ledger")
    slots = {item.slot_digest: item for item in ledger.source.materialization_slots}
    pair_semantics = {
        item.pair_digest: item.semantic_type for item in ledger.source.pairs
    }
    candidate_by_record = {item.record_id: item for item in candidate_rows}
    judge_by_record = {item.record_id: item for item in judge_rows}
    alias_to_pair_digest: dict[str, str] = {}
    pair_digest_to_alias: dict[str, str] = {}
    result: list[ProjectedRecord] = []
    for record_id in sorted(receipt_by_record):
        receipt = receipt_by_record[record_id]
        evidence = receipt.evidence
        slot_digest = evidence.materialization_slot_digest
        if type(slot_digest) is not str or slot_digest not in slots:
            raise ProtocolViolation("receipt does not join a declared materialization slot")
        slot = slots[slot_digest]
        candidate = candidate_by_record[record_id]
        judge = judge_by_record[record_id]
        if candidate.line_digest != evidence.candidate_row_digest:
            raise ProtocolViolation("candidate line digest contradicts receipt")
        if judge.line_digest != evidence.judge_row_digest:
            raise ProtocolViolation("judge line digest contradicts receipt")
        _validate_projectable_row_semantics(
            scope=scope,
            candidate=candidate,
            judge=judge,
            evidence=evidence,
        )
        role = slot.materialization_role
        if role is not evidence.materialization_role:
            raise ProtocolViolation("slot/receipt role identity differs")
        cohort = _cohort_from_role(role)
        judge_cohort = judge.value.get("cohort")
        population_flag = judge.value.get("population_denominator")
        probe_flag = judge.value.get("probe_denominator")
        if type(judge_cohort) is not str or judge_cohort != cohort.value:
            raise ProtocolViolation("judge cohort contradicts role-derived cohort")
        if type(population_flag) is not bool or type(probe_flag) is not bool:
            raise ProtocolViolation("judge denominator flags must be exact booleans")
        if population_flag is not (cohort is EvaluationCohort.POPULATION) or (
            probe_flag is not (cohort is EvaluationCohort.PROBE)
        ):
            raise ProtocolViolation("judge denominator flags contradict role-derived cohort")
        judge_pair_id = judge.value.get("pair_id")
        judge_pair_side = judge.value.get("pair_side")
        if role is MaterializationRole.PAIR_SIDE:
            if type(judge_pair_id) is not str or not judge_pair_id:
                raise ProtocolViolation("pair-side judge alias must be a non-empty string")
            if (
                type(judge_pair_side) is not int
                or judge_pair_side not in {0, 1}
                or judge_pair_side != slot.pair_side
            ):
                raise ProtocolViolation("judge pair_side is not exact integer topology")
            if slot.pair_digest not in pair_semantics:
                raise ProtocolViolation("pair-side slot has no typed pair semantic")
            prior_pair_digest = alias_to_pair_digest.setdefault(
                judge_pair_id, slot.pair_digest
            )
            if prior_pair_digest != slot.pair_digest:
                raise ProtocolViolation(
                    "one judge pair alias refers to multiple pre-split pairs"
                )
            prior_alias = pair_digest_to_alias.setdefault(
                slot.pair_digest, judge_pair_id
            )
            if prior_alias != judge_pair_id:
                raise ProtocolViolation(
                    "one pre-split pair is replaced by multiple judge pair aliases"
                )
        elif judge_pair_id is not None or judge_pair_side is not None:
            raise ProtocolViolation("non-pair role cannot claim judge pair identity")
        receipt_wire = receipt.to_wire()
        receipt_bytes = canonical_json_bytes(receipt_wire)
        result.append(
            ProjectedRecord(
                record_id=record_id,
                cohort=cohort,
                materialization_role=role,
                family_digest=receipt_wire["family_digest"],
                authority_digest=evidence.authority_digest,
                member_digest=evidence.member_digest,
                materialization_slot_digest=slot_digest,
                receipt_artifact_digest=digest_bytes(receipt_bytes),
                receipt_authority_body_digest=receipt.receipt_digest,
                candidate_line_digest=candidate.line_digest,
                judge_line_digest=judge.line_digest,
                public_history_digest=evidence.public_history_digest,
                stage_label=slot.stage_label,
                cut_digest=slot.cut_digest,
                query_cell_digest=slot.query_cell_digest,
                atomic_link_digest=slot.atomic_link_digest,
                pair_digest=slot.pair_digest,
                pair_semantic=(
                    None
                    if slot.pair_digest is None
                    else pair_semantics[slot.pair_digest]
                ),
                pair_side=slot.pair_side,
                raw_request_digest=evidence.raw_request_digest,
                raw_response_digest=evidence.raw_response_digest,
            )
        )
    return tuple(result)


def derive_shard_coverage_projection(
    unified_artifact_bytes: bytes,
    candidate_corpus_bytes: bytes,
    judge_corpus_bytes: bytes,
) -> ShardCoverageProjectionV1:
    """Re-derive one projection from exact parent bytes, always PRE-FREEZE."""

    for value, label in (
        (unified_artifact_bytes, "unified artifact"),
        (candidate_corpus_bytes, "candidate corpus"),
        (judge_corpus_bytes, "judge corpus"),
    ):
        if type(value) is not bytes or not value:
            raise ProtocolViolation(f"{label} must be non-empty exact bytes")
    unified = parse_unified_corpus_authority_artifact_bytes(unified_artifact_bytes)
    family = parse_family_materialization_authority_artifact_set_bytes(
        unified.family_artifact_set_preimage
    )
    scope = parse_authority_bound_corpus_scope_contract_bytes(
        unified.scope_contract_preimage
    )
    audit = parse_authority_bound_corpus_audit_bytes(unified.audit_preimage)
    ledger = family.ledger
    source = ledger.source
    if source.registry_digest != registry_digest():
        raise ProtocolViolation("family source registry digest is stale")
    split = _split_from_family(scope.split)
    identity = ShardProjectionIdentity(
        scope.benchmark_id,
        scope.benchmark_revision,
        scope.scope_digest,
        source.registry_digest,
        scope.world_slot,
        scope.panel_id,
        split,
        scope.training_replicate_id,
        scope.evaluation_replicate_id,
    )
    if digest_bytes(candidate_corpus_bytes) != scope.candidate_corpus_digest or (
        digest_bytes(candidate_corpus_bytes) != audit.candidate_corpus_digest
    ):
        raise ProtocolViolation("candidate corpus bytes contradict parent authority")
    if digest_bytes(judge_corpus_bytes) != scope.judge_corpus_digest or (
        digest_bytes(judge_corpus_bytes) != audit.judge_corpus_digest
    ):
        raise ProtocolViolation("judge corpus bytes contradict parent authority")
    candidate_rows = _parse_canonical_jsonl(
        candidate_corpus_bytes, label="candidate corpus"
    )
    judge_rows = _parse_canonical_jsonl(judge_corpus_bytes, label="judge corpus")
    records = _derive_records(
        ledger=ledger,
        scope=scope,
        candidate_rows=candidate_rows,
        judge_rows=judge_rows,
    )
    panel = _panel(identity.world_slot, identity.panel_id)
    expected_population_count = dict(panel.split_sizes)[_world_split(identity.split)]
    population_records = tuple(
        item for item in records if item.cohort is EvaluationCohort.POPULATION
    )
    probe_records = tuple(
        item for item in records if item.cohort is EvaluationCohort.PROBE
    )
    population = _cohort_summary(
        identity,
        EvaluationCohort.POPULATION,
        population_records,
        expected_source_count=expected_population_count,
    )
    probe = _cohort_summary(
        identity,
        EvaluationCohort.PROBE,
        probe_records,
        expected_source_count=None,
    )
    pairs = _derive_pairs(identity, probe_records)
    pair_topology_root, pair_endpoint_root = _pair_roots(identity, pairs)
    audit_wire = audit.to_wire()
    parents = ProjectionParentBindings(
        unified_artifact_digest=digest_bytes(unified_artifact_bytes),
        unified_authority_body_digest=unified.authority_body_digest,
        family_artifact_digest=digest_bytes(unified.family_artifact_set_preimage),
        family_authority_body_digest=family.artifact_set_digest,
        scope_artifact_digest=digest_bytes(unified.scope_contract_preimage),
        scope_authority_body_digest=scope.contract_digest,
        audit_artifact_digest=digest_bytes(unified.audit_preimage),
        audit_authority_body_digest=audit_wire["audit_digest"],
        candidate_corpus_digest=digest_bytes(candidate_corpus_bytes),
        judge_corpus_digest=digest_bytes(judge_corpus_bytes),
        family_receipt_exact_set_root=family.receipt_exact_set_root,
        authority_root_count=len(scope.roots),
        authority_root_set_digest=_authority_root_set_digest(scope, identity),
    )
    return ShardCoverageProjectionV1(
        identity,
        parents,
        records,
        population,
        probe,
        bool(panel.probes),
        pairs,
        pair_topology_root,
        pair_endpoint_root,
        _fixed_blockers(
            population,
            probe,
            registry_declares_probes=bool(panel.probes),
        ),
    )


def parse_shard_coverage_projection_bytes(
    payload: bytes,
) -> ShardCoverageProjectionV1:
    """Parse canonical self-consistency; this does not grant parent authority."""

    return ShardCoverageProjectionV1.from_canonical_bytes(payload)


def verify_shard_coverage_projection_bytes(
    projection_bytes: bytes,
    *,
    unified_artifact_bytes: bytes,
    candidate_corpus_bytes: bytes,
    judge_corpus_bytes: bytes,
) -> ShardCoverageProjectionV1:
    """Verify exact projection bytes by fully re-deriving from exact parents."""

    parsed = parse_shard_coverage_projection_bytes(projection_bytes)
    derived = derive_shard_coverage_projection(
        unified_artifact_bytes,
        candidate_corpus_bytes,
        judge_corpus_bytes,
    )
    if projection_bytes != derived.canonical_bytes:
        raise ProtocolViolation("projection bytes do not match exact parent re-derivation")
    if parsed.canonical_bytes != derived.canonical_bytes:
        raise ProtocolViolation("parsed projection differs from exact parent derivation")
    return parsed


__all__ = [
    "INCOMPLETE_HARNESS_CODE",
    "INCOMPLETE_ISOLATION_CODE",
    "PROJECTION_PROTOCOL",
    "ProjectedCohort",
    "ProjectedPair",
    "ProjectedRecord",
    "ProjectionBlocker",
    "ProjectionParentBindings",
    "ShardCoverageProjectionV1",
    "ShardProjectionIdentity",
    "derive_shard_coverage_projection",
    "parse_shard_coverage_projection_bytes",
    "verify_shard_coverage_projection_bytes",
]
