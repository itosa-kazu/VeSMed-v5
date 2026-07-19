from __future__ import annotations

import json
import gzip
from pathlib import Path

from prototype.unified_map.benchmark_v1_freeze import (
    verify_freeze_manifest_bytes,
    verify_seed_reveal,
)
from prototype.unified_map.benchmark_v1_runner import verify_run_bundle
from prototype.unified_map.candidate_seal import verify_candidate_seal
from prototype.unified_map.canonical import digest_bytes, digest_json
from prototype.unified_map.canonical import canonical_json_bytes


ROOT = Path(__file__).resolve().parents[2]
FREEZE = ROOT / "research/unified_map/BENCHMARK_V1_FREEZE.json"
SEED_REVEAL = ROOT / "research/unified_map/BENCHMARK_V1_SEED_REVEAL.json"
SEAL = ROOT / "research/unified_map/CANDIDATE_SEAL.json"

FULL_RUNS = (
    "20260719T053350Z-EXP-033-2e4152df0d",
    "20260719T062956Z-EXP-034-f2409bcf72",
    "20260719T063049Z-EXP-035-c28452cba8",
)
UPPER_BOUND = "20260719T063711Z-EXP-036-c92d3b84cb"
REDTEAM = ROOT / "results/unified_map/redteam/20260719T064407Z-F18-redteam-69f7a4c8e6"
REPRODUCTION = ROOT / "results/unified_map/reproduction/20260719T065132Z-I18-repro-bc7f2fab24"
DEMO = ROOT / "results/unified_map/demo/20260719T065722Z-DEMO-65f4649b88"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify_rows(directory: Path, rows: list[dict]) -> None:
    for row in rows:
        path = directory / row["name"]
        raw = path.read_bytes()
        assert len(raw) == row["byte_length"]
        assert digest_bytes(raw) == row["sha256"]


def _verify_sources(rows: list[dict]) -> None:
    for row in rows:
        path = ROOT / row["relative_path"]
        raw = path.read_bytes()
        assert len(raw) == row["byte_length"]
        assert digest_bytes(raw) == row["sha256"]


def _verify_standard_bundle(directory: Path) -> dict:
    manifest = _json(directory / "manifest.json")
    expected = digest_json({key: value for key, value in manifest.items() if key != "bundle_root"})
    assert manifest["bundle_root"] == expected
    _verify_rows(directory, manifest["files"])
    _verify_sources(manifest.get("sources", []))
    return manifest


def test_final_freeze_seed_reveal_and_candidate_seal_are_live() -> None:
    freeze = verify_freeze_manifest_bytes(FREEZE.read_bytes())
    reveal = _json(SEED_REVEAL)
    verify_seed_reveal(reveal, freeze)
    seal = verify_candidate_seal(SEAL, repo_root=ROOT)
    assert seal["status"] == "SEALED_FOR_POST_SELECTION_REDTEAM"
    assert seal["selection_disposition"]["ucm_eligible"] is False
    assert seal["selection_disposition"]["no_winner_claimed"] is True


def test_three_complete_candidates_and_true_state_upper_bound_reverify() -> None:
    for run_id in (*FULL_RUNS, UPPER_BOUND):
        summary = verify_run_bundle(ROOT / "results/unified_map/runs" / run_id)
        assert summary["config"]["complete_benchmark"] is True
        assert summary["config"]["world_slots"] == [f"W{index:02d}" for index in range(1, 21)]
        assert summary["config"]["replicate_ids"] == ["R01", "R02", "R03", "R04", "R05"]
    upper = verify_run_bundle(ROOT / "results/unified_map/runs" / UPPER_BOUND)
    assert upper["candidate_eligibility"] == "upper_bound_only"
    assert upper["cross_seed_summary"]["diagnosis_top1_accuracy"]["mean"] == 1.0


def test_post_selection_redteam_bundle_preserves_failures() -> None:
    _verify_standard_bundle(REDTEAM)
    report = _json(REDTEAM / "redteam.json")
    assert report["post_selection_candidate_mutation"] is False
    assert report["fresh_collision_probes"]["W04"]["dangerous_collision_count"] == 0
    assert report["fresh_ood"]["unsafe_forced_known_count"] == 9
    assert report["held_out_nonlinear_combination"]["diagnosis_top1_accuracy"] == 0.0
    assert report["new_state_only_task"]["state_only_probe_rmse"] > report["new_state_only_task"]["constant_baseline_rmse"]
    assert report["extension_new_check_and_treatment"]["W16"]["migration_cost"]["local_in_place_refinement"] is False
    assert report["extension_new_check_and_treatment"]["W17"]["migration_cost"]["local_in_place_refinement"] is False


def test_independent_implementation_exactly_reproduces_core() -> None:
    _verify_standard_bundle(REPRODUCTION)
    report = _json(REPRODUCTION / "reproduction.json")
    assert report["implementation_independence"]["imports_candidate_families"] is False
    assert report["exact_core_reproduction"] is True
    assert report["update_identity_failures"] == 0
    assert set(report["differences"].values()) == {0.0}


def test_demo_fans_out_one_state_then_updates_one_state() -> None:
    manifest = _json(DEMO / "manifest.json")
    assert manifest["bundle_root"] == digest_json(
        {"files": manifest["files"], "sources": manifest["sources"]}
    )
    _verify_rows(DEMO, manifest["files"])
    _verify_sources(manifest["sources"])
    report = _json(DEMO / "demo.json")
    loop = report["closed_loop"]
    assert loop["before"]["all_heads_same_state"] is True
    assert loop["after"]["all_heads_same_state"] is True
    assert loop["shared_state_invariants"]["passed"] is True
    assert loop["update"]["state_changed"] is True
    assert loop["update"]["input_state_hash"] != loop["update"]["output_state_hash"]
    assert report["ood_or_insufficient_information"]["map_admitted_unknown"] is True
    assert report["ood_or_insufficient_information"]["boundary"]["post_freeze_redteam_unsafe_forced_known_ood"] == 9


def test_run_verifier_accepts_manifest_bound_gzip_transport(tmp_path: Path) -> None:
    summary = {"run_id": "gzip-transport-test"}
    summary_raw = canonical_json_bytes(summary)
    raw_rows = b'{"row":1}\n{"row":2}\n'
    files = [
        {
            "name": "raw-episodes.jsonl",
            "byte_length": len(raw_rows),
            "sha256": digest_bytes(raw_rows),
        },
        {
            "name": "summary.json",
            "byte_length": len(summary_raw),
            "sha256": digest_bytes(summary_raw),
        },
    ]
    manifest = {
        "protocol": "ucm-benchmark-v1-run-manifest/1",
        "run_id": "gzip-transport-test",
        "files": files,
    }
    manifest["bundle_root"] = digest_json(manifest)
    (tmp_path / "summary.json").write_bytes(summary_raw)
    (tmp_path / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    with gzip.GzipFile(
        filename=str(tmp_path / "raw-episodes.jsonl.gz"),
        mode="wb",
        mtime=0,
    ) as handle:
        handle.write(raw_rows)
    assert verify_run_bundle(tmp_path) == summary
