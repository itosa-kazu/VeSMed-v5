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

from ..candidate_protocol import ResultStatus
from ..canonical import ProtocolViolation, digest_json
from ..extensions import (
    OpaqueExtensionCustody,
    RevealedExtensionPack,
    make_opaque_extension_pack,
)
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
from .randomness import bernoulli, categorical, normal01
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
_INITIAL_MEAN = 0.75
_INITIAL_SD = 0.20


def _s1_catalog() -> PublicCatalog:
    return PublicCatalog(
        observations=(
            ChannelSpec("obs_0"),
            ChannelSpec(
                "obs_1",
                value_type="binary",
                unit="indicator",
                valid_range=(0, 1),
            ),
        ),
        actions=(ActionSpec("A1", cost=0.05), ActionSpec("A2", cost=0.08)),
        checks=(CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),),
        diagnostic_labels=("E0",),
        horizons=(1, 4, 8),
    )


def make_w17_extension_custody() -> OpaqueExtensionCustody:
    catalog = _s1_catalog()
    pack = {
        "protocol": "ucm-world-extension-pack/1",
        "catalog": catalog.to_wire(),
        "catalog_digest": catalog.digest,
        "operator": {
            "action_id": "A2",
            "effect_C0": -0.55,
            "effect_C1": 0.55,
            "cost": 0.08,
        },
        "randomized_validation_arm": {
            "actions": ["NoNewAction", "A2"],
            "probabilities": [0.5, 0.5],
        },
        "frozen_corpus": {"episodes": 512, "old_state_pairs": 256},
        "plaintext_guard": "TREATMENT-EXTENSION-POST-SEAL-ONLY",
    }
    return make_opaque_extension_pack(
        "W17",
        pack,
        hiding_markers=(b'"A2"', b"effect_C1", b"TREATMENT-EXTENSION-POST-SEAL-ONLY"),
    )


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
    def __init__(
        self,
        *,
        extension_commitment: str | None = None,
        extension_reveal: RevealedExtensionPack | None = None,
    ) -> None:
        self._extension_commitment = extension_commitment
        self._extension_reveal = extension_reveal
        if extension_reveal is not None:
            if (
                extension_reveal.world_id != "W17"
                or extension_reveal.commitment != extension_commitment
            ):
                raise ProtocolViolation("W17 reveal/commitment mismatch")
            expected = _s1_catalog()
            pack = extension_reveal.pack
            if (
                pack.get("protocol") != "ucm-world-extension-pack/1"
                or pack.get("catalog") != expected.to_wire()
                or pack.get("catalog_digest") != expected.digest
            ):
                raise ProtocolViolation("W17 revealed extension pack is not frozen S1")

    def activate_extension(self, reveal: RevealedExtensionPack) -> "W17World":
        return type(self)(
            extension_commitment=reveal.commitment,
            extension_reveal=reveal,
        )

    def _require_extension(self) -> RevealedExtensionPack:
        if self._extension_reveal is None:
            raise ProtocolViolation("W17 extension source is unavailable before reveal")
        return self._extension_reveal

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
        self._require_extension()
        return _s1_catalog()

    @property
    def extension_commitment(self) -> str | None:
        return self._extension_commitment

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W17 horizon")
        return _standard_policy_set(horizon, treatments=("A1",), checks=())

    def extension_policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        self._require_extension()
        if horizon not in self.extension_catalog.horizons:
            raise ValueError("unsupported W17 extension horizon")
        return _standard_policy_set(horizon, treatments=("A1", "A2"), checks=())

    @staticmethod
    def _behavior_probabilities(y: float) -> tuple[float, float]:
        return _exploratory_probabilities(_softmax((0.3, 0.8 * y)))

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        c = episode_index % 2
        x = _INITIAL_MEAN + _INITIAL_SD * normal01(
            generator_seed, "w17", split.value, episode_index, "initial-x"
        )
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

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        """Classify only from candidate-visible timing/catalog/observations."""

        obs0 = [
            float(event.payload["value"])
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_0"
        ]
        obs1 = [
            event
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_1"
        ]
        strata = ["iid_support"]
        if any(value <= 0.0 or value >= 1.25 for value in obs0):
            strata.append("boundary_tail")
        # Every S0 row carries the neutral public context whose retained/lost
        # information is challenged by the post-seal A2 operator.
        strata.append("extension_treatment")
        # The frozen pair fixture has one context and one matched current-Q0
        # observation.  This is replayable from public bytes; no fixture tag,
        # class, episode index, or oracle anchor is consulted.
        if len(obs0) == 1 and len(obs1) == 1:
            strata.append("behavior_pair")
        return tuple(strata)

    def as_extension_episode(self, episode: PrivateEpisode) -> PrivateEpisode:
        """Rebind public bytes to the revealed catalog without replaying them."""

        self._require_extension()
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

    def generate_extension_episode(
        self,
        split: WorldSplit,
        generator_seed: int,
        episode_index: int,
    ) -> PrivateEpisode:
        """Independent S1 validation row with a genuine randomized A2 arm."""

        self._require_extension()
        base = self.as_extension_episode(
            self.generate_episode(split, generator_seed, episode_index)
        )
        klass = int(base.invariant_parameters["class_index"])
        assigned_a2 = bool(
            bernoulli(
                0.5,
                generator_seed,
                "w17",
                split.value,
                episode_index,
                "s1-a2-randomized-assignment",
            )
        )
        x = float(base.hidden_state_at_cut["x"])
        future: list[dict[str, Any]] = []
        utility = 0.0
        for offset in range(4):
            action = "A2" if assigned_a2 and offset == 0 else "NoNewAction"
            g = 1.0 if klass == 0 else -1.0
            x = (
                _RHO * x
                + _BIAS
                + (-_A2_MAGNITUDE * g if action == "A2" else 0.0)
                + _PROCESS_SD
                * normal01(
                    generator_seed,
                    "w17",
                    split.value,
                    episode_index,
                    "s1-randomized-future",
                    offset,
                )
            )
            utility -= 0.97**offset * (
                x * x + (0.08 if action == "A2" else 0.0)
            )
            future.append(
                {
                    "offset": offset + 1,
                    "observations": {"obs_0": _json_float(x)},
                    "performed_action": action,
                }
            )
        return replace(
            base,
            factual_future=future,
            factual_utility=_json_float(utility),
            action_propensities=[
                *base.action_propensities,
                {
                    "decision_at": 0,
                    "probabilities": {"NoNewAction": 0.5, "A2": 0.5},
                    "selected": "A2" if assigned_a2 else "NoNewAction",
                    "randomized": True,
                },
            ],
            oracle_anchor={
                **base.oracle_anchor,
                "randomized_s1_arm": "A2" if assigned_a2 else "NoNewAction",
                "assignment_probability": 0.5,
            },
        )

    def generate_extension_corpus(
        self,
        split: WorldSplit,
        generator_seed: int,
        *,
        size: int = 512,
    ) -> tuple[PrivateEpisode, ...]:
        if type(size) is not int or size <= 0:
            raise ValueError("extension corpus size must be positive")
        return tuple(
            self.generate_extension_episode(split, generator_seed, index)
            for index in range(size)
        )

    @staticmethod
    def legacy_extension_verdict(status: ResultStatus) -> str:
        """Compatibility label; the runner, not a caller bool, scores accuracy."""

        if type(status) is not ResultStatus:
            raise ProtocolViolation("W17 extension status must use ResultStatus")
        if status is ResultStatus.SCOPE_INSUFFICIENT:
            return "HONEST_LIMIT"
        if status is ResultStatus.OK:
            return "UNSCORED_OK"
        return "HARD_FAILURE"

    def _public_class_posterior(self, episode: PrivateEpisode) -> float:
        marker = _latest(episode, "obs_1")
        if marker is None:
            return 0.5
        likelihood_c1 = 0.05 if int(marker) == 1 else 0.95
        likelihood_c0 = 0.95 if int(marker) == 1 else 0.05
        return likelihood_c1 / (likelihood_c1 + likelihood_c0)

    def public_history_posterior(
        self, episode: PrivateEpisode
    ) -> tuple[float, float, float]:
        """Candidate-view Kalman filter plus Bayes marker posterior."""

        mean, variance = _INITIAL_MEAN, _INITIAL_SD**2
        for tick in range(-4, 1):
            for event in episode.public_history.events:
                if (
                    event.kind is EventKind.OBSERVATION_AVAILABLE
                    and event.payload.get("channel_id") == "obs_0"
                    and event.occurred_at == tick
                ):
                    observed = float(event.payload["value"])
                    gain = variance / (variance + _OBS_SD**2)
                    mean += gain * (observed - mean)
                    variance *= 1.0 - gain
            if tick < 0:
                treated = any(
                    event.kind is EventKind.PERFORMED_TREATMENT
                    and event.payload.get("action_id") == "A1"
                    and event.occurred_at == tick
                    for event in episode.public_history.events
                )
                mean = _RHO * mean + _BIAS + (_A1_EFFECT if treated else 0.0)
                variance = _RHO**2 * variance + _PROCESS_SD**2
        return mean, variance, self._public_class_posterior(episode)

    def reference_public_history_posterior(
        self, episode: PrivateEpisode
    ) -> tuple[float, float, float]:
        """Source-distinct information-form reference calculation."""

        precision = 1.0 / (_INITIAL_SD * _INITIAL_SD)
        information = _INITIAL_MEAN * precision
        obs_precision = 1.0 / (_OBS_SD * _OBS_SD)
        for tick in range(-4, 1):
            values = tuple(
                float(event.payload["value"])
                for event in episode.public_history.events
                if event.kind is EventKind.OBSERVATION_AVAILABLE
                and event.payload.get("channel_id") == "obs_0"
                and event.occurred_at == tick
            )
            for value in values:
                precision += obs_precision
                information += value * obs_precision
            if tick < 0:
                mu = information / precision
                var = 1.0 / precision
                has_a1 = sum(
                    1
                    for event in episode.public_history.events
                    if event.kind is EventKind.PERFORMED_TREATMENT
                    and event.payload.get("action_id") == "A1"
                    and event.occurred_at == tick
                )
                mu = _RHO * mu + _BIAS + (_A1_EFFECT if has_a1 else 0.0)
                var = _RHO * _RHO * var + _PROCESS_SD * _PROCESS_SD
                precision, information = 1.0 / var, mu / var
        marker = _latest(episode, "obs_1")
        if marker is None:
            odds = 1.0
        else:
            odds = (1.0 / 19.0) if int(marker) == 1 else 19.0
        return information / precision, 1.0 / precision, odds / (1.0 + odds)

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
        extension = (
            self._extension_reveal is not None
            and episode.public_history.catalog_digest == self.extension_catalog.digest
        )
        allowed = {"A1", "A2"} if extension else {"A1"}
        if policy.kind is PlanKind.ACTION_SEQUENCE and any(
            action.action_id not in allowed for action in policy.actions
        ):
            raise ValueError("policy is outside the episode semantic scope")
        posterior_mean, posterior_variance, marker_posterior = (
            self.public_history_posterior(episode)
        )
        p_c1 = marker_posterior if extension else 0.5
        components = []
        total_utility = 0.0
        schedule = _schedule(policy, horizon)
        for c, weight in ((0, 1.0 - p_c1), (1, p_c1)):
            mean = posterior_mean
            variance = posterior_variance
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
            numerical_diagnostics={"method": "production-kalman-finite-mixture", "absolute_error_bound": 0.0},
        )

    def reference_counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        """Independent information-filter and explicit class enumeration."""

        del oracle_seed
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W17 horizon")
        extension = (
            self._extension_reveal is not None
            and episode.public_history.catalog_digest == self.extension_catalog.digest
        )
        allowed = {"A1", "A2"} if extension else {"A1"}
        if policy.kind is PlanKind.ACTION_SEQUENCE and any(
            action.action_id not in allowed for action in policy.actions
        ):
            raise ValueError("policy is outside the episode semantic scope")
        initial_mean, initial_variance, marker_c1 = (
            self.reference_public_history_posterior(episode)
        )
        p_c1 = marker_c1 if extension else 0.5
        actions = ["NoNewAction" for _ in range(horizon)]
        if policy.kind is PlanKind.ACTION_SEQUENCE:
            for item in policy.actions:
                if item.offset < horizon and item.action_id in {"A1", "A2"}:
                    actions[item.offset] = item.action_id
        rows: list[dict[str, Any]] = []
        weighted_utility = 0.0
        for klass in (0, 1):
            weight = p_c1 if klass == 1 else 1.0 - p_c1
            location, spread, utility = initial_mean, initial_variance, 0.0
            steps: list[dict[str, Any]] = []
            sign = 1.0 if klass == 0 else -1.0
            for offset in range(horizon):
                action = actions[offset]
                shift = 0.0
                if action == "A1":
                    shift = _A1_EFFECT
                elif action == "A2":
                    shift = -_A2_MAGNITUDE * sign
                location = _RHO * location + _BIAS + shift
                spread = _RHO * _RHO * spread + _PROCESS_SD * _PROCESS_SD
                loss = location * location + spread
                if action == "A1":
                    loss += 0.05
                elif action == "A2":
                    loss += 0.08
                utility -= (0.97**offset) * loss
                steps.append(
                    {
                        "offset": offset + 1,
                        "mean": _json_float(location),
                        "variance": _json_float(spread),
                    }
                )
            weighted_utility += weight * utility
            rows.append(
                {
                    "class": f"C{klass}",
                    "weight": _json_float(weight),
                    "steps": steps,
                    "expected_utility": _json_float(utility),
                }
            )
        return CounterfactualOracle(
            policy,
            horizon,
            {"family": "two-component-linear-gaussian", "components": rows},
            {
                "family": "two-component-linear-gaussian",
                "class_posterior": {"C0": 1.0 - p_c1, "C1": p_c1},
                "components": rows,
            },
            {
                "expected_utility": _json_float(weighted_utility),
                "scope": "S1" if extension else "S0",
            },
            _json_float(weighted_utility),
            {
                "method": "reference-information-filter-class-enumeration",
                "absolute_error_bound": 1e-12,
            },
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

__all__ = ["W17World", "World", "make_w17_extension_custody"]
