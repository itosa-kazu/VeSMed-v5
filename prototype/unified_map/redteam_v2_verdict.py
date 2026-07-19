"""Deterministic, evidence-bounded verdict for the public UCM red-team-v2 bundle.

This module does not execute candidates, generate attacks, or rerun a benchmark.
It verifies the immutable public bundle receipts, reads the already-produced raw
gzip JSONL records, and derives a deliberately narrow verdict from those rows.
"""

from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .canonical import canonical_json_bytes, digest_bytes, digest_json


VERDICT_PROTOCOL = "ucm-redteam-v2-verdict/1"
RUN_PROTOCOL = "ucm-source-distinct-redteam-run/2"
MANIFEST_PROTOCOL = "ucm-source-distinct-redteam-manifest/2"
EXPECTED_ATTACK_CLASSES = (
    "new_check",
    "new_treatment_opposite_response",
    "new_nonlinear_combination",
    "new_task_conditional_expected_future_utility",
    "ood",
    "dangerous_collision",
    "history_deletion_trio",
    "same_state_time_scales",
    "action_semantics",
    "query_update_rehydrate_compliance",
)


class VerdictViolation(ValueError):
    """Raised when the public bundle or its verdict is inconsistent."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise VerdictViolation(message)


def _read_json(path: Path, *, canonical: bool = True) -> dict[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw)
    _require(type(value) is dict, f"{path.name} must contain a JSON object")
    if canonical:
        _require(raw == canonical_json_bytes(value), f"{path.name} is not canonical JSON")
    return value


def _receipt(raw: bytes) -> dict[str, Any]:
    return {"byte_length": len(raw), "sha256": digest_bytes(raw)}


def _artifact_map(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = manifest.get("artifacts")
    _require(type(artifacts) is list, "manifest artifacts must be a list")
    result: dict[str, dict[str, Any]] = {}
    for entry in artifacts:
        _require(type(entry) is dict and type(entry.get("path")) is str, "bad artifact entry")
        path = entry["path"]
        _require(path not in result, f"duplicate manifest artifact: {path}")
        result[path] = entry
    return result


def _verify_public_bundle(
    bundle_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, bytes]]:
    manifest_path = bundle_dir / "manifest.json"
    summary_path = bundle_dir / "summary.json"
    manifest = _read_json(manifest_path)
    summary = _read_json(summary_path)
    _require(manifest.get("protocol") == MANIFEST_PROTOCOL, "manifest protocol mismatch")
    _require(summary.get("protocol") == RUN_PROTOCOL, "summary protocol mismatch")
    _require(manifest.get("run_id") == summary.get("run_id"), "run id mismatch")
    _require(bundle_dir.name == summary["run_id"], "bundle directory/run id mismatch")
    _require(
        manifest.get("bundle_root") == digest_json(manifest["artifacts"]),
        "bundle root mismatch",
    )

    artifacts = _artifact_map(manifest)
    decompressed: dict[str, bytes] = {}
    raw_receipts = summary.get("raw_receipts")
    _require(type(raw_receipts) is dict, "summary raw_receipts missing")
    for logical_path, receipt in raw_receipts.items():
        _require(type(receipt) is dict, f"bad raw receipt: {logical_path}")
        _require(receipt.get("path") == logical_path, f"raw path mismatch: {logical_path}")
        gzip_path = receipt.get("gzip_path")
        _require(type(gzip_path) is str, f"gzip path missing: {logical_path}")
        compressed = (bundle_dir / gzip_path).read_bytes()
        _require(digest_bytes(compressed) == receipt["gzip_sha256"], f"gzip digest mismatch: {gzip_path}")
        raw = gzip.decompress(compressed)
        _require(len(raw) == receipt["byte_length"], f"raw byte length mismatch: {logical_path}")
        _require(digest_bytes(raw) == receipt["sha256"], f"raw digest mismatch: {logical_path}")
        _require(raw.count(b"\n") == receipt["line_count"], f"raw line count mismatch: {logical_path}")
        decompressed[logical_path] = raw
        _require(artifacts.get(logical_path) == {
            "byte_length": receipt["byte_length"],
            "line_count": receipt["line_count"],
            "path": logical_path,
            "sha256": receipt["sha256"],
        }, f"manifest raw receipt mismatch: {logical_path}")
        _require(artifacts.get(gzip_path) == {
            "byte_length": len(compressed),
            "path": gzip_path,
            "sha256": receipt["gzip_sha256"],
        }, f"manifest gzip receipt mismatch: {gzip_path}")

    for relative, entry in artifacts.items():
        path = bundle_dir / relative
        if not path.exists():
            _require(relative in decompressed, f"missing bundle artifact: {relative}")
            continue
        raw = path.read_bytes()
        _require(len(raw) == entry["byte_length"], f"artifact byte length mismatch: {relative}")
        _require(digest_bytes(raw) == entry["sha256"], f"artifact digest mismatch: {relative}")
        if "line_count" in entry:
            _require(raw.count(b"\n") == entry["line_count"], f"artifact line count mismatch: {relative}")

    chronology = _read_json(bundle_dir / "chronology.json")
    commitment_raw = (bundle_dir / "commitment.json").read_bytes()
    amendment_raw = (bundle_dir / "evaluator-amendment.json").read_bytes()
    commitment = json.loads(commitment_raw)
    amendment = json.loads(amendment_raw)
    _require(
        digest_bytes(commitment_raw) == chronology["commitment_blob_digest"],
        "commitment chronology binding mismatch",
    )
    amendment_chronology = chronology.get("evaluator_amendment")
    _require(type(amendment_chronology) is dict, "evaluator amendment chronology missing")
    _require(
        digest_bytes(amendment_raw) == amendment_chronology["amendment_blob_digest"],
        "evaluator amendment chronology binding mismatch",
    )
    _require(commitment["pack_digest"] == summary["pack_digest"], "pack binding mismatch")
    _require(amendment["original_pack_digest"] == summary["pack_digest"], "amendment pack mismatch")
    _require(
        summary["evaluator_amendment_digest"] == amendment_chronology["amendment_digest"],
        "summary amendment digest mismatch",
    )
    _require(
        summary["evaluator_amendment_git_commit"] == amendment_chronology["amendment_git_commit"],
        "summary amendment commit mismatch",
    )
    return manifest, summary, chronology, decompressed


def _jsonl(raw: bytes, logical_path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(raw.splitlines(), start=1):
        value = json.loads(line)
        _require(type(value) is dict, f"{logical_path}:{index} must be an object")
        _require(line + b"\n" == canonical_json_bytes(value), f"{logical_path}:{index} is not canonical")
        rows.append(value)
    return rows


def _per_implementation(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(row["implementation_id"] for row in rows).items()))


def _query_plan(row: dict[str, Any]) -> str | None:
    query = row.get("query")
    return query.get("plan_id") if type(query) is dict else None


def _new_task_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    implementations = sorted({row["implementation_id"] for row in rows})
    _require(implementations, "new-task probe rows missing")
    by_implementation: dict[str, list[dict[str, Any]]] = {}
    for implementation in implementations:
        selected = [row for row in rows if row["implementation_id"] == implementation]
        by_implementation[implementation] = sorted(
            [
                {
                    "capacity": row["capacity"],
                    "mae": row["mae"],
                    "rmse": row["rmse"],
                    "view": row["view"],
                }
                for row in selected
            ],
            key=lambda cell: (cell["capacity"], cell["view"]),
        )
    shared = by_implementation[implementations[0]]
    identical = all(by_implementation[item] == shared for item in implementations[1:])
    _require(all(row["target_is_conditional_expectation"] is True for row in rows),
             "new-task target is not uniformly conditional expectation")
    _require(all(row["realized_future_noise_used"] is False for row in rows),
             "new-task probe used realized future noise")
    return {
        "implementation_count": len(implementations),
        "implementations": implementations,
        "metrics_identical_across_implementations": identical,
        "probe_cells_per_implementation": len(shared),
        "shared_cells": shared if identical else [],
        "target_is_conditional_expectation": True,
        "realized_future_noise_used": False,
        "train_count": sorted({row["train_count"] for row in rows}),
        "test_count": sorted({row["test_count"] for row in rows}),
    }


def derive_verdict(bundle_dir: Path) -> dict[str, Any]:
    """Derive the exact narrow verdict from a completed public bundle."""

    bundle_dir = bundle_dir.resolve()
    manifest, summary, chronology, raw = _verify_public_bundle(bundle_dir)
    episodes = _jsonl(raw["raw-episodes.jsonl"], "raw-episodes.jsonl")
    pairs = _jsonl(raw["raw-pairs.jsonl"], "raw-pairs.jsonl")
    probes = _jsonl(raw["raw-probes.jsonl"], "raw-probes.jsonl")
    run_id = summary["run_id"]
    _require(all(row.get("run_id") == run_id for row in episodes + pairs + probes),
             "raw row run id mismatch")

    reveal = _read_json(bundle_dir / "reveal.json")
    pack = reveal["pack"]
    _require(tuple(pack["attack_classes"]) == EXPECTED_ATTACK_CLASSES, "attack class registry mismatch")
    threshold = pack["thresholds"]["state_equivalence_l2"]
    oracle_threshold = pack["thresholds"]["oracle_distinguishable_l2"]

    ood_rows = [row for row in episodes if row["attack_id"] == "ood"]
    unsafe_ood = sum(bool(row["unsafe_ood_forced_known"]) for row in ood_rows)
    _require(unsafe_ood == summary["unsafe_ood_forced_known_count"], "OOD summary mismatch")

    collision_rows = [row for row in pairs if row["attack_id"] == "dangerous_collision"]
    recomputed_dangerous = sum(
        row["state_distance"] <= threshold and row["oracle_margin"] >= oracle_threshold
        for row in collision_rows
    )
    _require(
        all(bool(row["dangerous_collision"]) == (
            row["state_distance"] <= threshold and row["oracle_margin"] >= oracle_threshold
        ) for row in collision_rows),
        "dangerous-collision row mismatch",
    )
    _require(recomputed_dangerous == summary["dangerous_collision_count"], "collision summary mismatch")

    check_probe_rows = [row for row in probes if row["attack_id"] == "new_check"]
    check_rollout_rows = [row for row in episodes if _query_plan(row) == "new_check"]
    treatment_rows = [row for row in episodes if row["attack_id"] == "new_treatment_opposite_response"]
    combination_rows = [row for row in episodes if row["attack_id"] == "new_nonlinear_combination"]
    time_rows = [row for row in episodes if row["attack_id"] == "same_state_time_scales"]
    action_rows = [row for row in episodes if row["attack_id"] == "action_semantics"]
    history_rows = [row for row in pairs if row["attack_id"] == "history_deletion_trio"]
    compliance_rows = [row for row in probes if row["attack_id"] == "query_update_rehydrate_compliance"]
    task_rows = [row for row in probes if row["attack_id"] == "new_task_conditional_expected_future_utility"]

    equivalent_history = [row for row in history_rows if row["expected_state_relation"] == "equivalent"]
    distinguishable_history = [row for row in history_rows if row["expected_state_relation"] == "distinguishable"]
    false_splits = sum(row["state_distance"] > threshold for row in equivalent_history)
    preserved_distinctions = sum(row["state_distance"] > threshold for row in distinguishable_history)

    new_task_contract = pack["new_task_contract"]
    preregistered_new_task_criterion = any(
        key in new_task_contract for key in ("decision_criterion", "pass_threshold", "pass_thresholds")
    )
    _require(not preregistered_new_task_criterion, "unsupported new-task decision criterion present")

    all_compliance_true = all(
        row["state_hash_before"] == row["state_hash_after"]
        and row["query_order_diagnosis_equal"] is True
        and row["query_order_rollout_equal"] is True
        and row["primary_scope_update_old_hash"] != row["primary_scope_update_new_hash"]
        and row["primary_scope_update_replay_match"] is True
        and row["cold_state_hash_equal"] is True
        and row["cold_diagnosis_equal"] is True
        and row["cold_rollout_equal"] is True
        for row in compliance_rows
    )

    attack_verdicts = [
        {
            "attack_class": "new_check",
            "verdict": "OPEN_WORLD_SCOPE_FAILURE",
            "evidence": {
                "probe_rows": len(check_probe_rows),
                "per_implementation_probe_rows": _per_implementation(check_probe_rows),
                "controls": sorted({row["control"] for row in check_probe_rows}),
                "operator_outside_primary_scope_rows": sum(not row["operator_in_primary_scope"] for row in check_probe_rows),
                "nonadmissible_old_scope_update_rows": sum(row["scope_result"] == "nonadmissible_old_scope_update_attempt" for row in check_probe_rows),
                "extension_refit_required_rows": sum(row["migration_cost"]["extension_refit_required"] is True for row in check_probe_rows),
                "visible_history_replay_required_rows": sum(row["migration_cost"]["visible_history_replay_required"] is True for row in check_probe_rows),
                "primary_state_reusable_without_replay_rows": sum(row["migration_cost"]["primary_state_reusable_without_replay"] is True for row in check_probe_rows),
                "incremental_replay_match_rows": sum(row["incremental_replay_match"] is True for row in check_probe_rows),
                "rollout_rows": len(check_rollout_rows),
                "scope_insufficient_rollout_rows": sum(row["scope_result"] == "scope_insufficient" for row in check_rollout_rows),
                "abstained_rollout_rows": sum(row["prediction"]["abstained"] is True for row in check_rollout_rows),
                "migration_required": pack["extension_contract"]["admissible_migration"],
            },
            "claim_boundary": "The primary-scope state cannot locally absorb or answer the new check; extension fit plus visible-history replay is required.",
        },
        {
            "attack_class": "new_treatment_opposite_response",
            "verdict": "OPEN_WORLD_SCOPE_FAILURE",
            "evidence": {
                "rows": len(treatment_rows),
                "per_implementation_rows": _per_implementation(treatment_rows),
                "opposite_response_oracle_valid_rows": sum(row["opposite_response_oracle_valid"] is True for row in treatment_rows),
                "positive_oracle_effect_rows": sum(row["oracle_effect_sign"] == 1 for row in treatment_rows),
                "negative_oracle_effect_rows": sum(row["oracle_effect_sign"] == -1 for row in treatment_rows),
                "scope_insufficient_rows": sum(row["scope_result"] == "scope_insufficient" for row in treatment_rows),
                "abstained_rows": sum(row["prediction"]["abstained"] is True for row in treatment_rows),
                "migration_required_rows": sum(row["migration_required"] == pack["extension_contract"]["admissible_migration"] for row in treatment_rows),
                "query_state_unchanged_rows": sum(row["pre_state_hash"] == row["post_state_hash"] for row in treatment_rows),
            },
            "claim_boundary": "Safe abstention is not evidence that F18 supports the unseen treatment or its opposite response.",
        },
        {
            "attack_class": "new_nonlinear_combination",
            "verdict": "MIXED_CLOSED_CATALOG_LOCAL_SUPPORT_AND_OPEN_WORLD_SCOPE_FAILURE",
            "evidence": {
                "rows": len(combination_rows),
                "per_implementation_rows": _per_implementation(combination_rows),
                "primary_scope_natural_rows": sum(_query_plan(row) == "natural" and row["scope_result"] == "primary_scope" for row in combination_rows),
                "scope_insufficient_new_check_rows": sum(_query_plan(row) == "new_check" and row["scope_result"] == "scope_insufficient" for row in combination_rows),
                "abstained_new_check_rows": sum(_query_plan(row) == "new_check" and row["prediction"]["abstained"] is True for row in combination_rows),
            },
            "claim_boundary": "Natural queries remain callable in the committed catalog, while the extension operator remains out of scope; no preregistered predictive-accuracy pass threshold is inferred.",
        },
        {
            "attack_class": "new_task_conditional_expected_future_utility",
            "verdict": "INCONCLUSIVE",
            "evidence": {
                **_new_task_metrics(task_rows),
                "preregistered_decision_criterion_present": preregistered_new_task_criterion,
                "views": sorted({row["view"] for row in task_rows}),
                "capacities": sorted({row["capacity"] for row in task_rows}),
            },
            "claim_boundary": "Same-capacity state/history/true-state readout numbers are descriptive only because no preregistered decision criterion supports a sufficiency or superiority claim.",
        },
        {
            "attack_class": "ood",
            "verdict": "CLOSED_CATALOG_LOCAL_SUPPORT",
            "evidence": {
                "rows": len(ood_rows),
                "per_implementation_rows": _per_implementation(ood_rows),
                "unsafe_forced_known_rows": unsafe_ood,
                "unknown_probability_one_rows": sum(row["prediction"]["probabilities"].get("unknown") == 1.0 for row in ood_rows),
            },
            "claim_boundary": "Zero unsafe forced-known decisions is local evidence for this committed synthetic OOD pack, not universal open-world coverage.",
        },
        {
            "attack_class": "dangerous_collision",
            "verdict": "CLOSED_CATALOG_LOCAL_SUPPORT",
            "evidence": {
                "rows": len(collision_rows),
                "per_implementation_rows": _per_implementation(collision_rows),
                "recomputed_dangerous_collision_rows": recomputed_dangerous,
                "state_equivalence_l2": threshold,
                "oracle_distinguishable_l2": oracle_threshold,
                "minimum_state_distance": min(row["state_distance"] for row in collision_rows),
                "minimum_oracle_margin": min(row["oracle_margin"] for row in collision_rows),
            },
            "claim_boundary": "No dangerous collision occurred among the eight preregistered paired rows; this does not close untested collision classes.",
        },
        {
            "attack_class": "history_deletion_trio",
            "verdict": "NON_MINIMAL_STATE_EVIDENCE",
            "evidence": {
                "rows": len(history_rows),
                "per_implementation_rows": _per_implementation(history_rows),
                "oracle_equivalent_rows": len(equivalent_history),
                "oracle_equivalent_rows_collapsed": len(equivalent_history) - false_splits,
                "oracle_equivalent_false_split_rows": false_splits,
                "oracle_distinguishable_rows": len(distinguishable_history),
                "oracle_distinguishable_rows_separated": preserved_distinctions,
                "equivalent_row_state_distances": sorted(row["state_distance"] for row in equivalent_history),
                "state_equivalence_l2": threshold,
            },
            "claim_boundary": "The state preserves relevant distinctions but also separates all oracle-equivalent deletion controls, so minimal behavioral state is not supported.",
        },
        {
            "attack_class": "same_state_time_scales",
            "verdict": "MIXED_CLOSED_CATALOG_LOCAL_SUPPORT_AND_OPEN_WORLD_SCOPE_FAILURE",
            "evidence": {
                "rows": len(time_rows),
                "per_implementation_rows": _per_implementation(time_rows),
                "horizons": sorted({row["query"]["horizon"] for row in time_rows}),
                "natural_primary_scope_rows": sum(_query_plan(row) == "natural" and row["scope_result"] == "primary_scope" for row in time_rows),
                "new_check_scope_insufficient_rows": sum(_query_plan(row) == "new_check" and row["scope_result"] == "scope_insufficient" for row in time_rows),
                "query_state_unchanged_rows": sum(row["pre_state_hash"] == row["post_state_hash"] for row in time_rows),
                "unique_pre_state_hashes_by_implementation": {
                    implementation: len({row["pre_state_hash"] for row in time_rows if row["implementation_id"] == implementation})
                    for implementation in sorted({row["implementation_id"] for row in time_rows})
                },
            },
            "claim_boundary": "One shared state per implementation served all three horizons for natural queries; the new-check plan still required migration and replay.",
        },
        {
            "attack_class": "action_semantics",
            "verdict": "CLOSED_CATALOG_LOCAL_SUPPORT",
            "evidence": {
                "rows": len(action_rows),
                "per_implementation_rows": _per_implementation(action_rows),
                "plans": sorted({_query_plan(row) for row in action_rows}),
                "horizons": sorted({row["query"]["horizon"] for row in action_rows}),
                "primary_scope_rows": sum(row["scope_result"] == "primary_scope" for row in action_rows),
                "abstained_rows": sum(row["prediction"]["abstained"] is True for row in action_rows),
                "query_state_unchanged_rows": sum(row["pre_state_hash"] == row["post_state_hash"] for row in action_rows),
            },
            "claim_boundary": "Known action queries were state-only, side-effect free, and in scope; no unregistered predictive-accuracy threshold is claimed.",
        },
        {
            "attack_class": "query_update_rehydrate_compliance",
            "verdict": "CLOSED_CATALOG_LOCAL_SUPPORT",
            "evidence": {
                "rows": len(compliance_rows),
                "per_implementation_rows": _per_implementation(compliance_rows),
                "all_checks_passed_rows": sum(
                    row["state_hash_before"] == row["state_hash_after"]
                    and row["query_order_diagnosis_equal"] is True
                    and row["query_order_rollout_equal"] is True
                    and row["primary_scope_update_old_hash"] != row["primary_scope_update_new_hash"]
                    and row["primary_scope_update_replay_match"] is True
                    and row["cold_state_hash_equal"] is True
                    and row["cold_diagnosis_equal"] is True
                    and row["cold_rollout_equal"] is True
                    for row in compliance_rows
                ),
                "all_checks_passed": all_compliance_true,
                "cold_rehydrate_scopes": sorted({row["cold_rehydrate_scope"] for row in compliance_rows}),
            },
            "claim_boundary": "Cold rehydrate evidence is limited to a fresh object in the same process with the same static model.",
        },
    ]

    _require(tuple(item["attack_class"] for item in attack_verdicts) == EXPECTED_ATTACK_CLASSES,
             "derived attack verdict order mismatch")
    manifest_raw = (bundle_dir / "manifest.json").read_bytes()
    summary_raw = (bundle_dir / "summary.json").read_bytes()
    commitment_raw = (bundle_dir / "commitment.json").read_bytes()
    amendment_raw = (bundle_dir / "evaluator-amendment.json").read_bytes()
    amendment_chronology = chronology["evaluator_amendment"]
    return {
        "protocol": VERDICT_PROTOCOL,
        "run_binding": {
            "run_id": run_id,
            "bundle_path": f"results/unified_map/redteam_v2/{run_id}",
            "bundle_root": manifest["bundle_root"],
            "bundle_root_definition": manifest["bundle_root_definition"],
            "manifest_receipt": _receipt(manifest_raw),
            "summary_receipt": _receipt(summary_raw),
            "raw_receipts": summary["raw_receipts"],
            "run_git_head": chronology["run_git_head"],
            "pack_digest": summary["pack_digest"],
            "commitment": {
                "blob_receipt": _receipt(commitment_raw),
                "git_commit": chronology["commitment_git_commit"],
                "pre_pack_git_commit": chronology["pre_pack_git_commit"],
            },
            "evaluator_amendment": {
                "blob_receipt": _receipt(amendment_raw),
                "digest": summary["evaluator_amendment_digest"],
                "git_commit": summary["evaluator_amendment_git_commit"],
            },
        },
        "attack_verdicts": attack_verdicts,
        "overall_verdict": {
            "closed_catalog": "CLOSED_CATALOG_LOCAL_SUPPORT",
            "open_world_extensions": "OPEN_WORLD_SCOPE_FAILURE",
            "new_task_sufficiency": "INCONCLUSIVE",
            "state_minimality": "NOT_SUPPORTED",
            "complete_benchmark_claimed": False,
            "clinical_effectiveness_claimed": False,
            "global_optimality_claimed": False,
            "summary": "F18 has bounded local structural/safety support inside the committed synthetic catalog, but it requires extension fit plus visible-history replay for the unseen check/treatment and therefore does not establish an open-world unified map.",
        },
        "evidence_boundary": {
            "source": "one completed source-distinct synthetic red-team-v2 bundle",
            "raw_recomputation": True,
            "candidate_or_benchmark_rerun": False,
            "safe_abstention_is_new_treatment_support": False,
            "new_task_numeric_ordering_is_sufficiency_proof": False,
            "clinical_validity": "not_evaluated",
        },
    }


def write_verdict(bundle_dir: Path, verdict_path: Path) -> dict[str, Any]:
    verdict = derive_verdict(bundle_dir)
    verdict_path.write_bytes(canonical_json_bytes(verdict))
    return verdict


def verify_verdict(bundle_dir: Path, verdict_path: Path) -> dict[str, Any]:
    raw = verdict_path.read_bytes()
    actual = json.loads(raw)
    _require(type(actual) is dict, "verdict must be a JSON object")
    _require(raw == canonical_json_bytes(actual), "verdict is not canonical JSON")
    expected = derive_verdict(bundle_dir)
    _require(actual == expected, "verdict differs from raw-derived verdict")
    return {
        "verified": True,
        "protocol": VERDICT_PROTOCOL,
        "run_id": expected["run_binding"]["run_id"],
        "bundle_root": expected["run_binding"]["bundle_root"],
        "verdict_digest": digest_bytes(raw),
        "verdict_byte_length": len(raw),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--verdict", type=Path, required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        write_verdict(args.bundle, args.verdict)
    print(json.dumps(verify_verdict(args.bundle, args.verdict), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXPECTED_ATTACK_CLASSES",
    "VERDICT_PROTOCOL",
    "VerdictViolation",
    "derive_verdict",
    "verify_verdict",
    "write_verdict",
]
