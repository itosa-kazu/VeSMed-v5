"""候选无关控制面合同。

这里故意不定义统一 ``PatientState``：事件账本的知识态、状态空间模型的
posterior、SCM 的反事实世界和重写系统的 configuration 不是同一种对象。
公共层只规定资格、类型、版本、查询意图、失败与审计回执。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Any, Mapping, Sequence


class ContractError(ValueError):
    """输入违反冻结控制面合同。"""


# These budgets are part of the executable control-plane boundary.  They are
# deliberately generous for the PoC, but finite: a closed JSON-shaped message
# must not turn validation itself into an unbounded computation.
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 65_536
MAX_JSON_BYTES = 1_048_576


def validate_json_like(
    value: Any,
    *,
    label: str = "value",
    max_depth: int = MAX_JSON_DEPTH,
    max_nodes: int = MAX_JSON_NODES,
    max_bytes: int = MAX_JSON_BYTES,
    allow_tuple: bool = True,
) -> None:
    """Validate an inert, exact-builtin JSON-like value without user hooks.

    Only *exact* builtin scalar/container types are accepted.  In particular,
    subclasses, arbitrary ``Mapping`` implementations, dataclasses, enums and
    callables are rejected.  Validation happens before any ``deepcopy``,
    ``asdict``, hashing of supplied keys, or serialization.  Dict keys must be
    exact ``str`` objects.  Cycles, non-finite floats and over-budget values are
    rejected.

    Tuples are admitted as an immutable JSON-like transport convenience used
    by the frozen Python contract.  Wire serialization still emits ordinary
    JSON arrays.
    """

    if type(max_depth) is not int or max_depth < 0:
        raise ContractError("max_depth 必须是非负 exact int")
    if type(max_nodes) is not int or max_nodes < 1:
        raise ContractError("max_nodes 必须是正 exact int")
    if type(max_bytes) is not int or max_bytes < 1:
        raise ContractError("max_bytes 必须是正 exact int")

    nodes = 0
    bytes_used = 0
    active: set[int] = set()

    def add_cost(node_cost: int, byte_cost: int) -> None:
        nonlocal nodes, bytes_used
        nodes += node_cost
        bytes_used += byte_cost
        if nodes > max_nodes:
            raise ContractError(f"{label} 超过 node budget={max_nodes}")
        if bytes_used > max_bytes:
            raise ContractError(f"{label} 超过 byte budget={max_bytes}")

    def visit(item: Any, depth: int, path: str) -> None:
        if depth > max_depth:
            raise ContractError(f"{label} 超过 depth budget={max_depth}: {path}")
        item_type = type(item)
        if item_type is type(None):
            add_cost(1, 4)
            return
        if item_type is bool:
            add_cost(1, 4 if item else 5)
            return
        if item_type is int:
            # Avoid decimal conversion of an attacker-sized integer.  The
            # bit-length estimate is a safe upper bound for budget rejection.
            bits = int.bit_length(item)
            decimal_upper_bound = 1 if bits == 0 else ((bits * 30103) // 100000 + 2)
            add_cost(1, decimal_upper_bound + (1 if item < 0 else 0))
            return
        if item_type is float:
            if not isfinite(item):
                raise ContractError(f"{path} float 必须有限")
            add_cost(1, 24)
            return
        if item_type is str:
            # Any UTF-8 string consumes at least len(item) bytes.  Reject that
            # lower bound before allocating an encoded copy.
            if len(item) > max_bytes - bytes_used:
                raise ContractError(f"{label} 超过 byte budget={max_bytes}")
            add_cost(1, len(str.encode(item, "utf-8")) + 2)
            return
        if item_type is dict:
            identity = id(item)
            if identity in active:
                raise ContractError(f"{path} 不得包含循环引用")
            active.add(identity)
            try:
                add_cost(1, 2)
                # ``dict.items`` is invoked through the builtin descriptor only
                # after exact-type validation; custom mapping hooks cannot run.
                for index, pair in enumerate(dict.items(item)):
                    key, child = pair
                    if type(key) is not str:
                        raise ContractError(f"{path} dict key 必须是 exact str")
                    visit(key, depth + 1, f"{path}.<key:{index}>")
                    add_cost(0, 2)
                    visit(child, depth + 1, f"{path}.{key}")
                    if index:
                        add_cost(0, 1)
            finally:
                active.remove(identity)
            return
        if item_type is list or (allow_tuple and item_type is tuple):
            identity = id(item)
            if identity in active:
                raise ContractError(f"{path} 不得包含循环引用")
            active.add(identity)
            try:
                add_cost(1, 2)
                for index in range(len(item)):
                    if index:
                        add_cost(0, 1)
                    visit(item[index], depth + 1, f"{path}[{index}]")
            finally:
                active.remove(identity)
            return
        raise ContractError(
            f"{path} 只接受 exact-builtin JSON-like 类型；收到 {item_type.__name__}"
        )

    visit(value, 0, label)


def _require_exact_string(value: Any, label: str, *, optional: bool = False) -> None:
    if optional and value is None:
        return
    if type(value) is not str or not value:
        raise ContractError(f"{label} 必须是非空 exact str")


class SemanticRole(str, Enum):
    RAW_OBSERVATION = "raw_observation"
    SUBJECT_STATEMENT = "subject_statement"
    DETERMINISTIC_DERIVATION = "deterministic_derivation"
    MODEL_INFERENCE = "model_inference"
    HYPOTHESIS = "hypothesis"
    PLAN = "plan"
    ORDER = "order"
    PERFORMED_INTERVENTION = "performed_intervention"
    STOPPED_INTERVENTION = "stopped_intervention"
    GENERAL_KNOWLEDGE = "general_knowledge"
    TASK_POLICY = "task_policy"
    MASKED_ARTIFACT = "masked_artifact"


class InfoState(str, Enum):
    PRESENT = "present"
    ABSENT = "absent"
    NOT_ASKED = "not_asked"
    NOT_TESTED = "not_tested"
    UNABLE_TO_ASSESS = "unable_to_assess"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"
    NOT_APPLICABLE = "not_applicable"
    OUT_OF_MODEL = "out_of_model"
    MASKED = "masked"
    CENSORED_LOW = "censored_low"
    CENSORED_HIGH = "censored_high"


class ResultStatus(str, Enum):
    OK = "ok"
    UNSUPPORTED = "unsupported"
    INSUFFICIENT = "insufficient"
    CONFLICTING = "conflicting"
    INVALID = "invalid"
    NUMERICAL_FAILURE = "numerical_failure"
    OUT_OF_MODEL = "out_of_model"


class QueryKind(str, Enum):
    EVIDENCE_VIEW = "evidence_view"
    PROJECT = "project"
    REPLAY_AS_THEN = "replay_as_then"
    REINTERPRET_NOW = "reinterpret_now"
    CONDITION = "condition"
    FILTER = "filter"
    SMOOTH = "smooth"
    FORECAST = "forecast"
    INTERVENE = "intervene"
    COUNTERFACTUAL = "counterfactual"
    EVALUATE_POLICY = "evaluate_policy"
    REACHABILITY = "reachability"
    CHECK_INVARIANT = "check_invariant"
    EXPLAIN = "explain"


class Track(str, Enum):
    NATIVE = "native"
    COMPANION = "companion"


def parse_time(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if type(value) is datetime:
        dt = value
    elif type(value) is str:
        if not value or len(value) > 128:
            raise ContractError("时间字符串为空或过长")
        try:
            dt = datetime.fromisoformat(str.replace(value, "Z", "+00:00"))
        except ValueError as exc:
            raise ContractError(f"非法 ISO-8601 时间: {value!r}") from exc
    else:
        raise ContractError(f"时间必须是 exact str/datetime: {type(value).__name__}")
    if dt.tzinfo is None:
        raise ContractError(f"时间必须含时区: {value!r}")
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Scope:
    subject_id: str
    encounter_id: str | None = None
    specimen_id: str | None = None
    device_id: str | None = None
    site_id: str | None = None
    body_site: str | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        _require_exact_string(self.subject_id, "subject_id")
        for name in ("encounter_id", "specimen_id", "device_id", "site_id", "body_site"):
            _require_exact_string(getattr(self, name), f"scope.{name}", optional=True)


@dataclass(frozen=True)
class ClockSet:
    effective_start: str
    effective_end: str | None
    collected_at: str | None
    available_at: str
    recorded_at: str
    expires_at: str | None = None

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        for name in ("effective_start", "available_at", "recorded_at"):
            _require_exact_string(getattr(self, name), f"clocks.{name}")
        for name in ("effective_end", "collected_at", "expires_at"):
            _require_exact_string(getattr(self, name), f"clocks.{name}", optional=True)
        start = parse_time(self.effective_start)
        end = parse_time(self.effective_end)
        available = parse_time(self.available_at)
        recorded = parse_time(self.recorded_at)
        expires = parse_time(self.expires_at)
        parse_time(self.collected_at)
        if end is not None and start is not None and end <= start:
            raise ContractError("effective_end 必须晚于 effective_start（半开区间）")
        if recorded is not None and available is not None and recorded < available:
            # 允许系统先形成结果、稍后记录；反向则说明字段角色很可能填错。
            raise ContractError("recorded_at 早于 available_at")
        if expires is not None and start is not None and expires <= start:
            raise ContractError("expires_at 必须晚于 effective_start（半开区间）")


@dataclass(frozen=True)
class SourceArtifact:
    artifact_id: str
    source_id: str
    semantic_role: SemanticRole
    concept: str
    scope: Scope
    clocks: ClockSet
    information_state: InfoState = InfoState.PRESENT
    value: Any = None
    unit: str | None = None
    method: str | None = None
    context: Mapping[str, Any] = field(default_factory=dict)
    reliability: float | None = None
    source_family: str | None = None
    supersedes: str | None = None
    raw_payload: Mapping[str, Any] = field(default_factory=dict)
    mapping_version: str = "canonical-v1"

    def __post_init__(self) -> None:
        # Construction performs only hook-free shape checks needed by ordinary
        # callers.  The public runtime boundary must call ``validate`` and turn
        # failures into a typed INVALID result; this also lets adversarial tests
        # prove no hostile ``__deepcopy__`` hook ran before rejection.
        for name in ("artifact_id", "source_id", "concept", "mapping_version"):
            _require_exact_string(getattr(self, name), name)
        if self.reliability is not None and (
            type(self.reliability) not in {int, float}
            or not isfinite(float(self.reliability))
            or not 0.0 <= float(self.reliability) <= 1.0
        ):
            raise ContractError("reliability 必须在 [0,1]")
        if self.semantic_role is SemanticRole.RAW_OBSERVATION:
            if self.information_state is InfoState.PRESENT and self.value is None:
                raise ContractError("present observation 必须有 value")
        if (
            (self.semantic_role is SemanticRole.PLAN or self.semantic_role is SemanticRole.ORDER)
            and type(self.context) is dict
            and dict.get(self.context, "performed")
        ):
            raise ContractError("计划/医嘱不得携带 performed=true")

    def validate(self) -> None:
        for name in ("artifact_id", "source_id", "concept", "mapping_version"):
            _require_exact_string(getattr(self, name), name)
        if type(self.semantic_role) is not SemanticRole:
            raise ContractError("semantic_role 必须是 SemanticRole enum")
        if type(self.information_state) is not InfoState:
            raise ContractError("information_state 必须是 InfoState enum")
        if type(self.scope) is not Scope:
            raise ContractError("scope 必须是 exact Scope")
        Scope.validate(self.scope)
        if type(self.clocks) is not ClockSet:
            raise ContractError("clocks 必须是 exact ClockSet")
        ClockSet.validate(self.clocks)
        for name in ("unit", "method", "source_family", "supersedes"):
            _require_exact_string(getattr(self, name), name, optional=True)
        if self.reliability is not None and (
            type(self.reliability) not in {int, float}
            or not isfinite(float(self.reliability))
            or not 0.0 <= float(self.reliability) <= 1.0
        ):
            raise ContractError("reliability 必须在 [0,1]")
        if type(self.context) is not dict:
            raise ContractError("context 必须是 exact dict")
        if type(self.raw_payload) is not dict:
            raise ContractError("raw_payload 必须是 exact dict")
        validate_json_like(self.value, label="artifact.value")
        validate_json_like(self.context, label="artifact.context")
        validate_json_like(self.raw_payload, label="artifact.raw_payload")
        if self.semantic_role is SemanticRole.RAW_OBSERVATION:
            if self.information_state is InfoState.PRESENT and self.value is None:
                raise ContractError("present observation 必须有 value")
        if self.semantic_role in {SemanticRole.PLAN, SemanticRole.ORDER} and self.context.get("performed"):
            raise ContractError("计划/医嘱不得携带 performed=true")


@dataclass(frozen=True)
class QuerySpec:
    query_id: str
    kind: QueryKind
    target: str
    subject_id: str
    as_known_at: str
    valid_at: str | None = None
    task: str | None = None
    knowledge_version: str = "knowledge-v1"
    model_version: str | None = None
    intervention: Mapping[str, Any] | None = None
    horizon_hours: float | None = None
    requested_guarantees: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    seed: int = 0

    def __post_init__(self) -> None:
        # As with SourceArtifact, candidates re-run the strict validator and
        # return typed INVALID.  Keep constructor checks hook-free and limited
        # to the legacy ergonomic invariants.
        for name in ("query_id", "target", "subject_id", "as_known_at"):
            _require_exact_string(getattr(self, name), name)
        parse_time(self.as_known_at)
        if self.valid_at is not None:
            parse_time(self.valid_at)
        if (
            (self.kind is QueryKind.INTERVENE or self.kind is QueryKind.COUNTERFACTUAL)
            and self.intervention is None
        ):
            raise ContractError(f"{self.kind.value} query 必须声明 intervention")
        if self.kind is QueryKind.FORECAST and self.horizon_hours is None:
            raise ContractError("forecast query 必须声明 horizon_hours")

    def validate(self) -> None:
        for name in ("query_id", "target", "subject_id", "as_known_at", "knowledge_version"):
            _require_exact_string(getattr(self, name), name)
        if type(self.kind) is not QueryKind:
            raise ContractError("kind 必须是 QueryKind enum")
        for name in ("valid_at", "task", "model_version"):
            _require_exact_string(getattr(self, name), name, optional=True)
        parse_time(self.as_known_at)
        parse_time(self.valid_at)
        if self.intervention is not None:
            if type(self.intervention) is not dict:
                raise ContractError("intervention 必须是 exact dict")
            validate_json_like(self.intervention, label="query.intervention")
        if self.horizon_hours is not None and (
            type(self.horizon_hours) not in {int, float}
            or not isfinite(float(self.horizon_hours))
        ):
            raise ContractError("horizon_hours 必须是有限数值")
        for name in ("requested_guarantees", "assumptions"):
            values = getattr(self, name)
            if type(values) is not tuple:
                raise ContractError(f"{name} 必须是 exact tuple")
            if any(type(item) is not str or not item for item in values):
                raise ContractError(f"{name} 只能含非空 exact str")
            if len(values) != len(set(values)):
                raise ContractError(f"{name} 不得含重复项")
            validate_json_like(values, label=f"query.{name}")
        if type(self.seed) is not int:
            raise ContractError("seed 必须是 exact int")
        if self.kind in {QueryKind.INTERVENE, QueryKind.COUNTERFACTUAL} and self.intervention is None:
            raise ContractError(f"{self.kind.value} query 必须声明 intervention")
        if self.kind is QueryKind.FORECAST and self.horizon_hours is None:
            raise ContractError("forecast query 必须声明 horizon_hours")


@dataclass
class CapabilityResult:
    status: ResultStatus
    # 正交结果轴。``status`` 仅为传输兼容摘要；正式判断不得只读它。
    validation: str = "valid"
    capability: str = "native"
    epistemic: str = "not_applicable"
    coverage_status: str = "unknown"
    identification: str = "not_applicable"
    computation: str = "not_applicable"
    value_kind: str = "none"
    value: Any = None
    assumptions: list[str] = field(default_factory=list)
    coverage: dict[str, Any] = field(default_factory=dict)
    time_cut: dict[str, Any] = field(default_factory=dict)
    evidence_witness: dict[str, Any] = field(default_factory=dict)
    native_witness: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    versions: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        if type(self.status) is not ResultStatus:
            raise ContractError("CapabilityResult.status 必须是 ResultStatus enum")
        for name in (
            "validation",
            "capability",
            "epistemic",
            "coverage_status",
            "identification",
            "computation",
            "value_kind",
        ):
            _require_exact_string(getattr(self, name), f"result.{name}")
        if type(self.assumptions) is not list or any(
            type(item) is not str or not item for item in self.assumptions
        ):
            raise ContractError("result.assumptions 必须是非空字符串组成的 exact list")
        validate_json_like(self.assumptions, label="result.assumptions")
        validate_json_like(self.value, label="result.value")
        for name in (
            "coverage",
            "time_cut",
            "evidence_witness",
            "native_witness",
            "diagnostics",
            "versions",
        ):
            item = getattr(self, name)
            if type(item) is not dict:
                raise ContractError(f"result.{name} 必须是 exact dict")
            validate_json_like(item, label=f"result.{name}")

        # Basic cross-axis coherence.  These checks intentionally do not infer
        # the rich axes from the compatibility status; they only reject clear
        # contradictions.
        if self.status is ResultStatus.OK:
            if self.validation != "valid" or self.capability == "unsupported":
                raise ContractError("status=ok 与 validation/capability 轴矛盾")
        if self.status is ResultStatus.INVALID and self.validation != "invalid":
            raise ContractError("status=invalid 必须携带 validation=invalid")
        if self.status is ResultStatus.UNSUPPORTED and self.capability != "unsupported":
            raise ContractError("status=unsupported 必须携带 capability=unsupported")
        if self.status is ResultStatus.CONFLICTING and self.epistemic != "conflicting":
            raise ContractError("status=conflicting 必须携带 epistemic=conflicting")

    def to_dict(self) -> dict[str, Any]:
        # A mutable result may have been changed after construction.  Recheck
        # before any copy/serialization so hostile ``__deepcopy__`` hooks never
        # run.
        self.validate()
        out = {
            "status": self.status.value,
            "validation": self.validation,
            "capability": self.capability,
            "epistemic": self.epistemic,
            "coverage_status": self.coverage_status,
            "identification": self.identification,
            "computation": self.computation,
            "value_kind": self.value_kind,
            "value": self.value,
            "assumptions": self.assumptions,
            "coverage": self.coverage,
            "time_cut": self.time_cut,
            "evidence_witness": self.evidence_witness,
            "native_witness": self.native_witness,
            "diagnostics": self.diagnostics,
            "versions": self.versions,
        }
        validate_json_like(out, label="CapabilityResult")
        # Safe now: the graph contains exact inert builtins only.
        return deepcopy(out)


@dataclass(frozen=True)
class CandidateManifest:
    candidate_id: str
    version: str
    formal_signature: tuple[str, ...]
    execution_semantics: tuple[str, ...]
    companion_layers: tuple[str, ...]
    primitive_profile: Mapping[str, Sequence[str]]
    foreign_boundaries: tuple[Mapping[str, Any], ...]
    declared_query_capabilities: tuple[QueryKind, ...]
    failure_types: tuple[ResultStatus, ...]


class ArchitectureCandidate(ABC):
    """统一控制面；实现内部不得按测试 ID 或 oracle 分支。"""

    def __init__(self, track: Track = Track.NATIVE) -> None:
        self.track = track

    @property
    @abstractmethod
    def manifest(self) -> CandidateManifest:
        raise NotImplementedError

    @abstractmethod
    def ingest(self, artifact: SourceArtifact) -> CapabilityResult:
        raise NotImplementedError

    @abstractmethod
    def retract(self, source_id: str, known_at: str) -> CapabilityResult:
        raise NotImplementedError

    @abstractmethod
    def query(self, spec: QuerySpec) -> CapabilityResult:
        raise NotImplementedError

    @abstractmethod
    def register_module(self, module: Any) -> CapabilityResult:
        """只允许具体实现验证过的 closed typed IR；不得接受 callback。"""
        raise NotImplementedError

    @abstractmethod
    def explain(self, result_id: str) -> CapabilityResult:
        raise NotImplementedError

    @abstractmethod
    def clean_rebuild(self) -> "ArchitectureCandidate":
        """从仍有效的原始输入重建，用于验证撤回/增量等价。"""
        raise NotImplementedError
