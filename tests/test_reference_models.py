from __future__ import annotations

import json
import unittest

from prototype.reference_models import (
    REFERENCE_VERSION,
    assert_reference_models_valid,
    public_model,
    reference_output,
    self_test_reference_models,
)


class ReferenceModelTests(unittest.TestCase):
    def test_all_reference_self_tests_pass(self) -> None:
        results = self_test_reference_models()
        self.assertGreaterEqual(len(results), 8)
        self.assertTrue(all(result.passed for result in results), [result.to_dict() for result in results])
        assert_reference_models_valid()

    def test_exact_see_do_reversal(self) -> None:
        result = reference_output("E02")
        self.assertAlmostEqual(result["P_bad_given_T1"], 0.545, places=12)
        self.assertAlmostEqual(result["P_bad_given_T0"], 0.270, places=12)
        self.assertAlmostEqual(result["P_bad_given_do_T1"], 0.325, places=12)
        self.assertAlmostEqual(result["P_bad_given_do_T0"], 0.550, places=12)
        self.assertGreater(result["P_bad_given_T1"], result["P_bad_given_T0"])
        self.assertLess(result["P_bad_given_do_T1"], result["P_bad_given_do_T0"])

    def test_exact_same_unit_counterfactual(self) -> None:
        result = reference_output("E03")
        self.assertEqual(result["posterior_R1"], 1.0)
        self.assertEqual(result["individual_counterfactual_Y_T0"], 1.0)
        self.assertEqual(result["population_do_mean_Y_T0"], 0.5)

    def test_public_records_are_detached_and_do_not_contain_answers(self) -> None:
        first = public_model("E02")
        first["P_severe"] = 99
        second = public_model("E02")
        self.assertEqual(second["P_severe"], 0.5)
        encoded = json.dumps(second, sort_keys=True)
        self.assertNotIn("P_bad_given_do_T1", encoded)
        self.assertNotIn("reference_version", encoded)

    def test_all_outputs_are_json_serializable_and_versioned(self) -> None:
        for experiment_id in [f"E{index:02d}" for index in range(1, 9)]:
            result = reference_output(experiment_id)
            self.assertEqual(result["reference_version"], REFERENCE_VERSION)
            json.dumps(result, allow_nan=False, sort_keys=True)


if __name__ == "__main__":
    unittest.main()
