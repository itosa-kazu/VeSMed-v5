"""Audit which holdout cases are concretely executable from fixture bytes.

This audit deliberately does not import either candidate.  It distinguishes a
concrete portable input from a prose mutation descriptor so the latter cannot
silently be reported as an executed hidden test.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS = ROOT / "tests" / "bridge_holdout" / "hidden_corpus.json"


def audit(corpus: Mapping[str, Any]) -> dict[str, Any]:
    queries = corpus["base"]["authority_projection"]["queries"]
    available_queries = sorted(queries)
    referenced_queries = {
        case["case_id"]: list(case.get("queries", ()))
        for case in corpus["cases"]
        if case.get("queries")
    }
    dangling_queries = {
        case_id: sorted(set(names) - set(available_queries))
        for case_id, names in referenced_queries.items()
        if set(names) - set(available_queries)
    }
    concrete_base_cases = [
        case["case_id"]
        for case in corpus["cases"]
        if case.get("fixture") and case["case_id"] not in dangling_queries
    ]
    descriptor_only_cases = [
        case["case_id"]
        for case in corpus["cases"]
        if "mutation" in case and not any(
            key in case
            for key in ("fixture_object", "fixture_patch", "control_fixture", "mutant_fixture")
        )
    ]
    return {
        "audit_schema": "bridge-holdout-corpus-executability-audit-v1",
        "corpus_protocol": corpus["protocol_version"],
        "available_queries": available_queries,
        "referenced_queries": referenced_queries,
        "dangling_queries": dangling_queries,
        "concrete_base_cases": concrete_base_cases,
        "descriptor_only_cases": descriptor_only_cases,
        "counts": {
            "all_cases": len(corpus["cases"]),
            "concrete_base_cases": len(concrete_base_cases),
            "dangling_query_cases": len(dangling_queries),
            "descriptor_only_cases": len(descriptor_only_cases),
        },
        "classification_rule": {
            "descriptor_without_concrete_input": "HARNESS_INCOMPLETE",
            "postseal_runner_constructed_input": "POST_SEAL_EXTERNAL_PROBE",
            "candidate_schema_has_no_lossless_permitted_projection": "ADAPTER_UNREPRESENTABLE",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    print(json.dumps(audit(corpus), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
