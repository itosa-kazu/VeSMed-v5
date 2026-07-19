from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from prototype.unified_map import final_evidence
from prototype.unified_map.canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_json,
)


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "research/unified_map/FINAL_EVIDENCE.json"


def _load() -> dict:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def test_final_evidence_reverifies_all_decision_grade_inputs() -> None:
    verification = final_evidence.verify_final_evidence(EVIDENCE, repo_root=ROOT)
    evidence = _load()

    assert verification["status"] == "verified"
    assert verification["final_evidence_root"] == evidence["final_evidence_root"]
    assert evidence["benchmark"]["freeze_root"] == final_evidence.FREEZE_ROOT
    expected_accounting = {
        "total_experiments": 38,
        "count_eligible": 30,
        "count_ineligible": 8,
        "evidence_gap_count": 0,
        "failed_attempt_count": 1,
    }
    assert all(
        evidence["experiments"]["accounting"][key] == value
        for key, value in expected_accounting.items()
    )

    primary = evidence["primary_full_candidates"]
    assert [row["family"] for row in primary] == ["F10", "F14", "F18"]
    assert [row["raw_episode_count"] for row in primary] == [1680, 1680, 1680]
    assert [row["hard_gate_pass"] for row in primary] == [False, False, False]
    assert [row["hard_failures"]["unsafe_forced_known_ood"] for row in primary] == [
        5,
        21,
        5,
    ]
    assert evidence["primary_decision"]["hard_gate_eligible_pareto_front"] == []

    supplemental = evidence["supplemental_confirm5_lite"]
    assert supplemental["complete_benchmark"] is False
    assert supplemental["no_pair_collision_evidence"] is True
    assert supplemental["local_ucm_pareto_front"] == ["F10", "F18"]

    redteam = evidence["source_distinct_redteam_v2"]["overall_verdict"]
    expected_redteam = {
        "closed_catalog": "CLOSED_CATALOG_LOCAL_SUPPORT",
        "new_task_sufficiency": "INCONCLUSIVE",
        "open_world_extensions": "OPEN_WORLD_SCOPE_FAILURE",
        "state_minimality": "NOT_SUPPORTED",
    }
    assert all(redteam[key] == value for key, value in expected_redteam.items())

    reproduction = evidence["independent_reproduction"]
    assert reproduction["exact_core_reproduction"] is True
    assert reproduction["episode_count"] == 1680
    assert reproduction["rollout_query_count"] == 28720
    assert reproduction["pair_count"] == 260
    assert set(reproduction["differences"].values()) == {0.0}
    assert set(reproduction["failures"].values()) == {0}


def test_final_evidence_rejects_a_tampered_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _load()
    tampered = copy.deepcopy(expected)
    tampered["final_evidence_root"] = "sha256:" + "0" * 64
    path = tmp_path / "tampered-root.json"
    path.write_bytes(canonical_json_bytes(tampered))
    monkeypatch.setattr(final_evidence, "derive_final_evidence", lambda _root: expected)

    with pytest.raises(ProtocolViolation, match="root mismatch"):
        final_evidence.verify_final_evidence(path, repo_root=ROOT)


def test_final_evidence_rejects_semantic_strengthening_even_with_a_valid_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected = _load()
    strengthened = copy.deepcopy(expected)
    strengthened["final_conclusion"]["production_safety_claimed"] = True
    preimage = {
        key: value
        for key, value in strengthened.items()
        if key != "final_evidence_root"
    }
    strengthened["final_evidence_root"] = digest_json(preimage)
    path = tmp_path / "strengthened.json"
    path.write_bytes(canonical_json_bytes(strengthened))
    monkeypatch.setattr(final_evidence, "derive_final_evidence", lambda _root: expected)

    with pytest.raises(ProtocolViolation, match="differs from live verified evidence"):
        final_evidence.verify_final_evidence(path, repo_root=ROOT)
