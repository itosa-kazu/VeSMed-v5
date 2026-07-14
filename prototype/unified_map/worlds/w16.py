"""W16: a sealed old state is refined by a newly revealed check.

The primary (S0) catalog intentionally makes the private class behaviourally
irrelevant.  ``extension_catalog`` is a separately committed S1 contract.  A
legacy candidate is allowed to answer ``scope_insufficient`` at the extension
boundary; that is recorded as an honest limit, not as an ordinary prediction
failure.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..canonical import digest_json
from ..schema import ActionPlan, EventKind, PlanKind, PlannedAction, VisibleDelta
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
    _exploratory_probabilities,
    _json_float,
    _observation_event,
    _softmax,
    _standard_policy_set,
    _treatment_event,
    _visible_history,
)


_RHO = 0.90
_BIAS = 0.10
_A1_EFFECT = -0.30
_PROCESS_SD = 0.04
_OBS_SD = 0.05


def _action_schedule(policy: ActionPlan, horizon: int, action_id: str = "A1") -> list[bool]:
    schedule = [False] * horizon
    if policy.kind is PlanKind.ACTION_SEQUENCE:
        for action in policy.actions:
            if action.offset < horizon and action.action_id == action_id:
                schedule[action.offset] = True
    return schedule


def _latest_value(episode: PrivateEpisode, channel_id: str) -> float | int | None:
    values = [
        event.payload["value"]
        for event in episode.public_history.events
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == channel_id
    ]
    return values[-1] if values else None


class W16World(MicroWorld):
    """Executable two-stage check-extension benchmark."""

    @property
    def environment_key(self) -> str:
        return "ucm-private-environment-16"

    @property
    def catalog(self) -> PublicCatalog:
        """The frozen primary S0 catalog."""

        return PublicCatalog(
            observations=(ChannelSpec("obs_0"),),
            actions=(ActionSpec("A1", cost=0.05),),
            checks=(CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),),
            diagnostic_labels=("E0",),
            horizons=(1, 4, 8),
        )

    @property
    def extension_catalog(self) -> PublicCatalog:
        """The S1 catalog revealed only after the primary state seal."""

        return PublicCatalog(
            observations=(
                ChannelSpec("obs_0"),
                ChannelSpec("obs_2", value_type="binary", unit="indicator", valid_range=(0, 1)),
            ),
            actions=(ActionSpec("A1", cost=0.05),),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q2", ("obs_2",), (1, 1), cost=0.08),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    @property
    def extension_commitment(self) -> str:
        """Commitment published before S1 identifiers/operators are revealed."""

        return digest_json(
            {
                "domain": "ucm-extension-commitment/1",
                "environment": self.environment_key,
                "catalog_digest": self.extension_catalog.digest,
                "operator": {
                    "p_result_1_given_C0": 0.05,
                    "p_result_1_given_C1": 0.95,
                    "delay": 1,
                },
            }
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W16 horizon")
        return _standard_policy_set(horizon, treatments=("A1",), checks=())

    def extension_policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.extension_catalog.horizons:
            raise ValueError("unsupported W16 extension horizon")
        policies = list(_standard_policy_set(horizon, treatments=("A1",), checks=("Q2",)))
        # A public, result-contingent policy encoded without a callback.  The
        # runner interprets this fixed policy identifier after Q2 is available.
        policies.append(
            ActionPlan(
                PlanKind.ACTION_SEQUENCE,
                (PlannedAction(0, "Q2", {"then": "A1_if_obs_2_is_1"}),),
            )
        )
        return tuple(policies)

    @staticmethod
    def _action_probabilities(y: float) -> tuple[float, float]:
        return _exploratory_probabilities(_softmax((0.3, 0.8 * y)))

    def _base_episode(
        self, split: WorldSplit, seed: int, episode_index: int
    ) -> PrivateEpisode:
        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        class_index = episode_index % 2
        x = 0.25 + uniform01(seed, "w16", split.value, episode_index, "x")
        events = []
        propensities: list[dict[str, Any]] = []
        for tick in range(-4, 1):
            observed = x + _OBS_SD * normal01(
                seed, "w16", split.value, episode_index, "obs", tick
            )
            events.append(
                _observation_event(
                    seed,
                    "obs_0",
                    observed,
                    collected_at=tick,
                    available_at=tick,
                    slot=episode_index * 32,
                )
            )
            if tick == 0:
                break
            probabilities = self._action_probabilities(observed)
            selected = categorical(
                probabilities,
                seed,
                "w16",
                split.value,
                episode_index,
                "behavior",
                tick,
            )
            action_id = ("NoNewAction", "A1")[selected]
            propensities.append(
                {
                    "decision_at": tick,
                    "probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                    },
                    "selected": action_id,
                }
            )
            if action_id == "A1":
                events.append(
                    _treatment_event(seed, "A1", tick, slot=episode_index * 32)
                )
            x = (
                _RHO * x
                + _BIAS
                + (_A1_EFFECT if action_id == "A1" else 0.0)
                + _PROCESS_SD
                * normal01(
                    seed, "w16", split.value, episode_index, "process", tick + 1
                )
            )

        history = _visible_history(events, self.catalog)
        future, factual_utility = self._factual_future(
            x, seed, episode_index, split, class_index
        )
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, split, seed, episode_index),
            environment_key=self.environment_key,
            split=split,
            generator_seed=seed,
            public_history=history,
            hidden_state_at_cut={"x": _json_float(x)},
            invariant_parameters={"stage": "S0", "class_index": class_index},
            diagnostic_target={"E0": 1.0},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=_json_float(factual_utility),
            oracle_anchor={
                "semantic_stage": "S0",
                "private_class_behaviorally_relevant": False,
                "extension_commitment": self.extension_commitment,
            },
        )

    def _factual_future(
        self,
        x: float,
        seed: int,
        episode_index: int,
        split: WorldSplit,
        class_index: int,
    ) -> tuple[list[dict[str, Any]], float]:
        del class_index  # S0 factual dynamics are deliberately class-free.
        future: list[dict[str, Any]] = []
        utility = 0.0
        for offset in range(4):
            probabilities = self._action_probabilities(x)
            selected = categorical(
                probabilities,
                seed,
                "w16",
                split.value,
                episode_index,
                "future-action",
                offset,
            )
            action_id = ("NoNewAction", "A1")[selected]
            x = (
                _RHO * x
                + _BIAS
                + (_A1_EFFECT if action_id == "A1" else 0.0)
                + _PROCESS_SD
                * normal01(
                    seed,
                    "w16",
                    split.value,
                    episode_index,
                    "future-process",
                    offset,
                )
            )
            utility -= 0.97**offset * (x * x + 0.05 * (action_id == "A1"))
            future.append(
                {
                    "offset": offset + 1,
                    "observations": {"obs_0": _json_float(x)},
                    "performed_action": action_id,
                }
            )
        return future, utility

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        """Generate the primary S0 episode; extensions never replace it."""

        return self._base_episode(split, generator_seed, episode_index)

    def extension_delta(
        self,
        result: int,
        *,
        seed: int,
        episode_index: int,
        ordered_at: int = -1,
        available_at: int = 0,
    ) -> VisibleDelta:
        if result not in (0, 1):
            raise ValueError("Q2 result must be binary")
        ordered = _check_event(
            seed, "Q2", ordered_at, performed=False, slot=episode_index * 64 + 1
        )
        observed = _observation_event(
            seed,
            "obs_2",
            result,
            collected_at=ordered_at,
            available_at=available_at,
            slot=episode_index * 64 + 2,
        )
        return VisibleDelta(advance_to=available_at, events=tuple(sorted((ordered, observed), key=lambda e: (e.available_at, e.occurred_at, e.kind.value, e.event_uid))))

    def generate_extension_episode(
        self,
        split: WorldSplit,
        generator_seed: int,
        episode_index: int,
        *,
        reveal_result: bool = True,
    ) -> PrivateEpisode:
        base = self._base_episode(split, generator_seed, episode_index)
        class_index = int(base.invariant_parameters["class_index"])
        events = list(base.public_history.events)
        result: int | None = None
        if reveal_result:
            probability = 0.95 if class_index == 1 else 0.05
            result = int(
                bernoulli(
                    probability,
                    generator_seed,
                    "w16",
                    split.value,
                    episode_index,
                    "q2-result",
                )
            )
            events.extend(
                self.extension_delta(
                    result, seed=generator_seed, episode_index=episode_index
                ).events
            )
        history = _visible_history(events, self.extension_catalog)
        posterior_c1 = 0.5 if result is None else (0.95 if result == 1 else 0.05)
        return replace(
            base,
            case_key=_case_key(
                self.environment_key + "-extension", split, generator_seed, episode_index
            ),
            public_history=history,
            invariant_parameters={"stage": "S1", "class_index": class_index},
            diagnostic_target={
                "C0": float(class_index == 0),
                "C1": float(class_index == 1),
            },
            oracle_anchor={
                "semantic_stage": "S1",
                "extension_commitment": self.extension_commitment,
                "q2_result": result,
                "public_posterior": {"C0": 1.0 - posterior_c1, "C1": posterior_c1},
            },
        )

    @staticmethod
    def legacy_extension_verdict(status: str, *, supported_and_correct: bool = False) -> str:
        """Grade the first state-only S1 query without converting honesty to error."""

        if status == "scope_insufficient":
            return "HONEST_LIMIT"
        if status == "supported" and supported_and_correct:
            return "PASS"
        return "HARD_FAILURE"

    def _posterior_c1(self, episode: PrivateEpisode) -> float:
        result = _latest_value(episode, "obs_2")
        if result is None:
            return 0.5
        return 0.95 if int(result) == 1 else 0.05

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W16 horizon")
        is_extension = episode.public_history.catalog_digest == self.extension_catalog.digest
        allowed = {"A1", "Q2"} if is_extension else {"A1"}
        if policy.kind is PlanKind.ACTION_SEQUENCE and any(
            action.action_id not in allowed for action in policy.actions
        ):
            raise ValueError("policy is outside the episode semantic scope")
        mean = float(_latest_value(episode, "obs_0"))
        variance = _OBS_SD**2
        schedule = _action_schedule(policy, horizon)
        steps: list[dict[str, Any]] = []
        utility = 0.0
        q2_cost = 0.0
        if policy.kind is PlanKind.ACTION_SEQUENCE and any(
            action.action_id == "Q2" for action in policy.actions
        ):
            q2_cost = 0.08
        for offset, uses_a1 in enumerate(schedule):
            mean = _RHO * mean + _BIAS + (_A1_EFFECT if uses_a1 else 0.0)
            variance = _RHO**2 * variance + _PROCESS_SD**2
            step_cost = mean * mean + variance + 0.05 * uses_a1
            if offset == 0:
                step_cost += q2_cost
            utility -= 0.97**offset * step_cost
            steps.append(
                {
                    "offset": offset + 1,
                    "mean": _json_float(mean),
                    "variance": _json_float(variance),
                }
            )
        posterior_c1 = self._posterior_c1(episode) if is_extension else 0.5
        diagnostic = (
            {"C0": 1.0 - posterior_c1, "C1": posterior_c1}
            if is_extension
            else {"E0": 1.0}
        )
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "linear-gaussian-plus-binary-readout",
                "steps": steps,
                "q2_predictive_probability": 0.5 if is_extension else None,
            },
            latent_distribution={
                "family": "linear-gaussian",
                "steps": steps,
                "diagnostic_posterior": diagnostic,
            },
            outcome_distribution={
                "expected_utility": _json_float(utility),
                "scope": "S1" if is_extension else "S0",
            },
            expected_utility=_json_float(utility),
            numerical_diagnostics={"method": "analytic-linear-gaussian", "absolute_error_bound": 0.0},
        )

    def pre_result_alias_pair(self, seed: int = 1601) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Private C0/C1 swap with exact candidate bytes before Q2 is available."""

        first = self.generate_extension_episode(
            WorldSplit.SEALED_TEST, seed, 0, reveal_result=False
        )
        second = replace(
            first,
            case_key=digest_json({"pair": "w16-pre-result", "seed": seed, "side": 1}),
            invariant_parameters={"stage": "S1", "class_index": 1},
            diagnostic_target={"C0": 0.0, "C1": 1.0},
        )
        return first, second

    def extension_result_pair(self, seed: int = 1603) -> tuple[PrivateEpisode, PrivateEpisode]:
        """One sealed old prefix locally refined by opposite Q2 result deltas."""

        base = self.generate_extension_episode(
            WorldSplit.SEALED_TEST, seed, 2, reveal_result=False
        )
        episodes = []
        for result in (0, 1):
            events = list(base.public_history.events)
            events.extend(
                self.extension_delta(result, seed=seed, episode_index=2).events
            )
            posterior_c1 = 0.95 if result else 0.05
            episodes.append(
                replace(
                    base,
                    case_key=digest_json(
                        {"pair": "w16-result", "seed": seed, "result": result}
                    ),
                    public_history=_visible_history(events, self.extension_catalog),
                    diagnostic_target={
                        "C0": 1.0 - posterior_c1,
                        "C1": posterior_c1,
                    },
                    oracle_anchor={
                        "fixture": "extension-result-pair",
                        "q2_result": result,
                    },
                )
            )
        return episodes[0], episodes[1]


World = W16World

__all__ = ["W16World", "World"]
