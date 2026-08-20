from __future__ import annotations

import json
import unittest
from pathlib import Path

from refinement_experiment import (
    CHILD_A,
    CHILD_B,
    NEW_ACTION,
    OLD_ACTIONS,
    TARGET_PARENT,
    build_target_pair,
    build_unaffected_patient,
    child_posterior,
    encode_old_state,
    find_new_action_collisions,
    make_refinement_record,
    old_query_fingerprint,
    old_state_is_sufficient,
    run_experiment,
    utility,
    write_results,
)


ROOT = Path(__file__).resolve().parents[1]


class LocalRefinementExperimentTests(unittest.TestCase):
    def test_old_state_is_exactly_shared_and_sufficient_for_old_actions(self) -> None:
        pair = build_target_pair(check_available=True)
        self.assertEqual(encode_old_state(pair[0]), encode_old_state(pair[1]))
        self.assertTrue(old_state_is_sufficient(pair))
        for action in OLD_ACTIONS:
            self.assertEqual(utility(pair[0], action), utility(pair[1], action))

    def test_new_treatment_freezes_exact_dangerous_collision_witness(self) -> None:
        pair = build_target_pair(check_available=True)
        witnesses = find_new_action_collisions(pair)
        self.assertEqual(len(witnesses), 1)
        witness = witnesses[0]
        self.assertEqual(witness.action, NEW_ACTION)
        self.assertTrue(witness.opposite_response)
        self.assertTrue(witness.disjoint_optima)
        self.assertEqual(witness.response_a, 6.0)
        self.assertEqual(witness.response_b, -10.0)

    def test_ordered_but_unavailable_check_cannot_split_parent(self) -> None:
        for patient in build_target_pair(check_available=True):
            status, posterior = child_posterior(
                patient,
                check_catalog_contains_biomarker=True,
                result_is_available=False,
            )
            self.assertEqual(status, "AWAITING_PUBLIC_CHECK")
            self.assertEqual(posterior, {CHILD_A: 0.5, CHILD_B: 0.5})

    def test_available_public_check_locally_splits_and_reduces_regret(self) -> None:
        results = run_experiment()["observable_refinement"]
        self.assertEqual(results["before_result"]["mean_oracle_regret"], 3.0)
        self.assertEqual(results["after_result"]["mean_oracle_regret"], 0.0)
        self.assertEqual(results["regret_reduction"], 3.0)
        self.assertEqual(
            results["after_result"]["statuses"],
            ["IDENTIFIED_BY_PUBLIC_CHECK", "IDENTIFIED_BY_PUBLIC_CHECK"],
        )
        self.assertEqual(results["after_result"]["choices"], [NEW_ACTION, "support"])

    def test_refinement_preserves_old_queries_and_unaffected_stratum(self) -> None:
        pair = build_target_pair(check_available=True)
        unaffected = build_unaffected_patient()
        before = old_query_fingerprint(pair + (unaffected,))
        record = make_refinement_record(check_available=True)
        after = old_query_fingerprint(pair + (unaffected,))
        self.assertEqual(before, after)
        self.assertEqual(record.affected_parent_strata, (TARGET_PARENT,))
        self.assertNotIn(unaffected.parent_stratum, record.affected_parent_strata)
        self.assertEqual(record.status, "LOCALLY_REFINED")

    def test_unobservable_subtype_is_not_forced_into_child(self) -> None:
        pair = build_target_pair(check_available=False)
        for patient in pair:
            status, posterior = child_posterior(
                patient,
                check_catalog_contains_biomarker=False,
                result_is_available=False,
            )
            self.assertEqual(status, "UNIDENTIFIABLE")
            self.assertEqual(posterior, {CHILD_A: 0.5, CHILD_B: 0.5})
        results = run_experiment()["unobservable_refinement"]
        self.assertEqual(results["classification"], "UNIDENTIFIABLE")
        self.assertFalse(results["forced_child_assignment"])
        self.assertFalse(results["individual_treatment_direction_identified"])
        self.assertGreater(results["mean_oracle_regret"], 0.0)

    def test_evidence_artifact_is_reproducible(self) -> None:
        path = ROOT / "evidence" / "refinement_results.json"
        expected = write_results(path)
        observed = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(observed, expected)
        self.assertFalse(observed["independence_boundary"]["uses_v5"])
        self.assertEqual(observed["new_action_collision"]["count"], 1)


if __name__ == "__main__":
    unittest.main()
