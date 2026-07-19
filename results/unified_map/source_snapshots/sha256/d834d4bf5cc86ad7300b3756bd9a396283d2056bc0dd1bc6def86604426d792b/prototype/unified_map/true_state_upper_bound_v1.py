"""Publish B01, a privileged true-state/oracle upper bound for frozen v1.

B01 is deliberately not a candidate.  It regenerates the judge-side hidden
state and copies the already-published oracle answers from a verified complete
run.  The result is an exact ceiling for the task metrics, not a learnable map.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .benchmark_v1_contract import DiagnosisPrediction, diagnosis_scores
from .benchmark_v1_runner import (
    DEFAULT_RESULTS_ROOT,
    RUN_MANIFEST_PROTOCOL,
    RUN_PROTOCOL,
    _aggregate_scalar_rows,
    _cross_seed_summary,
    _derived_seed,
    _load_authority,
    _panels,
    _replicate_secret,
    _replicate_summary,
    _repo_root,
    verify_run_bundle,
)
from .canonical import ProtocolViolation, canonical_json_bytes, digest_bytes, digest_json
from .schema import PlanKind
from .worlds.base import WorldSplit


RAW_PROTOCOL = "ucm-benchmark-v1-true-state-upper-bound-raw/1"


def _flatten_numbers(value: Any) -> list[float]:
    if type(value) in {int, float} and type(value) is not bool:
        return [float(value)]
    if type(value) is list:
        rows: list[float] = []
        for item in value:
            rows.extend(_flatten_numbers(item))
        return rows
    if type(value) is dict:
        rows = []
        for key in sorted(value):
            rows.extend(_flatten_numbers(value[key]))
        return rows
    return []


def _exact_episode_row(
    row: dict[str, Any], *, hidden_state: dict[str, Any], invariant_parameters: dict[str, Any]
) -> dict[str, Any]:
    source_summary = row["episode_summary"]
    target = {key: float(value) for key, value in row["diagnosis_target"].items()}
    diagnosis = diagnosis_scores(DiagnosisPrediction(target), target)
    policy_rows: list[dict[str, Any]] = []
    natural_scores: list[dict[str, float]] = []
    intervention_scores: list[dict[str, float]] = []
    by_horizon: dict[int, list[dict[str, Any]]] = {}
    oracle_behavior: list[float] = [*target.values()]
    for source in row["policy_rows"]:
        oracle = source["oracle"]
        signature = [float(value) for value in oracle["signature"]]
        utility = float(oracle["expected_utility"])
        oracle_behavior.extend((*signature, utility))
        scores = {"signature_rmse": 0.0, "utility_absolute_error": 0.0}
        kind = PlanKind(source["policy"]["kind"])
        if kind in {PlanKind.NO_NEW_ACTION, PlanKind.CONTINUE_CURRENT}:
            natural_scores.append(scores)
        else:
            intervention_scores.append(scores)
        exact = {
            **source,
            "prediction": {
                "signature": signature,
                "expected_utility": utility,
                "abstained": False,
            },
            "scores": scores,
        }
        policy_rows.append(exact)
        by_horizon.setdefault(int(source["horizon"]), []).append(exact)

    regret_rows: list[dict[str, Any]] = []
    for horizon, rows in sorted(by_horizon.items()):
        utilities = [float(item["oracle"]["expected_utility"]) for item in rows]
        best = max(utilities)
        selected = utilities.index(best)
        regret_rows.append(
            {
                "horizon": horizon,
                "selected_policy_index": int(rows[selected]["policy_index"]),
                "oracle_best_utility": best,
                "selected_oracle_utility": best,
                "regret": 0.0,
            }
        )

    state_payload = {
        "protocol": "ucm-b01-privileged-true-state-oracle/1",
        "hidden_state_at_cut": hidden_state,
        "invariant_parameters": invariant_parameters,
        "diagnostic_truth": target,
        "oracle_behavior": oracle_behavior,
    }
    state_bytes = canonical_json_bytes(state_payload)
    state_hash = digest_json(state_payload)
    unknown_metrics: dict[str, float] = {}
    if "unknown" in target:
        unknown_metrics = {
            "unknown_brier": 0.0,
            "known_coverage": float(target["unknown"] < 0.5),
            "unsafe_non_abstain": 0.0,
        }
    summary = {
        "world_slot": source_summary["world_slot"],
        "panel_id": source_summary["panel_id"],
        "replicate_id": source_summary["replicate_id"],
        "episode_index": source_summary["episode_index"],
        "state_hash": state_hash,
        "state_bytes": len(state_bytes),
        "state_dimension": max(1, len(_flatten_numbers(state_payload))),
        "compactness_class": "privileged_true_state_upper_bound",
        "initialize_ms": 0.0,
        "head_ms": 0.0,
        "diagnosis": diagnosis,
        "natural": _aggregate_scalar_rows(natural_scores),
        "intervention": _aggregate_scalar_rows(intervention_scores),
        "regret": _aggregate_scalar_rows(regret_rows),
        "ood": unknown_metrics,
        "update_replay_match": True,
        "query_order_pure": True,
    }
    for policy_row in policy_rows:
        policy_row["state_hash"] = state_hash
    return {
        "protocol": RAW_PROTOCOL,
        "episode_summary": summary,
        "diagnosis_prediction": target,
        "diagnosis_target": target,
        "policy_rows": policy_rows,
        "privileged": True,
        "eligibility": "upper_bound_only",
    }


def _exact_pair_row(row: dict[str, Any], replicate_id: str) -> dict[str, Any]:
    identity = {
        key: row[key]
        for key in ("world_slot", "panel_id", "probe_id", "probe_index", "group_index")
    }
    left = digest_json(["B01", replicate_id, identity, "left"])
    right = left if float(row["oracle_distance"]) == 0.0 else digest_json(
        ["B01", replicate_id, identity, "right"]
    )
    return {
        **identity,
        "left_state_hash": left,
        "right_state_hash": right,
        "candidate_distance": float(row["oracle_distance"]),
        "oracle_distance": float(row["oracle_distance"]),
        "dangerous_collision": False,
        "false_split": False,
    }


def publish_upper_bound(
    *, reference_run: Path, secret_path: Path, results_root: Path | None = None
) -> Path:
    root = _repo_root()
    results_root = results_root or root / DEFAULT_RESULTS_ROOT
    reference = verify_run_bundle(reference_run)
    if not reference["config"]["complete_benchmark"]:
        raise ProtocolViolation("B01 requires a verified complete reference run")
    freeze, secret = _load_authority(
        root / "research/unified_map/BENCHMARK_V1_FREEZE.json", secret_path
    )
    run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-EXP-036-{uuid.uuid4().hex[:10]}"
    temporary = results_root / f".{run_id}.tmp"
    final = results_root / run_id
    temporary.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    try:
        source_episode_rows = [
            json.loads(line)
            for line in (reference_run / reference["raw_episode_file"])
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        source_pair_rows = [
            json.loads(line)
            for line in (reference_run / reference["raw_pair_file"])
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        pair_cursor = 0
        replicate_results: list[dict[str, Any]] = []
        raw_episode_path = temporary / "raw-episodes.jsonl"
        raw_pair_path = temporary / "raw-pairs.jsonl"
        with raw_episode_path.open("wb") as episode_writer, raw_pair_path.open(
            "wb"
        ) as pair_writer:
            for source_replicate in reference["replicates"]:
                replicate_id = source_replicate["replicate_id"]
                seed_row = _replicate_secret(secret, replicate_id)
                selected = [
                    row
                    for row in source_episode_rows
                    if row["episode_summary"]["replicate_id"] == replicate_id
                ]
                exact_episode_rows: list[dict[str, Any]] = []
                worlds = {
                    (slot, panel.panel_id): world
                    for slot, panel, world in _panels(tuple(reference["config"]["world_slots"]))
                }
                for row in selected:
                    summary = row["episode_summary"]
                    slot = summary["world_slot"]
                    panel_id = summary["panel_id"]
                    world = worlds[(slot, panel_id)]
                    generator_seed = _derived_seed(
                        seed_row["sealed_test_root_seed"], slot, panel_id, "population"
                    )
                    episode = world.generate_episode(
                        WorldSplit.SEALED_TEST,
                        generator_seed,
                        int(summary["episode_index"]),
                    )
                    if canonical_json_bytes(episode.diagnostic_target) != canonical_json_bytes(
                        row["diagnosis_target"]
                    ):
                        raise ProtocolViolation("B01 regenerated episode drifted")
                    exact = _exact_episode_row(
                        row,
                        hidden_state=episode.hidden_state_at_cut,
                        invariant_parameters=episode.invariant_parameters,
                    )
                    exact_episode_rows.append(exact["episode_summary"])
                    episode_writer.write(canonical_json_bytes(exact))

                pair_count = int(source_replicate["summary"]["pair_probe_count"])
                source_pairs = source_pair_rows[pair_cursor : pair_cursor + pair_count]
                pair_cursor += pair_count
                exact_pairs = [_exact_pair_row(row, replicate_id) for row in source_pairs]
                for row in exact_pairs:
                    pair_writer.write(canonical_json_bytes(row))
                replicate_results.append(
                    {
                        "replicate_id": replicate_id,
                        "model_seed": source_replicate["model_seed"],
                        "seed_commitment": source_replicate["seed_commitment"],
                        "fit_seconds": 0.0,
                        "training_record_count": source_replicate[
                            "training_record_count"
                        ],
                        "model_summary": {
                            "baseline_id": "B01",
                            "family_id": "B01-privileged-true-state-oracle",
                            "eligibility": "upper_bound_only",
                            "privileged": True,
                            "parameter_count": 0,
                        },
                        "summary": _replicate_summary(exact_episode_rows, exact_pairs),
                    }
                )
        if pair_cursor != len(source_pair_rows):
            raise ProtocolViolation("B01 pair ledger did not close")

        source_path = Path(__file__).resolve()
        source_raw = source_path.read_bytes()
        reference_manifest = json.loads((reference_run / "manifest.json").read_text())
        config = {**reference["config"], "experiment_id": "EXP-036", "family_code": "B01"}
        report = {
            "protocol": RUN_PROTOCOL,
            "run_id": run_id,
            "created_at_utc": datetime.now(UTC).isoformat(),
            "freeze_root": freeze["freeze_root"],
            "benchmark_status": freeze["status"],
            "config": config,
            "candidate_eligibility": "upper_bound_only",
            "shared_state_compliant_by_design": True,
            "privileged": True,
            "source_binding": {
                "files": [
                    {
                        "relative_path": "prototype/unified_map/true_state_upper_bound_v1.py",
                        "byte_length": len(source_raw),
                        "sha256": digest_bytes(source_raw),
                    }
                ],
                "source_digest": digest_bytes(source_raw),
                "reference_run_id": reference["run_id"],
                "reference_bundle_root": reference_manifest["bundle_root"],
            },
            "replicates": replicate_results,
            "cross_seed_summary": _cross_seed_summary(replicate_results),
            "hard_failures": {
                "dangerous_collision": 0,
                "update_inconsistency": 0,
                "query_order_impurity": 0,
                "unsafe_forced_known_ood": 0,
            },
            "hard_gate_pass": True,
            "wall_seconds": time.perf_counter() - started,
            "raw_episode_file": raw_episode_path.name,
            "raw_pair_file": raw_pair_path.name,
            "seed_preimages_published": False,
            "claim_boundary": {
                "synthetic_only": True,
                "clinical_validity_claimed": False,
                "complete_benchmark": True,
                "screening_run": False,
                "upper_bound_only": True,
                "learnable_candidate": False,
            },
        }
        summary_path = temporary / "summary.json"
        summary_path.write_bytes(canonical_json_bytes(report))
        manifest = {
            "protocol": RUN_MANIFEST_PROTOCOL,
            "run_id": run_id,
            "freeze_root": freeze["freeze_root"],
            "files": [
                {
                    "name": path.name,
                    "byte_length": path.stat().st_size,
                    "sha256": digest_bytes(path.read_bytes()),
                }
                for path in (raw_episode_path, raw_pair_path, summary_path)
            ],
        }
        manifest["bundle_root"] = digest_json(manifest)
        (temporary / "manifest.json").write_bytes(canonical_json_bytes(manifest))
        os.replace(temporary, final)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return final


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish frozen-v1 B01 upper bound")
    parser.add_argument("--reference-run", type=Path, required=True)
    parser.add_argument("--secret", type=Path, required=True)
    args = parser.parse_args()
    print(publish_upper_bound(reference_run=args.reference_run, secret_path=args.secret))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

