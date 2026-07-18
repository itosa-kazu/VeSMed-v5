"""Replay-bound index for the eight PRE-FREEZE patient upper-bound slices.

This module deliberately does not turn the privileged probes into a benchmark
candidate, an experiment, or freeze evidence.  It gives the eight heterogeneous
world-specific collectors one content-addressed index and verifies every member
by rerunning its own adapter against the committed source artifact.
"""

from __future__ import annotations

import importlib
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .canonical import (
    ProtocolViolation,
    canonical_json_bytes,
    digest_bytes,
    digest_json,
)
from .upper_bound_evaluator import STATUS_CHAIN


PROTOCOL = "ucm-pre-freeze-upper-bound-suite-index/1"
WORLD_SLOTS = ("W01", "W02", "W04", "W08", "W15", "W18", "W19", "W20")
BENCHMARK_WORLD_SLOTS = tuple(f"W{index:02d}" for index in range(1, 21))


@dataclass(frozen=True, slots=True)
class _AdapterSpec:
    world_slot: str
    module_name: str


_ADAPTERS = (
    _AdapterSpec("W01", "prototype.unified_map.upper_bound_evaluator"),
    *(
        _AdapterSpec(
            slot, f"prototype.unified_map.upper_bound_evaluator_{slot.lower()}"
        )
        for slot in WORLD_SLOTS[1:]
    ),
)

_SCOPE_STATEMENT = {
    "benchmark_status": "PRE-FREEZE",
    "patient_bound_world_slots": list(WORLD_SLOTS),
    "benchmark_world_slots": list(BENCHMARK_WORLD_SLOTS),
    "full_benchmark_coverage": False,
    "privileged": True,
    "upper_bound_only": True,
    "candidate_performance_claimed": False,
    "formal_freeze_authority": False,
    "formal_expected_cell_corpus": False,
    "cross_world_metric_homogeneity_claimed": False,
    "ledger_credit": 0,
}

_SUITE_BLOCKERS = [
    "not-a-frozen-expected-cell-corpus",
    "partial-eight-of-twenty-patient-bound-slices",
    "privileged-upper-bound-only",
    "per-world-semantics-not-uniform",
    "no-candidate-or-freeze-credit",
]


def _closed(value: object, keys: set[str], label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != keys:
        raise ProtocolViolation(f"{label} is not a closed object")
    return value


def _digest(value: object, label: str) -> str:
    if (
        type(value) is not str
        or not value.startswith("sha256:")
        or len(value) != 71
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        raise ProtocolViolation(f"{label} must be a sha256-prefixed digest")
    return value


def _load_adapter(spec: _AdapterSpec) -> tuple[ModuleType, Any, Any, Path]:
    module = importlib.import_module(spec.module_name)
    suffix = spec.world_slot.lower()
    try:
        run = getattr(module, f"run_{suffix}_upper_bound_sanity")
        verify = getattr(module, f"verify_{suffix}_upper_bound_sanity")
        source_artifact = Path(getattr(module, f"DEFAULT_{spec.world_slot}_ARTIFACT"))
    except (AttributeError, TypeError) as exc:
        raise ProtocolViolation(
            f"{spec.world_slot} upper-bound adapter API is incomplete"
        ) from exc
    if not callable(run) or not callable(verify):
        raise ProtocolViolation(
            f"{spec.world_slot} upper-bound adapter API is not callable"
        )
    return module, run, verify, source_artifact


def _repo_relative_source(module: ModuleType) -> tuple[str, bytes]:
    source_name = getattr(module, "__file__", None)
    if type(source_name) is not str:
        raise ProtocolViolation("upper-bound adapter has no source file")
    source_path = Path(source_name).resolve()
    repo_root = Path(__file__).resolve().parents[2]
    try:
        relative = source_path.relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise ProtocolViolation(
            "upper-bound adapter source is outside the repository"
        ) from exc
    if not relative.startswith("prototype/unified_map/") or not relative.endswith(
        ".py"
    ):
        raise ProtocolViolation(
            "upper-bound adapter source is outside its isolated package"
        )
    try:
        raw = source_path.read_bytes()
    except OSError as exc:
        raise ProtocolViolation("upper-bound adapter source cannot be read") from exc
    return relative, raw


def _member_record(
    spec: _AdapterSpec,
    module: ModuleType,
    report: dict[str, Any],
) -> dict[str, Any]:
    source_anchor = _closed(
        report.get("source_anchor"),
        {
            "artifact_relpath",
            "artifact_digest",
            "artifact_bytes",
            "artifact_protocol",
            "replay_digest",
            "byte_identical_replay",
        },
        f"{spec.world_slot} source anchor",
    )
    summary = report.get("verification_summary")
    if type(summary) is not dict:
        raise ProtocolViolation(f"{spec.world_slot} verification summary is missing")
    blockers = summary.get("formalization_blockers")
    if (
        type(blockers) is not list
        or any(type(item) is not str or not item for item in blockers)
        or len(blockers) != len(set(blockers))
    ):
        raise ProtocolViolation(
            f"{spec.world_slot} formalization blockers are not an exact string set"
        )
    if (
        report.get("world_slot") != spec.world_slot
        or report.get("status_chain") != STATUS_CHAIN
        or type(summary.get("status")) is not str
        or not summary["status"].startswith("VALID_PRE_FREEZE")
        or summary.get("ledger_credit") != 0
        or source_anchor["byte_identical_replay"] is not True
        or source_anchor["artifact_digest"] != source_anchor["replay_digest"]
    ):
        raise ProtocolViolation(
            f"{spec.world_slot} report overstates or breaks its PRE-FREEZE scope"
        )
    cells = report.get("cells")
    states = report.get("states")
    if type(cells) is not list or type(states) is not dict:
        raise ProtocolViolation(f"{spec.world_slot} report has no typed cells/states")
    state_binding_count = summary.get("state_binding_count")
    if (
        summary.get("cell_count") != len(cells)
        or type(state_binding_count) is not int
        or state_binding_count <= 0
    ):
        raise ProtocolViolation(
            f"{spec.world_slot} summary count does not match its closed report"
        )
    adapter_path, adapter_bytes = _repo_relative_source(module)
    return {
        "world_slot": spec.world_slot,
        "adapter_module": spec.module_name,
        "adapter_source_path": adapter_path,
        "adapter_source_digest": digest_bytes(adapter_bytes),
        "adapter_protocol": report.get("protocol"),
        "source_artifact_relpath": source_anchor["artifact_relpath"],
        "source_artifact_digest": source_anchor["artifact_digest"],
        "source_artifact_bytes": source_anchor["artifact_bytes"],
        "manifest_digest": report.get("manifest_digest"),
        "cell_set_root": report.get("cell_set_root"),
        "cell_count": len(cells),
        "state_binding_count": state_binding_count,
        "formalization_blockers": list(blockers),
        "member_bundle_root": report.get("bundle_root"),
        "member_report_digest": digest_bytes(canonical_json_bytes(report)),
    }


def _collect_members() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    members: list[dict[str, Any]] = []
    reports: dict[str, dict[str, Any]] = {}
    for spec in _ADAPTERS:
        module, run, verify, source_artifact = _load_adapter(spec)
        report = run(source_artifact=source_artifact)
        verify(report, source_artifact=source_artifact, replay_runtime=True)
        members.append(_member_record(spec, module, report))
        reports[spec.world_slot] = report
    return members, reports


def _member_set_root(members: list[dict[str, Any]]) -> str:
    return digest_json(
        {
            "protocol": PROTOCOL,
            "members": members,
        }
    )


def compute_upper_bound_suite_root(value: dict[str, Any]) -> str:
    if type(value) is not dict or "suite_root" not in value:
        raise ProtocolViolation("upper-bound suite must contain suite_root")
    preimage = {key: item for key, item in value.items() if key != "suite_root"}
    return digest_json(preimage)


def _assemble_suite(members: list[dict[str, Any]]) -> dict[str, Any]:
    missing = [slot for slot in BENCHMARK_WORLD_SLOTS if slot not in WORLD_SLOTS]
    report = {
        "protocol": PROTOCOL,
        "bundle_kind": "pre_freeze_patient_bound_upper_bound_suite_index",
        "status_chain": deepcopy(STATUS_CHAIN),
        "scope_statement": deepcopy(_SCOPE_STATEMENT),
        "covered_world_slots": list(WORLD_SLOTS),
        "missing_benchmark_world_slots": missing,
        "members": members,
        "member_set_root": _member_set_root(members),
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_EIGHT_WORLD_SANITY_INDEX",
            "member_count": len(members),
            "total_cell_count": sum(member["cell_count"] for member in members),
            "total_state_binding_count": sum(
                member["state_binding_count"] for member in members
            ),
            "all_members_live_replayed": True,
            "full_benchmark_coverage": False,
            "candidate_performance_claimed": False,
            "formal_freeze_authority": False,
            "ledger_credit": 0,
            "formalization_blockers": list(_SUITE_BLOCKERS),
        },
    }
    report["suite_root"] = digest_json(report)
    return report


def run_upper_bound_suite() -> dict[str, Any]:
    """Run and verify all eight adapters, then return their compact index."""

    members, _ = _collect_members()
    report = _assemble_suite(members)
    verify_upper_bound_suite(report, replay_runtime=False)
    return report


def verify_upper_bound_suite(
    report: dict[str, Any],
    *,
    replay_runtime: bool = True,
) -> None:
    """Verify the index and optionally rerun every world-specific adapter."""

    _closed(
        report,
        {
            "protocol",
            "bundle_kind",
            "status_chain",
            "scope_statement",
            "covered_world_slots",
            "missing_benchmark_world_slots",
            "members",
            "member_set_root",
            "verification_summary",
            "suite_root",
        },
        "upper-bound suite",
    )
    if (
        report["protocol"] != PROTOCOL
        or report["bundle_kind"] != "pre_freeze_patient_bound_upper_bound_suite_index"
        or report["status_chain"] != STATUS_CHAIN
        or report["scope_statement"] != _SCOPE_STATEMENT
        or report["covered_world_slots"] != list(WORLD_SLOTS)
        or report["missing_benchmark_world_slots"]
        != [slot for slot in BENCHMARK_WORLD_SLOTS if slot not in WORLD_SLOTS]
    ):
        raise ProtocolViolation("upper-bound suite identity or scope mismatch")
    members = report["members"]
    if type(members) is not list or len(members) != len(_ADAPTERS):
        raise ProtocolViolation("upper-bound suite member coverage mismatch")
    if [member.get("world_slot") for member in members if type(member) is dict] != list(
        WORLD_SLOTS
    ):
        raise ProtocolViolation("upper-bound suite member order/identity mismatch")
    member_keys = {
        "world_slot",
        "adapter_module",
        "adapter_source_path",
        "adapter_source_digest",
        "adapter_protocol",
        "source_artifact_relpath",
        "source_artifact_digest",
        "source_artifact_bytes",
        "manifest_digest",
        "cell_set_root",
        "cell_count",
        "state_binding_count",
        "formalization_blockers",
        "member_bundle_root",
        "member_report_digest",
    }
    for member in members:
        row = _closed(member, member_keys, "upper-bound suite member")
        for key in (
            "adapter_source_digest",
            "source_artifact_digest",
            "manifest_digest",
            "cell_set_root",
            "member_bundle_root",
            "member_report_digest",
        ):
            _digest(row[key], f"upper-bound suite member {key}")
        if (
            type(row["cell_count"]) is not int
            or row["cell_count"] <= 0
            or type(row["state_binding_count"]) is not int
            or row["state_binding_count"] <= 0
            or type(row["source_artifact_bytes"]) is not int
            or row["source_artifact_bytes"] <= 0
        ):
            raise ProtocolViolation("upper-bound suite member count is invalid")
    if _member_set_root(members) != report["member_set_root"]:
        raise ProtocolViolation("upper-bound suite member-set root mismatch")
    _digest(report["member_set_root"], "upper-bound suite member-set root")
    if compute_upper_bound_suite_root(report) != report["suite_root"]:
        raise ProtocolViolation("upper-bound suite root mismatch")
    _digest(report["suite_root"], "upper-bound suite root")

    summary = _closed(
        report["verification_summary"],
        {
            "status",
            "member_count",
            "total_cell_count",
            "total_state_binding_count",
            "all_members_live_replayed",
            "full_benchmark_coverage",
            "candidate_performance_claimed",
            "formal_freeze_authority",
            "ledger_credit",
            "formalization_blockers",
        },
        "upper-bound suite verification summary",
    )
    if summary != {
        "status": "VALID_PRE_FREEZE_EIGHT_WORLD_SANITY_INDEX",
        "member_count": len(members),
        "total_cell_count": sum(member["cell_count"] for member in members),
        "total_state_binding_count": sum(
            member["state_binding_count"] for member in members
        ),
        "all_members_live_replayed": True,
        "full_benchmark_coverage": False,
        "candidate_performance_claimed": False,
        "formal_freeze_authority": False,
        "ledger_credit": 0,
        "formalization_blockers": _SUITE_BLOCKERS,
    }:
        raise ProtocolViolation("upper-bound suite verification summary was overstated")

    if replay_runtime:
        expected, _ = _collect_members()
        if members != expected:
            raise ProtocolViolation(
                "upper-bound suite members differ from live adapter replay"
            )


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(payload)
    except FileExistsError as exc:
        raise ProtocolViolation(f"refusing to overwrite {path}") from exc


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Materialize the eight-world PRE-FREEZE upper-bound suite index."
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--member-directory",
        type=Path,
        help="optionally materialize each verified member report as WXX.json",
    )
    parser.add_argument(
        "--verify-only",
        type=Path,
        help="verify an existing suite index instead of generating one",
    )
    args = parser.parse_args()
    if args.verify_only is not None:
        import json

        try:
            raw = args.verify_only.read_bytes()
            decoded = json.loads(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            raise ProtocolViolation("suite index cannot be decoded") from exc
        if canonical_json_bytes(decoded) != raw:
            raise ProtocolViolation("suite index is not canonical JSON")
        verify_upper_bound_suite(decoded, replay_runtime=True)
        return 0

    if args.output is None:
        parser.error("--output is required unless --verify-only is used")

    members, reports = _collect_members()
    suite = _assemble_suite(members)
    verify_upper_bound_suite(suite, replay_runtime=False)
    targets: list[tuple[Path, bytes]] = [(args.output, canonical_json_bytes(suite))]
    if args.member_directory is not None:
        targets.extend(
            (
                args.member_directory / f"{slot}.json",
                canonical_json_bytes(reports[slot]),
            )
            for slot in WORLD_SLOTS
        )
    existing = [str(path) for path, _ in targets if path.exists()]
    if existing:
        raise ProtocolViolation(
            "refusing partial publication because targets already exist: "
            + ", ".join(existing)
        )
    for path, payload in targets:
        _write_new(path, payload)
    return 0


__all__ = [
    "BENCHMARK_WORLD_SLOTS",
    "PROTOCOL",
    "WORLD_SLOTS",
    "compute_upper_bound_suite_root",
    "run_upper_bound_suite",
    "verify_upper_bound_suite",
]


if __name__ == "__main__":
    raise SystemExit(_main())
