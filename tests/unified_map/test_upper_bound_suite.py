from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from prototype.unified_map import upper_bound_suite as suite_module
from prototype.unified_map.upper_bound_suite import (
    BENCHMARK_PANEL_KEYS,
    BENCHMARK_WORLD_SLOTS,
    PROTOCOL,
    WORLD_SLOTS,
    compute_upper_bound_suite_root,
    run_upper_bound_suite,
    verify_upper_bound_suite,
)


@pytest.fixture(scope="module")
def collected_suite() -> tuple[dict, dict[str, dict]]:
    members, reports = suite_module._collect_members()
    report = suite_module._assemble_suite(members)
    verify_upper_bound_suite(report, replay_runtime=False)
    return report, reports


def _resign_suite(report: dict) -> None:
    report["member_set_root"] = digest_json(
        {"protocol": PROTOCOL, "members": report["members"]}
    )
    report["suite_root"] = compute_upper_bound_suite_root(report)


def test_full_suite_covers_twenty_worlds_and_twenty_one_panels_without_credit(
    collected_suite: tuple[dict, dict[str, dict]],
) -> None:
    report, _ = collected_suite
    verify_upper_bound_suite(report, replay_runtime=False)

    assert (
        WORLD_SLOTS
        == BENCHMARK_WORLD_SLOTS
        == tuple(f"W{index:02d}" for index in range(1, 21))
    )
    assert len(BENCHMARK_PANEL_KEYS) == 21
    assert len(report["members"]) == 20
    assert tuple(report["covered_world_slots"]) == WORLD_SLOTS
    assert [
        (row["world_slot"], row["panel_id"]) for row in report["covered_panel_keys"]
    ] == list(BENCHMARK_PANEL_KEYS)
    assert report["missing_benchmark_world_slots"] == []
    assert report["missing_benchmark_panel_keys"] == []

    members = {member["world_slot"]: member for member in report["members"]}
    assert members["W15"]["panel_ids"] == [
        "W15A-randomized-identifiable",
        "W15B-observational-nonidentified",
    ]
    assert members["W15"]["panel_count"] == 2
    assert all(
        member["panel_ids"] == ["primary"] and member["panel_count"] == 1
        for slot, member in members.items()
        if slot != "W15"
    )

    scope = report["scope_statement"]
    summary = report["verification_summary"]
    assert scope["benchmark_status"] == "PRE-FREEZE"
    assert scope["complete_world_slot_coverage"] is True
    assert scope["complete_panel_coverage"] is True
    assert scope["formal_benchmark_coverage_claimed"] is False
    assert scope["upper_bound_only"] is True
    assert scope["ucm_eligible"] is False
    assert scope["candidate_performance_claimed"] is False
    assert scope["formal_freeze_authority"] is False
    assert scope["fresh_process_live_replay_required"] is True
    assert scope["adapter_source_digest_imported_code_attestation_claimed"] is False
    assert scope["member_runtime_attestation_delegated_to_member_verifiers"] is True
    assert scope["ledger_credit"] == 0
    assert summary["member_count"] == 20
    assert summary["world_count"] == 20
    assert summary["panel_count"] == 21
    assert summary["total_cell_count"] == 94
    assert summary["total_state_binding_count"] == 43
    assert summary["total_cell_count"] == sum(
        member["cell_count"] for member in report["members"]
    )
    assert summary["total_state_binding_count"] == sum(
        member["state_binding_count"] for member in report["members"]
    )
    assert summary["all_members_run_then_live_verified"] is True
    assert summary["all_member_reports_exact_canonical_bytes_bound"] is True
    assert summary["fresh_process_live_replay_required"] is True
    assert summary["adapter_source_digest_imported_code_attestation_claimed"] is False
    assert summary["member_runtime_attestation_delegated_to_member_verifiers"] is True
    assert summary["formal_benchmark_coverage_claimed"] is False
    assert summary["upper_bound_only"] is True
    assert summary["ucm_eligible"] is False
    assert summary["candidate_performance_claimed"] is False
    assert summary["formal_freeze_authority"] is False
    assert summary["ledger_credit"] == 0
    assert report["suite_root"] == compute_upper_bound_suite_root(report)


def test_each_member_binds_its_exact_canonical_report_bytes(
    collected_suite: tuple[dict, dict[str, dict]],
) -> None:
    report, member_reports = collected_suite
    for member in report["members"]:
        raw = canonical_json_bytes(member_reports[member["world_slot"]])
        assert member["member_report_bytes"] == len(raw)
        assert member["member_report_digest"] == digest_bytes(raw)
        assert (
            member["member_bundle_root"]
            == member_reports[member["world_slot"]]["bundle_root"]
        )


def test_materialized_member_tree_is_exact_and_closed(
    collected_suite: tuple[dict, dict[str, dict]],
    tmp_path: Path,
) -> None:
    report, member_reports = collected_suite
    member_directory = tmp_path / "members"
    member_directory.mkdir()
    for slot, member_report in member_reports.items():
        (member_directory / f"{slot}.json").write_bytes(
            canonical_json_bytes(member_report)
        )
    verify_upper_bound_suite(
        report,
        replay_runtime=False,
        member_directory=member_directory,
    )

    w01_path = member_directory / "W01.json"
    w01_raw = w01_path.read_bytes()
    w01_path.write_bytes(w01_raw + b"\n")
    with pytest.raises(ProtocolViolation, match="byte-identical"):
        verify_upper_bound_suite(
            report,
            replay_runtime=False,
            member_directory=member_directory,
        )
    w01_path.write_bytes(w01_raw)

    (member_directory / "unexpected.json").write_bytes(b"{}")
    with pytest.raises(ProtocolViolation, match="exact tree"):
        verify_upper_bound_suite(
            report,
            replay_runtime=False,
            member_directory=member_directory,
        )


def test_public_run_assembles_the_same_verified_member_set(
    collected_suite: tuple[dict, dict[str, dict]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report, member_reports = collected_suite
    members = deepcopy(report["members"])
    monkeypatch.setattr(
        suite_module,
        "_collect_members",
        lambda: (deepcopy(members), deepcopy(member_reports)),
    )
    assert run_upper_bound_suite() == report


def test_suite_verifier_live_reverifies_all_twenty_adapters(
    collected_suite: tuple[dict, dict[str, dict]],
) -> None:
    report, _ = collected_suite
    verify_upper_bound_suite(report, replay_runtime=True)


def test_resigned_member_tamper_fails_exact_live_member_comparison(
    collected_suite: tuple[dict, dict[str, dict]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report, member_reports = collected_suite
    expected_members = deepcopy(report["members"])
    tampered = deepcopy(report)
    tampered["members"][0]["member_report_digest"] = "sha256:" + "0" * 64
    _resign_suite(tampered)
    monkeypatch.setattr(
        suite_module,
        "_collect_members",
        lambda: (deepcopy(expected_members), deepcopy(member_reports)),
    )

    with pytest.raises(ProtocolViolation, match="live adapter replay"):
        verify_upper_bound_suite(tampered, replay_runtime=True)


def test_w15_panel_cannot_be_collapsed_after_all_roots_are_recomputed(
    collected_suite: tuple[dict, dict[str, dict]],
) -> None:
    report, _ = collected_suite
    tampered = deepcopy(report)
    w15 = next(
        member for member in tampered["members"] if member["world_slot"] == "W15"
    )
    w15["panel_ids"] = ["W15A-randomized-identifiable"]
    w15["panel_count"] = 1
    _resign_suite(tampered)

    with pytest.raises(ProtocolViolation):
        verify_upper_bound_suite(tampered, replay_runtime=False)
