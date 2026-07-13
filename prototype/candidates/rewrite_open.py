"""Typed rewrite/open-component candidate.

This prototype intentionally implements a *small closed algebra* rather than a
``Node(payload)`` or ``Rule(callback)`` escape hatch.  Its native strengths are
evidence-preserving local rewriting, bitemporal cuts, explicit action receipts,
reachability, and fail-closed component wiring.  It deliberately does not claim
probabilistic filtering, physiological forecasting, ``do`` semantics, or
individual counterfactuals.

The persistent authority is the immutable :class:`SourceArtifact` history.
Configurations and proof graphs are reconstructed from an explicit time cut;
derived terms can never mint evidence roots.  Rewrite evaluation is a finite,
monotone least-fixed-point calculation over closed term constructors.  Cycles
therefore need an externally grounded premise and cannot create support from
nothing.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from itertools import combinations, product
import json
from math import isfinite
from typing import Iterable, Mapping, Sequence, TypeAlias

from ..contract import (
    ArchitectureCandidate,
    CandidateManifest,
    CapabilityResult,
    ClockSet,
    ContractError,
    InfoState,
    QueryKind,
    QuerySpec,
    ResultStatus,
    Scope,
    SemanticRole,
    SourceArtifact,
    Track,
    parse_time,
)


_EPOCH = "1970-01-01T00:00:00+00:00"
_ACTION_ROLES = frozenset(
    {
        SemanticRole.PLAN,
        SemanticRole.ORDER,
        SemanticRole.PERFORMED_INTERVENTION,
        SemanticRole.STOPPED_INTERVENTION,
    }
)


class Polarity(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class TermKind(str, Enum):
    PRESENCE = "presence"
    QUANTITY = "quantity"
    CODE = "code"
    TEXT = "text"
    NO_VALUE = "no_value"
    ACTION = "action"
    EFFECT_TOKEN = "effect_token"


class QuantityComparator(str, Enum):
    EXACT = "exact"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"


class ActionPhase(str, Enum):
    PROPOSED = "proposed"
    PLANNED = "planned"
    REQUESTED = "requested"
    ORDERED = "ordered"
    STARTED = "started"
    PARTIALLY_PERFORMED = "partially_performed"
    PERFORMED = "performed"
    PAUSED = "paused"
    REFUSED = "refused"
    CANCELLED = "cancelled"
    STOPPED = "stopped"
    NOT_PERFORMED = "not_performed"


_EFFECT_PHASES = frozenset(
    {
        ActionPhase.STARTED,
        ActionPhase.PARTIALLY_PERFORMED,
        ActionPhase.PERFORMED,
    }
)


class GuardOperator(str, Enum):
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"
    EQ = "eq"
    BETWEEN_CLOSED = "between_closed"


class ConclusionMode(str, Enum):
    PRESENCE = "presence"
    COPY = "copy"
    QUANTITY = "quantity"
    CODE = "code"
    TEXT = "text"
    NO_VALUE = "no_value"


class RuleOutputSemantics(str, Enum):
    EPISTEMIC_DERIVATION = "epistemic_derivation"
    STATE_EFFECT = "state_effect"
    OBSERVATION_EFFECT = "observation_effect"


class RewriteStrategy(str, Enum):
    LEAST_FIXED_POINT = "least_fixed_point"


class CompositionLaw(str, Enum):
    ASSOCIATIVE = "associative"
    COMMUTATIVE = "commutative"
    IDEMPOTENT = "idempotent"
    REGISTRATION_ORDER_INDEPENDENT = "registration_order_independent"


class PortDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"


class PortRole(str, Enum):
    OBSERVATION = "observation"
    REPORTED_STATEMENT = "reported_statement"
    LATENT_STATE = "latent_state"
    ACTION_RECEIPT = "action_receipt"
    EFFECT_TOKEN = "effect_token"
    MODEL_OUTPUT = "model_output"
    POLICY = "policy"
    KNOWLEDGE = "knowledge"


class ScopeBinding(str, Enum):
    SAME_SUBJECT = "same_subject"
    SAME_ENCOUNTER = "same_encounter"
    SAME_SPECIMEN = "same_specimen"
    SAME_DEVICE = "same_device"
    SAME_SITE = "same_site"


class TimeBasis(str, Enum):
    EFFECTIVE = "effective"
    COLLECTION = "collection"
    AVAILABLE = "available"
    RECORDED = "recorded"
    ACTION_EXECUTION = "action_execution"


class OwnershipKind(str, Enum):
    NONE = "none"
    OWNED = "owned"
    BORROWED = "borrowed"
    SHARED_REFERENCE = "shared_reference"


class UncertaintySemantics(str, Enum):
    DETERMINISTIC = "deterministic"
    FOUR_VALUED_EVIDENCE = "four_valued_evidence"
    INTERVAL = "interval"
    SET_VALUED = "set_valued"
    PROBABILITY = "probability"


class ProvenancePolicy(str, Enum):
    PRESERVE_ROOTS = "preserve_roots"
    UNION_ROOTS = "union_roots"
    REQUIRE_RECEIPT = "require_receipt"
    OPAQUE_MODEL_RUN = "opaque_model_run"


class ComponentFamily(str, Enum):
    REWRITE = "rewrite"
    EVIDENCE = "evidence"
    ACTION = "action"
    BRIDGE = "bridge"


@dataclass(frozen=True)
class PresenceTerm:
    concept: str
    scope: Scope
    polarity: Polarity
    semantic_role: SemanticRole

    def __post_init__(self) -> None:
        if not self.concept:
            raise ContractError("PresenceTerm.concept 不得为空")
        if self.polarity is Polarity.UNKNOWN:
            raise ContractError("unknown 必须用 NoValueTerm 表达")


@dataclass(frozen=True)
class QuantityTerm:
    concept: str
    scope: Scope
    magnitude: float
    unit: str
    comparator: QuantityComparator
    polarity: Polarity
    semantic_role: SemanticRole

    def __post_init__(self) -> None:
        if not self.concept or not self.unit:
            raise ContractError("QuantityTerm.concept/unit 不得为空")
        if not isfinite(float(self.magnitude)):
            raise ContractError("QuantityTerm.magnitude 必须有限")
        if self.polarity is Polarity.UNKNOWN:
            raise ContractError("unknown quantity 必须用 NoValueTerm 表达")


@dataclass(frozen=True)
class CodeTerm:
    concept: str
    scope: Scope
    code: str
    polarity: Polarity
    semantic_role: SemanticRole

    def __post_init__(self) -> None:
        if not self.concept or not self.code:
            raise ContractError("CodeTerm.concept/code 不得为空")


@dataclass(frozen=True)
class TextTerm:
    concept: str
    scope: Scope
    text: str
    polarity: Polarity
    semantic_role: SemanticRole

    def __post_init__(self) -> None:
        if not self.concept:
            raise ContractError("TextTerm.concept 不得为空")


@dataclass(frozen=True)
class NoValueTerm:
    concept: str
    scope: Scope
    information_state: InfoState
    semantic_role: SemanticRole

    def __post_init__(self) -> None:
        if not self.concept:
            raise ContractError("NoValueTerm.concept 不得为空")
        if self.information_state in {InfoState.PRESENT, InfoState.ABSENT}:
            raise ContractError("present/absent 不是 no-value reason")


@dataclass(frozen=True)
class ActionTerm:
    action_id: str
    concept: str
    scope: Scope
    phase: ActionPhase
    semantic_role: SemanticRole
    dose: QuantityTerm | CodeTerm | TextTerm | None = None
    effective_start: str = _EPOCH
    effective_end: str | None = None
    available_at: str = _EPOCH

    def __post_init__(self) -> None:
        if not self.action_id or not self.concept:
            raise ContractError("ActionTerm.action_id/concept 不得为空")
        if self.semantic_role not in _ACTION_ROLES:
            raise ContractError("ActionTerm 必须具有 action semantic role")
        start = parse_time(self.effective_start)
        end = parse_time(self.effective_end)
        parse_time(self.available_at)
        if end is not None and start is not None and end < start:
            raise ContractError("action effective_end 早于 effective_start")


@dataclass(frozen=True)
class EffectTokenTerm:
    """An execution receipt projected into an active, cut-local effect token."""

    action_id: str
    concept: str
    scope: Scope
    phase: ActionPhase
    semantic_role: SemanticRole
    active_start: str
    active_end: str | None = None

    def __post_init__(self) -> None:
        if not self.action_id or not self.concept:
            raise ContractError("EffectTokenTerm.action_id/concept 不得为空")
        if self.phase not in _EFFECT_PHASES:
            raise ContractError("只有 started/partial/performed 可形成 EffectToken")
        if self.semantic_role is not SemanticRole.PERFORMED_INTERVENTION:
            raise ContractError("EffectToken 必须来自 performed intervention receipt")
        start = parse_time(self.active_start)
        end = parse_time(self.active_end)
        if end is not None and start is not None and end < start:
            raise ContractError("EffectToken.active_end 早于 active_start")


ClinicalTerm: TypeAlias = (
    PresenceTerm
    | QuantityTerm
    | CodeTerm
    | TextTerm
    | NoValueTerm
    | ActionTerm
    | EffectTokenTerm
)


@dataclass(frozen=True)
class FactPremise:
    concept: str
    polarity: Polarity | None = Polarity.POSITIVE
    term_kind: TermKind | None = None
    unit: str | None = None
    semantic_roles: tuple[SemanticRole, ...] = ()

    def __post_init__(self) -> None:
        if not self.concept:
            raise ContractError("FactPremise.concept 不得为空")
        if self.term_kind in {TermKind.ACTION, TermKind.EFFECT_TOKEN}:
            raise ContractError("action 必须用 ActionPremise")


@dataclass(frozen=True)
class ActionPremise:
    concept: str
    phases: tuple[ActionPhase, ...] = (
        ActionPhase.STARTED,
        ActionPhase.PARTIALLY_PERFORMED,
        ActionPhase.PERFORMED,
    )

    def __post_init__(self) -> None:
        if not self.concept or not self.phases:
            raise ContractError("ActionPremise.concept/phases 不得为空")


Premise: TypeAlias = FactPremise | ActionPremise


@dataclass(frozen=True)
class NumericGuard:
    premise_index: int
    operator: GuardOperator
    lower: float
    upper: float | None = None

    def __post_init__(self) -> None:
        if self.premise_index < 0:
            raise ContractError("guard premise_index 不得为负")
        if not isfinite(float(self.lower)):
            raise ContractError("guard lower 必须有限")
        if self.operator is GuardOperator.BETWEEN_CLOSED:
            if self.upper is None or not isfinite(float(self.upper)):
                raise ContractError("between guard 必须有有限 upper")
            if self.upper < self.lower:
                raise ContractError("between guard upper 小于 lower")
        elif self.upper is not None:
            raise ContractError("非 between guard 不得携带 upper")


@dataclass(frozen=True)
class ConclusionTemplate:
    concept: str
    mode: ConclusionMode = ConclusionMode.PRESENCE
    polarity: Polarity = Polarity.POSITIVE
    premise_index: int | None = None
    magnitude: float | None = None
    unit: str | None = None
    code: str | None = None
    text: str | None = None
    information_state: InfoState | None = None

    def __post_init__(self) -> None:
        if not self.concept:
            raise ContractError("ConclusionTemplate.concept 不得为空")
        if self.mode is ConclusionMode.COPY:
            if self.premise_index is None or self.premise_index < 0:
                raise ContractError("copy conclusion 必须给出 premise_index")
        elif self.premise_index is not None:
            raise ContractError("只有 copy conclusion 可给 premise_index")
        if self.mode is ConclusionMode.QUANTITY:
            if self.magnitude is None or self.unit is None:
                raise ContractError("quantity conclusion 必须给 magnitude/unit")
            if not isfinite(float(self.magnitude)):
                raise ContractError("quantity conclusion magnitude 必须有限")
        elif self.magnitude is not None or self.unit is not None:
            raise ContractError("只有 quantity conclusion 可给 magnitude/unit")
        if self.mode is ConclusionMode.CODE:
            if not self.code:
                raise ContractError("code conclusion 必须给 code")
        elif self.code is not None:
            raise ContractError("只有 code conclusion 可给 code")
        if self.mode is ConclusionMode.TEXT:
            if self.text is None:
                raise ContractError("text conclusion 必须给 text")
        elif self.text is not None:
            raise ContractError("只有 text conclusion 可给 text")
        if self.mode is ConclusionMode.NO_VALUE:
            if self.information_state is None or self.information_state in {
                InfoState.PRESENT,
                InfoState.ABSENT,
            }:
                raise ContractError("no-value conclusion 必须给真正的 no-value state")
        elif self.information_state is not None:
            raise ContractError("只有 no-value conclusion 可给 information_state")


@dataclass(frozen=True)
class RewriteRule:
    rule_id: str
    premises: tuple[Premise, ...]
    conclusion: ConclusionTemplate
    guards: tuple[NumericGuard, ...] = ()
    output_semantics: RuleOutputSemantics = RuleOutputSemantics.EPISTEMIC_DERIVATION

    def __post_init__(self) -> None:
        if not self.rule_id or not self.premises:
            raise ContractError("rewrite rule 必须有 rule_id 和至少一个 premise")
        for premise in self.premises:
            if not isinstance(premise, (FactPremise, ActionPremise)):
                raise ContractError("rewrite premise 必须是封闭 FactPremise/ActionPremise")
        if self.conclusion.mode is ConclusionMode.COPY:
            assert self.conclusion.premise_index is not None
            if self.conclusion.premise_index >= len(self.premises):
                raise ContractError("copy conclusion premise_index 越界")
        for guard in self.guards:
            if guard.premise_index >= len(self.premises):
                raise ContractError("guard premise_index 越界")
        if self.output_semantics in {
            RuleOutputSemantics.STATE_EFFECT,
            RuleOutputSemantics.OBSERVATION_EFFECT,
        }:
            action_premises = [p for p in self.premises if isinstance(p, ActionPremise)]
            if not action_premises:
                raise ContractError("effect rewrite 必须依赖 ActionPremise")
            for premise in action_premises:
                if not set(premise.phases).issubset(_EFFECT_PHASES):
                    raise ContractError("计划/医嘱/停止事件不能生成 effect")


@dataclass(frozen=True)
class DeclaredSubalgebra:
    subalgebra_id: str
    rule_ids: tuple[str, ...]
    laws: tuple[CompositionLaw, ...]

    def __post_init__(self) -> None:
        if not self.subalgebra_id or not self.rule_ids or not self.laws:
            raise ContractError("declared subalgebra 的 id/rules/laws 不得为空")


@dataclass(frozen=True)
class RewriteModule:
    module_id: str
    version: str
    rules: tuple[RewriteRule, ...]
    known_from: str = _EPOCH
    strategy: RewriteStrategy = RewriteStrategy.LEAST_FIXED_POINT
    max_rounds: int = 64
    declared_subalgebras: tuple[DeclaredSubalgebra, ...] = ()

    def __post_init__(self) -> None:
        if not self.module_id or not self.version:
            raise ContractError("RewriteModule.module_id/version 不得为空")
        parse_time(self.known_from)
        if self.strategy is not RewriteStrategy.LEAST_FIXED_POINT:
            raise ContractError("本原型只实现 least_fixed_point")
        if self.max_rounds <= 0:
            raise ContractError("max_rounds 必须为正")
        rule_ids = [rule.rule_id for rule in self.rules]
        if len(set(rule_ids)) != len(rule_ids):
            raise ContractError("module 内 rule_id 重复")
        known = set(rule_ids)
        sub_ids: set[str] = set()
        for sub in self.declared_subalgebras:
            if sub.subalgebra_id in sub_ids:
                raise ContractError("declared subalgebra id 重复")
            sub_ids.add(sub.subalgebra_id)
            unknown = set(sub.rule_ids) - known
            if unknown:
                raise ContractError(f"subalgebra 引用了未知规则: {sorted(unknown)}")


@dataclass(frozen=True)
class Port:
    port_id: str
    direction: PortDirection
    role: PortRole
    concept: str
    scope_binding: ScopeBinding
    unit: str | None
    time_basis: TimeBasis
    ownership: OwnershipKind
    owner_id: str | None
    uncertainty: UncertaintySemantics
    provenance: ProvenancePolicy
    required: bool = True

    def __post_init__(self) -> None:
        if not self.port_id or not self.concept:
            raise ContractError("Port.port_id/concept 不得为空")
        if self.ownership is OwnershipKind.NONE and self.owner_id is not None:
            raise ContractError("ownership=none 时不得给 owner_id")
        if self.ownership is not OwnershipKind.NONE and not self.owner_id:
            raise ContractError("state ownership 必须给 owner_id")


@dataclass(frozen=True)
class OpenComponent:
    component_id: str
    version: str
    family: ComponentFamily
    input_ports: tuple[Port, ...] = ()
    output_ports: tuple[Port, ...] = ()
    rewrite_module_ids: tuple[str, ...] = ()
    owned_state_ids: tuple[str, ...] = ()
    shared_state_ids: tuple[str, ...] = ()
    interaction_domains: tuple[str, ...] = ()
    declared_subalgebras: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.component_id or not self.version:
            raise ContractError("OpenComponent.component_id/version 不得为空")
        ports = (*self.input_ports, *self.output_ports)
        ids = [port.port_id for port in ports]
        if len(set(ids)) != len(ids):
            raise ContractError("component 内 port_id 必须唯一")
        if any(port.direction is not PortDirection.INPUT for port in self.input_ports):
            raise ContractError("input_ports 中存在非 input port")
        if any(port.direction is not PortDirection.OUTPUT for port in self.output_ports):
            raise ContractError("output_ports 中存在非 output port")
        overlap = set(self.owned_state_ids) & set(self.shared_state_ids)
        if overlap:
            raise ContractError(f"state 不能同时 owned/shared: {sorted(overlap)}")


@dataclass(frozen=True)
class PortRef:
    component_id: str
    port_id: str

    def __post_init__(self) -> None:
        if not self.component_id or not self.port_id:
            raise ContractError("PortRef.component_id/port_id 不得为空")


@dataclass(frozen=True)
class Wire:
    source: PortRef
    target: PortRef


@dataclass(frozen=True)
class InteractionDeclaration:
    interaction_id: str
    domain: str
    component_ids: tuple[str, ...]
    rewrite_module_id: str

    def __post_init__(self) -> None:
        if not self.interaction_id or not self.domain or not self.rewrite_module_id:
            raise ContractError("interaction id/domain/module 不得为空")
        if len(set(self.component_ids)) < 2:
            raise ContractError("interaction 至少连接两个不同组件")


@dataclass(frozen=True)
class CompositionSpec:
    composition_id: str
    component_ids: tuple[str, ...]
    wires: tuple[Wire, ...]
    interactions: tuple[InteractionDeclaration, ...] = ()
    declared_subalgebra: str | None = None
    close_boundary: bool = False

    def __post_init__(self) -> None:
        if not self.composition_id or len(set(self.component_ids)) < 1:
            raise ContractError("composition 必须有 id 和至少一个组件")
        if len(set(self.component_ids)) != len(self.component_ids):
            raise ContractError("composition component_ids 重复")


@dataclass(frozen=True)
class ProofNode:
    proof_id: str
    kind: str
    conclusion_digest: str
    root_source_ids: frozenset[str]
    source_families: frozenset[str]
    premise_proof_ids: tuple[str, ...] = ()
    rule_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.proof_id or not self.conclusion_digest or not self.root_source_ids:
            raise ContractError("proof 必须有 id/conclusion/root")
        if self.kind in {"rewrite", "action_effect"} and (
            not self.premise_proof_ids or not self.rule_ref
        ):
            raise ContractError("derived proof 必须有 premises/rule_ref")


# ---------------------------------------------------------------------------
# Fail-closed boundary validation
# ---------------------------------------------------------------------------


def _validate_exact_json(
    value: object,
    path: str,
    *,
    active: set[int] | None = None,
    depth: int = 0,
) -> None:
    """Validate JSON without copying, hashing, coercion, or user callbacks.

    ``SourceArtifact`` deliberately accepts ``Any`` at the repository-wide
    contract boundary.  This candidate is stricter: before an object can reach
    ``deepcopy``/canonical hashing, every value/context/raw-payload node must be
    an *exact* JSON builtin.  In particular, mapping/list subclasses and
    callables are rejected rather than asked to implement copy/iteration
    protocols.  A small depth/cycle guard also prevents adversarial containers
    from turning validation into an unbounded traversal.
    """

    if depth > 128:
        raise ContractError(f"{path} nesting 超过 128 层")
    value_type = type(value)
    if value is None or value_type in {str, bool, int}:
        return
    if value_type is float:
        if not isfinite(value):
            raise ContractError(f"{path} 必须是有限 JSON number")
        return
    if value_type not in {dict, list}:
        kind = "callable" if callable(value) else value_type.__name__
        raise ContractError(f"{path} 只允许 exact JSON builtin；收到 {kind}")

    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        raise ContractError(f"{path} 包含循环 JSON 容器")
    active.add(identity)
    try:
        if value_type is list:
            for index, item in enumerate(value):
                _validate_exact_json(
                    item,
                    f"{path}[{index}]",
                    active=active,
                    depth=depth + 1,
                )
        else:
            for key, item in value.items():
                if type(key) is not str:
                    raise ContractError(f"{path} JSON object key 必须是 exact str")
                _validate_exact_json(
                    item,
                    f"{path}.{key}",
                    active=active,
                    depth=depth + 1,
                )
    finally:
        active.remove(identity)


def _validate_source_artifact_input(artifact: object) -> SourceArtifact:
    """Perform the complete untrusted-artifact preflight before any copy/hash."""

    if type(artifact) is not SourceArtifact:
        raise ContractError("input 必须是 exact SourceArtifact")
    if type(artifact.scope) is not Scope:
        raise ContractError("artifact.scope 必须是 exact Scope")
    if type(artifact.clocks) is not ClockSet:
        raise ContractError("artifact.clocks 必须是 exact ClockSet")
    if type(artifact.semantic_role) is not SemanticRole:
        raise ContractError("artifact.semantic_role 必须是 SemanticRole enum")
    if type(artifact.information_state) is not InfoState:
        raise ContractError("artifact.information_state 必须是 InfoState enum")

    required_strings = {
        "artifact_id": artifact.artifact_id,
        "source_id": artifact.source_id,
        "concept": artifact.concept,
        "mapping_version": artifact.mapping_version,
    }
    for name, value in required_strings.items():
        if type(value) is not str or not value:
            raise ContractError(f"artifact.{name} 必须是非空 exact str")
    for name in ("unit", "method", "source_family", "supersedes"):
        value = getattr(artifact, name)
        if value is not None and type(value) is not str:
            raise ContractError(f"artifact.{name} 必须是 exact str | None")

    for name in (
        "subject_id",
        "encounter_id",
        "specimen_id",
        "device_id",
        "site_id",
        "body_site",
    ):
        value = getattr(artifact.scope, name)
        if value is not None and type(value) is not str:
            raise ContractError(f"artifact.scope.{name} 必须是 exact str | None")
    if not artifact.scope.subject_id:
        raise ContractError("artifact.scope.subject_id 不得为空")

    for name in (
        "effective_start",
        "effective_end",
        "collected_at",
        "available_at",
        "recorded_at",
        "expires_at",
    ):
        value = getattr(artifact.clocks, name)
        if value is not None and type(value) is not str:
            raise ContractError(f"artifact.clocks.{name} 必须是 exact str | None")

    reliability = artifact.reliability
    if reliability is not None:
        if type(reliability) not in {int, float} or isinstance(reliability, bool):
            raise ContractError("artifact.reliability 必须是 exact number | None")
        if not isfinite(float(reliability)) or not 0.0 <= reliability <= 1.0:
            raise ContractError("artifact.reliability 必须在 [0,1]")
    if type(artifact.context) is not dict:
        raise ContractError("artifact.context 必须是 exact JSON object")
    if type(artifact.raw_payload) is not dict:
        raise ContractError("artifact.raw_payload 必须是 exact JSON object")
    _validate_exact_json(artifact.value, "artifact.value")
    _validate_exact_json(artifact.context, "artifact.context")
    _validate_exact_json(artifact.raw_payload, "artifact.raw_payload")

    # Re-run the ordinary dataclass invariants only after the entire reachable
    # payload has passed the non-executing exact-builtin check.
    artifact.scope.__post_init__()
    artifact.clocks.__post_init__()
    artifact.__post_init__()
    return artifact


_CLOSED_ENUM_TYPES = {
    Polarity,
    TermKind,
    QuantityComparator,
    ActionPhase,
    GuardOperator,
    ConclusionMode,
    RuleOutputSemantics,
    RewriteStrategy,
    CompositionLaw,
    PortDirection,
    PortRole,
    ScopeBinding,
    TimeBasis,
    OwnershipKind,
    UncertaintySemantics,
    ProvenancePolicy,
    ComponentFamily,
    SemanticRole,
    InfoState,
}
_CLOSED_DATACLASS_TYPES = {
    FactPremise,
    ActionPremise,
    NumericGuard,
    ConclusionTemplate,
    RewriteRule,
    DeclaredSubalgebra,
    RewriteModule,
    Port,
    OpenComponent,
    PortRef,
    Wire,
    InteractionDeclaration,
    CompositionSpec,
}


def _validate_closed_typed_graph(
    value: object,
    path: str,
    *,
    active: set[int] | None = None,
) -> None:
    """Reject foreign/nested executable values before equality/copy/hash."""

    if callable(value):
        raise ContractError(f"{path} 包含 foreign callback/callable")
    value_type = type(value)
    if value is None or value_type in {str, bool, int}:
        return
    if value_type is float:
        if not isfinite(value):
            raise ContractError(f"{path} 包含非有限 float")
        return
    if value_type in _CLOSED_ENUM_TYPES:
        return

    active = set() if active is None else active
    if value_type in {tuple, frozenset}:
        identity = id(value)
        if identity in active:
            raise ContractError(f"{path} 包含循环 typed container")
        active.add(identity)
        try:
            for index, item in enumerate(value):
                _validate_closed_typed_graph(item, f"{path}[{index}]", active=active)
        finally:
            active.remove(identity)
        return

    if value_type not in _CLOSED_DATACLASS_TYPES:
        raise ContractError(
            f"{path} 超出封闭 typed graph；收到 {value_type.__name__}"
        )
    identity = id(value)
    if identity in active:
        raise ContractError(f"{path} 包含循环 typed dataclass")
    active.add(identity)
    try:
        for item in fields(value):
            _validate_closed_typed_graph(
                getattr(value, item.name),
                f"{path}.{item.name}",
                active=active,
            )
    finally:
        active.remove(identity)


def _revalidate_closed_typed_graph(value: object) -> None:
    """Re-run constructor invariants bottom-up after safe structural preflight."""

    value_type = type(value)
    if value_type in {tuple, frozenset}:
        for item in value:
            _revalidate_closed_typed_graph(item)
    elif value_type in _CLOSED_DATACLASS_TYPES:
        for item in fields(value):
            _revalidate_closed_typed_graph(getattr(value, item.name))
        _validate_closed_dataclass_field_types(value)
        post_init = value_type.__dict__.get("__post_init__")
        if post_init is not None:
            post_init(value)


def _validate_closed_dataclass_field_types(value: object) -> None:
    """Enforce field-specific enum/scalar types after inert graph validation."""

    def string(item: object, label: str, *, optional: bool = False) -> None:
        if optional and item is None:
            return
        if type(item) is not str or not item:
            raise ContractError(f"{label} 必须是非空 exact str")

    def exact_tuple(
        item: object,
        member_types: tuple[type[object], ...],
        label: str,
    ) -> None:
        if type(item) is not tuple or any(type(member) not in member_types for member in item):
            expected = "/".join(member.__name__ for member in member_types)
            raise ContractError(f"{label} 必须是 tuple[{expected}, ...]")

    if type(value) is FactPremise:
        string(value.concept, "FactPremise.concept")
        if value.polarity is not None and type(value.polarity) is not Polarity:
            raise ContractError("FactPremise.polarity 必须是 Polarity | None")
        if value.term_kind is not None and type(value.term_kind) is not TermKind:
            raise ContractError("FactPremise.term_kind 必须是 TermKind | None")
        string(value.unit, "FactPremise.unit", optional=True)
        exact_tuple(value.semantic_roles, (SemanticRole,), "FactPremise.semantic_roles")
    elif type(value) is ActionPremise:
        string(value.concept, "ActionPremise.concept")
        exact_tuple(value.phases, (ActionPhase,), "ActionPremise.phases")
    elif type(value) is NumericGuard:
        if type(value.premise_index) is not int:
            raise ContractError("NumericGuard.premise_index 必须是 exact int")
        if type(value.operator) is not GuardOperator:
            raise ContractError("NumericGuard.operator 必须是 GuardOperator")
        if type(value.lower) not in {int, float} or isinstance(value.lower, bool):
            raise ContractError("NumericGuard.lower 必须是 exact number")
        if value.upper is not None and (
            type(value.upper) not in {int, float} or isinstance(value.upper, bool)
        ):
            raise ContractError("NumericGuard.upper 必须是 exact number | None")
    elif type(value) is ConclusionTemplate:
        string(value.concept, "ConclusionTemplate.concept")
        if type(value.mode) is not ConclusionMode:
            raise ContractError("ConclusionTemplate.mode 必须是 ConclusionMode")
        if type(value.polarity) is not Polarity:
            raise ContractError("ConclusionTemplate.polarity 必须是 Polarity")
        if value.premise_index is not None and type(value.premise_index) is not int:
            raise ContractError("ConclusionTemplate.premise_index 必须是 exact int | None")
        if value.magnitude is not None and (
            type(value.magnitude) not in {int, float} or isinstance(value.magnitude, bool)
        ):
            raise ContractError("ConclusionTemplate.magnitude 必须是 exact number | None")
        for name in ("unit", "code", "text"):
            string(getattr(value, name), f"ConclusionTemplate.{name}", optional=True)
        if value.information_state is not None and type(value.information_state) is not InfoState:
            raise ContractError("ConclusionTemplate.information_state 必须是 InfoState | None")
    elif type(value) is RewriteRule:
        string(value.rule_id, "RewriteRule.rule_id")
        exact_tuple(value.premises, (FactPremise, ActionPremise), "RewriteRule.premises")
        if type(value.conclusion) is not ConclusionTemplate:
            raise ContractError("RewriteRule.conclusion 必须是 ConclusionTemplate")
        exact_tuple(value.guards, (NumericGuard,), "RewriteRule.guards")
        if type(value.output_semantics) is not RuleOutputSemantics:
            raise ContractError("RewriteRule.output_semantics 必须是 RuleOutputSemantics")
    elif type(value) is DeclaredSubalgebra:
        string(value.subalgebra_id, "DeclaredSubalgebra.subalgebra_id")
        exact_tuple(value.rule_ids, (str,), "DeclaredSubalgebra.rule_ids")
        exact_tuple(value.laws, (CompositionLaw,), "DeclaredSubalgebra.laws")
    elif type(value) is RewriteModule:
        string(value.module_id, "RewriteModule.module_id")
        string(value.version, "RewriteModule.version")
        string(value.known_from, "RewriteModule.known_from")
        exact_tuple(value.rules, (RewriteRule,), "RewriteModule.rules")
        if type(value.strategy) is not RewriteStrategy:
            raise ContractError("RewriteModule.strategy 必须是 RewriteStrategy")
        if type(value.max_rounds) is not int:
            raise ContractError("RewriteModule.max_rounds 必须是 exact int")
        exact_tuple(
            value.declared_subalgebras,
            (DeclaredSubalgebra,),
            "RewriteModule.declared_subalgebras",
        )
    elif type(value) is Port:
        string(value.port_id, "Port.port_id")
        string(value.concept, "Port.concept")
        string(value.unit, "Port.unit", optional=True)
        string(value.owner_id, "Port.owner_id", optional=True)
        for field_name, expected in (
            ("direction", PortDirection),
            ("role", PortRole),
            ("scope_binding", ScopeBinding),
            ("time_basis", TimeBasis),
            ("ownership", OwnershipKind),
            ("uncertainty", UncertaintySemantics),
            ("provenance", ProvenancePolicy),
        ):
            if type(getattr(value, field_name)) is not expected:
                raise ContractError(f"Port.{field_name} 必须是 {expected.__name__}")
        if type(value.required) is not bool:
            raise ContractError("Port.required 必须是 exact bool")
    elif type(value) is OpenComponent:
        string(value.component_id, "OpenComponent.component_id")
        string(value.version, "OpenComponent.version")
        if type(value.family) is not ComponentFamily:
            raise ContractError("OpenComponent.family 必须是 ComponentFamily")
        exact_tuple(value.input_ports, (Port,), "OpenComponent.input_ports")
        exact_tuple(value.output_ports, (Port,), "OpenComponent.output_ports")
        for name in (
            "rewrite_module_ids",
            "owned_state_ids",
            "shared_state_ids",
            "interaction_domains",
            "declared_subalgebras",
        ):
            exact_tuple(getattr(value, name), (str,), f"OpenComponent.{name}")
    elif type(value) is PortRef:
        string(value.component_id, "PortRef.component_id")
        string(value.port_id, "PortRef.port_id")
    elif type(value) is Wire:
        if type(value.source) is not PortRef or type(value.target) is not PortRef:
            raise ContractError("Wire.source/target 必须是 PortRef")
    elif type(value) is InteractionDeclaration:
        string(value.interaction_id, "InteractionDeclaration.interaction_id")
        string(value.domain, "InteractionDeclaration.domain")
        string(value.rewrite_module_id, "InteractionDeclaration.rewrite_module_id")
        exact_tuple(value.component_ids, (str,), "InteractionDeclaration.component_ids")
    elif type(value) is CompositionSpec:
        string(value.composition_id, "CompositionSpec.composition_id")
        exact_tuple(value.component_ids, (str,), "CompositionSpec.component_ids")
        exact_tuple(value.wires, (Wire,), "CompositionSpec.wires")
        exact_tuple(
            value.interactions,
            (InteractionDeclaration,),
            "CompositionSpec.interactions",
        )
        string(
            value.declared_subalgebra,
            "CompositionSpec.declared_subalgebra",
            optional=True,
        )
        if type(value.close_boundary) is not bool:
            raise ContractError("CompositionSpec.close_boundary 必须是 exact bool")


def _validate_query_spec_input(spec: object) -> QuerySpec:
    """Validate the closed query control plane before enum dispatch."""

    if type(spec) is not QuerySpec:
        raise ContractError("input 必须是 exact QuerySpec")
    if type(spec.kind) is not QueryKind:
        raise ContractError("query.kind 必须是 QueryKind enum")
    for name in ("query_id", "target", "subject_id", "as_known_at", "knowledge_version"):
        value = getattr(spec, name)
        if type(value) is not str or not value:
            raise ContractError(f"query.{name} 必须是非空 exact str")
    for name in ("valid_at", "task", "model_version"):
        value = getattr(spec, name)
        if value is not None and type(value) is not str:
            raise ContractError(f"query.{name} 必须是 exact str | None")
    if spec.intervention is not None:
        if type(spec.intervention) is not dict:
            raise ContractError("query.intervention 必须是 exact JSON object | None")
        _validate_exact_json(spec.intervention, "query.intervention")
    if spec.horizon_hours is not None:
        if type(spec.horizon_hours) not in {int, float} or isinstance(
            spec.horizon_hours, bool
        ):
            raise ContractError("query.horizon_hours 必须是 exact number | None")
        if not isfinite(float(spec.horizon_hours)):
            raise ContractError("query.horizon_hours 必须有限")
    for name in ("requested_guarantees", "assumptions"):
        value = getattr(spec, name)
        if type(value) is not tuple or any(type(item) is not str for item in value):
            raise ContractError(f"query.{name} 必须是 tuple[exact str, ...]")
    if type(spec.seed) is not int:
        raise ContractError("query.seed 必须是 exact int")
    spec.__post_init__()
    return spec


@dataclass
class _Configuration:
    terms: set[ClinicalTerm] = field(default_factory=set)
    proofs: dict[str, ProofNode] = field(default_factory=dict)
    term_proofs: dict[ClinicalTerm, list[str]] = field(default_factory=dict)
    root_signatures: dict[ClinicalTerm, set[frozenset[str]]] = field(default_factory=dict)
    trace: list[dict[str, object]] = field(default_factory=list)
    rounds: int = 0
    diagnostics: dict[str, object] = field(default_factory=dict)


def _enum_value(value: object) -> object:
    return value.value if isinstance(value, Enum) else value


def _scope_dict(scope: Scope) -> dict[str, object]:
    return {
        "subject_id": scope.subject_id,
        "encounter_id": scope.encounter_id,
        "specimen_id": scope.specimen_id,
        "device_id": scope.device_id,
        "site_id": scope.site_id,
        "body_site": scope.body_site,
    }


def _term_kind(term: ClinicalTerm) -> TermKind:
    if isinstance(term, PresenceTerm):
        return TermKind.PRESENCE
    if isinstance(term, QuantityTerm):
        return TermKind.QUANTITY
    if isinstance(term, CodeTerm):
        return TermKind.CODE
    if isinstance(term, TextTerm):
        return TermKind.TEXT
    if isinstance(term, NoValueTerm):
        return TermKind.NO_VALUE
    if isinstance(term, ActionTerm):
        return TermKind.ACTION
    if isinstance(term, EffectTokenTerm):
        return TermKind.EFFECT_TOKEN
    raise ContractError("未知 term constructor")


def _term_concept(term: ClinicalTerm) -> str:
    return term.concept


def _term_scope(term: ClinicalTerm) -> Scope:
    return term.scope


def _term_role(term: ClinicalTerm) -> SemanticRole:
    return term.semantic_role


def _term_polarity(term: ClinicalTerm) -> Polarity:
    if isinstance(term, NoValueTerm):
        return Polarity.UNKNOWN
    if isinstance(term, (ActionTerm, EffectTokenTerm)):
        return Polarity.POSITIVE
    return term.polarity


def _term_dict(term: ClinicalTerm) -> dict[str, object]:
    base: dict[str, object] = {
        "kind": _term_kind(term).value,
        "concept": term.concept,
        "scope": _scope_dict(term.scope),
        "semantic_role": term.semantic_role.value,
    }
    if isinstance(term, PresenceTerm):
        base["polarity"] = term.polarity.value
    elif isinstance(term, QuantityTerm):
        base.update(
            {
                "magnitude": term.magnitude,
                "unit": term.unit,
                "comparator": term.comparator.value,
                "polarity": term.polarity.value,
            }
        )
    elif isinstance(term, CodeTerm):
        base.update({"code": term.code, "polarity": term.polarity.value})
    elif isinstance(term, TextTerm):
        base.update({"text": term.text, "polarity": term.polarity.value})
    elif isinstance(term, NoValueTerm):
        base.update(
            {
                "information_state": term.information_state.value,
                "polarity": Polarity.UNKNOWN.value,
            }
        )
    elif isinstance(term, ActionTerm):
        base.update(
            {
                "action_id": term.action_id,
                "phase": term.phase.value,
                "polarity": Polarity.POSITIVE.value,
                "dose": _term_dict(term.dose) if term.dose is not None else None,
                "effective_start": term.effective_start,
                "effective_end": term.effective_end,
                "available_at": term.available_at,
            }
        )
    elif isinstance(term, EffectTokenTerm):
        base.update(
            {
                "action_id": term.action_id,
                "phase": term.phase.value,
                "polarity": Polarity.POSITIVE.value,
                "active_start": term.active_start,
                "active_end": term.active_end,
            }
        )
    return base


def _term_unit(term: ClinicalTerm) -> str | None:
    if isinstance(term, QuantityTerm):
        return term.unit
    return None


def _term_value_signature(term: ClinicalTerm) -> dict[str, object]:
    """Return the closed value identity used for same-time conflict checks."""

    if isinstance(term, PresenceTerm):
        return {"kind": "presence", "polarity": term.polarity.value}
    if isinstance(term, QuantityTerm):
        return {
            "kind": "quantity",
            "magnitude": term.magnitude,
            "comparator": term.comparator.value,
            "polarity": term.polarity.value,
        }
    if isinstance(term, CodeTerm):
        return {
            "kind": "code",
            "code": term.code,
            "polarity": term.polarity.value,
        }
    if isinstance(term, TextTerm):
        return {
            "kind": "text",
            "text": term.text,
            "polarity": term.polarity.value,
        }
    raise ContractError("action/no-value/effect token 不是可比较 observed value")


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _term_digest(term: ClinicalTerm) -> str:
    return _digest(_term_dict(term))


def _artifact_semantic_dict(artifact: SourceArtifact) -> dict[str, object]:
    """Canonical semantic delivery identity, intentionally excluding artifact_id."""

    return {
        "source_id": artifact.source_id,
        "semantic_role": artifact.semantic_role.value,
        "concept": artifact.concept,
        "scope": _scope_dict(artifact.scope),
        "clocks": asdict(artifact.clocks),
        "information_state": artifact.information_state.value,
        "value": deepcopy(artifact.value),
        "unit": artifact.unit,
        "method": artifact.method,
        "context": deepcopy(dict(artifact.context)),
        "reliability": artifact.reliability,
        "source_family": artifact.source_family,
        "supersedes": artifact.supersedes,
        "raw_payload": deepcopy(dict(artifact.raw_payload)),
        "mapping_version": artifact.mapping_version,
    }


def _polarity_from_artifact(artifact: SourceArtifact) -> Polarity:
    if artifact.information_state is InfoState.ABSENT:
        return Polarity.NEGATIVE
    if artifact.information_state is InfoState.PRESENT:
        if isinstance(artifact.value, bool) and not artifact.value:
            return Polarity.NEGATIVE
        return Polarity.POSITIVE
    return Polarity.UNKNOWN


def _artifact_is_withheld(artifact: SourceArtifact) -> bool:
    """Return whether semantic/source bytes are intentionally non-disclosable."""

    if (
        artifact.information_state is InfoState.MASKED
        or artifact.semantic_role is SemanticRole.MASKED_ARTIFACT
    ):
        return True
    visibility = artifact.context.get("visibility")
    if visibility in {"masked", "withheld", "redacted"}:
        return True
    return any(
        artifact.context.get(flag) is True
        for flag in ("masked", "withheld", "redacted")
    )


def _action_phase(artifact: SourceArtifact) -> ActionPhase:
    raw_phase = artifact.context.get("phase")
    defaults = {
        SemanticRole.PLAN: ActionPhase.PLANNED,
        SemanticRole.ORDER: ActionPhase.ORDERED,
        SemanticRole.PERFORMED_INTERVENTION: ActionPhase.PERFORMED,
        SemanticRole.STOPPED_INTERVENTION: ActionPhase.STOPPED,
    }
    if raw_phase is None:
        return defaults[artifact.semantic_role]
    try:
        phase = ActionPhase(str(raw_phase))
    except ValueError as exc:
        raise ContractError(f"未知 action phase: {raw_phase!r}") from exc
    allowed = {
        SemanticRole.PLAN: {ActionPhase.PROPOSED, ActionPhase.PLANNED},
        SemanticRole.ORDER: {ActionPhase.REQUESTED, ActionPhase.ORDERED},
        SemanticRole.PERFORMED_INTERVENTION: set(_EFFECT_PHASES),
        SemanticRole.STOPPED_INTERVENTION: {
            ActionPhase.PAUSED,
            ActionPhase.REFUSED,
            ActionPhase.CANCELLED,
            ActionPhase.STOPPED,
            ActionPhase.NOT_PERFORMED,
        },
    }[artifact.semantic_role]
    if phase not in allowed:
        raise ContractError(
            f"semantic_role={artifact.semantic_role.value} 与 phase={phase.value} 不兼容"
        )
    return phase


def _closed_scalar_term(
    artifact: SourceArtifact,
    *,
    semantic_role: SemanticRole | None = None,
) -> ClinicalTerm:
    if _artifact_is_withheld(artifact):
        return NoValueTerm(
            artifact.concept,
            artifact.scope,
            InfoState.MASKED,
            SemanticRole.MASKED_ARTIFACT,
        )
    role = semantic_role or artifact.semantic_role
    polarity = _polarity_from_artifact(artifact)
    if artifact.information_state not in {InfoState.PRESENT, InfoState.ABSENT}:
        return NoValueTerm(artifact.concept, artifact.scope, artifact.information_state, role)
    if artifact.information_state is InfoState.ABSENT:
        return PresenceTerm(artifact.concept, artifact.scope, Polarity.NEGATIVE, role)
    value = artifact.value
    if isinstance(value, bool):
        return PresenceTerm(
            artifact.concept,
            artifact.scope,
            Polarity.POSITIVE if value else Polarity.NEGATIVE,
            role,
        )
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if artifact.unit is None:
            raise ContractError("numeric observation 必须显式声明 unit（无量纲用 '1'）")
        return QuantityTerm(
            artifact.concept,
            artifact.scope,
            float(value),
            artifact.unit,
            QuantityComparator.EXACT,
            polarity,
            role,
        )
    if isinstance(value, str):
        return CodeTerm(artifact.concept, artifact.scope, value, polarity, role)
    if isinstance(value, Mapping):
        allowed = set(value)
        if "magnitude" in value and allowed <= {"magnitude", "unit", "comparator"}:
            unit = value.get("unit", artifact.unit)
            if not isinstance(unit, str) or not unit:
                raise ContractError("quantity mapping 必须给 unit")
            comparator_raw = value.get("comparator", QuantityComparator.EXACT.value)
            try:
                comparator = QuantityComparator(str(comparator_raw))
            except ValueError as exc:
                raise ContractError(f"未知 quantity comparator: {comparator_raw!r}") from exc
            magnitude = value.get("magnitude")
            if not isinstance(magnitude, (int, float)) or isinstance(magnitude, bool):
                raise ContractError("quantity mapping magnitude 必须是 number")
            return QuantityTerm(
                artifact.concept,
                artifact.scope,
                float(magnitude),
                unit,
                comparator,
                polarity,
                role,
            )
        if allowed == {"code"} and isinstance(value.get("code"), str):
            return CodeTerm(
                artifact.concept, artifact.scope, str(value["code"]), polarity, role
            )
        if allowed == {"text"} and isinstance(value.get("text"), str):
            return TextTerm(
                artifact.concept, artifact.scope, str(value["text"]), polarity, role
            )
    raise ContractError(
        "semantic value 超出封闭构造；raw_payload 已隔离，需版本化 adapter 后再摄取"
    )


def _artifact_to_term(artifact: SourceArtifact) -> ClinicalTerm:
    if _artifact_is_withheld(artifact):
        return NoValueTerm(
            artifact.concept,
            artifact.scope,
            InfoState.MASKED,
            SemanticRole.MASKED_ARTIFACT,
        )
    if artifact.semantic_role in _ACTION_ROLES:
        phase = _action_phase(artifact)
        action_id_raw = artifact.context.get("action_id", artifact.source_id)
        if not isinstance(action_id_raw, str) or not action_id_raw:
            raise ContractError("action_id 必须是非空字符串")
        dose: QuantityTerm | CodeTerm | TextTerm | None = None
        if artifact.value is not None:
            scalar = _closed_scalar_term(artifact)
            if isinstance(scalar, (QuantityTerm, CodeTerm, TextTerm)):
                dose = scalar
            elif isinstance(scalar, PresenceTerm):
                # A boolean action receipt is an execution marker, not a dose.
                dose = None
            else:
                raise ContractError("action dose 只能是 quantity/code/text")
        return ActionTerm(
            str(action_id_raw),
            artifact.concept,
            artifact.scope,
            phase,
            artifact.semantic_role,
            dose,
            artifact.clocks.effective_start,
            artifact.clocks.effective_end,
            artifact.clocks.available_at,
        )
    return _closed_scalar_term(artifact)


def _term_matches(
    term: ClinicalTerm,
    premise: Premise,
    output_semantics: RuleOutputSemantics,
) -> bool:
    if _term_concept(term) != premise.concept:
        return False
    if isinstance(premise, ActionPremise):
        if output_semantics in {
            RuleOutputSemantics.STATE_EFFECT,
            RuleOutputSemantics.OBSERVATION_EFFECT,
        }:
            return isinstance(term, EffectTokenTerm) and term.phase in premise.phases
        return isinstance(term, ActionTerm) and term.phase in premise.phases
    if isinstance(term, (ActionTerm, EffectTokenTerm)):
        return False
    if premise.term_kind is not None and _term_kind(term) is not premise.term_kind:
        return False
    if premise.polarity is not None and _term_polarity(term) is not premise.polarity:
        return False
    if premise.semantic_roles and _term_role(term) not in premise.semantic_roles:
        return False
    if premise.unit is not None:
        return isinstance(term, QuantityTerm) and term.unit == premise.unit
    return True


def _guard_holds(guard: NumericGuard, terms: Sequence[ClinicalTerm]) -> bool:
    term = terms[guard.premise_index]
    if not isinstance(term, QuantityTerm):
        return False
    value = term.magnitude
    if guard.operator is GuardOperator.GT:
        return value > guard.lower
    if guard.operator is GuardOperator.GE:
        return value >= guard.lower
    if guard.operator is GuardOperator.LT:
        return value < guard.lower
    if guard.operator is GuardOperator.LE:
        return value <= guard.lower
    if guard.operator is GuardOperator.EQ:
        return value == guard.lower
    assert guard.upper is not None
    return guard.lower <= value <= guard.upper


def _conclusion_term(
    conclusion: ConclusionTemplate,
    premises: Sequence[ClinicalTerm],
) -> ClinicalTerm:
    scope = _term_scope(premises[0])
    role = SemanticRole.DETERMINISTIC_DERIVATION
    if conclusion.mode is ConclusionMode.PRESENCE:
        return PresenceTerm(conclusion.concept, scope, conclusion.polarity, role)
    if conclusion.mode is ConclusionMode.COPY:
        assert conclusion.premise_index is not None
        source = premises[conclusion.premise_index]
        if isinstance(source, PresenceTerm):
            return PresenceTerm(conclusion.concept, scope, conclusion.polarity, role)
        if isinstance(source, QuantityTerm):
            return QuantityTerm(
                conclusion.concept,
                scope,
                source.magnitude,
                source.unit,
                source.comparator,
                conclusion.polarity,
                role,
            )
        if isinstance(source, CodeTerm):
            return CodeTerm(conclusion.concept, scope, source.code, conclusion.polarity, role)
        if isinstance(source, TextTerm):
            return TextTerm(conclusion.concept, scope, source.text, conclusion.polarity, role)
        if isinstance(source, NoValueTerm):
            return NoValueTerm(conclusion.concept, scope, source.information_state, role)
        raise ContractError("ActionTerm 不能用 COPY 隐式转成 patient fact")
    if conclusion.mode is ConclusionMode.QUANTITY:
        assert conclusion.magnitude is not None and conclusion.unit is not None
        return QuantityTerm(
            conclusion.concept,
            scope,
            conclusion.magnitude,
            conclusion.unit,
            QuantityComparator.EXACT,
            conclusion.polarity,
            role,
        )
    if conclusion.mode is ConclusionMode.CODE:
        assert conclusion.code is not None
        return CodeTerm(conclusion.concept, scope, conclusion.code, conclusion.polarity, role)
    if conclusion.mode is ConclusionMode.TEXT:
        assert conclusion.text is not None
        return TextTerm(conclusion.concept, scope, conclusion.text, conclusion.polarity, role)
    assert conclusion.information_state is not None
    return NoValueTerm(conclusion.concept, scope, conclusion.information_state, role)


def _rule_graph_analysis(module: RewriteModule) -> dict[str, object]:
    """Return SCC and potential conflict diagnostics without claiming more laws."""

    graph: dict[str, set[str]] = {}
    for rule in module.rules:
        target = rule.conclusion.concept
        graph.setdefault(target, set())
        for premise in rule.premises:
            graph.setdefault(premise.concept, set()).add(target)

    index = 0
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    sccs: list[list[str]] = []

    def strongconnect(node: str) -> None:
        nonlocal index
        indices[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in graph.get(node, set()):
            if neighbor not in indices:
                strongconnect(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indices[neighbor])
        if lowlinks[node] == indices[node]:
            component: list[str] = []
            while True:
                item = stack.pop()
                on_stack.remove(item)
                component.append(item)
                if item == node:
                    break
            sccs.append(sorted(component))

    for node in sorted(graph):
        if node not in indices:
            strongconnect(node)

    cycles: list[list[str]] = []
    for component in sccs:
        if len(component) > 1 or (
            len(component) == 1 and component[0] in graph.get(component[0], set())
        ):
            cycles.append(component)

    by_concept: dict[str, set[Polarity]] = {}
    for rule in module.rules:
        by_concept.setdefault(rule.conclusion.concept, set()).add(rule.conclusion.polarity)
    potential_conflicts = sorted(
        concept
        for concept, polarities in by_concept.items()
        if {Polarity.POSITIVE, Polarity.NEGATIVE}.issubset(polarities)
    )
    return {
        "epistemic_cycles_requiring_external_roots": cycles,
        "potential_conflicting_conclusions": potential_conflicts,
        "termination_argument": (
            "finite closed constructors + no zero-premise rule + set semantics + "
            "one proof per (term, root-set)"
        ),
        "declared_subalgebras": [
            {
                "subalgebra_id": sub.subalgebra_id,
                "rule_ids": list(sub.rule_ids),
                "laws": [law.value for law in sub.laws],
            }
            for sub in module.declared_subalgebras
        ],
    }


def _root_proof(term: ClinicalTerm, artifact: SourceArtifact) -> ProofNode:
    roots = frozenset({artifact.source_id})
    families = frozenset(
        {artifact.source_family} if artifact.source_family is not None else set()
    )
    data = {
        "kind": "root",
        "term": _term_dict(term),
        "root": artifact.source_id,
        "artifact_id": artifact.artifact_id,
    }
    return ProofNode(
        proof_id=f"p-{_digest(data)[:24]}",
        kind="root",
        conclusion_digest=_term_digest(term),
        root_source_ids=roots,
        source_families=families,
    )


def _rewrite_proof(
    term: ClinicalTerm,
    premise_proofs: Sequence[ProofNode],
    module: RewriteModule,
    rule: RewriteRule,
) -> ProofNode:
    roots = frozenset().union(*(proof.root_source_ids for proof in premise_proofs))
    families = frozenset().union(*(proof.source_families for proof in premise_proofs))
    premise_ids = tuple(sorted(proof.proof_id for proof in premise_proofs))
    rule_ref = f"{module.module_id}@{module.version}:{rule.rule_id}"
    data = {
        "kind": "rewrite",
        "term": _term_dict(term),
        "roots": sorted(roots),
        "rule_ref": rule_ref,
        # The representative proof path is retained, but paths do not mint roots.
        "premises": list(premise_ids),
    }
    return ProofNode(
        proof_id=f"p-{_digest(data)[:24]}",
        kind="rewrite",
        conclusion_digest=_term_digest(term),
        root_source_ids=roots,
        source_families=families,
        premise_proof_ids=premise_ids,
        rule_ref=rule_ref,
    )


def _action_effect_proof(
    token: EffectTokenTerm,
    receipt_proof: ProofNode,
) -> ProofNode:
    rule_ref = "kernel@v1:performed-receipt-to-active-effect-token"
    data = {
        "kind": "action_effect",
        "term": _term_dict(token),
        "roots": sorted(receipt_proof.root_source_ids),
        "receipt": receipt_proof.proof_id,
        "rule_ref": rule_ref,
    }
    return ProofNode(
        proof_id=f"p-{_digest(data)[:24]}",
        kind="action_effect",
        conclusion_digest=_term_digest(token),
        root_source_ids=receipt_proof.root_source_ids,
        source_families=receipt_proof.source_families,
        premise_proof_ids=(receipt_proof.proof_id,),
        rule_ref=rule_ref,
    )


def _time_iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.astimezone(timezone.utc).isoformat()


class RewriteOpenCandidate(ArchitectureCandidate):
    """Finite typed rewrite + open component prototype."""

    VERSION = "0.2.0"
    _SUPPORTED_KNOWLEDGE_VERSIONS = frozenset({"knowledge-v1"})
    _SUPPORTED_TASKS = frozenset({"diagnosis", "medication_safety"})
    _SUPPORTED_QUERY_GUARANTEES = frozenset(
        {
            "evidence_roots",
            "rooted_support",
            "independence_explicit",
            "solver_diagnostics",
            "raw_roundtrip",
        }
    )

    def __init__(self, track: Track = Track.NATIVE) -> None:
        super().__init__(track)
        self._artifacts: dict[str, SourceArtifact] = {}
        self._source_index: dict[str, str] = {}
        self._retractions: dict[str, set[datetime]] = {}
        self._modules: dict[tuple[str, str], RewriteModule] = {}
        self._components: dict[str, OpenComponent] = {}
        self._compositions: dict[str, CompositionSpec] = {}
        self._results: dict[str, CapabilityResult] = {}
        self._rebuild_receipt: dict[str, object] | None = None

    @property
    def manifest(self) -> CandidateManifest:
        return CandidateManifest(
            candidate_id="typed-rewrite-open",
            version=self.VERSION,
            formal_signature=(
                "PresenceTerm|QuantityTerm|CodeTerm|TextTerm|NoValueTerm|ActionTerm|EffectTokenTerm",
                "FactPremise|ActionPremise + NumericGuard -> ConclusionTemplate",
                "RewriteModule",
                "Port + OpenComponent + Wire + InteractionDeclaration",
            ),
            execution_semantics=(
                "immutable source history with available/recorded/effective cuts",
                "grounded monotone least-fixed-point local rewriting",
                "four-valued positive/negative evidence projection",
                "typed fail-closed open-component wiring",
                "only explicitly declared subalgebras expose composition laws",
            ),
            companion_layers=(),
            primitive_profile={
                "typed_object_value_constructors": (
                    "PresenceTerm",
                    "QuantityTerm",
                    "CodeTerm",
                    "TextTerm",
                    "NoValueTerm",
                    "ActionTerm",
                    "EffectTokenTerm",
                ),
                "state_update_operators": (
                    "source_ingest",
                    "retraction_delta",
                    "guarded_local_rewrite",
                    "least_fixed_point",
                ),
                "time_visibility_operators": (
                    "available_cut",
                    "recorded_cut",
                    "effective_interval_cut",
                    "knowledge_known_from_cut",
                ),
                "uncertainty_belief_operators": (
                    "positive_root_set",
                    "negative_root_set",
                    "explicit_unknown",
                    "localized_conflict",
                ),
                "intervention_counterfactual_operators": (),
                "composition_wiring_operators": (
                    "typed_wire",
                    "explicit_interaction",
                    "declared_subalgebra",
                ),
                "query_readout_operators": (
                    "project",
                    "replay_as_then",
                    "reinterpret_now",
                    "reachability",
                    "explain",
                ),
                "persistence_replay_operators": (
                    "immutable_artifact_store",
                    "clean_rebuild",
                ),
                "foreign_semantic_escape_hatches": (),
            },
            foreign_boundaries=(),
            declared_query_capabilities=(
                QueryKind.PROJECT,
                QueryKind.REPLAY_AS_THEN,
                QueryKind.REINTERPRET_NOW,
                QueryKind.REACHABILITY,
            ),
            failure_types=(
                ResultStatus.INVALID,
                ResultStatus.INSUFFICIENT,
                ResultStatus.CONFLICTING,
                ResultStatus.UNSUPPORTED,
                ResultStatus.NUMERICAL_FAILURE,
                ResultStatus.OUT_OF_MODEL,
            ),
        )

    def _remember(self, result_id: str, result: CapabilityResult) -> CapabilityResult:
        self._results[result_id] = deepcopy(result)
        return result

    def _invalid(self, operation: str, message: str, **extra: object) -> CapabilityResult:
        return CapabilityResult(
            status=ResultStatus.INVALID,
            validation="invalid",
            capability="native",
            epistemic="not_applicable",
            coverage_status="unknown",
            computation="not_applicable",
            diagnostics={"operation": operation, "error": message, **extra},
            versions={"candidate": self.VERSION},
        )

    def _unsupported(self, spec: QuerySpec) -> CapabilityResult:
        return CapabilityResult(
            status=ResultStatus.UNSUPPORTED,
            validation="valid",
            capability="unsupported",
            epistemic="not_applicable",
            coverage_status="out_of_model",
            identification=(
                "not_identified"
                if spec.kind in {QueryKind.INTERVENE, QueryKind.COUNTERFACTUAL}
                else "not_applicable"
            ),
            computation="not_applicable",
            assumptions=list(spec.assumptions),
            coverage={"boundary": "rewrite/evidence semantics only"},
            time_cut={"as_known_at": spec.as_known_at, "valid_at": spec.valid_at},
            diagnostics={
                "operation": "query",
                "missing_capability": spec.kind.value,
                "reason": (
                    "closed rewrite reachability is not probabilistic state estimation, "
                    "forecasting, intervention identification, or same-unit counterfactual"
                ),
                "state_mutated": False,
            },
            versions={"candidate": self.VERSION},
        )

    def _unsupported_query_controls(self, spec: QuerySpec) -> CapabilityResult | None:
        """Fail closed when a version/task/guarantee has no native semantics."""

        unsupported: dict[str, object] = {}
        if spec.knowledge_version not in self._SUPPORTED_KNOWLEDGE_VERSIONS:
            unsupported["knowledge_version"] = {
                "requested": spec.knowledge_version,
                "supported": sorted(self._SUPPORTED_KNOWLEDGE_VERSIONS),
            }
        if spec.model_version not in {None, self.VERSION}:
            unsupported["model_version"] = {
                "requested": spec.model_version,
                "supported": [self.VERSION],
            }
        if spec.task is not None and spec.task not in self._SUPPORTED_TASKS:
            unsupported["task"] = {
                "requested": spec.task,
                "supported": sorted(self._SUPPORTED_TASKS),
            }
        unknown_guarantees = sorted(
            set(spec.requested_guarantees) - self._SUPPORTED_QUERY_GUARANTEES
        )
        if unknown_guarantees:
            unsupported["requested_guarantees"] = {
                "requested_but_not_provided": unknown_guarantees,
                "supported": sorted(self._SUPPORTED_QUERY_GUARANTEES),
            }
        if not unsupported:
            return None
        return CapabilityResult(
            status=ResultStatus.UNSUPPORTED,
            validation="valid",
            capability="unsupported",
            epistemic="not_applicable",
            coverage_status="partial",
            identification="not_applicable",
            computation="not_applicable",
            value_kind="none",
            assumptions=list(spec.assumptions),
            coverage={
                "native_family": "typed_rewrite_open",
                "control_plane_coverage": "partial",
            },
            time_cut={
                "as_known_at": spec.as_known_at,
                "valid_at": spec.valid_at,
            },
            diagnostics={
                "operation": "query",
                "unsupported_controls": unsupported,
                "reason": "requested query control has no declared native semantics",
                "state_mutated": False,
            },
            versions={
                "candidate": self.VERSION,
                "knowledge_requested": spec.knowledge_version,
                "model_requested": spec.model_version,
            },
        )

    def ingest(self, artifact: SourceArtifact) -> CapabilityResult:
        return self._ingest(artifact, allow_missing_supersedes=False)

    def _ingest(
        self,
        artifact: SourceArtifact,
        *,
        allow_missing_supersedes: bool,
    ) -> CapabilityResult:
        try:
            safe_artifact = _validate_source_artifact_input(artifact)
            frozen = deepcopy(safe_artifact)
            # Validate the closed semantic adapter before persistence. raw_payload is
            # preserved but never consulted by this conversion.
            term = _artifact_to_term(frozen)
        except (ContractError, TypeError, ValueError, AssertionError, RecursionError) as exc:
            return self._invalid("ingest", str(exc), quarantined=True)

        existing = self._artifacts.get(frozen.artifact_id)
        if existing is not None:
            if existing == frozen:
                result = CapabilityResult(
                    status=ResultStatus.OK,
                    value_kind="ingest_receipt",
                    value={
                        "artifact_id": frozen.artifact_id,
                        "source_id": frozen.source_id,
                        "idempotent": True,
                    },
                    evidence_witness={"root_sources": [frozen.source_id]},
                    native_witness={"kind": "immutable_source_root"},
                    diagnostics={"duplicate_delivery": "same artifact_id and bytes"},
                    versions={"candidate": self.VERSION},
                )
                return self._remember(f"ingest:{frozen.artifact_id}", result)
            return self._invalid(
                "ingest", "artifact_id collision with different immutable content"
            )

        prior_artifact_id = self._source_index.get(frozen.source_id)
        if prior_artifact_id is not None:
            prior = self._artifacts[prior_artifact_id]
            if _artifact_semantic_dict(prior) == _artifact_semantic_dict(frozen):
                result = CapabilityResult(
                    status=ResultStatus.OK,
                    value_kind="ingest_receipt",
                    value={
                        "artifact_id": prior.artifact_id,
                        "delivery_alias": frozen.artifact_id,
                        "source_id": frozen.source_id,
                        "idempotent": True,
                    },
                    evidence_witness={"root_sources": [frozen.source_id]},
                    native_witness={"kind": "deduplicated_source_root"},
                    diagnostics={"duplicate_delivery": "same stable source_id"},
                    versions={"candidate": self.VERSION},
                )
                return self._remember(f"ingest:{frozen.artifact_id}", result)
            return self._invalid(
                "ingest",
                "source_id collision; correction requires a new source_id and supersedes",
            )

        if frozen.supersedes is not None:
            target = self._resolve_artifact_ref(frozen.supersedes)
            if target is None and not allow_missing_supersedes:
                return self._invalid(
                    "ingest", f"supersedes target 不存在: {frozen.supersedes}"
                )
            if target is not None and target.scope.subject_id != frozen.scope.subject_id:
                return self._invalid("ingest", "correction 不得跨 subject supersede")

        self._artifacts[frozen.artifact_id] = frozen
        self._source_index[frozen.source_id] = frozen.artifact_id
        result = CapabilityResult(
            status=ResultStatus.OK,
            value_kind="ingest_receipt",
            value={
                "artifact_id": frozen.artifact_id,
                "source_id": frozen.source_id,
                "term_digest": _term_digest(term),
                "idempotent": False,
            },
            evidence_witness={
                "root_sources": [frozen.source_id],
                "source_families": (
                    [frozen.source_family] if frozen.source_family is not None else []
                ),
            },
            native_witness={
                "kind": "closed_term_constructor",
                "term": _term_dict(term),
            },
            diagnostics={"raw_payload_used_for_semantics": False},
            versions={
                "candidate": self.VERSION,
                "mapping": frozen.mapping_version,
            },
        )
        return self._remember(f"ingest:{frozen.artifact_id}", result)

    def _resolve_artifact_ref(self, reference: str) -> SourceArtifact | None:
        if reference in self._artifacts:
            return self._artifacts[reference]
        artifact_id = self._source_index.get(reference)
        return self._artifacts.get(artifact_id) if artifact_id is not None else None

    def retract(self, source_id: str, known_at: str) -> CapabilityResult:
        if type(source_id) is not str or not source_id:
            return self._invalid("retract", "source_id 必须是非空 exact str")
        if type(known_at) is not str:
            return self._invalid("retract", "known_at 必须是 exact str")
        if source_id not in self._source_index:
            return self._invalid("retract", f"未知 source_id: {source_id}")
        try:
            cut = parse_time(known_at)
        except (ContractError, ValueError) as exc:
            return self._invalid("retract", str(exc))
        assert cut is not None
        target = self._artifacts[self._source_index[source_id]]
        recorded = parse_time(target.clocks.recorded_at)
        available = parse_time(target.clocks.available_at)
        assert recorded is not None and available is not None
        if cut < recorded or cut < available:
            return self._invalid(
                "retract",
                "retraction tombstone 不得早于被撤回 artifact 的 available/recorded time",
                source_id=source_id,
                artifact_available_at=_time_iso(available),
                artifact_recorded_at=_time_iso(recorded),
                requested_known_at=_time_iso(cut),
                state_mutated=False,
            )
        moments = self._retractions.setdefault(source_id, set())
        idempotent = cut in moments
        moments.add(cut)
        result = CapabilityResult(
            status=ResultStatus.OK,
            value_kind="retraction_receipt",
            value={
                "source_id": source_id,
                "known_at": _time_iso(cut),
                "idempotent": idempotent,
            },
            evidence_witness={"retracted_root": source_id},
            native_witness={"kind": "immutable_retraction_delta"},
            diagnostics={"clinical_negative_created": False},
            versions={"candidate": self.VERSION},
        )
        return self._remember(f"retract:{source_id}:{_time_iso(cut)}", result)

    def register_module(self, module: object) -> CapabilityResult:
        try:
            _validate_closed_typed_graph(module, "module")
            _revalidate_closed_typed_graph(module)
        except (ContractError, TypeError, ValueError, AssertionError, RecursionError) as exc:
            return self._invalid("register_module", str(exc), quarantined=True)
        if type(module) is RewriteModule:
            module_key = (module.module_id, module.version)
            existing = self._modules.get(module_key)
            if existing is not None:
                if existing == module:
                    return CapabilityResult(
                        status=ResultStatus.OK,
                        value_kind="module_receipt",
                        value={"module_id": module.module_id, "idempotent": True},
                        native_witness={"kind": "closed_rewrite_module"},
                        versions={"candidate": self.VERSION, "module": module.version},
                    )
                return self._invalid(
                    "register_module", "module_id collision with different definition"
                )
            analysis = _rule_graph_analysis(module)
            self._modules[module_key] = deepcopy(module)
            return CapabilityResult(
                status=ResultStatus.OK,
                value_kind="module_receipt",
                value={
                    "module_id": module.module_id,
                    "version": module.version,
                    "rule_count": len(module.rules),
                    "idempotent": False,
                },
                native_witness={
                    "kind": "closed_rewrite_module",
                    "analysis": analysis,
                },
                diagnostics={
                    "foreign_callback": False,
                    "operator_expansion": {
                        "rules": len(module.rules),
                        "premises": sum(len(rule.premises) for rule in module.rules),
                        "guards": sum(len(rule.guards) for rule in module.rules),
                    },
                },
                versions={"candidate": self.VERSION, "module": module.version},
            )
        if type(module) is OpenComponent:
            existing_component = self._components.get(module.component_id)
            if existing_component is not None:
                if existing_component == module:
                    return CapabilityResult(
                        status=ResultStatus.OK,
                        value_kind="component_receipt",
                        value={"component_id": module.component_id, "idempotent": True},
                        native_witness={"kind": "typed_open_component"},
                        versions={"candidate": self.VERSION, "component": module.version},
                    )
                return self._invalid(
                    "register_module", "component_id collision with different definition"
                )
            self._components[module.component_id] = deepcopy(module)
            unresolved = sorted(
                reference
                for reference in module.rewrite_module_ids
                if not self._module_ref_exists(reference)
            )
            return CapabilityResult(
                status=ResultStatus.OK,
                value_kind="component_receipt",
                value={
                    "component_id": module.component_id,
                    "version": module.version,
                    "ports": len(module.input_ports) + len(module.output_ports),
                    "idempotent": False,
                },
                native_witness={
                    "kind": "typed_open_component",
                    "unresolved_modules": unresolved,
                },
                diagnostics={
                    "registration_order_semantics": "deferred reference validation",
                    "foreign_callback": False,
                },
                versions={"candidate": self.VERSION, "component": module.version},
            )
        return self._invalid(
            "register_module",
            "只接受封闭 RewriteModule 或 OpenComponent dataclass",
            received_type=type(module).__name__,
        )

    def compose(self, spec: CompositionSpec) -> CapabilityResult:
        try:
            _validate_closed_typed_graph(spec, "composition")
            _revalidate_closed_typed_graph(spec)
        except (ContractError, TypeError, ValueError, AssertionError, RecursionError) as exc:
            return self._invalid("compose", str(exc), quarantined=True)
        if type(spec) is not CompositionSpec:
            return self._invalid("compose", "输入必须是 exact CompositionSpec")
        existing = self._compositions.get(spec.composition_id)
        if existing is not None:
            if existing == spec:
                return CapabilityResult(
                    status=ResultStatus.OK,
                    value_kind="composition_receipt",
                    value={"composition_id": spec.composition_id, "idempotent": True},
                    native_witness={"kind": "typed_wiring"},
                    versions={"candidate": self.VERSION},
                )
            return self._invalid(
                "compose", "composition_id collision with different definition"
            )

        missing_components = sorted(set(spec.component_ids) - set(self._components))
        if missing_components:
            return self._invalid(
                "compose", "composition 引用了未知组件", missing_components=missing_components
            )
        components = [self._components[item] for item in spec.component_ids]
        unresolved_modules = sorted(
            {
                module_id
                for component in components
                for module_id in component.rewrite_module_ids
                if not self._module_ref_exists(module_id)
            }
        )
        if unresolved_modules:
            return self._invalid(
                "compose",
                "component 引用的 rewrite module 尚未注册",
                missing_modules=unresolved_modules,
            )

        ownership: dict[str, list[str]] = {}
        for component in components:
            for state_id in component.owned_state_ids:
                ownership.setdefault(state_id, []).append(component.component_id)
        conflicts = {
            state_id: sorted(owners)
            for state_id, owners in ownership.items()
            if len(owners) > 1
        }
        if conflicts:
            return self._invalid(
                "compose", "同一 state 有多个 owner", ownership_conflicts=conflicts
            )
        shared_references = {
            state_id
            for component in components
            for state_id in component.shared_state_ids
        }
        unowned_shared = sorted(shared_references - set(ownership))
        if unowned_shared:
            return CapabilityResult(
                status=ResultStatus.UNSUPPORTED,
                validation="valid",
                capability="unsupported",
                coverage_status="partial",
                diagnostics={
                    "operation": "compose",
                    "reason": "shared state reference has no unique owner in composition",
                    "unowned_shared_states": unowned_shared,
                    "state_mutated": False,
                },
                versions={"candidate": self.VERSION},
            )

        wire_errors: list[dict[str, object]] = []
        wired_targets: set[tuple[str, str]] = set()
        for wire in spec.wires:
            source = self._find_port(wire.source)
            target = self._find_port(wire.target)
            if source is None or target is None:
                wire_errors.append(
                    {"wire": asdict(wire), "mismatch": ["unknown_port"]}
                )
                continue
            mismatches = self._port_mismatches(source, target)
            if mismatches:
                wire_errors.append(
                    {"wire": asdict(wire), "mismatch": mismatches}
                )
            else:
                wired_targets.add((wire.target.component_id, wire.target.port_id))
        if wire_errors:
            return self._invalid(
                "compose", "typed port 不兼容", wire_errors=wire_errors
            )

        missing_required_ports = sorted(
            (component.component_id, port.port_id)
            for component in components
            for port in component.input_ports
            if port.required and (component.component_id, port.port_id) not in wired_targets
        )
        if missing_required_ports and spec.close_boundary:
            return CapabilityResult(
                status=ResultStatus.UNSUPPORTED,
                validation="valid",
                capability="unsupported",
                coverage_status="partial",
                value_kind="none",
                diagnostics={
                    "operation": "compose",
                    "reason": "required input ports are unwired",
                    "missing_ports": missing_required_ports,
                    "state_mutated": False,
                },
                versions={"candidate": self.VERSION},
            )

        required_interactions: set[tuple[str, tuple[str, ...]]] = set()
        for left_index, left in enumerate(components):
            for right in components[left_index + 1 :]:
                for domain in set(left.interaction_domains) & set(right.interaction_domains):
                    required_interactions.add(
                        (domain, tuple(sorted((left.component_id, right.component_id))))
                    )
        declared: set[tuple[str, tuple[str, ...]]] = set()
        interaction_errors: list[dict[str, object]] = []
        for interaction in spec.interactions:
            for left, right in combinations(sorted(set(interaction.component_ids)), 2):
                declared.add((interaction.domain, (left, right)))
            if not set(interaction.component_ids).issubset(spec.component_ids):
                interaction_errors.append(
                    {
                        "interaction_id": interaction.interaction_id,
                        "reason": "component outside composition",
                    }
                )
            if not self._module_ref_exists(interaction.rewrite_module_id):
                interaction_errors.append(
                    {
                        "interaction_id": interaction.interaction_id,
                        "reason": "interaction module not registered",
                    }
                )
        if interaction_errors:
            return self._invalid(
                "compose", "interaction declaration 无效", errors=interaction_errors
            )
        missing_interactions = sorted(required_interactions - declared)
        if missing_interactions:
            return CapabilityResult(
                status=ResultStatus.UNSUPPORTED,
                validation="valid",
                capability="unsupported",
                coverage_status="partial",
                value_kind="none",
                diagnostics={
                    "operation": "compose",
                    "reason": "required interaction is undeclared; no additive fallback",
                    "missing_interactions": missing_interactions,
                    "state_mutated": False,
                },
                versions={"candidate": self.VERSION},
            )

        exposed_laws: list[str] = []
        if spec.declared_subalgebra is not None:
            matching = [
                sub
                for module in self._current_modules()
                for sub in module.declared_subalgebras
                if sub.subalgebra_id == spec.declared_subalgebra
            ]
            if not matching or any(
                spec.declared_subalgebra not in component.declared_subalgebras
                for component in components
            ):
                return CapabilityResult(
                    status=ResultStatus.UNSUPPORTED,
                    validation="valid",
                    capability="unsupported",
                    coverage_status="partial",
                    diagnostics={
                        "operation": "compose",
                        "reason": "composition law not declared by all participating components",
                        "subalgebra": spec.declared_subalgebra,
                        "state_mutated": False,
                    },
                    versions={"candidate": self.VERSION},
                )
            exposed_laws = sorted(
                {law.value for sub in matching for law in sub.laws}
            )

        self._compositions[spec.composition_id] = deepcopy(spec)
        return CapabilityResult(
            status=ResultStatus.OK,
            value_kind="composition_receipt",
            value={
                "composition_id": spec.composition_id,
                "components": sorted(spec.component_ids),
                "wires": len(spec.wires),
                "interactions": sorted(
                    interaction.interaction_id for interaction in spec.interactions
                ),
                "exposed_input_ports": [
                    {"component_id": component_id, "port_id": port_id}
                    for component_id, port_id in missing_required_ports
                ],
                "idempotent": False,
            },
            native_witness={
                "kind": "typed_wiring",
                "validated_dimensions": [
                    "direction",
                    "role",
                    "concept",
                    "scope",
                    "unit",
                    "time",
                    "state_owner",
                    "uncertainty",
                    "provenance",
                ],
                "declared_laws_only": exposed_laws,
            },
            diagnostics={"implicit_interaction": False, "foreign_callback": False},
            versions={"candidate": self.VERSION},
        )

    def _find_port(self, reference: PortRef) -> Port | None:
        component = self._components.get(reference.component_id)
        if component is None:
            return None
        return next(
            (
                port
                for port in (*component.input_ports, *component.output_ports)
                if port.port_id == reference.port_id
            ),
            None,
        )

    def _module_ref_exists(self, reference: str) -> bool:
        """Resolve ``module`` or the explicit ``module@version`` closed reference."""

        if "@" in reference:
            module_id, version = reference.rsplit("@", 1)
            return (module_id, version) in self._modules
        return any(module_id == reference for module_id, _ in self._modules)

    def _current_modules(self) -> list[RewriteModule]:
        latest: dict[str, RewriteModule] = {}
        for module in self._modules.values():
            prior = latest.get(module.module_id)
            if prior is None or (
                parse_time(module.known_from),
                module.version,
            ) > (
                parse_time(prior.known_from),
                prior.version,
            ):
                latest[module.module_id] = module
        return sorted(latest.values(), key=lambda item: (item.module_id, item.version))

    @staticmethod
    def _port_mismatches(source: Port, target: Port) -> list[str]:
        mismatches: list[str] = []
        if source.direction is not PortDirection.OUTPUT:
            mismatches.append("source_direction")
        if target.direction is not PortDirection.INPUT:
            mismatches.append("target_direction")
        comparisons = {
            "role": source.role == target.role,
            "concept": source.concept == target.concept,
            "scope": source.scope_binding == target.scope_binding,
            "unit": source.unit == target.unit,
            "time": source.time_basis == target.time_basis,
            "uncertainty": source.uncertainty == target.uncertainty,
            "provenance": source.provenance == target.provenance,
        }
        mismatches.extend(key for key, matches in comparisons.items() if not matches)
        if source.ownership is OwnershipKind.OWNED:
            if target.ownership not in {
                OwnershipKind.BORROWED,
                OwnershipKind.SHARED_REFERENCE,
            }:
                mismatches.append("state_ownership_mode")
            if source.owner_id != target.owner_id:
                mismatches.append("state_owner")
        elif source.ownership != target.ownership or source.owner_id != target.owner_id:
            mismatches.append("state_owner")
        return sorted(set(mismatches))

    def _visible_artifacts(
        self,
        *,
        subject_id: str,
        known_at: datetime,
        valid_at: datetime,
    ) -> tuple[list[SourceArtifact], dict[str, list[str]]]:
        preliminary: list[SourceArtifact] = []
        excluded: dict[str, list[str]] = {}
        for artifact in self._artifacts.values():
            reasons: list[str] = []
            if artifact.scope.subject_id != subject_id:
                reasons.append("different_subject")
            available = parse_time(artifact.clocks.available_at)
            recorded = parse_time(artifact.clocks.recorded_at)
            effective_start = parse_time(artifact.clocks.effective_start)
            effective_end = parse_time(artifact.clocks.effective_end)
            expires = parse_time(artifact.clocks.expires_at)
            assert available is not None and recorded is not None and effective_start is not None
            if available > known_at:
                reasons.append("not_yet_available")
            if recorded > known_at:
                reasons.append("not_yet_recorded")
            if effective_start > valid_at:
                reasons.append("future_effective")
            if (
                artifact.semantic_role not in _ACTION_ROLES
                and effective_end is not None
                and effective_end <= valid_at
            ):
                reasons.append("effective_interval_ended")
            if (
                artifact.semantic_role not in _ACTION_ROLES
                and expires is not None
                and expires < valid_at
            ):
                reasons.append("expired")
            if any(moment <= known_at for moment in self._retractions.get(artifact.source_id, set())):
                reasons.append("retracted_at_cut")
            if reasons:
                excluded[artifact.artifact_id] = reasons
            else:
                preliminary.append(artifact)

        visible_ids = {artifact.artifact_id for artifact in preliminary}
        visible_sources = {artifact.source_id for artifact in preliminary}
        superseded_refs = {
            artifact.supersedes
            for artifact in preliminary
            if artifact.supersedes is not None
        }
        result: list[SourceArtifact] = []
        for artifact in preliminary:
            if artifact.artifact_id in superseded_refs or artifact.source_id in superseded_refs:
                excluded.setdefault(artifact.artifact_id, []).append("superseded_at_cut")
            else:
                result.append(artifact)
        # The variables document that both stable reference forms are checked.
        del visible_ids, visible_sources
        result.sort(key=lambda item: (item.clocks.recorded_at, item.artifact_id))
        return result, excluded

    def _active_modules(self, spec: QuerySpec) -> list[RewriteModule]:
        if spec.kind is QueryKind.REPLAY_AS_THEN:
            cut = parse_time(spec.as_known_at)
            assert cut is not None
            eligible = [
                module
                for module in self._modules.values()
                if (parse_time(module.known_from) or datetime.min.replace(tzinfo=timezone.utc))
                <= cut
            ]
            latest: dict[str, RewriteModule] = {}
            for module in eligible:
                prior = latest.get(module.module_id)
                if prior is None or (
                    parse_time(module.known_from),
                    module.version,
                ) > (
                    parse_time(prior.known_from),
                    prior.version,
                ):
                    latest[module.module_id] = module
            modules = list(latest.values())
        else:
            modules = self._current_modules()
        return sorted(modules, key=lambda module: (module.module_id, module.version))

    def _build_configuration(
        self,
        artifacts: Sequence[SourceArtifact],
        modules: Sequence[RewriteModule],
        valid_at: datetime,
    ) -> _Configuration:
        config = _Configuration()
        action_roots: list[tuple[ActionTerm, ProofNode]] = []
        for artifact in artifacts:
            term = _artifact_to_term(artifact)
            proof = _root_proof(term, artifact)
            config.terms.add(term)
            config.proofs[proof.proof_id] = proof
            config.term_proofs.setdefault(term, []).append(proof.proof_id)
            config.root_signatures.setdefault(term, set()).add(proof.root_source_ids)
            config.trace.append(
                {
                    "op": "root",
                    "artifact_id": artifact.artifact_id,
                    "source_id": artifact.source_id,
                    "term_digest": proof.conclusion_digest,
                    "proof_id": proof.proof_id,
                }
            )
            if isinstance(term, ActionTerm):
                action_roots.append((term, proof))

        # Only explicit STOP/CANCEL receipts can close an already materialized
        # performed effect.  A later PLAN/ORDER/REFUSAL is evidence about an
        # action lifecycle, not a time machine that erases execution.
        closing_events: dict[str, list[ActionTerm]] = {}
        for action, _ in action_roots:
            if action.phase in {ActionPhase.STOPPED, ActionPhase.CANCELLED}:
                moment = parse_time(action.effective_start)
                if moment is not None and moment <= valid_at:
                    closing_events.setdefault(action.action_id, []).append(action)
        for action, receipt_proof in action_roots:
            if action.phase not in _EFFECT_PHASES:
                continue
            start = parse_time(action.effective_start)
            end = parse_time(action.effective_end)
            assert start is not None
            closed = any(
                closing.concept == action.concept
                and closing.scope == action.scope
                and start
                <= (parse_time(closing.effective_start) or start)
                <= valid_at
                for closing in closing_events.get(action.action_id, ())
            )
            # Effective intervals are half-open: [start, end).
            if start > valid_at or (end is not None and end <= valid_at) or closed:
                continue
            token = EffectTokenTerm(
                action.action_id,
                action.concept,
                action.scope,
                action.phase,
                SemanticRole.PERFORMED_INTERVENTION,
                action.effective_start,
                action.effective_end,
            )
            token_proof = _action_effect_proof(token, receipt_proof)
            config.terms.add(token)
            config.proofs[token_proof.proof_id] = token_proof
            config.term_proofs.setdefault(token, []).append(token_proof.proof_id)
            config.root_signatures.setdefault(token, set()).add(
                token_proof.root_source_ids
            )
            config.trace.append(
                {
                    "op": "action_effect_token",
                    "action_id": action.action_id,
                    "receipt_proof_id": receipt_proof.proof_id,
                    "proof_id": token_proof.proof_id,
                    "term_digest": token_proof.conclusion_digest,
                }
            )

        total_round_limit = sum(module.max_rounds for module in modules) or 1
        # One extra dry convergence check avoids classifying a term produced in
        # the last permitted rewrite round as a non-terminating computation.
        for round_number in range(1, total_round_limit + 2):
            changed = False
            snapshot_terms = sorted(config.terms, key=_term_digest)
            for module in modules:
                for rule in sorted(module.rules, key=lambda item: item.rule_id):
                    matches: list[list[ClinicalTerm]] = []
                    for premise in rule.premises:
                        matches.append(
                            [
                                term
                                for term in snapshot_terms
                                if _term_matches(term, premise, rule.output_semantics)
                            ]
                        )
                    if any(not group for group in matches):
                        continue
                    for premise_terms in product(*matches):
                        # Local rewrite never joins two patients/specimens/encounters by
                        # merely sharing a concept name.
                        if any(
                            _term_scope(term) != _term_scope(premise_terms[0])
                            for term in premise_terms[1:]
                        ):
                            continue
                        if not all(_guard_holds(guard, premise_terms) for guard in rule.guards):
                            continue
                        try:
                            conclusion = _conclusion_term(rule.conclusion, premise_terms)
                        except ContractError as exc:
                            config.diagnostics.setdefault("rule_failures", []).append(
                                {"rule_id": rule.rule_id, "error": str(exc)}
                            )
                            continue
                        proof_choices = [config.term_proofs[term] for term in premise_terms]
                        for chosen_ids in product(*proof_choices):
                            chosen = [config.proofs[proof_id] for proof_id in chosen_ids]
                            proof = _rewrite_proof(conclusion, chosen, module, rule)
                            # Every derived statement must remain externally grounded.
                            if not proof.root_source_ids:
                                config.diagnostics.setdefault("rootless_rewrites", []).append(
                                    rule.rule_id
                                )
                                continue
                            signatures = config.root_signatures.setdefault(conclusion, set())
                            if proof.root_source_ids in signatures:
                                continue
                            signatures.add(proof.root_source_ids)
                            config.terms.add(conclusion)
                            config.proofs[proof.proof_id] = proof
                            config.term_proofs.setdefault(conclusion, []).append(proof.proof_id)
                            config.trace.append(
                                {
                                    "op": "rewrite",
                                    "module_id": module.module_id,
                                    "module_version": module.version,
                                    "rule_id": rule.rule_id,
                                    "premise_proof_ids": list(proof.premise_proof_ids),
                                    "proof_id": proof.proof_id,
                                    "term_digest": proof.conclusion_digest,
                                    "roots": sorted(proof.root_source_ids),
                                }
                            )
                            changed = True
            config.rounds = round_number
            if not changed:
                break
            if round_number > total_round_limit:
                config.diagnostics["nontermination"] = {
                    "reason": "least fixed point did not converge within closed module budget",
                    "round_limit": total_round_limit,
                }
                break
        return config

    @staticmethod
    def _action_diagnostics(terms: Iterable[ClinicalTerm]) -> dict[str, object]:
        actions: dict[str, list[ActionTerm]] = {}
        for term in terms:
            if isinstance(term, ActionTerm):
                actions.setdefault(term.action_id, []).append(term)
        allowed: dict[ActionPhase, set[ActionPhase]] = {
            ActionPhase.PROPOSED: {
                ActionPhase.PLANNED,
                ActionPhase.REQUESTED,
                ActionPhase.ORDERED,
                ActionPhase.CANCELLED,
                ActionPhase.REFUSED,
            },
            ActionPhase.PLANNED: {
                ActionPhase.REQUESTED,
                ActionPhase.ORDERED,
                ActionPhase.STARTED,
                ActionPhase.CANCELLED,
                ActionPhase.REFUSED,
            },
            ActionPhase.REQUESTED: {
                ActionPhase.ORDERED,
                ActionPhase.STARTED,
                ActionPhase.REFUSED,
                ActionPhase.CANCELLED,
            },
            ActionPhase.ORDERED: {
                ActionPhase.STARTED,
                ActionPhase.PARTIALLY_PERFORMED,
                ActionPhase.PERFORMED,
                ActionPhase.REFUSED,
                ActionPhase.CANCELLED,
            },
            ActionPhase.STARTED: {
                ActionPhase.PARTIALLY_PERFORMED,
                ActionPhase.PERFORMED,
                ActionPhase.PAUSED,
                ActionPhase.STOPPED,
                ActionPhase.CANCELLED,
            },
            ActionPhase.PARTIALLY_PERFORMED: {
                ActionPhase.PERFORMED,
                ActionPhase.PAUSED,
                ActionPhase.STOPPED,
                ActionPhase.CANCELLED,
            },
            ActionPhase.PERFORMED: {
                ActionPhase.STOPPED,
                ActionPhase.CANCELLED,
            },
            ActionPhase.PAUSED: {ActionPhase.STARTED, ActionPhase.STOPPED},
            ActionPhase.REFUSED: set(),
            ActionPhase.CANCELLED: set(),
            ActionPhase.STOPPED: set(),
            ActionPhase.NOT_PERFORMED: set(),
        }
        invalid: list[dict[str, str]] = []
        projection: list[dict[str, object]] = []
        for action_id, events in sorted(actions.items()):
            events.sort(
                key=lambda item: (
                    parse_time(item.effective_start)
                    or datetime.min.replace(tzinfo=timezone.utc),
                    parse_time(item.available_at)
                    or datetime.min.replace(tzinfo=timezone.utc),
                    item.phase.value,
                    _term_digest(item),
                )
            )
            identities = {
                (event.concept, event.scope)
                for event in events
            }
            if len(identities) != 1:
                invalid.append(
                    {
                        "action_id": action_id,
                        "from": "identity",
                        "to": "conflicting_concept_or_scope",
                    }
                )
            phases = [event.phase for event in events]
            for before, after in zip(phases, phases[1:]):
                if after not in allowed[before]:
                    invalid.append(
                        {
                            "action_id": action_id,
                            "from": before.value,
                            "to": after.value,
                        }
                    )
            projection.append(
                {
                    "action_id": action_id,
                    "concept": events[-1].concept,
                    "phases": [phase.value for phase in phases],
                    "effect_token_phases": [
                        phase.value for phase in phases if phase in _EFFECT_PHASES
                    ],
                    "current_phase": phases[-1].value,
                }
            )
        return {"actions": projection, "invalid_transitions": invalid}

    def _conflicts(self, config: _Configuration) -> list[dict[str, object]]:
        """Surface local polarity *and value* conflicts without erasing either.

        Direct observations are compared only when scope, concept,
        ``effective_start`` and unit are identical.  This prevents a legitimate
        longitudinal change from being mislabeled while ensuring two different
        values for the same clinical coordinate cannot silently coexist as
        ordinary positive support.
        """

        direct: dict[
            tuple[str, Scope, str, str | None],
            dict[str, dict[str, object]],
        ] = {}
        derived_polarities: dict[
            tuple[str, Scope], dict[Polarity, set[str]]
        ] = {}
        for term in config.terms:
            if isinstance(term, (NoValueTerm, ActionTerm, EffectTokenTerm)):
                continue
            for proof_id in config.term_proofs.get(term, []):
                proof = config.proofs[proof_id]
                if proof.kind == "root" and len(proof.root_source_ids) == 1:
                    source_id = next(iter(proof.root_source_ids))
                    artifact = self._resolve_artifact_ref(source_id)
                    if artifact is None:
                        continue
                    key = (
                        term.concept,
                        term.scope,
                        artifact.clocks.effective_start,
                        _term_unit(term),
                    )
                    signature = _term_value_signature(term)
                    signature_id = _canonical_json(signature)
                    row = direct.setdefault(key, {}).setdefault(
                        signature_id,
                        {"value": signature, "roots": set()},
                    )
                    roots = row["roots"]
                    assert isinstance(roots, set)
                    roots.add(source_id)
                else:
                    derived_polarities.setdefault(
                        (term.concept, term.scope), {}
                    ).setdefault(_term_polarity(term), set()).update(
                        proof.root_source_ids
                    )

        conflicts: list[dict[str, object]] = []
        for (concept, scope, effective_start, unit), variants in direct.items():
            if len(variants) <= 1:
                continue
            conflicts.append(
                {
                    "conflict_type": "same_coordinate_value_disagreement",
                    "concept": concept,
                    "scope": _scope_dict(scope),
                    "effective_start": effective_start,
                    "unit": unit,
                    "variants": [
                        {
                            "value": deepcopy(row["value"]),
                            "roots": sorted(row["roots"]),
                        }
                        for _, row in sorted(variants.items())
                    ],
                }
            )

        for (concept, scope), polarities in derived_polarities.items():
            if Polarity.POSITIVE in polarities and Polarity.NEGATIVE in polarities:
                conflicts.append(
                    {
                        "conflict_type": "derived_polarity_disagreement",
                        "concept": concept,
                        "scope": _scope_dict(scope),
                        "positive_roots": sorted(polarities[Polarity.POSITIVE]),
                        "negative_roots": sorted(polarities[Polarity.NEGATIVE]),
                    }
                )
        return sorted(conflicts, key=lambda item: _canonical_json(item))

    def query(self, spec: QuerySpec) -> CapabilityResult:
        try:
            safe_spec = _validate_query_spec_input(spec)
        except (ContractError, TypeError, ValueError, AssertionError, RecursionError) as exc:
            return self._invalid("query", str(exc), quarantined=True)
        spec = safe_spec
        controls_failure = self._unsupported_query_controls(spec)
        if controls_failure is not None:
            return self._remember(spec.query_id, controls_failure)
        if spec.kind not in self.manifest.declared_query_capabilities:
            return self._remember(spec.query_id, self._unsupported(spec))
        try:
            known_at = parse_time(spec.as_known_at)
            valid_at = parse_time(spec.valid_at) or known_at
        except (ContractError, ValueError) as exc:
            return self._remember(spec.query_id, self._invalid("query", str(exc)))
        assert known_at is not None and valid_at is not None
        try:
            artifacts, excluded = self._visible_artifacts(
                subject_id=spec.subject_id,
                known_at=known_at,
                valid_at=valid_at,
            )
            modules = self._active_modules(spec)
            config = self._build_configuration(artifacts, modules, valid_at)
        except (ContractError, TypeError, ValueError) as exc:
            return self._remember(spec.query_id, self._invalid("query", str(exc)))

        if "nontermination" in config.diagnostics:
            result = CapabilityResult(
                status=ResultStatus.NUMERICAL_FAILURE,
                validation="valid",
                capability="native",
                epistemic="insufficient",
                coverage_status="partial",
                computation="nonconverged",
                diagnostics=deepcopy(config.diagnostics),
                time_cut={
                    "as_known_at": _time_iso(known_at),
                    "valid_at": _time_iso(valid_at),
                },
                native_witness={"kind": "least_fixed_point", "trace": config.trace},
                versions={"candidate": self.VERSION},
            )
            return self._remember(spec.query_id, result)

        action_info = self._action_diagnostics(config.terms)
        conflicts = self._conflicts(config)
        selected = [
            term
            for term in config.terms
            if term.scope.subject_id == spec.subject_id
            and (
                spec.kind is QueryKind.CHECK_INVARIANT
                or spec.target in {"*", "configuration", "actions"}
                or term.concept == spec.target
            )
        ]
        if spec.target == "actions":
            selected = [term for term in selected if isinstance(term, ActionTerm)]
        elif spec.kind is not QueryKind.CHECK_INVARIANT and spec.target not in {
            "*",
            "configuration",
        }:
            selected = [term for term in selected if not isinstance(term, ActionTerm)]
        selected.sort(key=_term_digest)

        claim_rows: list[dict[str, object]] = []
        witness_claims: dict[str, dict[str, object]] = {}
        all_roots: set[str] = set()
        all_families: set[str] = set()
        for term in selected:
            proof_ids = sorted(config.term_proofs.get(term, []))
            roots = {
                root
                for proof_id in proof_ids
                for root in config.proofs[proof_id].root_source_ids
            }
            families = {
                family
                for proof_id in proof_ids
                for family in config.proofs[proof_id].source_families
            }
            digest = _term_digest(term)
            all_roots.update(roots)
            all_families.update(families)
            claim_rows.append(
                {
                    "claim_id": digest,
                    "term": _term_dict(term),
                    "proof_alternatives": proof_ids,
                    "root_sources": sorted(roots),
                    "source_families": sorted(families),
                }
            )
            witness_claims[digest] = {
                "roots": sorted(roots),
                "source_families": sorted(families),
                "proof_alternatives": proof_ids,
            }

        selected_conflicts = [
            item
            for item in conflicts
            if spec.target in {"*", "configuration"} or item["concept"] == spec.target
        ]
        selected_no_values = [
            term for term in selected if isinstance(term, NoValueTerm)
        ]
        selected_assertions = [
            term
            for term in selected
            if not isinstance(term, (NoValueTerm, ActionTerm))
        ]
        action_relevant = spec.target in {"*", "configuration", "actions"}
        if spec.kind is QueryKind.CHECK_INVARIANT:
            status = (
                ResultStatus.INVALID
                if action_relevant and action_info["invalid_transitions"]
                else ResultStatus.OK
            )
            epistemic = "supported" if status is ResultStatus.OK else "conflicting"
        # A malformed lifecycle invalidates any result computed from the same
        # cut, including an ordinary derived-effect target.  It must never be
        # hidden merely because the caller did not ask for ``target=actions``.
        elif action_info["invalid_transitions"]:
            status = ResultStatus.INVALID
            epistemic = "conflicting"
        elif selected_conflicts:
            status = ResultStatus.CONFLICTING
            epistemic = "conflicting"
        elif not selected:
            status = ResultStatus.INSUFFICIENT
            epistemic = "insufficient"
        elif any(
            term.information_state is InfoState.CONFLICTING
            for term in selected_no_values
        ):
            status = ResultStatus.CONFLICTING
            epistemic = "conflicting"
        elif selected_no_values and not selected_assertions:
            if any(
                term.information_state is InfoState.OUT_OF_MODEL
                for term in selected_no_values
            ):
                status = ResultStatus.OUT_OF_MODEL
                epistemic = "insufficient"
            else:
                status = ResultStatus.INSUFFICIENT
                epistemic = "insufficient"
        else:
            status = ResultStatus.OK
            polarities = {_term_polarity(term) for term in selected_assertions}
            epistemic = (
                "refuted"
                if polarities == {Polarity.NEGATIVE}
                else "supported"
            )

        selected_proof_ids = {
            proof_id
            for row in claim_rows
            for proof_id in row["proof_alternatives"]  # type: ignore[union-attr]
        }
        proof_closure = set(selected_proof_ids)
        frontier = list(selected_proof_ids)
        while frontier:
            current = config.proofs.get(frontier.pop())
            if current is None:
                continue
            for premise_id in current.premise_proof_ids:
                if premise_id not in proof_closure:
                    proof_closure.add(premise_id)
                    frontier.append(premise_id)
        proof_rows = {
            proof_id: {
                "kind": proof.kind,
                "conclusion_digest": proof.conclusion_digest,
                "root_source_ids": sorted(proof.root_source_ids),
                "source_families": sorted(proof.source_families),
                "premise_proof_ids": list(proof.premise_proof_ids),
                "rule_ref": proof.rule_ref,
            }
            for proof_id, proof in sorted(config.proofs.items())
            if proof_id in proof_closure
        }
        raw_roots = [
            {
                "artifact_id": artifact.artifact_id,
                "source_id": artifact.source_id,
                "source_family": artifact.source_family,
                "mapping_version": artifact.mapping_version,
                "clocks": asdict(artifact.clocks),
                "withheld": _artifact_is_withheld(artifact),
                "raw_payload_disclosed": False,
            }
            for artifact in artifacts
            if artifact.source_id in all_roots
        ]
        module_analysis = {
            f"{module.module_id}@{module.version}": _rule_graph_analysis(module)
            for module in modules
        }
        result = CapabilityResult(
            status=status,
            validation="invalid" if status is ResultStatus.INVALID else "valid",
            capability="native",
            epistemic=epistemic,
            coverage_status=(
                "out_of_model" if status is ResultStatus.OUT_OF_MODEL else "in_domain"
            ),
            identification="not_applicable",
            computation="exact_least_fixed_point",
            value_kind=(
                "invariant_report"
                if spec.kind is QueryKind.CHECK_INVARIANT
                else "evidence_projection"
            ),
            value={
                "subject_id": spec.subject_id,
                "target": spec.target,
                "task": spec.task,
                "claims": claim_rows,
                "actions": action_info["actions"],
                "conflicts": selected_conflicts,
                "invariants": {
                    "all_derived_claims_grounded": all(
                        proof.root_source_ids for proof in config.proofs.values()
                    ),
                    "no_implicit_action_effect": all(
                        rule.output_semantics
                        is RuleOutputSemantics.EPISTEMIC_DERIVATION
                        or any(
                            isinstance(premise, ActionPremise)
                            and set(premise.phases).issubset(_EFFECT_PHASES)
                            for premise in rule.premises
                        )
                        for module in modules
                        for rule in module.rules
                    ),
                    "action_lifecycle_valid": not action_info["invalid_transitions"],
                    "raw_payload_not_executed": True,
                    "foreign_callback_absent": True,
                },
            },
            assumptions=list(spec.assumptions),
            coverage={
                "native_family": "typed_rewrite_open",
                "probabilistic_dynamics": False,
                "causal_identification": False,
            },
            time_cut={
                "as_known_at": _time_iso(known_at),
                "valid_at": _time_iso(valid_at),
                "replay_mode": spec.kind.value,
                "root_artifacts": [artifact.artifact_id for artifact in artifacts],
                "excluded_artifacts": excluded,
            },
            evidence_witness={
                "root_sources": sorted(all_roots),
                "source_families": sorted(all_families),
                "claims": witness_claims,
                "raw_roots": raw_roots,
                "proof_alternatives": proof_rows,
                "lineage_is_not_independence": True,
                "statistical_independence_assumed": False,
            },
            native_witness={
                "kind": "rewrite_reachability"
                if spec.kind is QueryKind.REACHABILITY
                else "least_fixed_point",
                "rounds": config.rounds,
                "trace": config.trace,
                "module_analysis": module_analysis,
                "conflicts_are_local": True,
                "normal_form": (
                    "unique_monotone_least_fixed_point"
                    if not selected_conflicts
                    else "least_fixed_point_contains_explicit_conflict"
                ),
                "declared_composition_laws_only": [
                    {
                        "module": module.module_id,
                        "subalgebra": sub.subalgebra_id,
                        "laws": [law.value for law in sub.laws],
                    }
                    for module in modules
                    for sub in module.declared_subalgebras
                ],
            },
            diagnostics={
                **deepcopy(config.diagnostics),
                "action_lifecycle": action_info,
                "result_id": spec.query_id,
                "rebuild_origin": deepcopy(self._rebuild_receipt),
            },
            versions={
                "candidate": self.VERSION,
                "knowledge_requested": spec.knowledge_version,
                "modules": {
                    module.module_id: module.version for module in modules
                },
            },
        )
        return self._remember(spec.query_id, result)

    def explain(self, result_id: str) -> CapabilityResult:
        if type(result_id) is not str or not result_id:
            return self._invalid("explain", "result_id 必须是非空 exact str")
        stored = self._results.get(result_id)
        if stored is None:
            return CapabilityResult(
                status=ResultStatus.INSUFFICIENT,
                validation="valid",
                capability="native",
                epistemic="insufficient",
                coverage_status="unknown",
                value_kind="none",
                diagnostics={"operation": "explain", "unknown_result_id": result_id},
                versions={"candidate": self.VERSION},
            )
        return CapabilityResult(
            status=stored.status,
            validation=stored.validation,
            capability=stored.capability,
            epistemic=stored.epistemic,
            coverage_status=stored.coverage_status,
            identification=stored.identification,
            computation=stored.computation,
            value_kind="explanation",
            value={
                "result_id": result_id,
                "status": stored.status.value,
                "value_kind": stored.value_kind,
                "claim_count": (
                    len(stored.value.get("claims", []))
                    if isinstance(stored.value, Mapping)
                    else None
                ),
            },
            assumptions=deepcopy(stored.assumptions),
            coverage=deepcopy(stored.coverage),
            time_cut=deepcopy(stored.time_cut),
            evidence_witness=deepcopy(stored.evidence_witness),
            native_witness=deepcopy(stored.native_witness),
            diagnostics={
                "operation": "explain",
                "frozen_result": True,
                "original_diagnostics": deepcopy(stored.diagnostics),
            },
            versions=deepcopy(stored.versions),
        )

    def clean_rebuild(self) -> "RewriteOpenCandidate":
        rebuilt = type(self)(self.track)
        for module in sorted(
            self._modules.values(), key=lambda item: (item.module_id, item.version)
        ):
            rebuilt.register_module(deepcopy(module))
        for component in sorted(
            self._components.values(), key=lambda item: item.component_id
        ):
            rebuilt.register_module(deepcopy(component))

        # Rebuild the immutable *history*, not merely today's surviving
        # projection.  Dropping retracted/superseded roots destroys historical
        # bitemporal cuts and makes a pre-tombstone replay disagree with the
        # incremental store.
        history = list(self._artifacts.values())
        for artifact in sorted(
            history, key=lambda item: (item.clocks.recorded_at, item.artifact_id)
        ):
            receipt = rebuilt._ingest(
                deepcopy(artifact), allow_missing_supersedes=True
            )
            if receipt.status is not ResultStatus.OK:
                raise RuntimeError(
                    f"clean rebuild rejected historical artifact {artifact.artifact_id}: "
                    f"{receipt.diagnostics}"
                )
        tombstone_count = 0
        for source_id, moments in sorted(self._retractions.items()):
            for moment in sorted(moments):
                receipt = rebuilt.retract(source_id, _time_iso(moment) or _EPOCH)
                if receipt.status is not ResultStatus.OK:
                    raise RuntimeError(
                        f"clean rebuild rejected tombstone {source_id}@{moment}: "
                        f"{receipt.diagnostics}"
                    )
                tombstone_count += 1
        for spec in sorted(
            self._compositions.values(), key=lambda item: item.composition_id
        ):
            receipt = rebuilt.compose(deepcopy(spec))
            if receipt.status is not ResultStatus.OK:
                raise RuntimeError(
                    f"clean rebuild rejected composition {spec.composition_id}: "
                    f"{receipt.diagnostics}"
                )
        rebuilt._rebuild_receipt = {
            "source_artifact_count": len(history),
            "retraction_tombstone_count": tombstone_count,
            "history_preserved": True,
            "materialized_terms_copied": False,
        }
        return rebuilt


# Stable public aliases used by the benchmark adapter and explanatory notebooks.
TypedRewriteOpenCandidate = RewriteOpenCandidate


def build_candidate(track: Track = Track.NATIVE) -> RewriteOpenCandidate:
    """Return a fresh native candidate without hidden shared state."""

    return RewriteOpenCandidate(track)


__all__ = [
    "ActionPhase",
    "ActionPremise",
    "ActionTerm",
    "CodeTerm",
    "ComponentFamily",
    "CompositionLaw",
    "CompositionSpec",
    "ConclusionMode",
    "ConclusionTemplate",
    "DeclaredSubalgebra",
    "EffectTokenTerm",
    "FactPremise",
    "GuardOperator",
    "InteractionDeclaration",
    "NoValueTerm",
    "NumericGuard",
    "OpenComponent",
    "OwnershipKind",
    "Polarity",
    "Port",
    "PortDirection",
    "PortRef",
    "PortRole",
    "PresenceTerm",
    "ProvenancePolicy",
    "QuantityComparator",
    "QuantityTerm",
    "RewriteModule",
    "RewriteOpenCandidate",
    "RewriteRule",
    "RewriteStrategy",
    "RuleOutputSemantics",
    "ScopeBinding",
    "TermKind",
    "TextTerm",
    "TimeBasis",
    "TypedRewriteOpenCandidate",
    "UncertaintySemantics",
    "Wire",
    "build_candidate",
]
