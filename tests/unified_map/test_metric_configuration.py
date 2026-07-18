from __future__ import annotations

import copy
import hashlib
import json

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
)
from prototype.unified_map.metric_configuration import (
    METRIC_TARGET_DOMAIN,
    OUTPUT_REQUIRED_DIMENSIONS,
    MetricDefinitionStatus,
    MetricOutputDefinition,
    MetricRuntimeCoverage,
    benchmark_v1_metric_target_registry,
    metric_target_artifact_digest_from_bytes,
    metric_target_digest_from_bytes,
    parse_metric_target_registry_bytes,
)
from prototype.unified_map.metrics import (
    benchmark_v1_diagnostic_metrics,
    diagnostic_metrics,
)


def _wire() -> dict:
    return benchmark_v1_metric_target_registry().to_wire()


def _canonical_mutation(mutator) -> bytes:
    value = copy.deepcopy(_wire())
    mutator(value)
    return canonical_json_bytes(value)


def test_metric_target_registry_is_exact_code_owned_and_covers_all_16_areas() -> None:
    config = benchmark_v1_metric_target_registry()
    parsed = parse_metric_target_registry_bytes(config.canonical_bytes)
    wire = parsed.to_wire()

    assert [row.measurement_id for row in parsed.measurement_contracts] == [
        f"M{index:02d}" for index in range(1, 17)
    ]
    assert len({row.area for row in parsed.measurement_contracts}) == 16
    outputs = [output for row in parsed.measurement_contracts for output in row.outputs]
    assert outputs
    assert all(type(output) is MetricOutputDefinition for output in outputs)
    for output in outputs:
        if output.definition_status is MetricDefinitionStatus.CLOSED:
            assert output.unresolved_target_gap is None
            assert output.formula_id and output.formula_version
            assert output.optimization_direction is not None
            assert output.denominator is not None
            assert output.task_applicability is not None
            assert output.aggregation_hierarchy is not None
            assert output.undefined_disposition is not None
        else:
            assert (
                output.definition_status is MetricDefinitionStatus.UNRESOLVED_TARGET_GAP
            )
            assert output.unresolved_target_gap is not None
            assert (
                output.unresolved_target_gap.missing_dimensions
                == OUTPUT_REQUIRED_DIMENSIONS
            )
            assert output.formula_id is None
            assert output.optimization_direction is None
    assert wire["benchmark_id"] == "UCM-BENCHMARK-v1"
    assert wire["target_revision"] == "PRE-FREEZE-metric-target-v1"
    assert wire["benchmark_status"] == "PRE-FREEZE"
    assert wire["authority_claim"] == "typed_metric_target_registry_only"
    assert wire["runtime_binding_status"] == "not_bound_to_evaluator"
    assert wire["freeze_authority_status"] == "not_claimed"
    assert wire["semantic_config_ready"] is False
    assert wire["target_gap_count"] == len(outputs) + len(parsed.global_target_gaps)
    assert parsed.target_gap_count == wire["target_gap_count"]
    assert parsed.semantic_config_ready is False
    assert "metric_target_digest" not in wire
    assert "artifact_digest" not in wire


def test_target_parameters_and_unresolved_global_authorities_are_machine_readable() -> (
    None
):
    wire = _wire()
    numeric = wire["numerical_policy"]
    aggregation = wire["aggregation_policy"]
    uncertainty = wire["uncertainty_policy"]
    undefined = wire["undefined_policy"]
    gates = wire["hard_gate_policy"]
    selection = wire["selection_policy"]

    assert numeric["calibration_bins"] == 15
    assert numeric["calibration_binning"] == "equal_mass_empirical_quantile"
    assert numeric["pre_score_quantization"] == "none"
    assert numeric["reported_quantization"] == "none"
    assert numeric["canonical_float_representation"].endswith("binary64")
    assert numeric["probability_clip_lower_for_scores"] == 1e-12
    assert numeric["probability_sum_absolute_tolerance"] == 1e-9
    assert aggregation["world_count"] == 20
    assert aggregation["replicate_count"] == 5
    assert aggregation["single_aggregate_score"] == "forbidden"
    assert aggregation["definition_status"] == "unresolved_target_gap"
    assert {
        "task",
        "stratum",
        "family_id",
        "panel_id",
        "w19_tail_cohort_membership",
    } <= set(aggregation["raw_grain"])
    assert aggregation["closed_reducer_formula_registry"] is None
    assert aggregation["unresolved_target_gap"]["gap_id"].endswith("AGGREGATION")
    assert uncertainty["seed_ci_degrees_freedom"] == 4
    assert uncertainty["episode_bootstrap_replicates"] == 10000
    assert uncertainty["hierarchical_bootstrap_replicates"] == 10000
    assert uncertainty["bounded_rate_interval"] == "wilson_score_two_sided"
    assert uncertainty["definition_status"] == "unresolved_target_gap"
    assert uncertainty["episode_bootstrap_sampling_preimage"] is None
    assert undefined["metric_imputation"] == "forbidden"
    assert undefined["abstain"].startswith("retain_in_")
    assert gates["event_level_gate_ignores_ci_compensation"] is True
    assert gates["forced_known_max_known_probability"] == 0.90
    assert gates["forced_known_max_unknown_probability"] == 0.10
    assert gates["collision_margin_source"] == "frozen_world_manifest"
    assert gates["definition_status"] == "unresolved_target_gap"
    assert gates["complete_run_level_gate_catalog"] is None
    assert selection["winner_selection_ready"] is False
    assert selection["definition_status"] == "unresolved_target_gap"
    assert selection["per_task_paired_practical_noninferiority_margins"] is None


def test_configuration_digest_has_exact_preimage_and_separate_domain() -> None:
    config = benchmark_v1_metric_target_registry()
    assert (
        config.artifact_digest
        == "sha256:7ba4ab4a9831e70d179466389a1eb6aa618c1c9a1bad4c8b8bdb0dfd20804c93"
    )
    assert (
        config.metric_target_digest
        == "sha256:a4a3781b29d01c677d79d5a1503b9e240fcfe0dc5ae4eb432b2fbe874c3d9deb"
    )
    assert metric_target_artifact_digest_from_bytes(
        config.canonical_bytes
    ) == digest_bytes(config.canonical_bytes)

    semantic = hashlib.sha256(METRIC_TARGET_DOMAIN + config.canonical_bytes)
    assert config.metric_target_digest == "sha256:" + semantic.hexdigest()
    assert (
        metric_target_digest_from_bytes(config.canonical_bytes)
        == config.metric_target_digest
    )
    assert config.metric_target_digest != config.artifact_digest


def test_parser_rejects_noncanonical_duplicate_and_missing_or_extra_fields() -> None:
    canonical = benchmark_v1_metric_target_registry().canonical_bytes
    assert canonical.endswith(b"\n")
    with pytest.raises(ProtocolViolation, match="not canonical"):
        parse_metric_target_registry_bytes(canonical.rstrip(b"\n"))
    with pytest.raises(ProtocolViolation, match="duplicate key"):
        parse_metric_target_registry_bytes(
            canonical.replace(
                b'{"aggregation_policy":',
                b'{"schema_version":"ucm-pre-freeze-metric-target-registry/1","aggregation_policy":',
                1,
            )
        )
    with pytest.raises(ProtocolViolation, match="missing/extra"):
        parse_metric_target_registry_bytes(
            _canonical_mutation(lambda row: row.pop("undefined_policy"))
        )
    with pytest.raises(
        ProtocolViolation, match="missing/extra|differs from code-owned"
    ):
        parse_metric_target_registry_bytes(
            _canonical_mutation(lambda row: row.__setitem__("claimed_digest", "x"))
        )


def test_parser_rejects_re_signed_semantic_enum_and_bool_number_tampering() -> None:
    tampered = _canonical_mutation(
        lambda row: row["numerical_policy"].__setitem__("calibration_bins", 10)
    )
    # An attacker can recompute an ordinary digest, but cannot mint code-owned
    # semantics by placing alternate exact bytes behind that digest.
    assert digest_bytes(tampered).startswith("sha256:")
    with pytest.raises(ProtocolViolation, match="differs from code-owned"):
        parse_metric_target_registry_bytes(tampered)

    with pytest.raises(ProtocolViolation, match="differs from code-owned"):
        parse_metric_target_registry_bytes(
            _canonical_mutation(
                lambda row: row["measurement_contracts"][0]["outputs"][0].__setitem__(
                    "definition_status", "pretend_closed"
                )
            )
        )
    with pytest.raises(ProtocolViolation, match="differs from code-owned"):
        parse_metric_target_registry_bytes(
            _canonical_mutation(
                # bool compares equal to numeric zero in Python.  Exact
                # preimage verification must still reject this type swap.
                lambda row: row["numerical_policy"].__setitem__(
                    "probability_sum_relative_tolerance", False
                )
            )
        )


def test_runtime_coverage_is_machine_readable_and_never_claims_freeze_readiness() -> (
    None
):
    config = benchmark_v1_metric_target_registry()
    coverage = {
        output.runtime_implementation_status
        for row in config.measurement_contracts
        for output in row.outputs
    }
    blocker_codes = {item.code for item in config.blockers}

    assert coverage == {
        MetricRuntimeCoverage.PARTIAL_UNBOUND,
        MetricRuntimeCoverage.NOT_IMPLEMENTED_UNBOUND,
        MetricRuntimeCoverage.ISOLATED_IMPLEMENTATION_UNBOUND,
    }
    assert blocker_codes == {f"UCM-METRIC-B00{index}" for index in range(1, 8)}
    assert all(
        set(row.blocker_codes) <= blocker_codes for row in config.measurement_contracts
    )
    assert "freeze" not in _wire()["runtime_binding_status"]


def test_v1_diagnostic_path_uses_15_equal_mass_bins_and_keeps_ties_together() -> None:
    confidences = [0.51] * 10 + [0.60] * 10 + [0.99] * 10
    probabilities = [[value, 1.0 - value] for value in confidences]
    labels = [0] * 5 + [1] * 5 + [0] * 10 + [0] * 2 + [1] * 8

    configured = benchmark_v1_diagnostic_metrics(probabilities, labels)
    reversed_rows = benchmark_v1_diagnostic_metrics(
        list(reversed(probabilities)), list(reversed(labels))
    )

    assert configured.expected_calibration_error == pytest.approx(
        reversed_rows.expected_calibration_error
    )
    # The three tied confidence groups must each remain one empirical bin.
    expected = (10 / 30) * abs(0.51 - 0.5)
    expected += (10 / 30) * abs(0.60 - 1.0)
    expected += (10 / 30) * abs(0.99 - 0.2)
    assert configured.expected_calibration_error == pytest.approx(expected)


def test_legacy_diagnostic_default_remains_compatible_until_evaluator_migration() -> (
    None
):
    # The authority is isolated: merely defining v1 semantics cannot rewrite
    # already-verifiable PRE-FREEZE artifacts or W01 direction checks.
    exact = diagnostic_metrics([[0.0, 1.0]], [1])
    assert exact.accuracy == 1.0
    assert exact.log_loss == 0.0


def test_configuration_wire_is_a_fresh_copy() -> None:
    config = benchmark_v1_metric_target_registry()
    first = config.to_wire()
    first["numerical_policy"]["calibration_bins"] = 10
    assert config.to_wire()["numerical_policy"]["calibration_bins"] == 15


def test_parser_requires_exact_bytes_not_json_or_string() -> None:
    with pytest.raises(ProtocolViolation, match="exact bytes"):
        parse_metric_target_registry_bytes(_wire())  # type: ignore[arg-type]
    with pytest.raises(ProtocolViolation, match="exact bytes"):
        parse_metric_target_registry_bytes(json.dumps(_wire()))  # type: ignore[arg-type]
