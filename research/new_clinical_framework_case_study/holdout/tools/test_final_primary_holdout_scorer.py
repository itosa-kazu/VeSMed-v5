from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from final_primary_holdout_scorer import (
    COVERAGE_SCHEMA_VERSION,
    FAILED_VERDICT,
    INCOMPLETE_VERDICT,
    INPUT_SCHEMA_VERSION,
    POSITIVE_VERDICT,
    REQUIRED_COMPLEX_COVERAGE,
    _validate_automated_assertion_binding,
    score_documents,
)
from producer_replay_verifier import (
    build_invocation_descriptor,
    invocation_sha256,
)


ROOT = Path(__file__).resolve().parents[2]


def content_ref(path: Path, root: Path, *, ref_id: str | None = None) -> dict:
    value = {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }
    if ref_id is not None:
        value = {"ref_id": ref_id, **value}
    return value


class FinalPrimaryHoldoutScorerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.gates = json.loads((ROOT / "holdout/PERFECT_LANDING_GATES.json").read_text(encoding="utf-8"))
        cls.scoring_template = json.loads((ROOT / "holdout/PRIMARY_HOLDOUT_SCORING_v1.json").read_text(encoding="utf-8"))
        cls.gate_ids = [row["id"] for row in cls.gates["gates"]]

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.study_root = Path(self.temp.name)
        self.scoring = copy.deepcopy(self.scoring_template)
        self.tool = self.study_root / "holdout/tools/test_primary_gate_producer.py"
        self.tool.parent.mkdir(parents=True, exist_ok=True)
        self.tool.write_text(
            """#!/usr/bin/env python3
import argparse, json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--input', required=True)
p.add_argument('--output', required=True)
a=p.parse_args()
v=json.loads(Path(a.input).read_text(encoding='utf-8'))
out={'schema_version':'ncf.test-primary-gate-producer-output.v1',
     'produced_by':'holdout/tools/test_primary_gate_producer.py',
     'check_values':v['check_values']}
Path(a.output).write_text(json.dumps(out,sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')
""",
            encoding="utf-8",
        )
        self.tool_ref = content_ref(self.tool, self.study_root)
        self.sealed_artifacts = {self.tool_ref["path"]: dict(self.tool_ref)}
        self.input = self.study_root / "inputs/check-values.json"
        self.input.parent.mkdir(parents=True)
        all_subjects = self.gate_ids + REQUIRED_COMPLEX_COVERAGE
        self.input.write_text(
            json.dumps(
                {
                    "schema_version": "ncf.test-primary-gate-producer-input.v1",
                    "check_values": {subject_id: True for subject_id in all_subjects},
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        self.default_output = self.study_root / "producer-output/default.json"
        self.default_output.parent.mkdir(parents=True)
        subprocess.run(
            [sys.executable, str(self.tool), "--input", str(self.input), "--output", str(self.default_output)],
            check=True,
        )
        self.scoring["final_scorer_contract"]["evidence_producer_policy"]["sealed_automated_generators"] = [
            {
                "producer_id": "test-primary-gate-producer-v1",
                "tool_path": self.tool_ref["path"],
                "artifact_schema_versions": ["ncf.test-primary-gate-producer-output.v1"],
                "artifact_produced_by_required": True,
                "replay_contract": {
                    "schema_version": "ncf.producer-replay-policy.v1",
                    "adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
                    "argv_template": [
                        "--input", "{input:input}",
                        "--output", "{output}",
                    ],
                    "required_input_slots": {
                        "input": {"json_schema_versions": ["ncf.test-primary-gate-producer-input.v1"]}
                    },
                    "check_arg_contract": {},
                    "output_contract": {
                        "mode": "SINGLE_FILE",
                        "json_schema_versions": ["ncf.test-primary-gate-producer-output.v1"],
                    },
                    "timeout_seconds": 30,
                    "working_directory": "STUDY_ROOT",
                    "network_policy": "APPLICATION_SOCKET_GUARD_OFFLINE",
                    "comparison": "EXACT_BYTES_AND_CANONICAL_JSON",
                },
                "allowed_subjects": {
                    "GATE": self.gate_ids,
                    "COMPLEX_COVERAGE": REQUIRED_COMPLEX_COVERAGE,
                },
                "assertion_contract": {
                    "schema_version": "ncf.producer-assertion-contract.v1",
                    "mode": "SUBJECT_EXACT_POINTERS_V1",
                    "subject_assertions": {
                        "GATE": {
                            subject_id: [{
                                "json_pointer": f"/check_values/{subject_id}",
                                "expected": True,
                                "operator": "EQ",
                            }]
                            for subject_id in self.gate_ids
                        },
                        "COMPLEX_COVERAGE": {
                            subject_id: [{
                                "json_pointer": f"/check_values/{subject_id}",
                                "expected": True,
                                "operator": "EQ",
                            }]
                            for subject_id in REQUIRED_COMPLEX_COVERAGE
                        },
                    },
                },
            }
        ]

    def tearDown(self) -> None:
        self.temp.cleanup()

    def evidence_ref(
        self,
        kind: str,
        subject_id: str,
        result: str,
        *,
        observed: bool | None = None,
        claimed_observed: bool | None = None,
        producer_ref: dict | None = None,
    ) -> dict:
        actual_observed = (result == "PASS") if observed is None else observed
        if actual_observed:
            input_path = self.input
            source_path = self.default_output
        else:
            input_path = self.study_root / f"producer-input/{kind.lower()}-{subject_id}-false.json"
            input_path.parent.mkdir(parents=True, exist_ok=True)
            input_value = json.loads(self.input.read_text(encoding="utf-8"))
            input_value["check_values"][subject_id] = False
            input_path.write_text(json.dumps(input_value, sort_keys=True), encoding="utf-8")
            source_path = self.study_root / f"producer-output/{kind.lower()}-{subject_id}-false.json"
            subprocess.run(
                [sys.executable, str(self.tool), "--input", str(input_path), "--output", str(source_path)],
                check=True,
            )
        input_ref = content_ref(input_path, self.study_root, ref_id="producer-input")
        source_ref = content_ref(source_path, self.study_root, ref_id="producer-output")
        replay = {
            "adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
            "input_ref_ids": {"input": "producer-input"},
            "check_args": {},
            "invocation_sha256": "0" * 64,
        }
        source_refs = {"producer-input": input_ref, "producer-output": source_ref}
        descriptor = build_invocation_descriptor(
            producer_id="test-primary-gate-producer-v1",
            tool_ref=producer_ref or self.tool_ref,
            replay_policy=self.scoring["final_scorer_contract"]["evidence_producer_policy"]["sealed_automated_generators"][0]["replay_contract"],
            replay_claim=replay,
            source_refs=source_refs,
            output_ref_id="producer-output",
        )
        replay["invocation_sha256"] = invocation_sha256(descriptor)
        value = {
            "schema_version": "ncf.primary-gate-evidence.v3",
            "subject_kind": kind,
            "subject_id": subject_id,
            "claimed_result": result,
            "producer": {
                "policy": "SEALED_AUTOMATED_GENERATOR",
                "producer_id": "test-primary-gate-producer-v1",
                "tool_ref": copy.deepcopy(producer_ref or self.tool_ref),
                "artifact_ref_id": "producer-output",
                "replay": replay,
            },
            "source_artifact_refs": [input_ref, source_ref],
            "assertions": [
                {
                    "assertion_id": f"assert-{subject_id}",
                    "source_ref_id": "producer-output",
                    "observed_json_pointer": f"/check_values/{subject_id}",
                    "observed": actual_observed if claimed_observed is None else claimed_observed,
                    "expected": True,
                    "operator": "EQ",
                }
            ],
        }
        rel = f"evidence/{kind.lower()}-{subject_id}.json"
        path = self.study_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
        return content_ref(path, self.study_root)

    def manual_evidence_ref(self, kind: str, subject_id: str, result: str) -> dict:
        audit_path = self.study_root / f"audit/{subject_id}.json"
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps({"check_value": False}, sort_keys=True), encoding="utf-8")
        audit_ref = content_ref(audit_path, self.study_root, ref_id="audit-record")
        role_path = self.study_root / f"audit/{subject_id}.role.json"
        role = {
            "schema_version": "NCF-PRIMARY-ROLE-MANIFEST-1.1.0",
            "role": "scorer_auditor",
            "case_identity_exposed": True,
            "attestations": {
                "only_declared_inputs_observed": True,
                "no_forbidden_data_class_observed": True,
                "no_undeclared_output_written": True,
                "no_artifact_modified_after_input_hash": True,
            },
            "outputs": [{
                **{k: audit_ref[k] for k in ("path", "sha256", "bytes")},
                "data_class": "audit_report",
            }],
        }
        role_path.write_text(json.dumps(role, sort_keys=True), encoding="utf-8")
        role_ref = content_ref(role_path, self.study_root, ref_id="role-manifest")
        evidence = {
            "schema_version": "ncf.primary-gate-evidence.v3",
            "subject_kind": kind,
            "subject_id": subject_id,
            "claimed_result": result,
            "producer": {
                "policy": "MANUAL_INDEPENDENT_AUDITOR",
                "policy_id": "NCF-MANUAL-INDEPENDENT-AUDITOR-FAILURE-ONLY-1.0.0",
                "auditor_role_manifest_ref_id": "role-manifest",
                "audit_record_ref_id": "audit-record",
            },
            "source_artifact_refs": [role_ref, audit_ref],
            "assertions": [{
                "assertion_id": f"manual-{subject_id}",
                "source_ref_id": "audit-record",
                "observed_json_pointer": "/check_value",
                "observed": False,
                "expected": True,
                "operator": "EQ",
            }],
        }
        path = self.study_root / f"evidence/manual-{subject_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
        return content_ref(path, self.study_root)

    def gate_bundle(self, result: str = "PASS") -> dict:
        return {
            "schema_version": INPUT_SCHEMA_VERSION,
            "contract_id": "NCF-PERFECT-LANDING-GATES",
            "contract_version": "1.1.0",
            "correct_diagnosis_reported": False,
            "gate_results": [
                {"gate_id": gate_id, "result": result, "evidence_refs": [self.evidence_ref("GATE", gate_id, result)]}
                for gate_id in self.gate_ids
            ],
        }

    def coverage_bundle(self, result: str = "PASS") -> dict:
        return {
            "schema_version": COVERAGE_SCHEMA_VERSION,
            "checks": [
                {"coverage_id": item, "result": result, "evidence_refs": [self.evidence_ref("COMPLEX_COVERAGE", item, result)]}
                for item in REQUIRED_COMPLEX_COVERAGE
            ],
        }

    def score(self, gates=None, coverage=None):
        return score_documents(
            self.gates,
            self.scoring,
            gates or self.gate_bundle(),
            coverage or self.coverage_bundle(),
            generated_at="2026-07-21T00:00:00Z",
            study_root=self.study_root,
            sealed_artifacts=self.sealed_artifacts,
        )

    def test_exactly_30_pass_and_complex_coverage_is_only_positive_path(self) -> None:
        report = self.score()
        self.assertEqual(report["verdict"], POSITIVE_VERDICT)
        self.assertEqual(report["evidence_integrity"]["validated_artifact_count"], 37)

    def test_correct_diagnosis_cannot_override_hard_gate_failure(self) -> None:
        bundle = self.gate_bundle()
        bundle["correct_diagnosis_reported"] = True
        bundle["gate_results"][7]["result"] = "FAIL"
        gate_id = bundle["gate_results"][7]["gate_id"]
        bundle["gate_results"][7]["evidence_refs"] = [self.evidence_ref("GATE", gate_id, "FAIL")]
        report = self.score(bundle)
        self.assertEqual(report["verdict"], FAILED_VERDICT)
        self.assertFalse(report["diagnosis_override"]["used_to_override_gate_failure"])

    def test_missing_duplicate_unknown_or_bad_header_is_incomplete(self) -> None:
        bundle = self.gate_bundle()
        bundle["gate_results"].pop()
        self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)
        bundle = self.gate_bundle()
        bundle["gate_results"].append(copy.deepcopy(bundle["gate_results"][0]))
        self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)
        bundle = self.gate_bundle()
        bundle["gate_results"][0]["gate_id"] = "PL-UNKNOWN-999"
        self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)
        bundle = self.gate_bundle()
        bundle["contract_version"] = "1.0.0"
        self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)

    def test_not_executed_or_missing_evidence_is_incomplete(self) -> None:
        for result in ("NOT_EXECUTED", "EVIDENCE_MISSING", "NOT_APPLICABLE"):
            with self.subTest(result=result):
                bundle = self.gate_bundle()
                bundle["gate_results"][0]["result"] = result
                self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)
        bundle = self.gate_bundle()
        bundle["gate_results"][0]["evidence_refs"] = []
        self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)

    def test_complex_coverage_failure_is_failed_and_missing_is_incomplete(self) -> None:
        coverage = self.coverage_bundle()
        coverage["checks"][0]["result"] = "FAIL"
        subject = coverage["checks"][0]["coverage_id"]
        coverage["checks"][0]["evidence_refs"] = [self.evidence_ref("COMPLEX_COVERAGE", subject, "FAIL")]
        self.assertEqual(self.score(coverage=coverage)["verdict"], FAILED_VERDICT)
        coverage = self.coverage_bundle()
        coverage["checks"].pop()
        self.assertEqual(self.score(coverage=coverage)["verdict"], INCOMPLETE_VERDICT)

    def test_fake_path_hash_or_bytes_is_incomplete(self) -> None:
        for mutation in ("path", "sha256", "bytes"):
            with self.subTest(mutation=mutation):
                bundle = self.gate_bundle()
                ref = bundle["gate_results"][0]["evidence_refs"][0]
                if mutation == "path":
                    ref["path"] = "evidence/does-not-exist.json"
                elif mutation == "sha256":
                    ref["sha256"] = "0" * 64
                else:
                    ref["bytes"] += 1
                self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)

    def test_cross_gate_evidence_binding_is_incomplete(self) -> None:
        bundle = self.gate_bundle()
        bundle["gate_results"][0]["evidence_refs"] = bundle["gate_results"][1]["evidence_refs"]
        self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)

    def test_fresh_replayed_unrelated_true_pointer_cannot_launder_subject_pass(self) -> None:
        """Producer provenance cannot turn another subject's truth into this gate's evidence."""
        bundle = self.gate_bundle()
        target = bundle["gate_results"][0]
        other_subject = bundle["gate_results"][1]["gate_id"]
        evidence_path = self.study_root / target["evidence_refs"][0]["path"]
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        evidence["assertions"][0]["observed_json_pointer"] = f"/check_values/{other_subject}"
        # The output remains an exact fresh replay and the substituted pointer
        # really is true.  Only subject-specific exhaustive binding can reject
        # this otherwise-valid provenance chain.
        evidence_path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
        target["evidence_refs"] = [content_ref(evidence_path, self.study_root)]
        report = self.score(bundle)
        self.assertEqual(report["verdict"], INCOMPLETE_VERDICT)
        self.assertIn(
            "producer_assertion_coverage_not_exact",
            {row["reason"] for row in report["evidence_integrity"]["invalid_artifacts"]},
        )

    def test_evaluator_assertions_must_exhaustively_bind_recomputed_subject_checks(self) -> None:
        contract = {
            "schema_version": "ncf.producer-assertion-contract.v1",
            "mode": "SUBJECT_RESULT_ROW_EXHAUSTIVE_CHECKS_V1",
            "result_array_json_pointers": {"GATE": "/gate_results", "COMPLEX_COVERAGE": "/coverage_results"},
            "subject_id_field": "subject_id",
            "subject_kind_field": "subject_kind",
            "result_field": "computed_result",
            "checks_field": "checks",
            "check_id_field": "check_id",
            "check_observed_field": "observed",
            "check_expected_field": "expected",
            "check_operator_field": "operator",
            "check_pass_field": "passed",
        }
        artifact = {
            "gate_results": [{
                "subject_kind": "GATE",
                "subject_id": "PL-LED-001",
                "computed_result": "PASS",
                "checks": [
                    {"check_id": "denominator", "observed": 3, "expected": 3, "operator": "EQ", "passed": True},
                    {"check_id": "ledger", "observed": True, "expected": True, "operator": "EQ", "passed": True},
                ],
            }],
            "coverage_results": [],
        }
        assertions = [
            {"assertion_id": "result", "source_ref_id": "evaluation", "observed_json_pointer": "/gate_results/0/computed_result", "observed": "PASS", "expected": "PASS", "operator": "EQ"},
            {"assertion_id": "check-0", "source_ref_id": "evaluation", "observed_json_pointer": "/gate_results/0/checks/0/passed", "observed": True, "expected": True, "operator": "EQ"},
            {"assertion_id": "check-1", "source_ref_id": "evaluation", "observed_json_pointer": "/gate_results/0/checks/1/passed", "observed": True, "expected": True, "operator": "EQ"},
        ]
        ok, reason = _validate_automated_assertion_binding(
            contract=contract, artifact=artifact, assertions=assertions,
            source_ref_id="evaluation", subject_kind="GATE",
            subject_id="PL-LED-001", claimed_result="PASS",
        )
        self.assertTrue(ok, reason)

        ok, reason = _validate_automated_assertion_binding(
            contract=contract, artifact=artifact, assertions=assertions[:-1],
            source_ref_id="evaluation", subject_kind="GATE",
            subject_id="PL-LED-001", claimed_result="PASS",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "producer_assertion_coverage_not_exact")

        inconsistent = copy.deepcopy(artifact)
        inconsistent["gate_results"][0]["checks"][1]["observed"] = False
        ok, reason = _validate_automated_assertion_binding(
            contract=contract, artifact=inconsistent, assertions=assertions,
            source_ref_id="evaluation", subject_kind="GATE",
            subject_id="PL-LED-001", claimed_result="PASS",
        )
        self.assertFalse(ok)
        self.assertEqual(reason, "producer_assertion_subject_check_pass_not_recomputable")

    def test_bare_passed_boolean_is_rejected(self) -> None:
        bundle = self.gate_bundle()
        ref = bundle["gate_results"][0]["evidence_refs"][0]
        path = self.study_root / ref["path"]
        evidence = json.loads(path.read_text())
        evidence["assertions"] = [{"assertion_id": "forged", "passed": True}]
        path.write_text(json.dumps(evidence), encoding="utf-8")
        bundle["gate_results"][0]["evidence_refs"] = [content_ref(path, self.study_root)]
        report = self.score(bundle)
        self.assertEqual(report["verdict"], INCOMPLETE_VERDICT)
        self.assertIn("deterministic_assertion_invalid_or_not_source_derived", {x["reason"] for x in report["evidence_integrity"]["invalid_artifacts"]})

    def test_claimed_observed_must_match_source_pointer(self) -> None:
        bundle = self.gate_bundle()
        gate_id = bundle["gate_results"][0]["gate_id"]
        bundle["gate_results"][0]["evidence_refs"] = [
            self.evidence_ref("GATE", gate_id, "PASS", observed=True, claimed_observed=False)
        ]
        self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)

    def test_false_operator_result_cannot_hide_behind_pass(self) -> None:
        bundle = self.gate_bundle()
        gate_id = bundle["gate_results"][0]["gate_id"]
        bundle["gate_results"][0]["evidence_refs"] = [self.evidence_ref("GATE", gate_id, "PASS", observed=False)]
        report = self.score(bundle)
        self.assertEqual(report["verdict"], INCOMPLETE_VERDICT)
        self.assertIn(
            "producer_assertion_subject_result_not_derived_from_exact_pointers",
            {x["reason"] for x in report["evidence_integrity"]["invalid_artifacts"]},
        )

    def test_unsealed_or_scope_mismatched_producer_is_incomplete(self) -> None:
        bundle = self.gate_bundle()
        gate_id = bundle["gate_results"][0]["gate_id"]
        forged = dict(self.tool_ref)
        forged["sha256"] = "0" * 64
        bundle["gate_results"][0]["evidence_refs"] = [self.evidence_ref("GATE", gate_id, "PASS", producer_ref=forged)]
        self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)
        self.scoring["final_scorer_contract"]["evidence_producer_policy"]["sealed_automated_generators"][0]["allowed_subjects"]["GATE"].remove(gate_id)
        bundle["gate_results"][0]["evidence_refs"] = [self.evidence_ref("GATE", gate_id, "PASS")]
        self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)

    def test_handcrafted_schema_and_produced_by_cannot_impersonate_sealed_producer(self) -> None:
        """A self-authored artifact cannot pass by copying producer metadata."""
        bundle = self.gate_bundle()
        gate_row = bundle["gate_results"][0]
        evidence_ref = gate_row["evidence_refs"][0]
        evidence_path = self.study_root / evidence_ref["path"]
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))

        forged_path = self.study_root / "producer-output/handcrafted-spoof.json"
        forged = json.loads(self.default_output.read_text(encoding="utf-8"))
        # Preserve the admitted schema and copy a plausible producer marker.  A
        # metadata-only trust model would accept this file even though the
        # sealed tool did not emit these exact bytes.
        forged["produced_by"] = "holdout/tools/test_primary_gate_producer.py"
        forged["handcrafted_marker"] = "not-emitted-by-sealed-tool"
        forged_path.write_text(
            json.dumps(forged, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        forged_ref = content_ref(forged_path, self.study_root, ref_id="producer-output")
        evidence["source_artifact_refs"] = [
            ref if ref["ref_id"] != "producer-output" else forged_ref
            for ref in evidence["source_artifact_refs"]
        ]
        source_refs = {ref["ref_id"]: ref for ref in evidence["source_artifact_refs"]}
        descriptor = build_invocation_descriptor(
            producer_id="test-primary-gate-producer-v1",
            tool_ref=self.tool_ref,
            replay_policy=self.scoring["final_scorer_contract"]["evidence_producer_policy"]["sealed_automated_generators"][0]["replay_contract"],
            replay_claim=evidence["producer"]["replay"],
            source_refs=source_refs,
            output_ref_id="producer-output",
        )
        evidence["producer"]["replay"]["invocation_sha256"] = invocation_sha256(descriptor)
        evidence_path.write_text(json.dumps(evidence, sort_keys=True), encoding="utf-8")
        gate_row["evidence_refs"] = [content_ref(evidence_path, self.study_root)]

        report = self.score(bundle)
        self.assertEqual(report["verdict"], INCOMPLETE_VERDICT)
        self.assertTrue(
            any(
                "producer_fresh_replay_failed:replay_output_exact_bytes_mismatch"
                in row["reason"]
                for row in report["evidence_integrity"]["invalid_artifacts"]
            ),
            report["evidence_integrity"],
        )
    def test_source_artifact_hash_or_bytes_mismatch_is_incomplete(self) -> None:
        bundle = self.gate_bundle()
        ref = bundle["gate_results"][0]["evidence_refs"][0]
        path = self.study_root / ref["path"]
        evidence = json.loads(path.read_text())
        evidence["source_artifact_refs"][0]["bytes"] += 1
        path.write_text(json.dumps(evidence), encoding="utf-8")
        bundle["gate_results"][0]["evidence_refs"] = [content_ref(path, self.study_root)]
        self.assertEqual(self.score(bundle)["verdict"], INCOMPLETE_VERDICT)

    def test_manual_auditor_cannot_mint_pass_but_can_surface_fail(self) -> None:
        bundle = self.gate_bundle()
        gate_id = bundle["gate_results"][0]["gate_id"]
        bundle["gate_results"][0]["evidence_refs"] = [self.manual_evidence_ref("GATE", gate_id, "PASS")]
        report = self.score(bundle)
        self.assertEqual(report["verdict"], INCOMPLETE_VERDICT)
        self.assertIn("manual_auditor_pass_cannot_complete_gate", {x["reason"] for x in report["evidence_integrity"]["invalid_artifacts"]})

        bundle = self.gate_bundle()
        bundle["gate_results"][0]["result"] = "FAIL"
        bundle["gate_results"][0]["evidence_refs"] = [self.manual_evidence_ref("GATE", gate_id, "FAIL")]
        self.assertEqual(self.score(bundle)["verdict"], FAILED_VERDICT)

    def test_missing_verified_seal_index_is_incomplete(self) -> None:
        report = score_documents(
            self.gates,
            self.scoring,
            self.gate_bundle(),
            self.coverage_bundle(),
            generated_at="2026-07-21T00:00:00Z",
            study_root=self.study_root,
            sealed_artifacts=None,
        )
        self.assertEqual(report["verdict"], INCOMPLETE_VERDICT)
        self.assertIn("verified_combined_seal_producer_index_not_supplied", {x["reason"] for x in report["evidence_integrity"]["invalid_artifacts"]})


if __name__ == "__main__":
    unittest.main()
