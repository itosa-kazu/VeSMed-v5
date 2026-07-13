#!/usr/bin/env python3
"""External, implementation-B-only runner for the sealed bridge holdout.

This file is deliberately outside ``prototype/bridge_holdout``.  It imports
the sealed implementation by path and SHA-256, lowers the portable authority
to B's public API without using candidate parsing/canonicalisation helpers,
and lifts B's *executable native fields* with an independently implemented
closed decoder.  ``recover_bundle`` is recorded as a diagnostic only: recovery
tape equality is never accepted as round-trip evidence.

Only the base objects are concretely materialized by the corpus; most mutation
entries are prose descriptors.  Descriptor-only cases remain
``HARNESS_INCOMPLETE``.  Separately constructed checks are labelled
``post_seal_external_probe`` and are never promoted to hidden-case evidence.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from hashlib import sha256
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Callable, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[2]
CORPUS_PATH = ROOT / "tests" / "bridge_holdout" / "hidden_corpus.json"
FREEZE_PATH = ROOT / "results" / "bridge-holdout" / "freeze-manifest.json"
IMPL_PATH = ROOT / "prototype" / "bridge_holdout" / "impl_b.py"
EXPECTED_IMPL_SHA256 = "dea8ad3d88fc1f626fe7121357da2278ae8095aff37847502a97e114db6d1cb0"
EXPECTED_CORPUS_SHA256 = "9ed638f0f6d5b5db688f40581b4bb659bb1b6df29e377048fa628b970944f309"
TOL = 1e-12
FORBIDDEN_CANDIDATE_INPUT_KEYS = {
    "hidden_oracle",
    "oracle",
    "case_id",
    "expected",
    "authority_projection",
    "report_contract",
}
MIN_FILTER_SMOOTH_SEPARATION = 0.04  # public preregistration margin


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def canonical_equal(left: Any, right: Any) -> bool:
    return canonical_bytes(left) == canonical_bytes(right)


def assert_no_oracle_leak(value: Any, path: str = "$") -> None:
    """Fail before a candidate call if a runner-only key leaked inward."""

    if type(value) is dict:
        forbidden = sorted(set(value) & FORBIDDEN_CANDIDATE_INPUT_KEYS)
        if forbidden:
            raise AssertionError(f"runner-only candidate input key(s) at {path}: {forbidden}")
        for key, child in value.items():
            assert_no_oracle_leak(child, f"{path}.{key}")
    elif type(value) in {list, tuple}:
        for index, child in enumerate(value):
            assert_no_oracle_leak(child, f"{path}[{index}]")


def load_candidate():
    observed = file_sha256(IMPL_PATH)
    if observed != EXPECTED_IMPL_SHA256:
        raise RuntimeError(f"sealed implementation B hash mismatch: {observed}")
    spec = importlib.util.spec_from_file_location("sealed_bridge_impl_b", IMPL_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load sealed implementation B")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Independent decoder/encoder for B's documented immutable native sidecars.
# No candidate _freeze/_thaw helper is imported or called.
FROZEN_TAGS = {"null", "bool", "int", "float", "str", "list", "tuple", "dict"}


def decode_b_frozen(node: tuple[Any, ...]) -> Any:
    if type(node) is not tuple or not node or node[0] not in FROZEN_TAGS:
        raise ValueError("closed B frozen node expected")
    tag = node[0]
    if tag == "null":
        if len(node) != 1:
            raise ValueError("malformed null node")
        return None
    if tag == "bool":
        if len(node) != 2 or node[1] not in (0, 1):
            raise ValueError("malformed bool node")
        return bool(node[1])
    if tag == "int":
        if len(node) != 2 or type(node[1]) is not str:
            raise ValueError("malformed int node")
        return int(node[1])
    if tag == "float":
        if len(node) != 2 or type(node[1]) is not str:
            raise ValueError("malformed float node")
        value = float.fromhex(node[1])
        if not math.isfinite(value):
            raise ValueError("non-finite float node")
        return value
    if tag == "str":
        if len(node) != 2 or type(node[1]) is not str:
            raise ValueError("malformed str node")
        return node[1]
    if tag == "list":
        return [decode_b_frozen(child) for child in node[1:]]
    if tag == "tuple":
        return tuple(decode_b_frozen(child) for child in node[1:])
    out: dict[str, Any] = {}
    for pair in node[1:]:
        if type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str or pair[0] in out:
            raise ValueError("malformed or duplicate B frozen dict pair")
        out[pair[0]] = decode_b_frozen(pair[1])
    return out


def encode_b_frozen(value: Any) -> tuple[Any, ...]:
    """Independent encoder used solely for destructive integrity probes."""

    if value is None:
        return ("null",)
    if type(value) is bool:
        return ("bool", int(value))
    if type(value) is int:
        return ("int", str(value))
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError("non-finite value")
        return ("float", value.hex())
    if type(value) is str:
        return ("str", value)
    if type(value) is list:
        return ("list", *(encode_b_frozen(item) for item in value))
    if type(value) is tuple:
        return ("tuple", *(encode_b_frozen(item) for item in value))
    if type(value) is dict:
        return ("dict", *((key, encode_b_frozen(child)) for key, child in value.items()))
    raise ValueError(f"not JSON-like: {type(value).__name__}")


def ratio(pair: Sequence[int]) -> float:
    return float(Fraction(int(pair[0]), int(pair[1])))


def plus_microsecond(value: str) -> str:
    parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    return (parsed + timedelta(microseconds=1)).astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def root_index(base: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["root_occurrence_id"]: row for row in base["roots"]}


def relevant_roots(base: Mapping[str, Any], family: str) -> list[dict[str, Any]]:
    refs: set[str]
    authority = base["authority_projection"]
    if family == "dbn":
        refs = {row["root_ref"]["occurrence_id"] for row in authority["dbn_observations"]}
    elif family == "scm":
        refs = {row["root_ref"]["occurrence_id"] for row in authority["scm_factual_observations"]}
    else:
        raise ValueError(f"unknown family {family}")
    return [copy.deepcopy(row) for row in base["roots"] if row["root_occurrence_id"] in refs]


def project_roots(base: Mapping[str, Any], family: str) -> list[dict[str, Any]]:
    rows = []
    for portable in relevant_roots(base, family):
        # Explicit, invertible field rename required by B's public boundary.
        rows.append({"root_id": portable["root_occurrence_id"], **portable})
    return rows


def common_projection(base: Mapping[str, Any], family: str) -> dict[str, Any]:
    cut = copy.deepcopy(base["cut"])
    versions = copy.deepcopy(cut["version_vector"])
    model_version = versions["model_by_kernel"]["finite_dbn" if family == "dbn" else "finite_scm"]
    versions["model"] = model_version
    uncertainty = (
        copy.deepcopy(base["dbn"]["uncertainty_contract"])
        if family == "dbn"
        else {
            "aleatoric": "finite_world_probability",
            "epistemic": "finite_world_table_fixed",
            "measurement": "exact_factual_constraint",
            "identification": base["scm"]["identification_contract"],
            "shared_world_policy": base["scm"]["shared_world_policy"],
        }
    )
    return {
        "schema_version": "vesmed.evidence-model-bridge/1",
        "bundle_id": f"portable-holdout-b-{family}",
        "bridge": {
            "bridge_id": "portable-authority-to-implementation-b",
            "version": cut["version_vector"]["bridge"],
            "mapping_version": cut["version_vector"]["mapping"],
            "registered_at": "2037-04-11T00:00:00Z",
        },
        "temporal_cut": cut,
        "versions": versions,
        "uncertainty": uncertainty,
        "roots": project_roots(base, family),
        "projection_manifest": {
            "authority": "portable hidden corpus",
            "field_renames": {"root_occurrence_id": "root_id"},
            "family": family,
            "manual_likelihoods": 0,
            "query_semantics_in_candidate": True,
        },
    }


def dbn_projection(base: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, tuple[str, int]]]:
    canonical = common_projection(base, "dbn")
    dbn = base["dbn"]
    authority = base["authority_projection"]
    roots = root_index(base)
    states: list[str] = []
    inverse: dict[str, tuple[str, int]] = {}
    prior: list[float] = []
    for member in dbn["epistemic_members"]:
        weight = ratio(member["weight"])
        p1 = ratio(member["prior_x1"])
        for x in (0, 1):
            label = f"member={member['member_id']}|state={x}"
            states.append(label)
            inverse[label] = (member["member_id"], x)
            prior.append(weight * (p1 if x else 1.0 - p1))

    member_by_id = {row["member_id"]: row for row in dbn["epistemic_members"]}
    transition: list[list[float]] = []
    for source in states:
        member_id, old_x = inverse[source]
        p1 = ratio(member_by_id[member_id]["transition_no_action_p1"][str(old_x)])
        row = []
        for target in states:
            target_member, new_x = inverse[target]
            row.append(0.0 if target_member != member_id else (p1 if new_x else 1.0 - p1))
        transition.append(row)

    p_y1 = {int(x): ratio(pair) for x, pair in dbn["measurement"]["p_y1_given_x"].items()}
    evidence = []
    for observation in authority["dbn_observations"]:
        root_id = observation["root_ref"]["occurrence_id"]
        portable_root = roots[root_id]
        measured = observation["measurement"]
        if measured.get("kind") != "exact":
            value: Any = copy.deepcopy(measured)
            likelihood = None
        else:
            value = measured["value"]
            likelihood = [
                p_y1[inverse[state][1]] if value == 1 else 1.0 - p_y1[inverse[state][1]]
                for state in states
            ]
        record = {
            "record_id": observation["record_id"],
            "logical_id": portable_root["logical_id"],
            "record_version": observation["root_ref"]["version"],
            "slice": observation["slice"],
            "slice_index": observation["slice_index"],
            "available_at": observation["available_at"],
            "transaction_revision": observation["transaction_revision"],
            "variable": observation["concept"],
            "value": value,
            "portable_value": copy.deepcopy(portable_root["value"]),
            "root_ids": [root_id],
            "dependence_families": copy.deepcopy(portable_root["dependence_families"]),
            "scope": copy.deepcopy(portable_root["scope"]),
            "clock_roles": copy.deepcopy(portable_root["times"]),
            "raw_digest": portable_root["raw_digest"],
            "source_span": copy.deepcopy(portable_root["source_span"]),
            "mapping_version": portable_root["mapping_version"],
            "uncertainty": {
                "channel": "measurement",
                "kind": dbn["measurement"]["kind"],
                "method_id": dbn["measurement"]["method_id"],
                "method_version": dbn["measurement"]["method_version"],
            },
        }
        if likelihood is not None:
            record["likelihood"] = likelihood
        evidence.append(record)

    canonical["evidence"] = evidence
    canonical["model"] = {
        "kind": "finite_dbn",
        "model_id": dbn["model_id"],
        "model_version": dbn["model_version"],
        "schema_version": dbn["schema_version"],
        "states": states,
        "state_inverse": {label: {"epistemic_member": member, "state": x} for label, (member, x) in inverse.items()},
        "timeline": copy.deepcopy(dbn["timeline"]),
        "prior": prior,
        "transition_blocks": [transition, transition],
        "observation_variable": dbn["observation_concept"],
        "target_variable": dbn["state_concept"],
    }
    canonical["projection_manifest"]["product_state_transform"] = "fixed_epistemic_member_x_binary_state"
    canonical["projection_manifest"]["manual_likelihoods"] = len(evidence)
    return canonical, inverse


def scm_projection(base: Mapping[str, Any]) -> dict[str, Any]:
    canonical = common_projection(base, "scm")
    scm = base["scm"]
    authority = base["authority_projection"]
    roots = root_index(base)
    treatment = scm["treatment_concept"]
    outcome = scm["outcome_concept"]
    evidence = []
    for observation in authority["scm_factual_observations"]:
        root_id = observation["root_ref"]["occurrence_id"]
        portable_root = roots[root_id]
        evidence.append(
            {
                "record_id": observation["record_id"],
                "logical_id": portable_root["logical_id"],
                "record_version": observation["root_ref"]["version"],
                "slice": 0,
                "available_at": portable_root["times"]["available_to_actor"],
                "transaction_revision": portable_root["times"]["kernel_committed"],
                "variable": observation["variable"],
                "value": observation["value"],
                "portable_value": copy.deepcopy(portable_root["value"]),
                "semantic_role": observation["semantic_role"],
                "root_ids": [root_id],
                "dependence_families": copy.deepcopy(portable_root["dependence_families"]),
                "scope": copy.deepcopy(portable_root["scope"]),
                "clock_roles": copy.deepcopy(portable_root["times"]),
                "raw_digest": portable_root["raw_digest"],
                "source_span": copy.deepcopy(portable_root["source_span"]),
                "mapping_version": portable_root["mapping_version"],
                "uncertainty": {"channel": "measurement", "kind": "exact_factual_constraint"},
            }
        )
    worlds = []
    for world in scm["worlds"]:
        observed_t = world["observed_t"]
        factual_y = world["y1"] if observed_t == 1 else world["y0"]
        worlds.append(
            {
                "world_id": world["world_id"],
                "probability": ratio(world["weight"]),
                "exogenous": {"portable_world_identity": world["world_id"]},
                "factual": {treatment: observed_t, outcome: factual_y},
                "responses": [
                    {"do_set": {treatment: 0}, "values": {treatment: 0, outcome: world["y0"]}},
                    {"do_set": {treatment: 1}, "values": {treatment: 1, outcome: world["y1"]}},
                ],
            }
        )
    canonical["evidence"] = evidence
    canonical["model"] = {
        "kind": "finite_scm",
        "model_id": scm["model_id"],
        "model_version": scm["model_version"],
        "schema_version": scm["schema_version"],
        "timeline": [0],
        "treatment_variable": treatment,
        "outcome_variable": outcome,
        "worlds": worlds,
    }
    canonical["projection_manifest"]["response_world_transform"] = "potential_outcome_row_to_do_response_rows"
    return canonical


def dbn_query(base: Mapping[str, Any], name: str) -> dict[str, Any]:
    query = copy.deepcopy(base["authority_projection"]["queries"][name])
    query["kind"] = query.pop("operator")
    return query


def scm_query(base: Mapping[str, Any], name: str) -> dict[str, Any]:
    query = copy.deepcopy(base["authority_projection"]["queries"][name])
    query["kind"] = query.pop("operator")
    if "factual" in query:
        query["factual_evidence"] = query.pop("factual")
    return query


def probability_one(result: Mapping[str, Any], *, inverse: Mapping[str, tuple[str, int]] | None = None) -> float:
    if inverse is None:
        return sum(float(row["probability"]) for row in result["distribution"] if row["value"] == 1)
    return sum(float(row["probability"]) for row in result["distribution"] if inverse[row["value"]][1] == 1)


def native_audit(native: Any) -> dict[str, Any]:
    ir = native.native_ir
    roots = []
    for row in native.roots:
        roots.append(
            {
                "root_id": row.root_id,
                "root_version": row.version,
                "logical_id": row.logical_id,
                "active": row.active,
                "metadata": decode_b_frozen(row.metadata),
            }
        )
    columns = []
    for row in ir.evidence_columns:
        columns.append(
            {
                "record_id": row.record_id,
                "logical_id": row.logical_id,
                "record_version": row.record_version,
                "active": row.active,
                "slice_index": row.slice_index,
                "slice_label": row.slice_label,
                "available_at": row.available_at,
                "transaction_revision": row.transaction_revision,
                "variable": row.variable,
                "value": row.value,
                "root_ids": list(row.root_ids),
                "uncertainty": decode_b_frozen(row.uncertainty),
                "raw_record": decode_b_frozen(row.raw_record),
            }
        )
    return {
        "target_kernel": native.target_kernel,
        "bundle_id": native.bundle_id,
        "bridge": decode_b_frozen(native.bridge_sidecar),
        "temporal_cut": decode_b_frozen(native.temporal_cut_sidecar),
        "versions": decode_b_frozen(native.versions_sidecar),
        "uncertainty": decode_b_frozen(native.uncertainty_sidecar),
        "roots": roots,
        "evidence": columns,
    }


def expected_native_audit(canonical: Mapping[str, Any], family: str) -> dict[str, Any]:
    roots = [
        {
            "root_id": row["root_id"],
            "root_version": row["root_version"],
            "logical_id": row["logical_id"],
            "active": bool(row.get("active", True)),
            "metadata": row,
        }
        for row in canonical["roots"]
    ]
    evidence = []
    timeline = canonical["model"]["timeline"]
    for record in canonical["evidence"]:
        evidence.append(
            {
                "record_id": record["record_id"],
                "logical_id": record["logical_id"],
                "record_version": record["record_version"],
                "active": bool(record.get("active", True)),
                "slice_index": timeline.index(record["slice"]),
                "slice_label": record["slice"],
                "available_at": record["available_at"],
                "transaction_revision": record["transaction_revision"],
                "variable": record["variable"],
                "value": record["value"],
                "root_ids": list(dict.fromkeys(record["root_ids"])),
                "uncertainty": record["uncertainty"],
                "raw_record": record,
            }
        )
    return {
        "target_kernel": "finite_dbn" if family == "dbn" else "finite_scm",
        "bundle_id": canonical["bundle_id"],
        "bridge": canonical["bridge"],
        "temporal_cut": canonical["temporal_cut"],
        "versions": canonical["versions"],
        "uncertainty": canonical["uncertainty"],
        "roots": roots,
        "evidence": evidence,
    }


def audit_projection(candidate: Any, canonical: dict[str, Any], family: str) -> tuple[Any, dict[str, Any]]:
    target = "finite_dbn" if family == "dbn" else "finite_scm"
    assert_no_oracle_leak(canonical)
    start = time.perf_counter_ns()
    native = candidate.compile_bundle(canonical, target)
    compile_ns = time.perf_counter_ns() - start
    observed = native_audit(native)
    expected = expected_native_audit(canonical, family)
    executable_equal = canonical_equal(observed, expected)
    start = time.perf_counter_ns()
    recovered = candidate.recover_bundle(native)
    recover_ns = time.perf_counter_ns() - start
    return native, {
        "native_capsule_audit_equal": executable_equal,
        "recovery_tape_equal_diagnostic_only": canonical_equal(recovered, canonical),
        "audit_coverage": {
            "included": ["roots", "evidence columns", "bridge", "cut", "versions", "uncertainty"],
            "not_yet_included": ["full executable model tables", "execute-time portable query inverse"],
            "classification_consequence": "HARNESS_INCOMPLETE",
        },
        "compile_ns": compile_ns,
        "recover_ns": recover_ns,
        "capsule_mismatch_count": 0 if executable_equal else 1,
        "portable_roundtrip_field_loss_count": None,
        "observed_audit_sha256": sha256(canonical_bytes(observed)).hexdigest(),
        "expected_audit_sha256": sha256(canonical_bytes(expected)).hexdigest(),
    }


def assertion(name: str, passed: bool, **evidence: Any) -> dict[str, Any]:
    return {"name": name, "passed": bool(passed), "evidence": evidence}


def typed_candidate_error(error: BaseException, allowed_fragments: Iterable[str]) -> tuple[bool, dict[str, Any]]:
    """Record exception diagnostics; exceptions never satisfy typed refusal.

    PREREGISTRATION.md explicitly says that an exception is not a pass.  B's
    public API exposes ``BridgeError`` exceptions rather than a structured
    failure outcome/code, so even a descriptive message remains candidate
    failure.  Fragment matching is retained as diagnostics only.
    """

    message = str(error)
    fragments = tuple(allowed_fragments)
    matched = [fragment for fragment in fragments if fragment.lower() in message.lower()]
    return False, {
        "error_type": type(error).__name__,
        "error_code": matched[0] if matched else None,
        "error": message,
        "typed_refusal": False,
        "exception_cannot_satisfy_negative_fixture": True,
    }


def case_result(case: Mapping[str, Any], assertions: Sequence[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "title": case["title"],
        "family": case["family"],
        "fixture": case.get("fixture"),
        "mutation": case.get("mutation"),
        "classification": "PASS" if assertions and all(row["passed"] for row in assertions) else "CANDIDATE_FAIL",
        "assertions": list(assertions),
        **extra,
    }


def unrepresentable(case: Mapping[str, Any], reason: str, **evidence: Any) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "title": case["title"],
        "family": case["family"],
        "fixture": case.get("fixture"),
        "mutation": case.get("mutation"),
        "classification": "ADAPTER_UNREPRESENTABLE",
        "assertions": [],
        "reason": reason,
        "evidence": evidence,
    }


def harness_incomplete(case: Mapping[str, Any], reason: str, *, external_probe_refs: Sequence[str] = ()) -> dict[str, Any]:
    """Corpus classification used when no concrete mutated authority object exists."""

    return {
        "case_id": case["case_id"],
        "title": case["title"],
        "family": case["family"],
        "fixture": case.get("fixture"),
        "mutation": case.get("mutation"),
        "classification": "HARNESS_INCOMPLETE",
        "harness_reason_code": "CORPUS_DESCRIPTOR_ONLY",
        "assertions": [],
        "reason": reason,
        "external_probe_refs": list(external_probe_refs),
        "external_probe_coverage": "related_partial_only" if external_probe_refs else "none",
        "candidate_pass_fail_attribution_allowed": False,
    }


def expected_used_roots(base: Mapping[str, Any], family: str, query: Mapping[str, Any]) -> list[str]:
    authority = base["authority_projection"]
    if family == "dbn":
        timeline = base["dbn"]["timeline"]
        final_index = timeline.index(query["target_slice"])
        if query["operator"] == "smooth":
            final_index = timeline.index(query.get("evidence_through", timeline[-1]))
        return [
            row["root_ref"]["occurrence_id"]
            for row in authority["dbn_observations"]
            if row["slice_index"] <= final_index
        ]
    if query["operator"] == "condition":
        condition = query["given"]
    elif query["operator"] == "aap":
        condition = query["factual"]
    else:
        condition = {}
    return [
        row["root_ref"]["occurrence_id"]
        for row in authority["scm_factual_observations"]
        if row["variable"] in condition and row["value"] == condition[row["variable"]]
    ]


def lift_portable_query(result: Mapping[str, Any]) -> dict[str, Any]:
    """Invert B's execute witness for the currently materialized query set."""

    operator = result["operator"]
    witness = result["witness"]
    if operator in {"filter", "smooth"}:
        query: dict[str, Any] = {
            "operator": operator,
            "target": result["target"],
            "target_slice": witness["target_slice"],
        }
        if operator == "smooth":
            query["evidence_through"] = witness["smoothing_evidence_through"]
            query["later_evidence_policy"] = witness["later_evidence_policy"]
        return query
    if operator == "condition":
        return {"operator": "condition", "target": result["target"], "given": witness["observation_set"]}
    if operator == "do":
        population_condition = witness["population_condition"]
        return {
            "operator": "intervene",
            "target": result["target"],
            "do_set": witness["do_set"],
            "population_selector": None if population_condition == {} else population_condition,
        }
    if operator == "aap":
        stages = [name for name in ("abduction", "action", "prediction") if witness.get(name) is True]
        return {
            "operator": "aap",
            "target": result["target"],
            "factual": witness["factual_evidence"],
            "do_set": witness["do_set"],
            "shared_world_policy": witness["shared_world_policy"],
            "stages": stages,
        }
    raise ValueError(f"cannot lift unsupported result operator {operator!r}")


def resolve_query(base: Mapping[str, Any], requested: str) -> tuple[str, dict[str, Any]]:
    queries = base["authority_projection"]["queries"]
    if requested in queries:
        query = copy.deepcopy(queries[requested])
        return ("dbn" if query["operator"] in {"filter", "smooth"} else "scm"), query
    if requested == "condition_t0":
        query = copy.deepcopy(queries["condition_t1"])
        variable = next(iter(query["given"]))
        query["given"][variable] = 0
        return "scm", query
    if requested == "do_t1":
        query = copy.deepcopy(queries["do_t0"])
        variable = next(iter(query["do_set"]))
        query["do_set"][variable] = 1
        return "scm", query
    if requested == "smooth_t1":
        query = copy.deepcopy(queries["smooth_t1_later_y2"])
        query["evidence_through"] = query["target_slice"]
        return "dbn", query
    if requested.startswith("aap_"):
        matches = [copy.deepcopy(value) for value in queries.values() if value["operator"] == "aap"]
        if len(matches) == 1:
            return "scm", matches[0]
    raise KeyError(f"portable query {requested!r} is not defined or derivable")


def lower_query(query: Mapping[str, Any]) -> dict[str, Any]:
    lowered = copy.deepcopy(query)
    lowered["kind"] = lowered.pop("operator")
    if "factual" in lowered:
        lowered["factual_evidence"] = lowered.pop("factual")
    return lowered


def portable_dbn_oracle(base: Mapping[str, Any], query: Mapping[str, Any], observations: Sequence[Mapping[str, Any]] | None = None) -> Fraction:
    """Independent exact enumeration over member and the three binary slices."""

    dbn = base["dbn"]
    timeline = dbn["timeline"]
    target_index = timeline.index(query["target_slice"])
    final_index = target_index
    if query["operator"] == "smooth":
        final_index = timeline.index(query.get("evidence_through", timeline[-1]))
    rows = list(observations if observations is not None else base["authority_projection"]["dbn_observations"])
    visible = {
        row["slice_index"]: row["measurement"]["value"]
        for row in rows
        if row["slice_index"] <= final_index and row["measurement"].get("kind") == "exact"
    }
    p_y1 = {int(x): Fraction(*pair) for x, pair in dbn["measurement"]["p_y1_given_x"].items()}
    numerator = Fraction(0)
    denominator = Fraction(0)
    for member in dbn["epistemic_members"]:
        member_weight = Fraction(*member["weight"])
        initial_p1 = Fraction(*member["prior_x1"])
        for path in ((x0, x1, x2) for x0 in (0, 1) for x1 in (0, 1) for x2 in (0, 1)):
            probability = member_weight * (initial_p1 if path[0] else 1 - initial_p1)
            for edge in (0, 1):
                p1 = Fraction(*member["transition_no_action_p1"][str(path[edge])])
                probability *= p1 if path[edge + 1] else 1 - p1
            for slice_index, value in visible.items():
                p = p_y1[path[slice_index]]
                probability *= p if value == 1 else 1 - p
            denominator += probability
            if path[target_index] == 1:
                numerator += probability
    if denominator == 0:
        raise ValueError("portable DBN oracle has zero mass")
    return numerator / denominator


def portable_scm_oracle(base: Mapping[str, Any], query: Mapping[str, Any]) -> Fraction:
    scm = base["scm"]
    treatment = scm["treatment_concept"]
    outcome = scm["outcome_concept"]
    operator = query["operator"]
    numerator = Fraction(0)
    denominator = Fraction(0)
    for world in scm["worlds"]:
        weight = Fraction(*world["weight"])
        factual = {treatment: world["observed_t"], outcome: world["y1"] if world["observed_t"] else world["y0"]}
        if operator == "condition":
            if any(factual.get(key) != value for key, value in query["given"].items()):
                continue
            value = factual[outcome]
        elif operator in {"intervene", "do"}:
            do_value = query["do_set"][treatment]
            value = world["y1"] if do_value else world["y0"]
        elif operator == "aap":
            factual_condition = query["factual"]
            if any(factual.get(key) != value for key, value in factual_condition.items()):
                continue
            do_value = query["do_set"][treatment]
            value = world["y1"] if do_value else world["y0"]
        else:
            raise ValueError(f"unsupported portable SCM oracle operator {operator}")
        denominator += weight
        if value == 1:
            numerator += weight
    if denominator == 0:
        raise ValueError("portable SCM oracle has zero mass")
    return numerator / denominator


def execute_timed(candidate: Any, native: Any, query: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    start = time.perf_counter_ns()
    result = candidate.execute(native, dict(query))
    return result, time.perf_counter_ns() - start


def fixture_case(candidate: Any, base: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    family = case["family"]
    if family == "dbn":
        canonical, inverse = dbn_projection(base)
    elif family == "scm":
        canonical, inverse = scm_projection(base), None
    else:
        return unrepresentable(case, "base fixture family must be DBN or SCM")
    native, audit = audit_projection(candidate, canonical, family)
    checks = [assertion("native_capsule_audit_without_recovery_tape", audit["native_capsule_audit_equal"], **audit)]
    query_names = list(case.get("queries", []))
    if not query_names:
        if family == "dbn":
            query_names = ["filter_t1"]
        else:
            # A baseline SCM fixture exercises every causal constructor that
            # is actually materialized in the portable authority.  This is a
            # family rule, not case-id dispatch; dangling derived names in
            # H20/H21 remain HARNESS_INCOMPLETE.
            query_names = [
                name
                for name, query in base["authority_projection"]["queries"].items()
                if query.get("operator") in {"condition", "intervene", "do", "aap"}
            ]
    outputs: dict[str, Any] = {}
    run_latencies: list[int] = []
    for name in query_names:
        resolved_family, portable_query = resolve_query(base, name)
        if resolved_family != family:
            raise AssertionError("query family disagrees with case family")
        result, elapsed = execute_timed(candidate, native, lower_query(portable_query))
        run_latencies.append(elapsed)
        observed = probability_one(result, inverse=inverse)
        expected_fraction = portable_dbn_oracle(base, portable_query) if family == "dbn" else portable_scm_oracle(base, portable_query)
        expected = float(expected_fraction)
        error = abs(observed - expected)
        checks.append(
            assertion(
                f"exact_finite_numeric:{name}",
                error <= TOL,
                observed=observed,
                expected=expected,
                expected_numerator=expected_fraction.numerator,
                expected_denominator=expected_fraction.denominator,
                absolute_error=error,
                operator=result["operator"],
                operator_tag=result["operator_tag"],
                used_roots=result["used_roots"],
            )
        )
        roots_expected = expected_used_roots(base, family, portable_query)
        checks.append(
            assertion(
                f"consumed_roots_exact:{name}",
                result["used_roots"] == roots_expected,
                observed=result["used_roots"],
                expected=roots_expected,
                native_addresses=result["witness"]["native_addresses"],
            )
        )
        lifted_query = lift_portable_query(result)
        checks.append(
            assertion(
                f"execute_query_constructor_roundtrip:{name}",
                canonical_equal(lifted_query, portable_query),
                observed=lifted_query,
                expected=portable_query,
                explicit_inverse_mappings=[
                    "candidate do -> portable intervene",
                    "empty population_condition -> null population_selector",
                    "AAP stage booleans -> ordered stages list",
                ],
            )
        )
        outputs[name] = {
            "probability_one": observed,
            "oracle": expected,
            "operator": result["operator"],
            "operator_tag": result["operator_tag"],
            "used_roots": result["used_roots"],
            "future_evidence_used": result["witness"].get("future_evidence_used"),
            "lifted_portable_query": lifted_query,
        }
    if family == "dbn" and len(outputs) >= 2:
        values = [row["probability_one"] for row in outputs.values()]
        checks.append(assertion("filter_and_smooth_separated", abs(values[0] - values[1]) >= MIN_FILTER_SMOOTH_SEPARATION, values=values, preregistered_minimum=MIN_FILTER_SMOOTH_SEPARATION))
        filter_row = outputs.get("filter_t1")
        smooth_row = outputs.get("smooth_t1_later_y2")
        if filter_row and smooth_row:
            checks.append(
                assertion(
                    "filter_smooth_operator_policy_witness_distinct",
                    filter_row["operator"] == "filter"
                    and smooth_row["operator"] == "smooth"
                    and filter_row["operator_tag"] != smooth_row["operator_tag"]
                    and filter_row["future_evidence_used"] is False
                    and smooth_row["future_evidence_used"] is True,
                    filter=filter_row,
                    smooth=smooth_row,
                )
            )
    if family == "scm" and len(outputs) >= 2:
        by_operator = {row["operator"]: row["probability_one"] for row in outputs.values()}
        if "aap" in by_operator and "do" in by_operator:
            checks.append(assertion("aap_and_population_do_separated", abs(by_operator["aap"] - by_operator["do"]) > TOL, values=by_operator))
    if "uncertainty" in case["coverage"]:
        observed_uncertainty = native_audit(native)["uncertainty"]
        expected_uncertainty = canonical["uncertainty"]
        channel_names = {"aleatoric", "epistemic", "measurement"}
        checks.append(
            assertion(
                "typed_uncertainty_channels_preserved",
                channel_names <= set(observed_uncertainty) and "confidence" not in observed_uncertainty and canonical_equal(observed_uncertainty, expected_uncertainty),
                observed=observed_uncertainty,
            )
        )
    partial = case_result(
        case,
        checks,
        native_invoked=True,
        outputs=outputs,
        metrics={"compile_ns": audit["compile_ns"], "recover_ns": audit["recover_ns"], "run_ns": run_latencies},
    )
    if all(row["passed"] for row in checks):
        partial["classification"] = "HARNESS_INCOMPLETE"
        partial["harness_reason_code"] = "MODEL_ROUNDTRIP_AUDIT_OMITTED"
        partial["candidate_pass_fail_attribution_allowed"] = False
    partial["verified_partial_assertions"] = sum(row["passed"] for row in checks)
    partial["failed_partial_assertions"] = sum(not row["passed"] for row in checks)
    return partial


def probe_record(
    probe_id: str,
    title: str,
    status: str,
    construction: Mapping[str, Any],
    inputs: Any,
    assertions: Sequence[dict[str, Any]],
    trace: Mapping[str, Any],
) -> dict[str, Any]:
    if status not in {"CANDIDATE_PASS", "CANDIDATE_FAIL", "ADAPTER_UNREPRESENTABLE"}:
        raise ValueError("invalid external-probe status")
    return {
        "probe_id": probe_id,
        "title": title,
        "evidence_class": "post_seal_external_probe",
        "counts_as_mechanically_generated_hidden_case": False,
        "classification": status,
        "deterministic_construction": dict(construction),
        "input_sha256": sha256(canonical_bytes(inputs)).hexdigest(),
        "assertions": list(assertions),
        "trace": dict(trace),
    }


def external_scm_operator_probe(candidate: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    canonical = scm_projection(base)
    native = candidate.compile_bundle(canonical, "finite_scm")
    query_names = ["condition_t1", "condition_t0", "do_t0", "do_t1", "aap_t0_given_t1_y1"]
    outputs: dict[str, Any] = {}
    checks = []
    for name in query_names:
        _, portable_query = resolve_query(base, name)
        result = candidate.execute(native, lower_query(portable_query))
        observed = probability_one(result)
        exact = portable_scm_oracle(base, portable_query)
        error = abs(observed - float(exact))
        outputs[name] = {
            "operator": result["operator"],
            "operator_tag": result["operator_tag"],
            "observed": observed,
            "oracle": float(exact),
            "absolute_error": error,
            "used_roots": result["used_roots"],
        }
        checks.append(assertion(f"numeric:{name}", error <= TOL, **outputs[name]))
    checks.extend(
        [
            assertion("condition_not_do", abs(outputs["condition_t1"]["observed"] - outputs["do_t1"]["observed"]) > TOL),
            assertion("aap_not_population_do", abs(outputs["aap_t0_given_t1_y1"]["observed"] - outputs["do_t0"]["observed"]) > TOL),
            assertion(
                "aap_consumes_factual_roots",
                set(outputs["aap_t0_given_t1_y1"]["used_roots"])
                == {row["root_ref"]["occurrence_id"] for row in base["authority_projection"]["scm_factual_observations"]},
                roots=outputs["aap_t0_given_t1_y1"]["used_roots"],
            ),
        ]
    )
    return probe_record(
        "PB-SCM-OPS",
        "Condition, population do, and shared-world AAP external derivation",
        "CANDIDATE_PASS" if all(row["passed"] for row in checks) else "CANDIDATE_FAIL",
        {
            "source": "base.scm plus base.authority_projection.queries",
            "derived_queries": ["condition_t0 flips the sole given value", "do_t1 flips the sole do_set value"],
            "reason_not_hidden_case": "H20/H21 query name list is not fully materialized in the corpus",
        },
        {"canonical": canonical, "queries": query_names},
        checks,
        outputs,
    )


def corrected_dbn_inputs(base: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    canonical, _ = dbn_projection(base)
    old = copy.deepcopy(canonical["evidence"][1])
    old_root = next(row for row in canonical["roots"] if row["root_id"] == old["root_ids"][0])
    new_root = copy.deepcopy(old_root)
    new_root["root_id"] = new_root["root_occurrence_id"] = old_root["root_id"] + "-corrected"
    new_root["root_version"] = old_root["root_version"] + "-v2"
    new_root["artifact_version"] = old_root["artifact_version"] + "-v2"
    new_root["logical_id"] = old_root["logical_id"] + "-corrected"
    new_record = copy.deepcopy(old)
    new_record["record_id"] = old["record_id"] + "-corrected"
    new_record["logical_id"] = new_root["logical_id"]
    new_record["record_version"] = new_root["root_version"]
    new_record["value"] = 1
    new_record["portable_value"] = {"kind": "exact", "unit": "1", "value": 1}
    new_record["root_ids"] = [new_root["root_id"]]
    new_record["likelihood"] = [1.0 - value for value in old["likelihood"]]
    delta = {
        "kind": "Corrects",
        "old": old["record_id"],
        "new_record": new_record,
        "new_root": new_root,
        "versions": {"evidence_authority": "post-seal-probe-v2"},
    }
    clean = copy.deepcopy(canonical)
    clean["evidence"] = [row for row in clean["evidence"] if row["record_id"] != old["record_id"]] + [copy.deepcopy(new_record)]
    clean["roots"] = [row for row in clean["roots"] if row["root_id"] != old_root["root_id"]] + [copy.deepcopy(new_root)]
    clean["versions"]["evidence_authority"] = "post-seal-probe-v2"
    return canonical, delta, clean


def external_delta_probe(candidate: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    canonical, delta, clean = corrected_dbn_inputs(base)
    _, inverse = dbn_projection(base)
    query = dbn_query(base, "filter_t1")
    original = candidate.compile_bundle(canonical, "finite_dbn")
    incremental = candidate.apply_delta(original, delta)
    rebuilt = candidate.compile_bundle(clean, "finite_dbn")
    inc_result = candidate.execute(incremental, query)
    clean_result = candidate.execute(rebuilt, query)
    inc_audit = native_audit(incremental)
    clean_audit = native_audit(rebuilt)
    inc_active_roots = sorted(row["root_id"] for row in inc_audit["roots"] if row["active"])
    clean_active_roots = sorted(row["root_id"] for row in clean_audit["roots"] if row["active"])
    replacement_record = delta["new_record"]
    replacement_root = delta["new_root"]
    retract_delta = {
        "kind": "Retracts",
        "old": replacement_record["record_id"],
        "versions": {"evidence_authority": "post-seal-probe-v3"},
    }
    retracted_incremental = candidate.apply_delta(incremental, retract_delta)
    clean_retracted = copy.deepcopy(clean)
    clean_retracted["evidence"] = [row for row in clean_retracted["evidence"] if row["record_id"] != replacement_record["record_id"]]
    clean_retracted["roots"] = [row for row in clean_retracted["roots"] if row["root_id"] != replacement_root["root_id"]]
    clean_retracted["versions"]["evidence_authority"] = "post-seal-probe-v3"
    retracted_rebuilt = candidate.compile_bundle(clean_retracted, "finite_dbn")
    retract_inc_result = candidate.execute(retracted_incremental, query)
    retract_clean_result = candidate.execute(retracted_rebuilt, query)
    retract_inc_audit = native_audit(retracted_incremental)
    retract_clean_audit = native_audit(retracted_rebuilt)
    checks = [
        assertion(
            "incremental_numeric_equals_clean",
            canonical_equal(inc_result["distribution"], clean_result["distribution"]),
            incremental=probability_one(inc_result, inverse=inverse),
            clean=probability_one(clean_result, inverse=inverse),
        ),
        assertion("incremental_used_roots_equal_clean", sorted(inc_result["used_roots"]) == sorted(clean_result["used_roots"]), incremental=inc_result["used_roots"], clean=clean_result["used_roots"]),
        assertion("incremental_active_root_authority_equals_clean", inc_active_roots == clean_active_roots, incremental=inc_active_roots, clean=clean_active_roots),
        assertion(
            "incremental_executable_audit_equals_clean",
            canonical_equal(inc_audit, clean_audit),
            incremental_audit_sha256=sha256(canonical_bytes(inc_audit)).hexdigest(),
            clean_audit_sha256=sha256(canonical_bytes(clean_audit)).hexdigest(),
        ),
        assertion(
            "retraction_incremental_numeric_equals_clean",
            canonical_equal(retract_inc_result["distribution"], retract_clean_result["distribution"]),
            incremental=probability_one(retract_inc_result, inverse=inverse),
            clean=probability_one(retract_clean_result, inverse=inverse),
        ),
        assertion(
            "retraction_incremental_executable_audit_equals_clean",
            canonical_equal(retract_inc_audit, retract_clean_audit),
            incremental_audit_sha256=sha256(canonical_bytes(retract_inc_audit)).hexdigest(),
            clean_audit_sha256=sha256(canonical_bytes(retract_clean_audit)).hexdigest(),
        ),
    ]
    return probe_record(
        "PB-DELTA-CLEAN",
        "Correction incremental versus clean rebuild",
        "CANDIDATE_PASS" if all(row["passed"] for row in checks) else "CANDIDATE_FAIL",
        {
            "source": "base DBN projection",
            "operation": "flip the second exact observation 0->1 with a new occurrence/version; apply typed Corrects",
            "clean_rebuild": "remove old record/root, add replacement, update evidence authority version",
        },
        {"canonical": canonical, "delta": delta, "clean": clean, "retract_delta": retract_delta, "clean_retracted": clean_retracted, "query": query},
        checks,
        {
            "incremental_distribution": inc_result["distribution"],
            "clean_distribution": clean_result["distribution"],
            "incremental_used_roots": inc_result["used_roots"],
            "clean_used_roots": clean_result["used_roots"],
            "incremental_active_roots": inc_active_roots,
            "clean_active_roots": clean_active_roots,
            "retraction_incremental_distribution": retract_inc_result["distribution"],
            "retraction_clean_distribution": retract_clean_result["distribution"],
            "retraction_incremental_active_roots": sorted(row["root_id"] for row in retract_inc_audit["roots"] if row["active"]),
            "retraction_clean_active_roots": sorted(row["root_id"] for row in retract_clean_audit["roots"] if row["active"]),
        },
    )


def external_m01_probe(candidate: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    dbn_canonical, inverse = dbn_projection(base)
    dbn_native = candidate.compile_bundle(dbn_canonical, "finite_dbn")
    dbn_query_map = dbn_query(base, "filter_t1")
    dbn_before = candidate.execute(dbn_native, dbn_query_map)
    hostile_prior = tuple([0.97] + [0.01] * (len(dbn_native.native_ir.prior) - 1))
    hostile_dbn_ir = replace(dbn_native.native_ir, prior=hostile_prior)
    hostile_dbn = replace(dbn_native, native_ir=hostile_dbn_ir)
    dbn_after = candidate.execute(hostile_dbn, dbn_query_map)
    dbn_recovered = candidate.recover_bundle(hostile_dbn)

    scm_canonical = scm_projection(base)
    scm_native = candidate.compile_bundle(scm_canonical, "finite_scm")
    scm_query_map = scm_query(base, "do_t0")
    scm_before = candidate.execute(scm_native, scm_query_map)
    worlds = list(scm_native.native_ir.worlds)
    hostile_worlds = tuple(
        replace(world, probability=(0.97 if index == 0 else 0.03 / (len(worlds) - 1)))
        for index, world in enumerate(worlds)
    )
    hostile_scm_ir = replace(scm_native.native_ir, worlds=hostile_worlds)
    hostile_scm = replace(scm_native, native_ir=hostile_scm_ir)
    scm_after = candidate.execute(hostile_scm, scm_query_map)
    scm_recovered = candidate.recover_bundle(hostile_scm)

    dbn_changed = abs(probability_one(dbn_before, inverse=inverse) - probability_one(dbn_after, inverse=inverse)) > TOL
    scm_changed = abs(probability_one(scm_before) - probability_one(scm_after)) > TOL
    dbn_recovery_changed = not canonical_equal(dbn_recovered, dbn_canonical)
    scm_recovery_changed = not canonical_equal(scm_recovered, scm_canonical)
    digest_changed = hostile_dbn.semantic_digest != dbn_native.semantic_digest or hostile_scm.semantic_digest != scm_native.semantic_digest
    checks = [
        assertion("destructive_native_dbn_semantics_changed_execution", dbn_changed, before=probability_one(dbn_before, inverse=inverse), after=probability_one(dbn_after, inverse=inverse)),
        assertion("destructive_native_scm_semantics_changed_execution", scm_changed, before=probability_one(scm_before), after=probability_one(scm_after)),
        assertion("recovery_reflects_dbn_executable_mutation_or_fails_closed", dbn_recovery_changed, recovered_equal_original=not dbn_recovery_changed),
        assertion("recovery_reflects_scm_executable_mutation_or_fails_closed", scm_recovery_changed, recovered_equal_original=not scm_recovery_changed),
        assertion("semantic_digest_binds_executable_semantics", digest_changed, digest=dbn_native.semantic_digest),
    ]
    return probe_record(
        "PB-M01-DESTRUCTIVE",
        "M01 destructive executable-semantics round trip",
        "CANDIDATE_PASS" if all(row["passed"] for row in checks) else "CANDIDATE_FAIL",
        {
            "mutation_1": "replace DBN executable prior with (0.97,0.01,...) while leaving recovery tape/digest untouched",
            "mutation_2": "replace SCM executable world probabilities with 0.97/remaining while leaving recovery tape/digest untouched",
            "acceptance": "execution must refuse, or recovered semantics/digest must change; tape echo is failure",
        },
        {
            "dbn_canonical": dbn_canonical,
            "dbn_mutation": {"prior": hostile_prior},
            "scm_canonical": scm_canonical,
            "scm_mutation": {"world_probabilities": [row.probability for row in hostile_worlds]},
        },
        checks,
        {
            "dbn_before": probability_one(dbn_before, inverse=inverse),
            "dbn_after": probability_one(dbn_after, inverse=inverse),
            "scm_before": probability_one(scm_before),
            "scm_after": probability_one(scm_after),
            "dbn_recovered_equal_original": not dbn_recovery_changed,
            "scm_recovered_equal_original": not scm_recovery_changed,
            "semantic_digest_changed": digest_changed,
        },
    )


def external_query_cut_probe(candidate: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    canonical, inverse = dbn_projection(base)
    native = candidate.compile_bundle(canonical, "finite_dbn")
    timeline = base["dbn"]["timeline"]
    unknown_target = "unbound-state-concept-post-seal-probe"
    target_query = dbn_query(base, "filter_t1")
    target_query["target"] = unknown_target
    outside_query = dbn_query(base, "filter_t1")
    outside_query["target_slice"] = timeline[0]
    traces: dict[str, Any] = {}
    checks = []
    for label, query in (("unbound_target", target_query), ("outside_frozen_window", outside_query)):
        try:
            result = candidate.execute(native, query)
            traces[label] = {"accepted": True, "target": result["target"], "mean": probability_one(result, inverse=inverse), "used_roots": result["used_roots"]}
            rejected = False
        except candidate.BridgeError as error:
            fragments = ("unbound", "target", "outside") if label == "unbound_target" else ("window", "outside", "cut mismatch")
            rejected, error_trace = typed_candidate_error(error, fragments)
            traces[label] = {"accepted": False, "phase": "execute", "native_result_returned": False, **error_trace}
        checks.append(assertion(f"typed_reject:{label}", rejected, **traces[label]))
    return probe_record(
        "PB-QUERY-CUT-GUARDS",
        "Query target binding and frozen target-window guards",
        "CANDIDATE_PASS" if all(row["passed"] for row in checks) else "CANDIDATE_FAIL",
        {
            "unbound_target": "replace target concept only; target slice remains valid",
            "outside_window": "use declared timeline[0] while cut.target_window is timeline[1]",
            "acceptance": "typed refusal before execute result",
        },
        {"canonical": canonical, "queries": [target_query, outside_query]},
        checks,
        traces,
    )


def external_version_integrity_probe(candidate: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    canonical, inverse = dbn_projection(base)
    unavailable = copy.deepcopy(canonical)
    unavailable["bridge"]["registered_at"] = plus_microsecond(canonical["temporal_cut"]["actor_visibility_cut"])
    unavailable["versions"]["model"] = "model-version-not-registered-post-seal-probe"
    query = dbn_query(base, "filter_t1")
    trace: dict[str, Any] = {}
    try:
        native_unavailable = candidate.compile_bundle(unavailable, "finite_dbn")
        unavailable_result = candidate.execute(native_unavailable, query)
        unavailable_rejected = False
        trace["unavailable"] = {"accepted": True, "mean": probability_one(unavailable_result, inverse=inverse), "versions": unavailable_result["witness"]["versions"]}
    except candidate.BridgeError as error:
        unavailable_rejected, error_trace = typed_candidate_error(error, ("version", "registered", "unavailable"))
        trace["unavailable"] = {"accepted": False, "phase": "compile_or_execute", "native_result_returned": False, **error_trace}

    native = candidate.compile_bundle(canonical, "finite_dbn")
    versions = decode_b_frozen(native.versions_sidecar)
    versions["model"] = "tampered-executable-sidecar-version"
    hostile = replace(native, versions_sidecar=encode_b_frozen(versions))
    try:
        hostile_result = candidate.execute(hostile, query)
        integrity_rejected = False
        trace["sidecar_tamper"] = {
            "accepted": True,
            "reported_model_version": hostile_result["witness"]["versions"]["model"],
            "semantic_digest_unchanged": hostile.semantic_digest == native.semantic_digest,
            "recovered_model_version": candidate.recover_bundle(hostile)["versions"]["model"],
        }
    except candidate.BridgeError as error:
        integrity_rejected, error_trace = typed_candidate_error(error, ("integrity", "digest", "version"))
        trace["sidecar_tamper"] = {"accepted": False, "phase": "execute", "native_result_returned": False, **error_trace}
    checks = [
        assertion("future_bridge_or_missing_model_typed_reject", unavailable_rejected, **trace["unavailable"]),
        assertion("version_sidecar_tamper_integrity_reject", integrity_rejected, **trace["sidecar_tamper"]),
    ]
    return probe_record(
        "PB-VERSION-INTEGRITY",
        "Version availability and executable-sidecar integrity",
        "CANDIDATE_PASS" if all(row["passed"] for row in checks) else "CANDIDATE_FAIL",
        {
            "unavailable": "move bridge registration 1us after actor cut and use an unregistered model token",
            "tamper": "replace only native versions_sidecar with independent closed encoder",
        },
        {"canonical": canonical, "unavailable": unavailable, "query": query, "tampered_versions": versions},
        checks,
        trace,
    )


def cloned_root_and_record(canonical: Mapping[str, Any], record_index: int, suffix: str, *, preserve_family: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    record = copy.deepcopy(canonical["evidence"][record_index])
    old_root = next(row for row in canonical["roots"] if row["root_id"] == record["root_ids"][0])
    root = copy.deepcopy(old_root)
    root["root_id"] = root["root_occurrence_id"] = old_root["root_id"] + suffix
    root["root_version"] = old_root["root_version"] + suffix
    root["artifact_version"] = old_root["artifact_version"] + suffix
    root["logical_id"] = old_root["logical_id"] + suffix
    if not preserve_family:
        root["dependence_families"] = [old_root["dependence_families"][0] + suffix]
    record["record_id"] += suffix
    record["logical_id"] = root["logical_id"]
    record["record_version"] = root["root_version"]
    record["root_ids"] = [root["root_id"]]
    record["dependence_families"] = copy.deepcopy(root["dependence_families"])
    return root, record


def external_root_dependence_probe(candidate: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    canonical, inverse = dbn_projection(base)
    query = dbn_query(base, "filter_t1")
    baseline_native = candidate.compile_bundle(canonical, "finite_dbn")
    baseline = candidate.execute(baseline_native, query)
    baseline_value = probability_one(baseline, inverse=inverse)

    same_root = copy.deepcopy(canonical)
    alias = copy.deepcopy(same_root["evidence"][1])
    alias["record_id"] += "-same-root-alias"
    # Only the materialisation path/record identity changes.  Logical and root
    # occurrence identities remain exact, so a numeric difference is genuine
    # path-count voting rather than an illegal logical-version fork.
    alias["projection_path_alias"] = "alternate-fanout-path"
    same_root["evidence"].append(alias)
    same_root_result = candidate.execute(candidate.compile_bundle(same_root, "finite_dbn"), query)
    same_root_value = probability_one(same_root_result, inverse=inverse)

    same_family = copy.deepcopy(canonical)
    family_root, family_record = cloned_root_and_record(same_family, 1, "-same-family", preserve_family=True)
    same_family["roots"].append(family_root)
    same_family["evidence"].append(family_record)
    family_rejected = False
    family_trace: dict[str, Any]
    try:
        family_result = candidate.execute(candidate.compile_bundle(same_family, "finite_dbn"), query)
        family_trace = {"accepted": True, "mean": probability_one(family_result, inverse=inverse), "used_roots": family_result["used_roots"]}
    except candidate.BridgeError as error:
        family_rejected, error_trace = typed_candidate_error(error, ("dependence", "joint", "duplicate"))
        family_trace = {"accepted": False, "phase": "compile_or_execute", "native_result_returned": False, **error_trace}

    independent = copy.deepcopy(canonical)
    independent_root, independent_record = cloned_root_and_record(independent, 1, "-independent", preserve_family=False)
    independent["roots"].append(independent_root)
    independent["evidence"].append(independent_record)
    independent_result = candidate.execute(candidate.compile_bundle(independent, "finite_dbn"), query)
    independent_value = probability_one(independent_result, inverse=inverse)
    checks = [
        assertion("same_root_alias_idempotent", abs(same_root_value - baseline_value) <= TOL, baseline=baseline_value, duplicate=same_root_value, used_roots=same_root_result["used_roots"]),
        assertion("same_dependence_family_requires_joint_model_or_reject", family_rejected, **family_trace),
        assertion("independent_family_control_is_live", abs(independent_value - baseline_value) > TOL, baseline=baseline_value, independent=independent_value),
    ]
    return probe_record(
        "PB-ROOT-DEPENDENCE",
        "Root occurrence idempotence and dependence-family handling",
        "CANDIDATE_PASS" if all(row["passed"] for row in checks) else "CANDIDATE_FAIL",
        {
            "same_root": "duplicate one t1 record under a new path/record ID but identical root occurrence",
            "same_family": "duplicate under a new occurrence retaining the original dependence family",
            "independent_control": "duplicate under a new occurrence and a new dependence family",
        },
        {"baseline": canonical, "same_root": same_root, "same_family": same_family, "independent": independent, "query": query},
        checks,
        {
            "baseline": baseline_value,
            "same_root": same_root_value,
            "same_family": family_trace,
            "independent": independent_value,
        },
    )


def external_postcut_delta_probe(candidate: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    canonical, delta, _ = corrected_dbn_inputs(base)
    _, inverse = dbn_projection(base)
    cut = canonical["temporal_cut"]["transaction_revision_cut"]
    delta["new_record"]["transaction_revision"] = plus_microsecond(cut)
    delta["new_record"]["available_at"] = plus_microsecond(canonical["temporal_cut"]["actor_visibility_cut"])
    delta["new_root"]["times"]["kernel_committed"] = delta["new_record"]["transaction_revision"]
    delta["new_root"]["times"]["available_to_actor"] = delta["new_record"]["available_at"]
    query = dbn_query(base, "filter_t1")
    original = candidate.compile_bundle(canonical, "finite_dbn")
    original_result = candidate.execute(original, query)
    incremental = candidate.apply_delta(original, delta)
    incremental_result = candidate.execute(incremental, query)
    original_value = probability_one(original_result, inverse=inverse)
    incremental_value = probability_one(incremental_result, inverse=inverse)
    checks = [
        assertion("postcut_correction_invisible_at_old_cut", abs(original_value - incremental_value) <= TOL, original=original_value, incremental=incremental_value),
        assertion("postcut_new_root_not_consumed", delta["new_root"]["root_id"] not in incremental_result["used_roots"], used_roots=incremental_result["used_roots"]),
        assertion("precut_old_root_remains_consumed", canonical["evidence"][1]["root_ids"][0] in incremental_result["used_roots"], used_roots=incremental_result["used_roots"]),
    ]
    return probe_record(
        "PB-POSTCUT-DELTA",
        "Post-transaction-cut correction invisibility",
        "CANDIDATE_PASS" if all(row["passed"] for row in checks) else "CANDIDATE_FAIL",
        {
            "source": "PB-DELTA-CLEAN correction",
            "mutation": "move replacement availability and transaction revision 1us after the frozen cuts",
            "acceptance": "old bundle result and witness remain unchanged",
        },
        {"canonical": canonical, "delta": delta, "query": query},
        checks,
        {
            "original": original_value,
            "incremental": incremental_value,
            "original_roots": original_result["used_roots"],
            "incremental_roots": incremental_result["used_roots"],
        },
    )


def external_closed_semantic_guards_probe(candidate: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    traces: dict[str, Any] = {}
    checks = []

    # Empty dependence family: metadata remains syntactically JSON-like, so a
    # closed semantic bridge must reject rather than invent independence.
    empty_family, inverse = dbn_projection(base)
    empty_family["roots"][0]["dependence_families"] = []
    empty_family["evidence"][0]["dependence_families"] = []
    try:
        result = candidate.execute(candidate.compile_bundle(empty_family, "finite_dbn"), dbn_query(base, "filter_t1"))
        traces["empty_dependence_family"] = {"accepted": True, "mean": probability_one(result, inverse=inverse), "used_roots": result["used_roots"]}
        rejected = False
    except candidate.BridgeError as error:
        rejected, error_trace = typed_candidate_error(error, ("dependence", "family", "independence"))
        traces["empty_dependence_family"] = {"accepted": False, "phase": "compile_or_execute", "native_result_returned": False, **error_trace}
    checks.append(assertion("empty_dependence_family_typed_reject", rejected, **traces["empty_dependence_family"]))

    # Same subject, different encounter.  Both the query and bundle carry an
    # explicit scope; candidate B currently treats them as inert extras.
    scope_mismatch, inverse = dbn_projection(base)
    authoritative_scope = copy.deepcopy(scope_mismatch["roots"][0]["scope"])
    scope_mismatch["query_scope"] = authoritative_scope
    scope_mismatch["roots"][1]["scope"]["encounter"] += "-other"
    scope_mismatch["evidence"][1]["scope"] = copy.deepcopy(scope_mismatch["roots"][1]["scope"])
    scope_query = dbn_query(base, "filter_t1")
    scope_query["scope"] = authoritative_scope
    try:
        result = candidate.execute(candidate.compile_bundle(scope_mismatch, "finite_dbn"), scope_query)
        traces["scope_mismatch"] = {"accepted": True, "mean": probability_one(result, inverse=inverse), "used_roots": result["used_roots"]}
        rejected = False
    except candidate.BridgeError as error:
        rejected, error_trace = typed_candidate_error(error, ("scope", "encounter", "specimen"))
        traces["scope_mismatch"] = {"accepted": False, "phase": "compile_or_execute", "native_result_returned": False, **error_trace}
    checks.append(assertion("encounter_scope_mismatch_typed_reject", rejected, **traces["scope_mismatch"]))

    # SCM namespace collision in a world-table representation.
    collision = scm_projection(base)
    treatment = base["scm"]["treatment_concept"]
    collision["model"]["worlds"][0]["exogenous"] = {treatment: 1}
    try:
        native = candidate.compile_bundle(collision, "finite_scm")
        result = candidate.execute(native, scm_query(base, "do_t0"))
        traces["causal_namespace_collision"] = {"accepted": True, "mean": probability_one(result)}
        rejected = False
    except candidate.BridgeError as error:
        rejected, error_trace = typed_candidate_error(error, ("namespace", "collision", "exogenous", "endogenous"))
        traces["causal_namespace_collision"] = {"accepted": False, "phase": "compile_or_execute", "native_result_returned": False, **error_trace}
    checks.append(assertion("causal_namespace_collision_typed_reject", rejected, **traces["causal_namespace_collision"]))

    # Population selector uses the portable field name.  Ignoring it produces
    # exactly the unselected population result and consumes no selector root.
    scm_canonical = scm_projection(base)
    native = candidate.compile_bundle(scm_canonical, "finite_scm")
    unselected_query = scm_query(base, "do_t0")
    selected_query = copy.deepcopy(unselected_query)
    selected_query["population_selector"] = {treatment: 1}
    selector_root = next(
        row["root_ref"]["occurrence_id"]
        for row in base["authority_projection"]["scm_factual_observations"]
        if row["variable"] == treatment
    )
    unselected = candidate.execute(native, unselected_query)
    selector_safe = False
    try:
        selected = candidate.execute(native, selected_query)
        selector_safe = selector_root in selected["used_roots"] and abs(probability_one(unselected) - probability_one(selected)) > TOL
        traces["population_selector"] = {
            "accepted": True,
            "phase": "execute",
            "native_result_returned": True,
            "unselected": probability_one(unselected),
            "selected": probability_one(selected),
            "selected_used_roots": selected["used_roots"],
        }
    except candidate.BridgeError as error:
        selector_safe, error_trace = typed_candidate_error(error, ("population", "selector", "unsupported", "identified"))
        traces["population_selector"] = {"accepted": False, "phase": "execute", "native_result_returned": False, **error_trace}
    checks.append(
        assertion(
            "population_selector_consumed_or_typed_reject",
            selector_safe,
            **traces["population_selector"],
        )
    )
    return probe_record(
        "PB-CLOSED-SEMANTIC-GUARDS",
        "Dependence, scope, causal namespace, and selector guards",
        "CANDIDATE_PASS" if all(row["passed"] for row in checks) else "CANDIDATE_FAIL",
        {
            "empty_family": "clear one authoritative root and record dependence-family list",
            "scope": "change only encounter for one same-subject record and declare query scope",
            "namespace": "reuse treatment symbol in one world exogenous map",
            "selector": "add portable population_selector={factual treatment:1} to population do",
        },
        {
            "empty_family": empty_family,
            "scope_mismatch": scope_mismatch,
            "namespace_collision": collision,
            "population_selector_query": selected_query,
        },
        checks,
        traces,
    )


def external_censored_refusal_probe(candidate: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    traces: dict[str, Any] = {}
    checks = []
    for kind, payload in (
        ("absent", {"kind": "absent"}),
        ("below_detection", {"kind": "below_detection", "upper_bound": 0.2, "unit": "1"}),
    ):
        canonical, inverse = dbn_projection(base)
        record = canonical["evidence"][1]
        record["value"] = payload
        record["portable_value"] = copy.deepcopy(payload)
        record.pop("likelihood", None)
        compiled = False
        try:
            native = candidate.compile_bundle(canonical, "finite_dbn")
            compiled = True
            result = candidate.execute(native, dbn_query(base, "filter_t1"))
            control = copy.deepcopy(canonical)
            removed_root = record["root_ids"][0]
            control["evidence"] = [row for row in control["evidence"] if row["record_id"] != record["record_id"]]
            control["roots"] = [row for row in control["roots"] if row["root_id"] != removed_root]
            control_result = candidate.execute(candidate.compile_bundle(control, "finite_dbn"), dbn_query(base, "filter_t1"))
            mean = probability_one(result, inverse=inverse)
            prior_control = probability_one(control_result, inverse=inverse)
            typed_trace = [row for row in result["witness"]["evidence_uncertainty"] if row["native_address"] in result["witness"]["native_addresses"]]
            safe = removed_root in result["used_roots"] and abs(mean - prior_control) > TOL and bool(typed_trace)
            traces[kind] = {
                "compiled": True,
                "execute_called": True,
                "native_result_returned": True,
                "mean": mean,
                "deleted_evidence_control_mean": prior_control,
                "used_roots": result["used_roots"],
                "typed_uncertainty_trace": typed_trace,
            }
        except candidate.BridgeError as error:
            safe, error_trace = typed_candidate_error(error, ("emission row lacks value", "likelihood", "unsupported"))
            traces[kind] = {
                "compiled": compiled,
                "execute_called": False,
                "native_result_returned": False,
                "phase": "compile" if not compiled else "execute",
                **error_trace,
            }
        checks.append(assertion(f"{kind}_typed_likelihood_or_refusal_no_green_prior", safe, **traces[kind]))
    all_unrepresentable = all(not row.get("compiled", False) for row in traces.values())
    return probe_record(
        "PB-TYPED-MEASUREMENT-REFUSAL",
        "Absent and censored observations do not launder to a green prior",
        "ADAPTER_UNREPRESENTABLE"
        if all_unrepresentable
        else ("CANDIDATE_PASS" if all(row["passed"] for row in checks) else "CANDIDATE_FAIL"),
        {
            "mutation": "replace one exact observation sum type and remove its explicit likelihood",
            "acceptance": "typed model-aware likelihood or typed refusal; no successful prior fallback",
        },
        traces,
        checks,
        traces,
    )


def external_time_boundary_probe(candidate: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    canonical, inverse = dbn_projection(base)
    boundary_record = canonical["evidence"][2]
    boundary_root_id = boundary_record["root_ids"][0]
    visibility = boundary_record["available_at"]
    canonical["temporal_cut"]["actor_visibility_cut"] = visibility
    canonical["temporal_cut"]["transaction_revision_cut"] = boundary_record["transaction_revision"]
    future_root, future_record = cloned_root_and_record(canonical, 2, "-plus-1us", preserve_family=False)
    future_record["available_at"] = plus_microsecond(visibility)
    future_record["transaction_revision"] = plus_microsecond(boundary_record["transaction_revision"])
    future_root["times"]["available_to_actor"] = future_record["available_at"]
    future_root["times"]["kernel_committed"] = future_record["transaction_revision"]
    canonical["roots"].append(future_root)
    canonical["evidence"].append(future_record)
    query = dbn_query(base, "smooth_t1_later_y2")
    native = candidate.compile_bundle(canonical, "finite_dbn")
    result = candidate.execute(native, query)
    future_id = future_root["root_id"]
    checks = [
        assertion("available_at_boundary_included", boundary_root_id in result["used_roots"], used_roots=result["used_roots"]),
        assertion("available_at_plus_1us_excluded", future_id not in result["used_roots"], used_roots=result["used_roots"]),
        assertion("boundary_query_is_smooth", result["operator"] == "smooth" and result["witness"].get("future_evidence_used") is True, operator=result["operator"], witness=result["witness"]),
    ]
    return probe_record(
        "PB-TIME-BOUNDARY",
        "Actor/revision cut inclusive boundary and future exclusion",
        "CANDIDATE_PASS" if all(row["passed"] for row in checks) else "CANDIDATE_FAIL",
        {
            "boundary": "set actor and revision cuts equal to the existing y2 record clocks",
            "future": "clone y2 under a new independent root and move both clocks +1us",
        },
        {"canonical": canonical, "query": query},
        checks,
        {"mean": probability_one(result, inverse=inverse), "used_roots": result["used_roots"], "boundary_root": boundary_root_id, "future_root": future_id},
    )


def external_uncertainty_isolation_probe(candidate: Any, base: Mapping[str, Any]) -> dict[str, Any]:
    variants: dict[str, dict[str, Any]] = {"control": copy.deepcopy(base)}
    aleatoric = copy.deepcopy(base)
    aleatoric["dbn"]["epistemic_members"][0]["transition_no_action_p1"]["0"] = [27, 100]
    aleatoric["dbn"]["uncertainty_contract"]["aleatoric"] = "stochastic_state_transition:perturbed"
    variants["aleatoric"] = aleatoric
    epistemic = copy.deepcopy(base)
    epistemic["dbn"]["epistemic_members"][0]["weight"] = [7, 10]
    epistemic["dbn"]["epistemic_members"][1]["weight"] = [3, 10]
    epistemic["dbn"]["uncertainty_contract"]["epistemic"] = "finite_fixed_member_ensemble:weights_perturbed"
    variants["epistemic"] = epistemic
    measurement = copy.deepcopy(base)
    measurement["dbn"]["measurement"]["p_y1_given_x"]["0"] = [21, 100]
    measurement["dbn"]["uncertainty_contract"]["measurement"] = "binary_confusion_matrix:perturbed"
    variants["measurement"] = measurement
    outputs: dict[str, Any] = {}
    checks = []
    for name, portable in variants.items():
        canonical, inverse = dbn_projection(portable)
        native = candidate.compile_bundle(canonical, "finite_dbn")
        query = dbn_query(portable, "filter_t1")
        result = candidate.execute(native, query)
        observed = probability_one(result, inverse=inverse)
        exact = portable_dbn_oracle(portable, portable["authority_projection"]["queries"]["filter_t1"])
        uncertainty = native_audit(native)["uncertainty"]
        outputs[name] = {"observed": observed, "oracle": float(exact), "absolute_error": abs(observed - float(exact)), "uncertainty": uncertainty}
        checks.append(assertion(f"numeric:{name}", abs(observed - float(exact)) <= TOL, **outputs[name]))
    control = outputs["control"]
    for channel in ("aleatoric", "epistemic", "measurement"):
        changed_descriptors = [key for key in ("aleatoric", "epistemic", "measurement") if outputs[channel]["uncertainty"][key] != control["uncertainty"][key]]
        checks.append(
            assertion(
                f"only_declared_uncertainty_descriptor_changes:{channel}",
                changed_descriptors == [channel] and abs(outputs[channel]["observed"] - control["observed"]) > TOL,
                descriptor_changes=changed_descriptors,
                control=control["observed"],
                variant=outputs[channel]["observed"],
            )
        )
    return probe_record(
        "PB-UNCERTAINTY-ISOLATION",
        "Aleatoric, epistemic, and measurement perturbations remain isolated",
        "CANDIDATE_PASS" if all(row["passed"] for row in checks) else "CANDIDATE_FAIL",
        {
            "aleatoric": "change member-0 P(Xnext=1|X=0) 0.17->0.27",
            "epistemic": "change member weights 0.58/0.42->0.70/0.30",
            "measurement": "change P(Y=1|X=0) 0.11->0.21",
            "oracle": "independent exact path enumeration for every variant",
        },
        variants,
        checks,
        outputs,
    )


PROBE_REFS_BY_MUTATION: dict[str, tuple[str, ...]] = {
    "alias_fanout_fanin_same_root": ("PB-ROOT-DEPENDENCE",),
    "two_roots_singleton_port": (),
    "raw_canary_only": (),
    "available_boundary_pair": ("PB-TIME-BOUNDARY",),
    "effective_end_and_unknown_clock": ("PB-TIME-BOUNDARY",),
    "remove_later_evidence": (),
    "target_window_mismatch": ("PB-QUERY-CUT-GUARDS",),
    "version_v1_v2": ("PB-VERSION-INTEGRITY",),
    "future_bridge_or_missing_model": ("PB-VERSION-INTEGRITY",),
    "correct_retract_alternative": ("PB-DELTA-CLEAN",),
    "unresolved_version_fork": ("PB-VERSION-INTEGRITY",),
    "schema_without_migration": ("PB-VERSION-INTEGRITY",),
    "uncertainty_one_at_a_time": ("PB-UNCERTAINTY-ISOLATION",),
    "censor_interval_pairs": ("PB-TYPED-MEASUREMENT-REFUSAL",),
    "masked_absent_unknown_conflict": ("PB-TYPED-MEASUREMENT-REFUSAL",),
    "missing_shared_policy_or_late_factual": ("PB-SCM-OPS",),
    "plan_performed_forecast_do": (),
    "cross_scope_and_role_upgrade": ("PB-CLOSED-SEMANTIC-GUARDS",),
    "unknown_mapping_and_legal_control": ("PB-VERSION-INTEGRITY",),
    "integrity_or_runner_field_tamper": ("PB-M01-DESTRUCTIVE", "PB-VERSION-INTEGRITY"),
    "alpha_rename_and_module_shuffle": (),
    "warm_future_then_old_cut": ("PB-TIME-BOUNDARY", "PB-VERSION-INTEGRITY"),
    "full_state_cross": ("PB-DELTA-CLEAN", "PB-UNCERTAINTY-ISOLATION"),
    "full_causal_cross": ("PB-SCM-OPS", "PB-DELTA-CLEAN"),
    "query_target_unknown_or_cross_bound": ("PB-QUERY-CUT-GUARDS",),
    "same_root_alias_and_same_dependence_family_duplicates": ("PB-ROOT-DEPENDENCE",),
    "correction_registered_after_transaction_cut": ("PB-POSTCUT-DELTA",),
    "supersedes_self_cycle_and_unresolved_fork": ("PB-DELTA-CLEAN",),
    "population_selector_requires_evidence": ("PB-CLOSED-SEMANTIC-GUARDS",),
    "same_subject_other_encounter_or_specimen": ("PB-CLOSED-SEMANTIC-GUARDS",),
    "correction_and_retraction_both_after_cut": ("PB-POSTCUT-DELTA",),
    "absent_and_below_detection_observations": ("PB-TYPED-MEASUREMENT-REFUSAL",),
    "query_time_before_or_after_target_window": ("PB-QUERY-CUT-GUARDS",),
    "same_symbol_exogenous_and_endogenous": ("PB-CLOSED-SEMANTIC-GUARDS",),
    "root_with_empty_dependence_families": ("PB-CLOSED-SEMANTIC-GUARDS",),
}


def percentile(values: Sequence[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1))
    return ordered[index]


def json_node_count(value: Any) -> int:
    if type(value) is dict:
        return 1 + sum(json_node_count(key) + json_node_count(child) for key, child in value.items())
    if type(value) in {list, tuple}:
        return 1 + sum(json_node_count(child) for child in value)
    return 1


def physical_nonblank_nonhash_loc(path: Path) -> int:
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#"))


def make_report() -> dict[str, Any]:
    corpus_sha = file_sha256(CORPUS_PATH)
    if corpus_sha != EXPECTED_CORPUS_SHA256:
        raise RuntimeError(f"hidden corpus hash mismatch: {corpus_sha}")
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    if freeze["implementations"]["impl_b"]["sha256"] != EXPECTED_IMPL_SHA256:
        raise RuntimeError("freeze manifest implementation-B hash mismatch")
    if corpus["transport_binding"]["implementation_b"]["source_sha256"] != EXPECTED_IMPL_SHA256:
        raise RuntimeError("corpus transport binding implementation-B hash mismatch")
    candidate = load_candidate()
    base = corpus["base"]

    case_results: list[dict[str, Any]] = []
    available_queries = set(base["authority_projection"]["queries"])
    for case in corpus["cases"]:
        mutation = case.get("mutation")
        dangling = [name for name in case.get("queries", []) if name not in available_queries]
        if mutation is not None:
            case_results.append(
                harness_incomplete(
                    case,
                    "corpus provides a mutation descriptor/oracle text but no concrete mutated authority object; external probes cannot be promoted to hidden-case evidence",
                    external_probe_refs=PROBE_REFS_BY_MUTATION.get(mutation, ()),
                )
            )
        elif dangling:
            item = harness_incomplete(
                case,
                f"query references are not materialized in base.authority_projection.queries: {dangling}",
                external_probe_refs=("PB-SCM-OPS",),
            )
            item["harness_reason_code"] = "DANGLING_QUERY"
            item["dangling_queries"] = dangling
            case_results.append(item)
        else:
            try:
                case_results.append(fixture_case(candidate, base, case))
            except Exception as error:  # runner/integration defect, not candidate attribution
                case_results.append(
                    {
                        "case_id": case["case_id"],
                        "title": case["title"],
                        "family": case["family"],
                        "fixture": case.get("fixture"),
                        "mutation": mutation,
                        "classification": "HARNESS_ERROR",
                        "harness_reason_code": "RUNNER_EXCEPTION",
                        "candidate_pass_fail_attribution_allowed": False,
                        "error_type": type(error).__name__,
                        "error": str(error),
                    }
                )

    probe_functions: list[Callable[[Any, Mapping[str, Any]], dict[str, Any]]] = [
        external_scm_operator_probe,
        external_delta_probe,
        external_m01_probe,
        external_query_cut_probe,
        external_version_integrity_probe,
        external_root_dependence_probe,
        external_postcut_delta_probe,
        external_closed_semantic_guards_probe,
        external_censored_refusal_probe,
        external_time_boundary_probe,
        external_uncertainty_isolation_probe,
    ]
    probes = [function(candidate, base) for function in probe_functions]

    mechanical_counts = {name: sum(row["classification"] == name for row in case_results) for name in ("PASS", "CANDIDATE_FAIL", "ADAPTER_UNREPRESENTABLE", "HARNESS_INCOMPLETE", "HARNESS_ERROR")}
    probe_counts = {name: sum(row["classification"] == name for row in probes) for name in ("CANDIDATE_PASS", "CANDIDATE_FAIL", "ADAPTER_UNREPRESENTABLE")}
    case_by_id = {row["case_id"]: row for row in case_results}
    probe_by_id = {row["probe_id"]: row for row in probes}
    compile_ns: list[int] = []
    recover_ns: list[int] = []
    run_ns: list[int] = []
    for row in case_results:
        metrics = row.get("metrics", {})
        if "compile_ns" in metrics:
            compile_ns.append(metrics["compile_ns"])
        if "recover_ns" in metrics:
            recover_ns.append(metrics["recover_ns"])
        run_ns.extend(metrics.get("run_ns", []))

    hard_assertions = {
        "root_scope_clock_version_uncertainty_roundtrip": {
            "classification": "INCOMPLETE",
            "evidence": ["H01", "H02", "H16"],
            "recovery_tape_counted": False,
            "reason": "full executable model audit is not implemented",
        },
        "dbn_filter_smooth_exact": {
            "classification": "PARTIAL_PASS_MODEL_ROUNDTRIP_INCOMPLETE",
            "evidence": ["H08"],
        },
        "scm_condition_do_aap": {
            "classification": "POST_SEAL_EXTERNAL_ONLY",
            "candidate_probe_result": probe_by_id["PB-SCM-OPS"]["classification"],
            "hidden_cases": {"H20": case_by_id["H20"]["classification"], "H21": case_by_id["H21"]["classification"]},
        },
        "correction_retraction_incremental_equals_clean": {
            "classification": "POST_SEAL_EXTERNAL_ONLY",
            "candidate_probe_result": probe_by_id["PB-DELTA-CLEAN"]["classification"],
            "hidden_case": case_by_id["H13"]["classification"],
        },
        "M01_destructive_roundtrip": {
            "classification": probe_by_id["PB-M01-DESTRUCTIVE"]["classification"],
            "decisive": True,
            "recovery_echo_forbidden": True,
        },
    }

    preliminary = {
        "schema_version": "vesmed.bridge-holdout.external-runner-b-report/1",
        "implementation": "B",
        "run_metadata": {
            "run_id": "implementation-b-corrected-run-03",
            "status": "corrected_external_run_03",
            "parent_run_02_sha256": "4908aae52466f9fbfe1892fd604afe95366bad644a920a8a2106c5198f358689",
            "lost_uncommitted_run_01_sha256": "d92cd05b2e9c0ef68380c691c1d64dfb439747dc5d8b3bc9e7664ea592e5412a",
            "run_01_artifact_preserved": False,
            "rerun_reason": "runner-only audit correction: demote incomplete full roundtrip, add root/query assertions, and fix probe attribution",
            "candidate_source_changed": False,
            "corpus_changed": False,
        },
        "evidence_policy": {
            "mechanical_hidden_cases_require_concrete_fixture_and_materialized_queries": True,
            "descriptor_only_cases_are_harness_incomplete": True,
            "post_seal_external_probes_never_promoted_to_hidden_pass_fail": True,
            "candidate_exception_is_not_typed_failure": True,
            "recovery_tape_echo_is_not_roundtrip_evidence": True,
            "candidate_input_forbidden_keys": sorted(FORBIDDEN_CANDIDATE_INPUT_KEYS),
        },
        "hashes": {
            "corpus_sha256": corpus_sha,
            "freeze_manifest_sha256": file_sha256(FREEZE_PATH),
            "implementation_b_sha256": file_sha256(IMPL_PATH),
            "runner_b_sha256": file_sha256(Path(__file__)),
        },
        "freeze_binding": {
            "freeze_commit": freeze["implementations"]["impl_b"]["introducing_commit"],
            "source_changed_after_reveal": False,
            "public_api": corpus["transport_binding"]["implementation_b"]["calls"],
        },
        "summary": {
            "corpus_cases": len(case_results),
            "mechanical_case_counts": mechanical_counts,
            "external_probe_counts": probe_counts,
            "candidate_hard_failure": probe_by_id["PB-M01-DESTRUCTIVE"]["classification"] == "CANDIDATE_FAIL",
            "holdout_complete": mechanical_counts["HARNESS_INCOMPLETE"] == 0 and mechanical_counts["HARNESS_ERROR"] == 0,
            "no_compensating_total_score": True,
        },
        "hard_assertions_by_dimension": hard_assertions,
        "cases": case_results,
        "post_seal_external_probes": probes,
        "mutation_kills": {
            "M01": {
                "classification": "NOT_KILLED" if probe_by_id["PB-M01-DESTRUCTIVE"]["classification"] == "CANDIDATE_FAIL" else "KILLED",
                "evidence": "PB-M01-DESTRUCTIVE",
            },
            "M02": {
                "classification": "NOT_EXECUTED_BY_RUNNER_B",
                "reason": "requires pairwise A/B static and runtime independence audit",
            },
            **{
                f"M{index:02d}": {
                    "classification": "NOT_EXECUTED_BY_RUNNER_B",
                    "reason": "no concrete executable mutation object is bound in this B-only runner",
                }
                for index in range(3, 13)
            },
        },
        "adapter_metrics": {
            "physical_nonblank_nonhash_loc": physical_nonblank_nonhash_loc(Path(__file__)),
            "loc_method_is_not_strict_noncomment": True,
            "closed_transform_opcodes": [
                "root_occurrence_id<->root_id",
                "fixed_epistemic_member_x_state_product_and_marginalization",
                "finite_potential_outcome_world_to_B_response_rows",
                "portable_operator/factual field renaming",
            ],
            "closed_transform_count": 4,
            "manual_semantic_commitments": {
                "likelihoods": 3,
                "unit_conversions": 0,
                "clock_policies": 0,
                "identification_assumptions": 1,
                "shared_world_policies": 1,
                "latest_version_resolvers": 0,
            },
            "latency_ns": {
                "sample_count_compile": len(compile_ns),
                "sample_count_recover": len(recover_ns),
                "sample_count_run": len(run_ns),
                "adequate_for_stable_p95": False,
                "compile_p50": percentile(compile_ns, 0.50),
                "compile_p95": percentile(compile_ns, 0.95),
                "recover_p50": percentile(recover_ns, 0.50),
                "recover_p95": percentile(recover_ns, 0.95),
                "run_p50": percentile(run_ns, 0.50),
                "run_p95": percentile(run_ns, 0.95),
            },
            "extension_blast_radius": {
                "core_candidate_files_changed": 0,
                "schema_migrations": 0,
                "new_runner_files": [str(Path(__file__).relative_to(ROOT)).replace("\\", "/")],
            },
        },
    }
    encoded = canonical_bytes(preliminary)
    preliminary["trace_metrics"] = {"report_bytes_before_trace_metrics": len(encoded), "report_json_nodes_before_trace_metrics": json_node_count(preliminary)}
    return preliminary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="write canonical machine-readable JSON here")
    parser.add_argument("--pretty", action="store_true", help="pretty-print stdout when --output is absent")
    args = parser.parse_args(argv)
    report = make_report()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(canonical_bytes(report))
        print(json.dumps({"output": str(args.output), "sha256": file_sha256(args.output), "summary": report["summary"]}, ensure_ascii=False, sort_keys=True))
    else:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

