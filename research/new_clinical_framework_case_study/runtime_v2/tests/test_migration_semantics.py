from __future__ import annotations

import copy
import unittest

from runtime_v2 import RuntimeV2, digest, import_legacy_v1_state, migrate_v2_state
from runtime_v2.tests.test_runtime_v2 import (
    action_event,
    activation_marginals,
    model_dict,
    observation,
)


def identity_migration(source: RuntimeV2, target: RuntimeV2, migration_id: str) -> dict:
    return {
        "migration_id": migration_id,
        "from_model_digest": source.model_digest,
        "to_model_digest": target.model_digest,
        "process_map": {pid: pid for pid in source.process_ids},
        "coordinate_maps": {
            pid: {
                row["coordinate_id"]: row["coordinate_id"]
                for row in source.processes[pid]["coordinates"]
            }
            for pid in source.process_ids
        },
        "mode_maps": {
            pid: {
                row["mode_id"]: row["mode_id"]
                for row in source.processes[pid]["modes"]
            }
            for pid in source.process_ids
        },
        "stratum_maps": {
            pid: {
                row["stratum_id"]: row["stratum_id"]
                for row in (
                    source.processes[pid].get("strata")
                    or [{"stratum_id": f"stratum:{pid}"}]
                )
            }
            for pid in source.process_ids
        },
        "action_map": {action_id: action_id for action_id in source.actions},
    }


class MigrationSemanticClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source_spec = model_dict()
        self.source = RuntimeV2(self.source_spec)
        self.target_spec = copy.deepcopy(self.source_spec)
        self.target_spec["model_id"] = "neutral-migration-semantic-target"
        self.target = RuntimeV2(self.target_spec)
        self.migration = identity_migration(self.source, self.target, "semantic-migration-v1")

    def test_source_model_spec_must_match_source_wire_lineage(self) -> None:
        state = self.source.initialize([observation("source-observation", "OBS_A_MARKER", True)], cut=0)
        impostor_spec = copy.deepcopy(self.source_spec)
        impostor_spec["model_id"] = "impostor-source-model"
        with self.assertRaisesRegex(ValueError, "source_model_spec digest"):
            migrate_v2_state(state, impostor_spec, self.target, self.migration)

    def test_factor_provenance_and_same_source_exact_once_survive_migration(self) -> None:
        original = observation(
            "original-rendering",
            "OBS_A_MARKER",
            True,
            source_id="PUBLIC-SOURCE-A",
        )
        state = self.source.initialize([original], cut=0)
        migrated = migrate_v2_state(
            state, self.source_spec, self.target, self.migration
        )

        before_wire = state.to_dict()["factor_graph_state"]
        migrated_wire = migrated.to_dict()["factor_graph_state"]
        self.assertEqual(
            migrated_wire["factor_messages"], before_wire["factor_messages"]
        )
        self.assertEqual(migrated_wire["recognized_result_ids"], ["PUBLIC-SOURCE-A"])
        for process_id, probability in activation_marginals(state).items():
            self.assertAlmostEqual(
                activation_marginals(migrated)[process_id], probability
            )

        alternate_rendering = observation(
            "alternate-transport-event",
            "OBS_A_MARKER",
            True,
            source_id="PUBLIC-SOURCE-A",
        )
        replayed = self.target.update(migrated, [alternate_rendering], advance_to=0)
        self.assertIs(replayed, migrated)
        self.assertEqual(
            replayed.to_dict()["factor_graph_state"]["factor_messages"],
            migrated_wire["factor_messages"],
        )
        self.assertEqual(
            replayed.to_dict()["event_lineage"]["processed_event_ids"],
            migrated.to_dict()["event_lineage"]["processed_event_ids"],
        )

    def test_mode_action_response_and_history_lineage_survive_migration(self) -> None:
        state = self.source.initialize(
            [
                action_event("migration-action-start", "ActionStarted", at=0, dose=1.0),
                observation("migration-baseline", "OBS_A_LOAD", 0.8, at=0),
            ],
            cut=0,
        )
        state = self.source.update(
            state,
            [
                observation("migration-direction", "OBS_A_DIRECTION", "falling", at=1),
                observation("migration-response", "OBS_A_LOAD", 0.1, at=1),
            ],
            advance_to=1,
        )
        before = state.to_dict()["history_summary"]
        self.assertTrue(before["mode_transitions"])
        self.assertTrue(before["action_response_windows"])

        migrated = migrate_v2_state(
            state, self.source_spec, self.target, self.migration
        )
        self.assertEqual(migrated.to_dict()["as_of"]["cut_id"], "cut:1.0")
        self.assertIsNone(migrated.to_dict()["as_of"]["clock_time"])
        after = migrated.to_dict()["history_summary"]
        self.assertEqual(after["mode_transitions"], before["mode_transitions"])
        self.assertEqual(
            after["action_response_windows"], before["action_response_windows"]
        )
        self.assertEqual(after["trajectory_features"], before["trajectory_features"])
        self.assertEqual(after["retained_event_ids"], before["retained_event_ids"])
        # A migrated public wire must already be canonically consumable; this
        # would fail if epistemic or identifiability claims were copied rather
        # than re-derived under the target model.
        self.target.diagnose(migrated)
        self.target.forecast(migrated, horizon=1)

    def test_incomplete_local_maps_fail_instead_of_resetting_operable_state(self) -> None:
        state = self.source.initialize(
            [observation("coordinate-load", "OBS_A_LOAD", 0.9)], cut=0
        )
        missing_coordinate = copy.deepcopy(self.migration)
        missing_coordinate["coordinate_maps"]["PROCESS_A"] = {}
        with self.assertRaisesRegex(ValueError, "coordinate map must account"):
            migrate_v2_state(
                state, self.source_spec, self.target, missing_coordinate
            )

        missing_mode = copy.deepcopy(self.migration)
        missing_mode["mode_maps"]["PROCESS_A"].pop("recovering")
        with self.assertRaisesRegex(ValueError, "mode map must account"):
            migrate_v2_state(state, self.source_spec, self.target, missing_mode)

    def test_stratum_posterior_is_migrated_instead_of_reset_to_target_prior(self) -> None:
        source_spec = model_dict()
        process_a = next(
            row for row in source_spec["processes"] if row["process_id"] == "PROCESS_A"
        )
        process_a["strata"] = [
            {"stratum_id": "stratum:PROCESS_A:S1", "prior": 0.5},
            {"stratum_id": "stratum:PROCESS_A:S2", "prior": 0.5},
        ]
        source_spec["observations"].append(
            {
                "concept_id": "OBS_A_STRATUM",
                "factor_id": "FACTOR_A_STRATUM",
                "reliability": 1.0,
                "emissions": [
                    {
                        "process_id": "PROCESS_A",
                        "active_likelihood": {"family": "bernoulli", "p_true": 0.5},
                        "inactive_likelihood": {"family": "bernoulli", "p_true": 0.5},
                        "stratum_likelihoods": {
                            "stratum:PROCESS_A:S1": {"family": "bernoulli", "p_true": 0.9},
                            "stratum:PROCESS_A:S2": {"family": "bernoulli", "p_true": 0.1},
                        },
                    }
                ],
            }
        )
        source = RuntimeV2(source_spec)
        state = source.initialize(
            [observation("stratum-evidence", "OBS_A_STRATUM", True)], cut=0
        )
        before = source.diagnose(state)["local_stratum_posteriors"]["PROCESS_A"]
        self.assertGreater(before["stratum:PROCESS_A:S1"], 0.85)

        target_spec = copy.deepcopy(source_spec)
        target_spec["model_id"] = "stratum-preserving-target"
        target = RuntimeV2(target_spec)
        migration = identity_migration(source, target, "stratum-preserving-v1")
        migrated = migrate_v2_state(state, source_spec, target, migration)
        after = target.diagnose(migrated)["local_stratum_posteriors"]["PROCESS_A"]
        for stratum_id, probability in before.items():
            self.assertAlmostEqual(after[stratum_id], probability)
        policy = {
            "policy_id": "EXISTING-ACTION",
            "start_actions": [{"action_id": "ACTION_REDUCE_A", "dose": 1.0}],
        }
        self.assertAlmostEqual(
            source.rollout(state, policy, horizon=1)["expected_coordinate_burden"],
            target.rollout(migrated, policy, horizon=1)["expected_coordinate_burden"],
        )

    def test_mode_transition_history_is_remapped_and_referentially_valid(self) -> None:
        state = self.source.initialize(
            [
                observation("transition-load", "OBS_A_LOAD", 0.9, at=0),
                observation("transition-direction", "OBS_A_DIRECTION", "falling", at=0),
            ],
            cut=0,
        )
        transitions = state.to_dict()["history_summary"]["mode_transitions"]
        self.assertTrue(transitions)
        self.assertTrue(
            any(row["to_mode_id"] == "recovering" for row in transitions)
        )

        target_spec = copy.deepcopy(self.source_spec)
        target_spec["model_id"] = "renamed-mode-target"
        process_a = next(
            row for row in target_spec["processes"] if row["process_id"] == "PROCESS_A"
        )
        for mode in process_a["modes"]:
            if mode["mode_id"] == "recovering":
                mode["mode_id"] = "healing"
        for guard in process_a.get("mode_guards", []):
            if guard.get("source_mode_id") == "recovering":
                guard["source_mode_id"] = "healing"
            if guard.get("target_mode_id") == "recovering":
                guard["target_mode_id"] = "healing"
        for observation_row in target_spec["observations"]:
            for emission in observation_row.get("emissions", []):
                if emission["process_id"] != "PROCESS_A":
                    continue
                mode_likelihoods = emission.get("mode_likelihoods", {})
                if "recovering" in mode_likelihoods:
                    mode_likelihoods["healing"] = mode_likelihoods.pop("recovering")
        for coupling in target_spec.get("mode_couplings", []):
            if coupling.get("source_process_id") == "PROCESS_A" and coupling.get("source_mode_id") == "recovering":
                coupling["source_mode_id"] = "healing"
            if coupling.get("target_process_id") == "PROCESS_A" and coupling.get("target_mode_id") == "recovering":
                coupling["target_mode_id"] = "healing"
        target = RuntimeV2(target_spec)
        migration = identity_migration(self.source, target, "mode-rename-v1")
        migration["mode_maps"]["PROCESS_A"]["recovering"] = "healing"
        migrated = migrate_v2_state(state, self.source_spec, target, migration)
        after = migrated.to_dict()["history_summary"]["mode_transitions"]
        self.assertFalse(any(row["to_mode_id"] == "recovering" for row in after))
        self.assertTrue(any(row["to_mode_id"] == "healing" for row in after))
        target.diagnose(migrated)

    def test_legacy_import_normalizes_parent_digest_and_exposes_loss_warning(self) -> None:
        legacy = {
            "available_cut": 0,
            "model_digest": "legacy-model-digest",
            "branch_posterior": {"PROCESS_A": 0.7, "PROCESS_B": 0.2, "PROCESS_C": 0.1},
            "unknown_mass": 0.1,
            "recognized_observation_count": 2,
            "unrecognized_observation_count": 1,
        }
        migration = {
            "migration_id": "legacy-semantic-closure-v1",
            "process_map": {pid: pid for pid in self.target.process_ids},
            "coordinate_maps": {},
            "mode_maps": {},
            "action_map": {},
        }
        migrated = import_legacy_v1_state(legacy, self.target, migration)
        wire = migrated.to_dict()
        self.assertRegex(wire["model_lineage"]["parent_model_digest"], r"^[0-9a-f]{64}$")
        self.assertIn(
            "legacy-migration-information-loss",
            {
                row["information_id"]
                for row in wire["epistemic_residual"]["missing_distinguishing_information"]
            },
        )
        self.target.diagnose(migrated)

    def test_migration_accepts_exact_nondefault_source_runtime_preimage(self) -> None:
        source = RuntimeV2(self.source_spec, topology_enabled=False)
        state = source.initialize(
            [observation("nondefault-runtime-evidence", "OBS_A_MARKER", True)],
            cut=0,
        )
        target_spec = copy.deepcopy(self.source_spec)
        target_spec["model_id"] = "nondefault-runtime-target"
        target = RuntimeV2(target_spec, topology_enabled=False)
        migration = identity_migration(source, target, "exact-runtime-preimage-v1")
        migrated = migrate_v2_state(state, source, target, migration)
        for pid, probability in activation_marginals(state).items():
            self.assertAlmostEqual(
                activation_marginals(migrated)[pid], probability
            )
        target.diagnose(migrated)

    def test_historical_factor_semantic_change_requires_validated_transport(self) -> None:
        state = self.source.initialize(
            [observation("semantic-factor-evidence", "OBS_A_MARKER", True)], cut=0
        )
        target_spec = copy.deepcopy(self.source_spec)
        target_spec["model_id"] = "reversed-factor-target"
        observation_row = next(
            row for row in target_spec["observations"] if row["concept_id"] == "OBS_A_MARKER"
        )
        emission = next(
            row for row in observation_row["emissions"] if row["process_id"] == "PROCESS_A"
        )
        emission["active_likelihood"], emission["inactive_likelihood"] = (
            emission["inactive_likelihood"],
            emission["active_likelihood"],
        )
        target = RuntimeV2(target_spec)
        migration = identity_migration(self.source, target, "semantic-change-v1")
        with self.assertRaisesRegex(ValueError, "historical factor semantics changed"):
            migrate_v2_state(state, self.source_spec, target, migration)

    def test_factor_rename_remaps_historical_messages(self) -> None:
        state = self.source.initialize(
            [observation("renamed-factor-evidence", "OBS_A_MARKER", True)], cut=0
        )
        source_factor_id = next(
            row["factor_id"]
            for row in self.source_spec["observations"]
            if row["concept_id"] == "OBS_A_MARKER"
        )
        target_factor_id = source_factor_id + ":RENAMED"
        target_spec = copy.deepcopy(self.source_spec)
        target_spec["model_id"] = "renamed-factor-target"
        next(
            row for row in target_spec["observations"] if row["concept_id"] == "OBS_A_MARKER"
        )["factor_id"] = target_factor_id
        target = RuntimeV2(target_spec)
        migration = identity_migration(self.source, target, "factor-rename-v1")
        migration["factor_map"] = {source_factor_id: target_factor_id}
        migrated = migrate_v2_state(state, self.source_spec, target, migration)
        factor_ids = {
            row["factor_id"]
            for row in migrated.to_dict()["factor_graph_state"]["factor_messages"]
        }
        self.assertIn(target_factor_id, factor_ids)
        self.assertNotIn(source_factor_id, factor_ids)
        target.diagnose(migrated)

    def test_factor_rename_remaps_mode_transition_emission_guard_ids(self) -> None:
        state = self.source.initialize(
            [
                observation("factor-rename-transition-load", "OBS_A_LOAD", 0.9),
                observation(
                    "factor-rename-transition-direction",
                    "OBS_A_DIRECTION",
                    "falling",
                ),
            ],
            cut=0,
        )
        before = state.to_dict()["history_summary"]["mode_transitions"]
        self.assertTrue(before)
        source_factor_id = next(
            row["factor_id"]
            for row in self.source_spec["observations"]
            if row["concept_id"] == "OBS_A_DIRECTION"
        )
        self.assertIn(f"emission:{source_factor_id}", before[0]["guard_ids"])

        target_factor_id = source_factor_id + ":RENAMED"
        target_spec = copy.deepcopy(self.source_spec)
        target_spec["model_id"] = "renamed-transition-factor-target"
        next(
            row
            for row in target_spec["observations"]
            if row["concept_id"] == "OBS_A_DIRECTION"
        )["factor_id"] = target_factor_id
        target = RuntimeV2(target_spec)
        migration = identity_migration(
            self.source, target, "transition-factor-rename-v1"
        )
        migration["factor_map"] = {source_factor_id: target_factor_id}
        migrated = migrate_v2_state(state, self.source_spec, target, migration)
        after = migrated.to_dict()["history_summary"]["mode_transitions"]
        self.assertIn(f"emission:{target_factor_id}", after[0]["guard_ids"])
        self.assertNotIn(f"emission:{source_factor_id}", after[0]["guard_ids"])
        target.diagnose(migrated)

    def test_many_to_one_process_migration_requires_explicit_merge_kernel(self) -> None:
        state = self.source.initialize([], cut=0)
        target_spec = copy.deepcopy(self.source_spec)
        target_spec["model_id"] = "many-to-one-target"
        target = RuntimeV2(target_spec)
        migration = identity_migration(self.source, target, "many-to-one-v1")
        migration["process_map"]["PROCESS_B"] = "PROCESS_A"
        with self.assertRaisesRegex(ValueError, "explicit typed merge kernel"):
            migrate_v2_state(state, self.source_spec, target, migration)

    def test_active_action_migration_rejects_unit_change_without_explicit_dose_conversion(self) -> None:
        source_spec = copy.deepcopy(self.source_spec)
        source_action = next(
            row for row in source_spec["actions"] if row["action_id"] == "ACTION_REDUCE_A"
        )
        source_action["dose_unit"] = "mg"
        source = RuntimeV2(source_spec)
        state = source.initialize(
            [
                action_event(
                    "active-mg-action",
                    "ActionStarted",
                    at=0,
                    dose=1.0,
                    dose_unit="mg",
                )
            ],
            cut=0,
        )

        target_spec = copy.deepcopy(source_spec)
        target_spec["model_id"] = "action-unit-mcg-target"
        next(
            row for row in target_spec["actions"] if row["action_id"] == "ACTION_REDUCE_A"
        )["dose_unit"] = "mcg"
        target = RuntimeV2(target_spec)
        migration = identity_migration(source, target, "action-unit-change-v1")
        with self.assertRaisesRegex(ValueError, "explicit typed action transport"):
            migrate_v2_state(state, source, target, migration)

    def test_linear_action_dose_transport_converts_operative_state_and_is_digest_bound(self) -> None:
        source_spec = copy.deepcopy(self.source_spec)
        source_action = next(
            row for row in source_spec["actions"] if row["action_id"] == "ACTION_REDUCE_A"
        )
        source_action["dose_unit"] = "mg"
        source = RuntimeV2(source_spec)
        state = source.initialize(
            [
                action_event(
                    "active-mg-action-for-conversion",
                    "ActionStarted",
                    at=0,
                    dose=1.0,
                    dose_unit="mg",
                )
            ],
            cut=0,
        )

        target_spec = copy.deepcopy(source_spec)
        target_spec["model_id"] = "action-unit-converted-target"
        target_action = next(
            row for row in target_spec["actions"] if row["action_id"] == "ACTION_REDUCE_A"
        )
        target_action["dose_unit"] = "mcg"
        target_action["dose_reference"] = 1000.0
        target = RuntimeV2(target_spec)
        migration = identity_migration(source, target, "action-unit-conversion-v1")
        migration["action_transports"] = {
            "ACTION_REDUCE_A": {
                "transport_type": "linear_dose_unit_conversion",
                "target_action_id": "ACTION_REDUCE_A",
                "source_action_digest": digest(source.actions["ACTION_REDUCE_A"]),
                "target_action_digest": digest(target.actions["ACTION_REDUCE_A"]),
                "source_dose_unit": "mg",
                "target_dose_unit": "mcg",
                "dose_multiplier": 1000.0,
                "validation_artifact_digest": "a" * 64,
            }
        }
        migrated = migrate_v2_state(state, source, target, migration)
        active_instance = next(
            row
            for row in migrated.to_dict()["action_memory"]["instances"]
            if row["status"] == "active"
        )
        self.assertEqual(active_instance["dose_history"][-1]["unit"], "mcg")
        self.assertEqual(active_instance["dose_history"][-1]["value"], 1000.0)
        source_forecast = source.forecast(state, horizon=1)
        target_forecast = target.forecast(migrated, horizon=1)
        self.assertAlmostEqual(
            source_forecast["expected_coordinate_burden"],
            target_forecast["expected_coordinate_burden"],
        )


if __name__ == "__main__":
    unittest.main()
