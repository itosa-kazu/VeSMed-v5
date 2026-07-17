"""W01: fully observed stable linear control system.

The module also contains a few deliberately small construction helpers shared by
the other v1 microworld modules.  They only build protocol DTOs; no candidate
implementation or K0 code is imported here.
"""

from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable

import numpy as np

from ..canonical import canonical_json_bytes, digest_json
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
from .randomness import categorical, normal01, uniform01


_A = {
    0: np.array([[0.82, 0.10], [0.00, 0.75]], dtype=float),
    1: np.array([[0.92, 0.18], [-0.05, 0.80]], dtype=float),
}
_B = np.array([-0.35, 0.20], dtype=float)
_Q = np.diag([0.04**2, 0.04**2])
_U = {"A1": 1.0, "A2": -1.0}


def _json_float(value: float) -> float:
    """Convert numpy scalars and eliminate negative zero on the wire."""

    result = float(value)
    return 0.0 if result == 0.0 else result


def _opaque_uid(master_seed: int, *keys: str | int) -> str:
    """Return an opaque, distribution-independent event identifier."""

    payload = canonical_json_bytes([master_seed, *keys])
    return "e-" + hashlib.sha256(b"UCM_EVENT_UID_V1\0" + payload).hexdigest()[:24]


def _split_rng_seed(master_seed: int, split: WorldSplit) -> int:
    """Domain-separate split tapes while retaining the caller seed in ledgers."""

    payload = canonical_json_bytes([master_seed, split.value])
    return int.from_bytes(
        hashlib.sha256(b"UCM_WORLD_SPLIT_SEED_V1\0" + payload).digest()[:16],
        "big",
    )


def _observation_event(
    master_seed: int,
    channel_id: str,
    value: float | int,
    *,
    collected_at: int,
    available_at: int,
    slot: int = 0,
) -> CandidateVisibleEvent:
    return CandidateVisibleEvent(
        kind=EventKind.OBSERVATION_AVAILABLE,
        occurred_at=collected_at,
        collected_at=collected_at,
        available_at=available_at,
        event_uid=_opaque_uid(
            master_seed, "observation", channel_id, collected_at, available_at, slot
        ),
        payload={"channel_id": channel_id, "value": _json_float(value)},
    )


def _treatment_event(
    master_seed: int,
    action_id: str,
    occurred_at: int,
    *,
    slot: int = 0,
) -> CandidateVisibleEvent:
    return CandidateVisibleEvent(
        kind=EventKind.PERFORMED_TREATMENT,
        occurred_at=occurred_at,
        collected_at=None,
        available_at=occurred_at,
        event_uid=_opaque_uid(master_seed, "treatment", action_id, occurred_at, slot),
        payload={"action_id": action_id, "parameters": {}},
    )


def _check_event(
    master_seed: int,
    check_id: str,
    occurred_at: int,
    *,
    performed: bool,
    slot: int = 0,
) -> CandidateVisibleEvent:
    kind = EventKind.TEST_PERFORMED if performed else EventKind.TEST_ORDERED
    return CandidateVisibleEvent(
        kind=kind,
        occurred_at=occurred_at,
        collected_at=occurred_at if performed else None,
        available_at=occurred_at,
        event_uid=_opaque_uid(
            master_seed,
            "check-performed" if performed else "check-ordered",
            check_id,
            occurred_at,
            slot,
        ),
        payload={"check_id": check_id},
    )


def _visible_history(
    events: Iterable[CandidateVisibleEvent],
    catalog: PublicCatalog,
    *,
    as_of: int = 0,
) -> VisibleHistory:
    available = tuple(
        sorted(
            (event for event in events if event.available_at <= as_of),
            key=event_sort_key,
        )
    )
    return VisibleHistory(
        events=available,
        as_of_available_at=as_of,
        catalog_digest=catalog.digest,
    )


def _softmax(logits: tuple[float, ...]) -> tuple[float, ...]:
    offset = max(logits)
    raw = tuple(math.exp(value - offset) for value in logits)
    total = math.fsum(raw)
    return tuple(value / total for value in raw)


def _exploratory_probabilities(
    base: tuple[float, ...], exploration: float = 0.10
) -> tuple[float, ...]:
    uniform = 1.0 / len(base)
    return tuple((1.0 - exploration) * value + exploration * uniform for value in base)


def _constant_plan(action_id: str, horizon: int) -> ActionPlan:
    return ActionPlan(
        PlanKind.ACTION_SEQUENCE,
        tuple(PlannedAction(offset, action_id) for offset in range(horizon)),
    )


def _single_plan(action_id: str) -> ActionPlan:
    return ActionPlan(
        PlanKind.ACTION_SEQUENCE,
        (PlannedAction(0, action_id),),
    )


def _check_plan(
    check_id: str, parameters: dict[str, Any] | None = None
) -> ActionPlan:
    return ActionPlan(
        PlanKind.ACTION_SEQUENCE,
        (PlannedAction(0, check_id, parameters or {}),),
    )


def _standard_policy_set(
    horizon: int,
    *,
    treatments: tuple[str, ...] = ("A1", "A2"),
    checks: tuple[str, ...] = (),
) -> tuple[ActionPlan, ...]:
    policies: list[ActionPlan] = [ActionPlan(PlanKind.NO_NEW_ACTION)]
    policies.extend(_single_plan(action) for action in treatments)
    if horizon > 1:
        policies.extend(_constant_plan(action, horizon) for action in treatments)
    policies.extend(_check_plan(check) for check in checks)
    return tuple(policies)


def _treatment_schedule(policy: ActionPlan, horizon: int) -> tuple[float, ...]:
    schedule = [0.0] * horizon
    if policy.kind is PlanKind.ACTION_SEQUENCE:
        for action in policy.actions:
            if action.offset < horizon and action.action_id in _U:
                schedule[action.offset] = _U[action.action_id]
    return tuple(schedule)


def _last_observations(
    history: VisibleHistory, channel_id: str
) -> list[CandidateVisibleEvent]:
    return [
        event
        for event in history.events
        if event.kind is EventKind.OBSERVATION_AVAILABLE
        and event.payload.get("channel_id") == channel_id
    ]


def _case_key(environment_key: str, split: WorldSplit, seed: int, index: int) -> str:
    return digest_json(
        {
            "domain": "ucm-private-case-key/1",
            "environment": environment_key,
            "split": split.value,
            "seed": seed,
            "index": index,
        }
    )


class W01World(MicroWorld):
    """Executable W01 world and analytic all-policy oracle."""

    @property
    def environment_key(self) -> str:
        return "ucm-private-environment-01"

    @property
    def catalog(self) -> PublicCatalog:
        return PublicCatalog(
            observations=(
                ChannelSpec("obs_0", valid_range=None),
                ChannelSpec("obs_1", valid_range=None),
                ChannelSpec("obs_2", value_type="categorical", unit="class-index", valid_range=(0, 1)),
            ),
            actions=(ActionSpec("A1", cost=0.05), ActionSpec("A2", cost=0.05)),
            checks=(CheckSpec("Q0", ("obs_0", "obs_1", "obs_2"), (0, 0), cost=0.0),),
            diagnostic_labels=("C0", "C1"),
            horizons=(1, 4, 8),
        )

    def policy_set(self, horizon: int) -> tuple[ActionPlan, ...]:
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W01 horizon")
        return _standard_policy_set(horizon, checks=("Q0",))

    def _initial_state(
        self, split: WorldSplit, seed: int, episode_index: int
    ) -> tuple[int, np.ndarray]:
        if episode_index < 0:
            raise ValueError("episode_index must be non-negative")
        cell = episode_index % 8
        class_index = cell // 4
        sign_bits = cell % 4
        if split is WorldSplit.TRAIN:
            radius = 1.0
        elif split is WorldSplit.VALIDATION:
            radius = 1.15
        elif episode_index % 5 == 0:
            # Boundary-shell fifth; the larger coordinate is forced outside 1.15.
            outer = 1.15 + 0.20 * uniform01(seed, "w01", "shell", episode_index)
            inner = 1.15 * uniform01(seed, "w01", "inner", episode_index)
            if (episode_index // 5) % 2:
                state = np.array([inner, outer], dtype=float)
            else:
                state = np.array([outer, inner], dtype=float)
            state[0] *= -1.0 if sign_bits & 1 else 1.0
            state[1] *= -1.0 if sign_bits & 2 else 1.0
            return class_index, state
        else:
            radius = 1.15
        state = np.array(
            [
                radius * uniform01(seed, "w01", "x", episode_index, 0)
                * (-1.0 if sign_bits & 1 else 1.0),
                radius * uniform01(seed, "w01", "x", episode_index, 1)
                * (-1.0 if sign_bits & 2 else 1.0),
            ],
            dtype=float,
        )
        return class_index, state

    @staticmethod
    def _action_probabilities(y: float) -> tuple[float, float, float]:
        return _exploratory_probabilities(_softmax((0.0, 1.2 * y, -1.2 * y)))

    def generate_episode(
        self, split: WorldSplit, generator_seed: int, episode_index: int
    ) -> PrivateEpisode:
        requested_seed = generator_seed
        generator_seed = _split_rng_seed(generator_seed, split)
        c, state = self._initial_state(split, generator_seed, episode_index)
        events: list[CandidateVisibleEvent] = []
        propensities: list[dict[str, Any]] = []
        history_actions: dict[int, str] = {}

        for tick in range(-4, 1):
            for slot, (channel, value) in enumerate(
                (("obs_0", state[0]), ("obs_1", state[1]), ("obs_2", c))
            ):
                events.append(
                    _observation_event(
                        generator_seed,
                        channel,
                        value,
                        collected_at=tick,
                        available_at=tick,
                        slot=episode_index * 32 + slot,
                    )
                )
            if tick == 0:
                break
            probabilities = self._action_probabilities(float(state[0]))
            action_index = categorical(
                probabilities, generator_seed, "w01", "behavior", episode_index, tick
            )
            action_id = ("NoNewAction", "A1", "A2")[action_index]
            propensities.append(
                {
                    "decision_at": tick,
                    "probabilities": {
                        "NoNewAction": probabilities[0],
                        "A1": probabilities[1],
                        "A2": probabilities[2],
                    },
                    "selected": action_id,
                }
            )
            history_actions[tick] = action_id
            if action_id != "NoNewAction":
                events.append(
                    _treatment_event(
                        generator_seed,
                        action_id,
                        tick,
                        slot=episode_index * 32,
                    )
                )
            u = _U.get(action_id, 0.0)
            noise = np.array(
                [
                    0.04
                    * normal01(
                        generator_seed, "w01", "process", episode_index, tick + 1, dim
                    )
                    for dim in range(2)
                ]
            )
            state = _A[c] @ state + _B * u + noise

        state_at_cut = state.copy()
        public_history = _visible_history(events, self.catalog)

        factual_state = state.copy()
        future: list[dict[str, Any]] = []
        factual_utility = 0.0
        for offset in range(4):
            probabilities = self._action_probabilities(float(factual_state[0]))
            action_index = categorical(
                probabilities,
                generator_seed,
                "w01",
                "factual-future-action",
                episode_index,
                offset,
            )
            action_id = ("NoNewAction", "A1", "A2")[action_index]
            u = _U.get(action_id, 0.0)
            noise = np.array(
                [
                    0.04
                    * normal01(
                        generator_seed,
                        "w01",
                        "factual-future-process",
                        episode_index,
                        offset,
                        dim,
                    )
                    for dim in range(2)
                ]
            )
            factual_state = _A[c] @ factual_state + _B * u + noise
            step_cost = factual_state[0] ** 2 + 0.5 * factual_state[1] ** 2 + 0.05 * u**2
            factual_utility -= 0.97**offset * float(step_cost)
            future.append(
                {
                    "offset": offset + 1,
                    "observations": {
                        "obs_0": _json_float(factual_state[0]),
                        "obs_1": _json_float(factual_state[1]),
                        "obs_2": c,
                    },
                    "performed_action": action_id,
                }
            )

        return PrivateEpisode(
            case_key=_case_key(self.environment_key, split, generator_seed, episode_index),
            environment_key=self.environment_key,
            split=split,
            generator_seed=requested_seed,
            public_history=public_history,
            hidden_state_at_cut={"x": [_json_float(v) for v in state_at_cut]},
            invariant_parameters={"class_index": c},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=future,
            action_propensities=propensities,
            factual_utility=_json_float(factual_utility),
            oracle_anchor={
                "posterior_source": "exact-public-panel",
                "policy_count_by_horizon": {
                    str(h): len(self.policy_set(h)) for h in self.catalog.horizons
                },
                "strata": [
                    "iid_support",
                    *(
                        ["boundary_tail"]
                        if split is WorldSplit.SEALED_TEST
                        and episode_index % 5 == 0
                        else []
                    ),
                ],
            },
        )

    def strata_for_episode(self, episode: PrivateEpisode) -> tuple[str, ...]:
        """Return the exact judge-side generator cell for registry materialization."""

        value = episode.oracle_anchor.get("strata")
        if type(value) is not list or not value or any(type(item) is not str for item in value):
            raise ValueError("W01 episode lacks exact generator strata")
        result = tuple(value)
        if result not in {("iid_support",), ("iid_support", "boundary_tail")}:
            raise ValueError("W01 episode declares an impossible generator stratum")
        return result

    def _public_cut_state(self, episode: PrivateEpisode) -> tuple[int, np.ndarray]:
        latest = {
            channel: _last_observations(episode.public_history, channel)[-1].payload[
                "value"
            ]
            for channel in ("obs_0", "obs_1", "obs_2")
        }
        return int(latest["obs_2"]), np.array([latest["obs_0"], latest["obs_1"]])

    def counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        del oracle_seed  # analytic integration has no random traversal order
        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W01 horizon")
        c, mean = self._public_cut_state(episode)
        return self._counterfactual_from_state(c, mean, policy, horizon)

    def judge_true_state_counterfactual(
        self,
        hidden_state_at_cut: dict[str, Any],
        invariant_parameters: dict[str, Any],
        policy: ActionPlan,
        horizon: int,
    ) -> CounterfactualOracle:
        """Evaluate W01 from the judge-only Markov state.

        This is the Phase-2 true-state upper-bound path.  It is deliberately
        separate from :meth:`counterfactual`, whose production scoring path is
        a function of the candidate-visible cut only.  Ordinary candidates
        must never receive either private mapping.
        """

        if horizon not in self.catalog.horizons:
            raise ValueError("unsupported W01 horizon")
        if set(hidden_state_at_cut) != {"x"}:
            raise ValueError("W01 private state must contain exactly x")
        if set(invariant_parameters) != {"class_index"}:
            raise ValueError("W01 private parameters must contain class_index")
        raw_state = hidden_state_at_cut["x"]
        class_index = invariant_parameters["class_index"]
        if (
            type(raw_state) is not list
            or len(raw_state) != 2
            or any(type(value) not in {int, float} for value in raw_state)
            or any(not math.isfinite(float(value)) for value in raw_state)
        ):
            raise ValueError("W01 private x must be two finite numbers")
        if type(class_index) is not int or class_index not in {0, 1}:
            raise ValueError("W01 private class_index must be zero or one")
        return self._counterfactual_from_state(
            class_index,
            np.asarray(raw_state, dtype=float),
            policy,
            horizon,
        )

    def _counterfactual_from_state(
        self,
        c: int,
        mean: np.ndarray,
        policy: ActionPlan,
        horizon: int,
    ) -> CounterfactualOracle:
        """Shared analytic transition used by public and judge-only entry paths."""

        if policy not in self.policy_set(horizon):
            raise ValueError("policy is outside the finite W01 policy set")
        covariance = np.zeros((2, 2), dtype=float)
        schedule = _treatment_schedule(policy, horizon)
        steps: list[dict[str, Any]] = []
        expected_utility = 0.0
        for offset, u in enumerate(schedule):
            mean = _A[c] @ mean + _B * u
            covariance = _A[c] @ covariance @ _A[c].T + _Q
            expected_cost = (
                mean[0] ** 2
                + covariance[0, 0]
                + 0.5 * (mean[1] ** 2 + covariance[1, 1])
                + 0.05 * u**2
            )
            expected_utility -= 0.97**offset * float(expected_cost)
            steps.append(
                {
                    "offset": offset + 1,
                    "mean": [_json_float(v) for v in mean],
                    "covariance": [
                        [_json_float(v) for v in row] for row in covariance
                    ],
                }
            )
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "joint-gaussian",
                "channels": ["obs_0", "obs_1"],
                "steps": steps,
                "obs_2_point_mass": c,
            },
            latent_distribution={
                "family": "joint-gaussian",
                "state_channels": ["x0", "x1"],
                "steps": steps,
                "diagnostic_posterior": {"C0": float(c == 0), "C1": float(c == 1)},
            },
            outcome_distribution={
                "utility_family": "quadratic-form-of-gaussian",
                "expected_utility": _json_float(expected_utility),
            },
            expected_utility=_json_float(expected_utility),
            numerical_diagnostics={
                "method": "analytic-linear-gaussian",
                "absolute_error_bound": 0.0,
                "spectral_radius": _json_float(max(abs(np.linalg.eigvals(_A[c])))),
            },
        )

    def reference_counterfactual(
        self,
        episode: PrivateEpisode,
        policy: ActionPlan,
        horizon: int,
        oracle_seed: int,
    ) -> CounterfactualOracle:
        """Independent scalar moment recursion from the public cut panel.

        This reference intentionally does not call ``_public_cut_state``,
        ``_treatment_schedule``, ``_json_float`` or the production oracle.  It
        expands the two-dimensional Gaussian recurrence into scalar equations,
        providing a source-distinct freeze-time check of the analytic path.
        """

        del oracle_seed
        if horizon not in (1, 4, 8):
            raise ValueError("unsupported W01 horizon")
        latest: dict[str, float] = {}
        for event in episode.public_history.events:
            if event.kind is EventKind.OBSERVATION_AVAILABLE:
                channel = event.payload.get("channel_id")
                if channel in {"obs_0", "obs_1", "obs_2"}:
                    latest[str(channel)] = float(event.payload["value"])
        if set(latest) != {"obs_0", "obs_1", "obs_2"}:
            raise ValueError("W01 reference requires a complete public cut panel")
        mechanism = int(latest["obs_2"])
        if mechanism not in (0, 1):
            raise ValueError("W01 public mechanism value must be binary")
        matrix = (
            ((0.82, 0.10), (0.00, 0.75))
            if mechanism == 0
            else ((0.92, 0.18), (-0.05, 0.80))
        )
        doses = [0.0 for _ in range(horizon)]
        if policy.kind is PlanKind.ACTION_SEQUENCE:
            for action in policy.actions:
                if action.offset < horizon:
                    if action.action_id == "A1":
                        doses[action.offset] = 1.0
                    elif action.action_id == "A2":
                        doses[action.offset] = -1.0

        mean0, mean1 = latest["obs_0"], latest["obs_1"]
        c00 = c01 = c10 = c11 = 0.0
        utility = 0.0
        steps: list[dict[str, Any]] = []
        a00, a01 = matrix[0]
        a10, a11 = matrix[1]
        for offset, dose in enumerate(doses):
            prior0, prior1 = mean0, mean1
            mean0 = a00 * prior0 + a01 * prior1 - 0.35 * dose
            mean1 = a10 * prior0 + a11 * prior1 + 0.20 * dose
            t00 = a00 * c00 + a01 * c10
            t01 = a00 * c01 + a01 * c11
            t10 = a10 * c00 + a11 * c10
            t11 = a10 * c01 + a11 * c11
            c00 = t00 * a00 + t01 * a01 + 0.04**2
            c01 = t00 * a10 + t01 * a11
            c10 = t10 * a00 + t11 * a01
            c11 = t10 * a10 + t11 * a11 + 0.04**2
            utility -= 0.97**offset * (
                mean0 * mean0 + c00 + 0.5 * (mean1 * mean1 + c11) + 0.05 * dose * dose
            )
            steps.append(
                {
                    "offset": offset + 1,
                    "mean": [0.0 if mean0 == 0.0 else mean0, 0.0 if mean1 == 0.0 else mean1],
                    "covariance": [
                        [0.0 if c00 == 0.0 else c00, 0.0 if c01 == 0.0 else c01],
                        [0.0 if c10 == 0.0 else c10, 0.0 if c11 == 0.0 else c11],
                    ],
                }
            )
        utility = 0.0 if utility == 0.0 else float(utility)
        posterior = {
            "C0": float(mechanism == 0),
            "C1": float(mechanism == 1),
        }
        return CounterfactualOracle(
            policy=policy,
            horizon=horizon,
            observation_distribution={
                "family": "joint-gaussian",
                "channels": ["obs_0", "obs_1"],
                "steps": steps,
                "obs_2_point_mass": mechanism,
            },
            latent_distribution={
                "family": "joint-gaussian",
                "state_channels": ["x0", "x1"],
                "steps": steps,
                "diagnostic_posterior": posterior,
            },
            outcome_distribution={
                "utility_family": "quadratic-form-of-gaussian",
                "expected_utility": utility,
            },
            expected_utility=utility,
            numerical_diagnostics={
                "method": "independent-scalar-gaussian-moment-recursion",
                "absolute_error_bound": 0.0,
                "spectral_radius_verified": True,
            },
        )

    def _episode_from_public_state(
        self,
        state: tuple[float, float],
        c: int,
        seed: int,
        *,
        uid_salt: int,
    ) -> PrivateEpisode:
        events = [
            _observation_event(
                seed + uid_salt,
                channel,
                value,
                collected_at=0,
                available_at=0,
                slot=slot,
            )
            for slot, (channel, value) in enumerate(
                (("obs_0", state[0]), ("obs_1", state[1]), ("obs_2", c))
            )
        ]
        return PrivateEpisode(
            case_key=_case_key(self.environment_key, WorldSplit.SEALED_TEST, seed, uid_salt),
            environment_key=self.environment_key,
            split=WorldSplit.SEALED_TEST,
            generator_seed=seed,
            public_history=_visible_history(events, self.catalog),
            hidden_state_at_cut={"x": [state[0], state[1]]},
            invariant_parameters={"class_index": c},
            diagnostic_target={"C0": float(c == 0), "C1": float(c == 1)},
            factual_future=[],
            action_propensities=[],
            factual_utility=0.0,
            oracle_anchor={"fixture": "paired", "strata": ["iid_support"]},
        )

    def collision_fixture(self, seed: int = 101) -> tuple[PrivateEpisode, PrivateEpisode]:
        """A visible-state pair whose utility-optimal action directions differ."""

        v = 0.55 + 0.40 * uniform01(seed, "w01", "collision-v")
        return (
            self._episode_from_public_state((v, -v / 2.0), 0, seed, uid_salt=1),
            self._episode_from_public_state((-v, v / 2.0), 0, seed, uid_salt=2),
        )

    def false_split_fixture(self, seed: int = 103) -> tuple[PrivateEpisode, PrivateEpisode]:
        """Same public clinical facts under an alpha-renaming of opaque UIDs."""

        state = (0.625, -0.25)
        return (
            self._episode_from_public_state(state, 1, seed, uid_salt=11),
            self._episode_from_public_state(state, 1, seed, uid_salt=29),
        )


World = W01World


__all__ = ["W01World", "World"]
