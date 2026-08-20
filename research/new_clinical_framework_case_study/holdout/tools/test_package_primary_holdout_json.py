from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


TOOLS = Path(__file__).resolve().parent
STUDY = TOOLS.parents[1]
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import package_primary_holdout_json as P


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(P.canonical(value))


def ref(root: Path, path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


class PrimaryJsonEvidencePackagerTests(unittest.TestCase):
    """Exercise the independent JSON packager without running any producer."""

    COPIED = (
        P.INPUT_SCHEMA,
        P.RECEIPT_SCHEMA,
        P.EVENT_SCHEMA,
        P.STRUCT_SCHEMA,
        P.EVAL_SCHEMA,
        P.MANIFEST_SCHEMA,
        P.EVIDENCE_SCHEMA,
        P.GATE_BUNDLE_SCHEMA,
        P.COVERAGE_SCHEMA,
        P.STRUCT_TOOL,
        P.EVENT_TOOL,
        P.EVAL_TOOL,
        P.THIS_TOOL,
    )

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for relative in self.COPIED:
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(STUDY / relative, destination)

        self.gates = json.loads((STUDY / P.GATES).read_text(encoding="utf-8"))
        self.scoring = json.loads((STUDY / P.SCORING).read_text(encoding="utf-8"))
        policy_rows = self.scoring["final_scorer_contract"]["evidence_producer_policy"]["sealed_automated_generators"]
        by_id = {row["producer_id"]: row for row in policy_rows}

        # Frozen routing under test: 23 structural subjects (including the
        # structural shadow row for PL-LED-002), six case subjects including
        # PL-IND-001, one report subject.  Fresh replay remains authoritative
        # for PL-LED-002, so PRE_REPORT contains exactly 22+1+6 = 29 rows.
        structural_ids = by_id["structural-gate-harness-v1"]["allowed_subjects"]["GATE"]
        structural_ids.remove("PL-IND-001")
        case_ids = by_id["primary-case-gate-evaluator-case-v1"]["allowed_subjects"]["GATE"]
        case_ids.insert(0, "PL-IND-001")
        self.assertEqual(len(structural_ids), 23)
        self.assertEqual(len(case_ids), 6)

        write_json(self.root / P.GATES, self.gates)
        write_json(self.root / P.SCORING, self.scoring)

        self.seal_path = self.root / P.SEAL
        self.seal = {
            "payload_sha256": "a" * 64,
            "bindings": {
                "primary_execution": {
                    "structural_gate_harness": ref(self.root, self.root / P.STRUCT_TOOL),
                    "event_ledger_replay": ref(self.root, self.root / P.EVENT_TOOL),
                    "primary_case_gate_evaluator": ref(self.root, self.root / P.EVAL_TOOL),
                }
            },
        }
        write_json(self.seal_path, self.seal)

        self.structural = self.root / "run/structural.json"
        write_json(self.structural, {
            "schema_version": "ncf.structural-gate-results.v1",
            "produced_by": P.STRUCT_TOOL,
            "contract_id": "NCF-PERFECT-LANDING-GATES",
            "contract_version": "1.1.0",
            "architecture_version": "NCF-ARCH-1.0.0",
            "generated_at": "2026-07-21T00:00:00Z",
            "case_blind": True,
            "scope": {},
            "runtime_binding": {},
            "gate_results": [{"gate_id": item, "result": "PASS"} for item in structural_ids],
            "architecture_gate_results": [{} for _ in range(17)],
            "overall_status": "PASS",
            "evidence_manifest": [],
        })

        self.bundle = self.root / "run/event_bundle.json"
        self.model = self.root / "run/model.json"
        write_json(self.bundle, {"schema_version": "ncf.holdout.event-ledger-replay-bundle.v1"})
        write_json(self.model, {"schema_version": "new-clinical-runtime.model.v2.0"})
        self.event = self.root / "run/event_report.json"
        write_json(self.event, {
            "schema_version": "ncf.holdout.fresh-process-replay-report.v1",
            "status": "PASS",
            "bundle_digest": "1" * 64,
            "model_digest": "2" * 64,
            "recursive_fresh_process_byte_exact": True,
            "cold_prefix_replay_byte_exact": True,
            "cold_full_history_replay_byte_exact": True,
            "deterministic_event_order_validated": True,
            "available_time_boundary_validated": True,
            "recursive_steps": [],
            "cold_prefixes": [],
            "future_exclusion_by_cut": [],
            "final_binding": {},
            "report_digest": "3" * 64,
        })

        self.case_manifest = self._evaluator_manifest("CASE_EVALUATION", "case_manifest.json")
        case_policy = by_id["primary-case-gate-evaluator-case-v1"]["allowed_subjects"]
        self.case_eval = self.root / "run/case_eval.json"
        write_json(self.case_eval, self._evaluation(
            "CASE_AND_COVERAGE", self.case_manifest,
            case_policy["GATE"], case_policy["COMPLEX_COVERAGE"],
        ))
        self.pre_manifest = self.root / "run/pre_packager_manifest.json"
        write_json(self.pre_manifest, {
            "schema_version": "ncf.primary-json-evidence-packager-input.v1",
            "phase": "PRE_REPORT",
            "inputs": self._base_refs(),
        })

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _evaluator_manifest(self, stage: str, name: str) -> Path:
        items = []
        roles = ("gate_contract", "scoring_contract", "preprimary_seal", "audit_report")
        for index, role in enumerate(roles):
            path = self.root / f"run/{name}.input-{index}.json"
            write_json(path, {"fixture": index})
            items.append({"ref_id": f"input_{index}", "role": role, **ref(self.root, path)})
        path = self.root / f"run/{name}"
        write_json(path, {
            "schema_version": "ncf.primary-case-gate-evaluator-input.v1",
            "stage": stage,
            "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR",
            "inputs": items,
        })
        return path

    @staticmethod
    def _result(kind: str, subject: str) -> dict[str, object]:
        return {
            "subject_kind": kind,
            "subject_id": subject,
            "computed_result": "PASS",
            "checks": [{
                "check_id": f"{subject}.fixed",
                "observed": True,
                "expected": True,
                "operator": "EQ",
                "passed": True,
            }],
        }

    def _evaluation(self, kind: str, manifest: Path, gates: list[str], coverage: list[str]) -> dict[str, object]:
        raw = manifest.read_bytes()
        manifest_doc = json.loads(raw)
        return {
            "schema_version": "ncf.primary-case-gate-evaluation.v1",
            "produced_by": P.EVAL_TOOL,
            "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR",
            "evaluation_kind": kind,
            "input_manifest_digest": {"sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)},
            "input_refs": manifest_doc["inputs"],
            "gate_results": [self._result("GATE", item) for item in gates],
            "coverage_results": [self._result("COMPLEX_COVERAGE", item) for item in coverage],
            "integrity": {
                "all_input_refs_verified": True,
                "thresholds_loaded_from_frozen_scoring_contract": True,
                "screening_claims_used_as_oracle_truth": False,
                "final_diagnosis_or_terminal_outcome_consumed": False,
                "deterministic": True,
            },
        }

    def _base_refs(self) -> dict[str, dict[str, object]]:
        return {
            "structural_results": ref(self.root, self.structural),
            "event_replay_report": ref(self.root, self.event),
            "event_replay_bundle": ref(self.root, self.bundle),
            "model": ref(self.root, self.model),
            "case_evaluation": ref(self.root, self.case_eval),
            "case_evaluator_manifest": ref(self.root, self.case_manifest),
            "combined_preprimary_seal": ref(self.root, self.seal_path),
        }

    def _package_pre(self, output_name: str = "out/pre") -> dict[str, Path]:
        with patch.object(P, "verify_seal", return_value=self.seal):
            return P.package(self.root, self.pre_manifest, self.root / output_name)

    def _report_pair(self) -> tuple[Path, Path]:
        manifest = self._evaluator_manifest("REPORT_CONSISTENCY", "report_manifest.json")
        evaluation = self.root / "run/report_eval.json"
        write_json(evaluation, self._evaluation("REPORT_CONSISTENCY", manifest, [P.REPORT_GATE], []))
        return evaluation, manifest

    def _final_manifest(self, pre: dict[str, Path]) -> Path:
        report, report_manifest = self._report_pair()
        inputs = self._base_refs()
        inputs.update({
            "report_evaluation": ref(self.root, report),
            "report_evaluator_manifest": ref(self.root, report_manifest),
            "pre_report_receipt": ref(self.root, pre["receipt"]),
            "pre_report_gate_bundle": ref(self.root, pre["gate_bundle"]),
            "coverage_bundle": ref(self.root, pre["coverage_bundle"]),
        })
        path = self.root / "run/final_packager_manifest.json"
        write_json(path, {
            "schema_version": "ncf.primary-json-evidence-packager-input.v1",
            "phase": "FINAL",
            "inputs": inputs,
        })
        return path

    def _rewrite_pre_manifest_ref(self, key: str, path: Path) -> None:
        manifest = json.loads(self.pre_manifest.read_text(encoding="utf-8"))
        manifest["inputs"][key] = ref(self.root, path)
        write_json(self.pre_manifest, manifest)

    def test_two_stage_write_once_package_is_exact_29_30_and_7(self) -> None:
        pre = self._package_pre()
        pre_bundle = json.loads(pre["gate_bundle"].read_text(encoding="utf-8"))
        coverage = json.loads(pre["coverage_bundle"].read_text(encoding="utf-8"))
        receipt = json.loads(pre["receipt"].read_text(encoding="utf-8"))
        self.assertEqual(len(pre_bundle["gate_results"]), 29)
        self.assertEqual(len(coverage["checks"]), 7)
        self.assertEqual(len(receipt["gate_evidence"]), 29)
        self.assertEqual(len(receipt["coverage_evidence"]), 7)
        self.assertEqual(pre_bundle["gate_results"][0]["gate_id"], "PL-IND-001")
        first = json.loads((self.root / pre_bundle["gate_results"][0]["evidence_refs"][0]["path"]).read_text())
        self.assertEqual(first["producer"]["producer_id"], "primary-case-gate-evaluator-case-v1")
        self.assertTrue(all(row["claimed_result"] == "PASS" for row in (
            json.loads(path.read_text()) for path in (pre["receipt"].parent / "evidence").glob("*.json")
        )))

        final_manifest = self._final_manifest(pre)
        with patch.object(P, "verify_seal", return_value=self.seal):
            final = P.package(self.root, final_manifest, self.root / "out/final")
        final_bundle = json.loads(final["gate_bundle"].read_text(encoding="utf-8"))
        final_receipt = json.loads(final["receipt"].read_text(encoding="utf-8"))
        self.assertEqual(len(final_bundle["gate_results"]), 30)
        self.assertEqual([row["gate_id"] for row in final_bundle["gate_results"]],
                         [row["id"] for row in self.gates["gates"]])
        self.assertEqual(len(final_receipt["gate_evidence"]), 30)
        self.assertEqual(len(final_receipt["coverage_evidence"]), 7)
        self.assertTrue(final_receipt["invariants"]["manual_pass_forbidden"])

    def test_output_directory_is_write_once(self) -> None:
        self._package_pre("out/immutable")
        with self.assertRaisesRegex(P.PackagingError, "refusing to overwrite output directory"):
            self._package_pre("out/immutable")

    def test_content_reference_tampering_fails_closed(self) -> None:
        document = json.loads(self.structural.read_text(encoding="utf-8"))
        document["overall_status"] = "FAIL"
        write_json(self.structural, document)
        with patch.object(P, "verify_seal", return_value=self.seal):
            with self.assertRaisesRegex(P.PackagingError, "hash/bytes mismatch"):
                P.package(self.root, self.pre_manifest, self.root / "out/tamper")

    def test_missing_duplicate_and_unknown_subjects_fail_closed(self) -> None:
        original = json.loads(self.case_eval.read_text(encoding="utf-8"))
        mutations = {}
        missing = copy.deepcopy(original)
        missing["gate_results"].pop()
        mutations["missing"] = missing
        duplicate = copy.deepcopy(original)
        duplicate["gate_results"].append(copy.deepcopy(duplicate["gate_results"][0]))
        mutations["duplicate"] = duplicate
        unknown = copy.deepcopy(original)
        unknown["gate_results"][-1]["subject_id"] = "PL-UNKNOWN-999"
        mutations["unknown"] = unknown
        for label, document in mutations.items():
            with self.subTest(label=label):
                write_json(self.case_eval, document)
                self._rewrite_pre_manifest_ref("case_evaluation", self.case_eval)
                with patch.object(P, "verify_seal", return_value=self.seal):
                    with self.assertRaises(P.PackagingError):
                        P.package(self.root, self.pre_manifest, self.root / f"out/{label}")
        write_json(self.case_eval, original)

    def test_schema_and_recomputed_check_reject_untrusted_pass(self) -> None:
        original = json.loads(self.case_eval.read_text(encoding="utf-8"))
        malformed = copy.deepcopy(original)
        malformed["manual_result"] = "PASS"
        write_json(self.case_eval, malformed)
        self._rewrite_pre_manifest_ref("case_evaluation", self.case_eval)
        with patch.object(P, "verify_seal", return_value=self.seal):
            with self.assertRaisesRegex(P.PackagingError, "additional property"):
                P.package(self.root, self.pre_manifest, self.root / "out/manual-field")

        inconsistent = copy.deepcopy(original)
        inconsistent["gate_results"][0]["checks"][0]["observed"] = False
        # The producer's PASS/passed=True claim is now inconsistent with the
        # frozen EQ assertion.  The packager must recompute it, not trust it.
        write_json(self.case_eval, inconsistent)
        self._rewrite_pre_manifest_ref("case_evaluation", self.case_eval)
        with patch.object(P, "verify_seal", return_value=self.seal):
            with self.assertRaisesRegex(P.PackagingError, "not recomputable"):
                P.package(self.root, self.pre_manifest, self.root / "out/false-pass")

    def test_prior_manual_auditor_evidence_is_not_accepted(self) -> None:
        source = self.root / "run/manual_source.json"
        write_json(source, {"result": "PASS"})
        evidence_path = self.root / "run/manual_evidence.json"
        write_json(evidence_path, {
            "schema_version": "ncf.primary-gate-evidence.v3",
            "subject_kind": "GATE",
            "subject_id": "PL-IND-001",
            "claimed_result": "PASS",
            "producer": {
                "policy": "MANUAL_INDEPENDENT_AUDITOR",
                "policy_id": "manual",
                "auditor_role_manifest_ref_id": "producer_artifact",
                "audit_record_ref_id": "producer_artifact",
            },
            "source_artifact_refs": [{"ref_id": "producer_artifact", **ref(self.root, source)}],
            "assertions": [{
                "assertion_id": "manual.pass",
                "source_ref_id": "producer_artifact",
                "observed_json_pointer": "/result",
                "observed": "PASS",
                "expected": "PASS",
                "operator": "EQ",
            }],
        })
        row = {
            "gate_id": "PL-IND-001", "result": "PASS",
            "evidence_refs": [ref(self.root, evidence_path)],
        }
        with self.assertRaisesRegex(P.PackagingError, "producer mismatch"):
            P.verify_old_evidence(self.root, row, "GATE", "gate_id")

    def test_pre_report_manifest_rejects_report_or_result_inputs(self) -> None:
        document = json.loads(self.pre_manifest.read_text(encoding="utf-8"))
        document["inputs"]["report_evaluation"] = ref(self.root, self.case_eval)
        write_json(self.pre_manifest, document)
        with patch.object(P, "verify_seal", return_value=self.seal):
            with self.assertRaisesRegex(P.PackagingError, "PRE_REPORT inputs not exact"):
                P.package(self.root, self.pre_manifest, self.root / "out/extra-report")
        self.assertNotIn("result", P.package_pre.__code__.co_varnames)


if __name__ == "__main__":
    unittest.main()
