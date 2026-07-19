"""Verifier for preregistration-bound UCM experiment decisions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .benchmark_v1_runner import verify_run_bundle
from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes


DECISION_PROTOCOL = "ucm-experiment-decision/1"


def _canonical_object(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation(f"{label} cannot be read as JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise ProtocolViolation(f"{label} must be a canonical JSON object")
    return value, raw


def _git_object_bytes(repo_root: Path, commit: str, relative_path: str) -> bytes:
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative_path}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ProtocolViolation("decision preregistration Git object is unavailable")
    return result.stdout


def _planned_config_comparison(
    preregistration: dict[str, Any], summary: dict[str, Any]
) -> dict[str, Any]:
    planned = preregistration["planned_screen_config"]
    actual = summary["config"]
    seed = summary["seed_authority"]
    return {
        "pair_probe_limit_per_declaration": {
            "planned": planned["pair_probe_limit_per_declaration"],
            "actual": actual["pair_probe_limit_per_declaration"],
            "match": planned["pair_probe_limit_per_declaration"]
            == actual["pair_probe_limit_per_declaration"],
        },
        "replicate_ids": {
            "planned": planned["replicate_ids"],
            "actual": actual["replicate_ids"],
            "match": planned["replicate_ids"] == actual["replicate_ids"],
        },
        "sealed_test_episodes_per_panel": {
            "planned": planned["sealed_test_episodes_per_panel"],
            "actual_field": "test_episodes_per_panel",
            "actual": actual["test_episodes_per_panel"],
            "match": planned["sealed_test_episodes_per_panel"]
            == actual["test_episodes_per_panel"],
        },
        "seed_authority": {
            "planned": planned["seed_authority"],
            "actual": {
                "authority_kind": seed["authority_kind"],
                "authority_schema_version": seed["authority_schema_version"],
                "seed_preimages_published": seed["seed_preimages_published"],
            },
            "match": seed["authority_kind"] == "public_seed_reveal"
            and seed["seed_preimages_published"] is True,
        },
        "train_episodes_per_panel": {
            "planned": planned["train_episodes_per_panel"],
            "actual": actual["train_episodes_per_panel"],
            "match": planned["train_episodes_per_panel"]
            == actual["train_episodes_per_panel"],
        },
        "validation_episodes_per_panel": {
            "planned": planned["validation_episodes_per_panel"],
            "actual": actual["validation_episodes_per_panel"],
            "match": planned["validation_episodes_per_panel"]
            == actual["validation_episodes_per_panel"],
        },
        "world_slots": {
            "planned": planned["world_slots"],
            "actual": actual["world_slots"],
            "match": planned["world_slots"] == actual["world_slots"],
        },
    }


def verify_experiment_decision(
    decision_path: Path, *, repo_root: Path
) -> dict[str, Any]:
    """Rebind a decision to its committed preregistration and run bundle."""

    repo_root = repo_root.resolve()
    decision, _ = _canonical_object(decision_path, "experiment decision")
    if decision.get("protocol") != DECISION_PROTOCOL:
        raise ProtocolViolation("experiment decision protocol mismatch")
    if decision.get("decision") != "ABANDON":
        raise ProtocolViolation("EXP-038 decision must preserve its preregistered abandonment")

    prereg_binding = decision["preregistration_binding"]
    prereg_raw = _git_object_bytes(
        repo_root,
        prereg_binding["commit"],
        prereg_binding["relative_path"],
    )
    if (
        len(prereg_raw) != prereg_binding["byte_length"]
        or digest_bytes(prereg_raw) != prereg_binding["sha256"]
    ):
        raise ProtocolViolation("committed preregistration binding drifted")
    try:
        preregistration = json.loads(prereg_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolViolation("committed preregistration is not JSON") from exc
    if canonical_json_bytes(preregistration) != prereg_raw:
        raise ProtocolViolation("committed preregistration is not canonical")
    live_prereg = repo_root / prereg_binding["relative_path"]
    if digest_bytes(live_prereg.read_bytes()) != prereg_binding["sha256"]:
        raise ProtocolViolation("live preregistration differs from bound commit")

    result = decision["result_binding"]
    run_path = repo_root / result["relative_path"]
    summary = verify_run_bundle(run_path)
    manifest, manifest_raw = _canonical_object(run_path / "manifest.json", "run manifest")
    summary_wire, summary_raw = _canonical_object(run_path / "summary.json", "run summary")
    if summary_wire != summary:
        raise ProtocolViolation("run verifier/summary disagreement")
    if (
        summary["run_id"] != result["run_id"]
        or manifest["bundle_root"] != result["bundle_root"]
        or digest_bytes(manifest_raw) != result["manifest_sha256"]
        or digest_bytes(summary_raw) != result["summary_sha256"]
        or summary["source_binding"]["source_digest"] != result["source_digest"]
    ):
        raise ProtocolViolation("experiment result binding drifted")

    if preregistration["experiment_id"] != decision["experiment_id"]:
        raise ProtocolViolation("decision/preregistration experiment mismatch")
    if summary["config"]["experiment_id"] != decision["experiment_id"]:
        raise ProtocolViolation("decision/run experiment mismatch")
    if summary["replicates"][0]["model_summary"]["candidate_id"] != preregistration[
        "candidate_id"
    ]:
        raise ProtocolViolation("candidate identity drifted after preregistration")
    bound_candidate_source = next(
        row
        for row in summary["source_binding"]["files"]
        if row["relative_path"] == preregistration["source_binding"]["relative_path"]
    )
    if bound_candidate_source != preregistration["source_binding"]:
        raise ProtocolViolation("candidate source differs from preregistration")

    comparison = _planned_config_comparison(preregistration, summary)
    if comparison != decision["planned_config_comparison"]:
        raise ProtocolViolation("planned/actual configuration comparison drifted")
    if any(row["match"] is not True for row in comparison.values()):
        raise ProtocolViolation("run configuration did not match preregistration")

    hard_failures = summary["hard_failures"]
    if (
        summary["hard_gate_pass"] is not False
        or sum(hard_failures.values()) <= 0
        or hard_failures != decision["observed_result"]["hard_failures"]
        or decision["observed_result"]["hard_gate_pass"] is not False
    ):
        raise ProtocolViolation("abandonment is not supported by the bound hard gate")
    if decision["legal_policy_totality_fix"]["status"] != "SUPPORTED_IN_SCREEN":
        raise ProtocolViolation("legal-policy totality result was not preserved")
    if decision["candidate_disposition"] != "DO_NOT_KEEP_OR_REFINE":
        raise ProtocolViolation("candidate disposition contradicts abandonment")
    return decision


__all__ = ["DECISION_PROTOCOL", "verify_experiment_decision"]
