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

# The sealed scoring population is a finite stratified population.  A randomly
# selected candidate-visible row has these class priors; the row index and its
# private stratum are never conditioned on by the scoring oracle.
_SCORING_PRIORS = {
    WorldSplit.TRAIN: {"C0": 0.5, "C1": 0.5},
    WorldSplit.VALIDATION: {"C0": 0.4, "C1": 0.4, "Cdev": 0.2},
    WorldSplit.SEALED_TEST: {"C0": 0.4, "C1": 0.4, "C2": 0.2},
}


def _x_prior_components(
    split: WorldSplit, mechanism: str
) -> tuple[tuple[float, float, float], ...]:
    """Return ``(mixture weight, low, high)`` for the frozen x prior.

    ``low == high`` denotes a point mass.  The test generator uses exact
    ten-row strata: each known class is 75% regular and 25% low-density
    extreme; C2 is half bounded-away-from-zero and half an overlap point mass.
    """

    if mechanism in {"C0", "C1"}:
        if split is WorldSplit.SEALED_TEST:
            return (
                (0.75, -1.15, 1.15),
                (0.125, -1.45, -1.30),
                (0.125, 1.30, 1.45),
            )
        return ((1.0, -1.15, 1.15),)
    if mechanism == "C2":
        return (
            (0.25, -1.40, -0.50),
            (0.50, 0.0, 0.0),
            (0.25, 0.50, 1.40),
        )
    if mechanism == "Cdev":
        return ((1.0, -1.15, 1.15),)
    raise ValueError(f"unknown W18 mechanism {mechanism!r}")


def _emission_interval(
    mechanism: str, obs_0: float, obs_1: float, low: float, high: float
) -> tuple[float, float] | None:
    """Analytic intersection for two independent bounded-noise channels."""

    sign = _PARAMETERS[mechanism][3]
    lower = max(low, obs_0 - _NOISE_HALF_WIDTH)
    upper = min(high, obs_0 + _NOISE_HALF_WIDTH)
    if sign == 0.0:
        if abs(obs_1) > _NOISE_HALF_WIDTH:
            return None
    else:
        endpoint_a = (obs_1 - _NOISE_HALF_WIDTH) / sign
        endpoint_b = (obs_1 + _NOISE_HALF_WIDTH) / sign
        lower = max(lower, min(endpoint_a, endpoint_b))
        upper = min(upper, max(endpoint_a, endpoint_b))
    if lower > upper:
        return None
    return lower, upper


def _component_likelihood(
    mechanism: str,
    obs_0: float,
    obs_1: float,
    mixture_weight: float,
    low: float,
    high: float,
) -> float:
    interval = _emission_interval(mechanism, obs_0, obs_1, low, high)
    if interval is None:
        return 0.0
    emission_density = 1.0 / ((2.0 * _NOISE_HALF_WIDTH) ** 2)
    if low == high:
        return mixture_weight * emission_density
    overlap = max(0.0, interval[1] - interval[0])
    return mixture_weight * overlap / (high - low) * emission_density


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
        obs_0, obs_1 = _latest(episode, "obs_0"), _latest(episode, "obs_1")
        return tuple(
            self._class_likelihood(episode.split, mechanism, obs_0, obs_1) > 0.0
            for mechanism in ("C0", "C1")
        )  # type: ignore[return-value]

    @staticmethod
    def posterior_solver_provenance() -> dict[str, str]:
        return {
            "production": "analytic-interval-mixture-v1",
            "reference": "independent-midpoint-quadrature-v1",
        }

    @staticmethod
    def _class_likelihood(
        split: WorldSplit, mechanism: str, obs_0: float, obs_1: float
    ) -> float:
        return math.fsum(
            _component_likelihood(mechanism, obs_0, obs_1, weight, low, high)
            for weight, low, high in _x_prior_components(split, mechanism)
        )

    @classmethod
    def _mechanism_posterior_values(
        cls, split: WorldSplit, obs_0: float, obs_1: float
    ) -> dict[str, float]:
        raw = {
            mechanism: prior
            * cls._class_likelihood(split, mechanism, obs_0, obs_1)
            for mechanism, prior in _SCORING_PRIORS[split].items()
        }
        total = math.fsum(raw.values())
        if total <= 0.0:
            raise ValueError("W18 public history has zero likelihood under frozen regime")
        return {key: value / total for key, value in raw.items()}

    def public_posterior(self, episode: PrivateEpisode) -> dict[str, float]:
        """P(C0,C1,unknown | public H, frozen regime), never private truth."""

        mechanism = self._mechanism_posterior_values(
            episode.split, _latest(episode, "obs_0"), _latest(episode, "obs_1")
        )
        return {
            "C0": mechanism.get("C0", 0.0),
            "C1": mechanism.get("C1", 0.0),
            "unknown": mechanism.get("C2", 0.0) + mechanism.get("Cdev", 0.0),
        }

    def reference_public_posterior(self, episode: PrivateEpisode) -> dict[str, float]:
        """Source-distinct midpoint integration used only for certification."""

        y0, y1 = _latest(episode, "obs_0"), _latest(episode, "obs_1")
        raw: dict[str, float] = {}
        for mechanism, prior in _SCORING_PRIORS[episode.split].items():
            sign = _PARAMETERS[mechanism][3]
            likelihood = 0.0
            for weight, low, high in _x_prior_components(episode.split, mechanism):
                if low == high:
                    inside = (
                        abs(y0 - low) <= _NOISE_HALF_WIDTH
                        and abs(y1 - sign * low) <= _NOISE_HALF_WIDTH
                    )
                    likelihood += weight * float(inside) / (
                        (2.0 * _NOISE_HALF_WIDTH) ** 2
                    )
                    continue
                # An independent deterministic Riemann solver.  It deliberately
                # does not call the production interval-intersection functions.
                cells = 20001
                width = (high - low) / cells
                hits = 0
                for index in range(cells):
                    x = low + (index + 0.5) * width
                    if (
                        abs(y0 - x) <= _NOISE_HALF_WIDTH
                        and abs(y1 - sign * x) <= _NOISE_HALF_WIDTH
                    ):
                        hits += 1
                likelihood += weight * hits / cells / (
                    (2.0 * _NOISE_HALF_WIDTH) ** 2
                )
            raw[mechanism] = prior * likelihood
        total = math.fsum(raw.values())
        if total <= 0.0:
            raise ValueError("W18 reference history has zero likelihood")
        return {
            "C0": raw.get("C0", 0.0) / total,
            "C1": raw.get("C1", 0.0) / total,
            "unknown": (raw.get("C2", 0.0) + raw.get("Cdev", 0.0)) / total,
        }

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

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        strata = ["iid_support"]
        tag = self.attribution_tag(episode)
        if tag in {"KNOWN_EXTREME", "OOD_ATTRIBUTABLE"}:
            strata.append("boundary_tail")
        if tag.startswith("OOD_") or tag.startswith("DEV_ANOMALY_"):
            strata.append("mechanism_ood")
        if bool(episode.oracle_anchor.get("fixture", False)):
            strata.append("behavior_pair")
        return tuple(strata)

    @staticmethod
    def _mechanism_for(split: WorldSplit, episode_index: int) -> tuple[str, str]:
        if split is WorldSplit.TRAIN:
            return ("C0" if episode_index % 2 == 0 else "C1"), "known"
        if split is WorldSplit.VALIDATION and episode_index % 5 == 0:
            return "Cdev", "development-anomaly"
        if split is WorldSplit.SEALED_TEST:
            strata = (
                ("C2", "attributable"),
                ("C2", "overlap"),
                ("C0", "known-extreme"),
                ("C1", "known-extreme"),
                ("C0", "known"),
                ("C0", "known"),
                ("C0", "known"),
                ("C1", "known"),
                ("C1", "known"),
                ("C1", "known"),
            )
            return strata[episode_index % len(strata)]
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
            return 0.0, False
        known_extreme = subtype == "known-extreme"
        if known_extreme:
            magnitude = 1.30 + 0.15 * uniform01(
                seed, "w18", split.value, episode_index, "extreme-magnitude"
            )
            sign = -1.0 if uniform01(
                seed, "w18", split.value, episode_index, "extreme-sign"
            ) < 0.5 else 1.0
            return sign * magnitude, True
        return 1.15 * (
            2.0 * uniform01(seed, "w18", split.value, episode_index, "x") - 1.0
        ), False

    @staticmethod
    def _action_probabilities(obs_0: float) -> tuple[float, float]:
        p_a1 = 0.15 + 0.70 * (1.0 / (1.0 + math.exp(-2.0 * obs_0)))
        return 1.0 - p_a1, p_a1

    def _diagnostic_target_from_public(
        self, split: WorldSplit, obs_0: float, obs_1: float
    ) -> dict[str, float]:
        mechanism = self._mechanism_posterior_values(split, obs_0, obs_1)
        return {
            "C0": mechanism.get("C0", 0.0),
            "C1": mechanism.get("C1", 0.0),
            "unknown": mechanism.get("C2", 0.0) + mechanism.get("Cdev", 0.0),
        }

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
        target = self._diagnostic_target_from_public(split, obs_0, obs_1)
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
        mechanism_posterior = self._mechanism_posterior_values(
            episode.split, _latest(episode, "obs_0"), _latest(episode, "obs_1")
        )
        public_components = tuple(mechanism_posterior.items())
        diagnostic = {
            "C0": mechanism_posterior.get("C0", 0.0),
            "C1": mechanism_posterior.get("C1", 0.0),
            "unknown": mechanism_posterior.get("C2", 0.0)
            + mechanism_posterior.get("Cdev", 0.0),
        }
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
                    "public_component": mechanism
                    if mechanism in {"C0", "C1"}
                    else "unknown-reference",
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

    def reference_counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        """Independent closed-form implementation for freeze certification.

        This method intentionally duplicates the probability calculation and
        affine propagation instead of calling any production-oracle helper.
        """

        del oracle_seed
        if horizon not in (1, 4, 8):
            raise ValueError("unsupported W18 horizon")
        visible: dict[str, float] = {}
        for event in episode.public_history.events:
            if (
                event.kind is EventKind.OBSERVATION_AVAILABLE
                and event.payload.get("channel_id") in {"obs_0", "obs_1"}
            ):
                visible[str(event.payload["channel_id"])] = float(
                    event.payload["value"]
                )
        y0, y1 = visible["obs_0"], visible["obs_1"]

        priors = {
            WorldSplit.TRAIN: (("C0", 0.5), ("C1", 0.5)),
            WorldSplit.VALIDATION: (("C0", 0.4), ("C1", 0.4), ("Cdev", 0.2)),
            WorldSplit.SEALED_TEST: (("C0", 0.4), ("C1", 0.4), ("C2", 0.2)),
        }[episode.split]
        prior_supports = {
            "C0": (
                ((0.75, -1.15, 1.15), (0.125, -1.45, -1.30), (0.125, 1.30, 1.45))
                if episode.split is WorldSplit.SEALED_TEST
                else ((1.0, -1.15, 1.15),)
            ),
            "C1": (
                ((0.75, -1.15, 1.15), (0.125, -1.45, -1.30), (0.125, 1.30, 1.45))
                if episode.split is WorldSplit.SEALED_TEST
                else ((1.0, -1.15, 1.15),)
            ),
            "C2": ((0.25, -1.40, -0.50), (0.50, 0.0, 0.0), (0.25, 0.50, 1.40)),
            "Cdev": ((1.0, -1.15, 1.15),),
        }
        signs = {"C0": 1.0, "C1": -1.0, "C2": 0.0, "Cdev": 0.5}
        raw: dict[str, float] = {}
        for name, prior in priors:
            likelihood = 0.0
            sign = signs[name]
            for weight, base_low, base_high in prior_supports[name]:
                if base_low == base_high:
                    if (
                        abs(y0 - base_low) <= 0.03
                        and abs(y1 - sign * base_low) <= 0.03
                    ):
                        likelihood += weight / (0.06**2)
                    continue
                lo = max(base_low, y0 - 0.03)
                hi = min(base_high, y0 + 0.03)
                if sign == 0.0:
                    if abs(y1) > 0.03:
                        continue
                else:
                    first = (y1 - 0.03) / sign
                    second = (y1 + 0.03) / sign
                    lo = max(lo, min(first, second))
                    hi = min(hi, max(first, second))
                likelihood += (
                    weight * max(0.0, hi - lo) / (base_high - base_low) / (0.06**2)
                )
            raw[name] = prior * likelihood
        normalizer = math.fsum(raw.values())
        if normalizer <= 0.0:
            raise ValueError("W18 reference history has zero likelihood")
        posterior = {name: value / normalizer for name, value in raw.items()}

        action_offsets = {
            action.offset
            for action in policy.actions
            if action.action_id == "A1" and action.offset < horizon
        } if policy.kind is PlanKind.ACTION_SEQUENCE else set()
        reference_has_q1 = False
        if policy.kind is PlanKind.ACTION_SEQUENCE:
            for planned in policy.actions:
                if planned.action_id == "Q1":
                    reference_has_q1 = True
                    break
        check_cost = 0.08 if reference_has_q1 else 0.0
        parameters = {
            "C0": (0.85, 0.10, 0.30, 1.0),
            "C1": (0.85, -0.10, -0.30, -1.0),
            "C2": (0.55, 0.35, -0.55, 0.0),
            "Cdev": (0.70, 0.18, -0.10, 0.5),
        }
        components: list[dict[str, Any]] = []
        total_utility = 0.0
        for name, weight in posterior.items():
            rho, bias, beta, sign = parameters[name]
            mean = y0
            variance = (0.03 / math.sqrt(3.0)) ** 2
            steps: list[dict[str, Any]] = []
            component_utility = 0.0
            for offset in range(horizon):
                a1 = offset in action_offsets
                mean = rho * mean + bias - beta * a1
                variance = rho * rho * variance + 0.03**2 / 3.0
                cost = mean * mean + variance + 0.08 * a1
                if offset == 0:
                    cost += check_cost
                component_utility -= 0.97**offset * cost
                steps.append(
                    {
                        "offset": offset + 1,
                        "obs_0_mean": 0.0 if mean == 0.0 else float(mean),
                        "obs_1_mean": 0.0 if sign * mean == 0.0 else float(sign * mean),
                        "latent_variance": 0.0 if variance == 0.0 else float(variance),
                    }
                )
            total_utility += weight * component_utility
            components.append(
                {
                    "public_component": name if name in {"C0", "C1"} else "unknown-reference",
                    "weight": weight,
                    "steps": steps,
                    "expected_utility": 0.0
                    if component_utility == 0.0
                    else float(component_utility),
                }
            )
        known = (raw.get("C0", 0.0) > 0.0, raw.get("C1", 0.0) > 0.0)
        diagnostic = {
            "C0": posterior.get("C0", 0.0),
            "C1": posterior.get("C1", 0.0),
            "unknown": posterior.get("C2", 0.0) + posterior.get("Cdev", 0.0),
        }
        tag = "OOD_ATTRIBUTABLE" if not any(known) else "KNOWN_SUPPORT_PRESENT"
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "bounded-noise-affine",
                "components": components,
                "precise_check_half_width": 0.01,
            },
            latent_distribution={
                "family": "bounded-noise-affine",
                "components": components,
                "known_support": {"C0": known[0], "C1": known[1]},
                "diagnostic_posterior": diagnostic,
            },
            outcome_distribution={
                "expected_utility": 0.0 if total_utility == 0.0 else float(total_utility),
                "public_ood_attribution": tag,
                "forced_ood_scored": not any(known),
                "unsafe_non_abstain_reference_only": not any(known),
            },
            expected_utility=0.0 if total_utility == 0.0 else float(total_utility),
            numerical_diagnostics={
                "method": "reference-direct-interval-affine",
                "absolute_error_bound": 0.0,
            },
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
                WorldSplit.SEALED_TEST, obs_0, obs_1
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
            diagnostic_target=unseen.diagnostic_target,
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
