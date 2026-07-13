from __future__ import annotations

import json

import pytest

from prototype.contract import Track
from prototype.experiment import RUNNER_VERSION, run_experiment
from prototype.isolated_benchmark import ISOLATED_PROTOCOL


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_focused_isolated_bundle_is_atomic_complete_and_non_overwriting(tmp_path) -> None:
    """One workload exercises the real subprocess path without running the panel."""

    target = run_experiment(
        output_root=tmp_path,
        run_id="fixed-test-run",
        candidates=("tel",),
        tracks=(Track.NATIVE,),
        workload_ids=("T01",),
    )
    metadata = _read(target / "metadata.json")
    bundle = _read(target / "tel-native.json")
    summary = _read(target / "summary.json")

    assert metadata["run_id"] == "fixed-test-run"
    assert metadata["runner_version"] == RUNNER_VERSION
    assert metadata["execution"]["mode"] == "isolated"
    assert metadata["execution"]["isolation_protocol"] == ISOLATED_PROTOCOL
    assert metadata["execution"]["candidate_stdin"] == "candidate_view only"
    assert metadata["selection"]["workload_ids"] == ["T01"]
    assert metadata["selection"]["workload_count"] == 1
    assert metadata["hashes"]["candidate_code"]["tel"].startswith("sha256:")
    assert metadata["hashes"]["model_subkernel_code"].startswith("sha256:")
    assert metadata["hashes"]["benchmark_code"].startswith("sha256:")
    assert metadata["hashes"]["selected_candidate_views"].startswith("sha256:")
    assert metadata["hashes"]["selected_oracle_views"].startswith("sha256:")
    assert bundle["execution_mode"] == "isolated"
    assert bundle["isolation_protocol"] == ISOLATED_PROTOCOL
    assert bundle["workload_ids"] == ["T01"]
    assert bundle["summary"]["workload_count"] == 1
    assert set(bundle["runs"]) == {"T01"}
    assert "tel-native" in summary["panels"]
    assert not list(tmp_path.glob(".fixed-test-run.tmp-*"))
    assert not (tmp_path / ".fixed-test-run.lock").exists()

    with pytest.raises(FileExistsError):
        run_experiment(
            output_root=tmp_path,
            run_id="fixed-test-run",
            candidates=("tel",),
            tracks=(Track.NATIVE,),
            workload_ids=("T01",),
        )


def test_candidate_track_selection_skips_undefined_companion_panels(tmp_path) -> None:
    target = run_experiment(
        output_root=tmp_path,
        run_id="track-matrix",
        candidates=("tel", "kernel", "model"),
        tracks=(Track.COMPANION,),
        workload_ids=("T01",),
        execution_mode="in_process_diagnostic",
    )
    metadata = _read(target / "metadata.json")
    summary = _read(target / "summary.json")

    assert metadata["execution"]["evidentiary_status"] == (
        "diagnostic_only_not_isolated_evidence"
    )
    assert metadata["selection"]["panel_matrix"] == [
        {"candidate": "tel", "track": "companion"}
    ]
    assert {
        (item["candidate"], item["track"])
        for item in metadata["selection"]["skipped_non_applicable"]
    } == {("kernel", "companion"), ("model", "companion")}
    assert set(summary["panels"]) == {"tel-companion"}
    assert (target / "tel-companion.json").is_file()
    assert not (target / "kernel-companion.json").exists()
    assert not (target / "model-companion.json").exists()


def test_selection_rejects_empty_applicable_matrix(tmp_path) -> None:
    with pytest.raises(ValueError, match="no applicable panel"):
        run_experiment(
            output_root=tmp_path,
            run_id="none",
            candidates=("kernel", "model"),
            tracks=(Track.COMPANION,),
            workload_ids=("T01",),
        )

