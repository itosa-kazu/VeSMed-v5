from __future__ import annotations

import json
import copy
from pathlib import Path
import unittest

from prototype.benchmark import BenchmarkRunner, _digest
from prototype.candidates.temporal_ledger import TemporalEvidenceLedger
from prototype.isolated_benchmark import (
    ISOLATED_PROTOCOL,
    KNOWN_CANDIDATES,
    IsolatedBenchmarkRunner,
    run_isolated,
)
from prototype.workloads import candidate_view, load_workloads


STACK_CHEAT_SOURCE = r'''
from __future__ import annotations

import importlib
import inspect
from pathlib import Path
import sys

from prototype.contract import CapabilityResult, ResultStatus


class StackCheat:
    def __init__(self, track):
        self.track = track

    @property
    def manifest(self):
        return {
            "candidate_id": "stack-cheat",
            "version": "1",
            "formal_signature": ["malicious test fixture"],
            "execution_semantics": ["attempt oracle imports and stack inspection"],
            "companion_layers": [],
            "primitive_profile": {},
            "foreign_boundaries": [],
            "declared_query_capabilities": [],
            "failure_types": ["unsupported"],
        }

    def _probe(self):
        imports = {}
        for name in (
            "prototype.reference_models",
            "prototype.workloads",
            "prototype.benchmark",
            "prototype.isolated_benchmark",
            "tests.test_isolated_benchmark",
        ):
            try:
                importlib.import_module(name)
                imports[name] = "IMPORTED"
            except Exception as exc:
                imports[name] = "blocked:" + type(exc).__name__
        frames = [str(frame.filename).replace("\\", "/") for frame in inspect.stack()]
        files = sorted(
            str(path.relative_to(Path.cwd())).replace("\\", "/")
            for path in Path.cwd().rglob("*") if path.is_file()
        )
        modules = sorted(
            name for name in sys.modules
            if name.startswith("prototype.") or name.startswith("tests")
        )
        return {
            "import_attempts": imports,
            "stack_has_oracle": any(
                token in frame
                for frame in frames
                for token in ("benchmark.py", "reference_models.py", "workloads.py", "/tests/")
            ),
            "visible_files": files,
            "visible_modules": modules,
        }

    def _result(self):
        return CapabilityResult(
            status=ResultStatus.UNSUPPORTED,
            validation="valid",
            capability="unsupported",
            epistemic="not_applicable",
            coverage_status="out_of_model",
            identification="not_applicable",
            computation="not_applicable",
            diagnostics={"reason": "probe only", **self._probe()},
        )

    def ingest(self, artifact): return self._result()
    def retract(self, source_id, known_at): return self._result()
    def query(self, spec): return self._result()
    def register_module(self, module): return self._result()
    def explain(self, result_id): return self._result()
    def clean_rebuild(self):
        raise AssertionError("judge must not trust candidate.clean_rebuild")


def build_candidate(track):
    return StackCheat(track)
'''


class IsolatedBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workloads = load_workloads()

    def test_all_known_candidates_execute_through_function_api(self) -> None:
        workload = self.workloads["T12"]
        for candidate in KNOWN_CANDIDATES:
            with self.subTest(candidate=candidate):
                run = run_isolated(candidate, workload, timeout_seconds=30)
                self.assertFalse(run.harness_errors, run.harness_errors)
                self.assertTrue(run.calls)
                self.assertEqual(run.workload_id, "T12")
                # A benchmark failure is an observed candidate result, not a
                # process-isolation failure.
                self.assertNotEqual(run.verdict.classification, "HARNESS_ERROR")

    def test_sandbox_inventory_is_minimal_and_excludes_judge_modules(self) -> None:
        runner = IsolatedBenchmarkRunner("kernel")
        runner.run(self.workloads["T12"])
        inventory = set(runner.last_sandbox_inventory)
        self.assertIn("prototype/contract.py", inventory)
        self.assertIn("prototype/ir.py", inventory)
        self.assertIn("prototype/kernel.py", inventory)
        self.assertIn("prototype/isolated_worker.py", inventory)
        forbidden = {
            "prototype/benchmark.py",
            "prototype/isolated_benchmark.py",
            "prototype/workloads.py",
            "prototype/reference_models.py",
        }
        self.assertTrue(forbidden.isdisjoint(inventory), inventory)
        self.assertFalse(any(path.startswith("tests/") for path in inventory))
        self.assertFalse(any(path.startswith("results/") for path in inventory))

    def test_stdin_transcript_contains_public_view_digest_but_no_oracle(self) -> None:
        runner = IsolatedBenchmarkRunner("tel")
        runner.run(self.workloads["T12"])
        transcript = runner.last_worker_transcript
        self.assertIsNotNone(transcript)
        assert transcript is not None
        self.assertEqual(transcript["protocol"], ISOLATED_PROTOCOL)
        self.assertEqual(
            transcript["candidate_input_digest"],
            _digest(candidate_view(self.workloads["T12"])),
        )
        self.assertEqual(
            set(transcript),
            {
                "protocol",
                "candidate_id",
                "manifest_snapshot",
                "candidate_input_digest",
                "calls",
                "captures",
                "capture_inputs",
                "harness_errors",
            },
        )
        encoded = json.dumps(transcript, sort_keys=True)
        self.assertNotIn("oracle_view", encoded)
        self.assertNotIn("assertion_id", encoded)
        self.assertNotIn("reference_path", encoded)
        query_calls = [item for item in transcript["calls"] if item["op"] == "query"]
        self.assertTrue(query_calls)
        self.assertEqual(query_calls[0]["query_kind"], "project")
        self.assertNotIn("query_kind", query_calls[0]["result"]["diagnostics"])
        self.assertEqual(
            set(transcript["captures"]), set(transcript["capture_inputs"])
        )

    def test_worker_fails_closed_if_runner_only_key_crosses_stdin(self) -> None:
        runner = IsolatedBenchmarkRunner("tel")
        view = dict(candidate_view(self.workloads["T12"]))
        view["oracle_view"] = {"assertions": []}
        transcript = runner._execute_view(view)
        self.assertFalse(transcript["calls"])
        self.assertTrue(
            any("runner-only key" in item for item in transcript["harness_errors"]),
            transcript,
        )

    def test_stack_cheat_cannot_import_or_inspect_parent_oracle(self) -> None:
        runner = IsolatedBenchmarkRunner(
            "custom", custom_candidate_source=STACK_CHEAT_SOURCE
        )
        run = runner.run(self.workloads["T12"])
        self.assertFalse(run.harness_errors, run.harness_errors)
        query_calls = [call for call in run.calls if call.op == "query"]
        self.assertTrue(query_calls)
        diagnostic = query_calls[0].result["diagnostics"]
        self.assertFalse(diagnostic["stack_has_oracle"], diagnostic)
        self.assertTrue(
            all(value.startswith("blocked:") for value in diagnostic["import_attempts"].values()),
            diagnostic,
        )
        visible = set(diagnostic["visible_files"])
        self.assertNotIn("prototype/benchmark.py", visible)
        self.assertNotIn("prototype/workloads.py", visible)
        self.assertNotIn("prototype/reference_models.py", visible)
        self.assertFalse(any(path.startswith("tests/") for path in visible), visible)
        self.assertFalse(
            any(
                name in diagnostic["visible_modules"]
                for name in (
                    "prototype.benchmark",
                    "prototype.workloads",
                    "prototype.reference_models",
                )
            ),
            diagnostic,
        )
        # The cheat is still judged by the parent oracle and does not gain a
        # semantic pass merely by returning a well-typed refusal.
        self.assertEqual(run.verdict.hard, "fail")
        self.assertEqual(run.verdict.classification, "HONEST_UNSUPPORTED")
        semantic = [item for item in run.assertions if item.oracle_kind != "honesty"]
        self.assertTrue(semantic)
        self.assertTrue(all(not item.semantic_eligible for item in semantic))

    def test_python_confinement_blocks_known_absolute_oracle_path(self) -> None:
        # Import-path isolation alone is insufficient if candidate code already
        # knows a host path.  The worker's CPython audit hook must reject that
        # direct read before the custom candidate can manufacture a root.
        oracle_path = (
            Path(__file__).resolve().parent / "workloads" / "T" / "T12.json"
        )
        source = r'''
from __future__ import annotations
import json
from prototype.contract import CapabilityResult, ResultStatus

ORACLE_PATH = __ORACLE_PATH__

class AbsoluteReadProbe:
    def __init__(self, track): self.track = track
    @property
    def manifest(self):
        return {
            "candidate_id": "absolute-read-probe", "version": "1",
            "formal_signature": ["probe"], "execution_semantics": ["probe"],
            "companion_layers": [], "primitive_profile": {},
            "foreign_boundaries": [], "declared_query_capabilities": [],
            "failure_types": ["unsupported"],
        }
    def _result(self):
        read = False
        roots = []
        error = None
        try:
            with open(ORACLE_PATH, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            read = "oracle_view" in payload
            if read:
                roots = ["lab-source"]
        except Exception as exc:
            error = type(exc).__name__
        return CapabilityResult(
            status=ResultStatus.UNSUPPORTED,
            validation="valid", capability="unsupported",
            epistemic="not_applicable", coverage_status="out_of_model",
            identification="not_applicable", computation="not_applicable",
            evidence_witness={"root_sources": roots},
            diagnostics={"reason": "probe", "oracle_file_read": read, "error": error},
        )
    def ingest(self, artifact): return self._result()
    def retract(self, source_id, known_at): return self._result()
    def query(self, spec): return self._result()
    def register_module(self, module): return self._result()
    def explain(self, result_id): return self._result()
    def clean_rebuild(self): return self

def build_candidate(track): return AbsoluteReadProbe(track)
'''.replace("__ORACLE_PATH__", repr(str(oracle_path)))
        run = IsolatedBenchmarkRunner(
            "custom", custom_candidate_source=source
        ).run(self.workloads["T12"])
        self.assertFalse(run.harness_errors, run.harness_errors)
        query = next(call for call in run.calls if call.op == "query")
        self.assertFalse(query.result["diagnostics"]["oracle_file_read"])
        self.assertEqual(query.result["diagnostics"]["error"], "PermissionError")
        self.assertNotEqual(run.verdict.classification, "PASS")

    def test_isolated_judge_is_semantically_equal_to_in_process_runner(self) -> None:
        # T12 exercises runner-owned query_kind/capture_inputs; T24 exercises
        # the external mutation-journal clean rebuild.
        for workload_id in ("T12", "T24"):
            with self.subTest(workload_id=workload_id):
                workload = self.workloads[workload_id]
                in_process = BenchmarkRunner(TemporalEvidenceLedger).run(workload)
                isolated = IsolatedBenchmarkRunner("tel").run(workload)
                self.assertEqual(
                    [item.to_dict() for item in in_process.calls],
                    [item.to_dict() for item in isolated.calls],
                )
                self.assertEqual(in_process.captures, isolated.captures)
                self.assertEqual(
                    [item.to_dict() for item in in_process.assertions],
                    [item.to_dict() for item in isolated.assertions],
                )
                self.assertEqual(
                    in_process.verdict.to_dict(), isolated.verdict.to_dict()
                )
                self.assertEqual(in_process.harness_errors, isolated.harness_errors)

    def test_clean_rebuild_uses_fresh_provider_and_external_journal(self) -> None:
        runner = IsolatedBenchmarkRunner(
            "custom", custom_candidate_source=STACK_CHEAT_SOURCE
        )
        run = runner.run(self.workloads["T24"])
        self.assertFalse(run.harness_errors, run.harness_errors)
        operations = [call.op for call in run.calls]
        self.assertIn("rebuild_replay_ingest", operations)
        self.assertIn("rebuild_replay_retract", operations)
        receipt = next(call for call in run.calls if call.op == "clean_rebuild")
        self.assertTrue(receipt.result["diagnostics"]["external_replay"])
        self.assertEqual(receipt.result["capability"], "runner_replay")

    def test_no_hard_assertions_is_not_applicable_not_fail(self) -> None:
        workload = copy.deepcopy(self.workloads["T12"])
        workload["workload_id"] = "X-NO-HARD"
        workload["oracle_view"]["assertions"] = []
        run = IsolatedBenchmarkRunner("tel").run(workload)
        self.assertFalse(run.harness_errors, run.harness_errors)
        self.assertEqual(run.verdict.hard, "not_applicable")
        self.assertNotEqual(run.verdict.classification, "PASS")


if __name__ == "__main__":
    unittest.main()
