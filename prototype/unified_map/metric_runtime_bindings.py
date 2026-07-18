"""Code-owned PRE-FREEZE inventory of executable metric primitives.

This module answers one deliberately narrow question: which objects in the
111-output metric *target* registry currently have a real callable and a typed
selector that can be exercised on a known-answer input?  It does not close a
metric definition, bind a panel/task/cell, define an aggregate, or grant
evaluator/freeze authority.

Every target also declares its required, implemented, and missing formula
branches.  Conditional or compound targets count as formula-executable only
when all required branches have code-owned callable/selector known answers;
otherwise the implemented slice remains explicit partial coverage.

The inventory is derived from actual callable objects held in a code-owned
mapping.  Caller-supplied module/function names are never accepted.  Every
parse freshly re-hashes the exact source closure and re-runs the known-answer
invocations before accepting the canonical artifact.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable

import numpy as np

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    validate_json_like,
)
from .metric_configuration import (
    benchmark_v1_metric_target_registry,
    metric_target_artifact_digest_from_bytes,
    metric_target_digest_from_bytes,
    parse_metric_target_registry_bytes,
)
from .metrics_diagnosis_forecast import (
    DiagnosisMetricReport,
    EnergyScoreReport,
    EventMetricReport,
    IntervalInput,
    OraclePosteriorDiagnosisMetricReport,
    ContinuousForecastReport,
    diagnosis_metrics_m01,
    discrete_event_metrics_m02,
    ensemble_continuous_metrics_m02,
    joint_energy_score_m02,
    oracle_posterior_diagnosis_metrics_m01,
)
from .metrics_intervention_regret import (
    CoverageDisposition,
    EffectIdentification,
    GaussianTrajectoryCase,
    IdentifiedSetCase,
    IdentifiedSetMetrics,
    Interval,
    InterventionTrajectoryMetrics,
    PartialIdentificationCase,
    PartialIdentificationMetrics,
    PointRegretMetrics,
    PolicyHorizonCoverageMetrics,
    PolicyHorizonExposure,
    RegretCase,
    SetClaimKind,
    TreatmentEffectCase,
    TreatmentEffectMetrics,
    identified_set_metrics,
    intervention_trajectory_metrics,
    partial_identification_regret,
    point_identified_regret,
    policy_horizon_coverage,
    treatment_effect_metrics,
)
from .metrics_m09_m11 import (
    M09_POINT_SCHEMA,
    M10_PAIR_SCHEMA,
    M11_OBSERVATION_SCHEMA,
    TRAIN_FRACTION_PERCENTS,
    CanonicalMetricEvidence,
    CombinationGeneralizationResult,
    ExtensionCostObservation,
    ExtensionCostResult,
    HeldoutMatchedPair,
    LearningCurvePoint,
    SampleEfficiencyResult,
    combination_generalization,
    extension_cost,
    sample_efficiency,
)
from .metrics_state_resource_stability import (
    M12_ROW_SCHEMA,
    M13_MEASUREMENT_SCHEMA,
    M13_PROVENANCE_SCHEMA,
    CandidateOperation,
    CanonicalEvidence as StateResourceEvidence,
    CollectorProvenance,
    FiveSeedStabilityResult,
    MetricDirection,
    ReplicateSeries,
    ResourceKind,
    ResourceMeasurement,
    ResourceResult,
    StateSizeResult,
    StateSizeRow,
    five_seed_stability,
    resource_metrics,
    state_size_metrics,
)
from .metrics_update_transfer import (
    EvaluationGrain,
    InformationKind,
    NovelReadoutCard,
    NovelReadoutEvaluation,
    NovelReadoutScorePoint,
    NovelReadoutTransferResult,
    NoveltyRelation,
    OracleScoreChangeObservation,
    OriginalYMembershipBasis,
    QueryOrderObservation,
    ReadoutInput,
    ReadoutKind,
    RuntimeStateIdentity,
    ScoreDirection,
    Task,
    UpdateConsistencyResult,
    UpdateIdentityObservation,
    sealed_state_novel_readout_transfer,
    update_consistency,
)
from .pre_freeze_metrics_m05_m08 import (
    CollisionMetricReport,
    FalseSplitMetricReport,
    OODExample,
    OODMetricReport,
    PairMetricProbe,
    PairThresholds,
    TemporalLeakMetricReport,
    TemporalLeakProbe,
    collision_metrics,
    false_split_metrics,
    ood_metrics,
    temporal_leakage_metrics,
)
from .seed_protocol import ZIPPED_REPLICATE_IDS
from .state import StateClass, StatePayload, seal_state


SCHEMA_VERSION = "ucm-pre-freeze-metric-runtime-bindings/2"
BENCHMARK_ID = "UCM-BENCHMARK-v1"
BENCHMARK_STATUS = "PRE-FREEZE"
AUTHORITY_CLAIM = "formula_runtime_coverage_inventory_only"
EVALUATOR_BINDING = "not_bound"
FREEZE_AUTHORITY = "not_claimed"
AGGREGATE_SCORE = "forbidden"
TARGET_OBJECT_DOMAIN = b"UCM_METRIC_TARGET_OBJECT_V1\0"
SOURCE_CLOSURE_DOMAIN = b"UCM_METRIC_RUNTIME_SOURCE_CLOSURE_V1\0"
BINDING_SET_DOMAIN = b"UCM_METRIC_RUNTIME_BINDING_SET_V1\0"
ARTIFACT_DOMAIN = b"UCM_METRIC_RUNTIME_BINDING_ARTIFACT_V1\0"

_ALWAYS_REMAINING_BLOCKERS = (
    "UCM-METRIC-B002",
    "UCM-METRIC-B003",
    "UCM-METRIC-B004",
    "UCM-METRIC-B007",
)
_REMAINING_GLOBAL_GAPS = (
    "formal_panel_task_applicability",
    "frozen_world_metric_parameters",
    "closed_denominator_and_exposure_registry",
    "closed_aggregation_hierarchy",
    "authorized_evaluator_runtime_binding",
    "fresh_process_import_attestation",
)
_SOURCE_PATHS = (
    "prototype/unified_map/canonical.py",
    "prototype/unified_map/metric_configuration.py",
    "prototype/unified_map/metric_runtime_bindings.py",
    "prototype/unified_map/metrics_diagnosis_forecast.py",
    "prototype/unified_map/metrics_intervention_regret.py",
    "prototype/unified_map/metrics_m09_m11.py",
    "prototype/unified_map/metrics_state_resource_stability.py",
    "prototype/unified_map/metrics_update_transfer.py",
    "prototype/unified_map/pre_freeze_metrics_m05_m08.py",
    "prototype/unified_map/seed_protocol.py",
    "prototype/unified_map/state.py",
)


class RuntimeBindingStatus(str, Enum):
    FORMULA_EXECUTABLE_UNBOUND = "formula_executable_unbound"
    PARTIAL_FORMULA_COVERAGE_UNBOUND = "partial_formula_coverage_unbound"
    PARTIAL_UNTRUSTED_COLLECTOR = "partial_untrusted_collector"
    UNIMPLEMENTED = "unimplemented"


class FormulaImplementationKey(str, Enum):
    M01_DIAGNOSIS = "m01_diagnosis"
    M01_ORACLE_POSTERIOR = "m01_oracle_posterior"
    M02_CONTINUOUS = "m02_continuous"
    M02_EVENT = "m02_event"
    M02_ENERGY = "m02_energy"
    M03_TRAJECTORY = "m03_trajectory"
    M03_EFFECT = "m03_effect"
    M03_COVERAGE = "m03_coverage"
    M03_IDENTIFIED_SET = "m03_identified_set"
    M04_POINT_REGRET = "m04_point_regret"
    M04_PARTIAL_REGRET = "m04_partial_regret"
    M05_COLLISION = "m05_collision"
    M06_FALSE_SPLIT = "m06_false_split"
    M07_OOD = "m07_ood"
    M08_TEMPORAL_LEAK = "m08_temporal_leak"
    M09_SAMPLE_EFFICIENCY = "m09_sample_efficiency"
    M10_GENERALIZATION = "m10_generalization"
    M11_EXTENSION_COST = "m11_extension_cost"
    M12_STATE_SIZE = "m12_state_size"
    M13_RESOURCE = "m13_resource"
    M14_STABILITY = "m14_stability"
    M15_UPDATE_CONSISTENCY = "m15_update_consistency"
    M16_NOVEL_READOUT = "m16_novel_readout"


@dataclass(frozen=True, slots=True)
class FormulaAdapter:
    function: Callable[..., object]
    invoke_known_answer: Callable[[], object]
    expected_result_type: type[object]
    source_path: str
    input_type_contract: str
    known_answer_parameter_preimage: dict[str, Any]
    formula_family: str


@dataclass(frozen=True, slots=True)
class FormulaBranchBindingSpec:
    branch_id: str
    satisfies_target_branches: tuple[str, ...]
    implementation_key: FormulaImplementationKey
    selector_key: str
    selector: Callable[[object], object]
    denominator_contract: str
    tie_policy: str
    undefined_disposition: str


@dataclass(frozen=True, slots=True)
class TargetBindingSpec:
    branches: tuple[FormulaBranchBindingSpec, ...]


@dataclass(frozen=True, slots=True)
class FrozenFormulaAdapter:
    function: Callable[..., object]
    invoke_known_answer: Callable[[], object]
    expected_result_type: type[object]
    source_path: str
    input_type_contract: str
    known_answer_parameter_preimage_bytes: bytes
    formula_family: str


@dataclass(frozen=True, slots=True)
class CodeOwnedBindingManifest:
    adapters: Mapping[FormulaImplementationKey, FrozenFormulaAdapter]
    target_bindings: Mapping[tuple[str, int], TargetBindingSpec]
    required_branches: Mapping[tuple[str, int], tuple[str, ...]]
    untrusted_targets: frozenset[tuple[str, int]]


@dataclass(frozen=True, slots=True)
class CodeOwnedControlPlane:
    manifest: CodeOwnedBindingManifest
    source_paths: tuple[str, ...]
    always_remaining_blockers: tuple[str, ...]
    remaining_global_gaps: tuple[str, ...]
    imported_source_digests: Mapping[str, str]
    schema_version: str
    benchmark_id: str
    benchmark_status: str
    authority_claim: str
    evaluator_binding: str
    freeze_authority: str
    aggregate_score: str
    target_object_domain: bytes
    source_closure_domain: bytes
    binding_set_domain: bytes
    artifact_domain: bytes


def _intervals(shape: tuple[int, int]) -> tuple[IntervalInput, ...]:
    zeros = np.zeros(shape, dtype=np.float64)
    ones = np.ones(shape, dtype=np.float64)
    return tuple(
        IntervalInput(level, zeros.copy(), ones.copy()) for level in (0.50, 0.80, 0.95)
    )


def _invoke_m01() -> DiagnosisMetricReport:
    return diagnosis_metrics_m01(
        np.array(((0.8, 0.2), (0.3, 0.7))),
        np.array((0, 1)),
        top_k=(2,),
        probability_intervals=_intervals((2, 2)),
    )


def _invoke_m01_oracle_posterior() -> OraclePosteriorDiagnosisMetricReport:
    return oracle_posterior_diagnosis_metrics_m01(
        np.array(((0.8, 0.2), (0.3, 0.7))),
        np.array(((0.75, 0.25), (0.2, 0.8))),
    )


def _invoke_m02_continuous() -> ContinuousForecastReport:
    samples = np.array((((0.0, 1.0), (1.0, 2.0)), ((2.0, 1.0), (3.0, 0.0))))
    truth = np.array(((0.5, 1.5), (2.5, 0.5)))
    return ensemble_continuous_metrics_m02(
        samples,
        truth,
        np.array((1.0, 2.0)),
        intervals=_intervals((2, 2)),
    )


def _invoke_m02_event() -> EventMetricReport:
    return discrete_event_metrics_m02(
        np.array(((0.8, 0.2), (0.4, 0.9))), np.array(((1, 0), (0, 1)))
    )


def _invoke_m02_energy() -> EnergyScoreReport:
    return joint_energy_score_m02(
        np.array((((0.0, 1.0), (1.0, 2.0)), ((2.0, 1.0), (3.0, 0.0)))),
        np.array(((0.5, 1.5), (2.5, 0.5))),
        np.array((1.0, 2.0)),
    )


def _invoke_m03_trajectory() -> InterventionTrajectoryMetrics:
    return intervention_trajectory_metrics(
        (GaussianTrajectoryCase("case", "A1", "H1", (1.0,), (1.0,), (0.0,), (2.0,)),)
    )


def _invoke_m03_effect() -> TreatmentEffectMetrics:
    return treatment_effect_metrics(
        (
            TreatmentEffectCase("unit", 1.0, -1.0, EffectIdentification.UNIT),
            TreatmentEffectCase(
                "distribution", 0.5, 0.25, EffectIdentification.DISTRIBUTION
            ),
        ),
        effect_sign_tolerance=0.0,
    )


def _invoke_m03_coverage() -> PolicyHorizonCoverageMetrics:
    return policy_horizon_coverage(
        (
            PolicyHorizonExposure(
                "r1", "W01", "c1", "cut", "A0", "H1", CoverageDisposition.POINT_SCORED
            ),
            PolicyHorizonExposure(
                "r2",
                "W01",
                "c1",
                "cut",
                "A1",
                "H1",
                CoverageDisposition.TYPED_ABSTENTION,
            ),
        )
    )


def _invoke_m03_identified() -> IdentifiedSetMetrics:
    return identified_set_metrics(
        (
            IdentifiedSetCase(
                "set",
                Interval(-1.0, 1.0),
                SetClaimKind.IDENTIFIED_SET,
                Interval(-1.5, 1.25),
                ("A0", "A1"),
                ("A0", "A1"),
            ),
            IdentifiedSetCase(
                "point",
                Interval(-1.0, 1.0),
                SetClaimKind.POINT,
                Interval(0.2, 0.2),
                ("A0", "A1"),
                ("A1",),
            ),
        ),
        tolerance=0.0,
    )


def _invoke_m04_point() -> PointRegretMetrics:
    return point_identified_regret(
        (
            RegretCase(
                "regular",
                "W01",
                ("A", "B"),
                (0.0, 1.0),
                (2.0, 0.0),
                ("A", "B"),
                0.0,
                1.0,
                ("B",),
            ),
            RegretCase(
                "tail",
                "W19",
                ("A", "B"),
                (1.0, 0.0),
                (0.0, 2.0),
                ("A", "B"),
                0.0,
                1.0,
                ("A",),
                True,
            ),
        )
    )


def _invoke_m04_partial() -> PartialIdentificationMetrics:
    return partial_identification_regret(
        (
            PartialIdentificationCase(
                "partial",
                "W19",
                ("A", "B"),
                (Interval(0.0, 1.0), Interval(0.0, 0.5)),
                ((1.0, 0.0), (0.0, 1.0)),
                ("A", "B"),
                0.0,
                0.5,
                ("A",),
                SetClaimKind.HIGH_CONFIDENCE_INTERVAL,
                (0.0, 1.0),
                True,
            ),
        )
    )


def _thresholds() -> PairThresholds:
    return PairThresholds(0.1, 0.5, 0.1, 0.5, 1.0)


def _pair_rows() -> tuple[PairMetricProbe, ...]:
    return (
        PairMetricProbe("collision", "all", 1.0, True, 0.05, 0.8, True, 1.2),
        PairMetricProbe("split", "all", 1.0, False, 0.8, 0.05, False, 0.0),
    )


def _invoke_m05() -> CollisionMetricReport:
    return collision_metrics(_pair_rows(), _thresholds())


def _invoke_m06() -> FalseSplitMetricReport:
    return false_split_metrics(_pair_rows(), _thresholds())


def _invoke_m07() -> OODMetricReport:
    return ood_metrics(
        (
            OODExample("known", "all", 1.0, False, 0.1, False, 0.0, 0.0),
            OODExample("ood", "all", 1.0, True, 0.9, False, 1.0, 2.0),
        ),
        frozen_low_fpr=0.05,
        catastrophic_margin=1.0,
    )


def _invoke_m08() -> TemporalLeakMetricReport:
    return temporal_leakage_metrics(
        (
            TemporalLeakProbe(
                "probe",
                "all",
                1.0,
                b"same",
                b"same",
                "s1",
                "s2",
                b"p1",
                b"p2",
                0.5,
                False,
                True,
                "old",
                "new",
                b"before",
                b"after",
            ),
        )
    )


def _evidence(path: str, payload: dict[str, Any]) -> CanonicalMetricEvidence:
    return CanonicalMetricEvidence.from_payload(path, payload)


def _invoke_m09() -> SampleEfficiencyResult:
    counts = (10, 50, 100, 250, 500, 1000)
    points = tuple(
        LearningCurvePoint(
            _evidence(
                f"known/m09/{task}-{fraction}.json",
                {
                    "schema_version": M09_POINT_SCHEMA,
                    "task": task,
                    "train_fraction_percent": fraction,
                    "train_examples": count,
                    "proper_score": float(7 - index),
                },
            )
        )
        for task in ("diagnosis", "natural_forecast", "intervention")
        for index, (fraction, count) in enumerate(
            zip(TRAIN_FRACTION_PERCENTS, counts, strict=True), 1
        )
    )
    return sample_efficiency(points)


def _invoke_m10() -> CombinationGeneralizationResult:
    pairs = tuple(
        HeldoutMatchedPair(
            _evidence(
                f"known/m10/{stratum}.json",
                {
                    "schema_version": M10_PAIR_SCHEMA,
                    "stratum": stratum,
                    "pair_id": "p1",
                    "heldout_case_id": f"heldout-{stratum}",
                    "matched_seen_case_id": f"seen-{stratum}",
                    "score_direction": "minimize",
                    "heldout_score": 2.0,
                    "matched_seen_score": 1.0,
                },
            )
        )
        for stratum in (
            "heldout_mechanism_combination",
            "heldout_host_modifier",
            "heldout_nonlinear_comorbidity",
        )
    )
    return combination_generalization(pairs)


def _invoke_m11() -> ExtensionCostResult:
    first_payload = {
        "schema_version": M11_OBSERVATION_SCHEMA,
        "extension_id": "known-extension-a",
        "extension_kind": "new_check",
        "model_migration_required": True,
        "state_migration_required": False,
        "schema_migration_required": True,
        "retrain_examples": 20,
        "base_artifact_size_bytes": 100,
        "extended_artifact_size_bytes": 140,
        "core_diff_files": [
            {"path": "core/a.py", "added_lines": 4, "deleted_lines": 1}
        ],
        "old_benchmark_before_score": 1.0,
        "old_benchmark_after_score": 1.3,
        "old_benchmark_score_direction": "minimize",
        "old_benchmark_denominator": 50,
        "completion_disposition": "completed",
    }
    second_payload = {
        **first_payload,
        "extension_id": "known-extension-z",
        "extension_kind": "new_treatment",
        "model_migration_required": False,
        "state_migration_required": True,
        "schema_migration_required": False,
        "retrain_examples": 35,
        "extended_artifact_size_bytes": 175,
        "core_diff_files": [
            {"path": "core/b.py", "added_lines": 7, "deleted_lines": 2},
            {"path": "core/c.py", "added_lines": 1, "deleted_lines": 0},
        ],
        "old_benchmark_after_score": 0.9,
    }
    return extension_cost(
        (
            ExtensionCostObservation(
                _evidence("known/m11/extension-z.json", second_payload)
            ),
            ExtensionCostObservation(
                _evidence("known/m11/extension-a.json", first_payload)
            ),
        )
    )


def _fixture_digest(label: str) -> str:
    return digest_bytes(label.encode("utf-8"))


def _invoke_m12() -> StateSizeResult:
    rows = tuple(
        StateSizeRow(
            StateResourceEvidence.from_payload(
                f"known/m12/row-{index:02d}.json",
                {
                    "schema_version": M12_ROW_SCHEMA,
                    "record_id": f"record-{index:02d}",
                    "candidate_id": "known-candidate",
                    "scope_digest": _fixture_digest("m12-scope"),
                    "candidate_artifact_digest": _fixture_digest(
                        "m12-candidate-artifact"
                    ),
                    "training_replicate_id": "train-01",
                    "evaluation_replicate_id": "eval-01",
                    "world_slot": "W01",
                    "panel_id": "primary",
                    "family_id": "known-family",
                    "stratum_id": "known-stratum",
                    "task": "diagnosis",
                    "episode_id": f"episode-{index:02d}",
                    "cut_id": "cut-01",
                    "expected_cell_id": f"cell-{index:02d}",
                    "history_slope_grain_id": "known-matched-grain",
                    "horizon": 1,
                    "policy_id": "no-op",
                    "history_length": index,
                    "canonical_state": {
                        "history": "x" * index,
                        "value": index,
                    },
                    "scalar_count": index,
                    "node_count": 1,
                    "edge_count": 0,
                    "particle_count": 0,
                },
            )
        )
        for index in (1, 2, 3)
    )
    return state_size_metrics(rows)


def _invoke_m13() -> ResourceResult:
    provenance = CollectorProvenance(
        StateResourceEvidence.from_payload(
            "known/m13/provenance.json",
            {
                "schema_version": M13_PROVENANCE_SCHEMA,
                "collector_id": "known-resource-collector",
                "collector_version": "1",
                "run_id": "known-run",
                "candidate_id": "known-candidate",
                "scope_digest": _fixture_digest("m13-scope"),
                "collector_source_digest": _fixture_digest("m13-collector-source"),
                "collector_config_digest": _fixture_digest("m13-collector-config"),
                "environment_digest": _fixture_digest("m13-environment"),
                "clock_source": "perf_counter_ns",
                "memory_source": "wait4_maxrss_and_gpu_api",
                "started_at_utc": "2026-07-18T00:00:00Z",
                "finished_at_utc": "2026-07-18T00:01:00Z",
                "cold_process_per_sample": True,
            },
        )
    )
    units = {
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

    def measurement(
        measurement_id: str,
        kind: ResourceKind,
        value: int | float,
        operation: CandidateOperation | None = None,
    ) -> ResourceMeasurement:
        return ResourceMeasurement(
            StateResourceEvidence.from_payload(
                f"known/m13/{measurement_id}.json",
                {
                    "schema_version": M13_MEASUREMENT_SCHEMA,
                    "measurement_id": measurement_id,
                    "run_id": provenance.run_id,
                    "candidate_id": provenance.candidate_id,
                    "scope_digest": provenance.scope_digest,
                    "resource_kind": kind.value,
                    "operation": None if operation is None else operation.value,
                    "value": value,
                    "unit": units[kind],
                    "undefined_reason": None,
                    "collector_provenance_digest": provenance.evidence.artifact_digest,
                },
            ),
            provenance,
        )

    latency = tuple(
        measurement(
            f"latency-{operation.value}",
            ResourceKind.COLD_LATENCY,
            1_000 + index,
            operation,
        )
        for index, operation in enumerate(CandidateOperation, 1)
    )
    resources = (
        measurement("peak-rss", ResourceKind.PEAK_RSS, 100_000),
        measurement("peak-gpu", ResourceKind.PEAK_GPU_MEMORY, 50_000),
        measurement("artifact", ResourceKind.MODEL_ARTIFACT_BYTES, 10_000),
        measurement("train-wall", ResourceKind.TRAIN_WALL_TIME, 3.5),
        measurement("train-flops", ResourceKind.TRAIN_FLOPS, 1_000_000),
        measurement("worker-wall", ResourceKind.POSTSEAL_WORKER_WALL_TIME, 0.5),
        measurement("worker-rss", ResourceKind.POSTSEAL_WORKER_PEAK_RSS, 25_000),
        measurement("worker-gpu", ResourceKind.POSTSEAL_WORKER_PEAK_GPU_MEMORY, 12_500),
    )
    return resource_metrics(latency + resources)


def _invoke_m14() -> FiveSeedStabilityResult:
    return five_seed_stability(
        metric_name="known-proper-score",
        unit="score",
        direction=MetricDirection.MINIMIZE,
        candidate=ReplicateSeries(ZIPPED_REPLICATE_IDS, (1.0, 2.0, 3.0, 4.0, 5.0)),
        baseline=ReplicateSeries(ZIPPED_REPLICATE_IDS, (0.5, 1.5, 2.5, 3.5, 4.5)),
    )


def _m15_runtime_state() -> RuntimeStateIdentity:
    payload = StatePayload.from_json(
        {"known": "state"},
        schema_version="ucm-m15-known-answer-state/1",
        state_class=StateClass.DYNAMIC_SHARED,
    )
    return RuntimeStateIdentity.from_sealed_state(
        seal_state(
            payload,
            candidate_bundle_digest=_fixture_digest("m15-candidate-bundle"),
            model_digest=_fixture_digest("m15-model"),
            scope_digest=_fixture_digest("m15-scope"),
            catalog_digest=_fixture_digest("m15-catalog"),
            as_of_available_at=2,
            operation="initialize",
            state_instance_id="m15-known-answer-instance",
        )
    )


def _invoke_m15() -> UpdateConsistencyResult:
    state = _m15_runtime_state()
    grain = EvaluationGrain(
        world_id="W01",
        case_id="known-case",
        cut_id="cut-02",
        task=Task.RECURSIVE_UPDATE,
        replicate_id="replicate-003",
        horizon_id="horizon-04",
        policy_id="policy-A",
    )
    update = UpdateIdentityObservation(
        grain=grain,
        information_kind=InformationKind.INFORMATIVE_OBSERVATION,
        incremental_state=state,
        replay_state=state,
        batch_behavior={"diagnosis": [0.2, 0.8]},
        sequential_behavior={"diagnosis": [0.2, 0.8]},
    )
    query = QueryOrderObservation(
        grain=grain,
        first_order=("diagnosis", "rollout"),
        second_order=("rollout", "diagnosis"),
        first_pre_state=state,
        first_post_state=state,
        second_pre_state=state,
        second_post_state=state,
        first_outputs_by_query={"diagnosis": [0.7, 0.3], "rollout": {"y": 2}},
        second_outputs_by_query={"rollout": {"y": 2}, "diagnosis": [0.7, 0.3]},
    )
    score_specs = (
        (InformationKind.INFORMATIVE_OBSERVATION, ReadoutKind.DIAGNOSIS),
        (InformationKind.INFORMATIVE_OBSERVATION, ReadoutKind.ROLLOUT),
        (InformationKind.INFORMATIVE_TREATMENT_RESPONSE, ReadoutKind.DIAGNOSIS),
        (InformationKind.INFORMATIVE_TREATMENT_RESPONSE, ReadoutKind.ROLLOUT),
        (InformationKind.NO_INFORMATION_CONTROL, ReadoutKind.DIAGNOSIS),
    )
    scores = tuple(
        OracleScoreChangeObservation(
            grain=grain,
            information_kind=information_kind,
            readout_kind=readout_kind,
            score_direction=ScoreDirection.MINIMIZE,
            candidate_before=2.0,
            candidate_after=1.0,
            oracle_before=0.0,
            oracle_after=0.0,
        )
        for information_kind, readout_kind in score_specs
    )
    return update_consistency((update,), (query,), scores)


def _invoke_m16() -> NovelReadoutTransferResult:
    evaluations = tuple(
        NovelReadoutEvaluation(
            card=NovelReadoutCard(
                readout_id=readout_id,
                candidate_seal_digest=_fixture_digest("m16-candidate-seal"),
                source_scope_digest=_fixture_digest("m16-source-scope"),
                target_scope_digest=_fixture_digest("m16-target-scope"),
                candidate_build_worker_id="candidate-builder",
                readout_worker_id="independent-readout-worker",
                history_baseline_worker_id="independent-history-worker",
                candidate_sealed_before_target_reveal=True,
                candidate_base_digest_before=_fixture_digest("m16-sealed-base"),
                candidate_base_digest_after=_fixture_digest("m16-sealed-base"),
                readout_inputs=(ReadoutInput.SEALED_STATE, ReadoutInput.NEW_LABEL),
                history_baseline_inputs=(
                    ReadoutInput.RAW_HISTORY,
                    ReadoutInput.NEW_LABEL,
                ),
                novelty_relation=NoveltyRelation.GENUINELY_NEW_SEMANTIC_READOUT,
                novelty_basis_digest=_fixture_digest(f"m16-novelty-{readout_id}"),
                in_original_y=in_original_y,
                original_y_membership_basis=(
                    OriginalYMembershipBasis.EXACT_ORIGINAL_Y_SEMANTIC_MEMBER
                    if in_original_y
                    else OriginalYMembershipBasis.TARGET_SCOPE_EXTENSION_OUTSIDE_ORIGINAL_Y
                ),
                original_y_membership_evidence_digest=_fixture_digest(
                    f"m16-membership-{readout_id}"
                ),
                score_direction=ScoreDirection.MINIMIZE,
                sample_efficiency_target_score=0.3,
            ),
            points=(
                NovelReadoutScorePoint(10, 0.6, 0.5),
                NovelReadoutScorePoint(20, 0.25, 0.2),
            ),
        )
        for readout_id, in_original_y in (
            ("known-readout-z", False),
            ("known-readout-a", True),
        )
    )
    return sealed_state_novel_readout_transfer(evaluations)


_ADAPTER_BUILDERS: dict[FormulaImplementationKey, FormulaAdapter] = {
    FormulaImplementationKey.M01_DIAGNOSIS: FormulaAdapter(
        diagnosis_metrics_m01,
        _invoke_m01,
        DiagnosisMetricReport,
        "prototype/unified_map/metrics_diagnosis_forecast.py",
        "probability_matrix + realized_label_vector + exact top_k + probability intervals",
        {
            "fixture": "m01-two-row-two-class",
            "top_k": [2],
            "interval_levels": [0.5, 0.8, 0.95],
        },
        "M01 realized-label diagnosis metrics",
    ),
    FormulaImplementationKey.M01_ORACLE_POSTERIOR: FormulaAdapter(
        oracle_posterior_diagnosis_metrics_m01,
        _invoke_m01_oracle_posterior,
        OraclePosteriorDiagnosisMetricReport,
        "prototype/unified_map/metrics_diagnosis_forecast.py",
        "predicted_probability_matrix + aligned oracle_posterior_probability_matrix",
        {
            "fixture": "m01-two-row-two-class-oracle-posterior",
            "truth_branch": "oracle_posterior",
        },
        "M01 oracle-posterior diagnosis proper scores",
    ),
    FormulaImplementationKey.M02_CONTINUOUS: FormulaAdapter(
        ensemble_continuous_metrics_m02,
        _invoke_m02_continuous,
        ContinuousForecastReport,
        "prototype/unified_map/metrics_diagnosis_forecast.py",
        "ensemble[row,member,axis] + truth[row,axis] + positive oracle_scale[axis] + intervals",
        {
            "fixture": "m02-two-row-two-member-two-axis",
            "interval_levels": [0.5, 0.8, 0.95],
        },
        "M02 continuous forecast metrics",
    ),
    FormulaImplementationKey.M02_EVENT: FormulaAdapter(
        discrete_event_metrics_m02,
        _invoke_m02_event,
        EventMetricReport,
        "prototype/unified_map/metrics_diagnosis_forecast.py",
        "event_probability_matrix + aligned binary event truth",
        {"fixture": "m02-two-row-two-event"},
        "M02 discrete-event metrics",
    ),
    FormulaImplementationKey.M02_ENERGY: FormulaAdapter(
        joint_energy_score_m02,
        _invoke_m02_energy,
        EnergyScoreReport,
        "prototype/unified_map/metrics_diagnosis_forecast.py",
        "ensemble[row,member,axis] + truth[row,axis] + positive oracle_scale[axis]",
        {"fixture": "m02-two-row-two-member-two-axis"},
        "M02 normalized joint energy score",
    ),
    FormulaImplementationKey.M03_TRAJECTORY: FormulaAdapter(
        intervention_trajectory_metrics,
        _invoke_m03_trajectory,
        InterventionTrajectoryMetrics,
        "prototype/unified_map/metrics_intervention_regret.py",
        "nonempty tuple[GaussianTrajectoryCase]",
        {"fixture": "m03-one-gaussian-trajectory"},
        "M03 Gaussian intervention trajectory",
    ),
    FormulaImplementationKey.M03_EFFECT: FormulaAdapter(
        treatment_effect_metrics,
        _invoke_m03_effect,
        TreatmentEffectMetrics,
        "prototype/unified_map/metrics_intervention_regret.py",
        "nonempty tuple[TreatmentEffectCase] + nonnegative effect_sign_tolerance",
        {"fixture": "m03-two-effect-cases", "effect_sign_tolerance": 0.0},
        "M03 treatment-effect metrics",
    ),
    FormulaImplementationKey.M03_COVERAGE: FormulaAdapter(
        policy_horizon_coverage,
        _invoke_m03_coverage,
        PolicyHorizonCoverageMetrics,
        "prototype/unified_map/metrics_intervention_regret.py",
        "nonempty tuple[PolicyHorizonExposure] with unique required cells",
        {"fixture": "m03-two-required-cells"},
        "M03 policy-horizon coverage",
    ),
    FormulaImplementationKey.M03_IDENTIFIED_SET: FormulaAdapter(
        identified_set_metrics,
        _invoke_m03_identified,
        IdentifiedSetMetrics,
        "prototype/unified_map/metrics_intervention_regret.py",
        "nonempty tuple[IdentifiedSetCase] + nonnegative tolerance",
        {"fixture": "m03-set-and-point-claims", "tolerance": 0.0},
        "M03 identified-set metrics",
    ),
    FormulaImplementationKey.M04_POINT_REGRET: FormulaAdapter(
        point_identified_regret,
        _invoke_m04_point,
        PointRegretMetrics,
        "prototype/unified_map/metrics_intervention_regret.py",
        "nonempty tuple[RegretCase] with action-local tie order and margins",
        {"fixture": "m04-point-regret-with-w19-tail"},
        "M04 point-identified regret",
    ),
    FormulaImplementationKey.M04_PARTIAL_REGRET: FormulaAdapter(
        partial_identification_regret,
        _invoke_m04_partial,
        PartialIdentificationMetrics,
        "prototype/unified_map/metrics_intervention_regret.py",
        "nonempty tuple[PartialIdentificationCase] with compatible oracle models",
        {"fixture": "m04-partial-regret-with-w19-tail"},
        "M04 partial-identification regret",
    ),
    FormulaImplementationKey.M05_COLLISION: FormulaAdapter(
        collision_metrics,
        _invoke_m05,
        CollisionMetricReport,
        "prototype/unified_map/pre_freeze_metrics_m05_m08.py",
        "pair probes + explicit PairThresholds",
        {
            "fixture": "m05-collision-and-split-pairs",
            "thresholds": [0.1, 0.5, 0.1, 0.5, 1.0],
        },
        "M05 collision metrics",
    ),
    FormulaImplementationKey.M06_FALSE_SPLIT: FormulaAdapter(
        false_split_metrics,
        _invoke_m06,
        FalseSplitMetricReport,
        "prototype/unified_map/pre_freeze_metrics_m05_m08.py",
        "pair probes + explicit PairThresholds",
        {
            "fixture": "m06-collision-and-split-pairs",
            "thresholds": [0.1, 0.5, 0.1, 0.5, 1.0],
        },
        "M06 false-split metrics",
    ),
    FormulaImplementationKey.M07_OOD: FormulaAdapter(
        ood_metrics,
        _invoke_m07,
        OODMetricReport,
        "prototype/unified_map/pre_freeze_metrics_m05_m08.py",
        "OOD examples + frozen_low_fpr + catastrophic_margin",
        {
            "fixture": "m07-one-known-one-ood",
            "frozen_low_fpr": 0.05,
            "catastrophic_margin": 1.0,
        },
        "M07 OOD metrics",
    ),
    FormulaImplementationKey.M08_TEMPORAL_LEAK: FormulaAdapter(
        temporal_leakage_metrics,
        _invoke_m08,
        TemporalLeakMetricReport,
        "prototype/unified_map/pre_freeze_metrics_m05_m08.py",
        "temporal leak probes with exact prefix/state/prediction bytes",
        {"fixture": "m08-one-identical-prefix-probe"},
        "M08 temporal leakage metrics",
    ),
    FormulaImplementationKey.M09_SAMPLE_EFFICIENCY: FormulaAdapter(
        sample_efficiency,
        _invoke_m09,
        SampleEfficiencyResult,
        "prototype/unified_map/metrics_m09_m11.py",
        "exact tuple of 18 canonical LearningCurvePoint evidence objects",
        {
            "fixture": "m09-three-tasks-six-fractions",
            "fractions": list(TRAIN_FRACTION_PERCENTS),
        },
        "M09 log-sample learning curves",
    ),
    FormulaImplementationKey.M10_GENERALIZATION: FormulaAdapter(
        combination_generalization,
        _invoke_m10,
        CombinationGeneralizationResult,
        "prototype/unified_map/metrics_m09_m11.py",
        "canonical HeldoutMatchedPair evidence covering all three strata",
        {"fixture": "m10-one-pair-per-stratum"},
        "M10 matched held-out gaps",
    ),
    FormulaImplementationKey.M11_EXTENSION_COST: FormulaAdapter(
        extension_cost,
        _invoke_m11,
        ExtensionCostResult,
        "prototype/unified_map/metrics_m09_m11.py",
        "caller-produced canonical ExtensionCostObservation evidence",
        {
            "fixture": "m11-two-caller-produced-observations-reversed-input",
            "projection_order": "extension_id_ascending",
            "projection_shape": "tuple[{extension_id,value}]",
        },
        "M11 extension cost collector",
    ),
    FormulaImplementationKey.M12_STATE_SIZE: FormulaAdapter(
        state_size_metrics,
        _invoke_m12,
        StateSizeResult,
        "prototype/unified_map/metrics_state_resource_stability.py",
        "caller-produced canonical StateSizeRow evidence for one candidate authority",
        {
            "fixture": "m12-three-json-state-rows-one-matched-grain",
            "state_codec_branch": "canonical_json_only",
            "history_lengths": [1, 2, 3],
        },
        "M12 state size, component count, slope, and task-horizon slices",
    ),
    FormulaImplementationKey.M13_RESOURCE: FormulaAdapter(
        resource_metrics,
        _invoke_m13,
        ResourceResult,
        "prototype/unified_map/metrics_state_resource_stability.py",
        "caller-produced ResourceMeasurement rows with one caller-bound CollectorProvenance",
        {
            "fixture": "m13-four-latencies-and-all-eight-resource-kinds",
            "latency_operation_order": [item.value for item in CandidateOperation],
            "collector_authority": "caller_asserted_unbound",
        },
        "M13 cold latency and resource collector summaries",
    ),
    FormulaImplementationKey.M14_STABILITY: FormulaAdapter(
        five_seed_stability,
        _invoke_m14,
        FiveSeedStabilityResult,
        "prototype/unified_map/metrics_state_resource_stability.py",
        "exact five zipped replicate candidate series plus optional paired baseline series",
        {
            "fixture": "m14-five-zipped-candidate-and-baseline-replicates",
            "replicate_pairs": [list(pair) for pair in ZIPPED_REPLICATE_IDS],
            "seed_ci": "student_t_df4",
        },
        "M14 five-seed summary and paired-delta stability",
    ),
    FormulaImplementationKey.M15_UPDATE_CONSISTENCY: FormulaAdapter(
        update_consistency,
        _invoke_m15,
        UpdateConsistencyResult,
        "prototype/unified_map/metrics_update_transfer.py",
        "caller-produced typed update, query-order, and oracle-score observations",
        {
            "fixture": "m15-one-aligned-grain-all-directional-information-readout-branches",
            "directional_readouts": ["diagnosis", "rollout"],
            "directional_information_kinds": [
                "informative_observation",
                "informative_treatment_response",
                "no_information_control",
            ],
            "input_authority": "caller_asserted_unbound",
        },
        "M15 update/replay identity, query purity, and directional changes",
    ),
    FormulaImplementationKey.M16_NOVEL_READOUT: FormulaAdapter(
        sealed_state_novel_readout_transfer,
        _invoke_m16,
        NovelReadoutTransferResult,
        "prototype/unified_map/metrics_update_transfer.py",
        "caller-produced typed novel-readout cards and score curves",
        {
            "fixture": "m16-two-caller-asserted-readout-cards-reversed-input",
            "projection_order": "readout_id_ascending",
            "projection_shape": "tuple[{readout_id,value}]",
            "formal_eligibility": "unavailable",
        },
        "M16 sealed-state novel-readout caller-shape and score summaries",
    ),
}


_TARGET_REQUIRED_BRANCH_BUILDERS: dict[tuple[str, int], tuple[str, ...]] = {
    ("M01", 1): ("realized_label", "oracle_posterior"),
    ("M01", 2): ("realized_label", "oracle_posterior"),
    ("M01", 9): ("coverage_50", "coverage_80", "coverage_95"),
    ("M02", 6): (
        "continuous_crps",
        "oracle_scale_normalized_mae",
        "oracle_scale_normalized_rmse",
    ),
    ("M02", 7): ("coverage_50", "coverage_80", "coverage_95"),
    ("M02", 11): (
        "normalized_joint_energy_score",
        "world_declared_joint_proper_score",
    ),
    ("M02", 12): ("integrated_survival_brier", "integrated_survival_nll"),
    ("M02", 14): (
        "calibration_slope_by_horizon",
        "calibration_intercept_by_horizon",
    ),
    ("M03", 1): (
        "continuous_gaussian_nll_slice",
        "continuous_crps",
        "discrete_event_nll",
        "discrete_event_brier",
        "normalized_joint_energy_score",
        "world_declared_joint_proper_score",
    ),
    ("M03", 2): ("mean_absolute_effect_error", "root_mean_squared_effect_error"),
    ("M03", 3): ("effect_sign_error_count", "effect_sign_error_rate"),
    ("M03", 4): ("policy_horizon_coverage", "policy_horizon_calibration"),
    ("M03", 6): (
        "oracle_set_coverage",
        "candidate_set_width",
        "hausdorff_error",
        "set_bound_error",
    ),
    ("M04", 3): ("mean", "median", "p95", "maximum", "cvar95"),
    ("M04", 11): (
        "point_identified_w19_tail",
        "partial_identified_w19_tail",
    ),
    ("M05", 6): ("pair_level_decisions", "pair_level_trajectory_evidence"),
    ("M06", 5): ("pair_level_decisions", "pair_level_trajectory_evidence"),
    ("M07", 5): ("risk_coverage_curve", "aurc"),
    ("M07", 8): (
        "unknown_probability_brier",
        "unknown_probability_nll",
        "unknown_probability_calibration",
    ),
    ("M07", 9): ("ood_treatment_regret", "unsafe_nonabstain_rate"),
    ("M09", 1): ("diagnosis_learning_curve", "diagnosis_log_sample_auc"),
    ("M09", 2): (
        "natural_forecast_learning_curve",
        "natural_forecast_log_sample_auc",
    ),
    ("M09", 3): (
        "intervention_learning_curve",
        "intervention_log_sample_auc",
    ),
    ("M11", 4): ("core_diff_loc", "core_diff_changed_files"),
    ("M12", 1): (
        "canonical_json_raw_bytes",
        "raw_f64le_raw_bytes",
        "bound_harness_state_custody",
    ),
    ("M12", 2): (
        "canonical_json_compressed_bytes",
        "raw_f64le_compressed_bytes",
        "bound_harness_state_custody",
    ),
    ("M12", 3): (
        "scalar_count",
        "node_count",
        "edge_count",
        "particle_count",
    ),
    ("M12", 4): (
        "canonical_json_history_length_ols",
        "raw_f64le_history_length_ols",
        "bound_harness_state_custody",
    ),
    ("M12", 5): (
        "canonical_json_task_horizon_slices",
        "raw_f64le_task_horizon_slices",
        "bound_harness_state_custody",
    ),
    ("M13", 1): (
        "initialize_latency_distribution",
        "update_latency_distribution",
        "diagnose_latency_distribution",
        "rollout_latency_distribution",
    ),
    ("M13", 2): ("peak_rss",),
    ("M13", 3): ("peak_gpu_memory",),
    ("M13", 4): ("model_artifact_bytes",),
    ("M13", 5): ("train_flops", "train_wall_time"),
    ("M13", 6): (
        "postseal_worker_wall_time",
        "postseal_worker_peak_rss",
        "postseal_worker_peak_gpu_memory",
    ),
    ("M14", 1): ("replicate_mean",),
    ("M14", 2): ("sample_standard_deviation",),
    ("M14", 3): ("replicate_minimum", "replicate_maximum"),
    ("M14", 4): ("student_t_ci95_lower", "student_t_ci95_upper"),
    ("M14", 5): ("paired_delta_ci95_lower", "paired_delta_ci95_upper"),
    ("M14", 6): ("hierarchical_bootstrap_ci95",),
    ("M15", 1): ("state_hash_match", "payload_bytes_match"),
    ("M15", 2): ("batch_sequential_behavioral_match",),
    ("M15", 3): (
        "same_start_state_hash",
        "same_start_payload_bytes",
        "first_order_state_unchanged",
        "second_order_state_unchanged",
        "per_query_outputs_equal",
    ),
    ("M15", 4): (
        "informative_observation_diagnosis",
        "informative_observation_rollout",
        "informative_treatment_response_diagnosis",
        "informative_treatment_response_rollout",
        "no_information_control_disposition",
    ),
    ("M16", 1): (
        "caller_asserted_score",
        "formal_novel_readout_eligibility",
    ),
    ("M16", 2): (
        "caller_asserted_sample_efficiency_curve",
        "frozen_target_authority",
        "formal_novel_readout_eligibility",
    ),
    ("M16", 3): (
        "caller_asserted_state_history_gap",
        "same_basis_score_authority",
        "formal_novel_readout_eligibility",
    ),
    ("M16", 4): (
        "caller_asserted_input_shape_signal",
        "independent_history_reread_proof",
    ),
    ("M16", 5): ("formal_original_scope_sufficiency_disposition",),
}


_UNTRUSTED_TARGET_BUILDERS = frozenset(
    {
        *(("M11", ordinal) for ordinal in range(1, 7)),
        *(("M12", ordinal) for ordinal in range(1, 6)),
        *(("M13", ordinal) for ordinal in range(1, 7)),
        *(("M15", ordinal) for ordinal in range(1, 5)),
        *(("M16", ordinal) for ordinal in range(1, 5)),
    }
)


def _branch(
    branch_id: str,
    key: FormulaImplementationKey,
    selector_key: str,
    selector: Callable[[object], object],
    denominator: str,
    tie: str = "not_applicable",
    undefined: str = "reject_invalid_input_or_typed_null",
    *,
    satisfies_target_branches: tuple[str, ...] | None = None,
) -> FormulaBranchBindingSpec:
    return FormulaBranchBindingSpec(
        branch_id,
        (
            (branch_id,)
            if satisfies_target_branches is None
            else satisfies_target_branches
        ),
        key,
        selector_key,
        selector,
        denominator,
        tie,
        undefined,
    )


def _multi_spec(*branches: FormulaBranchBindingSpec) -> TargetBindingSpec:
    return TargetBindingSpec(branches)


def _spec(
    key: FormulaImplementationKey,
    selector_key: str,
    selector: Callable[[object], object],
    denominator: str,
    tie: str = "not_applicable",
    undefined: str = "reject_invalid_input_or_typed_null",
    *,
    branch_id: str = "complete_target",
    satisfies_target_branches: tuple[str, ...] | None = None,
) -> TargetBindingSpec:
    return _multi_spec(
        _branch(
            branch_id,
            key,
            selector_key,
            selector,
            denominator,
            tie,
            undefined,
            satisfies_target_branches=satisfies_target_branches,
        )
    )


def _curve(result: object, task: str) -> object:
    return next(item for item in result.task_curves if item.task.value == task)  # type: ignore[attr-defined]


def _gap(result: object, stratum: str) -> object:
    return next(item for item in result.stratum_gaps if item.stratum.value == stratum)  # type: ignore[attr-defined]


def _partial_w19_tail(result: object) -> object:
    rows = tuple(row for row in result.rows if row.w19_tail_member)  # type: ignore[attr-defined]
    return {
        "exposure": len(rows),
        "robust_regret_bound_summary": result.w19_tail_robust_regret_bound_summary,  # type: ignore[attr-defined]
        "all_compatible_catastrophic_count": sum(
            row.all_compatible_catastrophic for row in rows
        ),
        "all_compatible_catastrophic_rate": (
            sum(row.all_compatible_catastrophic for row in rows) / len(rows)
            if rows
            else None
        ),
        "undefined_reason": result.w19_tail_undefined_reason,  # type: ignore[attr-defined]
    }


def _extension_projection(result: object, field: str) -> object:
    return tuple(
        {"extension_id": extension["extension_id"], "value": extension[field]}
        for extension in result.extensions  # type: ignore[attr-defined]
    )


def _state_row_projection(result: object, field: str) -> object:
    return tuple(
        {"record_id": row["record_id"], "value": row[field]}
        for row in result.rows  # type: ignore[attr-defined]
    )


def _resource_projection(result: object, *kinds: ResourceKind) -> object:
    wanted = {kind.value for kind in kinds}
    return tuple(
        {"resource_kind": row["resource_kind"], "value": row}
        for row in result.resources  # type: ignore[attr-defined]
        if row["resource_kind"] in wanted
    )


def _readout_projection(result: object, field: str) -> object:
    return tuple(
        {"readout_id": row["readout_id"], "value": row[field]}
        for row in result.readouts  # type: ignore[attr-defined]
    )


def _readout_fields_projection(result: object, *fields: str) -> object:
    return tuple(
        {
            "readout_id": row["readout_id"],
            "value": {field: row[field] for field in fields},
        }
        for row in result.readouts  # type: ignore[attr-defined]
    )


def _type_attestation(value: type[object]) -> dict[str, str]:
    return {
        "object_identity": f"0x{id(value):x}",
        "module": value.__module__,
        "qualname": value.__qualname__,
    }


def _attestation_value(value: object) -> Any:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ProtocolViolation(
                "control-plane attestation contains non-finite float"
            )
        return value
    if type(value) is bytes:
        return {"exact_bytes_hex": value.hex()}
    if isinstance(value, Enum):
        return {
            "enum_type": _type_attestation(type(value)),
            "value": value.value,
        }
    if inspect.isfunction(value):
        return _function_attestation(value)
    if isinstance(value, type):
        return {"type": _type_attestation(value)}
    if type(value) is tuple:
        return [_attestation_value(item) for item in value]
    if type(value) is list:
        return [_attestation_value(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ProtocolViolation(
                "control-plane attestation dictionary keys must be strings"
            )
        return {key: _attestation_value(item) for key, item in value.items()}
    raise ProtocolViolation(
        f"unsupported control-plane attestation value {type(value)!r}"
    )


def _function_attestation(function: Callable[..., object]) -> dict[str, Any]:
    if not inspect.isfunction(function):
        raise ProtocolViolation(
            "control-plane callable must be an exact Python function"
        )
    try:
        code_bytes = canonical_json_bytes(_code_attestation_wire(function.__code__))
        signature = str(inspect.signature(function))
        source_file = inspect.getsourcefile(function)
    except (TypeError, ValueError, OSError) as exc:
        raise ProtocolViolation("control-plane callable is not inspectable") from exc
    closure: list[Any] = []
    for cell in function.__closure__ or ():
        try:
            closure.append(_attestation_value(cell.cell_contents))
        except ValueError:
            closure.append({"empty_cell": True})
    return {
        "object_identity": f"0x{id(function):x}",
        "module": function.__module__,
        "name": function.__name__,
        "qualname": function.__qualname__,
        "signature": signature,
        "source_file": None
        if source_file is None
        else Path(source_file).resolve().as_posix(),
        "code_byte_count": len(code_bytes),
        "code_digest": digest_bytes(code_bytes),
        "defaults": _attestation_value(function.__defaults__),
        "keyword_defaults": _attestation_value(function.__kwdefaults__),
        "annotations": _attestation_value(dict(function.__annotations__)),
        "closure": closure,
        "function_attributes": _attestation_value(dict(function.__dict__)),
    }


def _code_constant_attestation(value: object) -> Any:
    if inspect.iscode(value):
        return {"code_object": _code_attestation_wire(value)}
    if value is Ellipsis:
        return {"singleton": "Ellipsis"}
    if type(value) is complex:
        if not math.isfinite(value.real) or not math.isfinite(value.imag):
            raise ProtocolViolation("control-plane code constant is non-finite")
        return {"complex_real": value.real, "complex_imag": value.imag}
    if type(value) is frozenset:
        members = [_code_constant_attestation(item) for item in value]
        return {
            "frozenset": sorted(members, key=lambda item: canonical_json_bytes(item))
        }
    return _attestation_value(value)


def _code_attestation_wire(code: object) -> dict[str, Any]:
    if not inspect.iscode(code):
        raise ProtocolViolation(
            "control-plane function code is not an exact code object"
        )
    return {
        "object_identity": f"0x{id(code):x}",
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "nlocals": code.co_nlocals,
        "stacksize": code.co_stacksize,
        "flags": code.co_flags,
        "bytecode_hex": code.co_code.hex(),
        "constants": [_code_constant_attestation(item) for item in code.co_consts],
        "names": list(code.co_names),
        "varnames": list(code.co_varnames),
        "filename": Path(code.co_filename).resolve().as_posix(),
        "name": code.co_name,
        "qualname": code.co_qualname,
        "firstlineno": code.co_firstlineno,
        "linetable_hex": code.co_linetable.hex(),
        "exceptiontable_hex": code.co_exceptiontable.hex(),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
    }


def _manifest_attestation_wire(
    manifest: CodeOwnedBindingManifest,
) -> dict[str, Any]:
    if type(manifest) is not CodeOwnedBindingManifest:
        raise ProtocolViolation("code-owned binding manifest has a wrong exact type")
    adapters: list[dict[str, Any]] = []
    for key, adapter in sorted(
        manifest.adapters.items(), key=lambda item: item[0].value
    ):
        if type(key) is not FormulaImplementationKey:
            raise ProtocolViolation("manifest adapter key is not code-owned")
        if type(adapter) is not FrozenFormulaAdapter:
            raise ProtocolViolation("manifest adapter has a wrong exact type")
        adapters.append(
            {
                "implementation_key": key.value,
                "adapter_type": _type_attestation(type(adapter)),
                "function": _function_attestation(adapter.function),
                "invoke_known_answer": _function_attestation(
                    adapter.invoke_known_answer
                ),
                "expected_result_type": _type_attestation(adapter.expected_result_type),
                "source_path": adapter.source_path,
                "input_type_contract": adapter.input_type_contract,
                "known_answer_parameter_preimage_exact_bytes_hex": (
                    adapter.known_answer_parameter_preimage_bytes.hex()
                ),
                "formula_family": adapter.formula_family,
            }
        )
    bindings: list[dict[str, Any]] = []
    for join_key, spec in sorted(manifest.target_bindings.items()):
        if (
            type(join_key) is not tuple
            or len(join_key) != 2
            or type(join_key[0]) is not str
            or type(join_key[1]) is not int
            or type(spec) is not TargetBindingSpec
        ):
            raise ProtocolViolation("manifest target binding entry is malformed")
        branches: list[dict[str, Any]] = []
        for branch in spec.branches:
            if type(branch) is not FormulaBranchBindingSpec:
                raise ProtocolViolation("manifest branch has a wrong exact type")
            branches.append(
                {
                    "branch_type": _type_attestation(type(branch)),
                    "branch_id": branch.branch_id,
                    "satisfies_target_branches": list(branch.satisfies_target_branches),
                    "implementation_key": branch.implementation_key.value,
                    "selector_key": branch.selector_key,
                    "selector": _function_attestation(branch.selector),
                    "denominator_contract": branch.denominator_contract,
                    "tie_policy": branch.tie_policy,
                    "undefined_disposition": branch.undefined_disposition,
                }
            )
        bindings.append(
            {
                "measurement_id": join_key[0],
                "ordinal": join_key[1],
                "binding_type": _type_attestation(type(spec)),
                "branches": branches,
            }
        )
    required_branches = [
        {
            "measurement_id": join_key[0],
            "ordinal": join_key[1],
            "required_branches": list(branches),
        }
        for join_key, branches in sorted(manifest.required_branches.items())
    ]
    untrusted_targets = [
        {"measurement_id": measurement_id, "ordinal": ordinal}
        for measurement_id, ordinal in sorted(manifest.untrusted_targets)
    ]
    return {
        "manifest_type": _type_attestation(type(manifest)),
        "adapters": adapters,
        "target_bindings": bindings,
        "required_branches": required_branches,
        "untrusted_targets": untrusted_targets,
    }


def _control_plane_attestation_bytes(control: CodeOwnedControlPlane) -> bytes:
    if type(control) is not CodeOwnedControlPlane:
        raise ProtocolViolation("code-owned control plane has a wrong exact type")
    imported_source_digests = [
        {"path": path, "artifact_digest": digest}
        for path, digest in sorted(control.imported_source_digests.items())
    ]
    return canonical_json_bytes(
        {
            "control_plane_type": _type_attestation(type(control)),
            "manifest": _manifest_attestation_wire(control.manifest),
            "source_paths": list(control.source_paths),
            "always_remaining_blockers": list(control.always_remaining_blockers),
            "remaining_global_gaps": list(control.remaining_global_gaps),
            "imported_source_digests": imported_source_digests,
            "semantic_constants": {
                "schema_version": control.schema_version,
                "benchmark_id": control.benchmark_id,
                "benchmark_status": control.benchmark_status,
                "authority_claim": control.authority_claim,
                "evaluator_binding": control.evaluator_binding,
                "freeze_authority": control.freeze_authority,
                "aggregate_score": control.aggregate_score,
                "target_object_domain_hex": control.target_object_domain.hex(),
                "source_closure_domain_hex": control.source_closure_domain.hex(),
                "binding_set_domain_hex": control.binding_set_domain.hex(),
                "artifact_domain_hex": control.artifact_domain.hex(),
            },
        }
    )


_TARGET_BINDING_BUILDERS: dict[tuple[str, int], TargetBindingSpec] = {}


def _bind(measurement: str, ordinal: int, spec: TargetBindingSpec) -> None:
    key = (measurement, ordinal)
    if key in _TARGET_BINDING_BUILDERS:
        raise RuntimeError(f"duplicate code-owned target binding {key!r}")
    _TARGET_BINDING_BUILDERS[key] = spec


_M01_SELECTORS = (
    ("multiclass_nll", lambda r: r.multiclass_nll, "N diagnosis rows"),
    ("multiclass_brier", lambda r: r.multiclass_brier, "N diagnosis rows"),
    ("top1_accuracy", lambda r: r.top1_accuracy, "N diagnosis rows"),
    ("topk_accuracy", lambda r: r.topk_accuracy, "N rows per declared k"),
    ("macro_recall", lambda r: r.macro_recall, "supported true classes"),
    (
        "top_label_calibration_ece15",
        lambda r: r.top_label_calibration,
        "N top-label rows",
    ),
    (
        "classwise_calibration_ece15",
        lambda r: r.classwise_calibration,
        "N one-vs-rest rows per class",
    ),
    (
        "top_label_reliability_bins15",
        lambda r: r.top_label_calibration.bins,
        "N top-label rows across 15 nominal bins",
    ),
    (
        "probability_interval_coverage",
        lambda r: r.probability_interval_coverage,
        "N*K cells per declared interval level",
    ),
)
for _ordinal, (_selector_key, _selector, _denominator) in enumerate(_M01_SELECTORS, 1):
    if _ordinal in {1, 2}:
        _oracle_selector_key, _oracle_selector = (
            (
                "oracle_posterior_cross_entropy_nll",
                lambda r: r.posterior_cross_entropy_nll,
            )
            if _ordinal == 1
            else (
                "oracle_posterior_multiclass_brier",
                lambda r: r.posterior_multiclass_brier,
            )
        )
        _binding = _multi_spec(
            _branch(
                "realized_label",
                FormulaImplementationKey.M01_DIAGNOSIS,
                _selector_key,
                _selector,
                _denominator,
                "descending_probability_then_ascending_class_index_where_applicable",
            ),
            _branch(
                "oracle_posterior",
                FormulaImplementationKey.M01_ORACLE_POSTERIOR,
                _oracle_selector_key,
                _oracle_selector,
                _denominator,
            ),
        )
    else:
        _binding = _spec(
            FormulaImplementationKey.M01_DIAGNOSIS,
            _selector_key,
            _selector,
            _denominator,
            "descending_probability_then_ascending_class_index_where_applicable",
            satisfies_target_branches=(
                ("coverage_50", "coverage_80", "coverage_95") if _ordinal == 9 else None
            ),
        )
    _bind(
        "M01",
        _ordinal,
        _binding,
    )

for _ordinal, _selector_key, _selector, _denominator in (
    (
        3,
        "crps_by_axis",
        lambda r: r.crps_by_axis,
        "rows per axis; equal ensemble members",
    ),
    (
        4,
        "normalized_mae_by_axis",
        lambda r: r.oracle_scale_normalized_mae_by_axis,
        "rows per axis",
    ),
    (
        5,
        "normalized_rmse_by_axis",
        lambda r: r.oracle_scale_normalized_rmse_by_axis,
        "rows per axis",
    ),
    (
        6,
        "all_continuous_axis_results",
        lambda r: {
            "crps": r.crps_by_axis,
            "mae": r.oracle_scale_normalized_mae_by_axis,
            "rmse": r.oracle_scale_normalized_rmse_by_axis,
        },
        "rows per axis",
    ),
    (
        7,
        "continuous_interval_coverage",
        lambda r: r.interval_coverage,
        "row-axis cells per level",
    ),
):
    _bind(
        "M02",
        _ordinal,
        _spec(
            FormulaImplementationKey.M02_CONTINUOUS,
            _selector_key,
            _selector,
            _denominator,
            satisfies_target_branches=(
                (
                    "continuous_crps",
                    "oracle_scale_normalized_mae",
                    "oracle_scale_normalized_rmse",
                )
                if _ordinal == 6
                else (
                    ("coverage_50", "coverage_80", "coverage_95")
                    if _ordinal == 7
                    else None
                )
            ),
        ),
    )
for _ordinal, _selector_key, _selector in (
    (8, "event_nll_by_event", lambda r: r.nll_by_event),
    (9, "event_brier_by_event", lambda r: r.brier_by_event),
    (10, "event_reliability_by_event", lambda r: r.reliability_by_event),
):
    _bind(
        "M02",
        _ordinal,
        _spec(
            FormulaImplementationKey.M02_EVENT,
            _selector_key,
            _selector,
            "rows per event",
        ),
    )
_bind(
    "M02",
    11,
    _spec(
        FormulaImplementationKey.M02_ENERGY,
        "normalized_joint_energy_score",
        lambda r: r.normalized_joint_energy_score,
        "N multivariate rows; equal ensemble members",
        branch_id="normalized_joint_energy_score",
    ),
)

for _ordinal, _selector_key, _selector, _key, _denominator in (
    (
        1,
        "gaussian_nll",
        lambda r: r.gaussian_nll,
        FormulaImplementationKey.M03_TRAJECTORY,
        "scalar trajectory cells",
    ),
    (
        2,
        "effect_mae_rmse",
        lambda r: {
            "mae": r.mean_absolute_effect_error,
            "rmse": r.root_mean_squared_effect_error,
        },
        FormulaImplementationKey.M03_EFFECT,
        "treatment-effect cases",
    ),
    (
        3,
        "effect_sign_error",
        lambda r: {
            "count": r.effect_sign_error_count,
            "rate": r.effect_sign_error_rate,
        },
        FormulaImplementationKey.M03_EFFECT,
        "treatment-effect cases",
    ),
    (
        4,
        "policy_horizon_coverage",
        lambda r: {
            "required": r.required_exposure,
            "response": r.response_coverage,
            "scored": r.scored_coverage,
        },
        FormulaImplementationKey.M03_COVERAGE,
        "all declared required policy-horizon cells",
    ),
    (
        5,
        "pehe",
        lambda r: r.pehe,
        FormulaImplementationKey.M03_EFFECT,
        "unit-identified effect cases only",
    ),
    (
        6,
        "identified_set_coverage_width_error",
        lambda r: {
            "coverage": r.oracle_set_coverage,
            "width": r.mean_candidate_set_width,
            "hausdorff": r.mean_hausdorff_error,
            "bound": r.mean_set_bound_error,
        },
        FormulaImplementationKey.M03_IDENTIFIED_SET,
        "non-abstaining set claims",
    ),
    (
        7,
        "identified_set_hausdorff",
        lambda r: r.mean_hausdorff_error,
        FormulaImplementationKey.M03_IDENTIFIED_SET,
        "non-abstaining set claims",
    ),
    (
        8,
        "identified_set_bound_error",
        lambda r: r.mean_set_bound_error,
        FormulaImplementationKey.M03_IDENTIFIED_SET,
        "non-abstaining set claims",
    ),
    (
        9,
        "partial_oracle_set_optimal_actions",
        lambda r: tuple(row.oracle_set_valued_optimal_action_ids for row in r.rows),
        FormulaImplementationKey.M04_PARTIAL_REGRET,
        "partial-ID cases",
    ),
    (
        10,
        "partial_uniformly_dominated_actions",
        lambda r: tuple(row.uniformly_dominated_action_ids for row in r.rows),
        FormulaImplementationKey.M04_PARTIAL_REGRET,
        "partial-ID cases",
    ),
    (
        11,
        "partial_robust_regret_intervals",
        lambda r: tuple(row.selected_oracle_robust_regret_interval for row in r.rows),
        FormulaImplementationKey.M04_PARTIAL_REGRET,
        "partial-ID cases",
    ),
    (
        12,
        "identified_set_false_certainty_rate",
        lambda r: r.false_certainty_rate,
        FormulaImplementationKey.M03_IDENTIFIED_SET,
        "certainty claims only",
    ),
):
    _bind(
        "M03",
        _ordinal,
        _spec(
            _key,
            _selector_key,
            _selector,
            _denominator,
            "action_ties_follow_explicit_action_order_where_applicable",
            branch_id=(
                "continuous_gaussian_nll_slice"
                if _ordinal == 1
                else ("policy_horizon_coverage" if _ordinal == 4 else "complete_target")
            ),
            satisfies_target_branches=(
                ("mean_absolute_effect_error", "root_mean_squared_effect_error")
                if _ordinal == 2
                else (
                    ("effect_sign_error_count", "effect_sign_error_rate")
                    if _ordinal == 3
                    else (
                        (
                            "oracle_set_coverage",
                            "candidate_set_width",
                            "hausdorff_error",
                            "set_bound_error",
                        )
                        if _ordinal == 6
                        else None
                    )
                )
            ),
        ),
    )

for _ordinal, _selector_key, _selector, _key, _denominator in (
    (
        1,
        "point_raw_regret",
        lambda r: {
            "summary": r.full_population.raw,
            "rows": tuple(row.raw_regret for row in r.rows),
        },
        FormulaImplementationKey.M04_POINT_REGRET,
        "point-identified cases",
    ),
    (
        2,
        "point_normalized_regret",
        lambda r: {
            "summary": r.full_population.normalized,
            "rows": tuple(row.normalized_regret for row in r.rows),
        },
        FormulaImplementationKey.M04_POINT_REGRET,
        "cases with nonzero oracle utility range",
    ),
    (
        3,
        "point_regret_distribution",
        lambda r: r.full_population,
        FormulaImplementationKey.M04_POINT_REGRET,
        "point-identified cases",
    ),
    (
        4,
        "point_catastrophic_rate",
        lambda r: {
            "count": r.full_population.catastrophic_action_count,
            "rate": r.full_population.catastrophic_action_rate,
        },
        FormulaImplementationKey.M04_POINT_REGRET,
        "point-identified cases",
    ),
    (
        5,
        "partial_robust_regret_bound",
        lambda r: r.robust_regret_bound_summary,
        FormulaImplementationKey.M04_PARTIAL_REGRET,
        "partial-ID cases",
    ),
    (
        6,
        "partial_set_optimal_actions",
        lambda r: tuple(row.oracle_set_valued_optimal_action_ids for row in r.rows),
        FormulaImplementationKey.M04_PARTIAL_REGRET,
        "partial-ID cases",
    ),
    (
        7,
        "partial_uniformly_dominated_actions",
        lambda r: tuple(row.uniformly_dominated_action_ids for row in r.rows),
        FormulaImplementationKey.M04_PARTIAL_REGRET,
        "partial-ID cases",
    ),
    (
        8,
        "partial_robust_regret_intervals",
        lambda r: tuple(row.selected_oracle_robust_regret_interval for row in r.rows),
        FormulaImplementationKey.M04_PARTIAL_REGRET,
        "partial-ID cases",
    ),
    (
        9,
        "partial_false_certainty_rate",
        lambda r: r.false_certainty_rate,
        FormulaImplementationKey.M04_PARTIAL_REGRET,
        "partial-ID certainty claims",
    ),
    (
        10,
        "partial_descriptive_realization_regret",
        lambda r: tuple(row.descriptive_realization_regret for row in r.rows),
        FormulaImplementationKey.M04_PARTIAL_REGRET,
        "partial-ID cases carrying optional realized oracle utilities",
    ),
    (
        11,
        "point_w19_tail_summary",
        lambda r: r.w19_tail,
        FormulaImplementationKey.M04_POINT_REGRET,
        "W19 tail-member cases",
    ),
):
    if _ordinal == 11:
        _binding = _multi_spec(
            _branch(
                "point_identified_w19_tail",
                FormulaImplementationKey.M04_POINT_REGRET,
                _selector_key,
                _selector,
                _denominator,
                "candidate_optimal_ties_follow_explicit_tie_break_action_ids",
            ),
            _branch(
                "partial_identified_w19_tail",
                FormulaImplementationKey.M04_PARTIAL_REGRET,
                "partial_w19_tail_summary",
                _partial_w19_tail,
                "W19 partial-ID tail-member cases",
                "candidate_optimal_ties_follow_explicit_tie_break_action_ids",
            ),
        )
    else:
        _binding = _spec(
            _key,
            _selector_key,
            _selector,
            _denominator,
            "candidate_optimal_ties_follow_explicit_tie_break_action_ids",
            satisfies_target_branches=(
                ("mean", "median", "p95", "maximum", "cvar95")
                if _ordinal == 3
                else None
            ),
        )
    _bind(
        "M04",
        _ordinal,
        _binding,
    )

for _ordinal, _selector_key, _selector, _denominator in (
    (
        1,
        "raw_exact_collision_rate",
        lambda r: r.overall.raw_exact_collision_rate,
        "oracle-distinguishable pair weight",
    ),
    (
        2,
        "functional_near_collision_rate",
        lambda r: r.overall.functional_near_collision_rate,
        "oracle-distinguishable pair weight",
    ),
    (
        3,
        "attributable_collision_rate",
        lambda r: r.overall.attributable_collision_rate,
        "attributable-eligible pair weight",
    ),
    (
        4,
        "attributable_dangerous_events",
        lambda r: r.overall.dangerous_events,
        "event list; no reduction",
    ),
    (
        5,
        "max_missed_oracle_distance",
        lambda r: r.overall.max_missed_oracle_distance,
        "colliding oracle-distinguishable pairs",
    ),
    (6, "pair_level_decisions", lambda r: r.pair_decisions, "all supplied pair probes"),
):
    _bind(
        "M05",
        _ordinal,
        _spec(
            FormulaImplementationKey.M05_COLLISION,
            _selector_key,
            _selector,
            _denominator,
            branch_id=("pair_level_decisions" if _ordinal == 6 else "complete_target"),
        ),
    )
for _ordinal, _selector_key, _selector, _denominator in (
    (
        1,
        "oracle_equivalent_denominator",
        lambda r: r.overall.oracle_equivalent_denominator,
        "all supplied pair probes filtered by oracle-equivalence margin",
    ),
    (
        2,
        "functional_false_split_rate",
        lambda r: r.overall.functional_false_split_rate,
        "oracle-equivalent pair weight",
    ),
    (
        3,
        "structural_redundancy_count",
        lambda r: {
            "count": r.overall.structural_redundancy_count,
            "weight": r.overall.structural_redundancy_weight,
        },
        "oracle-equivalent pairs",
    ),
    (
        4,
        "max_spurious_candidate_distance",
        lambda r: r.overall.max_spurious_candidate_distance,
        "oracle-equivalent pairs",
    ),
    (5, "pair_level_decisions", lambda r: r.pair_decisions, "all supplied pair probes"),
):
    _bind(
        "M06",
        _ordinal,
        _spec(
            FormulaImplementationKey.M06_FALSE_SPLIT,
            _selector_key,
            _selector,
            _denominator,
            branch_id=("pair_level_decisions" if _ordinal == 5 else "complete_target"),
        ),
    )

_bind(
    "M07",
    8,
    _spec(
        FormulaImplementationKey.M07_OOD,
        "unknown_probability_brier_nll",
        lambda r: {
            "brier": r.overall.unknown_probability_brier,
            "nll": r.overall.unknown_probability_nll,
        },
        "all known/OOD examples with exact supplied weights",
        "equal unknown probability ties remain atomic",
        branch_id="unknown_probability_proper_scores",
        satisfies_target_branches=(
            "unknown_probability_brier",
            "unknown_probability_nll",
        ),
    ),
)

for _ordinal, _selector_key, _selector, _denominator in (
    (1, "ood_auroc", lambda r: r.overall.auroc, "known-OOD weighted pairs"),
    (2, "ood_auprc", lambda r: r.overall.auprc, "weighted OOD examples"),
    (
        3,
        "fpr_at_95_tpr",
        lambda r: r.overall.fpr_at_95_tpr,
        "known and OOD examples; both classes required",
    ),
    (
        4,
        "tpr_at_frozen_low_fpr",
        lambda r: r.overall.tpr_at_frozen_low_fpr,
        "known and OOD examples; both classes required",
    ),
    (
        5,
        "selective_risk_coverage_aurc",
        lambda r: {
            "aurc": r.overall.risk_coverage_aurc,
            "curve": r.overall.risk_coverage_curve,
        },
        "all examples retained in coverage denominator",
    ),
    (
        6,
        "known_case_coverage",
        lambda r: r.overall.known_case_coverage,
        "known-case weight",
    ),
    (7, "ood_abstention", lambda r: r.overall.ood_abstention_rate, "OOD-case weight"),
    (
        9,
        "ood_unsafe_nonabstain_regret",
        lambda r: {
            "rate": r.overall.unsafe_nonabstain_rate,
            "mean_regret": r.overall.nonabstain_ood_mean_regret,
            "max_regret": r.overall.nonabstain_ood_max_regret,
        },
        "OOD-case weight for unsafe rate; non-abstaining OOD weight for regret",
    ),
):
    _bind(
        "M07",
        _ordinal,
        _spec(
            FormulaImplementationKey.M07_OOD,
            _selector_key,
            _selector,
            _denominator,
            "equal unknown probability ties remain atomic",
            satisfies_target_branches=(
                ("risk_coverage_curve", "aurc")
                if _ordinal == 5
                else (
                    ("ood_treatment_regret", "unsafe_nonabstain_rate")
                    if _ordinal == 9
                    else None
                )
            ),
        ),
    )

for _ordinal, _selector_key, _selector, _denominator in (
    (
        1,
        "state_leak_rate",
        lambda r: r.overall.state_leak_rate,
        "exact-identical-prefix probe weight",
    ),
    (
        2,
        "prediction_leak_rate",
        lambda r: r.overall.prediction_leak_rate,
        "exact-identical-prefix probe weight",
    ),
    (
        3,
        "max_preavailability_output_divergence",
        lambda r: r.overall.max_preavailability_output_divergence,
        "exact-identical-prefix probes",
    ),
    (
        4,
        "boundary_error_count",
        lambda r: {
            "count": r.overall.boundary_error_count,
            "weight": r.overall.boundary_error_weight,
            "exposure": r.overall.boundary_exposure_count,
        },
        "boundary probes",
    ),
    (
        5,
        "old_cut_instability_count",
        lambda r: {
            "count": r.overall.old_cut_instability_count,
            "weight": r.overall.old_cut_instability_weight,
            "exposure": r.overall.old_cut_exposure_count,
        },
        "complete old-cut probes",
    ),
):
    _bind(
        "M08",
        _ordinal,
        _spec(
            FormulaImplementationKey.M08_TEMPORAL_LEAK,
            _selector_key,
            _selector,
            _denominator,
            "exact canonical byte equality",
        ),
    )

for _ordinal, _task in enumerate(("diagnosis", "natural_forecast", "intervention"), 1):
    _bind(
        "M09",
        _ordinal,
        _spec(
            FormulaImplementationKey.M09_SAMPLE_EFFICIENCY,
            f"{_task}_curve",
            lambda r, task=_task: _curve(r, task),
            "six frozen train-fraction points within one task",
            satisfies_target_branches=(
                f"{_task}_learning_curve",
                f"{_task}_log_sample_auc",
            ),
        ),
    )
_bind(
    "M09",
    4,
    _spec(
        FormulaImplementationKey.M09_SAMPLE_EFFICIENCY,
        "frozen_fraction_slices",
        lambda r: tuple(
            (curve.task, curve.fractions_percent, curve.train_examples)
            for curve in r.task_curves
        ),
        "three tasks times six train fractions",
    ),
)

for _ordinal, _stratum in enumerate(
    (
        "heldout_mechanism_combination",
        "heldout_host_modifier",
        "heldout_nonlinear_comorbidity",
    ),
    1,
):
    _bind(
        "M10",
        _ordinal,
        _spec(
            FormulaImplementationKey.M10_GENERALIZATION,
            f"{_stratum}_gap",
            lambda r, stratum=_stratum: _gap(r, stratum),
            "explicit matched heldout-seen pairs within the named stratum",
        ),
    )

for _ordinal, _selector_key, _selector in (
    (1, "migration_flags", lambda r: _extension_projection(r, "migration_flags")),
    (2, "retrain_examples", lambda r: _extension_projection(r, "retrain_examples")),
    (3, "artifact_delta_bytes", lambda r: _extension_projection(r, "artifact_bytes")),
    (4, "core_diff", lambda r: _extension_projection(r, "core_diff")),
    (
        5,
        "old_benchmark_regression",
        lambda r: _extension_projection(r, "old_benchmark_regression"),
    ),
    (
        6,
        "hard_extensibility_failure",
        lambda r: _extension_projection(r, "hard_extensibility_failure"),
    ),
):
    _bind(
        "M11",
        _ordinal,
        _spec(
            FormulaImplementationKey.M11_EXTENSION_COST,
            _selector_key,
            _selector,
            "caller-produced extension observation rows",
            undefined="collector rejects malformed evidence; collection itself is not independently trusted",
            satisfies_target_branches=(
                ("core_diff_loc", "core_diff_changed_files") if _ordinal == 4 else None
            ),
        ),
    )


for _ordinal, _selector_key, _selector, _branch_id, _satisfied, _denominator in (
    (
        1,
        "canonical_json_raw_bytes_by_record",
        lambda r: _state_row_projection(r, "canonical_state_raw_bytes"),
        "canonical_json_raw_bytes",
        ("canonical_json_raw_bytes",),
        "caller-provided JSON state rows",
    ),
    (
        2,
        "canonical_json_compressed_bytes_by_record",
        lambda r: _state_row_projection(
            r, "canonical_state_compressed_bytes_auxiliary"
        ),
        "canonical_json_compressed_bytes",
        ("canonical_json_compressed_bytes",),
        "caller-provided JSON state rows under the code-owned compressor",
    ),
    (
        3,
        "caller_asserted_component_counts_by_record",
        lambda r: _state_row_projection(r, "component_counts"),
        "caller_asserted_component_counts",
        ("scalar_count", "node_count", "edge_count", "particle_count"),
        "caller-provided state rows; component count authority remains unverified",
    ),
    (
        4,
        "canonical_json_history_length_ols_by_matched_grain",
        lambda r: r.history_length_slopes,
        "canonical_json_history_length_ols",
        ("canonical_json_history_length_ols",),
        "matched JSON-state grains with at least two distinct history lengths for a defined slope",
    ),
    (
        5,
        "canonical_json_task_horizon_slices",
        lambda r: r.task_horizon_slices,
        "canonical_json_task_horizon_slices",
        ("canonical_json_task_horizon_slices",),
        "caller-provided JSON state rows grouped by exact task and horizon",
    ),
):
    _bind(
        "M12",
        _ordinal,
        _spec(
            FormulaImplementationKey.M12_STATE_SIZE,
            _selector_key,
            _selector,
            _denominator,
            "retain_all_equal_rows",
            "reject_malformed_rows; undefined_ols_is_typed_with_reason",
            branch_id=_branch_id,
            satisfies_target_branches=_satisfied,
        ),
    )

for _ordinal, _selector_key, _selector, _satisfied, _denominator in (
    (
        1,
        "cold_latency_by_operation",
        lambda r: r.cold_latency,
        (
            "initialize_latency_distribution",
            "update_latency_distribution",
            "diagnose_latency_distribution",
            "rollout_latency_distribution",
        ),
        "caller-provided cold-process measurements for every code-owned operation",
    ),
    (
        2,
        "peak_rss",
        lambda r: _resource_projection(r, ResourceKind.PEAK_RSS),
        ("peak_rss",),
        "caller-provided peak RSS measurement",
    ),
    (
        3,
        "peak_gpu_memory",
        lambda r: _resource_projection(r, ResourceKind.PEAK_GPU_MEMORY),
        ("peak_gpu_memory",),
        "caller-provided peak GPU memory measurement",
    ),
    (
        4,
        "model_artifact_bytes",
        lambda r: _resource_projection(r, ResourceKind.MODEL_ARTIFACT_BYTES),
        ("model_artifact_bytes",),
        "caller-provided model artifact byte measurement",
    ),
    (
        5,
        "train_flops_and_wall_time",
        lambda r: _resource_projection(
            r, ResourceKind.TRAIN_FLOPS, ResourceKind.TRAIN_WALL_TIME
        ),
        ("train_flops", "train_wall_time"),
        "caller-provided training FLOP and wall-time measurements",
    ),
    (
        6,
        "postseal_worker_resources",
        lambda r: _resource_projection(
            r,
            ResourceKind.POSTSEAL_WORKER_WALL_TIME,
            ResourceKind.POSTSEAL_WORKER_PEAK_RSS,
            ResourceKind.POSTSEAL_WORKER_PEAK_GPU_MEMORY,
        ),
        (
            "postseal_worker_wall_time",
            "postseal_worker_peak_rss",
            "postseal_worker_peak_gpu_memory",
        ),
        "caller-provided post-seal worker wall-time, RSS, and GPU measurements",
    ),
):
    _bind(
        "M13",
        _ordinal,
        _spec(
            FormulaImplementationKey.M13_RESOURCE,
            _selector_key,
            _selector,
            _denominator,
            "retain_equal_measurements_and_apply_HF7_latency_quantiles",
            "null_with_reason_and_zero_defined_exposure",
            satisfies_target_branches=_satisfied,
        ),
    )

for _ordinal, _selector_key, _selector, _satisfied, _denominator in (
    (
        1,
        "replicate_mean",
        lambda r: r.candidate_summary["mean"],
        ("replicate_mean",),
        "exactly five seed-protocol zipped replicate values",
    ),
    (
        2,
        "sample_standard_deviation",
        lambda r: r.candidate_summary["sample_sd"],
        ("sample_standard_deviation",),
        "exactly five seed-protocol zipped replicate values with ddof=1",
    ),
    (
        3,
        "replicate_minimum_and_maximum",
        lambda r: {
            "minimum": r.candidate_summary["min"],
            "maximum": r.candidate_summary["max"],
        },
        ("replicate_minimum", "replicate_maximum"),
        "exactly five seed-protocol zipped replicate values",
    ),
    (
        4,
        "student_t_df4_ci95",
        lambda r: {
            "lower": r.candidate_summary["ci95_lower"],
            "upper": r.candidate_summary["ci95_upper"],
        },
        ("student_t_ci95_lower", "student_t_ci95_upper"),
        "five replicate-level fixed-world macros under Student-t df=4",
    ),
    (
        5,
        "paired_same_index_delta_student_t_df4_ci95",
        lambda r: {
            "lower": r.paired_summary["ci95_lower"],
            "upper": r.paired_summary["ci95_upper"],
        },
        ("paired_delta_ci95_lower", "paired_delta_ci95_upper"),
        "five same-index zipped candidate-minus-baseline deltas",
    ),
):
    _bind(
        "M14",
        _ordinal,
        _spec(
            FormulaImplementationKey.M14_STABILITY,
            _selector_key,
            _selector,
            _denominator,
            "retain_equal_replicates_and_zero_variance",
            "reject_nonfive_or_unpaired_input",
            satisfies_target_branches=_satisfied,
        ),
    )

for _ordinal, _selector_key, _selector, _satisfied, _denominator in (
    (
        1,
        "incremental_replay_exact_identity",
        lambda r: r.incremental_replay,
        ("state_hash_match", "payload_bytes_match"),
        "caller-provided update observations at exact evaluation grain",
    ),
    (
        2,
        "batch_sequential_behavioral_identity",
        lambda r: r.batch_sequential,
        ("batch_sequential_behavioral_match",),
        "caller-provided update observations at exact evaluation grain",
    ),
    (
        3,
        "query_order_purity",
        lambda r: r.query_order_purity,
        (
            "same_start_state_hash",
            "same_start_payload_bytes",
            "first_order_state_unchanged",
            "second_order_state_unchanged",
            "per_query_outputs_equal",
        ),
        "caller-provided two-order query observations at exact evaluation grain",
    ),
    (
        4,
        "oracle_relative_directional_changes",
        lambda r: r.oracle_directional_changes,
        (
            "informative_observation_diagnosis",
            "informative_observation_rollout",
            "informative_treatment_response_diagnosis",
            "informative_treatment_response_rollout",
            "no_information_control_disposition",
        ),
        "caller-provided score changes by information kind and readout kind",
    ),
):
    _bind(
        "M15",
        _ordinal,
        _spec(
            FormulaImplementationKey.M15_UPDATE_CONSISTENCY,
            _selector_key,
            _selector,
            _denominator,
            "exact_canonical_identity_or_explicit_score_direction",
            "reject_malformed_or_duplicate_grains",
            satisfies_target_branches=_satisfied,
        ),
    )

for _ordinal, _selector_key, _selector, _branch_id, _satisfied, _denominator in (
    (
        1,
        "postseal_new_readout_score_by_readout",
        lambda r: _readout_projection(r, "postseal_new_readout_score"),
        "caller_asserted_score",
        ("caller_asserted_score",),
        "caller-reported readout cards with nonempty score curves",
    ),
    (
        2,
        "postseal_new_readout_sample_efficiency_by_readout",
        lambda r: _readout_fields_projection(
            r,
            "postseal_new_readout_sample_efficiency",
            "curve_points",
        ),
        "caller_asserted_sample_efficiency_curve",
        ("caller_asserted_sample_efficiency_curve",),
        "caller-reported readout curves and target score",
    ),
    (
        3,
        "postseal_history_baseline_gap_by_readout",
        lambda r: _readout_fields_projection(
            r,
            "postseal_new_readout_score",
            "curve_points",
            "postseal_history_baseline_gap",
            "score_direction",
            "state_only_vs_history_interpretation",
        ),
        "caller_asserted_state_history_gap",
        ("caller_asserted_state_history_gap",),
        "caller-reported state-only and history scores on a claimed common curve basis",
    ),
    (
        4,
        "caller_asserted_history_input_shape_by_readout",
        lambda r: tuple(
            {
                "readout_id": row["readout_id"],
                "value": {
                    "includes_raw_history": row[
                        "caller_asserted_input_shape_includes_raw_history"
                    ],
                    "protocol_shape_violation_facts": row[
                        "protocol_shape_violation_facts"
                    ],
                },
            }
            for row in r.readouts
        ),
        "caller_asserted_input_shape_signal",
        ("caller_asserted_input_shape_signal",),
        "caller-reported readout input enums and protocol-shape facts",
    ),
):
    _bind(
        "M16",
        _ordinal,
        _spec(
            FormulaImplementationKey.M16_NOVEL_READOUT,
            _selector_key,
            _selector,
            _denominator,
            "readout_id_ascending",
            "formal_eligibility_and_independent_trace_proof_remain_unavailable",
            branch_id=_branch_id,
            satisfies_target_branches=_satisfied,
        ),
    )


def _freeze_code_owned_manifest() -> CodeOwnedBindingManifest:
    frozen_adapters = {
        key: FrozenFormulaAdapter(
            function=adapter.function,
            invoke_known_answer=adapter.invoke_known_answer,
            expected_result_type=adapter.expected_result_type,
            source_path=adapter.source_path,
            input_type_contract=adapter.input_type_contract,
            known_answer_parameter_preimage_bytes=canonical_json_bytes(
                adapter.known_answer_parameter_preimage
            ),
            formula_family=adapter.formula_family,
        )
        for key, adapter in _ADAPTER_BUILDERS.items()
    }
    return CodeOwnedBindingManifest(
        adapters=MappingProxyType(frozen_adapters),
        target_bindings=MappingProxyType(dict(_TARGET_BINDING_BUILDERS)),
        required_branches=MappingProxyType(dict(_TARGET_REQUIRED_BRANCH_BUILDERS)),
        untrusted_targets=frozenset(_UNTRUSTED_TARGET_BUILDERS),
    )


_CODE_OWNED_MANIFEST = _freeze_code_owned_manifest()
_ADAPTERS = _CODE_OWNED_MANIFEST.adapters
_TARGET_BINDINGS = _CODE_OWNED_MANIFEST.target_bindings
_TARGET_REQUIRED_BRANCHES = _CODE_OWNED_MANIFEST.required_branches
_UNTRUSTED_TARGETS = _CODE_OWNED_MANIFEST.untrusted_targets
# Retire every import-time builder into the immutable manifest view.  Keeping
# the names defined prevents late-bound helper functions from seeing a deleted
# global, while any attempted post-import mutation now fails closed.
_ADAPTER_BUILDERS = _CODE_OWNED_MANIFEST.adapters  # type: ignore[assignment]
_TARGET_BINDING_BUILDERS = _CODE_OWNED_MANIFEST.target_bindings  # type: ignore[assignment]
_TARGET_REQUIRED_BRANCH_BUILDERS = _CODE_OWNED_MANIFEST.required_branches  # type: ignore[assignment]
_UNTRUSTED_TARGET_BUILDERS = _CODE_OWNED_MANIFEST.untrusted_targets


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _read_source_bytes(path: str) -> bytes:
    candidate = (_repo_root() / Path(path)).resolve()
    if _repo_root() not in candidate.parents:
        raise ProtocolViolation("metric binding source path escapes repository root")
    try:
        return candidate.read_bytes()
    except OSError as exc:
        raise ProtocolViolation(f"metric binding source is unreadable: {path}") from exc


def _capture_import_source_digests(
    source_paths: tuple[str, ...],
) -> dict[str, str]:
    return {path: digest_bytes(_read_source_bytes(path)) for path in source_paths}


_IMPORTED_SOURCE_DIGESTS = MappingProxyType(
    _capture_import_source_digests(_SOURCE_PATHS)
)
_CODE_OWNED_CONTROL_PLANE = CodeOwnedControlPlane(
    manifest=_CODE_OWNED_MANIFEST,
    source_paths=_SOURCE_PATHS,
    always_remaining_blockers=_ALWAYS_REMAINING_BLOCKERS,
    remaining_global_gaps=_REMAINING_GLOBAL_GAPS,
    imported_source_digests=_IMPORTED_SOURCE_DIGESTS,
    schema_version=SCHEMA_VERSION,
    benchmark_id=BENCHMARK_ID,
    benchmark_status=BENCHMARK_STATUS,
    authority_claim=AUTHORITY_CLAIM,
    evaluator_binding=EVALUATOR_BINDING,
    freeze_authority=FREEZE_AUTHORITY,
    aggregate_score=AGGREGATE_SCORE,
    target_object_domain=TARGET_OBJECT_DOMAIN,
    source_closure_domain=SOURCE_CLOSURE_DOMAIN,
    binding_set_domain=BINDING_SET_DOMAIN,
    artifact_domain=ARTIFACT_DOMAIN,
)
_IMPORTED_CONTROL_PLANE_ATTESTATION_BYTES = _control_plane_attestation_bytes(
    _CODE_OWNED_CONTROL_PLANE
)
_IMPORTED_CONTROL_PLANE_ATTESTATION_DIGEST = digest_bytes(
    _IMPORTED_CONTROL_PLANE_ATTESTATION_BYTES
)


def _live_control_plane() -> CodeOwnedControlPlane:
    return CodeOwnedControlPlane(
        manifest=_CODE_OWNED_MANIFEST,
        source_paths=_SOURCE_PATHS,
        always_remaining_blockers=_ALWAYS_REMAINING_BLOCKERS,
        remaining_global_gaps=_REMAINING_GLOBAL_GAPS,
        imported_source_digests=_IMPORTED_SOURCE_DIGESTS,
        schema_version=SCHEMA_VERSION,
        benchmark_id=BENCHMARK_ID,
        benchmark_status=BENCHMARK_STATUS,
        authority_claim=AUTHORITY_CLAIM,
        evaluator_binding=EVALUATOR_BINDING,
        freeze_authority=FREEZE_AUTHORITY,
        aggregate_score=AGGREGATE_SCORE,
        target_object_domain=TARGET_OBJECT_DOMAIN,
        source_closure_domain=SOURCE_CLOSURE_DOMAIN,
        binding_set_domain=BINDING_SET_DOMAIN,
        artifact_domain=ARTIFACT_DOMAIN,
    )


def _attest_code_owned_control_plane(
    control: CodeOwnedControlPlane,
    expected_bytes: bytes,
    expected_digest: str,
) -> None:
    try:
        sealed_current = _control_plane_attestation_bytes(control)
        live_current = _control_plane_attestation_bytes(_live_control_plane())
    except Exception as exc:
        raise ProtocolViolation(
            "metric binding code-owned control plane changed after import"
        ) from exc
    if (
        _CODE_OWNED_CONTROL_PLANE is not control
        or _IMPORTED_CONTROL_PLANE_ATTESTATION_BYTES is not expected_bytes
        or _IMPORTED_CONTROL_PLANE_ATTESTATION_DIGEST != expected_digest
        or _CODE_OWNED_MANIFEST is not control.manifest
        or _SOURCE_PATHS is not control.source_paths
        or _ALWAYS_REMAINING_BLOCKERS is not control.always_remaining_blockers
        or _REMAINING_GLOBAL_GAPS is not control.remaining_global_gaps
        or _IMPORTED_SOURCE_DIGESTS is not control.imported_source_digests
        or sealed_current != expected_bytes
        or live_current != expected_bytes
        or digest_bytes(sealed_current) != expected_digest
        or digest_bytes(live_current) != expected_digest
    ):
        raise ProtocolViolation(
            "metric binding code-owned control plane changed after import"
        )


def _fresh_source_closure(
    control: CodeOwnedControlPlane,
) -> tuple[list[dict[str, Any]], str]:
    entries: list[dict[str, Any]] = []
    for path in control.source_paths:
        raw = _read_source_bytes(path)
        fresh = digest_bytes(raw)
        if control.imported_source_digests.get(path) != fresh:
            raise ProtocolViolation(
                f"loaded metric binding source differs from live bytes: {path}"
            )
        entries.append({"path": path, "byte_count": len(raw), "artifact_digest": fresh})
    closure_bytes = canonical_json_bytes(entries)
    digest = hashlib.sha256(control.source_closure_domain + closure_bytes).hexdigest()
    return entries, "sha256:" + digest


def _callable_identity(
    key: FormulaImplementationKey, adapter: FrozenFormulaAdapter
) -> dict[str, str]:
    function = adapter.function
    if not inspect.isfunction(function):
        raise ProtocolViolation(f"{key.value} adapter does not hold a Python function")
    source = inspect.getsourcefile(function)
    if source is None:
        raise ProtocolViolation(f"{key.value} callable has no inspectable source")
    relative = Path(source).resolve().relative_to(_repo_root()).as_posix()
    if relative != adapter.source_path:
        raise ProtocolViolation(f"{key.value} callable source path is not code-owned")
    return {
        "module": function.__module__,
        "qualname": function.__qualname__,
        "signature": str(inspect.signature(function)),
        "source_path": relative,
    }


def _wire_value(value: object) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _wire_value(getattr(value, field.name))
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Enum):
        return value.value
    if type(value) is bytes:
        return {"bytes_sha256": digest_bytes(value), "byte_count": len(value)}
    if type(value) is tuple:
        return [_wire_value(item) for item in value]
    if type(value) is list:
        return [_wire_value(item) for item in value]
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ProtocolViolation(
                "known-answer selector dictionary keys must be strings"
            )
        return {key: _wire_value(item) for key, item in value.items()}
    if value is None or type(value) in {str, int, float, bool}:
        if type(value) is float and not math.isfinite(value):
            raise ProtocolViolation("known-answer selector produced non-finite output")
        return value
    raise ProtocolViolation(
        f"known-answer selector produced unsupported type {type(value)!r}"
    )


def _typed_name(value: object) -> str:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return f"{type(value).__module__}.{type(value).__qualname__}"
    if isinstance(value, Enum):
        return f"{type(value).__module__}.{type(value).__qualname__}"
    if type(value) is tuple:
        members = sorted({_typed_name(item) for item in value})
        return "tuple[" + "|".join(members or ["empty"]) + "]"
    if type(value) is dict:
        return "dict[str,typed_value]"
    if type(value) is list:
        return "list[typed_value]"
    return type(value).__name__


def _target_object_digest(target_wire: dict[str, Any], domain: bytes) -> str:
    raw = canonical_json_bytes(target_wire)
    return "sha256:" + hashlib.sha256(domain + raw).hexdigest()


def _known_answer(
    branch: FormulaBranchBindingSpec,
    adapters: Mapping[FormulaImplementationKey, FrozenFormulaAdapter],
) -> dict[str, Any]:
    key = branch.implementation_key
    adapter = adapters[key]
    identity = _callable_identity(key, adapter)
    result = adapter.invoke_known_answer()
    if type(result) is not adapter.expected_result_type:
        raise ProtocolViolation(f"{key.value} known-answer returned a wrong exact type")
    selected = branch.selector(result)
    selected_wire = _wire_value(selected)
    validate_json_like(selected_wire, path=f"{key.value} known-answer selected output")
    return {
        "branch_id": branch.branch_id,
        "satisfies_target_branches": list(branch.satisfies_target_branches),
        "implementation_key": key.value,
        "callable_identity": identity,
        "input_type_contract": adapter.input_type_contract,
        "callable_output_type": f"{adapter.expected_result_type.__module__}.{adapter.expected_result_type.__qualname__}",
        "selector_key": branch.selector_key,
        "selector_output_type": _typed_name(selected),
        "denominator_contract": branch.denominator_contract,
        "tie_policy": branch.tie_policy,
        "undefined_disposition": branch.undefined_disposition,
        "formula_contract": {
            "family": adapter.formula_family,
            "version": "source-bound-runtime-v1",
            "status": "executable_primitive_not_semantically_closed",
        },
        "formula_parameter_preimage": json.loads(
            adapter.known_answer_parameter_preimage_bytes
        ),
        "known_answer_selected_output_cardinality": (
            len(selected) if type(selected) in {tuple, list, dict} else None
        ),
        "known_answer_selected_output_digest": digest_bytes(
            canonical_json_bytes(selected_wire)
        ),
    }


def _shared_branch_contract(
    branches: tuple[FormulaBranchBindingSpec, ...], field: str
) -> str:
    values = tuple(dict.fromkeys(getattr(branch, field) for branch in branches))
    return values[0] if len(values) == 1 else "branch_specific_see_implementations"


def _code_owned_wire(
    target_registry_bytes: bytes,
    _control: CodeOwnedControlPlane = _CODE_OWNED_CONTROL_PLANE,
    _expected_attestation_bytes: bytes = _IMPORTED_CONTROL_PLANE_ATTESTATION_BYTES,
    _expected_attestation_digest: str = _IMPORTED_CONTROL_PLANE_ATTESTATION_DIGEST,
    _attest: Callable[
        [CodeOwnedControlPlane, bytes, str], None
    ] = _attest_code_owned_control_plane,
) -> dict[str, Any]:
    _attest(_control, _expected_attestation_bytes, _expected_attestation_digest)
    manifest = _control.manifest
    if (
        _CODE_OWNED_MANIFEST is not manifest
        or _ADAPTERS is not manifest.adapters
        or _TARGET_BINDINGS is not manifest.target_bindings
        or _TARGET_REQUIRED_BRANCHES is not manifest.required_branches
        or _UNTRUSTED_TARGETS is not manifest.untrusted_targets
    ):
        raise ProtocolViolation("metric binding manifest aliases changed after import")
    registry = parse_metric_target_registry_bytes(target_registry_bytes)
    source_closure, source_closure_digest = _fresh_source_closure(_control)
    expected_keys = {
        (contract.measurement_id, ordinal)
        for contract in registry.measurement_contracts
        for ordinal, _ in enumerate(contract.outputs, 1)
    }
    if not set(manifest.required_branches).issubset(expected_keys):
        raise ProtocolViolation("metric branch requirements name an unknown target")
    if not set(manifest.target_bindings).issubset(expected_keys):
        raise ProtocolViolation("metric runtime bindings name an unknown target")
    if not manifest.untrusted_targets.issubset(expected_keys):
        raise ProtocolViolation(
            "metric untrusted target directory names an unknown target"
        )
    if not manifest.untrusted_targets.issubset(manifest.target_bindings):
        raise ProtocolViolation(
            "metric untrusted target directory names an unbound target"
        )
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    for contract in registry.measurement_contracts:
        for ordinal, output in enumerate(contract.outputs, 1):
            join_key = (contract.measurement_id, ordinal)
            if join_key in seen:
                raise ProtocolViolation(
                    "metric binding target join keys are not unique"
                )
            seen.add(join_key)
            target_wire = output.to_wire()
            spec = manifest.target_bindings.get(join_key)
            required_branches = manifest.required_branches.get(
                join_key, ("complete_target",)
            )
            if (
                type(required_branches) is not tuple
                or not required_branches
                or any(type(item) is not str or not item for item in required_branches)
                or len(set(required_branches)) != len(required_branches)
            ):
                raise ProtocolViolation("metric target branch requirements are invalid")
            status = RuntimeBindingStatus.UNIMPLEMENTED
            implementations: list[dict[str, Any]] = []
            implemented_branches: list[str] = []
            missing_branches = list(required_branches)
            denominator = None
            tie_policy = None
            undefined = None
            gaps = list(_control.remaining_global_gaps)
            blockers = set(_control.always_remaining_blockers)
            blockers.update(contract.blocker_codes)
            if spec is not None:
                if type(spec.branches) is not tuple or not spec.branches:
                    raise ProtocolViolation("metric target binding requires branches")
                branch_ids: set[str] = set()
                satisfied: set[str] = set()
                for branch in spec.branches:
                    if type(branch) is not FormulaBranchBindingSpec:
                        raise ProtocolViolation(
                            "metric target branch must be code-owned"
                        )
                    if (
                        type(branch.branch_id) is not str
                        or not branch.branch_id
                        or branch.branch_id in branch_ids
                    ):
                        raise ProtocolViolation(
                            "metric implementation branch ids are invalid"
                        )
                    branch_ids.add(branch.branch_id)
                    if type(branch.implementation_key) is not FormulaImplementationKey:
                        raise ProtocolViolation(
                            "metric implementation key must be a code-owned enum"
                        )
                    if (
                        type(branch.satisfies_target_branches) is not tuple
                        or not branch.satisfies_target_branches
                        or any(
                            type(item) is not str or not item
                            for item in branch.satisfies_target_branches
                        )
                        or len(set(branch.satisfies_target_branches))
                        != len(branch.satisfies_target_branches)
                        or not set(branch.satisfies_target_branches).issubset(
                            required_branches
                        )
                    ):
                        raise ProtocolViolation(
                            "metric implementation satisfies unknown/invalid target branches"
                        )
                    satisfied.update(branch.satisfies_target_branches)
                    implementations.append(_known_answer(branch, manifest.adapters))
                implemented_branches = [
                    branch for branch in required_branches if branch in satisfied
                ]
                missing_branches = [
                    branch for branch in required_branches if branch not in satisfied
                ]
                denominator = _shared_branch_contract(
                    spec.branches, "denominator_contract"
                )
                tie_policy = _shared_branch_contract(spec.branches, "tie_policy")
                undefined = _shared_branch_contract(
                    spec.branches, "undefined_disposition"
                )
                if missing_branches:
                    status = RuntimeBindingStatus.PARTIAL_FORMULA_COVERAGE_UNBOUND
                    gaps.insert(0, "complete_formula_branch_coverage")
                elif join_key in manifest.untrusted_targets:
                    status = RuntimeBindingStatus.PARTIAL_UNTRUSTED_COLLECTOR
                else:
                    status = RuntimeBindingStatus.FORMULA_EXECUTABLE_UNBOUND
                if join_key in manifest.untrusted_targets:
                    gaps.extend(
                        (
                            "independent_trusted_input_collector",
                            "closed_expected_exposure_registry",
                        )
                    )
                    if contract.measurement_id == "M11":
                        gaps.extend(
                            (
                                "independent_extension_collector",
                                "trusted_runtime_resource_measurement",
                            )
                        )
                    elif contract.measurement_id == "M12":
                        gaps.extend(
                            (
                                "bound_harness_state_custody",
                                "verified_component_count_collector",
                            )
                        )
                    elif contract.measurement_id == "M13":
                        gaps.append("trusted_runtime_resource_measurement")
                    elif contract.measurement_id == "M15":
                        gaps.append("bound_update_query_score_evidence_roots")
                    elif contract.measurement_id == "M16":
                        gaps.append(
                            "formal_novel_readout_eligibility_and_independent_trace_custody"
                        )
                    blockers.add("UCM-METRIC-B005")
            else:
                gaps.insert(0, "code_owned_callable_and_typed_selector")
            records.append(
                {
                    "measurement_id": contract.measurement_id,
                    "ordinal": ordinal,
                    "metric_id": output.metric_id,
                    "target_object_digest": _target_object_digest(
                        target_wire, _control.target_object_domain
                    ),
                    "runtime_binding_status": status.value,
                    "required_branches": list(required_branches),
                    "implemented_branches": implemented_branches,
                    "missing_branches": missing_branches,
                    "implementations": implementations,
                    "denominator_contract": denominator,
                    "task_applicability": None,
                    "world_panel_applicability": None,
                    "aggregation_hierarchy": None,
                    "evaluator_runtime_environment": None,
                    "tie_policy": tie_policy,
                    "undefined_disposition": undefined,
                    "remaining_semantic_gaps": gaps,
                    "remaining_blocker_codes": sorted(blockers),
                    "closed_definition_claimed": False,
                }
            )
    if seen != expected_keys or len(records) != 111:
        raise ProtocolViolation(
            "metric binding coverage is not exactly 111 target objects"
        )
    coverage = {
        status.value: sum(
            item["runtime_binding_status"] == status.value for item in records
        )
        for status in RuntimeBindingStatus
    }
    preimage = {
        "schema_version": _control.schema_version,
        "benchmark_id": _control.benchmark_id,
        "benchmark_status": _control.benchmark_status,
        "authority_claim": _control.authority_claim,
        "evaluator_binding": _control.evaluator_binding,
        "freeze_authority": _control.freeze_authority,
        "single_aggregate_score": _control.aggregate_score,
        "semantic_metric_config_ready": False,
        "closed_target_count": 0,
        "target_count": len(records),
        "coverage": coverage,
        "target_registry_binding": {
            "artifact_digest": metric_target_artifact_digest_from_bytes(
                target_registry_bytes
            ),
            "metric_target_digest": metric_target_digest_from_bytes(
                target_registry_bytes
            ),
            "byte_count": len(target_registry_bytes),
            "join": "measurement_id+one_based_ordinal+domain_separated_exact_target_object_digest",
        },
        "source_closure": source_closure,
        "source_closure_digest": source_closure_digest,
        "target_records": records,
        "remaining_global_blockers": list(_control.always_remaining_blockers),
    }
    binding_set_digest = (
        "sha256:"
        + hashlib.sha256(
            _control.binding_set_domain + canonical_json_bytes(preimage)
        ).hexdigest()
    )
    _attest(_control, _expected_attestation_bytes, _expected_attestation_digest)
    return {**preimage, "binding_set_digest": binding_set_digest}


_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "benchmark_id",
        "benchmark_status",
        "authority_claim",
        "evaluator_binding",
        "freeze_authority",
        "single_aggregate_score",
        "semantic_metric_config_ready",
        "closed_target_count",
        "target_count",
        "coverage",
        "target_registry_binding",
        "source_closure",
        "source_closure_digest",
        "target_records",
        "remaining_global_blockers",
        "binding_set_digest",
    }
)


def _decode_exact_canonical_object(payload: object) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation("metric runtime bindings must be exact bytes")

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolViolation(
                    f"metric runtime bindings contain duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        text = payload.decode("utf-8", errors="strict")
        value = json.loads(text, object_pairs_hook=reject_duplicates)
    except ProtocolViolation:
        raise
    except (
        UnicodeDecodeError,
        json.JSONDecodeError,
        RecursionError,
        ValueError,
    ) as exc:
        raise ProtocolViolation(
            "metric runtime bindings are not strict canonical JSON"
        ) from exc
    if type(value) is not dict:
        raise ProtocolViolation("metric runtime bindings must encode an exact object")
    validate_json_like(value, path="metric runtime bindings")
    if canonical_json_bytes(value) != payload:
        raise ProtocolViolation(
            "metric runtime binding bytes are not canonical sorted compact JSON plus one LF"
        )
    if frozenset(value) != _TOP_LEVEL_KEYS:
        raise ProtocolViolation(
            "metric runtime bindings have missing or extra top-level fields"
        )
    return value


@dataclass(frozen=True, slots=True)
class MetricRuntimeBindings:
    canonical_bytes: bytes
    target_registry_bytes: bytes

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def binding_artifact_digest(self) -> str:
        return (
            "sha256:"
            + hashlib.sha256(ARTIFACT_DOMAIN + self.canonical_bytes).hexdigest()
        )

    def to_wire(self) -> dict[str, Any]:
        return json.loads(self.canonical_bytes)


def benchmark_v1_metric_runtime_bindings(
    target_registry_bytes: bytes | None = None,
) -> MetricRuntimeBindings:
    exact_target = (
        benchmark_v1_metric_target_registry().canonical_bytes
        if target_registry_bytes is None
        else target_registry_bytes
    )
    if type(exact_target) is not bytes:
        raise ProtocolViolation(
            "metric runtime binding target registry must be exact bytes"
        )
    wire = _code_owned_wire(exact_target)
    return MetricRuntimeBindings(canonical_json_bytes(wire), exact_target)


def parse_metric_runtime_bindings_bytes(
    payload: bytes, target_registry_bytes: bytes | None = None
) -> MetricRuntimeBindings:
    value = _decode_exact_canonical_object(payload)
    exact_target = (
        benchmark_v1_metric_target_registry().canonical_bytes
        if target_registry_bytes is None
        else target_registry_bytes
    )
    if type(exact_target) is not bytes:
        raise ProtocolViolation(
            "metric runtime binding target registry must be exact bytes"
        )
    expected = _code_owned_wire(exact_target)
    if value != expected:
        raise ProtocolViolation(
            "metric runtime bindings differ from fresh code-owned truth"
        )
    return MetricRuntimeBindings(payload, exact_target)
