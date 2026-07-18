from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import pytest

from prototype.unified_map.canonical import ProtocolViolation, digest_json
from prototype.unified_map.upper_bound_evaluator import (
    compute_upper_bound_bundle_root,
)
from prototype.unified_map.upper_bound_evaluator_w02 import (
    DEFAULT_W02_ARTIFACT,
    run_w02_upper_bound_sanity,
    verify_w02_upper_bound_sanity,
)
from prototype.unified_map.upper_bound_evaluator_w04 import (
    DEFAULT_W04_ARTIFACT,
    run_w04_upper_bound_sanity,
    verify_w04_upper_bound_sanity,
)
from prototype.unified_map.upper_bound_evaluator_w08 import (
    DEFAULT_W08_ARTIFACT,
    run_w08_upper_bound_sanity,
    verify_w08_upper_bound_sanity,
)
from prototype.unified_map.upper_bound_evaluator_w15 import (
    DEFAULT_W15_ARTIFACT,
    run_w15_upper_bound_sanity,
    verify_w15_upper_bound_sanity,
)
from prototype.unified_map.upper_bound_evaluator_w18 import (
    DEFAULT_W18_ARTIFACT,
    run_w18_upper_bound_sanity,
    verify_w18_upper_bound_sanity,
)
from prototype.unified_map.upper_bound_evaluator_w19 import (
    DEFAULT_W19_ARTIFACT,
    run_w19_upper_bound_sanity,
    verify_w19_upper_bound_sanity,
)
from prototype.unified_map.upper_bound_evaluator_w20 import (
    DEFAULT_W20_ARTIFACT,
    run_w20_upper_bound_sanity,
    verify_w20_upper_bound_sanity,
)


@dataclass(frozen=True)
class _Adapter:
    source_artifact: Path
    run: Callable[..., dict]
    verify: Callable[..., None]


ADAPTERS = {
    "W02": _Adapter(
        Path(DEFAULT_W02_ARTIFACT),
        run_w02_upper_bound_sanity,
        verify_w02_upper_bound_sanity,
    ),
    "W04": _Adapter(
        Path(DEFAULT_W04_ARTIFACT),
        run_w04_upper_bound_sanity,
        verify_w04_upper_bound_sanity,
    ),
    "W08": _Adapter(
        Path(DEFAULT_W08_ARTIFACT),
        run_w08_upper_bound_sanity,
        verify_w08_upper_bound_sanity,
    ),
    "W15": _Adapter(
        Path(DEFAULT_W15_ARTIFACT),
        run_w15_upper_bound_sanity,
        verify_w15_upper_bound_sanity,
    ),
    "W18": _Adapter(
        Path(DEFAULT_W18_ARTIFACT),
        run_w18_upper_bound_sanity,
        verify_w18_upper_bound_sanity,
    ),
    "W19": _Adapter(
        Path(DEFAULT_W19_ARTIFACT),
        run_w19_upper_bound_sanity,
        verify_w19_upper_bound_sanity,
    ),
    "W20": _Adapter(
        Path(DEFAULT_W20_ARTIFACT),
        run_w20_upper_bound_sanity,
        verify_w20_upper_bound_sanity,
    ),
}


@pytest.fixture(scope="module")
def world_bundles() -> dict[str, dict]:
    return {
        world_slot: adapter.run(source_artifact=adapter.source_artifact)
        for world_slot, adapter in ADAPTERS.items()
    }


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


def _resign(bundle: dict) -> dict:
    bundle["cell_set_root"] = _cell_set_root(bundle["cells"])
    bundle["bundle_root"] = compute_upper_bound_bundle_root(bundle)
    return bundle


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_world_adapter_live_replay_keeps_zero_credit_status(
    world_slot: str,
    world_bundles: dict[str, dict],
) -> None:
    adapter = ADAPTERS[world_slot]
    bundle = world_bundles[world_slot]

    adapter.verify(
        bundle,
        source_artifact=adapter.source_artifact,
        replay_runtime=True,
    )
    assert bundle["world_slot"] == world_slot
    assert bundle["bundle_root"] == compute_upper_bound_bundle_root(bundle)
    assert bundle["cell_set_root"] == _cell_set_root(bundle["cells"])
    assert bundle["status_chain"] == {
        "analysis_weight": 0.0,
        "benchmark_freeze_evidence": False,
        "benchmark_status": "PRE-FREEZE",
        "candidate_eligible": False,
        "candidate_gate": "NOT_APPLICABLE",
        "eligibility": "upper_bound_only",
        "experiment_status": "NOT_COUNT_ELIGIBLE",
        "formal_run": False,
        "freeze_grade": False,
        "ledger_credit": 0,
        "privileged": True,
    }
    assert bundle["scope_statement"]["candidate_performance_claimed"] is False
    assert bundle["verification_summary"]["ledger_credit"] == 0


def test_w02_separates_privileged_identity_from_public_posterior(
    world_bundles: dict[str, dict],
) -> None:
    bundle = world_bundles["W02"]
    cells = _cells_by_id(bundle)
    identity = cells["W02.initial.privileged_true_class_identity"]

    assert identity["oracle_target"]["probabilities"] == [1.0, 0.0]
    public_posterior = identity["public_oracle_audit"]["public_posterior"]
    assert 0.49 < public_posterior[0] < 0.51
    assert 0.49 < public_posterior[1] < 0.51
    assert bundle["scope_statement"]["public_posterior_primary_claimed"] is False
    assert (
        bundle["verification_summary"]["source_distinct_explicit_state_oracle_pairs"]
        == 0
    )

    intervention = cells["W02.initial.intervention"]
    assert intervention["metric"]["worst_regret"] == 0.0
    assert intervention["degraded_control_metric"]["worst_regret"] > 2.0


def test_w04_modifier_retains_opposite_patient_specific_actions(
    world_bundles: dict[str, dict],
) -> None:
    cells = _cells_by_id(world_bundles["W04"])
    pair = cells["W04.patient_pair.collision"]

    assert pair["natural_mean_paths"]["C0"] == pair["natural_mean_paths"]["C1"]
    assert pair["optimal_action_aliases"] == {"C0": "single_A1", "C1": "single_A2"}
    classification = pair["classification"]
    assert classification["candidate_distance"] == pytest.approx(
        classification["oracle_distance"]
    )
    assert classification["cross_applied_regret"] > 4.0
    assert classification["dangerous_collision"] is False
    assert classification["attributable_collision"] is False


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_default_verifier_rejects_a_resigned_forged_source_anchor(
    world_slot: str,
    world_bundles: dict[str, dict],
) -> None:
    tampered = deepcopy(world_bundles[world_slot])
    forged_digest = "sha256:" + ("0" * 64)
    tampered["source_anchor"].update(
        {
            "artifact_relpath": "forged.json",
            "artifact_digest": forged_digest,
            "artifact_bytes": 1,
            "replay_digest": forged_digest,
        }
    )
    _resign(tampered)

    with pytest.raises(ProtocolViolation):
        ADAPTERS[world_slot].verify(tampered, replay_runtime=True)


@pytest.mark.parametrize("world_slot", ADAPTERS)
def test_default_verifier_rejects_a_resigned_forged_source_path(
    world_slot: str,
    world_bundles: dict[str, dict],
) -> None:
    tampered = deepcopy(world_bundles[world_slot])
    tampered["source_anchor"]["artifact_relpath"] = "does-not-exist/forged-source.json"
    _resign(tampered)

    with pytest.raises(ProtocolViolation):
        ADAPTERS[world_slot].verify(tampered, replay_runtime=True)


def test_w08_pending_results_are_firewalled_until_availability(
    world_bundles: dict[str, dict],
) -> None:
    cells = _cells_by_id(world_bundles["W08"])
    firewall = cells["W08.preavailability.pending_firewall"]

    assert firewall["left_pending_digest"] != firewall["right_pending_digest"]
    assert firewall["left_state_hash"] == firewall["right_state_hash"]
    update = cells["W08.late_result.update"]
    assert update["prior_state_hash"] == update["parent_state_hash"]
    assert update["state_hash"] != update["prior_state_hash"]
    assert any(
        event["kind"] == "observation_available" for event in update["delta"]["events"]
    )


def test_w18_excludes_irreducible_alias_from_primary_ood_metrics(
    world_bundles: dict[str, dict],
) -> None:
    bundle = world_bundles["W18"]
    cells = _cells_by_id(bundle)
    ood = bundle["collector_metrics"]["ood"]

    assert ood["auroc"] == 1.0
    assert ood["average_precision"] == 1.0
    assert ood["primary_denominator"] == 2
    assert ood["irreducible_excluded_count"] == 1
    irreducible = cells["W18.irreducible_alias.ood"]
    assert irreducible["oracle_scoring"]["primary_ood_scored"] is False
    abstained = cells["W18.attributable_updated.intervention"]
    assert abstained["abstain"] is True
    assert abstained["selection_scored"] is False
    assert abstained["metric"] is None


def test_w15_separates_identified_effect_from_nonidentified_set(
    world_bundles: dict[str, dict],
) -> None:
    bundle = world_bundles["W15"]
    cells = _cells_by_id(bundle)
    assert {cell["panel_id"] for cell in cells.values() if cell["panel"] == "W15A"} == {
        "W15A-randomized-identifiable"
    }
    assert {cell["panel_id"] for cell in cells.values() if cell["panel"] == "W15B"} == {
        "W15B-observational-nonidentified"
    }
    scope = bundle["scope_statement"]
    assert scope["source_distinct_reference_oracle_claimed"] is False
    assert scope["evidence_assimilation_claimed"] is False
    assert scope["observational_association_used_as_do_effect"] is False

    identified = cells["W15.W15A.initial.intervention"]

    assert set(identified["do_effect"].values()) == {-0.35}
    assert identified["metric"]["worst_regret"] == 0.0
    assert identified["degraded_control_metric"]["catastrophic_count"] == 1
    update = cells["W15.W15A.update"]
    assert update["expected_next_severity"] == pytest.approx(0.478)
    assert update["structural_replay_next_severity"] == pytest.approx(0.478)
    assert update["delta_observation_matches_structural_replay"] is True

    twin = cells["W15.W15B.public_twin"]
    assert twin["state_hash"] == twin["plus_state_hash"] == twin["minus_state_hash"]
    assert twin["plus_public_history_digest"] == twin["minus_public_history_digest"]
    assert twin["private_structural_effect_witness"] == {
        "plus": 1.0,
        "minus": -1.0,
    }
    assert twin["private_identity_in_candidate_state"] is False

    identified_set = cells["W15.W15B.identified_set"]
    assert identified_set["diagnosis_metric"] is None
    assert identified_set["treatment_regret_metric"] is None
    contracts = identified_set["support_contracts"]
    assert contracts["no_new_action"]["observation_support"] == [0.0, 0.0, 0.0, 2.0]
    assert contracts["no_new_action"]["policy_utility_support"] == [
        0.0,
        0.0,
        0.0,
        2.0,
    ]
    assert contracts["do_A1"]["observation_support"] == [1.0, 1.0, -1.0, 1.0]
    assert contracts["do_A1"]["policy_utility_support"] == [
        0.95,
        0.95,
        -1.05,
        0.95,
    ]
    for support in contracts.values():
        assert support["ate_identified_set"] == [-1.0, 1.0]
        assert support["observation_probabilities"] == [0.25] * 4
        assert support["recommendation"] == "abstain"
        assert support["point_effect_scored"] is False
        assert support["realized_private_scm_scored"] is False
        assert support["structural_replay"]["reference_independence_certified"] is False


def test_w19_tail_posterior_changes_the_safety_decision(
    world_bundles: dict[str, dict],
) -> None:
    bundle = world_bundles["W19"]
    cells = _cells_by_id(bundle)
    initial = cells["W19.initial.tail_aware_intervention"]["safety_decision"]
    updated = cells["W19.updated.tail_aware_intervention"]["safety_decision"]

    assert bundle["verification_summary"]["private_aliases_share_one_state"] is True
    assert bundle["verification_summary"]["initial_tail_probability"] == 0.015625
    assert bundle["verification_summary"]["updated_tail_probability"] > 0.43
    assert initial["panel_expected_value_argmax"] == "do_A1"
    assert initial["panel_expected_argmax_rejected_by_tail_gate"] is True
    assert initial["panel_eligible_argmax"] == "do_A2"
    assert updated["panel_expected_value_argmax"] == "do_A2"
    assert updated["panel_eligible_argmax"] == "do_A2"


def test_w20_retains_exposure_and_quotients_nonpredictive_evidence_count(
    world_bundles: dict[str, dict],
) -> None:
    bundle = world_bundles["W20"]
    cells = _cells_by_id(bundle)
    expected_thresholds = {
        "candidate_same_epsilon": 0.008,
        "candidate_split_delta": 0.38,
        "catastrophic_margin": 0.8,
        "oracle_distinguishable_delta": 0.38,
        "oracle_equivalent_epsilon": 0.008,
    }
    assert bundle["collector_metrics"]["pair_thresholds"] == expected_thresholds
    collision = cells["W20.physiology_only.compression_collision"]

    assert collision["pair_thresholds"] == expected_thresholds
    assert collision["signatures_collide"] is True
    assert collision["full_states_distinct"] is True
    assert collision["low_expected_utility_argmax"] == "do_A1"
    assert collision["high_expected_utility_argmax"] == "no_new_action"
    assert collision["optimal_actions_differ"] is True
    assert collision["max_cross_applied_regret"] > 2.0
    assert collision["pair_classification"]["dangerous_collision"] is True
    assert collision["pair_classification"]["attributable_collision"] is True
    assert collision["pair_classification"]["cross_applied_regret"] > 2.0

    for cell_id in (
        "W20.low.initial.shared_state",
        "W20.high.initial.shared_state",
        "W20.updated.shared_state",
    ):
        panel = cells[cell_id]
        assert panel["treatment_regret_metric"]["worst_regret"] == 0.0
        assert set(panel["projection_checks"]) == {
            "no_new_action",
            "do_A1",
            "do_A2",
        }
        assert all(
            projection["joint_temporal_law_scored"] is False
            for projection in panel["projection_checks"].values()
        )

    update = cells["W20.combined_action_response.update"]
    reversal = update["response_reversal"]
    assert reversal["before_a1_first_mean"] < reversal["before_no_action_first_mean"]
    assert reversal["after_a1_first_mean"] > reversal["after_no_action_first_mean"]
    assert reversal["direction_reversed"] is True
    replay = update["full_history_batch_replay"]
    assert replay["production_full_history"] == replay["reference_full_history"]
    assert replay["production_reference_exact_at_wire_precision"] is True
    assert (
        replay["sealed_quantization_max_abs_error"]
        <= replay["sealed_quantization_error_bound"]
    )

    behavior_alias = cells["W20.evidence_count.behavior_alias"]
    assert behavior_alias["pair_thresholds"] == expected_thresholds
    assert behavior_alias["posterior_and_exposure_equal"] is True
    assert behavior_alias["raw_evidence_counts"] == [5, 6]
    assert behavior_alias["raw_history_digests_different"] is True
    assert behavior_alias["raw_evidence_counts_different"] is True
    assert behavior_alias["state_hashes_equal"] is True
    assert behavior_alias["state_identity_fields"] == [
        "as_of_available_at",
        "posterior_mean",
        "posterior_variance",
        "exposure_memory",
    ]
    assert behavior_alias["state_identity_excludes"] == [
        "public_history_digest",
        "raw_evidence_count",
    ]
    triplet = behavior_alias["added_q1_event_triplet"]
    assert [event["kind"] for event in triplet] == [
        "test_ordered",
        "test_performed",
        "observation_available",
    ]
    assert triplet[0]["payload"] == {"check_id": "Q1"}
    assert triplet[1]["payload"] == {"check_id": "Q1"}
    assert triplet[1]["collected_at"] == -1
    assert triplet[2]["payload"]["channel_id"] == "obs_1"
    assert triplet[2]["collected_at"] == -1
    assert triplet[2]["available_at"] == 0
    assert behavior_alias["full_h4_policy_count"] == 9
    assert behavior_alias["full_h4_policy_semantics_equal"] is True
    assert behavior_alias["legacy_count_argument_semantically_inert"] is True
    assert all(
        row["semantic_equal"] is True
        and row["raw_count_semantics_equal_state_sentinel"] is True
        for row in behavior_alias["policy_semantic_witnesses"]
    )
    assert behavior_alias["known_false_split_repaired"] is True
    assert behavior_alias["false_split_detected"] is False
    assert behavior_alias["minimal_quotient_claimed"] is False
    assert behavior_alias["formal_blocker"] == "minimal-behavioral-quotient-not-proved"
    assert behavior_alias["pair_classification"]["candidate_distance"] == 0.0
    assert behavior_alias["pair_classification"]["oracle_distance"] == 0.0
    assert behavior_alias["pair_classification"]["false_split"] is False
    assert behavior_alias["pair_classification"]["dangerous_collision"] is False

    states = bundle["states"]
    low_binding = states["low_initial"]
    q1_binding = states["low_plus_nonpredictive_q1"]
    assert low_binding["record"]["state_hash"] == q1_binding["record"]["state_hash"]
    assert low_binding["payload"] == q1_binding["payload"]
    representation = low_binding["payload"]["representation"]
    assert set(representation) == {
        "protocol",
        "world_slot",
        "as_of_available_at",
        "posterior_mean",
        "posterior_variance",
        "exposure_memory",
    }
    assert "evidence_count" not in representation
    provenance = bundle["history_evidence_provenance"]
    assert (
        provenance["low_initial"]["public_history_digest"]
        != provenance["low_plus_nonpredictive_q1"]["public_history_digest"]
    )
    assert provenance["low_initial"]["raw_evidence_count"] == 5
    assert provenance["low_plus_nonpredictive_q1"]["raw_evidence_count"] == 6
    assert all(
        item["raw_history_in_state_identity"] is False
        and item["raw_evidence_count_in_state_identity"] is False
        for item in provenance.values()
    )

    scope = bundle["scope_statement"]
    summary = bundle["verification_summary"]
    assert scope["known_evidence_count_false_split_open"] is False
    assert scope["minimal_behavioral_quotient_claimed"] is False
    assert scope["source_distinct_reference_oracle_claimed"] is False
    assert scope["joint_temporal_law_claimed"] is False
    assert scope["action_only_update_claimed"] is False
    runtime = bundle["runtime_semantics"]
    assert runtime["production_oracle"] == (
        "covariance-form-filter-plus-branch-enumeration"
    )
    assert runtime["reference_oracle"] == (
        "information-form-filter-plus-independent-enumeration"
    )
    assert runtime["legacy_document_sobol_r_grid_description_matches_runtime"] is False
    assert runtime["source_distinct_sealed_state_reference_collected"] is False
    assert summary["known_evidence_count_false_split_repaired"] is True
    assert summary["nonpredictive_false_split_detected"] is False
    assert summary["full_h4_policy_behavior_alias_witness_count"] == 9
    assert summary["minimal_quotient_claimed"] is False
    assert (
        "evidence-count-nonpredictive-false-split"
        not in summary["formalization_blockers"]
    )
    assert "nonminimal-state-quotient" not in summary["formalization_blockers"]
    assert "minimal-behavioral-quotient-not-proved" in summary["formalization_blockers"]
    assert {
        "source-distinct-sealed-state-reference-not-collected",
        "runtime-document-oracle-method-drift",
        "marginal-moments-no-joint-temporal-law",
        "combined-action-response-update-not-action-only",
    }.issubset(summary["formalization_blockers"])


def test_w20_rejects_resigned_history_evidence_provenance_tamper(
    world_bundles: dict[str, dict],
) -> None:
    tampered = deepcopy(world_bundles["W20"])
    tampered["history_evidence_provenance"]["low_plus_nonpredictive_q1"][
        "raw_evidence_count"
    ] += 1
    _resign(tampered)

    with pytest.raises(ProtocolViolation):
        ADAPTERS["W20"].verify(tampered, replay_runtime=True)


def _tamper_w02(bundle: dict) -> None:
    _cells_by_id(bundle)["W02.initial.privileged_true_class_identity"]["metric"][
        "accuracy"
    ] = 0.5


def _tamper_w04(bundle: dict) -> None:
    _cells_by_id(bundle)["W04.patient_pair.collision"]["classification"][
        "candidate_distance"
    ] += 0.25


def _tamper_w08(bundle: dict) -> None:
    _cells_by_id(bundle)["W08.preavailability.pending_firewall"][
        "left_pending_results"
    ][0]["value"] += 0.25


def _tamper_w18(bundle: dict) -> None:
    bundle["collector_metrics"]["ood"]["auroc"] = 0.5


def _tamper_w15(bundle: dict) -> None:
    _cells_by_id(bundle)["W15.W15B.identified_set"]["support_contracts"]["do_A1"][
        "ate_identified_set"
    ][0] = -0.5


def _tamper_w19(bundle: dict) -> None:
    _cells_by_id(bundle)["W19.initial.diagnosis"][
        "posterior_tail_from_state_bytes"
    ] += 0.125


def _tamper_w20(bundle: dict) -> None:
    _cells_by_id(bundle)["W20.evidence_count.behavior_alias"][
        "full_h4_policy_semantics_equal"
    ] = False


TAMPERS = {
    "W02": _tamper_w02,
    "W04": _tamper_w04,
    "W08": _tamper_w08,
    "W15": _tamper_w15,
    "W18": _tamper_w18,
    "W19": _tamper_w19,
    "W20": _tamper_w20,
}


@pytest.mark.parametrize("world_slot", TAMPERS)
def test_semantic_tamper_fails_after_cell_and_bundle_roots_are_recomputed(
    world_slot: str,
    world_bundles: dict[str, dict],
) -> None:
    tampered = deepcopy(world_bundles[world_slot])
    TAMPERS[world_slot](tampered)
    _resign(tampered)

    with pytest.raises(ProtocolViolation):
        ADAPTERS[world_slot].verify(tampered)
