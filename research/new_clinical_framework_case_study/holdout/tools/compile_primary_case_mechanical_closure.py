#!/usr/bin/env python3
"""Compile case-role access lineage and event-ledger audit from exact artifacts.

This is evidence machinery, not a medical judge.  It verifies content
addresses, selected-source inventory, eight-role input/output DAG, structured
tool traces, producer/consumer timing, and the frozen availability compiler
chain.  It never assesses diagnoses, clinical correctness, or gate outcomes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence
from urllib.parse import urlsplit

from compile_availability_epochs import compile_ledger as compile_availability
from verify_evaluator_sanitized_runtime_ledger import build_verification as verify_sanitized_ledger
from verify_compiled_availability import verify as verify_compiled_availability


ROLES = [
    "scout", "screener", "extractor", "source_auditor", "concept_mapper",
    "oracle_adjudicator", "evaluator", "scorer_auditor",
]
LINEAGE_VERSION = "NCF-PRIMARY-CASE-ACCESS-LINEAGE-1.0.0"
AUDIT_VERSION = "NCF-PRIMARY-EVENT-LEDGER-AUDIT-1.0.0"
AVAILABILITY_PRODUCER_ID = "availability-epoch-compiler-v1"
AVAILABILITY_COMPILER_REL = "holdout/tools/compile_availability_epochs.py"
AVAILABILITY_VERIFIER_REL = "holdout/tools/verify_compiled_availability.py"
AVAILABILITY_RAW = "availability_ledger"
AVAILABILITY_COMPILED = "compiled_guaranteed_availability"
AVAILABILITY_SEALED = "sealed_compiled_guaranteed_availability"
AVAILABILITY_PROOF_SEALED = "sealed_availability_compiler_proof"
CANONICAL_PROTOCOL_REL = "holdout/PRIMARY_HOLDOUT_EXECUTION_PROTOCOL_v1.json"
CANONICAL_COMBINED_SEAL_REL = "holdout/evidence/PRE_PRIMARY_HOLDOUT_SEAL.json"
SANITIZER_INPUTS = {
    "sealed_event_ledger",
    AVAILABILITY_SEALED,
    AVAILABILITY_PROOF_SEALED,
    "sealed_concept_map",
    "sanitized_id_type_unit_registry",
    "combined_preprimary_seal",
}
EVALUATOR_SOURCE_TIMING_FORBIDDEN = {
    "event_ledger",
    "sealed_event_ledger",
    AVAILABILITY_RAW,
    "sealed_availability_ledger",
    AVAILABILITY_COMPILED,
    AVAILABILITY_SEALED,
    "availability_compiler_proof",
    AVAILABILITY_PROOF_SEALED,
}


class ClosureError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise ClosureError(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail(f"non-canonical JSON value: {exc}")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _ref(root: Path, path: Path) -> dict[str, Any]:
    resolved = path.resolve(strict=True)
    try:
        rel = resolved.relative_to(root)
    except ValueError:
        _fail(f"artifact escapes study root: {path}")
    cursor = root
    for part in rel.parts:
        cursor /= part
        if cursor.is_symlink():
            _fail(f"artifact path contains symlink: {rel.as_posix()}")
    if not resolved.is_file():
        _fail(f"artifact is not a file: {rel.as_posix()}")
    raw = resolved.read_bytes()
    return {"path": rel.as_posix(), "sha256": _sha(raw), "bytes": len(raw)}


def _verify_ref(root: Path, ref: Any, label: str) -> tuple[Path, bytes]:
    if not isinstance(ref, Mapping) or not {"path", "sha256", "bytes"}.issubset(ref):
        _fail(f"{label} content ref missing")
    rel_text = ref.get("path")
    if not isinstance(rel_text, str) or not rel_text:
        _fail(f"{label}.path missing")
    rel = PurePosixPath(rel_text)
    if rel.is_absolute() or ".." in rel.parts or re.match(r"^[A-Za-z]:", rel_text):
        _fail(f"{label}.path is not canonical in-root")
    path = root / Path(*rel.parts)
    actual = _ref(root, path)
    if ref.get("sha256") != actual["sha256"] or ref.get("bytes") != actual["bytes"]:
        _fail(f"{label} hash/bytes mismatch")
    return path.resolve(strict=True), path.read_bytes()


def _json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not UTF-8 JSON: {exc}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _artifact_rows(value: Any) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if (
            isinstance(value.get("path"), str)
            and isinstance(value.get("sha256"), str)
            and isinstance(value.get("bytes"), int)
        ):
            rows.append(value)
        for child in value.values():
            rows.extend(_artifact_rows(child))
    elif isinstance(value, list):
        for child in value:
            rows.extend(_artifact_rows(child))
    return rows


def _combined_seal_authority(
    root: Path, protocol: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, tuple[str, int]]]:
    contract = protocol.get("role_manifest")
    paths = contract.get("presealed_root_asset_paths") if isinstance(contract, Mapping) else None
    if (
        not isinstance(paths, Mapping)
        or paths.get("combined_preprimary_seal") != CANONICAL_COMBINED_SEAL_REL
        or paths.get("protocol") != CANONICAL_PROTOCOL_REL
    ):
        _fail("protocol canonical authority paths mismatch")
    seal_ref = _ref(root, root / Path(*PurePosixPath(CANONICAL_COMBINED_SEAL_REL).parts))
    seal_value = _json(
        (root / Path(*PurePosixPath(CANONICAL_COMBINED_SEAL_REL).parts)).read_bytes(),
        "combined preprimary seal",
    )
    digest = seal_value.get("payload_sha256")
    unsigned = dict(seal_value)
    unsigned.pop("payload_sha256", None)
    if (
        seal_value.get("status") != "SEALED_BEFORE_PRIMARY_CASE_SELECTION"
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        or _sha(_canonical_bytes(unsigned)) != digest
    ):
        _fail("combined preprimary seal is invalid")
    inventory: dict[str, tuple[str, int]] = {}
    for row in _artifact_rows(seal_value.get("bindings")):
        _verify_ref(root, row, "combined seal binding")
        identity = (row["sha256"], row["bytes"])
        if row["path"] in inventory and inventory[row["path"]] != identity:
            _fail(f"combined seal has conflicting binding: {row['path']}")
        inventory[row["path"]] = identity
    return seal_ref, seal_value, digest, inventory


def _validate_role_protocol_contract(
    root: Path,
    role: str,
    manifest: Mapping[str, Any],
    protocol: Mapping[str, Any],
    combined_seal_ref: Mapping[str, Any],
    combined_inventory: Mapping[str, tuple[str, int]],
) -> None:
    role_policy = protocol.get("roles", {}).get(role)
    contract = protocol.get("role_manifest")
    if not isinstance(role_policy, Mapping) or not isinstance(contract, Mapping):
        _fail(f"protocol role contract missing: {role}")
    inputs, outputs = manifest["inputs"], manifest["outputs"]
    input_classes = [row.get("data_class") for row in inputs]
    output_classes = [row.get("data_class") for row in outputs]
    # This is an invariant of the blinded execution architecture, not a
    # mutable protocol preference.  Even a self-consistent, re-sealed protocol
    # may not give the evaluator direct access to source-rich event/timing
    # ledgers; the only lawful route is the externally compiled opaque ledger.
    if role == "evaluator" and set(input_classes) & EVALUATOR_SOURCE_TIMING_FORBIDDEN:
        _fail("evaluator direct source/timing ledger access is forbidden")
    allowed_inputs = role_policy.get("allowed_input_data_classes")
    allowed_outputs = role_policy.get("allowed_output_data_classes")
    if (
        not isinstance(allowed_inputs, list)
        or not isinstance(allowed_outputs, list)
        or len(input_classes) != len(set(input_classes))
        or len(output_classes) != len(set(output_classes))
        or set(input_classes) != set(allowed_inputs)
        or set(output_classes) != set(allowed_outputs)
    ):
        _fail(f"role {role} manifest does not exactly implement frozen input/output allowlist")
    observed = manifest.get("observed_data_classes")
    if not isinstance(observed, list) or len(observed) != len(set(observed)) or set(observed) != set(input_classes):
        _fail(f"role {role} observed data classes differ from exact input inventory")
    forbidden = role_policy.get("forbidden_data_classes")
    if not isinstance(forbidden, list) or (set(input_classes) | set(output_classes) | set(observed)) & set(forbidden):
        _fail(f"role {role} exposes a forbidden data class")
    if role_policy.get("case_identity_exposure") == "FORBIDDEN" and manifest.get("case_identity_exposed") is not False:
        _fail(f"role {role} violates case identity isolation")
    attestations = manifest.get("attestations")
    if not isinstance(attestations, Mapping) or any(
        attestations.get(key) is not True
        for key in (
            "only_declared_inputs_observed",
            "no_forbidden_data_class_observed",
            "no_undeclared_output_written",
            "no_artifact_modified_after_input_hash",
        )
    ):
        _fail(f"role {role} attestations incomplete")
    schema_ids = contract.get("data_class_schema_ids")
    roots = contract.get("presealed_root_data_classes")
    root_paths = contract.get("presealed_root_asset_paths")
    if not isinstance(schema_ids, Mapping) or not isinstance(roots, list) or not isinstance(root_paths, Mapping):
        _fail("protocol root/schema registry missing")
    for side, rows in (("input", inputs), ("output", outputs)):
        for row in rows:
            if row.get("schema_id") != schema_ids.get(row.get("data_class")):
                _fail(f"role {role} {side} schema_id mismatch: {row.get('data_class')}")
    for row in inputs:
        producer = row.get("producer")
        if not isinstance(producer, Mapping):
            _fail(f"role {role} input producer missing: {row.get('data_class')}")
        kind = producer.get("kind")
        if kind == "PRESEALED_ROOT":
            data_class = row["data_class"]
            if (
                set(producer) != {"kind", "seal"}
                or data_class not in roots
                or row["path"] != root_paths.get(data_class)
                or _basic_ref(producer.get("seal", {})) != _basic_ref(combined_seal_ref)
            ):
                _fail(f"role {role} has invalid PRESEALED_ROOT binding: {data_class}")
            if data_class == "combined_preprimary_seal":
                if _basic_ref(row) != _basic_ref(combined_seal_ref):
                    _fail(f"role {role} combined seal input does not bind canonical authority")
            elif combined_inventory.get(row["path"]) != (row["sha256"], row["bytes"]):
                _fail(f"role {role} root input is absent from combined seal: {data_class}")
        elif kind == "ROLE_OUTPUT":
            continue
        elif kind == "SEALED_EXECUTABLE_OUTPUT":
            external_edges = contract.get("external_producer_edges")
            matches = [
                edge for edge in external_edges if isinstance(edge, Mapping)
                and edge.get("producer_id") == producer.get("producer_id")
                and edge.get("data_class") == row.get("data_class")
                and role in edge.get("consumer_roles", [])
                and edge.get("producer_kind") == "SEALED_EXECUTABLE_OUTPUT"
            ] if isinstance(external_edges, list) else []
            if (
                role != "evaluator"
                or row.get("data_class") != "evaluator_sanitized_runtime_ledger"
                or set(producer) != {
                    "kind", "producer_id", "assignment_proof", "replay_verification",
                }
                or len(matches) != 1
            ):
                _fail(f"role {role} has unauthorized sealed executable input")
            _, proof_raw = _verify_ref(
                root, producer["assignment_proof"], "sanitized-ledger assignment proof",
            )
            _, verification_raw = _verify_ref(
                root, producer["replay_verification"], "sanitized-ledger replay verification",
            )
            proof = _json(proof_raw, "sanitized-ledger assignment proof")
            verification = _json(verification_raw, "sanitized-ledger replay verification")
            proof_output = proof.get("output_ledger", {})
            proof_output_matches = (
                isinstance(proof_output, Mapping)
                and proof_output.get("path") == PurePosixPath(row["path"]).name
                and proof_output.get("sha256") == row.get("sha256")
                and proof_output.get("bytes") == row.get("bytes")
                and proof_output.get("data_class") == row.get("data_class")
                and proof_output.get("schema_id") == row.get("schema_id")
            )
            if (
                proof.get("status") != "PASS"
                or proof.get("producer_id") != producer["producer_id"]
                or not proof_output_matches
                or verification.get("status") != "PASS"
                or verification.get("producer_id") != producer["producer_id"]
                or _basic_ref(verification.get("compiler_outputs", {}).get("ledger", {})) != _basic_ref(row)
                or _basic_ref(
                    verification.get("compiler_outputs", {}).get("assignment_proof", {})
                ) != _basic_ref(producer["assignment_proof"])
                or _basic_ref(verification.get("compiler_input_manifest", {}))
                != _basic_ref(proof.get("input_manifest", {}))
            ):
                _fail("sealed executable output proof/verification content binding mismatch")
            manifest_path = root / Path(*PurePosixPath(proof["input_manifest"]["path"]).parts)
            ledger_path = root / Path(*PurePosixPath(row["path"]).parts)
            proof_path = root / Path(*PurePosixPath(producer["assignment_proof"]["path"]).parts)
            seal_path = root / Path(*PurePosixPath(combined_seal_ref["path"]).parts)
            try:
                expected_verification = verify_sanitized_ledger(
                    root,
                    manifest_path=manifest_path,
                    ledger_path=ledger_path,
                    assignment_proof_path=proof_path,
                    combined_seal_path=seal_path,
                )
            except Exception as exc:
                _fail(f"sealed executable output fresh replay failed: {exc}")
            if _canonical_bytes(verification) != _canonical_bytes(expected_verification):
                _fail("sealed executable output replay verification is not exact fresh verifier output")
        else:
            _fail(f"role {role} input producer kind invalid")


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str):
        _fail(f"{label} missing")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        _fail(f"{label} invalid: {exc}")
    if result.tzinfo is None:
        _fail(f"{label} must be timezone-aware")
    return result


def _typed_ref(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(key) for key in ("path", "sha256", "bytes", "data_class", "schema_id"))


def _basic_ref(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return tuple(row.get(key) for key in ("path", "sha256", "bytes"))


def _one(by_role: Mapping[str, Mapping[str, Any]], role: str, side: str, data_class: str) -> Mapping[str, Any]:
    rows = [row for row in by_role[role][side] if row.get("data_class") == data_class]
    if len(rows) != 1:
        _fail(f"role {role} must declare exactly one {side} {data_class}")
    return rows[0]


def _validate_trace(
    root: Path,
    role: str,
    manifest: Mapping[str, Any],
    trace: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> None:
    if (
        trace.get("schema_version") != "NCF-PRIMARY-ROLE-TOOL-ACCESS-TRACE-1.0.0"
        or trace.get("role") != role
        or trace.get("run_id") != manifest.get("run_id")
        or trace.get("case_identity_exposed") != manifest.get("case_identity_exposed")
        or trace.get("trace_complete") is not True
        or trace.get("undeclared_access_detected") is not False
    ):
        _fail(f"role {role} tool trace identity/completeness mismatch")
    expected: set[tuple[Any, ...]] = set()
    for row in manifest.get("inputs", []):
        expected.add(("READ", "INPUT", *_typed_ref(row)))
    for row in manifest.get("outputs", []):
        expected.add(("WRITE", "OUTPUT", *_typed_ref(row)))
    for kind, key, data_class, schema_id in (
        ("PROMPT_OR_COMMAND", "prompt_or_command", "role_prompt_or_command", "ncf.role.prompt-or-command.v1"),
        ("PARENT_PACKET", "parent_packet", "role_parent_packet", "ncf.role.parent-packet.v1"),
    ):
        ref = manifest.get(key)
        if not isinstance(ref, Mapping):
            _fail(f"role {role} {key} missing")
        _verify_ref(root, ref, f"role {role} {key}")
        expected.add(("READ", kind, ref["path"], ref["sha256"], ref["bytes"], data_class, schema_id))
    accesses = trace.get("accesses")
    if not isinstance(accesses, list) or not all(isinstance(row, Mapping) for row in accesses):
        _fail(f"role {role} accesses missing")
    if [row.get("sequence") for row in accesses] != list(range(len(accesses))):
        _fail(f"role {role} trace sequence is not contiguous")
    if any(not isinstance(row.get("access_count"), int) or row["access_count"] < 1 for row in accesses):
        _fail(f"role {role} trace has invalid access_count")
    actual = {
        (
            row.get("operation"), row.get("artifact_kind"), row.get("path"), row.get("sha256"),
            row.get("bytes"), row.get("data_class"), row.get("schema_id"),
        )
        for row in accesses
    }
    if len(actual) != len(accesses) or actual != expected:
        _fail(f"role {role} tool trace is not an exact read/write inventory")
    if (
        trace.get("prompt_or_command_sha256") != manifest["prompt_or_command"]["sha256"]
        or trace.get("parent_packet_sha256") != manifest["parent_packet"]["sha256"]
    ):
        _fail(f"role {role} trace prompt/parent digest mismatch")
    network_requests = trace.get("network_requests")
    if not isinstance(network_requests, list) or not all(isinstance(row, Mapping) for row in network_requests):
        _fail(f"role {role} network request trace missing")
    if trace.get("network_access_detected") != bool(network_requests):
        _fail(f"role {role} network flag/request inventory mismatch")
    if [row.get("sequence") for row in network_requests] != list(range(len(network_requests))):
        _fail(f"role {role} network request sequence is not contiguous")
    policy = protocol.get("roles", {}).get(role, {}).get("network_access_policy")
    if policy == "FORBIDDEN" and network_requests:
        _fail(f"role {role} violates frozen no-network policy")
    if policy == "REQUIRED_NCBI_HTTPS_GET_ONLY":
        if not network_requests:
            _fail("scout lacks required retrieval trace")
        allowed_hosts = {
            "eutils.ncbi.nlm.nih.gov",
            "pubmed.ncbi.nlm.nih.gov",
            "pmc.ncbi.nlm.nih.gov",
            "www.ncbi.nlm.nih.gov",
        }
        expected_keys = {
            "sequence", "method", "request_url", "response_sha256", "response_bytes", "retrieved_at",
        }
        for request in network_requests:
            parsed = urlsplit(request.get("request_url", ""))
            if (
                set(request) != expected_keys
                or request.get("method") != "GET"
                or parsed.scheme != "https"
                or parsed.hostname not in allowed_hosts
                or parsed.username is not None
                or parsed.password is not None
                or parsed.port not in {None, 443}
                or bool(parsed.fragment)
                or re.fullmatch(r"[0-9a-f]{64}", str(request.get("response_sha256"))) is None
                or not isinstance(request.get("response_bytes"), int)
                or request["response_bytes"] < 1
            ):
                _fail("scout network request is outside exact NCBI HTTPS GET contract")
            _parse_time(request.get("retrieved_at"), "scout.network.retrieved_at")


def _load_roles(root: Path, aggregate_path: Path) -> tuple[
    dict[str, Any], dict[str, dict[str, Any]], dict[str, dict[str, Any]],
    dict[str, dict[str, Any]], dict[str, Any]
]:
    aggregate_ref = _ref(root, aggregate_path)
    aggregate = _json(aggregate_path.read_bytes(), "role manifest set")
    if aggregate.get("schema_version") != "NCF-PRIMARY-ROLE-MANIFEST-SET-1.0.0":
        _fail("role manifest set schema_version mismatch")
    _, protocol_raw = _verify_ref(root, aggregate.get("protocol"), "role manifest set protocol")
    protocol = _json(protocol_raw, "execution protocol")
    combined_seal_ref, _, _, combined_inventory = _combined_seal_authority(root, protocol)
    protocol_ref = _ref(root, root / Path(*PurePosixPath(CANONICAL_PROTOCOL_REL).parts))
    if (
        _basic_ref(aggregate.get("protocol", {})) != _basic_ref(protocol_ref)
        or combined_inventory.get(CANONICAL_PROTOCOL_REL) != (protocol_ref["sha256"], protocol_ref["bytes"])
    ):
        _fail("aggregate protocol is not the exact canonical protocol frozen in combined seal")
    rows = aggregate.get("manifests")
    if not isinstance(rows, list) or [row.get("role") for row in rows if isinstance(row, Mapping)] != ROLES:
        _fail("role manifest set must contain exact eight-role frozen order")
    manifests: dict[str, dict[str, Any]] = {}
    manifest_refs: dict[str, dict[str, Any]] = {}
    traces: dict[str, dict[str, Any]] = {}
    for row in rows:
        role = row["role"]
        _, raw = _verify_ref(root, row, f"role manifest ref {role}")
        manifest = _json(raw, f"role manifest {role}")
        if (
            manifest.get("schema_version") != "NCF-PRIMARY-ROLE-MANIFEST-1.1.0"
            or manifest.get("role") != role
            or manifest.get("run_id") != row.get("run_id")
        ):
            _fail(f"role manifest identity mismatch: {role}")
        start = _parse_time(manifest.get("started_at"), f"{role}.started_at")
        finish = _parse_time(manifest.get("finished_at"), f"{role}.finished_at")
        if finish < start:
            _fail(f"role {role} finishes before it starts")
        inputs, outputs = manifest.get("inputs"), manifest.get("outputs")
        if not isinstance(inputs, list) or not isinstance(outputs, list):
            _fail(f"role {role} inputs/outputs missing")
        _validate_role_protocol_contract(
            root,
            role,
            manifest,
            protocol,
            combined_seal_ref,
            combined_inventory,
        )
        for index, artifact in enumerate([*inputs, *outputs]):
            _verify_ref(root, artifact, f"role {role} artifact {index}")
        _, trace_raw = _verify_ref(root, manifest.get("tool_trace"), f"role {role} tool trace")
        trace = _json(trace_raw, f"role {role} tool trace")
        _validate_trace(root, role, manifest, trace, protocol)
        manifests[role] = manifest
        manifest_refs[role] = {key: row[key] for key in ("path", "sha256", "bytes")}
        traces[role] = trace
    return aggregate_ref, manifests, manifest_refs, traces, protocol


def _validate_dag(
    manifests: Mapping[str, Mapping[str, Any]],
    manifest_refs: Mapping[str, Mapping[str, Any]],
    protocol: Mapping[str, Any],
) -> list[dict[str, Any]]:
    outputs: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for role, manifest in manifests.items():
        for row in manifest["outputs"]:
            outputs.setdefault((role, row["data_class"]), []).append(row)
    edges: list[dict[str, Any]] = []
    actual: set[tuple[str, str, str]] = set()
    for consumer, manifest in manifests.items():
        for row in manifest["inputs"]:
            producer = row.get("producer")
            if not isinstance(producer, Mapping) or producer.get("kind") != "ROLE_OUTPUT":
                continue
            producer_role = producer.get("role")
            if producer_role not in manifests:
                _fail(f"DAG producer role is not in frozen role set: {producer_role}")
            expected_producer = {
                "kind": "ROLE_OUTPUT",
                "role": producer_role,
                "run_id": manifests.get(producer_role, {}).get("run_id"),
                "manifest_path": manifest_refs.get(producer_role, {}).get("path"),
                "manifest_sha256": manifest_refs.get(producer_role, {}).get("sha256"),
                "manifest_bytes": manifest_refs.get(producer_role, {}).get("bytes"),
            }
            if dict(producer) != expected_producer:
                _fail(f"DAG producer manifest lineage mismatch: {producer_role}->{consumer}")
            candidates = outputs.get((producer_role, row.get("data_class")), [])
            if len(candidates) != 1 or _typed_ref(candidates[0]) != _typed_ref(row):
                _fail(f"DAG input is not exact producer output: {producer_role}->{consumer}:{row.get('data_class')}")
            if _parse_time(manifests[producer_role]["finished_at"], "producer finished") > _parse_time(
                manifest["started_at"], "consumer started"
            ):
                _fail(f"consumer starts before producer finishes: {producer_role}->{consumer}")
            actual.add((producer_role, consumer, row["data_class"]))
            edges.append(
                {
                    "producer_role": producer_role,
                    "consumer_role": consumer,
                    "data_class": row["data_class"],
                    "artifact": {key: row[key] for key in ("path", "sha256", "bytes")},
                }
            )
    declared_rows = protocol.get("role_manifest", {}).get("producer_consumer_edges")
    if not isinstance(declared_rows, list):
        _fail("protocol role DAG missing")
    expected = {
        (row["producer_role"], consumer, row["data_class"])
        for row in declared_rows for consumer in row["consumer_roles"]
    }
    if actual != expected:
        _fail(f"role DAG differs from protocol; missing={sorted(expected-actual)} extra={sorted(actual-expected)}")
    return sorted(edges, key=lambda row: (ROLES.index(row["consumer_role"]), row["data_class"], row["producer_role"]))


def _validate_selected_inventory(
    root: Path, manifest_row: Mapping[str, Any], inventory_row: Mapping[str, Any]
) -> int:
    _, manifest_raw = _verify_ref(root, manifest_row, "selected immutable source manifest")
    selected = _json(manifest_raw, "selected immutable source manifest")
    if (
        set(selected) != {
            "schema_version", "selected_source", "source_artifacts",
            "inventory_sha256", "immutable", "inventory_complete",
        }
        or not isinstance(selected.get("selected_source"), Mapping)
        or set(selected["selected_source"]) != {"path", "sha256", "bytes"}
        or
        selected.get("schema_version") != "NCF-PRIMARY-SELECTED-IMMUTABLE-SOURCE-MANIFEST-1.0.0"
        or selected.get("immutable") is not True
        or selected.get("inventory_complete") is not True
    ):
        _fail("selected immutable source manifest contract mismatch")
    source_rows = selected.get("source_artifacts")
    if not isinstance(source_rows, list) or not source_rows:
        _fail("selected immutable source manifest has empty inventory")
    identities: list[tuple[Any, ...]] = []
    for index, row in enumerate(source_rows):
        if not isinstance(row, Mapping) or set(row) != {"path", "sha256", "bytes", "source_role"}:
            _fail(f"selected source artifact {index} shape invalid")
        _verify_ref(root, row, f"selected source artifact {index}")
        identities.append((row["path"], row["sha256"], row["bytes"]))
    if len(identities) != len(set(identities)) or selected.get("inventory_sha256") != _sha(_canonical_bytes(source_rows)):
        _fail("selected source inventory digest/uniqueness mismatch")
    selected_ref = selected.get("selected_source")
    _verify_ref(root, selected_ref, "selected primary source")
    if _basic_ref(selected_ref) not in {_basic_ref(row) for row in source_rows}:
        _fail("selected primary source is absent from immutable inventory")

    _, inventory_raw = _verify_ref(root, inventory_row, "extracted source inventory")
    inventory = _json(inventory_raw, "extracted source inventory")
    if (
        set(inventory) != {
            "schema_version", "selected_source_manifest", "source_artifacts", "inventory_sha256",
        }
        or not isinstance(inventory.get("selected_source_manifest"), Mapping)
        or set(inventory["selected_source_manifest"]) != {"path", "sha256", "bytes"}
        or inventory.get("schema_version") != "NCF-PRIMARY-EXTRACTED-SOURCE-INVENTORY-1.0.0"
    ):
        _fail("extracted source inventory schema_version mismatch")
    if _basic_ref(inventory.get("selected_source_manifest", {})) != _basic_ref(manifest_row):
        _fail("extracted source inventory does not bind selected manifest")
    extracted = inventory.get("source_artifacts")
    expected = [{key: row[key] for key in ("path", "sha256", "bytes")} for row in source_rows]
    if extracted != expected or inventory.get("inventory_sha256") != _sha(_canonical_bytes(extracted)):
        _fail("extracted source inventory is not exact selected-source inventory")
    return len(source_rows)


def _event_rows(value: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = value.get("events")
    if not isinstance(rows, list) or not rows:
        _fail("event ledger must contain events")
    return rows


def _validate_event_and_availability(
    root: Path,
    selected_manifest_row: Mapping[str, Any],
    source_inventory_row: Mapping[str, Any],
    event_row: Mapping[str, Any],
    raw_availability_row: Mapping[str, Any],
    compiled_row: Mapping[str, Any],
    proof_row: Mapping[str, Any],
    combined_seal_row: Mapping[str, Any],
) -> dict[str, Any]:
    source_count = _validate_selected_inventory(root, selected_manifest_row, source_inventory_row)
    _, inventory_raw = _verify_ref(root, source_inventory_row, "source inventory")
    source_inventory = _json(inventory_raw, "source inventory")
    source_refs = {row["path"]: row for row in source_inventory["source_artifacts"]}
    _, event_raw = _verify_ref(root, event_row, "event ledger")
    event_value = _json(event_raw, "event ledger")
    if event_value.get("schema_version") != "ncf.data.event-ledger.v1":
        _fail("event ledger schema_version mismatch")
    events = _event_rows(event_value)
    event_ids: list[str] = []
    for index, row in enumerate(events):
        if (
            not isinstance(row, Mapping)
            or not isinstance(row.get("source_event_id"), str)
            or not row.get("source_event_id")
        ):
            _fail(f"event ledger row {index} lacks source_event_id")
        event_id = row["source_event_id"]
        if event_id in event_ids:
            _fail(f"duplicate source_event_id: {event_id}")
        event_ids.append(event_id)
        runtime_event = row.get("runtime_event")
        if not isinstance(runtime_event, Mapping) or "available_at" in runtime_event:
            _fail(f"event {event_id} lacks runtime_event or contains hand-authored available_at")
        locator = row.get("source_locator")
        if not isinstance(locator, Mapping) or set(locator) != {"artifact_path", "artifact_sha256", "artifact_bytes", "locator"}:
            _fail(f"event {event_id} source locator shape invalid")
        source = source_refs.get(locator["artifact_path"])
        if (
            source is None
            or locator["artifact_sha256"] != source["sha256"]
            or locator["artifact_bytes"] != source["bytes"]
            or not isinstance(locator["locator"], str)
            or not locator["locator"]
        ):
            _fail(f"event {event_id} source locator is outside exact inventory")

    _, availability_raw = _verify_ref(root, raw_availability_row, "raw availability ledger")
    availability_value = _json(availability_raw, "raw availability ledger")
    raw_rows = availability_value.get("events")
    if not isinstance(raw_rows, list) or [row.get("source_event_id") for row in raw_rows] != event_ids:
        _fail("raw availability event inventory/order differs from event ledger")
    for event_source, row in zip(events, raw_rows, strict=True):
        runtime_event = row.get("runtime_event")
        if not isinstance(runtime_event, Mapping) or "available_at" in runtime_event:
            _fail("raw availability ledger contains hand-authored available_at")
        if _canonical_bytes(runtime_event) != _canonical_bytes(event_source["runtime_event"]):
            _fail("raw availability runtime_event differs from event ledger")

    _, compiled_raw = _verify_ref(root, compiled_row, "compiled guaranteed availability")
    compiled_value = _json(compiled_raw, "compiled guaranteed availability")
    expected_compiled = compile_availability(availability_value)
    if _canonical_bytes(compiled_value) != _canonical_bytes(expected_compiled):
        _fail("compiled guaranteed availability is not exact frozen-compiler output")
    released = compiled_value["released_events"]
    withheld = compiled_value["withheld_events"]
    partition = [row["source_event_id"] for row in released] + [row["source_event_id"] for row in withheld]
    if set(partition) != set(event_ids) or len(partition) != len(event_ids):
        _fail("compiled availability released/withheld partition is not exact event inventory")

    _, proof_raw = _verify_ref(root, proof_row, "availability compiler proof")
    proof = _json(proof_raw, "availability compiler proof")
    _, combined_seal_raw = _verify_ref(root, combined_seal_row, "combined preprimary seal")
    combined_seal = _json(combined_seal_raw, "combined preprimary seal")
    seal_payload_sha256 = combined_seal.get("payload_sha256")
    unsigned_seal = dict(combined_seal)
    unsigned_seal.pop("payload_sha256", None)
    if (
        combined_seal.get("status") != "SEALED_BEFORE_PRIMARY_CASE_SELECTION"
        or not isinstance(seal_payload_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", seal_payload_sha256) is None
        or _sha(_canonical_bytes(unsigned_seal)) != seal_payload_sha256
    ):
        _fail("combined preprimary seal is invalid")
    if proof.get("combined_preprimary_seal_payload_sha256") != seal_payload_sha256:
        _fail("availability compiler proof does not bind exact combined preprimary seal")
    try:
        expected_proof = verify_compiled_availability(
            root,
            root / Path(*PurePosixPath(raw_availability_row["path"]).parts),
            root / Path(*PurePosixPath(compiled_row["path"]).parts),
            root / Path(*PurePosixPath(combined_seal_row["path"]).parts),
        )
    except Exception as exc:
        _fail(f"frozen availability verifier replay failed: {exc}")
    if _canonical_bytes(proof) != _canonical_bytes(expected_proof):
        _fail("availability compiler proof is not exact frozen-verifier output")
    return {
        "schema_version": AUDIT_VERSION,
        "status": "PASS",
        "selected_source_manifest": {key: selected_manifest_row[key] for key in ("path", "sha256", "bytes")},
        "source_inventory": {key: source_inventory_row[key] for key in ("path", "sha256", "bytes")},
        "event_ledger": {key: event_row[key] for key in ("path", "sha256", "bytes")},
        "raw_availability_ledger": {key: raw_availability_row[key] for key in ("path", "sha256", "bytes")},
        "compiled_guaranteed_availability": {key: compiled_row[key] for key in ("path", "sha256", "bytes")},
        "availability_compiler_proof": {key: proof_row[key] for key in ("path", "sha256", "bytes")},
        "combined_preprimary_seal": {key: combined_seal_row[key] for key in ("path", "sha256", "bytes")},
        "inventory_exact": True,
        "event_inventory_exact": True,
        "raw_available_at_forbidden": True,
        "compiled_timing_exact": True,
        "counts": {
            "source_artifacts": source_count,
            "events": len(events),
            "released_events": len(released),
            "withheld_events": len(withheld),
            "cuts": len(compiled_value["cut_manifest"]),
        },
        "event_inventory_sha256": _sha(_canonical_bytes(event_ids)),
    }


def compile_closure(root: Path, aggregate_path: Path, audit_output_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    root = root.resolve(strict=True)
    aggregate_path = aggregate_path.resolve(strict=True)
    aggregate_ref, manifests, manifest_refs, traces, protocol = _load_roles(root, aggregate_path)
    dag = _validate_dag(manifests, manifest_refs, protocol)
    selected_manifest = _one(manifests, "screener", "outputs", "immutable_source_manifest")
    source_inventory = _one(manifests, "extractor", "outputs", "source_inventory")
    event_ledger = _one(manifests, "extractor", "outputs", "event_ledger")
    raw_availability = _one(manifests, "extractor", "outputs", AVAILABILITY_RAW)
    compiled = _one(manifests, "extractor", "outputs", AVAILABILITY_COMPILED)
    sealed_compiled = _one(manifests, "source_auditor", "outputs", AVAILABILITY_SEALED)
    sealed_proof = _one(manifests, "source_auditor", "outputs", AVAILABILITY_PROOF_SEALED)
    combined_seal = _one(manifests, "source_auditor", "inputs", "combined_preprimary_seal")
    for upstream in (raw_availability, compiled):
        candidates = [row for row in manifests["source_auditor"]["inputs"] if row["data_class"] == upstream["data_class"]]
        if len(candidates) != 1 or _typed_ref(candidates[0]) != _typed_ref(upstream):
            _fail(f"source_auditor does not consume exact {upstream['data_class']}")
    if sealed_compiled["sha256"] != compiled["sha256"] or sealed_compiled["bytes"] != compiled["bytes"]:
        _fail("source_auditor sealed compiled availability changes compiler bytes")

    required_lineage = {
        "extractor": {
            AVAILABILITY_COMPILER_REL: _ref(root, root / AVAILABILITY_COMPILER_REL)["sha256"],
        },
        "source_auditor": {
            AVAILABILITY_VERIFIER_REL: _ref(root, root / AVAILABILITY_VERIFIER_REL)["sha256"],
        },
    }
    for role, required in required_lineage.items():
        lineage_rows = traces[role].get("tool_lineage")
        actual_lineage = {
            row.get("tool_id"): row.get("version_or_build")
            for row in lineage_rows if isinstance(row, Mapping)
        } if isinstance(lineage_rows, list) else {}
        for tool_id, digest in required.items():
            if actual_lineage.get(tool_id) != digest:
                _fail(f"{role} tool lineage omits exact frozen tool hash: {tool_id}")

    sanitizer_inputs = (
        protocol.get("primary_execution_asset_contract", {})
        .get("evaluator_sanitized_runtime_ledger_compiler", {})
        .get("input_data_classes")
    )
    if not isinstance(sanitizer_inputs, list) or set(sanitizer_inputs) != SANITIZER_INPUTS or len(
        sanitizer_inputs
    ) != len(SANITIZER_INPUTS):
        _fail("sanitizer contract is not compiled-availability-only")

    audit = _validate_event_and_availability(
        root, selected_manifest, source_inventory, event_ledger, raw_availability, compiled,
        sealed_proof, combined_seal,
    )
    audit_ref = _ref(root, audit_output_path) if audit_output_path.exists() else None
    if audit_ref is None:
        # The caller writes audit first, then recomputes lineage so its content
        # reference cannot be guessed or self-referential.
        return audit, {}
    role_rows = []
    for role in ROLES:
        manifest_ref = _ref(root, root / next(
            row["path"] for row in _json(aggregate_path.read_bytes(), "role set")["manifests"] if row["role"] == role
        ))
        trace_ref = manifests[role]["tool_trace"]
        role_rows.append(
            {
                "role": role,
                "run_id": manifests[role]["run_id"],
                "manifest": manifest_ref,
                "tool_trace": {key: trace_ref[key] for key in ("path", "sha256", "bytes")},
                "started_at": manifests[role]["started_at"],
                "finished_at": manifests[role]["finished_at"],
            }
        )
    lineage = {
        "schema_version": LINEAGE_VERSION,
        "status": "PASS",
        "role_manifest_set": aggregate_ref,
        "event_ledger_audit": audit_ref,
        "roles": role_rows,
        "dag_edges": dag,
        "role_count": 8,
        "manifest_set_exact": True,
        "role_protocol_contracts_exact": True,
        "tool_traces_exact": True,
        "dag_exact": True,
        "timing_valid": True,
        "availability_chain": {
            "raw_assertions_producer": "extractor",
            "compiler_owner": AVAILABILITY_PRODUCER_ID,
            "source_auditor_consumer": "source_auditor",
            "proof_producer": "source_auditor",
            "canonical_combined_preprimary_seal": {
                key: combined_seal[key] for key in ("path", "sha256", "bytes")
            },
            "sealed_compiled_output": {key: sealed_compiled[key] for key in ("path", "sha256", "bytes")},
            "sealed_proof": {key: sealed_proof[key] for key in ("path", "sha256", "bytes")},
            "sanitizer_raw_timing_access_forbidden": True,
        },
    }
    return audit, lineage


def _write(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        _fail(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def run_compile(root: Path, aggregate: Path, audit_output: Path, lineage_output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if audit_output.resolve(strict=False) == lineage_output.resolve(strict=False):
        _fail("audit and lineage outputs must differ")
    audit, _ = compile_closure(root, aggregate, audit_output)
    _write(audit_output, audit)
    try:
        recomputed_audit, lineage = compile_closure(root, aggregate, audit_output)
        if _canonical_bytes(recomputed_audit) != _canonical_bytes(audit):
            _fail("non-deterministic event audit recomputation")
        _write(lineage_output, lineage)
    except Exception:
        audit_output.unlink(missing_ok=True)
        raise
    return audit, lineage


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, required=True)
    parser.add_argument("--role-manifest-set", type=Path, required=True)
    parser.add_argument("--event-ledger-audit", type=Path, required=True)
    parser.add_argument("--case-access-lineage", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        audit, lineage = run_compile(
            args.study_root,
            args.role_manifest_set,
            args.event_ledger_audit,
            args.case_access_lineage,
        )
        print(json.dumps({
            "status": "PASS",
            "event_inventory_sha256": audit["event_inventory_sha256"],
            "role_count": lineage["role_count"],
        }, sort_keys=True))
        return 0
    except (ClosureError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL_CLOSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
