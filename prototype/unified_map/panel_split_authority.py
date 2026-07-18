"""Panel/task-scoped split authority with split-neutral family intents.

The older family scaffold commits materialized row bundles before assignment.
Those bundles contain candidate/judge row digests, so they cannot serve as the
split-neutral preimage required by the benchmark freeze chain.  This module
adds a narrower authority layer whose pre-split input contains only generator
intent, family definitions, weights, and atomic grouping.

One global artifact must contain exactly 21 panels x 5 tasks = 105 assignment
authorities.  A second artifact partitions every assignment into exactly the
three benchmark splits.  The 315 task projections refer to 63 shared
panel/split partitions and exactly 315 semantic zipped shard slots
(21 panels x 3 splits x 5 pairs), never a 5 x 5 Cartesian grid.  These are
protocol slots, not materialized corpus shards.

All artifacts remain PRE-FREEZE scaffolds.  In particular, constructing them
does not upgrade the legacy materializer or supply external custody.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar, Iterable

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    domain_digest,
    validate_json_like,
)
from .evaluator import EvaluationTask
from .seed_protocol import (
    SEED_PROTOCOL_DIGEST,
    SEED_PROTOCOL_MANIFEST_BYTES,
    ZIPPED_REPLICATE_IDS,
)
from .world_registry import WORLD_REGISTRY


FAMILY_INTENT_PROTOCOL = "ucm-panel-task-split-neutral-family-intent/1"
FAMILY_ASSIGNMENT_PROTOCOL = "ucm-panel-task-family-assignment-authority/1"
GLOBAL_ASSIGNMENT_SET_PROTOCOL = "ucm-global-panel-task-family-authority-set/1"
PARTITION_PROTOCOL = "ucm-panel-task-split-partition-authority/1"
GLOBAL_PARTITION_SET_PROTOCOL = "ucm-global-panel-task-partition-authority-set/1"
STRATA_PREIMAGE_SET_PROTOCOL = "ucm-legacy-global-strata-root-byte-preimage-set/1"
FAMILY_DEFINITION_PROTOCOL = "ucm-split-neutral-family-definition-intent/1"
GENERATOR_INTENT_PROTOCOL = "ucm-split-neutral-generator-intent/1"
INTENT_POLICY_PROTOCOL = "ucm-split-neutral-family-intent-policy/1"
SPLIT_POLICY_PROTOCOL = "ucm-panel-family-split-policy/1"
SPLIT_SEED_CONTEXT_PROTOCOL = "ucm-panel-family-split-seed-context/1"
ZIPPED_PANEL_CONTEXT_PROTOCOL = "ucm-zipped-seed-pairing-protocol-context/1"

INCOMPLETE_CODE = "UCM-E003-HARNESS_INCOMPLETE"
PANEL_COUNT = 21
TASK_COUNT = 5
ASSIGNMENT_AUTHORITY_COUNT = PANEL_COUNT * TASK_COUNT
PARTITIONS_PER_AUTHORITY = 3
PARTITION_AUTHORITY_COUNT = ASSIGNMENT_AUTHORITY_COUNT * PARTITIONS_PER_AUTHORITY
ZIPPED_SHARD_SLOTS_PER_PARTITION = 5

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_IDENTITY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")

_IDENTITY_DOMAIN = b"UCM\0PANEL_TASK_AUTHORITY_IDENTITY_V1\0"
_UNIT_INTENT_DOMAIN = b"UCM\0SPLIT_NEUTRAL_FAMILY_UNIT_INTENT_V1\0"
_FAMILY_INTENT_DOMAIN = b"UCM\0PANEL_TASK_FAMILY_INTENT_V1\0"
_ASSIGNMENT_DOMAIN = b"UCM\0PANEL_TASK_FAMILY_ASSIGNMENT_V1\0"
_ASSIGNMENT_SET_DOMAIN = b"UCM\0GLOBAL_PANEL_TASK_ASSIGNMENT_SET_V1\0"
_PARTITION_DOMAIN = b"UCM\0PANEL_TASK_SPLIT_PARTITION_V1\0"
_PARTITION_SET_DOMAIN = b"UCM\0GLOBAL_PANEL_TASK_PARTITION_SET_V1\0"
_SHARD_DOMAIN = b"UCM\0ZIPPED_SEMANTIC_SHARD_SLOT_V1\0"
_STRATA_PREIMAGE_SET_DOMAIN = b"UCM\0PANEL_TASK_STRATA_PREIMAGE_SET_V1\0"
_PHYSICAL_ASSIGNMENT_DOMAIN = b"UCM\0PANEL_PHYSICAL_FAMILY_ASSIGNMENT_V1\0"
_SEMANTIC_PANEL_SPLIT_SLOT_DOMAIN = b"UCM\0PANEL_PHYSICAL_SPLIT_PARTITION_V1\0"
_ZIPPED_PANEL_CONTEXT_DOMAIN = b"UCM\0ZIPPED_SEED_PAIRING_PROTOCOL_CONTEXT_V1\0"

_STATUS_WIRE = {
    "status": "pre_freeze_scaffold",
    "freeze_grade_evidence": False,
    "benchmark_freeze_eligible": False,
    "legacy_materializer_status": "incomplete_not_upgradeable",
    "blockers": [
        {
            "code": INCOMPLETE_CODE,
            "artifact": "external_custody_and_atomic_publication",
            "detail": (
                "typed authority closure does not prove external custody, atomic "
                "publication, or legacy materializer readiness"
            ),
        },
        {
            "code": INCOMPLETE_CODE,
            "artifact": "post_freeze_seed_predecessor_chain",
            "detail": (
                "PRE-FREEZE binds seed protocol, replicate slots, and timing only; "
                "TRAIN5 precommit, hidden EVAL commitment, corpus finalization, and "
                "reveal verification do not yet exist"
            ),
        },
        {
            "code": INCOMPLETE_CODE,
            "artifact": "formal_scope_and_split_derivation_predecessors",
            "detail": (
                "formal scope exact bytes and split-seed reveal/derivation are not "
                "integrated; scope_digest and split commitment remain PRE-FREEZE "
                "placeholders rather than freeze authority"
            ),
        },
    ],
}

_LEGACY_STRATA_BLOCKERS = [
    *_STATUS_WIRE["blockers"],
    {
        "code": INCOMPLETE_CODE,
        "artifact": "legacy_strata_semantic_and_partition_authority",
        "detail": (
            "legacy roots prove exact-byte integrity only; independent old-schema "
            "semantic replay and panel/task/split/partition authority are not proven"
        ),
    },
]


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a lowercase sha256 digest")
    return value


def _identity(value: object, label: str) -> str:
    if type(value) is not str or _IDENTITY_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a canonical ASCII identity")
    return value


def _positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ProtocolViolation(f"{label} must be a positive integer")
    return value


def _exact_object(
    value: object, expected: frozenset[str], label: str
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    validate_json_like(value, path=label)
    actual = frozenset(value)
    if actual != expected:
        raise ProtocolViolation(
            f"{label} keys mismatch: missing={sorted(expected - actual)!r}, "
            f"extra={sorted(actual - expected)!r}"
        )
    return value


def _canonical_object(payload: object, label: str) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation(f"{label} must be exact bytes")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolViolation(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
        )
    except ProtocolViolation:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ProtocolViolation(f"{label} is not strict canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != payload:
        raise ProtocolViolation(f"{label} must be canonical JSON plus one LF")
    return value


def _parse_task(value: object, label: str = "task") -> EvaluationTask:
    if type(value) is not str:
        raise ProtocolViolation(f"{label} must be an exact string")
    try:
        return EvaluationTask(value)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} is not a code-owned benchmark task") from exc


def _expected_panel_task_keys() -> tuple[tuple[str, str, EvaluationTask], ...]:
    return tuple(
        (world_slot, panel.panel_id, task)
        for world_slot, declaration in WORLD_REGISTRY.items()
        for panel in declaration.panels
        for task in EvaluationTask
    )


EXPECTED_PANEL_TASK_KEYS = _expected_panel_task_keys()
if len(EXPECTED_PANEL_TASK_KEYS) != ASSIGNMENT_AUTHORITY_COUNT:
    raise RuntimeError(
        "UCM authority inventory must contain exactly 21 panels x 5 tasks"
    )


class AuthoritySplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class FamilyDefinitionIntent:
    definition_id: str
    member_intent_ids: tuple[str, ...]
    source_unit_semantic: str = "patient_family"

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "definition_id",
            "source_unit_semantic",
            "member_intent_ids",
        }
    )

    def __post_init__(self) -> None:
        _identity(self.definition_id, "family definition_id")
        if self.source_unit_semantic != "patient_family":
            raise ProtocolViolation(
                "family source_unit_semantic must be patient_family"
            )
        if (
            type(self.member_intent_ids) is not tuple
            or not self.member_intent_ids
            or any(type(item) is not str for item in self.member_intent_ids)
        ):
            raise ProtocolViolation("member_intent_ids must be a non-empty exact tuple")
        for item in self.member_intent_ids:
            _identity(item, "member_intent_id")
        if self.member_intent_ids != tuple(sorted(set(self.member_intent_ids))):
            raise ProtocolViolation("member_intent_ids must be unique canonical order")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": FAMILY_DEFINITION_PROTOCOL,
            "definition_id": self.definition_id,
            "source_unit_semantic": self.source_unit_semantic,
            "member_intent_ids": list(self.member_intent_ids),
        }

    @classmethod
    def from_wire(cls, value: object) -> "FamilyDefinitionIntent":
        row = _exact_object(value, cls._KEYS, "family definition intent")
        if row["schema_version"] != FAMILY_DEFINITION_PROTOCOL:
            raise ProtocolViolation("family definition intent protocol mismatch")
        if type(row["member_intent_ids"]) is not list:
            raise ProtocolViolation("member_intent_ids must be an exact list")
        return cls(
            row["definition_id"],
            tuple(row["member_intent_ids"]),
            row["source_unit_semantic"],
        )


@dataclass(frozen=True, slots=True)
class GeneratorIntent:
    generator_id: str
    generator_version: str
    generator_protocol: str
    population_recipe_id: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "generator_id",
            "generator_version",
            "generator_protocol",
            "population_recipe_id",
        }
    )

    def __post_init__(self) -> None:
        for value, label in (
            (self.generator_id, "generator_id"),
            (self.generator_version, "generator_version"),
            (self.generator_protocol, "generator_protocol"),
            (self.population_recipe_id, "population_recipe_id"),
        ):
            _identity(value, label)

    def to_wire(self) -> dict[str, str]:
        return {
            "schema_version": GENERATOR_INTENT_PROTOCOL,
            "generator_id": self.generator_id,
            "generator_version": self.generator_version,
            "generator_protocol": self.generator_protocol,
            "population_recipe_id": self.population_recipe_id,
        }

    @classmethod
    def from_wire(cls, value: object) -> "GeneratorIntent":
        row = _exact_object(value, cls._KEYS, "generator intent")
        if row["schema_version"] != GENERATOR_INTENT_PROTOCOL:
            raise ProtocolViolation("generator intent protocol mismatch")
        return cls(
            row["generator_id"],
            row["generator_version"],
            row["generator_protocol"],
            row["population_recipe_id"],
        )


@dataclass(frozen=True, slots=True)
class FamilyIntentPolicy:
    policy_id: str
    policy_version: str
    authority_stage: str = "before_split_and_materialization"
    row_payload_binding: str = "forbidden"

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "policy_id",
            "policy_version",
            "authority_stage",
            "row_payload_binding",
        }
    )

    def __post_init__(self) -> None:
        _identity(self.policy_id, "family intent policy_id")
        _identity(self.policy_version, "family intent policy_version")
        if self.authority_stage != "before_split_and_materialization":
            raise ProtocolViolation(
                "family intent authority_stage is not split-neutral"
            )
        if self.row_payload_binding != "forbidden":
            raise ProtocolViolation(
                "family intent policy must forbid row payload binding"
            )

    def to_wire(self) -> dict[str, str]:
        return {
            "schema_version": INTENT_POLICY_PROTOCOL,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "authority_stage": self.authority_stage,
            "row_payload_binding": self.row_payload_binding,
        }

    @classmethod
    def from_wire(cls, value: object) -> "FamilyIntentPolicy":
        row = _exact_object(value, cls._KEYS, "family intent policy")
        if row["schema_version"] != INTENT_POLICY_PROTOCOL:
            raise ProtocolViolation("family intent policy protocol mismatch")
        return cls(
            row["policy_id"],
            row["policy_version"],
            row["authority_stage"],
            row["row_payload_binding"],
        )


@dataclass(frozen=True, slots=True)
class SplitPolicyContext:
    policy_id: str
    policy_version: str
    assignment_unit: str = "atomic_family_group"
    balance_weight: str = "family_unit_weight"
    split_order: tuple[AuthoritySplit, ...] = tuple(AuthoritySplit)

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "policy_id",
            "policy_version",
            "assignment_unit",
            "balance_weight",
            "split_order",
        }
    )

    def __post_init__(self) -> None:
        _identity(self.policy_id, "split policy_id")
        _identity(self.policy_version, "split policy_version")
        if self.assignment_unit != "atomic_family_group":
            raise ProtocolViolation("split assignment_unit must be atomic_family_group")
        if self.balance_weight != "family_unit_weight":
            raise ProtocolViolation("split balance_weight must be family_unit_weight")
        if self.split_order != tuple(AuthoritySplit):
            raise ProtocolViolation(
                "split policy must bind canonical train/validation/test"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": SPLIT_POLICY_PROTOCOL,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "assignment_unit": self.assignment_unit,
            "balance_weight": self.balance_weight,
            "split_order": [split.value for split in self.split_order],
        }

    @classmethod
    def from_wire(cls, value: object) -> "SplitPolicyContext":
        row = _exact_object(value, cls._KEYS, "split policy context")
        if row["schema_version"] != SPLIT_POLICY_PROTOCOL:
            raise ProtocolViolation("split policy protocol mismatch")
        if type(row["split_order"]) is not list:
            raise ProtocolViolation("split_order must be an exact list")
        return cls(
            row["policy_id"],
            row["policy_version"],
            row["assignment_unit"],
            row["balance_weight"],
            tuple(_parse_split(item) for item in row["split_order"]),
        )


def _parse_split(value: object, label: str = "split") -> AuthoritySplit:
    if type(value) is not str:
        raise ProtocolViolation(f"{label} must be an exact string")
    try:
        return AuthoritySplit(value)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} is not train, validation, or test") from exc


@dataclass(frozen=True, slots=True)
class PanelTaskIdentity:
    benchmark_id: str
    benchmark_revision: str
    scope_digest: str
    world_slot: str
    panel_id: str
    task: EvaluationTask

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "benchmark_id",
            "benchmark_revision",
            "scope_digest",
            "world_slot",
            "panel_id",
            "task",
            "identity_digest",
        }
    )

    def __post_init__(self) -> None:
        _identity(self.benchmark_id, "benchmark_id")
        _identity(self.benchmark_revision, "benchmark_revision")
        _digest(self.scope_digest, "scope_digest")
        _identity(self.world_slot, "world_slot")
        _identity(self.panel_id, "panel_id")
        if type(self.task) is not EvaluationTask:
            raise ProtocolViolation("task must be EvaluationTask")
        declaration = WORLD_REGISTRY.get(self.world_slot)
        if declaration is None or self.panel_id not in {
            panel.panel_id for panel in declaration.panels
        }:
            raise ProtocolViolation("world_slot/panel_id is not a registry panel")

    def preimage_wire(self) -> dict[str, str]:
        return {
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "scope_digest": self.scope_digest,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "task": self.task.value,
        }

    @property
    def identity_digest(self) -> str:
        return domain_digest(
            _IDENTITY_DOMAIN, (canonical_json_bytes(self.preimage_wire()),)
        )

    def to_wire(self) -> dict[str, str]:
        return {**self.preimage_wire(), "identity_digest": self.identity_digest}

    @classmethod
    def from_wire(cls, value: object) -> "PanelTaskIdentity":
        row = _exact_object(value, cls._KEYS, "panel/task identity")
        result = cls(
            benchmark_id=row["benchmark_id"],
            benchmark_revision=row["benchmark_revision"],
            scope_digest=row["scope_digest"],
            world_slot=row["world_slot"],
            panel_id=row["panel_id"],
            task=_parse_task(row["task"]),
        )
        _digest(row["identity_digest"], "identity_digest")
        if row != result.to_wire():
            raise ProtocolViolation("panel/task identity digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class PanelPhysicalIdentity:
    benchmark_id: str
    benchmark_revision: str
    scope_digest: str
    world_slot: str
    panel_id: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "benchmark_id",
            "benchmark_revision",
            "scope_digest",
            "world_slot",
            "panel_id",
            "physical_identity_digest",
        }
    )

    @classmethod
    def from_task_identity(cls, identity: PanelTaskIdentity) -> "PanelPhysicalIdentity":
        if type(identity) is not PanelTaskIdentity:
            raise ProtocolViolation(
                "physical identity source must be PanelTaskIdentity"
            )
        return cls(
            identity.benchmark_id,
            identity.benchmark_revision,
            identity.scope_digest,
            identity.world_slot,
            identity.panel_id,
        )

    def __post_init__(self) -> None:
        # Re-enter the live registry contract through one arbitrary code-owned task.
        PanelTaskIdentity(
            self.benchmark_id,
            self.benchmark_revision,
            self.scope_digest,
            self.world_slot,
            self.panel_id,
            EvaluationTask.DIAGNOSIS,
        )

    def preimage_wire(self) -> dict[str, str]:
        return {
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "scope_digest": self.scope_digest,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
        }

    @property
    def physical_identity_digest(self) -> str:
        return domain_digest(
            _IDENTITY_DOMAIN,
            (b"physical-panel", canonical_json_bytes(self.preimage_wire())),
        )

    def to_wire(self) -> dict[str, str]:
        return {
            **self.preimage_wire(),
            "physical_identity_digest": self.physical_identity_digest,
        }

    @classmethod
    def from_wire(cls, value: object) -> "PanelPhysicalIdentity":
        row = _exact_object(value, cls._KEYS, "panel physical identity")
        result = cls(
            row["benchmark_id"],
            row["benchmark_revision"],
            row["scope_digest"],
            row["world_slot"],
            row["panel_id"],
        )
        _digest(row["physical_identity_digest"], "physical_identity_digest")
        if row != result.to_wire():
            raise ProtocolViolation("panel physical identity digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class SplitSeedCommitmentContext:
    panel_identity: PanelPhysicalIdentity
    split_policy: SplitPolicyContext
    commitment_scheme: str = "sha256_hidden_seed_commitment"
    commitment_stage: str = "before_family_assignment"

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "panel_identity",
            "split_policy",
            "commitment_scheme",
            "commitment_stage",
            "context_digest",
        }
    )

    def __post_init__(self) -> None:
        if type(self.panel_identity) is not PanelPhysicalIdentity:
            raise ProtocolViolation("split seed panel identity must be typed")
        if type(self.split_policy) is not SplitPolicyContext:
            raise ProtocolViolation("split seed policy must be typed")
        if self.commitment_scheme != "sha256_hidden_seed_commitment":
            raise ProtocolViolation("split seed commitment scheme is not code-owned")
        if self.commitment_stage != "before_family_assignment":
            raise ProtocolViolation("split seed commitment is not pre-assignment")

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": SPLIT_SEED_CONTEXT_PROTOCOL,
            "panel_identity": self.panel_identity.to_wire(),
            "split_policy": self.split_policy.to_wire(),
            "commitment_scheme": self.commitment_scheme,
            "commitment_stage": self.commitment_stage,
        }

    @property
    def context_digest(self) -> str:
        return digest_json(self.preimage_wire())

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "context_digest": self.context_digest}

    @classmethod
    def from_wire(cls, value: object) -> "SplitSeedCommitmentContext":
        row = _exact_object(value, cls._KEYS, "split seed commitment context")
        if row["schema_version"] != SPLIT_SEED_CONTEXT_PROTOCOL:
            raise ProtocolViolation("split seed context protocol mismatch")
        result = cls(
            PanelPhysicalIdentity.from_wire(row["panel_identity"]),
            SplitPolicyContext.from_wire(row["split_policy"]),
            row["commitment_scheme"],
            row["commitment_stage"],
        )
        _digest(row["context_digest"], "split seed context_digest")
        if row != result.to_wire():
            raise ProtocolViolation("split seed context digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class SplitNeutralFamilyUnitIntent:
    family_unit_id: str
    family_definition: FamilyDefinitionIntent
    generator_intent: GeneratorIntent
    atomic_group_id: str
    weight: int

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "family_unit_id",
            "family_definition",
            "generator_intent",
            "atomic_group_id",
            "weight",
            "unit_intent_digest",
        }
    )

    def __post_init__(self) -> None:
        _identity(self.family_unit_id, "family_unit_id")
        if type(self.family_definition) is not FamilyDefinitionIntent:
            raise ProtocolViolation("family definition intent must be typed")
        if type(self.generator_intent) is not GeneratorIntent:
            raise ProtocolViolation("generator intent must be typed")
        _identity(self.atomic_group_id, "atomic_group_id")
        _positive_int(self.weight, "family unit weight")

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "family_unit_id": self.family_unit_id,
            "family_definition": self.family_definition.to_wire(),
            "generator_intent": self.generator_intent.to_wire(),
            "atomic_group_id": self.atomic_group_id,
            "weight": self.weight,
        }

    @property
    def unit_intent_digest(self) -> str:
        return domain_digest(
            _UNIT_INTENT_DOMAIN, (canonical_json_bytes(self.preimage_wire()),)
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "unit_intent_digest": self.unit_intent_digest}

    @classmethod
    def from_wire(cls, value: object) -> "SplitNeutralFamilyUnitIntent":
        row = _exact_object(value, cls._KEYS, "split-neutral family unit")
        result = cls(
            family_unit_id=row["family_unit_id"],
            family_definition=FamilyDefinitionIntent.from_wire(
                row["family_definition"]
            ),
            generator_intent=GeneratorIntent.from_wire(row["generator_intent"]),
            atomic_group_id=row["atomic_group_id"],
            weight=row["weight"],
        )
        _digest(row["unit_intent_digest"], "unit_intent_digest")
        if row != result.to_wire():
            raise ProtocolViolation("family unit intent digest mismatch")
        return result


@dataclass(frozen=True, slots=True)
class SplitNeutralFamilyIntent:
    identity: PanelTaskIdentity
    intent_policy: FamilyIntentPolicy
    units: tuple[SplitNeutralFamilyUnitIntent, ...]

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "identity",
            "intent_policy",
            "units",
            "unit_count",
            "family_intent_digest",
        }
    )

    def __post_init__(self) -> None:
        if type(self.identity) is not PanelTaskIdentity:
            raise ProtocolViolation("family intent identity must be typed")
        if type(self.intent_policy) is not FamilyIntentPolicy:
            raise ProtocolViolation("family intent policy must be typed")
        if (
            type(self.units) is not tuple
            or not self.units
            or any(
                type(unit) is not SplitNeutralFamilyUnitIntent for unit in self.units
            )
        ):
            raise ProtocolViolation(
                "family intent units must be a non-empty typed tuple"
            )
        unit_ids = tuple(unit.family_unit_id for unit in self.units)
        unit_digests = tuple(unit.unit_intent_digest for unit in self.units)
        if len(unit_ids) != len(set(unit_ids)) or len(unit_digests) != len(
            set(unit_digests)
        ):
            raise ProtocolViolation("family intent units must be unique")
        if unit_digests != tuple(sorted(unit_digests)):
            raise ProtocolViolation(
                "family intent units must use canonical digest order"
            )

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": FAMILY_INTENT_PROTOCOL,
            "identity": self.identity.to_wire(),
            "intent_policy": self.intent_policy.to_wire(),
            "units": [unit.to_wire() for unit in self.units],
            "unit_count": len(self.units),
        }

    @property
    def family_intent_digest(self) -> str:
        return domain_digest(
            _FAMILY_INTENT_DOMAIN, (canonical_json_bytes(self.preimage_wire()),)
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            **self.preimage_wire(),
            "family_intent_digest": self.family_intent_digest,
        }

    @classmethod
    def from_wire(cls, value: object) -> "SplitNeutralFamilyIntent":
        row = _exact_object(value, cls._KEYS, "split-neutral family intent")
        if row["schema_version"] != FAMILY_INTENT_PROTOCOL:
            raise ProtocolViolation("family intent protocol mismatch")
        if type(row["units"]) is not list:
            raise ProtocolViolation("family intent units must be an exact list")
        result = cls(
            identity=PanelTaskIdentity.from_wire(row["identity"]),
            intent_policy=FamilyIntentPolicy.from_wire(row["intent_policy"]),
            units=tuple(
                SplitNeutralFamilyUnitIntent.from_wire(unit) for unit in row["units"]
            ),
        )
        if type(row["unit_count"]) is not int or row["unit_count"] != len(result.units):
            raise ProtocolViolation("family intent unit_count mismatch")
        _digest(row["family_intent_digest"], "family_intent_digest")
        if row != result.to_wire():
            raise ProtocolViolation("family intent canonical reconstruction mismatch")
        return result


@dataclass(frozen=True, slots=True)
class FamilyUnitSplitAssignment:
    unit_intent_digest: str
    split: AuthoritySplit

    _KEYS: ClassVar[frozenset[str]] = frozenset({"unit_intent_digest", "split"})

    def __post_init__(self) -> None:
        _digest(self.unit_intent_digest, "assignment unit_intent_digest")
        if type(self.split) is not AuthoritySplit:
            raise ProtocolViolation("assignment split must be AuthoritySplit")

    def to_wire(self) -> dict[str, str]:
        return {
            "unit_intent_digest": self.unit_intent_digest,
            "split": self.split.value,
        }

    @classmethod
    def from_wire(cls, value: object) -> "FamilyUnitSplitAssignment":
        row = _exact_object(value, cls._KEYS, "family unit split assignment")
        return cls(row["unit_intent_digest"], _parse_split(row["split"]))


@dataclass(frozen=True, slots=True)
class PanelTaskFamilyAssignmentAuthority:
    family_intent: SplitNeutralFamilyIntent
    split_policy: SplitPolicyContext
    split_seed_context: SplitSeedCommitmentContext
    split_seed_commitment: str
    assignments: tuple[FamilyUnitSplitAssignment, ...]

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "status",
            "freeze_grade_evidence",
            "benchmark_freeze_eligible",
            "legacy_materializer_status",
            "authority_role",
            "identity",
            "family_intent",
            "physical_assignment_preimage",
            "physical_assignment_digest",
            "split_policy",
            "split_seed_context",
            "split_seed_commitment",
            "assignments",
            "split_counts",
            "assignment_authority_digest",
            "blockers",
        }
    )

    def __post_init__(self) -> None:
        if type(self.family_intent) is not SplitNeutralFamilyIntent:
            raise ProtocolViolation("assignment family_intent must be typed")
        if type(self.split_policy) is not SplitPolicyContext:
            raise ProtocolViolation("assignment split_policy must be typed")
        if type(self.split_seed_context) is not SplitSeedCommitmentContext:
            raise ProtocolViolation("assignment split_seed_context must be typed")
        _digest(self.split_seed_commitment, "split_seed_commitment")
        physical_identity = PanelPhysicalIdentity.from_task_identity(
            self.family_intent.identity
        )
        if (
            self.split_seed_context.panel_identity != physical_identity
            or self.split_seed_context.split_policy != self.split_policy
        ):
            raise ProtocolViolation(
                "split seed context cross-splices panel identity or split policy"
            )
        if type(self.assignments) is not tuple or any(
            type(item) is not FamilyUnitSplitAssignment for item in self.assignments
        ):
            raise ProtocolViolation("assignments must be a typed tuple")
        assignment_digests = tuple(item.unit_intent_digest for item in self.assignments)
        expected = tuple(unit.unit_intent_digest for unit in self.family_intent.units)
        if assignment_digests != expected:
            raise ProtocolViolation(
                "assignment must exactly cover intent units in canonical order"
            )
        unit_by_digest = {
            unit.unit_intent_digest: unit for unit in self.family_intent.units
        }
        group_splits: dict[str, set[AuthoritySplit]] = {}
        for item in self.assignments:
            group_splits.setdefault(
                unit_by_digest[item.unit_intent_digest].atomic_group_id, set()
            ).add(item.split)
        if any(len(splits) != 1 for splits in group_splits.values()):
            raise ProtocolViolation("an atomic family group cannot cross splits")
        if {item.split for item in self.assignments} != set(AuthoritySplit):
            raise ProtocolViolation(
                "every assignment authority must populate all three splits"
            )

    def _split_counts_wire(self) -> dict[str, int]:
        return {
            split.value: sum(item.split is split for item in self.assignments)
            for split in AuthoritySplit
        }

    def physical_assignment_preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-panel-physical-family-assignment/1",
            "panel_identity": PanelPhysicalIdentity.from_task_identity(
                self.family_intent.identity
            ).to_wire(),
            "intent_policy": self.family_intent.intent_policy.to_wire(),
            "units": [unit.to_wire() for unit in self.family_intent.units],
            "unit_count": len(self.family_intent.units),
            "split_policy": self.split_policy.to_wire(),
            "split_seed_context": self.split_seed_context.to_wire(),
            "split_seed_commitment": self.split_seed_commitment,
            "assignments": [item.to_wire() for item in self.assignments],
            "split_counts": self._split_counts_wire(),
        }

    @property
    def physical_assignment_digest(self) -> str:
        return domain_digest(
            _PHYSICAL_ASSIGNMENT_DOMAIN,
            (canonical_json_bytes(self.physical_assignment_preimage_wire()),),
        )

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": FAMILY_ASSIGNMENT_PROTOCOL,
            **_STATUS_WIRE,
            "authority_role": "task_projection_of_panel_physical_assignment",
            "identity": self.family_intent.identity.to_wire(),
            "family_intent": self.family_intent.to_wire(),
            "physical_assignment_preimage": self.physical_assignment_preimage_wire(),
            "physical_assignment_digest": self.physical_assignment_digest,
            "split_policy": self.split_policy.to_wire(),
            "split_seed_context": self.split_seed_context.to_wire(),
            "split_seed_commitment": self.split_seed_commitment,
            "assignments": [item.to_wire() for item in self.assignments],
            "split_counts": self._split_counts_wire(),
        }

    @property
    def assignment_authority_digest(self) -> str:
        return domain_digest(
            _ASSIGNMENT_DOMAIN, (canonical_json_bytes(self.preimage_wire()),)
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            **self.preimage_wire(),
            "assignment_authority_digest": self.assignment_authority_digest,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @classmethod
    def from_wire(cls, value: object) -> "PanelTaskFamilyAssignmentAuthority":
        row = _exact_object(value, cls._KEYS, "panel/task family assignment")
        _validate_scaffold_fields(row, "panel/task family assignment")
        if row["schema_version"] != FAMILY_ASSIGNMENT_PROTOCOL:
            raise ProtocolViolation("family assignment protocol mismatch")
        if row["authority_role"] != "task_projection_of_panel_physical_assignment":
            raise ProtocolViolation("family assignment authority_role mismatch")
        if type(row["assignments"]) is not list:
            raise ProtocolViolation("assignments must be an exact list")
        result = cls(
            family_intent=SplitNeutralFamilyIntent.from_wire(row["family_intent"]),
            split_policy=SplitPolicyContext.from_wire(row["split_policy"]),
            split_seed_context=SplitSeedCommitmentContext.from_wire(
                row["split_seed_context"]
            ),
            split_seed_commitment=row["split_seed_commitment"],
            assignments=tuple(
                FamilyUnitSplitAssignment.from_wire(item) for item in row["assignments"]
            ),
        )
        if row["identity"] != result.family_intent.identity.to_wire():
            raise ProtocolViolation(
                "assignment identity does not bind the family intent"
            )
        _digest(row["physical_assignment_digest"], "physical_assignment_digest")
        if (
            row["physical_assignment_preimage"]
            != result.physical_assignment_preimage_wire()
            or row["physical_assignment_digest"] != result.physical_assignment_digest
        ):
            raise ProtocolViolation("physical assignment preimage/digest mismatch")
        _digest(row["assignment_authority_digest"], "assignment_authority_digest")
        if row != result.to_wire():
            raise ProtocolViolation(
                "family assignment canonical reconstruction mismatch"
            )
        return result

    @classmethod
    def from_canonical_bytes(
        cls, payload: bytes
    ) -> "PanelTaskFamilyAssignmentAuthority":
        return cls.from_wire(_canonical_object(payload, "panel/task family assignment"))


def _validate_scaffold_fields(row: dict[str, Any], label: str) -> None:
    for key, expected in _STATUS_WIRE.items():
        if row.get(key) != expected:
            raise ProtocolViolation(f"{label} {key} must remain code-owned PRE-FREEZE")


@dataclass(frozen=True, slots=True)
class GlobalPanelTaskFamilyAuthoritySet:
    authorities: tuple[PanelTaskFamilyAssignmentAuthority, ...]

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "status",
            "freeze_grade_evidence",
            "benchmark_freeze_eligible",
            "legacy_materializer_status",
            "benchmark_id",
            "benchmark_revision",
            "scope_digest",
            "panel_count",
            "task_count",
            "authority_count",
            "physical_assignment_count",
            "physical_assignments",
            "authorities",
            "authority_set_root",
            "blockers",
        }
    )

    def __post_init__(self) -> None:
        if type(self.authorities) is not tuple or any(
            type(item) is not PanelTaskFamilyAssignmentAuthority
            for item in self.authorities
        ):
            raise ProtocolViolation("global assignments must be a typed tuple")
        if len(self.authorities) != ASSIGNMENT_AUTHORITY_COUNT:
            raise ProtocolViolation(
                "global assignments must contain exactly 105 authorities"
            )
        identities = tuple(
            (
                item.family_intent.identity.world_slot,
                item.family_intent.identity.panel_id,
                item.family_intent.identity.task,
            )
            for item in self.authorities
        )
        if identities != EXPECTED_PANEL_TASK_KEYS:
            raise ProtocolViolation(
                "global assignments are missing, duplicated, reordered, or cross-panel"
            )
        roots = {
            (
                item.family_intent.identity.benchmark_id,
                item.family_intent.identity.benchmark_revision,
                item.family_intent.identity.scope_digest,
            )
            for item in self.authorities
        }
        if len(roots) != 1:
            raise ProtocolViolation(
                "global assignments do not share one benchmark scope"
            )
        physical_by_panel: dict[tuple[str, str], set[str]] = {}
        for item in self.authorities:
            identity = item.family_intent.identity
            physical_by_panel.setdefault(
                (identity.world_slot, identity.panel_id), set()
            ).add(item.physical_assignment_digest)
        if len(physical_by_panel) != PANEL_COUNT or any(
            len(digests) != 1 for digests in physical_by_panel.values()
        ):
            raise ProtocolViolation(
                "five task projections must share one physical assignment per panel"
            )

    def _physical_assignment_wires(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for item in self.authorities:
            identity = item.family_intent.identity
            key = (identity.world_slot, identity.panel_id)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "panel_identity": PanelPhysicalIdentity.from_task_identity(
                        identity
                    ).to_wire(),
                    "physical_assignment_preimage": (
                        item.physical_assignment_preimage_wire()
                    ),
                    "physical_assignment_digest": item.physical_assignment_digest,
                }
            )
        return result

    @property
    def common_identity(self) -> tuple[str, str, str]:
        item = self.authorities[0].family_intent.identity
        return item.benchmark_id, item.benchmark_revision, item.scope_digest

    def preimage_wire(self) -> dict[str, Any]:
        benchmark_id, benchmark_revision, scope_digest = self.common_identity
        return {
            "schema_version": GLOBAL_ASSIGNMENT_SET_PROTOCOL,
            **_STATUS_WIRE,
            "benchmark_id": benchmark_id,
            "benchmark_revision": benchmark_revision,
            "scope_digest": scope_digest,
            "panel_count": PANEL_COUNT,
            "task_count": TASK_COUNT,
            "authority_count": len(self.authorities),
            "physical_assignment_count": PANEL_COUNT,
            "physical_assignments": self._physical_assignment_wires(),
            "authorities": [item.to_wire() for item in self.authorities],
        }

    @property
    def authority_set_root(self) -> str:
        return domain_digest(
            _ASSIGNMENT_SET_DOMAIN, (canonical_json_bytes(self.preimage_wire()),)
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "authority_set_root": self.authority_set_root}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @classmethod
    def from_canonical_bytes(
        cls, payload: bytes
    ) -> "GlobalPanelTaskFamilyAuthoritySet":
        row = _exact_object(
            _canonical_object(payload, "global panel/task family authority set"),
            cls._KEYS,
            "global panel/task family authority set",
        )
        _validate_scaffold_fields(row, "global panel/task family authority set")
        if row["schema_version"] != GLOBAL_ASSIGNMENT_SET_PROTOCOL:
            raise ProtocolViolation("global assignment set protocol mismatch")
        if type(row["authorities"]) is not list:
            raise ProtocolViolation("global authorities must be an exact list")
        result = cls(
            tuple(
                PanelTaskFamilyAssignmentAuthority.from_wire(item)
                for item in row["authorities"]
            )
        )
        _digest(row["authority_set_root"], "authority_set_root")
        if row != result.to_wire():
            raise ProtocolViolation("global assignment set reconstruction mismatch")
        return result


@dataclass(frozen=True, slots=True)
class ZippedSeedPairingProtocolContext:
    """PRE-FREEZE seed semantics without raw TRAIN5/EVAL5 values.

    Actual TRAIN5 and EVAL5 values belong to the later confirmation chain.
    This context binds only the code-owned seed protocol bytes, five zipped
    replicate slots, and the required publication/reveal timing.
    """

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "seed_protocol_preimage",
            "seed_protocol_digest",
            "zipped_replicate_pairs",
            "timing",
            "raw_seed_values",
            "context_digest",
        }
    )

    @staticmethod
    def _timing_wire() -> dict[str, str]:
        return {
            "train5": "post_freeze_pre_training_precommit",
            "eval5": "post_candidate_seals_hidden_commitment",
            "eval5_reveal": "post_corpus_finalization",
            "redteam5": "evaluation_only_no_training_pairing",
        }

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": ZIPPED_PANEL_CONTEXT_PROTOCOL,
            "seed_protocol_preimage": _preimage_wire(SEED_PROTOCOL_MANIFEST_BYTES),
            "seed_protocol_digest": SEED_PROTOCOL_DIGEST,
            "zipped_replicate_pairs": [
                {
                    "training_replicate_id": training_id,
                    "evaluation_replicate_id": evaluation_id,
                }
                for training_id, evaluation_id in ZIPPED_REPLICATE_IDS
            ],
            "timing": self._timing_wire(),
            "raw_seed_values": "excluded_pre_freeze",
        }

    @property
    def context_digest(self) -> str:
        return domain_digest(
            _ZIPPED_PANEL_CONTEXT_DOMAIN,
            (canonical_json_bytes(self.preimage_wire()),),
        )

    @property
    def pairing_digest(self) -> str:
        return self.context_digest

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "context_digest": self.context_digest}

    @classmethod
    def from_wire(cls, value: object) -> "ZippedSeedPairingProtocolContext":
        row = _exact_object(value, cls._KEYS, "zipped seed pairing protocol context")
        if row["schema_version"] != ZIPPED_PANEL_CONTEXT_PROTOCOL:
            raise ProtocolViolation("zipped seed pairing protocol mismatch")
        seed_protocol_bytes = _decode_preimage_wire(
            row["seed_protocol_preimage"], "seed protocol preimage"
        )
        if seed_protocol_bytes != SEED_PROTOCOL_MANIFEST_BYTES:
            raise ProtocolViolation(
                "seed protocol predecessor bytes are not code-owned"
            )
        _digest(row["seed_protocol_digest"], "seed_protocol_digest")
        if row["seed_protocol_digest"] != SEED_PROTOCOL_DIGEST:
            raise ProtocolViolation("seed protocol predecessor digest mismatch")
        result = cls()
        _digest(row["context_digest"], "seed pairing protocol context_digest")
        if row != result.to_wire():
            raise ProtocolViolation(
                "seed pairing protocol context reconstruction mismatch"
            )
        return result


CODE_OWNED_ZIPPED_SEED_PAIRING_CONTEXT = ZippedSeedPairingProtocolContext()


@dataclass(frozen=True, slots=True)
class ZippedSemanticShardSlot:
    training_replicate_id: str
    evaluation_replicate_id: str
    shard_slot_digest: str

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {"training_replicate_id", "evaluation_replicate_id", "shard_slot_digest"}
    )

    @classmethod
    def for_partition(
        cls,
        partition_preimage_digest: str,
        training_replicate_id: str,
        evaluation_replicate_id: str,
    ) -> "ZippedSemanticShardSlot":
        _digest(partition_preimage_digest, "partition_preimage_digest")
        pair = (training_replicate_id, evaluation_replicate_id)
        if pair not in ZIPPED_REPLICATE_IDS:
            raise ProtocolViolation(
                "semantic shard slot is not one of the five canonical zipped pairs"
            )
        shard_slot_digest = domain_digest(
            _SHARD_DOMAIN,
            (
                partition_preimage_digest.encode("ascii"),
                training_replicate_id.encode("ascii"),
                evaluation_replicate_id.encode("ascii"),
            ),
        )
        return cls(training_replicate_id, evaluation_replicate_id, shard_slot_digest)

    def __post_init__(self) -> None:
        if (self.training_replicate_id, self.evaluation_replicate_id) not in (
            ZIPPED_REPLICATE_IDS
        ):
            raise ProtocolViolation(
                "semantic shard slot must be a canonical zipped pair"
            )
        _digest(self.shard_slot_digest, "shard_slot_digest")

    def to_wire(self) -> dict[str, str]:
        return {
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "shard_slot_digest": self.shard_slot_digest,
        }


def _partition_membership_preimage(
    *,
    assignment_authority_digest: str,
    identity_digest: str,
    split: AuthoritySplit,
    assigned_unit_intent_digests: tuple[str, ...],
    zipped_pairing_digest: str,
) -> dict[str, Any]:
    return {
        "assignment_authority_digest": assignment_authority_digest,
        "identity_digest": identity_digest,
        "split": split.value,
        "assigned_unit_intent_digests": list(assigned_unit_intent_digests),
        "zipped_pairing_digest": zipped_pairing_digest,
    }


def _semantic_panel_split_slot_preimage(
    *,
    physical_assignment_digest: str,
    panel_identity_digest: str,
    split: AuthoritySplit,
    assigned_unit_intent_digests: tuple[str, ...],
    zipped_pairing_digest: str,
) -> dict[str, Any]:
    return {
        "physical_assignment_digest": physical_assignment_digest,
        "panel_identity_digest": panel_identity_digest,
        "split": split.value,
        "assigned_unit_intent_digests": list(assigned_unit_intent_digests),
        "zipped_pairing_digest": zipped_pairing_digest,
    }


@dataclass(frozen=True, slots=True)
class PanelTaskSplitPartitionAuthority:
    assignment: PanelTaskFamilyAssignmentAuthority
    split: AuthoritySplit
    zipped_pairing: ZippedSeedPairingProtocolContext

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "status",
            "freeze_grade_evidence",
            "benchmark_freeze_eligible",
            "legacy_materializer_status",
            "identity",
            "split",
            "assignment_authority_preimage",
            "assignment_authority_digest",
            "physical_assignment_digest",
            "assigned_unit_intent_digests",
            "assigned_unit_count",
            "zipped_pairing_authority",
            "zipped_shard_slot_count",
            "zipped_shard_slots",
            "semantic_panel_split_slot_root",
            "partition_membership_root",
            "partition_authority_digest",
            "blockers",
        }
    )
    _PROJECTION_KEYS: ClassVar[frozenset[str]] = _KEYS - frozenset(
        {"assignment_authority_preimage"}
    )

    def __post_init__(self) -> None:
        if type(self.assignment) is not PanelTaskFamilyAssignmentAuthority:
            raise ProtocolViolation("partition assignment must be typed")
        if type(self.split) is not AuthoritySplit:
            raise ProtocolViolation("partition split must be AuthoritySplit")
        if type(self.zipped_pairing) is not ZippedSeedPairingProtocolContext:
            raise ProtocolViolation("partition zipped pairing must be typed")
        if not self.assigned_unit_intent_digests:
            raise ProtocolViolation("partition authority cannot be empty")

    @property
    def assigned_unit_intent_digests(self) -> tuple[str, ...]:
        return tuple(
            item.unit_intent_digest
            for item in self.assignment.assignments
            if item.split is self.split
        )

    @property
    def partition_membership_root(self) -> str:
        identity = self.assignment.family_intent.identity
        body = _partition_membership_preimage(
            assignment_authority_digest=self.assignment.assignment_authority_digest,
            identity_digest=identity.identity_digest,
            split=self.split,
            assigned_unit_intent_digests=self.assigned_unit_intent_digests,
            zipped_pairing_digest=self.zipped_pairing.pairing_digest,
        )
        return domain_digest(_PARTITION_DOMAIN, (canonical_json_bytes(body),))

    @property
    def semantic_panel_split_slot_root(self) -> str:
        physical_identity = PanelPhysicalIdentity.from_task_identity(
            self.assignment.family_intent.identity
        )
        body = _semantic_panel_split_slot_preimage(
            physical_assignment_digest=self.assignment.physical_assignment_digest,
            panel_identity_digest=physical_identity.physical_identity_digest,
            split=self.split,
            assigned_unit_intent_digests=self.assigned_unit_intent_digests,
            zipped_pairing_digest=self.zipped_pairing.pairing_digest,
        )
        return domain_digest(
            _SEMANTIC_PANEL_SPLIT_SLOT_DOMAIN, (canonical_json_bytes(body),)
        )

    @property
    def zipped_shard_slots(self) -> tuple[ZippedSemanticShardSlot, ...]:
        return tuple(
            ZippedSemanticShardSlot.for_partition(
                self.semantic_panel_split_slot_root, training_id, evaluation_id
            )
            for training_id, evaluation_id in ZIPPED_REPLICATE_IDS
        )

    def authority_preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": PARTITION_PROTOCOL,
            **_STATUS_WIRE,
            "identity": self.assignment.family_intent.identity.to_wire(),
            "split": self.split.value,
            "assignment_authority_digest": self.assignment.assignment_authority_digest,
            "physical_assignment_digest": self.assignment.physical_assignment_digest,
            "assigned_unit_intent_digests": list(self.assigned_unit_intent_digests),
            "assigned_unit_count": len(self.assigned_unit_intent_digests),
            "zipped_pairing_authority": self.zipped_pairing.to_wire(),
            "zipped_shard_slot_count": ZIPPED_SHARD_SLOTS_PER_PARTITION,
            "zipped_shard_slots": [item.to_wire() for item in self.zipped_shard_slots],
            "semantic_panel_split_slot_root": self.semantic_panel_split_slot_root,
            "partition_membership_root": self.partition_membership_root,
        }

    def projection_wire(self) -> dict[str, Any]:
        return {
            **self.authority_preimage_wire(),
            "partition_authority_digest": self.partition_authority_digest,
        }

    @property
    def partition_authority_digest(self) -> str:
        return domain_digest(
            _PARTITION_DOMAIN,
            (canonical_json_bytes(self.authority_preimage_wire()),),
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            **self.authority_preimage_wire(),
            "assignment_authority_preimage": _preimage_wire(
                self.assignment.canonical_bytes
            ),
            "partition_authority_digest": self.partition_authority_digest,
        }

    @classmethod
    def from_wire(
        cls,
        value: object,
        assignment_by_digest: dict[str, PanelTaskFamilyAssignmentAuthority]
        | None = None,
    ) -> "PanelTaskSplitPartitionAuthority":
        row = _exact_object(value, cls._KEYS, "panel/task split partition")
        _validate_scaffold_fields(row, "panel/task split partition")
        if row["schema_version"] != PARTITION_PROTOCOL:
            raise ProtocolViolation("partition protocol mismatch")
        assignment_digest = _digest(
            row["assignment_authority_digest"], "assignment_authority_digest"
        )
        assignment_bytes = _decode_preimage_wire(
            row["assignment_authority_preimage"],
            "partition assignment authority preimage",
        )
        assignment = PanelTaskFamilyAssignmentAuthority.from_canonical_bytes(
            assignment_bytes
        )
        if assignment.assignment_authority_digest != assignment_digest:
            raise ProtocolViolation("partition assignment digest/preimage mismatch")
        if assignment_by_digest is not None:
            global_assignment = assignment_by_digest.get(assignment_digest)
            if (
                global_assignment is None
                or global_assignment.canonical_bytes != assignment.canonical_bytes
            ):
                raise ProtocolViolation(
                    "partition references a foreign global assignment authority"
                )
        pairing = ZippedSeedPairingProtocolContext.from_wire(
            row["zipped_pairing_authority"]
        )
        result = cls(assignment, _parse_split(row["split"]), pairing)
        _digest(row["partition_membership_root"], "partition_membership_root")
        _digest(row["semantic_panel_split_slot_root"], "semantic_panel_split_slot_root")
        _digest(row["partition_authority_digest"], "partition_authority_digest")
        if row != result.to_wire():
            raise ProtocolViolation("partition canonical reconstruction mismatch")
        return result

    @classmethod
    def from_projection_wire(
        cls,
        value: object,
        assignment_by_digest: dict[str, PanelTaskFamilyAssignmentAuthority],
    ) -> "PanelTaskSplitPartitionAuthority":
        row = _exact_object(
            value, cls._PROJECTION_KEYS, "panel/task split partition projection"
        )
        _validate_scaffold_fields(row, "panel/task split partition projection")
        assignment_digest = _digest(
            row["assignment_authority_digest"], "assignment_authority_digest"
        )
        assignment = assignment_by_digest.get(assignment_digest)
        if assignment is None:
            raise ProtocolViolation(
                "partition projection references foreign assignment"
            )
        pairing = ZippedSeedPairingProtocolContext.from_wire(
            row["zipped_pairing_authority"]
        )
        result = cls(assignment, _parse_split(row["split"]), pairing)
        if row != result.projection_wire():
            raise ProtocolViolation("partition projection reconstruction mismatch")
        return result

    @classmethod
    def from_canonical_bytes(cls, payload: bytes) -> "PanelTaskSplitPartitionAuthority":
        return cls.from_wire(_canonical_object(payload, "panel/task split partition"))


@dataclass(frozen=True, slots=True)
class GlobalPanelTaskPartitionAuthoritySet:
    assignment_set: GlobalPanelTaskFamilyAuthoritySet
    zipped_pairing: ZippedSeedPairingProtocolContext
    partitions: tuple[PanelTaskSplitPartitionAuthority, ...]

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "status",
            "freeze_grade_evidence",
            "benchmark_freeze_eligible",
            "legacy_materializer_status",
            "assignment_set_preimage",
            "assignment_set_artifact_digest",
            "assignment_set_root",
            "zipped_pairing_authority",
            "authority_count",
            "partitions_per_authority",
            "partition_count",
            "zipped_shard_slots_per_partition",
            "semantic_panel_split_slot_count",
            "semantic_shard_slot_count",
            "physical_shard_materialization_authority",
            "semantic_panel_split_slots",
            "partitions",
            "partition_set_root",
            "blockers",
        }
    )

    def __post_init__(self) -> None:
        if type(self.assignment_set) is not GlobalPanelTaskFamilyAuthoritySet:
            raise ProtocolViolation("partition set assignment_set must be typed")
        if type(self.zipped_pairing) is not ZippedSeedPairingProtocolContext:
            raise ProtocolViolation("partition set zipped pairing must be typed")
        if type(self.partitions) is not tuple or any(
            type(item) is not PanelTaskSplitPartitionAuthority
            for item in self.partitions
        ):
            raise ProtocolViolation("partition set partitions must be a typed tuple")
        expected = tuple(
            (assignment.assignment_authority_digest, split)
            for assignment in self.assignment_set.authorities
            for split in AuthoritySplit
        )
        actual = tuple(
            (partition.assignment.assignment_authority_digest, partition.split)
            for partition in self.partitions
        )
        if actual != expected or len(self.partitions) != PARTITION_AUTHORITY_COUNT:
            raise ProtocolViolation(
                "partition set must exactly contain 105 authorities x 3 splits"
            )
        if any(
            partition.zipped_pairing != self.zipped_pairing
            for partition in self.partitions
        ):
            raise ProtocolViolation(
                "partition set contains a foreign pairing authority"
            )
        physical_by_panel_split: dict[tuple[str, str, AuthoritySplit], set[str]] = {}
        shard_sets: dict[tuple[str, str, AuthoritySplit], set[tuple[str, ...]]] = {}
        for partition in self.partitions:
            identity = partition.assignment.family_intent.identity
            key = (identity.world_slot, identity.panel_id, partition.split)
            physical_by_panel_split.setdefault(key, set()).add(
                partition.semantic_panel_split_slot_root
            )
            shard_sets.setdefault(key, set()).add(
                tuple(shard.shard_slot_digest for shard in partition.zipped_shard_slots)
            )
        if len(physical_by_panel_split) != PANEL_COUNT * PARTITIONS_PER_AUTHORITY:
            raise ProtocolViolation(
                "semantic panel/split slot inventory must be 21 x 3"
            )
        if any(len(roots) != 1 for roots in physical_by_panel_split.values()) or any(
            len(shards) != 1 for shards in shard_sets.values()
        ):
            raise ProtocolViolation(
                "five task partitions must project one shared semantic panel/split slot"
            )
        unique_semantic_shard_slots = {
            shard.shard_slot_digest
            for partition in self.partitions
            for shard in partition.zipped_shard_slots
        }
        if len(unique_semantic_shard_slots) != PANEL_COUNT * 3 * 5:
            raise ProtocolViolation(
                "semantic shard-slot inventory must be exactly 21 panels x 3 splits x 5 zipped pairs"
            )

    def _semantic_panel_split_slot_wires(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str, AuthoritySplit]] = set()
        for partition in self.partitions:
            identity = partition.assignment.family_intent.identity
            key = (identity.world_slot, identity.panel_id, partition.split)
            if key in seen:
                continue
            seen.add(key)
            result.append(
                {
                    "panel_identity": PanelPhysicalIdentity.from_task_identity(
                        identity
                    ).to_wire(),
                    "split": partition.split.value,
                    "physical_assignment_digest": (
                        partition.assignment.physical_assignment_digest
                    ),
                    "semantic_panel_split_slot_root": partition.semantic_panel_split_slot_root,
                    "zipped_shard_slots": [
                        shard.to_wire() for shard in partition.zipped_shard_slots
                    ],
                }
            )
        return result

    @classmethod
    def build(
        cls,
        assignment_set: GlobalPanelTaskFamilyAuthoritySet,
        zipped_pairing: ZippedSeedPairingProtocolContext,
    ) -> "GlobalPanelTaskPartitionAuthoritySet":
        return cls(
            assignment_set,
            zipped_pairing,
            tuple(
                PanelTaskSplitPartitionAuthority(assignment, split, zipped_pairing)
                for assignment in assignment_set.authorities
                for split in AuthoritySplit
            ),
        )

    def preimage_wire(self) -> dict[str, Any]:
        assignment_bytes = self.assignment_set.canonical_bytes
        return {
            "schema_version": GLOBAL_PARTITION_SET_PROTOCOL,
            **_STATUS_WIRE,
            "assignment_set_preimage": _preimage_wire(assignment_bytes),
            "assignment_set_artifact_digest": digest_bytes(assignment_bytes),
            "assignment_set_root": self.assignment_set.authority_set_root,
            "zipped_pairing_authority": self.zipped_pairing.to_wire(),
            "authority_count": ASSIGNMENT_AUTHORITY_COUNT,
            "partitions_per_authority": PARTITIONS_PER_AUTHORITY,
            "partition_count": len(self.partitions),
            "zipped_shard_slots_per_partition": ZIPPED_SHARD_SLOTS_PER_PARTITION,
            "semantic_panel_split_slot_count": PANEL_COUNT * PARTITIONS_PER_AUTHORITY,
            "semantic_shard_slot_count": PANEL_COUNT * 3 * 5,
            "physical_shard_materialization_authority": "not_claimed",
            "semantic_panel_split_slots": self._semantic_panel_split_slot_wires(),
            "partitions": [item.projection_wire() for item in self.partitions],
        }

    @property
    def partition_set_root(self) -> str:
        return domain_digest(
            _PARTITION_SET_DOMAIN, (canonical_json_bytes(self.preimage_wire()),)
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "partition_set_root": self.partition_set_root}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @classmethod
    def from_canonical_bytes(
        cls, payload: bytes
    ) -> "GlobalPanelTaskPartitionAuthoritySet":
        row = _exact_object(
            _canonical_object(payload, "global partition authority set"),
            cls._KEYS,
            "global partition authority set",
        )
        _validate_scaffold_fields(row, "global partition authority set")
        if row["schema_version"] != GLOBAL_PARTITION_SET_PROTOCOL:
            raise ProtocolViolation("global partition set protocol mismatch")
        assignment_bytes = _decode_preimage_wire(
            row["assignment_set_preimage"], "assignment set preimage"
        )
        assignment_set = GlobalPanelTaskFamilyAuthoritySet.from_canonical_bytes(
            assignment_bytes
        )
        if row["assignment_set_artifact_digest"] != digest_bytes(assignment_bytes):
            raise ProtocolViolation("assignment set artifact digest mismatch")
        if row["assignment_set_root"] != assignment_set.authority_set_root:
            raise ProtocolViolation("assignment set authority root mismatch")
        pairing = ZippedSeedPairingProtocolContext.from_wire(
            row["zipped_pairing_authority"]
        )
        if type(row["partitions"]) is not list:
            raise ProtocolViolation("partitions must be an exact list")
        assignment_by_digest = {
            item.assignment_authority_digest: item
            for item in assignment_set.authorities
        }
        result = cls(
            assignment_set,
            pairing,
            tuple(
                PanelTaskSplitPartitionAuthority.from_projection_wire(
                    item, assignment_by_digest
                )
                for item in row["partitions"]
            ),
        )
        _digest(row["partition_set_root"], "partition_set_root")
        if row != result.to_wire():
            raise ProtocolViolation("global partition set reconstruction mismatch")
        return result


def _preimage_wire(payload: bytes) -> dict[str, Any]:
    if type(payload) is not bytes or not payload:
        raise ProtocolViolation("authority preimage must be non-empty exact bytes")
    return {
        "encoding": "base64",
        "byte_length": len(payload),
        "canonical_bytes_base64": base64.b64encode(payload).decode("ascii"),
        "artifact_digest": digest_bytes(payload),
    }


def _decode_preimage_wire(value: object, label: str) -> bytes:
    row = _exact_object(
        value,
        frozenset(
            {"encoding", "byte_length", "canonical_bytes_base64", "artifact_digest"}
        ),
        label,
    )
    if row["encoding"] != "base64" or type(row["canonical_bytes_base64"]) is not str:
        raise ProtocolViolation(f"{label} encoding must be canonical base64")
    try:
        payload = base64.b64decode(
            row["canonical_bytes_base64"].encode("ascii"), validate=True
        )
    except (UnicodeEncodeError, ValueError, binascii.Error) as exc:
        raise ProtocolViolation(f"{label} base64 is invalid") from exc
    if base64.b64encode(payload).decode("ascii") != row["canonical_bytes_base64"]:
        raise ProtocolViolation(f"{label} base64 is non-canonical")
    if type(row["byte_length"]) is not int or row["byte_length"] != len(payload):
        raise ProtocolViolation(f"{label} byte_length mismatch")
    _digest(row["artifact_digest"], f"{label} artifact_digest")
    if row["artifact_digest"] != digest_bytes(payload):
        raise ProtocolViolation(f"{label} exact-byte digest mismatch")
    return payload


_STRATA_ROOT_FIELDS = {
    "public_strata_classifier": ("ucm-public-strata-classifier/1", "classifier_digest"),
    "pre_split_strata_allocation_manifest": (
        "ucm-pre-split-strata-allocation-manifest/1",
        "manifest_digest",
    ),
    "judge_allocation_authority": (
        "ucm-judge-strata-authority/2",
        "allocation_manifest_digest",
    ),
    "dual_channel_authority": (
        "ucm-dual-channel-strata-authority/2",
        "authority_digest",
    ),
    "strata_receipt_batch": ("ucm-dual-channel-strata-receipt-batch/2", "batch_digest"),
}
_STRATA_ROOT_IDS = tuple(_STRATA_ROOT_FIELDS)
_STRATA_ROOT_KEYS = {
    "public_strata_classifier": frozenset(
        {
            "schema_version",
            "status",
            "freeze_grade_evidence",
            "benchmark_freeze_eligible",
            "authority_role",
            "benchmark_id",
            "benchmark_revision",
            "world_slot",
            "classifier_id",
            "classifier_version",
            "classifier_source_digest",
            "definition_contract_digest",
            "definitions",
            "blockers",
            "classifier_digest",
        }
    ),
    "pre_split_strata_allocation_manifest": frozenset(
        {
            "schema_version",
            "status",
            "freeze_grade_evidence",
            "benchmark_freeze_eligible",
            "authority_role",
            "benchmark_id",
            "benchmark_revision",
            "world_slot",
            "family_source_digest",
            "generator_source_digest",
            "allocation_policy_digest",
            "allocation_schema_digest",
            "builder_id",
            "builder_version",
            "declared_slot_count",
            "entries",
            "w19_blocks",
            "w19_population_slot_union_digest",
            "blockers",
            "manifest_digest",
        }
    ),
    "judge_allocation_authority": frozenset(
        {
            "schema_version",
            "status",
            "freeze_grade_evidence",
            "benchmark_freeze_eligible",
            "authority_role",
            "benchmark_id",
            "benchmark_revision",
            "world_slot",
            "family_source_digest",
            "family_assignment_digest",
            "split_policy_digest",
            "generator_source_digest",
            "pre_split_allocation_manifest_digest",
            "allocation_source_manifest_digest",
            "allocation_policy_digest",
            "definition_source_digest",
            "definition_contract_digest",
            "family_materialization_ledger_digest",
            "materialization_receipt_root_digest",
            "definitions",
            "entries",
            "w19_blocks",
            "blockers",
            "allocation_manifest_digest",
        }
    ),
    "dual_channel_authority": frozenset(
        {
            "schema_version",
            "status",
            "freeze_grade_evidence",
            "benchmark_freeze_eligible",
            "benchmark_id",
            "benchmark_revision",
            "world_slot",
            "public_classifier_digest",
            "judge_allocation_manifest_digest",
            "family_source_digest",
            "family_assignment_digest",
            "split_policy_digest",
            "channel_definitions",
            "blockers",
            "authority_digest",
            "public",
            "judge",
        }
    ),
    "strata_receipt_batch": frozenset(
        {
            "schema_version",
            "status",
            "freeze_grade_evidence",
            "benchmark_freeze_eligible",
            "authority_digest",
            "allocation_manifest_digest",
            "expected_join_count",
            "receipt_count",
            "receipts",
            "blockers",
            "batch_digest",
        }
    ),
}


def _strata_root_body(root_id: str, wire: dict[str, Any]) -> dict[str, Any]:
    _, digest_field = _STRATA_ROOT_FIELDS[root_id]
    body = dict(wire)
    body.pop(digest_field, None)
    if root_id == "dual_channel_authority":
        body.pop("public", None)
        body.pop("judge", None)
    return body


@dataclass(frozen=True, slots=True)
class LegacyStrataRootBytePreimage:
    root_id: str
    canonical_bytes: bytes

    _KEYS: ClassVar[frozenset[str]] = frozenset({"root_id", "root_digest", "preimage"})

    def __post_init__(self) -> None:
        if self.root_id not in _STRATA_ROOT_FIELDS:
            raise ProtocolViolation(
                "strata root id is not one of the five code-owned roots"
            )
        wire = _canonical_object(self.canonical_bytes, f"{self.root_id} preimage")
        _exact_object(
            wire,
            _STRATA_ROOT_KEYS[self.root_id],
            f"{self.root_id} preimage",
        )
        expected_schema, digest_field = _STRATA_ROOT_FIELDS[self.root_id]
        if wire.get("schema_version") != expected_schema:
            raise ProtocolViolation(f"{self.root_id} schema_version mismatch")
        if (
            wire.get("status") != "pre_freeze_scaffold"
            or wire.get("freeze_grade_evidence") is not False
            or wire.get("benchmark_freeze_eligible") is not False
        ):
            raise ProtocolViolation(f"{self.root_id} must remain PRE-FREEZE")
        _digest(wire.get(digest_field), f"{self.root_id} {digest_field}")
        if wire[digest_field] != digest_json(_strata_root_body(self.root_id, wire)):
            raise ProtocolViolation(
                f"{self.root_id} root is not rebuilt from exact preimage"
            )

    @property
    def root_digest(self) -> str:
        wire = _canonical_object(self.canonical_bytes, f"{self.root_id} preimage")
        return wire[_STRATA_ROOT_FIELDS[self.root_id][1]]

    def to_wire(self) -> dict[str, Any]:
        return {
            "root_id": self.root_id,
            "root_digest": self.root_digest,
            "preimage": _preimage_wire(self.canonical_bytes),
        }

    @classmethod
    def from_wire(cls, value: object) -> "LegacyStrataRootBytePreimage":
        row = _exact_object(value, cls._KEYS, "exact strata root preimage")
        if type(row["root_id"]) is not str:
            raise ProtocolViolation("strata root_id must be an exact string")
        result = cls(
            row["root_id"],
            _decode_preimage_wire(row["preimage"], f"{row['root_id']} preimage"),
        )
        _digest(row["root_digest"], "strata root_digest")
        if row != result.to_wire():
            raise ProtocolViolation("strata root preimage reconstruction mismatch")
        return result


@dataclass(frozen=True, slots=True)
class LegacyGlobalStrataRootBytePreimageSet:
    benchmark_id: str
    benchmark_revision: str
    world_slot: str
    roots: tuple[LegacyStrataRootBytePreimage, ...]

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "schema_version",
            "status",
            "freeze_grade_evidence",
            "benchmark_freeze_eligible",
            "legacy_materializer_status",
            "authority_claim",
            "semantic_schema_replay",
            "panel_task_split_partition_authority",
            "benchmark_id",
            "benchmark_revision",
            "world_slot",
            "root_count",
            "roots",
            "root_set_digest",
            "blockers",
        }
    )

    def __post_init__(self) -> None:
        _identity(self.benchmark_id, "legacy strata benchmark_id")
        _identity(self.benchmark_revision, "legacy strata benchmark_revision")
        _identity(self.world_slot, "legacy strata world_slot")
        if self.world_slot not in WORLD_REGISTRY:
            raise ProtocolViolation("legacy strata world_slot is not in registry")
        if type(self.roots) is not tuple or any(
            type(root) is not LegacyStrataRootBytePreimage for root in self.roots
        ):
            raise ProtocolViolation("strata roots must be a typed tuple")
        if tuple(root.root_id for root in self.roots) != _STRATA_ROOT_IDS:
            raise ProtocolViolation(
                "strata preimages must contain the exact five roots in order"
            )
        wires = {
            root.root_id: _canonical_object(root.canonical_bytes, root.root_id)
            for root in self.roots
        }
        world_slots = {
            wire.get("world_slot") for wire in wires.values() if "world_slot" in wire
        }
        if world_slots != {self.world_slot}:
            raise ProtocolViolation("legacy strata roots do not share one world")
        benchmark_scopes = {
            (
                wire.get("benchmark_id"),
                wire.get("benchmark_revision"),
            )
            for wire in wires.values()
            if "benchmark_id" in wire
        }
        if benchmark_scopes != {(self.benchmark_id, self.benchmark_revision)}:
            raise ProtocolViolation("strata roots do not bind the benchmark identity")
        if (
            wires["dual_channel_authority"].get("public_classifier_digest")
            != self.roots[0].root_digest
        ):
            raise ProtocolViolation(
                "dual strata root does not bind public classifier preimage"
            )
        if (
            wires["dual_channel_authority"].get("public")
            != wires["public_strata_classifier"]
        ):
            raise ProtocolViolation(
                "dual strata nested public preimage is not the exact public root"
            )
        if (
            wires["judge_allocation_authority"].get(
                "pre_split_allocation_manifest_digest"
            )
            != self.roots[1].root_digest
        ):
            raise ProtocolViolation(
                "judge strata root does not bind allocation preimage"
            )
        if (
            wires["judge_allocation_authority"].get("allocation_source_manifest_digest")
            != self.roots[1].root_digest
        ):
            raise ProtocolViolation(
                "judge strata allocation-source root does not bind allocation preimage"
            )
        if (
            wires["dual_channel_authority"].get("judge_allocation_manifest_digest")
            != self.roots[2].root_digest
        ):
            raise ProtocolViolation("dual strata root does not bind judge preimage")
        if (
            wires["dual_channel_authority"].get("judge")
            != wires["judge_allocation_authority"]
        ):
            raise ProtocolViolation(
                "dual strata nested judge preimage is not the exact judge root"
            )
        if (
            wires["strata_receipt_batch"].get("authority_digest")
            != self.roots[3].root_digest
        ):
            raise ProtocolViolation(
                "strata receipt batch does not bind dual authority preimage"
            )
        if (
            wires["strata_receipt_batch"].get("allocation_manifest_digest")
            != self.roots[2].root_digest
        ):
            raise ProtocolViolation(
                "strata receipt batch does not bind judge authority preimage"
            )
        cross_root_fields = (
            "family_source_digest",
            "family_assignment_digest",
            "split_policy_digest",
        )
        for field_name in cross_root_fields:
            values = {
                wires[root_id].get(field_name)
                for root_id in (
                    "judge_allocation_authority",
                    "dual_channel_authority",
                )
            }
            if len(values) != 1 or None in values:
                raise ProtocolViolation(
                    f"strata roots cross-splice {field_name} authority"
                )
        if wires["pre_split_strata_allocation_manifest"].get(
            "family_source_digest"
        ) != wires["judge_allocation_authority"].get("family_source_digest"):
            raise ProtocolViolation(
                "strata allocation and judge roots cross-splice family source"
            )

    def preimage_wire(self) -> dict[str, Any]:
        return {
            "schema_version": STRATA_PREIMAGE_SET_PROTOCOL,
            **{key: value for key, value in _STATUS_WIRE.items() if key != "blockers"},
            "authority_claim": "exact_byte_integrity_only",
            "semantic_schema_replay": "not_proven",
            "panel_task_split_partition_authority": "not_claimed",
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "world_slot": self.world_slot,
            "root_count": len(self.roots),
            "roots": [root.to_wire() for root in self.roots],
            "blockers": _LEGACY_STRATA_BLOCKERS,
        }

    @property
    def root_set_digest(self) -> str:
        return domain_digest(
            _STRATA_PREIMAGE_SET_DOMAIN, (canonical_json_bytes(self.preimage_wire()),)
        )

    def to_wire(self) -> dict[str, Any]:
        return {**self.preimage_wire(), "root_set_digest": self.root_set_digest}

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @classmethod
    def from_canonical_bytes(
        cls, payload: bytes
    ) -> "LegacyGlobalStrataRootBytePreimageSet":
        row = _exact_object(
            _canonical_object(payload, "legacy global strata root byte preimage set"),
            cls._KEYS,
            "legacy global strata root byte preimage set",
        )
        for key, expected in _STATUS_WIRE.items():
            if key != "blockers" and row.get(key) != expected:
                raise ProtocolViolation("legacy strata set must remain PRE-FREEZE")
        if row["blockers"] != _LEGACY_STRATA_BLOCKERS:
            raise ProtocolViolation("legacy strata blockers are not code-owned")
        if row["schema_version"] != STRATA_PREIMAGE_SET_PROTOCOL:
            raise ProtocolViolation("strata root preimage set protocol mismatch")
        if (
            row["authority_claim"] != "exact_byte_integrity_only"
            or row["semantic_schema_replay"] != "not_proven"
            or row["panel_task_split_partition_authority"] != "not_claimed"
        ):
            raise ProtocolViolation("legacy strata authority claim is overstated")
        if type(row["roots"]) is not list:
            raise ProtocolViolation("strata roots must be an exact list")
        result = cls(
            row["benchmark_id"],
            row["benchmark_revision"],
            row["world_slot"],
            tuple(
                LegacyStrataRootBytePreimage.from_wire(root) for root in row["roots"]
            ),
        )
        _digest(row["root_set_digest"], "strata root_set_digest")
        if row != result.to_wire():
            raise ProtocolViolation("strata root preimage set reconstruction mismatch")
        return result

    @classmethod
    def from_typed_authorities(
        cls,
        public: object,
        allocation: object,
        judge: object,
        dual: object,
        batch: object,
    ) -> "LegacyGlobalStrataRootBytePreimageSet":
        from .strata_manifest import (
            DualChannelStrataAuthority,
            JudgeStrataAuthority,
            PreSplitStrataAllocationManifest,
            PublicClassifierAuthority,
            StrataReceiptBatch,
        )

        expected_types = (
            (public, PublicClassifierAuthority, "public classifier"),
            (allocation, PreSplitStrataAllocationManifest, "allocation manifest"),
            (judge, JudgeStrataAuthority, "judge authority"),
            (dual, DualChannelStrataAuthority, "dual authority"),
            (batch, StrataReceiptBatch, "strata receipt batch"),
        )
        for value, expected_type, label in expected_types:
            if type(value) is not expected_type:
                raise ProtocolViolation(f"legacy typed {label} has wrong type")
        if (
            dual.public is not public
            or dual.judge is not judge
            or judge.allocation_manifest is not allocation
            or batch.authority is not dual
        ):
            raise ProtocolViolation("legacy typed strata authorities do not exact-join")
        wires = (
            ("public_strata_classifier", public.to_wire()),
            ("pre_split_strata_allocation_manifest", allocation.to_wire()),
            ("judge_allocation_authority", judge.to_wire()),
            ("dual_channel_authority", dual.to_wire()),
            ("strata_receipt_batch", batch.to_wire()),
        )
        return cls(
            public.benchmark_id,
            public.benchmark_revision,
            public.world_slot,
            tuple(
                LegacyStrataRootBytePreimage(root_id, canonical_json_bytes(wire))
                for root_id, wire in wires
            ),
        )


def build_global_panel_task_family_authority_set(
    authorities: Iterable[PanelTaskFamilyAssignmentAuthority],
) -> GlobalPanelTaskFamilyAuthoritySet:
    by_key: dict[
        tuple[str, str, EvaluationTask], PanelTaskFamilyAssignmentAuthority
    ] = {}
    for authority in authorities:
        if type(authority) is not PanelTaskFamilyAssignmentAuthority:
            raise ProtocolViolation(
                "global authority builder accepts typed authorities only"
            )
        identity = authority.family_intent.identity
        key = (identity.world_slot, identity.panel_id, identity.task)
        if key in by_key:
            raise ProtocolViolation(
                "global authority builder received a duplicate identity"
            )
        by_key[key] = authority
    if set(by_key) != set(EXPECTED_PANEL_TASK_KEYS):
        missing = sorted(
            (world, panel, task.value)
            for world, panel, task in set(EXPECTED_PANEL_TASK_KEYS) - set(by_key)
        )
        extra = sorted(
            (world, panel, task.value)
            for world, panel, task in set(by_key) - set(EXPECTED_PANEL_TASK_KEYS)
        )
        raise ProtocolViolation(
            f"global authority inventory mismatch; missing={missing!r}, extra={extra!r}"
        )
    return GlobalPanelTaskFamilyAuthoritySet(
        tuple(by_key[key] for key in EXPECTED_PANEL_TASK_KEYS)
    )


def parse_global_panel_task_family_authority_set_bytes(
    payload: bytes,
) -> GlobalPanelTaskFamilyAuthoritySet:
    return GlobalPanelTaskFamilyAuthoritySet.from_canonical_bytes(payload)


def parse_panel_task_family_assignment_authority_bytes(
    payload: bytes,
) -> PanelTaskFamilyAssignmentAuthority:
    return PanelTaskFamilyAssignmentAuthority.from_canonical_bytes(payload)


def parse_panel_task_split_partition_authority_bytes(
    payload: bytes,
) -> PanelTaskSplitPartitionAuthority:
    return PanelTaskSplitPartitionAuthority.from_canonical_bytes(payload)


def parse_global_panel_task_partition_authority_set_bytes(
    payload: bytes,
) -> GlobalPanelTaskPartitionAuthoritySet:
    return GlobalPanelTaskPartitionAuthoritySet.from_canonical_bytes(payload)


def parse_legacy_global_strata_root_byte_preimage_set_bytes(
    payload: bytes,
) -> LegacyGlobalStrataRootBytePreimageSet:
    return LegacyGlobalStrataRootBytePreimageSet.from_canonical_bytes(payload)


__all__ = [
    "ASSIGNMENT_AUTHORITY_COUNT",
    "AuthoritySplit",
    "EXPECTED_PANEL_TASK_KEYS",
    "ZippedSeedPairingProtocolContext",
    "FamilyDefinitionIntent",
    "FamilyIntentPolicy",
    "FamilyUnitSplitAssignment",
    "GeneratorIntent",
    "GlobalPanelTaskFamilyAuthoritySet",
    "GlobalPanelTaskPartitionAuthoritySet",
    "LegacyGlobalStrataRootBytePreimageSet",
    "LegacyStrataRootBytePreimage",
    "PANEL_COUNT",
    "PARTITION_AUTHORITY_COUNT",
    "PanelTaskFamilyAssignmentAuthority",
    "PanelTaskIdentity",
    "PanelTaskSplitPartitionAuthority",
    "PanelPhysicalIdentity",
    "SplitPolicyContext",
    "SplitSeedCommitmentContext",
    "SplitNeutralFamilyIntent",
    "SplitNeutralFamilyUnitIntent",
    "TASK_COUNT",
    "ZIPPED_SHARD_SLOTS_PER_PARTITION",
    "build_global_panel_task_family_authority_set",
    "parse_global_panel_task_family_authority_set_bytes",
    "parse_global_panel_task_partition_authority_set_bytes",
    "parse_panel_task_family_assignment_authority_bytes",
    "parse_panel_task_split_partition_authority_bytes",
    "parse_legacy_global_strata_root_byte_preimage_set_bytes",
]
