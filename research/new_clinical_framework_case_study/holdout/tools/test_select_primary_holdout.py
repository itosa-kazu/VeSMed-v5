from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from select_primary_holdout import SelectionError, select, verify_selection_record
from compile_opaque_concurrent_process_candidates import compile_claims
from validate_primary_case_screening import (
    COUNT_CRITERIA,
    PROTOCOL_ELIGIBILITY,
    _expected_claim_name,
    _expected_complexity_packet_name,
    _expected_source_name,
)
from validate_primary_search_snapshot import canonical_request_url


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def artifact_ref(root: Path, path: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": sha(path),
        "bytes": path.stat().st_size,
    }


class SelectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.exclusions = self.root / "holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json"
        self.protocol = self.root / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json"
        self.preprimary = self.root / "holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json"
        self.search = self.root / "holdout/evidence/PRIMARY_CASE_SEARCH_SNAPSHOT.json"
        self.screen = self.root / "holdout/evidence/PRIMARY_CASE_SCREENING.json"
        self.screen_evidence = (
            self.root / "holdout/evidence/PRIMARY_SCREENING_EVIDENCE_INDEX.json"
        )
        self.selection_record = self.root / "holdout/evidence/PRIMARY_HOLDOUT_SELECTION.json"
        self.exclusions.parent.mkdir(parents=True, exist_ok=True)
        self.preprimary.parent.mkdir(parents=True, exist_ok=True)
        self.exclusions.write_text(
            json.dumps(
                {
                    "schema_version": "NCF-PRIMARY-HOLDOUT-EXCLUSIONS-1.0.0",
                    "exclusion_set_id": "synthetic-selector-fixture",
                    # Deliberately use PMCID while the search universe is PMID;
                    # the validator must exclude through the source-backed alias
                    # closure rather than exact string comparison.
                    "excluded_case_ids": ["PMCID:PMC104"],
                }
            ),
            encoding="utf-8",
        )
        queries = [
            {"query_id": "Q1", "query": "one", "sort": "pub date", "retmax": 100},
            {"query_id": "Q2", "query": "two", "sort": "pub date", "retmax": 100},
        ]
        protocol_criteria = dict(PROTOCOL_ELIGIBILITY)
        self.protocol.write_text(
            json.dumps(
                {
                    "protocol_version": "1.1.0",
                    "status": "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION",
                    "selection": {
                        "sources": ["PubMed", "PubMed Central"],
                        "queries": queries,
                        "minimum_eligible_candidates": 3,
                        "eligibility": protocol_criteria,
                        "raw_search_validation": {
                            "provider": "NCBI_PUBMED_ESEARCH_JSON"
                        },
                    },
                }
            ),
            encoding="utf-8",
        )
        self._write_preprimary()
        raw_root = self.root / "holdout/evidence/primary_search_raw"
        payload_root = raw_root / "payloads"
        payload_root.mkdir(parents=True, exist_ok=True)
        query_ids = [["101", "102"], ["103", "104"]]
        query_runs = []
        for query, ids in zip(queries, query_ids):
            payload_path = payload_root / f"{query['query_id']}.response.json"
            payload_path.write_text(
                json.dumps(
                    {
                        "esearchresult": {
                            "count": str(len(ids)),
                            "retmax": str(len(ids)),
                            "retstart": "0",
                            "idlist": ids,
                        }
                    }
                ),
                encoding="utf-8",
            )
            capture_path = raw_root / f"{query['query_id']}.capture.json"
            capture_path.write_text(
                json.dumps(
                    {
                        "schema_version": "NCF-PRIMARY-RAW-SEARCH-RESPONSE-1.0.0",
                        "provider": "NCBI_PUBMED_ESEARCH_JSON",
                        "query_id": query["query_id"],
                        "retrieved_at": "2026-07-21T00:00:00Z",
                        "request": {
                            "database": "pubmed",
                            "query": query["query"],
                            "sort": query["sort"],
                            "retmax": query["retmax"],
                            "retstart": 0,
                            "retmode": "json",
                            "request_url": canonical_request_url(query),
                        },
                        "raw_payload_ref": {
                            "path": payload_path.relative_to(self.root).as_posix(),
                            "sha256": sha(payload_path),
                            "bytes": payload_path.stat().st_size,
                        },
                        "retrieved_count": len(ids),
                    }
                ),
                encoding="utf-8",
            )
            query_runs.append(
                {
                    **query,
                    "ordered_case_ids": [f"PMID:{item}" for item in ids],
                    "raw_response_ref": {
                        "path": capture_path.relative_to(self.root).as_posix(),
                        "sha256": sha(capture_path),
                    },
                }
            )
        snapshot = {
            "schema_version": "NCF-PRIMARY-SEARCH-SNAPSHOT-1.0.0",
            "retrieved_at": "2026-07-21T00:00:00Z",
            "query_runs": query_runs,
            "canonical_case_ids": ["PMID:101", "PMID:102", "PMID:103", "PMID:104"],
        }
        self.search.write_text(json.dumps(snapshot), encoding="utf-8")
        rows = []
        for cid in snapshot["canonical_case_ids"]:
            # The protocol stores numeric thresholds for count criteria, while
            # the screening manifest stores the adjudicated boolean result of
            # every criterion.  Keeping those two layers distinct mirrors the
            # production validator contract.
            row_criteria = {criterion: True for criterion in PROTOCOL_ELIGIBILITY}
            eligible = cid != "PMID:104"
            row_criteria["must_not_be_in_presealed_exclusion_set"] = eligible
            rows.append(
                {
                    "canonical_case_id": cid,
                    "eligible": eligible,
                    "criteria": row_criteria,
                    "source_locator": cid,
                    "screening_notes": "",
                }
            )
        self.screen.write_text(
            json.dumps(
                {
                    "schema_version": "NCF-PRIMARY-CASE-SCREENING-1.1.0",
                    "search_snapshot_sha256": sha(self.search),
                    "candidates": rows,
                }
            ),
            encoding="utf-8",
        )
        self._write_screening_evidence()

    def tearDown(self):
        self.tmp.cleanup()

    def _write_preprimary(self):
        payload = {
            "status": "SEALED_BEFORE_PRIMARY_CASE_SELECTION",
            "bindings": {
                "primary_execution": {
                    "protocol_json": {
                        "path": "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json",
                        "sha256": sha(self.protocol),
                        "bytes": self.protocol.stat().st_size,
                    }
                },
                "primary_holdout_exclusions": {
                    "artifact": {
                        "path": "holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json",
                        "sha256": sha(self.exclusions),
                        "bytes": self.exclusions.stat().st_size,
                    }
                },
            },
        }
        payload["payload_sha256"] = hashlib.sha256(canonical(payload)).hexdigest()
        self.preprimary.write_text(json.dumps(payload), encoding="utf-8")

    def _write_screening_evidence(self):
        source_root = self.root / "holdout/evidence/primary_screening_sources"
        claim_root = self.root / "holdout/evidence/primary_screening_evidence/claims"
        identity_root = self.root / "holdout/evidence/primary_screening_identity"
        source_root.mkdir(parents=True, exist_ok=True)
        claim_root.mkdir(parents=True, exist_ok=True)
        identity_root.mkdir(parents=True, exist_ok=True)
        screening = json.loads(self.screen.read_text())
        index_rows = []
        for row in screening["candidates"]:
            cid = row["canonical_case_id"]
            pmid = cid.split(":", 1)[1]
            pmcid = f"PMC{pmid}"
            doi = f"10.1000/synthetic.{pmid}"
            identity_path = (
                identity_root
                / f"{hashlib.sha256(cid.encode('utf-8')).hexdigest()}.identity.response.json"
            )
            identity_path.write_text(
                json.dumps(
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
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            identity_bytes = identity_path.read_bytes()
            identity_aliases = {
                "provider": "NCBI_ID_CONVERTER_JSON",
                "aliases": [cid, f"PMCID:{pmcid}", f"DOI:{doi}"],
                "source_document_id": f"PMCID:{pmcid}",
                "raw_identity_response_ref": artifact_ref(self.root, identity_path),
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
            source = source_root / _expected_source_name(cid)
            source.write_text(
                f"Synthetic evidence for {cid}; adult ICU chronology, organ domains, "
                "action response, negative evidence, delayed result, and diagnostic basis.",
                encoding="utf-8",
            )
            source_bytes = source.read_bytes()
            row["source_locator"] = source.relative_to(self.root).as_posix()
            source_ref = artifact_ref(self.root, source)

            def locator(needle: bytes) -> dict:
                start = source_bytes.index(needle)
                return {
                    "byte_start": start,
                    "byte_end": start + len(needle),
                    "excerpt_sha256": hashlib.sha256(needle).hexdigest(),
                }

            claims_path = (
                self.root
                / "holdout/evidence/primary_complexity_candidates/claims"
                / f"{hashlib.sha256(cid.encode('utf-8')).hexdigest()}.claims.json"
            )
            claims_path.parent.mkdir(parents=True, exist_ok=True)
            claims = {
                "schema_version": "NCF-OPAQUE-CONCURRENT-PROCESS-CANDIDATE-CLAIMS-1.0.0",
                "canonical_case_id": cid,
                "terminal_verification_epoch_index": 4,
                "model_blind": True,
                "disease_name_used": False,
                "process_candidates": [
                    {
                        "active_epoch_indices": [1, 2],
                        "trajectory_witnesses": [
                            {"epoch_index": 1, "source_artifact_ref": source_ref, "locator": locator(b"adult ICU chronology")},
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
                        "locator": locator(b"negative evidence"),
                    }
                ],
            }
            claims_path.write_text(json.dumps(claims, sort_keys=True), encoding="utf-8")
            packet_path = (
                self.root
                / "holdout/evidence/primary_complexity_candidates/packets"
                / _expected_complexity_packet_name(cid)
            )
            packet_path.parent.mkdir(parents=True, exist_ok=True)
            packet_path.write_text(
                json.dumps(compile_claims(study_root=self.root, claims_path=claims_path), sort_keys=True),
                encoding="utf-8",
            )
            row["opaque_concurrent_process_candidate_packet_ref"] = artifact_ref(self.root, packet_path)
            criterion_rows = []
            for criterion, claimed in row["criteria"].items():
                claim = {
                    "schema_version": "NCF-PRIMARY-SCREENING-CRITERION-EVIDENCE-1.0.0",
                    "canonical_case_id": cid,
                    "criterion_id": criterion,
                    "claimed_result": claimed,
                    "source_artifact_ref": artifact_ref(self.root, source),
                    "locators": [
                        {
                            "locator_kind": "WHOLE_DOCUMENT_REVIEW",
                            "byte_start": 0,
                            "byte_end": len(source_bytes),
                            "excerpt_sha256": hashlib.sha256(source_bytes).hexdigest(),
                            "source_anchor": "complete synthetic source",
                            "assertions": [
                                {
                                    "assertion_id": "synthetic_criterion_adjudication",
                                    "statement": f"claimed_result={claimed} for {criterion}",
                                    "passed": True,
                                }
                            ],
                        }
                    ],
                }
                if criterion in COUNT_CRITERIA:
                    claim["actual_count"] = COUNT_CRITERIA[criterion]
                claim_path = claim_root / _expected_claim_name(cid, criterion)
                claim_path.write_text(json.dumps(claim, sort_keys=True), encoding="utf-8")
                criterion_rows.append(
                    {
                        "criterion_id": criterion,
                        "evidence_ref": artifact_ref(self.root, claim_path),
                    }
                )
            index_rows.append(
                {
                    "canonical_case_id": cid,
                    "identity_aliases": identity_aliases,
                    "opaque_concurrent_process_candidate_packet_ref": artifact_ref(self.root, packet_path),
                    "criterion_evidence": criterion_rows,
                }
            )
        self.screen.write_text(json.dumps(screening), encoding="utf-8")
        self.screen_evidence.write_text(
            json.dumps(
                {
                    "schema_version": "NCF-PRIMARY-SCREENING-EVIDENCE-INDEX-1.1.0",
                    "protocol_ref": artifact_ref(self.root, self.protocol),
                    "search_snapshot_ref": artifact_ref(self.root, self.search),
                    "screening_manifest_ref": artifact_ref(self.root, self.screen),
                    "exclusions_ref": artifact_ref(self.root, self.exclusions),
                    "candidates": index_rows,
                }
            ),
            encoding="utf-8",
        )

    def _refresh_screening_evidence_input_refs(self):
        value = json.loads(self.screen_evidence.read_text())
        value["protocol_ref"] = artifact_ref(self.root, self.protocol)
        value["search_snapshot_ref"] = artifact_ref(self.root, self.search)
        value["screening_manifest_ref"] = artifact_ref(self.root, self.screen)
        value["exclusions_ref"] = artifact_ref(self.root, self.exclusions)
        self.screen_evidence.write_text(json.dumps(value), encoding="utf-8")

    def run_select(self, *, verifier_result=None, verifier_error=None):
        if verifier_result is None:
            verifier_result = {"status": "PASS"}
        patcher = mock.patch("select_primary_holdout.verify_combined_seal")
        with patcher as verifier:
            if verifier_error is not None:
                verifier.side_effect = verifier_error
            else:
                verifier.return_value = verifier_result
            result = select(
                preprimary_path=self.preprimary,
                protocol_path=self.protocol,
                exclusions_path=self.exclusions,
                search_snapshot_path=self.search,
                screening_path=self.screen,
                screening_evidence_index_path=self.screen_evidence,
            )
            verifier.assert_called_once()
            return result

    def test_deterministic_selection_and_exclusion(self):
        one = self.run_select()
        two = self.run_select()
        self.assertEqual(one, two)
        self.assertNotEqual(one["selected_case_id"], "PMID:104")
        self.assertEqual(one["eligible_candidate_count"], 3)
        self.assertEqual(
            [row["canonical_case_id"] for row in one["eligible_complexity_packet_refs"]],
            ["PMID:101", "PMID:102", "PMID:103"],
        )
        screening = json.loads(self.screen.read_text())
        expected = {
            row["canonical_case_id"]: row["opaque_concurrent_process_candidate_packet_ref"]
            for row in screening["candidates"]
        }
        for row in one["eligible_complexity_packet_refs"]:
            self.assertEqual(row["packet_ref"], expected[row["canonical_case_id"]])

    def test_executor_controlled_retrieval_metadata_cannot_change_winner(self):
        baseline = self.run_select()
        baseline_winner = baseline["selected_case_id"]
        baseline_query_hash = baseline["frozen_query_contract_sha256"]
        baseline_projection_hash = baseline["raw_ordered_identifier_projection_sha256"]
        baseline_eligible_hash = baseline["canonical_eligible_id_set_sha256"]
        seen_search_hashes = {baseline["search_snapshot_sha256"]}
        for second in range(1, 12):
            snapshot = json.loads(self.search.read_text())
            snapshot["retrieved_at"] = f"2026-07-21T00:00:{second:02d}Z"
            self.search.write_text(json.dumps(snapshot), encoding="utf-8")
            screening = json.loads(self.screen.read_text())
            screening["search_snapshot_sha256"] = sha(self.search)
            self.screen.write_text(json.dumps(screening), encoding="utf-8")
            self._write_screening_evidence()
            result = self.run_select()
            seen_search_hashes.add(result["search_snapshot_sha256"])
            self.assertEqual(result["selected_case_id"], baseline_winner)
            self.assertEqual(result["frozen_query_contract_sha256"], baseline_query_hash)
            self.assertEqual(
                result["raw_ordered_identifier_projection_sha256"], baseline_projection_hash
            )
            self.assertEqual(result["canonical_eligible_id_set_sha256"], baseline_eligible_hash)
        self.assertGreater(len(seen_search_hashes), 1)

    def test_combined_seal_metadata_cannot_change_winner(self):
        baseline = self.run_select()
        baseline_winner = baseline["selected_case_id"]
        value = json.loads(self.preprimary.read_text())
        value["generated_at"] = "2099-12-31T23:59:59Z"
        unsigned = dict(value)
        unsigned.pop("payload_sha256", None)
        value["payload_sha256"] = hashlib.sha256(canonical(unsigned)).hexdigest()
        self.preprimary.write_text(json.dumps(value), encoding="utf-8")
        result = self.run_select()
        self.assertNotEqual(
            baseline["pre_primary_payload_sha256"], result["pre_primary_payload_sha256"]
        )
        self.assertEqual(result["selected_case_id"], baseline_winner)

    def test_unscreened_retrieved_candidate_fails(self):
        value = json.loads(self.screen.read_text())
        value["candidates"].pop()
        self.screen.write_text(json.dumps(value))
        with self.assertRaisesRegex(SelectionError, "complete search universe"):
            self.run_select()

    def test_query_change_fails(self):
        value = json.loads(self.search.read_text())
        value["query_runs"][0]["query"] = "tailored query"
        self.search.write_text(json.dumps(value))
        value = json.loads(self.screen.read_text())
        value["search_snapshot_sha256"] = sha(self.search)
        self.screen.write_text(json.dumps(value))
        with self.assertRaisesRegex(SelectionError, "snapshot differs from frozen query"):
            self.run_select()

    def test_screening_hash_mismatch_fails(self):
        value = json.loads(self.screen.read_text())
        value["search_snapshot_sha256"] = "0" * 64
        self.screen.write_text(json.dumps(value))
        with self.assertRaisesRegex(SelectionError, "not bound"):
            self.run_select()

    def test_insufficient_eligible_pool_fails(self):
        value = json.loads(self.screen.read_text())
        value["candidates"][0]["criteria"]["performed_action_with_later_response"] = False
        value["candidates"][0]["eligible"] = False
        self.screen.write_text(json.dumps(value))
        self._write_screening_evidence()
        with self.assertRaisesRegex(SelectionError, "HARNESS_INCOMPLETE"):
            self.run_select()

    def test_manual_eligible_flag_disagreement_fails(self):
        value = json.loads(self.screen.read_text())
        value["candidates"][0]["eligible"] = False
        self.screen.write_text(json.dumps(value))
        self._write_screening_evidence()
        with self.assertRaisesRegex(SelectionError, "disagrees"):
            self.run_select()

    def test_exclusions_tamper_fails(self):
        self.exclusions.write_text(json.dumps({"excluded_case_ids": []}))
        with self.assertRaisesRegex(SelectionError, "differ"):
            self.run_select()

    def test_preprimary_payload_digest_tamper_fails(self):
        value = json.loads(self.preprimary.read_text())
        value["unsealed_extra"] = True
        self.preprimary.write_text(json.dumps(value))
        with self.assertRaisesRegex(SelectionError, "payload_sha256 does not match"):
            self.run_select()

    def test_protocol_mutation_after_preprimary_seal_fails(self):
        value = json.loads(self.protocol.read_text())
        value["selection"]["queries"][0]["query"] = "post-seal tailored query"
        self.protocol.write_text(json.dumps(value))
        with self.assertRaisesRegex(SelectionError, "execution protocol differs"):
            self.run_select()

    def test_raw_search_candidate_omission_fails(self):
        value = json.loads(self.search.read_text())
        value["query_runs"][0]["ordered_case_ids"].pop()
        value["canonical_case_ids"].remove("PMID:102")
        self.search.write_text(json.dumps(value))
        screening = json.loads(self.screen.read_text())
        screening["search_snapshot_sha256"] = sha(self.search)
        screening["candidates"] = [
            row for row in screening["candidates"] if row["canonical_case_id"] != "PMID:102"
        ]
        self.screen.write_text(json.dumps(screening))
        with self.assertRaisesRegex(SelectionError, "differ from exact raw response"):
            self.run_select()

    def test_combined_verifier_failure_is_fail_closed(self):
        from build_pre_primary_holdout_seal import SealError

        with self.assertRaisesRegex(SelectionError, "combined seal verification failed"):
            self.run_select(verifier_error=SealError("runtime tree drift"))

    def test_combined_verifier_nonpass_is_fail_closed(self):
        with self.assertRaisesRegex(SelectionError, "did not return PASS"):
            self.run_select(verifier_result={"status": "FAIL"})

    def test_noncanonical_preprimary_path_is_rejected(self):
        other = self.root / "preprimary-copy.json"
        other.write_bytes(self.preprimary.read_bytes())
        with mock.patch("select_primary_holdout.verify_combined_seal") as verifier:
            with self.assertRaisesRegex(SelectionError, "canonical"):
                select(
                    preprimary_path=other,
                    protocol_path=self.protocol,
                    exclusions_path=self.exclusions,
                    search_snapshot_path=self.search,
                    screening_path=self.screen,
                    screening_evidence_index_path=self.screen_evidence,
                )
            verifier.assert_not_called()


if __name__ == "__main__":
    unittest.main()
