from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from runtime_v2 import RuntimeV2


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "examples" / "neutral_factorial_model.json"


def model_dict() -> dict:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def dynamic_transition(enter: float, withdraw: float) -> dict:
    return {
        "enter_hazard_per_step": enter,
        "withdraw_hazard_per_step": withdraw,
        "entry_initialization": {"policy": "RESET_TO_PRIOR"},
        "exit_policy": {"policy": "SURVIVOR_CARRY_REENTRY_RESET"},
        "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
        "source_id": "conditional-active-factorization-test",
        "version": "1",
    }


class ConditionalActiveFactorizationTests(unittest.TestCase):
    def test_own_action_is_not_activation_weighted_twice_ranking_flip(self) -> None:
        """p=.5,x=.4,d=-.2,cost=.075 must prefer action (.175 < .2)."""

        spec = model_dict()
        for process in spec["processes"]:
            for coordinate in process["coordinates"]:
                coordinate["objective_weight"] = 0.0
            for mode in process["modes"]:
                mode["coordinate_drift"] = {
                    coordinate_id: 0.0
                    for coordinate_id in mode["coordinate_drift"]
                }
        process_a = next(
            row for row in spec["processes"] if row["process_id"] == "PROCESS_A"
        )
        process_a["activation_prior"] = 0.5
        process_a["coordinates"][0]["prior_mean"] = 0.4
        process_a["coordinates"][0]["objective_weight"] = 1.0
        process_a["activation_transition"] = dynamic_transition(0.1, 0.1)
        spec["coactivation_interactions"] = []
        spec["process_couplings"] = []
        spec["mode_couplings"] = []
        spec["topology"]["inference_coupling"] = 0.0
        spec["topology"]["planning_coupling"] = 0.0
        action = spec["actions"][0]
        action["action_cost"] = 0.075
        action["effects"] = [
            {
                "process_id": "PROCESS_A",
                "coordinate_id": "a_burden",
                "delta_per_unit_step": -0.2,
            }
        ]

        runtime = RuntimeV2(spec)
        state = runtime.initialize([], cut=0)
        no_action = runtime.forecast(state, horizon=1)
        with_action = runtime.rollout(
            state,
            {
                "policy_id": "ACT",
                "start_actions": [
                    {"action_id": "ACTION_REDUCE_A", "dose": 1.0}
                ],
            },
            horizon=1,
        )

        self.assertAlmostEqual(no_action["total_objective"], 0.2, places=10)
        self.assertAlmostEqual(with_action["total_objective"], 0.175, places=10)
        self.assertLess(with_action["total_objective"], no_action["total_objective"])
        self.assertAlmostEqual(
            with_action["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"],
            0.2,
            places=10,
        )

    def test_conditional_coactivation_preserves_joint_dependence(self) -> None:
        runtime = RuntimeV2(model_dict())
        perfect = [
            {
                "active_processes": ["PROCESS_A", "PROCESS_B"],
                "unknown_active": False,
                "probability": 0.5,
            },
            {
                "active_processes": [],
                "unknown_active": False,
                "probability": 0.5,
            },
        ]
        exclusive = [
            {
                "active_processes": ["PROCESS_A"],
                "unknown_active": False,
                "probability": 0.5,
            },
            {
                "active_processes": ["PROCESS_B"],
                "unknown_active": False,
                "probability": 0.5,
            },
        ]
        self.assertEqual(
            runtime._conditional_coactivation_weight(
                perfect, "PROCESS_A", "PROCESS_B", target_marginal=0.5
            ),
            1.0,
        )
        self.assertEqual(
            runtime._conditional_coactivation_weight(
                exclusive, "PROCESS_A", "PROCESS_B", target_marginal=0.5
            ),
            0.0,
        )

    def test_process_and_planning_couplings_report_joint_conditional_weight(self) -> None:
        runtime = RuntimeV2(model_dict())
        state = runtime.initialize([], cut=0)
        internal_joint = [
            {
                "active_processes": [
                    pid
                    for pid in row["active_process_ids"]
                    if pid in runtime.process_ids
                ],
                "unknown_active": "NCF_UNMODELED_PROCESS"
                in row["active_process_ids"],
                "probability": row["probability"],
            }
            for row in state.to_dict()["active_process_posterior"]["joint_hypotheses"]
        ]
        p_b = next(
            row["p_active"]
            for row in state.to_dict()["active_process_posterior"]["process_marginals"]
            if row["process_id"] == "PROCESS_B"
        )
        expected_conditional = runtime._conditional_coactivation_weight(
            internal_joint, "PROCESS_A", "PROCESS_B", target_marginal=p_b
        )

        natural = runtime.forecast(state, horizon=1)
        coupling = natural["process_coupling_trace"][0]
        self.assertAlmostEqual(
            coupling["conditional_coactivation"], expected_conditional, places=12
        )
        self.assertAlmostEqual(
            coupling["delta"],
            0.02 * 0.2 * expected_conditional,
            places=12,
        )

        treated = runtime.rollout(
            state,
            {
                "policy_id": "ACT",
                "start_actions": [
                    {"action_id": "ACTION_REDUCE_A", "dose": 1.0}
                ],
            },
            horizon=1,
        )
        bridge = treated["topology_effect_trace"][0]
        self.assertAlmostEqual(
            bridge["conditional_coactivation"], expected_conditional, places=12
        )
        direct_delta = -0.25
        self.assertAlmostEqual(
            bridge["delta"],
            direct_delta * bridge["weight"] * expected_conditional,
            places=12,
        )

    def test_wire_and_query_reports_disclose_factorization(self) -> None:
        runtime = RuntimeV2(model_dict())
        state = runtime.initialize([], cut=0)
        wire = state.to_dict()
        contract = runtime.spec["posterior_factorization"]

        self.assertEqual(
            wire["active_process_posterior"]["representation"],
            "hybrid_approximation",
        )
        missing_ids = {
            row["information_id"]
            for row in wire["epistemic_residual"][
                "missing_distinguishing_information"
            ]
        }
        self.assertIn("factorization:unsupported-correlations", missing_ids)
        self.assertEqual(
            wire["epistemic_residual"]["abstention_status"],
            "partial_answer_only",
        )
        for claim in wire["identifiability_claims"]:
            self.assertTrue(
                set(contract["assumption_ids"]).issubset(claim["assumption_ids"])
            )

        diagnosis = runtime.diagnose(state)
        self.assertEqual(diagnosis["posterior_factorization"], contract)
        self.assertIn("mean_field", diagnosis["inference_kind"])
        forecast = runtime.forecast(state, horizon=1)
        self.assertEqual(forecast["posterior_factorization"], contract)
        self.assertIn("OUT_OF_SCOPE", forecast["factorization_limitation"])

    def test_factorization_contract_is_digest_bound(self) -> None:
        first = model_dict()
        second = copy.deepcopy(first)
        second["posterior_factorization"]["assumption_ids"].append(
            "additional-declared-assumption"
        )
        self.assertNotEqual(RuntimeV2(first).model_digest, RuntimeV2(second).model_digest)


if __name__ == "__main__":
    unittest.main()
