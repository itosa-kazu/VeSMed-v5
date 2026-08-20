from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from runtime_v2 import (
    PublicEvent,
    RuntimeV2,
    SharedPatientState,
    architecture_state_hash,
    build_event_ledger_proof,
    digest,
)
from runtime_v2.architecture_wire import model_time_from_as_of


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "examples" / "neutral_factorial_model.json"


def observation(event_id: str, concept_id: str, value: object, at: float) -> PublicEvent:
    return PublicEvent.from_dict(
        {
            "event_id": event_id,
            "event_type": "ObservationAvailable",
            "available_at": at,
            "recorded_at": at,
            "occurred_time": {"lower": at, "upper": at},
            "sample_time": {"lower": at, "upper": at},
            "result_at": at,
            "concept_id": concept_id,
            "value": value,
            "unit": "score" if isinstance(value, (int, float)) else None,
            "provenance": {"source_result_id": f"source:{event_id}"},
        }
    )


def action_start(event_id: str, at: float = 0.0) -> PublicEvent:
    return PublicEvent.from_dict(
        {
            "event_id": event_id,
            "event_type": "ActionStarted",
            "available_at": at,
            "recorded_at": at,
            "occurred_time": {"lower": at, "upper": at},
            "action_id": "ACTION_REDUCE_A",
            "exposure_id": "closure-exposure",
            "dose": 1.0,
            "provenance": {"source_result_id": f"source:{event_id}"},
        }
    )


def rehash_history(wire: dict) -> SharedPatientState:
    history = wire["history_summary"]
    body = {
        "trajectory_features": history["trajectory_features"],
        "mode_transitions": history["mode_transitions"],
        "action_response_windows": history["action_response_windows"],
        "retained_event_ids": history["retained_event_ids"],
    }
    history["summary_digest"] = digest(body)
    wire["integrity"]["state_hash"] = architecture_state_hash(wire)
    return SharedPatientState.from_dict(wire)


class QueryBoundaryHistoryClosureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RuntimeV2.from_json(MODEL_PATH)

    def _mode_state(self) -> SharedPatientState:
        state = self.runtime.initialize(
            [observation("mode-result", "OBS_A_DIRECTION", "falling", 0.0)],
            cut=0,
        )
        self.assertTrue(state.payload["history_summary"]["mode_transitions"])
        return state

    def _response_state(self) -> SharedPatientState:
        started = self.runtime.initialize([action_start("response-start")], cut=0)
        state = self.runtime.update(
            started,
            [observation("response-result", "OBS_A_LOAD", 0.1, 1.0)],
            advance_to=1,
        )
        self.assertTrue(state.payload["history_summary"]["action_response_windows"])
        return state

    def _assert_all_boundaries_reject(
        self,
        forged: SharedPatientState,
        original: SharedPatientState,
        pattern: str,
    ) -> None:
        proof = build_event_ledger_proof(original)
        # Rebind the otherwise-valid ledger proof to the forged envelope so the
        # update path reaches the same payload semantic validator as the query
        # heads. The history tamper under test does not alter ledger entries.
        proof["state_hash"] = forged.state_hash
        calls = (
            lambda: self.runtime.diagnose(forged),
            lambda: self.runtime.forecast(forged, horizon=1),
            lambda: self.runtime.plan(
                forged,
                [{"policy_id": "NO_NEW_ACTION", "start_actions": []}],
                horizon=1,
            ),
            lambda: self.runtime.update(
                forged,
                [],
                advance_to=model_time_from_as_of(forged.payload["as_of"]),
                event_ledger_proof=proof,
            ),
        )
        for call in calls:
            with self.subTest(boundary=call):
                with self.assertRaisesRegex(ValueError, pattern):
                    call()

    def test_rehashed_mode_cursor_outside_lineage_is_rejected_by_every_head(self) -> None:
        original = self._mode_state()
        wire = original.to_dict()
        transition = wire["history_summary"]["mode_transitions"][0]
        transition["event_cursor"] = 999
        local = next(
            row for row in wire["local_states"] if row["process_id"] == "PROCESS_A"
        )
        local["last_transition_cursor"] = 999
        forged = rehash_history(wire)
        self._assert_all_boundaries_reject(
            forged, original, "mode transition event_cursor"
        )

    def test_rehashed_mode_transition_guard_reference_is_model_bound(self) -> None:
        original = self._mode_state()
        wire = original.to_dict()
        wire["history_summary"]["mode_transitions"][0]["guard_ids"] = [
            "emission:FORGED_FACTOR"
        ]
        forged = rehash_history(wire)
        with self.assertRaisesRegex(ValueError, "undeclared guard/factor"):
            self.runtime.diagnose(forged)

    def test_mode_transition_cursor_cache_must_match_retained_history(self) -> None:
        original = self._mode_state()
        wire = original.to_dict()
        local = next(
            row for row in wire["local_states"] if row["process_id"] == "PROCESS_A"
        )
        local["last_transition_cursor"] = None
        wire["integrity"]["state_hash"] = architecture_state_hash(wire)
        forged = SharedPatientState.from_dict(wire)
        with self.assertRaisesRegex(ValueError, "last_transition_cursor disagrees"):
            self.runtime.diagnose(forged)

    def test_public_event_cursor_must_equal_processed_ledger_cardinality(self) -> None:
        original = self._mode_state()
        wire = original.to_dict()
        wire["as_of"]["event_cursor"] = 7
        wire["integrity"]["state_hash"] = architecture_state_hash(wire)
        forged = SharedPatientState.from_dict(wire)
        with self.assertRaisesRegex(ValueError, "event cursor does not equal"):
            self.runtime.diagnose(forged)

    def test_response_window_unknown_action_instance_is_rejected_by_every_head(self) -> None:
        original = self._response_state()
        wire = original.to_dict()
        wire["history_summary"]["action_response_windows"][0][
            "action_instance_ids"
        ] = ["forged-exposure"]
        forged = rehash_history(wire)
        self._assert_all_boundaries_reject(
            forged, original, "unknown/duplicate action instances"
        )

    def test_response_window_cursor_result_and_start_are_closed(self) -> None:
        original = self._response_state()
        mutations = (
            (
                lambda window: window.update({"start_cursor": 0}),
                "start does not match action start",
            ),
            (
                lambda window: window.update({"end_cursor": 999}),
                "cursor range is inconsistent",
            ),
            (
                lambda window: window.update({"result_event_ids": ["invented-result"]}),
                "results are not a processed-event subset",
            ),
        )
        for mutate, pattern in mutations:
            wire = original.to_dict()
            mutate(wire["history_summary"]["action_response_windows"][0])
            forged = rehash_history(wire)
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(ValueError, pattern):
                    self.runtime.diagnose(forged)

    def test_response_window_ids_are_unique_and_summary_bound(self) -> None:
        original = self._response_state()
        wire = original.to_dict()
        wire["history_summary"]["action_response_windows"].append(
            copy.deepcopy(wire["history_summary"]["action_response_windows"][0])
        )
        duplicate = rehash_history(wire)
        with self.assertRaisesRegex(ValueError, "window ids"):
            self.runtime.diagnose(duplicate)

        wire = original.to_dict()
        wire["history_summary"]["action_response_windows"][0]["window_id"] = (
            "response:unbound"
        )
        unbound = rehash_history(wire)
        with self.assertRaisesRegex(ValueError, "missing window"):
            self.runtime.diagnose(unbound)

    def test_new_response_baseline_is_bound_but_older_opaque_baseline_remains_legal(self) -> None:
        original = self._response_state()
        wire = original.to_dict()
        wire["history_summary"]["action_response_windows"][0][
            "baseline_state_hash"
        ] = "f" * 64
        forged = rehash_history(wire)
        with self.assertRaisesRegex(ValueError, "baseline is not bound"):
            self.runtime.diagnose(forged)

        # After another update the frozen wire no longer carries the complete
        # ancestry chain.  The old digest remains opaque but its window/action/
        # result references still have to close.
        later = self.runtime.update(original, [], advance_to=2)
        self.runtime.diagnose(SharedPatientState.from_bytes(later.to_bytes()))

    def test_initial_update_response_baseline_uses_verifiable_synthetic_digest(self) -> None:
        original = self.runtime.initialize(
            [
                action_start("initial-response-start", 0.0),
                observation("initial-response-result", "OBS_A_LOAD", 0.1, 1.0),
            ],
            cut=1,
        )
        self.assertIsNone(original.payload["event_lineage"]["parent_state_hash"])
        self.runtime.diagnose(SharedPatientState.from_bytes(original.to_bytes()))

        wire = original.to_dict()
        wire["history_summary"]["action_response_windows"][0][
            "baseline_state_hash"
        ] = "a" * 64
        forged = rehash_history(wire)
        with self.assertRaisesRegex(ValueError, "baseline is not bound"):
            self.runtime.diagnose(forged)

    def test_trajectory_source_ids_must_be_processed_and_typed(self) -> None:
        original = self.runtime.initialize(
            [observation("trajectory-result", "OBS_A_LOAD", 0.3, 0.0)], cut=0
        )
        wire = original.to_dict()
        for feature in wire["history_summary"]["trajectory_features"]:
            if feature["target_id"] == "OBS_A_LOAD":
                feature["source_event_ids"] = ["invented-trajectory-source"]
        forged = rehash_history(wire)
        with self.assertRaisesRegex(ValueError, "unprocessed source events"):
            self.runtime.diagnose(forged)

        wire = original.to_dict()
        latest = next(
            row
            for row in wire["history_summary"]["trajectory_features"]
            if row["feature_id"] == "latest:OBS_A_LOAD"
        )
        latest["window_id"] = "all-public-values"
        forged_type = rehash_history(wire)
        with self.assertRaisesRegex(ValueError, "invalid typed window"):
            self.runtime.diagnose(forged_type)

        wire = original.to_dict()
        count = next(
            row
            for row in wire["history_summary"]["trajectory_features"]
            if row["feature_id"] == "count:OBS_A_LOAD"
        )
        count["value"] = 2.0
        forged_count = rehash_history(wire)
        with self.assertRaisesRegex(ValueError, "count/provenance cardinality"):
            self.runtime.diagnose(forged_count)


if __name__ == "__main__":
    unittest.main()
