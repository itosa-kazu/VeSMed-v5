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
    _channel_rows,
    _finite_policy_set,
    _normal_log_likelihood,
    _normalise_log_particles,
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
        confounder = (episode_index + int(split is WorldSplit.VALIDATION)) % 2
        draw = uniform01(generator_seed, *key, "severity")
        if split is WorldSplit.TRAIN:
            # Training diagonal: both host strata remain represented while the
            # opposite severity x u combinations are held for sealed test.
            severity = (0.25 + 0.35 * draw) if confounder == 0 else (0.95 + 0.35 * draw)
            stratum = "train-severity-u-diagonal"
        elif split is WorldSplit.VALIDATION:
            severity = 0.55 + 0.40 * draw
            stratum = "validation-middle-band"
        elif episode_index % 10 < 6:
            severity = (0.95 + 0.35 * draw) if confounder == 0 else (0.25 + 0.35 * draw)
            stratum = "sealed-heldout-severity-u-cross"
        else:
            severity = 0.25 + 1.05 * draw
            stratum = "sealed-iid"
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
        current_public_y = y
        for offset in range(4):
            p_treat = _sigmoid(1.5 * current_public_y)
            treated = bernoulli(
                p_treat, generator_seed, *key, "future-treatment", offset
            )
            severity = self._step(
                severity,
                confounder,
                treated,
                0.04 * normal01(generator_seed, *key, "future-process", offset),
            )
            current_public_y = severity + 0.05 * normal01(
                generator_seed, *key, "future-q0", offset
            )
            utility -= 0.97**offset * (severity * severity + 0.05 * treated)
            future.append(
                {
                    "offset": offset + 1,
                    "observations": {"obs_0": current_public_y},
                    "performed_action": "A1" if treated else "NoNewAction",
                }
            )
            propensities.append(
                {
                    "decision_at": offset,
                    "assignment": "behavioral",
                    "probabilities": {
                        "A1": p_treat,
                        "NoNewAction": 1.0 - p_treat,
                    },
                    "selected": "A1" if treated else "NoNewAction",
                    "check_probabilities": {"Q1": 0.0, "NoCheck": 1.0},
                    "selected_check": "NoCheck",
                    "phase": "factual-future",
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
                "split_stratum": stratum,
                "probe_attribution": "causal-effect-attributable",
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
        particles = self._public_posterior(episode)
        variance = 0.0
        utility = 0.0
        steps: list[dict[str, Any]] = []
        working = [(confounder, severity, weight) for confounder, severity, weight in particles]
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            treated = "A1" in ids
            working = [
                (confounder, self._step(severity, confounder, treated), weight)
                for confounder, severity, weight in working
            ]
            variance = 0.92**2 * variance + 0.04**2
            expected = math.fsum(
                weight * severity * severity
                for _, severity, weight in working
            )
            expected += variance + 0.05 * treated + 0.06 * float("Q1" in ids)
            utility -= 0.97**offset * expected
            mean = math.fsum(weight * severity for _, severity, weight in working)
            posterior_variance = math.fsum(
                weight * (severity - mean) ** 2
                for _, severity, weight in working
            )
            steps.append(
                {
                    "offset": offset + 1,
                    "severity_mean": mean,
                    "severity_variance": posterior_variance + variance,
                }
            )
        p_c0 = math.fsum(
            weight for _, severity, weight in particles if severity < 0.80
        )
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
                    "C0": p_c0,
                    "C1": 1.0 - p_c0,
                },
            },
            outcome_distribution={
                "identification_status": "identified-by-randomized-anchor",
                "utility_family": "discounted-severity",
                "expected_utility": float(utility),
            },
            expected_utility=float(utility),
            numerical_diagnostics={
                "method": "public-history-randomized-anchor-grid",
                "absolute_error_bound": 0.025,
                "posterior_fork": "single-public-posterior",
                "private_state_used": False,
                "identified_transition_effect": -0.35,
            },
        )

    @classmethod
    def _public_posterior(
        cls, episode: PrivateEpisode
    ) -> tuple[tuple[int, float, float], ...]:
        observations = _channel_rows(episode, "obs_0")
        if not observations:
            raise ProtocolViolation("W15A requires public obs_0")
        latest = observations[-1][1]
        markers = _channel_rows(episode, "obs_1")
        marker = markers[-1][1] if markers else None
        actions = {
            event.occurred_at
            for event in episode.public_history.events
            if event.kind is EventKind.PERFORMED_TREATMENT
            and event.payload.get("action_id") == "A1"
        }
        # Public transition residuals sharpen u without conditioning on the
        # realized private confounder.
        residual_scores = {0: 0.0, 1: 0.0}
        for (tick0, y0), (tick1, y1) in zip(observations, observations[1:]):
            treated = tick0 in actions
            for confounder in (0, 1):
                predicted = 0.92 * y0 + 0.20 * confounder - 0.35 * treated
                residual_scores[confounder] += _normal_log_likelihood(
                    y1, predicted, 0.10
                )
        upper = max(1.8, latest + 0.6)
        rows: list[tuple[tuple[Any, ...], float]] = []
        for confounder in (0, 1):
            for i in range(91):
                severity = upper * i / 90.0
                score = _normal_log_likelihood(latest, severity, 0.075)
                score += residual_scores[confounder]
                if marker is not None:
                    score += _normal_log_likelihood(
                        marker, float(confounder), 0.10
                    )
                rows.append(((confounder, severity), score))
        return _normalise_log_particles(rows)  # type: ignore[return-value]

    def reference_counterfactual(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> float:
        """Independent midpoint enumeration with inline randomized SCM."""

        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the finite W15A policy set")
        observations = _channel_rows(episode, "obs_0")
        if not observations:
            raise ProtocolViolation("W15A reference requires obs_0")
        latest = observations[-1][1]
        markers = _channel_rows(episode, "obs_1")
        marker = markers[-1][1] if markers else None
        actions = {
            event.occurred_at
            for event in episode.public_history.events
            if event.kind is EventKind.PERFORMED_TREATMENT
            and event.payload.get("action_id") == "A1"
        }
        raw: list[tuple[int, float, float]] = []
        upper = max(1.8, latest + 0.6)
        for confounder in (0, 1):
            residual_score = 0.0
            for (tick0, y0), (_, y1) in zip(observations, observations[1:]):
                mean = 0.92 * y0 + 0.20 * confounder - 0.35 * float(tick0 in actions)
                residual_score += _normal_log_likelihood(y1, mean, 0.10)
            if marker is not None:
                residual_score += _normal_log_likelihood(marker, float(confounder), 0.10)
            for i in range(140):
                severity = upper * (i + 0.5) / 140.0
                score = residual_score + _normal_log_likelihood(latest, severity, 0.075)
                raw.append((confounder, severity, score))
        peak = max(row[2] for row in raw)
        weighted = [(u, x, math.exp(max(-745.0, s - peak))) for u, x, s in raw]
        norm = math.fsum(row[2] for row in weighted)
        particles = [(u, x, w / norm) for u, x, w in weighted]
        variance = 0.0
        utility = 0.0
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            treated = "A1" in ids
            particles = [
                (u, max(0.0, 0.92 * x + 0.20 * u - 0.35 * treated), weight)
                for u, x, weight in particles
            ]
            variance = 0.92**2 * variance + 0.04**2
            expected = math.fsum(weight * x * x for _, x, weight in particles)
            expected += variance + 0.05 * treated + 0.06 * float("Q1" in ids)
            utility -= 0.97**offset * expected
        return float(utility)

    def private_state_upper_bound(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> float:
        """Judge-only realized-confounder comparator, excluded from scoring."""

        severity = float(episode.hidden_state_at_cut["severity"])
        confounder = int(episode.invariant_parameters["confounder"])
        utility = 0.0
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            treated = "A1" in ids
            severity = self._step(severity, confounder, treated)
            utility -= 0.97**offset * (
                severity * severity + 0.05 * treated + 0.06 * float("Q1" in ids)
            )
        return float(utility)

    @staticmethod
    def estimate_randomized_anchor_effect(
        episodes: tuple[PrivateEpisode, ...]
    ) -> float:
        """Estimate the one-step effect from public randomized slots only.

        This is a benchmark audit helper, not the production oracle.  It
        demonstrates that identification comes from observable randomization
        rather than from the private confounder field.
        """

        treated_residuals: list[float] = []
        control_residuals: list[float] = []
        for episode in episodes:
            observations = dict(_channel_rows(episode, "obs_0"))
            randomized_ticks = {
                tick
                for tick, value in _channel_rows(episode, "obs_2")
                if value == 1.0
            }
            treated_ticks = {
                event.occurred_at
                for event in episode.public_history.events
                if event.kind is EventKind.PERFORMED_TREATMENT
                and event.payload.get("action_id") == "A1"
            }
            for tick in randomized_ticks:
                if tick not in observations or tick + 1 not in observations:
                    continue
                residual = observations[tick + 1] - 0.92 * observations[tick]
                (treated_residuals if tick in treated_ticks else control_residuals).append(
                    residual
                )
        if not treated_residuals or not control_residuals:
            raise ProtocolViolation("randomized anchor sample lacks both arms")
        return (
            math.fsum(treated_residuals) / len(treated_residuals)
            - math.fsum(control_residuals) / len(control_residuals)
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
            oracle_anchor={
                "fixture": "randomized-identifiable",
                "probe_attribution": "candidate-attributable",
            },
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
        # The candidate cut is explicitly *before* the observational action
        # and outcome.  Therefore a NoNewAction query sets the upcoming action
        # to zero; it never attempts to undo a treatment already in history.
        events: list[Any] = [
            _observation(
                generator_seed,
                public_key,
                "obs_0",
                neutral_context,
                0,
                slot=0,
            )
        ]
        observed_outcome = float(confounder)
        factual_utility = observed_outcome - 0.05 * confounder
        return PrivateEpisode(
            case_key=_case_key(
                self.environment_key, split, generator_seed, episode_index
            ),
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"latent_confounder": confounder},
            invariant_parameters={"private_scm": model},
            # The diagnostic target is identifiable exposure/severity class;
            # the private SCM identity is intentionally absent.
            diagnostic_target={
                "C0": 0.5,
                "C1": 0.5,
            },
            factual_future=[
                {
                    "offset": 1,
                    "observations": {"obs_1": observed_outcome},
                    "performed_action": "A1" if confounder else "NoNewAction",
                }
            ],
            action_propensities=[
                {
                    "decision_at": 0,
                    "probabilities": {
                        "A1": float(confounder == 1),
                        "NoNewAction": float(confounder == 0),
                    },
                    "selected": "A1" if confounder else "NoNewAction",
                    "positivity": "absent",
                    "phase": "factual-future",
                }
            ],
            factual_utility=float(factual_utility),
            oracle_anchor={
                "panel": "observational-nonidentified",
                "public_scm_posterior": {"Mplus": 0.5, "Mminus": 0.5},
                "point_effect_scoring": False,
                "cut_semantics": "pre-action-pre-outcome",
                "split_stratum": "exact-observational-twin",
                "probe_attribution": "nonidentified-not-candidate-error",
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
            raise ProtocolViolation("policy is not in the finite W15B policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        del oracle_seed
        treated = any("A1" in ids for ids in _plan_ids(policy, 1))
        outcomes = []
        utilities = []
        for model in ("Mplus", "Mminus"):
            for confounder in (0, 1):
                y0, y1 = self._potential_outcomes(model, confounder)
                outcome = y1 if treated else y0
                outcomes.append(outcome)
                utilities.append(outcome - 0.05 * treated)
        expected_outcome = math.fsum(outcomes) / 4.0
        expected_utility = math.fsum(utilities) / 4.0
        return CounterfactualOracle(
            policy=policy,
            horizon=1,
            observation_distribution={
                "family": "two-scm-public-evidence-mixture",
                "obs_1_support": outcomes,
                "obs_1_probabilities": [0.25, 0.25, 0.25, 0.25],
                "obs_1_mean": expected_outcome,
            },
            latent_distribution={
                "family": "nonidentified-scm-set",
                "diagnostic_posterior": {
                    "C0": 0.5,
                    "C1": 0.5,
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
                "private_confounder_used_for_scoring": False,
                "cut_semantics": "pre-action-pre-outcome",
            },
        )

    def reference_counterfactual(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> float:
        """Source-distinct exact table enumerator for the public equivalence set."""

        del episode
        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the finite W15B policy set")
        treated = any("A1" in ids for ids in _plan_ids(policy, 1))
        # Rows are (Mplus,u0), (Mplus,u1), (Mminus,u0), (Mminus,u1).
        do_zero = (0.0, 0.0, 0.0, 2.0)
        do_one = (1.0, 1.0, -1.0, 1.0)
        selected = do_one if treated else do_zero
        return math.fsum(value - 0.05 * treated for value in selected) / 4.0

    def private_state_upper_bound(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> float:
        """Judge-only realized-SCM utility; prohibited as a scoring target."""

        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the finite W15B policy set")
        model = str(episode.invariant_parameters["private_scm"])
        confounder = int(episode.hidden_state_at_cut["latent_confounder"])
        treated = any("A1" in ids for ids in _plan_ids(policy, 1))
        y0, y1 = self._potential_outcomes(model, confounder)
        return float((y1 if treated else y0) - 0.05 * treated)

    def judge_structural_effect(self, episode: PrivateEpisode) -> float:
        """Judge-only red-team fact; never used by the candidate scoring oracle."""

        model = str(episode.invariant_parameters["private_scm"])
        confounder = int(episode.hidden_state_at_cut["latent_confounder"])
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
