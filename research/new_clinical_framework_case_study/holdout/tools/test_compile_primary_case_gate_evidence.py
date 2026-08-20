from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


STUDY_ROOT = Path(__file__).resolve().parents[2]
TOOLS = STUDY_ROOT / "holdout/tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import compile_primary_case_gate_evidence as C
from producer_replay_verifier import build_invocation_descriptor, invocation_sha256
from validate_primary_holdout_protocol import _validate_schema_instance


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


class CompilePrimaryCaseEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "holdout/tools").mkdir(parents=True)
        evaluator_raw = (STUDY_ROOT / C.TOOL_REL).read_bytes()
        (self.root / C.TOOL_REL).write_bytes(evaluator_raw)
        self.tool_ref = {"path": C.TOOL_REL, "sha256": hashlib.sha256(evaluator_raw).hexdigest(), "bytes": len(evaluator_raw)}
        self.scoring = json.loads((STUDY_ROOT / "holdout/PRIMARY_HOLDOUT_SCORING_v1.json").read_text(encoding="utf-8"))
        self.scoring_path = self.root / "holdout/PRIMARY_HOLDOUT_SCORING_v1.json"
        self.scoring_path.write_bytes(canonical(self.scoring))
        self.seal_path = self.root / "holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json"
        self.seal_path.parent.mkdir(parents=True)
        self.seal_path.write_bytes(canonical({"bindings": {"primary_execution": {"primary_case_gate_evaluator": self.tool_ref}}}))
        self.manifest_path = self.root / "manifest.json"
        self.manifest_path.write_bytes(canonical({
            "schema_version": "ncf.primary-case-gate-evaluator-input.v1",
            "stage": "CASE_EVALUATION",
            "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR",
            "inputs": [],
        }))
        self.evaluation_path = self.root / "evaluation.json"
        self.evaluation = {
            "schema_version": "ncf.primary-case-gate-evaluation.v1",
            "produced_by": C.TOOL_REL,
            "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR",
            "evaluation_kind": "CASE_AND_COVERAGE",
            "input_manifest_digest": {"sha256": "0" * 64, "bytes": 1},
            "input_refs": [],
            "gate_results": [{
                "subject_kind": "GATE", "subject_id": "PL-DX-002", "computed_result": "PASS",
                "checks": [{"check_id": "x", "observed": True, "expected": True, "operator": "EQ", "passed": True}],
            }],
            "coverage_results": [],
            "integrity": {"all_input_refs_verified": True, "thresholds_loaded_from_frozen_scoring_contract": True, "screening_claims_used_as_oracle_truth": False, "final_diagnosis_or_terminal_outcome_consumed": False, "deterministic": True},
        }
        self.evaluation_path.write_bytes(canonical(self.evaluation))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def compile(self, **overrides):
        args = dict(
            evaluation_path=self.evaluation_path,
            manifest_path=self.manifest_path,
            scoring_path=self.scoring_path,
            seal_path=self.seal_path,
            subject_kind="GATE",
            subject_id="PL-DX-002",
        )
        args.update(overrides)
        return C.compile_evidence(self.root, **args)

    def test_positive_compilation_schema_and_invocation_hash(self):
        value = self.compile()
        schema = json.loads((STUDY_ROOT / "holdout/schemas/primary_gate_evidence.schema.json").read_text())
        def remove_property_names(node):
            if isinstance(node, dict):
                node.pop("propertyNames", None)
                for child in node.values():
                    remove_property_names(child)
            elif isinstance(node, list):
                for child in node:
                    remove_property_names(child)
        remove_property_names(schema)
        _validate_schema_instance(value, schema)
        policy = next(row for row in self.scoring["final_scorer_contract"]["evidence_producer_policy"]["sealed_automated_generators"] if row["producer_id"] == C.CASE_PRODUCER_ID)
        refs = {row["ref_id"]: row for row in value["source_artifact_refs"]}
        descriptor = build_invocation_descriptor(
            producer_id=C.CASE_PRODUCER_ID,
            tool_ref=value["producer"]["tool_ref"],
            replay_policy=policy["replay_contract"],
            replay_claim=value["producer"]["replay"],
            source_refs=refs,
            output_ref_id=value["producer"]["artifact_ref_id"],
        )
        self.assertEqual(value["producer"]["replay"]["invocation_sha256"], invocation_sha256(descriptor))
        self.assertEqual(value["producer"]["replay"]["check_args"], {"subcommand": "evaluate-case"})

    def test_result_check_inconsistency_rejected(self):
        bad = copy.deepcopy(self.evaluation)
        bad["gate_results"][0]["checks"][0]["passed"] = False
        self.evaluation_path.write_bytes(canonical(bad))
        with self.assertRaises(C.CompileError):
            self.compile()

    def test_wrong_subject_and_stage_rejected(self):
        with self.assertRaises(C.CompileError):
            self.compile(subject_id="PL-REPORT-001")
        bad_manifest = json.loads(self.manifest_path.read_text())
        bad_manifest["stage"] = "REPORT_CONSISTENCY"
        self.manifest_path.write_bytes(canonical(bad_manifest))
        with self.assertRaises(C.CompileError):
            self.compile()

    def test_wrong_sealed_tool_rejected(self):
        bad = {"bindings": {"primary_execution": {"primary_case_gate_evaluator": {**self.tool_ref, "sha256": "f" * 64}}}}
        self.seal_path.write_bytes(canonical(bad))
        with self.assertRaises(C.CompileError):
            self.compile()

    def test_report_producer_requires_report_stage_and_subject(self):
        self.evaluation["evaluation_kind"] = "REPORT_CONSISTENCY"
        self.evaluation["gate_results"][0]["subject_id"] = "PL-REPORT-001"
        self.evaluation_path.write_bytes(canonical(self.evaluation))
        manifest = json.loads(self.manifest_path.read_text())
        manifest["stage"] = "REPORT_CONSISTENCY"
        self.manifest_path.write_bytes(canonical(manifest))
        value = self.compile(subject_id="PL-REPORT-001")
        self.assertEqual(value["producer"]["producer_id"], C.REPORT_PRODUCER_ID)
        self.assertEqual(value["producer"]["replay"]["check_args"], {"subcommand": "evaluate-report"})


if __name__ == "__main__":
    unittest.main()
