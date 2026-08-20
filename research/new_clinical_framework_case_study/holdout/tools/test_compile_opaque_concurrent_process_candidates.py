from __future__ import annotations

import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

try:
    from .compile_opaque_concurrent_process_candidates import (
        ComplexityPacketError,
        compile_claims,
        validate_packet,
    )
except ImportError:  # direct unittest discovery from holdout/tools
    from compile_opaque_concurrent_process_candidates import (
        ComplexityPacketError,
        compile_claims,
        validate_packet,
    )


def sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class OpaqueConcurrentProcessPacketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source_dir = self.root / "holdout/evidence/primary_screening_sources"
        self.claim_dir = self.root / "holdout/evidence/primary_complexity_candidates/claims"
        self.packet_dir = self.root / "holdout/evidence/primary_complexity_candidates/packets"
        self.source_dir.mkdir(parents=True)
        self.claim_dir.mkdir(parents=True)
        self.packet_dir.mkdir(parents=True)
        self.source = self.source_dir / "PMID_123.json"
        self.source_bytes = b"alpha-state\nbeta-state\nalpha-response\nbeta-response\ndistinct-processes\n"
        self.source.write_bytes(self.source_bytes)
        self.source_ref = {
            "path": self.source.relative_to(self.root).as_posix(),
            "sha256": sha(self.source_bytes),
            "bytes": len(self.source_bytes),
        }
        spans = {}
        cursor = 0
        for line in self.source_bytes.splitlines(keepends=True):
            text = line.rstrip(b"\n")
            spans[text.decode()] = {
                "byte_start": cursor,
                "byte_end": cursor + len(text),
                "excerpt_sha256": sha(text),
            }
            cursor += len(line)
        self.spans = spans
        self.claims_path = self.claim_dir / "PMID_123.json"
        self.packet_path = self.packet_dir / "PMID_123.json"
        self.claims = {
            "schema_version": "NCF-OPAQUE-CONCURRENT-PROCESS-CANDIDATE-CLAIMS-1.0.0",
            "canonical_case_id": "PMID:123",
            "terminal_verification_epoch_index": 5,
            "model_blind": True,
            "disease_name_used": False,
            "process_candidates": [
                {
                    "active_epoch_indices": [1, 2, 3],
                    "trajectory_witnesses": [
                        {"epoch_index": 1, "source_artifact_ref": self.source_ref, "locator": spans["alpha-state"]},
                        {"epoch_index": 3, "source_artifact_ref": self.source_ref, "locator": spans["alpha-response"]},
                    ],
                },
                {
                    "active_epoch_indices": [2, 3, 4],
                    "trajectory_witnesses": [
                        {"epoch_index": 2, "source_artifact_ref": self.source_ref, "locator": spans["beta-state"]},
                        {"epoch_index": 4, "source_artifact_ref": self.source_ref, "locator": spans["beta-response"]},
                    ],
                },
            ],
            "pairwise_distinctness_witnesses": [
                {
                    "candidate_indices": [0, 1],
                    "basis": "INDEPENDENT_TRAJECTORY",
                    "source_artifact_ref": self.source_ref,
                    "locator": spans["distinct-processes"],
                }
            ],
        }

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_claims(self, value=None) -> None:
        self.claims_path.write_text(json.dumps(value or self.claims), encoding="utf-8")

    def write_packet(self, value) -> None:
        self.packet_path.write_text(json.dumps(value), encoding="utf-8")

    def test_valid_packet_is_opaque_coactive_and_recompilable(self) -> None:
        self.write_claims()
        packet = compile_claims(study_root=self.root, claims_path=self.claims_path)
        self.assertTrue(packet["qualifies"])
        self.assertEqual(packet["target_count"], 2)
        self.assertEqual(packet["coactive_preterminal_epoch_indices"], [2, 3])
        serialized = json.dumps(packet).lower()
        for forbidden in ("diagnosis", "disease_name\"", "process_name", "description", "expected_diagnosis"):
            self.assertNotIn(forbidden, serialized)
        self.write_packet(packet)
        result = validate_packet(study_root=self.root, packet_path=self.packet_path)
        self.assertEqual(result["status"], "PASS")

    def test_one_candidate_is_valid_negative_packet(self) -> None:
        value = copy.deepcopy(self.claims)
        value["process_candidates"] = value["process_candidates"][:1]
        value["pairwise_distinctness_witnesses"] = []
        self.write_claims(value)
        packet = compile_claims(study_root=self.root, claims_path=self.claims_path)
        self.assertFalse(packet["qualifies"])
        self.assertEqual(packet["target_count"], 1)

    def test_candidates_without_common_preterminal_epoch_fail(self) -> None:
        value = copy.deepcopy(self.claims)
        value["process_candidates"][1]["active_epoch_indices"] = [0, 4]
        value["process_candidates"][1]["trajectory_witnesses"][0]["epoch_index"] = 0
        value["process_candidates"][1]["trajectory_witnesses"][1]["epoch_index"] = 4
        self.write_claims(value)
        packet = compile_claims(study_root=self.root, claims_path=self.claims_path)
        self.assertFalse(packet["qualifies"])
        self.assertEqual(packet["target_count"], 0)

    def test_each_candidate_requires_trackable_two_epoch_trajectory(self) -> None:
        value = copy.deepcopy(self.claims)
        value["process_candidates"][0]["trajectory_witnesses"][1]["epoch_index"] = 1
        self.write_claims(value)
        with self.assertRaisesRegex(ComplexityPacketError, "not trackable"):
            compile_claims(study_root=self.root, claims_path=self.claims_path)

    def test_repeated_source_assertions_do_not_establish_independence(self) -> None:
        value = copy.deepcopy(self.claims)
        value["process_candidates"][1]["trajectory_witnesses"] = copy.deepcopy(
            value["process_candidates"][0]["trajectory_witnesses"]
        )
        value["process_candidates"][1]["active_epoch_indices"] = [1, 2, 3]
        self.write_claims(value)
        with self.assertRaisesRegex(ComplexityPacketError, "no independent source assertion"):
            compile_claims(study_root=self.root, claims_path=self.claims_path)

    def test_every_pair_requires_exactly_one_distinctness_witness(self) -> None:
        value = copy.deepcopy(self.claims)
        value["pairwise_distinctness_witnesses"] = []
        self.write_claims(value)
        with self.assertRaisesRegex(ComplexityPacketError, "every candidate pair"):
            compile_claims(study_root=self.root, claims_path=self.claims_path)

    def test_source_hash_and_locator_are_recomputed(self) -> None:
        value = copy.deepcopy(self.claims)
        value["process_candidates"][0]["trajectory_witnesses"][0]["source_artifact_ref"]["sha256"] = "0" * 64
        self.write_claims(value)
        with self.assertRaisesRegex(ComplexityPacketError, "content reference mismatch"):
            compile_claims(study_root=self.root, claims_path=self.claims_path)

        value = copy.deepcopy(self.claims)
        value["process_candidates"][0]["trajectory_witnesses"][0]["locator"]["excerpt_sha256"] = "0" * 64
        self.write_claims(value)
        with self.assertRaisesRegex(ComplexityPacketError, "excerpt hash mismatch"):
            compile_claims(study_root=self.root, claims_path=self.claims_path)

    def test_diagnosis_or_runtime_fields_cannot_enter_claims(self) -> None:
        value = copy.deepcopy(self.claims)
        value["expected_diagnosis"] = "forbidden"
        self.write_claims(value)
        with self.assertRaisesRegex(ComplexityPacketError, "must contain exactly"):
            compile_claims(study_root=self.root, claims_path=self.claims_path)
        value = copy.deepcopy(self.claims)
        value["model_blind"] = False
        self.write_claims(value)
        with self.assertRaisesRegex(ComplexityPacketError, "model-blind"):
            compile_claims(study_root=self.root, claims_path=self.claims_path)

    def test_tampered_packet_fails_deterministic_recompile(self) -> None:
        self.write_claims()
        packet = compile_claims(study_root=self.root, claims_path=self.claims_path)
        packet["coactive_preterminal_epoch_indices"] = [2]
        self.write_packet(packet)
        with self.assertRaisesRegex(ComplexityPacketError, "deterministic recompilation"):
            validate_packet(study_root=self.root, packet_path=self.packet_path)

    def test_symlink_source_is_rejected_when_supported(self) -> None:
        target = self.source_dir / "real.json"
        target.write_bytes(self.source_bytes)
        link = self.source_dir / "link.json"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlink creation not permitted")
        value = copy.deepcopy(self.claims)
        link_ref = {"path": link.relative_to(self.root).as_posix(), "sha256": sha(self.source_bytes), "bytes": len(self.source_bytes)}
        value["process_candidates"][0]["trajectory_witnesses"][0]["source_artifact_ref"] = link_ref
        self.write_claims(value)
        with self.assertRaisesRegex(ComplexityPacketError, "symlink"):
            compile_claims(study_root=self.root, claims_path=self.claims_path)


if __name__ == "__main__":
    unittest.main()
