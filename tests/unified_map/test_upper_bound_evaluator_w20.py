from __future__ import annotations

from copy import deepcopy

import pytest

from prototype.unified_map.canonical import ProtocolViolation, digest_json
from prototype.unified_map.upper_bound_evaluator import (
    compute_upper_bound_bundle_root,
)
from prototype.unified_map.upper_bound_evaluator_w20 import (
    run_w20_upper_bound_sanity,
    verify_w20_upper_bound_sanity,
)


@pytest.fixture(scope="module")
def w20_bundle() -> dict:
    report = run_w20_upper_bound_sanity()
    verify_w20_upper_bound_sanity(report, replay_runtime=True)
    return report


def _cells(report: dict) -> dict[str, dict]:
    return {cell["cell_id"]: cell for cell in report["cells"]}


def _resign(report: dict) -> None:
    identities = [
        {
            "cell_id": cell["cell_id"],
            "cut_alias": cell["cut_alias"],
            "task": cell["task"],
            "cell_digest": digest_json(cell),
        }
        for cell in report["cells"]
    ]
    identities.sort(key=lambda item: item["cell_id"].encode("utf-8"))
    report["cell_set_root"] = digest_json(
        {
            "protocol": "ucm-upper-bound-cell-set-root/1",
            "identities": identities,
        }
    )
    report["bundle_root"] = compute_upper_bound_bundle_root(report)


def test_w20_nonpredictive_q1_aliases_to_one_behavior_state(
    w20_bundle: dict,
) -> None:
    states = w20_bundle["states"]
    left = states["low_initial"]
    right = states["low_plus_nonpredictive_q1"]
    assert left["record"]["state_hash"] == right["record"]["state_hash"]
    assert left["payload"] == right["payload"]
    assert set(left["payload"]["representation"]) == {
        "protocol",
        "world_slot",
        "as_of_available_at",
        "posterior_mean",
        "posterior_variance",
        "exposure_memory",
    }

    provenance = w20_bundle["history_evidence_provenance"]
    left_audit = provenance["low_initial"]
    right_audit = provenance["low_plus_nonpredictive_q1"]
    assert left_audit["public_history_digest"] != right_audit["public_history_digest"]
    assert [
        left_audit["raw_evidence_count"],
        right_audit["raw_evidence_count"],
    ] == [5, 6]
    assert left_audit["raw_history_in_state_identity"] is False
    assert right_audit["raw_evidence_count_in_state_identity"] is False


def test_w20_behavior_alias_covers_all_nine_h4_policy_semantics(
    w20_bundle: dict,
) -> None:
    cell = _cells(w20_bundle)["W20.evidence_count.behavior_alias"]
    assert cell["posterior_and_exposure_equal"] is True
    assert cell["state_hashes_equal"] is True
    assert cell["raw_evidence_counts"] == [5, 6]
    assert cell["full_h4_policy_count"] == 9
    assert cell["full_h4_policy_semantics_equal"] is True
    assert cell["legacy_count_argument_semantically_inert"] is True
    assert len(cell["policy_semantic_witnesses"]) == 9
    assert all(
        row["semantic_equal"] is True
        and row["raw_count_semantics_equal_state_sentinel"] is True
        and row["left_semantic_digest"] == row["right_semantic_digest"]
        and row["left_semantic_digest"] == row["state_sentinel_semantic_digest"]
        for row in cell["policy_semantic_witnesses"]
    )
    assert cell["pair_classification"]["candidate_distance"] == 0.0
    assert cell["pair_classification"]["oracle_distance"] == 0.0
    assert cell["pair_classification"]["false_split"] is False


def test_w20_repairs_known_split_without_claiming_minimal_quotient(
    w20_bundle: dict,
) -> None:
    scope = w20_bundle["scope_statement"]
    summary = w20_bundle["verification_summary"]
    assert scope["known_evidence_count_false_split_open"] is False
    assert scope["minimal_behavioral_quotient_claimed"] is False
    assert summary["known_evidence_count_false_split_repaired"] is True
    assert summary["nonpredictive_false_split_detected"] is False
    assert summary["minimal_quotient_claimed"] is False
    assert summary["formalization_blockers"] == [
        "not-a-frozen-expected-cell-corpus",
        "patient-bound-rounded-state-projection-only",
        "marginal-moments-no-joint-temporal-law",
        "combined-action-response-update-not-action-only",
        "minimal-behavioral-quotient-not-proved",
        "source-distinct-sealed-state-reference-not-collected",
        "runtime-document-oracle-method-drift",
        "privileged-upper-bound-only",
    ]


@pytest.mark.parametrize("target", ["provenance", "policy_witness"])
def test_w20_live_verifier_rejects_resigned_semantic_tamper(
    w20_bundle: dict,
    target: str,
) -> None:
    tampered = deepcopy(w20_bundle)
    if target == "provenance":
        tampered["history_evidence_provenance"]["low_plus_nonpredictive_q1"][
            "raw_evidence_count"
        ] += 1
    else:
        _cells(tampered)["W20.evidence_count.behavior_alias"][
            "full_h4_policy_semantics_equal"
        ] = False
    _resign(tampered)

    with pytest.raises(ProtocolViolation):
        verify_w20_upper_bound_sanity(tampered, replay_runtime=True)
