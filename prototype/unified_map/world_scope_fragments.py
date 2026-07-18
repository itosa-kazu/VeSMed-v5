"""Live-derived typed W01--W20 fragments for the future eleven-axis scope.

The artifact in this module is deliberately PRE-FREEZE.  It is not a scope
manifest and cannot issue freeze authority.  Its parser accepts bytes only
when an exact rebuild from current code-owned declarations is byte-identical.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, TypeVar

from .candidate_protocol import Operation, RolloutResult
from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    validate_json_like,
)
from .evaluator import EvaluationTask
from .metric_configuration import (
    METRIC_TARGET_DOMAIN,
    METRIC_TARGET_SCHEMA,
    benchmark_v1_metric_target_registry,
)
from .schema import EventKind, PlanKind
from .scope_manifest import SCOPE_AXES
from .scope_transition_protocols import (
    DISTANCE_DERIVATION_SCHEMA,
    EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST,
    EXTENSION_TEMPLATE_SET_BYTES,
    EXTENSION_TEMPLATE_SET_SCHEMA,
    EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST,
    SPLIT_DERIVATION_ARTIFACT_DIGEST,
    SPLIT_DERIVATION_PROTOCOL_BYTES,
    SPLIT_DERIVATION_PROTOCOL_SCHEMA,
    SPLIT_DERIVATION_SEMANTIC_DIGEST,
    distance_derivation_contract_bytes,
    distance_derivation_contract_digest,
    parse_extension_template_set_bytes,
    parse_split_derivation_protocol_bytes,
)
from .seed_protocol import ZIPPED_REPLICATE_IDS
from .task_protocol import TASK_EXECUTION_TRUTH, TaskExecutionKind
from .world_registry import EXTENSION_WORLD_REGISTRY, WORLD_REGISTRY, PanelDeclaration
from .worlds.base import CounterfactualOracle, MicroWorld, PublicCatalog, WorldSplit

WORLD_SCOPE_FRAGMENT_SET_SCHEMA = "ucm-world-scope-fragment-set/3"
WORLD_SCOPE_FRAGMENT_DOMAIN = b"UCM_WORLD_SCOPE_FRAGMENT_SET_V3\0"
WORLD_SCOPE_FRAGMENT_AUTHORITY = "typed_world_semantics_only"
WORLD_SCOPE_BUILD_STATUS = "PRE-FREEZE"

EXPECTED_PANEL_IDENTITIES = (
    *((f"W{index:02d}", "primary") for index in range(1, 15)),
    ("W15", "W15A-randomized-identifiable"),
    ("W15", "W15B-observational-nonidentified"),
    *((f"W{index:02d}", "primary") for index in range(16, 21)),
)
EXPECTED_TASKS = (
    EvaluationTask.DIAGNOSIS,
    EvaluationTask.NATURAL_FORECAST,
    EvaluationTask.INTERVENTION,
    EvaluationTask.OOD,
    EvaluationTask.NEW_READOUT,
)
EXPECTED_SPLITS = (
    WorldSplit.TRAIN,
    WorldSplit.VALIDATION,
    WorldSplit.SEALED_TEST,
)


def _exact_object(value: object, keys: frozenset[str], label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    validate_json_like(value, path=label)
    actual = frozenset(value)
    if actual != keys:
        raise ProtocolViolation(
            f"{label} has missing/extra fields; missing={sorted(keys - actual)!r}, "
            f"extra={sorted(actual - keys)!r}"
        )
    return value


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    value.encode("utf-8", errors="strict")
    return value


def _strings(
    value: object, label: str, *, allow_empty: bool = False
) -> tuple[str, ...]:
    if type(value) is not list or (not allow_empty and not value):
        raise ProtocolViolation(f"{label} must be an exact list")
    result = tuple(_name(item, f"{label} item") for item in value)
    if len(result) != len(set(result)):
        raise ProtocolViolation(f"{label} values must be unique")
    return result


_EnumT = TypeVar("_EnumT", bound=Enum)


def _enum(enum_type: type[_EnumT], value: object, label: str) -> _EnumT:
    if type(value) is not str:
        raise ProtocolViolation(f"{label} must be an exact string")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} is not code-owned") from exc


def _decode(payload: object) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation("world scope fragment set must be exact bytes")

    def pairs(rows: list[tuple[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in rows:
            if key in out:
                raise ProtocolViolation(f"fragment set contains duplicate key {key!r}")
            out[key] = value
        return out

    try:
        value = json.loads(
            payload.decode("utf-8", errors="strict"), object_pairs_hook=pairs
        )
    except ProtocolViolation:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        ValueError,
        RecursionError,
    ) as exc:
        raise ProtocolViolation("fragment set is not strict UTF-8 JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != payload:
        raise ProtocolViolation(
            "fragment set is not canonical sorted compact JSON plus one LF"
        )
    return value


def _inert_object_bytes(value: object, label: str) -> bytes:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    validate_json_like(value, path=label)
    return canonical_json_bytes(value)


def _fresh_object(payload: bytes, label: str) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation(f"{label} internal preimage must be exact bytes")
    value = json.loads(payload)
    if type(value) is not dict or canonical_json_bytes(value) != payload:
        raise ProtocolViolation(f"{label} internal preimage is not canonical")
    return value


def _exact_preimage_payload(value: object, label: str) -> bytes:
    body = _exact_object(
        value,
        frozenset(
            {
                "schema_version",
                "label",
                "encoding",
                "byte_count",
                "digest",
                "payload_b64",
            }
        ),
        label,
    )
    if (
        body["schema_version"] != "ucm-exact-byte-preimage/1"
        or body["encoding"] != "base64"
        or type(body["byte_count"]) is not int
        or body["byte_count"] < 0
        or type(body["payload_b64"]) is not str
    ):
        raise ProtocolViolation(f"{label} metadata is invalid")
    _name(body["label"], f"{label} label")
    _name(body["digest"], f"{label} digest")
    try:
        payload = base64.b64decode(body["payload_b64"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProtocolViolation(f"{label} payload is not strict base64") from exc
    if len(payload) != body["byte_count"] or digest_bytes(payload) != body["digest"]:
        raise ProtocolViolation(f"{label} payload length/digest mismatch")
    return payload


class TaskApplicability(str, Enum):
    REQUIRED = "required"
    CONTROL = "control"
    NOT_APPLICABLE = "not_applicable"
    POST_SEAL_EXTENSION = "post_seal_extension"


class ApplicabilityBasis(str, Enum):
    PRIMARY = "primary_shared_state_task"
    OOD_REQUIRED = "designated_ood_positive_and_known_control_panel"
    OOD_CONTROL = "known_support_ood_specificity_control"
    NOVEL_READOUT = "independent_novel_readout_worker"


class ExtensionSemantic(str, Enum):
    NONE = "none"
    OPAQUE_POST_SEAL_SCOPE_SUCCESSOR = "opaque_post_seal_scope_successor"


class ExtensionTemplateRole(str, Enum):
    NEW_CHECK = "new_check_commitment_template"
    NEW_TREATMENT = "new_treatment_commitment_template"


class ProtocolReferenceKind(str, Enum):
    FAMILY_SPLIT_DERIVATION = "family_split_derivation"
    EXTENSION_TEMPLATE_SET = "extension_template_set"


@lru_cache(maxsize=2)
def _parsed_protocol_reference_contract(
    kind: ProtocolReferenceKind,
    *,
    split_payload: bytes = SPLIT_DERIVATION_PROTOCOL_BYTES,
    split_schema: str = SPLIT_DERIVATION_PROTOCOL_SCHEMA,
    split_artifact_digest: str = SPLIT_DERIVATION_ARTIFACT_DIGEST,
    split_semantic_digest: str = SPLIT_DERIVATION_SEMANTIC_DIGEST,
    split_parser: Any = parse_split_derivation_protocol_bytes,
    extension_payload: bytes = EXTENSION_TEMPLATE_SET_BYTES,
    extension_schema: str = EXTENSION_TEMPLATE_SET_SCHEMA,
    extension_artifact_digest: str = EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST,
    extension_semantic_digest: str = EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST,
    extension_parser: Any = parse_extension_template_set_bytes,
) -> tuple[str, str, str, str]:
    """Parse and cache the immutable code-owned predecessor identity."""
    if type(kind) is not ProtocolReferenceKind:
        raise ProtocolViolation("scope successor protocol reference kind drifted")
    if kind is ProtocolReferenceKind.FAMILY_SPLIT_DERIVATION:
        parsed = split_parser(split_payload)
        expected = (
            split_schema,
            split_artifact_digest,
            split_semantic_digest,
            "scope_transition_protocols.SPLIT_DERIVATION_PROTOCOL_BYTES",
        )
    else:
        parsed = extension_parser(extension_payload)
        expected = (
            extension_schema,
            extension_artifact_digest,
            extension_semantic_digest,
            "scope_transition_protocols.EXTENSION_TEMPLATE_SET_BYTES",
        )
    wire = parsed.to_wire()
    actual = (
        _name(wire["schema_version"], "predecessor protocol schema"),
        parsed.artifact_digest,
        parsed.semantic_digest,
        expected[3],
    )
    if actual != expected:
        raise ProtocolViolation("scope successor protocol identity drifted")
    return actual


def _exact_protocol_reference_contract(
    kind: ProtocolReferenceKind,
    *,
    split_payload: bytes = SPLIT_DERIVATION_PROTOCOL_BYTES,
    split_schema: str = SPLIT_DERIVATION_PROTOCOL_SCHEMA,
    split_artifact_digest: str = SPLIT_DERIVATION_ARTIFACT_DIGEST,
    split_semantic_digest: str = SPLIT_DERIVATION_SEMANTIC_DIGEST,
    split_parser: Any = parse_split_derivation_protocol_bytes,
    extension_payload: bytes = EXTENSION_TEMPLATE_SET_BYTES,
    extension_schema: str = EXTENSION_TEMPLATE_SET_SCHEMA,
    extension_artifact_digest: str = EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST,
    extension_semantic_digest: str = EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST,
    extension_parser: Any = parse_extension_template_set_bytes,
    parsed_identity_provider: Any = _parsed_protocol_reference_contract,
) -> tuple[str, str, str, str]:
    """Return an identity proven against the exact parsed predecessor bytes.

    Defaults capture the imported code-owned control plane at module load.  The
    explicit current-binding checks make later rebinding fail closed instead of
    letting a local alias supply both a claimed digest and its own expectation.
    """

    if type(kind) is not ProtocolReferenceKind:
        raise ProtocolViolation("scope successor protocol reference kind drifted")
    if _parsed_protocol_reference_contract is not parsed_identity_provider:
        raise ProtocolViolation("parsed predecessor identity provider drifted")
    if kind is ProtocolReferenceKind.FAMILY_SPLIT_DERIVATION:
        if (
            SPLIT_DERIVATION_PROTOCOL_BYTES != split_payload
            or SPLIT_DERIVATION_PROTOCOL_SCHEMA != split_schema
            or SPLIT_DERIVATION_ARTIFACT_DIGEST != split_artifact_digest
            or SPLIT_DERIVATION_SEMANTIC_DIGEST != split_semantic_digest
            or parse_split_derivation_protocol_bytes is not split_parser
        ):
            raise ProtocolViolation("split predecessor binding drifted")
    elif (
        EXTENSION_TEMPLATE_SET_BYTES != extension_payload
        or EXTENSION_TEMPLATE_SET_SCHEMA != extension_schema
        or EXTENSION_TEMPLATE_SET_ARTIFACT_DIGEST != extension_artifact_digest
        or EXTENSION_TEMPLATE_SET_SEMANTIC_DIGEST != extension_semantic_digest
        or parse_extension_template_set_bytes is not extension_parser
    ):
        raise ProtocolViolation("extension predecessor binding drifted")
    return parsed_identity_provider(kind)


def _exact_distance_derivation_declaration_schema(
    expected_schema: str = DISTANCE_DERIVATION_SCHEMA,
    contract_bytes_provider: Any = distance_derivation_contract_bytes,
) -> str:
    """Bind the declaration schema to the predecessor's live control plane."""

    if (
        DISTANCE_DERIVATION_SCHEMA != expected_schema
        or distance_derivation_contract_bytes is not contract_bytes_provider
        or type(expected_schema) is not str
        or not expected_schema
    ):
        raise ProtocolViolation("distance derivation declaration binding drifted")
    # The provider validates the predecessor executable-control-plane inventory.
    contract_bytes_provider()
    return expected_schema


class GapScope(str, Enum):
    GLOBAL = "global"
    PANEL = "panel"


class ScopeGapCode(str, Enum):
    P_POPULATION_SUPPORT = "P-population-support-not-typed"
    P_HOST_SUPPORT = "P-host-support-not-typed"
    P_MECHANISM_SUPPORT = "P-mechanism-support-not-typed"
    O_CHANNEL_KERNEL = "O-channel-generation-kernel-not-typed"
    O_MISSINGNESS = "O-missingness-process-not-typed"
    A_EFFECT_KERNEL = "A-physiologic-treatment-effect-kernel-not-typed"
    Q_RESULT_KERNEL = "Q-check-result-kernel-not-typed"
    PI_ADAPTIVE_RULE = "Pi-adaptive-rule-execution-not-typed"
    GAMMA_QUOTIENT = "Gamma-behavioral-granularity-not-typed"
    Y_OBSERVABLE_SCHEMA = "Y-observable-distribution-schema-not-typed"
    Y_OUTCOME_SCHEMA = "Y-outcome-distribution-schema-not-typed"
    Y_EVENT_CLOSURE = "Y-future-event-closure-not-typed"
    U_FORMULA = "U-utility-function-not-typed"
    D_NORMALIZATION = "D-normalization-scale-not-typed"
    D_CANDIDATE_SAME = "D-candidate-same-margin-not-typed"
    D_EQUIVALENT = "D-equivalence-margin-not-typed"
    D_DISTINGUISHABLE = "D-distinguishability-margin-not-typed"
    D_CATASTROPHIC = "D-catastrophic-margin-not-typed"
    D_OPTIMAL_TOLERANCE = "D-optimal-action-tolerance-not-typed"
    D_METRIC_TARGET_GAP = "D-code-owned-metric-target-gap"
    D_BEHAVIOR_DISTANCE_CLOSURE = "D-behavior-distance-source-closure-unbound"
    D_PAIR_CLASSIFIER_CLOSURE = "D-pair-classifier-source-closure-unbound"
    R_DATA_BUDGET = "R-training-data-budget-not-typed"
    R_COMPUTE_BUDGET = "R-resource-budget-not-typed"
    R_ISOLATION = "R-isolation-profile-not-typed"


@dataclass(frozen=True, slots=True)
class ExactProtocolReference:
    kind: ProtocolReferenceKind
    schema_version: str
    artifact_digest: str
    semantic_digest: str
    canonical_bytes_source: str

    def __post_init__(
        self, reference_validator: Any = _exact_protocol_reference_contract
    ) -> None:
        if _exact_protocol_reference_contract is not reference_validator:
            raise ProtocolViolation("exact protocol reference validator drifted")
        expected = reference_validator(self.kind)
        if (
            type(self.kind) is not ProtocolReferenceKind
            or (
                self.schema_version,
                self.artifact_digest,
                self.semantic_digest,
                self.canonical_bytes_source,
            )
            != expected
        ):
            raise ProtocolViolation("scope successor protocol reference drifted")

    def to_wire(self) -> dict[str, str]:
        return {
            "kind": self.kind.value,
            "schema_version": self.schema_version,
            "artifact_digest": self.artifact_digest,
            "semantic_digest": self.semantic_digest,
            "canonical_bytes_source": self.canonical_bytes_source,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ExactProtocolReference":
        body = _exact_object(
            value,
            frozenset(
                {
                    "kind",
                    "schema_version",
                    "artifact_digest",
                    "semantic_digest",
                    "canonical_bytes_source",
                }
            ),
            "exact protocol reference",
        )
        return cls(
            _enum(ProtocolReferenceKind, body["kind"], "protocol reference kind"),
            _name(body["schema_version"], "protocol reference schema"),
            _name(body["artifact_digest"], "protocol artifact digest"),
            _name(body["semantic_digest"], "protocol semantic digest"),
            _name(body["canonical_bytes_source"], "protocol bytes source"),
        )


@dataclass(frozen=True, slots=True)
class PostScopeAuthorityRequirement:
    """Typed nonblocking work that may only occur after base-scope closure."""

    schema_version: str
    requirement_id: str
    stage: str
    detail: str
    blocks_base_scope: bool

    def __post_init__(self) -> None:
        expected_prefix = {
            "ucm-post-scope-requirement/1": "UCM-SPLIT-POST-SCOPE-R",
            "ucm-successor-runtime-blocker/1": "UCM-EXTENSION-SUCCESSOR-B",
        }
        if (
            type(self.schema_version) is not str
            or self.schema_version not in expected_prefix
            or not self.requirement_id.startswith(expected_prefix[self.schema_version])
            or any(
                type(value) is not str or not value or value.strip() != value
                for value in (self.requirement_id, self.stage, self.detail)
            )
            or self.blocks_base_scope is not False
        ):
            raise ProtocolViolation(
                "post-scope authority requirement must be typed and base-S nonblocking"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "requirement_id": self.requirement_id,
            "stage": self.stage,
            "detail": self.detail,
            "blocks_base_scope": self.blocks_base_scope,
        }

    @classmethod
    def from_wire(cls, value: object) -> "PostScopeAuthorityRequirement":
        body = _exact_object(
            value,
            frozenset(
                {
                    "schema_version",
                    "requirement_id",
                    "stage",
                    "detail",
                    "blocks_base_scope",
                }
            ),
            "post-scope authority requirement",
        )
        if type(body["blocks_base_scope"]) is not bool:
            raise ProtocolViolation("post-scope blocks_base_scope must be bool")
        return cls(
            _name(body["schema_version"], "post-scope requirement schema"),
            _name(body["requirement_id"], "post-scope requirement id"),
            _name(body["stage"], "post-scope requirement stage"),
            _name(body["detail"], "post-scope requirement detail"),
            body["blocks_base_scope"],
        )


def _typed_post_scope_requirements(
    rows: object, label: str
) -> tuple[PostScopeAuthorityRequirement, ...]:
    if type(rows) is not list or not rows:
        raise ProtocolViolation(f"{label} must be a non-empty exact list")
    return tuple(PostScopeAuthorityRequirement.from_wire(row) for row in rows)


_SPLIT_POST_SCOPE_AUTHORITY_REQUIREMENTS = _typed_post_scope_requirements(
    parse_split_derivation_protocol_bytes(SPLIT_DERIVATION_PROTOCOL_BYTES).to_wire()[
        "post_scope_requirements"
    ],
    "split post-scope requirements",
)


@dataclass(frozen=True, slots=True)
class ExtensionCommitmentTemplate:
    """Base-scope requirement for an opaque extension, never its payload.

    The actual commitment value and revealed extension declaration are
    run-specific successors.  This object only states the template and
    chronology that a later, independently sealed transition must satisfy.
    """

    template_id: str
    role: ExtensionTemplateRole
    protocol_reference: ExactProtocolReference
    commitment_requirement: str
    reveal_gate: str
    source_closure_requirement: str
    closure_status: str
    base_scope_payload_rule: str
    transition_owner: str

    def __post_init__(self) -> None:
        expected_id = {
            ExtensionTemplateRole.NEW_CHECK: "W16-new-check-template",
            ExtensionTemplateRole.NEW_TREATMENT: "W17-new-treatment-template",
        }
        if (
            type(self.role) is not ExtensionTemplateRole
            or self.template_id != expected_id[self.role]
            or type(self.protocol_reference) is not ExactProtocolReference
            or self.protocol_reference.kind
            is not ProtocolReferenceKind.EXTENSION_TEMPLATE_SET
            or self.commitment_requirement
            != "opaque_hiding_commitment_before_candidate_model_state_seals"
            or self.reveal_gate
            != "exact_opening_only_after_candidate_model_state_seals"
            or self.source_closure_requirement
            != "exact_commit_reveal_schema_algorithm_and_source_preimage"
            or self.closure_status != "protocol_complete_predecessor"
            or self.base_scope_payload_rule
            != "actual_commitment_and_revealed_payload_excluded"
            or self.transition_owner != "R.extension_transition"
        ):
            raise ProtocolViolation(
                "extension commitment template is not the code-owned base contract"
            )

    def to_wire(self) -> dict[str, str]:
        return {
            "template_id": self.template_id,
            "role": self.role.value,
            "protocol_reference": self.protocol_reference.to_wire(),
            "commitment_requirement": self.commitment_requirement,
            "reveal_gate": self.reveal_gate,
            "source_closure_requirement": self.source_closure_requirement,
            "closure_status": self.closure_status,
            "base_scope_payload_rule": self.base_scope_payload_rule,
            "transition_owner": self.transition_owner,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ExtensionCommitmentTemplate":
        body = _exact_object(
            value,
            frozenset(
                {
                    "template_id",
                    "role",
                    "protocol_reference",
                    "commitment_requirement",
                    "reveal_gate",
                    "source_closure_requirement",
                    "closure_status",
                    "base_scope_payload_rule",
                    "transition_owner",
                }
            ),
            "extension commitment template",
        )
        return cls(
            _name(body["template_id"], "extension template id"),
            _enum(ExtensionTemplateRole, body["role"], "extension template role"),
            ExactProtocolReference.from_wire(body["protocol_reference"]),
            _name(body["commitment_requirement"], "extension commitment rule"),
            _name(body["reveal_gate"], "extension reveal gate"),
            _name(body["source_closure_requirement"], "extension source closure"),
            _name(body["closure_status"], "extension closure status"),
            _name(body["base_scope_payload_rule"], "extension base payload rule"),
            _name(body["transition_owner"], "extension transition owner"),
        )


@dataclass(frozen=True, slots=True)
class ChannelDeclaration:
    channel_id: str
    value_type: str
    unit: str
    valid_range: tuple[float, float] | None

    def to_wire(self) -> dict[str, Any]:
        return {
            "channel_id": self.channel_id,
            "value_type": self.value_type,
            "unit": self.unit,
            "valid_range": None if self.valid_range is None else list(self.valid_range),
        }

    @classmethod
    def from_wire(cls, value: object) -> "ChannelDeclaration":
        body = _exact_object(
            value,
            frozenset({"channel_id", "value_type", "unit", "valid_range"}),
            "channel",
        )
        raw = body["valid_range"]
        if raw is not None and (type(raw) is not list or len(raw) != 2):
            raise ProtocolViolation("channel valid_range must be null or pair")
        return cls(
            _name(body["channel_id"], "channel id"),
            _name(body["value_type"], "channel type"),
            _name(body["unit"], "channel unit"),
            None if raw is None else tuple(raw),
        )


@dataclass(frozen=True, slots=True)
class ActionDeclaration:
    action_id: str
    parameter_schema_bytes: bytes
    cost: float

    @property
    def parameter_schema(self) -> dict[str, Any]:
        return _fresh_object(self.parameter_schema_bytes, "action parameter_schema")

    def to_wire(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "parameter_schema": self.parameter_schema,
            "cost": self.cost,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ActionDeclaration":
        body = _exact_object(
            value, frozenset({"action_id", "parameter_schema", "cost"}), "action"
        )
        if type(body["parameter_schema"]) is not dict or type(body["cost"]) not in {
            int,
            float,
        }:
            raise ProtocolViolation("action schema/cost is invalid")
        return cls(
            _name(body["action_id"], "action id"),
            _inert_object_bytes(body["parameter_schema"], "action parameter_schema"),
            body["cost"],
        )

    @classmethod
    def from_live(
        cls, action_id: str, parameter_schema: dict[str, Any], cost: float
    ) -> "ActionDeclaration":
        return cls(
            action_id,
            _inert_object_bytes(parameter_schema, "action parameter_schema"),
            cost,
        )


@dataclass(frozen=True, slots=True)
class CheckDeclaration:
    check_id: str
    result_channels: tuple[str, ...]
    delay_support: tuple[int, int]
    cost: float

    def to_wire(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "result_channels": list(self.result_channels),
            "delay_support": list(self.delay_support),
            "cost": self.cost,
        }

    @classmethod
    def from_wire(cls, value: object) -> "CheckDeclaration":
        body = _exact_object(
            value,
            frozenset({"check_id", "result_channels", "delay_support", "cost"}),
            "check",
        )
        delay = body["delay_support"]
        if (
            type(delay) is not list
            or len(delay) != 2
            or any(type(x) is not int for x in delay)
        ):
            raise ProtocolViolation("check delay support must be integer pair")
        return cls(
            _name(body["check_id"], "check id"),
            _strings(body["result_channels"], "check channels"),
            tuple(delay),
            body["cost"],
        )


@dataclass(frozen=True, slots=True)
class PlannedActionDeclaration:
    offset: int
    action_id: str
    parameters_bytes: bytes

    @property
    def parameters(self) -> dict[str, Any]:
        return _fresh_object(self.parameters_bytes, "planned action parameters")

    def to_wire(self) -> dict[str, Any]:
        return {
            "offset": self.offset,
            "action_id": self.action_id,
            "parameters": self.parameters,
        }

    @classmethod
    def from_wire(cls, value: object) -> "PlannedActionDeclaration":
        body = _exact_object(
            value, frozenset({"offset", "action_id", "parameters"}), "planned action"
        )
        if (
            type(body["offset"]) is not int
            or body["offset"] < 0
            or type(body["parameters"]) is not dict
        ):
            raise ProtocolViolation("planned action is invalid")
        return cls(
            body["offset"],
            _name(body["action_id"], "planned action id"),
            _inert_object_bytes(body["parameters"], "planned action parameters"),
        )

    @classmethod
    def from_live(
        cls, offset: int, action_id: str, parameters: dict[str, Any]
    ) -> "PlannedActionDeclaration":
        return cls(
            offset,
            action_id,
            _inert_object_bytes(parameters, "planned action parameters"),
        )


@dataclass(frozen=True, slots=True)
class PolicyDeclaration:
    kind: PlanKind
    actions: tuple[PlannedActionDeclaration, ...]
    policy_digest: str | None
    adaptive_rule_ids: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "actions": [x.to_wire() for x in self.actions],
            "policy_digest": self.policy_digest,
            "adaptive_rule_ids": list(self.adaptive_rule_ids),
        }

    @classmethod
    def from_wire(cls, value: object) -> "PolicyDeclaration":
        body = _exact_object(
            value,
            frozenset({"kind", "actions", "policy_digest", "adaptive_rule_ids"}),
            "policy",
        )
        actions = body["actions"]
        if type(actions) is not list or (
            body["policy_digest"] is not None and type(body["policy_digest"]) is not str
        ):
            raise ProtocolViolation("policy actions/digest is invalid")
        return cls(
            _enum(PlanKind, body["kind"], "policy kind"),
            tuple(PlannedActionDeclaration.from_wire(x) for x in actions),
            body["policy_digest"],
            _strings(body["adaptive_rule_ids"], "adaptive rules", allow_empty=True),
        )


@dataclass(frozen=True, slots=True)
class PolicyHorizonDeclaration:
    horizon: int
    policies: tuple[PolicyDeclaration, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "horizon": self.horizon,
            "policies": [x.to_wire() for x in self.policies],
        }

    @classmethod
    def from_wire(cls, value: object) -> "PolicyHorizonDeclaration":
        body = _exact_object(
            value, frozenset({"horizon", "policies"}), "policy horizon"
        )
        if (
            type(body["horizon"]) is not int
            or body["horizon"] <= 0
            or type(body["policies"]) is not list
        ):
            raise ProtocolViolation("policy horizon is invalid")
        return cls(
            body["horizon"],
            tuple(PolicyDeclaration.from_wire(x) for x in body["policies"]),
        )


@dataclass(frozen=True, slots=True)
class SplitRoleDeclaration:
    generator_split: WorldSplit
    evaluation_split: str
    role: str
    population_count: int

    def to_wire(self) -> dict[str, Any]:
        return {
            "generator_split": self.generator_split.value,
            "evaluation_split": self.evaluation_split,
            "role": self.role,
            "population_count": self.population_count,
        }

    @classmethod
    def from_wire(cls, value: object) -> "SplitRoleDeclaration":
        body = _exact_object(
            value,
            frozenset(
                {"generator_split", "evaluation_split", "role", "population_count"}
            ),
            "split role",
        )
        if type(body["population_count"]) is not int or body["population_count"] <= 0:
            raise ProtocolViolation("split population count is invalid")
        return cls(
            _enum(WorldSplit, body["generator_split"], "generator split"),
            _name(body["evaluation_split"], "evaluation split"),
            _name(body["role"], "split role"),
            body["population_count"],
        )


@dataclass(frozen=True, slots=True)
class PopulationAxis:
    generation_interface: str
    generator_inputs: tuple[str, ...]
    episode_index_domain: str
    split_support: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "generation_interface": self.generation_interface,
            "generator_inputs": list(self.generator_inputs),
            "episode_index_domain": self.episode_index_domain,
            "split_support": list(self.split_support),
        }

    @classmethod
    def from_wire(cls, value: object) -> "PopulationAxis":
        body = _exact_object(
            value,
            frozenset(
                {
                    "generation_interface",
                    "generator_inputs",
                    "episode_index_domain",
                    "split_support",
                }
            ),
            "P axis",
        )
        return cls(
            _name(body["generation_interface"], "P interface"),
            _strings(body["generator_inputs"], "P inputs"),
            _name(body["episode_index_domain"], "P domain"),
            _strings(body["split_support"], "P splits"),
        )


@dataclass(frozen=True, slots=True)
class ObservationAxis:
    catalog_protocol: str
    history_protocol: str
    event_kinds: tuple[str, ...]
    time_fields: tuple[str, ...]
    visibility_rule: str
    channels: tuple[ChannelDeclaration, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "catalog_protocol": self.catalog_protocol,
            "history_protocol": self.history_protocol,
            "event_kinds": list(self.event_kinds),
            "time_fields": list(self.time_fields),
            "visibility_rule": self.visibility_rule,
            "channels": [x.to_wire() for x in self.channels],
        }

    @classmethod
    def from_wire(cls, value: object) -> "ObservationAxis":
        body = _exact_object(
            value,
            frozenset(
                {
                    "catalog_protocol",
                    "history_protocol",
                    "event_kinds",
                    "time_fields",
                    "visibility_rule",
                    "channels",
                }
            ),
            "O axis",
        )
        if type(body["channels"]) is not list:
            raise ProtocolViolation("O channels must be a list")
        return cls(
            _name(body["catalog_protocol"], "O catalog protocol"),
            _name(body["history_protocol"], "O history protocol"),
            _strings(body["event_kinds"], "O event kinds"),
            _strings(body["time_fields"], "O time fields"),
            _name(body["visibility_rule"], "O visibility"),
            tuple(ChannelDeclaration.from_wire(x) for x in body["channels"]),
        )


@dataclass(frozen=True, slots=True)
class ActionAxis:
    intervention_semantics: str
    actions: tuple[ActionDeclaration, ...]
    extension_commitment_template: ExtensionCommitmentTemplate | None

    def __post_init__(self) -> None:
        if self.extension_commitment_template is not None and (
            type(self.extension_commitment_template) is not ExtensionCommitmentTemplate
            or self.extension_commitment_template.role
            is not ExtensionTemplateRole.NEW_TREATMENT
        ):
            raise ProtocolViolation("A extension template must be new-treatment")

    def to_wire(self) -> dict[str, Any]:
        return {
            "intervention_semantics": self.intervention_semantics,
            "actions": [x.to_wire() for x in self.actions],
            "extension_commitment_template": (
                None
                if self.extension_commitment_template is None
                else self.extension_commitment_template.to_wire()
            ),
        }

    @classmethod
    def from_wire(cls, value: object) -> "ActionAxis":
        body = _exact_object(
            value,
            frozenset(
                {
                    "intervention_semantics",
                    "actions",
                    "extension_commitment_template",
                }
            ),
            "A axis",
        )
        if type(body["actions"]) is not list:
            raise ProtocolViolation("A actions must be a list")
        return cls(
            _name(body["intervention_semantics"], "A semantics"),
            tuple(ActionDeclaration.from_wire(x) for x in body["actions"]),
            (
                None
                if body["extension_commitment_template"] is None
                else ExtensionCommitmentTemplate.from_wire(
                    body["extension_commitment_template"]
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class CheckAxis:
    information_semantics: str
    checks: tuple[CheckDeclaration, ...]
    extension_commitment_template: ExtensionCommitmentTemplate | None

    def __post_init__(self) -> None:
        if self.extension_commitment_template is not None and (
            type(self.extension_commitment_template) is not ExtensionCommitmentTemplate
            or self.extension_commitment_template.role
            is not ExtensionTemplateRole.NEW_CHECK
        ):
            raise ProtocolViolation("Q extension template must be new-check")

    def to_wire(self) -> dict[str, Any]:
        return {
            "information_semantics": self.information_semantics,
            "checks": [x.to_wire() for x in self.checks],
            "extension_commitment_template": (
                None
                if self.extension_commitment_template is None
                else self.extension_commitment_template.to_wire()
            ),
        }

    @classmethod
    def from_wire(cls, value: object) -> "CheckAxis":
        body = _exact_object(
            value,
            frozenset(
                {
                    "information_semantics",
                    "checks",
                    "extension_commitment_template",
                }
            ),
            "Q axis",
        )
        if type(body["checks"]) is not list:
            raise ProtocolViolation("Q checks must be a list")
        return cls(
            _name(body["information_semantics"], "Q semantics"),
            tuple(CheckDeclaration.from_wire(x) for x in body["checks"]),
            (
                None
                if body["extension_commitment_template"] is None
                else ExtensionCommitmentTemplate.from_wire(
                    body["extension_commitment_template"]
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class PolicyAxis:
    policy_source: str
    by_horizon: tuple[PolicyHorizonDeclaration, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "policy_source": self.policy_source,
            "by_horizon": [x.to_wire() for x in self.by_horizon],
        }

    @classmethod
    def from_wire(cls, value: object) -> "PolicyAxis":
        body = _exact_object(
            value, frozenset({"policy_source", "by_horizon"}), "Pi axis"
        )
        if type(body["by_horizon"]) is not list:
            raise ProtocolViolation("Pi horizons must be a list")
        return cls(
            _name(body["policy_source"], "Pi source"),
            tuple(PolicyHorizonDeclaration.from_wire(x) for x in body["by_horizon"]),
        )


@dataclass(frozen=True, slots=True)
class HorizonAxis:
    horizons: tuple[int, ...]
    time_unit: str

    def to_wire(self) -> dict[str, Any]:
        return {"horizons": list(self.horizons), "time_unit": self.time_unit}

    @classmethod
    def from_wire(cls, value: object) -> "HorizonAxis":
        body = _exact_object(value, frozenset({"horizons", "time_unit"}), "Tau axis")
        raw = body["horizons"]
        if (
            type(raw) is not list
            or not raw
            or any(type(x) is not int or x <= 0 for x in raw)
        ):
            raise ProtocolViolation("Tau horizons are invalid")
        return cls(tuple(raw), _name(body["time_unit"], "Tau unit"))


@dataclass(frozen=True, slots=True)
class DiagnosisAxis:
    labels: tuple[str, ...]
    label_source: str
    unknown_label_supported: bool

    def to_wire(self) -> dict[str, Any]:
        return {
            "labels": list(self.labels),
            "label_source": self.label_source,
            "unknown_label_supported": self.unknown_label_supported,
        }

    @classmethod
    def from_wire(cls, value: object) -> "DiagnosisAxis":
        body = _exact_object(
            value,
            frozenset({"labels", "label_source", "unknown_label_supported"}),
            "Gamma axis",
        )
        if type(body["unknown_label_supported"]) is not bool:
            raise ProtocolViolation("Gamma unknown support must be bool")
        return cls(
            _strings(body["labels"], "Gamma labels"),
            _name(body["label_source"], "Gamma source"),
            body["unknown_label_supported"],
        )


@dataclass(frozen=True, slots=True)
class FutureAxis:
    rollout_response_fields: tuple[str, ...]
    judge_oracle_fields: tuple[str, ...]
    observable_ids: tuple[str, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "rollout_response_fields": list(self.rollout_response_fields),
            "judge_oracle_fields": list(self.judge_oracle_fields),
            "observable_ids": list(self.observable_ids),
        }

    @classmethod
    def from_wire(cls, value: object) -> "FutureAxis":
        body = _exact_object(
            value,
            frozenset(
                {"rollout_response_fields", "judge_oracle_fields", "observable_ids"}
            ),
            "Y axis",
        )
        return cls(
            _strings(body["rollout_response_fields"], "Y response fields"),
            _strings(body["judge_oracle_fields"], "Y oracle fields"),
            _strings(body["observable_ids"], "Y observables"),
        )


@dataclass(frozen=True, slots=True)
class UtilityAxis:
    judge_utility_field: str
    candidate_utility_field: str
    preference_order: str
    treatment_costs: tuple[tuple[str, float], ...]
    check_costs: tuple[tuple[str, float], ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "judge_utility_field": self.judge_utility_field,
            "candidate_utility_field": self.candidate_utility_field,
            "preference_order": self.preference_order,
            "treatment_costs": [
                {"item_id": k, "cost": v} for k, v in self.treatment_costs
            ],
            "check_costs": [{"item_id": k, "cost": v} for k, v in self.check_costs],
        }

    @staticmethod
    def _costs(value: object, label: str) -> tuple[tuple[str, float], ...]:
        if type(value) is not list:
            raise ProtocolViolation(f"{label} must be a list")
        out = []
        for row in value:
            body = _exact_object(row, frozenset({"item_id", "cost"}), label)
            if type(body["cost"]) not in {int, float}:
                raise ProtocolViolation(f"{label} cost must be numeric")
            out.append((_name(body["item_id"], f"{label} id"), body["cost"]))
        return tuple(out)

    @classmethod
    def from_wire(cls, value: object) -> "UtilityAxis":
        body = _exact_object(
            value,
            frozenset(
                {
                    "judge_utility_field",
                    "candidate_utility_field",
                    "preference_order",
                    "treatment_costs",
                    "check_costs",
                }
            ),
            "U axis",
        )
        return cls(
            _name(body["judge_utility_field"], "U judge field"),
            _name(body["candidate_utility_field"], "U candidate field"),
            _name(body["preference_order"], "U order"),
            cls._costs(body["treatment_costs"], "treatment costs"),
            cls._costs(body["check_costs"], "check costs"),
        )


@dataclass(frozen=True, slots=True)
class DistanceAxis:
    metric_target_schema: str
    metric_target_domain_hex: str
    metric_target_artifact_digest: str
    metric_target_digest: str
    metric_target_source: str
    panel_metric_applicability_status: str
    applicable_measurement_ids: tuple[str, ...]
    calibration_bins: int
    behavior_distance_id: str
    pair_classifier_id: str
    margin_sources: tuple[tuple[str, str], ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "metric_target_schema": self.metric_target_schema,
            "metric_target_domain_hex": self.metric_target_domain_hex,
            "metric_target_artifact_digest": self.metric_target_artifact_digest,
            "metric_target_digest": self.metric_target_digest,
            "metric_target_source": self.metric_target_source,
            "panel_metric_applicability_status": self.panel_metric_applicability_status,
            "applicable_measurement_ids": list(self.applicable_measurement_ids),
            "calibration_bins": self.calibration_bins,
            "behavior_distance_id": self.behavior_distance_id,
            "pair_classifier_id": self.pair_classifier_id,
            "margin_sources": {k: v for k, v in self.margin_sources},
        }

    @classmethod
    def from_wire(cls, value: object) -> "DistanceAxis":
        body = _exact_object(
            value,
            frozenset(
                {
                    "metric_target_schema",
                    "metric_target_domain_hex",
                    "metric_target_artifact_digest",
                    "metric_target_digest",
                    "metric_target_source",
                    "panel_metric_applicability_status",
                    "applicable_measurement_ids",
                    "calibration_bins",
                    "behavior_distance_id",
                    "pair_classifier_id",
                    "margin_sources",
                }
            ),
            "D axis",
        )
        margins = body["margin_sources"]
        if type(margins) is not dict or type(body["calibration_bins"]) is not int:
            raise ProtocolViolation("D metric config is invalid")
        return cls(
            _name(body["metric_target_schema"], "D target schema"),
            _name(body["metric_target_domain_hex"], "D target domain"),
            _name(body["metric_target_artifact_digest"], "D artifact digest"),
            _name(body["metric_target_digest"], "D target digest"),
            _name(body["metric_target_source"], "D target source"),
            _name(
                body["panel_metric_applicability_status"],
                "D panel applicability status",
            ),
            _strings(
                body["applicable_measurement_ids"],
                "D applicable measurement ids",
                allow_empty=True,
            ),
            body["calibration_bins"],
            _name(body["behavior_distance_id"], "D distance id"),
            _name(body["pair_classifier_id"], "D classifier id"),
            tuple(
                (_name(k, "D margin key"), _name(v, "D margin source"))
                for k, v in margins.items()
            ),
        )


@dataclass(frozen=True, slots=True)
class ZippedSlotTiming:
    training_replicate_id: str
    evaluation_replicate_id: str
    training_commitment_stage: str
    evaluation_commitment_stage: str
    evaluation_reveal_stage: str

    def __post_init__(self) -> None:
        pair = (self.training_replicate_id, self.evaluation_replicate_id)
        if (
            pair not in ZIPPED_REPLICATE_IDS
            or self.training_commitment_stage != "post_freeze_pre_training_precommit"
            or self.evaluation_commitment_stage
            != "post_candidate_seals_hidden_commitment"
            or self.evaluation_reveal_stage != "post_corpus_finalization"
        ):
            raise ProtocolViolation("zipped slot timing is not code-owned")

    def to_wire(self) -> dict[str, str]:
        return {
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "training_commitment_stage": self.training_commitment_stage,
            "evaluation_commitment_stage": self.evaluation_commitment_stage,
            "evaluation_reveal_stage": self.evaluation_reveal_stage,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ZippedSlotTiming":
        body = _exact_object(
            value,
            frozenset(
                {
                    "training_replicate_id",
                    "evaluation_replicate_id",
                    "training_commitment_stage",
                    "evaluation_commitment_stage",
                    "evaluation_reveal_stage",
                }
            ),
            "zipped slot timing",
        )
        return cls(
            _name(body["training_replicate_id"], "training replicate id"),
            _name(body["evaluation_replicate_id"], "evaluation replicate id"),
            _name(body["training_commitment_stage"], "training commitment stage"),
            _name(
                body["evaluation_commitment_stage"],
                "evaluation commitment stage",
            ),
            _name(body["evaluation_reveal_stage"], "evaluation reveal stage"),
        )


@dataclass(frozen=True, slots=True)
class FamilySplitDerivationRequirement:
    """Scope-owned protocol requirement, not an assignment/partition result."""

    protocol_reference: ExactProtocolReference
    closure_status: str
    panel_count: int
    task_count: int
    split_count: int
    physical_assignment_count: int
    task_assignment_projection_count: int
    physical_partition_count: int
    task_partition_projection_count: int
    zipped_slots_per_physical_partition: int
    semantic_zipped_slot_count: int
    zipped_slots: tuple[ZippedSlotTiming, ...]
    derivation_chronology: tuple[str, ...]
    post_scope_derivation_stage: str
    post_scope_derivation_rule: str
    post_scope_authority_requirements: tuple[PostScopeAuthorityRequirement, ...]
    scope_forbidden_inputs: tuple[str, ...]

    _CHRONOLOGY = (
        "full_semantic_freeze_authorized",
        "materialize_split_neutral_family_intents",
        "publish_hidden_split_seed_commitment_before_assignment",
        "derive_family_atomic_assignments_and_partitions_bound_to_same_S",
        "reveal_and_verify_split_seed_opening",
        "exact_keyed_rederivation_comparison",
    )
    _FORBIDDEN = (
        "actual_family_assignment_root",
        "actual_split_partition_root",
        "actual_panel_assignment_or_partition_digest",
        "actual_split_seed_commitment_or_opening",
        "actual_TRAIN5_or_EVAL5_tuple",
        "actual_TRAIN5_PRECOMMIT_or_EVAL5_commitment_value",
        "actual_run_specific_raw_seed_value_or_digest",
    )

    def __post_init__(self) -> None:
        expected_slots = tuple(
            ZippedSlotTiming(
                training_id,
                evaluation_id,
                "post_freeze_pre_training_precommit",
                "post_candidate_seals_hidden_commitment",
                "post_corpus_finalization",
            )
            for training_id, evaluation_id in ZIPPED_REPLICATE_IDS
        )
        if (
            type(self.protocol_reference) is not ExactProtocolReference
            or self.protocol_reference.kind
            is not ProtocolReferenceKind.FAMILY_SPLIT_DERIVATION
            or self.closure_status != "protocol_complete_predecessor"
            or (self.panel_count, self.task_count, self.split_count)
            != (
                len(EXPECTED_PANEL_IDENTITIES),
                len(EXPECTED_TASKS),
                len(EXPECTED_SPLITS),
            )
            or self.physical_assignment_count != self.panel_count
            or self.task_assignment_projection_count
            != self.panel_count * self.task_count
            or self.physical_partition_count != self.panel_count * self.split_count
            or self.task_partition_projection_count
            != self.panel_count * self.task_count * self.split_count
            or self.zipped_slots_per_physical_partition != len(ZIPPED_REPLICATE_IDS)
            or self.semantic_zipped_slot_count
            != self.panel_count
            * self.split_count
            * self.zipped_slots_per_physical_partition
            or self.zipped_slots != expected_slots
            or self.derivation_chronology != self._CHRONOLOGY
            or self.post_scope_derivation_stage != "post_scope_authorization"
            or self.post_scope_derivation_rule
            != "actual_authorities_bind_S_one_way_and_never_feed_back_into_S"
            or self.post_scope_authority_requirements
            != _SPLIT_POST_SCOPE_AUTHORITY_REQUIREMENTS
            or self.scope_forbidden_inputs != self._FORBIDDEN
        ):
            raise ProtocolViolation(
                "family/split derivation requirement is not the code-owned base contract"
            )

    @property
    def post_scope_authority_requirement_count(self) -> int:
        return len(self.post_scope_authority_requirements)

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol_reference": self.protocol_reference.to_wire(),
            "closure_status": self.closure_status,
            "projection_shape": {
                "panel_count": self.panel_count,
                "task_count": self.task_count,
                "split_count": self.split_count,
                "physical_assignment_count": self.physical_assignment_count,
                "task_assignment_projection_count": (
                    self.task_assignment_projection_count
                ),
                "physical_partition_count": self.physical_partition_count,
                "task_partition_projection_count": (
                    self.task_partition_projection_count
                ),
                "zipped_slots_per_physical_partition": (
                    self.zipped_slots_per_physical_partition
                ),
                "semantic_zipped_slot_count": self.semantic_zipped_slot_count,
            },
            "zipped_slots": [x.to_wire() for x in self.zipped_slots],
            "derivation_chronology": list(self.derivation_chronology),
            "post_scope_derivation_stage": self.post_scope_derivation_stage,
            "post_scope_derivation_rule": self.post_scope_derivation_rule,
            "post_scope_authority_requirement_count": (
                self.post_scope_authority_requirement_count
            ),
            "post_scope_authority_requirements": [
                x.to_wire() for x in self.post_scope_authority_requirements
            ],
            "scope_forbidden_inputs": list(self.scope_forbidden_inputs),
        }

    @classmethod
    def from_wire(cls, value: object) -> "FamilySplitDerivationRequirement":
        body = _exact_object(
            value,
            frozenset(
                {
                    "protocol_reference",
                    "closure_status",
                    "projection_shape",
                    "zipped_slots",
                    "derivation_chronology",
                    "post_scope_derivation_stage",
                    "post_scope_derivation_rule",
                    "post_scope_authority_requirement_count",
                    "post_scope_authority_requirements",
                    "scope_forbidden_inputs",
                }
            ),
            "family/split derivation requirement",
        )
        shape = _exact_object(
            body["projection_shape"],
            frozenset(
                {
                    "panel_count",
                    "task_count",
                    "split_count",
                    "physical_assignment_count",
                    "task_assignment_projection_count",
                    "physical_partition_count",
                    "task_partition_projection_count",
                    "zipped_slots_per_physical_partition",
                    "semantic_zipped_slot_count",
                }
            ),
            "family/split projection shape",
        )
        if (
            any(type(shape[key]) is not int for key in shape)
            or type(body["zipped_slots"]) is not list
            or type(body["post_scope_authority_requirement_count"]) is not int
            or type(body["post_scope_authority_requirements"]) is not list
            or body["post_scope_authority_requirement_count"]
            != len(body["post_scope_authority_requirements"])
        ):
            raise ProtocolViolation("family/split shape or zipped slots are invalid")
        return cls(
            ExactProtocolReference.from_wire(body["protocol_reference"]),
            _name(body["closure_status"], "family/split closure status"),
            shape["panel_count"],
            shape["task_count"],
            shape["split_count"],
            shape["physical_assignment_count"],
            shape["task_assignment_projection_count"],
            shape["physical_partition_count"],
            shape["task_partition_projection_count"],
            shape["zipped_slots_per_physical_partition"],
            shape["semantic_zipped_slot_count"],
            tuple(ZippedSlotTiming.from_wire(x) for x in body["zipped_slots"]),
            _strings(body["derivation_chronology"], "family/split chronology"),
            _name(
                body["post_scope_derivation_stage"],
                "family/split post-scope stage",
            ),
            _name(
                body["post_scope_derivation_rule"],
                "family/split post-scope rule",
            ),
            tuple(
                PostScopeAuthorityRequirement.from_wire(x)
                for x in body["post_scope_authority_requirements"]
            ),
            _strings(
                body["scope_forbidden_inputs"],
                "family/split forbidden scope inputs",
            ),
        )


def _extension_protocol_contract(
    role: ExtensionTemplateRole,
    distance_schema_provider: Any = _exact_distance_derivation_declaration_schema,
) -> dict[str, Any]:
    if _exact_distance_derivation_declaration_schema is not distance_schema_provider:
        raise ProtocolViolation("distance derivation schema provider drifted")
    world_slot = {
        ExtensionTemplateRole.NEW_CHECK: "W16",
        ExtensionTemplateRole.NEW_TREATMENT: "W17",
    }[role]
    wire = parse_extension_template_set_bytes(EXTENSION_TEMPLATE_SET_BYTES).to_wire()
    protocol = wire["protocol"]
    template = next(
        row for row in protocol["templates"] if row["world_slot"] == world_slot
    )
    actual_diff = protocol["external_successor_artifacts"]["actual_scope_diff"]
    receipt = protocol["external_successor_artifacts"]["successor_receipt"]
    distance_preimage = protocol["distance_derivation_contract"]
    distance_contract_bytes = _exact_preimage_payload(
        distance_preimage, "extension distance derivation contract"
    )
    distance_contract = _fresh_object(
        distance_contract_bytes, "extension distance derivation contract"
    )
    distance_declaration_schema = distance_schema_provider()
    scope_spec_preimage = template["extension_scope_spec_contract"]
    scope_spec_contract_bytes = _exact_preimage_payload(
        scope_spec_preimage, f"{world_slot} extension scope spec contract"
    )
    scope_spec_contract = _fresh_object(
        scope_spec_contract_bytes, f"{world_slot} extension scope spec contract"
    )
    isolation = protocol["isolation"]
    chronology = tuple(protocol["chronology"])
    required_stages = (
        "authorize_base_S_and_template",
        "seal_primary_result_root_before_extension_reveal",
        "reveal_only_after_candidate_model_and_state_seals",
        "derive_full_expanded_state_space_S_prime",
        "compute_exact_actual_scope_diff",
        "run_state_only_first_extension_query",
        "allow_optional_measured_migration_only_after_scope_insufficient",
        "emit_extension_only_score_without_rewriting_primary_scores",
    )
    if (
        wire["scope_binding_status"] != "not_bound"
        or wire["gap_count"] != 0
        or wire["gaps"] != []
        or wire["successor_blocker_count"] != len(wire["successor_blockers"])
        or not wire["successor_blockers"]
        or any(
            row["blocks_base_scope"] is not False for row in wire["successor_blockers"]
        )
        or template["successor_axis_coverage"] != "all11"
        or tuple(template["successor_axis_order"]) != SCOPE_AXES
        or tuple(template["required_changed_axes"])
        != (
            {
                ExtensionTemplateRole.NEW_CHECK: "Q",
                ExtensionTemplateRole.NEW_TREATMENT: "A",
            }[role],
        )
        or not set(template["required_changed_axes"]).issubset(
            template["role_specific_allowed_changed_axes"]
        )
        or template["actual_expanded_scope"] != "excluded"
        or template["actual_axis_diff"] != "excluded"
        or scope_spec_preimage["label"] != f"{world_slot}-extension-scope-spec-contract"
        or scope_spec_contract["schema_version"]
        != "ucm-extension-scope-spec-contract/1"
        or tuple(scope_spec_contract["required_changed_axes"])
        != tuple(template["required_changed_axes"])
        or tuple(scope_spec_contract["allowed_non_D_changed_axes"])
        != tuple(template["role_specific_allowed_changed_axes"])
        or scope_spec_contract["typed_spec_schema"]
        != actual_diff["extension_scope_spec_schema"]
        or scope_spec_contract["parser"] != actual_diff["extension_scope_spec_parser"]
        or scope_spec_contract["successor_deriver"] != actual_diff["successor_deriver"]
        or scope_spec_contract["no_op_patch"] != "forbidden"
        or distance_preimage["schema_version"] != "ucm-exact-byte-preimage/1"
        or distance_preimage["encoding"] != "base64"
        or distance_preimage["label"] != "extension-distance-derivation-contract"
        or distance_contract_bytes != distance_derivation_contract_bytes()
        or distance_contract["schema_version"]
        != "ucm-extension-distance-derivation-contract/1"
        or template["distance_derivation_contract_digest"]
        != distance_derivation_contract_digest()
        or distance_contract["metric_registry_schema"] != METRIC_TARGET_SCHEMA
        or distance_contract["metric_registry_domain_hex"] != METRIC_TARGET_DOMAIN.hex()
        or actual_diff["storage"] != "external_not_embedded_in_template"
        or tuple(actual_diff["successor_axis_order"]) != SCOPE_AXES
        or receipt["storage"] != "external_not_embedded_in_template"
        or receipt["primary_aggregate_eligible"] is not False
        or receipt["successor_runtime_eligible"] is not False
        or receipt["runtime_binding_status"] != "successor_runtime_not_integrated"
        or receipt["first_query_envelope_schema"]
        != "ucm-extension-first-query-envelope/1"
        or receipt["first_result_envelope_schema"]
        != "ucm-extension-first-result-envelope/1"
        or isolation["extension_result_namespace"]
        != "separate_extension_only_namespace"
        or isolation["mixed_scope_aggregation"] != "forbidden"
        or isolation["source_target_scope_join"] != "fail_closed_exact_identity_join"
        or any(stage not in chronology for stage in required_stages)
        or tuple(chronology.index(stage) for stage in required_stages)
        != tuple(sorted(chronology.index(stage) for stage in required_stages))
    ):
        raise ProtocolViolation(
            "scope-independent extension protocol contradicts base scope"
        )
    return {
        "role_axis": {
            ExtensionTemplateRole.NEW_CHECK: "Q",
            ExtensionTemplateRole.NEW_TREATMENT: "A",
        }[role],
        "successor_axis_coverage": tuple(template["successor_axis_order"]),
        "required_changed_axes": tuple(template["required_changed_axes"]),
        "allowed_changed_axes": tuple(template["allowed_changed_axes"]),
        "role_specific_allowed_changed_axes": tuple(
            template["role_specific_allowed_changed_axes"]
        ),
        "chronology": chronology,
        "extension_scope_spec_contract_preimage_schema": scope_spec_preimage[
            "schema_version"
        ],
        "extension_scope_spec_contract_preimage_label": scope_spec_preimage["label"],
        "extension_scope_spec_contract_preimage_encoding": scope_spec_preimage[
            "encoding"
        ],
        "extension_scope_spec_contract_schema": scope_spec_contract["schema_version"],
        "extension_scope_spec_contract_byte_count": scope_spec_preimage["byte_count"],
        "extension_scope_spec_contract_artifact_digest": scope_spec_preimage["digest"],
        "extension_scope_spec_schema": actual_diff["extension_scope_spec_schema"],
        "extension_scope_spec_parser": actual_diff["extension_scope_spec_parser"],
        "successor_scope_deriver": actual_diff["successor_deriver"],
        "distance_derivation_declaration_schema": distance_declaration_schema,
        "distance_derivation_contract_preimage_schema": distance_preimage[
            "schema_version"
        ],
        "distance_derivation_contract_preimage_label": distance_preimage["label"],
        "distance_derivation_contract_preimage_encoding": distance_preimage["encoding"],
        "distance_derivation_contract_schema": distance_contract["schema_version"],
        "distance_derivation_contract_byte_count": distance_preimage["byte_count"],
        "distance_derivation_contract_artifact_digest": distance_preimage["digest"],
        "distance_derivation_contract_digest": template[
            "distance_derivation_contract_digest"
        ],
        "distance_axis_rule": template["distance_axis_rule"],
        "actual_scope_diff_schema": actual_diff["schema_version"],
        "successor_receipt_schema": receipt["schema_version"],
        "first_query_envelope_schema": receipt["first_query_envelope_schema"],
        "first_result_envelope_schema": receipt["first_result_envelope_schema"],
        "external_artifact_storage": receipt["storage"],
        "actual_diff_required_verifications": tuple(
            actual_diff["required_verifications"]
        ),
        "successor_receipt_required_verifications": tuple(
            receipt["required_verifications"]
        ),
        "primary_aggregate_eligible": receipt["primary_aggregate_eligible"],
        "successor_runtime_eligible": receipt["successor_runtime_eligible"],
        "runtime_binding_status": receipt["runtime_binding_status"],
        "extension_result_namespace": isolation["extension_result_namespace"],
        "mixed_scope_aggregation": isolation["mixed_scope_aggregation"],
        "source_target_scope_join": isolation["source_target_scope_join"],
        "successor_runtime_requirements": _typed_post_scope_requirements(
            wire["successor_blockers"], "extension successor runtime requirements"
        ),
    }


@dataclass(frozen=True, slots=True)
class ExtensionScopeTransitionDeclaration:
    """Exact base reference to an external, post-reveal S-prime receipt chain."""

    protocol_reference: ExactProtocolReference
    semantic: ExtensionSemantic
    primary_role: ExtensionTemplateRole
    role_axis: str
    successor_axis_coverage: tuple[str, ...]
    required_changed_axes: tuple[str, ...]
    allowed_changed_axes: tuple[str, ...]
    role_specific_allowed_changed_axes: tuple[str, ...]
    chronology: tuple[str, ...]
    closure_status: str
    extension_scope_spec_contract_preimage_schema: str
    extension_scope_spec_contract_preimage_label: str
    extension_scope_spec_contract_preimage_encoding: str
    extension_scope_spec_contract_schema: str
    extension_scope_spec_contract_byte_count: int
    extension_scope_spec_contract_artifact_digest: str
    extension_scope_spec_schema: str
    extension_scope_spec_parser: str
    successor_scope_deriver: str
    distance_derivation_declaration_schema: str
    distance_derivation_contract_preimage_schema: str
    distance_derivation_contract_preimage_label: str
    distance_derivation_contract_preimage_encoding: str
    distance_derivation_contract_schema: str
    distance_derivation_contract_byte_count: int
    distance_derivation_contract_artifact_digest: str
    distance_derivation_contract_digest: str
    distance_axis_rule: str
    actual_scope_diff_schema: str
    successor_receipt_schema: str
    first_query_envelope_schema: str
    first_result_envelope_schema: str
    external_artifact_storage: str
    actual_diff_required_verifications: tuple[str, ...]
    successor_receipt_required_verifications: tuple[str, ...]
    primary_aggregate_eligible: bool
    successor_runtime_eligible: bool
    runtime_binding_status: str
    extension_result_namespace: str
    mixed_scope_aggregation: str
    source_target_scope_join: str
    successor_runtime_requirements: tuple[PostScopeAuthorityRequirement, ...]
    task_relation: str

    def __post_init__(
        self, contract_provider: Any = _extension_protocol_contract
    ) -> None:
        if _extension_protocol_contract is not contract_provider:
            raise ProtocolViolation("extension protocol contract provider drifted")
        contract = contract_provider(self.primary_role)
        if (
            type(self.protocol_reference) is not ExactProtocolReference
            or self.protocol_reference.kind
            is not ProtocolReferenceKind.EXTENSION_TEMPLATE_SET
            or self.semantic is not ExtensionSemantic.OPAQUE_POST_SEAL_SCOPE_SUCCESSOR
            or self.role_axis != contract["role_axis"]
            or self.successor_axis_coverage != contract["successor_axis_coverage"]
            or self.required_changed_axes != contract["required_changed_axes"]
            or self.required_changed_axes != (self.role_axis,)
            or self.allowed_changed_axes != contract["allowed_changed_axes"]
            or self.role_specific_allowed_changed_axes
            != contract["role_specific_allowed_changed_axes"]
            or not set(self.required_changed_axes).issubset(
                self.role_specific_allowed_changed_axes
            )
            or self.chronology != contract["chronology"]
            or self.closure_status != "protocol_complete_predecessor"
            or self.extension_scope_spec_contract_preimage_schema
            != contract["extension_scope_spec_contract_preimage_schema"]
            or self.extension_scope_spec_contract_preimage_label
            != contract["extension_scope_spec_contract_preimage_label"]
            or self.extension_scope_spec_contract_preimage_encoding
            != contract["extension_scope_spec_contract_preimage_encoding"]
            or self.extension_scope_spec_contract_schema
            != contract["extension_scope_spec_contract_schema"]
            or self.extension_scope_spec_contract_byte_count
            != contract["extension_scope_spec_contract_byte_count"]
            or self.extension_scope_spec_contract_artifact_digest
            != contract["extension_scope_spec_contract_artifact_digest"]
            or self.extension_scope_spec_schema
            != contract["extension_scope_spec_schema"]
            or self.extension_scope_spec_parser
            != contract["extension_scope_spec_parser"]
            or self.successor_scope_deriver != contract["successor_scope_deriver"]
            or self.distance_derivation_declaration_schema
            != contract["distance_derivation_declaration_schema"]
            or self.distance_derivation_contract_preimage_schema
            != contract["distance_derivation_contract_preimage_schema"]
            or self.distance_derivation_contract_preimage_label
            != contract["distance_derivation_contract_preimage_label"]
            or self.distance_derivation_contract_preimage_encoding
            != contract["distance_derivation_contract_preimage_encoding"]
            or self.distance_derivation_contract_schema
            != contract["distance_derivation_contract_schema"]
            or self.distance_derivation_contract_byte_count
            != contract["distance_derivation_contract_byte_count"]
            or self.distance_derivation_contract_artifact_digest
            != contract["distance_derivation_contract_artifact_digest"]
            or self.distance_derivation_contract_digest
            != contract["distance_derivation_contract_digest"]
            or self.distance_axis_rule != contract["distance_axis_rule"]
            or self.actual_scope_diff_schema != contract["actual_scope_diff_schema"]
            or self.successor_receipt_schema != contract["successor_receipt_schema"]
            or self.first_query_envelope_schema
            != contract["first_query_envelope_schema"]
            or self.first_result_envelope_schema
            != contract["first_result_envelope_schema"]
            or self.external_artifact_storage != contract["external_artifact_storage"]
            or self.actual_diff_required_verifications
            != contract["actual_diff_required_verifications"]
            or self.successor_receipt_required_verifications
            != contract["successor_receipt_required_verifications"]
            or self.primary_aggregate_eligible
            is not contract["primary_aggregate_eligible"]
            or self.successor_runtime_eligible
            is not contract["successor_runtime_eligible"]
            or self.runtime_binding_status != contract["runtime_binding_status"]
            or self.extension_result_namespace != contract["extension_result_namespace"]
            or self.mixed_scope_aggregation != contract["mixed_scope_aggregation"]
            or self.source_target_scope_join != contract["source_target_scope_join"]
            or self.successor_runtime_requirements
            != contract["successor_runtime_requirements"]
            or not self.successor_runtime_requirements
            or any(
                type(requirement) is not PostScopeAuthorityRequirement
                or requirement.schema_version != "ucm-successor-runtime-blocker/1"
                or requirement.blocks_base_scope is not False
                for requirement in self.successor_runtime_requirements
            )
            or self.task_relation != "world_extension_is_distinct_from_new_readout_task"
        ):
            raise ProtocolViolation(
                "extension transition declaration is not the exact base contract"
            )

    @property
    def successor_runtime_requirement_count(self) -> int:
        return len(self.successor_runtime_requirements)

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol_reference": self.protocol_reference.to_wire(),
            "semantic": self.semantic.value,
            "primary_role": self.primary_role.value,
            "role_axis": self.role_axis,
            "successor_axis_coverage": list(self.successor_axis_coverage),
            "required_changed_axes": list(self.required_changed_axes),
            "allowed_changed_axes": list(self.allowed_changed_axes),
            "role_specific_allowed_changed_axes": list(
                self.role_specific_allowed_changed_axes
            ),
            "chronology": list(self.chronology),
            "closure_status": self.closure_status,
            "extension_scope_spec_contract": {
                "preimage_schema": self.extension_scope_spec_contract_preimage_schema,
                "preimage_label": self.extension_scope_spec_contract_preimage_label,
                "preimage_encoding": self.extension_scope_spec_contract_preimage_encoding,
                "contract_schema": self.extension_scope_spec_contract_schema,
                "byte_count": self.extension_scope_spec_contract_byte_count,
                "artifact_digest": self.extension_scope_spec_contract_artifact_digest,
                "typed_spec_schema": self.extension_scope_spec_schema,
                "parser": self.extension_scope_spec_parser,
                "successor_deriver": self.successor_scope_deriver,
            },
            "distance_derivation_contract": {
                "declaration_schema": self.distance_derivation_declaration_schema,
                "preimage_schema": self.distance_derivation_contract_preimage_schema,
                "preimage_label": self.distance_derivation_contract_preimage_label,
                "preimage_encoding": self.distance_derivation_contract_preimage_encoding,
                "contract_schema": self.distance_derivation_contract_schema,
                "byte_count": self.distance_derivation_contract_byte_count,
                "artifact_digest": self.distance_derivation_contract_artifact_digest,
                "contract_digest": self.distance_derivation_contract_digest,
                "distance_axis_rule": self.distance_axis_rule,
            },
            "external_successor_contract": {
                "actual_scope_diff_schema": self.actual_scope_diff_schema,
                "successor_receipt_schema": self.successor_receipt_schema,
                "first_query_envelope_schema": self.first_query_envelope_schema,
                "first_result_envelope_schema": self.first_result_envelope_schema,
                "external_artifact_storage": self.external_artifact_storage,
                "actual_diff_required_verifications": list(
                    self.actual_diff_required_verifications
                ),
                "successor_receipt_required_verifications": list(
                    self.successor_receipt_required_verifications
                ),
                "primary_aggregate_eligible": self.primary_aggregate_eligible,
                "successor_runtime_eligible": self.successor_runtime_eligible,
                "runtime_binding_status": self.runtime_binding_status,
                "extension_result_namespace": self.extension_result_namespace,
                "mixed_scope_aggregation": self.mixed_scope_aggregation,
                "source_target_scope_join": self.source_target_scope_join,
                "successor_runtime_requirement_count": (
                    self.successor_runtime_requirement_count
                ),
                "successor_runtime_requirements": [
                    x.to_wire() for x in self.successor_runtime_requirements
                ],
            },
            "task_relation": self.task_relation,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ExtensionScopeTransitionDeclaration":
        body = _exact_object(
            value,
            frozenset(
                {
                    "protocol_reference",
                    "semantic",
                    "primary_role",
                    "role_axis",
                    "successor_axis_coverage",
                    "required_changed_axes",
                    "allowed_changed_axes",
                    "role_specific_allowed_changed_axes",
                    "chronology",
                    "closure_status",
                    "extension_scope_spec_contract",
                    "distance_derivation_contract",
                    "external_successor_contract",
                    "task_relation",
                }
            ),
            "extension scope transition",
        )
        external = _exact_object(
            body["external_successor_contract"],
            frozenset(
                {
                    "actual_scope_diff_schema",
                    "successor_receipt_schema",
                    "first_query_envelope_schema",
                    "first_result_envelope_schema",
                    "external_artifact_storage",
                    "actual_diff_required_verifications",
                    "successor_receipt_required_verifications",
                    "primary_aggregate_eligible",
                    "successor_runtime_eligible",
                    "runtime_binding_status",
                    "extension_result_namespace",
                    "mixed_scope_aggregation",
                    "source_target_scope_join",
                    "successor_runtime_requirement_count",
                    "successor_runtime_requirements",
                }
            ),
            "external successor contract",
        )
        scope_spec = _exact_object(
            body["extension_scope_spec_contract"],
            frozenset(
                {
                    "preimage_schema",
                    "preimage_label",
                    "preimage_encoding",
                    "contract_schema",
                    "byte_count",
                    "artifact_digest",
                    "typed_spec_schema",
                    "parser",
                    "successor_deriver",
                }
            ),
            "extension scope spec contract",
        )
        distance = _exact_object(
            body["distance_derivation_contract"],
            frozenset(
                {
                    "declaration_schema",
                    "preimage_schema",
                    "preimage_label",
                    "preimage_encoding",
                    "contract_schema",
                    "byte_count",
                    "artifact_digest",
                    "contract_digest",
                    "distance_axis_rule",
                }
            ),
            "extension distance derivation contract",
        )
        if (
            type(external["primary_aggregate_eligible"]) is not bool
            or type(external["successor_runtime_eligible"]) is not bool
            or type(external["successor_runtime_requirement_count"]) is not int
            or type(external["successor_runtime_requirements"]) is not list
            or external["successor_runtime_requirement_count"]
            != len(external["successor_runtime_requirements"])
            or type(scope_spec["byte_count"]) is not int
            or type(distance["byte_count"]) is not int
        ):
            raise ProtocolViolation(
                "extension successor contract counts/types are invalid"
            )
        return cls(
            ExactProtocolReference.from_wire(body["protocol_reference"]),
            _enum(ExtensionSemantic, body["semantic"], "extension semantic"),
            _enum(ExtensionTemplateRole, body["primary_role"], "extension role"),
            _name(body["role_axis"], "extension role axis"),
            _strings(body["successor_axis_coverage"], "successor axis coverage"),
            _strings(body["required_changed_axes"], "required changed axes"),
            _strings(body["allowed_changed_axes"], "allowed changed axes"),
            _strings(
                body["role_specific_allowed_changed_axes"],
                "role-specific allowed changed axes",
            ),
            _strings(body["chronology"], "extension chronology"),
            _name(body["closure_status"], "extension closure status"),
            _name(scope_spec["preimage_schema"], "scope spec preimage schema"),
            _name(scope_spec["preimage_label"], "scope spec preimage label"),
            _name(scope_spec["preimage_encoding"], "scope spec preimage encoding"),
            _name(scope_spec["contract_schema"], "scope spec contract schema"),
            scope_spec["byte_count"],
            _name(scope_spec["artifact_digest"], "scope spec contract digest"),
            _name(scope_spec["typed_spec_schema"], "typed extension spec schema"),
            _name(scope_spec["parser"], "typed extension spec parser"),
            _name(scope_spec["successor_deriver"], "successor scope deriver"),
            _name(distance["declaration_schema"], "distance declaration schema"),
            _name(distance["preimage_schema"], "distance preimage schema"),
            _name(distance["preimage_label"], "distance preimage label"),
            _name(distance["preimage_encoding"], "distance preimage encoding"),
            _name(distance["contract_schema"], "distance contract schema"),
            distance["byte_count"],
            _name(distance["artifact_digest"], "distance contract artifact digest"),
            _name(distance["contract_digest"], "distance derivation contract digest"),
            _name(distance["distance_axis_rule"], "distance axis rule"),
            _name(external["actual_scope_diff_schema"], "actual diff schema"),
            _name(external["successor_receipt_schema"], "successor receipt schema"),
            _name(external["first_query_envelope_schema"], "first query schema"),
            _name(external["first_result_envelope_schema"], "first result schema"),
            _name(external["external_artifact_storage"], "external storage"),
            _strings(
                external["actual_diff_required_verifications"],
                "actual diff verifications",
            ),
            _strings(
                external["successor_receipt_required_verifications"],
                "successor receipt verifications",
            ),
            external["primary_aggregate_eligible"],
            external["successor_runtime_eligible"],
            _name(external["runtime_binding_status"], "successor runtime status"),
            _name(external["extension_result_namespace"], "extension namespace"),
            _name(external["mixed_scope_aggregation"], "mixed scope aggregation"),
            _name(external["source_target_scope_join"], "scope join"),
            tuple(
                PostScopeAuthorityRequirement.from_wire(x)
                for x in external["successor_runtime_requirements"]
            ),
            _name(body["task_relation"], "extension task relation"),
        )


@dataclass(frozen=True, slots=True)
class ResourceAxis:
    identification: str
    base_candidate_methods: tuple[str, ...]
    split_roles: tuple[SplitRoleDeclaration, ...]
    projection_layers: tuple[str, ...]
    test_split_alias: str
    family_split_derivation: FamilySplitDerivationRequirement
    extension_transition: ExtensionScopeTransitionDeclaration | None
    worker_contracts: tuple[tuple[str, str], ...]
    training_track: str

    def __post_init__(self) -> None:
        if type(self.family_split_derivation) is not FamilySplitDerivationRequirement:
            raise ProtocolViolation("R family/split derivation requirement is untyped")
        if self.extension_transition is not None and (
            type(self.extension_transition) is not ExtensionScopeTransitionDeclaration
        ):
            raise ProtocolViolation("R extension transition is untyped")

    @property
    def extension_semantics(self) -> ExtensionSemantic:
        return (
            ExtensionSemantic.NONE
            if self.extension_transition is None
            else self.extension_transition.semantic
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "identification": self.identification,
            "base_candidate_methods": list(self.base_candidate_methods),
            "split_roles": [x.to_wire() for x in self.split_roles],
            "projection_layers": list(self.projection_layers),
            "test_split_alias": self.test_split_alias,
            "family_split_derivation": self.family_split_derivation.to_wire(),
            "extension_transition": (
                None
                if self.extension_transition is None
                else self.extension_transition.to_wire()
            ),
            "worker_contracts": {k: v for k, v in self.worker_contracts},
            "training_track": self.training_track,
        }

    @classmethod
    def from_wire(cls, value: object) -> "ResourceAxis":
        body = _exact_object(
            value,
            frozenset(
                {
                    "identification",
                    "base_candidate_methods",
                    "split_roles",
                    "projection_layers",
                    "test_split_alias",
                    "family_split_derivation",
                    "extension_transition",
                    "worker_contracts",
                    "training_track",
                }
            ),
            "R axis",
        )
        if (
            type(body["split_roles"]) is not list
            or type(body["worker_contracts"]) is not dict
        ):
            raise ProtocolViolation("R roles/contracts are invalid")
        return cls(
            _name(body["identification"], "R identification"),
            _strings(body["base_candidate_methods"], "R methods"),
            tuple(SplitRoleDeclaration.from_wire(x) for x in body["split_roles"]),
            _strings(body["projection_layers"], "R layers"),
            _name(body["test_split_alias"], "R alias"),
            FamilySplitDerivationRequirement.from_wire(body["family_split_derivation"]),
            (
                None
                if body["extension_transition"] is None
                else ExtensionScopeTransitionDeclaration.from_wire(
                    body["extension_transition"]
                )
            ),
            tuple(
                (_name(k, "R worker"), _name(v, "R contract"))
                for k, v in body["worker_contracts"].items()
            ),
            _name(body["training_track"], "R track"),
        )


@dataclass(frozen=True, slots=True)
class ScopeAxes:
    P: PopulationAxis
    O: ObservationAxis  # noqa: E741
    A: ActionAxis
    Q: CheckAxis
    Pi: PolicyAxis
    Tau: HorizonAxis
    Gamma: DiagnosisAxis
    Y: FutureAxis
    U: UtilityAxis
    D: DistanceAxis
    R: ResourceAxis

    def __post_init__(self) -> None:
        if tuple(self.to_wire()) != SCOPE_AXES:
            raise ProtocolViolation(
                "fragment axes are not exact formal eleven-axis order"
            )
        transition = self.R.extension_transition
        action_template = self.A.extension_commitment_template
        check_template = self.Q.extension_commitment_template
        if transition is None:
            if action_template is not None or check_template is not None:
                raise ProtocolViolation(
                    "extension template cannot exist without R transition"
                )
        elif transition.primary_role is ExtensionTemplateRole.NEW_CHECK:
            if (
                action_template is not None
                or check_template is None
                or check_template.role is not ExtensionTemplateRole.NEW_CHECK
                or transition.role_axis != "Q"
                or "Q" not in transition.role_specific_allowed_changed_axes
                or check_template.protocol_reference != transition.protocol_reference
            ):
                raise ProtocolViolation(
                    "new-check extension must bind Q template and matching R transition"
                )
        elif (
            check_template is not None
            or action_template is None
            or action_template.role is not ExtensionTemplateRole.NEW_TREATMENT
            or transition.role_axis != "A"
            or "A" not in transition.role_specific_allowed_changed_axes
            or action_template.protocol_reference != transition.protocol_reference
        ):
            raise ProtocolViolation(
                "new-treatment extension must bind A template and matching R transition"
            )

    def to_wire(self) -> dict[str, Any]:
        return {axis: getattr(self, axis).to_wire() for axis in SCOPE_AXES}

    @classmethod
    def from_wire(cls, value: object) -> "ScopeAxes":
        body = _exact_object(value, frozenset(SCOPE_AXES), "scope axes")
        return cls(
            P=PopulationAxis.from_wire(body["P"]),
            O=ObservationAxis.from_wire(body["O"]),
            A=ActionAxis.from_wire(body["A"]),
            Q=CheckAxis.from_wire(body["Q"]),
            Pi=PolicyAxis.from_wire(body["Pi"]),
            Tau=HorizonAxis.from_wire(body["Tau"]),
            Gamma=DiagnosisAxis.from_wire(body["Gamma"]),
            Y=FutureAxis.from_wire(body["Y"]),
            U=UtilityAxis.from_wire(body["U"]),
            D=DistanceAxis.from_wire(body["D"]),
            R=ResourceAxis.from_wire(body["R"]),
        )


@dataclass(frozen=True, slots=True)
class TaskApplicabilityRow:
    task: EvaluationTask
    applicability: TaskApplicability
    execution_kind: TaskExecutionKind
    operations: tuple[Operation, ...]
    applicability_basis: ApplicabilityBasis

    def __post_init__(self) -> None:
        truth = {
            task: (kind, operations) for task, kind, operations in TASK_EXECUTION_TRUTH
        }
        if type(self.task) is not EvaluationTask or truth.get(self.task) != (
            self.execution_kind,
            self.operations,
        ):
            raise ProtocolViolation("task row contradicts TASK_EXECUTION_TRUTH")

    def to_wire(self) -> dict[str, Any]:
        return {
            "task": self.task.value,
            "applicability": self.applicability.value,
            "execution_kind": self.execution_kind.value,
            "operations": [x.value for x in self.operations],
            "applicability_basis": self.applicability_basis.value,
        }

    @classmethod
    def from_wire(cls, value: object) -> "TaskApplicabilityRow":
        body = _exact_object(
            value,
            frozenset(
                {
                    "task",
                    "applicability",
                    "execution_kind",
                    "operations",
                    "applicability_basis",
                }
            ),
            "task row",
        )
        if type(body["operations"]) is not list:
            raise ProtocolViolation("task operations must be a list")
        return cls(
            _enum(EvaluationTask, body["task"], "task"),
            _enum(TaskApplicability, body["applicability"], "applicability"),
            _enum(TaskExecutionKind, body["execution_kind"], "execution kind"),
            tuple(_enum(Operation, x, "operation") for x in body["operations"]),
            _enum(
                ApplicabilityBasis, body["applicability_basis"], "applicability basis"
            ),
        )


def _task_rows(world_slot: str) -> tuple[TaskApplicabilityRow, ...]:
    rows = []
    for task, kind, operations in TASK_EXECUTION_TRUTH:
        if task in {
            EvaluationTask.DIAGNOSIS,
            EvaluationTask.NATURAL_FORECAST,
            EvaluationTask.INTERVENTION,
        }:
            applicability, basis = (
                TaskApplicability.REQUIRED,
                ApplicabilityBasis.PRIMARY,
            )
        elif task is EvaluationTask.OOD and world_slot == "W18":
            applicability, basis = (
                TaskApplicability.REQUIRED,
                ApplicabilityBasis.OOD_REQUIRED,
            )
        elif task is EvaluationTask.OOD:
            applicability, basis = (
                TaskApplicability.CONTROL,
                ApplicabilityBasis.OOD_CONTROL,
            )
        else:
            applicability, basis = (
                TaskApplicability.POST_SEAL_EXTENSION,
                ApplicabilityBasis.NOVEL_READOUT,
            )
        rows.append(TaskApplicabilityRow(task, applicability, kind, operations, basis))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class WorldScopeFragment:
    world_slot: str
    panel_id: str
    axes: ScopeAxes
    task_applicability: tuple[TaskApplicabilityRow, ...]

    def __post_init__(self) -> None:
        if type(self.axes) is not ScopeAxes or self.task_applicability != _task_rows(
            self.world_slot
        ):
            raise ProtocolViolation("fragment axes/task rows are not code-owned")
        expected_extension_role = {
            "W16": ExtensionTemplateRole.NEW_CHECK,
            "W17": ExtensionTemplateRole.NEW_TREATMENT,
        }.get(self.world_slot)
        transition = self.axes.R.extension_transition
        actual_extension_role = None if transition is None else transition.primary_role
        if actual_extension_role is not expected_extension_role:
            raise ProtocolViolation(
                "fragment world identity contradicts extension transition role"
            )

    @property
    def identity(self) -> tuple[str, str]:
        return self.world_slot, self.panel_id

    def to_wire(self) -> dict[str, Any]:
        return {
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "axes": self.axes.to_wire(),
            "task_applicability": [x.to_wire() for x in self.task_applicability],
        }

    @classmethod
    def from_wire(cls, value: object) -> "WorldScopeFragment":
        body = _exact_object(
            value,
            frozenset({"world_slot", "panel_id", "axes", "task_applicability"}),
            "fragment",
        )
        if type(body["task_applicability"]) is not list:
            raise ProtocolViolation("task rows must be a list")
        return cls(
            _name(body["world_slot"], "world slot"),
            _name(body["panel_id"], "panel id"),
            ScopeAxes.from_wire(body["axes"]),
            tuple(
                TaskApplicabilityRow.from_wire(x) for x in body["task_applicability"]
            ),
        )


@dataclass(frozen=True, slots=True)
class WorldScopeFragmentSet:
    panels: tuple[WorldScopeFragment, ...]
    schema_version: str = WORLD_SCOPE_FRAGMENT_SET_SCHEMA
    benchmark_id: str = "UCM-BENCHMARK-v1"
    authority_claim: str = WORLD_SCOPE_FRAGMENT_AUTHORITY

    def __post_init__(self) -> None:
        if (self.schema_version, self.benchmark_id, self.authority_claim) != (
            WORLD_SCOPE_FRAGMENT_SET_SCHEMA,
            "UCM-BENCHMARK-v1",
            WORLD_SCOPE_FRAGMENT_AUTHORITY,
        ):
            raise ProtocolViolation("fragment set identity/claim is not code-owned")
        if tuple(x.identity for x in self.panels) != EXPECTED_PANEL_IDENTITIES:
            raise ProtocolViolation(
                "fragment panels are missing, reordered, duplicated, or stale"
            )
        if sum(len(x.task_applicability) for x in self.panels) != 105:
            raise ProtocolViolation("fragment set must contain exact 21 x 5 task rows")

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "benchmark_id": self.benchmark_id,
            "authority_claim": self.authority_claim,
            "panels": [x.to_wire() for x in self.panels],
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        return (
            "sha256:"
            + hashlib.sha256(
                WORLD_SCOPE_FRAGMENT_DOMAIN + self.canonical_bytes
            ).hexdigest()
        )

    @classmethod
    def from_wire(cls, value: object) -> "WorldScopeFragmentSet":
        body = _exact_object(
            value,
            frozenset({"schema_version", "benchmark_id", "authority_claim", "panels"}),
            "fragment set",
        )
        if type(body["panels"]) is not list:
            raise ProtocolViolation("panels must be a list")
        return cls(
            tuple(WorldScopeFragment.from_wire(x) for x in body["panels"]),
            body["schema_version"],
            body["benchmark_id"],
            body["authority_claim"],
        )


@dataclass(frozen=True, slots=True)
class ScopeClosureGap:
    scope_level: GapScope
    world_slot: str | None
    panel_id: str | None
    axis: str
    subject_id: str
    code: ScopeGapCode
    detail: str

    def __post_init__(self) -> None:
        if (
            type(self.scope_level) is not GapScope
            or self.axis not in SCOPE_AXES
            or type(self.code) is not ScopeGapCode
        ):
            raise ProtocolViolation("gap axis/code is invalid")
        if self.scope_level is GapScope.GLOBAL:
            if self.world_slot is not None or self.panel_id is not None:
                raise ProtocolViolation("global gap cannot carry panel identity")
        elif self.world_slot is None or self.panel_id is None:
            raise ProtocolViolation("panel gap requires world and panel identity")


@dataclass(frozen=True, slots=True)
class WorldScopeBuildReport:
    fragments: WorldScopeFragmentSet
    gaps: tuple[ScopeClosureGap, ...]
    status: str = WORLD_SCOPE_BUILD_STATUS
    scope_manifest_emitted: bool = False
    freeze_authority: bool = False

    def __post_init__(self) -> None:
        if (
            self.status != "PRE-FREEZE"
            or self.scope_manifest_emitted
            or self.freeze_authority
        ):
            raise ProtocolViolation(
                "world fragments cannot claim scope/freeze authority"
            )
        if self.gaps != _gap_inventory(self.fragments):
            raise ProtocolViolation(
                "gap inventory is missing, extra, reordered, or stale"
            )

    @property
    def scope_ready(self) -> bool:
        return False

    def require_scope_ready(self) -> WorldScopeFragmentSet:
        raise ProtocolViolation("world scope fragments are PRE-FREEZE and incomplete")


def _assert_live_shape() -> None:
    if tuple(EvaluationTask) != EXPECTED_TASKS or tuple(WorldSplit) != EXPECTED_SPLITS:
        raise ProtocolViolation("live task/split enum drifted")
    if tuple(task for task, _, _ in TASK_EXECUTION_TRUTH) != EXPECTED_TASKS:
        raise ProtocolViolation("TASK_EXECUTION_TRUTH drifted")
    live = tuple(
        (slot, panel.panel_id)
        for slot, decl in WORLD_REGISTRY.items()
        for panel in decl.panels
    )
    if live != EXPECTED_PANEL_IDENTITIES:
        raise ProtocolViolation("live panel identities drifted")
    if tuple(EXTENSION_WORLD_REGISTRY) != ("W16", "W17"):
        raise ProtocolViolation("extension registry drifted")


def _adaptive_ids(parameters: dict[str, Any]) -> tuple[str, ...]:
    found: list[str] = []

    def walk(value: object) -> None:
        if type(value) is dict:
            for key, item in value.items():
                if key == "adaptive_rule" and type(item) is str and item not in found:
                    found.append(item)
                walk(item)
        elif type(value) is list:
            for item in value:
                walk(item)

    walk(parameters)
    return tuple(found)


def _policy(plan: Any) -> PolicyDeclaration:
    wire = plan.to_wire()
    actions = tuple(
        PlannedActionDeclaration.from_live(x["offset"], x["action_id"], x["parameters"])
        for x in wire["actions"]
    )
    adaptive: list[str] = []
    for action in actions:
        for item in _adaptive_ids(action.parameters):
            if item not in adaptive:
                adaptive.append(item)
    return PolicyDeclaration(plan.kind, actions, plan.policy_digest, tuple(adaptive))


def _metric_target_binding() -> tuple[str, str, int, tuple[tuple[str, str], ...]]:
    registry = benchmark_v1_metric_target_registry()
    wire = registry.to_wire()
    gates = wire["hard_gate_policy"]
    sources = tuple(
        sorted(
            (key, gates[key])
            for key in (
                "collision_margin_source",
                "catastrophic_margin_source",
                "optimal_action_tolerance_source",
                "action_tie_break_source",
            )
        )
    )
    return (
        registry.artifact_digest,
        registry.metric_target_digest,
        wire["numerical_policy"]["calibration_bins"],
        sources,
    )


def _family_split_derivation_requirement() -> FamilySplitDerivationRequirement:
    protocol_wire = parse_split_derivation_protocol_bytes(
        SPLIT_DERIVATION_PROTOCOL_BYTES
    ).to_wire()
    inventory = protocol_wire["protocol"]["inventory_semantics"]
    pairing = protocol_wire["protocol"]["zipped_seed_semantics"]["pairing"]
    post_scope_requirements = _typed_post_scope_requirements(
        protocol_wire["post_scope_requirements"], "split post-scope requirements"
    )
    if (
        protocol_wire["scope_binding_status"] != "not_bound"
        or protocol_wire["gap_count"] != 0
        or protocol_wire["gaps"] != []
        or protocol_wire["post_scope_requirement_count"]
        != len(protocol_wire["post_scope_requirements"])
        or not protocol_wire["post_scope_requirements"]
        or post_scope_requirements != _SPLIT_POST_SCOPE_AUTHORITY_REQUIREMENTS
        or any(
            row["blocks_base_scope"] is not False
            for row in protocol_wire["post_scope_requirements"]
        )
        or protocol_wire["protocol"]["deterministic_derivation"][
            "materialized_assignments"
        ]
        != "excluded"
        or protocol_wire["protocol"]["deterministic_derivation"][
            "materialized_partitions"
        ]
        != "excluded"
        or tuple(
            (row["training_replicate_id"], row["evaluation_replicate_id"])
            for row in pairing
        )
        != ZIPPED_REPLICATE_IDS
    ):
        raise ProtocolViolation(
            "scope-independent split derivation protocol contradicts base scope"
        )
    reference = _exact_protocol_reference_contract(
        ProtocolReferenceKind.FAMILY_SPLIT_DERIVATION
    )
    return FamilySplitDerivationRequirement(
        ExactProtocolReference(
            ProtocolReferenceKind.FAMILY_SPLIT_DERIVATION, *reference
        ),
        "protocol_complete_predecessor",
        inventory["panel_count"],
        inventory["task_count"],
        inventory["split_count"],
        inventory["physical_assignment_count"],
        inventory["task_projection_count"],
        inventory["physical_partition_count"],
        inventory["panel_task_split_projection_count"],
        inventory["zipped_slot_count_per_panel_split"],
        inventory["zipped_slot_count"],
        tuple(
            ZippedSlotTiming(
                training_id,
                evaluation_id,
                "post_freeze_pre_training_precommit",
                "post_candidate_seals_hidden_commitment",
                "post_corpus_finalization",
            )
            for training_id, evaluation_id in ZIPPED_REPLICATE_IDS
        ),
        FamilySplitDerivationRequirement._CHRONOLOGY,
        "post_scope_authorization",
        "actual_authorities_bind_S_one_way_and_never_feed_back_into_S",
        post_scope_requirements,
        FamilySplitDerivationRequirement._FORBIDDEN,
    )


def _extension_role(slot: str) -> ExtensionTemplateRole | None:
    expected = {
        "W16": (
            "make_w16_extension_custody",
            ExtensionTemplateRole.NEW_CHECK,
        ),
        "W17": (
            "make_w17_extension_custody",
            ExtensionTemplateRole.NEW_TREATMENT,
        ),
    }
    if slot not in expected:
        return None
    factory_name, role = expected[slot]
    if EXTENSION_WORLD_REGISTRY[slot].custody_factory_name != factory_name:
        raise ProtocolViolation(f"{slot} extension commitment source drifted")
    return role


def _extension_template(role: ExtensionTemplateRole) -> ExtensionCommitmentTemplate:
    reference = _exact_protocol_reference_contract(
        ProtocolReferenceKind.EXTENSION_TEMPLATE_SET
    )
    return ExtensionCommitmentTemplate(
        {
            ExtensionTemplateRole.NEW_CHECK: "W16-new-check-template",
            ExtensionTemplateRole.NEW_TREATMENT: "W17-new-treatment-template",
        }[role],
        role,
        ExactProtocolReference(
            ProtocolReferenceKind.EXTENSION_TEMPLATE_SET, *reference
        ),
        "opaque_hiding_commitment_before_candidate_model_state_seals",
        "exact_opening_only_after_candidate_model_state_seals",
        "exact_commit_reveal_schema_algorithm_and_source_preimage",
        "protocol_complete_predecessor",
        "actual_commitment_and_revealed_payload_excluded",
        "R.extension_transition",
    )


def _extension_transition(
    role: ExtensionTemplateRole | None,
) -> ExtensionScopeTransitionDeclaration | None:
    if role is None:
        return None
    contract = _extension_protocol_contract(role)
    reference = _exact_protocol_reference_contract(
        ProtocolReferenceKind.EXTENSION_TEMPLATE_SET
    )
    return ExtensionScopeTransitionDeclaration(
        ExactProtocolReference(
            ProtocolReferenceKind.EXTENSION_TEMPLATE_SET, *reference
        ),
        ExtensionSemantic.OPAQUE_POST_SEAL_SCOPE_SUCCESSOR,
        role,
        contract["role_axis"],
        contract["successor_axis_coverage"],
        contract["required_changed_axes"],
        contract["allowed_changed_axes"],
        contract["role_specific_allowed_changed_axes"],
        contract["chronology"],
        "protocol_complete_predecessor",
        contract["extension_scope_spec_contract_preimage_schema"],
        contract["extension_scope_spec_contract_preimage_label"],
        contract["extension_scope_spec_contract_preimage_encoding"],
        contract["extension_scope_spec_contract_schema"],
        contract["extension_scope_spec_contract_byte_count"],
        contract["extension_scope_spec_contract_artifact_digest"],
        contract["extension_scope_spec_schema"],
        contract["extension_scope_spec_parser"],
        contract["successor_scope_deriver"],
        contract["distance_derivation_declaration_schema"],
        contract["distance_derivation_contract_preimage_schema"],
        contract["distance_derivation_contract_preimage_label"],
        contract["distance_derivation_contract_preimage_encoding"],
        contract["distance_derivation_contract_schema"],
        contract["distance_derivation_contract_byte_count"],
        contract["distance_derivation_contract_artifact_digest"],
        contract["distance_derivation_contract_digest"],
        contract["distance_axis_rule"],
        contract["actual_scope_diff_schema"],
        contract["successor_receipt_schema"],
        contract["first_query_envelope_schema"],
        contract["first_result_envelope_schema"],
        contract["external_artifact_storage"],
        contract["actual_diff_required_verifications"],
        contract["successor_receipt_required_verifications"],
        contract["primary_aggregate_eligible"],
        contract["successor_runtime_eligible"],
        contract["runtime_binding_status"],
        contract["extension_result_namespace"],
        contract["mixed_scope_aggregation"],
        contract["source_target_scope_join"],
        contract["successor_runtime_requirements"],
        "world_extension_is_distinct_from_new_readout_task",
    )


def _build_panel(
    slot: str,
    panel: PanelDeclaration,
    world: MicroWorld,
    family_split_derivation: FamilySplitDerivationRequirement,
) -> WorldScopeFragment:
    catalog = world.catalog
    if type(catalog) is not PublicCatalog:
        raise ProtocolViolation("world catalog is not PublicCatalog")
    channels = tuple(
        ChannelDeclaration(x.channel_id, x.value_type, x.unit, x.valid_range)
        for x in catalog.observations
    )
    actions = tuple(
        ActionDeclaration.from_live(x.action_id, x.parameter_schema, x.cost)
        for x in catalog.actions
    )
    checks = tuple(
        CheckDeclaration(x.check_id, x.result_channels, x.delay_support, x.cost)
        for x in catalog.checks
    )
    policies = tuple(
        PolicyHorizonDeclaration(h, tuple(_policy(x) for x in world.policy_set(h)))
        for h in catalog.horizons
    )
    metric_artifact_digest, metric_target_digest, bins, margin_sources = (
        _metric_target_binding()
    )
    extension_role = _extension_role(slot)
    split_roles = tuple(
        SplitRoleDeclaration(
            split,
            {
                WorldSplit.TRAIN: "train",
                WorldSplit.VALIDATION: "validation",
                WorldSplit.SEALED_TEST: "test",
            }[split],
            {
                WorldSplit.TRAIN: "fit",
                WorldSplit.VALIDATION: "model_selection",
                WorldSplit.SEALED_TEST: "confirmatory",
            }[split],
            panel.episode_count(split, world),
        )
        for split in EXPECTED_SPLITS
    )
    axes = ScopeAxes(
        P=PopulationAxis(
            "MicroWorld.generate_episode",
            ("split", "generator_seed", "episode_index"),
            "nonnegative_integer",
            tuple(x.value for x in EXPECTED_SPLITS),
        ),
        O=ObservationAxis(
            "ucm-public-catalog/1",
            "ucm-visible-history/1",
            tuple(x.value for x in EventKind),
            ("occurred_at", "collected_at", "available_at"),
            "event.available_at<=history.as_of_available_at",
            channels,
        ),
        A=ActionAxis(
            "counterfactual_is_do_policy_not_observational_conditioning",
            actions,
            (
                _extension_template(extension_role)
                if extension_role is ExtensionTemplateRole.NEW_TREATMENT
                else None
            ),
        ),
        Q=CheckAxis(
            "check_changes_information_availability_after_declared_delay",
            checks,
            (
                _extension_template(extension_role)
                if extension_role is ExtensionTemplateRole.NEW_CHECK
                else None
            ),
        ),
        Pi=PolicyAxis("MicroWorld.policy_set(horizon)", policies),
        Tau=HorizonAxis(catalog.horizons, catalog.time_unit),
        Gamma=DiagnosisAxis(
            catalog.diagnostic_labels,
            "PublicCatalog.diagnostic_labels",
            "unknown" in catalog.diagnostic_labels,
        ),
        Y=FutureAxis(
            tuple(RolloutResult.__dataclass_fields__),
            tuple(CounterfactualOracle.__dataclass_fields__),
            tuple(x.channel_id for x in catalog.observations),
        ),
        U=UtilityAxis(
            "CounterfactualOracle.expected_utility",
            "RolloutResult.utility_prediction",
            "maximize_expected_utility",
            tuple((x.action_id, x.cost) for x in catalog.actions),
            tuple((x.check_id, x.cost) for x in catalog.checks),
        ),
        D=DistanceAxis(
            METRIC_TARGET_SCHEMA,
            METRIC_TARGET_DOMAIN.hex(),
            metric_artifact_digest,
            metric_target_digest,
            "metric_configuration.benchmark_v1_metric_target_registry",
            "unresolved_global_target_gap",
            (),
            bins,
            "linf_max_abs_behavior_signature",
            "metrics.classify_pair",
            margin_sources,
        ),
        R=ResourceAxis(
            panel.identification,
            tuple(x.value for x in Operation),
            split_roles,
            ("candidate_inputs", "trainer_targets", "judge_oracle"),
            "sealed_test->test",
            family_split_derivation,
            _extension_transition(extension_role),
            (
                (
                    "extension_worker",
                    "post_seal_independent_worker_sealed_state_no_history",
                ),
                (
                    "head_worker",
                    "fresh_process_model_plus_exact_state_plus_nonpatient_query_only",
                ),
                (
                    "state_worker",
                    "fresh_process_model_plus_history_or_state_delta_only",
                ),
            ),
            "FACTUAL-TRAIN-v1",
        ),
    )
    return WorldScopeFragment(slot, panel.panel_id, axes, _task_rows(slot))


def build_code_owned_world_scope_fragments() -> WorldScopeFragmentSet:
    _assert_live_shape()
    family_split_derivation = _family_split_derivation_requirement()
    return WorldScopeFragmentSet(
        tuple(
            _build_panel(
                slot,
                panel,
                panel.instantiate(),
                family_split_derivation,
            )
            for slot, decl in WORLD_REGISTRY.items()
            for panel in decl.panels
        )
    )


def _gap(
    fragment: WorldScopeFragment,
    axis: str,
    subject: str,
    code: ScopeGapCode,
    detail: str,
) -> ScopeClosureGap:
    return ScopeClosureGap(
        GapScope.PANEL,
        fragment.world_slot,
        fragment.panel_id,
        axis,
        subject,
        code,
        detail,
    )


def _global_gap(
    axis: str,
    subject: str,
    code: ScopeGapCode,
    detail: str,
) -> ScopeClosureGap:
    return ScopeClosureGap(
        GapScope.GLOBAL,
        None,
        None,
        axis,
        subject,
        code,
        detail,
    )


def _gap_inventory(fragments: WorldScopeFragmentSet) -> tuple[ScopeClosureGap, ...]:
    metric_wire = benchmark_v1_metric_target_registry().to_wire()
    metric_gaps = [
        (item["gap_id"], item["missing_dimensions"])
        for item in metric_wire["global_target_gaps"]
    ]
    metric_gaps.extend(
        (
            output["unresolved_target_gap"]["gap_id"],
            output["unresolved_target_gap"]["missing_dimensions"],
        )
        for measurement in metric_wire["measurement_contracts"]
        for output in measurement["outputs"]
        if output["unresolved_target_gap"] is not None
    )
    if len(metric_gaps) != metric_wire["target_gap_count"]:
        raise ProtocolViolation(
            "metric target gap inventory contradicts its code-owned count"
        )
    gaps: list[ScopeClosureGap] = [
        _global_gap(
            "D",
            gap_id,
            ScopeGapCode.D_METRIC_TARGET_GAP,
            "metric target registry unresolved dimensions: "
            + ",".join(missing_dimensions),
        )
        for gap_id, missing_dimensions in metric_gaps
    ]
    gaps.extend(
        (
            _global_gap(
                "D",
                "linf_max_abs_behavior_signature",
                ScopeGapCode.D_BEHAVIOR_DISTANCE_CLOSURE,
                "behavior distance formula and source closure are not code-bound",
            ),
            _global_gap(
                "D",
                "metrics.classify_pair",
                ScopeGapCode.D_PAIR_CLASSIFIER_CLOSURE,
                "pair classifier formula and source closure are not code-bound",
            ),
        )
    )
    for f in fragments.panels:
        gaps.extend(
            (
                _gap(
                    f,
                    "P",
                    "population_support",
                    ScopeGapCode.P_POPULATION_SUPPORT,
                    "population parameter support lacks a typed declaration",
                ),
                _gap(
                    f,
                    "P",
                    "host_support",
                    ScopeGapCode.P_HOST_SUPPORT,
                    "host support lacks a typed declaration",
                ),
                _gap(
                    f,
                    "P",
                    "mechanism_support",
                    ScopeGapCode.P_MECHANISM_SUPPORT,
                    "mechanism support lacks a typed declaration",
                ),
                _gap(
                    f,
                    "O",
                    "missingness_process",
                    ScopeGapCode.O_MISSINGNESS,
                    "missingness and sampling process lack a typed declaration",
                ),
                _gap(
                    f,
                    "Gamma",
                    "behavioral_quotient",
                    ScopeGapCode.GAMMA_QUOTIENT,
                    "diagnostic labels lack typed behavioral quotient granularity",
                ),
                _gap(
                    f,
                    "Y",
                    "outcome_distribution",
                    ScopeGapCode.Y_OUTCOME_SCHEMA,
                    "outcome distribution inner schema is not closed",
                ),
                _gap(
                    f,
                    "Y",
                    "future_event_closure",
                    ScopeGapCode.Y_EVENT_CLOSURE,
                    "future event and outcome closure is not typed",
                ),
                _gap(
                    f,
                    "U",
                    "utility_formula",
                    ScopeGapCode.U_FORMULA,
                    "utility formula remains executable code rather than typed semantics",
                ),
                _gap(
                    f,
                    "D",
                    "normalization_scale",
                    ScopeGapCode.D_NORMALIZATION,
                    "world normalization scale is not typed",
                ),
                _gap(
                    f,
                    "D",
                    "epsilon_candidate_same",
                    ScopeGapCode.D_CANDIDATE_SAME,
                    "candidate-same margin is not typed",
                ),
                _gap(
                    f,
                    "D",
                    "epsilon_equivalent",
                    ScopeGapCode.D_EQUIVALENT,
                    "equivalence margin is not typed",
                ),
                _gap(
                    f,
                    "D",
                    "delta_distinguishable",
                    ScopeGapCode.D_DISTINGUISHABLE,
                    "distinguishability margin is not typed",
                ),
                _gap(
                    f,
                    "D",
                    "catastrophic_margin",
                    ScopeGapCode.D_CATASTROPHIC,
                    "catastrophic margin is not typed",
                ),
                _gap(
                    f,
                    "D",
                    "optimal_action_tolerance",
                    ScopeGapCode.D_OPTIMAL_TOLERANCE,
                    "optimal action tolerance is not typed",
                ),
                _gap(
                    f,
                    "R",
                    "training_data_budget",
                    ScopeGapCode.R_DATA_BUDGET,
                    "training data budget is not typed",
                ),
                _gap(
                    f,
                    "R",
                    "compute_budget",
                    ScopeGapCode.R_COMPUTE_BUDGET,
                    "compute latency and memory budgets are not typed",
                ),
                _gap(
                    f,
                    "R",
                    "isolation_profile",
                    ScopeGapCode.R_ISOLATION,
                    "runtime isolation assurance profile is not typed",
                ),
            )
        )
        gaps.extend(
            _gap(
                f,
                "O",
                x.channel_id,
                ScopeGapCode.O_CHANNEL_KERNEL,
                "observation channel generation kernel is not typed",
            )
            for x in f.axes.O.channels
        )
        gaps.extend(
            _gap(
                f,
                "A",
                x.action_id,
                ScopeGapCode.A_EFFECT_KERNEL,
                "action physiologic and treatment effect kernel is not typed",
            )
            for x in f.axes.A.actions
        )
        gaps.extend(
            _gap(
                f,
                "Q",
                x.check_id,
                ScopeGapCode.Q_RESULT_KERNEL,
                "check result generation kernel is not typed",
            )
            for x in f.axes.Q.checks
        )
        gaps.extend(
            _gap(
                f,
                "Y",
                x,
                ScopeGapCode.Y_OBSERVABLE_SCHEMA,
                "observable predictive distribution inner schema is not typed",
            )
            for x in f.axes.Y.observable_ids
        )
        adaptive = tuple(
            dict.fromkeys(
                rule
                for row in f.axes.Pi.by_horizon
                for plan in row.policies
                for rule in plan.adaptive_rule_ids
            )
        )
        gaps.extend(
            _gap(
                f,
                "Pi",
                x,
                ScopeGapCode.PI_ADAPTIVE_RULE,
                "adaptive rule execution semantics are not independently typed",
            )
            for x in adaptive
        )
    return tuple(gaps)


def inspect_world_scope_fragments() -> WorldScopeBuildReport:
    fragments = build_code_owned_world_scope_fragments()
    return WorldScopeBuildReport(fragments, _gap_inventory(fragments))


def parse_world_scope_fragment_set_bytes(payload: bytes) -> WorldScopeFragmentSet:
    parsed = WorldScopeFragmentSet.from_wire(_decode(payload))
    if parsed.canonical_bytes != payload:
        raise ProtocolViolation("fragment DTO round-trip changed bytes")
    live = build_code_owned_world_scope_fragments()
    if live.canonical_bytes != payload:
        raise ProtocolViolation(
            "fragment bytes contradict live code-owned declarations"
        )
    return parsed


def world_scope_fragment_artifact_digest_from_bytes(payload: bytes) -> str:
    return parse_world_scope_fragment_set_bytes(payload).artifact_digest


def world_scope_fragment_semantic_digest_from_bytes(payload: bytes) -> str:
    return parse_world_scope_fragment_set_bytes(payload).semantic_digest


CODE_OWNED_WORLD_SCOPE_FRAGMENTS = build_code_owned_world_scope_fragments()
CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES = CODE_OWNED_WORLD_SCOPE_FRAGMENTS.canonical_bytes
CODE_OWNED_WORLD_SCOPE_FRAGMENT_ARTIFACT_DIGEST = (
    CODE_OWNED_WORLD_SCOPE_FRAGMENTS.artifact_digest
)
CODE_OWNED_WORLD_SCOPE_FRAGMENT_SEMANTIC_DIGEST = (
    CODE_OWNED_WORLD_SCOPE_FRAGMENTS.semantic_digest
)

__all__ = [
    "ActionDeclaration",
    "CODE_OWNED_WORLD_SCOPE_FRAGMENT_ARTIFACT_DIGEST",
    "CODE_OWNED_WORLD_SCOPE_FRAGMENT_BYTES",
    "CODE_OWNED_WORLD_SCOPE_FRAGMENT_SEMANTIC_DIGEST",
    "CODE_OWNED_WORLD_SCOPE_FRAGMENTS",
    "EXPECTED_PANEL_IDENTITIES",
    "ExtensionSemantic",
    "ExtensionTemplateRole",
    "GapScope",
    "PlannedActionDeclaration",
    "PostScopeAuthorityRequirement",
    "ScopeGapCode",
    "TaskApplicability",
    "WORLD_SCOPE_FRAGMENT_DOMAIN",
    "WorldScopeBuildReport",
    "WorldScopeFragmentSet",
    "build_code_owned_world_scope_fragments",
    "inspect_world_scope_fragments",
    "parse_world_scope_fragment_set_bytes",
    "world_scope_fragment_artifact_digest_from_bytes",
    "world_scope_fragment_semantic_digest_from_bytes",
]
