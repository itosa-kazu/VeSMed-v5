"""Typed temporal evidence ledger with positive, provenance-carrying rules.

This candidate deliberately models an *epistemic ledger*, not physiology.  It
is therefore native for bitemporal projection, correction and deterministic
derivation, while forecast/intervention/counterfactual queries are reported as
unsupported rather than simulated by hidden ad-hoc code.

The rule/module language below is closed data.  ``register_module`` accepts a
``TemporalRuleModule`` or its strict mapping representation; executable Python
objects, callbacks, SQL and prompt strings are not accepted as semantics.

Mapping form (all timestamps require an offset)::

    {
      "module_id": "screening-rules",
      "version": "2",
      "registered_at": "2026-01-02T00:00:00Z",
      "knowledge_version": "knowledge-v1",
      "rules": [{
        "rule_id": "fever-and-tachycardia",
        "premises": [
          {"concept": "temperature", "min_value": 38.0, "unit": "Cel"},
          {"concept": "heart_rate", "min_value": 100.0, "unit": "/min"}
        ],
        "conclusion": {"concept": "screen_positive", "value": true},
        "max_span_hours": 6.0,
        "scope_relation": "compatible"
      }],
      "projections": [{
        "task": "presentation",
        "include_roles": ["raw_observation", "deterministic_derivation"]
      }]
    }

Rules are positive: they may match an explicit ``absent`` assertion, but they
cannot fire from failure to find a fact.  Rule dependency cycles are rejected,
which makes closure finite and deterministic without an execution escape hatch.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from itertools import product
import json
import math
from typing import Any, Iterable, Mapping, Sequence

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


class _MissingType:
    """Deep-copy-stable sentinel used by frozen rule IR."""

    def __copy__(self) -> "_MissingType":
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> "_MissingType":
        return self


_MISSING = _MissingType()
_UNKNOWN_STATES = frozenset(
    {
        InfoState.NOT_ASKED,
        InfoState.NOT_TESTED,
        InfoState.UNABLE_TO_ASSESS,
        InfoState.INSUFFICIENT,
        InfoState.NOT_APPLICABLE,
        InfoState.OUT_OF_MODEL,
        InfoState.MASKED,
    }
)
_RULE_PREMISE_STATES = frozenset({InfoState.PRESENT, InfoState.ABSENT})
_RESERVED_TASKS = frozenset(
    {
        "all",
        "audit",
        "presentation",
        "observation",
        "diagnosis",
        "medication_safety",
        "planning",
        "performed",
        "action",
    }
)

# Closed-input budgets are deliberately enforced *before* ``asdict``,
# ``deepcopy`` or hashing.  Apart from bounding denial-of-service inputs this
# also prevents user-defined Mapping/list/scalar subclasses from gaining an
# execution hook through iteration, conversion or copying.
_MAX_INPUT_NODES = 10_000
_MAX_INPUT_DEPTH = 32
_MAX_INPUT_SCALAR_CHARS = 1_000_000
_MAX_RULES_PER_MODULE = 512
_MAX_PREMISES_PER_RULE = 32
_MAX_PROJECTIONS_PER_MODULE = 128
_MAX_ARTIFACTS = 10_000
_MAX_CLOSURE_COMBINATIONS = 200_000
_MAX_CLOSURE_FACTS = 100_000

_SUPPORTED_GUARANTEES: Mapping[str, str] = {
    "evidence_roots": "every projected claim emits the union of immutable root source ids",
    "rooted_support": "every derived proof alternative has non-empty root support",
    "independence_explicit": "the ledger explicitly makes no statistical-independence assumption",
    "raw_roundtrip": "accepted roots retain their exact validated raw payload; masked roots remain non-disclosive",
    "bitemporal_cut": "availability/recorded and effective-time cuts are both enforced",
    "deterministic_rebuild": "closure is recomputed from immutable roots and versioned closed rules",
    "masked_non_disclosure": "masked values, context and raw payload are redacted from every witness",
}


def _validate_closed_json(
    value: Any,
    where: str,
    *,
    allow_tuple: bool = False,
    max_nodes: int = _MAX_INPUT_NODES,
    max_depth: int = _MAX_INPUT_DEPTH,
    max_scalar_chars: int = _MAX_INPUT_SCALAR_CHARS,
) -> None:
    """Validate a bounded, exact-builtin JSON value without invoking hooks.

    ``isinstance`` is intentionally not used for containers or scalars: a
    dict/list/int/str subclass can override iteration, conversion, copying or
    representation.  Tuples are accepted only for already-typed frozen IR and
    control-plane tuple fields, never for external mapping-form JSON.
    """

    nodes = 0
    scalar_chars = 0
    active: set[int] = set()

    def walk(current: Any, depth: int, path: str) -> None:
        nonlocal nodes, scalar_chars
        nodes += 1
        if nodes > max_nodes:
            raise ContractError(f"{where} 超过节点预算 {max_nodes}")
        if depth > max_depth:
            raise ContractError(f"{where} 超过嵌套深度预算 {max_depth}")

        current_type = type(current)
        if current_type is str:
            scalar_chars += len(current)
        elif current is None or current_type is bool:
            pass
        elif current_type is int:
            # Bound giant Python integers before json encoding allocates their
            # complete decimal representation.
            bits = current.bit_length()
            scalar_chars += max(1, (bits * 30103) // 100000 + 2)
        elif current_type is float:
            if not math.isfinite(current):
                raise ContractError(f"{path} 不得为 NaN/Infinity")
            scalar_chars += 24
        elif current_type is dict:
            marker = id(current)
            if marker in active:
                raise ContractError(f"{path} 含循环引用")
            active.add(marker)
            try:
                for key, child in current.items():
                    if type(key) is not str:
                        raise ContractError(f"{path} 的 object key 必须是 exact str")
                    scalar_chars += len(key)
                    walk(child, depth + 1, f"{path}.{key}")
            finally:
                active.remove(marker)
        elif current_type is list or (allow_tuple and current_type is tuple):
            marker = id(current)
            if marker in active:
                raise ContractError(f"{path} 含循环引用")
            active.add(marker)
            try:
                for index, child in enumerate(current):
                    walk(child, depth + 1, f"{path}[{index}]")
            finally:
                active.remove(marker)
        else:
            executable = " / callable" if callable(current) else ""
            raise ContractError(
                f"{path} 必须是 exact JSON-like builtin{executable}; 得到 {current_type.__name__}"
            )
        if scalar_chars > max_scalar_chars:
            raise ContractError(f"{where} 超过标量字符预算 {max_scalar_chars}")

    walk(value, 0, where)


def _exact_optional_str(value: Any, where: str) -> None:
    if value is not None and type(value) is not str:
        raise ContractError(f"{where} 必须是 exact str 或 null")


def _validate_artifact_input(artifact: Any) -> SourceArtifact:
    """Validate the typed artifact without ``asdict``/copy/hash first."""

    if type(artifact) is not SourceArtifact:
        raise ContractError("ingest requires exact SourceArtifact")
    if type(artifact.scope) is not Scope or type(artifact.clocks) is not ClockSet:
        raise ContractError("artifact scope/clocks 必须是 exact contract dataclass")
    if type(artifact.semantic_role) is not SemanticRole or type(artifact.information_state) is not InfoState:
        raise ContractError("artifact enum 字段类型非法")
    for name in ("artifact_id", "source_id", "concept", "mapping_version"):
        value = getattr(artifact, name)
        if type(value) is not str or not value:
            raise ContractError(f"artifact.{name} 必须是非空 exact str")
    for name in ("unit", "method", "source_family", "supersedes"):
        _exact_optional_str(getattr(artifact, name), f"artifact.{name}")
    for name in ("subject_id", "encounter_id", "specimen_id", "device_id", "site_id", "body_site"):
        value = getattr(artifact.scope, name)
        if name == "subject_id":
            if type(value) is not str or not value:
                raise ContractError("artifact.scope.subject_id 必须是非空 exact str")
        else:
            _exact_optional_str(value, f"artifact.scope.{name}")
    for name in ("effective_start", "effective_end", "collected_at", "available_at", "recorded_at", "expires_at"):
        value = getattr(artifact.clocks, name)
        _exact_optional_str(value, f"artifact.clocks.{name}")
    # Revalidate timestamps because a frozen dataclass can still be corrupted
    # deliberately with object.__setattr__ in hostile tests.
    try:
        start = _dt(artifact.clocks.effective_start)
        end = _dt(artifact.clocks.effective_end)
        available = _dt(artifact.clocks.available_at)
        recorded = _dt(artifact.clocks.recorded_at)
        expires = _dt(artifact.clocks.expires_at)
        _dt(artifact.clocks.collected_at)
    except (ContractError, TypeError, ValueError) as exc:
        raise ContractError(f"artifact clocks 非法: {exc}") from exc
    if start is None or available is None or recorded is None:
        raise ContractError("effective_start/available_at/recorded_at 必填")
    if end is not None and end < start:
        raise ContractError("effective_end 早于 effective_start")
    if recorded < available:
        raise ContractError("recorded_at 早于 available_at")
    if expires is not None and expires < start:
        raise ContractError("expires_at 早于 effective_start")
    if artifact.reliability is not None:
        if type(artifact.reliability) not in {int, float} or type(artifact.reliability) is bool:
            raise ContractError("artifact.reliability 必须是 finite number")
        if not math.isfinite(float(artifact.reliability)) or not 0.0 <= float(artifact.reliability) <= 1.0:
            raise ContractError("artifact.reliability 必须在 [0,1]")
    if type(artifact.context) is not dict or type(artifact.raw_payload) is not dict:
        raise ContractError("artifact.context/raw_payload 必须是 exact dict")
    # One combined budget covers all externally controlled payload-bearing
    # fields before the first serialization/copy/fingerprint operation.
    _validate_closed_json(
        {
            "artifact_id": artifact.artifact_id,
            "source_id": artifact.source_id,
            "concept": artifact.concept,
            "scope": {
                "subject_id": artifact.scope.subject_id,
                "encounter_id": artifact.scope.encounter_id,
                "specimen_id": artifact.scope.specimen_id,
                "device_id": artifact.scope.device_id,
                "site_id": artifact.scope.site_id,
                "body_site": artifact.scope.body_site,
            },
            "clocks": {
                "effective_start": artifact.clocks.effective_start,
                "effective_end": artifact.clocks.effective_end,
                "collected_at": artifact.clocks.collected_at,
                "available_at": artifact.clocks.available_at,
                "recorded_at": artifact.clocks.recorded_at,
                "expires_at": artifact.clocks.expires_at,
            },
            "value": artifact.value,
            "unit": artifact.unit,
            "method": artifact.method,
            "context": artifact.context,
            "source_family": artifact.source_family,
            "supersedes": artifact.supersedes,
            "raw_payload": artifact.raw_payload,
            "mapping_version": artifact.mapping_version,
        },
        "artifact",
    )
    return artifact


def _validate_query_input(spec: Any) -> QuerySpec:
    """Validate a possibly-corrupted frozen QuerySpec without serialization."""

    if type(spec) is not QuerySpec:
        raise ContractError("query requires exact QuerySpec")
    if type(spec.kind) is not QueryKind:
        raise ContractError("query.kind 必须是 QueryKind")
    for name in ("query_id", "target", "subject_id", "knowledge_version", "as_known_at"):
        value = getattr(spec, name)
        if type(value) is not str or not value:
            raise ContractError(f"query.{name} 必须是非空 exact str")
    for name in ("valid_at", "task", "model_version"):
        _exact_optional_str(getattr(spec, name), f"query.{name}")
    try:
        if _dt(spec.as_known_at) is None:
            raise ContractError("as_known_at required")
        _dt(spec.valid_at)
    except (ContractError, TypeError, ValueError) as exc:
        raise ContractError(f"query clocks 非法: {exc}") from exc
    if type(spec.requested_guarantees) is not tuple or not all(type(v) is str and v for v in spec.requested_guarantees):
        raise ContractError("requested_guarantees 必须是非空 exact str 的 exact tuple")
    if len(spec.requested_guarantees) != len(set(spec.requested_guarantees)):
        raise ContractError("requested_guarantees 不得重复")
    if type(spec.assumptions) is not tuple or not all(type(v) is str for v in spec.assumptions):
        raise ContractError("assumptions 必须是 exact str 的 exact tuple")
    if spec.intervention is not None:
        if type(spec.intervention) is not dict:
            raise ContractError("intervention 必须是 exact dict")
        _validate_closed_json(spec.intervention, "query.intervention")
    if spec.horizon_hours is not None:
        if type(spec.horizon_hours) not in {int, float} or type(spec.horizon_hours) is bool:
            raise ContractError("horizon_hours 必须是 finite number")
        if not math.isfinite(float(spec.horizon_hours)) or float(spec.horizon_hours) < 0:
            raise ContractError("horizon_hours 必须是非负 finite number")
    if type(spec.seed) is not int:
        raise ContractError("seed 必须是 exact int")
    _validate_closed_json(
        {
            "query_id": spec.query_id,
            "target": spec.target,
            "subject_id": spec.subject_id,
            "as_known_at": spec.as_known_at,
            "valid_at": spec.valid_at,
            "task": spec.task,
            "knowledge_version": spec.knowledge_version,
            "model_version": spec.model_version,
            "intervention": spec.intervention,
            "horizon_hours": spec.horizon_hours,
            "requested_guarantees": list(spec.requested_guarantees),
            "assumptions": list(spec.assumptions),
            "seed": spec.seed,
        },
        "query",
    )
    return spec


def _guarantee_witness(spec: QuerySpec) -> dict[str, Any]:
    requested = list(spec.requested_guarantees)
    return {
        "requested_guarantees": requested,
        "requested_guarantees_consumed": True,
        "guarantee_semantics": {name: _SUPPORTED_GUARANTEES[name] for name in requested},
    }


def _dt(value: str | datetime | None) -> datetime | None:
    return parse_time(value)


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def _plain(value: Any) -> Any:
    """Convert contract dataclasses/enums to a deterministic JSON value."""
    if isinstance(value, (InfoState, SemanticRole, QueryKind, ResultStatus, Track)):
        return value.value
    if isinstance(value, datetime):
        return _iso(value)
    if hasattr(value, "__dataclass_fields__"):
        return {k: _plain(v) for k, v in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(v) for v in value), key=lambda x: json.dumps(x, sort_keys=True))
    return value


def _canonical(value: Any) -> str:
    try:
        return json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"值不可确定性序列化: {exc}") from exc


def _digest(value: Any) -> str:
    return sha256(_canonical(value).encode("utf-8")).hexdigest()


def _artifact_witness(artifact: SourceArtifact) -> dict[str, Any]:
    """Audit representation that never discloses a masked payload."""
    masked = artifact.information_state is InfoState.MASKED or artifact.semantic_role is SemanticRole.MASKED_ARTIFACT
    # Construct this explicitly instead of calling asdict first: masked values
    # never enter an output-shaped intermediate object.
    return {
        "artifact_id": artifact.artifact_id,
        "source_id": artifact.source_id,
        "semantic_role": artifact.semantic_role.value,
        "concept": artifact.concept,
        "scope": _plain(artifact.scope),
        "clocks": _plain(artifact.clocks),
        "information_state": artifact.information_state.value,
        "value": None if masked else _plain(artifact.value),
        "unit": artifact.unit,
        "method": artifact.method,
        "context": {"redacted": True} if masked else _plain(artifact.context),
        "reliability": artifact.reliability,
        "source_family": artifact.source_family,
        "supersedes": artifact.supersedes,
        "raw_payload": {"redacted": True} if masked else _plain(artifact.raw_payload),
        "mapping_version": artifact.mapping_version,
    }


def _contains_callable(value: Any, seen: set[int] | None = None) -> bool:
    if callable(value):
        return True
    if seen is None:
        seen = set()
    marker = id(value)
    if marker in seen:
        return False
    seen.add(marker)
    if isinstance(value, Mapping):
        return any(_contains_callable(k, seen) or _contains_callable(v, seen) for k, v in value.items())
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_callable(v, seen) for v in value)
    return False


def _strict_fields(data: Mapping[str, Any], allowed: set[str], where: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise ContractError(f"{where} 未知字段: {sorted(unknown)}")


def _enum_tuple(enum_type: type, values: Sequence[Any] | None, default: Sequence[Any]) -> tuple[Any, ...]:
    raw = default if values is None else values
    if type(raw) not in {list, tuple}:
        raise ContractError(f"{enum_type.__name__} list 必须是 exact list/tuple")
    try:
        return tuple(v if type(v) is enum_type else enum_type(v) for v in raw)
    except (TypeError, ValueError) as exc:
        raise ContractError(f"非法 {enum_type.__name__}") from exc


@dataclass(frozen=True)
class TemporalPremise:
    """One positive, typed atom in a deterministic temporal rule."""

    concept: str
    information_states: tuple[InfoState, ...] = (InfoState.PRESENT,)
    semantic_roles: tuple[SemanticRole, ...] = (
        SemanticRole.RAW_OBSERVATION,
        SemanticRole.SUBJECT_STATEMENT,
        SemanticRole.DETERMINISTIC_DERIVATION,
        SemanticRole.PERFORMED_INTERVENTION,
        SemanticRole.STOPPED_INTERVENTION,
    )
    equals: Any = field(default=_MISSING, repr=False, compare=False)
    min_value: float | None = None
    max_value: float | None = None
    unit: str | None = None
    method: str | None = None

    def __post_init__(self) -> None:
        if type(self.concept) is not str or not self.concept:
            raise ContractError("premise.concept 不得为空")
        if type(self.information_states) is not tuple or type(self.semantic_roles) is not tuple:
            raise ContractError("premise 的 information_states/semantic_roles 必须是 exact tuple")
        if not self.information_states or not self.semantic_roles:
            raise ContractError("premise 的 information_states/semantic_roles 不得为空")
        if not all(type(state) is InfoState for state in self.information_states):
            raise ContractError("premise.information_states 必须是 InfoState")
        if not all(type(role) is SemanticRole for role in self.semantic_roles):
            raise ContractError("premise.semantic_roles 必须是 SemanticRole")
        unsafe_states = set(self.information_states) - _RULE_PREMISE_STATES
        if unsafe_states:
            raise ContractError(
                "deterministic rule 不得把 unknown/conflict/masked/censored 洗成结论: "
                + ",".join(sorted(state.value for state in unsafe_states))
            )
        for name in ("min_value", "max_value"):
            numeric = getattr(self, name)
            if numeric is not None and (
                type(numeric) not in {int, float}
                or type(numeric) is bool
                or not math.isfinite(float(numeric))
            ):
                raise ContractError(f"premise.{name} 必须是 finite number")
        _exact_optional_str(self.unit, "premise.unit")
        _exact_optional_str(self.method, "premise.method")
        if self.min_value is not None and self.max_value is not None and self.min_value > self.max_value:
            raise ContractError("premise.min_value 大于 max_value")
        if self.equals is not _MISSING and (self.min_value is not None or self.max_value is not None):
            raise ContractError("premise.equals 不得与 min_value/max_value 同用")
        numeric_equals = self.equals is not _MISSING and isinstance(self.equals, (int, float)) and not isinstance(self.equals, bool)
        if (self.min_value is not None or self.max_value is not None or numeric_equals) and self.unit is None:
            raise ContractError("numeric premise guard 必须声明 exact unit；无量纲请用 unit='1'")
        if self.equals is not _MISSING:
            _validate_closed_json(self.equals, "premise.equals")

    @classmethod
    def from_data(cls, data: Mapping[str, Any] | "TemporalPremise") -> "TemporalPremise":
        if type(data) is cls:
            return data
        if type(data) is not dict:
            raise ContractError("premise 必须是 mapping")
        _validate_closed_json(data, "premise")
        _strict_fields(
            data,
            {"concept", "information_states", "semantic_roles", "equals", "value_equals", "min_value", "max_value", "unit", "method"},
            "premise",
        )
        if "equals" in data and "value_equals" in data:
            raise ContractError("premise.equals/value_equals 只能使用一个")
        if type(data.get("concept")) is not str:
            raise ContractError("premise.concept 必须是 exact str")
        for name in ("unit", "method"):
            _exact_optional_str(data.get(name), f"premise.{name}")
        for name in ("min_value", "max_value"):
            value = data.get(name)
            if value is not None and (type(value) not in {int, float} or type(value) is bool):
                raise ContractError(f"premise.{name} 必须是 number")
        equals = data.get("equals", data.get("value_equals", _MISSING))
        return cls(
            concept=str(data.get("concept", "")),
            information_states=_enum_tuple(InfoState, data.get("information_states"), (InfoState.PRESENT,)),
            semantic_roles=_enum_tuple(
                SemanticRole,
                data.get("semantic_roles"),
                (
                    SemanticRole.RAW_OBSERVATION,
                    SemanticRole.SUBJECT_STATEMENT,
                    SemanticRole.DETERMINISTIC_DERIVATION,
                    SemanticRole.PERFORMED_INTERVENTION,
                    SemanticRole.STOPPED_INTERVENTION,
                ),
            ),
            equals=equals,
            min_value=float(data["min_value"]) if data.get("min_value") is not None else None,
            max_value=float(data["max_value"]) if data.get("max_value") is not None else None,
            unit=str(data["unit"]) if data.get("unit") is not None else None,
            method=str(data["method"]) if data.get("method") is not None else None,
        )

    def to_data(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "concept": self.concept,
            "information_states": [v.value for v in self.information_states],
            "semantic_roles": [v.value for v in self.semantic_roles],
            "min_value": self.min_value,
            "max_value": self.max_value,
            "unit": self.unit,
            "method": self.method,
        }
        if self.equals is not _MISSING:
            out["equals"] = _plain(self.equals)
        return out


@dataclass(frozen=True)
class RuleConclusion:
    concept: str
    value: Any = _MISSING
    value_from: int | None = None
    information_state: InfoState = InfoState.PRESENT
    unit: str | None = None
    unit_from: int | None = None
    semantic_role: SemanticRole = SemanticRole.DETERMINISTIC_DERIVATION
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.concept) is not str or not self.concept:
            raise ContractError("conclusion.concept 不得为空")
        if type(self.information_state) is not InfoState:
            raise ContractError("conclusion.information_state 必须是 InfoState")
        if type(self.semantic_role) is not SemanticRole:
            raise ContractError("conclusion.semantic_role 必须是 SemanticRole")
        if self.semantic_role is not SemanticRole.DETERMINISTIC_DERIVATION:
            raise ContractError("rule conclusion 必须是 deterministic_derivation")
        if (self.value is _MISSING) == (self.value_from is None):
            raise ContractError("conclusion 必须且只能声明 value 或 value_from")
        if self.value_from is not None and type(self.value_from) is not int:
            raise ContractError("conclusion.value_from 必须是 exact int")
        if self.unit_from is not None and type(self.unit_from) is not int:
            raise ContractError("conclusion.unit_from 必须是 exact int")
        if self.value_from is not None and self.value_from < 0:
            raise ContractError("conclusion.value_from 不得为负")
        if self.unit_from is not None and self.unit_from < 0:
            raise ContractError("conclusion.unit_from 不得为负")
        if self.unit is not None and self.unit_from is not None:
            raise ContractError("conclusion.unit/unit_from 只能使用一个")
        if self.value_from is not None and self.unit is None and self.unit_from is None:
            object.__setattr__(self, "unit_from", self.value_from)
        _exact_optional_str(self.unit, "conclusion.unit")
        if type(self.context) is not dict:
            raise ContractError("conclusion.context 必须是 exact dict")
        if self.value is not _MISSING:
            _validate_closed_json(self.value, "conclusion.value")
        _validate_closed_json(self.context, "conclusion.context")

    @classmethod
    def from_data(cls, data: Mapping[str, Any] | "RuleConclusion") -> "RuleConclusion":
        if type(data) is cls:
            return data
        if type(data) is not dict:
            raise ContractError("conclusion 必须是 mapping")
        _validate_closed_json(data, "conclusion")
        _strict_fields(
            data,
            {"concept", "value", "value_from", "information_state", "unit", "unit_from", "semantic_role", "context"},
            "conclusion",
        )
        if type(data.get("concept")) is not str:
            raise ContractError("conclusion.concept 必须是 exact str")
        _exact_optional_str(data.get("unit"), "conclusion.unit")
        if type(data.get("context", {})) is not dict:
            raise ContractError("conclusion.context 必须是 exact dict")
        for name in ("value_from", "unit_from"):
            value = data.get(name)
            if value is not None and type(value) is not int:
                raise ContractError(f"conclusion.{name} 必须是 exact int")
        for name in ("information_state", "semantic_role"):
            value = data.get(name)
            if value is not None and type(value) is not str:
                raise ContractError(f"conclusion.{name} 必须是 exact str")
        return cls(
            concept=str(data.get("concept", "")),
            value=data.get("value", _MISSING),
            value_from=int(data["value_from"]) if data.get("value_from") is not None else None,
            information_state=data.get("information_state")
            if isinstance(data.get("information_state"), InfoState)
            else InfoState(data.get("information_state", InfoState.PRESENT.value)),
            unit=str(data["unit"]) if data.get("unit") is not None else None,
            unit_from=int(data["unit_from"]) if data.get("unit_from") is not None else None,
            semantic_role=data.get("semantic_role")
            if isinstance(data.get("semantic_role"), SemanticRole)
            else SemanticRole(data.get("semantic_role", SemanticRole.DETERMINISTIC_DERIVATION.value)),
            context=dict(data.get("context", {})),
        )

    def to_data(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "concept": self.concept,
            "value_from": self.value_from,
            "information_state": self.information_state.value,
            "unit": self.unit,
            "unit_from": self.unit_from,
            "semantic_role": self.semantic_role.value,
            "context": _plain(self.context),
        }
        if self.value is not _MISSING:
            out["value"] = _plain(self.value)
        return out


@dataclass(frozen=True)
class TemporalRule:
    rule_id: str
    premises: tuple[TemporalPremise, ...]
    conclusion: RuleConclusion
    ordered: bool = False
    max_span_hours: float | None = None
    scope_relation: str = "compatible"

    def __post_init__(self) -> None:
        if type(self.premises) is not tuple or not all(type(premise) is TemporalPremise for premise in self.premises):
            raise ContractError("rule.premises 必须是 TemporalPremise")
        if type(self.conclusion) is not RuleConclusion:
            raise ContractError("rule.conclusion 必须是 RuleConclusion")
        if type(self.rule_id) is not str or not self.rule_id or not self.premises:
            raise ContractError("rule_id/premises 不得为空")
        if len(self.premises) > _MAX_PREMISES_PER_RULE:
            raise ContractError(f"rule premises 超过预算 {_MAX_PREMISES_PER_RULE}")
        if type(self.ordered) is not bool:
            raise ContractError("rule.ordered 必须是 exact bool")
        if self.max_span_hours is not None and (
            type(self.max_span_hours) not in {int, float}
            or type(self.max_span_hours) is bool
            or not math.isfinite(float(self.max_span_hours))
        ):
            raise ContractError("max_span_hours 必须是 finite number")
        if self.max_span_hours is not None and self.max_span_hours < 0:
            raise ContractError("max_span_hours 不得为负")
        if type(self.scope_relation) is not str or self.scope_relation not in {"same_subject", "compatible", "same_encounter", "same_specimen"}:
            raise ContractError(f"未知 scope_relation: {self.scope_relation}")
        # Intents and probabilistic/model claims may be retained and projected,
        # but this deterministic evidence rule language must not recast them as
        # observed clinical facts.  Performed/stopped actions are explicit
        # events and remain legal premises.
        non_derivable_roles = {
            SemanticRole.PLAN,
            SemanticRole.ORDER,
            SemanticRole.MODEL_INFERENCE,
            SemanticRole.HYPOTHESIS,
            SemanticRole.TASK_POLICY,
            SemanticRole.MASKED_ARTIFACT,
        }
        for premise in self.premises:
            forbidden = set(premise.semantic_roles) & non_derivable_roles
            if forbidden:
                raise ContractError(
                    "deterministic rule premise 不得消费可洗白的语义角色: "
                    + ",".join(sorted(role.value for role in forbidden))
                )
        for index in (self.conclusion.value_from, self.conclusion.unit_from):
            if index is not None and index >= len(self.premises):
                raise ContractError("conclusion 的 premise index 越界")
        if self.conclusion.value_from is not None:
            source = self.premises[self.conclusion.value_from]
            if InfoState.MASKED in source.information_states or SemanticRole.MASKED_ARTIFACT in source.semantic_roles:
                raise ContractError("masked premise 的 value 不得复制到派生结论")

    @classmethod
    def from_data(cls, data: Mapping[str, Any] | "TemporalRule") -> "TemporalRule":
        if type(data) is cls:
            return data
        if type(data) is not dict:
            raise ContractError("rule 必须是 mapping")
        _validate_closed_json(data, "rule")
        _strict_fields(data, {"rule_id", "premises", "conclusion", "ordered", "max_span_hours", "scope_relation"}, "rule")
        if type(data.get("rule_id")) is not str:
            raise ContractError("rule.rule_id 必须是 exact str")
        if type(data.get("premises", [])) is not list or type(data.get("conclusion", {})) is not dict:
            raise ContractError("rule premises/conclusion 类型非法")
        if type(data.get("ordered", False)) is not bool:
            raise ContractError("rule.ordered 必须是 exact bool")
        if data.get("max_span_hours") is not None and (
            type(data["max_span_hours"]) not in {int, float} or type(data["max_span_hours"]) is bool
        ):
            raise ContractError("rule.max_span_hours 必须是 number")
        if type(data.get("scope_relation", "compatible")) is not str:
            raise ContractError("rule.scope_relation 必须是 exact str")
        return cls(
            rule_id=str(data.get("rule_id", "")),
            premises=tuple(TemporalPremise.from_data(p) for p in data.get("premises", ())),
            conclusion=RuleConclusion.from_data(data.get("conclusion", {})),
            ordered=bool(data.get("ordered", False)),
            max_span_hours=float(data["max_span_hours"]) if data.get("max_span_hours") is not None else None,
            scope_relation=str(data.get("scope_relation", "compatible")),
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "premises": [p.to_data() for p in self.premises],
            "conclusion": self.conclusion.to_data(),
            "ordered": self.ordered,
            "max_span_hours": self.max_span_hours,
            "scope_relation": self.scope_relation,
        }


@dataclass(frozen=True)
class TaskProjection:
    task: str
    include_roles: tuple[SemanticRole, ...] = ()
    exclude_roles: tuple[SemanticRole, ...] = ()
    include_concepts: tuple[str, ...] = ()
    exclude_concepts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.task) is not str or not self.task:
            raise ContractError("projection.task 不得为空")
        if type(self.include_roles) is not tuple or type(self.exclude_roles) is not tuple:
            raise ContractError("projection roles 必须是 exact tuple")
        if not all(type(role) is SemanticRole for role in self.include_roles + self.exclude_roles):
            raise ContractError("projection roles 必须是 SemanticRole")
        if type(self.include_concepts) is not tuple or type(self.exclude_concepts) is not tuple:
            raise ContractError("projection concepts 必须是 exact tuple")
        if not all(type(concept) is str and concept for concept in self.include_concepts + self.exclude_concepts):
            raise ContractError("projection concepts 必须是非空 exact str")
        if set(self.include_roles) & set(self.exclude_roles):
            raise ContractError("projection role 同时 include/exclude")
        if set(self.include_concepts) & set(self.exclude_concepts):
            raise ContractError("projection concept 同时 include/exclude")

    @classmethod
    def from_data(cls, data: Mapping[str, Any] | "TaskProjection") -> "TaskProjection":
        if type(data) is cls:
            return data
        if type(data) is not dict:
            raise ContractError("projection 必须是 mapping")
        _validate_closed_json(data, "projection")
        _strict_fields(data, {"task", "include_roles", "exclude_roles", "include_concepts", "exclude_concepts"}, "projection")
        if type(data.get("task")) is not str:
            raise ContractError("projection.task 必须是 exact str")
        for name in ("include_roles", "exclude_roles", "include_concepts", "exclude_concepts"):
            if type(data.get(name, [])) is not list:
                raise ContractError(f"projection.{name} 必须是 exact list")
        for name in ("include_concepts", "exclude_concepts"):
            if not all(type(v) is str for v in data.get(name, [])):
                raise ContractError(f"projection.{name} 必须只含 exact str")
        return cls(
            task=str(data.get("task", "")),
            include_roles=_enum_tuple(SemanticRole, data.get("include_roles"), ()),
            exclude_roles=_enum_tuple(SemanticRole, data.get("exclude_roles"), ()),
            include_concepts=tuple(str(v) for v in data.get("include_concepts", ())),
            exclude_concepts=tuple(str(v) for v in data.get("exclude_concepts", ())),
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "include_roles": [v.value for v in self.include_roles],
            "exclude_roles": [v.value for v in self.exclude_roles],
            "include_concepts": list(self.include_concepts),
            "exclude_concepts": list(self.exclude_concepts),
        }


@dataclass(frozen=True)
class TemporalRuleModule:
    module_id: str
    version: str
    registered_at: str
    knowledge_version: str = "knowledge-v1"
    rules: tuple[TemporalRule, ...] = ()
    projections: tuple[TaskProjection, ...] = ()

    def __post_init__(self) -> None:
        if not all(type(v) is str and v for v in (self.module_id, self.version, self.registered_at, self.knowledge_version)):
            raise ContractError("module_id/version/knowledge_version 不得为空")
        _dt(self.registered_at)
        if type(self.rules) is not tuple or not all(type(rule) is TemporalRule for rule in self.rules):
            raise ContractError("module.rules 必须是 TemporalRule")
        if type(self.projections) is not tuple or not all(type(projection) is TaskProjection for projection in self.projections):
            raise ContractError("module.projections 必须是 TaskProjection")
        if len(self.rules) > _MAX_RULES_PER_MODULE:
            raise ContractError(f"module.rules 超过预算 {_MAX_RULES_PER_MODULE}")
        if len(self.projections) > _MAX_PROJECTIONS_PER_MODULE:
            raise ContractError(f"module.projections 超过预算 {_MAX_PROJECTIONS_PER_MODULE}")
        rule_ids = [r.rule_id for r in self.rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ContractError("同一 module 中 rule_id 重复")
        tasks = [p.task for p in self.projections]
        if len(tasks) != len(set(tasks)):
            raise ContractError("同一 module 中 projection.task 重复")
        reserved = sorted(set(tasks) & _RESERVED_TASKS)
        if reserved:
            raise ContractError(f"module 不得覆盖内置安全 projection: {reserved}")
        cycle = _rule_cycle(self.rules)
        if cycle:
            raise ContractError(f"positive rule dependency 必须无环: {' -> '.join(cycle)}")

    @classmethod
    def from_data(cls, data: Mapping[str, Any] | "TemporalRuleModule") -> "TemporalRuleModule":
        if type(data) is cls:
            return data
        if type(data) is not dict:
            raise ContractError("module 必须是无 callback 的 mapping/TemporalRuleModule")
        _validate_closed_json(data, "module")
        _strict_fields(data, {"module_id", "version", "registered_at", "knowledge_version", "rules", "projections"}, "module")
        for name in ("module_id", "version", "registered_at"):
            if type(data.get(name)) is not str:
                raise ContractError(f"module.{name} 必须是 exact str")
        if type(data.get("knowledge_version", "knowledge-v1")) is not str:
            raise ContractError("module.knowledge_version 必须是 exact str")
        if type(data.get("rules", [])) is not list or type(data.get("projections", [])) is not list:
            raise ContractError("module.rules/projections 必须是 exact list")
        return cls(
            module_id=str(data.get("module_id", "")),
            version=str(data.get("version", "")),
            registered_at=str(data.get("registered_at", "")),
            knowledge_version=str(data.get("knowledge_version", "knowledge-v1")),
            rules=tuple(TemporalRule.from_data(r) for r in data.get("rules", ())),
            projections=tuple(TaskProjection.from_data(p) for p in data.get("projections", ())),
        )

    def to_data(self) -> dict[str, Any]:
        return {
            "module_id": self.module_id,
            "version": self.version,
            "registered_at": self.registered_at,
            "knowledge_version": self.knowledge_version,
            "rules": [r.to_data() for r in self.rules],
            "projections": [p.to_data() for p in self.projections],
        }


def _revalidate_typed_module(module: Any) -> TemporalRuleModule:
    """Revalidate a possibly-corrupted frozen module before copying/hashing."""

    if type(module) is not TemporalRuleModule:
        raise ContractError("module 必须是 exact TemporalRuleModule")
    if type(module.rules) is not tuple or type(module.projections) is not tuple:
        raise ContractError("typed module rules/projections 类型非法")
    for rule in module.rules:
        if type(rule) is not TemporalRule:
            raise ContractError("typed module rule 类型非法")
        if type(rule.premises) is not tuple:
            raise ContractError("typed rule premises 类型非法")
        for premise in rule.premises:
            if type(premise) is not TemporalPremise:
                raise ContractError("typed premise 类型非法")
            premise.__post_init__()
        if type(rule.conclusion) is not RuleConclusion:
            raise ContractError("typed conclusion 类型非法")
        rule.conclusion.__post_init__()
        rule.__post_init__()
    for projection in module.projections:
        if type(projection) is not TaskProjection:
            raise ContractError("typed projection 类型非法")
        projection.__post_init__()
    module.__post_init__()
    # Only after every nested object is proven exact/closed may conversion run.
    _validate_closed_json(module.to_data(), "typed module")
    return module


def _rule_cycle(rules: Sequence[TemporalRule]) -> list[str]:
    graph: dict[str, set[str]] = {}
    for rule in rules:
        target = rule.conclusion.concept
        for premise in rule.premises:
            graph.setdefault(premise.concept, set()).add(target)
        graph.setdefault(target, set())
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []

    def walk(node: str) -> list[str] | None:
        if node in visiting:
            index = stack.index(node)
            return stack[index:] + [node]
        if node in visited:
            return None
        visiting.add(node)
        stack.append(node)
        for nxt in sorted(graph.get(node, ())):
            found = walk(nxt)
            if found:
                return found
        stack.pop()
        visiting.remove(node)
        visited.add(node)
        return None

    for node in sorted(graph):
        found = walk(node)
        if found:
            return found
    return []


@dataclass(frozen=True)
class _Fact:
    fact_id: str
    concept: str
    semantic_role: SemanticRole
    information_state: InfoState
    value: Any
    unit: str | None
    method: str | None
    context: Mapping[str, Any]
    scope: Scope
    effective_start: datetime
    effective_end: datetime | None
    collected_at: datetime | None
    available_at: datetime
    recorded_at: datetime
    expires_at: datetime | None
    roots: frozenset[str]
    source_families: frozenset[str]
    support_ids: tuple[str, ...]
    derivation: Mapping[str, Any]

    def semantic_key(self) -> tuple[str, ...]:
        masked = self.information_state is InfoState.MASKED or self.semantic_role is SemanticRole.MASKED_ARTIFACT
        return (
            self.concept,
            self.semantic_role.value,
            self.information_state.value,
            _canonical("__MASKED__" if masked else self.value),
            self.unit or "",
            _canonical(_plain(self.scope)),
            _iso(self.effective_start) or "",
            _iso(self.effective_end) or "",
            _iso(self.expires_at) or "",
        )

    def to_claim(self) -> dict[str, Any]:
        masked = self.information_state is InfoState.MASKED or self.semantic_role is SemanticRole.MASKED_ARTIFACT
        return {
            "claim_id": self.fact_id,
            "concept": self.concept,
            "semantic_role": self.semantic_role.value,
            "information_state": self.information_state.value,
            "value": None if masked else _plain(self.value),
            "unit": self.unit,
            "method": self.method,
            "context": {"redacted": True} if masked else _plain(self.context),
            "scope": _plain(self.scope),
            "effective_start": _iso(self.effective_start),
            "effective_end": _iso(self.effective_end),
            "collected_at": _iso(self.collected_at),
            "available_at": _iso(self.available_at),
            "recorded_at": _iso(self.recorded_at),
            "expires_at": _iso(self.expires_at),
            "root_sources": sorted(self.roots),
            "source_families": sorted(self.source_families),
            "support_ids": list(self.support_ids),
            "derivation": _plain(self.derivation),
        }


_BUILTIN_PROJECTIONS: dict[str, TaskProjection] = {
    "all": TaskProjection(task="all"),
    "audit": TaskProjection(task="audit"),
    "presentation": TaskProjection(
        task="presentation",
        include_roles=(
            SemanticRole.RAW_OBSERVATION,
            SemanticRole.SUBJECT_STATEMENT,
            SemanticRole.DETERMINISTIC_DERIVATION,
            SemanticRole.PERFORMED_INTERVENTION,
            SemanticRole.STOPPED_INTERVENTION,
            SemanticRole.MASKED_ARTIFACT,
        ),
    ),
    "observation": TaskProjection(
        task="observation",
        include_roles=(SemanticRole.RAW_OBSERVATION, SemanticRole.SUBJECT_STATEMENT, SemanticRole.DETERMINISTIC_DERIVATION),
    ),
    "diagnosis": TaskProjection(
        task="diagnosis",
        include_roles=(
            SemanticRole.RAW_OBSERVATION,
            SemanticRole.SUBJECT_STATEMENT,
            SemanticRole.DETERMINISTIC_DERIVATION,
            SemanticRole.MODEL_INFERENCE,
            SemanticRole.HYPOTHESIS,
            SemanticRole.PERFORMED_INTERVENTION,
            SemanticRole.STOPPED_INTERVENTION,
        ),
    ),
    "medication_safety": TaskProjection(
        task="medication_safety",
        include_roles=(
            SemanticRole.RAW_OBSERVATION,
            SemanticRole.SUBJECT_STATEMENT,
            SemanticRole.DETERMINISTIC_DERIVATION,
            SemanticRole.PERFORMED_INTERVENTION,
            SemanticRole.STOPPED_INTERVENTION,
        ),
    ),
    "planning": TaskProjection(
        task="planning",
        include_roles=(SemanticRole.PLAN, SemanticRole.ORDER),
    ),
    "performed": TaskProjection(
        task="performed",
        include_roles=(SemanticRole.PERFORMED_INTERVENTION, SemanticRole.STOPPED_INTERVENTION),
    ),
    "action": TaskProjection(
        task="action",
        include_roles=(SemanticRole.PLAN, SemanticRole.ORDER, SemanticRole.PERFORMED_INTERVENTION, SemanticRole.STOPPED_INTERVENTION),
    ),
}


class TemporalEvidenceLedger(ArchitectureCandidate):
    """Append-only typed evidence plus query-time truth maintenance closure."""

    VERSION = "0.3.0"

    def __init__(self, track: Track = Track.NATIVE) -> None:
        super().__init__(track)
        self._artifacts: dict[str, SourceArtifact] = {}
        self._artifact_ids: dict[str, str] = {}
        self._retractions: dict[str, datetime] = {}
        self._modules: dict[tuple[str, str, str], TemporalRuleModule] = {}
        self._results: dict[str, dict[str, Any]] = {}

    @property
    def manifest(self) -> CandidateManifest:
        return CandidateManifest(
            candidate_id="temporal-evidence-ledger-positive-tms",
            version=self.VERSION,
            formal_signature=(
                "Artifact(scope, semantic_role, information_state, value, clocks, source)",
                "PositivePremise(concept, role, information_state, closed value guard)",
                "Rule(premises, deterministic conclusion, temporal/scope guard)",
                "Derivation(root-source union, support tuple, rule version)",
                "Projection(task, included roles/concepts)",
            ),
            execution_semantics=(
                "append/idempotent-ingest",
                "bitemporal-eligibility-with-expiry",
                "positive-acyclic-fixpoint",
                "root-provenance-union",
                "source-retraction-and-supersession",
                "replay-as-then-versus-reinterpret-now",
                "role-preserving-task-projection",
            ),
            companion_layers=(),
            primitive_profile={
                "evidence": ("typed artifact", "explicit information state", "root source", "source family"),
                "time": ("effective interval", "collection", "availability", "record", "expiry"),
                "rules": ("positive premise", "closed guard", "deterministic conclusion", "scope relation"),
                "maintenance": ("retraction", "supersession", "clean rebuild", "module version"),
                "projection": ("semantic role", "task projection", "conflict-preserving claim set"),
            },
            foreign_boundaries=(
                {"boundary": "physiological dynamics", "policy": "unsupported", "reason": "no latent transition kernel"},
                {"boundary": "causal intervention/counterfactual", "policy": "unsupported", "reason": "no SCM/do semantics"},
                {"boundary": "module execution", "policy": "closed typed data only", "callbacks": False},
            ),
            declared_query_capabilities=(QueryKind.PROJECT, QueryKind.REPLAY_AS_THEN, QueryKind.REINTERPRET_NOW),
            failure_types=(
                ResultStatus.UNSUPPORTED,
                ResultStatus.INSUFFICIENT,
                ResultStatus.CONFLICTING,
                ResultStatus.INVALID,
                ResultStatus.NUMERICAL_FAILURE,
                ResultStatus.OUT_OF_MODEL,
            ),
        )

    def _remember(self, result_id: str, result: CapabilityResult, trace: Mapping[str, Any]) -> CapabilityResult:
        result.diagnostics.setdefault("result_id", result_id)
        self._results[result_id] = {"result": result.to_dict(), "trace": _plain(trace)}
        return result

    def ingest(self, artifact: SourceArtifact) -> CapabilityResult:
        try:
            _validate_artifact_input(artifact)
            if len(self._artifacts) >= _MAX_ARTIFACTS and artifact.source_id not in self._artifacts:
                raise ContractError(f"ledger artifacts 超过预算 {_MAX_ARTIFACTS}")
            fingerprint = _digest(artifact)
        except (ContractError, TypeError, ValueError, OverflowError) as exc:
            return CapabilityResult(
                status=ResultStatus.INVALID,
                validation="invalid",
                capability="native",
                epistemic="not_applicable",
                coverage_status="not_evaluated",
                identification="not_applicable",
                computation="not_applicable",
                diagnostics={"error": str(exc)},
            )
        existing = self._artifacts.get(artifact.source_id)
        masked_artifact = (
            artifact.information_state is InfoState.MASKED
            or artifact.semantic_role is SemanticRole.MASKED_ARTIFACT
        )
        public_fingerprint = None if masked_artifact else fingerprint
        if existing is not None:
            same = _digest(existing) == fingerprint
            status = ResultStatus.OK if same else ResultStatus.INVALID
            result = CapabilityResult(
                status=status,
                validation="valid" if same else "invalid",
                capability="native",
                epistemic="asserted" if same else "not_applicable",
                coverage_status="complete" if same else "not_evaluated",
                identification="not_applicable",
                computation="exact",
                value_kind="ingest_receipt",
                value={"source_id": artifact.source_id, "artifact_id": artifact.artifact_id, "idempotent": same, "accepted": same},
                evidence_witness={"root_sources": [artifact.source_id]},
                native_witness={
                    "operation": "idempotent-source-ingest",
                    "fingerprint": public_fingerprint,
                    "fingerprint_redacted": masked_artifact,
                },
                diagnostics={} if same else {"error": "source_id already bound to different immutable artifact"},
                versions={"candidate": self.VERSION, "mapping": artifact.mapping_version},
            )
            return self._remember(f"ingest:{artifact.source_id}", result, {"existing": True, "same_fingerprint": same})
        owner = self._artifact_ids.get(artifact.artifact_id)
        if owner is not None:
            result = CapabilityResult(
                status=ResultStatus.INVALID,
                validation="invalid",
                capability="native",
                epistemic="not_applicable",
                coverage_status="not_evaluated",
                identification="not_applicable",
                computation="not_applicable",
                diagnostics={"error": "artifact_id already belongs to another source_id", "owner": owner},
            )
            return self._remember(f"ingest:{artifact.source_id}", result, {"artifact_id_collision": artifact.artifact_id})
        if artifact.supersedes in {artifact.source_id, artifact.artifact_id}:
            result = CapabilityResult(
                status=ResultStatus.INVALID,
                validation="invalid",
                capability="native",
                epistemic="not_applicable",
                coverage_status="not_evaluated",
                identification="not_applicable",
                computation="not_applicable",
                diagnostics={"error": "artifact cannot supersede itself"},
            )
            return self._remember(f"ingest:{artifact.source_id}", result, {"self_supersession": True})
        tentative_artifacts = dict(self._artifacts)
        tentative_artifacts[artifact.source_id] = artifact
        tentative_ids = dict(self._artifact_ids)
        tentative_ids[artifact.artifact_id] = artifact.source_id
        cycle = self._supersession_cycle(tentative_artifacts, tentative_ids)
        if cycle:
            result = CapabilityResult(
                status=ResultStatus.INVALID,
                validation="invalid",
                capability="native",
                epistemic="not_applicable",
                coverage_status="not_evaluated",
                identification="not_applicable",
                computation="not_applicable",
                diagnostics={"error": "supersession graph cycle", "cycle": cycle},
            )
            return self._remember(f"ingest:{artifact.source_id}", result, {"supersession_cycle": cycle})
        # ``frozen=True`` is shallow for nested mappings; keep a private copy so
        # caller mutation cannot rewrite an already-ingested root.
        stored_artifact = deepcopy(artifact)
        self._artifacts[artifact.source_id] = stored_artifact
        self._artifact_ids[artifact.artifact_id] = artifact.source_id
        result = CapabilityResult(
            status=ResultStatus.OK,
            validation="valid",
            capability="native",
            epistemic="asserted",
            coverage_status="complete",
            identification="not_applicable",
            computation="exact",
            value_kind="ingest_receipt",
            value={"source_id": artifact.source_id, "artifact_id": artifact.artifact_id, "idempotent": False, "accepted": True},
            evidence_witness={"root_sources": [artifact.source_id]},
            native_witness={
                "operation": "append-source",
                "fingerprint": public_fingerprint,
                "fingerprint_redacted": masked_artifact,
            },
            versions={"candidate": self.VERSION, "mapping": artifact.mapping_version},
        )
        return self._remember(f"ingest:{artifact.source_id}", result, {"artifact": _artifact_witness(artifact)})

    def retract(self, source_id: str, known_at: str) -> CapabilityResult:
        try:
            if type(source_id) is not str or not source_id:
                raise ContractError("source_id 必须是非空 exact str")
            if type(known_at) is not str:
                raise ContractError("known_at 必须是 exact str")
            when = _dt(known_at)
            if when is None:
                raise ContractError("known_at required")
        except (ContractError, ValueError) as exc:
            return CapabilityResult(
                status=ResultStatus.INVALID,
                validation="invalid",
                capability="native",
                epistemic="not_applicable",
                coverage_status="not_evaluated",
                identification="not_applicable",
                computation="not_applicable",
                diagnostics={"error": str(exc)},
            )
        artifact = self._artifacts.get(source_id)
        if artifact is None:
            result = CapabilityResult(
                status=ResultStatus.INSUFFICIENT,
                validation="valid",
                capability="native",
                epistemic="insufficient",
                coverage_status="source_not_found",
                identification="not_applicable",
                computation="exact",
                value_kind="retraction_receipt",
                value={"source_id": source_id, "retracted": False},
                diagnostics={"reason": "unknown source_id"},
            )
            return self._remember(f"retract:{source_id}:{_iso(when)}", result, {"source_found": False})
        recorded = _dt(artifact.clocks.recorded_at)
        assert recorded is not None
        if when < recorded:
            result = CapabilityResult(
                status=ResultStatus.INVALID,
                validation="invalid",
                capability="native",
                epistemic="not_applicable",
                coverage_status="not_evaluated",
                identification="not_applicable",
                computation="not_applicable",
                diagnostics={"error": "retraction known_at precedes source recorded_at"},
            )
            return self._remember(f"retract:{source_id}:{_iso(when)}", result, {"recorded_at": artifact.clocks.recorded_at})
        previous = self._retractions.get(source_id)
        effective = min(previous, when) if previous else when
        self._retractions[source_id] = effective
        result = CapabilityResult(
            status=ResultStatus.OK,
            validation="valid",
            capability="native",
            epistemic="retracted",
            coverage_status="complete",
            identification="not_applicable",
            computation="exact",
            value_kind="retraction_receipt",
            value={"source_id": source_id, "retracted": True, "known_at": _iso(effective), "idempotent": previous == effective},
            evidence_witness={"root_sources": [source_id]},
            native_witness={"operation": "source-retraction", "invalidates_derived_closure": True},
            versions={"candidate": self.VERSION},
        )
        return self._remember(f"retract:{source_id}:{_iso(when)}", result, {"previous": _iso(previous), "effective": _iso(effective)})

    def register_module(self, module: Any) -> CapabilityResult:
        try:
            if type(module) is TemporalRuleModule:
                parsed = _revalidate_typed_module(module)
            else:
                parsed = TemporalRuleModule.from_data(module)
                _revalidate_typed_module(parsed)
            key = (parsed.knowledge_version, parsed.module_id, parsed.version)
            fingerprint = _digest(parsed.to_data())
            previous = self._modules.get(key)
            if previous is not None:
                same = _digest(previous.to_data()) == fingerprint
                if not same:
                    raise ContractError("same module/version has different immutable content")
                return CapabilityResult(
                    status=ResultStatus.OK,
                    validation="valid",
                    capability="native",
                    epistemic="not_applicable",
                    coverage_status="complete",
                    identification="not_applicable",
                    computation="exact",
                    value_kind="module_receipt",
                    value={"module_id": parsed.module_id, "version": parsed.version, "idempotent": True},
                    native_witness={"closed_ir": True, "fingerprint": fingerprint},
                    versions={"candidate": self.VERSION, "knowledge": parsed.knowledge_version, "module": parsed.version},
                )
            for existing in self._modules.values():
                if (
                    existing.knowledge_version == parsed.knowledge_version
                    and existing.module_id == parsed.module_id
                    and existing.version != parsed.version
                    and _dt(existing.registered_at) == _dt(parsed.registered_at)
                ):
                    raise ContractError("same module_id timestamp cannot contain multiple opaque versions")
            # Reject cycles at *every* historical module-version cut, not only
            # in today's latest set.  Otherwise a later empty replacement can
            # hide an illegal older self-support cycle from replay.
            tentative = dict(self._modules)
            stored_module = deepcopy(parsed)
            tentative[key] = stored_module
            cutoffs = sorted(
                {
                    _dt(candidate.registered_at)
                    for candidate in tentative.values()
                    if candidate.knowledge_version == parsed.knowledge_version
                }
            )
            for cutoff in cutoffs:
                assert cutoff is not None
                active_at_cut = self._select_modules_from(tentative, parsed.knowledge_version, cutoff)
                cycle = _rule_cycle(tuple(r for m in active_at_cut for r in m.rules))
                if cycle:
                    raise ContractError(
                        f"module graph cycle at {_iso(cutoff)}: {' -> '.join(cycle)}"
                    )
            self._modules[key] = stored_module
        except (ContractError, TypeError, ValueError, OverflowError, RecursionError) as exc:
            return CapabilityResult(
                status=ResultStatus.INVALID,
                validation="invalid",
                capability="native",
                epistemic="not_applicable",
                coverage_status="not_evaluated",
                identification="not_applicable",
                computation="not_applicable",
                diagnostics={"error": str(exc), "closed_ir_required": True, "callbacks_accepted": False},
            )
        result = CapabilityResult(
            status=ResultStatus.OK,
            validation="valid",
            capability="native",
            epistemic="not_applicable",
            coverage_status="complete",
            identification="not_applicable",
            computation="exact",
            value_kind="module_receipt",
            value={
                "module_id": parsed.module_id,
                "version": parsed.version,
                "knowledge_version": parsed.knowledge_version,
                "rules": len(parsed.rules),
                "projections": len(parsed.projections),
                "idempotent": False,
            },
            native_witness={"closed_ir": True, "acyclic": True, "fingerprint": fingerprint},
            versions={"candidate": self.VERSION, "knowledge": parsed.knowledge_version, "module": parsed.version},
        )
        return self._remember(f"module:{parsed.knowledge_version}:{parsed.module_id}:{parsed.version}", result, parsed.to_data())

    def _select_modules_from(
        self,
        modules: Mapping[tuple[str, str, str], TemporalRuleModule],
        knowledge_version: str,
        cutoff: datetime | None,
    ) -> list[TemporalRuleModule]:
        eligible = [
            module
            for (knowledge, _, _), module in modules.items()
            if knowledge == knowledge_version and (cutoff is None or (_dt(module.registered_at) or cutoff) <= cutoff)
        ]
        grouped: dict[str, list[TemporalRuleModule]] = {}
        for module in eligible:
            grouped.setdefault(module.module_id, []).append(module)
        selected: list[TemporalRuleModule] = []
        for module_id in sorted(grouped):
            selected.append(max(grouped[module_id], key=lambda m: ((_dt(m.registered_at) or datetime.min.replace(tzinfo=timezone.utc)), m.version)))
        return selected

    def _select_modules(self, spec: QuerySpec, as_known: datetime) -> list[TemporalRuleModule]:
        cutoff = None if spec.kind is QueryKind.REINTERPRET_NOW else as_known
        return self._select_modules_from(self._modules, spec.knowledge_version, cutoff)

    @staticmethod
    def _supersession_cycle(
        artifacts: Mapping[str, SourceArtifact], artifact_ids: Mapping[str, str]
    ) -> list[str]:
        def predecessor(source_id: str) -> str | None:
            ref = artifacts[source_id].supersedes
            if not ref:
                return None
            if ref in artifacts:
                return ref
            return artifact_ids.get(ref)

        for origin in sorted(artifacts):
            order: list[str] = []
            seen: dict[str, int] = {}
            node: str | None = origin
            while node is not None and node in artifacts:
                if node in seen:
                    return order[seen[node] :] + [node]
                seen[node] = len(order)
                order.append(node)
                node = predecessor(node)
        return []

    @staticmethod
    def _valid_at(artifact: SourceArtifact, valid_at: datetime) -> bool:
        start = _dt(artifact.clocks.effective_start)
        end = _dt(artifact.clocks.effective_end)
        expires = _dt(artifact.clocks.expires_at)
        assert start is not None
        return start <= valid_at and (end is None or valid_at < end) and (expires is None or valid_at < expires)

    def _eligible_artifacts(self, spec: QuerySpec, as_known: datetime, valid_at: datetime) -> list[SourceArtifact]:
        selected: list[SourceArtifact] = []
        for source_id, artifact in self._artifacts.items():
            if artifact.scope.subject_id != spec.subject_id:
                continue
            available = _dt(artifact.clocks.available_at)
            recorded = _dt(artifact.clocks.recorded_at)
            assert available is not None and recorded is not None
            if available > as_known or recorded > as_known:
                continue
            retracted = self._retractions.get(source_id)
            if retracted is not None and retracted <= as_known:
                continue
            if not self._valid_at(artifact, valid_at):
                continue
            selected.append(artifact)

        # A correction suppresses its named predecessor only when the correction
        # itself is eligible.  The predecessor can be addressed by source or
        # artifact id; no disease/test-specific knowledge is involved.
        suppressed: set[str] = set()
        for artifact in selected:
            if artifact.supersedes:
                suppressed.add(artifact.supersedes)
                owner = self._artifact_ids.get(artifact.supersedes)
                if owner:
                    suppressed.add(owner)
        return sorted(
            [a for a in selected if a.source_id not in suppressed and a.artifact_id not in suppressed],
            key=lambda a: (a.clocks.recorded_at, a.source_id),
        )

    @staticmethod
    def _source_fact(artifact: SourceArtifact) -> _Fact:
        start = _dt(artifact.clocks.effective_start)
        available = _dt(artifact.clocks.available_at)
        recorded = _dt(artifact.clocks.recorded_at)
        assert start is not None and available is not None and recorded is not None
        return _Fact(
            fact_id=f"source:{artifact.source_id}",
            concept=artifact.concept,
            semantic_role=artifact.semantic_role,
            information_state=artifact.information_state,
            value=artifact.value,
            unit=artifact.unit,
            method=artifact.method,
            context=dict(artifact.context),
            scope=artifact.scope,
            effective_start=start,
            effective_end=_dt(artifact.clocks.effective_end),
            collected_at=_dt(artifact.clocks.collected_at),
            available_at=available,
            recorded_at=recorded,
            expires_at=_dt(artifact.clocks.expires_at),
            roots=frozenset({artifact.source_id}),
            source_families=frozenset({artifact.source_family}) if artifact.source_family else frozenset(),
            support_ids=(),
            derivation={"kind": "source", "artifact_id": artifact.artifact_id, "mapping_version": artifact.mapping_version},
        )

    @staticmethod
    def _premise_matches(premise: TemporalPremise, fact: _Fact) -> bool:
        if fact.concept != premise.concept:
            return False
        if fact.information_state not in premise.information_states or fact.semantic_role not in premise.semantic_roles:
            return False
        if premise.unit is not None and fact.unit != premise.unit:
            return False
        if premise.method is not None and fact.method != premise.method:
            return False
        if premise.equals is not _MISSING and _canonical(fact.value) != _canonical(premise.equals):
            return False
        if premise.min_value is not None or premise.max_value is not None:
            if isinstance(fact.value, bool) or not isinstance(fact.value, (int, float)):
                return False
            if premise.min_value is not None and float(fact.value) < premise.min_value:
                return False
            if premise.max_value is not None and float(fact.value) > premise.max_value:
                return False
        return True

    @staticmethod
    def _scope_ok(facts: Sequence[_Fact], relation: str) -> bool:
        if len({f.scope.subject_id for f in facts}) != 1:
            return False
        if relation == "same_subject":
            return True
        if relation == "same_encounter":
            values = [f.scope.encounter_id for f in facts]
            return all(v is not None for v in values) and len(set(values)) == 1
        if relation == "same_specimen":
            values = [f.scope.specimen_id for f in facts]
            return all(v is not None for v in values) and len(set(values)) == 1
        for field_name in ("encounter_id", "specimen_id", "device_id", "site_id", "body_site"):
            non_null = {getattr(f.scope, field_name) for f in facts if getattr(f.scope, field_name) is not None}
            if len(non_null) > 1:
                return False
        return True

    @staticmethod
    def _merge_scope(facts: Sequence[_Fact]) -> Scope:
        kwargs: dict[str, Any] = {"subject_id": facts[0].scope.subject_id}
        for field_name in ("encounter_id", "specimen_id", "device_id", "site_id", "body_site"):
            values = {getattr(f.scope, field_name) for f in facts if getattr(f.scope, field_name) is not None}
            kwargs[field_name] = next(iter(values)) if len(values) == 1 else None
        return Scope(**kwargs)

    @staticmethod
    def _combo_ok(rule: TemporalRule, facts: Sequence[_Fact]) -> bool:
        if len({f.fact_id for f in facts}) != len(facts):
            return False
        if not TemporalEvidenceLedger._scope_ok(facts, rule.scope_relation):
            return False
        times = [f.effective_start for f in facts]
        if rule.ordered and times != sorted(times):
            return False
        if rule.max_span_hours is not None:
            span = (max(times) - min(times)).total_seconds() / 3600.0
            if span > rule.max_span_hours:
                return False
        return True

    @staticmethod
    def _derive(module: TemporalRuleModule, rule: TemporalRule, facts: Sequence[_Fact]) -> _Fact | None:
        conclusion = rule.conclusion
        value = facts[conclusion.value_from].value if conclusion.value_from is not None else conclusion.value
        unit = facts[conclusion.unit_from].unit if conclusion.unit_from is not None else conclusion.unit
        start = max(f.effective_start for f in facts)
        finite_ends = [f.effective_end for f in facts if f.effective_end is not None]
        end = min(finite_ends) if finite_ends else None
        finite_expiry = [f.expires_at for f in facts if f.expires_at is not None]
        expires = min(finite_expiry) if finite_expiry else None
        if (end is not None and end <= start) or (expires is not None and expires <= start):
            return None
        roots = frozenset().union(*(f.roots for f in facts))
        families = frozenset().union(*(f.source_families for f in facts))
        support_ids = tuple(f.fact_id for f in facts)
        derivation = {
            "kind": "positive_rule",
            "module_id": module.module_id,
            "module_version": module.version,
            "knowledge_version": module.knowledge_version,
            "rule_id": rule.rule_id,
            "registered_at": module.registered_at,
        }
        identity = {
            "concept": conclusion.concept,
            "role": conclusion.semantic_role.value,
            "state": conclusion.information_state.value,
            "value": _plain(value),
            "unit": unit,
            "scope": _plain(TemporalEvidenceLedger._merge_scope(facts)),
            "start": _iso(start),
            "end": _iso(end),
            "expiry": _iso(expires),
            "roots": sorted(roots),
            "supports": list(support_ids),
            "derivation": derivation,
        }
        return _Fact(
            fact_id=f"derived:{_digest(identity)[:24]}",
            concept=conclusion.concept,
            semantic_role=conclusion.semantic_role,
            information_state=conclusion.information_state,
            value=value,
            unit=unit,
            method=f"rule:{module.module_id}/{rule.rule_id}",
            context=dict(conclusion.context),
            scope=TemporalEvidenceLedger._merge_scope(facts),
            effective_start=start,
            effective_end=end,
            collected_at=max((f.collected_at for f in facts if f.collected_at is not None), default=None),
            available_at=max(f.available_at for f in facts),
            recorded_at=max(f.recorded_at for f in facts),
            expires_at=expires,
            roots=roots,
            source_families=families,
            support_ids=support_ids,
            derivation=derivation,
        )

    def _closure(self, artifacts: Sequence[SourceArtifact], modules: Sequence[TemporalRuleModule]) -> tuple[list[_Fact], dict[str, Any]]:
        facts: dict[str, _Fact] = {f.fact_id: f for f in (self._source_fact(a) for a in artifacts)}
        applications: list[dict[str, Any]] = []
        rules = [(m, r) for m in modules for r in m.rules]
        combinations_checked = 0
        # Acyclic dependencies guarantee at most one new concept layer per pass.
        for _ in range(max(1, len(rules) + 1)):
            added = 0
            snapshot = list(facts.values())
            for module, rule in rules:
                pools = [[f for f in snapshot if self._premise_matches(premise, f)] for premise in rule.premises]
                if any(not pool for pool in pools):
                    continue
                for combo in product(*pools):
                    combinations_checked += 1
                    if combinations_checked > _MAX_CLOSURE_COMBINATIONS:
                        raise ContractError(
                            f"closure combination budget exceeded: {_MAX_CLOSURE_COMBINATIONS}"
                        )
                    if not self._combo_ok(rule, combo):
                        continue
                    derived = self._derive(module, rule, combo)
                    if derived is None or derived.fact_id in facts:
                        continue
                    facts[derived.fact_id] = derived
                    if len(facts) > _MAX_CLOSURE_FACTS:
                        raise ContractError(f"closure fact budget exceeded: {_MAX_CLOSURE_FACTS}")
                    applications.append(
                        {
                            "derived_fact": derived.fact_id,
                            "module": module.module_id,
                            "module_version": module.version,
                            "rule": rule.rule_id,
                            "supports": list(derived.support_ids),
                            "root_sources": sorted(derived.roots),
                        }
                    )
                    added += 1
            if added == 0:
                break
        return sorted(facts.values(), key=lambda f: (f.concept, f.semantic_role.value, f.fact_id)), {
            "rule_applications": applications,
            "combinations_checked": combinations_checked,
        }

    @staticmethod
    def _projection_for(task: str | None, modules: Sequence[TemporalRuleModule]) -> tuple[TaskProjection | None, str | None]:
        if task is None:
            return _BUILTIN_PROJECTIONS["all"], None
        if task in _BUILTIN_PROJECTIONS:
            return _BUILTIN_PROJECTIONS[task], None
        custom = [p for module in modules for p in module.projections if p.task == task]
        if custom:
            fingerprints = {_canonical(p.to_data()) for p in custom}
            if len(fingerprints) > 1:
                return None, "active modules define conflicting projection policies"
            return custom[0], None
        return None, "task projection is not registered"

    @staticmethod
    def _project(facts: Iterable[_Fact], policy: TaskProjection, target: str) -> list[_Fact]:
        out: list[_Fact] = []
        for fact in facts:
            if target != "*" and fact.concept != target:
                continue
            if policy.include_roles and fact.semantic_role not in policy.include_roles:
                continue
            if fact.semantic_role in policy.exclude_roles:
                continue
            if policy.include_concepts and fact.concept not in policy.include_concepts:
                continue
            if fact.concept in policy.exclude_concepts:
                continue
            out.append(fact)
        return out

    @staticmethod
    def _resolve(facts: Sequence[_Fact]) -> tuple[ResultStatus, list[dict[str, Any]], dict[str, Any]]:
        # Exact duplicate claims merge their proof alternatives, but facts with
        # distinct semantic roles/scopes remain distinct (plan != performed).
        exact: dict[tuple[str, ...], list[_Fact]] = {}
        for fact in facts:
            exact.setdefault(fact.semantic_key(), []).append(fact)
        claims: list[dict[str, Any]] = []
        for key in sorted(exact):
            alternatives = exact[key]
            representative = alternatives[0].to_claim()
            # Claim identity is semantic and therefore invariant under adding,
            # removing or reordering alternative proofs.  Fact/proof identities
            # remain separately visible for audit.
            semantic_claim_id = f"claim:{_digest(list(key))[:24]}"
            representative["claim_id"] = semantic_claim_id
            representative["claim_ids"] = [semantic_claim_id]
            representative["fact_ids"] = sorted(f.fact_id for f in alternatives)
            proof_alternatives: list[dict[str, Any]] = []
            for fact in alternatives:
                proof_body = {
                    "fact_id": fact.fact_id,
                    "support_ids": list(fact.support_ids),
                    "root_sources": sorted(fact.roots),
                    "derivation": _plain(fact.derivation),
                }
                proof_alternatives.append(
                    {
                        "proof_id": f"proof:{_digest(proof_body)[:24]}",
                        **proof_body,
                    }
                )
            representative["proof_alternatives"] = sorted(proof_alternatives, key=lambda proof: proof["proof_id"])
            representative["root_sources"] = sorted(set().union(*(set(f.roots) for f in alternatives)))
            representative["source_families"] = sorted(set().union(*(set(f.source_families) for f in alternatives)))
            claims.append(representative)

        partitions: dict[tuple[str, str, str], list[_Fact]] = {}
        for fact in facts:
            partitions.setdefault((fact.concept, fact.semantic_role.value, _canonical(_plain(fact.scope))), []).append(fact)
        conflicts: list[dict[str, Any]] = []
        for (concept, role, scope), group in sorted(partitions.items()):
            states = {f.information_state for f in group}
            # Censoring is retained as an interval/bound assertion, not compared
            # as though its threshold were an ordinary exact measurement.
            visible_present = [
                f
                for f in group
                if f.information_state is InfoState.PRESENT and f.semantic_role is not SemanticRole.MASKED_ARTIFACT
            ]
            present_values = {_canonical(f.value) for f in visible_present}
            units = {f.unit for f in visible_present}
            is_conflict = (
                InfoState.CONFLICTING in states
                or len(present_values) > 1
                or len(units) > 1
                or (InfoState.ABSENT in states and bool(present_values))
            )
            if is_conflict:
                conflicts.append(
                    {
                        "concept": concept,
                        "semantic_role": role,
                        "scope": json.loads(scope),
                        "claim_ids": sorted({f"claim:{_digest(list(f.semantic_key()))[:24]}" for f in group}),
                        "fact_ids": sorted(f.fact_id for f in group),
                    }
                )
        if conflicts:
            status = ResultStatus.CONFLICTING
        elif any(
            f.information_state not in _UNKNOWN_STATES and f.semantic_role is not SemanticRole.MASKED_ARTIFACT
            for f in facts
        ):
            status = ResultStatus.OK
        elif any(f.information_state is InfoState.OUT_OF_MODEL for f in facts):
            status = ResultStatus.OUT_OF_MODEL
        else:
            status = ResultStatus.INSUFFICIENT
        return status, claims, {
            "conflicts": conflicts,
            "partition_count": len(partitions),
            "information_states": sorted({f.information_state.value for f in facts}),
        }

    def _unsupported(self, spec: QuerySpec) -> CapabilityResult:
        return self._remember(
            spec.query_id,
            CapabilityResult(
                status=ResultStatus.UNSUPPORTED,
                validation="valid",
                capability="unsupported",
                epistemic="not_applicable",
                coverage_status="not_evaluated",
                identification="not_applicable",
                computation="not_attempted",
                value_kind="unsupported_query",
                value={
                    "claims": [],
                    "hypotheses": [],
                    "trajectory": None,
                    "probability": None,
                    "diagnostics": {
                        "requested_query": spec.kind.value,
                        "requested_task": spec.task,
                        "requested_model_version": spec.model_version,
                        "requested_guarantees": list(spec.requested_guarantees),
                    },
                },
                assumptions=list(spec.assumptions),
                coverage={"declared": [q.value for q in self.manifest.declared_query_capabilities]},
                native_witness={
                    "reason": "ledger has no latent transition or structural causal kernel",
                    "option_disposition": {
                        "task": "not_evaluated_due_to_unsupported_query_kind" if spec.task is not None else "not_requested",
                        "model_version": "unsupported_by_non_model_ledger" if spec.model_version is not None else "not_requested",
                        "requested_guarantees": "not_evaluated_due_to_unsupported_query_kind",
                    },
                },
                diagnostics={
                    "unsupported_query_kind": spec.kind.value,
                    "requested_guarantees": list(spec.requested_guarantees),
                },
                versions={"candidate": self.VERSION},
            ),
            {"query": _plain(spec), "branch": "declared-unsupported-capability"},
        )

    def query(self, spec: QuerySpec) -> CapabilityResult:
        try:
            _validate_query_input(spec)
        except (ContractError, TypeError, ValueError, OverflowError, RecursionError) as exc:
            return CapabilityResult(
                status=ResultStatus.INVALID,
                validation="invalid",
                capability="native",
                epistemic="not_applicable",
                coverage_status="not_evaluated",
                identification="not_applicable",
                computation="not_applicable",
                diagnostics={"error": str(exc)},
            )
        if spec.kind not in self.manifest.declared_query_capabilities:
            return self._unsupported(spec)
        # TEL is not a statistical/causal model.  Treating model_version as a
        # candidate implementation pin would change the field's meaning, so a
        # non-null request is honestly unsupported instead of ignored.
        if spec.model_version is not None:
            return self._remember(
                spec.query_id,
                CapabilityResult(
                    status=ResultStatus.UNSUPPORTED,
                    validation="valid",
                    capability="unsupported",
                    epistemic="not_applicable",
                    coverage_status="not_evaluated",
                    identification="not_applicable",
                    computation="not_attempted",
                    value_kind="unsupported_option",
                    value={"claims": [], "diagnostics": {"unsupported_option": "model_version"}},
                    assumptions=list(spec.assumptions),
                    native_witness={"model_version_semantics": "not present in temporal evidence ledger"},
                    diagnostics={"requested_model_version": spec.model_version},
                    versions={"candidate": self.VERSION, "knowledge": spec.knowledge_version},
                ),
                {"query": _plain(spec), "branch": "unsupported-model-version-option"},
            )
        unsupported_guarantees = sorted(set(spec.requested_guarantees) - set(_SUPPORTED_GUARANTEES))
        if unsupported_guarantees:
            return self._remember(
                spec.query_id,
                CapabilityResult(
                    status=ResultStatus.UNSUPPORTED,
                    validation="valid",
                    capability="unsupported",
                    epistemic="not_applicable",
                    coverage_status="not_evaluated",
                    identification="not_applicable",
                    computation="not_attempted",
                    value_kind="unsupported_guarantee",
                    value={"claims": [], "diagnostics": {"unsupported_guarantees": unsupported_guarantees}},
                    assumptions=list(spec.assumptions),
                    native_witness={
                        "supported_guarantees": dict(_SUPPORTED_GUARANTEES),
                        "requested_guarantees_consumed": False,
                    },
                    diagnostics={"unsupported_guarantees": unsupported_guarantees},
                    versions={"candidate": self.VERSION, "knowledge": spec.knowledge_version},
                ),
                {"query": _plain(spec), "branch": "unsupported-requested-guarantee"},
            )
        # Timestamps were validated above; parsing cannot execute caller code.
        as_known = _dt(spec.as_known_at)
        valid_at = _dt(spec.valid_at) or as_known
        assert as_known is not None and valid_at is not None
        modules = self._select_modules(spec, as_known)
        historical_cycle = _rule_cycle(tuple(rule for module in modules for rule in module.rules))
        if historical_cycle:
            return self._remember(
                spec.query_id,
                CapabilityResult(
                    status=ResultStatus.INVALID,
                    validation="invalid",
                    capability="native",
                    epistemic="not_applicable",
                    coverage_status="not_evaluated",
                    identification="not_applicable",
                    computation="not_attempted",
                    diagnostics={"reason": "selected historical rule set is cyclic", "cycle": historical_cycle},
                    native_witness={"rootless_self_support_rejected": True, **_guarantee_witness(spec)},
                    versions={
                        "candidate": self.VERSION,
                        "knowledge": spec.knowledge_version,
                        "modules": {m.module_id: m.version for m in modules},
                    },
                ),
                {"query": _plain(spec), "illegal_rule_cycle": historical_cycle},
            )
        policy, policy_error = self._projection_for(spec.task, modules)
        if policy is None:
            status = ResultStatus.INVALID if "conflicting" in (policy_error or "") else ResultStatus.UNSUPPORTED
            return self._remember(
                spec.query_id,
                CapabilityResult(
                    status=status,
                    validation="invalid" if status is ResultStatus.INVALID else "valid",
                    capability="native" if status is ResultStatus.INVALID else "unsupported",
                    epistemic="not_applicable",
                    coverage_status="not_evaluated",
                    identification="not_applicable",
                    computation="not_attempted",
                    diagnostics={
                        "task": spec.task,
                        "reason": policy_error,
                        "requested_guarantees": list(spec.requested_guarantees),
                    },
                    versions={"candidate": self.VERSION, "knowledge": spec.knowledge_version},
                ),
                {"query": _plain(spec), "projection_error": policy_error},
            )
        artifacts = self._eligible_artifacts(spec, as_known, valid_at)
        try:
            closure, closure_trace = self._closure(artifacts, modules)
        except (ContractError, OverflowError) as exc:
            return self._remember(
                spec.query_id,
                CapabilityResult(
                    status=ResultStatus.NUMERICAL_FAILURE,
                    validation="valid",
                    capability="native",
                    epistemic="not_applicable",
                    coverage_status="resource_budget_exceeded",
                    identification="not_applicable",
                    computation="failed",
                    value_kind="computation_failure",
                    value={"claims": [], "diagnostics": {"reason": str(exc)}},
                    assumptions=list(spec.assumptions),
                    native_witness={"closed_ir": True, **_guarantee_witness(spec)},
                    diagnostics={"error": str(exc)},
                    versions={
                        "candidate": self.VERSION,
                        "knowledge": spec.knowledge_version,
                        "modules": {m.module_id: m.version for m in modules},
                    },
                ),
                {
                    "query": _plain(spec),
                    "eligible_sources": [a.source_id for a in artifacts],
                    "branch": "closure-resource-budget",
                },
            )
        projected = self._project(closure, policy, spec.target)
        if not projected:
            result = CapabilityResult(
                status=ResultStatus.INSUFFICIENT,
                validation="valid",
                capability="native",
                epistemic="insufficient",
                coverage_status="no_eligible_claim",
                identification="not_applicable",
                computation="exact",
                value_kind="temporal_projection",
                value={
                    "claims": [],
                    "hypotheses": [],
                    "trajectory": None,
                    "probability": None,
                    "diagnostics": {"reason": "no eligible claim; unknown was not coerced to false/zero"},
                },
                assumptions=list(spec.assumptions),
                coverage={"eligible_sources": len(artifacts), "closure_facts": len(closure), "projected_claims": 0},
                time_cut={"as_known_at": _iso(as_known), "valid_at": _iso(valid_at), "mode": spec.kind.value},
                evidence_witness={"root_sources": []},
                native_witness={"projection": policy.to_data(), "unknown_preserved": True, **_guarantee_witness(spec)},
                diagnostics={"target": spec.target, "task": spec.task},
                versions={
                    "candidate": self.VERSION,
                    "knowledge": spec.knowledge_version,
                    "modules": {m.module_id: m.version for m in modules},
                },
            )
            return self._remember(spec.query_id, result, {"query": _plain(spec), "eligible_sources": [a.source_id for a in artifacts], **closure_trace})

        status, claims, resolution = self._resolve(projected)
        root_sources = sorted(set().union(*(set(f.roots) for f in projected)))
        families = sorted(set().union(*(set(f.source_families) for f in projected)))
        root_artifacts = {
            source_id: _artifact_witness(self._artifacts[source_id])
            for source_id in root_sources
            if source_id in self._artifacts
        }
        hypotheses = [claim for claim in claims if claim["semantic_role"] == SemanticRole.HYPOTHESIS.value]
        if status is ResultStatus.CONFLICTING:
            epistemic = "conflicting"
        elif status is ResultStatus.OUT_OF_MODEL:
            epistemic = "out_of_model"
        elif status is ResultStatus.INSUFFICIENT:
            epistemic = (
                "masked"
                if projected
                and all(
                    f.information_state is InfoState.MASKED or f.semantic_role is SemanticRole.MASKED_ARTIFACT
                    for f in projected
                )
                else "insufficient"
            )
        else:
            epistemic = "supported"
        result = CapabilityResult(
            status=status,
            validation="valid",
            capability="native",
            epistemic=epistemic,
            coverage_status="complete_for_projection",
            identification="not_applicable",
            computation="exact",
            value_kind="temporal_projection",
            value={
                "claims": claims,
                "hypotheses": hypotheses,
                "trajectory": None,
                "probability": None,
                "diagnostics": resolution,
            },
            assumptions=list(spec.assumptions),
            coverage={
                "eligible_sources": len(artifacts),
                "closure_facts": len(closure),
                "projected_claims": len(claims),
                "target": spec.target,
                "task": spec.task or "all",
            },
            time_cut={"as_known_at": _iso(as_known), "valid_at": _iso(valid_at), "mode": spec.kind.value},
            evidence_witness={
                "root_sources": root_sources,
                "source_families": families,
                "statistical_independence_assumed": False,
                "root_artifacts": root_artifacts,
                "proofs": [c["proof_alternatives"] for c in claims],
            },
            native_witness={
                "projection": policy.to_data(),
                "rule_applications": closure_trace["rule_applications"],
                "role_partitioned": True,
                "root_provenance_union": True,
                **_guarantee_witness(spec),
            },
            diagnostics={"conflict_count": len(resolution["conflicts"]), "result_id": spec.query_id},
            versions={
                "candidate": self.VERSION,
                "knowledge": spec.knowledge_version,
                "modules": {m.module_id: m.version for m in modules},
            },
        )
        trace = {
            "query": _plain(spec),
            "eligible_sources": [a.source_id for a in artifacts],
            "selected_modules": [m.to_data() for m in modules],
            "projection": policy.to_data(),
            "projected_fact_ids": [f.fact_id for f in projected],
            "resolution": resolution,
            **closure_trace,
        }
        return self._remember(spec.query_id, result, trace)

    def explain(self, result_id: str) -> CapabilityResult:
        record = self._results.get(result_id)
        if record is None:
            return CapabilityResult(
                status=ResultStatus.INSUFFICIENT,
                validation="valid",
                capability="native",
                epistemic="insufficient",
                coverage_status="result_not_found",
                identification="not_applicable",
                computation="exact",
                value_kind="explanation",
                value={"claims": [], "diagnostics": {"result_id": result_id, "reason": "unknown result id"}},
                diagnostics={"result_id": result_id},
                versions={"candidate": self.VERSION},
            )
        return CapabilityResult(
            status=ResultStatus.OK,
            validation="valid",
            capability="native",
            epistemic="supported",
            coverage_status="complete",
            identification="not_applicable",
            computation="exact",
            value_kind="explanation",
            value={"claims": record["result"].get("value", {}).get("claims", []), "trace": record["trace"], "result": record["result"]},
            evidence_witness=record["result"].get("evidence_witness", {}),
            native_witness={"trace_kind": "source/rule/projection", "result_id": result_id},
            versions={"candidate": self.VERSION},
        )

    def clean_rebuild(self) -> "TemporalEvidenceLedger":
        rebuilt = TemporalEvidenceLedger(track=self.track)
        # Modules are immutable, already validated configuration.  Copying the
        # complete accepted version set atomically avoids a false rejection
        # caused only by the registration order of two versions sharing a cut.
        # No patient-derived/cache state is copied.
        rebuilt._modules = deepcopy(self._modules)
        # Replay immutable roots and tombstones, rather than copying any derived
        # cache.  This is equivalent for the current cut *and* preserves the
        # ability to replay a cut before a later retraction.
        for source_id in sorted(self._artifacts):
            rebuilt.ingest(self._artifacts[source_id])
        for source_id, when in sorted(self._retractions.items()):
            rebuilt.retract(source_id, _iso(when) or "")
        return rebuilt


# Short aliases used by the candidate registry and examples.
TemporalLedgerCandidate = TemporalEvidenceLedger


__all__ = [
    "RuleConclusion",
    "TaskProjection",
    "TemporalEvidenceLedger",
    "TemporalLedgerCandidate",
    "TemporalPremise",
    "TemporalRule",
    "TemporalRuleModule",
]
