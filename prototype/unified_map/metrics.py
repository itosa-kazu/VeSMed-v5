"""Candidate-neutral UCM metrics; no weighted aggregate score is provided."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import numpy as np

from .canonical import ProtocolViolation


def _array(value: Any, *, ndim: int, label: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != ndim or array.size == 0 or not np.all(np.isfinite(array)):
        raise ProtocolViolation(f"{label} must be a non-empty finite {ndim}D array")
    return array


def _probability_matrix(value: Any, label: str) -> np.ndarray:
    probabilities = _array(value, ndim=2, label=label)
    if np.any(probabilities < 0.0) or np.any(probabilities > 1.0):
        raise ProtocolViolation(f"{label} contains values outside [0,1]")
    if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-9, rtol=0.0):
        raise ProtocolViolation(f"{label} rows must sum to one")
    return probabilities


@dataclass(frozen=True, slots=True)
class DiagnosticMetricVector:
    count: int
    accuracy: float
    log_loss: float
    multiclass_brier: float
    expected_calibration_error: float


def diagnostic_metrics(
    probabilities: Any,
    true_class: Any,
    *,
    calibration_bins: int = 10,
) -> DiagnosticMetricVector:
    probs = _probability_matrix(probabilities, "diagnostic probabilities")
    labels = np.asarray(true_class)
    if labels.ndim != 1 or labels.shape[0] != probs.shape[0]:
        raise ProtocolViolation("true_class must align with probability rows")
    if not np.issubdtype(labels.dtype, np.integer):
        raise ProtocolViolation("true_class must contain integer indexes")
    labels = labels.astype(np.int64, copy=False)
    if np.any(labels < 0) or np.any(labels >= probs.shape[1]):
        raise ProtocolViolation("true_class contains an out-of-range index")
    if type(calibration_bins) is not int or calibration_bins <= 0:
        raise ProtocolViolation("calibration_bins must be positive")

    rows = np.arange(probs.shape[0])
    chosen = np.argmax(probs, axis=1)
    accuracy = float(np.mean(chosen == labels))
    log_loss = float(-np.mean(np.log(np.clip(probs[rows, labels], 1e-15, 1.0))))
    one_hot = np.zeros_like(probs)
    one_hot[rows, labels] = 1.0
    brier = float(np.mean(np.sum((probs - one_hot) ** 2, axis=1)))

    confidence = np.max(probs, axis=1)
    correct = (chosen == labels).astype(np.float64)
    edges = np.linspace(0.0, 1.0, calibration_bins + 1)
    ece = 0.0
    for index in range(calibration_bins):
        if index == calibration_bins - 1:
            mask = (confidence >= edges[index]) & (confidence <= edges[index + 1])
        else:
            mask = (confidence >= edges[index]) & (confidence < edges[index + 1])
        if np.any(mask):
            ece += float(np.mean(mask)) * abs(
                float(np.mean(confidence[mask])) - float(np.mean(correct[mask]))
            )
    return DiagnosticMetricVector(
        count=probs.shape[0],
        accuracy=accuracy,
        log_loss=log_loss,
        multiclass_brier=brier,
        expected_calibration_error=ece,
    )


@dataclass(frozen=True, slots=True)
class TrajectoryMetricVector:
    count: int
    normalized_rmse: float
    normalized_mae: float
    gaussian_nll: float | None


def trajectory_metrics(
    predicted_mean: Any,
    truth: Any,
    scale: Any,
    *,
    predicted_std: Any | None = None,
) -> TrajectoryMetricVector:
    mean = _array(predicted_mean, ndim=2, label="predicted_mean")
    observed = _array(truth, ndim=2, label="truth")
    if mean.shape != observed.shape:
        raise ProtocolViolation("predicted_mean and truth shapes differ")
    normalization = np.asarray(scale, dtype=np.float64)
    if normalization.ndim == 1:
        if normalization.shape[0] != mean.shape[1]:
            raise ProtocolViolation("scale length must match trajectory columns")
        normalization = np.broadcast_to(normalization, mean.shape)
    elif normalization.shape != mean.shape:
        raise ProtocolViolation("scale must be one value per column or cell")
    if not np.all(np.isfinite(normalization)) or np.any(normalization <= 0):
        raise ProtocolViolation("trajectory scale must be finite and positive")
    error = (mean - observed) / normalization
    nrmse = float(np.sqrt(np.mean(error**2)))
    nmae = float(np.mean(np.abs(error)))

    nll: float | None = None
    if predicted_std is not None:
        std = _array(predicted_std, ndim=2, label="predicted_std")
        if std.shape != mean.shape or np.any(std <= 0):
            raise ProtocolViolation("predicted_std must be positive and aligned")
        variance = std**2
        nll = float(
            np.mean(
                0.5 * np.log(2.0 * np.pi * variance)
                + 0.5 * ((observed - mean) ** 2) / variance
            )
        )
    return TrajectoryMetricVector(
        count=mean.shape[0],
        normalized_rmse=nrmse,
        normalized_mae=nmae,
        gaussian_nll=nll,
    )


@dataclass(frozen=True, slots=True)
class RegretMetricVector:
    count: int
    mean_regret: float
    median_regret: float
    p90_regret: float
    p99_regret: float
    worst_regret: float
    catastrophic_count: int
    chosen_actions: tuple[int, ...]


def treatment_regret(
    predicted_utilities: Any,
    oracle_utilities: Any,
    *,
    catastrophic_margin: float,
) -> RegretMetricVector:
    predicted = _array(predicted_utilities, ndim=2, label="predicted_utilities")
    oracle = _array(oracle_utilities, ndim=2, label="oracle_utilities")
    if predicted.shape != oracle.shape:
        raise ProtocolViolation("predicted and oracle utility shapes differ")
    if type(catastrophic_margin) not in {int, float} or catastrophic_margin < 0:
        raise ProtocolViolation("catastrophic_margin must be non-negative")
    chosen = np.argmax(predicted, axis=1)
    rows = np.arange(predicted.shape[0])
    regret = np.max(oracle, axis=1) - oracle[rows, chosen]
    if np.any(regret < -1e-10):
        raise ProtocolViolation("oracle regret became negative")
    regret = np.maximum(regret, 0.0)
    return RegretMetricVector(
        count=predicted.shape[0],
        mean_regret=float(np.mean(regret)),
        median_regret=float(np.quantile(regret, 0.5)),
        p90_regret=float(np.quantile(regret, 0.9)),
        p99_regret=float(np.quantile(regret, 0.99)),
        worst_regret=float(np.max(regret)),
        catastrophic_count=int(np.sum(regret >= catastrophic_margin)),
        chosen_actions=tuple(int(value) for value in chosen),
    )


def binary_roc_auc(scores: Any, labels: Any) -> float:
    """AUROC with average ranks for ties; larger score means positive/OOD."""

    score = _array(scores, ndim=1, label="scores")
    target = np.asarray(labels)
    if target.ndim != 1 or target.shape[0] != score.shape[0]:
        raise ProtocolViolation("labels must align with scores")
    if not np.all(np.isin(target, [0, 1])):
        raise ProtocolViolation("labels must be binary")
    positive = int(np.sum(target == 1))
    negative = int(np.sum(target == 0))
    if positive == 0 or negative == 0:
        raise ProtocolViolation("AUROC requires both classes")

    order = np.argsort(score, kind="mergesort")
    ranks = np.empty(score.shape[0], dtype=np.float64)
    start = 0
    while start < score.shape[0]:
        end = start + 1
        while end < score.shape[0] and score[order[end]] == score[order[start]]:
            end += 1
        average_rank = 0.5 * ((start + 1) + end)
        ranks[order[start:end]] = average_rank
        start = end
    rank_sum = float(np.sum(ranks[target == 1]))
    return (rank_sum - positive * (positive + 1) / 2.0) / (
        positive * negative
    )


class InformationRelation(str, Enum):
    DISTINGUISHABLE = "distinguishable_from_public_history"
    IDENTICAL_PREFIX = "identical_public_prefix"
    NONIDENTIFIED = "nonidentified_from_training_regime"


@dataclass(frozen=True, slots=True)
class PairProbe:
    pair_id: str
    state_hash_a: str
    state_hash_b: str
    candidate_signature_a: tuple[float, ...]
    candidate_signature_b: tuple[float, ...]
    oracle_signature_a: tuple[float, ...]
    oracle_signature_b: tuple[float, ...]
    oracle_action_values_a: tuple[float, ...]
    oracle_action_values_b: tuple[float, ...]
    information_relation: str
    intervention_identifiable: bool


@dataclass(frozen=True, slots=True)
class PairClassification:
    pair_id: str
    candidate_distance: float
    oracle_distance: float
    exact_collision: bool
    functional_near_collision: bool
    dangerous_collision: bool
    attributable_collision: bool
    false_split: bool
    cross_applied_regret: float


def _max_distance(first: tuple[float, ...], second: tuple[float, ...]) -> float:
    if type(first) is not tuple or type(second) is not tuple or len(first) != len(second):
        raise ProtocolViolation("pair signatures must be aligned tuples")
    if not first:
        raise ProtocolViolation("pair signatures must be non-empty")
    left = np.asarray(first, dtype=np.float64)
    right = np.asarray(second, dtype=np.float64)
    if not np.all(np.isfinite(left)) or not np.all(np.isfinite(right)):
        raise ProtocolViolation("pair signatures must be finite")
    return float(np.max(np.abs(left - right)))


def classify_pair(
    probe: PairProbe,
    *,
    candidate_same_epsilon: float,
    candidate_split_delta: float,
    oracle_distinguishable_delta: float,
    oracle_equivalent_epsilon: float,
    catastrophic_margin: float,
) -> PairClassification:
    thresholds = {
        "candidate_same_epsilon": candidate_same_epsilon,
        "candidate_split_delta": candidate_split_delta,
        "oracle_distinguishable_delta": oracle_distinguishable_delta,
        "oracle_equivalent_epsilon": oracle_equivalent_epsilon,
        "catastrophic_margin": catastrophic_margin,
    }
    for label, value in thresholds.items():
        if type(value) not in {int, float} or not np.isfinite(value) or value < 0:
            raise ProtocolViolation(f"{label} must be finite and non-negative")
    if probe.information_relation not in set(InformationRelation):
        raise ProtocolViolation("unknown pair information relation")
    candidate_distance = _max_distance(
        probe.candidate_signature_a, probe.candidate_signature_b
    )
    oracle_distance = _max_distance(probe.oracle_signature_a, probe.oracle_signature_b)
    action_a = np.asarray(probe.oracle_action_values_a, dtype=np.float64)
    action_b = np.asarray(probe.oracle_action_values_b, dtype=np.float64)
    if (
        action_a.ndim != 1
        or action_a.size == 0
        or action_a.shape != action_b.shape
        or not np.all(np.isfinite(action_a))
        or not np.all(np.isfinite(action_b))
    ):
        raise ProtocolViolation("oracle action values must be aligned finite vectors")

    exact = (
        probe.state_hash_a == probe.state_hash_b
        and oracle_distance >= oracle_distinguishable_delta
    )
    near = (
        candidate_distance <= candidate_same_epsilon
        and oracle_distance >= oracle_distinguishable_delta
    )
    best_a = int(np.argmax(action_a))
    best_b = int(np.argmax(action_b))
    cross_regret = max(
        float(np.max(action_a) - action_a[best_b]),
        float(np.max(action_b) - action_b[best_a]),
    )
    dangerous = (exact or near) and (
        best_a != best_b or cross_regret >= catastrophic_margin
    )
    attributable = dangerous and (
        probe.information_relation == InformationRelation.DISTINGUISHABLE
        and probe.intervention_identifiable
    )
    false_split = (
        oracle_distance <= oracle_equivalent_epsilon
        and candidate_distance >= candidate_split_delta
    )
    return PairClassification(
        pair_id=probe.pair_id,
        candidate_distance=candidate_distance,
        oracle_distance=oracle_distance,
        exact_collision=exact,
        functional_near_collision=near,
        dangerous_collision=dangerous,
        attributable_collision=attributable,
        false_split=false_split,
        cross_applied_regret=max(cross_regret, 0.0),
    )
