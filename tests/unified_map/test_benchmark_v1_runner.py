from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototype.unified_map.benchmark_v1_freeze import (
    build_freeze_manifest,
    new_seed_secret,
)
from prototype.unified_map.benchmark_v1_runner import (
    RunConfig,
    run_benchmark,
    verify_run_bundle,
)
from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes


REPO = Path(__file__).resolve().parents[2]


def test_one_world_runner_publishes_unique_verifiable_raw_bundle(tmp_path: Path) -> None:
    secret = tmp_path / "secret.json"
    seed_preimage = new_seed_secret()
    secret.write_bytes(canonical_json_bytes(seed_preimage))
    freeze = tmp_path / "freeze.json"
    freeze.write_bytes(canonical_json_bytes(build_freeze_manifest(seed_preimage)))
    config = RunConfig(
        "EXP-TEST-RUNNER",
        "F01",
        {"regularization": 0.01},
        ("W01",),
        ("R01",),
        4,
        2,
        2,
        0,
    )
    path = run_benchmark(
        config,
        freeze_path=freeze,
        secret_path=secret,
        results_root=tmp_path / "runs",
    )
    summary = verify_run_bundle(path)
    assert summary["claim_boundary"]["screening_run"] is True
    assert summary["claim_boundary"]["complete_benchmark"] is False
    assert summary["replicates"][0]["training_record_count"] == 4
    assert summary["replicates"][0]["summary"]["worlds"]["W01"]["episode_count"] == 2
    assert summary["seed_preimages_published"] is False
    assert (path / "raw-episodes.jsonl").stat().st_size > 0

    # Exact member custody rejects even one-byte drift.
    raw_path = path / "raw-episodes.jsonl"
    raw_path.write_bytes(raw_path.read_bytes() + b" ")
    with pytest.raises(ProtocolViolation, match="member drifted"):
        verify_run_bundle(path)


def test_run_config_refuses_overstated_complete_or_oversized_subset() -> None:
    config = RunConfig(
        "EXP-SUBSET",
        "F01",
        {},
        ("W01",),
        ("R01",),
        1,
        1,
        1,
        0,
    )
    assert config.complete_benchmark is False
    with pytest.raises(ProtocolViolation, match="exceeds frozen allocation"):
        RunConfig(
            "EXP-TOO-LARGE",
            "F01",
            {},
            ("W01",),
            ("R01",),
            33,
            1,
            1,
            0,
        )
