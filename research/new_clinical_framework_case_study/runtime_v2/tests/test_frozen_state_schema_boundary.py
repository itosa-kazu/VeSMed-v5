from __future__ import annotations

import copy
from pathlib import Path
import unittest

from runtime_v2 import RuntimeV2, SharedPatientState, architecture_state_hash


ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "examples" / "neutral_factorial_model.json"


def rehash(wire: dict) -> dict:
    wire["integrity"]["state_hash"] = architecture_state_hash(wire)
    return wire


class FrozenStateSchemaBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.runtime = RuntimeV2.from_json(MODEL_PATH)
        self.valid = self.runtime.initialize([], cut=0).to_dict()

    def test_valid_state_deserializes(self) -> None:
        self.assertIsNone(self.valid["as_of"]["clock_time"])
        restored = SharedPatientState.from_dict(self.valid)
        self.assertEqual(restored.to_dict(), self.valid)

    def test_numeric_model_time_cannot_masquerade_as_date_time(self) -> None:
        wire = copy.deepcopy(self.valid)
        wire["as_of"]["clock_time"] = "0.0"
        with self.assertRaisesRegex(ValueError, "RFC3339 date-time"):
            SharedPatientState.from_dict(rehash(wire))

    def test_nested_additional_property_is_rejected_at_deserialization(self) -> None:
        wire = copy.deepcopy(self.valid)
        wire["as_of"]["undeclared_nested_field"] = "forged"
        with self.assertRaisesRegex(ValueError, "additional property"):
            SharedPatientState.from_dict(rehash(wire))

    def test_missing_nested_required_property_is_rejected_at_deserialization(self) -> None:
        wire = copy.deepcopy(self.valid)
        del wire["local_states"][0]["mode_posterior"]
        with self.assertRaisesRegex(ValueError, "missing required"):
            SharedPatientState.from_dict(rehash(wire))

    def test_probability_outside_domain_is_rejected_at_deserialization(self) -> None:
        wire = copy.deepcopy(self.valid)
        wire["local_states"][0]["mode_posterior"][0]["probability"] = 1.5
        with self.assertRaisesRegex(ValueError, "above maximum"):
            SharedPatientState.from_dict(rehash(wire))

    def test_unique_items_contract_is_enforced_at_deserialization(self) -> None:
        wire = copy.deepcopy(self.valid)
        process_id = wire["active_process_posterior"]["process_marginals"][0]["process_id"]
        wire["active_process_posterior"]["process_marginals"][0][
            "supporting_factor_ids"
        ] = ["FACTOR-X", "FACTOR-X"]
        with self.assertRaisesRegex(ValueError, "not unique"):
            SharedPatientState.from_dict(rehash(wire))


if __name__ == "__main__":
    unittest.main()
