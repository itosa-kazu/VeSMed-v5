"""Integrity and claim-boundary checks for audited bridge holdout runs."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results" / "bridge-holdout"
CORPUS = ROOT / "tests" / "bridge_holdout" / "hidden_corpus.json"
FREEZE = RESULTS / "freeze-manifest.json"
A_RUNNER = ROOT / "tests" / "bridge_holdout" / "runner_a_external.py"
B_RUNNER = ROOT / "tests" / "bridge_holdout" / "runner_b_external.py"
A_REPORT = RESULTS / "implementation-a-audited-run-01.json"
B_REPORT_02 = RESULTS / "implementation-b-corrected-run-02.json"
B_REPORT_03 = RESULTS / "implementation-b-corrected-run-03.json"
REDTEAM_RUNNER = ROOT / "tests" / "bridge_holdout" / "redteam_external_probes.py"
REDTEAM_REPORT = RESULTS / "redteam-external-probes.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sidecar_digest(path: Path) -> str:
    return path.with_suffix(path.suffix + ".sha256").read_text(encoding="utf-8").split()[0]


def test_a_audited_report_integrity_and_conservative_classification() -> None:
    report = _load(A_REPORT)
    metadata = report["run_metadata"]
    summary = report["summary"]

    assert _sidecar_digest(A_REPORT) == _sha256(A_REPORT)
    assert metadata["runner_sha256"] == _sha256(A_RUNNER)
    assert metadata["candidate_source_sha256"] == _sha256(
        ROOT / "prototype" / "bridge_holdout" / "impl_a.py"
    )
    assert metadata["corpus_sha256"] == _sha256(CORPUS)
    assert metadata["freeze_manifest_sha256"] == _sha256(FREEZE)
    assert summary["mechanical_case_counts"] == {
        "PASS": 0,
        "CANDIDATE_FAIL": 0,
        "ADAPTER_UNREPRESENTABLE": 4,
        "HARNESS_INCOMPLETE": 37,
        "HARNESS_ERROR": 0,
    }
    assert summary["holdout_complete"] is False

    cases = {row["case_id"]: row for row in report["cases"]}
    assert len(cases) == 41
    assert {
        case_id: cases[case_id]["classification"]
        for case_id in ("H01", "H02", "H08", "H16")
    } == {
        "H01": "ADAPTER_UNREPRESENTABLE",
        "H02": "ADAPTER_UNREPRESENTABLE",
        "H08": "ADAPTER_UNREPRESENTABLE",
        "H16": "ADAPTER_UNREPRESENTABLE",
    }
    probes = {row["probe_id"]: row for row in report["post_seal_external_probes"]}
    assert probes["PA-DBN-NUMERICS"]["classification"] == "CANDIDATE_PASS"
    assert probes["PA-UNCERTAINTY-CHANNELS"]["classification"] == "CANDIDATE_FAIL"
    assert probes["PA-M01-DESTRUCTIVE-ROUNDTRIP"]["classification"] == "PARTIAL"
    assert report["mutation_kills"]["M01"]["classification"] == "NOT_KILLED"


def test_a_runner_exact_byte_replay(tmp_path: Path) -> None:
    output = tmp_path / "implementation-a.json"
    subprocess.run(
        [sys.executable, str(A_RUNNER), "--output", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert output.read_bytes() == A_REPORT.read_bytes()
    assert _sidecar_digest(output) == _sha256(output)


def test_b_corrected_run_lineage_and_claim_boundary() -> None:
    run_03 = _load(B_REPORT_03)
    assert _sidecar_digest(B_REPORT_02) == _sha256(B_REPORT_02)
    assert _sidecar_digest(B_REPORT_03) == _sha256(B_REPORT_03)
    assert run_03["run_metadata"]["parent_run_02_sha256"] == _sha256(B_REPORT_02)
    assert run_03["hashes"]["runner_b_sha256"] == _sha256(B_RUNNER)
    assert run_03["hashes"]["corpus_sha256"] == _sha256(CORPUS)
    assert run_03["hashes"]["freeze_manifest_sha256"] == _sha256(FREEZE)
    assert run_03["summary"]["mechanical_case_counts"] == {
        "PASS": 0,
        "CANDIDATE_FAIL": 0,
        "ADAPTER_UNREPRESENTABLE": 0,
        "HARNESS_INCOMPLETE": 41,
        "HARNESS_ERROR": 0,
    }
    assert run_03["summary"]["candidate_hard_failure"] is True
    assert run_03["summary"]["holdout_complete"] is False
    assert run_03["mutation_kills"]["M01"]["classification"] == "NOT_KILLED"


def test_redteam_post_seal_report_exact_byte_replay(tmp_path: Path) -> None:
    output = tmp_path / "redteam.json"
    subprocess.run(
        [sys.executable, str(REDTEAM_RUNNER), "--output", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    assert output.read_bytes() == REDTEAM_REPORT.read_bytes()
