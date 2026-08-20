from __future__ import annotations

import json
import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from holdout.tools.structural_gate_harness import (
    ARCHITECTURE_GATES,
    STRUCTURAL_PL_GATES,
    Harness,
    main,
    validate_evidence_envelope,
)


class StructuralGateHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp = tempfile.TemporaryDirectory()
        cls.output = Path(cls.temp.name) / "evidence"
        cls.harness = Harness(cls.output, generated_at="2026-07-20T00:00:00Z")
        cls.result = cls.harness.run()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp.cleanup()

    def test_exactly_g01_through_g17_are_covered(self) -> None:
        rows = self.result["architecture_gate_results"]
        self.assertEqual([row["gate_id"] for row in rows], ARCHITECTURE_GATES)
        self.assertTrue(all(row["contributing_pl_gates"] for row in rows))

    def test_every_required_machine_evidence_file_exists_and_validates(self) -> None:
        for gate_id in STRUCTURAL_PL_GATES:
            for filename in self.harness.gate_contracts[gate_id]["required_evidence"]:
                path = self.output / filename
                self.assertTrue(path.exists(), f"missing {gate_id}: {filename}")
                if filename.endswith(".json"):
                    row = json.loads(path.read_text(encoding="utf-8"))
                    validate_evidence_envelope(row)

    def test_previously_unsupported_claims_have_decisive_green_witnesses(self) -> None:
        # Different factor IDs derived from one public result are grouped by
        # their common source and therefore cannot multiply evidence.
        common_parent = json.loads((self.output / "common_parent_ablation.json").read_text(encoding="utf-8"))
        self.assertEqual(common_parent["status"], "PASS")
        self.assertTrue(common_parent["assertions"][0]["passed"])
        # OOD evidence must also surface an explicit partial-answer marker.
        forced = json.loads((self.output / "forced_choice_audit.json").read_text(encoding="utf-8"))
        self.assertEqual(forced["status"], "PASS")
        self.assertTrue(forced["assertions"][0]["passed"])
        # Model-bound control-plane edits are authoritative when they change a
        # head or are rejected fail-closed; silent ignore would fail.
        wire = json.loads((self.output / "field_consumption_trace.json").read_text(encoding="utf-8"))
        self.assertEqual(wire["status"], "PASS")
        self.assertTrue(all(row["passed"] is True for row in wire["assertions"]))
        non_regression = json.loads((self.output / "refinement_non_regression.json").read_text(encoding="utf-8"))
        self.assertEqual(non_regression["status"], "PASS")
        self.assertTrue(non_regression["assertions"][0]["passed"])
        self.assertEqual(self.result["overall_status"], "PASS")

    def test_fresh_process_and_refinement_witnesses_are_real(self) -> None:
        fresh = json.loads((self.output / "fresh_process_replay.json").read_text(encoding="utf-8"))
        self.assertEqual(fresh["status"], "PASS")
        self.assertTrue(fresh["assertions"][0]["passed"])
        refine = json.loads((self.output / "refinement_trigger.json").read_text(encoding="utf-8"))
        self.assertEqual(refine["status"], "PASS")
        self.assertEqual(refine["outputs"]["report"]["status"], "REFINED")

    def test_cli_replay_is_byte_exact_across_output_directories(self) -> None:
        generated_at = "2026-07-20T00:00:00Z"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outputs = [root / "first", root / "nested" / "second"]
            snapshots: list[dict[str, bytes]] = []
            for output in outputs:
                with contextlib.redirect_stdout(io.StringIO()):
                    exit_code = main(
                        [
                            "--output",
                            str(output),
                            "--generated-at",
                            generated_at,
                        ]
                    )
                self.assertEqual(exit_code, 0)
                snapshots.append(
                    {
                        path.relative_to(output).as_posix(): path.read_bytes()
                        for path in sorted(output.rglob("*"))
                        if path.is_file()
                    }
                )

            self.assertEqual(snapshots[0], snapshots[1])
            command = snapshots[0]["full_replay_command.txt"].decode("utf-8")
            self.assertIn('--output "<OUTPUT_DIR>"', command)
            self.assertIn(f'--generated-at "{generated_at}"', command)
            self.assertNotIn(str(outputs[0].resolve()), command)
            result = json.loads(snapshots[0]["structural_gate_results.json"])
            self.assertEqual(result["generated_at"], generated_at)


if __name__ == "__main__":
    unittest.main()
