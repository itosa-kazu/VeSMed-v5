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

from producer_replay_verifier import (  # noqa: E402
    ProducerReplayError,
    build_invocation_descriptor,
    invocation_sha256,
    verify_automated_producer_replay,
)


REAL_STUDY_ROOT = Path(__file__).resolve().parents[2]


def content_ref(path: Path, root: Path, *, ref_id: str | None = None) -> dict:
    value = {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }
    return ({"ref_id": ref_id, **value} if ref_id is not None else value)


class ProducerReplayVerifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.tool = self.root / "holdout/tools/deterministic_producer.py"
        self.tool.parent.mkdir(parents=True)
        self.tool.write_text(
            """#!/usr/bin/env python3
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--input',required=True)
p.add_argument('--mode',required=True)
p.add_argument('--output',required=True)
a=p.parse_args()
v=json.loads(Path(a.input).read_text(encoding='utf-8'))
out={'schema_version':'ncf.test-output.v1','produced_by':'spoofable-string',
     'mode':a.mode,'value':v['value']}
target=Path(a.output); target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(json.dumps(out,sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')
if a.mode=='EXTRA': (target.parent/'undeclared.txt').write_text('extra',encoding='utf-8')
""",
            encoding="utf-8",
        )
        self.input = self.root / "primary/input.json"
        self.input.parent.mkdir(parents=True)
        self.input.write_text(
            json.dumps({"schema_version": "ncf.test-input.v1", "value": 7}, sort_keys=True),
            encoding="utf-8",
        )
        self.output = self.root / "primary/output.json"
        self.output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                sys.executable,
                str(self.tool),
                "--input", str(self.input),
                "--mode", "NORMAL",
                "--output", str(self.output),
            ],
            check=True,
        )
        self.tool_ref = content_ref(self.tool, self.root)
        self.input_ref = content_ref(self.input, self.root, ref_id="input")
        self.output_ref = content_ref(self.output, self.root, ref_id="output")
        self.policy = {
            "schema_version": "ncf.producer-replay-policy.v1",
            "adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
            "argv_template": [
                "--input", "{input:payload}",
                "--mode", "{check:mode}",
                "--output", "{output}",
            ],
            "required_input_slots": {
                "payload": {"json_schema_versions": ["ncf.test-input.v1"]}
            },
            "check_arg_contract": {
                "mode": {"source": "SEALED_ENUM", "allowed_values": ["NORMAL", "EXTRA"]}
            },
            "output_contract": {
                "mode": "SINGLE_FILE",
                "json_schema_versions": ["ncf.test-output.v1"],
            },
            "timeout_seconds": 30,
            "working_directory": "STUDY_ROOT",
            "network_policy": "APPLICATION_SOCKET_GUARD_OFFLINE",
            "comparison": "EXACT_BYTES_AND_CANONICAL_JSON",
        }
        self.claim = {
            "adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
            "input_ref_ids": {"payload": "input"},
            "check_args": {"mode": "NORMAL"},
            "invocation_sha256": "0" * 64,
        }
        self.refresh_claim()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def refs(self) -> dict[str, dict]:
        return {"input": self.input_ref, "output": self.output_ref}

    def paths(self) -> dict[str, Path]:
        return {"input": self.input, "output": self.output}

    def values(self) -> dict[str, dict]:
        return {
            "input": json.loads(self.input.read_text(encoding="utf-8")),
            "output": json.loads(self.output.read_text(encoding="utf-8")),
        }

    def refresh_claim(self) -> None:
        descriptor = build_invocation_descriptor(
            producer_id="test-v1",
            tool_ref=self.tool_ref,
            replay_policy=self.policy,
            replay_claim=self.claim,
            source_refs=self.refs(),
            output_ref_id="output",
        )
        self.claim["invocation_sha256"] = invocation_sha256(descriptor)

    def verify(self):
        return verify_automated_producer_replay(
            study_root=self.root,
            producer_id="test-v1",
            tool_ref=self.tool_ref,
            tool_path=self.tool,
            replay_policy=self.policy,
            replay_claim=self.claim,
            source_refs=self.refs(),
            source_paths=self.paths(),
            source_values=self.values(),
            output_ref_id="output",
        )

    def test_formal_policy_positive_path_reexecutes_exact_bytes(self) -> None:
        result = self.verify()
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.output_sha256, self.output_ref["sha256"])
        self.assertEqual(result.network_control, "APPLICATION_SOCKET_GUARD_OFFLINE_NOT_OS_SANDBOX")

    def test_verified_original_path_materialization_reexecutes_exact_bytes(self) -> None:
        self.policy["required_input_slots"]["payload"]["materialization"] = (
            "VERIFIED_ORIGINAL_PATH"
        )
        self.refresh_claim()
        result = self.verify()
        self.assertEqual(result.status, "PASS")
        self.assertEqual(result.output_sha256, self.output_ref["sha256"])

    def test_unknown_input_materialization_fails_closed(self) -> None:
        self.policy["required_input_slots"]["payload"]["materialization"] = "TRUST_PATH"
        with self.assertRaisesRegex(ProducerReplayError, "materialization"):
            self.refresh_claim()

    def _named_file_fixture(self):
        tool = self.root / "holdout/tools/named_producer.py"
        tool.write_text(
            """#!/usr/bin/env python3
import argparse,json
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--study-root',required=True)
p.add_argument('--input',required=True)
p.add_argument('--ledger',required=True)
p.add_argument('--proof',required=True)
a=p.parse_args()
v=json.loads(Path(a.input).read_text(encoding='utf-8'))
Path(a.ledger).write_text(json.dumps({'schema_version':'ncf.test-ledger.v1','value':v['value']},sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')
Path(a.proof).write_text(json.dumps({'schema_version':'ncf.test-proof.v1','study_root_name':Path(a.study_root).name,'count':1},sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')
""",
            encoding="utf-8",
        )
        ledger = self.root / "primary/ledger.json"
        proof = self.root / "primary/proof.json"
        subprocess.run(
            [sys.executable, str(tool), "--study-root", str(self.root), "--input", str(self.input), "--ledger", str(ledger), "--proof", str(proof)],
            check=True,
        )
        refs = {
            "input": self.input_ref,
            "ledger": content_ref(ledger, self.root, ref_id="ledger"),
            "proof": content_ref(proof, self.root, ref_id="proof"),
        }
        paths = {"input": self.input, "ledger": ledger, "proof": proof}
        values = {key: json.loads(path.read_text(encoding="utf-8")) for key, path in paths.items()}
        policy = {
            "schema_version": "ncf.producer-replay-policy.v1",
            "adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
            "argv_template": [
                "--study-root", "{study_root}",
                "--input", "{input:payload}",
                "--ledger", "{output:ledger}",
                "--proof", "{output:proof}",
            ],
            "required_input_slots": {"payload": {"json_schema_versions": ["ncf.test-input.v1"]}},
            "check_arg_contract": {},
            "output_contract": {
                "mode": "NAMED_FILES",
                "outputs": {
                    "ledger": {"artifact_relative_path": "ledger.json", "json_schema_versions": ["ncf.test-ledger.v1"]},
                    "proof": {"artifact_relative_path": "proof.json", "json_schema_versions": ["ncf.test-proof.v1"]},
                },
            },
            "timeout_seconds": 30,
            "working_directory": "STUDY_ROOT",
            "network_policy": "APPLICATION_SOCKET_GUARD_OFFLINE",
            "comparison": "EXACT_BYTES_AND_CANONICAL_JSON",
        }
        claim = {
            "adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
            "input_ref_ids": {"payload": "input"},
            "output_ref_ids": {"ledger": "ledger", "proof": "proof"},
            "check_args": {},
            "invocation_sha256": "0" * 64,
        }
        tool_ref = content_ref(tool, self.root)
        claim["invocation_sha256"] = invocation_sha256(build_invocation_descriptor(
            producer_id="named-v1",
            tool_ref=tool_ref,
            replay_policy=policy,
            replay_claim=claim,
            source_refs=refs,
        ))
        return tool, tool_ref, ledger, proof, refs, paths, values, policy, claim

    def test_named_files_positive_path_binds_every_output(self) -> None:
        tool, tool_ref, _, _, refs, paths, values, policy, claim = self._named_file_fixture()
        result = verify_automated_producer_replay(
            study_root=self.root,
            producer_id="named-v1",
            tool_ref=tool_ref,
            tool_path=tool,
            replay_policy=policy,
            replay_claim=claim,
            source_refs=refs,
            source_paths=paths,
            source_values=values,
        )
        self.assertEqual(result.status, "PASS")
        self.assertEqual(set(result.outputs or {}), {"ledger", "proof"})
        self.assertEqual(result.outputs["ledger"]["sha256"], refs["ledger"]["sha256"])

    def test_named_files_handcrafted_secondary_output_is_rejected(self) -> None:
        tool, tool_ref, _, proof, refs, paths, values, policy, claim = self._named_file_fixture()
        forged = json.loads(proof.read_text(encoding="utf-8"))
        forged["count"] = 999
        proof.write_text(json.dumps(forged, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        refs["proof"] = content_ref(proof, self.root, ref_id="proof")
        values["proof"] = forged
        claim["invocation_sha256"] = invocation_sha256(build_invocation_descriptor(
            producer_id="named-v1", tool_ref=tool_ref, replay_policy=policy,
            replay_claim=claim, source_refs=refs,
        ))
        with self.assertRaisesRegex(ProducerReplayError, "exact_bytes_mismatch"):
            verify_automated_producer_replay(
                study_root=self.root, producer_id="named-v1", tool_ref=tool_ref,
                tool_path=tool, replay_policy=policy, replay_claim=claim,
                source_refs=refs, source_paths=paths, source_values=values,
            )

    def test_application_socket_guard_is_actually_loaded(self) -> None:
        self.tool.write_text(
            """#!/usr/bin/env python3
import socket
socket.create_connection(('example.invalid', 443), timeout=0.1)
""",
            encoding="utf-8",
        )
        self.tool_ref = content_ref(self.tool, self.root)
        self.refresh_claim()
        with self.assertRaisesRegex(ProducerReplayError, "replay_subprocess_nonzero"):
            self.verify()

    def test_handmade_schema_and_produced_by_spoof_is_rejected(self) -> None:
        # A plausible handcrafted artifact has valid schema/produced_by and a
        # refreshed content ref/invocation digest.  Only execution provenance
        # distinguishes it from producer output.
        forged = json.loads(self.output.read_text(encoding="utf-8"))
        forged["value"] = 999
        self.output.write_text(json.dumps(forged, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        self.output_ref = content_ref(self.output, self.root, ref_id="output")
        self.refresh_claim()
        with self.assertRaisesRegex(ProducerReplayError, "exact_bytes_mismatch"):
            self.verify()

    def test_parameter_drift_is_rejected_before_execution(self) -> None:
        self.claim["check_args"]["mode"] = "EXTRA"
        with self.assertRaisesRegex(ProducerReplayError, "invocation_sha256_mismatch"):
            self.verify()

    def test_recomputed_parameter_change_with_stale_artifact_is_rejected(self) -> None:
        self.claim["check_args"]["mode"] = "EXTRA"
        self.refresh_claim()
        with self.assertRaisesRegex(ProducerReplayError, "extra_or_missing_output_files"):
            self.verify()

    def test_input_drift_is_rejected_by_content_ref(self) -> None:
        self.input.write_text(
            json.dumps({"schema_version": "ncf.test-input.v1", "value": 8}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ProducerReplayError, "hash_or_bytes_mismatch"):
            self.verify()

    def test_recomputed_input_ref_with_stale_output_is_rejected(self) -> None:
        self.input.write_text(
            json.dumps({"schema_version": "ncf.test-input.v1", "value": 8}),
            encoding="utf-8",
        )
        self.input_ref = content_ref(self.input, self.root, ref_id="input")
        self.refresh_claim()
        with self.assertRaisesRegex(ProducerReplayError, "exact_bytes_mismatch"):
            self.verify()

    def test_tool_drift_is_rejected_by_combined_seal_ref(self) -> None:
        self.tool.write_text(self.tool.read_text(encoding="utf-8") + "# drift\n", encoding="utf-8")
        with self.assertRaisesRegex(ProducerReplayError, "hash_or_bytes_mismatch"):
            self.verify()

    def test_adapter_drift_is_rejected(self) -> None:
        self.claim["adapter_id"] = "FAKE_ADAPTER"
        with self.assertRaisesRegex(ProducerReplayError, "adapter_drift"):
            self.verify()

    def test_input_order_or_duplicate_ref_cannot_change_invocation(self) -> None:
        # Exact slot set is enforced; an extra alias cannot be smuggled into
        # argv or the invocation preimage.
        self.claim["input_ref_ids"]["extra"] = "input"
        with self.assertRaisesRegex(ProducerReplayError, "input_slots_drift"):
            self.verify()

    def test_unsealed_literal_or_interpreter_flag_in_policy_is_rejected(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["argv_template"].insert(0, "{evil:flag}")
        with self.assertRaisesRegex(ProducerReplayError, "placeholder_invalid"):
            build_invocation_descriptor(
                producer_id="test-v1",
                tool_ref=self.tool_ref,
                replay_policy=policy,
                replay_claim=self.claim,
                source_refs=self.refs(),
                output_ref_id="output",
            )


class ExistingSealedProducerAdapterTests(unittest.TestCase):
    """Positive replay paths for both current case-blind producers."""

    @classmethod
    def setUpClass(cls) -> None:
        scoring = json.loads(
            (REAL_STUDY_ROOT / "holdout/PRIMARY_HOLDOUT_SCORING_v1.json").read_text(encoding="utf-8")
        )
        cls.policy = {
            row["producer_id"]: row["replay_contract"]
            for row in scoring["final_scorer_contract"]["evidence_producer_policy"]["sealed_automated_generators"]
        }

    def test_structural_gate_harness_exact_replay(self) -> None:
        tool = REAL_STUDY_ROOT / "holdout/tools/structural_gate_harness.py"
        with tempfile.TemporaryDirectory(dir=REAL_STUDY_ROOT / "holdout") as directory:
            directory = Path(directory)
            output_dir = directory / "structural"
            completed = subprocess.run(
                [
                    sys.executable, str(tool),
                    "--output", str(output_dir),
                    "--generated-at", "2026-07-21T00:00:00Z",
                ],
                cwd=REAL_STUDY_ROOT,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
            output = output_dir / "structural_gate_results.json"
            tool_ref = content_ref(tool, REAL_STUDY_ROOT)
            output_ref = content_ref(output, REAL_STUDY_ROOT, ref_id="output")
            refs = {"output": output_ref}
            claim = {
                "adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
                "input_ref_ids": {},
                "check_args": {"generated_at": "2026-07-21T00:00:00Z"},
                "invocation_sha256": "0" * 64,
            }
            claim["invocation_sha256"] = invocation_sha256(
                build_invocation_descriptor(
                    producer_id="structural-gate-harness-v1",
                    tool_ref=tool_ref,
                    replay_policy=self.policy["structural-gate-harness-v1"],
                    replay_claim=claim,
                    source_refs=refs,
                    output_ref_id="output",
                )
            )
            result = verify_automated_producer_replay(
                study_root=REAL_STUDY_ROOT,
                producer_id="structural-gate-harness-v1",
                tool_ref=tool_ref,
                tool_path=tool,
                replay_policy=self.policy["structural-gate-harness-v1"],
                replay_claim=claim,
                source_refs=refs,
                source_paths={"output": output},
                source_values={"output": json.loads(output.read_text(encoding="utf-8"))},
                output_ref_id="output",
            )
            self.assertEqual(result.status, "PASS")

    def test_event_ledger_fresh_replay_exact_replay(self) -> None:
        if str(REAL_STUDY_ROOT) not in sys.path:
            sys.path.insert(0, str(REAL_STUDY_ROOT))
        from holdout.tools import event_ledger_replay as ledger_replay
        from runtime_v2 import EVENT_SCHEMA_VERSION, PublicEvent, RuntimeV2

        model = REAL_STUDY_ROOT / "runtime_v2/examples/neutral_factorial_model.json"
        runtime = RuntimeV2.from_json(model)
        event = PublicEvent.from_dict(
            {
                "schema_version": EVENT_SCHEMA_VERSION,
                "event_id": "producer-replay-test-event",
                "event_type": "ObservationAvailable",
                "available_at": 0,
                "recorded_at": 0,
                "occurred_time": {"lower": 0, "upper": 0},
                "sample_time": {"lower": 0, "upper": 0},
                "result_at": 0,
                "concept_id": "OBS_A_MARKER",
                "value": True,
                "provenance": {"source_result_id": "producer-replay-test-event"},
            }
        )
        recorder = ledger_replay.ReplayBundleRecorder(runtime)
        recorder.initialize([event], cut=0)
        tool = REAL_STUDY_ROOT / "holdout/tools/event_ledger_replay.py"
        with tempfile.TemporaryDirectory(dir=REAL_STUDY_ROOT / "holdout") as directory:
            directory = Path(directory)
            bundle = directory / "bundle.json"
            output = directory / "report.json"
            recorder.save(bundle)
            completed = subprocess.run(
                [
                    sys.executable, str(tool), "verify",
                    "--bundle", str(bundle),
                    "--model", str(model),
                    "--report", str(output),
                ],
                cwd=REAL_STUDY_ROOT,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))
            refs = {
                "bundle": content_ref(bundle, REAL_STUDY_ROOT, ref_id="bundle"),
                "model": content_ref(model, REAL_STUDY_ROOT, ref_id="model"),
                "output": content_ref(output, REAL_STUDY_ROOT, ref_id="output"),
            }
            tool_ref = content_ref(tool, REAL_STUDY_ROOT)
            claim = {
                "adapter_id": "CONFIGURED_CLI_EXACT_JSON_V1",
                "input_ref_ids": {"bundle": "bundle", "model": "model"},
                "check_args": {},
                "invocation_sha256": "0" * 64,
            }
            claim["invocation_sha256"] = invocation_sha256(
                build_invocation_descriptor(
                    producer_id="event-ledger-fresh-replay-v1",
                    tool_ref=tool_ref,
                    replay_policy=self.policy["event-ledger-fresh-replay-v1"],
                    replay_claim=claim,
                    source_refs=refs,
                    output_ref_id="output",
                )
            )
            result = verify_automated_producer_replay(
                study_root=REAL_STUDY_ROOT,
                producer_id="event-ledger-fresh-replay-v1",
                tool_ref=tool_ref,
                tool_path=tool,
                replay_policy=self.policy["event-ledger-fresh-replay-v1"],
                replay_claim=claim,
                source_refs=refs,
                source_paths={"bundle": bundle, "model": model, "output": output},
                source_values={key: json.loads(path.read_text(encoding="utf-8")) for key, path in {
                    "bundle": bundle, "model": model, "output": output
                }.items()},
                output_ref_id="output",
            )
            self.assertEqual(result.status, "PASS")


if __name__ == "__main__":
    unittest.main()
