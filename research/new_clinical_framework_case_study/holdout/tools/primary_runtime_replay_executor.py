#!/usr/bin/env python3
"""Blind, deterministic primary-holdout RuntimeV2 replay executor.

This is the sole clinical execution program of the ``evaluator`` role.  It
accepts exactly nine content-addressed, case-neutral input classes, compiles a
sanitized ordinal ledger to public RuntimeV2 events, recursively updates one
canonical patient state, and seals every query head before the next cut is
opened.  It never reads a source article, case identity, diagnosis, terminal
outcome, or oracle contents.  ``WASHOUT`` is intentionally not an authorable
ledger phase; it may appear only inside RuntimeV2-derived action memory/traces.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import socket
import sys
import sysconfig
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, NoReturn, Sequence


STUDY_ROOT = Path(__file__).resolve().parents[2]
if str(STUDY_ROOT) not in sys.path:
    sys.path.insert(0, str(STUDY_ROOT))

# Exclude modules already present in an embedding test runner or host process.
# Dependencies introduced by this executor (plus the explicit NCF runtime
# namespaces below) remain part of the auditable trace.
_IMPORT_BASELINE = frozenset(sys.modules)

from runtime_v2 import (  # noqa: E402
    PublicEvent,
    RuntimeV2,
    canonical_json_bytes,
    digest,
)
from holdout.tools.event_ledger_replay import (  # noqa: E402
    ReplayBundleRecorder,
    verify_fresh_process_replay,
)


TOOL_REL = "holdout/tools/primary_runtime_replay_executor.py"
INPUT_SCHEMA_VERSION = "NCF-PRIMARY-RUNTIME-REPLAY-INPUT-MANIFEST-1.0.0"
RUNTIME_OUTPUT_VERSION = "NCF-PRIMARY-RUNTIME-OUTPUT-1.0.0"
REPLAY_SEAL_VERSION = "NCF-PRIMARY-RUNTIME-REPLAY-SEAL-1.0.0"
MAPPED_CONSUMPTION_VERSION = "NCF-MAPPED-OBSERVATION-CONSUMPTION-1.1.0"
EVENT_SCHEMA_VERSION = "new-clinical-runtime.event.v2.1"

RUNTIME_OUTPUT_SCHEMA_ID = "ncf.data.runtime-output.v1"
REPLAY_SEAL_SCHEMA_ID = "ncf.data.replay-seal.v1"
MAPPED_CONSUMPTION_SCHEMA_ID = "ncf.mapped-observation-consumption.v1"
REPLAY_BUNDLE_SCHEMA_ID = "ncf.holdout.event-ledger-replay-bundle.v1"
DEPENDENCY_TRACE_VERSION = "NCF-PRIMARY-RUNTIME-DEPENDENCY-TRACE-1.0.0"

EXPECTED_INPUT_ROLES = {
    "evaluator_sanitized_runtime_ledger",
    "sealed_concept_map",
    "model_pack",
    "runtime",
    "scoring_contract",
    "protocol",
    "combined_preprimary_seal",
    "oracle_seal_hash_only",
    "sanitized_id_type_unit_registry",
}
EXPECTED_INPUT_SCHEMA_IDS = {
    "evaluator_sanitized_runtime_ledger": "ncf.evaluator-sanitized-runtime-ledger.v1",
    "sealed_concept_map": "ncf.data.sealed-concept-map.v1",
    "model_pack": "ncf.data.model-pack.v1",
    "runtime": "ncf.data.runtime.v1",
    "scoring_contract": "ncf.data.scoring-contract.v1",
    "protocol": "ncf.data.protocol.v1",
    "combined_preprimary_seal": "ncf.data.combined-preprimary-seal.v1",
    "oracle_seal_hash_only": "ncf.data.oracle-seal-hash-only.v1",
    "sanitized_id_type_unit_registry": "ncf.data.sanitized-id-type-unit-registry.v1",
}
LIFECYCLE_PHASES = {
    "ORDERED",
    "STARTED",
    "CONTINUED",
    "DOSE_CHANGED",
    "HELD",
    "RESUMED",
    "STOPPED",
    "COMPLETED",
}
PHASE_TO_RUNTIME = {
    "ORDERED": "PlannedAction",
    "STARTED": "ActionStarted",
    "CONTINUED": "ActionContinued",
    "DOSE_CHANGED": "ActionDoseChanged",
    "HELD": "ActionHeld",
    "RESUMED": "ActionContinued",
    "STOPPED": "ActionStopped",
    "COMPLETED": "ActionCompleted",
}
ACTIVE_PHASES = {"STARTED", "CONTINUED", "DOSE_CHANGED", "RESUMED"}
INACTIVE_PHASES = {"HELD", "STOPPED", "COMPLETED"}
DOSE_PHASES = {"STARTED", "CONTINUED", "DOSE_CHANGED", "RESUMED"}
RELIABILITY_WEIGHT = {"HIGH": 1.0, "MEDIUM": 0.65, "LOW": 0.25, "UNKNOWN": 0.0}
TRISTATE = {"TRUE", "FALSE", "UNKNOWN"}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
EVENT_ID_RE = re.compile(r"^EV-[0-9]{8}$")
ACTION_INSTANCE_RE = re.compile(r"^ACT-[0-9]{8}$")
SOURCE_TOKEN_RE = re.compile(r"^SC-[0-9]{8}$")
ALT_GROUP_RE = re.compile(r"^ARG-[0-9]{8}$")
RUN_ID_RE = re.compile(r"^RUN-[0-9a-f]{64}$")

FORBIDDEN_KEY_TOKENS = {
    "case_id", "diagnosis", "final_diagnosis", "expected_diagnosis",
    "published_diagnosis", "outcome", "terminal_outcome", "source_text",
    "source_locator", "pmid", "pmcid", "doi", "source_title", "article_title",
}


class ExecutionError(RuntimeError):
    """Fail-closed input, compilation, replay, or sealing error."""


def _fail(message: str) -> NoReturn:
    raise ExecutionError(message)


class _OfflineSocketGuard:
    """Fail closed on ordinary Python network APIs during the real replay."""

    def __init__(self) -> None:
        self.attempts: list[dict[str, str]] = []
        self._original_socket = socket.socket
        self._original_create_connection = socket.create_connection
        self._original_getaddrinfo = socket.getaddrinfo

    def _blocked(self, api: str, *args: Any, **kwargs: Any) -> NoReturn:
        self.attempts.append(
            {
                "api": api,
                "target": repr(args[0])[:256] if args else "<unspecified>",
            }
        )
        raise ExecutionError(f"network access forbidden during primary replay: {api}")

    def __enter__(self) -> "_OfflineSocketGuard":
        guard = self

        class GuardedSocket(self._original_socket):  # type: ignore[misc, valid-type]
            def connect(self, *args: Any, **kwargs: Any) -> NoReturn:  # type: ignore[override]
                return guard._blocked("socket.connect", *args, **kwargs)

            def connect_ex(self, *args: Any, **kwargs: Any) -> NoReturn:  # type: ignore[override]
                return guard._blocked("socket.connect_ex", *args, **kwargs)

            def sendto(self, *args: Any, **kwargs: Any) -> NoReturn:  # type: ignore[override]
                return guard._blocked("socket.sendto", *args, **kwargs)

        socket.socket = GuardedSocket  # type: ignore[assignment]
        socket.create_connection = lambda *args, **kwargs: self._blocked(  # type: ignore[assignment]
            "socket.create_connection", *args, **kwargs
        )
        socket.getaddrinfo = lambda *args, **kwargs: self._blocked(  # type: ignore[assignment]
            "socket.getaddrinfo", *args, **kwargs
        )
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        socket.socket = self._original_socket  # type: ignore[assignment]
        socket.create_connection = self._original_create_connection
        socket.getaddrinfo = self._original_getaddrinfo


def _dependency_trace(
    root: Path,
    *,
    guard: _OfflineSocketGuard,
    input_bindings: Sequence[Mapping[str, Any]],
    produced: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Capture the imports, artifact IO, and network control of this replay.

    Every concrete module origin is classified.  Only files inside the frozen
    NCF study root, the Python standard library, and built-in/frozen modules
    are approved.  Site-packages are intentionally not accepted implicitly;
    a future dependency must first be frozen into the contract.
    """

    resolved_root = root.resolve(strict=True)
    stdlib = Path(sysconfig.get_paths()["stdlib"]).resolve(strict=True)
    site_roots = {
        Path(value).resolve(strict=False)
        for value in (sysconfig.get_paths().get("purelib"), sysconfig.get_paths().get("platlib"))
        if value
    }
    module_rows: list[dict[str, Any]] = []
    builtin_or_frozen: list[str] = []
    outside: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    # Trace every module introduced after this executor established its import
    # baseline, plus the executor and explicit NCF namespaces.  The baseline
    # excludes modules inherited from an embedding unit-test runner while the
    # delta still catches transitive and runtime imports made by the real NCF
    # execution path.  In the primary CLI process this therefore includes all
    # dependencies introduced by RuntimeV2 and ledger replay, including any
    # unapproved third-party module.
    traced_names = {
        name
        for name in sys.modules
        if name not in _IMPORT_BASELINE
        or name == __name__
        or name == "runtime_v2"
        or name.startswith("runtime_v2.")
        or name == "holdout.tools.event_ledger_replay"
    }
    python_runtime_root = Path(sys.base_prefix).resolve(strict=True)
    for name in sorted(traced_names):
        module = sys.modules[name]
        canonical_name = (
            "holdout.tools.primary_runtime_replay_executor"
            if name == "__main__" and Path(str(getattr(module, "__file__", ""))).resolve(strict=False) == Path(__file__).resolve()
            else str(name)
        )
        origin = getattr(module, "__file__", None)
        if not origin:
            builtin_or_frozen.append(str(name))
            continue
        try:
            path = Path(str(origin)).resolve(strict=True)
        except OSError:
            outside.append({"module": str(name), "origin": str(origin), "reason": "UNRESOLVABLE"})
            continue
        key = (canonical_name, os.path.normcase(str(path)))
        if key in seen:
            continue
        seen.add(key)
        classification = "OUTSIDE_ALLOWLIST"
        serialized_origin = str(path)
        try:
            rel = path.relative_to(resolved_root)
            classification = "NCF_FROZEN_SOURCE"
            serialized_origin = PurePosixPath(*rel.parts).as_posix()
        except ValueError:
            in_site = any(path == site or site in path.parents for site in site_roots)
            if not in_site and (
                path == stdlib
                or stdlib in path.parents
                or path == python_runtime_root
                or python_runtime_root in path.parents
            ):
                classification = "PYTHON_STDLIB"
        raw = path.read_bytes()
        module_rows.append(
            {
                "module": canonical_name,
                "origin": serialized_origin,
                "classification": classification,
                "sha256": _sha(raw),
                "bytes": len(raw),
            }
        )
        if classification == "OUTSIDE_ALLOWLIST":
            outside.append({"module": canonical_name, "origin": str(path), "reason": "NOT_NCF_OR_STDLIB"})
    if outside:
        _fail(f"runtime imported modules outside frozen allowlist: {outside[:3]}")
    if guard.attempts:
        _fail("network access attempt detected during primary replay")
    return {
        "schema_version": DEPENDENCY_TRACE_VERSION,
        "trace_scope": "ACTUAL_PRIMARY_CASE_RUNTIME_REPLAY_PROCESS",
        "approved_origin_classes": [
            "NCF_FROZEN_SOURCE",
            "PYTHON_STDLIB",
            "BUILTIN_OR_FROZEN",
        ],
        "module_origins": module_rows,
        "builtin_or_frozen_modules": sorted(set(builtin_or_frozen)),
        "outside_allowlist": [],
        "io_trace": {
            "input_bindings": [dict(row) for row in input_bindings],
            "produced_artifacts": [dict(row) for row in produced],
        },
        "network_guard": {
            "control": "APPLICATION_SOCKET_GUARD_OFFLINE_NOT_OS_SANDBOX",
            "attempt_count": 0,
            "attempts": [],
            "passed": True,
        },
    }


def _canonical_file_bytes(value: Any) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _artifact_bytes(filename: str, schema_id: str, raw: bytes) -> dict[str, Any]:
    return {"filename": filename, "schema_id": schema_id, "sha256": _sha(raw), "bytes": len(raw)}


def _reject_forbidden(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_KEY_TOKENS:
                _fail(f"forbidden identity/source/oracle field at {path}.{key}")
            _reject_forbidden(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_forbidden(child, f"{path}[{index}]")
    elif isinstance(value, str):
        lowered = value.lower()
        if re.search(r"(?:pmid|pmcid|doi)\s*[:/]", lowered):
            _fail(f"forbidden source identifier value at {path}")
        if re.match(r"^[a-zA-Z]:[\\/]", value) or value.startswith("/"):
            _fail(f"absolute path forbidden at {path}")


def _resolve_ref(study_root: Path, row: Any, label: str) -> tuple[dict[str, Any], Path, bytes]:
    if not isinstance(row, Mapping):
        _fail(f"{label} must be an object")
    expected = {"ref_id", "role", "path", "sha256", "bytes", "schema_id"}
    if set(row) != expected:
        _fail(f"{label} keys mismatch")
    role = row.get("role")
    if role not in EXPECTED_INPUT_ROLES:
        _fail(f"{label} unknown role")
    if row.get("schema_id") != EXPECTED_INPUT_SCHEMA_IDS[role]:
        _fail(f"{label} schema_id mismatch")
    ref_id = row.get("ref_id")
    if not isinstance(ref_id, str) or not re.fullmatch(r"REF-[0-9a-f]{16,64}", ref_id):
        _fail(f"{label} invalid ref_id")
    path_text = row.get("path")
    if not isinstance(path_text, str):
        _fail(f"{label} path missing")
    rel = PurePosixPath(path_text)
    if rel.is_absolute() or rel.as_posix() != path_text or ".." in rel.parts or not rel.parts:
        _fail(f"{label} path must be canonical relative POSIX")
    root = study_root.resolve(strict=True)
    candidate = root.joinpath(*rel.parts)
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError:
        _fail(f"{label} path escapes study root")
    cursor = root
    for part in rel.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            _fail(f"{label} path contains symlink")
    if not resolved.is_file():
        _fail(f"{label} path is not a file")
    raw = resolved.read_bytes()
    if row.get("sha256") != _sha(raw) or row.get("bytes") != len(raw):
        _fail(f"{label} content address mismatch")
    return dict(row), resolved, raw


def _load_manifest(study_root: Path, manifest_path: Path) -> tuple[dict[str, Any], bytes, dict[str, dict[str, Any]], dict[str, Path], dict[str, Any]]:
    root = study_root.resolve(strict=True)
    path = manifest_path.resolve(strict=True)
    try:
        path.relative_to(root)
    except ValueError:
        _fail("input manifest outside study root")
    if path.is_symlink() or not path.is_file():
        _fail("input manifest missing or symlink")
    raw = path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _fail(f"invalid input manifest JSON: {exc}")
    if not isinstance(manifest, Mapping) or set(manifest) != {"schema_version", "execution_role", "inputs"}:
        _fail("input manifest shape mismatch")
    if manifest.get("schema_version") != INPUT_SCHEMA_VERSION or manifest.get("execution_role") != "evaluator":
        _fail("input manifest schema/role mismatch")
    rows = manifest.get("inputs")
    if not isinstance(rows, list) or len(rows) != 9:
        _fail("input manifest must contain exactly nine inputs")
    refs: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    docs: dict[str, Any] = {}
    ref_ids: set[str] = set()
    for index, row in enumerate(rows):
        ref, resolved, content = _resolve_ref(root, row, f"inputs[{index}]")
        role = ref["role"]
        if role in refs or ref["ref_id"] in ref_ids:
            _fail("duplicate input role/ref_id")
        try:
            doc = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            _fail(f"{role} must be UTF-8 JSON: {exc}")
        if role in {"evaluator_sanitized_runtime_ledger", "sealed_concept_map", "oracle_seal_hash_only"}:
            _reject_forbidden(doc, f"$.inputs.{role}")
        refs[role], paths[role], docs[role] = ref, resolved, doc
        ref_ids.add(ref["ref_id"])
    if set(refs) != EXPECTED_INPUT_ROLES:
        _fail("input roles are not the exact evaluator set")
    return dict(manifest), raw, refs, paths, docs


def _expect_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{label} must be an object")
    return dict(value)


def _expect_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{label} must be an array")
    return value


def _finite_number(text: Any, label: str) -> float:
    try:
        value = float(text)
    except (TypeError, ValueError) as exc:
        _fail(f"{label} is not numeric: {exc}")
    if not math.isfinite(value):
        _fail(f"{label} must be finite")
    return value


def _verify_run_and_transport_ids(ledger: Mapping[str, Any], combined: Mapping[str, Any]) -> None:
    payload_hash = combined.get("payload_sha256")
    if not isinstance(payload_hash, str) or not SHA256_RE.fullmatch(payload_hash):
        _fail("combined seal payload_sha256 invalid")
    # The source-auditor transport contract uses fixed-width, non-semantic
    # counters.  RUN is bound to the already-frozen execution surface.
    if ledger.get("opaque_run_id") != f"RUN-{payload_hash}":
        _fail("opaque_run_id is not derived from combined pre-primary seal")
    events = _expect_list(ledger.get("events"), "ledger.events")
    expected_event_ids = [f"EV-{index:08d}" for index in range(1, len(events) + 1)]
    actual_event_ids = [row.get("opaque_event_id") if isinstance(row, Mapping) else None for row in events]
    if actual_event_ids != expected_event_ids:
        _fail("opaque_event_ids are not fixed-width canonical row counters")
    action_order: dict[str, str] = {}
    alt_order: dict[str, str] = {}
    for row in events:
        lifecycle = row.get("action_lifecycle")
        if isinstance(lifecycle, Mapping):
            action = str(lifecycle.get("opaque_action_id"))
            if action not in action_order:
                action_order[action] = f"ACT-{len(action_order)+1:08d}"
        group = row.get("alternative_representation_group_id")
        if group is not None:
            group = str(group)
            if group not in alt_order:
                alt_order[group] = f"ARG-{len(alt_order)+1:08d}"
    if any(key != expected for key, expected in action_order.items()):
        _fail("action instance ids are not canonical first-appearance counters")
    if any(key != expected for key, expected in alt_order.items()):
        _fail("alternative group ids are not canonical first-appearance counters")


def _validate_ledger(ledger: Any, combined: Mapping[str, Any]) -> list[dict[str, Any]]:
    doc = _expect_dict(ledger, "sanitized ledger")
    if doc.get("schema_version") != "NCF-EVALUATOR-SANITIZED-RUNTIME-LEDGER-1.0.0":
        _fail("sanitized ledger schema mismatch")
    for flag in ("identity_removed", "source_text_removed", "source_locator_removed", "reversible_source_ids_removed"):
        if doc.get(flag) is not True:
            _fail(f"sanitized ledger {flag} must be true")
    events = _expect_list(doc.get("events"), "ledger.events")
    if not events:
        _fail("sanitized ledger is empty")
    _verify_run_and_transport_ids(doc, combined)
    previous_sort: tuple[int, str] | None = None
    for index, raw in enumerate(events):
        row = _expect_dict(raw, f"ledger.events[{index}]")
        required = {"opaque_event_id", "opaque_source_concept_token", "event_kind", "typed_value", "unit", "observed_epoch_ordinal", "available_epoch_ordinal", "reliability"}
        if not required.issubset(row):
            _fail(f"ledger.events[{index}] missing required fields")
        event_id = row["opaque_event_id"]
        token = row["opaque_source_concept_token"]
        if not EVENT_ID_RE.fullmatch(str(event_id)) or not SOURCE_TOKEN_RE.fullmatch(str(token)):
            _fail(f"ledger.events[{index}] invalid fixed-width transport id")
        observed = row["observed_epoch_ordinal"]
        available = row["available_epoch_ordinal"]
        if isinstance(observed, bool) or not isinstance(observed, int) or observed < 0:
            _fail("observed epoch must be nonnegative integer")
        if isinstance(available, bool) or not isinstance(available, int) or available < 0:
            _fail("available epoch must be nonnegative integer")
        key = (available, event_id)
        if previous_sort is not None and key < previous_sort:
            _fail("ledger events must be in canonical availability/event order")
        previous_sort = key
        if row["reliability"] not in RELIABILITY_WEIGHT:
            _fail("invalid reliability")
        value = _expect_dict(row["typed_value"], "typed_value")
        if set(value) != {"kind", "canonical"} or value.get("kind") not in {"NUMBER", "BOOLEAN", "CODE", "NULL"}:
            _fail("invalid typed_value")
        if "WASHOUT" in {str(value.get("canonical")).upper(), str(row.get("event_kind")).upper()}:
            _fail("WASHOUT is runtime-derived and forbidden in source ledger")
        kind = row["event_kind"]
        if kind == "OBSERVATION":
            q = _expect_dict(row.get("evidence_qualification"), "evidence_qualification")
            if set(q) != {"explicit_assertion", "target_scope", "adequate_method", "adequate_timing", "adequate_reliability"} or any(v not in TRISTATE for v in q.values()):
                _fail("invalid evidence_qualification")
            group = row.get("alternative_representation_group_id")
            if group is not None and not ALT_GROUP_RE.fullmatch(str(group)):
                _fail("invalid alternative group id")
            if "action_lifecycle" in row:
                _fail("observation cannot carry action lifecycle")
        elif kind in {"ACTION", "SUPPORT"}:
            lifecycle = _expect_dict(row.get("action_lifecycle"), "action_lifecycle")
            phase = lifecycle.get("phase")
            if phase not in LIFECYCLE_PHASES or phase == "WASHOUT":
                _fail("invalid/forbidden action phase")
            if not ACTION_INSTANCE_RE.fullmatch(str(lifecycle.get("opaque_action_id"))):
                _fail("invalid action instance id")
            if value.get("kind") != "CODE" or value.get("canonical") != phase:
                _fail("action typed_value must equal lifecycle phase")
            has_dose = "dose" in lifecycle or "dose_unit" in lifecycle
            if phase in DOSE_PHASES and not ("dose" in lifecycle and "dose_unit" in lifecycle):
                _fail("active/dose action phase requires dose and dose_unit")
            if phase not in DOSE_PHASES and has_dose:
                _fail("inactive/planned phase forbids dose")
        else:
            _fail("invalid event_kind")
    return [dict(row) for row in events]


def _validate_registry(registry: Any, model: Mapping[str, Any], model_ref_sha: str) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    doc = _expect_dict(registry, "sanitized registry")
    if doc.get("schema_version") != "NCF-MAPPER-SANITIZED-REGISTRY-1.0.0":
        _fail("sanitized registry schema mismatch")
    if doc.get("source_model_pack_sha256") != model_ref_sha:
        _fail("registry is not bound to model pack bytes")
    observations: dict[str, dict[str, Any]] = {}
    for raw in _expect_list(doc.get("observations"), "registry.observations"):
        row = _expect_dict(raw, "registry observation")
        cid = str(row.get("concept_id"))
        if cid in observations:
            _fail("duplicate registry observation")
        observations[cid] = row
    actions: dict[str, dict[str, Any]] = {}
    for raw in _expect_list(doc.get("actions"), "registry.actions"):
        row = _expect_dict(raw, "registry action")
        aid = str(row.get("action_id"))
        if aid in actions:
            _fail("duplicate registry action")
        actions[aid] = row
    model_obs = {str(row["concept_id"]): row for row in _expect_list(model.get("observations"), "model.observations")}
    model_actions = {str(row["action_id"]): row for row in _expect_list(model.get("actions"), "model.actions")}
    if set(observations) != set(model_obs) or set(actions) != set(model_actions):
        _fail("registry ids do not exactly cover model observations/actions")
    for cid, row in observations.items():
        model_row = model_obs[cid]
        expected_type = str(model_row.get("value_type", "")).upper()
        if expected_type == "NUMBER":
            expected_type = "NUMBER"
        if row.get("value_type") != expected_type or row.get("unit") != model_row.get("unit"):
            _fail(f"registry/model mismatch for observation {cid}")
    return observations, actions


def _validate_concept_map(value: Any, obs_registry: Mapping[str, Any], action_registry: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    doc = _expect_dict(value, "sealed concept map")
    if doc.get("schema_version") != "NCF-SEALED-CONCEPT-MAP-1.0.0":
        _fail("sealed concept map schema mismatch")
    result: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(_expect_list(doc.get("mappings"), "concept map mappings"), start=1):
        row = _expect_dict(raw, "concept mapping")
        token = str(row.get("opaque_source_concept_token"))
        if not SOURCE_TOKEN_RE.fullmatch(token) or token != f"SC-{index:08d}" or token in result:
            _fail("invalid/duplicate concept token mapping")
        if row.get("mapping_status") != "MAPPED":
            _fail("sealed concept map accepts only MAPPED rows")
        mapped = str(row.get("mapped_id"))
        entity = row.get("entity_type")
        registry = obs_registry if entity == "OBSERVATION" else action_registry if entity == "ACTION" else None
        if registry is None or mapped not in registry:
            _fail("concept mapping id/entity absent from registry")
        expected = registry[mapped]
        if row.get("unit") != expected.get("unit"):
            _fail("concept mapping unit differs from registry")
        expected_type = expected.get("value_type") if entity == "OBSERVATION" else "ACTION"
        if row.get("value_type") != expected_type:
            _fail("concept mapping value type differs from registry")
        result[token] = row
    return result


def _verify_combined_closure(study_root: Path, refs: Mapping[str, Mapping[str, Any]], docs: Mapping[str, Any], *, verifier: Callable[[Path, Path | None], Mapping[str, Any]] | None) -> dict[str, Any]:
    seal = _expect_dict(docs["combined_preprimary_seal"], "combined seal")
    payload = copy.deepcopy(seal)
    claimed = payload.pop("payload_sha256", None)
    if not isinstance(claimed, str) or claimed != _sha(canonical_json_bytes(payload)):
        _fail("combined seal payload digest mismatch")
    if seal.get("format_version") != "NCF-PRE-PRIMARY-HOLDOUT-SEAL-1.0.0" or seal.get("status") != "SEALED_BEFORE_PRIMARY_CASE_SELECTION":
        _fail("combined seal is not final pre-primary contract")
    invariants = _expect_dict(seal.get("invariants"), "combined seal invariants")
    for key in ("all_component_statuses_final", "component_seals_reverified", "execution_and_scoring_frozen_before_case_search", "primary_execution_generators_tests_and_schemas_bound"):
        if invariants.get(key) is not True:
            _fail(f"combined seal invariant false: {key}")
    if verifier is None:
        from holdout.tools.build_pre_primary_holdout_seal import verify_seal
        report = verify_seal(study_root, study_root / refs["combined_preprimary_seal"]["path"])
    else:
        report = verifier(study_root, study_root / refs["combined_preprimary_seal"]["path"])
    if not isinstance(report, Mapping) or report.get("status") != "PASS" or report.get("payload_sha256") != claimed:
        _fail("combined seal independent verification failed")
    bindings = _expect_dict(seal.get("bindings"), "combined seal bindings")
    runtime = _expect_dict(bindings.get("runtime"), "combined runtime binding")
    model = _expect_dict(bindings.get("generic_model"), "combined model binding")
    execution = _expect_dict(bindings.get("primary_execution"), "combined execution binding")

    def assert_ref(binding: Any, role: str, label: str) -> None:
        row = _expect_dict(binding, label)
        ref = refs[role]
        if row.get("path") != ref["path"] or row.get("sha256") != ref["sha256"] or row.get("bytes") != ref["bytes"]:
            _fail(f"combined seal does not bind actual {role}")

    assert_ref(runtime.get("manifest"), "runtime", "runtime manifest binding")
    assert_ref(model.get("model_pack"), "model_pack", "model pack binding")
    assert_ref(execution.get("protocol_json"), "protocol", "protocol binding")
    assert_ref(execution.get("scoring_contract"), "scoring_contract", "scoring binding")
    required_assets = {
        "primary_runtime_replay_executor": TOOL_REL,
        "primary_runtime_replay_executor_test": "holdout/tools/test_primary_runtime_replay_executor.py",
        "primary_runtime_replay_input_schema": "holdout/schemas/primary_runtime_replay_input_manifest.schema.json",
        "primary_runtime_output_schema": "holdout/schemas/primary_runtime_output.schema.json",
        "primary_runtime_replay_seal_schema": "holdout/schemas/primary_runtime_replay_seal.schema.json",
        "mapped_observation_schema": "holdout/schemas/mapped_observation_consumption.schema.json",
    }
    for key, expected_path in required_assets.items():
        row = _expect_dict(execution.get(key), f"combined execution {key}")
        path = study_root / expected_path
        raw = path.read_bytes()
        if row != {"path": expected_path, "sha256": _sha(raw), "bytes": len(raw)}:
            _fail(f"combined seal execution binding mismatch: {key}")
    tree = _expect_dict(model.get("recursive_source_tree"), "generic model source tree")
    files = _expect_list(tree.get("files"), "generic model source files")
    registry_ref = refs["sanitized_id_type_unit_registry"]
    if not any(row == {"path": registry_ref["path"], "sha256": registry_ref["sha256"], "bytes": registry_ref["bytes"]} for row in files):
        _fail("combined seal generic tree does not bind sanitized registry")
    return {"path": refs["combined_preprimary_seal"]["path"], "sha256": refs["combined_preprimary_seal"]["sha256"], "bytes": refs["combined_preprimary_seal"]["bytes"], "payload_sha256": claimed, "independent_verification_status": "PASS"}


def _typed_value(row: Mapping[str, Any], expected_type: str) -> tuple[Any, str | None]:
    typed = _expect_dict(row.get("typed_value"), "typed_value")
    kind = typed.get("kind")
    canonical = typed.get("canonical")
    if kind == "NULL":
        return None, "NULL_VALUE"
    if expected_type == "NUMBER":
        if kind != "NUMBER":
            return None, "VALUE_TYPE_MISMATCH"
        return _finite_number(canonical, "numeric observation"), None
    if expected_type == "BOOLEAN":
        if kind != "BOOLEAN" or canonical not in {"true", "false"}:
            return None, "VALUE_TYPE_MISMATCH"
        return canonical == "true", None
    if expected_type in {"CATEGORICAL", "ORDINAL"}:
        if kind != "CODE" or not isinstance(canonical, str):
            return None, "VALUE_TYPE_MISMATCH"
        return canonical.lower(), None
    return None, "UNSUPPORTED_VALUE_TYPE"


def _action_overlap(observation: Mapping[str, Any], action: Mapping[str, Any]) -> bool:
    observation_targets: set[tuple[str, str | None]] = set()
    for emission in observation.get("emissions", []):
        if not isinstance(emission, Mapping):
            continue
        process_id = str(emission.get("process_id") or "")
        update = emission.get("coordinate_update")
        coordinate_id = str(update.get("coordinate_id")) if isinstance(update, Mapping) and update.get("coordinate_id") else None
        observation_targets.add((process_id, coordinate_id))
    for effect in action.get("effects", []):
        if not isinstance(effect, Mapping):
            continue
        target = (str(effect.get("process_id") or ""), str(effect.get("coordinate_id")) if effect.get("coordinate_id") else None)
        if target in observation_targets:
            return True
        # An observation emission is process-conditioned even where its
        # coordinate update is narrower than the action's controlled
        # coordinate (for example EF/contractile dysfunction under inotropic
        # support acting on forward flow).  Same-process emission therefore is
        # an explicit masking route; a wholly unrelated process is not.
        if any(process_id == target[0] for process_id, _ in observation_targets):
            return True
    for effect in action.get("activation_effects", []):
        if isinstance(effect, Mapping) and any(process_id == str(effect.get("process_id") or "") for process_id, _ in observation_targets):
            return True
    return False


def _active_actions_at_sample(
    observation_row: Mapping[str, Any],
    ledger_events: Sequence[Mapping[str, Any]],
    mappings: Mapping[str, Mapping[str, Any]],
) -> tuple[list[str], list[str]]:
    sample = int(observation_row["observed_epoch_ordinal"])
    knowledge_cut = int(observation_row["available_epoch_ordinal"])
    state: dict[str, tuple[str, str]] = {}
    for row in ledger_events:
        if row.get("event_kind") not in {"ACTION", "SUPPORT"}:
            continue
        if int(row["available_epoch_ordinal"]) > knowledge_cut or int(row["observed_epoch_ordinal"]) > sample:
            continue
        lifecycle = row["action_lifecycle"]
        instance = str(lifecycle["opaque_action_id"])
        mapping = mappings.get(str(row["opaque_source_concept_token"]))
        if mapping is None or mapping.get("entity_type") != "ACTION":
            continue
        phase = str(lifecycle["phase"])
        mapped_id = str(mapping["mapped_id"])
        if phase in ACTIVE_PHASES:
            state[instance] = (mapped_id, phase)
        elif phase in INACTIVE_PHASES:
            state.pop(instance, None)
        # ORDERED remains record-only and never marks exposure active.
    instances = sorted(state)
    return sorted({state[item][0] for item in instances}), instances


def _conditioned_factor_available(observation: Mapping[str, Any], masking_action_ids: Sequence[str]) -> bool:
    declarations = observation.get("support_conditioned_factors") or observation.get("conditioned_factors") or []
    if not isinstance(declarations, list):
        return False
    declared: set[str] = set()
    for row in declarations:
        if isinstance(row, str):
            declared.add(row)
        elif isinstance(row, Mapping) and row.get("action_id"):
            declared.add(str(row["action_id"]))
    return bool(masking_action_ids) and set(masking_action_ids).issubset(declared)


def _select_alternative_representations(events: Sequence[Mapping[str, Any]]) -> tuple[dict[str, str], dict[str, list[str]]]:
    groups: dict[str, list[Mapping[str, Any]]] = {}
    for row in events:
        group = row.get("alternative_representation_group_id")
        if row.get("event_kind") == "OBSERVATION" and group is not None:
            groups.setdefault(str(group), []).append(row)
    selected: dict[str, str] = {}
    suppressed: dict[str, list[str]] = {}
    reliability_rank = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "UNKNOWN": 0}
    for group, rows in groups.items():
        def quality(row: Mapping[str, Any]) -> tuple[int, int, int, int, str]:
            q = row["evidence_qualification"]
            true_count = sum(value == "TRUE" for value in q.values())
            # min() below: negate quality so higher-quality evidence wins,
            # then use the earliest factual availability and canonical id.
            return (-true_count, -reliability_rank[row["reliability"]], int(row["available_epoch_ordinal"]), int(row["observed_epoch_ordinal"]), str(row["opaque_event_id"]))
        winner = min(rows, key=quality)
        selected[group] = str(winner["opaque_event_id"])
        suppressed[group] = sorted(str(row["opaque_event_id"]) for row in rows if row is not winner)
    return selected, suppressed


def _compile_events(
    ledger_events: Sequence[Mapping[str, Any]],
    mappings: Mapping[str, Mapping[str, Any]],
    obs_registry: Mapping[str, Mapping[str, Any]],
    action_registry: Mapping[str, Mapping[str, Any]],
    model: Mapping[str, Any],
) -> tuple[list[PublicEvent], list[dict[str, Any]]]:
    model_obs = {str(row["concept_id"]): row for row in model["observations"]}
    model_actions = {str(row["action_id"]): row for row in model["actions"]}
    selected, suppressed = _select_alternative_representations(ledger_events)
    result: list[PublicEvent] = []
    consumption: list[dict[str, Any]] = []
    for row in ledger_events:
        event_id = str(row["opaque_event_id"])
        token = str(row["opaque_source_concept_token"])
        observed = int(row["observed_epoch_ordinal"])
        available = int(row["available_epoch_ordinal"])
        mapping = mappings.get(token)
        base: dict[str, Any] = {
            "schema_version": EVENT_SCHEMA_VERSION,
            "event_id": event_id,
            "occurred_time": {"lower": observed, "upper": observed, "partial_order_id": f"epoch:{observed}"},
            "recorded_at": available,
            "available_at": available,
            "provenance": {
                "source_result_id": event_id,
                "source_kind": "evaluator_sanitized_ordinal_ledger",
                "opaque_source_concept_token": token,
            },
        }
        if row["event_kind"] in {"ACTION", "SUPPORT"}:
            if mapping is None or mapping.get("entity_type") != "ACTION":
                base.update({"event_type": "RecordOnly", "concept_id": "UNMAPPED_ACTION_LIFECYCLE", "rankable": False, "mapper_disposition_reason": "UNKNOWN_CONDITION"})
                result.append(PublicEvent.from_dict(base))
                continue
            action_id = str(mapping["mapped_id"])
            lifecycle = row["action_lifecycle"]
            phase = str(lifecycle["phase"])
            runtime_type = PHASE_TO_RUNTIME[phase]
            base.update({
                "event_type": runtime_type,
                "action_id": action_id,
                "exposure_id": str(lifecycle["opaque_action_id"]),
            })
            base["provenance"]["source_lifecycle_phase"] = phase
            if phase in DOSE_PHASES:
                dose_obj = _expect_dict(lifecycle["dose"], "action dose")
                if dose_obj.get("kind") != "NUMBER":
                    _fail("action dose must be NUMBER")
                dose = _finite_number(dose_obj.get("canonical"), "action dose")
                reference = _finite_number(model_actions[action_id].get("dose_reference", 1.0), "model dose_reference")
                if dose < 0 or dose > reference:
                    _fail(f"action dose outside frozen normalized range: {action_id}")
                if lifecycle.get("dose_unit") != action_registry[action_id].get("unit"):
                    _fail("action dose unit differs from sealed registry")
                base["dose"] = dose
                base["dose_unit"] = lifecycle.get("dose_unit")
            result.append(PublicEvent.from_dict(base))
            continue

        qualification = row["evidence_qualification"]
        basis = {key: qualification[key] == "TRUE" for key in qualification}
        unknown_q = [key for key, value in qualification.items() if value == "UNKNOWN"]
        false_q = [key for key, value in qualification.items() if value == "FALSE"]
        method_status = "UNKNOWN" if unknown_q else "FAILED" if false_q else "SATISFIED"
        reliability_status = "RELIABLE" if row["reliability"] == "HIGH" and basis["adequate_reliability"] else "UNKNOWN" if row["reliability"] == "UNKNOWN" or qualification["adequate_reliability"] == "UNKNOWN" else "LOW"
        mapped_id: str | None = None
        mapping_status = "UNMAPPED"
        unit_status = "NOT_APPLICABLE"
        normalized_unit = None
        value: Any = None
        value_error: str | None = None
        observation: Mapping[str, Any] | None = None
        if mapping is not None and mapping.get("entity_type") == "OBSERVATION":
            mapped_id = str(mapping["mapped_id"])
            observation = model_obs[mapped_id]
            registry_row = obs_registry[mapped_id]
            normalized_unit = registry_row.get("unit")
            unit_status = "SATISFIED" if row.get("unit") == normalized_unit else "FAILED"
            value, value_error = _typed_value(row, str(registry_row["value_type"]))
            mapping_status = "MAPPED" if value_error is None and unit_status != "FAILED" else "MAPPING_INVALID"
        group = row.get("alternative_representation_group_id")
        is_selected = group is None or selected[str(group)] == event_id
        active_action_ids, active_instances = _active_actions_at_sample(row, ledger_events, mappings)
        masking_action_ids: list[str] = []
        policy = observation.get("support_masking_policy") if observation else None
        if policy:
            masking_action_ids = sorted(action_id for action_id in active_action_ids if _action_overlap(observation, model_actions[action_id]))
        conditioned = bool(observation) and _conditioned_factor_available(observation, masking_action_ids)
        masking_risk = "PRESENT" if masking_action_ids else "NONE"
        masking_disposition = "CONSUME_CONDITIONED" if masking_action_ids and conditioned else "WITHHOLD_TO_MEASUREMENT_UNCERTAINTY" if masking_action_ids else "CONSUME_UNMASKED"
        reason: str | None = None
        disposition = "CONSUME"
        if mapping is None:
            disposition, reason = "RECORD_ONLY", "UNMAPPED_SOURCE_CONCEPT"
        elif mapping_status != "MAPPED":
            disposition, reason = "RECORD_ONLY", value_error or "UNIT_NORMALIZATION_FAILED"
        elif not is_selected:
            disposition, reason = "RECORD_ONLY", "ALTERNATIVE_REPRESENTATION_SUPPRESSED"
        elif method_status != "SATISFIED":
            disposition, reason = "WITHHOLD_TO_MEASUREMENT_UNCERTAINTY", "METHOD_REQUIREMENT_NOT_SATISFIED"
        elif reliability_status != "RELIABLE":
            disposition, reason = "WITHHOLD_TO_MEASUREMENT_UNCERTAINTY", "RELIABILITY_NOT_PRIMARY_RANKABLE"
        elif masking_action_ids and not conditioned:
            disposition, reason = "WITHHOLD_TO_MEASUREMENT_UNCERTAINTY", "ACTIVE_SUPPORT_MASKING_WITHOUT_CONDITIONED_FACTOR"
        if mapped_id is None:
            mapped_id = f"UNMAPPED::{token}"
        runtime_reason = {
            None: None,
            "UNMAPPED_SOURCE_CONCEPT": "UNKNOWN_CONDITION",
            "ALTERNATIVE_REPRESENTATION_SUPPRESSED": "UNKNOWN_CONDITION",
            "METHOD_REQUIREMENT_NOT_SATISFIED": "INVALID_METHOD",
            "RELIABILITY_NOT_PRIMARY_RANKABLE": "LOW_RELIABILITY",
            "ACTIVE_SUPPORT_MASKING_WITHOUT_CONDITIONED_FACTOR": "SUPPORT_MASKED",
            "UNIT_NORMALIZATION_FAILED": "INVALID_METHOD",
            "NULL_VALUE": "UNKNOWN_CONDITION",
            "VALUE_TYPE_MISMATCH": "INVALID_METHOD",
            "UNSUPPORTED_VALUE_TYPE": "INVALID_METHOD",
        }.get(reason, "UNKNOWN_CONDITION" if reason else None)
        base.update({
            "event_type": "ObservationAvailable",
            "sample_time": {"lower": observed, "upper": observed, "partial_order_id": f"epoch:{observed}"},
            "result_at": available,
            "concept_id": mapped_id,
            "value": value if value_error is None else None,
            "rankable": disposition == "CONSUME",
            "reliability": RELIABILITY_WEIGHT[row["reliability"]],
            "mapper_disposition_reason": runtime_reason,
            "support_masking": 1.0 if masking_action_ids else 0.0,
        })
        result.append(PublicEvent.from_dict(base))
        selected_ids = [selected[str(group)]] if group is not None else [event_id]
        suppressed_ids = suppressed.get(str(group), []) if group is not None else []
        consumption.append({
            "event_id": event_id,
            "source_result_id": event_id,
            "mapped_id": mapped_id if not mapped_id.startswith("UNMAPPED::") else None,
            "mapping_status": mapping_status,
            "method": {
                "requirement_status": method_status,
                "required_provenance_fields_present": sorted(key for key, value in qualification.items() if value == "TRUE"),
                "required_provenance_fields_missing": sorted(key for key, value in qualification.items() if value != "TRUE"),
            },
            "unit": {"normalization_status": unit_status, "source_unit": row.get("unit"), "normalized_unit": normalized_unit},
            "reliability": {"status": reliability_status, "basis": basis},
            "rankability_disposition": disposition,
            "support_masking": {
                "active_action_ids_at_sample": active_action_ids,
                "masking_action_ids": masking_action_ids,
                "masking_risk": masking_risk,
                "conditioned_factor_available": conditioned,
                "disposition": masking_disposition,
            },
            "alternative_representation": {"group_id": group, "selected_source_result_ids": selected_ids, "suppressed_source_result_ids": suppressed_ids},
            "runtime_event_type": "ObservationAvailable",
            "runtime_disposition_reason": reason,
        })
    result.sort(key=lambda event: (float(event.payload["available_at"]), event.event_id))
    consumption.sort(key=lambda row: row["event_id"])
    return result, consumption


def _state_coordinates(state: Mapping[str, Any]) -> dict[tuple[str, str], tuple[float, float, dict[str, float]]]:
    result: dict[tuple[str, str], tuple[float, float, dict[str, float]]] = {}
    for local in state.get("local_states", []):
        process_id = str(local["process_id"])
        modes = {str(row["mode_id"]): float(row["probability"]) for row in local.get("mode_posterior", [])}
        for coordinate in local.get("coordinates", []):
            distribution = coordinate["distribution"]
            result[(process_id, str(coordinate["coordinate_id"]))] = (float(distribution["mean"]), max(float(distribution["sd"]), 1e-9), modes)
    return result


def _persistence_baseline(state: Mapping[str, Any], state_hash: str) -> dict[str, Any]:
    coordinates = []
    directions = []
    local_modes = []
    for local in state.get("local_states", []):
        process_id = str(local["process_id"])
        local_modes.append({"process_id": process_id, "probabilities": {str(row["mode_id"]): float(row["probability"]) for row in local.get("mode_posterior", [])}})
        for coordinate in local.get("coordinates", []):
            distribution = coordinate["distribution"]
            coordinates.append({
                "process_id": process_id,
                "coordinate_id": str(coordinate["coordinate_id"]),
                "family": "truncated_normal",
                "mean": float(distribution["mean"]),
                "scale": max(float(distribution["sd"]), 1e-9),
                "support": copy.deepcopy(coordinate["support"]),
            })
            directions.append({"process_id": process_id, "coordinate_id": str(coordinate["coordinate_id"]), "probabilities": {"increase": 0.1, "decrease": 0.1, "stable": 0.8}})
    activation = [{"process_id": str(row["process_id"]), "p_active": float(row["p_active"])} for row in state["active_process_posterior"]["process_marginals"]]
    support = {
        "schema_version": "ncf.predictive-support.v1",
        "scoring_rule_id": "truncated-normal-plus-categorical-log-score-v1",
        "continuous_coordinates": sorted(coordinates, key=lambda row: (row["process_id"], row["coordinate_id"])),
        "coordinate_directions": sorted(directions, key=lambda row: (row["process_id"], row["coordinate_id"])),
        "process_activation": sorted(activation, key=lambda row: row["process_id"]),
        "local_modes": sorted(local_modes, key=lambda row: row["process_id"]),
    }
    return {
        "schema_version": "ncf.persistence-predictive-support.v1",
        "policy_id": "FROZEN_PERSISTENCE_BASELINE",
        "consumed_state_hash": state_hash,
        "assumptions": {"process_drift": False, "coupling": False, "mode_switch": False, "action_effect": False},
        "predictive_support": support,
    }


def _factor_effect_trace(
    factor_messages: Sequence[Mapping[str, Any]],
    consumption_records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Attach auditable RAISE/LOWER semantics to immutable runtime messages."""
    semantics = {
        str(row["source_result_id"]): {
            "source_result_id": str(row["source_result_id"]),
            "mapped_id": row.get("mapped_id"),
            "rankability_disposition": row.get("rankability_disposition"),
            "runtime_disposition_reason": row.get("runtime_disposition_reason"),
        }
        for row in consumption_records
    }
    result: list[dict[str, Any]] = []
    for raw in factor_messages:
        row = copy.deepcopy(dict(raw))
        likelihoods = row.get("log_likelihood_by_hypothesis", {})
        paired: dict[str, dict[str, float]] = {}
        if isinstance(likelihoods, Mapping):
            for key, value in likelihoods.items():
                match = re.fullmatch(r"process:(.+):(active|inactive)", str(key))
                if match:
                    paired.setdefault(match.group(1), {})[match.group(2)] = float(value)
        effects: list[dict[str, Any]] = []
        for process_id in sorted(paired):
            pair = paired[process_id]
            if set(pair) != {"active", "inactive"}:
                continue
            log_bayes_factor = pair["active"] - pair["inactive"]
            direction = "RAISE" if log_bayes_factor > 0.0 else "LOWER" if log_bayes_factor < 0.0 else "NEUTRAL"
            effects.append({
                "process_id": process_id,
                "direction": direction,
                "log_bayes_factor_active_vs_inactive": log_bayes_factor,
            })
        source_ids = [str(item) for item in row.get("source_result_ids", [])]
        row["derived_process_effects"] = effects
        row["source_event_semantics"] = [semantics[source] for source in source_ids if source in semantics]
        result.append(row)
    return result


def _bounded_log(value: float, floor: float) -> float:
    return min(0.0, max(math.log(floor), math.log(max(floor, value))))


def _score_support(support: Mapping[str, Any], current_state: Mapping[str, Any], next_state: Mapping[str, Any], *, floor: float, deadband: float) -> dict[str, Any]:
    current_coords = _state_coordinates(current_state)
    next_coords = _state_coordinates(next_state)
    components: list[dict[str, Any]] = []
    for row in support.get("continuous_coordinates", []):
        key = (str(row["process_id"]), str(row["coordinate_id"]))
        if key not in next_coords:
            continue
        realized = next_coords[key][0]
        lower = float(row["support"]["lower"])
        upper = float(row["support"]["upper"])
        if realized < lower or realized > upper:
            probability = 0.0
        else:
            scale = max(float(row["scale"]), 1e-9)
            z = (realized - float(row["mean"])) / scale
            probability = math.exp(-0.5 * z * z) / (scale * math.sqrt(2.0 * math.pi))
        components.append({"kind": "continuous_coordinate", "process_id": key[0], "coordinate_id": key[1], "realized_posterior_mean": realized, "bounded_log_score": _bounded_log(probability, floor), "positive_support": probability >= floor})
    direction_by_key = {(str(row["process_id"]), str(row["coordinate_id"])): row["probabilities"] for row in support.get("coordinate_directions", [])}
    for key, probabilities in direction_by_key.items():
        if key not in current_coords or key not in next_coords:
            continue
        delta = next_coords[key][0] - current_coords[key][0]
        direction = "increase" if delta >= deadband else "decrease" if delta <= -deadband else "stable"
        probability = float(probabilities.get(direction, 0.0))
        components.append({"kind": "coordinate_direction", "process_id": key[0], "coordinate_id": key[1], "realized_direction": direction, "realized_delta": delta, "bounded_log_score": _bounded_log(probability, floor), "positive_support": probability >= floor})
    next_activation = {str(row["process_id"]): float(row["p_active"]) for row in next_state["active_process_posterior"]["process_marginals"]}
    for row in support.get("process_activation", []):
        process_id = str(row["process_id"])
        if process_id not in next_activation:
            continue
        q = next_activation[process_id]
        p = min(1.0 - floor, max(floor, float(row["p_active"])))
        score = q * math.log(p) + (1.0 - q) * math.log(1.0 - p)
        components.append({"kind": "process_activation_posterior", "process_id": process_id, "realized_p_active": q, "bounded_log_score": min(0.0, max(math.log(floor), score)), "positive_support": p >= floor and (1.0 - p) >= floor})
    next_modes = {str(local["process_id"]): {str(row["mode_id"]): float(row["probability"]) for row in local.get("mode_posterior", [])} for local in next_state.get("local_states", [])}
    for row in support.get("local_modes", []):
        process_id = str(row["process_id"])
        if process_id not in next_modes:
            continue
        predicted = row["probabilities"]
        realized = next_modes[process_id]
        score = sum(q * math.log(max(floor, float(predicted.get(mode, 0.0)))) for mode, q in realized.items())
        components.append({"kind": "local_mode_posterior", "process_id": process_id, "realized_mode_posterior": realized, "bounded_log_score": min(0.0, max(math.log(floor), score)), "positive_support": all(float(predicted.get(mode, 0.0)) >= floor for mode, q in realized.items() if q > 0)})
    mean = sum(row["bounded_log_score"] for row in components) / len(components) if components else math.log(floor)
    return {"component_count": len(components), "components": components, "bounded_log_score": mean, "all_components_positive_support": bool(components) and all(row["positive_support"] for row in components)}


def _cut_core(
    *,
    sequence: int,
    cut: int,
    parent_seal: str | None,
    replay_record: Mapping[str, Any],
    state: Any,
    diagnosis: Mapping[str, Any],
    forecast: Mapping[str, Any],
    persistence: Mapping[str, Any],
    plan: Mapping[str, Any],
    consumption_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    wire = state.to_dict()
    processed = set(replay_record["processed_event_ids"])
    available_consumption = [copy.deepcopy(row) for row in consumption_records if row["event_id"] in processed]
    factor_messages = copy.deepcopy(wire["factor_graph_state"]["factor_messages"])
    factor_effect_trace = _factor_effect_trace(factor_messages, available_consumption)
    head_hashes = {
        "diagnosis": diagnosis.get("consumed_state_hash"),
        "forecast": forecast.get("consumed_state_hash"),
        "persistence_baseline": persistence.get("consumed_state_hash"),
        "plan": plan.get("consumed_state_hash"),
    }
    all_equal = set(head_hashes.values()) == {state.state_hash}
    if not all_equal:
        _fail("diagnose/forecast/plan did not consume the same canonical state")
    factor_sources = sorted({str(row.get("source_result_id")) for row in factor_messages if row.get("source_result_id")})
    cut_row = {
        "sequence": sequence,
        "cut_ordinal": cut,
        "parent_cut_seal_sha256": parent_seal,
        "new_event_ids": list(replay_record["expected_new_event_ids"]),
        "processed_event_ids": list(replay_record["processed_event_ids"]),
        "future_registered_event_ids": list(replay_record["future_registered_event_ids"]),
        "canonical_state_hash": state.state_hash,
        "canonical_state_bytes_sha256": digest(canonical_json_bytes(wire)),
        "canonical_state": wire,
        "diagnosis": copy.deepcopy(dict(diagnosis)),
        "forecast": copy.deepcopy(dict(forecast)),
        "persistence_baseline": copy.deepcopy(dict(persistence)),
        "plan": copy.deepcopy(dict(plan)),
        "consumption_trace": {
            "mapped_observation_records": available_consumption,
            "factor_message_source_result_ids": factor_sources,
            "recognized_result_ids": copy.deepcopy(wire["factor_graph_state"].get("recognized_result_ids", [])),
            "unrecognized_result_ids": copy.deepcopy(wire["factor_graph_state"].get("unrecognized_result_ids", [])),
            "unexplained_observations": copy.deepcopy(wire["epistemic_residual"].get("unexplained_observations", [])),
        },
        "factor_trace": factor_effect_trace,
        "mode_trace": [{"process_id": row["process_id"], "stratum_id": row["stratum_id"], "mode_posterior": copy.deepcopy(row["mode_posterior"]), "last_transition_cursor": row.get("last_transition_cursor")} for row in wire["local_states"]],
        "ood_trace": {"epistemic_residual": copy.deepcopy(wire["epistemic_residual"]), "diagnostic_epistemic": copy.deepcopy(diagnosis.get("epistemic")), "abstention_status": diagnosis.get("abstention_status")},
        "action_lifecycle_trace": {"action_memory": copy.deepcopy(wire["action_memory"]), "history_action_response_windows": copy.deepcopy(wire["history_summary"].get("action_response_windows", [])), "forecast_final_action_lifecycle": copy.deepcopy(forecast.get("final_action_lifecycle")), "forecast_policy_lifecycle_trace": copy.deepcopy(forecast.get("policy_lifecycle_trace", []))},
        "head_state_hashes": head_hashes,
        "head_state_hashes_all_equal": True,
    }
    cut_row["sealed_before_next_cut_sha256"] = digest(cut_row)
    return cut_row


def _oracle_hash_only(value: Any) -> str:
    doc = _expect_dict(value, "oracle seal hash only")
    allowed = {"schema_version", "oracle_seal_sha256"}
    if set(doc) != allowed or doc.get("schema_version") not in {"NCF-ORACLE-SEAL-HASH-ONLY-1.0.0", "ncf.data.oracle-seal-hash-only.v1"}:
        _fail("oracle hash-only artifact shape mismatch")
    value = doc.get("oracle_seal_sha256")
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        _fail("oracle hash-only artifact lacks a single SHA-256")
    return value


def verify_prospective_score_bindings(runtime_output: Mapping[str, Any]) -> dict[str, Any]:
    """Independently verify that post-cut scores bind, but never alter, cuts."""
    cuts = _expect_list(runtime_output.get("cuts"), "runtime output cuts")
    scores = _expect_list(runtime_output.get("prospective_scores"), "prospective scores")
    if len(scores) != max(0, len(cuts) - 1):
        _fail("prospective score count does not equal adjacent cut count")
    verified: list[dict[str, Any]] = []
    for index, raw_cut in enumerate(cuts):
        cut = _expect_dict(raw_cut, "runtime cut")
        claimed = cut.get("sealed_before_next_cut_sha256")
        core = copy.deepcopy(cut)
        core.pop("sealed_before_next_cut_sha256", None)
        recomputed = _sha(canonical_json_bytes(core))
        if claimed != recomputed:
            _fail(f"cut {index} seal mismatch")
        if index and cut.get("parent_cut_seal_sha256") != cuts[index - 1].get("sealed_before_next_cut_sha256"):
            _fail(f"cut {index} parent seal mismatch")
    for index, raw_score in enumerate(scores):
        score = _expect_dict(raw_score, "prospective score")
        left = _expect_dict(cuts[index], "forecast cut")
        right = _expect_dict(cuts[index + 1], "realization cut")
        checks = {
            "forecast_cut_ordinal": left.get("cut_ordinal"),
            "realization_cut_ordinal": right.get("cut_ordinal"),
            "forecast_cut_seal_sha256": left.get("sealed_before_next_cut_sha256"),
            "forecast_payload_sha256": _sha(canonical_json_bytes(left.get("forecast"))),
            "next_canonical_state_hash": right.get("canonical_state_hash"),
            "next_cut_parent_seal_sha256": right.get("parent_cut_seal_sha256"),
            "prospective_seal_verified": True,
        }
        for key, expected in checks.items():
            if score.get(key) != expected:
                _fail(f"prospective score {index} binding mismatch: {key}")
        claimed_binding = score.get("score_binding_sha256")
        binding_payload = copy.deepcopy(score)
        binding_payload.pop("score_binding_sha256", None)
        if claimed_binding != _sha(canonical_json_bytes(binding_payload)):
            _fail(f"prospective score {index} payload binding mismatch")
        verified.append({"score_ordinal": index, "forecast_cut_seal_sha256": checks["forecast_cut_seal_sha256"], "next_canonical_state_hash": checks["next_canonical_state_hash"]})
    return {"status": "PASS", "verified_score_count": len(verified), "verified_bindings": verified}


def _case_blind_process_priors(model: Mapping[str, Any]) -> list[dict[str, Any]]:
    priors = [
        {
            "process_id": str(row["process_id"]),
            "activation_prior": float(row["activation_prior"]),
            "prior_source": "frozen_model_pack",
        }
        for row in _expect_list(model.get("processes"), "model processes")
    ]
    priors.append({
        "process_id": "NCF_UNMODELED_PROCESS",
        "activation_prior": float(_expect_dict(model.get("epistemic"), "model epistemic")["unknown_prior"]),
        "prior_source": "frozen_model_pack_epistemic",
    })
    return sorted(priors, key=lambda row: row["process_id"])


def _write_once(path: Path, raw: bytes) -> None:
    if path.exists():
        _fail(f"refusing to overwrite output: {path.name}")
    path.write_bytes(raw)


def _execute_manifest_under_guard(
    study_root: Path,
    manifest_path: Path,
    output_dir: Path,
    *,
    dependency_guard: _OfflineSocketGuard,
    preprimary_verifier: Callable[[Path, Path | None], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute and seal a complete blind replay.

    ``preprimary_verifier`` exists solely for isolated unit fixtures.  The CLI
    always passes ``None`` and therefore invokes the independently frozen
    combined-seal verifier against the canonical seal.
    """

    root = study_root.resolve(strict=True)
    manifest, manifest_raw, refs, paths, docs = _load_manifest(root, manifest_path)
    combined_closure = _verify_combined_closure(root, refs, docs, verifier=preprimary_verifier)
    events = _validate_ledger(docs["evaluator_sanitized_runtime_ledger"], docs["combined_preprimary_seal"])
    model = _expect_dict(docs["model_pack"], "model pack")
    runtime_manifest = _expect_dict(docs["runtime"], "runtime manifest")
    if runtime_manifest.get("manifest_kind") != "runtime_v2_1_case_blind_implementation_manifest" or runtime_manifest.get("case_blind") is not True:
        _fail("runtime input is not frozen case-blind runtime manifest")
    scoring = _expect_dict(docs["scoring_contract"], "scoring contract")
    if scoring.get("status") != "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION" or scoring.get("architecture_version") != "NCF-ARCH-1.0.0":
        _fail("scoring contract is not frozen/final")
    protocol = _expect_dict(docs["protocol"], "execution protocol")
    if protocol.get("status") != "FROZEN_BEFORE_PRIMARY_CASE_SEARCH_OR_SELECTION" or protocol.get("protocol_version") != "1.1.0":
        _fail("execution protocol is not frozen/final")
    oracle_hash = _oracle_hash_only(docs["oracle_seal_hash_only"])
    obs_registry, action_registry = _validate_registry(docs["sanitized_id_type_unit_registry"], model, refs["model_pack"]["sha256"])
    mappings = _validate_concept_map(docs["sealed_concept_map"], obs_registry, action_registry)
    ledger_tokens = {str(row["opaque_source_concept_token"]) for row in events}
    if set(mappings) != ledger_tokens:
        _fail("sealed concept map must exactly cover ledger source tokens")
    compiled, consumption_records = _compile_events(events, mappings, obs_registry, action_registry, model)
    compiled_wire = [event.to_dict() for event in compiled]
    compiled_digest = digest(compiled_wire)

    runtime = RuntimeV2(model)
    if runtime.model_digest != runtime_manifest.get("model_digest"):
        _fail("runtime manifest model digest differs from provided model pack")
    cuts = sorted({int(event.payload["available_at"]) for event in compiled})
    if not cuts:
        _fail("compiled ledger has no availability cuts")
    recorder = ReplayBundleRecorder(runtime)
    states: list[Any] = []
    cut_rows: list[dict[str, Any]] = []
    parent_seal: str | None = None
    policies = [{"policy_id": "NO_NEW_ACTION", "start_actions": []}]
    for action_id in sorted(action_registry):
        action = next(row for row in model["actions"] if row["action_id"] == action_id)
        policies.append({"policy_id": f"START::{action_id}", "start_actions": [{"action_id": action_id, "dose": float(action.get("dose_reference", 1.0))}]})
    for sequence, cut in enumerate(cuts):
        if sequence == 0:
            state = recorder.initialize(compiled, cut=cut)
        else:
            state = recorder.update([], advance_to=cut)
        # Query order is frozen.  Each query validates and returns the same
        # canonical consumed_state_hash before the next cut is opened.
        diagnosis = runtime.diagnose(state)
        forecast = runtime.forecast(state, horizon=1)
        persistence = _persistence_baseline(state.to_dict(), state.state_hash)
        plan = runtime.plan(state, policies, horizon=1)
        replay_record = recorder.bundle["cuts"][-1]
        cut_row = _cut_core(
            sequence=sequence,
            cut=cut,
            parent_seal=parent_seal,
            replay_record=replay_record,
            state=state,
            diagnosis=diagnosis,
            forecast=forecast,
            persistence=persistence,
            plan=plan,
            consumption_records=consumption_records,
        )
        parent_seal = cut_row["sealed_before_next_cut_sha256"]
        cut_rows.append(cut_row)
        states.append(state)

    support_floor = float(scoring.get("prediction_case_consistency", {}).get("support_floor", 1e-12))
    deadband = float(scoring.get("prediction_case_consistency", {}).get("direction_deadband", 0.05))
    # Scores are deliberately derived *after* every cut has been sealed.  They
    # are not members of any cut payload, and therefore cannot feed back into
    # the prior forecast, state, or plan.  The explicit forecast-payload and
    # next-state hashes let a downstream gate independently reject a score
    # whose realization binding no longer matches the sealed replay.
    prospective: list[dict[str, Any]] = []
    for index in range(len(cut_rows) - 1):
        model_score = _score_support(cut_rows[index]["forecast"]["predictive_support"], states[index].to_dict(), states[index + 1].to_dict(), floor=support_floor, deadband=deadband)
        baseline_score = _score_support(cut_rows[index]["persistence_baseline"]["predictive_support"], states[index].to_dict(), states[index + 1].to_dict(), floor=support_floor, deadband=deadband)
        score_row = {
            "forecast_cut_ordinal": cut_rows[index]["cut_ordinal"],
            "realization_cut_ordinal": cut_rows[index + 1]["cut_ordinal"],
            "forecast_cut_seal_sha256": cut_rows[index]["sealed_before_next_cut_sha256"],
            "forecast_payload_sha256": _sha(canonical_json_bytes(cut_rows[index]["forecast"])),
            "next_canonical_state_hash": cut_rows[index + 1]["canonical_state_hash"],
            "next_cut_parent_seal_sha256": cut_rows[index + 1]["parent_cut_seal_sha256"],
            "prospective_seal_verified": cut_rows[index + 1]["parent_cut_seal_sha256"] == cut_rows[index]["sealed_before_next_cut_sha256"],
            "model": model_score,
            "persistence_baseline": baseline_score,
        }
        score_row["score_binding_sha256"] = _sha(canonical_json_bytes(score_row))
        prospective.append(score_row)

    bindings = [{"role": role, "sha256": refs[role]["sha256"], "bytes": refs[role]["bytes"], "schema_id": refs[role]["schema_id"]} for role in sorted(refs)]
    runtime_output = {
        "schema_version": RUNTIME_OUTPUT_VERSION,
        "execution_role": "evaluator",
        "case_blind": True,
        "input_manifest_sha256": _sha(manifest_raw),
        "input_bindings": bindings,
        "oracle_seal_sha256": oracle_hash,
        "case_blind_process_priors": _case_blind_process_priors(model),
        "compiled_event_ledger_sha256": compiled_digest,
        "cut_count": len(cut_rows),
        "cuts": cut_rows,
        "prospective_scores": prospective,
        "final_cut_seal_sha256": cut_rows[-1]["sealed_before_next_cut_sha256"],
        "raw_trace_contract": {
            "same_canonical_state_for_all_heads": True,
            "future_events_excluded_until_available": True,
            "washout_source_input_forbidden": True,
            "post_replay_recomputation_supported": True,
        },
    }
    verify_prospective_score_bindings(runtime_output)
    runtime_output_raw = _canonical_file_bytes(runtime_output)
    runtime_output_sha = _sha(runtime_output_raw)
    mapped = {
        "schema_version": MAPPED_CONSUMPTION_VERSION,
        "execution_role": "evaluator",
        "runtime_output_sha256": runtime_output_sha,
        "event_count": len(consumption_records),
        "records": consumption_records,
    }
    mapped_raw = _canonical_file_bytes(mapped)
    replay_bundle = recorder.sealed_bundle()
    replay_bundle_raw = _canonical_file_bytes(replay_bundle)
    fresh = verify_fresh_process_replay(replay_bundle, paths["model_pack"])
    if fresh.get("status") != "PASS":
        _fail("fresh process replay failed")

    output_dir = output_dir.resolve(strict=False)
    try:
        output_dir.relative_to(root)
    except ValueError:
        _fail("output directory must remain inside study root")
    if output_dir.is_symlink():
        _fail("output directory may not be symlink")
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime_path = output_dir / "runtime_output.json"
    bundle_path = output_dir / "runtime_event_ledger_replay_bundle.json"
    mapped_path = output_dir / "mapped_observation_consumption.json"
    seal_path = output_dir / "runtime_replay_seal.json"
    _write_once(runtime_path, runtime_output_raw)
    _write_once(bundle_path, replay_bundle_raw)
    _write_once(mapped_path, mapped_raw)

    tool_raw = (root / TOOL_REL).read_bytes()
    manifest_artifact = {"filename": manifest_path.name, "schema_id": "ncf.primary-runtime-replay-input-manifest.v1", "sha256": _sha(manifest_raw), "bytes": len(manifest_raw)}
    produced = [
        _artifact_bytes(runtime_path.name, RUNTIME_OUTPUT_SCHEMA_ID, runtime_output_raw),
        _artifact_bytes(bundle_path.name, REPLAY_BUNDLE_SCHEMA_ID, replay_bundle_raw),
        _artifact_bytes(mapped_path.name, MAPPED_CONSUMPTION_SCHEMA_ID, mapped_raw),
    ]
    dependency_trace = _dependency_trace(
        root,
        guard=dependency_guard,
        input_bindings=bindings,
        produced=produced,
    )
    seal = {
        "schema_version": REPLAY_SEAL_VERSION,
        "execution_role": "evaluator",
        "case_blind": True,
        "invocation_contract": {
            "executable": {"path": TOOL_REL, "sha256": _sha(tool_raw), "bytes": len(tool_raw)},
            "cli_template": "python holdout/tools/primary_runtime_replay_executor.py --study-root <root> --input-manifest <relative-manifest> --output-dir <relative-empty-dir>",
            "input_manifest_sha256": _sha(manifest_raw),
            "deterministic_output_filenames": [item["filename"] for item in produced],
            "network_access": "FORBIDDEN",
        },
        "input_manifest": manifest_artifact,
        "input_bindings": bindings,
        "combined_preprimary_closure": combined_closure,
        "runtime_output": produced[0],
        "event_ledger_replay_bundle": produced[1],
        "mapped_observation_consumption": produced[2],
        "fresh_process_replay": fresh,
        "dependency_trace": dependency_trace,
        "artifact_set_digest": digest(produced),
    }
    seal["seal_payload_sha256"] = digest(seal)
    seal_raw = _canonical_file_bytes(seal)
    _write_once(seal_path, seal_raw)
    return {
        "status": "PASS",
        "execution_role": "evaluator",
        "runtime_output": _artifact_bytes(runtime_path.name, RUNTIME_OUTPUT_SCHEMA_ID, runtime_output_raw),
        "replay_bundle": _artifact_bytes(bundle_path.name, REPLAY_BUNDLE_SCHEMA_ID, replay_bundle_raw),
        "mapped_observation_consumption": _artifact_bytes(mapped_path.name, MAPPED_CONSUMPTION_SCHEMA_ID, mapped_raw),
        "replay_seal": _artifact_bytes(seal_path.name, REPLAY_SEAL_SCHEMA_ID, seal_raw),
    }


def execute_manifest(
    study_root: Path,
    manifest_path: Path,
    output_dir: Path,
    *,
    preprimary_verifier: Callable[[Path, Path | None], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute the actual case replay with a fail-closed socket guard."""

    with _OfflineSocketGuard() as guard:
        return _execute_manifest_under_guard(
            study_root,
            manifest_path,
            output_dir,
            dependency_guard=guard,
            preprimary_verifier=preprimary_verifier,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-root", type=Path, default=STUDY_ROOT)
    parser.add_argument("--input-manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        root = args.study_root.resolve(strict=True)
        manifest = args.input_manifest if args.input_manifest.is_absolute() else root / args.input_manifest
        output = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
        result = execute_manifest(root, manifest, output)
        sys.stdout.buffer.write(_canonical_file_bytes(result))
        return 0
    except Exception as exc:
        error = {"status": "FAIL", "error_type": type(exc).__name__, "error": str(exc)}
        sys.stderr.buffer.write(_canonical_file_bytes(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ExecutionError",
    "execute_manifest",
    "main",
    "_action_overlap",
    "_compile_events",
]
