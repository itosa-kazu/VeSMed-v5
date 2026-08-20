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
)


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "examples" / "neutral_factorial_model.json"


def numeric_observation(event_id: str, value: float, at: float) -> PublicEvent:
    return PublicEvent.from_dict(
        {
            "event_id": event_id,
            "event_type": "ObservationAvailable",
            "available_at": at,
            "recorded_at": at,
            "occurred_time": {"lower": at, "upper": at},
            "sample_time": {"lower": at, "upper": at},
            "result_at": at,
            "concept_id": "OBS_A_LOAD",
            "value": value,
            "unit": "score",
            "provenance": {"source_result_id": event_id},
        }
    )


def boolean_observation(event_id: str, value: bool, at: float) -> PublicEvent:
    return PublicEvent.from_dict(
        {
            "event_id": event_id,
            "event_type": "ObservationAvailable",
            "available_at": at,
            "recorded_at": at,
            "occurred_time": {"lower": at, "upper": at},
            "sample_time": {"lower": at, "upper": at},
            "result_at": at,
            "concept_id": "OBS_A_MARKER",
            "value": value,
            "provenance": {"source_result_id": event_id},
        }
    )


def feature_map(state: SharedPatientState) -> dict[str, dict]:
    return {
        row["feature_id"]: row
        for row in state.to_dict()["history_summary"]["trajectory_features"]
        if row["target_id"] == "OBS_A_LOAD"
    }


class HistoryWireSemanticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RuntimeV2.from_json(MODEL_PATH)

    def test_cold_restore_preserves_longitudinal_summary_exactly(self) -> None:
        first = self.runtime.initialize([numeric_observation("hist-1", 0.2, 0)], cut=0)
        second = self.runtime.update(
            first, [numeric_observation("hist-2", 0.5, 1)], advance_to=1
        )

        features = feature_map(second)
        self.assertEqual(features["latest:OBS_A_LOAD"]["value"], 0.5)
        self.assertEqual(features["previous:OBS_A_LOAD"]["value"], 0.2)
        self.assertAlmostEqual(features["trend:OBS_A_LOAD"]["value"], 0.3)
        self.assertEqual(features["count:OBS_A_LOAD"]["value"], 2.0)
        self.assertEqual(features["latest_available_at:OBS_A_LOAD"]["value"], 1.0)

        third = numeric_observation("hist-3", 0.9, 2)
        warm = self.runtime.update(second, [third], advance_to=2)
        cold_parent = SharedPatientState.from_bytes(second.to_bytes())
        cold = RuntimeV2.from_json(MODEL_PATH).update(
            cold_parent,
            [third],
            advance_to=2,
            event_ledger_proof=build_event_ledger_proof(second),
        )
        self.assertEqual(warm.to_bytes(), cold.to_bytes())
        final_features = feature_map(cold)
        self.assertEqual(final_features["previous:OBS_A_LOAD"]["value"], 0.5)
        self.assertAlmostEqual(final_features["trend:OBS_A_LOAD"]["value"], 0.4)
        self.assertEqual(final_features["count:OBS_A_LOAD"]["value"], 3.0)

    def test_repeated_boolean_history_is_not_a_numeric_trend_and_cold_queries(self) -> None:
        first = self.runtime.initialize([boolean_observation("bool-1", True, 0)], cut=0)
        second = self.runtime.update(
            first, [boolean_observation("bool-2", False, 1)], advance_to=1
        )

        marker_features = {
            row["feature_id"]: row
            for row in second.to_dict()["history_summary"]["trajectory_features"]
            if row["target_id"] == "OBS_A_MARKER"
        }
        self.assertNotIn("latest:OBS_A_MARKER", marker_features)
        self.assertNotIn("previous:OBS_A_MARKER", marker_features)
        self.assertNotIn("trend:OBS_A_MARKER", marker_features)
        self.assertEqual(marker_features["count:OBS_A_MARKER"]["value"], 2.0)

        cold_parent = SharedPatientState.from_bytes(second.to_bytes())
        cold_runtime = RuntimeV2.from_json(MODEL_PATH)
        cold_runtime.diagnose(cold_parent)
        third = boolean_observation("bool-3", True, 2)
        warm = self.runtime.update(second, [third], advance_to=2)
        cold = cold_runtime.update(
            cold_parent,
            [third],
            advance_to=2,
            event_ledger_proof=build_event_ledger_proof(second),
        )
        self.assertEqual(warm.to_bytes(), cold.to_bytes())

    def test_rehashed_history_semantic_edit_fails_closed(self) -> None:
        first = self.runtime.initialize([numeric_observation("hist-a", 0.2, 0)], cut=0)
        state = self.runtime.update(
            first, [numeric_observation("hist-b", 0.5, 1)], advance_to=1
        )
        wire = state.to_dict()
        previous = next(
            row
            for row in wire["history_summary"]["trajectory_features"]
            if row["feature_id"] == "previous:OBS_A_LOAD"
        )
        previous["value"] = 99.0
        body = {
            "trajectory_features": wire["history_summary"]["trajectory_features"],
            "mode_transitions": wire["history_summary"]["mode_transitions"],
            "action_response_windows": wire["history_summary"]["action_response_windows"],
            "retained_event_ids": wire["history_summary"]["retained_event_ids"],
        }
        # Recompute both the materialized-view digest and the outer state hash:
        # a valid content hash must not authorize a contradictory history.
        import hashlib

        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        wire["history_summary"]["summary_digest"] = hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
        wire["integrity"]["state_hash"] = architecture_state_hash(wire)
        tampered = SharedPatientState.from_dict(wire)
        with self.assertRaises(ValueError):
            self.runtime.diagnose(tampered)

    def test_unsupported_schema_valid_history_feature_is_rejected_not_deleted(self) -> None:
        state = self.runtime.initialize([], cut=0)
        wire = state.to_dict()
        wire["history_summary"]["trajectory_features"].append(
            {
                "feature_id": "rolling_mean:OBS_A_LOAD",
                "target_id": "OBS_A_LOAD",
                "window_id": "undeclared-window",
                "value": 0.4,
                "unit": "score",
                "source_event_ids": [],
            }
        )
        body = {
            "trajectory_features": wire["history_summary"]["trajectory_features"],
            "mode_transitions": wire["history_summary"]["mode_transitions"],
            "action_response_windows": wire["history_summary"]["action_response_windows"],
            "retained_event_ids": wire["history_summary"]["retained_event_ids"],
        }
        import hashlib

        canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        wire["history_summary"]["summary_digest"] = hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
        wire["integrity"]["state_hash"] = architecture_state_hash(wire)
        forged = SharedPatientState.from_dict(wire)
        with self.assertRaisesRegex(ValueError, "unsupported trajectory feature"):
            self.runtime.diagnose(forged)


if __name__ == "__main__":
    unittest.main()
