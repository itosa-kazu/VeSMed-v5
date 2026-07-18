from __future__ import annotations

import copy
import math

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
)
from prototype.unified_map.metrics_m09_m11 import (
    M09_POINT_SCHEMA,
    M10_PAIR_SCHEMA,
    M11_OBSERVATION_SCHEMA,
    TRAIN_FRACTION_PERCENTS,
    CanonicalMetricEvidence,
    ExtensionCostObservation,
    HeldoutMatchedPair,
    LearningCurvePoint,
    combination_generalization,
    extension_cost,
    sample_efficiency,
)


def _evidence(path: str, payload: dict) -> CanonicalMetricEvidence:
    return CanonicalMetricEvidence.from_payload(path, payload)


def _m09_point(
    task: str,
    fraction: int,
    examples: int,
    score: int | float,
) -> LearningCurvePoint:
    return LearningCurvePoint(
        _evidence(
            f"m09/{task}-{fraction:03d}.json",
            {
                "schema_version": M09_POINT_SCHEMA,
                "task": task,
                "train_fraction_percent": fraction,
                "train_examples": examples,
                "proper_score": score,
            },
        )
    )


def _m09_fixture() -> tuple[LearningCurvePoint, ...]:
    counts = (10, 50, 100, 250, 500, 1000)
    task_scores = {
        "diagnosis": (6.0, 5.0, 4.0, 3.0, 2.0, 1.0),
        "natural_forecast": (12.0, 10.0, 8.0, 6.0, 4.0, 2.0),
        "intervention": (3.0, 2.5, 2.0, 1.5, 1.0, 0.5),
    }
    return tuple(
        _m09_point(task, fraction, count, score)
        for task, scores in task_scores.items()
        for fraction, count, score in zip(
            TRAIN_FRACTION_PERCENTS, counts, scores, strict=True
        )
    )


def test_m09_log_sample_auc_is_hand_computable_and_kept_per_task() -> None:
    points = _m09_fixture()
    result = sample_efficiency(points)
    wire = result.to_wire()

    assert wire["benchmark_status"] == "PRE-FREEZE"
    assert wire["evidence_qualification"] == "runtime_only"
    assert wire["authority_claim"] == "not_claimed"
    assert wire["freeze_authority_status"] == "not_claimed"
    assert wire["cross_metric_aggregate_score"] == "forbidden"
    assert wire["cross_task_aggregate_score"] == "forbidden"
    assert [row["task"] for row in wire["task_curves"]] == [
        "diagnosis",
        "natural_forecast",
        "intervention",
    ]

    diagnosis = wire["task_curves"][0]
    x = [math.log(value) for value in (10, 50, 100, 250, 500, 1000)]
    y = (6.0, 5.0, 4.0, 3.0, 2.0, 1.0)
    expected_auc = sum(
        (right_x - left_x) * (left_y + right_y) / 2.0
        for left_x, right_x, left_y, right_y in zip(x, x[1:], y, y[1:])
    )
    expected_span = math.log(1000) - math.log(10)
    assert diagnosis["log_sample_auc"] == pytest.approx(expected_auc)
    assert diagnosis["normalization_denominator_log_sample_span"] == pytest.approx(
        expected_span
    )
    assert diagnosis["normalized_log_sample_auc"] == pytest.approx(
        expected_auc / expected_span
    )
    assert diagnosis["optimization_direction"] == "minimize"
    assert len(diagnosis["evidence_references"]) == 6
    assert all("artifact_digest" in row for row in diagnosis["evidence_references"])


def test_m09_is_order_invariant_and_missing_duplicate_or_undefined_fails_closed() -> (
    None
):
    points = _m09_fixture()
    assert (
        sample_efficiency(points).canonical_bytes
        == sample_efficiency(tuple(reversed(points))).canonical_bytes
    )

    with pytest.raises(ProtocolViolation, match="exactly 18"):
        sample_efficiency(points[:-1])
    duplicate = LearningCurvePoint(
        _evidence(
            "m09/duplicate-diagnosis-001.json",
            {
                "schema_version": M09_POINT_SCHEMA,
                "task": "diagnosis",
                "train_fraction_percent": 1,
                "train_examples": 10,
                "proper_score": 6.0,
            },
        )
    )
    with pytest.raises(ProtocolViolation, match="duplicate task/fraction"):
        sample_efficiency(points[:-1] + (duplicate,))
    with pytest.raises(ProtocolViolation, match="strictly increase"):
        invalid = list(points)
        invalid[1] = _m09_point("diagnosis", 5, 10, 5.0)
        sample_efficiency(tuple(invalid))
    with pytest.raises(ProtocolViolation, match="finite number"):
        _m09_point("diagnosis", 1, 10, False)
    with pytest.raises(ProtocolViolation, match="tuple of typed"):
        sample_efficiency(list(points))  # type: ignore[arg-type]


def _m10_pair(
    *,
    stratum: str,
    pair_id: str,
    heldout: int | float,
    seen: int | float,
    direction: str = "minimize",
) -> HeldoutMatchedPair:
    return HeldoutMatchedPair(
        _evidence(
            f"m10/{stratum}-{pair_id}.json",
            {
                "schema_version": M10_PAIR_SCHEMA,
                "stratum": stratum,
                "pair_id": pair_id,
                "heldout_case_id": f"heldout-{stratum}-{pair_id}",
                "matched_seen_case_id": f"seen-{stratum}-{pair_id}",
                "score_direction": direction,
                "heldout_score": heldout,
                "matched_seen_score": seen,
            },
        )
    )


def _m10_fixture() -> tuple[HeldoutMatchedPair, ...]:
    return (
        _m10_pair(
            stratum="heldout_mechanism_combination",
            pair_id="p1",
            heldout=12,
            seen=10,
        ),
        _m10_pair(
            stratum="heldout_mechanism_combination",
            pair_id="p2",
            heldout=15,
            seen=11,
        ),
        _m10_pair(stratum="heldout_host_modifier", pair_id="p1", heldout=9, seen=10),
        _m10_pair(stratum="heldout_host_modifier", pair_id="p2", heldout=7, seen=10),
        _m10_pair(
            stratum="heldout_nonlinear_comorbidity",
            pair_id="p1",
            heldout=0.7,
            seen=0.8,
            direction="maximize",
        ),
        _m10_pair(
            stratum="heldout_nonlinear_comorbidity",
            pair_id="p2",
            heldout=0.5,
            seen=0.8,
            direction="maximize",
        ),
    )


def test_m10_reports_direction_denominator_and_paired_uncertainty() -> None:
    result = combination_generalization(_m10_fixture())
    wire = result.to_wire()
    assert wire["cross_stratum_aggregate_score"] == "forbidden"
    mechanism = wire["stratum_gaps"][0]
    assert mechanism["stratum"] == "heldout_mechanism_combination"
    assert mechanism["score_direction"] == "minimize"
    assert mechanism["gap_orientation"] == "positive_means_heldout_is_worse"
    assert mechanism["denominator_count"] == 2
    assert mechanism["mean_heldout_score"] == pytest.approx(13.5)
    assert mechanism["mean_matched_seen_score"] == pytest.approx(10.5)
    assert mechanism["mean_oriented_gap"] == pytest.approx(3.0)
    assert mechanism["uncertainty"]["paired_delta_sample_sd"] == pytest.approx(
        math.sqrt(2.0)
    )
    assert mechanism["uncertainty"]["paired_delta_standard_error"] == pytest.approx(1.0)
    assert mechanism["uncertainty"]["status"] == "defined"
    assert mechanism["uncertainty"]["sampling_unit"] == (
        "explicit_matched_heldout_seen_pair"
    )
    assert mechanism["uncertainty"]["degrees_of_freedom"] == 1
    assert mechanism["uncertainty"]["student_t_critical"] == pytest.approx(
        12.7062047361747
    )
    assert mechanism["uncertainty"]["ci95_lower"] == pytest.approx(
        3.0 - 12.7062047361747
    )
    assert mechanism["uncertainty"]["ci95_upper"] == pytest.approx(
        3.0 + 12.7062047361747
    )
    nonlinear = wire["stratum_gaps"][2]
    assert nonlinear["score_direction"] == "maximize"
    assert nonlinear["mean_oriented_gap"] == pytest.approx(0.2)


def test_m10_is_order_invariant_and_bad_coverage_direction_or_number_fails_closed() -> (
    None
):
    pairs = _m10_fixture()
    assert combination_generalization(pairs).canonical_bytes == (
        combination_generalization(tuple(reversed(pairs))).canonical_bytes
    )
    with pytest.raises(ProtocolViolation, match="requires a matched pair"):
        combination_generalization(pairs[:-2])
    with pytest.raises(ProtocolViolation, match="homogeneous"):
        replacement = _m10_pair(
            stratum="heldout_mechanism_combination",
            pair_id="p2",
            heldout=15,
            seen=11,
            direction="maximize",
        )
        combination_generalization((pairs[0], replacement) + pairs[2:])
    with pytest.raises(ProtocolViolation, match="finite number"):
        _m10_pair(
            stratum="heldout_host_modifier",
            pair_id="bool",
            heldout=True,
            seen=0,
        )


def test_m10_single_pair_keeps_mean_and_types_uncertainty_as_undefined() -> None:
    pairs = tuple(
        _m10_pair(stratum=stratum, pair_id="only", heldout=4.0, seen=1.0)
        for stratum in (
            "heldout_mechanism_combination",
            "heldout_host_modifier",
            "heldout_nonlinear_comorbidity",
        )
    )
    wire = combination_generalization(pairs).to_wire()
    for row in wire["stratum_gaps"]:
        assert row["denominator_count"] == 1
        assert row["mean_oriented_gap"] == pytest.approx(3.0)
        uncertainty = row["uncertainty"]
        assert uncertainty["status"] == "undefined"
        assert uncertainty["undefined_reason"] == "insufficient_pairs"
        assert uncertainty["degrees_of_freedom"] == 0
        assert uncertainty["student_t_critical"] is None
        assert uncertainty["paired_delta_sample_sd"] is None
        assert uncertainty["paired_delta_standard_error"] is None
        assert uncertainty["ci95_lower"] is None
        assert uncertainty["ci95_upper"] is None


def test_m10_five_pair_student_t_uses_df4_code_owned_critical() -> None:
    pairs = tuple(
        _m10_pair(
            stratum=stratum,
            pair_id=f"p{index}",
            heldout=float(index + 1),
            seen=0.0,
        )
        for stratum in (
            "heldout_mechanism_combination",
            "heldout_host_modifier",
            "heldout_nonlinear_comorbidity",
        )
        for index in range(5)
    )
    wire = combination_generalization(pairs).to_wire()
    for row in wire["stratum_gaps"]:
        uncertainty = row["uncertainty"]
        assert uncertainty["degrees_of_freedom"] == 4
        assert uncertainty["student_t_critical"] == pytest.approx(2.77644510519779)


def _m11_payload(extension_id: str, kind: str) -> dict:
    return {
        "schema_version": M11_OBSERVATION_SCHEMA,
        "extension_id": extension_id,
        "extension_kind": kind,
        "model_migration_required": True,
        "state_migration_required": False,
        "schema_migration_required": True,
        "retrain_examples": 20,
        "base_artifact_size_bytes": 100,
        "extended_artifact_size_bytes": 140,
        "core_diff_files": [
            {"path": "core/b.py", "added_lines": 2, "deleted_lines": 3},
            {"path": "core/a.py", "added_lines": 4, "deleted_lines": 1},
        ],
        "old_benchmark_before_score": 1.0,
        "old_benchmark_after_score": 1.3,
        "old_benchmark_score_direction": "minimize",
        "old_benchmark_denominator": 50,
        "completion_disposition": "completed",
    }


def _m11_observation(payload: dict) -> ExtensionCostObservation:
    return ExtensionCostObservation(
        _evidence(f"m11/{payload['extension_id']}.json", payload)
    )


def test_m11_reports_each_cost_axis_and_derives_hard_failure() -> None:
    completed = _m11_observation(_m11_payload("z-check", "new_check"))
    failure_payload = _m11_payload("a-treatment", "new_treatment")
    failure_payload.update(
        {
            "completion_disposition": "requires_full_core_rewrite",
            "old_benchmark_before_score": 0.8,
            "old_benchmark_after_score": 0.5,
            "old_benchmark_score_direction": "maximize",
            "base_artifact_size_bytes": 150,
            "extended_artifact_size_bytes": 120,
        }
    )
    failed = _m11_observation(failure_payload)
    wire = extension_cost((completed, failed)).to_wire()

    assert wire["benchmark_status"] == "PRE-FREEZE"
    assert wire["evidence_qualification"] == "runtime_only"
    assert wire["cross_extension_aggregate_score"] == "forbidden"
    assert [row["extension_id"] for row in wire["extensions"]] == [
        "a-treatment",
        "z-check",
    ]
    failure = wire["extensions"][0]
    assert failure["hard_extensibility_failure"] is True
    assert failure["artifact_bytes"] == {
        "base": 150,
        "extended": 120,
        "signed_delta": -30,
        "absolute_delta": 30,
    }
    assert failure["old_benchmark_regression"]["oriented_regression"] == (
        pytest.approx(0.3)
    )
    success = wire["extensions"][1]
    assert success["hard_extensibility_failure"] is False
    assert success["migration_flags"] == {
        "model_migration_required": True,
        "state_migration_required": False,
        "schema_migration_required": True,
    }
    assert success["retrain_examples"] == 20
    assert success["artifact_bytes"]["signed_delta"] == 40
    assert success["core_diff"]["changed_file_count"] == 2
    assert success["core_diff"]["added_lines"] == 6
    assert success["core_diff"]["deleted_lines"] == 4
    assert success["core_diff"]["changed_loc"] == 10
    assert [row["path"] for row in success["core_diff"]["files"]] == [
        "core/a.py",
        "core/b.py",
    ]
    assert success["old_benchmark_regression"]["denominator_count"] == 50
    assert success["old_benchmark_regression"]["oriented_regression"] == (
        pytest.approx(0.3)
    )


def test_m11_is_order_invariant_and_schema_bool_number_duplicates_fail_closed() -> None:
    first = _m11_observation(_m11_payload("check", "new_check"))
    second_payload = _m11_payload("treatment", "new_treatment")
    second_payload["completion_disposition"] = "requires_full_core_rewrite"
    second = _m11_observation(second_payload)
    assert (
        extension_cost((first, second)).canonical_bytes
        == extension_cost((second, first)).canonical_bytes
    )

    missing = _m11_payload("missing", "new_check")
    missing.pop("retrain_examples")
    with pytest.raises(ProtocolViolation, match="schema mismatch"):
        _m11_observation(missing)
    bool_number = _m11_payload("bool", "new_check")
    bool_number["retrain_examples"] = False
    with pytest.raises(ProtocolViolation, match="exact integer"):
        _m11_observation(bool_number)
    duplicated_path = _m11_payload("duplicate-path", "new_check")
    duplicated_path["core_diff_files"][1]["path"] = "core/b.py"
    with pytest.raises(ProtocolViolation, match="paths must be unique"):
        _m11_observation(duplicated_path)
    duplicate_id = ExtensionCostObservation(
        _evidence("m11/check-duplicate.json", _m11_payload("check", "new_check"))
    )
    with pytest.raises(ProtocolViolation, match="extension ids must be unique"):
        extension_cost((first, duplicate_id))


def test_exact_path_bytes_and_hash_provenance_rejects_tampering_and_callbacks() -> None:
    payload = {
        "schema_version": M09_POINT_SCHEMA,
        "task": "diagnosis",
        "train_fraction_percent": 1,
        "train_examples": 10,
        "proper_score": 1.0,
    }
    exact = canonical_json_bytes(payload)
    with pytest.raises(ProtocolViolation, match="digest does not bind"):
        CanonicalMetricEvidence(
            "m09/point.json",
            exact.replace(b"1.0", b"2.0"),
            digest_bytes(exact),
        )
    with pytest.raises(ProtocolViolation, match="canonical POSIX relative path"):
        CanonicalMetricEvidence("../escape.json", exact, digest_bytes(exact))
    with pytest.raises(ProtocolViolation, match="exact non-empty bytes"):
        CanonicalMetricEvidence(
            "m09/callback.json",  # type: ignore[arg-type]
            lambda: exact,
            digest_bytes(exact),
        )

    # Re-signing bytes cannot turn a missing field into a valid typed record.
    missing = copy.deepcopy(payload)
    missing.pop("proper_score")
    with pytest.raises(ProtocolViolation, match="schema mismatch"):
        LearningCurvePoint(_evidence("m09/resigned.json", missing))


def test_nonfinite_empty_negative_and_bool_inputs_fail_closed() -> None:
    with pytest.raises(ProtocolViolation, match="exactly 18"):
        sample_efficiency(())
    with pytest.raises(ProtocolViolation, match="cannot be empty"):
        combination_generalization(())
    with pytest.raises(ProtocolViolation, match="non-empty tuple"):
        extension_cost(())

    with pytest.raises(ProtocolViolation, match="non-negative exact integer"):
        _m09_point("diagnosis", 1, -1, 1.0)
    negative = _m11_payload("negative", "new_check")
    negative["old_benchmark_denominator"] = -1
    with pytest.raises(ProtocolViolation, match="non-negative exact integer"):
        _m11_observation(negative)
    bool_denominator = _m11_payload("bool-denominator", "new_check")
    bool_denominator["old_benchmark_denominator"] = True
    with pytest.raises(ProtocolViolation, match="exact integer"):
        _m11_observation(bool_denominator)
    with pytest.raises(ProtocolViolation, match="finite number"):
        _m09_point("diagnosis", 1, 1, 10**400)

    for token in (b"NaN", b"Infinity", b"-Infinity"):
        raw = b'{"value":' + token + b"}\n"
        with pytest.raises(ProtocolViolation, match="NaN/Infinity"):
            CanonicalMetricEvidence("invalid/nonfinite.json", raw, digest_bytes(raw))


def test_derived_floating_arithmetic_overflow_fails_closed() -> None:
    counts = (10, 50, 100, 250, 500, 1000)
    overflowing_curve = tuple(
        _m09_point(task, fraction, count, 1e308)
        for task in ("diagnosis", "natural_forecast", "intervention")
        for fraction, count in zip(TRAIN_FRACTION_PERCENTS, counts, strict=True)
    )
    with pytest.raises(ProtocolViolation, match="derived arithmetic"):
        sample_efficiency(overflowing_curve)

    overflowing_gap = (
        _m10_pair(
            stratum="heldout_mechanism_combination",
            pair_id="overflow",
            heldout=1e308,
            seen=-1e308,
        ),
        _m10_pair(
            stratum="heldout_host_modifier",
            pair_id="safe",
            heldout=1.0,
            seen=0.0,
        ),
        _m10_pair(
            stratum="heldout_nonlinear_comorbidity",
            pair_id="safe",
            heldout=1.0,
            seen=0.0,
        ),
    )
    with pytest.raises(ProtocolViolation, match="derived arithmetic"):
        combination_generalization(overflowing_gap)

    overflowing_sum = (
        _m10_pair(
            stratum="heldout_mechanism_combination",
            pair_id="p1",
            heldout=1e308,
            seen=0.0,
        ),
        _m10_pair(
            stratum="heldout_mechanism_combination",
            pair_id="p2",
            heldout=1e308,
            seen=0.0,
        ),
        *_m10_fixture()[2:],
    )
    with pytest.raises(ProtocolViolation, match="derived arithmetic overflow"):
        combination_generalization(overflowing_sum)

    regression = _m11_payload("overflow-regression", "new_treatment")
    regression["old_benchmark_before_score"] = -1e308
    regression["old_benchmark_after_score"] = 1e308
    with pytest.raises(ProtocolViolation, match="derived arithmetic"):
        extension_cost((_m11_observation(regression),))
