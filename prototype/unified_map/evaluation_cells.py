"""Freeze-safe materialization of the UCM v1 exact evaluation-cell manifest.

This module deliberately does not invent an evaluation population.  It only
compiles cells from corpus shards that already exist as physically separated,
canonical candidate/judge JSONL streams and whose completed materialization
receipt and content digests are frozen in :class:`ExpectedCellsScopeContract`.
Missing, truncated, non-canonical, stale-scope, or otherwise unverified input
therefore produces a typed ``INCOMPLETE`` result and no ``expected-cells.json``.

The materialized :class:`~prototype.unified_map.evaluator.EvaluationManifest`
is denominator-safe: every population record has every task declared by its
shard, every probe pair is explicitly registered, W15 panels remain distinct,
and W19's tail cohort is derived from the judge-side frozen stratum rather than
from candidate output.  Raw results can subsequently be checked with
``audit_raw_exact_join`` before metric aggregation.

Important: this revision is intentionally a **PRE-FREEZE scaffold**.  The
code-owned v1 coverage lock contains the complete outer W01--W20/panel/split/
TRAIN5-EVAL5 shape but no authoritative scope, lineage, query, or raw-ledger
roots yet.  ``build_expected_cells`` therefore cannot return ``COMPLETE`` and
``materialize_expected_cells`` cannot publish ``expected-cells.json``.  Local
fixture compilation returns ``PRE_FREEZE_SCAFFOLD`` only; raw structural joins
are explicitly not benchmark-freeze evidence.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterable

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
    validate_json_like,
)
from .evaluator import (
    EvaluationCohort,
    EvaluationManifest,
    EvaluationSplit,
    EvaluationTask,
    ExpectedEvaluationCell,
    ExpectedPairCell,
    IdentificationKind,
    OODAttribution,
    PairThresholds,
    RawEvaluationRecord,
    RawPairRecord,
    W19SafetyDeclaration,
)
from .world_registry import WORLD_REGISTRY, registry_digest


INCOMPLETE_CODE = "UCM-E003-HARNESS_INCOMPLETE"


def _name(value: object, label: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise ProtocolViolation(f"{label} must be a canonical non-empty string")
    return value


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 71 or not value.startswith("sha256:"):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    try:
        int(value[7:], 16)
    except ValueError as exc:
        raise ProtocolViolation(f"{label} must be hexadecimal") from exc
    return value


def _path(value: object, label: str) -> Path:
    if not isinstance(value, Path):
        raise ProtocolViolation(f"{label} must be pathlib.Path")
    return value


def _canonical_sort(values: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(sorted(values, key=lambda item: canonical_json_bytes(item.to_wire())))


class CellMaterializationStatus(str, Enum):
    PRE_FREEZE_SCAFFOLD = "pre_freeze_scaffold"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class CellMaterializationBlocker:
    code: str
    artifact: str
    detail: str

    def __post_init__(self) -> None:
        _name(self.code, "blocker code")
        _name(self.artifact, "blocker artifact")
        _name(self.detail, "blocker detail")

    def to_wire(self) -> dict[str, str]:
        return {"code": self.code, "artifact": self.artifact, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class FrozenCorpusShard:
    """Path-independent frozen evidence plus local paths used for replay.

    The three paths are intentionally omitted from :meth:`to_wire`; moving an
    unchanged sealed corpus does not alter the contract digest.  The exact
    bytes at those paths are nevertheless required to match all three frozen
    digests before any expected cell can be emitted.
    """

    shard_id: str
    world_slot: str
    panel_id: str
    split: EvaluationSplit
    training_replicate_id: str
    evaluation_replicate_id: str
    required_tasks: tuple[EvaluationTask, ...]
    candidate_path: Path
    judge_path: Path
    status_path: Path
    candidate_digest: str
    judge_digest: str
    status_digest: str

    def __post_init__(self) -> None:
        for value, label in (
            (self.shard_id, "shard_id"),
            (self.world_slot, "world_slot"),
            (self.panel_id, "panel_id"),
            (self.training_replicate_id, "training_replicate_id"),
            (self.evaluation_replicate_id, "evaluation_replicate_id"),
        ):
            _name(value, label)
        if type(self.split) is not EvaluationSplit:
            raise ProtocolViolation("shard split must be EvaluationSplit")
        if type(self.required_tasks) is not tuple or not self.required_tasks:
            raise ProtocolViolation("required_tasks must be a non-empty tuple")
        if any(type(item) is not EvaluationTask for item in self.required_tasks):
            raise ProtocolViolation("required_tasks contains a non-EvaluationTask")
        if len(set(self.required_tasks)) != len(self.required_tasks):
            raise ProtocolViolation("required_tasks must be unique")
        _path(self.candidate_path, "candidate_path")
        _path(self.judge_path, "judge_path")
        _path(self.status_path, "status_path")
        for value, label in (
            (self.candidate_digest, "candidate_digest"),
            (self.judge_digest, "judge_digest"),
            (self.status_digest, "status_digest"),
        ):
            _digest(value, label)

    def to_wire(self) -> dict[str, Any]:
        return {
            "shard_id": self.shard_id,
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "split": self.split.value,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "required_tasks": sorted(item.value for item in self.required_tasks),
            "candidate_digest": self.candidate_digest,
            "judge_digest": self.judge_digest,
            "status_digest": self.status_digest,
        }


@dataclass(frozen=True, slots=True)
class QueryCellContract:
    shard_id: str
    source_record_id: str
    cut_alias: str
    task: EvaluationTask
    horizon: int
    policy_alias: str
    ood_attribution: OODAttribution = OODAttribution.NOT_APPLICABLE
    unsafe_action_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for value, label in (
            (self.shard_id, "query shard_id"),
            (self.source_record_id, "query source_record_id"),
            (self.cut_alias, "query cut_alias"),
            (self.policy_alias, "query policy_alias"),
        ):
            _name(value, label)
        if type(self.task) is not EvaluationTask:
            raise ProtocolViolation("query task must be EvaluationTask")
        if type(self.horizon) is not int or self.horizon < 0:
            raise ProtocolViolation("query horizon must be non-negative")
        if type(self.ood_attribution) is not OODAttribution:
            raise ProtocolViolation("query ood_attribution must be OODAttribution")
        if self.task is EvaluationTask.OOD:
            if self.ood_attribution is OODAttribution.NOT_APPLICABLE:
                raise ProtocolViolation("OOD query requires an attribution class")
        elif self.ood_attribution is not OODAttribution.NOT_APPLICABLE:
            raise ProtocolViolation("non-OOD query cannot carry OOD attribution")
        if type(self.unsafe_action_ids) is not tuple or any(
            type(item) is not str or not item for item in self.unsafe_action_ids
        ):
            raise ProtocolViolation("unsafe_action_ids must be tuple[str, ...]")
        if len(set(self.unsafe_action_ids)) != len(self.unsafe_action_ids):
            raise ProtocolViolation("unsafe_action_ids must be unique")

    def to_wire(self) -> dict[str, Any]:
        return {
            "shard_id": self.shard_id,
            "source_record_id": self.source_record_id,
            "cut_alias": self.cut_alias,
            "task": self.task.value,
            "horizon": self.horizon,
            "policy_alias": self.policy_alias,
            "ood_attribution": self.ood_attribution.value,
            "unsafe_action_ids": sorted(self.unsafe_action_ids),
        }


@dataclass(frozen=True, slots=True)
class PairCellContract:
    shard_id: str
    source_pair_id: str
    thresholds: PairThresholds

    def __post_init__(self) -> None:
        _name(self.shard_id, "pair shard_id")
        _name(self.source_pair_id, "source_pair_id")
        if type(self.thresholds) is not PairThresholds:
            raise ProtocolViolation("pair thresholds must be PairThresholds")

    def to_wire(self) -> dict[str, Any]:
        return {
            "shard_id": self.shard_id,
            "source_pair_id": self.source_pair_id,
            "thresholds": self.thresholds.to_wire(),
        }


@dataclass(frozen=True, slots=True)
class W19SafetyContract:
    contraindicated_action_id: str
    catastrophic_margin: float

    def __post_init__(self) -> None:
        _name(self.contraindicated_action_id, "contraindicated_action_id")
        if (
            type(self.catastrophic_margin) not in {int, float}
            or not math.isfinite(float(self.catastrophic_margin))
            or float(self.catastrophic_margin) < 0.0
        ):
            raise ProtocolViolation("catastrophic_margin must be finite and non-negative")

    def to_wire(self) -> dict[str, Any]:
        return {
            "contraindicated_action_id": self.contraindicated_action_id,
            "catastrophic_margin": float(self.catastrophic_margin),
        }


@dataclass(frozen=True, slots=True)
class LockedQueryTemplate:
    cut_alias: str
    task: EvaluationTask
    horizon: int
    policy_alias: str

    def __post_init__(self) -> None:
        _name(self.cut_alias, "locked query cut_alias")
        if type(self.task) is not EvaluationTask:
            raise ProtocolViolation("locked query task must be EvaluationTask")
        if type(self.horizon) is not int or self.horizon < 0:
            raise ProtocolViolation("locked query horizon must be non-negative")
        _name(self.policy_alias, "locked query policy_alias")

    @property
    def identity(self) -> tuple[str, EvaluationTask, int, str]:
        return self.cut_alias, self.task, self.horizon, self.policy_alias

    def to_wire(self) -> dict[str, Any]:
        return {
            "cut_alias": self.cut_alias,
            "task": self.task.value,
            "horizon": self.horizon,
            "policy_alias": self.policy_alias,
        }


@dataclass(frozen=True, slots=True)
class LockedShardCoverage:
    world_slot: str
    panel_id: str
    split: EvaluationSplit
    training_replicate_id: str
    evaluation_replicate_id: str
    population_queries: tuple[LockedQueryTemplate, ...]
    probe_queries: tuple[LockedQueryTemplate, ...] = ()

    def __post_init__(self) -> None:
        for value, label in (
            (self.world_slot, "locked world_slot"),
            (self.panel_id, "locked panel_id"),
            (self.training_replicate_id, "locked training_replicate_id"),
            (self.evaluation_replicate_id, "locked evaluation_replicate_id"),
        ):
            _name(value, label)
        if type(self.split) is not EvaluationSplit:
            raise ProtocolViolation("locked split must be EvaluationSplit")
        for values, label in (
            (self.population_queries, "population_queries"),
            (self.probe_queries, "probe_queries"),
        ):
            if type(values) is not tuple or any(
                type(item) is not LockedQueryTemplate for item in values
            ):
                raise ProtocolViolation(f"{label} contains a wrong type")
            identities = [item.identity for item in values]
            if len(identities) != len(set(identities)):
                raise ProtocolViolation(f"{label} identities must be unique")

    @property
    def identity(self) -> tuple[str, str, EvaluationSplit, str, str]:
        return (
            self.world_slot,
            self.panel_id,
            self.split,
            self.training_replicate_id,
            self.evaluation_replicate_id,
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "split": self.split.value,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "population_queries": [
                item.to_wire() for item in _canonical_sort(self.population_queries)
            ],
            "probe_queries": [
                item.to_wire() for item in _canonical_sort(self.probe_queries)
            ],
        }


@dataclass(frozen=True, slots=True)
class BenchmarkCoverageLock:
    benchmark_id: str
    benchmark_revision: str
    scope_digest: str | None
    scope_manifest_digest: str | None
    family_source_digest: str | None
    family_manifest_digest: str | None
    family_seal_digest: str | None
    raw_roots_digest: str | None
    query_scope_frozen: bool
    shards: tuple[LockedShardCoverage, ...]

    def __post_init__(self) -> None:
        _name(self.benchmark_id, "coverage benchmark_id")
        _name(self.benchmark_revision, "coverage benchmark_revision")
        for value, label in (
            (self.scope_digest, "coverage scope_digest"),
            (self.scope_manifest_digest, "coverage scope_manifest_digest"),
            (self.family_source_digest, "coverage family_source_digest"),
            (self.family_manifest_digest, "coverage family_manifest_digest"),
            (self.family_seal_digest, "coverage family_seal_digest"),
            (self.raw_roots_digest, "coverage raw_roots_digest"),
        ):
            if value is not None:
                _digest(value, label)
        if type(self.query_scope_frozen) is not bool:
            raise ProtocolViolation("query_scope_frozen must be boolean")
        if type(self.shards) is not tuple or not self.shards or any(
            type(item) is not LockedShardCoverage for item in self.shards
        ):
            raise ProtocolViolation("coverage shards must be non-empty locked entries")
        identities = [item.identity for item in self.shards]
        if len(identities) != len(set(identities)):
            raise ProtocolViolation("coverage shard identities must be unique")

    @property
    def ready(self) -> bool:
        return (
            self.scope_digest is not None
            and self.scope_manifest_digest is not None
            and self.family_source_digest is not None
            and self.family_manifest_digest is not None
            and self.family_seal_digest is not None
            and self.raw_roots_digest is not None
            and self.query_scope_frozen
            and all(item.population_queries for item in self.shards)
        )

    def to_wire(self) -> dict[str, Any]:
        body = {
            "schema_version": "ucm-benchmark-v1-coverage-lock/1",
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "scope_digest": self.scope_digest,
            "scope_manifest_digest": self.scope_manifest_digest,
            "family_source_digest": self.family_source_digest,
            "family_manifest_digest": self.family_manifest_digest,
            "family_seal_digest": self.family_seal_digest,
            "raw_roots_digest": self.raw_roots_digest,
            "query_scope_frozen": self.query_scope_frozen,
            "shards": [item.to_wire() for item in _canonical_sort(self.shards)],
        }
        validate_json_like(body)
        return body

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


_BENCHMARK_V2_SCHEMA = "ucm-benchmark-v2-coverage-lock/1"
_BENCHMARK_V2_ID = "UCM-BENCHMARK-v1"
_BENCHMARK_V2_REVISION = "FROZEN-v1"
_BENCHMARK_V2_PANELS = (
    *((f"W{index:02d}", "primary") for index in range(1, 15)),
    ("W15", "W15A-randomized-identifiable"),
    ("W15", "W15B-observational-nonidentified"),
    *((f"W{index:02d}", "primary") for index in range(16, 21)),
)
_BENCHMARK_V2_SPLITS = (
    EvaluationSplit.TRAIN,
    EvaluationSplit.VALIDATION,
    EvaluationSplit.TEST,
)
_BENCHMARK_V2_REPLICATE_PAIRS = tuple(
    (f"train-{index:02d}", f"eval-{index:02d}") for index in range(1, 6)
)
_BENCHMARK_V2_SHARD_COUNT = 21 * 3 * 5

# This dependency domain is part of the code-owned wire schema.  In particular,
# the generator roots are committed before expected-cell compilation and cannot
# be defined in terms of an expected-cell root, this coverage lock's digest, a
# freeze manifest, or a run bundle.  V2 intentionally carries no embedded
# ``lock_digest``: its digest is computed externally from these acyclic bytes.
_GENERATOR_RAW_PREIMAGE_PROTOCOL = "ucm-generator-raw-preimage-roots/1"
_GENERATOR_RAW_PREIMAGE_DEPENDENCIES = (
    "candidate_corpus_bytes",
    "judge_corpus_bytes",
    "materialization_receipt_bytes",
    "query_cell_preimage_bytes",
    "oracle_target_preimage_bytes",
    "raw_request_preimage_bytes",
    "raw_response_preimage_bytes",
)
_COVERAGE_SLOT_PROTOCOL = "ucm-benchmark-v2-coverage-slot/1"
_SOURCE_CUT_QUERY_SET_BINDING_PROTOCOL = (
    "ucm-source-cut-query-set-bindings/1"
)
_PAIR_THRESHOLD_BINDING_PROTOCOL = "ucm-pair-threshold-bindings/1"


def _closed_object(
    value: object, keys: frozenset[str], label: str
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ProtocolViolation(
            f"{label} must be a closed object with keys {sorted(keys)!r}"
        )
    return value


def _decode_canonical_object(payload: bytes, label: str) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation(f"{label} payload must be exact bytes")
    try:
        value = json.loads(payload.decode("utf-8"))
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ProtocolViolation(f"{label} is not UTF-8 JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be a JSON object")
    try:
        canonical = canonical_json_bytes(value)
    except (ProtocolViolation, UnicodeEncodeError) as exc:
        raise ProtocolViolation(f"{label} cannot be canonical JSON") from exc
    if canonical != payload:
        raise ProtocolViolation(f"{label} is not canonical JSON bytes")
    return value


def _v2_digest(value: object, label: str) -> str:
    result = _digest(value, label)
    if result != result.lower():
        raise ProtocolViolation(f"{label} must use lowercase hexadecimal")
    return result


def _v2_optional_digest(value: object, label: str) -> str | None:
    if value is None:
        return None
    return _v2_digest(value, label)


def _v2_split_from_wire(value: object) -> EvaluationSplit:
    if type(value) is not str:
        raise ProtocolViolation("v2 shard split must be an exact string")
    for split in _BENCHMARK_V2_SPLITS:
        if value == split.value:
            return split
    raise ProtocolViolation("v2 shard split is outside train/validation/test")


def _v2_coverage_slot_digest(
    *,
    world_slot: str,
    panel_id: str,
    split: EvaluationSplit,
    training_replicate_id: str,
    evaluation_replicate_id: str,
    cohort: EvaluationCohort,
) -> str:
    if type(split) is not EvaluationSplit or split not in _BENCHMARK_V2_SPLITS:
        raise ProtocolViolation("v2 coverage slot split is invalid")
    if type(cohort) is not EvaluationCohort:
        raise ProtocolViolation("v2 coverage slot cohort is invalid")
    return digest_json(
        {
            "protocol": _COVERAGE_SLOT_PROTOCOL,
            "world_slot": _name(world_slot, "v2 slot world_slot"),
            "panel_id": _name(panel_id, "v2 slot panel_id"),
            "split": split.value,
            "training_replicate_id": _name(
                training_replicate_id, "v2 slot training_replicate_id"
            ),
            "evaluation_replicate_id": _name(
                evaluation_replicate_id, "v2 slot evaluation_replicate_id"
            ),
            "cohort": cohort.value,
        }
    )


@dataclass(frozen=True, slots=True)
class LockedSourceDenominatorV2:
    """Exact pre-cell source denominator for one shard and one cohort."""

    coverage_slot_digest: str
    denominator_contract_digest: str
    source_count: int
    source_record_ids_root: str
    materialization_receipts_root: str

    def __post_init__(self) -> None:
        _v2_digest(self.coverage_slot_digest, "v2 denominator coverage_slot_digest")
        _v2_digest(
            self.denominator_contract_digest,
            "v2 denominator_contract_digest",
        )
        if type(self.source_count) is not int or self.source_count <= 0:
            raise ProtocolViolation("v2 source_count must be a positive integer")
        _v2_digest(self.source_record_ids_root, "v2 source_record_ids_root")
        _v2_digest(
            self.materialization_receipts_root,
            "v2 materialization_receipts_root",
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "coverage_slot_digest": self.coverage_slot_digest,
            "denominator_contract_digest": self.denominator_contract_digest,
            "source_count": self.source_count,
            "source_record_ids_root": self.source_record_ids_root,
            "materialization_receipts_root": self.materialization_receipts_root,
        }

    @classmethod
    def from_wire(cls, value: object) -> "LockedSourceDenominatorV2":
        body = _closed_object(
            value,
            frozenset(
                {
                    "coverage_slot_digest",
                    "denominator_contract_digest",
                    "source_count",
                    "source_record_ids_root",
                    "materialization_receipts_root",
                }
            ),
            "v2 source denominator",
        )
        return cls(
            coverage_slot_digest=body["coverage_slot_digest"],
            denominator_contract_digest=body["denominator_contract_digest"],
            source_count=body["source_count"],
            source_record_ids_root=body["source_record_ids_root"],
            materialization_receipts_root=body["materialization_receipts_root"],
        )


@dataclass(frozen=True, slots=True)
class LockedQuerySetV2:
    """Precommitted query sets plus exact source/cut/stage/role bindings."""

    coverage_slot_digest: str
    template_contract_digest: str
    query_set_ids: tuple[str, ...]
    template_count: int
    query_templates_root: str
    source_cut_binding_count: int
    source_cut_bindings_root: str

    def __post_init__(self) -> None:
        _v2_digest(self.coverage_slot_digest, "v2 query coverage_slot_digest")
        _v2_digest(
            self.template_contract_digest,
            "v2 template_contract_digest",
        )
        if type(self.query_set_ids) is not tuple or not self.query_set_ids:
            raise ProtocolViolation("v2 query_set_ids must be a non-empty tuple")
        if any(
            type(item) is not str or not item or item.strip() != item
            for item in self.query_set_ids
        ):
            raise ProtocolViolation("v2 query_set_ids contains a non-canonical id")
        if len(set(self.query_set_ids)) != len(self.query_set_ids):
            raise ProtocolViolation("v2 query_set_ids must be unique")
        if type(self.template_count) is not int or self.template_count <= 0:
            raise ProtocolViolation("v2 template_count must be a positive integer")
        if self.template_count < len(self.query_set_ids):
            raise ProtocolViolation(
                "v2 template_count must cover every non-empty query set"
            )
        _v2_digest(self.query_templates_root, "v2 query_templates_root")
        if (
            type(self.source_cut_binding_count) is not int
            or self.source_cut_binding_count <= 0
        ):
            raise ProtocolViolation(
                "v2 source_cut_binding_count must be a positive integer"
            )
        if self.source_cut_binding_count < len(self.query_set_ids):
            raise ProtocolViolation(
                "v2 source_cut_binding_count must reference every query set"
            )
        _v2_digest(self.source_cut_bindings_root, "v2 source_cut_bindings_root")

    def to_wire(self) -> dict[str, Any]:
        return {
            "coverage_slot_digest": self.coverage_slot_digest,
            "template_contract_digest": self.template_contract_digest,
            "query_set_ids": sorted(self.query_set_ids),
            "template_count": self.template_count,
            "query_templates_root": self.query_templates_root,
            "source_cut_binding_protocol": (
                _SOURCE_CUT_QUERY_SET_BINDING_PROTOCOL
            ),
            "source_cut_binding_count": self.source_cut_binding_count,
            "source_cut_bindings_root": self.source_cut_bindings_root,
        }

    @classmethod
    def from_wire(cls, value: object) -> "LockedQuerySetV2":
        body = _closed_object(
            value,
            frozenset(
                {
                    "coverage_slot_digest",
                    "template_contract_digest",
                    "query_set_ids",
                    "template_count",
                    "query_templates_root",
                    "source_cut_binding_protocol",
                    "source_cut_binding_count",
                    "source_cut_bindings_root",
                }
            ),
            "v2 query set",
        )
        if (
            type(body["source_cut_binding_protocol"]) is not str
            or body["source_cut_binding_protocol"]
            != _SOURCE_CUT_QUERY_SET_BINDING_PROTOCOL
        ):
            raise ProtocolViolation(
                "v2 query set source_cut_binding_protocol differs from code-owned field"
            )
        query_set_ids = body["query_set_ids"]
        if type(query_set_ids) is not list:
            raise ProtocolViolation("v2 query_set_ids must be a list")
        return cls(
            coverage_slot_digest=body["coverage_slot_digest"],
            template_contract_digest=body["template_contract_digest"],
            query_set_ids=tuple(query_set_ids),
            template_count=body["template_count"],
            query_templates_root=body["query_templates_root"],
            source_cut_binding_count=body["source_cut_binding_count"],
            source_cut_bindings_root=body["source_cut_bindings_root"],
        )


@dataclass(frozen=True, slots=True)
class LockedPairCoverageV2:
    """Exact two-endpoint pair denominator and threshold-registry references."""

    coverage_slot_digest: str
    threshold_contract_digest: str
    pair_count: int
    endpoint_count: int
    pair_endpoint_bindings_root: str
    pair_threshold_bindings_root: str
    threshold_registry_entry_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        _v2_digest(self.coverage_slot_digest, "v2 pair coverage_slot_digest")
        _v2_digest(
            self.threshold_contract_digest,
            "v2 pair threshold_contract_digest",
        )
        if type(self.pair_count) is not int or self.pair_count <= 0:
            raise ProtocolViolation("v2 pair_count must be a positive integer")
        if type(self.endpoint_count) is not int or self.endpoint_count <= 0:
            raise ProtocolViolation("v2 endpoint_count must be a positive integer")
        if self.endpoint_count != 2 * self.pair_count:
            raise ProtocolViolation("v2 endpoint_count must equal twice pair_count")
        _v2_digest(
            self.pair_endpoint_bindings_root,
            "v2 pair_endpoint_bindings_root",
        )
        _v2_digest(
            self.pair_threshold_bindings_root,
            "v2 pair_threshold_bindings_root",
        )
        if type(self.threshold_registry_entry_ids) is not tuple or not (
            self.threshold_registry_entry_ids
        ):
            raise ProtocolViolation(
                "v2 threshold_registry_entry_ids must be a non-empty tuple"
            )
        if any(
            type(item) is not str or not item or item.strip() != item
            for item in self.threshold_registry_entry_ids
        ):
            raise ProtocolViolation(
                "v2 threshold_registry_entry_ids contains a non-canonical id"
            )
        if len(set(self.threshold_registry_entry_ids)) != len(
            self.threshold_registry_entry_ids
        ):
            raise ProtocolViolation(
                "v2 threshold_registry_entry_ids must be unique"
            )
        if len(self.threshold_registry_entry_ids) > self.pair_count:
            raise ProtocolViolation(
                "v2 pair_count cannot leave threshold registry entries unused"
            )

    def to_wire(self) -> dict[str, Any]:
        return {
            "coverage_slot_digest": self.coverage_slot_digest,
            "threshold_contract_digest": self.threshold_contract_digest,
            "pair_count": self.pair_count,
            "endpoint_count": self.endpoint_count,
            "pair_endpoint_bindings_root": self.pair_endpoint_bindings_root,
            "pair_threshold_binding_protocol": _PAIR_THRESHOLD_BINDING_PROTOCOL,
            "pair_threshold_bindings_root": self.pair_threshold_bindings_root,
            "threshold_registry_entry_ids": sorted(
                self.threshold_registry_entry_ids
            ),
        }

    @classmethod
    def from_wire(cls, value: object) -> "LockedPairCoverageV2":
        body = _closed_object(
            value,
            frozenset(
                {
                    "coverage_slot_digest",
                    "threshold_contract_digest",
                    "pair_count",
                    "endpoint_count",
                    "pair_endpoint_bindings_root",
                    "pair_threshold_binding_protocol",
                    "pair_threshold_bindings_root",
                    "threshold_registry_entry_ids",
                }
            ),
            "v2 pair coverage",
        )
        if (
            type(body["pair_threshold_binding_protocol"]) is not str
            or body["pair_threshold_binding_protocol"]
            != _PAIR_THRESHOLD_BINDING_PROTOCOL
        ):
            raise ProtocolViolation(
                "v2 pair pair_threshold_binding_protocol differs from code-owned field"
            )
        entries = body["threshold_registry_entry_ids"]
        if type(entries) is not list:
            raise ProtocolViolation(
                "v2 threshold_registry_entry_ids must be a list"
            )
        return cls(
            coverage_slot_digest=body["coverage_slot_digest"],
            threshold_contract_digest=body["threshold_contract_digest"],
            pair_count=body["pair_count"],
            endpoint_count=body["endpoint_count"],
            pair_endpoint_bindings_root=body["pair_endpoint_bindings_root"],
            pair_threshold_bindings_root=body["pair_threshold_bindings_root"],
            threshold_registry_entry_ids=tuple(entries),
        )


@dataclass(frozen=True, slots=True)
class LockedShardCoverageV2:
    """Typed V2 coverage for one exact zipped train/evaluation shard."""

    world_slot: str
    panel_id: str
    split: EvaluationSplit
    training_replicate_id: str
    evaluation_replicate_id: str
    population_denominator: LockedSourceDenominatorV2 | None = None
    population_query_set: LockedQuerySetV2 | None = None
    probe_denominator: LockedSourceDenominatorV2 | None = None
    probe_query_set: LockedQuerySetV2 | None = None
    pair_coverage: LockedPairCoverageV2 | None = None

    def __post_init__(self) -> None:
        for value, label in (
            (self.world_slot, "v2 shard world_slot"),
            (self.panel_id, "v2 shard panel_id"),
            (self.training_replicate_id, "v2 shard training_replicate_id"),
            (self.evaluation_replicate_id, "v2 shard evaluation_replicate_id"),
        ):
            _name(value, label)
        if type(self.split) is not EvaluationSplit:
            raise ProtocolViolation("v2 shard split must be EvaluationSplit")
        for value, expected_type, label in (
            (
                self.population_denominator,
                LockedSourceDenominatorV2,
                "population_denominator",
            ),
            (self.population_query_set, LockedQuerySetV2, "population_query_set"),
            (
                self.probe_denominator,
                LockedSourceDenominatorV2,
                "probe_denominator",
            ),
            (self.probe_query_set, LockedQuerySetV2, "probe_query_set"),
            (self.pair_coverage, LockedPairCoverageV2, "pair_coverage"),
        ):
            if value is not None and type(value) is not expected_type:
                raise ProtocolViolation(f"v2 shard {label} has a wrong type")

    @property
    def identity(self) -> tuple[str, str, EvaluationSplit, str, str]:
        return (
            self.world_slot,
            self.panel_id,
            self.split,
            self.training_replicate_id,
            self.evaluation_replicate_id,
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "world_slot": self.world_slot,
            "panel_id": self.panel_id,
            "split": self.split.value,
            "training_replicate_id": self.training_replicate_id,
            "evaluation_replicate_id": self.evaluation_replicate_id,
            "population_denominator": None
            if self.population_denominator is None
            else self.population_denominator.to_wire(),
            "population_query_set": None
            if self.population_query_set is None
            else self.population_query_set.to_wire(),
            "probe_denominator": None
            if self.probe_denominator is None
            else self.probe_denominator.to_wire(),
            "probe_query_set": None
            if self.probe_query_set is None
            else self.probe_query_set.to_wire(),
            "pair_coverage": None
            if self.pair_coverage is None
            else self.pair_coverage.to_wire(),
        }

    @classmethod
    def from_wire(cls, value: object) -> "LockedShardCoverageV2":
        body = _closed_object(
            value,
            frozenset(
                {
                    "world_slot",
                    "panel_id",
                    "split",
                    "training_replicate_id",
                    "evaluation_replicate_id",
                    "population_denominator",
                    "population_query_set",
                    "probe_denominator",
                    "probe_query_set",
                    "pair_coverage",
                }
            ),
            "v2 shard coverage",
        )

        def optional(value: object, parser: Any) -> Any:
            return None if value is None else parser(value)

        return cls(
            world_slot=body["world_slot"],
            panel_id=body["panel_id"],
            split=_v2_split_from_wire(body["split"]),
            training_replicate_id=body["training_replicate_id"],
            evaluation_replicate_id=body["evaluation_replicate_id"],
            population_denominator=optional(
                body["population_denominator"],
                LockedSourceDenominatorV2.from_wire,
            ),
            population_query_set=optional(
                body["population_query_set"], LockedQuerySetV2.from_wire
            ),
            probe_denominator=optional(
                body["probe_denominator"], LockedSourceDenominatorV2.from_wire
            ),
            probe_query_set=optional(
                body["probe_query_set"], LockedQuerySetV2.from_wire
            ),
            pair_coverage=optional(
                body["pair_coverage"], LockedPairCoverageV2.from_wire
            ),
        )


def _v2_expected_outer_identities() -> frozenset[
    tuple[str, str, EvaluationSplit, str, str]
]:
    return frozenset(
        (world, panel, split, training, evaluation)
        for world, panel in _BENCHMARK_V2_PANELS
        for split in _BENCHMARK_V2_SPLITS
        for training, evaluation in _BENCHMARK_V2_REPLICATE_PAIRS
    )


def _v2_panel_declaration(world_slot: str, panel_id: str) -> Any:
    declaration = WORLD_REGISTRY.get(world_slot)
    if declaration is None:
        raise ProtocolViolation(f"v2 coverage has unknown world {world_slot!r}")
    matches = tuple(panel for panel in declaration.panels if panel.panel_id == panel_id)
    if len(matches) != 1:
        raise ProtocolViolation(
            f"v2 coverage has unknown/ambiguous panel {world_slot}/{panel_id}"
        )
    return matches[0]


def _v2_population_count(
    world_slot: str, panel_id: str, split: EvaluationSplit
) -> int:
    panel = _v2_panel_declaration(world_slot, panel_id)
    source_split = "sealed_test" if split is EvaluationSplit.TEST else split.value
    matches = tuple(
        count for declared_split, count in panel.split_sizes
        if declared_split.value == source_split
    )
    if len(matches) != 1:
        raise ProtocolViolation(
            f"registry does not declare one source split for {world_slot}/{panel_id}"
        )
    return matches[0]


@dataclass(frozen=True, slots=True)
class BenchmarkCoverageLockV2:
    """Independent, authority-bound V2 coverage lock scaffold.

    The constructor validates data semantics.  ``from_canonical_bytes`` is the
    authority boundary and accepts only the exact bytes pinned by this module's
    code-owned ``BENCHMARK_V2_COVERAGE_LOCK``.  Thus recomputing an external
    hash after changing denominators or prior commitments cannot self-authorize
    a replacement lock.

    ``structurally_complete`` only reports populated, cross-bound metadata.
    ``ready`` additionally requires exact equality with the code-owned bytes;
    neither is freeze authority.  This slice deliberately exposes no builder
    or manifest path and ``benchmark_freeze_eligible`` remains hard-coded false.
    """

    benchmark_id: str
    benchmark_revision: str
    registry_digest: str
    query_template_contract_digest: str | None
    source_denominator_contract_digest: str | None
    pair_threshold_contract_digest: str | None
    generator_raw_preimage_roots_digest: str | None
    shards: tuple[LockedShardCoverageV2, ...]

    def __post_init__(self) -> None:
        live_worlds = tuple(WORLD_REGISTRY)
        live_panels = tuple(
            (world, panel.panel_id)
            for world, declaration in WORLD_REGISTRY.items()
            for panel in declaration.panels
        )
        if live_worlds != tuple(f"W{index:02d}" for index in range(1, 21)):
            raise ProtocolViolation("v2 coverage requires exactly ordered W01--W20")
        if live_panels != _BENCHMARK_V2_PANELS:
            raise ProtocolViolation(
                "v2 coverage requires exactly 21 code-owned registry panels"
            )
        if self.benchmark_id != _BENCHMARK_V2_ID or type(self.benchmark_id) is not str:
            raise ProtocolViolation("v2 benchmark_id differs from code-owned id")
        if (
            self.benchmark_revision != _BENCHMARK_V2_REVISION
            or type(self.benchmark_revision) is not str
        ):
            raise ProtocolViolation(
                "v2 benchmark_revision differs from code-owned revision"
            )
        _v2_digest(self.registry_digest, "v2 registry_digest")
        if self.registry_digest != registry_digest():
            raise ProtocolViolation(
                "v2 registry_digest differs from live code-owned registry"
            )
        for value, label in (
            (
                self.query_template_contract_digest,
                "query_template_contract_digest",
            ),
            (
                self.source_denominator_contract_digest,
                "source_denominator_contract_digest",
            ),
            (
                self.pair_threshold_contract_digest,
                "pair_threshold_contract_digest",
            ),
            (
                self.generator_raw_preimage_roots_digest,
                "generator_raw_preimage_roots_digest",
            ),
        ):
            _v2_optional_digest(value, label)
        if type(self.shards) is not tuple or any(
            type(item) is not LockedShardCoverageV2 for item in self.shards
        ):
            raise ProtocolViolation(
                "v2 coverage shards must be a tuple of typed entries"
            )
        if len(self.shards) != _BENCHMARK_V2_SHARD_COUNT:
            raise ProtocolViolation("v2 coverage must contain exactly 315 shards")
        identities = [item.identity for item in self.shards]
        if len(identities) != len(set(identities)):
            raise ProtocolViolation("v2 coverage shard identities must be unique")
        expected = _v2_expected_outer_identities()
        actual = frozenset(identities)
        if actual != expected:
            missing = sorted(
                (world, panel, split.value, training, evaluation)
                for world, panel, split, training, evaluation in expected - actual
            )
            unexpected = sorted(
                (world, panel, split.value, training, evaluation)
                for world, panel, split, training, evaluation in actual - expected
            )
            raise ProtocolViolation(
                "v2 coverage outer shape mismatch; "
                f"missing={missing[:3]!r}, unexpected={unexpected[:3]!r}"
            )
        for shard in self.shards:
            population_slot = _v2_coverage_slot_digest(
                world_slot=shard.world_slot,
                panel_id=shard.panel_id,
                split=shard.split,
                training_replicate_id=shard.training_replicate_id,
                evaluation_replicate_id=shard.evaluation_replicate_id,
                cohort=EvaluationCohort.POPULATION,
            )
            probe_slot = _v2_coverage_slot_digest(
                world_slot=shard.world_slot,
                panel_id=shard.panel_id,
                split=shard.split,
                training_replicate_id=shard.training_replicate_id,
                evaluation_replicate_id=shard.evaluation_replicate_id,
                cohort=EvaluationCohort.PROBE,
            )
            for item, expected_slot, label in (
                (
                    shard.population_denominator,
                    population_slot,
                    "population_denominator",
                ),
                (
                    shard.population_query_set,
                    population_slot,
                    "population_query_set",
                ),
                (shard.probe_denominator, probe_slot, "probe_denominator"),
                (shard.probe_query_set, probe_slot, "probe_query_set"),
                (shard.pair_coverage, probe_slot, "pair_coverage"),
            ):
                if item is not None and item.coverage_slot_digest != expected_slot:
                    raise ProtocolViolation(
                        f"v2 {label} is cross-cohort or cross-shard spliced"
                    )
            for item, expected_contract, label in (
                (
                    shard.population_denominator,
                    self.source_denominator_contract_digest,
                    "population denominator",
                ),
                (
                    shard.population_query_set,
                    self.query_template_contract_digest,
                    "population query",
                ),
                (
                    shard.probe_denominator,
                    self.source_denominator_contract_digest,
                    "probe denominator",
                ),
                (
                    shard.probe_query_set,
                    self.query_template_contract_digest,
                    "probe query",
                ),
                (
                    shard.pair_coverage,
                    self.pair_threshold_contract_digest,
                    "pair threshold",
                ),
            ):
                if item is None or expected_contract is None:
                    continue
                actual_contract = (
                    item.denominator_contract_digest
                    if type(item) is LockedSourceDenominatorV2
                    else item.template_contract_digest
                    if type(item) is LockedQuerySetV2
                    else item.threshold_contract_digest
                )
                if actual_contract != expected_contract:
                    raise ProtocolViolation(
                        f"v2 {label} metadata contradicts its prior contract"
                    )
            if shard.population_denominator is not None:
                expected_count = _v2_population_count(
                    shard.world_slot, shard.panel_id, shard.split
                )
                if shard.population_denominator.source_count != expected_count:
                    raise ProtocolViolation(
                        "v2 population source_count contradicts registry: "
                        f"{shard.world_slot}/{shard.panel_id}/{shard.split.value}"
                    )

    @property
    def structurally_complete(self) -> bool:
        """Return completeness only; this is not code-owned authority."""

        if any(
            value is None
            for value in (
                self.query_template_contract_digest,
                self.source_denominator_contract_digest,
                self.pair_threshold_contract_digest,
                self.generator_raw_preimage_roots_digest,
            )
        ):
            return False
        for shard in self.shards:
            if (
                shard.population_denominator is None
                or shard.population_query_set is None
            ):
                return False
            if (
                shard.population_denominator.denominator_contract_digest
                != self.source_denominator_contract_digest
                or shard.population_query_set.template_contract_digest
                != self.query_template_contract_digest
                or shard.population_query_set.source_cut_binding_count
                < shard.population_denominator.source_count
            ):
                return False
            panel = _v2_panel_declaration(shard.world_slot, shard.panel_id)
            if panel.probes:
                if (
                    shard.probe_denominator is None
                    or shard.probe_query_set is None
                    or shard.pair_coverage is None
                ):
                    return False
                if (
                    shard.probe_denominator.denominator_contract_digest
                    != self.source_denominator_contract_digest
                    or shard.probe_query_set.template_contract_digest
                    != self.query_template_contract_digest
                    or shard.pair_coverage.threshold_contract_digest
                    != self.pair_threshold_contract_digest
                    or shard.probe_query_set.source_cut_binding_count
                    < shard.probe_denominator.source_count
                    or shard.pair_coverage.endpoint_count
                    > shard.probe_denominator.source_count
                ):
                    return False
            elif any(
                value is not None
                for value in (
                    shard.probe_denominator,
                    shard.probe_query_set,
                    shard.pair_coverage,
                )
            ):
                return False
        return True

    @property
    def ready(self) -> bool:
        if not self.structurally_complete:
            return False
        code_owned = globals().get("_BENCHMARK_V2_CODE_OWNED_CANONICAL_BYTES")
        return type(code_owned) is bytes and self.canonical_bytes == code_owned

    @property
    def benchmark_freeze_eligible(self) -> bool:
        return False

    def to_wire(self) -> dict[str, Any]:
        body = {
            "schema_version": _BENCHMARK_V2_SCHEMA,
            "status": "PRE-FREEZE",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "registry_digest": self.registry_digest,
            "query_template_contract_digest": self.query_template_contract_digest,
            "source_denominator_contract_digest": (
                self.source_denominator_contract_digest
            ),
            "pair_threshold_contract_digest": self.pair_threshold_contract_digest,
            "generator_raw_preimage_roots_digest": (
                self.generator_raw_preimage_roots_digest
            ),
            "generator_raw_preimage_protocol": _GENERATOR_RAW_PREIMAGE_PROTOCOL,
            "generator_raw_preimage_dependencies": list(
                _GENERATOR_RAW_PREIMAGE_DEPENDENCIES
            ),
            "shards": [item.to_wire() for item in _canonical_sort(self.shards)],
        }
        validate_json_like(body)
        return body

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @classmethod
    def from_canonical_bytes(cls, payload: bytes) -> "BenchmarkCoverageLockV2":
        body = _closed_object(
            _decode_canonical_object(payload, "v2 coverage lock"),
            frozenset(
                {
                    "schema_version",
                    "status",
                    "freeze_grade_evidence",
                    "benchmark_freeze_eligible",
                    "benchmark_id",
                    "benchmark_revision",
                    "registry_digest",
                    "query_template_contract_digest",
                    "source_denominator_contract_digest",
                    "pair_threshold_contract_digest",
                    "generator_raw_preimage_roots_digest",
                    "generator_raw_preimage_protocol",
                    "generator_raw_preimage_dependencies",
                    "shards",
                }
            ),
            "v2 coverage lock",
        )
        fixed: dict[str, Any] = {
            "schema_version": _BENCHMARK_V2_SCHEMA,
            "status": "PRE-FREEZE",
            "freeze_grade_evidence": False,
            "benchmark_freeze_eligible": False,
            "generator_raw_preimage_protocol": _GENERATOR_RAW_PREIMAGE_PROTOCOL,
            "generator_raw_preimage_dependencies": list(
                _GENERATOR_RAW_PREIMAGE_DEPENDENCIES
            ),
        }
        for key, expected in fixed.items():
            if type(body[key]) is not type(expected) or body[key] != expected:
                raise ProtocolViolation(f"v2 coverage code-owned field differs: {key}")
        rows = body["shards"]
        if type(rows) is not list:
            raise ProtocolViolation("v2 coverage shards must be a list")
        lock = cls(
            benchmark_id=body["benchmark_id"],
            benchmark_revision=body["benchmark_revision"],
            registry_digest=body["registry_digest"],
            query_template_contract_digest=_v2_optional_digest(
                body["query_template_contract_digest"],
                "query_template_contract_digest",
            ),
            source_denominator_contract_digest=_v2_optional_digest(
                body["source_denominator_contract_digest"],
                "source_denominator_contract_digest",
            ),
            pair_threshold_contract_digest=_v2_optional_digest(
                body["pair_threshold_contract_digest"],
                "pair_threshold_contract_digest",
            ),
            generator_raw_preimage_roots_digest=_v2_optional_digest(
                body["generator_raw_preimage_roots_digest"],
                "generator_raw_preimage_roots_digest",
            ),
            shards=tuple(LockedShardCoverageV2.from_wire(row) for row in rows),
        )
        if lock.canonical_bytes != payload:
            raise ProtocolViolation(
                "v2 coverage lock list ordering is not canonical round-trip bytes"
            )
        code_owned = globals().get("_BENCHMARK_V2_CODE_OWNED_CANONICAL_BYTES")
        if type(code_owned) is not bytes or payload != code_owned:
            raise ProtocolViolation(
                "payload is not the code-owned v2 coverage lock; caller re-signing "
                "does not establish authority"
            )
        return lock


@dataclass(frozen=True, slots=True)
class FrozenFamilyLineage:
    source_path: Path
    manifest_path: Path
    seal_path: Path
    source_digest: str
    manifest_digest: str
    seal_digest: str

    def __post_init__(self) -> None:
        _path(self.source_path, "family source_path")
        _path(self.manifest_path, "family manifest_path")
        _path(self.seal_path, "family seal_path")
        _digest(self.source_digest, "family source_digest")
        _digest(self.manifest_digest, "family manifest_digest")
        _digest(self.seal_digest, "family seal_digest")

    def to_wire(self) -> dict[str, str]:
        return {
            "source_digest": self.source_digest,
            "manifest_digest": self.manifest_digest,
            "seal_digest": self.seal_digest,
        }


@dataclass(frozen=True, slots=True)
class FrozenAuthorityRoots:
    scope_manifest_path: Path
    raw_roots_path: Path
    scope_manifest_digest: str
    raw_roots_digest: str

    def __post_init__(self) -> None:
        _path(self.scope_manifest_path, "scope_manifest_path")
        _path(self.raw_roots_path, "raw_roots_path")
        _digest(self.scope_manifest_digest, "scope_manifest_digest")
        _digest(self.raw_roots_digest, "raw_roots_digest")

    def to_wire(self) -> dict[str, str]:
        return {
            "scope_manifest_digest": self.scope_manifest_digest,
            "raw_roots_digest": self.raw_roots_digest,
        }


@dataclass(frozen=True, slots=True)
class ExpectedCellsScopeContract:
    benchmark_id: str
    benchmark_revision: str
    scope_digest: str
    registry_digest: str
    coverage_lock_digest: str
    family_lineage: FrozenFamilyLineage
    authority_roots: FrozenAuthorityRoots
    shards: tuple[FrozenCorpusShard, ...]
    queries: tuple[QueryCellContract, ...]
    pairs: tuple[PairCellContract, ...]
    w19_safety: W19SafetyContract | None = None
    forced_known_max_known: float = 0.90
    forced_known_max_unknown: float = 0.10

    def __post_init__(self) -> None:
        _name(self.benchmark_id, "benchmark_id")
        _name(self.benchmark_revision, "benchmark_revision")
        _digest(self.scope_digest, "scope_digest")
        _digest(self.registry_digest, "registry_digest")
        _digest(self.coverage_lock_digest, "coverage_lock_digest")
        if type(self.family_lineage) is not FrozenFamilyLineage:
            raise ProtocolViolation("family_lineage must be FrozenFamilyLineage")
        if type(self.authority_roots) is not FrozenAuthorityRoots:
            raise ProtocolViolation("authority_roots must be FrozenAuthorityRoots")
        if type(self.shards) is not tuple or not self.shards:
            raise ProtocolViolation("shards must be a non-empty tuple")
        if any(type(item) is not FrozenCorpusShard for item in self.shards):
            raise ProtocolViolation("shards contains a wrong type")
        shard_ids = [item.shard_id for item in self.shards]
        if len(shard_ids) != len(set(shard_ids)):
            raise ProtocolViolation("shard_ids must be unique")
        if type(self.queries) is not tuple or any(
            type(item) is not QueryCellContract for item in self.queries
        ):
            raise ProtocolViolation("queries contains a wrong type")
        query_wires = [canonical_json_bytes(item.to_wire()) for item in self.queries]
        if len(query_wires) != len(set(query_wires)):
            raise ProtocolViolation("query declarations must be exactly unique")
        query_identities = [
            (
                item.shard_id,
                item.source_record_id,
                item.cut_alias,
                item.task,
                item.horizon,
                item.policy_alias,
            )
            for item in self.queries
        ]
        if len(query_identities) != len(set(query_identities)):
            raise ProtocolViolation(
                "one executable query identity cannot carry conflicting judge labels"
            )
        if type(self.pairs) is not tuple or any(
            type(item) is not PairCellContract for item in self.pairs
        ):
            raise ProtocolViolation("pairs contains a wrong type")
        pair_wires = [canonical_json_bytes(item.to_wire()) for item in self.pairs]
        if len(pair_wires) != len(set(pair_wires)):
            raise ProtocolViolation("pair declarations must be exactly unique")
        pair_identities = [(item.shard_id, item.source_pair_id) for item in self.pairs]
        if len(pair_identities) != len(set(pair_identities)):
            raise ProtocolViolation(
                "one source pair identity cannot carry conflicting thresholds"
            )
        if self.w19_safety is not None and type(self.w19_safety) is not W19SafetyContract:
            raise ProtocolViolation("w19_safety must be W19SafetyContract")
        for value, label in (
            (self.forced_known_max_known, "forced_known_max_known"),
            (self.forced_known_max_unknown, "forced_known_max_unknown"),
        ):
            if type(value) not in {int, float} or not math.isfinite(float(value)):
                raise ProtocolViolation(f"{label} must be finite numeric")
            if not 0.0 <= float(value) <= 1.0:
                raise ProtocolViolation(f"{label} must lie in [0,1]")

    def to_wire(self) -> dict[str, Any]:
        body = {
            "schema_version": "ucm-expected-cells-contract/1",
            "benchmark_id": self.benchmark_id,
            "benchmark_revision": self.benchmark_revision,
            "scope_digest": self.scope_digest,
            "registry_digest": self.registry_digest,
            "coverage_lock_digest": self.coverage_lock_digest,
            "family_lineage": self.family_lineage.to_wire(),
            "authority_roots": self.authority_roots.to_wire(),
            "shards": [item.to_wire() for item in _canonical_sort(self.shards)],
            "queries": [item.to_wire() for item in _canonical_sort(self.queries)],
            "pairs": [item.to_wire() for item in _canonical_sort(self.pairs)],
            "w19_safety": None if self.w19_safety is None else self.w19_safety.to_wire(),
            "forced_known_max_known": float(self.forced_known_max_known),
            "forced_known_max_unknown": float(self.forced_known_max_unknown),
        }
        validate_json_like(body)
        return body

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_wire())

    @property
    def digest(self) -> str:
        return digest_json(self.to_wire())


_BENCHMARK_V1_PANELS = (
    *((f"W{index:02d}", "primary") for index in range(1, 15)),
    ("W15", "W15A-randomized-identifiable"),
    ("W15", "W15B-observational-nonidentified"),
    *((f"W{index:02d}", "primary") for index in range(16, 21)),
)


def _unfrozen_benchmark_v1_lock() -> BenchmarkCoverageLock:
    replicate_pairs = tuple(
        (f"train-{index:02d}", f"eval-{index:02d}") for index in range(1, 6)
    )
    shards = tuple(
        LockedShardCoverage(world, panel, split, train, evaluation, ())
        for world, panel in _BENCHMARK_V1_PANELS
        for split in (
            EvaluationSplit.TRAIN,
            EvaluationSplit.VALIDATION,
            EvaluationSplit.TEST,
        )
        for train, evaluation in replicate_pairs
    )
    return BenchmarkCoverageLock(
        benchmark_id="UCM-BENCHMARK-v1",
        benchmark_revision="FROZEN-v1",
        scope_digest=None,
        scope_manifest_digest=None,
        family_source_digest=None,
        family_manifest_digest=None,
        family_seal_digest=None,
        raw_roots_digest=None,
        query_scope_frozen=False,
        shards=shards,
    )


# This is intentionally an *unready* code-owned lock.  It already fixes the
# required W01--W20/W15-panel/split/TRAIN5-EVAL5 outer product, but benchmark
# freeze cannot complete until authoritative scope, family-lineage, query, and
# per-cell raw-ledger roots are generated independently and their exact digests
# replace the ``None`` values in a reviewed code change.
BENCHMARK_V1_COVERAGE_LOCK = _unfrozen_benchmark_v1_lock()


def _unfrozen_benchmark_v2_lock() -> BenchmarkCoverageLockV2:
    shards = tuple(
        LockedShardCoverageV2(
            world_slot=world,
            panel_id=panel,
            split=split,
            training_replicate_id=training,
            evaluation_replicate_id=evaluation,
        )
        for world, panel in _BENCHMARK_V2_PANELS
        for split in _BENCHMARK_V2_SPLITS
        for training, evaluation in _BENCHMARK_V2_REPLICATE_PAIRS
    )
    return BenchmarkCoverageLockV2(
        benchmark_id=_BENCHMARK_V2_ID,
        benchmark_revision=_BENCHMARK_V2_REVISION,
        registry_digest=registry_digest(),
        query_template_contract_digest=None,
        source_denominator_contract_digest=None,
        pair_threshold_contract_digest=None,
        generator_raw_preimage_roots_digest=None,
        shards=_canonical_sort(shards),
    )


# This is a new, standalone lock contract.  It is deliberately not consulted by
# the legacy expected-cell compiler and cannot publish a manifest.  A future
# reviewed change must replace the four absent prior commitments and every
# per-shard denominator before ``ready`` can become true.
BENCHMARK_V2_COVERAGE_LOCK = _unfrozen_benchmark_v2_lock()
_BENCHMARK_V2_CODE_OWNED_CANONICAL_BYTES = BENCHMARK_V2_COVERAGE_LOCK.canonical_bytes


@dataclass(frozen=True, slots=True)
class ExpectedCellsBuildResult:
    status: CellMaterializationStatus
    contract_digest: str
    manifest: EvaluationManifest | None
    blockers: tuple[CellMaterializationBlocker, ...]

    def __post_init__(self) -> None:
        if type(self.status) is not CellMaterializationStatus:
            raise ProtocolViolation("build status must be CellMaterializationStatus")
        _digest(self.contract_digest, "contract_digest")
        if self.manifest is not None and type(self.manifest) is not EvaluationManifest:
            raise ProtocolViolation("manifest has wrong type")
        if type(self.blockers) is not tuple or any(
            type(item) is not CellMaterializationBlocker for item in self.blockers
        ):
            raise ProtocolViolation("blockers contains a wrong type")
        if self.status is CellMaterializationStatus.PRE_FREEZE_SCAFFOLD:
            if self.manifest is None or self.blockers:
                raise ProtocolViolation(
                    "pre-freeze scaffold requires manifest and no blockers"
                )
        elif self.manifest is not None:
            raise ProtocolViolation("incomplete build cannot expose a manifest")

    @property
    def canonical_bytes(self) -> bytes | None:
        return None if self.manifest is None else self.manifest.canonical_bytes

    @property
    def manifest_digest(self) -> str | None:
        return None if self.manifest is None else self.manifest.digest

    @property
    def benchmark_freeze_eligible(self) -> bool:
        return False

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-expected-cells-build-result/1",
            "status": self.status.value,
            "benchmark_freeze_eligible": False,
            "contract_digest": self.contract_digest,
            "manifest_digest": self.manifest_digest,
            "blockers": [item.to_wire() for item in self.blockers],
        }


@dataclass(frozen=True, slots=True)
class RawJoinAudit:
    status: CellMaterializationStatus
    blockers: tuple[CellMaterializationBlocker, ...]

    @property
    def benchmark_freeze_eligible(self) -> bool:
        return False

    def to_wire(self) -> dict[str, Any]:
        return {
            "schema_version": "ucm-raw-exact-join-audit/1",
            "status": self.status.value,
            "benchmark_freeze_eligible": False,
            "blockers": [item.to_wire() for item in self.blockers],
        }


@dataclass(frozen=True, slots=True)
class _LoadedShard:
    evidence: FrozenCorpusShard
    candidate_rows: tuple[dict[str, Any], ...]
    judge_rows: tuple[dict[str, Any], ...]
    status: dict[str, Any]


@dataclass(frozen=True, slots=True)
class _AuthoritativeFamilyMember:
    family_digest: str
    world_slot: str
    panel_id: str
    cohort: str


def _split_label(split: EvaluationSplit) -> str:
    return "sealed_test" if split is EvaluationSplit.TEST else split.value


def _block(artifact: str, detail: str) -> CellMaterializationBlocker:
    return CellMaterializationBlocker(INCOMPLETE_CODE, artifact, detail)


def _read_canonical_object(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        return None, f"cannot read file: {type(exc).__name__}: {exc}"
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"file is not canonical JSON: {type(exc).__name__}: {exc}"
    if type(decoded) is not dict:
        return None, "JSON root must be an exact object"
    try:
        if canonical_json_bytes(decoded) != payload:
            return None, "JSON bytes are not canonical UTF-8 sorted compact JSON + LF"
    except ProtocolViolation as exc:
        return None, str(exc)
    return decoded, None


def _read_canonical_jsonl(path: Path) -> tuple[tuple[dict[str, Any], ...] | None, str | None]:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        return None, f"cannot read file: {type(exc).__name__}: {exc}"
    if not payload or not payload.endswith(b"\n"):
        return None, "JSONL must be non-empty and end with LF"
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(payload.splitlines(keepends=True), start=1):
        try:
            decoded = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            return None, f"line {line_number} is invalid JSON: {type(exc).__name__}: {exc}"
        if type(decoded) is not dict:
            return None, f"line {line_number} root must be an exact object"
        try:
            if canonical_json_bytes(decoded) != line:
                return None, f"line {line_number} is not canonical JSON"
        except ProtocolViolation as exc:
            return None, f"line {line_number}: {exc}"
        rows.append(decoded)
    return tuple(rows), None


def _load_authority_roots(
    contract: ExpectedCellsScopeContract,
    lock: BenchmarkCoverageLock,
) -> tuple[CellMaterializationBlocker, ...]:
    evidence = contract.authority_roots
    blockers: list[CellMaterializationBlocker] = []
    for path, expected, locked, label in (
        (
            evidence.scope_manifest_path,
            evidence.scope_manifest_digest,
            lock.scope_manifest_digest,
            "authoritative scope manifest",
        ),
        (
            evidence.raw_roots_path,
            evidence.raw_roots_digest,
            lock.raw_roots_digest,
            "authoritative raw roots",
        ),
    ):
        try:
            actual = digest_bytes(path.read_bytes())
        except OSError as exc:
            blockers.append(
                _block(label, f"artifact is unavailable: {type(exc).__name__}: {exc}")
            )
            continue
        if actual != expected:
            blockers.append(_block(label, "artifact digest contradicts contract"))
        if locked is None or expected != locked:
            blockers.append(_block(label, "artifact is not bound by the code-owned lock"))
        value, problem = _read_canonical_object(path)
        if problem is not None or value is None:
            blockers.append(_block(label, problem or "artifact is invalid"))
            continue
        required_schema = (
            "ucm-scope-manifest/1"
            if label == "authoritative scope manifest"
            else "ucm-expected-raw-roots/1"
        )
        if value.get("schema_version") != required_schema:
            blockers.append(_block(label, "artifact schema is not freeze-authoritative"))
        if value.get("scope_digest") != contract.scope_digest:
            blockers.append(_block(label, "artifact scope_digest contradicts contract"))
    return tuple(blockers)


def _source_family_assignments(
    source: dict[str, Any],
) -> tuple[dict[str, _AuthoritativeFamilyMember] | None, str | None]:
    if source.get("schema_version") != "ucm-pre-split-family-source/1":
        return None, "family source has unknown schema"
    families = source.get("families")
    if type(families) is not list or not families:
        return None, "family source must contain non-empty families"
    assignments: dict[str, _AuthoritativeFamilyMember] = {}
    family_keys: set[str] = set()
    for family in families:
        if type(family) is not dict or set(family) != {"family_key", "members"}:
            return None, "family source entries must use the closed family schema"
        family_key = family.get("family_key")
        if type(family_key) is not str or not family_key or family_key in family_keys:
            return None, "family source family_key must be unique"
        family_keys.add(family_key)
        members = family.get("members")
        if type(members) is not list or not members:
            return None, "family source family must have members"
        normalized: list[dict[str, str]] = []
        for member in members:
            if type(member) is not dict or set(member) != {
                "record_id",
                "world_slot",
                "panel_id",
                "cohort",
            }:
                return None, "family member uses a non-closed schema"
            record_id = member.get("record_id")
            world_slot = member.get("world_slot")
            panel_id = member.get("panel_id")
            cohort = member.get("cohort")
            if any(
                type(value) is not str or not value
                for value in (record_id, world_slot, panel_id)
            ) or cohort not in {"population", "probe"}:
                return None, "family member contains an invalid identity"
            if record_id in assignments:
                return None, "record belongs to more than one pre-split family"
            normalized.append(
                {
                    "record_id": record_id,
                    "world_slot": world_slot,
                    "panel_id": panel_id,
                    "cohort": cohort,
                }
            )
        normalized.sort(key=lambda item: canonical_json_bytes(item))
        family_digest = digest_json(
            {
                "schema_version": "ucm-pre-split-counterfactual-family/1",
                "family_key": family_key,
                "members": normalized,
            }
        )
        for member in normalized:
            assignments[member["record_id"]] = _AuthoritativeFamilyMember(
                family_digest,
                member["world_slot"],
                member["panel_id"],
                member["cohort"],
            )
    return assignments, None


def _load_family_lineage(
    contract: ExpectedCellsScopeContract,
    lock: BenchmarkCoverageLock,
) -> tuple[
    dict[str, _AuthoritativeFamilyMember] | None,
    tuple[CellMaterializationBlocker, ...],
]:
    evidence = contract.family_lineage
    blockers: list[CellMaterializationBlocker] = []
    for path, expected, locked, label in (
        (evidence.source_path, evidence.source_digest, lock.family_source_digest, "family source"),
        (
            evidence.manifest_path,
            evidence.manifest_digest,
            lock.family_manifest_digest,
            "family manifest",
        ),
        (evidence.seal_path, evidence.seal_digest, lock.family_seal_digest, "family seal"),
    ):
        try:
            actual = digest_bytes(path.read_bytes())
        except OSError as exc:
            blockers.append(
                _block(label, f"artifact is unavailable: {type(exc).__name__}: {exc}")
            )
            continue
        if actual != expected:
            blockers.append(_block(label, "artifact digest contradicts contract"))
        if locked is None or expected != locked:
            blockers.append(_block(label, "artifact is not bound by the code-owned lock"))
    if blockers:
        return None, tuple(blockers)

    source, problem = _read_canonical_object(evidence.source_path)
    if problem is not None or source is None:
        return None, (_block("family source", problem or "invalid source"),)
    if (
        source.get("benchmark_id") != contract.benchmark_id
        or source.get("benchmark_revision") != contract.benchmark_revision
        or source.get("scope_digest") != contract.scope_digest
        or source.get("registry_digest") != contract.registry_digest
        or source.get("generation_phase") != "pre_split"
    ):
        blockers.append(
            _block("family source", "source identity/phase contradicts frozen contract")
        )
    assignments, problem = _source_family_assignments(source)
    if problem is not None or assignments is None:
        blockers.append(_block("family source", problem or "invalid family grouping"))
        return None, tuple(blockers)

    expected_assignment_rows = [
        {
            "record_id": record_id,
            "family_digest": member.family_digest,
            "world_slot": member.world_slot,
            "panel_id": member.panel_id,
            "cohort": member.cohort,
        }
        for record_id, member in sorted(assignments.items())
    ]
    expected_manifest = {
        "schema_version": "ucm-pre-split-family-manifest/1",
        "benchmark_id": contract.benchmark_id,
        "benchmark_revision": contract.benchmark_revision,
        "scope_digest": contract.scope_digest,
        "source_digest": evidence.source_digest,
        "assignments": expected_assignment_rows,
    }
    manifest, problem = _read_canonical_object(evidence.manifest_path)
    if problem is not None or manifest != expected_manifest:
        blockers.append(
            _block(
                "family manifest",
                problem or "manifest is not the exact derivation of pre-split source bytes",
            )
        )
    expected_seal = {
        "schema_version": "ucm-pre-split-family-seal/1",
        "state": "PRE_SPLIT_FROZEN",
        "sequence": 0,
        "benchmark_id": contract.benchmark_id,
        "benchmark_revision": contract.benchmark_revision,
        "scope_digest": contract.scope_digest,
        "registry_digest": contract.registry_digest,
        "source_digest": evidence.source_digest,
        "manifest_digest": evidence.manifest_digest,
    }
    seal, problem = _read_canonical_object(evidence.seal_path)
    if problem is not None or seal != expected_seal:
        blockers.append(
            _block(
                "family seal",
                problem or "seal does not freeze source/manifest before split",
            )
        )
    return (assignments if not blockers else None), tuple(blockers)


def _validate_registry_binding(shard: FrozenCorpusShard) -> str | None:
    declaration = WORLD_REGISTRY.get(shard.world_slot)
    if declaration is None:
        return "world slot is absent from the frozen W01--W20 registry"
    panels = {panel.panel_id for panel in declaration.panels}
    if shard.panel_id not in panels:
        return "panel is absent from the frozen world declaration"
    return None


def _registry_population_count(shard: FrozenCorpusShard) -> int | None:
    """Return the frozen registry population count when the split is v1-native."""

    declaration = WORLD_REGISTRY.get(shard.world_slot)
    if declaration is None:
        return None
    panel = next(
        (item for item in declaration.panels if item.panel_id == shard.panel_id),
        None,
    )
    if panel is None:
        return None
    source_label = _split_label(shard.split)
    for split, count in panel.split_sizes:
        if split.value == source_label:
            return count
    # REDTEAM corpora are committed by a separate post-freeze declaration.
    return None


def _registry_identification(shard: FrozenCorpusShard) -> str | None:
    declaration = WORLD_REGISTRY.get(shard.world_slot)
    if declaration is None:
        return None
    panel = next(
        (item for item in declaration.panels if item.panel_id == shard.panel_id),
        None,
    )
    return None if panel is None else panel.identification


def _coverage_identity(
    shard: FrozenCorpusShard,
) -> tuple[str, str, EvaluationSplit, str, str]:
    return (
        shard.world_slot,
        shard.panel_id,
        shard.split,
        shard.training_replicate_id,
        shard.evaluation_replicate_id,
    )


def _audit_code_owned_coverage(
    contract: ExpectedCellsScopeContract,
) -> tuple[
    BenchmarkCoverageLock,
    dict[tuple[str, str, EvaluationSplit, str, str], LockedShardCoverage],
    tuple[CellMaterializationBlocker, ...],
]:
    lock = BENCHMARK_V1_COVERAGE_LOCK
    blockers: list[CellMaterializationBlocker] = []
    if contract.coverage_lock_digest != lock.digest:
        blockers.append(
            _block("coverage", "contract does not bind the code-owned coverage lock")
        )
    if not lock.ready:
        blockers.append(
            _block(
                "coverage",
                "benchmark-v1 scope/family/query/raw-root lock is not frozen",
            )
        )
    if (
        contract.benchmark_id != lock.benchmark_id
        or contract.benchmark_revision != lock.benchmark_revision
    ):
        blockers.append(
            _block("coverage", "benchmark identity contradicts code-owned lock")
        )
    if lock.scope_digest is None or contract.scope_digest != lock.scope_digest:
        blockers.append(
            _block("coverage", "scope_digest is not code-owned and frozen")
        )

    expected = {item.identity: item for item in lock.shards}
    actual: dict[
        tuple[str, str, EvaluationSplit, str, str], FrozenCorpusShard
    ] = {}
    for shard in contract.shards:
        identity = _coverage_identity(shard)
        if identity in actual:
            blockers.append(
                _block(shard.shard_id, "duplicate shard for one locked coverage identity")
            )
        else:
            actual[identity] = shard
    for identity in sorted(set(expected) - set(actual), key=str):
        blockers.append(_block("coverage", f"required locked shard is missing: {identity!r}"))
    for identity in sorted(set(actual) - set(expected), key=str):
        blockers.append(_block("coverage", f"unexpected shard is outside lock: {identity!r}"))
    for identity in set(expected) & set(actual):
        locked = expected[identity]
        declared_tasks = set(actual[identity].required_tasks)
        locked_tasks = {item.task for item in locked.population_queries}
        if declared_tasks != locked_tasks:
            blockers.append(
                _block(
                    actual[identity].shard_id,
                    "caller required_tasks contradict code-owned query scope",
                )
            )
    return lock, expected, tuple(blockers)


def _load_shard(
    shard: FrozenCorpusShard,
) -> tuple[_LoadedShard | None, tuple[CellMaterializationBlocker, ...]]:
    blockers: list[CellMaterializationBlocker] = []
    registry_problem = _validate_registry_binding(shard)
    if registry_problem is not None:
        blockers.append(_block(shard.shard_id, registry_problem))

    for path, expected, label in (
        (shard.candidate_path, shard.candidate_digest, "candidate corpus"),
        (shard.judge_path, shard.judge_digest, "judge corpus"),
        (shard.status_path, shard.status_digest, "materialization receipt"),
    ):
        try:
            actual = digest_bytes(path.read_bytes())
        except OSError as exc:
            blockers.append(
                _block(shard.shard_id, f"{label} is not materialized: {type(exc).__name__}: {exc}")
            )
        else:
            if actual != expected:
                blockers.append(_block(shard.shard_id, f"{label} digest mismatch"))
    if blockers:
        return None, tuple(blockers)

    status, problem = _read_canonical_object(shard.status_path)
    if problem is not None or status is None:
        return None, (_block(shard.shard_id, problem or "invalid materialization receipt"),)
    if status.get("schema_version") != "ucm-materialization-result/1":
        blockers.append(_block(shard.shard_id, "unknown materialization receipt schema"))
    if status.get("status") != "complete":
        blockers.append(_block(shard.shard_id, "corpus materialization is not complete"))
    if status.get("blockers") != []:
        blockers.append(_block(shard.shard_id, "materialization receipt contains blockers"))
    for key, expected in (
        ("world_slot", shard.world_slot),
        ("panel_id", shard.panel_id),
        ("split", _split_label(shard.split)),
        ("candidate_digest", shard.candidate_digest),
        ("judge_digest", shard.judge_digest),
    ):
        if status.get(key) != expected:
            blockers.append(_block(shard.shard_id, f"receipt {key} contradicts frozen shard"))

    candidate_rows, problem = _read_canonical_jsonl(shard.candidate_path)
    if problem is not None or candidate_rows is None:
        blockers.append(_block(shard.shard_id, problem or "invalid candidate corpus"))
    judge_rows, problem = _read_canonical_jsonl(shard.judge_path)
    if problem is not None or judge_rows is None:
        blockers.append(_block(shard.shard_id, problem or "invalid judge corpus"))
    if candidate_rows is None or judge_rows is None:
        return None, tuple(blockers)

    if len(candidate_rows) != len(judge_rows):
        blockers.append(_block(shard.shard_id, "candidate/judge row counts differ"))
    candidate_ids = [row.get("record_id") for row in candidate_rows]
    judge_ids = [row.get("record_id") for row in judge_rows]
    ids_valid = not any(
        type(item) is not str or not item for item in candidate_ids + judge_ids
    )
    if not ids_valid:
        blockers.append(_block(shard.shard_id, "corpus contains an invalid record_id"))
    elif len(set(candidate_ids)) != len(candidate_ids) or len(set(judge_ids)) != len(judge_ids):
        blockers.append(_block(shard.shard_id, "corpus record_ids are not unique"))
    if candidate_ids != judge_ids:
        blockers.append(_block(shard.shard_id, "candidate/judge row order or linkage differs"))

    population_count = 0
    probe_count = 0
    for candidate, judge in zip(candidate_rows, judge_rows):
        if candidate.get("schema_version") != "ucm-candidate-public-episode/1":
            blockers.append(_block(shard.shard_id, "candidate row has unknown schema"))
            break
        if judge.get("schema_version") != "ucm-judge-private-episode/1":
            blockers.append(_block(shard.shard_id, "judge row has unknown schema"))
            break
        for key, expected in (
            ("world_slot", shard.world_slot),
            ("panel_id", shard.panel_id),
            ("split", _split_label(shard.split)),
        ):
            if judge.get(key) != expected:
                blockers.append(_block(shard.shard_id, f"judge row {key} contradicts shard"))
                break
        if judge.get("source_episode_split") != _split_label(shard.split):
            blockers.append(
                _block(
                    shard.shard_id,
                    "source episode split provenance is absent or contradicts shard",
                )
            )
        public_history = candidate.get("public_history")
        if type(public_history) is not dict:
            blockers.append(_block(shard.shard_id, "candidate public_history is invalid"))
        elif judge.get("public_history_digest") != digest_json(public_history):
            blockers.append(
                _block(
                    shard.shard_id,
                    "candidate public_history does not match judge provenance digest",
                )
            )
        cohort = judge.get("cohort")
        if cohort == "population":
            population_count += 1
            if (
                judge.get("population_denominator") is not True
                or judge.get("probe_denominator") is not False
            ):
                blockers.append(_block(shard.shard_id, "population denominator flags are invalid"))
        elif cohort == "probe":
            probe_count += 1
            if (
                judge.get("population_denominator") is not False
                or judge.get("probe_denominator") is not True
            ):
                blockers.append(_block(shard.shard_id, "probe denominator flags are invalid"))
        else:
            blockers.append(_block(shard.shard_id, "judge row has unknown cohort"))
        case_key = judge.get("case_key")
        if type(case_key) is not str or not case_key:
            blockers.append(_block(shard.shard_id, "judge row lacks a family case_key"))
        try:
            source_family_digest = _digest(
                judge.get("family_digest"), "judge family_digest"
            )
        except ProtocolViolation:
            blockers.append(
                _block(
                    shard.shard_id,
                    "judge row lacks a valid pre-split family_digest",
                )
            )
        if type(judge.get("strata")) is not list or any(
            type(item) is not str for item in judge.get("strata", [])
        ):
            blockers.append(_block(shard.shard_id, "judge row strata are not exact strings"))
        if judge.get("identification") not in {"point", "partial", "none"}:
            blockers.append(_block(shard.shard_id, "judge row identification is invalid"))
        elif judge.get("identification") != _registry_identification(shard):
            blockers.append(
                _block(shard.shard_id, "judge row identification contradicts registry panel")
            )

    for key, actual in (
        ("population_count", population_count),
        ("probe_record_count", probe_count),
    ):
        if type(status.get(key)) is not int or status.get(key) != actual:
            blockers.append(_block(shard.shard_id, f"receipt {key} does not match exact rows"))
    registry_population = _registry_population_count(shard)
    if registry_population is not None and population_count != registry_population:
        blockers.append(
            _block(
                shard.shard_id,
                "population has "
                f"{population_count} rows but registry requires {registry_population}",
            )
        )
    if blockers:
        return None, tuple(blockers)
    return _LoadedShard(shard, candidate_rows, judge_rows, status), ()


def _family_id(
    scope_digest: str,
    shard: FrozenCorpusShard,
    family_digest: str,
) -> str:
    _digest(family_digest, "family_digest")
    value = digest_json(
        {
            "schema_version": "ucm-evaluation-family-id/1",
            "scope_digest": scope_digest,
            "world_slot": shard.world_slot,
            "panel_id": shard.panel_id,
            "split": shard.split.value,
            "evaluation_replicate_id": shard.evaluation_replicate_id,
            # Namespace the private pre-split digest; never expose it directly
            # in a candidate/run-facing expected cell.
            "source_family_digest": family_digest,
        }
    )
    return "f-" + value[7:]


def _cell_id(identity: dict[str, Any]) -> str:
    return "c-" + digest_json(
        {"schema_version": "ucm-evaluation-cell-id/1", **identity}
    )[7:]


def _episode_alias(
    scope_digest: str,
    shard: FrozenCorpusShard,
    source_record_id: str,
) -> str:
    """Namespace a corpus alias by its hidden evaluation replicate.

    World materialization aliases are opaque but may be regenerated with a
    repeated alias secret.  The expected-cell layer must not collapse equal
    source aliases from two required EVAL5 shards into one W19 episode.
    """

    return "e-" + digest_json(
        {
            "schema_version": "ucm-evaluation-episode-alias/1",
            "scope_digest": scope_digest,
            "world_slot": shard.world_slot,
            "panel_id": shard.panel_id,
            "split": shard.split.value,
            "evaluation_replicate_id": shard.evaluation_replicate_id,
            "source_record_id": source_record_id,
        }
    )[7:]


def _pair_id(identity: dict[str, Any]) -> str:
    return "p-" + digest_json(
        {"schema_version": "ucm-evaluation-pair-cell-id/1", **identity}
    )[7:]


def _identification(value: str) -> IdentificationKind:
    return {
        "point": IdentificationKind.POINT,
        "partial": IdentificationKind.PARTIAL,
        "none": IdentificationKind.NONE,
    }[value]


def build_expected_cells(contract: ExpectedCellsScopeContract) -> ExpectedCellsBuildResult:
    """Compile one exact manifest or return typed incomplete evidence.

    Duplicate query/pair declarations, including conflicting judge labels for
    one executable identity, are rejected by the scope contract rather than
    silently canonicalized into a smaller denominator.
    """

    if type(contract) is not ExpectedCellsScopeContract:
        raise ProtocolViolation("contract must be ExpectedCellsScopeContract")
    blockers: list[CellMaterializationBlocker] = []
    lock, locked_coverage, coverage_blockers = _audit_code_owned_coverage(contract)
    blockers.extend(coverage_blockers)
    if contract.registry_digest != registry_digest():
        blockers.append(_block("registry", "contract registry digest is stale or foreign"))
    blockers.extend(_load_authority_roots(contract, lock))
    family_assignments, family_blockers = _load_family_lineage(contract, lock)
    blockers.extend(family_blockers)

    loaded: dict[str, _LoadedShard] = {}
    for shard in _canonical_sort(contract.shards):
        item, item_blockers = _load_shard(shard)
        blockers.extend(item_blockers)
        if item is not None:
            loaded[shard.shard_id] = item

    # The independent pre-split source is authoritative.  Judge rows and shard
    # receipts may only join it; they cannot define or regroup a family.
    observed_record_ids: set[str] = set()
    family_splits: dict[str, set[EvaluationSplit]] = {}
    family_shards: dict[str, set[str]] = {}
    prefix_splits: dict[tuple[str, str], set[EvaluationSplit]] = {}
    prefix_shards: dict[tuple[str, str], set[str]] = {}
    for shard_id, shard in loaded.items():
        status = shard.status
        for key, expected in (
            ("pre_split_family_source_digest", contract.family_lineage.source_digest),
            ("pre_split_family_manifest_digest", contract.family_lineage.manifest_digest),
            ("pre_split_family_seal_digest", contract.family_lineage.seal_digest),
        ):
            if status.get(key) != expected:
                blockers.append(
                    _block(shard_id, f"receipt {key} does not join frozen lineage")
                )
        for row in shard.judge_rows:
            record_id = row["record_id"]
            if record_id in observed_record_ids:
                blockers.append(
                    _block(record_id, "record_id occurs in more than one corpus shard")
                )
            observed_record_ids.add(record_id)
            authority = (
                None if family_assignments is None else family_assignments.get(record_id)
            )
            if authority is None:
                blockers.append(
                    _block(record_id, "record is absent from frozen pre-split lineage")
                )
                continue
            if (
                authority.world_slot != shard.evidence.world_slot
                or authority.panel_id != shard.evidence.panel_id
                or authority.cohort != row["cohort"]
            ):
                blockers.append(
                    _block(record_id, "corpus membership contradicts frozen lineage")
                )
            if row.get("family_digest") != authority.family_digest:
                blockers.append(
                    _block(
                        record_id,
                        "judge self-reported family_digest contradicts frozen lineage",
                    )
                )
            source_family = authority.family_digest
            family_splits.setdefault(source_family, set()).add(shard.evidence.split)
            family_shards.setdefault(source_family, set()).add(shard_id)
            prefix_key = (
                shard.evidence.world_slot,
                row["public_history_digest"],
            )
            prefix_splits.setdefault(prefix_key, set()).add(shard.evidence.split)
            prefix_shards.setdefault(prefix_key, set()).add(shard_id)
    if family_assignments is not None:
        for record_id in sorted(set(family_assignments) - observed_record_ids):
            blockers.append(
                _block(record_id, "frozen pre-split member is absent from all shards")
            )
    for source_family in sorted(family_splits):
        splits = family_splits[source_family]
        if len(splits) > 1:
            blockers.append(
                _block(
                    ",".join(sorted(family_shards[source_family])),
                    "one pre-split family_digest appears in multiple splits: "
                    + ",".join(sorted(item.value for item in splits)),
                )
            )
    for prefix_key in sorted(prefix_splits):
        splits = prefix_splits[prefix_key]
        if len(splits) > 1:
            blockers.append(
                _block(
                    ",".join(sorted(prefix_shards[prefix_key])),
                    "exact public-history prefix digest appears in multiple splits: "
                    + ",".join(sorted(item.value for item in splits)),
                )
            )
    if blockers:
        return ExpectedCellsBuildResult(
            CellMaterializationStatus.INCOMPLETE,
            contract.digest,
            None,
            tuple(blockers),
        )

    cells_by_id: dict[str, ExpectedEvaluationCell] = {}
    queries_by_source: dict[
        tuple[str, str], set[tuple[str, EvaluationTask, int, str]]
    ] = {}
    for query in _canonical_sort(contract.queries):
        shard = loaded.get(query.shard_id)
        if shard is None:
            blockers.append(_block(query.shard_id, "query references an unavailable shard"))
            continue
        rows = {row["record_id"]: row for row in shard.judge_rows}
        judge = rows.get(query.source_record_id)
        if judge is None:
            blockers.append(
                _block(
                    query.shard_id,
                    f"query references absent source row {query.source_record_id}",
                )
            )
            continue
        evidence = shard.evidence
        cohort = (
            EvaluationCohort.POPULATION
            if judge["cohort"] == "population"
            else EvaluationCohort.PROBE
        )
        assert family_assignments is not None
        source_family_digest = family_assignments[
            query.source_record_id
        ].family_digest
        family_id = _family_id(
            contract.scope_digest, evidence, source_family_digest
        )
        identity = {
            "scope_digest": contract.scope_digest,
            "world_slot": evidence.world_slot,
            "panel_id": evidence.panel_id,
            "source_record_id": query.source_record_id,
            "split": evidence.split.value,
            "family_id": family_id,
            "cut_alias": query.cut_alias,
            "training_replicate_id": evidence.training_replicate_id,
            "evaluation_replicate_id": evidence.evaluation_replicate_id,
            "task": query.task.value,
            "horizon": query.horizon,
            "policy_alias": query.policy_alias,
        }
        record_id = _cell_id(identity)
        unsafe = set(query.unsafe_action_ids)
        tail_member = (
            evidence.world_slot == "W19"
            and cohort is EvaluationCohort.POPULATION
            and "boundary_tail" in judge["strata"]
        )
        if (
            tail_member
            and query.task is EvaluationTask.INTERVENTION
            and contract.w19_safety is not None
        ):
            unsafe.add(contract.w19_safety.contraindicated_action_id)
        cell = ExpectedEvaluationCell(
            record_id=record_id,
            world_slot=evidence.world_slot,
            panel_id=evidence.panel_id,
            episode_alias=_episode_alias(
                contract.scope_digest, evidence, query.source_record_id
            ),
            cohort=cohort,
            task=query.task,
            scope_digest=contract.scope_digest,
            split=evidence.split,
            family_id=family_id,
            cut_alias=query.cut_alias,
            training_replicate_id=evidence.training_replicate_id,
            evaluation_replicate_id=evidence.evaluation_replicate_id,
            horizon=query.horizon,
            policy_alias=query.policy_alias,
            tail_member=tail_member,
            ood_attribution=query.ood_attribution,
            identification=_identification(judge["identification"]),
            unsafe_action_ids=tuple(sorted(unsafe)),
        )
        previous = cells_by_id.get(record_id)
        if previous is not None and previous != cell:
            blockers.append(_block(record_id, "conflicting declarations share one cell identity"))
        else:
            cells_by_id[record_id] = cell
        queries_by_source.setdefault(
            (query.shard_id, query.source_record_id), set()
        ).add((query.cut_alias, query.task, query.horizon, query.policy_alias))

    # Query denominators are the code-owned exact cut/task/horizon/policy
    # templates crossed with every frozen source member, not caller-provided
    # ``required_tasks`` or whichever rows happened to finish.
    for shard_id, shard in loaded.items():
        locked = locked_coverage.get(_coverage_identity(shard.evidence))
        if locked is None:
            continue
        for judge in shard.judge_rows:
            templates = (
                locked.population_queries
                if judge["cohort"] == "population"
                else locked.probe_queries
            )
            expected_queries = {item.identity for item in templates}
            observed_queries = queries_by_source.get(
                (shard_id, judge["record_id"]), set()
            )
            if observed_queries != expected_queries:
                blockers.append(
                    _block(
                        shard_id,
                        "row "
                        f"{judge['record_id']} query identities contradict locked scope",
                    )
                )

    expected_pairs_by_id: dict[str, ExpectedPairCell] = {}
    pair_declarations_by_source: dict[tuple[str, str], PairCellContract] = {}
    for pair in _canonical_sort(contract.pairs):
        source_key = (pair.shard_id, pair.source_pair_id)
        previous_source = pair_declarations_by_source.get(source_key)
        if previous_source is not None and previous_source.thresholds != pair.thresholds:
            blockers.append(_block(pair.source_pair_id, "pair thresholds conflict"))
            continue
        pair_declarations_by_source[source_key] = pair

    for shard_id, shard in loaded.items():
        grouped: dict[str, list[dict[str, Any]]] = {}
        for judge in shard.judge_rows:
            if judge["cohort"] != "probe":
                continue
            source_pair_id = judge.get("pair_id")
            if type(source_pair_id) is not str or not source_pair_id:
                blockers.append(_block(shard_id, "probe row lacks source pair_id"))
                continue
            grouped.setdefault(source_pair_id, []).append(judge)
        declared_sources = {
            source
            for declared_shard, source in pair_declarations_by_source
            if declared_shard == shard_id
        }
        for source_pair_id in sorted(set(grouped) - declared_sources):
            blockers.append(_block(shard_id, f"probe pair {source_pair_id} is undeclared"))
        for source_pair_id in sorted(declared_sources - set(grouped)):
            blockers.append(_block(shard_id, f"declared pair {source_pair_id} is absent"))
        for source_pair_id in sorted(set(grouped) & declared_sources):
            rows = grouped[source_pair_id]
            sides = [row.get("pair_side") for row in rows]
            if (
                len(sides) != 2
                or any(type(side) is not int for side in sides)
                or set(sides) != {0, 1}
            ):
                blockers.append(
                    _block(shard_id, f"pair {source_pair_id} must contain exact sides 0 and 1")
                )
                continue
            declaration = pair_declarations_by_source[(shard_id, source_pair_id)]
            evidence = shard.evidence
            assert family_assignments is not None
            pair_family_digests = {
                family_assignments[row["record_id"]].family_digest for row in rows
            }
            if len(pair_family_digests) != 1:
                blockers.append(
                    _block(
                        shard_id,
                        f"pair {source_pair_id} crosses counterfactual families",
                    )
                )
                continue
            family_id = _family_id(
                contract.scope_digest,
                evidence,
                next(iter(pair_family_digests)),
            )
            identity = {
                "scope_digest": contract.scope_digest,
                "world_slot": evidence.world_slot,
                "panel_id": evidence.panel_id,
                "source_pair_id": source_pair_id,
                "split": evidence.split.value,
                "family_id": family_id,
                "training_replicate_id": evidence.training_replicate_id,
                "evaluation_replicate_id": evidence.evaluation_replicate_id,
            }
            pair_id = _pair_id(identity)
            cell = ExpectedPairCell(
                pair_id=pair_id,
                world_slot=evidence.world_slot,
                panel_id=evidence.panel_id,
                thresholds=declaration.thresholds,
                scope_digest=contract.scope_digest,
                split=evidence.split,
                family_id=family_id,
                training_replicate_id=evidence.training_replicate_id,
                evaluation_replicate_id=evidence.evaluation_replicate_id,
            )
            previous = expected_pairs_by_id.get(pair_id)
            if previous is not None and previous != cell:
                blockers.append(
                    _block(pair_id, "conflicting declarations share one pair identity")
                )
            else:
                expected_pairs_by_id[pair_id] = cell

    # A declaration for an unknown shard must not disappear merely because no
    # loaded source group happened to encounter it.
    for shard_id, source_pair_id in pair_declarations_by_source:
        if shard_id not in loaded:
            blockers.append(
                _block(
                    shard_id,
                    f"pair {source_pair_id} references unavailable shard",
                )
            )

    w19_cells = [cell for cell in cells_by_id.values() if cell.world_slot == "W19"]
    w19_declaration: W19SafetyDeclaration | None = None
    if w19_cells:
        if contract.w19_safety is None:
            blockers.append(_block("W19", "W19 cells require a frozen tail safety contract"))
        else:
            tail_population_aliases: set[str] = set()
            tail_intervention_aliases: set[str] = set()
            for cell in w19_cells:
                if cell.tail_member and cell.cohort is EvaluationCohort.POPULATION:
                    tail_population_aliases.add(cell.episode_alias)
                    if cell.task is EvaluationTask.INTERVENTION:
                        tail_intervention_aliases.add(cell.episode_alias)
            if not tail_population_aliases:
                blockers.append(_block("W19", "materialized W19 corpus has no frozen tail rows"))
            if tail_population_aliases != tail_intervention_aliases:
                blockers.append(
                    _block("W19", "not every frozen tail row has an intervention cell")
                )
            if tail_population_aliases:
                aliases = tuple(sorted(tail_population_aliases))
                w19_declaration = W19SafetyDeclaration(
                    aliases,
                    W19SafetyDeclaration.compute_digest(aliases),
                    contract.w19_safety.contraindicated_action_id,
                    float(contract.w19_safety.catastrophic_margin),
                )
    elif contract.w19_safety is not None:
        blockers.append(_block("W19", "tail safety contract exists without any W19 cells"))

    if blockers:
        return ExpectedCellsBuildResult(
            CellMaterializationStatus.INCOMPLETE,
            contract.digest,
            None,
            tuple(blockers),
        )
    cells = tuple(sorted(cells_by_id.values(), key=lambda item: item.record_id))
    pairs = tuple(sorted(expected_pairs_by_id.values(), key=lambda item: item.pair_id))
    if not cells:
        return ExpectedCellsBuildResult(
            CellMaterializationStatus.INCOMPLETE,
            contract.digest,
            None,
            (_block("expected-cells", "no expected query cells were materialized"),),
        )
    manifest = EvaluationManifest(
        scope_digest=contract.scope_digest,
        expected_cells=cells,
        expected_pairs=pairs,
        w19_safety=w19_declaration,
        forced_known_max_known=float(contract.forced_known_max_known),
        forced_known_max_unknown=float(contract.forced_known_max_unknown),
        cell_contract_digest=contract.digest,
    )
    return ExpectedCellsBuildResult(
        # Per-cell public-input/query/oracle/state-ledger roots are not yet
        # fields of ExpectedEvaluationCell.  Even with a test fixture lock,
        # this compiler is therefore a local scaffold, never freeze evidence.
        CellMaterializationStatus.PRE_FREEZE_SCAFFOLD,
        contract.digest,
        manifest,
        (),
    )


def materialize_expected_cells(
    contract: ExpectedCellsScopeContract,
    output_path: Path,
) -> ExpectedCellsBuildResult:
    """Audit/compile locally, but never publish a freeze artifact in this revision."""

    _path(output_path, "output_path")
    result = build_expected_cells(contract)
    # ExpectedEvaluationCell does not yet carry authoritative per-cell
    # public/query/oracle/state roots.  Publishing these scaffold bytes under
    # the freeze filename would turn a local structural check into false
    # evidence, so this revision intentionally has no write path.
    return result


def audit_raw_exact_join(
    manifest: EvaluationManifest,
    records: Iterable[RawEvaluationRecord],
    pair_records: Iterable[RawPairRecord],
) -> RawJoinAudit:
    """Check exact expected/raw identity and scope without computing metrics."""

    if type(manifest) is not EvaluationManifest:
        raise ProtocolViolation("manifest must be EvaluationManifest")
    rows = tuple(records)
    pairs = tuple(pair_records)
    if any(type(item) is not RawEvaluationRecord for item in rows):
        raise ProtocolViolation("records contains a wrong type")
    if any(type(item) is not RawPairRecord for item in pairs):
        raise ProtocolViolation("pair_records contains a wrong type")
    blockers: list[CellMaterializationBlocker] = []

    expected = {item.record_id: item for item in manifest.expected_cells}
    actual: dict[str, RawEvaluationRecord] = {}
    duplicates: set[str] = set()
    for row in rows:
        if row.record_id in actual:
            duplicates.add(row.record_id)
        else:
            actual[row.record_id] = row
    for record_id in sorted(duplicates):
        blockers.append(_block(record_id, "duplicate raw result row"))
    for record_id in sorted(set(expected) - set(actual)):
        blockers.append(_block(record_id, "required raw result row is missing"))
    for record_id in sorted(set(actual) - set(expected)):
        blockers.append(_block(record_id, "unexpected raw result row is outside expected-cells"))
    for record_id in sorted(set(expected) & set(actual)):
        cell = expected[record_id]
        row = actual[record_id]
        if (
            row.world_slot != cell.world_slot
            or row.panel_id != cell.panel_id
            or row.episode_alias != cell.episode_alias
            or row.cohort is not cell.cohort
            or row.task is not cell.task
            or row.scope_digest != cell.scope_digest
            or row.scope_digest != manifest.scope_digest
            or row.split is not cell.split
            or row.family_id != cell.family_id
            or row.cut_alias != cell.cut_alias
            or row.training_replicate_id != cell.training_replicate_id
            or row.evaluation_replicate_id != cell.evaluation_replicate_id
            or row.horizon != cell.horizon
            or row.policy_alias != cell.policy_alias
        ):
            blockers.append(_block(record_id, "raw result identity/scope does not exact-join"))
        expected_weight = 1.0 if cell.cohort is EvaluationCohort.POPULATION else 0.0
        if float(row.analysis_weight) != expected_weight:
            blockers.append(_block(record_id, "raw result denominator weight is invalid"))
        if digest_json(row.candidate_output) != row.candidate_output_digest:
            blockers.append(_block(record_id, "candidate output digest mismatch"))
        if digest_json(row.oracle_record) != row.oracle_record_digest:
            blockers.append(_block(record_id, "oracle record digest mismatch"))

    expected_pairs = {item.pair_id: item for item in manifest.expected_pairs}
    if expected_pairs:
        blockers.append(
            _block(
                "raw-pairs",
                "ExpectedPairCell does not yet bind frozen endpoint record IDs "
                "and per-side public/query/oracle/state roots",
            )
        )
    actual_pairs: dict[str, RawPairRecord] = {}
    duplicate_pairs: set[str] = set()
    for row in pairs:
        if row.pair_id in actual_pairs:
            duplicate_pairs.add(row.pair_id)
        else:
            actual_pairs[row.pair_id] = row
    for pair_id in sorted(duplicate_pairs):
        blockers.append(_block(pair_id, "duplicate raw pair row"))
    for pair_id in sorted(set(expected_pairs) - set(actual_pairs)):
        blockers.append(_block(pair_id, "required raw pair row is missing"))
    for pair_id in sorted(set(actual_pairs) - set(expected_pairs)):
        blockers.append(_block(pair_id, "unexpected raw pair row is outside expected-cells"))
    for pair_id in sorted(set(expected_pairs) & set(actual_pairs)):
        cell = expected_pairs[pair_id]
        row = actual_pairs[pair_id]
        if (
            row.world_slot != cell.world_slot
            or row.panel_id != cell.panel_id
            or row.scope_digest != cell.scope_digest
            or row.scope_digest != manifest.scope_digest
            or row.split is not cell.split
            or row.family_id != cell.family_id
            or row.training_replicate_id != cell.training_replicate_id
            or row.evaluation_replicate_id != cell.evaluation_replicate_id
        ):
            blockers.append(_block(pair_id, "raw pair identity/scope does not exact-join"))
        if float(row.analysis_weight) != 0.0:
            blockers.append(_block(pair_id, "raw pair entered a population denominator"))
        if digest_json(row.candidate_record) != row.candidate_record_digest:
            blockers.append(_block(pair_id, "pair candidate record digest mismatch"))
        if digest_json(row.oracle_record) != row.oracle_record_digest:
            blockers.append(_block(pair_id, "pair oracle record digest mismatch"))

    return RawJoinAudit(
        CellMaterializationStatus.INCOMPLETE
        if blockers
        else CellMaterializationStatus.PRE_FREEZE_SCAFFOLD,
        tuple(blockers),
    )


__all__ = [
    "BENCHMARK_V1_COVERAGE_LOCK",
    "BENCHMARK_V2_COVERAGE_LOCK",
    "BenchmarkCoverageLock",
    "BenchmarkCoverageLockV2",
    "CellMaterializationBlocker",
    "CellMaterializationStatus",
    "ExpectedCellsBuildResult",
    "ExpectedCellsScopeContract",
    "FrozenAuthorityRoots",
    "FrozenCorpusShard",
    "FrozenFamilyLineage",
    "LockedQueryTemplate",
    "LockedQuerySetV2",
    "LockedPairCoverageV2",
    "LockedShardCoverage",
    "LockedShardCoverageV2",
    "LockedSourceDenominatorV2",
    "PairCellContract",
    "QueryCellContract",
    "RawJoinAudit",
    "W19SafetyContract",
    "audit_raw_exact_join",
    "build_expected_cells",
    "materialize_expected_cells",
]
