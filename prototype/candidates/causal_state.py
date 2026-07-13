"""Finite dynamic-state and structural-causal candidate.

This candidate deliberately has two *native* mathematical kernels rather than an
evidence ledger hidden behind a state-vector API:

``DynamicModule``
    A finite, typed DBN kernel
    ``P(X0) prod_t P(Xt | X[t-1], At) P(Yt | Xt, At)``.  It performs exact
    filtering and finite-horizon prediction by enumeration.

``FiniteSCMModule``
    A finite acyclic SCM ``M=(U,V,F,P(U))``.  It distinguishes observational
    conditioning, population ``do`` intervention, and same-unit
    abduction-action-prediction counterfactuals.

The native track does **not** claim bitemporal evidence replay, truth
maintenance, or derivation lineage.  The companion track adds only a visibly
accounted append-only transaction-cut adapter; the adapter is declared in the
manifest as a foreign event-sourcing semantic family.  Even in companion mode,
the native witness remains a DBN factor trace or SCM AAP trace.

All registered computations use :class:`prototype.ir.Expr`.  Python callbacks,
SQL, prompts, and executable strings are never accepted as module semantics.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from enum import Enum
from itertools import product
from math import isfinite, prod
from typing import Any, Iterable, Mapping, Sequence

from ..contract import (
    ArchitectureCandidate,
    CandidateManifest,
    CapabilityResult,
    ContractError,
    InfoState,
    QueryKind,
    QuerySpec,
    ResultStatus,
    SemanticRole,
    SourceArtifact,
    Track,
    parse_time,
    validate_json_like,
)
from ..ir import Expr


_PROBABILITY_TOLERANCE = 1e-9
_DOMAIN_TOLERANCE = 1e-9


class VariableRole(str, Enum):
    """Closed role vocabulary used by both native kernels."""

    EXOGENOUS = "exogenous"
    LATENT = "latent"
    OBSERVATION = "observation"
    ACTION = "action"
    OUTCOME = "outcome"


def _strict_mapping(
    data: Mapping[str, Any], *, allowed: set[str], required: set[str], label: str
) -> None:
    if type(data) is not dict:
        raise ContractError(f"{label} 必须是 exact dict")
    validate_json_like(data, label=label)
    unknown = set(data) - allowed
    missing = required - set(data)
    if unknown:
        raise ContractError(f"{label} 未知字段: {sorted(unknown)}")
    if missing:
        raise ContractError(f"{label} 缺少字段: {sorted(missing)}")


def _expr_variables(expr: Expr) -> set[str]:
    if type(expr) is not Expr:
        raise ContractError("module expression 必须是 exact Expr")
    expr.validate()
    if expr.op == "var":
        return {str(expr.value)}
    out: set[str] = set()
    for arg in expr.args:
        out.update(_expr_variables(arg))
    return out


def _as_expr(value: Expr | Mapping[str, Any] | int | float) -> Expr:
    if type(value) is Expr:
        value.validate()
        return value
    if isinstance(value, Expr):
        raise ContractError("Expr 子类被禁止")
    return Expr.from_data(value)


def _canonical_domain_value(value: Any, domain: Sequence[float]) -> float:
    if isinstance(value, bool):
        number = float(int(value))
    elif isinstance(value, (int, float)) and isfinite(float(value)):
        number = float(value)
    else:
        raise ContractError(f"离散数值域不接受值 {value!r}")
    for candidate in domain:
        if abs(number - candidate) <= _DOMAIN_TOLERANCE:
            return float(candidate)
    raise ContractError(f"值 {number!r} 不在 domain={tuple(domain)!r}")


def _utc_text(value: str | datetime) -> str:
    parsed = parse_time(value)
    if parsed is None:  # pragma: no cover - non-optional caller contract
        raise ContractError("时间不得为空")
    return parsed.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class FiniteVariable:
    """A numeric finite-domain variable with an explicit epistemic/causal role."""

    name: str
    role: VariableRole | str
    domain: tuple[float, ...]
    concept: str | None = None
    default: float | None = None
    unit: str | None = None
    intervenable: bool = False

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name:
            raise ContractError("variable.name 不得为空")
        try:
            if type(self.role) is VariableRole:
                role = self.role
            elif type(self.role) is str:
                role = VariableRole(self.role)
            else:
                raise ContractError("variable.role 必须是 exact str/VariableRole")
        except ValueError as exc:
            raise ContractError(f"未知 variable role: {self.role!r}") from exc
        object.__setattr__(self, "role", role)
        if type(self.domain) is not tuple or not self.domain:
            raise ContractError(f"{self.name}: domain 不得为空")
        normalized: list[float] = []
        for item in self.domain:
            if type(item) not in {int, float} or not isfinite(float(item)):
                raise ContractError(f"{self.name}: domain 只能含有限数值")
            number = float(item)
            if any(abs(number - old) <= _DOMAIN_TOLERANCE for old in normalized):
                raise ContractError(f"{self.name}: domain 有重复值 {number}")
            normalized.append(number)
        object.__setattr__(self, "domain", tuple(normalized))
        if self.default is not None:
            object.__setattr__(self, "default", _canonical_domain_value(self.default, normalized))
        if role in {VariableRole.OBSERVATION, VariableRole.ACTION} and not self.concept:
            raise ContractError(f"{self.name}: observation/action variable 必须声明 concept")
        if self.concept is not None and (type(self.concept) is not str or not self.concept):
            raise ContractError(f"{self.name}: concept 必须是非空 exact str")
        if self.unit is not None and (type(self.unit) is not str or not self.unit):
            raise ContractError(f"{self.name}: unit 必须是非空 exact str")
        if type(self.intervenable) is not bool:
            raise ContractError(f"{self.name}: intervenable 必须是 exact bool")
        if role is VariableRole.ACTION and not self.intervenable:
            object.__setattr__(self, "intervenable", True)

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> "FiniteVariable":
        _strict_mapping(
            data,
            allowed={"name", "role", "domain", "concept", "default", "unit", "intervenable"},
            required={"name", "role", "domain"},
            label="variable",
        )
        domain = data["domain"]
        if type(domain) not in {list, tuple}:
            raise ContractError("variable.domain 必须是 list/tuple")
        intervenable = data.get("intervenable", False)
        if type(intervenable) is not bool:
            raise ContractError("variable.intervenable 必须是 exact bool")
        return cls(
            name=data["name"],
            role=data["role"],
            domain=tuple(domain),
            concept=data.get("concept"),
            default=data.get("default"),
            unit=data.get("unit"),
            intervenable=intervenable,
        )


@dataclass(frozen=True)
class ValueProbability:
    """One finite-domain mass whose probability is a closed ``Expr``."""

    value: float
    probability: Expr

    def __post_init__(self) -> None:
        if type(self.value) not in {int, float} or not isfinite(float(self.value)):
            raise ContractError("ValueProbability.value 必须是有限 exact number")
        if type(self.probability) is not Expr:
            raise ContractError("ValueProbability.probability 必须是 exact Expr")
        self.probability.validate()

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> "ValueProbability":
        _strict_mapping(
            data,
            allowed={"value", "probability"},
            required={"value", "probability"},
            label="probability mass",
        )
        if type(data["value"]) not in {int, float}:
            raise ContractError("probability mass.value 必须是 exact number")
        return cls(float(data["value"]), _as_expr(data["probability"]))


@dataclass(frozen=True)
class FiniteConditional:
    """A normalized conditional probability vector for one target variable."""

    target: str
    masses: tuple[ValueProbability, ...]

    def __post_init__(self) -> None:
        if type(self.target) is not str or not self.target or type(self.masses) is not tuple or not self.masses:
            raise ContractError("conditional.target/masses 不得为空")
        if not all(type(item) is ValueProbability for item in self.masses):
            raise ContractError("conditional.masses 必须全为 exact ValueProbability")

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> "FiniteConditional":
        _strict_mapping(
            data,
            allowed={"target", "masses"},
            required={"target", "masses"},
            label="conditional",
        )
        masses = data["masses"]
        if type(masses) not in {list, tuple}:
            raise ContractError("conditional.masses 必须是 list/tuple")
        if type(data["target"]) is not str:
            raise ContractError("conditional.target 必须是 exact str")
        return cls(data["target"], tuple(ValueProbability.from_data(item) for item in masses))


@dataclass(frozen=True)
class StructuralEquation:
    """A deterministic SCM equation in topological registration order."""

    target: str
    expression: Expr

    def __post_init__(self) -> None:
        if type(self.target) is not str or not self.target or type(self.expression) is not Expr:
            raise ContractError("structural equation 需要 exact target 和 Expr")
        self.expression.validate()

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> "StructuralEquation":
        _strict_mapping(
            data,
            allowed={"target", "expression"},
            required={"target", "expression"},
            label="structural equation",
        )
        if type(data["target"]) is not str:
            raise ContractError("structural equation.target 必须是 exact str")
        return cls(data["target"], _as_expr(data["expression"]))


def _validate_names_and_concepts(variables: Sequence[FiniteVariable]) -> None:
    names = [item.name for item in variables]
    if len(names) != len(set(names)):
        raise ContractError("variable.name 必须唯一")
    concepts = [item.concept for item in variables if item.concept]
    if len(concepts) != len(set(concepts)):
        raise ContractError("同一 module 内 concept 必须唯一")


def _validate_mass_domain(cpd: FiniteConditional, variable: FiniteVariable) -> None:
    actual = [_canonical_domain_value(item.value, variable.domain) for item in cpd.masses]
    if len(actual) != len(set(actual)) or set(actual) != set(variable.domain):
        raise ContractError(
            f"{cpd.target}: probability masses 必须恰好覆盖 domain {variable.domain}"
        )


def _evaluate_cpd(cpd: FiniteConditional, env: Mapping[str, float]) -> dict[float, float]:
    probabilities: dict[float, float] = {}
    for mass in cpd.masses:
        value = float(mass.value)
        probability = mass.probability.evaluate(env)
        if probability < -_PROBABILITY_TOLERANCE or probability > 1 + _PROBABILITY_TOLERANCE:
            raise ArithmeticError(f"{cpd.target}: probability {probability} outside [0,1]")
        probabilities[value] = min(1.0, max(0.0, probability))
    total = sum(probabilities.values())
    if abs(total - 1.0) > _PROBABILITY_TOLERANCE:
        raise ArithmeticError(f"{cpd.target}: probabilities sum to {total}, not 1")
    if total <= 0:
        raise ArithmeticError(f"{cpd.target}: zero probability mass")
    return {key: value / total for key, value in probabilities.items()}


@dataclass(frozen=True)
class DynamicModule:
    """Closed finite DBN module.

    Transition expressions may read only ``prev__<latent>`` and
    ``action__<action>``.  Emissions may read only ``state__<latent>`` and
    ``action__<action>``.  This prefix discipline prevents an observation from
    silently becoming latent state or an order from becoming a performed act.
    """

    module_id: str
    version: str
    variables: tuple[FiniteVariable, ...]
    initial: tuple[FiniteConditional, ...]
    transitions: tuple[FiniteConditional, ...]
    emissions: tuple[FiniteConditional, ...]
    step_hours: float = 1.0
    max_joint_states: int = 4096

    def __post_init__(self) -> None:
        if type(self.module_id) is not str or not self.module_id or type(self.version) is not str or not self.version:
            raise ContractError("dynamic module_id/version 不得为空")
        if type(self.variables) is not tuple or not all(type(item) is FiniteVariable for item in self.variables):
            raise ContractError("dynamic.variables 必须是 exact FiniteVariable tuple")
        for label, values in (("initial", self.initial), ("transitions", self.transitions), ("emissions", self.emissions)):
            if type(values) is not tuple or not all(type(item) is FiniteConditional for item in values):
                raise ContractError(f"dynamic.{label} 必须是 exact FiniteConditional tuple")
        if type(self.step_hours) not in {int, float} or self.step_hours <= 0 or not isfinite(float(self.step_hours)):
            raise ContractError("step_hours 必须是有限正数")
        if type(self.max_joint_states) is not int or self.max_joint_states < 1:
            raise ContractError("max_joint_states 必须为正整数")
        _validate_names_and_concepts(self.variables)
        roles = {item.role for item in self.variables}
        if not roles <= {VariableRole.LATENT, VariableRole.OBSERVATION, VariableRole.ACTION}:
            raise ContractError("DynamicModule 仅接受 latent/observation/action roles")
        latent = [item for item in self.variables if item.role is VariableRole.LATENT]
        observed = [item for item in self.variables if item.role is VariableRole.OBSERVATION]
        actions = [item for item in self.variables if item.role is VariableRole.ACTION]
        if not latent:
            raise ContractError("DynamicModule 至少需要一个 latent variable")
        state_count = prod(len(item.domain) for item in latent)
        if state_count > self.max_joint_states:
            raise ContractError(
                f"joint latent state count {state_count} 超过 max_joint_states={self.max_joint_states}"
            )
        by_name = {item.name: item for item in self.variables}
        for label, cpds, expected in (
            ("initial", self.initial, latent),
            ("transition", self.transitions, latent),
            ("emission", self.emissions, observed),
        ):
            targets = [item.target for item in cpds]
            wanted = [item.name for item in expected]
            if len(targets) != len(set(targets)) or set(targets) != set(wanted):
                raise ContractError(f"{label} targets 必须恰好为 {wanted}")
            for cpd in cpds:
                _validate_mass_domain(cpd, by_name[cpd.target])
        initial_allowed: set[str] = set()
        transition_allowed = {f"prev__{item.name}" for item in latent} | {
            f"action__{item.name}" for item in actions
        }
        emission_allowed = {f"state__{item.name}" for item in latent} | {
            f"action__{item.name}" for item in actions
        }
        for label, cpds, allowed in (
            ("initial", self.initial, initial_allowed),
            ("transition", self.transitions, transition_allowed),
            ("emission", self.emissions, emission_allowed),
        ):
            for cpd in cpds:
                for mass in cpd.masses:
                    unknown = _expr_variables(mass.probability) - allowed
                    if unknown:
                        raise ContractError(f"{label} {cpd.target} 引用了非法变量 {sorted(unknown)}")
        # Validate normalization for every reachable input row, not just one fixture.
        for cpd in self.initial:
            _evaluate_cpd(cpd, {})
        action_domains = [item.domain for item in actions]
        action_assignments = product(*action_domains) if action_domains else [()]
        action_rows = [dict(zip([item.name for item in actions], row)) for row in action_assignments]
        latent_domains = [item.domain for item in latent]
        for state_row in product(*latent_domains):
            state = dict(zip([item.name for item in latent], state_row))
            for action in action_rows:
                transition_env = {f"prev__{key}": value for key, value in state.items()}
                transition_env.update({f"action__{key}": value for key, value in action.items()})
                emission_env = {f"state__{key}": value for key, value in state.items()}
                emission_env.update({f"action__{key}": value for key, value in action.items()})
                for cpd in self.transitions:
                    _evaluate_cpd(cpd, transition_env)
                for cpd in self.emissions:
                    _evaluate_cpd(cpd, emission_env)

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> "DynamicModule":
        _strict_mapping(
            data,
            allowed={
                "kind",
                "module_id",
                "version",
                "variables",
                "initial",
                "transitions",
                "emissions",
                "step_hours",
                "max_joint_states",
            },
            required={"kind", "module_id", "version", "variables", "initial", "transitions", "emissions"},
            label="dynamic module",
        )
        if data["kind"] != "dynamic":
            raise ContractError("DynamicModule.kind 必须为 'dynamic'")
        for key in ("variables", "initial", "transitions", "emissions"):
            if type(data[key]) not in {list, tuple}:
                raise ContractError(f"dynamic.{key} 必须是 list/tuple")
        step_hours = data.get("step_hours", 1.0)
        max_joint_states = data.get("max_joint_states", 4096)
        if type(step_hours) not in {int, float}:
            raise ContractError("dynamic.step_hours 必须是 exact number")
        if type(max_joint_states) is not int:
            raise ContractError("dynamic.max_joint_states 必须是 exact int")
        return cls(
            module_id=data["module_id"],
            version=data["version"],
            variables=tuple(FiniteVariable.from_data(item) for item in data["variables"]),
            initial=tuple(FiniteConditional.from_data(item) for item in data["initial"]),
            transitions=tuple(FiniteConditional.from_data(item) for item in data["transitions"]),
            emissions=tuple(FiniteConditional.from_data(item) for item in data["emissions"]),
            step_hours=float(step_hours),
            max_joint_states=max_joint_states,
        )


@dataclass(frozen=True)
class FiniteSCMModule:
    """Closed finite acyclic SCM with exact abduction/action/prediction."""

    module_id: str
    version: str
    variables: tuple[FiniteVariable, ...]
    exogenous_distributions: tuple[FiniteConditional, ...]
    equations: tuple[StructuralEquation, ...]
    max_worlds: int = 4096

    def __post_init__(self) -> None:
        if type(self.module_id) is not str or not self.module_id or type(self.version) is not str or not self.version:
            raise ContractError("SCM module_id/version 不得为空")
        if type(self.variables) is not tuple or not all(type(item) is FiniteVariable for item in self.variables):
            raise ContractError("SCM.variables 必须是 exact FiniteVariable tuple")
        if type(self.exogenous_distributions) is not tuple or not all(
            type(item) is FiniteConditional for item in self.exogenous_distributions
        ):
            raise ContractError("SCM.exogenous_distributions 必须是 exact FiniteConditional tuple")
        if type(self.equations) is not tuple or not all(type(item) is StructuralEquation for item in self.equations):
            raise ContractError("SCM.equations 必须是 exact StructuralEquation tuple")
        if type(self.max_worlds) is not int or self.max_worlds < 1:
            raise ContractError("max_worlds 必须为正整数")
        _validate_names_and_concepts(self.variables)
        by_name = {item.name: item for item in self.variables}
        exogenous = [item for item in self.variables if item.role is VariableRole.EXOGENOUS]
        endogenous = [item for item in self.variables if item.role is not VariableRole.EXOGENOUS]
        if not exogenous or not endogenous:
            raise ContractError("FiniteSCMModule 同时需要 exogenous 与 endogenous variables")
        world_count = prod(len(item.domain) for item in exogenous)
        if world_count > self.max_worlds:
            raise ContractError(f"exogenous world count {world_count} 超过 max_worlds={self.max_worlds}")
        distribution_targets = [item.target for item in self.exogenous_distributions]
        if len(distribution_targets) != len(set(distribution_targets)) or set(distribution_targets) != {
            item.name for item in exogenous
        }:
            raise ContractError("exogenous_distributions 必须恰好覆盖所有 exogenous variables")
        for cpd in self.exogenous_distributions:
            variable = by_name.get(cpd.target)
            if variable is None or variable.role is not VariableRole.EXOGENOUS:
                raise ContractError(f"{cpd.target}: 不是 exogenous variable")
            _validate_mass_domain(cpd, variable)
            for mass in cpd.masses:
                if _expr_variables(mass.probability):
                    raise ContractError("原型 SCM 的 exogenous distributions 必须是常数独立质量")
            _evaluate_cpd(cpd, {})
        equation_targets = [item.target for item in self.equations]
        if len(equation_targets) != len(set(equation_targets)) or set(equation_targets) != {
            item.name for item in endogenous
        }:
            raise ContractError("equations 必须恰好覆盖所有 endogenous variables")
        available = {item.name for item in exogenous}
        for equation in self.equations:
            variable = by_name.get(equation.target)
            if variable is None or variable.role is VariableRole.EXOGENOUS:
                raise ContractError(f"{equation.target}: SCM equation target 非法")
            unknown = _expr_variables(equation.expression) - available
            if unknown:
                raise ContractError(
                    f"{equation.target}: equation 引用未来/未知变量 {sorted(unknown)}；equations 必须拓扑有序"
                )
            available.add(equation.target)
        # Enumerate all exogenous worlds once: domain errors are registration failures,
        # not silently deferred until a favorable test case.
        exo_names = [item.name for item in exogenous]
        for row in product(*(item.domain for item in exogenous)):
            env = dict(zip(exo_names, row))
            for equation in self.equations:
                value = equation.expression.evaluate(env)
                env[equation.target] = _canonical_domain_value(value, by_name[equation.target].domain)

    @classmethod
    def from_data(cls, data: Mapping[str, Any]) -> "FiniteSCMModule":
        _strict_mapping(
            data,
            allowed={
                "kind",
                "module_id",
                "version",
                "variables",
                "exogenous_distributions",
                "equations",
                "max_worlds",
            },
            required={"kind", "module_id", "version", "variables", "exogenous_distributions", "equations"},
            label="SCM module",
        )
        if data["kind"] != "finite_scm":
            raise ContractError("FiniteSCMModule.kind 必须为 'finite_scm'")
        for key in ("variables", "exogenous_distributions", "equations"):
            if type(data[key]) not in {list, tuple}:
                raise ContractError(f"SCM.{key} 必须是 list/tuple")
        max_worlds = data.get("max_worlds", 4096)
        if type(max_worlds) is not int:
            raise ContractError("SCM.max_worlds 必须是 exact int")
        return cls(
            module_id=data["module_id"],
            version=data["version"],
            variables=tuple(FiniteVariable.from_data(item) for item in data["variables"]),
            exogenous_distributions=tuple(
                FiniteConditional.from_data(item) for item in data["exogenous_distributions"]
            ),
            equations=tuple(StructuralEquation.from_data(item) for item in data["equations"]),
            max_worlds=max_worlds,
        )


@dataclass(frozen=True)
class _LedgerEvent:
    kind: str
    known_at: str
    artifact: SourceArtifact | None = None
    source_id: str | None = None


class _UnsupportedSemantic(Exception):
    pass


class _OutOfModel(Exception):
    pass


class _InsufficientEvidence(Exception):
    pass


class _ConflictingEvidence(Exception):
    pass


class CausalStateCandidate(ArchitectureCandidate):
    """Candidate B: exact finite dynamic/causal kernel."""

    CANDIDATE_ID = "candidate-b-dynamic-causal-state"
    VERSION = "0.2.0"
    SUPPORTED_KNOWLEDGE_VERSION = "knowledge-v1"

    def __init__(self, track: Track = Track.NATIVE) -> None:
        super().__init__(Track(track))
        self._modules: dict[str, DynamicModule | FiniteSCMModule] = {}
        self._artifacts: dict[str, SourceArtifact] = {}
        self._source_index: dict[str, str] = {}
        self._event_log: list[_LedgerEvent] = []
        self._results: dict[str, dict[str, Any]] = {}
        self._result_counter = 0

    @property
    def manifest(self) -> CandidateManifest:
        companion = self.track is Track.COMPANION
        declared = [
            QueryKind.PROJECT,
            QueryKind.CONDITION,
            QueryKind.FILTER,
            QueryKind.FORECAST,
            QueryKind.INTERVENE,
            QueryKind.COUNTERFACTUAL,
        ]
        if companion:
            declared.extend([QueryKind.REPLAY_AS_THEN, QueryKind.REINTERPRET_NOW])
        foreign: tuple[Mapping[str, Any], ...]
        if companion:
            foreign = (
                {
                    "boundary": "append_only_transaction_cut_adapter",
                    "semantic_family": "event_sourcing/bitemporal_transaction_cut",
                    "native": False,
                    "provides": ["recorded-time cut", "source tombstone", "evidence snapshot"],
                    "does_not_provide": [
                        "derivation lineage",
                        "source-independence proof",
                        "knowledge-version migration",
                        "full valid-time interval algebra",
                    ],
                },
            )
        else:
            foreign = (
                {
                    "boundary": "evidence_history",
                    "semantic_family": "not implemented natively",
                    "native": False,
                    "provides": [],
                    "does_not_provide": ["historical transaction cuts", "retraction", "derivation lineage"],
                },
            )
        return CandidateManifest(
            candidate_id=self.CANDIDATE_ID,
            version=self.VERSION,
            formal_signature=(
                "DBN: P(X0) product_t P(X_t|X_{t-1},A_t) P(Y_t|X_t,A_t)",
                "SCM: M=(U,V,F,P(U)); condition != do; CF=AAP(U_same)",
            ),
            execution_semantics=(
                "exact finite enumeration",
                "typed latent/observation/action roles",
                "closed Expr IR",
                "explicit coverage and numerical failure",
            ),
            companion_layers=("append-only transaction-cut adapter",) if companion else (),
            primitive_profile={
                "native_state": (
                    "finite variable",
                    "conditional probability factor",
                    "Bayes filter",
                    "Markov transition",
                ),
                "native_causal": (
                    "exogenous distribution",
                    "structural equation",
                    "do replacement",
                    "AAP shared-exogenous counterfactual",
                ),
                "foreign_companion": (
                    "append event",
                    "source tombstone",
                    "transaction-time cut",
                )
                if companion
                else (),
            },
            foreign_boundaries=foreign,
            declared_query_capabilities=tuple(declared),
            failure_types=(
                ResultStatus.UNSUPPORTED,
                ResultStatus.INSUFFICIENT,
                ResultStatus.CONFLICTING,
                ResultStatus.INVALID,
                ResultStatus.NUMERICAL_FAILURE,
                ResultStatus.OUT_OF_MODEL,
            ),
        )

    # ------------------------------------------------------------------
    # Public control-plane methods
    # ------------------------------------------------------------------
    def register_module(self, module: Any) -> CapabilityResult:
        try:
            parsed = self._parse_module(module)
            existing = self._modules.get(parsed.module_id)
            if existing is not None:
                if existing == parsed:
                    return self._record(
                        CapabilityResult(
                            status=ResultStatus.OK,
                            capability="native",
                            coverage_status="complete",
                            value_kind="module_registration",
                            value={"module_id": parsed.module_id, "idempotent": True},
                            native_witness={"closed_ir": True, "module_type": type(parsed).__name__},
                            versions={"candidate": self.VERSION, "module": parsed.version},
                        ),
                        operation="register_module",
                    )
                raise ContractError(f"module_id {parsed.module_id!r} 已注册为不同定义")
            self._modules[parsed.module_id] = parsed
            return self._record(
                CapabilityResult(
                    status=ResultStatus.OK,
                    capability="native",
                    coverage_status="complete",
                    value_kind="module_registration",
                    value={
                        "module_id": parsed.module_id,
                        "module_type": type(parsed).__name__,
                        "version": parsed.version,
                        "idempotent": False,
                    },
                    native_witness={
                        "closed_ir": True,
                        "callbacks_accepted": False,
                        "variable_roles": sorted({item.role.value for item in parsed.variables}),
                    },
                    versions={"candidate": self.VERSION, "module": parsed.version},
                ),
                operation="register_module",
            )
        except (ContractError, TypeError, ValueError) as exc:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.INVALID,
                    validation="invalid",
                    capability="native",
                    coverage_status="not_evaluated",
                    computation="not_started",
                    diagnostics={"error": str(exc), "accepted": ["DynamicModule", "FiniteSCMModule", "closed typed mapping"]},
                ),
                operation="register_module",
            )
        except ArithmeticError as exc:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.NUMERICAL_FAILURE,
                    capability="native",
                    coverage_status="not_evaluated",
                    computation="failed",
                    diagnostics={"error": str(exc), "phase": "module_validation"},
                ),
                operation="register_module",
            )

    def ingest(self, artifact: SourceArtifact) -> CapabilityResult:
        if type(artifact) is not SourceArtifact:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.INVALID,
                    validation="invalid",
                    capability="native",
                    coverage_status="not_evaluated",
                    diagnostics={"error": "ingest 只接受 SourceArtifact"},
                ),
                operation="ingest",
            )
        try:
            # Revalidate even exact instances: ``object.__new__`` can bypass a
            # dataclass constructor, and frozen nested dict/list fields remain
            # mutable.  No equality, hashing or copying occurs before this gate.
            SourceArtifact.validate(artifact)
        except (ContractError, TypeError, ValueError) as exc:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.INVALID,
                    validation="invalid",
                    capability="native",
                    coverage_status="not_evaluated",
                    computation="not_started",
                    diagnostics={"error": str(exc), "phase": "closed_input_validation"},
                ),
                operation="ingest",
            )
        existing = self._artifacts.get(artifact.artifact_id)
        if existing is not None:
            if existing == artifact:
                return self._record(
                    CapabilityResult(
                        status=ResultStatus.OK,
                        capability="native" if self.track is Track.NATIVE else "companion",
                        coverage_status="unchanged",
                        value_kind="ingest_receipt",
                        value={"artifact_id": artifact.artifact_id, "idempotent": True},
                        evidence_witness={"artifact_id": artifact.artifact_id},
                    ),
                    operation="ingest",
                )
            return self._record(
                CapabilityResult(
                    status=ResultStatus.CONFLICTING,
                    validation="invalid",
                    capability="native",
                    epistemic="conflicting",
                    coverage_status="not_evaluated",
                    diagnostics={"error": "同一 artifact_id 对应不同 payload", "artifact_id": artifact.artifact_id},
                ),
                operation="ingest",
            )
        prior_artifact_id = self._source_index.get(artifact.source_id)
        if prior_artifact_id is not None:
            prior = self._artifacts[prior_artifact_id]
            if self._artifact_semantic_identity(prior) == self._artifact_semantic_identity(artifact):
                return self._record(
                    CapabilityResult(
                        status=ResultStatus.OK,
                        capability="native" if self.track is Track.NATIVE else "companion",
                        coverage_status="unchanged",
                        value_kind="ingest_receipt",
                        value={
                            "artifact_id": prior.artifact_id,
                            "delivery_alias": artifact.artifact_id,
                            "source_id": artifact.source_id,
                            "idempotent": True,
                        },
                        evidence_witness={"artifact_id": prior.artifact_id, "source_id": artifact.source_id},
                        native_witness={"deduplicated_by": "stable_source_id"},
                    ),
                    operation="ingest",
                )
            return self._record(
                CapabilityResult(
                    status=ResultStatus.CONFLICTING,
                    validation="invalid",
                    capability="native",
                    epistemic="conflicting",
                    coverage_status="not_evaluated",
                    diagnostics={
                        "error": "同一 source_id 对应不同 immutable semantic payload；修订必须使用新 source_id/supersedes",
                        "source_id": artifact.source_id,
                        "existing_artifact_id": prior.artifact_id,
                        "incoming_artifact_id": artifact.artifact_id,
                    },
                ),
                operation="ingest",
            )
        stored = self._clone_artifact(artifact)
        self._artifacts[stored.artifact_id] = stored
        self._source_index[stored.source_id] = stored.artifact_id
        if self.track is Track.COMPANION:
            self._event_log.append(
                _LedgerEvent("ingest", _utc_text(stored.clocks.recorded_at), artifact=stored)
            )
        coverage = self._artifact_coverage(stored)
        mapped = bool(coverage["mapped_modules"])
        excluded = coverage["semantic_role_effect"] == "stored_but_not_evidence"
        status = ResultStatus.OK if mapped or excluded else ResultStatus.OUT_OF_MODEL
        return self._record(
            CapabilityResult(
                status=status,
                capability="native" if self.track is Track.NATIVE else "companion",
                epistemic="asserted" if mapped else "not_used",
                coverage_status="covered" if mapped else "out_of_model",
                value_kind="ingest_receipt",
                value={
                    "artifact_id": stored.artifact_id,
                    "idempotent": False,
                    "semantic_role": stored.semantic_role.value,
                    "mapped": mapped,
                },
                coverage=coverage,
                evidence_witness={"artifact_id": stored.artifact_id, "source_id": stored.source_id},
                native_witness={
                    "role_gate": coverage["semantic_role_effect"],
                    "lineage_claimed": False,
                },
                diagnostics={
                    "stored_for_future_module_registration": not mapped,
                    "transaction_cut_adapter": self.track is Track.COMPANION,
                },
            ),
            operation="ingest",
        )

    def retract(self, source_id: str, known_at: str) -> CapabilityResult:
        try:
            cut = _utc_text(known_at)
        except (ContractError, ValueError) as exc:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.INVALID,
                    validation="invalid",
                    capability="unsupported" if self.track is Track.NATIVE else "companion",
                    coverage_status="not_evaluated",
                    diagnostics={"error": str(exc)},
                ),
                operation="retract",
            )
        if self.track is Track.NATIVE:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.UNSUPPORTED,
                    capability="unsupported",
                    coverage_status="not_evaluated",
                    value_kind="none",
                    assumptions=["native DBN/SCM state has no transaction-time truth-maintenance semantics"],
                    diagnostics={
                        "unsupported_semantic": "source retraction",
                        "migration": "use Track.COMPANION and account append-only cut adapter",
                    },
                ),
                operation="retract",
            )
        cut_dt = parse_time(cut)
        matches = [
            item
            for item in self._artifacts.values()
            if item.source_id == source_id and parse_time(item.clocks.recorded_at) <= cut_dt
        ]
        if not matches:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.INSUFFICIENT,
                    capability="companion",
                    epistemic="insufficient",
                    coverage_status="no_matching_source",
                    diagnostics={"source_id": source_id, "known_at": cut, "matched": 0},
                ),
                operation="retract",
            )
        self._event_log.append(_LedgerEvent("retract", cut, source_id=source_id))
        return self._record(
            CapabilityResult(
                status=ResultStatus.OK,
                capability="companion",
                epistemic="retracted",
                coverage_status="covered",
                value_kind="retraction_receipt",
                value={"source_id": source_id, "known_at": cut, "matched": len(matches)},
                evidence_witness={"retracted_artifact_ids": sorted(item.artifact_id for item in matches)},
                native_witness={
                    "native_kernel_changed": False,
                    "foreign_adapter": "append_only_transaction_cut_adapter",
                },
            ),
            operation="retract",
        )

    def query(self, spec: QuerySpec) -> CapabilityResult:
        if type(spec) is not QuerySpec:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.INVALID,
                    validation="invalid",
                    capability="native",
                    coverage_status="not_evaluated",
                    diagnostics={"error": "query 只接受 QuerySpec"},
                ),
                operation="query",
            )
        try:
            QuerySpec.validate(spec)
        except (ContractError, TypeError, ValueError) as exc:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.INVALID,
                    validation="invalid",
                    capability="native",
                    coverage_status="not_evaluated",
                    computation="not_started",
                    diagnostics={"error": str(exc), "phase": "closed_query_validation"},
                ),
                operation="query",
            )
        try:
            self._validate_query_controls(spec)
            module, target = self._resolve_target(spec.target)
            if spec.model_version is not None and spec.model_version != module.version:
                raise _OutOfModel(
                    f"requested model_version={spec.model_version!r}, registered={module.version!r}"
                )
            artifacts, cut_witness = self._artifacts_for_query(spec)
            effective_kind = spec.kind
            replay_mode: str | None = None
            if spec.kind in {QueryKind.REPLAY_AS_THEN, QueryKind.REINTERPRET_NOW}:
                if self.track is Track.NATIVE:
                    raise _UnsupportedSemantic("native track 不支持历史 transaction cut")
                if spec.kind is QueryKind.REPLAY_AS_THEN:
                    if spec.model_version != module.version:
                        raise _UnsupportedSemantic(
                            "replay_as_then 需要显式 model_version 命中已注册不可变 module；知识库版本历史未实现"
                        )
                    replay_mode = "as_then_evidence_and_explicit_model_snapshot"
                else:
                    replay_mode = "historical_evidence_reinterpreted_by_current_registered_module"
                effective_kind = QueryKind.FILTER if isinstance(module, DynamicModule) else QueryKind.CONDITION

            if isinstance(module, DynamicModule):
                result = self._query_dynamic(module, target, spec, effective_kind, artifacts)
            else:
                result = self._query_scm(module, target, spec, effective_kind, artifacts)
            self._attest_consumed_query_controls(result, spec, module)
            result.time_cut.update(cut_witness)
            if replay_mode:
                result.time_cut["replay_mode"] = replay_mode
                result.capability = "companion"
                result.assumptions.append(
                    "transaction cut is companion semantics; inference witness remains native DBN/SCM"
                )
            return self._record(result, operation="query", query_id=spec.query_id)
        except _UnsupportedSemantic as exc:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.UNSUPPORTED,
                    capability="unsupported",
                    coverage_status="not_evaluated",
                    diagnostics={"error": str(exc), "query_kind": spec.kind.value},
                    versions={"candidate": self.VERSION},
                ),
                operation="query",
                query_id=spec.query_id,
            )
        except _OutOfModel as exc:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.OUT_OF_MODEL,
                    capability="native",
                    epistemic="out_of_model",
                    coverage_status="out_of_model",
                    identification="not_identified",
                    diagnostics={"error": str(exc), "target": spec.target},
                    versions={"candidate": self.VERSION},
                ),
                operation="query",
                query_id=spec.query_id,
            )
        except _ConflictingEvidence as exc:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.CONFLICTING,
                    capability="native",
                    epistemic="conflicting",
                    coverage_status="covered_but_conflicting",
                    identification="not_identified",
                    diagnostics={"error": str(exc)},
                    versions={"candidate": self.VERSION},
                ),
                operation="query",
                query_id=spec.query_id,
            )
        except _InsufficientEvidence as exc:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.INSUFFICIENT,
                    capability="native",
                    epistemic="insufficient",
                    coverage_status="insufficient",
                    identification="not_identified",
                    diagnostics={"error": str(exc)},
                    versions={"candidate": self.VERSION},
                ),
                operation="query",
                query_id=spec.query_id,
            )
        except (ArithmeticError, OverflowError, FloatingPointError) as exc:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.NUMERICAL_FAILURE,
                    capability="native",
                    epistemic="not_evaluated",
                    coverage_status="unknown",
                    identification="not_evaluated",
                    computation="failed",
                    diagnostics={"error": str(exc), "query_kind": spec.kind.value},
                    versions={"candidate": self.VERSION},
                ),
                operation="query",
                query_id=spec.query_id,
            )
        except (ContractError, TypeError, ValueError) as exc:
            return self._record(
                CapabilityResult(
                    status=ResultStatus.INVALID,
                    validation="invalid",
                    capability="native",
                    coverage_status="not_evaluated",
                    computation="not_started",
                    diagnostics={"error": str(exc), "query_kind": spec.kind.value},
                    versions={"candidate": self.VERSION},
                ),
                operation="query",
                query_id=spec.query_id,
            )

    def explain(self, result_id: str) -> CapabilityResult:
        stored = self._results.get(result_id)
        if stored is None:
            return CapabilityResult(
                status=ResultStatus.OUT_OF_MODEL,
                capability="native",
                epistemic="out_of_model",
                coverage_status="out_of_model",
                diagnostics={"error": f"未知 result_id {result_id!r}"},
            )
        return CapabilityResult(
            status=ResultStatus.OK,
            capability="native",
            epistemic="explanation_of_recorded_result",
            coverage_status="same_as_explained_result",
            value_kind="explanation",
            value=stored,
            assumptions=[
                "native witness is a factor/AAP execution trace, not source derivation lineage",
                "direct artifact ids do not prove source independence",
            ],
            native_witness={"result_id": result_id, "immutable_snapshot": True},
            versions={"candidate": self.VERSION},
        )

    def clean_rebuild(self) -> "CausalStateCandidate":
        rebuilt = type(self)(self.track)
        for module in self._modules.values():
            receipt = rebuilt.register_module(module)
            if receipt.status is not ResultStatus.OK:  # pragma: no cover - validated source modules
                raise RuntimeError(f"clean rebuild module failed: {receipt.to_dict()}")
        if self.track is Track.COMPANION:
            for event in self._event_log:
                if event.kind == "ingest" and event.artifact is not None:
                    rebuilt.ingest(event.artifact)
                elif event.kind == "retract" and event.source_id is not None:
                    rebuilt.retract(event.source_id, event.known_at)
        else:
            for artifact in self._artifacts.values():
                rebuilt.ingest(artifact)
        # Rebuild receipts are intentionally not copied: explanations are local
        # execution records, while modules/raw events are reconstructible inputs.
        rebuilt._results.clear()
        rebuilt._result_counter = 0
        return rebuilt

    # ------------------------------------------------------------------
    # Registration / target / evidence helpers
    # ------------------------------------------------------------------
    def _validate_query_controls(self, spec: QuerySpec) -> None:
        """Consume or reject every semantic control-plane selector.

        The finite prototype has one immutable knowledge-contract version.  It
        understands only the two task labels that disambiguate its causal
        operators and a small closed guarantee vocabulary.  Everything else is
        a typed unsupported request rather than ignored metadata.
        """

        if spec.knowledge_version != self.SUPPORTED_KNOWLEDGE_VERSION:
            raise _UnsupportedSemantic(
                f"knowledge_version {spec.knowledge_version!r} 不受支持；"
                f"仅支持 {self.SUPPORTED_KNOWLEDGE_VERSION!r}"
            )
        if spec.task is not None:
            supported_task = (
                (spec.kind is QueryKind.COUNTERFACTUAL and spec.task == "individual")
                or (spec.kind is QueryKind.INTERVENE and spec.task == "population")
            )
            if not supported_task:
                raise _UnsupportedSemantic(
                    f"query kind={spec.kind.value} 无法消费 task={spec.task!r}"
                )
        for guarantee in spec.requested_guarantees:
            if guarantee == "share_abduced_exogenous":
                if spec.kind is not QueryKind.COUNTERFACTUAL:
                    raise _UnsupportedSemantic(
                        "share_abduced_exogenous 仅适用于 counterfactual AAP"
                    )
            elif guarantee == "solver_diagnostics":
                # Both exact finite engines return normalization/world/state
                # diagnostics and surface numerical failure as a result axis.
                continue
            else:
                raise _UnsupportedSemantic(f"无法提供 requested_guarantee={guarantee!r}")

    def _attest_consumed_query_controls(
        self,
        result: CapabilityResult,
        spec: QuerySpec,
        module: DynamicModule | FiniteSCMModule,
    ) -> None:
        result.versions = dict(result.versions)
        result.versions["knowledge"] = spec.knowledge_version
        result.versions["requested_model"] = spec.model_version
        result.diagnostics = dict(result.diagnostics)
        result.diagnostics["query_controls_consumed"] = {
            "knowledge_version": spec.knowledge_version,
            "model_version": spec.model_version,
            "task": spec.task,
            "requested_guarantees": list(spec.requested_guarantees),
        }
        if "share_abduced_exogenous" in spec.requested_guarantees:
            if not isinstance(module, FiniteSCMModule) or not result.native_witness.get(
                "same_exogenous_unit_reused"
            ):
                raise ContractError("内部错误：未兑现 share_abduced_exogenous")
            result.diagnostics["guarantee_share_abduced_exogenous"] = "satisfied"
        if "solver_diagnostics" in spec.requested_guarantees:
            result.diagnostics["guarantee_solver_diagnostics"] = "satisfied"
        for assumption in spec.assumptions:
            marker = f"caller_declared_assumption:{assumption}"
            if marker not in result.assumptions:
                result.assumptions.append(marker)

    def _artifact_semantic_identity(self, artifact: SourceArtifact) -> dict[str, Any]:
        """Stable source delivery identity, intentionally excluding artifact_id."""

        return {
            "source_id": artifact.source_id,
            "semantic_role": artifact.semantic_role.value,
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
            "information_state": artifact.information_state.value,
            "value": artifact.value,
            "unit": artifact.unit,
            "method": artifact.method,
            "context": artifact.context,
            "reliability": artifact.reliability,
            "source_family": artifact.source_family,
            "supersedes": artifact.supersedes,
            "raw_payload": artifact.raw_payload,
            "mapping_version": artifact.mapping_version,
        }

    def _clone_artifact(self, artifact: SourceArtifact) -> SourceArtifact:
        """Copy only after SourceArtifact.validate proved an inert builtin graph."""

        return SourceArtifact(
            artifact_id=artifact.artifact_id,
            source_id=artifact.source_id,
            semantic_role=artifact.semantic_role,
            concept=artifact.concept,
            scope=artifact.scope,
            clocks=artifact.clocks,
            information_state=artifact.information_state,
            value=deepcopy(artifact.value),
            unit=artifact.unit,
            method=artifact.method,
            context=deepcopy(artifact.context),
            reliability=artifact.reliability,
            source_family=artifact.source_family,
            supersedes=artifact.supersedes,
            raw_payload=deepcopy(artifact.raw_payload),
            mapping_version=artifact.mapping_version,
        )

    def _parse_module(self, module: Any) -> DynamicModule | FiniteSCMModule:
        if type(module) is DynamicModule:
            DynamicModule.__post_init__(module)
            return module
        if type(module) is FiniteSCMModule:
            FiniteSCMModule.__post_init__(module)
            return module
        if isinstance(module, (DynamicModule, FiniteSCMModule)):
            raise ContractError("module dataclass 子类被禁止")
        if type(module) is not dict:
            raise ContractError("module 必须是 dataclass 或 closed typed mapping")
        validate_json_like(module, label="module")
        kind = dict.get(module, "kind")
        if kind == "dynamic":
            return DynamicModule.from_data(module)
        if kind == "finite_scm":
            return FiniteSCMModule.from_data(module)
        raise ContractError(f"未知 module kind: {kind!r}")

    def _resolve_target(
        self, target_text: str
    ) -> tuple[DynamicModule | FiniteSCMModule, FiniteVariable | None]:
        if not self._modules:
            raise _OutOfModel("尚未注册 module")
        explicit_module: str | None = None
        target = target_text
        if "::" in target_text:
            explicit_module, target = target_text.split("::", 1)
        else:
            for module_id in sorted(self._modules, key=len, reverse=True):
                prefix = module_id + "."
                if target_text.startswith(prefix):
                    explicit_module, target = module_id, target_text[len(prefix) :]
                    break
        if explicit_module is not None:
            module = self._modules.get(explicit_module)
            if module is None:
                raise _OutOfModel(f"未知 module {explicit_module!r}")
            if not target or target == "*":
                return module, None
            matches = [item for item in module.variables if item.name == target or item.concept == target]
            if not matches:
                raise _OutOfModel(f"module {explicit_module!r} 不含 target/concept {target!r}")
            return module, matches[0]
        if target_text in self._modules:
            return self._modules[target_text], None
        matches: list[tuple[DynamicModule | FiniteSCMModule, FiniteVariable]] = []
        for module in self._modules.values():
            for variable in module.variables:
                if variable.name == target_text or variable.concept == target_text:
                    matches.append((module, variable))
        if len(matches) == 1:
            return matches[0]
        if not matches:
            raise _OutOfModel(f"未建模 target/concept {target_text!r}")
        raise _OutOfModel(
            f"target {target_text!r} 在多个 modules 中歧义: {[item[0].module_id for item in matches]}；请用 module::target"
        )

    def _artifact_coverage(self, artifact: SourceArtifact) -> dict[str, Any]:
        observation_roles = {SemanticRole.RAW_OBSERVATION, SemanticRole.SUBJECT_STATEMENT}
        action_roles = {SemanticRole.PERFORMED_INTERVENTION, SemanticRole.STOPPED_INTERVENTION}
        if artifact.semantic_role in observation_roles:
            permitted_roles = {VariableRole.OBSERVATION, VariableRole.OUTCOME}
            role_effect = "observation_evidence"
        elif artifact.semantic_role in action_roles:
            permitted_roles = {VariableRole.ACTION}
            role_effect = "performed_action_evidence"
        else:
            permitted_roles = set()
            role_effect = "stored_but_not_evidence"
        mapped: list[dict[str, str]] = []
        wrong_role: list[dict[str, str]] = []
        for module in self._modules.values():
            for variable in module.variables:
                if variable.concept == artifact.concept:
                    item = {"module_id": module.module_id, "variable": variable.name, "role": variable.role.value}
                    if variable.role in permitted_roles:
                        mapped.append(item)
                    else:
                        wrong_role.append(item)
        return {
            "concept": artifact.concept,
            "mapped_modules": mapped,
            "same_concept_wrong_role": wrong_role,
            "semantic_role_effect": role_effect,
            "information_state": artifact.information_state.value,
        }

    def _artifacts_for_query(self, spec: QuerySpec) -> tuple[list[SourceArtifact], dict[str, Any]]:
        cut = parse_time(spec.as_known_at)
        if cut is None:  # pragma: no cover
            raise ContractError("as_known_at 不得为空")
        if self.track is Track.NATIVE:
            future_records = [
                item.artifact_id
                for item in self._artifacts.values()
                if parse_time(item.clocks.recorded_at) > cut
            ]
            if future_records:
                raise _UnsupportedSemantic(
                    "native track 无法重建过去 transaction cut；cut 后已有记录: " + ", ".join(sorted(future_records))
                )
            active = list(self._artifacts.values())
            adapter = "none"
        else:
            active = self._active_companion_cut(cut)
            adapter = "append_only_transaction_cut_adapter"
        available = [item for item in active if parse_time(item.clocks.available_at) <= cut]
        available = [item for item in available if item.scope.subject_id == spec.subject_id]
        # A missing valid-time selector is not an unbounded wildcard.  It means
        # "valid at the as-known cut".  Validity and expiry are half-open:
        # [effective_start, effective_end) intersect [effective_start, expires_at).
        valid = parse_time(spec.valid_at) if spec.valid_at is not None else cut
        assert valid is not None

        def valid_at_cut(item: SourceArtifact) -> bool:
            start = parse_time(item.clocks.effective_start)
            end = parse_time(item.clocks.effective_end)
            expires = parse_time(item.clocks.expires_at)
            assert start is not None
            return (
                start <= valid
                and (end is None or valid < end)
                and (expires is None or valid < expires)
            )

        available = [item for item in available if valid_at_cut(item)]
        return available, {
            "as_known_at": _utc_text(spec.as_known_at),
            "valid_at": _utc_text(valid),
            "valid_at_defaulted_to_as_known_at": spec.valid_at is None,
            "validity_interval": "[effective_start,effective_end) intersect [effective_start,expires_at)",
            "artifact_count": len(available),
            "adapter": adapter,
        }

    def _active_companion_cut(self, cut: datetime) -> list[SourceArtifact]:
        ingestion_events = [
            event
            for event in self._event_log
            if event.kind == "ingest" and event.artifact is not None and parse_time(event.known_at) <= cut
        ]
        retractions = [
            event
            for event in self._event_log
            if event.kind == "retract" and event.source_id is not None and parse_time(event.known_at) <= cut
        ]
        active: list[SourceArtifact] = []
        for event in ingestion_events:
            artifact = event.artifact
            assert artifact is not None
            artifact_recorded = parse_time(event.known_at)
            invalidated = any(
                tombstone.source_id == artifact.source_id
                and artifact_recorded <= parse_time(tombstone.known_at)
                for tombstone in retractions
            )
            if not invalidated:
                active.append(artifact)
        return active

    # ------------------------------------------------------------------
    # Dynamic DBN execution
    # ------------------------------------------------------------------
    def _query_dynamic(
        self,
        module: DynamicModule,
        target: FiniteVariable | None,
        spec: QuerySpec,
        kind: QueryKind,
        artifacts: list[SourceArtifact],
    ) -> CapabilityResult:
        if target is not None and target.role is not VariableRole.LATENT:
            raise _OutOfModel("dynamic query target 必须是 latent variable 或 module::* joint state")
        if kind not in {QueryKind.PROJECT, QueryKind.FILTER, QueryKind.FORECAST, QueryKind.INTERVENE}:
            if kind is QueryKind.COUNTERFACTUAL:
                raise _UnsupportedSemantic("DBN forecast 不等于同一患者 AAP counterfactual；请查询 FiniteSCMModule")
            raise _UnsupportedSemantic(f"DynamicModule 不原生支持 {kind.value}")
        posterior, trace, coverage, last_time = self._dynamic_filter(module, artifacts, spec.subject_id)
        semantics = "filter"
        horizon = 0.0
        override: dict[str, float] = {}
        if kind in {QueryKind.FORECAST, QueryKind.INTERVENE}:
            horizon = spec.horizon_hours if spec.horizon_hours is not None else module.step_hours
            if horizon < 0:
                raise ContractError("horizon_hours 不得为负")
            if spec.intervention:
                override = self._normalize_intervention(spec.intervention, module)
            steps = int(round(horizon / module.step_hours))
            if abs(steps * module.step_hours - horizon) > _DOMAIN_TOLERANCE:
                raise _OutOfModel(
                    f"horizon {horizon}h 不是 step_hours={module.step_hours} 的整数倍；原型不偷偷插值"
                )
            action_artifacts = self._module_action_artifacts(module, artifacts)
            forecast_start = last_time or parse_time(spec.valid_at or spec.as_known_at)
            for index in range(steps):
                transition_start = (
                    forecast_start + timedelta(hours=index * module.step_hours)
                    if forecast_start is not None
                    else None
                )
                action = self._actions_at(module, action_artifacts, transition_start, override)
                posterior = self._transition_once(module, posterior, action)
                trace.append(
                    {
                        "phase": "forecast",
                        "step": index + 1,
                        "elapsed_hours": (index + 1) * module.step_hours,
                        "transition_start": transition_start.isoformat().replace("+00:00", "Z")
                        if transition_start is not None
                        else None,
                        "action": action,
                        "posterior": self._serialize_dynamic_distribution(module, posterior, target),
                    }
                )
            semantics = "intervention_forecast" if override else "forecast"
        probability = self._serialize_dynamic_distribution(module, posterior, target)
        target_name = target.name if target is not None else "joint_latent_state"
        hypotheses = self._probability_to_hypotheses(target_name, probability)
        used_ids = coverage["used_artifact_ids"]
        complete = not coverage["gaps"]
        return CapabilityResult(
            status=ResultStatus.OK,
            capability="native",
            epistemic="posterior_distribution",
            coverage_status="complete" if complete else "partial",
            identification="identified_within_registered_finite_model",
            computation="exact_enumeration",
            value_kind="dynamic_posterior",
            value={
                "module_id": module.module_id,
                "query": kind.value,
                "query_semantics": semantics,
                "target": target_name,
                "probability": probability,
                "hypotheses": hypotheses,
                "claims": [
                    {
                        "kind": "posterior_or_predictive_distribution",
                        "target": target_name,
                        "conditioned_on_artifact_ids": used_ids,
                        "intervention": override,
                        "horizon_hours": horizon,
                    }
                ],
                "trajectory": trace,
                "diagnostics": {"exact": True, "finite_state_count": len(posterior)},
            },
            assumptions=[
                "registered first-order Markov/factorization assumptions hold",
                "used observation artifacts are conditionally independent given latent state",
                "direct artifact ids do not establish source independence",
            ]
            + (["no modeled observation used; result is prior/predictive only"] if not used_ids else []),
            coverage=coverage,
            evidence_witness={
                "direct_artifact_ids": used_ids,
                "direct_artifacts": self._artifact_scope_witness(used_ids),
                "lineage_graph": "not_native",
            },
            native_witness={
                "kernel": "finite_dbn",
                "factorization": "initial -> transition/action -> emission",
                "trace_steps": len(trace),
                "exact": True,
            },
            diagnostics={
                "unmodeled_evidence_count": len(coverage["gaps"]),
                "numerical_normalization_checked": True,
            },
            versions={"candidate": self.VERSION, "module": module.version},
        )

    def _dynamic_filter(
        self, module: DynamicModule, artifacts: list[SourceArtifact], subject_id: str
    ) -> tuple[
        dict[tuple[float, ...], float], list[dict[str, Any]], dict[str, Any], datetime | None
    ]:
        latent = self._variables(module, VariableRole.LATENT)
        posterior: dict[tuple[float, ...], float] = {}
        initial_by_target = {item.target: item for item in module.initial}
        for row in product(*(item.domain for item in latent)):
            probability = 1.0
            for variable, value in zip(latent, row):
                probability *= _evaluate_cpd(initial_by_target[variable.name], {})[value]
            if probability:
                posterior[tuple(row)] = probability
        posterior = self._normalize_weights(posterior, "initial distribution")
        observations, gaps = self._module_observations(module, artifacts)
        actions = self._module_action_artifacts(module, artifacts)
        by_time: dict[datetime, list[tuple[FiniteVariable, float, SourceArtifact]]] = {}
        for variable, value, artifact in observations:
            at = parse_time(artifact.clocks.effective_start)
            assert at is not None
            by_time.setdefault(at, []).append((variable, value, artifact))
        trace: list[dict[str, Any]] = []
        previous_time: datetime | None = None
        used: list[str] = []
        for at in sorted(by_time):
            transition_steps = 0
            if previous_time is not None:
                elapsed = (at - previous_time).total_seconds() / 3600.0
                transition_steps = int(round(elapsed / module.step_hours))
                if elapsed < -_DOMAIN_TOLERANCE:
                    raise ContractError("observation time order reversed")
                if abs(transition_steps * module.step_hours - elapsed) > _DOMAIN_TOLERANCE:
                    raise _OutOfModel(
                        f"irregular gap {elapsed}h 不可由 step_hours={module.step_hours} 精确表示"
                    )
                for step_index in range(transition_steps):
                    transition_start = previous_time + timedelta(
                        hours=step_index * module.step_hours
                    )
                    action = self._actions_at(module, actions, transition_start, {})
                    posterior = self._transition_once(module, posterior, action)
            action = self._actions_at(module, actions, at, {})
            weighted: dict[tuple[float, ...], float] = {}
            artifact_ids: list[str] = []
            for state_key, prior in posterior.items():
                state = dict(zip([item.name for item in latent], state_key))
                likelihood = 1.0
                for variable, observed_value, artifact in by_time[at]:
                    likelihood *= self._emission_probability(
                        module, variable, observed_value, state, action
                    )
                    artifact_ids.append(artifact.artifact_id)
                weighted[state_key] = prior * likelihood
            if sum(weighted.values()) <= _PROBABILITY_TOLERANCE:
                raise _InsufficientEvidence(
                    f"observations at {at.isoformat()} have zero likelihood under registered DynamicModule"
                )
            posterior = self._normalize_weights(weighted, f"observation update at {at.isoformat()}")
            unique_ids = sorted(set(artifact_ids))
            used.extend(unique_ids)
            trace.append(
                {
                    "phase": "filter",
                    "effective_at": at.isoformat().replace("+00:00", "Z"),
                    "transition_steps": transition_steps,
                    "artifact_ids": unique_ids,
                    "action": action,
                    "posterior": self._serialize_dynamic_distribution(module, posterior, None),
                }
            )
            previous_time = at
        coverage = {
            "modeled_observation_concepts": sorted(
                item.concept for item in self._variables(module, VariableRole.OBSERVATION) if item.concept
            ),
            "used_artifact_ids": sorted(set(used)),
            "gaps": gaps,
            "used_count": len(set(used)),
            "gap_count": len(gaps),
        }
        return posterior, trace, coverage, previous_time

    def _transition_once(
        self,
        module: DynamicModule,
        posterior: Mapping[tuple[float, ...], float],
        action: Mapping[str, float],
    ) -> dict[tuple[float, ...], float]:
        latent = self._variables(module, VariableRole.LATENT)
        cpds = {item.target: item for item in module.transitions}
        next_weights: dict[tuple[float, ...], float] = {}
        for previous_key, previous_probability in posterior.items():
            previous = dict(zip([item.name for item in latent], previous_key))
            env = {f"prev__{key}": value for key, value in previous.items()}
            env.update({f"action__{key}": value for key, value in action.items()})
            rows = [_evaluate_cpd(cpds[item.name], env) for item in latent]
            for next_key in product(*(item.domain for item in latent)):
                probability = previous_probability
                for value, row in zip(next_key, rows):
                    probability *= row[value]
                if probability:
                    next_weights[tuple(next_key)] = next_weights.get(tuple(next_key), 0.0) + probability
        return self._normalize_weights(next_weights, "transition")

    def _emission_probability(
        self,
        module: DynamicModule,
        variable: FiniteVariable,
        observed_value: float,
        state: Mapping[str, float],
        action: Mapping[str, float],
    ) -> float:
        cpd = next(item for item in module.emissions if item.target == variable.name)
        env = {f"state__{key}": value for key, value in state.items()}
        env.update({f"action__{key}": value for key, value in action.items()})
        return _evaluate_cpd(cpd, env)[observed_value]

    def _module_observations(
        self, module: DynamicModule, artifacts: list[SourceArtifact]
    ) -> tuple[list[tuple[FiniteVariable, float, SourceArtifact]], list[dict[str, Any]]]:
        concept_map = {
            item.concept: item for item in self._variables(module, VariableRole.OBSERVATION) if item.concept
        }
        used: list[tuple[FiniteVariable, float, SourceArtifact]] = []
        gaps: list[dict[str, Any]] = []
        seen_dependency: dict[tuple[str, str, str], tuple[float, str]] = {}
        for artifact in artifacts:
            if artifact.semantic_role not in {SemanticRole.RAW_OBSERVATION, SemanticRole.SUBJECT_STATEMENT}:
                continue
            variable = concept_map.get(artifact.concept)
            if variable is None:
                gaps.append(
                    {"artifact_id": artifact.artifact_id, "concept": artifact.concept, "reason": "unmodeled_concept"}
                )
                continue
            try:
                value = self._artifact_value(artifact, variable)
            except ContractError as exc:
                gaps.append(
                    {"artifact_id": artifact.artifact_id, "concept": artifact.concept, "reason": str(exc)}
                )
                continue
            dependency = artifact.source_family or artifact.source_id
            dependency_key = (
                variable.name,
                _utc_text(artifact.clocks.effective_start),
                dependency,
            )
            prior = seen_dependency.get(dependency_key)
            if prior is not None:
                if abs(prior[0] - value) > _DOMAIN_TOLERANCE:
                    raise _ConflictingEvidence(
                        f"dependent observations conflict for {variable.name}: "
                        f"{prior[1]}={prior[0]} vs {artifact.artifact_id}={value}"
                    )
                gaps.append(
                    {
                        "artifact_id": artifact.artifact_id,
                        "concept": artifact.concept,
                        "reason": "dependent_duplicate_excluded",
                        "same_dependency_as": prior[1],
                    }
                )
                continue
            seen_dependency[dependency_key] = (value, artifact.artifact_id)
            used.append((variable, value, artifact))
        return used, gaps

    def _module_action_artifacts(
        self, module: DynamicModule | FiniteSCMModule, artifacts: list[SourceArtifact]
    ) -> list[tuple[FiniteVariable, SourceArtifact]]:
        concept_map = {
            item.concept: item for item in self._variables(module, VariableRole.ACTION) if item.concept
        }
        out: list[tuple[FiniteVariable, SourceArtifact]] = []
        for artifact in artifacts:
            if artifact.semantic_role not in {
                SemanticRole.PERFORMED_INTERVENTION,
                SemanticRole.STOPPED_INTERVENTION,
            }:
                continue
            variable = concept_map.get(artifact.concept)
            if variable is not None:
                out.append((variable, artifact))
        self._assert_action_events_consistent(out)
        return out

    def _scope_key(self, artifact: SourceArtifact) -> tuple[str | None, ...]:
        scope = artifact.scope
        return (
            scope.subject_id,
            scope.encounter_id,
            scope.specimen_id,
            scope.device_id,
            scope.site_id,
            scope.body_site,
        )

    def _assert_action_events_consistent(
        self, artifacts: list[tuple[FiniteVariable, SourceArtifact]]
    ) -> None:
        """Reject order-dependent same-target assignments at one typed instant."""

        seen: dict[
            tuple[str, tuple[str | None, ...], str],
            tuple[float, SemanticRole, str],
        ] = {}
        for variable, artifact in artifacts:
            if artifact.semantic_role is SemanticRole.STOPPED_INTERVENTION:
                value = variable.default if variable.default is not None else variable.domain[0]
            else:
                value = self._artifact_value(artifact, variable)
            key = (
                variable.name,
                self._scope_key(artifact),
                _utc_text(artifact.clocks.effective_start),
            )
            prior = seen.get(key)
            if prior is not None and (
                abs(prior[0] - value) > _DOMAIN_TOLERANCE
                or prior[1] is not artifact.semantic_role
            ):
                raise _ConflictingEvidence(
                    f"performed action 同 scope/time/target 冲突: {variable.name} at {key[2]} "
                    f"{prior[0]} ({prior[2]}) vs {value} ({artifact.artifact_id}); "
                    "拒绝顺序 last-write"
                )
            seen[key] = (value, artifact.semantic_role, artifact.artifact_id)

    def _actions_at(
        self,
        module: DynamicModule,
        artifacts: list[tuple[FiniteVariable, SourceArtifact]],
        at: datetime | None,
        override: Mapping[str, float],
    ) -> dict[str, float]:
        actions = self._variables(module, VariableRole.ACTION)
        values: dict[str, float] = {}
        for variable in actions:
            default = variable.default if variable.default is not None else variable.domain[0]
            values[variable.name] = default
        ordered = sorted(artifacts, key=lambda item: parse_time(item[1].clocks.effective_start))
        for variable, artifact in ordered:
            effective = parse_time(artifact.clocks.effective_start)
            if at is not None and effective is not None and effective > at:
                continue
            if artifact.semantic_role is SemanticRole.STOPPED_INTERVENTION:
                values[variable.name] = variable.default if variable.default is not None else variable.domain[0]
            else:
                effective_end = parse_time(artifact.clocks.effective_end)
                if at is not None and effective_end is not None and at >= effective_end:
                    values[variable.name] = (
                        variable.default if variable.default is not None else variable.domain[0]
                    )
                else:
                    values[variable.name] = self._artifact_value(artifact, variable)
        values.update(override)
        return values

    def _serialize_dynamic_distribution(
        self,
        module: DynamicModule,
        distribution: Mapping[tuple[float, ...], float],
        target: FiniteVariable | None,
    ) -> list[dict[str, Any]]:
        latent = self._variables(module, VariableRole.LATENT)
        if target is not None:
            index = [item.name for item in latent].index(target.name)
            marginal = {value: 0.0 for value in target.domain}
            for key, probability in distribution.items():
                marginal[key[index]] += probability
            return [
                {"value": value, "probability": marginal[value]}
                for value in target.domain
            ]
        return [
            {
                "state": dict(zip([item.name for item in latent], key)),
                "probability": probability,
            }
            for key, probability in sorted(distribution.items())
        ]

    # ------------------------------------------------------------------
    # Finite SCM execution
    # ------------------------------------------------------------------
    def _query_scm(
        self,
        module: FiniteSCMModule,
        target: FiniteVariable | None,
        spec: QuerySpec,
        kind: QueryKind,
        artifacts: list[SourceArtifact],
    ) -> CapabilityResult:
        if target is None:
            raise ContractError("SCM query 必须指定 module::target")
        if target.role is VariableRole.EXOGENOUS:
            raise _OutOfModel("SCM query 不暴露 exogenous unit identity；只输出 endogenous target")
        if kind not in {
            QueryKind.PROJECT,
            QueryKind.CONDITION,
            QueryKind.INTERVENE,
            QueryKind.COUNTERFACTUAL,
        }:
            raise _UnsupportedSemantic(f"FiniteSCMModule 不原生支持 {kind.value}")
        evidence, gaps = self._scm_evidence(module, artifacts)
        conflict = self._evidence_conflict(evidence)
        if conflict:
            raise _ConflictingEvidence(conflict)
        intervention = self._normalize_intervention(spec.intervention or {}, module)
        factual_worlds = self._enumerate_scm_worlds(module, {})
        used_ids: list[str] = []
        factual_posterior = factual_worlds
        if kind in {QueryKind.PROJECT, QueryKind.CONDITION, QueryKind.COUNTERFACTUAL}:
            factual_posterior, used_ids = self._condition_worlds(factual_worlds, evidence)
        if kind in {QueryKind.PROJECT, QueryKind.CONDITION}:
            output_worlds = factual_posterior
            semantics = "observational_conditioning"
            operator = "P(target | observed evidence)"
        elif kind is QueryKind.INTERVENE:
            output_worlds = self._enumerate_scm_worlds(module, intervention)
            semantics = "population_do_intervention"
            operator = "P(target | do(intervention))"
            used_ids = []
        else:
            # Abduction uses posterior U from the factual evidence.  Action replaces
            # structural equations, and prediction reuses the *same* U per unit.
            output_worlds = []
            for weight, exogenous, factual in factual_posterior:
                counterfactual = self._solve_scm(module, exogenous, intervention)
                output_worlds.append((weight, exogenous, counterfactual))
            output_worlds = self._normalize_worlds(output_worlds, "counterfactual prediction")
            semantics = "same_patient_abduction_action_prediction"
            operator = "P(target_do | factual evidence; same U)"
        probability = self._world_marginal(output_worlds, target)
        factual_probability = (
            self._world_marginal(factual_posterior, target) if kind is QueryKind.COUNTERFACTUAL else None
        )
        complete = not gaps
        value: dict[str, Any] = {
            "module_id": module.module_id,
            "query": kind.value,
            "query_semantics": semantics,
            "target": target.name,
            "probability": probability,
            "hypotheses": self._probability_to_hypotheses(target.name, probability),
            "claims": [
                {
                    "kind": "causal_distribution" if kind in {QueryKind.INTERVENE, QueryKind.COUNTERFACTUAL} else "observational_distribution",
                    "operator": operator,
                    "target": target.name,
                    "intervention": intervention,
                    "conditioned_on_artifact_ids": used_ids,
                }
            ],
            "trajectory": [],
            "diagnostics": {"exact": True, "finite_worlds": len(output_worlds)},
        }
        if factual_probability is not None:
            value["factual_probability"] = factual_probability
        return CapabilityResult(
            status=ResultStatus.OK,
            capability="native",
            epistemic="posterior_distribution",
            coverage_status="complete" if complete else "partial",
            identification="identified_by_registered_scm_assumptions",
            computation="exact_enumeration",
            value_kind="causal_distribution",
            value=value,
            assumptions=[
                "registered structural equations and exogenous distribution are causally adequate",
                "exogenous variables are mutually independent as declared by the finite product measure",
                "identification is model-relative; registration does not prove assumptions from data",
            ],
            coverage={
                "used_artifact_ids": used_ids,
                "gaps": gaps,
                "used_count": len(used_ids),
                "gap_count": len(gaps),
            },
            evidence_witness={
                "direct_artifact_ids": used_ids,
                "direct_artifacts": self._artifact_scope_witness(used_ids),
                "lineage_graph": "not_native",
            },
            native_witness={
                "kernel": "finite_acyclic_scm",
                "steps": ["abduction", "action", "prediction"]
                if kind is QueryKind.COUNTERFACTUAL
                else (["equation_replacement", "prediction"] if kind is QueryKind.INTERVENE else ["conditioning"]),
                "same_exogenous_unit_reused": kind is QueryKind.COUNTERFACTUAL,
                "conditioning_is_do": False,
            },
            diagnostics={
                "population_do_ignores_factual_evidence": kind is QueryKind.INTERVENE,
                "numerical_normalization_checked": True,
            },
            versions={"candidate": self.VERSION, "module": module.version},
        )

    def _enumerate_scm_worlds(
        self, module: FiniteSCMModule, intervention: Mapping[str, float]
    ) -> list[tuple[float, dict[str, float], dict[str, float]]]:
        exogenous = self._variables(module, VariableRole.EXOGENOUS)
        distributions = {item.target: _evaluate_cpd(item, {}) for item in module.exogenous_distributions}
        worlds: list[tuple[float, dict[str, float], dict[str, float]]] = []
        for row in product(*(item.domain for item in exogenous)):
            exo = dict(zip([item.name for item in exogenous], row))
            probability = prod(distributions[item.name][exo[item.name]] for item in exogenous)
            if probability:
                worlds.append((probability, exo, self._solve_scm(module, exo, intervention)))
        return self._normalize_worlds(worlds, "SCM prior")

    def _solve_scm(
        self,
        module: FiniteSCMModule,
        exogenous: Mapping[str, float],
        intervention: Mapping[str, float],
    ) -> dict[str, float]:
        by_name = {item.name: item for item in module.variables}
        env = dict(exogenous)
        world: dict[str, float] = dict(exogenous)
        for equation in module.equations:
            if equation.target in intervention:
                value = intervention[equation.target]
            else:
                value = equation.expression.evaluate(env)
            canonical = _canonical_domain_value(value, by_name[equation.target].domain)
            env[equation.target] = canonical
            world[equation.target] = canonical
        return world

    def _scm_evidence(
        self, module: FiniteSCMModule, artifacts: list[SourceArtifact]
    ) -> tuple[list[tuple[FiniteVariable, float, SourceArtifact]], list[dict[str, Any]]]:
        concept_map = {
            item.concept: item
            for item in module.variables
            if item.concept and item.role in {VariableRole.OBSERVATION, VariableRole.ACTION, VariableRole.OUTCOME}
        }
        evidence: list[tuple[FiniteVariable, float, SourceArtifact]] = []
        gaps: list[dict[str, Any]] = []
        for artifact in artifacts:
            allowed = False
            if artifact.semantic_role in {SemanticRole.RAW_OBSERVATION, SemanticRole.SUBJECT_STATEMENT}:
                allowed_roles = {VariableRole.OBSERVATION, VariableRole.OUTCOME}
                allowed = True
            elif artifact.semantic_role in {
                SemanticRole.PERFORMED_INTERVENTION,
                SemanticRole.STOPPED_INTERVENTION,
            }:
                allowed_roles = {VariableRole.ACTION}
                allowed = True
            else:
                continue
            variable = concept_map.get(artifact.concept)
            if variable is None:
                gaps.append(
                    {"artifact_id": artifact.artifact_id, "concept": artifact.concept, "reason": "unmodeled_concept"}
                )
                continue
            if variable.role not in allowed_roles:
                gaps.append(
                    {
                        "artifact_id": artifact.artifact_id,
                        "concept": artifact.concept,
                        "reason": f"semantic_role {artifact.semantic_role.value} cannot populate {variable.role.value}",
                    }
                )
                continue
            try:
                if artifact.semantic_role is SemanticRole.STOPPED_INTERVENTION:
                    value = variable.default if variable.default is not None else variable.domain[0]
                else:
                    value = self._artifact_value(artifact, variable)
            except ContractError as exc:
                gaps.append(
                    {"artifact_id": artifact.artifact_id, "concept": artifact.concept, "reason": str(exc)}
                )
                continue
            evidence.append((variable, value, artifact))
        return evidence, gaps

    def _evidence_conflict(
        self, evidence: list[tuple[FiniteVariable, float, SourceArtifact]]
    ) -> str | None:
        # Same variable at the same effective instant with different exact finite
        # values is an explicit contradiction.  Different times are not collapsed.
        seen: dict[tuple[str, str, tuple[str | None, ...]], tuple[float, str, SemanticRole]] = {}
        for variable, value, artifact in evidence:
            key = (
                variable.name,
                _utc_text(artifact.clocks.effective_start),
                self._scope_key(artifact),
            )
            old = seen.get(key)
            if old is not None and abs(old[0] - value) > _DOMAIN_TOLERANCE:
                prefix = (
                    "performed action 同 scope/time/target 冲突（拒绝顺序 last-write）"
                    if artifact.semantic_role
                    in {SemanticRole.PERFORMED_INTERVENTION, SemanticRole.STOPPED_INTERVENTION}
                    or old[2]
                    in {SemanticRole.PERFORMED_INTERVENTION, SemanticRole.STOPPED_INTERVENTION}
                    else f"{variable.name} 在 {key[1]} 冲突"
                )
                return (
                    f"{prefix}: {old[0]} ({old[1]}) vs "
                    f"{value} ({artifact.artifact_id})"
                )
            if old is not None and old[2] is not artifact.semantic_role and (
                artifact.semantic_role
                in {SemanticRole.PERFORMED_INTERVENTION, SemanticRole.STOPPED_INTERVENTION}
                or old[2]
                in {SemanticRole.PERFORMED_INTERVENTION, SemanticRole.STOPPED_INTERVENTION}
            ):
                return (
                    "performed action 同 scope/time/target 阶段冲突（拒绝顺序 last-write）: "
                    f"{old[2].value} ({old[1]}) vs {artifact.semantic_role.value} "
                    f"({artifact.artifact_id})"
                )
            seen[key] = (value, artifact.artifact_id, artifact.semantic_role)
        return None

    def _condition_worlds(
        self,
        worlds: list[tuple[float, dict[str, float], dict[str, float]]],
        evidence: list[tuple[FiniteVariable, float, SourceArtifact]],
    ) -> tuple[list[tuple[float, dict[str, float], dict[str, float]]], list[str]]:
        if not evidence:
            return worlds, []
        surviving: list[tuple[float, dict[str, float], dict[str, float]]] = []
        for weight, exogenous, world in worlds:
            if all(abs(world[variable.name] - value) <= _DOMAIN_TOLERANCE for variable, value, _ in evidence):
                surviving.append((weight, exogenous, world))
        if not surviving:
            raise _InsufficientEvidence("factual evidence has zero probability under registered SCM")
        return self._normalize_worlds(surviving, "SCM conditioning"), sorted(
            {artifact.artifact_id for _, _, artifact in evidence}
        )

    def _world_marginal(
        self,
        worlds: list[tuple[float, dict[str, float], dict[str, float]]],
        target: FiniteVariable,
    ) -> list[dict[str, float]]:
        masses = {value: 0.0 for value in target.domain}
        for weight, _, world in worlds:
            masses[world[target.name]] += weight
        return [{"value": value, "probability": masses[value]} for value in target.domain]

    # ------------------------------------------------------------------
    # Generic numeric / value helpers
    # ------------------------------------------------------------------
    def _variables(
        self, module: DynamicModule | FiniteSCMModule, role: VariableRole
    ) -> list[FiniteVariable]:
        return [item for item in module.variables if item.role is role]

    def _artifact_value(self, artifact: SourceArtifact, variable: FiniteVariable) -> float:
        if variable.unit is not None:
            if artifact.unit is None:
                raise _OutOfModel(
                    f"unit_unknown:model variable {variable.name} requires {variable.unit!r}"
                )
            if variable.unit != artifact.unit:
                raise _OutOfModel(f"unit_mismatch:{artifact.unit}->{variable.unit}")
        if artifact.information_state is InfoState.PRESENT:
            return _canonical_domain_value(artifact.value, variable.domain)
        if artifact.information_state is InfoState.ABSENT and 0.0 in variable.domain:
            return 0.0
        raise ContractError(f"information_state_{artifact.information_state.value}_not_numeric_evidence")

    def _artifact_scope_witness(self, artifact_ids: Iterable[str]) -> list[dict[str, Any]]:
        """Preserve identities without claiming a native provenance algebra."""

        rows: list[dict[str, Any]] = []
        for artifact_id in sorted(set(artifact_ids)):
            artifact = self._artifacts.get(artifact_id)
            if artifact is None:
                continue
            rows.append(
                {
                    "artifact_id": artifact.artifact_id,
                    "source_id": artifact.source_id,
                    "source_family": artifact.source_family,
                    "scope": asdict(artifact.scope),
                    "effective_start": artifact.clocks.effective_start,
                    "available_at": artifact.clocks.available_at,
                    "recorded_at": artifact.clocks.recorded_at,
                }
            )
        return rows

    def _normalize_intervention(
        self,
        raw: Mapping[str, Any],
        module: DynamicModule | FiniteSCMModule,
    ) -> dict[str, float]:
        if not raw:
            return {}
        payload: Any = raw
        if "set" in raw:
            if set(raw) != {"set"}:
                raise ContractError("intervention 使用 set wrapper 时不得有其他字段")
            payload = raw["set"]
        elif "do" in raw:
            if set(raw) != {"do"}:
                raise ContractError("intervention 使用 do wrapper 时不得有其他字段")
            payload = raw["do"]
        elif module.module_id in raw:
            if set(raw) != {module.module_id}:
                raise ContractError("module wrapper intervention 不得混入其他字段")
            payload = raw[module.module_id]
        if not isinstance(payload, Mapping):
            raise ContractError("intervention payload 必须是 mapping")
        by_name = {item.name: item for item in module.variables}
        out: dict[str, float] = {}
        for name, value in payload.items():
            variable = by_name.get(str(name))
            if variable is None:
                raise _OutOfModel(f"intervention target {name!r} 未建模")
            if isinstance(module, DynamicModule) and variable.role is not VariableRole.ACTION:
                raise ContractError(
                    f"DynamicModule intervention 只能设置 action variable，不能直接改 {variable.role.value}"
                )
            if not variable.intervenable:
                raise ContractError(f"variable {name!r} 未声明 intervenable")
            out[variable.name] = _canonical_domain_value(value, variable.domain)
        return out

    def _normalize_weights(
        self, weights: Mapping[tuple[float, ...], float], label: str
    ) -> dict[tuple[float, ...], float]:
        if any((not isfinite(value) or value < 0) for value in weights.values()):
            raise ArithmeticError(f"{label}: non-finite/negative weight")
        total = sum(weights.values())
        if not isfinite(total) or total <= _PROBABILITY_TOLERANCE:
            raise ArithmeticError(f"{label}: zero/non-finite normalizer")
        return {key: value / total for key, value in weights.items() if value > 0}

    def _normalize_worlds(
        self,
        worlds: list[tuple[float, dict[str, float], dict[str, float]]],
        label: str,
    ) -> list[tuple[float, dict[str, float], dict[str, float]]]:
        if any((not isfinite(item[0]) or item[0] < 0) for item in worlds):
            raise ArithmeticError(f"{label}: non-finite/negative world weight")
        total = sum(item[0] for item in worlds)
        if not isfinite(total) or total <= _PROBABILITY_TOLERANCE:
            raise ArithmeticError(f"{label}: zero/non-finite normalizer")
        return [(weight / total, exogenous, world) for weight, exogenous, world in worlds if weight > 0]

    def _probability_to_hypotheses(
        self, target: str, probability: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        hypotheses: list[dict[str, Any]] = []
        for row in probability:
            assignment = row.get("state") if "state" in row else {target: row.get("value")}
            hypotheses.append({"assignment": assignment, "probability": row["probability"]})
        return hypotheses

    def _record(
        self,
        result: CapabilityResult,
        *,
        operation: str,
        query_id: str | None = None,
    ) -> CapabilityResult:
        self._result_counter += 1
        result_id = f"causal-state-{self._result_counter:06d}"
        result.diagnostics = dict(result.diagnostics)
        result.diagnostics["result_id"] = result_id
        if query_id is not None:
            result.diagnostics["query_id"] = query_id
        snapshot = result.to_dict()
        self._results[result_id] = {
            "result_id": result_id,
            "operation": operation,
            "query_id": query_id,
            "track": self.track.value,
            "result": snapshot,
            "explanation_boundary": {
                "native": "factor execution trace / SCM AAP trace",
                "not_native": "derivation lineage and source-independence proof",
            },
        }
        return result


# Stable import aliases for the shared runner without hiding the concrete family.
DynamicCausalStateCandidate = CausalStateCandidate
Candidate = CausalStateCandidate


def build_candidate(track: Track = Track.NATIVE) -> CausalStateCandidate:
    """Return a fresh candidate with no hidden process-global state."""

    return CausalStateCandidate(track)


__all__ = [
    "Candidate",
    "CausalStateCandidate",
    "DynamicCausalStateCandidate",
    "DynamicModule",
    "FiniteConditional",
    "FiniteSCMModule",
    "FiniteVariable",
    "StructuralEquation",
    "ValueProbability",
    "VariableRole",
    "build_candidate",
]
