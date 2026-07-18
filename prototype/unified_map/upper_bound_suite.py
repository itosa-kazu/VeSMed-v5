"""Replay-bound index for all PRE-FREEZE patient upper-bound slices.

This module deliberately does not turn the privileged probes into a benchmark
candidate, an experiment, or freeze evidence.  It gives the twenty heterogeneous
world-specific collectors (twenty-one separately counted panels because W15A
and W15B have different estimands) one content-addressed index.  Every member is
run, verified, serialized to exact canonical bytes, and can be reverified live
against its committed source artifact.

``adapter_source_digest`` is only an exact file binding.  It is not a claim
that an arbitrary long-lived interpreter executes those bytes.  Final
publication and verification therefore require a fresh process; imported-code
attestation remains the responsibility of each member adapter.
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


PROTOCOL = "ucm-pre-freeze-upper-bound-suite-index/2"
BENCHMARK_WORLD_SLOTS = tuple(f"W{index:02d}" for index in range(1, 21))
WORLD_SLOTS = BENCHMARK_WORLD_SLOTS

# These are benchmark panel identities, not adapter/module identities.  The
# nineteen ordinary worlds each own one primary panel.  W15 remains one world
# adapter but its point-identified and nonidentified estimands are counted and
# bound independently.
_W15_PANEL_IDS = (
    "W15A-randomized-identifiable",
    "W15B-observational-nonidentified",
)
_PANEL_IDS_BY_WORLD = {
    slot: (_W15_PANEL_IDS if slot == "W15" else ("primary",)) for slot in WORLD_SLOTS
}
BENCHMARK_PANEL_KEYS = tuple(
    (world_slot, panel_id)
    for world_slot in WORLD_SLOTS
    for panel_id in _PANEL_IDS_BY_WORLD[world_slot]
)


@dataclass(frozen=True, slots=True)
class _AdapterSpec:
    world_slot: str
    module_name: str


_ADAPTERS = tuple(
    _AdapterSpec(
        slot,
        (
            "prototype.unified_map.upper_bound_evaluator"
            if slot == "W01"
            else f"prototype.unified_map.upper_bound_evaluator_{slot.lower()}"
        ),
    )
    for slot in WORLD_SLOTS
)


def _panel_key_wire() -> list[dict[str, str]]:
    return [
        {"world_slot": world_slot, "panel_id": panel_id}
        for world_slot, panel_id in BENCHMARK_PANEL_KEYS
    ]


_SCOPE_STATEMENT = {
    "benchmark_status": "PRE-FREEZE",
    "patient_bound_world_slots": list(WORLD_SLOTS),
    "patient_bound_panel_keys": _panel_key_wire(),
    "benchmark_world_slots": list(BENCHMARK_WORLD_SLOTS),
    "benchmark_panel_keys": _panel_key_wire(),
    "complete_world_slot_coverage": True,
    "complete_panel_coverage": True,
    "formal_benchmark_coverage_claimed": False,
    "privileged": True,
    "upper_bound_only": True,
    "ucm_eligible": False,
    "candidate_performance_claimed": False,
    "formal_freeze_authority": False,
    "formal_expected_cell_corpus": False,
    "cross_world_metric_homogeneity_claimed": False,
    "fresh_process_live_replay_required": True,
    "adapter_source_digest_imported_code_attestation_claimed": False,
    "member_runtime_attestation_delegated_to_member_verifiers": True,
    "ledger_credit": 0,
}

_SUITE_BLOCKERS = [
    "not-a-frozen-expected-cell-corpus",
    "privileged-upper-bound-only",
    "per-world-semantics-not-uniform",
    "formal-scope-authority-absent",
    "fresh-process-live-replay-required-for-publication",
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
    panel_ids = _PANEL_IDS_BY_WORLD[spec.world_slot]
    if spec.world_slot == "W15":
        panel_contract = report.get("panel_contract")
        if type(panel_contract) is not dict:
            raise ProtocolViolation("W15 report has no two-panel contract")
        if (
            panel_contract.get("outer_world_slot") != "W15"
            or panel_contract.get("panel_alias_to_panel_id")
            != {"W15A": panel_ids[0], "W15B": panel_ids[1]}
            or panel_contract.get("panel_identities") != list(panel_ids)
            or panel_contract.get("panel_identity_is_world_slot") is not False
            or summary.get("panel_count") != 2
            or {cell.get("panel_id") for cell in cells if type(cell) is dict}
            != set(panel_ids)
        ):
            raise ProtocolViolation("W15A/W15B are not independently panel-bound")
    adapter_path, adapter_bytes = _repo_relative_source(module)
    member_report_bytes = canonical_json_bytes(report)
    return {
        "world_slot": spec.world_slot,
        "panel_ids": list(panel_ids),
        "panel_count": len(panel_ids),
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
        "member_report_bytes": len(member_report_bytes),
        "member_report_digest": digest_bytes(member_report_bytes),
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
    report = {
        "protocol": PROTOCOL,
        "bundle_kind": "pre_freeze_patient_bound_upper_bound_suite_index",
        "status_chain": deepcopy(STATUS_CHAIN),
        "scope_statement": deepcopy(_SCOPE_STATEMENT),
        "covered_world_slots": list(WORLD_SLOTS),
        "covered_panel_keys": _panel_key_wire(),
        "missing_benchmark_world_slots": [],
        "missing_benchmark_panel_keys": [],
        "members": members,
        "member_set_root": _member_set_root(members),
        "verification_summary": {
            "status": "VALID_PRE_FREEZE_TWENTY_WORLD_TWENTY_ONE_PANEL_SANITY_INDEX",
            "member_count": len(members),
            "world_count": len(WORLD_SLOTS),
            "panel_count": len(BENCHMARK_PANEL_KEYS),
            "total_cell_count": sum(member["cell_count"] for member in members),
            "total_state_binding_count": sum(
                member["state_binding_count"] for member in members
            ),
            "all_members_run_then_live_verified": True,
            "all_member_reports_exact_canonical_bytes_bound": True,
            "fresh_process_live_replay_required": True,
            "adapter_source_digest_imported_code_attestation_claimed": False,
            "member_runtime_attestation_delegated_to_member_verifiers": True,
            "complete_world_slot_coverage": True,
            "complete_panel_coverage": True,
            "formal_benchmark_coverage_claimed": False,
            "upper_bound_only": True,
            "ucm_eligible": False,
            "candidate_performance_claimed": False,
            "formal_freeze_authority": False,
            "ledger_credit": 0,
            "formalization_blockers": list(_SUITE_BLOCKERS),
        },
    }
    report["suite_root"] = digest_json(report)
    return report


def run_upper_bound_suite() -> dict[str, Any]:
    """Run and verify all twenty adapters, then return their compact index."""

    members, _ = _collect_members()
    report = _assemble_suite(members)
    verify_upper_bound_suite(report, replay_runtime=False)
    return report


def _verify_materialized_member_files(
    members: list[dict[str, Any]], member_directory: Path
) -> None:
    expected_names = {f"{slot}.json" for slot in WORLD_SLOTS}
    try:
        entries = list(member_directory.iterdir())
    except OSError as exc:
        raise ProtocolViolation("upper-bound member directory is unavailable") from exc
    if {entry.name for entry in entries} != expected_names or any(
        not entry.is_file() or entry.is_symlink() for entry in entries
    ):
        raise ProtocolViolation("upper-bound member directory is not an exact tree")
    members_by_slot = {member["world_slot"]: member for member in members}
    for slot in WORLD_SLOTS:
        try:
            raw = (member_directory / f"{slot}.json").read_bytes()
        except OSError as exc:
            raise ProtocolViolation(
                f"materialized upper-bound member {slot} cannot be read"
            ) from exc
        member = members_by_slot[slot]
        if (
            len(raw) != member["member_report_bytes"]
            or digest_bytes(raw) != member["member_report_digest"]
        ):
            raise ProtocolViolation(
                f"materialized upper-bound member {slot} is not byte-identical"
            )


def verify_upper_bound_suite(
    report: dict[str, Any],
    *,
    replay_runtime: bool = True,
    member_directory: Path | None = None,
) -> None:
    """Verify the index, exact member files, and live adapters when requested."""

    _closed(
        report,
        {
            "protocol",
            "bundle_kind",
            "status_chain",
            "scope_statement",
            "covered_world_slots",
            "covered_panel_keys",
            "missing_benchmark_world_slots",
            "missing_benchmark_panel_keys",
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
        or report["covered_panel_keys"] != _panel_key_wire()
        or report["missing_benchmark_world_slots"] != []
        or report["missing_benchmark_panel_keys"] != []
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
        "panel_ids",
        "panel_count",
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
        "member_report_bytes",
        "member_report_digest",
    }
    for spec, member in zip(_ADAPTERS, members, strict=True):
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
        expected_source_path = spec.module_name.replace(".", "/") + ".py"
        if (
            row["world_slot"] != spec.world_slot
            or row["panel_ids"] != list(_PANEL_IDS_BY_WORLD[spec.world_slot])
            or row["panel_count"] != len(_PANEL_IDS_BY_WORLD[spec.world_slot])
            or row["adapter_module"] != spec.module_name
            or row["adapter_source_path"] != expected_source_path
            or type(row["adapter_protocol"]) is not str
            or not row["adapter_protocol"]
            or type(row["source_artifact_relpath"]) is not str
            or not row["source_artifact_relpath"]
            or type(row["cell_count"]) is not int
            or row["cell_count"] <= 0
            or type(row["state_binding_count"]) is not int
            or row["state_binding_count"] <= 0
            or type(row["source_artifact_bytes"]) is not int
            or row["source_artifact_bytes"] <= 0
            or type(row["member_report_bytes"]) is not int
            or row["member_report_bytes"] <= 0
            or type(row["formalization_blockers"]) is not list
            or any(
                type(blocker) is not str or not blocker
                for blocker in row["formalization_blockers"]
            )
            or len(row["formalization_blockers"])
            != len(set(row["formalization_blockers"]))
        ):
            raise ProtocolViolation("upper-bound suite member shape is invalid")
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
            "world_count",
            "panel_count",
            "total_cell_count",
            "total_state_binding_count",
            "all_members_run_then_live_verified",
            "all_member_reports_exact_canonical_bytes_bound",
            "fresh_process_live_replay_required",
            "adapter_source_digest_imported_code_attestation_claimed",
            "member_runtime_attestation_delegated_to_member_verifiers",
            "complete_world_slot_coverage",
            "complete_panel_coverage",
            "formal_benchmark_coverage_claimed",
            "upper_bound_only",
            "ucm_eligible",
            "candidate_performance_claimed",
            "formal_freeze_authority",
            "ledger_credit",
            "formalization_blockers",
        },
        "upper-bound suite verification summary",
    )
    if summary != {
        "status": "VALID_PRE_FREEZE_TWENTY_WORLD_TWENTY_ONE_PANEL_SANITY_INDEX",
        "member_count": len(members),
        "world_count": len(WORLD_SLOTS),
        "panel_count": len(BENCHMARK_PANEL_KEYS),
        "total_cell_count": sum(member["cell_count"] for member in members),
        "total_state_binding_count": sum(
            member["state_binding_count"] for member in members
        ),
        "all_members_run_then_live_verified": True,
        "all_member_reports_exact_canonical_bytes_bound": True,
        "fresh_process_live_replay_required": True,
        "adapter_source_digest_imported_code_attestation_claimed": False,
        "member_runtime_attestation_delegated_to_member_verifiers": True,
        "complete_world_slot_coverage": True,
        "complete_panel_coverage": True,
        "formal_benchmark_coverage_claimed": False,
        "upper_bound_only": True,
        "ucm_eligible": False,
        "candidate_performance_claimed": False,
        "formal_freeze_authority": False,
        "ledger_credit": 0,
        "formalization_blockers": _SUITE_BLOCKERS,
    }:
        raise ProtocolViolation("upper-bound suite verification summary was overstated")

    if member_directory is not None:
        if not isinstance(member_directory, Path):
            raise ProtocolViolation("upper-bound member directory must be a Path")
        _verify_materialized_member_files(members, member_directory)

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
        description=(
            "Materialize the twenty-world/twenty-one-panel PRE-FREEZE "
            "upper-bound suite index."
        )
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--member-directory",
        type=Path,
        help=(
            "materialize each verified member report as WXX.json, or verify "
            "the exact member tree with --verify-only"
        ),
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
        verify_upper_bound_suite(
            decoded,
            replay_runtime=True,
            member_directory=args.member_directory,
        )
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
    "BENCHMARK_PANEL_KEYS",
    "BENCHMARK_WORLD_SLOTS",
    "PROTOCOL",
    "WORLD_SLOTS",
    "compute_upper_bound_suite_root",
    "run_upper_bound_suite",
    "verify_upper_bound_suite",
]


if __name__ == "__main__":
    raise SystemExit(_main())
