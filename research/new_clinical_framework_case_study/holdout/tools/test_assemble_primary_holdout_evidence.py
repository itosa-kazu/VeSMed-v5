from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parent
STUDY = TOOLS.parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import assemble_primary_holdout_evidence as A
from validate_primary_holdout_protocol import _validate_schema_instance


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(A.canonical_json_bytes(value))


def ref(root: Path, path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


class AssemblePrimaryHoldoutEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "holdout/tools").mkdir(parents=True)
        for rel in (A.STRUCTURAL_TOOL_REL, A.EVENT_TOOL_REL, A.CASE_TOOL_REL):
            dst = self.root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes((STUDY / rel).read_bytes())
        self.gates = json.loads((STUDY / A.GATES_REL).read_text(encoding="utf-8"))
        self.scoring = json.loads((STUDY / A.SCORING_REL).read_text(encoding="utf-8"))
        write_json(self.root / A.GATES_REL, self.gates)
        write_json(self.root / A.SCORING_REL, self.scoring)
        self.seal_path = self.root / A.COMBINED_SEAL_REL
        self.seal = {
            "payload_sha256": "a" * 64,
            "bindings": {"primary_execution": {
                "structural_gate_harness": ref(self.root, self.root / A.STRUCTURAL_TOOL_REL),
                "event_ledger_replay": ref(self.root, self.root / A.EVENT_TOOL_REL),
                "primary_case_gate_evaluator": ref(self.root, self.root / A.CASE_TOOL_REL),
            }},
        }
        write_json(self.seal_path, self.seal)
        structural_allowed = next(row for row in self.scoring["final_scorer_contract"]["evidence_producer_policy"]["sealed_automated_generators"] if row["producer_id"] == "structural-gate-harness-v1")["allowed_subjects"]["GATE"]
        self.structural = self.root / "run/structural_gate_results.json"
        write_json(self.structural, {
            "schema_version": A.STRUCTURAL_SCHEMA,
            "produced_by": A.STRUCTURAL_TOOL_REL,
            "contract_id": "NCF-PERFECT-LANDING-GATES", "contract_version": "1.1.0",
            "architecture_version": "NCF-ARCH-1.0.0", "generated_at": "2026-07-21T00:00:00Z",
            "case_blind": True, "scope": {}, "runtime_binding": {},
            "gate_results": [{"gate_id": item, "result": "PASS"} for item in structural_allowed],
            "architecture_gate_results": [], "overall_status": "PASS", "evidence_manifest": [],
        })
        self.event_bundle = self.root / "run/event_bundle.json"
        self.model = self.root / "run/model.json"
        write_json(self.event_bundle, {"schema_version": "ncf.holdout.event-ledger-replay-bundle.v1"})
        write_json(self.model, {"schema_version": "new-clinical-runtime.model.v2.0"})
        self.event_report = self.root / "run/event_report.json"
        write_json(self.event_report, {
            "schema_version": A.EVENT_SCHEMA, "status": "PASS",
            "recursive_fresh_process_byte_exact": True, "cold_prefix_replay_byte_exact": True,
            "cold_full_history_replay_byte_exact": True, "deterministic_event_order_validated": True,
            "available_time_boundary_validated": True,
        })
        self.closed_artifacts = []
        for name, data_class in (("runtime.json", "runtime_output"), ("replay.json", "replay_seal"), ("consumption.json", "mapped_observation_consumption")):
            path = self.root / "run" / name
            write_json(path, {"schema_version": name})
            self.closed_artifacts.append({**ref(self.root, path), "data_class": data_class, "schema_id": f"ncf.{data_class}.v1"})
        self.all_sealed = self.root / "run/all_sealed.json"
        write_json(self.all_sealed, {
            "schema_version": A.ALL_SEALED_SCHEMA, "evaluator_run_id": "RUN-a",
            "replay_sealed": True, "oracle_contents_included": False,
            "artifacts": self.closed_artifacts,
        })
        self.case_manifest = self.root / "run/case_manifest.json"
        write_json(self.case_manifest, {
            "schema_version": A.CASE_MANIFEST_SCHEMA, "stage": "CASE_EVALUATION",
            "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR",
            "inputs": [
                {"ref_id": "seal", "role": "preprimary_seal", **ref(self.root, self.seal_path)},
                {"ref_id": "closure", "role": "all_sealed_artifacts_after_replay", **ref(self.root, self.all_sealed)},
            ],
        })
        checks = lambda tag: [{"check_id": f"{tag}-check", "observed": True, "expected": True, "operator": "EQ", "passed": True}]
        self.case_eval = self.root / "run/case_eval.json"
        write_json(self.case_eval, {
            "schema_version": A.CASE_EVALUATION_SCHEMA, "produced_by": A.CASE_TOOL_REL,
            "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR",
            "evaluation_kind": "CASE_AND_COVERAGE", "input_manifest_digest": {"sha256": "0" * 64, "bytes": 1}, "input_refs": [],
            "gate_results": [{"subject_kind": "GATE", "subject_id": item, "computed_result": "PASS", "checks": checks(item)} for item in A.CASE_GATE_IDS],
            "coverage_results": [{"subject_kind": "COMPLEX_COVERAGE", "subject_id": item, "computed_result": "PASS", "checks": checks(item)} for item in A.REQUIRED_COVERAGE[1:]],
            "integrity": {"all_input_refs_verified": True, "thresholds_loaded_from_frozen_scoring_contract": True, "screening_claims_used_as_oracle_truth": False, "final_diagnosis_or_terminal_outcome_consumed": False, "deterministic": True},
        })
        self.non_dir = self.root / "assembled/nonreport"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def nonreport(self):
        with patch.object(A, "_verify_preprimary", return_value=self.seal):
            return A.assemble_nonreport(
                self.root, structural_results=self.structural, event_report=self.event_report,
                event_bundle=self.event_bundle, model=self.model, case_evaluation=self.case_eval,
                case_manifest=self.case_manifest, all_sealed_inventory=self.all_sealed,
                combined_seal=self.seal_path, output_dir=self.non_dir,
            )

    def report_fixture(self):
        manifest = self.root / "run/report_manifest.json"
        write_json(manifest, {
            "schema_version": A.CASE_MANIFEST_SCHEMA, "stage": "REPORT_CONSISTENCY",
            "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR", "inputs": [],
        })
        evaluation = self.root / "run/report_eval.json"
        write_json(evaluation, {
            "schema_version": A.CASE_EVALUATION_SCHEMA, "produced_by": A.CASE_TOOL_REL,
            "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR",
            "evaluation_kind": "REPORT_CONSISTENCY", "input_manifest_digest": {"sha256": "0" * 64, "bytes": 1}, "input_refs": [],
            "gate_results": [{"subject_kind": "GATE", "subject_id": A.REPORT_GATE_ID, "computed_result": "PASS", "checks": [{"check_id": "report", "observed": True, "expected": True, "operator": "EQ", "passed": True}]}],
            "coverage_results": [], "integrity": {"all_input_refs_verified": True, "thresholds_loaded_from_frozen_scoring_contract": True, "screening_claims_used_as_oracle_truth": False, "final_diagnosis_or_terminal_outcome_consumed": False, "deterministic": True},
        })
        return evaluation, manifest

    def test_two_stage_pipeline_emits_exact_30_and_7(self):
        non = self.nonreport()
        non_doc = json.loads(non["gate_bundle"].read_text())
        cov_doc = json.loads(non["coverage_bundle"].read_text())
        self.assertEqual(len(non_doc["gate_results"]), 29)
        self.assertEqual(len(cov_doc["checks"]), 7)
        report_eval, report_manifest = self.report_fixture()
        with patch.object(A, "_verify_preprimary", return_value=self.seal):
            final = A.assemble_final(
                self.root, nonreport_gates=non["gate_bundle"], coverage_bundle=non["coverage_bundle"],
                nonreport_assembly=non["assembly_manifest"], report_evaluation=report_eval,
                report_manifest=report_manifest, all_sealed_inventory=self.all_sealed,
                combined_seal=self.seal_path, output_dir=self.root / "assembled/final",
            )
        final_doc = json.loads(final["gate_bundle"].read_text())
        self.assertEqual([row["gate_id"] for row in final_doc["gate_results"]], [row["id"] for row in self.gates["gates"]])
        self.assertEqual(len(final_doc["gate_results"]), 30)
        self.assertTrue(all(row["result"] == "PASS" for row in final_doc["gate_results"]))
        assembly = json.loads(final["assembly_manifest"].read_text())
        self.assertEqual(assembly["phase"], "FINAL")
        self.assertEqual(len(assembly["evidence_files"]), 37)

    def test_nonreport_outputs_validate_against_frozen_schemas(self):
        result = self.nonreport()
        pairs = (
            (result["gate_bundle"], STUDY / "holdout/schemas/primary_gate_evidence_bundle.schema.json"),
            (result["coverage_bundle"], STUDY / "holdout/schemas/primary_complex_case_coverage_bundle.schema.json"),
            (result["assembly_manifest"], STUDY / "holdout/schemas/primary_final_evidence_assembly.schema.json"),
        )
        for value_path, schema_path in pairs:
            with self.subTest(schema=schema_path.name):
                _validate_schema_instance(json.loads(value_path.read_text()), json.loads(schema_path.read_text()))

    def test_all_sealed_hash_mutation_fails_closed(self):
        bad = json.loads(self.all_sealed.read_text())
        bad["artifacts"][0]["sha256"] = "0" * 64
        write_json(self.all_sealed, bad)
        # Rebind only the inventory itself; inner artifact remains corrupt.
        manifest = json.loads(self.case_manifest.read_text())
        manifest["inputs"][1].update(ref(self.root, self.all_sealed))
        write_json(self.case_manifest, manifest)
        with self.assertRaises(A.AssemblyError):
            self.nonreport()

    def test_case_manifest_must_bind_combined_seal_and_all_sealed(self):
        bad = json.loads(self.case_manifest.read_text())
        bad["inputs"][0]["sha256"] = "0" * 64
        write_json(self.case_manifest, bad)
        with self.assertRaises(A.AssemblyError):
            self.nonreport()

    def test_missing_or_duplicate_structural_gate_fails_closed(self):
        for mode in ("missing", "duplicate"):
            with self.subTest(mode=mode):
                original = json.loads(self.structural.read_text())
                bad = copy.deepcopy(original)
                if mode == "missing":
                    bad["gate_results"].pop()
                else:
                    bad["gate_results"].append(copy.deepcopy(bad["gate_results"][0]))
                write_json(self.structural, bad)
                with self.assertRaises(A.AssemblyError):
                    self.nonreport()
                write_json(self.structural, original)

    def test_case_or_report_incomplete_status_cannot_be_assembled(self):
        bad = json.loads(self.case_eval.read_text())
        bad["gate_results"][0]["computed_result"] = "EVIDENCE_MISSING"
        write_json(self.case_eval, bad)
        with self.assertRaises(Exception):
            self.nonreport()


if __name__ == "__main__":
    unittest.main()
