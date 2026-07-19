from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from prototype.unified_map import benchmark_v1_runner as benchmark_runner
from prototype.unified_map.benchmark_v1_freeze import FREEZE_FILENAME
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from prototype.unified_map.postseal_confirm5 import (
    CONFIRM_ALIASES,
    DURABLE_SEAL_COMMIT,
    PURPOSE,
    build_commitment,
    build_secret,
)
from prototype.unified_map.postseal_confirm5_runner import (
    BATCH_MANIFEST_PROTOCOL,
    CANDIDATE_SPECS,
    BatchConfig,
    run_postseal_confirm5_batch,
    verify_postseal_confirm5_batch,
)


ROOT = Path(__file__).resolve().parents[2]


def _candidate_source_digest() -> str:
    relative = "prototype/unified_map/candidate_families.py"
    raw = (ROOT / relative).read_bytes()
    return digest_json(
        [
            {
                "relative_path": relative,
                "byte_length": len(raw),
                "sha256": digest_bytes(raw),
            }
        ]
    )


def _authority_files(tmp_path: Path) -> tuple[Path, Path, dict]:
    rows = [
        {
            "confirm_alias": alias,
            "train_root_seed": 1000 + index * 10 + 1,
            "validation_root_seed": 1000 + index * 10 + 2,
            "sealed_test_root_seed": 1000 + index * 10 + 3,
        }
        for index, alias in enumerate(CONFIRM_ALIASES)
    ]
    secret = build_secret(rows, candidate_source_digest=_candidate_source_digest())
    commitment = build_commitment(secret)
    secret_path = tmp_path / "private-secret.json"
    commitment_path = tmp_path / "public-commitment.json"
    secret_path.write_bytes(canonical_json_bytes(secret))
    commitment_path.write_bytes(canonical_json_bytes(commitment))
    return secret_path, commitment_path, commitment


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_complete_config_defaults_to_frozen_confirm5_allocation() -> None:
    config = BatchConfig()
    assert config.complete_benchmark is True
    assert config.train_episodes_per_panel == 32
    assert config.validation_episodes_per_panel == 8
    assert config.test_episodes_per_panel == 16
    assert config.pair_probe_limit_per_declaration == 2
    assert config.to_wire()["confirm_aliases"] == list(CONFIRM_ALIASES)
    assert config.to_wire()["candidate_order"] == [
        "F10",
        "F14",
        "F18",
        "B02V2",
        "B03V2",
    ]


def test_one_world_batch_materializes_once_per_alias_and_children_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret_path, commitment_path, commitment = _authority_files(tmp_path)
    results_root = tmp_path / "results"
    config = BatchConfig(
        world_slots=("W01",),
        train_episodes_per_panel=1,
        validation_episodes_per_panel=1,
        test_episodes_per_panel=1,
        pair_probe_limit_per_declaration=0,
    )

    # Count materializer entries rather than oracle-cache misses.  The suite
    # must call each expensive builder once per alias, not once per candidate.
    counts = {"training": 0, "sealed": 0, "pairs": 0}
    original_training = benchmark_runner._training_records
    original_sealed = benchmark_runner._sealed_evaluation_rows
    original_pairs = benchmark_runner._precompute_pair_oracles

    def counted_training(*args, **kwargs):
        counts["training"] += 1
        return original_training(*args, **kwargs)

    def counted_sealed(*args, **kwargs):
        counts["sealed"] += 1
        return original_sealed(*args, **kwargs)

    def counted_pairs(*args, **kwargs):
        counts["pairs"] += 1
        return original_pairs(*args, **kwargs)

    monkeypatch.setattr(benchmark_runner, "_training_records", counted_training)
    monkeypatch.setattr(benchmark_runner, "_sealed_evaluation_rows", counted_sealed)
    monkeypatch.setattr(benchmark_runner, "_precompute_pair_oracles", counted_pairs)
    monkeypatch.setenv("UCM_ORACLE_WORKERS", "2")

    batch_path = run_postseal_confirm5_batch(
        secret_path=secret_path,
        commitment_path=commitment_path,
        freeze_path=ROOT / FREEZE_FILENAME,
        results_root=results_root,
        config=config,
    )
    assert counts == {"training": 5, "sealed": 5, "pairs": 5}

    batch = verify_postseal_confirm5_batch(batch_path)
    assert batch["protocol"] == BATCH_MANIFEST_PROTOCOL
    assert batch["purpose"] == PURPOSE
    assert batch["durable_seal_commit"] == DURABLE_SEAL_COMMIT
    assert batch["judge_materialization_count"] == 5
    assert batch["oracle_workers"] == 2
    assert [row["family_code"] for row in batch["children"]] == [
        spec.family_code for spec in CANDIDATE_SPECS
    ]
    assert len({row["run_id"] for row in batch["children"]}) == 5

    expected_commitments = {
        row["confirm_alias"]: row["commitment"]
        for row in commitment["row_commitments"]
    }
    required_sources = {
        "prototype/unified_map/postseal_confirm5_runner.py",
        "prototype/unified_map/benchmark_v1_runner.py",
        "prototype/unified_map/benchmark_v1_authority.py",
        "prototype/unified_map/postseal_confirm5.py",
        "prototype/unified_map/baselines_v2.py",
        "prototype/unified_map/candidate_families.py",
    }
    for child_row in batch["children"]:
        child = batch_path / Path(*child_row["relative_path"].split("/"))
        summary = benchmark_runner.verify_run_bundle(child)
        assert summary["seed_authority"]["supplemental_postseal_confirm"] is True
        assert summary["seed_authority"]["original_freeze_seed_authority"] is False
        assert summary["supplemental_confirmation"]["confirm_aliases"] == list(
            CONFIRM_ALIASES
        )
        assert summary["claim_boundary"]["original_freeze_seeds"] is False
        assert len(summary["replicates"]) == 5
        for replicate, alias in zip(
            summary["replicates"], CONFIRM_ALIASES, strict=True
        ):
            assert replicate["confirm_alias"] == alias
            assert replicate["seed_commitment"] == expected_commitments[alias]
            assert replicate["training_record_count"] == 1
        assert len(_jsonl(child / "raw-episodes.jsonl")) == 5
        assert (child / "raw-pairs.jsonl").read_bytes() == b""
        for name in ("raw-episodes.jsonl", "raw-pairs.jsonl"):
            raw_path = child / name
            compressed_path = child / f"{name}.gz"
            compressed = compressed_path.read_bytes()
            assert compressed[:3] == b"\x1f\x8b\x08"
            assert compressed[3] & 0x08 == 0  # no host filename in header
            assert compressed[4:8] == b"\0\0\0\0"  # deterministic mtime
            assert gzip.decompress(compressed) == raw_path.read_bytes()
        assert {
            row["relative_path"] for row in summary["source_binding"]["files"]
        } == required_sources
        # Simulate a clean clone: raw JSONL is ignored, deterministic gzip is
        # tracked, and the standard verifier must reconstruct manifest bytes.
        (child / "raw-episodes.jsonl").unlink()
        (child / "raw-pairs.jsonl").unlink()
        benchmark_runner.verify_run_bundle(child)
    verify_postseal_confirm5_batch(batch_path)


def test_batch_verifier_rejects_manifest_tamper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Avoid another model execution: create a canonical invalid batch manifest
    # whose root no longer matches after one field changes.
    path = tmp_path / "batch"
    path.mkdir()
    wire = {
        "protocol": BATCH_MANIFEST_PROTOCOL,
        "batch_id": "fixture",
        "purpose": PURPOSE,
        "confirm_aliases": list(CONFIRM_ALIASES),
        "durable_seal_commit": DURABLE_SEAL_COMMIT,
        "children": [],
    }
    wire["batch_root"] = digest_json(wire)
    wire["purpose"] = "tampered"
    (path / "batch-manifest.json").write_bytes(canonical_json_bytes(wire))
    with pytest.raises(ProtocolViolation, match="batch root mismatch"):
        verify_postseal_confirm5_batch(path)
