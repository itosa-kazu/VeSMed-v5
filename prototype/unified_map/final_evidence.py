"""Canonical, machine-reverified final evidence map for the isolated UCM track.

This module does not rerun candidates or repair any result.  It invokes the
published bundle verifiers, recomputes a small set of cross-bundle facts, and
builds one deliberately conservative final claim surface.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import defaultdict
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable

from .benchmark_v1_freeze import verify_freeze_manifest_bytes, verify_seed_reveal
from .benchmark_v1_runner import verify_run_bundle
from .candidate_seal import verify_candidate_seal
from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes, digest_json
from .demo_v1 import verify_demo_bundle
from .experiment_index import verify_experiment_index
from .f18_compliance_audit import verify_f18_compliance_bundle
from .independent_reproduction import verify_reproduction_bundle
from .postseal_confirm5 import verify_commitment_bytes, verify_reveal_bytes
from .postseal_confirm5_lite_scope import verify_lite_scope_bytes
from .redteam_v2_runner import verify_redteam_v2_run
from .redteam_v2_verdict import verify_verdict
from .secondary_metric_battery import verify_secondary_bundle
from .source_snapshots import verify_source_snapshots


PROTOCOL = "ucm-final-evidence/1"
FREEZE_ROOT = "sha256:8acb6623c2fdf79008240c5f5967b2143c4fb5e7bb87a4e8aa9f72e77ef33a2d"

FREEZE_PATH = "research/unified_map/BENCHMARK_V1_FREEZE.json"
SEED_REVEAL_PATH = "research/unified_map/BENCHMARK_V1_SEED_REVEAL.json"
EXPERIMENT_INDEX_PATH = "research/unified_map/EXPERIMENT_INDEX.json"
SOURCE_SNAPSHOT_INDEX_PATH = "results/unified_map/source_snapshots/index.json"
CANDIDATE_SEAL_PATH = "research/unified_map/CANDIDATE_SEAL.json"
COMPLIANCE_PATH = (
    "results/unified_map/compliance/"
    "20260719T075102Z-F18-compliance-3350cee88f"
)
DEMO_PATH = "results/unified_map/demo/20260719T073939Z-DEMO-956e6ca844"
SECONDARY_PATH = (
    "results/unified_map/secondary/"
    "20260719T090245Z-SECONDARY-25cd492973"
)
CONFIRM_SCOPE_PATH = "research/unified_map/POSTSEAL_CONFIRM5_LITE_SCOPE.json"
CONFIRM_COMMITMENT_PATH = "research/unified_map/POSTSEAL_CONFIRM5_COMMITMENT.json"
CONFIRM_REVEAL_PATH = "research/unified_map/POSTSEAL_CONFIRM5_REVEAL.json"
REDTEAM_PATH = (
    "results/unified_map/redteam_v2/"
    "20260719T093209Z-RT2-6337a6ad2d"
)
REDTEAM_VERDICT_PATH = "research/unified_map/REDTEAM_V2_VERDICT.json"
REPRODUCTION_PATH = (
    "results/unified_map/reproduction/"
    "20260719T101913Z-I18-full-repro-01c908cb1b"
)
FAILED_REPRO_PATH = (
    "research/unified_map/REPRO5_FAILED_ATTEMPT_20260719T095421Z.json"
)

FULL_RUNS = (
    ("F10", "EXP-033", "results/unified_map/runs/20260719T053350Z-EXP-033-2e4152df0d", 5),
    ("F14", "EXP-034", "results/unified_map/runs/20260719T062956Z-EXP-034-f2409bcf72", 21),
    ("F18", "EXP-035", "results/unified_map/runs/20260719T063049Z-EXP-035-c28452cba8", 5),
)


def _root() -> Path:
    return Path(__file__).resolve().parents[2]


def _canonical_object(path: Path, label: str) -> tuple[bytes, dict[str, Any]]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} is unavailable or invalid") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"{label} is not canonical JSON")
    return raw, value


def _receipt(root: Path, relative: str) -> dict[str, Any]:
    raw = (root / relative).read_bytes()
    return {
        "relative_path": relative,
        "byte_length": len(raw),
        "sha256": digest_bytes(raw),
    }


def _logical_bytes(directory: Path, name: str) -> bytes:
    path = directory / name
    if path.is_file():
        return path.read_bytes()
    compressed = directory / f"{name}.gz"
    if compressed.is_file():
        return gzip.decompress(compressed.read_bytes())
    raise ProtocolViolation(f"missing logical bundle member: {directory / name}")


def _jsonl_rows(payload: bytes, label: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(payload.splitlines(keepends=True), start=1):
        try:
            value = json.loads(line.decode("utf-8", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolViolation(f"{label}:{index} is invalid JSON") from exc
        if type(value) is not dict or canonical_json_bytes(value) != line:
            raise ProtocolViolation(f"{label}:{index} is not canonical JSON")
        rows.append(value)
    return rows


def _manifest_root(directory: Path) -> str:
    _, manifest = _canonical_object(directory / "manifest.json", "bundle manifest")
    value = manifest.get("bundle_root")
    if type(value) is not str:
        raise ProtocolViolation("bundle manifest has no root")
    return value


def _secondary_findings(directory: Path) -> dict[str, Any]:
    _, summary = _canonical_object(directory / "summary.json", "secondary summary")
    rows = _jsonl_rows((directory / "raw.jsonl").read_bytes(), "secondary raw")

    m09 = sorted(
        (
            {
                "family": row["family"],
                "normalized_error_auc": row["normalized_error_auc"],
            }
            for row in rows
            if row.get("metric") == "M09"
            and row.get("row_kind") == "sample_efficiency_summary"
        ),
        key=lambda item: (item["normalized_error_auc"], item["family"]),
    )
    for rank, row in enumerate(m09, start=1):
        row["rank"] = rank

    focus = {"F10", "F14", "F18", "F22"}
    m11_rows = [
        row for row in rows if row.get("metric") == "M11" and row.get("family") in focus
    ]
    m11: list[dict[str, Any]] = []
    for family in sorted(focus):
        selected = [row for row in m11_rows if row["family"] == family]
        if len(selected) != 2:
            raise ProtocolViolation(f"secondary M11 coverage mismatch for {family}")
        m11.append(
            {
                "family": family,
                "worlds": sorted(row["world"] for row in selected),
                "all_scope_insufficient": all(row["scope_insufficient"] for row in selected),
                "all_local_state_migration_unsupported": all(
                    not row["local_state_migration_supported"] for row in selected
                ),
                "history_replay_bytes": sum(row["history_replay_bytes"] for row in selected),
            }
        )

    m13: list[dict[str, Any]] = []
    for family in sorted(focus):
        selected = [
            row
            for row in rows
            if row.get("metric") == "M13" and row.get("family") == family
        ]
        if len(selected) != 5:
            raise ProtocolViolation(f"secondary M13 coverage mismatch for {family}")
        m13.append(
            {
                "family": family,
                "mean_python_tracemalloc_peak_increment_bytes": fmean(
                    row["peak_increment_bytes"] for row in selected
                ),
                "native_allocator_coverage": sorted(
                    {row["native_allocator_coverage"] for row in selected}
                ),
            }
        )

    m16: list[dict[str, Any]] = []
    view_fields = {
        "state_only": ("state_only_validation_mse", "state_only_sealed_test_mse"),
        "same_capacity_full_visible_history": (
            "same_capacity_full_history_validation_mse",
            "same_capacity_full_history_sealed_test_mse",
        ),
        "judge_true_state": (
            "judge_true_state_validation_mse",
            "judge_true_state_sealed_test_mse",
        ),
    }
    for family in sorted(focus):
        selected = [
            row
            for row in rows
            if row.get("metric") == "M16" and row.get("family") == family
        ]
        views: list[dict[str, Any]] = []
        for view, (validation_field, test_field) in view_fields.items():
            chosen = min(
                selected,
                key=lambda row: (row[validation_field], row["capacity"]),
            )
            views.append(
                {
                    "view": view,
                    "validation_selected_capacity": chosen["capacity"],
                    "validation_mse": chosen[validation_field],
                    "sealed_test_mse": chosen[test_field],
                }
            )
        m16.append({"family": family, "views": views, "verdict": "INCONCLUSIVE"})

    return {
        "run_id": summary["run_id"],
        "bundle_root": _manifest_root(directory),
        "row_count": summary["row_count"],
        "metrics": summary["configuration"]["metrics"],
        "worker_count": summary["worker_count"],
        "formal_frozen_metric_claim": summary["formal_frozen_metric_claim"],
        "status": summary["status"],
        "m09_top_five": m09[:5],
        "m11_focus": m11,
        "m13_focus": m13,
        "m16_focus": m16,
    }


def _full_candidate_rows(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for family, experiment_id, relative, expected_unsafe in FULL_RUNS:
        directory = root / relative
        summary = verify_run_bundle(directory)
        raw_count = len(
            _jsonl_rows(
                _logical_bytes(directory, "raw-episodes.jsonl"),
                f"{family} full raw episodes",
            )
        )
        config = summary["config"]
        if (
            config["family_code"] != family
            or config["complete_benchmark"] is not True
            or config["world_slots"] != [f"W{index:02d}" for index in range(1, 21)]
            or config["replicate_ids"] != ["R01", "R02", "R03", "R04", "R05"]
            or raw_count != 1680
            or summary["hard_failures"]["unsafe_forced_known_ood"] != expected_unsafe
            or summary["hard_gate_pass"] is not False
        ):
            raise ProtocolViolation(f"primary full-run contract mismatch for {family}")
        rows.append(
            {
                "family": family,
                "experiment_id": experiment_id,
                "run_id": summary["run_id"],
                "bundle_root": _manifest_root(directory),
                "world_count": len(config["world_slots"]),
                "panel_count": 21,
                "replicate_count": len(config["replicate_ids"]),
                "raw_episode_count": raw_count,
                "hard_gate_pass": summary["hard_gate_pass"],
                "hard_failures": summary["hard_failures"],
                "headline": summary["cross_seed_summary"],
            }
        )
    return rows


def _confirm_rows(root: Path, scope: dict[str, Any]) -> list[dict[str, Any]]:
    batch = root / scope["batch_binding"]["relative_path"]
    rows: list[dict[str, Any]] = []
    for child in scope["batch_binding"]["children"]:
        directory = batch / child["relative_path"]
        summary = verify_run_bundle(directory)
        if summary["config"]["pair_probe_limit_per_declaration"] != 0:
            raise ProtocolViolation("CONFIRM5 lite unexpectedly contains pair probes")
        rows.append(
            {
                "family": child["family_code"],
                "run_id": child["run_id"],
                "bundle_root": child["bundle_root"],
                "candidate_eligibility": summary["candidate_eligibility"],
                "hard_gate_pass": summary["hard_gate_pass"],
                "hard_failures": summary["hard_failures"],
                "headline": summary["cross_seed_summary"],
            }
        )
    return rows


def _evidence_receipts(root: Path) -> list[dict[str, Any]]:
    paths = (
        FREEZE_PATH,
        SEED_REVEAL_PATH,
        EXPERIMENT_INDEX_PATH,
        SOURCE_SNAPSHOT_INDEX_PATH,
        CANDIDATE_SEAL_PATH,
        CONFIRM_SCOPE_PATH,
        CONFIRM_COMMITMENT_PATH,
        CONFIRM_REVEAL_PATH,
        REDTEAM_VERDICT_PATH,
        FAILED_REPRO_PATH,
        "prototype/unified_map/final_evidence.py",
    )
    return [_receipt(root, path) for path in paths]


def derive_final_evidence(repo_root: Path | None = None) -> dict[str, Any]:
    """Reverify every decision-grade artifact and derive the final narrow claim."""

    root = (repo_root or _root()).resolve(strict=True)
    freeze_raw, _ = _canonical_object(root / FREEZE_PATH, "benchmark freeze")
    freeze = verify_freeze_manifest_bytes(freeze_raw)
    _, seed_reveal = _canonical_object(root / SEED_REVEAL_PATH, "benchmark seed reveal")
    verify_seed_reveal(seed_reveal, freeze)
    if (
        freeze["status"] != "FROZEN-v1"
        or freeze["freeze_root"] != FREEZE_ROOT
        or freeze["world_count"] != 20
        or freeze["panel_count"] != 21
    ):
        raise ProtocolViolation("final benchmark authority mismatch")

    experiment_index = verify_experiment_index(
        root / EXPERIMENT_INDEX_PATH, repo_root=root
    )
    accounting = experiment_index["accounting"]
    expected_accounting = {
        "total_experiments": 38,
        "count_eligible": 30,
        "count_ineligible": 8,
        "evidence_gap_count": 0,
        "failed_attempt_count": 1,
    }
    if any(accounting.get(key) != value for key, value in expected_accounting.items()):
        raise ProtocolViolation("final experiment accounting mismatch")
    eligible_families = sorted(
        {row["family"] for row in experiment_index["experiments"] if row["count_eligible"]}
    )
    if len(eligible_families) < 8:
        raise ProtocolViolation("fewer than eight count-eligible architecture families")
    snapshot = verify_source_snapshots(root, through_experiment=38)
    # Verifier diagnostics use an absolute local path.  The published evidence
    # must remain byte-identical in a clean checkout at a different location.
    snapshot = {**snapshot, "index": SOURCE_SNAPSHOT_INDEX_PATH}

    full_candidates = _full_candidate_rows(root)
    if any(row["hard_gate_pass"] for row in full_candidates):
        raise ProtocolViolation("primary hard-gate frontier is unexpectedly nonempty")

    candidate_seal = verify_candidate_seal(root / CANDIDATE_SEAL_PATH, repo_root=root)
    if (
        candidate_seal["selection_disposition"]["no_winner_claimed"] is not True
        or candidate_seal["selection_disposition"]["ucm_eligible"] is not False
    ):
        raise ProtocolViolation("candidate seal overstates the selected candidate")

    compliance = verify_f18_compliance_bundle(root / COMPLIANCE_PATH, repo_root=root)
    demo = verify_demo_bundle(root / DEMO_PATH, repo_root=root)
    secondary_verification = verify_secondary_bundle(root / SECONDARY_PATH)
    secondary = _secondary_findings(root / SECONDARY_PATH)
    if secondary_verification["bundle_root"] != secondary["bundle_root"]:
        raise ProtocolViolation("secondary verification root mismatch")

    confirm_scope_raw, _ = _canonical_object(
        root / CONFIRM_SCOPE_PATH, "CONFIRM5 lite scope"
    )
    confirm_scope = verify_lite_scope_bytes(confirm_scope_raw, repo_root=root)
    commitment_raw, _ = _canonical_object(
        root / CONFIRM_COMMITMENT_PATH, "CONFIRM5 commitment"
    )
    commitment = verify_commitment_bytes(commitment_raw)
    confirm_reveal_raw, _ = _canonical_object(
        root / CONFIRM_REVEAL_PATH, "CONFIRM5 reveal"
    )
    verify_reveal_bytes(confirm_reveal_raw, commitment)
    confirm_candidates = _confirm_rows(root, confirm_scope)
    if (
        confirm_scope["complete_benchmark"] is not False
        or confirm_scope["no_pair_collision_evidence"] is not True
        or [row["family"] for row in confirm_candidates]
        != ["F10", "F14", "F18", "B02V2", "B03V2"]
    ):
        raise ProtocolViolation("CONFIRM5 lite claim boundary mismatch")
    lite_passes = [
        row["family"]
        for row in confirm_candidates
        if row["candidate_eligibility"] == "ucm_candidate" and row["hard_gate_pass"]
    ]
    if lite_passes != ["F10", "F18"]:
        raise ProtocolViolation("CONFIRM5 lite local frontier mismatch")

    redteam_verification = verify_redteam_v2_run(
        root / REDTEAM_PATH,
        repository_root=root,
    )
    redteam_verdict_verification = verify_verdict(
        root / REDTEAM_PATH, root / REDTEAM_VERDICT_PATH
    )
    _, redteam_verdict = _canonical_object(
        root / REDTEAM_VERDICT_PATH, "red-team v2 verdict"
    )
    expected_overall = {
        "closed_catalog": "CLOSED_CATALOG_LOCAL_SUPPORT",
        "open_world_extensions": "OPEN_WORLD_SCOPE_FAILURE",
        "new_task_sufficiency": "INCONCLUSIVE",
        "state_minimality": "NOT_SUPPORTED",
    }
    if any(
        redteam_verdict["overall_verdict"].get(key) != value
        for key, value in expected_overall.items()
    ):
        raise ProtocolViolation("red-team final verdict mismatch")

    reproduction = verify_reproduction_bundle(root / REPRODUCTION_PATH)
    if (
        reproduction["exact_core_reproduction"] is not True
        or reproduction["episode_count"] != 1680
        or reproduction["rollout_query_count"] != 28720
        or reproduction["pair_count"] != 260
        or any(reproduction["differences"].values())
        or any(reproduction["failures"].values())
    ):
        raise ProtocolViolation("full independent reproduction mismatch")
    _, failed_reproduction = _canonical_object(
        root / FAILED_REPRO_PATH, "failed REPRO5 attempt receipt"
    )
    failed_preimage = {
        key: value
        for key, value in failed_reproduction.items()
        if key != "receipt_root"
    }
    if (
        failed_reproduction["receipt_root"] != digest_json(failed_preimage)
        or failed_reproduction["claim_boundary"]["reproduction_credit"] is not False
    ):
        raise ProtocolViolation("failed REPRO5 receipt mismatch")

    receipts = _evidence_receipts(root)
    preimage = {
        "protocol": PROTOCOL,
        "benchmark": {
            "status": freeze["status"],
            "freeze_root": freeze["freeze_root"],
            "world_count": freeze["world_count"],
            "panel_count": freeze["panel_count"],
            "replicate_ids": [row["replicate_id"] for row in seed_reveal["replicates"]],
            "seed_reveal_verified": True,
        },
        "experiments": {
            "index_root": experiment_index["index_root"],
            "accounting": accounting,
            "count_eligible_family_count": len(eligible_families),
            "count_eligible_families": eligible_families,
            "source_snapshot_verification": snapshot,
        },
        "primary_full_candidates": full_candidates,
        "primary_decision": {
            "hard_gate_eligible_winner_exists": False,
            "hard_gate_eligible_pareto_front": [],
            "reason": "F10, F14, and F18 each forced known diagnoses on frozen OOD rows.",
            "selected_redteam_subject": "F18",
            "selected_subject_is_winner": False,
            "claim_ceiling": "L2",
        },
        "shared_state_runtime": {
            "compliance_run_id": compliance["run_id"],
            "compliance_bundle_root": _manifest_root(root / COMPLIANCE_PATH),
            "access_trace": compliance["summary"],
            "demo_run_id": demo["run_id"],
            "demo_bundle_root": _manifest_root(root / DEMO_PATH),
            "demo_before_all_heads_same_state": demo["closed_loop"]["before"][
                "all_heads_same_state"
            ],
            "demo_after_all_heads_same_state": demo["closed_loop"]["after"][
                "all_heads_same_state"
            ],
            "demo_update_changed_state": demo["closed_loop"]["update"][
                "state_changed"
            ],
            "claim_boundary": "synthetic shared-state data flow and runtime closure only",
        },
        "supplemental_confirm5_lite": {
            "scope_root": confirm_scope["scope_root"],
            "batch_root": confirm_scope["batch_binding"]["batch_root"],
            "scope_class": confirm_scope["scope_class"],
            "complete_benchmark": confirm_scope["complete_benchmark"],
            "no_pair_collision_evidence": confirm_scope["no_pair_collision_evidence"],
            "execution_disclosure": confirm_scope["execution_disclosure"],
            "candidates": confirm_candidates,
            "local_ucm_pareto_front": ["F10", "F18"],
            "pareto_boundary": (
                "supplemental train4/validation1/test2/pair0 only; does not repair "
                "primary frozen OOD failures"
            ),
        },
        "secondary_exploratory": secondary,
        "source_distinct_redteam_v2": {
            "run_id": redteam_verification["run_id"],
            "bundle_root": redteam_verification["bundle_root"],
            "verdict_digest": redteam_verdict_verification["verdict_digest"],
            "overall_verdict": redteam_verdict["overall_verdict"],
            "attack_verdicts": redteam_verdict["attack_verdicts"],
            "verification": redteam_verification,
        },
        "independent_reproduction": {
            "run_id": reproduction["run_id"],
            "bundle_root": _manifest_root(root / REPRODUCTION_PATH),
            "source_commit": reproduction["source_commit"],
            "exact_core_reproduction": reproduction["exact_core_reproduction"],
            "episode_count": reproduction["episode_count"],
            "rollout_query_count": reproduction["rollout_query_count"],
            "pair_count": reproduction["pair_count"],
            "pair_scope": {
                "included": reproduction["scope"]["pair_probe_world_slots"],
                "excluded_extension_worlds": reproduction["scope"][
                    "pair_probe_excluded_extension_world_slots"
                ],
                "rule": reproduction["scope"]["pair_probe_scope_rule"],
            },
            "differences": reproduction["differences"],
            "failures": reproduction["failures"],
            "claim_boundary": reproduction["claim_boundary"],
            "failed_attempt_receipt_root": failed_reproduction["receipt_root"],
        },
        "final_conclusion": {
            "verified": [
                "W01-W20 benchmark-v1 freeze and public seed opening",
                "30 count-eligible substantive experiments across at least eight families",
                "three W01-W20 x five-replicate primary candidate runs",
                "one-state diagnosis/rollout/update runtime closure for sealed F18",
                "source-distinct red-team-v2 execution and raw-derived verdict",
                "full W01-W20 x five-replicate independent behavioral reproduction of sealed F18",
            ],
            "synthetic_local_support": (
                "A finite shared patient state is locally realizable inside the committed "
                "closed synthetic catalog; F10 and F18 are the bounded supplemental trade-off."
            ),
            "failed": [
                "No primary full candidate passes the frozen OOD hard gate.",
                "F18 does not natively absorb the unseen check or treatment without extension fit and visible-history replay.",
                "F18 state minimality is not supported by deletion controls.",
            ],
            "unknown": [
                "Whether a finite shared state can support preregistered open-world extensions without history replay.",
                "Whether the sealed state is sufficient for a genuinely new task under a preregistered decision threshold.",
                "Clinical validity, production safety, and global architectural optimality.",
            ],
            "clinical_validity_claimed": False,
            "production_safety_claimed": False,
            "global_optimality_claimed": False,
        },
        "next_highest_information_gain_experiment": {
            "question": (
                "Can a preregistered native scope-extensible shared state absorb a new check "
                "and an opposite-response treatment without replaying visible history?"
            ),
            "why_highest_information_gain": (
                "Current evidence already closes implementation equivalence and closed-catalog "
                "runtime compliance; the unresolved discriminator is open-world state extension."
            ),
            "required_controls": ["F10", "sealed F18", "B02V2 full visible history", "B03V2 separate task states"],
            "authority": "fresh preregistration plus post-seal commitment/reveal",
            "hard_constraints": [
                "zero visible-history replay bytes",
                "zero task-specific hidden patient state",
                "zero unsafe forced-known OOD decisions",
                "zero dangerous collisions on fresh committed pairs",
                "new-task decision threshold fixed before reveal",
            ],
            "decision": (
                "Support open-world local shared-state extension only if the native extension "
                "beats preregistered accuracy/regret margins while every hard constraint passes; "
                "otherwise retain the closed-catalog-only conclusion."
            ),
        },
        "evidence_receipts": receipts,
    }
    return {**preimage, "final_evidence_root": digest_json(preimage)}


def verify_final_evidence(
    evidence_path: Path, *, repo_root: Path | None = None
) -> dict[str, Any]:
    root = (repo_root or _root()).resolve(strict=True)
    raw, actual = _canonical_object(evidence_path, "final UCM evidence")
    expected = derive_final_evidence(root)
    if set(actual) != set(expected) or actual.get("protocol") != PROTOCOL:
        raise ProtocolViolation("final UCM evidence schema mismatch")
    preimage = {
        key: value for key, value in actual.items() if key != "final_evidence_root"
    }
    if actual["final_evidence_root"] != digest_json(preimage):
        raise ProtocolViolation("final UCM evidence root mismatch")
    if actual != expected:
        raise ProtocolViolation("final UCM evidence differs from live verified evidence")
    return {
        "status": "verified",
        "protocol": PROTOCOL,
        "final_evidence_root": actual["final_evidence_root"],
        "byte_length": len(raw),
        "sha256": digest_bytes(raw),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--output", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        if args.output.exists():
            raise ProtocolViolation("final UCM evidence publication is append-only")
        value = derive_final_evidence()
        args.output.write_bytes(canonical_json_bytes(value))
        result = verify_final_evidence(args.output)
    else:
        result = verify_final_evidence(args.evidence)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = ["PROTOCOL", "derive_final_evidence", "verify_final_evidence"]
