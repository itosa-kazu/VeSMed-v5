#!/usr/bin/env python3
"""Deterministic post-seal red-team probes for the frozen bridge candidates.

This file is deliberately *not* a hidden-corpus runner.  The portable corpus
contains metadata-only mutation names for most negative cases.  Every probe in
this file is therefore labelled ``post_seal_external_probe`` and uses a small,
fully materialized input defined here after the four candidate source seals.

The runner never edits the frozen candidates.  It emits canonical machine JSON
with a hash of each probe input and observed output so the observations can be
replayed and compared byte-for-byte.
"""

from __future__ import annotations

import argparse
import ast
import copy
import dataclasses
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from prototype.bridge_holdout import impl_a, impl_b, panel_a, panel_b  # noqa: E402


SCHEMA_VERSION = "vesmed.bridge-redteam-external-probes/1"
PROVENANCE = "post_seal_external_probe"
FROZEN_PATHS = (
    "prototype/bridge_holdout/impl_a.py",
    "prototype/bridge_holdout/impl_b.py",
    "prototype/bridge_holdout/panel_a.py",
    "prototype/bridge_holdout/panel_b.py",
)


def jsonable(value: Any) -> Any:
    if dataclasses.is_dataclass(value):
        return jsonable(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(child) for child in value]
    if isinstance(value, set):
        return sorted((jsonable(child) for child in value), key=canonical_text)
    if value is None or type(value) in {str, int, float, bool}:
        if type(value) is float and not math.isfinite(value):
            raise ValueError("non-finite probe value")
        return value
    raise TypeError(f"probe value is not JSON-shaped: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def canonical_text(value: Any) -> str:
    return canonical_bytes(value).decode("utf-8")


def sha256_value(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probability(result: Mapping[str, Any], value: Any) -> float:
    return next(
        float(row["probability"])
        for row in result["distribution"]
        if json.dumps(row["value"], sort_keys=True) == json.dumps(value, sort_keys=True)
    )


def panel_value(module: Any, model: Mapping[str, Any], query: Mapping[str, Any]) -> dict[str, Any]:
    return dict(module.execute(copy.deepcopy(model), copy.deepcopy(query))["value"])


def caught(call: Callable[[], Any]) -> dict[str, Any]:
    try:
        value = call()
    except Exception as exc:  # typed candidate exceptions are part of the observation
        return {"accepted": False, "error_type": type(exc).__name__, "error": str(exc)}
    return {"accepted": True, "value": jsonable(value)}


def make_probe(
    probe_id: str,
    *,
    target: str,
    dimension: str,
    expectation: str,
    input_object: Mapping[str, Any],
    observed: Mapping[str, Any],
    verdict: str,
    reason: str,
) -> dict[str, Any]:
    if verdict not in {"pass", "fail", "partial", "evidence_gap"}:
        raise ValueError(f"invalid verdict {verdict!r}")
    normalized_input = jsonable(input_object)
    normalized_observed = jsonable(observed)
    return {
        "probe_id": probe_id,
        "provenance": PROVENANCE,
        "target": target,
        "dimension": dimension,
        "contract_expectation": expectation,
        "input": normalized_input,
        "input_sha256": sha256_value(normalized_input),
        "observed": normalized_observed,
        "observed_sha256": sha256_value(normalized_observed),
        "verdict": verdict,
        "reason": reason,
    }


def a_fixture_digest() -> str:
    return impl_a.CodecA.semantic_digest(impl_a._fixture())


def b_fixture_digest(kind: str) -> str:
    source = impl_b.demo_dbn_bundle() if kind == "dbn" else impl_b.demo_scm_bundle()
    return sha256_value(source)


def probe_static_closure() -> list[dict[str, Any]]:
    forbidden = {
        "prototype.reference_models",
        "prototype.model_subkernel",
        "prototype.bridge_holdout.impl_a",
        "prototype.bridge_holdout.impl_b",
        "prototype.bridge_holdout.panel_a",
        "prototype.bridge_holdout.panel_b",
    }
    rows: dict[str, Any] = {}
    cross_edges: list[str] = []
    dynamic_calls: list[str] = []
    for relative in FROZEN_PATHS:
        path = REPO_ROOT / relative
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        imports: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.append(node.module or "")
            elif isinstance(node, ast.Call):
                name = ""
                if isinstance(node.func, ast.Name):
                    name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    name = node.func.attr
                if name in {"eval", "exec", "__import__", "open"}:
                    dynamic_calls.append(f"{relative}:{getattr(node, 'lineno', 0)}:{name}")
        rows[relative] = {"imports": sorted(imports), "sha256": sha256_file(path)}
        for imported in imports:
            if imported in forbidden and not relative.endswith(imported.rsplit(".", 1)[-1] + ".py"):
                cross_edges.append(f"{relative}->{imported}")
    observed = {"files": rows, "forbidden_cross_edges": cross_edges, "dynamic_calls": dynamic_calls}
    return [
        make_probe(
            "STATIC_M02_CLOSURE",
            target="all_frozen_sources",
            dimension="M02_shared_executable_helper",
            expectation="stdlib-only closure; no candidate/reference cross-import or dynamic loader",
            input_object={"paths": list(FROZEN_PATHS), "forbidden": sorted(forbidden)},
            observed=observed,
            verdict="pass" if not cross_edges and not dynamic_calls else "fail",
            reason="AST import/call graph is closed" if not cross_edges and not dynamic_calls else "forbidden dependency edge found",
        )
    ]


def probe_a_m01() -> list[dict[str, Any]]:
    source = impl_a._fixture()
    native = impl_a.compile_bundle(source, "finite_dbn")
    base = impl_a.execute(native, "q-filter")

    target_mutation = copy.deepcopy(native)
    model = target_mutation["native_model"]
    first_from, first_to = model["slices"][:2]
    for row in model["transitions"]:
        if row["from_slice"] == first_from and row["to_slice"] == first_to:
            row["probability"] = 0.5
    recovered_candidate = impl_a._normalized_bundle(impl_a._recover_unchecked(target_mutation))
    target_mutation["semantic_digest"] = impl_a._digest(recovered_candidate)
    changed = impl_a.execute(target_mutation, "q-filter")
    recovered = impl_a.recover_bundle(target_mutation)
    target_observed = {
        "base_p1": probability(base, 1),
        "mutated_p1": probability(changed, 1),
        "execution_changed": base["distribution"] != changed["distribution"],
        "recovery_reflects_target_mutation": recovered["models"]["finite_dbn"] != source["models"]["finite_dbn"],
    }

    sidecar_mutation = copy.deepcopy(native)
    sidecar_mutation["other_model_registry_entry"]["coverage_contract"]["population"] = "MUTATED-UNEXECUTED"
    sidecar_recovered = impl_a._normalized_bundle(impl_a._recover_unchecked(sidecar_mutation))
    sidecar_mutation["semantic_digest"] = impl_a._digest(sidecar_recovered)
    sidecar_result = impl_a.execute(sidecar_mutation, "q-filter")
    sidecar_roundtrip = impl_a.recover_bundle(sidecar_mutation)
    sidecar_observed = {
        "execution_unchanged": sidecar_result["distribution"] == base["distribution"],
        "recovered_unexecuted_value": sidecar_roundtrip["models"]["finite_scm"]["coverage_contract"]["population"],
        "unexecuted_other_model_carried": True,
    }

    desync = copy.deepcopy(native)
    next(row for row in desync["evidence_table"] if row["statement_id"] == "s-y0")["measurement"] = {
        "kind": "exact",
        "value": 0,
    }
    desync["semantic_digest"] = impl_a._digest(impl_a._normalized_bundle(impl_a._recover_unchecked(desync)))
    desync_observed = caught(lambda: impl_a.execute(desync, "q-filter"))
    return [
        make_probe(
            "A_M01_TARGET_NATIVE_LINK",
            target="impl_a",
            dimension="M01_canonical_echo",
            expectation="mutating executable native transition changes execution and recovered target semantics",
            input_object={"fixture_digest": a_fixture_digest(), "mutation": "first transition block rows -> [0.5,0.5]"},
            observed=target_observed,
            verdict="pass" if all(target_observed[key] for key in ("execution_changed", "recovery_reflects_target_mutation")) else "fail",
            reason="target native model is linked to both execution and recovery",
        ),
        make_probe(
            "A_M01_UNEXECUTED_SIDECAR",
            target="impl_a",
            dimension="M01_canonical_echo",
            expectation="positive full-bundle roundtrip must not be mistaken for execution of uncompiled semantic fields",
            input_object={"fixture_digest": a_fixture_digest(), "mutation": "other_model_registry_entry only"},
            observed=sidecar_observed,
            verdict="partial",
            reason="target model is real, but the other model is recovered from an unexecuted readable carrier",
        ),
        make_probe(
            "A_M01_EVIDENCE_DERIVATION_GUARD",
            target="impl_a",
            dimension="M01_canonical_echo",
            expectation="authority evidence and compiled model input cannot silently desynchronize",
            input_object={"fixture_digest": a_fixture_digest(), "mutation": "evidence_table measurement only"},
            observed=desync_observed,
            verdict="pass" if not desync_observed["accepted"] else "fail",
            reason="derived model_input_table cross-check rejects a copied-table desynchronization",
        ),
    ]


def probe_b_m01() -> list[dict[str, Any]]:
    source = impl_b.demo_dbn_bundle()
    native = impl_b.compile_bundle(source, "finite_dbn")
    query = {"kind": "filter", "target": "state", "target_slice": 0}
    base = impl_b.execute(native, query)
    mutated = dataclasses.replace(native, native_ir=dataclasses.replace(native.native_ir, prior=(0.99, 0.01)))
    changed = impl_b.execute(mutated, query)
    recovered = impl_b.recover_bundle(mutated)
    observed = {
        "recovered_equal_original": recovered == source,
        "semantic_digest_unchanged": mutated.semantic_digest == native.semantic_digest,
        "execution_changed": base["distribution"] != changed["distribution"],
        "base_distribution": base["distribution"],
        "mutated_distribution": changed["distribution"],
    }
    return [
        make_probe(
            "B_M01_OPAQUE_TAPE_DESYNC",
            target="impl_b",
            dimension="M01_canonical_echo",
            expectation="native semantic mutation must invalidate or change recovery",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "mutation": "native prior -> [0.99,0.01], tape untouched"},
            observed=observed,
            verdict="fail" if observed["recovered_equal_original"] and observed["execution_changed"] else "pass",
            reason="opaque recovery tape returns the old canonical source while native execution semantics changed",
        )
    ]


def probe_future_filter_smooth() -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    source_a = impl_a._fixture()
    base_a = impl_a.compile_bundle(source_a, "finite_dbn")
    flipped_a = copy.deepcopy(source_a)
    late_record = next(row for row in flipped_a["evidence_history"] if row["statement_id"] == "s-y2")
    late_record["measurement"] = {"kind": "exact", "value": 1}
    late_root = next(row for row in flipped_a["roots"] if row["occurrence_id"] == "r-y2")
    late_root["raw_payload"] = {"Y": 1}
    late_root["raw_digest"] = impl_a._digest(late_root["raw_payload"])
    changed_a = impl_a.compile_bundle(flipped_a, "finite_dbn")
    a_filter_0, a_filter_1 = impl_a.execute(base_a, "q-filter"), impl_a.execute(changed_a, "q-filter")
    a_smooth_0, a_smooth_1 = impl_a.execute(base_a, "q-smooth"), impl_a.execute(changed_a, "q-smooth")
    observed_a = {
        "filter_unchanged": a_filter_0["distribution"] == a_filter_1["distribution"],
        "smooth_changed": a_smooth_0["distribution"] != a_smooth_1["distribution"],
        "filter_future_used": a_filter_0["native_witness"]["future_evidence_used"],
        "smooth_future_used": a_smooth_0["native_witness"]["future_evidence_used"],
    }
    probes.append(
        make_probe(
            "A_M03_M04_FILTER_SMOOTH",
            target="impl_a",
            dimension="M03_future_filter_and_M04_smooth_liveness",
            expectation="late observation mutation leaves filter fixed and changes smooth",
            input_object={"fixture_digest": a_fixture_digest(), "mutation": "s-y2 exact 0 -> 1"},
            observed=observed_a,
            verdict="pass" if observed_a["filter_unchanged"] and observed_a["smooth_changed"] else "fail",
            reason="forward filter and retrospective smoother are behaviorally separated",
        )
    )

    source_b = impl_b.demo_dbn_bundle()
    base_b = impl_b.compile_bundle(source_b, "finite_dbn")
    flipped_b = copy.deepcopy(source_b)
    flipped_b["evidence"][1]["likelihood"] = {"well": 0.9, "ill": 0.1}
    changed_b = impl_b.compile_bundle(flipped_b, "finite_dbn")
    q_filter = {"kind": "filter", "target": "state", "target_slice": 0}
    q_smooth = {
        "kind": "smooth",
        "target": "state",
        "target_slice": 0,
        "evidence_through": 1,
        "later_evidence_policy": "allow-visible-later-evidence",
    }
    b_filter_0, b_filter_1 = impl_b.execute(base_b, q_filter), impl_b.execute(changed_b, q_filter)
    b_smooth_0, b_smooth_1 = impl_b.execute(base_b, q_smooth), impl_b.execute(changed_b, q_smooth)
    observed_b = {
        "filter_unchanged": b_filter_0["distribution"] == b_filter_1["distribution"],
        "smooth_changed": b_smooth_0["distribution"] != b_smooth_1["distribution"],
        "filter_future_used": b_filter_0["witness"]["future_evidence_used"],
        "smooth_future_used": b_smooth_0["witness"]["future_evidence_used"],
    }
    probes.append(
        make_probe(
            "B_M03_M04_FILTER_SMOOTH",
            target="impl_b",
            dimension="M03_future_filter_and_M04_smooth_liveness",
            expectation="late observation mutation leaves filter fixed and changes smooth",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "mutation": "late likelihood swap"},
            observed=observed_b,
            verdict="pass" if observed_b["filter_unchanged"] and observed_b["smooth_changed"] else "fail",
            reason="forward filter and backward smoother are behaviorally separated",
        )
    )
    return probes


def probe_target_window() -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    source_a = impl_a._fixture()
    native_a = impl_a.compile_bundle(source_a, "finite_dbn")
    wrong_target_a = {"query_id": "wrong-target", "kind": "filter", "target": "NOT_X", "at": "2026-01-01T01:00:00Z"}
    target_a = caught(lambda: impl_a.execute(native_a, wrong_target_a))
    probes.append(
        make_probe(
            "A_H31_TARGET_BINDING",
            target="impl_a",
            dimension="query_target_binding",
            expectation="unknown DBN target is rejected before posterior production",
            input_object={"fixture_digest": a_fixture_digest(), "query": wrong_target_a},
            observed=target_a,
            verdict="fail" if target_a["accepted"] else "pass",
            reason="DBN query.target is ignored" if target_a["accepted"] else "unknown target rejected",
        )
    )
    outside_a = copy.deepcopy(source_a)
    outside_a["temporal_cut"]["target_window"]["end"] = "2026-01-01T00:00:00Z"
    native_outside_a = impl_a.compile_bundle(outside_a, "finite_dbn")
    result_outside_a = caught(lambda: impl_a.execute(native_outside_a, "q-filter"))
    probes.append(
        make_probe(
            "A_H39_TARGET_WINDOW",
            target="impl_a",
            dimension="query_target_window",
            expectation="query at 01:00 is rejected when frozen target window ends at 00:00",
            input_object={"fixture_digest": impl_a.CodecA.semantic_digest(outside_a), "query_id": "q-filter"},
            observed=result_outside_a,
            verdict="fail" if result_outside_a["accepted"] else "pass",
            reason="query time is not bound to TemporalCut.target_window",
        )
    )

    source_b = impl_b.demo_dbn_bundle()
    native_b = impl_b.compile_bundle(source_b, "finite_dbn")
    query_b = {"kind": "filter", "target": "NOT_THE_STATE", "target_slice": 0}
    target_b = caught(lambda: impl_b.execute(native_b, query_b))
    probes.append(
        make_probe(
            "B_H31_TARGET_BINDING",
            target="impl_b",
            dimension="query_target_binding",
            expectation="unknown DBN target is rejected before posterior production",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "query": query_b},
            observed=target_b,
            verdict="fail" if target_b["accepted"] else "pass",
            reason="DBN target is only echoed, not bound to native state",
        )
    )
    outside_b = copy.deepcopy(source_b)
    outside_b["temporal_cut"]["target_window"] = [1, 1]
    native_outside_b = impl_b.compile_bundle(outside_b, "finite_dbn")
    query_outside_b = {"kind": "filter", "target": "state", "target_slice": 0}
    result_outside_b = caught(lambda: impl_b.execute(native_outside_b, query_outside_b))
    probes.append(
        make_probe(
            "B_H39_TARGET_WINDOW",
            target="impl_b",
            dimension="query_target_window",
            expectation="target_slice=0 is rejected when frozen target window is [1,1]",
            input_object={"fixture_digest": sha256_value(outside_b), "query": query_outside_b},
            observed=result_outside_b,
            verdict="fail" if result_outside_b["accepted"] else "pass",
            reason="target_window sidecar is not consulted by DBN execution",
        )
    )
    return probes


def probe_duplicate_dependence() -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    source_a = impl_a._fixture()
    base_a = impl_a.execute(impl_a.compile_bundle(source_a, "finite_dbn"), "q-filter")
    same_root_a = copy.deepcopy(source_a)
    alias = copy.deepcopy(same_root_a["evidence_history"][0])
    alias.update({"statement_id": "s-y0-alias", "logical_id": "s-y0-alias", "proof": {"kind": "alias"}})
    same_root_a["evidence_history"].append(alias)
    same_root_result_a = impl_a.execute(impl_a.compile_bundle(same_root_a, "finite_dbn"), "q-filter")

    same_family_a = copy.deepcopy(source_a)
    peer_root = copy.deepcopy(same_family_a["roots"][0])
    peer_root.update({"occurrence_id": "r-y0-peer", "artifact_id": "artifact-r-y0-peer"})
    peer_root["raw_digest"] = impl_a._digest(peer_root["raw_payload"])
    same_family_a["roots"].append(peer_root)
    peer_record = copy.deepcopy(same_family_a["evidence_history"][0])
    peer_record.update({"statement_id": "s-y0-peer", "logical_id": "s-y0-peer", "proof": {"kind": "same-family-peer"}})
    peer_record["root_refs"] = [{"occurrence_id": "r-y0-peer", "version": "1"}]
    same_family_a["evidence_history"].append(peer_record)
    same_family_result_a = impl_a.execute(impl_a.compile_bundle(same_family_a, "finite_dbn"), "q-filter")
    observed_a = {
        "base_p1": probability(base_a, 1),
        "same_root_p1": probability(same_root_result_a, 1),
        "same_family_p1": probability(same_family_result_a, 1),
        "same_root_used_statement_count": len(same_root_result_a["used_evidence"]["statement_ids"]),
        "same_root_used_root_count": len(same_root_result_a["used_evidence"]["root_refs"]),
    }
    probes.append(
        make_probe(
            "A_H32_ROOT_DEPENDENCE_IDEMPOTENCE",
            target="impl_a",
            dimension="M09_path_count_and_dependence",
            expectation="same-root alias is idempotent; same-family duplicate is jointly modeled or rejected",
            input_object={"fixture_digest": a_fixture_digest(), "mutations": ["same root alias", "distinct root same dependence family"]},
            observed=observed_a,
            verdict="fail" if observed_a["base_p1"] != observed_a["same_root_p1"] or observed_a["base_p1"] != observed_a["same_family_p1"] else "pass",
            reason="record likelihoods are multiplied without root/dependence-family semantics",
        )
    )

    source_b = impl_b.demo_dbn_bundle()
    base_native_b = impl_b.compile_bundle(source_b, "finite_dbn")
    query_b = {"kind": "filter", "target": "state", "target_slice": 0}
    base_b = impl_b.execute(base_native_b, query_b)
    same_root_b = copy.deepcopy(source_b)
    alias_b = copy.deepcopy(same_root_b["evidence"][0])
    alias_b.update({"record_id": "obs-early-alias", "logical_id": "obs-early-alias"})
    same_root_b["evidence"].append(alias_b)
    same_root_result_b = impl_b.execute(impl_b.compile_bundle(same_root_b, "finite_dbn"), query_b)
    same_family_b = copy.deepcopy(source_b)
    root_peer_b = copy.deepcopy(same_family_b["roots"][0])
    root_peer_b.update({"root_id": "root-early-peer", "logical_id": "early-lab-peer"})
    same_family_b["roots"].append(root_peer_b)
    record_peer_b = copy.deepcopy(same_family_b["evidence"][0])
    record_peer_b.update({"record_id": "obs-early-peer", "logical_id": "obs-early-peer", "root_ids": ["root-early-peer"]})
    same_family_b["evidence"].append(record_peer_b)
    same_family_result_b = impl_b.execute(impl_b.compile_bundle(same_family_b, "finite_dbn"), query_b)
    observed_b = {
        "base_ill": probability(base_b, "ill"),
        "same_root_ill": probability(same_root_result_b, "ill"),
        "same_family_ill": probability(same_family_result_b, "ill"),
        "same_root_native_address_count": len(same_root_result_b["witness"]["native_addresses"]),
        "same_root_used_root_count": len(same_root_result_b["used_roots"]),
    }
    probes.append(
        make_probe(
            "B_H32_ROOT_DEPENDENCE_IDEMPOTENCE",
            target="impl_b",
            dimension="M09_path_count_and_dependence",
            expectation="same-root alias is idempotent; same-family duplicate is jointly modeled or rejected",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "mutations": ["same root alias", "distinct root same dependence family"]},
            observed=observed_b,
            verdict="fail" if observed_b["base_ill"] != observed_b["same_root_ill"] or observed_b["base_ill"] != observed_b["same_family_ill"] else "pass",
            reason="native emission columns are multiplied by path, not root/dependence identity",
        )
    )
    return probes


def make_a_postcut_correction(source: Mapping[str, Any]) -> dict[str, Any]:
    new_root = copy.deepcopy(source["roots"][0])
    new_root.update(
        {
            "occurrence_id": "r-y0-corrected",
            "version": "2",
            "artifact_id": "artifact-r-y0-corrected",
            "artifact_version": "2",
            "raw_payload": {"Y": 0},
        }
    )
    new_root["raw_digest"] = impl_a._digest(new_root["raw_payload"])
    new_record = copy.deepcopy(source["evidence_history"][0])
    new_record.update(
        {
            "statement_id": "s-y0-v2",
            "logical_id": "s-y0",
            "version": "2",
            "measurement": {"kind": "exact", "value": 0},
            "root_refs": [{"occurrence_id": "r-y0-corrected", "version": "2"}],
            "proof": {"kind": "correction"},
            "supersedes": {"logical_id": "s-y0", "version": "1"},
        }
    )
    return {
        "kind": "correct",
        "delta_id": "post-cut-correction",
        "registered_at": "2026-01-01T04:00:00Z",
        "reason": "post-cut probe",
        "old_statement": {"logical_id": "s-y0", "version": "1"},
        "new_root": new_root,
        "new_record": new_record,
    }


def probe_postcut_delta() -> list[dict[str, Any]]:
    source_a = impl_a._fixture()
    native_a = impl_a.compile_bundle(source_a, "finite_dbn")
    base_a = impl_a.execute(native_a, "q-filter")
    delta_a = make_a_postcut_correction(source_a)
    changed_a_native = impl_a.apply_delta(native_a, delta_a)
    changed_a = impl_a.execute(changed_a_native, "q-filter")
    observed_a = {
        "transaction_cut": source_a["temporal_cut"]["transaction_revision_cut"],
        "delta_registered_at": delta_a["registered_at"],
        "base_p1": probability(base_a, 1),
        "post_delta_p1": probability(changed_a, 1),
        "new_statement_active": "s-y0-v2" in changed_a_native["active_statement_ids"],
    }

    source_b = impl_b.demo_dbn_bundle()
    native_b = impl_b.compile_bundle(source_b, "finite_dbn")
    query_b = {"kind": "filter", "target": "state", "target_slice": 0}
    base_b = impl_b.execute(native_b, query_b)
    new_record_b = {
        "record_id": "obs-early-v2",
        "logical_id": "obs-early",
        "version": "2",
        "slice": 0,
        "available_at": 0,
        "variable": "marker",
        "value": "negative",
        "root_ids": ["root-new"],
        "likelihood": {"well": 0.1, "ill": 0.9},
        "uncertainty": {"kind": "assay_likelihood", "version": "u-2"},
    }
    delta_b = {
        "kind": "Corrects",
        "old": "obs-early-v1",
        "new_record": new_record_b,
        "new_root": {"root_id": "root-new", "root_version": "2", "logical_id": "early-lab"},
    }
    changed_b_native = impl_b.apply_delta(native_b, delta_b)
    changed_b = impl_b.execute(changed_b_native, query_b)
    observed_b = {
        "transaction_cut": impl_b._mapping_from_frozen(native_b.temporal_cut_sidecar, "cut")["transaction_revision_cut"],
        "delta_has_registration_clock": False,
        "new_record_transaction_revision": changed_b_native.native_ir.evidence_columns[-1].transaction_revision,
        "base_ill": probability(base_b, "ill"),
        "post_delta_ill": probability(changed_b, "ill"),
    }
    return [
        make_probe(
            "A_H33_POSTCUT_CORRECTION",
            target="impl_a",
            dimension="post_transaction_delta",
            expectation="correction registered after frozen transaction cut is invisible at old cut",
            input_object={"fixture_digest": a_fixture_digest(), "delta": delta_a},
            observed=observed_a,
            verdict="fail" if observed_a["base_p1"] != observed_a["post_delta_p1"] else "pass",
            reason="backdated new_record.supersedes bypasses delta registration eligibility",
        ),
        make_probe(
            "B_H33_POSTCUT_CORRECTION",
            target="impl_b",
            dimension="post_transaction_delta",
            expectation="correction has a transaction registration/revision and cannot alter an older frozen cut",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "delta": delta_b},
            observed=observed_b,
            verdict="fail" if observed_b["base_ill"] != observed_b["post_delta_ill"] else "pass",
            reason="delta schema has no registration clock and a revision-less replacement is immediately eligible",
        ),
    ]


def probe_supersedes() -> list[dict[str, Any]]:
    source_a = impl_a._fixture()
    self_a = copy.deepcopy(source_a)
    self_a["evidence_history"][0]["supersedes"] = {"logical_id": "s-y0", "version": "1"}
    observed_a = caught(lambda: impl_a.compile_bundle(self_a, "finite_dbn"))
    if observed_a["accepted"]:
        native = impl_a.compile_bundle(self_a, "finite_dbn")
        observed_a = {"accepted": True, "self_statement_active": "s-y0" in native["active_statement_ids"]}

    source_b = impl_b.demo_dbn_bundle()
    self_b = copy.deepcopy(source_b)
    self_b["evidence"][0]["supersedes"] = {"logical_id": "obs-early", "version": "1"}
    observed_b = caught(lambda: impl_b.compile_bundle(self_b, "finite_dbn"))
    if observed_b["accepted"]:
        observed_b = {"accepted": True, "compiled_column_count": len(impl_b.compile_bundle(self_b, "finite_dbn").native_ir.evidence_columns)}
    return [
        make_probe(
            "A_H34_SELF_SUPERSEDES",
            target="impl_a",
            dimension="supersedes_graph",
            expectation="self-supersedes is rejected as an invalid version graph",
            input_object={"fixture_digest": a_fixture_digest(), "edge": "s-y0@1 -> s-y0@1"},
            observed=observed_a,
            verdict="fail" if observed_a["accepted"] else "pass",
            reason="self edge is accepted and silently removes its own statement",
        ),
        make_probe(
            "B_H34_SELF_SUPERSEDES",
            target="impl_b",
            dimension="supersedes_graph",
            expectation="self-supersedes is rejected as an invalid version graph",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "edge": "obs-early@1 -> obs-early@1"},
            observed=observed_b,
            verdict="fail" if observed_b["accepted"] else "pass",
            reason="supersedes metadata is not parsed as a version graph",
        ),
    ]


def probe_scope() -> list[dict[str, Any]]:
    source_a = impl_a._fixture()
    mismatched_a = copy.deepcopy(source_a)
    mismatched_a["evidence_history"][0]["scope"]["encounter_id"] = "enc-other"
    observed_a = caught(lambda: impl_a.compile_bundle(mismatched_a, "finite_dbn"))

    source_b = impl_b.demo_dbn_bundle()
    mismatched_b = copy.deepcopy(source_b)
    mismatched_b["scope"] = {"subject_id": "patient-A", "encounter_id": "enc-A"}
    mismatched_b["evidence"][0]["scope"] = {"subject_id": "patient-B", "encounter_id": "enc-B"}
    observed_b = caught(lambda: impl_b.compile_bundle(mismatched_b, "finite_dbn"))
    return [
        make_probe(
            "A_H36_ENCOUNTER_SCOPE",
            target="impl_a",
            dimension="scope_binding",
            expectation="same subject but other encounter is rejected",
            input_object={"fixture_digest": a_fixture_digest(), "record_encounter": "enc-other"},
            observed=observed_a,
            verdict="fail" if observed_a["accepted"] else "pass",
            reason="only subject_id is compared",
        ),
        make_probe(
            "B_H36_SUBJECT_SCOPE",
            target="impl_b",
            dimension="scope_binding",
            expectation="cross-subject/cross-encounter evidence is rejected",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "bundle_subject": "patient-A", "record_subject": "patient-B"},
            observed=observed_b,
            verdict="fail" if observed_b["accepted"] else "pass",
            reason="scope is carried only in raw record metadata and is not validated",
        ),
    ]


def probe_absent_censored() -> list[dict[str, Any]]:
    source = impl_a._fixture()
    present_censor = copy.deepcopy(source)
    present_censor["evidence_history"][0]["measurement"] = {"kind": "below_detection", "limit": 0.5}
    present_censor["evidence_history"][0]["information_state"] = "present"
    typed_censor = copy.deepcopy(present_censor)
    typed_censor["evidence_history"][0]["information_state"] = "censored_low"
    present_result = impl_a.execute(impl_a.compile_bundle(present_censor, "finite_dbn"), "q-filter")
    censor_result = impl_a.execute(impl_a.compile_bundle(typed_censor, "finite_dbn"), "q-filter")

    present_absent = copy.deepcopy(source)
    present_absent["evidence_history"][0].update(
        {"measurement": {"kind": "exact", "value": 0}, "information_state": "present"}
    )
    typed_absent = copy.deepcopy(present_absent)
    typed_absent["evidence_history"][0]["information_state"] = "absent"
    present_absent_result = impl_a.execute(impl_a.compile_bundle(present_absent, "finite_dbn"), "q-filter")
    absent_result = impl_a.execute(impl_a.compile_bundle(typed_absent, "finite_dbn"), "q-filter")
    observed_a = {
        "below_detection_present_p1": probability(present_result, 1),
        "censored_low_p1": probability(censor_result, 1),
        "censored_used": "s-y0" in censor_result["used_evidence"]["statement_ids"],
        "exact_zero_present_p1": probability(present_absent_result, 1),
        "absent_p1": probability(absent_result, 1),
        "absent_used": "s-y0" in absent_result["used_evidence"]["statement_ids"],
    }

    source_b1 = impl_b.demo_dbn_bundle()
    source_b2 = copy.deepcopy(source_b1)
    source_b1["evidence"][0]["uncertainty"] = {
        "kind": "pmf",
        "masses": [{"value": 0, "p": 0.5}, {"value": 2, "p": 0.5}],
        "mean": 1,
    }
    source_b2["evidence"][0]["uncertainty"] = {
        "kind": "pmf",
        "masses": [{"value": 1, "p": 1.0}],
        "mean": 1,
    }
    query_b = {"kind": "filter", "target": "state", "target_slice": 0}
    native_b1 = impl_b.compile_bundle(source_b1, "finite_dbn")
    native_b2 = impl_b.compile_bundle(source_b2, "finite_dbn")
    result_b1, result_b2 = impl_b.execute(native_b1, query_b), impl_b.execute(native_b2, query_b)
    observed_b = {
        "typed_uncertainty_distinct_in_native": native_b1.native_ir.evidence_columns[0].uncertainty
        != native_b2.native_ir.evidence_columns[0].uncertainty,
        "execution_distribution_equal": result_b1["distribution"] == result_b2["distribution"],
        "likelihood_column_equal": native_b1.native_ir.evidence_columns[0].likelihood
        == native_b2.native_ir.evidence_columns[0].likelihood,
    }
    return [
        make_probe(
            "A_H38_ABSENT_CENSORED_LIVENESS",
            target="impl_a",
            dimension="M07_measurement_uncertainty_liveness",
            expectation="absent/censored evidence is executed or typed unsupported, never silently skipped to a green prior",
            input_object={"fixture_digest": a_fixture_digest(), "variants": ["absent exact-zero", "censored_low below_detection(0.5)"]},
            observed=observed_a,
            verdict="fail" if not observed_a["absent_used"] and not observed_a["censored_used"] else "pass",
            reason="both typed variants are silently skipped and return prior-driven posteriors",
        ),
        make_probe(
            "B_M07_UNCERTAINTY_LIVENESS",
            target="impl_b",
            dimension="M07_measurement_uncertainty_liveness",
            expectation="same-mean different-support PMFs affect a declared semantic path or are typed unsupported",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "variants": ["0/2 mixture mean=1", "point mass 1 mean=1"]},
            observed=observed_b,
            verdict="fail" if observed_b["typed_uncertainty_distinct_in_native"] and observed_b["execution_distribution_equal"] else "pass",
            reason="uncertainty is copied to an audit field but execution consumes only a separately pre-flattened likelihood",
        ),
    ]


def probe_a_uncertainty_positive() -> list[dict[str, Any]]:
    source = impl_a._fixture()
    # Use the existing binary observation model.  Two categorical likelihoods
    # with different support produce different native likelihoods; neither is
    # replaced by a scalar mean.
    left = copy.deepcopy(source)
    right = copy.deepcopy(source)
    left["evidence_history"][0]["measurement"] = {
        "kind": "categorical_likelihood",
        "entries": [{"value": 0, "likelihood": 0.8}, {"value": 1, "likelihood": 0.2}],
    }
    right["evidence_history"][0]["measurement"] = {
        "kind": "categorical_likelihood",
        "entries": [{"value": 0, "likelihood": 0.2}, {"value": 1, "likelihood": 0.8}],
    }
    native_left = impl_a.compile_bundle(left, "finite_dbn")
    native_right = impl_a.compile_bundle(right, "finite_dbn")
    result_left = impl_a.execute(native_left, "q-filter")
    result_right = impl_a.execute(native_right, "q-filter")
    observed = {
        "left_p1": probability(result_left, 1),
        "right_p1": probability(result_right, 1),
        "distribution_distinct": result_left["distribution"] != result_right["distribution"],
        "roundtrip_left_kind": impl_a.recover_bundle(native_left)["evidence_history"][0]["measurement"]["kind"],
        "roundtrip_right_kind": impl_a.recover_bundle(native_right)["evidence_history"][0]["measurement"]["kind"],
    }
    return [
        make_probe(
            "A_M07_CATEGORICAL_LIVENESS_CONTROL",
            target="impl_a",
            dimension="M07_measurement_uncertainty_liveness",
            expectation="categorical likelihood support remains typed and changes execution",
            input_object={"fixture_digest": a_fixture_digest(), "likelihoods": [[0.8, 0.2], [0.2, 0.8]]},
            observed=observed,
            verdict="pass" if observed["distribution_distinct"] else "fail",
            reason="categorical likelihood is a live semantic value; censor/information-state handling fails separately",
        )
    ]


def probe_namespace_empty_family() -> list[dict[str, Any]]:
    source_a = impl_a._fixture()
    collision_a = copy.deepcopy(source_a)
    model_a = collision_a["models"]["finite_scm"]
    for world in model_a["exogenous_worlds"]:
        world["values"]["H"] = world["values"].pop("U")
    for case in model_a["equations"][0]["cases"]:
        case["when"]["H"] = case["when"].pop("U")
    observed_collision_a = caught(lambda: impl_a.compile_bundle(collision_a, "finite_scm"))
    empty_a = copy.deepcopy(source_a)
    empty_a["roots"][0]["dependence_families"] = []
    observed_empty_a = caught(lambda: impl_a.compile_bundle(empty_a, "finite_dbn"))

    source_b = impl_b.demo_scm_bundle()
    collision_b = copy.deepcopy(source_b)
    for world in collision_b["model"]["worlds"]:
        world["exogenous"] = {"T": world["exogenous"]["R"]}
    observed_collision_b = caught(lambda: impl_b.compile_bundle(collision_b, "finite_scm"))
    empty_b = impl_b.demo_dbn_bundle()
    empty_b["roots"][0]["dependence_families"] = []
    observed_empty_b = caught(lambda: impl_b.compile_bundle(empty_b, "finite_dbn"))
    return [
        make_probe(
            "A_H40_CAUSAL_NAMESPACE",
            target="impl_a",
            dimension="causal_namespace_collision",
            expectation="same exogenous/endogenous symbol is rejected",
            input_object={"fixture_digest": a_fixture_digest(), "collision": "H exogenous and endogenous"},
            observed=observed_collision_a,
            verdict="fail" if observed_collision_a["accepted"] else "pass",
            reason="SCM validator allows exogenous names to shadow endogenous names",
        ),
        make_probe(
            "B_H40_CAUSAL_NAMESPACE",
            target="impl_b",
            dimension="causal_namespace_collision",
            expectation="same exogenous/endogenous symbol is rejected",
            input_object={"fixture_digest": b_fixture_digest("scm"), "collision": "T in world.exogenous and factual variables"},
            observed=observed_collision_b,
            verdict="fail" if observed_collision_b["accepted"] else "pass",
            reason="finite response-world compiler accepts namespace collision metadata",
        ),
        make_probe(
            "A_H41_EMPTY_DEPENDENCE_FAMILY",
            target="impl_a",
            dimension="dependence_family_presence",
            expectation="empty dependence-family set is rejected",
            input_object={"fixture_digest": a_fixture_digest(), "dependence_families": []},
            observed=observed_empty_a,
            verdict="fail" if observed_empty_a["accepted"] else "pass",
            reason="root validator checks member shape but not non-empty cardinality",
        ),
        make_probe(
            "B_H41_EMPTY_DEPENDENCE_FAMILY",
            target="impl_b",
            dimension="dependence_family_presence",
            expectation="empty dependence-family set is rejected",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "dependence_families": []},
            observed=observed_empty_b,
            verdict="fail" if observed_empty_b["accepted"] else "pass",
            reason="dependence family metadata is not validated",
        ),
    ]


def probe_versions_roots_bridge() -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    source_a = impl_a._fixture()
    base_a = impl_a.execute(impl_a.compile_bundle(source_a, "finite_dbn"), "q-filter")
    tags_a = copy.deepcopy(source_a)
    tags_a["version_vector"].update(
        {"adapter": "bogus-adapter", "terminology": "bogus-term", "knowledge": "bogus-knowledge", "policy": "bogus-policy", "solver": "bogus-solver"}
    )
    result_a = impl_a.execute(impl_a.compile_bundle(tags_a, "finite_dbn"), "q-filter")
    observed_a = {
        "distribution_equal": base_a["distribution"] == result_a["distribution"],
        "reported_versions": result_a["used_evidence"]["version_vector"],
    }
    probes.append(
        make_probe(
            "A_M10_VERSION_BEHAVIOR_BINDING",
            target="impl_a",
            dimension="M10_version_binding",
            expectation="adapter/terminology/knowledge/policy/solver versions bind executable behavior or resolve via frozen registries",
            input_object={"fixture_digest": a_fixture_digest(), "version_mutation": tags_a["version_vector"]},
            observed=observed_a,
            verdict="fail" if observed_a["distribution_equal"] else "pass",
            reason="non-model version tags are echoed without a behavioral registry fingerprint",
        )
    )

    source_b = impl_b.demo_dbn_bundle()
    base_b_native = impl_b.compile_bundle(source_b, "finite_dbn")
    query_b = {"kind": "filter", "target": "state", "target_slice": 0}
    base_b = impl_b.execute(base_b_native, query_b)
    tags_b = copy.deepcopy(source_b)
    tags_b["versions"] = {
        "evidence_authority": "latest-bogus",
        "knowledge": "wrong-k",
        "model": "unrelated-model-999",
        "solver": "oracle-name-only",
    }
    result_b = impl_b.execute(impl_b.compile_bundle(tags_b, "finite_dbn"), query_b)
    observed_b = {
        "distribution_equal": base_b["distribution"] == result_b["distribution"],
        "reported_versions": result_b["witness"]["versions"],
    }
    probes.append(
        make_probe(
            "B_M10_VERSION_BEHAVIOR_BINDING",
            target="impl_b",
            dimension="M10_version_binding",
            expectation="reported version vector binds compiled/executed behavior",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "version_mutation": tags_b["versions"]},
            observed=observed_b,
            verdict="fail" if observed_b["distribution_equal"] else "pass",
            reason="arbitrary version tags are copied to witness without checking model/solver behavior",
        )
    )

    coexisting = copy.deepcopy(source_b)
    v2 = copy.deepcopy(coexisting["roots"][0])
    v2.update({"root_version": "2", "logical_id": "early-lab-v2"})
    coexisting["roots"].append(v2)
    coexist_observed = caught(lambda: impl_b.compile_bundle(coexisting, "finite_dbn"))
    version_ref = copy.deepcopy(source_b)
    version_ref["evidence"][0]["root_ids"] = [{"root_id": "root-early", "root_version": "1"}]
    native_ref = impl_b.compile_bundle(version_ref, "finite_dbn")
    ref_observed = {"compiled_root_reference": list(native_ref.native_ir.evidence_columns[0].root_ids)}
    probes.extend(
        [
            make_probe(
                "B_M10_ROOT_VERSION_COEXISTENCE",
                target="impl_b",
                dimension="M10_version_binding",
                expectation="same occurrence id at old/new versions can coexist as distinct root identities",
                input_object={"fixture_digest": b_fixture_digest("dbn"), "roots": [["root-early", "1"], ["root-early", "2"]]},
                observed=coexist_observed,
                verdict="fail" if not coexist_observed["accepted"] else "pass",
                reason="root registry is keyed only by root_id, so old/new versions cannot coexist",
            ),
            make_probe(
                "B_M08_ROOT_REFERENCE_VERSION",
                target="impl_b",
                dimension="M08_raw_root_identity",
                expectation="compiled evidence reference retains occurrence and version",
                input_object={"fixture_digest": b_fixture_digest("dbn"), "root_ref": ["root-early", "1"]},
                observed=ref_observed,
                verdict="fail" if ref_observed["compiled_root_reference"] == ["root-early"] else "pass",
                reason="EvidenceColumnB stores root ids without versions",
            ),
        ]
    )

    rootless = copy.deepcopy(source_b)
    rootless["roots"] = []
    for record in rootless["evidence"]:
        record.pop("root_ids", None)
    rootless_native = impl_b.compile_bundle(rootless, "finite_dbn")
    rootless_result = impl_b.execute(rootless_native, query_b)
    rootless_observed = {
        "used_roots": rootless_result["used_roots"],
        "native_addresses": rootless_result["witness"]["native_addresses"],
        "distribution": rootless_result["distribution"],
    }
    probes.append(
        make_probe(
            "B_M08_ROOTLESS_EXECUTION",
            target="impl_b",
            dimension="M08_raw_root_identity",
            expectation="every consumed semantic evidence column has an authoritative root occurrence/version",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "mutation": "remove root registry and record root refs"},
            observed=rootless_observed,
            verdict="fail" if rootless_observed["native_addresses"] and not rootless_observed["used_roots"] else "pass",
            reason="rootless likelihood columns are accepted and executed",
        )
    )

    bridge_b = copy.deepcopy(source_b)
    bridge_b["bridge"] = {
        "version": "bridge-x",
        "transform": "reverse_boolean",
        "source_role": "plan",
        "target_role": "performed_intervention",
    }
    bridge_b["versions"]["bridge"] = "bridge-x"
    bridge_result = impl_b.execute(impl_b.compile_bundle(bridge_b, "finite_dbn"), query_b)
    bridge_observed = {
        "distribution_equal": bridge_result["distribution"] == base_b["distribution"],
        "reported_bridge": bridge_result["witness"]["bridge"],
    }
    probes.append(
        make_probe(
            "B_BRIDGE_SEMANTIC_LIVENESS",
            target="impl_b",
            dimension="bridge_transform_and_role_binding",
            expectation="unknown transform and plan->performed role upgrade are rejected",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "bridge": bridge_b["bridge"]},
            observed=bridge_observed,
            verdict="fail" if bridge_observed["distribution_equal"] else "pass",
            reason="bridge contract is an inert sidecar; evidence is compiled directly",
        )
    )
    return probes


def probe_clean_rebuild_and_unsupported() -> list[dict[str, Any]]:
    probes: list[dict[str, Any]] = []
    source_a = impl_a._fixture()
    delta_a = {
        "kind": "retract",
        "delta_id": "delta-r-y2",
        "registered_at": "2026-01-01T02:30:00Z",
        "reason": "external clean rebuild probe",
        "target_root": {"occurrence_id": "r-y2", "version": "1"},
    }
    incremental_a = impl_a.apply_delta(impl_a.compile_bundle(source_a, "finite_dbn"), delta_a)
    authoritative_a = copy.deepcopy(source_a)
    authoritative_a["deltas"].append(delta_a)
    clean_a = impl_a.compile_bundle(authoritative_a, "finite_dbn")
    inc_a_result, clean_a_result = impl_a.execute(incremental_a, "q-smooth"), impl_a.execute(clean_a, "q-smooth")
    observed_a = {"incremental_equals_authoritative_clean": inc_a_result == clean_a_result}
    probes.append(
        make_probe(
            "A_M11_AUTHORITATIVE_CLEAN_REBUILD",
            target="impl_a",
            dimension="M11_clean_rebuild",
            expectation="incremental in-cut retraction equals fresh compile from authority source plus delta",
            input_object={"fixture_digest": a_fixture_digest(), "delta": delta_a},
            observed=observed_a,
            verdict="pass" if observed_a["incremental_equals_authoritative_clean"] else "fail",
            reason="simple in-cut retraction matches a source-built clean compile; post-cut correction fails separately",
        )
    )

    source_b = impl_b.demo_dbn_bundle()
    native_b = impl_b.compile_bundle(source_b, "finite_dbn")
    delta_b = {"kind": "Retracts", "old": "root-late", "versions": {"evidence_authority": "tel-5"}}
    incremental_b = impl_b.apply_delta(native_b, delta_b)
    authoritative_b = copy.deepcopy(source_b)
    authoritative_b["roots"] = [row for row in authoritative_b["roots"] if row["root_id"] != "root-late"]
    authoritative_b["evidence"] = [row for row in authoritative_b["evidence"] if "root-late" not in row.get("root_ids", [])]
    authoritative_b["versions"].update(delta_b["versions"])
    clean_b = impl_b.compile_bundle(authoritative_b, "finite_dbn")
    smooth_b = {
        "kind": "smooth",
        "target": "state",
        "target_slice": 0,
        "evidence_through": 1,
        "later_evidence_policy": "allow-visible-later-evidence",
    }
    inc_b_result, clean_b_result = impl_b.execute(incremental_b, smooth_b), impl_b.execute(clean_b, smooth_b)
    observed_b = {
        "distribution_equal": inc_b_result["distribution"] == clean_b_result["distribution"],
        "roots_equal": inc_b_result["used_roots"] == clean_b_result["used_roots"],
    }
    probes.append(
        make_probe(
            "B_M11_AUTHORITATIVE_CLEAN_REBUILD",
            target="impl_b",
            dimension="M11_clean_rebuild",
            expectation="incremental in-cut retraction equals fresh compile from independently updated source",
            input_object={"fixture_digest": b_fixture_digest("dbn"), "delta": delta_b},
            observed=observed_b,
            verdict="pass" if all(observed_b.values()) else "fail",
            reason="simple retraction numeric projection matches independent clean source; version/post-cut gates fail separately",
        )
    )

    native_a = impl_a.compile_bundle(source_a, "finite_dbn")
    unsupported_a = caught(
        lambda: impl_a.execute(
            native_a,
            {"query_id": "wrong-op", "kind": "condition", "estimand": "X", "observation_ids": ["s-y0"]},
        )
    )
    native_b = impl_b.compile_bundle(source_b, "finite_dbn")
    unsupported_b = caught(lambda: impl_b.execute(native_b, {"kind": "condition", "target": "state", "condition": {}}))
    probes.extend(
        [
            make_probe(
                "A_M12_UNSUPPORTED_OPERATOR",
                target="impl_a",
                dimension="M12_unsupported_relabel",
                expectation="DBN cannot relabel conditioning as a supported DBN operation",
                input_object={"fixture_digest": a_fixture_digest(), "operator": "condition"},
                observed=unsupported_a,
                verdict="pass" if not unsupported_a["accepted"] else "fail",
                reason="target kernel rejects unsupported query kind",
            ),
            make_probe(
                "B_M12_UNSUPPORTED_OPERATOR",
                target="impl_b",
                dimension="M12_unsupported_relabel",
                expectation="DBN cannot relabel conditioning as a supported DBN operation",
                input_object={"fixture_digest": b_fixture_digest("dbn"), "operator": "condition"},
                observed=unsupported_b,
                verdict="pass" if not unsupported_b["accepted"] else "fail",
                reason="target kernel rejects unsupported query kind",
            ),
        ]
    )
    return probes


def ambiguous_aap_bundles() -> tuple[dict[str, Any], dict[str, Any]]:
    worlds = []
    for index, (u, signal, weight) in enumerate(((1, 1, 0.4), (0, 1, 0.1), (1, 0, 0.1), (0, 0, 0.4))):
        worlds.append(
            {
                "world_id": f"u{u}s{signal}-{index}",
                "probability": weight,
                "exogenous": {"U": u, "Snoise": signal},
                "factual": {"S": signal, "T": 1, "Y": u},
                "responses": [
                    {"do_set": {"T": 0}, "values": {"S": signal, "T": 0, "Y": u}},
                    {"do_set": {"T": 1}, "values": {"S": signal, "T": 1, "Y": u}},
                ],
            }
        )
    b = {
        "schema_version": "vesmed.evidence-model-bridge/1",
        "bundle_id": "ambiguous-aap-b",
        "bridge": {"version": "v1"},
        "temporal_cut": {"target_window": [0, 0], "actor_visibility_cut": 0, "transaction_revision_cut": 0},
        "versions": {"model": "m1"},
        "uncertainty": {"kind": "finite"},
        "roots": [{"root_id": "signal-root", "root_version": "1"}],
        "evidence": [
            {
                "record_id": "signal",
                "slice": 0,
                "available_at": 0,
                "transaction_revision": 0,
                "variable": "S",
                "value": 1,
                "root_ids": ["signal-root"],
            }
        ],
        "model": {"kind": "finite_scm", "timeline": [0], "worlds": worlds},
    }

    a = impl_a._fixture()
    scope = copy.deepcopy(a["scope"])
    raw = {"S": 1}
    a["roots"] = [
        {
            "occurrence_id": "signal-root",
            "version": "1",
            "artifact_id": "signal-artifact",
            "artifact_version": "1",
            "source_span": {"start": 0, "end": 1},
            "raw_payload": raw,
            "raw_digest": impl_a._digest(raw),
            "dependence_families": ["signal-family"],
        }
    ]
    a["evidence_history"] = [
        {
            "statement_id": "signal",
            "logical_id": "signal",
            "version": "1",
            "concept": "signal",
            "semantic_role": "raw_observation",
            "information_state": "present",
            "scope": scope,
            "clocks": {
                "effective_start": "2026-01-01T00:00:00Z",
                "available_at": "2026-01-01T00:00:00Z",
                "recorded_at": "2026-01-01T00:00:00Z",
                "slice_id": "2026-01-01T00:00:00Z",
            },
            "measurement": {"kind": "exact", "value": 1},
            "unit": None,
            "method": "probe",
            "mapping_versions": ["m1"],
            "root_refs": [{"occurrence_id": "signal-root", "version": "1"}],
            "proof": {"kind": "root"},
        }
    ]
    exogenous_worlds, cases_s, cases_t, cases_y = [], [], [], []
    for index, (u, signal, weight) in enumerate(((1, 1, 0.4), (0, 1, 0.1), (1, 0, 0.1), (0, 0, 0.4))):
        world_id = f"w{index}"
        exogenous_worlds.append({"world_id": world_id, "probability": weight, "values": {"W": world_id}})
        cases_s.append({"when": {"W": world_id}, "value": signal})
        cases_t.append({"when": {"W": world_id}, "value": 1})
        cases_y.extend(
            [
                {"when": {"W": world_id, "T": 0}, "value": u},
                {"when": {"W": world_id, "T": 1}, "value": u},
            ]
        )
    a["models"]["finite_scm"] = {
        "model_id": "ambiguous-aap-a",
        "version": "ambiguous-m1",
        "kernel": "finite_scm",
        "endogenous_order": ["S", "T", "Y"],
        "domains": {"S": [0, 1], "T": [0, 1], "Y": [0, 1]},
        "exogenous_worlds": exogenous_worlds,
        "equations": [
            {"variable": "S", "cases": cases_s},
            {"variable": "T", "cases": cases_t},
            {"variable": "Y", "cases": cases_y},
        ],
        "observation_bindings": [{"concept": "signal", "variable": "S"}],
        "uncertainty_semantics": "finite_probability_mass/v1",
        "coverage_contract": {"population": "all"},
        "identification_contracts": ["enumeration"],
    }
    a["deltas"] = []
    a["version_vector"]["model"] = a["models"]["finite_dbn"]["version"] + "+ambiguous-m1"
    a["queries"] = [
        {
            "query_id": "aap",
            "kind": "aap",
            "unit": scope["subject_id"],
            "estimand": "Y",
            "factual_observation_ids": ["signal"],
            "do_set": {"T": 0},
            "shared_world_policy": "share_abduced_exogenous",
            "stages": ["abduction", "action", "prediction"],
        },
        {
            "query_id": "do",
            "kind": "intervene",
            "estimand": "Y",
            "do_set": {"T": 0},
            "conditioning_observation_ids": [],
            "population": "all",
            "identification_contract": "enumeration",
            "mechanism_replacement": True,
        },
    ]
    return a, b


def probe_aap() -> list[dict[str, Any]]:
    a, b = ambiguous_aap_bundles()
    native_a = impl_a.compile_bundle(a, "finite_scm")
    aap_a, do_a = impl_a.execute(native_a, "aap"), impl_a.execute(native_a, "do")
    observed_a = {
        "aap_p1": probability(aap_a, 1),
        "population_do_p1": probability(do_a, 1),
        "used_roots": aap_a["used_evidence"]["root_refs"],
    }
    native_b = impl_b.compile_bundle(b, "finite_scm")
    query_aap_b = {
        "kind": "aap",
        "target": "Y",
        "factual_evidence": {"S": 1},
        "do_set": {"T": 0},
        "shared_world_policy": "same_world",
    }
    query_do_b = {"kind": "do", "target": "Y", "do_set": {"T": 0}}
    aap_b, do_b = impl_b.execute(native_b, query_aap_b), impl_b.execute(native_b, query_do_b)
    observed_b = {
        "aap_p1": probability(aap_b, 1),
        "population_do_p1": probability(do_b, 1),
        "used_roots": aap_b["used_roots"],
    }
    return [
        make_probe(
            "A_M06_AMBIGUOUS_AAP",
            target="impl_a",
            dimension="M06_AAP_shared_world",
            expectation="posterior P(U=1|signal=1)=0.8 is retained across action; population do remains 0.5",
            input_object={"fixture_digest": impl_a.CodecA.semantic_digest(a), "world_weights": [0.4, 0.1, 0.1, 0.4]},
            observed=observed_a,
            verdict="pass" if math.isclose(observed_a["aap_p1"], 0.8, abs_tol=1e-12) and math.isclose(observed_a["population_do_p1"], 0.5, abs_tol=1e-12) else "fail",
            reason="same abduced finite worlds are reused after intervention",
        ),
        make_probe(
            "B_M06_AMBIGUOUS_AAP",
            target="impl_b",
            dimension="M06_AAP_shared_world",
            expectation="posterior P(U=1|signal=1)=0.8 is retained across action; population do remains 0.5",
            input_object={"fixture_digest": sha256_value(b), "world_weights": [0.4, 0.1, 0.1, 0.4]},
            observed=observed_b,
            verdict="pass" if math.isclose(observed_b["aap_p1"], 0.8, abs_tol=1e-12) and math.isclose(observed_b["population_do_p1"], 0.5, abs_tol=1e-12) else "fail",
            reason="same response-world identities are reweighted, not resampled",
        ),
    ]


def panel_protocol() -> dict[str, Any]:
    return json.loads((REPO_ROOT / "research_notes/bridge_panel_protocol_v1.json").read_text(encoding="utf-8"))


def probe_panels() -> list[dict[str, Any]]:
    protocol = panel_protocol()
    model_e03 = protocol["models"]["E03"]
    query_e03 = protocol["queries"]["E03"]
    bad_policy = copy.deepcopy(model_e03)
    bad_policy["cross_world_policy"] = "resample_exogenous"
    policy_a = caught(lambda: panel_a.execute(bad_policy, query_e03))
    policy_b = caught(lambda: panel_b.execute(bad_policy, query_e03))

    prior_mutation = copy.deepcopy(model_e03)
    prior_mutation["R"]["probabilities"] = [0.2, 0.8]
    prior_a = panel_value(panel_a, prior_mutation, query_e03)
    prior_b = panel_value(panel_b, prior_mutation, query_e03)
    equation_mutation = copy.deepcopy(model_e03)
    equation_mutation["structural_equation"] = "Y = R*(2+T) + (1-R)*(-T)"
    equation_query = copy.deepcopy(query_e03)
    equation_query["factual_evidence"]["Y"] = 3
    equation_a = panel_value(panel_a, equation_mutation, equation_query)
    equation_b = panel_value(panel_b, equation_mutation, equation_query)

    solver_rows: list[dict[str, Any]] = []
    for experiment_id in ("E01", "E04", "E06"):
        model = copy.deepcopy(protocol["models"][experiment_id])
        query = copy.deepcopy(protocol["queries"][experiment_id])
        baseline_a = panel_value(panel_a, protocol["models"][experiment_id], protocol["queries"][experiment_id])
        baseline_b = panel_value(panel_b, protocol["models"][experiment_id], protocol["queries"][experiment_id])
        if experiment_id == "E01":
            model["dynamics"] = "dS_dt = 0.08*(1-S) - 0.23*U*S"
            scalar_key = "natural_map_at_9"
        elif experiment_id == "E04":
            model["parameters"]["r"] = 0.41
            scalar_key = "C_peak_hour"
        else:
            query["renal_capacity"] = 0.7
            scalar_key = "renal_capacity"
        mutated_a = panel_value(panel_a, model, query)
        mutated_b = panel_value(panel_b, model, query)
        solver_rows.append(
            {
                "experiment": experiment_id,
                "a_changed": mutated_a != baseline_a,
                "b_changed": mutated_b != baseline_b,
                "scalar_key": scalar_key,
                "a_scalar": mutated_a[scalar_key],
                "b_scalar": mutated_b[scalar_key],
                "scalar_close_1e-6": math.isclose(
                    float(mutated_a[scalar_key]), float(mutated_b[scalar_key]), rel_tol=1e-6, abs_tol=1e-6
                ),
            }
        )
    return [
        make_probe(
            "PANEL_A_E03_POLICY",
            target="panel_a",
            dimension="M06_AAP_policy",
            expectation="resample_exogenous policy is rejected",
            input_object={"protocol_sha256": sha256_file(REPO_ROOT / "research_notes/bridge_panel_protocol_v1.json"), "policy": "resample_exogenous"},
            observed=policy_a,
            verdict="pass" if not policy_a["accepted"] else "fail",
            reason="Panel A enforces share_abduced_exogenous",
        ),
        make_probe(
            "PANEL_B_E03_POLICY",
            target="panel_b",
            dimension="M06_AAP_policy",
            expectation="resample_exogenous policy is rejected",
            input_object={"protocol_sha256": sha256_file(REPO_ROOT / "research_notes/bridge_panel_protocol_v1.json"), "policy": "resample_exogenous"},
            observed=policy_b,
            verdict="fail" if policy_b["accepted"] else "pass",
            reason="Panel B computes AAP while merely echoing the invalid policy in trace",
        ),
        make_probe(
            "PANELS_E03_SOLVER_LIVENESS",
            target="panel_a+panel_b",
            dimension="AAP_solver_liveness",
            expectation="prior and structural equation mutations change outputs consistently across independent panels",
            input_object={
                "protocol_sha256": sha256_file(REPO_ROOT / "research_notes/bridge_panel_protocol_v1.json"),
                "prior_probabilities": [0.2, 0.8],
                "equation": equation_mutation["structural_equation"],
                "factual_Y": 3,
            },
            observed={"prior_a": prior_a, "prior_b": prior_b, "equation_a": equation_a, "equation_b": equation_b},
            verdict="pass" if prior_a == prior_b and equation_a == equation_b and prior_a["population_do_mean_Y_T0"] == 0.8 and equation_a["individual_counterfactual_Y_T0"] == 2.0 else "fail",
            reason="both independent AAP solvers consume public prior/equation rather than expected-output constants",
        ),
        make_probe(
            "PANELS_ODE_SOLVER_LIVENESS",
            target="panel_a+panel_b",
            dimension="numeric_solver_liveness",
            expectation="public dynamics/parameter/query mutations are live and independent solvers agree within 1e-6",
            input_object={"protocol_sha256": sha256_file(REPO_ROOT / "research_notes/bridge_panel_protocol_v1.json"), "mutations": ["E01 treatment=0.23", "E04 r=0.41", "E06 renal=0.7"]},
            observed={"rows": solver_rows},
            verdict="pass" if all(row["a_changed"] and row["b_changed"] and row["scalar_close_1e-6"] for row in solver_rows) else "fail",
            reason="RK4 and adaptive Heun/Richardson respond to public inputs and agree numerically",
        ),
    ]


def build_report() -> dict[str, Any]:
    probes: list[dict[str, Any]] = []
    for producer in (
        probe_static_closure,
        probe_a_m01,
        probe_b_m01,
        probe_future_filter_smooth,
        probe_target_window,
        probe_duplicate_dependence,
        probe_postcut_delta,
        probe_supersedes,
        probe_scope,
        probe_absent_censored,
        probe_a_uncertainty_positive,
        probe_namespace_empty_family,
        probe_versions_roots_bridge,
        probe_clean_rebuild_and_unsupported,
        probe_aap,
        probe_panels,
    ):
        probes.extend(producer())
    ids = [probe["probe_id"] for probe in probes]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate probe ids")

    freeze_manifest_path = REPO_ROOT / "results/bridge-holdout/freeze-manifest.json"
    fixture_manifest_path = REPO_ROOT / "results/bridge-holdout/fixture-manifest.json"
    freeze_manifest = json.loads(freeze_manifest_path.read_text(encoding="utf-8"))
    seals = {
        key: {
            "path": value["path"],
            "expected_sha256": value["sha256"],
            "observed_sha256": sha256_file(REPO_ROOT / value["path"]),
        }
        for key, value in freeze_manifest["implementations"].items()
        if key in {"impl_a", "impl_b", "panel_a", "panel_b"}
    }
    for row in seals.values():
        row["matches"] = row["expected_sha256"] == row["observed_sha256"]
    fixture_context: dict[str, Any] = {"used_as_probe_input": False}
    if fixture_manifest_path.exists():
        fixture_manifest = json.loads(fixture_manifest_path.read_text(encoding="utf-8"))
        fixture_path = REPO_ROOT / fixture_manifest["artifacts"]["fixture"]["path"]
        fixture_context.update(
            {
                "manifest_sha256": sha256_file(fixture_manifest_path),
                "fixture_path": str(fixture_path.relative_to(REPO_ROOT)).replace("\\", "/"),
                "expected_fixture_sha256": fixture_manifest["artifacts"]["fixture"]["sha256"],
                "observed_fixture_sha256": sha256_file(fixture_path),
                "metadata_only_mutations_note": "H03-H41 mutation payloads are not materialized by this external probe file",
            }
        )
    counts: dict[str, int] = {}
    for probe in probes:
        counts[probe["verdict"]] = counts.get(probe["verdict"], 0) + 1
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "provenance": PROVENANCE,
        "claim_boundary": {
            "is_hidden_corpus_run": False,
            "is_candidate_self_attestation": False,
            "description": "materialized deterministic probes authored after candidate seals",
        },
        "canonical_hash_encoding": "UTF-8 sorted compact JSON without trailing LF",
        "source_seals": seals,
        "fixture_context": fixture_context,
        "verdict_counts_non_compensating": counts,
        "probes": sorted(probes, key=lambda probe: probe["probe_id"]),
    }
    report["report_sha256"] = sha256_value(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="optional machine-JSON output path")
    args = parser.parse_args()
    report = build_report()
    payload = canonical_bytes(report) + b"\n"
    if args.output is not None:
        output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(payload)
    sys.stdout.buffer.write(payload)


if __name__ == "__main__":
    main()
