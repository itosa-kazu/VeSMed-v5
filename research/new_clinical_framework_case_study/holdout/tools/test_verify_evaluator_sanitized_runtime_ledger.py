from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from producer_replay_verifier import ProducerReplayError, canonical_json_bytes  # noqa: E402
from verify_evaluator_sanitized_runtime_ledger import (  # noqa: E402
    SCHEMA_VERSION,
    build_verification,
)
from test_compile_evaluator_sanitized_runtime_ledger import CompilerFixture, write_json  # noqa: E402


def ref(root: Path, path: Path) -> dict:
    raw = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


class SanitizedLedgerReplayVerificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        tools = self.root / "holdout/tools"
        evidence = self.root / "holdout/evidence"
        tools.mkdir(parents=True)
        evidence.mkdir(parents=True)
        self.verifier = tools / "verify_evaluator_sanitized_runtime_ledger.py"
        shutil.copy2(TOOLS / self.verifier.name, self.verifier)
        self.compiler = tools / "compile_evaluator_sanitized_runtime_ledger.py"
        self.compiler.write_text(
            """#!/usr/bin/env python3
import argparse,hashlib,json
from pathlib import Path
p=argparse.ArgumentParser(); p.add_argument('compile',nargs='?')
p.add_argument('--study-root',required=True); p.add_argument('--manifest',required=True)
p.add_argument('--output-ledger',required=True); p.add_argument('--assignment-proof',required=True)
a=p.parse_args(); root=Path(a.study_root)
m=json.loads(Path(a.manifest).read_text(encoding='utf-8'))
seal=json.loads((root/m['combined_preprimary_seal_path']).read_text(encoding='utf-8'))
ledger={'schema_version':'NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-1.0.0','events':[{'event_id':'EV-00000001'}]}
Path(a.output_ledger).write_text(json.dumps(ledger,sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')
proof={'schema_version':'NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-ASSIGNMENT-PROOF-1.0.0',
       'producer_id':'evaluator-sanitized-runtime-ledger-compiler-v1',
       'combined_preprimary_seal_payload_sha256':seal['payload_sha256']}
Path(a.assignment_proof).write_text(json.dumps(proof,sort_keys=True,separators=(',',':'))+'\\n',encoding='utf-8')
""",
            encoding="utf-8",
        )
        payload = {
            "schema_version": "ncf.test-combined-seal.v1",
            "bindings": {
                "primary_execution": {
                    "evaluator_sanitized_runtime_ledger_compiler": ref(self.root, self.compiler),
                    "evaluator_sanitized_runtime_ledger_replay_verifier": ref(self.root, self.verifier),
                }
            },
        }
        payload["payload_sha256"] = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
        self.seal = evidence / "PRE_PRIMARY_HOLDOUT_SEAL.json"
        self.seal.write_bytes(canonical_json_bytes(payload) + b"\n")
        self.manifest = evidence / "compiler-input.json"
        self.manifest.write_bytes(canonical_json_bytes({
            "schema_version": "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-COMPILER-INPUT-1.0.0",
            "combined_preprimary_seal_path": self.seal.relative_to(self.root).as_posix(),
        }) + b"\n")
        self.ledger = evidence / "sanitized-ledger.json"
        self.proof = evidence / "assignment-proof.json"
        subprocess.run(
            [sys.executable, str(self.compiler), "compile", "--study-root", str(self.root),
             "--manifest", str(self.manifest), "--output-ledger", str(self.ledger),
             "--assignment-proof", str(self.proof)],
            check=True,
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def verify(self):
        return build_verification(
            self.root,
            manifest_path=self.manifest,
            ledger_path=self.ledger,
            assignment_proof_path=self.proof,
            combined_seal_path=self.seal,
        )

    def test_dual_output_fresh_replay_is_exact_and_auditable(self) -> None:
        value = self.verify()
        self.assertEqual(value["schema_version"], SCHEMA_VERSION)
        self.assertEqual(value["status"], "PASS")
        self.assertEqual(set(value["fresh_replay"]["outputs"]), {"ledger", "assignment_proof"})
        self.assertEqual(value["compiler_outputs"]["ledger"]["sha256"], ref(self.root, self.ledger)["sha256"])

    def test_handcrafted_ledger_with_refreshed_content_ref_still_fails_replay(self) -> None:
        value = json.loads(self.ledger.read_text(encoding="utf-8"))
        value["events"].append({"event_id": "FORGED"})
        self.ledger.write_bytes(canonical_json_bytes(value) + b"\n")
        with self.assertRaisesRegex(ProducerReplayError, "exact_bytes_mismatch"):
            self.verify()

    def test_real_compiler_outputs_reexecute_byte_exact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            fixture = CompilerFixture(root)
            verifier = root / "holdout/tools/verify_evaluator_sanitized_runtime_ledger.py"
            shutil.copy2(TOOLS / verifier.name, verifier)

            seal = json.loads(fixture.seal_path.read_text(encoding="utf-8"))
            seal["bindings"]["primary_execution"][
                "evaluator_sanitized_runtime_ledger_compiler"
            ] = seal["bindings"]["primary_execution"]["compiler"]
            seal["bindings"]["primary_execution"][
                "evaluator_sanitized_runtime_ledger_replay_verifier"
            ] = ref(root, verifier)
            seal.pop("payload_sha256", None)
            seal["payload_sha256"] = hashlib.sha256(canonical_json_bytes(seal)).hexdigest()
            write_json(fixture.seal_path, seal)

            fixture.manifest["inputs"]["combined_preprimary_seal"] = {
                **fixture.manifest["inputs"]["combined_preprimary_seal"],
                **ref(root, fixture.seal_path),
            }
            write_json(fixture.manifest_path, fixture.manifest)
            fixture.run()

            verification = build_verification(
                root,
                manifest_path=fixture.manifest_path,
                ledger_path=fixture.output_path,
                assignment_proof_path=fixture.proof_path,
                combined_seal_path=fixture.seal_path,
            )
            self.assertEqual(verification["status"], "PASS")
            self.assertEqual(
                set(verification["fresh_replay"]["outputs"]),
                {"ledger", "assignment_proof"},
            )


if __name__ == "__main__":
    unittest.main()
