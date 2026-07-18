"""Executable PRE-FREEZE runtime metrics for M09, M10, and M11.

This module intentionally closes only three metric formulas.  It does not bind
them into the benchmark evaluator, select a winner, or claim freeze authority.
Every input is an exact canonical-JSON byte record with a relative path and a
verified SHA-256 digest.  Metric code never invokes candidate callbacks or
loads paths supplied by a candidate.

The three measurements remain separate Pareto vectors:

* M09 integrates each task's proper-score learning curve over natural-log
  sample count and reports both the integral and its log-span normalization;
* M10 reports three matched held-out gaps with explicit orientation,
  denominator, and paired uncertainty; and
* M11 reports each extension's migration/cost/regression vector and derives the
  hard-failure flag from a closed completion disposition.

No cross-task, cross-stratum, cross-extension, or cross-metric scalar score is
produced.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    validate_json_like,
)


BENCHMARK_STATUS = "PRE-FREEZE"
EVIDENCE_QUALIFICATION = "runtime_only"
AUTHORITY_CLAIM = "not_claimed"
FREEZE_AUTHORITY_STATUS = "not_claimed"
CROSS_METRIC_AGGREGATION = "forbidden"

M09_POINT_SCHEMA = "ucm-m09-learning-curve-point/1"
M09_RESULT_SCHEMA = "ucm-m09-sample-efficiency-result/1"
M10_PAIR_SCHEMA = "ucm-m10-heldout-matched-pair/1"
M10_RESULT_SCHEMA = "ucm-m10-combination-generalization-result/1"
M11_OBSERVATION_SCHEMA = "ucm-m11-extension-cost-observation/2"
M11_RESULT_SCHEMA = "ucm-m11-extension-cost-result/1"

TRAIN_FRACTION_PERCENTS = (1, 5, 10, 25, 50, 100)
PAIRED_CI_CONFIDENCE_LEVEL = 0.95
PAIRED_CI_TWO_SIDED_TAIL = 0.025

_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


class LearningTask(str, Enum):
    DIAGNOSIS = "diagnosis"
    NATURAL_FORECAST = "natural_forecast"
    INTERVENTION = "intervention"


LEARNING_TASKS = (
    LearningTask.DIAGNOSIS,
    LearningTask.NATURAL_FORECAST,
    LearningTask.INTERVENTION,
)


class HeldoutStratum(str, Enum):
    MECHANISM_COMBINATION = "heldout_mechanism_combination"
    HOST_MODIFIER = "heldout_host_modifier"
    NONLINEAR_COMORBIDITY = "heldout_nonlinear_comorbidity"


HELDOUT_STRATA = (
    HeldoutStratum.MECHANISM_COMBINATION,
    HeldoutStratum.HOST_MODIFIER,
    HeldoutStratum.NONLINEAR_COMORBIDITY,
)


class ScoreDirection(str, Enum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class ExtensionKind(str, Enum):
    NEW_CHECK = "new_check"
    NEW_TREATMENT = "new_treatment"


class ExtensionDisposition(str, Enum):
    COMPLETED = "completed"
    REQUIRES_FULL_CORE_REWRITE = "requires_full_core_rewrite"


def _exact_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise ProtocolViolation(
            f"{label} schema mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    if any(ord(character) < 0x20 for character in value):
        raise ProtocolViolation(f"{label} contains a control character")
    return value


def _relative_path(value: object, label: str) -> str:
    path = _name(value, label)
    if "\\" in path or ":" in path:
        raise ProtocolViolation(f"{label} must be a canonical POSIX relative path")
    parsed = PurePosixPath(path)
    if (
        parsed.is_absolute()
        or str(parsed) != path
        or path in {".", ".."}
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ProtocolViolation(f"{label} must be a canonical POSIX relative path")
    return path


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a lowercase SHA-256 digest")
    return value


def _number(value: object, label: str) -> float:
    if type(value) not in {int, float}:
        raise ProtocolViolation(f"{label} must be an exact finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ProtocolViolation(f"{label} must be an exact finite number") from exc
    if not math.isfinite(result):
        raise ProtocolViolation(f"{label} must be an exact finite number")
    return result


def _derived(value: float, label: str) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise ProtocolViolation(f"{label} derived arithmetic is non-finite")
    return value


def _derived_sum(values: tuple[float, ...], label: str) -> float:
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError) as exc:
        raise ProtocolViolation(f"{label} derived arithmetic overflow") from exc
    return _derived(result, label)


def _derived_difference(left: float, right: float, label: str) -> float:
    return _derived(left - right, label)


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """Lentz continued fraction used by the regularized incomplete beta."""

    max_iterations = 300
    epsilon = 3.0e-14
    minimum = 1.0e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < minimum:
        d = minimum
    d = 1.0 / d
    result = d
    for iteration in range(1, max_iterations + 1):
        even = 2 * iteration
        numerator = iteration * (b - iteration) * x / ((qam + even) * (a + even))
        d = 1.0 + numerator * d
        if abs(d) < minimum:
            d = minimum
        c = 1.0 + numerator / c
        if abs(c) < minimum:
            c = minimum
        d = 1.0 / d
        result *= d * c

        numerator = (
            -(a + iteration) * (qab + iteration) * x / ((a + even) * (qap + even))
        )
        d = 1.0 + numerator * d
        if abs(d) < minimum:
            d = minimum
        c = 1.0 + numerator / c
        if abs(c) < minimum:
            c = minimum
        d = 1.0 / d
        delta = d * c
        result *= delta
        if abs(delta - 1.0) <= epsilon:
            return _derived(result, "Student-t beta continued fraction")
    raise ProtocolViolation("Student-t beta continued fraction did not converge")


def _regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    if not (0.0 <= x <= 1.0) or a <= 0.0 or b <= 0.0:
        raise ProtocolViolation("Student-t beta inputs are outside their domain")
    if x == 0.0:
        return 0.0
    if x == 1.0:
        return 1.0
    log_term = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(log_term)
    if x < (a + 1.0) / (a + b + 2.0):
        value = front * _beta_continued_fraction(a, b, x) / a
    else:
        value = 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b
    return min(max(_derived(value, "Student-t incomplete beta"), 0.0), 1.0)


def _student_t_cdf_positive(value: float, degrees_of_freedom: int) -> float:
    if value < 0.0 or type(degrees_of_freedom) is not int or degrees_of_freedom < 1:
        raise ProtocolViolation("Student-t CDF inputs are invalid")
    df = float(degrees_of_freedom)
    beta_x = df / (df + value * value)
    return 1.0 - 0.5 * _regularized_incomplete_beta(beta_x, df / 2.0, 0.5)


def _student_t_two_sided_95_critical(degrees_of_freedom: int) -> float:
    """Code-owned inverse CDF for the paired two-sided 95% Student-t CI."""

    if type(degrees_of_freedom) is not int or degrees_of_freedom < 1:
        raise ProtocolViolation("Student-t degrees_of_freedom must be positive")
    target = 1.0 - PAIRED_CI_TWO_SIDED_TAIL
    lower = 0.0
    upper = 1.0
    while _student_t_cdf_positive(upper, degrees_of_freedom) < target:
        upper *= 2.0
        if not math.isfinite(upper):
            raise ProtocolViolation("Student-t critical search overflowed")
    # Binary64 bisection is deterministic and dependency-free.  Eighty
    # iterations exceed the precision needed for any representable result.
    for _ in range(80):
        midpoint = (lower + upper) / 2.0
        if _student_t_cdf_positive(midpoint, degrees_of_freedom) < target:
            lower = midpoint
        else:
            upper = midpoint
    return _derived((lower + upper) / 2.0, "Student-t critical value")


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ProtocolViolation(f"{label} must be a non-negative exact integer")
    return value


def _positive_int(value: object, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result == 0:
        raise ProtocolViolation(f"{label} must be positive")
    return result


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise ProtocolViolation(f"{label} must be an exact boolean")
    return value


def _enum(value: object, enum_type: type[Enum], label: str) -> Enum:
    if type(value) is not str:
        raise ProtocolViolation(f"{label} must be a code-owned enum value")
    try:
        result = enum_type(value)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} must be a code-owned enum value") from exc
    return result


def _status_wire() -> dict[str, str]:
    return {
        "benchmark_status": BENCHMARK_STATUS,
        "evidence_qualification": EVIDENCE_QUALIFICATION,
        "authority_claim": AUTHORITY_CLAIM,
        "freeze_authority_status": FREEZE_AUTHORITY_STATUS,
        "cross_metric_aggregate_score": CROSS_METRIC_AGGREGATION,
    }


@dataclass(frozen=True, slots=True)
class CanonicalMetricEvidence:
    """Exact inert input custody; this object never opens ``path`` on disk."""

    path: str
    canonical_bytes: bytes
    artifact_digest: str

    def __post_init__(self) -> None:
        _relative_path(self.path, "metric evidence path")
        if type(self.canonical_bytes) is not bytes or not self.canonical_bytes:
            raise ProtocolViolation(
                "metric evidence must contain exact non-empty bytes"
            )
        _digest(self.artifact_digest, "metric evidence artifact_digest")
        if digest_bytes(self.canonical_bytes) != self.artifact_digest:
            raise ProtocolViolation("metric evidence digest does not bind exact bytes")
        try:
            decoded = self.canonical_bytes.decode("utf-8", errors="strict")
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation(
                "metric evidence must be canonical UTF-8 JSON"
            ) from exc
        if type(payload) is not dict:
            raise ProtocolViolation("metric evidence must encode an exact object")
        validate_json_like(payload, path=f"metric evidence {self.path}")
        if canonical_json_bytes(payload) != self.canonical_bytes:
            raise ProtocolViolation("metric evidence bytes are not canonical JSON")

    @classmethod
    def from_payload(
        cls, path: str, payload: dict[str, Any]
    ) -> CanonicalMetricEvidence:
        if type(payload) is not dict:
            raise ProtocolViolation("metric evidence payload must be an exact object")
        exact_bytes = canonical_json_bytes(payload)
        return cls(path, exact_bytes, digest_bytes(exact_bytes))

    @property
    def payload(self) -> dict[str, Any]:
        # Do not expose the retained object by reference.
        return json.loads(self.canonical_bytes)

    def reference_wire(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "byte_length": len(self.canonical_bytes),
            "artifact_digest": self.artifact_digest,
        }


@dataclass(frozen=True, slots=True)
class LearningCurvePoint:
    evidence: CanonicalMetricEvidence
    task: LearningTask = field(init=False)
    train_fraction_percent: int = field(init=False)
    train_examples: int = field(init=False)
    proper_score: float = field(init=False)

    def __post_init__(self) -> None:
        if type(self.evidence) is not CanonicalMetricEvidence:
            raise ProtocolViolation("M09 point requires typed canonical evidence")
        row = self.evidence.payload
        _exact_keys(
            row,
            frozenset(
                {
                    "schema_version",
                    "task",
                    "train_fraction_percent",
                    "train_examples",
                    "proper_score",
                }
            ),
            "M09 learning-curve point",
        )
        if row["schema_version"] != M09_POINT_SCHEMA:
            raise ProtocolViolation("M09 point schema_version is invalid")
        task = _enum(row["task"], LearningTask, "M09 task")
        fraction = _positive_int(
            row["train_fraction_percent"], "M09 train_fraction_percent"
        )
        if fraction not in TRAIN_FRACTION_PERCENTS:
            raise ProtocolViolation("M09 train fraction is outside the fixed schedule")
        object.__setattr__(self, "task", task)
        object.__setattr__(self, "train_fraction_percent", fraction)
        object.__setattr__(
            self,
            "train_examples",
            _positive_int(row["train_examples"], "M09 train_examples"),
        )
        object.__setattr__(
            self, "proper_score", _number(row["proper_score"], "M09 proper_score")
        )


@dataclass(frozen=True, slots=True)
class TaskLearningCurveResult:
    task: LearningTask
    fractions_percent: tuple[int, ...]
    train_examples: tuple[int, ...]
    proper_scores: tuple[float, ...]
    log_sample_auc: float
    log_sample_span: float
    normalized_log_sample_auc: float
    evidence_references: tuple[dict[str, Any], ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "task": self.task.value,
            "optimization_direction": "minimize",
            "fractions_percent": list(self.fractions_percent),
            "train_examples": list(self.train_examples),
            "proper_scores": list(self.proper_scores),
            "formula_id": "natural_log_sample_trapezoid_auc",
            "formula_version": "1",
            "log_sample_auc": self.log_sample_auc,
            "normalization_denominator_log_sample_span": self.log_sample_span,
            "normalized_log_sample_auc": self.normalized_log_sample_auc,
            "evidence_references": list(self.evidence_references),
        }


@dataclass(frozen=True, slots=True)
class SampleEfficiencyResult:
    task_curves: tuple[TaskLearningCurveResult, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": M09_RESULT_SCHEMA,
            "measurement_id": "M09",
            **_status_wire(),
            "fixed_train_fraction_percents": list(TRAIN_FRACTION_PERCENTS),
            "task_curves": [curve.to_wire() for curve in self.task_curves],
            "cross_task_aggregate_score": "forbidden",
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


def sample_efficiency(
    points: tuple[LearningCurvePoint, ...],
) -> SampleEfficiencyResult:
    """Compute three separate proper-score AUCs on the frozen sample slices."""

    if type(points) is not tuple or any(
        type(point) is not LearningCurvePoint for point in points
    ):
        raise ProtocolViolation("M09 input must be a tuple of typed points")
    expected_count = len(LEARNING_TASKS) * len(TRAIN_FRACTION_PERCENTS)
    if len(points) != expected_count:
        raise ProtocolViolation(
            f"M09 requires exactly {expected_count} task/fraction points"
        )
    paths = [point.evidence.path for point in points]
    if len(set(paths)) != len(paths):
        raise ProtocolViolation("M09 evidence paths must be unique")

    indexed: dict[tuple[LearningTask, int], LearningCurvePoint] = {}
    for point in points:
        key = (point.task, point.train_fraction_percent)
        if key in indexed:
            raise ProtocolViolation("M09 contains a duplicate task/fraction point")
        indexed[key] = point
    expected_keys = {
        (task, fraction)
        for task in LEARNING_TASKS
        for fraction in TRAIN_FRACTION_PERCENTS
    }
    if set(indexed) != expected_keys:
        raise ProtocolViolation("M09 task/fraction coverage is not exact")

    results: list[TaskLearningCurveResult] = []
    for task in LEARNING_TASKS:
        ordered = tuple(
            indexed[(task, fraction)] for fraction in TRAIN_FRACTION_PERCENTS
        )
        counts = tuple(point.train_examples for point in ordered)
        if any(right <= left for left, right in zip(counts, counts[1:])):
            raise ProtocolViolation(
                f"M09 {task.value} train_examples must strictly increase"
            )
        scores = tuple(point.proper_score for point in ordered)
        log_counts = tuple(math.log(count) for count in counts)
        trapezoids: list[float] = []
        for left_x, right_x, left_y, right_y in zip(
            log_counts, log_counts[1:], scores, scores[1:]
        ):
            midpoint_score = _derived_sum(
                (left_y / 2.0, right_y / 2.0),
                f"M09 {task.value} trapezoid midpoint",
            )
            trapezoids.append(
                _derived(
                    (right_x - left_x) * midpoint_score,
                    f"M09 {task.value} trapezoid area",
                )
            )
        auc = _derived_sum(tuple(trapezoids), f"M09 {task.value} AUC")
        span = _derived_difference(
            log_counts[-1], log_counts[0], f"M09 {task.value} log-sample span"
        )
        if span <= 0:
            raise ProtocolViolation("M09 log-sample AUC is undefined")
        normalized = _derived(auc / span, f"M09 {task.value} normalized log-sample AUC")
        results.append(
            TaskLearningCurveResult(
                task=task,
                fractions_percent=TRAIN_FRACTION_PERCENTS,
                train_examples=counts,
                proper_scores=scores,
                log_sample_auc=auc,
                log_sample_span=span,
                normalized_log_sample_auc=normalized,
                evidence_references=tuple(
                    point.evidence.reference_wire() for point in ordered
                ),
            )
        )
    return SampleEfficiencyResult(tuple(results))


@dataclass(frozen=True, slots=True)
class HeldoutMatchedPair:
    evidence: CanonicalMetricEvidence
    stratum: HeldoutStratum = field(init=False)
    pair_id: str = field(init=False)
    heldout_case_id: str = field(init=False)
    matched_seen_case_id: str = field(init=False)
    score_direction: ScoreDirection = field(init=False)
    heldout_score: float = field(init=False)
    matched_seen_score: float = field(init=False)

    def __post_init__(self) -> None:
        if type(self.evidence) is not CanonicalMetricEvidence:
            raise ProtocolViolation("M10 pair requires typed canonical evidence")
        row = self.evidence.payload
        _exact_keys(
            row,
            frozenset(
                {
                    "schema_version",
                    "stratum",
                    "pair_id",
                    "heldout_case_id",
                    "matched_seen_case_id",
                    "score_direction",
                    "heldout_score",
                    "matched_seen_score",
                }
            ),
            "M10 matched pair",
        )
        if row["schema_version"] != M10_PAIR_SCHEMA:
            raise ProtocolViolation("M10 pair schema_version is invalid")
        object.__setattr__(
            self, "stratum", _enum(row["stratum"], HeldoutStratum, "M10 stratum")
        )
        object.__setattr__(self, "pair_id", _name(row["pair_id"], "M10 pair_id"))
        object.__setattr__(
            self,
            "heldout_case_id",
            _name(row["heldout_case_id"], "M10 heldout_case_id"),
        )
        object.__setattr__(
            self,
            "matched_seen_case_id",
            _name(row["matched_seen_case_id"], "M10 matched_seen_case_id"),
        )
        if self.heldout_case_id == self.matched_seen_case_id:
            raise ProtocolViolation("M10 heldout and seen case ids must differ")
        object.__setattr__(
            self,
            "score_direction",
            _enum(row["score_direction"], ScoreDirection, "M10 score_direction"),
        )
        object.__setattr__(
            self, "heldout_score", _number(row["heldout_score"], "M10 heldout_score")
        )
        object.__setattr__(
            self,
            "matched_seen_score",
            _number(row["matched_seen_score"], "M10 matched_seen_score"),
        )

    @property
    def oriented_gap(self) -> float:
        if self.score_direction is ScoreDirection.MINIMIZE:
            return _derived_difference(
                self.heldout_score,
                self.matched_seen_score,
                f"M10 {self.stratum.value} pair {self.pair_id} gap",
            )
        if self.score_direction is ScoreDirection.MAXIMIZE:
            return _derived_difference(
                self.matched_seen_score,
                self.heldout_score,
                f"M10 {self.stratum.value} pair {self.pair_id} gap",
            )
        raise ProtocolViolation("M10 score direction enum identity is invalid")


@dataclass(frozen=True, slots=True)
class HeldoutGapResult:
    stratum: HeldoutStratum
    score_direction: ScoreDirection
    denominator_count: int
    mean_heldout_score: float
    mean_matched_seen_score: float
    mean_oriented_gap: float
    uncertainty_status: str
    uncertainty_reason: str | None
    paired_delta_degrees_of_freedom: int
    paired_delta_student_t_critical: float | None
    paired_delta_sample_sd: float | None
    paired_delta_standard_error: float | None
    paired_delta_student_t_ci95_lower: float | None
    paired_delta_student_t_ci95_upper: float | None
    pairs: tuple[dict[str, Any], ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "stratum": self.stratum.value,
            "score_direction": self.score_direction.value,
            "gap_orientation": "positive_means_heldout_is_worse",
            "denominator_definition": "explicit_matched_heldout_seen_pairs",
            "denominator_count": self.denominator_count,
            "mean_heldout_score": self.mean_heldout_score,
            "mean_matched_seen_score": self.mean_matched_seen_score,
            "mean_oriented_gap": self.mean_oriented_gap,
            "uncertainty": {
                "status": self.uncertainty_status,
                "undefined_reason": self.uncertainty_reason,
                "method": "paired_delta_student_t_ci95",
                "sampling_unit": "explicit_matched_heldout_seen_pair",
                "confidence_level": PAIRED_CI_CONFIDENCE_LEVEL,
                "two_sided_tail_probability": PAIRED_CI_TWO_SIDED_TAIL,
                "degrees_of_freedom": self.paired_delta_degrees_of_freedom,
                "student_t_critical": self.paired_delta_student_t_critical,
                "sample_sd_ddof": 1,
                "paired_delta_sample_sd": self.paired_delta_sample_sd,
                "paired_delta_standard_error": self.paired_delta_standard_error,
                "ci95_lower": self.paired_delta_student_t_ci95_lower,
                "ci95_upper": self.paired_delta_student_t_ci95_upper,
            },
            "pairs": list(self.pairs),
        }


@dataclass(frozen=True, slots=True)
class CombinationGeneralizationResult:
    stratum_gaps: tuple[HeldoutGapResult, ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": M10_RESULT_SCHEMA,
            "measurement_id": "M10",
            **_status_wire(),
            "stratum_gaps": [gap.to_wire() for gap in self.stratum_gaps],
            "cross_stratum_aggregate_score": "forbidden",
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


def combination_generalization(
    pairs: tuple[HeldoutMatchedPair, ...],
) -> CombinationGeneralizationResult:
    """Compute oriented matched gaps for the three required held-out strata."""

    if type(pairs) is not tuple or any(
        type(pair) is not HeldoutMatchedPair for pair in pairs
    ):
        raise ProtocolViolation("M10 input must be a tuple of typed matched pairs")
    if not pairs:
        raise ProtocolViolation("M10 matched pairs cannot be empty")
    paths = [pair.evidence.path for pair in pairs]
    if len(set(paths)) != len(paths):
        raise ProtocolViolation("M10 evidence paths must be unique")

    results: list[HeldoutGapResult] = []
    for stratum in HELDOUT_STRATA:
        selected = sorted(
            (pair for pair in pairs if pair.stratum is stratum),
            key=lambda pair: pair.pair_id,
        )
        if not selected:
            raise ProtocolViolation(f"M10 {stratum.value} requires a matched pair")
        pair_ids = [pair.pair_id for pair in selected]
        heldout_ids = [pair.heldout_case_id for pair in selected]
        if len(set(pair_ids)) != len(pair_ids):
            raise ProtocolViolation(f"M10 {stratum.value} pair ids must be unique")
        if len(set(heldout_ids)) != len(heldout_ids):
            raise ProtocolViolation(
                f"M10 {stratum.value} heldout case ids must be unique"
            )
        directions = {pair.score_direction for pair in selected}
        if len(directions) != 1:
            raise ProtocolViolation(
                f"M10 {stratum.value} score direction must be homogeneous"
            )
        direction = next(iter(directions))
        gaps = tuple(pair.oriented_gap for pair in selected)
        denominator = len(gaps)
        mean_gap = _derived(
            _derived_sum(gaps, f"M10 {stratum.value} gap sum") / denominator,
            f"M10 {stratum.value} mean gap",
        )
        mean_heldout = _derived(
            _derived_sum(
                tuple(pair.heldout_score for pair in selected),
                f"M10 {stratum.value} heldout score sum",
            )
            / denominator,
            f"M10 {stratum.value} mean heldout score",
        )
        mean_seen = _derived(
            _derived_sum(
                tuple(pair.matched_seen_score for pair in selected),
                f"M10 {stratum.value} seen score sum",
            )
            / denominator,
            f"M10 {stratum.value} mean seen score",
        )
        degrees_of_freedom = denominator - 1
        if denominator == 1:
            uncertainty_status = "undefined"
            uncertainty_reason = "insufficient_pairs"
            critical = None
            sample_sd = None
            standard_error = None
            ci_lower = None
            ci_upper = None
        else:
            centered_squares: list[float] = []
            for gap in gaps:
                centered = _derived_difference(
                    gap, mean_gap, f"M10 {stratum.value} centered gap"
                )
                centered_squares.append(
                    _derived(
                        centered * centered,
                        f"M10 {stratum.value} centered squared gap",
                    )
                )
            variance = _derived(
                _derived_sum(
                    tuple(centered_squares), f"M10 {stratum.value} variance sum"
                )
                / degrees_of_freedom,
                f"M10 {stratum.value} sample variance",
            )
            sample_sd = _derived(
                math.sqrt(max(variance, 0.0)), f"M10 {stratum.value} sample SD"
            )
            standard_error = _derived(
                sample_sd / math.sqrt(denominator),
                f"M10 {stratum.value} standard error",
            )
            critical = _student_t_two_sided_95_critical(degrees_of_freedom)
            half_width = _derived(
                critical * standard_error, f"M10 {stratum.value} CI half-width"
            )
            ci_lower = _derived_difference(
                mean_gap, half_width, f"M10 {stratum.value} CI lower"
            )
            ci_upper = _derived(mean_gap + half_width, f"M10 {stratum.value} CI upper")
            uncertainty_status = "defined"
            uncertainty_reason = None
        results.append(
            HeldoutGapResult(
                stratum=stratum,
                score_direction=direction,
                denominator_count=denominator,
                mean_heldout_score=mean_heldout,
                mean_matched_seen_score=mean_seen,
                mean_oriented_gap=mean_gap,
                uncertainty_status=uncertainty_status,
                uncertainty_reason=uncertainty_reason,
                paired_delta_degrees_of_freedom=degrees_of_freedom,
                paired_delta_student_t_critical=critical,
                paired_delta_sample_sd=sample_sd,
                paired_delta_standard_error=standard_error,
                paired_delta_student_t_ci95_lower=ci_lower,
                paired_delta_student_t_ci95_upper=ci_upper,
                pairs=tuple(
                    {
                        "pair_id": pair.pair_id,
                        "heldout_case_id": pair.heldout_case_id,
                        "matched_seen_case_id": pair.matched_seen_case_id,
                        "heldout_score": pair.heldout_score,
                        "matched_seen_score": pair.matched_seen_score,
                        "oriented_gap": pair.oriented_gap,
                        "evidence": pair.evidence.reference_wire(),
                    }
                    for pair in selected
                ),
            )
        )
    if len(pairs) != sum(result.denominator_count for result in results):
        raise ProtocolViolation("M10 contains a pair outside the closed strata")
    return CombinationGeneralizationResult(tuple(results))


@dataclass(frozen=True, slots=True)
class CoreDiffFile:
    path: str
    added_lines: int
    deleted_lines: int

    @classmethod
    def from_wire(cls, value: object) -> CoreDiffFile:
        if type(value) is not dict:
            raise ProtocolViolation("M11 core diff file must be an exact object")
        _exact_keys(
            value,
            frozenset({"path", "added_lines", "deleted_lines"}),
            "M11 core diff file",
        )
        result = cls(
            _relative_path(value["path"], "M11 core diff path"),
            _nonnegative_int(value["added_lines"], "M11 core diff added_lines"),
            _nonnegative_int(value["deleted_lines"], "M11 core diff deleted_lines"),
        )
        # A committed source path can change with zero logical LOC (for example
        # adding/removing an empty file).  The collector still has to retain the
        # changed-file axis instead of conflating absence with empty bytes.
        return result

    def to_wire(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "added_lines": self.added_lines,
            "deleted_lines": self.deleted_lines,
        }


@dataclass(frozen=True, slots=True)
class ExtensionCostObservation:
    evidence: CanonicalMetricEvidence
    extension_id: str = field(init=False)
    extension_kind: ExtensionKind = field(init=False)
    model_migration_required: bool = field(init=False)
    state_migration_required: bool = field(init=False)
    schema_migration_required: bool = field(init=False)
    retrain_examples: int = field(init=False)
    base_artifact_size_bytes: int = field(init=False)
    extended_artifact_size_bytes: int = field(init=False)
    core_diff_files: tuple[CoreDiffFile, ...] = field(init=False)
    old_benchmark_before_score: float = field(init=False)
    old_benchmark_after_score: float = field(init=False)
    old_benchmark_score_direction: ScoreDirection = field(init=False)
    old_benchmark_denominator: int = field(init=False)
    completion_disposition: ExtensionDisposition = field(init=False)

    def __post_init__(self) -> None:
        if type(self.evidence) is not CanonicalMetricEvidence:
            raise ProtocolViolation("M11 observation requires typed canonical evidence")
        row = self.evidence.payload
        _exact_keys(
            row,
            frozenset(
                {
                    "schema_version",
                    "extension_id",
                    "extension_kind",
                    "model_migration_required",
                    "state_migration_required",
                    "schema_migration_required",
                    "retrain_examples",
                    "base_artifact_size_bytes",
                    "extended_artifact_size_bytes",
                    "core_diff_files",
                    "old_benchmark_before_score",
                    "old_benchmark_after_score",
                    "old_benchmark_score_direction",
                    "old_benchmark_denominator",
                    "completion_disposition",
                }
            ),
            "M11 extension cost observation",
        )
        if row["schema_version"] != M11_OBSERVATION_SCHEMA:
            raise ProtocolViolation("M11 observation schema_version is invalid")
        object.__setattr__(
            self, "extension_id", _name(row["extension_id"], "M11 extension_id")
        )
        object.__setattr__(
            self,
            "extension_kind",
            _enum(row["extension_kind"], ExtensionKind, "M11 extension_kind"),
        )
        for field_name in (
            "model_migration_required",
            "state_migration_required",
            "schema_migration_required",
        ):
            object.__setattr__(
                self, field_name, _bool(row[field_name], f"M11 {field_name}")
            )
        object.__setattr__(
            self,
            "retrain_examples",
            _nonnegative_int(row["retrain_examples"], "M11 retrain_examples"),
        )
        object.__setattr__(
            self,
            "base_artifact_size_bytes",
            _positive_int(
                row["base_artifact_size_bytes"], "M11 base_artifact_size_bytes"
            ),
        )
        object.__setattr__(
            self,
            "extended_artifact_size_bytes",
            _positive_int(
                row["extended_artifact_size_bytes"],
                "M11 extended_artifact_size_bytes",
            ),
        )
        diff_rows = row["core_diff_files"]
        if type(diff_rows) is not list:
            raise ProtocolViolation("M11 core_diff_files must be an exact list")
        files = tuple(
            sorted(
                (CoreDiffFile.from_wire(item) for item in diff_rows),
                key=lambda item: item.path,
            )
        )
        if len({item.path for item in files}) != len(files):
            raise ProtocolViolation("M11 core diff paths must be unique")
        object.__setattr__(self, "core_diff_files", files)
        object.__setattr__(
            self,
            "old_benchmark_before_score",
            _number(
                row["old_benchmark_before_score"],
                "M11 old_benchmark_before_score",
            ),
        )
        object.__setattr__(
            self,
            "old_benchmark_after_score",
            _number(row["old_benchmark_after_score"], "M11 old_benchmark_after_score"),
        )
        object.__setattr__(
            self,
            "old_benchmark_score_direction",
            _enum(
                row["old_benchmark_score_direction"],
                ScoreDirection,
                "M11 old_benchmark_score_direction",
            ),
        )
        object.__setattr__(
            self,
            "old_benchmark_denominator",
            _positive_int(
                row["old_benchmark_denominator"], "M11 old_benchmark_denominator"
            ),
        )
        object.__setattr__(
            self,
            "completion_disposition",
            _enum(
                row["completion_disposition"],
                ExtensionDisposition,
                "M11 completion_disposition",
            ),
        )

    @property
    def artifact_delta_bytes(self) -> int:
        return self.extended_artifact_size_bytes - self.base_artifact_size_bytes

    @property
    def old_benchmark_oriented_regression(self) -> float:
        if self.old_benchmark_score_direction is ScoreDirection.MINIMIZE:
            return _derived_difference(
                self.old_benchmark_after_score,
                self.old_benchmark_before_score,
                f"M11 {self.extension_id} old benchmark regression",
            )
        if self.old_benchmark_score_direction is ScoreDirection.MAXIMIZE:
            return _derived_difference(
                self.old_benchmark_before_score,
                self.old_benchmark_after_score,
                f"M11 {self.extension_id} old benchmark regression",
            )
        raise ProtocolViolation("M11 score direction enum identity is invalid")

    @property
    def hard_extensibility_failure(self) -> bool:
        return (
            self.completion_disposition
            is ExtensionDisposition.REQUIRES_FULL_CORE_REWRITE
        )


@dataclass(frozen=True, slots=True)
class ExtensionCostResult:
    extensions: tuple[dict[str, Any], ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": M11_RESULT_SCHEMA,
            "measurement_id": "M11",
            **_status_wire(),
            "extensions": list(self.extensions),
            "cross_extension_aggregate_score": "forbidden",
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


def extension_cost(
    observations: tuple[ExtensionCostObservation, ...],
) -> ExtensionCostResult:
    """Return one non-collapsed extension cost vector per extension attempt."""

    if (
        type(observations) is not tuple
        or not observations
        or any(
            type(observation) is not ExtensionCostObservation
            for observation in observations
        )
    ):
        raise ProtocolViolation(
            "M11 input must be a non-empty tuple of typed observations"
        )
    paths = [observation.evidence.path for observation in observations]
    if len(set(paths)) != len(paths):
        raise ProtocolViolation("M11 evidence paths must be unique")
    ids = [observation.extension_id for observation in observations]
    if len(set(ids)) != len(ids):
        raise ProtocolViolation("M11 extension ids must be unique")

    rows: list[dict[str, Any]] = []
    for observation in sorted(observations, key=lambda item: item.extension_id):
        added = sum(item.added_lines for item in observation.core_diff_files)
        deleted = sum(item.deleted_lines for item in observation.core_diff_files)
        rows.append(
            {
                "extension_id": observation.extension_id,
                "extension_kind": observation.extension_kind.value,
                "migration_flags": {
                    "model_migration_required": observation.model_migration_required,
                    "state_migration_required": observation.state_migration_required,
                    "schema_migration_required": observation.schema_migration_required,
                },
                "retrain_examples": observation.retrain_examples,
                "artifact_bytes": {
                    "base": observation.base_artifact_size_bytes,
                    "extended": observation.extended_artifact_size_bytes,
                    "signed_delta": observation.artifact_delta_bytes,
                    "absolute_delta": abs(observation.artifact_delta_bytes),
                },
                "core_diff": {
                    "changed_file_count": len(observation.core_diff_files),
                    "added_lines": added,
                    "deleted_lines": deleted,
                    "changed_loc": added + deleted,
                    "files": [item.to_wire() for item in observation.core_diff_files],
                },
                "old_benchmark_regression": {
                    "score_direction": observation.old_benchmark_score_direction.value,
                    "gap_orientation": "positive_means_old_benchmark_is_worse",
                    "before_score": observation.old_benchmark_before_score,
                    "after_score": observation.old_benchmark_after_score,
                    "oriented_regression": observation.old_benchmark_oriented_regression,
                    "denominator_definition": "old_benchmark_evaluation_examples",
                    "denominator_count": observation.old_benchmark_denominator,
                },
                "completion_disposition": observation.completion_disposition.value,
                "hard_extensibility_failure": observation.hard_extensibility_failure,
                "evidence": observation.evidence.reference_wire(),
            }
        )
    return ExtensionCostResult(tuple(rows))
