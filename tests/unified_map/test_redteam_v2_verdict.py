from __future__ import annotations

import json
from pathlib import Path

import pytest

from prototype.unified_map.canonical import canonical_json_bytes
from prototype.unified_map.redteam_v2_verdict import (
    EXPECTED_ATTACK_CLASSES,
    VerdictViolation,
    derive_verdict,
    verify_verdict,
)


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = (
    ROOT
    / "results"
    / "unified_map"
    / "redteam_v2"
    / "20260719T093209Z-RT2-6337a6ad2d"
)
VERDICT = ROOT / "research" / "unified_map" / "REDTEAM_V2_VERDICT.json"


def _by_attack(verdict: dict) -> dict[str, dict]:
    return {row["attack_class"]: row for row in verdict["attack_verdicts"]}


def test_public_verdict_is_canonical_and_recomputed_from_bound_raw_bundle() -> None:
    receipt = verify_verdict(BUNDLE, VERDICT)
    assert receipt["verified"] is True
    assert receipt["bundle_root"] == (
        "sha256:d3b0ecfd8722e9863d84d3bd88ffa30d9e00b04976ac48b50cd00f02f34040b3"
    )

    first = derive_verdict(BUNDLE)
    second = derive_verdict(BUNDLE)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert tuple(row["attack_class"] for row in first["attack_verdicts"]) == (
        EXPECTED_ATTACK_CLASSES
    )

    attacks = _by_attack(first)
    assert attacks["ood"]["evidence"]["unsafe_forced_known_rows"] == 0
    assert attacks["dangerous_collision"]["evidence"][
        "recomputed_dangerous_collision_rows"
    ] == 0
    assert attacks["new_treatment_opposite_response"]["verdict"] == (
        "OPEN_WORLD_SCOPE_FAILURE"
    )
    assert attacks["new_treatment_opposite_response"]["evidence"]["abstained_rows"] == 216
    assert attacks["new_check"]["evidence"]["extension_refit_required_rows"] == 6
    assert attacks["new_check"]["evidence"]["visible_history_replay_required_rows"] == 6
    assert attacks["new_task_conditional_expected_future_utility"]["verdict"] == (
        "INCONCLUSIVE"
    )
    assert attacks["new_task_conditional_expected_future_utility"]["evidence"][
        "preregistered_decision_criterion_present"
    ] is False
    assert attacks["history_deletion_trio"]["verdict"] == "NON_MINIMAL_STATE_EVIDENCE"
    assert attacks["history_deletion_trio"]["evidence"][
        "oracle_equivalent_false_split_rows"
    ] == 4
    assert attacks["query_update_rehydrate_compliance"]["evidence"][
        "all_checks_passed"
    ] is True
    assert first["overall_verdict"] == {
        "clinical_effectiveness_claimed": False,
        "closed_catalog": "CLOSED_CATALOG_LOCAL_SUPPORT",
        "complete_benchmark_claimed": False,
        "global_optimality_claimed": False,
        "new_task_sufficiency": "INCONCLUSIVE",
        "open_world_extensions": "OPEN_WORLD_SCOPE_FAILURE",
        "state_minimality": "NOT_SUPPORTED",
        "summary": (
            "F18 has bounded local structural/safety support inside the committed "
            "synthetic catalog, but it requires extension fit plus visible-history "
            "replay for the unseen check/treatment and therefore does not establish "
            "an open-world unified map."
        ),
    }


def test_verifier_rejects_semantically_strengthened_verdict(tmp_path: Path) -> None:
    tampered = json.loads(VERDICT.read_bytes())
    tampered["attack_verdicts"][1]["verdict"] = "CLOSED_CATALOG_LOCAL_SUPPORT"
    tampered["overall_verdict"]["open_world_extensions"] = "SUPPORTED"
    path = tmp_path / "strengthened-verdict.json"
    path.write_bytes(canonical_json_bytes(tampered))
    with pytest.raises(VerdictViolation, match="differs from raw-derived verdict"):
        verify_verdict(BUNDLE, path)
