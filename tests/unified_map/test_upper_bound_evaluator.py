from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from prototype.unified_map.state import (
    StateClass,
    StatePayload,
    compute_state_hash,
)
from prototype.unified_map.upper_bound_evaluator import (
    STATUS_CHAIN,
    compute_upper_bound_bundle_root,
    run_w01_upper_bound_sanity,
    verify_w01_upper_bound_sanity,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ARTIFACT = (
    REPO_ROOT
    / "results"
    / "unified_map"
    / "pre_freeze"
    / "20260717-w01-true-state-probe"
    / "vertical-slice.json"
)
EXPECTED_CELL_IDS = [
    "W01.initial.diagnosis",
    "W01.initial.natural_forecast",
    "W01.initial.intervention",
    "W01.update",
    "W01.updated.diagnosis",
    "W01.updated.natural_forecast",
]


@pytest.fixture(scope="module")
def w01_bundle() -> dict:
    return run_w01_upper_bound_sanity(source_artifact=SOURCE_ARTIFACT)


def _cells_by_id(bundle: dict) -> dict[str, dict]:
    return {cell["cell_id"]: cell for cell in bundle["cells"]}


def _cell_set_root(cells: list[dict]) -> str:
    identities = [
        {
            "cell_id": cell["cell_id"],
            "cut_alias": cell["cut_alias"],
            "task": cell["task"],
            "cell_digest": digest_json(cell),
        }
        for cell in cells
    ]
    identities.sort(key=lambda item: item["cell_id"].encode("utf-8"))
    return digest_json(
        {
            "protocol": "ucm-upper-bound-cell-set-root/1",
            "identities": identities,
        }
    )


def _resign(bundle: dict, *, cells_changed: bool = False) -> dict:
    if cells_changed:
        bundle["cell_set_root"] = _cell_set_root(bundle["cells"])
    bundle["bundle_root"] = compute_upper_bound_bundle_root(bundle)
    return bundle


def _stable_state_hash(binding: dict) -> str:
    payload_wire = binding["payload"]
    record = binding["record"]
    payload = StatePayload.from_json(
        payload_wire["representation"],
        schema_version=payload_wire["schema_version"],
        state_class=StateClass(payload_wire["state_class"]),
    )
    return compute_state_hash(
        payload,
        candidate_bundle_digest=record["candidate_bundle_digest"],
        model_digest=record["model_digest"],
        scope_digest=record["scope_digest"],
        catalog_digest=record["catalog_digest"],
        as_of_available_at=record["as_of_available_at"],
    )


def test_w01_bundle_is_deterministic_has_six_cells_and_metric_direction() -> None:
    first = run_w01_upper_bound_sanity(source_artifact=SOURCE_ARTIFACT)
    second = run_w01_upper_bound_sanity(source_artifact=SOURCE_ARTIFACT)

    assert first == second
    verify_w01_upper_bound_sanity(first)
    assert first["status_chain"] == STATUS_CHAIN
    assert first["bundle_root"] == compute_upper_bound_bundle_root(first)
    assert [cell["cell_id"] for cell in first["cells"]] == EXPECTED_CELL_IDS
    assert first["verification_summary"]["cell_count"] == 6
    assert first["verification_summary"]["ledger_credit"] == 0

    cells = _cells_by_id(first)
    for cell_id in (
        "W01.initial.diagnosis",
        "W01.updated.diagnosis",
    ):
        metric = cells[cell_id]["metric"]
        degraded = cells[cell_id]["degraded_control_metric"]
        assert metric["accuracy"] == 1.0
        assert metric["log_loss"] == 0.0
        assert metric["multiclass_brier"] == 0.0
        assert degraded["accuracy"] == 0.0
        assert degraded["log_loss"] > metric["log_loss"]
        assert degraded["multiclass_brier"] > metric["multiclass_brier"]

    for cell_id in (
        "W01.initial.natural_forecast",
        "W01.updated.natural_forecast",
    ):
        metric = cells[cell_id]["metric"]
        degraded = cells[cell_id]["degraded_control_metric"]
        assert metric["normalized_rmse"] == 0.0
        assert metric["normalized_mae"] == 0.0
        assert degraded["normalized_rmse"] > metric["normalized_rmse"]
        assert degraded["normalized_mae"] > metric["normalized_mae"]

    intervention = cells["W01.initial.intervention"]
    assert intervention["metric"]["worst_regret"] == 0.0
    assert intervention["metric"]["catastrophic_count"] == 0
    assert intervention["degraded_control_metric"]["worst_regret"] > 0.0
    assert intervention["degraded_control_metric"]["catastrophic_count"] == 1
    assert all(
        metric["normalized_rmse"] == 0.0
        and metric["normalized_mae"] == 0.0
        for metric in intervention["trajectory_metrics"].values()
    )
    assert all(
        comparison["passed"] is True
        for comparison in intervention["oracle_comparisons"].values()
    )


def test_w01_source_artifact_is_exact_canonical_byte_replay(tmp_path: Path) -> None:
    source_bytes = SOURCE_ARTIFACT.read_bytes()
    copied = tmp_path / "vertical-slice.json"
    copied.write_bytes(source_bytes)

    bundle = run_w01_upper_bound_sanity(source_artifact=copied)
    anchor = bundle["source_anchor"]
    assert canonical_json_bytes(json.loads(source_bytes)) == source_bytes
    assert anchor["artifact_digest"] == digest_bytes(source_bytes)
    assert anchor["replay_digest"] == digest_bytes(source_bytes)
    assert anchor["artifact_bytes"] == len(source_bytes)
    assert anchor["byte_identical_replay"] is True

    tampered = json.loads(source_bytes)
    tampered["train_fixture"]["episode_index"] += 1
    copied.write_bytes(canonical_json_bytes(tampered))
    with pytest.raises(ProtocolViolation, match="does not byte-replay"):
        run_w01_upper_bound_sanity(source_artifact=copied)


def test_w01_state_head_query_and_update_lineage_is_exact(w01_bundle: dict) -> None:
    states = w01_bundle["states"]
    initial = states["initial"]["record"]
    updated = states["updated"]["record"]
    assert initial["state_hash"] == _stable_state_hash(states["initial"])
    assert updated["state_hash"] == _stable_state_hash(states["updated"])
    assert initial["state_id"] == "ucm-state:" + initial["state_hash"][7:23]
    assert updated["state_id"] == "ucm-state:" + updated["state_hash"][7:23]
    assert initial["state_hash"] != updated["state_hash"]
    assert initial["parent_state_hash"] is None
    assert updated["parent_state_hash"] == initial["state_hash"]

    cells = _cells_by_id(w01_bundle)
    intervention = cells["W01.initial.intervention"]
    initial_heads = [
        cells["W01.initial.diagnosis"]["candidate_head"],
        cells["W01.initial.natural_forecast"]["candidate_head"],
        *intervention["candidate_heads"].values(),
    ]
    updated_heads = [
        cells["W01.updated.diagnosis"]["candidate_head"],
        cells["W01.updated.natural_forecast"]["candidate_head"],
    ]
    assert {
        head["execution"]["consumed_state_hash"] for head in initial_heads
    } == {initial["state_hash"]}
    assert {
        head["execution"]["consumed_state_hash"] for head in updated_heads
    } == {updated["state_hash"]}
    for head in (*initial_heads, *updated_heads):
        execution = head["execution"]
        assert execution["query_digest"] == digest_json(head["query"])
        assert execution["manifest_digest"] == w01_bundle["manifest_digest"]
        assert execution["privileged"] is True
        assert execution["eligibility"] == "upper_bound_only"
        assert execution["operation"] == execution["response"]["operation"]

    assert cells["W01.initial.diagnosis"]["state_hash"] == initial["state_hash"]
    assert (
        cells["W01.initial.natural_forecast"]["state_hash"]
        == initial["state_hash"]
    )
    assert intervention["state_hash"] == initial["state_hash"]
    assert cells["W01.updated.diagnosis"]["state_hash"] == updated["state_hash"]
    assert (
        cells["W01.updated.natural_forecast"]["state_hash"]
        == updated["state_hash"]
    )

    update = cells["W01.update"]
    assert update["state_hash"] == updated["state_hash"]
    assert update["prior_state_hash"] == initial["state_hash"]
    assert update["parent_state_hash"] == initial["state_hash"]
    assert update["delta_digest"] == digest_json(update["delta"])
    assert update["delta_digest"] == updated["delta_digest"]


def test_candidate_point_trajectory_tamper_fails_after_roots_are_recomputed(
    w01_bundle: dict,
) -> None:
    tampered = deepcopy(w01_bundle)
    forecast = _cells_by_id(tampered)["W01.initial.natural_forecast"]
    forecast["candidate_head"]["execution"]["response"]["result"][
        "observable_predictions"
    ]["obs_0"]["values"][0] += 0.125
    _resign(tampered, cells_changed=True)

    with pytest.raises(ProtocolViolation, match="collector-derived|metric direction"):
        verify_w01_upper_bound_sanity(tampered)


def test_query_digest_tamper_fails_after_roots_are_recomputed(
    w01_bundle: dict,
) -> None:
    tampered = deepcopy(w01_bundle)
    diagnosis = _cells_by_id(tampered)["W01.initial.diagnosis"]
    diagnosis["candidate_head"]["execution"]["query_digest"] = digest_json(
        {"tampered": True}
    )
    _resign(tampered, cells_changed=True)

    with pytest.raises(ProtocolViolation, match="query digest mismatch"):
        verify_w01_upper_bound_sanity(tampered)


def test_status_chain_tamper_fails_after_bundle_root_is_recomputed(
    w01_bundle: dict,
) -> None:
    tampered = deepcopy(w01_bundle)
    tampered["status_chain"]["ledger_credit"] = 1
    _resign(tampered)

    with pytest.raises(ProtocolViolation, match="status or identity was rewritten"):
        verify_w01_upper_bound_sanity(tampered)


def test_reported_metric_tamper_fails_after_roots_are_recomputed(
    w01_bundle: dict,
) -> None:
    tampered = deepcopy(w01_bundle)
    diagnosis = _cells_by_id(tampered)["W01.initial.diagnosis"]
    diagnosis["metric"]["log_loss"] = 0.25
    _resign(tampered, cells_changed=True)

    with pytest.raises(ProtocolViolation, match="not collector-derived"):
        verify_w01_upper_bound_sanity(tampered)


def test_head_and_update_lineage_tamper_fails_after_roots_are_recomputed(
    w01_bundle: dict,
) -> None:
    head_tamper = deepcopy(w01_bundle)
    cells = _cells_by_id(head_tamper)
    cells["W01.initial.diagnosis"]["candidate_head"]["execution"][
        "consumed_state_hash"
    ] = head_tamper["states"]["updated"]["record"]["state_hash"]
    _resign(head_tamper, cells_changed=True)
    with pytest.raises(ProtocolViolation, match="head binding mismatch"):
        verify_w01_upper_bound_sanity(head_tamper)

    update_tamper = deepcopy(w01_bundle)
    updated_hash = update_tamper["states"]["updated"]["record"]["state_hash"]
    update_tamper["states"]["updated"]["record"][
        "parent_state_hash"
    ] = updated_hash
    _cells_by_id(update_tamper)["W01.update"]["parent_state_hash"] = updated_hash
    _resign(update_tamper, cells_changed=True)
    with pytest.raises(ProtocolViolation, match="state lineage is not closed"):
        verify_w01_upper_bound_sanity(update_tamper)


def test_cli_writes_canonical_bundle_once_and_refuses_overwrite(
    tmp_path: Path,
) -> None:
    output = tmp_path / "nested" / "w01-upper-bound-sanity.json"
    command = [
        sys.executable,
        "-m",
        "prototype.unified_map.upper_bound_evaluator",
        "--output",
        str(output),
        "--source-artifact",
        str(SOURCE_ARTIFACT),
    ]
    first = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert first.returncode == 0, first.stderr
    original = output.read_bytes()
    payload = json.loads(original)
    assert canonical_json_bytes(payload) == original
    verify_w01_upper_bound_sanity(payload)

    second = subprocess.run(
        command,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert second.returncode != 0
    assert "refusing to overwrite" in second.stderr
    assert output.read_bytes() == original
