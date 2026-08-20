from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from validate_primary_holdout_protocol import (
    ProtocolError,
    validate_mapper_packet,
    validate_preprimary_contracts,
)


ROOT = Path(__file__).resolve().parents[2]


def canonical_sha(value: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


class PrimaryProtocolValidatorTests(unittest.TestCase):
    """Pre-primary integration checks.

    The exhaustive 8-role exact-I/O, trace, root-binding, timing and replay
    package tests live in ``test_role_manifest_contract_hardening.py``.  The
    old partial single-role fixtures were deliberately removed because the
    frozen contract now requires every permitted input/output exactly once;
    keeping incomplete fixtures would test an obsolete, weaker protocol.
    """

    def test_current_frozen_contract_preflight(self) -> None:
        result = validate_preprimary_contracts(ROOT)
        self.assertEqual(result["status"], "PASS")
        for artifact in (
            "final_scorer",
            "availability_compiler",
            "event_ledger_replay",
            "structural_gate_harness",
            "structural_gate_evidence_schema",
            "structural_gate_results_schema",
            "screening_validator",
            "screening_validator_test",
            "screening_evidence_schema",
            "complexity_compiler",
            "complexity_compiler_test",
            "complexity_claims_schema",
            "complexity_packet_schema",
            "sealed_complexity_packet_schema",
            "role_manifest_set_schema",
            "role_tool_access_trace_schema",
            "evaluator_sanitized_runtime_ledger_schema",
            "evaluator_sanitized_runtime_ledger_compiler",
            "evaluator_sanitized_runtime_ledger_compiler_test",
            "evaluator_sanitized_runtime_ledger_compiler_input_schema",
            "evaluator_sanitized_runtime_ledger_assignment_proof_schema",
            "evaluator_sanitized_runtime_ledger_replay_verifier",
            "evaluator_sanitized_runtime_ledger_replay_verifier_test",
            "evaluator_sanitized_runtime_ledger_replay_verification_schema",
            "all_sealed_artifacts_after_replay_schema",
            "sealed_concept_map_schema",
            "producer_replay_verifier",
            "producer_replay_verifier_test",
            "primary_case_gate_evaluator",
            "primary_case_gate_evaluator_test",
            "primary_case_gate_evaluator_runtime_test",
            "primary_gate_evidence_compiler",
            "primary_gate_evidence_compiler_test",
            "primary_runtime_replay_executor",
            "primary_runtime_replay_executor_test",
            "primary_runtime_replay_input_manifest_schema",
            "primary_runtime_output_schema",
            "primary_runtime_replay_seal_schema",
        ):
            self.assertIn(artifact, result["artifacts"])
        protocol = json.loads(
            (ROOT / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(
            protocol["primary_execution_asset_contract"][
                "generated_primary_results_bound_preprimary"
            ]
        )
        self.assertEqual(protocol["protocol_version"], "1.1.0")
        self.assertEqual(
            protocol["selection"]["eligibility"][
                "minimum_concurrent_process_target_candidates"
            ],
            2,
        )
        executor = protocol["primary_execution_asset_contract"][
            "primary_runtime_replay_executor"
        ]
        self.assertEqual(executor["execution_role"], "evaluator")
        self.assertEqual(
            executor["input_data_classes"],
            protocol["roles"]["evaluator"]["allowed_input_data_classes"],
        )
        transport = protocol["opaque_transport_id_contract"]
        self.assertEqual(transport["run_id"]["regex"], "^RUN-[0-9a-f]{64}$")
        self.assertEqual(transport["decimal_width"], 8)
        self.assertEqual(transport["sequence_start"], 1)
        assets = protocol["primary_execution_asset_contract"]
        self.assertEqual(
            assets["evaluator_sanitized_runtime_ledger_compiler"]["producer_id"],
            "evaluator-sanitized-runtime-ledger-compiler-v1",
        )
        self.assertEqual(
            assets["evaluator_sanitized_runtime_ledger_replay_verifier"]["output_schema"],
            "holdout/schemas/evaluator_sanitized_runtime_ledger_replay_verification.schema.json",
        )

    def test_mapper_packet_rejects_case_value(self) -> None:
        packet = {
            "schema_version": "ncf.mapper-packet.v1",
            "concepts": [
                {"source_concept_id": "c1", "definition": "neutral", "value": 42}
            ],
        }
        packet["packet_sha256"] = canonical_sha(packet)
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "packet.json"
            path.write_text(json.dumps(packet), encoding="utf-8")
            with self.assertRaises(ProtocolError):
                validate_mapper_packet(ROOT, path)


if __name__ == "__main__":
    unittest.main()
