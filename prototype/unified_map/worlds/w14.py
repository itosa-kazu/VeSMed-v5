"""W14: path dependence represented by an exact finite lag state."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from ..canonical import ProtocolViolation
from ..schema import ActionPlan
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
    _finite_policy_set,
    _observation,
    _plan_ids,
    _treatment,
)


class World14(MicroWorld):
    """Current activity is insufficient without exponentially weighted memory."""

    def __init__(self) -> None:
        self._catalog = PublicCatalog(
            observations=(ChannelSpec("obs_0"), ChannelSpec("obs_1")),
            actions=(ActionSpec("A1", cost=0.06), ActionSpec("A2", cost=0.06)),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.08),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    @property
    def environment_key(self) -> str:
        return "ucm-benchmark-private-w14-v1"

    @property
    def catalog(self) -> PublicCatalog:
        return self._catalog

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ProtocolViolation("unsupported horizon")
        return _finite_policy_set(
            horizon, treatments=("A1", "A2"), checks=("Q1",)
        )

    @staticmethod
    def _step(
        x: float,
        memory: float,
        action: str | None,
        noise: float = 0.0,
    ) -> tuple[float, float]:
        next_x = max(
            0.0,
            0.90 * x
            + 0.08
            - 0.32 * float(action == "A1")
            + 0.10 * math.tanh(memory - 1.0)
            + noise,
        )
        next_memory = max(
            0.0,
            0.75 * memory + next_x - 0.45 * float(action == "A2"),
        )
        return next_x, next_memory

    @staticmethod
    def _behavior(y: float, public_ewma: float) -> tuple[float, float, float]:
        return _mixed_categorical(
            _softmax((0.3, 0.8 * y, 0.7 * public_ewma))
        )

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        _validate_episode_request(split, generator_seed, episode_index)
        key: tuple[str | int, ...] = ("w14", split.value, episode_index)
        x = 0.10 + 0.75 * uniform01(generator_seed, *key, "initial-x")
        memory = 0.20 + 1.80 * uniform01(generator_seed, *key, "initial-memory")
        public_ewma = x
        events: list[Any] = []
        propensities: list[dict[str, Any]] = []

        for tick in range(-5, 1):
            y = x + 0.05 * normal01(generator_seed, *key, "q0", tick)
            public_ewma = 0.75 * public_ewma + y
            events.append(_observation(generator_seed, key, "obs_0", y, tick))
            if tick == 0:
                break
            p_q1 = 0.12 + 0.30 / (1.0 + math.exp(-(public_ewma - 0.8)))
            take_q1 = bernoulli(p_q1, generator_seed, *key, "q1-take", tick)
            if take_q1:
                events.append(
                    _observation(
                        generator_seed,
                        key,
                        "obs_1",
                        memory + 0.10 * normal01(generator_seed, *key, "q1", tick),
                        tick,
                        delay=1,
                    )
                )
            probabilities = self._behavior(y, public_ewma)
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
                    "check_probabilities": {"Q1": p_q1, "NoCheck": 1.0 - p_q1},
                }
            )
            if action is not None:
                events.append(_treatment(generator_seed, key, action, tick))
            x, memory = self._step(
                x,
                memory,
                action,
                0.04 * normal01(generator_seed, *key, "process", tick),
            )

        state_at_cut = (x, memory)
        memory_class = int(memory >= 0.9)
        future: list[dict[str, Any]] = []
        utility = 0.0
        for offset in range(4):
            probabilities = self._behavior(x, public_ewma)
            choice = categorical(
                probabilities, generator_seed, *key, "future-action", offset
            )
            action = (None, "A1", "A2")[choice]
            x, memory = self._step(
                x,
                memory,
                action,
                0.04 * normal01(generator_seed, *key, "future-process", offset),
            )
            utility -= 0.97**offset * (
                x * x + 0.45 * memory * memory + 0.06 * float(action is not None)
            )
            future.append(
                {
                    "offset": offset + 1,
                    "observations": {"obs_0": x},
                    "performed_action": "NoNewAction" if action is None else action,
                }
            )

        if split is WorldSplit.SEALED_TEST:
            residue = episode_index % 10
            stratum = (
                "same-current-different-memory"
                if residue < 3
                else "same-sufficient-state-different-history"
                if residue < 5
                else "long-gap"
                if residue < 7
                else "routine"
            )
        elif split is WorldSplit.VALIDATION:
            stratum = "intermittent-pulse"
        else:
            stratum = "short-pulse"

        return PrivateEpisode(
            case_key=_case_key(
                self.environment_key, split, generator_seed, episode_index
            ),
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={
                "current_activity": state_at_cut[0],
                "path_memory": state_at_cut[1],
            },
            invariant_parameters={"memory_class": memory_class},
            diagnostic_target={
                "C0": float(memory_class == 0),
                "C1": float(memory_class == 1),
            },
            factual_future=future,
            action_propensities=propensities,
            factual_utility=float(utility),
            oracle_anchor={"stratum": stratum, "markov_state": ["x", "r"]},
        )

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the finite W14 policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        del oracle_seed
        x = float(episode.hidden_state_at_cut["current_activity"])
        memory = float(episode.hidden_state_at_cut["path_memory"])
        utility = 0.0
        variance = 0.0
        steps: list[dict[str, Any]] = []
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = "A1" if "A1" in ids else "A2" if "A2" in ids else None
            x, memory = self._step(x, memory, action)
            variance = 0.90**2 * variance + 0.04**2
            check_cost = 0.08 * float("Q1" in ids)
            utility -= 0.97**offset * (
                x * x
                + variance
                + 0.45 * memory * memory
                + 0.06 * float(action is not None)
                + check_cost
            )
            steps.append(
                {
                    "offset": offset + 1,
                    "activity_mean": x,
                    "memory_mean": memory,
                    "activity_variance": variance,
                }
            )
        memory_class = int(episode.invariant_parameters["memory_class"])
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "lag-state-gaussian-moments",
                "steps": [
                    {
                        "offset": row["offset"],
                        "obs_0_mean": row["activity_mean"],
                        "obs_0_variance": row["activity_variance"] + 0.05**2,
                        "obs_1_mean": row["memory_mean"],
                    }
                    for row in steps
                ],
            },
            latent_distribution={
                "family": "finite-path-memory-state",
                "steps": steps,
                "diagnostic_posterior": {
                    "C0": float(memory_class == 0),
                    "C1": float(memory_class == 1),
                },
            },
            outcome_distribution={
                "utility_family": "activity-memory-burden",
                "expected_utility": float(utility),
            },
            expected_utility=float(utility),
            numerical_diagnostics={
                "method": "augmented-state-moment-rollout",
                "absolute_error_bound": 0.01,
                "markov_closure": ["activity", "path_memory"],
                "posterior_fork": "single-cut-state",
            },
        )

    def _fixture(
        self,
        *,
        seed: int,
        salt: int,
        history_values: tuple[float, ...],
        x: float,
        memory: float,
    ) -> PrivateEpisode:
        key: tuple[str | int, ...] = ("w14-fixture", salt)
        events = [
            _observation(seed, key, "obs_0", value, tick, slot=position)
            for position, (tick, value) in enumerate(
                zip(range(-len(history_values) + 1, 1), history_values)
            )
        ]
        memory_class = int(memory >= 0.9)
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, salt),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"current_activity": x, "path_memory": memory},
            invariant_parameters={"memory_class": memory_class},
            diagnostic_target={
                "C0": float(memory_class == 0),
                "C1": float(memory_class == 1),
            },
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={"fixture": "paired"},
        )

    def distinguishable_fixture(
        self, seed: int = 1411
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Equal current activity; ordered public trajectories imply different lag."""

        return (
            self._fixture(
                seed=seed,
                salt=1,
                history_values=(0.08, 0.12, 0.16, 0.20),
                x=0.20,
                memory=0.30,
            ),
            self._fixture(
                seed=seed,
                salt=2,
                history_values=(1.25, 1.05, 0.62, 0.20),
                x=0.20,
                memory=3.00,
            ),
        )

    def equivalent_fixture(
        self, seed: int = 1413
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Different remote paths converge to the exact same sufficient state."""

        first = self._fixture(
            seed=seed,
            salt=3,
            history_values=(0.20, 0.55, 0.42),
            x=0.42,
            memory=1.10,
        )
        second = self._fixture(
            seed=seed,
            salt=4,
            history_values=(0.95, 0.18, 0.42),
            x=0.42,
            memory=1.10,
        )
        return first, second

    def alpha_equivalent_fixture(
        self, seed: int = 1414
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        first = self._fixture(
            seed=seed,
            salt=5,
            history_values=(0.18, 0.33),
            x=0.33,
            memory=0.82,
        )
        return first, replace(
            first,
            public_history=_alpha_rename(first.public_history, "w14-alpha"),
        )

    collision_fixture = distinguishable_fixture
    false_split_fixture = equivalent_fixture


W14World = World14
World = World14

__all__ = ["W14World", "World", "World14"]
