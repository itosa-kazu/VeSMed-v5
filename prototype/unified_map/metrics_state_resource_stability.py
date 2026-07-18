"""Executable, isolated PRE-FREEZE formulas for UCM metrics M12--M14.

The functions in this module consume inert, typed evidence and produce three
separate Pareto vectors.  They are deliberately not bound to the evaluator,
do not emit a cross-metric score, and cannot issue benchmark freeze authority.

M12 binds every state-size row to its complete evaluation identity, measures
canonical JSON bytes plus an auxiliary code-owned compression recipe, and
reports OLS history-length slopes and task/horizon slices.  M13 accepts only
measurements bound to exact canonical collector-provenance bytes.  M14 accepts
exactly the five code-owned TRAIN5/EVAL5 replicate pairs and computes same-index
Student-t intervals; it never forms the invalid 5-by-5 Cartesian comparison.

All exposure and identity claims are caller-asserted and unbound.  M12
component counts are explicitly unverified, M13 collectors are explicitly
partial/untrusted, and absence of supplied rows is never presented as complete
coverage.  These formulas summarize only the provided exposure.
"""

from __future__ import annotations

import json
import math
import re
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    validate_json_like,
)
from .seed_protocol import ZIPPED_REPLICATE_IDS


BENCHMARK_STATUS = "PRE-FREEZE"
EVIDENCE_QUALIFICATION = "runtime_only"
RUNTIME_BINDING = "isolated_unbound"
FREEZE_AUTHORITY_STATUS = "not_claimed"
CROSS_METRIC_AGGREGATE_SCORE = "forbidden"

M12_ROW_SCHEMA = "ucm-m12-state-size-row/1"
M12_RESULT_SCHEMA = "ucm-m12-state-size-result/1"
M13_PROVENANCE_SCHEMA = "ucm-m13-collector-provenance/1"
M13_MEASUREMENT_SCHEMA = "ucm-m13-resource-measurement/1"
M13_RESULT_SCHEMA = "ucm-m13-resource-result/1"
M14_RESULT_SCHEMA = "ucm-m14-five-seed-stability-result/1"

CODE_OWNED_COMPRESSOR_ID = "zlib-rfc1950-deflate-level-9-v1"
CODE_OWNED_COMPRESSOR_LEVEL = 9
HF7_QUANTILE_RECIPE = "Hyndman-Fan-type-7-linear"
FIVE_REPLICATE_COUNT = 5
STUDENT_T_DEGREES_OF_FREEDOM = 4
STUDENT_T_95_CRITICAL_DF4 = 2.7764451051977987
HIERARCHICAL_BOOTSTRAP_BLOCKER = "UCM-METRIC-B004"
MAX_SAFE_EXACT_INTEGER = 2**53 - 1

_DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}")
_RFC3339_UTC_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


class MetricDirection(str, Enum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class CandidateOperation(str, Enum):
    INITIALIZE = "initialize"
    UPDATE = "update"
    DIAGNOSE = "diagnose"
    ROLLOUT = "rollout"


class ResourceKind(str, Enum):
    COLD_LATENCY = "cold_latency"
    PEAK_RSS = "peak_rss"
    PEAK_GPU_MEMORY = "peak_gpu_memory"
    MODEL_ARTIFACT_BYTES = "model_artifact_bytes"
    TRAIN_WALL_TIME = "train_wall_time"
    TRAIN_FLOPS = "train_flops"
    POSTSEAL_WORKER_WALL_TIME = "postseal_worker_wall_time"
    POSTSEAL_WORKER_PEAK_RSS = "postseal_worker_peak_rss"
    POSTSEAL_WORKER_PEAK_GPU_MEMORY = "postseal_worker_peak_gpu_memory"


_RESOURCE_UNITS = {
    ResourceKind.COLD_LATENCY: "nanosecond",
    ResourceKind.PEAK_RSS: "byte",
    ResourceKind.PEAK_GPU_MEMORY: "byte",
    ResourceKind.MODEL_ARTIFACT_BYTES: "byte",
    ResourceKind.TRAIN_WALL_TIME: "second",
    ResourceKind.TRAIN_FLOPS: "FLOP",
    ResourceKind.POSTSEAL_WORKER_WALL_TIME: "second",
    ResourceKind.POSTSEAL_WORKER_PEAK_RSS: "byte",
    ResourceKind.POSTSEAL_WORKER_PEAK_GPU_MEMORY: "byte",
}
_EXACT_INTEGER_RESOURCE_KINDS = frozenset(
    {
        ResourceKind.COLD_LATENCY,
        ResourceKind.PEAK_RSS,
        ResourceKind.PEAK_GPU_MEMORY,
        ResourceKind.MODEL_ARTIFACT_BYTES,
        ResourceKind.TRAIN_FLOPS,
        ResourceKind.POSTSEAL_WORKER_PEAK_RSS,
        ResourceKind.POSTSEAL_WORKER_PEAK_GPU_MEMORY,
    }
)


def _status_wire() -> dict[str, Any]:
    return {
        "benchmark_status": BENCHMARK_STATUS,
        "evidence_qualification": EVIDENCE_QUALIFICATION,
        "runtime_binding": RUNTIME_BINDING,
        "input_authority": "caller_asserted_unbound",
        "coverage_scope": "provided_exposure_only",
        "freeze_authority": False,
        "freeze_authority_status": FREEZE_AUTHORITY_STATUS,
        "cross_metric_aggregate_score": CROSS_METRIC_AGGREGATE_SCORE,
    }


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    if any(ord(character) < 0x20 for character in value):
        raise ProtocolViolation(f"{label} contains a control character")
    return value


def _relative_path(value: object, label: str) -> str:
    path = _name(value, label)
    parsed = PurePosixPath(path)
    if (
        "\\" in path
        or ":" in path
        or parsed.is_absolute()
        or str(parsed) != path
        or path in {".", ".."}
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise ProtocolViolation(f"{label} must be a canonical POSIX relative path")
    return path


def _digest(value: object, label: str) -> str:
    if type(value) is not str or _DIGEST_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be a lowercase SHA-256 digest")
    return value


def _finite(value: object, label: str, *, nonnegative: bool = False) -> float:
    if type(value) not in {int, float}:
        raise ProtocolViolation(f"{label} must be an exact finite number")
    try:
        result = float(value)
    except OverflowError as exc:
        raise ProtocolViolation(f"{label} cannot be represented as binary64") from exc
    if not math.isfinite(result) or (nonnegative and result < 0.0):
        suffix = " non-negative" if nonnegative else ""
        raise ProtocolViolation(f"{label} must be an exact finite{suffix} number")
    return result


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0 or value > MAX_SAFE_EXACT_INTEGER:
        raise ProtocolViolation(
            f"{label} must be a non-negative exact integer no greater than "
            f"{MAX_SAFE_EXACT_INTEGER}"
        )
    return value


def _positive_int(value: object, label: str) -> int:
    result = _nonnegative_int(value, label)
    if result == 0:
        raise ProtocolViolation(f"{label} must be positive")
    return result


def _utc_timestamp(value: object, label: str) -> tuple[str, datetime]:
    if type(value) is not str or _RFC3339_UTC_RE.fullmatch(value) is None:
        raise ProtocolViolation(f"{label} must be canonical RFC3339 UTC seconds")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
    except ValueError as exc:
        raise ProtocolViolation(f"{label} is not a real UTC timestamp") from exc
    if parsed.strftime("%Y-%m-%dT%H:%M:%SZ") != value:
        raise ProtocolViolation(f"{label} must be canonical RFC3339 UTC seconds")
    return value, parsed


def _exact_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    actual = frozenset(value)
    if actual != expected:
        raise ProtocolViolation(
            f"{label} schema mismatch: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _safe_sum(values: tuple[float, ...], label: str) -> float:
    try:
        result = math.fsum(values)
    except (OverflowError, ValueError) as exc:
        raise ProtocolViolation(f"{label} derived arithmetic overflow") from exc
    if not math.isfinite(result):
        raise ProtocolViolation(f"{label} derived arithmetic is non-finite")
    return result


def _safe_value(value: float, label: str) -> float:
    if type(value) is not float or not math.isfinite(value):
        raise ProtocolViolation(f"{label} derived arithmetic is non-finite")
    return value


def _mean(values: tuple[float, ...], label: str) -> float:
    if not values:
        raise ProtocolViolation(f"{label} mean requires exposure")
    return _safe_value(_safe_sum(values, label) / len(values), f"{label} mean")


def _sample_sd(values: tuple[float, ...], mean: float, label: str) -> float:
    if len(values) < 2:
        raise ProtocolViolation(f"{label} sample SD requires at least two values")
    squares: list[float] = []
    for value in values:
        centered = _safe_value(value - mean, f"{label} centered value")
        squares.append(_safe_value(centered * centered, f"{label} square"))
    variance = _safe_value(
        _safe_sum(tuple(squares), f"{label} square sum") / (len(values) - 1),
        f"{label} sample variance",
    )
    return _safe_value(math.sqrt(variance), f"{label} sample SD")


@dataclass(frozen=True, slots=True)
class CanonicalEvidence:
    """Exact canonical JSON custody without opening a supplied path."""

    path: str
    canonical_bytes: bytes
    artifact_digest: str

    def __post_init__(self) -> None:
        _relative_path(self.path, "evidence path")
        if type(self.canonical_bytes) is not bytes or not self.canonical_bytes:
            raise ProtocolViolation(
                "evidence canonical_bytes must be exact non-empty bytes"
            )
        _digest(self.artifact_digest, "evidence artifact_digest")
        if digest_bytes(self.canonical_bytes) != self.artifact_digest:
            raise ProtocolViolation("evidence digest does not bind exact bytes")
        try:
            payload = json.loads(self.canonical_bytes.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ProtocolViolation("evidence must be strict UTF-8 JSON") from exc
        if type(payload) is not dict:
            raise ProtocolViolation("evidence must encode an exact object")
        validate_json_like(payload, path=self.path)
        if canonical_json_bytes(payload) != self.canonical_bytes:
            raise ProtocolViolation("evidence bytes are not canonical JSON")

    @classmethod
    def from_payload(cls, path: str, payload: dict[str, Any]) -> "CanonicalEvidence":
        if type(payload) is not dict:
            raise ProtocolViolation("evidence payload must be an exact object")
        try:
            raw = canonical_json_bytes(payload)
        except (OverflowError, RecursionError, ValueError) as exc:
            raise ProtocolViolation(
                "evidence payload is not representable as canonical JSON"
            ) from exc
        return cls(path, raw, digest_bytes(raw))

    @property
    def payload(self) -> dict[str, Any]:
        return json.loads(self.canonical_bytes)

    def reference_wire(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "byte_length": len(self.canonical_bytes),
            "artifact_digest": self.artifact_digest,
        }


@dataclass(frozen=True, slots=True)
class StateSizeRow:
    evidence: CanonicalEvidence
    record_id: str = field(init=False)
    candidate_id: str = field(init=False)
    scope_digest: str = field(init=False)
    candidate_artifact_digest: str = field(init=False)
    training_replicate_id: str = field(init=False)
    evaluation_replicate_id: str = field(init=False)
    world_slot: str = field(init=False)
    panel_id: str = field(init=False)
    family_id: str = field(init=False)
    stratum_id: str = field(init=False)
    task: str = field(init=False)
    episode_id: str = field(init=False)
    cut_id: str = field(init=False)
    expected_cell_id: str = field(init=False)
    history_slope_grain_id: str = field(init=False)
    horizon: int = field(init=False)
    policy_id: str = field(init=False)
    history_length: int = field(init=False)
    raw_bytes: int = field(init=False)
    compressed_bytes: int = field(init=False)
    scalar_count: int = field(init=False)
    node_count: int = field(init=False)
    edge_count: int = field(init=False)
    particle_count: int = field(init=False)
    state_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if type(self.evidence) is not CanonicalEvidence:
            raise ProtocolViolation("M12 row requires typed canonical evidence")
        row = self.evidence.payload
        _exact_keys(
            row,
            frozenset(
                {
                    "schema_version",
                    "record_id",
                    "candidate_id",
                    "scope_digest",
                    "candidate_artifact_digest",
                    "training_replicate_id",
                    "evaluation_replicate_id",
                    "world_slot",
                    "panel_id",
                    "family_id",
                    "stratum_id",
                    "task",
                    "episode_id",
                    "cut_id",
                    "expected_cell_id",
                    "history_slope_grain_id",
                    "horizon",
                    "policy_id",
                    "history_length",
                    "canonical_state",
                    "scalar_count",
                    "node_count",
                    "edge_count",
                    "particle_count",
                }
            ),
            "M12 state-size row",
        )
        if row["schema_version"] != M12_ROW_SCHEMA:
            raise ProtocolViolation("M12 row schema_version is invalid")
        for attribute in (
            "record_id",
            "candidate_id",
            "training_replicate_id",
            "evaluation_replicate_id",
            "world_slot",
            "panel_id",
            "family_id",
            "stratum_id",
            "task",
            "episode_id",
            "cut_id",
            "expected_cell_id",
            "history_slope_grain_id",
            "policy_id",
        ):
            object.__setattr__(
                self, attribute, _name(row[attribute], f"M12 {attribute}")
            )
        object.__setattr__(
            self, "scope_digest", _digest(row["scope_digest"], "M12 scope_digest")
        )
        object.__setattr__(
            self,
            "candidate_artifact_digest",
            _digest(row["candidate_artifact_digest"], "M12 candidate_artifact_digest"),
        )
        if (
            self.training_replicate_id,
            self.evaluation_replicate_id,
        ) not in ZIPPED_REPLICATE_IDS:
            raise ProtocolViolation(
                "M12 replicate identities are not a canonical zipped pair"
            )
        object.__setattr__(
            self, "horizon", _nonnegative_int(row["horizon"], "M12 horizon")
        )
        object.__setattr__(
            self,
            "history_length",
            _nonnegative_int(row["history_length"], "M12 history_length"),
        )
        for attribute in ("scalar_count", "node_count", "edge_count", "particle_count"):
            object.__setattr__(
                self,
                attribute,
                _nonnegative_int(row[attribute], f"M12 {attribute}"),
            )
        state = row["canonical_state"]
        validate_json_like(state, path="M12 canonical_state")
        raw = canonical_json_bytes(state)
        compressed = zlib.compress(raw, level=CODE_OWNED_COMPRESSOR_LEVEL)
        if type(compressed) is not bytes or not compressed:
            raise ProtocolViolation("M12 code-owned compressor returned invalid bytes")
        object.__setattr__(
            self, "raw_bytes", _nonnegative_int(len(raw), "M12 raw byte length")
        )
        object.__setattr__(
            self,
            "compressed_bytes",
            _nonnegative_int(len(compressed), "M12 compressed byte length"),
        )
        object.__setattr__(self, "state_digest", digest_bytes(raw))

    @property
    def identity(self) -> tuple[str, ...]:
        return (
            self.scope_digest,
            self.candidate_id,
            self.candidate_artifact_digest,
            self.training_replicate_id,
            self.evaluation_replicate_id,
            self.world_slot,
            self.panel_id,
            self.family_id,
            self.stratum_id,
            self.task,
            self.episode_id,
            self.cut_id,
            self.expected_cell_id,
            self.history_slope_grain_id,
            self.policy_id,
            str(self.horizon),
            self.record_id,
        )

    @property
    def fanout_identity(self) -> tuple[str, ...]:
        """State producer identity with downstream task/policy removed."""

        return (
            self.scope_digest,
            self.candidate_id,
            self.candidate_artifact_digest,
            self.training_replicate_id,
            self.evaluation_replicate_id,
            self.world_slot,
            self.panel_id,
            self.episode_id,
            self.cut_id,
        )

    @property
    def slope_grain_identity(self) -> tuple[str, ...]:
        return (
            self.scope_digest,
            self.candidate_id,
            self.candidate_artifact_digest,
            self.training_replicate_id,
            self.evaluation_replicate_id,
            self.world_slot,
            self.panel_id,
            self.family_id,
            self.stratum_id,
            self.task,
            str(self.horizon),
            self.policy_id,
            self.history_slope_grain_id,
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "candidate_id": self.candidate_id,
            "scope_digest": self.scope_digest,
            "candidate_artifact_digest": self.candidate_artifact_digest,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "family_id": self.family_id,
            "stratum_id": self.stratum_id,
            "task": self.task,
            "episode_id": self.episode_id,
            "cut_id": self.cut_id,
            "expected_cell_id": self.expected_cell_id,
            "history_slope_grain_id": self.history_slope_grain_id,
            "horizon": self.horizon,
            "policy_id": self.policy_id,
            "history_length": self.history_length,
            "canonical_state_raw_bytes": self.raw_bytes,
            "canonical_state_compressed_bytes_auxiliary": self.compressed_bytes,
            "state_digest": self.state_digest,
            "component_counts": {
                "verification_status": "caller_asserted_unverified",
                "scalar_count": self.scalar_count,
                "node_count": self.node_count,
                "edge_count": self.edge_count,
                "particle_count": self.particle_count,
            },
            "evidence": self.evidence.reference_wire(),
        }


def _ols_slope(points: tuple[tuple[int, int], ...], label: str) -> dict[str, Any]:
    if len(points) < 2:
        return {
            "status": "undefined",
            "undefined_reason": "fewer_than_two_rows",
            "slope": None,
            "exposure": len(points),
        }
    xs = tuple(float(point[0]) for point in points)
    ys = tuple(float(point[1]) for point in points)
    mean_x = _mean(xs, f"{label} x")
    mean_y = _mean(ys, f"{label} y")
    numerator_terms: list[float] = []
    denominator_terms: list[float] = []
    for x_value, y_value in zip(xs, ys, strict=True):
        x_centered = _safe_value(x_value - mean_x, f"{label} centered x")
        y_centered = _safe_value(y_value - mean_y, f"{label} centered y")
        numerator_terms.append(
            _safe_value(x_centered * y_centered, f"{label} cross product")
        )
        denominator_terms.append(
            _safe_value(x_centered * x_centered, f"{label} x square")
        )
    denominator = _safe_sum(tuple(denominator_terms), f"{label} denominator")
    if denominator == 0.0:
        return {
            "status": "undefined",
            "undefined_reason": "zero_predictor_variance",
            "slope": None,
            "exposure": len(points),
        }
    numerator = _safe_sum(tuple(numerator_terms), f"{label} numerator")
    return {
        "status": "defined",
        "undefined_reason": None,
        "slope": _safe_value(numerator / denominator, f"{label} slope"),
        "exposure": len(points),
    }


@dataclass(frozen=True, slots=True)
class StateSizeResult:
    rows: tuple[dict[str, Any], ...]
    history_length_slopes: tuple[dict[str, Any], ...]
    task_horizon_slices: tuple[dict[str, Any], ...]

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": M12_RESULT_SCHEMA,
            **_status_wire(),
            "metric_id": "M12",
            "no_single_score": True,
            "raw_byte_direction": MetricDirection.MINIMIZE.value,
            "raw_byte_unit": "byte",
            "compressed_bytes_role": "auxiliary_only",
            "compressor": {
                "compressor_id": CODE_OWNED_COMPRESSOR_ID,
                "level": CODE_OWNED_COMPRESSOR_LEVEL,
                "input": "canonical_utf8_json_plus_terminal_lf",
            },
            "component_count_unit": "count",
            "component_count_authority": "caller_asserted_unverified",
            "tie_policy": "retain_all_equal_rows",
            "rows": list(self.rows),
            "global_history_length_ols": {
                "status": "not_computed",
                "reason": "cross_grain_ols_would_be_confounding",
            },
            "history_length_ols_recipe": {
                "formula": "sum((x-mean_x)*(y-mean_y))/sum((x-mean_x)^2)",
                "predictor": "history_length_count",
                "response": "canonical_state_raw_bytes",
                "unit": "byte_per_visible_history_event",
                "direction": MetricDirection.MINIMIZE.value,
            },
            "history_length_ols_by_matched_grain": list(self.history_length_slopes),
            "task_horizon_slices": list(self.task_horizon_slices),
        }


def state_size_metrics(rows: tuple[StateSizeRow, ...]) -> StateSizeResult:
    if (
        type(rows) is not tuple
        or not rows
        or any(type(row) is not StateSizeRow for row in rows)
    ):
        raise ProtocolViolation(
            "M12 rows must be a non-empty exact tuple of StateSizeRow"
        )
    candidate_ids = {row.candidate_id for row in rows}
    if len(candidate_ids) != 1:
        raise ProtocolViolation("M12 rows must belong to exactly one candidate")
    for label, values in (
        ("scope", {row.scope_digest for row in rows}),
        ("candidate artifact", {row.candidate_artifact_digest for row in rows}),
        (
            "zipped replicate",
            {(row.training_replicate_id, row.evaluation_replicate_id) for row in rows},
        ),
    ):
        if len(values) != 1:
            raise ProtocolViolation(f"M12 rows cannot mix {label} authority")
    record_ids = [row.record_id for row in rows]
    if len(record_ids) != len(set(record_ids)):
        raise ProtocolViolation("M12 record_id values must be unique")
    cell_keys = [row.identity[:-1] for row in rows]
    if len(cell_keys) != len(set(cell_keys)):
        raise ProtocolViolation("M12 evaluation cell identities must be unique")
    fanout_keys = [row.fanout_identity for row in rows]
    if len(fanout_keys) != len(set(fanout_keys)):
        raise ProtocolViolation(
            "M12 same state producer cannot be reweighted through task/policy fanout"
        )
    ordered = tuple(sorted(rows, key=lambda row: row.identity))
    slope_groups: dict[tuple[str, ...], list[StateSizeRow]] = {}
    for row in ordered:
        slope_groups.setdefault(row.slope_grain_identity, []).append(row)
    slopes: list[dict[str, Any]] = []
    for grain, members in sorted(slope_groups.items()):
        slopes.append(
            {
                "grain": {
                    "scope_digest": grain[0],
                    "candidate_id": grain[1],
                    "candidate_artifact_digest": grain[2],
                    "training_replicate_id": grain[3],
                    "evaluation_replicate_id": grain[4],
                    "world_slot": grain[5],
                    "panel_id": grain[6],
                    "family_id": grain[7],
                    "stratum_id": grain[8],
                    "task": grain[9],
                    "horizon": int(grain[10]),
                    "policy_id": grain[11],
                    "history_slope_grain_id": grain[12],
                },
                **_ols_slope(
                    tuple(
                        (member.history_length, member.raw_bytes) for member in members
                    ),
                    f"M12 matched grain {grain!r}",
                ),
            }
        )
    groups: dict[tuple[str, int], list[StateSizeRow]] = {}
    for row in ordered:
        groups.setdefault((row.task, row.horizon), []).append(row)
    slices: list[dict[str, Any]] = []
    for (task, horizon), members in sorted(groups.items()):
        raw = tuple(float(member.raw_bytes) for member in members)
        compressed = tuple(float(member.compressed_bytes) for member in members)
        slices.append(
            {
                "task": task,
                "horizon": horizon,
                "exposure": len(members),
                "raw_bytes": {
                    "unit": "byte",
                    "direction": MetricDirection.MINIMIZE.value,
                    "mean": _mean(raw, f"M12 {task}/{horizon} raw"),
                    "min": int(min(raw)),
                    "max": int(max(raw)),
                },
                "compressed_bytes_auxiliary": {
                    "unit": "byte",
                    "mean": _mean(compressed, f"M12 {task}/{horizon} compressed"),
                    "min": int(min(compressed)),
                    "max": int(max(compressed)),
                },
            }
        )
    return StateSizeResult(
        tuple(row.to_wire() for row in ordered), tuple(slopes), tuple(slices)
    )


@dataclass(frozen=True, slots=True)
class CollectorProvenance:
    evidence: CanonicalEvidence
    collector_id: str = field(init=False)
    run_id: str = field(init=False)
    candidate_id: str = field(init=False)
    scope_digest: str = field(init=False)
    environment_digest: str = field(init=False)
    cold_process_per_sample: bool = field(init=False)

    def __post_init__(self) -> None:
        if type(self.evidence) is not CanonicalEvidence:
            raise ProtocolViolation("M13 provenance requires typed canonical evidence")
        row = self.evidence.payload
        _exact_keys(
            row,
            frozenset(
                {
                    "schema_version",
                    "collector_id",
                    "collector_version",
                    "run_id",
                    "candidate_id",
                    "scope_digest",
                    "collector_source_digest",
                    "collector_config_digest",
                    "environment_digest",
                    "clock_source",
                    "memory_source",
                    "started_at_utc",
                    "finished_at_utc",
                    "cold_process_per_sample",
                }
            ),
            "M13 collector provenance",
        )
        if row["schema_version"] != M13_PROVENANCE_SCHEMA:
            raise ProtocolViolation("M13 provenance schema_version is invalid")
        for key in (
            "collector_id",
            "collector_version",
            "run_id",
            "candidate_id",
            "clock_source",
            "memory_source",
        ):
            _name(row[key], f"M13 provenance {key}")
        for key in (
            "scope_digest",
            "collector_source_digest",
            "collector_config_digest",
            "environment_digest",
        ):
            _digest(row[key], f"M13 provenance {key}")
        _, started = _utc_timestamp(
            row["started_at_utc"], "M13 provenance started_at_utc"
        )
        _, finished = _utc_timestamp(
            row["finished_at_utc"], "M13 provenance finished_at_utc"
        )
        if started > finished:
            raise ProtocolViolation("M13 provenance start time exceeds finish time")
        if type(row["cold_process_per_sample"]) is not bool:
            raise ProtocolViolation("M13 cold_process_per_sample must be exact boolean")
        object.__setattr__(self, "collector_id", row["collector_id"])
        object.__setattr__(self, "run_id", row["run_id"])
        object.__setattr__(self, "candidate_id", row["candidate_id"])
        object.__setattr__(self, "scope_digest", row["scope_digest"])
        object.__setattr__(self, "environment_digest", row["environment_digest"])
        object.__setattr__(
            self, "cold_process_per_sample", row["cold_process_per_sample"]
        )

    def reference_wire(self) -> dict[str, Any]:
        return {
            **self.evidence.reference_wire(),
            "canonical_bytes_hex": self.evidence.canonical_bytes.hex(),
        }


@dataclass(frozen=True, slots=True)
class ResourceMeasurement:
    evidence: CanonicalEvidence
    provenance: CollectorProvenance
    measurement_id: str = field(init=False)
    run_id: str = field(init=False)
    candidate_id: str = field(init=False)
    scope_digest: str = field(init=False)
    kind: ResourceKind = field(init=False)
    operation: CandidateOperation | None = field(init=False)
    value: int | float | None = field(init=False)
    undefined_reason: str | None = field(init=False)

    def __post_init__(self) -> None:
        if (
            type(self.evidence) is not CanonicalEvidence
            or type(self.provenance) is not CollectorProvenance
        ):
            raise ProtocolViolation(
                "M13 measurement requires typed evidence and provenance"
            )
        row = self.evidence.payload
        _exact_keys(
            row,
            frozenset(
                {
                    "schema_version",
                    "measurement_id",
                    "run_id",
                    "candidate_id",
                    "scope_digest",
                    "resource_kind",
                    "operation",
                    "value",
                    "unit",
                    "undefined_reason",
                    "collector_provenance_digest",
                }
            ),
            "M13 resource measurement",
        )
        if row["schema_version"] != M13_MEASUREMENT_SCHEMA:
            raise ProtocolViolation("M13 measurement schema_version is invalid")
        measurement_id = _name(row["measurement_id"], "M13 measurement_id")
        run_id = _name(row["run_id"], "M13 run_id")
        candidate_id = _name(row["candidate_id"], "M13 candidate_id")
        scope_digest = _digest(row["scope_digest"], "M13 scope_digest")
        try:
            kind = ResourceKind(row["resource_kind"])
        except (TypeError, ValueError) as exc:
            raise ProtocolViolation("M13 resource_kind is not code-owned") from exc
        if row["unit"] != _RESOURCE_UNITS[kind]:
            raise ProtocolViolation("M13 resource unit does not match resource_kind")
        raw_operation = row["operation"]
        if kind is ResourceKind.COLD_LATENCY:
            try:
                operation = CandidateOperation(raw_operation)
            except (TypeError, ValueError) as exc:
                raise ProtocolViolation(
                    "M13 cold latency requires a code-owned operation"
                ) from exc
            if not self.provenance.cold_process_per_sample:
                raise ProtocolViolation(
                    "M13 cold latency provenance is not cold-process-per-sample"
                )
        else:
            if raw_operation is not None:
                raise ProtocolViolation(
                    "M13 non-latency resource operation must be null"
                )
            operation = None
        if (
            row["collector_provenance_digest"]
            != self.provenance.evidence.artifact_digest
        ):
            raise ProtocolViolation("M13 measurement does not bind provenance bytes")
        if (
            run_id != self.provenance.run_id
            or candidate_id != self.provenance.candidate_id
            or scope_digest != self.provenance.scope_digest
        ):
            raise ProtocolViolation(
                "M13 measurement run/candidate/scope differs from provenance"
            )
        raw_value = row["value"]
        raw_reason = row["undefined_reason"]
        if raw_value is None:
            value = None
            reason = _name(raw_reason, "M13 undefined_reason")
        else:
            if kind in _EXACT_INTEGER_RESOURCE_KINDS:
                value = _nonnegative_int(raw_value, "M13 count/byte resource value")
            else:
                value = _finite(raw_value, "M13 resource value", nonnegative=True)
            if raw_reason is not None:
                raise ProtocolViolation(
                    "M13 defined resource cannot carry undefined_reason"
                )
            reason = None
        object.__setattr__(self, "measurement_id", measurement_id)
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "scope_digest", scope_digest)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "operation", operation)
        object.__setattr__(self, "value", value)
        object.__setattr__(self, "undefined_reason", reason)

    def reference_wire(self) -> dict[str, Any]:
        return {
            "measurement_id": self.measurement_id,
            "measurement_evidence": self.evidence.reference_wire(),
            "collector_provenance": self.provenance.reference_wire(),
        }


def _hf7(values: tuple[float, ...], probability: float, label: str) -> float:
    if not values:
        raise ProtocolViolation(f"{label} quantile requires exposure")
    ordered = tuple(sorted(values))
    h = _safe_value((len(ordered) - 1) * probability, f"{label} HF7 index")
    lower = int(math.floor(h))
    upper = int(math.ceil(h))
    if lower == upper:
        return ordered[lower]
    fraction = _safe_value(h - lower, f"{label} HF7 fraction")
    delta = _safe_value(ordered[upper] - ordered[lower], f"{label} HF7 delta")
    return _safe_value(ordered[lower] + fraction * delta, f"{label} HF7 value")


@dataclass(frozen=True, slots=True)
class ResourceResult:
    cold_latency: tuple[dict[str, Any], ...]
    resources: tuple[dict[str, Any], ...]
    provided_measurement_count: int
    authority_identity: dict[str, Any] | None

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": M13_RESULT_SCHEMA,
            **_status_wire(),
            "metric_id": "M13",
            "no_single_score": True,
            "collector_evidence_status": "partial_untrusted_collector",
            "collector_authority": "caller_asserted",
            "direction": MetricDirection.MINIMIZE.value,
            "latency_quantile_recipe": HF7_QUANTILE_RECIPE,
            "undefined_policy": "null_with_reason_and_zero_defined_exposure",
            "coverage": {
                "claim": "provided_exposure_only",
                "provided_measurement_count": self.provided_measurement_count,
                "expected_measurement_count": None,
                "coverage_denominator": None,
                "coverage_complete": None,
                "deletion_detection": "unavailable_without_bound_expected_cells",
            },
            "authority_identity": self.authority_identity,
            "cold_latency_by_operation": list(self.cold_latency),
            "resource_measurements": list(self.resources),
        }


def resource_metrics(measurements: tuple[ResourceMeasurement, ...]) -> ResourceResult:
    if type(measurements) is not tuple or any(
        type(item) is not ResourceMeasurement for item in measurements
    ):
        raise ProtocolViolation(
            "M13 measurements must be an exact tuple of ResourceMeasurement"
        )
    ids = [item.measurement_id for item in measurements]
    if len(ids) != len(set(ids)):
        raise ProtocolViolation("M13 measurement_id values must be unique")
    authorities = {
        (
            item.provenance.evidence.artifact_digest,
            item.provenance.environment_digest,
            item.run_id,
            item.candidate_id,
            item.scope_digest,
        )
        for item in measurements
    }
    if len(authorities) > 1:
        raise ProtocolViolation(
            "M13 measurements cannot mix provenance/environment/run/candidate/scope"
        )
    authority_identity = None
    if authorities:
        provenance_digest, environment_digest, run_id, candidate_id, scope_digest = (
            next(iter(authorities))
        )
        authority_identity = {
            "collector_provenance_digest": provenance_digest,
            "environment_digest": environment_digest,
            "run_id": run_id,
            "candidate_id": candidate_id,
            "scope_digest": scope_digest,
        }
    ordered = tuple(sorted(measurements, key=lambda item: item.measurement_id))
    latency_rows: list[dict[str, Any]] = []
    for operation in CandidateOperation:
        members = tuple(
            item
            for item in ordered
            if item.kind is ResourceKind.COLD_LATENCY and item.operation is operation
        )
        defined = tuple(item.value for item in members if item.value is not None)
        values = tuple(float(value) for value in defined)
        if values:
            summary = {
                "status": "defined",
                "undefined_reason": None,
                "p50": _hf7(values, 0.50, f"M13 {operation.value} p50"),
                "p95": _hf7(values, 0.95, f"M13 {operation.value} p95"),
                "p99": _hf7(values, 0.99, f"M13 {operation.value} p99"),
            }
        else:
            summary = {
                "status": "undefined",
                "undefined_reason": (
                    "not_provided_no_coverage_claim"
                    if not members
                    else "all_measurements_undefined"
                ),
                "p50": None,
                "p95": None,
                "p99": None,
            }
        latency_rows.append(
            {
                "operation": operation.value,
                "unit": "nanosecond",
                "direction": MetricDirection.MINIMIZE.value,
                "defined_exposure": len(values),
                "undefined_exposure": len(members) - len(values),
                **summary,
                "evidence": [item.reference_wire() for item in members],
            }
        )
    resource_rows: list[dict[str, Any]] = []
    for kind in ResourceKind:
        if kind is ResourceKind.COLD_LATENCY:
            continue
        members = tuple(item for item in ordered if item.kind is kind)
        if len(members) > 1:
            raise ProtocolViolation(
                f"M13 {kind.value} requires at most one measurement row"
            )
        if not members:
            resource_rows.append(
                {
                    "resource_kind": kind.value,
                    "unit": _RESOURCE_UNITS[kind],
                    "direction": MetricDirection.MINIMIZE.value,
                    "status": "undefined",
                    "undefined_reason": "not_provided_no_coverage_claim",
                    "value": None,
                    "evidence": None,
                }
            )
            continue
        member = members[0]
        resource_rows.append(
            {
                "resource_kind": kind.value,
                "unit": _RESOURCE_UNITS[kind],
                "direction": MetricDirection.MINIMIZE.value,
                "status": "defined" if member.value is not None else "undefined",
                "undefined_reason": member.undefined_reason,
                "value": member.value,
                "evidence": member.reference_wire(),
            }
        )
    return ResourceResult(
        tuple(latency_rows),
        tuple(resource_rows),
        len(measurements),
        authority_identity,
    )


@dataclass(frozen=True, slots=True)
class ReplicateSeries:
    replicate_pairs: tuple[tuple[str, str], ...]
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        if type(self.replicate_pairs) is not tuple or type(self.values) is not tuple:
            raise ProtocolViolation(
                "M14 replicate pairs and values must be exact tuples"
            )
        if (
            len(self.replicate_pairs) != FIVE_REPLICATE_COUNT
            or len(self.values) != FIVE_REPLICATE_COUNT
        ):
            raise ProtocolViolation("M14 requires exactly five zipped replicates")
        pairs: list[tuple[str, str]] = []
        for raw_pair in self.replicate_pairs:
            if type(raw_pair) is not tuple or len(raw_pair) != 2:
                raise ProtocolViolation("M14 replicate pair must be an exact pair")
            pairs.append(
                (
                    _name(raw_pair[0], "M14 training_replicate_id"),
                    _name(raw_pair[1], "M14 evaluation_replicate_id"),
                )
            )
        normalized_pairs = tuple(pairs)
        if normalized_pairs != ZIPPED_REPLICATE_IDS:
            raise ProtocolViolation(
                "M14 must use seed_protocol.ZIPPED_REPLICATE_IDS exactly"
            )
        normalized = tuple(
            _finite(value, "M14 replicate value") for value in self.values
        )
        object.__setattr__(self, "replicate_pairs", normalized_pairs)
        object.__setattr__(self, "values", normalized)


def _five_summary(values: tuple[float, ...], label: str) -> dict[str, Any]:
    if len(values) != FIVE_REPLICATE_COUNT:
        raise ProtocolViolation(f"{label} requires exactly five values")
    mean = _mean(values, label)
    sd = _sample_sd(values, mean, label)
    standard_error = _safe_value(
        sd / math.sqrt(FIVE_REPLICATE_COUNT), f"{label} standard error"
    )
    half_width = _safe_value(
        STUDENT_T_95_CRITICAL_DF4 * standard_error,
        f"{label} CI half width",
    )
    return {
        "mean": mean,
        "sample_sd": sd,
        "min": min(values),
        "max": max(values),
        "standard_error": standard_error,
        "ci95_lower": _safe_value(mean - half_width, f"{label} CI lower"),
        "ci95_upper": _safe_value(mean + half_width, f"{label} CI upper"),
    }


@dataclass(frozen=True, slots=True)
class FiveSeedStabilityResult:
    metric_name: str
    unit: str
    direction: MetricDirection
    replicate_pairs: tuple[tuple[str, str], ...]
    candidate_values: tuple[float, ...]
    candidate_summary: dict[str, Any]
    baseline_values: tuple[float, ...] | None
    paired_deltas: tuple[float, ...] | None
    paired_summary: dict[str, Any] | None

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": M14_RESULT_SCHEMA,
            **_status_wire(),
            "metric_id": "M14",
            "no_single_score": True,
            "metric_name": self.metric_name,
            "unit": self.unit,
            "direction": self.direction.value,
            "tie_policy": "retain_equal_replicates_and_zero_variance",
            "pairing": {
                "method": "same_index_zipped_replicate",
                "cartesian_5x5_forbidden": True,
                "replicate_pairs": [
                    {
                        "training_replicate_id": training_id,
                        "evaluation_replicate_id": evaluation_id,
                    }
                    for training_id, evaluation_id in self.replicate_pairs
                ],
                "authority": "seed_protocol.ZIPPED_REPLICATE_IDS",
            },
            "seed_ci95_recipe": {
                "method": "student_t_on_five_replicate_world_macro",
                "confidence_level": 0.95,
                "sample_sd_ddof": 1,
                "replicate_count": FIVE_REPLICATE_COUNT,
                "degrees_of_freedom": STUDENT_T_DEGREES_OF_FREEDOM,
                "critical_value": STUDENT_T_95_CRITICAL_DF4,
            },
            "candidate": {
                "value_grain": "replicate_level_fixed_world_macro_caller_asserted",
                "values": list(self.candidate_values),
                **self.candidate_summary,
            },
            "paired_baseline": None
            if self.baseline_values is None
            else {
                "values": list(self.baseline_values),
                "delta_convention": "candidate_minus_baseline",
                "paired_deltas": list(self.paired_deltas or ()),
                "summary": self.paired_summary,
            },
            "hierarchical_bootstrap_ci95": {
                "status": "unavailable",
                "undefined_reason": "sampling_preimage_endpoint_rule_and_analysis_seed_unbound",
                "blocker_code": HIERARCHICAL_BOOTSTRAP_BLOCKER,
                "required_replicates": 10000,
            },
        }


def five_seed_stability(
    *,
    metric_name: str,
    unit: str,
    direction: MetricDirection,
    candidate: ReplicateSeries,
    baseline: ReplicateSeries | None = None,
) -> FiveSeedStabilityResult:
    name = _name(metric_name, "M14 metric_name")
    metric_unit = _name(unit, "M14 unit")
    if type(direction) is not MetricDirection:
        raise ProtocolViolation("M14 direction must be a typed MetricDirection")
    if type(candidate) is not ReplicateSeries:
        raise ProtocolViolation("M14 candidate must be a typed ReplicateSeries")
    if baseline is not None and type(baseline) is not ReplicateSeries:
        raise ProtocolViolation("M14 baseline must be null or a typed ReplicateSeries")
    baseline_values: tuple[float, ...] | None = None
    deltas: tuple[float, ...] | None = None
    paired_summary: dict[str, Any] | None = None
    if baseline is not None:
        if candidate.replicate_pairs != baseline.replicate_pairs:
            raise ProtocolViolation(
                "M14 candidate/baseline replicate IDs do not zip exactly"
            )
        baseline_values = baseline.values
        delta_list: list[float] = []
        for candidate_value, baseline_value in zip(
            candidate.values, baseline.values, strict=True
        ):
            delta_list.append(
                _safe_value(
                    candidate_value - baseline_value,
                    "M14 paired candidate-minus-baseline delta",
                )
            )
        deltas = tuple(delta_list)
        paired_summary = _five_summary(deltas, "M14 paired delta")
    return FiveSeedStabilityResult(
        metric_name=name,
        unit=metric_unit,
        direction=direction,
        replicate_pairs=candidate.replicate_pairs,
        candidate_values=candidate.values,
        candidate_summary=_five_summary(candidate.values, "M14 candidate"),
        baseline_values=baseline_values,
        paired_deltas=deltas,
        paired_summary=paired_summary,
    )


__all__ = [
    "BENCHMARK_STATUS",
    "CODE_OWNED_COMPRESSOR_ID",
    "CROSS_METRIC_AGGREGATE_SCORE",
    "CandidateOperation",
    "CanonicalEvidence",
    "CollectorProvenance",
    "EVIDENCE_QUALIFICATION",
    "FREEZE_AUTHORITY_STATUS",
    "FiveSeedStabilityResult",
    "HIERARCHICAL_BOOTSTRAP_BLOCKER",
    "M12_RESULT_SCHEMA",
    "M12_ROW_SCHEMA",
    "M13_MEASUREMENT_SCHEMA",
    "M13_PROVENANCE_SCHEMA",
    "M13_RESULT_SCHEMA",
    "M14_RESULT_SCHEMA",
    "MetricDirection",
    "ReplicateSeries",
    "ResourceKind",
    "ResourceMeasurement",
    "ResourceResult",
    "StateSizeResult",
    "StateSizeRow",
    "five_seed_stability",
    "resource_metrics",
    "state_size_metrics",
]
