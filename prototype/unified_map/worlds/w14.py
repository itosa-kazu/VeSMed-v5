"""W14: path dependence represented by an exact finite lag state."""

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
        x = 0.10 + 0.75 * uniform01(generator_seed, *key, "initial-x")
        memory = 0.20 + 1.80 * uniform01(generator_seed, *key, "initial-memory")
        public_ewma = x
        events: list[Any] = []
        propensities: list[dict[str, Any]] = []

        # The long-gap allocation uses a genuinely unseen public time grid;
        # it does not merely attach a textual stratum name to the routine
        # schedule.  The number/order of state transitions remains unchanged.
        ticks = (
            (-12, -8, -4, -2, -1, 0)
            if stratum == "long-gap"
            else tuple(range(-5, 1))
        )
        for tick in ticks:
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
                    "selected_check": "Q1" if take_q1 else "NoCheck",
                    "phase": "observed-prefix",
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
        current_public_y = y
        for offset in range(4):
            # The behavior policy is a function of the currently available
            # public prefix only.  Hidden x/memory never enter these logits.
            probabilities = self._behavior(current_public_y, public_ewma)
            p_q1 = 0.12 + 0.30 / (1.0 + math.exp(-(public_ewma - 0.8)))
            take_q1 = bernoulli(
                p_q1, generator_seed, *key, "future-q1-take", offset
            )
            choice = categorical(
                probabilities, generator_seed, *key, "future-action", offset
            )
            action = (None, "A1", "A2")[choice]
            propensities.append(
                {
                    "decision_at": offset,
                    "probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                        "A2": probabilities[2],
                    },
                    "selected": "NoNewAction" if action is None else action,
                    "check_probabilities": {
                        "Q1": p_q1,
                        "NoCheck": 1.0 - p_q1,
                    },
                    "selected_check": "Q1" if take_q1 else "NoCheck",
                    "phase": "factual-future",
                    "public_inputs": {
                        "latest_obs_0": current_public_y,
                        "public_ewma": public_ewma,
                    },
                }
            )
            x, memory = self._step(
                x,
                memory,
                action,
                0.04 * normal01(generator_seed, *key, "future-process", offset),
            )
            current_public_y = x + 0.05 * normal01(
                generator_seed, *key, "future-q0", offset
            )
            public_ewma = 0.75 * public_ewma + current_public_y
            utility -= 0.97**offset * (
                x * x
                + 0.45 * memory * memory
                + 0.06 * float(action is not None)
                + 0.08 * float(take_q1)
            )
            observations = {"obs_0": current_public_y}
            if take_q1:
                observations["obs_1"] = memory + 0.10 * normal01(
                    generator_seed, *key, "future-q1-value", offset
                )
            future.append(
                {
                    "offset": offset + 1,
                    "observations": observations,
                    "performed_action": "NoNewAction" if action is None else action,
                    "performed_check": "Q1" if take_q1 else "NoCheck",
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
            oracle_anchor={
                "stratum": stratum,
                "markov_state": ["x", "r"],
                "probe_attribution": "candidate-attributable",
                "behavior_policy_inputs": "public-prefix-only",
            },
        )

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        """Classify W14 path/schedule cells without consulting hidden memory.

        ``schedule_time_holdout`` is tied to the frozen generator allocation,
        while ``boundary_tail`` is replayed directly from candidate-visible
        observations.  The latter cannot be manufactured by a private memory
        class.  Pair membership is an explicit judge-side probe-cohort bit.
        """

        if type(episode) is not PrivateEpisode or episode.environment_key != self.environment_key:
            raise ProtocolViolation("W14 strata require a W14 PrivateEpisode")
        strata = ["iid_support"]
        obs0_rows = _channel_rows(episode, "obs_0")
        values = tuple(value for _, value in obs0_rows)
        if not values:
            raise ProtocolViolation("W14 stratum classification requires public obs_0")
        if any(value <= 0.05 or value >= 1.0 for value in values):
            strata.append("boundary_tail")

        pair_member = episode.oracle_anchor.get("behavior_pair_member", False)
        if type(pair_member) is not bool:
            raise ProtocolViolation("W14 behavior-pair witness must be boolean")
        cell = episode.oracle_anchor.get("stratum")
        if pair_member:
            if cell is not None or episode.factual_future or episode.action_propensities:
                raise ProtocolViolation("W14 pair witness is inconsistent with a population row")
        else:
            allowed = {
                WorldSplit.TRAIN: {"short-pulse"},
                WorldSplit.VALIDATION: {"intermittent-pulse"},
                WorldSplit.SEALED_TEST: {
                    "same-current-different-memory",
                    "same-sufficient-state-different-history",
                    "long-gap",
                    "routine",
                },
            }[episode.split]
            if cell not in allowed:
                raise ProtocolViolation("W14 episode lacks a valid generator-cell witness")
            public_times = tuple(row[0] for row in obs0_rows)
            has_long_gap = any(
                later - earlier > 1
                for earlier, later in zip(public_times, public_times[1:])
            )
            if (cell == "long-gap") != has_long_gap:
                raise ProtocolViolation("W14 schedule witness contradicts public event times")
            if has_long_gap:
                strata.append("schedule_time_holdout")
        if pair_member:
            strata.append("behavior_pair")
        return tuple(strata)

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
        particles = self._public_posterior(episode)
        utility = 0.0
        variance = 0.0
        steps: list[dict[str, Any]] = []
        working = [(x, memory, weight) for x, memory, weight in particles]
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = "A1" if "A1" in ids else "A2" if "A2" in ids else None
            working = [
                (*self._step(x, memory, action), weight)
                for x, memory, weight in working
            ]
            variance = 0.90**2 * variance + 0.04**2
            check_cost = 0.08 * float("Q1" in ids)
            expected = math.fsum(
                weight * (x * x + 0.45 * memory * memory)
                for x, memory, weight in working
            )
            expected += variance + 0.06 * float(action is not None) + check_cost
            utility -= 0.97**offset * expected
            mean_x = math.fsum(weight * x for x, _, weight in working)
            mean_memory = math.fsum(
                weight * memory for _, memory, weight in working
            )
            var_x = math.fsum(
                weight * (x - mean_x) ** 2 for x, _, weight in working
            ) + variance
            var_memory = math.fsum(
                weight * (memory - mean_memory) ** 2
                for _, memory, weight in working
            )
            steps.append(
                {
                    "offset": offset + 1,
                    "activity_mean": mean_x,
                    "memory_mean": mean_memory,
                    "activity_variance": var_x,
                    "memory_variance": var_memory,
                }
            )
        p_c0 = math.fsum(weight for _, memory, weight in particles if memory < 0.9)
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
                    "C0": p_c0,
                    "C1": 1.0 - p_c0,
                },
            },
            outcome_distribution={
                "utility_family": "activity-memory-burden",
                "expected_utility": float(utility),
            },
            expected_utility=float(utility),
            numerical_diagnostics={
                "method": "public-prefix-augmented-state-grid",
                "absolute_error_bound": 0.04,
                "markov_closure": ["activity", "path_memory"],
                "posterior_fork": "single-public-posterior",
                "private_state_used": False,
            },
        )

    @staticmethod
    def _public_memory_summary(episode: PrivateEpisode) -> tuple[float, float]:
        """Compute the finite lag statistic from public observations/actions."""

        observations = _channel_rows(episode, "obs_0")
        if not observations:
            raise ProtocolViolation("W14 requires public obs_0")
        actions_by_tick = {
            event.occurred_at: str(event.payload.get("action_id"))
            for event in episode.public_history.events
            if event.kind is EventKind.PERFORMED_TREATMENT
        }
        previous_tick, first_value = observations[0]
        summary = first_value
        for tick, value in observations[1:]:
            # A2 at the previous decision clears memory before the next Q0.
            summary = 0.75 * summary + value - 0.45 * float(
                actions_by_tick.get(previous_tick) == "A2"
            )
            previous_tick = tick
        return observations[-1][1], max(0.0, summary)

    @classmethod
    def _public_posterior(
        cls, episode: PrivateEpisode
    ) -> tuple[tuple[float, float, float], ...]:
        current, summary = cls._public_memory_summary(episode)
        memory_checks = _channel_rows(episode, "obs_1")
        if memory_checks:
            check_tick, checked_memory = memory_checks[-1]
            latest_tick = _channel_rows(episode, "obs_0")[-1][0]
            if check_tick < latest_tick:
                action_at_check = any(
                    event.kind is EventKind.PERFORMED_TREATMENT
                    and event.occurred_at == check_tick
                    and event.payload.get("action_id") == "A2"
                    for event in episode.public_history.events
                )
                checked_memory = max(
                    0.0,
                    0.75 * checked_memory
                    + current
                    - 0.45 * float(action_at_check),
                )
            summary = 0.35 * summary + 0.65 * checked_memory
        rows: list[tuple[tuple[Any, ...], float]] = []
        x_low, x_high = max(0.0, current - 0.30), max(0.35, current + 0.30)
        r_low, r_high = max(0.0, summary - 0.70), max(0.80, summary + 0.70)
        for i in range(25):
            x = x_low + (x_high - x_low) * i / 24.0
            for j in range(31):
                memory = r_low + (r_high - r_low) * j / 30.0
                score = _normal_log_likelihood(current, x, 0.07)
                score += _normal_log_likelihood(summary, memory, 0.18)
                rows.append(((x, memory), score))
        return _normalise_log_particles(rows)  # type: ignore[return-value]

    def reference_counterfactual(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> float:
        """Independent rectangular quadrature with inline lag transitions."""

        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the finite W14 policy set")
        current, summary = self._public_memory_summary(episode)
        checks = _channel_rows(episode, "obs_1")
        if checks:
            check_tick, checked_memory = checks[-1]
            latest_tick = _channel_rows(episode, "obs_0")[-1][0]
            if check_tick < latest_tick:
                cleared = any(
                    event.kind is EventKind.PERFORMED_TREATMENT
                    and event.occurred_at == check_tick
                    and event.payload.get("action_id") == "A2"
                    for event in episode.public_history.events
                )
                checked_memory = max(
                    0.0,
                    0.75 * checked_memory + current - 0.45 * float(cleared),
                )
            summary = 0.35 * summary + 0.65 * checked_memory
        raw: list[tuple[float, float, float]] = []
        x_low, x_high = max(0.0, current - 0.35), max(0.40, current + 0.35)
        r_low, r_high = max(0.0, summary - 0.80), max(0.90, summary + 0.80)
        for i in range(40):
            x = x_low + (x_high - x_low) * (i + 0.5) / 40.0
            for j in range(48):
                memory = r_low + (r_high - r_low) * (j + 0.5) / 48.0
                score = _normal_log_likelihood(current, x, 0.07)
                score += _normal_log_likelihood(summary, memory, 0.18)
                raw.append((x, memory, score))
        peak = max(row[2] for row in raw)
        weighted = [(x, r, math.exp(max(-745.0, s - peak))) for x, r, s in raw]
        norm = math.fsum(row[2] for row in weighted)
        particles = [(x, r, w / norm) for x, r, w in weighted]
        variance = 0.0
        utility = 0.0
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = "A1" if "A1" in ids else "A2" if "A2" in ids else None
            next_rows = []
            for x, memory, weight in particles:
                next_x = max(
                    0.0,
                    0.90 * x + 0.08 - 0.32 * float(action == "A1")
                    + 0.10 * math.tanh(memory - 1.0),
                )
                next_memory = max(
                    0.0,
                    0.75 * memory + next_x - 0.45 * float(action == "A2"),
                )
                next_rows.append((next_x, next_memory, weight))
            particles = next_rows
            variance = 0.90**2 * variance + 0.04**2
            expected = math.fsum(
                weight * (x * x + 0.45 * memory * memory)
                for x, memory, weight in particles
            )
            expected += variance + 0.06 * float(action is not None)
            expected += 0.08 * float("Q1" in ids)
            utility -= 0.97**offset * expected
        return float(utility)

    def private_state_upper_bound(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> float:
        """Judge-only realized lag-state comparator, excluded from scoring."""

        x = float(episode.hidden_state_at_cut["current_activity"])
        memory = float(episode.hidden_state_at_cut["path_memory"])
        utility = 0.0
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = "A1" if "A1" in ids else "A2" if "A2" in ids else None
            x, memory = self._step(x, memory, action)
            utility -= 0.97**offset * (
                x * x + 0.45 * memory * memory
                + 0.06 * float(action is not None) + 0.08 * float("Q1" in ids)
            )
        return float(utility)

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
            oracle_anchor={
                "fixture": "paired",
                "behavior_pair_member": True,
                "probe_attribution": "candidate-attributable",
            },
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
            # .75*(.75*.80+.10)+.42 ==
            # .75*(.75*.20+.55)+.42, so the public finite statistic agrees.
            history_values=(0.80, 0.10, 0.42),
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
