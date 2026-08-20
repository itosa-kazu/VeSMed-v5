from __future__ import annotations

import copy
import json
import unittest

from holdout.tools import primary_case_gate_evaluator as evaluator
from holdout.tools import primary_runtime_replay_executor as executor
from holdout.tools.test_primary_runtime_replay_executor import FullFixture, ROOT, artifact


def by_id(checks: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(row["check_id"]): row for row in checks}


class PrimaryCaseGateEvaluatorRuntimeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = FullFixture()
        cls.out = cls.fixture.path / "evaluator_runtime_integration"
        executor.execute_manifest(
            ROOT,
            cls.fixture.manifest_path,
            cls.out,
            preprimary_verifier=cls.fixture.verifier,
        )
        cls.runtime = json.loads((cls.out / "runtime_output.json").read_text(encoding="utf-8"))
        cls.mapped = json.loads((cls.out / "mapped_observation_consumption.json").read_text(encoding="utf-8"))
        cls.replay = json.loads((cls.out / "runtime_replay_seal.json").read_text(encoding="utf-8"))
        cls.refs = {
            "runtime_output": artifact(cls.out / "runtime_output.json"),
            "mapped_observation_consumption": artifact(cls.out / "mapped_observation_consumption.json"),
        }
        cls.events = {
            "source-event-alpha": {
                "event_id": "source-event-alpha",
                "opaque_event_id": "EV-00000001",
                "available_epoch": 0,
            },
            "source-event-beta": {
                "event_id": "source-event-beta",
                "opaque_event_id": "EV-00000002",
                "available_epoch": 2,
            },
        }

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def evaluate(self, runtime: dict[str, object]) -> dict[str, dict[str, object]]:
        _cuts, checks = evaluator._runtime_integrity_checks(
            self.refs,
            {
                "runtime_output": runtime,
                "mapped_observation_consumption": self.mapped,
                "runtime_replay_seal": self.replay,
            },
            self.events,
        )
        return by_id(checks)

    def test_exact_raw_executor_outputs_pass_every_runtime_integrity_check(self) -> None:
        checks = self.evaluate(copy.deepcopy(self.runtime))
        self.assertTrue(all(row["passed"] for row in checks.values()), checks)

    def test_future_leak_cut_seal_parent_and_score_tampering_fail_closed(self) -> None:
        state_tamper = copy.deepcopy(self.runtime)
        state_tamper["cuts"][0]["canonical_state"]["integrity"]["state_hash"] = "a" * 64
        checks = self.evaluate(state_tamper)
        self.assertFalse(checks["all_heads_consume_exact_canonical_state"]["passed"])

        leaked = copy.deepcopy(self.runtime)
        leaked["cuts"][0]["processed_event_ids"].append("EV-00000002")
        leaked["cuts"][0]["new_event_ids"].append("EV-00000002")
        leaked["cuts"][0]["future_registered_event_ids"] = []
        checks = self.evaluate(leaked)
        self.assertFalse(checks["future_events_withheld_until_available_cut"]["passed"])

        reordered = copy.deepcopy(self.runtime)
        reordered["cuts"][1]["processed_event_ids"].reverse()
        checks = self.evaluate(reordered)
        self.assertFalse(checks["future_events_withheld_until_available_cut"]["passed"])

        cut_tamper = copy.deepcopy(self.runtime)
        cut_tamper["cuts"][0]["sealed_before_next_cut_sha256"] = "0" * 64
        checks = self.evaluate(cut_tamper)
        self.assertFalse(checks["cut_seals_and_parent_chain_recompute_exactly"]["passed"])
        self.assertFalse(checks["every_cut_and_prospective_score_exactly_bound"]["passed"])

        parent_tamper = copy.deepcopy(self.runtime)
        parent_tamper["cuts"][1]["parent_cut_seal_sha256"] = "f" * 64
        checks = self.evaluate(parent_tamper)
        self.assertFalse(checks["cut_seals_and_parent_chain_recompute_exactly"]["passed"])
        self.assertFalse(checks["every_cut_and_prospective_score_exactly_bound"]["passed"])

        score_tamper = copy.deepcopy(self.runtime)
        score_tamper["prospective_scores"][0]["model"]["bounded_log_score"] -= 1.0
        checks = self.evaluate(score_tamper)
        self.assertTrue(checks["cut_seals_and_parent_chain_recompute_exactly"]["passed"])
        self.assertFalse(checks["every_cut_and_prospective_score_exactly_bound"]["passed"])


if __name__ == "__main__":
    unittest.main()
