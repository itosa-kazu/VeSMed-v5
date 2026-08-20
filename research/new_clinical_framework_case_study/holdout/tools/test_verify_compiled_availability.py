from __future__ import annotations

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

from compile_availability_epochs import compile_ledger  # noqa: E402
from verify_compiled_availability import (  # noqa: E402
    FROZEN_ASSETS,
    VerificationError,
    verify,
)


SOURCE_ROOT = Path(__file__).resolve().parents[2]


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ref(root: Path, path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


class AvailabilityReplayFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        for rel in FROZEN_ASSETS:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE_ROOT / rel, target)
        self.source = root / "run/raw_availability.json"
        self.compiled = root / "run/compiled_availability.json"
        self.seal = root / "holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json"
        self.ledger = {
            "schema_version": "ncf.primary-availability-ledger.v1",
            "publication_order_used_as_clinical_availability": False,
            "events": [
                {
                    "source_event_id": "event-1",
                    "availability_evidence": {"kind": "INTERVAL", "earliest_epoch": 1, "latest_epoch": 2},
                    "runtime_event": {"event_type": "OBSERVATION", "value": 1},
                }
            ],
        }
        write_json(self.source, self.ledger)
        write_json(self.compiled, compile_ledger(self.ledger))
        unsigned = {
            "format_version": "NCF-PRE-PRIMARY-HOLDOUT-SEAL-1.0.0",
            "status": "SEALED_BEFORE_PRIMARY_CASE_SELECTION",
            "bindings": {"availability_assets": [ref(root, root / rel) for rel in FROZEN_ASSETS]},
        }
        unsigned["payload_sha256"] = hashlib.sha256(canonical(unsigned)).hexdigest()
        write_json(self.seal, unsigned)


class VerifyCompiledAvailabilityTests(unittest.TestCase):
    def test_fresh_replay_positive(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = AvailabilityReplayFixture(Path(temp))
            proof = verify(fx.root, fx.source, fx.compiled, fx.seal)
            self.assertEqual(proof["status"], "PASS")
            self.assertEqual(proof["fresh_replay"]["output_sha256"], ref(fx.root, fx.compiled)["sha256"])

    def test_handcrafted_compiled_output_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = AvailabilityReplayFixture(Path(temp))
            value = json.loads(fx.compiled.read_text(encoding="utf-8"))
            value["released_events"][0]["guaranteed_available_epoch"] = 1
            value["released_events"][0]["runtime_event"]["available_at"] = 1
            unsigned = dict(value)
            unsigned.pop("compiled_sha256")
            value["compiled_sha256"] = hashlib.sha256(canonical(unsigned)).hexdigest()
            write_json(fx.compiled, value)
            with self.assertRaisesRegex(Exception, "replay_output_exact_bytes_mismatch"):
                verify(fx.root, fx.source, fx.compiled, fx.seal)

    def test_changed_source_after_compilation_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = AvailabilityReplayFixture(Path(temp))
            fx.ledger["events"][0]["availability_evidence"]["latest_epoch"] = 3
            write_json(fx.source, fx.ledger)
            with self.assertRaisesRegex(VerificationError, "does not bind source"):
                verify(fx.root, fx.source, fx.compiled, fx.seal)

    def test_frozen_compiler_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            fx = AvailabilityReplayFixture(Path(temp))
            compiler = fx.root / "holdout/tools/compile_availability_epochs.py"
            compiler.write_text(compiler.read_text(encoding="utf-8") + "\n# drift\n", encoding="utf-8")
            with self.assertRaisesRegex(VerificationError, "asset drift"):
                verify(fx.root, fx.source, fx.compiled, fx.seal)


if __name__ == "__main__":
    unittest.main()
