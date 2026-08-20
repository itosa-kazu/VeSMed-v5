from __future__ import annotations

import copy
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    import jsonschema
except ImportError:  # pragma: no cover
    jsonschema = None

from holdout.tools import primary_runtime_replay_executor as ex
from runtime_v2 import RuntimeV2, canonical_json_bytes


ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "holdout/generic_model/model_pack.json"
REGISTRY_PATH = ROOT / "holdout/generic_model/mapper_sanitized_registry.json"
NEUTRAL_MODEL_PATH = ROOT / "runtime_v2/examples/neutral_factorial_model.json"
TRUE_Q = {
    "explicit_assertion": "TRUE",
    "target_scope": "TRUE",
    "adequate_method": "TRUE",
    "adequate_timing": "TRUE",
    "adequate_reliability": "TRUE",
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_file(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def artifact(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    return {"path": path.relative_to(ROOT).as_posix(), "sha256": sha(raw), "bytes": len(raw)}


def observation(
    event_no: int,
    token_no: int,
    value: str,
    *,
    unit: str | None,
    observed: int,
    available: int,
    kind: str = "NUMBER",
    reliability: str = "HIGH",
    qualification: dict[str, str] | None = None,
    group: str | None = None,
) -> dict[str, object]:
    return {
        "opaque_event_id": f"EV-{event_no:08d}",
        "opaque_source_concept_token": f"SC-{token_no:08d}",
        "event_kind": "OBSERVATION",
        "typed_value": {"kind": kind, "canonical": value},
        "unit": unit,
        "observed_epoch_ordinal": observed,
        "available_epoch_ordinal": available,
        "reliability": reliability,
        "evidence_qualification": copy.deepcopy(qualification or TRUE_Q),
        "alternative_representation_group_id": group,
    }


def action(
    event_no: int,
    token_no: int,
    phase: str,
    *,
    observed: int,
    available: int,
    instance_no: int = 1,
    dose: str | None = None,
) -> dict[str, object]:
    lifecycle: dict[str, object] = {
        "opaque_action_id": f"ACT-{instance_no:08d}",
        "phase": phase,
    }
    if phase in ex.DOSE_PHASES:
        lifecycle.update({"dose": {"kind": "NUMBER", "canonical": dose or "1"}, "dose_unit": None})
    return {
        "opaque_event_id": f"EV-{event_no:08d}",
        "opaque_source_concept_token": f"SC-{token_no:08d}",
        "event_kind": "ACTION",
        "typed_value": {"kind": "CODE", "canonical": phase},
        "unit": None,
        "observed_epoch_ordinal": observed,
        "available_epoch_ordinal": available,
        "reliability": "HIGH",
        "action_lifecycle": lifecycle,
    }


class FullFixture:
    def __init__(self) -> None:
        evidence = ROOT / "holdout/evidence"
        evidence.mkdir(parents=True, exist_ok=True)
        self.path = Path(tempfile.mkdtemp(prefix="primary_executor_test_", dir=evidence))
        self.model = json.loads(NEUTRAL_MODEL_PATH.read_text(encoding="utf-8"))
        for row in self.model["observations"]:
            row["value_type"] = "number" if row["concept_id"].endswith("_LOAD") else "categorical" if row["concept_id"].endswith("_DIRECTION") else "boolean"
            row["unit"] = None
        self.model_path = self.write("neutral_model.json", self.model)
        self.registry = {
            "schema_version": "NCF-MAPPER-SANITIZED-REGISTRY-1.0.0",
            "source_model_pack_sha256": sha(self.model_path.read_bytes()),
            "observations": [
                {"concept_id": row["concept_id"], "value_type": row["value_type"].upper(), "unit": row["unit"]}
                for row in self.model["observations"]
            ],
            "actions": [
                {"action_id": row["action_id"], "entity_type": "ACTION", "unit": None}
                for row in self.model["actions"]
            ],
        }
        self.registry_path = self.write("neutral_registry.json", self.registry)
        runtime = RuntimeV2(self.model)
        self.runtime_doc = {
            "manifest_kind": "runtime_v2_1_case_blind_implementation_manifest",
            "case_blind": True,
            "model_digest": runtime.model_digest,
        }
        self.protocol_doc = {
            "status": "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION",
            "protocol_version": "1.1.0",
        }
        self.scoring_doc = {
            "status": "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION",
            "architecture_version": "NCF-ARCH-1.0.0",
            "prediction_case_consistency": {"support_floor": 1e-12, "direction_deadband": 0.05},
        }
        self.oracle_doc = {
            "schema_version": "NCF-ORACLE-SEAL-HASH-ONLY-1.0.0",
            "oracle_seal_sha256": "a" * 64,
        }
        self.runtime_path = self.write("runtime.json", self.runtime_doc)
        self.protocol_path = self.write("protocol.json", self.protocol_doc)
        self.scoring_path = self.write("scoring.json", self.scoring_doc)
        self.oracle_path = self.write("oracle_hash.json", self.oracle_doc)
        self.map_doc = {
            "schema_version": "NCF-SEALED-CONCEPT-MAP-1.0.0",
            "mappings": [
                {
                    "opaque_source_concept_token": "SC-00000001",
                    "mapped_id": "OBS_A_MARKER",
                    "entity_type": "OBSERVATION",
                    "value_type": "BOOLEAN",
                    "unit": None,
                    "mapping_status": "MAPPED",
                },
                {
                    "opaque_source_concept_token": "SC-00000002",
                    "mapped_id": "OBS_B_MARKER",
                    "entity_type": "OBSERVATION",
                    "value_type": "BOOLEAN",
                    "unit": None,
                    "mapping_status": "MAPPED",
                },
            ],
        }
        self.map_path = self.write("concept_map.json", self.map_doc)
        self.combined_doc = self._combined()
        self.combined_path = self.write("combined.json", self.combined_doc)
        self.ledger_doc = {
            "schema_version": "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-1.0.0",
            "opaque_run_id": f"RUN-{self.combined_doc['payload_sha256']}",
            "identity_removed": True,
            "source_text_removed": True,
            "source_locator_removed": True,
            "reversible_source_ids_removed": True,
            "events": [
                observation(1, 1, "true", unit=None, observed=0, available=0, kind="BOOLEAN"),
                observation(2, 2, "true", unit=None, observed=1, available=2, kind="BOOLEAN"),
            ],
        }
        self.ledger_path = self.write("ledger.json", self.ledger_doc)
        self.manifest_path = self._manifest()

    def write(self, name: str, value: object) -> Path:
        path = self.path / name
        path.write_bytes(canonical_file(value))
        return path

    def _combined(self) -> dict[str, object]:
        execution_paths = {
            "primary_runtime_replay_executor": ROOT / ex.TOOL_REL,
            "primary_runtime_replay_executor_test": ROOT / "holdout/tools/test_primary_runtime_replay_executor.py",
            "primary_runtime_replay_input_schema": ROOT / "holdout/schemas/primary_runtime_replay_input_manifest.schema.json",
            "primary_runtime_output_schema": ROOT / "holdout/schemas/primary_runtime_output.schema.json",
            "primary_runtime_replay_seal_schema": ROOT / "holdout/schemas/primary_runtime_replay_seal.schema.json",
            "mapped_observation_schema": ROOT / "holdout/schemas/mapped_observation_consumption.schema.json",
        }
        payload: dict[str, object] = {
            "format_version": "NCF-PRE-PRIMARY-HOLDOUT-SEAL-1.0.0",
            "status": "SEALED_BEFORE_PRIMARY_CASE_SELECTION",
            "invariants": {
                "all_component_statuses_final": True,
                "component_seals_reverified": True,
                "execution_and_scoring_frozen_before_case_search": True,
                "primary_execution_generators_tests_and_schemas_bound": True,
            },
            "bindings": {
                "runtime": {"manifest": artifact(self.runtime_path)},
                "generic_model": {
                    "model_pack": artifact(self.model_path),
                    "recursive_source_tree": {"files": [artifact(self.registry_path)]},
                },
                "primary_execution": {
                    "protocol_json": artifact(self.protocol_path),
                    "scoring_contract": artifact(self.scoring_path),
                    **{key: artifact(path) for key, path in execution_paths.items()},
                },
            },
        }
        payload["payload_sha256"] = sha(canonical_json_bytes(payload))
        return payload

    def _ref(self, role: str, path: Path) -> dict[str, object]:
        raw = path.read_bytes()
        ref_digest = sha(role.encode("utf-8") + raw)
        return {
            "ref_id": f"REF-{ref_digest[:16]}",
            "role": role,
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": sha(raw),
            "bytes": len(raw),
            "schema_id": ex.EXPECTED_INPUT_SCHEMA_IDS[role],
        }

    def _manifest(self) -> Path:
        paths = {
            "evaluator_sanitized_runtime_ledger": self.ledger_path,
            "sealed_concept_map": self.map_path,
            "model_pack": self.model_path,
            "runtime": self.runtime_path,
            "scoring_contract": self.scoring_path,
            "protocol": self.protocol_path,
            "combined_preprimary_seal": self.combined_path,
            "oracle_seal_hash_only": self.oracle_path,
            "sanitized_id_type_unit_registry": self.registry_path,
        }
        manifest = {
            "schema_version": ex.INPUT_SCHEMA_VERSION,
            "execution_role": "evaluator",
            "inputs": [self._ref(role, paths[role]) for role in sorted(paths)],
        }
        return self.write("input_manifest.json", manifest)

    def verifier(self, _root: Path, _seal_path: Path | None) -> dict[str, object]:
        return {"status": "PASS", "payload_sha256": self.combined_doc["payload_sha256"]}

    def cleanup(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


class PrimaryRuntimeReplayExecutorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixture = FullFixture()
        cls.out1 = cls.fixture.path / "out1"
        cls.out2 = cls.fixture.path / "out2"
        cls.result1 = ex.execute_manifest(ROOT, cls.fixture.manifest_path, cls.out1, preprimary_verifier=cls.fixture.verifier)
        cls.result2 = ex.execute_manifest(ROOT, cls.fixture.manifest_path, cls.out2, preprimary_verifier=cls.fixture.verifier)
        cls.runtime_output = json.loads((cls.out1 / "runtime_output.json").read_text(encoding="utf-8"))
        cls.mapped = json.loads((cls.out1 / "mapped_observation_consumption.json").read_text(encoding="utf-8"))
        cls.seal = json.loads((cls.out1 / "runtime_replay_seal.json").read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls) -> None:
        cls.fixture.cleanup()

    def generic_components(self):
        model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
        registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        obs_registry, action_registry = ex._validate_registry(registry, model, sha(MODEL_PATH.read_bytes()))
        return model, registry, obs_registry, action_registry

    def test_positive_cold_replay_and_schemas(self) -> None:
        self.assertEqual(self.result1["status"], "PASS")
        self.assertEqual(
            (self.out1 / "runtime_output.json").read_bytes(),
            (self.out2 / "runtime_output.json").read_bytes(),
        )
        self.assertEqual(
            (self.out1 / "mapped_observation_consumption.json").read_bytes(),
            (self.out2 / "mapped_observation_consumption.json").read_bytes(),
        )
        self.assertEqual(
            (self.out1 / "runtime_replay_seal.json").read_bytes(),
            (self.out2 / "runtime_replay_seal.json").read_bytes(),
        )
        self.assertEqual(self.seal["fresh_process_replay"]["status"], "PASS")
        if jsonschema is not None:
            for filename, value in [
                ("primary_runtime_output.schema.json", self.runtime_output),
                ("mapped_observation_consumption.schema.json", self.mapped),
                ("primary_runtime_replay_seal.schema.json", self.seal),
            ]:
                schema = json.loads((ROOT / "holdout/schemas" / filename).read_text(encoding="utf-8"))
                jsonschema.Draft202012Validator(schema).validate(value)

    def test_actual_replay_dependency_trace_is_fail_closed(self) -> None:
        trace = self.seal["dependency_trace"]
        self.assertEqual(trace["schema_version"], "NCF-PRIMARY-RUNTIME-DEPENDENCY-TRACE-1.0.0")
        self.assertEqual(trace["trace_scope"], "ACTUAL_PRIMARY_CASE_RUNTIME_REPLAY_PROCESS")
        self.assertEqual(trace["outside_allowlist"], [])
        self.assertTrue(trace["network_guard"]["passed"])
        self.assertEqual(trace["network_guard"]["attempt_count"], 0)
        self.assertEqual(len(trace["io_trace"]["input_bindings"]), 9)
        self.assertEqual(len(trace["io_trace"]["produced_artifacts"]), 3)
        self.assertTrue(
            any(
                row["classification"] == "NCF_FROZEN_SOURCE"
                and row["module"].startswith("runtime_v2")
                for row in trace["module_origins"]
            )
        )
        self.assertTrue(
            all(
                row["classification"] in {"NCF_FROZEN_SOURCE", "PYTHON_STDLIB"}
                for row in trace["module_origins"]
            )
        )

    def test_socket_guard_blocks_and_records_attempt(self) -> None:
        with ex._OfflineSocketGuard() as guard:
            with self.assertRaises(ex.ExecutionError):
                import socket

                socket.create_connection(("127.0.0.1", 9))
        self.assertEqual(len(guard.attempts), 1)
        self.assertEqual(guard.attempts[0]["api"], "socket.create_connection")

    def test_same_state_heads_and_case_blind_priors(self) -> None:
        for cut in self.runtime_output["cuts"]:
            self.assertTrue(cut["head_state_hashes_all_equal"])
            self.assertEqual(set(cut["head_state_hashes"].values()), {cut["canonical_state_hash"]})
        model_priors = {row["process_id"]: row["activation_prior"] for row in self.runtime_output["case_blind_process_priors"]}
        expected = {row["process_id"]: row["activation_prior"] for row in self.fixture.model["processes"]}
        self.assertEqual({key: model_priors[key] for key in expected}, expected)

    def test_future_event_excluded_until_available(self) -> None:
        first, second = self.runtime_output["cuts"]
        self.assertEqual(first["processed_event_ids"], ["EV-00000001"])
        self.assertEqual(first["future_registered_event_ids"], ["EV-00000002"])
        self.assertEqual(second["processed_event_ids"], ["EV-00000001", "EV-00000002"])

    def test_post_cut_score_cannot_mutate_prior_forecast(self) -> None:
        original = copy.deepcopy(self.runtime_output)
        prior_seal = original["cuts"][0]["sealed_before_next_cut_sha256"]
        mutated_score = copy.deepcopy(original)
        mutated_score["prospective_scores"][0]["model"]["bounded_log_score"] -= 1.0
        self.assertEqual(mutated_score["cuts"][0]["sealed_before_next_cut_sha256"], prior_seal)
        with self.assertRaisesRegex(ex.ExecutionError, "payload binding mismatch"):
            ex.verify_prospective_score_bindings(mutated_score)
        mutated_forecast = copy.deepcopy(original)
        mutated_forecast["cuts"][0]["forecast"]["policy_id"] = "TAMPER"
        parent = None
        for cut in mutated_forecast["cuts"]:
            cut["parent_cut_seal_sha256"] = parent
            core = copy.deepcopy(cut)
            core.pop("sealed_before_next_cut_sha256", None)
            cut["sealed_before_next_cut_sha256"] = sha(canonical_json_bytes(core))
            parent = cut["sealed_before_next_cut_sha256"]
        with self.assertRaisesRegex(ex.ExecutionError, "prospective score 0 binding mismatch"):
            ex.verify_prospective_score_bindings(mutated_forecast)
        self.assertEqual(ex.verify_prospective_score_bindings(original)["status"], "PASS")

    def test_factor_trace_has_direction_and_source_semantics(self) -> None:
        traces = [row for cut in self.runtime_output["cuts"] for row in cut["factor_trace"]]
        self.assertTrue(any(row["derived_process_effects"] for row in traces))
        self.assertTrue(any(row["source_event_semantics"] for row in traces))
        self.assertTrue(all(effect["direction"] in {"RAISE", "LOWER", "NEUTRAL"} for row in traces for effect in row["derived_process_effects"]))

    def test_lifecycle_mapping_and_washout_rejected(self) -> None:
        model, _, obs_registry, action_registry = self.generic_components()
        phases = ["ORDERED", "STARTED", "CONTINUED", "DOSE_CHANGED", "HELD", "RESUMED", "STOPPED", "COMPLETED"]
        rows = [action(i, 1, phase, observed=i, available=i, dose="0.5") for i, phase in enumerate(phases, 1)]
        mappings = {"SC-00000001": {"entity_type": "ACTION", "mapped_id": "ACTION_VASOCONSTRICTOR_SUPPORT"}}
        compiled, _ = ex._compile_events(rows, mappings, obs_registry, action_registry, model)
        self.assertEqual([item.payload["event_type"] for item in compiled], [ex.PHASE_TO_RUNTIME[phase] for phase in phases])
        bad = copy.deepcopy(rows[0])
        bad["typed_value"] = {"kind": "CODE", "canonical": "WASHOUT"}
        bad["action_lifecycle"]["phase"] = "WASHOUT"
        ledger = copy.deepcopy(self.fixture.ledger_doc)
        ledger["events"] = [bad]
        bad["opaque_source_concept_token"] = "SC-00000001"
        bad["opaque_event_id"] = "EV-00000001"
        with self.assertRaisesRegex(ex.ExecutionError, "WASHOUT"):
            ex._validate_ledger(ledger, self.fixture.combined_doc)

    def test_unmapped_and_uncertain_observation_preserved_as_residual(self) -> None:
        model = self.fixture.model
        obs_registry, action_registry = ex._validate_registry(self.fixture.registry, model, sha(self.fixture.model_path.read_bytes()))
        row = observation(1, 1, "true", unit=None, observed=0, available=0, kind="BOOLEAN")
        compiled, records = ex._compile_events([row], {}, obs_registry, action_registry, model)
        self.assertEqual(len(compiled), 1)
        self.assertFalse(compiled[0].payload["rankable"])
        self.assertEqual(compiled[0].payload["mapper_disposition_reason"], "UNKNOWN_CONDITION")
        self.assertEqual(records[0]["runtime_disposition_reason"], "UNMAPPED_SOURCE_CONCEPT")
        self.assertEqual(records[0]["rankability_disposition"], "RECORD_ONLY")
        uncertain = observation(1, 1, "true", unit=None, observed=0, available=0, kind="BOOLEAN", qualification={**TRUE_Q, "adequate_method": "UNKNOWN"})
        mapping = {"SC-00000001": self.fixture.map_doc["mappings"][0]}
        compiled, records = ex._compile_events([uncertain], mapping, obs_registry, action_registry, model)
        self.assertFalse(compiled[0].payload["rankable"])
        self.assertEqual(records[0]["rankability_disposition"], "WITHHOLD_TO_MEASUREMENT_UNCERTAINTY")

    def test_support_masking_positive_and_unrelated_negative(self) -> None:
        model, _, obs_registry, action_registry = self.generic_components()

        def run(action_id: str, observation_id: str, value: str, unit: str) -> dict[str, object]:
            rows = [
                action(1, 1, "STARTED", observed=0, available=0, dose="0.5"),
                observation(2, 2, value, unit=unit, observed=1, available=1),
            ]
            mapping = {
                "SC-00000001": {"entity_type": "ACTION", "mapped_id": action_id},
                "SC-00000002": {"entity_type": "OBSERVATION", "mapped_id": observation_id},
            }
            _, records = ex._compile_events(rows, mapping, obs_registry, action_registry, model)
            return records[0]

        map_vaso = run("ACTION_VASOCONSTRICTOR_SUPPORT", "mean_arterial_pressure_mm_hg", "70", "mmHg")
        self.assertEqual(map_vaso["support_masking"]["masking_action_ids"], ["ACTION_VASOCONSTRICTOR_SUPPORT"])
        self.assertEqual(map_vaso["rankability_disposition"], "WITHHOLD_TO_MEASUREMENT_UNCERTAINTY")
        ef_inotrope = run("ACTION_INOTROPIC_SUPPORT", "left_ventricular_ejection_fraction_percent", "30", "percent")
        self.assertEqual(ef_inotrope["support_masking"]["masking_action_ids"], ["ACTION_INOTROPIC_SUPPORT"])
        unrelated = run("ACTION_TOXICOLOGIC_SOURCE_CONTROL", "mean_arterial_pressure_mm_hg", "70", "mmHg")
        self.assertEqual(unrelated["support_masking"]["masking_action_ids"], [])
        self.assertEqual(unrelated["rankability_disposition"], "CONSUME")

    def test_alternative_representation_suppression(self) -> None:
        model = self.fixture.model
        obs_registry, action_registry = ex._validate_registry(self.fixture.registry, model, sha(self.fixture.model_path.read_bytes()))
        rows = [
            observation(1, 1, "true", unit=None, observed=0, available=0, kind="BOOLEAN", group="ARG-00000001", reliability="HIGH"),
            observation(2, 1, "true", unit=None, observed=0, available=0, kind="BOOLEAN", group="ARG-00000001", reliability="LOW"),
        ]
        mapping = {"SC-00000001": self.fixture.map_doc["mappings"][0]}
        _, records = ex._compile_events(rows, mapping, obs_registry, action_registry, model)
        self.assertEqual(records[0]["rankability_disposition"], "CONSUME")
        self.assertEqual(records[1]["runtime_disposition_reason"], "ALTERNATIVE_REPRESENTATION_SUPPRESSED")

    def test_transport_dose_and_content_address_tamper_rejected(self) -> None:
        ledger = copy.deepcopy(self.fixture.ledger_doc)
        ledger["events"][0]["opaque_event_id"] = "EV-case-derived"
        with self.assertRaisesRegex(ex.ExecutionError, "opaque_event_ids"):
            ex._validate_ledger(ledger, self.fixture.combined_doc)

        model, _, obs_registry, action_registry = self.generic_components()
        too_high = action(1, 1, "STARTED", observed=0, available=0, dose="1.1")
        mapping = {"SC-00000001": {"entity_type": "ACTION", "mapped_id": "ACTION_VASOCONSTRICTOR_SUPPORT"}}
        with self.assertRaisesRegex(ex.ExecutionError, "outside frozen normalized range"):
            ex._compile_events([too_high], mapping, obs_registry, action_registry, model)

        manifest = json.loads(self.fixture.manifest_path.read_text(encoding="utf-8"))
        manifest["inputs"][0]["sha256"] = "0" * 64
        tampered = self.fixture.write("tampered_manifest.json", manifest)
        with self.assertRaisesRegex(ex.ExecutionError, "content address mismatch"):
            ex.execute_manifest(ROOT, tampered, self.fixture.path / "bad_out", preprimary_verifier=self.fixture.verifier)


if __name__ == "__main__":
    unittest.main()
