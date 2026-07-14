"""W15: hidden confounding, with identifiable and nonidentified panels.

``World15A`` contains a public 30% randomized anchor and therefore has an
identifiable treatment effect.  ``World15B`` is an observational twin pair:
two private SCMs induce byte-identical public data but opposite do-effects.
The W15B oracle consequently returns the public-evidence mixture/identified
set and never scores a candidate against the realized private SCM identity.
"""

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
from .randomness import bernoulli, normal01, uniform01
from .w06 import (
    _alpha_rename,
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


def _sigmoid(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1.0 / (1.0 + inverse)
    direct = math.exp(value)
    return direct / (1.0 + direct)


class World15A(MicroWorld):
    """Severity-confounded behavior with a public randomized anchor."""

    def __init__(self) -> None:
        self._catalog = PublicCatalog(
            observations=(
                ChannelSpec("obs_0"),
                ChannelSpec("obs_1"),
                ChannelSpec("obs_2", value_type="binary", unit="indicator", valid_range=(0, 1)),
            ),
            actions=(ActionSpec("A1", cost=0.05),),
            checks=(
                CheckSpec("Q0", ("obs_0", "obs_2"), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.06),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    @property
    def environment_key(self) -> str:
        return "ucm-benchmark-private-w15a-v1"

    @property
    def catalog(self) -> PublicCatalog:
        return self._catalog

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ProtocolViolation("unsupported horizon")
        return _finite_policy_set(horizon, treatments=("A1",), checks=("Q1",))

    @staticmethod
    def _step(
        severity: float, confounder: int, treated: bool, noise: float = 0.0
    ) -> float:
        return max(
            0.0,
            0.92 * severity + 0.20 * confounder - 0.35 * treated + noise,
        )

    @staticmethod
    def _randomized_slot(episode_index: int, tick: int) -> bool:
        # Across every ten consecutive episode indices, each fixed decision
        # tick has exactly three randomized anchors.
        return (episode_index + (tick + 3) * 3) % 10 < 3

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        _validate_episode_request(split, generator_seed, episode_index)
        key: tuple[str | int, ...] = ("w15a", split.value, episode_index)
        confounder = int(
            bernoulli(0.5, generator_seed, *key, "confounder")
        )
        severity = 0.25 + 1.05 * uniform01(generator_seed, *key, "severity")
        events: list[Any] = []
        propensities: list[dict[str, Any]] = []

        for tick in range(-3, 1):
            y = severity + 0.05 * normal01(generator_seed, *key, "q0", tick)
            events.append(_observation(generator_seed, key, "obs_0", y, tick))
            if tick == 0:
                break
            randomized = self._randomized_slot(episode_index, tick)
            events.append(
                _observation(
                    generator_seed,
                    key,
                    "obs_2",
                    float(randomized),
                    tick,
                    slot=1,
                )
            )
            p_treat = 0.5 if randomized else _sigmoid(1.5 * y)
            treated = bernoulli(
                p_treat, generator_seed, *key, "behavior-treatment", tick
            )
            take_q1 = bernoulli(
                0.30, generator_seed, *key, "confounder-check", tick
            )
            if take_q1:
                events.append(
                    _observation(
                        generator_seed,
                        key,
                        "obs_1",
                        confounder
                        + 0.06 * normal01(generator_seed, *key, "q1", tick),
                        tick,
                        delay=1,
                    )
                )
            propensities.append(
                {
                    "decision_at": tick,
                    "assignment": "randomized" if randomized else "behavioral",
                    "probabilities": {"A1": p_treat, "NoNewAction": 1.0 - p_treat},
                    "selected": "A1" if treated else "NoNewAction",
                    "check_probabilities": {"Q1": 0.30, "NoCheck": 0.70},
                }
            )
            if treated:
                events.append(_treatment(generator_seed, key, "A1", tick))
            severity = self._step(
                severity,
                confounder,
                treated,
                0.04 * normal01(generator_seed, *key, "process", tick),
            )

        state_at_cut = severity
        severity_class = int(severity >= 0.80)
        future: list[dict[str, Any]] = []
        utility = 0.0
        for offset in range(4):
            p_treat = _sigmoid(1.5 * severity)
            treated = bernoulli(
                p_treat, generator_seed, *key, "future-treatment", offset
            )
            severity = self._step(
                severity,
                confounder,
                treated,
                0.04 * normal01(generator_seed, *key, "future-process", offset),
            )
            utility -= 0.97**offset * (severity * severity + 0.05 * treated)
            future.append(
                {
                    "offset": offset + 1,
                    "observations": {"obs_0": severity},
                    "performed_action": "A1" if treated else "NoNewAction",
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
            hidden_state_at_cut={"severity": state_at_cut},
            invariant_parameters={"confounder": confounder},
            diagnostic_target={
                "C0": float(severity_class == 0),
                "C1": float(severity_class == 1),
            },
            factual_future=future,
            action_propensities=propensities,
            factual_utility=float(utility),
            oracle_anchor={
                "panel": "randomized-identifiable",
                "randomized_fraction": 0.30,
                "causal_effect_identified": True,
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
            raise ProtocolViolation("policy is not in the finite W15A policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        del oracle_seed
        severity = float(episode.hidden_state_at_cut["severity"])
        confounder = int(episode.invariant_parameters["confounder"])
        variance = 0.0
        utility = 0.0
        steps: list[dict[str, Any]] = []
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            treated = "A1" in ids
            severity = self._step(severity, confounder, treated)
            variance = 0.92**2 * variance + 0.04**2
            utility -= 0.97**offset * (
                severity * severity
                + variance
                + 0.05 * treated
                + 0.06 * float("Q1" in ids)
            )
            steps.append(
                {
                    "offset": offset + 1,
                    "severity_mean": severity,
                    "severity_variance": variance,
                }
            )
        severity_class = int(episode.diagnostic_target["C1"] > 0.5)
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "identified-dynamic-scm",
                "steps": [
                    {
                        "offset": row["offset"],
                        "obs_0_mean": row["severity_mean"],
                        "obs_0_variance": row["severity_variance"] + 0.05**2,
                    }
                    for row in steps
                ],
            },
            latent_distribution={
                "family": "severity-confounder-state",
                "steps": steps,
                "diagnostic_posterior": {
                    "C0": float(severity_class == 0),
                    "C1": float(severity_class == 1),
                },
            },
            outcome_distribution={
                "identification_status": "identified-by-randomized-anchor",
                "utility_family": "discounted-severity",
                "expected_utility": float(utility),
            },
            expected_utility=float(utility),
            numerical_diagnostics={
                "method": "analytic-randomized-anchor-scm",
                "absolute_error_bound": 0.005,
                "posterior_fork": "single-cut-state",
            },
        )

    def _fixture(
        self, *, seed: int, salt: int, severity: float, confounder: int
    ) -> PrivateEpisode:
        key: tuple[str | int, ...] = ("w15a-fixture", salt)
        events = [
            _observation(seed, key, "obs_0", severity, 0, slot=0),
            _observation(seed, key, "obs_1", float(confounder), 0, slot=1),
            _observation(seed, key, "obs_2", 1.0, 0, slot=2),
        ]
        severity_class = int(severity >= 0.80)
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, salt),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"severity": severity},
            invariant_parameters={"confounder": confounder},
            diagnostic_target={
                "C0": float(severity_class == 0),
                "C1": float(severity_class == 1),
            },
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={"fixture": "randomized-identifiable"},
        )

    def distinguishable_fixture(
        self, seed: int = 1511
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        return (
            self._fixture(seed=seed, salt=1, severity=0.90, confounder=0),
            self._fixture(seed=seed, salt=2, severity=0.90, confounder=1),
        )

    def equivalent_fixture(
        self, seed: int = 1513
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        first = self._fixture(seed=seed, salt=3, severity=0.72, confounder=1)
        return first, replace(
            first,
            public_history=_alpha_rename(first.public_history, "w15a-equivalent"),
        )

    collision_fixture = distinguishable_fixture
    false_split_fixture = equivalent_fixture


class World15B(MicroWorld):
    """Observationally equivalent SCM twins with an unidentified do-effect."""

    def __init__(self) -> None:
        self._catalog = PublicCatalog(
            observations=(ChannelSpec("obs_0"), ChannelSpec("obs_1")),
            actions=(ActionSpec("A1", cost=0.05),),
            checks=(CheckSpec("Q0", ("obs_0", "obs_1"), (0, 0), cost=0.0),),
            diagnostic_labels=("C0", "C1"),
            horizons=(1,),
        )

    @property
    def environment_key(self) -> str:
        return "ucm-benchmark-private-w15b-v1"

    @property
    def catalog(self) -> PublicCatalog:
        return self._catalog

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon != 1:
            raise ProtocolViolation("W15B is a one-decision identified-set panel")
        return _finite_policy_set(horizon, treatments=("A1",), checks=())

    @staticmethod
    def _potential_outcomes(model: str, confounder: int) -> tuple[float, float]:
        if model == "Mplus":
            return 0.0, 1.0
        if confounder == 0:
            return 0.0, -1.0
        return 2.0, 1.0

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        _validate_episode_request(split, generator_seed, episode_index)
        model = "Mplus" if episode_index % 2 == 0 else "Mminus"
        pair_index = episode_index // 2
        confounder = (pair_index + int(split is WorldSplit.VALIDATION)) % 2
        # Crucially, every public random key excludes model and within-pair
        # index.  Adjacent episodes are therefore byte-identical twins.
        public_key: tuple[str | int, ...] = ("w15b-public", split.value, pair_index)
        neutral_context = 2.0 * uniform01(
            generator_seed, *public_key, "neutral-context"
        ) - 1.0
        events: list[Any] = [
            _observation(
                generator_seed,
                public_key,
                "obs_0",
                neutral_context,
                -1,
                slot=0,
            )
        ]
        if confounder == 1:
            events.append(_treatment(generator_seed, public_key, "A1", -1))
        observed_outcome = float(confounder)
        events.append(
            _observation(
                generator_seed,
                public_key,
                "obs_1",
                observed_outcome,
                0,
                slot=1,
            )
        )
        factual_utility = observed_outcome - 0.05 * confounder
        return PrivateEpisode(
            case_key=_case_key(
                self.environment_key, split, generator_seed, episode_index
            ),
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"observed_confounder": confounder},
            invariant_parameters={"private_scm": model},
            # The diagnostic target is identifiable exposure/severity class;
            # the private SCM identity is intentionally absent.
            diagnostic_target={
                "C0": float(confounder == 0),
                "C1": float(confounder == 1),
            },
            factual_future=[
                {
                    "offset": 0,
                    "observations": {"obs_1": observed_outcome},
                    "performed_action": "A1" if confounder else "NoNewAction",
                }
            ],
            action_propensities=[
                {
                    "decision_at": -1,
                    "probabilities": {
                        "A1": float(confounder == 1),
                        "NoNewAction": float(confounder == 0),
                    },
                    "selected": "A1" if confounder else "NoNewAction",
                    "positivity": "absent",
                }
            ],
            factual_utility=float(factual_utility),
            oracle_anchor={
                "panel": "observational-nonidentified",
                "public_scm_posterior": {"Mplus": 0.5, "Mminus": 0.5},
                "point_effect_scoring": False,
            },
        )

    @staticmethod
    def _public_confounder(episode: PrivateEpisode) -> int:
        return int(
            any(
                event.kind is EventKind.PERFORMED_TREATMENT
                and event.payload.get("action_id") == "A1"
                for event in episode.public_history.events
            )
        )

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the finite W15B policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        del oracle_seed
        confounder = self._public_confounder(episode)
        treated = any("A1" in ids for ids in _plan_ids(policy, 1))
        outcomes = []
        utilities = []
        for model in ("Mplus", "Mminus"):
            y0, y1 = self._potential_outcomes(model, confounder)
            outcome = y1 if treated else y0
            outcomes.append(outcome)
            utilities.append(outcome - 0.05 * treated)
        expected_outcome = math.fsum(outcomes) / 2.0
        expected_utility = math.fsum(utilities) / 2.0
        return CounterfactualOracle(
            policy=policy,
            horizon=1,
            observation_distribution={
                "family": "two-scm-public-evidence-mixture",
                "obs_1_support": outcomes,
                "obs_1_probabilities": [0.5, 0.5],
                "obs_1_mean": expected_outcome,
            },
            latent_distribution={
                "family": "nonidentified-scm-set",
                "diagnostic_posterior": {
                    "C0": float(confounder == 0),
                    "C1": float(confounder == 1),
                },
                "causal_model_posterior": {"Mplus": 0.5, "Mminus": 0.5},
            },
            outcome_distribution={
                "identification_status": "unsupported-point-effect",
                "ate_identified_set": [-1.0, 1.0],
                "policy_utility_support": utilities,
                "expected_utility": expected_utility,
                "recommendation": "abstain",
                "candidate_collision_attributable": False,
            },
            expected_utility=float(expected_utility),
            numerical_diagnostics={
                "method": "exact-observational-equivalence-class",
                "absolute_error_bound": 0.0,
                "private_scm_used_for_scoring": False,
            },
        )

    def judge_structural_effect(self, episode: PrivateEpisode) -> float:
        """Judge-only red-team fact; never used by the candidate scoring oracle."""

        model = str(episode.invariant_parameters["private_scm"])
        confounder = int(episode.hidden_state_at_cut["observed_confounder"])
        y0, y1 = self._potential_outcomes(model, confounder)
        return y1 - y0

    def nonidentified_twin_fixture(
        self, seed: int = 1521, *, confounder: int = 0
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        # Choose a pair index with the requested public confounder under test.
        offset = int(WorldSplit.SEALED_TEST is WorldSplit.VALIDATION)
        pair_index = (confounder - offset) % 2
        return (
            self.generate_episode(WorldSplit.SEALED_TEST, seed, 2 * pair_index),
            self.generate_episode(WorldSplit.SEALED_TEST, seed, 2 * pair_index + 1),
        )

    def distinguishable_fixture(
        self, seed: int = 1522
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        # Pair index 0 exposes u=0; pair index 1 exposes u=1.
        return (
            self.generate_episode(WorldSplit.SEALED_TEST, seed, 0),
            self.generate_episode(WorldSplit.SEALED_TEST, seed, 2),
        )

    def equivalent_fixture(
        self, seed: int = 1523
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        return self.nonidentified_twin_fixture(seed)

    collision_fixture = distinguishable_fixture
    false_split_fixture = equivalent_fixture


class World15(World15A):
    """Discovery alias for the identifiable primary panel; W15B stays separate."""


W15World = World15
World = World15

__all__ = ["W15World", "World", "World15", "World15A", "World15B"]
