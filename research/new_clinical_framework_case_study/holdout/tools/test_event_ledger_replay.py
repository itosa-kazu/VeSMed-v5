from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[2]
if str(STUDY_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDY_ROOT))

from holdout.tools import event_ledger_replay as replay
from runtime_v2 import (
    EVENT_SCHEMA_VERSION,
    PublicEvent,
    RuntimeV2,
    SharedPatientState,
    build_event_ledger_proof,
    canonical_json_bytes,
)


MODEL_PATH = STUDY_ROOT / "runtime_v2" / "examples" / "neutral_factorial_model.json"


def observation(event_id: str, concept_id: str, value: object, at: float) -> PublicEvent:
    return PublicEvent.from_dict(
        {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": event_id,
            "event_type": "ObservationAvailable",
            "available_at": at,
            "recorded_at": at,
            "occurred_time": {"lower": at - 0.5, "upper": at - 0.5},
            "sample_time": {"lower": at - 0.5, "upper": at - 0.5},
            "result_at": at,
            "concept_id": concept_id,
            "value": value,
            "provenance": {"source_result_id": event_id},
        }
    )


class ReplayBundleContractTests(unittest.TestCase):
    def runtime(self) -> RuntimeV2:
        return RuntimeV2.from_json(MODEL_PATH)

    def test_same_id_same_bytes_is_idempotent_and_changed_bytes_fail_closed(self) -> None:
        first = observation("event-1", "OBS_A_MARKER", True, 0)
        recorder = replay.ReplayBundleRecorder(self.runtime())
        state = recorder.initialize([first], cut=0)
        repeated = recorder.update([first], advance_to=0)
        self.assertEqual(state.to_bytes(), repeated.to_bytes())
        self.assertTrue(recorder.bundle["cuts"][-1]["runtime_noop"])

        changed = observation("event-1", "OBS_A_MARKER", False, 0)
        with self.assertRaisesRegex(replay.EventIdConflict, "changed canonical bytes"):
            recorder.update([changed], advance_to=0)

    def test_cold_state_requires_and_accepts_bound_proof(self) -> None:
        event = observation("event-1", "OBS_A_MARKER", True, 0)
        recorder = replay.ReplayBundleRecorder(self.runtime())
        warm = recorder.initialize([event], cut=0)
        bundle = recorder.sealed_bundle()
        cold = SharedPatientState.from_bytes(warm.to_bytes())

        with self.assertRaisesRegex(ValueError, "content-addressed event ledger proof"):
            self.runtime().update(cold, [event], advance_to=0)

        entries = replay._proof_entries_for_state(bundle, cold)
        proof = build_event_ledger_proof(cold, entries)
        exact = self.runtime().update(
            cold, [event], advance_to=0, event_ledger_proof=proof
        )
        self.assertEqual(exact.to_bytes(), cold.to_bytes())

        changed = observation("event-1", "OBS_A_MARKER", False, 0)
        with self.assertRaisesRegex(ValueError, "event_id collision"):
            self.runtime().update(
                cold, [changed], advance_to=0, event_ledger_proof=proof
            )

    def test_event_order_is_deterministic(self) -> None:
        event_a = observation("a", "OBS_A_MARKER", True, 0)
        event_b = observation("b", "OBS_B_MARKER", True, 0)
        left = replay.ReplayBundleRecorder(self.runtime())
        right = replay.ReplayBundleRecorder(self.runtime())
        left_state = left.initialize([event_b, event_a], cut=0)
        right_state = right.initialize([event_a, event_b], cut=0)
        self.assertEqual(left_state.to_bytes(), right_state.to_bytes())
        self.assertEqual(
            canonical_json_bytes(left.sealed_bundle()),
            canonical_json_bytes(right.sealed_bundle()),
        )

    def test_available_time_boundary_and_automatic_release(self) -> None:
        now = observation("now", "OBS_A_MARKER", True, 0)
        future = observation("future", "OBS_B_MARKER", True, 2)

        with_future = replay.ReplayBundleRecorder(self.runtime())
        early_with_future = with_future.initialize([future, now], cut=0)
        without_future = replay.ReplayBundleRecorder(self.runtime())
        early_without_future = without_future.initialize([now], cut=0)
        self.assertEqual(early_with_future.to_bytes(), early_without_future.to_bytes())
        self.assertNotIn(
            "future",
            early_with_future.to_dict()["event_lineage"]["processed_event_ids"],
        )
        self.assertEqual(
            with_future.bundle["cuts"][0]["future_registered_event_ids"], ["future"]
        )

        later = with_future.update([], advance_to=2)
        self.assertIn("future", later.to_dict()["event_lineage"]["processed_event_ids"])

    def test_null_clock_time_uses_the_runtime_typed_cut_id(self) -> None:
        """The model-step wire keeps wall-clock null and carries time in cut_id."""

        recorder = replay.ReplayBundleRecorder(self.runtime())
        state = recorder.initialize([observation("now", "OBS_A_MARKER", True, 0)], cut=0)
        self.assertIsNone(state.to_dict()["as_of"]["clock_time"])
        self.assertEqual(state.to_dict()["as_of"]["cut_id"], "cut:0.0")
        advanced = recorder.update([], advance_to=1)
        self.assertEqual(advanced.to_dict()["as_of"]["cut_id"], "cut:1.0")

    def test_bundle_payload_tampering_fails_content_address_validation(self) -> None:
        event = observation("event-1", "OBS_A_MARKER", True, 0)
        recorder = replay.ReplayBundleRecorder(self.runtime())
        recorder.initialize([event], cut=0)
        bundle = recorder.sealed_bundle()
        tampered = copy.deepcopy(bundle)
        event_digest = tampered["event_index"]["event-1"]["event_digest"]
        tampered["event_blobs"][event_digest]["value"] = False
        tampered["integrity"]["bundle_digest"] = replay._bundle_digest(tampered)
        with self.assertRaisesRegex(replay.ReplayBundleError, "event blob digest mismatch"):
            replay.validate_bundle(tampered)

    def test_fresh_subprocess_replays_every_recursive_edge_and_cold_prefix(self) -> None:
        at_zero = observation("at-zero", "OBS_A_MARKER", True, 0)
        at_one = observation("at-one", "OBS_A_LOAD", 0.8, 1)
        at_two = observation("at-two", "OBS_B_MARKER", True, 2)
        recorder = replay.ReplayBundleRecorder(self.runtime())
        recorder.initialize([at_two, at_zero], cut=0)
        recorder.update([at_zero], advance_to=0)  # exact duplicate no-op
        recorder.update([at_one], advance_to=1)
        recorder.update([], advance_to=2)  # releases stored future event

        with tempfile.TemporaryDirectory() as directory:
            bundle_path = Path(directory) / "bundle.json"
            report_path = Path(directory) / "fresh_process_replay.json"
            recorder.save(bundle_path)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("event_ledger_replay.py")),
                    "verify",
                    "--bundle",
                    str(bundle_path),
                    "--model",
                    str(MODEL_PATH),
                    "--report",
                    str(report_path),
                ],
                cwd=STUDY_ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            if completed.returncode != 0:
                self.fail(
                    f"fresh verifier failed: stdout={completed.stdout}\n"
                    f"stderr={completed.stderr}"
                )
            report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(report["recursive_fresh_process_byte_exact"])
        self.assertTrue(report["cold_prefix_replay_byte_exact"])
        self.assertTrue(report["available_time_boundary_validated"])
        self.assertEqual(len(report["recursive_steps"]), 4)


if __name__ == "__main__":
    unittest.main()
