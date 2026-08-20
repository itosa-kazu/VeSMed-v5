from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from holdout.tools.compile_primary_case_screening import (
        INPUT_VERSION,
        ScreeningCompilationError,
        compile_screening,
    )
    from holdout.tools import test_validate_primary_case_screening as _screening_fixture
    from holdout.tools.validate_primary_case_screening import (
        COUNT_CRITERIA,
        PROTOCOL_ELIGIBILITY,
        validate_case_screening,
    )
else:
    from .compile_primary_case_screening import (
        INPUT_VERSION,
        ScreeningCompilationError,
        compile_screening,
    )
    from . import test_validate_primary_case_screening as _screening_fixture
    from .validate_primary_case_screening import (
        COUNT_CRITERIA,
        PROTOCOL_ELIGIBILITY,
        validate_case_screening,
    )


class ScreeningCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = _screening_fixture.ScreeningEvidenceTests(
            methodName="test_valid_chain_recomputes_three_eligible_candidates"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root
        self.compiler_input = self.root / "holdout/evidence/PRIMARY_SCREENING_COMPILER_INPUT.json"
        self.payload = self._input_from_existing_chain()
        self._remove_compiler_outputs()
        self._write_input()

    def _input_from_existing_chain(self) -> dict:
        screening = self.fixture.read_json(self.fixture.screening)
        index = self.fixture.read_json(self.fixture.index)
        candidates = []
        for screen_row, index_row in zip(screening["candidates"], index["candidates"], strict=True):
            criteria = []
            for criterion_row in index_row["criterion_evidence"]:
                claim_path = self.root / criterion_row["evidence_ref"]["path"]
                claim = json.loads(claim_path.read_text(encoding="utf-8"))
                item = {
                    "criterion_id": claim["criterion_id"],
                    "claimed_result": claim["claimed_result"],
                    "locators": claim["locators"],
                }
                if claim["criterion_id"] in COUNT_CRITERIA:
                    item["actual_count"] = claim["actual_count"]
                criteria.append(item)
            first_claim = json.loads(
                (self.root / index_row["criterion_evidence"][0]["evidence_ref"]["path"]).read_text(
                    encoding="utf-8"
                )
            )
            candidates.append(
                {
                    "canonical_case_id": screen_row["canonical_case_id"],
                    "source_artifact_ref": first_claim["source_artifact_ref"],
                    "identity_aliases": index_row["identity_aliases"],
                    "opaque_concurrent_process_candidate_packet_ref": index_row[
                        "opaque_concurrent_process_candidate_packet_ref"
                    ],
                    "criteria": criteria,
                    "screening_notes": screen_row["screening_notes"],
                }
            )
        return {
            "schema_version": INPUT_VERSION,
            "protocol_ref": self.fixture.read_json(self.fixture.index)["protocol_ref"],
            "search_snapshot_ref": self.fixture.read_json(self.fixture.index)["search_snapshot_ref"],
            "exclusions_ref": self.fixture.read_json(self.fixture.index)["exclusions_ref"],
            "candidates": candidates,
        }

    def _remove_compiler_outputs(self) -> None:
        for cid in self.fixture.ids:
            for criterion in PROTOCOL_ELIGIBILITY:
                self.fixture.evidence_path(cid, criterion).unlink()
        self.fixture.screening.unlink()
        self.fixture.index.unlink()

    def _write_input(self) -> None:
        self.compiler_input.parent.mkdir(parents=True, exist_ok=True)
        self.compiler_input.write_text(
            json.dumps(self.payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )

    def _compile(self) -> dict:
        return compile_screening(
            study_root=self.root,
            compiler_input_path=self.compiler_input,
            screening_output_path=self.fixture.screening,
            evidence_index_output_path=self.fixture.index,
        )

    def test_compiles_agent_judgments_into_validator_passing_chain(self) -> None:
        result = self._compile()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["criterion_claim_count"], 4 * 12)
        self.assertEqual(result["eligible_candidate_ids"], self.fixture.ids[:3])
        validated = validate_case_screening(
            study_root=self.root,
            protocol_path=self.fixture.protocol,
            search_snapshot_path=self.fixture.search,
            screening_path=self.fixture.screening,
            exclusions_path=self.fixture.exclusions,
            evidence_index_path=self.fixture.index,
        )
        self.assertEqual(validated["status"], "PASS")

    def test_noncount_medical_false_is_preserved_not_inferred_from_prose(self) -> None:
        row = self.payload["candidates"][-1]
        claim = next(item for item in row["criteria"] if item["criterion_id"] == "single_adult_primary_case")
        claim["claimed_result"] = False
        self._write_input()
        self._compile()
        screening = json.loads(self.fixture.screening.read_text(encoding="utf-8"))
        emitted = screening["candidates"][-1]
        self.assertFalse(emitted["criteria"]["single_adult_primary_case"])
        self.assertFalse(emitted["eligible"])

    def test_bad_locator_fails_before_any_output_is_written(self) -> None:
        locator = self.payload["candidates"][0]["criteria"][0]["locators"][0]
        locator["excerpt_sha256"] = "0" * 64
        self._write_input()
        with self.assertRaisesRegex(RuntimeError, "excerpt sha256 mismatch"):
            self._compile()
        self.assertFalse(self.fixture.screening.exists())
        self.assertFalse(self.fixture.index.exists())
        for cid in self.fixture.ids:
            for criterion in PROTOCOL_ELIGIBILITY:
                self.assertFalse(self.fixture.evidence_path(cid, criterion).exists())

    def test_mechanical_count_contradiction_fails_before_write(self) -> None:
        claim = next(
            item
            for item in self.payload["candidates"][0]["criteria"]
            if item["criterion_id"]
            == "minimum_guaranteed_availability_epochs_before_terminal_verification"
        )
        claim["actual_count"] = 4
        self._write_input()
        with self.assertRaisesRegex(ScreeningCompilationError, "mechanical recomputation"):
            self._compile()
        self.assertFalse(self.fixture.screening.exists())
        self.assertFalse(self.fixture.index.exists())

    def test_write_once_refuses_second_compilation(self) -> None:
        self._compile()
        before_screen = self.fixture.screening.read_bytes()
        before_index = self.fixture.index.read_bytes()
        with self.assertRaisesRegex(ScreeningCompilationError, "write-once output already exists"):
            self._compile()
        self.assertEqual(self.fixture.screening.read_bytes(), before_screen)
        self.assertEqual(self.fixture.index.read_bytes(), before_index)

    def test_same_input_fixture_is_byte_deterministic(self) -> None:
        self._compile()
        first_screen = self.fixture.screening.read_bytes()
        first_index = self.fixture.index.read_bytes()
        first_claims = {
            (cid, criterion): self.fixture.evidence_path(cid, criterion).read_bytes()
            for cid in self.fixture.ids
            for criterion in PROTOCOL_ELIGIBILITY
        }

        other = _screening_fixture.ScreeningEvidenceTests(
            methodName="test_valid_chain_recomputes_three_eligible_candidates"
        )
        other.setUp()
        self.addCleanup(other.tearDown)
        old_fixture, old_root = self.fixture, self.root
        try:
            self.fixture, self.root = other, other.root
            self.compiler_input = self.root / "holdout/evidence/PRIMARY_SCREENING_COMPILER_INPUT.json"
            self.payload = self._input_from_existing_chain()
            self._remove_compiler_outputs()
            self._write_input()
            self._compile()
            self.assertEqual(other.screening.read_bytes(), first_screen)
            self.assertEqual(other.index.read_bytes(), first_index)
            for key, raw in first_claims.items():
                self.assertEqual(other.evidence_path(*key).read_bytes(), raw)
        finally:
            self.fixture, self.root = old_fixture, old_root


if __name__ == "__main__":
    unittest.main()
