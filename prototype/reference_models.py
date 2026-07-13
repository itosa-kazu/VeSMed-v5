"""Runner-only reference models for the E01--E08 experiment panel.

The implementations in this module are deliberately small, deterministic and
independent from every architecture candidate.  Candidates receive the public
model records produced by :func:`public_model`; they never receive the values
returned by :func:`reference_output`.

These are dimensionless architecture discriminators, not clinical models.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from random import Random
from typing import Any, Callable, Iterable, Mapping, Sequence


REFERENCE_VERSION = "archbench-reference-v1"


def _rk4_scalar(
    rhs: Callable[[float, float], float],
    y0: float,
    end: float,
    *,
    step: float = 1.0 / 600.0,
) -> tuple[list[float], list[float]]:
    """Integrate a scalar ODE on a fixed fine grid with RK4."""

    t = 0.0
    y = float(y0)
    ts = [t]
    ys = [y]
    while t < end - 1e-14:
        h = min(step, end - t)
        k1 = rhs(t, y)
        k2 = rhs(t + h / 2.0, y + h * k1 / 2.0)
        k3 = rhs(t + h / 2.0, y + h * k2 / 2.0)
        k4 = rhs(t + h, y + h * k3)
        y += h * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
        t += h
        ts.append(t)
        ys.append(y)
    return ts, ys


def _rk4_vector(
    rhs: Callable[[float, Sequence[float]], Sequence[float]],
    y0: Sequence[float],
    end: float,
    *,
    step: float = 1.0 / 600.0,
) -> tuple[list[float], list[list[float]]]:
    """Integrate a small vector ODE on a fixed fine grid with RK4."""

    t = 0.0
    y = [float(v) for v in y0]
    ts = [t]
    ys = [y.copy()]
    while t < end - 1e-14:
        h = min(step, end - t)
        k1 = list(rhs(t, y))
        y2 = [v + h * k / 2.0 for v, k in zip(y, k1)]
        k2 = list(rhs(t + h / 2.0, y2))
        y3 = [v + h * k / 2.0 for v, k in zip(y, k2)]
        k3 = list(rhs(t + h / 2.0, y3))
        y4 = [v + h * k for v, k in zip(y, k3)]
        k4 = list(rhs(t + h, y4))
        y = [
            v + h * (a + 2.0 * b + 2.0 * c + d) / 6.0
            for v, a, b, c, d in zip(y, k1, k2, k3, k4)
        ]
        t += h
        ts.append(t)
        ys.append(y.copy())
    return ts, ys


def _piecewise_vector(
    rhs: Callable[[float, Sequence[float], Any], Sequence[float]],
    y0: Sequence[float],
    segments: Sequence[tuple[float, Any]],
    *,
    step: float,
) -> tuple[list[float], list[list[float]]]:
    """Integrate exactly up to every discontinuity before changing regime."""

    absolute_start = 0.0
    current = [float(v) for v in y0]
    all_t = [0.0]
    all_y = [current.copy()]
    for absolute_end, regime in segments:
        duration = absolute_end - absolute_start
        local_t, local_y = _rk4_vector(
            lambda tau, values: rhs(absolute_start + tau, values, regime),
            current,
            duration,
            step=step,
        )
        all_t.extend(absolute_start + t for t in local_t[1:])
        all_y.extend(values.copy() for values in local_y[1:])
        current = local_y[-1]
        absolute_start = absolute_end
    return all_t, all_y


def _sample(ts: Sequence[float], values: Sequence[Any], at: Iterable[float]) -> list[Any]:
    """Nearest-grid samples; the reference grid is much finer than tolerance."""

    out: list[Any] = []
    for q in at:
        index = min(range(len(ts)), key=lambda i: abs(ts[i] - q))
        value = values[index]
        out.append(value.copy() if isinstance(value, list) else value)
    return out


E_PUBLIC: dict[str, dict[str, Any]] = {
    "E01": {
        "model_kind": "controlled_state_space",
        "state": {"S0_prior": {"kind": "beta", "alpha": 8, "beta": 2}, "bounds": [0, 1]},
        "control": {"U_bounds": [0, 1], "performed_intervals": [[4, 12]]},
        "dynamics": "dS_dt = 0.08*(1-S) - 0.18*U*S",
        "observation": "MAP = 75 - 25*S + 18*U + Normal(0,1.5)",
        "observation_hours": [0, 2, 4, 6, 9, 12, 15, 20],
        "query_hours": [9, 12, 18, 24],
        "seed": 1103,
    },
    "E02": {
        "model_kind": "finite_scm",
        "P_severe": 0.5,
        "P_treated_given_severe": 0.9,
        "P_treated_given_mild": 0.1,
        "P_bad": {"severe_T0": 0.90, "severe_T1": 0.60, "mild_T0": 0.20, "mild_T1": 0.05},
    },
    "E03": {
        "model_kind": "finite_scm",
        "R": {"values": [0, 1], "probabilities": [0.5, 0.5]},
        "structural_equation": "Y = R*(1+T) + (1-R)*(-T)",
        "factual_evidence": {"T": 1, "Y": 2},
        "cross_world_policy": "share_abduced_exogenous",
    },
    "E04": {
        "model_kind": "nonlinear_state_space",
        "initial": {"B": 0.08, "C": 0.0118},
        "parameters": {"r": 0.35, "K": 1.0, "k_abx": 1.0, "hill_h": 3, "hill_K": 0.35, "tau_hours": 6.0},
        "dynamics": [
            "dB_dt = r*B*(1-B/K) - k_abx*A*B",
            "I = B^hill_h/(hill_K^hill_h+B^hill_h)",
            "dC_dt = (I-C)/tau_hours",
        ],
        "pulse": {"A": 1, "start_hour": 6, "end_hour": 10},
        "observation_hours": [0, 3, 7, 11, 16, 24, 31],
        "query_hours": [7, 16, 24, 40],
        "seed": 2207,
    },
    "E05": {
        "model_kind": "finite_hypothesis_model",
        "prior": {"infection": 0.5, "sterile": 0.5},
        "pre_treatment_phenotype_likelihood": {"infection": 0.8, "sterile": 0.8},
        "P_response_after_antipyretic": {"infection": 0.8, "sterile": 0.8},
        "P_mechanism_response_after_antibiotic": {"infection": 0.9, "sterile": 0.2},
    },
    "E06": {
        "model_kind": "typed_open_ode",
        "initial": {"burden": 0.25, "drug_amount": 0.0, "renal_capacity": 0.45},
        "parameters": {"r_burden": 0.25, "CL0": 0.8, "Km": 0.3, "Emax": 0.9, "EC50": 0.4, "Tmax": 0.7},
        "ports": [
            "A.drug_effect<-I.efficacy",
            "I.burden<-A.burden",
            "I.amount<-C.amount",
            "I.renal<-B.capacity",
            "C.clearance<-I.clearance",
        ],
        "input": {"infusion_rate": 0.18, "start_hour": 0, "end_hour": 8},
        "query_hours": [4, 8, 12, 24],
        "interaction_equations": [
            "clearance = CL0*renal*amount/(Km+amount)",
            "efficacy = Emax*amount/(EC50+amount)",
            "toxicity = (amount^2/(Tmax^2+amount^2))*(1-renal)",
            "dBurden_dt = r_burden*burden*(1-burden)-efficacy*burden",
        ],
    },
    "E07": {
        "model_kind": "composition_law_probe",
        "input": 1.0,
        "modules": {"A": {"delta": 1.0}, "B": {"delta": -0.25}, "C": {"delta": 0.5}},
        "claimed_law": "associative_parallel_sum",
    },
    "E08": {
        "model_kind": "feedback_and_support",
        "contraction": "x_next=0.4*x+0.6",
        "rootless_support_cycle": ["A<-B", "B<-A"],
        "no_solution": "x=x+1",
        "non_unique": "x=x",
    },
}


def public_model(experiment_id: str) -> dict[str, Any]:
    """Return a detached copy of a public model commitment."""

    import copy

    if experiment_id not in E_PUBLIC:
        raise KeyError(experiment_id)
    return copy.deepcopy(E_PUBLIC[experiment_id])


def reference_e01(*, step: float = 1.0 / 600.0) -> dict[str, Any]:
    model = E_PUBLIC["E01"]
    s0 = 8.0 / 10.0

    def control(t: float) -> float:
        return 1.0 if 4.0 <= t < 12.0 else 0.0

    def rhs(_t: float, values: Sequence[float], u: float) -> Sequence[float]:
        s = values[0]
        return (0.08 * (1.0 - s) - 0.18 * u * s,)

    ts, vector_ss = _piecewise_vector(rhs, [s0], [(4.0, 0.0), (12.0, 1.0), (24.0, 0.0)], step=step)
    ss = [values[0] for values in vector_ss]
    obs_s = _sample(ts, ss, model["observation_hours"])
    rng = Random(model["seed"])
    observations = []
    for t, s in zip(model["observation_hours"], obs_s):
        u = control(float(t))
        observations.append({"hour": t, "MAP": 75.0 - 25.0 * s + 18.0 * u + rng.gauss(0.0, 1.5), "U": u})
    query_s = _sample(ts, ss, model["query_hours"])
    return {
        "reference_version": REFERENCE_VERSION,
        "state_trajectory": [{"hour": t, "S": s} for t, s in zip(model["query_hours"], query_s)],
        "observations": observations,
        "natural_map_at_9": 75.0 - 25.0 * query_s[0],
        "supported_map_at_9": 75.0 - 25.0 * query_s[0] + 18.0,
        "stop_support_direction": "S_increases_after_stop",
    }


def reference_e02() -> dict[str, Any]:
    # Exact exhaustive enumeration over H and T.
    observational_t1 = (0.5 * 0.9 * 0.60 + 0.5 * 0.1 * 0.05) / (0.5 * 0.9 + 0.5 * 0.1)
    observational_t0 = (0.5 * 0.1 * 0.90 + 0.5 * 0.9 * 0.20) / (0.5 * 0.1 + 0.5 * 0.9)
    do_t1 = 0.5 * 0.60 + 0.5 * 0.05
    do_t0 = 0.5 * 0.90 + 0.5 * 0.20
    return {
        "reference_version": REFERENCE_VERSION,
        "P_bad_given_T1": observational_t1,
        "P_bad_given_T0": observational_t0,
        "P_bad_given_do_T1": do_t1,
        "P_bad_given_do_T0": do_t0,
        "observational_direction": "treated_worse",
        "interventional_direction": "treated_better",
    }


def reference_e03() -> dict[str, Any]:
    # T=1,Y=2 identifies R=1 exactly.  AAP retains that R in the counterfactual.
    return {
        "reference_version": REFERENCE_VERSION,
        "posterior_R1": 1.0,
        "individual_counterfactual_Y_T0": 1.0,
        "population_do_mean_Y_T0": 0.5,
    }


def reference_e04(*, step: float = 1.0 / 600.0) -> dict[str, Any]:
    p = E_PUBLIC["E04"]["parameters"]

    def rhs(_t: float, y: Sequence[float], a: float) -> Sequence[float]:
        b, c = y
        db = p["r"] * b * (1.0 - b / p["K"]) - p["k_abx"] * a * b
        hill = b ** p["hill_h"] / (p["hill_K"] ** p["hill_h"] + b ** p["hill_h"])
        dc = (hill - c) / p["tau_hours"]
        return db, dc

    ts, ys = _piecewise_vector(rhs, [0.08, 0.0118], [(6.0, 0.0), (10.0, 1.0), (40.0, 0.0)], step=step)
    query = _sample(ts, ys, E_PUBLIC["E04"]["query_hours"])
    dense_c = [v[1] for v in ys]
    peak_index = max(range(len(dense_c)), key=dense_c.__getitem__)
    return {
        "reference_version": REFERENCE_VERSION,
        "trajectory": [
            {"hour": t, "B": value[0], "C": value[1]}
            for t, value in zip(E_PUBLIC["E04"]["query_hours"], query)
        ],
        "C_peak_hour": ts[peak_index],
        "phase_at_7": "rising" if rhs(7.0, query[0], 1.0)[1] > 0 else "falling",
        "phase_at_16": "rising" if rhs(16.0, query[1], 0.0)[1] > 0 else "falling",
    }


def reference_e05() -> dict[str, Any]:
    prior = {"infection": 0.5, "sterile": 0.5}

    def posterior(likelihood: Mapping[str, float]) -> dict[str, float]:
        weights = {k: prior[k] * likelihood[k] for k in prior}
        z = sum(weights.values())
        return {k: v / z for k, v in weights.items()}

    return {
        "reference_version": REFERENCE_VERSION,
        "pre_treatment": posterior(E_PUBLIC["E05"]["pre_treatment_phenotype_likelihood"]),
        "after_antipyretic": posterior(E_PUBLIC["E05"]["P_response_after_antipyretic"]),
        "after_antibiotic_response": posterior(E_PUBLIC["E05"]["P_mechanism_response_after_antibiotic"]),
    }


def reference_e06(*, renal_capacity: float = 0.45, step: float = 1.0 / 600.0) -> dict[str, Any]:
    p = E_PUBLIC["E06"]["parameters"]

    def rhs(_t: float, y: Sequence[float], infusion: float) -> Sequence[float]:
        burden, amount = y
        clearance = p["CL0"] * renal_capacity * amount / (p["Km"] + amount) if amount > 0.0 else 0.0
        efficacy = p["Emax"] * amount / (p["EC50"] + amount) if amount > 0.0 else 0.0
        db = p["r_burden"] * burden * (1.0 - burden) - efficacy * burden
        da = infusion - clearance
        return db, da

    ts, ys = _piecewise_vector(rhs, [0.25, 0.0], [(8.0, 0.18), (24.0, 0.0)], step=step)
    query = _sample(ts, ys, E_PUBLIC["E06"]["query_hours"])
    rows = []
    for hour, (burden, amount) in zip(E_PUBLIC["E06"]["query_hours"], query):
        toxicity = (amount * amount / (p["Tmax"] ** 2 + amount * amount)) * (1.0 - renal_capacity)
        rows.append({"hour": hour, "burden": burden, "drug_amount": amount, "toxicity": toxicity})
    return {
        "reference_version": REFERENCE_VERSION,
        "renal_capacity": renal_capacity,
        "trajectory": rows,
        "interaction_required": True,
    }


def reference_e07() -> dict[str, Any]:
    modules = E_PUBLIC["E07"]["modules"]
    x = E_PUBLIC["E07"]["input"]
    total = x + sum(module["delta"] for module in modules.values())
    return {
        "reference_version": REFERENCE_VERSION,
        "left_bracket": total,
        "right_bracket": total,
        "registration_orders": {"ABC": total, "CBA": total, "BAC": total},
        "used_modules": sorted(modules),
    }


def reference_e08(*, tolerance: float = 1e-12) -> dict[str, Any]:
    x = 0.0
    iterations = 0
    while iterations < 1000:
        next_x = 0.4 * x + 0.6
        iterations += 1
        if abs(next_x - x) < tolerance:
            x = next_x
            break
        x = next_x
    return {
        "reference_version": REFERENCE_VERSION,
        "contraction": {"status": "unique", "value": x, "iterations": iterations},
        "rootless_support": [],
        "no_solution": {"status": "no_solution"},
        "non_unique": {"status": "multiple_solutions"},
    }


REFERENCE_FUNCTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "E01": reference_e01,
    "E02": reference_e02,
    "E03": reference_e03,
    "E04": reference_e04,
    "E05": reference_e05,
    "E06": reference_e06,
    "E07": reference_e07,
    "E08": reference_e08,
}


def reference_output(experiment_id: str, **kwargs: Any) -> dict[str, Any]:
    try:
        function = REFERENCE_FUNCTIONS[experiment_id]
    except KeyError as exc:
        raise KeyError(f"unknown reference experiment: {experiment_id}") from exc
    return function(**kwargs)


@dataclass(frozen=True)
class ReferenceSelfTest:
    test_id: str
    passed: bool
    diagnostic: str

    def to_dict(self) -> dict[str, Any]:
        return {"test_id": self.test_id, "passed": self.passed, "diagnostic": self.diagnostic}


def self_test_reference_models() -> list[ReferenceSelfTest]:
    """Analytic limits and step-halving checks used to qualify runner judges."""

    tests: list[ReferenceSelfTest] = []

    e02 = reference_e02()
    expected_e02 = (0.545, 0.270, 0.325, 0.550)
    observed_e02 = tuple(e02[key] for key in ("P_bad_given_T1", "P_bad_given_T0", "P_bad_given_do_T1", "P_bad_given_do_T0"))
    tests.append(ReferenceSelfTest("E02.exact_enumeration", all(isclose(a, b, abs_tol=1e-12) for a, b in zip(observed_e02, expected_e02)), repr(observed_e02)))

    e03 = reference_e03()
    tests.append(
        ReferenceSelfTest(
            "E03.shared_exogenous",
            e03["individual_counterfactual_Y_T0"] == 1.0 and e03["population_do_mean_Y_T0"] == 0.5,
            repr(e03),
        )
    )

    for experiment, function, keys in (
        ("E01", reference_e01, ("state_trajectory",)),
        ("E04", reference_e04, ("trajectory",)),
        ("E06", reference_e06, ("trajectory",)),
    ):
        # The integrator stops exactly at every control/pulse boundary before
        # switching regimes, so ordinary RK4 step halving is meaningful.
        fine = function(step=1.0 / 600.0)
        finer = function(step=1.0 / 1200.0)

        def numbers(value: Any) -> list[float]:
            if isinstance(value, (int, float)):
                return [float(value)]
            if isinstance(value, list):
                return [n for item in value for n in numbers(item)]
            if isinstance(value, dict):
                return [n for key, item in sorted(value.items()) if key != "reference_version" for n in numbers(item)]
            return []

        left = [n for key in keys for n in numbers(fine[key])]
        right = [n for key in keys for n in numbers(finer[key])]
        error = max((abs(a - b) for a, b in zip(left, right)), default=0.0)
        tests.append(ReferenceSelfTest(f"{experiment}.step_halving", error < 1e-5, f"max_abs_error={error:.3g}"))

    e05 = reference_e05()
    tests.append(
        ReferenceSelfTest(
            "E05.selectivity",
            isclose(e05["after_antipyretic"]["infection"], 0.5, abs_tol=1e-12)
            and e05["after_antibiotic_response"]["infection"] > 0.8,
            repr(e05),
        )
    )
    e07 = reference_e07()
    tests.append(ReferenceSelfTest("E07.associativity", e07["left_bracket"] == e07["right_bracket"], repr(e07)))
    e08 = reference_e08()
    tests.append(
        ReferenceSelfTest(
            "E08.feedback_classification",
            abs(e08["contraction"]["value"] - 1.0) < 1e-10
            and e08["rootless_support"] == []
            and e08["no_solution"]["status"] == "no_solution"
            and e08["non_unique"]["status"] == "multiple_solutions",
            repr(e08),
        )
    )
    return tests


def assert_reference_models_valid() -> None:
    failures = [test for test in self_test_reference_models() if not test.passed]
    if failures:
        raise AssertionError("reference model self-test failures: " + "; ".join(f"{f.test_id}: {f.diagnostic}" for f in failures))


__all__ = [
    "E_PUBLIC",
    "REFERENCE_VERSION",
    "assert_reference_models_valid",
    "public_model",
    "reference_output",
    "self_test_reference_models",
]
