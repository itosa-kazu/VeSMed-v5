"""PRE-FREEZE typed metric target registry for UCM benchmark v1.

This module owns an exact code-owned target preimage and its fail-closed
parser/digests.  It deliberately does *not* claim a complete semantic metric
configuration: unresolved formulas, applicability and reducers are represented
as typed target gaps.  It does not bind the target into the current evaluator,
issue a freeze, or alter legacy artifact verification.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    validate_json_like,
)


METRIC_TARGET_SCHEMA = "ucm-pre-freeze-metric-target-registry/1"
METRIC_TARGET_DOMAIN = b"UCM_PRE_FREEZE_METRIC_TARGET_V1\0"
METRIC_TARGET_BENCHMARK_ID = "UCM-BENCHMARK-v1"
METRIC_TARGET_REVISION = "PRE-FREEZE-metric-target-v1"
METRIC_TARGET_BENCHMARK_STATUS = "PRE-FREEZE"
METRIC_TARGET_AUTHORITY_CLAIM = "typed_metric_target_registry_only"
METRIC_TARGET_RUNTIME_BINDING = "not_bound_to_evaluator"
METRIC_TARGET_FREEZE_AUTHORITY = "not_claimed"
METRIC_TARGET_SEMANTIC_READY = False


class MetricRuntimeCoverage(str, Enum):
    PARTIAL_UNBOUND = "legacy_partial_unbound"
    NOT_IMPLEMENTED_UNBOUND = "not_implemented_unbound"
    ISOLATED_IMPLEMENTATION_UNBOUND = "isolated_implementation_unbound"


class MetricDefinitionStatus(str, Enum):
    CLOSED = "closed"
    UNRESOLVED_TARGET_GAP = "unresolved_target_gap"


class MetricHardGateRole(str, Enum):
    NOT_A_HARD_GATE = "not_a_hard_gate"
    CONDITIONAL_HARD_GATE_TARGET = "conditional_hard_gate_target"


OUTPUT_REQUIRED_DIMENSIONS = (
    "formula_id_and_version",
    "formula_parameter_preimage",
    "optimization_direction",
    "unit_and_normalization",
    "denominator_exposure_and_cohort",
    "task_world_panel_applicability",
    "aggregation_hierarchy",
    "tie_policy",
    "undefined_disposition",
)


_MEASUREMENT_TRUTH: tuple[
    tuple[str, str, tuple[str, ...], str, MetricRuntimeCoverage, tuple[str, ...]], ...
] = (
    (
        "M01",
        "diagnosis_accuracy_and_calibration",
        (
            "diagnostic_cross_entropy_nll",
            "multiclass_brier",
            "top1_accuracy",
            "topk_accuracy",
            "macro_recall",
            "equal_mass_ece_15",
            "classwise_ece_15",
            "reliability_bins_15",
            "empirical_interval_coverage_50_80_95",
        ),
        "proper_score_and_calibration_pareto",
        MetricRuntimeCoverage.PARTIAL_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B003"),
    ),
    (
        "M02",
        "natural_history_forecast_error",
        (
            "no_new_action_policy_slice",
            "continue_current_policy_slice",
            "continuous_crps",
            "oracle_scale_normalized_mae",
            "oracle_scale_normalized_rmse",
            "per_axis_error",
            "continuous_interval_coverage_50_80_95",
            "discrete_event_nll",
            "discrete_event_brier",
            "discrete_event_reliability",
            "joint_energy_or_world_declared_proper_score",
            "integrated_survival_brier_nll",
            "fixed_time_utility_distribution_error",
            "calibration_slope_intercept_by_horizon",
        ),
        "proper_score_pareto",
        MetricRuntimeCoverage.PARTIAL_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B003"),
    ),
    (
        "M03",
        "post_intervention_trajectory_error",
        (
            "intervention_trajectory_proper_score",
            "treatment_effect_error",
            "effect_sign_error",
            "policy_horizon_calibration_coverage",
            "pehe_ite_error_when_unit_identified",
            "identified_set_coverage_width_error",
            "identified_set_hausdorff_error",
            "identified_set_bound_error",
            "set_valued_optimal_actions",
            "uniformly_dominated_actions",
            "oracle_robust_regret_interval",
            "false_certainty_rate",
            "worst_policy_world_episode",
        ),
        "proper_score_and_safety_pareto",
        MetricRuntimeCoverage.PARTIAL_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B003"),
    ),
    (
        "M04",
        "treatment_selection_regret",
        (
            "raw_regret",
            "normalized_regret",
            "mean_median_p95_max_cvar95_regret",
            "catastrophic_action_rate",
            "robust_regret_bound_for_partial_identification",
            "set_valued_optimal_actions",
            "uniformly_dominated_actions",
            "oracle_robust_regret_interval",
            "false_certainty_rate",
            "descriptive_realization_regret",
            "w19_tail_mean_max_cvar95_catastrophic_rate",
        ),
        "tail_pareto_and_hard_gate",
        MetricRuntimeCoverage.PARTIAL_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B003"),
    ),
    (
        "M05",
        "state_collision_rate",
        (
            "raw_exact_collision_rate",
            "functional_near_collision_rate",
            "attributable_collision_rate",
            "attributable_dangerous_collision_events",
            "max_missed_oracle_distance",
            "pair_level_trajectories",
        ),
        "pareto_and_attributable_dangerous_hard_gate",
        MetricRuntimeCoverage.PARTIAL_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B003"),
    ),
    (
        "M06",
        "functional_false_split_rate",
        (
            "oracle_equivalent_pair_denominator",
            "functional_false_split_rate",
            "structural_redundancy_count",
            "max_spurious_candidate_distance",
            "pair_level_trajectories",
        ),
        "parsimony_pareto_not_hard_gate",
        MetricRuntimeCoverage.PARTIAL_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B003"),
    ),
    (
        "M07",
        "ood_unknown_recognition",
        (
            "ood_auroc",
            "ood_auprc",
            "fpr_at_95_tpr",
            "tpr_at_frozen_low_fpr",
            "selective_risk_coverage_aurc",
            "known_case_coverage",
            "ood_abstention",
            "unknown_probability_brier_nll_calibration",
            "ood_treatment_regret_unsafe_non_abstain_rate",
        ),
        "open_world_pareto_and_unsafe_forced_known_hard_gate",
        MetricRuntimeCoverage.PARTIAL_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B003"),
    ),
    (
        "M08",
        "temporal_leakage",
        (
            "state_leak_rate",
            "prediction_leak_rate",
            "max_preavailability_output_divergence",
            "boundary_error_count",
            "old_cut_instability_count",
        ),
        "exact_semantics_hard_gate",
        MetricRuntimeCoverage.PARTIAL_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B003"),
    ),
    (
        "M09",
        "sample_efficiency",
        (
            "diagnosis_learning_curve_log_sample_auc",
            "natural_forecast_learning_curve_log_sample_auc",
            "intervention_learning_curve_log_sample_auc",
            "frozen_train_fraction_slices_1_5_10_25_50_100_percent",
        ),
        "efficiency_pareto",
        MetricRuntimeCoverage.NOT_IMPLEMENTED_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B003", "UCM-METRIC-B004"),
    ),
    (
        "M10",
        "novel_mechanism_combination_generalization",
        (
            "heldout_mechanism_combination_gap",
            "heldout_host_modifier_gap",
            "heldout_nonlinear_comorbidity_gap",
        ),
        "generalization_pareto",
        MetricRuntimeCoverage.NOT_IMPLEMENTED_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B003", "UCM-METRIC-B004"),
    ),
    (
        "M11",
        "new_check_and_treatment_extension_cost",
        (
            "extension_model_state_schema_migration",
            "extension_retrain_examples",
            "extension_artifact_delta_bytes",
            "extension_core_diff_loc_changed_files",
            "extension_old_benchmark_regression",
            "hard_extensibility_failure",
        ),
        "extension_cost_pareto",
        MetricRuntimeCoverage.NOT_IMPLEMENTED_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B005"),
    ),
    (
        "M12",
        "state_dimension_or_description_length",
        (
            "canonical_state_raw_bytes",
            "canonical_state_compressed_bytes_auxiliary",
            "state_scalar_node_edge_particle_counts",
            "state_size_history_length_slope",
            "state_size_by_horizon_task",
        ),
        "compactness_pareto",
        MetricRuntimeCoverage.NOT_IMPLEMENTED_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B005"),
    ),
    (
        "M13",
        "inference_latency_and_memory",
        (
            "initialize_update_diagnose_rollout_cold_p50_p95_p99_latency",
            "peak_rss",
            "peak_gpu_memory",
            "model_artifact_bytes",
            "train_flops_and_wall_time",
            "postseal_extension_worker_resources",
        ),
        "resource_pareto",
        MetricRuntimeCoverage.NOT_IMPLEMENTED_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B005"),
    ),
    (
        "M14",
        "multi_seed_stability",
        (
            "replicate_mean",
            "replicate_standard_deviation",
            "replicate_min_max",
            "seed_ci95",
            "paired_delta_ci95",
            "hierarchical_bootstrap_ci95",
        ),
        "stability_pareto_and_noninferiority",
        MetricRuntimeCoverage.NOT_IMPLEMENTED_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B004"),
    ),
    (
        "M15",
        "update_consistency",
        (
            "incremental_replay_exact_hash_match_rate",
            "batch_sequential_behavioral_match",
            "query_order_purity",
            "oracle_directional_score_change_after_information",
        ),
        "update_semantics_hard_gate_and_pareto",
        MetricRuntimeCoverage.PARTIAL_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B003"),
    ),
    (
        "M16",
        "sealed_state_novel_readout_transfer",
        (
            "postseal_new_readout_score",
            "postseal_new_readout_sample_efficiency",
            "postseal_history_baseline_gap",
            "history_reread_violation",
            "original_scope_sufficiency_disposition",
        ),
        "transfer_pareto_and_history_reread_hard_gate",
        MetricRuntimeCoverage.NOT_IMPLEMENTED_UNBOUND,
        ("UCM-METRIC-B002", "UCM-METRIC-B005"),
    ),
)


@dataclass(frozen=True, slots=True)
class MetricTargetGap:
    """Typed proof that one target is not yet a closed metric definition."""

    gap_id: str
    missing_dimensions: tuple[str, ...]
    required_authorities: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.gap_id) is not str or not self.gap_id:
            raise ProtocolViolation("metric target gap_id must be an exact name")
        if (
            type(self.missing_dimensions) is not tuple
            or not self.missing_dimensions
            or any(
                type(item) is not str or item not in OUTPUT_REQUIRED_DIMENSIONS
                for item in self.missing_dimensions
            )
            or len(set(self.missing_dimensions)) != len(self.missing_dimensions)
        ):
            raise ProtocolViolation("metric target gap dimensions must be closed")
        if (
            type(self.required_authorities) is not tuple
            or not self.required_authorities
            or any(
                type(item) is not str or not item for item in self.required_authorities
            )
        ):
            raise ProtocolViolation("metric target gap authorities must be named")

    def to_wire(self) -> dict[str, Any]:
        return {
            "gap_id": self.gap_id,
            "missing_dimensions": list(self.missing_dimensions),
            "required_authorities": list(self.required_authorities),
        }


@dataclass(frozen=True, slots=True)
class MetricOutputDefinition:
    """Closed sum type: an executable definition or an explicit target gap."""

    metric_id: str
    definition_status: MetricDefinitionStatus
    formula_id: str | None
    formula_version: str | None
    formula_parameter_preimage: dict[str, Any] | None
    optimization_direction: str | None
    unit: str | None
    normalization: str | None
    denominator: str | None
    exposure: str | None
    cohort: str | None
    task_applicability: tuple[str, ...] | None
    world_panel_applicability: tuple[str, ...] | None
    aggregation_hierarchy: tuple[str, ...] | None
    tie_policy: str | None
    undefined_disposition: str | None
    hard_gate_role: MetricHardGateRole
    runtime_implementation_status: MetricRuntimeCoverage
    unresolved_target_gap: MetricTargetGap | None

    def __post_init__(self) -> None:
        if type(self.metric_id) is not str or not self.metric_id:
            raise ProtocolViolation("metric output metric_id must be an exact name")
        if type(self.definition_status) is not MetricDefinitionStatus:
            raise ProtocolViolation(
                "metric output definition_status must be code-owned"
            )
        if type(self.hard_gate_role) is not MetricHardGateRole:
            raise ProtocolViolation("metric output hard_gate_role must be code-owned")
        if type(self.runtime_implementation_status) is not MetricRuntimeCoverage:
            raise ProtocolViolation("metric runtime status must be code-owned")
        semantic_fields = (
            self.formula_id,
            self.formula_version,
            self.formula_parameter_preimage,
            self.optimization_direction,
            self.unit,
            self.normalization,
            self.denominator,
            self.exposure,
            self.cohort,
            self.task_applicability,
            self.world_panel_applicability,
            self.aggregation_hierarchy,
            self.tie_policy,
            self.undefined_disposition,
        )
        if self.definition_status is MetricDefinitionStatus.UNRESOLVED_TARGET_GAP:
            if any(value is not None for value in semantic_fields):
                raise ProtocolViolation(
                    "unresolved metric target cannot carry pseudo-closed semantics"
                )
            if type(self.unresolved_target_gap) is not MetricTargetGap:
                raise ProtocolViolation("unresolved metric target requires a typed gap")
            return
        if self.unresolved_target_gap is not None or any(
            value is None for value in semantic_fields
        ):
            raise ProtocolViolation(
                "closed metric definition requires every semantic dimension"
            )
        validate_json_like(
            self.formula_parameter_preimage,
            path=f"metric output {self.metric_id} parameter preimage",
        )

    def to_wire(self) -> dict[str, Any]:
        return {
            "metric_id": self.metric_id,
            "definition_status": self.definition_status.value,
            "formula_id": self.formula_id,
            "formula_version": self.formula_version,
            "formula_parameter_preimage": self.formula_parameter_preimage,
            "optimization_direction": self.optimization_direction,
            "unit": self.unit,
            "normalization": self.normalization,
            "denominator": self.denominator,
            "exposure": self.exposure,
            "cohort": self.cohort,
            "task_applicability": (
                None
                if self.task_applicability is None
                else list(self.task_applicability)
            ),
            "world_panel_applicability": (
                None
                if self.world_panel_applicability is None
                else list(self.world_panel_applicability)
            ),
            "aggregation_hierarchy": (
                None
                if self.aggregation_hierarchy is None
                else list(self.aggregation_hierarchy)
            ),
            "tie_policy": self.tie_policy,
            "undefined_disposition": self.undefined_disposition,
            "hard_gate_role": self.hard_gate_role.value,
            "runtime_implementation_status": self.runtime_implementation_status.value,
            "unresolved_target_gap": (
                None
                if self.unresolved_target_gap is None
                else self.unresolved_target_gap.to_wire()
            ),
        }


@dataclass(frozen=True, slots=True)
class MetricMeasurementContract:
    measurement_id: str
    area: str
    outputs: tuple[MetricOutputDefinition, ...]
    selection_role: str
    blocker_codes: tuple[str, ...]

    def __post_init__(self) -> None:
        if type(self.measurement_id) is not str or not self.measurement_id:
            raise ProtocolViolation("metric measurement_id must be an exact name")
        if type(self.area) is not str or not self.area:
            raise ProtocolViolation("metric area must be an exact name")
        if (
            type(self.outputs) is not tuple
            or not self.outputs
            or any(type(item) is not MetricOutputDefinition for item in self.outputs)
        ):
            raise ProtocolViolation("metric outputs must be typed and non-empty")
        ids = tuple(item.metric_id for item in self.outputs)
        if len(set(ids)) != len(ids):
            raise ProtocolViolation("metric output ids must be unique within an area")
        if type(self.selection_role) is not str or not self.selection_role:
            raise ProtocolViolation("selection_role must be an exact name")
        if type(self.blocker_codes) is not tuple or not self.blocker_codes:
            raise ProtocolViolation("blocker_codes must be a non-empty tuple")
        if any(type(item) is not str or not item for item in self.blocker_codes):
            raise ProtocolViolation("blocker_codes must contain exact names")

    def to_wire(self) -> dict[str, Any]:
        return {
            "measurement_id": self.measurement_id,
            "area": self.area,
            "outputs": [item.to_wire() for item in self.outputs],
            "selection_role": self.selection_role,
            "blocker_codes": list(self.blocker_codes),
        }


_CONDITIONAL_HARD_GATE_OUTPUTS = frozenset(
    {
        "effect_sign_error",
        "catastrophic_action_rate",
        "w19_tail_mean_max_cvar95_catastrophic_rate",
        "attributable_dangerous_collision_events",
        "ood_treatment_regret_unsafe_non_abstain_rate",
        "state_leak_rate",
        "prediction_leak_rate",
        "max_preavailability_output_divergence",
        "boundary_error_count",
        "old_cut_instability_count",
        "incremental_replay_exact_hash_match_rate",
        "batch_sequential_behavioral_match",
        "query_order_purity",
        "history_reread_violation",
    }
)


def _output_definition(
    measurement_id: str,
    output_index: int,
    metric_id: str,
    runtime_coverage: MetricRuntimeCoverage,
) -> MetricOutputDefinition:
    runtime = (
        MetricRuntimeCoverage.ISOLATED_IMPLEMENTATION_UNBOUND
        if metric_id == "equal_mass_ece_15"
        else runtime_coverage
    )
    hard_gate_role = (
        MetricHardGateRole.CONDITIONAL_HARD_GATE_TARGET
        if metric_id in _CONDITIONAL_HARD_GATE_OUTPUTS
        else MetricHardGateRole.NOT_A_HARD_GATE
    )
    return MetricOutputDefinition(
        metric_id=metric_id,
        definition_status=MetricDefinitionStatus.UNRESOLVED_TARGET_GAP,
        formula_id=None,
        formula_version=None,
        formula_parameter_preimage=None,
        optimization_direction=None,
        unit=None,
        normalization=None,
        denominator=None,
        exposure=None,
        cohort=None,
        task_applicability=None,
        world_panel_applicability=None,
        aggregation_hierarchy=None,
        tie_policy=None,
        undefined_disposition=None,
        hard_gate_role=hard_gate_role,
        runtime_implementation_status=runtime,
        unresolved_target_gap=MetricTargetGap(
            gap_id=f"UCM-METRIC-G-{measurement_id}-{output_index:02d}",
            missing_dimensions=OUTPUT_REQUIRED_DIMENSIONS,
            required_authorities=(
                "closed_formula_registry",
                "formal_21_panel_task_applicability",
                "frozen_world_metric_parameter_manifests",
                "closed_metric_reducer_and_denominator_registry",
            ),
        ),
    )


def _measurement_contracts() -> tuple[MetricMeasurementContract, ...]:
    result = []
    for (
        measurement_id,
        area,
        output_ids,
        selection_role,
        runtime_coverage,
        blocker_codes,
    ) in _MEASUREMENT_TRUTH:
        result.append(
            MetricMeasurementContract(
                measurement_id=measurement_id,
                area=area,
                outputs=tuple(
                    _output_definition(
                        measurement_id,
                        index,
                        metric_id,
                        runtime_coverage,
                    )
                    for index, metric_id in enumerate(output_ids, 1)
                ),
                selection_role=selection_role,
                blocker_codes=blocker_codes + ("UCM-METRIC-B007",),
            )
        )
    return tuple(result)


@dataclass(frozen=True, slots=True)
class MetricBlocker:
    code: str
    detail: str

    def __post_init__(self) -> None:
        if type(self.code) is not str or not self.code:
            raise ProtocolViolation("metric blocker code must be an exact name")
        if type(self.detail) is not str or not self.detail:
            raise ProtocolViolation("metric blocker detail must be an exact string")

    def to_wire(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


_BLOCKERS = (
    MetricBlocker(
        "UCM-METRIC-B001",
        "metric_target_digest is not yet bound by an authorized scope and freeze chain",
    ),
    MetricBlocker(
        "UCM-METRIC-B002",
        "the evaluator does not yet consume and bind this exact metric target registry",
    ),
    MetricBlocker(
        "UCM-METRIC-B003",
        "legacy runtime implements only a subset of the required score and hard-gate primitives",
    ),
    MetricBlocker(
        "UCM-METRIC-B004",
        "freeze-grade aggregation and confidence-interval analysis runtime is absent",
    ),
    MetricBlocker(
        "UCM-METRIC-B005",
        "resource and post-seal extension collectors are not freeze-grade complete",
    ),
    MetricBlocker(
        "UCM-METRIC-B006",
        "winner selection, practical noninferiority margins, baseline binding, and practical advantage authority are unresolved",
    ),
    MetricBlocker(
        "UCM-METRIC-B007",
        "metric output formulas, applicability, denominators, reducers, ties, and undefined semantics remain typed target gaps",
    ),
)


_GLOBAL_TARGET_GAPS = (
    MetricTargetGap(
        "UCM-METRIC-G-GLOBAL-AGGREGATION",
        (
            "denominator_exposure_and_cohort",
            "task_world_panel_applicability",
            "aggregation_hierarchy",
            "tie_policy",
            "undefined_disposition",
        ),
        (
            "formal_21_panel_task_applicability",
            "closed_metric_reducer_and_denominator_registry",
            "frozen_query_cell_weight_authority",
        ),
    ),
    MetricTargetGap(
        "UCM-METRIC-G-GLOBAL-UNCERTAINTY",
        (
            "formula_id_and_version",
            "formula_parameter_preimage",
            "denominator_exposure_and_cohort",
            "aggregation_hierarchy",
            "tie_policy",
            "undefined_disposition",
        ),
        ("closed_ci_algorithm_registry", "authorized_analysis_seed_preimage"),
    ),
    MetricTargetGap(
        "UCM-METRIC-G-GLOBAL-HARD-GATE",
        (
            "formula_id_and_version",
            "formula_parameter_preimage",
            "task_world_panel_applicability",
            "tie_policy",
            "undefined_disposition",
        ),
        (
            "complete_run_level_gate_catalog",
            "canonical_world_margin_field_bindings",
        ),
    ),
    MetricTargetGap(
        "UCM-METRIC-G-GLOBAL-SELECTION",
        (
            "formula_id_and_version",
            "formula_parameter_preimage",
            "optimization_direction",
            "denominator_exposure_and_cohort",
            "task_world_panel_applicability",
            "aggregation_hierarchy",
            "tie_policy",
            "undefined_disposition",
        ),
        (
            "capacity_matched_baseline_authority",
            "paired_practical_noninferiority_margin_authority",
            "practical_advantage_gate_authority",
        ),
    ),
)


def _target_gap_count() -> int:
    return sum(len(contract.outputs) for contract in _measurement_contracts()) + len(
        _GLOBAL_TARGET_GAPS
    )


_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "benchmark_id",
        "target_revision",
        "benchmark_status",
        "authority_claim",
        "runtime_binding_status",
        "freeze_authority_status",
        "semantic_config_ready",
        "target_gap_count",
        "global_target_gaps",
        "measurement_contracts",
        "numerical_policy",
        "aggregation_policy",
        "uncertainty_policy",
        "undefined_policy",
        "hard_gate_policy",
        "selection_policy",
        "blockers",
    }
)


def _code_owned_wire() -> dict[str, Any]:
    return {
        "schema_version": METRIC_TARGET_SCHEMA,
        "benchmark_id": METRIC_TARGET_BENCHMARK_ID,
        "target_revision": METRIC_TARGET_REVISION,
        "benchmark_status": METRIC_TARGET_BENCHMARK_STATUS,
        "authority_claim": METRIC_TARGET_AUTHORITY_CLAIM,
        "runtime_binding_status": METRIC_TARGET_RUNTIME_BINDING,
        "freeze_authority_status": METRIC_TARGET_FREEZE_AUTHORITY,
        "semantic_config_ready": METRIC_TARGET_SEMANTIC_READY,
        "target_gap_count": _target_gap_count(),
        "global_target_gaps": [item.to_wire() for item in _GLOBAL_TARGET_GAPS],
        "measurement_contracts": [item.to_wire() for item in _measurement_contracts()],
        "numerical_policy": {
            "parameter_status": "closed_target_parameters_not_runtime_bound",
            "calibration_bins": 15,
            "calibration_binning": "equal_mass_empirical_quantile",
            "calibration_tie_policy": "equal_confidence_values_remain_together",
            "probability_clip_lower_for_scores": 1e-12,
            "probability_clip_upper_for_scores": 1.0 - 1e-12,
            "probability_sum_absolute_tolerance": 1e-9,
            "probability_sum_relative_tolerance": 0.0,
            "pre_score_quantization": "none",
            "reported_quantization": "none",
            "canonical_float_representation": "canonical_json_shortest_roundtrip_binary64",
            "score_float_format": "ieee754_binary64",
            "quantile_method": "hyndman_fan_type_7_linear",
            "finite_values_required": True,
            "raw_candidate_output_retained": True,
        },
        "aggregation_policy": {
            "definition_status": "unresolved_target_gap",
            "raw_grain": [
                "record_id",
                "candidate_id",
                "candidate_artifact_id",
                "training_replicate_id",
                "evaluation_replicate_id",
                "model_seed_id",
                "world_slot",
                "panel_id",
                "family_id",
                "episode_alias",
                "task",
                "stratum",
                "cohort",
                "cut_alias",
                "horizon",
                "policy_alias",
                "w19_tail_cohort_membership",
            ],
            "target_reducer_order": [
                "raw_query_to_family",
                "family_to_world_task_horizon_policy_stratum",
                "frozen_query_cell_weight_within_world",
                "equal_weight_fixed_world_macro",
                "replicate_summary_and_ci",
            ],
            "closed_reducer_formula_registry": None,
            "closed_weight_preimage": None,
            "closed_denominator_and_exposure_registry": None,
            "required_cell_handling_registry": None,
            "world_count": 20,
            "replicate_count": 5,
            "separate_before_gate": [
                "task",
                "horizon",
                "policy",
                "stratum",
                "w19_tail_cohort",
            ],
            "episode_weighted_result": "sensitivity_only",
            "single_aggregate_score": "forbidden",
            "unresolved_target_gap": _GLOBAL_TARGET_GAPS[0].to_wire(),
        },
        "uncertainty_policy": {
            "definition_status": "unresolved_target_gap",
            "confidence_level": 0.95,
            "seed_ci_method": "student_t_on_five_replicate_world_macro",
            "seed_ci_degrees_freedom": 4,
            "paired_delta_ci_method": "paired_student_t_same_replicate_corpus",
            "paired_delta_ci_degrees_freedom": 4,
            "episode_ci_method": "family_cluster_percentile_bootstrap",
            "episode_bootstrap_replicates": 10000,
            "episode_bootstrap_sampling_preimage": None,
            "episode_bootstrap_endpoint_rule": None,
            "hierarchical_ci_method": "fixed_world_replicate_and_within_world_family_cluster_percentile_bootstrap",
            "hierarchical_bootstrap_replicates": 10000,
            "hierarchical_bootstrap_sampling_preimage": None,
            "hierarchical_bootstrap_endpoint_rule": None,
            "bounded_rate_interval": "wilson_score_two_sided",
            "zero_event_upper_bound": "clopper_pearson_one_sided",
            "analysis_seed_source": "freeze_manifest_separate_analysis_domain",
            "primary_world_resampling": "forbidden_fixed_panel",
            "world_resampled_ci": "exploratory_superpopulation_sensitivity_only",
            "unresolved_target_gap": _GLOBAL_TARGET_GAPS[1].to_wire(),
        },
        "undefined_policy": {
            "nan_or_infinity": "protocol_failure",
            "empty_denominator": "null_with_reason_and_zero_exposure",
            "zero_normalized_regret_denominator": "null_reason_zero_oracle_utility_range",
            "single_class_discrimination": "null_reason_insufficient_class_support",
            "optional_distribution_component": "null_reason_not_provided",
            "required_distribution_component": "required_cell_incomplete_or_ineligible",
            "unsupported_invalid_crash_required_cell": "required_cell_incomplete_or_ineligible",
            "abstain": "retain_in_selective_risk_and_coverage_denominator",
            "zero_events": "zero_rate_with_nonzero_exact_upper_bound",
            "metric_imputation": "forbidden",
        },
        "hard_gate_policy": {
            "definition_status": "unresolved_target_gap",
            "event_level_gate_ignores_ci_compensation": True,
            "required_status_failures": [
                "unsupported",
                "invalid_input",
                "crash",
                "nan_or_infinity",
                "unscorable_required_distribution",
            ],
            "probability_range": "strict_closed_unit_interval",
            "paired_prefix_tolerance": "exact_canonical_bytes_and_hash",
            "forced_known_max_known_probability": 0.90,
            "forced_known_max_unknown_probability": 0.10,
            "collision_margin_source": "frozen_world_manifest",
            "catastrophic_margin_source": "frozen_world_manifest",
            "optimal_action_tolerance_source": "frozen_world_manifest",
            "action_tie_break_source": "frozen_world_query_manifest",
            "w19_tail_cohort_source": "frozen_world_manifest",
            "dangerous_collision_requires_attribution": True,
            "partial_identification_catastrophe_rule": "catastrophic_in_all_compatible_models",
            "broken_true_state_upper_bound_disposition": "harness_incomplete",
            "complete_run_level_gate_catalog": None,
            "canonical_world_margin_field_bindings": None,
            "unresolved_target_gap": _GLOBAL_TARGET_GAPS[2].to_wire(),
        },
        "selection_policy": {
            "definition_status": "unresolved_target_gap",
            "capacity_matched_baseline_binding": None,
            "per_task_paired_practical_noninferiority_margins": None,
            "paired_ci_decision_rule": None,
            "required_practical_advantage_rule": None,
            "winner_selection_ready": False,
            "unresolved_target_gap": _GLOBAL_TARGET_GAPS[3].to_wire(),
        },
        "blockers": [item.to_wire() for item in _BLOCKERS],
    }


def _exact_object(
    value: object, expected_keys: frozenset[str], label: str
) -> dict[str, Any]:
    if type(value) is not dict:
        raise ProtocolViolation(f"{label} must be an exact object")
    validate_json_like(value, path=label)
    actual = frozenset(value)
    if actual != expected_keys:
        raise ProtocolViolation(
            f"{label} has missing/extra fields; "
            f"missing={sorted(expected_keys - actual)!r}, "
            f"extra={sorted(actual - expected_keys)!r}"
        )
    return value


def _decode_exact_canonical_object(payload: object) -> dict[str, Any]:
    if type(payload) is not bytes:
        raise ProtocolViolation("metric target registry must be exact bytes")

    def reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ProtocolViolation(
                    f"metric target registry contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProtocolViolation(
            "metric target registry is not strict UTF-8 JSON"
        ) from exc
    try:
        value = json.loads(text, object_pairs_hook=reject_duplicate_pairs)
    except ProtocolViolation:
        raise
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ProtocolViolation("metric target registry is not valid JSON") from exc
    if type(value) is not dict:
        raise ProtocolViolation("metric target registry must encode an exact object")
    validate_json_like(value, path="metric target registry")
    if canonical_json_bytes(value) != payload:
        raise ProtocolViolation(
            "metric target registry bytes are not canonical sorted compact JSON plus one LF"
        )
    return value


@dataclass(frozen=True, slots=True)
class BenchmarkMetricTargetRegistry:
    """Immutable parsed PRE-FREEZE target preimage; not semantic readiness."""

    canonical_bytes: bytes

    def __post_init__(self) -> None:
        if type(self.canonical_bytes) is not bytes:
            raise ProtocolViolation(
                "metric target registry preimage must be exact bytes"
            )
        if self.canonical_bytes != canonical_json_bytes(_code_owned_wire()):
            raise ProtocolViolation(
                "metric target registry differs from code-owned v1 truth"
            )

    @property
    def artifact_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def metric_target_digest(self) -> str:
        digest = hashlib.sha256()
        digest.update(METRIC_TARGET_DOMAIN)
        digest.update(self.canonical_bytes)
        return "sha256:" + digest.hexdigest()

    @property
    def measurement_contracts(self) -> tuple[MetricMeasurementContract, ...]:
        return _measurement_contracts()

    @property
    def global_target_gaps(self) -> tuple[MetricTargetGap, ...]:
        return _GLOBAL_TARGET_GAPS

    @property
    def target_gap_count(self) -> int:
        return _target_gap_count()

    @property
    def semantic_config_ready(self) -> bool:
        return False

    @property
    def blockers(self) -> tuple[MetricBlocker, ...]:
        return _BLOCKERS

    def to_wire(self) -> dict[str, Any]:
        # Return a new inert object, never a mutable reference held by this DTO.
        return json.loads(self.canonical_bytes)


def benchmark_v1_metric_target_registry() -> BenchmarkMetricTargetRegistry:
    return BenchmarkMetricTargetRegistry(canonical_json_bytes(_code_owned_wire()))


def parse_metric_target_registry_bytes(payload: bytes) -> BenchmarkMetricTargetRegistry:
    """Parse exact bytes and reject even internally re-signed alternate semantics."""

    value = _decode_exact_canonical_object(payload)
    _exact_object(value, _TOP_LEVEL_KEYS, "metric target registry")
    expected = _code_owned_wire()
    if value != expected:
        raise ProtocolViolation(
            "metric target registry differs from code-owned v1 truth"
        )
    return BenchmarkMetricTargetRegistry(payload)


def metric_target_artifact_digest_from_bytes(payload: bytes) -> str:
    return parse_metric_target_registry_bytes(payload).artifact_digest


def metric_target_digest_from_bytes(payload: bytes) -> str:
    return parse_metric_target_registry_bytes(payload).metric_target_digest
