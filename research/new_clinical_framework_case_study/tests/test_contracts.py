from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from case_adapter import load_case, validate_monotone_case
from harness_utils import canonical_json_bytes, seal_files

from framework import FrameworkModel, PublicEvent, SharedPatientState


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "models" / "tma_generic_model.json"


def event(
    event_id: str,
    event_type: str,
    concept_id: str,
    value: object,
    *,
    available_at: int = 0,
    source_result_id: str | None = None,
) -> PublicEvent:
    return PublicEvent.from_dict(
        {
            "event_id": event_id,
            "event_type": event_type,
            "available_at": available_at,
            "concept_id": concept_id,
            "value": value,
            "unit": None,
            "rankable": event_type == "ObservationAvailable",
            "measurement_context": {},
            "provenance": {
                "source_result_id": source_result_id or event_id,
                "synthetic_fixture": True,
            },
        }
    )


def load_model() -> FrameworkModel:
    spec = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    return FrameworkModel.from_dict(spec)


def behavior_wire(state: SharedPatientState) -> dict[str, object]:
    wire = copy.deepcopy(state.to_dict())
    for key in (
        "state_hash", "lineage", "available_cut", "consumed_event_digests",
        "factor_observations",
    ):
        wire.pop(key, None)
    return wire


class EventLedgerContractTests(unittest.TestCase):
    def test_both_independent_case_schemas_normalize_monotonically(self) -> None:
        for path in sorted((ROOT / "cases").glob("*/*.json")):
            case = load_case(path)
            validate_monotone_case(case)
            self.assertGreater(len(case.cut_ids), 1)
            self.assertGreater(len(case.events), 0)
            self.assertEqual(
                len(case.events_at(case.cut_ids[-1])),
                len(case.events),
            )

    def test_blind_model_files_have_deterministic_freeze_hash(self) -> None:
        paths = sorted((ROOT / "models").glob("*_generic_model.json"))
        self.assertTrue(paths)
        first = seal_files(ROOT, paths, role="blind_pre_case_model")
        second = seal_files(ROOT, list(reversed(paths)), role="blind_pre_case_model")
        self.assertEqual(first, second)

    def test_future_availability_cannot_change_earlier_state(self) -> None:
        model = load_model()
        current = event("o0", "ObservationAvailable", "O_ANTI_GBM_ASSAY", "positive")
        future = event(
            "o1",
            "ObservationAvailable",
            "O_ADAMTS13_ACTIVITY",
            "preserved",
            available_at=2,
        )
        state_without_future = model.initialize([current], cut=0)
        state_with_future_file = model.initialize([current, future], cut=0)
        self.assertEqual(state_without_future.to_bytes(), state_with_future_file.to_bytes())

    def test_planned_action_does_not_change_physiology(self) -> None:
        model = load_model()
        baseline = model.initialize([], cut=0)
        planned = event(
            "plan",
            "PlannedTreatment",
            "A_HEPARIN_EXPOSURE_START_OR_CONTINUE",
            {"status": "planned"},
            available_at=1,
        )
        after_plan = model.update(baseline, [planned], advance_to=1)
        before_wire = baseline.to_dict()
        after_wire = after_plan.to_dict()
        self.assertEqual(
            before_wire["action_exposure"],
            after_wire["action_exposure"],
        )
        self.assertEqual(
            model.rollout(baseline, {"policy_id": "A_NO_NEW_ACTION"}, 1)["trajectory"],
            model.rollout(after_plan, {"policy_id": "A_NO_NEW_ACTION"}, 1)["trajectory"],
        )


class SharedStateContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.model = load_model()
        self.state = self.model.initialize(
            [
                event("p", "ObservationAvailable", "O_PLATELET_COUNT_RELATIVE", "marked"),
                event("ldh", "ObservationAvailable", "O_LDH_RELATIVE", "marked"),
            ],
            cut=0,
        )

    def test_diagnosis_forecast_and_plan_consume_exact_same_state_hash(self) -> None:
        diagnosis = self.model.diagnose(self.state)
        natural = self.model.rollout(
            self.state, {"policy_id": "A_NO_NEW_ACTION"}, horizon=2
        )
        plan = self.model.plan(
            self.state,
            [
                {"policy_id": "A_NO_NEW_ACTION"},
                {"policy_id": "A_PLASMA_EXCHANGE_LIKE"},
            ],
            horizon=2,
        )
        self.assertEqual(
            {diagnosis["consumed_state_hash"], natural["consumed_state_hash"], plan["consumed_state_hash"]},
            {self.state.state_hash},
        )

    def test_queries_are_pure_and_order_independent(self) -> None:
        original = self.state.to_bytes()
        policy_a = {"policy_id": "A_NO_NEW_ACTION"}
        policy_b = {"policy_id": "A_PLASMA_EXCHANGE_LIKE"}
        first_a = self.model.rollout(self.state, policy_a, 2)
        first_b = self.model.rollout(self.state, policy_b, 2)
        second_b = self.model.rollout(self.state, policy_b, 2)
        second_a = self.model.rollout(self.state, policy_a, 2)
        self.assertEqual(first_a, second_a)
        self.assertEqual(first_b, second_b)
        self.assertEqual(original, self.state.to_bytes())

    def test_recursive_update_is_closed_over_serialized_state(self) -> None:
        delta = [event("h", "ObservationAvailable", "O_HAPTOGLOBIN_RELATIVE", "marked")]
        direct = self.model.update(self.state, delta, advance_to=1)
        restored = SharedPatientState.from_bytes(self.state.to_bytes())
        cold_model = load_model()
        cold = cold_model.update(restored, delta, advance_to=1)
        self.assertEqual(direct.to_bytes(), cold.to_bytes())
        self.assertEqual(direct.to_dict()["lineage"]["parent_state_hash"], self.state.state_hash)

    def test_factor_copy_attack_does_not_multiply_common_cause_evidence(self) -> None:
        model = load_model()
        one = event(
            "s0",
            "ObservationAvailable",
            "O_SCHISTOCYTE_BURDEN",
            "marked",
            source_result_id="smear-1",
        )
        copies = [
            event(
                f"copy-{index}",
                "ObservationAvailable",
                "O_SCHISTOCYTE_BURDEN",
                "marked",
                source_result_id="smear-1",
            )
            for index in range(10)
        ]
        state_one = model.initialize([one], cut=0)
        state_copies = model.initialize(copies, cut=0)
        diagnosis_one = model.diagnose(state_one)
        diagnosis_copies = model.diagnose(state_copies)
        self.assertEqual(
            diagnosis_one["branch_posterior"],
            diagnosis_copies["branch_posterior"],
        )
        self.assertEqual(
            state_one.to_dict()["factor_evidence_counts"],
            state_copies.to_dict()["factor_evidence_counts"],
        )

    def test_state_is_canonical_json_not_python_object_identity(self) -> None:
        wire = self.state.to_dict()
        self.assertEqual(self.state.to_bytes(), canonical_json_bytes(wire))
        clone = SharedPatientState.from_bytes(self.state.to_bytes())
        self.assertEqual(clone.state_hash, self.state.state_hash)
        self.assertIsNot(clone, self.state)

    def test_history_and_action_ablations_expose_snapshot_collisions(self) -> None:
        full_model = load_model()
        improving = [
            event("p0", "ObservationAvailable", "O_PLATELET_COUNT_RELATIVE", "extreme", available_at=0),
            event("p1", "ObservationAvailable", "O_PLATELET_COUNT_RELATIVE", "mild", available_at=1),
        ]
        chronically_mild = [
            event("q0", "ObservationAvailable", "O_PLATELET_COUNT_RELATIVE", "mild", available_at=0),
            event("q1", "ObservationAvailable", "O_PLATELET_COUNT_RELATIVE", "mild", available_at=1),
        ]
        full_a = full_model.initialize(improving, cut=1)
        full_b = full_model.initialize(chronically_mild, cut=1)
        self.assertNotEqual(behavior_wire(full_a), behavior_wire(full_b))

        no_history_a = full_model.initialize(improving, cut=1, options={"history": False})
        no_history_b = full_model.initialize(chronically_mild, cut=1, options={"history": False})
        self.assertEqual(behavior_wire(no_history_a), behavior_wire(no_history_b))

        surface = event("surface", "ObservationAvailable", "O_HEMODYNAMIC_STRAIN", "none", available_at=1)
        support = event(
            "support",
            "PerformedTreatment",
            "A_CONTINUE_EXISTING_SUPPORT",
            {"level": "high", "status": "performed"},
            available_at=0,
        )
        supported = full_model.initialize([support, surface], cut=1)
        unsupported = full_model.initialize([surface], cut=1)
        self.assertNotEqual(
            supported.to_dict()["action_exposure"], unsupported.to_dict()["action_exposure"]
        )

        no_action_a = full_model.initialize(
            [support, surface], cut=1, options={"actions": False}
        )
        no_action_b = full_model.initialize([surface], cut=1, options={"actions": False})
        self.assertEqual(
            no_action_a.to_dict()["action_exposure"], no_action_b.to_dict()["action_exposure"]
        )
        self.assertEqual(
            full_model.rollout(no_action_a, {"policy_id": "A_NO_NEW_ACTION"}, 1)["trajectory"],
            full_model.rollout(no_action_b, {"policy_id": "A_NO_NEW_ACTION"}, 1)["trajectory"],
        )

    def test_discrete_mode_ablation_loses_same_endpoint_direction(self) -> None:
        model = load_model()
        recovering = [
            event("r0", "ObservationAvailable", "O_HEMODYNAMIC_STRAIN", "marked", available_at=0),
            event("r1", "ObservationAvailable", "O_HEMODYNAMIC_STRAIN", "mild", available_at=1),
        ]
        deteriorating = [
            event("d0", "ObservationAvailable", "O_HEMODYNAMIC_STRAIN", "none", available_at=0),
            event("d1", "ObservationAvailable", "O_HEMODYNAMIC_STRAIN", "mild", available_at=1),
        ]
        state_r = model.initialize(recovering, cut=1)
        state_d = model.initialize(deteriorating, cut=1)
        self.assertNotEqual(
            state_r.to_dict()["mode_posterior"], state_d.to_dict()["mode_posterior"]
        )
        self.assertNotEqual(
            model.rollout(state_r, {"policy_id": "A_NO_NEW_ACTION"}, 1)["trajectory"],
            model.rollout(state_d, {"policy_id": "A_NO_NEW_ACTION"}, 1)["trajectory"],
        )

        no_mode_r = model.initialize(recovering, cut=1, options={"mode": False})
        no_mode_d = model.initialize(deteriorating, cut=1, options={"mode": False})
        self.assertEqual(
            model.rollout(no_mode_r, {"policy_id": "A_NO_NEW_ACTION"}, 1)["trajectory"],
            model.rollout(no_mode_d, {"policy_id": "A_NO_NEW_ACTION"}, 1)["trajectory"],
        )

    def test_branch_topology_distance_is_not_flat_chart_distance(self) -> None:
        model = load_model()
        same_chart = model.branch_distance(
            "B_COMPLEMENT_TMA", {"disease_load": 0.5},
            "B_COMPLEMENT_TMA", {"disease_load": 0.6},
        )
        sibling_chart = model.branch_distance(
            "B_COMPLEMENT_TMA", {"disease_load": 0.5},
            "B_TTP", {"disease_load": 0.5},
        )
        remote_chart = model.branch_distance(
            "B_COMPLEMENT_TMA", {"disease_load": 0.5},
            "B_ANTI_GBM", {"disease_load": 0.5},
        )
        self.assertLess(same_chart, sibling_chart)
        self.assertLess(sibling_chart, remote_chart)

        # The no-topology baseline compares only numerically matching values and
        # therefore (incorrectly) declares both cross-chart pairs identical.
        naive_flat_sibling = abs(0.5 - 0.5)
        naive_flat_remote = abs(0.5 - 0.5)
        self.assertEqual(naive_flat_sibling, naive_flat_remote)
        self.assertNotEqual(sibling_chart, remote_chart)


if __name__ == "__main__":
    unittest.main()
