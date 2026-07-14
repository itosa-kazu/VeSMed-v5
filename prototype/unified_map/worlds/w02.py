"""W02: partially observed two-dimensional linear system.

The judge posterior is an exact two-component Kalman mixture for every fixed
policy.  The two frozen check-then-treat policies use deterministic nested
Gauss-Hermite integration and report their 16-vs-32-node discrepancy.
"""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any

import numpy as np
from numpy.polynomial.hermite import hermgauss

from ..schema import ActionPlan, EventKind, PlanKind, PlannedAction
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
from .randomness import categorical, normal01
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


_A = {
    0: np.array([[0.85, 0.25], [-0.10, 0.80]], dtype=float),
    1: np.array([[0.85, -0.25], [0.10, 0.80]], dtype=float),
}
_B = np.array([-0.30, 0.12], dtype=float)
_Q = np.diag([0.06**2, 0.06**2])
_CHECKS: dict[str, tuple[np.ndarray, float, int, float]] = {
    "Q0": (np.array([1.0, 1.0]), 0.18**2, 0, 0.01),
    "Q1": (np.array([1.0, 0.0]), 0.08**2, 1, 0.04),
    "Q2": (np.array([0.0, 1.0]), 0.08**2, 1, 0.04),
}
_CHANNEL_TO_CHECK = {"obs_0": "Q0", "obs_1": "Q1", "obs_2": "Q2"}


def _normal_logpdf(value: float, mean: float, variance: float) -> float:
    return -0.5 * (
        math.log(2.0 * math.pi * variance) + (value - mean) ** 2 / variance
    )


def _condition_scalar(
    mean: np.ndarray,
    covariance: np.ndarray,
    h: np.ndarray,
    value: float,
    noise_variance: float,
) -> tuple[np.ndarray, np.ndarray, float]:
    predicted = float(h @ mean)
    innovation_variance = float(h @ covariance @ h + noise_variance)
    gain = covariance @ h / innovation_variance
    updated_mean = mean + gain * (value - predicted)
    updated_covariance = covariance - np.outer(gain, h @ covariance)
    updated_covariance = 0.5 * (updated_covariance + updated_covariance.T)
    return (
        updated_mean,
        updated_covariance,
        _normal_logpdf(value, predicted, innovation_variance),
    )


def _normalize_components(components: list[dict[str, Any]]) -> None:
    maximum = max(float(component["log_weight"]) for component in components)
    raw = [math.exp(float(component["log_weight"]) - maximum) for component in components]
    total = math.fsum(raw)
    for component, value in zip(components, raw, strict=True):
        normalized = value / total
        component["weight"] = normalized
        component["log_weight"] = math.log(normalized) if normalized > 0.0 else -math.inf


def _action_by_tick(episode: PrivateEpisode) -> dict[int, str]:
    return {
        event.occurred_at: str(event.payload["action_id"])
        for event in episode.public_history.events
        if event.kind is EventKind.PERFORMED_TREATMENT
    }


class W02World(MicroWorld):
    @property
    def environment_key(self) -> str:
        return "ucm-private-environment-02"

    @property
    def catalog(self) -> PublicCatalog:
        return PublicCatalog(
            observations=(
                ChannelSpec("obs_0"),
                ChannelSpec("obs_1"),
                ChannelSpec("obs_2"),
            ),
            actions=(ActionSpec("A1", cost=0.05), ActionSpec("A2", cost=0.05)),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.01),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.04),
                CheckSpec("Q2", ("obs_2",), (1, 1), cost=0.04),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W02 horizon")
        policies = list(
            _standard_policy_set(horizon, checks=("Q0", "Q1", "Q2"))
        )
        if horizon > 1:
            policies.extend(
                (
                    _check_plan(
                        "Q1",
                        {
                            "adaptive_rule": "A1_if_posterior_coordinate_positive_else_A2",
                            "coordinate": 0,
                        },
                    ),
                    _check_plan(
                        "Q2",
                        {
                            "adaptive_rule": "A1_if_posterior_coordinate_positive_else_A2",
                            "coordinate": 1,
                        },
                    ),
                )
            )
        return tuple(policies)

    @staticmethod
    def _check_probabilities(last_q0: float) -> tuple[float, float, float]:
        q1 = 0.275 + 0.15 / (1.0 + math.exp(-(abs(last_q0) - 0.5)))
        base = (0.45, q1, 1.0 - 0.45 - q1)
        return _exploratory_probabilities(base)

    @staticmethod
    def _action_probabilities(last_q0: float) -> tuple[float, float, float]:
        return _exploratory_probabilities(
            _softmax((0.0, 0.9 * last_q0, -0.9 * last_q0))
        )

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        requested_seed = generator_seed
        generator_seed = _split_rng_seed(generator_seed, split)
        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        c = episode_index % 2
        state = np.array(
            [
                0.8 * normal01(generator_seed, "w02", "initial", episode_index, 0),
                0.8 * normal01(generator_seed, "w02", "initial", episode_index, 1),
            ],
            dtype=float,
        )
        # Validation changes only the prior correlation stratum.
        if split is WorldSplit.VALIDATION:
            corr = (-0.35, 0.0, 0.35)[episode_index % 3]
            state[1] = corr * state[0] + math.sqrt(1.0 - corr**2) * state[1]

        events = []
        propensities: list[dict[str, Any]] = []
        latest_q0 = 0.0
        previous_check: str | None = None
        for tick in range(-4, 1):
            check_probabilities = self._check_probabilities(latest_q0)
            forced_check: int | None = None
            if tick == 0:
                forced_check = 0
            elif split is WorldSplit.SEALED_TEST and episode_index % 5 == 1:
                # Sparse stratum: exactly one targeted check in the prefix.
                forced_check = 1 if tick == -1 else 0
            elif split is WorldSplit.SEALED_TEST and episode_index % 5 == 2:
                # Q2->Q1 order-combination holdout.
                forced_check = {-2: 2, -1: 1}.get(tick, 0)
            if forced_check is not None:
                check_index = forced_check
                actual_check_probabilities = tuple(
                    1.0 if index == check_index else 0.0 for index in range(3)
                )
            else:
                check_index = categorical(
                    check_probabilities,
                    generator_seed,
                    "w02",
                    "check",
                    episode_index,
                    tick,
                )
                # The train corpus withholds consecutive Q2->Q1 only; both
                # checks retain support in every other ordering.
                if (
                    split is WorldSplit.TRAIN
                    and previous_check == "Q2"
                    and check_index == 1
                ):
                    check_index = 0
                    actual_check_probabilities = (
                        check_probabilities[0] + check_probabilities[1],
                        0.0,
                        check_probabilities[2],
                    )
                else:
                    actual_check_probabilities = check_probabilities
            check_id = ("Q0", "Q1", "Q2")[check_index]
            h, variance, delay, _ = _CHECKS[check_id]
            observation = float(h @ state) + math.sqrt(variance) * normal01(
                generator_seed, "w02", "observation", episode_index, tick, check_id
            )
            events.extend(
                (
                    _check_event(
                        generator_seed,
                        check_id,
                        tick,
                        performed=False,
                        slot=episode_index * 64,
                    ),
                    _check_event(
                        generator_seed,
                        check_id,
                        tick,
                        performed=True,
                        slot=episode_index * 64,
                    ),
                    _observation_event(
                        generator_seed,
                        f"obs_{check_index}",
                        observation,
                        collected_at=tick,
                        available_at=tick + delay,
                        slot=episode_index * 64,
                    ),
                )
            )
            if check_id == "Q0":
                latest_q0 = observation
            propensities.append(
                {
                    "decision_at": tick,
                    "kind": "check",
                    "probabilities": {
                        "Q0": actual_check_probabilities[0],
                        "Q1": actual_check_probabilities[1],
                        "Q2": actual_check_probabilities[2],
                    },
                    "selected": check_id,
                }
            )
            previous_check = check_id
            if tick == 0:
                break
            action_probabilities = self._action_probabilities(latest_q0)
            randomized_probe = (
                split is WorldSplit.TRAIN
                and episode_index % 10 < 2
                and tick == -4
            )
            actual_action_probabilities = (
                (1.0 / 3.0,) * 3 if randomized_probe else action_probabilities
            )
            action_index = categorical(
                actual_action_probabilities,
                generator_seed,
                "w02",
                "action",
                episode_index,
                tick,
            )
            action_id = ("NoNewAction", "A1", "A2")[action_index]
            propensities.append(
                {
                    "decision_at": tick,
                    "kind": "treatment",
                    "probabilities": {
                        "NoNewAction": actual_action_probabilities[0],
                        "A1": actual_action_probabilities[1],
                        "A2": actual_action_probabilities[2],
                    },
                    "selected": action_id,
                    "randomized_probe": randomized_probe,
                }
            )
            if action_id != "NoNewAction":
                events.append(
                    _treatment_event(
                        generator_seed,
                        action_id,
                        tick,
                        slot=episode_index * 64,
                    )
                )
            state = (
                _A[c] @ state
                + _B * _U.get(action_id, 0.0)
                + np.array(
                    [
                        0.06
                        * normal01(
                            generator_seed,
                            "w02",
                            "process",
                            episode_index,
                            tick + 1,
                            dimension,
                        )
                        for dimension in range(2)
                    ]
                )
            )

        public_history = _visible_history(events, self.catalog)
        state_at_cut = state.copy()
        factual_future: list[dict[str, Any]] = []
        factual_utility = 0.0
        future_last_q0 = latest_q0
        for offset in range(4):
            # The trainer stream records one supported factual continuation.
            probabilities = self._action_probabilities(future_last_q0)
            selected = categorical(
                probabilities,
                generator_seed,
                "w02",
                "future-action",
                episode_index,
                offset,
            )
            action_id = ("NoNewAction", "A1", "A2")[selected]
            u = _U.get(action_id, 0.0)
            state = _A[c] @ state + _B * u + np.array(
                [
                    0.06
                    * normal01(
                        generator_seed,
                        "w02",
                        "future-process",
                        episode_index,
                        offset,
                        dimension,
                    )
                    for dimension in range(2)
                ]
            )
            future_last_q0 = float(state.sum()) + 0.18 * normal01(
                generator_seed,
                "w02",
                "future-q0",
                episode_index,
                offset,
            )
            factual_utility -= 0.97**offset * float(
                state[0] ** 2 + 0.7 * state[1] ** 2 + 0.05 * u**2
            )
            factual_future.append(
                {
                    "offset": offset + 1,
                    "latent_outcome": [_json_float(value) for value in state],
                    "available_observation": {
                        "channel_id": "obs_0",
                        "value": _json_float(future_last_q0),
                    },
                    "performed_action": action_id,
                }
            )

        return PrivateEpisode(
            case_key=_case_key(self.environment_key, split, generator_seed, episode_index),
            environment_key=self.environment_key,
            split=split,
            generator_seed=requested_seed,
            public_history=public_history,
            hidden_state_at_cut={"x": [_json_float(value) for value in state_at_cut]},
            invariant_parameters={"class_index": c},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=factual_future,
            action_propensities=propensities,
            factual_utility=_json_float(factual_utility),
            oracle_anchor={"posterior": "two-component-kalman-mixture"},
        )

    def _posterior(self, episode: PrivateEpisode) -> list[dict[str, Any]]:
        components: list[dict[str, Any]] = [
            {
                "class_index": c,
                "mean": np.zeros(2),
                "covariance": np.diag([0.8**2, 0.8**2]),
                "weight": 0.5,
                "log_weight": math.log(0.5),
            }
            for c in (0, 1)
        ]
        observations: dict[int, list[Any]] = {}
        for event in episode.public_history.events:
            if event.kind is EventKind.OBSERVATION_AVAILABLE:
                observations.setdefault(int(event.collected_at), []).append(event)
        actions = _action_by_tick(episode)
        for tick in range(-4, 1):
            for event in sorted(observations.get(tick, []), key=lambda item: item.event_uid):
                check_id = _CHANNEL_TO_CHECK[str(event.payload["channel_id"])]
                h, variance, _, _ = _CHECKS[check_id]
                value = float(event.payload["value"])
                for component in components:
                    mean, covariance, log_likelihood = _condition_scalar(
                        component["mean"],
                        component["covariance"],
                        h,
                        value,
                        variance,
                    )
                    component["mean"] = mean
                    component["covariance"] = covariance
                    component["log_weight"] += log_likelihood
                _normalize_components(components)
            if tick < 0:
                u = _U.get(actions.get(tick, "NoNewAction"), 0.0)
                for component in components:
                    matrix = _A[int(component["class_index"])]
                    component["mean"] = matrix @ component["mean"] + _B * u
                    component["covariance"] = (
                        matrix @ component["covariance"] @ matrix.T + _Q
                    )
        return components

    @staticmethod
    def _fixed_rollout(
        components: list[dict[str, Any]],
        schedule: tuple[float, ...],
        *,
        check_cost: float = 0.0,
    ) -> tuple[list[dict[str, Any]], float]:
        working = [
            {
                **component,
                "mean": component["mean"].copy(),
                "covariance": component["covariance"].copy(),
            }
            for component in components
        ]
        steps: list[dict[str, Any]] = []
        utility = -check_cost
        for offset, u in enumerate(schedule):
            total_mean = np.zeros(2)
            total_second = np.zeros((2, 2))
            expected_cost = 0.0
            for component in working:
                matrix = _A[int(component["class_index"])]
                component["mean"] = matrix @ component["mean"] + _B * u
                component["covariance"] = (
                    matrix @ component["covariance"] @ matrix.T + _Q
                )
                weight = float(component["weight"])
                mean = component["mean"]
                covariance = component["covariance"]
                total_mean += weight * mean
                total_second += weight * (covariance + np.outer(mean, mean))
                expected_cost += weight * (
                    mean[0] ** 2
                    + covariance[0, 0]
                    + 0.7 * (mean[1] ** 2 + covariance[1, 1])
                    + 0.05 * u**2
                )
            total_covariance = total_second - np.outer(total_mean, total_mean)
            utility -= 0.97**offset * float(expected_cost)
            steps.append(
                {
                    "offset": offset + 1,
                    "mean": [_json_float(value) for value in total_mean],
                    "covariance": [
                        [_json_float(value) for value in row]
                        for row in total_covariance
                    ],
                }
            )
        return steps, float(utility)

    def _adaptive_value(
        self,
        components: list[dict[str, Any]],
        horizon: int,
        check_id: str,
        quadrature_order: int,
    ) -> tuple[list[dict[str, Any]], float]:
        h, noise_variance, _, check_cost = _CHECKS[check_id]
        nodes, weights = hermgauss(quadrature_order)
        aggregate_steps: list[dict[str, Any]] = []
        first_moments = [np.zeros(2) for _ in range(horizon)]
        second_moments = [np.zeros((2, 2)) for _ in range(horizon)]
        expected_utility = 0.0
        total_outer_weight = 0.0
        coordinate = 0 if check_id == "Q1" else 1
        for source in components:
            predictive_mean = float(h @ source["mean"])
            predictive_variance = float(
                h @ source["covariance"] @ h + noise_variance
            )
            for node, node_weight in zip(nodes, weights, strict=True):
                value = predictive_mean + math.sqrt(2.0 * predictive_variance) * float(node)
                outer_weight = float(source["weight"]) * float(node_weight) / math.sqrt(math.pi)
                conditioned: list[dict[str, Any]] = []
                for component in components:
                    mean, covariance, log_likelihood = _condition_scalar(
                        component["mean"],
                        component["covariance"],
                        h,
                        value,
                        noise_variance,
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
                posterior_coordinate = math.fsum(
                    float(component["weight"])
                    * float(component["mean"][coordinate])
                    for component in conditioned
                )
                # Result is available after one tick, so treatment starts at offset 1.
                schedule = [0.0] * horizon
                if horizon > 1:
                    schedule[1] = 1.0 if posterior_coordinate > 0.0 else -1.0
                steps, utility = self._fixed_rollout(
                    conditioned, tuple(schedule), check_cost=check_cost
                )
                total_outer_weight += outer_weight
                expected_utility += outer_weight * utility
                for offset, step in enumerate(steps):
                    mean = np.array(step["mean"], dtype=float)
                    covariance = np.array(step["covariance"], dtype=float)
                    first_moments[offset] += outer_weight * mean
                    second_moments[offset] += outer_weight * (
                        covariance + np.outer(mean, mean)
                    )
        for offset in range(horizon):
            mean = first_moments[offset] / total_outer_weight
            covariance = second_moments[offset] / total_outer_weight - np.outer(mean, mean)
            aggregate_steps.append(
                {
                    "offset": offset + 1,
                    "mean": [_json_float(value) for value in mean],
                    "covariance": [
                        [_json_float(value) for value in row] for row in covariance
                    ],
                }
            )
        return aggregate_steps, expected_utility / total_outer_weight

    @staticmethod
    def _adaptive_check(policy: ActionPlan) -> str | None:
        if policy.kind is not PlanKind.ACTION_SEQUENCE or len(policy.actions) != 1:
            return None
        action = policy.actions[0]
        if action.parameters.get("adaptive_rule"):
            return action.action_id
        return None

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W02 horizon")
        components = self._posterior(episode)
        adaptive_check = self._adaptive_check(policy)
        if adaptive_check:
            steps, utility = self._adaptive_value(
                components, horizon, adaptive_check, quadrature_order=32
            )
            _, coarse_utility = self._adaptive_value(
                components, horizon, adaptive_check, quadrature_order=16
            )
            method = "deterministic-gauss-hermite-mixture"
            error_bound = abs(utility - coarse_utility)
        else:
            schedule = _treatment_schedule(policy, horizon)
            check_cost = 0.0
            if policy.kind is PlanKind.ACTION_SEQUENCE:
                check_cost = math.fsum(
                    _CHECKS[action.action_id][3]
                    for action in policy.actions
                    if action.action_id in _CHECKS
                )
            steps, utility = self._fixed_rollout(
                components, schedule, check_cost=check_cost
            )
            method = "analytic-class-kalman-mixture"
            error_bound = 0.0
        class_posterior = {
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
                "family": "gaussian-mixture",
                "channels": ["obs_0", "obs_1", "obs_2"],
                "latent_moment_projection": steps,
            },
            latent_distribution={
                "family": "class-conditioned-gaussian-mixture",
                "diagnostic_posterior": {
                    key: _json_float(value) for key, value in class_posterior.items()
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
                "absolute_error_estimate": _json_float(error_bound),
                "quadrature_order": 32 if adaptive_check else 0,
            },
        )

    def _fixture_episode(
        self,
        values: tuple[tuple[int, str, float], ...],
        seed: int,
        salt: int,
    ) -> PrivateEpisode:
        events = [
            _observation_event(
                seed + salt,
                channel,
                value,
                collected_at=tick,
                available_at=tick,
                slot=position,
            )
            for position, (tick, channel, value) in enumerate(values)
        ]
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, salt),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"fixture_realization": salt & 1},
            invariant_parameters={"fixture": "posterior-pair"},
            diagnostic_target={"C0": 0.5, "C1": 0.5},
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={"fixture": "paired"},
        )

    def collision_fixture(self, seed: int = 201) -> tuple[PrivateEpisode, PrivateEpisode]:
        common = ((-4, "obs_0", 0.0), (-2, "obs_0", 0.0), (0, "obs_0", 0.0))
        return (
            self._fixture_episode(common + ((0, "obs_1", 0.85),), seed, 1),
            self._fixture_episode(common + ((0, "obs_1", -0.85),), seed, 2),
        )

    def false_split_fixture(self, seed: int = 203) -> tuple[PrivateEpisode, PrivateEpisode]:
        first = self.generate_episode(WorldSplit.SEALED_TEST, seed, 7)
        renamed_events = tuple(
            replace(
                event,
                event_uid=_opaque_uid(seed + 999, "alpha", position, event.kind.value),
            )
            for position, event in enumerate(first.public_history.events)
        )
        second = replace(
            first,
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, 8),
            public_history=_visible_history(renamed_events, self.catalog),
        )
        return first, second

    def future_leak_fixture(self, seed: int = 205) -> tuple[PrivateEpisode, PrivateEpisode]:
        first = self.generate_episode(WorldSplit.SEALED_TEST, seed, 10)
        second = replace(
            first,
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, 11),
            hidden_state_at_cut={"x": [99.0, -99.0]},
            invariant_parameters={"class_index": 1 - int(first.invariant_parameters["class_index"])},
            factual_future=[{"different_private_future": True}],
        )
        return first, second


World = W02World


__all__ = ["W02World", "World"]
