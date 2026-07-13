"""Integrity and claim-boundary checks for audited bridge holdout runs."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


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
FINAL_REPORT = RESULTS / "final-report.json"
FIXTURE_MANIFEST = RESULTS / "fixture-manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _sidecar_digest(path: Path) -> str:
    return path.with_suffix(path.suffix + ".sha256").read_text(encoding="utf-8").split()[0]


def _git_blobs(commit: str, paths: list[str]) -> dict[str, bytes]:
    """Read exact Git blob bytes for many paths through one batch process."""

    request = "".join(f"{commit}:{path}\n" for path in paths).encode("utf-8")
    completed = subprocess.run(
        ["git", "cat-file", "--batch"],
        cwd=ROOT,
        input=request,
        check=True,
        capture_output=True,
    )
    output = completed.stdout
    offset = 0
    blobs: dict[str, bytes] = {}
    for path in paths:
        header_end = output.index(b"\n", offset)
        header = output[offset:header_end].decode("ascii").split()
        assert len(header) == 3 and header[1] == "blob", (path, header)
        size = int(header[2])
        start = header_end + 1
        end = start + size
        blobs[path] = output[start:end]
        assert output[end : end + 1] == b"\n"
        offset = end + 1
    assert offset == len(output)
    return blobs


def _classification_counts(rows: list[dict[str, Any]], labels: tuple[str, ...]) -> dict[str, int]:
    observed = Counter(row["classification"] for row in rows)
    return {label: observed.get(label, 0) for label in labels}


def _normalize_b_replay(value: Any) -> Any:
    """Drop only runtime timing fields that B intentionally records per replay."""

    if isinstance(value, dict):
        return {
            key: _normalize_b_replay(item)
            for key, item in value.items()
            if key != "latency_ns"
            and key != "report_bytes_before_trace_metrics"
            and not key.endswith("_ns")
        }
    if isinstance(value, list):
        return [_normalize_b_replay(item) for item in value]
    return value


def _corpus_executability(corpus: dict[str, Any]) -> dict[str, Any]:
    queries = corpus["base"]["authority_projection"]["queries"]
    available = set(queries)
    dangling = {
        case["case_id"]: sorted(set(case.get("queries", ())) - available)
        for case in corpus["cases"]
        if set(case.get("queries", ())) - available
    }
    concrete = [
        case["case_id"]
        for case in corpus["cases"]
        if case.get("fixture") and case["case_id"] not in dangling
    ]
    descriptor_only = [
        case["case_id"]
        for case in corpus["cases"]
        if "mutation" in case
        and not any(
            key in case
            for key in ("fixture_object", "fixture_patch", "control_fixture", "mutant_fixture")
        )
    ]
    return {"dangling": dangling, "concrete": concrete, "descriptor_only": descriptor_only}


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


def test_b_runner_normalized_semantic_replay(tmp_path: Path) -> None:
    output = tmp_path / "implementation-b.json"
    completed = subprocess.run(
        [sys.executable, str(B_RUNNER), "--output", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    replay = _load(output)
    frozen = _load(B_REPORT_03)
    receipt = json.loads(completed.stdout)
    assert receipt["sha256"] == _sha256(output)
    assert _normalize_b_replay(replay) == _normalize_b_replay(frozen)


def test_redteam_post_seal_report_exact_byte_replay(tmp_path: Path) -> None:
    output = tmp_path / "redteam.json"
    subprocess.run(
        [sys.executable, str(REDTEAM_RUNNER), "--output", str(output)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    assert output.read_bytes() == REDTEAM_REPORT.read_bytes()


def test_final_report_integrity_and_non_compensating_outcome() -> None:
    report = _load(FINAL_REPORT)
    assert _sidecar_digest(FINAL_REPORT) == _sha256(FINAL_REPORT)
    assert report["status"] == {
        "experimental_round": "SEALED_AND_REPORTED",
        "frozen_implementation_hypothesis": "HYPOTHESIS_FAIL",
        "sealed_41_case_corpus": "HARNESS_INCOMPLETE",
        "architecture_selection": "CHECKPOINT_3_AND_7_REOPENED",
        "holdout_complete": False,
        "no_compensating_total_score": True,
    }
    assert report["claim_boundary"]["evidence_partition"] == {
        "sealed_corpus_supports": "HARNESS_INCOMPLETE_ONLY_NO_CANDIDATE_FAIL_VERDICTS",
        "implementation_hypothesis_fail_support": (
            "DETERMINISTIC_POSTSEAL_EXTERNAL_HARD_COUNTEREXAMPLES"
        ),
        "external_probes_promoted_to_hidden_cases": False,
    }
    a_report = _load(A_REPORT)
    b_report = _load(B_REPORT_03)
    redteam = _load(REDTEAM_REPORT)
    corpus = _load(CORPUS)
    fixture_manifest = _load(FIXTURE_MANIFEST)
    labels = ("PASS", "CANDIDATE_FAIL", "ADAPTER_UNREPRESENTABLE", "HARNESS_INCOMPLETE", "HARNESS_ERROR")
    assert report["mechanical_hidden_cases"]["implementation_a"] == _classification_counts(
        a_report["cases"], labels
    )
    assert report["mechanical_hidden_cases"]["implementation_b"] == _classification_counts(
        b_report["cases"], labels
    )
    assert report["external_evidence"]["runner_a"]["counts"] == a_report["summary"][
        "external_probe_counts"
    ]
    assert report["external_evidence"]["runner_b"]["counts"] == b_report["summary"][
        "external_probe_counts"
    ]
    assert report["external_evidence"]["deterministic_redteam"]["counts"] == redteam[
        "verdict_counts_non_compensating"
    ]
    assert report["external_evidence"]["deterministic_redteam"]["file_sha256"] == _sha256(
        REDTEAM_REPORT
    )
    assert report["external_evidence"]["deterministic_redteam"][
        "embedded_payload_sha256"
    ] == redteam["report_sha256"]
    redteam_payload = dict(redteam)
    embedded_digest = redteam_payload.pop("report_sha256")
    canonical_payload = json.dumps(
        redteam_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    assert hashlib.sha256(canonical_payload).hexdigest() == embedded_digest

    corpus_audit = _corpus_executability(corpus)
    mechanical = report["mechanical_hidden_cases"]
    assert mechanical["case_partition"] == {
        "preregistered": fixture_manifest["corpus"]["preregistered_cases"],
        "postseal_preexecution_static_audit_addendum": fixture_manifest["corpus"][
            "postseal_static_audit_addendum"
        ],
    }
    assert mechanical["directly_specified_base_case_ids"] == corpus_audit["concrete"]
    assert mechanical["descriptor_only_case_count"] == len(corpus_audit["descriptor_only"])
    assert mechanical["dangling_query_refs"] == corpus_audit["dangling"]
    assert mechanical["dangling_descriptor_overlap_case_ids"] == sorted(
        set(corpus_audit["dangling"]) & set(corpus_audit["descriptor_only"])
    )

    b_probes = {row["probe_id"]: row for row in b_report["post_seal_external_probes"]}
    scm_errors = {
        row["name"].removeprefix("numeric:"): row["evidence"]["absolute_error"]
        for row in b_probes["PB-SCM-OPS"]["assertions"]
        if row["name"].startswith("numeric:")
    }
    uncertainty_errors = {
        row["name"].removeprefix("numeric:"): row["evidence"]["absolute_error"]
        for row in b_probes["PB-UNCERTAINTY-ISOLATION"]["assertions"]
        if row["name"].startswith("numeric:")
    }
    numeric = report["required_report_vector"]["finite_numeric_errors"]
    for name, error in scm_errors.items():
        assert numeric[f"b_external_scm_{name}"] == error
    for name, error in uncertainty_errors.items():
        assert numeric[f"b_external_uncertainty_{name}"] == error

    mutation_matrix = report["required_report_vector"]["formal_candidate_runner_mutation_kills"]
    assert mutation_matrix["M01"] == {"A": "NOT_KILLED", "B": "NOT_KILLED"}
    for number in range(2, 13):
        mutation_id = f"M{number:02d}"
        assert a_report["mutation_kills"][mutation_id]["classification"] == (
            "NOT_EXECUTED_BY_RUNNER_A"
        )
        assert b_report["mutation_kills"][mutation_id]["classification"] == (
            "NOT_EXECUTED_BY_RUNNER_B"
        )
        assert mutation_matrix[mutation_id] == {
            "A": "NOT_EXECUTED_BY_CANDIDATE_RUNNER",
            "B": "NOT_EXECUTED_BY_CANDIDATE_RUNNER",
        }

    artifacts = report["integrity"]["artifacts"]
    assert "reveal_seed" in artifacts
    for metadata in artifacts.values():
        path = ROOT / metadata["path"]
        assert path.stat().st_size == metadata["bytes"]
        assert _sha256(path) == metadata["sha256"]
    packaging_checkpoint = report["integrity"]["artifact_packaging_checkpoint"]
    artifact_paths = [metadata["path"] for metadata in artifacts.values()]
    packaged_blobs = _git_blobs(packaging_checkpoint, artifact_paths)
    for metadata in artifacts.values():
        blob = packaged_blobs[metadata["path"]]
        assert len(blob) == metadata["bytes"]
        assert hashlib.sha256(blob).hexdigest() == metadata["sha256"]
    for manifest_path, collection in ((FREEZE, "implementations"), (FIXTURE_MANIFEST, "artifacts")):
        manifest = _load(manifest_path)
        for metadata in manifest[collection].values():
            path = ROOT / metadata["path"]
            assert path.stat().st_size == metadata["bytes"]
            assert _sha256(path) == metadata["sha256"]
    assert report["integrity"]["b_run_history"]["complete_append_only_history_claimed"] is False
    assert report["integrity"]["logical_experiment_checkpoint"] == (
        "abac08786f642c28ba76d8940c60fe1906ab9945"
    )
    assert report["integrity"]["artifact_packaging_checkpoint"] == (
        "d08a8e5b12377890499703b6de6bed1f90c4aa98"
    )
    assert report["required_report_vector"]["adapter_commitments"]["A"][
        "adapter_noncomment_loc"
    ]["value"] is None
    assert report["required_report_vector"]["adapter_commitments"]["B"][
        "adapter_noncomment_loc"
    ]["value"] is None
    assert report["required_report_vector"]["latency"]["A_ns"]["compile_p50"] is None
    assert report["required_report_vector"]["incremental_vs_clean"]["A_numeric_mismatch_count"] is None
    assert report["required_report_vector"]["measurement_completeness"]["complete"] is False
    assert report["required_report_vector"]["extension_blast_radius"][
        "core_runtime_branches_changed"
    ] == 0
    assert report["verification"]["bridge_focused"]["result"].startswith("16 passed")
    assert report["verification"]["full_suite"]["result"].startswith(
        "135 passed, 7 subtests passed"
    )
    assert "does not promote" in report["verification"]["interpretation"]
