from __future__ import annotations

import sys
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from compile_availability_epochs import AvailabilityError, SCHEMA_VERSION, compile_ledger


def event(event_id: str, evidence: dict) -> dict:
    return {
        "source_event_id": event_id,
        "availability_evidence": evidence,
        "runtime_event": {"event_id": event_id, "event_type": "ObservationAvailable"},
    }


class AvailabilityCompilerTests(unittest.TestCase):
    def ledger(self, events):
        return {
            "schema_version": SCHEMA_VERSION,
            "publication_order_used_as_clinical_availability": False,
            "events": events,
        }

    def test_interval_releases_only_at_latest_possible_epoch(self) -> None:
        result = compile_ledger(self.ledger([event("e1", {"kind": "INTERVAL", "earliest_epoch": 2, "latest_epoch": 5})]))
        self.assertEqual(result["released_events"][0]["guaranteed_available_epoch"], 5.0)
        self.assertEqual(result["released_events"][0]["runtime_event"]["available_at"], 5.0)

    def test_unknown_and_unbounded_partial_order_are_withheld(self) -> None:
        result = compile_ledger(self.ledger([
            event("u", {"kind": "UNKNOWN"}),
            event("p", {"kind": "PARTIAL_ORDER", "after_event_ids": ["x"]}),
        ]))
        self.assertEqual(result["released_events"], [])
        self.assertEqual([row["source_event_id"] for row in result["withheld_events"]], ["p", "u"])
        self.assertTrue(all(row["measurement_uncertainty_required"] for row in result["withheld_events"]))

    def test_reported_batch_cannot_be_split(self) -> None:
        with self.assertRaisesRegex(AvailabilityError, "split across cuts"):
            compile_ledger(self.ledger([
                event("a", {"kind": "REPORTED_BATCH", "batch_id": "b", "latest_epoch": 2}),
                event("b", {"kind": "REPORTED_BATCH", "batch_id": "b", "latest_epoch": 3}),
            ]))

    def test_publication_order_is_forbidden(self) -> None:
        ledger = self.ledger([])
        ledger["publication_order_used_as_clinical_availability"] = True
        with self.assertRaisesRegex(AvailabilityError, "publication order"):
            compile_ledger(ledger)

    def test_prepopulated_available_at_is_forbidden(self) -> None:
        row = event("e", {"kind": "EXACT", "exact_epoch": 1})
        row["runtime_event"]["available_at"] = 0
        with self.assertRaisesRegex(AvailabilityError, "pre-populates"):
            compile_ledger(self.ledger([row]))

    def test_duplicate_source_event_id_is_forbidden(self) -> None:
        row = event("e", {"kind": "EXACT", "exact_epoch": 1})
        with self.assertRaisesRegex(AvailabilityError, "duplicate"):
            compile_ledger(self.ledger([row, row]))

    def test_empty_source_event_id_is_forbidden(self) -> None:
        with self.assertRaisesRegex(AvailabilityError, "missing source_event_id"):
            compile_ledger(self.ledger([event("", {"kind": "EXACT", "exact_epoch": 1})]))


if __name__ == "__main__":
    unittest.main()
