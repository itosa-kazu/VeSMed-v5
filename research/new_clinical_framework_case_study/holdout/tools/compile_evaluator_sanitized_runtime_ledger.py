#!/usr/bin/env python3
"""Compile a source-rich sealed ledger into the evaluator's opaque transport ledger.

The compiler is an external deterministic producer.  It runs only after the
source/event/availability ledgers and the concept map are sealed.  Source-facing
identifiers are used solely as join keys and never appear in either output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, NoReturn, Sequence


PRODUCER_ID = "evaluator-sanitized-runtime-ledger-compiler-v1"
INPUT_VERSION = "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-COMPILER-INPUT-1.0.0"
LEDGER_VERSION = "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-1.0.0"
PROOF_VERSION = "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-ASSIGNMENT-PROOF-1.0.0"
OUTPUT_LEDGER_BASENAME = "evaluator_sanitized_runtime_ledger.json"
OUTPUT_PROOF_BASENAME = "evaluator_sanitized_runtime_ledger_assignment_proof.json"

INPUT_SLOTS = (
    "sealed_event_ledger",
    "sealed_availability_ledger",
    "sealed_concept_map",
    "sanitized_id_type_unit_registry",
    "combined_preprimary_seal",
)
EXPECTED_INPUT_SCHEMA_IDS = {
    "sealed_event_ledger": "ncf.data.sealed-event-ledger.v1",
    "sealed_availability_ledger": "ncf.data.sealed-availability-ledger.v1",
    "sealed_concept_map": "ncf.data.sealed-concept-map.v1",
    "sanitized_id_type_unit_registry": "ncf.data.sanitized-id-type-unit-registry.v1",
    "combined_preprimary_seal": "ncf.data.combined-preprimary-seal.v1",
}
FROZEN_ASSETS = {
    "compiler": "holdout/tools/compile_evaluator_sanitized_runtime_ledger.py",
    "compiler_test": "holdout/tools/test_compile_evaluator_sanitized_runtime_ledger.py",
    "compiler_input_schema": "holdout/schemas/evaluator_sanitized_runtime_ledger_compiler_input.schema.json",
    "ledger_output_schema": "holdout/schemas/evaluator_sanitized_runtime_ledger.schema.json",
    "assignment_proof_schema": "holdout/schemas/evaluator_sanitized_runtime_ledger_assignment_proof.schema.json",
}
ALGORITHM = {
    "run_id": "RUN_PREFIX_PLUS_FULL_COMBINED_PREPRIMARY_PAYLOAD_SHA256",
    "event_id": "CANONICAL_LEDGER_ROW_ORDER_DECIMAL8_START1",
    "source_concept_id": "CANONICAL_LEDGER_FIRST_OCCURRENCE_DECIMAL8_START1",
    "action_id": "CANONICAL_LEDGER_FIRST_OCCURRENCE_DECIMAL8_START1",
    "alternative_group_id": "CANONICAL_LEDGER_FIRST_OCCURRENCE_DECIMAL8_START1",
}
QUALIFICATION_KEYS = (
    "explicit_assertion", "target_scope", "adequate_method",
    "adequate_timing", "adequate_reliability",
)
TRISTATE = {"TRUE", "FALSE", "UNKNOWN"}
RELIABILITY = {"HIGH", "MEDIUM", "LOW", "UNKNOWN"}
LIFECYCLE_PHASES = {
    "ORDERED", "STARTED", "CONTINUED", "DOSE_CHANGED",
    "HELD", "RESUMED", "STOPPED", "COMPLETED",
}
ACTIVE_DOSE_PHASES = {"STARTED", "CONTINUED", "DOSE_CHANGED", "RESUMED"}


class CompilerError(RuntimeError):
    pass


def _fail(message: str) -> NoReturn:
    raise CompilerError(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        _fail(f"value is not canonical JSON: {exc}")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _content_ref(path: Path, study_root: Path, *, include_path: bool = True) -> dict[str, Any]:
    payload = path.read_bytes()
    result: dict[str, Any] = {"sha256": _sha_bytes(payload), "bytes": len(payload)}
    if include_path:
        result["path"] = path.relative_to(study_root).as_posix()
    return result


def _resolve_ref(study_root: Path, ref: Mapping[str, Any], label: str) -> tuple[Path, bytes]:
    rel_text = ref.get("path")
    if not isinstance(rel_text, str) or not rel_text:
        _fail(f"{label}.path missing")
    rel = PurePosixPath(rel_text)
    if rel.is_absolute() or ".." in rel.parts or re.match(r"^[A-Za-z]:", rel_text):
        _fail(f"{label}.path must be a contained relative path")
    path = (study_root / Path(*rel.parts)).resolve(strict=True)
    try:
        path.relative_to(study_root)
    except ValueError:
        _fail(f"{label}.path escapes study root")
    if not path.is_file() or path.is_symlink():
        _fail(f"{label} must be a regular non-symlink file")
    payload = path.read_bytes()
    if ref.get("sha256") != _sha_bytes(payload) or ref.get("bytes") != len(payload):
        _fail(f"{label} content reference mismatch")
    return path, payload


def _load_object(payload: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"{label} is not valid UTF-8 JSON: {exc}")
    if not isinstance(value, dict):
        _fail(f"{label} must be a JSON object")
    return value


def _verify_combined_seal(seal: Mapping[str, Any]) -> str:
    digest = seal.get("payload_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        _fail("combined preprimary seal payload_sha256 missing")
    unsigned = dict(seal)
    unsigned.pop("payload_sha256", None)
    if _sha_bytes(_canonical_bytes(unsigned)) != digest:
        _fail("combined preprimary seal payload digest mismatch")
    if seal.get("status") != "SEALED_BEFORE_PRIMARY_CASE_SELECTION":
        _fail("combined preprimary seal status mismatch")
    return digest


def _all_artifact_rows(value: Any) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    if isinstance(value, Mapping):
        if set(("path", "sha256", "bytes")).issubset(value):
            rows.append(value)
        for child in value.values():
            rows.extend(_all_artifact_rows(child))
    elif isinstance(value, list):
        for child in value:
            rows.extend(_all_artifact_rows(child))
    return rows


def _verify_frozen_assets(study_root: Path, seal: Mapping[str, Any]) -> list[dict[str, Any]]:
    by_path: dict[str, Mapping[str, Any]] = {}
    for row in _all_artifact_rows(seal.get("bindings")):
        path = row.get("path")
        if isinstance(path, str):
            by_path[path] = row
    result: list[dict[str, Any]] = []
    for role, rel_text in FROZEN_ASSETS.items():
        row = by_path.get(rel_text)
        if row is None:
            _fail(f"combined preprimary seal does not bind frozen asset: {rel_text}")
        path = (study_root / Path(*PurePosixPath(rel_text).parts)).resolve(strict=True)
        actual = _content_ref(path, study_root)
        if row.get("sha256") != actual["sha256"] or row.get("bytes") != actual["bytes"]:
            _fail(f"frozen asset differs from combined preprimary seal: {rel_text}")
        result.append({"asset_role": role, **actual})
    return result


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(f"{label} must be a non-negative integer ordinal")
    return value


def _availability_by_event(ledger: Mapping[str, Any]) -> dict[str, int]:
    rows = ledger.get("events")
    if not isinstance(rows, list):
        _fail("sealed availability ledger.events must be a list")
    result: dict[str, int] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            _fail(f"availability event {index} must be an object")
        event_id = row.get("source_event_id")
        if not isinstance(event_id, str) or not event_id or event_id in result:
            _fail(f"availability event {index} has missing or duplicate source_event_id")
        evidence = row.get("availability_evidence")
        if not isinstance(evidence, Mapping):
            _fail(f"availability event {event_id} lacks evidence")
        kind = evidence.get("kind")
        if kind == "EXACT":
            epoch = _integer(evidence.get("exact_epoch"), f"{event_id}.exact_epoch")
        elif kind in {"INTERVAL", "REPORTED_BATCH", "PARTIAL_ORDER"}:
            if evidence.get("latest_epoch") is None:
                _fail(f"availability event {event_id} has no bounded latest epoch")
            epoch = _integer(evidence.get("latest_epoch"), f"{event_id}.latest_epoch")
        elif kind == "UNKNOWN":
            _fail(f"availability event {event_id} is unknown and cannot enter evaluator ledger")
        else:
            _fail(f"availability event {event_id} has invalid evidence kind")
        result[event_id] = epoch
    return result


def _registry_maps(registry: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    observations = registry.get("observations")
    actions = registry.get("actions")
    if not isinstance(observations, list) or not isinstance(actions, list):
        _fail("sanitized registry observations/actions missing")
    obs: dict[str, Mapping[str, Any]] = {}
    act: dict[str, Mapping[str, Any]] = {}
    for row in observations:
        if not isinstance(row, Mapping) or not isinstance(row.get("concept_id"), str):
            _fail("invalid observation registry row")
        if row["concept_id"] in obs:
            _fail("duplicate observation registry id")
        obs[row["concept_id"]] = row
    for row in actions:
        if not isinstance(row, Mapping) or not isinstance(row.get("action_id"), str):
            _fail("invalid action registry row")
        if row["action_id"] in act:
            _fail("duplicate action registry id")
        act[row["action_id"]] = row
    return obs, act


def _concept_map_rows(concept_map: Mapping[str, Any], registry: Mapping[str, Any]) -> tuple[list[Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
    rows = concept_map.get("mappings")
    if not isinstance(rows, list) or not rows:
        _fail("sealed concept map.mappings must be a non-empty list")
    obs, act = _registry_maps(registry)
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, Mapping):
            _fail(f"concept mapping {index} must be an object")
        token = row.get("opaque_source_concept_token")
        expected = f"SC-{index:08d}"
        if token != expected:
            _fail("sealed concept map tokens must be canonical sequential SC identifiers")
        if token in result:
            _fail("duplicate sealed concept map token")
        mapped_id = row.get("mapped_id")
        entity = row.get("entity_type")
        if entity == "OBSERVATION":
            registry_row = obs.get(mapped_id)
            expected_value = registry_row.get("value_type") if registry_row else None
            if expected_value == "CATEGORICAL":
                expected_value = "CATEGORICAL"
        elif entity == "ACTION":
            registry_row = act.get(mapped_id)
            expected_value = "ACTION"
        else:
            _fail(f"concept mapping {token} has invalid entity_type")
        if registry_row is None:
            _fail(f"concept mapping {token} is absent from sanitized registry")
        if row.get("unit") != registry_row.get("unit") or row.get("value_type") != expected_value:
            _fail(f"concept mapping {token} disagrees with sanitized registry")
        if row.get("mapping_status") != "MAPPED":
            _fail(f"concept mapping {token} is not MAPPED")
        result[token] = row
    return list(rows), result


def _source_event_rows(ledger: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = ledger.get("events")
    if not isinstance(rows, list) or not rows:
        _fail("sealed event ledger.events must be a non-empty list")
    result: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, outer in enumerate(rows):
        if not isinstance(outer, Mapping):
            _fail(f"sealed event row {index} must be an object")
        event_id = outer.get("source_event_id")
        if not isinstance(event_id, str) or not event_id or event_id in seen:
            _fail(f"sealed event row {index} has missing or duplicate source_event_id")
        seen.add(event_id)
        inner = outer.get("runtime_event", outer)
        if not isinstance(inner, Mapping):
            _fail(f"sealed event {event_id} runtime_event must be an object")
        row = dict(inner)
        if "source_event_id" in row and row["source_event_id"] != event_id:
            _fail(f"sealed event {event_id} outer/inner identifiers disagree")
        row["source_event_id"] = event_id
        result.append(row)
    return result


def _copy_typed_value(value: Any, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or set(value) != {"kind", "canonical"}:
        _fail(f"{label} must be an exact typed_value object")
    kind, canonical = value.get("kind"), value.get("canonical")
    if kind not in {"NUMBER", "BOOLEAN", "CODE", "NULL"} or not isinstance(canonical, str):
        _fail(f"{label} has invalid kind/canonical")
    if kind == "NUMBER" and re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", canonical) is None:
        _fail(f"{label} number is not canonical")
    if kind == "BOOLEAN" and canonical not in {"true", "false"}:
        _fail(f"{label} boolean is not canonical")
    if kind == "NULL" and canonical != "null":
        _fail(f"{label} null is not canonical")
    return {"kind": kind, "canonical": canonical}


def compile_ledger(
    event_ledger: Mapping[str, Any], availability_ledger: Mapping[str, Any],
    concept_map: Mapping[str, Any], registry: Mapping[str, Any], seal_payload_sha256: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    source_rows = _source_event_rows(event_ledger)
    availability = _availability_by_event(availability_ledger)
    map_rows, mappings = _concept_map_rows(concept_map, registry)
    if set(availability) != {row["source_event_id"] for row in source_rows}:
        _fail("sealed event and availability ledgers have different event inventories")

    source_concepts: dict[str, str] = {}
    actions: dict[str, str] = {}
    groups: dict[str, str] = {}
    output_events: list[dict[str, Any]] = []
    for index, row in enumerate(source_rows, start=1):
        source_id = row["source_event_id"]
        source_token = row.get("source_concept_token", row.get("opaque_source_concept_token"))
        if not isinstance(source_token, str) or not source_token:
            _fail(f"sealed event {source_id} lacks source concept token")
        token = source_concepts.setdefault(source_token, f"SC-{len(source_concepts) + 1:08d}")
        if token not in mappings:
            _fail(f"sealed event {source_id} source concept is absent from concept map")
        event_kind = row.get("event_kind")
        if event_kind not in {"OBSERVATION", "ACTION", "SUPPORT"}:
            _fail(f"sealed event {source_id} has invalid event_kind")
        mapped_entity = mappings[token].get("entity_type")
        if (event_kind == "OBSERVATION" and mapped_entity != "OBSERVATION") or (
            event_kind in {"ACTION", "SUPPORT"} and mapped_entity != "ACTION"
        ):
            _fail(f"sealed event {source_id} kind disagrees with concept map")
        observed = _integer(row.get("observed_epoch_ordinal"), f"{source_id}.observed_epoch_ordinal")
        available = availability[source_id]
        if available < observed:
            _fail(f"sealed event {source_id} is available before it is observed")
        reliability = row.get("reliability")
        if reliability not in RELIABILITY:
            _fail(f"sealed event {source_id} has invalid reliability")
        out: dict[str, Any] = {
            "opaque_event_id": f"EV-{index:08d}",
            "opaque_source_concept_token": token,
            "event_kind": event_kind,
            "typed_value": _copy_typed_value(row.get("typed_value"), f"{source_id}.typed_value"),
            "unit": row.get("unit"),
            "observed_epoch_ordinal": observed,
            "available_epoch_ordinal": available,
            "reliability": reliability,
        }
        if row.get("unit") != mappings[token].get("unit"):
            _fail(f"sealed event {source_id} unit disagrees with concept map")
        if event_kind in {"ACTION", "SUPPORT"}:
            lifecycle = row.get("action_lifecycle")
            if not isinstance(lifecycle, Mapping):
                _fail(f"sealed event {source_id} lacks action_lifecycle")
            source_action_id = lifecycle.get("source_action_instance_id")
            if not isinstance(source_action_id, str) or not source_action_id:
                _fail(f"sealed event {source_id} lacks source_action_instance_id")
            action_id = actions.setdefault(source_action_id, f"ACT-{len(actions) + 1:08d}")
            phase = lifecycle.get("phase")
            if phase not in LIFECYCLE_PHASES:
                _fail(f"sealed event {source_id} has invalid action phase")
            target: dict[str, Any] = {"opaque_action_id": action_id, "phase": phase}
            if phase in ACTIVE_DOSE_PHASES:
                target["dose"] = _copy_typed_value(lifecycle.get("dose"), f"{source_id}.dose")
                if target["dose"]["kind"] != "NUMBER" or target["dose"]["canonical"].startswith("-"):
                    _fail(f"sealed event {source_id} action dose must be non-negative NUMBER")
                target["dose_unit"] = lifecycle.get("dose_unit")
            elif "dose" in lifecycle or "dose_unit" in lifecycle:
                _fail(f"sealed event {source_id} inactive lifecycle phase carries dose")
            out["action_lifecycle"] = target
        else:
            qualification = row.get("evidence_qualification")
            if not isinstance(qualification, Mapping) or set(qualification) != set(QUALIFICATION_KEYS):
                _fail(f"sealed event {source_id} lacks exact evidence qualification")
            if any(qualification[key] not in TRISTATE for key in QUALIFICATION_KEYS):
                _fail(f"sealed event {source_id} has invalid evidence qualification")
            out["evidence_qualification"] = {key: qualification[key] for key in QUALIFICATION_KEYS}
            source_group = row.get("source_alternative_representation_group_id")
            if source_group is None:
                out["alternative_representation_group_id"] = None
            elif isinstance(source_group, str) and source_group:
                out["alternative_representation_group_id"] = groups.setdefault(
                    source_group, f"ARG-{len(groups) + 1:08d}",
                )
            else:
                _fail(f"sealed event {source_id} has invalid alternative group")
        output_events.append(out)

    expected_tokens = [f"SC-{index:08d}" for index in range(1, len(source_concepts) + 1)]
    if [row["opaque_source_concept_token"] for row in map_rows] != expected_tokens:
        _fail("concept map row order is not canonical ledger source-concept first-occurrence order")
    if set(mappings) != set(expected_tokens):
        _fail("concept map and event ledger source-concept inventories differ")

    ledger = {
        "schema_version": LEDGER_VERSION,
        "opaque_run_id": f"RUN-{seal_payload_sha256}",
        "identity_removed": True,
        "source_text_removed": True,
        "source_locator_removed": True,
        "reversible_source_ids_removed": True,
        "events": output_events,
    }
    assignments = {
        "opaque_run_id": ledger["opaque_run_id"],
        "events": [
            {
                "opaque_event_id": row["opaque_event_id"],
                "opaque_source_concept_token": row["opaque_source_concept_token"],
                "opaque_action_id": row.get("action_lifecycle", {}).get("opaque_action_id"),
                "alternative_representation_group_id": row.get("alternative_representation_group_id"),
            }
            for row in output_events
        ],
    }
    summary = {
        "assignment_counts": {
            "events": len(output_events),
            "source_concepts": len(source_concepts),
            "actions": len(actions),
            "alternative_groups": len(groups),
        },
        "assignment_digest": _sha_bytes(_canonical_bytes(assignments)),
    }
    return ledger, summary


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        _fail(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    if temp.exists():
        temp.unlink()
    try:
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        if temp.exists():
            temp.unlink()


def run_compile(study_root: Path, manifest_path: Path, output_ledger: Path, proof_path: Path) -> dict[str, Any]:
    study_root = study_root.resolve(strict=True)
    manifest_path = manifest_path.resolve(strict=True)
    if manifest_path.is_symlink() or not manifest_path.is_file():
        _fail("input manifest must be a regular non-symlink file")
    try:
        manifest_path.relative_to(study_root)
    except ValueError:
        _fail("input manifest escapes study root")
    output_ledger = output_ledger.resolve(strict=False)
    proof_path = proof_path.resolve(strict=False)
    for path, label in ((output_ledger, "output ledger"), (proof_path, "assignment proof")):
        try:
            path.relative_to(study_root)
        except ValueError:
            _fail(f"{label} escapes study root")
    if output_ledger == proof_path:
        _fail("output ledger and assignment proof paths must differ")
    if output_ledger.name != OUTPUT_LEDGER_BASENAME or proof_path.name != OUTPUT_PROOF_BASENAME:
        _fail("output ledger and assignment proof must use frozen logical basenames")
    manifest_payload = manifest_path.read_bytes()
    manifest = _load_object(manifest_payload, "compiler input manifest")
    if manifest.get("schema_version") != INPUT_VERSION or set(manifest) != {"schema_version", "inputs"}:
        _fail("compiler input manifest schema mismatch")
    refs = manifest.get("inputs")
    if not isinstance(refs, Mapping) or tuple(refs.keys()) != INPUT_SLOTS:
        _fail("compiler input manifest must contain exact ordered input slots")

    values: dict[str, dict[str, Any]] = {}
    input_proof: list[dict[str, Any]] = []
    for slot in INPUT_SLOTS:
        ref = refs[slot]
        if not isinstance(ref, Mapping) or set(ref) != {"path", "sha256", "bytes", "data_class", "schema_id"}:
            _fail(f"input slot {slot} must be an exact artifact reference")
        if ref.get("data_class") != slot or ref.get("schema_id") != EXPECTED_INPUT_SCHEMA_IDS[slot]:
            _fail(f"input slot {slot} data_class/schema_id mismatch")
        _, payload = _resolve_ref(study_root, ref, f"input slot {slot}")
        values[slot] = _load_object(payload, slot)
        input_proof.append({"slot": slot, **dict(ref)})

    seal = values["combined_preprimary_seal"]
    seal_digest = _verify_combined_seal(seal)
    frozen_assets = _verify_frozen_assets(study_root, seal)
    ledger, summary = compile_ledger(
        values["sealed_event_ledger"], values["sealed_availability_ledger"],
        values["sealed_concept_map"], values["sanitized_id_type_unit_registry"], seal_digest,
    )
    _atomic_write_json(output_ledger, ledger)
    # The proof is replayed into a unique directory.  Bind the frozen logical
    # artifact name plus content address rather than the caller's directory,
    # otherwise an exact fresh replay would be impossible by construction.
    ledger_ref = _content_ref(output_ledger.resolve(strict=True), study_root, include_path=False)
    ledger_ref["path"] = OUTPUT_LEDGER_BASENAME
    proof = {
        "schema_version": PROOF_VERSION,
        "producer_id": PRODUCER_ID,
        "status": "PASS",
        "input_manifest": _content_ref(manifest_path, study_root),
        "inputs": input_proof,
        "output_ledger": {
            **ledger_ref,
            "data_class": "evaluator_sanitized_runtime_ledger",
            "schema_id": "ncf.evaluator-sanitized-runtime-ledger.v1",
        },
        "frozen_assets": frozen_assets,
        "combined_preprimary_seal_payload_sha256": seal_digest,
        "opaque_run_id": ledger["opaque_run_id"],
        "assignment_algorithm": ALGORITHM,
        **summary,
    }
    try:
        _atomic_write_json(proof_path, proof)
    except Exception:
        output_ledger.unlink(missing_ok=True)
        raise
    return proof


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    compile_parser = sub.add_parser("compile")
    compile_parser.add_argument("--study-root", type=Path, required=True)
    compile_parser.add_argument("--manifest", type=Path, required=True)
    compile_parser.add_argument("--output-ledger", type=Path, required=True)
    compile_parser.add_argument("--assignment-proof", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        proof = run_compile(args.study_root, args.manifest, args.output_ledger, args.assignment_proof)
        print(json.dumps({"status": "PASS", "assignment_digest": proof["assignment_digest"]}, sort_keys=True))
        return 0
    except (CompilerError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL_CLOSED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
