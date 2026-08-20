"""Case-neutral fresh-replay tests for the post-replay closure verifier."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from test_compile_all_sealed_artifacts_after_replay import PostReplayFixture, _write
from verify_all_sealed_artifacts_after_replay import VerificationError, verify


class VerifierTests(unittest.TestCase):
    def test_fresh_replay_and_final_role_crosscheck(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = PostReplayFixture(Path(temp))
            fx.finalize_evaluator_and_scorer()
            with patch(
                "verify_all_sealed_artifacts_after_replay.validate_role_manifest_set",
                return_value={"status": "PASS", "role_count": 8},
            ):
                report, raw = verify(
                    fx.root, fx.compiler_input_path, fx.closure_path,
                    fx.base.aggregate_path,
                )
            self.assertEqual(report["status"], "PASS")
            self.assertTrue(report["fresh_replay"]["byte_exact"])
            self.assertTrue(all(report["checks"].values()))
            self.assertGreater(len(raw), 100)

    def test_rejects_scorer_closure_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = PostReplayFixture(Path(temp))
            fx.finalize_evaluator_and_scorer()
            scorer = fx.base.manifest("scorer_auditor")
            row = next(item for item in scorer["inputs"] if item["data_class"] == "all_sealed_artifacts_after_replay")
            row["sha256"] = "f" * 64
            fx.base.write_manifest("scorer_auditor", scorer)
            aggregate = fx.base.read_json(fx.base.aggregate_path)
            aggregate_row = next(item for item in aggregate["manifests"] if item["role"] == "scorer_auditor")
            aggregate_row.update(fx.base.ref(fx.base.manifest_paths["scorer_auditor"]))
            _write(fx.base.aggregate_path, aggregate)
            with patch(
                "verify_all_sealed_artifacts_after_replay.validate_role_manifest_set",
                return_value={"status": "PASS", "role_count": 8},
            ):
                with self.assertRaisesRegex(VerificationError, "scorer does not consume"):
                    verify(fx.root, fx.compiler_input_path, fx.closure_path, fx.base.aggregate_path)

    def test_rejects_final_upstream_manifest_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = PostReplayFixture(Path(temp))
            fx.finalize_evaluator_and_scorer()
            aggregate = fx.base.read_json(fx.base.aggregate_path)
            row = next(item for item in aggregate["manifests"] if item["role"] == "scout")
            row["run_id"] = "substituted-scout"
            _write(fx.base.aggregate_path, aggregate)
            with patch(
                "verify_all_sealed_artifacts_after_replay.validate_role_manifest_set",
                return_value={"status": "PASS", "role_count": 8},
            ):
                with self.assertRaisesRegex(VerificationError, "identity mismatch|upstream manifests"):
                    verify(fx.root, fx.compiler_input_path, fx.closure_path, fx.base.aggregate_path)

    def test_rejects_nonpassing_full_manifest_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = PostReplayFixture(Path(temp))
            fx.finalize_evaluator_and_scorer()
            with patch(
                "verify_all_sealed_artifacts_after_replay.validate_role_manifest_set",
                return_value={"status": "FAIL", "role_count": 8},
            ):
                with self.assertRaisesRegex(VerificationError, "did not validate"):
                    verify(fx.root, fx.compiler_input_path, fx.closure_path, fx.base.aggregate_path)


if __name__ == "__main__":
    unittest.main()
