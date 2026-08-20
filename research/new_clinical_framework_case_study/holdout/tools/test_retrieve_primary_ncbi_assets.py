from __future__ import annotations

import hashlib
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parent
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import retrieve_primary_ncbi_assets as retriever
from compile_primary_search_snapshot import compile_snapshot


def canonical(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode()


class FakeGetterFactory:
    def __init__(self, payloads):
        self.payloads = payloads
        self.allowed = None
        self.calls = []

    def __call__(self, allowed):
        self.allowed = tuple(allowed)

        def get(url):
            self.calls.append(url)
            if url not in self.allowed:
                raise AssertionError("test getter received non-allowlisted URL")
            return self.payloads[url]

        return get


class FakeResponse:
    status = 200

    def __init__(self, url, body=b"<xml/>"):
        self.url = url
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def geturl(self):
        return self.url

    def read(self, limit):
        return self.body


class FakeOpener:
    def __init__(self, url):
        self.url = url
        self.request = None

    def open(self, request, timeout):
        self.request = request
        return FakeResponse(self.url)


class NcbiRetrieverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.holdout = self.root / "holdout"
        (self.holdout / "tools").mkdir(parents=True)
        (self.holdout / "schemas").mkdir(parents=True)
        (self.holdout / "evidence").mkdir(parents=True)
        source_root = Path(retriever.__file__).parent.parent
        copies = {
            retriever.REL_TOOL: Path(retriever.__file__).read_bytes(),
            retriever.REL_TOOL_TEST: b"frozen mocked HTTP tests\n",
            retriever.REL_SOURCE_REQUEST_SCHEMA: (
                source_root / "schemas/primary_source_identifier_request.schema.json"
            ).read_bytes(),
            retriever.REL_SOURCE_MANIFEST_SCHEMA: (
                source_root / "schemas/primary_source_retrieval_manifest.schema.json"
            ).read_bytes(),
            retriever.REL_SEARCH_MANIFEST_SCHEMA: (
                source_root / "schemas/primary_search_retrieval_manifest.schema.json"
            ).read_bytes(),
        }
        for rel, raw in copies.items():
            path = self.root.joinpath(*rel.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        self.queries = [
            {"query_id": "Q1", "query": "query one", "sort": "pub date", "retmax": 100},
            {"query_id": "Q2", "query": "query two", "sort": "pub date", "retmax": 100},
        ]
        self.protocol = {
            "status": "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION",
            "selection": {
                "queries": self.queries,
                "raw_search_validation": {
                    "retriever": retriever.REL_TOOL.as_posix(),
                    "retriever_test_source": retriever.REL_TOOL_TEST.as_posix(),
                    "retriever_network_policy": "HTTPS_GET_EXACT_URL_ONLY_NO_REDIRECT_NO_PROXY",
                },
                "source_capture": {
                    "retriever": retriever.REL_TOOL.as_posix(),
                    "retriever_test_source": retriever.REL_TOOL_TEST.as_posix(),
                    "identifier_request_schema": retriever.REL_SOURCE_REQUEST_SCHEMA.as_posix(),
                    "retrieval_manifest_schema": retriever.REL_SOURCE_MANIFEST_SCHEMA.as_posix(),
                    "network_policy": "HTTPS_GET_EXACT_URL_ONLY_NO_REDIRECT_NO_PROXY",
                    "eligibility_logic": "FORBIDDEN",
                },
            },
        }
        protocol_path = self.root.joinpath(*retriever.REL_PROTOCOL.parts)
        protocol_path.write_bytes(canonical(self.protocol))
        primary = {"protocol_json": self.ref(retriever.REL_PROTOCOL)}
        for key, rel in (
            ("ncbi_retriever", retriever.REL_TOOL),
            ("ncbi_retriever_test", retriever.REL_TOOL_TEST),
            ("source_identifier_request_schema", retriever.REL_SOURCE_REQUEST_SCHEMA),
            ("source_retrieval_manifest_schema", retriever.REL_SOURCE_MANIFEST_SCHEMA),
            ("raw_search_retrieval_schema", retriever.REL_SEARCH_MANIFEST_SCHEMA),
        ):
            primary[key] = self.ref(rel)
        seal = {
            "status": "SEALED_BEFORE_PRIMARY_CASE_SELECTION",
            "sealed_at": "2026-07-20T00:00:00Z",
            "bindings": {"primary_execution": primary},
        }
        seal["payload_sha256"] = hashlib.sha256(canonical(seal)).hexdigest()
        self.root.joinpath(*retriever.REL_COMBINED_SEAL.parts).write_bytes(canonical(seal))

    def tearDown(self):
        self.tmp.cleanup()

    def ref(self, rel):
        path = self.root.joinpath(*rel.parts)
        raw = path.read_bytes()
        return {"path": rel.as_posix(), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}

    def search_factory(self, *, incomplete=False):
        payloads = {}
        for index, query in enumerate(self.queries, 1):
            url = retriever.canonical_request_url(query)
            ids = [str(index), str(index + 10)]
            retmax = len(ids) - 1 if incomplete and index == 1 else len(ids)
            payloads[url] = json.dumps(
                {
                    "esearchresult": {
                        "count": str(len(ids)),
                        "retmax": str(retmax),
                        "retstart": "0",
                        "idlist": ids,
                    }
                },
                separators=(",", ":"),
            ).encode()
        return FakeGetterFactory(payloads)

    def test_search_exact_q1_q2_bytes_and_write_once_manifest(self):
        factory = self.search_factory()
        result = retriever.retrieve_search(
            study_root=self.root,
            getter_factory=factory,
            now=lambda: "2026-07-21T00:00:00Z",
        )
        self.assertEqual(result["status"], "CAPTURED")
        self.assertEqual(factory.allowed, tuple(retriever.canonical_request_url(q) for q in self.queries))
        self.assertEqual(factory.calls, list(factory.allowed))
        manifest = json.loads(self.root.joinpath(*retriever.REL_SEARCH_MANIFEST.parts).read_bytes())
        self.assertEqual([r["query_id"] for r in manifest["query_runs"]], ["Q1", "Q2"])
        for row in manifest["query_runs"]:
            path = self.root / row["raw_payload_ref"]["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), row["raw_payload_ref"]["sha256"])
        compiled = compile_snapshot(
            study_root=self.root,
            protocol=self.protocol,
            retrieval_manifest=manifest,
            snapshot_output=self.root / "holdout/evidence/PRIMARY_CASE_SEARCH_SNAPSHOT.json",
        )
        self.assertEqual(compiled["status"], "COMPILED")
        with self.assertRaisesRegex(retriever.RetrievalError, "write-once"):
            retriever.retrieve_search(study_root=self.root, getter_factory=factory)

    def test_incomplete_esearch_page_fails_before_any_write(self):
        with self.assertRaisesRegex(retriever.RetrievalError, "incomplete"):
            retriever.retrieve_search(study_root=self.root, getter_factory=self.search_factory(incomplete=True))
        self.assertFalse(self.root.joinpath(*retriever.REL_SEARCH_MANIFEST.parts).exists())
        self.assertFalse(self.root.joinpath(*retriever.REL_SEARCH_PAYLOAD_ROOT.parts).exists())

    def test_missing_or_tampered_preseal_fails_before_network(self):
        seal = self.root.joinpath(*retriever.REL_COMBINED_SEAL.parts)
        value = json.loads(seal.read_bytes())
        value["status"] = "TAMPERED"
        seal.write_bytes(canonical(value))
        factory = self.search_factory()
        with self.assertRaisesRegex(retriever.RetrievalError, "status|payload_sha256 mismatch"):
            retriever.retrieve_search(study_root=self.root, getter_factory=factory)
        self.assertEqual(factory.calls, [])

    def test_clock_before_seal_fails_before_network(self):
        factory = self.search_factory()
        with self.assertRaisesRegex(retriever.RetrievalError, "precedes"):
            retriever.retrieve_search(
                study_root=self.root,
                getter_factory=factory,
                now=lambda: "2026-07-19T23:59:59Z",
            )
        self.assertEqual(factory.calls, [])

    def write_request(self, purpose, identifiers, extra=None):
        rel = (
            retriever.REL_SCREENING_REQUEST
            if purpose == "SCREENING"
            else retriever.REL_SELECTED_REQUEST
        )
        value = {"schema_version": retriever.SOURCE_REQUEST_VERSION, "purpose": purpose, "identifiers": identifiers}
        if extra:
            value.update(extra)
        self.root.joinpath(*rel.parts).write_bytes(canonical(value))
        return rel

    def test_source_capture_identity_and_fulltext_exact_bytes_no_eligibility(self):
        request = self.write_request("SCREENING", [{"pmid": "123", "pmcid": "PMC456"}])
        identity_url = retriever.canonical_pubmed_identity_url("123")
        fulltext_url = retriever.canonical_pmc_fulltext_url("PMC456")
        factory = FakeGetterFactory({identity_url: b"<PubmedArticleSet>identity</PubmedArticleSet>", fulltext_url: b"<article>full text</article>"})
        result = retriever.retrieve_sources(
            study_root=self.root,
            purpose="SCREENING",
            request_rel=request,
            getter_factory=factory,
            now=lambda: "2026-07-21T00:00:00Z",
        )
        self.assertFalse(result["eligibility_assessed"])
        manifest = json.loads(self.root.joinpath(*retriever.REL_SCREENING_SOURCE_MANIFEST.parts).read_bytes())
        self.assertFalse(manifest["eligibility_assessed"])
        self.assertEqual(factory.calls, [identity_url, fulltext_url])
        for key in ("identity_payload_ref", "fulltext_payload_ref"):
            ref = manifest["entries"][0][key]
            path = self.root / ref["path"]
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), ref["sha256"])

    def test_identity_only_request_does_not_invent_pmcid_or_fulltext(self):
        request = self.write_request("SELECTED", [{"pmid": "789"}])
        url = retriever.canonical_pubmed_identity_url("789")
        retriever.retrieve_sources(
            study_root=self.root,
            purpose="SELECTED",
            request_rel=request,
            getter_factory=FakeGetterFactory({url: b"<PubmedArticleSet/>"}),
        )
        manifest = json.loads(self.root.joinpath(*retriever.REL_SELECTED_SOURCE_MANIFEST.parts).read_bytes())
        row = manifest["entries"][0]
        self.assertIsNone(row["pmcid"])
        self.assertIsNone(row["fulltext_request_url"])
        self.assertIsNone(row["fulltext_payload_ref"])

    def test_clinical_or_eligibility_field_in_identifier_request_fails_before_network(self):
        request = self.write_request(
            "SCREENING",
            [{"pmid": "123", "pmcid": None}],
            {"eligible": True},
        )
        factory = FakeGetterFactory({})
        with self.assertRaisesRegex(retriever.RetrievalError, "non-identifier"):
            retriever.retrieve_sources(
                study_root=self.root,
                purpose="SCREENING",
                request_rel=request,
                getter_factory=factory,
            )
        self.assertEqual(factory.calls, [])

    def test_source_capture_refuses_overwrite(self):
        request = self.write_request("SELECTED", [{"pmid": "789"}])
        url = retriever.canonical_pubmed_identity_url("789")
        factory = FakeGetterFactory({url: b"<PubmedArticleSet/>"})
        retriever.retrieve_sources(
            study_root=self.root, purpose="SELECTED", request_rel=request, getter_factory=factory
        )
        with self.assertRaisesRegex(retriever.RetrievalError, "write-once"):
            retriever.retrieve_sources(
                study_root=self.root, purpose="SELECTED", request_rel=request, getter_factory=factory
            )

    def test_exact_url_domain_query_and_identifier_guards(self):
        good = retriever.canonical_pubmed_identity_url("123")
        retriever._validate_exact_url(good, [good])
        for bad in (
            good.replace("eutils.ncbi.nlm.nih.gov", "example.com"),
            good + "&extra=1",
            good.replace("https://", "http://"),
        ):
            with self.assertRaises(retriever.RetrievalError):
                retriever._validate_exact_url(bad, [good])
        for invalid in ("0", "01", "1 OR 1", "PMC1"):
            with self.assertRaises(retriever.RetrievalError):
                retriever.canonical_pubmed_identity_url(invalid)

    def test_transport_uses_get_and_rejects_redirect_and_wrong_socket_domain(self):
        url = retriever.canonical_pubmed_identity_url("123")
        fake = FakeOpener(url)
        getter = retriever.NcbiHttpsGetter([url])
        with patch.object(retriever, "build_opener", return_value=fake):
            self.assertEqual(getter(url), b"<xml/>")
        self.assertEqual(fake.request.get_method(), "GET")
        with self.assertRaises(retriever.RetrievalError):
            retriever._NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://example.com")
        with getter._socket_guard():
            with self.assertRaisesRegex(retriever.RetrievalError, "socket destination forbidden"):
                socket.create_connection(("example.com", 443), timeout=0.01)

    def test_schema_documents_validate_representative_outputs(self):
        request_schema = json.loads(self.root.joinpath(*retriever.REL_SOURCE_REQUEST_SCHEMA.parts).read_bytes())
        manifest_schema = json.loads(self.root.joinpath(*retriever.REL_SOURCE_MANIFEST_SCHEMA.parts).read_bytes())
        request = {"schema_version": retriever.SOURCE_REQUEST_VERSION, "purpose": "SCREENING", "identifiers": [{"pmid": "1", "pmcid": "PMC2"}]}
        self.assertEqual(request_schema["$id"], "ncf.primary-source-identifier-request.v1")
        self.assertEqual(set(request), set(request_schema["required"]))
        ref = {"path": "holdout/evidence/a", "sha256": "0" * 64, "bytes": 1}
        manifest = {
            "schema_version": retriever.SOURCE_MANIFEST_VERSION,
            "purpose": "SCREENING",
            "retrieved_at": "2026-07-21T00:00:00Z",
            "combined_preprimary_payload_sha256": "1" * 64,
            "identifier_request_ref": ref,
            "entries": [{
                "pmid": "1", "pmcid": "PMC2",
                "identity_request_url": retriever.canonical_pubmed_identity_url("1"),
                "identity_payload_ref": ref,
                "fulltext_request_url": retriever.canonical_pmc_fulltext_url("PMC2"),
                "fulltext_payload_ref": ref,
            }],
            "eligibility_assessed": False,
        }
        self.assertEqual(manifest_schema["$id"], "ncf.primary-source-retrieval-manifest.v1")
        self.assertEqual(set(manifest), set(manifest_schema["required"]))


if __name__ == "__main__":
    unittest.main()
