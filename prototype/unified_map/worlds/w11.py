"""W11: observational convergence from two distinct mechanisms.

The routine channel only reports total burden.  A delayed component contrast
can identify which mechanism is active, and the two treatments target opposite
components.  All simulator state stays inside :class:`PrivateEpisode`.
"""

from __future__ import annotations

import math
from typing import Any

from ..canonical import ProtocolViolation, digest_json
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
from .w06 import (
    _alpha_rename,
    _constant_plan,
    _event,
    _mixed_categorical,
    _no_action,
    _opaque_token,
    _sequence,
    _softmax,
    _validate_episode_request,
    _visible_history,
)


def _case_key(environment: str, split: WorldSplit, seed: int, index: int) -> str:
    return digest_json(
        {
            "domain": "ucm-private-case-key/1",
            "environment": environment,
            "split": split.value,
            "seed": seed,
            "index": index,
        }
    )


def _finite_policy_set(
    horizon: int,
    *,
    treatments: tuple[str, ...],
    checks: tuple[str, ...],
) -> tuple[ActionPlan, ...]:
    policies: list[ActionPlan] = [_no_action()]
    policies.extend(_sequence((0, action, None)) for action in treatments)
    if horizon > 1:
        policies.extend(_constant_plan(action, horizon) for action in treatments)
    policies.extend(_sequence((0, check, None)) for check in checks)
    return tuple(policies)


def _plan_ids(policy: ActionPlan, horizon: int) -> tuple[tuple[str, ...], ...]:
    """Return the explicitly scheduled IDs for each offset."""

    rows: list[list[str]] = [[] for _ in range(horizon)]
    if policy.kind is PlanKind.ACTION_SEQUENCE:
        for action in policy.actions:
            if action.offset < horizon:
                rows[action.offset].append(action.action_id)
    return tuple(tuple(row) for row in rows)


def _observation(
    seed: int,
    key: tuple[str | int, ...],
    channel: str,
    value: float,
    tick: int,
    *,
    delay: int = 0,
    slot: int = 0,
) -> Any:
    return _event(
        kind=EventKind.OBSERVATION_AVAILABLE,
        occurred_at=tick,
        collected_at=tick,
        available_at=tick + delay,
        uid=_opaque_token(seed, *key, "obs", channel, tick, slot),
        payload={"channel_id": channel, "value": float(value)},
    )


def _treatment(
    seed: int, key: tuple[str | int, ...], action: str, tick: int, slot: int = 0
) -> Any:
    return _event(
        kind=EventKind.PERFORMED_TREATMENT,
        occurred_at=tick,
        available_at=tick,
        uid=_opaque_token(seed, *key, "action", action, tick, slot),
        payload={"action_id": action, "parameters": {}},
    )


def _last_channel(episode: PrivateEpisode, channel: str) -> float | None:
    values = [
        event.payload["value"]
        for event in episode.public_history.events
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == channel
    ]
    return None if not values else float(values[-1])


def _channel_rows(
    episode: PrivateEpisode, channel: str
) -> tuple[tuple[int, float], ...]:
    """Return semantic observations in occurrence order, ignoring opaque UIDs.

    Oracle conditioning is deliberately routed through this public projection.
    Nothing in this helper can read ``hidden_state_at_cut`` or
    ``invariant_parameters``.
    """

    rows = [
        (event.occurred_at, float(event.payload["value"]))
        for event in episode.public_history.events
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == channel
    ]
    return tuple(sorted(rows))


def _normal_log_likelihood(observed: float, mean: float, sigma: float) -> float:
    residual = (observed - mean) / sigma
    return -0.5 * residual * residual


def _normalise_log_particles(
    rows: list[tuple[tuple[Any, ...], float]],
) -> tuple[tuple[Any, ...], ...]:
    """Attach normalized weights to finite public-posterior particles."""

    if not rows:
        raise ProtocolViolation("public posterior grid is empty")
    maximum = max(log_weight for _, log_weight in rows)
    weights = [math.exp(max(-745.0, value - maximum)) for _, value in rows]
    total = math.fsum(weights)
    if not math.isfinite(total) or total <= 0.0:
        raise ProtocolViolation("public posterior failed to normalize")
    return tuple(
        (*particle, weight / total)
        for (particle, _), weight in zip(rows, weights, strict=True)
    )


def _semantic_events(episode: PrivateEpisode) -> list[dict[str, Any]]:
    """Fixture-only projection that deliberately ignores opaque UID alpha names."""

    return [
        {
            "kind": event.kind.value,
            "occurred_at": event.occurred_at,
            "collected_at": event.collected_at,
            "available_at": event.available_at,
            "payload": event.payload,
        }
        for event in episode.public_history.events
    ]


class World11(MicroWorld):
    """Two latent sources share a routine total but have different dynamics."""

    def __init__(self) -> None:
        self._catalog = PublicCatalog(
            observations=(ChannelSpec("obs_0"), ChannelSpec("obs_1")),
            actions=(ActionSpec("A1", cost=0.06), ActionSpec("A2", cost=0.06)),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.07),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    @property
    def environment_key(self) -> str:
        return "ucm-benchmark-private-w11-v1"

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
        x0: float,
        x1: float,
        action: str | None,
        noise0: float = 0.0,
        noise1: float = 0.0,
    ) -> tuple[float, float]:
        return (
            max(0.0, 0.92 * x0 + 0.08 - 0.42 * float(action == "A1") + noise0),
            max(0.0, 0.76 * x1 + 0.20 - 0.42 * float(action == "A2") + noise1),
        )

    @staticmethod
    def _behavior(y: float) -> tuple[float, float, float]:
        return _mixed_categorical(_softmax((0.3, 0.7 * y, 0.7 * y)))

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        _validate_episode_request(split, generator_seed, episode_index)
        key: tuple[str | int, ...] = ("w11", split.value, episode_index)
        if split is WorldSplit.SEALED_TEST:
            residue = episode_index % 20
            split_stratum = (
                "iid" if residue < 8
                else "same-q0-opposite-source-probe" if residue < 14
                else "q1-missing" if residue < 17
                else "q1-contradictory-noise"
            )
        elif split is WorldSplit.VALIDATION:
            split_stratum = "mixed-35-percent"
        else:
            split_stratum = "mixed-20-percent"
        c = (episode_index + (split is WorldSplit.VALIDATION)) % 2
        severity = 0.45 + 0.85 * uniform01(generator_seed, *key, "severity")
        minor = 0.02 + 0.10 * uniform01(generator_seed, *key, "minor")
        x0, x1 = (severity, minor) if c == 0 else (minor, severity)
        events: list[Any] = []
        propensities: list[dict[str, Any]] = []

        for tick in range(-3, 1):
            q0 = x0 + x1 + 0.05 * normal01(
                generator_seed, *key, "q0", tick
            )
            events.append(_observation(generator_seed, key, "obs_0", q0, tick))
            if tick == 0:
                break
            p_q1 = 0.15 + 0.30 / (1.0 + math.exp(-(q0 - 0.5)))
            p_q1 = 0.90 * p_q1 + 0.05
            if split_stratum == "q1-missing":
                p_q1 = 0.0
            ordered = bernoulli(p_q1, generator_seed, *key, "q1", tick)
            if ordered:
                contrast = x0 - x1 + 0.08 * normal01(
                    generator_seed, *key, "q1-value", tick
                )
                if split_stratum == "q1-contradictory-noise":
                    contrast = -contrast
                events.append(
                    _observation(
                        generator_seed,
                        key,
                        "obs_1",
                        contrast,
                        tick,
                        delay=1,
                    )
                )
            probabilities = self._behavior(q0)
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
                }
            )
            if action is not None:
                events.append(_treatment(generator_seed, key, action, tick))
            x0, x1 = self._step(
                x0,
                x1,
                action,
                0.035 * normal01(generator_seed, *key, "process", tick, 0),
                0.035 * normal01(generator_seed, *key, "process", tick, 1),
            )

        state_at_cut = (x0, x1)
        future: list[dict[str, Any]] = []
        factual_utility = 0.0
        for offset in range(4):
            probabilities = self._behavior(x0 + x1)
            choice = categorical(
                probabilities,
                generator_seed,
                *key,
                "factual-future-action",
                offset,
            )
            action = (None, "A1", "A2")[choice]
            x0, x1 = self._step(
                x0,
                x1,
                action,
                0.035
                * normal01(generator_seed, *key, "factual-process", offset, 0),
                0.035
                * normal01(generator_seed, *key, "factual-process", offset, 1),
            )
            cost = (x0 + x1) ** 2 + 0.25 * x0 * x1 + 0.06 * float(action is not None)
            factual_utility -= 0.97**offset * cost
            future.append(
                {
                    "offset": offset + 1,
                    "observations": {"obs_0": x0 + x1},
                    "performed_action": "NoNewAction" if action is None else action,
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
            hidden_state_at_cut={"components": [float(state_at_cut[0]), float(state_at_cut[1])]},
            invariant_parameters={"mechanism_index": int(c)},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=float(factual_utility),
            oracle_anchor={
                "oracle_family": "reflected-component-dynamics",
                "split_stratum": split_stratum,
                "probe_attribution": (
                    "candidate-attributable"
                    if split_stratum != "q1-missing"
                    else "posterior-ambiguity-expected"
                ),
            },
        )

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        """Classify the frozen W11 generator cell without reading private truth.

        The broad registry strata are derived from the judge-side generator
        design recorded at construction time.  In particular, the population
        cell whose historical name contains ``probe`` is *not* a pair probe:
        only episodes produced by the explicit pair-fixture constructors carry
        ``behavior_pair_member``.  This keeps probe rows out of the headline
        population denominator.
        """

        if type(episode) is not PrivateEpisode or episode.environment_key != self.environment_key:
            raise ProtocolViolation("W11 strata require a W11 PrivateEpisode")

        strata = ["iid_support"]
        pair_member = episode.oracle_anchor.get("behavior_pair_member", False)
        if type(pair_member) is not bool:
            raise ProtocolViolation("W11 behavior-pair witness must be boolean")

        cell = episode.oracle_anchor.get("split_stratum")
        if pair_member:
            if cell is not None or episode.factual_future or episode.action_propensities:
                raise ProtocolViolation("W11 pair witness is inconsistent with a population row")
        else:
            allowed = {
                WorldSplit.TRAIN: {"mixed-20-percent"},
                WorldSplit.VALIDATION: {"mixed-35-percent"},
                WorldSplit.SEALED_TEST: {
                    "iid",
                    "same-q0-opposite-source-probe",
                    "q1-missing",
                    "q1-contradictory-noise",
                },
            }[episode.split]
            if cell not in allowed:
                raise ProtocolViolation("W11 episode lacks a valid generator-cell witness")
            if cell == "q1-missing":
                q1_rows = _channel_rows(episode, "obs_1")
                prefix_propensities = [
                    row
                    for row in episode.action_propensities
                    if row.get("phase") != "factual-future"
                ]
                if q1_rows or not prefix_propensities or any(
                    row.get("check_probabilities", {}).get("Q1") != 0.0
                    for row in prefix_propensities
                ):
                    raise ProtocolViolation("W11 q1-missing witness contradicts generated material")
                strata.append("boundary_tail")
            elif cell == "q1-contradictory-noise":
                # The sign-reversed measurement kernel is a judge-side
                # generator setting, not an inferred private mechanism label.
                strata.append("boundary_tail")

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
            raise ProtocolViolation("policy is not in the finite W11 policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        del oracle_seed
        particles = self._public_posterior(episode)
        schedule = _plan_ids(policy, horizon)
        latent_steps: list[dict[str, Any]] = []
        observation_steps: list[dict[str, Any]] = []
        utility = 0.0
        variance0 = variance1 = 0.0
        working = [(x0, x1, weight) for x0, x1, weight in particles]
        for offset, ids in enumerate(schedule):
            action = "A1" if "A1" in ids else "A2" if "A2" in ids else None
            working = [(*self._step(x0, x1, action), weight) for x0, x1, weight in working]
            variance0 = 0.92**2 * variance0 + 0.035**2
            variance1 = 0.76**2 * variance1 + 0.035**2
            check_cost = 0.07 * float("Q1" in ids)
            mean0 = math.fsum(weight * x0 for x0, _, weight in working)
            mean1 = math.fsum(weight * x1 for _, x1, weight in working)
            second_sum = math.fsum(
                weight * (x0 + x1) ** 2 for x0, x1, weight in working
            )
            cross = math.fsum(weight * x0 * x1 for x0, x1, weight in working)
            posterior_var0 = math.fsum(
                weight * (x0 - mean0) ** 2 for x0, _, weight in working
            )
            posterior_var1 = math.fsum(
                weight * (x1 - mean1) ** 2 for _, x1, weight in working
            )
            expected_cost = (
                second_sum + variance0 + variance1 + 0.25 * cross
                + 0.06 * float(action is not None) + check_cost
            )
            utility -= 0.97**offset * expected_cost
            latent_steps.append(
                {
                    "offset": offset + 1,
                    "mean": [mean0, mean1],
                    "variance": [posterior_var0 + variance0, posterior_var1 + variance1],
                }
            )
            observation_steps.append(
                {
                    "offset": offset + 1,
                    "obs_0_mean": mean0 + mean1,
                    "obs_0_variance": (
                        math.fsum(
                            weight * ((x0 + x1) - (mean0 + mean1)) ** 2
                            for x0, x1, weight in working
                        )
                        + variance0 + variance1 + 0.05**2
                    ),
                    "obs_1_mean": mean0 - mean1,
                    "obs_1_variance": (
                        math.fsum(
                            weight * ((x0 - x1) - (mean0 - mean1)) ** 2
                            for x0, x1, weight in working
                        )
                        + variance0 + variance1 + 0.08**2
                    ),
                }
            )
        p_c0 = math.fsum(weight for x0, x1, weight in particles if x0 >= x1)
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "reflected-gaussian-moment-approximation",
                "steps": observation_steps,
            },
            latent_distribution={
                "family": "two-component-state",
                "steps": latent_steps,
                "diagnostic_posterior": {"C0": p_c0, "C1": 1.0 - p_c0},
            },
            outcome_distribution={
                "utility_family": "discounted-quadratic",
                "expected_utility": utility,
            },
            expected_utility=float(utility),
            numerical_diagnostics={
                "method": "public-history-component-grid",
                "absolute_error_bound": 0.03,
                "posterior_fork": "single-public-posterior",
                "private_state_used": False,
            },
        )

    @staticmethod
    def _public_posterior(
        episode: PrivateEpisode,
    ) -> tuple[tuple[float, float, float], ...]:
        """Production posterior: Cartesian component grid conditioned on H."""

        totals = _channel_rows(episode, "obs_0")
        if not totals:
            raise ProtocolViolation("W11 requires a public obs_0 at the cut")
        y_total = totals[-1][1]
        contrasts = _channel_rows(episode, "obs_1")
        y_contrast = contrasts[-1][1] if contrasts else None
        upper = max(1.8, y_total + 0.8)
        rows: list[tuple[tuple[Any, ...], float]] = []
        for i in range(31):
            x0 = upper * i / 30.0
            for j in range(31):
                x1 = upper * j / 30.0
                log_weight = _normal_log_likelihood(y_total, x0 + x1, 0.08)
                if y_contrast is not None:
                    log_weight += _normal_log_likelihood(
                        y_contrast, x0 - x1, 0.13
                    )
                rows.append(((x0, x1), log_weight))
        return _normalise_log_particles(rows)  # type: ignore[return-value]

    def reference_counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
    ) -> float:
        """Independent sum/contrast quadrature reference for expected utility.

        This path intentionally does not call ``_public_posterior`` or
        ``_step``.  It exists solely as a freeze-time reference check.
        """

        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the finite W11 policy set")
        totals = _channel_rows(episode, "obs_0")
        if not totals:
            raise ProtocolViolation("W11 reference requires obs_0")
        y0 = totals[-1][1]
        contrasts = _channel_rows(episode, "obs_1")
        y1 = contrasts[-1][1] if contrasts else None
        upper = max(1.8, y0 + 0.8)
        raw: list[tuple[float, float, float]] = []
        for si in range(1, 61):
            total = 2.0 * upper * (si - 0.5) / 60.0
            for di in range(1, 61):
                contrast = -upper + 2.0 * upper * (di - 0.5) / 60.0
                x0 = 0.5 * (total + contrast)
                x1 = 0.5 * (total - contrast)
                if x0 < 0.0 or x1 < 0.0 or x0 > upper or x1 > upper:
                    continue
                score = _normal_log_likelihood(y0, total, 0.08)
                if y1 is not None:
                    score += _normal_log_likelihood(y1, contrast, 0.13)
                raw.append((x0, x1, score))
        peak = max(row[2] for row in raw)
        weighted = [(x0, x1, math.exp(max(-745.0, score - peak))) for x0, x1, score in raw]
        normalizer = math.fsum(row[2] for row in weighted)
        particles = [(x0, x1, weight / normalizer) for x0, x1, weight in weighted]
        utility = 0.0
        variance0 = variance1 = 0.0
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = "A1" if "A1" in ids else "A2" if "A2" in ids else None
            next_rows = []
            for x0, x1, weight in particles:
                next0 = max(0.0, 0.92 * x0 + 0.08 - 0.42 * float(action == "A1"))
                next1 = max(0.0, 0.76 * x1 + 0.20 - 0.42 * float(action == "A2"))
                next_rows.append((next0, next1, weight))
            particles = next_rows
            variance0 = 0.92**2 * variance0 + 0.035**2
            variance1 = 0.76**2 * variance1 + 0.035**2
            expected = math.fsum(
                weight * ((x0 + x1) ** 2 + 0.25 * x0 * x1)
                for x0, x1, weight in particles
            )
            expected += variance0 + variance1
            expected += 0.06 * float(action is not None) + 0.07 * float("Q1" in ids)
            utility -= 0.97**offset * expected
        return float(utility)

    def private_state_upper_bound(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> float:
        """Judge-only realized-state upper bound; never used for scoring."""

        x0, x1 = (float(v) for v in episode.hidden_state_at_cut["components"])
        utility = 0.0
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = "A1" if "A1" in ids else "A2" if "A2" in ids else None
            x0, x1 = self._step(x0, x1, action)
            utility -= 0.97**offset * (
                (x0 + x1) ** 2 + 0.25 * x0 * x1
                + 0.06 * float(action is not None) + 0.07 * float("Q1" in ids)
            )
        return float(utility)

    def _fixture_episode(
        self,
        *,
        seed: int,
        salt: int,
        components: tuple[float, float],
        contrast: float,
        alpha_namespace: str | None = None,
    ) -> PrivateEpisode:
        key: tuple[str | int, ...] = ("w11-fixture", salt)
        events = [
            _observation(seed, key, "obs_0", sum(components), 0, slot=0),
            _observation(seed, key, "obs_1", contrast, 0, slot=1),
        ]
        c = int(components[1] > components[0])
        episode = PrivateEpisode(
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, salt),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"components": [components[0], components[1]]},
            invariant_parameters={"mechanism_index": c},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={
                "fixture": "paired",
                "behavior_pair_member": True,
                "probe_attribution": "candidate-attributable",
            },
        )
        if alpha_namespace is None:
            return episode
        return PrivateEpisode(
            case_key=episode.case_key,
            environment_key=episode.environment_key,
            split=episode.split,
            generator_seed=episode.generator_seed,
            public_history=_alpha_rename(episode.public_history, alpha_namespace),
            hidden_state_at_cut=episode.hidden_state_at_cut,
            invariant_parameters=episode.invariant_parameters,
            diagnostic_target=episode.diagnostic_target,
            factual_future=episode.factual_future,
            action_propensities=episode.action_propensities,
            factual_utility=episode.factual_utility,
            oracle_anchor=episode.oracle_anchor,
        )

    def distinguishable_fixture(
        self, seed: int = 1111
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Same total burden, but public contrast and optimal target differ."""

        value = 1.25
        return (
            self._fixture_episode(
                seed=seed, salt=1, components=(value, 0.0), contrast=value
            ),
            self._fixture_episode(
                seed=seed, salt=2, components=(0.0, value), contrast=-value
            ),
        )

    def equivalent_fixture(
        self, seed: int = 1113
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Opaque UID alpha-renaming must not create a clinical state split."""

        first = self._fixture_episode(
            seed=seed, salt=3, components=(0.72, 0.18), contrast=0.54
        )
        second = self._fixture_episode(
            seed=seed,
            salt=3,
            components=(0.72, 0.18),
            contrast=0.54,
            alpha_namespace="w11-equivalent",
        )
        return first, second

    collision_fixture = distinguishable_fixture
    false_split_fixture = equivalent_fixture


W11World = World11
World = World11

__all__ = [
    "W11World",
    "World",
    "World11",
    "_case_key",
    "_finite_policy_set",
    "_last_channel",
    "_observation",
    "_plan_ids",
    "_semantic_events",
    "_treatment",
]
