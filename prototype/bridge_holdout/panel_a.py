"""Independent public-model executor for bridge holdout panel A.

The module is deliberately self contained.  Its only semantic inputs are the
``public_model`` and typed ``query`` mappings passed to :func:`execute`; it does
not load workload files, hidden fixtures, expected values, or another model
executor.  The supported operator vocabulary is the frozen E01--E06 public
protocol.

Numerical systems use deterministic fourth-order Runge--Kutta integration with
a maximum step of 1/600 hour.  Finite models use exact enumeration/Bayes
normalisation.  Results include both an operator trace and a solver trace so a
caller can audit which semantics produced every value.
"""

from __future__ import annotations

import ast
import math
import random
import re
from collections.abc import Mapping, Sequence
from typing import Any, Callable


__all__ = ["PanelAError", "execute"]

_MAX_STEP_HOURS = 1.0 / 600.0
_ABS_EPS = 1e-12


class PanelAError(ValueError):
    """Raised when the public model or typed query violates the closed API."""


def _finite_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PanelAError(f"{path} must be a finite number")
    answer = float(value)
    if not math.isfinite(answer):
        raise PanelAError(f"{path} must be a finite number")
    return answer


def _mapping(value: Any, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PanelAError(f"{path} must be a mapping")
    return value


def _sequence(value: Any, path: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PanelAError(f"{path} must be a sequence")
    return value


def _normalise(weights: Mapping[Any, float], *, path: str) -> dict[Any, float]:
    checked = {key: _finite_number(value, f"{path}.{key}") for key, value in weights.items()}
    if any(value < 0.0 for value in checked.values()):
        raise PanelAError(f"{path} contains a negative weight")
    total = math.fsum(checked.values())
    if total <= 0.0:
        raise PanelAError(f"{path} has zero total mass")
    return {key: value / total for key, value in checked.items()}


def _rk4_step(
    derivative: Callable[[float, tuple[float, ...]], tuple[float, ...]],
    t: float,
    state: tuple[float, ...],
    h: float,
) -> tuple[float, ...]:
    k1 = derivative(t, state)
    s2 = tuple(y + 0.5 * h * k for y, k in zip(state, k1))
    k2 = derivative(t + 0.5 * h, s2)
    s3 = tuple(y + 0.5 * h * k for y, k in zip(state, k2))
    k3 = derivative(t + 0.5 * h, s3)
    s4 = tuple(y + h * k for y, k in zip(state, k3))
    # Evaluate the last stage on the left limit.  The integrator splits at all
    # declared discontinuities; using the left limit prevents a step/pulse's
    # right-hand value from contaminating the interval that ends at its jump.
    k4 = derivative(math.nextafter(t + h, t), s4)
    return tuple(
        y + h * (a + 2.0 * b + 2.0 * c + d) / 6.0
        for y, a, b, c, d in zip(state, k1, k2, k3, k4)
    )


def _integrate_samples(
    derivative: Callable[[float, tuple[float, ...]], tuple[float, ...]],
    initial: Sequence[float],
    sample_hours: Sequence[float],
    *,
    discontinuities: Sequence[float] = (),
    max_step: float = _MAX_STEP_HOURS,
) -> tuple[dict[float, tuple[float, ...]], int]:
    hours = sorted({_finite_number(hour, "sample_hour") for hour in sample_hours})
    if not hours or hours[0] < 0.0:
        raise PanelAError("sample hours must be nonempty and nonnegative")
    cuts = sorted(
        {
            _finite_number(point, "discontinuity")
            for point in discontinuities
            if 0.0 < float(point) < hours[-1]
        }
    )
    targets = sorted(set(hours + cuts))
    t = 0.0
    state = tuple(_finite_number(value, "initial_state") for value in initial)
    snapshots: dict[float, tuple[float, ...]] = {}
    steps = 0
    if 0.0 in hours:
        snapshots[0.0] = state
    for target in targets:
        while t < target - 1e-14:
            h = min(max_step, target - t)
            state = _rk4_step(derivative, t, state, h)
            if not all(math.isfinite(value) for value in state):
                raise PanelAError("numerical integration produced a non-finite state")
            t += h
            steps += 1
        t = target
        if target in hours:
            snapshots[target] = state
    return snapshots, steps


def _requested(query: Mapping[str, Any], available: Mapping[str, Any]) -> dict[str, Any]:
    outputs = _sequence(query.get("outputs", tuple(available)), "query.outputs")
    names: list[str] = []
    for output in outputs:
        if not isinstance(output, str) or not output:
            raise PanelAError("query.outputs entries must be nonempty strings")
        if output not in available:
            raise PanelAError(f"unsupported output {output!r}")
        if output not in names:
            names.append(output)
    return {name: available[name] for name in names}


def _base_result(
    operator: str,
    value: Mapping[str, Any],
    operator_trace: Sequence[Mapping[str, Any]],
    solver: Mapping[str, Any],
    **diagnostics: Any,
) -> dict[str, Any]:
    return {
        "operator": operator,
        "value": dict(value),
        "trace": {
            "operator": [dict(item) for item in operator_trace],
            "solver": dict(solver),
        },
        "diagnostics": {
            "implementation": "panel_a",
            "deterministic": True,
            "finite": True,
            **diagnostics,
        },
    }


def _control_at(hour: float, intervals: Sequence[Any]) -> float:
    for raw in intervals:
        pair = _sequence(raw, "control.performed_intervals[]")
        if len(pair) != 2:
            raise PanelAError("each control interval must have two endpoints")
        start = _finite_number(pair[0], "control.start")
        end = _finite_number(pair[1], "control.end")
        if end < start:
            raise PanelAError("control interval end precedes start")
        if start <= hour < end:
            return 1.0
    return 0.0


_CONTROLLED_DYNAMICS = re.compile(
    r"^\s*dS_dt\s*=\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*\*\s*\(\s*1\s*-\s*S\s*\)"
    r"\s*-\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*\*\s*U\s*\*\s*S\s*$"
)
_CONTROLLED_OBSERVATION = re.compile(
    r"^\s*MAP\s*=\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*"
    r"([+-])\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*\*\s*S\s*"
    r"([+-])\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*\*\s*U\s*"
    r"\+\s*Normal\s*\(\s*0\s*,\s*([+]?(?:\d+(?:\.\d*)?|\.\d+))\s*\)\s*$"
)


def _execute_controlled(public_model: Mapping[str, Any], query: Mapping[str, Any]) -> dict[str, Any]:
    dynamics_match = _CONTROLLED_DYNAMICS.fullmatch(str(public_model.get("dynamics", "")))
    observation_match = _CONTROLLED_OBSERVATION.fullmatch(str(public_model.get("observation", "")))
    if dynamics_match is None or observation_match is None:
        raise PanelAError("controlled_state_space equation is outside the closed grammar")
    recovery, treatment = (float(item) for item in dynamics_match.groups())
    base = float(observation_match.group(1))
    state_coef = float(observation_match.group(3)) * (-1.0 if observation_match.group(2) == "-" else 1.0)
    control_coef = float(observation_match.group(5)) * (-1.0 if observation_match.group(4) == "-" else 1.0)
    noise_sd = float(observation_match.group(6))

    state = _mapping(public_model.get("state"), "public_model.state")
    prior = _mapping(state.get("S0_prior"), "public_model.state.S0_prior")
    if prior.get("kind") != "beta":
        raise PanelAError("controlled_state_space requires a beta S0 prior")
    alpha = _finite_number(prior.get("alpha"), "S0_prior.alpha")
    beta = _finite_number(prior.get("beta"), "S0_prior.beta")
    if alpha <= 0.0 or beta <= 0.0:
        raise PanelAError("beta prior parameters must be positive")
    s0 = alpha / (alpha + beta)
    bounds = _sequence(state.get("bounds"), "state.bounds")
    if len(bounds) != 2:
        raise PanelAError("state.bounds must have length two")
    lower, upper = (_finite_number(item, "state.bounds[]") for item in bounds)
    if not lower <= s0 <= upper:
        raise PanelAError("S0 prior mean is outside state bounds")

    control = _mapping(public_model.get("control"), "public_model.control")
    intervals = _sequence(control.get("performed_intervals", ()), "control.performed_intervals")
    observation_hours = [
        _finite_number(item, "observation_hours[]")
        for item in _sequence(public_model.get("observation_hours"), "observation_hours")
    ]
    query_hours = [
        _finite_number(item, "query_hours[]")
        for item in _sequence(public_model.get("query_hours"), "query_hours")
    ]
    all_hours = sorted(set(observation_hours + query_hours))
    discontinuities = [float(endpoint) for interval in intervals for endpoint in interval]

    def derivative(hour: float, values: tuple[float, ...]) -> tuple[float, ...]:
        s_value = values[0]
        u_value = _control_at(hour, intervals)
        return (recovery * (1.0 - s_value) - treatment * u_value * s_value,)

    snapshots, steps = _integrate_samples(
        derivative,
        (s0,),
        all_hours,
        discontinuities=discontinuities,
    )
    state_trajectory = [
        {"hour": hour, "S": snapshots[hour][0], "U": _control_at(hour, intervals)}
        for hour in query_hours
    ]
    observations = []
    observation_rng = random.Random(int(_finite_number(public_model.get("seed"), "seed")))
    for hour in observation_hours:
        s_value = snapshots[hour][0]
        u_value = _control_at(hour, intervals)
        map_mean = base + state_coef * s_value + control_coef * u_value
        observations.append(
            {
                "hour": hour,
                "S": s_value,
                "U": u_value,
                "MAP": observation_rng.gauss(map_mean, noise_sd),
                "MAP_mean": map_mean,
                "MAP_sd": noise_sd,
            }
        )
    contrast_hour = _finite_number(query.get("contrast_hour", 9.0), "query.contrast_hour")
    if contrast_hour not in snapshots:
        extra, extra_steps = _integrate_samples(
            derivative, (s0,), (contrast_hour,), discontinuities=discontinuities
        )
        snapshots.update(extra)
        steps += extra_steps
    contrast_state = snapshots[contrast_hour][0]
    natural_map = base + state_coef * contrast_state
    supported_map = natural_map + control_coef
    stop_hour = max((float(interval[1]) for interval in intervals), default=0.0)
    stop_targets = sorted({stop_hour, max(query_hours)})
    stop_snapshots, stop_steps = _integrate_samples(
        derivative, (s0,), stop_targets, discontinuities=discontinuities
    )
    steps += stop_steps
    stop_delta = stop_snapshots[stop_targets[-1]][0] - stop_snapshots[stop_targets[0]][0]
    stop_direction = "S_increases_after_stop" if stop_delta > 0.0 else "S_decreases_after_stop"

    available = {
        "state_trajectory": state_trajectory,
        "observations": observations,
        "natural_map_at_9": natural_map,
        "supported_map_at_9": supported_map,
        "stop_support_direction": stop_direction,
    }
    return _base_result(
        "controlled_state_space",
        _requested(query, available),
        (
            {"step": "prior_moment", "distribution": "beta", "mean": s0},
            {"step": "transition", "control_policy": "performed_intervals"},
            {"step": "observation_projection", "noise": "zero-mean Gaussian"},
            {"step": "support_channel_contrast", "hour": contrast_hour},
            {
                "step": "stop_support_direction",
                "from_hour": stop_targets[0],
                "to_hour": stop_targets[-1],
                "delta_S": stop_delta,
                "direction": stop_direction,
            },
        ),
        {
            "method": "RK4",
            "max_step_hours": _MAX_STEP_HOURS,
            "steps": steps,
            "discontinuities": sorted(set(discontinuities)),
        },
        uncertainty={"S0": "beta prior mean propagation", "MAP_sd": noise_sd},
    )


def _bad_probability(model: Mapping[str, Any], severity: str, treatment: int) -> float:
    table = _mapping(model.get("P_bad"), "public_model.P_bad")
    key = f"{severity}_T{treatment}"
    probability = _finite_number(table.get(key), f"P_bad.{key}")
    if not 0.0 <= probability <= 1.0:
        raise PanelAError(f"P_bad.{key} is not a probability")
    return probability


def _execute_condition_do(public_model: Mapping[str, Any], query: Mapping[str, Any]) -> dict[str, Any]:
    p_severe = _finite_number(public_model.get("P_severe"), "P_severe")
    p_t_given_severe = _finite_number(
        public_model.get("P_treated_given_severe"), "P_treated_given_severe"
    )
    p_t_given_mild = _finite_number(
        public_model.get("P_treated_given_mild"), "P_treated_given_mild"
    )
    if any(not 0.0 <= value <= 1.0 for value in (p_severe, p_t_given_severe, p_t_given_mild)):
        raise PanelAError("finite SCM probabilities must lie in [0,1]")
    severity_prior = {"severe": p_severe, "mild": 1.0 - p_severe}
    propensity = {"severe": p_t_given_severe, "mild": p_t_given_mild}

    conditional: dict[int, float] = {}
    interventional: dict[int, float] = {}
    posterior_trace: dict[str, dict[str, float]] = {}
    for treatment in (0, 1):
        likelihood = {
            severity: (propensity[severity] if treatment else 1.0 - propensity[severity])
            for severity in severity_prior
        }
        posterior = _normalise(
            {
                severity: severity_prior[severity] * likelihood[severity]
                for severity in severity_prior
            },
            path=f"P(severity,T={treatment})",
        )
        posterior_trace[f"T{treatment}"] = posterior
        conditional[treatment] = math.fsum(
            posterior[severity] * _bad_probability(public_model, severity, treatment)
            for severity in severity_prior
        )
        interventional[treatment] = math.fsum(
            severity_prior[severity] * _bad_probability(public_model, severity, treatment)
            for severity in severity_prior
        )
    available = {
        "P_bad_given_T1": conditional[1],
        "P_bad_given_T0": conditional[0],
        "P_bad_given_do_T1": interventional[1],
        "P_bad_given_do_T0": interventional[0],
    }
    return _base_result(
        "condition_and_population_do",
        _requested(query, available),
        (
            {"step": "condition", "mechanism": "Bayes on treatment propensity", "posterior": posterior_trace},
            {"step": "do", "mechanism": "replace T mechanism; retain severity prior"},
        ),
        {"method": "exact_finite_enumeration", "states": 2, "steps": 4},
        identification={"backdoor_variable": "severity", "assumption": "public SCM is causal"},
    )


_ALLOWED_BINOPS: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
}
_ALLOWED_UNARY: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: lambda value: value,
    ast.USub: lambda value: -value,
}


def _safe_expression(expression: str, variables: Mapping[str, float]) -> float:
    try:
        parsed = ast.parse(expression.replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise PanelAError("invalid structural expression") from exc

    def visit(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in variables:
            return _finite_number(variables[node.id], f"expression variable {node.id}")
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
            return _ALLOWED_BINOPS[type(node.op)](visit(node.left), visit(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
            return _ALLOWED_UNARY[type(node.op)](visit(node.operand))
        raise PanelAError("structural expression is outside the arithmetic grammar")

    answer = visit(parsed)
    if not math.isfinite(answer):
        raise PanelAError("structural expression produced a non-finite value")
    return answer


def _structural_rhs(model: Mapping[str, Any]) -> str:
    equation = str(model.get("structural_equation", ""))
    if "=" not in equation:
        raise PanelAError("structural_equation must contain '='")
    lhs, rhs = equation.split("=", 1)
    if lhs.strip() != "Y":
        raise PanelAError("only a Y structural equation is supported")
    return rhs.strip()


def _execute_aap(public_model: Mapping[str, Any], query: Mapping[str, Any]) -> dict[str, Any]:
    raw_r = _mapping(public_model.get("R"), "public_model.R")
    values = list(_sequence(raw_r.get("values"), "R.values"))
    probabilities = list(_sequence(raw_r.get("probabilities"), "R.probabilities"))
    if len(values) != len(probabilities) or not values:
        raise PanelAError("R values/probabilities must be nonempty and aligned")
    prior = _normalise(
        {
            _finite_number(value, "R.values[]"): _finite_number(probability, "R.probabilities[]")
            for value, probability in zip(values, probabilities)
        },
        path="R.prior",
    )
    factual = _mapping(query.get("factual_evidence", public_model.get("factual_evidence")), "factual_evidence")
    factual_t = _finite_number(factual.get("T"), "factual_evidence.T")
    factual_y = _finite_number(factual.get("Y"), "factual_evidence.Y")
    intervention = _mapping(query.get("intervention"), "query.intervention")
    if "T" not in intervention:
        raise PanelAError("same_patient_aap requires intervention.T")
    counterfactual_t = _finite_number(intervention["T"], "intervention.T")
    if public_model.get("cross_world_policy") != "share_abduced_exogenous":
        raise PanelAError("same_patient_aap requires share_abduced_exogenous")
    rhs = _structural_rhs(public_model)
    likelihood: dict[float, float] = {}
    for r_value in prior:
        predicted = _safe_expression(rhs, {"R": r_value, "T": factual_t})
        likelihood[r_value] = 1.0 if math.isclose(predicted, factual_y, abs_tol=_ABS_EPS) else 0.0
    posterior = _normalise(
        {r_value: prior[r_value] * likelihood[r_value] for r_value in prior},
        path="AAP.abduction",
    )
    individual_mean = math.fsum(
        probability * _safe_expression(rhs, {"R": r_value, "T": counterfactual_t})
        for r_value, probability in posterior.items()
    )
    population_mean = math.fsum(
        probability * _safe_expression(rhs, {"R": r_value, "T": counterfactual_t})
        for r_value, probability in prior.items()
    )
    posterior_r1 = posterior.get(1.0, 0.0)
    available = {
        "posterior_R1": posterior_r1,
        "individual_counterfactual_Y_T0": individual_mean,
        "population_do_mean_Y_T0": population_mean,
    }
    return _base_result(
        "same_patient_aap",
        _requested(query, available),
        (
            {"step": "abduction", "posterior_R": {str(key): value for key, value in posterior.items()}},
            {"step": "action", "replace": "T mechanism", "value": counterfactual_t},
            {"step": "prediction", "world_policy": "share_abduced_exogenous"},
            {"step": "population_do", "world_policy": "population prior"},
        ),
        {"method": "exact_finite_enumeration", "states": len(prior), "steps": len(prior) * 2},
        cross_world_policy="share_abduced_exogenous",
    )


def _execute_nonlinear(public_model: Mapping[str, Any], query: Mapping[str, Any]) -> dict[str, Any]:
    expected_equations = {
        "dB_dt = r*B*(1-B/K) - k_abx*A*B",
        "I = B^hill_h/(hill_K^hill_h+B^hill_h)",
        "dC_dt = (I-C)/tau_hours",
    }
    equations = {str(item) for item in _sequence(public_model.get("dynamics"), "dynamics")}
    if equations != expected_equations:
        raise PanelAError("nonlinear_state_space equation set is outside the closed grammar")
    initial = _mapping(public_model.get("initial"), "initial")
    parameters = _mapping(public_model.get("parameters"), "parameters")
    pulse = _mapping(public_model.get("pulse"), "pulse")
    b0 = _finite_number(initial.get("B"), "initial.B")
    c0 = _finite_number(initial.get("C"), "initial.C")
    r = _finite_number(parameters.get("r"), "parameters.r")
    carrying = _finite_number(parameters.get("K"), "parameters.K")
    k_abx = _finite_number(parameters.get("k_abx"), "parameters.k_abx")
    hill_h = _finite_number(parameters.get("hill_h"), "parameters.hill_h")
    hill_k = _finite_number(parameters.get("hill_K"), "parameters.hill_K")
    tau = _finite_number(parameters.get("tau_hours"), "parameters.tau_hours")
    amplitude = _finite_number(pulse.get("A"), "pulse.A")
    pulse_start = _finite_number(pulse.get("start_hour"), "pulse.start_hour")
    pulse_end = _finite_number(pulse.get("end_hour"), "pulse.end_hour")
    if carrying <= 0.0 or hill_k <= 0.0 or tau <= 0.0 or pulse_end < pulse_start:
        raise PanelAError("nonlinear model has invalid positive/range parameters")

    def derived(values: tuple[float, ...]) -> float:
        b_value = max(0.0, values[0])
        numerator = b_value**hill_h
        return numerator / (hill_k**hill_h + numerator)

    def derivative(hour: float, values: tuple[float, ...]) -> tuple[float, ...]:
        b_value, c_value = values
        a_value = amplitude if pulse_start <= hour < pulse_end else 0.0
        inflammation = derived(values)
        return (
            r * b_value * (1.0 - b_value / carrying) - k_abx * a_value * b_value,
            (inflammation - c_value) / tau,
        )

    query_hours = [
        _finite_number(item, "query_hours[]")
        for item in _sequence(public_model.get("query_hours"), "query_hours")
    ]
    if not query_hours:
        raise PanelAError("query_hours cannot be empty")
    dense_hours = [index * _MAX_STEP_HOURS for index in range(int(math.ceil(max(query_hours) / _MAX_STEP_HOURS)) + 1)]
    if dense_hours[-1] < max(query_hours):
        dense_hours.append(max(query_hours))
    all_hours = sorted(set(dense_hours + query_hours + [7.0, 16.0]))
    snapshots, steps = _integrate_samples(
        derivative,
        (b0, c0),
        all_hours,
        discontinuities=(pulse_start, pulse_end),
    )
    trajectory = []
    for hour in query_hours:
        b_value, c_value = snapshots[hour]
        trajectory.append({"hour": hour, "B": b_value, "I": derived((b_value, c_value)), "C": c_value})

    # The dense grid brackets the lagged C maximum.  Parabolic interpolation
    # removes grid quantisation while remaining independent of an oracle.
    peak_index = max(range(len(dense_hours)), key=lambda index: snapshots[dense_hours[index]][1])
    peak_hour = dense_hours[peak_index]
    if 0 < peak_index < len(dense_hours) - 1:
        left, middle, right = (dense_hours[peak_index + offset] for offset in (-1, 0, 1))
        y0, y1, y2 = (snapshots[hour][1] for hour in (left, middle, right))
        denominator = y0 - 2.0 * y1 + y2
        if abs(denominator) > 1e-24:
            peak_hour = middle + 0.5 * (y0 - y2) / denominator * (middle - left)

    derivative7 = derivative(7.0, snapshots[7.0])[1]
    derivative16 = derivative(16.0, snapshots[16.0])[1]
    phase7 = "rising" if derivative7 > 0.0 else "falling"
    phase16 = "rising" if derivative16 > 0.0 else "falling"
    available = {
        "trajectory": trajectory,
        "C_peak_hour": peak_hour,
        "phase_at_7": phase7,
        "phase_at_16": phase16,
    }
    return _base_result(
        "nonlinear_state_space",
        _requested(query, available),
        (
            {"step": "initialise", "state": {"B": b0, "C": c0}},
            {"step": "pulse_transition", "start_hour": pulse_start, "end_hour": pulse_end},
            {"step": "lagged_observation", "state": "C", "driver": "Hill(B)"},
            {
                "step": "phase_and_peak",
                "method": "derivative sign and parabolic refinement",
                "dC_dt_at_7": derivative7,
                "dC_dt_at_16": derivative16,
                "phase_at_7": phase7,
                "phase_at_16": phase16,
            },
        ),
        {
            "method": "RK4",
            "max_step_hours": _MAX_STEP_HOURS,
            "steps": steps,
            "discontinuities": [pulse_start, pulse_end],
        },
        approximation="deterministic dense integration; no observation conditioning requested",
    )


def _bayes_update(prior: Mapping[str, float], likelihood: Mapping[str, Any], path: str) -> dict[str, float]:
    if set(prior) != set(likelihood):
        raise PanelAError(f"{path} hypotheses do not match prior")
    return _normalise(
        {
            hypothesis: probability * _finite_number(likelihood[hypothesis], f"{path}.{hypothesis}")
            for hypothesis, probability in prior.items()
        },
        path=path,
    )


def _execute_hypothesis(public_model: Mapping[str, Any], query: Mapping[str, Any]) -> dict[str, Any]:
    prior_raw = _mapping(public_model.get("prior"), "prior")
    prior = _normalise(
        {str(key): _finite_number(value, f"prior.{key}") for key, value in prior_raw.items()},
        path="prior",
    )
    phenotype = _mapping(
        public_model.get("pre_treatment_phenotype_likelihood"),
        "pre_treatment_phenotype_likelihood",
    )
    antipyretic = _mapping(
        public_model.get("P_response_after_antipyretic"),
        "P_response_after_antipyretic",
    )
    antibiotic = _mapping(
        public_model.get("P_mechanism_response_after_antibiotic"),
        "P_mechanism_response_after_antibiotic",
    )
    pre = _bayes_update(prior, phenotype, "phenotype")
    after_antipyretic = _bayes_update(pre, antipyretic, "antipyretic_response")
    after_antibiotic = _bayes_update(after_antipyretic, antibiotic, "antibiotic_response")
    available = {
        "pre_treatment": pre,
        "after_antipyretic": after_antipyretic,
        "after_antibiotic_response": after_antibiotic,
    }
    return _base_result(
        "finite_hypothesis_update",
        _requested(query, available),
        (
            {"step": "prior", "weights": prior},
            {"step": "phenotype_update", "weights": pre},
            {"step": "antipyretic_update", "weights": after_antipyretic},
            {"step": "antibiotic_mechanism_update", "weights": after_antibiotic},
        ),
        {"method": "exact_bayes_normalisation", "states": len(prior), "steps": 3},
        evidence_order=["phenotype", "antipyretic_response", "antibiotic_mechanism_response"],
    )


def _execute_open_ode(public_model: Mapping[str, Any], query: Mapping[str, Any]) -> dict[str, Any]:
    required_equations = {
        "clearance = CL0*renal*amount/(Km+amount)",
        "efficacy = Emax*amount/(EC50+amount)",
        "toxicity = (amount^2/(Tmax^2+amount^2))*(1-renal)",
        "dBurden_dt = r_burden*burden*(1-burden)-efficacy*burden",
    }
    equations = {
        str(item) for item in _sequence(public_model.get("interaction_equations"), "interaction_equations")
    }
    if equations != required_equations:
        raise PanelAError("typed_open_ode interaction equations are incomplete or outside the closed grammar")
    required_ports = {
        "A.drug_effect<-I.efficacy",
        "I.burden<-A.burden",
        "I.amount<-C.amount",
        "I.renal<-B.capacity",
        "C.clearance<-I.clearance",
    }
    ports = {str(item) for item in _sequence(public_model.get("ports"), "ports")}
    if ports != required_ports:
        raise PanelAError("typed_open_ode port wiring does not provide the explicit interaction")
    initial = _mapping(public_model.get("initial"), "initial")
    parameters = _mapping(public_model.get("parameters"), "parameters")
    input_spec = _mapping(public_model.get("input"), "input")
    burden0 = _finite_number(initial.get("burden"), "initial.burden")
    amount0 = _finite_number(initial.get("drug_amount"), "initial.drug_amount")
    renal = _finite_number(query.get("renal_capacity", initial.get("renal_capacity")), "renal_capacity")
    r_burden = _finite_number(parameters.get("r_burden"), "parameters.r_burden")
    cl0 = _finite_number(parameters.get("CL0"), "parameters.CL0")
    km = _finite_number(parameters.get("Km"), "parameters.Km")
    emax = _finite_number(parameters.get("Emax"), "parameters.Emax")
    ec50 = _finite_number(parameters.get("EC50"), "parameters.EC50")
    tmax = _finite_number(parameters.get("Tmax"), "parameters.Tmax")
    infusion = _finite_number(input_spec.get("infusion_rate"), "input.infusion_rate")
    infusion_start = _finite_number(input_spec.get("start_hour"), "input.start_hour")
    infusion_end = _finite_number(input_spec.get("end_hour"), "input.end_hour")
    if any(value <= 0.0 for value in (km, ec50, tmax)) or not 0.0 <= renal <= 1.0:
        raise PanelAError("typed_open_ode has invalid scale or renal capacity")

    def channels(values: tuple[float, ...]) -> tuple[float, float, float]:
        _, amount = values
        clearance = cl0 * renal * amount / (km + amount)
        efficacy = emax * amount / (ec50 + amount)
        toxicity = (amount * amount / (tmax * tmax + amount * amount)) * (1.0 - renal)
        return clearance, efficacy, toxicity

    def derivative(hour: float, values: tuple[float, ...]) -> tuple[float, ...]:
        burden, amount = values
        clearance, efficacy, _ = channels(values)
        current_infusion = infusion if infusion_start <= hour < infusion_end else 0.0
        return (
            r_burden * burden * (1.0 - burden) - efficacy * burden,
            current_infusion - clearance,
        )

    query_hours = [
        _finite_number(item, "query_hours[]")
        for item in _sequence(public_model.get("query_hours"), "query_hours")
    ]
    snapshots, steps = _integrate_samples(
        derivative,
        (burden0, amount0),
        query_hours,
        discontinuities=(infusion_start, infusion_end),
    )
    trajectory = []
    for hour in query_hours:
        burden, amount = snapshots[hour]
        clearance, efficacy, toxicity = channels((burden, amount))
        trajectory.append(
            {
                "hour": hour,
                "burden": burden,
                "drug_amount": amount,
                "clearance": clearance,
                "efficacy": efficacy,
                "toxicity": toxicity,
            }
        )
    available = {
        "renal_capacity": renal,
        "trajectory": trajectory,
        "interaction_required": True,
    }
    return _base_result(
        "typed_open_ode",
        _requested(query, available),
        (
            {"step": "validate_typed_ports", "ports": sorted(ports)},
            {"step": "resolve_interaction", "channels": ["clearance", "efficacy", "toxicity"]},
            {"step": "integrate", "state": ["burden", "drug_amount"], "renal_capacity": renal},
        ),
        {
            "method": "RK4",
            "max_step_hours": _MAX_STEP_HOURS,
            "steps": steps,
            "discontinuities": [infusion_start, infusion_end],
        },
        composition="A+B+C+I with explicit typed interaction",
    )


_DISPATCH: dict[str, tuple[str, Callable[[Mapping[str, Any], Mapping[str, Any]], dict[str, Any]]]] = {
    "controlled_state_space": ("controlled_state_space", _execute_controlled),
    "condition_and_population_do": ("finite_scm", _execute_condition_do),
    "same_patient_aap": ("finite_scm", _execute_aap),
    "nonlinear_state_space": ("nonlinear_state_space", _execute_nonlinear),
    "finite_hypothesis_update": ("finite_hypothesis_model", _execute_hypothesis),
    "typed_open_ode": ("typed_open_ode", _execute_open_ode),
}


def execute(public_model: Mapping[str, Any], query: Mapping[str, Any]) -> Mapping[str, Any]:
    """Execute one frozen public E01--E06 operator.

    Dispatch is solely by the closed ``query.operator`` enum and is checked
    against ``public_model.model_kind``.  Query IDs and requested output values
    never influence dispatch or arithmetic.
    """

    model = _mapping(public_model, "public_model")
    typed_query = _mapping(query, "query")
    operator = typed_query.get("operator")
    if not isinstance(operator, str) or operator not in _DISPATCH:
        raise PanelAError(f"unsupported query.operator {operator!r}")
    expected_kind, implementation = _DISPATCH[operator]
    actual_kind = model.get("model_kind")
    if actual_kind != expected_kind:
        raise PanelAError(
            f"operator {operator!r} requires model_kind {expected_kind!r}, got {actual_kind!r}"
        )
    return implementation(model, typed_query)
