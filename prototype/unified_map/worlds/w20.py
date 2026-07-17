"""W20: feedback and treatment-history dependence with finite memory.

The judge-side state is ``(x, r)``.  Every performed dose and ``r_-4 = 0`` are
public, so the cut posterior is a Gaussian belief over ``x`` times an exact
point mass over ``r``.  The scoring oracle filters *all* available Q0 results;
it never substitutes the last result or a private realized state for
``P(x, r | public history)``.

Two source-distinct implementations are intentionally kept in this module:
the production path uses covariance-form Kalman updates, while the reference
path uses scalar information-form updates and an independently written policy
enumerator.  They share constants and protocol DTOs, but no substantive
filtering or rollout helper.
"""

from __future__ import annotations

import math
from dataclasses import replace
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
from .w01 import (
    _case_key,
    _check_event,
    _check_plan,
    _exploratory_probabilities,
    _json_float,
    _observation_event,
    _softmax,
    _standard_policy_set,
    _treatment_event,
    _visible_history,
)


_DOSE = {"A1": 1.0, "A2": 0.5}
_RHO = 0.90
_BIAS = 0.10
_MEMORY_DECAY = 0.50
_THRESHOLD = 0.75
_PROCESS_SD = 0.04
_OBS_SD = 0.05
_Q1_SD = 0.08
_INITIAL_MEAN = 0.70
_INITIAL_VARIANCE = 0.35**2
_DISCOUNT = 0.97
_SPLIT_SIZE = {
    WorldSplit.TRAIN: 4096,
    WorldSplit.VALIDATION: 1024,
    WorldSplit.SEALED_TEST: 2048,
}
_FROZEN_STRATA = (
    ("response_reversal", 25),
    ("sufficient_false_split", 25),
    ("stop_continue", 20),
    ("threshold_band", 15),
    ("iid", 15),
)
_CONTINUE_DIGEST = digest_json(
    {"domain": "w20-explicit-current-schedule/1", "dose_schedule": "A1-every-tick"}
)
_ADAPTIVE_RULE = "A1_if_delayed_obs_1_below_0.75_else_A2"


def _rounded(value: float) -> float:
    """Stable oracle wire precision, far below the frozen W20 epsilon."""

    result = float(round(float(value), 12))
    return 0.0 if result == 0.0 else result


class W20World(MicroWorld):
    @property
    def environment_key(self) -> str:
        return "ucm-private-environment-20"

    @property
    def catalog(self) -> PublicCatalog:
        return PublicCatalog(
            observations=(ChannelSpec("obs_0"), ChannelSpec("obs_1")),
            actions=(ActionSpec("A1", cost=0.06), ActionSpec("A2", cost=0.015)),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.08),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W20 horizon")
        policies = list(
            _standard_policy_set(
                horizon, treatments=("A1", "A2"), checks=("Q1",)
            )
        )
        if horizon > 1:
            policies.append(
                _check_plan(
                    "Q1",
                    {
                        "adaptive_rule": _ADAPTIVE_RULE,
                        "measurement_threshold": _THRESHOLD,
                        "result_available_offset": 1,
                        "when_below": "A1",
                        "when_at_or_above": "A2",
                    },
                )
            )
        policies.extend(
            (
                ActionPlan(PlanKind.STOP_CONTROLLABLE),
                ActionPlan(PlanKind.CONTINUE_CURRENT, policy_digest=_CONTINUE_DIGEST),
            )
        )
        return tuple(policies)

    @staticmethod
    def gain(exposure: float) -> float:
        return 0.40 if exposure < _THRESHOLD else -0.35

    @classmethod
    def transition(
        cls, x: float, exposure: float, dose: float, noise: float = 0.0
    ) -> tuple[float, float]:
        next_x = _RHO * x + _BIAS - cls.gain(exposure) * dose + noise
        next_exposure = _MEMORY_DECAY * exposure + dose
        return next_x, next_exposure

    @staticmethod
    def behavior_probabilities(y: float, rhat: float) -> tuple[float, float, float]:
        logits = (0.3, 0.9 * y - 0.6 * rhat, 0.6 * y - 0.3 * rhat)
        return _exploratory_probabilities(_softmax(logits), exploration=0.10)

    @staticmethod
    def q1_probability(rhat: float) -> float:
        return 0.10 + 0.30 / (1.0 + math.exp(-(rhat - 0.60)))

    @staticmethod
    def population_size(split: WorldSplit) -> int:
        if type(split) is not WorldSplit:
            raise ProtocolViolation("W20 split must be WorldSplit")
        return _SPLIT_SIZE[split]

    @staticmethod
    def _apportioned_counts(size: int) -> tuple[int, ...]:
        raw = [size * percentage / 100.0 for _, percentage in _FROZEN_STRATA]
        counts = [math.floor(value) for value in raw]
        missing = size - sum(counts)
        priority = sorted(
            range(len(raw)), key=lambda index: (-(raw[index] - counts[index]), index)
        )
        for index in priority[:missing]:
            counts[index] += 1
        return tuple(counts)

    @classmethod
    def expected_frozen_stratum_counts(cls, split: WorldSplit) -> dict[str, int]:
        if split is not WorldSplit.SEALED_TEST:
            raise ProtocolViolation("W20 frozen 25/25/20/15/15 quotas are test-only")
        size = cls.population_size(split)
        return {
            name: count
            for (name, _), count in zip(
                _FROZEN_STRATA, cls._apportioned_counts(size), strict=True
            )
        }

    @classmethod
    def _stratum_assignment(
        cls, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> tuple[str, int]:
        size = cls.population_size(split)
        if episode_index < 0 or episode_index >= size:
            raise ValueError("W20 episode_index is outside the frozen population")
        if split is not WorldSplit.SEALED_TEST:
            return "iid", episode_index
        shift = int(uniform01(generator_seed, "w20", split.value, "stratum-shift") * size)
        rank = (4051 * episode_index + shift) % size
        lower = 0
        for (name, _), count in zip(
            _FROZEN_STRATA, cls._apportioned_counts(size), strict=True
        ):
            if rank < lower + count:
                return name, rank - lower
            lower += count
        raise AssertionError("W20 frozen stratum apportionment did not close")

    @staticmethod
    def frozen_stratum(episode: PrivateEpisode) -> str:
        value = episode.oracle_anchor.get("frozen_stratum")
        if value not in {name for name, _ in _FROZEN_STRATA}:
            raise ProtocolViolation("episode has no valid W20 frozen stratum")
        return str(value)

    @classmethod
    def strata_for_episode(cls, episode: PrivateEpisode) -> tuple[str, ...]:
        name = cls.frozen_stratum(episode)
        if name == "response_reversal":
            return ("iid_support", "boundary_tail", "behavior_pair")
        if name == "sufficient_false_split":
            return ("iid_support", "compositional_holdout")
        if name == "stop_continue":
            return ("iid_support", "schedule_time_holdout")
        if name == "threshold_band":
            return ("iid_support", "policy_coverage_holdout")
        return ("iid_support",)

    @staticmethod
    def exposure_from_history(episode: PrivateEpisode) -> float:
        """Reconstruct exact ``r`` using public performed actions only."""

        q0_ticks = [
            event.collected_at
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_0"
            and event.collected_at is not None
        ]
        if not q0_ticks:
            raise ValueError("W20 history has no Q0 timeline anchor")
        cut = episode.public_history.as_of_available_at
        start = min(q0_ticks)
        performed = {
            event.occurred_at: str(event.payload["action_id"])
            for event in episode.public_history.events
            if event.kind is EventKind.PERFORMED_TREATMENT
            and event.payload.get("action_id") in _DOSE
        }
        exposure = 0.0
        for tick in range(start, cut):
            exposure = _MEMORY_DECAY * exposure + _DOSE.get(
                performed.get(tick, "NoNewAction"), 0.0
            )
        return exposure

    @staticmethod
    def _forced_action(
        split: WorldSplit, stratum: str, ordinal: int, tick: int
    ) -> tuple[bool, str]:
        """Return ``(forced, action)`` for support/holdout construction."""

        if split is WorldSplit.TRAIN:
            pattern = ordinal % 4
            if pattern == 3:
                return False, "NoNewAction"
            forced = {
                0: {-4: "A1"},
                1: {-3: "A2"},
                2: {-1: "A1"},
            }[pattern]
            return True, forced.get(tick, "NoNewAction")
        if split is WorldSplit.VALIDATION:
            pattern = ordinal % 3
            schedules = (
                {-3: "A1", -1: "A1"},
                {-3: "A2", -1: "A2"},
                {},
            )
            return True, schedules[pattern].get(tick, "NoNewAction")
        if stratum == "response_reversal":
            schedule = {} if ordinal % 2 == 0 else {-2: "A1", -1: "A1"}
            return True, schedule.get(tick, "NoNewAction")
        if stratum == "sufficient_false_split":
            schedule = {-2: "A1"} if ordinal % 2 == 0 else {-1: "A2"}
            return True, schedule.get(tick, "NoNewAction")
        if stratum == "stop_continue":
            schedule = {-3: "A1", -2: "A1", -1: "A1"}
            return True, schedule.get(tick, "NoNewAction")
        if stratum == "threshold_band":
            schedule = {-2: "A2", -1: "A2"}
            return True, schedule.get(tick, "NoNewAction")
        return False, "NoNewAction"

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        stratum, ordinal = self._stratum_assignment(
            split, generator_seed, episode_index
        )
        paired_target = None
        if split is WorldSplit.SEALED_TEST and stratum in {
            "response_reversal",
            "sufficient_false_split",
        }:
            paired_target = 0.25 + 0.90 * uniform01(
                generator_seed,
                "w20",
                split.value,
                stratum,
                ordinal // 2,
                "paired-posterior-target",
            )
        x = _INITIAL_MEAN + math.sqrt(_INITIAL_VARIANCE) * normal01(
            generator_seed, "w20", split.value, episode_index, "initial-x"
        )
        exposure = 0.0
        events = []
        propensities: list[dict[str, Any]] = []
        latest_q0 = 0.0
        for tick in range(-4, 1):
            if paired_target is None:
                latest_q0 = x + _OBS_SD * normal01(
                    generator_seed, "w20", split.value, episode_index, "q0", tick
                )
            else:
                # Both sides of a frozen pair get the same pre-cut observation
                # tape.  The final value is adjusted below so their *complete*
                # posterior, rather than merely their latest Q0, hits the same
                # target despite the deliberately different action histories.
                latest_q0 = paired_target + 0.12 * normal01(
                    generator_seed,
                    "w20",
                    split.value,
                    stratum,
                    ordinal // 2,
                    "paired-q0",
                    tick,
                )
            events.append(
                _observation_event(
                    generator_seed,
                    "obs_0",
                    latest_q0,
                    collected_at=tick,
                    available_at=tick,
                    slot=episode_index * 64,
                )
            )
            if tick == 0:
                break

            check_probability = self.q1_probability(exposure)
            selected_check = "Q1" if bernoulli(
                check_probability,
                generator_seed,
                "w20",
                split.value,
                episode_index,
                "q1-order",
                tick,
            ) else "NoCheck"
            propensities.append(
                {
                    "decision_at": tick,
                    "kind": "check",
                    "probabilities": {
                        "NoCheck": 1.0 - check_probability,
                        "Q1": check_probability,
                    },
                    "selected": selected_check,
                    "public_inputs": {"rhat": _json_float(exposure)},
                }
            )
            if selected_check == "Q1":
                slot = episode_index * 64 + (tick + 4) * 4
                events.extend(
                    (
                        _check_event(
                            generator_seed,
                            "Q1",
                            tick,
                            performed=False,
                            slot=slot,
                        ),
                        _check_event(
                            generator_seed,
                            "Q1",
                            tick,
                            performed=True,
                            slot=slot,
                        ),
                        _observation_event(
                            generator_seed,
                            "obs_1",
                            exposure
                            + _Q1_SD
                            * normal01(
                                generator_seed,
                                "w20",
                                split.value,
                                episode_index,
                                "q1-result",
                                tick,
                            ),
                            collected_at=tick,
                            available_at=tick + 1,
                            slot=slot,
                        ),
                    )
                )

            probabilities = self.behavior_probabilities(latest_q0, exposure)
            forced, forced_action = self._forced_action(
                split, stratum, ordinal, tick
            )
            if forced:
                action = forced_action
                sampling = {
                    name: float(name == action)
                    for name in ("NoNewAction", "A1", "A2")
                }
            else:
                selected = categorical(
                    probabilities,
                    generator_seed,
                    "w20",
                    split.value,
                    episode_index,
                    "behavior-action",
                    tick,
                )
                action = ("NoNewAction", "A1", "A2")[selected]
                sampling = {
                    "NoNewAction": probabilities[0],
                    "A1": probabilities[1],
                    "A2": probabilities[2],
                }
            propensities.append(
                {
                    "decision_at": tick,
                    "kind": "action",
                    "probabilities": sampling,
                    "behavior_proposal_probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                        "A2": probabilities[2],
                    },
                    "selection_mode": "frozen_stratum" if forced else "behavior",
                    "selected": action,
                    "public_inputs": {
                        "latest_q0": _json_float(latest_q0),
                        "rhat": _json_float(exposure),
                    },
                }
            )
            if action in _DOSE:
                events.append(
                    _treatment_event(
                        generator_seed,
                        action,
                        tick,
                        slot=episode_index * 64 + tick + 4,
                    )
                )
            x, exposure = self.transition(
                x,
                exposure,
                _DOSE.get(action, 0.0),
                _PROCESS_SD
                * normal01(
                    generator_seed,
                    "w20",
                    split.value,
                    episode_index,
                    "process",
                    tick + 1,
                ),
            )

        history = _visible_history(events, self.catalog)
        if paired_target is not None:
            history = self._retarget_history_posterior(
                history,
                split=split,
                generator_seed=generator_seed,
                target_mean=paired_target,
            )
            latest_q0 = next(
                float(event.payload["value"])
                for event in reversed(history.events)
                if event.kind is EventKind.OBSERVATION_AVAILABLE
                and event.payload.get("channel_id") == "obs_0"
            )
        reconstructed = self.exposure_from_history(
            PrivateEpisode(
                case_key="temporary-w20-reconstruction",
                environment_key=self.environment_key,
                split=split,
                generator_seed=generator_seed,
                public_history=history,
                hidden_state_at_cut={},
                invariant_parameters={},
                diagnostic_target={},
                factual_future=[],
                action_propensities=[],
                factual_utility=0.0,
                oracle_anchor={},
            )
        )
        if abs(reconstructed - exposure) > 1e-12:
            raise AssertionError("public action ledger failed to close W20 r")
        if stratum == "threshold_band" and split is WorldSplit.SEALED_TEST:
            if abs(exposure - _THRESHOLD) > 0.03:
                raise AssertionError("W20 threshold stratum escaped its frozen band")

        factual_x = x
        factual_r = exposure
        public_q0 = latest_q0
        future: list[dict[str, Any]] = []
        utility = 0.0
        for offset in range(4):
            check_probability = self.q1_probability(factual_r)
            q1_selected = bernoulli(
                check_probability,
                generator_seed,
                "w20",
                split.value,
                episode_index,
                "future-q1-order",
                offset,
            )
            probabilities = self.behavior_probabilities(public_q0, factual_r)
            selected = categorical(
                probabilities,
                generator_seed,
                "w20",
                split.value,
                episode_index,
                "future-action",
                offset,
            )
            action = ("NoNewAction", "A1", "A2")[selected]
            public_inputs = {
                "latest_q0": _json_float(public_q0),
                "rhat": _json_float(factual_r),
            }
            q1_result = (
                factual_r
                + _Q1_SD
                * normal01(
                    generator_seed,
                    "w20",
                    split.value,
                    episode_index,
                    "future-q1-result",
                    offset,
                )
                if q1_selected
                else None
            )
            dose = _DOSE.get(action, 0.0)
            factual_x, factual_r = self.transition(
                factual_x,
                factual_r,
                dose,
                _PROCESS_SD
                * normal01(
                    generator_seed,
                    "w20",
                    split.value,
                    episode_index,
                    "future-process",
                    offset,
                ),
            )
            public_q0 = factual_x + _OBS_SD * normal01(
                generator_seed,
                "w20",
                split.value,
                episode_index,
                "future-q0",
                offset,
            )
            utility -= _DISCOUNT**offset * (
                factual_x * factual_x + 0.06 * dose * dose + 0.08 * q1_selected
            )
            future_observations = {"obs_0": _json_float(public_q0)}
            if q1_result is not None:
                future_observations["obs_1"] = _json_float(q1_result)
            future.append(
                {
                    "offset": offset + 1,
                    "observations": future_observations,
                    "performed_action": action,
                    "exposure_memory": _json_float(factual_r),
                    "decision_public_inputs": public_inputs,
                    "action_probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                        "A2": probabilities[2],
                    },
                    "q1_ordered": q1_selected,
                    "q1_probability": check_probability,
                    "q1_result_available_offset": offset + 1 if q1_selected else None,
                }
            )

        c = int(exposure >= _THRESHOLD)
        return PrivateEpisode(
            case_key=_case_key(
                self.environment_key, split, generator_seed, episode_index
            ),
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=history,
            hidden_state_at_cut={"x": _json_float(x), "r": _json_float(exposure)},
            invariant_parameters={
                "initial_mean": _INITIAL_MEAN,
                "initial_variance": _INITIAL_VARIANCE,
                "initial_exposure": 0.0,
                "memory_decay": _MEMORY_DECAY,
            },
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=_json_float(utility),
            oracle_anchor={
                "sufficient_statistic": ["posterior_x", "point_mass_r"],
                "exposure_reconstructed_from_public_actions": True,
                "future_behavior_inputs": ["latest_public_q0", "public_rhat"],
                "frozen_stratum": stratum,
                "frozen_stratum_ordinal": ordinal,
                "frozen_pair_id": (
                    ordinal // 2
                    if stratum
                    in {"response_reversal", "sufficient_false_split"}
                    else None
                ),
            },
        )

    def _retarget_history_posterior(
        self,
        history: Any,
        *,
        split: WorldSplit,
        generator_seed: int,
        target_mean: float,
    ) -> Any:
        """Change only final Q0 so a frozen pair has one exact posterior mean."""

        events = list(history.events)
        final_index = max(
            index
            for index, event in enumerate(events)
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_0"
            and event.collected_at == history.as_of_available_at
        )

        def with_value(value: float) -> Any:
            adjusted = list(events)
            event = adjusted[final_index]
            adjusted[final_index] = replace(
                event, payload={**event.payload, "value": float(value)}
            )
            return replace(history, events=tuple(adjusted))

        def temporary(candidate_history: Any) -> PrivateEpisode:
            return PrivateEpisode(
                case_key="temporary-w20-posterior-retarget",
                environment_key=self.environment_key,
                split=split,
                generator_seed=generator_seed,
                public_history=candidate_history,
                hidden_state_at_cut={},
                invariant_parameters={},
                diagnostic_target={},
                factual_future=[],
                action_propensities=[],
                factual_utility=0.0,
                oracle_anchor={},
            )

        zero_mean = self._production_posterior(temporary(with_value(0.0)))[0]
        unit_mean = self._production_posterior(temporary(with_value(1.0)))[0]
        slope = unit_mean - zero_mean
        if abs(slope) < 1e-12:
            raise AssertionError("W20 final Q0 cannot retarget posterior")
        final_value = (target_mean - zero_mean) / slope
        adjusted_history = with_value(final_value)
        for _ in range(3):
            obtained = self._production_posterior(temporary(adjusted_history))[0]
            error = target_mean - obtained
            if abs(error) <= 1e-14:
                break
            final_value += error / slope
            adjusted_history = with_value(final_value)
        if _rounded(
            self._production_posterior(temporary(adjusted_history))[0]
        ) != _rounded(target_mean):
            raise AssertionError("W20 paired posterior retarget failed")
        return adjusted_history

    # ------------------------------------------------------------------
    # Production oracle: covariance-form filter + branch enumeration.
    # ------------------------------------------------------------------

    @staticmethod
    def _production_posterior(episode: PrivateEpisode) -> tuple[float, float, float, int]:
        observations: dict[int, list[float]] = {}
        action_at: dict[int, float] = {}
        evidence_count = 0
        for event in episode.public_history.events:
            if (
                event.kind is EventKind.OBSERVATION_AVAILABLE
                and event.payload.get("channel_id") == "obs_0"
                and event.collected_at is not None
            ):
                observations.setdefault(event.collected_at, []).append(
                    float(event.payload["value"])
                )
                evidence_count += 1
            elif event.kind is EventKind.OBSERVATION_AVAILABLE and event.payload.get(
                "channel_id"
            ) == "obs_1":
                evidence_count += 1
            elif event.kind is EventKind.PERFORMED_TREATMENT:
                identifier = event.payload.get("action_id")
                if identifier in _DOSE:
                    action_at[event.occurred_at] = _DOSE[str(identifier)]
                    evidence_count += 1
        if not observations:
            raise ProtocolViolation("W20 production oracle requires public Q0 history")
        start = min(observations)
        cut = episode.public_history.as_of_available_at
        mean = _INITIAL_MEAN
        variance = _INITIAL_VARIANCE
        exposure = 0.0
        observation_variance = _OBS_SD**2
        for tick in range(start, cut + 1):
            for value in observations.get(tick, ()):
                innovation_variance = variance + observation_variance
                kalman_gain = variance / innovation_variance
                mean = mean + kalman_gain * (value - mean)
                variance = (1.0 - kalman_gain) * variance
            if tick < cut:
                dose = action_at.get(tick, 0.0)
                response = 0.40 if exposure < _THRESHOLD else -0.35
                mean = _RHO * mean + _BIAS - response * dose
                variance = _RHO * _RHO * variance + _PROCESS_SD * _PROCESS_SD
                exposure = _MEMORY_DECAY * exposure + dose
        return mean, variance, exposure, evidence_count

    @staticmethod
    def _production_branches(
        policy: ActionPlan, horizon: int, exposure: float
    ) -> tuple[list[tuple[str, float, int | None, list[float]]], float]:
        adaptive = (
            policy.kind is PlanKind.ACTION_SEQUENCE
            and len(policy.actions) == 1
            and policy.actions[0].action_id == "Q1"
            and policy.actions[0].parameters.get("adaptive_rule") == _ADAPTIVE_RULE
        )
        has_check = (
            policy.kind is PlanKind.ACTION_SEQUENCE
            and any(action.action_id == "Q1" for action in policy.actions)
        )
        check_cost = 0.08 if has_check else 0.0
        if adaptive:
            z = (_THRESHOLD - exposure) / _Q1_SD
            below = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
            branches = []
            for name, weight, dose in (("A1", below, 1.0), ("A2", 1.0 - below, 0.5)):
                schedule = [0.0] * horizon
                if horizon > 1:
                    schedule[1] = dose
                branches.append((name, weight, 1, schedule))
            return branches, check_cost
        schedule = [0.0] * horizon
        if policy.kind is PlanKind.ACTION_SEQUENCE:
            for action in policy.actions:
                if action.offset < horizon and action.action_id in _DOSE:
                    schedule[action.offset] = _DOSE[action.action_id]
        elif policy.kind is PlanKind.CONTINUE_CURRENT:
            schedule = [1.0] * horizon
        return [("open_loop", 1.0, None, schedule)], check_cost

    @staticmethod
    def _production_component(
        mean: float,
        variance: float,
        exposure: float,
        schedule: list[float],
        check_cost: float,
    ) -> tuple[list[dict[str, Any]], float]:
        steps: list[dict[str, Any]] = []
        utility = -check_cost
        for offset, dose in enumerate(schedule):
            response = 0.40 if exposure < _THRESHOLD else -0.35
            mean = _RHO * mean + _BIAS - response * dose
            variance = _RHO * _RHO * variance + _PROCESS_SD * _PROCESS_SD
            exposure = _MEMORY_DECAY * exposure + dose
            utility -= _DISCOUNT**offset * (
                mean * mean + variance + 0.06 * dose * dose
            )
            steps.append(
                {
                    "offset": offset + 1,
                    "mean": _rounded(mean),
                    "variance": _rounded(variance),
                    "observation_variance": _rounded(variance + _OBS_SD**2),
                    "exposure_memory": _rounded(exposure),
                    "gain_before_dose": _rounded(response),
                    "dose": _rounded(dose),
                }
            )
        return steps, utility

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed
        mean, variance, exposure, evidence_count = self._production_posterior(episode)
        return self.public_belief_counterfactual(
            mean,
            variance,
            exposure,
            evidence_count,
            policy,
            horizon,
        )

    def public_belief_counterfactual(
        self,
        mean: float,
        variance: float,
        exposure: float,
        evidence_count: int,
        policy: ActionPlan,
        horizon: int,
    ) -> CounterfactualOracle:
        """Roll out from the finite public Bayesian state ``(x belief, r)``."""

        if horizon not in (1, 4, 8):
            raise ValueError("unsupported W20 horizon")
        if policy not in self.policy_set(horizon):
            raise ValueError("policy is outside the finite W20 policy set")
        if any(
            type(value) not in {int, float} or not math.isfinite(float(value))
            for value in (mean, variance, exposure)
        ):
            raise ValueError("W20 public belief must be finite")
        if variance < 0.0 or exposure < 0.0:
            raise ValueError("W20 public variance/exposure cannot be negative")
        if type(evidence_count) is not int or evidence_count <= 0:
            raise ValueError("W20 evidence count must be positive")
        branch_specs, check_cost = self._production_branches(policy, horizon, exposure)
        components: list[dict[str, Any]] = []
        outcome_components: list[dict[str, Any]] = []
        expected_utility = 0.0
        for branch_action, weight, available_offset, schedule in branch_specs:
            steps, branch_utility = self._production_component(
                mean, variance, exposure, schedule, check_cost
            )
            components.append(
                {
                    "branch_action": branch_action,
                    "weight": _rounded(weight),
                    "result_available_offset": available_offset,
                    "steps": steps,
                }
            )
            outcome_components.append(
                {
                    "branch_action": branch_action,
                    "weight": _rounded(weight),
                    "expected_utility": _rounded(branch_utility),
                }
            )
            expected_utility += weight * branch_utility
        cut = {
            "family": "gaussian-x-point-mass-r",
            "state_channels": ["x", "r"],
            "mean": [_rounded(mean), _rounded(exposure)],
            "covariance": [[_rounded(variance), 0.0], [0.0, 0.0]],
        }
        diagnostic = {
            "C0": float(exposure < _THRESHOLD),
            "C1": float(exposure >= _THRESHOLD),
        }
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "public-posterior-branch-mixture",
                "components": components,
            },
            latent_distribution={
                "family": "finite-bayesian-sufficient-state",
                "state_channels": ["x", "r"],
                "cut_posterior": cut,
                "components": components,
                "steps": components[0]["steps"],
                "diagnostic_posterior": diagnostic,
            },
            outcome_distribution={
                "utility_family": "posterior-expected-quadratic-cost",
                "check_cost": check_cost,
                "components": outcome_components,
                "expected_utility": _rounded(expected_utility),
            },
            expected_utility=_rounded(expected_utility),
            numerical_diagnostics={
                "method": "covariance-form-full-public-history-filter",
                "absolute_error_bound": 5e-12,
            },
        )

    # ------------------------------------------------------------------
    # Reference oracle: information-form filter + independent enumerator.
    # ------------------------------------------------------------------

    @staticmethod
    def _reference_posterior(episode: PrivateEpisode) -> tuple[float, float, float, int]:
        q0_rows: list[tuple[int, float]] = []
        dose_rows: dict[int, float] = {}
        evidence = 0
        for row in episode.public_history.events:
            if row.kind is EventKind.OBSERVATION_AVAILABLE:
                channel = row.payload.get("channel_id")
                if channel == "obs_0" and row.collected_at is not None:
                    q0_rows.append((row.collected_at, float(row.payload["value"])))
                    evidence += 1
                elif channel == "obs_1":
                    evidence += 1
            if row.kind is EventKind.PERFORMED_TREATMENT:
                action_name = row.payload.get("action_id")
                if action_name == "A1":
                    dose_rows[row.occurred_at] = 1.0
                    evidence += 1
                elif action_name == "A2":
                    dose_rows[row.occurred_at] = 0.5
                    evidence += 1
        if not q0_rows:
            raise ProtocolViolation("W20 reference oracle requires public Q0 history")
        grouped: dict[int, list[float]] = {}
        for timestamp, observed_value in q0_rows:
            grouped.setdefault(timestamp, []).append(observed_value)
        start_time = min(grouped)
        end_time = episode.public_history.as_of_available_at
        location = _INITIAL_MEAN
        spread = _INITIAL_VARIANCE
        remembered_dose = 0.0
        measurement_precision = 1.0 / (_OBS_SD * _OBS_SD)
        for timestamp in range(start_time, end_time + 1):
            for observed_value in grouped.get(timestamp, []):
                prior_precision = 1.0 / spread
                posterior_precision = prior_precision + measurement_precision
                information = location * prior_precision + observed_value * measurement_precision
                location = information / posterior_precision
                spread = 1.0 / posterior_precision
            if timestamp != end_time:
                administered = dose_rows.get(timestamp, 0.0)
                coefficient = 0.40 if remembered_dose < 0.75 else -0.35
                location = 0.90 * location + 0.10 - coefficient * administered
                spread = 0.81 * spread + 0.0016
                remembered_dose = 0.50 * remembered_dose + administered
        return location, spread, remembered_dose, evidence

    @staticmethod
    def _reference_branches(
        policy: ActionPlan, horizon: int, remembered_dose: float
    ) -> tuple[list[dict[str, Any]], float]:
        check_present = False
        adaptive_present = False
        if policy.kind is PlanKind.ACTION_SEQUENCE:
            for proposed in policy.actions:
                if proposed.action_id == "Q1":
                    check_present = True
                    adaptive_present = (
                        proposed.parameters.get("adaptive_rule") == _ADAPTIVE_RULE
                    )
        fee = 0.08 if check_present else 0.0
        if adaptive_present:
            from statistics import NormalDist

            lower_probability = NormalDist(mu=remembered_dose, sigma=0.08).cdf(0.75)
            first_schedule = [0.0 for _ in range(horizon)]
            second_schedule = [0.0 for _ in range(horizon)]
            if horizon >= 2:
                first_schedule[1] = 1.0
                second_schedule[1] = 0.5
            return [
                {
                    "name": "A1",
                    "probability": lower_probability,
                    "available": 1,
                    "schedule": first_schedule,
                },
                {
                    "name": "A2",
                    "probability": 1.0 - lower_probability,
                    "available": 1,
                    "schedule": second_schedule,
                },
            ], fee
        doses = [0.0 for _ in range(horizon)]
        if policy.kind is PlanKind.CONTINUE_CURRENT:
            for position in range(horizon):
                doses[position] = 1.0
        elif policy.kind is PlanKind.ACTION_SEQUENCE:
            for proposed in policy.actions:
                if proposed.offset >= horizon:
                    continue
                if proposed.action_id == "A1":
                    doses[proposed.offset] = 1.0
                elif proposed.action_id == "A2":
                    doses[proposed.offset] = 0.5
        return [
            {
                "name": "open_loop",
                "probability": 1.0,
                "available": None,
                "schedule": doses,
            }
        ], fee

    @staticmethod
    def _reference_component(
        location: float,
        spread: float,
        remembered_dose: float,
        schedule: list[float],
        fee: float,
    ) -> tuple[list[dict[str, Any]], float]:
        trajectory: list[dict[str, Any]] = []
        total_value = -fee
        discount = 1.0
        for position in range(len(schedule)):
            administered = schedule[position]
            response_coefficient = 0.40 if remembered_dose < 0.75 else -0.35
            location = 0.90 * location + 0.10 - response_coefficient * administered
            spread = 0.81 * spread + 0.0016
            remembered_dose = 0.50 * remembered_dose + administered
            period_loss = location**2 + spread + 0.06 * administered**2
            total_value = total_value - discount * period_loss
            discount = discount * 0.97
            trajectory.append(
                {
                    "offset": position + 1,
                    "mean": float(round(location, 12)),
                    "variance": float(round(spread, 12)),
                    "observation_variance": float(round(spread + 0.0025, 12)),
                    "exposure_memory": float(round(remembered_dose, 12)),
                    "gain_before_dose": float(round(response_coefficient, 12)),
                    "dose": float(round(administered, 12)),
                }
            )
        return trajectory, total_value

    def reference_counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed
        if horizon != 1 and horizon != 4 and horizon != 8:
            raise ValueError("unsupported W20 reference horizon")
        location, spread, remembered_dose, evidence = self._reference_posterior(episode)
        alternatives, fee = self._reference_branches(policy, horizon, remembered_dose)
        mixture_rows: list[dict[str, Any]] = []
        utility_rows: list[dict[str, Any]] = []
        total = 0.0
        for alternative in alternatives:
            trajectory, value = self._reference_component(
                location,
                spread,
                remembered_dose,
                alternative["schedule"],
                fee,
            )
            probability = float(alternative["probability"])
            mixture_rows.append(
                {
                    "branch_action": alternative["name"],
                    "weight": float(round(probability, 12)),
                    "result_available_offset": alternative["available"],
                    "steps": trajectory,
                }
            )
            utility_rows.append(
                {
                    "branch_action": alternative["name"],
                    "weight": float(round(probability, 12)),
                    "expected_utility": float(round(value, 12)),
                }
            )
            total = total + probability * value
        cut_belief = {
            "family": "gaussian-x-point-mass-r",
            "state_channels": ["x", "r"],
            "mean": [float(round(location, 12)), float(round(remembered_dose, 12))],
            "covariance": [[float(round(spread, 12)), 0.0], [0.0, 0.0]],
        }
        class_probabilities = {
            "C0": float(remembered_dose < 0.75),
            "C1": float(remembered_dose >= 0.75),
        }
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "public-posterior-branch-mixture",
                "components": mixture_rows,
            },
            latent_distribution={
                "family": "finite-bayesian-sufficient-state",
                "state_channels": ["x", "r"],
                "cut_posterior": cut_belief,
                "components": mixture_rows,
                "steps": mixture_rows[0]["steps"],
                "diagnostic_posterior": class_probabilities,
            },
            outcome_distribution={
                "utility_family": "posterior-expected-quadratic-cost",
                "check_cost": fee,
                "components": utility_rows,
                "expected_utility": float(round(total, 12)),
            },
            expected_utility=float(round(total, 12)),
            numerical_diagnostics={
                "method": "independent-information-form-public-history-filter",
                "absolute_error_bound": 5e-12,
            },
        )

    def sufficient_state(self, episode: PrivateEpisode) -> tuple[float, float]:
        mean, _, exposure, _ = self._production_posterior(episode)
        return _rounded(mean), _rounded(exposure)

    def _fixture_episode(
        self,
        *,
        seed: int,
        side: str,
        actions: dict[int, str],
        observations: dict[int, float],
        private_x: float,
    ) -> PrivateEpisode:
        events = []
        slot_base = 0 if side == "left" else 100
        for tick in range(-4, 1):
            events.append(
                _observation_event(
                    seed,
                    "obs_0",
                    observations[tick],
                    collected_at=tick,
                    available_at=tick,
                    slot=slot_base + tick + 4,
                )
            )
            action = actions.get(tick)
            if action in _DOSE:
                events.append(
                    _treatment_event(
                        seed,
                        action,
                        tick,
                        slot=slot_base + tick + 4,
                    )
                )
        history = _visible_history(events, self.catalog)
        temporary = PrivateEpisode(
            case_key=digest_json({"fixture": "w20", "seed": seed, "side": side}),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=history,
            hidden_state_at_cut={},
            invariant_parameters={},
            diagnostic_target={},
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={},
        )
        exposure = self.exposure_from_history(temporary)
        c = int(exposure >= _THRESHOLD)
        return replace(
            temporary,
            hidden_state_at_cut={"x": private_x, "r": exposure},
            invariant_parameters={"fixture_private_realization": side},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            oracle_anchor={
                "fixture": side,
                "sufficient_statistic": ["posterior_x", "point_mass_r"],
            },
        )

    def _fixture_with_target_posterior(
        self,
        *,
        seed: int,
        side: str,
        actions: dict[int, str],
        earlier_values: dict[int, float],
        target_mean: float,
    ) -> PrivateEpisode:
        base_values = {tick: earlier_values.get(tick, 0.0) for tick in range(-4, 0)}

        def build(last: float) -> PrivateEpisode:
            return self._fixture_episode(
                seed=seed,
                side=side,
                actions=actions,
                observations={**base_values, 0: last},
                private_x=target_mean,
            )

        zero = build(0.0)
        one = build(1.0)
        zero_mean = self._production_posterior(zero)[0]
        slope = self._production_posterior(one)[0] - zero_mean
        if abs(slope) < 1e-12:
            raise AssertionError("W20 fixture final observation has zero leverage")
        last_value = (target_mean - zero_mean) / slope
        result = build(last_value)
        for _ in range(3):
            error = target_mean - self._production_posterior(result)[0]
            if abs(error) <= 1e-14:
                break
            last_value += error / slope
            result = build(last_value)
        if _rounded(self._production_posterior(result)[0]) != _rounded(target_mean):
            raise AssertionError("W20 fixture posterior target did not close")
        return result

    def exposure_collision_pair(
        self, seed: int = 2001
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Same public posterior over x; public r flips the A1 response sign."""

        low = self._fixture_with_target_posterior(
            seed=seed,
            side="left",
            actions={},
            earlier_values={-4: 0.2, -3: 0.3, -2: 0.5, -1: 0.6},
            target_mean=0.70,
        )
        high = self._fixture_with_target_posterior(
            seed=seed,
            side="right",
            actions={-2: "A1", -1: "A1"},
            earlier_values={-4: 1.0, -3: 0.9, -2: 0.8, -1: 0.75},
            target_mean=0.70,
        )
        return low, high

    def sufficient_statistic_false_split_pair(
        self, seed: int = 2003
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Different histories with the same complete public ``P(x,r|H)``."""

        first = self._fixture_with_target_posterior(
            seed=seed,
            side="left",
            actions={-2: "A1"},
            earlier_values={-4: 0.1, -3: 0.3, -2: 0.9, -1: 0.8},
            target_mean=0.65,
        )
        second = self._fixture_with_target_posterior(
            seed=seed,
            side="right",
            actions={-1: "A2"},
            earlier_values={-4: 0.7, -3: 0.6, -2: 0.5, -1: 0.4},
            target_mean=0.65,
        )
        first_posterior = self._production_posterior(first)
        second_posterior = self._production_posterior(second)
        if (
            _rounded(first_posterior[0]) != _rounded(second_posterior[0])
            or _rounded(first_posterior[1]) != _rounded(second_posterior[1])
            or _rounded(first_posterior[2]) != _rounded(second_posterior[2])
        ):
            raise AssertionError("W20 full-posterior false-split construction failed")
        return first, second


World = W20World

__all__ = ["W20World", "World"]
