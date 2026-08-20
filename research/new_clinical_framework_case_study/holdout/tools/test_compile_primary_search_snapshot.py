from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from compile_primary_search_snapshot import SearchCompileError, compile_snapshot
from validate_primary_search_snapshot import canonical_request_url, validate_search_snapshot


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PrimarySearchCompilerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.payload_root = self.root / "holdout/evidence/primary_search_raw/payloads"
        self.payload_root.mkdir(parents=True)
        self.queries = [
            {"query_id": "Q1", "query": "query one", "sort": "pub date", "retmax": 100},
            {"query_id": "Q2", "query": "query two", "sort": "pub date", "retmax": 100},
        ]
        self.protocol = {"selection": {"queries": self.queries}}
        self.manifest = {
            "schema_version": "NCF-PRIMARY-SEARCH-RETRIEVAL-MANIFEST-1.0.0",
            "retrieved_at": "2026-07-21T00:00:00Z",
            "query_runs": [],
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
            self.manifest["query_runs"].append(
                {
                    "query_id": query["query_id"],
                    "request_url": canonical_request_url(query),
                    "raw_payload_ref": {
                        "path": payload.relative_to(self.root).as_posix(),
                        "sha256": sha(payload),
                        "bytes": payload.stat().st_size,
                    },
                }
            )
        self.output = self.root / "holdout/evidence/PRIMARY_CASE_SEARCH_SNAPSHOT.json"

    def tearDown(self):
        self.tmp.cleanup()

    def compile(self):
        return compile_snapshot(
            study_root=self.root,
            protocol=self.protocol,
            retrieval_manifest=self.manifest,
            snapshot_output=self.output,
        )

    def test_compiles_exact_bytes_to_valid_snapshot(self):
        result = self.compile()
        self.assertEqual(result["status"], "COMPILED")
        self.assertEqual(result["retrieved_count_by_query"], {"Q1": 2, "Q2": 1})
        snapshot = json.loads(self.output.read_text())
        self.assertEqual(
            validate_search_snapshot(
                study_root=self.root, protocol=self.protocol, snapshot=snapshot
            )["status"],
            "PASS",
        )

    def test_wrong_url_fails_without_output(self):
        self.manifest["query_runs"][0]["request_url"] += "&unused=1"
        with self.assertRaisesRegex(SearchCompileError, "request_url differs"):
            self.compile()
        self.assertFalse(self.output.exists())

    def test_equivalent_but_noncanonical_url_encoding_fails(self):
        self.manifest["query_runs"][0]["request_url"] = self.manifest["query_runs"][0][
            "request_url"
        ].replace("%20", "+")
        with self.assertRaisesRegex(SearchCompileError, "request_url differs"):
            self.compile()

    def test_payload_hash_mismatch_fails_without_output(self):
        self.manifest["query_runs"][0]["raw_payload_ref"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(SearchCompileError, "sha256 mismatch"):
            self.compile()
        self.assertFalse(self.output.exists())

    def test_refuses_overwrite(self):
        self.compile()
        with self.assertRaisesRegex(SearchCompileError, "overwrite"):
            self.compile()


if __name__ == "__main__":
    unittest.main()
