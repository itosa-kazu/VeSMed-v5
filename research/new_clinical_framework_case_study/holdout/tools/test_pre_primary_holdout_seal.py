from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from build_pre_primary_holdout_seal import (
    ARCHITECTURE_VERSION,
    SealError,
    REL_MODEL_ROOT,
    REL_RUNTIME_ROOT,
    _canonical_bytes,
    _sha256_file,
    _tree_files,
    _tree_record,
    build_payload,
    verify_seal,
    write_seal,
)
from select_primary_holdout import SelectionError, select as select_primary_holdout
from compile_opaque_concurrent_process_candidates import compile_claims
from validate_primary_case_screening import (
    COUNT_CRITERIA,
    _expected_claim_name,
    _expected_complexity_packet_name,
    _expected_source_name,
)
from validate_primary_search_snapshot import canonical_request_url


STAMP = "2026-07-20T00:00:00+09:00"
FIXTURE_SOURCE_ROOT = Path(__file__).resolve().parents[2]
IDENTIFIABILITY_ENUM = [
    "IDENTIFIED_WITHIN_SCOPE",
    "PARTIALLY_IDENTIFIED",
    "UNIDENTIFIABLE",
    "OUT_OF_SCOPE",
]


class CombinedSealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self._make_fixture()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _write_json(self, rel: str, value: object) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
        return path

    def _artifact_ref(self, path: Path) -> dict[str, object]:
        return {
            "path": path.relative_to(self.root).as_posix(),
            "sha256": _sha256_file(path),
            "bytes": path.stat().st_size,
        }

    def _write_screening_evidence(
        self, *, protocol: Path, search: Path, screening: Path
    ) -> Path:
        source_root = self.root / "holdout/evidence/primary_screening_sources"
        claim_root = self.root / "holdout/evidence/primary_screening_evidence/claims"
        identity_root = self.root / "holdout/evidence/primary_screening_identity"
        source_root.mkdir(parents=True, exist_ok=True)
        claim_root.mkdir(parents=True, exist_ok=True)
        identity_root.mkdir(parents=True, exist_ok=True)

        screening_value = json.loads(screening.read_text(encoding="utf-8"))
        index_rows = []
        for row in screening_value["candidates"]:
            candidate_id = row["canonical_case_id"]
            pmid = candidate_id.split(":", 1)[1]
            pmcid = f"PMC{pmid}"
            doi = f"10.1000/combined-seal-fixture.{pmid}"

            identity_path = identity_root / (
                f"{hashlib.sha256(candidate_id.encode('utf-8')).hexdigest()}"
                ".identity.response.json"
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
                "aliases": [candidate_id, f"PMCID:{pmcid}", f"DOI:{doi}"],
                "source_document_id": f"PMCID:{pmcid}",
                "raw_identity_response_ref": self._artifact_ref(identity_path),
                "locators": [
                    {
                        "locator_kind": "WHOLE_DOCUMENT_REVIEW",
                        "byte_start": 0,
                        "byte_end": len(identity_bytes),
                        "excerpt_sha256": hashlib.sha256(identity_bytes).hexdigest(),
                        "source_anchor": "complete fixture identity response",
                        "assertions": [
                            {
                                "assertion_id": "identity_aliases_match_response",
                                "statement": "PMID, PMCID and DOI aliases are read from this response",
                                "passed": True,
                            }
                        ],
                    }
                ],
            }

            source_path = source_root / _expected_source_name(candidate_id)
            source_path.write_text(
                f"Fixture evidence for {candidate_id}: adult ICU chronology, two organ domains, "
                "action response, reliable negative, delayed result and diagnostic basis.",
                encoding="utf-8",
            )
            source_bytes = source_path.read_bytes()
            source_ref = self._artifact_ref(source_path)

            def locator(needle: bytes) -> dict[str, object]:
                start = source_bytes.index(needle)
                return {
                    "byte_start": start,
                    "byte_end": start + len(needle),
                    "excerpt_sha256": hashlib.sha256(needle).hexdigest(),
                }

            complexity_claims_path = (
                self.root
                / "holdout/evidence/primary_complexity_candidates/claims"
                / f"{hashlib.sha256(candidate_id.encode('utf-8')).hexdigest()}.claims.json"
            )
            complexity_claims = {
                "schema_version": "NCF-OPAQUE-CONCURRENT-PROCESS-CANDIDATE-CLAIMS-1.0.0",
                "canonical_case_id": candidate_id,
                "terminal_verification_epoch_index": 4,
                "model_blind": True,
                "disease_name_used": False,
                "process_candidates": [
                    {
                        "active_epoch_indices": [1, 2],
                        "trajectory_witnesses": [
                            {"epoch_index": 1, "source_artifact_ref": source_ref, "locator": locator(b"adult ICU chronology")},
                            {"epoch_index": 2, "source_artifact_ref": source_ref, "locator": locator(b"two organ domains")},
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
                        "locator": locator(b"reliable negative"),
                    }
                ],
            }
            self._write_json(
                complexity_claims_path.relative_to(self.root).as_posix(),
                complexity_claims,
            )
            complexity_packet_path = (
                self.root
                / "holdout/evidence/primary_complexity_candidates/packets"
                / _expected_complexity_packet_name(candidate_id)
            )
            self._write_json(
                complexity_packet_path.relative_to(self.root).as_posix(),
                compile_claims(study_root=self.root, claims_path=complexity_claims_path),
            )
            complexity_packet_ref = self._artifact_ref(complexity_packet_path)
            row["source_locator"] = source_path.relative_to(self.root).as_posix()
            row["opaque_concurrent_process_candidate_packet_ref"] = complexity_packet_ref
            row["screening_notes"] = ""

            criterion_rows = []
            for criterion, claimed in row["criteria"].items():
                claim = {
                    "schema_version": "NCF-PRIMARY-SCREENING-CRITERION-EVIDENCE-1.0.0",
                    "canonical_case_id": candidate_id,
                    "criterion_id": criterion,
                    "claimed_result": claimed,
                    "source_artifact_ref": self._artifact_ref(source_path),
                    "locators": [
                        {
                            "locator_kind": "WHOLE_DOCUMENT_REVIEW",
                            "byte_start": 0,
                            "byte_end": len(source_bytes),
                            "excerpt_sha256": hashlib.sha256(source_bytes).hexdigest(),
                            "source_anchor": "complete fixture source",
                            "assertions": [
                                {
                                    "assertion_id": "fixture_criterion_adjudication",
                                    "statement": f"claimed_result={claimed} for {criterion}",
                                    "passed": True,
                                }
                            ],
                        }
                    ],
                }
                if criterion in COUNT_CRITERIA:
                    claim["actual_count"] = COUNT_CRITERIA[criterion]
                claim_path = claim_root / _expected_claim_name(candidate_id, criterion)
                claim_path.write_text(json.dumps(claim, sort_keys=True), encoding="utf-8")
                criterion_rows.append(
                    {
                        "criterion_id": criterion,
                        "evidence_ref": self._artifact_ref(claim_path),
                    }
                )
            index_rows.append(
                {
                    "canonical_case_id": candidate_id,
                    "identity_aliases": identity_aliases,
                    "opaque_concurrent_process_candidate_packet_ref": complexity_packet_ref,
                    "criterion_evidence": criterion_rows,
                }
            )

        screening.write_text(json.dumps(screening_value, indent=2) + "\n", encoding="utf-8")
        exclusions = self.root / "holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json"
        return self._write_json(
            "holdout/evidence/PRIMARY_SCREENING_EVIDENCE_INDEX.json",
            {
                "schema_version": "NCF-PRIMARY-SCREENING-EVIDENCE-INDEX-1.1.0",
                "protocol_ref": self._artifact_ref(protocol),
                "search_snapshot_ref": self._artifact_ref(search),
                "screening_manifest_ref": self._artifact_ref(screening),
                "exclusions_ref": self._artifact_ref(exclusions),
                "candidates": index_rows,
            },
        )

    def _runtime_manifest(self) -> dict:
        rows = []
        for rel in (
            "runtime_v2/__init__.py",
            "runtime_v2/engine.py",
            "runtime_v2/schemas/model_v2.schema.json",
            "runtime_v2/tests/test_runtime_v2.py",
        ):
            path = self.root / rel
            rows.append({"path": rel, "sha256": _sha256_file(path), "bytes": path.stat().st_size})
        tree = _tree_record(_tree_files(self.root, REL_RUNTIME_ROOT))
        return {
            "manifest_kind": "runtime_v2_1_case_blind_implementation_manifest",
            "runtime_version": "2.1",
            "architecture_version": ARCHITECTURE_VERSION,
            "case_blind": True,
            "source_tree": {
                "file_count": tree["file_count"],
                "total_bytes": tree["total_bytes"],
                "tree_sha256": tree["tree_sha256"],
            },
            "files": rows,
        }

    def _make_fixture(self) -> None:
        (self.root / "ARCHITECTURE_FINAL_v1.md").write_text("# frozen architecture\n", encoding="utf-8")
        self._write_json(
            "architecture_final_v1.schema.json",
            {
                "title": ARCHITECTURE_VERSION,
                "type": "object",
                "$defs": {
                    "identifiabilityClaim": {
                        "type": "object",
                        "properties": {"status": {"enum": IDENTIFIABILITY_ENUM}},
                    }
                },
            },
        )
        (self.root / "holdout").mkdir(parents=True, exist_ok=True)
        (self.root / "holdout/PERFECT_LANDING_GATES.md").write_text(
            "# frozen human-readable gates\n", encoding="utf-8"
        )
        arch_hash = _sha256_file(self.root / "ARCHITECTURE_FINAL_v1.md")
        schema_hash = _sha256_file(self.root / "architecture_final_v1.schema.json")
        gates_markdown_hash = _sha256_file(self.root / "holdout/PERFECT_LANDING_GATES.md")
        gates = {
            "contract_id": "NCF-PERFECT-LANDING-GATES",
            "contract_version": "1.1.0",
            "status": "FROZEN_BEFORE_HOLDOUT_INSPECTION",
            "identifiability_enum": IDENTIFIABILITY_ENUM,
            "architecture_binding": {
                "architecture_version": ARCHITECTURE_VERSION,
                "architecture_document_sha256": arch_hash,
                "wire_schema_sha256": schema_hash,
            },
            "aggregation": {"top1_diagnosis_can_override_failure": False},
            "gates": [
                {"id": f"PL-{i:03d}", "severity": "HARD"}
                for i in range(1, 31)
            ],
        }
        self._write_json("holdout/PERFECT_LANDING_GATES.json", gates)
        gates_hash = _sha256_file(self.root / "holdout/PERFECT_LANDING_GATES.json")
        self._write_json(
            "holdout/PERFECT_LANDING_GATES.seal.json",
            {
                "case_identity_included": False,
                "artifacts": [
                    {"path": "PERFECT_LANDING_GATES.md", "sha256": gates_markdown_hash},
                    {"path": "../ARCHITECTURE_FINAL_v1.md", "sha256": arch_hash},
                    {"path": "../architecture_final_v1.schema.json", "sha256": schema_hash},
                    {"path": "PERFECT_LANDING_GATES.json", "sha256": gates_hash},
                ],
            },
        )

        for rel, content in {
            "runtime_v2/__init__.py": "# neutral runtime\n",
            "runtime_v2/engine.py": "def update(state, event): return state\n",
            "runtime_v2/schemas/model_v2.schema.json": '{"type":"object"}\n',
            "runtime_v2/tests/test_runtime_v2.py": "def test_neutral(): assert True\n",
        }.items():
            path = self.root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        manifest_path = self._write_json("runtime_v2/evidence/manifest.json", self._runtime_manifest())
        runtime_seal_path = self._write_json(
            "runtime_v2/evidence/FREEZE_SEAL.json",
            {
                "seal_kind": "runtime_v2_1_case_blind_freeze",
                "runtime_version": "2.1",
                "architecture_version": ARCHITECTURE_VERSION,
                "case_blind": True,
                "final": True,
                "frozen_at": STAMP,
                "manifest_sha256": _sha256_file(manifest_path),
                "source_tree_sha256": self._runtime_manifest()["source_tree"]["tree_sha256"],
            },
        )

        model_pack = self._write_json("holdout/generic_model/model_pack.json", {"processes": ["A", "B"]})
        model_validation = self._write_json(
            "holdout/generic_model/model_validation.json",
            {
                "architecture_version": ARCHITECTURE_VERSION,
                "runtime_version": "2.1",
                "case_blind": True,
                "status": "PASS",
                "tests": [{"name": "neutral", "result": "PASS"}],
                "runtime_binding": {
                    "runtime_version": "2.1",
                    "seal_kind": "runtime_v2_1_case_blind_freeze",
                    "manifest_sha256": _sha256_file(manifest_path),
                    "seal_sha256": _sha256_file(runtime_seal_path),
                },
            },
        )
        (self.root / "holdout/generic_model/_build_generic_model.py").write_text(
            "# generic, no holdout\n", encoding="utf-8"
        )
        shutil.copyfile(
            FIXTURE_SOURCE_ROOT / "holdout/generic_model/mapper_sanitized_registry.json",
            self.root / "holdout/generic_model/mapper_sanitized_registry.json",
        )
        model_source_files = [item.as_dict() for item in _tree_files(self.root, REL_MODEL_ROOT)]
        self._write_json(
            "holdout/evidence/GENERIC_MODEL_FREEZE_SEAL.json",
            {
                "seal_kind": "generic_model_case_blind_freeze",
                "runtime_version": "2.1",
                "architecture_version": ARCHITECTURE_VERSION,
                "case_blind": True,
                "final": True,
                "sealed_at": STAMP,
                "model_pack_sha256": _sha256_file(model_pack),
                "validation_sha256": _sha256_file(model_validation),
                "source_tree_sha256": _tree_record(_tree_files(self.root, REL_MODEL_ROOT))["tree_sha256"],
                "source_files": model_source_files,
            },
        )
        self._write_json(
            "holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json",
            {
                "schema_version": "NCF-PRIMARY-HOLDOUT-EXCLUSIONS-1.0.0",
                "exclusion_set_id": "fixture-v1",
                "excluded_case_ids": ["PMCID:PMC9001", "PMID:9002"],
            },
        )

        # The combined-seal fixture binds the actual frozen, case-blind
        # execution/scoring/scorer assets.  Individual tests mutate copies in
        # the temporary tree, never the workspace originals.
        for rel in (
            "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.md",
            "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json",
            "holdout/PRIMARY_HOLDOUT_SCORING_v1.json",
            "holdout/tools/build_pre_primary_holdout_seal.py",
            "holdout/tools/test_pre_primary_holdout_seal.py",
            "holdout/tools/select_primary_holdout.py",
            "holdout/tools/test_select_primary_holdout.py",
            "holdout/tools/validate_primary_search_snapshot.py",
            "holdout/tools/test_validate_primary_search_snapshot.py",
            "holdout/tools/compile_primary_search_snapshot.py",
            "holdout/tools/test_compile_primary_search_snapshot.py",
            "holdout/tools/validate_primary_case_screening.py",
            "holdout/tools/test_validate_primary_case_screening.py",
            "holdout/tools/compile_opaque_concurrent_process_candidates.py",
            "holdout/tools/test_compile_opaque_concurrent_process_candidates.py",
            "holdout/tools/compile_evaluator_sanitized_runtime_ledger.py",
            "holdout/tools/test_compile_evaluator_sanitized_runtime_ledger.py",
            "holdout/tools/verify_evaluator_sanitized_runtime_ledger.py",
            "holdout/tools/test_verify_evaluator_sanitized_runtime_ledger.py",
            "holdout/tools/validate_primary_holdout_protocol.py",
            "holdout/tools/test_validate_primary_holdout_protocol.py",
            "holdout/tools/final_primary_holdout_scorer.py",
            "holdout/tools/test_final_primary_holdout_scorer.py",
            "holdout/tools/producer_replay_verifier.py",
            "holdout/tools/test_producer_replay_verifier.py",
            "holdout/tools/primary_case_gate_evaluator.py",
            "holdout/tools/test_primary_case_gate_evaluator.py",
            "holdout/tools/test_primary_case_gate_evaluator_runtime.py",
            "holdout/tools/compile_primary_case_gate_evidence.py",
            "holdout/tools/test_compile_primary_case_gate_evidence.py",
            "holdout/tools/primary_runtime_replay_executor.py",
            "holdout/tools/test_primary_runtime_replay_executor.py",
            "holdout/tools/compile_availability_epochs.py",
            "holdout/tools/test_compile_availability_epochs.py",
            "holdout/tools/event_ledger_replay.py",
            "holdout/tools/test_event_ledger_replay.py",
            "holdout/tools/structural_gate_harness.py",
            "holdout/tools/test_structural_gate_harness.py",
            "holdout/tools/structural_gate_evidence.schema.json",
            "holdout/tools/structural_gate_results.schema.json",
            "holdout/schemas/primary_role_execution_manifest.schema.json",
            "holdout/schemas/primary_role_manifest_set.schema.json",
            "holdout/schemas/primary_role_tool_access_trace.schema.json",
            "holdout/schemas/evaluator_sanitized_runtime_ledger.schema.json",
            "holdout/schemas/evaluator_sanitized_runtime_ledger_compiler_input.schema.json",
            "holdout/schemas/evaluator_sanitized_runtime_ledger_assignment_proof.schema.json",
            "holdout/schemas/evaluator_sanitized_runtime_ledger_replay_verification.schema.json",
            "holdout/schemas/primary_all_sealed_artifacts_after_replay.schema.json",
            "holdout/schemas/sealed_concept_map.schema.json",
            "holdout/schemas/primary_case_search_snapshot.schema.json",
            "holdout/schemas/primary_raw_search_response.schema.json",
            "holdout/schemas/primary_search_retrieval_manifest.schema.json",
            "holdout/schemas/primary_case_screening.schema.json",
            "holdout/schemas/primary_screening_evidence.schema.json",
            "holdout/schemas/primary_opaque_concurrent_process_candidate_claims.schema.json",
            "holdout/schemas/primary_opaque_concurrent_process_candidate_packet.schema.json",
            "holdout/schemas/primary_sealed_opaque_concurrent_process_candidate_packet.schema.json",
            "holdout/schemas/mapped_observation_consumption.schema.json",
            "holdout/schemas/primary_gate_evidence.schema.json",
            "holdout/schemas/primary_case_gate_evaluator_input.schema.json",
            "holdout/schemas/primary_case_gate_evaluation.schema.json",
            "holdout/schemas/primary_report_candidate.schema.json",
            "holdout/schemas/primary_runtime_replay_input_manifest.schema.json",
            "holdout/schemas/primary_runtime_output.schema.json",
            "holdout/schemas/primary_runtime_replay_seal.schema.json",
            "holdout/schemas/primary_holdout_final_result.schema.json",
            "holdout/schemas/primary_availability_ledger.schema.json",
        ):
            source = FIXTURE_SOURCE_ROOT / rel
            target = self.root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

    def test_build_and_verify(self) -> None:
        output = write_seal(self.root, sealed_at=STAMP)
        self.assertTrue(output.is_file())
        result = verify_seal(self.root)
        self.assertEqual(result["status"], "PASS")

        payload = json.loads(output.read_text(encoding="utf-8"))
        execution = payload["bindings"]["primary_execution"]
        self.assertEqual(
            execution["event_ledger_replay"]["path"],
            "holdout/tools/event_ledger_replay.py",
        )
        self.assertEqual(
            execution["structural_gate_harness"]["path"],
            "holdout/tools/structural_gate_harness.py",
        )
        self.assertEqual(
            execution["primary_case_gate_evaluator"]["path"],
            "holdout/tools/primary_case_gate_evaluator.py",
        )
        self.assertEqual(
            execution["primary_gate_evidence_compiler"]["path"],
            "holdout/tools/compile_primary_case_gate_evidence.py",
        )
        self.assertEqual(
            execution["primary_runtime_replay_executor"]["path"],
            "holdout/tools/primary_runtime_replay_executor.py",
        )
        self.assertEqual(
            execution["screening_validator"]["path"],
            "holdout/tools/validate_primary_case_screening.py",
        )
        self.assertEqual(
            execution["screening_evidence_schema"]["path"],
            "holdout/schemas/primary_screening_evidence.schema.json",
        )
        self.assertEqual(
            execution["evaluator_sanitized_runtime_ledger_schema"]["path"],
            "holdout/schemas/evaluator_sanitized_runtime_ledger.schema.json",
        )
        self.assertEqual(
            execution["evaluator_sanitized_runtime_ledger_compiler"]["path"],
            "holdout/tools/compile_evaluator_sanitized_runtime_ledger.py",
        )
        self.assertEqual(
            execution["evaluator_sanitized_runtime_ledger_replay_verifier"]["path"],
            "holdout/tools/verify_evaluator_sanitized_runtime_ledger.py",
        )
        self.assertEqual(
            execution["all_sealed_artifacts_after_replay_schema"]["path"],
            "holdout/schemas/primary_all_sealed_artifacts_after_replay.schema.json",
        )
        self.assertEqual(
            execution["sealed_concept_map_schema"]["path"],
            "holdout/schemas/sealed_concept_map.schema.json",
        )
        self.assertFalse(payload["invariants"]["generated_primary_results_bound_preprimary"])
        self.assertNotIn("structural_gate_results", execution)

    def _valid_selection_inputs(self) -> tuple[Path, Path, Path]:
        protocol_path = self.root / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json"
        protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
        queries = protocol["selection"]["queries"]
        candidate_ids = ["PMCID:CANDIDATE-A", "PMCID:CANDIDATE-B", "PMCID:CANDIDATE-C"]
        query_runs = []
        for index, query in enumerate(queries):
            ids = candidate_ids if index == 0 else []
            # The raw validator requires numeric PubMed identifiers; keep the
            # fixture readable while using three deterministic numeric ids.
            raw_ids = [str(position + 1) for position, _ in enumerate(ids)]
            canonical_ids_for_query = [f"PMID:{item}" for item in raw_ids]
            payload_path = self._write_json(
                f"holdout/evidence/primary_search_raw/payloads/{query['query_id']}.response.json",
                {
                    "esearchresult": {
                        "count": str(len(raw_ids)),
                        "retmax": str(len(raw_ids)),
                        "retstart": "0",
                        "idlist": raw_ids,
                    }
                },
            )
            raw_path = self._write_json(
                f"holdout/evidence/primary_search_raw/{query['query_id']}.capture.json",
                {
                    "schema_version": "NCF-PRIMARY-RAW-SEARCH-RESPONSE-1.0.0",
                    "provider": "NCBI_PUBMED_ESEARCH_JSON",
                    "query_id": query["query_id"],
                    "retrieved_at": STAMP,
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
                        "sha256": _sha256_file(payload_path),
                        "bytes": payload_path.stat().st_size,
                    },
                    "retrieved_count": len(raw_ids),
                },
            )
            query_runs.append(
                {
                    **query,
                    "ordered_case_ids": canonical_ids_for_query,
                    "raw_response_ref": {
                        "path": raw_path.relative_to(self.root).as_posix(),
                        "sha256": _sha256_file(raw_path),
                    },
                }
            )
        candidate_ids = ["PMID:1", "PMID:2", "PMID:3"]
        search = self._write_json(
            "holdout/evidence/PRIMARY_CASE_SEARCH_SNAPSHOT.json",
            {
                "schema_version": "NCF-PRIMARY-SEARCH-SNAPSHOT-1.0.0",
                "retrieved_at": STAMP,
                "query_runs": query_runs,
                "canonical_case_ids": sorted(candidate_ids),
            },
        )
        criteria = {key: True for key in protocol["selection"]["eligibility"]}
        screening = self._write_json(
            "holdout/evidence/PRIMARY_CASE_SCREENING.json",
            {
                "schema_version": "NCF-PRIMARY-CASE-SCREENING-1.1.0",
                "search_snapshot_sha256": _sha256_file(search),
                "candidates": [
                    {
                        "canonical_case_id": candidate_id,
                        "eligible": True,
                        "criteria": dict(criteria),
                    }
                    for candidate_id in sorted(candidate_ids)
                ],
            },
        )
        screening_evidence = self._write_screening_evidence(
            protocol=protocol_path,
            search=search,
            screening=screening,
        )
        return search, screening, screening_evidence

    def test_selector_invokes_and_accepts_valid_combined_verifier(self) -> None:
        preprimary = write_seal(self.root, sealed_at=STAMP)
        search, screening, screening_evidence = self._valid_selection_inputs()
        result = select_primary_holdout(
            preprimary_path=preprimary,
            protocol_path=self.root / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json",
            exclusions_path=self.root / "holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json",
            search_snapshot_path=search,
            screening_path=screening,
            screening_evidence_index_path=screening_evidence,
        )
        self.assertIn(result["selected_case_id"], {"PMID:1", "PMID:2", "PMID:3"})

    def test_selector_rejects_component_drift_after_combined_seal(self) -> None:
        preprimary = write_seal(self.root, sealed_at=STAMP)
        search, screening, screening_evidence = self._valid_selection_inputs()
        (self.root / "runtime_v2/engine.py").write_text("# drift after combined seal\n", encoding="utf-8")
        with self.assertRaisesRegex(SelectionError, "combined seal verification failed"):
            select_primary_holdout(
                preprimary_path=preprimary,
                protocol_path=self.root / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json",
                exclusions_path=self.root / "holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json",
                search_snapshot_path=search,
                screening_path=screening,
                screening_evidence_index_path=screening_evidence,
            )

    def test_recursive_runtime_mutation_breaks_verification(self) -> None:
        write_seal(self.root, sealed_at=STAMP)
        (self.root / "runtime_v2/engine.py").write_text("# changed after freeze\n", encoding="utf-8")
        with self.assertRaises(SealError):
            verify_seal(self.root)

    def test_pending_model_fails_without_output(self) -> None:
        validation = json.loads((self.root / "holdout/generic_model/model_validation.json").read_text())
        validation["status"] = "PENDING_RUNTIME_FREEZE"
        self._write_json("holdout/generic_model/model_validation.json", validation)
        with self.assertRaises(SealError):
            write_seal(self.root, sealed_at=STAMP)
        self.assertFalse((self.root / "holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json").exists())

    def test_old_runtime_contract_fails(self) -> None:
        seal_path = self.root / "runtime_v2/evidence/FREEZE_SEAL.json"
        seal = json.loads(seal_path.read_text())
        seal["seal_kind"] = "runtime_v2_case_blind_freeze"
        seal.pop("runtime_version")
        self._write_json("runtime_v2/evidence/FREEZE_SEAL.json", seal)
        with self.assertRaises(SealError):
            build_payload(self.root, sealed_at=STAMP)

    def test_case_shaped_source_path_is_rejected_before_hash(self) -> None:
        forbidden = self.root / "holdout/generic_model/primary_case.json"
        forbidden.write_text("this must never be read", encoding="utf-8")
        with self.assertRaisesRegex(SealError, "case-shaped source path"):
            build_payload(self.root, sealed_at=STAMP)

    def test_case_shaped_runtime_manifest_path_is_rejected_before_open(self) -> None:
        forbidden = self.root / "runtime_v2/evidence/primary_case.json"
        forbidden.write_text("sentinel patient narrative that must never be read", encoding="utf-8")
        manifest_path = self.root / "runtime_v2/evidence/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"].append(
            {
                "path": "runtime_v2/evidence/primary_case.json",
                "sha256": _sha256_file(forbidden),
                "bytes": forbidden.stat().st_size,
            }
        )
        self._write_json("runtime_v2/evidence/manifest.json", manifest)
        seal_path = self.root / "runtime_v2/evidence/FREEZE_SEAL.json"
        seal = json.loads(seal_path.read_text())
        seal["manifest_sha256"] = _sha256_file(manifest_path)
        self._write_json("runtime_v2/evidence/FREEZE_SEAL.json", seal)

        original_open = Path.open

        def guarded_open(path: Path, *args, **kwargs):
            if path.resolve(strict=False) == forbidden.resolve(strict=False):
                raise AssertionError("builder opened a case-shaped runtime evidence path")
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", guarded_open):
            with self.assertRaisesRegex(SealError, "forbidden before open"):
                build_payload(self.root, sealed_at=STAMP)

    def test_stale_runtime_manifest_hash_fails(self) -> None:
        manifest_path = self.root / "runtime_v2/evidence/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"][0]["sha256"] = "0" * 64
        self._write_json("runtime_v2/evidence/manifest.json", manifest)
        seal_path = self.root / "runtime_v2/evidence/FREEZE_SEAL.json"
        seal = json.loads(seal_path.read_text())
        seal["manifest_sha256"] = _sha256_file(manifest_path)
        self._write_json("runtime_v2/evidence/FREEZE_SEAL.json", seal)
        with self.assertRaisesRegex(SealError, "hash mismatch for runtime manifest"):
            build_payload(self.root, sealed_at=STAMP)

    def test_runtime_manifest_stale_source_tree_summary_fails(self) -> None:
        manifest_path = self.root / "runtime_v2/evidence/manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["source_tree"]["tree_sha256"] = "0" * 64
        self._write_json("runtime_v2/evidence/manifest.json", manifest)
        seal_path = self.root / "runtime_v2/evidence/FREEZE_SEAL.json"
        seal = json.loads(seal_path.read_text())
        seal["manifest_sha256"] = _sha256_file(manifest_path)
        self._write_json("runtime_v2/evidence/FREEZE_SEAL.json", seal)
        with self.assertRaisesRegex(SealError, "source_tree summary"):
            build_payload(self.root, sealed_at=STAMP)

    def test_model_validation_bound_to_superseded_runtime_seal_fails(self) -> None:
        # Change and validly reseal the runtime component without revalidating
        # the generic model.  Version labels remain the same; exact artifact
        # binding must still reject this stale component combination.
        seal_path = self.root / "runtime_v2/evidence/FREEZE_SEAL.json"
        seal = json.loads(seal_path.read_text())
        seal["frozen_at"] = "2026-07-20T00:00:01+09:00"
        self._write_json("runtime_v2/evidence/FREEZE_SEAL.json", seal)
        with self.assertRaisesRegex(SealError, "generic model bound runtime seal"):
            build_payload(self.root, sealed_at=STAMP)

    def test_generic_model_source_mutation_after_component_seal_fails(self) -> None:
        (self.root / "holdout/generic_model/_build_generic_model.py").write_text(
            "# changed after generic-model freeze\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(SealError, "does not bind the current recursive source tree"):
            build_payload(self.root, sealed_at=STAMP)

    def test_gate_markdown_tamper_breaks_component_seal(self) -> None:
        (self.root / "holdout/PERFECT_LANDING_GATES.md").write_text(
            "# tampered after gate freeze\n", encoding="utf-8"
        )
        with self.assertRaisesRegex(SealError, "gate seal artifact PERFECT_LANDING_GATES.md"):
            build_payload(self.root, sealed_at=STAMP)

    def test_gate_identifiability_enum_mismatch_fails(self) -> None:
        path = self.root / "holdout/PERFECT_LANDING_GATES.json"
        gates = json.loads(path.read_text())
        gates["identifiability_enum"] = ["IDENTIFIED", "PARTIALLY_IDENTIFIED", "UNIDENTIFIABLE"]
        self._write_json("holdout/PERFECT_LANDING_GATES.json", gates)
        with self.assertRaisesRegex(SealError, "identifiability enum"):
            build_payload(self.root, sealed_at=STAMP)

    def test_final_scorer_mutation_after_combined_seal_breaks_verification(self) -> None:
        write_seal(self.root, sealed_at=STAMP)
        path = self.root / "holdout/tools/final_primary_holdout_scorer.py"
        path.write_text(path.read_text(encoding="utf-8") + "\n# post-seal mutation\n", encoding="utf-8")
        with self.assertRaises(SealError):
            verify_seal(self.root)

    def test_deleted_role_policy_fails_before_combined_seal(self) -> None:
        path = self.root / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json"
        protocol = json.loads(path.read_text(encoding="utf-8"))
        protocol.pop("roles")
        self._write_json("holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json", protocol)
        with self.assertRaisesRegex(Exception, "roles"):
            build_payload(self.root, sealed_at=STAMP)

    def test_id_only_role_schema_fails_before_combined_seal(self) -> None:
        self._write_json(
            "holdout/schemas/primary_role_execution_manifest.schema.json",
            {"$id": "ncf.primary-role-execution-manifest.v1.1"},
        )
        with self.assertRaisesRegex(Exception, "role schema|role manifest schema|required"):
            build_payload(self.root, sealed_at=STAMP)

    def test_final_result_schema_mutation_after_combined_seal_breaks_verification(self) -> None:
        write_seal(self.root, sealed_at=STAMP)
        path = self.root / "holdout/schemas/primary_holdout_final_result.schema.json"
        schema = json.loads(path.read_text())
        schema["title"] = "tampered"
        self._write_json("holdout/schemas/primary_holdout_final_result.schema.json", schema)
        with self.assertRaises(SealError):
            verify_seal(self.root)

    def test_every_bound_execution_or_selection_asset_mutation_breaks_verification(self) -> None:
        """No frozen protocol/scoring/selection byte may drift post-seal."""

        write_seal(self.root, sealed_at=STAMP)
        bound_paths = (
            "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.md",
            "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json",
            "holdout/PRIMARY_HOLDOUT_SCORING_v1.json",
            "holdout/tools/build_pre_primary_holdout_seal.py",
            "holdout/tools/test_pre_primary_holdout_seal.py",
            "holdout/tools/select_primary_holdout.py",
            "holdout/tools/test_select_primary_holdout.py",
            "holdout/tools/validate_primary_search_snapshot.py",
            "holdout/tools/test_validate_primary_search_snapshot.py",
            "holdout/tools/compile_primary_search_snapshot.py",
            "holdout/tools/test_compile_primary_search_snapshot.py",
            "holdout/tools/validate_primary_case_screening.py",
            "holdout/tools/test_validate_primary_case_screening.py",
            "holdout/tools/compile_opaque_concurrent_process_candidates.py",
            "holdout/tools/test_compile_opaque_concurrent_process_candidates.py",
            "holdout/tools/compile_evaluator_sanitized_runtime_ledger.py",
            "holdout/tools/test_compile_evaluator_sanitized_runtime_ledger.py",
            "holdout/tools/verify_evaluator_sanitized_runtime_ledger.py",
            "holdout/tools/test_verify_evaluator_sanitized_runtime_ledger.py",
            "holdout/tools/validate_primary_holdout_protocol.py",
            "holdout/tools/test_validate_primary_holdout_protocol.py",
            "holdout/tools/final_primary_holdout_scorer.py",
            "holdout/tools/test_final_primary_holdout_scorer.py",
            "holdout/tools/producer_replay_verifier.py",
            "holdout/tools/test_producer_replay_verifier.py",
            "holdout/tools/primary_case_gate_evaluator.py",
            "holdout/tools/test_primary_case_gate_evaluator.py",
            "holdout/tools/test_primary_case_gate_evaluator_runtime.py",
            "holdout/tools/compile_primary_case_gate_evidence.py",
            "holdout/tools/test_compile_primary_case_gate_evidence.py",
            "holdout/tools/primary_runtime_replay_executor.py",
            "holdout/tools/test_primary_runtime_replay_executor.py",
            "holdout/tools/compile_availability_epochs.py",
            "holdout/tools/test_compile_availability_epochs.py",
            "holdout/tools/event_ledger_replay.py",
            "holdout/tools/test_event_ledger_replay.py",
            "holdout/tools/structural_gate_harness.py",
            "holdout/tools/test_structural_gate_harness.py",
            "holdout/tools/structural_gate_evidence.schema.json",
            "holdout/tools/structural_gate_results.schema.json",
            "holdout/schemas/primary_role_execution_manifest.schema.json",
            "holdout/schemas/primary_role_manifest_set.schema.json",
            "holdout/schemas/primary_role_tool_access_trace.schema.json",
            "holdout/schemas/evaluator_sanitized_runtime_ledger.schema.json",
            "holdout/schemas/evaluator_sanitized_runtime_ledger_compiler_input.schema.json",
            "holdout/schemas/evaluator_sanitized_runtime_ledger_assignment_proof.schema.json",
            "holdout/schemas/evaluator_sanitized_runtime_ledger_replay_verification.schema.json",
            "holdout/schemas/primary_all_sealed_artifacts_after_replay.schema.json",
            "holdout/schemas/sealed_concept_map.schema.json",
            "holdout/schemas/primary_case_search_snapshot.schema.json",
            "holdout/schemas/primary_raw_search_response.schema.json",
            "holdout/schemas/primary_search_retrieval_manifest.schema.json",
            "holdout/schemas/primary_case_screening.schema.json",
            "holdout/schemas/primary_screening_evidence.schema.json",
            "holdout/schemas/primary_opaque_concurrent_process_candidate_claims.schema.json",
            "holdout/schemas/primary_opaque_concurrent_process_candidate_packet.schema.json",
            "holdout/schemas/primary_sealed_opaque_concurrent_process_candidate_packet.schema.json",
            "holdout/schemas/mapped_observation_consumption.schema.json",
            "holdout/schemas/primary_holdout_final_result.schema.json",
            "holdout/schemas/primary_gate_evidence.schema.json",
            "holdout/schemas/primary_case_gate_evaluator_input.schema.json",
            "holdout/schemas/primary_case_gate_evaluation.schema.json",
            "holdout/schemas/primary_report_candidate.schema.json",
            "holdout/schemas/primary_runtime_replay_input_manifest.schema.json",
            "holdout/schemas/primary_runtime_output.schema.json",
            "holdout/schemas/primary_runtime_replay_seal.schema.json",
            "holdout/schemas/primary_availability_ledger.schema.json",
            "holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json",
        )
        for rel in bound_paths:
            with self.subTest(rel=rel):
                path = self.root / rel
                original = path.read_bytes()
                try:
                    # Appending whitespace preserves JSON validity while still
                    # proving the exact frozen bytes are authoritative.  The
                    # same mutation is also harmless syntax for MD/Python.
                    path.write_bytes(original + b"\n")
                    with self.assertRaises(SealError):
                        verify_seal(self.root)
                finally:
                    path.write_bytes(original)

    def test_scoring_contract_cannot_enable_diagnosis_override(self) -> None:
        path = self.root / "holdout/PRIMARY_HOLDOUT_SCORING_v1.json"
        scoring = json.loads(path.read_text())
        scoring["final_scorer_contract"]["correct_diagnosis_override_forbidden"] = False
        self._write_json("holdout/PRIMARY_HOLDOUT_SCORING_v1.json", scoring)
        with self.assertRaisesRegex(SealError, "final scorer contract mismatch"):
            build_payload(self.root, sealed_at=STAMP)

    def test_protocol_cannot_prebind_generated_primary_results(self) -> None:
        path = self.root / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json"
        protocol = json.loads(path.read_text(encoding="utf-8"))
        protocol["primary_execution_asset_contract"][
            "generated_primary_results_bound_preprimary"
        ] = True
        self._write_json("holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json", protocol)
        with self.assertRaisesRegex(SealError, "exclude generated primary results"):
            build_payload(self.root, sealed_at=STAMP)

    def test_protocol_cannot_smuggle_generated_result_path(self) -> None:
        path = self.root / "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json"
        protocol = json.loads(path.read_text(encoding="utf-8"))
        protocol["primary_execution_asset_contract"][
            "generated_structural_result_path"
        ] = "holdout/evidence/structural_gate_results.json"
        self._write_json("holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json", protocol)
        with self.assertRaisesRegex(SealError, "primary execution asset contract keys mismatch"):
            build_payload(self.root, sealed_at=STAMP)

    def test_structural_gate_schema_identity_is_semantically_validated(self) -> None:
        path = self.root / "holdout/tools/structural_gate_results.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        schema["$id"] = "ncf.structural-gate-results.substituted"
        self._write_json("holdout/tools/structural_gate_results.schema.json", schema)
        with self.assertRaisesRegex(SealError, "structural gate results schema id mismatch"):
            build_payload(self.root, sealed_at=STAMP)

    def test_case_selection_outside_read_surface_is_never_opened(self) -> None:
        forbidden = self.root / "holdout/CASE_SELECTION.md"
        forbidden.write_text("sentinel narrative that must remain unread", encoding="utf-8")
        original_open = Path.open

        def guarded_open(path: Path, *args, **kwargs):
            if path.resolve(strict=False) == forbidden.resolve(strict=False):
                raise AssertionError("builder attempted to open case selection")
            return original_open(path, *args, **kwargs)

        with mock.patch.object(Path, "open", guarded_open):
            payload = build_payload(self.root, sealed_at=STAMP)
        self.assertEqual(payload["case_blindness"]["case_content_read_by_builder"], False)

    def test_exclusion_file_rejects_narrative_fields(self) -> None:
        self._write_json(
            "holdout/PRIMARY_HOLDOUT_EXCLUSIONS.json",
            {
                "schema_version": "NCF-PRIMARY-HOLDOUT-EXCLUSIONS-1.0.0",
                "exclusion_set_id": "fixture-v1",
                "excluded_case_ids": ["PMCID:EXCLUDED-1"],
                "case_narrative": "forbidden",
            },
        )
        with self.assertRaisesRegex(SealError, "identifier-only"):
            build_payload(self.root, sealed_at=STAMP)

    def test_tampered_payload_digest_fails(self) -> None:
        output = write_seal(self.root, sealed_at=STAMP)
        value = json.loads(output.read_text())
        value["status"] = "MUTATED"
        output.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(SealError):
            verify_seal(self.root)

    def test_payload_digest_is_stable(self) -> None:
        first = build_payload(self.root, sealed_at=STAMP)
        second = build_payload(self.root, sealed_at=STAMP)
        self.assertEqual(first["payload_sha256"], second["payload_sha256"])
        unsigned = dict(first)
        digest = unsigned.pop("payload_sha256")
        self.assertEqual(digest, hashlib.sha256(_canonical_bytes(unsigned)).hexdigest())

    def test_refuses_overwrite(self) -> None:
        write_seal(self.root, sealed_at=STAMP)
        with self.assertRaisesRegex(SealError, "refusing to overwrite"):
            write_seal(self.root, sealed_at=STAMP)


if __name__ == "__main__":
    unittest.main()
