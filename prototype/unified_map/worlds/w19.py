"""W19: a fixed-prevalence contraindication tail with catastrophic utility.

Population allocation is stratified, not Bernoulli: every keyed block of 64
contains exactly one tail member.  The separate 256-pair probe cohort is never
part of population prevalence or headline aggregation.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..canonical import digest_json
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
    _check_plan,
    _exploratory_probabilities,
    _json_float,
    _observation_event,
    _softmax,
    _standard_policy_set,
    _visible_history,
)


_SPLIT_SIZE = {
    WorldSplit.TRAIN: 4096,
    WorldSplit.VALIDATION: 1024,
    WorldSplit.SEALED_TEST: 2048,
}
_TAIL_RATE = 1.0 / 64.0
_RHO = 0.90
_BIAS = 0.12
_PROCESS_SD = 0.04
_OBS_SD = 0.05
_CATASTROPHE = 30.0


def _latest_marker(episode: PrivateEpisode) -> int | None:
    values = [
        int(event.payload["value"])
        for event in episode.public_history.events
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == "obs_1"
    ]
    return values[-1] if values else None


def _latest_x(episode: PrivateEpisode) -> float:
    values = [
        float(event.payload["value"])
        for event in episode.public_history.events
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == "obs_0"
    ]
    if not values:
        raise ValueError("missing obs_0")
    return values[-1]


def _schedule(policy: ActionPlan, horizon: int) -> list[str]:
    result = ["NoNewAction"] * horizon
    if policy.kind is PlanKind.ACTION_SEQUENCE:
        for action in policy.actions:
            if action.offset < horizon and action.action_id in {"A1", "A2"}:
                result[action.offset] = action.action_id
    return result


class W19World(MicroWorld):
    @property
    def environment_key(self) -> str:
        return "ucm-private-environment-19"

    @property
    def catalog(self) -> PublicCatalog:
        return PublicCatalog(
            observations=(
                ChannelSpec("obs_0"),
                ChannelSpec("obs_1", value_type="binary", unit="indicator", valid_range=(0, 1)),
            ),
            actions=(ActionSpec("A1", cost=0.05), ActionSpec("A2", cost=0.08)),
            checks=(
                CheckSpec("Q0", ("obs_0",), (0, 0), cost=0.0),
                CheckSpec("Q1", ("obs_1",), (1, 1), cost=0.08),
            ),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W19 horizon")
        return _standard_policy_set(
            horizon, treatments=("A1", "A2"), checks=("Q1",)
        )

    @staticmethod
    def population_size(split: WorldSplit) -> int:
        return _SPLIT_SIZE[split]

    @staticmethod
    def expected_tail_count(split: WorldSplit) -> int:
        return _SPLIT_SIZE[split] // 64

    @staticmethod
    def is_population_tail(
        split: WorldSplit, generator_seed: int, episode_index: int
    ) -> bool:
        """One secret-permutation position per 64-row family block."""

        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        block, position = divmod(episode_index, 64)
        scores = [
            uniform01(
                generator_seed,
                "w19",
                split.value,
                "tail-permutation",
                block,
                candidate,
            )
            for candidate in range(64)
        ]
        chosen = min(range(64), key=lambda candidate: (scores[candidate], candidate))
        return position == chosen

    @staticmethod
    def _marker_posterior(marker: int | None) -> float:
        if marker is None:
            return _TAIL_RATE
        likelihood_tail = 0.98 if marker == 1 else 0.02
        likelihood_common = 0.02 if marker == 1 else 0.98
        numerator = _TAIL_RATE * likelihood_tail
        return numerator / (numerator + (1.0 - _TAIL_RATE) * likelihood_common)

    @staticmethod
    def _behavior_probabilities(y: float, marker: int | None) -> tuple[float, float, float]:
        if marker == 1:
            # Keep A1 positivity for identification but never read private h.
            return (0.28, 0.02, 0.70)
        base = _softmax((0.2, 0.9 * y, 0.55 * y))
        return _exploratory_probabilities(base, exploration=0.20)

    def _transition(
        self,
        x: float,
        tail: bool,
        action: str,
        noise: float,
    ) -> float:
        effect = 0.0
        if action == "A1":
            effect = 1.40 if tail else -0.50
        elif action == "A2":
            effect = -0.22
        return _RHO * x + _BIAS + effect + noise

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        if episode_index >= self.population_size(split):
            raise ValueError("population episode_index is outside the frozen split")
        tail = self.is_population_tail(split, generator_seed, episode_index)
        x = 0.20 + 1.10 * uniform01(
            generator_seed, "w19", split.value, episode_index, "x"
        )
        marker_available = episode_index % 3 != 0
        marker: int | None = None
        events = []
        if marker_available:
            marker = int(
                bernoulli(
                    0.98 if tail else 0.02,
                    generator_seed,
                    "w19",
                    split.value,
                    episode_index,
                    "marker",
                )
            )
            events.append(
                _observation_event(
                    generator_seed,
                    "obs_1",
                    marker,
                    collected_at=-1,
                    available_at=0,
                    slot=episode_index * 16 + 1,
                )
            )
        observed = x + _OBS_SD * normal01(
            generator_seed, "w19", split.value, episode_index, "obs"
        )
        events.append(
            _observation_event(
                generator_seed,
                "obs_0",
                observed,
                collected_at=0,
                available_at=0,
                slot=episode_index * 16,
            )
        )
        probabilities = self._behavior_probabilities(observed, marker)
        selected = categorical(
            probabilities,
            generator_seed,
            "w19",
            split.value,
            episode_index,
            "future-action",
        )
        action = ("NoNewAction", "A1", "A2")[selected]
        next_x = self._transition(
            x,
            tail,
            action,
            _PROCESS_SD
            * normal01(
                generator_seed,
                "w19",
                split.value,
                episode_index,
                "future-process",
            ),
        )
        catastrophe = tail and action == "A1"
        utility = -(
            next_x * next_x
            + 0.05 * (action == "A1")
            + 0.08 * (action == "A2")
        ) - _CATASTROPHE * catastrophe
        return PrivateEpisode(
            case_key=_case_key(
                self.environment_key, split, generator_seed, episode_index
            ),
            environment_key=self.environment_key,
            split=split,
            generator_seed=generator_seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"x": _json_float(x)},
            invariant_parameters={
                "tail": tail,
                "cohort": "population",
                "population_weight": _TAIL_RATE if tail else 1.0 - _TAIL_RATE,
            },
            diagnostic_target={"C0": float(not tail), "C1": float(tail)},
            factual_future=[
                {
                    "offset": 1,
                    "observations": {"obs_0": _json_float(next_x)},
                    "performed_action": action,
                    "catastrophic_event": catastrophe,
                }
            ],
            action_propensities=[
                {
                    "decision_at": 0,
                    "probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                        "A2": probabilities[2],
                    },
                    "selected": action,
                }
            ],
            factual_utility=_json_float(utility),
            oracle_anchor={
                "tail_allocation": "one-per-keyed-64-block",
                "population_tail_rate": _TAIL_RATE,
                "probe_cohort_in_population_denominator": False,
            },
        )

    def _component_utility(
        self,
        start_mean: float,
        start_variance: float,
        tail: bool,
        schedule: list[str],
        check_cost: float,
    ) -> tuple[float, list[dict[str, Any]], bool]:
        mean = start_mean
        variance = start_variance
        utility = 0.0
        steps = []
        catastrophe = False
        for offset, action in enumerate(schedule):
            mean = self._transition(mean, tail, action, 0.0)
            variance = _RHO**2 * variance + _PROCESS_SD**2
            catastrophe = catastrophe or (tail and action == "A1")
            cost = mean * mean + variance
            cost += 0.05 * (action == "A1") + 0.08 * (action == "A2")
            if offset == 0:
                cost += check_cost
            utility -= 0.97**offset * cost
            steps.append(
                {
                    "offset": offset + 1,
                    "mean": _json_float(mean),
                    "variance": _json_float(variance),
                }
            )
        if catastrophe:
            utility -= _CATASTROPHE
        return utility, steps, catastrophe

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W19 horizon")
        marker = _latest_marker(episode)
        p_tail = self._marker_posterior(marker)
        schedule = _schedule(policy, horizon)
        check_cost = 0.08 if (
            policy.kind is PlanKind.ACTION_SEQUENCE
            and any(action.action_id == "Q1" for action in policy.actions)
        ) else 0.0
        components = []
        expected = 0.0
        component_utilities: list[tuple[float, float]] = []
        for tail, weight in ((False, 1.0 - p_tail), (True, p_tail)):
            utility, steps, catastrophe = self._component_utility(
                _latest_x(episode), _OBS_SD**2, tail, schedule, check_cost
            )
            expected += weight * utility
            component_utilities.append((utility, weight))
            components.append(
                {
                    "class": "C1" if tail else "C0",
                    "weight": _json_float(weight),
                    "steps": steps,
                    "expected_utility": _json_float(utility),
                    "catastrophic_action": catastrophe,
                }
            )
        ordered = sorted(component_utilities, key=lambda item: item[0])
        worst_utility = ordered[0][0]
        # Exact two-component lower-tail CVaR at alpha=.95 (worst 5%).
        remaining = 0.05
        tail_sum = 0.0
        for value, weight in ordered:
            mass = min(weight, remaining)
            tail_sum += mass * value
            remaining -= mass
            if remaining <= 1e-15:
                break
        if remaining > 0.0:
            tail_sum += remaining * ordered[-1][0]
        cvar05 = tail_sum / 0.05
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "two-component-linear-gaussian",
                "components": components,
                "marker_posterior_tail": _json_float(p_tail),
            },
            latent_distribution={
                "family": "two-component-linear-gaussian",
                "components": components,
                "diagnostic_posterior": {"C0": 1.0 - p_tail, "C1": p_tail},
            },
            outcome_distribution={
                "expected_utility": _json_float(expected),
                "worst_component_utility": _json_float(worst_utility),
                "lower_tail_cvar_95": _json_float(cvar05),
                "catastrophic_action_probability": _json_float(
                    p_tail if "A1" in schedule else 0.0
                ),
                "population_tail_rate": _TAIL_RATE,
                "reporting_contract": [
                    "mean",
                    "p95_regret",
                    "max_regret",
                    "cvar95",
                    "tail_only_regret",
                    "catastrophic_action_rate",
                ],
            },
            expected_utility=_json_float(expected),
            numerical_diagnostics={"method": "analytic-two-component-mixture", "absolute_error_bound": 0.0},
        )

    def _probe_episode(
        self,
        *,
        seed: int,
        probe_index: int,
        tail: bool,
        marker: int | None,
        shared_events: tuple | None = None,
    ) -> PrivateEpisode:
        x = 0.80
        if shared_events is None:
            events = [
                _observation_event(
                    seed,
                    "obs_0",
                    x,
                    collected_at=0,
                    available_at=0,
                    slot=probe_index * 8,
                )
            ]
            if marker is not None:
                events.append(
                    _observation_event(
                        seed,
                        "obs_1",
                        marker,
                        collected_at=-1,
                        available_at=0,
                        slot=probe_index * 8 + 1,
                    )
                )
        else:
            events = list(shared_events)
        posterior = self._marker_posterior(marker)
        return PrivateEpisode(
            case_key=digest_json(
                {"cohort": "w19-probe", "seed": seed, "index": probe_index, "tail": tail}
            ),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"x": x},
            invariant_parameters={
                "tail": tail,
                "cohort": "dedicated-probe",
                "population_weight": 0.0,
            },
            diagnostic_target={"C0": 1.0 - posterior, "C1": posterior},
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={
                "fixture": "tail-probe",
                "probe_cohort_in_population_denominator": False,
            },
        )

    def tail_probe_pair(
        self, seed: int = 1901, probe_index: int = 0
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        if not 0 <= probe_index < 256:
            raise ValueError("W19 dedicated probe index must be in [0,256)")
        common = self._probe_episode(
            seed=seed, probe_index=probe_index, tail=False, marker=0
        )
        tail = self._probe_episode(
            seed=seed, probe_index=probe_index, tail=True, marker=1
        )
        return common, tail

    def unidentified_tail_alias_pair(
        self, seed: int = 1903
    ) -> tuple[PrivateEpisode, PrivateEpisode]:
        common = self._probe_episode(seed=seed, probe_index=0, tail=False, marker=None)
        tail = replace(
            common,
            case_key=digest_json({"pair": "w19-unidentified", "seed": seed, "side": 1}),
            invariant_parameters={
                "tail": True,
                "cohort": "dedicated-probe",
                "population_weight": 0.0,
            },
        )
        return common, tail


World = W19World

__all__ = ["W19World", "World"]
