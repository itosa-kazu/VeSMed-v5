from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from runtime_v2 import RuntimeV2, evaluate_behavioral_collision, execute_local_refinement
from runtime_v2.refinement import _old_scope_projection
from runtime_v2.schema import validate_migration_spec
from runtime_v2.tests.test_runtime_v2 import (
    CollisionAndRefinementTests,
    model_dict,
    observation,
)


class RefinementSemanticTests(unittest.TestCase):
    def fixture(self) -> CollisionAndRefinementTests:
        fixture = CollisionAndRefinementTests(methodName="runTest")
        fixture.setUp()
        return fixture

    def test_same_sign_responses_can_collide_when_optimal_safe_actions_are_incompatible(self) -> None:
        collision = evaluate_behavioral_collision(
            [
                {
                    "world_id": "NEW_BEST",
                    "old_state": {"same": True},
                    "action_outcomes": {"OLD": 1.0, "NEW": 3.0},
                },
                {
                    "world_id": "OLD_BEST",
                    "old_state": {"same": True},
                    "action_outcomes": {"OLD": 1.0, "NEW": 0.5},
                },
            ],
            old_action_ids=["OLD"],
            new_action_id="NEW",
        )
        self.assertEqual(collision["status"], "COLLISION_WITNESS")
        witness = collision["witnesses"][0]
        self.assertEqual(witness["response_relation"], "SAME_SIGN")
        self.assertEqual(
            witness["collision_basis"], "INCOMPATIBLE_OPTIMAL_SAFE_ACTIONS"
        )

    def test_value_difference_without_incompatible_optimal_action_is_not_collision(self) -> None:
        collision = evaluate_behavioral_collision(
            [
                {
                    "world_id": "W1",
                    "old_state": {"same": True},
                    "action_outcomes": {"OLD": 1.0, "NEW": 3.0},
                },
                {
                    "world_id": "W2",
                    "old_state": {"same": True},
                    "action_outcomes": {"OLD": 1.0, "NEW": 2.0},
                },
            ],
            old_action_ids=["OLD"],
            new_action_id="NEW",
        )
        self.assertEqual(collision["status"], "NO_COLLISION")

    def test_old_scope_projection_masks_only_affected_local_stratum(self) -> None:
        projected = _old_scope_projection(
            {
                "local_stratum_posteriors": {
                    "PROCESS_A": {"A1": 0.9, "A2": 0.1},
                    "PROCESS_B": {"B1": 0.8, "B2": 0.2},
                }
            },
            affected_process_id="PROCESS_A",
        )
        self.assertNotIn("PROCESS_A", projected["local_stratum_posteriors"])
        self.assertEqual(
            projected["local_stratum_posteriors"]["PROCESS_B"],
            {"B1": 0.8, "B2": 0.2},
        )

    def test_refinement_registers_new_action_and_builds_nonzero_stratum_geometry(self) -> None:
        fixture = self.fixture()
        state = fixture.runtime.initialize(
            [observation("pre-refine-geometry", "OBS_B_MARKER", True)], cut=0
        )
        execution = execute_local_refinement(
            state,
            fixture.spec,
            fixture.collision,
            fixture.refinement,
            separating_event=observation(
                "separator-geometry", "OBS_RESPONSE_SEPARATOR", True, at=1
            ),
            migration_id="local-stratum-geometry-v1",
        )
        positive = "stratum:PROCESS_A:positive-response"
        negative = "stratum:PROCESS_A:negative-response"
        self.assertNotIn("NEW_ACTION", fixture.runtime.actions)
        self.assertIn("NEW_ACTION", execution.runtime.actions)
        self.assertFalse(
            execution.report["action_scope_extension"]["was_previously_registered"]
        )
        self.assertTrue(
            execution.report["migration_contract"]["schema_validated"]
        )
        generated_migration = execution.report["migration_contract"]["migration_spec"]
        self.assertEqual(validate_migration_spec(generated_migration), generated_migration)
        schema = json.loads(
            (Path(__file__).parents[1] / "schemas" / "migration_v2.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertTrue(set(schema["required"]).issubset(generated_migration))
        self.assertTrue(set(generated_migration).issubset(schema["properties"]))
        self.assertNotEqual(
            execution.report["action_scope_extension"]["source_action_catalog_digest"],
            execution.report["action_scope_extension"]["target_action_catalog_digest"],
        )
        self.assertGreater(execution.runtime.stratum_distance(positive, negative), 0.0)
        self.assertNotEqual(
            state.to_dict()["geometry_state"]["geometry_digest"],
            execution.migrated_state.to_dict()["geometry_state"]["geometry_digest"],
        )
        migrated_strata = execution.runtime.diagnose(execution.migrated_state)[
            "local_stratum_posteriors"
        ]["PROCESS_A"]
        self.assertAlmostEqual(migrated_strata[positive], 0.5)
        self.assertAlmostEqual(migrated_strata[negative], 0.5)
        geometry = execution.refined_state.to_dict()["geometry_state"]
        child_neighbors = [
            row
            for row in geometry["nearest_behavioral_neighbors"]
            if positive in row["reference_state_id"]
            and negative in row["reference_state_id"]
        ]
        self.assertTrue(child_neighbors)
        self.assertIn("NEW_ACTION", child_neighbors[0]["policy_witness_ids"])
        rollout = execution.runtime.rollout(
            execution.refined_state,
            {
                "policy_id": "NEW-ACTION-ROLLOUT",
                "start_actions": [{"action_id": "NEW_ACTION", "dose": 1.0}],
            },
            horizon=1,
        )
        self.assertTrue(rollout["action_stratum_modifier_trace"])

    def test_rollout_uses_stratum_distance_for_missing_local_modifier(self) -> None:
        fixture = self.fixture()
        state = fixture.runtime.initialize([], cut=0)
        execution = execute_local_refinement(
            state,
            fixture.spec,
            fixture.collision,
            fixture.refinement,
            separating_event=observation(
                "separator-for-planning-distance",
                "OBS_RESPONSE_SEPARATOR",
                False,
                at=1,
            ),
            migration_id="planning-distance-base-v1",
        )
        spec = copy.deepcopy(execution.runtime.spec)
        spec["model_id"] = "planning-distance-operative-model"
        process_a = next(
            row for row in spec["processes"] if row["process_id"] == "PROCESS_A"
        )
        positive = next(
            row
            for row in process_a["strata"]
            if row["stratum_id"] == "stratum:PROCESS_A:positive-response"
        )
        negative = next(
            row
            for row in process_a["strata"]
            if row["stratum_id"] == "stratum:PROCESS_A:negative-response"
        )
        positive["action_effect_modifiers"]["NEW_ACTION"] = 2.0
        negative["action_effect_modifiers"].pop("NEW_ACTION")
        runtime = RuntimeV2(spec)
        state = runtime.initialize(
            [
                observation(
                    "negative-stratum-evidence",
                    "OBS_RESPONSE_SEPARATOR",
                    False,
                    at=0,
                )
            ],
            cut=0,
        )
        rollout = runtime.rollout(
            state,
            {
                "policy_id": "GEOMETRY-INTERPOLATED-ACTION",
                "start_actions": [{"action_id": "NEW_ACTION", "dose": 1.0}],
            },
            horizon=1,
        )
        components = rollout["action_stratum_modifier_trace"][0][
            "stratum_components"
        ]
        negative_component = next(
            row
            for row in components
            if row["stratum_id"] == "stratum:PROCESS_A:negative-response"
        )
        self.assertEqual(
            negative_component["geometry_witness_stratum_id"],
            "stratum:PROCESS_A:positive-response",
        )
        self.assertGreater(negative_component["geometry_distance"], 0.0)
        self.assertGreater(negative_component["resolved_modifier"], 1.0)
        self.assertLess(negative_component["resolved_modifier"], 2.0)


if __name__ == "__main__":
    unittest.main()
