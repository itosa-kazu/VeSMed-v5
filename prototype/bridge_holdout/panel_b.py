"""Independent Panel B executor for the public E01--E06 bridge holdout.

This module is intentionally self contained.  It consumes only the public model
mapping and the typed query supplied to :func:`execute`; it has no dependency on
the repository's reference/oracle implementation or on the other panel.

Numerical strategy
------------------
Panel B uses deterministic adaptive step-doubled Heun integration with
Richardson extrapolation, explicit error control, and exact alignment at input
discontinuities and requested output times.  Finite SCMs and hypothesis models
are evaluated by exhaustive support enumeration and normalised probability
arithmetic.  No expected result is embedded here.
"""

from __future__ import annotations

import ast
import math
import random
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any


_DEFAULT_STEP_HOURS = 1.0 / 600.0
_OPERATORS = {
    "controlled_state_space",
    "condition_and_population_do",
    "same_patient_aap",
    "nonlinear_state_space",
    "finite_hypothesis_update",
    "typed_open_ode",
}


class PanelBError(ValueError):
    """Typed public-model/query validation failure."""


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PanelBError(f"{name} must be a finite number")
    out = float(value)
    if not math.isfinite(out):
        raise PanelBError(f"{name} must be finite")
    return out


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PanelBError(f"{name} must be a mapping")
    return value


def _sequence(value: Any, name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise PanelBError(f"{name} must be a sequence")
    return value


def _normalise(weights: Mapping[Any, float], name: str) -> dict[Any, float]:
    clean = {key: _number(value, f"{name}[{key!r}]") for key, value in weights.items()}
    if any(value < 0.0 for value in clean.values()):
        raise PanelBError(f"{name} contains a negative probability")
    total = math.fsum(clean.values())
    if total <= 0.0:
        raise PanelBError(f"{name} has zero probability mass")
    return {key: value / total for key, value in clean.items()}


_SAFE_BINARY = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
}
_SAFE_UNARY = {ast.UAdd: lambda a: a, ast.USub: lambda a: -a}


def _expression(text: str) -> Callable[[Mapping[str, float]], float]:
    """Compile the tiny arithmetic language used by the frozen public models."""

    try:
        tree = ast.parse(text.replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise PanelBError(f"invalid public arithmetic expression: {text!r}") from exc

    def evaluate(node: ast.AST, env: Mapping[str, float]) -> float:
        if isinstance(node, ast.Expression):
            return evaluate(node.body, env)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name):
            if node.id not in env:
                raise PanelBError(f"unbound public-model variable {node.id!r}")
            return _number(env[node.id], node.id)
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BINARY:
            return _SAFE_BINARY[type(node.op)](evaluate(node.left, env), evaluate(node.right, env))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARY:
            return _SAFE_UNARY[type(node.op)](evaluate(node.operand, env))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Normal":
            if len(node.args) != 2:
                raise PanelBError("Normal(mean, sd) requires two arguments")
            # Deterministic public-panel execution reports the observation mean;
            # uncertainty is retained separately in the observation rows.
            return evaluate(node.args[0], env)
        raise PanelBError(f"unsupported arithmetic syntax: {ast.dump(node, include_attributes=False)}")

    def run(env: Mapping[str, float]) -> float:
        value = float(evaluate(tree, env))
        if not math.isfinite(value):
            raise PanelBError("public-model expression produced a non-finite value")
        return value

    return run


def _assignment(text: str, name: str) -> tuple[str, Callable[[Mapping[str, float]], float]]:
    if not isinstance(text, str) or "=" not in text:
        raise PanelBError(f"{name} must be an assignment expression")
    lhs, rhs = text.split("=", 1)
    lhs = lhs.strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", lhs):
        raise PanelBError(f"invalid assignment target {lhs!r}")
    return lhs, _expression(rhs.strip())


def _heun_step(
    derivative: Callable[[float, tuple[float, ...]], tuple[float, ...]],
    time: float,
    state: tuple[float, ...],
    step: float,
) -> tuple[float, ...]:
    """One explicit trapezoid (Heun) step, evaluated left of a boundary."""

    k1 = derivative(time, state)
    terminal_time = math.nextafter(time + step, time)
    predictor = tuple(x + step * k for x, k in zip(state, k1))
    k2 = derivative(terminal_time, predictor)
    result = tuple(x + (step / 2.0) * (a + b) for x, a, b in zip(state, k1, k2))
    if not all(math.isfinite(value) for value in result):
        raise PanelBError("Heun produced a non-finite state")
    return result


def _heun_embedded(
    derivative: Callable[[float, tuple[float, ...]], tuple[float, ...]],
    time: float,
    state: tuple[float, ...],
    step: float,
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Step-doubled Heun with Richardson extrapolation and error estimate.

    The two-half-step solution and one-full-step solution differ by three
    times the leading local error.  Extrapolation cancels that term, while the
    returned estimate drives an adaptive controller independently of Panel A.
    """

    coarse = _heun_step(derivative, time, state, step)
    half = _heun_step(derivative, time, state, step / 2.0)
    fine = _heun_step(derivative, time + step / 2.0, half, step / 2.0)
    estimate = tuple((f - c) / 3.0 for f, c in zip(fine, coarse))
    extrapolated = tuple(f + e for f, e in zip(fine, estimate))
    if not all(math.isfinite(value) for value in extrapolated):
        raise PanelBError("Richardson-extrapolated Heun produced a non-finite state")
    return extrapolated, estimate


def _integrate(
    derivative: Callable[[float, tuple[float, ...]], tuple[float, ...]],
    initial: tuple[float, ...],
    output_times: Sequence[float],
    *,
    breakpoints: Sequence[float] = (),
    max_step: float = _DEFAULT_STEP_HOURS,
    absolute_tolerance: float = 1e-12,
    relative_tolerance: float = 1e-10,
) -> tuple[dict[float, tuple[float, ...]], int, list[tuple[float, tuple[float, ...]]]]:
    times = sorted({_number(value, "output time") for value in output_times})
    if not times or times[0] < 0.0:
        raise PanelBError("output times must be a non-empty, non-negative set")
    max_step = _number(max_step, "max_step")
    if max_step <= 0.0:
        raise PanelBError("max_step must be positive")

    stops = sorted({0.0, *times, *(_number(x, "breakpoint") for x in breakpoints)})
    stops = [value for value in stops if 0.0 <= value <= times[-1]]
    wanted = set(times)
    current_t = 0.0
    current = tuple(_number(value, "initial state") for value in initial)
    result: dict[float, tuple[float, ...]] = {}
    dense: list[tuple[float, tuple[float, ...]]] = [(0.0, current)]
    if 0.0 in wanted:
        result[0.0] = current
    steps = 0
    proposed_step = max_step
    for stop in stops[1:]:
        while current_t < stop - 1e-14:
            h = min(proposed_step, max_step, stop - current_t)
            candidate, error = _heun_embedded(derivative, current_t, current, h)
            error_ratio = max(
                abs(err) / (absolute_tolerance + relative_tolerance * max(abs(old), abs(new)))
                for old, new, err in zip(current, candidate, error)
            )
            if error_ratio > 1.0:
                proposed_step = max(1e-10, h * max(0.2, 0.9 * error_ratio ** (-1.0 / 3.0)))
                if proposed_step <= 1e-10 and h <= 1e-10:
                    raise PanelBError("adaptive Heun cannot satisfy its error tolerance")
                continue
            current = candidate
            current_t += h
            if abs(current_t - stop) <= 1e-12:
                current_t = stop
            dense.append((current_t, current))
            steps += 1
            if error_ratio == 0.0:
                proposed_step = max_step
            else:
                proposed_step = min(max_step, h * min(2.0, 0.9 * error_ratio ** (-1.0 / 3.0)))
        if stop in wanted:
            result[stop] = current
    return result, steps, dense


def _query_outputs(query: Mapping[str, Any], computed: Mapping[str, Any]) -> dict[str, Any]:
    requested = _sequence(query.get("outputs"), "query.outputs")
    out: dict[str, Any] = {}
    for raw_key in requested:
        if not isinstance(raw_key, str) or not raw_key:
            raise PanelBError("query.outputs entries must be non-empty strings")
        if raw_key not in computed:
            raise PanelBError(f"operator does not provide requested output {raw_key!r}")
        out[raw_key] = computed[raw_key]
    return out


def _active_control(intervals: Sequence[Any], hour: float) -> float:
    for raw in intervals:
        pair = _sequence(raw, "control interval")
        if len(pair) != 2:
            raise PanelBError("control intervals must be [start, end]")
        start, end = (_number(pair[0], "control start"), _number(pair[1], "control end"))
        if start <= hour < end:
            return 1.0
    return 0.0


def _controlled_state_space(model: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    state_spec = _mapping(model.get("state"), "state")
    prior = _mapping(state_spec.get("S0_prior"), "state.S0_prior")
    if prior.get("kind") != "beta":
        raise PanelBError("Panel B controlled-state executor requires a beta S0 prior")
    alpha = _number(prior.get("alpha"), "prior.alpha")
    beta = _number(prior.get("beta"), "prior.beta")
    if alpha <= 0.0 or beta <= 0.0:
        raise PanelBError("beta-prior shapes must be positive")
    s0 = alpha / (alpha + beta)
    bounds = _sequence(state_spec.get("bounds"), "state.bounds")
    lo, hi = _number(bounds[0], "state lower bound"), _number(bounds[1], "state upper bound")
    if not lo <= s0 <= hi:
        raise PanelBError("prior expectation lies outside state bounds")

    _, drift = _assignment(str(model.get("dynamics")), "dynamics")
    observation_text = str(model.get("observation"))
    _, observation = _assignment(observation_text, "observation")
    normal_match = re.search(r"Normal\s*\(\s*[^,]+,\s*([0-9.eE+-]+)\s*\)", observation_text)
    observation_sd = _number(float(normal_match.group(1)), "observation sd") if normal_match else 0.0
    control = _mapping(model.get("control"), "control")
    intervals = _sequence(control.get("performed_intervals", ()), "performed_intervals")
    breakpoints = [point for pair in intervals for point in _sequence(pair, "control interval")]
    observation_hours = [_number(x, "observation hour") for x in _sequence(model.get("observation_hours"), "observation_hours")]
    query_hours = [_number(x, "query hour") for x in _sequence(model.get("query_hours"), "query_hours")]
    all_hours = sorted({0.0, 9.0, *observation_hours, *query_hours})

    def derivative(t: float, state: tuple[float, ...]) -> tuple[float, ...]:
        return (drift({"S": state[0], "U": _active_control(intervals, t)}),)

    states, steps, _ = _integrate(derivative, (s0,), all_hours, breakpoints=breakpoints)

    def point(hour: float) -> dict[str, float]:
        s = min(hi, max(lo, states[hour][0]))
        return {"hour": hour, "S": s, "U": _active_control(intervals, hour)}

    trajectory = [point(hour) for hour in query_hours]
    observations: list[dict[str, float]] = []
    rng = random.Random(int(_number(model.get("seed"), "seed")))
    for hour in observation_hours:
        row = point(hour)
        row["MAP_mean"] = observation({"S": row["S"], "U": row["U"]})
        row["MAP_sd"] = observation_sd
        row["MAP"] = row["MAP_mean"] + rng.gauss(0.0, observation_sd)
        observations.append(row)

    s9 = point(9.0)["S"]
    natural_map = observation({"S": s9, "U": 0.0})
    supported_map = observation({"S": s9, "U": 1.0})

    end_hour = max(query_hours)
    interval_ends = [_number(_sequence(pair, "control interval")[1], "control end") for pair in intervals]
    comparison_start = max(interval_ends) if interval_ends else 0.0
    s_start = states[comparison_start][0] if comparison_start in states else states[max(h for h in states if h <= comparison_start)][0]

    def constant_derivative(u: float) -> Callable[[float, tuple[float, ...]], tuple[float, ...]]:
        return lambda _t, state: (drift({"S": state[0], "U": u}),)

    duration = max(0.0, end_hour - comparison_start)
    stopped = _integrate(constant_derivative(0.0), (s_start,), [duration])[0][duration][0]
    continued = _integrate(constant_derivative(1.0), (s_start,), [duration])[0][duration][0]
    stopped_map = observation({"S": stopped, "U": 0.0})
    continued_map = observation({"S": continued, "U": 1.0})
    state_delta = stopped - continued
    map_delta = stopped_map - continued_map
    if state_delta > 0.0 and map_delta < 0.0:
        direction = "S_increases_after_stop"
    elif state_delta < 0.0 and map_delta > 0.0:
        direction = "stopping_decreases_S_and_raises_MAP"
    else:
        direction = "mixed_or_no_direction"
    return {
        "state_trajectory": trajectory,
        "observations": observations,
        "natural_map_at_9": natural_map,
        "supported_map_at_9": supported_map,
        "stop_support_direction": direction,
    }, {
        "solver": "adaptive_step_doubled_heun_richardson",
        "max_step_hours": _DEFAULT_STEP_HOURS,
        "absolute_tolerance": 1e-12,
        "relative_tolerance": 1e-10,
        "steps": steps,
        "prior_reduction": "beta_expectation",
        "stop_comparison": {
            "hour": end_hour,
            "state_delta_stop_minus_continue": state_delta,
            "map_delta_stop_minus_continue": map_delta,
        },
    }


def _condition_and_do(model: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    p_severe = _number(model.get("P_severe"), "P_severe")
    p_treated_mild = _number(model.get("P_treated_given_mild"), "P_treated_given_mild")
    p_treated_severe = _number(model.get("P_treated_given_severe"), "P_treated_given_severe")
    bad = _mapping(model.get("P_bad"), "P_bad")
    priors = {"mild": 1.0 - p_severe, "severe": p_severe}
    treatment = {"mild": p_treated_mild, "severe": p_treated_severe}

    def p_bad(severity: str, treated: int) -> float:
        return _number(bad.get(f"{severity}_T{treated}"), f"P_bad.{severity}_T{treated}")

    conditioned: dict[int, float] = {}
    intervened: dict[int, float] = {}
    for treated in (0, 1):
        joint_weights = {
            severity: priors[severity] * (treatment[severity] if treated else 1.0 - treatment[severity])
            for severity in priors
        }
        posterior = _normalise(joint_weights, f"P(severity,T={treated})")
        conditioned[treated] = math.fsum(posterior[s] * p_bad(s, treated) for s in priors)
        intervened[treated] = math.fsum(priors[s] * p_bad(s, treated) for s in priors)
    return {
        "P_bad_given_T1": conditioned[1],
        "P_bad_given_T0": conditioned[0],
        "P_bad_given_do_T1": intervened[1],
        "P_bad_given_do_T0": intervened[0],
    }, {"solver": "exact_finite_enumeration", "latent_support": ["mild", "severe"], "identification": "structural_mechanism_replacement"}


def _same_patient_aap(model: Mapping[str, Any], query: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    distribution = _mapping(model.get("R"), "R")
    values = list(_sequence(distribution.get("values"), "R.values"))
    probabilities = list(_sequence(distribution.get("probabilities"), "R.probabilities"))
    if len(values) != len(probabilities) or not values:
        raise PanelBError("R values/probabilities must be non-empty and aligned")
    prior = _normalise({value: _number(prob, "R probability") for value, prob in zip(values, probabilities)}, "R")
    equation_text = str(model.get("structural_equation"))
    _, equation = _assignment(equation_text, "structural_equation")
    factual = _mapping(query.get("factual_evidence", model.get("factual_evidence")), "factual_evidence")
    factual_t = _number(factual.get("T"), "factual T")
    factual_y = _number(factual.get("Y"), "factual Y")
    likelihood = {
        value: 1.0 if math.isclose(equation({"R": _number(value, "R value"), "T": factual_t}), factual_y, abs_tol=1e-12) else 0.0
        for value in prior
    }
    posterior = _normalise({value: prior[value] * likelihood[value] for value in prior}, "abducted R")
    intervention = _mapping(query.get("intervention"), "intervention")
    intervention_t = _number(intervention.get("T"), "intervention T")
    individual = math.fsum(
        posterior[value] * equation({"R": _number(value, "R value"), "T": intervention_t}) for value in posterior
    )
    population = math.fsum(
        prior[value] * equation({"R": _number(value, "R value"), "T": intervention_t}) for value in prior
    )
    posterior_r1 = math.fsum(probability for value, probability in posterior.items() if math.isclose(_number(value, "R value"), 1.0))
    return {
        "posterior_R1": posterior_r1,
        "individual_counterfactual_Y_T0": individual,
        "population_do_mean_Y_T0": population,
    }, {
        "solver": "exact_abduction_action_prediction",
        "cross_world_policy": model.get("cross_world_policy"),
        "abduced_support": {str(key): value for key, value in posterior.items()},
    }


def _nonlinear_state_space(model: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    parameters = {key: _number(value, f"parameters.{key}") for key, value in _mapping(model.get("parameters"), "parameters").items()}
    initial = _mapping(model.get("initial"), "initial")
    b0, c0 = _number(initial.get("B"), "initial.B"), _number(initial.get("C"), "initial.C")
    assignments = [_assignment(str(text), "dynamics") for text in _sequence(model.get("dynamics"), "dynamics")]
    algebraic = [(lhs, fn) for lhs, fn in assignments if not (lhs.startswith("d") and lhs.endswith("_dt"))]
    derivative_map = {lhs[1:-3]: fn for lhs, fn in assignments if lhs.startswith("d") and lhs.endswith("_dt")}
    if set(derivative_map) != {"B", "C"}:
        raise PanelBError("nonlinear state-space model must define dB_dt and dC_dt")
    pulse = _mapping(model.get("pulse"), "pulse")
    pulse_start = _number(pulse.get("start_hour"), "pulse.start_hour")
    pulse_end = _number(pulse.get("end_hour"), "pulse.end_hour")
    pulse_a = _number(pulse.get("A"), "pulse.A")

    def env_at(t: float, state: tuple[float, ...]) -> dict[str, float]:
        env = {**parameters, "B": state[0], "C": state[1], "A": pulse_a if pulse_start <= t < pulse_end else 0.0}
        for lhs, fn in algebraic:
            env[lhs] = fn(env)
        return env

    def derivative(t: float, state: tuple[float, ...]) -> tuple[float, ...]:
        env = env_at(t, state)
        return derivative_map["B"](env), derivative_map["C"](env)

    query_hours = [_number(x, "query hour") for x in _sequence(model.get("query_hours"), "query_hours")]
    max_hour = max(query_hours)
    states, steps, dense = _integrate(derivative, (b0, c0), query_hours, breakpoints=[pulse_start, pulse_end])
    trajectory = [
        {"hour": hour, "B": states[hour][0], "C": states[hour][1], "I": env_at(hour, states[hour])["I"], "A": env_at(hour, states[hour])["A"]}
        for hour in query_hours
    ]

    # Locate the global C maximum.  Refine each sign-changing dC bracket by
    # deterministic bisection with Heun-Richardson propagation from its left endpoint.
    candidates: list[tuple[float, tuple[float, ...]]] = [dense[0], dense[-1]]
    for (ta, xa), (tb, xb) in zip(dense, dense[1:]):
        da, db = derivative(ta, xa)[1], derivative(tb, xb)[1]
        if da > 0.0 and db <= 0.0:
            left_t, left_x, right_t = ta, xa, tb
            for _ in range(44):
                mid_t = (left_t + right_t) / 2.0
                mid_x = _heun_embedded(derivative, left_t, left_x, mid_t - left_t)[0]
                if derivative(mid_t, mid_x)[1] > 0.0:
                    left_t, left_x = mid_t, mid_x
                else:
                    right_t = mid_t
            peak_t = (left_t + right_t) / 2.0
            peak_x = _heun_embedded(derivative, left_t, left_x, peak_t - left_t)[0]
            candidates.append((peak_t, peak_x))
    peak_t, _ = max(candidates, key=lambda item: item[1][1])

    phase_derivatives: dict[str, dict[str, float]] = {}

    def phase(hour: float) -> str:
        state = states[hour]
        db, dc = derivative(hour, state)
        phase_derivatives[str(int(hour) if hour.is_integer() else hour)] = {"dB_dt": db, "dC_dt": dc}
        return "rising" if dc > 0.0 else "falling" if dc < 0.0 else "stationary"

    phase7 = phase(7.0)
    phase16 = phase(16.0)

    return {
        "trajectory": trajectory,
        "C_peak_hour": peak_t,
        "phase_at_7": phase7,
        "phase_at_16": phase16,
    }, {
        "solver": "adaptive_step_doubled_heun_richardson_with_derivative_root_refinement",
        "max_step_hours": _DEFAULT_STEP_HOURS,
        "absolute_tolerance": 1e-12,
        "relative_tolerance": 1e-10,
        "steps": steps,
        "breakpoints": [pulse_start, pulse_end],
        "phase_derivatives": phase_derivatives,
        "integrated_to_hour": max_hour,
    }


def _finite_hypothesis_update(model: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    prior = _normalise(_mapping(model.get("prior"), "prior"), "prior")
    phenotype = _mapping(model.get("pre_treatment_phenotype_likelihood"), "pre_treatment_phenotype_likelihood")
    antipyretic = _mapping(model.get("P_response_after_antipyretic"), "P_response_after_antipyretic")
    antibiotic = _mapping(model.get("P_mechanism_response_after_antibiotic"), "P_mechanism_response_after_antibiotic")

    def update(current: Mapping[str, float], likelihood: Mapping[str, Any], label: str) -> dict[str, float]:
        if set(current) != set(likelihood):
            raise PanelBError(f"{label} hypothesis support does not match prior")
        return _normalise({key: current[key] * _number(likelihood[key], f"{label}.{key}") for key in current}, label)

    pre = update(prior, phenotype, "phenotype")
    after_antipyretic = update(pre, antipyretic, "antipyretic response")
    after_antibiotic = update(after_antipyretic, antibiotic, "antibiotic response")
    return {
        "pre_treatment": pre,
        "after_antipyretic": after_antipyretic,
        "after_antibiotic_response": after_antibiotic,
    }, {"solver": "exact_bayes_normalisation", "hypotheses": sorted(str(key) for key in prior), "updates": 3}


def _typed_open_ode(model: Mapping[str, Any], query: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    parameters = {key: _number(value, f"parameters.{key}") for key, value in _mapping(model.get("parameters"), "parameters").items()}
    initial = _mapping(model.get("initial"), "initial")
    burden0 = _number(initial.get("burden"), "initial.burden")
    amount0 = _number(initial.get("drug_amount"), "initial.drug_amount")
    renal = _number(query.get("renal_capacity", initial.get("renal_capacity")), "renal_capacity")
    input_spec = _mapping(model.get("input"), "input")
    infusion_start = _number(input_spec.get("start_hour"), "input.start_hour")
    infusion_end = _number(input_spec.get("end_hour"), "input.end_hour")
    infusion_rate = _number(input_spec.get("infusion_rate"), "input.infusion_rate")
    assignments = [_assignment(str(text), "interaction equation") for text in _sequence(model.get("interaction_equations"), "interaction_equations")]
    algebraic = [(lhs, fn) for lhs, fn in assignments if not (lhs.startswith("d") and lhs.endswith("_dt"))]
    derivatives = {lhs[1:-3]: fn for lhs, fn in assignments if lhs.startswith("d") and lhs.endswith("_dt")}
    if "Burden" not in derivatives:
        raise PanelBError("typed open ODE requires dBurden_dt")

    ports = list(_sequence(model.get("ports"), "ports"))
    required_ports = {
        "A.drug_effect<-I.efficacy",
        "I.burden<-A.burden",
        "I.amount<-C.amount",
        "I.renal<-B.capacity",
        "C.clearance<-I.clearance",
    }
    interaction_required = required_ports.issubset(set(ports)) and {"clearance", "efficacy", "toxicity"}.issubset({lhs for lhs, _ in algebraic})
    if not interaction_required:
        raise PanelBError("typed open ODE lacks an explicit required interaction or port")

    def env_at(t: float, state: tuple[float, ...]) -> dict[str, float]:
        burden, amount = state
        env = {**parameters, "burden": burden, "amount": amount, "renal": renal}
        for lhs, fn in algebraic:
            env[lhs] = fn(env)
        env["infusion"] = infusion_rate if infusion_start <= t < infusion_end else 0.0
        return env

    def derivative(t: float, state: tuple[float, ...]) -> tuple[float, ...]:
        env = env_at(t, state)
        # The public typed ports close the PK mass balance: C receives the
        # interaction clearance and the external input supplies infusion.
        return derivatives["Burden"](env), env["infusion"] - env["clearance"]

    query_hours = [_number(x, "query hour") for x in _sequence(model.get("query_hours"), "query_hours")]
    states, steps, _ = _integrate(derivative, (burden0, amount0), query_hours, breakpoints=[infusion_start, infusion_end])
    trajectory = []
    for hour in query_hours:
        burden, amount = states[hour]
        env = env_at(hour, states[hour])
        trajectory.append({
            "hour": hour,
            "burden": burden,
            "drug_amount": amount,
            "clearance": env["clearance"],
            "efficacy": env["efficacy"],
            "toxicity": env["toxicity"],
        })
    return {
        "renal_capacity": renal,
        "trajectory": trajectory,
        "interaction_required": interaction_required,
    }, {
        "solver": "adaptive_step_doubled_heun_richardson_typed_port_balance",
        "max_step_hours": _DEFAULT_STEP_HOURS,
        "absolute_tolerance": 1e-12,
        "relative_tolerance": 1e-10,
        "steps": steps,
        "breakpoints": [infusion_start, infusion_end],
        "validated_ports": sorted(required_ports),
    }


def _assert_finite_tree(value: Any, path: str = "value") -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise PanelBError(f"{path} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _assert_finite_tree(child, f"{path}.{key}")
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, child in enumerate(value):
            _assert_finite_tree(child, f"{path}[{index}]")
        return
    raise PanelBError(f"{path} contains a non-JSON value {type(value).__name__}")


def execute(public_model: Mapping[str, Any], query: Mapping[str, Any]) -> Mapping[str, Any]:
    """Execute one frozen public-panel query.

    Dispatch is solely by the closed ``query.operator`` enum.  ``query_id`` and
    any workload/test identifier are deliberately ignored for computation.
    """

    model = _mapping(public_model, "public_model")
    typed_query = _mapping(query, "query")
    operator = typed_query.get("operator")
    if operator not in _OPERATORS:
        raise PanelBError(f"unsupported closed operator {operator!r}")

    expected_kind = {
        "controlled_state_space": "controlled_state_space",
        "condition_and_population_do": "finite_scm",
        "same_patient_aap": "finite_scm",
        "nonlinear_state_space": "nonlinear_state_space",
        "finite_hypothesis_update": "finite_hypothesis_model",
        "typed_open_ode": "typed_open_ode",
    }[operator]
    if model.get("model_kind") != expected_kind:
        raise PanelBError(f"operator {operator!r} requires model_kind {expected_kind!r}")

    if operator == "controlled_state_space":
        computed, solver_trace = _controlled_state_space(model)
    elif operator == "condition_and_population_do":
        computed, solver_trace = _condition_and_do(model)
    elif operator == "same_patient_aap":
        computed, solver_trace = _same_patient_aap(model, typed_query)
    elif operator == "nonlinear_state_space":
        computed, solver_trace = _nonlinear_state_space(model)
    elif operator == "finite_hypothesis_update":
        computed, solver_trace = _finite_hypothesis_update(model)
    else:
        computed, solver_trace = _typed_open_ode(model, typed_query)

    selected = _query_outputs(typed_query, computed)
    _assert_finite_tree(selected)
    result = {
        "operator": operator,
        "value": selected,
        "trace": {
            "implementation": "panel_b",
            "query_id": typed_query.get("query_id"),
            "dispatch": "closed_operator_enum",
            **solver_trace,
        },
        "diagnostics": {
            "status": "ok",
            "deterministic": True,
            "finite": True,
            "model_kind": model.get("model_kind"),
        },
    }
    _assert_finite_tree(result)
    return result


__all__ = ["PanelBError", "execute"]
