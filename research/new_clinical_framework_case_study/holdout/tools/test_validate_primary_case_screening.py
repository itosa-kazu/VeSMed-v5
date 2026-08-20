import hashlib
import json
import tempfile
import unittest
from pathlib import Path

try:
    from .compile_opaque_concurrent_process_candidates import compile_claims
    from .validate_primary_case_screening import (
        COUNT_CRITERIA,
        PROTOCOL_ELIGIBILITY,
        ScreeningValidationError,
        _expected_claim_name,
        _expected_complexity_packet_name,
        _expected_source_name,
        validate_case_screening,
    )
except ImportError:  # direct discovery from holdout/tools
    from compile_opaque_concurrent_process_candidates import compile_claims
    from validate_primary_case_screening import (
        COUNT_CRITERIA,
        PROTOCOL_ELIGIBILITY,
        ScreeningValidationError,
        _expected_claim_name,
        _expected_complexity_packet_name,
        _expected_source_name,
        validate_case_screening,
    )


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref(root: Path, path: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha(path),
        "bytes": path.stat().st_size,
    }


class ScreeningEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.protocol = self.root / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json"
        self.search = self.root / "holdout/evidence/PRIMARY_CASE_SEARCH_SNAPSHOT.json"
        self.screening = self.root / "holdout/evidence/PRIMARY_CASE_SCREENING.json"
        self.exclusions = self.root / "holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json"
        self.index = self.root / "holdout/evidence/PRIMARY_SCREENING_EVIDENCE_INDEX.json"
        for path in (self.protocol, self.search, self.screening, self.exclusions, self.index):
            path.parent.mkdir(parents=True, exist_ok=True)

        self.ids = ["PMID:101", "PMID:102", "PMID:103", "PMID:104"]
        self.excluded_id = self.ids[-1]
        self.write_json(
            self.protocol,
            {
                "protocol_version": "1.1.0",
                "selection": {
                    "minimum_eligible_candidates": 3,
                    "eligibility": PROTOCOL_ELIGIBILITY,
                },
            },
        )
        self.write_json(
            self.search,
            {
                "schema_version": "NCF-PRIMARY-SEARCH-SNAPSHOT-1.0.0",
                "canonical_case_ids": self.ids,
            },
        )
        self.write_json(
            self.exclusions,
            {
                "schema_version": "NCF-PRIMARY-HOLDOUT-EXCLUSIONS-1.0.0",
                "exclusion_set_id": "SYNTHETIC-EXCLUSIONS",
                # Deliberately a PMCID while the search universe is PMID.  A
                # correct validator must exclude by source-backed alias closure.
                "excluded_case_ids": ["PMCID:PMC104"],
            },
        )
        self.build_valid_chain()

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def write_json(path: Path, value: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")

    def read_json(self, path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def evidence_path(self, cid: str, criterion: str) -> Path:
        return (
            self.root
            / "holdout/evidence/primary_screening_evidence/claims"
            / _expected_claim_name(cid, criterion)
        )

    def source_path(self, cid: str) -> Path:
        return self.root / "holdout/evidence/primary_screening_sources" / _expected_source_name(cid)

    def identity_path(self, cid: str) -> Path:
        return (
            self.root
            / "holdout/evidence/primary_screening_identity"
            / f"{hashlib.sha256(cid.encode('utf-8')).hexdigest()}.identity.response.json"
        )

    def complexity_claims_path(self, cid: str) -> Path:
        return (
            self.root
            / "holdout/evidence/primary_complexity_candidates/claims"
            / f"{hashlib.sha256(cid.encode('utf-8')).hexdigest()}.claims.json"
        )

    def complexity_packet_path(self, cid: str) -> Path:
        return (
            self.root
            / "holdout/evidence/primary_complexity_candidates/packets"
            / _expected_complexity_packet_name(cid)
        )

    def build_valid_chain(self) -> None:
        source_root = self.root / "holdout/evidence/primary_screening_sources"
        claim_root = self.root / "holdout/evidence/primary_screening_evidence/claims"
        identity_root = self.root / "holdout/evidence/primary_screening_identity"
        source_root.mkdir(parents=True, exist_ok=True)
        claim_root.mkdir(parents=True, exist_ok=True)
        identity_root.mkdir(parents=True, exist_ok=True)
        screen_rows = []
        index_rows = []
        for cid in self.ids:
            pmid = cid.split(":", 1)[1]
            pmcid = f"PMC{pmid}"
            doi = f"10.1000/synthetic.{pmid}"
            identity_path = self.identity_path(cid)
            self.write_json(
                identity_path,
                {
                    "status": "ok",
                    "records": [
                        {
                            "requested-id": pmid,
                            "pmid": pmid,
                            "pmcid": pmcid,
                            "doi": doi,
                        }
                    ],
                },
            )
            identity_bytes = identity_path.read_bytes()
            identity_aliases = {
                "provider": "NCBI_ID_CONVERTER_JSON",
                "aliases": [cid, f"PMCID:{pmcid}", f"DOI:{doi}"],
                "source_document_id": f"PMCID:{pmcid}",
                "raw_identity_response_ref": ref(self.root, identity_path),
                "locators": [
                    {
                        "locator_kind": "WHOLE_DOCUMENT_REVIEW",
                        "byte_start": 0,
                        "byte_end": len(identity_bytes),
                        "excerpt_sha256": hashlib.sha256(identity_bytes).hexdigest(),
                        "source_anchor": "complete synthetic NCBI identity response",
                        "assertions": [
                            {
                                "assertion_id": "identity_aliases_match_response",
                                "statement": "PMID, PMCID, and DOI aliases are read from this response",
                                "passed": True,
                            }
                        ],
                    }
                ],
            }
            source = self.source_path(cid)
            source.write_text(
                f"Synthetic screening source for {cid}. Adult ICU chronology, organ domains, "
                "action response, explicit negative, delayed result, and diagnostic basis.",
                encoding="utf-8",
            )
            source_bytes = source.read_bytes()
            source_ref = ref(self.root, source)

            def locator(needle: bytes) -> dict:
                start = source_bytes.index(needle)
                return {
                    "byte_start": start,
                    "byte_end": start + len(needle),
                    "excerpt_sha256": hashlib.sha256(needle).hexdigest(),
                }

            complexity_claims = {
                "schema_version": "NCF-OPAQUE-CONCURRENT-PROCESS-CANDIDATE-CLAIMS-1.0.0",
                "canonical_case_id": cid,
                "terminal_verification_epoch_index": 4,
                "model_blind": True,
                "disease_name_used": False,
                "process_candidates": [
                    {
                        "active_epoch_indices": [1, 2],
                        "trajectory_witnesses": [
                            {"epoch_index": 1, "source_artifact_ref": source_ref, "locator": locator(b"Adult ICU chronology")},
                            {"epoch_index": 2, "source_artifact_ref": source_ref, "locator": locator(b"organ domains")},
                        ],
                    },
                    {
                        "active_epoch_indices": [1, 2],
                        "trajectory_witnesses": [
                            {"epoch_index": 1, "source_artifact_ref": source_ref, "locator": locator(b"action response")},
                            {"epoch_index": 2, "source_artifact_ref": source_ref, "locator": locator(b"delayed result")},
                        ],
                    },
                ],
                "pairwise_distinctness_witnesses": [
                    {
                        "candidate_indices": [0, 1],
                        "basis": "INDEPENDENT_TRAJECTORY",
                        "source_artifact_ref": source_ref,
                        "locator": locator(b"explicit negative"),
                    }
                ],
            }
            claims_path = self.complexity_claims_path(cid)
            self.write_json(claims_path, complexity_claims)
            packet_path = self.complexity_packet_path(cid)
            self.write_json(
                packet_path,
                compile_claims(study_root=self.root, claims_path=claims_path),
            )
            complexity_packet_ref = ref(self.root, packet_path)
            criteria = {key: True for key in PROTOCOL_ELIGIBILITY}
            criteria["must_not_be_in_presealed_exclusion_set"] = cid != self.excluded_id
            screen_rows.append(
                {
                    "canonical_case_id": cid,
                    "eligible": all(criteria.values()),
                    "criteria": criteria,
                    "source_locator": source.relative_to(self.root).as_posix(),
                    "opaque_concurrent_process_candidate_packet_ref": complexity_packet_ref,
                    "screening_notes": "synthetic fixture",
                }
            )
            criterion_rows = []
            for criterion, claimed in criteria.items():
                claim = {
                    "schema_version": "NCF-PRIMARY-SCREENING-CRITERION-EVIDENCE-1.0.0",
                    "canonical_case_id": cid,
                    "criterion_id": criterion,
                    "claimed_result": claimed,
                    "source_artifact_ref": ref(self.root, source),
                    "locators": [
                        {
                            "locator_kind": "WHOLE_DOCUMENT_REVIEW",
                            "byte_start": 0,
                            "byte_end": len(source_bytes),
                            "excerpt_sha256": hashlib.sha256(source_bytes).hexdigest(),
                            "source_anchor": "complete synthetic source",
                            "assertions": [
                                {
                                    "assertion_id": "criterion_adjudication_matches_source",
                                    "statement": f"The source supports claimed_result={claimed} for {criterion}",
                                    "passed": True,
                                }
                            ],
                        }
                    ],
                }
                if criterion in COUNT_CRITERIA:
                    claim["actual_count"] = COUNT_CRITERIA[criterion]
                claim_path = self.evidence_path(cid, criterion)
                self.write_json(claim_path, claim)
                criterion_rows.append({"criterion_id": criterion, "evidence_ref": ref(self.root, claim_path)})
            index_rows.append(
                {
                    "canonical_case_id": cid,
                    "identity_aliases": identity_aliases,
                    "opaque_concurrent_process_candidate_packet_ref": complexity_packet_ref,
                    "criterion_evidence": criterion_rows,
                }
            )
        self.write_json(
            self.screening,
            {
                "schema_version": "NCF-PRIMARY-CASE-SCREENING-1.1.0",
                "search_snapshot_sha256": sha(self.search),
                "candidates": screen_rows,
            },
        )
        self.write_json(
            self.index,
            {
                "schema_version": "NCF-PRIMARY-SCREENING-EVIDENCE-INDEX-1.1.0",
                "protocol_ref": ref(self.root, self.protocol),
                "search_snapshot_ref": ref(self.root, self.search),
                "screening_manifest_ref": ref(self.root, self.screening),
                "exclusions_ref": ref(self.root, self.exclusions),
                "candidates": index_rows,
            },
        )

    def run_validation(self) -> dict:
        return validate_case_screening(
            study_root=self.root,
            protocol_path=self.protocol,
            search_snapshot_path=self.search,
            screening_path=self.screening,
            exclusions_path=self.exclusions,
            evidence_index_path=self.index,
        )

    def refresh_index_ref(self, key: str, path: Path) -> None:
        index = self.read_json(self.index)
        index[key] = ref(self.root, path)
        self.write_json(self.index, index)

    def refresh_claim_ref(self, cid: str, criterion: str) -> None:
        index = self.read_json(self.index)
        row = next(row for row in index["candidates"] if row["canonical_case_id"] == cid)
        claim_row = next(row for row in row["criterion_evidence"] if row["criterion_id"] == criterion)
        claim_row["evidence_ref"] = ref(self.root, self.evidence_path(cid, criterion))
        self.write_json(self.index, index)

    def refresh_identity_ref(self, cid: str) -> None:
        index = self.read_json(self.index)
        row = next(row for row in index["candidates"] if row["canonical_case_id"] == cid)
        path = self.identity_path(cid)
        row["identity_aliases"]["raw_identity_response_ref"] = ref(self.root, path)
        raw = path.read_bytes()
        locator = row["identity_aliases"]["locators"][0]
        locator["byte_start"] = 0
        locator["byte_end"] = len(raw)
        locator["excerpt_sha256"] = hashlib.sha256(raw).hexdigest()
        self.write_json(self.index, index)

    def refresh_complexity_packet_refs(self, cid: str) -> None:
        packet_ref = ref(self.root, self.complexity_packet_path(cid))
        screening = self.read_json(self.screening)
        srow = next(row for row in screening["candidates"] if row["canonical_case_id"] == cid)
        srow["opaque_concurrent_process_candidate_packet_ref"] = packet_ref
        self.write_json(self.screening, screening)
        index = self.read_json(self.index)
        irow = next(row for row in index["candidates"] if row["canonical_case_id"] == cid)
        irow["opaque_concurrent_process_candidate_packet_ref"] = packet_ref
        index["screening_manifest_ref"] = ref(self.root, self.screening)
        self.write_json(self.index, index)

    def test_valid_chain_recomputes_three_eligible_candidates(self):
        result = self.run_validation()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["eligible_candidate_ids"], self.ids[:3])
        self.assertEqual(result["eligible_candidate_count"], 3)
        self.assertNotIn(self.excluded_id, result["eligible_candidate_ids"])

    def test_missing_criterion_evidence_fails(self):
        index = self.read_json(self.index)
        index["candidates"][0]["criterion_evidence"].pop()
        self.write_json(self.index, index)
        with self.assertRaisesRegex(ScreeningValidationError, "exactly one row per criterion"):
            self.run_validation()

    def test_claim_hash_mismatch_fails(self):
        path = self.evidence_path(self.ids[0], "single_adult_primary_case")
        path.write_text(path.read_text() + "\n", encoding="utf-8")
        with self.assertRaisesRegex(ScreeningValidationError, "evidence sha256 mismatch"):
            self.run_validation()

    def test_source_mutation_fails(self):
        self.source_path(self.ids[0]).write_text("mutated", encoding="utf-8")
        with self.assertRaisesRegex(ScreeningValidationError, "content reference mismatch|candidate source sha256 mismatch"):
            self.run_validation()

    def test_claim_identity_mismatch_fails(self):
        cid, criterion = self.ids[0], "single_adult_primary_case"
        path = self.evidence_path(cid, criterion)
        claim = self.read_json(path)
        claim["canonical_case_id"] = self.ids[1]
        self.write_json(path, claim)
        self.refresh_claim_ref(cid, criterion)
        with self.assertRaisesRegex(ScreeningValidationError, "identity mismatch"):
            self.run_validation()

    def test_claimed_result_mismatch_fails(self):
        cid, criterion = self.ids[0], "single_adult_primary_case"
        path = self.evidence_path(cid, criterion)
        claim = self.read_json(path)
        claim["claimed_result"] = False
        self.write_json(path, claim)
        self.refresh_claim_ref(cid, criterion)
        with self.assertRaisesRegex(ScreeningValidationError, "evidence claim differs"):
            self.run_validation()

    def test_evidence_backed_false_noncount_claim_is_accepted(self):
        cid, criterion = self.excluded_id, "single_adult_primary_case"
        path = self.evidence_path(cid, criterion)
        claim = self.read_json(path)
        claim["claimed_result"] = False
        self.write_json(path, claim)
        self.refresh_claim_ref(cid, criterion)
        screening = self.read_json(self.screening)
        row = next(row for row in screening["candidates"] if row["canonical_case_id"] == cid)
        row["criteria"][criterion] = False
        self.write_json(self.screening, screening)
        self.refresh_index_ref("screening_manifest_ref", self.screening)
        result = self.run_validation()
        self.assertEqual(result["eligible_candidate_ids"], self.ids[:3])

    def test_threshold_is_recomputed_from_actual_count(self):
        cid = self.ids[0]
        criterion = "minimum_guaranteed_availability_epochs_before_terminal_verification"
        path = self.evidence_path(cid, criterion)
        claim = self.read_json(path)
        claim["actual_count"] = 4
        self.write_json(path, claim)
        self.refresh_claim_ref(cid, criterion)
        with self.assertRaisesRegex(ScreeningValidationError, "independently recomputed"):
            self.run_validation()

    def test_actual_count_is_required_for_numeric_criterion(self):
        cid = self.ids[0]
        criterion = "minimum_additional_organ_domains"
        path = self.evidence_path(cid, criterion)
        claim = self.read_json(path)
        claim.pop("actual_count")
        self.write_json(path, claim)
        self.refresh_claim_ref(cid, criterion)
        with self.assertRaisesRegex(ScreeningValidationError, "must contain exactly"):
            self.run_validation()

    def test_actual_count_for_boolean_criterion_is_rejected(self):
        cid, criterion = self.ids[0], "single_adult_primary_case"
        path = self.evidence_path(cid, criterion)
        claim = self.read_json(path)
        claim["actual_count"] = 1
        self.write_json(path, claim)
        self.refresh_claim_ref(cid, criterion)
        with self.assertRaisesRegex(ScreeningValidationError, "must contain exactly"):
            self.run_validation()

    def test_exclusion_membership_is_recomputed_not_trusted(self):
        cid, criterion = self.excluded_id, "must_not_be_in_presealed_exclusion_set"
        path = self.evidence_path(cid, criterion)
        claim = self.read_json(path)
        claim["claimed_result"] = True
        self.write_json(path, claim)
        self.refresh_claim_ref(cid, criterion)
        screening = self.read_json(self.screening)
        row = next(row for row in screening["candidates"] if row["canonical_case_id"] == cid)
        row["criteria"][criterion] = True
        row["eligible"] = True
        self.write_json(self.screening, screening)
        self.refresh_index_ref("screening_manifest_ref", self.screening)
        with self.assertRaisesRegex(ScreeningValidationError, "independently recomputed"):
            self.run_validation()

    def test_pmcid_exclusion_matches_pmid_candidate_by_alias_closure(self):
        result = self.run_validation()
        self.assertIn("PMID:104", self.ids)
        self.assertNotIn("PMID:104", result["eligible_candidate_ids"])

    def test_identity_alias_omission_fails(self):
        cid = self.ids[0]
        index = self.read_json(self.index)
        row = next(row for row in index["candidates"] if row["canonical_case_id"] == cid)
        row["identity_aliases"]["aliases"].remove("PMCID:PMC101")
        self.write_json(self.index, index)
        with self.assertRaisesRegex(ScreeningValidationError, "differ from raw NCBI"):
            self.run_validation()

    def test_fabricated_crosswalk_fails_against_raw_identity_response(self):
        cid = self.ids[0]
        path = self.identity_path(cid)
        raw = self.read_json(path)
        raw["records"][0]["pmcid"] = "PMC999"
        self.write_json(path, raw)
        self.refresh_identity_ref(cid)
        with self.assertRaisesRegex(ScreeningValidationError, "differ from raw NCBI"):
            self.run_validation()

    def test_duplicate_article_identity_across_candidates_fails(self):
        cid = self.ids[1]
        path = self.identity_path(cid)
        raw = self.read_json(path)
        raw["records"][0]["pmcid"] = "PMC101"
        self.write_json(path, raw)
        index = self.read_json(self.index)
        row = next(row for row in index["candidates"] if row["canonical_case_id"] == cid)
        row["identity_aliases"]["aliases"][1] = "PMCID:PMC101"
        row["identity_aliases"]["source_document_id"] = "PMCID:PMC101"
        row["identity_aliases"]["raw_identity_response_ref"] = ref(self.root, path)
        payload = path.read_bytes()
        locator = row["identity_aliases"]["locators"][0]
        locator["byte_end"] = len(payload)
        locator["excerpt_sha256"] = hashlib.sha256(payload).hexdigest()
        self.write_json(self.index, index)
        with self.assertRaisesRegex(ScreeningValidationError, "duplicate article identity alias"):
            self.run_validation()

    def test_raw_canonical_pmid_alias_cannot_be_omitted(self):
        cid = self.ids[0]
        index = self.read_json(self.index)
        row = next(row for row in index["candidates"] if row["canonical_case_id"] == cid)
        row["identity_aliases"]["aliases"].remove(cid)
        self.write_json(self.index, index)
        with self.assertRaisesRegex(ScreeningValidationError, "differ from raw NCBI|omitted"):
            self.run_validation()

    def test_identity_response_mutation_fails_content_address(self):
        self.identity_path(self.ids[0]).write_text('{"status":"mutated"}', encoding="utf-8")
        with self.assertRaisesRegex(ScreeningValidationError, "identity response sha256 mismatch"):
            self.run_validation()

    def test_source_document_id_must_be_backed_by_same_identity_response(self):
        cid = self.ids[0]
        index = self.read_json(self.index)
        row = next(row for row in index["candidates"] if row["canonical_case_id"] == cid)
        row["identity_aliases"]["source_document_id"] = "PMCID:PMC999"
        self.write_json(self.index, index)
        with self.assertRaisesRegex(ScreeningValidationError, "not an NCBI-backed alias"):
            self.run_validation()

    def test_open_full_text_claim_requires_pmcid_source_identity(self):
        cid = self.ids[0]
        index = self.read_json(self.index)
        row = next(row for row in index["candidates"] if row["canonical_case_id"] == cid)
        row["identity_aliases"]["source_document_id"] = cid
        self.write_json(self.index, index)
        with self.assertRaisesRegex(ScreeningValidationError, "requires a PMCID"):
            self.run_validation()

    def test_screening_source_locator_must_bind_candidate_source(self):
        screening = self.read_json(self.screening)
        screening["candidates"][0]["source_locator"] = "not-content-addressed"
        self.write_json(self.screening, screening)
        self.refresh_index_ref("screening_manifest_ref", self.screening)
        with self.assertRaisesRegex(ScreeningValidationError, "source_locator does not bind"):
            self.run_validation()

    def test_locator_excerpt_hash_mismatch_fails(self):
        cid, criterion = self.ids[0], "single_adult_primary_case"
        path = self.evidence_path(cid, criterion)
        claim = self.read_json(path)
        claim["locators"][0]["excerpt_sha256"] = "0" * 64
        self.write_json(path, claim)
        self.refresh_claim_ref(cid, criterion)
        with self.assertRaisesRegex(ScreeningValidationError, "excerpt sha256 mismatch"):
            self.run_validation()

    def test_whole_document_locator_must_span_exact_bytes(self):
        cid, criterion = self.ids[0], "single_adult_primary_case"
        path = self.evidence_path(cid, criterion)
        claim = self.read_json(path)
        claim["locators"][0]["byte_start"] = 1
        source = self.source_path(cid).read_bytes()
        claim["locators"][0]["excerpt_sha256"] = hashlib.sha256(source[1:]).hexdigest()
        self.write_json(path, claim)
        self.refresh_claim_ref(cid, criterion)
        with self.assertRaisesRegex(ScreeningValidationError, "must span exact source bytes"):
            self.run_validation()

    def test_false_assertion_fails(self):
        cid, criterion = self.ids[0], "single_adult_primary_case"
        path = self.evidence_path(cid, criterion)
        claim = self.read_json(path)
        claim["locators"][0]["assertions"][0]["passed"] = False
        self.write_json(path, claim)
        self.refresh_claim_ref(cid, criterion)
        with self.assertRaisesRegex(ScreeningValidationError, "not a verified assertion"):
            self.run_validation()

    def test_candidate_omission_fails(self):
        index = self.read_json(self.index)
        index["candidates"].pop()
        self.write_json(self.index, index)
        with self.assertRaisesRegex(ScreeningValidationError, "candidate count differs"):
            self.run_validation()

    def test_screening_instance_is_strictly_validated(self):
        screening = self.read_json(self.screening)
        screening["candidates"][0].pop("screening_notes")
        self.write_json(self.screening, screening)
        self.refresh_index_ref("screening_manifest_ref", self.screening)
        with self.assertRaisesRegex(ScreeningValidationError, "must contain exactly"):
            self.run_validation()

    def test_protocol_threshold_mutation_fails(self):
        protocol = self.read_json(self.protocol)
        protocol["selection"]["eligibility"][
            "minimum_guaranteed_availability_epochs_before_terminal_verification"
        ] = 1
        self.write_json(self.protocol, protocol)
        self.refresh_index_ref("protocol_ref", self.protocol)
        with self.assertRaisesRegex(ScreeningValidationError, "differs from frozen semantics"):
            self.run_validation()

    def test_complexity_packet_tamper_fails_even_when_refs_are_refreshed(self):
        cid = self.ids[0]
        path = self.complexity_packet_path(cid)
        packet = self.read_json(path)
        packet["target_count"] = 99
        self.write_json(path, packet)
        self.refresh_complexity_packet_refs(cid)
        with self.assertRaisesRegex(ScreeningValidationError, "deterministic recompilation"):
            self.run_validation()

    def test_complexity_criterion_count_must_equal_packet(self):
        cid = self.ids[0]
        criterion = "minimum_concurrent_process_target_candidates"
        claim_path = self.evidence_path(cid, criterion)
        claim = self.read_json(claim_path)
        claim["actual_count"] = 3
        self.write_json(claim_path, claim)
        self.refresh_claim_ref(cid, criterion)
        with self.assertRaisesRegex(ScreeningValidationError, "actual_count differs from opaque packet"):
            self.run_validation()

    def test_screening_and_index_must_bind_same_complexity_packet(self):
        screening = self.read_json(self.screening)
        screening["candidates"][0]["opaque_concurrent_process_candidate_packet_ref"] = screening["candidates"][1]["opaque_concurrent_process_candidate_packet_ref"]
        self.write_json(self.screening, screening)
        self.refresh_index_ref("screening_manifest_ref", self.screening)
        with self.assertRaisesRegex(ScreeningValidationError, "bind different complexity packets"):
            self.run_validation()

    def test_evidence_index_ref_must_bind_supplied_screening(self):
        screening = self.read_json(self.screening)
        screening["candidates"][0]["screening_notes"] = "changed"
        self.write_json(self.screening, screening)
        with self.assertRaisesRegex(ScreeningValidationError, "screening manifest sha256 mismatch"):
            self.run_validation()

    def test_claim_path_is_canonical_and_identity_derived(self):
        index = self.read_json(self.index)
        row = index["candidates"][0]["criterion_evidence"][0]
        original = self.root / row["evidence_ref"]["path"]
        renamed = original.with_name("arbitrary.claim.json")
        renamed.write_bytes(original.read_bytes())
        row["evidence_ref"] = ref(self.root, renamed)
        self.write_json(self.index, index)
        with self.assertRaisesRegex(ScreeningValidationError, "canonical name"):
            self.run_validation()

    @unittest.skipUnless(hasattr(Path, "symlink_to"), "symlink support unavailable")
    def test_symlinked_claim_is_rejected_when_supported(self):
        cid, criterion = self.ids[0], "single_adult_primary_case"
        path = self.evidence_path(cid, criterion)
        real = path.with_suffix(".real.json")
        path.replace(real)
        try:
            path.symlink_to(real)
        except OSError as exc:
            self.skipTest(f"symlink creation unavailable: {exc}")
        with self.assertRaisesRegex(ScreeningValidationError, "missing or symlink"):
            self.run_validation()


if __name__ == "__main__":
    unittest.main()
