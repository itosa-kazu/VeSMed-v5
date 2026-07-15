"""W09: absolute observations must be interpreted relative to a personal baseline."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import math
from typing import Any

import numpy as np

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
from .randomness import bernoulli, categorical, normal01, uniform01
from .w06 import (
    _alpha_rename,
    _condition_gaussian,
    _constant_plan,
    _event,
    _mixture_moments,
    _mixed_categorical,
    _no_action,
    _normal_cdf,
    _opaque_token,
    _reference_linear_condition,
    _reference_normalized_weights,
    _sequence,
    _softmax,
    _validate_episode_request,
    _visible_history,
    _unique_plans,
)


class World09(MicroWorld):
    """Static baseline ``b`` and dynamic deviation ``x`` are distinct state."""

    _RHO = (0.78, 0.96)
    _DOSE = {"A1": 0.45, "A2": 0.80}

    def __init__(self) -> None:
        self._catalog = PublicCatalog(
            observations=(
                ChannelSpec("obs_0"),
                ChannelSpec("obs_1"),
                ChannelSpec("obs_2"),
            ),
            actions=(
                ActionSpec("A1", cost=0.05),
                ActionSpec("A2", cost=0.10),
            ),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.06),
                CheckSpec("Q2", ("obs_2",), (1, 1), cost=0.10),
            ),
            diagnostic_labels=("C00", "C01", "C10", "C11"),
            horizons=(1, 4, 8),
        )

    @property
    def environment_key(self) -> str:
        return "ucm-benchmark-private-w09-v1"

    @property
    def catalog(self) -> PublicCatalog:
        return self._catalog

    def _baseline_range(self, split: WorldSplit, seed: int, *key: str | int) -> tuple[float, float]:
        if split is WorldSplit.TRAIN:
            return -0.8, 0.8
        if split is WorldSplit.VALIDATION:
            return -1.0, 1.0
        # Frozen test allocates 15% to the declared shell.
        shell = bernoulli(0.15, seed, *key, "baseline-shell")
        if not shell:
            return -1.0, 1.0
        return (-1.25, -1.0) if bernoulli(0.5, seed, *key, "shell-side") else (1.0, 1.25)

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        _validate_episode_request(split, generator_seed, episode_index)
        key = ("episode", episode_index, split.value)
        c = categorical((0.5, 0.5), generator_seed, *key, "class")
        low_b, high_b = self._baseline_range(split, generator_seed, *key)
        baseline = low_b + (high_b - low_b) * uniform01(
            generator_seed, *key, "baseline"
        )
        x = -0.2 + 1.2 * uniform01(generator_seed, *key, "initial-deviation")
        events = []
        pending = []
        propensities: list[dict[str, Any]] = []
        latest_absolute = baseline + x + 0.05 * normal01(
            generator_seed, *key, "q0", -4
        )
        latest_baseline: float | None = None
        events.append(
            _event(
                kind=EventKind.OBSERVATION_AVAILABLE,
                occurred_at=-4,
                collected_at=-4,
                available_at=-4,
                uid=_opaque_token(generator_seed, *key, "q0", -4),
                payload={"channel_id": "obs_0", "check_id": "Q0", "value": latest_absolute},
            )
        )
        for tick in range(-4, 0):
            for result in pending:
                if result.available_at == tick and result.payload["channel_id"] == "obs_1":
                    latest_baseline = float(result.payload["value"])
            estimate = 0.0 if latest_baseline is None else latest_baseline
            z = latest_absolute - estimate
            probabilities = _mixed_categorical(
                _softmax((0.3, 0.8 * z, 1.2 * (z - 0.45)))
            )
            action_choice = categorical(
                probabilities, generator_seed, *key, "behavior-action", tick
            )
            action_id = (None, "A1", "A2")[action_choice]
            missing_baseline = latest_baseline is None
            p_q1 = 0.12 + 0.25 * float(missing_baseline)
            p_q2 = 0.08 + 0.25 / (1.0 + math.exp(-(abs(z) - 0.40)))
            # At most one targeted check; preserve the declared relative mass.
            check_probs = _mixed_categorical(
                (max(0.0, 1.0 - p_q1 - p_q2), p_q1, p_q2)
            )
            check_choice = categorical(
                check_probs, generator_seed, *key, "behavior-check", tick
            )
            check_id = (None, "Q1", "Q2")[check_choice]
            propensities.append(
                {
                    "tick": tick,
                    "conditioning": "available_public_prefix",
                    "public_inputs": {
                        "latest_absolute": latest_absolute,
                        "latest_baseline": latest_baseline,
                        "baseline_adjusted_value": z,
                    },
                    "action": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                        "A2": probabilities[2],
                    },
                    "check": {
                        "NoCheck": check_probs[0],
                        "Q1": check_probs[1],
                        "Q2": check_probs[2],
                    },
                    "selected_action": action_id or "NoNewAction",
                    "selected_check": check_id or "NoCheck",
                }
            )
            dose = 0.0 if action_id is None else self._DOSE[action_id]
            if action_id is not None:
                events.append(
                    _event(
                        kind=EventKind.PERFORMED_TREATMENT,
                        occurred_at=tick,
                        available_at=tick,
                        uid=_opaque_token(generator_seed, *key, "action", tick),
                        payload={"action_id": action_id, "dose": dose},
                    )
                )
            if check_id is not None:
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
                            occurred_at=tick + 1,
                            collected_at=tick + 1,
                            available_at=tick + 1,
                            uid=_opaque_token(generator_seed, *key, "perform", tick),
                            payload={"check_id": check_id},
                        ),
                    )
                )
            x = (
                self._RHO[c] * x
                + 0.08
                - dose
                + 0.04 * normal01(generator_seed, *key, "process", tick + 1)
            )
            latest_absolute = baseline + x + 0.05 * normal01(
                generator_seed, *key, "q0", tick + 1
            )
            events.append(
                _event(
                    kind=EventKind.OBSERVATION_AVAILABLE,
                    occurred_at=tick + 1,
                    collected_at=tick + 1,
                    available_at=tick + 1,
                    uid=_opaque_token(generator_seed, *key, "q0", tick + 1),
                    payload={"channel_id": "obs_0", "check_id": "Q0", "value": latest_absolute},
                )
            )
            if check_id is not None:
                if check_id == "Q1":
                    channel, value, noise = "obs_1", baseline, 0.04
                else:
                    channel, value, noise = "obs_2", x, 0.10
                measured = value + noise * normal01(
                    generator_seed, *key, "targeted-value", tick + 1
                )
                pending.append(
                    _event(
                        kind=EventKind.OBSERVATION_AVAILABLE,
                        occurred_at=tick + 1,
                        collected_at=tick + 1,
                        available_at=tick + 2,
                        uid=_opaque_token(generator_seed, *key, "targeted-result", tick),
                        payload={"channel_id": channel, "check_id": check_id, "value": measured},
                    )
                )
        events.extend(pending)
        history = _visible_history(events, self.catalog)
        future = []
        factual_utility = 0.0
        future_x = x
        for step in range(1, 9):
            future_x = self._RHO[c] * future_x + 0.08 + 0.04 * normal01(
                generator_seed, *key, "factual-future", step
            )
            future.append(
                {
                    "offset": step,
                    "deviation": future_x,
                    "absolute": baseline + future_x,
                }
            )
            factual_utility -= 0.97 ** (step - 1) * future_x * future_x
        diagnostic = f"C{c}{int(x >= 0.55)}"
        strata = ["iid_support"]
        shell_member = low_b >= 1.0 or high_b <= -1.0
        if split is WorldSplit.SEALED_TEST and shell_member:
            strata.append("boundary_tail")
        return PrivateEpisode(
            case_key=f"w09-private-{split.value}-{episode_index}",
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=history,
            hidden_state_at_cut={"baseline": baseline, "deviation": x},
            invariant_parameters={
                "c": c,
                "rho": self._RHO[c],
                "baseline_prior_range": [low_b, high_b],
            },
            diagnostic_target={label: float(label == diagnostic) for label in self.catalog.diagnostic_labels},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=factual_utility,
            oracle_anchor={
                "posterior_source": "public_history_only",
                "target_reference": "personal_baseline",
                "baseline_shell_member": shell_member,
                "split_strata": strata,
            },
        )

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        if episode.environment_key != self.environment_key:
            raise ProtocolViolation("episode belongs to a different world")
        recorded = episode.oracle_anchor.get("split_strata")
        if not isinstance(recorded, list) or any(type(item) is not str for item in recorded):
            raise ProtocolViolation("W09 episode lacks exact split strata")
        prior_range = episode.invariant_parameters.get("baseline_prior_range")
        if not isinstance(prior_range, list) or len(prior_range) != 2:
            raise ProtocolViolation("W09 episode lacks baseline support ledger")
        shell_member = float(prior_range[0]) >= 1.0 or float(prior_range[1]) <= -1.0
        strata = ["iid_support"]
        if episode.split is WorldSplit.SEALED_TEST and shell_member:
            strata.append("boundary_tail")
        strata = tuple(strata)
        allowed = {"iid_support", "boundary_tail"}
        if not strata or strata[0] != "iid_support" or set(strata) - allowed:
            raise ProtocolViolation("W09 split strata contradict the registry")
        if tuple(recorded) != strata:
            raise ProtocolViolation("W09 stored split stratum is stale")
        return strata

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ProtocolViolation("unsupported W09 horizon")
        return _unique_plans((
            _no_action(),
            _sequence((0, "A1", None)),
            _sequence((0, "A2", None)),
            _constant_plan("A1", horizon),
            _constant_plan("A2", horizon),
            _sequence((0, "Q1", {"rule": "posterior_deviation_dose"})),
            _sequence((0, "Q2", {"rule": "posterior_deviation_dose"})),
        ))

    def _prior_range(self, episode: PrivateEpisode) -> tuple[float, float]:
        # A scoring oracle is P(. | public history, query).  The split and the
        # realized shell flag are judge-private, so every candidate-visible
        # prefix is conditioned against the same declared population support.
        del episode
        return -1.25, 1.25

    def _posterior(self, episode: PrivateEpisode) -> list[dict[str, Any]]:
        if episode.public_history.catalog_digest != self.catalog.digest:
            raise ProtocolViolation("public history uses a different catalog")
        times = list(range(-4, 1))
        position = {tick: index for index, tick in enumerate(times)}
        actions: dict[int, float] = {}
        for event in episode.public_history.events:
            if event.kind is EventKind.PERFORMED_TREATMENT:
                action = event.payload.get("action_id")
                if action in self._DOSE:
                    actions[event.occurred_at] = self._DOSE[str(action)]
        observations = [
            event
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") in {"obs_0", "obs_1", "obs_2"}
            and event.collected_at in position
        ]
        y = np.asarray([float(event.payload["value"]) for event in observations])
        low_b, high_b = self._prior_range(episode)
        components = []
        log_weights = []
        for c, rho in enumerate(self._RHO):
            # [b, x_-4, ..., x_0]
            mean = np.zeros(6)
            covariance = np.zeros((6, 6))
            mean[0] = (low_b + high_b) / 2.0
            covariance[0, 0] = (high_b - low_b) ** 2 / 12.0
            mean[1] = 0.4
            covariance[1, 1] = 1.2**2 / 12.0
            for index, tick in enumerate(range(-4, 0), start=2):
                mean[index] = rho * mean[index - 1] + 0.08 - actions.get(tick, 0.0)
                covariance[index, :index] = rho * covariance[index - 1, :index]
                covariance[:index, index] = covariance[index, :index]
                covariance[index, index] = rho * rho * covariance[index - 1, index - 1] + 0.04**2
            design = np.zeros((len(observations), 6))
            noise = np.zeros((len(observations), len(observations)))
            for row, event in enumerate(observations):
                channel = event.payload["channel_id"]
                x_index = 1 + position[int(event.collected_at)]
                if channel == "obs_0":
                    design[row, 0] = 1.0
                    design[row, x_index] = 1.0
                    noise[row, row] = 0.05**2
                elif channel == "obs_1":
                    design[row, 0] = 1.0
                    noise[row, row] = 0.04**2
                else:
                    design[row, x_index] = 1.0
                    noise[row, row] = 0.10**2
            post_mean, post_cov, log_likelihood = _condition_gaussian(
                mean, covariance, design, y, noise
            )
            select = np.zeros((2, 6))
            select[0, 0] = 1.0
            select[1, -1] = 1.0
            components.append(
                {
                    "class": c,
                    "mean": select @ post_mean,
                    "covariance": select @ post_cov @ select.T,
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
            raise ProtocolViolation("policy is not in the W09 frozen policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        components = self._posterior(episode)
        actions = {
            action.offset: action.action_id
            for action in policy.actions
            if action.action_id in self._DOSE
        }
        checks = {
            action.offset: action.action_id
            for action in policy.actions
            if action.action_id in {"Q1", "Q2"}
        }
        per_component = []
        utility = 0.0
        diagnosis = {label: 0.0 for label in self.catalog.diagnostic_labels}
        for component in components:
            c = int(component["class"])
            weight = float(component["weight"])
            mean = np.asarray(component["mean"], dtype=float)
            covariance = np.asarray(component["covariance"], dtype=float)
            probability_high = 1.0 - _normal_cdf(
                0.55, float(mean[1]), float(covariance[1, 1])
            )
            diagnosis[f"C{c}0"] += weight * (1.0 - probability_high)
            diagnosis[f"C{c}1"] += weight * probability_high
            baseline_rows = []
            deviation_rows = []
            absolute_rows = []
            component_utility = 0.0
            for step in range(1, horizon + 1):
                action_id = actions.get(step - 1)
                dose = self._DOSE.get(action_id, 0.0)
                transition = np.asarray([[1.0, 0.0], [0.0, self._RHO[c]]])
                mean = transition @ mean + np.asarray([0.0, 0.08 - dose])
                covariance = transition @ covariance @ transition.T
                covariance[1, 1] += 0.04**2
                base_mean, x_mean = float(mean[0]), float(mean[1])
                base_var, x_var = float(covariance[0, 0]), float(covariance[1, 1])
                absolute_mean = base_mean + x_mean
                absolute_var = float(covariance[0, 0] + covariance[1, 1] + 2.0 * covariance[0, 1])
                baseline_rows.append((base_mean, base_var))
                deviation_rows.append((x_mean, x_var))
                absolute_rows.append((absolute_mean, absolute_var))
                check_id = checks.get(step - 1)
                check_cost = 0.06 if check_id == "Q1" else (0.10 if check_id == "Q2" else 0.0)
                action_cost = 0.05 if action_id == "A1" else (0.10 if action_id == "A2" else 0.0)
                component_utility -= 0.97 ** (step - 1) * (
                    x_var + x_mean * x_mean + action_cost + check_cost
                )
            utility += weight * component_utility
            per_component.append(
                {
                    "weight": weight,
                    "baseline": baseline_rows,
                    "deviation": deviation_rows,
                    "absolute": absolute_rows,
                }
            )
        weights = [item["weight"] for item in per_component]

        def rows(key: str, noise: float = 0.0) -> list[dict[str, float]]:
            answer = []
            for index in range(horizon):
                mean, variance = _mixture_moments(
                    weights,
                    [float(item[key][index][0]) for item in per_component],
                    [float(item[key][index][1]) + noise for item in per_component],
                )
                answer.append({"offset": index + 1, "mean": mean, "variance": variance})
            return answer

        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "obs_0": rows("absolute", 0.05**2),
                "obs_1": rows("baseline", 0.04**2),
                "obs_2": rows("deviation", 0.10**2),
            },
            latent_distribution={"baseline": rows("baseline"), "deviation": rows("deviation")},
            outcome_distribution={
                "expected_utility": utility,
                "diagnostic_posterior": diagnosis,
                "target_reference": "personal_baseline",
            },
            expected_utility=utility,
            numerical_diagnostics={
                "method": "analytic_static_dynamic_class_mixture",
                "posterior_source": "candidate_visible_history",
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
        """Independent information-form static/dynamic reference utility."""

        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the W09 frozen policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        del oracle_seed
        times = tuple(range(-4, 1))
        time_index = {tick: offset for offset, tick in enumerate(times)}
        factual_actions: dict[int, float] = {}
        for event in episode.public_history.events:
            if event.kind is EventKind.PERFORMED_TREATMENT:
                identifier = event.payload.get("action_id")
                if identifier in self._DOSE:
                    factual_actions[event.occurred_at] = self._DOSE[str(identifier)]
        observations = [
            event
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") in {"obs_0", "obs_1", "obs_2"}
            and event.collected_at in time_index
        ]
        observed = np.asarray(
            [float(event.payload["value"]) for event in observations], dtype=float
        )
        components: list[tuple[int, np.ndarray, np.ndarray]] = []
        log_weights: list[float] = []
        for class_index, rho in enumerate(self._RHO):
            prior_mean = np.zeros(6, dtype=float)
            prior_covariance = np.zeros((6, 6), dtype=float)
            prior_covariance[0, 0] = 2.5**2 / 12.0
            prior_mean[1] = 0.4
            prior_covariance[1, 1] = 1.2**2 / 12.0
            for offset, tick in enumerate(range(-4, 0), start=2):
                prior_mean[offset] = (
                    rho * prior_mean[offset - 1]
                    + 0.08
                    - factual_actions.get(tick, 0.0)
                )
                prior_covariance[offset, :offset] = (
                    rho * prior_covariance[offset - 1, :offset]
                )
                prior_covariance[:offset, offset] = prior_covariance[offset, :offset]
                prior_covariance[offset, offset] = (
                    rho * rho * prior_covariance[offset - 1, offset - 1]
                    + 0.04**2
                )
            design = np.zeros((len(observations), 6), dtype=float)
            noise = np.zeros((len(observations), len(observations)), dtype=float)
            for row, event in enumerate(observations):
                channel = event.payload["channel_id"]
                x_offset = 1 + time_index[int(event.collected_at)]
                if channel == "obs_0":
                    design[row, 0] = 1.0
                    design[row, x_offset] = 1.0
                    noise[row, row] = 0.05**2
                elif channel == "obs_1":
                    design[row, 0] = 1.0
                    noise[row, row] = 0.04**2
                else:
                    design[row, x_offset] = 1.0
                    noise[row, row] = 0.10**2
            posterior_mean, posterior_covariance, likelihood = (
                _reference_linear_condition(
                    prior_mean, prior_covariance, design, observed, noise
                )
            )
            selector = np.zeros((2, 6), dtype=float)
            selector[0, 0] = 1.0
            selector[1, -1] = 1.0
            components.append(
                (
                    class_index,
                    selector @ posterior_mean,
                    selector @ posterior_covariance @ selector.T,
                )
            )
            log_weights.append(math.log(0.5) + likelihood)
        weights = _reference_normalized_weights(log_weights)
        future_actions = {
            item.offset: item.action_id
            for item in policy.actions
            if item.action_id in self._DOSE
        }
        future_checks = {
            item.offset: item.action_id
            for item in policy.actions
            if item.action_id in {"Q1", "Q2"}
        }
        total_utility = 0.0
        for (class_index, mean, covariance), weight in zip(components, weights):
            component_utility = 0.0
            rho = self._RHO[class_index]
            for step in range(1, horizon + 1):
                offset = step - 1
                action_id = future_actions.get(offset)
                dose = self._DOSE.get(action_id, 0.0)
                mean = np.asarray(
                    [float(mean[0]), rho * float(mean[1]) + 0.08 - dose],
                    dtype=float,
                )
                transition = np.diag([1.0, rho])
                covariance = transition @ covariance @ transition.T
                covariance[1, 1] += 0.04**2
                action_cost = (
                    0.05 if action_id == "A1" else 0.10 if action_id == "A2" else 0.0
                )
                check_id = future_checks.get(offset)
                check_cost = (
                    0.06 if check_id == "Q1" else 0.10 if check_id == "Q2" else 0.0
                )
                component_utility -= 0.97**offset * (
                    float(covariance[1, 1])
                    + float(mean[1]) ** 2
                    + action_cost
                    + check_cost
                )
            total_utility += weight * component_utility
        return float(total_utility)

    def _translate_history(self, episode: PrivateEpisode, delta: float) -> PrivateEpisode:
        events = []
        for event in episode.public_history.events:
            payload = dict(event.payload)
            if payload.get("channel_id") in {"obs_0", "obs_1"}:
                payload["value"] = float(payload["value"]) + delta
            events.append(replace(event, payload=payload))
        return replace(
            episode,
            case_key="w09-private-interior-translation",
            public_history=_visible_history(events, self.catalog),
        )

    def probe_fixtures(
        self, generator_seed: int = 909
    ) -> dict[str, tuple[PrivateEpisode, PrivateEpisode]]:
        # Probe custody is part of the sealed cohort.  In particular, do not
        # recycle the same-seed TRAIN population stream as judge-only probes.
        # Search only the SEALED_TEST stream for a declared interior
        # approximate translation pair.
        base = self.generate_episode(WorldSplit.SEALED_TEST, generator_seed, 0)
        for index in range(64):
            candidate = self.generate_episode(
                WorldSplit.SEALED_TEST, generator_seed, index
            )
            b = float(candidate.hidden_state_at_cut["baseline"])
            if -0.4 <= b <= 0.4:
                translated = self._translate_history(candidate, 0.05)
                policies = self.policy_set(4)[:3]
                original_utility = [
                    self.counterfactual(candidate, policy, 4, 1).expected_utility
                    for policy in policies
                ]
                translated_utility = [
                    self.counterfactual(translated, policy, 4, 1).expected_utility
                    for policy in policies
                ]
                original_contrasts = [
                    value - original_utility[0] for value in original_utility[1:]
                ]
                translated_contrasts = [
                    value - translated_utility[0] for value in translated_utility[1:]
                ]
                # Only oracle-screened treatment contrasts enter the fixture.
                if max(
                    abs(left - right)
                    for left, right in zip(original_contrasts, translated_contrasts)
                ) <= 0.01:
                    base = candidate
                    translation_pair = (candidate, translated)
                    break
        else:
            translation_pair = (base, self._translate_history(base, 0.05))
        renamed = replace(
            base,
            case_key="w09-private-alpha-renamed",
            public_history=_alpha_rename(base.public_history, "w09-alpha"),
        )
        private_swap = replace(
            base,
            case_key="w09-private-decomposition-swap",
            hidden_state_at_cut={
                "baseline": float(base.hidden_state_at_cut["baseline"]) + 0.2,
                "deviation": float(base.hidden_state_at_cut["deviation"]) - 0.2,
            },
        )

        def same_absolute(side: str, high_deviation: bool) -> PrivateEpisode:
            events = []
            baseline_value = 0.20 if high_deviation else 0.80
            for tick in range(-4, 1):
                absolute = 1.00
                events.append(
                    _event(
                        kind=EventKind.OBSERVATION_AVAILABLE,
                        occurred_at=tick,
                        collected_at=tick,
                        available_at=tick,
                        uid=hashlib.sha256(f"{side}:q0:{tick}".encode()).hexdigest()[:32],
                        payload={"channel_id": "obs_0", "check_id": "Q0", "value": absolute},
                    )
                )
            events.append(
                _event(
                    kind=EventKind.OBSERVATION_AVAILABLE,
                    occurred_at=-2,
                    collected_at=-2,
                    available_at=-1,
                    uid=hashlib.sha256(f"{side}:q1".encode()).hexdigest()[:32],
                    payload={"channel_id": "obs_1", "check_id": "Q1", "value": baseline_value},
                )
            )
            return replace(
                base,
                case_key=f"w09-private-same-absolute-{side}",
                public_history=_visible_history(events, self.catalog),
                hidden_state_at_cut={"baseline": baseline_value, "deviation": 1.0 - baseline_value},
            )

        return {
            "same_absolute_collision": (
                same_absolute("high-deviation", True),
                same_absolute("low-deviation", False),
            ),
            "interior_translation": translation_pair,
            "identical_prefix_private_decomposition": (base, private_swap),
            "false_split_alpha_rename": (base, renamed),
        }


__all__ = ["World09"]
