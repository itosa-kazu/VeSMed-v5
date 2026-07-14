"""W19: a fixed-prevalence contraindication tail with catastrophic utility.

Population allocation is stratified, not Bernoulli: every keyed block of 64
contains exactly one tail member.  The separate 256-pair probe cohort is never
part of population prevalence or headline aggregation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
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
from .randomness import normal01, uniform01
from .w01 import (
    _case_key,
    _check_event,
    _check_plan,
    _json_float,
    _observation_event,
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
_X_PRIOR_LOW = 0.20
_X_PRIOR_HIGH = 1.30
# The finite split quotas below are a generator contract, not a scoring prior.
# Scoring uses this one frozen public marker kernel for every cohort/split.
_PUBLIC_MARKER_SENSITIVITY = 0.98
_PUBLIC_MARKER_FALSE_POSITIVE_RATE = 0.02


@dataclass(frozen=True, slots=True)
class W19TailTruth:
    """Typed judge material consumed by the evaluator's W19 safety gate."""

    posterior_tail_probability: float
    common_expected_utility: float
    tail_expected_utility: float
    tail_best_expected_utility: float
    tail_only_regret: float
    posterior_catastrophic_action_probability: float
    tail_catastrophic_action_probability: float
    catastrophic_hard_gate_exposed: bool


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _normal_pdf(value: float) -> float:
    return math.exp(-0.5 * value * value) / math.sqrt(2.0 * math.pi)


def _truncated_uniform_gaussian_moments(
    observations: tuple[float, ...],
) -> tuple[float, float, float]:
    """Analytic posterior moments for Uniform[a,b] with Gaussian readings."""

    if not observations:
        width = _X_PRIOR_HIGH - _X_PRIOR_LOW
        return (
            0.5 * (_X_PRIOR_LOW + _X_PRIOR_HIGH),
            width * width / 12.0,
            1.0,
        )
    n = len(observations)
    center = math.fsum(observations) / n
    sd = _OBS_SD / math.sqrt(n)
    alpha = (_X_PRIOR_LOW - center) / sd
    beta = (_X_PRIOR_HIGH - center) / sd
    z = _normal_cdf(beta) - _normal_cdf(alpha)
    if z <= 0.0:
        raise ValueError("W19 observation has zero likelihood under x prior")
    ratio = (_normal_pdf(alpha) - _normal_pdf(beta)) / z
    mean = center + sd * ratio
    variance = sd * sd * (
        1.0
        + (alpha * _normal_pdf(alpha) - beta * _normal_pdf(beta)) / z
        - ratio * ratio
    )
    # Marginal evidence up to constants independent of x; retained for audit.
    evidence = z / (_X_PRIOR_HIGH - _X_PRIOR_LOW)
    return mean, max(0.0, variance), evidence


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


def _coprime_multiplier(size: int, seed: int, *keys: str | int) -> int:
    candidate = 1 + int(uniform01(seed, *keys, "multiplier") * max(1, size - 1))
    while math.gcd(candidate, size) != 1:
        candidate = 1 + (candidate % max(1, size - 1))
    return candidate


def _permuted_rank(
    ordinal: int, size: int, seed: int, *keys: str | int
) -> int:
    if not 0 <= ordinal < size:
        raise ValueError("quota ordinal outside population")
    multiplier = _coprime_multiplier(size, seed, *keys)
    offset = int(uniform01(seed, *keys, "offset") * size) % size
    return (multiplier * ordinal + offset) % size


def _balanced_counts(total: int, labels: tuple[str, ...]) -> dict[str, int]:
    quotient, remainder = divmod(total, len(labels))
    return {
        label: quotient + int(index < remainder)
        for index, label in enumerate(labels)
    }


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
    def _tail_position(split: WorldSplit, generator_seed: int, block: int) -> int:
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
        return min(range(64), key=lambda candidate: (scores[candidate], candidate))

    @staticmethod
    def is_population_tail(
        split: WorldSplit, generator_seed: int, episode_index: int
    ) -> bool:
        """One secret-permutation position per 64-row family block."""

        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        block, position = divmod(episode_index, 64)
        return position == W19World._tail_position(split, generator_seed, block)

    @classmethod
    def _class_ordinal(
        cls, split: WorldSplit, generator_seed: int, episode_index: int, tail: bool
    ) -> int:
        block, position = divmod(episode_index, 64)
        chosen = cls._tail_position(split, generator_seed, block)
        if tail:
            return block
        within_common = position - int(position > chosen)
        return block * 63 + within_common

    @classmethod
    def population_quota_manifest(cls, split: WorldSplit) -> dict[str, Any]:
        size = cls.population_size(split)
        tail = cls.expected_tail_count(split)
        common = size - tail
        # Small frozen splits cannot represent exactly .98 with binary rows.
        # Keep one false-negative in every split so both marker outcomes and
        # every safety branch have deterministic generator support.  These
        # finite-sample counts must not be fed back into the scoring kernel.
        tail_positive = max(1, tail - 1)
        common_positive = max(1, round(0.02 * common))
        return {
            "population": size,
            "tail": tail,
            "common": common,
            "tail_marker": {
                "positive": tail_positive,
                "negative": tail - tail_positive,
            },
            "common_marker": {
                "positive": common_positive,
                "negative": common - common_positive,
            },
            "actions": _balanced_counts(
                size, ("NoNewAction", "A1", "A2")
            ),
        }

    @classmethod
    def _marker_for_row(
        cls,
        split: WorldSplit,
        generator_seed: int,
        episode_index: int,
        tail: bool,
    ) -> int:
        manifest = cls.population_quota_manifest(split)
        class_name = "tail" if tail else "common"
        size = int(manifest[class_name])
        positive = int(manifest[f"{class_name}_marker"]["positive"])
        ordinal = cls._class_ordinal(split, generator_seed, episode_index, tail)
        rank = _permuted_rank(
            ordinal, size, generator_seed, "w19", split.value, class_name, "marker"
        )
        return int(rank < positive)

    @classmethod
    def _action_for_row(
        cls, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> tuple[str, tuple[float, float, float]]:
        manifest = cls.population_quota_manifest(split)
        size = cls.population_size(split)
        counts = manifest["actions"]
        rank = _permuted_rank(
            episode_index, size, generator_seed, "w19", split.value, "action"
        )
        boundaries = (
            int(counts["NoNewAction"]),
            int(counts["NoNewAction"]) + int(counts["A1"]),
        )
        action = (
            "NoNewAction" if rank < boundaries[0] else "A1" if rank < boundaries[1] else "A2"
        )
        probabilities = tuple(
            float(counts[label]) / size for label in ("NoNewAction", "A1", "A2")
        )
        return action, probabilities  # type: ignore[return-value]

    @staticmethod
    def _marker_posterior(marker: int | None) -> float:
        if marker is None:
            return _TAIL_RATE
        likelihood_tail = (
            _PUBLIC_MARKER_SENSITIVITY
            if marker == 1
            else 1.0 - _PUBLIC_MARKER_SENSITIVITY
        )
        likelihood_common = (
            _PUBLIC_MARKER_FALSE_POSITIVE_RATE
            if marker == 1
            else 1.0 - _PUBLIC_MARKER_FALSE_POSITIVE_RATE
        )
        numerator = _TAIL_RATE * likelihood_tail
        return numerator / (numerator + (1.0 - _TAIL_RATE) * likelihood_common)

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

    @staticmethod
    def posterior_solver_provenance() -> dict[str, str]:
        return {
            "production": "analytic-truncated-normal-v1",
            "reference": "independent-uniform-grid-v1",
        }

    def public_posterior(self, episode: PrivateEpisode) -> dict[str, float]:
        observations = tuple(
            float(event.payload["value"])
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_0"
        )
        x_mean, x_variance, evidence = _truncated_uniform_gaussian_moments(
            observations
        )
        p_tail = self._marker_posterior(_latest_marker(episode))
        return {
            "C0": 1.0 - p_tail,
            "C1": p_tail,
            "x_mean": x_mean,
            "x_variance": x_variance,
            "x_evidence": evidence,
        }

    def reference_public_posterior(self, episode: PrivateEpisode) -> dict[str, float]:
        """Independent grid integration; it shares no production moment code."""

        observations = tuple(
            float(event.payload["value"])
            for event in episode.public_history.events
            if event.kind is EventKind.OBSERVATION_AVAILABLE
            and event.payload.get("channel_id") == "obs_0"
        )
        cells = 40001
        width = (_X_PRIOR_HIGH - _X_PRIOR_LOW) / cells
        masses: list[float] = []
        xs: list[float] = []
        for index in range(cells):
            x = _X_PRIOR_LOW + (index + 0.5) * width
            exponent = -math.fsum((value - x) ** 2 for value in observations) / (
                2.0 * _OBS_SD**2
            )
            masses.append(math.exp(exponent))
            xs.append(x)
        total = math.fsum(masses)
        if total <= 0.0:
            raise ValueError("W19 reference posterior underflow")
        x_mean = math.fsum(x * mass for x, mass in zip(xs, masses)) / total
        x_variance = (
            math.fsum((x - x_mean) ** 2 * mass for x, mass in zip(xs, masses))
            / total
        )

        marker = _latest_marker(episode)
        # Independent reference integration uses the same frozen public
        # measurement contract, never the realized finite-split quota.
        sensitivity = 0.98
        false_positive = 0.02
        if marker is None:
            p_tail = _TAIL_RATE
        else:
            lt = sensitivity if marker else 1.0 - sensitivity
            lc = false_positive if marker else 1.0 - false_positive
            tail_mass = _TAIL_RATE * lt
            p_tail = tail_mass / (tail_mass + (1.0 - _TAIL_RATE) * lc)
        gaussian_constant = (1.0 / (_OBS_SD * math.sqrt(2.0 * math.pi))) ** len(
            observations
        )
        evidence = math.fsum(masses) / cells * gaussian_constant
        return {
            "C0": 1.0 - p_tail,
            "C1": p_tail,
            "x_mean": x_mean,
            "x_variance": x_variance,
            "x_evidence": evidence,
        }

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        if episode_index >= self.population_size(split):
            raise ValueError("population episode_index is outside the frozen split")
        tail = self.is_population_tail(split, generator_seed, episode_index)
        x = _X_PRIOR_LOW + (_X_PRIOR_HIGH - _X_PRIOR_LOW) * uniform01(
            generator_seed, "w19", split.value, episode_index, "x"
        )
        marker = self._marker_for_row(
            split, generator_seed, episode_index, tail
        )
        events = [
            _check_event(
                generator_seed,
                "Q1",
                -1,
                performed=False,
                slot=episode_index * 16 + 1,
            ),
            _check_event(
                generator_seed,
                "Q1",
                -1,
                performed=True,
                slot=episode_index * 16 + 2,
            ),
            _observation_event(
                generator_seed,
                "obs_1",
                marker,
                collected_at=-1,
                available_at=0,
                slot=episode_index * 16 + 3,
            ),
        ]
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
        action, probabilities = self._action_for_row(
            split, generator_seed, episode_index
        )
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
        # Scoring targets are public-history posterior probabilities rather
        # than the realized private tail bit.
        p_tail = self._marker_posterior(marker)
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
            },
            diagnostic_target={"C0": 1.0 - p_tail, "C1": p_tail},
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
                "quota_manifest": self.population_quota_manifest(split),
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
        belief = self.public_posterior(episode)
        p_tail = belief["C1"]
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
                belief["x_mean"], belief["x_variance"], tail, schedule, check_cost
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
        ordered = (
            component_utilities
            if component_utilities[0][0] <= component_utilities[1][0]
            else [component_utilities[1], component_utilities[0]]
        )
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
        truth = self.tail_truth(episode, policy, horizon)
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
                "common_expected_utility": _json_float(
                    truth.common_expected_utility
                ),
                "tail_expected_utility": _json_float(truth.tail_expected_utility),
                "tail_best_expected_utility": _json_float(
                    truth.tail_best_expected_utility
                ),
                "tail_only_regret": _json_float(truth.tail_only_regret),
                "tail_catastrophic_action_probability": _json_float(
                    truth.tail_catastrophic_action_probability
                ),
                "catastrophic_hard_gate_exposed": truth.catastrophic_hard_gate_exposed,
            },
            expected_utility=_json_float(expected),
            numerical_diagnostics={"method": "analytic-two-component-mixture", "absolute_error_bound": 0.0},
        )

    def _conditional_policy_utility(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        *,
        tail: bool,
    ) -> tuple[float, bool]:
        belief = self.public_posterior(episode)
        schedule = _schedule(policy, horizon)
        check_cost = 0.08 if (
            policy.kind is PlanKind.ACTION_SEQUENCE
            and any(action.action_id == "Q1" for action in policy.actions)
        ) else 0.0
        utility, _, catastrophe = self._component_utility(
            belief["x_mean"],
            belief["x_variance"],
            tail,
            schedule,
            check_cost,
        )
        return utility, catastrophe

    def tail_truth(
        self, episode: PrivateEpisode, policy: ActionPlan, horizon: int
    ) -> W19TailTruth:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W19 horizon")
        posterior = self.public_posterior(episode)
        common_utility, _ = self._conditional_policy_utility(
            episode, policy, horizon, tail=False
        )
        tail_utility, tail_catastrophe = self._conditional_policy_utility(
            episode, policy, horizon, tail=True
        )
        tail_best = max(
            self._conditional_policy_utility(
                episode, candidate, horizon, tail=True
            )[0]
            for candidate in self.policy_set(horizon)
        )
        tail_regret = max(0.0, tail_best - tail_utility)
        p_tail = posterior["C1"]
        return W19TailTruth(
            posterior_tail_probability=p_tail,
            common_expected_utility=common_utility,
            tail_expected_utility=tail_utility,
            tail_best_expected_utility=tail_best,
            tail_only_regret=tail_regret,
            posterior_catastrophic_action_probability=(
                p_tail if tail_catastrophe else 0.0
            ),
            tail_catastrophic_action_probability=float(tail_catastrophe),
            catastrophic_hard_gate_exposed=tail_catastrophe and tail_regret >= 10.0,
        )

    def reference_counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        """Independent analytic implementation for oracle certification."""

        del oracle_seed
        if horizon not in (1, 4, 8):
            raise ValueError("unsupported W19 horizon")
        x_observations: list[float] = []
        marker: int | None = None
        for event in episode.public_history.events:
            if event.kind is not EventKind.OBSERVATION_AVAILABLE:
                continue
            if event.payload.get("channel_id") == "obs_0":
                x_observations.append(float(event.payload["value"]))
            elif event.payload.get("channel_id") == "obs_1":
                marker = int(event.payload["value"])
        if not x_observations:
            raise ValueError("missing obs_0")

        count = len(x_observations)
        center = math.fsum(x_observations) / count
        posterior_sd = 0.05 / math.sqrt(count)
        alpha = (0.20 - center) / posterior_sd
        beta = (1.30 - center) / posterior_sd
        cdf_alpha = 0.5 * (1.0 + math.erf(alpha / math.sqrt(2.0)))
        cdf_beta = 0.5 * (1.0 + math.erf(beta / math.sqrt(2.0)))
        normalization = cdf_beta - cdf_alpha
        pdf_alpha = math.exp(-0.5 * alpha * alpha) / math.sqrt(2.0 * math.pi)
        pdf_beta = math.exp(-0.5 * beta * beta) / math.sqrt(2.0 * math.pi)
        ratio = (pdf_alpha - pdf_beta) / normalization
        start_mean = center + posterior_sd * ratio
        start_variance = posterior_sd**2 * (
            1.0
            + (alpha * pdf_alpha - beta * pdf_beta) / normalization
            - ratio * ratio
        )

        # The reference path intentionally re-implements Bayes' rule, but its
        # inputs are the same frozen public marker kernel as production.  The
        # split-specific population quota is generator-only evidence.
        sensitivity = 0.98
        false_positive = 0.02
        if marker is None:
            p_tail = 1.0 / 64.0
        else:
            likelihood_tail = sensitivity if marker else 1.0 - sensitivity
            likelihood_common = false_positive if marker else 1.0 - false_positive
            tail_mass = (1.0 / 64.0) * likelihood_tail
            p_tail = tail_mass / (
                tail_mass + (63.0 / 64.0) * likelihood_common
            )

        selected_schedule = ["NoNewAction"] * horizon
        if policy.kind is PlanKind.ACTION_SEQUENCE:
            for planned in policy.actions:
                if planned.offset < horizon and planned.action_id in {"A1", "A2"}:
                    selected_schedule[planned.offset] = planned.action_id
        reference_q1 = False
        if policy.kind is PlanKind.ACTION_SEQUENCE:
            for planned in policy.actions:
                if planned.action_id == "Q1":
                    reference_q1 = True
                    break
        selected_check_cost = 0.08 if reference_q1 else 0.0

        def evaluate(
            is_tail: bool, actions: list[str], first_check_cost: float
        ) -> tuple[float, list[dict[str, Any]], bool]:
            mean = start_mean
            variance = start_variance
            utility = 0.0
            steps: list[dict[str, Any]] = []
            catastrophic = False
            for offset, action in enumerate(actions):
                effect = 0.0
                if action == "A1":
                    effect = 1.40 if is_tail else -0.50
                elif action == "A2":
                    effect = -0.22
                mean = 0.90 * mean + 0.12 + effect
                variance = 0.90**2 * variance + 0.04**2
                catastrophic = catastrophic or (is_tail and action == "A1")
                cost = mean * mean + variance
                cost += 0.05 * (action == "A1") + 0.08 * (action == "A2")
                if offset == 0:
                    cost += first_check_cost
                utility -= 0.97**offset * cost
                steps.append(
                    {
                        "offset": offset + 1,
                        "mean": 0.0 if mean == 0.0 else float(mean),
                        "variance": 0.0 if variance == 0.0 else float(variance),
                    }
                )
            if catastrophic:
                utility -= 30.0
            return utility, steps, catastrophic

        components: list[dict[str, Any]] = []
        component_utilities: list[tuple[float, float]] = []
        expected = 0.0
        selected_by_class: dict[bool, tuple[float, bool]] = {}
        for is_tail, weight in ((False, 1.0 - p_tail), (True, p_tail)):
            value, steps, catastrophic = evaluate(
                is_tail, selected_schedule, selected_check_cost
            )
            selected_by_class[is_tail] = (value, catastrophic)
            expected += weight * value
            component_utilities.append((value, weight))
            components.append(
                {
                    "class": "C1" if is_tail else "C0",
                    "weight": 0.0 if weight == 0.0 else float(weight),
                    "steps": steps,
                    "expected_utility": 0.0 if value == 0.0 else float(value),
                    "catastrophic_action": catastrophic,
                }
            )

        candidate_schedules: list[tuple[list[str], float]] = [
            (["NoNewAction"] * horizon, 0.0),
            (["A1"] + ["NoNewAction"] * (horizon - 1), 0.0),
            (["A2"] + ["NoNewAction"] * (horizon - 1), 0.0),
        ]
        if horizon > 1:
            candidate_schedules.extend(
                [(["A1"] * horizon, 0.0), (["A2"] * horizon, 0.0)]
            )
        candidate_schedules.append((["NoNewAction"] * horizon, 0.08))
        tail_best = max(
            evaluate(True, actions, check)[0]
            for actions, check in candidate_schedules
        )
        tail_selected, tail_catastrophic = selected_by_class[True]
        common_selected = selected_by_class[False][0]
        tail_regret = max(0.0, tail_best - tail_selected)

        ordered = sorted(component_utilities, key=lambda item: item[0])
        worst = ordered[0][0]
        remaining = 0.05
        lower_sum = 0.0
        for value, weight in ordered:
            mass = min(weight, remaining)
            lower_sum += mass * value
            remaining -= mass
            if remaining <= 1e-15:
                break
        if remaining > 0.0:
            lower_sum += remaining * ordered[-1][0]
        cvar = lower_sum / 0.05
        catastrophic_probability = p_tail if tail_catastrophic else 0.0

        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "two-component-linear-gaussian",
                "components": components,
                "marker_posterior_tail": 0.0 if p_tail == 0.0 else float(p_tail),
            },
            latent_distribution={
                "family": "two-component-linear-gaussian",
                "components": components,
                "diagnostic_posterior": {"C0": 1.0 - p_tail, "C1": p_tail},
            },
            outcome_distribution={
                "expected_utility": 0.0 if expected == 0.0 else float(expected),
                "worst_component_utility": 0.0 if worst == 0.0 else float(worst),
                "lower_tail_cvar_95": 0.0 if cvar == 0.0 else float(cvar),
                "catastrophic_action_probability": 0.0
                if catastrophic_probability == 0.0
                else float(catastrophic_probability),
                "population_tail_rate": 1.0 / 64.0,
                "common_expected_utility": 0.0
                if common_selected == 0.0
                else float(common_selected),
                "tail_expected_utility": 0.0
                if tail_selected == 0.0
                else float(tail_selected),
                "tail_best_expected_utility": 0.0
                if tail_best == 0.0
                else float(tail_best),
                "tail_only_regret": 0.0
                if tail_regret == 0.0
                else float(tail_regret),
                "tail_catastrophic_action_probability": float(tail_catastrophic),
                "catastrophic_hard_gate_exposed": tail_catastrophic
                and tail_regret >= 10.0,
            },
            expected_utility=0.0 if expected == 0.0 else float(expected),
            numerical_diagnostics={
                "method": "reference-direct-truncated-mixture",
                "absolute_error_bound": 0.0,
            },
        )

    def _probe_episode(
        self,
        *,
        seed: int,
        probe_index: int,
        tail: bool,
        marker: int | None,
        shared_events: tuple | None = None,
        observed_x: float = 0.80,
    ) -> PrivateEpisode:
        x = observed_x
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
            },
        )
        return common, tail

    @staticmethod
    def population_membership(episode: PrivateEpisode) -> bool:
        return episode.invariant_parameters.get("cohort") == "population"

    def audit_population_quota(
        self, split: WorldSplit, generator_seed: int
    ) -> dict[str, Any]:
        audit = {
            "population": self.population_size(split),
            "tail": 0,
            "common": 0,
            "tail_marker": {"positive": 0, "negative": 0},
            "common_marker": {"positive": 0, "negative": 0},
            "actions": {"NoNewAction": 0, "A1": 0, "A2": 0},
        }
        for index in range(self.population_size(split)):
            tail = self.is_population_tail(split, generator_seed, index)
            label = "tail" if tail else "common"
            audit[label] += 1
            marker = self._marker_for_row(
                split, generator_seed, index, tail
            )
            audit[f"{label}_marker"]["positive" if marker else "negative"] += 1
            action, _ = self._action_for_row(split, generator_seed, index)
            audit["actions"][action] += 1
        return audit

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        strata = ["iid_support"]
        if bool(episode.invariant_parameters.get("tail", False)):
            strata.append("boundary_tail")
        if self.population_membership(episode):
            strata.append("policy_coverage_holdout")
        if episode.oracle_anchor.get("fixture") == "tail-probe":
            strata.append("behavior_pair")
        return tuple(strata)


World = W19World

__all__ = ["W19TailTruth", "W19World", "World"]
