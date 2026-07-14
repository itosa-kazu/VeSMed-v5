"""W05: internal treatment reservoir with a two-step routine-observation lag."""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any

import numpy as np
from numpy.polynomial.legendre import leggauss

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
from .randomness import bernoulli, categorical, normal01, uniform01
from .w01 import (
    _U,
    _case_key,
    _check_event,
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


_LAMBDA = {0: 0.35, 1: 0.65}
_PROCESS_VARIANCE = 0.045**2
_Q0_VARIANCE = 0.05**2
_Q1_VARIANCE = 0.10**2


def _transition(class_index: int, dose: float) -> tuple[np.ndarray, np.ndarray]:
    decay = _LAMBDA[class_index]
    matrix = np.array(
        [
            [0.94, -0.50 * decay, 0.0, 0.0],
            [0.0, decay, 0.0, 0.0],
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ],
        dtype=float,
    )
    intercept = np.array([0.12 - 0.40 * dose, 0.80 * dose, 0.0, 0.0])
    return matrix, intercept


class W05World(MicroWorld):
    def __init__(self) -> None:
        self._posterior_cache: dict[str, list[dict[str, Any]]] = {}

    @property
    def environment_key(self) -> str:
        return "ucm-private-environment-05"

    @property
    def catalog(self) -> PublicCatalog:
        return PublicCatalog(
            observations=(ChannelSpec("obs_0"), ChannelSpec("obs_1")),
            actions=(ActionSpec("A1", cost=0.05), ActionSpec("A2", cost=0.05)),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.08),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W05 horizon")
        policies = list(_standard_policy_set(horizon, checks=("Q0", "Q1")))
        if horizon > 1:
            policies.append(
                ActionPlan(
                    PlanKind.ACTION_SEQUENCE,
                    (
                        PlannedAction(0, "A1"),
                        PlannedAction(1, "Q1", {"purpose": "post-dose-internal-check"}),
                    ),
                )
            )
        return tuple(policies)

    @staticmethod
    def _action_probabilities(y: float, dy: float) -> tuple[float, float, float]:
        return _exploratory_probabilities(
            _softmax((0.3, 0.9 * y + 0.4 * dy, -0.9 * y - 0.4 * dy))
        )

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        requested_seed = generator_seed
        generator_seed = _split_rng_seed(generator_seed, split)
        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        c = episode_index % 2
        x = 1.5 * uniform01(generator_seed, "w05", "initial-x", episode_index)
        r = -0.3 + 0.6 * uniform01(
            generator_seed, "w05", "initial-r", episode_index
        )
        state = np.array([x, r, x, x], dtype=float)
        events = []
        propensities: list[dict[str, Any]] = []
        q0_values: list[float] = []
        design_group = (episode_index // 2) % 4
        if split is WorldSplit.TRAIN:
            forced_action_tick = -1 if design_group % 2 == 0 else None
        elif split is WorldSplit.VALIDATION:
            forced_action_tick = -(design_group + 1)
        elif design_group == 0:
            forced_action_tick = -1
        elif design_group == 1:
            forced_action_tick = -3
        else:
            forced_action_tick = None
        force_q1 = split is WorldSplit.VALIDATION and design_group % 2 == 0
        suppress_q1 = split is WorldSplit.VALIDATION and not force_q1
        for tick in range(-4, 1):
            # Q0 is current-time available but reads the two-step buffer entry.
            q0 = state[3] + 0.05 * normal01(
                generator_seed, "w05", "q0", episode_index, tick
            )
            q0_values.append(q0)
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
            dy = q0_values[-1] - q0_values[-2] if len(q0_values) >= 2 else 0.0
            q1_probability = 0.10 + 0.35 / (
                1.0 + math.exp(-(abs(dy) - 0.15))
            )
            q1_probability = 0.9 * q1_probability + 0.1 * 0.5
            forced_q1_now = force_q1 and tick == -1
            q1_ordered = False if suppress_q1 else (
                forced_q1_now
                or (
                    tick < 0
                    and bernoulli(
                        q1_probability,
                        generator_seed,
                        "w05",
                        "q1-order",
                        episode_index,
                        tick,
                    )
                )
            )
            actual_q1_probability = (
                0.0 if suppress_q1 else (1.0 if forced_q1_now else q1_probability)
            )
            if q1_ordered:
                q1 = state[0] + 0.10 * normal01(
                    generator_seed, "w05", "q1", episode_index, tick
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
            probabilities = self._action_probabilities(q0, dy)
            if tick == forced_action_tick:
                selected = 1
                actual_probabilities = (0.0, 1.0, 0.0)
            else:
                selected = categorical(
                    probabilities,
                    generator_seed,
                    "w05",
                    "action",
                    episode_index,
                    tick,
                )
                actual_probabilities = probabilities
            action_id = ("NoNewAction", "A1", "A2")[selected]
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
                    "design_forced": tick == forced_action_tick,
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
            matrix, intercept = _transition(c, _U.get(action_id, 0.0))
            state = matrix @ state + intercept
            state[0] += 0.045 * normal01(
                generator_seed, "w05", "process", episode_index, tick + 1
            )

        public_history = _visible_history(events, self.catalog)
        state_at_cut = state.copy()
        future: list[dict[str, Any]] = []
        factual_utility = 0.0
        for offset in range(4):
            dy = q0_values[-1] - q0_values[-2]
            probabilities = self._action_probabilities(q0_values[-1], dy)
            selected = categorical(
                probabilities,
                generator_seed,
                "w05",
                "future-action",
                episode_index,
                offset,
            )
            action_id = ("NoNewAction", "A1", "A2")[selected]
            matrix, intercept = _transition(c, _U.get(action_id, 0.0))
            state = matrix @ state + intercept
            state[0] += 0.045 * normal01(
                generator_seed,
                "w05",
                "future-process",
                episode_index,
                offset,
            )
            factual_utility -= 0.97**offset * (
                state[0] ** 2 + 0.05 * float(action_id != "NoNewAction")
            )
            future.append(
                {
                    "offset": offset + 1,
                    "latent_internal_level": _json_float(state[0]),
                    "delayed_routine_observation": _json_float(state[3]),
                    "performed_action": action_id,
                }
            )
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, split, generator_seed, episode_index),
            environment_key=self.environment_key,
            split=split,
            generator_seed=requested_seed,
            public_history=public_history,
            hidden_state_at_cut={
                "x": _json_float(state_at_cut[0]),
                "reservoir": _json_float(state_at_cut[1]),
                "delay_buffer": [_json_float(state_at_cut[2]), _json_float(state_at_cut[3])],
            },
            invariant_parameters={"class_index": c, "reservoir_decay": _LAMBDA[c]},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=_json_float(factual_utility),
            oracle_anchor={"augmented_state": ["x", "reservoir", "x_lag_1", "x_lag_2"]},
        )

    def _posterior(self, episode: PrivateEpisode) -> list[dict[str, Any]]:
        cached = self._posterior_cache.get(episode.public_history.digest)
        if cached is not None:
            return cached
        x_nodes, x_weights = leggauss(16)
        r_nodes, r_weights = leggauss(16)
        components: list[dict[str, Any]] = []
        for c in (0, 1):
            for x_node, x_weight in zip(x_nodes, x_weights, strict=True):
                x = 0.75 + 0.75 * float(x_node)
                for r_node, r_weight in zip(r_nodes, r_weights, strict=True):
                    r = 0.30 * float(r_node)
                    weight = 0.5 * float(x_weight) / 2.0 * float(r_weight) / 2.0
                    components.append(
                        {
                            "class_index": c,
                            "mean": np.array([x, r, x, x], dtype=float),
                            "covariance": np.zeros((4, 4)),
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
                if channel == "obs_0":
                    h = np.array([0.0, 0.0, 0.0, 1.0])
                    variance = _Q0_VARIANCE
                else:
                    h = np.array([1.0, 0.0, 0.0, 0.0])
                    variance = _Q1_VARIANCE
                value = float(event.payload["value"])
                for component in components:
                    mean, covariance, log_likelihood = _condition_scalar(
                        component["mean"], component["covariance"], h, value, variance
                    )
                    component["mean"] = mean
                    component["covariance"] = covariance
                    component["log_weight"] += log_likelihood
                _normalize_components(components)
            if tick < 0:
                dose = _U.get(actions.get(tick, "NoNewAction"), 0.0)
                for component in components:
                    matrix, intercept = _transition(int(component["class_index"]), dose)
                    component["mean"] = matrix @ component["mean"] + intercept
                    component["covariance"] = matrix @ component["covariance"] @ matrix.T
                    component["covariance"][0, 0] += _PROCESS_VARIANCE
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
        utility = -check_cost
        steps = []
        for offset, dose in enumerate(schedule):
            mean_total = np.zeros(4)
            second_total = np.zeros((4, 4))
            expected_cost = 0.0
            for component in working:
                matrix, intercept = _transition(int(component["class_index"]), dose)
                component["mean"] = matrix @ component["mean"] + intercept
                component["covariance"] = matrix @ component["covariance"] @ matrix.T
                component["covariance"][0, 0] += _PROCESS_VARIANCE
                weight = float(component["weight"])
                mean = component["mean"]
                covariance = component["covariance"]
                mean_total += weight * mean
                second_total += weight * (covariance + np.outer(mean, mean))
                expected_cost += weight * (
                    mean[0] ** 2 + covariance[0, 0] + 0.05 * float(dose != 0.0)
                )
            covariance_total = second_total - np.outer(mean_total, mean_total)
            utility -= 0.97**offset * expected_cost
            steps.append(
                {
                    "offset": offset + 1,
                    "internal_mean": _json_float(mean_total[0]),
                    "internal_variance": _json_float(max(0.0, covariance_total[0, 0])),
                    "reservoir_mean": _json_float(mean_total[1]),
                    "routine_observation_mean": _json_float(mean_total[3]),
                    "routine_observation_variance": _json_float(
                        max(0.0, covariance_total[3, 3] + _Q0_VARIANCE)
                    ),
                }
            )
        return steps, utility

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W05 horizon")
        components = self._posterior(episode)
        check_cost = 0.0
        if policy.kind is PlanKind.ACTION_SEQUENCE:
            check_cost = 0.08 * sum(
                action.action_id == "Q1" for action in policy.actions
            )
        steps, utility = self._rollout(
            components, _treatment_schedule(policy, horizon), check_cost
        )
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
                "family": "delayed-gaussian-mixture",
                "channels": ["obs_0", "obs_1"],
                "steps": steps,
                "fixed_routine_lag": 2,
            },
            latent_distribution={
                "family": "class-conditioned-augmented-gaussian-mixture",
                "diagnostic_posterior": {
                    key: _json_float(value) for key, value in posterior.items()
                },
                "steps": steps,
            },
            outcome_distribution={
                "utility_family": "internal-state-quadratic-form",
                "expected_utility": _json_float(utility),
            },
            expected_utility=_json_float(utility),
            numerical_diagnostics={
                "method": "gauss-legendre-initial-mixture-linear-gaussian",
                "initial_x_quadrature_order": 16,
                "initial_reservoir_quadrature_order": 16,
            },
        )

    def _fixture_episode(
        self, *, exposed: bool, seed: int, salt: int
    ) -> PrivateEpisode:
        events = [
            _observation_event(
                seed + salt,
                "obs_0",
                0.70,
                collected_at=tick,
                available_at=tick,
                slot=position,
            )
            for position, tick in enumerate(range(-4, 1))
        ]
        if exposed:
            # Recent doses changed x/r, while Q0(0) still reads x_-2.  Two
            # consecutive exposures make the frozen pair's optimal action sets
            # disjoint without changing any displayed Q0 value.
            events.extend(
                (
                    _treatment_event(seed + salt, "A1", -2, slot=98),
                    _treatment_event(seed + salt, "A1", -1, slot=99),
                )
            )
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, salt),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"fixture_realization": salt},
            invariant_parameters={"fixture": "delayed-reservoir"},
            diagnostic_target={"C0": 0.5, "C1": 0.5},
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={"fixture": "paired"},
        )

    def collision_fixture(self, seed: int = 501) -> tuple[PrivateEpisode, PrivateEpisode]:
        return (
            self._fixture_episode(exposed=True, seed=seed, salt=1),
            self._fixture_episode(exposed=False, seed=seed, salt=2),
        )

    def false_split_fixture(self, seed: int = 503) -> tuple[PrivateEpisode, PrivateEpisode]:
        first = self._fixture_episode(exposed=True, seed=seed, salt=7)
        events = tuple(
            replace(event, event_uid=_opaque_uid(seed + 123, "alpha", index))
            for index, event in enumerate(first.public_history.events)
        )
        return first, replace(
            first,
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, 8),
            public_history=_visible_history(events, self.catalog),
        )

    def future_leak_fixture(self, seed: int = 505) -> tuple[PrivateEpisode, PrivateEpisode]:
        first = self._fixture_episode(exposed=False, seed=seed, salt=11)
        second = replace(
            first,
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, 12),
            factual_future=[{"private_response": 999.0}],
            hidden_state_at_cut={"different_private_realization": True},
        )
        return first, second


World = W05World


__all__ = ["W05World", "World"]
