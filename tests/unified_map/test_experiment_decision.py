from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototype.unified_map.canonical import ProtocolViolation, canonical_json_bytes
from prototype.unified_map.experiment_decision import verify_experiment_decision


ROOT = Path(__file__).resolve().parents[2]
DECISION = ROOT / "research/unified_map/experiment_decisions/EXP-038.json"


def test_exp038_decision_rebinds_preregistration_run_and_hard_gate() -> None:
    decision = verify_experiment_decision(DECISION, repo_root=ROOT)
    assert decision["decision"] == "ABANDON"
    assert decision["candidate_disposition"] == "DO_NOT_KEEP_OR_REFINE"
    assert decision["legal_policy_totality_fix"]["status"] == "SUPPORTED_IN_SCREEN"
    assert decision["observed_result"]["hard_gate_pass"] is False
    assert decision["observed_result"]["hard_failures"] == {
        "dangerous_collision": 1,
        "query_order_impurity": 0,
        "unsafe_forced_known_ood": 1,
        "update_inconsistency": 0,
    }
    assert all(
        row["match"] is True
        for row in decision["planned_config_comparison"].values()
    )


def test_exp038_decision_rejects_posthoc_result_relabeling(tmp_path: Path) -> None:
    decision = json.loads(DECISION.read_bytes())
    decision["decision"] = "KEEP"
    mutated = tmp_path / "EXP-038.json"
    mutated.write_bytes(canonical_json_bytes(decision))
    with pytest.raises(ProtocolViolation, match="abandonment"):
        verify_experiment_decision(mutated, repo_root=ROOT)


def test_exp038_decision_rejects_planned_config_rewrite(tmp_path: Path) -> None:
    decision = json.loads(DECISION.read_bytes())
    decision["planned_config_comparison"]["train_episodes_per_panel"]["planned"] = 999
    mutated = tmp_path / "EXP-038.json"
    mutated.write_bytes(canonical_json_bytes(decision))
    with pytest.raises(ProtocolViolation, match="configuration comparison"):
        verify_experiment_decision(mutated, repo_root=ROOT)

