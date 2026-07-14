"""W06: an intervention that changes only the observation channel.

The implementation deliberately keeps the candidate projection boring: the
world key, split, episode index, random tape and latent state remain in the
``PrivateEpisode``.  The oracle reconstructs a class-mixture posterior from
the public history instead of conditioning on the realized private state.

This module also owns a few small, candidate-neutral construction helpers used
by W07--W10.  They live here (rather than in ``base.py``) so that the frozen
base protocol need not change while the microworlds are still pre-freeze.
"""

from __future__ import annotations

from dataclasses import replace
import hashlib
import math
from typing import Any, Iterable

import numpy as np

from ..canonical import ProtocolViolation, canonical_json_bytes, digest_json
from ..schema import (
    ActionPlan,
    CandidateVisibleEvent,
    EventKind,
    PlanKind,
    PlannedAction,
    VisibleHistory,
    event_sort_key,
)
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


def _validate_episode_request(
    split: WorldSplit, generator_seed: int, episode_index: int
) -> None:
    if type(split) is not WorldSplit:
        raise ProtocolViolation("split must be WorldSplit")
    if (
        type(generator_seed) is not int
        or generator_seed < 0
        or generator_seed >= 2**128
    ):
        raise ProtocolViolation("generator_seed must be an unsigned 128-bit integer")
    if type(episode_index) is not int or episode_index < 0:
        raise ProtocolViolation("episode_index must be a non-negative integer")


def _opaque_token(master_seed: int, *parts: str | int) -> str:
    """Return a non-reversible visible token with no semantic prefix."""

    wire = canonical_json_bytes([master_seed, *parts])
    return hashlib.sha256(b"UCM_OPAQUE_TOKEN_V1\0" + wire).hexdigest()[:32]


def _event(
    *,
    kind: EventKind,
    occurred_at: int,
    available_at: int,
    uid: str,
    payload: dict[str, Any],
    collected_at: int | None = None,
) -> CandidateVisibleEvent:
    return CandidateVisibleEvent(
        kind=kind,
        occurred_at=occurred_at,
        collected_at=collected_at,
        available_at=available_at,
        event_uid=uid,
        payload=payload,
    )


def _visible_history(
    events: Iterable[CandidateVisibleEvent], catalog: PublicCatalog, as_of: int = 0
) -> VisibleHistory:
    visible = tuple(
        sorted(
            (event for event in events if event.available_at <= as_of),
            key=event_sort_key,
        )
    )
    return VisibleHistory(
        events=visible,
        as_of_available_at=as_of,
        catalog_digest=catalog.digest,
    )


def _alpha_rename(history: VisibleHistory, namespace: str) -> VisibleHistory:
    renamed = tuple(
        replace(
            event,
            event_uid=hashlib.sha256(
                f"{namespace}:{position}".encode("utf-8")
            ).hexdigest()[:32],
        )
        for position, event in enumerate(history.events)
    )
    return VisibleHistory(
        events=tuple(sorted(renamed, key=event_sort_key)),
        as_of_available_at=history.as_of_available_at,
        catalog_digest=history.catalog_digest,
    )


def _no_action() -> ActionPlan:
    return ActionPlan(PlanKind.NO_NEW_ACTION)


def _sequence(*actions: tuple[int, str, dict[str, Any] | None]) -> ActionPlan:
    planned = tuple(
        sorted(
            (
                PlannedAction(
                    offset=offset,
                    action_id=action_id,
                    parameters={} if parameters is None else parameters,
                )
                for offset, action_id, parameters in actions
            ),
            key=lambda item: (item.offset, item.action_id),
        )
    )
    return ActionPlan(PlanKind.ACTION_SEQUENCE, planned)


def _constant_plan(action_id: str, horizon: int, stride: int = 1) -> ActionPlan:
    return _sequence(
        *((offset, action_id, None) for offset in range(0, horizon, stride))
    )


def _unique_plans(plans: Iterable[ActionPlan]) -> tuple[ActionPlan, ...]:
    """Preserve semantic order while removing horizon-induced duplicates."""

    answer: list[ActionPlan] = []
    seen: set[bytes] = set()
    for plan in plans:
        wire = canonical_json_bytes(plan.to_wire())
        if wire not in seen:
            seen.add(wire)
            answer.append(plan)
    return tuple(answer)


def _softmax(logits: tuple[float, ...]) -> tuple[float, ...]:
    peak = max(logits)
    raw = tuple(math.exp(value - peak) for value in logits)
    total = math.fsum(raw)
    return tuple(value / total for value in raw)


def _mixed_categorical(
    base: tuple[float, ...], exploration: float = 0.10
) -> tuple[float, ...]:
    uniform = 1.0 / len(base)
    return tuple((1.0 - exploration) * value + exploration * uniform for value in base)


def _normal_logpdf(y: np.ndarray, mean: np.ndarray, covariance: np.ndarray) -> float:
    if y.size == 0:
        return 0.0
    covariance = (covariance + covariance.T) * 0.5
    sign, logdet = np.linalg.slogdet(covariance)
    if sign <= 0:
        covariance = covariance + np.eye(covariance.shape[0]) * 1e-10
        sign, logdet = np.linalg.slogdet(covariance)
    delta = y - mean
    solved = np.linalg.solve(covariance, delta)
    return float(-0.5 * (y.size * math.log(2.0 * math.pi) + logdet + delta @ solved))


def _condition_gaussian(
    mean: np.ndarray,
    covariance: np.ndarray,
    design: np.ndarray,
    observed: np.ndarray,
    noise_covariance: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Batch Gaussian conditioning and its marginal log likelihood."""

    if observed.size == 0:
        return mean.copy(), covariance.copy(), 0.0
    innovation_cov = design @ covariance @ design.T + noise_covariance
    predicted = design @ mean
    gain = np.linalg.solve(innovation_cov, design @ covariance).T
    posterior_mean = mean + gain @ (observed - predicted)
    posterior_cov = covariance - gain @ design @ covariance
    posterior_cov = (posterior_cov + posterior_cov.T) * 0.5
    return (
        posterior_mean,
        posterior_cov,
        _normal_logpdf(observed, predicted, innovation_cov),
    )


def _mixture_moments(
    weights: list[float], means: list[float], variances: list[float]
) -> tuple[float, float]:
    mean = math.fsum(weight * value for weight, value in zip(weights, means))
    second = math.fsum(
        weight * (variance + value * value)
        for weight, value, variance in zip(weights, means, variances)
    )
    return mean, max(0.0, second - mean * mean)


def _positive_square_moment(mean: float, variance: float) -> float:
    if variance <= 1e-15:
        return max(0.0, mean) ** 2
    sigma = math.sqrt(variance)
    z = mean / sigma
    phi = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    cdf = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return (variance + mean * mean) * cdf + mean * sigma * phi


def _normal_cdf(value: float, mean: float, variance: float) -> float:
    if variance <= 1e-15:
        return 1.0 if value >= mean else 0.0
    return 0.5 * (
        1.0 + math.erf((value - mean) / math.sqrt(2.0 * variance))
    )


class World06(MicroWorld):
    """Treatment A1 masks a routine channel but cannot change physiology."""

    _RHO = (0.88, 0.97)
    _BIAS = (0.08, 0.03)

    def __init__(self) -> None:
        self._catalog = PublicCatalog(
            observations=(ChannelSpec("obs_0"), ChannelSpec("obs_1")),
            actions=(ActionSpec("A1", cost=0.30),),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.10),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    @property
    def environment_key(self) -> str:
        return "ucm-benchmark-private-w06-v1"

    @property
    def catalog(self) -> PublicCatalog:
        return self._catalog

    def _prior(self, split: WorldSplit) -> tuple[float, float]:
        del split
        return 0.0, 1.4

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        _validate_episode_request(split, generator_seed, episode_index)
        key = ("episode", episode_index, split.value)
        c = categorical((0.5, 0.5), generator_seed, *key, "class")
        low, high = self._prior(split)
        x = low + (high - low) * uniform01(generator_seed, *key, "initial-x")
        r = 0.0
        events: list[CandidateVisibleEvent] = []
        propensities: list[dict[str, Any]] = []
        pending: list[CandidateVisibleEvent] = []

        initial_y = x + 0.05 * normal01(generator_seed, *key, "q0", -4)
        events.append(
            _event(
                kind=EventKind.OBSERVATION_AVAILABLE,
                occurred_at=-4,
                collected_at=-4,
                available_at=-4,
                uid=_opaque_token(generator_seed, *key, "q0", -4),
                payload={"channel_id": "obs_0", "check_id": "Q0", "value": initial_y},
            )
        )
        latest_y = initial_y
        actions_by_tick: dict[int, bool] = {}

        for tick in range(-4, 0):
            base_action = 0.10 + 0.75 / (
                1.0 + math.exp(-1.4 * (latest_y - 0.45))
            )
            p_action = 0.90 * base_action + 0.10 * 0.50
            take_action = bernoulli(
                p_action, generator_seed, *key, "behavior-action", tick
            )
            base_check = 0.08 + 0.35 / (
                1.0 + math.exp(-(abs(latest_y - 0.50) - 0.25))
            )
            p_check = 0.90 * base_check + 0.10 * 0.50
            take_check = bernoulli(
                p_check, generator_seed, *key, "behavior-check", tick
            )
            actions_by_tick[tick] = take_action
            propensities.append(
                {
                    "tick": tick,
                    "action": {"A1": p_action, "NoNewAction": 1.0 - p_action},
                    "check": {"Q1": p_check, "NoCheck": 1.0 - p_check},
                }
            )
            if take_action:
                events.append(
                    _event(
                        kind=EventKind.PERFORMED_TREATMENT,
                        occurred_at=tick,
                        available_at=tick,
                        uid=_opaque_token(generator_seed, *key, "a1", tick),
                        payload={"action_id": "A1", "dose": 1.0},
                    )
                )
            if take_check:
                events.extend(
                    (
                        _event(
                            kind=EventKind.TEST_ORDERED,
                            occurred_at=tick,
                            available_at=tick,
                            uid=_opaque_token(generator_seed, *key, "q1-order", tick),
                            payload={"check_id": "Q1"},
                        ),
                        _event(
                            kind=EventKind.TEST_PERFORMED,
                            occurred_at=tick + 1,
                            collected_at=tick + 1,
                            available_at=tick + 1,
                            uid=_opaque_token(generator_seed, *key, "q1-perform", tick),
                            payload={"check_id": "Q1"},
                        ),
                    )
                )

            x = (
                self._RHO[c] * x
                + self._BIAS[c]
                + 0.04 * normal01(generator_seed, *key, "process", tick + 1)
            )
            r = 0.25 * r + float(take_action)
            latest_y = (
                x
                - 0.75 * r
                + 0.05 * normal01(generator_seed, *key, "q0", tick + 1)
            )
            events.append(
                _event(
                    kind=EventKind.OBSERVATION_AVAILABLE,
                    occurred_at=tick + 1,
                    collected_at=tick + 1,
                    available_at=tick + 1,
                    uid=_opaque_token(generator_seed, *key, "q0", tick + 1),
                    payload={
                        "channel_id": "obs_0",
                        "check_id": "Q0",
                        "value": latest_y,
                    },
                )
            )
            if take_check:
                q1 = x + 0.08 * normal01(
                    generator_seed, *key, "q1-value", tick + 1
                )
                pending.append(
                    _event(
                        kind=EventKind.OBSERVATION_AVAILABLE,
                        occurred_at=tick + 1,
                        collected_at=tick + 1,
                        available_at=tick + 2,
                        uid=_opaque_token(generator_seed, *key, "q1-result", tick),
                        payload={"channel_id": "obs_1", "check_id": "Q1", "value": q1},
                    )
                )

        events.extend(pending)
        history = _visible_history(events, self.catalog)
        factual_future, factual_utility = self._realized_natural_future(
            x, r, c, generator_seed, key
        )
        return PrivateEpisode(
            case_key=f"w06-private-{split.value}-{episode_index}",
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=history,
            hidden_state_at_cut={"x": x, "r": r},
            invariant_parameters={
                "c": c,
                "rho": self._RHO[c],
                "bias": self._BIAS[c],
            },
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=factual_future,
            action_propensities=propensities,
            factual_utility=factual_utility,
            oracle_anchor={
                "posterior_source": "public_history_only",
                "latent_action_effect": 0.0,
            },
        )

    def _realized_natural_future(
        self,
        x: float,
        r: float,
        c: int,
        seed: int,
        key: tuple[str | int, ...],
    ) -> tuple[list[dict[str, Any]], float]:
        rows: list[dict[str, Any]] = []
        utility = 0.0
        for step in range(1, 9):
            x = self._RHO[c] * x + self._BIAS[c] + 0.04 * normal01(
                seed, *key, "factual-future", step
            )
            r *= 0.25
            obs = x - 0.75 * r + 0.05 * normal01(
                seed, *key, "factual-observation", step
            )
            rows.append({"offset": step, "latent": x, "obs_0": obs})
            utility -= 0.97 ** (step - 1) * (x * x + 0.60 * max(0.0, x - 0.75 * r) ** 2)
        return rows, utility

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ProtocolViolation("unsupported W06 horizon")
        return _unique_plans((
            _no_action(),
            _sequence((0, "A1", None)),
            _constant_plan("A1", horizon),
            _sequence((0, "Q1", None)),
            _sequence((0, "Q1", {"rule": "never_A1"})),
        ))

    def _posterior(self, episode: PrivateEpisode) -> list[dict[str, float]]:
        if episode.environment_key != self.environment_key:
            raise ProtocolViolation("episode belongs to a different world")
        times = list(range(-4, 1))
        index = {tick: position for position, tick in enumerate(times)}
        performed = {
            event.occurred_at
            for event in episode.public_history.events
            if event.kind is EventKind.PERFORMED_TREATMENT
            and event.payload.get("action_id") == "A1"
        }
        r_by_time = {-4: 0.0}
        for tick in range(-4, 0):
            r_by_time[tick + 1] = 0.25 * r_by_time[tick] + float(tick in performed)

        low, high = self._prior(episode.split)
        observations = [
            event
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") in {"obs_0", "obs_1"}
            and event.collected_at in index
        ]
        y = np.asarray([float(event.payload["value"]) for event in observations])
        log_weights: list[float] = []
        components: list[dict[str, float]] = []
        for c, (rho, bias) in enumerate(zip(self._RHO, self._BIAS)):
            mean = np.zeros(5)
            covariance = np.zeros((5, 5))
            mean[0] = (low + high) / 2.0
            covariance[0, 0] = (high - low) ** 2 / 12.0
            for position in range(1, 5):
                mean[position] = rho * mean[position - 1] + bias
                covariance[position, :position] = rho * covariance[position - 1, :position]
                covariance[:position, position] = covariance[position, :position]
                covariance[position, position] = (
                    rho * rho * covariance[position - 1, position - 1] + 0.04**2
                )
            design = np.zeros((len(observations), 5))
            adjusted = y.copy()
            noise = np.zeros((len(observations), len(observations)))
            for row, event in enumerate(observations):
                position = index[int(event.collected_at)]
                design[row, position] = 1.0
                if event.payload["channel_id"] == "obs_0":
                    adjusted[row] += 0.75 * r_by_time[int(event.collected_at)]
                    noise[row, row] = 0.05**2
                else:
                    noise[row, row] = 0.08**2
            post_mean, post_cov, log_likelihood = _condition_gaussian(
                mean, covariance, design, adjusted, noise
            )
            log_weights.append(math.log(0.5) + log_likelihood)
            components.append(
                {
                    "class": float(c),
                    "mean_x": float(post_mean[-1]),
                    "var_x": float(max(post_cov[-1, -1], 0.0)),
                    "r": r_by_time[0],
                    "weight": 0.0,
                }
            )
        peak = max(log_weights)
        raw = [math.exp(value - peak) for value in log_weights]
        total = math.fsum(raw)
        for component, value in zip(components, raw):
            component["weight"] = value / total
        return components

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the W06 frozen policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        components = self._posterior(episode)
        actions = {
            action.offset
            for action in policy.actions
            if action.action_id == "A1"
        }
        checks = {
            action.offset
            for action in policy.actions
            if action.action_id == "Q1"
        }
        per_component: list[dict[str, Any]] = []
        utility = 0.0
        for component in components:
            c = int(component["class"])
            mean_x = component["mean_x"]
            var_x = component["var_x"]
            r = component["r"]
            latent: list[tuple[float, float]] = []
            routine: list[tuple[float, float]] = []
            check_values: list[tuple[float, float]] = []
            component_utility = 0.0
            for step in range(1, horizon + 1):
                action_offset = step - 1
                took_action = action_offset in actions
                mean_x = self._RHO[c] * mean_x + self._BIAS[c]
                var_x = self._RHO[c] ** 2 * var_x + 0.04**2
                r = 0.25 * r + float(took_action)
                obs_mean = mean_x - 0.75 * r
                obs_var = var_x + 0.05**2
                latent.append((mean_x, var_x))
                routine.append((obs_mean, obs_var))
                check_values.append((mean_x, var_x + 0.08**2))
                component_utility -= 0.97 ** (step - 1) * (
                    var_x
                    + mean_x * mean_x
                    + 0.60 * _positive_square_moment(obs_mean, var_x)
                    + 0.30 * float(took_action)
                    + 0.10 * float(action_offset in checks)
                )
            utility += component["weight"] * component_utility
            per_component.append(
                {
                    "weight": component["weight"],
                    "latent": latent,
                    "routine": routine,
                    "check": check_values,
                }
            )

        weights = [float(item["weight"]) for item in per_component]
        latent_rows: list[dict[str, float]] = []
        routine_rows: list[dict[str, float]] = []
        check_rows: list[dict[str, float]] = []
        for position in range(horizon):
            latent_mean, latent_var = _mixture_moments(
                weights,
                [float(item["latent"][position][0]) for item in per_component],
                [float(item["latent"][position][1]) for item in per_component],
            )
            obs_mean, obs_var = _mixture_moments(
                weights,
                [float(item["routine"][position][0]) for item in per_component],
                [float(item["routine"][position][1]) for item in per_component],
            )
            q1_mean, q1_var = _mixture_moments(
                weights,
                [float(item["check"][position][0]) for item in per_component],
                [float(item["check"][position][1]) for item in per_component],
            )
            latent_rows.append({"offset": position + 1, "mean": latent_mean, "variance": latent_var})
            routine_rows.append({"offset": position + 1, "mean": obs_mean, "variance": obs_var})
            check_rows.append({"offset": position + 1, "mean": q1_mean, "variance": q1_var})
        diagnosis = {
            f"C{int(component['class'])}": component["weight"]
            for component in components
        }
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={"obs_0": routine_rows, "obs_1": check_rows},
            latent_distribution={"x": latent_rows},
            outcome_distribution={
                "expected_utility": utility,
                "diagnostic_posterior": diagnosis,
                "latent_action_path": "none",
            },
            expected_utility=utility,
            numerical_diagnostics={
                "method": "analytic_class_mixture_batch_gaussian",
                "posterior_source": "candidate_visible_history",
                "oracle_seed_used": False,
            },
        )

    def probe_fixtures(
        self, generator_seed: int = 606
    ) -> dict[str, tuple[PrivateEpisode, PrivateEpisode]]:
        """Frozen semantic pairs: masked state, future leak and false split."""

        base = self.generate_episode(WorldSplit.SEALED_TEST, generator_seed, 0)
        future_swap = replace(
            base,
            case_key="w06-private-future-swap",
            factual_future=list(reversed(base.factual_future)),
            factual_utility=base.factual_utility - 1.0,
        )
        renamed = replace(
            base,
            case_key="w06-private-alpha-renamed",
            public_history=_alpha_rename(base.public_history, "w06-alpha"),
        )

        def masked(side: str, treated: bool) -> PrivateEpisode:
            events: list[CandidateVisibleEvent] = []
            for tick in range(-4, 1):
                if treated and tick == -1:
                    events.append(
                        _event(
                            kind=EventKind.PERFORMED_TREATMENT,
                            occurred_at=-1,
                            available_at=-1,
                            uid=hashlib.sha256(f"{side}:a".encode()).hexdigest()[:32],
                            payload={"action_id": "A1", "dose": 1.0},
                        )
                    )
                value = 0.55 if tick == 0 else (1.25 if treated else 0.55)
                events.append(
                    _event(
                        kind=EventKind.OBSERVATION_AVAILABLE,
                        occurred_at=tick,
                        collected_at=tick,
                        available_at=tick,
                        uid=hashlib.sha256(f"{side}:q:{tick}".encode()).hexdigest()[:32],
                        payload={"channel_id": "obs_0", "check_id": "Q0", "value": value},
                    )
                )
            # The channel-independent check pins the intended latent side.
            # Its low-side realization is deliberately a rare noisy draw; the
            # fixture is oracle-screened for disjoint optimal policy sets.
            events.append(
                _event(
                    kind=EventKind.OBSERVATION_AVAILABLE,
                    occurred_at=0,
                    collected_at=0,
                    available_at=0,
                    uid=hashlib.sha256(f"{side}:q1".encode()).hexdigest()[:32],
                    payload={
                        "channel_id": "obs_1",
                        "check_id": "Q1",
                        "value": 1.30 if treated else 0.20,
                    },
                )
            )
            return replace(
                base,
                case_key=f"w06-private-masked-{side}",
                public_history=_visible_history(events, self.catalog),
                hidden_state_at_cut={"x": 1.30 if treated else 0.55, "r": 1.0 if treated else 0.0},
            )

        return {
            "masked_state_collision": (masked("low", False), masked("high", True)),
            "identical_prefix_future_swap": (base, future_swap),
            "false_split_alpha_rename": (base, renamed),
        }


__all__ = ["World06"]
