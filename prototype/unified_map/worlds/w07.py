"""W07: treatment has separate physiological and observation-channel paths."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import math
from typing import Any

import numpy as np

from ..canonical import ProtocolViolation
from ..schema import ActionPlan, EventKind
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
from .w06 import (
    _alpha_rename,
    _condition_gaussian,
    _constant_plan,
    _event,
    _mixture_moments,
    _mixed_categorical,
    _no_action,
    _opaque_token,
    _reference_linear_condition,
    _reference_normalized_weights,
    _sequence,
    _softmax,
    _validate_episode_request,
    _visible_history,
    _unique_plans,
)


class World07(MicroWorld):
    """A dose moves latent state and masks the routine readout more strongly."""

    _BETA = (0.18, 0.30)
    _DOSE = {"A1": 1.0, "A2": 2.0}

    def __init__(self) -> None:
        self._catalog = PublicCatalog(
            observations=(ChannelSpec("obs_0"), ChannelSpec("obs_1")),
            actions=(
                ActionSpec("A1", {"dose": "fixed_1"}, cost=0.04),
                ActionSpec("A2", {"dose": "fixed_2"}, cost=0.16),
            ),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.10),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    @property
    def environment_key(self) -> str:
        return "ucm-benchmark-private-w07-v1"

    @property
    def catalog(self) -> PublicCatalog:
        return self._catalog

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        _validate_episode_request(split, generator_seed, episode_index)
        key = ("episode", episode_index, split.value)
        c = categorical((0.5, 0.5), generator_seed, *key, "class")
        x = 1.6 * uniform01(generator_seed, *key, "initial-x")
        r = 0.5 * uniform01(generator_seed, *key, "initial-r")
        events = []
        pending = []
        propensities: list[dict[str, Any]] = []
        performed_sequence: list[tuple[int, str]] = []
        latest_y = x - 0.55 * r + 0.05 * normal01(
            generator_seed, *key, "q0", -4
        )
        events.append(
            _event(
                kind=EventKind.OBSERVATION_AVAILABLE,
                occurred_at=-4,
                collected_at=-4,
                available_at=-4,
                uid=_opaque_token(generator_seed, *key, "q0", -4),
                payload={"channel_id": "obs_0", "check_id": "Q0", "value": latest_y},
            )
        )
        for tick in range(-4, 0):
            logits = (
                0.2,
                1.0 * (latest_y - 0.25),
                1.5 * (latest_y - 0.75),
            )
            action_probabilities = _mixed_categorical(_softmax(logits))
            choice = categorical(
                action_probabilities,
                generator_seed,
                *key,
                "behavior-action",
                tick,
            )
            action_id = (None, "A1", "A2")[choice]
            base_check = 0.10 + 0.40 / (
                1.0 + math.exp(-(abs(latest_y - 0.45) - 0.25))
            )
            p_check = 0.90 * base_check + 0.10 * 0.50
            take_check = bernoulli(
                p_check, generator_seed, *key, "behavior-check", tick
            )
            propensities.append(
                {
                    "tick": tick,
                    "conditioning": "available_public_prefix",
                    "public_inputs": {"latest_obs_0": latest_y},
                    "action": {
                        "NoNewAction": action_probabilities[0],
                        "A1": action_probabilities[1],
                        "A2": action_probabilities[2],
                    },
                    "check": {"Q1": p_check, "NoCheck": 1.0 - p_check},
                    "selected_action": action_id or "NoNewAction",
                    "selected_check": "Q1" if take_check else "NoCheck",
                }
            )
            dose = 0.0 if action_id is None else self._DOSE[action_id]
            if action_id is not None:
                performed_sequence.append((tick, action_id))
                events.append(
                    _event(
                        kind=EventKind.PERFORMED_TREATMENT,
                        occurred_at=tick,
                        available_at=tick,
                        uid=_opaque_token(generator_seed, *key, "action", tick),
                        payload={"action_id": action_id, "dose": dose},
                    )
                )
            if take_check:
                events.extend(
                    (
                        _event(
                            kind=EventKind.TEST_ORDERED,
                            occurred_at=tick,
                            available_at=tick,
                            uid=_opaque_token(generator_seed, *key, "q1-order", tick),
                            payload={"check_id": "Q1"},
                        ),
                        _event(
                            kind=EventKind.TEST_PERFORMED,
                            occurred_at=tick + 1,
                            collected_at=tick + 1,
                            available_at=tick + 1,
                            uid=_opaque_token(generator_seed, *key, "q1-perform", tick),
                            payload={"check_id": "Q1"},
                        ),
                    )
                )
            r = 0.35 * r + dose
            x = (
                0.95 * x
                + 0.12
                - self._BETA[c] * dose
                + 0.045 * normal01(generator_seed, *key, "process", tick + 1)
            )
            latest_y = x - 0.55 * r + 0.05 * normal01(
                generator_seed, *key, "q0", tick + 1
            )
            events.append(
                _event(
                    kind=EventKind.OBSERVATION_AVAILABLE,
                    occurred_at=tick + 1,
                    collected_at=tick + 1,
                    available_at=tick + 1,
                    uid=_opaque_token(generator_seed, *key, "q0", tick + 1),
                    payload={"channel_id": "obs_0", "check_id": "Q0", "value": latest_y},
                )
            )
            if take_check:
                q1 = x + 0.09 * normal01(
                    generator_seed, *key, "q1-value", tick + 1
                )
                pending.append(
                    _event(
                        kind=EventKind.OBSERVATION_AVAILABLE,
                        occurred_at=tick + 1,
                        collected_at=tick + 1,
                        available_at=tick + 2,
                        uid=_opaque_token(generator_seed, *key, "q1-result", tick),
                        payload={"channel_id": "obs_1", "check_id": "Q1", "value": q1},
                    )
                )
        events.extend(pending)
        history = _visible_history(events, self.catalog)
        factual_future: list[dict[str, Any]] = []
        factual_utility = 0.0
        future_x, future_r = x, r
        for step in range(1, 9):
            future_x = 0.95 * future_x + 0.12 + 0.045 * normal01(
                generator_seed, *key, "factual-future", step
            )
            future_r *= 0.35
            factual_future.append(
                {
                    "offset": step,
                    "latent": future_x,
                    "obs_0": future_x - 0.55 * future_r,
                }
            )
            factual_utility -= 0.97 ** (step - 1) * future_x * future_x
        strata = ["iid_support"]
        if split is WorldSplit.SEALED_TEST and (
            x <= -0.15 or x >= 1.35 or r >= 2.5
        ):
            strata.append("boundary_tail")
        if split is WorldSplit.SEALED_TEST and any(
            left_id == "A2" and right_id == "A1" and right_tick == left_tick + 1
            for (left_tick, left_id), (right_tick, right_id) in zip(
                performed_sequence, performed_sequence[1:]
            )
        ):
            strata.append("policy_coverage_holdout")
        return PrivateEpisode(
            case_key=f"w07-private-{split.value}-{episode_index}",
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=history,
            hidden_state_at_cut={"x": x, "r": r},
            invariant_parameters={"c": c, "beta": self._BETA[c]},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=factual_future,
            action_propensities=propensities,
            factual_utility=factual_utility,
            oracle_anchor={
                "posterior_source": "public_history_only",
                "paths": ["state_mediated", "channel_direct"],
                "split_strata": strata,
            },
        )

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        if episode.environment_key != self.environment_key:
            raise ProtocolViolation("episode belongs to a different world")
        recorded = episode.oracle_anchor.get("split_strata")
        if not isinstance(recorded, list) or any(type(item) is not str for item in recorded):
            raise ProtocolViolation("W07 episode lacks exact split strata")
        strata = ["iid_support"]
        x = float(episode.hidden_state_at_cut["x"])
        r = float(episode.hidden_state_at_cut["r"])
        if episode.split is WorldSplit.SEALED_TEST and (
            x <= -0.15 or x >= 1.35 or r >= 2.5
        ):
            strata.append("boundary_tail")
        performed = sorted(
            (
                event.occurred_at,
                str(event.payload["action_id"]),
            )
            for event in episode.public_history.events
            if event.kind is EventKind.PERFORMED_TREATMENT
            and event.payload.get("action_id") in {"A1", "A2"}
        )
        if episode.split is WorldSplit.SEALED_TEST and any(
            left_id == "A2" and right_id == "A1" and right_tick == left_tick + 1
            for (left_tick, left_id), (right_tick, right_id) in zip(
                performed, performed[1:]
            )
        ):
            strata.append("policy_coverage_holdout")
        strata = tuple(strata)
        allowed = {"iid_support", "boundary_tail", "policy_coverage_holdout"}
        if not strata or strata[0] != "iid_support" or set(strata) - allowed:
            raise ProtocolViolation("W07 split strata contradict the registry")
        if tuple(recorded) != strata:
            raise ProtocolViolation("W07 stored split stratum is stale")
        return strata

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ProtocolViolation("unsupported W07 horizon")
        return _unique_plans((
            _no_action(),
            _sequence((0, "A1", None)),
            _sequence((0, "A2", None)),
            _constant_plan("A1", horizon),
            _constant_plan("A2", horizon),
            _sequence((0, "Q1", {"rule": "posterior_threshold_dose"})),
        ))

    def _posterior(self, episode: PrivateEpisode) -> list[dict[str, Any]]:
        if episode.public_history.catalog_digest != self.catalog.digest:
            raise ProtocolViolation("public history uses a different catalog")
        times = list(range(-4, 1))
        time_index = {tick: position for position, tick in enumerate(times)}
        actions: dict[int, float] = {}
        for event in episode.public_history.events:
            if event.kind is EventKind.PERFORMED_TREATMENT:
                action = event.payload.get("action_id")
                if action in self._DOSE:
                    actions[event.occurred_at] = self._DOSE[str(action)]
        observations = [
            event
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") in {"obs_0", "obs_1"}
            and event.collected_at in time_index
        ]
        y = np.asarray([float(event.payload["value"]) for event in observations])
        components: list[dict[str, Any]] = []
        log_weights: list[float] = []
        for c, beta in enumerate(self._BETA):
            # Latent vector is [x_-4..x_0, r_-4].
            mean = np.zeros(6)
            covariance = np.zeros((6, 6))
            mean[0] = 0.8
            covariance[0, 0] = 1.6**2 / 12.0
            mean[5] = 0.25
            covariance[5, 5] = 0.5**2 / 12.0
            for position, tick in enumerate(range(-4, 0), start=1):
                dose = actions.get(tick, 0.0)
                mean[position] = 0.95 * mean[position - 1] + 0.12 - beta * dose
                covariance[position, :position] = 0.95 * covariance[position - 1, :position]
                covariance[:position, position] = covariance[position, :position]
                covariance[position, position] = (
                    0.95**2 * covariance[position - 1, position - 1] + 0.045**2
                )
            r_coefficients = {-4: 1.0}
            r_offsets = {-4: 0.0}
            for tick in range(-4, 0):
                r_coefficients[tick + 1] = 0.35 * r_coefficients[tick]
                r_offsets[tick + 1] = 0.35 * r_offsets[tick] + actions.get(tick, 0.0)
            design = np.zeros((len(observations), 6))
            adjusted = y.copy()
            noise = np.zeros((len(observations), len(observations)))
            for row, event in enumerate(observations):
                tick = int(event.collected_at)
                design[row, time_index[tick]] = 1.0
                if event.payload["channel_id"] == "obs_0":
                    design[row, 5] = -0.55 * r_coefficients[tick]
                    adjusted[row] += 0.55 * r_offsets[tick]
                    noise[row, row] = 0.05**2
                else:
                    noise[row, row] = 0.09**2
            post_mean, post_cov, log_likelihood = _condition_gaussian(
                mean, covariance, design, adjusted, noise
            )
            transform = np.zeros((2, 6))
            transform[0, 4] = 1.0
            transform[1, 5] = r_coefficients[0]
            transformed_mean = transform @ post_mean
            transformed_mean[1] += r_offsets[0]
            transformed_cov = transform @ post_cov @ transform.T
            components.append(
                {
                    "class": c,
                    "mean": transformed_mean,
                    "covariance": transformed_cov,
                    "weight": 0.0,
                }
            )
            log_weights.append(math.log(0.5) + log_likelihood)
        peak = max(log_weights)
        raw = [math.exp(value - peak) for value in log_weights]
        total = math.fsum(raw)
        for component, value in zip(components, raw):
            component["weight"] = value / total
        return components

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the W07 frozen policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        components = self._posterior(episode)
        action_by_offset = {
            action.offset: action.action_id
            for action in policy.actions
            if action.action_id in self._DOSE
        }
        checks = {
            action.offset
            for action in policy.actions
            if action.action_id == "Q1"
        }
        per_component = []
        expected_utility = 0.0
        for component in components:
            c = int(component["class"])
            mean = np.asarray(component["mean"], dtype=float)
            covariance = np.asarray(component["covariance"], dtype=float)
            latent = []
            routine = []
            independent = []
            utility = 0.0
            for step in range(1, horizon + 1):
                action_id = action_by_offset.get(step - 1)
                dose = self._DOSE.get(action_id, 0.0)
                transition = np.diag([0.95, 0.35])
                mean = transition @ mean + np.asarray(
                    [0.12 - self._BETA[c] * dose, dose]
                )
                covariance = transition @ covariance @ transition.T
                covariance[0, 0] += 0.045**2
                x_mean, r_mean = float(mean[0]), float(mean[1])
                x_var = float(max(covariance[0, 0], 0.0))
                obs_mean = x_mean - 0.55 * r_mean
                obs_var = float(
                    max(
                        covariance[0, 0]
                        + 0.55**2 * covariance[1, 1]
                        - 1.10 * covariance[0, 1]
                        + 0.05**2,
                        0.0,
                    )
                )
                latent.append((x_mean, x_var))
                routine.append((obs_mean, obs_var))
                independent.append((x_mean, x_var + 0.09**2))
                utility -= 0.97 ** (step - 1) * (
                    x_var
                    + x_mean * x_mean
                    + 0.04 * dose * dose
                    + 0.10 * float(step - 1 in checks)
                )
            expected_utility += float(component["weight"]) * utility
            per_component.append(
                {
                    "weight": float(component["weight"]),
                    "latent": latent,
                    "routine": routine,
                    "independent": independent,
                }
            )
        weights = [item["weight"] for item in per_component]

        def rows(key: str) -> list[dict[str, float]]:
            answer = []
            for position in range(horizon):
                mean, variance = _mixture_moments(
                    weights,
                    [float(item[key][position][0]) for item in per_component],
                    [float(item[key][position][1]) for item in per_component],
                )
                answer.append({"offset": position + 1, "mean": mean, "variance": variance})
            return answer

        diagnosis = {
            f"C{int(component['class'])}": float(component["weight"])
            for component in components
        }
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={"obs_0": rows("routine"), "obs_1": rows("independent")},
            latent_distribution={"x": rows("latent")},
            outcome_distribution={
                "expected_utility": expected_utility,
                "diagnostic_posterior": diagnosis,
                "path_decomposition": {
                    "state_per_unit_dose": -sum(
                        float(component["weight"]) * self._BETA[int(component["class"])]
                        for component in components
                    ),
                    "channel_per_unit_dose": -0.55,
                },
            },
            expected_utility=expected_utility,
            numerical_diagnostics={
                "method": "analytic_class_mixture_batch_gaussian",
                "posterior_source": "candidate_visible_history",
                "oracle_seed_used": False,
            },
        )

    def reference_counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        *,
        oracle_seed: int = 0,
    ) -> float:
        """Independent public-prefix information-form reference utility."""

        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the W07 frozen policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        del oracle_seed
        times = tuple(range(-4, 1))
        time_index = {tick: offset for offset, tick in enumerate(times)}
        factual_actions: dict[int, float] = {}
        for event in episode.public_history.events:
            if event.kind is EventKind.PERFORMED_TREATMENT:
                identifier = event.payload.get("action_id")
                if identifier in self._DOSE:
                    factual_actions[event.occurred_at] = self._DOSE[str(identifier)]
        observations = [
            event
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") in {"obs_0", "obs_1"}
            and event.collected_at in time_index
        ]
        observed = np.asarray(
            [float(event.payload["value"]) for event in observations], dtype=float
        )
        components: list[tuple[int, np.ndarray, np.ndarray]] = []
        log_weights: list[float] = []
        for class_index, beta in enumerate(self._BETA):
            prior_mean = np.zeros(6, dtype=float)
            prior_covariance = np.zeros((6, 6), dtype=float)
            prior_mean[0] = 0.8
            prior_covariance[0, 0] = 1.6**2 / 12.0
            prior_mean[5] = 0.25
            prior_covariance[5, 5] = 0.5**2 / 12.0
            for offset, tick in enumerate(range(-4, 0), start=1):
                dose = factual_actions.get(tick, 0.0)
                prior_mean[offset] = 0.95 * prior_mean[offset - 1] + 0.12 - beta * dose
                prior_covariance[offset, :offset] = (
                    0.95 * prior_covariance[offset - 1, :offset]
                )
                prior_covariance[:offset, offset] = prior_covariance[offset, :offset]
                prior_covariance[offset, offset] = (
                    0.95**2 * prior_covariance[offset - 1, offset - 1]
                    + 0.045**2
                )
            r_coefficient = {-4: 1.0}
            r_offset = {-4: 0.0}
            for tick in range(-4, 0):
                r_coefficient[tick + 1] = 0.35 * r_coefficient[tick]
                r_offset[tick + 1] = (
                    0.35 * r_offset[tick] + factual_actions.get(tick, 0.0)
                )
            design = np.zeros((len(observations), 6), dtype=float)
            adjusted = observed.copy()
            noise = np.zeros((len(observations), len(observations)), dtype=float)
            for row, event in enumerate(observations):
                tick = int(event.collected_at)
                design[row, time_index[tick]] = 1.0
                if event.payload["channel_id"] == "obs_0":
                    design[row, 5] = -0.55 * r_coefficient[tick]
                    adjusted[row] += 0.55 * r_offset[tick]
                    noise[row, row] = 0.05**2
                else:
                    noise[row, row] = 0.09**2
            posterior_mean, posterior_covariance, likelihood = (
                _reference_linear_condition(
                    prior_mean, prior_covariance, design, adjusted, noise
                )
            )
            selector = np.zeros((2, 6), dtype=float)
            selector[0, 4] = 1.0
            selector[1, 5] = r_coefficient[0]
            cut_mean = selector @ posterior_mean
            cut_mean[1] += r_offset[0]
            cut_covariance = selector @ posterior_covariance @ selector.T
            components.append((class_index, cut_mean, cut_covariance))
            log_weights.append(math.log(0.5) + likelihood)
        weights = _reference_normalized_weights(log_weights)
        future_actions = {
            item.offset: item.action_id
            for item in policy.actions
            if item.action_id in self._DOSE
        }
        checks = {
            item.offset for item in policy.actions if item.action_id == "Q1"
        }
        total_utility = 0.0
        for (class_index, mean, covariance), weight in zip(components, weights):
            component_utility = 0.0
            for step in range(1, horizon + 1):
                offset = step - 1
                dose = self._DOSE.get(future_actions.get(offset), 0.0)
                mean = np.asarray(
                    [
                        0.95 * float(mean[0]) + 0.12 - self._BETA[class_index] * dose,
                        0.35 * float(mean[1]) + dose,
                    ],
                    dtype=float,
                )
                transition = np.diag([0.95, 0.35])
                covariance = transition @ covariance @ transition.T
                covariance[0, 0] += 0.045**2
                component_utility -= 0.97**offset * (
                    float(covariance[0, 0])
                    + float(mean[0]) ** 2
                    + 0.04 * dose * dose
                    + 0.10 * float(offset in checks)
                )
            total_utility += weight * component_utility
        return float(total_utility)

    def probe_fixtures(
        self, generator_seed: int = 707
    ) -> dict[str, tuple[PrivateEpisode, PrivateEpisode]]:
        base = self.generate_episode(WorldSplit.SEALED_TEST, generator_seed, 0)
        renamed = replace(
            base,
            case_key="w07-private-alpha-renamed",
            public_history=_alpha_rename(base.public_history, "w07-alpha"),
        )
        future_swap = replace(
            base,
            case_key="w07-private-future-swap",
            factual_future=list(reversed(base.factual_future)),
        )

        def same_readout(side: str, treated: bool) -> PrivateEpisode:
            events = []
            for tick in range(-4, 1):
                if treated and tick == -1:
                    events.append(
                        _event(
                            kind=EventKind.PERFORMED_TREATMENT,
                            occurred_at=-1,
                            available_at=-1,
                            uid=hashlib.sha256(f"{side}:a".encode()).hexdigest()[:32],
                            payload={"action_id": "A1", "dose": 1.0},
                        )
                    )
                value = 0.60 if tick == 0 else (1.15 if treated else 0.60)
                events.append(
                    _event(
                        kind=EventKind.OBSERVATION_AVAILABLE,
                        occurred_at=tick,
                        collected_at=tick,
                        available_at=tick,
                        uid=hashlib.sha256(f"{side}:q:{tick}".encode()).hexdigest()[:32],
                        payload={"channel_id": "obs_0", "check_id": "Q0", "value": value},
                    )
                )
            return replace(
                base,
                case_key=f"w07-private-same-readout-{side}",
                public_history=_visible_history(events, self.catalog),
                hidden_state_at_cut={"x": 1.15 if treated else 0.60, "r": 1.0 if treated else 0.0},
            )

        return {
            "same_readout_collision": (
                same_readout("untreated", False),
                same_readout("treated", True),
            ),
            "identical_prefix_future_swap": (base, future_swap),
            "false_split_alpha_rename": (base, renamed),
        }


__all__ = ["World07"]
