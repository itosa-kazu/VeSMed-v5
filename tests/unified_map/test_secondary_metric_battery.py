from __future__ import annotations

from dataclasses import replace

import pytest

from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes
from prototype.unified_map.secondary_metric_battery import (
    METRIC_IDS,
    ORDINARY_FAMILY_CODES,
    SecondaryBatteryConfig,
    conditional_expected_future_statistic,
    execute_secondary_battery,
    make_battery_candidate,
    verify_secondary_bundle,
    write_secondary_bundle,
)
from prototype.unified_map.worlds.base import WorldSplit
from prototype.unified_map.worlds.w01 import World as World01


def test_family_registry_covers_f01_through_f22_and_path_ablations() -> None:
    expected = {f"F{index:02d}" for index in range(1, 23)} | {"F09S", "F09L"}
    assert set(ORDINARY_FAMILY_CODES) == expected
    for family in ORDINARY_FAMILY_CODES:
        candidate = make_battery_candidate(family)
        assert candidate.candidate_id
        assert candidate.family_id


def test_configuration_is_serial_and_rejects_nonordinary_baselines() -> None:
    with pytest.raises(ProtocolViolation, match="single-worker"):
        SecondaryBatteryConfig(worker_count=2)
    with pytest.raises(ProtocolViolation, match="ordinary-family"):
        SecondaryBatteryConfig(families=("B02V2",))


def test_new_readout_target_is_expected_future_not_realized_factual_noise() -> None:
    world = World01()
    episode = world.generate_episode(WorldSplit.SEALED_TEST, 701, 3)
    target = conditional_expected_future_statistic(world, episode)
    mutated_factual = replace(
        episode,
        factual_future=[{"deliberately": "unrelated-realized-noise"}],
        factual_utility=999.0,
    )
    assert conditional_expected_future_statistic(world, mutated_factual) == target
    shifted = replace(
        episode,
        hidden_state_at_cut={
            "x": [
                episode.hidden_state_at_cut["x"][0] + 0.5,
                episode.hidden_state_at_cut["x"][1],
            ]
        },
    )
    assert conditional_expected_future_statistic(world, shifted) != target


def test_focused_single_family_battery_runs_all_secondary_probes() -> None:
    config = SecondaryBatteryConfig(
        families=("F01",),
        metrics=METRIC_IDS,
        below_normal_priority=False,
        m09_train_sizes=(1,),
        m09_validation_examples=1,
        m10_train_examples=1,
        m10_pair_count=1,
        m11_primary_train_examples=1,
        m11_extension_train_examples=1,
        m13_train_examples=1,
        m16_candidate_train_examples=2,
        m16_readout_train_examples=4,
        m16_readout_validation_examples=2,
        m16_readout_test_examples=2,
        m16_max_capacity=2,
    )
    result = execute_secondary_battery(config)
    assert {row["metric"] for row in result["rows"]} == set(METRIC_IDS)
    assert result["worker_count"] == 1
    assert result["formal_frozen_metric_claim"] is False

    extension = [row for row in result["rows"] if row["metric"] == "M11"]
    assert {row["world"] for row in extension} == {"W16", "W17"}
    assert all(row["scope_insufficient"] for row in extension)
    assert all(row["old_state_unchanged_after_query"] for row in extension)
    assert all(row["migration_disposition"].startswith("explicit_full_retrain") for row in extension)

    readout = [row for row in result["rows"] if row["metric"] == "M16"]
    assert readout
    assert all(row["same_capacity_for_state_and_history"] for row in readout)
    assert all(row["target_is_conditional_expectation_not_realized_noise"] for row in readout)
    assert all(row["candidate_received_true_or_future"] is False for row in readout)


@pytest.mark.parametrize("family", ("F09S", "F09L", "F22"))
def test_variant_and_supplemental_family_routes_are_executable(family: str) -> None:
    result = execute_secondary_battery(
        SecondaryBatteryConfig(
            families=(family,),
            metrics=("M13",),
            below_normal_priority=False,
            m13_train_examples=1,
        )
    )
    assert len(result["rows"]) == 5
    assert {row["family"] for row in result["rows"]} == {family}


def test_bundle_is_canonical_closed_and_tamper_evident(tmp_path) -> None:
    config = SecondaryBatteryConfig(
        families=("F01",),
        metrics=("M13",),
        below_normal_priority=False,
        m13_train_examples=1,
    )
    result = execute_secondary_battery(config)
    bundle = write_secondary_bundle(result, tmp_path)
    receipt = verify_secondary_bundle(bundle)
    assert receipt["status"] == "verified"
    assert receipt["row_count"] == 5
    for name in ("manifest.json", "summary.json"):
        raw = (bundle / name).read_bytes()
        assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    for line in (bundle / "raw.jsonl").read_bytes().splitlines(keepends=True):
        import json

        assert canonical_json_bytes(json.loads(line)) == line

    raw_path = bundle / "raw.jsonl"
    raw_path.write_bytes(raw_path.read_bytes() + b" ")
    with pytest.raises(ProtocolViolation, match="binding mismatch"):
        verify_secondary_bundle(bundle)
