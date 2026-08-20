from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from validate_primary_search_snapshot import (
    SearchValidationError,
    canonical_request_url,
    validate_search_snapshot,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class RawSearchSnapshotValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.raw_root = self.root / "holdout/evidence/primary_search_raw"
        self.payload_root = self.raw_root / "payloads"
        self.payload_root.mkdir(parents=True)
        self.queries = [
            {"query_id": "Q1", "query": "query one", "sort": "pub date", "retmax": 100},
            {"query_id": "Q2", "query": "query two", "sort": "pub date", "retmax": 100},
        ]
        self.protocol = {"selection": {"queries": self.queries}}
        self.snapshot = {
            "schema_version": "NCF-PRIMARY-SEARCH-SNAPSHOT-1.0.0",
            "retrieved_at": "2026-07-21T00:00:00Z",
            "query_runs": [],
            "canonical_case_ids": ["PMID:1", "PMID:2", "PMID:3"],
        }
        for query, ids in zip(self.queries, [["1", "2"], ["3"]]):
            payload = self.payload_root / f"{query['query_id']}.response.json"
            payload.write_bytes(
                json.dumps(
                    {
                        "esearchresult": {
                            "count": str(len(ids)),
                            "retmax": str(len(ids)),
                            "retstart": "0",
                            "idlist": ids,
                        }
                    },
                    separators=(",", ":"),
                ).encode()
            )
            capture_path = self.raw_root / f"{query['query_id']}.capture.json"
            capture = {
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
                    "path": payload.relative_to(self.root).as_posix(),
                    "sha256": sha(payload),
                    "bytes": payload.stat().st_size,
                },
                "retrieved_count": len(ids),
            }
            capture_path.write_text(json.dumps(capture), encoding="utf-8")
            self.snapshot["query_runs"].append(
                {
                    **query,
                    "ordered_case_ids": [f"PMID:{item}" for item in ids],
                    "raw_response_ref": {
                        "path": capture_path.relative_to(self.root).as_posix(),
                        "sha256": sha(capture_path),
                    },
                }
            )

    def tearDown(self):
        self.tmp.cleanup()

    def validate(self):
        return validate_search_snapshot(
            study_root=self.root, protocol=self.protocol, snapshot=self.snapshot
        )

    def _capture(self, query_id="Q1"):
        path = self.raw_root / f"{query_id}.capture.json"
        return path, json.loads(path.read_text())

    def _rewrite_capture(self, path: Path, value: dict, index=0):
        path.write_text(json.dumps(value), encoding="utf-8")
        self.snapshot["query_runs"][index]["raw_response_ref"]["sha256"] = sha(path)

    def test_exact_content_addressed_projection_passes(self):
        result = self.validate()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["retrieved_count_by_query"], {"Q1": 2, "Q2": 1})

    def test_omitted_identifier_fails(self):
        self.snapshot["query_runs"][0]["ordered_case_ids"].pop()
        with self.assertRaisesRegex(SearchValidationError, "differ from exact raw response"):
            self.validate()

    def test_substituted_identifier_fails(self):
        self.snapshot["query_runs"][0]["ordered_case_ids"][0] = "PMID:999"
        with self.assertRaisesRegex(SearchValidationError, "differ from exact raw response"):
            self.validate()

    def test_wrong_capture_hash_fails(self):
        self.snapshot["query_runs"][0]["raw_response_ref"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(SearchValidationError, "raw capture sha256 mismatch"):
            self.validate()

    def test_post_hash_payload_mutation_fails(self):
        payload = self.payload_root / "Q1.response.json"
        payload.write_bytes(payload.read_bytes() + b"\n")
        with self.assertRaisesRegex(SearchValidationError, "exact raw payload sha256 mismatch"):
            self.validate()

    def test_frozen_query_mismatch_fails(self):
        path, value = self._capture()
        value["request"]["query"] = "tailored query"
        self._rewrite_capture(path, value)
        with self.assertRaisesRegex(SearchValidationError, "differs from frozen query"):
            self.validate()

    def test_missing_request_url_fails(self):
        path, value = self._capture()
        value["request"].pop("request_url")
        self._rewrite_capture(path, value)
        with self.assertRaisesRegex(SearchValidationError, "request shape mismatch"):
            self.validate()

    def test_tampered_request_url_fails(self):
        path, value = self._capture()
        value["request"]["request_url"] += "&unused=1"
        self._rewrite_capture(path, value)
        with self.assertRaisesRegex(SearchValidationError, "canonical URL differs"):
            self.validate()

    def test_equivalent_noncanonical_url_encoding_fails(self):
        path, value = self._capture()
        value["request"]["request_url"] = value["request"]["request_url"].replace("%20", "+")
        self._rewrite_capture(path, value)
        with self.assertRaisesRegex(SearchValidationError, "canonical URL differs"):
            self.validate()

    def test_retrieved_count_mismatch_fails(self):
        path, value = self._capture()
        value["retrieved_count"] = 1
        self._rewrite_capture(path, value)
        with self.assertRaisesRegex(SearchValidationError, "retrieved_count"):
            self.validate()

    def test_incomplete_raw_page_fails(self):
        capture_path, capture = self._capture()
        payload = self.payload_root / "Q1.response.json"
        value = json.loads(payload.read_text())
        value["esearchresult"]["count"] = "3"
        payload.write_text(json.dumps(value), encoding="utf-8")
        capture["raw_payload_ref"]["sha256"] = sha(payload)
        capture["raw_payload_ref"]["bytes"] = payload.stat().st_size
        self._rewrite_capture(capture_path, capture)
        with self.assertRaisesRegex(SearchValidationError, "incomplete raw result page"):
            self.validate()

    def test_noncanonical_or_outside_capture_path_fails(self):
        outside = self.root / "other.json"
        outside.write_text("{}", encoding="utf-8")
        self.snapshot["query_runs"][0]["raw_response_ref"] = {
            "path": "other.json",
            "sha256": sha(outside),
        }
        with self.assertRaisesRegex(SearchValidationError, "raw capture path must be"):
            self.validate()

    def test_symlink_capture_fails(self):
        link = self.raw_root / "Q1.capture.json"
        target = self.raw_root / "Q1.capture.target.json"
        link.replace(target)
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlink creation unavailable")
        self.snapshot["query_runs"][0]["raw_response_ref"] = {
            "path": link.relative_to(self.root).as_posix(),
            "sha256": sha(target),
        }
        with self.assertRaisesRegex(SearchValidationError, "missing or symlink"):
            self.validate()


if __name__ == "__main__":
    unittest.main()
