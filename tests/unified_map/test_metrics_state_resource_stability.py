from __future__ import annotations

from copy import deepcopy
import math
import zlib

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
)
from prototype.unified_map.metrics_state_resource_stability import (
    CODE_OWNED_COMPRESSOR_ID,
    HIERARCHICAL_BOOTSTRAP_BLOCKER,
    M12_ROW_SCHEMA,
    M13_MEASUREMENT_SCHEMA,
    M13_PROVENANCE_SCHEMA,
    CandidateOperation,
    CanonicalEvidence,
    CollectorProvenance,
    MetricDirection,
    ReplicateSeries,
    ResourceKind,
    ResourceMeasurement,
    StateSizeRow,
    five_seed_stability,
    resource_metrics,
    state_size_metrics,
)
from prototype.unified_map.seed_protocol import ZIPPED_REPLICATE_IDS


def _evidence(path: str, payload: dict) -> CanonicalEvidence:
    return CanonicalEvidence.from_payload(path, payload)


def _state_payload(
    index: int,
    *,
    candidate_id: str = "candidate-A",
    history_length: int | bool | float | None = None,
    horizon: int | bool = 1,
    task: str = "diagnosis",
    state: object | None = None,
) -> dict:
    return {
        "schema_version": M12_ROW_SCHEMA,
        "record_id": f"record-{index:02d}",
        "candidate_id": candidate_id,
        "scope_digest": "sha256:" + "a" * 64,
        "candidate_artifact_digest": "sha256:" + "b" * 64,
        "training_replicate_id": "train-01",
        "evaluation_replicate_id": "eval-01",
        "world_slot": "W01",
        "panel_id": "primary",
        "family_id": "family-01",
        "stratum_id": "main",
        "task": task,
        "episode_id": f"episode-{index:02d}",
        "cut_id": "cut-01",
        "expected_cell_id": f"cell-{index:02d}",
        "history_slope_grain_id": "matched-grain-01",
        "horizon": horizon,
        "policy_id": "no-op",
        "history_length": index if history_length is None else history_length,
        "canonical_state": (
            {"history": "x" * index, "value": index} if state is None else state
        ),
        "scalar_count": index,
        "node_count": 1,
        "edge_count": 0,
        "particle_count": 0,
    }


def _state_row(index: int, **kwargs: object) -> StateSizeRow:
    payload = _state_payload(index, **kwargs)
    return StateSizeRow(_evidence(f"m12/row-{index:02d}.json", payload))


def _provenance_payload(
    *,
    cold: bool = True,
    candidate_id: str = "candidate-A",
    run_id: str = "run-01",
    scope_digest: str = "sha256:" + "a" * 64,
    environment_digest: str = "sha256:" + "3" * 64,
) -> dict:
    digest = "sha256:" + "1" * 64
    return {
        "schema_version": M13_PROVENANCE_SCHEMA,
        "collector_id": "resource-collector",
        "collector_version": "1",
        "run_id": run_id,
        "candidate_id": candidate_id,
        "scope_digest": scope_digest,
        "collector_source_digest": digest,
        "collector_config_digest": "sha256:" + "2" * 64,
        "environment_digest": environment_digest,
        "clock_source": "perf_counter_ns",
        "memory_source": "wait4_maxrss_and_gpu_api",
        "started_at_utc": "2026-07-18T00:00:00Z",
        "finished_at_utc": "2026-07-18T00:01:00Z",
        "cold_process_per_sample": cold,
    }


def _provenance(
    *,
    cold: bool = True,
    suffix: str = "main",
    candidate_id: str = "candidate-A",
    run_id: str = "run-01",
    scope_digest: str = "sha256:" + "a" * 64,
    environment_digest: str = "sha256:" + "3" * 64,
) -> CollectorProvenance:
    return CollectorProvenance(
        _evidence(
            f"m13/provenance-{suffix}.json",
            _provenance_payload(
                cold=cold,
                candidate_id=candidate_id,
                run_id=run_id,
                scope_digest=scope_digest,
                environment_digest=environment_digest,
            ),
        )
    )


def _measurement(
    measurement_id: str,
    kind: ResourceKind,
    *,
    value: object = 1,
    operation: CandidateOperation | None = None,
    reason: str | None = None,
    provenance: CollectorProvenance | None = None,
    unit: str | None = None,
    candidate_id: str = "candidate-A",
) -> ResourceMeasurement:
    provenance = provenance or _provenance(
        suffix=measurement_id, candidate_id=candidate_id
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
    payload = {
        "schema_version": M13_MEASUREMENT_SCHEMA,
        "measurement_id": measurement_id,
        "run_id": provenance.run_id,
        "candidate_id": provenance.candidate_id,
        "scope_digest": provenance.scope_digest,
        "resource_kind": kind.value,
        "operation": None if operation is None else operation.value,
        "value": value,
        "unit": units[kind] if unit is None else unit,
        "undefined_reason": reason,
        "collector_provenance_digest": provenance.evidence.artifact_digest,
    }
    return ResourceMeasurement(
        _evidence(f"m13/measurement-{measurement_id}.json", payload), provenance
    )


def _series(
    values: tuple[float, ...],
    *,
    pairs: tuple[tuple[str, str], ...] = ZIPPED_REPLICATE_IDS,
) -> ReplicateSeries:
    return ReplicateSeries(pairs, values)


def test_m12_canonical_bytes_counts_hand_ols_and_slices() -> None:
    rows = (_state_row(1), _state_row(2), _state_row(3))
    result = state_size_metrics(rows).to_wire()

    expected_sizes = tuple(
        len(canonical_json_bytes(_state_payload(index)["canonical_state"]))
        for index in (1, 2, 3)
    )
    mean_x = 2.0
    mean_y = sum(expected_sizes) / 3.0
    expected_slope = sum(
        (x - mean_x) * (y - mean_y)
        for x, y in zip((1, 2, 3), expected_sizes, strict=True)
    ) / sum((x - mean_x) ** 2 for x in (1, 2, 3))

    assert [row["canonical_state_raw_bytes"] for row in result["rows"]] == list(
        expected_sizes
    )
    assert result["global_history_length_ols"]["status"] == "not_computed"
    assert result["history_length_ols_recipe"]["unit"] == (
        "byte_per_visible_history_event"
    )
    assert result["history_length_ols_by_matched_grain"][0]["slope"] == pytest.approx(
        expected_slope
    )
    assert result["rows"][2]["component_counts"] == {
        "verification_status": "caller_asserted_unverified",
        "scalar_count": 3,
        "node_count": 1,
        "edge_count": 0,
        "particle_count": 0,
    }
    assert result["task_horizon_slices"][0]["exposure"] == 3
    assert result["task_horizon_slices"][0]["task"] == "diagnosis"


def test_m12_aux_compression_is_exact_code_owned_recipe_and_raw_is_primary() -> None:
    row = _state_row(9)
    wire = state_size_metrics((row,)).to_wire()
    raw = canonical_json_bytes(_state_payload(9)["canonical_state"])
    assert row.compressed_bytes == len(zlib.compress(raw, level=9))
    assert wire["compressor"]["compressor_id"] == CODE_OWNED_COMPRESSOR_ID
    assert wire["compressed_bytes_role"] == "auxiliary_only"
    assert wire["raw_byte_direction"] == "minimize"
    assert wire["history_length_ols_by_matched_grain"][0] | {
        "grain": wire["history_length_ols_by_matched_grain"][0]["grain"]
    } == {
        "grain": wire["history_length_ols_by_matched_grain"][0]["grain"],
        "status": "undefined",
        "undefined_reason": "fewer_than_two_rows",
        "slope": None,
        "exposure": 1,
    }


def test_m12_zero_history_variance_is_typed_undefined_and_input_order_is_inert() -> (
    None
):
    left = _state_row(1, history_length=4)
    right = _state_row(2, history_length=4)
    first = state_size_metrics((left, right)).to_wire()
    second = state_size_metrics((right, left)).to_wire()
    assert first == second
    assert first["history_length_ols_by_matched_grain"][0]["status"] == "undefined"
    assert first["history_length_ols_by_matched_grain"][0]["undefined_reason"] == (
        "zero_predictor_variance"
    )


@pytest.mark.parametrize(
    ("field", "bad"),
    (
        ("history_length", True),
        ("horizon", False),
        ("scalar_count", True),
        ("node_count", -1),
        ("edge_count", 1.5),
        ("particle_count", 2**60),
    ),
)
def test_m12_rejects_bool_negative_and_ragged_schema(field: str, bad: object) -> None:
    payload = _state_payload(1)
    payload[field] = bad
    with pytest.raises(ProtocolViolation):
        StateSizeRow(_evidence("m12/bad.json", payload))

    ragged = _state_payload(1)
    ragged["extra"] = 1
    with pytest.raises(ProtocolViolation, match="schema mismatch"):
        StateSizeRow(_evidence("m12/ragged.json", ragged))


def test_m12_rejects_duplicate_record_cell_and_mixed_candidate() -> None:
    row = _state_row(1)
    with pytest.raises(ProtocolViolation, match="record_id"):
        state_size_metrics((row, row))

    same_cell = _state_payload(1)
    same_cell["record_id"] = "different-record"
    with pytest.raises(ProtocolViolation, match="cell identities"):
        state_size_metrics(
            (row, StateSizeRow(_evidence("m12/same-cell.json", same_cell)))
        )

    with pytest.raises(ProtocolViolation, match="one candidate"):
        state_size_metrics((row, _state_row(2, candidate_id="candidate-B")))


def test_m12_rejects_task_policy_fanout_reweighting_of_same_state() -> None:
    left_payload = _state_payload(1)
    right_payload = deepcopy(left_payload)
    right_payload.update(
        {
            "record_id": "record-fanout",
            "expected_cell_id": "cell-fanout",
            "task": "intervention",
            "policy_id": "A1",
        }
    )
    left = StateSizeRow(_evidence("m12/fanout-left.json", left_payload))
    right = StateSizeRow(_evidence("m12/fanout-right.json", right_payload))
    with pytest.raises(ProtocolViolation, match="fanout"):
        state_size_metrics((left, right))


def test_m12_history_slope_is_matched_grain_stratified_not_global() -> None:
    payloads = [_state_payload(index) for index in (1, 2, 3, 4)]
    for payload in payloads[2:]:
        payload["history_slope_grain_id"] = "matched-grain-02"
    rows = tuple(
        StateSizeRow(_evidence(f"m12/grain-{index}.json", payload))
        for index, payload in enumerate(payloads, start=1)
    )
    wire = state_size_metrics(rows).to_wire()
    assert wire["global_history_length_ols"] == {
        "status": "not_computed",
        "reason": "cross_grain_ols_would_be_confounding",
    }
    assert len(wire["history_length_ols_by_matched_grain"]) == 2
    assert {
        row["grain"]["history_slope_grain_id"]
        for row in wire["history_length_ols_by_matched_grain"]
    } == {"matched-grain-01", "matched-grain-02"}


@pytest.mark.parametrize(
    ("field", "value", "match"),
    (
        ("scope_digest", "sha256:" + "c" * 64, "scope authority"),
        (
            "candidate_artifact_digest",
            "sha256:" + "c" * 64,
            "candidate artifact authority",
        ),
        ("training_replicate_id", "train-02", "zipped replicate authority"),
    ),
)
def test_m12_rejects_mixed_scope_artifact_and_replicate_authority(
    field: str, value: str, match: str
) -> None:
    left = _state_row(1)
    payload = _state_payload(2)
    payload[field] = value
    if field == "training_replicate_id":
        payload["evaluation_replicate_id"] = "eval-02"
    right = StateSizeRow(_evidence(f"m12/mixed-{field}.json", payload))
    with pytest.raises(ProtocolViolation, match=match):
        state_size_metrics((left, right))


def test_m12_rejects_noncanonical_training_evaluation_pair() -> None:
    payload = _state_payload(1)
    payload["evaluation_replicate_id"] = "eval-02"
    with pytest.raises(ProtocolViolation, match="canonical zipped pair"):
        StateSizeRow(_evidence("m12/bad-pair.json", payload))


def test_canonical_evidence_rejects_digest_noncanonical_bytes_and_bad_path() -> None:
    raw = canonical_json_bytes({"x": 1})
    with pytest.raises(ProtocolViolation, match="digest"):
        CanonicalEvidence("evidence/x.json", raw, "sha256:" + "0" * 64)
    noncanonical = b'{"x": 1}\n'
    with pytest.raises(ProtocolViolation, match="canonical"):
        CanonicalEvidence("evidence/x.json", noncanonical, digest_bytes(noncanonical))
    with pytest.raises(ProtocolViolation, match="relative path"):
        CanonicalEvidence.from_payload("../x.json", {"x": 1})

    with pytest.raises(ProtocolViolation, match="representable as canonical JSON"):
        CanonicalEvidence.from_payload("evidence/huge.json", {"x": 10**10000})

    huge_integer_bytes = b'{"x":' + (b"9" * 10001) + b"}\n"
    with pytest.raises(ProtocolViolation, match="strict UTF-8 JSON"):
        CanonicalEvidence(
            "evidence/huge-bytes.json",
            huge_integer_bytes,
            digest_bytes(huge_integer_bytes),
        )


def test_m13_hf7_cold_latency_and_provenance_bound_resources() -> None:
    measurements: list[ResourceMeasurement] = []
    for index, value in enumerate((10, 20, 30, 40, 50), start=1):
        measurements.append(
            _measurement(
                f"init-{index}",
                ResourceKind.COLD_LATENCY,
                value=value,
                operation=CandidateOperation.INITIALIZE,
            )
        )
    measurements.extend(
        (
            _measurement("rss", ResourceKind.PEAK_RSS, value=4096),
            _measurement(
                "gpu", ResourceKind.PEAK_GPU_MEMORY, value=None, reason="gpu_absent"
            ),
            _measurement("model", ResourceKind.MODEL_ARTIFACT_BYTES, value=1024),
            _measurement("train-time", ResourceKind.TRAIN_WALL_TIME, value=12.5),
            _measurement("train-flops", ResourceKind.TRAIN_FLOPS, value=2_500_000_000),
            _measurement("ext-time", ResourceKind.POSTSEAL_WORKER_WALL_TIME, value=3.5),
            _measurement("ext-rss", ResourceKind.POSTSEAL_WORKER_PEAK_RSS, value=2048),
        )
    )
    wire = resource_metrics(tuple(reversed(measurements))).to_wire()
    initialize = wire["cold_latency_by_operation"][0]
    assert initialize["operation"] == "initialize"
    assert initialize["p50"] == 30
    assert initialize["p95"] == pytest.approx(48)
    assert initialize["p99"] == pytest.approx(49.6)
    assert initialize["defined_exposure"] == 5
    assert all(
        evidence["collector_provenance"]["artifact_digest"].startswith("sha256:")
        for evidence in initialize["evidence"]
    )
    by_kind = {item["resource_kind"]: item for item in wire["resource_measurements"]}
    assert by_kind["peak_rss"]["value"] == 4096
    assert by_kind["peak_gpu_memory"]["status"] == "undefined"
    assert by_kind["peak_gpu_memory"]["undefined_reason"] == "gpu_absent"
    assert by_kind["postseal_worker_peak_gpu_memory"]["undefined_reason"] == (
        "not_provided_no_coverage_claim"
    )
    assert wire["collector_evidence_status"] == "partial_untrusted_collector"
    assert wire["collector_authority"] == "caller_asserted"
    assert wire["coverage"]["claim"] == "provided_exposure_only"
    assert wire["coverage"]["expected_measurement_count"] is None


def test_m13_missing_operations_and_resources_are_typed_undefined() -> None:
    wire = resource_metrics(()).to_wire()
    assert {row["operation"] for row in wire["cold_latency_by_operation"]} == {
        "initialize",
        "update",
        "diagnose",
        "rollout",
    }
    assert all(
        row["status"] == "undefined" for row in wire["cold_latency_by_operation"]
    )
    assert all(
        row["defined_exposure"] == 0 for row in wire["cold_latency_by_operation"]
    )
    assert all(row["status"] == "undefined" for row in wire["resource_measurements"])
    assert wire["coverage"] == {
        "claim": "provided_exposure_only",
        "provided_measurement_count": 0,
        "expected_measurement_count": None,
        "coverage_denominator": None,
        "coverage_complete": None,
        "deletion_detection": "unavailable_without_bound_expected_cells",
    }


def test_m13_rejects_non_cold_latency_wrong_unit_and_provenance_drift() -> None:
    non_cold = _provenance(cold=False)
    with pytest.raises(ProtocolViolation, match="not cold"):
        _measurement(
            "latency",
            ResourceKind.COLD_LATENCY,
            value=1,
            operation=CandidateOperation.UPDATE,
            provenance=non_cold,
        )
    with pytest.raises(ProtocolViolation, match="unit"):
        _measurement("rss", ResourceKind.PEAK_RSS, value=1, unit="kilobyte")

    provenance = _provenance()
    payload = {
        "schema_version": M13_MEASUREMENT_SCHEMA,
        "measurement_id": "drift",
        "run_id": "run-01",
        "candidate_id": "candidate-A",
        "scope_digest": "sha256:" + "a" * 64,
        "resource_kind": ResourceKind.PEAK_RSS.value,
        "operation": None,
        "value": 1,
        "unit": "byte",
        "undefined_reason": None,
        "collector_provenance_digest": "sha256:" + "0" * 64,
    }
    with pytest.raises(ProtocolViolation, match="provenance bytes"):
        ResourceMeasurement(_evidence("m13/drift.json", payload), provenance)


@pytest.mark.parametrize("bad", [True, 1.0, -1, math.nan, math.inf, 10**1000])
def test_m13_rejects_bool_negative_nonfinite_and_overflow(bad: object) -> None:
    with pytest.raises(ProtocolViolation):
        _measurement("bad", ResourceKind.PEAK_RSS, value=bad)


def test_m13_rejects_duplicate_ids_duplicate_scalar_resource_and_mixed_candidates() -> (
    None
):
    first = _measurement("rss-a", ResourceKind.PEAK_RSS, value=1)
    second = _measurement("rss-b", ResourceKind.PEAK_RSS, value=2)
    with pytest.raises(ProtocolViolation, match="at most one"):
        resource_metrics((first, second))
    with pytest.raises(ProtocolViolation, match="measurement_id"):
        resource_metrics((first, first))
    other = _measurement(
        "model-other",
        ResourceKind.MODEL_ARTIFACT_BYTES,
        value=1,
        candidate_id="candidate-B",
    )
    with pytest.raises(ProtocolViolation, match="cannot mix"):
        resource_metrics((first, other))


@pytest.mark.parametrize(
    ("started", "finished"),
    (
        ("2026-7-18T00:00:00Z", "2026-07-18T00:01:00Z"),
        ("2026-02-30T00:00:00Z", "2026-07-18T00:01:00Z"),
        ("2026-07-18T00:02:00Z", "2026-07-18T00:01:00Z"),
        ("2026-07-18T00:00:00+00:00", "2026-07-18T00:01:00Z"),
    ),
)
def test_m13_provenance_requires_ordered_strict_rfc3339(
    started: str, finished: str
) -> None:
    payload = _provenance_payload()
    payload["started_at_utc"] = started
    payload["finished_at_utc"] = finished
    with pytest.raises(ProtocolViolation):
        CollectorProvenance(_evidence("m13/bad-time.json", payload))


@pytest.mark.parametrize(
    "other_provenance",
    (
        _provenance(suffix="mix-env", environment_digest="sha256:" + "4" * 64),
        _provenance(suffix="mix-run", run_id="run-02"),
        _provenance(suffix="mix-candidate", candidate_id="candidate-B"),
        _provenance(suffix="mix-scope", scope_digest="sha256:" + "c" * 64),
    ),
)
def test_m13_rejects_mixed_provenance_environment_run_candidate_scope(
    other_provenance: CollectorProvenance,
) -> None:
    first = _measurement("base", ResourceKind.PEAK_RSS, value=1)
    second = _measurement(
        "other",
        ResourceKind.MODEL_ARTIFACT_BYTES,
        value=1,
        provenance=other_provenance,
    )
    with pytest.raises(ProtocolViolation, match="cannot mix"):
        resource_metrics((first, second))


def test_m13_each_value_retains_exact_provenance_bytes_and_digest() -> None:
    measurement = _measurement("rss-bound", ResourceKind.PEAK_RSS, value=3)
    wire = resource_metrics((measurement,)).to_wire()
    row = next(
        item
        for item in wire["resource_measurements"]
        if item["resource_kind"] == "peak_rss"
    )
    reference = row["evidence"]["collector_provenance"]
    exact = bytes.fromhex(reference["canonical_bytes_hex"])
    assert digest_bytes(exact) == reference["artifact_digest"]
    assert exact == measurement.provenance.evidence.canonical_bytes


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("run_id", "run-02"),
        ("candidate_id", "candidate-B"),
        ("scope_digest", "sha256:" + "c" * 64),
    ),
)
def test_m13_measurement_identity_must_equal_its_provenance(
    field: str, value: str
) -> None:
    measurement = _measurement("identity", ResourceKind.PEAK_RSS, value=1)
    payload = deepcopy(measurement.evidence.payload)
    payload[field] = value
    with pytest.raises(ProtocolViolation, match="differs from provenance"):
        ResourceMeasurement(
            _evidence(f"m13/mismatch-{field}.json", payload), measurement.provenance
        )


def test_m14_five_seed_hand_summary_and_zipped_paired_t_df4() -> None:
    candidate = _series((1.0, 2.0, 3.0, 4.0, 5.0))
    baseline = _series((0.5, 1.5, 2.5, 3.5, 4.5))
    wire = five_seed_stability(
        metric_name="diagnostic_nll",
        unit="nat_per_case",
        direction=MetricDirection.MINIMIZE,
        candidate=candidate,
        baseline=baseline,
    ).to_wire()

    expected_sd = math.sqrt(2.5)
    expected_half_width = 2.7764451051977987 * expected_sd / math.sqrt(5)
    assert wire["candidate"]["mean"] == 3.0
    assert wire["candidate"]["sample_sd"] == pytest.approx(expected_sd)
    assert wire["candidate"]["min"] == 1.0
    assert wire["candidate"]["max"] == 5.0
    assert wire["candidate"]["ci95_lower"] == pytest.approx(3.0 - expected_half_width)
    assert wire["candidate"]["ci95_upper"] == pytest.approx(3.0 + expected_half_width)
    assert wire["paired_baseline"]["paired_deltas"] == [0.5] * 5
    assert wire["paired_baseline"]["summary"]["mean"] == 0.5
    assert wire["paired_baseline"]["summary"]["sample_sd"] == 0.0
    assert wire["pairing"]["method"] == "same_index_zipped_replicate"
    assert wire["pairing"]["cartesian_5x5_forbidden"] is True
    assert wire["pairing"]["authority"] == "seed_protocol.ZIPPED_REPLICATE_IDS"
    assert wire["pairing"]["replicate_pairs"] == [
        {
            "training_replicate_id": training_id,
            "evaluation_replicate_id": evaluation_id,
        }
        for training_id, evaluation_id in ZIPPED_REPLICATE_IDS
    ]
    assert wire["seed_ci95_recipe"]["degrees_of_freedom"] == 4


def test_m14_ties_have_zero_width_ci_and_bootstrap_is_honestly_unavailable() -> None:
    wire = five_seed_stability(
        metric_name="latency",
        unit="nanosecond",
        direction=MetricDirection.MINIMIZE,
        candidate=_series((7.0, 7.0, 7.0, 7.0, 7.0)),
    ).to_wire()
    assert wire["candidate"]["sample_sd"] == 0.0
    assert wire["candidate"]["ci95_lower"] == 7.0
    assert wire["candidate"]["ci95_upper"] == 7.0
    assert wire["paired_baseline"] is None
    assert wire["hierarchical_bootstrap_ci95"] == {
        "status": "unavailable",
        "undefined_reason": "sampling_preimage_endpoint_rule_and_analysis_seed_unbound",
        "blocker_code": HIERARCHICAL_BOOTSTRAP_BLOCKER,
        "required_replicates": 10000,
    }


def test_m14_rejects_wrong_count_arbitrary_ids_ragged_and_permutation() -> None:
    with pytest.raises(ProtocolViolation, match="exactly five"):
        ReplicateSeries((ZIPPED_REPLICATE_IDS[0],), (1.0,))
    with pytest.raises(ProtocolViolation, match="exact pair"):
        ReplicateSeries(
            (
                ("train-01", "eval-01", "extra"),  # type: ignore[arg-type]
                *ZIPPED_REPLICATE_IDS[1:],
            ),
            (1.0,) * 5,
        )
    arbitrary = tuple(
        (training_id, "eval-99" if index == 4 else evaluation_id)
        for index, (training_id, evaluation_id) in enumerate(ZIPPED_REPLICATE_IDS)
    )
    with pytest.raises(ProtocolViolation, match="ZIPPED_REPLICATE_IDS"):
        ReplicateSeries(arbitrary, (1.0,) * 5)
    with pytest.raises(ProtocolViolation, match="ZIPPED_REPLICATE_IDS"):
        ReplicateSeries(tuple(reversed(ZIPPED_REPLICATE_IDS)), (1.0,) * 5)


@pytest.mark.parametrize("bad", [True, math.nan, math.inf, 10**1000])
def test_m14_rejects_bool_nonfinite_and_input_overflow(bad: object) -> None:
    with pytest.raises(ProtocolViolation):
        _series((bad, 1.0, 2.0, 3.0, 4.0))


def test_m14_rejects_derived_delta_overflow_and_untyped_direction() -> None:
    with pytest.raises(ProtocolViolation, match="non-finite"):
        five_seed_stability(
            metric_name="m",
            unit="u",
            direction=MetricDirection.MAXIMIZE,
            candidate=_series((1e308,) * 5),
            baseline=_series((-1e308,) * 5),
        )
    with pytest.raises(ProtocolViolation, match="typed MetricDirection"):
        five_seed_stability(
            metric_name="m",
            unit="u",
            direction="minimize",  # type: ignore[arg-type]
            candidate=_series((1.0,) * 5),
        )


def test_all_results_remain_pre_freeze_unbound_and_have_no_single_score() -> None:
    wires = (
        state_size_metrics((_state_row(1),)).to_wire(),
        resource_metrics(()).to_wire(),
        five_seed_stability(
            metric_name="m",
            unit="u",
            direction=MetricDirection.MAXIMIZE,
            candidate=_series((1.0,) * 5),
        ).to_wire(),
    )
    for wire in wires:
        assert wire["benchmark_status"] == "PRE-FREEZE"
        assert wire["evidence_qualification"] == "runtime_only"
        assert wire["runtime_binding"] == "isolated_unbound"
        assert wire["input_authority"] == "caller_asserted_unbound"
        assert wire["coverage_scope"] == "provided_exposure_only"
        assert wire["freeze_authority"] is False
        assert wire["freeze_authority_status"] == "not_claimed"
        assert wire["cross_metric_aggregate_score"] == "forbidden"
        assert wire["no_single_score"] is True
        assert "aggregate_score" not in wire


def test_m13_provenance_ragged_bool_and_noncanonical_inputs_fail_closed() -> None:
    payload = _provenance_payload()
    payload["extra"] = 1
    with pytest.raises(ProtocolViolation, match="schema mismatch"):
        CollectorProvenance(_evidence("m13/ragged-provenance.json", payload))

    bad = _provenance_payload()
    bad["cold_process_per_sample"] = 1
    with pytest.raises(ProtocolViolation, match="exact boolean"):
        CollectorProvenance(_evidence("m13/bool-provenance.json", bad))

    measurement = _measurement("defined", ResourceKind.PEAK_RSS, value=1)
    body = deepcopy(measurement.evidence.payload)
    body["undefined_reason"] = "contradiction"
    with pytest.raises(ProtocolViolation, match="cannot carry"):
        ResourceMeasurement(
            _evidence("m13/contradiction.json", body), measurement.provenance
        )
