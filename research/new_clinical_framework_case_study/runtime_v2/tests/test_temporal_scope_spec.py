from __future__ import annotations

import copy
import json
import math
import time
import unittest
from pathlib import Path

from runtime_v2 import PublicEvent, RuntimeV2


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "examples" / "neutral_factorial_model.json"


def model_dict() -> dict:
    return json.loads(MODEL_PATH.read_text(encoding="utf-8"))


def local_state_map(state) -> dict:
    return {row["process_id"]: row for row in state.to_dict()["local_states"]}


def started_action() -> PublicEvent:
    return PublicEvent.from_dict(
        {
            "event_id": "start-a",
            "event_type": "ActionStarted",
            "available_at": 0,
            "recorded_at": 0,
            "occurred_time": {"lower": 0, "upper": 0},
            "provenance": {"source_result_id": "start-a"},
            "action_id": "ACTION_REDUCE_A",
            "exposure_id": "exposure-a",
            "dose": 0.25,
        }
    )


class TemporalScopeAndSpecIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RuntimeV2(model_dict())

    def test_clock_only_update_advances_same_natural_dynamics_as_forecast(self) -> None:
        baseline = self.runtime.initialize([], cut=0)
        predicted = self.runtime.forecast(baseline, horizon=2)

        advanced = self.runtime.update(baseline, [], advance_to=2)
        actual = local_state_map(advanced)

        for process_id, coordinates in predicted["final_coordinates"].items():
            observed_coordinates = {
                row["coordinate_id"]: row for row in actual[process_id]["coordinates"]
            }
            for coordinate_id, estimate in coordinates.items():
                self.assertAlmostEqual(
                    observed_coordinates[coordinate_id]["distribution"]["mean"],
                    estimate["mean"],
                )
        for process_id, probabilities in predicted["final_mode_posteriors"].items():
            observed_modes = {
                row["mode_id"]: row["probability"]
                for row in actual[process_id]["mode_posterior"]
            }
            self.assertEqual(set(observed_modes), set(probabilities))
            for mode_id, probability in probabilities.items():
                self.assertAlmostEqual(observed_modes[mode_id], probability)

        # Advancing in two one-step updates is the same transition semigroup.
        stepped = self.runtime.update(baseline, [], advance_to=1)
        stepped = self.runtime.update(stepped, [], advance_to=2)
        self.assertEqual(local_state_map(advanced), local_state_map(stepped))

    def test_invalid_horizon_fails_and_out_of_scope_returns_nonexecuted_envelope(self) -> None:
        state = self.runtime.initialize([], cut=0)
        policy = {"policy_id": "NO_NEW_ACTION", "start_actions": []}
        for invalid in (0, -1, math.nan, math.inf, -math.inf):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    self.runtime.forecast(state, horizon=invalid)
                with self.assertRaises(ValueError):
                    self.runtime.rollout(state, policy, horizon=invalid)
                with self.assertRaises(ValueError):
                    self.runtime.plan(state, [], horizon=invalid)

        declared = float(self.runtime.spec["scope"]["horizon"]["value"])
        for fractional in (0.1, 1.5):
            with self.assertRaisesRegex(ValueError, "whole number"):
                self.runtime.forecast(state, horizon=fractional)

        requested = declared + 1.0
        outside = self.runtime.forecast(state, horizon=requested)
        self.assertEqual(outside["status"], "OUT_OF_SCOPE")
        self.assertEqual(outside["execution_status"], "NOT_EXECUTED_OUT_OF_SCOPE")
        self.assertNotIn("trajectory", outside)
        self.assertNotIn("final_coordinates", outside)

        outside_rollout = self.runtime.rollout(state, policy, horizon=requested)
        self.assertEqual(outside_rollout["status"], "OUT_OF_SCOPE")
        self.assertNotIn("trajectory", outside_rollout)

        outside_plan = self.runtime.plan(state, [policy], horizon=requested)
        self.assertEqual(outside_plan["status"], "OUT_OF_SCOPE")
        self.assertIsNone(outside_plan["selected_policy_id"])
        self.assertEqual(outside_plan["excluded_policy_ids"], ["NO_NEW_ACTION"])
        self.assertNotIn("trajectory", outside_plan["policy_rollouts"][0])
        # The declared boundary itself remains admissible.
        self.assertEqual(len(self.runtime.forecast(state, horizon=declared)["trajectory"]), 5)

    def test_clock_only_update_includes_existing_action_dynamics(self) -> None:
        active = self.runtime.initialize([started_action()], cut=0)
        predicted = self.runtime.forecast(active, horizon=2)
        advanced = self.runtime.update(active, [], advance_to=2)
        actual = local_state_map(advanced)
        for process_id, coordinates in predicted["final_coordinates"].items():
            observed_coordinates = {
                row["coordinate_id"]: row for row in actual[process_id]["coordinates"]
            }
            for coordinate_id, estimate in coordinates.items():
                self.assertAlmostEqual(
                    observed_coordinates[coordinate_id]["distribution"]["mean"],
                    estimate["mean"],
                )

    def test_fractional_event_time_and_clock_update_use_scaled_final_step(self) -> None:
        baseline = self.runtime.initialize([], cut=0)
        half = self.runtime.update(baseline, [], advance_to=0.5)
        full = self.runtime.update(baseline, [], advance_to=1.0)
        half_states = local_state_map(half)
        full_states = local_state_map(full)
        base_states = local_state_map(baseline)
        saw_strict_partial = False
        for process_id in half_states:
            half_coordinates = {
                row["coordinate_id"]: row["distribution"]["mean"]
                for row in half_states[process_id]["coordinates"]
            }
            full_coordinates = {
                row["coordinate_id"]: row["distribution"]["mean"]
                for row in full_states[process_id]["coordinates"]
            }
            base_coordinates = {
                row["coordinate_id"]: row["distribution"]["mean"]
                for row in base_states[process_id]["coordinates"]
            }
            for coordinate_id in half_coordinates:
                low = min(base_coordinates[coordinate_id], full_coordinates[coordinate_id])
                high = max(base_coordinates[coordinate_id], full_coordinates[coordinate_id])
                self.assertGreaterEqual(half_coordinates[coordinate_id], low - 1e-12)
                self.assertLessEqual(half_coordinates[coordinate_id], high + 1e-12)
                saw_strict_partial = saw_strict_partial or (
                    abs(half_coordinates[coordinate_id] - base_coordinates[coordinate_id]) > 1e-12
                    and abs(half_coordinates[coordinate_id] - full_coordinates[coordinate_id]) > 1e-12
                )
        self.assertTrue(saw_strict_partial)

        # A legal fractional public availability cut is consumed without
        # pretending it is a full model step.
        event = PublicEvent.from_dict(
            {
                "event_id": "fractional-observation",
                "event_type": "ObservationAvailable",
                "available_at": 0.5,
                "recorded_at": 0.5,
                "occurred_time": {"lower": 0.5, "upper": 0.5},
                "sample_time": {"lower": 0.5, "upper": 0.5},
                "result_at": 0.5,
                "concept_id": "OBS_A_MARKER",
                "value": True,
                "provenance": {"source_result_id": "fractional-observation"},
            }
        )
        updated = self.runtime.update(baseline, [event], advance_to=0.5)
        self.assertIsNone(updated.to_dict()["as_of"]["clock_time"])
        self.assertEqual(updated.to_dict()["as_of"]["cut_id"], "cut:0.5")

    def test_caller_owned_spec_is_defensively_copied(self) -> None:
        supplied = model_dict()
        runtime = RuntimeV2(supplied)
        supplied["scope"]["horizon"]["value"] = 999
        state = runtime.initialize([], cut=0)
        self.assertEqual(state.to_dict()["scope"]["horizon"]["value"], 5.0)

    def test_post_construction_model_or_registry_mutation_fails_closed(self) -> None:
        state = self.runtime.initialize([], cut=0)

        self.runtime.spec["scope"]["horizon"]["value"] = 999
        with self.assertRaisesRegex(ValueError, "runtime model spec mutated"):
            self.runtime.forecast(state, horizon=1)
        with self.assertRaisesRegex(ValueError, "runtime model spec mutated"):
            self.runtime.initialize([], cut=0)

        runtime = RuntimeV2(model_dict())
        state = runtime.initialize([], cut=0)
        runtime.actions["ACTION_REDUCE_A"]["action_cost"] = 999
        with self.assertRaisesRegex(ValueError, "runtime model spec mutated"):
            runtime.forecast(state, horizon=1)

        runtime = RuntimeV2(model_dict())
        state = runtime.initialize([], cut=0)
        runtime.actions["FABRICATED_ACTION"] = copy.deepcopy(
            runtime.actions["ACTION_REDUCE_A"]
        )
        with self.assertRaisesRegex(ValueError, "runtime registries mutated"):
            runtime.forecast(state, horizon=1)

    def test_model_spec_rejects_nonfinite_and_illegal_numeric_domains_at_construction(self) -> None:
        def set_categorical_sum(spec: dict) -> None:
            observation = next(
                row for row in spec["observations"] if row["concept_id"] == "OBS_A_DIRECTION"
            )
            observation["emissions"][0]["active_likelihood"]["probabilities"] = {
                "falling": 0.8,
                "stable": 0.8,
                "rising": 0.8,
            }

        def set_gaussian_sd(spec: dict) -> None:
            observation = next(
                row for row in spec["observations"] if row["concept_id"] == "OBS_A_LOAD"
            )
            observation["emissions"][0]["active_likelihood"]["sd"] = math.inf

        mutations = [
            ("scope_horizon_nan", lambda spec: spec["scope"]["horizon"].__setitem__("value", math.nan)),
            ("scope_tolerance_inf", lambda spec: spec["scope"].__setitem__("tolerance", math.inf)),
            ("mode_prior_negative", lambda spec: spec["processes"][0]["modes"][0].__setitem__("prior", -0.1)),
            ("mode_prior_not_normalized", lambda spec: spec["processes"][0]["modes"][0].__setitem__("prior", 0.9)),
            ("coordinate_uncertainty_inf", lambda spec: spec["processes"][0]["coordinates"][0].__setitem__("prior_uncertainty", math.inf)),
            ("objective_weight_negative", lambda spec: spec["processes"][0]["coordinates"][0].__setitem__("objective_weight", -1.0)),
            ("mode_drift_inf", lambda spec: spec["processes"][0]["modes"][0]["coordinate_drift"].__setitem__("a_burden", math.inf)),
            ("categorical_not_normalized", set_categorical_sum),
            ("gaussian_sd_inf", set_gaussian_sd),
            ("topology_distance_inf", lambda spec: spec["topology"]["edges"][0].__setitem__("distance", math.inf)),
            ("topology_distance_scale_inf", lambda spec: spec["topology"].__setitem__("distance_scale", math.inf)),
            ("topology_coupling_nan", lambda spec: spec["topology"].__setitem__("planning_coupling", math.nan)),
            ("action_dose_reference_inf", lambda spec: spec["actions"][0].__setitem__("dose_reference", math.inf)),
            ("action_washout_nan", lambda spec: spec["actions"][0].__setitem__("washout_steps", math.nan)),
            ("action_cost_negative", lambda spec: spec["actions"][0].__setitem__("action_cost", -1.0)),
            ("action_effect_nan", lambda spec: spec["actions"][0]["effects"][0].__setitem__("delta_per_unit_step", math.nan)),
            ("action_status_invalid", lambda spec: spec["actions"][0].__setitem__("causal_status", "MAGIC")),
            ("process_coupling_inf", lambda spec: spec["process_couplings"][0].__setitem__("strength_per_step", math.inf)),
            ("mode_coupling_nan", lambda spec: spec["mode_couplings"][0].__setitem__("log_potential_per_step", math.nan)),
            ("coactivation_inf", lambda spec: spec["coactivation_interactions"][0].__setitem__("log_potential_when_coactive", math.inf)),
        ]
        for label, mutate in mutations:
            with self.subTest(label=label):
                spec = model_dict()
                mutate(spec)
                with self.assertRaises(ValueError):
                    RuntimeV2(spec)

    def test_joint_process_activation_enters_withdraws_and_responds_to_coupling_and_action(self) -> None:
        def transition(enter: float, withdraw: float) -> dict:
            return {
                "enter_hazard_per_step": enter,
                "withdraw_hazard_per_step": withdraw,
                "entry_initialization": {"policy": "RESET_TO_PRIOR"},
                "exit_policy": {"policy": "SURVIVOR_CARRY_REENTRY_RESET"},
                "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
                "source_id": "case-blind-structural-test",
                "version": "1",
            }

        base_spec = model_dict()
        for process in base_spec["processes"]:
            process["activation_transition"] = transition(0.0, 0.0)
        runtime = RuntimeV2(base_spec)
        state = runtime.initialize([], cut=0)
        frozen = runtime.forecast(state, horizon=1)

        evolving_spec = copy.deepcopy(base_spec)
        next(row for row in evolving_spec["processes"] if row["process_id"] == "PROCESS_A")[
            "activation_transition"
        ] = transition(0.0, 0.6)
        next(row for row in evolving_spec["processes"] if row["process_id"] == "PROCESS_C")[
            "activation_transition"
        ] = transition(0.08, 0.0)
        evolving = RuntimeV2(evolving_spec)
        evolving_state = evolving.initialize([], cut=0)
        natural = evolving.forecast(evolving_state, horizon=1)
        natural_activation = {
            row["process_id"]: row["p_active"]
            for row in natural["predictive_support"]["process_activation"]
        }
        frozen_activation = {
            row["process_id"]: row["p_active"]
            for row in frozen["predictive_support"]["process_activation"]
        }
        self.assertLess(natural_activation["PROCESS_A"], frozen_activation["PROCESS_A"])
        self.assertGreater(natural_activation["PROCESS_C"], frozen_activation["PROCESS_C"])
        self.assertAlmostEqual(
            sum(row["probability"] for row in natural["final_joint_hypotheses"]), 1.0
        )

        coupled_spec = copy.deepcopy(evolving_spec)
        coupled_spec["process_activation_couplings"] = [
            {
                "coupling_id": "A-activates-C",
                "source_process_id": "PROCESS_A",
                "target_process_id": "PROCESS_C",
                "enter_log_hazard_shift_per_step": 2.0,
                "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
                "source_id": "case-blind-structural-test",
                "version": "1",
            }
        ]
        coupled = RuntimeV2(coupled_spec)
        coupled_result = coupled.forecast(coupled.initialize([], cut=0), horizon=1)
        coupled_c = next(
            row["p_active"]
            for row in coupled_result["predictive_support"]["process_activation"]
            if row["process_id"] == "PROCESS_C"
        )
        self.assertGreater(coupled_c, natural_activation["PROCESS_C"])

        action_spec = copy.deepcopy(evolving_spec)
        action_spec["actions"][0]["activation_effects"] = [
            {
                "process_id": "PROCESS_C",
                "enter_log_hazard_shift_per_unit": 3.0,
                "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
                "source_id": "case-blind-structural-test",
                "version": "1",
            }
        ]
        action_runtime = RuntimeV2(action_spec)
        action_state = action_runtime.initialize([], cut=0)
        action_result = action_runtime.rollout(
            action_state,
            {
                "policy_id": "START_A",
                "start_actions": [{"action_id": "ACTION_REDUCE_A", "dose": 1.0}],
            },
            horizon=1,
        )
        action_c = next(
            row["p_active"]
            for row in action_result["predictive_support"]["process_activation"]
            if row["process_id"] == "PROCESS_C"
        )
        self.assertGreater(action_c, natural_activation["PROCESS_C"])

        # Factual clock advancement materializes exactly the propagated joint.
        advanced = evolving.update(evolving_state, [], advance_to=1)
        advanced_joint = advanced.to_dict()["active_process_posterior"]["joint_hypotheses"]
        self.assertAlmostEqual(sum(row["probability"] for row in advanced_joint), 1.0)
        advanced_marginals = {
            row["process_id"]: row["p_active"]
            for row in advanced.to_dict()["active_process_posterior"]["process_marginals"]
        }
        self.assertAlmostEqual(advanced_marginals["PROCESS_A"], natural_activation["PROCESS_A"])
        self.assertAlmostEqual(advanced_marginals["PROCESS_C"], natural_activation["PROCESS_C"])

        # A materialized dynamic belief is a valid authoritative current
        # state.  It must remain queryable and advanceable; the validator must
        # not incorrectly replay it as a static prior-plus-evidence posterior.
        continued_forecast = evolving.forecast(advanced, horizon=1)
        continued = evolving.update(advanced, [], advance_to=2)
        self.assertAlmostEqual(
            sum(
                row["probability"]
                for row in continued_forecast["final_joint_hypotheses"]
            ),
            1.0,
        )
        self.assertAlmostEqual(
            sum(
                row["probability"]
                for row in continued.to_dict()["active_process_posterior"]["joint_hypotheses"]
            ),
            1.0,
        )

    def test_dynamic_activation_is_consistent_for_delayed_cut_and_late_action(self) -> None:
        def transition(enter: float, withdraw: float) -> dict:
            return {
                "enter_hazard_per_step": enter,
                "withdraw_hazard_per_step": withdraw,
                "entry_initialization": {"policy": "RESET_TO_PRIOR"},
                "exit_policy": {"policy": "SURVIVOR_CARRY_REENTRY_RESET"},
                "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
                "source_id": "case-blind-structural-test",
                "version": "1",
            }

        spec = model_dict()
        for process in spec["processes"]:
            process["activation_transition"] = transition(0.0, 0.0)
        next(row for row in spec["processes"] if row["process_id"] == "PROCESS_A")[
            "activation_transition"
        ] = transition(0.02, 0.25)
        next(row for row in spec["processes"] if row["process_id"] == "PROCESS_C")[
            "activation_transition"
        ] = transition(0.08, 0.01)
        spec["actions"][0]["activation_effects"] = [
            {
                "process_id": "PROCESS_C",
                "enter_log_hazard_shift_per_unit": 2.0,
                "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
                "source_id": "case-blind-structural-test",
                "version": "1",
            }
        ]
        runtime = RuntimeV2(spec)
        observation = PublicEvent.from_dict(
            {
                "event_id": "obs-at-one",
                "event_type": "ObservationAvailable",
                "available_at": 1,
                "recorded_at": 1,
                "occurred_time": {"lower": 1, "upper": 1},
                "sample_time": {"lower": 1, "upper": 1},
                "result_at": 1,
                "concept_id": "OBS_A_MARKER",
                "value": True,
                "provenance": {"source_result_id": "obs-at-one"},
            }
        )

        # initialize(events@t=1, cut=5) and an equivalent sequence of updates
        # must use the same transition/observation ordering.
        direct = runtime.initialize([observation], cut=5)
        sequential = runtime.initialize([], cut=0)
        sequential = runtime.update(sequential, [observation], advance_to=1)
        sequential = runtime.update(sequential, [], advance_to=5)
        self.assertEqual(
            direct.to_dict()["active_process_posterior"],
            sequential.to_dict()["active_process_posterior"],
        )
        self.assertEqual(local_state_map(direct), local_state_map(sequential))
        runtime.forecast(direct, horizon=1)

        late_action = PublicEvent.from_dict(
            {
                "event_id": "late-action",
                "event_type": "ActionStarted",
                "available_at": 3,
                "recorded_at": 3,
                "occurred_time": {"lower": 3, "upper": 3},
                "provenance": {"source_result_id": "late-action"},
                "action_id": "ACTION_REDUCE_A",
                "exposure_id": "late-exposure",
                "dose": 0.5,
            }
        )
        direct_action = runtime.initialize([late_action], cut=5)
        sequential_action = runtime.initialize([], cut=0)
        sequential_action = runtime.update(
            sequential_action, [late_action], advance_to=3
        )
        sequential_action = runtime.update(sequential_action, [], advance_to=5)
        self.assertEqual(
            direct_action.to_dict()["active_process_posterior"],
            sequential_action.to_dict()["active_process_posterior"],
        )
        self.assertEqual(local_state_map(direct_action), local_state_map(sequential_action))
        self.assertEqual(
            direct_action.to_dict()["action_memory"],
            sequential_action.to_dict()["action_memory"],
        )
        runtime.forecast(direct_action, horizon=1)

    def test_activation_kernel_scales_to_thirteen_known_processes(self) -> None:
        """Guard against the former O(4^N) simultaneous-target enumerator."""

        spec = model_dict()
        template = copy.deepcopy(spec["processes"][0])
        processes = []
        for index in range(13):
            process = copy.deepcopy(template)
            process_id = f"PERF_PROCESS_{index:02d}"
            coordinate_id = f"perf_burden_{index:02d}"
            process["process_id"] = process_id
            process["branch_id"] = process_id
            process["organ_or_domain"] = f"PERF_DOMAIN_{index:02d}"
            process["activation_prior"] = 0.1 + 0.01 * (index % 5)
            process["coordinates"][0]["coordinate_id"] = coordinate_id
            for mode in process["modes"]:
                drift = next(iter(mode["coordinate_drift"].values()))
                mode["coordinate_drift"] = {coordinate_id: drift}
            process["activation_transition"] = {
                "enter_hazard_per_step": 0.02,
                "withdraw_hazard_per_step": 0.03,
                "entry_initialization": {"policy": "RESET_TO_PRIOR"},
                "exit_policy": {"policy": "SURVIVOR_CARRY_REENTRY_RESET"},
                "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
                "source_id": "thirteen-process-complexity-gate",
                "version": "1",
            }
            processes.append(process)
        spec["processes"] = processes
        spec["inference"]["max_exact_processes"] = 13
        spec["observations"] = []
        spec["coactivation_interactions"] = []
        spec["process_couplings"] = []
        spec["mode_couplings"] = []
        spec["actions"] = []
        spec["topology"]["edges"] = []
        spec["topology"]["planning_bridges"] = []
        runtime = RuntimeV2(spec)
        joint = runtime._enumerate_prior()
        coordinates = {
            process["process_id"]: {
                process["coordinates"][0]["coordinate_id"]: {
                    "mean": 0.2,
                    "uncertainty": 0.8,
                }
            }
            for process in processes
        }
        modes = {
            process["process_id"]: {
                mode["mode_id"]: mode["prior"] for mode in process["modes"]
            }
            for process in processes
        }
        started = time.perf_counter()
        propagated, _ = runtime._advance_process_activation(
            joint,
            action_doses={},
            coordinates=coordinates,
            modes=modes,
            step_width=1.0,
        )
        elapsed = time.perf_counter() - started
        # 13 known bits plus the preserved OOD bit = 16,384 exact rows.
        self.assertEqual(len(propagated), 2 ** 14)
        self.assertAlmostEqual(sum(row["probability"] for row in propagated), 1.0)
        # The O(N*2^N) implementation is normally sub-second here.  Five
        # seconds leaves broad CI headroom while deterministically rejecting
        # the former O(4^N) implementation (about 1.34e8 branch expansions).
        self.assertLess(elapsed, 5.0)

    def test_activation_kernel_is_alpha_renaming_invariant_and_mass_preserving(self) -> None:
        """Process IDs/registry order cannot change coupled activation physics."""

        spec = model_dict()
        for process in spec["processes"]:
            process["activation_transition"] = {
                "enter_hazard_per_step": 0.04,
                "withdraw_hazard_per_step": 0.03,
                "entry_initialization": {"policy": "RESET_TO_PRIOR"},
                "exit_policy": {"policy": "SURVIVOR_CARRY_REENTRY_RESET"},
                "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
                "source_id": "alpha-renaming-gate",
                "version": "1",
            }
        spec["process_activation_couplings"] = [
            {
                "coupling_id": "A-raises-B-entry",
                "source_process_id": "PROCESS_A",
                "target_process_id": "PROCESS_B",
                "enter_log_hazard_shift_per_step": 3.0,
                "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
                "source_id": "alpha-renaming-gate",
                "version": "1",
            }
        ]

        rename = {
            "PROCESS_A": "ZZZ_SOURCE",
            "PROCESS_B": "AAA_TARGET",
            "PROCESS_C": "MMM_OTHER",
        }

        def alpha_rename(value):
            if isinstance(value, str):
                return rename.get(value, value)
            if isinstance(value, list):
                return [alpha_rename(item) for item in value]
            if isinstance(value, dict):
                return {
                    rename.get(key, key): alpha_rename(item)
                    for key, item in value.items()
                }
            return value

        renamed_spec = alpha_rename(copy.deepcopy(spec))
        renamed_spec["model_id"] = "alpha-renamed-equivalent-model"
        original = RuntimeV2(spec)
        renamed = RuntimeV2(renamed_spec)

        def propagate(runtime: RuntimeV2):
            payload = runtime._empty_payload(0.0)
            rows, _ = runtime._advance_process_activation(
                payload["joint_hypotheses"],
                action_doses={},
                coordinates={
                    pid: copy.deepcopy(payload["per_process"][pid]["coordinates"])
                    for pid in runtime.process_ids
                },
                modes={
                    pid: copy.deepcopy(payload["per_process"][pid]["mode_posterior"])
                    for pid in runtime.process_ids
                },
                step_width=1.0,
            )
            self.assertTrue(all(math.isfinite(row["probability"]) for row in rows))
            self.assertTrue(all(row["probability"] >= 0.0 for row in rows))
            self.assertAlmostEqual(
                math.fsum(row["probability"] for row in rows), 1.0, places=12
            )
            return {
                pid: math.fsum(
                    row["probability"] for row in rows if pid in row["active_processes"]
                )
                for pid in runtime.process_ids
            }

        original_marginals = propagate(original)
        renamed_marginals = propagate(renamed)
        for original_id, renamed_id in rename.items():
            self.assertAlmostEqual(
                original_marginals[original_id],
                renamed_marginals[renamed_id],
                places=12,
            )

    def test_activation_local_memory_entry_exit_and_inactive_drift_contract(self) -> None:
        """D01: local state is q(x,m|active), with no dormant-memory fiction."""

        spec = model_dict()
        process_a = next(row for row in spec["processes"] if row["process_id"] == "PROCESS_A")
        process_a["activation_prior"] = 1e-9
        process_a["activation_transition"] = {
            "enter_hazard_per_step": 0.0,
            "withdraw_hazard_per_step": 0.1,
            "entry_initialization": {"policy": "RESET_TO_PRIOR"},
            "exit_policy": {"policy": "SURVIVOR_CARRY_REENTRY_RESET"},
            "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
            "source_id": "activation-local-memory-gate",
            "version": "1",
        }
        runtime = RuntimeV2(spec)
        state = runtime.initialize([], cut=0)
        initial = local_state_map(state)["PROCESS_A"]["coordinates"][0]["distribution"]["mean"]
        forecast = runtime.forecast(state, horizon=2)
        final = forecast["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"]
        # The decompensated-mode drift exists in the model, but an almost
        # certainly inactive process must not accumulate it in the background.
        self.assertLess(abs(final - initial), 1e-8)
        self.assertEqual(
            forecast["final_mode_posteriors"]["PROCESS_A"],
            {
                mode["mode_id"]: mode["prior"]
                for mode in process_a["modes"]
            },
        )

        def local_fixture():
            local_spec = model_dict()
            process = next(
                row for row in local_spec["processes"] if row["process_id"] == "PROCESS_A"
            )
            process["activation_transition"] = {
                "enter_hazard_per_step": 0.2,
                "withdraw_hazard_per_step": 0.2,
                "entry_initialization": {"policy": "RESET_TO_PRIOR"},
                "exit_policy": {"policy": "SURVIVOR_CARRY_REENTRY_RESET"},
                "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
                "source_id": "activation-local-memory-gate",
                "version": "1",
            }
            return RuntimeV2(local_spec)

        def altered_local():
            return (
                {"a_burden": {"mean": 0.9, "uncertainty": 0.1}},
                {"compensated": 0.0, "decompensated": 1.0, "recovering": 0.0},
            )

        conditional = local_fixture()

        # A non-selective partial exit removes active mass but cannot change
        # the state distribution among the active survivors.
        coordinates, modes = altered_local()
        conditional._apply_activation_local_semantics(
            "PROCESS_A",
            coordinates,
            modes,
            {
                "p_active_before": 0.8,
                "p_active_after": 0.5,
                "entered_probability_flux": 0.0,
                "withdrawn_probability_flux": 0.3,
            },
            step_width=1.0,
        )
        self.assertAlmostEqual(coordinates["a_burden"]["mean"], 0.9)
        self.assertAlmostEqual(modes["decompensated"], 1.0)

        # Once active mass is numerically zero, the sole wire row is a prior
        # placeholder; there is no representable dormant memory.
        coordinates, modes = altered_local()
        conditional._apply_activation_local_semantics(
            "PROCESS_A",
            coordinates,
            modes,
            {
                "p_active_before": 1.0,
                "p_active_after": 0.0,
                "entered_probability_flux": 0.0,
                "withdrawn_probability_flux": 1.0,
            },
            step_width=1.0,
        )
        self.assertAlmostEqual(coordinates["a_burden"]["mean"], 0.2)
        self.assertAlmostEqual(modes["compensated"], 0.65)

        # Re-entry always starts from the declared prior, even if a caller
        # presents an altered placeholder.
        coordinates, modes = altered_local()
        conditional._apply_activation_local_semantics(
            "PROCESS_A",
            coordinates,
            modes,
            {
                "p_active_before": 0.0,
                "p_active_after": 0.5,
                "entered_probability_flux": 0.5,
                "withdrawn_probability_flux": 0.0,
            },
            step_width=1.0,
        )
        self.assertAlmostEqual(coordinates["a_burden"]["mean"], 0.2)
        self.assertAlmostEqual(modes["compensated"], 0.65)

        # Entrants and active survivors mix by active probability mass.
        coordinates, modes = altered_local()
        conditional._apply_activation_local_semantics(
            "PROCESS_A",
            coordinates,
            modes,
            {
                "p_active_before": 0.5,
                "p_active_after": 0.8,
                "entered_probability_flux": 0.3,
                "withdrawn_probability_flux": 0.0,
            },
            step_width=1.0,
        )
        expected = (0.5 * 0.9 + 0.3 * 0.2) / 0.8
        self.assertAlmostEqual(coordinates["a_burden"]["mean"], expected)

    def test_activation_transition_schema_requires_explicit_local_memory_semantics(self) -> None:
        spec = model_dict()
        process_a = next(row for row in spec["processes"] if row["process_id"] == "PROCESS_A")
        process_a["activation_transition"] = {
            "enter_hazard_per_step": 0.1,
            "withdraw_hazard_per_step": 0.0,
            "parameter_status": "STRUCTURAL_TOY_NONCALIBRATED",
            "source_id": "missing-local-memory-contract",
            "version": "1",
        }
        with self.assertRaisesRegex(ValueError, "entry_initialization and exit_policy"):
            RuntimeV2(spec)

        old_policies = [
            {"policy": "CARRY"},
            {"policy": "RESET_TO_PRIOR"},
            {"policy": "DECAY_TO_PRIOR", "decay_rate_per_step": 1.0},
        ]
        for exit_policy in old_policies:
            invalid = copy.deepcopy(spec)
            transition = next(
                row for row in invalid["processes"] if row["process_id"] == "PROCESS_A"
            )["activation_transition"]
            transition["entry_initialization"] = {"policy": "RESET_TO_PRIOR"}
            transition["exit_policy"] = exit_policy
            with self.subTest(exit_policy=exit_policy):
                with self.assertRaisesRegex(
                    ValueError, "SURVIVOR_CARRY_REENTRY_RESET"
                ):
                    RuntimeV2(invalid)

        invalid_entry = copy.deepcopy(spec)
        transition = next(
            row for row in invalid_entry["processes"] if row["process_id"] == "PROCESS_A"
        )["activation_transition"]
        transition["entry_initialization"] = {"policy": "CARRY"}
        transition["exit_policy"] = {
            "policy": "SURVIVOR_CARRY_REENTRY_RESET"
        }
        with self.assertRaisesRegex(ValueError, "must be RESET_TO_PRIOR"):
            RuntimeV2(invalid_entry)

        for field, value in (
            ("enter_log_hazard_shift_by_mode", {"compensated": 0.1}),
            ("withdraw_log_hazard_shift_by_mode", {"compensated": -0.1}),
            ("enter_log_hazard_shift_by_coordinate", {"a_burden": 0.1}),
            ("withdraw_log_hazard_shift_by_coordinate", {"a_burden": -0.1}),
        ):
            invalid = copy.deepcopy(spec)
            transition = next(
                row for row in invalid["processes"] if row["process_id"] == "PROCESS_A"
            )["activation_transition"]
            transition["entry_initialization"] = {"policy": "RESET_TO_PRIOR"}
            transition["exit_policy"] = {
                "policy": "SURVIVOR_CARRY_REENTRY_RESET"
            }
            transition[field] = value
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "must be empty"):
                    RuntimeV2(invalid)

    def test_factual_clock_materializes_net_mode_transition_history(self) -> None:
        spec = model_dict()
        process = next(row for row in spec["processes"] if row["process_id"] == "PROCESS_A")
        process["coordinates"][0]["prior_mean"] = 0.8
        for mode in process["modes"]:
            mode["prior"] = 0.98 if mode["mode_id"] == "compensated" else 0.01
            mode["coordinate_drift"]["a_burden"] = (
                0.1 if mode["mode_id"] == "decompensated" else 0.0
            )
        process["mode_guards"] = [
            {
                "guard_id": "A_ENTER_DECOMP",
                "coordinate_id": "a_burden",
                "source_mode_id": "compensated",
                "target_mode_id": "decompensated",
                "direction": "above",
                "enter_threshold": 0.7,
                "exit_threshold": 0.5,
                "transition_probability": 1.0,
            }
        ]
        runtime = RuntimeV2(spec)
        state = runtime.initialize([], cut=0)
        advanced = runtime.update(state, [], advance_to=2)
        history = advanced.to_dict()["history_summary"]
        transitions = [
            row
            for row in history["mode_transitions"]
            if row["stratum_id"] == "stratum:PROCESS_A"
        ]
        self.assertEqual(len(transitions), 1)
        self.assertEqual(transitions[0]["from_mode_id"], "compensated")
        self.assertEqual(transitions[0]["to_mode_id"], "decompensated")
        self.assertEqual(transitions[0]["event_cursor"], 0)
        self.assertIn("A_ENTER_DECOMP", transitions[0]["guard_ids"])
        self.assertEqual(
            local_state_map(advanced)["PROCESS_A"]["last_transition_cursor"], 0
        )


if __name__ == "__main__":
    unittest.main()

