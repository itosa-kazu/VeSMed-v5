"""Case-neutral tests for the production post-replay inventory compiler."""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Mapping
import sys
import shutil

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from compile_all_sealed_artifacts_after_replay import (
    CompileError,
    _canonical_bytes,
    _digest_value,
    _write_once,
    compile_closure,
)
from test_role_manifest_contract_hardening import _RoleContractFixture


def _write(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(value))


def _ref(root: Path, path: Path, data_class: str, schema_id: str) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "data_class": data_class,
        "schema_id": schema_id,
    }


class PostReplayFixture:
    def __init__(self, root: Path) -> None:
        self.base = _RoleContractFixture(root)
        self.root = root
        compiler_source = TOOLS / "compile_all_sealed_artifacts_after_replay.py"
        compiler_target = root / "holdout/tools/compile_all_sealed_artifacts_after_replay.py"
        compiler_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(compiler_source, compiler_target)
        shutil.copy2(
            TOOLS / "validate_primary_holdout_protocol.py",
            root / "holdout/tools/validate_primary_holdout_protocol.py",
        )
        self.executor_dir = root / "run/evaluator/executor"
        self.compiler_input_path = root / "run/evaluator/post_replay_compiler_input.json"
        self.closure_path = root / "run/evaluator/outputs/all_sealed_artifacts_after_replay.json"
        self._create_executor_outputs()
        self._create_input()

    def _create_executor_outputs(self) -> None:
        rows = {
            "runtime_output": (
                "runtime_output.json", "ncf.data.runtime-output.v1",
                {"schema_version": "NCF-PRIMARY-RUNTIME-OUTPUT-1.0.0", "fixture": "neutral"},
            ),
            "runtime_event_ledger_replay_bundle": (
                "runtime_event_ledger_replay_bundle.json", "ncf.holdout.event-ledger-replay-bundle.v1",
                {"schema_version": "ncf.holdout.event-ledger-replay-bundle.v1", "fixture": "neutral"},
            ),
            "mapped_observation_consumption": (
                "mapped_observation_consumption.json", "ncf.mapped-observation-consumption.v1",
                {"schema_version": "NCF-MAPPED-OBSERVATION-CONSUMPTION-1.1.0", "fixture": "neutral"},
            ),
        }
        self.executor: dict[str, dict[str, Any]] = {}
        triple: list[dict[str, Any]] = []
        for data_class, (filename, schema_id, payload) in rows.items():
            path = self.executor_dir / filename
            _write(path, payload)
            ref = _ref(self.root, path, data_class, schema_id)
            self.executor[data_class] = ref
            triple.append({
                "filename": filename, "schema_id": schema_id,
                "sha256": ref["sha256"], "bytes": ref["bytes"],
            })
        seal = {
            "schema_version": "NCF-PRIMARY-RUNTIME-REPLAY-SEAL-1.0.0",
            "execution_role": "evaluator",
            "case_blind": True,
            "invocation_contract": {"fixture": "neutral"},
            "input_manifest": {"filename": "neutral.json", "schema_id": "ncf.primary-runtime-replay-input-manifest.v1", "sha256": "0" * 64, "bytes": 1},
            "input_bindings": [],
            "combined_preprimary_closure": {},
            "runtime_output": {key: self.executor["runtime_output"][key] for key in ()},
            "event_ledger_replay_bundle": {},
            "mapped_observation_consumption": {},
            "fresh_process_replay": {"status": "PASS"},
            "artifact_set_digest": _digest_value(triple),
        }
        for seal_key, artifact_key in (
            ("runtime_output", "runtime_output"),
            ("event_ledger_replay_bundle", "runtime_event_ledger_replay_bundle"),
            ("mapped_observation_consumption", "mapped_observation_consumption"),
        ):
            row = self.executor[artifact_key]
            seal[seal_key] = {
                "filename": Path(row["path"]).name, "schema_id": row["schema_id"],
                "sha256": row["sha256"], "bytes": row["bytes"],
            }
        seal["seal_payload_sha256"] = _digest_value(seal)
        seal_path = self.executor_dir / "runtime_replay_seal.json"
        _write(seal_path, seal)
        self.executor["replay_seal"] = _ref(
            self.root, seal_path, "replay_seal", "ncf.data.replay-seal.v1"
        )

    def _create_input(self) -> None:
        aggregate = self.base.read_json(self.base.aggregate_path)
        upstream = []
        for row in aggregate["manifests"][:6]:
            upstream.append({
                **row,
                "data_class": "role_execution_manifest",
                "schema_id": "ncf.primary-role-execution-manifest.v1.1",
            })
        evaluator = self.base.manifest("evaluator")
        evaluator_inputs = [
            {key: row[key] for key in ("path", "sha256", "bytes", "data_class", "schema_id")}
            for row in evaluator["inputs"]
        ]
        ledger_input = next(row for row in evaluator["inputs"] if row["data_class"] == "evaluator_sanitized_runtime_ledger")
        proof_path = self.root / ledger_input["producer"]["assignment_proof"]["path"]
        verification_path = self.root / ledger_input["producer"]["replay_verification"]["path"]
        protocol = next(row for row in evaluator_inputs if row["data_class"] == "protocol")
        combined = next(row for row in evaluator_inputs if row["data_class"] == "combined_preprimary_seal")
        oracle = next(row for row in evaluator_inputs if row["data_class"] == "oracle_seal_hash_only")
        self.value = {
            "schema_version": "NCF-POST-REPLAY-INVENTORY-COMPILER-INPUT-1.0.0",
            "producer_id": "post-replay-inventory-compiler-v1",
            "evaluator_run_id": evaluator["run_id"],
            "protocol": protocol,
            "combined_preprimary_seal": combined,
            "upstream_role_manifests": upstream,
            "evaluator_inputs": evaluator_inputs,
            "sanitizer": {
                "ledger": next(row for row in evaluator_inputs if row["data_class"] == "evaluator_sanitized_runtime_ledger"),
                "assignment_proof": _ref(self.root, proof_path, "evaluator_sanitized_runtime_ledger_assignment_proof", "ncf.evaluator-sanitized-runtime-ledger-assignment-proof.v1"),
                "replay_verification": _ref(self.root, verification_path, "evaluator_sanitized_runtime_ledger_replay_verification", "ncf.evaluator-sanitized-runtime-ledger-replay-verification.v1"),
            },
            "executor_outputs": copy.deepcopy(self.executor),
            "oracle_seal_hash_only": oracle,
            "topology_attestations": {
                "six_upstream_manifests_closed_before_compile": True,
                "evaluator_receipt_excludes_closure_self_reference": True,
                "scorer_manifest_not_available_to_compiler": True,
                "final_eight_role_set_verified_only_after_scorer": True,
            },
        }
        _write(self.compiler_input_path, self.value)

    def rewrite(self) -> None:
        _write(self.compiler_input_path, self.value)

    def _output_access(self, sequence: int, row: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "sequence": sequence,
            "operation": "WRITE",
            "artifact_kind": "OUTPUT",
            **{key: row[key] for key in ("path", "sha256", "bytes", "data_class", "schema_id")},
            "access_count": 1,
        }

    def _replace_trace_outputs(self, role: str, outputs: list[dict[str, Any]]) -> None:
        manifest = self.base.manifest(role)
        trace_path = self.root / manifest["tool_trace"]["path"]
        trace = self.base.read_json(trace_path)
        inputs = [row for row in trace["accesses"] if row["artifact_kind"] == "INPUT"]
        trace["accesses"] = [*inputs, *[
            self._output_access(len(inputs) + index, row)
            for index, row in enumerate(outputs)
        ]]
        _write(trace_path, trace)
        manifest["tool_trace"] = self.base.ref(trace_path)
        manifest["outputs"] = copy.deepcopy(outputs)
        self.base.write_manifest(role, manifest)

    def finalize_evaluator_and_scorer(self) -> None:
        closure, raw = compile_closure(self.root, self.compiler_input_path)
        self.closure_path.parent.mkdir(parents=True, exist_ok=True)
        self.closure_path.write_bytes(raw)
        closure_ref = _ref(
            self.root, self.closure_path,
            "all_sealed_artifacts_after_replay",
            "ncf.data.all-sealed-artifacts-after-replay.v1",
        )
        evaluator_outputs = [
            copy.deepcopy(self.executor["runtime_output"]),
            copy.deepcopy(self.executor["replay_seal"]),
            copy.deepcopy(self.executor["mapped_observation_consumption"]),
            closure_ref,
        ]
        self._replace_trace_outputs("evaluator", evaluator_outputs)
        evaluator_manifest_path = self.base.manifest_paths["evaluator"]
        evaluator_manifest_ref = self.base.ref(evaluator_manifest_path)

        scorer = self.base.manifest("scorer_auditor")
        replacements = {
            "all_sealed_artifacts_after_replay": closure_ref,
            "mapped_observation_consumption": self.executor["mapped_observation_consumption"],
        }
        for row in scorer["inputs"]:
            if row["data_class"] in replacements:
                fresh = replacements[row["data_class"]]
                for key in ("path", "sha256", "bytes", "data_class", "schema_id"):
                    row[key] = fresh[key]
                row["producer"] = {
                    "kind": "ROLE_OUTPUT",
                    "role": "evaluator",
                    "run_id": "fixture-evaluator",
                    "manifest_path": evaluator_manifest_ref["path"],
                    "manifest_sha256": evaluator_manifest_ref["sha256"],
                    "manifest_bytes": evaluator_manifest_ref["bytes"],
                }
        trace_path = self.root / scorer["tool_trace"]["path"]
        trace = self.base.read_json(trace_path)
        for access in trace["accesses"]:
            if access["artifact_kind"] == "INPUT" and access["data_class"] in replacements:
                fresh = replacements[access["data_class"]]
                for key in ("path", "sha256", "bytes", "data_class", "schema_id"):
                    access[key] = fresh[key]
        _write(trace_path, trace)
        scorer["tool_trace"] = self.base.ref(trace_path)
        self.base.write_manifest("scorer_auditor", scorer)

        aggregate = self.base.read_json(self.base.aggregate_path)
        for role in ("evaluator", "scorer_auditor"):
            row = next(item for item in aggregate["manifests"] if item["role"] == role)
            fresh = self.base.ref(self.base.manifest_paths[role])
            row.update(fresh)
        _write(self.base.aggregate_path, aggregate)


class CompilerTests(unittest.TestCase):
    def test_compiles_exact_inventory_and_broad_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = PostReplayFixture(Path(temp))
            closure, raw = compile_closure(fx.root, fx.compiler_input_path)
            self.assertEqual(len(closure["artifacts"]), 12)
            self.assertEqual(len(closure["producer_inputs"]), 16)
            self.assertFalse(closure["oracle_contents_included"])
            self.assertEqual(
                closure["executor_internal_bundle"]["data_class"],
                "runtime_event_ledger_replay_bundle",
            )
            self.assertEqual(raw, _canonical_bytes(closure))
            self.assertNotIn(fx.closure_path.relative_to(fx.root).as_posix(), {row["path"] for row in closure["producer_inputs"]})

    def test_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = PostReplayFixture(Path(temp))
            first = compile_closure(fx.root, fx.compiler_input_path)[1]
            second = compile_closure(fx.root, fx.compiler_input_path)[1]
            self.assertEqual(first, second)

    def test_rejects_content_address_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = PostReplayFixture(Path(temp))
            path = fx.root / fx.value["executor_outputs"]["runtime_output"]["path"]
            path.write_bytes(path.read_bytes() + b"x")
            with self.assertRaisesRegex(CompileError, "content identity mismatch"):
                compile_closure(fx.root, fx.compiler_input_path)

    def test_rejects_oracle_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = PostReplayFixture(Path(temp))
            fx.value["oracle_seal_hash_only"]["data_class"] = "oracle_contents"
            fx.rewrite()
            with self.assertRaisesRegex(CompileError, "nine-class|oracle seal hash-only"):
                compile_closure(fx.root, fx.compiler_input_path)

    def test_rejects_missing_evaluator_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = PostReplayFixture(Path(temp))
            fx.value["evaluator_inputs"].pop()
            fx.rewrite()
            with self.assertRaisesRegex(CompileError, "exactly nine"):
                compile_closure(fx.root, fx.compiler_input_path)

    def test_rejects_bad_sanitizer_replay(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = PostReplayFixture(Path(temp))
            verification = fx.base.replay_verification()
            verification["status"] = "FAIL"
            path = fx.base.replay_verification_path()
            _write(path, verification)
            fx.value["sanitizer"]["replay_verification"] = _ref(
                fx.root, path,
                "evaluator_sanitized_runtime_ledger_replay_verification",
                "ncf.evaluator-sanitized-runtime-ledger-replay-verification.v1",
            )
            fx.rewrite()
            with self.assertRaisesRegex(CompileError, "did not PASS"):
                compile_closure(fx.root, fx.compiler_input_path)

    def test_write_once_is_idempotent_but_never_replaces(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "closure.json"
            _write_once(path, b"frozen\n")
            _write_once(path, b"frozen\n")
            self.assertEqual(path.read_bytes(), b"frozen\n")
            with self.assertRaisesRegex(CompileError, "refusing to overwrite"):
                _write_once(path, b"changed\n")
            self.assertEqual(path.read_bytes(), b"frozen\n")


if __name__ == "__main__":
    unittest.main()
