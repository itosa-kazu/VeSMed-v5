from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes, digest_json
from prototype.unified_map.redteam_v2_adapter import candidate_source_bindings, training_records
from prototype.unified_map.redteam_v2_pack import (
    REQUIRED_ATTACK_CLASSES,
    build_secret_pack,
    prepare_custody,
    verify_reveal,
)
from prototype.unified_map.redteam_v2_runner import run_redteam_v2, verify_redteam_v2_run


DUMMY_SECRET = b"unit-test-only-redteam-secret-0001"


def _json(path: Path) -> dict:
    return json.loads(path.read_bytes())


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_bytes().splitlines()]


def test_pack_is_source_distinct_and_has_numeric_paired_controls() -> None:
    modules = (
        Path("prototype/unified_map/redteam_v2_pack.py"),
        Path("prototype/unified_map/redteam_v2_adapter.py"),
        Path("prototype/unified_map/redteam_v2_runner.py"),
    )
    forbidden = ("world_registry", "prototype.unified_map.worlds", ".worlds", "fixtures")
    for path in modules:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(("." * node.level) + (node.module or ""))
        assert not any(token in name for name in imports for token in forbidden), (path, imports)

    pack = build_secret_pack(DUMMY_SECRET, training_count=24, ordinary_test_count=12)
    assert tuple(pack["attack_classes"]) == REQUIRED_ATTACK_CLASSES
    assert set(pack["horizons"]) == {1, 24, 168}
    assert pack["source_distinct_declaration"]["does_not_import_frozen_worlds"] is True
    assert all(
        not (
            row["judge_private"]["latent"]["a"] < -0.55
            and row["judge_private"]["latent"]["b"] < -0.55
        )
        for row in pack["training_episodes"]
    )
    novel = [row for row in pack["test_episodes"] if row["tier"] == "novel_quadrant"]
    assert novel and all(
        row["judge_private"]["latent"]["a"] < -0.55
        and row["judge_private"]["latent"]["b"] < -0.55
        for row in novel
    )
    deletion = {row["control"]: row for row in pack["paired_controls"]["history_deletion"]}
    assert deletion["oracle_irrelevant"]["oracle_distance"] == pytest.approx(0.0, abs=1e-12)
    assert deletion["oracle_equivalent_redundant"]["oracle_distance"] == pytest.approx(0.0, abs=1e-12)
    assert deletion["latent_relevant"]["oracle_distance"] >= pack["thresholds"]["oracle_distinguishable_l2"]
    assert pack["new_task_contract"]["realized_future_noise_used"] is False
    primary_ids = {
        row.get("action_id", row.get("check_id", row.get("channel_id")))
        for field in ("observations", "actions", "checks")
        for row in pack["catalog"][field]
    }
    extension_ids = {
        row.get("action_id", row.get("check_id", row.get("channel_id")))
        for field in ("observations", "actions", "checks")
        for row in pack["extension_catalog"][field]
    }
    assert "rt_biphasic" not in primary_ids and "rt_new_check" not in primary_ids
    assert {"rt_biphasic", "rt_new_check", "rt_new_check_signal"} <= extension_ids
    _, records = training_records(pack)
    assert records and all(len(record.rollouts) == 9 for record in records)


def test_custody_is_hiding_external_and_tamper_evident(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    commitment_path = repository / "research" / "commitment.json"
    reveal_path = tmp_path / "external-custody" / "reveal.json"
    commitment = prepare_custody(
        secret=DUMMY_SECRET,
        repository_root=repository,
        commitment_path=commitment_path,
        external_reveal_path=reveal_path,
        pre_pack_git_commit="deadbeef",
        candidate_source_bindings=candidate_source_bindings(),
        created_at="2026-07-19T00:00:00+00:00",
        training_count=24,
        ordinary_test_count=12,
    )
    assert "secret_hex" not in canonical_json_bytes(commitment).decode("utf-8")
    reveal = _json(reveal_path)
    assert verify_reveal(commitment, reveal)["catalog_digest"]
    tampered = json.loads(canonical_json_bytes(reveal))
    tampered["pack"]["thresholds"]["state_equivalence_l2"] = 0.5
    with pytest.raises(ProtocolViolation, match="reveal does not match"):
        verify_reveal(commitment, tampered)
    with pytest.raises(ProtocolViolation, match="outside repository"):
        prepare_custody(
            secret=DUMMY_SECRET,
            repository_root=repository,
            commitment_path=commitment_path,
            external_reveal_path=repository / "leaked-reveal.json",
            pre_pack_git_commit="deadbeef",
            candidate_source_bindings=candidate_source_bindings(),
            created_at="2026-07-19T00:00:00+00:00",
            training_count=24,
            ordinary_test_count=12,
        )


def test_dummy_one_shot_run_has_both_implementations_all_raw_and_verifies(tmp_path: Path) -> None:
    repository = tmp_path / "fake-repository"
    repository.mkdir()
    commitment_path = repository / "commitment.json"
    reveal_path = tmp_path / "external" / "reveal.json"
    prepare_custody(
        secret=DUMMY_SECRET,
        repository_root=repository,
        commitment_path=commitment_path,
        external_reveal_path=reveal_path,
        pre_pack_git_commit="deadbeef",
        candidate_source_bindings=candidate_source_bindings(),
        created_at="2026-07-19T00:00:00+00:00",
        training_count=24,
        ordinary_test_count=12,
    )
    run = run_redteam_v2(
        repository_root=repository,
        commitment_path=commitment_path,
        external_reveal_path=reveal_path,
        output_root=tmp_path / "results",
        commitment_git_commit=None,
        enforce_git_chronology=False,
    )
    verification = verify_redteam_v2_run(run)
    assert verification["verified"] is True
    summary = _json(run / "summary.json")
    chronology = _json(run / "chronology.json")
    assert summary["implementations"] == ["independent_f18", "sealed_f18"]
    assert chronology["both_implementations_finished_before_reveal"] is True
    assert chronology["retry_count"] == 0
    assert summary["evidence_boundary"]["os_sandbox"] is False
    assert summary["evidence_boundary"]["head_inputs_state_only"] is True

    episodes = _rows(run / "raw-episodes.jsonl")
    pairs = _rows(run / "raw-pairs.jsonl")
    probes = _rows(run / "raw-probes.jsonl")
    access = _rows(run / "access-trace.jsonl")
    closures = _rows(run / "state-closures.jsonl")
    attack_ids = {row["attack_id"] for row in [*episodes, *pairs, *probes]}
    assert set(REQUIRED_ATTACK_CLASSES) <= attack_ids
    assert {row["implementation_id"] for row in closures} == {"sealed_f18", "independent_f18"}
    assert all(row["pre_state_hash"] == row["post_state_hash"] for row in episodes)
    assert all(row["passed"] for row in access)
    assert all(
        row["allowed_patient_input"] == "SharedPatientState only"
        for row in access
        if row["operation"] in {"diagnose", "rollout"}
    )
    time_rows = [row for row in episodes if row["attack_id"] == "same_state_time_scales"]
    assert {row["query"]["horizon"] for row in time_rows} == {1, 24, 168}
    assert len({row["pre_state_hash"] for row in time_rows if row["implementation_id"] == "sealed_f18"}) == 1
    deletion = [row for row in pairs if row["attack_id"] == "history_deletion_trio"]
    assert {row["control"] for row in deletion} == {
        "oracle_irrelevant",
        "latent_relevant",
        "oracle_equivalent_redundant",
    }
    capacities = [row for row in probes if row["attack_id"] == "new_task_conditional_expected_future_utility"]
    assert {row["view"] for row in capacities} == {
        "state_only",
        "same_capacity_full_visible_history",
        "true_state_upper_bound",
    }
    assert {row["capacity"] for row in capacities} == {8, 32, 128}
    compliance = [row for row in probes if row["attack_id"] == "query_update_rehydrate_compliance"]
    assert compliance and all(
        row["query_order_diagnosis_equal"]
        and row["query_order_rollout_equal"]
        and row["cold_state_hash_equal"]
        and row["cold_diagnosis_equal"]
        and row["cold_rollout_equal"]
        and row["primary_scope_update_replay_match"]
        for row in compliance
    )
    new_treatment = [row for row in episodes if row["attack_id"] == "new_treatment_opposite_response"]
    assert new_treatment and all(row["operator_in_primary_scope"] is False for row in new_treatment)
    assert all(row["scope_result"] == "scope_insufficient" for row in new_treatment)
    assert {row["oracle_effect_sign"] for row in new_treatment} == {-1, 1}
    new_check = [row for row in probes if row["attack_id"] == "new_check"]
    assert new_check and all(row["scope_result"] == "nonadmissible_old_scope_update_attempt" for row in new_check)

    compressed_only = tmp_path / "compressed-only-clone"
    shutil.copytree(run, compressed_only)
    for name in summary["raw_receipts"]:
        (compressed_only / name).unlink()
    assert verify_redteam_v2_run(compressed_only)["verified"] is True

    # The verifier must independently reject an artifact byte mutation.
    damaged = tmp_path / "damaged"
    shutil.copytree(run, damaged)
    path = damaged / "raw-pairs.jsonl"
    path.write_bytes(path.read_bytes() + b"{}\n")
    with pytest.raises(ProtocolViolation, match="artifact digest mismatch"):
        verify_redteam_v2_run(damaged)
