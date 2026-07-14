"""W13: nonlinear comorbidity interactions (synergy, antagonism, threshold)."""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from ..canonical import ProtocolViolation
from ..schema import ActionPlan
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
    _mixed_categorical,
    _softmax,
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


class World13(MicroWorld):
    """Two mechanisms interact through one of three nonlinear laws."""

    def __init__(self) -> None:
        self._catalog = PublicCatalog(
            observations=(
                ChannelSpec("obs_0"),
                ChannelSpec("obs_1"),
                ChannelSpec("obs_2"),
            ),
            actions=(
                ActionSpec("A1", cost=0.05),
                ActionSpec("A2", cost=0.05),
                ActionSpec("A3", cost=0.10),
            ),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.08),
                CheckSpec("Q2", ("obs_2",), (1, 1), cost=0.10),
            ),
            diagnostic_labels=("C0", "C1", "C2"),
            horizons=(1, 4, 8),
        )

    @property
    def environment_key(self) -> str:
        return "ucm-benchmark-private-w13-v1"

    @property
    def catalog(self) -> PublicCatalog:
        return self._catalog

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ProtocolViolation("unsupported horizon")
        return _finite_policy_set(
            horizon,
            treatments=("A1", "A2", "A3"),
            checks=("Q1", "Q2"),
        )

    @staticmethod
    def _phi(c: int, x0: float, x1: float) -> float:
        if c == 0:
            return 0.70 * x0 * x1
        if c == 1:
            return -0.35 * min(x0, x1)
        return max(x0 * x1 - 0.36, 0.0)

    @classmethod
    def _step(
        cls,
        c: int,
        x0: float,
        x1: float,
        action: str | None,
        noise0: float = 0.0,
        noise1: float = 0.0,
    ) -> tuple[float, float]:
        z = cls._phi(c, x0, x1)
        targets0 = action in {"A1", "A3"}
        targets1 = action in {"A2", "A3"}
        next0 = 0.88 * x0 + 0.06 + 0.12 * z - 0.35 * targets0 + noise0
        next1 = 0.84 * x1 + 0.08 + 0.12 * z - 0.35 * targets1 + noise1
        return min(1.5, max(0.0, next0)), min(1.5, max(0.0, next1))

    @staticmethod
    def _behavior(y: float) -> tuple[float, float, float, float]:
        return _mixed_categorical(
            _softmax((0.3, 0.7 * y, 0.7 * y, 1.0 * (y - 0.8)))
        )

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        _validate_episode_request(split, generator_seed, episode_index)
        key: tuple[str | int, ...] = ("w13", split.value, episode_index)
        c = (episode_index + int(split is WorldSplit.VALIDATION)) % 3
        if split is WorldSplit.SEALED_TEST and episode_index % 5 == 0:
            # Alternate immediately below/above the threshold while keeping
            # all marginal coordinate ranges already present in training.
            if (episode_index // 5) % 2:
                x0, x1 = 0.80, 0.50  # product .40
            else:
                root = math.sqrt(0.33)
                x0, x1 = (1.30 + root) / 2.0, (1.30 - root) / 2.0
            c = 2
            stratum = "threshold-shell"
        else:
            x0 = 0.08 + 1.22 * uniform01(generator_seed, *key, "x0")
            x1 = 0.08 + 1.22 * uniform01(generator_seed, *key, "x1")
            stratum = (
                "sealed-heldout-combination-cell"
                if split is WorldSplit.SEALED_TEST
                else "validation-combination-cell"
                if split is WorldSplit.VALIDATION
                else "train-combination-cell"
            )
        events: list[Any] = []
        propensities: list[dict[str, Any]] = []

        for tick in range(-3, 1):
            z = self._phi(c, x0, x1)
            y = x0 + x1 + 0.05 * normal01(generator_seed, *key, "q0", tick)
            events.append(_observation(generator_seed, key, "obs_0", y, tick))
            if tick == 0:
                break
            p_q1 = 0.15
            p_q2 = 0.15 + 0.20 / (1.0 + math.exp(-(abs(y - 0.8))))
            take_q1 = bernoulli(p_q1, generator_seed, *key, "q1-take", tick)
            take_q2 = bernoulli(p_q2, generator_seed, *key, "q2-take", tick)
            if take_q1:
                # Q1 is a component-resolving panel represented as a scalar
                # contrast; its clinical semantics are in the public catalog.
                events.append(
                    _observation(
                        generator_seed,
                        key,
                        "obs_1",
                        x0 - x1 + 0.08 * normal01(generator_seed, *key, "q1", tick),
                        tick,
                        delay=1,
                    )
                )
            if take_q2:
                events.append(
                    _observation(
                        generator_seed,
                        key,
                        "obs_2",
                        z + 0.07 * normal01(generator_seed, *key, "q2", tick),
                        tick,
                        delay=1,
                    )
                )
            probabilities = self._behavior(y)
            choice = categorical(
                probabilities, generator_seed, *key, "behavior", tick
            )
            action = (None, "A1", "A2", "A3")[choice]
            propensities.append(
                {
                    "decision_at": tick,
                    "probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                        "A2": probabilities[2],
                        "A3": probabilities[3],
                    },
                    "selected": "NoNewAction" if action is None else action,
                    "check_probabilities": {"Q1": p_q1, "Q2": p_q2},
                }
            )
            if action is not None:
                events.append(_treatment(generator_seed, key, action, tick))
            x0, x1 = self._step(
                c,
                x0,
                x1,
                action,
                0.03 * normal01(generator_seed, *key, "process", tick, 0),
                0.03 * normal01(generator_seed, *key, "process", tick, 1),
            )

        state_at_cut = (x0, x1)
        future: list[dict[str, Any]] = []
        utility = 0.0
        for offset in range(4):
            probabilities = self._behavior(x0 + x1)
            choice = categorical(
                probabilities, generator_seed, *key, "future-action", offset
            )
            action = (None, "A1", "A2", "A3")[choice]
            x0, x1 = self._step(
                c,
                x0,
                x1,
                action,
                0.03 * normal01(generator_seed, *key, "future-process", offset, 0),
                0.03 * normal01(generator_seed, *key, "future-process", offset, 1),
            )
            z = self._phi(c, x0, x1)
            dose_count = 2 if action == "A3" else int(action is not None)
            utility -= 0.97**offset * ((x0 + x1 + z) ** 2 + 0.05 * dose_count)
            future.append(
                {
                    "offset": offset + 1,
                    "observations": {"obs_0": x0 + x1, "obs_2": z},
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
            hidden_state_at_cut={"components": [state_at_cut[0], state_at_cut[1]]},
            invariant_parameters={"interaction_class": c},
            diagnostic_target={f"C{i}": float(i == c) for i in range(3)},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=float(utility),
            oracle_anchor={
                "stratum": stratum,
                "oracle_family": "nonlinear-grid",
                "probe_attribution": "candidate-attributable",
            },
        )

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        """Map W13's preallocated interaction cells to registry strata.

        Membership uses the generator cell and split only.  It never infers a
        stratum from ``interaction_class`` or the realized hidden components.
        Explicit pair fixtures remain probe-cohort rows and therefore receive
        only the universal IID-support tag here.
        """

        if type(episode) is not PrivateEpisode or episode.environment_key != self.environment_key:
            raise ProtocolViolation("W13 strata require a W13 PrivateEpisode")
        strata = ["iid_support"]
        cell = episode.oracle_anchor.get("stratum")
        if episode.oracle_anchor.get("fixture") == "paired":
            if cell is not None or episode.factual_future or episode.action_propensities:
                raise ProtocolViolation("W13 pair fixture has population material")
            return tuple(strata)

        allowed = {
            WorldSplit.TRAIN: {"train-combination-cell"},
            WorldSplit.VALIDATION: {"validation-combination-cell"},
            WorldSplit.SEALED_TEST: {
                "threshold-shell",
                "sealed-heldout-combination-cell",
            },
        }[episode.split]
        if cell not in allowed:
            raise ProtocolViolation("W13 episode lacks a valid generator-cell witness")
        if cell == "threshold-shell":
            strata.append("boundary_tail")
        if cell == "threshold-shell":
            strata.append("compositional_holdout")
        return tuple(strata)

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the finite W13 policy set")
        if type(oracle_seed) is not int or oracle_seed < 0:
            raise ProtocolViolation("oracle_seed must be non-negative")
        del oracle_seed
        particles = self._public_posterior(episode)
        utility = 0.0
        latent_steps: list[dict[str, Any]] = []
        observed_steps: list[dict[str, Any]] = []
        working = [(c, x0, x1, weight) for c, x0, x1, weight in particles]
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = next((name for name in ("A3", "A1", "A2") if name in ids), None)
            working = [
                (c, *self._step(c, x0, x1, action), weight)
                for c, x0, x1, weight in working
            ]
            dose_count = 2 if action == "A3" else int(action is not None)
            check_cost = 0.08 * float("Q1" in ids) + 0.10 * float("Q2" in ids)
            expected_burden = math.fsum(
                weight * (x0 + x1 + self._phi(c, x0, x1)) ** 2
                for c, x0, x1, weight in working
            )
            utility -= 0.97**offset * (
                expected_burden + 2.0 * 0.03**2
                + 0.05 * dose_count + check_cost
            )
            mean0 = math.fsum(weight * x0 for _, x0, _, weight in working)
            mean1 = math.fsum(weight * x1 for _, _, x1, weight in working)
            mean_z = math.fsum(
                weight * self._phi(c, x0, x1)
                for c, x0, x1, weight in working
            )
            latent_steps.append(
                {
                    "offset": offset + 1,
                    "component_mean": [mean0, mean1],
                    "interaction_mean": mean_z,
                }
            )
            observed_steps.append(
                {
                    "offset": offset + 1,
                    "obs_0_mean": mean0 + mean1,
                    "obs_1_mean": mean0 - mean1,
                    "obs_2_mean": mean_z,
                }
            )
        class_probabilities = {
            f"C{i}": math.fsum(
                weight for c, _, _, weight in particles if c == i
            )
            for i in range(3)
        }
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "nonlinear-moment-rollout",
                "steps": observed_steps,
            },
            latent_distribution={
                "family": "interaction-state",
                "steps": latent_steps,
                "diagnostic_posterior": class_probabilities,
            },
            outcome_distribution={
                "utility_family": "nonlinear-joint-burden",
                "expected_utility": float(utility),
            },
            expected_utility=float(utility),
            numerical_diagnostics={
                "method": "public-history-class-component-grid",
                "reference_method": "sum-difference-midpoint-quadrature",
                "absolute_error_bound": 0.04,
                "posterior_fork": "single-public-posterior",
                "private_state_used": False,
            },
        )

    @classmethod
    def _public_posterior(
        cls, episode: PrivateEpisode
    ) -> tuple[tuple[int, float, float, float], ...]:
        totals = _channel_rows(episode, "obs_0")
        if not totals:
            raise ProtocolViolation("W13 requires public obs_0")
        y0 = totals[-1][1]
        contrasts = _channel_rows(episode, "obs_1")
        interactions = _channel_rows(episode, "obs_2")
        y1 = contrasts[-1][1] if contrasts else None
        y2 = interactions[-1][1] if interactions else None
        upper = 1.5
        rows: list[tuple[tuple[Any, ...], float]] = []
        for c in range(3):
            for i in range(21):
                x0 = upper * i / 20.0
                for j in range(21):
                    x1 = upper * j / 20.0
                    score = _normal_log_likelihood(y0, x0 + x1, 0.09)
                    if y1 is not None:
                        score += _normal_log_likelihood(y1, x0 - x1, 0.13)
                    if y2 is not None:
                        score += _normal_log_likelihood(
                            y2, cls._phi(c, x0, x1), 0.11
                        )
                    rows.append(((c, x0, x1), score))
        return _normalise_log_particles(rows)  # type: ignore[return-value]

    def reference_counterfactual(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> float:
        """Independent sum/difference midpoint enumerator with inline dynamics."""

        if policy not in self.policy_set(horizon):
            raise ProtocolViolation("policy is not in the finite W13 policy set")
        totals = _channel_rows(episode, "obs_0")
        if not totals:
            raise ProtocolViolation("W13 reference requires obs_0")
        y0 = totals[-1][1]
        contrasts = _channel_rows(episode, "obs_1")
        interactions = _channel_rows(episode, "obs_2")
        y1 = contrasts[-1][1] if contrasts else None
        y2 = interactions[-1][1] if interactions else None

        def ref_phi(c: int, a: float, b: float) -> float:
            if c == 0:
                return 0.70 * a * b
            if c == 1:
                return -0.35 * min(a, b)
            return max(a * b - 0.36, 0.0)

        raw: list[tuple[int, float, float, float]] = []
        for c in range(3):
            for si in range(50):
                total = 3.0 * (si + 0.5) / 50.0
                for di in range(50):
                    contrast = -1.5 + 3.0 * (di + 0.5) / 50.0
                    x0 = 0.5 * (total + contrast)
                    x1 = 0.5 * (total - contrast)
                    if not (0.0 <= x0 <= 1.5 and 0.0 <= x1 <= 1.5):
                        continue
                    score = _normal_log_likelihood(y0, total, 0.09)
                    if y1 is not None:
                        score += _normal_log_likelihood(y1, contrast, 0.13)
                    if y2 is not None:
                        score += _normal_log_likelihood(y2, ref_phi(c, x0, x1), 0.11)
                    raw.append((c, x0, x1, score))
        peak = max(row[3] for row in raw)
        weighted = [
            (c, x0, x1, math.exp(max(-745.0, score - peak)))
            for c, x0, x1, score in raw
        ]
        norm = math.fsum(row[3] for row in weighted)
        particles = [(c, x0, x1, w / norm) for c, x0, x1, w in weighted]
        utility = 0.0
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = next((name for name in ("A3", "A1", "A2") if name in ids), None)
            next_rows = []
            for c, x0, x1, weight in particles:
                z = ref_phi(c, x0, x1)
                n0 = min(1.5, max(0.0, 0.88 * x0 + 0.06 + 0.12 * z - 0.35 * float(action in {"A1", "A3"})))
                n1 = min(1.5, max(0.0, 0.84 * x1 + 0.08 + 0.12 * z - 0.35 * float(action in {"A2", "A3"})))
                next_rows.append((c, n0, n1, weight))
            particles = next_rows
            expected = math.fsum(
                weight * (x0 + x1 + ref_phi(c, x0, x1)) ** 2
                for c, x0, x1, weight in particles
            )
            dose = 2 if action == "A3" else int(action is not None)
            expected += 2.0 * 0.03**2 + 0.05 * dose
            expected += 0.08 * float("Q1" in ids) + 0.10 * float("Q2" in ids)
            utility -= 0.97**offset * expected
        return float(utility)

    def private_state_upper_bound(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> float:
        """Judge-only realized interaction comparator, never the scoring oracle."""

        c = int(episode.invariant_parameters["interaction_class"])
        x0, x1 = (float(v) for v in episode.hidden_state_at_cut["components"])
        utility = 0.0
        for offset, ids in enumerate(_plan_ids(policy, horizon)):
            action = next((name for name in ("A3", "A1", "A2") if name in ids), None)
            x0, x1 = self._step(c, x0, x1, action)
            dose = 2 if action == "A3" else int(action is not None)
            utility -= 0.97**offset * (
                (x0 + x1 + self._phi(c, x0, x1)) ** 2 + 0.05 * dose
                + 0.08 * float("Q1" in ids) + 0.10 * float("Q2" in ids)
            )
        return float(utility)

    def _fixture(
        self,
        *,
        seed: int,
        salt: int,
        c: int,
        components: tuple[float, float],
    ) -> PrivateEpisode:
        x0, x1 = components
        z = self._phi(c, x0, x1)
        key: tuple[str | int, ...] = ("w13-fixture", salt)
        events = [
            _observation(seed, key, "obs_0", x0 + x1, 0, slot=0),
            _observation(seed, key, "obs_1", x0 - x1, 0, slot=1),
            _observation(seed, key, "obs_2", z, 0, slot=2),
        ]
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, salt),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"components": [x0, x1]},
            invariant_parameters={"interaction_class": c},
            diagnostic_target={f"C{i}": float(i == c) for i in range(3)},
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={
                "fixture": "paired",
                "probe_attribution": "candidate-attributable",
            },
        )

    def distinguishable_fixture(
        self, seed: int = 1311
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Same components, but the public interaction assay and futures differ."""

        return (
            self._fixture(seed=seed, salt=1, c=0, components=(0.75, 0.65)),
            self._fixture(seed=seed, salt=2, c=1, components=(0.75, 0.65)),
        )

    def threshold_fixture(
        self, seed: int = 1312
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Equal routine total on opposite sides of the product threshold."""

        root = math.sqrt(0.33)
        return (
            self._fixture(
                seed=seed,
                salt=3,
                c=2,
                components=((1.30 + root) / 2.0, (1.30 - root) / 2.0),
            ),
            self._fixture(seed=seed, salt=4, c=2, components=(0.80, 0.50)),
        )

    def equivalent_fixture(
        self, seed: int = 1313
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        first = self._fixture(seed=seed, salt=5, c=0, components=(0.58, 0.37))
        return first, replace(
            first,
            public_history=_alpha_rename(first.public_history, "w13-equivalent"),
        )

    collision_fixture = distinguishable_fixture
    false_split_fixture = equivalent_fixture


W13World = World13
World = World13

__all__ = ["W13World", "World", "World13"]
