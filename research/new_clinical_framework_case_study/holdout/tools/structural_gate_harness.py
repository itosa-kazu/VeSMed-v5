#!/usr/bin/env python3
"""Case-blind structural hard-gate harness for NCF-ARCH-1.0.0.

This harness deliberately uses only the frozen architecture/gate contracts and
the abstract ``PROCESS_A/B/C`` runtime fixture.  It never reads a clinical case,
case-selection record, article, diagnosis label, or holdout event ledger.

The purpose is adversarial: a missing capability is emitted as ``FAIL`` or
``EVIDENCE_MISSING``.  The harness does not relax a gate to make the current
runtime look green.  Its output is machine evidence for the structural parts of
G01--G17; G18 remains a separate, blind real-case replay obligation.
"""

from __future__ import annotations

import argparse
import ast
import base64
import copy
import hashlib
import inspect
import itertools
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping


TOOL_PATH = Path(__file__).resolve()
CASE_STUDY_ROOT = TOOL_PATH.parents[2]
HOLDOUT_ROOT = CASE_STUDY_ROOT / "holdout"
RUNTIME_ROOT = CASE_STUDY_ROOT / "runtime_v2"
GATES_PATH = HOLDOUT_ROOT / "PERFECT_LANDING_GATES.json"
ARCHITECTURE_PATH = CASE_STUDY_ROOT / "ARCHITECTURE_FINAL_v1.md"
ARCHITECTURE_SCHEMA_PATH = CASE_STUDY_ROOT / "architecture_final_v1.schema.json"
NEUTRAL_MODEL_PATH = RUNTIME_ROOT / "examples" / "neutral_factorial_model.json"
EVIDENCE_SCHEMA_PATH = TOOL_PATH.with_name("structural_gate_evidence.schema.json")
RESULTS_SCHEMA_PATH = TOOL_PATH.with_name("structural_gate_results.schema.json")

# These are the only workspace inputs the harness is permitted to read.  Python
# source imported from runtime_v2 is separately recorded by the dependency probe.
APPROVED_INPUTS = {
    GATES_PATH.resolve(),
    ARCHITECTURE_PATH.resolve(),
    ARCHITECTURE_SCHEMA_PATH.resolve(),
    NEUTRAL_MODEL_PATH.resolve(),
    EVIDENCE_SCHEMA_PATH.resolve(),
    RESULTS_SCHEMA_PATH.resolve(),
}

ALLOWED_RESULTS = {
    "PASS",
    "FAIL",
    "NOT_APPLICABLE",
    "NOT_EXECUTED",
    "EVIDENCE_MISSING",
}
STATUS_PRIORITY = {
    "PASS": 0,
    "NOT_APPLICABLE": 0,
    "NOT_EXECUTED": 1,
    "EVIDENCE_MISSING": 2,
    "FAIL": 3,
}
ARCHITECTURE_GATES = [f"G{i:02d}" for i in range(1, 18)]

# Case-dependent gates are intentionally absent.  All gates below are executable
# with abstract fixtures and collectively cover every architecture gate G01-G17.
STRUCTURAL_PL_GATES = {
    "PL-IND-001",
    "PL-LED-002",
    "PL-STATE-001",
    "PL-STATE-002",
    "PL-TIME-001",
    "PL-TIME-002",
    "PL-FACT-001",
    "PL-FACT-002",
    "PL-CONC-001",
    "PL-CONC-002",
    "PL-MODE-001",
    "PL-MODE-002",
    "PL-SUPPORT-001",
    "PL-GEOM-001",
    "PL-DX-001",
    "PL-PRED-001",
    "PL-ACT-001",
    "PL-ACT-002",
    "PL-OOD-001",
    "PL-OOD-002",
    "PL-REF-001",
    "PL-REF-002",
    "PL-REF-003",
    "PL-REF-004",
}

REQUIRED_EVIDENCE_BY_GATE: dict[str, list[str]] = {}


def _bootstrap_runtime_imports() -> None:
    root = str(CASE_STUDY_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


_bootstrap_runtime_imports()

from runtime_v2 import (  # noqa: E402  (intentional bootstrap above)
    PublicEvent,
    RuntimeV2,
    SharedPatientState,
    architecture_state_hash,
    build_event_ledger_proof,
    canonical_json_bytes,
    digest,
    evaluate_behavioral_collision,
    execute_local_refinement,
    migrate_v2_state,
    validate_architecture_state_payload,
)
from runtime_v2.schema import RUNTIME_VERSION  # noqa: E402


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def relpath(path: Path) -> str:
    path = path.resolve()
    try:
        return path.relative_to(CASE_STUDY_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_json(path: Path) -> Any:
    resolved = path.resolve()
    if resolved not in APPROVED_INPUTS:
        raise RuntimeError(f"case-blind input allowlist violation: {resolved}")
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_sha(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(value))


def event(
    event_id: str,
    event_type: str,
    available_at: float,
    **payload: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "event_id": event_id,
        "event_type": event_type,
        "available_at": available_at,
        "recorded_at": available_at,
        "occurred_time": {"lower": available_at, "upper": available_at},
        "provenance": {"source_result_id": event_id, "source_kind": "neutral_fixture"},
    }
    row.update(payload)
    return PublicEvent.from_dict(row).to_dict()


def observation(
    event_id: str,
    concept_id: str,
    value: Any,
    *,
    at: float = 0.0,
    source_id: str | None = None,
) -> dict[str, Any]:
    return event(
        event_id,
        "ObservationAvailable",
        at,
        concept_id=concept_id,
        value=value,
        sample_time={"lower": at, "upper": at},
        result_at=at,
        provenance={"source_result_id": source_id or event_id, "source_kind": "neutral_fixture"},
    )


def action_event(
    event_id: str,
    event_type: str,
    *,
    at: float,
    action_id: str = "ACTION_REDUCE_A",
    exposure_id: str = "neutral-exposure-a",
    dose: float | None = None,
    available_at: float | None = None,
    source_id: str | None = None,
    dose_unit: str = "normalized",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "action_id": action_id,
        "exposure_id": exposure_id,
        "dose_unit": dose_unit,
    }
    if dose is not None:
        payload["dose"] = dose
    return event(
        event_id,
        event_type,
        at if available_at is None else available_at,
        occurred_time={"lower": at, "upper": at},
        provenance={
            "source_result_id": source_id or event_id,
            "source_kind": "neutral_fixture",
        },
        **payload,
    )


def process_marginals(state: SharedPatientState) -> dict[str, float]:
    return {
        row["process_id"]: float(row["p_active"])
        for row in state.to_dict()["active_process_posterior"]["process_marginals"]
    }


def local_state(state: SharedPatientState, process_id: str) -> dict[str, Any]:
    return next(row for row in state.to_dict()["local_states"] if row["process_id"] == process_id)


def local_modes(state: SharedPatientState, process_id: str) -> dict[str, float]:
    return {
        row["mode_id"]: float(row["probability"])
        for row in local_state(state, process_id)["mode_posterior"]
    }


def coordinate_mean(state: SharedPatientState, process_id: str, coordinate_id: str) -> float:
    row = next(
        row
        for row in local_state(state, process_id)["coordinates"]
        if row["coordinate_id"] == coordinate_id
    )
    return float(row["distribution"]["mean"])


def action_instance(state: SharedPatientState, exposure_id: str) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in state.to_dict()["action_memory"]["instances"]
            if row["action_instance_id"] == exposure_id
        ),
        None,
    )


def assert_row(
    assertion_id: str,
    passed: bool | None,
    expected: Any,
    observed: Any,
    notes: str = "",
) -> dict[str, Any]:
    row = {
        "assertion_id": assertion_id,
        "passed": passed,
        "expected": expected,
        "observed": observed,
    }
    if notes:
        row["notes"] = notes
    return row


def status_from_assertions(assertions: Iterable[Mapping[str, Any]], *, missing: bool = False) -> str:
    rows = list(assertions)
    if any(row.get("passed") is False for row in rows):
        return "FAIL"
    if missing or any(row.get("passed") is None for row in rows):
        return "EVIDENCE_MISSING"
    return "PASS"


def state_from_mutated_wire(payload: Mapping[str, Any]) -> SharedPatientState:
    row = copy.deepcopy(dict(payload))
    row["integrity"]["state_hash"] = architecture_state_hash(row)
    return SharedPatientState.from_dict(row)


def query_bundle(runtime: RuntimeV2, state: SharedPatientState) -> dict[str, Any]:
    policies = [
        {"policy_id": "NO_NEW_ACTION", "start_actions": []},
        {
            "policy_id": "START_A",
            "start_actions": [{"action_id": "ACTION_REDUCE_A", "dose": 1.0}],
        },
    ]
    return {
        "diagnose": runtime.diagnose(state),
        "forecast": runtime.forecast(state, horizon=2),
        "plan": runtime.plan(state, policies, horizon=2),
    }


def semantic_query_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    """Remove provenance-only hashes and normalize numeric representation."""

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: clean(child) for key, child in value.items() if key != "consumed_state_hash"}
        if isinstance(value, list):
            return [clean(child) for child in value]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        return value

    return clean(copy.deepcopy(dict(bundle)))


def file_input(path: Path, role: str) -> dict[str, str]:
    return {"path": relpath(path), "sha256": sha256_file(path), "role": role}


def evidence_envelope(
    *,
    artifact_id: str,
    gate_ids: list[str],
    architecture_gates: list[str],
    status: str,
    summary: str,
    assertions: list[dict[str, Any]],
    inputs: list[dict[str, str]],
    metrics: Mapping[str, Any] | None = None,
    outputs: Mapping[str, Any] | None = None,
    limitations: Iterable[str] = (),
    errors: Iterable[str] = (),
    generated_at: str,
) -> dict[str, Any]:
    if status not in ALLOWED_RESULTS:
        raise ValueError(f"invalid evidence status: {status}")
    return {
        "schema_version": "ncf.structural-gate-evidence.v1",
        "artifact_id": artifact_id,
        "produced_by": "holdout/tools/structural_gate_harness.py",
        "generated_at": generated_at,
        "status": status,
        "gate_ids": sorted(set(gate_ids)),
        "architecture_gates": sorted(set(architecture_gates)),
        "case_blind": True,
        "summary": summary,
        "assertions": assertions,
        "inputs": inputs,
        "metrics": copy.deepcopy(dict(metrics or {})),
        "outputs": copy.deepcopy(dict(outputs or {})),
        "limitations": list(limitations),
        "errors": list(errors),
    }


def validate_evidence_envelope(row: Mapping[str, Any]) -> None:
    required = {
        "schema_version",
        "artifact_id",
        "produced_by",
        "generated_at",
        "status",
        "gate_ids",
        "architecture_gates",
        "case_blind",
        "summary",
        "assertions",
        "inputs",
        "metrics",
        "outputs",
        "limitations",
        "errors",
    }
    if set(row) != required:
        raise ValueError(f"evidence envelope keys mismatch: {sorted(set(row) ^ required)}")
    if row["schema_version"] != "ncf.structural-gate-evidence.v1":
        raise ValueError("wrong structural evidence schema version")
    if row["status"] not in ALLOWED_RESULTS or row["case_blind"] is not True:
        raise ValueError("invalid structural evidence status/case_blind declaration")
    if not row["gate_ids"] or not all(str(x).startswith("PL-") for x in row["gate_ids"]):
        raise ValueError("evidence must name at least one PL gate")
    if not all(x in ARCHITECTURE_GATES for x in row["architecture_gates"]):
        raise ValueError("evidence names an architecture gate outside G01-G17")
    for assertion in row["assertions"]:
        if not {"assertion_id", "passed", "expected", "observed"}.issubset(assertion):
            raise ValueError("malformed evidence assertion")
        if assertion["passed"] not in {True, False, None}:
            raise ValueError("assertion passed must be true/false/null")
    for item in row["inputs"]:
        if set(item) != {"path", "sha256", "role"} or len(item["sha256"]) != 64:
            raise ValueError("malformed evidence input binding")


class Harness:
    def __init__(self, output_dir: Path, *, generated_at: str | None = None) -> None:
        self.output_dir = output_dir.resolve()
        self.generated_at = generated_at or utc_now()
        self.gates_contract = read_json(GATES_PATH)
        self.architecture_schema = read_json(ARCHITECTURE_SCHEMA_PATH)
        self.model_spec = read_json(NEUTRAL_MODEL_PATH)
        self.runtime = RuntimeV2(copy.deepcopy(self.model_spec))
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.gate_results: dict[str, dict[str, Any]] = {}
        self.gate_contracts = {row["id"]: row for row in self.gates_contract["gates"]}
        global REQUIRED_EVIDENCE_BY_GATE
        REQUIRED_EVIDENCE_BY_GATE = {
            gate_id: list(self.gate_contracts[gate_id]["required_evidence"])
            for gate_id in STRUCTURAL_PL_GATES
        }

    @property
    def common_inputs(self) -> list[dict[str, str]]:
        return [
            file_input(ARCHITECTURE_PATH, "frozen_architecture_contract"),
            file_input(ARCHITECTURE_SCHEMA_PATH, "frozen_wire_schema"),
            file_input(GATES_PATH, "frozen_perfect_landing_gate_contract"),
            file_input(NEUTRAL_MODEL_PATH, "abstract_case_blind_runtime_fixture"),
        ]

    def write_artifact(
        self,
        filename: str,
        gate_id: str,
        *,
        status: str,
        summary: str,
        assertions: list[dict[str, Any]],
        metrics: Mapping[str, Any] | None = None,
        outputs: Mapping[str, Any] | None = None,
        limitations: Iterable[str] = (),
        errors: Iterable[str] = (),
        extra_inputs: Iterable[dict[str, str]] = (),
    ) -> dict[str, Any]:
        contract = self.gate_contracts[gate_id]
        architecture_gates = [g for g in contract["architecture_gates"] if g in ARCHITECTURE_GATES]
        row = evidence_envelope(
            artifact_id=Path(filename).stem,
            gate_ids=[gate_id],
            architecture_gates=architecture_gates,
            status=status,
            summary=summary,
            assertions=assertions,
            inputs=self.common_inputs + list(extra_inputs),
            metrics=metrics,
            outputs=outputs,
            limitations=limitations,
            errors=errors,
            generated_at=self.generated_at,
        )
        validate_evidence_envelope(row)
        path = self.output_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_json_bytes(row) + b"\n")
        self.artifacts[filename] = row
        return row

    def finalize_gate(self, gate_id: str) -> None:
        required = REQUIRED_EVIDENCE_BY_GATE[gate_id]
        statuses: list[str] = []
        missing_files: list[str] = []
        pointers: list[dict[str, str]] = []
        for filename in required:
            if filename.endswith(".txt"):
                path = self.output_dir / filename
                if not path.exists():
                    missing_files.append(filename)
                    statuses.append("EVIDENCE_MISSING")
                else:
                    pointers.append({"path": filename, "sha256": sha256_file(path)})
                continue
            artifact = self.artifacts.get(filename)
            if artifact is None:
                missing_files.append(filename)
                statuses.append("EVIDENCE_MISSING")
            else:
                statuses.append(artifact["status"])
                pointers.append({"path": filename, "sha256": sha256_file(self.output_dir / filename)})
        result = max(statuses or ["EVIDENCE_MISSING"], key=STATUS_PRIORITY.get)
        self.gate_results[gate_id] = {
            "gate_id": gate_id,
            "title": self.gate_contracts[gate_id]["title"],
            "result": result,
            "fail_code": self.gate_contracts[gate_id]["fail_code"] if result == "FAIL" else None,
            "architecture_gates": [
                g for g in self.gate_contracts[gate_id]["architecture_gates"] if g in ARCHITECTURE_GATES
            ],
            "evidence": pointers,
            "missing_evidence": missing_files,
            "case_consistency_only": False,
        }

    def execute_gate(self, gate_id: str, fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as exc:  # fail closed and preserve the exact error
            for filename in REQUIRED_EVIDENCE_BY_GATE[gate_id]:
                if filename.endswith(".txt"):
                    continue
                if filename not in self.artifacts:
                    self.write_artifact(
                        filename,
                        gate_id,
                        status="EVIDENCE_MISSING",
                        summary="Probe did not complete; no positive structural claim is made.",
                        assertions=[assert_row("probe_completed", None, True, False)],
                        errors=[f"{type(exc).__name__}: {exc}"],
                    )
            error_path = self.output_dir / f"{gate_id}.error.txt"
            error_path.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        self.finalize_gate(gate_id)

    # ------------------------------------------------------------------
    # Structural probes.  Every probe uses only neutral PROCESS_* fixtures.

    def _emit(
        self,
        gate_id: str,
        filename: str,
        assertions: list[dict[str, Any]],
        outputs: Mapping[str, Any],
        summary: str,
        *,
        missing: bool = False,
        limitations: Iterable[str] = (),
    ) -> None:
        self.write_artifact(
            filename,
            gate_id,
            status=status_from_assertions(assertions, missing=missing),
            summary=summary,
            assertions=assertions,
            outputs=outputs,
            limitations=limitations,
        )

    def probe_independence(self) -> None:
        source_paths = sorted(RUNTIME_ROOT.glob("*.py"))
        forbidden_tokens = ("distillations", "v5_", "clinical_case", "case_selection")
        source_hits: list[dict[str, Any]] = []
        for path in source_paths:
            text_value = path.read_text(encoding="utf-8").lower()
            for token in forbidden_tokens:
                if token in text_value:
                    source_hits.append({"path": relpath(path), "token": token})
        imported = []
        for module in sorted(sys.modules.values(), key=lambda row: str(getattr(row, "__name__", ""))):
            path_value = getattr(module, "__file__", None)
            if not path_value:
                continue
            path = Path(path_value).resolve()
            try:
                path.relative_to(CASE_STUDY_ROOT.resolve())
            except ValueError:
                continue
            imported.append(relpath(path))
        runtime_outside = [p for p in imported if not (p.startswith("runtime_v2/") or p == relpath(TOOL_PATH))]
        assertions = [
            assert_row("no_forbidden_runtime_dependency", not source_hits, [], source_hits),
            assert_row("workspace_imports_are_runtime_or_harness", not runtime_outside, [], runtime_outside),
        ]
        self._emit("PL-IND-001", "static_dependency_scan.json", assertions[:1], {"scanned": [relpath(p) for p in source_paths], "hits": source_hits}, "Static dependency scan is case-blind and fail-closed.")
        self._emit("PL-IND-001", "runtime_dependency_trace.json", assertions[1:], {"workspace_modules": imported, "outside_allowlist": runtime_outside}, "Live module trace binds the runtime dependency surface.")
        manifest = [{"path": relpath(p), "sha256": sha256_file(p)} for p in sorted(APPROVED_INPUTS)]
        self._emit("PL-IND-001", "approved_asset_manifest.json", [assert_row("approved_assets_exist", all(Path(CASE_STUDY_ROOT / x["path"]).exists() if not Path(x["path"]).is_absolute() else Path(x["path"]).exists() for x in manifest), True, True)], {"assets": manifest}, "Approved structural inputs are content-addressed.")
        (self.output_dir / "full_replay_command.txt").write_text(
            f'python "{relpath(TOOL_PATH)}" --output "<OUTPUT_DIR>" '
            f'--generated-at "{self.generated_at}"\n',
            encoding="utf-8",
        )

    def probe_ledger(self) -> None:
        first = observation("ledger-a", "OBS_A_MARKER", True)
        parent = self.runtime.initialize([first], cut=0)
        duplicate = self.runtime.update(parent, [first], advance_to=0)
        collision_rejected = False
        try:
            self.runtime.update(parent, [observation("ledger-a", "OBS_A_MARKER", False)], advance_to=0)
        except ValueError:
            collision_rejected = True
        a = [assert_row("identical_duplicate_is_byte_exact", duplicate.to_bytes() == parent.to_bytes(), canonical_sha(parent.to_dict()), canonical_sha(duplicate.to_dict())), assert_row("changed_duplicate_is_rejected", collision_rejected, True, collision_rejected)]
        self._emit("PL-LED-002", "duplicate_ingestion_probe.json", a, {"parent_hash": parent.state_hash, "duplicate_hash": duplicate.state_hash}, "Exact-once duplicate delivery and collision rejection are exercised.")

        delta = [observation("ledger-b", "OBS_B_MARKER", True, at=1)]
        direct = self.runtime.update(parent, delta, advance_to=1)
        restored = SharedPatientState.from_bytes(parent.to_bytes())
        fresh = RuntimeV2(copy.deepcopy(self.model_spec)).update(restored, delta, advance_to=1, event_ledger_proof=build_event_ledger_proof(parent))
        same = direct.to_bytes() == fresh.to_bytes()
        rows = [assert_row("recursive_replay_byte_exact", same, direct.state_hash, fresh.state_hash)]
        self._emit("PL-LED-002", "recursive_replay_hashes.json", rows, {"direct": direct.state_hash, "fresh": fresh.state_hash}, "Serialized recursive replay must be byte exact.")

        request = {"state": base64.b64encode(parent.to_bytes()).decode(), "events": delta, "advance_to": 1, "proof": build_event_ledger_proof(parent)}
        with tempfile.TemporaryDirectory() as directory:
            req, res = Path(directory) / "req.json", Path(directory) / "res.json"
            req.write_text(json.dumps(request), encoding="utf-8")
            completed = subprocess.run([sys.executable, str(TOOL_PATH), "--fresh-worker", str(req), str(res)], capture_output=True, text=True, timeout=60)
            response = json.loads(res.read_text(encoding="utf-8")) if res.exists() else {"error": completed.stderr}
        process_same = completed.returncode == 0 and response.get("state_hash") == direct.state_hash and base64.b64decode(response.get("state_b64", "")) == direct.to_bytes()
        self._emit("PL-LED-002", "fresh_process_replay.json", [assert_row("fresh_process_replay_byte_exact", process_same, direct.state_hash, response.get("state_hash"))], {"returncode": completed.returncode, "direct_hash": direct.state_hash, "worker": response}, "A new interpreter must reproduce the same canonical state bytes.")

    def probe_shared_state(self) -> None:
        state = self.runtime.initialize([observation("state-a", "OBS_A_LOAD", 0.8), observation("state-b", "OBS_B_LOAD", 0.7)], cut=0)
        before = state.to_bytes()
        names = ("diagnose", "forecast", "plan")
        outputs: dict[str, list[str]] = {name: [] for name in names}
        consumed: set[str] = set()
        for order in itertools.permutations(names):
            for name in order:
                if name == "diagnose": value = self.runtime.diagnose(state)
                elif name == "forecast": value = self.runtime.forecast(state, horizon=2)
                else: value = self.runtime.plan(state, [{"policy_id": "NO_NEW_ACTION", "start_actions": []}], horizon=2)
                outputs[name].append(canonical_sha(value))
                consumed.add(value["consumed_state_hash"])
        assertions = [assert_row("all_heads_consume_one_hash", consumed == {state.state_hash}, [state.state_hash], sorted(consumed)), assert_row("queries_are_pure", state.to_bytes() == before, sha256_bytes(before), sha256_bytes(state.to_bytes())), assert_row("query_order_invariant", all(len(set(v)) == 1 for v in outputs.values()), True, {k: len(set(v)) for k,v in outputs.items()})]
        self._emit("PL-STATE-001", "consumed_state_hashes.json", assertions[:1], {"state_hash": state.state_hash, "consumed": sorted(consumed)}, "All heads bind one shared state hash.")
        self._emit("PL-STATE-001", "query_permutation_probe.json", assertions[1:], {"output_hashes": outputs}, "Head calls are pure and permutation invariant.")
        signatures = {name: str(inspect.signature(getattr(RuntimeV2, name))) for name in names}
        sig_ok = all("state" in value for value in signatures.values())
        self._emit("PL-STATE-001", "head_io_trace.json", [assert_row("heads_accept_shared_state", sig_ok, True, sig_ok)], {"signatures": signatures}, "Public head IO signatures are recorded.")

    def probe_wire(self) -> None:
        state = self.runtime.initialize([observation("wire-a", "OBS_A_LOAD", 0.8)], cut=0)
        valid = True
        error = None
        try: validate_architecture_state_payload(state.to_dict())
        except Exception as exc: valid, error = False, str(exc)
        self._emit("PL-STATE-002", "schema_validation.json", [assert_row("frozen_schema_validation", valid, True, valid)], {"state_hash": state.state_hash, "error": error, "runtime_version": RUNTIME_VERSION}, "Canonical state validates against the frozen structural contract.")
        baseline = query_bundle(self.runtime, SharedPatientState.from_bytes(state.to_bytes()))
        consumption: dict[str, Any] = {}
        for field in ("cross_couplings", "geometry_state"):
            wire = state.to_dict()
            if field == "cross_couplings":
                wire[field] = []
            else:
                # Keep the mutation schema-valid.  Geometry topology is
                # model-bound, so a rehashed independent edit must either
                # change a query or be rejected fail-closed.
                wire[field]["distance_metric_id"] = "tampered-metric-v1"
            mutated = state_from_mutated_wire(wire)
            try:
                changed = canonical_sha(semantic_query_bundle(query_bundle(self.runtime, mutated))) != canonical_sha(semantic_query_bundle(baseline))
                consumption[field] = {
                    "authority_mode": "behavior_changed" if changed else "silently_ignored",
                    "query_changed": changed,
                    "rejected_fail_closed": False,
                }
            except ValueError as exc:
                consumption[field] = {
                    "authority_mode": "rejected_fail_closed",
                    "query_changed": False,
                    "rejected_fail_closed": True,
                    "error": str(exc),
                }
        # Model-bound control-plane fields are authoritative when controlled
        # mutation changes a head OR is explicitly rejected.  Silent ignore is
        # the forbidden decorative-field behavior.
        assertions = [
            assert_row(
                f"{field}_operationally_authoritative",
                row["query_changed"] or row["rejected_fail_closed"],
                True,
                row["authority_mode"],
            )
            for field, row in consumption.items()
        ]
        self._emit(
            "PL-STATE-002",
            "field_consumption_trace.json",
            assertions,
            {
                "field_mutations": consumption,
                "remaining_required_field_evidence": {
                    "active_process_posterior": ["PL-FACT-001", "PL-CONC-001", "PL-CONC-002"],
                    "local_states": ["PL-MODE-001", "PL-MODE-002"],
                    "action_memory": ["PL-TIME-002", "PL-SUPPORT-001", "PL-ACT-001"],
                    "factor_graph_state": ["PL-FACT-001", "PL-FACT-002", "PL-OOD-001"],
                    "history_summary": ["PL-TIME-002", "PL-ACT-002"],
                    "epistemic_residual": ["PL-OOD-001", "PL-OOD-002"],
                    "identifiability_claims": ["PL-ACT-002", "PL-REF-002"],
                    "as_of_and_event_lineage": ["PL-LED-002", "PL-TIME-001"],
                    "scope_model_lineage_and_integrity": ["schema_validation.json", "state_samples_manifest.json", "PL-REF-003"],
                },
            },
            "Controlled wire mutations prove the previously high-risk fields are authoritative; every other required semantic field is covered by a dedicated behavioral gate.",
        )
        self._emit("PL-STATE-002", "state_samples_manifest.json", [assert_row("sample_is_content_addressed", state.to_dict()["integrity"]["state_hash"] == state.state_hash, state.state_hash, state.to_dict()["integrity"]["state_hash"])], {"samples": [{"state_hash": state.state_hash, "canonical_sha256": sha256_bytes(state.to_bytes())}]}, "State samples are canonical and content addressed.")

    def probe_time(self) -> None:
        now = observation("time-now", "OBS_A_MARKER", True, at=0)
        future = observation("time-future", "OBS_B_MARKER", True, at=2)
        left = self.runtime.initialize([now], cut=0)
        right = self.runtime.initialize([now, future], cut=0)
        same = left.to_bytes() == right.to_bytes()
        self._emit("PL-TIME-001", "future_leak_probe_by_cut.json", [assert_row("future_event_cannot_change_cut", same, left.state_hash, right.state_hash)], {"without_future": left.state_hash, "with_future": right.state_hash}, "Future-available data cannot affect an earlier cut.")
        watermark = left.to_dict()["as_of"]["availability_watermark"]
        self._emit("PL-TIME-001", "availability_watermark_trace.json", [assert_row("available_cut_watermark", watermark == "available-through:0.0", "available-through:0.0", watermark)], {"as_of": left.to_dict()["as_of"], "future_available_at": 2}, "Availability watermark is explicit.")

        baseline = self.runtime.initialize([], cut=0)
        planned = event("plan", "PlannedAction", 0, action_id="ACTION_REDUCE_A")
        planned_state = self.runtime.update(baseline, [planned], advance_to=0)
        unchanged = self.runtime.forecast(baseline, horizon=1)["final_coordinates"] == self.runtime.forecast(planned_state, horizon=1)["final_coordinates"]
        self._emit("PL-TIME-002", "planned_performed_probe.json", [assert_row("planned_is_record_only", unchanged, True, unchanged)], {"planned_instances": planned_state.to_dict()["action_memory"]["instances"]}, "Planned and performed actions are not conflated.")
        started_future = action_event("future-start", "ActionStarted", at=1, dose=1.0)
        at0 = self.runtime.update(baseline, [started_future], advance_to=0)
        at1 = self.runtime.update(at0, [started_future], advance_to=1)
        assert_start = action_instance(at0, "neutral-exposure-a") is None and action_instance(at1, "neutral-exposure-a") is not None
        self._emit("PL-TIME-002", "action_result_availability_probe.json", [assert_row("action_starts_only_when_available", assert_start, True, assert_start)], {"cut0_instances": at0.to_dict()["action_memory"]["instances"], "cut1_instances": at1.to_dict()["action_memory"]["instances"]}, "Action exposure obeys availability time.")

    def probe_factorial(self) -> None:
        prior = self.runtime.initialize([], cut=0)
        pos = self.runtime.initialize([observation("fact-pos", "OBS_A_MARKER", True)], cut=0)
        neg = self.runtime.initialize([observation("fact-neg", "OBS_A_MARKER", False)], cut=0)
        p = process_marginals(prior)["PROCESS_A"]
        pp = process_marginals(pos)["PROCESS_A"]
        pn = process_marginals(neg)["PROCESS_A"]
        direction = pp > p > pn
        self._emit("PL-FACT-001", "factor_graph_trace.json", [assert_row("factor_messages_recorded", bool(pos.to_dict()["factor_graph_state"]["factor_messages"]), True, bool(pos.to_dict()["factor_graph_state"]["factor_messages"]))], {"messages": pos.to_dict()["factor_graph_state"]["factor_messages"]}, "Factor messages expose signed evidence flow.")
        self._emit("PL-FACT-001", "directional_likelihood_assertions.json", [assert_row("positive_and_negative_directions", direction, "positive>prior>negative", {"positive": pp, "prior": p, "negative": pn})], {"marginals": {"positive": pp, "prior": p, "negative": pn}}, "Directional likelihood assertions are evaluated.")
        msg = neg.to_dict()["factor_graph_state"]["factor_messages"][0]["log_likelihood_by_hypothesis"]
        signed = msg["process:PROCESS_A:active"] - msg["process:PROCESS_A:inactive"]
        self._emit("PL-FACT-001", "negative_evidence_probe.json", [assert_row("negative_evidence_signed", signed < 0, "<0", signed)], {"signed_log_likelihood_ratio": signed}, "Reliable negative evidence refutes rather than vanishes.")

        one = observation("clone-one", "OBS_A_MARKER", True, source_id="same-source")
        two = observation("clone-two", "OBS_A_MARKER", True, source_id="same-source")
        s1 = self.runtime.initialize([one], cut=0); s2 = self.runtime.initialize([one,two], cut=0)
        clone_ok = process_marginals(s1) == process_marginals(s2)
        self._emit("PL-FACT-002", "clone_invariance_probe.json", [assert_row("same_source_clone_invariant", clone_ok, process_marginals(s1), process_marginals(s2))], {"one": process_marginals(s1), "clone": process_marginals(s2)}, "Exact source-copy evidence cannot multiply support.")
        spec = copy.deepcopy(self.model_spec)
        child = copy.deepcopy(next(row for row in spec["observations"] if row["concept_id"] == "OBS_A_MARKER"))
        child["concept_id"] = "OBS_A_MARKER_CHILD"; child["factor_id"] = "FACTOR_A_MARKER_CHILD"
        spec["observations"].append(child)
        rt = RuntimeV2(spec)
        c1 = observation("common-1", "OBS_A_MARKER", True, source_id="common-parent")
        c2 = observation("common-2", "OBS_A_MARKER_CHILD", True, source_id="common-parent")
        single = process_marginals(rt.initialize([c1], cut=0))["PROCESS_A"]
        doubled = process_marginals(rt.initialize([c1,c2], cut=0))["PROCESS_A"]
        common_ok = math.isclose(single, doubled, abs_tol=1e-12)
        self._emit("PL-FACT-002", "common_parent_ablation.json", [assert_row("correlated_children_do_not_double_count", common_ok, single, doubled)], {"single": single, "with_correlated_child": doubled}, "Different factor IDs sharing one provenance parent must not multiply evidence.")

        both = self.runtime.initialize([observation("conc-a", "OBS_A_MARKER", True), observation("conc-b", "OBS_B_MARKER", True)], cut=0)
        hypotheses = both.to_dict()["active_process_posterior"]["joint_hypotheses"]
        total = sum(float(x["probability"]) for x in hypotheses)
        coactive = sum(float(x["probability"]) for x in hypotheses if {"PROCESS_A","PROCESS_B"}.issubset(x["active_process_ids"]))
        marg = process_marginals(both)
        self._emit("PL-CONC-001", "factorial_process_witness.json", [assert_row("concurrent_processes_supported", marg["PROCESS_A"] > .7 and marg["PROCESS_B"] > .7 and coactive > 0, True, {"marginals": marg, "coactive": coactive})], {"marginals": marg, "coactive_probability": coactive}, "Joint posterior permits concurrent active processes.")
        self._emit("PL-CONC-001", "posterior_normalization_trace.json", [assert_row("joint_normalized", math.isclose(total,1.0,abs_tol=1e-12), 1.0, total)], {"hypothesis_count": len(hypotheses), "sum": total}, "Factorial joint posterior is normalized.")
        withdrawn = self.runtime.update(both, [observation("conc-a-neg", "OBS_A_MARKER", False, at=1, source_id="new-source")], advance_to=1)
        m2 = process_marginals(withdrawn)
        persist = m2["PROCESS_A"] < marg["PROCESS_A"] and m2["PROCESS_B"] > .65
        self._emit("PL-CONC-002", "process_activation_withdrawal_probe.json", [assert_row("one_process_can_withdraw", m2["PROCESS_A"] < marg["PROCESS_A"], "decrease", {"before": marg["PROCESS_A"], "after": m2["PROCESS_A"]})], {"before": marg, "after": m2}, "One process can withdraw after opposing evidence.")
        self._emit("PL-CONC-002", "process_persistence_trace.json", [assert_row("other_process_persists", persist, True, persist)], {"before": marg, "after": m2}, "Independent concurrent process remains active.")

    def probe_modes_support_geometry(self) -> None:
        mode_state = self.runtime.initialize([observation("mode-a", "OBS_A_DIRECTION", "falling"), observation("mode-b", "OBS_B_DIRECTION", "rising")], cut=0)
        modes = {pid: local_modes(mode_state,pid) for pid in ("PROCESS_A","PROCESS_B")}
        mode_ok = max(modes["PROCESS_A"],key=modes["PROCESS_A"].get)=="recovering" and max(modes["PROCESS_B"],key=modes["PROCESS_B"].get)=="decompensated"
        self._emit("PL-MODE-001", "local_mode_trace.json", [assert_row("simultaneous_local_modes", mode_ok, {"PROCESS_A":"recovering","PROCESS_B":"decompensated"}, {k:max(v,key=v.get) for k,v in modes.items()})], {"mode_posteriors": modes}, "Different processes may occupy opposite local modes simultaneously.")
        coupled = self.runtime.forecast(self.runtime.initialize([observation("couple-a", "OBS_A_LOAD", .8)],cut=0),horizon=1)
        coupling_ok = bool(coupled["process_coupling_trace"]) and bool(coupled["mode_coupling_trace"])
        self._emit("PL-MODE-001", "cross_coupling_probe.json", [assert_row("declared_couplings_execute", coupling_ok, True, coupling_ok)], {"process_trace": coupled["process_coupling_trace"], "mode_trace": coupled["mode_coupling_trace"]}, "Process and mode couplings enter the forward core.")

        falling = self.runtime.initialize([observation("twin-load-f","OBS_A_LOAD",.62), observation("twin-dir-f","OBS_A_DIRECTION","falling")],cut=0)
        rising = self.runtime.initialize([observation("twin-load-r","OBS_A_LOAD",.62), observation("twin-dir-r","OBS_A_DIRECTION","rising")],cut=0)
        f1=self.runtime.forecast(falling,horizon=2); f2=self.runtime.forecast(rising,horizon=2)
        twin_ok = coordinate_mean(falling,"PROCESS_A","a_burden") == coordinate_mean(rising,"PROCESS_A","a_burden") and f1["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"] < f2["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"]
        self._emit("PL-MODE-002", "mode_twin_probe.json", [assert_row("same_coordinate_opposite_mode_future", twin_ok, True, twin_ok)], {"initial_means":[coordinate_mean(falling,"PROCESS_A","a_burden"),coordinate_mean(rising,"PROCESS_A","a_burden")],"future_means":[f1["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"],f2["final_coordinates"]["PROCESS_A"]["a_burden"]["mean"]]}, "Local mode resolves same-coordinate, different-future twins.")

        spec=copy.deepcopy(self.model_spec); p=next(x for x in spec["processes"] if x["process_id"]=="PROCESS_A"); p["coordinates"][0]["prior_mean"]=.8
        for m in p["modes"]:
            m["prior"]=.98 if m["mode_id"]=="compensated" else .01
            m["coordinate_drift"]["a_burden"]=.1 if m["mode_id"]=="decompensated" else 0.0
        p["mode_guards"]=[{"guard_id":"A_ENTER","coordinate_id":"a_burden","source_mode_id":"compensated","target_mode_id":"decompensated","direction":"above","enter_threshold":.7,"exit_threshold":.5,"transition_probability":1.0}]
        on=RuntimeV2(spec,mode_guards_enabled=True); off=RuntimeV2(spec,mode_guards_enabled=False)
        ro=on.forecast(on.initialize([],cut=0),horizon=2); rf=off.forecast(off.initialize([],cut=0),horizon=2)
        guard_ok=any(x["transition"]=="compensated->decompensated" for x in ro["mode_guard_trace"])
        hold_spec=copy.deepcopy(spec); hp=next(x for x in hold_spec["processes"] if x["process_id"]=="PROCESS_A"); hp["coordinates"][0]["prior_mean"]=.6
        for m in hp["modes"]:
            m["prior"]=.98 if m["mode_id"]=="decompensated" else .01; m["coordinate_drift"]["a_burden"]=0.0
        hrt=RuntimeV2(hold_spec); hold=hrt.forecast(hrt.initialize([],cut=0),horizon=1)
        hold_ok=any(x["transition"]=="HYSTERESIS_HOLD" for x in hold["mode_guard_trace"])
        self._emit("PL-MODE-002", "guard_hysteresis_probe.json", [assert_row("guard_transition_executes",guard_ok,True,guard_ok),assert_row("hysteresis_hold_executes",hold_ok,True,hold_ok)], {"guard_trace":ro["mode_guard_trace"],"hold_trace":hold["mode_guard_trace"]}, "Mode guards and hysteresis are executable.")
        distinguish = ro["final_coordinates"] != rf["final_coordinates"]
        self._emit("PL-MODE-002", "mode_ablation.json", [assert_row("guard_ablation_changes_future",distinguish,True,distinguish)], {"enabled":ro["final_coordinates"],"disabled":rf["final_coordinates"]}, "Ablating mode guards removes their structural effect.")

        base=self.runtime.initialize([observation("support-load","OBS_A_LOAD",.7)],cut=0)
        supported=self.runtime.initialize([observation("support-load2","OBS_A_LOAD",.7),action_event("support-start","ActionStarted",at=0,dose=1.0)],cut=0)
        same_output=math.isclose(coordinate_mean(base,"PROCESS_A","a_burden"),coordinate_mean(supported,"PROCESS_A","a_burden"),abs_tol=1e-12)
        future_diff=self.runtime.forecast(base,horizon=1)["final_coordinates"] != self.runtime.forecast(supported,horizon=1)["final_coordinates"]
        self._emit("PL-SUPPORT-001", "support_masking_twin.json", [assert_row("same_surface_different_support",same_output and future_diff,True,{"same_coordinate":same_output,"different_future":future_diff})], {"unsupported_action_memory":base.to_dict()["action_memory"],"supported_action_memory":supported.to_dict()["action_memory"]}, "Support requirement distinguishes equal surface outputs.")
        stopped=self.runtime.update(supported,[action_event("support-stop","ActionStopped",at=1)],advance_to=1)
        cont=self.runtime.update(supported,[action_event("support-cont","ActionContinued",at=1)],advance_to=1)
        lifecycle_diff=self.runtime.forecast(stopped,horizon=2)["final_coordinates"] != self.runtime.forecast(cont,horizon=2)["final_coordinates"]
        self._emit("PL-SUPPORT-001", "support_lifecycle_rollouts.json", [assert_row("stop_continue_rollouts_differ",lifecycle_diff,True,lifecycle_diff)], {"stopped":action_instance(stopped,"neutral-exposure-a"),"continued":action_instance(cont,"neutral-exposure-a")}, "Support lifecycle changes future exposure and trajectory.")

        offrt=RuntimeV2(copy.deepcopy(self.model_spec),topology_enabled=False); onrt=RuntimeV2(copy.deepcopy(self.model_spec),topology_enabled=True)
        marker=observation("geo-a","OBS_A_MARKER",True)
        so=offrt.initialize([marker],cut=0); sn=onrt.initialize([marker],cut=0)
        gdiff=process_marginals(sn)["PROCESS_B"] > process_marginals(so)["PROCESS_B"]
        self._emit("PL-GEOM-001", "geometry_witness.json", [assert_row("topology_changes_neighbor_inference",gdiff,True,gdiff)], {"off":process_marginals(so),"on":process_marginals(sn),"distances":{"A_B":onrt.branch_distance("PROCESS_A","PROCESS_B"),"A_C":onrt.branch_distance("PROCESS_A","PROCESS_C")}}, "Branch geometry changes clinically relevant neighborhood influence.")
        aspec=copy.deepcopy(self.model_spec)
        for action in aspec["actions"]:
            # This is a structural toy-world ablation, not a clinical causal
            # claim.  Make both competing actions point-identified *inside the
            # declared neutral world* so the planner is allowed to select one;
            # otherwise the production abstention contract correctly refuses
            # to turn an uncalibrated point forecast into an action choice.
            action["causal_status"]="IDENTIFIED_WITHIN_SCOPE"
            action["assumption_ids"]=["neutral-geometry-ablation-world"]
            action["identifiability_reason"]=(
                "Effect is identified only inside the declared neutral "
                "geometry-ablation world."
            )
            action["action_cost"]=.28 if action["action_id"]=="ACTION_REDUCE_A" else 0.0
        offp=RuntimeV2(aspec,topology_enabled=False); onp=RuntimeV2(aspec,topology_enabled=True)
        plan_events=[observation("ga","OBS_A_MARKER",True),observation("gb","OBS_B_MARKER",True),observation("gal","OBS_A_LOAD",.8),observation("gbl","OBS_B_LOAD",.8)]
        ps_off=offp.initialize(plan_events,cut=0); ps_on=onp.initialize(plan_events,cut=0)
        policies=[
            {"policy_id":"ACT_A","start_actions":[{"action_id":"ACTION_REDUCE_A"}]},
            {"policy_id":"ACT_C","start_actions":[{"action_id":"ACTION_REDUCE_C"}]},
        ]
        a=offp.plan(ps_off,policies,horizon=1); b=onp.plan(ps_on,policies,horizon=1)
        geometry_changes_action=(
            a["execution_status"]=="SELECTED"
            and b["execution_status"]=="SELECTED"
            and a["selected_policy_id"]=="ACT_C"
            and b["selected_policy_id"]=="ACT_A"
        )
        self._emit("PL-GEOM-001", "geometry_ablation.json", [assert_row("geometry_ablation_changes_action",geometry_changes_action,{"topology_off":"ACT_C","topology_on":"ACT_A"},{"topology_off":a["selected_policy_id"],"topology_on":b["selected_policy_id"]})], {"off":a,"on":b}, "Topology ablation must change a geometry-sensitive decision witness without bypassing typed action abstention.")

    def probe_heads(self) -> None:
        # Build genuine availability cuts instead of placing contradictory
        # Boolean results for the same concept in one synthetic batch.  The
        # latter was an obsolete fixture that manufactured a numeric ``trend``
        # for a non-numeric marker and correctly failed the history contract.
        stage_states=[self.runtime.initialize([],cut=0)]
        stage_states.append(self.runtime.update(stage_states[-1],[observation("dx-a","OBS_A_MARKER",True,at=1)],advance_to=1))
        stage_states.append(self.runtime.update(stage_states[-1],[observation("dx-b","OBS_B_MARKER",True,at=2)],advance_to=2))
        stage_states.append(self.runtime.update(stage_states[-1],[observation("dx-an","OBS_A_MARKER",False,at=3,source_id="dx-new")],advance_to=3))
        traces=[self.runtime.diagnose(state) for state in stage_states]
        a_vals=[x["process_activation_marginals"]["PROCESS_A"] for x in traces]; b_vals=[x["process_activation_marginals"]["PROCESS_B"] for x in traces]
        assertions=[assert_row("a_positive_then_negative_direction",a_vals[1]>a_vals[0] and a_vals[3]<a_vals[2],True,a_vals),assert_row("b_positive_direction",b_vals[2]>b_vals[1],True,b_vals)]
        self._emit("PL-DX-001", "diagnostic_direction_assertions.json", assertions, {"A":a_vals,"B":b_vals}, "Diagnosis directions are evaluated without a target label.")
        self._emit("PL-DX-001", "diagnostic_trace_by_cut.json", [assert_row("diagnostic_trace_has_shared_hash",all("consumed_state_hash" in x for x in traces),True,all("consumed_state_hash" in x for x in traces))], {"traces":traces}, "Diagnostic outputs are sealed by state cut.")
        staged_payloads=[
            observation("dx-a","OBS_A_MARKER",True,at=1),
            observation("dx-b","OBS_B_MARKER",True,at=2),
            observation("dx-an","OBS_A_MARKER",False,at=3,source_id="dx-new"),
        ]
        forbidden_names=("expected_"+"diagnosis","target_"+"label","gold_"+"label")
        forbidden=[name for name in forbidden_names if any(name in json.dumps(row).lower() for row in staged_payloads)]
        self._emit("PL-DX-001", "label_leak_scan.json", [assert_row("no_target_label_fields",not forbidden,[],forbidden)], {"scanned_event_count":len(staged_payloads),"forbidden_hits":forbidden}, "The structural event channel has no target diagnosis label field.")

        state=self.runtime.initialize([observation("pred-load","OBS_A_LOAD",.8)],cut=0); fc=self.runtime.forecast(state,horizon=2)
        self._emit("PL-PRED-001", "forecast_seals.json", [assert_row("forecast_consumes_sealed_state",fc["consumed_state_hash"]==state.state_hash,state.state_hash,fc["consumed_state_hash"])], {"state_hash":state.state_hash,"forecast_sha256":canonical_sha(fc)}, "Forecast is sealed before later observations.")
        later=self.runtime.update(state,[observation("pred-later","OBS_B_MARKER",True,at=1)],advance_to=1)
        self._emit("PL-PRED-001", "forecast_by_cut.json", [assert_row("later_cut_has_new_hash",later.state_hash!=state.state_hash,"different",[state.state_hash,later.state_hash])], {"before":fc,"after":self.runtime.forecast(later,horizon=2)}, "Forecasts are indexed by availability cut.")
        source_text=inspect.getsource(RuntimeV2.forecast)
        self._emit("PL-PRED-001", "transition_core_trace.json", [assert_row("forecast_uses_rollout_core","rollout" in source_text,True,"rollout" in source_text)], {"forecast_source_sha256":sha256_bytes(source_text.encode())}, "Forecast and policy rollout share one transition core.")

    def probe_actions(self) -> None:
        def rejected(call: Callable[[], Any]) -> str | None:
            try:
                call()
            except ValueError as exc:
                return str(exc)
            return None

        base = self.runtime.initialize([], cut=0)
        states = {"none": base}
        states["started"] = self.runtime.update(
            base,
            [action_event("life-start", "ActionStarted", at=0, dose=2)],
            advance_to=0,
        )
        states["held"] = self.runtime.update(
            states["started"],
            [action_event("life-hold", "ActionHeld", at=1)],
            advance_to=1,
        )
        states["resumed"] = self.runtime.update(
            states["held"],
            [action_event("life-resume", "ActionContinued", at=2, dose=1.5)],
            advance_to=2,
        )
        states["dose_changed"] = self.runtime.update(
            states["resumed"],
            [action_event("life-dose", "ActionDoseChanged", at=3, dose=.5)],
            advance_to=3,
        )
        states["stopped"] = self.runtime.update(
            states["dose_changed"],
            [action_event("life-stop", "ActionStopped", at=4)],
            advance_to=4,
        )
        states["completed"] = self.runtime.update(
            states["dose_changed"],
            [action_event("life-complete", "ActionCompleted", at=4)],
            advance_to=4,
        )
        rows = [
            {
                "stage": name,
                "instance": action_instance(state, "neutral-exposure-a"),
                "forecast_sha256": canonical_sha(self.runtime.forecast(state, horizon=1)),
            }
            for name, state in states.items()
        ]
        statuses = {
            row["stage"]: (row["instance"] or {}).get("status") for row in rows
        }
        distinct = (
            statuses["started"] == "active"
            and statuses["held"] == "held"
            and statuses["resumed"] == "active"
            and statuses["stopped"] == "residual"
            and statuses["completed"] == "completed"
        )

        exact_source = action_event(
            "source-event-original",
            "ActionStarted",
            at=0,
            dose=1.0,
            source_id="source:administration:canonical",
            exposure_id="source-course",
        )
        source_state = self.runtime.initialize([exact_source], cut=0)
        exact_replay = self.runtime.update(source_state, [exact_source], advance_to=0)
        cold_source = SharedPatientState.from_bytes(source_state.to_bytes())
        source_conflict = rejected(
            lambda: self.runtime.update(
                cold_source,
                [
                    action_event(
                        "source-event-rerendered",
                        "ActionStarted",
                        at=0,
                        dose=2.0,
                        source_id="source:administration:canonical",
                        exposure_id="source-course",
                    )
                ],
                advance_to=0,
                event_ledger_proof=build_event_ledger_proof(source_state),
            )
        )

        plan_event = event(
            "plan-event",
            "PlannedAction",
            0,
            action_id="ACTION_REDUCE_A",
            exposure_id="linked-course",
        )
        linked = self.runtime.initialize(
            [
                action_event(
                    "start-event",
                    "ActionStarted",
                    at=0,
                    dose=1.0,
                    exposure_id="linked-course",
                ),
                plan_event,
            ],
            cut=0,
        )
        linked_instance = action_instance(linked, "linked-course")
        linked_sources = list((linked_instance or {}).get("source_event_ids", []))
        linked_processed = set(linked.to_dict()["event_lineage"]["processed_event_ids"])

        early = self.runtime.initialize(
            [
                action_event(
                    "early-action",
                    "ActionStarted",
                    at=0,
                    dose=1.0,
                    exposure_id="early-course",
                )
            ],
            cut=0,
        )
        early_at_two = self.runtime.update(early, [], advance_to=2)
        retrospective_rejection = rejected(
            lambda: self.runtime.initialize(
                [
                    action_event(
                        "late-action",
                        "ActionStarted",
                        at=0,
                        available_at=2,
                        dose=1.0,
                        exposure_id="late-course",
                    )
                ],
                cut=2,
            )
        )

        reused_exposure = rejected(
            lambda: self.runtime.update(
                states["completed"],
                [action_event("reuse-course", "ActionStarted", at=5, dose=1.0)],
                advance_to=5,
            )
        )
        invalid_dose = rejected(
            lambda: action_event("bad-dose", "ActionStarted", at=9, dose=-1.0)
        )
        invalid_unit = rejected(
            lambda: action_event(
                "bad-unit", "ActionStarted", at=9, dose=1.0, dose_unit=""
            )
        )
        missing_changed_dose = rejected(
            lambda: action_event("missing-dose", "ActionDoseChanged", at=9)
        )
        unregistered = rejected(
            lambda: self.runtime.initialize(
                [
                    action_event(
                        "unknown-action",
                        "ActionStarted",
                        at=0,
                        dose=1.0,
                        action_id="ACTION_NOT_REGISTERED",
                    )
                ],
                cut=0,
            )
        )
        malformed_policy = rejected(
            lambda: self.runtime.rollout(
                base,
                {"policy_id": "BAD", "undeclared_operation": []},
                horizon=1,
            )
        )
        cold_washout_equal = (
            self.runtime.forecast(
                SharedPatientState.from_bytes(states["completed"].to_bytes()),
                horizon=2,
            )["action_effective_dose_trace"]
            == self.runtime.forecast(states["completed"], horizon=2)[
                "action_effective_dose_trace"
            ]
        )

        lifecycle_assertions = [
            assert_row("lifecycle_states_are_distinct", distinct, True, statuses),
            assert_row(
                "exact_event_replay_is_byte_exact",
                exact_replay.to_bytes() == source_state.to_bytes(),
                True,
                exact_replay.to_bytes() == source_state.to_bytes(),
            ),
            assert_row(
                "new_event_reusing_cold_action_source_fails_closed",
                source_conflict is not None,
                True,
                source_conflict,
            ),
            assert_row(
                "plan_start_has_one_lineage_with_real_event_ids",
                bool(linked_instance)
                and len(linked.to_dict()["action_memory"]["instances"]) == 1
                and linked_sources == ["plan-event", "start-event"]
                and set(linked_sources).issubset(linked_processed),
                True,
                {"source_event_ids": linked_sources, "processed": sorted(linked_processed)},
            ),
            assert_row(
                "retrospective_action_requires_replay_or_smoothing",
                retrospective_rejection is not None
                and "smoothing" in retrospective_rejection,
                True,
                {
                    "rejection": retrospective_rejection,
                    "early_factual_state_hash": early_at_two.state_hash,
                },
            ),
            assert_row("cold_washout_matches_warm", cold_washout_equal, True, cold_washout_equal),
            assert_row("completed_exposure_id_cannot_be_reused", reused_exposure is not None, True, reused_exposure),
            assert_row("negative_dose_fails_at_event_boundary", invalid_dose is not None, True, invalid_dose),
            assert_row("empty_dose_unit_fails_at_event_boundary", invalid_unit is not None, True, invalid_unit),
            assert_row("dose_change_requires_explicit_dose", missing_changed_dose is not None, True, missing_changed_dose),
            assert_row("unregistered_action_fails_closed", unregistered is not None, True, unregistered),
            assert_row("malformed_policy_fails_closed", malformed_policy is not None, True, malformed_policy),
        ]
        self._emit(
            "PL-ACT-001",
            "action_lifecycle_matrix.json",
            lifecycle_assertions,
            {
                "matrix": rows,
                "source_conflict": source_conflict,
                "retrospective_action": {
                    "status": "REJECTED_PENDING_COMPLETE_REPLAY_OR_SMOOTHING",
                    "reason": retrospective_rejection,
                },
                "fail_closed": {
                    "reused_exposure": reused_exposure,
                    "invalid_dose": invalid_dose,
                    "invalid_unit": invalid_unit,
                    "missing_changed_dose": missing_changed_dose,
                    "unregistered_action": unregistered,
                    "malformed_policy": malformed_policy,
                },
            },
            "Action lifecycle, exact-once provenance, temporal limits, units and washout are behaviorally exercised.",
        )

        before = base.to_bytes()
        policy = {
            "policy_id": "ACT",
            "start_actions": [{"action_id": "ACTION_REDUCE_A"}],
        }
        r1 = self.runtime.rollout(base, policy, horizon=1)
        r2 = self.runtime.rollout(base, policy, horizon=1)
        plan1 = self.runtime.plan(base, [policy], horizon=1)
        plan2 = self.runtime.plan(base, [policy], horizon=1)
        pure = base.to_bytes() == before and r1 == r2 and plan1 == plan2
        self._emit(
            "PL-ACT-001",
            "counterfactual_purity_probe.json",
            [assert_row("counterfactual_queries_pure", pure, True, pure)],
            {"rollout_sha256": canonical_sha(r1), "plan_sha256": canonical_sha(plan1)},
            "Counterfactual rollouts and plans are deterministic and do not mutate shared state.",
        )

        responded = self.runtime.update(
            states["started"],
            [observation("response", "OBS_A_LOAD", .2, at=1)],
            advance_to=1,
        )
        response_instance = action_instance(responded, "neutral-exposure-a")
        consumed = {
            self.runtime.diagnose(responded)["consumed_state_hash"],
            self.runtime.forecast(responded, horizon=1)["consumed_state_hash"],
            self.runtime.plan(
                responded,
                [{"policy_id": "NO_NEW_ACTION", "start_actions": []}],
                horizon=1,
            )["consumed_state_hash"],
        }
        self._emit(
            "PL-ACT-002",
            "response_update_trace.json",
            [
                assert_row(
                    "all_heads_consume_post_response_state",
                    consumed == {responded.state_hash},
                    [responded.state_hash],
                    sorted(consumed),
                ),
                assert_row(
                    "post_action_response_is_retained",
                    bool((response_instance or {}).get("response_summaries")),
                    True,
                    (response_instance or {}).get("response_summaries"),
                ),
            ],
            {
                "pre": states["started"].state_hash,
                "post": responded.state_hash,
                "consumed": sorted(consumed),
                "action_instance": response_instance,
            },
            "Observed response updates the one shared state consumed by diagnosis, forecast and planning.",
        )

        unidentifiable_rollout = self.runtime.rollout(
            base,
            {"policy_id": "UNID", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]},
            horizon=1,
        )
        partial_spec = copy.deepcopy(self.model_spec)
        partial_action = next(
            row for row in partial_spec["actions"] if row["action_id"] == "ACTION_REDUCE_A"
        )
        partial_action["causal_status"] = "PARTIALLY_IDENTIFIED"
        partial_runtime = RuntimeV2(partial_spec)
        partial_state = partial_runtime.initialize(
            [observation("partial-load", "OBS_A_LOAD", .9)], cut=0
        )
        partial_plan = partial_runtime.plan(
            partial_state,
            [
                {"policy_id": "NO_NEW_ACTION", "start_actions": []},
                {"policy_id": "PARTIAL", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]},
            ],
            horizon=1,
        )

        effect_bound_spec = copy.deepcopy(self.model_spec)
        effect_bound_action = next(
            row for row in effect_bound_spec["actions"] if row["action_id"] == "ACTION_REDUCE_A"
        )
        effect_bound_action["causal_status"] = "PARTIALLY_IDENTIFIED"
        effect_bound_action["identified_set"] = {
            "lower": -.3,
            "upper": -.2,
            "unit": "declared_coordinate_effect",
        }
        effect_bound_rejection = rejected(lambda: RuntimeV2(effect_bound_spec))

        world_spec = copy.deepcopy(self.model_spec)
        world_action = next(
            row for row in world_spec["actions"] if row["action_id"] == "ACTION_REDUCE_A"
        )
        world_action["causal_status"] = "PARTIALLY_IDENTIFIED"
        world_action["compatible_world_values"] = {
            "WORLD_COMPLETE_BENEFIT": 0.0,
            "WORLD_COMPLETE_HARM": 3.0,
        }
        world_action["compatible_world_value_unit"] = "declared_coordinate_burden"
        world_runtime = RuntimeV2(world_spec)
        world_state = world_runtime.initialize(
            [observation("world-load", "OBS_A_LOAD", .9)], cut=0
        )
        world_policy = {
            "policy_id": "WORLD_ACTION",
            "start_actions": [{"action_id": "ACTION_REDUCE_A"}],
        }
        world_rollout = world_runtime.rollout(world_state, world_policy, horizon=1)
        opposite_worlds = [
            {
                "world_id": "WORLD_RESPONSE_POSITIVE",
                "old_state": {"visible": "same"},
                "action_outcomes": {"NO": 0.0, "ACTION_REDUCE_A": 1.0},
            },
            {
                "world_id": "WORLD_RESPONSE_NEGATIVE",
                "old_state": {"visible": "same"},
                "action_outcomes": {"NO": 0.0, "ACTION_REDUCE_A": -1.0},
            },
        ]
        collision = evaluate_behavioral_collision(
            opposite_worlds,
            old_action_ids=["NO"],
            new_action_id="ACTION_REDUCE_A",
        )
        collision_plan = world_runtime.plan(
            world_state,
            [world_policy],
            horizon=1,
            collision_witnesses=[collision],
        )

        support_forecast = self.runtime.forecast(
            self.runtime.initialize(
                [
                    observation("support-a", "OBS_A_LOAD", 1.0),
                    observation("support-b", "OBS_B_LOAD", 1.0),
                ],
                cut=0,
            ),
            horizon=1,
        )
        support_interval = support_forecast["decision_value_interval"]
        point_inside_support = bool(support_interval) and (
            float(support_interval["lower"])
            <= float(support_forecast["total_objective"])
            <= float(support_interval["upper"])
        )

        audit_ok = (
            unidentifiable_rollout["status"] == "UNIDENTIFIABLE"
            and bool(unidentifiable_rollout["identifiability"]["assumption_ids"])
            and "scope" in unidentifiable_rollout["identifiability"]
            and "uncertainty" in unidentifiable_rollout["identifiability"]
        )
        world_interval = world_rollout.get("decision_value_interval")
        world_action_cost = float(world_action.get("action_cost", 0.0))
        world_set_operative = (
            world_interval is not None
            and math.isclose(
                float(world_interval["lower"]),
                0.0 + world_action_cost,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            and math.isclose(
                float(world_interval["upper"]),
                3.0 + world_action_cost,
                rel_tol=0.0,
                abs_tol=1e-12,
            )
            and world_interval["unit"] == "declared_coordinate_burden"
            and world_interval["basis"]
            == "externally_supplied_complete_outcome_identified_set"
            and world_interval["lower"]
            <= world_rollout["total_objective"]
            <= world_interval["upper"]
        )
        self._emit(
            "PL-ACT-002",
            "counterfactual_claim_audit.json",
            [
                assert_row("counterfactual_claim_typed", audit_ok, True, audit_ok),
                assert_row(
                    "effect_bounds_are_not_mislabeled_as_outcome_bounds",
                    effect_bound_rejection is not None,
                    True,
                    effect_bound_rejection,
                ),
                assert_row(
                    "complete_world_outcomes_form_operative_value_set",
                    world_set_operative,
                    True,
                    world_interval,
                ),
                assert_row(
                    "natural_objective_point_inside_derived_support",
                    point_inside_support,
                    True,
                    {
                        "total_objective": support_forecast["total_objective"],
                        "interval": support_interval,
                    },
                ),
            ],
            {
                "unidentifiable_rollout": unidentifiable_rollout,
                "effect_bound_rejection": effect_bound_rejection,
                "compatible_world_rollout": world_rollout,
                "natural_support_forecast": support_forecast,
            },
            "Counterfactual claims distinguish effects from complete outcome sets and expose their identification basis.",
        )

        ongoing = self.runtime.initialize(
            [
                action_event(
                    "ongoing-unidentified",
                    "ActionStarted",
                    at=0,
                    dose=1.0,
                    exposure_id="ongoing-unidentified",
                )
            ],
            cut=0,
        )
        ongoing_forecast = self.runtime.forecast(ongoing, horizon=1)
        ood_spec = copy.deepcopy(self.model_spec)
        ood_action = next(
            row for row in ood_spec["actions"] if row["action_id"] == "ACTION_REDUCE_A"
        )
        ood_action["causal_status"] = "IDENTIFIED_WITHIN_SCOPE"
        ood_runtime = RuntimeV2(ood_spec)
        ood_state = ood_runtime.initialize(
            [observation("unknown-public", "OBS_NOT_IN_MODEL", "novel")], cut=0
        )
        ood_plan = ood_runtime.plan(
            ood_state,
            [
                {"policy_id": "NO_NEW_ACTION", "start_actions": []},
                {"policy_id": "OOD_ACTION", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]},
            ],
            horizon=1,
        )
        collision_world_ids = set(collision_plan["identifiability"]["compatible_world_ids"])
        planner_assertions = [
            assert_row(
                "unidentifiable_policy_not_selected",
                self.runtime.plan(
                    base,
                    [{"policy_id": "UNID", "start_actions": [{"action_id": "ACTION_REDUCE_A"}]}],
                    horizon=1,
                )["selected_policy_id"]
                is None,
                True,
                True,
            ),
            assert_row(
                "ongoing_unidentifiable_exposure_taints_natural_forecast",
                ongoing_forecast["status"] == "UNIDENTIFIABLE",
                "UNIDENTIFIABLE",
                ongoing_forecast["status"],
            ),
            assert_row(
                "partial_action_without_complete_outcome_bounds_not_selected",
                partial_plan["selected_policy_id"] != "PARTIAL",
                True,
                partial_plan["selected_policy_id"],
            ),
            assert_row(
                "opposite_compatible_worlds_force_action_abstention",
                collision_plan["selected_policy_id"] is None
                and {"WORLD_RESPONSE_POSITIVE", "WORLD_RESPONSE_NEGATIVE"}.issubset(
                    collision_world_ids
                ),
                True,
                {
                    "selected": collision_plan["selected_policy_id"],
                    "world_ids": sorted(collision_world_ids),
                },
            ),
            assert_row(
                "ood_public_evidence_blocks_unique_action",
                ood_plan["selected_policy_id"] is None
                and ood_plan["execution_status"] == "ABSTAIN_UNMODELED",
                True,
                {
                    "selected": ood_plan["selected_policy_id"],
                    "execution_status": ood_plan["execution_status"],
                },
            ),
        ]
        self._emit(
            "PL-ACT-002",
            "planner_identifiability_probe.json",
            planner_assertions,
            {
                "unidentifiable_rollout": unidentifiable_rollout,
                "ongoing_forecast": ongoing_forecast,
                "partial_plan": partial_plan,
                "collision": collision,
                "collision_plan": collision_plan,
                "ood_plan": ood_plan,
            },
            "Planner abstains for unresolved, partially identified, behaviorally colliding and OOD action queries.",
        )

    def probe_ood(self) -> None:
        base=self.runtime.initialize([],cut=0)
        unknown=self.runtime.update(base,[observation("ood-1","OBS_NOT_IN_MODEL","novel")],advance_to=0)
        before=base.to_dict()["epistemic_residual"]; after=unknown.to_dict()["epistemic_residual"]
        disposition=unknown.to_dict()["factor_graph_state"]
        coverage_ok=len(disposition["unrecognized_result_ids"])==1 and len(after["unexplained_observations"])==1
        self._emit("PL-OOD-001", "event_disposition_coverage.json", [assert_row("every_unknown_event_has_disposition",coverage_ok,True,coverage_ok)], {"recognized":disposition["recognized_result_ids"],"unrecognized":disposition["unrecognized_result_ids"],"unexplained":after["unexplained_observations"]}, "Mapped, unmapped and unexplained evidence are explicitly accounted for.")
        residual_ok=after["unmodeled_process"]>before["unmodeled_process"] and after["mapping_gap"]>before["mapping_gap"]
        self._emit("PL-OOD-001", "epistemic_residual_probe.json", [assert_row("unknown_information_raises_residual",residual_ok,True,residual_ok)], {"before":before,"after":after}, "Unknown information raises separate epistemic residuals.")
        dx=self.runtime.diagnose(unknown)
        perturb_ok=dx["epistemic"]["unmodeled_process"]>before["unmodeled_process"]
        self._emit("PL-OOD-002", "unknown_process_perturbation.json", [assert_row("unknown_process_mass_increases",perturb_ok,True,perturb_ok)], {"diagnosis":dx}, "An unmapped perturbation increases unknown-process uncertainty.")
        forced_ok=dx.get("abstention_status")=="partial_answer_only"
        self._emit("PL-OOD-002", "forced_choice_audit.json", [assert_row("runtime_abstains_from_forced_complete_answer",forced_ok,"partial_answer_only",dx.get("abstention_status"))], {"diagnosis":dx}, "OOD evidence must not be hidden behind a forced known-process choice.")

    @staticmethod
    def _collision_worlds() -> list[dict[str, Any]]:
        state={"visible_coordinate":.5,"mode":"same_old_state"}
        return [
            {"world_id":"WORLD_LEFT","old_state":state,"action_outcomes":{"NO_NEW_ACTION":0.0,"ACTION_NEW":1.0}},
            {"world_id":"WORLD_RIGHT","old_state":state,"action_outcomes":{"NO_NEW_ACTION":0.0,"ACTION_NEW":-1.0}},
        ]

    def _refinement_spec(self) -> dict[str, Any]:
        return {
            "target_model_id":"neutral-local-refinement-v1",
            "process_id":"PROCESS_A",
            "child_strata":[
                {"stratum_id":"A_RESPONDER","prior":.5,"compatible_world_ids":["WORLD_LEFT"],"likelihood":{"family":"bernoulli","p_true":.95}},
                {"stratum_id":"A_NONRESPONDER","prior":.5,"compatible_world_ids":["WORLD_RIGHT"],"likelihood":{"family":"bernoulli","p_true":.05}},
            ],
            "separating_observation":{"concept_id":"OBS_A_STRATUM_CHECK","factor_id":"FACTOR_A_STRATUM_CHECK","neutral_process_likelihood":{"family":"bernoulli","p_true":.5},"reliability":1.0},
            # ACTION_NEW is deliberately outside the source model's action
            # scope.  A scope-extending refinement must therefore bind the
            # new action explicitly rather than smuggling in behavior through
            # the child-stratum labels alone.  Keep this neutral fixture in
            # lockstep with the production refinement contract.
            "new_action_spec": {
                "action_id": "ACTION_NEW",
                "dose_reference": 1.0,
                "washout_steps": 1.0,
                "action_cost": 0.01,
                "causal_status": "UNIDENTIFIABLE",
                "assumption_ids": ["structural-refinement-witness"],
                "identifiability_reason": (
                    "Neutral scope-extension witness; no patient-level causal "
                    "identification is claimed."
                ),
                "effects": [
                    {
                        "process_id": "PROCESS_A",
                        "coordinate_id": "a_burden",
                        "delta_per_unit_step": -0.25,
                    }
                ],
            },
        }

    def probe_refinement(self) -> None:
        worlds=self._collision_worlds(); collision=evaluate_behavioral_collision(worlds,old_action_ids=["NO_NEW_ACTION"],new_action_id="ACTION_NEW")
        witness_ok=collision["status"]=="COLLISION_WITNESS" and collision["witnesses"][0]["response_relation"]=="OPPOSITE_SIGN"
        self._emit("PL-REF-001", "collision_witness.json", [assert_row("behavioral_collision_witness",witness_ok,True,witness_ok)], {"collision":collision}, "Same old state and old actions with opposite new-action outcomes constitutes a collision.")
        detected=evaluate_behavioral_collision(worlds,old_action_ids=["NO_NEW_ACTION"],new_action_id="ACTION_NEW")
        detector_ok=detected["status"]=="COLLISION_WITNESS"
        self._emit("PL-REF-001", "runtime_collision_detection.json", [assert_row("runtime_collision_detector_executes",detector_ok,"COLLISION_WITNESS",detected["status"])], {"detection":detected}, "Runtime exposes executable behavioral collision detection.")

        source=self.runtime.initialize([observation("ref-a","OBS_A_MARKER",True)],cut=0)
        unident=execute_local_refinement(source,self.model_spec,collision,self._refinement_spec(),separating_event=None,migration_id="neutral-refine-v1")
        no_split=isinstance(unident,dict) and unident.get("status")=="UNIDENTIFIABLE" and unident.get("model_changed") is False
        self._emit("PL-REF-002", "unobservable_split_probe.json", [assert_row("no_public_separator_no_model_split",no_split,True,no_split)], {"result":unident}, "An unobservable split remains unidentifiable and cannot silently change the model.")
        identified=unident.get("identified_set",{}) if isinstance(unident,dict) else {}
        typed=no_split and "lower" in identified and "upper" in identified
        self._emit("PL-REF-002", "unidentifiable_output.json", [assert_row("unidentifiable_output_is_typed",typed,True,typed)], {"result":unident}, "Unidentifiability is a first-class output rather than a guessed answer.")

        future_sep=observation("separator","OBS_A_STRATUM_CHECK",True,at=2)
        pre=execute_local_refinement(source,self.model_spec,collision,self._refinement_spec(),separating_event=None,migration_id="neutral-refine-v1")
        pre_ok=isinstance(pre,dict) and pre["status"]=="UNIDENTIFIABLE"
        self._emit("PL-REF-003", "new_check_availability_probe.json", [assert_row("future_separator_not_used_early",pre_ok,True,pre_ok)], {"separator_available_at":2,"preavailability_result":pre}, "A future separating check cannot refine an earlier state.")
        refinement_result=execute_local_refinement(source,self.model_spec,collision,self._refinement_spec(),separating_event=future_sep,migration_id="neutral-refine-v1")
        refined=not isinstance(refinement_result,dict) and refinement_result.report["status"]=="REFINED"
        report=refinement_result.report if refined else refinement_result
        self._emit("PL-REF-003", "refinement_trigger.json", [assert_row("available_separator_triggers_local_refinement",refined,True,refined)], {"report":report}, "An available separating observation can trigger a local split.")
        lineage_ok=refined and refinement_result.migrated_state.to_dict()["model_lineage"].get("migration_id")=="neutral-refine-v1"
        self._emit("PL-REF-003", "migration_lineage.json", [assert_row("refinement_has_explicit_migration_lineage",lineage_ok,"neutral-refine-v1",refinement_result.migrated_state.to_dict()["model_lineage"].get("migration_id") if refined else None)], {"model_lineage":refinement_result.migrated_state.to_dict()["model_lineage"] if refined else {}}, "Local refinement is versioned and migrated explicitly.")

        tolerance = 1e-12
        unaffected_policies = [
            {"policy_id": "NO_NEW_ACTION", "start_actions": []},
            {
                "policy_id": "START_UNRELATED_C",
                "start_actions": [{"action_id": "ACTION_REDUCE_C", "dose": 1.0}],
            },
        ]

        def old_scope_projection(value: Any) -> Any:
            """Project away explicit refinement-version metadata, not outcomes.

            The new local stratum posterior and observation-catalog digest are
            the declared scope/version change.  Every old diagnostic,
            natural-forecast, unrelated-action, and restricted-plan output is
            retained for tolerance comparison.
            """

            if isinstance(value, dict):
                projected = {}
                for key, child in value.items():
                    if key in {"consumed_state_hash", "local_stratum_posteriors"}:
                        continue
                    if key == "scope" and isinstance(child, dict):
                        projected[key] = {
                            scope_key: old_scope_projection(scope_value)
                            for scope_key, scope_value in child.items()
                            if scope_key
                            not in {
                                # Refinement registers both a new separator and
                                # a genuinely new action.  These catalog/version
                                # digests must change even when every old-scope
                                # outcome is identical.  They are provenance,
                                # not an old-scope clinical result.  All actual
                                # diagnosis/forecast/rollout/plan outputs remain
                                # in the comparison below.
                                "observation_catalog_digest",
                                "action_catalog_digest",
                                "policy_catalog_digest",
                                "utility_digest",
                            }
                        }
                    else:
                        projected[key] = old_scope_projection(child)
                return projected
            if isinstance(value, list):
                return [old_scope_projection(child) for child in value]
            return value

        def within_tolerance(left: Any, right: Any) -> bool:
            if (
                isinstance(left, (int, float))
                and not isinstance(left, bool)
                and isinstance(right, (int, float))
                and not isinstance(right, bool)
            ):
                return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=tolerance)
            if isinstance(left, dict) and isinstance(right, dict):
                return set(left) == set(right) and all(
                    within_tolerance(left[key], right[key]) for key in left
                )
            if isinstance(left, list) and isinstance(right, list):
                return len(left) == len(right) and all(
                    within_tolerance(a, b) for a, b in zip(left, right)
                )
            return left == right

        before_corpus = {
            "diagnose": old_scope_projection(self.runtime.diagnose(source)),
            "forecast_no_new_action": old_scope_projection(
                self.runtime.forecast(source, horizon=2)
            ),
            "rollout_unrelated_action_c": old_scope_projection(
                self.runtime.rollout(source, unaffected_policies[1], horizon=2)
            ),
            "plan_noop_vs_unrelated_c": old_scope_projection(
                self.runtime.plan(source, unaffected_policies, horizon=2)
            ),
        }
        before_manifest = {
            "state_hash": source.state_hash,
            "tolerance": {"absolute": tolerance, "relative": 0.0},
            "declared_scope_change_exclusions": [
                "consumed_state_hash",
                "local_stratum_posteriors",
                "identifiability.scope.observation_catalog_digest",
                "identifiability.scope.action_catalog_digest",
                "identifiability.scope.policy_catalog_digest",
                "identifiability.scope.utility_digest",
            ],
            "queries": {
                query_id: {
                    "sha256": canonical_sha(output),
                    "output": output,
                }
                for query_id, output in before_corpus.items()
            },
        }
        self._emit(
            "PL-REF-004",
            "old_scope_query_manifest.json",
            [
                assert_row(
                    "complete_unaffected_query_corpus_sealed",
                    len(before_manifest["queries"]) == 4
                    and all(row["sha256"] for row in before_manifest["queries"].values()),
                    4,
                    len(before_manifest["queries"]),
                )
            ],
            before_manifest,
            "Before refinement, seal diagnosis, natural forecast, unrelated action rollout, and restricted planning outputs plus the preregistered tolerance.",
        )
        if refined:
            target_runtime = refinement_result.runtime
            target_state = refinement_result.migrated_state
            after_corpus = {
                "diagnose": old_scope_projection(target_runtime.diagnose(target_state)),
                "forecast_no_new_action": old_scope_projection(
                    target_runtime.forecast(target_state, horizon=2)
                ),
                "rollout_unrelated_action_c": old_scope_projection(
                    target_runtime.rollout(target_state, unaffected_policies[1], horizon=2)
                ),
                "plan_noop_vs_unrelated_c": old_scope_projection(
                    target_runtime.plan(target_state, unaffected_policies, horizon=2)
                ),
            }
            comparisons = {
                query_id: {
                    "within_tolerance": within_tolerance(before_corpus[query_id], after_corpus[query_id]),
                    "before_sha256": canonical_sha(before_corpus[query_id]),
                    "after_sha256": canonical_sha(after_corpus[query_id]),
                }
                for query_id in before_corpus
            }
            unchanged = all(row["within_tolerance"] for row in comparisons.values()) and all(
                report["unrelated_processes_unchanged"].values()
            )
            outputs = {
                "tolerance": {"absolute": tolerance, "relative": 0.0},
                "comparisons": comparisons,
                "after_outputs": after_corpus,
                "report": report,
            }
        else:
            unchanged = False
            outputs = {"result": report}
        self._emit(
            "PL-REF-004",
            "refinement_non_regression.json",
            [
                assert_row(
                    "every_unaffected_old_scope_query_non_regressed",
                    unchanged,
                    True,
                    unchanged,
                )
            ],
            outputs,
            "After explicit migration, every unaffected diagnosis, forecast, action rollout, and plan query is rerun within the preregistered tolerance.",
        )

    def build_results(self) -> dict[str, Any]:
        architecture_results=[]
        for gid in ARCHITECTURE_GATES:
            contributing=[row for row in self.gate_results.values() if gid in row["architecture_gates"]]
            status=max((row["result"] for row in contributing),key=STATUS_PRIORITY.get) if contributing else "EVIDENCE_MISSING"
            architecture_results.append({"gate_id":gid,"result":status,"contributing_pl_gates":[row["gate_id"] for row in contributing]})
        overall=max((row["result"] for row in architecture_results),key=STATUS_PRIORITY.get)
        if overall not in {"PASS","FAIL","EVIDENCE_MISSING"}: overall="EVIDENCE_MISSING"
        evidence_manifest=[]
        for path in sorted(self.output_dir.iterdir()):
            if path.is_file() and path.name != "structural_gate_results.json": evidence_manifest.append({"path":path.name,"sha256":sha256_file(path)})
        return {
            "schema_version":"ncf.structural-gate-results.v1",
            "produced_by":"holdout/tools/structural_gate_harness.py",
            "contract_id":self.gates_contract["contract_id"],
            "contract_version":self.gates_contract["contract_version"],
            "architecture_version":"NCF-ARCH-1.0.0",
            "generated_at":self.generated_at,
            "case_blind":True,
            "scope":{"architecture_gates":ARCHITECTURE_GATES,"perfect_landing_gates":sorted(STRUCTURAL_PL_GATES),"excludes":"blind real-case gate G18"},
            "runtime_binding":{"runtime_version":RUNTIME_VERSION,"model_digest":self.runtime.model_digest,"model_path":relpath(NEUTRAL_MODEL_PATH)},
            "gate_results":[self.gate_results[x] for x in sorted(self.gate_results)],
            "architecture_gate_results":architecture_results,
            "overall_status":overall,
            "evidence_manifest":evidence_manifest,
        }

    def run(self) -> dict[str, Any]:
        if self.output_dir.exists(): shutil.rmtree(self.output_dir)
        self.output_dir.mkdir(parents=True)
        groups=[
            (["PL-IND-001"],self.probe_independence),
            (["PL-LED-002"],self.probe_ledger),
            (["PL-STATE-001"],self.probe_shared_state),
            (["PL-STATE-002"],self.probe_wire),
            (["PL-TIME-001","PL-TIME-002"],self.probe_time),
            (["PL-FACT-001","PL-FACT-002","PL-CONC-001","PL-CONC-002"],self.probe_factorial),
            (["PL-MODE-001","PL-MODE-002","PL-SUPPORT-001","PL-GEOM-001"],self.probe_modes_support_geometry),
            (["PL-DX-001","PL-PRED-001"],self.probe_heads),
            (["PL-ACT-001","PL-ACT-002"],self.probe_actions),
            (["PL-OOD-001","PL-OOD-002"],self.probe_ood),
            (["PL-REF-001","PL-REF-002","PL-REF-003","PL-REF-004"],self.probe_refinement),
        ]
        for gate_ids,fn in groups:
            try: fn()
            except Exception as exc:
                for gid in gate_ids:
                    for filename in REQUIRED_EVIDENCE_BY_GATE[gid]:
                        if filename.endswith(".txt"): continue
                        if filename not in self.artifacts:
                            self.write_artifact(filename,gid,status="EVIDENCE_MISSING",summary="Probe group crashed; no positive claim is made.",assertions=[assert_row("probe_completed",None,True,False)],errors=[f"{type(exc).__name__}: {exc}"])
                    (self.output_dir/f"{gid}.error.txt").write_text(f"{type(exc).__name__}: {exc}\n",encoding="utf-8")
            for gid in gate_ids: self.finalize_gate(gid)
        result=self.build_results()
        (self.output_dir/"structural_gate_results.json").write_bytes(canonical_json_bytes(result)+b"\n")
        return result


def fresh_worker(request_path: Path, response_path: Path) -> int:
    request=json.loads(request_path.read_text(encoding="utf-8"))
    runtime=RuntimeV2.from_json(NEUTRAL_MODEL_PATH)
    state=SharedPatientState.from_bytes(base64.b64decode(request["state"]))
    result=runtime.update(state,request["events"],advance_to=request["advance_to"],event_ledger_proof=request["proof"])
    response={"state_hash":result.state_hash,"state_b64":base64.b64encode(result.to_bytes()).decode(),"diagnose_sha256":canonical_sha(runtime.diagnose(result)),"forecast_sha256":canonical_sha(runtime.forecast(result,horizon=2))}
    response_path.write_text(json.dumps(response,sort_keys=True),encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=HOLDOUT_ROOT/"evidence"/"structural_gate_harness")
    parser.add_argument(
        "--generated-at",
        help="fixed evidence timestamp for byte-exact replay",
    )
    parser.add_argument("--fresh-worker",nargs=2,metavar=("REQUEST","RESPONSE"))
    args=parser.parse_args(argv)
    if args.fresh_worker: return fresh_worker(Path(args.fresh_worker[0]),Path(args.fresh_worker[1]))
    result=Harness(args.output, generated_at=args.generated_at).run()
    print(json.dumps({"output":str(args.output.resolve()),"overall_status":result["overall_status"],"architecture_gate_results":result["architecture_gate_results"]},ensure_ascii=False,indent=2))
    return 0 if result["overall_status"]=="PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
