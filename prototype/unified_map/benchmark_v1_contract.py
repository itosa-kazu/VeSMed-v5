"""Executable, candidate-neutral contract for the frozen UCM benchmark v1.

The earlier PRE-FREEZE work proved that W01--W20 are executable, but it also
tried to translate every line of Python world semantics into a second typed
language.  That is useful assurance research, not a prerequisite for running
the patient-world-model experiment requested by the project.  This module is
the deliberately small executable contract that is frozen before candidate
implementations exist.

The judge may use a ``MicroWorld`` and its private ``CounterfactualOracle`` to
build training/evaluation targets.  Candidate code receives only public
histories, public catalogs, trainer targets, non-patient queries and one
serialized shared patient state.  Diagnosis and rollout heads never receive a
history.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .schema import ActionPlan, VisibleDelta, VisibleHistory
from .worlds.base import CounterfactualOracle, MicroWorld, PrivateEpisode, PublicCatalog


CONTRACT_SCHEMA = "ucm-benchmark-v1-executable-contract/1"
BENCHMARK_ID = "UCM-BENCHMARK-v1"
SIGNATURE_DIMENSION = 32
STATE_DISTANCE_EPSILON = 1e-9
STATE_SPLIT_DELTA = 1e-3
ORACLE_EQUIVALENT_EPSILON = 1e-9
ORACLE_DISTINGUISHABLE_DELTA = 0.05
CATASTROPHIC_UTILITY_MARGIN = 0.25
PROBABILITY_CLIP = 1e-12


METRIC_CONTRACTS: tuple[dict[str, Any], ...] = (
    {
        "measurement_id": "M01",
        "name": "diagnosis_accuracy_and_calibration",
        "outputs": ("top1_accuracy", "cross_entropy_nll", "multiclass_brier"),
        "direction": ("maximize", "minimize", "minimize"),
    },
    {
        "measurement_id": "M02",
        "name": "natural_history_forecast_error",
        "outputs": ("signature_rmse", "utility_absolute_error"),
        "direction": ("minimize", "minimize"),
    },
    {
        "measurement_id": "M03",
        "name": "post_intervention_trajectory_error",
        "outputs": ("signature_rmse", "utility_absolute_error"),
        "direction": ("minimize", "minimize"),
    },
    {
        "measurement_id": "M04",
        "name": "treatment_selection_regret",
        "outputs": ("regret", "catastrophic_action"),
        "direction": ("minimize", "hard_fail_when_true"),
    },
    {
        "measurement_id": "M05",
        "name": "state_collision_rate",
        "outputs": ("dangerous_collision_rate", "max_missed_oracle_distance"),
        "direction": ("hard_fail_if_attributable", "minimize"),
    },
    {
        "measurement_id": "M06",
        "name": "functional_false_split_rate",
        "outputs": ("false_split_rate",),
        "direction": ("minimize",),
    },
    {
        "measurement_id": "M07",
        "name": "ood_unknown_recognition",
        "outputs": ("unknown_brier", "known_coverage", "unsafe_non_abstain_rate"),
        "direction": ("minimize", "maximize", "hard_fail_if_positive"),
    },
    {
        "measurement_id": "M08",
        "name": "temporal_leakage",
        "outputs": ("old_cut_instability", "future_access_violation"),
        "direction": ("hard_fail_if_positive", "hard_fail_if_positive"),
    },
    {
        "measurement_id": "M09",
        "name": "sample_efficiency",
        "outputs": ("log_sample_auc",),
        "direction": ("maximize",),
    },
    {
        "measurement_id": "M10",
        "name": "novel_mechanism_combination_generalization",
        "outputs": ("heldout_combination_gap",),
        "direction": ("minimize",),
    },
    {
        "measurement_id": "M11",
        "name": "new_check_and_treatment_extension_cost",
        "outputs": ("changed_core_lines", "retrain_examples", "old_scope_regression"),
        "direction": ("minimize", "minimize", "minimize"),
    },
    {
        "measurement_id": "M12",
        "name": "state_dimension_or_description_length",
        "outputs": ("canonical_state_bytes", "distance_dimension"),
        "direction": ("minimize", "minimize"),
    },
    {
        "measurement_id": "M13",
        "name": "inference_time_and_memory",
        "outputs": ("initialize_ms", "head_ms", "peak_memory_bytes"),
        "direction": ("minimize", "minimize", "minimize"),
    },
    {
        "measurement_id": "M14",
        "name": "multi_seed_stability",
        "outputs": ("seed_standard_deviation", "seed_worst_case"),
        "direction": ("minimize", "report"),
    },
    {
        "measurement_id": "M15",
        "name": "update_consistency",
        "outputs": ("incremental_replay_match", "query_order_purity"),
        "direction": ("hard_fail_if_false", "hard_fail_if_false"),
    },
    {
        "measurement_id": "M16",
        "name": "sealed_state_novel_readout_transfer",
        "outputs": ("new_readout_error", "history_reread_violation"),
        "direction": ("minimize", "hard_fail_if_true"),
    },
)


def metric_contract_wire() -> dict[str, Any]:
    """Return a fresh JSON-like preimage of all sixteen frozen measurements."""

    return {
        "schema_version": CONTRACT_SCHEMA,
        "benchmark_id": BENCHMARK_ID,
        "aggregation": {
            "raw_grain": "episode+policy+horizon+world+panel+model_seed",
            "within_world": "arithmetic_mean_over_required_rows",
            "across_worlds": "equal_weight_world_macro",
            "seed_summary": "mean_sd_min_max_and_student_t_95ci_for_five_seeds",
            "single_compensating_score": "forbidden",
        },
        "undefined": {
            "nan_or_infinity": "protocol_failure",
            "empty_denominator": "typed_null_with_zero_exposure",
            "metric_imputation": "forbidden",
        },
        "thresholds": {
            "state_distance_epsilon": STATE_DISTANCE_EPSILON,
            "state_split_delta": STATE_SPLIT_DELTA,
            "oracle_equivalent_epsilon": ORACLE_EQUIVALENT_EPSILON,
            "oracle_distinguishable_delta": ORACLE_DISTINGUISHABLE_DELTA,
            "catastrophic_utility_margin": CATASTROPHIC_UTILITY_MARGIN,
        },
        "measurements": [
            {
                "measurement_id": row["measurement_id"],
                "name": row["name"],
                "outputs": list(row["outputs"]),
                "direction": list(row["direction"]),
            }
            for row in METRIC_CONTRACTS
        ],
    }


def _finite(value: object, label: str) -> float:
    if type(value) not in {int, float} or not math.isfinite(float(value)):
        raise ProtocolViolation(f"{label} must be finite numeric")
    return float(value)


def _probabilities(value: dict[str, float], labels: Sequence[str]) -> dict[str, float]:
    if type(value) is not dict or set(value) != set(labels):
        raise ProtocolViolation("diagnosis output must match the public label catalog")
    result = {label: _finite(value[label], f"probability {label}") for label in labels}
    if any(number < 0.0 or number > 1.0 for number in result.values()):
        raise ProtocolViolation("diagnosis probabilities must lie in [0,1]")
    if not math.isclose(math.fsum(result.values()), 1.0, abs_tol=1e-9, rel_tol=0.0):
        raise ProtocolViolation("diagnosis probabilities must sum to one")
    return result


def policy_key(plan: ActionPlan, horizon: int) -> str:
    if type(plan) is not ActionPlan or type(horizon) is not int or horizon <= 0:
        raise ProtocolViolation("policy_key requires one typed plan and positive horizon")
    return digest_json(
        {
            "protocol": "ucm-benchmark-v1-policy-key/1",
            "horizon": horizon,
            "plan": plan.to_wire(),
        }
    )


def _project_numeric(value: object, path: str, bins: list[float]) -> None:
    """Hash-project numeric oracle means/probabilities into a fixed public target.

    Variance/covariance and diagnostics are intentionally excluded: benchmark v1
    evaluates the central trajectory and utility, while calibration is measured
    on diagnosis.  The stable path hash prevents heterogeneous world DTO shapes
    from becoming task-specific candidate APIs.
    """

    lowered = path.lower()
    if any(token in lowered for token in ("variance", "covariance", "diagnostic")):
        return
    if type(value) is bool or value is None or type(value) is str:
        return
    if type(value) in {int, float}:
        number = _finite(value, f"oracle numeric leaf {path}")
        digest = hashlib.sha256(b"UCM_SIGNATURE_V1\0" + path.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % SIGNATURE_DIMENSION
        sign = -1.0 if digest[4] & 1 else 1.0
        bins[index] += sign * number
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _project_numeric(item, f"{path}[{index}]", bins)
        return
    if type(value) is dict:
        for key in sorted(value):
            _project_numeric(value[key], f"{path}.{key}", bins)
        return
    raise ProtocolViolation(f"oracle signature contains unsupported type at {path}")


def oracle_signature(oracle: CounterfactualOracle) -> tuple[float, ...]:
    if type(oracle) is not CounterfactualOracle:
        raise ProtocolViolation("oracle_signature is judge-only and requires oracle DTO")
    bins = [0.0] * SIGNATURE_DIMENSION
    _project_numeric(oracle.observation_distribution, "observation", bins)
    # Do not project expected utility twice; it has its own proper target.
    outcome = {
        key: value
        for key, value in oracle.outcome_distribution.items()
        if key != "expected_utility"
    }
    _project_numeric(outcome, "outcome", bins)
    return tuple(bins)


@dataclass(frozen=True, slots=True)
class RolloutTarget:
    horizon: int
    policy: ActionPlan
    signature: tuple[float, ...]
    expected_utility: float

    def __post_init__(self) -> None:
        if type(self.horizon) is not int or self.horizon <= 0:
            raise ProtocolViolation("rollout target horizon must be positive")
        if type(self.policy) is not ActionPlan:
            raise ProtocolViolation("rollout target policy must be ActionPlan")
        if type(self.signature) is not tuple or len(self.signature) != SIGNATURE_DIMENSION:
            raise ProtocolViolation("rollout target signature has wrong dimension")
        for value in self.signature:
            _finite(value, "rollout target signature")
        _finite(self.expected_utility, "rollout target utility")

    @property
    def query_key(self) -> str:
        return policy_key(self.policy, self.horizon)

    def to_wire(self) -> dict[str, Any]:
        return {
            "query_key": self.query_key,
            "horizon": self.horizon,
            "policy": self.policy.to_wire(),
            "signature": list(self.signature),
            "expected_utility": self.expected_utility,
        }


@dataclass(frozen=True, slots=True)
class PublicTrainingRecord:
    """Trainer-visible row; contains no simulator state or case/test identity."""

    history: VisibleHistory
    diagnostic_target: dict[str, float]
    rollouts: tuple[RolloutTarget, ...]

    def __post_init__(self) -> None:
        if type(self.history) is not VisibleHistory:
            raise ProtocolViolation("training record history must be visible history")
        _probabilities(self.diagnostic_target, tuple(self.diagnostic_target))
        if type(self.rollouts) is not tuple or not self.rollouts:
            raise ProtocolViolation("training record requires rollout targets")
        keys = tuple(item.query_key for item in self.rollouts)
        if len(keys) != len(set(keys)):
            raise ProtocolViolation("training record rollout targets must be unique")

    def to_wire(self) -> dict[str, Any]:
        return {
            "protocol": "ucm-benchmark-v1-public-training-record/1",
            "history": self.history.to_wire(),
            "diagnostic_target": self.diagnostic_target,
            "rollouts": [row.to_wire() for row in self.rollouts],
        }


def build_public_training_record(
    world: MicroWorld,
    episode: PrivateEpisode,
    *,
    oracle_seed: int,
) -> PublicTrainingRecord:
    """Judge-side projection that may use training oracles, never hidden state."""

    if not isinstance(world, MicroWorld) or type(episode) is not PrivateEpisode:
        raise ProtocolViolation("training projection requires one live world episode")
    rows: list[RolloutTarget] = []
    for horizon in world.catalog.horizons:
        for plan_index, plan in enumerate(world.policy_set(horizon)):
            oracle = world.counterfactual(
                episode,
                plan,
                horizon,
                oracle_seed + 1009 * horizon + plan_index,
            )
            rows.append(
                RolloutTarget(
                    horizon,
                    plan,
                    oracle_signature(oracle),
                    oracle.expected_utility,
                )
            )
    return PublicTrainingRecord(
        episode.public_history,
        dict(episode.diagnostic_target),
        tuple(rows),
    )


@dataclass(frozen=True, slots=True)
class SharedPatientState:
    """The only patient-specific object available to every candidate head."""

    schema_version: str
    payload: bytes
    distance_vector: tuple[float, ...]
    compactness_class: str = "candidate_shared_state"

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or not self.schema_version:
            raise ProtocolViolation("state schema_version must be non-empty")
        if type(self.payload) is not bytes:
            raise ProtocolViolation("state payload must be exact bytes")
        try:
            value = json.loads(self.payload.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ProtocolViolation("state payload must be canonical JSON") from exc
        if canonical_json_bytes(value) != self.payload:
            raise ProtocolViolation("state payload must be canonical JSON bytes")
        if type(self.distance_vector) is not tuple or not self.distance_vector:
            raise ProtocolViolation("state requires a non-empty distance vector")
        for number in self.distance_vector:
            _finite(number, "state distance vector")
        if self.compactness_class not in {
            "candidate_shared_state",
            "full_visible_history_baseline",
            "separate_task_baseline",
            "k0_only_baseline",
        }:
            raise ProtocolViolation("state compactness class is not code-owned")

    @property
    def state_hash(self) -> str:
        return digest_json(
            {
                "schema_version": self.schema_version,
                "payload_digest": digest_bytes(self.payload),
                "distance_vector": list(self.distance_vector),
                "compactness_class": self.compactness_class,
            }
        )

    @property
    def canonical_size_bytes(self) -> int:
        return len(self.payload)


@dataclass(frozen=True, slots=True)
class DiagnosisPrediction:
    probabilities: dict[str, float]

    def validate_for(self, catalog: PublicCatalog) -> "DiagnosisPrediction":
        if type(catalog) is not PublicCatalog:
            raise ProtocolViolation("diagnosis validation requires public catalog")
        _probabilities(self.probabilities, catalog.diagnostic_labels)
        return self


@dataclass(frozen=True, slots=True)
class RolloutPrediction:
    signature: tuple[float, ...]
    expected_utility: float
    abstained: bool = False

    def __post_init__(self) -> None:
        if type(self.signature) is not tuple or len(self.signature) != SIGNATURE_DIMENSION:
            raise ProtocolViolation("rollout prediction signature has wrong dimension")
        for number in self.signature:
            _finite(number, "rollout prediction signature")
        _finite(self.expected_utility, "rollout prediction utility")
        if type(self.abstained) is not bool:
            raise ProtocolViolation("rollout abstained must be boolean")


class ExecutableUCMCandidate(Protocol):
    """Research candidate API; patient heads receive state, never history."""

    candidate_id: str
    family_id: str

    def fit(
        self,
        catalogs: tuple[PublicCatalog, ...],
        records: tuple[PublicTrainingRecord, ...],
        *,
        model_seed: int,
    ) -> None: ...

    def initialize(
        self, history: VisibleHistory, *, inference_seed: int
    ) -> SharedPatientState: ...

    def update(
        self,
        state: SharedPatientState,
        delta: VisibleDelta,
        *,
        inference_seed: int,
    ) -> SharedPatientState: ...

    def diagnose(
        self,
        state: SharedPatientState,
        label_catalog: tuple[str, ...],
        *,
        query_seed: int,
    ) -> DiagnosisPrediction: ...

    def rollout(
        self,
        state: SharedPatientState,
        policy: ActionPlan,
        horizon: int,
        *,
        query_seed: int,
    ) -> RolloutPrediction: ...


def diagnosis_scores(
    prediction: DiagnosisPrediction,
    target: dict[str, float],
) -> dict[str, float]:
    labels = tuple(target)
    predicted = _probabilities(prediction.probabilities, labels)
    truth = _probabilities(target, labels)
    top_predicted = max(labels, key=lambda label: (predicted[label], label))
    top_target = max(labels, key=lambda label: (truth[label], label))
    nll = -math.fsum(
        truth[label] * math.log(max(PROBABILITY_CLIP, predicted[label]))
        for label in labels
    )
    brier = math.fsum(
        (predicted[label] - truth[label]) ** 2 for label in labels
    ) / len(labels)
    return {
        "top1_accuracy": float(top_predicted == top_target),
        "cross_entropy_nll": nll,
        "multiclass_brier": brier,
    }


def rollout_scores(
    prediction: RolloutPrediction,
    oracle: CounterfactualOracle,
) -> dict[str, float]:
    target = oracle_signature(oracle)
    mse = math.fsum(
        (prediction.signature[index] - target[index]) ** 2
        for index in range(SIGNATURE_DIMENSION)
    ) / SIGNATURE_DIMENSION
    return {
        "signature_rmse": math.sqrt(mse),
        "utility_absolute_error": abs(
            prediction.expected_utility - oracle.expected_utility
        ),
    }


def treatment_regret(
    predictions: Sequence[RolloutPrediction],
    oracles: Sequence[CounterfactualOracle],
) -> dict[str, Any]:
    if not predictions or len(predictions) != len(oracles):
        raise ProtocolViolation("regret requires aligned non-empty policy rows")
    predicted_index = max(
        range(len(predictions)), key=lambda index: predictions[index].expected_utility
    )
    oracle_utilities = [row.expected_utility for row in oracles]
    best = max(oracle_utilities)
    selected = oracle_utilities[predicted_index]
    regret = max(0.0, best - selected)
    return {
        "selected_policy_index": predicted_index,
        "regret": regret,
        "catastrophic_action": regret >= CATASTROPHIC_UTILITY_MARGIN,
        "oracle_best_utility": best,
        "selected_oracle_utility": selected,
    }


def state_distance(left: SharedPatientState, right: SharedPatientState) -> float:
    if len(left.distance_vector) != len(right.distance_vector):
        return math.inf
    return math.sqrt(
        math.fsum((a - b) ** 2 for a, b in zip(left.distance_vector, right.distance_vector))
    )


def oracle_behavior_distance(
    left: Sequence[CounterfactualOracle], right: Sequence[CounterfactualOracle]
) -> float:
    if not left or len(left) != len(right):
        raise ProtocolViolation("oracle behavior comparison requires aligned rows")
    distances: list[float] = []
    for a, b in zip(left, right):
        if a.horizon != b.horizon or a.policy.to_wire() != b.policy.to_wire():
            raise ProtocolViolation("oracle behavior rows are not query-aligned")
        signature_a = oracle_signature(a)
        signature_b = oracle_signature(b)
        distances.append(abs(a.expected_utility - b.expected_utility))
        distances.extend(abs(x - y) for x, y in zip(signature_a, signature_b))
    return max(distances)


def classify_state_pair(
    left_state: SharedPatientState,
    right_state: SharedPatientState,
    left_oracles: Sequence[CounterfactualOracle],
    right_oracles: Sequence[CounterfactualOracle],
) -> dict[str, Any]:
    candidate_distance = state_distance(left_state, right_state)
    oracle_distance = oracle_behavior_distance(left_oracles, right_oracles)
    dangerous_collision = (
        candidate_distance <= STATE_DISTANCE_EPSILON
        and oracle_distance >= ORACLE_DISTINGUISHABLE_DELTA
    )
    false_split = (
        candidate_distance >= STATE_SPLIT_DELTA
        and oracle_distance <= ORACLE_EQUIVALENT_EPSILON
    )
    return {
        "candidate_distance": candidate_distance,
        "oracle_distance": oracle_distance,
        "dangerous_collision": dangerous_collision,
        "false_split": false_split,
    }


def contract_digest() -> str:
    return digest_bytes(canonical_json_bytes(metric_contract_wire()))


validate_json_like(metric_contract_wire())


__all__ = [
    "BENCHMARK_ID",
    "CATASTROPHIC_UTILITY_MARGIN",
    "CONTRACT_SCHEMA",
    "DiagnosisPrediction",
    "ExecutableUCMCandidate",
    "METRIC_CONTRACTS",
    "PublicTrainingRecord",
    "RolloutPrediction",
    "RolloutTarget",
    "SIGNATURE_DIMENSION",
    "SharedPatientState",
    "build_public_training_record",
    "classify_state_pair",
    "contract_digest",
    "diagnosis_scores",
    "metric_contract_wire",
    "oracle_behavior_distance",
    "oracle_signature",
    "policy_key",
    "rollout_scores",
    "state_distance",
    "treatment_regret",
]
