"""Live-derived typed W01--W20 fragments for the future eleven-axis scope.

The artifact in this module is deliberately PRE-FREEZE.  It is not a scope
manifest and cannot issue freeze authority.  Its parser accepts bytes only
when an exact rebuild from current code-owned declarations is byte-identical.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
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
from .task_protocol import TASK_EXECUTION_TRUTH, TaskExecutionKind
from .world_registry import EXTENSION_WORLD_REGISTRY, WORLD_REGISTRY, PanelDeclaration
from .worlds.base import CounterfactualOracle, MicroWorld, PublicCatalog, WorldSplit

WORLD_SCOPE_FRAGMENT_SET_SCHEMA = "ucm-world-scope-fragment-set/2"
WORLD_SCOPE_FRAGMENT_DOMAIN = b"UCM_WORLD_SCOPE_FRAGMENT_SET_V2\0"
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
    NEW_CHECK_SCOPE_REFINEMENT = "new_check_scope_refinement"
    NEW_TREATMENT_SCOPE_REFINEMENT = "new_treatment_scope_refinement"


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
    A_W17_EXTENSION = "A-W17-extension-scope-not-closed"
    Q_RESULT_KERNEL = "Q-check-result-kernel-not-typed"
    Q_W16_EXTENSION = "Q-W16-extension-scope-not-closed"
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
    R_FAMILY_ASSIGNMENT = "R-family-assignment-not-frozen"
    R_DATA_BUDGET = "R-training-data-budget-not-typed"
    R_COMPUTE_BUDGET = "R-resource-budget-not-typed"
    R_ISOLATION = "R-isolation-profile-not-typed"
    R_EXTENSION_SCOPE = "R-extension-whole-scope-not-closed"


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

    def to_wire(self) -> dict[str, Any]:
        return {
            "intervention_semantics": self.intervention_semantics,
            "actions": [x.to_wire() for x in self.actions],
        }

    @classmethod
    def from_wire(cls, value: object) -> "ActionAxis":
        body = _exact_object(
            value, frozenset({"intervention_semantics", "actions"}), "A axis"
        )
        if type(body["actions"]) is not list:
            raise ProtocolViolation("A actions must be a list")
        return cls(
            _name(body["intervention_semantics"], "A semantics"),
            tuple(ActionDeclaration.from_wire(x) for x in body["actions"]),
        )


@dataclass(frozen=True, slots=True)
class CheckAxis:
    information_semantics: str
    checks: tuple[CheckDeclaration, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "information_semantics": self.information_semantics,
            "checks": [x.to_wire() for x in self.checks],
        }

    @classmethod
    def from_wire(cls, value: object) -> "CheckAxis":
        body = _exact_object(
            value, frozenset({"information_semantics", "checks"}), "Q axis"
        )
        if type(body["checks"]) is not list:
            raise ProtocolViolation("Q checks must be a list")
        return cls(
            _name(body["information_semantics"], "Q semantics"),
            tuple(CheckDeclaration.from_wire(x) for x in body["checks"]),
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
class ResourceAxis:
    identification: str
    base_candidate_methods: tuple[str, ...]
    split_roles: tuple[SplitRoleDeclaration, ...]
    projection_layers: tuple[str, ...]
    test_split_alias: str
    extension_semantics: ExtensionSemantic
    worker_contracts: tuple[tuple[str, str], ...]
    training_track: str

    def to_wire(self) -> dict[str, Any]:
        return {
            "identification": self.identification,
            "base_candidate_methods": list(self.base_candidate_methods),
            "split_roles": [x.to_wire() for x in self.split_roles],
            "projection_layers": list(self.projection_layers),
            "test_split_alias": self.test_split_alias,
            "extension_semantics": self.extension_semantics.value,
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
                    "extension_semantics",
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
            _enum(ExtensionSemantic, body["extension_semantics"], "R extension"),
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


def _extension(slot: str) -> ExtensionSemantic:
    if slot == "W16":
        if (
            EXTENSION_WORLD_REGISTRY[slot].custody_factory_name
            != "make_w16_extension_custody"
        ):
            raise ProtocolViolation("W16 extension semantic drifted")
        return ExtensionSemantic.NEW_CHECK_SCOPE_REFINEMENT
    if slot == "W17":
        if (
            EXTENSION_WORLD_REGISTRY[slot].custody_factory_name
            != "make_w17_extension_custody"
        ):
            raise ProtocolViolation("W17 extension semantic drifted")
        return ExtensionSemantic.NEW_TREATMENT_SCOPE_REFINEMENT
    return ExtensionSemantic.NONE


def _build_panel(
    slot: str, panel: PanelDeclaration, world: MicroWorld
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
            "counterfactual_is_do_policy_not_observational_conditioning", actions
        ),
        Q=CheckAxis(
            "check_changes_information_availability_after_declared_delay", checks
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
            _extension(slot),
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
    return WorldScopeFragmentSet(
        tuple(
            _build_panel(slot, panel, panel.instantiate())
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
                    "family_assignment",
                    ScopeGapCode.R_FAMILY_ASSIGNMENT,
                    "family-atomic split assignment is not frozen",
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
        if f.world_slot == "W16":
            gaps.append(
                _gap(
                    f,
                    "Q",
                    "S-prime-new-check",
                    ScopeGapCode.Q_W16_EXTENSION,
                    "W16 target S-prime new-check scope is not closed",
                )
            )
        if f.world_slot == "W17":
            gaps.append(
                _gap(
                    f,
                    "A",
                    "S-prime-new-treatment",
                    ScopeGapCode.A_W17_EXTENSION,
                    "W17 target S-prime new-treatment scope is not closed",
                )
            )
        if f.world_slot in {"W16", "W17"}:
            gaps.append(
                _gap(
                    f,
                    "R",
                    "S-prime-eleven-axis",
                    ScopeGapCode.R_EXTENSION_SCOPE,
                    "extension target whole eleven-axis scope is not closed",
                )
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
    "GapScope",
    "PlannedActionDeclaration",
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
