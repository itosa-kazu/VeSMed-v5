"""W10: multiple observed channels share one latent specimen disturbance."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import math
from typing import Any

import numpy as np

from ..canonical import ProtocolViolation, canonical_json_bytes, digest_json
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
from .randomness import categorical, normal01, uniform01
from .w06 import (
    _alpha_rename,
    _condition_gaussian,
    _constant_plan,
    _event,
    _mixture_moments,
    _mixed_categorical,
    _no_action,
    _opaque_token,
    _sequence,
    _softmax,
    _validate_episode_request,
    _visible_history,
    _unique_plans,
)


# Primitive-polynomial direction parameters for the first ten Sobol dimensions.
# Tuple format is (degree s, coefficient a, initial odd m values).
_SOBOL_PARAMETERS: dict[int, tuple[int, int, tuple[int, ...]]] = {
    2: (1, 0, (1,)),
    3: (2, 1, (1, 3)),
    4: (3, 1, (1, 3, 1)),
    5: (3, 2, (1, 1, 1)),
    6: (4, 1, (1, 3, 5, 13)),
    7: (4, 4, (1, 1, 5, 5)),
    8: (5, 2, (1, 3, 3, 9, 7)),
    9: (5, 4, (1, 1, 3, 11, 13)),
    10: (5, 7, (1, 1, 5, 1, 15)),
}


def _sobol_direction_numbers(dimension: int, bits: int = 32) -> np.ndarray:
    if dimension == 1:
        return np.asarray([0] + [1 << (bits - index) for index in range(1, bits + 1)], dtype=np.uint32)
    s, a, initial = _SOBOL_PARAMETERS[dimension]
    values = np.zeros(bits + 1, dtype=np.uint32)
    for index in range(1, s + 1):
        values[index] = np.uint32(initial[index - 1] << (bits - index))
    for index in range(s + 1, bits + 1):
        value = int(values[index - s]) ^ (int(values[index - s]) >> s)
        for offset in range(1, s):
            if (a >> (s - 1 - offset)) & 1:
                value ^= int(values[index - offset])
        values[index] = np.uint32(value)
    return values


def _sobol_integers(dimension: int, count: int) -> np.ndarray:
    directions = _sobol_direction_numbers(dimension)
    answer = np.zeros(count, dtype=np.uint32)
    current = 0
    for index in range(1, count):
        direction = (index & -index).bit_length()
        current ^= int(directions[direction])
        answer[index] = np.uint32(current)
    return answer


def _seed64(master_seed: int, *parts: int) -> int:
    payload = canonical_json_bytes([master_seed, *parts])
    return int.from_bytes(
        hashlib.sha256(b"UCM_OWEN_SCRAMBLE_V1\0" + payload).digest()[:8], "big"
    )


def _nested_owen_scramble(
    values: np.ndarray, master_seed: int, replicate: int, dimension: int, bits: int
) -> np.ndarray:
    """Base-2 nested uniform scramble indexed by each original-bit prefix."""

    source = values >> np.uint32(32 - bits)
    prefix = np.zeros(source.shape[0], dtype=np.uint32)
    output = np.zeros(source.shape[0], dtype=np.uint32)
    for depth in range(bits):
        rng = np.random.Generator(
            np.random.PCG64DXSM(_seed64(master_seed, replicate, dimension, depth))
        )
        flips = rng.integers(0, 2, size=1 << depth, dtype=np.uint8)
        bit = ((source >> np.uint32(bits - 1 - depth)) & np.uint32(1)).astype(np.uint8)
        scrambled = bit ^ flips[prefix]
        output = (output << np.uint32(1)) | scrambled.astype(np.uint32)
        prefix = (prefix << np.uint32(1)) | bit.astype(np.uint32)
    return output


def _normal_ppf(probability: np.ndarray) -> np.ndarray:
    """Vectorized Acklam inverse-normal approximation (absolute error < 2e-9)."""

    a = np.asarray(
        [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    )
    b = np.asarray(
        [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    )
    c = np.asarray(
        [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    )
    d = np.asarray(
        [7.784695709041462e-03, 3.224671290700398e-01,
         2.445134137142996e00, 3.754408661907416e00]
    )
    p = np.asarray(probability, dtype=float)
    result = np.empty_like(p)
    low = p < 0.02425
    high = p > 1.0 - 0.02425
    middle = ~(low | high)
    q = np.sqrt(-2.0 * np.log(p[low]))
    result[low] = (
        (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    )
    q = np.sqrt(-2.0 * np.log(1.0 - p[high]))
    result[high] = -(
        (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5])
        / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    )
    q = p[middle] - 0.5
    r = q * q
    result[middle] = (
        (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5])
        * q
        / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    )
    return result


def _owen_sobol_normals(
    master_seed: int, replicate: int, dimension: int, bits: int = 14
) -> np.ndarray:
    if not 1 <= dimension <= 10:
        raise ProtocolViolation("W10 Sobol dimension is outside the frozen table")
    count = 1 << bits
    columns = []
    for coordinate in range(1, dimension + 1):
        base = _sobol_integers(coordinate, count)
        scrambled = _nested_owen_scramble(
            base, master_seed, replicate, coordinate, bits
        )
        probability = (scrambled.astype(float) + 0.5) / count
        columns.append(_normal_ppf(probability))
    return np.column_stack(columns)


class World10(MicroWorld):
    """One mechanism, correlated specimen shock, and conditionally noisy sensors."""

    _RHO = (0.82, 0.96)
    _DOSE = {"A1": 0.35, "A2": 0.65}
    _LOADINGS = np.asarray([1.0, 0.8, 1.2], dtype=float)

    def __init__(self) -> None:
        self._catalog = PublicCatalog(
            observations=(
                ChannelSpec("obs_0"),
                ChannelSpec("obs_1"),
                ChannelSpec("obs_2"),
            ),
            actions=(ActionSpec("A1", cost=0.05), ActionSpec("A2", cost=0.12)),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.02),
                CheckSpec("Q1", ("obs_0", "obs_1", "obs_2"), (1, 1), cost=0.05),
                CheckSpec("Q2", ("obs_0",), (1, 1), cost=0.10),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )
        self._oracle_cache: dict[str, CounterfactualOracle] = {}

    @property
    def environment_key(self) -> str:
        return "ucm-benchmark-private-w10-v1"

    @property
    def catalog(self) -> PublicCatalog:
        return self._catalog

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        _validate_episode_request(split, generator_seed, episode_index)
        key = ("episode", episode_index, split.value)
        c = categorical((0.5, 0.5), generator_seed, *key, "class")
        x = 1.2 * uniform01(generator_seed, *key, "initial-x")
        events = []
        pending = []
        propensities: list[dict[str, Any]] = []
        latest_mean = 0.0
        for tick in range(-4, 0):
            arrived = [
                event
                for event in pending
                if event.available_at == tick
                and event.kind is EventKind.OBSERVATION_AVAILABLE
            ]
            if arrived:
                latest_mean = math.fsum(float(event.payload["value"]) for event in arrived) / len(arrived)
            action_probabilities = _mixed_categorical(
                _softmax((0.3, 0.8 * latest_mean, 1.2 * (latest_mean - 0.7)))
            )
            action_choice = categorical(
                action_probabilities, generator_seed, *key, "behavior-action", tick
            )
            action_id = (None, "A1", "A2")[action_choice]
            q1_probability = 0.30 + 0.15 / (1.0 + math.exp(-(latest_mean - 0.5)))
            check_probabilities = _mixed_categorical(
                (0.45, q1_probability, max(0.0, 1.0 - 0.45 - q1_probability))
            )
            check_choice = categorical(
                check_probabilities, generator_seed, *key, "behavior-check", tick
            )
            check_id = ("Q0", "Q1", "Q2")[check_choice]
            propensities.append(
                {
                    "tick": tick,
                    "action": {
                        "NoNewAction": action_probabilities[0],
                        "A1": action_probabilities[1],
                        "A2": action_probabilities[2],
                    },
                    "check": {
                        "Q0": check_probabilities[0],
                        "Q1": check_probabilities[1],
                        "Q2": check_probabilities[2],
                    },
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
                + 0.10
                - dose
                + 0.055 * normal01(generator_seed, *key, "process", tick + 1)
            )
            delay = 0 if check_id == "Q0" else 1
            collection_tick = tick + 1
            if check_id == "Q0":
                specimen = _opaque_token(generator_seed, *key, "specimen", tick, 0)
                shock = 0.25 * normal01(generator_seed, *key, "shock", tick, 0)
                values = [(0, x + shock + 0.06 * normal01(generator_seed, *key, "sensor", tick, 0))]
                specimens = [specimen]
            elif check_id == "Q1":
                specimen = _opaque_token(generator_seed, *key, "specimen", tick, 0)
                shock = 0.25 * normal01(generator_seed, *key, "shock", tick, 0)
                values = [
                    (
                        slot,
                        float(self._LOADINGS[slot] * x + shock)
                        + 0.06 * normal01(generator_seed, *key, "sensor", tick, slot),
                    )
                    for slot in range(3)
                ]
                specimens = [specimen] * 3
            else:
                values = []
                specimens = []
                for replicate in range(2):
                    specimen = _opaque_token(generator_seed, *key, "specimen", tick, replicate)
                    shock = 0.25 * normal01(generator_seed, *key, "shock", tick, replicate)
                    values.append(
                        (
                            0,
                            x
                            + shock
                            + 0.06 * normal01(generator_seed, *key, "sensor", tick, replicate),
                        )
                    )
                    specimens.append(specimen)
            for ordinal, ((slot, value), specimen) in enumerate(zip(values, specimens)):
                pending.append(
                    _event(
                        kind=EventKind.OBSERVATION_AVAILABLE,
                        occurred_at=collection_tick,
                        collected_at=collection_tick,
                        available_at=collection_tick + delay,
                        uid=_opaque_token(generator_seed, *key, "result", tick, ordinal),
                        payload={
                            "channel_id": f"obs_{slot}",
                            "check_id": check_id,
                            "assay_slot": slot,
                            "specimen_uid": specimen,
                            "value": value,
                        },
                    )
                )
        events.extend(pending)
        history = _visible_history(events, self.catalog)
        future = []
        future_x = x
        factual_utility = 0.0
        crossed = False
        for step in range(1, 9):
            future_x = self._RHO[c] * future_x + 0.10 + 0.055 * normal01(
                generator_seed, *key, "factual-future", step
            )
            crossed = crossed or future_x > 0.9
            future.append({"offset": step, "mechanism": future_x, "crossed": crossed})
            factual_utility -= 0.97 ** (step - 1) * future_x * future_x
        factual_utility -= 1.5 * float(crossed)
        return PrivateEpisode(
            case_key=f"w10-private-{split.value}-{episode_index}",
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=history,
            hidden_state_at_cut={"mechanism": x},
            invariant_parameters={"c": c, "rho": self._RHO[c]},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=factual_utility,
            oracle_anchor={
                "posterior_source": "public_history_only",
                "specimen_covariance": "shared_rank_one_plus_sensor_diagonal",
            },
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ProtocolViolation("unsupported W10 horizon")
        return _unique_plans((
            _no_action(),
            _sequence((0, "A1", None)),
            _sequence((0, "A2", None)),
            _constant_plan("A1", horizon),
            _constant_plan("A2", horizon),
            _sequence((0, "Q1", {"rule": "tail_probability_dose"})),
            _sequence((0, "Q2", {"rule": "tail_probability_dose"})),
        ))

    def _posterior(self, episode: PrivateEpisode) -> list[dict[str, float]]:
        if episode.environment_key != self.environment_key:
            raise ProtocolViolation("episode belongs to a different world")
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
        components = []
        log_weights = []
        for c, rho in enumerate(self._RHO):
            mean = np.zeros(5)
            covariance = np.zeros((5, 5))
            mean[0] = 0.6
            covariance[0, 0] = 1.2**2 / 12.0
            for index, tick in enumerate(range(-4, 0), start=1):
                mean[index] = rho * mean[index - 1] + 0.10 - actions.get(tick, 0.0)
                covariance[index, :index] = rho * covariance[index - 1, :index]
                covariance[:index, index] = covariance[index, :index]
                covariance[index, index] = rho * rho * covariance[index - 1, index - 1] + 0.055**2
            design = np.zeros((len(observations), 5))
            noise = np.zeros((len(observations), len(observations)))
            groups: list[str] = []
            for row, event in enumerate(observations):
                slot = int(event.payload.get("assay_slot", int(str(event.payload["channel_id"])[-1])))
                design[row, position[int(event.collected_at)]] = self._LOADINGS[slot]
                groups.append(str(event.payload.get("specimen_uid", event.event_uid)))
                noise[row, row] = 0.25**2 + 0.06**2
            for left in range(len(observations)):
                for right in range(left + 1, len(observations)):
                    if groups[left] == groups[right]:
                        noise[left, right] = noise[right, left] = 0.25**2
            post_mean, post_cov, log_likelihood = _condition_gaussian(
                mean, covariance, design, y, noise
            )
            components.append(
                {
                    "class": float(c),
                    "mean": float(post_mean[-1]),
                    "variance": float(max(post_cov[-1, -1], 0.0)),
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

    def _tail_probability(
        self,
        components: list[dict[str, float]],
        action_by_offset: dict[int, str],
        horizon: int,
        oracle_seed: int,
    ) -> tuple[float, float, list[float]]:
        replicate_estimates = []
        for replicate in range(16):
            normals = _owen_sobol_normals(
                oracle_seed, replicate, horizon + 1, bits=14
            )
            mixture_probability = 0.0
            for component in components:
                c = int(component["class"])
                paths = component["mean"] + math.sqrt(component["variance"]) * normals[:, 0]
                maximum = np.full(paths.shape, -np.inf)
                for step in range(1, horizon + 1):
                    dose = self._DOSE.get(action_by_offset.get(step - 1), 0.0)
                    paths = self._RHO[c] * paths + 0.10 - dose + 0.055 * normals[:, step]
                    maximum = np.maximum(maximum, paths)
                mixture_probability += float(component["weight"]) * float(np.mean(maximum > 0.9))
            replicate_estimates.append(mixture_probability)
        estimate = math.fsum(replicate_estimates) / len(replicate_estimates)
        standard_deviation = float(np.std(np.asarray(replicate_estimates), ddof=1))
        # t_0.995,15 = 2.9467; replicate-level variance is the valid RQMC error estimate.
        half_width = 2.9467 * standard_deviation / math.sqrt(16.0)
        return estimate, half_width, replicate_estimates

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the W10 frozen policy set")
        if type(oracle_seed) is not int or oracle_seed < 0 or oracle_seed >= 2**128:
            raise ProtocolViolation("oracle_seed must be an unsigned 128-bit integer")
        cache_key = digest_json(
            {
                "history": episode.public_history.digest,
                "policy": policy.to_wire(),
                "horizon": horizon,
                "oracle_seed": oracle_seed,
            }
        )
        cached = self._oracle_cache.get(cache_key)
        if cached is not None:
            return cached
        components = self._posterior(episode)
        actions = {
            action.offset: action.action_id
            for action in policy.actions
            if action.action_id in self._DOSE
        }
        checks = [
            action.action_id
            for action in policy.actions
            if action.action_id in {"Q0", "Q1", "Q2"}
        ]
        per_component = []
        analytic_utility = 0.0
        for component in components:
            c = int(component["class"])
            mean = component["mean"]
            variance = component["variance"]
            rows = []
            component_utility = 0.0
            for step in range(1, horizon + 1):
                action_id = actions.get(step - 1)
                dose = self._DOSE.get(action_id, 0.0)
                mean = self._RHO[c] * mean + 0.10 - dose
                variance = self._RHO[c] ** 2 * variance + 0.055**2
                rows.append((mean, variance))
                action_cost = 0.05 if action_id == "A1" else (0.12 if action_id == "A2" else 0.0)
                component_utility -= 0.97 ** (step - 1) * (
                    variance + mean * mean + action_cost
                )
            analytic_utility += component["weight"] * component_utility
            per_component.append({"weight": component["weight"], "mechanism": rows})
        analytic_utility -= math.fsum(
            0.02 if check == "Q0" else (0.05 if check == "Q1" else 0.10)
            for check in checks
        )
        tail_probability, half_width, replicates = self._tail_probability(
            components, actions, horizon, oracle_seed
        )
        expected_utility = analytic_utility - 1.5 * tail_probability
        weights = [float(item["weight"]) for item in per_component]
        mechanism_rows = []
        panel_rows = []
        shared_covariance = (
            0.25**2 * np.ones((3, 3)) + 0.06**2 * np.eye(3)
        )
        for index in range(horizon):
            mean, variance = _mixture_moments(
                weights,
                [float(item["mechanism"][index][0]) for item in per_component],
                [float(item["mechanism"][index][1]) for item in per_component],
            )
            mechanism_rows.append({"offset": index + 1, "mean": mean, "variance": variance})
            panel_rows.append(
                {
                    "offset": index + 1,
                    "mean": [float(value * mean) for value in self._LOADINGS],
                    "conditional_covariance": shared_covariance.tolist(),
                }
            )
        diagnosis = {
            f"C{int(component['class'])}": component["weight"]
            for component in components
        }
        answer = CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "mechanism_marginal": mechanism_rows,
                "same_specimen_panel": panel_rows,
            },
            latent_distribution={"shared_mechanism": mechanism_rows},
            outcome_distribution={
                "expected_utility": expected_utility,
                "diagnostic_posterior": diagnosis,
                "first_crossing_probability": tail_probability,
            },
            expected_utility=expected_utility,
            numerical_diagnostics={
                "method": "nested_owen_scrambled_sobol_base2",
                "replicates": 16,
                "points_per_replicate": 16384,
                "ci99_half_width": half_width,
                "ci99_requirement_met": half_width < 0.005,
                "replicate_estimates": replicates,
                "posterior_source": "candidate_visible_history",
            },
        )
        self._oracle_cache[cache_key] = answer
        return answer

    def _panel_episode(
        self,
        base: PrivateEpisode,
        name: str,
        values: np.ndarray,
        specimens: tuple[str, str, str],
    ) -> PrivateEpisode:
        events = []
        for slot in range(3):
            events.append(
                _event(
                    kind=EventKind.OBSERVATION_AVAILABLE,
                    occurred_at=0,
                    collected_at=0,
                    available_at=0,
                    uid=hashlib.sha256(f"{name}:{slot}".encode()).hexdigest()[:32],
                    payload={
                        "channel_id": f"obs_{slot}",
                        "check_id": "Q1",
                        "assay_slot": slot,
                        "specimen_uid": specimens[slot],
                        "value": float(values[slot]),
                    },
                )
            )
        return replace(
            base,
            case_key=f"w10-private-{name}",
            public_history=_visible_history(events, self.catalog),
        )

    def probe_fixtures(
        self, generator_seed: int = 1010
    ) -> dict[str, tuple[PrivateEpisode, PrivateEpisode]]:
        base = self.generate_episode(WorldSplit.SEALED_TEST, generator_seed, 0)
        values = np.asarray([0.75, 0.60, 0.90])
        same_uid = hashlib.sha256(b"w10-same-specimen").hexdigest()[:32]
        grouped = self._panel_episode(base, "grouped", values, (same_uid,) * 3)
        independent = self._panel_episode(
            base,
            "independent",
            values,
            tuple(
                hashlib.sha256(f"w10-independent:{slot}".encode()).hexdigest()[:32]
                for slot in range(3)
            ),
        )
        sigma = 0.25**2 * np.ones((3, 3)) + 0.06**2 * np.eye(3)
        information_direction = np.linalg.solve(sigma, self._LOADINGS)
        null = np.asarray([information_direction[1], -information_direction[0], 0.0])
        null *= 0.12 / np.linalg.norm(null)
        null_left = self._panel_episode(base, "null-left", values, (same_uid,) * 3)
        null_right = self._panel_episode(base, "null-right", values + null, (same_uid,) * 3)
        renamed = replace(
            base,
            case_key="w10-private-alpha-renamed",
            public_history=_alpha_rename(base.public_history, "w10-alpha"),
        )
        return {
            "same_values_different_grouping": (grouped, independent),
            "posterior_equivalent_nullspace": (null_left, null_right),
            "false_split_alpha_rename": (base, renamed),
        }


__all__ = ["World10"]
