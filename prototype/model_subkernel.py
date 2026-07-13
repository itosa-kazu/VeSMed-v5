"""Closed experimental-model execution subkernel.

This module is deliberately *not* a universal patient-state model.  It is a
small, candidate-neutral executable boundary for the public mathematical
models used by the architecture experiment panel.  Registration accepts only
one of eight closed schemas, parses the few equation strings with whitelisted
grammars, and never evaluates Python or foreign callbacks.

The implementation dispatches solely on ``model_kind`` plus the public model
parameters and the typed :class:`~prototype.contract.QuerySpec`.  Benchmark
identifiers and runner-side judging data are neither required nor accepted.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Mapping, Sequence

from .contract import (
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
)


SUBKERNEL_VERSION = "experimental-model-subkernel-v1"
MODEL_SCHEMA_VERSION = "public-math-model/1"
INTEGRATOR_VERSION = "fixed-rk4-v1"


class ModelSchemaError(ValueError):
    """A module is outside the closed public mathematical-model schema."""


@dataclass(frozen=True)
class _ModelRecord:
    module_id: str
    family: str
    public_model: Mapping[str, Any]
    compiled: Mapping[str, Any]
    version: str


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ModelSchemaError(f"non-JSON value is forbidden: {type(value).__name__}")


def _digest(value: Any) -> str:
    encoded = json.dumps(_plain(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _exact_keys(value: Any, required: Iterable[str], *, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ModelSchemaError(f"{where} must be an object")
    expected = set(required)
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ModelSchemaError(f"{where} fields mismatch; missing={missing}, extra={extra}")
    return value


def _number(value: Any, *, where: str, low: float | None = None, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise ModelSchemaError(f"{where} must be a finite number")
    out = float(value)
    if low is not None and out < low:
        raise ModelSchemaError(f"{where} must be >= {low}")
    if high is not None and out > high:
        raise ModelSchemaError(f"{where} must be <= {high}")
    return out


def _probability(value: Any, *, where: str) -> float:
    return _number(value, where=where, low=0.0, high=1.0)


def _times(value: Any, *, where: str) -> list[float]:
    if not isinstance(value, list) or not value:
        raise ModelSchemaError(f"{where} must be a non-empty list")
    out = [_number(item, where=f"{where}[{index}]", low=0.0) for index, item in enumerate(value)]
    if out != sorted(set(out)):
        raise ModelSchemaError(f"{where} must be strictly increasing")
    return out


def _contains_callable(value: Any) -> bool:
    if callable(value):
        return True
    if isinstance(value, Mapping):
        return any(_contains_callable(key) or _contains_callable(item) for key, item in value.items())
    if isinstance(value, (list, tuple, set)):
        return any(_contains_callable(item) for item in value)
    return False


_SENSITIVE_FIELDS = {
    "workload_id",
    "test_id",
    "assertion",
    "assertions",
    "assertion_id",
    "oracle",
    "oracle_view",
    "reference_id",
    "reference_path",
    "reference_output",
    "expected",
}


def _reject_runner_fields(value: Any, *, path: str = "module") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _SENSITIVE_FIELDS:
                raise ModelSchemaError(f"runner-only field forbidden at {path}.{key}")
            _reject_runner_fields(item, path=f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _reject_runner_fields(item, path=f"{path}[{index}]")


_CONTROL_DYNAMICS = re.compile(
    r"^dS_dt\s*=\s*(?P<recovery>[0-9]+(?:\.[0-9]+)?)\*\(1-S\)\s*-\s*"
    r"(?P<treatment>[0-9]+(?:\.[0-9]+)?)\*U\*S$"
)
_CONTROL_OBSERVATION = re.compile(
    r"^MAP\s*=\s*(?P<intercept>[0-9]+(?:\.[0-9]+)?)\s*-\s*"
    r"(?P<slope>[0-9]+(?:\.[0-9]+)?)\*S\s*\+\s*"
    r"(?P<support>[0-9]+(?:\.[0-9]+)?)\*U\s*\+\s*Normal\(0,\s*"
    r"(?P<sigma>[0-9]+(?:\.[0-9]+)?)\)$"
)


def _validate_controlled(model: Mapping[str, Any]) -> dict[str, Any]:
    _exact_keys(
        model,
        {"model_kind", "state", "control", "dynamics", "observation", "observation_hours", "query_hours", "seed"},
        where="public_model",
    )
    state = _exact_keys(model["state"], {"S0_prior", "bounds"}, where="state")
    prior = _exact_keys(state["S0_prior"], {"kind", "alpha", "beta"}, where="state.S0_prior")
    if prior["kind"] != "beta":
        raise ModelSchemaError("only beta S0_prior is supported")
    alpha = _number(prior["alpha"], where="state.S0_prior.alpha", low=1e-12)
    beta = _number(prior["beta"], where="state.S0_prior.beta", low=1e-12)
    if not isinstance(state["bounds"], list) or len(state["bounds"]) != 2:
        raise ModelSchemaError("state.bounds must be [low, high]")
    bounds = [_number(item, where="state.bounds") for item in state["bounds"]]
    if not bounds[0] < bounds[1]:
        raise ModelSchemaError("state.bounds must be increasing")
    control = _exact_keys(model["control"], {"U_bounds", "performed_intervals"}, where="control")
    if not isinstance(control["U_bounds"], list) or len(control["U_bounds"]) != 2:
        raise ModelSchemaError("control.U_bounds must be [low, high]")
    u_bounds = [_number(item, where="control.U_bounds") for item in control["U_bounds"]]
    if not u_bounds[0] < u_bounds[1]:
        raise ModelSchemaError("control.U_bounds must be increasing")
    intervals: list[tuple[float, float]] = []
    if not isinstance(control["performed_intervals"], list):
        raise ModelSchemaError("control.performed_intervals must be a list")
    for index, interval in enumerate(control["performed_intervals"]):
        if not isinstance(interval, list) or len(interval) != 2:
            raise ModelSchemaError(f"control.performed_intervals[{index}] must be [start,end]")
        start = _number(interval[0], where=f"performed_intervals[{index}].start", low=0.0)
        end = _number(interval[1], where=f"performed_intervals[{index}].end", low=0.0)
        if end <= start:
            raise ModelSchemaError("performed interval must have positive duration")
        intervals.append((start, end))
    dynamics = _CONTROL_DYNAMICS.fullmatch(str(model["dynamics"]))
    observation = _CONTROL_OBSERVATION.fullmatch(str(model["observation"]))
    if dynamics is None or observation is None:
        raise ModelSchemaError("controlled model equation is outside the closed grammar")
    observation_hours = _times(model["observation_hours"], where="observation_hours")
    query_hours = _times(model["query_hours"], where="query_hours")
    if isinstance(model["seed"], bool) or not isinstance(model["seed"], int):
        raise ModelSchemaError("seed must be an integer")
    return {
        "alpha": alpha,
        "beta": beta,
        "bounds": bounds,
        "u_bounds": u_bounds,
        "performed_intervals": intervals,
        "recovery": float(dynamics.group("recovery")),
        "treatment": float(dynamics.group("treatment")),
        "intercept": float(observation.group("intercept")),
        "slope": float(observation.group("slope")),
        "support": float(observation.group("support")),
        "sigma": float(observation.group("sigma")),
        "observation_hours": observation_hours,
        "query_hours": query_hours,
    }


def _validate_finite_scm(model: Mapping[str, Any]) -> dict[str, Any]:
    keys = set(model)
    confounding = {"model_kind", "P_severe", "P_treated_given_severe", "P_treated_given_mild", "P_bad"}
    structural = {"model_kind", "R", "structural_equation", "factual_evidence", "cross_world_policy"}
    if keys == confounding:
        bad = _exact_keys(model["P_bad"], {"severe_T0", "severe_T1", "mild_T0", "mild_T1"}, where="P_bad")
        return {
            "subkind": "confounding_binary",
            "P_severe": _probability(model["P_severe"], where="P_severe"),
            "P_treated_given_severe": _probability(model["P_treated_given_severe"], where="P_treated_given_severe"),
            "P_treated_given_mild": _probability(model["P_treated_given_mild"], where="P_treated_given_mild"),
            "P_bad": {key: _probability(value, where=f"P_bad.{key}") for key, value in bad.items()},
        }
    if keys == structural:
        r = _exact_keys(model["R"], {"values", "probabilities"}, where="R")
        if not isinstance(r["values"], list) or not r["values"]:
            raise ModelSchemaError("R.values must be non-empty")
        values = [_number(item, where="R.values") for item in r["values"]]
        if len(set(values)) != len(values):
            raise ModelSchemaError("R.values must be unique")
        if not isinstance(r["probabilities"], list) or len(r["probabilities"]) != len(values):
            raise ModelSchemaError("R.probabilities must align with R.values")
        probabilities = [_probability(item, where="R.probabilities") for item in r["probabilities"]]
        if not math.isclose(sum(probabilities), 1.0, abs_tol=1e-12):
            raise ModelSchemaError("R.probabilities must sum to one")
        evidence = _exact_keys(model["factual_evidence"], {"T", "Y"}, where="factual_evidence")
        if model["structural_equation"] != "Y = R*(1+T) + (1-R)*(-T)":
            raise ModelSchemaError("structural equation is outside the closed SCM grammar")
        if model["cross_world_policy"] != "share_abduced_exogenous":
            raise ModelSchemaError("unsupported cross_world_policy")
        return {
            "subkind": "shared_exogenous",
            "r_values": values,
            "r_probabilities": probabilities,
            "factual_T": _number(evidence["T"], where="factual_evidence.T"),
            "factual_Y": _number(evidence["Y"], where="factual_evidence.Y"),
        }
    raise ModelSchemaError("finite_scm fields do not match a supported closed variant")


_NONLINEAR_EQUATIONS = [
    "dB_dt = r*B*(1-B/K) - k_abx*A*B",
    "I = B^hill_h/(hill_K^hill_h+B^hill_h)",
    "dC_dt = (I-C)/tau_hours",
]


def _validate_nonlinear(model: Mapping[str, Any]) -> dict[str, Any]:
    _exact_keys(
        model,
        {"model_kind", "initial", "parameters", "dynamics", "pulse", "observation_hours", "query_hours", "seed"},
        where="public_model",
    )
    initial = _exact_keys(model["initial"], {"B", "C"}, where="initial")
    parameters = _exact_keys(
        model["parameters"], {"r", "K", "k_abx", "hill_h", "hill_K", "tau_hours"}, where="parameters"
    )
    pulse = _exact_keys(model["pulse"], {"A", "start_hour", "end_hour"}, where="pulse")
    if model["dynamics"] != _NONLINEAR_EQUATIONS:
        raise ModelSchemaError("nonlinear equations are outside the closed grammar")
    compiled = {
        "initial": {key: _number(value, where=f"initial.{key}", low=0.0) for key, value in initial.items()},
        "parameters": {
            "r": _number(parameters["r"], where="parameters.r"),
            "K": _number(parameters["K"], where="parameters.K", low=1e-12),
            "k_abx": _number(parameters["k_abx"], where="parameters.k_abx", low=0.0),
            "hill_h": _number(parameters["hill_h"], where="parameters.hill_h", low=1e-12),
            "hill_K": _number(parameters["hill_K"], where="parameters.hill_K", low=1e-12),
            "tau_hours": _number(parameters["tau_hours"], where="parameters.tau_hours", low=1e-12),
        },
        "pulse": {
            "A": _number(pulse["A"], where="pulse.A"),
            "start": _number(pulse["start_hour"], where="pulse.start_hour", low=0.0),
            "end": _number(pulse["end_hour"], where="pulse.end_hour", low=0.0),
        },
        "observation_hours": _times(model["observation_hours"], where="observation_hours"),
        "query_hours": _times(model["query_hours"], where="query_hours"),
    }
    if compiled["pulse"]["end"] <= compiled["pulse"]["start"]:
        raise ModelSchemaError("pulse end must follow pulse start")
    if isinstance(model["seed"], bool) or not isinstance(model["seed"], int):
        raise ModelSchemaError("seed must be an integer")
    return compiled


def _validate_hypothesis(model: Mapping[str, Any]) -> dict[str, Any]:
    _exact_keys(
        model,
        {
            "model_kind",
            "prior",
            "pre_treatment_phenotype_likelihood",
            "P_response_after_antipyretic",
            "P_mechanism_response_after_antibiotic",
        },
        where="public_model",
    )
    prior = model["prior"]
    if not isinstance(prior, Mapping) or len(prior) < 2 or not all(isinstance(key, str) and key for key in prior):
        raise ModelSchemaError("prior must name at least two hypotheses")
    hypotheses = set(prior)
    compiled: dict[str, Any] = {"prior": {key: _probability(value, where=f"prior.{key}") for key, value in prior.items()}}
    if not math.isclose(sum(compiled["prior"].values()), 1.0, abs_tol=1e-12):
        raise ModelSchemaError("prior probabilities must sum to one")
    for field in (
        "pre_treatment_phenotype_likelihood",
        "P_response_after_antipyretic",
        "P_mechanism_response_after_antibiotic",
    ):
        values = model[field]
        if not isinstance(values, Mapping) or set(values) != hypotheses:
            raise ModelSchemaError(f"{field} must cover exactly the prior hypotheses")
        compiled[field] = {key: _probability(value, where=f"{field}.{key}") for key, value in values.items()}
    return compiled


_OPEN_EQUATIONS = [
    "clearance = CL0*renal*amount/(Km+amount)",
    "efficacy = Emax*amount/(EC50+amount)",
    "toxicity = (amount^2/(Tmax^2+amount^2))*(1-renal)",
    "dBurden_dt = r_burden*burden*(1-burden)-efficacy*burden",
]
_PORT = re.compile(r"^[A-Z][A-Za-z0-9_]*\.[a-z][A-Za-z0-9_]*<-[A-Z][A-Za-z0-9_]*\.[a-z][A-Za-z0-9_]*$")


def _validate_open_ode(model: Mapping[str, Any]) -> dict[str, Any]:
    _exact_keys(
        model,
        {"model_kind", "initial", "parameters", "ports", "input", "query_hours", "interaction_equations"},
        where="public_model",
    )
    initial = _exact_keys(model["initial"], {"burden", "drug_amount", "renal_capacity"}, where="initial")
    parameters = _exact_keys(model["parameters"], {"r_burden", "CL0", "Km", "Emax", "EC50", "Tmax"}, where="parameters")
    input_data = _exact_keys(model["input"], {"infusion_rate", "start_hour", "end_hour"}, where="input")
    if model["interaction_equations"] != _OPEN_EQUATIONS:
        raise ModelSchemaError("open-ODE interaction equations are outside the closed grammar")
    ports = model["ports"]
    if not isinstance(ports, list) or not ports or any(not isinstance(port, str) or not _PORT.fullmatch(port) for port in ports):
        raise ModelSchemaError("ports must use the closed Component.port<-Component.port grammar")
    if len(set(ports)) != len(ports):
        raise ModelSchemaError("ports must be unique")
    compiled = {
        "initial": {
            "burden": _number(initial["burden"], where="initial.burden", low=0.0),
            "drug_amount": _number(initial["drug_amount"], where="initial.drug_amount", low=0.0),
            "renal_capacity": _number(initial["renal_capacity"], where="initial.renal_capacity", low=0.0, high=1.0),
        },
        "parameters": {key: _number(value, where=f"parameters.{key}", low=0.0) for key, value in parameters.items()},
        "input": {
            "rate": _number(input_data["infusion_rate"], where="input.infusion_rate", low=0.0),
            "start": _number(input_data["start_hour"], where="input.start_hour", low=0.0),
            "end": _number(input_data["end_hour"], where="input.end_hour", low=0.0),
        },
        "query_hours": _times(model["query_hours"], where="query_hours"),
        "ports": list(ports),
    }
    for required_positive in ("Km", "EC50", "Tmax"):
        if compiled["parameters"][required_positive] <= 0.0:
            raise ModelSchemaError(f"parameters.{required_positive} must be positive")
    if compiled["input"]["end"] <= compiled["input"]["start"]:
        raise ModelSchemaError("infusion end must follow start")
    return compiled


def _validate_composition(model: Mapping[str, Any]) -> dict[str, Any]:
    _exact_keys(model, {"model_kind", "input", "modules", "claimed_law"}, where="public_model")
    if model["claimed_law"] != "associative_parallel_sum":
        raise ModelSchemaError("unsupported composition law")
    modules = model["modules"]
    if not isinstance(modules, Mapping) or not modules:
        raise ModelSchemaError("composition modules must be non-empty")
    compiled_modules: dict[str, float] = {}
    for name, data in modules.items():
        if not isinstance(name, str) or not name:
            raise ModelSchemaError("composition module names must be non-empty strings")
        delta = _exact_keys(data, {"delta"}, where=f"modules.{name}")["delta"]
        compiled_modules[name] = _number(delta, where=f"modules.{name}.delta")
    return {"input": _number(model["input"], where="input"), "modules": compiled_modules}


_FIXED_POINT = re.compile(
    r"^x_next\s*=\s*(?P<a>[+-]?[0-9]+(?:\.[0-9]+)?)\*x\s*(?P<sign>[+-])\s*(?P<b>[0-9]+(?:\.[0-9]+)?)$"
)
_IDENTITY_SHIFT = re.compile(r"^x\s*=\s*x(?:\s*(?P<sign>[+-])\s*(?P<c>[0-9]+(?:\.[0-9]+)?))?$")
_SUPPORT_EDGE = re.compile(r"^(?P<target>[A-Za-z][A-Za-z0-9_]*)<-(?P<source>[A-Za-z][A-Za-z0-9_]*)$")


def _validate_feedback(model: Mapping[str, Any]) -> dict[str, Any]:
    _exact_keys(model, {"model_kind", "contraction", "rootless_support_cycle", "no_solution", "non_unique"}, where="public_model")
    contraction = _FIXED_POINT.fullmatch(str(model["contraction"]))
    if contraction is None:
        raise ModelSchemaError("contraction equation is outside the closed grammar")
    a = float(contraction.group("a"))
    b = float(contraction.group("b")) * (1.0 if contraction.group("sign") == "+" else -1.0)
    if abs(a) >= 1.0:
        raise ModelSchemaError("declared contraction must have |a| < 1")
    edges = model["rootless_support_cycle"]
    if not isinstance(edges, list) or not edges:
        raise ModelSchemaError("rootless_support_cycle must be a non-empty list")
    parsed_edges: list[tuple[str, str]] = []
    for item in edges:
        match = _SUPPORT_EDGE.fullmatch(str(item))
        if match is None:
            raise ModelSchemaError("support edges must use target<-source")
        parsed_edges.append((match.group("target"), match.group("source")))
    no_solution = _IDENTITY_SHIFT.fullmatch(str(model["no_solution"]))
    non_unique = _IDENTITY_SHIFT.fullmatch(str(model["non_unique"]))
    if no_solution is None or non_unique is None:
        raise ModelSchemaError("implicit equations are outside the closed grammar")

    def shift(match: re.Match[str]) -> float:
        if match.group("c") is None:
            return 0.0
        return float(match.group("c")) * (1.0 if match.group("sign") == "+" else -1.0)

    if shift(no_solution) == 0.0 or shift(non_unique) != 0.0:
        raise ModelSchemaError("no_solution/non_unique equations are misclassified")
    return {"a": a, "b": b, "edges": parsed_edges, "no_shift": shift(no_solution)}


_VALIDATORS: dict[str, Callable[[Mapping[str, Any]], dict[str, Any]]] = {
    "controlled_state_space": _validate_controlled,
    "finite_scm": _validate_finite_scm,
    "nonlinear_state_space": _validate_nonlinear,
    "finite_hypothesis_model": _validate_hypothesis,
    "typed_open_ode": _validate_open_ode,
    "composition_law_probe": _validate_composition,
    "feedback_and_support": _validate_feedback,
}


def _rk4(
    rhs: Callable[[float, Sequence[float]], Sequence[float]],
    initial: Sequence[float],
    end: float,
    *,
    step: float = 1.0 / 240.0,
    boundaries: Iterable[float] = (),
) -> tuple[list[float], list[list[float]]]:
    """Deterministic vector RK4 that lands exactly on declared discontinuities."""

    if end < 0.0:
        raise ValueError("integration end must be non-negative")
    stops = sorted({0.0, end, *(float(item) for item in boundaries if 0.0 < float(item) < end)})
    t = 0.0
    y = [float(item) for item in initial]
    ts = [t]
    ys = [y.copy()]
    for stop in stops[1:]:
        while t < stop - 1e-14:
            h = min(step, stop - t)
            k1 = list(rhs(t, y))
            k2 = list(rhs(t + h / 2.0, [value + h * slope / 2.0 for value, slope in zip(y, k1)]))
            k3 = list(rhs(t + h / 2.0, [value + h * slope / 2.0 for value, slope in zip(y, k2)]))
            k4 = list(rhs(t + h, [value + h * slope for value, slope in zip(y, k3)]))
            y = [
                value + h * (s1 + 2.0 * s2 + 2.0 * s3 + s4) / 6.0
                for value, s1, s2, s3, s4 in zip(y, k1, k2, k3, k4)
            ]
            if not all(math.isfinite(value) for value in y):
                raise FloatingPointError("non-finite RK4 state")
            t += h
            ts.append(t)
            ys.append(y.copy())
    return ts, ys


def _sample(ts: Sequence[float], values: Sequence[Sequence[float]], hours: Iterable[float]) -> list[list[float]]:
    out: list[list[float]] = []
    for hour in hours:
        index = min(range(len(ts)), key=lambda item: abs(ts[item] - float(hour)))
        out.append(list(values[index]))
    return out


def _hours_between(later: str, earlier: str) -> float:
    left = parse_time(later)
    right = parse_time(earlier)
    assert left is not None and right is not None
    return (left - right).total_seconds() / 3600.0


class ExperimentalModelSubkernel(ArchitectureCandidate):
    """Executable closed-schema model subkernel for E-style experiments."""

    def __init__(self, track: Track | None = Track.NATIVE) -> None:
        super().__init__(track or Track.NATIVE)
        self._models: dict[str, _ModelRecord] = {}
        self._artifacts: dict[str, SourceArtifact] = {}
        self._retracted: set[str] = set()
        self._revision = 0
        self._result_counter = 0
        self._result_records: dict[str, dict[str, Any]] = {}

    @property
    def manifest(self) -> CandidateManifest:
        return CandidateManifest(
            candidate_id="experimental-model-subkernel",
            version=SUBKERNEL_VERSION,
            formal_signature=(
                "ClosedPublicModel",
                "SourceArtifact",
                "QuerySpec",
                "CapabilityResult",
            ),
            execution_semantics=(
                "exact finite enumeration",
                "abduction-action-prediction",
                "deterministic RK4 with explicit discontinuities",
                "finite-hypothesis Bayes update",
                "typed fixed-point classification",
            ),
            companion_layers=(),
            primitive_profile={
                "native": (
                    "controlled_state_space",
                    "finite_scm",
                    "nonlinear_state_space",
                    "finite_hypothesis_model",
                    "typed_open_ode",
                    "composition_law_probe",
                    "feedback_and_support",
                )
            },
            foreign_boundaries=(),
            declared_query_capabilities=(
                QueryKind.CONDITION,
                QueryKind.FILTER,
                QueryKind.FORECAST,
                QueryKind.INTERVENE,
                QueryKind.COUNTERFACTUAL,
                QueryKind.REACHABILITY,
                QueryKind.CHECK_INVARIANT,
                QueryKind.EXPLAIN,
            ),
            failure_types=(
                ResultStatus.INVALID,
                ResultStatus.UNSUPPORTED,
                ResultStatus.INSUFFICIENT,
                ResultStatus.NUMERICAL_FAILURE,
                ResultStatus.OUT_OF_MODEL,
            ),
        )

    def _versions(self, model: _ModelRecord | None = None) -> dict[str, Any]:
        return {
            "candidate": SUBKERNEL_VERSION,
            "model_schema": MODEL_SCHEMA_VERSION,
            "integrator": INTEGRATOR_VERSION,
            "model": model.version if model else None,
            "evidence_revision": self._revision,
        }

    def _emit(
        self,
        *,
        status: ResultStatus,
        operation: str,
        value: Any = None,
        value_kind: str = "none",
        model: _ModelRecord | None = None,
        validation: str = "valid",
        capability: str = "native",
        epistemic: str = "not_applicable",
        coverage_status: str = "in_domain",
        identification: str = "not_applicable",
        computation: str = "exact",
        assumptions: Iterable[str] = (),
        roots: Iterable[str] = (),
        native_witness: Mapping[str, Any] | None = None,
        diagnostics: Mapping[str, Any] | None = None,
    ) -> CapabilityResult:
        self._result_counter += 1
        root_list = sorted(set(str(item) for item in roots))
        witness = dict(native_witness or {})
        seed = {
            "counter": self._result_counter,
            "operation": operation,
            "model": model.version if model else None,
            "value": value,
            "roots": root_list,
            "revision": self._revision,
        }
        result_id = "model-result:" + _digest(seed).split(":", 1)[1][:24]
        witness.update(
            {
                "result_id": result_id,
                "operation": operation,
                "module_id": model.module_id if model else None,
                "model_kind": model.family if model else None,
                "compiled_ir_hash": model.version if model else None,
            }
        )
        result = CapabilityResult(
            status=status,
            validation=validation,
            capability=capability,
            epistemic=epistemic,
            coverage_status=coverage_status,
            identification=identification,
            computation=computation,
            value_kind=value_kind,
            value=copy.deepcopy(value),
            assumptions=list(assumptions),
            coverage={"closed_schema": MODEL_SCHEMA_VERSION, "model_kind": model.family if model else None},
            time_cut={},
            evidence_witness={"root_sources": root_list, "statistical_independence_assumed": False},
            native_witness=witness,
            diagnostics=dict(diagnostics or {}),
            versions=self._versions(model),
        )
        self._result_records[result_id] = {
            "operation": operation,
            "status": status.value,
            "value_kind": value_kind,
            "model_version": model.version if model else None,
            "evidence_roots": root_list,
            "native_witness": copy.deepcopy(witness),
            "diagnostics": copy.deepcopy(dict(diagnostics or {})),
        }
        return result

    def _invalid(self, operation: str, reason: str) -> CapabilityResult:
        return self._emit(
            status=ResultStatus.INVALID,
            operation=operation,
            validation="invalid",
            capability="unsupported",
            coverage_status="unknown",
            computation="not_applicable",
            diagnostics={"reason": reason, "failure_type": "closed_schema_violation"},
        )

    def _unsupported(self, operation: str, reason: str, model: _ModelRecord | None = None) -> CapabilityResult:
        return self._emit(
            status=ResultStatus.UNSUPPORTED,
            operation=operation,
            model=model,
            capability="unsupported",
            coverage_status="out_of_model",
            computation="not_applicable",
            diagnostics={"reason": reason, "failure_type": "unsupported_query"},
        )

    def _insufficient(self, operation: str, reason: str, model: _ModelRecord | None = None) -> CapabilityResult:
        return self._emit(
            status=ResultStatus.INSUFFICIENT,
            operation=operation,
            model=model,
            epistemic="insufficient",
            coverage_status="partial",
            computation="not_applicable",
            diagnostics={"reason": reason, "failure_type": "insufficient_input"},
        )

    def register_module(self, module: Any) -> CapabilityResult:
        try:
            if _contains_callable(module):
                raise ModelSchemaError("callbacks/callables are forbidden")
            _reject_runner_fields(module)
            wrapper = _exact_keys(module, {"module_id", "family", "public_model"}, where="module")
            module_id = wrapper["module_id"]
            family = wrapper["family"]
            public_model = wrapper["public_model"]
            if not isinstance(module_id, str) or not module_id:
                raise ModelSchemaError("module_id must be a non-empty string")
            if not isinstance(family, str) or family not in _VALIDATORS:
                raise ModelSchemaError(f"unsupported family: {family!r}")
            if not isinstance(public_model, Mapping):
                raise ModelSchemaError("public_model must be an object")
            if public_model.get("model_kind") != family:
                raise ModelSchemaError("family must equal public_model.model_kind")
            compiled = _VALIDATORS[family](public_model)
            detached = _plain(public_model)
            version = _digest({"schema": MODEL_SCHEMA_VERSION, "family": family, "public_model": detached})
            existing = self._models.get(module_id)
            if existing is not None and existing.version != version:
                raise ModelSchemaError(f"module_id {module_id!r} already has a different immutable version")
            record = _ModelRecord(module_id, family, detached, compiled, version)
            if existing is None:
                self._models[module_id] = record
                self._revision += 1
            return self._emit(
                status=ResultStatus.OK,
                operation="register_module",
                model=record,
                value={"module_id": module_id, "model_kind": family, "model_version": version},
                value_kind="module_registration",
                native_witness={"schema_validated": True, "closed_grammar": True},
            )
        except (ModelSchemaError, TypeError, ValueError) as exc:
            return self._invalid("register_module", str(exc))

    def ingest(self, artifact: SourceArtifact) -> CapabilityResult:
        if not isinstance(artifact, SourceArtifact):
            return self._invalid("ingest", "artifact must be SourceArtifact")
        existing = self._artifacts.get(artifact.source_id)
        if existing is not None and existing != artifact:
            return self._invalid("ingest", f"source_id {artifact.source_id!r} is immutable and already differs")
        if existing is None:
            self._artifacts[artifact.source_id] = copy.deepcopy(artifact)
            self._retracted.discard(artifact.source_id)
            self._revision += 1
        return self._emit(
            status=ResultStatus.OK,
            operation="ingest",
            value={"source_id": artifact.source_id, "accepted": True, "idempotent": existing is not None},
            value_kind="ingest_receipt",
            roots=[artifact.source_id],
            native_witness={"artifact_id": artifact.artifact_id, "semantic_role": artifact.semantic_role.value},
        )

    def retract(self, source_id: str, known_at: str) -> CapabilityResult:
        try:
            parse_time(known_at)
        except (ContractError, ValueError) as exc:
            return self._invalid("retract", str(exc))
        if source_id not in self._artifacts:
            return self._insufficient("retract", f"unknown source_id: {source_id}")
        was_retracted = source_id in self._retracted
        if not was_retracted:
            self._retracted.add(source_id)
            self._revision += 1
        return self._emit(
            status=ResultStatus.OK,
            operation="retract",
            value={"source_id": source_id, "retracted": True, "idempotent": was_retracted},
            value_kind="retraction_receipt",
            native_witness={"known_at": known_at},
        )

    def _model_for(self, spec: QuerySpec) -> _ModelRecord | CapabilityResult:
        if not self._models:
            return self._insufficient("query", "no model module is registered")
        if spec.model_version:
            matches = [record for record in self._models.values() if record.version == spec.model_version]
            if len(matches) == 1:
                return matches[0]
            return self._insufficient("query", f"model_version not uniquely registered: {spec.model_version}")
        if len(self._models) != 1:
            return self._insufficient("query", "multiple modules require an explicit model_version")
        return next(iter(self._models.values()))

    def _eligible(self, spec: QuerySpec, *, include_future_valid: bool = False) -> list[SourceArtifact]:
        known = parse_time(spec.as_known_at)
        valid = parse_time(spec.valid_at)
        assert known is not None
        selected: list[SourceArtifact] = []
        for source_id, artifact in self._artifacts.items():
            if source_id in self._retracted or artifact.scope.subject_id != spec.subject_id:
                continue
            available = parse_time(artifact.clocks.available_at)
            effective_start = parse_time(artifact.clocks.effective_start)
            effective_end = parse_time(artifact.clocks.effective_end)
            if available is None or available > known:
                continue
            if not include_future_valid and valid is not None:
                if effective_start is not None and effective_start > valid:
                    continue
                if effective_end is not None and effective_end < valid:
                    continue
            selected.append(artifact)
        return sorted(selected, key=lambda item: (parse_time(item.clocks.available_at), item.source_id))

    def query(self, spec: QuerySpec) -> CapabilityResult:
        if not isinstance(spec, QuerySpec):
            return self._invalid("query", "spec must be QuerySpec")
        model_or_result = self._model_for(spec)
        if isinstance(model_or_result, CapabilityResult):
            return model_or_result
        model = model_or_result
        try:
            if model.family == "controlled_state_space":
                return self._query_controlled(model, spec)
            if model.family == "finite_scm":
                return self._query_scm(model, spec)
            if model.family == "nonlinear_state_space":
                return self._query_nonlinear(model, spec)
            if model.family == "finite_hypothesis_model":
                return self._query_hypothesis(model, spec)
            if model.family == "typed_open_ode":
                return self._query_open_ode(model, spec)
            if model.family == "composition_law_probe":
                return self._query_composition(model, spec)
            if model.family == "feedback_and_support":
                return self._query_feedback(model, spec)
        except (ArithmeticError, FloatingPointError, OverflowError) as exc:
            return self._emit(
                status=ResultStatus.NUMERICAL_FAILURE,
                operation="query",
                model=model,
                capability="native",
                coverage_status="in_domain",
                computation="numerical_failure",
                diagnostics={"reason": str(exc), "failure_type": "numerical_failure"},
            )
        except (ModelSchemaError, ContractError, TypeError, ValueError) as exc:
            return self._invalid("query", str(exc))
        return self._unsupported("query", f"unimplemented model family: {model.family}", model)

    @staticmethod
    def _control_value(compiled: Mapping[str, Any], hour: float) -> float:
        return 1.0 if any(start <= hour < end for start, end in compiled["performed_intervals"]) else 0.0

    def _controlled_path(
        self,
        compiled: Mapping[str, Any],
        end: float,
        *,
        intervention_start: float | None = None,
        intervention_value: float | None = None,
    ) -> tuple[list[float], list[list[float]]]:
        initial = compiled["alpha"] / (compiled["alpha"] + compiled["beta"])

        def rhs(t: float, y: Sequence[float]) -> Sequence[float]:
            u = self._control_value(compiled, t)
            if intervention_start is not None and t >= intervention_start and intervention_value is not None:
                u = intervention_value
            s = y[0]
            return [compiled["recovery"] * (1.0 - s) - compiled["treatment"] * u * s]

        boundaries = [edge for interval in compiled["performed_intervals"] for edge in interval]
        if intervention_start is not None:
            boundaries.append(intervention_start)
        return _rk4(rhs, [initial], end, boundaries=boundaries)

    def _query_hour(self, spec: QuerySpec, artifacts: Sequence[SourceArtifact]) -> float:
        point = spec.valid_at or spec.as_known_at
        if artifacts:
            anchor = min(artifact.clocks.effective_start for artifact in artifacts)
            return max(0.0, _hours_between(point, anchor))
        parsed = parse_time(point)
        assert parsed is not None
        midnight = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        return (parsed - midnight).total_seconds() / 3600.0

    def _query_controlled(self, model: _ModelRecord, spec: QuerySpec) -> CapabilityResult:
        if spec.target != "S":
            return self._unsupported("query", f"controlled model has no target {spec.target!r}", model)
        if spec.kind not in {QueryKind.FILTER, QueryKind.FORECAST, QueryKind.COUNTERFACTUAL, QueryKind.INTERVENE}:
            return self._unsupported("query", f"{spec.kind.value} is not supported by controlled state-space", model)
        artifacts = self._eligible(spec)
        roots = [artifact.source_id for artifact in artifacts]
        hour = self._query_hour(spec, artifacts)
        intervention_start: float | None = None
        intervention_value: float | None = None
        assumptions: list[str] = []
        world = "filtered"
        end = hour
        if spec.kind in {QueryKind.FORECAST, QueryKind.COUNTERFACTUAL, QueryKind.INTERVENE}:
            end = hour + float(spec.horizon_hours or 0.0)
            world = "forecast" if spec.kind is QueryKind.FORECAST else "interventional"
        if spec.kind in {QueryKind.COUNTERFACTUAL, QueryKind.INTERVENE}:
            intervention = spec.intervention or {}
            if set(intervention) != {"variable", "value"} or intervention.get("variable") != "U":
                return self._invalid("query", "controlled intervention must be exactly {variable:'U', value:number}")
            intervention_value = _number(intervention["value"], where="intervention.value")
            low, high = model.compiled["u_bounds"]
            if not low <= intervention_value <= high:
                return self._invalid("query", "intervention U is outside declared bounds")
            intervention_start = hour
            world = "counterfactual" if spec.kind is QueryKind.COUNTERFACTUAL else "interventional"
            if spec.kind is QueryKind.COUNTERFACTUAL:
                assumptions.append("same_pre_intervention_initial_condition")
        ts, ys = self._controlled_path(
            model.compiled,
            end,
            intervention_start=intervention_start,
            intervention_value=intervention_value,
        )
        state = _sample(ts, ys, [hour])[0][0]
        if spec.kind is QueryKind.FILTER:
            # Closed one-step Gaussian update from the latest MAP at the valid
            # cut.  This uses the declared observation equation; no raw value
            # is silently treated as a latent state.
            observations = [artifact for artifact in artifacts if artifact.concept == "mean_arterial_pressure" and artifact.information_state is InfoState.PRESENT]
            if observations:
                latest = max(observations, key=lambda item: parse_time(item.clocks.effective_start))
                u = _number(latest.context.get("performed_support_U", self._control_value(model.compiled, hour)), where="performed_support_U")
                observed_state = (model.compiled["intercept"] + model.compiled["support"] * u - float(latest.value)) / model.compiled["slope"]
                observed_state = min(model.compiled["bounds"][1], max(model.compiled["bounds"][0], observed_state))
                prior_var = model.compiled["alpha"] * model.compiled["beta"] / (
                    (model.compiled["alpha"] + model.compiled["beta"]) ** 2
                    * (model.compiled["alpha"] + model.compiled["beta"] + 1.0)
                )
                obs_var = (model.compiled["sigma"] / model.compiled["slope"]) ** 2
                state = (state / prior_var + observed_state / obs_var) / (1.0 / prior_var + 1.0 / obs_var)
        query_hours = [value for value in model.compiled["query_hours"] if value <= end + 1e-12]
        trajectory = [
            {"hour": query_hour, "S": values[0]}
            for query_hour, values in zip(query_hours, _sample(ts, ys, query_hours))
        ]
        value: dict[str, Any] = {"state": state, "S": state, "world": world, "trajectory": trajectory}
        if intervention_value is not None:
            value["intervention"] = {"variable": "U", "value": intervention_value, "start_hour": hour}
        return self._emit(
            status=ResultStatus.OK,
            operation="query",
            model=model,
            value=value,
            value_kind="state_estimate" if spec.kind is QueryKind.FILTER else "trajectory",
            epistemic="posterior" if spec.kind is QueryKind.FILTER else "not_applicable",
            identification="identified",
            computation="converged",
            assumptions=assumptions,
            roots=roots,
            native_witness={"query_kind": spec.kind.value, "algorithm": "rk4_plus_closed_gaussian_filter", "state_observation_separated": True},
            diagnostics={"step_hours": 1.0 / 240.0, "integration_end_hour": end},
        )

    @staticmethod
    def _parse_treatment_task(task: str | None) -> int:
        match = re.fullmatch(r"T=([01])", task or "")
        if match is None:
            raise ModelSchemaError("binary SCM condition task must be T=0 or T=1")
        return int(match.group(1))

    def _query_scm(self, model: _ModelRecord, spec: QuerySpec) -> CapabilityResult:
        compiled = model.compiled
        roots = [artifact.source_id for artifact in self._eligible(spec)]
        if compiled["subkind"] == "confounding_binary":
            if spec.target != "Y_bad":
                return self._unsupported("query", f"binary SCM has no target {spec.target!r}", model)
            if spec.kind is QueryKind.CONDITION:
                treatment = self._parse_treatment_task(spec.task)
                p_h = compiled["P_severe"]
                p_t_h = compiled["P_treated_given_severe"] if treatment else 1.0 - compiled["P_treated_given_severe"]
                p_t_m = compiled["P_treated_given_mild"] if treatment else 1.0 - compiled["P_treated_given_mild"]
                normalizer = p_h * p_t_h + (1.0 - p_h) * p_t_m
                if normalizer <= 0.0:
                    return self._insufficient("query", "conditioning event has probability zero", model)
                severe_posterior = p_h * p_t_h / normalizer
                probability = (
                    severe_posterior * compiled["P_bad"][f"severe_T{treatment}"]
                    + (1.0 - severe_posterior) * compiled["P_bad"][f"mild_T{treatment}"]
                )
                estimand = f"P(Y_bad=1|T={treatment})"
                witness = {"operator": "condition", "posterior_P_severe": severe_posterior}
            elif spec.kind is QueryKind.INTERVENE:
                intervention = spec.intervention or {}
                if set(intervention) != {"variable", "value"} or intervention.get("variable") != "T" or intervention.get("value") not in (0, 1):
                    return self._invalid("query", "binary SCM intervention must be exactly {variable:'T', value:0|1}")
                treatment = int(intervention["value"])
                p_h = compiled["P_severe"]
                probability = p_h * compiled["P_bad"][f"severe_T{treatment}"] + (1.0 - p_h) * compiled["P_bad"][f"mild_T{treatment}"]
                estimand = f"P(Y_bad=1|do(T={treatment}))"
                witness = {"operator": "truncated_factorization", "intervention": {"T": treatment}}
            else:
                return self._unsupported("query", f"{spec.kind.value} is unsupported for this finite SCM", model)
            return self._emit(
                status=ResultStatus.OK,
                operation="query",
                model=model,
                value={"probability": probability, "estimand": estimand},
                value_kind="finite_probability",
                identification="identified",
                computation="exact",
                roots=roots,
                native_witness={"query_kind": spec.kind.value, **witness, "enumeration": "finite_exact"},
            )

        if spec.target not in {"Y", "R"}:
            return self._unsupported("query", f"shared-exogenous SCM has no target {spec.target!r}", model)
        factual_t = compiled["factual_T"]
        factual_y = compiled["factual_Y"]
        for artifact in self._eligible(spec):
            if artifact.concept == "factual_T1_Y2" and isinstance(artifact.value, Mapping):
                if set(artifact.value) == {"T", "Y"}:
                    factual_t = _number(artifact.value["T"], where="factual.T")
                    factual_y = _number(artifact.value["Y"], where="factual.Y")

        def equation(r_value: float, treatment: float) -> float:
            return r_value * (1.0 + treatment) + (1.0 - r_value) * (-treatment)

        weights = [
            probability if math.isclose(equation(r_value, factual_t), factual_y, abs_tol=1e-12) else 0.0
            for r_value, probability in zip(compiled["r_values"], compiled["r_probabilities"])
        ]
        z = sum(weights)
        if z <= 0.0:
            return self._insufficient("query", "factual evidence has zero probability under the SCM", model)
        posterior = [weight / z for weight in weights]
        if spec.kind is QueryKind.CONDITION and spec.target == "R":
            value = {"distribution": [{"value": r, "probability": p} for r, p in zip(compiled["r_values"], posterior)]}
            assumptions: list[str] = []
            operator = "abduction"
        elif spec.kind in {QueryKind.COUNTERFACTUAL, QueryKind.INTERVENE} and spec.target == "Y":
            intervention = spec.intervention or {}
            if set(intervention) != {"variable", "value"} or intervention.get("variable") != "T":
                return self._invalid("query", "SCM intervention must be exactly {variable:'T', value:number}")
            treatment = _number(intervention["value"], where="intervention.value")
            if spec.kind is QueryKind.COUNTERFACTUAL:
                distribution = posterior
                assumptions = ["share_abduced_exogenous"]
                operator = "abduction_action_prediction"
            else:
                distribution = list(compiled["r_probabilities"])
                assumptions = []
                operator = "population_truncated_factorization"
            mean = sum(probability * equation(r_value, treatment) for r_value, probability in zip(compiled["r_values"], distribution))
            value = {"mean": mean, "probability": mean, "estimand": "individual_counterfactual" if spec.kind is QueryKind.COUNTERFACTUAL else "population_do"}
        else:
            return self._unsupported("query", f"{spec.kind.value}/{spec.target} is unsupported for shared-exogenous SCM", model)
        return self._emit(
            status=ResultStatus.OK,
            operation="query",
            model=model,
            value=value,
            value_kind="finite_probability" if spec.target == "R" else "counterfactual_expectation",
            epistemic="posterior" if spec.kind is QueryKind.COUNTERFACTUAL else "not_applicable",
            identification="identified",
            computation="exact",
            assumptions=assumptions,
            roots=roots,
            native_witness={"query_kind": spec.kind.value, "operator": operator, "abduced_distribution": posterior, "enumeration": "finite_exact"},
        )

    def _nonlinear_path(
        self,
        compiled: Mapping[str, Any],
        end: float,
        *,
        intervention_start: float | None = None,
        intervention_value: float | None = None,
    ) -> tuple[list[float], list[list[float]]]:
        p = compiled["parameters"]
        pulse = compiled["pulse"]

        def rhs(t: float, y: Sequence[float]) -> Sequence[float]:
            b, c = y
            a = pulse["A"] if pulse["start"] <= t < pulse["end"] else 0.0
            if intervention_start is not None and t >= intervention_start and intervention_value is not None:
                a = intervention_value
            db = p["r"] * b * (1.0 - b / p["K"]) - p["k_abx"] * a * b
            numerator = b ** p["hill_h"]
            denominator = p["hill_K"] ** p["hill_h"] + numerator
            signal = numerator / denominator
            dc = (signal - c) / p["tau_hours"]
            return [db, dc]

        boundaries = [pulse["start"], pulse["end"]]
        if intervention_start is not None:
            boundaries.append(intervention_start)
        return _rk4(rhs, [compiled["initial"]["B"], compiled["initial"]["C"]], end, boundaries=boundaries)

    def _query_nonlinear(self, model: _ModelRecord, spec: QuerySpec) -> CapabilityResult:
        if spec.target not in {"B", "C"}:
            return self._unsupported("query", f"nonlinear state-space has no target {spec.target!r}", model)
        if spec.kind not in {QueryKind.FILTER, QueryKind.FORECAST, QueryKind.COUNTERFACTUAL, QueryKind.INTERVENE}:
            return self._unsupported("query", f"{spec.kind.value} is unsupported by nonlinear state-space", model)
        artifacts = self._eligible(spec)
        hour = self._query_hour(spec, artifacts)
        horizon = float(spec.horizon_hours or 0.0) if spec.kind is not QueryKind.FILTER else 0.0
        end = max(max(model.compiled["query_hours"]), hour + horizon)
        intervention_start = None
        intervention_value = None
        assumptions: list[str] = []
        if spec.kind in {QueryKind.COUNTERFACTUAL, QueryKind.INTERVENE}:
            intervention = spec.intervention or {}
            if set(intervention) != {"variable", "value"} or intervention.get("variable") != "A":
                return self._invalid("query", "nonlinear intervention must be exactly {variable:'A', value:number}")
            intervention_start = hour
            intervention_value = _number(intervention["value"], where="intervention.value")
            if spec.kind is QueryKind.COUNTERFACTUAL:
                assumptions.append("same_pre_intervention_initial_condition")
        ts, ys = self._nonlinear_path(
            model.compiled,
            end,
            intervention_start=intervention_start,
            intervention_value=intervention_value,
        )
        rows = [
            {"hour": query_hour, "B": values[0], "C": values[1]}
            for query_hour, values in zip(model.compiled["query_hours"], _sample(ts, ys, model.compiled["query_hours"]))
        ]
        state = _sample(ts, ys, [hour])[0]
        value = {
            "state": {"B": state[0], "C": state[1]},
            "trajectory": rows,
            "world": "counterfactual" if spec.kind is QueryKind.COUNTERFACTUAL else "interventional" if spec.kind is QueryKind.INTERVENE else spec.kind.value,
        }
        return self._emit(
            status=ResultStatus.OK,
            operation="query",
            model=model,
            value=value,
            value_kind="trajectory",
            epistemic="posterior" if spec.kind is QueryKind.FILTER else "not_applicable",
            identification="identified",
            computation="converged",
            assumptions=assumptions,
            roots=[artifact.source_id for artifact in artifacts],
            native_witness={"query_kind": spec.kind.value, "algorithm": INTEGRATOR_VERSION, "state_observation_separated": True},
            diagnostics={"step_hours": 1.0 / 240.0, "integration_end_hour": end},
        )

    def _query_hypothesis(self, model: _ModelRecord, spec: QuerySpec) -> CapabilityResult:
        if spec.kind is not QueryKind.FILTER or spec.target != "diagnostic_hypothesis":
            return self._unsupported("query", f"finite hypothesis model supports FILTER diagnostic_hypothesis, not {spec.kind.value}/{spec.target}", model)
        artifacts = self._eligible(spec, include_future_valid=True)
        if not artifacts:
            return self._insufficient("query", "finite hypothesis update requires an evidence anchor", model)
        anchor_time = min(artifact.clocks.effective_start for artifact in artifacts)
        elapsed = _hours_between(spec.as_known_at, anchor_time)
        # The public record supplies ordered sequential likelihoods but no
        # response timestamps.  The closed v1 convention assigns consecutive
        # one-hour stages from the evidence anchor.  This is explicit in both
        # assumptions and witness rather than inferred from a query identifier.
        if elapsed < 1.0:
            field = "pre_treatment_phenotype_likelihood"
        elif elapsed < 2.0:
            field = "P_response_after_antipyretic"
        else:
            field = "P_mechanism_response_after_antibiotic"
        likelihood = model.compiled[field]
        weights = {key: model.compiled["prior"][key] * likelihood[key] for key in model.compiled["prior"]}
        normalizer = sum(weights.values())
        if normalizer <= 0.0:
            return self._insufficient("query", "evidence has zero marginal probability", model)
        posterior = {key: value / normalizer for key, value in weights.items()}
        value: dict[str, Any] = {"distribution": posterior}
        if "infection" in posterior:
            value["infection_probability"] = posterior["infection"]
        return self._emit(
            status=ResultStatus.OK,
            operation="query",
            model=model,
            value=value,
            value_kind="hypothesis_posterior",
            epistemic="posterior",
            identification="identified",
            computation="exact",
            assumptions=["sequential_likelihood_default_offsets_hours=[0,1,2]"],
            roots=[artifact.source_id for artifact in artifacts],
            native_witness={"query_kind": spec.kind.value, "likelihood_field": field, "elapsed_hours": elapsed, "operator": "finite_bayes"},
        )

    def _open_path(self, compiled: Mapping[str, Any], end: float) -> tuple[list[float], list[list[float]]]:
        p = compiled["parameters"]
        initial = compiled["initial"]
        infusion = compiled["input"]
        renal = initial["renal_capacity"]

        def rhs(t: float, y: Sequence[float]) -> Sequence[float]:
            burden, amount = y
            rate = infusion["rate"] if infusion["start"] <= t < infusion["end"] else 0.0
            clearance = p["CL0"] * renal * amount / (p["Km"] + amount) if amount > 0.0 else 0.0
            efficacy = p["Emax"] * amount / (p["EC50"] + amount) if amount > 0.0 else 0.0
            db = p["r_burden"] * burden * (1.0 - burden) - efficacy * burden
            da = rate - clearance
            return [db, da]

        return _rk4(
            rhs,
            [initial["burden"], initial["drug_amount"]],
            end,
            boundaries=[infusion["start"], infusion["end"]],
        )

    def _query_open_ode(self, model: _ModelRecord, spec: QuerySpec) -> CapabilityResult:
        if spec.kind is not QueryKind.FORECAST or spec.target != "burden":
            return self._unsupported("query", f"typed open ODE supports FORECAST burden, not {spec.kind.value}/{spec.target}", model)
        end = max(model.compiled["query_hours"])
        ts, ys = self._open_path(model.compiled, end)
        p = model.compiled["parameters"]
        renal = model.compiled["initial"]["renal_capacity"]
        rows = []
        for hour, (burden, amount) in zip(model.compiled["query_hours"], _sample(ts, ys, model.compiled["query_hours"])):
            toxicity = (amount * amount / (p["Tmax"] ** 2 + amount * amount)) * (1.0 - renal)
            rows.append({"hour": hour, "burden": burden, "drug_amount": amount, "toxicity": toxicity})
        return self._emit(
            status=ResultStatus.OK,
            operation="query",
            model=model,
            value={"trajectory": rows, "used_ports": list(model.compiled["ports"]), "interaction_required": True},
            value_kind="composed_trajectory",
            identification="identified",
            computation="converged",
            native_witness={"query_kind": spec.kind.value, "algorithm": INTEGRATOR_VERSION, "explicit_interaction": True},
            diagnostics={"step_hours": 1.0 / 240.0, "integration_end_hour": end},
        )

    def _query_composition(self, model: _ModelRecord, spec: QuerySpec) -> CapabilityResult:
        if spec.kind is not QueryKind.CHECK_INVARIANT or spec.target != "composition_result":
            return self._unsupported("query", f"composition probe supports CHECK_INVARIANT composition_result, not {spec.kind.value}/{spec.target}", model)
        names = sorted(model.compiled["modules"])
        total = model.compiled["input"] + sum(model.compiled["modules"][name] for name in names)
        if len(names) == 1:
            left = right = total
        else:
            midpoint = max(1, len(names) // 2)
            left = model.compiled["input"] + sum(model.compiled["modules"][name] for name in names[:midpoint]) + sum(model.compiled["modules"][name] for name in names[midpoint:])
            right = model.compiled["input"] + sum(model.compiled["modules"][name] for name in reversed(names))
        return self._emit(
            status=ResultStatus.OK,
            operation="query",
            model=model,
            value={"result": total, "left_bracket": left, "right_bracket": right, "used_modules": names},
            value_kind="composition_invariant",
            computation="exact",
            native_witness={"query_kind": spec.kind.value, "law": "associative_parallel_sum", "registration_order_independent": True},
        )

    def _query_feedback(self, model: _ModelRecord, spec: QuerySpec) -> CapabilityResult:
        if spec.target == "contraction" and spec.kind is QueryKind.CHECK_INVARIANT:
            x = 0.0
            iterations = 0
            residual = math.inf
            while iterations < 1000:
                next_x = model.compiled["a"] * x + model.compiled["b"]
                iterations += 1
                residual = abs(next_x - x)
                x = next_x
                if residual < 1e-12:
                    break
            if residual >= 1e-12:
                return self._emit(
                    status=ResultStatus.NUMERICAL_FAILURE,
                    operation="query",
                    model=model,
                    capability="native",
                    computation="not_converged",
                    diagnostics={"reason": "fixed-point iteration did not converge", "iterations": iterations, "residual": residual},
                )
            return self._emit(
                status=ResultStatus.OK,
                operation="query",
                model=model,
                value={"status": "unique", "value": x, "iterations": iterations},
                value_kind="fixed_point",
                computation="converged",
                native_witness={"query_kind": spec.kind.value, "contraction_factor": model.compiled["a"]},
                diagnostics={"iterations": iterations, "residual": residual},
            )
        if spec.target == "rootless_support" and spec.kind is QueryKind.REACHABILITY:
            return self._emit(
                status=ResultStatus.OK,
                operation="query",
                model=model,
                value={"claims": [], "rejected_cycle": [f"{target}<-{source}" for target, source in model.compiled["edges"]]},
                value_kind="grounded_support",
                epistemic="insufficient",
                computation="exact",
                roots=[],
                native_witness={"query_kind": spec.kind.value, "groundedness_required": True, "rootless_cycle_rejected": True},
            )
        if spec.target == "no_solution" and spec.kind is QueryKind.CHECK_INVARIANT:
            return self._emit(
                status=ResultStatus.OK,
                operation="query",
                model=model,
                value={"status": "no_solution"},
                value_kind="solution_classification",
                computation="no_solution",
                native_witness={"query_kind": spec.kind.value, "symbolic_reduction": f"0={model.compiled['no_shift']}"},
                diagnostics={"reason": "identity plus nonzero shift is inconsistent"},
            )
        if spec.target == "non_unique" and spec.kind is QueryKind.CHECK_INVARIANT:
            return self._emit(
                status=ResultStatus.OK,
                operation="query",
                model=model,
                value={"status": "multiple_solutions"},
                value_kind="solution_classification",
                computation="multiple_solutions",
                native_witness={"query_kind": spec.kind.value, "symbolic_reduction": "0=0"},
                diagnostics={"reason": "identity imposes no constraint"},
            )
        return self._unsupported("query", f"feedback model does not support {spec.kind.value}/{spec.target}", model)

    def explain(self, result_id: str) -> CapabilityResult:
        record = self._result_records.get(result_id)
        if record is None:
            return self._insufficient("explain", f"unknown result_id: {result_id}")
        return self._emit(
            status=ResultStatus.OK,
            operation="explain",
            value={"explained_result_id": result_id, **copy.deepcopy(record)},
            value_kind="execution_witness",
            roots=record["evidence_roots"],
            native_witness={"explanation_is_recorded_receipt": True},
        )

    def clean_rebuild(self) -> "ExperimentalModelSubkernel":
        rebuilt = ExperimentalModelSubkernel(track=self.track)
        for record in self._models.values():
            rebuilt.register_module(
                {"module_id": record.module_id, "family": record.family, "public_model": copy.deepcopy(record.public_model)}
            )
        for source_id, artifact in self._artifacts.items():
            if source_id not in self._retracted:
                rebuilt.ingest(copy.deepcopy(artifact))
        return rebuilt


__all__ = ["ExperimentalModelSubkernel", "MODEL_SCHEMA_VERSION", "ModelSchemaError", "SUBKERNEL_VERSION"]
