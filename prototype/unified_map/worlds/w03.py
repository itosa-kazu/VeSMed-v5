"""W03: identical current phenotype with opposite untreated dynamics."""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any

import numpy as np
from numpy.polynomial.hermite import hermgauss
from numpy.polynomial.legendre import leggauss

from ..canonical import canonical_json_bytes, digest_json
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
    _visible_history,
)
from .w02 import _condition_scalar, _normalize_components


_U3 = {"A1": -1.0, "A2": 1.0}
_PROCESS_VARIANCE = 0.035**2
_OBSERVATIONS = {"obs_0": (0.04**2, 0.0), "obs_1": (0.015**2, 0.03)}
# The scoring oracle uses one frozen population prior for every benchmark split.
# Split-specific supports below are generator-only covariate shifts and are not
# candidate-visible query semantics.
_PUBLIC_DRIFT_PRIOR_BOUNDS = (0.20, 0.30)


def _schedule(policy: ActionPlan, horizon: int) -> tuple[float, ...]:
    values = [0.0] * horizon
    if policy.kind is PlanKind.ACTION_SEQUENCE:
        for action in policy.actions:
            if action.offset < horizon:
                values[action.offset] = _U3.get(action.action_id, 0.0)
    return tuple(values)


class W03World(MicroWorld):
    def __init__(self) -> None:
        self._posterior_cache: dict[str, list[dict[str, Any]]] = {}
        self._adaptive_cache: dict[
            tuple[str, int], tuple[list[dict[str, Any]], float, float, float]
        ] = {}

    @property
    def environment_key(self) -> str:
        return "ucm-private-environment-03"

    @property
    def catalog(self) -> PublicCatalog:
        return PublicCatalog(
            observations=(ChannelSpec("obs_0"), ChannelSpec("obs_1")),
            actions=(ActionSpec("A1", cost=0.04), ActionSpec("A2", cost=0.04)),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.03),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W03 horizon")
        policies = list(_standard_policy_set(horizon, checks=("Q0", "Q1")))
        if horizon > 1:
            policies.append(
                _check_plan(
                    "Q1",
                    {
                        "adaptive_rule": "A1_if_posterior_level_positive_else_A2",
                        "treatment_offset": 1,
                    },
                )
            )
        return tuple(policies)

    @staticmethod
    def _generator_d_bounds(split: WorldSplit) -> tuple[float, float]:
        if split is WorldSplit.TRAIN:
            return (0.20, 0.27)
        if split is WorldSplit.VALIDATION:
            return (0.20, 0.30)
        return (0.23, 0.30)

    @staticmethod
    def _action_probabilities(slope: float) -> tuple[float, float, float]:
        return _exploratory_probabilities(
            _softmax((0.4, 2.0 * slope, -2.0 * slope))
        )

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        requested_seed = generator_seed
        generator_seed = _split_rng_seed(generator_seed, split)
        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        c = episode_index % 2
        pair_group = episode_index // 2
        current_match = (
            split is WorldSplit.VALIDATION and pair_group % 5 == 0
        ) or (
            split is WorldSplit.SEALED_TEST and pair_group % 5 in {0, 1}
        )
        sparse_history = (
            split is WorldSplit.SEALED_TEST and pair_group % 5 == 2
        )
        lower, upper = self._generator_d_bounds(split)
        d = lower + (upper - lower) * uniform01(
            generator_seed,
            "w03",
            "d",
            pair_group if current_match else episode_index,
        )
        state = -0.8 + 1.6 * uniform01(
            generator_seed, "w03", "initial", episode_index
        )
        events = []
        propensities: list[dict[str, Any]] = []
        q0_values: list[float] = []
        for tick in range(-4, 1):
            q0 = state + 0.04 * normal01(
                generator_seed, "w03", "q0", episode_index, tick
            )
            if current_match and tick == 0:
                q0 = -0.35 + 0.70 * uniform01(
                    generator_seed, "w03", "matched-current", pair_group
                )
            q0_values.append(q0)
            if not (sparse_history and tick == -2):
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
            slope = q0_values[-1] - q0_values[-2] if len(q0_values) >= 2 else 0.0
            q1_probability = 0.15 + 0.35 / (
                1.0 + math.exp(-(abs(slope) - 0.12))
            )
            q1_probability = 0.9 * q1_probability + 0.1 * 0.5
            actual_q1_probability = 0.0 if current_match else q1_probability
            q1_ordered = tick < 0 and bernoulli(
                actual_q1_probability,
                generator_seed,
                "w03",
                "q1-order",
                episode_index,
                tick,
            )
            if q1_ordered:
                q1 = state + 0.015 * normal01(
                    generator_seed, "w03", "q1", episode_index, tick
                )
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
                            q1,
                            collected_at=tick,
                            available_at=tick + 1,
                            slot=episode_index * 32,
                        ),
                    )
                )
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
            probabilities = self._action_probabilities(slope)
            selected = categorical(
                probabilities,
                generator_seed,
                "w03",
                "action",
                episode_index,
                tick,
            )
            action_id = ("NoNewAction", "A1", "A2")[selected]
            propensities.append(
                {
                    "decision_at": tick,
                    "kind": "treatment",
                    "probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                        "A2": probabilities[2],
                    },
                    "selected": action_id,
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
            state += d * (-1.0 if c == 0 else 1.0) + 0.30 * _U3.get(action_id, 0.0)
            state += 0.035 * normal01(
                generator_seed, "w03", "process", episode_index, tick + 1
            )

        state_at_cut = state
        public_history = _visible_history(events, self.catalog)
        future: list[dict[str, Any]] = []
        factual_utility = 0.0
        for offset in range(4):
            # Supported factual continuation uses the observable recent slope.
            probabilities = self._action_probabilities(
                q0_values[-1] - q0_values[-2]
            )
            selected = categorical(
                probabilities,
                generator_seed,
                "w03",
                "future-action",
                episode_index,
                offset,
            )
            action_id = ("NoNewAction", "A1", "A2")[selected]
            u = _U3.get(action_id, 0.0)
            state += d * (-1.0 if c == 0 else 1.0) + 0.30 * u
            state += 0.035 * normal01(
                generator_seed,
                "w03",
                "future-process",
                episode_index,
                offset,
            )
            factual_utility -= 0.97**offset * (state**2 + 0.04 * u**2)
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
            invariant_parameters={"class_index": c, "drift_magnitude": _json_float(d)},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=_json_float(factual_utility),
            oracle_anchor={
                "class_enumeration": 2,
                "drift_quadrature_order": 64,
                "strata": [
                    "iid_support",
                    *(
                        ["behavior_pair"]
                        if current_match
                        else ["boundary_tail"]
                        if sparse_history
                        else []
                    ),
                ],
            },
        )

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        value = episode.oracle_anchor.get("strata")
        if type(value) is not list or not value or any(type(item) is not str for item in value):
            raise ValueError("W03 episode lacks exact generator strata")
        result = tuple(value)
        allowed = {
            ("iid_support",),
            ("iid_support", "boundary_tail"),
            ("iid_support", "behavior_pair"),
        }
        if result not in allowed:
            raise ValueError("W03 episode declares an impossible generator stratum")
        return result

    def _posterior(self, episode: PrivateEpisode) -> list[dict[str, Any]]:
        cache_key = self._semantic_history_key(episode)
        cached = self._posterior_cache.get(cache_key)
        if cached is not None:
            return cached
        x_nodes, x_weights = leggauss(16)
        d_nodes, d_weights = leggauss(64)
        d_lower, d_upper = _PUBLIC_DRIFT_PRIOR_BOUNDS
        components: list[dict[str, Any]] = []
        for c in (0, 1):
            for x_node, x_weight in zip(x_nodes, x_weights, strict=True):
                initial = 0.8 * float(x_node)
                for d_node, d_weight in zip(d_nodes, d_weights, strict=True):
                    d = (d_lower + d_upper) / 2.0 + (d_upper - d_lower) / 2.0 * float(d_node)
                    weight = 0.5 * float(x_weight) / 2.0 * float(d_weight) / 2.0
                    components.append(
                        {
                            "class_index": c,
                            "d": d,
                            "mean": np.array([initial]),
                            "covariance": np.zeros((1, 1)),
                            "weight": weight,
                            "log_weight": math.log(weight),
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
                variance, _ = _OBSERVATIONS[channel]
                value = float(event.payload["value"])
                for component in components:
                    mean, covariance, log_likelihood = _condition_scalar(
                        component["mean"],
                        component["covariance"],
                        np.array([1.0]),
                        value,
                        variance,
                    )
                    component["mean"] = mean
                    component["covariance"] = covariance
                    component["log_weight"] += log_likelihood
                _normalize_components(components)
            if tick < 0:
                u = _U3.get(actions.get(tick, "NoNewAction"), 0.0)
                for component in components:
                    sign = -1.0 if int(component["class_index"]) == 0 else 1.0
                    component["mean"] = component["mean"] + component["d"] * sign + 0.30 * u
                    component["covariance"] = component["covariance"] + _PROCESS_VARIANCE
        self._posterior_cache[cache_key] = components
        return components

    @staticmethod
    def _semantic_history_key(episode: PrivateEpisode) -> str:
        return digest_json(
            {
                "events": sorted(
                    (
                        {
                            "kind": event.kind.value,
                            "occurred_at": event.occurred_at,
                            "collected_at": event.collected_at,
                            "available_at": event.available_at,
                            "payload": event.payload,
                        }
                        for event in episode.public_history.events
                    ),
                    key=lambda value: canonical_json_bytes(value),
                ),
            }
        )

    @staticmethod
    def _rollout(
        components: list[dict[str, Any]],
        schedule: tuple[float, ...],
        check_cost: float,
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
            mean_total = 0.0
            second_total = 0.0
            cost = 0.0
            for component in working:
                sign = -1.0 if int(component["class_index"]) == 0 else 1.0
                component["mean"][0] += component["d"] * sign + 0.30 * u
                component["covariance"][0, 0] += _PROCESS_VARIANCE
                weight = float(component["weight"])
                mean = float(component["mean"][0])
                variance = float(component["covariance"][0, 0])
                mean_total += weight * mean
                second_total += weight * (variance + mean**2)
                cost += weight * (variance + mean**2 + 0.04 * u**2)
            variance_total = max(0.0, second_total - mean_total**2)
            utility -= 0.97**offset * cost
            steps.append(
                {
                    "offset": offset + 1,
                    "mean": _json_float(mean_total),
                    "variance": _json_float(variance_total),
                }
            )
        return steps, utility

    def _adaptive_integral(
        self,
        components: list[dict[str, Any]],
        horizon: int,
        order: int,
    ) -> tuple[list[dict[str, Any]], float, float]:
        retained = [
            component for component in components if float(component["weight"]) > 1e-6
        ]
        retained_mass = math.fsum(float(component["weight"]) for component in retained)
        active = [
            {
                **component,
                "mean": component["mean"].copy(),
                "covariance": component["covariance"].copy(),
                "weight": float(component["weight"]) / retained_mass,
                "log_weight": math.log(float(component["weight"]) / retained_mass),
            }
            for component in retained
        ]
        nodes, weights = hermgauss(order)
        first = [0.0] * horizon
        second = [0.0] * horizon
        utility = 0.0
        total_weight = 0.0
        observation_variance = 0.015**2
        h = np.array([1.0])
        for source in active:
            predictive_mean = float(source["mean"][0])
            predictive_variance = float(
                source["covariance"][0, 0] + observation_variance
            )
            for node, node_weight in zip(nodes, weights, strict=True):
                value = predictive_mean + math.sqrt(2.0 * predictive_variance) * float(node)
                outer_weight = (
                    float(source["weight"])
                    * float(node_weight)
                    / math.sqrt(math.pi)
                )
                conditioned: list[dict[str, Any]] = []
                for component in active:
                    mean, covariance, log_likelihood = _condition_scalar(
                        component["mean"],
                        component["covariance"],
                        h,
                        value,
                        observation_variance,
                    )
                    conditioned.append(
                        {
                            **component,
                            "mean": mean,
                            "covariance": covariance,
                            "log_weight": math.log(float(component["weight"]))
                            + log_likelihood,
                        }
                    )
                _normalize_components(conditioned)
                posterior_level = math.fsum(
                    float(component["weight"]) * float(component["mean"][0])
                    for component in conditioned
                )
                schedule = [0.0] * horizon
                if horizon > 1:
                    schedule[1] = -1.0 if posterior_level > 0.0 else 1.0
                branch_steps, branch_utility = self._rollout(
                    conditioned, tuple(schedule), 0.03
                )
                total_weight += outer_weight
                utility += outer_weight * branch_utility
                for offset, step in enumerate(branch_steps):
                    mean = float(step["mean"])
                    variance = float(step["variance"])
                    first[offset] += outer_weight * mean
                    second[offset] += outer_weight * (variance + mean**2)
        steps = []
        for offset in range(horizon):
            mean = first[offset] / total_weight
            variance = second[offset] / total_weight - mean**2
            steps.append(
                {
                    "offset": offset + 1,
                    "mean": _json_float(mean),
                    "variance": _json_float(max(0.0, variance)),
                }
            )
        return steps, utility / total_weight, 1.0 - retained_mass

    def _adaptive_value(
        self, episode: PrivateEpisode, components: list[dict[str, Any]], horizon: int
    ) -> tuple[list[dict[str, Any]], float, float, float]:
        key = (self._semantic_history_key(episode), horizon)
        cached = self._adaptive_cache.get(key)
        if cached is not None:
            return cached
        steps, utility, truncated_mass = self._adaptive_integral(
            components, horizon, order=6
        )
        _, coarse_utility, _ = self._adaptive_integral(
            components, horizon, order=3
        )
        result = (steps, utility, abs(utility - coarse_utility), truncated_mass)
        self._adaptive_cache[key] = result
        return result

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W03 horizon")
        components = self._posterior(episode)
        adaptive = (
            policy.kind is PlanKind.ACTION_SEQUENCE
            and len(policy.actions) == 1
            and bool(policy.actions[0].parameters.get("adaptive_rule"))
        )
        if adaptive:
            steps, utility, integration_error, truncated_mass = self._adaptive_value(
                episode, components, horizon
            )
            method = "deterministic-gauss-hermite-adaptive-mixture"
        else:
            schedule = _schedule(policy, horizon)
            check_cost = math.fsum(
                _OBSERVATIONS[action.action_id.replace("Q", "obs_")][1]
                for action in policy.actions
                if action.action_id in {"Q0", "Q1"}
            ) if policy.kind is PlanKind.ACTION_SEQUENCE else 0.0
            method = "gauss-legendre-mixture-linear-gaussian"
            steps, utility = self._rollout(components, schedule, check_cost)
            integration_error = 0.0
            truncated_mass = 0.0
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
                "family": "continuous-mixture",
                "channels": ["obs_0", "obs_1"],
                "steps": steps,
            },
            latent_distribution={
                "family": "class-drift-gaussian-mixture",
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
                "drift_quadrature_order": 64,
                "initial_state_quadrature_order": 16,
                "adaptive_quadrature_order": 6 if adaptive else 0,
                "adaptive_3_vs_6_error": _json_float(integration_error),
                "posterior_mass_truncated": _json_float(truncated_mass),
            },
        )

    def reference_counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        """Independent vectorized quadrature over the public trajectory.

        Unlike the production object-per-component filter, this path stores
        class, drift, Gaussian mean/variance and weights in parallel arrays.
        It does not call any production posterior/rollout/adaptive helper.
        """

        del oracle_seed
        if horizon not in (1, 4, 8):
            raise ValueError("unsupported W03 horizon")

        def clean(value: float) -> float:
            result = float(value)
            return 0.0 if result == 0.0 else result

        x_nodes, x_weights = leggauss(16)
        d_nodes, d_weights = leggauss(64)
        # Independent implementation of the same frozen public scoring prior.
        # The private train/validation/sealed-test identity must not enter the
        # posterior once the public history and query are fixed.
        d_lower, d_upper = 0.20, 0.30
        classes: list[int] = []
        drifts: list[float] = []
        means: list[float] = []
        variances: list[float] = []
        weights: list[float] = []
        log_weights: list[float] = []
        for mechanism in (0, 1):
            for x_node, x_weight in zip(x_nodes, x_weights, strict=True):
                initial = 0.8 * float(x_node)
                for d_node, d_weight in zip(d_nodes, d_weights, strict=True):
                    drift = (
                        (d_lower + d_upper) / 2.0
                        + (d_upper - d_lower) / 2.0 * float(d_node)
                    )
                    weight = 0.5 * float(x_weight) / 2.0 * float(d_weight) / 2.0
                    classes.append(mechanism)
                    drifts.append(drift)
                    means.append(initial)
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
                noise = 0.04**2 if channel == "obs_0" else 0.015**2
                observed = float(event.payload["value"])
                for index in range(len(means)):
                    innovation = variances[index] + noise
                    residual = observed - means[index]
                    gain = variances[index] / innovation
                    means[index] += gain * residual
                    variances[index] -= gain * variances[index]
                    log_weights[index] += -0.5 * (
                        math.log(2.0 * math.pi * innovation)
                        + residual * residual / innovation
                    )
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
                dose = -1.0 if action == "A1" else 1.0 if action == "A2" else 0.0
                for index in range(len(means)):
                    direction = -1.0 if classes[index] == 0 else 1.0
                    means[index] += drifts[index] * direction + 0.30 * dose
                    variances[index] += 0.035**2

        def project(
            branch_classes: list[int],
            branch_drifts: list[float],
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
                for index in range(len(active_means)):
                    direction = -1.0 if branch_classes[index] == 0 else 1.0
                    active_means[index] += branch_drifts[index] * direction + 0.30 * dose
                    active_variances[index] += 0.035**2
                mean = math.fsum(
                    weight * value
                    for weight, value in zip(branch_weights, active_means, strict=True)
                )
                second = math.fsum(
                    weight * (variance + value * value)
                    for weight, value, variance in zip(
                        branch_weights, active_means, active_variances, strict=True
                    )
                )
                variance = max(0.0, second - mean * mean)
                cost = math.fsum(
                    weight * (spread + value * value + 0.04 * dose * dose)
                    for weight, value, spread in zip(
                        branch_weights, active_means, active_variances, strict=True
                    )
                )
                utility -= 0.97**offset * cost
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
                            doses[action.offset] = -1.0
                        elif action.action_id == "A2":
                            doses[action.offset] = 1.0
                    if action.action_id == "Q1":
                        check_cost += 0.03
            steps, utility = project(
                classes, drifts, means, variances, weights, doses, check_cost
            )
            method = "independent-parallel-array-legendre-filter"
            truncated_mass = 0.0
        else:
            retained = [index for index, weight in enumerate(weights) if weight > 1e-6]
            retained_mass = math.fsum(weights[index] for index in retained)
            a_classes = [classes[index] for index in retained]
            a_drifts = [drifts[index] for index in retained]
            a_means = [means[index] for index in retained]
            a_variances = [variances[index] for index in retained]
            a_weights = [weights[index] / retained_mass for index in retained]
            nodes, node_weights = hermgauss(6)
            first = [0.0] * horizon
            second = [0.0] * horizon
            utility_sum = 0.0
            total_mass = 0.0
            for source in range(len(a_means)):
                predictive_variance = a_variances[source] + 0.015**2
                for node, node_weight in zip(nodes, node_weights, strict=True):
                    observed = a_means[source] + math.sqrt(
                        2.0 * predictive_variance
                    ) * float(node)
                    outer = (
                        a_weights[source] * float(node_weight) / math.sqrt(math.pi)
                    )
                    b_means: list[float] = []
                    b_variances: list[float] = []
                    b_log_weights: list[float] = []
                    for mean, variance, weight in zip(
                        a_means, a_variances, a_weights, strict=True
                    ):
                        innovation = variance + 0.015**2
                        residual = observed - mean
                        gain = variance / innovation
                        b_means.append(mean + gain * residual)
                        b_variances.append(variance - gain * variance)
                        b_log_weights.append(
                            math.log(weight)
                            - 0.5
                            * (
                                math.log(2.0 * math.pi * innovation)
                                + residual * residual / innovation
                            )
                        )
                    peak = max(b_log_weights)
                    raw = [math.exp(value - peak) for value in b_log_weights]
                    denominator = math.fsum(raw)
                    b_weights = [value / denominator for value in raw]
                    level = math.fsum(
                        weight * mean
                        for weight, mean in zip(b_weights, b_means, strict=True)
                    )
                    doses = [0.0] * horizon
                    if horizon > 1:
                        doses[1] = -1.0 if level > 0.0 else 1.0
                    branch_steps, branch_utility = project(
                        a_classes,
                        a_drifts,
                        b_means,
                        b_variances,
                        b_weights,
                        doses,
                        0.03,
                    )
                    total_mass += outer
                    utility_sum += outer * branch_utility
                    for offset, row in enumerate(branch_steps):
                        mean = float(row["mean"])
                        variance = float(row["variance"])
                        first[offset] += outer * mean
                        second[offset] += outer * (variance + mean * mean)
            steps = []
            for offset in range(horizon):
                mean = first[offset] / total_mass
                variance = second[offset] / total_mass - mean * mean
                steps.append(
                    {
                        "offset": offset + 1,
                        "mean": clean(mean),
                        "variance": clean(max(0.0, variance)),
                    }
                )
            utility = utility_sum / total_mass
            method = "independent-vectorized-hermite-public-mixture"
            truncated_mass = 1.0 - retained_mass

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
                "family": "continuous-mixture",
                "channels": ["obs_0", "obs_1"],
                "steps": steps,
            },
            latent_distribution={
                "family": "class-drift-gaussian-mixture",
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
                "drift_quadrature_order": 64,
                "initial_state_quadrature_order": 16,
                "adaptive_quadrature_order": 6 if adaptive else 0,
                "posterior_mass_truncated": clean(truncated_mass),
                "private_state_used": False,
            },
        )

    def _fixture_episode(
        self, values: tuple[float, ...], seed: int, salt: int
    ) -> PrivateEpisode:
        events = [
            _observation_event(
                seed + salt,
                "obs_0",
                value,
                collected_at=tick,
                available_at=tick,
                slot=position,
            )
            for position, (tick, value) in enumerate(zip(range(-4, 1), values, strict=True))
        ]
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, salt),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"fixture_realization": salt},
            invariant_parameters={"fixture": "opposite-trend"},
            diagnostic_target={"C0": 0.5, "C1": 0.5},
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={
                "fixture": "paired",
                "strata": ["iid_support", "behavior_pair"],
            },
        )

    def collision_fixture(self, seed: int = 301) -> tuple[PrivateEpisode, PrivateEpisode]:
        # The last value is exactly equal; the ordered slopes are opposite.
        return (
            self._fixture_episode((0.80, 0.60, 0.40, 0.20, 0.0), seed, 1),
            self._fixture_episode((-0.80, -0.60, -0.40, -0.20, 0.0), seed, 2),
        )

    def false_split_fixture(self, seed: int = 303) -> tuple[PrivateEpisode, PrivateEpisode]:
        first = self._fixture_episode((0.5, 0.3, 0.1, -0.1, -0.3), seed, 7)
        events = tuple(
            replace(event, event_uid=_opaque_uid(seed + 77, "alpha", index))
            for index, event in enumerate(first.public_history.events)
        )
        second = replace(
            first,
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, 8),
            public_history=_visible_history(events, self.catalog),
        )
        return first, second


World = W03World


__all__ = ["W03World", "World"]
