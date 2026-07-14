"""W17: a newly revealed treatment can split a previously sufficient state.

S0 contains a one-shot public context marker, but that marker is irrelevant to
all S0 futures.  S1 adds A2, whose sign depends on the class correlated with the
old marker.  The first extension query is state-only: an old state may either
support A2 honestly or return ``scope_insufficient`` and request an explicit
offline migration.  Silent history replay is never represented here.
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
    _exploratory_probabilities,
    _json_float,
    _observation_event,
    _softmax,
    _standard_policy_set,
    _treatment_event,
    _visible_history,
)


_RHO = 0.92
_BIAS = 0.10
_A1_EFFECT = -0.25
_A2_MAGNITUDE = 0.55
_PROCESS_SD = 0.04
_OBS_SD = 0.05


def _latest(episode: PrivateEpisode, channel_id: str) -> float | int | None:
    values = [
        event.payload["value"]
        for event in episode.public_history.events
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == channel_id
    ]
    return values[-1] if values else None


def _schedule(policy: ActionPlan, horizon: int) -> list[str]:
    result = ["NoNewAction"] * horizon
    if policy.kind is PlanKind.ACTION_SEQUENCE:
        for action in policy.actions:
            if action.offset < horizon and action.action_id in {"A1", "A2"}:
                result[action.offset] = action.action_id
    return result


class W17World(MicroWorld):
    @property
    def environment_key(self) -> str:
        return "ucm-private-environment-17"

    @property
    def catalog(self) -> PublicCatalog:
        """Frozen S0 catalog; A2 is intentionally absent."""

        return PublicCatalog(
            observations=(
                ChannelSpec("obs_0"),
                ChannelSpec("obs_1", value_type="binary", unit="indicator", valid_range=(0, 1)),
            ),
            actions=(ActionSpec("A1", cost=0.05),),
            checks=(CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),),
            diagnostic_labels=("E0",),
            horizons=(1, 4, 8),
        )

    @property
    def extension_catalog(self) -> PublicCatalog:
        return PublicCatalog(
            observations=self.catalog.observations,
            actions=(ActionSpec("A1", cost=0.05), ActionSpec("A2", cost=0.08)),
            checks=self.catalog.checks,
            diagnostic_labels=("E0",),
            horizons=self.catalog.horizons,
        )

    @property
    def extension_commitment(self) -> str:
        return digest_json(
            {
                "domain": "ucm-extension-commitment/1",
                "environment": self.environment_key,
                "catalog_digest": self.extension_catalog.digest,
                "a2_effect": {"C0": -0.55, "C1": 0.55},
            }
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W17 horizon")
        return _standard_policy_set(horizon, treatments=("A1",), checks=())

    def extension_policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.extension_catalog.horizons:
            raise ValueError("unsupported W17 extension horizon")
        return _standard_policy_set(horizon, treatments=("A1", "A2"), checks=())

    @staticmethod
    def _behavior_probabilities(y: float) -> tuple[float, float]:
        return _exploratory_probabilities(_softmax((0.3, 0.8 * y)))

    @staticmethod
    def _marker_posterior_c1(marker: int | None) -> float:
        if marker is None:
            return 0.5
        return 0.95 if marker == 0 else 0.05

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        c = episode_index % 2
        x = 0.25 + uniform01(generator_seed, "w17", split.value, episode_index, "x")
        marker = int(
            bernoulli(
                0.95 if c == 0 else 0.05,
                generator_seed,
                "w17",
                split.value,
                episode_index,
                "context",
            )
        )
        events = [
            _observation_event(
                generator_seed,
                "obs_1",
                marker,
                collected_at=-4,
                available_at=-4,
                slot=episode_index * 32 + 1,
            )
        ]
        propensities: list[dict[str, Any]] = []
        for tick in range(-4, 1):
            observed = x + _OBS_SD * normal01(
                generator_seed, "w17", split.value, episode_index, "obs", tick
            )
            events.append(
                _observation_event(
                    generator_seed,
                    "obs_0",
                    observed,
                    collected_at=tick,
                    available_at=tick,
                    slot=episode_index * 32 + 2,
                )
            )
            if tick == 0:
                break
            probabilities = self._behavior_probabilities(observed)
            selected = categorical(
                probabilities,
                generator_seed,
                "w17",
                split.value,
                episode_index,
                "behavior",
                tick,
            )
            action = ("NoNewAction", "A1")[selected]
            propensities.append(
                {
                    "decision_at": tick,
                    "probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                    },
                    "selected": action,
                }
            )
            if action == "A1":
                events.append(
                    _treatment_event(
                        generator_seed, "A1", tick, slot=episode_index * 32
                    )
                )
            x = (
                _RHO * x
                + _BIAS
                + (_A1_EFFECT if action == "A1" else 0.0)
                + _PROCESS_SD
                * normal01(
                    generator_seed,
                    "w17",
                    split.value,
                    episode_index,
                    "process",
                    tick + 1,
                )
            )
        future: list[dict[str, Any]] = []
        utility = 0.0
        factual_x = x
        for offset in range(4):
            probabilities = self._behavior_probabilities(factual_x)
            selected = categorical(
                probabilities,
                generator_seed,
                "w17",
                split.value,
                episode_index,
                "future-action",
                offset,
            )
            action = ("NoNewAction", "A1")[selected]
            factual_x = (
                _RHO * factual_x
                + _BIAS
                + (_A1_EFFECT if action == "A1" else 0.0)
                + _PROCESS_SD
                * normal01(
                    generator_seed,
                    "w17",
                    split.value,
                    episode_index,
                    "future-process",
                    offset,
                )
            )
            utility -= 0.97**offset * (
                factual_x * factual_x + 0.05 * (action == "A1")
            )
            future.append(
                {
                    "offset": offset + 1,
                    "observations": {"obs_0": _json_float(factual_x)},
                    "performed_action": action,
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
            hidden_state_at_cut={"x": _json_float(x)},
            invariant_parameters={"stage": "S0", "class_index": c},
            diagnostic_target={"E0": 1.0},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=_json_float(utility),
            oracle_anchor={
                "semantic_stage": "S0",
                "private_class_behaviorally_relevant": False,
                "extension_commitment": self.extension_commitment,
            },
        )

    def as_extension_episode(self, episode: PrivateEpisode) -> PrivateEpisode:
        """Rebind public bytes to the revealed catalog without replaying them."""

        return replace(
            episode,
            case_key=digest_json(
                {"domain": "w17-extension-case", "base_case": episode.case_key}
            ),
            public_history=type(episode.public_history)(
                events=episode.public_history.events,
                as_of_available_at=episode.public_history.as_of_available_at,
                catalog_digest=self.extension_catalog.digest,
            ),
            invariant_parameters={
                **episode.invariant_parameters,
                "stage": "S1",
            },
            oracle_anchor={
                "semantic_stage": "S1",
                "extension_commitment": self.extension_commitment,
                "state_only_first_query": True,
            },
        )

    @staticmethod
    def legacy_extension_verdict(
        status: str, *, supported_and_correct: bool = False, replayed_history: bool = False
    ) -> str:
        if replayed_history:
            return "HARD_FAILURE"
        if status == "scope_insufficient":
            return "HONEST_LIMIT"
        if status == "supported" and supported_and_correct:
            return "PASS"
        return "HARD_FAILURE"

    def _public_class_posterior(self, episode: PrivateEpisode) -> float:
        marker = _latest(episode, "obs_1")
        return self._marker_posterior_c1(None if marker is None else int(marker))

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W17 horizon")
        extension = episode.public_history.catalog_digest == self.extension_catalog.digest
        allowed = {"A1", "A2"} if extension else {"A1"}
        if policy.kind is PlanKind.ACTION_SEQUENCE and any(
            action.action_id not in allowed for action in policy.actions
        ):
            raise ValueError("policy is outside the episode semantic scope")
        p_c1 = self._public_class_posterior(episode) if extension else 0.5
        components = []
        total_utility = 0.0
        schedule = _schedule(policy, horizon)
        for c, weight in ((0, 1.0 - p_c1), (1, p_c1)):
            mean = float(_latest(episode, "obs_0"))
            variance = _OBS_SD**2
            steps = []
            utility = 0.0
            g = 1.0 if c == 0 else -1.0
            for offset, action in enumerate(schedule):
                effect = _A1_EFFECT if action == "A1" else 0.0
                if action == "A2":
                    effect = -_A2_MAGNITUDE * g
                mean = _RHO * mean + _BIAS + effect
                variance = _RHO**2 * variance + _PROCESS_SD**2
                cost = mean * mean + variance
                cost += 0.05 * (action == "A1") + 0.08 * (action == "A2")
                utility -= 0.97**offset * cost
                steps.append(
                    {
                        "offset": offset + 1,
                        "mean": _json_float(mean),
                        "variance": _json_float(variance),
                    }
                )
            total_utility += weight * utility
            components.append(
                {
                    "class": f"C{c}",
                    "weight": _json_float(weight),
                    "steps": steps,
                    "expected_utility": _json_float(utility),
                }
            )
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "two-component-linear-gaussian",
                "components": components,
            },
            latent_distribution={
                "family": "two-component-linear-gaussian",
                "class_posterior": {"C0": 1.0 - p_c1, "C1": p_c1},
                "components": components,
            },
            outcome_distribution={
                "expected_utility": _json_float(total_utility),
                "scope": "S1" if extension else "S0",
            },
            expected_utility=_json_float(total_utility),
            numerical_diagnostics={"method": "analytic-finite-mixture", "absolute_error_bound": 0.0},
        )

    def extension_split_pair(self, seed: int = 1701) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Same S0 oracle state, opposite public context support for S1 A2."""

        base = self.generate_episode(WorldSplit.SEALED_TEST, seed, 0)
        latest_x = float(_latest(base, "obs_0"))
        common_obs = [
            _observation_event(
                seed,
                "obs_0",
                latest_x,
                collected_at=0,
                available_at=0,
                slot=900,
            )
        ]
        result = []
        for marker in (1, 0):
            events = [
                _observation_event(
                    seed,
                    "obs_1",
                    marker,
                    collected_at=-4,
                    available_at=-4,
                    slot=901,
                ),
                *common_obs,
            ]
            episode = replace(
                base,
                case_key=digest_json(
                    {"pair": "w17-extension", "seed": seed, "marker": marker}
                ),
                public_history=_visible_history(events, self.catalog),
                hidden_state_at_cut={"x": latest_x},
                invariant_parameters={"stage": "S0", "class_index": 1 - marker},
                oracle_anchor={"fixture": "extension-split", "marker": marker},
            )
            result.append(episode)
        return result[0], result[1]


World = W17World

__all__ = ["W17World", "World"]
