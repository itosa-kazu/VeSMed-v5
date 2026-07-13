from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from prototype.metrics import collect_metrics, compare_reports, write_report


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def report() -> dict:
    return collect_metrics(ROOT)


def test_metrics_cover_all_executable_candidates_and_have_explicit_primitives(report: dict) -> None:
    assert set(report["candidates"]) == {
        "temporal_ledger",
        "causal_state",
        "rewrite_open",
        "clinical_kernel",
        "model_subkernel",
    }
    for candidate in report["candidates"].values():
        totals = candidate["totals"]
        manifest = candidate["manifest"]
        assert totals["loc"]["nonblank_non_comment_lines"] > 0
        assert totals["definitions"]["class_count"] > 0
        assert totals["definitions"]["function_count_including_methods_and_nested"] > 0
        assert manifest["primitive_group_count"] > 0
        assert manifest["unique_primitive_count"] == len(manifest["unique_primitives"])
        assert manifest["declared_query_capability_count"] > 0


def test_candidate_sources_have_no_test_id_or_oracle_dispatch(report: dict) -> None:
    for name, candidate in report["candidates"].items():
        scan = candidate["totals"]["anti_dispatch_scan"]
        assert scan["literal_test_id_count"] == 0, name
        assert scan["test_or_oracle_dispatch_site_count"] == 0, name
        assert scan["forbidden_harness_or_reference_import_count"] == 0, name


def test_snapshot_digest_is_stable_for_same_files() -> None:
    first = collect_metrics(ROOT)
    second = collect_metrics(ROOT)
    assert first["generated_at_utc"] != second["generated_at_utc"] or first is not second
    assert first["report_sha256"] == second["report_sha256"]


def test_blast_radius_comparison_detects_a_core_fingerprint_change(report: dict) -> None:
    changed = deepcopy(report)
    core = changed["extension_blast_radius_input"]["fixed_core_groups"]
    first_group = next(iter(core.values()))
    first_group[0]["sha256"] = "0" * 64
    comparison = compare_reports(report, changed)
    assert comparison["extension_blast_radius_core_files"] == 1
    assert comparison["fixed_core"]["modified"] == [first_group[0]["path"]]


def test_write_report_refuses_to_overwrite_by_default(tmp_path: Path, report: dict) -> None:
    target = tmp_path / "metrics.json"
    assert write_report(target, report) == target
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        write_report(target, report)
    assert write_report(target, report, force=True) == target
