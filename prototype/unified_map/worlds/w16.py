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

from ..candidate_protocol import ResultStatus
from ..canonical import ProtocolViolation, digest_json
from ..extensions import (
    OpaqueExtensionCustody,
    RevealedExtensionPack,
    make_opaque_extension_pack,
)
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
from .randomness import bernoulli, categorical, normal01
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
_INITIAL_MEAN = 0.75
_INITIAL_SD = 0.20


def _s1_catalog() -> PublicCatalog:
    return PublicCatalog(
        observations=(
            ChannelSpec("obs_0"),
            ChannelSpec(
                "obs_2",
                value_type="binary",
                unit="indicator",
                valid_range=(0, 1),
            ),
        ),
        actions=(ActionSpec("A1", cost=0.05),),
        checks=(
            CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
            CheckSpec("Q2", ("obs_2",), (1, 1), cost=0.08),
        ),
        diagnostic_labels=("C0", "C1"),
        horizons=(1, 4, 8),
    )


def make_w16_extension_custody() -> OpaqueExtensionCustody:
    """Judge-only S1 source; candidates receive only ``custody.public`` pre-seal."""

    catalog = _s1_catalog()
    pack = {
        "protocol": "ucm-world-extension-pack/1",
        "catalog": catalog.to_wire(),
        "catalog_digest": catalog.digest,
        "operator": {
            "check_id": "Q2",
            "result_channel": "obs_2",
            "p_result_1_given_C0": 0.05,
            "p_result_1_given_C1": 0.95,
            "delay_ticks": 1,
            "cost": 0.08,
        },
        "frozen_corpus": {"episodes": 512, "branch_pairs": 256},
        "plaintext_guard": "CHECK-EXTENSION-POST-SEAL-ONLY",
    }
    return make_opaque_extension_pack(
        "W16",
        pack,
        hiding_markers=(b"obs_2", b"p_result_1_given_C1", b"CHECK-EXTENSION-POST-SEAL-ONLY"),
    )


def _action_schedule(policy: ActionPlan, horizon: int, action_id: str = "A1") -> list[bool]:
    schedule = [False] * horizon
    if policy.kind is PlanKind.ACTION_SEQUENCE:
        for action in policy.actions:
            if action.offset < horizon and action.action_id == action_id:
                schedule[action.offset] = True
    return schedule


class W16World(MicroWorld):
    """Executable two-stage check-extension benchmark."""

    def __init__(
        self,
        *,
        extension_commitment: str | None = None,
        extension_reveal: RevealedExtensionPack | None = None,
    ) -> None:
        self._extension_commitment = extension_commitment
        self._extension_reveal = extension_reveal
        if extension_reveal is not None:
            if extension_reveal.world_id != "W16":
                raise ProtocolViolation("W16 received a reveal for another world")
            if extension_commitment != extension_reveal.commitment:
                raise ProtocolViolation("W16 reveal/commitment mismatch")
            expected = _s1_catalog()
            pack = extension_reveal.pack
            if (
                pack.get("protocol") != "ucm-world-extension-pack/1"
                or pack.get("catalog") != expected.to_wire()
                or pack.get("catalog_digest") != expected.digest
            ):
                raise ProtocolViolation("W16 revealed extension pack is not the frozen S1 contract")

    def activate_extension(self, reveal: RevealedExtensionPack) -> "W16World":
        """Return an S1 view only after the runner has opened the commitment."""

        return type(self)(
            extension_commitment=reveal.commitment,
            extension_reveal=reveal,
        )

    def _require_extension(self) -> RevealedExtensionPack:
        if self._extension_reveal is None:
            raise ProtocolViolation("W16 extension source is unavailable before reveal")
        return self._extension_reveal

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

        self._require_extension()
        return _s1_catalog()

    @property
    def extension_commitment(self) -> str | None:
        """Randomized hiding commitment; it contains no S1 source digest alone."""

        return self._extension_commitment

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W16 horizon")
        return _standard_policy_set(horizon, treatments=("A1",), checks=())

    def extension_policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        self._require_extension()
        if horizon not in self.extension_catalog.horizons:
            raise ValueError("unsupported W16 extension horizon")
        policies = list(_standard_policy_set(horizon, treatments=("A1",), checks=("Q2",)))
        # A fixed, public decision rule.  Q2 is ordered at offset 0; its result
        # is available at offset 1, and only then may the A1 branch execute.
        policies.append(
            ActionPlan(
                PlanKind.ACTION_SEQUENCE,
                (
                    PlannedAction(
                        0,
                        "Q2",
                        {
                            "result_available_offset": 1,
                            "on_result_0": "NoNewAction",
                            "on_result_1": "A1",
                        },
                    ),
                ),
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
        x = _INITIAL_MEAN + _INITIAL_SD * normal01(
            seed, "w16", split.value, episode_index, "initial-x"
        )
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

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        """Exact, public-history-replayable W16 stratum classifier.

        Every primary row is an eligible old-state extension row.  Boundary
        membership is defined by an actually visible extreme observation, not
        an episode index/private label.  Once the revealed S1 catalog is bound,
        every row also admits the frozen opposite-private/result pair probes.
        """

        observed = [
            float(event.payload["value"])
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_0"
        ]
        strata = ["iid_support"]
        if any(value <= 0.0 or value >= 1.25 for value in observed):
            strata.append("boundary_tail")
        strata.append("extension_check")
        if (
            self._extension_reveal is not None
            and episode.public_history.catalog_digest == self.extension_catalog.digest
        ):
            strata.append("behavior_pair")
        return tuple(strata)

    def extension_delta(
        self,
        result: int,
        *,
        seed: int,
        episode_index: int,
        ordered_at: int = -1,
        available_at: int = 0,
    ) -> VisibleDelta:
        self._require_extension()
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
    ) -> PrivateEpisode:
        """Generate the genuine S1 corpus with randomized Q2 ordering.

        The 0.5 assignment is independent of the private class.  A result is
        present only in the ordered arm and follows the revealed operator.
        """

        self._require_extension()
        base = self._base_episode(split, generator_seed, episode_index)
        class_index = int(base.invariant_parameters["class_index"])
        events = list(base.public_history.events)
        result: int | None = None
        ordered = bool(
            bernoulli(
                0.5,
                generator_seed,
                "w16",
                split.value,
                episode_index,
                "s1-q2-assignment",
            )
        )
        if ordered:
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
            action_propensities=[
                *base.action_propensities,
                {
                    "decision_at": -1,
                    "probabilities": {"NoNewCheck": 0.5, "Q2": 0.5},
                    "selected": "Q2" if ordered else "NoNewCheck",
                },
            ],
            factual_utility=_json_float(
                base.factual_utility - (0.08 if ordered else 0.0)
            ),
            oracle_anchor={
                "semantic_stage": "S1",
                "extension_commitment": self.extension_commitment,
                "randomized_q2_arm": "Q2" if ordered else "NoNewCheck",
                "q2_result": result,
                "public_posterior": {"C0": 1.0 - posterior_c1, "C1": posterior_c1},
            },
        )

    def generate_extension_corpus(
        self,
        split: WorldSplit,
        generator_seed: int,
        *,
        size: int = 512,
    ) -> tuple[PrivateEpisode, ...]:
        self._require_extension()
        if type(size) is not int or size <= 0:
            raise ValueError("extension corpus size must be positive")
        return tuple(
            self.generate_extension_episode(split, generator_seed, index)
            for index in range(size)
        )

    @staticmethod
    def legacy_extension_verdict(status: ResultStatus) -> str:
        """Compatibility label only; correctness is judge-scored, never a caller bool."""

        if type(status) is not ResultStatus:
            raise ProtocolViolation("W16 extension status must use ResultStatus")
        if status is ResultStatus.SCOPE_INSUFFICIENT:
            return "HONEST_LIMIT"
        if status is ResultStatus.OK:
            return "UNSCORED_OK"
        return "HARD_FAILURE"

    def _posterior_c1(self, episode: PrivateEpisode) -> float:
        probability = 0.5
        results = [
            int(event.payload["value"])
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_2"
        ]
        for result in results:
            likelihood_c1 = 0.95 if result == 1 else 0.05
            likelihood_c0 = 0.05 if result == 1 else 0.95
            numerator = probability * likelihood_c1
            probability = numerator / (
                numerator + (1.0 - probability) * likelihood_c0
            )
        return probability

    def public_history_posterior(
        self, episode: PrivateEpisode
    ) -> tuple[float, float, float]:
        """Production Kalman/Bayes filter using candidate-visible history only."""

        mean = _INITIAL_MEAN
        variance = _INITIAL_SD**2
        observations: dict[int, list[float]] = {}
        treated_at: set[int] = set()
        for event in episode.public_history.events:
            if (
                event.kind is EventKind.OBSERVATION_AVAILABLE
                and event.payload.get("channel_id") == "obs_0"
            ):
                observations.setdefault(event.occurred_at, []).append(
                    float(event.payload["value"])
                )
            elif (
                event.kind is EventKind.PERFORMED_TREATMENT
                and event.payload.get("action_id") == "A1"
            ):
                treated_at.add(event.occurred_at)
        for tick in range(-4, 1):
            for observed in observations.get(tick, []):
                gain = variance / (variance + _OBS_SD**2)
                mean = mean + gain * (observed - mean)
                variance = (1.0 - gain) * variance
            if tick < 0:
                mean = (
                    _RHO * mean
                    + _BIAS
                    + (_A1_EFFECT if tick in treated_at else 0.0)
                )
                variance = _RHO**2 * variance + _PROCESS_SD**2
        return mean, variance, self._posterior_c1(episode)

    def reference_public_history_posterior(
        self, episode: PrivateEpisode
    ) -> tuple[float, float, float]:
        """Source-distinct information filter/reference Bayes implementation."""

        precision = 1.0 / (_INITIAL_SD**2)
        information = _INITIAL_MEAN * precision
        by_tick: dict[int, tuple[float, ...]] = {}
        actions: dict[int, float] = {}
        for tick in range(-4, 1):
            by_tick[tick] = tuple(
                float(event.payload["value"])
                for event in episode.public_history.events
                if event.kind is EventKind.OBSERVATION_AVAILABLE
                and event.payload.get("channel_id") == "obs_0"
                and event.occurred_at == tick
            )
            actions[tick] = (
                _A1_EFFECT
                if any(
                    event.kind is EventKind.PERFORMED_TREATMENT
                    and event.payload.get("action_id") == "A1"
                    and event.occurred_at == tick
                    for event in episode.public_history.events
                )
                else 0.0
            )
        measurement_precision = 1.0 / (_OBS_SD**2)
        for tick in range(-4, 1):
            for observed in by_tick[tick]:
                precision += measurement_precision
                information += observed * measurement_precision
            posterior_mean = information / precision
            posterior_variance = 1.0 / precision
            if tick < 0:
                predicted_mean = _RHO * posterior_mean + _BIAS + actions[tick]
                predicted_variance = (
                    _RHO * _RHO * posterior_variance + _PROCESS_SD * _PROCESS_SD
                )
                precision = 1.0 / predicted_variance
                information = predicted_mean * precision

        odds = 1.0
        for event in episode.public_history.events:
            if (
                event.kind is EventKind.OBSERVATION_AVAILABLE
                and event.payload.get("channel_id") == "obs_2"
            ):
                value = int(event.payload["value"])
                odds *= 19.0 if value == 1 else (1.0 / 19.0)
        p_c1 = odds / (1.0 + odds)
        return information / precision, 1.0 / precision, p_c1

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
        is_extension = (
            self._extension_reveal is not None
            and episode.public_history.catalog_digest == self.extension_catalog.digest
        )
        allowed = {"A1", "Q2"} if is_extension else {"A1"}
        if policy.kind is PlanKind.ACTION_SEQUENCE and any(
            action.action_id not in allowed for action in policy.actions
        ):
            raise ValueError("policy is outside the episode semantic scope")
        mean, variance, posterior_c1 = self.public_history_posterior(episode)
        adaptive = next(
            (
                action
                for action in policy.actions
                if action.action_id == "Q2"
                and action.parameters.get("result_available_offset") == 1
            ),
            None,
        )
        if adaptive is not None:
            if not is_extension:
                raise ValueError("adaptive Q2 policy is outside S0 scope")
            predictive_one = 0.05 * (1.0 - posterior_c1) + 0.95 * posterior_c1
            branches: list[dict[str, Any]] = []
            total_utility = 0.0
            for result, weight in ((0, 1.0 - predictive_one), (1, predictive_one)):
                branch_mean = mean
                branch_variance = variance
                steps: list[dict[str, Any]] = []
                utility = 0.0
                for offset in range(horizon):
                    acts = result == 1 and offset == 1
                    branch_mean = (
                        _RHO * branch_mean
                        + _BIAS
                        + (_A1_EFFECT if acts else 0.0)
                    )
                    branch_variance = (
                        _RHO**2 * branch_variance + _PROCESS_SD**2
                    )
                    cost = branch_mean**2 + branch_variance + 0.05 * acts
                    if offset == 0:
                        cost += 0.08
                    utility -= 0.97**offset * cost
                    steps.append(
                        {
                            "offset": offset + 1,
                            "action": "A1" if acts else "NoNewAction",
                            "mean": _json_float(branch_mean),
                            "variance": _json_float(branch_variance),
                        }
                    )
                likelihood_c1 = 0.95 if result else 0.05
                numerator = posterior_c1 * likelihood_c1
                posterior_after = numerator / max(weight, 1e-15)
                branches.append(
                    {
                        "q2_result": result,
                        "weight": _json_float(weight),
                        "result_available_offset": 1,
                        "diagnostic_posterior": {
                            "C0": _json_float(1.0 - posterior_after),
                            "C1": _json_float(posterior_after),
                        },
                        "steps": steps,
                        "expected_utility": _json_float(utility),
                    }
                )
                total_utility += weight * utility
            return CounterfactualOracle(
                policy=policy,
                horizon=horizon,
                observation_distribution={
                    "family": "adaptive-q2-linear-gaussian-mixture",
                    "q2_predictive_probability": _json_float(predictive_one),
                    "branches": branches,
                },
                latent_distribution={
                    "family": "adaptive-q2-posterior-mixture",
                    "cut_posterior": {
                        "x_mean": _json_float(mean),
                        "x_variance": _json_float(variance),
                        "C1": _json_float(posterior_c1),
                    },
                    "branches": branches,
                },
                outcome_distribution={
                    "expected_utility": _json_float(total_utility),
                    "scope": "S1",
                    "adaptive_action_occurs_only_after_available": True,
                },
                expected_utility=_json_float(total_utility),
                numerical_diagnostics={
                    "method": "production-kalman-result-mixture",
                    "absolute_error_bound": 0.0,
                },
            )

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
            numerical_diagnostics={"method": "production-kalman-linear-gaussian", "absolute_error_bound": 0.0},
        )

    def reference_counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        """Independent information-filter/enumeration oracle for audit."""

        del oracle_seed
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W16 horizon")
        extension = (
            self._extension_reveal is not None
            and episode.public_history.catalog_digest == self.extension_catalog.digest
        )
        permitted = {"A1", "Q2"} if extension else {"A1"}
        if policy.kind is PlanKind.ACTION_SEQUENCE and any(
            item.action_id not in permitted for item in policy.actions
        ):
            raise ValueError("policy is outside the episode semantic scope")
        m0, v0, pc1 = self.reference_public_history_posterior(episode)
        conditional = any(
            item.action_id == "Q2"
            and item.parameters.get("result_available_offset") == 1
            for item in policy.actions
        )
        if conditional:
            joint = []
            for klass, class_weight in ((0, 1.0 - pc1), (1, pc1)):
                for result in (0, 1):
                    probability_one = 0.95 if klass == 1 else 0.05
                    result_weight = probability_one if result else 1.0 - probability_one
                    joint.append((result, class_weight * result_weight, klass))
            branch_rows = []
            total = 0.0
            for result in (0, 1):
                selected = [(weight, klass) for value, weight, klass in joint if value == result]
                weight = sum(item[0] for item in selected)
                conditional_c1 = sum(w for w, klass in selected if klass == 1) / weight
                location, spread, utility = m0, v0, 0.0
                steps = []
                for offset in range(horizon):
                    action_a1 = result == 1 and offset == 1
                    location = _RHO * location + _BIAS + (
                        _A1_EFFECT if action_a1 else 0.0
                    )
                    spread = _RHO * _RHO * spread + _PROCESS_SD * _PROCESS_SD
                    loss = location * location + spread + 0.05 * action_a1
                    if offset == 0:
                        loss += 0.08
                    utility -= (0.97**offset) * loss
                    steps.append(
                        {
                            "offset": offset + 1,
                            "action": "A1" if action_a1 else "NoNewAction",
                            "mean": _json_float(location),
                            "variance": _json_float(spread),
                        }
                    )
                total += weight * utility
                branch_rows.append(
                    {
                        "q2_result": result,
                        "weight": _json_float(weight),
                        "result_available_offset": 1,
                        "diagnostic_posterior": {
                            "C0": _json_float(1.0 - conditional_c1),
                            "C1": _json_float(conditional_c1),
                        },
                        "steps": steps,
                        "expected_utility": _json_float(utility),
                    }
                )
            return CounterfactualOracle(
                policy,
                horizon,
                {
                    "family": "adaptive-q2-linear-gaussian-mixture",
                    "q2_predictive_probability": _json_float(branch_rows[1]["weight"]),
                    "branches": branch_rows,
                },
                {
                    "family": "adaptive-q2-posterior-mixture",
                    "cut_posterior": {
                        "x_mean": _json_float(m0),
                        "x_variance": _json_float(v0),
                        "C1": _json_float(pc1),
                    },
                    "branches": branch_rows,
                },
                {
                    "expected_utility": _json_float(total),
                    "scope": "S1",
                    "adaptive_action_occurs_only_after_available": True,
                },
                _json_float(total),
                {"method": "reference-information-filter-joint-enumeration", "absolute_error_bound": 1e-12},
            )

        actions = [False for _ in range(horizon)]
        if policy.kind is PlanKind.ACTION_SEQUENCE:
            for item in policy.actions:
                if item.action_id == "A1" and item.offset < horizon:
                    actions[item.offset] = True
        q2 = any(item.action_id == "Q2" for item in policy.actions)
        location, spread, utility = m0, v0, 0.0
        steps = []
        for offset in range(horizon):
            action_a1 = actions[offset]
            location = _RHO * location + _BIAS + (_A1_EFFECT if action_a1 else 0.0)
            spread = _RHO * _RHO * spread + _PROCESS_SD * _PROCESS_SD
            loss = location * location + spread + 0.05 * action_a1
            if q2 and offset == 0:
                loss += 0.08
            utility -= (0.97**offset) * loss
            steps.append({"offset": offset + 1, "mean": _json_float(location), "variance": _json_float(spread)})
        diagnostics = {"C0": 1.0 - pc1, "C1": pc1} if extension else {"E0": 1.0}
        return CounterfactualOracle(
            policy,
            horizon,
            {"family": "linear-gaussian-plus-binary-readout", "steps": steps, "q2_predictive_probability": (0.05 + 0.90 * pc1) if extension else None},
            {"family": "linear-gaussian", "steps": steps, "diagnostic_posterior": diagnostics},
            {"expected_utility": _json_float(utility), "scope": "S1" if extension else "S0"},
            _json_float(utility),
            {"method": "reference-information-filter", "absolute_error_bound": 1e-12},
        )

    def pre_result_alias_pair(self, seed: int = 1601) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Private C0/C1 swap with exact candidate bytes before Q2 is available."""

        self._require_extension()
        base = self._base_episode(WorldSplit.SEALED_TEST, seed, 0)
        first = replace(
            base,
            public_history=type(base.public_history)(
                events=base.public_history.events,
                as_of_available_at=base.public_history.as_of_available_at,
                catalog_digest=self.extension_catalog.digest,
            ),
            invariant_parameters={"stage": "S1", "class_index": 0},
            diagnostic_target={"C0": 1.0, "C1": 0.0},
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

        self._require_extension()
        raw = self._base_episode(WorldSplit.SEALED_TEST, seed, 2)
        base = replace(
            raw,
            public_history=type(raw.public_history)(
                events=raw.public_history.events,
                as_of_available_at=raw.public_history.as_of_available_at,
                catalog_digest=self.extension_catalog.digest,
            ),
            invariant_parameters={"stage": "S1", "class_index": 0},
            diagnostic_target={"C0": 1.0, "C1": 0.0},
        )
        episodes = []
        for result in (0, 1):
            events = list(base.public_history.events)
            events.extend(
                self.extension_delta(result, seed=seed, episode_index=2).events
            )
            episodes.append(
                replace(
                    base,
                    case_key=digest_json(
                        {"pair": "w16-result", "seed": seed, "result": result}
                    ),
                    public_history=_visible_history(events, self.extension_catalog),
                    diagnostic_target={"C0": 1.0, "C1": 0.0},
                    oracle_anchor={
                        "fixture": "extension-result-pair",
                        "q2_result": result,
                    },
                )
            )
        return episodes[0], episodes[1]


World = W16World

__all__ = ["W16World", "World", "make_w16_extension_custody"]
