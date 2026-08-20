from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from holdout.tools.validate_primary_holdout_protocol import _validate_schema_instance
from holdout.tools.test_compile_evaluator_sanitized_runtime_ledger import CompilerFixture, write_json as compiler_write_json


STUDY_ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = STUDY_ROOT / "holdout/tools/primary_case_gate_evaluator.py"
SPEC = importlib.util.spec_from_file_location("primary_case_gate_evaluator_under_test", TOOL_PATH)
assert SPEC and SPEC.loader
E = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(E)


def write_json(root: Path, name: str, value: object) -> dict[str, object]:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = E.canonical_json_file_bytes(value)
    path.write_bytes(raw)
    return {"path": name.replace("\\", "/"), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


class PrimaryCaseGateEvaluatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _fixture(self) -> tuple[Path, dict[str, object], dict[str, object]]:
        gates = json.loads((STUDY_ROOT / "holdout/PERFECT_LANDING_GATES.json").read_text(encoding="utf-8"))
        scoring = json.loads((STUDY_ROOT / "holdout/PRIMARY_HOLDOUT_SCORING_v1.json").read_text(encoding="utf-8"))
        roles = sorted(E.CASE_INPUT_ROLES)
        docs: dict[str, object] = {role: {"schema_version": "dummy"} for role in roles}
        docs["gate_contract"] = gates
        docs["scoring_contract"] = scoring
        docs["audit_report"] = {"schema_version": "NCF-PRIMARY-SCORER-AUDIT-REPORT-1.0.0", "role": "scorer_auditor", "findings": []}

        event_by_id = {
            "EV0": {"event_id": "EV0", "available_epoch": 0, "occurred_epoch_upper": 0, "source_fact_ids": ["F1"], "event_type": "ObservationAvailable"},
            "EV1": {"event_id": "EV1", "available_epoch": 1, "occurred_epoch_upper": 0, "source_fact_ids": ["F2"], "event_type": "ObservationAvailable"},
            "EV2": {"event_id": "EV2", "available_epoch": 1, "occurred_epoch_upper": 1, "source_fact_ids": ["F3"], "event_type": "ActionStarted", "action_id": "A", "exposure_id": "X"},
            "EV3": {"event_id": "EV3", "available_epoch": 2, "occurred_epoch_upper": 2, "source_fact_ids": ["F4"], "event_type": "ActionResponseAvailable", "action_id": "A", "exposure_id": "X"},
        }
        fact_by_id = {
            "F1": {"fact_id": "F1", "runtime_source_result_ids": ["EV0"], "local_domain_ids": ["D1"], "clinically_consequential": True, "evidence_semantics": "POSITIVE"},
            "F2": {"fact_id": "F2", "runtime_source_result_ids": ["EV1"], "local_domain_ids": ["D2"], "clinically_consequential": True, "evidence_semantics": "RELIABLE_NEGATIVE"},
            "F3": {"fact_id": "F3", "runtime_source_result_ids": ["EV2"], "local_domain_ids": ["D1"], "clinically_consequential": False, "evidence_semantics": "ACTION"},
            "F4": {"fact_id": "F4", "runtime_source_result_ids": ["EV3"], "local_domain_ids": ["D2"], "clinically_consequential": True, "evidence_semantics": "POSITIVE"},
        }
        source_to_opaque = {event_id: f"EV-{index:08d}" for index, event_id in enumerate(event_by_id, start=1)}
        state = {
            "opaque": "state",
            "local_states": [
                {"process_id": "P1", "coordinates": [], "mode_posterior": []},
                {"process_id": "P2", "coordinates": [], "mode_posterior": []},
            ],
        }
        state_hash = hashlib.sha256(E.canonical_json_bytes(state)).hexdigest()

        def cut(ordinal: int, processed: list[str], future: list[str]) -> dict[str, object]:
            diagnosis = {
                "consumed_state_hash": state_hash,
                "process_activation_marginals": {"P1": 0.7, "P2": 0.2},
            }
            factor_trace = [
                {
                    "source_result_ids": [source_to_opaque["EV0"]],
                    "derived_process_effects": [{"process_id": "P1", "direction": "RAISE", "log_bayes_factor_active_vs_inactive": 1.0}],
                },
                {
                    "source_result_ids": [source_to_opaque["EV1"]],
                    "derived_process_effects": [{"process_id": "P2", "direction": "LOWER", "log_bayes_factor_active_vs_inactive": -1.0}],
                },
            ]
            return {
                "sequence": ordinal,
                "cut_ordinal": ordinal,
                "canonical_state": state,
                "canonical_state_hash": state_hash,
                "canonical_state_bytes_sha256": state_hash,
                "diagnosis": diagnosis,
                "forecast": {"consumed_state_hash": state_hash},
                "persistence_baseline": {"consumed_state_hash": state_hash},
                "plan": {"consumed_state_hash": state_hash},
                "processed_event_ids": [source_to_opaque[item] for item in processed],
                "future_registered_event_ids": [source_to_opaque[item] for item in future],
                "new_event_ids": [source_to_opaque[item] for item in (processed if ordinal == 0 else [item for item in processed if item not in (["EV0"] if ordinal == 1 else ["EV0", "EV1", "EV2"])])],
                "head_state_hashes": {"diagnosis": state_hash, "forecast": state_hash, "persistence_baseline": state_hash, "plan": state_hash},
                "head_state_hashes_all_equal": True,
                "factor_trace": factor_trace,
                "mode_trace": [{"process_id": "P1"}, {"process_id": "P2"}],
                "sealed_before_next_cut_sha256": (str(ordinal + 1) * 64)[:64],
            }

        runtime_cuts = [cut(0, ["EV0"], ["EV1", "EV2", "EV3"]), cut(1, ["EV0", "EV1", "EV2"], ["EV3"]), cut(2, ["EV0", "EV1", "EV2", "EV3"], [])]
        prospective_scores = []
        for index in range(2):
            prospective_scores.append({
                "forecast_cut_ordinal": index,
                "realization_cut_ordinal": index + 1,
                "forecast_cut_seal_sha256": runtime_cuts[index]["sealed_before_next_cut_sha256"],
                "prospective_seal_verified": True,
                "model": {"component_count": 1, "components": [{"positive_support": True}], "bounded_log_score": -0.2, "all_components_positive_support": True},
                "persistence_baseline": {"component_count": 1, "components": [{"positive_support": True}], "bounded_log_score": -0.2, "all_components_positive_support": True},
            })
        runtime = {
            "schema_version": "NCF-PRIMARY-RUNTIME-OUTPUT-1.0.0",
            "case_blind_process_priors": [
                {"process_id": "P1", "activation_prior": 0.2, "prior_source": "frozen_model_pack"},
                {"process_id": "P2", "activation_prior": 0.5, "prior_source": "frozen_model_pack"},
            ],
            "cut_count": 3,
            "cuts": runtime_cuts,
            "prospective_scores": prospective_scores,
        }
        docs["runtime_output"] = runtime
        basis = {key: True for key in E.RELIABLE_NEGATIVE_DIMENSIONS}
        records = []
        for event_id, source_id in (("EV0", "RS1"), ("EV1", "RS2"), ("EV3", "RS4")):
            records.append({
                "event_id": event_id, "source_result_id": source_id, "mapped_id": "M", "mapping_status": "MAPPED",
                "method": {"requirement_status": "SATISFIED", "required_provenance_fields_present": [], "required_provenance_fields_missing": []},
                "unit": {"normalization_status": "NOT_APPLICABLE", "source_unit": None, "normalized_unit": None},
                "reliability": {"status": "RELIABLE", "basis": basis}, "rankability_disposition": "CONSUME",
                "support_masking": {"active_action_ids_at_sample": [], "masking_action_ids": [], "masking_risk": "NONE", "conditioned_factor_available": False, "disposition": "CONSUME_UNMASKED"},
                "alternative_representation": {"group_id": None, "selected_source_result_ids": [source_id], "suppressed_source_result_ids": []},
                "runtime_event_type": "ObservationAvailable", "runtime_disposition_reason": None,
            })
        for row in records:
            opaque_id = source_to_opaque[str(row["event_id"])]
            row["event_id"] = opaque_id
            row["source_result_id"] = opaque_id
            row["alternative_representation"]["selected_source_result_ids"] = [opaque_id]
        docs["mapped_observation_consumption"] = {
            "schema_version": "NCF-MAPPED-OBSERVATION-CONSUMPTION-1.1.0",
            "event_count": len(records),
            "records": records,
        }
        docs["event_ledger"] = {
            "schema_version": E.SANITIZED_LEDGER_SCHEMA_VERSION,
            "events": [
                {
                    "opaque_event_id": f"EV-{index:08d}",
                    "event_kind": "ACTION" if index == 3 else "OBSERVATION",
                    "evidence_qualification": {key: "TRUE" for key in E.RELIABLE_NEGATIVE_DIMENSIONS},
                }
                for index in range(1, 5)
            ],
        }
        docs["oracle_targets"] = {
            "schema_version": "NCF-PRIMARY-ORACLE-TARGETS-2.0.0", "decisive_epoch": 2, "target_process_id": "P1",
            "incompatible_alternative_process_ids": ["P2"],
            "trajectories": [{"trajectory_ref_id": "T1", "process_id": "P1"}, {"trajectory_ref_id": "T2", "process_id": "P2"}],
            "concurrent_targets": [
                {"process_id": "P1", "trajectory_ref_id": "T1", "source_fact_ids": ["F1"], "source_event_ids": ["EV0"], "decisive_epoch": 2},
                {"process_id": "P2", "trajectory_ref_id": "T2", "source_fact_ids": ["F2"], "source_event_ids": ["EV1"], "decisive_epoch": 2},
            ],
        }
        refs = []
        for role in roles:
            ref = write_json(self.root, f"inputs/{role}.json", docs[role])
            refs.append({"ref_id": f"ref-{role}", "role": role, **ref})
        manifest = {"schema_version": E.INPUT_SCHEMA_VERSION, "stage": "CASE_EVALUATION", "execution_context": "POST_ROLE_DAG_EXTERNAL_DETERMINISTIC_EVALUATOR", "inputs": refs}
        manifest_path = self.root / "manifest.json"
        manifest_path.write_bytes(E.canonical_json_file_bytes(manifest))
        audit_by_id = {event_id: {"event_id": event_id, "future_exposure": False} for event_id in event_by_id}
        boundaries = {"facts": list(fact_by_id.values()), "fact_by_id": fact_by_id, "event_by_id": event_by_id, "audit_by_id": audit_by_id, "source_to_opaque": source_to_opaque}
        return manifest_path, docs, boundaries

    def _real_sanitizer_chain(self):
        fixture = CompilerFixture(self.root)
        tools = self.root / "holdout/tools"
        for name in ("verify_evaluator_sanitized_runtime_ledger.py", "producer_replay_verifier.py"):
            shutil.copy2(STUDY_ROOT / "holdout/tools" / name, tools / name)
        seal = json.loads(fixture.seal_path.read_text(encoding="utf-8"))

        def plain_ref(path: Path) -> dict[str, object]:
            raw = path.read_bytes()
            return {
                "path": path.relative_to(self.root).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }

        seal["bindings"]["primary_execution"]["evaluator_sanitized_runtime_ledger_compiler"] = seal["bindings"]["primary_execution"]["compiler"]
        seal["bindings"]["primary_execution"]["evaluator_sanitized_runtime_ledger_replay_verifier"] = plain_ref(tools / "verify_evaluator_sanitized_runtime_ledger.py")
        seal.pop("payload_sha256", None)
        seal["payload_sha256"] = hashlib.sha256(E.canonical_json_bytes(seal)).hexdigest()
        compiler_write_json(fixture.seal_path, seal)
        fixture.manifest["inputs"]["combined_preprimary_seal"].update(plain_ref(fixture.seal_path))
        compiler_write_json(fixture.manifest_path, fixture.manifest)
        fixture.run()
        builder = E._load_sanitized_replay_builder(self.root)
        verification = builder(
            self.root,
            manifest_path=fixture.manifest_path,
            ledger_path=fixture.output_path,
            assignment_proof_path=fixture.proof_path,
            combined_seal_path=fixture.seal_path,
        )
        verification_path = self.root / "holdout/primary_execution/evaluator_sanitized_runtime_ledger_replay_verification.json"
        verification_path.write_bytes(E.canonical_json_file_bytes(verification))
        refs = {
            "event_ledger": {"ref_id": "sanitized-ledger", "role": "event_ledger", **plain_ref(fixture.output_path)},
            "sanitized_ledger_assignment_proof": {"ref_id": "assignment-proof", "role": "sanitized_ledger_assignment_proof", **plain_ref(fixture.proof_path)},
            "sanitized_ledger_replay_verification": {"ref_id": "replay-verification", "role": "sanitized_ledger_replay_verification", **plain_ref(verification_path)},
            "preprimary_seal": {"ref_id": "combined-seal", "role": "preprimary_seal", **plain_ref(fixture.seal_path)},
        }
        docs = {
            "event_ledger": json.loads(fixture.output_path.read_text(encoding="utf-8")),
            "sanitized_ledger_assignment_proof": json.loads(fixture.proof_path.read_text(encoding="utf-8")),
            "sanitized_ledger_replay_verification": verification,
        }
        return fixture, refs, docs, verification_path, plain_ref

    def _source_ledger_audit_fixture(self):
        source_path = self.root / "source/case.txt"
        source_path.parent.mkdir(parents=True, exist_ok=True)
        source_path.write_bytes(b"alpha")
        source_ref = {
            "path": "source/case.txt",
            "sha256": hashlib.sha256(b"alpha").hexdigest(),
            "bytes": 5,
        }
        manifest = {
            "schema_version": "NCF-PRIMARY-IMMUTABLE-SOURCE-MANIFEST-1.0.0",
            "selected_source_ref": source_ref,
        }
        manifest_ref = write_json(self.root, "source/immutable_source_manifest.json", manifest)
        fact = {
            "fact_id": "F1",
            "source_assertion_ids": ["S1"],
            "source_locator": {
                "source_path": "source/case.txt",
                "byte_start": 0,
                "byte_end": 5,
                "excerpt_sha256": hashlib.sha256(b"alpha").hexdigest(),
            },
            "runtime_source_result_ids": ["source-event-1"],
            "local_domain_ids": ["D1"],
            "clinically_consequential": True,
        }
        inventory = {
            "schema_version": "NCF-PRIMARY-SOURCE-INVENTORY-2.0.0",
            "immutable_source_manifest_ref": manifest_ref,
            "facts": [fact],
        }
        inventory_ref = write_json(self.root, "source/source_inventory.json", inventory)
        source_audit = {
            "schema_version": "NCF-PRIMARY-SOURCE-AUDIT-1.0.0",
            "reviewer_role": "source_auditor",
            "immutable_source_manifest_ref": manifest_ref,
            "source_inventory_ref": inventory_ref,
            "complete_raw_source_assertion_denominator": True,
            "complete_raw_source_assertion_ids": ["S1"],
            "clinically_consequential_fact_ids": ["F1"],
            "duplicate_groups": [],
            "duplicate_group_coverage_complete": True,
            "all_source_locators_verified": True,
        }
        event_ledger = {
            "schema_version": "ncf.data.sealed-event-ledger.v1",
            "events": [{
                "source_event_id": "source-event-1",
                "source_fact_ids": ["F1"],
                "runtime_event": {
                    "source_concept_token": "source-concept-1",
                    "event_kind": "OBSERVATION",
                    "typed_value": {"kind": "NUMBER", "canonical": "1"},
                    "unit": None,
                    "observed_epoch_ordinal": 0,
                    "reliability": "HIGH",
                },
            }],
        }
        event_ledger_ref = write_json(self.root, "source/sealed_event_ledger.json", event_ledger)
        availability = {
            "schema_version": "ncf.data.sealed-availability-ledger.v1",
            "publication_order_used_as_clinical_availability": False,
            "events": [{
                "source_event_id": "source-event-1",
                "availability_evidence": {"kind": "EXACT", "exact_epoch": 0},
            }],
        }
        event_audit = {
            "schema_version": "NCF-PRIMARY-EVENT-LEDGER-AUDIT-2.0.0",
            "reviewer_role": "source_auditor",
            "event_ledger_ref": event_ledger_ref,
            "all_event_provenance_verified": True,
            "all_event_type_semantics_verified": True,
            "all_event_temporal_semantics_verified": True,
            "all_event_dispositions_verified": True,
            "no_invented_clock_time": True,
            "event_reviews": [{
                "event_id": "source-event-1",
                "provenance_verified": True,
                "event_type_verified": True,
                "occurred_time_semantics_verified": True,
                "availability_semantics_verified": True,
                "disposition_verified": True,
                "no_invented_clock_time": True,
                "event_type": "ObservationAvailable",
                "occurred_epoch_upper": 0,
                "available_epoch": 0,
                "source_fact_ids": ["F1"],
                "future_exposure": False,
            }],
        }
        refs = {
            "immutable_source_manifest": {"ref_id": "m", "role": "immutable_source_manifest", **manifest_ref},
            "source_inventory": {"ref_id": "i", "role": "source_inventory", **inventory_ref},
        }
        docs = {
            "immutable_source_manifest": manifest,
            "source_inventory": inventory,
            "source_audit": source_audit,
            "event_ledger_audit": event_audit,
            "sanitized_ledger_assignment_proof": {
                "inputs": [{"slot": "sealed_event_ledger", **event_ledger_ref}],
            },
        }
        sanitizer_inputs = {
            "sealed_event_ledger": event_ledger,
            "sealed_availability_ledger": availability,
        }
        return refs, docs, sanitizer_inputs

    def _evaluate(self, mutate=None, *, source_checks=None):
        manifest_path, docs, boundary = self._fixture()
        if mutate:
            mutate(docs, boundary)
            for item in json.loads(manifest_path.read_text())["inputs"]:
                role = item["role"]
                ref = write_json(self.root, item["path"], docs[role])
                item.update(ref)
            manifest = json.loads(manifest_path.read_text())
            for item in manifest["inputs"]:
                ref = write_json(self.root, item["path"], docs[item["role"]])
                item.update(ref)
            manifest_path.write_bytes(E.canonical_json_file_bytes(manifest))
        source_return = (
            boundary["facts"],
            boundary["fact_by_id"],
            boundary["event_by_id"],
            boundary["audit_by_id"],
            source_checks if source_checks is not None else [E._check("source", True, True, "EQ", True)],
        )
        sanitizer_return = ({"sealed_event_ledger": {}, "sealed_availability_ledger": {}}, boundary["source_to_opaque"], {value: key for key, value in boundary["source_to_opaque"].items()}, [E._check("sanitizer", True, True, "EQ", True)])
        with mock.patch.object(E, "_verify_sanitized_ledger_chain", return_value=sanitizer_return), mock.patch.object(E, "_verify_source_and_ledger", return_value=source_return), mock.patch.object(E, "_verify_blindness_chain", return_value=[E._check("blind", True, True, "EQ", True)]), mock.patch.object(E, "_verify_primary_isolation_chain", return_value=[E._check("actual_primary_isolation", True, True, "EQ", True)]), mock.patch.object(E, "_runtime_integrity_checks", side_effect=lambda refs, d, e: (E._runtime_cut_by_ordinal(d["runtime_output"]), [E._check("runtime", True, True, "EQ", True)])), mock.patch.object(E, "_verify_post_replay_closure", return_value=[E._check("closure", True, True, "EQ", True)]):
            return E.evaluate_case(self.root, manifest_path), manifest_path

    def test_positive_case_and_deterministic_schema(self):
        first, manifest = self._evaluate()
        second, _ = self._evaluate()
        self.assertEqual(E.canonical_json_file_bytes(first), E.canonical_json_file_bytes(second))
        self.assertTrue(all(row["computed_result"] == "PASS" for row in first["gate_results"] + first["coverage_results"]))
        input_schema = json.loads((STUDY_ROOT / "holdout/schemas/primary_case_gate_evaluator_input.schema.json").read_text())
        output_schema = json.loads((STUDY_ROOT / "holdout/schemas/primary_case_gate_evaluation.schema.json").read_text())
        input_schema.pop("title", None)
        output_schema.pop("title", None)
        _validate_schema_instance(json.loads(manifest.read_text()), input_schema)
        _validate_schema_instance(first, output_schema)

    def test_pl_ind_requires_actual_role_trace_dependency_trace_and_fresh_runtime(self):
        role_ref = write_json(self.root, "run/role_manifest_set.json", {"fixture": True})
        input_ref = write_json(self.root, "run/runtime_input_manifest.json", {"fixture": True})
        runtime_ref = write_json(self.root, "run/runtime_output.json", {"fixture": "runtime"})
        mapped_ref = write_json(self.root, "run/mapped.json", {"fixture": "mapped"})
        bundle_ref = write_json(self.root, "run/runtime_event_ledger_replay_bundle.json", {"fixture": "bundle"})
        executor_rel = "holdout/tools/primary_runtime_replay_executor.py"
        executor_raw = (STUDY_ROOT / executor_rel).read_bytes()
        executor_path = self.root / executor_rel
        executor_path.parent.mkdir(parents=True, exist_ok=True)
        executor_path.write_bytes(executor_raw)
        executor_ref = {
            "path": executor_rel,
            "sha256": hashlib.sha256(executor_raw).hexdigest(),
            "bytes": len(executor_raw),
        }
        input_bindings = [
            {"role": f"role-{index}", "sha256": "0" * 64, "bytes": 1, "schema_id": f"schema-{index}"}
            for index in range(9)
        ]
        output_bindings = [
            {"filename": "runtime_output.json", "schema_id": "ncf.data.runtime-output.v1", "sha256": runtime_ref["sha256"], "bytes": runtime_ref["bytes"]},
            {"filename": "runtime_event_ledger_replay_bundle.json", "schema_id": "ncf.holdout.event-ledger-replay-bundle.v1", "sha256": bundle_ref["sha256"], "bytes": bundle_ref["bytes"]},
            {"filename": "mapped_observation_consumption.json", "schema_id": "ncf.mapped-observation-consumption.v1", "sha256": mapped_ref["sha256"], "bytes": mapped_ref["bytes"]},
        ]
        module_raw = (STUDY_ROOT / "runtime_v2/__init__.py").read_bytes()
        module_path = self.root / "runtime_v2/__init__.py"
        module_path.parent.mkdir(parents=True, exist_ok=True)
        module_path.write_bytes(module_raw)
        replay = {
            "invocation_contract": {
                "executable": executor_ref,
                "input_manifest_sha256": input_ref["sha256"],
                "network_access": "FORBIDDEN",
            },
            "input_bindings": input_bindings,
            "runtime_output": output_bindings[0],
            "event_ledger_replay_bundle": output_bindings[1],
            "mapped_observation_consumption": output_bindings[2],
            "dependency_trace": {
                "schema_version": "NCF-PRIMARY-RUNTIME-DEPENDENCY-TRACE-1.0.0",
                "trace_scope": "ACTUAL_PRIMARY_CASE_RUNTIME_REPLAY_PROCESS",
                "module_origins": [{
                    "module": "runtime_v2",
                    "origin": "runtime_v2/__init__.py",
                    "classification": "NCF_FROZEN_SOURCE",
                    "sha256": hashlib.sha256(module_raw).hexdigest(),
                    "bytes": len(module_raw),
                }],
                "outside_allowlist": [],
                "io_trace": {"input_bindings": input_bindings, "produced_artifacts": output_bindings},
                "network_guard": {
                    "control": "APPLICATION_SOCKET_GUARD_OFFLINE_NOT_OS_SANDBOX",
                    "attempt_count": 0,
                    "attempts": [],
                    "passed": True,
                },
            },
        }
        seal_ref = write_json(self.root, "run/runtime_replay_seal.json", replay)
        refs = {
            "role_manifest_set": role_ref,
            "runtime_input_manifest": input_ref,
            "runtime_output": runtime_ref,
            "mapped_observation_consumption": mapped_ref,
            "runtime_replay_seal": seal_ref,
        }
        docs = {
            "runtime_replay_seal": replay,
            "preprimary_seal": {"bindings": {"primary_execution": {"primary_runtime_replay_executor": executor_ref}}},
            "sanitized_ledger_replay_verification": {
                "schema_version": "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-REPLAY-VERIFICATION-1.0.0",
                "fresh_replay": {"status": "PASS"},
            },
        }

        def fake_run(command, **_kwargs):
            out_dir = Path(command[command.index("--output-dir") + 1])
            out_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.root / runtime_ref["path"], out_dir / "runtime_output.json")
            shutil.copy2(self.root / mapped_ref["path"], out_dir / "mapped_observation_consumption.json")
            shutil.copy2(self.root / bundle_ref["path"], out_dir / "runtime_event_ledger_replay_bundle.json")
            shutil.copy2(self.root / seal_ref["path"], out_dir / "runtime_replay_seal.json")
            return subprocess.CompletedProcess(command, 0, b"{}\n", b"")

        role_validation = {
            "status": "PASS",
            "role_count": 8,
            "roles": list(E.ROLE_NAMES),
            "aggregate_sha256": role_ref["sha256"],
        }
        with mock.patch.object(E, "validate_role_manifest_set", return_value=role_validation), mock.patch.object(E.subprocess, "run", side_effect=fake_run):
            checks = E._verify_primary_isolation_chain(self.root, refs=refs, docs=docs)
        self.assertTrue(all(row["passed"] for row in checks))

        docs["runtime_replay_seal"]["dependency_trace"]["outside_allowlist"] = [
            {"module": "foreign", "origin": "foreign.py", "reason": "NOT_NCF_OR_STDLIB"}
        ]
        with mock.patch.object(E, "validate_role_manifest_set", return_value=role_validation), mock.patch.object(E.subprocess, "run", side_effect=fake_run):
            checks = E._verify_primary_isolation_chain(self.root, refs=refs, docs=docs)
        by_id = {row["check_id"]: row for row in checks}
        self.assertFalse(by_id["actual_primary_runtime_dependency_trace_allowlisted"]["passed"])

    def test_each_reliable_negative_dimension_is_required(self):
        for dimension in E.RELIABLE_NEGATIVE_DIMENSIONS:
            def mutate(docs, _boundary, dimension=dimension):
                docs["mapped_observation_consumption"]["records"][1]["reliability"]["basis"][dimension] = False
            result, _ = self._evaluate(mutate)
            row = next(row for row in result["coverage_results"] if row["subject_id"] == "reliable_negative_evidence")
            self.assertEqual(row["computed_result"], "FAIL", dimension)

    def test_manual_failure_propagates(self):
        evidence = write_json(self.root, "audit/evidence.json", {"bad": True})
        def mutate(docs, _boundary):
            docs["audit_report"]["findings"] = [{"subject_kind": "GATE", "subject_id": "PL-DX-002", "verdict": "FAIL", "evidence_refs": [evidence]}]
        result, _ = self._evaluate(mutate)
        row = next(row for row in result["gate_results"] if row["subject_id"] == "PL-DX-002")
        self.assertEqual(row["computed_result"], "FAIL")

    def test_pl_led_fails_on_source_provenance_or_time_failure_without_case_fallback(self):
        for check_id in (
            "event_provenance_and_audit_exact",
            "source_availability_and_occurred_time_semantics_exact",
        ):
            source_checks = [E._check(check_id, False, True, "EQ", False)]
            result, _ = self._evaluate(source_checks=source_checks)
            led = next(row for row in result["gate_results"] if row["subject_id"] == "PL-LED-001")
            self.assertEqual(led["computed_result"], "FAIL", check_id)
            self.assertIn(check_id, {row["check_id"] for row in led["checks"]})

    def test_pl_led_fails_when_runtime_consumption_omits_a_source_observation(self):
        def mutate(docs, _boundary):
            docs["mapped_observation_consumption"]["records"].pop()
            docs["mapped_observation_consumption"]["event_count"] -= 1

        result, _ = self._evaluate(mutate)
        led = next(row for row in result["gate_results"] if row["subject_id"] == "PL-LED-001")
        self.assertEqual(led["computed_result"], "FAIL")
        check = next(row for row in led["checks"] if row["check_id"] == "mapped_observation_consumption_denominator_exact")
        self.assertFalse(check["passed"])

    def test_pl_led_contains_full_independent_evidence_scope(self):
        result, _ = self._evaluate()
        led = next(row for row in result["gate_results"] if row["subject_id"] == "PL-LED-001")
        check_ids = {row["check_id"] for row in led["checks"]}
        self.assertTrue(
            {
                "source",
                "sanitizer",
                "runtime",
                "closure",
                "mapped_observation_consumption_denominator_exact",
                "complete_source_event_denominator_processed_by_runtime",
            }.issubset(check_ids)
        )

    def test_oracle_reused_source_fact_fails(self):
        def mutate(docs, _boundary):
            docs["oracle_targets"]["concurrent_targets"][1]["source_fact_ids"] = ["F1"]
            docs["oracle_targets"]["concurrent_targets"][1]["source_event_ids"] = ["EV0"]
        result, _ = self._evaluate(mutate)
        row = next(row for row in result["gate_results"] if row["subject_id"] == "PL-DX-002")
        self.assertEqual(row["computed_result"], "FAIL")

    def test_no_free_summary_roles_no_recursive_or_undefined_evaluate_case(self):
        self.assertTrue({"diagnostic_localization", "prediction_scores", "consumption_crosscheck"}.isdisjoint(E.CASE_INPUT_ROLES))
        tree = ast.parse(TOOL_PATH.read_text(encoding="utf-8"))
        functions = {node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn("evaluate_case", functions)
        helper = functions["_verify_source_and_ledger"]
        self.assertFalse(any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "_verify_source_and_ledger" for node in ast.walk(helper)))
        calls = {node.func.id for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertTrue({"evaluate_case", "evaluate_report"}.issubset(functions))
        self.assertNotIn("diagnostic_localization", calls)

    def test_real_sanitizer_dual_output_replay_is_consumed_by_evaluator(self):
        _fixture, refs, docs, _path, _ref = self._real_sanitizer_chain()
        raw_inputs, source_to_opaque, opaque_to_source, checks = E._verify_sanitized_ledger_chain(
            self.root, refs=refs, docs=docs
        )
        self.assertTrue(all(row["passed"] for row in checks), checks)
        self.assertEqual(set(raw_inputs), {
            "sealed_event_ledger", "sealed_availability_ledger", "sealed_concept_map",
            "sanitized_id_type_unit_registry", "combined_preprimary_seal",
        })
        self.assertEqual(source_to_opaque["source-event-alpha"], "EV-00000001")
        self.assertEqual(opaque_to_source["EV-00000004"], "source-event-delta")

    def test_source_ledger_audit_recomputes_provenance_locators_denominator_and_time(self):
        refs, docs, sanitizer_inputs = self._source_ledger_audit_fixture()
        result = E._verify_source_and_ledger(
            self.root,
            refs=refs,
            docs=docs,
            sanitizer_inputs=sanitizer_inputs,
            source_to_opaque={"source-event-1": "EV-00000001"},
        )
        checks = {row["check_id"]: row for row in result[-1]}
        self.assertTrue(all(row["passed"] for row in checks.values()), checks)

        # A semantically changed available epoch may still be a valid bounded
        # ordinal.  It must nevertheless disagree with the independent audit
        # row and fail PL-LED evidence rather than silently becoming truth.
        changed = copy.deepcopy(sanitizer_inputs)
        changed["sealed_availability_ledger"]["events"][0]["availability_evidence"]["exact_epoch"] = 1
        result = E._verify_source_and_ledger(
            self.root,
            refs=refs,
            docs=docs,
            sanitizer_inputs=changed,
            source_to_opaque={"source-event-1": "EV-00000001"},
        )
        checks = {row["check_id"]: row for row in result[-1]}
        self.assertFalse(checks["event_type_time_and_disposition_audit_row_exhaustive"]["passed"])

        changed = copy.deepcopy(sanitizer_inputs)
        changed["sealed_event_ledger"]["events"][0]["source_fact_ids"] = ["MISSING"]
        result = E._verify_source_and_ledger(
            self.root,
            refs=refs,
            docs=docs,
            sanitizer_inputs=changed,
            source_to_opaque={"source-event-1": "EV-00000001"},
        )
        checks = {row["check_id"]: row for row in result[-1]}
        self.assertFalse(checks["event_provenance_and_audit_exact"]["passed"])
        self.assertFalse(checks["source_fact_event_denominator_bipartite_exact"]["passed"])

    def test_forged_sanitizer_verification_and_output_bindings_fail_closed(self):
        _fixture, refs, docs, verification_path, plain_ref = self._real_sanitizer_chain()
        pristine_refs = copy.deepcopy(refs)
        pristine_docs = copy.deepcopy(docs)
        forged = copy.deepcopy(docs)
        forged["sanitized_ledger_replay_verification"]["fresh_replay"]["outputs"]["ledger"]["sha256"] = "0" * 64
        verification_path.write_bytes(E.canonical_json_file_bytes(forged["sanitized_ledger_replay_verification"]))
        refs["sanitized_ledger_replay_verification"].update(plain_ref(verification_path))
        _raw, _forward, _reverse, checks = E._verify_sanitized_ledger_chain(self.root, refs=refs, docs=forged)
        by_id = {row["check_id"]: row for row in checks}
        self.assertFalse(by_id["sanitizer_verification_rebuilt_exactly"]["passed"])
        self.assertFalse(by_id["sanitizer_fresh_replay_outputs_exact"]["passed"])

        verification_path.write_bytes(E.canonical_json_file_bytes(pristine_docs["sanitized_ledger_replay_verification"]))
        refs = pristine_refs
        docs = pristine_docs
        docs["sanitized_ledger_assignment_proof"]["output_ledger"]["sha256"] = "f" * 64
        _raw, _forward, _reverse, checks = E._verify_sanitized_ledger_chain(self.root, refs=refs, docs=docs)
        by_id = {row["check_id"]: row for row in checks}
        self.assertFalse(by_id["sanitizer_direct_outputs_bound"]["passed"])


if __name__ == "__main__":
    unittest.main()
