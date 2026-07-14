"""W12: one mechanism expressed differently by two host response classes."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

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
    _mixed_categorical,
    _softmax,
    _validate_episode_request,
    _visible_history,
)
from .w11 import (
    _case_key,
    _channel_rows,
    _finite_policy_set,
    _normal_log_likelihood,
    _normalise_log_particles,
    _observation,
    _plan_ids,
    _treatment,
)


class World12(MicroWorld):
    """Host expression changes observations and A1 efficacy, not mechanism ID."""

    _HOST = (0.60, 1.40)
    _A1_EFFECT = (0.22, 0.42)

    def __init__(self) -> None:
        self._catalog = PublicCatalog(
            observations=(
                ChannelSpec("obs_0"),
                ChannelSpec("obs_1"),
                ChannelSpec("obs_2"),
            ),
            actions=(ActionSpec("A1", cost=0.06), ActionSpec("A2", cost=0.06)),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.06),
                CheckSpec("Q2", ("obs_2",), (1, 1), cost=0.09),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    @property
    def environment_key(self) -> str:
        return "ucm-benchmark-private-w12-v1"

    @property
    def catalog(self) -> PublicCatalog:
        return self._catalog

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ProtocolViolation("unsupported horizon")
        return _finite_policy_set(
            horizon, treatments=("A1", "A2"), checks=("Q1", "Q2")
        )

    @classmethod
    def _step(
        cls, x: float, host_class: int, action: str | None, noise: float = 0.0
    ) -> float:
        effect = cls._A1_EFFECT[host_class] if action == "A1" else 0.18 if action == "A2" else 0.0
        return max(0.0, 0.91 * x + 0.10 - effect + noise)

    @staticmethod
    def _behavior(y: float) -> tuple[float, float, float]:
        return _mixed_categorical(_softmax((0.3, 0.9 * y, 0.6 * y)))

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        _validate_episode_request(split, generator_seed, episode_index)
        key: tuple[str | int, ...] = ("w12", split.value, episode_index)
        host_class = (episode_index + int(split is WorldSplit.VALIDATION)) % 2
        host = self._HOST[host_class]
        residue = episode_index % 10
        if split is WorldSplit.SEALED_TEST and residue < 3:
            # Same-expression stratum: both host classes are mapped around 0.60.
            x = 0.60 / host + 0.04 * (
                2.0 * uniform01(generator_seed, *key, "same-expression") - 1.0
            )
            stratum = "same-expression"
        else:
            x = 0.15 + 1.05 * uniform01(generator_seed, *key, "initial-x")
            stratum = (
                "same-mechanism-different-expression"
                if split is WorldSplit.SEALED_TEST and residue < 5
                else "marker-missing"
                if split is WorldSplit.SEALED_TEST and residue < 7
                else "iid"
                if split is WorldSplit.SEALED_TEST
                else "validation-same-expression-holdout"
                if split is WorldSplit.VALIDATION
                else "train-host-x-balanced"
            )
        events: list[Any] = []
        propensities: list[dict[str, Any]] = []
        marker_seen = False

        for tick in range(-3, 1):
            y = host * x + 0.05 * normal01(generator_seed, *key, "q0", tick)
            events.append(_observation(generator_seed, key, "obs_0", y, tick))
            if tick == 0:
                break
            p_q1 = 0.08 if marker_seen else 0.30
            if stratum == "marker-missing":
                p_q1 = 0.0
            p_q2 = 0.12 + 0.20 / (
                1.0 + math.exp(-(abs(y) - 0.5))
            )
            take_q1 = bernoulli(p_q1, generator_seed, *key, "take-q1", tick)
            take_q2 = bernoulli(p_q2, generator_seed, *key, "take-q2", tick)
            if take_q1:
                marker_seen = True
                events.append(
                    _observation(
                        generator_seed,
                        key,
                        "obs_1",
                        host + 0.06 * normal01(generator_seed, *key, "q1", tick),
                        tick,
                        delay=1,
                    )
                )
            if take_q2:
                events.append(
                    _observation(
                        generator_seed,
                        key,
                        "obs_2",
                        x + 0.10 * normal01(generator_seed, *key, "q2", tick),
                        tick,
                        delay=1,
                    )
                )
            probabilities = self._behavior(y)
            choice = categorical(
                probabilities, generator_seed, *key, "behavior", tick
            )
            action = (None, "A1", "A2")[choice]
            propensities.append(
                {
                    "decision_at": tick,
                    "probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                        "A2": probabilities[2],
                    },
                    "selected": "NoNewAction" if action is None else action,
                    "check_probabilities": {
                        "Q1": p_q1,
                        "Q2": p_q2,
                    },
                }
            )
            if action is not None:
                events.append(_treatment(generator_seed, key, action, tick))
            x = self._step(
                x,
                host_class,
                action,
                0.04 * normal01(generator_seed, *key, "process", tick),
            )

        state_at_cut = x
        future: list[dict[str, Any]] = []
        utility = 0.0
        for offset in range(4):
            probabilities = self._behavior(host * x)
            choice = categorical(
                probabilities,
                generator_seed,
                *key,
                "factual-action",
                offset,
            )
            action = (None, "A1", "A2")[choice]
            x = self._step(
                x,
                host_class,
                action,
                0.04 * normal01(generator_seed, *key, "factual-process", offset),
            )
            cost = x * x + 0.20 * (host * x) ** 2 + 0.06 * float(action is not None)
            utility -= 0.97**offset * cost
            future.append(
                {
                    "offset": offset + 1,
                    "observations": {"obs_0": host * x},
                    "performed_action": "NoNewAction" if action is None else action,
                }
            )

        return PrivateEpisode(
            case_key=_case_key(
                self.environment_key, split, generator_seed, episode_index
            ),
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"mechanism_activity": float(state_at_cut)},
            invariant_parameters={
                "host_modifier": host,
                "host_class": host_class,
            },
            diagnostic_target={
                "C0": float(host_class == 0),
                "C1": float(host_class == 1),
            },
            factual_future=future,
            action_propensities=propensities,
            factual_utility=float(utility),
            oracle_anchor={
                "stratum": stratum,
                "oracle_family": "host-enumeration",
                "probe_attribution": (
                    "posterior-ambiguity-expected"
                    if stratum == "marker-missing"
                    else "candidate-attributable"
                ),
            },
        )

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the finite W12 policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        del oracle_seed
        particles = self._public_posterior(episode)
        variance = 0.0
        utility = 0.0
        latent_steps: list[dict[str, Any]] = []
        observed_steps: list[dict[str, Any]] = []
        working = [(host_class, x, weight) for host_class, x, weight in particles]
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = "A1" if "A1" in ids else "A2" if "A2" in ids else None
            working = [
                (host_class, self._step(x, host_class, action), weight)
                for host_class, x, weight in working
            ]
            variance = 0.91**2 * variance + 0.04**2
            check_cost = 0.06 * float("Q1" in ids) + 0.09 * float("Q2" in ids)
            expected_cost = math.fsum(
                weight
                * (
                    x * x
                    + variance
                    + 0.20 * self._HOST[host_class] ** 2 * (x * x + variance)
                )
                for host_class, x, weight in working
            )
            expected_cost += 0.06 * float(action is not None) + check_cost
            utility -= 0.97**offset * expected_cost
            mean_x = math.fsum(weight * x for _, x, weight in working)
            var_x = math.fsum(
                weight * (x - mean_x) ** 2 for _, x, weight in working
            ) + variance
            mean_y = math.fsum(
                weight * self._HOST[host_class] * x
                for host_class, x, weight in working
            )
            var_y = math.fsum(
                weight * (self._HOST[host_class] * x - mean_y) ** 2
                for host_class, x, weight in working
            ) + math.fsum(
                weight * self._HOST[host_class] ** 2 * variance
                for host_class, _, weight in working
            )
            mean_host = math.fsum(
                weight * self._HOST[host_class]
                for host_class, _, weight in working
            )
            latent_steps.append(
                {"offset": offset + 1, "mean": mean_x, "variance": var_x}
            )
            observed_steps.append(
                {
                    "offset": offset + 1,
                    "obs_0_mean": mean_y,
                    "obs_0_variance": var_y + 0.05**2,
                    "obs_1_mean": mean_host,
                    "obs_2_mean": mean_x,
                }
            )
        p_c0 = math.fsum(
            weight for host_class, _, weight in particles if host_class == 0
        )
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "host-modified-gaussian-moments",
                "steps": observed_steps,
            },
            latent_distribution={
                "family": "shared-mechanism-state",
                "steps": latent_steps,
                "diagnostic_posterior": {
                    "C0": p_c0,
                    "C1": 1.0 - p_c0,
                },
            },
            outcome_distribution={
                "utility_family": "mechanism-plus-expression-cost",
                "expected_utility": float(utility),
            },
            expected_utility=float(utility),
            numerical_diagnostics={
                "method": "public-history-host-x-grid",
                "absolute_error_bound": 0.03,
                "posterior_fork": "single-public-posterior",
                "private_state_used": False,
            },
        )

    @classmethod
    def _public_posterior(
        cls, episode: PrivateEpisode
    ) -> tuple[tuple[int, float, float], ...]:
        routine = _channel_rows(episode, "obs_0")
        if not routine:
            raise ProtocolViolation("W12 requires public obs_0")
        y = routine[-1][1]
        markers = _channel_rows(episode, "obs_1")
        mechanisms = _channel_rows(episode, "obs_2")
        marker = markers[-1][1] if markers else None
        mechanism = mechanisms[-1][1] if mechanisms else None
        upper = max(1.6, abs(y) / 0.60 + 0.5)
        rows: list[tuple[tuple[Any, ...], float]] = []
        for host_class, host in enumerate(cls._HOST):
            for i in range(81):
                x = upper * i / 80.0
                score = _normal_log_likelihood(y, host * x, 0.08)
                if marker is not None:
                    score += _normal_log_likelihood(marker, host, 0.10)
                if mechanism is not None:
                    score += _normal_log_likelihood(mechanism, x, 0.14)
                rows.append(((host_class, x), score))
        return _normalise_log_particles(rows)  # type: ignore[return-value]

    def reference_counterfactual(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> float:
        """Independent midpoint quadrature with inline host transitions."""

        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the finite W12 policy set")
        routine = _channel_rows(episode, "obs_0")
        if not routine:
            raise ProtocolViolation("W12 reference requires obs_0")
        y = routine[-1][1]
        markers = _channel_rows(episode, "obs_1")
        mechanisms = _channel_rows(episode, "obs_2")
        marker = markers[-1][1] if markers else None
        mechanism = mechanisms[-1][1] if mechanisms else None
        upper = max(1.6, abs(y) / 0.60 + 0.5)
        raw: list[tuple[int, float, float]] = []
        for host_class, host in enumerate((0.60, 1.40)):
            for i in range(120):
                x = upper * (i + 0.5) / 120.0
                score = _normal_log_likelihood(y, host * x, 0.08)
                if marker is not None:
                    score += _normal_log_likelihood(marker, host, 0.10)
                if mechanism is not None:
                    score += _normal_log_likelihood(mechanism, x, 0.14)
                raw.append((host_class, x, score))
        peak = max(row[2] for row in raw)
        weighted = [(h, x, math.exp(max(-745.0, s - peak))) for h, x, s in raw]
        norm = math.fsum(row[2] for row in weighted)
        particles = [(h, x, w / norm) for h, x, w in weighted]
        variance = 0.0
        utility = 0.0
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = "A1" if "A1" in ids else "A2" if "A2" in ids else None
            next_particles = []
            for host_class, x, weight in particles:
                effect = (0.22, 0.42)[host_class] if action == "A1" else 0.18 if action == "A2" else 0.0
                next_x = max(0.0, 0.91 * x + 0.10 - effect)
                next_particles.append((host_class, next_x, weight))
            particles = next_particles
            variance = 0.91**2 * variance + 0.04**2
            expected = math.fsum(
                weight * (
                    x * x + variance
                    + 0.20 * (0.60, 1.40)[host_class] ** 2 * (x * x + variance)
                )
                for host_class, x, weight in particles
            )
            expected += 0.06 * float(action is not None)
            expected += 0.06 * float("Q1" in ids) + 0.09 * float("Q2" in ids)
            utility -= 0.97**offset * expected
        return float(utility)

    def private_state_upper_bound(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> float:
        """Judge-only realized-state comparator, excluded from scoring."""

        host_class = int(episode.invariant_parameters["host_class"])
        host = self._HOST[host_class]
        x = float(episode.hidden_state_at_cut["mechanism_activity"])
        utility = 0.0
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = "A1" if "A1" in ids else "A2" if "A2" in ids else None
            x = self._step(x, host_class, action)
            utility -= 0.97**offset * (
                x * x + 0.20 * (host * x) ** 2
                + 0.06 * float(action is not None)
                + 0.06 * float("Q1" in ids) + 0.09 * float("Q2" in ids)
            )
        return float(utility)

    def _fixture(
        self,
        *,
        seed: int,
        salt: int,
        host_class: int,
        x: float,
        include_marker: bool = True,
    ) -> PrivateEpisode:
        host = self._HOST[host_class]
        key: tuple[str | int, ...] = ("w12-fixture", salt)
        events: list[Any] = [
            _observation(seed, key, "obs_0", host * x, 0, slot=0)
        ]
        if include_marker:
            events.extend(
                [
                    _observation(seed, key, "obs_1", host, 0, slot=1),
                    _observation(seed, key, "obs_2", x, 0, slot=2),
                ]
            )
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, salt),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"mechanism_activity": x},
            invariant_parameters={"host_modifier": host, "host_class": host_class},
            diagnostic_target={
                "C0": float(host_class == 0),
                "C1": float(host_class == 1),
            },
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={
                "fixture": "paired",
                "probe_attribution": "candidate-attributable",
            },
        )

    def distinguishable_fixture(
        self, seed: int = 1211
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Equal routine mean; host/direct checks reveal distinct sufficient states."""

        return (
            self._fixture(seed=seed, salt=1, host_class=0, x=1.0),
            self._fixture(seed=seed, salt=2, host_class=1, x=3.0 / 7.0),
        )

    def same_mechanism_fixture(
        self, seed: int = 1212
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Same mechanism state but expression futures differ by host."""

        return (
            self._fixture(seed=seed, salt=3, host_class=0, x=0.72),
            self._fixture(seed=seed, salt=4, host_class=1, x=0.72),
        )

    def equivalent_fixture(
        self, seed: int = 1213
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        first = self._fixture(seed=seed, salt=5, host_class=1, x=0.64)
        return first, replace(
            first,
            public_history=_alpha_rename(first.public_history, "w12-equivalent"),
        )

    collision_fixture = distinguishable_fixture
    false_split_fixture = equivalent_fixture


W12World = World12
World = World12

__all__ = ["W12World", "World", "World12"]
