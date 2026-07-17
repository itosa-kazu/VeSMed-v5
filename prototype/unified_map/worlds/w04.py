"""W04: identical untreated course with class-opposite treatment response."""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any

import numpy as np
from numpy.polynomial.legendre import leggauss

from ..schema import ActionPlan, EventKind, PlanKind
from .base import (
    ActionSpec,
    ChannelSpec,
    CheckSpec,
    CounterfactualOracle,
    MicroWorld,
    PrivateEpisode,
    PublicCatalog,
    WorldSplit,
)
from .randomness import bernoulli, categorical, normal01, uniform01
from .w01 import (
    _U,
    _case_key,
    _check_event,
    _check_plan,
    _exploratory_probabilities,
    _json_float,
    _observation_event,
    _opaque_uid,
    _softmax,
    _split_rng_seed,
    _standard_policy_set,
    _treatment_event,
    _treatment_schedule,
    _visible_history,
)
from .w02 import _condition_scalar, _normalize_components


_RHO = 0.92
_INTERCEPT = 0.15
_PROCESS_VARIANCE = 0.04**2
_Q0_VARIANCE = 0.05**2


def _marker_probability(marker: int, class_index: int) -> float:
    expected = 1 if class_index == 0 else -1
    return 0.95 if marker == expected else 0.05


class W04World(MicroWorld):
    def __init__(self) -> None:
        self._posterior_cache: dict[str, list[dict[str, Any]]] = {}

    @property
    def environment_key(self) -> str:
        return "ucm-private-environment-04"

    @property
    def catalog(self) -> PublicCatalog:
        return PublicCatalog(
            observations=(
                ChannelSpec("obs_0"),
                ChannelSpec(
                    "obs_1",
                    value_type="categorical",
                    unit="signed-marker",
                    valid_range=(-1, 1),
                ),
            ),
            actions=(ActionSpec("A1", cost=0.06), ActionSpec("A2", cost=0.06)),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.06),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W04 horizon")
        policies = list(_standard_policy_set(horizon, checks=("Q0", "Q1")))
        if horizon > 1:
            policies.append(
                _check_plan(
                    "Q1",
                    {
                        "adaptive_rule": "A1_if_marker_positive_else_A2",
                        "treatment_offset": 1,
                    },
                )
            )
        return tuple(policies)

    @staticmethod
    def _action_probabilities(latest_marker: int) -> tuple[float, float, float]:
        return _exploratory_probabilities(
            _softmax((0.2, 0.8 * latest_marker, -0.8 * latest_marker))
        )

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        requested_seed = generator_seed
        generator_seed = _split_rng_seed(generator_seed, split)
        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        c = episode_index % 2
        g = 1.0 if c == 0 else -1.0
        state = -0.5 + 1.7 * uniform01(
            generator_seed, "w04", "initial", episode_index
        )
        events = []
        propensities: list[dict[str, Any]] = []
        latest_marker = 0
        pending_markers: dict[int, int] = {}
        microprobe = (
            split is WorldSplit.TRAIN and episode_index % 10 < 3
        ) or (
            split is WorldSplit.SEALED_TEST and episode_index % 5 == 1
        )
        marker_missing = (
            split is WorldSplit.VALIDATION and episode_index % 5 == 0
        )
        marker_discordant = (
            split is WorldSplit.VALIDATION and episode_index % 5 == 1
        ) or (
            split is WorldSplit.SEALED_TEST and episode_index % 5 == 2
        )
        for tick in range(-4, 1):
            if tick in pending_markers:
                latest_marker = pending_markers[tick]
            q0 = state + 0.05 * normal01(
                generator_seed, "w04", "q0", episode_index, tick
            )
            events.append(
                _observation_event(
                    generator_seed,
                    "obs_0",
                    q0,
                    collected_at=tick,
                    available_at=tick,
                    slot=episode_index * 32,
                )
            )
            q1_probability = 0.9 * 0.25 + 0.1 * 0.5
            forced_marker = marker_discordant and tick == -1
            q1_ordered = False if marker_missing else (
                forced_marker
                or (
                    tick < 0
                    and bernoulli(
                        q1_probability,
                        generator_seed,
                        "w04",
                        "q1",
                        episode_index,
                        tick,
                    )
                )
            )
            actual_q1_probability = (
                0.0 if marker_missing else (1.0 if forced_marker else q1_probability)
            )
            if q1_ordered:
                correct = False if forced_marker else bernoulli(
                    0.95,
                    generator_seed,
                    "w04",
                    "marker-correct",
                    episode_index,
                    tick,
                )
                marker = (1 if c == 0 else -1) * (1 if correct else -1)
                events.extend(
                    (
                        _check_event(
                            generator_seed,
                            "Q1",
                            tick,
                            performed=False,
                            slot=episode_index * 32,
                        ),
                        _check_event(
                            generator_seed,
                            "Q1",
                            tick,
                            performed=True,
                            slot=episode_index * 32,
                        ),
                        _observation_event(
                            generator_seed,
                            "obs_1",
                            marker,
                            collected_at=tick,
                            available_at=tick + 1,
                            slot=episode_index * 32,
                        ),
                    )
                )
                pending_markers[tick + 1] = marker
            propensities.append(
                {
                    "decision_at": tick,
                    "kind": "check",
                    "probabilities": {
                        "Q1": actual_q1_probability,
                        "NoCheck": 1.0 - actual_q1_probability,
                    },
                    "selected": "Q1" if q1_ordered else "NoCheck",
                }
            )
            if tick == 0:
                break
            probabilities = self._action_probabilities(latest_marker)
            if microprobe and tick == -4:
                action_id = "A1"
                actual_probabilities = (0.0, 1.0, 0.0)
            elif microprobe and tick == -3:
                action_id = "A2"
                actual_probabilities = (0.0, 0.0, 1.0)
            else:
                selected = categorical(
                    probabilities,
                    generator_seed,
                    "w04",
                    "action",
                    episode_index,
                    tick,
                )
                action_id = ("NoNewAction", "A1", "A2")[selected]
                actual_probabilities = probabilities
            propensities.append(
                {
                    "decision_at": tick,
                    "kind": "treatment",
                    "probabilities": {
                        "NoNewAction": actual_probabilities[0],
                        "A1": actual_probabilities[1],
                        "A2": actual_probabilities[2],
                    },
                    "selected": action_id,
                    "selected_probability": actual_probabilities[
                        ("NoNewAction", "A1", "A2").index(action_id)
                    ],
                    "randomized_probe": microprobe and tick in {-4, -3},
                    "probe_assignment_probability": 0.30 if split is WorldSplit.TRAIN else 0.20,
                }
            )
            if action_id != "NoNewAction":
                events.append(
                    _treatment_event(
                        generator_seed,
                        action_id,
                        tick,
                        slot=episode_index * 32,
                    )
                )
            state = (
                _RHO * state
                + _INTERCEPT
                - 0.45 * g * _U.get(action_id, 0.0)
                + 0.04
                * normal01(generator_seed, "w04", "process", episode_index, tick + 1)
            )

        public_history = _visible_history(events, self.catalog)
        state_at_cut = state
        future: list[dict[str, Any]] = []
        factual_utility = 0.0
        for offset in range(4):
            probabilities = self._action_probabilities(latest_marker)
            selected = categorical(
                probabilities,
                generator_seed,
                "w04",
                "future-action",
                episode_index,
                offset,
            )
            action_id = ("NoNewAction", "A1", "A2")[selected]
            u = _U.get(action_id, 0.0)
            state = (
                _RHO * state
                + _INTERCEPT
                - 0.45 * g * u
                + 0.04
                * normal01(
                    generator_seed,
                    "w04",
                    "future-process",
                    episode_index,
                    offset,
                )
            )
            factual_utility -= 0.97**offset * (
                state**2 + 0.06 * float(action_id != "NoNewAction")
            )
            future.append(
                {
                    "offset": offset + 1,
                    "latent_outcome": _json_float(state),
                    "performed_action": action_id,
                }
            )
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, split, generator_seed, episode_index),
            environment_key=self.environment_key,
            split=split,
            generator_seed=requested_seed,
            public_history=public_history,
            hidden_state_at_cut={"x": _json_float(state_at_cut)},
            invariant_parameters={"class_index": c},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=_json_float(factual_utility),
            oracle_anchor={
                "continuous_filter": "uniform-prior-quadrature",
                "class_enumeration": 2,
                "strata": [
                    "iid_support",
                    *(
                        ["policy_coverage_holdout"]
                        if split is WorldSplit.SEALED_TEST and microprobe
                        else ["boundary_tail"]
                        if marker_missing or marker_discordant
                        else []
                    ),
                ],
            },
        )

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        value = episode.oracle_anchor.get("strata")
        if type(value) is not list or not value or any(type(item) is not str for item in value):
            raise ValueError("W04 episode lacks exact generator strata")
        result = tuple(value)
        allowed = {
            ("iid_support",),
            ("iid_support", "boundary_tail"),
            ("iid_support", "policy_coverage_holdout"),
            ("iid_support", "behavior_pair"),
        }
        if result not in allowed:
            raise ValueError("W04 episode declares an impossible generator stratum")
        return result

    def _posterior(self, episode: PrivateEpisode) -> list[dict[str, Any]]:
        cached = self._posterior_cache.get(episode.public_history.digest)
        if cached is not None:
            return cached
        nodes, weights = leggauss(48)
        components: list[dict[str, Any]] = []
        for c in (0, 1):
            for node, weight in zip(nodes, weights, strict=True):
                initial = 0.35 + 0.85 * float(node)
                component_weight = 0.5 * float(weight) / 2.0
                components.append(
                    {
                        "class_index": c,
                        "mean": np.array([initial]),
                        "covariance": np.zeros((1, 1)),
                        "weight": component_weight,
                        "log_weight": math.log(component_weight),
                    }
                )
        observations: dict[int, list[Any]] = {}
        actions: dict[int, str] = {}
        for event in episode.public_history.events:
            if event.kind is EventKind.OBSERVATION_AVAILABLE:
                observations.setdefault(int(event.collected_at), []).append(event)
            elif event.kind is EventKind.PERFORMED_TREATMENT:
                actions[event.occurred_at] = str(event.payload["action_id"])
        for tick in range(-4, 1):
            for event in sorted(observations.get(tick, []), key=lambda item: item.event_uid):
                channel = str(event.payload["channel_id"])
                if channel == "obs_0":
                    for component in components:
                        mean, covariance, log_likelihood = _condition_scalar(
                            component["mean"],
                            component["covariance"],
                            np.array([1.0]),
                            float(event.payload["value"]),
                            _Q0_VARIANCE,
                        )
                        component["mean"] = mean
                        component["covariance"] = covariance
                        component["log_weight"] += log_likelihood
                else:
                    marker = int(event.payload["value"])
                    for component in components:
                        component["log_weight"] += math.log(
                            _marker_probability(marker, int(component["class_index"]))
                        )
                _normalize_components(components)
            if tick < 0:
                u = _U.get(actions.get(tick, "NoNewAction"), 0.0)
                for component in components:
                    g = 1.0 if int(component["class_index"]) == 0 else -1.0
                    component["mean"] = (
                        _RHO * component["mean"] + _INTERCEPT - 0.45 * g * u
                    )
                    component["covariance"] = (
                        _RHO**2 * component["covariance"] + _PROCESS_VARIANCE
                    )
        self._posterior_cache[episode.public_history.digest] = components
        return components

    @staticmethod
    def _rollout(
        components: list[dict[str, Any]], schedule: tuple[float, ...], check_cost: float
    ) -> tuple[list[dict[str, Any]], float]:
        working = [
            {
                **component,
                "mean": component["mean"].copy(),
                "covariance": component["covariance"].copy(),
            }
            for component in components
        ]
        steps = []
        utility = -check_cost
        for offset, u in enumerate(schedule):
            total_mean = 0.0
            total_second = 0.0
            expected_cost = 0.0
            for component in working:
                g = 1.0 if int(component["class_index"]) == 0 else -1.0
                component["mean"] = (
                    _RHO * component["mean"] + _INTERCEPT - 0.45 * g * u
                )
                component["covariance"] = (
                    _RHO**2 * component["covariance"] + _PROCESS_VARIANCE
                )
                weight = float(component["weight"])
                mean = float(component["mean"][0])
                variance = float(component["covariance"][0, 0])
                total_mean += weight * mean
                total_second += weight * (variance + mean**2)
                expected_cost += weight * (
                    variance + mean**2 + 0.06 * float(u != 0.0)
                )
            total_variance = max(0.0, total_second - total_mean**2)
            utility -= 0.97**offset * expected_cost
            steps.append(
                {
                    "offset": offset + 1,
                    "mean": _json_float(total_mean),
                    "variance": _json_float(total_variance),
                }
            )
        return steps, utility

    def _adaptive_rollout(
        self, components: list[dict[str, Any]], horizon: int
    ) -> tuple[list[dict[str, Any]], float]:
        first = [np.zeros(1) for _ in range(horizon)]
        second = [0.0 for _ in range(horizon)]
        utility = 0.0
        total_probability = 0.0
        for marker in (-1, 1):
            branch = []
            probability = 0.0
            for component in components:
                likelihood = _marker_probability(marker, int(component["class_index"]))
                weight = float(component["weight"]) * likelihood
                probability += weight
                branch.append(
                    {
                        **component,
                        "mean": component["mean"].copy(),
                        "covariance": component["covariance"].copy(),
                        "weight": weight,
                        "log_weight": math.log(weight) if weight > 0.0 else -math.inf,
                    }
                )
            _normalize_components(branch)
            schedule = [0.0] * horizon
            if horizon > 1:
                schedule[1] = 1.0 if marker == 1 else -1.0
            steps, branch_utility = self._rollout(branch, tuple(schedule), 0.06)
            total_probability += probability
            utility += probability * branch_utility
            for offset, step in enumerate(steps):
                mean = float(step["mean"])
                variance = float(step["variance"])
                first[offset][0] += probability * mean
                second[offset] += probability * (variance + mean**2)
        result = []
        for offset in range(horizon):
            mean = float(first[offset][0] / total_probability)
            variance = second[offset] / total_probability - mean**2
            result.append(
                {
                    "offset": offset + 1,
                    "mean": _json_float(mean),
                    "variance": _json_float(max(0.0, variance)),
                }
            )
        return result, utility / total_probability

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W04 horizon")
        return self._counterfactual_from_components(
            self._posterior(episode), policy, horizon
        )

    def judge_true_state_counterfactual(
        self,
        hidden_state_at_cut: dict[str, Any],
        invariant_parameters: dict[str, Any],
        policy: ActionPlan,
        horizon: int,
    ) -> CounterfactualOracle:
        """Evaluate W04 from a judge-known response modifier and scalar state."""

        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W04 horizon")
        if set(hidden_state_at_cut) != {"x"}:
            raise ValueError("W04 private state must contain exactly x")
        if set(invariant_parameters) != {"class_index"}:
            raise ValueError("W04 private parameters must contain class_index")
        state = hidden_state_at_cut["x"]
        class_index = invariant_parameters["class_index"]
        if type(state) not in {int, float} or not math.isfinite(float(state)):
            raise ValueError("W04 private x must be finite")
        if type(class_index) is not int or class_index not in {0, 1}:
            raise ValueError("W04 private class_index must be zero or one")
        return self._counterfactual_from_components(
            [
                {
                    "class_index": class_index,
                    "mean": np.asarray([float(state)]),
                    "covariance": np.zeros((1, 1)),
                    "weight": 1.0,
                    "log_weight": 0.0,
                }
            ],
            policy,
            horizon,
        )

    def _counterfactual_from_components(
        self,
        components: list[dict[str, Any]],
        policy: ActionPlan,
        horizon: int,
    ) -> CounterfactualOracle:
        if policy not in self.policy_set(horizon):
            raise ValueError("policy is outside the finite W04 policy set")
        adaptive = (
            policy.kind is PlanKind.ACTION_SEQUENCE
            and len(policy.actions) == 1
            and bool(policy.actions[0].parameters.get("adaptive_rule"))
        )
        if adaptive:
            steps, utility = self._adaptive_rollout(components, horizon)
            method = "exact-binary-marker-enumeration"
        else:
            check_cost = 0.0
            if policy.kind is PlanKind.ACTION_SEQUENCE:
                check_cost = 0.06 * sum(
                    action.action_id == "Q1" for action in policy.actions
                )
            steps, utility = self._rollout(
                components, _treatment_schedule(policy, horizon), check_cost
            )
            method = "class-enumerated-linear-gaussian"
        posterior = {
            f"C{c}": math.fsum(
                float(component["weight"])
                for component in components
                if int(component["class_index"]) == c
            )
            for c in (0, 1)
        }
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "class-conditioned-gaussian-mixture",
                "channels": ["obs_0", "obs_1"],
                "steps": steps,
            },
            latent_distribution={
                "family": "class-conditioned-gaussian-mixture",
                "diagnostic_posterior": {
                    key: _json_float(value) for key, value in posterior.items()
                },
                "steps": steps,
            },
            outcome_distribution={
                "utility_family": "mixture-quadratic-form",
                "expected_utility": _json_float(utility),
            },
            expected_utility=_json_float(utility),
            numerical_diagnostics={
                "method": method,
                "initial_state_quadrature_order": 48,
                "absolute_error_bound_for_class_enumeration": 0.0,
            },
        )

    def reference_counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        """Independent parallel-array Bayesian filter and branch enumerator."""

        del oracle_seed
        if horizon not in (1, 4, 8):
            raise ValueError("unsupported W04 horizon")

        def clean(value: float) -> float:
            result = float(value)
            return 0.0 if result == 0.0 else result

        nodes, quadrature_weights = leggauss(48)
        classes: list[int] = []
        means: list[float] = []
        variances: list[float] = []
        weights: list[float] = []
        log_weights: list[float] = []
        for mechanism in (0, 1):
            for node, quadrature_weight in zip(
                nodes, quadrature_weights, strict=True
            ):
                weight = 0.5 * float(quadrature_weight) / 2.0
                classes.append(mechanism)
                means.append(0.35 + 0.85 * float(node))
                variances.append(0.0)
                weights.append(weight)
                log_weights.append(math.log(weight))

        observations: dict[int, list[Any]] = {}
        actions: dict[int, str] = {}
        for event in episode.public_history.events:
            if event.kind is EventKind.OBSERVATION_AVAILABLE:
                observations.setdefault(int(event.collected_at), []).append(event)
            elif event.kind is EventKind.PERFORMED_TREATMENT:
                actions[event.occurred_at] = str(event.payload["action_id"])
        for tick in range(-4, 1):
            for event in sorted(
                observations.get(tick, ()), key=lambda item: (item.event_uid,)
            ):
                channel = str(event.payload["channel_id"])
                if channel == "obs_0":
                    observed = float(event.payload["value"])
                    for index in range(len(means)):
                        innovation = variances[index] + 0.05**2
                        residual = observed - means[index]
                        gain = variances[index] / innovation
                        means[index] += gain * residual
                        variances[index] -= gain * variances[index]
                        log_weights[index] += -0.5 * (
                            math.log(2.0 * math.pi * innovation)
                            + residual * residual / innovation
                        )
                else:
                    marker = int(event.payload["value"])
                    for index, mechanism in enumerate(classes):
                        expected = 1 if mechanism == 0 else -1
                        likelihood = 0.95 if marker == expected else 0.05
                        log_weights[index] += math.log(likelihood)
                peak = max(log_weights)
                raw = [math.exp(value - peak) for value in log_weights]
                total = math.fsum(raw)
                weights = [value / total for value in raw]
                log_weights = [
                    math.log(value) if value > 0.0 else -math.inf
                    for value in weights
                ]
            if tick < 0:
                action = actions.get(tick)
                dose = 1.0 if action == "A1" else -1.0 if action == "A2" else 0.0
                for index, mechanism in enumerate(classes):
                    response_sign = 1.0 if mechanism == 0 else -1.0
                    means[index] = (
                        0.92 * means[index]
                        + 0.15
                        - 0.45 * response_sign * dose
                    )
                    variances[index] = 0.92**2 * variances[index] + 0.04**2

        def project(
            branch_means: list[float],
            branch_variances: list[float],
            branch_weights: list[float],
            doses: list[float],
            check_cost: float,
        ) -> tuple[list[dict[str, Any]], float]:
            active_means = list(branch_means)
            active_variances = list(branch_variances)
            utility = -check_cost
            rows: list[dict[str, Any]] = []
            for offset, dose in enumerate(doses):
                for index, mechanism in enumerate(classes):
                    response_sign = 1.0 if mechanism == 0 else -1.0
                    active_means[index] = (
                        0.92 * active_means[index]
                        + 0.15
                        - 0.45 * response_sign * dose
                    )
                    active_variances[index] = (
                        0.92**2 * active_variances[index] + 0.04**2
                    )
                mean = math.fsum(
                    weight * value
                    for weight, value in zip(
                        branch_weights, active_means, strict=True
                    )
                )
                second = math.fsum(
                    weight * (spread + value * value)
                    for weight, value, spread in zip(
                        branch_weights, active_means, active_variances, strict=True
                    )
                )
                variance = max(0.0, second - mean * mean)
                expected_cost = math.fsum(
                    weight
                    * (spread + value * value + 0.06 * float(dose != 0.0))
                    for weight, value, spread in zip(
                        branch_weights, active_means, active_variances, strict=True
                    )
                )
                utility -= 0.97**offset * expected_cost
                rows.append(
                    {
                        "offset": offset + 1,
                        "mean": clean(mean),
                        "variance": clean(variance),
                    }
                )
            return rows, float(utility)

        adaptive = (
            policy.kind is PlanKind.ACTION_SEQUENCE
            and len(policy.actions) == 1
            and bool(policy.actions[0].parameters.get("adaptive_rule"))
        )
        if not adaptive:
            doses = [0.0] * horizon
            check_cost = 0.0
            if policy.kind is PlanKind.ACTION_SEQUENCE:
                for action in policy.actions:
                    if action.offset < horizon:
                        if action.action_id == "A1":
                            doses[action.offset] = 1.0
                        elif action.action_id == "A2":
                            doses[action.offset] = -1.0
                    if action.action_id == "Q1":
                        check_cost += 0.06
            steps, utility = project(means, variances, weights, doses, check_cost)
            method = "independent-parallel-array-class-enumeration"
        else:
            first = [0.0] * horizon
            second = [0.0] * horizon
            utility_sum = 0.0
            probability_sum = 0.0
            for marker in (-1, 1):
                branch_weights = []
                probability = 0.0
                for mechanism, weight in zip(classes, weights, strict=True):
                    expected = 1 if mechanism == 0 else -1
                    likelihood = 0.95 if marker == expected else 0.05
                    unnormalized = weight * likelihood
                    probability += unnormalized
                    branch_weights.append(unnormalized)
                branch_weights = [value / probability for value in branch_weights]
                doses = [0.0] * horizon
                if horizon > 1:
                    doses[1] = 1.0 if marker == 1 else -1.0
                branch_steps, branch_utility = project(
                    means, variances, branch_weights, doses, 0.06
                )
                probability_sum += probability
                utility_sum += probability * branch_utility
                for offset, row in enumerate(branch_steps):
                    mean = float(row["mean"])
                    variance = float(row["variance"])
                    first[offset] += probability * mean
                    second[offset] += probability * (variance + mean * mean)
            steps = []
            for offset in range(horizon):
                mean = first[offset] / probability_sum
                variance = second[offset] / probability_sum - mean * mean
                steps.append(
                    {
                        "offset": offset + 1,
                        "mean": clean(mean),
                        "variance": clean(max(0.0, variance)),
                    }
                )
            utility = utility_sum / probability_sum
            method = "independent-binary-marker-branch-enumeration"

        posterior = {
            f"C{mechanism}": clean(
                math.fsum(
                    weight
                    for label, weight in zip(classes, weights, strict=True)
                    if label == mechanism
                )
            )
            for mechanism in (0, 1)
        }
        utility = clean(utility)
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "class-conditioned-gaussian-mixture",
                "channels": ["obs_0", "obs_1"],
                "steps": steps,
            },
            latent_distribution={
                "family": "class-conditioned-gaussian-mixture",
                "diagnostic_posterior": posterior,
                "steps": steps,
            },
            outcome_distribution={
                "utility_family": "mixture-quadratic-form",
                "expected_utility": utility,
            },
            expected_utility=utility,
            numerical_diagnostics={
                "method": method,
                "initial_state_quadrature_order": 48,
                "private_state_used": False,
            },
        )

    def _fixture_episode(
        self, marker: int, seed: int, salt: int
    ) -> PrivateEpisode:
        events = []
        for position, tick in enumerate(range(-4, 1)):
            events.append(
                _observation_event(
                    seed + salt,
                    "obs_0",
                    0.4,
                    collected_at=tick,
                    available_at=tick,
                    slot=position,
                )
            )
        events.append(
            _observation_event(
                seed + salt,
                "obs_1",
                marker,
                collected_at=-1,
                available_at=0,
                slot=99,
            )
        )
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, salt),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"fixture_realization": salt},
            invariant_parameters={"fixture": "opposite-response"},
            diagnostic_target={"C0": 0.5, "C1": 0.5},
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={
                "fixture": "paired",
                "strata": ["iid_support", "behavior_pair"],
            },
        )

    def collision_fixture(self, seed: int = 401) -> tuple[PrivateEpisode, PrivateEpisode]:
        return self._fixture_episode(1, seed, 1), self._fixture_episode(-1, seed, 2)

    def false_split_fixture(self, seed: int = 403) -> tuple[PrivateEpisode, PrivateEpisode]:
        first = self._fixture_episode(1, seed, 7)
        events = tuple(
            replace(event, event_uid=_opaque_uid(seed + 91, "alpha", index))
            for index, event in enumerate(first.public_history.events)
        )
        return first, replace(
            first,
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, 8),
            public_history=_visible_history(events, self.catalog),
        )

    def irreducible_fixture(self, seed: int = 405) -> tuple[PrivateEpisode, PrivateEpisode]:
        first = self.generate_episode(WorldSplit.SEALED_TEST, seed, 12)
        # Same bytes, opposite realized private class: correct oracle remains a belief.
        second = replace(
            first,
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, 13),
            invariant_parameters={"class_index": 1 - int(first.invariant_parameters["class_index"])},
            factual_future=[{"opposite_private_realization": True}],
        )
        return first, second


World = W04World


__all__ = ["W04World", "World"]
