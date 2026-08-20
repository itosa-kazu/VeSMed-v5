from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from compile_availability_epochs import compile_ledger  # noqa: E402
from compile_primary_case_mechanical_closure import (  # noqa: E402
    ClosureError,
    ROLES,
    run_compile,
)
from validate_primary_case_mechanical_closure import ValidationError, validate  # noqa: E402
from verify_compiled_availability import verify as verify_compiled_availability  # noqa: E402


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ref(root: Path, path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def typed(root: Path, path: Path, data_class: str, schema_id: str) -> dict:
    return {**ref(root, path), "data_class": data_class, "schema_id": schema_id}


class ClosureFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        for rel in (
            "holdout/tools/compile_availability_epochs.py",
            "holdout/tools/test_compile_availability_epochs.py",
            "holdout/tools/verify_compiled_availability.py",
            "holdout/tools/test_verify_compiled_availability.py",
            "holdout/tools/producer_replay_verifier.py",
            "holdout/tools/verify_evaluator_sanitized_runtime_ledger.py",
            "holdout/tools/compile_evaluator_sanitized_runtime_ledger.py",
            "holdout/tools/compile_primary_case_mechanical_closure.py",
            "holdout/tools/validate_primary_case_mechanical_closure.py",
            "holdout/schemas/primary_availability_ledger.schema.json",
            "holdout/schemas/compiled_guaranteed_availability.schema.json",
            "holdout/schemas/availability_compiler_proof.schema.json",
        ):
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE_ROOT / rel, target)
        self.protocol_path = root / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json"
        self.article = root / "run/source/article.txt"
        self.article.parent.mkdir(parents=True, exist_ok=True)
        self.article.write_text("immutable selected source bytes\n", encoding="utf-8")
        self.selected_manifest_path = root / "run/screener/immutable_source_manifest.json"
        article_ref = ref(root, self.article)
        source_rows = [{**article_ref, "source_role": "PRIMARY_ARTICLE"}]
        self.selected_manifest = {
            "schema_version": "NCF-PRIMARY-SELECTED-IMMUTABLE-SOURCE-MANIFEST-1.0.0",
            "selected_source": article_ref,
            "source_artifacts": source_rows,
            "inventory_sha256": hashlib.sha256(canonical(source_rows)).hexdigest(),
            "immutable": True,
            "inventory_complete": True,
        }
        write_json(self.selected_manifest_path, self.selected_manifest)
        self.inventory_path = root / "run/extractor/source_inventory.json"
        inventory_rows = [article_ref]
        self.inventory = {
            "schema_version": "NCF-PRIMARY-EXTRACTED-SOURCE-INVENTORY-1.0.0",
            "selected_source_manifest": ref(root, self.selected_manifest_path),
            "source_artifacts": inventory_rows,
            "inventory_sha256": hashlib.sha256(canonical(inventory_rows)).hexdigest(),
        }
        write_json(self.inventory_path, self.inventory)
        self.runtime_event = {
            "event_kind": "OBSERVATION",
            "source_concept_token": "source-concept-1",
            "typed_value": {"kind": "NUMBER", "canonical": "1"},
            "unit": None,
            "observed_epoch_ordinal": 1,
            "reliability": "HIGH",
            "evidence_qualification": {
                "explicit_assertion": "TRUE", "target_scope": "TRUE",
                "adequate_method": "TRUE", "adequate_timing": "TRUE",
                "adequate_reliability": "TRUE",
            },
            "source_alternative_representation_group_id": None,
        }
        self.event_path = root / "run/extractor/event_ledger.json"
        self.event_ledger = {
            "schema_version": "ncf.data.event-ledger.v1",
            "events": [
                {
                    "source_event_id": "source-event-1",
                    "source_locator": {
                        "artifact_path": article_ref["path"],
                        "artifact_sha256": article_ref["sha256"],
                        "artifact_bytes": article_ref["bytes"],
                        "locator": "line:1",
                    },
                    "runtime_event": self.runtime_event,
                }
            ],
        }
        write_json(self.event_path, self.event_ledger)
        self.raw_availability_path = root / "run/extractor/availability_ledger.json"
        self.raw_availability = {
            "schema_version": "ncf.primary-availability-ledger.v1",
            "publication_order_used_as_clinical_availability": False,
            "events": [
                {
                    "source_event_id": "source-event-1",
                    "availability_evidence": {"kind": "EXACT", "exact_epoch": 2},
                    "runtime_event": self.runtime_event,
                }
            ],
        }
        write_json(self.raw_availability_path, self.raw_availability)
        self.compiled_path = root / "run/extractor/compiled_guaranteed_availability.json"
        write_json(self.compiled_path, compile_ledger(self.raw_availability))
        self.combined_seal_path = root / "holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json"
        unsigned_seal = {
            "status": "SEALED_BEFORE_PRIMARY_CASE_SELECTION",
            "bindings": {
                rel.replace("/", "_").replace(".", "_"): ref(root, root / rel)
                for rel in (
                    "holdout/tools/compile_availability_epochs.py",
                    "holdout/tools/test_compile_availability_epochs.py",
                    "holdout/schemas/primary_availability_ledger.schema.json",
                    "holdout/schemas/compiled_guaranteed_availability.schema.json",
                    "holdout/tools/verify_compiled_availability.py",
                    "holdout/tools/test_verify_compiled_availability.py",
                    "holdout/schemas/availability_compiler_proof.schema.json",
                    "holdout/tools/producer_replay_verifier.py",
                )
            },
        }
        write_json(self.combined_seal_path, {
            **unsigned_seal,
            "payload_sha256": hashlib.sha256(canonical(unsigned_seal)).hexdigest(),
        })
        self.proof_path = root / "run/source_auditor/sealed_availability_compiler_proof.json"
        self.proof = verify_compiled_availability(
            root,
            self.raw_availability_path,
            self.compiled_path,
            self.combined_seal_path,
        )
        write_json(self.proof_path, self.proof)
        self.sealed_compiled_path = root / "run/source_auditor/sealed_compiled_guaranteed_availability.json"
        self.sealed_proof_path = self.proof_path
        self.sealed_compiled_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.compiled_path, self.sealed_compiled_path)
        self.aggregate_path = root / "run/role_manifest_set.json"
        self.audit_path = root / "run/event_ledger_audit.json"
        self.lineage_path = root / "run/case_access_lineage.json"
        self.manifest_paths: dict[str, Path] = {}
        self.trace_paths: dict[str, Path] = {}
        self._build_roles()
        # Re-seal after the canonical protocol exists, then regenerate the
        # source-auditor proof against that exact authority and rebuild refs.
        seal = json.loads(self.combined_seal_path.read_text(encoding="utf-8"))
        seal["bindings"]["canonical_protocol"] = ref(self.root, self.protocol_path)
        seal.pop("payload_sha256", None)
        seal["payload_sha256"] = hashlib.sha256(canonical(seal)).hexdigest()
        write_json(self.combined_seal_path, seal)
        self.proof = verify_compiled_availability(
            self.root,
            self.raw_availability_path,
            self.compiled_path,
            self.combined_seal_path,
        )
        write_json(self.proof_path, self.proof)
        self._build_roles()

    def _artifact_rows(self) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
        outputs = {role: [] for role in ROLES}
        outputs["screener"] = [typed(
            self.root, self.selected_manifest_path, "immutable_source_manifest",
            "ncf.primary-selected-immutable-source-manifest.v1",
        )]
        outputs["extractor"] = [
            typed(self.root, self.inventory_path, "source_inventory", "ncf.primary-extracted-source-inventory.v1"),
            typed(self.root, self.event_path, "event_ledger", "ncf.data.event-ledger.v1"),
            typed(self.root, self.raw_availability_path, "availability_ledger", "ncf.data.availability-ledger.v1"),
            typed(self.root, self.compiled_path, "compiled_guaranteed_availability", "ncf.compiled-guaranteed-availability.v1"),
        ]
        outputs["source_auditor"] = [
            typed(self.root, self.sealed_compiled_path, "sealed_compiled_guaranteed_availability", "ncf.compiled-guaranteed-availability.v1"),
            typed(self.root, self.sealed_proof_path, "sealed_availability_compiler_proof", "ncf.availability-compiler-proof.v1"),
        ]
        inputs = {role: [] for role in ROLES}
        inputs["extractor"] = [copy.deepcopy(outputs["screener"][0])]
        inputs["source_auditor"] = [
            *[copy.deepcopy(row) for row in outputs["extractor"]],
            typed(
                self.root,
                self.combined_seal_path,
                "combined_preprimary_seal",
                "ncf.data.combined-preprimary-seal.v1",
            ),
        ]
        return inputs, outputs

    def _build_roles(self, *, write_protocol_file: bool = True) -> None:
        inputs, outputs = self._artifact_rows()
        edges = [
            {"producer_role": "screener", "data_class": "immutable_source_manifest", "consumer_roles": ["extractor"]},
            *[
                {"producer_role": "extractor", "data_class": row["data_class"], "consumer_roles": ["source_auditor"]}
                for row in outputs["extractor"]
            ],
        ]
        schema_ids = {
            row["data_class"]: row["schema_id"]
            for role in ROLES
            for row in [*inputs[role], *outputs[role]]
        }
        protocol = {
            "protocol_version": "1.1.0",
            "roles": {
                role: {
                    "allowed_input_data_classes": [row["data_class"] for row in inputs[role]],
                    "allowed_output_data_classes": [row["data_class"] for row in outputs[role]],
                    "forbidden_data_classes": [],
                    "case_identity_exposure": "FORBIDDEN" if role in {"concept_mapper", "evaluator"} else "PERMITTED",
                    "network_access_policy": (
                        "REQUIRED_NCBI_HTTPS_GET_ONLY" if role == "scout" else "FORBIDDEN"
                    ),
                }
                for role in ROLES
            },
            "role_manifest": {
                "producer_consumer_edges": edges,
                "presealed_root_data_classes": ["combined_preprimary_seal"],
                "presealed_root_asset_paths": {
                    "protocol": self.protocol_path.relative_to(self.root).as_posix(),
                    "combined_preprimary_seal": self.combined_seal_path.relative_to(self.root).as_posix(),
                },
                "data_class_schema_ids": schema_ids,
            },
            "primary_execution_asset_contract": {
                "evaluator_sanitized_runtime_ledger_compiler": {
                    "input_data_classes": [
                        "sealed_event_ledger",
                        "sealed_compiled_guaranteed_availability",
                        "sealed_availability_compiler_proof",
                        "sealed_concept_map",
                        "sanitized_id_type_unit_registry",
                        "combined_preprimary_seal",
                    ]
                }
            },
        }
        if write_protocol_file:
            write_json(self.protocol_path, protocol)
        prior_manifest_refs: dict[str, dict] = {}
        aggregate_rows = []
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        producer_for = {"immutable_source_manifest": "screener"} | {
            row["data_class"]: "extractor" for row in outputs["extractor"]
        }
        for index, role in enumerate(ROLES):
            prompt = self.root / f"run/{role}/prompt.txt"
            parent = self.root / f"run/{role}/parent.json"
            prompt.parent.mkdir(parents=True, exist_ok=True)
            prompt.write_text(f"fixed mechanical fixture {role}\n", encoding="utf-8")
            write_json(parent, {"role": role})
            for row in inputs[role]:
                if row["data_class"] == "combined_preprimary_seal":
                    row["producer"] = {
                        "kind": "PRESEALED_ROOT",
                        "seal": ref(self.root, self.combined_seal_path),
                    }
                else:
                    producer_role = producer_for[row["data_class"]]
                    producer_manifest_ref = prior_manifest_refs[producer_role]
                    row["producer"] = {
                        "kind": "ROLE_OUTPUT",
                        "role": producer_role,
                        "run_id": f"run-{producer_role}",
                        "manifest_path": producer_manifest_ref["path"],
                        "manifest_sha256": producer_manifest_ref["sha256"],
                        "manifest_bytes": producer_manifest_ref["bytes"],
                    }
            tool_trace_path = self.root / f"run/{role}/tool_trace.json"
            accesses = []
            for row in inputs[role]:
                accesses.append({
                    "sequence": len(accesses), "operation": "READ", "artifact_kind": "INPUT",
                    **{key: row[key] for key in ("path", "sha256", "bytes", "data_class", "schema_id")},
                    "access_count": 1,
                })
            for row in outputs[role]:
                accesses.append({
                    "sequence": len(accesses), "operation": "WRITE", "artifact_kind": "OUTPUT",
                    **{key: row[key] for key in ("path", "sha256", "bytes", "data_class", "schema_id")},
                    "access_count": 1,
                })
            for kind, path, data_class, schema_id in (
                ("PROMPT_OR_COMMAND", prompt, "role_prompt_or_command", "ncf.role.prompt-or-command.v1"),
                ("PARENT_PACKET", parent, "role_parent_packet", "ncf.role.parent-packet.v1"),
            ):
                accesses.append({
                    "sequence": len(accesses), "operation": "READ", "artifact_kind": kind,
                    **ref(self.root, path), "data_class": data_class, "schema_id": schema_id,
                    "access_count": 1,
                })
            lineage = [{"tool_id": "fixture", "version_or_build": "1", "invocation_id": f"inv-{role}"}]
            if role == "extractor":
                lineage += [
                    {
                        "tool_id": "holdout/tools/compile_availability_epochs.py",
                        "version_or_build": ref(self.root, self.root / "holdout/tools/compile_availability_epochs.py")["sha256"],
                        "invocation_id": "availability-compile",
                    },
                ]
            if role == "source_auditor":
                lineage += [
                    {
                        "tool_id": "holdout/tools/verify_compiled_availability.py",
                        "version_or_build": ref(self.root, self.root / "holdout/tools/verify_compiled_availability.py")["sha256"],
                        "invocation_id": "availability-verify",
                    },
                ]
            network_requests = []
            if role == "scout":
                network_requests = [{
                    "sequence": 0,
                    "method": "GET",
                    "request_url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=x",
                    "response_sha256": "1" * 64,
                    "response_bytes": 1,
                    "retrieved_at": base.isoformat(),
                }]
            trace = {
                "schema_version": "NCF-PRIMARY-ROLE-TOOL-ACCESS-TRACE-1.0.0",
                "role": role,
                "run_id": f"run-{role}",
                "execution_kind": "HYBRID",
                "case_identity_exposed": role not in {"concept_mapper", "evaluator"},
                "prompt_or_command_sha256": ref(self.root, prompt)["sha256"],
                "parent_packet_sha256": ref(self.root, parent)["sha256"],
                "tool_lineage": lineage,
                "accesses": accesses,
                "network_requests": network_requests,
                "trace_complete": True,
                "undeclared_access_detected": False,
                "network_access_detected": bool(network_requests),
            }
            write_json(tool_trace_path, trace)
            start = base + timedelta(minutes=index * 10)
            finish = start + timedelta(minutes=5)
            manifest = {
                "schema_version": "NCF-PRIMARY-ROLE-MANIFEST-1.1.0",
                "role": role,
                "run_id": f"run-{role}",
                "started_at": start.isoformat(),
                "finished_at": finish.isoformat(),
                "case_identity_exposed": role not in {"concept_mapper", "evaluator"},
                "inputs": inputs[role],
                "outputs": outputs[role],
                "observed_data_classes": [row["data_class"] for row in inputs[role]],
                "attestations": {
                    "only_declared_inputs_observed": True,
                    "no_forbidden_data_class_observed": True,
                    "no_undeclared_output_written": True,
                    "no_artifact_modified_after_input_hash": True,
                },
                "prompt_or_command": ref(self.root, prompt),
                "tool_trace": ref(self.root, tool_trace_path),
                "parent_packet": ref(self.root, parent),
            }
            manifest_path = self.root / f"run/{role}/manifest.json"
            write_json(manifest_path, manifest)
            self.manifest_paths[role] = manifest_path
            self.trace_paths[role] = tool_trace_path
            manifest_ref = ref(self.root, manifest_path)
            prior_manifest_refs[role] = manifest_ref
            aggregate_rows.append({"role": role, "run_id": f"run-{role}", **manifest_ref})
        aggregate = {
            "schema_version": "NCF-PRIMARY-ROLE-MANIFEST-SET-1.0.0",
            "protocol": ref(self.root, self.protocol_path),
            "manifests": aggregate_rows,
        }
        write_json(self.aggregate_path, aggregate)

    def reseal_after_protocol_edit(self) -> None:
        seal = json.loads(self.combined_seal_path.read_text(encoding="utf-8"))
        seal["bindings"]["canonical_protocol"] = ref(self.root, self.protocol_path)
        seal.pop("payload_sha256", None)
        seal["payload_sha256"] = hashlib.sha256(canonical(seal)).hexdigest()
        write_json(self.combined_seal_path, seal)
        self.proof = verify_compiled_availability(
            self.root,
            self.raw_availability_path,
            self.compiled_path,
            self.combined_seal_path,
        )
        write_json(self.proof_path, self.proof)
        self._build_roles(write_protocol_file=False)

    def compile(self) -> None:
        self.audit_path.unlink(missing_ok=True)
        self.lineage_path.unlink(missing_ok=True)
        run_compile(self.root, self.aggregate_path, self.audit_path, self.lineage_path)


class PrimaryCaseMechanicalClosureTests(unittest.TestCase):
    def test_formal_shape_positive_and_fresh_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            fx.compile()
            report = validate(fx.root, fx.aggregate_path, fx.audit_path, fx.lineage_path)
            self.assertEqual(report["status"], "PASS")
            self.assertFalse(report["medical_judgment_performed"])
            lineage = json.loads(fx.lineage_path.read_text(encoding="utf-8"))
            self.assertEqual(lineage["role_count"], 8)
            self.assertTrue(lineage["availability_chain"]["sanitizer_raw_timing_access_forbidden"])
            audit_ref = lineage["event_ledger_audit"]
            audit_path = fx.root / audit_ref["path"]
            self.assertTrue(audit_path.is_file())
            self.assertEqual(ref(fx.root, audit_path), audit_ref)

    def test_hand_authored_available_at_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            value = json.loads(fx.raw_availability_path.read_text(encoding="utf-8"))
            value["events"][0]["runtime_event"]["available_at"] = 1
            write_json(fx.raw_availability_path, value)
            fx._build_roles()
            with self.assertRaisesRegex(ClosureError, "hand-authored available_at|pre-populates"):
                fx.compile()

    def test_selected_source_inventory_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            inventory = json.loads(fx.inventory_path.read_text(encoding="utf-8"))
            inventory["source_artifacts"] = []
            inventory["inventory_sha256"] = hashlib.sha256(canonical([])).hexdigest()
            write_json(fx.inventory_path, inventory)
            fx._build_roles()
            with self.assertRaisesRegex(ClosureError, "not exact selected-source inventory"):
                fx.compile()

    def test_event_locator_outside_inventory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            event = json.loads(fx.event_path.read_text(encoding="utf-8"))
            event["events"][0]["source_locator"]["artifact_sha256"] = "0" * 64
            write_json(fx.event_path, event)
            fx._build_roles()
            with self.assertRaisesRegex(ClosureError, "outside exact inventory"):
                fx.compile()

    def test_compiled_availability_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            value = json.loads(fx.compiled_path.read_text(encoding="utf-8"))
            value["released_events"][0]["guaranteed_available_epoch"] = 1
            write_json(fx.compiled_path, value)
            shutil.copy2(fx.compiled_path, fx.sealed_compiled_path)
            fx._build_roles()
            with self.assertRaisesRegex(ClosureError, "not exact frozen-compiler output"):
                fx.compile()

    def test_availability_proof_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            proof = json.loads(fx.proof_path.read_text(encoding="utf-8"))
            proof["fresh_replay"]["output_sha256"] = "0" * 64
            write_json(fx.proof_path, proof)
            fx._build_roles()
            with self.assertRaisesRegex(ClosureError, "exact frozen-verifier output"):
                fx.compile()

    def test_tool_trace_extra_access_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            trace_path = fx.trace_paths["extractor"]
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            extra = copy.deepcopy(trace["accesses"][0])
            extra["sequence"] = len(trace["accesses"])
            extra["path"] = "run/undeclared.json"
            trace["accesses"].append(extra)
            write_json(trace_path, trace)
            manifest_path = fx.manifest_paths["extractor"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tool_trace"] = ref(fx.root, trace_path)
            write_json(manifest_path, manifest)
            aggregate = json.loads(fx.aggregate_path.read_text(encoding="utf-8"))
            row = next(row for row in aggregate["manifests"] if row["role"] == "extractor")
            row.update(ref(fx.root, manifest_path))
            write_json(fx.aggregate_path, aggregate)
            with self.assertRaisesRegex(ClosureError, "not an exact read/write inventory"):
                fx.compile()

    def test_source_auditor_may_not_change_compiled_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            fx.sealed_compiled_path.write_text("{}\n", encoding="utf-8")
            fx._build_roles()
            with self.assertRaisesRegex(ClosureError, "changes compiler bytes"):
                fx.compile()

    def test_sanitizer_raw_timing_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            protocol = json.loads(fx.protocol_path.read_text(encoding="utf-8"))
            protocol["primary_execution_asset_contract"]["evaluator_sanitized_runtime_ledger_compiler"]["input_data_classes"].append("sealed_availability_ledger")
            write_json(fx.protocol_path, protocol)
            fx.reseal_after_protocol_edit()
            with self.assertRaisesRegex(ClosureError, "compiled-availability-only"):
                fx.compile()

    def test_sanitizer_undeclared_timing_side_channel_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            protocol = json.loads(fx.protocol_path.read_text(encoding="utf-8"))
            protocol["primary_execution_asset_contract"]["evaluator_sanitized_runtime_ledger_compiler"][
                "input_data_classes"
            ].append("raw_timing_shadow")
            write_json(fx.protocol_path, protocol)
            fx.reseal_after_protocol_edit()
            with self.assertRaisesRegex(ClosureError, "compiled-availability-only"):
                fx.compile()

    def test_bogus_producer_manifest_lineage_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            manifest_path = fx.manifest_paths["source_auditor"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            target = next(row for row in manifest["inputs"] if row["data_class"] == "availability_ledger")
            target["producer"]["manifest_sha256"] = "0" * 64
            write_json(manifest_path, manifest)
            aggregate = json.loads(fx.aggregate_path.read_text(encoding="utf-8"))
            next(row for row in aggregate["manifests"] if row["role"] == "source_auditor").update(
                ref(fx.root, manifest_path)
            )
            write_json(fx.aggregate_path, aggregate)
            with self.assertRaisesRegex(ClosureError, "producer manifest lineage mismatch"):
                fx.compile()

    def test_evaluator_cannot_read_raw_availability_even_with_matching_trace(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            manifest_path = fx.manifest_paths["evaluator"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw_input = typed(
                fx.root,
                fx.raw_availability_path,
                "availability_ledger",
                "ncf.data.availability-ledger.v1",
            )
            extractor_ref = ref(fx.root, fx.manifest_paths["extractor"])
            raw_input["producer"] = {
                "kind": "ROLE_OUTPUT",
                "role": "extractor",
                "run_id": "run-extractor",
                "manifest_path": extractor_ref["path"],
                "manifest_sha256": extractor_ref["sha256"],
                "manifest_bytes": extractor_ref["bytes"],
            }
            manifest["inputs"].append(raw_input)
            manifest["observed_data_classes"].append("availability_ledger")
            trace_path = fx.trace_paths["evaluator"]
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["accesses"].append({
                "sequence": len(trace["accesses"]),
                "operation": "READ",
                "artifact_kind": "INPUT",
                **{key: raw_input[key] for key in ("path", "sha256", "bytes", "data_class", "schema_id")},
                "access_count": 1,
            })
            write_json(trace_path, trace)
            manifest["tool_trace"] = ref(fx.root, trace_path)
            write_json(manifest_path, manifest)
            aggregate = json.loads(fx.aggregate_path.read_text(encoding="utf-8"))
            next(row for row in aggregate["manifests"] if row["role"] == "evaluator").update(
                ref(fx.root, manifest_path)
            )
            write_json(fx.aggregate_path, aggregate)
            with self.assertRaisesRegex(ClosureError, "direct source/timing ledger access"):
                fx.compile()

    def test_resealed_protocol_cannot_authorize_evaluator_raw_timing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            protocol = json.loads(fx.protocol_path.read_text(encoding="utf-8"))
            protocol["roles"]["evaluator"]["allowed_input_data_classes"].append(
                "availability_ledger"
            )
            protocol["role_manifest"]["data_class_schema_ids"]["availability_ledger"] = (
                "ncf.data.availability-ledger.v1"
            )
            protocol["role_manifest"]["producer_consumer_edges"].append({
                "producer_role": "extractor",
                "data_class": "availability_ledger",
                "consumer_roles": ["source_auditor", "evaluator"],
            })
            # Remove the original edge for the same producer/data class so the
            # malicious protocol remains internally self-consistent.
            protocol["role_manifest"]["producer_consumer_edges"] = [
                edge for edge in protocol["role_manifest"]["producer_consumer_edges"]
                if not (
                    edge["producer_role"] == "extractor"
                    and edge["data_class"] == "availability_ledger"
                    and edge["consumer_roles"] == ["source_auditor"]
                )
            ]
            write_json(fx.protocol_path, protocol)
            fx.reseal_after_protocol_edit()

            manifest_path = fx.manifest_paths["evaluator"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            raw_input = typed(
                fx.root, fx.raw_availability_path, "availability_ledger",
                "ncf.data.availability-ledger.v1",
            )
            extractor_ref = ref(fx.root, fx.manifest_paths["extractor"])
            raw_input["producer"] = {
                "kind": "ROLE_OUTPUT", "role": "extractor", "run_id": "run-extractor",
                "manifest_path": extractor_ref["path"],
                "manifest_sha256": extractor_ref["sha256"],
                "manifest_bytes": extractor_ref["bytes"],
            }
            manifest["inputs"].append(raw_input)
            manifest["observed_data_classes"].append("availability_ledger")
            trace_path = fx.trace_paths["evaluator"]
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["accesses"].append({
                "sequence": len(trace["accesses"]), "operation": "READ",
                "artifact_kind": "INPUT", "access_count": 1,
                **{key: raw_input[key] for key in (
                    "path", "sha256", "bytes", "data_class", "schema_id",
                )},
            })
            write_json(trace_path, trace)
            manifest["tool_trace"] = ref(fx.root, trace_path)
            write_json(manifest_path, manifest)
            aggregate = json.loads(fx.aggregate_path.read_text(encoding="utf-8"))
            next(row for row in aggregate["manifests"] if row["role"] == "evaluator").update(
                ref(fx.root, manifest_path)
            )
            write_json(fx.aggregate_path, aggregate)
            with self.assertRaisesRegex(ClosureError, "direct source/timing ledger access"):
                fx.compile()

    def test_fake_sealed_executable_output_is_rejected_before_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            protocol = json.loads(fx.protocol_path.read_text(encoding="utf-8"))
            protocol["roles"]["evaluator"]["allowed_input_data_classes"].append(
                "evaluator_sanitized_runtime_ledger"
            )
            protocol["role_manifest"]["data_class_schema_ids"][
                "evaluator_sanitized_runtime_ledger"
            ] = "ncf.data.evaluator-sanitized-runtime-ledger.v1"
            protocol["role_manifest"]["external_producer_edges"] = [{
                "producer_kind": "SEALED_EXECUTABLE_OUTPUT",
                "producer_id": "evaluator-sanitized-runtime-ledger-compiler-v1",
                "data_class": "evaluator_sanitized_runtime_ledger",
                "consumer_roles": ["evaluator"],
            }]
            write_json(fx.protocol_path, protocol)
            fx.reseal_after_protocol_edit()

            fake_path = fx.root / "run/sanitizer/fake_ledger.json"
            write_json(fake_path, {"fake": True})
            fake_input = typed(
                fx.root, fake_path, "evaluator_sanitized_runtime_ledger",
                "ncf.data.evaluator-sanitized-runtime-ledger.v1",
            )
            fake_input["producer"] = {"kind": "SEALED_EXECUTABLE_OUTPUT"}
            manifest_path = fx.manifest_paths["evaluator"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["inputs"].append(fake_input)
            manifest["observed_data_classes"].append("evaluator_sanitized_runtime_ledger")
            trace_path = fx.trace_paths["evaluator"]
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["accesses"].append({
                "sequence": len(trace["accesses"]), "operation": "READ",
                "artifact_kind": "INPUT", "access_count": 1,
                **{key: fake_input[key] for key in (
                    "path", "sha256", "bytes", "data_class", "schema_id",
                )},
            })
            write_json(trace_path, trace)
            manifest["tool_trace"] = ref(fx.root, trace_path)
            write_json(manifest_path, manifest)
            aggregate = json.loads(fx.aggregate_path.read_text(encoding="utf-8"))
            next(row for row in aggregate["manifests"] if row["role"] == "evaluator").update(
                ref(fx.root, manifest_path)
            )
            write_json(fx.aggregate_path, aggregate)
            with self.assertRaisesRegex(ClosureError, "unauthorized sealed executable input"):
                fx.compile()

    def test_scout_non_ncbi_or_non_get_request_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            trace_path = fx.trace_paths["scout"]
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["network_requests"][0]["method"] = "POST"
            trace["network_requests"][0]["request_url"] = "http://evil.example/x"
            write_json(trace_path, trace)
            manifest_path = fx.manifest_paths["scout"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tool_trace"] = ref(fx.root, trace_path)
            write_json(manifest_path, manifest)
            aggregate = json.loads(fx.aggregate_path.read_text(encoding="utf-8"))
            next(row for row in aggregate["manifests"] if row["role"] == "scout").update(
                ref(fx.root, manifest_path)
            )
            write_json(fx.aggregate_path, aggregate)
            with self.assertRaisesRegex(ClosureError, "outside exact NCBI HTTPS GET contract"):
                fx.compile()

    def test_unsealed_alternate_protocol_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            alternate = fx.root / "run/alternate_protocol.json"
            alternate.write_bytes(fx.protocol_path.read_bytes())
            aggregate = json.loads(fx.aggregate_path.read_text(encoding="utf-8"))
            aggregate["protocol"] = ref(fx.root, alternate)
            write_json(fx.aggregate_path, aggregate)
            with self.assertRaisesRegex(ClosureError, "exact canonical protocol frozen"):
                fx.compile()

    def test_presealed_root_must_bind_canonical_combined_seal(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            manifest_path = fx.manifest_paths["source_auditor"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            target = next(
                row for row in manifest["inputs"] if row["data_class"] == "combined_preprimary_seal"
            )
            target["producer"]["seal"]["sha256"] = "0" * 64
            write_json(manifest_path, manifest)
            aggregate = json.loads(fx.aggregate_path.read_text(encoding="utf-8"))
            next(row for row in aggregate["manifests"] if row["role"] == "source_auditor").update(
                ref(fx.root, manifest_path)
            )
            write_json(fx.aggregate_path, aggregate)
            with self.assertRaisesRegex(ClosureError, "invalid PRESEALED_ROOT binding"):
                fx.compile()

    def test_duplicate_selected_source_artifact_with_different_role_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            selected = json.loads(fx.selected_manifest_path.read_text(encoding="utf-8"))
            duplicate = dict(selected["source_artifacts"][0])
            duplicate["source_role"] = "SUPPLEMENT"
            selected["source_artifacts"].append(duplicate)
            selected["inventory_sha256"] = hashlib.sha256(canonical(selected["source_artifacts"])).hexdigest()
            write_json(fx.selected_manifest_path, selected)
            inventory = json.loads(fx.inventory_path.read_text(encoding="utf-8"))
            inventory["selected_source_manifest"] = ref(fx.root, fx.selected_manifest_path)
            inventory["source_artifacts"].append({
                key: duplicate[key] for key in ("path", "sha256", "bytes")
            })
            inventory["inventory_sha256"] = hashlib.sha256(canonical(inventory["source_artifacts"])).hexdigest()
            write_json(fx.inventory_path, inventory)
            fx._build_roles()
            with self.assertRaisesRegex(ClosureError, "digest/uniqueness mismatch"):
                fx.compile()

    def test_combined_seal_digest_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            seal = json.loads(fx.combined_seal_path.read_text(encoding="utf-8"))
            seal["payload_sha256"] = "0" * 64
            write_json(fx.combined_seal_path, seal)
            fx._build_roles()
            with self.assertRaisesRegex(ClosureError, "combined preprimary seal is invalid"):
                fx.compile()

    def test_trace_prompt_digest_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            trace_path = fx.trace_paths["extractor"]
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            trace["prompt_or_command_sha256"] = "0" * 64
            write_json(trace_path, trace)
            manifest_path = fx.manifest_paths["extractor"]
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tool_trace"] = ref(fx.root, trace_path)
            write_json(manifest_path, manifest)
            aggregate = json.loads(fx.aggregate_path.read_text(encoding="utf-8"))
            next(row for row in aggregate["manifests"] if row["role"] == "extractor").update(
                ref(fx.root, manifest_path)
            )
            write_json(fx.aggregate_path, aggregate)
            with self.assertRaisesRegex(ClosureError, "prompt/parent digest mismatch"):
                fx.compile()

    def test_stale_lineage_fails_fresh_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = ClosureFixture(Path(temp))
            fx.compile()
            lineage = json.loads(fx.lineage_path.read_text(encoding="utf-8"))
            lineage["timing_valid"] = False
            write_json(fx.lineage_path, lineage)
            with self.assertRaisesRegex(ValidationError, "exact replay mismatch"):
                validate(fx.root, fx.aggregate_path, fx.audit_path, fx.lineage_path)


if __name__ == "__main__":
    unittest.main()
