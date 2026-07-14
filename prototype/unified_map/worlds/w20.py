"""W20: feedback and treatment-history dependence with finite memory.

All performed doses are public and ``r`` is their exact exponentially decayed
sufficient statistic.  Raw action history is not itself the state truth:
different histories with the same current ``(x, r)`` must have identical
counterfactual behaviour.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..canonical import digest_json
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
    _check_plan,
    _exploratory_probabilities,
    _json_float,
    _observation_event,
    _softmax,
    _standard_policy_set,
    _treatment_event,
    _visible_history,
)


_DOSE = {"A1": 1.0, "A2": 0.5}
_RHO = 0.90
_BIAS = 0.10
_MEMORY_DECAY = 0.50
_THRESHOLD = 0.75
_PROCESS_SD = 0.04
_OBS_SD = 0.05
_CONTINUE_DIGEST = digest_json(
    {"domain": "w20-explicit-current-schedule/1", "dose_schedule": "A1-every-tick"}
)


def _latest_observation(episode: PrivateEpisode, channel: str = "obs_0") -> float:
    values = [
        float(event.payload["value"])
        for event in episode.public_history.events
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == channel
    ]
    if not values:
        raise ValueError(f"missing {channel}")
    return values[-1]


class W20World(MicroWorld):
    @property
    def environment_key(self) -> str:
        return "ucm-private-environment-20"

    @property
    def catalog(self) -> PublicCatalog:
        return PublicCatalog(
            observations=(ChannelSpec("obs_0"), ChannelSpec("obs_1")),
            actions=(ActionSpec("A1", cost=0.06), ActionSpec("A2", cost=0.015)),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.08),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W20 horizon")
        policies = list(
            _standard_policy_set(
                horizon, treatments=("A1", "A2"), checks=("Q1",)
            )
        )
        policies.extend(
            (
                ActionPlan(PlanKind.STOP_CONTROLLABLE),
                ActionPlan(
                    PlanKind.CONTINUE_CURRENT, policy_digest=_CONTINUE_DIGEST
                ),
            )
        )
        return tuple(policies)

    @staticmethod
    def gain(exposure: float) -> float:
        return 0.40 if exposure < _THRESHOLD else -0.35

    @classmethod
    def transition(
        cls, x: float, exposure: float, dose: float, noise: float = 0.0
    ) -> tuple[float, float]:
        next_x = _RHO * x + _BIAS - cls.gain(exposure) * dose + noise
        next_exposure = _MEMORY_DECAY * exposure + dose
        return next_x, next_exposure

    @staticmethod
    def exposure_from_history(episode: PrivateEpisode) -> float:
        """Exact r at the cut, reconstructed from public performed actions."""

        observation_ticks = [
            event.occurred_at
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_0"
        ]
        if not observation_ticks:
            raise ValueError("W20 history has no timeline anchor")
        cut = episode.public_history.as_of_available_at
        start = min(observation_ticks)
        performed = {
            event.occurred_at: str(event.payload["action_id"])
            for event in episode.public_history.events
            if event.kind is EventKind.PERFORMED_TREATMENT
        }
        exposure = 0.0
        for tick in range(start, cut):
            exposure = _MEMORY_DECAY * exposure + _DOSE.get(
                performed.get(tick, "NoNewAction"), 0.0
            )
        return exposure

    @staticmethod
    def _behavior_probabilities(y: float, rhat: float) -> tuple[float, float, float]:
        logits = (0.3, 0.9 * y - 0.6 * rhat, 0.6 * y - 0.3 * rhat)
        return _exploratory_probabilities(_softmax(logits), exploration=0.10)

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        x = 0.20 + uniform01(
            generator_seed, "w20", split.value, episode_index, "x"
        )
        exposure = 0.0
        events = []
        propensities: list[dict[str, Any]] = []
        for tick in range(-4, 1):
            observed = x + _OBS_SD * normal01(
                generator_seed, "w20", split.value, episode_index, "obs", tick
            )
            events.append(
                _observation_event(
                    generator_seed,
                    "obs_0",
                    observed,
                    collected_at=tick,
                    available_at=tick,
                    slot=episode_index * 32,
                )
            )
            if tick == 0:
                break
            probabilities = self._behavior_probabilities(observed, exposure)
            selected = categorical(
                probabilities,
                generator_seed,
                "w20",
                split.value,
                episode_index,
                "behavior",
                tick,
            )
            action = ("NoNewAction", "A1", "A2")[selected]
            propensities.append(
                {
                    "decision_at": tick,
                    "probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                        "A2": probabilities[2],
                    },
                    "selected": action,
                }
            )
            if action in _DOSE:
                events.append(
                    _treatment_event(
                        generator_seed,
                        action,
                        tick,
                        slot=episode_index * 32,
                    )
                )
            x, exposure = self.transition(
                x,
                exposure,
                _DOSE.get(action, 0.0),
                _PROCESS_SD
                * normal01(
                    generator_seed,
                    "w20",
                    split.value,
                    episode_index,
                    "process",
                    tick + 1,
                ),
            )
        if bernoulli(
            0.35,
            generator_seed,
            "w20",
            split.value,
            episode_index,
            "q1-available",
        ):
            events.append(
                _observation_event(
                    generator_seed,
                    "obs_1",
                    exposure
                    + 0.08
                    * normal01(
                        generator_seed,
                        "w20",
                        split.value,
                        episode_index,
                        "q1",
                    ),
                    collected_at=-1,
                    available_at=0,
                    slot=episode_index * 32 + 1,
                )
            )
        history = _visible_history(events, self.catalog)
        reconstructed = self.exposure_from_history(
            PrivateEpisode(
                case_key="temporary-w20-reconstruction",
                environment_key=self.environment_key,
                split=split,
                generator_seed=generator_seed,
                public_history=history,
                hidden_state_at_cut={},
                invariant_parameters={},
                diagnostic_target={},
                factual_future=[],
                action_propensities=[],
                factual_utility=0.0,
                oracle_anchor={},
            )
        )
        if abs(reconstructed - exposure) > 1e-12:
            raise AssertionError("public performed history failed to close W20 exposure")

        factual_x, factual_r = x, exposure
        future: list[dict[str, Any]] = []
        utility = 0.0
        for offset in range(4):
            probabilities = self._behavior_probabilities(factual_x, factual_r)
            selected = categorical(
                probabilities,
                generator_seed,
                "w20",
                split.value,
                episode_index,
                "future-action",
                offset,
            )
            action = ("NoNewAction", "A1", "A2")[selected]
            dose = _DOSE.get(action, 0.0)
            factual_x, factual_r = self.transition(
                factual_x,
                factual_r,
                dose,
                _PROCESS_SD
                * normal01(
                    generator_seed,
                    "w20",
                    split.value,
                    episode_index,
                    "future-process",
                    offset,
                ),
            )
            utility -= 0.97**offset * (factual_x * factual_x + 0.06 * dose * dose)
            future.append(
                {
                    "offset": offset + 1,
                    "observations": {"obs_0": _json_float(factual_x)},
                    "performed_action": action,
                    "exposure_memory": _json_float(factual_r),
                }
            )
        c = int(exposure >= _THRESHOLD)
        return PrivateEpisode(
            case_key=_case_key(
                self.environment_key, split, generator_seed, episode_index
            ),
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=history,
            hidden_state_at_cut={"x": _json_float(x), "r": _json_float(exposure)},
            invariant_parameters={"initial_exposure": 0.0, "memory_decay": _MEMORY_DECAY},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=_json_float(utility),
            oracle_anchor={
                "sufficient_statistic": ["x", "r"],
                "exposure_reconstructed_from_public_actions": True,
            },
        )

    def sufficient_state(self, episode: PrivateEpisode) -> tuple[float, float]:
        return _latest_observation(episode), self.exposure_from_history(episode)

    def _policy_schedule(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> list[str]:
        schedule = ["NoNewAction"] * horizon
        if policy.kind is PlanKind.ACTION_SEQUENCE:
            for action in policy.actions:
                if action.offset < horizon and action.action_id in _DOSE:
                    schedule[action.offset] = action.action_id
        elif policy.kind is PlanKind.CONTINUE_CURRENT:
            # The query digest commits an explicit A1 schedule.  It is not
            # inferred from raw factual history, preserving (x,r) closure.
            schedule = ["A1"] * horizon
        # NO_NEW_ACTION and STOP_CONTROLLABLE both have zero new dose; their
        # protocol identities remain distinct even when this world maps both to
        # the same physical schedule.
        return schedule

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W20 horizon")
        mean, exposure = self.sufficient_state(episode)
        variance = _OBS_SD**2
        schedule = self._policy_schedule(episode, policy, horizon)
        check_cost = 0.08 if (
            policy.kind is PlanKind.ACTION_SEQUENCE
            and any(action.action_id == "Q1" for action in policy.actions)
        ) else 0.0
        steps = []
        utility = 0.0
        for offset, action in enumerate(schedule):
            dose = _DOSE.get(action, 0.0)
            gain_before = self.gain(exposure)
            mean, exposure = self.transition(mean, exposure, dose)
            variance = _RHO**2 * variance + _PROCESS_SD**2
            cost = mean * mean + variance + 0.06 * dose * dose
            if offset == 0:
                cost += check_cost
            utility -= 0.97**offset * cost
            steps.append(
                {
                    "offset": offset + 1,
                    "mean": _json_float(mean),
                    "variance": _json_float(variance),
                    "exposure_memory": _json_float(exposure),
                    "gain_before_dose": _json_float(gain_before),
                    "dose": dose,
                }
            )
        c = int(self.sufficient_state(episode)[1] >= _THRESHOLD)
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "threshold-affine-gaussian",
                "steps": steps,
            },
            latent_distribution={
                "family": "finite-sufficient-state",
                "state_channels": ["x", "r"],
                "steps": steps,
                "diagnostic_posterior": {"C0": float(c == 0), "C1": float(c == 1)},
            },
            outcome_distribution={"expected_utility": _json_float(utility)},
            expected_utility=_json_float(utility),
            numerical_diagnostics={"method": "analytic-threshold-affine", "absolute_error_bound": 0.0},
        )

    def _fixture_episode(
        self,
        *,
        seed: int,
        side: str,
        actions: dict[int, str],
        earlier_values: dict[int, float],
        cut_x: float,
    ) -> PrivateEpisode:
        events = []
        for tick in range(-4, 1):
            value = cut_x if tick == 0 else earlier_values.get(tick, cut_x)
            events.append(
                _observation_event(
                    seed,
                    "obs_0",
                    value,
                    collected_at=tick,
                    available_at=tick,
                    slot=(0 if side == "left" else 100) + tick + 4,
                )
            )
            action = actions.get(tick)
            if action in _DOSE:
                events.append(
                    _treatment_event(
                        seed,
                        action,
                        tick,
                        slot=(0 if side == "left" else 100) + tick + 4,
                    )
                )
        history = _visible_history(events, self.catalog)
        temporary = PrivateEpisode(
            case_key=digest_json({"fixture": "w20", "seed": seed, "side": side}),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=history,
            hidden_state_at_cut={},
            invariant_parameters={},
            diagnostic_target={},
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={},
        )
        exposure = self.exposure_from_history(temporary)
        c = int(exposure >= _THRESHOLD)
        return replace(
            temporary,
            hidden_state_at_cut={"x": cut_x, "r": exposure},
            invariant_parameters={"initial_exposure": 0.0, "memory_decay": _MEMORY_DECAY},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            oracle_anchor={"fixture": side, "sufficient_statistic": ["x", "r"]},
        )

    def exposure_collision_pair(
        self, seed: int = 2001
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Same current x, but low/high r reverse the next A1 response sign."""

        low = self._fixture_episode(
            seed=seed,
            side="left",
            actions={},
            earlier_values={-4: 0.2, -3: 0.3, -2: 0.5, -1: 0.6},
            cut_x=0.70,
        )
        high = self._fixture_episode(
            seed=seed,
            side="right",
            actions={-2: "A1", -1: "A1"},
            earlier_values={-4: 1.0, -3: 0.9, -2: 0.8, -1: 0.75},
            cut_x=0.70,
        )
        return low, high

    def sufficient_statistic_false_split_pair(
        self, seed: int = 2003
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Different action histories ending in exactly the same public (x,r)."""

        first = self._fixture_episode(
            seed=seed,
            side="left",
            actions={-2: "A1"},
            earlier_values={-4: 0.1, -3: 0.3, -2: 0.9, -1: 0.8},
            cut_x=0.65,
        )
        second = self._fixture_episode(
            seed=seed,
            side="right",
            actions={-1: "A2"},
            earlier_values={-4: 0.7, -3: 0.6, -2: 0.5, -1: 0.4},
            cut_x=0.65,
        )
        if self.sufficient_state(first) != self.sufficient_state(second):
            raise AssertionError("W20 false-split construction did not close")
        return first, second


World = W20World

__all__ = ["W20World", "World"]
