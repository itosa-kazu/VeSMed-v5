"""W08: asynchronous, delayed and irregularly sampled observations."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import math
from typing import Any

import numpy as np

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
from .randomness import bernoulli, categorical, normal01
from .w06 import (
    _alpha_rename,
    _condition_gaussian,
    _event,
    _mixture_moments,
    _mixed_categorical,
    _no_action,
    _opaque_token,
    _reference_linear_condition,
    _reference_normalized_weights,
    _sequence,
    _softmax,
    _validate_episode_request,
    _visible_history,
    _unique_plans,
)


class World08(MicroWorld):
    """A linear-Gaussian world where availability and collection are distinct."""

    _DELTA = 0.25
    _F = (
        np.asarray([[-0.08, 0.04], [-0.02, -0.12]], dtype=float),
        np.asarray([[-0.04, -0.06], [0.05, -0.10]], dtype=float),
    )
    _B = np.asarray([-0.28, 0.10], dtype=float)

    def __init__(self) -> None:
        self._catalog = PublicCatalog(
            observations=(ChannelSpec("obs_0"), ChannelSpec("obs_1")),
            actions=(ActionSpec("A1"), ActionSpec("A2")),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 8), cost=0.03),
                CheckSpec("Q1", ("obs_1",), (1, 6), cost=0.03),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(4, 16, 32),
            time_unit="microtick",
        )

    @property
    def environment_key(self) -> str:
        return "ucm-benchmark-private-w08-v1"

    @property
    def catalog(self) -> PublicCatalog:
        return self._catalog

    def _delay(self, split: WorldSplit, channel: str, seed: int, *key: str | int) -> int:
        if channel == "obs_0":
            if split is WorldSplit.SEALED_TEST:
                support, probabilities = (0, 1, 4, 8), (0.35, 0.30, 0.25, 0.10)
            else:
                support, probabilities = (0, 1, 4), (0.39, 0.33, 0.28)
        else:
            if split is WorldSplit.TRAIN:
                support, probabilities = (1, 3), (0.53, 0.47)
            else:
                support, probabilities = (1, 3, 6), (0.40, 0.35, 0.25)
        return support[categorical(probabilities, seed, *key)]

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        _validate_episode_request(split, generator_seed, episode_index)
        key = ("episode", episode_index, split.value)
        c = categorical((0.5, 0.5), generator_seed, *key, "class")
        # The draft leaves the W08 initial prior implicit.  We freeze the
        # candidate-neutral N(0, .8^2 I) prior here and report it as a spec gap.
        x = np.asarray(
            [
                0.8 * normal01(generator_seed, *key, "initial", 0),
                0.8 * normal01(generator_seed, *key, "initial", 1),
            ],
            dtype=float,
        )
        exposure = 0
        remaining = 0
        events = []
        pending = []
        propensities: list[dict[str, Any]] = []
        latest_y = 0.0
        course_starts: dict[int, int] = {}
        delivered_results: set[str] = set()
        drawn_delays: list[dict[str, Any]] = []

        for tick in range(-16, 0):
            newly_available = sorted(
                [
                    event
                    for event in pending
                    if event.available_at <= tick
                    and event.event_uid not in delivered_results
                ],
                key=lambda event: (
                    event.available_at,
                    event.occurred_at,
                    event.kind.value,
                    event.event_uid,
                ),
            )
            for event in newly_available:
                latest_y = float(event.payload["value"])
                delivered_results.add(event.event_uid)

            if tick % 4 == 0:
                probabilities = _mixed_categorical(
                    _softmax((0.2, 0.8 * latest_y, -0.8 * latest_y))
                )
                choice = categorical(
                    probabilities, generator_seed, *key, "behavior-action", tick
                )
                direction = (0, 1, -1)[choice]
                propensities.append(
                    {
                        "tick": tick,
                        "conditioning": "available_public_prefix",
                        "public_inputs": {"latest_available_value": latest_y},
                        "action": {
                            "NoNewAction": probabilities[0],
                            "A1": probabilities[1],
                            "A2": probabilities[2],
                        },
                        "selected_action": (
                            "A1" if direction > 0 else "A2" if direction < 0 else "NoNewAction"
                        ),
                    }
                )
                if direction:
                    exposure, remaining = direction, 4
                    course_starts[tick] = direction
                    events.append(
                        _event(
                            kind=EventKind.PERFORMED_TREATMENT,
                            occurred_at=tick,
                            available_at=tick,
                            uid=_opaque_token(generator_seed, *key, "course", tick),
                            payload={
                                "action_id": "A1" if direction > 0 else "A2",
                                "course_microticks": 4,
                            },
                        )
                    )

            p_order = 0.12 + 0.30 / (
                1.0 + math.exp(-(abs(latest_y) - 0.45))
            )
            p_order = 0.90 * p_order + 0.10 * 0.50
            order = bernoulli(p_order, generator_seed, *key, "behavior-check", tick)
            propensities.append(
                {
                    "tick": tick,
                    "conditioning": "available_public_prefix",
                    "public_inputs": {"latest_available_value": latest_y},
                    "check": {"AnyCheck": p_order, "NoCheck": 1.0 - p_order},
                    "selected_check": "AnyCheck" if order else "NoCheck",
                }
            )
            if order:
                channel = (
                    "obs_0"
                    if bernoulli(0.55, generator_seed, *key, "check-kind", tick)
                    else "obs_1"
                )
                check_id = "Q0" if channel == "obs_0" else "Q1"
                delay = self._delay(
                    split, channel, generator_seed, *key, "delay", channel, tick
                )
                drawn_delays.append(
                    {"channel_id": channel, "delay": delay, "collected_at": tick}
                )
                value = float(x[0 if channel == "obs_0" else 1]) + 0.10 * normal01(
                    generator_seed, *key, "observation", channel, tick
                )
                events.extend(
                    (
                        _event(
                            kind=EventKind.TEST_ORDERED,
                            occurred_at=tick,
                            available_at=tick,
                            uid=_opaque_token(generator_seed, *key, "order", tick),
                            payload={"check_id": check_id},
                        ),
                        _event(
                            kind=EventKind.TEST_PERFORMED,
                            occurred_at=tick,
                            collected_at=tick,
                            available_at=tick,
                            uid=_opaque_token(generator_seed, *key, "perform", tick),
                            payload={"check_id": check_id},
                        ),
                    )
                )
                pending.append(
                    _event(
                        kind=EventKind.OBSERVATION_AVAILABLE,
                        occurred_at=tick,
                        collected_at=tick,
                        available_at=tick + delay,
                        uid=_opaque_token(generator_seed, *key, "result", tick),
                        payload={"channel_id": channel, "check_id": check_id, "value": value},
                    )
                )

            active = exposure if remaining > 0 else 0
            transition = np.eye(2) + self._DELTA * self._F[c]
            x = (
                transition @ x
                + self._DELTA * self._B * active
                + math.sqrt(self._DELTA)
                * 0.05
                * np.asarray(
                    [
                        normal01(generator_seed, *key, "process", tick + 1, 0),
                        normal01(generator_seed, *key, "process", tick + 1, 1),
                    ]
                )
            )
            if remaining > 0:
                remaining -= 1
                if remaining == 0:
                    exposure = 0

        events.extend(pending)
        history = _visible_history(events, self.catalog)
        factual_future = []
        factual_utility = 0.0
        future_x = x.copy()
        future_exposure, future_remaining = exposure, remaining
        transition = np.eye(2) + self._DELTA * self._F[c]
        for step in range(1, 33):
            active = future_exposure if future_remaining > 0 else 0
            future_x = (
                transition @ future_x
                + self._DELTA * self._B * active
                + math.sqrt(self._DELTA)
                * 0.05
                * np.asarray(
                    [
                        normal01(generator_seed, *key, "factual-future", step, 0),
                        normal01(generator_seed, *key, "factual-future", step, 1),
                    ]
                )
            )
            if future_remaining > 0:
                future_remaining -= 1
                if future_remaining == 0:
                    future_exposure = 0
            factual_future.append(
                {"offset": step, "latent_0": float(future_x[0]), "latent_1": float(future_x[1])}
            )
            factual_utility -= self._DELTA * 0.995 ** (step - 1) * (
                float(future_x[0] ** 2 + 0.6 * future_x[1] ** 2)
                + 0.04 * active * active
            )
        strata = ["iid_support"]
        available_times = [event.available_at for event in pending]
        if split is WorldSplit.SEALED_TEST and any(
            value in {0, 1} for value in available_times
        ):
            strata.append("boundary_tail")
        if split is WorldSplit.SEALED_TEST and any(
            row["channel_id"] == "obs_0" and row["delay"] == 8
            for row in drawn_delays
        ):
            strata.append("schedule_time_holdout")
        return PrivateEpisode(
            case_key=f"w08-private-{split.value}-{episode_index}",
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=history,
            hidden_state_at_cut={
                "x": [float(x[0]), float(x[1])],
                "exposure": exposure,
                "remaining": remaining,
                "pending_results": [
                    {
                        "collected_at": event.collected_at,
                        "available_at": event.available_at,
                        "channel_id": event.payload["channel_id"],
                        "value": event.payload["value"],
                    }
                    for event in pending
                    if event.available_at > 0
                ],
            },
            invariant_parameters={
                "c": c,
                "course_starts": [
                    {"tick": tick, "direction": direction}
                    for tick, direction in sorted(course_starts.items())
                ],
            },
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=factual_future,
            action_propensities=propensities,
            factual_utility=factual_utility,
            oracle_anchor={
                "posterior_source": "available_public_history_only",
                "late_result_rule": "condition_on_collected_at",
                "drawn_delays": drawn_delays,
                "split_strata": strata,
            },
        )

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        if episode.environment_key != self.environment_key:
            raise ProtocolViolation("episode belongs to a different world")
        recorded = episode.oracle_anchor.get("split_strata")
        delays = episode.oracle_anchor.get("drawn_delays")
        if not isinstance(recorded, list) or any(type(item) is not str for item in recorded):
            raise ProtocolViolation("W08 episode lacks exact split strata")
        if not isinstance(delays, list) or any(type(item) is not dict for item in delays):
            raise ProtocolViolation("W08 episode lacks exact delay ledger")
        strata = ["iid_support"]
        if episode.split is WorldSplit.SEALED_TEST and any(
            int(row["collected_at"]) + int(row["delay"]) in {0, 1}
            for row in delays
        ):
            strata.append("boundary_tail")
        if episode.split is WorldSplit.SEALED_TEST and any(
            row["channel_id"] == "obs_0" and int(row["delay"]) == 8
            for row in delays
        ):
            strata.append("schedule_time_holdout")
        strata = tuple(strata)
        allowed = {"iid_support", "boundary_tail", "schedule_time_holdout"}
        if not strata or strata[0] != "iid_support" or set(strata) - allowed:
            raise ProtocolViolation("W08 split strata contradict the registry")
        if tuple(recorded) != strata:
            raise ProtocolViolation("W08 stored split stratum is stale")
        return strata

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ProtocolViolation("unsupported W08 horizon")
        constant_a1 = _sequence(
            *((offset, "A1", {"course_microticks": 4}) for offset in range(0, horizon, 4))
        )
        constant_a2 = _sequence(
            *((offset, "A2", {"course_microticks": 4}) for offset in range(0, horizon, 4))
        )
        continuation_digest = digest_json({"semantics": "continue_active_course_at_boundary"})
        return _unique_plans((
            _no_action(),
            ActionPlan(PlanKind.STOP_CONTROLLABLE),
            ActionPlan(PlanKind.CONTINUE_CURRENT, policy_digest=continuation_digest),
            _sequence((0, "A1", {"course_microticks": 4})),
            _sequence((0, "A2", {"course_microticks": 4})),
            constant_a1,
            constant_a2,
            _sequence((0, "Q0", None)),
            _sequence((0, "Q1", None)),
            _sequence((0, "Q0", {"rule": "sign_at_next_boundary"})),
            _sequence((0, "Q1", {"rule": "sign_at_next_boundary"})),
        ))

    def _exposure_at_cut(self, history: Any) -> tuple[int, int]:
        latest_tick: int | None = None
        direction = 0
        for event in history.events:
            if event.kind is EventKind.PERFORMED_TREATMENT and event.payload.get("action_id") in {"A1", "A2"}:
                tick = event.occurred_at
                if latest_tick is None or tick > latest_tick:
                    latest_tick = tick
                    direction = 1 if event.payload["action_id"] == "A1" else -1
        if latest_tick is None:
            return 0, 0
        remaining = max(0, 4 - (0 - latest_tick))
        return (direction if remaining else 0), remaining

    def _posterior(self, episode: PrivateEpisode) -> list[dict[str, Any]]:
        if episode.public_history.catalog_digest != self.catalog.digest:
            raise ProtocolViolation("public history uses a different catalog")
        times = list(range(-16, 1))
        position = {tick: index for index, tick in enumerate(times)}
        actions: dict[int, int] = {}
        for event in episode.public_history.events:
            if event.kind is EventKind.PERFORMED_TREATMENT and event.payload.get("action_id") in {"A1", "A2"}:
                direction = 1 if event.payload["action_id"] == "A1" else -1
                for tick in range(event.occurred_at, event.occurred_at + 4):
                    if -16 <= tick < 0:
                        actions[tick] = direction
        observations = [
            event
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") in {"obs_0", "obs_1"}
            and event.collected_at in position
        ]
        y = np.asarray([float(event.payload["value"]) for event in observations])
        components = []
        log_weights = []
        dimension = 2 * len(times)
        for c in range(2):
            mean = np.zeros(dimension)
            covariance = np.zeros((dimension, dimension))
            covariance[:2, :2] = np.eye(2) * 0.8**2
            transition = np.eye(2) + self._DELTA * self._F[c]
            process_cov = np.eye(2) * (self._DELTA * 0.05**2)
            for step, tick in enumerate(range(-16, 0), start=1):
                previous = slice(2 * (step - 1), 2 * step)
                current = slice(2 * step, 2 * (step + 1))
                mean[current] = transition @ mean[previous] + self._DELTA * self._B * actions.get(tick, 0)
                covariance[current, : 2 * step] = transition @ covariance[previous, : 2 * step]
                covariance[: 2 * step, current] = covariance[current, : 2 * step].T
                covariance[current, current] = transition @ covariance[previous, previous] @ transition.T + process_cov
            design = np.zeros((len(observations), dimension))
            noise = np.eye(len(observations)) * 0.10**2
            for row, event in enumerate(observations):
                index = 2 * position[int(event.collected_at)]
                design[row, index + (0 if event.payload["channel_id"] == "obs_0" else 1)] = 1.0
            post_mean, post_cov, log_likelihood = _condition_gaussian(
                mean, covariance, design, y, noise
            )
            components.append(
                {
                    "class": c,
                    "mean": post_mean[-2:],
                    "covariance": post_cov[-2:, -2:],
                    "weight": 0.0,
                }
            )
            log_weights.append(math.log(0.5) + log_likelihood)
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
            raise ProtocolViolation("policy is not in the W08 frozen policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        components = self._posterior(episode)
        current_exposure, current_remaining = self._exposure_at_cut(episode.public_history)
        return self._counterfactual_from_components(
            components,
            current_exposure,
            current_remaining,
            policy,
            horizon,
        )

    def judge_true_state_counterfactual(
        self,
        hidden_state_at_cut: dict[str, Any],
        invariant_parameters: dict[str, Any],
        policy: ActionPlan,
        horizon: int,
    ) -> CounterfactualOracle:
        """Evaluate W08 from judge-known physiology and active-course state."""

        if set(hidden_state_at_cut) != {"x", "exposure", "remaining"}:
            raise ProtocolViolation(
                "W08 private state must contain x, exposure and remaining"
            )
        if set(invariant_parameters) != {"c"}:
            raise ProtocolViolation("W08 private parameters must contain c")
        state = hidden_state_at_cut["x"]
        exposure = hidden_state_at_cut["exposure"]
        remaining = hidden_state_at_cut["remaining"]
        class_index = invariant_parameters["c"]
        if (
            type(state) is not list
            or len(state) != 2
            or any(type(value) not in {int, float} for value in state)
            or any(not math.isfinite(float(value)) for value in state)
        ):
            raise ProtocolViolation("W08 private x must contain two finite numbers")
        if type(exposure) is not int or exposure not in {-1, 0, 1}:
            raise ProtocolViolation("W08 private exposure must be -1, zero or one")
        if type(remaining) is not int or remaining not in range(5):
            raise ProtocolViolation("W08 private remaining must be in [0, 4]")
        if (remaining == 0) != (exposure == 0):
            raise ProtocolViolation("W08 private course typestate is inconsistent")
        if type(class_index) is not int or class_index not in {0, 1}:
            raise ProtocolViolation("W08 private class must be zero or one")
        return self._counterfactual_from_components(
            [
                {
                    "class": class_index,
                    "mean": np.asarray([float(value) for value in state]),
                    "covariance": np.zeros((2, 2)),
                    "weight": 1.0,
                }
            ],
            exposure,
            remaining,
            policy,
            horizon,
        )

    def _counterfactual_from_components(
        self,
        components: list[dict[str, Any]],
        current_exposure: int,
        current_remaining: int,
        policy: ActionPlan,
        horizon: int,
    ) -> CounterfactualOracle:
        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the W08 frozen policy set")
        starts = {
            action.offset: (1 if action.action_id == "A1" else -1)
            for action in policy.actions
            if action.action_id in {"A1", "A2"}
        }
        check_count = sum(action.action_id in {"Q0", "Q1"} for action in policy.actions)
        per_component = []
        utility = 0.0
        for component in components:
            mean = np.asarray(component["mean"], dtype=float)
            covariance = np.asarray(component["covariance"], dtype=float)
            exposure, remaining = current_exposure, current_remaining
            if policy.kind is PlanKind.STOP_CONTROLLABLE:
                exposure, remaining = 0, 0
            latent_0 = []
            latent_1 = []
            component_utility = -0.03 * check_count
            transition = np.eye(2) + self._DELTA * self._F[int(component["class"])]
            process_cov = np.eye(2) * (self._DELTA * 0.05**2)
            for step in range(1, horizon + 1):
                offset = step - 1
                if offset in starts:
                    exposure, remaining = starts[offset], 4
                elif (
                    policy.kind is PlanKind.CONTINUE_CURRENT
                    and offset % 4 == 0
                    and current_exposure != 0
                ):
                    exposure, remaining = current_exposure, 4
                active = exposure if remaining > 0 else 0
                mean = transition @ mean + self._DELTA * self._B * active
                covariance = transition @ covariance @ transition.T + process_cov
                m0, m1 = float(mean[0]), float(mean[1])
                v0, v1 = float(covariance[0, 0]), float(covariance[1, 1])
                latent_0.append((m0, v0))
                latent_1.append((m1, v1))
                component_utility -= self._DELTA * 0.995 ** (step - 1) * (
                    v0 + m0 * m0 + 0.6 * (v1 + m1 * m1) + 0.04 * active * active
                )
                if remaining > 0:
                    remaining -= 1
                    if remaining == 0:
                        exposure = 0
            utility += float(component["weight"]) * component_utility
            per_component.append(
                {
                    "weight": float(component["weight"]),
                    "latent_0": latent_0,
                    "latent_1": latent_1,
                }
            )
        weights = [item["weight"] for item in per_component]

        def rows(key: str, observation_noise: float = 0.0) -> list[dict[str, float]]:
            answer = []
            for index in range(horizon):
                mean, variance = _mixture_moments(
                    weights,
                    [float(item[key][index][0]) for item in per_component],
                    [float(item[key][index][1]) + observation_noise for item in per_component],
                )
                answer.append({"offset": index + 1, "mean": mean, "variance": variance})
            return answer

        diagnosis = {
            f"C{int(component['class'])}": float(component["weight"])
            for component in components
        }
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "obs_0": rows("latent_0", 0.10**2),
                "obs_1": rows("latent_1", 0.10**2),
            },
            latent_distribution={"x0": rows("latent_0"), "x1": rows("latent_1")},
            outcome_distribution={
                "expected_utility": utility,
                "diagnostic_posterior": diagnosis,
                "pending_results_consumed": False,
            },
            expected_utility=utility,
            numerical_diagnostics={
                "method": "batch_gaussian_out_of_sequence_reference",
                "posterior_source": "available_public_history_only",
                "oracle_seed_used": False,
            },
        )

    def reference_counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        *,
        oracle_seed: int = 0,
    ) -> float:
        """Independent full-trajectory batch reference conditioned at collection time."""

        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the W08 frozen policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        del oracle_seed
        times = tuple(range(-16, 1))
        time_index = {tick: offset for offset, tick in enumerate(times)}
        factual_exposure: dict[int, int] = {}
        latest_course_tick: int | None = None
        latest_course_direction = 0
        for event in episode.public_history.events:
            if (
                event.kind is EventKind.PERFORMED_TREATMENT
                and event.payload.get("action_id") in {"A1", "A2"}
            ):
                direction = 1 if event.payload["action_id"] == "A1" else -1
                if latest_course_tick is None or event.occurred_at > latest_course_tick:
                    latest_course_tick = event.occurred_at
                    latest_course_direction = direction
                for tick in range(event.occurred_at, event.occurred_at + 4):
                    if -16 <= tick < 0:
                        factual_exposure[tick] = direction
        observations = [
            event
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") in {"obs_0", "obs_1"}
            and event.collected_at in time_index
        ]
        observed = np.asarray(
            [float(event.payload["value"]) for event in observations], dtype=float
        )
        dimension = 2 * len(times)
        components: list[tuple[int, np.ndarray, np.ndarray]] = []
        log_weights: list[float] = []
        for class_index in range(2):
            prior_mean = np.zeros(dimension, dtype=float)
            prior_covariance = np.zeros((dimension, dimension), dtype=float)
            prior_covariance[:2, :2] = np.eye(2) * 0.8**2
            transition = np.eye(2) + self._DELTA * self._F[class_index]
            process = np.eye(2) * (self._DELTA * 0.05**2)
            for offset, tick in enumerate(range(-16, 0), start=1):
                previous = slice(2 * (offset - 1), 2 * offset)
                current = slice(2 * offset, 2 * (offset + 1))
                prior_mean[current] = (
                    transition @ prior_mean[previous]
                    + self._DELTA * self._B * factual_exposure.get(tick, 0)
                )
                prior_covariance[current, : 2 * offset] = (
                    transition @ prior_covariance[previous, : 2 * offset]
                )
                prior_covariance[: 2 * offset, current] = (
                    prior_covariance[current, : 2 * offset].T
                )
                prior_covariance[current, current] = (
                    transition @ prior_covariance[previous, previous] @ transition.T
                    + process
                )
            design = np.zeros((len(observations), dimension), dtype=float)
            noise = np.eye(len(observations), dtype=float) * 0.10**2
            for row, event in enumerate(observations):
                coordinate = 0 if event.payload["channel_id"] == "obs_0" else 1
                design[row, 2 * time_index[int(event.collected_at)] + coordinate] = 1.0
            posterior_mean, posterior_covariance, likelihood = (
                _reference_linear_condition(
                    prior_mean, prior_covariance, design, observed, noise
                )
            )
            components.append(
                (
                    class_index,
                    posterior_mean[-2:].copy(),
                    posterior_covariance[-2:, -2:].copy(),
                )
            )
            log_weights.append(math.log(0.5) + likelihood)
        weights = _reference_normalized_weights(log_weights)
        current_remaining = (
            0
            if latest_course_tick is None
            else max(0, 4 - (0 - latest_course_tick))
        )
        current_exposure = latest_course_direction if current_remaining else 0
        planned_starts = {
            action.offset: (1 if action.action_id == "A1" else -1)
            for action in policy.actions
            if action.action_id in {"A1", "A2"}
        }
        check_count = sum(
            action.action_id in {"Q0", "Q1"} for action in policy.actions
        )
        total_utility = 0.0
        for (class_index, mean, covariance), weight in zip(components, weights):
            exposure = current_exposure
            remaining = current_remaining
            if policy.kind is PlanKind.STOP_CONTROLLABLE:
                exposure = remaining = 0
            component_utility = -0.03 * check_count
            transition = np.eye(2) + self._DELTA * self._F[class_index]
            process = np.eye(2) * (self._DELTA * 0.05**2)
            for step in range(1, horizon + 1):
                offset = step - 1
                if offset in planned_starts:
                    exposure, remaining = planned_starts[offset], 4
                elif (
                    policy.kind is PlanKind.CONTINUE_CURRENT
                    and offset % 4 == 0
                    and current_exposure != 0
                ):
                    exposure, remaining = current_exposure, 4
                active = exposure if remaining > 0 else 0
                mean = transition @ mean + self._DELTA * self._B * active
                covariance = transition @ covariance @ transition.T + process
                component_utility -= self._DELTA * 0.995**offset * (
                    float(covariance[0, 0])
                    + float(mean[0]) ** 2
                    + 0.6 * (float(covariance[1, 1]) + float(mean[1]) ** 2)
                    + 0.04 * active * active
                )
                if remaining > 0:
                    remaining -= 1
                    if remaining == 0:
                        exposure = 0
            total_utility += weight * component_utility
        return float(total_utility)

    def probe_fixtures(
        self, generator_seed: int = 808
    ) -> dict[str, tuple[PrivateEpisode, PrivateEpisode]]:
        base = self.generate_episode(WorldSplit.SEALED_TEST, generator_seed, 0)
        future_swap = replace(
            base,
            case_key="w08-private-future-swap",
            factual_future=list(reversed(base.factual_future)),
            hidden_state_at_cut={
                **base.hidden_state_at_cut,
                "pending_results": list(reversed(base.hidden_state_at_cut["pending_results"])),
            },
        )
        renamed = replace(
            base,
            case_key="w08-private-alpha-renamed",
            public_history=_alpha_rename(base.public_history, "w08-alpha"),
        )

        def collection(side: str, collected_at: int) -> PrivateEpisode:
            event = _event(
                kind=EventKind.OBSERVATION_AVAILABLE,
                occurred_at=collected_at,
                collected_at=collected_at,
                available_at=0,
                uid=hashlib.sha256(f"{side}:result".encode()).hexdigest()[:32],
                payload={"channel_id": "obs_0", "check_id": "Q0", "value": 0.75},
            )
            return replace(
                base,
                case_key=f"w08-private-collection-{side}",
                public_history=_visible_history([event], self.catalog),
            )

        visible_boundary = _event(
            kind=EventKind.OBSERVATION_AVAILABLE,
            occurred_at=-1,
            collected_at=-1,
            available_at=0,
            uid=hashlib.sha256(b"w08-visible-boundary").hexdigest()[:32],
            payload={"channel_id": "obs_1", "check_id": "Q1", "value": 0.25},
        )
        hidden_boundary = replace(
            visible_boundary,
            available_at=1,
            event_uid=hashlib.sha256(b"w08-hidden-boundary").hexdigest()[:32],
        )
        boundary_left = replace(
            base,
            case_key="w08-private-boundary-visible",
            public_history=_visible_history([visible_boundary], self.catalog),
        )
        boundary_right = replace(
            base,
            case_key="w08-private-boundary-hidden",
            public_history=_visible_history([hidden_boundary], self.catalog),
        )
        delivery = _event(
            kind=EventKind.OBSERVATION_AVAILABLE,
            occurred_at=-4,
            collected_at=-4,
            available_at=-4,
            uid=hashlib.sha256(b"w08-availability-equivalent").hexdigest()[:32],
            payload={"channel_id": "obs_0", "check_id": "Q0", "value": 0.42},
        )
        delivery_early = replace(
            base,
            case_key="w08-private-availability-early",
            public_history=_visible_history([delivery], self.catalog),
        )
        delivery_late = replace(
            base,
            case_key="w08-private-availability-late",
            public_history=_visible_history([replace(delivery, available_at=0)], self.catalog),
        )
        return {
            "collection_time_collision": (collection("fresh", 0), collection("stale", -8)),
            "availability_boundary": (boundary_left, boundary_right),
            "availability_equivalent": (delivery_early, delivery_late),
            "identical_prefix_future_swap": (base, future_swap),
            "false_split_alpha_rename": (base, renamed),
        }


__all__ = ["World08"]
