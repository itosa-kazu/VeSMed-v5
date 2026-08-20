from __future__ import annotations

import copy
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from compile_evaluator_sanitized_runtime_ledger import (
    ALGORITHM,
    CompilerError,
    FROZEN_ASSETS,
    INPUT_SLOTS,
    INPUT_VERSION,
    compile_ledger,
    run_compile,
)


SOURCE_ROOT = TOOLS.parent.parent


def canonical_sha(value) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ref(root: Path, path: Path, data_class: str, schema_id: str) -> dict:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "data_class": data_class,
        "schema_id": schema_id,
    }


def observation(event_id: str, token: str, observed: int, *, group: str | None = None) -> dict:
    return {
        "source_event_id": event_id,
        "runtime_event": {
            "source_concept_token": token,
            "event_kind": "OBSERVATION",
            "typed_value": {"kind": "NUMBER", "canonical": "65"},
            "unit": "percent",
            "observed_epoch_ordinal": observed,
            "reliability": "HIGH",
            "evidence_qualification": {
                "explicit_assertion": "TRUE",
                "target_scope": "TRUE",
                "adequate_method": "TRUE",
                "adequate_timing": "TRUE",
                "adequate_reliability": "TRUE",
            },
            "source_alternative_representation_group_id": group,
        },
    }


def action(event_id: str, token: str, observed: int, source_action: str, phase: str) -> dict:
    lifecycle = {"source_action_instance_id": source_action, "phase": phase}
    if phase in {"STARTED", "CONTINUED", "DOSE_CHANGED", "RESUMED"}:
        lifecycle.update({"dose": {"kind": "NUMBER", "canonical": "1"}, "dose_unit": None})
    return {
        "source_event_id": event_id,
        "runtime_event": {
            "source_concept_token": token,
            "event_kind": "ACTION",
            "typed_value": {"kind": "CODE", "canonical": phase},
            "unit": None,
            "observed_epoch_ordinal": observed,
            "reliability": "HIGH",
            "action_lifecycle": lifecycle,
        },
    }


class CompilerFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        for rel in FROZEN_ASSETS.values():
            source = SOURCE_ROOT / rel
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

        self.event_path = root / "holdout/primary_execution/sealed_event_ledger.json"
        self.avail_path = root / "holdout/primary_execution/sealed_availability_ledger.json"
        self.map_path = root / "holdout/primary_execution/sealed_concept_map.json"
        self.registry_path = root / "holdout/primary_execution/mapper_sanitized_registry.json"
        self.seal_path = root / "holdout/PRE_PRIMARY_COMBINED_SEAL.json"
        self.manifest_path = root / "holdout/primary_execution/sanitized_ledger_compiler_input.json"
        self.output_path = root / "holdout/primary_execution/evaluator_sanitized_runtime_ledger.json"
        self.proof_path = root / "holdout/primary_execution/evaluator_sanitized_runtime_ledger_assignment_proof.json"

        self.events = [
            observation("source-event-alpha", "source-concept-alpha", 0, group="source-group-alpha"),
            action("source-event-beta", "source-concept-beta", 1, "source-action-alpha", "STARTED"),
            observation("source-event-gamma", "source-concept-alpha", 2, group="source-group-alpha"),
            action("source-event-delta", "source-concept-beta", 3, "source-action-alpha", "STOPPED"),
        ]
        self.availability = {
            "schema_version": "ncf.data.sealed-availability-ledger.v1",
            "events": [
                {"source_event_id": row["source_event_id"], "availability_evidence": {"kind": "EXACT", "exact_epoch": index}}
                for index, row in enumerate(self.events)
            ],
        }
        self.registry = {
            "schema_version": "NCF-MAPPER-SANITIZED-REGISTRY-1.0.0",
            "observations": [{"concept_id": "left_ventricular_ejection_fraction_percent", "unit": "percent", "value_type": "NUMBER"}],
            "actions": [{"action_id": "ACTION_FLUID_CHALLENGE", "entity_type": "ACTION", "unit": None}],
        }
        self.concept_map = {
            "schema_version": "NCF-SEALED-CONCEPT-MAP-1.0.0",
            "mappings": [
                {
                    "opaque_source_concept_token": "SC-00000001",
                    "mapped_id": "left_ventricular_ejection_fraction_percent",
                    "entity_type": "OBSERVATION",
                    "value_type": "NUMBER",
                    "unit": "percent",
                    "mapping_status": "MAPPED",
                },
                {
                    "opaque_source_concept_token": "SC-00000002",
                    "mapped_id": "ACTION_FLUID_CHALLENGE",
                    "entity_type": "ACTION",
                    "value_type": "ACTION",
                    "unit": None,
                    "mapping_status": "MAPPED",
                },
            ],
        }
        self.flush_inputs()

    def flush_inputs(self) -> None:
        write_json(self.event_path, {"schema_version": "ncf.data.sealed-event-ledger.v1", "events": self.events})
        write_json(self.avail_path, self.availability)
        write_json(self.map_path, self.concept_map)
        write_json(self.registry_path, self.registry)
        bindings = {
            role: {
                "path": rel,
                "sha256": hashlib.sha256((self.root / rel).read_bytes()).hexdigest(),
                "bytes": (self.root / rel).stat().st_size,
            }
            for role, rel in FROZEN_ASSETS.items()
        }
        seal = {
            "format_version": "NCF-PRE-PRIMARY-COMBINED-SEAL-1.0.0",
            "status": "SEALED_BEFORE_PRIMARY_CASE_SELECTION",
            "bindings": {"primary_execution": bindings},
        }
        seal["payload_sha256"] = canonical_sha(seal)
        write_json(self.seal_path, seal)
        refs = {
            "sealed_event_ledger": ref(self.root, self.event_path, "sealed_event_ledger", "ncf.data.sealed-event-ledger.v1"),
            "sealed_availability_ledger": ref(self.root, self.avail_path, "sealed_availability_ledger", "ncf.data.sealed-availability-ledger.v1"),
            "sealed_concept_map": ref(self.root, self.map_path, "sealed_concept_map", "ncf.data.sealed-concept-map.v1"),
            "sanitized_id_type_unit_registry": ref(self.root, self.registry_path, "sanitized_id_type_unit_registry", "ncf.data.sanitized-id-type-unit-registry.v1"),
            "combined_preprimary_seal": ref(self.root, self.seal_path, "combined_preprimary_seal", "ncf.data.combined-preprimary-seal.v1"),
        }
        self.manifest = {"schema_version": INPUT_VERSION, "inputs": refs}
        write_json(self.manifest_path, self.manifest)

    def run(self):
        return run_compile(self.root, self.manifest_path, self.output_path, self.proof_path)


class SanitizedLedgerCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fx = CompilerFixture(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_compiles_deterministic_transport_ids_and_proof(self) -> None:
        proof = self.fx.run()
        ledger = json.loads(self.fx.output_path.read_text(encoding="utf-8"))
        self.assertRegex(ledger["opaque_run_id"], r"^RUN-[0-9a-f]{64}$")
        self.assertEqual([r["opaque_event_id"] for r in ledger["events"]], [f"EV-{i:08d}" for i in range(1, 5)])
        self.assertEqual([r["opaque_source_concept_token"] for r in ledger["events"]], ["SC-00000001", "SC-00000002", "SC-00000001", "SC-00000002"])
        self.assertEqual(ledger["events"][1]["action_lifecycle"]["opaque_action_id"], "ACT-00000001")
        self.assertEqual(ledger["events"][3]["action_lifecycle"]["opaque_action_id"], "ACT-00000001")
        self.assertEqual(ledger["events"][0]["alternative_representation_group_id"], "ARG-00000001")
        self.assertEqual(proof["assignment_algorithm"], ALGORITHM)
        self.assertEqual(proof["assignment_counts"], {"events": 4, "source_concepts": 2, "actions": 1, "alternative_groups": 1})
        self.assertEqual([r["slot"] for r in proof["inputs"]], list(INPUT_SLOTS))
        self.assertEqual(
            proof["output_ledger"]["path"],
            "evaluator_sanitized_runtime_ledger.json",
        )

    def test_outputs_contain_no_source_identifiers(self) -> None:
        self.fx.run()
        combined = self.fx.output_path.read_text(encoding="utf-8") + self.fx.proof_path.read_text(encoding="utf-8")
        for forbidden in ("source-event", "source-concept", "source-action", "source-group"):
            self.assertNotIn(forbidden, combined)

    def test_assignment_digest_has_exact_sanitized_preimage(self) -> None:
        proof = self.fx.run()
        ledger = json.loads(self.fx.output_path.read_text(encoding="utf-8"))
        preimage = {
            "opaque_run_id": ledger["opaque_run_id"],
            "events": [
                {
                    "opaque_event_id": row["opaque_event_id"],
                    "opaque_source_concept_token": row["opaque_source_concept_token"],
                    "opaque_action_id": row.get("action_lifecycle", {}).get("opaque_action_id"),
                    "alternative_representation_group_id": row.get("alternative_representation_group_id"),
                }
                for row in ledger["events"]
            ],
        }
        self.assertEqual(proof["assignment_digest"], canonical_sha(preimage))

    def test_concept_map_noncanonical_order_fails_closed(self) -> None:
        self.fx.concept_map["mappings"].reverse()
        self.fx.flush_inputs()
        with self.assertRaisesRegex(CompilerError, "canonical sequential"):
            self.fx.run()

    def test_concept_map_extra_token_fails_closed(self) -> None:
        extra = copy.deepcopy(self.fx.concept_map["mappings"][0])
        extra["opaque_source_concept_token"] = "SC-00000003"
        self.fx.concept_map["mappings"].append(extra)
        self.fx.flush_inputs()
        with self.assertRaisesRegex(CompilerError, "first-occurrence order"):
            self.fx.run()

    def test_event_reorder_requires_concept_map_first_occurrence_reorder(self) -> None:
        self.fx.events[0], self.fx.events[1] = self.fx.events[1], self.fx.events[0]
        self.fx.flush_inputs()
        with self.assertRaisesRegex(CompilerError, "kind disagrees"):
            self.fx.run()

    def test_unknown_availability_fails_closed(self) -> None:
        self.fx.availability["events"][0]["availability_evidence"] = {"kind": "UNKNOWN"}
        self.fx.flush_inputs()
        with self.assertRaisesRegex(CompilerError, "unknown"):
            self.fx.run()

    def test_event_availability_inventory_mismatch_fails_closed(self) -> None:
        self.fx.availability["events"].pop()
        self.fx.flush_inputs()
        with self.assertRaisesRegex(CompilerError, "different event inventories"):
            self.fx.run()

    def test_combined_seal_tamper_fails_closed(self) -> None:
        self.fx.flush_inputs()
        seal = json.loads(self.fx.seal_path.read_text(encoding="utf-8"))
        seal["status"] = "TAMPERED"
        write_json(self.fx.seal_path, seal)
        self.fx.manifest["inputs"]["combined_preprimary_seal"] = ref(
            self.root, self.fx.seal_path, "combined_preprimary_seal", "ncf.data.combined-preprimary-seal.v1"
        )
        write_json(self.fx.manifest_path, self.fx.manifest)
        with self.assertRaisesRegex(CompilerError, "payload digest mismatch"):
            self.fx.run()

    def test_frozen_asset_mutation_fails_closed(self) -> None:
        self.fx.flush_inputs()
        compiler_copy = self.root / FROZEN_ASSETS["compiler"]
        compiler_copy.write_text(compiler_copy.read_text(encoding="utf-8") + "\n# tamper\n", encoding="utf-8")
        with self.assertRaisesRegex(CompilerError, "differs from combined"):
            self.fx.run()

    def test_input_content_ref_tamper_fails_closed(self) -> None:
        self.fx.flush_inputs()
        manifest = json.loads(self.fx.manifest_path.read_text(encoding="utf-8"))
        manifest["inputs"]["sealed_event_ledger"]["sha256"] = "0" * 64
        write_json(self.fx.manifest_path, manifest)
        with self.assertRaisesRegex(CompilerError, "content reference mismatch"):
            self.fx.run()

    def test_refuses_to_overwrite_outputs(self) -> None:
        self.fx.run()
        with self.assertRaisesRegex(CompilerError, "refusing to overwrite"):
            self.fx.run()

    def test_output_logical_basenames_are_frozen(self) -> None:
        with self.assertRaisesRegex(CompilerError, "frozen logical basenames"):
            run_compile(
                self.root,
                self.fx.manifest_path,
                self.fx.output_path.with_name("other-ledger.json"),
                self.fx.proof_path,
            )


if __name__ == "__main__":
    unittest.main()
