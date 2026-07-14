"""W18: unseen mechanisms with public-evidence-attributable OOD scoring.

The OOD mask is deliberately a function of public bounded-support evidence.
Private membership in the unseen class is insufficient: overlap aliases are
marked ``OOD_IRREDUCIBLE`` and excluded from forced-OOD scoring.
"""

from __future__ import annotations

from dataclasses import replace
import math
from typing import Any

from ..canonical import digest_json
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
from .randomness import categorical, uniform01
from .w01 import (
    _case_key,
    _check_plan,
    _json_float,
    _observation_event,
    _single_plan,
    _visible_history,
)


_PARAMETERS = {
    "C0": (0.85, 0.10, 0.30, 1.0),
    "C1": (0.85, -0.10, -0.30, -1.0),
    "C2": (0.55, 0.35, -0.55, 0.0),
    "Cdev": (0.70, 0.18, -0.10, 0.5),
}
_NOISE_HALF_WIDTH = 0.03
_PRECISE_HALF_WIDTH = 0.01
_KNOWN_TOLERANCE = 2.0 * _NOISE_HALF_WIDTH + 1e-12
_OBS_SD = _NOISE_HALF_WIDTH / math.sqrt(3.0)


def _bounded_noise(seed: int, *keys: str | int, width: float = _NOISE_HALF_WIDTH) -> float:
    return width * (2.0 * uniform01(seed, *keys) - 1.0)


def _latest(episode: PrivateEpisode, channel: str) -> float:
    values = [
        float(event.payload["value"])
        for event in episode.public_history.events
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == channel
    ]
    if not values:
        raise ValueError(f"missing {channel}")
    return values[-1]


class W18World(MicroWorld):
    @property
    def environment_key(self) -> str:
        return "ucm-private-environment-18"

    @property
    def catalog(self) -> PublicCatalog:
        return PublicCatalog(
            observations=(ChannelSpec("obs_0"), ChannelSpec("obs_1")),
            actions=(ActionSpec("A1", cost=0.08),),
            checks=(
                CheckSpec("Q0", ("obs_0", "obs_1"), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_0", "obs_1"), (1, 1), cost=0.08),
            ),
            diagnostic_labels=("C0", "C1", "unknown"),
            horizons=(1, 4, 8),
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W18 horizon")
        policies = [ActionPlan(PlanKind.NO_NEW_ACTION), _single_plan("A1"), _check_plan("Q1")]
        if horizon > 1:
            policies.append(
                ActionPlan(
                    PlanKind.ACTION_SEQUENCE,
                    tuple(PlannedAction(i, "A1") for i in range(horizon)),
                )
            )
        return tuple(policies)

    @staticmethod
    def known_support_values(obs_0: float, obs_1: float) -> tuple[bool, bool]:
        """Return public bounded-support feasibility for C0 and C1."""

        return (
            abs(obs_1 - obs_0) <= _KNOWN_TOLERANCE,
            abs(obs_1 + obs_0) <= _KNOWN_TOLERANCE,
        )

    def known_support(self, episode: PrivateEpisode) -> tuple[bool, bool]:
        return self.known_support_values(_latest(episode, "obs_0"), _latest(episode, "obs_1"))

    def public_ood_attributable(self, episode: PrivateEpisode) -> bool:
        """This predicate uses candidate-visible bytes only, never private class."""

        support = self.known_support(episode)
        return not any(support)

    def attribution_tag(self, episode: PrivateEpisode) -> str:
        mechanism = str(episode.invariant_parameters["mechanism"])
        attributable = self.public_ood_attributable(episode)
        if mechanism == "C2":
            return "OOD_ATTRIBUTABLE" if attributable else "OOD_IRREDUCIBLE"
        if mechanism == "Cdev":
            return "DEV_ANOMALY_ATTRIBUTABLE" if attributable else "DEV_ANOMALY_OVERLAP"
        if bool(episode.invariant_parameters.get("known_extreme", False)):
            return "KNOWN_EXTREME"
        return "KNOWN"

    @staticmethod
    def scored_for_forced_ood(tag: str) -> bool:
        return tag == "OOD_ATTRIBUTABLE"

    @staticmethod
    def _mechanism_for(split: WorldSplit, episode_index: int) -> tuple[str, str]:
        if split is WorldSplit.TRAIN:
            return ("C0" if episode_index % 2 == 0 else "C1"), "known"
        if split is WorldSplit.VALIDATION and episode_index % 5 == 0:
            return "Cdev", "development-anomaly"
        if split is WorldSplit.SEALED_TEST and episode_index % 5 == 0:
            subtype = "attributable" if (episode_index // 5) % 2 == 0 else "overlap"
            return "C2", subtype
        return ("C0" if episode_index % 2 == 0 else "C1"), "known"

    def _initial_x(
        self,
        split: WorldSplit,
        seed: int,
        episode_index: int,
        mechanism: str,
        subtype: str,
    ) -> tuple[float, bool]:
        if mechanism == "C2" and subtype == "attributable":
            magnitude = 0.50 + 0.90 * uniform01(
                seed, "w18", split.value, episode_index, "ood-magnitude"
            )
            sign = -1.0 if (episode_index // 5) % 4 >= 2 else 1.0
            return sign * magnitude, False
        if mechanism == "C2" and subtype == "overlap":
            return 0.012 * (2.0 * uniform01(seed, "w18", split.value, episode_index, "alias-x") - 1.0), False
        known_extreme = split is WorldSplit.SEALED_TEST and episode_index % 10 in {1, 9}
        if known_extreme:
            return (1.35 if episode_index % 2 == 0 else -1.35), True
        return 1.15 * (
            2.0 * uniform01(seed, "w18", split.value, episode_index, "x") - 1.0
        ), False

    @staticmethod
    def _action_probabilities(obs_0: float) -> tuple[float, float]:
        p_a1 = 0.15 + 0.70 * (1.0 / (1.0 + math.exp(-2.0 * obs_0)))
        return 1.0 - p_a1, p_a1

    def _diagnostic_target_from_public(
        self, mechanism: str, obs_0: float, obs_1: float
    ) -> dict[str, float]:
        support = self.known_support_values(obs_0, obs_1)
        if mechanism in {"C2", "Cdev"} and not any(support):
            return {"C0": 0.0, "C1": 0.0, "unknown": 1.0}
        count = int(support[0]) + int(support[1])
        if count:
            return {
                "C0": float(support[0]) / count,
                "C1": float(support[1]) / count,
                "unknown": 0.0,
            }
        return {"C0": 0.0, "C1": 0.0, "unknown": 1.0}

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        mechanism, subtype = self._mechanism_for(split, episode_index)
        x, known_extreme = self._initial_x(
            split, generator_seed, episode_index, mechanism, subtype
        )
        _, _, _, sign = _PARAMETERS[mechanism]
        obs_0 = x + _bounded_noise(
            generator_seed, "w18", split.value, episode_index, "obs", 0
        )
        obs_1 = sign * x + _bounded_noise(
            generator_seed, "w18", split.value, episode_index, "obs", 1
        )
        events = [
            _observation_event(
                generator_seed,
                channel,
                value,
                collected_at=0,
                available_at=0,
                slot=episode_index * 8 + slot,
            )
            for slot, (channel, value) in enumerate((("obs_0", obs_0), ("obs_1", obs_1)))
        ]
        probabilities = self._action_probabilities(obs_0)
        selected = categorical(
            probabilities,
            generator_seed,
            "w18",
            split.value,
            episode_index,
            "factual-action",
        )
        action = ("NoNewAction", "A1")[selected]
        rho, bias, beta, _ = _PARAMETERS[mechanism]
        next_x = (
            rho * x
            + bias
            - beta * (action == "A1")
            + _bounded_noise(
                generator_seed,
                "w18",
                split.value,
                episode_index,
                "future-process",
            )
        )
        utility = -(next_x * next_x + 0.08 * (action == "A1"))
        target = self._diagnostic_target_from_public(mechanism, obs_0, obs_1)
        episode = PrivateEpisode(
            case_key=_case_key(
                self.environment_key, split, generator_seed, episode_index
            ),
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"x": _json_float(x)},
            invariant_parameters={
                "mechanism": mechanism,
                "subtype": subtype,
                "known_extreme": known_extreme,
            },
            diagnostic_target=target,
            factual_future=[
                {
                    "offset": 1,
                    "observations": {"obs_0": _json_float(next_x)},
                    "performed_action": action,
                }
            ],
            action_propensities=[
                {
                    "decision_at": 0,
                    "probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                    },
                    "selected": action,
                }
            ],
            factual_utility=_json_float(utility),
            oracle_anchor={
                "support_rule": "bounded-known-kernel-v1",
                "attribution_tolerance": _KNOWN_TOLERANCE,
            },
        )
        # The tag is judge-only and is computed after construction from public
        # support plus private membership; it never enters public_history.
        return replace(
            episode,
            oracle_anchor={
                **episode.oracle_anchor,
                "ood_attribution": self.attribution_tag(episode),
                "forced_ood_scored": self.scored_for_forced_ood(
                    self.attribution_tag(episode)
                ),
            },
        )

    def _policy_uses_a1(self, policy: ActionPlan, offset: int) -> bool:
        return policy.kind is PlanKind.ACTION_SEQUENCE and any(
            action.offset == offset and action.action_id == "A1"
            for action in policy.actions
        )

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W18 horizon")
        support = self.known_support(episode)
        if support == (True, False):
            public_components = (("C0", 1.0),)
            diagnostic = {"C0": 1.0, "C1": 0.0, "unknown": 0.0}
        elif support == (False, True):
            public_components = (("C1", 1.0),)
            diagnostic = {"C0": 0.0, "C1": 1.0, "unknown": 0.0}
        elif support == (True, True):
            public_components = (("C0", 0.5), ("C1", 0.5))
            diagnostic = {"C0": 0.5, "C1": 0.5, "unknown": 0.0}
        else:
            # The known support is empty.  C2's identity remains unavailable to
            # the candidate; this public "unknown-reference" component is the
            # frozen judge operator for unsafe non-abstain evaluation.
            public_components = (("C2", 1.0),)
            diagnostic = {"C0": 0.0, "C1": 0.0, "unknown": 1.0}
        check_cost = 0.08 if (
            policy.kind is PlanKind.ACTION_SEQUENCE
            and any(action.action_id == "Q1" for action in policy.actions)
        ) else 0.0
        components = []
        utility = 0.0
        for mechanism, weight in public_components:
            rho, bias, beta, sign = _PARAMETERS[mechanism]
            mean = _latest(episode, "obs_0")
            variance = _OBS_SD**2
            steps = []
            component_utility = 0.0
            for offset in range(horizon):
                a1 = self._policy_uses_a1(policy, offset)
                mean = rho * mean + bias - beta * a1
                variance = rho * rho * variance + _NOISE_HALF_WIDTH**2 / 3.0
                cost = mean * mean + variance + 0.08 * a1
                if offset == 0:
                    cost += check_cost
                component_utility -= 0.97**offset * cost
                steps.append(
                    {
                        "offset": offset + 1,
                        "obs_0_mean": _json_float(mean),
                        "obs_1_mean": _json_float(sign * mean),
                        "latent_variance": _json_float(variance),
                    }
                )
            utility += weight * component_utility
            components.append(
                {
                    "public_component": mechanism if mechanism != "C2" else "unknown-reference",
                    "weight": weight,
                    "steps": steps,
                    "expected_utility": _json_float(component_utility),
                }
            )
        public_tag = "OOD_ATTRIBUTABLE" if not any(support) else "KNOWN_SUPPORT_PRESENT"
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "bounded-noise-affine",
                "components": components,
                "precise_check_half_width": _PRECISE_HALF_WIDTH,
            },
            latent_distribution={
                "family": "bounded-noise-affine",
                "components": components,
                "known_support": {"C0": support[0], "C1": support[1]},
                "diagnostic_posterior": diagnostic,
            },
            outcome_distribution={
                "expected_utility": _json_float(utility),
                "public_ood_attribution": public_tag,
                "forced_ood_scored": not any(support),
                "unsafe_non_abstain_reference_only": not any(support),
            },
            expected_utility=_json_float(utility),
            numerical_diagnostics={"method": "analytic-bounded-affine", "absolute_error_bound": 0.0},
        )

    def _fixture(
        self,
        *,
        seed: int,
        side: int,
        mechanism: str,
        obs_0: float,
        obs_1: float,
        known_extreme: bool = False,
    ) -> PrivateEpisode:
        events = [
            _observation_event(
                seed,
                channel,
                value,
                collected_at=0,
                available_at=0,
                slot=slot,
            )
            for slot, (channel, value) in enumerate((("obs_0", obs_0), ("obs_1", obs_1)))
        ]
        episode = PrivateEpisode(
            case_key=digest_json({"pair": "w18", "seed": seed, "side": side}),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"x": obs_0},
            invariant_parameters={
                "mechanism": mechanism,
                "subtype": "fixture",
                "known_extreme": known_extreme,
            },
            diagnostic_target=self._diagnostic_target_from_public(
                mechanism, obs_0, obs_1
            ),
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={"fixture": True},
        )
        return replace(
            episode,
            oracle_anchor={
                "fixture": True,
                "ood_attribution": self.attribution_tag(episode),
                "forced_ood_scored": self.scored_for_forced_ood(
                    self.attribution_tag(episode)
                ),
            },
        )

    def attributable_ood_fixture(self, seed: int = 1801) -> PrivateEpisode:
        return self._fixture(
            seed=seed, side=0, mechanism="C2", obs_0=0.80, obs_1=0.0
        )

    def irreducible_alias_pair(self, seed: int = 1803) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Exact public prefix shared by unseen C2 and feasible known C0."""

        unseen = self._fixture(
            seed=seed, side=0, mechanism="C2", obs_0=0.0, obs_1=0.0
        )
        known = replace(
            unseen,
            case_key=digest_json({"pair": "w18-alias", "seed": seed, "side": 1}),
            invariant_parameters={
                "mechanism": "C0",
                "subtype": "fixture",
                "known_extreme": False,
            },
            diagnostic_target={"C0": 0.5, "C1": 0.5, "unknown": 0.0},
            oracle_anchor={
                "fixture": True,
                "ood_attribution": "KNOWN",
                "forced_ood_scored": False,
            },
        )
        return unseen, known

    def known_extreme_fixture(self, seed: int = 1805) -> PrivateEpisode:
        return self._fixture(
            seed=seed,
            side=0,
            mechanism="C0",
            obs_0=1.35,
            obs_1=1.35,
            known_extreme=True,
        )


World = W18World

__all__ = ["W18World", "World"]
